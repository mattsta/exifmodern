"""Source-grounded, non-mutating MRC metadata transaction plans.

The planner mirrors ExifTool's MRC reader: it requires a 1024-byte header,
validates axis, MAP, and machine-stamp bytes, decodes the fixed little-endian
header fields, optionally plans FEI1/FEI2 extended header frame reads, and
preserves the image volume bytes. It never rewrites MRC data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from struct import unpack_from
from typing import Literal

MRC_HEADER_SIZE = 1024
MRC_PM_SOURCE_PATH = "lib/Image/ExifTool/MRC.pm"

type MrcPlanStatus = Literal["planned", "unsupported"]
type MrcByteOrder = Literal["little"]
type MrcRewriteTarget = Literal[
    "header",
    "extended_header",
    "image_volume",
    "labels",
    "statistics",
]
type MrcRewriteOperation = Literal["insert", "replace", "delete"]
type MrcActionKind = Literal[
    "validate_header",
    "set_little_endian",
    "decode_dimensions",
    "decode_mode",
    "decode_cell",
    "decode_axes",
    "decode_statistics",
    "plan_fei_extended_header",
    "preserve_extended_header",
    "preserve_image_volume",
    "block_requested_rewrite",
]
type MrcBlockerCode = Literal[
    "truncated_mrc_header",
    "invalid_mrc_header_gate",
    "truncated_extended_header_size",
    "corrupted_extended_header",
    "truncated_fei_extended_header_frame",
    "truncated_image_volume",
    "rewrite_requested_requires_mrc_writer",
    "non_mutating_plan_requires_explicit_emission",
]
type MrcExtendedHeaderRoute = Literal[
    "none",
    "fei12_first_frame",
    "fei12_all_frames",
    "opaque_preserve",
]
type MrcFeiValueFormat = Literal[
    "bitmask",
    "bool8",
    "double",
    "int32u",
    "string16",
    "timestamp_ole",
]

MRC_DESCRIPTION_SOURCE = "mrc_description"
MRC_MAIN_TABLE_SOURCE = "mrc_main_table"
MRC_FEI12_TABLE_SOURCE = "mrc_fei12_table"
MRC_HEADER_GATE_SOURCE = "mrc_header_gate"
MRC_EXTENDED_HEADER_SOURCE = "mrc_extended_header"

MRC_TRANSACTION_SOURCES = (
    MRC_DESCRIPTION_SOURCE,
    MRC_MAIN_TABLE_SOURCE,
    MRC_FEI12_TABLE_SOURCE,
    MRC_HEADER_GATE_SOURCE,
    MRC_EXTENDED_HEADER_SOURCE,
)

MRC_MODE_DESCRIPTIONS: dict[int, str] = {
    0: "8-bit signed integer",
    1: "16-bit signed integer",
    2: "32-bit signed real",
    3: "complex 16-bit integer",
    4: "complex 32-bit real",
    6: "16-bit unsigned integer",
}
MRC_MODE_BYTES_PER_VOXEL: dict[int, int] = {
    0: 1,
    1: 2,
    2: 4,
    3: 4,
    4: 8,
    6: 2,
}
MRC_AXIS_LABELS: dict[int, str] = {1: "X", 2: "Y", 3: "Z"}
MRC_ACCEPTED_MACHINE_STAMPS = (b"DD\x00\x00", b"DA\x00\x00", b"\x11\x11\x00\x00")


@dataclass(frozen=True)
class MrcRewriteRequest:
    target: MrcRewriteTarget
    operation: MrcRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class MrcTransactionBlocker:
    code: MrcBlockerCode
    reason: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcOutputEmissionGate:
    code: MrcBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcHeaderValidationPlan:
    header_range: tuple[int, int]
    axes_raw: tuple[int, int, int] | None
    map_id: bytes
    machine_stamp: bytes
    mrc_version: int | None
    byte_order: MrcByteOrder | None
    reason: MrcBlockerCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class MrcDimensionPlan:
    image_width: int
    image_height: int
    image_depth: int
    start_point: tuple[int, int, int]
    grid_size: tuple[int, int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcModePlan:
    mode_code: int
    description: str | None
    bytes_per_voxel: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcCellPlan:
    cell_size_angstroms: tuple[float, float, float]
    cell_angles_degrees: tuple[float, float, float]
    origin: tuple[float, float, float]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcAxisPlan:
    width_axis: int
    height_axis: int
    depth_axis: int
    width_axis_label: str
    height_axis_label: str
    depth_axis_label: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcStatisticsPlan:
    density_min: float
    density_max: float
    density_mean: float
    rms_deviation: float
    space_group_number: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcLabelPlan:
    number_of_labels: int
    labels: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcExtendedHeaderPlan:
    declared_size: int
    header_type: str
    route: MrcExtendedHeaderRoute
    metadata_size: int | None
    frames_planned: int
    frame_ranges: tuple[tuple[int, int], ...]
    preserve_range: tuple[int, int] | None
    blockers: tuple[MrcTransactionBlocker, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcFeiFieldDefinition:
    tag_id: int
    name: str
    offset: int
    value_format: MrcFeiValueFormat
    bitmask_offset: int | None = None
    bitmask: int | None = None
    print_map: dict[int, str] | None = None


@dataclass(frozen=True)
class MrcFeiTagPlan:
    name: str
    tag_id: int
    value: str | int | float
    frame_index: int
    family_1_group: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcImageVolumePreservationPlan:
    byte_range: tuple[int, int]
    expected_byte_count: int | None
    available_byte_count: int
    complete: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcActionPlan:
    kind: MrcActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MrcMetadataTransactionPlan:
    status: MrcPlanStatus
    source_data: bytes
    header_validation: MrcHeaderValidationPlan
    dimensions: MrcDimensionPlan | None
    mode: MrcModePlan | None
    cell: MrcCellPlan | None
    axes: MrcAxisPlan | None
    statistics: MrcStatisticsPlan | None
    labels: MrcLabelPlan | None
    extended_header: MrcExtendedHeaderPlan | None
    fei_tags: tuple[MrcFeiTagPlan, ...]
    image_volume: MrcImageVolumePreservationPlan | None
    rewrite_requests: tuple[MrcRewriteRequest, ...]
    actions: tuple[MrcActionPlan, ...]
    blockers: tuple[MrcTransactionBlocker, ...]
    output_emission_gates: tuple[MrcOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"MRC metadata transaction output is gated: {gate_codes}")
        return self.source_data


def build_mrc_metadata_transaction_plan(
    mrc_data: bytes,
    *,
    rewrite_requests: tuple[MrcRewriteRequest, ...] = (),
    extract_embedded: bool = False,
    allow_output_emission: bool = False,
) -> MrcMetadataTransactionPlan:
    """Build a source-backed MRC metadata transaction plan."""

    blockers: list[MrcTransactionBlocker] = []
    actions: list[MrcActionPlan] = []
    header = _build_header_validation(mrc_data, blockers, actions)
    if not header.is_exiftool_accepted:
        return _finish_plan(
            status="unsupported",
            source_data=mrc_data,
            header_validation=header,
            dimensions=None,
            mode=None,
            cell=None,
            axes=None,
            statistics=None,
            labels=None,
            extended_header=None,
            fei_tags=(),
            image_volume=None,
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            blockers=tuple(blockers),
            allow_output_emission=allow_output_emission,
        )

    dimensions = _build_dimensions(mrc_data, actions)
    mode = _build_mode(mrc_data, actions)
    cell = _build_cell(mrc_data, actions)
    axes = _build_axes(mrc_data, actions)
    statistics = _build_statistics(mrc_data, actions)
    labels = _build_labels(mrc_data)
    extended_header = _build_extended_header(
        mrc_data,
        dimensions,
        extract_embedded,
        blockers,
        actions,
    )
    fei_tags = _build_fei_tags(mrc_data, extended_header)
    image_volume = _build_image_volume(
        mrc_data,
        dimensions,
        mode,
        extended_header,
        blockers,
        actions,
    )

    for request in rewrite_requests:
        blocker = MrcTransactionBlocker(
            code="rewrite_requested_requires_mrc_writer",
            reason=(
                f"MRC {request.operation} for {request.target} was requested, "
                "but ExifTool's MRC module is read-only."
            ),
            byte_range=None,
            evidence_ids=(MRC_DESCRIPTION_SOURCE,),
        )
        blockers.append(blocker)
        actions.append(
            MrcActionPlan(
                kind="block_requested_rewrite",
                target=request.target,
                byte_range=None,
                reason="MRC rewrites are blocked until a source-backed writer exists.",
                evidence_ids=(MRC_DESCRIPTION_SOURCE,),
            )
        )

    structural_codes = {
        "truncated_mrc_header",
        "invalid_mrc_header_gate",
        "truncated_extended_header_size",
        "corrupted_extended_header",
        "truncated_fei_extended_header_frame",
        "truncated_image_volume",
    }
    status: MrcPlanStatus = (
        "unsupported"
        if any(blocker.code in structural_codes for blocker in blockers)
        else "planned"
    )
    return _finish_plan(
        status=status,
        source_data=mrc_data,
        header_validation=header,
        dimensions=dimensions,
        mode=mode,
        cell=cell,
        axes=axes,
        statistics=statistics,
        labels=labels,
        extended_header=extended_header,
        fei_tags=fei_tags,
        image_volume=image_volume,
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        blockers=tuple(blockers),
        allow_output_emission=allow_output_emission,
    )


def _build_header_validation(
    mrc_data: bytes,
    blockers: list[MrcTransactionBlocker],
    actions: list[MrcActionPlan],
) -> MrcHeaderValidationPlan:
    if len(mrc_data) < MRC_HEADER_SIZE:
        blockers.append(
            MrcTransactionBlocker(
                code="truncated_mrc_header",
                reason="ExifTool's MRC reader requires a complete 1024-byte header.",
                byte_range=(0, len(mrc_data)),
                evidence_ids=(MRC_HEADER_GATE_SOURCE,),
            )
        )
        return MrcHeaderValidationPlan(
            header_range=(0, len(mrc_data)),
            axes_raw=None,
            map_id=mrc_data[208:212],
            machine_stamp=mrc_data[212:216],
            mrc_version=None,
            byte_order=None,
            reason="truncated_mrc_header",
            evidence_ids=(MRC_HEADER_GATE_SOURCE,),
        )

    axes_raw = (_u32(mrc_data, 64), _u32(mrc_data, 68), _u32(mrc_data, 72))
    map_id = mrc_data[208:212]
    machine_stamp = mrc_data[212:216]
    mrc_version = _u32(mrc_data, 108)
    is_valid = (
        all(axis in MRC_AXIS_LABELS for axis in axes_raw)
        and map_id in (b"MAP\x00", b"MAP ")
        and machine_stamp in MRC_ACCEPTED_MACHINE_STAMPS
    )
    if not is_valid:
        blockers.append(
            MrcTransactionBlocker(
                code="invalid_mrc_header_gate",
                reason="Input failed ExifTool's MRC axes, MAP, or machine-stamp gate.",
                byte_range=(64, 216),
                evidence_ids=(MRC_HEADER_GATE_SOURCE,),
            )
        )
        return MrcHeaderValidationPlan(
            header_range=(0, MRC_HEADER_SIZE),
            axes_raw=axes_raw,
            map_id=map_id,
            machine_stamp=machine_stamp,
            mrc_version=mrc_version,
            byte_order=None,
            reason="invalid_mrc_header_gate",
            evidence_ids=(MRC_HEADER_GATE_SOURCE,),
        )

    actions.append(
        MrcActionPlan(
            kind="validate_header",
            target="MRC",
            byte_range=(0, MRC_HEADER_SIZE),
            reason="Input satisfied ExifTool's MRC header gate.",
            evidence_ids=(MRC_HEADER_GATE_SOURCE,),
        )
    )
    actions.append(
        MrcActionPlan(
            kind="set_little_endian",
            target="II",
            byte_range=(0, MRC_HEADER_SIZE),
            reason="ExifTool sets little-endian order before processing Main.",
            evidence_ids=(MRC_HEADER_GATE_SOURCE,),
        )
    )
    return MrcHeaderValidationPlan(
        header_range=(0, MRC_HEADER_SIZE),
        axes_raw=axes_raw,
        map_id=map_id,
        machine_stamp=machine_stamp,
        mrc_version=mrc_version,
        byte_order="little",
        reason=None,
        evidence_ids=(MRC_HEADER_GATE_SOURCE,),
    )


def _build_dimensions(mrc_data: bytes, actions: list[MrcActionPlan]) -> MrcDimensionPlan:
    plan = MrcDimensionPlan(
        image_width=_u32(mrc_data, 0),
        image_height=_u32(mrc_data, 4),
        image_depth=_u32(mrc_data, 8),
        start_point=(_u32(mrc_data, 16), _u32(mrc_data, 20), _u32(mrc_data, 24)),
        grid_size=(_u32(mrc_data, 28), _u32(mrc_data, 32), _u32(mrc_data, 36)),
        evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
    )
    actions.append(
        MrcActionPlan(
            kind="decode_dimensions",
            target="ImageWidth/ImageHeight/ImageDepth",
            byte_range=(0, 40),
            reason="Decoded ExifTool Main table dimension, start, and grid fields.",
            evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
        )
    )
    return plan


def _build_mode(mrc_data: bytes, actions: list[MrcActionPlan]) -> MrcModePlan:
    mode_code = _u32(mrc_data, 12)
    plan = MrcModePlan(
        mode_code=mode_code,
        description=MRC_MODE_DESCRIPTIONS.get(mode_code),
        bytes_per_voxel=MRC_MODE_BYTES_PER_VOXEL.get(mode_code),
        evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
    )
    actions.append(
        MrcActionPlan(
            kind="decode_mode",
            target="ImageMode",
            byte_range=(12, 16),
            reason="Decoded ExifTool Main table ImageMode field.",
            evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
        )
    )
    return plan


def _build_cell(mrc_data: bytes, actions: list[MrcActionPlan]) -> MrcCellPlan:
    plan = MrcCellPlan(
        cell_size_angstroms=(_f32(mrc_data, 40), _f32(mrc_data, 44), _f32(mrc_data, 48)),
        cell_angles_degrees=(_f32(mrc_data, 52), _f32(mrc_data, 56), _f32(mrc_data, 60)),
        origin=(_f32(mrc_data, 196), _f32(mrc_data, 200), _f32(mrc_data, 204)),
        evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
    )
    actions.append(
        MrcActionPlan(
            kind="decode_cell",
            target="CellWidth/CellHeight/CellDepth",
            byte_range=(40, 208),
            reason="Decoded ExifTool Main table cell geometry and origin fields.",
            evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
        )
    )
    return plan


def _build_axes(mrc_data: bytes, actions: list[MrcActionPlan]) -> MrcAxisPlan:
    width_axis = _u32(mrc_data, 64)
    height_axis = _u32(mrc_data, 68)
    depth_axis = _u32(mrc_data, 72)
    plan = MrcAxisPlan(
        width_axis=width_axis,
        height_axis=height_axis,
        depth_axis=depth_axis,
        width_axis_label=MRC_AXIS_LABELS[width_axis],
        height_axis_label=MRC_AXIS_LABELS[height_axis],
        depth_axis_label=MRC_AXIS_LABELS[depth_axis],
        evidence_ids=(MRC_MAIN_TABLE_SOURCE, MRC_HEADER_GATE_SOURCE),
    )
    actions.append(
        MrcActionPlan(
            kind="decode_axes",
            target="ImageWidthAxis/ImageHeightAxis/ImageDepthAxis",
            byte_range=(64, 76),
            reason="Decoded ExifTool Main table axis mapping fields.",
            evidence_ids=(MRC_MAIN_TABLE_SOURCE, MRC_HEADER_GATE_SOURCE),
        )
    )
    return plan


def _build_statistics(mrc_data: bytes, actions: list[MrcActionPlan]) -> MrcStatisticsPlan:
    plan = MrcStatisticsPlan(
        density_min=_f32(mrc_data, 76),
        density_max=_f32(mrc_data, 80),
        density_mean=_f32(mrc_data, 84),
        rms_deviation=_f32(mrc_data, 216),
        space_group_number=_u32(mrc_data, 88),
        evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
    )
    actions.append(
        MrcActionPlan(
            kind="decode_statistics",
            target="DensityMin/DensityMax/DensityMean/RMSDeviation",
            byte_range=(76, 220),
            reason="Decoded ExifTool Main table density, RMS, and space group fields.",
            evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
        )
    )
    return plan


def _build_labels(mrc_data: bytes) -> MrcLabelPlan:
    raw_count = _u32(mrc_data, 220)
    label_count = min(raw_count, 10)
    labels: list[str] = []
    for index in range(label_count):
        start = 224 + index * 80
        labels.append(mrc_data[start : start + 80].split(b"\x00", 1)[0].decode("latin-1").rstrip())
    return MrcLabelPlan(
        number_of_labels=raw_count,
        labels=tuple(labels),
        evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
    )


def _build_extended_header(
    mrc_data: bytes,
    dimensions: MrcDimensionPlan,
    extract_embedded: bool,
    blockers: list[MrcTransactionBlocker],
    actions: list[MrcActionPlan],
) -> MrcExtendedHeaderPlan:
    declared_size = _u32(mrc_data, 92)
    header_type = mrc_data[104:108].decode("latin-1").rstrip("\x00 ")
    if declared_size == 0:
        return MrcExtendedHeaderPlan(
            declared_size=0,
            header_type=header_type,
            route="none",
            metadata_size=None,
            frames_planned=0,
            frame_ranges=(),
            preserve_range=None,
            blockers=(),
            evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
        )

    preserve_range = (MRC_HEADER_SIZE, MRC_HEADER_SIZE + declared_size)
    if not header_type.startswith(("FEI1", "FEI2")):
        actions.append(
            MrcActionPlan(
                kind="preserve_extended_header",
                target=header_type or "opaque",
                byte_range=preserve_range,
                reason=(
                    "ExifTool only decodes FEI1/FEI2 extended headers; other bytes are preserved."
                ),
                evidence_ids=(MRC_EXTENDED_HEADER_SOURCE,),
            )
        )
        return MrcExtendedHeaderPlan(
            declared_size=declared_size,
            header_type=header_type,
            route="opaque_preserve",
            metadata_size=None,
            frames_planned=0,
            frame_ranges=(),
            preserve_range=preserve_range,
            blockers=(),
            evidence_ids=(MRC_MAIN_TABLE_SOURCE, MRC_EXTENDED_HEADER_SOURCE),
        )

    local_blockers: list[MrcTransactionBlocker] = []
    if len(mrc_data) < MRC_HEADER_SIZE + 4:
        blocker = MrcTransactionBlocker(
            code="truncated_extended_header_size",
            reason="ExifTool reads four bytes to obtain FEI metadata size.",
            byte_range=(MRC_HEADER_SIZE, len(mrc_data)),
            evidence_ids=(MRC_EXTENDED_HEADER_SOURCE,),
        )
        blockers.append(blocker)
        local_blockers.append(blocker)
        metadata_size = None
        frame_ranges: tuple[tuple[int, int], ...] = ()
        frames_planned = 0
    else:
        metadata_size = _u32(mrc_data, MRC_HEADER_SIZE)
        if metadata_size * dimensions.image_depth > declared_size:
            blocker = MrcTransactionBlocker(
                code="corrupted_extended_header",
                reason="FEI metadata size times ImageDepth exceeds ExtendedHeaderSize.",
                byte_range=preserve_range,
                evidence_ids=(MRC_EXTENDED_HEADER_SOURCE,),
            )
            blockers.append(blocker)
            local_blockers.append(blocker)
            frame_ranges = ()
            frames_planned = 0
        else:
            frame_count = (
                dimensions.image_depth if extract_embedded else min(dimensions.image_depth, 1)
            )
            ranges: list[tuple[int, int]] = []
            for index in range(frame_count):
                start = MRC_HEADER_SIZE + index * metadata_size
                end = start + metadata_size
                if end > len(mrc_data):
                    blocker = MrcTransactionBlocker(
                        code="truncated_fei_extended_header_frame",
                        reason=f"FEI extended header frame {index} is truncated.",
                        byte_range=(start, len(mrc_data)),
                        evidence_ids=(MRC_EXTENDED_HEADER_SOURCE,),
                    )
                    blockers.append(blocker)
                    local_blockers.append(blocker)
                    break
                ranges.append((start, end))
            frame_ranges = tuple(ranges)
            frames_planned = len(frame_ranges)

    route: MrcExtendedHeaderRoute = "fei12_all_frames" if extract_embedded else "fei12_first_frame"
    actions.append(
        MrcActionPlan(
            kind="plan_fei_extended_header",
            target=header_type,
            byte_range=preserve_range,
            reason="Planned ExifTool FEI1/FEI2 extended header frame processing.",
            evidence_ids=(MRC_EXTENDED_HEADER_SOURCE, MRC_FEI12_TABLE_SOURCE),
        )
    )
    return MrcExtendedHeaderPlan(
        declared_size=declared_size,
        header_type=header_type,
        route=route,
        metadata_size=metadata_size,
        frames_planned=frames_planned,
        frame_ranges=frame_ranges,
        preserve_range=preserve_range,
        blockers=tuple(local_blockers),
        evidence_ids=(
            MRC_MAIN_TABLE_SOURCE,
            MRC_EXTENDED_HEADER_SOURCE,
            MRC_FEI12_TABLE_SOURCE,
        ),
    )


def _build_image_volume(
    mrc_data: bytes,
    dimensions: MrcDimensionPlan,
    mode: MrcModePlan,
    extended_header: MrcExtendedHeaderPlan,
    blockers: list[MrcTransactionBlocker],
    actions: list[MrcActionPlan],
) -> MrcImageVolumePreservationPlan:
    start = MRC_HEADER_SIZE + extended_header.declared_size
    available = max(0, len(mrc_data) - start)
    expected = None
    if mode.bytes_per_voxel is not None:
        expected = (
            dimensions.image_width
            * dimensions.image_height
            * dimensions.image_depth
            * mode.bytes_per_voxel
        )
    complete = expected is None or available >= expected
    end = len(mrc_data) if expected is None else min(len(mrc_data), start + expected)
    actions.append(
        MrcActionPlan(
            kind="preserve_image_volume",
            target="image_volume",
            byte_range=(start, end),
            reason=(
                "ExifTool's MRC reader extracts metadata from the header and FEI extended "
                "header without requiring the complete image volume bytes."
            ),
            evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
        )
    )
    return MrcImageVolumePreservationPlan(
        byte_range=(start, end),
        expected_byte_count=expected,
        available_byte_count=available,
        complete=complete,
        evidence_ids=(MRC_MAIN_TABLE_SOURCE,),
    )


def _finish_plan(
    *,
    status: MrcPlanStatus,
    source_data: bytes,
    header_validation: MrcHeaderValidationPlan,
    dimensions: MrcDimensionPlan | None,
    mode: MrcModePlan | None,
    cell: MrcCellPlan | None,
    axes: MrcAxisPlan | None,
    statistics: MrcStatisticsPlan | None,
    labels: MrcLabelPlan | None,
    extended_header: MrcExtendedHeaderPlan | None,
    fei_tags: tuple[MrcFeiTagPlan, ...],
    image_volume: MrcImageVolumePreservationPlan | None,
    rewrite_requests: tuple[MrcRewriteRequest, ...],
    actions: tuple[MrcActionPlan, ...],
    blockers: tuple[MrcTransactionBlocker, ...],
    allow_output_emission: bool,
) -> MrcMetadataTransactionPlan:
    gates = [
        MrcOutputEmissionGate(
            code=blocker.code,
            reason=blocker.reason,
            evidence_ids=blocker.evidence_ids,
        )
        for blocker in blockers
    ]
    if not allow_output_emission and not blockers:
        gates.append(
            MrcOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="MRC plans preserve bytes unless output emission is explicitly allowed.",
                evidence_ids=(MRC_DESCRIPTION_SOURCE,),
            )
        )
    return MrcMetadataTransactionPlan(
        status=status,
        source_data=source_data,
        header_validation=header_validation,
        dimensions=dimensions,
        mode=mode,
        cell=cell,
        axes=axes,
        statistics=statistics,
        labels=labels,
        extended_header=extended_header,
        fei_tags=fei_tags,
        image_volume=image_volume,
        rewrite_requests=rewrite_requests,
        actions=actions,
        blockers=blockers,
        output_emission_gates=tuple(gates),
        evidence_ids=MRC_TRANSACTION_SOURCES,
    )


def _u32(data: bytes, offset: int) -> int:
    return int(unpack_from("<I", data, offset)[0])


def _f32(data: bytes, offset: int) -> float:
    return float(unpack_from("<f", data, offset)[0])


def _f64(data: bytes, offset: int) -> float:
    return float(unpack_from("<d", data, offset)[0])


FEI_FIELDS: tuple[MrcFeiFieldDefinition, ...] = (
    MrcFeiFieldDefinition(0, "MetadataSize", 0, "int32u"),
    MrcFeiFieldDefinition(4, "MetadataVersion", 4, "int32u"),
    MrcFeiFieldDefinition(8, "Bitmask1", 8, "bitmask"),
    MrcFeiFieldDefinition(12, "TimeStamp", 12, "timestamp_ole", 8, 0x01),
    MrcFeiFieldDefinition(20, "MicroscopeType", 20, "string16", 8, 0x02),
    MrcFeiFieldDefinition(36, "MicroscopeID", 36, "string16", 8, 0x04),
    MrcFeiFieldDefinition(52, "Application", 52, "string16", 8, 0x08),
    MrcFeiFieldDefinition(68, "AppVersion", 68, "string16", 8, 0x10),
    MrcFeiFieldDefinition(84, "HighTension", 84, "double", 8, 0x20),
    MrcFeiFieldDefinition(92, "Dose", 92, "double", 8, 0x40),
    MrcFeiFieldDefinition(100, "AlphaTilt", 100, "double", 8, 0x80),
    MrcFeiFieldDefinition(108, "BetaTilt", 108, "double", 8, 0x100),
    MrcFeiFieldDefinition(116, "XStage", 116, "double", 8, 0x200),
    MrcFeiFieldDefinition(124, "YStage", 124, "double", 8, 0x400),
    MrcFeiFieldDefinition(132, "ZStage", 132, "double", 8, 0x800),
    MrcFeiFieldDefinition(140, "TiltAxisAngle", 140, "double", 8, 0x1000),
    MrcFeiFieldDefinition(148, "DualAxisRot", 148, "double", 8, 0x2000),
    MrcFeiFieldDefinition(156, "PixelSizeX", 156, "double", 8, 0x4000),
    MrcFeiFieldDefinition(164, "PixelSizeY", 164, "double", 8, 0x8000),
    MrcFeiFieldDefinition(220, "Defocus", 220, "double", 8, 0x400000),
    MrcFeiFieldDefinition(228, "STEMDefocus", 228, "double", 8, 0x800000),
    MrcFeiFieldDefinition(236, "AppliedDefocus", 236, "double", 8, 0x1000000),
    MrcFeiFieldDefinition(
        244,
        "InstrumentMode",
        244,
        "int32u",
        8,
        0x2000000,
        {1: "TEM", 2: "STEM"},
    ),
    MrcFeiFieldDefinition(
        248,
        "ProjectionMode",
        248,
        "int32u",
        8,
        0x4000000,
        {1: "Diffraction", 2: "Imaging"},
    ),
    MrcFeiFieldDefinition(252, "ObjectiveLens", 252, "string16", 8, 0x8000000),
    MrcFeiFieldDefinition(268, "HighMagnificationMode", 268, "string16", 8, 0x10000000),
    MrcFeiFieldDefinition(
        284,
        "ProbeMode",
        284,
        "int32u",
        8,
        0x20000000,
        {1: "Nano", 2: "Micro"},
    ),
    MrcFeiFieldDefinition(288, "EFTEMOn", 288, "bool8", 8, 0x40000000),
    MrcFeiFieldDefinition(289, "Magnification", 289, "double", 8, 0x80000000),
    MrcFeiFieldDefinition(297, "Bitmask2", 297, "bitmask"),
    MrcFeiFieldDefinition(301, "CameraLength", 301, "double", 297, 0x01),
    MrcFeiFieldDefinition(309, "SpotIndex", 309, "int32u", 297, 0x02),
    MrcFeiFieldDefinition(313, "IlluminationArea", 313, "double", 297, 0x04),
    MrcFeiFieldDefinition(321, "Intensity", 321, "double", 297, 0x08),
    MrcFeiFieldDefinition(329, "ConvergenceAngle", 329, "double", 297, 0x10),
    MrcFeiFieldDefinition(387, "ShiftOffsetX", 387, "double", 297, 0x1000),
    MrcFeiFieldDefinition(395, "ShiftOffsetY", 395, "double", 297, 0x2000),
    MrcFeiFieldDefinition(403, "ShiftX", 403, "double", 297, 0x4000),
    MrcFeiFieldDefinition(411, "ShiftY", 411, "double", 297, 0x8000),
    MrcFeiFieldDefinition(419, "IntegrationTime", 419, "double", 297, 0x10000),
    MrcFeiFieldDefinition(427, "BinningWidth", 427, "int32u", 297, 0x20000),
    MrcFeiFieldDefinition(431, "BinningHeight", 431, "int32u", 297, 0x40000),
    MrcFeiFieldDefinition(435, "CameraName", 435, "string16", 297, 0x80000),
    MrcFeiFieldDefinition(451, "ReadoutAreaLeft", 451, "int32u", 297, 0x100000),
    MrcFeiFieldDefinition(455, "ReadoutAreaTop", 455, "int32u", 297, 0x200000),
    MrcFeiFieldDefinition(459, "ReadoutAreaRight", 459, "int32u", 297, 0x400000),
    MrcFeiFieldDefinition(463, "ReadoutAreaBottom", 463, "int32u", 297, 0x800000),
    MrcFeiFieldDefinition(472, "DirectDetElectronCounting", 472, "bool8", 297, 0x4000000),
    MrcFeiFieldDefinition(473, "DirectDetAlignFrames", 473, "bool8", 297, 0x8000000),
    MrcFeiFieldDefinition(490, "Bitmask3", 490, "bitmask"),
    MrcFeiFieldDefinition(518, "PhasePlate", 518, "bool8", 490, 0x40),
    MrcFeiFieldDefinition(571, "DwellTime", 571, "double", 490, 0x8000),
    MrcFeiFieldDefinition(587, "ScanSizeLeft", 587, "int32u", 490, 0x20000),
    MrcFeiFieldDefinition(591, "ScanSizeTop", 591, "int32u", 490, 0x40000),
    MrcFeiFieldDefinition(595, "ScanSizeRight", 595, "int32u", 490, 0x80000),
    MrcFeiFieldDefinition(599, "ScanSizeBottom", 599, "int32u", 490, 0x100000),
    MrcFeiFieldDefinition(603, "FullScanFOV_X", 603, "double", 490, 0x200000),
    MrcFeiFieldDefinition(611, "FullScanFOV_Y", 611, "double", 490, 0x400000),
    MrcFeiFieldDefinition(748, "Bitmask4", 748, "bitmask"),
)


def _build_fei_tags(
    mrc_data: bytes,
    extended_header: MrcExtendedHeaderPlan,
) -> tuple[MrcFeiTagPlan, ...]:
    tags: list[MrcFeiTagPlan] = []
    for frame_index, frame_range in enumerate(extended_header.frame_ranges):
        group = "Main" if frame_index == 0 else f"Doc{frame_index}"
        tags.extend(
            _build_fei_frame_tags(mrc_data, frame_range[0], frame_range[1], frame_index, group)
        )
    return tuple(tags)


def _build_fei_frame_tags(
    mrc_data: bytes,
    start: int,
    end: int,
    frame_index: int,
    family_1_group: str,
) -> tuple[MrcFeiTagPlan, ...]:
    bitmasks: dict[int, int] = {}
    tags: list[MrcFeiTagPlan] = []
    for field in FEI_FIELDS:
        absolute_offset = start + field.offset
        if not _field_fits(absolute_offset, end, field.value_format):
            continue
        if field.value_format == "bitmask":
            bitmasks[field.offset] = _u32(mrc_data, absolute_offset)
        elif field.bitmask_offset is not None and field.bitmask is not None:
            active_bitmask = bitmasks.get(field.bitmask_offset)
            if active_bitmask is None or not active_bitmask & field.bitmask:
                continue
        value = _read_fei_value(mrc_data, absolute_offset, field)
        tags.append(
            MrcFeiTagPlan(
                name=field.name,
                tag_id=field.tag_id,
                value=value,
                frame_index=frame_index,
                family_1_group=family_1_group,
                evidence_ids=(MRC_FEI12_TABLE_SOURCE, MRC_EXTENDED_HEADER_SOURCE),
            )
        )
    return tuple(tags)


def _field_fits(offset: int, end: int, value_format: MrcFeiValueFormat) -> bool:
    width = {
        "bitmask": 4,
        "bool8": 1,
        "double": 8,
        "int32u": 4,
        "string16": 16,
        "timestamp_ole": 8,
    }[value_format]
    return offset + width <= end


def _read_fei_value(
    data: bytes,
    offset: int,
    field: MrcFeiFieldDefinition,
) -> str | int | float:
    if field.value_format == "bitmask":
        return f"0x{_u32(data, offset):08x}"
    if field.value_format == "bool8":
        return "Yes" if data[offset] else "No"
    if field.value_format == "double":
        return _f64(data, offset)
    if field.value_format == "int32u":
        value = _u32(data, offset)
        if field.print_map is not None:
            return field.print_map.get(value, value)
        return value
    if field.value_format == "string16":
        return data[offset : offset + 16].split(b"\x00", 1)[0].decode("latin-1").rstrip()
    return _ole_timestamp(_f64(data, offset))


def _ole_timestamp(days_since_ole_epoch: float) -> str:
    timestamp = datetime(1899, 12, 30) + timedelta(days=days_since_ole_epoch)
    return timestamp.strftime("%Y:%m:%d %H:%M:%S")
