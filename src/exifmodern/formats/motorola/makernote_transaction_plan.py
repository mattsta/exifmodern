"""Source-grounded Motorola EXIF maker-note transaction plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type MotorolaByteOrder = Literal["little", "big"]
type MotorolaPlanStatus = Literal["planned", "unsupported"]
type MotorolaExifFormat = Literal[
    "int8u",
    "string",
    "int16u",
    "int32u",
    "rational64u",
    "undef",
    "int32s",
    "rational64s",
    "float",
    "double",
]
type MotorolaWritableFormat = Literal["string"]
type MotorolaResponsibilityGroup = Literal[
    "build_identity",
    "camera_rendering",
    "capture_drive",
    "sensor_identity",
    "manufacturing_identity",
    "unknown_preservation",
]
type MotorolaValueClass = Literal[
    "writable_exif_string",
    "read_only_string_preserved",
    "read_only_scalar_preserved",
    "conditional_scalar_preserved",
    "unknown_preserved",
]
type MotorolaConditionBoundary = Literal["none", "custom_rendered_requires_string_format"]
type MotorolaActionKind = Literal[
    "route_main_table",
    "extract_writable_tag",
    "preserve_read_only_tag",
    "preserve_condition_mismatch",
    "preserve_unknown_tag",
    "block_requested_rewrite",
]
type MotorolaOutputGateCode = Literal[
    "truncated_ifd_header",
    "truncated_ifd_entry",
    "truncated_tag_value",
    "malformed_entry_type",
    "unknown_rewrite_tag",
    "unsupported_rewrite_tag",
    "duplicate_rewrite_tag",
    "non_mutating_plan_requires_explicit_emission",
]
type MotorolaRawValue = int | str | tuple[int, ...] | tuple[tuple[int, int], ...] | bytes | None

MOTOROLA_PM_SOURCE_PATH = "lib/Image/ExifTool/Motorola.pm"


def evidence_id(
    line_start: int,
    line_end: int,
    symbol: str,
    evidence: str,
) -> str:
    del line_start, line_end, evidence
    return "motorola.makernote." + _evidence_token(symbol)


def _evidence_token(symbol: str) -> str:
    return (
        symbol.removeprefix("%Image::ExifTool::")
        .replace("::", ".")
        .replace("%", "")
        .replace(" ", "-")
        .lower()
    )


MOTOROLA_MAIN_SOURCE = evidence_id(
    20,
    147,
    "%Image::ExifTool::Motorola::Main",
    "Motorola Main declares the MakerNotes/Camera EXIF maker-note table.",
)
MOTOROLA_EXIF_WRITE_SOURCE = evidence_id(
    21,
    24,
    "Motorola Main EXIF write surface",
    "The table declares Exif::WriteExif, Exif::CheckExif, and WRITABLE => 1.",
)
MOTOROLA_BUILD_SOURCE = evidence_id(
    27,
    28,
    "BuildNumber and SerialNumber",
    "BuildNumber and SerialNumber are writable string maker-note tags.",
)
MOTOROLA_RELATED_STRING_SOURCE = evidence_id(
    35,
    56,
    "Motorola related string/scalar comments before CustomRendered",
    "The table comments document string and scalar formats around build and rendering tags.",
)
MOTOROLA_CUSTOM_RENDERED_SOURCE = evidence_id(
    57,
    62,
    "CustomRendered",
    "CustomRendered is only named when the EXIF format is string and is writable as string.",
)
MOTOROLA_DRIVE_MODE_SOURCE = evidence_id(
    97,
    97,
    "DriveMode",
    "DriveMode is a writable string maker-note tag.",
)
MOTOROLA_SENSOR_SOURCE = evidence_id(
    120,
    120,
    "Sensor",
    "Sensor is a writable string maker-note tag.",
)
MOTOROLA_MANUFACTURE_DATE_SOURCE = evidence_id(
    121,
    129,
    "ManufactureDate and manufacturing strings",
    "ManufactureDate is a writable string and neighboring manufacturing fields are comments.",
)
MOTOROLA_UNKNOWN_SOURCE = evidence_id(
    25,
    146,
    "Motorola unnamed observed tags",
    "Unlisted observed Motorola tag IDs remain source-byte preservation responsibilities.",
)


@dataclass(frozen=True)
class MotorolaRewriteRequest:
    tag_name: str
    raw_payload: bytes


@dataclass(frozen=True)
class MotorolaTagSpec:
    tag_id: int
    name: str
    writable_format: MotorolaWritableFormat | None
    responsibility_group: MotorolaResponsibilityGroup
    condition_boundary: MotorolaConditionBoundary
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MotorolaIfdEntryPlan:
    tag_id: int
    exif_format: MotorolaExifFormat
    count: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_payload: bytes
    payload_is_inline: bool


@dataclass(frozen=True)
class MotorolaFieldPlan:
    tag_name: str
    tag_id: int
    exif_format: MotorolaExifFormat
    count: int
    byte_range: tuple[int, int]
    raw_payload: bytes
    raw_value: MotorolaRawValue
    value_class: MotorolaValueClass
    writable_format: MotorolaWritableFormat | None
    responsibility_group: MotorolaResponsibilityGroup
    condition_boundary: MotorolaConditionBoundary
    is_unknown: bool
    evidence_ids: tuple[str, ...]

    @property
    def is_writable_exif_string(self) -> bool:
        return self.value_class == "writable_exif_string"


@dataclass(frozen=True)
class MotorolaRoutingPlan:
    table: str
    byte_order: MotorolaByteOrder
    entry_count: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MotorolaPreservationPlan:
    payload_range: tuple[int, int]
    unknown_tag_ids: tuple[int, ...]
    read_only_tag_ids: tuple[int, ...]
    condition_mismatch_tag_ids: tuple[int, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MotorolaActionPlan:
    kind: MotorolaActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MotorolaOutputEmissionGate:
    code: MotorolaOutputGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MotorolaMakerNoteTransactionPlan:
    status: MotorolaPlanStatus
    source_data: bytes
    routing: MotorolaRoutingPlan
    fields: tuple[MotorolaFieldPlan, ...]
    preservation: MotorolaPreservationPlan
    actions: tuple[MotorolaActionPlan, ...]
    output_emission_gates: tuple[MotorolaOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def writable_exif_string_tags(self) -> tuple[str, ...]:
        return tuple(field.tag_name for field in self.fields if field.is_writable_exif_string)

    def field(self, tag_name: str) -> MotorolaFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Motorola maker-note transaction output is gated: {gate_codes}")
        return self.source_data


EXIF_FORMAT_SIZES = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    7: 1,
    9: 4,
    10: 8,
    11: 4,
    12: 8,
}
EXIF_FORMAT_NAMES: dict[int, MotorolaExifFormat] = {
    1: "int8u",
    2: "string",
    3: "int16u",
    4: "int32u",
    5: "rational64u",
    7: "undef",
    9: "int32s",
    10: "rational64s",
    11: "float",
    12: "double",
}
MOTOROLA_TAG_SPECS: dict[int, MotorolaTagSpec] = {
    0x5500: MotorolaTagSpec(
        0x5500,
        "BuildNumber",
        "string",
        "build_identity",
        "none",
        (MOTOROLA_BUILD_SOURCE,),
    ),
    0x5501: MotorolaTagSpec(
        0x5501,
        "SerialNumber",
        "string",
        "build_identity",
        "none",
        (MOTOROLA_BUILD_SOURCE,),
    ),
    0x6420: MotorolaTagSpec(
        0x6420,
        "CustomRendered",
        "string",
        "camera_rendering",
        "custom_rendered_requires_string_format",
        (MOTOROLA_CUSTOM_RENDERED_SOURCE,),
    ),
    0x64D0: MotorolaTagSpec(
        0x64D0,
        "DriveMode",
        "string",
        "capture_drive",
        "none",
        (MOTOROLA_DRIVE_MODE_SOURCE,),
    ),
    0x665E: MotorolaTagSpec(
        0x665E,
        "Sensor",
        "string",
        "sensor_identity",
        "none",
        (MOTOROLA_SENSOR_SOURCE,),
    ),
    0x6705: MotorolaTagSpec(
        0x6705,
        "ManufactureDate",
        "string",
        "manufacturing_identity",
        "none",
        (MOTOROLA_MANUFACTURE_DATE_SOURCE,),
    ),
}
RELATED_STRING_TAG_IDS = {
    0x5530,
    0x5560,
    0x5570,
    0x6400,
    0x6401,
    0x6410,
    0x643B,
    0x644D,
    0x6470,
    0x6501,
    0x6502,
    0x6606,
    0x6607,
    0x6608,
    0x6653,
    0x6700,
    0x6701,
    0x6702,
    0x6703,
    0x6704,
    0x6706,
    0x6707,
    0x6708,
    0x6709,
    0x670A,
    0x670B,
    0x670C,
    0x7100,
    0x7101,
    0x7102,
    0x7103,
    0x7104,
}


def build_motorola_makernote_transaction_plan(
    source_data: bytes,
    *,
    byte_order: MotorolaByteOrder = "little",
    rewrite_requests: tuple[MotorolaRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> MotorolaMakerNoteTransactionPlan:
    routing = MotorolaRoutingPlan(
        "Image::ExifTool::Motorola::Main",
        byte_order,
        0,
        (MOTOROLA_MAIN_SOURCE, MOTOROLA_EXIF_WRITE_SOURCE),
    )
    if len(source_data) < 2:
        gate = MotorolaOutputEmissionGate(
            "truncated_ifd_header",
            "Motorola maker notes need a two-byte EXIF IFD entry count.",
            (MOTOROLA_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entry_count = read_u16(source_data, 0, byte_order)
    routing = MotorolaRoutingPlan(
        "Image::ExifTool::Motorola::Main",
        byte_order,
        entry_count,
        (MOTOROLA_MAIN_SOURCE, MOTOROLA_EXIF_WRITE_SOURCE),
    )
    entry_region_end = 2 + (entry_count * 12) + 4
    if len(source_data) < entry_region_end:
        gate = MotorolaOutputEmissionGate(
            "truncated_ifd_entry",
            "Motorola maker-note entries and next-directory pointer are incomplete.",
            (MOTOROLA_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entries: list[MotorolaIfdEntryPlan] = []
    parse_gates: list[MotorolaOutputEmissionGate] = []
    for index in range(entry_count):
        entry_offset = 2 + (index * 12)
        parsed_entry = parse_ifd_entry(source_data, entry_offset, byte_order)
        if isinstance(parsed_entry, MotorolaOutputEmissionGate):
            parse_gates.append(parsed_entry)
        else:
            entries.append(parsed_entry)

    if parse_gates:
        return unsupported_plan(source_data, routing, tuple(parse_gates))

    fields, field_actions = build_fields(entries, byte_order)
    rewrite_gates, rewrite_actions = plan_rewrites(rewrite_requests)
    output_gates = list(rewrite_gates)
    if not rewrite_requests and not allow_output_emission:
        output_gates.append(non_mutating_gate())

    all_actions = (
        MotorolaActionPlan(
            "route_main_table",
            "Image::ExifTool::Motorola::Main",
            (0, len(source_data)),
            "Use the Motorola Main EXIF maker-note table.",
            (MOTOROLA_MAIN_SOURCE, MOTOROLA_EXIF_WRITE_SOURCE),
        ),
        *field_actions,
        *rewrite_actions,
    )
    preservation = MotorolaPreservationPlan(
        (0, len(source_data)),
        unknown_tag_ids(fields),
        read_only_tag_ids(fields),
        condition_mismatch_tag_ids(fields),
        (MOTOROLA_UNKNOWN_SOURCE,),
    )
    gates = tuple(output_gates)
    return MotorolaMakerNoteTransactionPlan(
        "planned",
        source_data,
        routing,
        fields,
        preservation,
        all_actions,
        gates,
        collect_evidence_ids(fields, all_actions, gates),
    )


def unsupported_plan(
    source_data: bytes,
    routing: MotorolaRoutingPlan,
    gates: tuple[MotorolaOutputEmissionGate, ...],
) -> MotorolaMakerNoteTransactionPlan:
    return MotorolaMakerNoteTransactionPlan(
        "unsupported",
        source_data,
        routing,
        (),
        MotorolaPreservationPlan((0, len(source_data)), (), (), (), routing.evidence_ids),
        (
            MotorolaActionPlan(
                "route_main_table",
                routing.table,
                (0, len(source_data)),
                "Motorola maker-note routing could not be completed.",
                routing.evidence_ids,
            ),
        ),
        gates,
        collect_evidence_ids((), (), gates),
    )


def parse_ifd_entry(
    source_data: bytes,
    entry_offset: int,
    byte_order: MotorolaByteOrder,
) -> MotorolaIfdEntryPlan | MotorolaOutputEmissionGate:
    tag_id = read_u16(source_data, entry_offset, byte_order)
    type_id = read_u16(source_data, entry_offset + 2, byte_order)
    if type_id not in EXIF_FORMAT_SIZES:
        return MotorolaOutputEmissionGate(
            "malformed_entry_type",
            f"Motorola maker-note tag 0x{tag_id:04x} uses unsupported EXIF type {type_id}.",
            (MOTOROLA_MAIN_SOURCE,),
        )
    count = read_u32(source_data, entry_offset + 4, byte_order)
    byte_count = EXIF_FORMAT_SIZES[type_id] * count
    value_slot = source_data[entry_offset + 8 : entry_offset + 12]
    if byte_count <= 4:
        value_range = (entry_offset + 8, entry_offset + 8 + byte_count)
        raw_payload = source_data[value_range[0] : value_range[1]]
        payload_is_inline = True
    else:
        value_offset = int.from_bytes(value_slot, byte_order)
        value_end = value_offset + byte_count
        if value_end > len(source_data):
            return MotorolaOutputEmissionGate(
                "truncated_tag_value",
                f"Motorola maker-note tag 0x{tag_id:04x} points beyond the source bytes.",
                (MOTOROLA_MAIN_SOURCE,),
            )
        value_range = (value_offset, value_end)
        raw_payload = source_data[value_offset:value_end]
        payload_is_inline = False
    return MotorolaIfdEntryPlan(
        tag_id,
        EXIF_FORMAT_NAMES[type_id],
        count,
        (entry_offset, entry_offset + 12),
        value_range,
        raw_payload,
        payload_is_inline,
    )


def build_fields(
    entries: list[MotorolaIfdEntryPlan],
    byte_order: MotorolaByteOrder,
) -> tuple[tuple[MotorolaFieldPlan, ...], tuple[MotorolaActionPlan, ...]]:
    fields: list[MotorolaFieldPlan] = []
    actions: list[MotorolaActionPlan] = []
    for entry in entries:
        field = build_field(entry, byte_order)
        fields.append(field)
        actions.append(action_for_field(field))
    return tuple(fields), tuple(actions)


def build_field(
    entry: MotorolaIfdEntryPlan,
    byte_order: MotorolaByteOrder,
) -> MotorolaFieldPlan:
    spec = MOTOROLA_TAG_SPECS.get(entry.tag_id)
    raw_value = decode_raw_value(entry.raw_payload, entry.exif_format, byte_order)
    if spec is None:
        return build_preserved_field(entry, raw_value)
    if (
        spec.condition_boundary == "custom_rendered_requires_string_format"
        and entry.exif_format != "string"
    ):
        return MotorolaFieldPlan(
            f"Motorola_0x{entry.tag_id:04x}",
            entry.tag_id,
            entry.exif_format,
            entry.count,
            entry.value_range,
            entry.raw_payload,
            raw_value,
            "conditional_scalar_preserved",
            None,
            spec.responsibility_group,
            spec.condition_boundary,
            False,
            spec.evidence_ids,
        )
    return MotorolaFieldPlan(
        spec.name,
        entry.tag_id,
        entry.exif_format,
        entry.count,
        entry.value_range,
        entry.raw_payload,
        raw_value,
        "writable_exif_string",
        spec.writable_format,
        spec.responsibility_group,
        spec.condition_boundary,
        False,
        spec.evidence_ids,
    )


def build_preserved_field(
    entry: MotorolaIfdEntryPlan,
    raw_value: MotorolaRawValue,
) -> MotorolaFieldPlan:
    if entry.exif_format == "string" or entry.tag_id in RELATED_STRING_TAG_IDS:
        value_class: MotorolaValueClass = "read_only_string_preserved"
    elif is_scalar_format(entry.exif_format):
        value_class = "read_only_scalar_preserved"
    else:
        value_class = "unknown_preserved"
    return MotorolaFieldPlan(
        f"Motorola_0x{entry.tag_id:04x}",
        entry.tag_id,
        entry.exif_format,
        entry.count,
        entry.value_range,
        entry.raw_payload,
        raw_value,
        value_class,
        None,
        "unknown_preservation",
        "none",
        True,
        (MOTOROLA_UNKNOWN_SOURCE,),
    )


def action_for_field(field: MotorolaFieldPlan) -> MotorolaActionPlan:
    if field.value_class == "writable_exif_string":
        return MotorolaActionPlan(
            "extract_writable_tag",
            field.tag_name,
            field.byte_range,
            "Extract a writable Motorola EXIF string tag.",
            field.evidence_ids,
        )
    if field.value_class == "conditional_scalar_preserved":
        return MotorolaActionPlan(
            "preserve_condition_mismatch",
            field.tag_name,
            field.byte_range,
            "Preserve 0x6420 because CustomRendered only applies to string format.",
            field.evidence_ids,
        )
    if field.is_unknown:
        return MotorolaActionPlan(
            "preserve_unknown_tag",
            field.tag_name,
            field.byte_range,
            "Preserve source bytes for a Motorola tag not named in Motorola.pm.",
            field.evidence_ids,
        )
    return MotorolaActionPlan(
        "preserve_read_only_tag",
        field.tag_name,
        field.byte_range,
        "Preserve a source tag that has no ported writable Motorola definition.",
        field.evidence_ids,
    )


def plan_rewrites(
    rewrite_requests: tuple[MotorolaRewriteRequest, ...],
) -> tuple[tuple[MotorolaOutputEmissionGate, ...], tuple[MotorolaActionPlan, ...]]:
    if not rewrite_requests:
        return (), ()

    known_names = {spec.name for spec in MOTOROLA_TAG_SPECS.values()}
    seen_names: set[str] = set()
    gates: list[MotorolaOutputEmissionGate] = []
    actions: list[MotorolaActionPlan] = []
    for request in rewrite_requests:
        if request.tag_name in seen_names:
            gate = MotorolaOutputEmissionGate(
                "duplicate_rewrite_tag",
                f"Motorola maker-note rewrite requested {request.tag_name} more than once.",
                (MOTOROLA_EXIF_WRITE_SOURCE,),
            )
        elif request.tag_name not in known_names:
            gate = MotorolaOutputEmissionGate(
                "unknown_rewrite_tag",
                f"Motorola.pm does not define a maker-note tag named {request.tag_name}.",
                (MOTOROLA_MAIN_SOURCE,),
            )
        else:
            gate = MotorolaOutputEmissionGate(
                "unsupported_rewrite_tag",
                "Motorola EXIF-backed writes are identified but not emitted by this slice.",
                (MOTOROLA_EXIF_WRITE_SOURCE,),
            )
        seen_names.add(request.tag_name)
        gates.append(gate)
        actions.append(
            MotorolaActionPlan(
                "block_requested_rewrite",
                request.tag_name,
                None,
                gate.reason,
                gate.evidence_ids,
            )
        )
    return tuple(gates), tuple(actions)


def non_mutating_gate() -> MotorolaOutputEmissionGate:
    return MotorolaOutputEmissionGate(
        "non_mutating_plan_requires_explicit_emission",
        "The default Motorola maker-note plan is read-only and does not emit bytes.",
        (MOTOROLA_EXIF_WRITE_SOURCE,),
    )


def decode_raw_value(
    raw_payload: bytes,
    exif_format: MotorolaExifFormat,
    byte_order: MotorolaByteOrder,
) -> MotorolaRawValue:
    if exif_format == "string":
        return raw_payload.rstrip(b"\x00").decode("latin-1")
    if exif_format in {"int8u", "undef"}:
        if len(raw_payload) == 1:
            return raw_payload[0]
        return tuple(raw_payload)
    if exif_format == "int16u":
        return integer_tuple(raw_payload, 2, byte_order, signed=False)
    if exif_format == "int32u":
        return integer_tuple(raw_payload, 4, byte_order, signed=False)
    if exif_format == "int32s":
        return integer_tuple(raw_payload, 4, byte_order, signed=True)
    if exif_format in {"rational64u", "rational64s"}:
        return rational_tuple(raw_payload, byte_order, signed=exif_format == "rational64s")
    return raw_payload


def integer_tuple(
    raw_payload: bytes,
    width: int,
    byte_order: MotorolaByteOrder,
    *,
    signed: bool,
) -> int | tuple[int, ...]:
    values: list[int] = []
    for offset in range(0, len(raw_payload), width):
        value = int.from_bytes(
            raw_payload[offset : offset + width],
            byte_order,
            signed=signed,
        )
        values.append(value)
    if len(values) == 1:
        return values[0]
    return tuple(values)


def rational_tuple(
    raw_payload: bytes,
    byte_order: MotorolaByteOrder,
    *,
    signed: bool,
) -> tuple[tuple[int, int], ...]:
    values: list[tuple[int, int]] = []
    for offset in range(0, len(raw_payload), 8):
        numerator = int.from_bytes(raw_payload[offset : offset + 4], byte_order, signed=signed)
        denominator = int.from_bytes(
            raw_payload[offset + 4 : offset + 8], byte_order, signed=signed
        )
        values.append((numerator, denominator))
    return tuple(values)


def is_scalar_format(exif_format: MotorolaExifFormat) -> bool:
    return exif_format in {
        "int8u",
        "int16u",
        "int32u",
        "rational64u",
        "int32s",
        "rational64s",
        "float",
        "double",
    }


def unknown_tag_ids(fields: tuple[MotorolaFieldPlan, ...]) -> tuple[int, ...]:
    return tuple(field.tag_id for field in fields if field.value_class == "unknown_preserved")


def read_only_tag_ids(fields: tuple[MotorolaFieldPlan, ...]) -> tuple[int, ...]:
    return tuple(
        field.tag_id
        for field in fields
        if field.value_class in {"read_only_string_preserved", "read_only_scalar_preserved"}
    )


def condition_mismatch_tag_ids(fields: tuple[MotorolaFieldPlan, ...]) -> tuple[int, ...]:
    return tuple(
        field.tag_id for field in fields if field.value_class == "conditional_scalar_preserved"
    )


def read_u16(source_data: bytes, offset: int, byte_order: MotorolaByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 2], byte_order)


def read_u32(source_data: bytes, offset: int, byte_order: MotorolaByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 4], byte_order)


def collect_evidence_ids(
    fields: tuple[MotorolaFieldPlan, ...],
    actions: tuple[MotorolaActionPlan, ...],
    gates: tuple[MotorolaOutputEmissionGate, ...],
) -> tuple[str, ...]:
    collected: list[str] = []
    for references in (
        *(field.evidence_ids for field in fields),
        *(action.evidence_ids for action in actions),
        *(gate.evidence_ids for gate in gates),
    ):
        for reference in references:
            if reference not in collected:
                collected.append(reference)
    return tuple(collected)
