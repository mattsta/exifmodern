"""Source-grounded General Imaging maker-note transaction planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type GeByteOrder = Literal["little", "big"]
type GePlanStatus = Literal["planned", "unsupported"]
type GeExifTypeName = Literal[
    "byte",
    "ascii",
    "short",
    "long",
    "rational",
    "undefined",
    "slong",
    "srational",
]
type GeWritableFormat = Literal["int16u", "string"]
type GeValueClass = Literal[
    "writable_exif_scalar",
    "writable_exif_string",
    "unknown_preserved",
]
type GeConversionBoundary = Literal["none", "macro_print_conversion", "string_value_boundary"]
type GeActionKind = Literal[
    "route_main_table",
    "extract_known_tag",
    "preserve_unknown_tag",
    "block_requested_rewrite",
]
type GeOutputGateCode = Literal[
    "truncated_ifd_header",
    "truncated_ifd_entry",
    "truncated_tag_value",
    "malformed_entry_type",
    "unknown_rewrite_tag",
    "missing_source_tag_for_rewrite",
    "duplicate_rewrite_tag",
    "maker_note_rewrite_not_supported",
    "non_mutating_plan_requires_explicit_emission",
]
type GeRawValue = int | str | bytes | None
type GeInterpretedValue = int | str | bytes | None

GE_PM_SOURCE_PATH = "lib/Image/ExifTool/GE.pm"


def evidence_id(
    line_start: int,
    line_end: int,
    symbol: str,
    evidence: str,
) -> str:
    del line_start, line_end, evidence
    return "ge.makernote." + _evidence_token(symbol)


def _evidence_token(symbol: str) -> str:
    return (
        symbol.removeprefix("%Image::ExifTool::")
        .replace("::", ".")
        .replace("%", "")
        .replace(" ", "-")
        .lower()
    )


GE_MAIN_SOURCE = evidence_id(
    20,
    52,
    "%Image::ExifTool::GE::Main",
    "GE Main is a type 1 EXIF-style maker-note table for General Imaging camera models.",
)
GE_EXIF_WRITE_SOURCE = evidence_id(
    22,
    26,
    "GE Main EXIF write surface",
    (
        "GE Main declares Exif::WriteExif, Exif::CheckExif, WRITABLE => 1, "
        "and MakerNotes/Camera groups."
    ),
)
GE_OBSERVED_UNKNOWN_SOURCE = evidence_id(
    31,
    51,
    "GE observed unnamed tags",
    "GE.pm comments record unnamed adjacent tag IDs and formats; this slice preserves their bytes.",
)
GE_MACRO_SOURCE = evidence_id(
    33,
    37,
    "Macro",
    "Macro is writable int16u and print-converts 0 to Off and 1 to On.",
)
GE_MODEL_SOURCE = evidence_id(
    42,
    45,
    "GEModel",
    "GEModel is a string-format GE Main maker-note tag.",
)
GE_MAKE_SOURCE = evidence_id(
    46,
    49,
    "GEMake",
    "GEMake is a string-format GE Main maker-note tag.",
)


@dataclass(frozen=True)
class GeRewriteRequest:
    tag_name: str
    raw_payload: bytes


@dataclass(frozen=True)
class GeTagSpec:
    tag_id: int
    name: str
    writable_format: GeWritableFormat
    evidence_ids: tuple[str, ...]

    @property
    def value_class(self) -> GeValueClass:
        if self.writable_format == "string":
            return "writable_exif_string"
        return "writable_exif_scalar"


@dataclass(frozen=True)
class GeIfdEntryPlan:
    tag_id: int
    exif_type: GeExifTypeName
    count: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_payload: bytes
    payload_is_inline: bool


@dataclass(frozen=True)
class GeFieldPlan:
    tag_name: str
    tag_id: int
    exif_type: GeExifTypeName
    count: int
    byte_range: tuple[int, int]
    raw_payload: bytes
    raw_value: GeRawValue
    interpreted_value: GeInterpretedValue
    value_class: GeValueClass
    writable_format: GeWritableFormat | None
    conversion_boundary: GeConversionBoundary
    is_unknown: bool
    evidence_ids: tuple[str, ...]

    @property
    def is_writable_exif_backed(self) -> bool:
        return self.value_class in {"writable_exif_scalar", "writable_exif_string"}


@dataclass(frozen=True)
class GeRoutingPlan:
    table: str
    byte_order: GeByteOrder
    entry_count: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GePreservationPlan:
    payload_range: tuple[int, int]
    unknown_tag_ids: tuple[int, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeActionPlan:
    kind: GeActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeOutputEmissionGate:
    code: GeOutputGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeMakerNoteTransactionPlan:
    status: GePlanStatus
    source_data: bytes
    routing: GeRoutingPlan
    fields: tuple[GeFieldPlan, ...]
    preservation: GePreservationPlan
    actions: tuple[GeActionPlan, ...]
    output_emission_gates: tuple[GeOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def writable_exif_backed_tags(self) -> tuple[str, ...]:
        return tuple(field.tag_name for field in self.fields if field.is_writable_exif_backed)

    def field(self, tag_name: str) -> GeFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"GE maker-note transaction output is gated: {gate_codes}")
        return self.source_data


EXIF_TYPE_SIZES = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    7: 1,
    9: 4,
    10: 8,
}
EXIF_TYPE_NAMES: dict[int, GeExifTypeName] = {
    1: "byte",
    2: "ascii",
    3: "short",
    4: "long",
    5: "rational",
    7: "undefined",
    9: "slong",
    10: "srational",
}
MACRO_LABELS = {0: "Off", 1: "On"}

GE_TAG_SPECS: tuple[GeTagSpec, ...] = (
    GeTagSpec(0x0202, "Macro", "int16u", (GE_MACRO_SOURCE,)),
    GeTagSpec(0x0207, "GEModel", "string", (GE_MODEL_SOURCE,)),
    GeTagSpec(0x0300, "GEMake", "string", (GE_MAKE_SOURCE,)),
)
GE_TAGS_BY_ID = {spec.tag_id: spec for spec in GE_TAG_SPECS}
GE_TAGS_BY_NAME = {spec.name: spec for spec in GE_TAG_SPECS}


def build_ge_makernote_transaction_plan(
    source_data: bytes,
    *,
    byte_order: GeByteOrder = "little",
    rewrite_requests: tuple[GeRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> GeMakerNoteTransactionPlan:
    routing = GeRoutingPlan(
        "Image::ExifTool::GE::Main",
        byte_order,
        0,
        (GE_MAIN_SOURCE, GE_EXIF_WRITE_SOURCE),
    )
    if len(source_data) < 2:
        gate = GeOutputEmissionGate(
            "truncated_ifd_header",
            "GE maker-note IFD header must contain a two-byte entry count.",
            (GE_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entry_count = read_u16(source_data, 0, byte_order)
    routing = GeRoutingPlan(
        "Image::ExifTool::GE::Main",
        byte_order,
        entry_count,
        (GE_MAIN_SOURCE, GE_EXIF_WRITE_SOURCE),
    )
    entry_region_end = 2 + (entry_count * 12) + 4
    if len(source_data) < entry_region_end:
        gate = GeOutputEmissionGate(
            "truncated_ifd_entry",
            "GE maker-note IFD entries and next-directory pointer are incomplete.",
            (GE_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entries: list[GeIfdEntryPlan] = []
    parse_gates: list[GeOutputEmissionGate] = []
    for index in range(entry_count):
        entry_offset = 2 + (index * 12)
        parsed_entry = parse_ifd_entry(source_data, entry_offset, byte_order)
        if isinstance(parsed_entry, GeOutputEmissionGate):
            parse_gates.append(parsed_entry)
        else:
            entries.append(parsed_entry)

    if parse_gates:
        return unsupported_plan(source_data, routing, tuple(parse_gates))

    fields, field_actions = build_fields(tuple(entries), byte_order)
    rewrite_gates, rewrite_actions = plan_rewrites(fields, rewrite_requests)
    output_gates = list(rewrite_gates)
    if not rewrite_requests and not allow_output_emission:
        output_gates.append(
            GeOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "The default GE maker-note plan is read-only and does not emit bytes.",
                (GE_EXIF_WRITE_SOURCE,),
            )
        )

    actions = (
        GeActionPlan(
            "route_main_table",
            "Image::ExifTool::GE::Main",
            (0, len(source_data)),
            "Use the GE Main maker-note EXIF table.",
            (GE_MAIN_SOURCE,),
        ),
        *field_actions,
        *rewrite_actions,
    )
    preservation = GePreservationPlan(
        (0, len(source_data)),
        tuple(field.tag_id for field in fields if field.value_class == "unknown_preserved"),
        (GE_MAIN_SOURCE, GE_OBSERVED_UNKNOWN_SOURCE),
    )
    return GeMakerNoteTransactionPlan(
        "planned",
        source_data,
        routing,
        fields,
        preservation,
        actions,
        tuple(output_gates),
        collect_evidence_ids(fields, actions, tuple(output_gates)),
    )


def unsupported_plan(
    source_data: bytes,
    routing: GeRoutingPlan,
    gates: tuple[GeOutputEmissionGate, ...],
) -> GeMakerNoteTransactionPlan:
    actions = (
        GeActionPlan(
            "route_main_table",
            "Image::ExifTool::GE::Main",
            (0, len(source_data)),
            "GE maker-note routing could not be completed.",
            routing.evidence_ids,
        ),
    )
    return GeMakerNoteTransactionPlan(
        "unsupported",
        source_data,
        routing,
        (),
        GePreservationPlan((0, len(source_data)), (), (GE_MAIN_SOURCE,)),
        actions,
        gates,
        collect_evidence_ids((), actions, gates),
    )


def parse_ifd_entry(
    source_data: bytes,
    entry_offset: int,
    byte_order: GeByteOrder,
) -> GeIfdEntryPlan | GeOutputEmissionGate:
    tag_id = read_u16(source_data, entry_offset, byte_order)
    type_id = read_u16(source_data, entry_offset + 2, byte_order)
    if type_id not in EXIF_TYPE_SIZES:
        return GeOutputEmissionGate(
            "malformed_entry_type",
            f"GE maker-note tag 0x{tag_id:04x} uses unsupported EXIF type {type_id}.",
            (GE_MAIN_SOURCE,),
        )
    count = read_u32(source_data, entry_offset + 4, byte_order)
    byte_count = EXIF_TYPE_SIZES[type_id] * count
    value_slot = source_data[entry_offset + 8 : entry_offset + 12]
    if byte_count <= 4:
        value_range = (entry_offset + 8, entry_offset + 8 + byte_count)
        raw_payload = value_slot[:byte_count]
        payload_is_inline = True
    else:
        value_offset = int.from_bytes(value_slot, byte_order)
        value_end = value_offset + byte_count
        if value_offset > len(source_data) or value_end > len(source_data):
            return GeOutputEmissionGate(
                "truncated_tag_value",
                f"GE maker-note tag 0x{tag_id:04x} points outside the source bytes.",
                (GE_MAIN_SOURCE,),
            )
        value_range = (value_offset, value_end)
        raw_payload = source_data[value_offset:value_end]
        payload_is_inline = False
    return GeIfdEntryPlan(
        tag_id,
        EXIF_TYPE_NAMES[type_id],
        count,
        (entry_offset, entry_offset + 12),
        value_range,
        raw_payload,
        payload_is_inline,
    )


def build_fields(
    entries: tuple[GeIfdEntryPlan, ...],
    byte_order: GeByteOrder,
) -> tuple[tuple[GeFieldPlan, ...], tuple[GeActionPlan, ...]]:
    fields: list[GeFieldPlan] = []
    actions: list[GeActionPlan] = []
    for entry in entries:
        spec = GE_TAGS_BY_ID.get(entry.tag_id)
        if spec is None:
            field = GeFieldPlan(
                f"GE_0x{entry.tag_id:04x}",
                entry.tag_id,
                entry.exif_type,
                entry.count,
                entry.value_range,
                entry.raw_payload,
                entry.raw_payload,
                entry.raw_payload,
                "unknown_preserved",
                None,
                "none",
                True,
                (GE_MAIN_SOURCE, GE_OBSERVED_UNKNOWN_SOURCE),
            )
            actions.append(
                GeActionPlan(
                    "preserve_unknown_tag",
                    field.tag_name,
                    field.byte_range,
                    "Preserve source bytes for a GE maker-note tag not named in GE.pm.",
                    field.evidence_ids,
                )
            )
        else:
            raw_value = interpret_value(entry, spec, byte_order)
            field = GeFieldPlan(
                spec.name,
                entry.tag_id,
                entry.exif_type,
                entry.count,
                entry.value_range,
                entry.raw_payload,
                raw_value,
                interpret_print_value(raw_value, spec),
                spec.value_class,
                spec.writable_format,
                conversion_boundary(spec),
                False,
                spec.evidence_ids,
            )
            actions.append(
                GeActionPlan(
                    "extract_known_tag",
                    field.tag_name,
                    field.byte_range,
                    "Extract source-backed GE Main maker-note tag.",
                    field.evidence_ids,
                )
            )
        fields.append(field)
    return tuple(fields), tuple(actions)


def interpret_value(
    entry: GeIfdEntryPlan,
    spec: GeTagSpec,
    byte_order: GeByteOrder,
) -> GeRawValue:
    if spec.writable_format == "string":
        return decode_ge_string(entry.raw_payload)
    if spec.writable_format == "int16u" and entry.exif_type == "short":
        return int.from_bytes(entry.raw_payload[:2], byte_order)
    return entry.raw_payload


def interpret_print_value(raw_value: GeRawValue, spec: GeTagSpec) -> GeInterpretedValue:
    if spec.name == "Macro" and isinstance(raw_value, int):
        return MACRO_LABELS.get(raw_value, raw_value)
    return raw_value


def conversion_boundary(spec: GeTagSpec) -> GeConversionBoundary:
    if spec.name == "Macro":
        return "macro_print_conversion"
    if spec.writable_format == "string":
        return "string_value_boundary"
    return "none"


def decode_ge_string(raw_payload: bytes) -> str:
    return raw_payload.split(b"\x00", 1)[0].decode("latin-1")


def plan_rewrites(
    fields: tuple[GeFieldPlan, ...],
    rewrite_requests: tuple[GeRewriteRequest, ...],
) -> tuple[tuple[GeOutputEmissionGate, ...], tuple[GeActionPlan, ...]]:
    fields_by_name = {field.tag_name: field for field in fields}
    seen_names: set[str] = set()
    gates: list[GeOutputEmissionGate] = []
    actions: list[GeActionPlan] = []
    for request in rewrite_requests:
        field = fields_by_name.get(request.tag_name)
        gate = rewrite_gate_for_request(request, field, seen_names)
        seen_names.add(request.tag_name)
        gates.append(gate)
        actions.append(
            GeActionPlan(
                "block_requested_rewrite",
                request.tag_name,
                field.byte_range if field is not None else None,
                gate.reason,
                gate.evidence_ids,
            )
        )
    return tuple(gates), tuple(actions)


def rewrite_gate_for_request(
    request: GeRewriteRequest,
    field: GeFieldPlan | None,
    seen_names: set[str],
) -> GeOutputEmissionGate:
    spec = GE_TAGS_BY_NAME.get(request.tag_name)
    if request.tag_name in seen_names:
        return GeOutputEmissionGate(
            "duplicate_rewrite_tag",
            f"GE maker-note rewrite for {request.tag_name} was requested more than once.",
            (GE_EXIF_WRITE_SOURCE,),
        )
    if spec is None:
        return GeOutputEmissionGate(
            "unknown_rewrite_tag",
            f"GE.pm does not define a writable tag named {request.tag_name}.",
            (GE_MAIN_SOURCE,),
        )
    if field is None:
        return GeOutputEmissionGate(
            "missing_source_tag_for_rewrite",
            f"GE maker-note tag {request.tag_name} is not present in the source payload.",
            spec.evidence_ids,
        )
    return GeOutputEmissionGate(
        "maker_note_rewrite_not_supported",
        (
            "This GE modernization slice classifies writable EXIF-backed tags "
            "but does not rewrite maker notes."
        ),
        (GE_EXIF_WRITE_SOURCE, *field.evidence_ids),
    )


def read_u16(source_data: bytes, offset: int, byte_order: GeByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 2], byte_order)


def read_u32(source_data: bytes, offset: int, byte_order: GeByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 4], byte_order)


def collect_evidence_ids(
    fields: tuple[GeFieldPlan, ...],
    actions: tuple[GeActionPlan, ...],
    gates: tuple[GeOutputEmissionGate, ...],
) -> tuple[str, ...]:
    collected: list[str] = [GE_MAIN_SOURCE, GE_EXIF_WRITE_SOURCE]
    for field in fields:
        for reference in field.evidence_ids:
            if reference not in collected:
                collected.append(reference)
    for action in actions:
        for reference in action.evidence_ids:
            if reference not in collected:
                collected.append(reference)
    for gate in gates:
        for reference in gate.evidence_ids:
            if reference not in collected:
                collected.append(reference)
    return tuple(collected)
