"""Non-mutating APP3 Stim metadata transaction planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

STIM_SIGNATURE = b"Stim\x00"
STIM_TIFF_OFFSET = 6
TIFF_HEADER_SIZE = 8
TIFF_ENTRY_SIZE = 12

type StimPlanStatus = Literal["planned", "unsupported"]
type StimByteOrder = Literal["little", "big"]
type StimRewriteTarget = Literal[
    "app3_segment",
    "tiff_header",
    "main_ifd",
    "crop_x",
    "crop_y",
    "tag",
]
type StimRewriteOperation = Literal["insert", "replace", "delete"]
type StimActionKind = Literal[
    "validate_stim_header",
    "parse_main_ifd",
    "route_main_tag",
    "route_crop_subdirectory",
    "preserve_payload",
    "block_requested_rewrite",
]
type StimBlockerCode = Literal[
    "truncated_stim_signature",
    "invalid_stim_signature",
    "truncated_stim_tiff_header",
    "invalid_stim_tiff_header",
    "truncated_main_ifd",
    "truncated_tiff_entry_value",
    "unsupported_tiff_field_type",
    "truncated_crop_subdirectory",
    "rewrite_requested_requires_stim_writer",
]
type StimEmissionGateCode = Literal[
    "truncated_stim_signature",
    "invalid_stim_signature",
    "truncated_stim_tiff_header",
    "invalid_stim_tiff_header",
    "truncated_main_ifd",
    "truncated_tiff_entry_value",
    "unsupported_tiff_field_type",
    "truncated_crop_subdirectory",
    "rewrite_requested_requires_stim_writer",
    "non_mutating_plan_requires_explicit_emission",
]
type StimTableName = Literal["Main", "CropX", "CropY"]
type StimRouteKind = Literal[
    "main_scalar",
    "main_binary",
    "main_subdirectory",
    "crop_subdirectory_scalar",
    "unknown_preserve",
]
type StimTiffFieldTypeName = Literal[
    "BYTE",
    "ASCII",
    "SHORT",
    "LONG",
    "UNDEFINED",
    "SSHORT",
    "SLONG",
]
type StimTagValue = int | bytes | str | tuple[int, ...]

JPEG_STIM_DISPATCH_SOURCE = "jpeg.stim.dispatch"
STIM_MAIN_TABLE_SOURCE = "stim.main.table"
STIM_CROPX_TABLE_SOURCE = "stim.cropx.table"
STIM_CROPY_TABLE_SOURCE = "stim.cropy.table"

STIM_TRANSACTION_SOURCES = (
    JPEG_STIM_DISPATCH_SOURCE,
    STIM_MAIN_TABLE_SOURCE,
    STIM_CROPX_TABLE_SOURCE,
    STIM_CROPY_TABLE_SOURCE,
)

TIFF_FIELD_TYPES: dict[int, tuple[StimTiffFieldTypeName, int]] = {
    1: ("BYTE", 1),
    2: ("ASCII", 1),
    3: ("SHORT", 2),
    4: ("LONG", 4),
    7: ("UNDEFINED", 1),
    8: ("SSHORT", 2),
    9: ("SLONG", 4),
}

STIM_MAIN_TAGS: dict[int, str] = {
    0: "StimVersion",
    1: "ApplicationData",
    2: "ImageArrangement",
    3: "ImageRotation",
    4: "ScalingFactor",
    5: "CropXSize",
    6: "CropYSize",
    7: "CropX",
    8: "CropY",
    9: "ViewType",
    10: "RepresentativeImage",
    11: "ConvergenceBaseImage",
    12: "AssumedDisplaySize",
    13: "AssumedDistanceView",
    14: "RepresentativeDisparityNear",
    15: "RepresentativeDisparityFar",
    16: "InitialDisplayEffect",
    17: "ConvergenceDistance",
    18: "CameraArrangementInterval",
    19: "ShootingCount",
}
STIM_CROPX_TAGS: dict[int, str] = {
    0: "CropXCommonOffset",
    2: "CropXViewpointNumber",
    3: "CropXOffset",
    7: "CropXViewpointNumber2",
    8: "CropXOffset2",
}
STIM_CROPY_TAGS: dict[int, str] = {
    0: "CropYCommonOffset",
    2: "CropYViewpointNumber",
    3: "CropYOffset",
    7: "CropYViewpointNumber2",
    8: "CropYOffset2",
}


@dataclass(frozen=True)
class StimRewriteRequest:
    target: StimRewriteTarget
    operation: StimRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class StimTransactionBlocker:
    code: StimBlockerCode
    reason: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class StimOutputEmissionGate:
    code: StimEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class StimHeaderValidationPlan:
    signature_range: tuple[int, int]
    signature: bytes
    tiff_header_range: tuple[int, int] | None
    byte_order: StimByteOrder | None
    tiff_magic: int | None
    first_ifd_offset: int | None
    reason: StimBlockerCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class StimTagPlan:
    table_name: StimTableName
    tag_id: int
    tag_name: str | None
    field_type: StimTiffFieldTypeName | None
    count: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_value: bytes
    value: StimTagValue | None
    print_value: str | None
    route_kind: StimRouteKind
    child_tags: tuple[StimTagPlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class StimPayloadPreservationPlan:
    payload_range: tuple[int, int]
    tiff_payload_range: tuple[int, int]
    preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class StimActionPlan:
    kind: StimActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class StimMetadataTransactionPlan:
    status: StimPlanStatus
    source_payload: bytes
    header_validation: StimHeaderValidationPlan
    main_tags: tuple[StimTagPlan, ...]
    payload_preservation: StimPayloadPreservationPlan | None
    rewrite_requests: tuple[StimRewriteRequest, ...]
    actions: tuple[StimActionPlan, ...]
    blockers: tuple[StimTransactionBlocker, ...]
    output_emission_gates: tuple[StimOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Stim metadata transaction output is gated: {gate_codes}")
        return self.source_payload


@dataclass(frozen=True)
class ParsedTiffEntry:
    tag_id: int
    field_type_id: int
    field_type: StimTiffFieldTypeName | None
    type_size: int | None
    count: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_value: bytes
    value: StimTagValue | None
    blocker: StimTransactionBlocker | None


def build_stim_metadata_transaction_plan(
    app3_payload: bytes,
    *,
    rewrite_requests: tuple[StimRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> StimMetadataTransactionPlan:
    """Build a source-backed, preserve-only Stim APP3 transaction plan."""

    blockers: list[StimTransactionBlocker] = []
    actions: list[StimActionPlan] = []
    header = _build_header_validation(app3_payload, blockers, actions)
    main_tags: tuple[StimTagPlan, ...] = ()
    payload_preservation: StimPayloadPreservationPlan | None = None

    if header.is_exiftool_accepted and header.byte_order is not None:
        main_tags = _parse_main_ifd(app3_payload, header.byte_order, blockers, actions)
        payload_preservation = StimPayloadPreservationPlan(
            payload_range=(0, len(app3_payload)),
            tiff_payload_range=(STIM_TIFF_OFFSET, len(app3_payload)),
            preserved=True,
            evidence_ids=(JPEG_STIM_DISPATCH_SOURCE, STIM_MAIN_TABLE_SOURCE),
        )
        actions.append(
            StimActionPlan(
                kind="preserve_payload",
                target="APP3 Stim",
                byte_range=(0, len(app3_payload)),
                reason="Stim planning is non-mutating and preserves the APP3 payload.",
                evidence_ids=(JPEG_STIM_DISPATCH_SOURCE, STIM_MAIN_TABLE_SOURCE),
            )
        )

    for request in rewrite_requests:
        blocker = StimTransactionBlocker(
            code="rewrite_requested_requires_stim_writer",
            reason=(
                f"Stim {request.operation} for {request.target} was requested, "
                "but this slice only ports ExifTool read routing and preservation."
            ),
            byte_range=None,
            evidence_ids=(STIM_MAIN_TABLE_SOURCE,),
        )
        blockers.append(blocker)
        actions.append(
            StimActionPlan(
                kind="block_requested_rewrite",
                target=request.target,
                byte_range=None,
                reason="Stim rewrites are blocked until a source-backed writer exists.",
                evidence_ids=(STIM_MAIN_TABLE_SOURCE,),
            )
        )

    structural_codes: tuple[StimBlockerCode, ...] = (
        "truncated_stim_signature",
        "invalid_stim_signature",
        "truncated_stim_tiff_header",
        "invalid_stim_tiff_header",
        "truncated_main_ifd",
        "truncated_tiff_entry_value",
        "unsupported_tiff_field_type",
        "truncated_crop_subdirectory",
    )
    status: StimPlanStatus = (
        "unsupported"
        if any(blocker.code in structural_codes for blocker in blockers)
        else "planned"
    )
    gates = _build_output_gates(blockers, allow_output_emission)
    return StimMetadataTransactionPlan(
        status=status,
        source_payload=app3_payload,
        header_validation=header,
        main_tags=main_tags,
        payload_preservation=payload_preservation,
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        blockers=tuple(blockers),
        output_emission_gates=gates,
        evidence_ids=STIM_TRANSACTION_SOURCES,
    )


def _build_header_validation(
    app3_payload: bytes,
    blockers: list[StimTransactionBlocker],
    actions: list[StimActionPlan],
) -> StimHeaderValidationPlan:
    signature = app3_payload[: len(STIM_SIGNATURE)]
    if len(app3_payload) < len(STIM_SIGNATURE):
        blockers.append(
            StimTransactionBlocker(
                code="truncated_stim_signature",
                reason="APP3 data is too short for the Stim signature.",
                byte_range=(0, len(app3_payload)),
                evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
            )
        )
        return StimHeaderValidationPlan(
            signature_range=(0, len(app3_payload)),
            signature=signature,
            tiff_header_range=None,
            byte_order=None,
            tiff_magic=None,
            first_ifd_offset=None,
            reason="truncated_stim_signature",
            evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
        )
    if signature != STIM_SIGNATURE:
        blockers.append(
            StimTransactionBlocker(
                code="invalid_stim_signature",
                reason="ExifTool routes APP3 Stim only when data begins with Stim NUL.",
                byte_range=(0, len(STIM_SIGNATURE)),
                evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
            )
        )
        return StimHeaderValidationPlan(
            signature_range=(0, len(STIM_SIGNATURE)),
            signature=signature,
            tiff_header_range=None,
            byte_order=None,
            tiff_magic=None,
            first_ifd_offset=None,
            reason="invalid_stim_signature",
            evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
        )

    tiff_header_end = STIM_TIFF_OFFSET + TIFF_HEADER_SIZE
    if len(app3_payload) < tiff_header_end:
        blockers.append(
            StimTransactionBlocker(
                code="truncated_stim_tiff_header",
                reason="ExifTool starts Stim TIFF parsing at APP3 byte offset 6.",
                byte_range=(STIM_TIFF_OFFSET, len(app3_payload)),
                evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
            )
        )
        return StimHeaderValidationPlan(
            signature_range=(0, len(STIM_SIGNATURE)),
            signature=signature,
            tiff_header_range=(STIM_TIFF_OFFSET, len(app3_payload)),
            byte_order=None,
            tiff_magic=None,
            first_ifd_offset=None,
            reason="truncated_stim_tiff_header",
            evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
        )

    byte_order = _byte_order(app3_payload[STIM_TIFF_OFFSET : STIM_TIFF_OFFSET + 2])
    if byte_order is None:
        return _invalid_tiff_header(app3_payload, signature, blockers)
    magic = _u16(app3_payload, STIM_TIFF_OFFSET + 2, byte_order)
    first_ifd_offset = _u32(app3_payload, STIM_TIFF_OFFSET + 4, byte_order)
    if magic != 42 or first_ifd_offset < TIFF_HEADER_SIZE:
        return _invalid_tiff_header(app3_payload, signature, blockers)

    actions.append(
        StimActionPlan(
            kind="validate_stim_header",
            target="APP3 Stim TIFF",
            byte_range=(0, tiff_header_end),
            reason="Input matches ExifTool's APP3 Stim signature and TIFF dispatch.",
            evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
        )
    )
    return StimHeaderValidationPlan(
        signature_range=(0, len(STIM_SIGNATURE)),
        signature=signature,
        tiff_header_range=(STIM_TIFF_OFFSET, tiff_header_end),
        byte_order=byte_order,
        tiff_magic=magic,
        first_ifd_offset=first_ifd_offset,
        reason=None,
        evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
    )


def _invalid_tiff_header(
    app3_payload: bytes,
    signature: bytes,
    blockers: list[StimTransactionBlocker],
) -> StimHeaderValidationPlan:
    tiff_header_end = min(len(app3_payload), STIM_TIFF_OFFSET + TIFF_HEADER_SIZE)
    blockers.append(
        StimTransactionBlocker(
            code="invalid_stim_tiff_header",
            reason="Stim APP3 data must contain a TIFF header at byte offset 6.",
            byte_range=(STIM_TIFF_OFFSET, tiff_header_end),
            evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
        )
    )
    return StimHeaderValidationPlan(
        signature_range=(0, len(STIM_SIGNATURE)),
        signature=signature,
        tiff_header_range=(STIM_TIFF_OFFSET, tiff_header_end),
        byte_order=None,
        tiff_magic=None,
        first_ifd_offset=None,
        reason="invalid_stim_tiff_header",
        evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
    )


def _parse_main_ifd(
    app3_payload: bytes,
    byte_order: StimByteOrder,
    blockers: list[StimTransactionBlocker],
    actions: list[StimActionPlan],
) -> tuple[StimTagPlan, ...]:
    first_ifd_offset = _u32(app3_payload, STIM_TIFF_OFFSET + 4, byte_order)
    ifd_start = STIM_TIFF_OFFSET + first_ifd_offset
    if ifd_start + 2 > len(app3_payload):
        blockers.append(
            StimTransactionBlocker(
                code="truncated_main_ifd",
                reason="Stim main IFD offset points beyond the APP3 payload.",
                byte_range=(ifd_start, len(app3_payload)),
                evidence_ids=(JPEG_STIM_DISPATCH_SOURCE, STIM_MAIN_TABLE_SOURCE),
            )
        )
        return ()

    entry_count = _u16(app3_payload, ifd_start, byte_order)
    entries_start = ifd_start + 2
    entries_end = entries_start + entry_count * TIFF_ENTRY_SIZE
    next_ifd_end = entries_end + 4
    if next_ifd_end > len(app3_payload):
        blockers.append(
            StimTransactionBlocker(
                code="truncated_main_ifd",
                reason="Stim main IFD entry table is truncated.",
                byte_range=(ifd_start, len(app3_payload)),
                evidence_ids=(JPEG_STIM_DISPATCH_SOURCE, STIM_MAIN_TABLE_SOURCE),
            )
        )
        return ()

    actions.append(
        StimActionPlan(
            kind="parse_main_ifd",
            target="Stim Main",
            byte_range=(ifd_start, next_ifd_end),
            reason="Parsing Stim main IFD with Image::ExifTool::Stim::Main routing.",
            evidence_ids=(JPEG_STIM_DISPATCH_SOURCE, STIM_MAIN_TABLE_SOURCE),
        )
    )
    tag_plans: list[StimTagPlan] = []
    for index in range(entry_count):
        entry_offset = entries_start + index * TIFF_ENTRY_SIZE
        entry = _parse_tiff_entry(app3_payload, byte_order, entry_offset)
        if entry.blocker is not None:
            blockers.append(entry.blocker)
            continue
        tag_plan = _route_main_entry(app3_payload, byte_order, entry, blockers, actions)
        tag_plans.append(tag_plan)
    return tuple(tag_plans)


def _parse_tiff_entry(
    app3_payload: bytes,
    byte_order: StimByteOrder,
    entry_offset: int,
) -> ParsedTiffEntry:
    entry_range = (entry_offset, entry_offset + TIFF_ENTRY_SIZE)
    tag_id = _u16(app3_payload, entry_offset, byte_order)
    field_type_id = _u16(app3_payload, entry_offset + 2, byte_order)
    count = _u32(app3_payload, entry_offset + 4, byte_order)
    field = TIFF_FIELD_TYPES.get(field_type_id)
    if field is None:
        return ParsedTiffEntry(
            tag_id=tag_id,
            field_type_id=field_type_id,
            field_type=None,
            type_size=None,
            count=count,
            entry_range=entry_range,
            value_range=(entry_offset + 8, entry_offset + 12),
            raw_value=app3_payload[entry_offset + 8 : entry_offset + 12],
            value=None,
            blocker=StimTransactionBlocker(
                code="unsupported_tiff_field_type",
                reason=f"TIFF field type {field_type_id} is not supported by this Stim slice.",
                byte_range=entry_range,
                evidence_ids=(JPEG_STIM_DISPATCH_SOURCE,),
            ),
        )

    field_type, type_size = field
    value_size = count * type_size
    if value_size <= 4:
        value_start = entry_offset + 8
        value_end = value_start + value_size
    else:
        value_offset = _u32(app3_payload, entry_offset + 8, byte_order)
        value_start = STIM_TIFF_OFFSET + value_offset
        value_end = value_start + value_size

    if value_end > len(app3_payload):
        return ParsedTiffEntry(
            tag_id=tag_id,
            field_type_id=field_type_id,
            field_type=field_type,
            type_size=type_size,
            count=count,
            entry_range=entry_range,
            value_range=(value_start, len(app3_payload)),
            raw_value=app3_payload[value_start:],
            value=None,
            blocker=StimTransactionBlocker(
                code="truncated_tiff_entry_value",
                reason="Stim TIFF entry value bytes extend beyond the APP3 payload.",
                byte_range=(value_start, len(app3_payload)),
                evidence_ids=(JPEG_STIM_DISPATCH_SOURCE, STIM_MAIN_TABLE_SOURCE),
            ),
        )
    raw_value = app3_payload[value_start:value_end]
    return ParsedTiffEntry(
        tag_id=tag_id,
        field_type_id=field_type_id,
        field_type=field_type,
        type_size=type_size,
        count=count,
        entry_range=entry_range,
        value_range=(value_start, value_end),
        raw_value=raw_value,
        value=_decode_tiff_value(raw_value, field_type, count, byte_order),
        blocker=None,
    )


def _route_main_entry(
    app3_payload: bytes,
    byte_order: StimByteOrder,
    entry: ParsedTiffEntry,
    blockers: list[StimTransactionBlocker],
    actions: list[StimActionPlan],
) -> StimTagPlan:
    tag_name = STIM_MAIN_TAGS.get(entry.tag_id)
    evidence_ids: tuple[str, ...]
    if tag_name is None:
        route_kind: StimRouteKind = "unknown_preserve"
        evidence_ids = (STIM_MAIN_TABLE_SOURCE,)
    elif entry.tag_id == 1:
        route_kind = "main_binary"
        evidence_ids = (STIM_MAIN_TABLE_SOURCE,)
    elif entry.tag_id in (7, 8):
        route_kind = "main_subdirectory"
        evidence_ids = (
            STIM_MAIN_TABLE_SOURCE,
            STIM_CROPX_TABLE_SOURCE if entry.tag_id == 7 else STIM_CROPY_TABLE_SOURCE,
        )
    else:
        route_kind = "main_scalar"
        evidence_ids = (STIM_MAIN_TABLE_SOURCE,)

    child_tags: tuple[StimTagPlan, ...] = ()
    if entry.tag_id in (7, 8):
        table_name: StimTableName = "CropX" if entry.tag_id == 7 else "CropY"
        child_tags = _route_crop_subdirectory(
            app3_payload,
            table_name,
            byte_order,
            entry.value_range,
            blockers,
            actions,
        )

    actions.append(
        StimActionPlan(
            kind="route_main_tag",
            target=tag_name or f"Unknown:{entry.tag_id}",
            byte_range=entry.entry_range,
            reason="Routed TIFF entry through the Stim main tag table.",
            evidence_ids=evidence_ids,
        )
    )
    return StimTagPlan(
        table_name="Main",
        tag_id=entry.tag_id,
        tag_name=tag_name,
        field_type=entry.field_type,
        count=entry.count,
        entry_range=entry.entry_range,
        value_range=entry.value_range,
        raw_value=entry.raw_value,
        value=entry.value,
        print_value=_print_main_value(entry.tag_id, entry.value),
        route_kind=route_kind,
        child_tags=child_tags,
        evidence_ids=evidence_ids,
    )


def _route_crop_subdirectory(
    app3_payload: bytes,
    table_name: StimTableName,
    byte_order: StimByteOrder,
    value_range: tuple[int, int],
    blockers: list[StimTransactionBlocker],
    actions: list[StimActionPlan],
) -> tuple[StimTagPlan, ...]:
    crop_tags = STIM_CROPX_TAGS if table_name == "CropX" else STIM_CROPY_TAGS
    crop_source = STIM_CROPX_TABLE_SOURCE if table_name == "CropX" else STIM_CROPY_TABLE_SOURCE
    specs: tuple[tuple[int, StimTiffFieldTypeName, int], ...] = (
        (0, "SHORT", 2),
        (2, "BYTE", 1),
        (3, "SLONG", 4),
        (7, "BYTE", 1),
        (8, "SLONG", 4),
    )
    child_tags: list[StimTagPlan] = []
    for tag_id, field_type, type_size in specs:
        value_start = value_range[0] + tag_id
        value_end = value_start + type_size
        if value_end > value_range[1]:
            blockers.append(
                StimTransactionBlocker(
                    code="truncated_crop_subdirectory",
                    reason=f"{table_name} BinaryData is too short for {crop_tags[tag_id]}.",
                    byte_range=(value_start, value_range[1]),
                    evidence_ids=(crop_source,),
                )
            )
            continue
        raw_value = app3_payload[value_start:value_end]
        child_tags.append(
            StimTagPlan(
                table_name=table_name,
                tag_id=tag_id,
                tag_name=crop_tags[tag_id],
                field_type=field_type,
                count=1,
                entry_range=(value_start, value_end),
                value_range=(value_start, value_end),
                raw_value=raw_value,
                value=_decode_tiff_value(raw_value, field_type, 1, byte_order),
                print_value=_print_crop_value(tag_id, raw_value, field_type, byte_order),
                route_kind="crop_subdirectory_scalar",
                child_tags=(),
                evidence_ids=(crop_source,),
            )
        )
    actions.append(
        StimActionPlan(
            kind="route_crop_subdirectory",
            target=table_name,
            byte_range=value_range,
            reason=f"Routed {table_name} bytes through the Stim BinaryData subtable.",
            evidence_ids=(crop_source,),
        )
    )
    return tuple(child_tags)


def _build_output_gates(
    blockers: list[StimTransactionBlocker],
    allow_output_emission: bool,
) -> tuple[StimOutputEmissionGate, ...]:
    gates = [
        StimOutputEmissionGate(
            code=blocker.code,
            reason=blocker.reason,
            evidence_ids=blocker.evidence_ids,
        )
        for blocker in blockers
    ]
    if not allow_output_emission:
        gates.append(
            StimOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="Stim plans preserve bytes unless output emission is explicitly enabled.",
                evidence_ids=(JPEG_STIM_DISPATCH_SOURCE, STIM_MAIN_TABLE_SOURCE),
            )
        )
    return tuple(gates)


def _byte_order(raw: bytes) -> StimByteOrder | None:
    if raw == b"II":
        return "little"
    if raw == b"MM":
        return "big"
    return None


def _u16(data: bytes, offset: int, byte_order: StimByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 2], byte_order)


def _u32(data: bytes, offset: int, byte_order: StimByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order)


def _i16(data: bytes, offset: int, byte_order: StimByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 2], byte_order, signed=True)


def _i32(data: bytes, offset: int, byte_order: StimByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order, signed=True)


def _decode_tiff_value(
    raw_value: bytes,
    field_type: StimTiffFieldTypeName,
    count: int,
    byte_order: StimByteOrder,
) -> StimTagValue:
    if field_type in ("BYTE", "UNDEFINED"):
        if count == 1:
            return raw_value[0]
        return tuple(raw_value)
    if field_type == "ASCII":
        return raw_value.rstrip(b"\x00").decode("latin-1", errors="replace")
    if field_type == "SHORT":
        values = tuple(_u16(raw_value, index * 2, byte_order) for index in range(count))
        return values[0] if count == 1 else values
    if field_type == "LONG":
        values = tuple(_u32(raw_value, index * 4, byte_order) for index in range(count))
        return values[0] if count == 1 else values
    if field_type == "SSHORT":
        values = tuple(_i16(raw_value, index * 2, byte_order) for index in range(count))
        return values[0] if count == 1 else values
    values = tuple(_i32(raw_value, index * 4, byte_order) for index in range(count))
    return values[0] if count == 1 else values


def _print_main_value(tag_id: int, value: StimTagValue | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, int):
        return None
    if tag_id == 2:
        return {0: "Parallel View Alignment", 1: "Cross View Alignment"}.get(value)
    if tag_id == 3:
        return {1: "None"}.get(value)
    if tag_id == 9:
        return {0: "No Pop-up Effect", 1: "Pop-up Effect"}.get(value)
    if tag_id == 10:
        return {0: "Left Viewpoint", 1: "Right Viewpoint"}.get(value)
    if tag_id == 11:
        return {
            0: "Left Viewpoint",
            1: "Right Viewpoint",
            255: "Equivalent for Both Viewpoints",
        }.get(value)
    if tag_id in (12, 13, 18) and isinstance(value, int):
        return f"{value} mm"
    if tag_id == 16:
        return {0: "Off", 1: "On"}.get(value)
    if tag_id == 17 and isinstance(value, int):
        return f"{value} mm" if value else "inf"
    return None


def _print_crop_value(
    tag_id: int,
    raw_value: bytes,
    field_type: StimTiffFieldTypeName,
    byte_order: StimByteOrder,
) -> str | None:
    if tag_id == 0:
        value = _decode_tiff_value(raw_value, field_type, 1, byte_order)
        if not isinstance(value, int):
            return None
        return {0: "Common Offset Setting", 1: "Individual Offset Setting"}.get(value)
    return None
