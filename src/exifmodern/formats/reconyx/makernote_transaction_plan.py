"""Source-grounded Reconyx maker-note BinaryData transaction plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type ReconyxMakerNoteFamily = Literal["hyperfire", "ultrafire"]
type ReconyxPlanStatus = Literal["planned", "unsupported"]
type ReconyxBinaryFormat = Literal[
    "int8u", "int16u", "int16s", "int32u", "string", "unicode", "undef"
]
type ReconyxFieldRole = Literal[
    "identity",
    "version",
    "date_time",
    "moon",
    "temperature",
    "event",
    "camera",
    "label",
    "structural_marker",
]
type ReconyxConversionBoundary = Literal[
    "none",
    "print_conversion",
    "value_conversion",
    "string_bytes",
    "utf16le_unicode",
    "version_bytes",
]
type ReconyxWritableSurface = Literal[
    "read_only_identity", "writable_binary_data", "structural_marker"
]
type ReconyxPlanActionKind = Literal[
    "route_hyperfire_table",
    "route_ultrafire_table",
    "extract_field",
    "preserve_unknown_bytes",
    "preserve_payload",
    "apply_raw_binary_data_rewrite",
    "block_requested_rewrite",
]
type ReconyxEmissionGateCode = Literal[
    "truncated_reconyx_routing_marker",
    "unsupported_reconyx_makernote_table",
    "malformed_hyperfire_identity",
    "malformed_ultrafire_structure",
    "truncated_reconyx_binary_data",
    "unknown_rewrite_tag",
    "read_only_rewrite_tag",
    "rewrite_payload_size_mismatch",
    "duplicate_rewrite_tag",
    "rewrite_requires_explicit_output_emission",
    "non_mutating_plan_requires_explicit_emission",
]
type ReconyxInterpretedValue = int | str | tuple[int, ...] | bytes | None

RECONYX_PM_SOURCE_PATH = "lib/Image/ExifTool/Reconyx.pm"
RECONYX_BINARY_INCREMENT = 2
HYPERFIRE_MAKER_NOTE_VERSION = 0xF101
ULTRAFIRE_MAKER_NOTE_ID = 0x00020000
ULTRAFIRE_PUBLIC_STRUCTURE_ID = 0x7F100001

MOON_PHASES = {
    0: "New",
    1: "New Crescent",
    2: "First Quarter",
    3: "Waxing Gibbous",
    4: "Full",
    5: "Waning Gibbous",
    6: "Last Quarter",
    7: "Old Crescent",
}
SUNDAY_ZERO_DAYS = {
    0: "Sunday",
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
}
HYPERFIRE_TRIGGER_MODES = {
    "C": "CodeLoc Not Entered",
    "E": "External Sensor",
    "M": "Motion Detection",
    "T": "Time Lapse",
}
ULTRAFIRE_TRIGGER_MODES = {
    "M": "Motion Detection",
    "T": "Time Lapse",
    "P": "Point and Shoot",
}
ON_OFF = {0: "Off", 1: "On"}


def evidence_id(
    line_start: int,
    line_end: int,
    symbol: str,
    evidence: str,
) -> str:
    del line_start, line_end, evidence
    return "reconyx.makernote." + _evidence_token(symbol)


def _evidence_token(symbol: str) -> str:
    return (
        symbol.removeprefix("%Image::ExifTool::")
        .replace("::", ".")
        .replace("%", "")
        .replace(" ", "-")
        .lower()
    )


VERSION_INFO_SOURCE = evidence_id(
    20,
    25,
    "%versionInfo",
    "UltraFire version fields use seven-byte undef payloads and byte/word conversion.",
)
MOON_PHASE_SOURCE = evidence_id(
    27,
    36,
    "%moonPhase",
    "MoonPhase values 0 through 7 map to source labels.",
)
SUNDAY_ZERO_SOURCE = evidence_id(38, 46, "%sunday0", "UltraFire DayOfWeek starts at Sunday.")
UNICODE_CONVERSION_SOURCE = evidence_id(
    60,
    63,
    "%convUnicode",
    "Reconyx unicode fields decode and encode UTF-16 little-endian strings.",
)
HYPERFIRE_TABLE_SOURCE = evidence_id(
    66,
    188,
    "%Image::ExifTool::Reconyx::HyperFire",
    "HyperFire maker notes use a writable int16u BinaryData table.",
)
HYPERFIRE_IDENTITY_SOURCE = evidence_id(
    78,
    89,
    "HyperFire MakerNoteVersion and FirmwareVersion",
    "These fields are non-writable because they are used for identification.",
)
HYPERFIRE_DATETIME_SOURCE = evidence_id(
    108,
    132,
    "HyperFire DateTimeOriginal",
    "HyperFire DateTimeOriginal is six int16u values with a byte-swapped fallback.",
)
ULTRAFIRE_TABLE_SOURCE = evidence_id(
    190,
    278,
    "%Image::ExifTool::Reconyx::UltraFire",
    "UltraFire maker notes use a writable int16u BinaryData table.",
)
ULTRAFIRE_STRUCTURE_SOURCE = evidence_id(
    199,
    202,
    "UltraFire maker-note structure comments",
    "Reconyx.pm documents UltraFire maker-note and public structure identifiers.",
)
ULTRAFIRE_DATETIME_SOURCE = evidence_id(
    226,
    239,
    "UltraFire DateTimeOriginal",
    "UltraFire DateTimeOriginal is seven bytes unpacked as C5v then reversed.",
)
RECONYX_WRITE_PROC_SOURCE = evidence_id(
    70,
    74,
    "Reconyx BinaryData write surface",
    "Reconyx tables declare WriteBinaryData and CheckBinaryData.",
)


@dataclass(frozen=True)
class ReconyxRewriteRequest:
    tag_name: str
    raw_payload: bytes


@dataclass(frozen=True)
class ReconyxTagSpec:
    name: str
    tag_id: int
    binary_format: ReconyxBinaryFormat
    count: int
    writable_surface: ReconyxWritableSurface
    role: ReconyxFieldRole
    conversion_boundary: ReconyxConversionBoundary
    evidence_ids: tuple[str, ...]

    @property
    def offset(self) -> int:
        return self.tag_id * RECONYX_BINARY_INCREMENT

    @property
    def byte_count(self) -> int:
        if self.binary_format == "int8u":
            return self.count
        if self.binary_format in {"int16u", "int16s", "unicode"}:
            return self.count * 2
        if self.binary_format == "int32u":
            return self.count * 4
        return self.count


@dataclass(frozen=True)
class ReconyxRoutingPlan:
    requested_family: ReconyxMakerNoteFamily | None
    selected_family: ReconyxMakerNoteFamily | None
    reason: str
    gate_code: ReconyxEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReconyxFieldPlan:
    tag_name: str
    tag_id: int
    byte_range: tuple[int, int]
    binary_format: ReconyxBinaryFormat
    raw_payload: bytes
    raw_values: tuple[int, ...] | bytes | str
    interpreted_value: ReconyxInterpretedValue
    writable_surface: ReconyxWritableSurface
    role: ReconyxFieldRole
    conversion_boundary: ReconyxConversionBoundary
    evidence_ids: tuple[str, ...]

    @property
    def is_writable_binary_data(self) -> bool:
        return self.writable_surface == "writable_binary_data"


@dataclass(frozen=True)
class ReconyxPreservationPlan:
    payload_range: tuple[int, int]
    unknown_ranges: tuple[tuple[int, int], ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReconyxRewriteStepPlan:
    tag_name: str
    byte_range: tuple[int, int]
    replacement_payload: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReconyxActionPlan:
    kind: ReconyxPlanActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReconyxOutputEmissionGate:
    code: ReconyxEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReconyxMakerNoteTransactionPlan:
    status: ReconyxPlanStatus
    source_data: bytes
    routing: ReconyxRoutingPlan
    fields: tuple[ReconyxFieldPlan, ...]
    preservation: ReconyxPreservationPlan
    rewrite_steps: tuple[ReconyxRewriteStepPlan, ...]
    actions: tuple[ReconyxActionPlan, ...]
    output_emission_gates: tuple[ReconyxOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def writable_binary_data_tags(self) -> tuple[str, ...]:
        return tuple(field.tag_name for field in self.fields if field.is_writable_binary_data)

    def field(self, tag_name: str) -> ReconyxFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Reconyx maker-note transaction output is gated: {gate_codes}")
        mutable = bytearray(self.source_data)
        for step in self.rewrite_steps:
            start, end = step.byte_range
            mutable[start:end] = step.replacement_payload
        return bytes(mutable)


def tag(
    name: str,
    tag_id: int,
    binary_format: ReconyxBinaryFormat,
    count: int,
    writable_surface: ReconyxWritableSurface,
    role: ReconyxFieldRole,
    conversion_boundary: ReconyxConversionBoundary,
    evidence_ids: tuple[str, ...],
) -> ReconyxTagSpec:
    return ReconyxTagSpec(
        name,
        tag_id,
        binary_format,
        count,
        writable_surface,
        role,
        conversion_boundary,
        evidence_ids,
    )


HYPERFIRE_TAGS: tuple[ReconyxTagSpec, ...] = (
    tag(
        "MakerNoteVersion",
        0x00,
        "int16u",
        1,
        "read_only_identity",
        "identity",
        "print_conversion",
        (HYPERFIRE_TABLE_SOURCE, HYPERFIRE_IDENTITY_SOURCE),
    ),
    tag(
        "FirmwareVersion",
        0x01,
        "int16u",
        3,
        "read_only_identity",
        "version",
        "print_conversion",
        (HYPERFIRE_TABLE_SOURCE, HYPERFIRE_IDENTITY_SOURCE),
    ),
    tag(
        "FirmwareDate",
        0x04,
        "int16u",
        2,
        "writable_binary_data",
        "date_time",
        "value_conversion",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "TriggerMode",
        0x06,
        "string",
        2,
        "writable_binary_data",
        "event",
        "print_conversion",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "Sequence",
        0x07,
        "int16u",
        2,
        "writable_binary_data",
        "event",
        "print_conversion",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "EventNumber",
        0x09,
        "int16u",
        2,
        "writable_binary_data",
        "event",
        "value_conversion",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "DateTimeOriginal",
        0x0B,
        "int16u",
        6,
        "writable_binary_data",
        "date_time",
        "value_conversion",
        (HYPERFIRE_TABLE_SOURCE, HYPERFIRE_DATETIME_SOURCE),
    ),
    tag(
        "MoonPhase",
        0x12,
        "int16u",
        1,
        "writable_binary_data",
        "moon",
        "print_conversion",
        (HYPERFIRE_TABLE_SOURCE, MOON_PHASE_SOURCE),
    ),
    tag(
        "AmbientTemperatureFahrenheit",
        0x13,
        "int16s",
        1,
        "writable_binary_data",
        "temperature",
        "print_conversion",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "AmbientTemperature",
        0x14,
        "int16s",
        1,
        "writable_binary_data",
        "temperature",
        "print_conversion",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "SerialNumber",
        0x15,
        "unicode",
        15,
        "writable_binary_data",
        "camera",
        "utf16le_unicode",
        (HYPERFIRE_TABLE_SOURCE, UNICODE_CONVERSION_SOURCE),
    ),
    tag(
        "Contrast",
        0x24,
        "int16u",
        1,
        "writable_binary_data",
        "camera",
        "none",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "Brightness",
        0x25,
        "int16u",
        1,
        "writable_binary_data",
        "camera",
        "none",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "Sharpness",
        0x26,
        "int16u",
        1,
        "writable_binary_data",
        "camera",
        "none",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "Saturation",
        0x27,
        "int16u",
        1,
        "writable_binary_data",
        "camera",
        "none",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "InfraredIlluminator",
        0x28,
        "int16u",
        1,
        "writable_binary_data",
        "camera",
        "print_conversion",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "MotionSensitivity",
        0x29,
        "int16u",
        1,
        "writable_binary_data",
        "camera",
        "none",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "BatteryVoltage",
        0x2A,
        "int16u",
        1,
        "writable_binary_data",
        "camera",
        "value_conversion",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
    tag(
        "UserLabel",
        0x2B,
        "string",
        22,
        "writable_binary_data",
        "label",
        "string_bytes",
        (HYPERFIRE_TABLE_SOURCE,),
    ),
)

ULTRAFIRE_TAGS: tuple[ReconyxTagSpec, ...] = (
    tag(
        "MakerNoteStructureID",
        0x0A,
        "int32u",
        1,
        "structural_marker",
        "structural_marker",
        "none",
        (ULTRAFIRE_TABLE_SOURCE, ULTRAFIRE_STRUCTURE_SOURCE),
    ),
    tag(
        "PublicStructureID",
        0x12,
        "int32u",
        1,
        "structural_marker",
        "structural_marker",
        "none",
        (ULTRAFIRE_TABLE_SOURCE, ULTRAFIRE_STRUCTURE_SOURCE),
    ),
    tag(
        "FirmwareVersion",
        0x18,
        "undef",
        7,
        "writable_binary_data",
        "version",
        "version_bytes",
        (ULTRAFIRE_TABLE_SOURCE, VERSION_INFO_SOURCE),
    ),
    tag(
        "Micro1Version",
        0x1F,
        "undef",
        7,
        "writable_binary_data",
        "version",
        "version_bytes",
        (ULTRAFIRE_TABLE_SOURCE, VERSION_INFO_SOURCE),
    ),
    tag(
        "BootLoaderVersion",
        0x26,
        "undef",
        7,
        "writable_binary_data",
        "version",
        "version_bytes",
        (ULTRAFIRE_TABLE_SOURCE, VERSION_INFO_SOURCE),
    ),
    tag(
        "Micro2Version",
        0x2D,
        "undef",
        7,
        "writable_binary_data",
        "version",
        "version_bytes",
        (ULTRAFIRE_TABLE_SOURCE, VERSION_INFO_SOURCE),
    ),
    tag(
        "TriggerMode",
        0x34,
        "undef",
        1,
        "writable_binary_data",
        "event",
        "print_conversion",
        (ULTRAFIRE_TABLE_SOURCE,),
    ),
    tag(
        "Sequence",
        0x35,
        "int8u",
        2,
        "writable_binary_data",
        "event",
        "print_conversion",
        (ULTRAFIRE_TABLE_SOURCE,),
    ),
    tag(
        "EventNumber",
        0x37,
        "int32u",
        1,
        "writable_binary_data",
        "event",
        "none",
        (ULTRAFIRE_TABLE_SOURCE,),
    ),
    tag(
        "DateTimeOriginal",
        0x3B,
        "int8u",
        7,
        "writable_binary_data",
        "date_time",
        "value_conversion",
        (ULTRAFIRE_TABLE_SOURCE, ULTRAFIRE_DATETIME_SOURCE),
    ),
    tag(
        "DayOfWeek",
        0x42,
        "int16u",
        1,
        "writable_binary_data",
        "date_time",
        "print_conversion",
        (ULTRAFIRE_TABLE_SOURCE, SUNDAY_ZERO_SOURCE),
    ),
    tag(
        "MoonPhase",
        0x43,
        "int16u",
        1,
        "writable_binary_data",
        "moon",
        "print_conversion",
        (ULTRAFIRE_TABLE_SOURCE, MOON_PHASE_SOURCE),
    ),
    tag(
        "AmbientTemperatureFahrenheit",
        0x44,
        "int16s",
        1,
        "writable_binary_data",
        "temperature",
        "print_conversion",
        (ULTRAFIRE_TABLE_SOURCE,),
    ),
    tag(
        "AmbientTemperature",
        0x46,
        "int16s",
        1,
        "writable_binary_data",
        "temperature",
        "print_conversion",
        (ULTRAFIRE_TABLE_SOURCE,),
    ),
    tag(
        "Illumination",
        0x48,
        "int16u",
        1,
        "writable_binary_data",
        "camera",
        "print_conversion",
        (ULTRAFIRE_TABLE_SOURCE,),
    ),
    tag(
        "BatteryVoltage",
        0x49,
        "int16u",
        1,
        "writable_binary_data",
        "camera",
        "value_conversion",
        (ULTRAFIRE_TABLE_SOURCE,),
    ),
    tag(
        "SerialNumber",
        0x4B,
        "string",
        15,
        "writable_binary_data",
        "camera",
        "string_bytes",
        (ULTRAFIRE_TABLE_SOURCE,),
    ),
    tag(
        "UserLabel",
        0x5A,
        "string",
        21,
        "writable_binary_data",
        "label",
        "string_bytes",
        (ULTRAFIRE_TABLE_SOURCE,),
    ),
)


def build_reconyx_makernote_transaction_plan(
    maker_note_data: bytes,
    *,
    family: ReconyxMakerNoteFamily | None = None,
    rewrite_requests: tuple[ReconyxRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> ReconyxMakerNoteTransactionPlan:
    routing = build_routing_plan(maker_note_data, family)
    gates = routing_gates(routing)
    fields: tuple[ReconyxFieldPlan, ...] = ()
    preservation = ReconyxPreservationPlan(
        (0, len(maker_note_data)), (), (RECONYX_WRITE_PROC_SOURCE,)
    )
    if routing.selected_family is not None:
        specs = tag_specs_for_family(routing.selected_family)
        if truncation_gate := validate_selected_table(
            maker_note_data, routing.selected_family, specs
        ):
            gates = (*gates, truncation_gate)
        else:
            fields = tuple(
                build_field_plan(maker_note_data, routing.selected_family, spec) for spec in specs
            )
            preservation = ReconyxPreservationPlan(
                (0, len(maker_note_data)),
                unknown_ranges(len(maker_note_data), tuple(field.byte_range for field in fields)),
                (RECONYX_WRITE_PROC_SOURCE,),
            )
    rewrite_steps, rewrite_gates = build_rewrite_steps(fields, rewrite_requests)
    gates = (*gates, *rewrite_gates)
    gates = add_permission_gate(gates, rewrite_requests, allow_output_emission)
    unique_gates = unique_gates_tuple(gates)
    actions = build_actions(
        routing, fields, preservation, rewrite_steps, rewrite_requests, unique_gates
    )
    status: ReconyxPlanStatus = (
        "unsupported" if structural_gate_present(unique_gates) else "planned"
    )
    return ReconyxMakerNoteTransactionPlan(
        status,
        maker_note_data,
        routing,
        fields,
        preservation,
        rewrite_steps,
        actions,
        unique_gates,
        evidence_ids_for_plan(routing, fields, preservation, rewrite_steps, unique_gates),
    )


def routing_gates(routing: ReconyxRoutingPlan) -> tuple[ReconyxOutputEmissionGate, ...]:
    if routing.gate_code is None:
        return ()
    return (ReconyxOutputEmissionGate(routing.gate_code, routing.reason, routing.evidence_ids),)


def add_permission_gate(
    gates: tuple[ReconyxOutputEmissionGate, ...],
    rewrite_requests: tuple[ReconyxRewriteRequest, ...],
    allow_output_emission: bool,
) -> tuple[ReconyxOutputEmissionGate, ...]:
    if allow_output_emission:
        return gates
    if rewrite_requests and not any(
        gate.code in unsupported_rewrite_gate_codes() for gate in gates
    ):
        return (
            *gates,
            ReconyxOutputEmissionGate(
                "rewrite_requires_explicit_output_emission",
                "Supported Reconyx raw BinaryData rewrites require explicit output emission.",
                (RECONYX_WRITE_PROC_SOURCE,),
            ),
        )
    if not rewrite_requests:
        return (
            *gates,
            ReconyxOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "Default Reconyx plans preserve bytes and require explicit output emission.",
                (RECONYX_WRITE_PROC_SOURCE,),
            ),
        )
    return gates


def build_routing_plan(
    data: bytes,
    requested_family: ReconyxMakerNoteFamily | None,
) -> ReconyxRoutingPlan:
    if requested_family == "hyperfire":
        return validate_hyperfire_route(data, requested_family)
    if requested_family == "ultrafire":
        return validate_ultrafire_route(data, requested_family)
    if len(data) < 2:
        return ReconyxRoutingPlan(
            None,
            None,
            "Reconyx maker-note data is too short to read the HyperFire identity word.",
            "truncated_reconyx_routing_marker",
            (HYPERFIRE_IDENTITY_SOURCE,),
        )
    if read_unsigned(data, 0, 2) == HYPERFIRE_MAKER_NOTE_VERSION:
        return validate_hyperfire_route(data, None)
    ultra_offset = 0x0A * RECONYX_BINARY_INCREMENT
    public_offset = 0x12 * RECONYX_BINARY_INCREMENT
    if len(data) >= public_offset + 4:
        if (
            read_unsigned(data, ultra_offset, 4) == ULTRAFIRE_MAKER_NOTE_ID
            and read_unsigned(data, public_offset, 4) == ULTRAFIRE_PUBLIC_STRUCTURE_ID
        ):
            return validate_ultrafire_route(data, None)
    return ReconyxRoutingPlan(
        None,
        None,
        "Maker-note bytes do not match HyperFire identity or UltraFire structure markers.",
        "unsupported_reconyx_makernote_table",
        (HYPERFIRE_IDENTITY_SOURCE, ULTRAFIRE_STRUCTURE_SOURCE),
    )


def validate_hyperfire_route(
    data: bytes,
    requested_family: ReconyxMakerNoteFamily | None,
) -> ReconyxRoutingPlan:
    if len(data) < 2:
        return ReconyxRoutingPlan(
            requested_family,
            None,
            "HyperFire routing requires the MakerNoteVersion identity word.",
            "truncated_reconyx_routing_marker",
            (HYPERFIRE_IDENTITY_SOURCE,),
        )
    if read_unsigned(data, 0, 2) != HYPERFIRE_MAKER_NOTE_VERSION:
        return ReconyxRoutingPlan(
            requested_family,
            None,
            "HyperFire MakerNoteVersion does not match Reconyx.pm.",
            "malformed_hyperfire_identity",
            (HYPERFIRE_IDENTITY_SOURCE,),
        )
    return ReconyxRoutingPlan(
        requested_family,
        "hyperfire",
        "HyperFire table selected from MakerNoteVersion identity.",
        None,
        (HYPERFIRE_TABLE_SOURCE, HYPERFIRE_IDENTITY_SOURCE),
    )


def validate_ultrafire_route(
    data: bytes,
    requested_family: ReconyxMakerNoteFamily | None,
) -> ReconyxRoutingPlan:
    ultra_offset = 0x0A * RECONYX_BINARY_INCREMENT
    public_offset = 0x12 * RECONYX_BINARY_INCREMENT
    if len(data) < public_offset + 4:
        return ReconyxRoutingPlan(
            requested_family,
            None,
            "UltraFire routing requires documented structure markers.",
            "truncated_reconyx_routing_marker",
            (ULTRAFIRE_STRUCTURE_SOURCE,),
        )
    if (
        read_unsigned(data, ultra_offset, 4) != ULTRAFIRE_MAKER_NOTE_ID
        or read_unsigned(data, public_offset, 4) != ULTRAFIRE_PUBLIC_STRUCTURE_ID
    ):
        return ReconyxRoutingPlan(
            requested_family,
            None,
            "UltraFire structure markers do not match Reconyx.pm.",
            "malformed_ultrafire_structure",
            (ULTRAFIRE_STRUCTURE_SOURCE,),
        )
    return ReconyxRoutingPlan(
        requested_family,
        "ultrafire",
        "UltraFire table selected from documented structure markers.",
        None,
        (ULTRAFIRE_TABLE_SOURCE, ULTRAFIRE_STRUCTURE_SOURCE),
    )


def validate_selected_table(
    data: bytes,
    family: ReconyxMakerNoteFamily,
    specs: tuple[ReconyxTagSpec, ...],
) -> ReconyxOutputEmissionGate | None:
    required_length = max(spec.offset + spec.byte_count for spec in specs)
    if len(data) >= required_length:
        return None
    source = HYPERFIRE_TABLE_SOURCE if family == "hyperfire" else ULTRAFIRE_TABLE_SOURCE
    return ReconyxOutputEmissionGate(
        "truncated_reconyx_binary_data",
        f"Reconyx {family} BinaryData is shorter than the source fixed field surface.",
        (source,),
    )


def build_field_plan(
    data: bytes,
    family: ReconyxMakerNoteFamily,
    spec: ReconyxTagSpec,
) -> ReconyxFieldPlan:
    start = spec.offset
    end = start + spec.byte_count
    payload = data[start:end]
    raw_values = raw_field_values(payload, spec)
    return ReconyxFieldPlan(
        spec.name,
        spec.tag_id,
        (start, end),
        spec.binary_format,
        payload,
        raw_values,
        interpreted_field_value(family, spec.name, payload, raw_values),
        spec.writable_surface,
        spec.role,
        spec.conversion_boundary,
        spec.evidence_ids,
    )


def raw_field_values(payload: bytes, spec: ReconyxTagSpec) -> tuple[int, ...] | bytes | str:
    if spec.binary_format == "string":
        return decode_string(payload)
    if spec.binary_format in {"undef", "unicode"}:
        return payload
    byte_count = field_scalar_byte_count(spec.binary_format)
    return tuple(
        read_integer(payload[index : index + byte_count], spec.binary_format)
        for index in range(0, len(payload), byte_count)
    )


def interpreted_field_value(
    family: ReconyxMakerNoteFamily,
    tag_name: str,
    payload: bytes,
    raw_values: tuple[int, ...] | bytes | str,
) -> ReconyxInterpretedValue:
    if family == "hyperfire":
        return interpreted_hyperfire_value(tag_name, payload, raw_values)
    return interpreted_ultrafire_value(tag_name, payload, raw_values)


def interpreted_hyperfire_value(
    tag_name: str,
    payload: bytes,
    raw_values: tuple[int, ...] | bytes | str,
) -> ReconyxInterpretedValue:
    if tag_name == "MakerNoteVersion" and isinstance(raw_values, tuple):
        return f"0x{raw_values[0]:04x}"
    if tag_name == "FirmwareVersion" and isinstance(raw_values, tuple):
        return ".".join(str(value) for value in raw_values)
    if tag_name == "FirmwareDate" and isinstance(raw_values, tuple):
        return firmware_date_value(raw_values)
    if tag_name == "TriggerMode" and isinstance(raw_values, str):
        return HYPERFIRE_TRIGGER_MODES.get(raw_values[:1], raw_values[:1])
    if tag_name == "Sequence" and isinstance(raw_values, tuple):
        return f"{raw_values[0]} of {raw_values[1]}"
    if tag_name == "EventNumber" and isinstance(raw_values, tuple):
        return (raw_values[0] << 16) + raw_values[1]
    if tag_name == "DateTimeOriginal" and isinstance(raw_values, tuple):
        return hyperfire_datetime(raw_values)
    if tag_name == "MoonPhase" and isinstance(raw_values, tuple):
        return MOON_PHASES.get(raw_values[0], raw_values[0])
    if tag_name == "AmbientTemperatureFahrenheit" and isinstance(raw_values, tuple):
        return f"{raw_values[0]} F"
    if tag_name == "AmbientTemperature" and isinstance(raw_values, tuple):
        return f"{raw_values[0]} C"
    if tag_name == "SerialNumber":
        return decode_utf16le(payload)
    if tag_name == "InfraredIlluminator" and isinstance(raw_values, tuple):
        return ON_OFF.get(raw_values[0], raw_values[0])
    if tag_name == "BatteryVoltage" and isinstance(raw_values, tuple):
        return voltage_value(raw_values[0])
    return raw_values


def interpreted_ultrafire_value(
    tag_name: str,
    payload: bytes,
    raw_values: tuple[int, ...] | bytes | str,
) -> ReconyxInterpretedValue:
    if tag_name in {"FirmwareVersion", "Micro1Version", "BootLoaderVersion", "Micro2Version"}:
        return version_info_value(payload)
    if tag_name == "TriggerMode":
        mode = payload[:1].decode("latin-1")
        return ULTRAFIRE_TRIGGER_MODES.get(mode, mode)
    if tag_name == "Sequence" and isinstance(raw_values, tuple):
        return f"{raw_values[0]} of {raw_values[1]}"
    if tag_name == "EventNumber" and isinstance(raw_values, tuple):
        return raw_values[0]
    if tag_name == "DateTimeOriginal":
        return ultrafire_datetime(payload)
    if tag_name == "DayOfWeek" and isinstance(raw_values, tuple):
        return SUNDAY_ZERO_DAYS.get(raw_values[0], raw_values[0])
    if tag_name == "MoonPhase" and isinstance(raw_values, tuple):
        return MOON_PHASES.get(raw_values[0], raw_values[0])
    if tag_name == "AmbientTemperatureFahrenheit" and isinstance(raw_values, tuple):
        return f"{raw_values[0]} F"
    if tag_name == "AmbientTemperature" and isinstance(raw_values, tuple):
        return f"{raw_values[0]} C"
    if tag_name == "Illumination" and isinstance(raw_values, tuple):
        return ON_OFF.get(raw_values[0], raw_values[0])
    if tag_name == "BatteryVoltage" and isinstance(raw_values, tuple):
        return voltage_value(raw_values[0])
    return raw_values


def build_rewrite_steps(
    fields: tuple[ReconyxFieldPlan, ...],
    rewrite_requests: tuple[ReconyxRewriteRequest, ...],
) -> tuple[tuple[ReconyxRewriteStepPlan, ...], tuple[ReconyxOutputEmissionGate, ...]]:
    steps: list[ReconyxRewriteStepPlan] = []
    gates: list[ReconyxOutputEmissionGate] = []
    seen_tags: set[str] = set()
    for request in rewrite_requests:
        if request.tag_name in seen_tags:
            gates.append(
                rewrite_gate(
                    "duplicate_rewrite_tag", request.tag_name, (RECONYX_WRITE_PROC_SOURCE,)
                )
            )
            continue
        seen_tags.add(request.tag_name)
        field = field_by_name(fields, request.tag_name)
        if field is None:
            gates.append(
                rewrite_gate("unknown_rewrite_tag", request.tag_name, (RECONYX_WRITE_PROC_SOURCE,))
            )
            continue
        if not field.is_writable_binary_data:
            gates.append(
                rewrite_gate("read_only_rewrite_tag", request.tag_name, field.evidence_ids)
            )
            continue
        start, end = field.byte_range
        if len(request.raw_payload) != end - start:
            gates.append(
                rewrite_gate("rewrite_payload_size_mismatch", request.tag_name, field.evidence_ids)
            )
            continue
        steps.append(
            ReconyxRewriteStepPlan(
                request.tag_name,
                field.byte_range,
                request.raw_payload,
                (*field.evidence_ids, RECONYX_WRITE_PROC_SOURCE),
            )
        )
    return tuple(steps), tuple(gates)


def rewrite_gate(
    code: ReconyxEmissionGateCode,
    tag_name: str,
    sources: tuple[str, ...],
) -> ReconyxOutputEmissionGate:
    return ReconyxOutputEmissionGate(
        code,
        f"Reconyx rewrite request for {tag_name} is outside the supported raw BinaryData surface.",
        sources,
    )


def build_actions(
    routing: ReconyxRoutingPlan,
    fields: tuple[ReconyxFieldPlan, ...],
    preservation: ReconyxPreservationPlan,
    rewrite_steps: tuple[ReconyxRewriteStepPlan, ...],
    rewrite_requests: tuple[ReconyxRewriteRequest, ...],
    gates: tuple[ReconyxOutputEmissionGate, ...],
) -> tuple[ReconyxActionPlan, ...]:
    actions: list[ReconyxActionPlan] = []
    if routing.selected_family == "hyperfire":
        actions.append(
            ReconyxActionPlan(
                "route_hyperfire_table",
                "HyperFire",
                None,
                routing.reason,
                routing.evidence_ids,
            )
        )
    if routing.selected_family == "ultrafire":
        actions.append(
            ReconyxActionPlan(
                "route_ultrafire_table",
                "UltraFire",
                None,
                routing.reason,
                routing.evidence_ids,
            )
        )
    actions.extend(
        ReconyxActionPlan(
            "extract_field",
            field.tag_name,
            field.byte_range,
            f"Extract Reconyx {field.tag_name} from the routed BinaryData table.",
            field.evidence_ids,
        )
        for field in fields
    )
    actions.extend(
        ReconyxActionPlan(
            "preserve_unknown_bytes",
            f"unknown:{start}:{end}",
            (start, end),
            "Bytes outside routed Reconyx source fields are preserved.",
            preservation.evidence_ids,
        )
        for start, end in preservation.unknown_ranges
    )
    actions.append(
        ReconyxActionPlan(
            "preserve_payload",
            "maker_note_payload",
            preservation.payload_range,
            "Reconyx transaction planning preserves the full maker-note payload.",
            preservation.evidence_ids,
        )
    )
    actions.extend(
        ReconyxActionPlan(
            "apply_raw_binary_data_rewrite",
            step.tag_name,
            step.byte_range,
            "Exact-size raw payload rewrite is within Reconyx.pm's BinaryData write surface.",
            step.evidence_ids,
        )
        for step in rewrite_steps
    )
    actions.extend(blocked_rewrite_actions(rewrite_requests, rewrite_steps, gates))
    return tuple(actions)


def blocked_rewrite_actions(
    rewrite_requests: tuple[ReconyxRewriteRequest, ...],
    rewrite_steps: tuple[ReconyxRewriteStepPlan, ...],
    gates: tuple[ReconyxOutputEmissionGate, ...],
) -> tuple[ReconyxActionPlan, ...]:
    if not any(gate.code in unsupported_rewrite_gate_codes() for gate in gates):
        return ()
    sources = tuple(source for gate in gates for source in gate.evidence_ids)
    return tuple(
        ReconyxActionPlan(
            "block_requested_rewrite",
            request.tag_name,
            None,
            "Requested Reconyx rewrite is outside the supported source-grounded surface.",
            sources,
        )
        for request in rewrite_requests
    )


def unsupported_rewrite_gate_codes() -> tuple[ReconyxEmissionGateCode, ...]:
    return (
        "unknown_rewrite_tag",
        "read_only_rewrite_tag",
        "rewrite_payload_size_mismatch",
        "duplicate_rewrite_tag",
    )


def tag_specs_for_family(family: ReconyxMakerNoteFamily) -> tuple[ReconyxTagSpec, ...]:
    if family == "hyperfire":
        return HYPERFIRE_TAGS
    return ULTRAFIRE_TAGS


def field_by_name(
    fields: tuple[ReconyxFieldPlan, ...],
    tag_name: str,
) -> ReconyxFieldPlan | None:
    for field in fields:
        if field.tag_name == tag_name:
            return field
    return None


def unknown_ranges(
    data_length: int,
    known_ranges: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for start, end in sorted(known_ranges):
        if cursor < start:
            ranges.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < data_length:
        ranges.append((cursor, data_length))
    return tuple(ranges)


def firmware_date_value(values: tuple[int, ...]) -> str:
    return f"{values[0]:04x}:{values[1] >> 8:02x}:{values[1] & 0xFF:02x}"


def hyperfire_datetime(values: tuple[int, ...]) -> str:
    parts = values
    if parts[0] & 0xFF00 and not parts[0] & 0xFF:
        parts = tuple(((part >> 8) | ((part & 0xFF) << 8)) for part in parts)
    return (
        f"{parts[5]:04d}:{parts[3]:02d}:{parts[4]:02d} {parts[2]:02d}:{parts[1]:02d}:{parts[0]:02d}"
    )


def ultrafire_datetime(payload: bytes) -> str:
    year = read_unsigned(payload, 5, 2)
    return (
        f"{year:04d}:{payload[4]:02d}:{payload[3]:02d} "
        f"{payload[2]:02d}:{payload[1]:02d}:{payload[0]:02d}"
    )


def version_info_value(payload: bytes) -> str:
    revision = payload[6:7].decode("latin-1")
    return (
        f"{payload[0]:02x}.{payload[1]:02x} {read_unsigned(payload, 2, 2):04x}:"
        f"{payload[4]:02x}:{payload[5]:02x} Rev.{revision}"
    )


def voltage_value(raw_millivolts: int) -> int | str:
    if raw_millivolts % 1000 == 0:
        return raw_millivolts // 1000
    return f"{raw_millivolts / 1000:g} V"


def decode_string(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("latin-1")


def decode_utf16le(payload: bytes) -> str:
    end = len(payload)
    for index in range(0, len(payload), 2):
        if payload[index : index + 2] == b"\x00\x00":
            end = index
            break
    return payload[:end].decode("utf-16le", errors="strict")


def field_scalar_byte_count(binary_format: ReconyxBinaryFormat) -> int:
    if binary_format == "int8u":
        return 1
    if binary_format in {"int16u", "int16s"}:
        return 2
    if binary_format == "int32u":
        return 4
    raise ValueError(f"{binary_format} is not an integer scalar format.")


def read_integer(payload: bytes, binary_format: ReconyxBinaryFormat) -> int:
    if binary_format == "int16s":
        return int.from_bytes(payload, "little", signed=True)
    return int.from_bytes(payload, "little", signed=False)


def read_unsigned(data: bytes, offset: int, byte_count: int) -> int:
    return int.from_bytes(data[offset : offset + byte_count], "little")


def structural_gate_present(gates: tuple[ReconyxOutputEmissionGate, ...]) -> bool:
    structural_codes = {
        "truncated_reconyx_routing_marker",
        "unsupported_reconyx_makernote_table",
        "malformed_hyperfire_identity",
        "malformed_ultrafire_structure",
        "truncated_reconyx_binary_data",
    }
    return any(gate.code in structural_codes for gate in gates)


def unique_gates_tuple(
    gates: tuple[ReconyxOutputEmissionGate, ...],
) -> tuple[ReconyxOutputEmissionGate, ...]:
    unique: list[ReconyxOutputEmissionGate] = []
    seen: set[ReconyxEmissionGateCode] = set()
    for gate in gates:
        if gate.code not in seen:
            unique.append(gate)
            seen.add(gate.code)
    return tuple(unique)


def evidence_ids_for_plan(
    routing: ReconyxRoutingPlan,
    fields: tuple[ReconyxFieldPlan, ...],
    preservation: ReconyxPreservationPlan,
    rewrite_steps: tuple[ReconyxRewriteStepPlan, ...],
    gates: tuple[ReconyxOutputEmissionGate, ...],
) -> tuple[str, ...]:
    return unique_sources(
        (
            HYPERFIRE_TABLE_SOURCE,
            ULTRAFIRE_TABLE_SOURCE,
            RECONYX_WRITE_PROC_SOURCE,
            *routing.evidence_ids,
            *(source for field in fields for source in field.evidence_ids),
            *preservation.evidence_ids,
            *(source for step in rewrite_steps for source in step.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source not in seen:
            unique.append(source)
            seen.add(source)
    return tuple(unique)


plan_reconyx_makernote_transaction = build_reconyx_makernote_transaction_plan
