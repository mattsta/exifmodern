"""Source-grounded, non-mutating WPG image transaction plans.

ExifTool's WPG module is a reader. It validates the WPG signature, reads the
16-byte header, seeks to the declared record stream, enumerates version 1 and
version 2 records with ExifTool's variable-length sizes, collapses adjacent
matching record entries, and extracts image dimensions from Start WPG records.
This planner preserves every parsed payload byte and never rewrites WPG data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

WPG_SIGNATURE = b"\xffWPC"
WPG_EXIFTOOL_HEADER_SIZE = 16
WPG_DEFAULT_RESOLUTION = 1200

type WpgPlanStatus = Literal["planned", "unsupported"]
type WpgRecordTable = Literal["Records", "RecordsV2"]
type WpgRecordRole = Literal[
    "control",
    "vector",
    "raster",
    "preview",
    "metadata",
    "color",
    "unknown",
]
type WpgActionKind = Literal[
    "validate_signature",
    "validate_header",
    "seek_record_start",
    "enumerate_record",
    "collapse_record_sequence",
    "extract_dimensions",
    "preserve_vector_payload",
    "preserve_raster_payload",
    "preserve_preview_payload",
    "preserve_metadata_payload",
    "preserve_color_payload",
    "preserve_unknown_payload",
    "block_requested_rewrite",
]
type WpgEmissionGateCode = Literal[
    "truncated_wpg_header",
    "unsupported_wpg_signature",
    "unsupported_wpg_version",
    "invalid_wpg_record_offset",
    "wpg_record_offset_beyond_input",
    "truncated_wpg_record_header",
    "truncated_wpg_record_length",
    "truncated_wpg_record_payload",
    "truncated_wpg_start_record",
    "invalid_wpg_start_precision",
    "rewrite_requested_requires_wpg_writer",
    "non_mutating_plan_requires_explicit_emission",
]
type WpgRewriteOperation = Literal["insert", "replace", "delete"]
type WpgRewriteTarget = Literal[
    "records",
    "dimensions",
    "metadata",
    "preview",
    "vector",
    "raster",
    "color",
    "unknown",
]

WPG_PM_SOURCE_PATH = "lib/Image/ExifTool/WPG.pm"

WPG_DESCRIPTION_SOURCE = "wpg.description"
WPG_MAIN_TABLE_SOURCE = "wpg.main.table"
WPG_PRINT_RECORD_SOURCE = "wpg.print.record"
WPG_VARINT_SOURCE = "wpg.varint"
WPG_HEADER_SOURCE = "wpg.header"
WPG_RECORD_HEADER_SOURCE = "wpg.record.header"
WPG_START_RECORD_SOURCE = "wpg.start.record"
WPG_PAYLOAD_SKIP_SOURCE = "wpg.payload.skip"
WPG_COLLAPSE_SOURCE = "wpg.collapse"

WPG_TRANSACTION_SOURCES = (
    WPG_DESCRIPTION_SOURCE,
    WPG_MAIN_TABLE_SOURCE,
    WPG_PRINT_RECORD_SOURCE,
    WPG_VARINT_SOURCE,
    WPG_HEADER_SOURCE,
    WPG_RECORD_HEADER_SOURCE,
    WPG_START_RECORD_SOURCE,
    WPG_PAYLOAD_SKIP_SOURCE,
    WPG_COLLAPSE_SOURCE,
)

WPG_V1_RECORD_NAMES: dict[int, str] = {
    0x01: "Fill Attributes",
    0x02: "Line Attributes",
    0x03: "Marker Attributes",
    0x04: "Polymarker",
    0x05: "Line",
    0x06: "Polyline",
    0x07: "Rectangle",
    0x08: "Polygon",
    0x09: "Ellipse",
    0x0A: "Reserved",
    0x0B: "Bitmap Type 1",
    0x0C: "Graphics Text Type 1",
    0x0D: "Graphics Text Attributes",
    0x0E: "Color Map",
    0x0F: "Start WPG Type 1",
    0x10: "End WPG",
    0x11: "PostScript Data Type 1",
    0x12: "Output Attributes",
    0x13: "Curved Polyline",
    0x14: "Bitmap Type 2",
    0x15: "Start Figure",
    0x16: "Start Chart",
    0x17: "PlanPerfect Data",
    0x18: "Graphics Text Type 2",
    0x19: "Start WPG Type 2",
    0x1A: "Graphics Text Type 3",
    0x1B: "PostScript Data Type 2",
}

WPG_V2_RECORD_NAMES: dict[int, str] = {
    0x00: "End Marker",
    0x01: "Start WPG",
    0x02: "End WPG",
    0x03: "Form Settings",
    0x04: "Ruler Settings",
    0x05: "Grid Settings",
    0x06: "Layer",
    0x08: "Pen Style Definition",
    0x09: "Pattern Definition",
    0x0A: "Comment",
    0x0B: "Color Transfer",
    0x0C: "Color Palette",
    0x0D: "DP Color Palette",
    0x0E: "Bitmap Data",
    0x0F: "Text Data",
    0x10: "Chart Style",
    0x11: "Chart Data",
    0x12: "Image Record 0x12",
    0x15: "Polyline",
    0x16: "Polyspline",
    0x17: "Polycurve",
    0x18: "Rectangle",
    0x19: "Arc",
    0x1A: "Compound Polygon",
    0x1B: "Bitmap",
    0x1C: "Text Line",
    0x1D: "Text Block",
    0x1E: "Text Path",
    0x1F: "Chart",
    0x20: "Group",
    0x21: "Capsule Record 0x21",
    0x22: "Font Settings",
    0x25: "Pen Fore Color",
    0x26: "DP Pen Fore Color",
    0x27: "Pen Back Color",
    0x28: "DP Pen Back Color",
    0x29: "Pen Style",
    0x2A: "Pen Pattern",
    0x2B: "Pen Size",
    0x2C: "DP Pen Size",
    0x2D: "Line Cap",
    0x2E: "Line Join",
    0x2F: "Brush Gradient",
    0x30: "DP Brush Gradient",
    0x31: "Brush Fore Color",
    0x32: "DP Brush Fore Color",
    0x33: "Brush Back Color",
    0x34: "DP Brush Back Color",
    0x35: "Brush Pattern",
    0x36: "Horizontal Line",
    0x37: "Vertical Line",
    0x38: "Poster Settings",
    0x39: "Image State",
    0x3A: "Envelope Definition",
    0x3B: "Envelope",
    0x3C: "Texture Definition",
    0x3D: "Brush Texture",
    0x3E: "Texture Alignment",
    0x3F: "Pen Texture",
}


@dataclass(frozen=True)
class WpgRewriteRequest:
    target: WpgRewriteTarget
    operation: WpgRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class WpgOutputEmissionGate:
    code: WpgEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WpgHeaderValidationPlan:
    signature: bytes
    declared_record_offset: int | None
    version: int | None
    revision: int | None
    version_label: str | None
    record_table: WpgRecordTable | None
    header_range: tuple[int, int]
    reason: WpgEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class WpgVarIntPlan:
    start_offset: int
    end_offset: int
    encoded: bytes
    value: int
    reason: WpgEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class WpgRecordPlan:
    index: int
    raw_type_code: int
    type_code: int | None
    name: str
    role: WpgRecordRole
    header_range: tuple[int, int]
    payload_range: tuple[int, int]
    length_plan: WpgVarIntPlan
    extension_plan: WpgVarIntPlan | None
    action: WpgActionKind
    terminates_record_list: bool
    evidence_ids: tuple[str, ...]

    @property
    def payload_length(self) -> int:
        start, end = self.payload_range
        return end - start


@dataclass(frozen=True)
class WpgCollapsedRecordPlan:
    type_code: int
    name: str
    count: int
    exiftool_value: str
    display_value: str
    record_indexes: tuple[int, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WpgDimensionPlan:
    record_index: int | None
    width_units: int | None
    height_units: int | None
    x_resolution: int | None
    y_resolution: int | None
    width_inches: float | None
    height_inches: float | None
    precision: int | None
    reason: WpgEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_available(self) -> bool:
        return self.reason is None and self.width_inches is not None


@dataclass(frozen=True)
class WpgImageResponsibilityPlan:
    dimension_record_index: int | None
    color_record_indexes: tuple[int, ...]
    raster_record_indexes: tuple[int, ...]
    vector_record_indexes: tuple[int, ...]
    preview_record_indexes: tuple[int, ...]
    metadata_record_indexes: tuple[int, ...]
    unknown_record_indexes: tuple[int, ...]
    color_depth_bits: int | None
    compression: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WpgPayloadPreservationPlan:
    role: WpgRecordRole
    record_indexes: tuple[int, ...]
    byte_ranges: tuple[tuple[int, int], ...]
    action: WpgActionKind
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WpgActionPlan:
    kind: WpgActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WpgImageTransactionPlan:
    status: WpgPlanStatus
    source_data: bytes
    header_validation: WpgHeaderValidationPlan
    records: tuple[WpgRecordPlan, ...]
    collapsed_records: tuple[WpgCollapsedRecordPlan, ...]
    dimensions: WpgDimensionPlan
    responsibilities: WpgImageResponsibilityPlan
    payload_preservation: tuple[WpgPayloadPreservationPlan, ...]
    rewrite_requests: tuple[WpgRewriteRequest, ...]
    actions: tuple[WpgActionPlan, ...]
    output_emission_gates: tuple[WpgOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"WPG image transaction output is gated: {gate_codes}")
        return self.source_data


def build_wpg_image_transaction_plan(
    wpg_data: bytes,
    *,
    rewrite_requests: tuple[WpgRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> WpgImageTransactionPlan:
    """Build a source-backed WPG image transaction plan."""

    gates: list[WpgOutputEmissionGate] = []
    actions: list[WpgActionPlan] = []
    header = _build_header_validation(wpg_data, gates, actions)
    if not header.is_exiftool_accepted:
        return _final_plan(
            status="unsupported",
            source_data=wpg_data,
            header=header,
            records=(),
            collapsed_records=(),
            dimensions=_empty_dimensions(header.reason),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    records = _enumerate_records(wpg_data, header, gates, actions)
    collapsed_records = _collapse_records(records, actions)
    dimensions = _extract_dimensions(wpg_data, header, records, gates, actions)
    responsibilities = _build_responsibilities(records, dimensions)
    preservation = _build_payload_preservation(records, actions)

    for request in rewrite_requests:
        gates.append(
            WpgOutputEmissionGate(
                code="rewrite_requested_requires_wpg_writer",
                reason=(
                    f"WPG {request.operation} for {request.target} was requested, "
                    "but ExifTool's WPG module has no writer."
                ),
                evidence_ids=(WPG_DESCRIPTION_SOURCE,),
            )
        )
        actions.append(
            WpgActionPlan(
                kind="block_requested_rewrite",
                target=request.target,
                byte_range=None,
                reason="WPG rewrites are blocked until a source-backed writer exists.",
                evidence_ids=(WPG_DESCRIPTION_SOURCE,),
            )
        )

    structural_codes = {
        "truncated_wpg_header",
        "unsupported_wpg_signature",
        "unsupported_wpg_version",
        "invalid_wpg_record_offset",
        "wpg_record_offset_beyond_input",
        "truncated_wpg_record_header",
        "truncated_wpg_record_length",
        "truncated_wpg_record_payload",
        "truncated_wpg_start_record",
        "invalid_wpg_start_precision",
    }
    status: WpgPlanStatus = (
        "unsupported" if any(gate.code in structural_codes for gate in gates) else "planned"
    )
    return _finish_plan(
        status=status,
        source_data=wpg_data,
        header=header,
        records=records,
        collapsed_records=collapsed_records,
        dimensions=dimensions,
        responsibilities=responsibilities,
        preservation=preservation,
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        gates=gates,
        allow_output_emission=allow_output_emission,
    )


plan_wpg_image_transaction = build_wpg_image_transaction_plan


def _build_header_validation(
    wpg_data: bytes,
    gates: list[WpgOutputEmissionGate],
    actions: list[WpgActionPlan],
) -> WpgHeaderValidationPlan:
    if len(wpg_data) < WPG_EXIFTOOL_HEADER_SIZE:
        gates.append(
            WpgOutputEmissionGate(
                code="truncated_wpg_header",
                reason="ExifTool's WPG reader requires an initial 16-byte header read.",
                evidence_ids=(WPG_HEADER_SOURCE,),
            )
        )
        return WpgHeaderValidationPlan(
            signature=wpg_data[:4],
            declared_record_offset=None,
            version=None,
            revision=None,
            version_label=None,
            record_table=None,
            header_range=(0, len(wpg_data)),
            reason="truncated_wpg_header",
            evidence_ids=(WPG_HEADER_SOURCE,),
        )

    if not wpg_data.startswith(WPG_SIGNATURE):
        gates.append(
            WpgOutputEmissionGate(
                code="unsupported_wpg_signature",
                reason="Input does not match ExifTool's /^\\xff\\x57\\x50\\x43/ WPG gate.",
                evidence_ids=(WPG_HEADER_SOURCE,),
            )
        )
        return WpgHeaderValidationPlan(
            signature=wpg_data[:4],
            declared_record_offset=None,
            version=None,
            revision=None,
            version_label=None,
            record_table=None,
            header_range=(0, WPG_EXIFTOOL_HEADER_SIZE),
            reason="unsupported_wpg_signature",
            evidence_ids=(WPG_HEADER_SOURCE,),
        )

    actions.append(
        WpgActionPlan(
            kind="validate_signature",
            target="WPG",
            byte_range=(0, 4),
            reason="Input satisfied ExifTool's WPG signature gate.",
            evidence_ids=(WPG_HEADER_SOURCE,),
        )
    )
    offset = int.from_bytes(wpg_data[4:8], "little")
    version = wpg_data[10]
    revision = wpg_data[11]
    version_label = f"{version}.{revision}"
    record_table: WpgRecordTable | None = "Records" if version == 1 else "RecordsV2"
    reason: WpgEmissionGateCode | None = None
    if version < 1 or version > 2:
        reason = "unsupported_wpg_version"
        gates.append(
            WpgOutputEmissionGate(
                code=reason,
                reason=(
                    "ExifTool warns and stops record processing for WPG versions outside 1 and 2."
                ),
                evidence_ids=(WPG_HEADER_SOURCE,),
            )
        )
        record_table = None
    elif offset == 0:
        reason = "invalid_wpg_record_offset"
        gates.append(
            WpgOutputEmissionGate(
                code=reason,
                reason="The declared WPG record offset must identify a stream position.",
                evidence_ids=(WPG_HEADER_SOURCE,),
            )
        )
    elif offset > len(wpg_data):
        reason = "wpg_record_offset_beyond_input"
        gates.append(
            WpgOutputEmissionGate(
                code=reason,
                reason="The declared WPG record offset is beyond the supplied bytes.",
                evidence_ids=(WPG_HEADER_SOURCE,),
            )
        )

    actions.append(
        WpgActionPlan(
            kind="validate_header",
            target=version_label,
            byte_range=(0, WPG_EXIFTOOL_HEADER_SIZE),
            reason="Decoded WPGVersion and the little-endian record offset from the header.",
            evidence_ids=(WPG_HEADER_SOURCE, WPG_MAIN_TABLE_SOURCE),
        )
    )
    if reason is None:
        actions.append(
            WpgActionPlan(
                kind="seek_record_start",
                target=str(offset),
                byte_range=(WPG_EXIFTOOL_HEADER_SIZE, offset),
                reason="ExifTool seeks forward when the record offset is greater than 16.",
                evidence_ids=(WPG_HEADER_SOURCE,),
            )
        )

    return WpgHeaderValidationPlan(
        signature=wpg_data[:4],
        declared_record_offset=offset,
        version=version,
        revision=revision,
        version_label=version_label,
        record_table=record_table,
        header_range=(0, WPG_EXIFTOOL_HEADER_SIZE),
        reason=reason,
        evidence_ids=(WPG_HEADER_SOURCE, WPG_MAIN_TABLE_SOURCE),
    )


def _enumerate_records(
    wpg_data: bytes,
    header: WpgHeaderValidationPlan,
    gates: list[WpgOutputEmissionGate],
    actions: list[WpgActionPlan],
) -> tuple[WpgRecordPlan, ...]:
    if header.version is None or header.declared_record_offset is None:
        return ()
    offset = header.declared_record_offset
    records: list[WpgRecordPlan] = []
    while offset < len(wpg_data):
        record, next_offset = _read_record(wpg_data, header.version, offset, len(records), gates)
        if record is None:
            break
        records.append(record)
        actions.append(
            WpgActionPlan(
                kind="enumerate_record",
                target=record.name,
                byte_range=(record.header_range[0], record.payload_range[1]),
                reason="Enumerated a WPG record using ExifTool's version-specific header rules.",
                evidence_ids=(WPG_RECORD_HEADER_SOURCE, WPG_VARINT_SOURCE),
            )
        )
        offset = next_offset
        if record.terminates_record_list:
            break
    return tuple(records)


def _read_record(
    wpg_data: bytes,
    version: int,
    offset: int,
    index: int,
    gates: list[WpgOutputEmissionGate],
) -> tuple[WpgRecordPlan | None, int]:
    header_width = version
    if len(wpg_data) - offset < header_width:
        gates.append(
            WpgOutputEmissionGate(
                code="truncated_wpg_record_header",
                reason=(
                    "A WPG record header ended before ExifTool's version-width read could finish."
                ),
                evidence_ids=(WPG_RECORD_HEADER_SOURCE,),
            )
        )
        return None, len(wpg_data)

    raw_type = wpg_data[offset] if version == 1 else wpg_data[offset + 1]
    varint_offset = offset + header_width
    extension_plan: WpgVarIntPlan | None = None
    if version == 2:
        extension_plan = _read_varint(wpg_data, varint_offset)
        if not extension_plan.is_valid:
            gates.append(
                WpgOutputEmissionGate(
                    code="truncated_wpg_record_length",
                    reason="A WPG version 2 record extension varint was truncated.",
                    evidence_ids=(WPG_RECORD_HEADER_SOURCE, WPG_VARINT_SOURCE),
                )
            )
            return None, len(wpg_data)
        varint_offset = extension_plan.end_offset

    length_plan = _read_varint(wpg_data, varint_offset)
    if not length_plan.is_valid:
        gates.append(
            WpgOutputEmissionGate(
                code="truncated_wpg_record_length",
                reason="A WPG record payload length varint was truncated.",
                evidence_ids=(WPG_RECORD_HEADER_SOURCE, WPG_VARINT_SOURCE),
            )
        )
        return None, len(wpg_data)

    payload_start = length_plan.end_offset
    payload_end = payload_start + length_plan.value
    if payload_end > len(wpg_data):
        gates.append(
            WpgOutputEmissionGate(
                code="truncated_wpg_record_payload",
                reason="A WPG record payload extends beyond the supplied bytes.",
                evidence_ids=(WPG_PAYLOAD_SKIP_SOURCE,),
            )
        )
        payload_end = len(wpg_data)

    type_code: int | None = raw_type
    terminates = False
    if version == 2 and raw_type > 0x3F:
        type_code = None
        terminates = True
    elif raw_type == 0:
        terminates = True

    name = _record_name(version, type_code, raw_type)
    role = _record_role(version, type_code)
    return (
        WpgRecordPlan(
            index=index,
            raw_type_code=raw_type,
            type_code=type_code,
            name=name,
            role=role,
            header_range=(offset, payload_start),
            payload_range=(payload_start, payload_end),
            length_plan=length_plan,
            extension_plan=extension_plan,
            action=_preservation_action(role),
            terminates_record_list=terminates,
            evidence_ids=(
                WPG_RECORD_HEADER_SOURCE,
                WPG_VARINT_SOURCE,
                WPG_PAYLOAD_SKIP_SOURCE,
            ),
        ),
        payload_start + length_plan.value,
    )


def _read_varint(wpg_data: bytes, offset: int) -> WpgVarIntPlan:
    if offset >= len(wpg_data):
        return WpgVarIntPlan(
            start_offset=offset,
            end_offset=offset,
            encoded=b"",
            value=0,
            reason="truncated_wpg_record_length",
            evidence_ids=(WPG_VARINT_SOURCE,),
        )
    first = wpg_data[offset]
    if first != 0xFF:
        return WpgVarIntPlan(
            start_offset=offset,
            end_offset=offset + 1,
            encoded=wpg_data[offset : offset + 1],
            value=first,
            reason=None,
            evidence_ids=(WPG_VARINT_SOURCE,),
        )
    if offset + 3 > len(wpg_data):
        return WpgVarIntPlan(
            start_offset=offset,
            end_offset=len(wpg_data),
            encoded=wpg_data[offset:],
            value=0,
            reason="truncated_wpg_record_length",
            evidence_ids=(WPG_VARINT_SOURCE,),
        )
    high_word = int.from_bytes(wpg_data[offset + 1 : offset + 3], "little")
    if not high_word & 0x8000:
        return WpgVarIntPlan(
            start_offset=offset,
            end_offset=offset + 3,
            encoded=wpg_data[offset : offset + 3],
            value=high_word,
            reason=None,
            evidence_ids=(WPG_VARINT_SOURCE,),
        )
    if offset + 5 > len(wpg_data):
        return WpgVarIntPlan(
            start_offset=offset,
            end_offset=len(wpg_data),
            encoded=wpg_data[offset:],
            value=0,
            reason="truncated_wpg_record_length",
            evidence_ids=(WPG_VARINT_SOURCE,),
        )
    low_word = int.from_bytes(wpg_data[offset + 3 : offset + 5], "little")
    return WpgVarIntPlan(
        start_offset=offset,
        end_offset=offset + 5,
        encoded=wpg_data[offset : offset + 5],
        value=((high_word & 0x7FFF) << 16) | low_word,
        reason=None,
        evidence_ids=(WPG_VARINT_SOURCE,),
    )


def _collapse_records(
    records: tuple[WpgRecordPlan, ...],
    actions: list[WpgActionPlan],
) -> tuple[WpgCollapsedRecordPlan, ...]:
    collapsed: list[WpgCollapsedRecordPlan] = []
    current_type: int | None = None
    current_name = ""
    current_indexes: list[int] = []
    for record in records:
        if record.type_code is None or record.type_code == 0:
            break
        if current_type == record.type_code:
            current_indexes.append(record.index)
            continue
        if current_type is not None:
            collapsed.append(_collapsed_record(current_type, current_name, current_indexes))
        current_type = record.type_code
        current_name = record.name
        current_indexes = [record.index]
    if current_type is not None:
        collapsed.append(_collapsed_record(current_type, current_name, current_indexes))
    if collapsed:
        actions.append(
            WpgActionPlan(
                kind="collapse_record_sequence",
                target="Records",
                byte_range=None,
                reason="Collapsed adjacent matching record codes as ExifTool does.",
                evidence_ids=(WPG_COLLAPSE_SOURCE, WPG_PRINT_RECORD_SOURCE),
            )
        )
    return tuple(collapsed)


def _collapsed_record(
    type_code: int,
    name: str,
    indexes: list[int],
) -> WpgCollapsedRecordPlan:
    count = len(indexes)
    exiftool_value = f"{type_code}x{count}" if count > 1 else str(type_code)
    display_value = f"{name} x {count}" if count > 1 else name
    return WpgCollapsedRecordPlan(
        type_code=type_code,
        name=name,
        count=count,
        exiftool_value=exiftool_value,
        display_value=display_value,
        record_indexes=tuple(indexes),
        evidence_ids=(WPG_COLLAPSE_SOURCE, WPG_PRINT_RECORD_SOURCE),
    )


def _extract_dimensions(
    wpg_data: bytes,
    header: WpgHeaderValidationPlan,
    records: tuple[WpgRecordPlan, ...],
    gates: list[WpgOutputEmissionGate],
    actions: list[WpgActionPlan],
) -> WpgDimensionPlan:
    if header.version is None:
        return _empty_dimensions(None)
    start_type = 0x0F if header.version == 1 else 0x01
    for record in records:
        if record.type_code != start_type:
            continue
        dimensions = (
            _extract_v1_dimensions(wpg_data, record)
            if header.version == 1
            else _extract_v2_dimensions(wpg_data, record)
        )
        if dimensions.reason is not None:
            gates.append(
                WpgOutputEmissionGate(
                    code=dimensions.reason,
                    reason=(
                        "A Start WPG record did not contain a complete supported dimension layout."
                    ),
                    evidence_ids=(WPG_START_RECORD_SOURCE,),
                )
            )
        actions.append(
            WpgActionPlan(
                kind="extract_dimensions",
                target=record.name,
                byte_range=record.payload_range,
                reason="Extracted ImageWidthInches and ImageHeightInches from a Start WPG record.",
                evidence_ids=(WPG_START_RECORD_SOURCE, WPG_MAIN_TABLE_SOURCE),
            )
        )
        return dimensions
    return _empty_dimensions(None)


def _extract_v1_dimensions(wpg_data: bytes, record: WpgRecordPlan) -> WpgDimensionPlan:
    start, end = record.payload_range
    if end - start < 6:
        return _empty_dimensions("truncated_wpg_start_record", record.index)
    width = int.from_bytes(wpg_data[start + 2 : start + 4], "little")
    height = int.from_bytes(wpg_data[start + 4 : start + 6], "little")
    return WpgDimensionPlan(
        record_index=record.index,
        width_units=width,
        height_units=height,
        x_resolution=None,
        y_resolution=None,
        width_inches=width / WPG_DEFAULT_RESOLUTION,
        height_inches=height / WPG_DEFAULT_RESOLUTION,
        precision=None,
        reason=None,
        evidence_ids=(WPG_START_RECORD_SOURCE, WPG_MAIN_TABLE_SOURCE),
    )


def _extract_v2_dimensions(wpg_data: bytes, record: WpgRecordPlan) -> WpgDimensionPlan:
    start, end = record.payload_range
    length = end - start
    if length < 5:
        return _empty_dimensions("truncated_wpg_start_record", record.index)
    x_resolution = int.from_bytes(wpg_data[start : start + 2], "little")
    y_resolution = int.from_bytes(wpg_data[start + 2 : start + 4], "little")
    precision = wpg_data[start + 4]
    if precision == 0 and length >= 21:
        x1, y1, x2, y2 = _read_signed_sequence(wpg_data, start + 13, 2, 4)
    elif precision == 1 and length >= 29:
        x1, y1, x2, y2 = _read_signed_sequence(wpg_data, start + 13, 4, 4)
    elif precision in {0, 1}:
        return _empty_dimensions("truncated_wpg_start_record", record.index, precision)
    else:
        return _empty_dimensions("invalid_wpg_start_precision", record.index, precision)
    width = abs(x2 - x1)
    height = abs(y2 - y1)
    x_divisor = x_resolution or WPG_DEFAULT_RESOLUTION
    y_divisor = y_resolution or WPG_DEFAULT_RESOLUTION
    return WpgDimensionPlan(
        record_index=record.index,
        width_units=width,
        height_units=height,
        x_resolution=x_resolution,
        y_resolution=y_resolution,
        width_inches=width / x_divisor,
        height_inches=height / y_divisor,
        precision=precision,
        reason=None,
        evidence_ids=(WPG_START_RECORD_SOURCE, WPG_MAIN_TABLE_SOURCE),
    )


def _read_signed_sequence(
    wpg_data: bytes,
    offset: int,
    width: int,
    count: int,
) -> tuple[int, int, int, int]:
    values: list[int] = []
    for index in range(count):
        start = offset + index * width
        values.append(int.from_bytes(wpg_data[start : start + width], "little", signed=True))
    return values[0], values[1], values[2], values[3]


def _build_responsibilities(
    records: tuple[WpgRecordPlan, ...],
    dimensions: WpgDimensionPlan,
) -> WpgImageResponsibilityPlan:
    return WpgImageResponsibilityPlan(
        dimension_record_index=dimensions.record_index,
        color_record_indexes=_indexes_for_role(records, "color"),
        raster_record_indexes=_indexes_for_role(records, "raster"),
        vector_record_indexes=_indexes_for_role(records, "vector"),
        preview_record_indexes=_indexes_for_role(records, "preview"),
        metadata_record_indexes=_indexes_for_role(records, "metadata"),
        unknown_record_indexes=_indexes_for_role(records, "unknown"),
        color_depth_bits=None,
        compression=None,
        evidence_ids=(WPG_MAIN_TABLE_SOURCE, WPG_START_RECORD_SOURCE),
    )


def _build_payload_preservation(
    records: tuple[WpgRecordPlan, ...],
    actions: list[WpgActionPlan],
) -> tuple[WpgPayloadPreservationPlan, ...]:
    plans: list[WpgPayloadPreservationPlan] = []
    for role in ("vector", "raster", "preview", "metadata", "color", "unknown"):
        role_indexes = _indexes_for_role(records, role)
        if not role_indexes:
            continue
        byte_ranges = tuple(records[index].payload_range for index in role_indexes)
        action = _preservation_action(role)
        plans.append(
            WpgPayloadPreservationPlan(
                role=role,
                record_indexes=role_indexes,
                byte_ranges=byte_ranges,
                action=action,
                reason=(
                    "ExifTool's WPG reader records or skips payload ranges without rewriting them."
                ),
                evidence_ids=(WPG_PAYLOAD_SKIP_SOURCE, WPG_DESCRIPTION_SOURCE),
            )
        )
        for index in role_indexes:
            actions.append(
                WpgActionPlan(
                    kind=action,
                    target=records[index].name,
                    byte_range=records[index].payload_range,
                    reason="Preserved the original WPG record payload bytes.",
                    evidence_ids=(WPG_PAYLOAD_SKIP_SOURCE, WPG_DESCRIPTION_SOURCE),
                )
            )
    return tuple(plans)


def _indexes_for_role(
    records: tuple[WpgRecordPlan, ...],
    role: WpgRecordRole,
) -> tuple[int, ...]:
    return tuple(record.index for record in records if record.role == role)


def _record_name(version: int, type_code: int | None, raw_type: int) -> str:
    if type_code is None:
        return f"Unknown (0x{raw_type:02x})"
    names = WPG_V1_RECORD_NAMES if version == 1 else WPG_V2_RECORD_NAMES
    return names.get(type_code, f"Unknown (0x{type_code:02x})")


def _record_role(version: int, type_code: int | None) -> WpgRecordRole:
    if type_code is None:
        return "unknown"
    if version == 1:
        if type_code in {0x0F, 0x10, 0x12, 0x15, 0x16, 0x19}:
            return "control"
        if type_code in {0x0B, 0x14}:
            return "raster"
        if type_code == 0x0E:
            return "color"
        if type_code in {0x0C, 0x0D, 0x11, 0x17, 0x18, 0x1A, 0x1B}:
            return "metadata"
        if type_code in WPG_V1_RECORD_NAMES:
            return "vector"
        return "unknown"
    if type_code in {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x38, 0x39}:
        return "control"
    if type_code in {0x0E, 0x1B}:
        return "raster"
    if type_code == 0x12:
        return "preview"
    if type_code in {0x0B, 0x0C, 0x0D, 0x25, 0x26, 0x27, 0x28, 0x31, 0x32, 0x33, 0x34}:
        return "color"
    if type_code in {0x0A, 0x0F, 0x10, 0x11, 0x1C, 0x1D, 0x1E, 0x1F, 0x22}:
        return "metadata"
    if type_code in WPG_V2_RECORD_NAMES:
        return "vector"
    return "unknown"


def _preservation_action(role: WpgRecordRole) -> WpgActionKind:
    if role == "raster":
        return "preserve_raster_payload"
    if role == "preview":
        return "preserve_preview_payload"
    if role == "metadata":
        return "preserve_metadata_payload"
    if role == "color":
        return "preserve_color_payload"
    if role == "unknown":
        return "preserve_unknown_payload"
    return "preserve_vector_payload"


def _empty_dimensions(
    reason: WpgEmissionGateCode | None,
    record_index: int | None = None,
    precision: int | None = None,
) -> WpgDimensionPlan:
    return WpgDimensionPlan(
        record_index=record_index,
        width_units=None,
        height_units=None,
        x_resolution=None,
        y_resolution=None,
        width_inches=None,
        height_inches=None,
        precision=precision,
        reason=reason,
        evidence_ids=(WPG_START_RECORD_SOURCE, WPG_MAIN_TABLE_SOURCE),
    )


def _final_plan(
    *,
    status: WpgPlanStatus,
    source_data: bytes,
    header: WpgHeaderValidationPlan,
    records: tuple[WpgRecordPlan, ...],
    collapsed_records: tuple[WpgCollapsedRecordPlan, ...],
    dimensions: WpgDimensionPlan,
    rewrite_requests: tuple[WpgRewriteRequest, ...],
    actions: tuple[WpgActionPlan, ...],
    gates: list[WpgOutputEmissionGate],
    allow_output_emission: bool,
) -> WpgImageTransactionPlan:
    responsibilities = _build_responsibilities(records, dimensions)
    return _finish_plan(
        status=status,
        source_data=source_data,
        header=header,
        records=records,
        collapsed_records=collapsed_records,
        dimensions=dimensions,
        responsibilities=responsibilities,
        preservation=(),
        rewrite_requests=rewrite_requests,
        actions=actions,
        gates=gates,
        allow_output_emission=allow_output_emission,
    )


def _finish_plan(
    *,
    status: WpgPlanStatus,
    source_data: bytes,
    header: WpgHeaderValidationPlan,
    records: tuple[WpgRecordPlan, ...],
    collapsed_records: tuple[WpgCollapsedRecordPlan, ...],
    dimensions: WpgDimensionPlan,
    responsibilities: WpgImageResponsibilityPlan,
    preservation: tuple[WpgPayloadPreservationPlan, ...],
    rewrite_requests: tuple[WpgRewriteRequest, ...],
    actions: tuple[WpgActionPlan, ...],
    gates: list[WpgOutputEmissionGate],
    allow_output_emission: bool,
) -> WpgImageTransactionPlan:
    if status == "planned" and not allow_output_emission:
        gates.append(
            WpgOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="WPG plans are non-mutating unless output emission is explicitly enabled.",
                evidence_ids=(WPG_DESCRIPTION_SOURCE,),
            )
        )
    evidence_ids = _unique_sources(
        header.evidence_ids
        + tuple(reference for record in records for reference in record.evidence_ids)
        + tuple(
            reference for collapsed in collapsed_records for reference in collapsed.evidence_ids
        )
        + dimensions.evidence_ids
        + responsibilities.evidence_ids
        + tuple(reference for item in preservation for reference in item.evidence_ids)
        + tuple(reference for action in actions for reference in action.evidence_ids)
        + tuple(reference for gate in gates for reference in gate.evidence_ids)
    )
    return WpgImageTransactionPlan(
        status=status,
        source_data=source_data,
        header_validation=header,
        records=records,
        collapsed_records=collapsed_records,
        dimensions=dimensions,
        responsibilities=responsibilities,
        payload_preservation=preservation,
        rewrite_requests=rewrite_requests,
        actions=actions,
        output_emission_gates=tuple(gates),
        evidence_ids=evidence_ids,
    )


def _unique_sources(
    references: tuple[str, ...],
) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)
