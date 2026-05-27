"""Source-grounded JVC maker-note transaction planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

type JvcNoteKind = Literal["auto", "exif", "text"]
type JvcResolvedNoteKind = Literal["exif", "text"]
type JvcPlanStatus = Literal["planned", "unsupported"]
type JvcTableName = Literal["Image::ExifTool::JVC::Main", "Image::ExifTool::JVC::Text"]
type JvcExifTypeName = Literal[
    "byte",
    "ascii",
    "short",
    "long",
    "rational",
    "undefined",
    "slong",
    "srational",
]
type JvcConversionBoundary = Literal[
    "none",
    "cpu_versions_value_conversion",
    "quality_print_conversion",
    "text_quality_print_conversion",
    "unknown_text_preservation",
]
type JvcValueClass = Literal[
    "source_value",
    "value_converted_text",
    "print_converted_quality",
    "unknown_text_preserved",
    "unknown_exif_preserved",
]
type JvcActionKind = Literal[
    "route_main_exif_table",
    "route_text_table",
    "extract_exif_tag",
    "extract_text_tag",
    "preserve_unknown_exif_tag",
    "preserve_unknown_text_tag",
    "skip_unknown_text_tag",
    "block_requested_rewrite",
]
type JvcOutputGateCode = Literal[
    "truncated_ifd_header",
    "truncated_ifd_entry",
    "truncated_tag_value",
    "malformed_entry_type",
    "bad_text_header",
    "unknown_rewrite_tag",
    "read_only_rewrite_tag",
    "duplicate_rewrite_tag",
    "text_rewrite_not_supported",
    "non_mutating_plan_requires_explicit_emission",
]
type JvcByteOrder = Literal["little", "big"]
type JvcTagKey = int | str
type JvcRawValue = int | str | bytes | None
type JvcInterpretedValue = int | str | bytes | None

JVC_MAIN_SOURCE = "jvc.pm.main-table"
JVC_EXIF_WRITE_SOURCE = "jvc.pm.main-exif-routing"
JVC_CPU_SOURCE = "jvc.pm.cpuversions-value-conversion"
JVC_EXIF_QUALITY_SOURCE = "jvc.pm.exif-quality-print-conversion"
JVC_TEXT_SOURCE = "jvc.pm.text-table"
JVC_TEXT_HEADER_SOURCE = "jvc.pm.process-text.header-validation"
JVC_TEXT_PARSE_SOURCE = "jvc.pm.process-text.tag-parser"
JVC_TEXT_UNKNOWN_SOURCE = "jvc.pm.process-text.unknown-tags"


@dataclass(frozen=True)
class JvcRewriteRequest:
    tag_name: str
    raw_payload: bytes


@dataclass(frozen=True)
class JvcExifEntryPlan:
    tag_id: int
    exif_type: JvcExifTypeName
    count: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_payload: bytes
    payload_is_inline: bool


@dataclass(frozen=True)
class JvcFieldPlan:
    tag_name: str
    tag_key: JvcTagKey
    table: JvcTableName
    byte_range: tuple[int, int]
    raw_payload: bytes
    raw_value: JvcRawValue
    interpreted_value: JvcInterpretedValue
    value_class: JvcValueClass
    conversion_boundary: JvcConversionBoundary
    is_unknown: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JvcRoutingPlan:
    note_kind: JvcResolvedNoteKind
    table: JvcTableName
    byte_order: JvcByteOrder | None
    entry_count: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JvcPreservationPlan:
    payload_range: tuple[int, int]
    unknown_exif_tag_ids: tuple[int, ...]
    unknown_text_tag_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JvcActionPlan:
    kind: JvcActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JvcOutputEmissionGate:
    code: JvcOutputGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JvcMakerNoteTransactionPlan:
    status: JvcPlanStatus
    source_data: bytes
    routing: JvcRoutingPlan
    fields: tuple[JvcFieldPlan, ...]
    preservation: JvcPreservationPlan
    actions: tuple[JvcActionPlan, ...]
    output_emission_gates: tuple[JvcOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def field(self, tag_name: str) -> JvcFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"JVC maker-note transaction output is gated: {gate_codes}")
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
EXIF_TYPE_NAMES: dict[int, JvcExifTypeName] = {
    1: "byte",
    2: "ascii",
    3: "short",
    4: "long",
    5: "rational",
    7: "undefined",
    9: "slong",
    10: "srational",
}
EXIF_QUALITY_LABELS = {0: "Low", 1: "Normal", 2: "Fine"}
TEXT_QUALITY_LABELS = {"STND": "Normal", "STD": "Normal", "FINE": "Fine"}
TEXT_TAG_RE = re.compile(rb"([A-Z]+):(.{3,4})", re.DOTALL)


def build_jvc_makernote_transaction_plan(
    source_data: bytes,
    *,
    note_kind: JvcNoteKind = "auto",
    byte_order: JvcByteOrder = "little",
    value_base_offset: int = 0,
    preserve_unknown_text_tags: bool = False,
    rewrite_requests: tuple[JvcRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> JvcMakerNoteTransactionPlan:
    if note_kind == "text" or (note_kind == "auto" and source_data.startswith(b"VER:")):
        return build_text_plan(
            source_data,
            preserve_unknown_text_tags=preserve_unknown_text_tags,
            rewrite_requests=rewrite_requests,
            allow_output_emission=allow_output_emission,
        )
    return build_exif_plan(
        source_data,
        byte_order=byte_order,
        value_base_offset=value_base_offset,
        rewrite_requests=rewrite_requests,
        allow_output_emission=allow_output_emission,
    )


def build_exif_plan(
    source_data: bytes,
    *,
    byte_order: JvcByteOrder,
    value_base_offset: int,
    rewrite_requests: tuple[JvcRewriteRequest, ...],
    allow_output_emission: bool,
) -> JvcMakerNoteTransactionPlan:
    routing = JvcRoutingPlan(
        "exif",
        "Image::ExifTool::JVC::Main",
        byte_order,
        0,
        (JVC_MAIN_SOURCE, JVC_EXIF_WRITE_SOURCE),
    )
    if len(source_data) < 2:
        gate = JvcOutputEmissionGate(
            "truncated_ifd_header",
            "JVC EXIF maker notes need a two-byte IFD entry count.",
            (JVC_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entry_count = read_u16(source_data, 0, byte_order)
    routing = JvcRoutingPlan(
        "exif",
        "Image::ExifTool::JVC::Main",
        byte_order,
        entry_count,
        (JVC_MAIN_SOURCE, JVC_EXIF_WRITE_SOURCE),
    )
    entry_region_end = 2 + (entry_count * 12) + 4
    if len(source_data) < entry_region_end:
        gate = JvcOutputEmissionGate(
            "truncated_ifd_entry",
            "JVC EXIF maker-note entries and next-directory pointer are incomplete.",
            (JVC_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entries: list[JvcExifEntryPlan] = []
    parse_gates: list[JvcOutputEmissionGate] = []
    for index in range(entry_count):
        entry_offset = 2 + (index * 12)
        parsed_entry = parse_ifd_entry(source_data, entry_offset, byte_order, value_base_offset)
        if isinstance(parsed_entry, JvcOutputEmissionGate):
            parse_gates.append(parsed_entry)
        else:
            entries.append(parsed_entry)

    if parse_gates:
        return unsupported_plan(source_data, routing, tuple(parse_gates))

    fields, actions = build_exif_fields(entries, byte_order)
    rewrite_gates, rewrite_actions = plan_exif_rewrites(fields, rewrite_requests)
    output_gates = list(rewrite_gates)
    if not rewrite_requests and not allow_output_emission:
        output_gates.append(non_mutating_gate((JVC_EXIF_WRITE_SOURCE,)))

    all_actions = (
        JvcActionPlan(
            "route_main_exif_table",
            "Image::ExifTool::JVC::Main",
            (0, len(source_data)),
            "Use the JVC Main EXIF maker-note table.",
            (JVC_MAIN_SOURCE,),
        ),
        *actions,
        *rewrite_actions,
    )
    preservation = JvcPreservationPlan(
        (0, len(source_data)),
        unknown_exif_tag_ids(fields),
        (),
        (JVC_MAIN_SOURCE,),
    )
    return JvcMakerNoteTransactionPlan(
        "planned",
        source_data,
        routing,
        fields,
        preservation,
        all_actions,
        tuple(output_gates),
        collect_evidence_ids(fields, all_actions, tuple(output_gates)),
    )


def build_text_plan(
    source_data: bytes,
    *,
    preserve_unknown_text_tags: bool,
    rewrite_requests: tuple[JvcRewriteRequest, ...],
    allow_output_emission: bool,
) -> JvcMakerNoteTransactionPlan:
    routing = JvcRoutingPlan(
        "text",
        "Image::ExifTool::JVC::Text",
        None,
        None,
        (JVC_TEXT_SOURCE, JVC_TEXT_PARSE_SOURCE),
    )
    if not source_data.startswith(b"VER:"):
        gate = JvcOutputEmissionGate(
            "bad_text_header",
            "JVC text maker notes must start with VER:.",
            (JVC_TEXT_HEADER_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    fields, actions = build_text_fields(source_data, preserve_unknown_text_tags)
    rewrite_gates, rewrite_actions = plan_text_rewrites(rewrite_requests)
    output_gates = list(rewrite_gates)
    if not rewrite_requests and not allow_output_emission:
        output_gates.append(non_mutating_gate((JVC_TEXT_SOURCE,)))

    all_actions = (
        JvcActionPlan(
            "route_text_table",
            "Image::ExifTool::JVC::Text",
            (0, len(source_data)),
            "Use the JVC/Victor text maker-note table.",
            (JVC_TEXT_SOURCE,),
        ),
        *actions,
        *rewrite_actions,
    )
    preservation = JvcPreservationPlan(
        (0, len(source_data)),
        (),
        unknown_text_tag_codes(fields),
        (JVC_TEXT_SOURCE, JVC_TEXT_UNKNOWN_SOURCE),
    )
    return JvcMakerNoteTransactionPlan(
        "planned",
        source_data,
        routing,
        fields,
        preservation,
        all_actions,
        tuple(output_gates),
        collect_evidence_ids(fields, all_actions, tuple(output_gates)),
    )


def unsupported_plan(
    source_data: bytes,
    routing: JvcRoutingPlan,
    gates: tuple[JvcOutputEmissionGate, ...],
) -> JvcMakerNoteTransactionPlan:
    route_action: JvcActionKind
    route_action = "route_text_table" if routing.note_kind == "text" else "route_main_exif_table"
    return JvcMakerNoteTransactionPlan(
        "unsupported",
        source_data,
        routing,
        (),
        JvcPreservationPlan((0, len(source_data)), (), (), routing.evidence_ids),
        (
            JvcActionPlan(
                route_action,
                routing.table,
                (0, len(source_data)),
                "JVC maker-note routing could not be completed.",
                routing.evidence_ids,
            ),
        ),
        gates,
        collect_evidence_ids((), (), gates),
    )


def unknown_exif_tag_ids(fields: tuple[JvcFieldPlan, ...]) -> tuple[int, ...]:
    tag_ids: list[int] = []
    for field in fields:
        if field.value_class == "unknown_exif_preserved" and isinstance(field.tag_key, int):
            tag_ids.append(field.tag_key)
    return tuple(tag_ids)


def unknown_text_tag_codes(fields: tuple[JvcFieldPlan, ...]) -> tuple[str, ...]:
    tag_codes: list[str] = []
    for field in fields:
        if field.value_class == "unknown_text_preserved" and isinstance(field.tag_key, str):
            tag_codes.append(field.tag_key)
    return tuple(tag_codes)


def parse_ifd_entry(
    source_data: bytes,
    entry_offset: int,
    byte_order: JvcByteOrder,
    value_base_offset: int,
) -> JvcExifEntryPlan | JvcOutputEmissionGate:
    tag_id = read_u16(source_data, entry_offset, byte_order)
    type_id = read_u16(source_data, entry_offset + 2, byte_order)
    if type_id not in EXIF_TYPE_SIZES:
        return JvcOutputEmissionGate(
            "malformed_entry_type",
            f"JVC maker-note tag 0x{tag_id:04x} uses unsupported EXIF type {type_id}.",
            (JVC_MAIN_SOURCE,),
        )
    count = read_u32(source_data, entry_offset + 4, byte_order)
    byte_count = EXIF_TYPE_SIZES[type_id] * count
    value_slot = source_data[entry_offset + 8 : entry_offset + 12]
    if byte_count <= 4:
        value_range = (entry_offset + 8, entry_offset + 8 + byte_count)
        raw_payload = source_data[value_range[0] : value_range[1]]
        payload_is_inline = True
    else:
        value_offset = int.from_bytes(value_slot, byte_order)
        local_value_offset = value_offset - value_base_offset
        value_end = local_value_offset + byte_count
        if local_value_offset < 0 or value_end > len(source_data):
            return JvcOutputEmissionGate(
                "truncated_tag_value",
                f"JVC maker-note tag 0x{tag_id:04x} points beyond the source bytes.",
                (JVC_MAIN_SOURCE,),
            )
        value_range = (local_value_offset, value_end)
        raw_payload = source_data[local_value_offset:value_end]
        payload_is_inline = False
    return JvcExifEntryPlan(
        tag_id,
        EXIF_TYPE_NAMES[type_id],
        count,
        (entry_offset, entry_offset + 12),
        value_range,
        raw_payload,
        payload_is_inline,
    )


def build_exif_fields(
    entries: list[JvcExifEntryPlan],
    byte_order: JvcByteOrder,
) -> tuple[tuple[JvcFieldPlan, ...], tuple[JvcActionPlan, ...]]:
    fields: list[JvcFieldPlan] = []
    actions: list[JvcActionPlan] = []
    for entry in entries:
        if entry.tag_id == 0x0002:
            converted = convert_cpu_versions(entry.raw_payload)
            field = JvcFieldPlan(
                "CPUVersions",
                entry.tag_id,
                "Image::ExifTool::JVC::Main",
                entry.value_range,
                entry.raw_payload,
                entry.raw_payload,
                converted,
                "value_converted_text",
                "cpu_versions_value_conversion",
                False,
                (JVC_CPU_SOURCE,),
            )
            actions.append(extract_exif_action(field, "Apply the CPUVersions value conversion."))
        elif entry.tag_id == 0x0003:
            raw_value = first_integer(entry.raw_payload, entry.exif_type, byte_order)
            interpreted = quality_label(raw_value)
            field = JvcFieldPlan(
                "Quality",
                entry.tag_id,
                "Image::ExifTool::JVC::Main",
                entry.value_range,
                entry.raw_payload,
                raw_value,
                interpreted,
                "print_converted_quality",
                "quality_print_conversion",
                False,
                (JVC_EXIF_QUALITY_SOURCE,),
            )
            actions.append(extract_exif_action(field, "Apply the EXIF Quality print conversion."))
        else:
            unknown_raw_value = decode_unknown_exif_raw_value(entry, byte_order)
            field = JvcFieldPlan(
                f"JVC_0x{entry.tag_id:04x}",
                entry.tag_id,
                "Image::ExifTool::JVC::Main",
                entry.value_range,
                entry.raw_payload,
                unknown_raw_value,
                unknown_raw_value,
                "unknown_exif_preserved",
                "none",
                True,
                (JVC_MAIN_SOURCE,),
            )
            actions.append(
                JvcActionPlan(
                    "preserve_unknown_exif_tag",
                    field.tag_name,
                    field.byte_range,
                    "Preserve source bytes for an EXIF tag not named in JVC.pm.",
                    field.evidence_ids,
                )
            )
        fields.append(field)
    return tuple(fields), tuple(actions)


def build_text_fields(
    source_data: bytes,
    preserve_unknown_text_tags: bool,
) -> tuple[tuple[JvcFieldPlan, ...], tuple[JvcActionPlan, ...]]:
    fields: list[JvcFieldPlan] = []
    actions: list[JvcActionPlan] = []
    for match in TEXT_TAG_RE.finditer(source_data):
        tag_code = match.group(1).decode("ascii")
        raw_payload = match.group(2)
        raw_text = decode_text(raw_payload)
        byte_range = match.span(2)
        if tag_code == "VER":
            field = JvcFieldPlan(
                "MakerNoteVersion",
                tag_code,
                "Image::ExifTool::JVC::Text",
                byte_range,
                raw_payload,
                raw_text,
                raw_text,
                "source_value",
                "none",
                False,
                (JVC_TEXT_SOURCE, JVC_TEXT_PARSE_SOURCE),
            )
            fields.append(field)
            actions.append(extract_text_action(field, "Extract the VER text maker-note tag."))
        elif tag_code == "QTY":
            interpreted = TEXT_QUALITY_LABELS.get(raw_text)
            field = JvcFieldPlan(
                "Quality",
                tag_code,
                "Image::ExifTool::JVC::Text",
                byte_range,
                raw_payload,
                raw_text,
                interpreted,
                "print_converted_quality",
                "text_quality_print_conversion",
                False,
                (JVC_TEXT_SOURCE,),
            )
            fields.append(field)
            actions.append(extract_text_action(field, "Apply the text Quality print conversion."))
        elif preserve_unknown_text_tags:
            field = JvcFieldPlan(
                f"JVC_Text_{tag_code}",
                tag_code,
                "Image::ExifTool::JVC::Text",
                byte_range,
                raw_payload,
                raw_text,
                raw_text,
                "unknown_text_preserved",
                "unknown_text_preservation",
                True,
                (JVC_TEXT_UNKNOWN_SOURCE,),
            )
            fields.append(field)
            actions.append(
                JvcActionPlan(
                    "preserve_unknown_text_tag",
                    field.tag_name,
                    field.byte_range,
                    "Preserve an unknown text tag because unknown-tag preservation is enabled.",
                    field.evidence_ids,
                )
            )
        else:
            actions.append(
                JvcActionPlan(
                    "skip_unknown_text_tag",
                    f"JVC_Text_{tag_code}",
                    byte_range,
                    "Skip an unknown text tag because unknown-tag preservation is disabled.",
                    (JVC_TEXT_UNKNOWN_SOURCE,),
                )
            )
    return tuple(fields), tuple(actions)


def extract_exif_action(field: JvcFieldPlan, reason: str) -> JvcActionPlan:
    return JvcActionPlan(
        "extract_exif_tag",
        field.tag_name,
        field.byte_range,
        reason,
        field.evidence_ids,
    )


def extract_text_action(field: JvcFieldPlan, reason: str) -> JvcActionPlan:
    return JvcActionPlan(
        "extract_text_tag",
        field.tag_name,
        field.byte_range,
        reason,
        field.evidence_ids,
    )


def plan_exif_rewrites(
    fields: tuple[JvcFieldPlan, ...],
    rewrite_requests: tuple[JvcRewriteRequest, ...],
) -> tuple[tuple[JvcOutputEmissionGate, ...], tuple[JvcActionPlan, ...]]:
    if not rewrite_requests:
        return (), ()

    available_names = {field.tag_name for field in fields}
    seen_names: set[str] = set()
    gates: list[JvcOutputEmissionGate] = []
    actions: list[JvcActionPlan] = []
    for request in rewrite_requests:
        if request.tag_name in seen_names:
            gate = JvcOutputEmissionGate(
                "duplicate_rewrite_tag",
                f"JVC maker-note rewrite requested {request.tag_name} more than once.",
                (JVC_EXIF_WRITE_SOURCE,),
            )
        elif request.tag_name not in available_names and request.tag_name not in {
            "CPUVersions",
            "Quality",
        }:
            gate = JvcOutputEmissionGate(
                "unknown_rewrite_tag",
                f"JVC.pm does not define a maker-note tag named {request.tag_name}.",
                (JVC_MAIN_SOURCE,),
            )
        else:
            gate = JvcOutputEmissionGate(
                "read_only_rewrite_tag",
                f"JVC maker-note tag {request.tag_name} has no ported writable surface.",
                (JVC_EXIF_WRITE_SOURCE,),
            )
        seen_names.add(request.tag_name)
        gates.append(gate)
        actions.append(block_rewrite_action(request.tag_name, gate.reason, gate.evidence_ids))
    return tuple(gates), tuple(actions)


def plan_text_rewrites(
    rewrite_requests: tuple[JvcRewriteRequest, ...],
) -> tuple[tuple[JvcOutputEmissionGate, ...], tuple[JvcActionPlan, ...]]:
    if not rewrite_requests:
        return (), ()

    seen_names: set[str] = set()
    gates: list[JvcOutputEmissionGate] = []
    actions: list[JvcActionPlan] = []
    for request in rewrite_requests:
        if request.tag_name in seen_names:
            gate = JvcOutputEmissionGate(
                "duplicate_rewrite_tag",
                f"JVC text maker-note rewrite requested {request.tag_name} more than once.",
                (JVC_TEXT_SOURCE,),
            )
        else:
            gate = JvcOutputEmissionGate(
                "text_rewrite_not_supported",
                "JVC.pm only implements text maker-note reading in this slice.",
                (JVC_TEXT_SOURCE,),
            )
        seen_names.add(request.tag_name)
        gates.append(gate)
        actions.append(block_rewrite_action(request.tag_name, gate.reason, gate.evidence_ids))
    return tuple(gates), tuple(actions)


def block_rewrite_action(
    tag_name: str,
    reason: str,
    evidence_ids: tuple[str, ...],
) -> JvcActionPlan:
    return JvcActionPlan(
        "block_requested_rewrite",
        tag_name,
        None,
        reason,
        evidence_ids,
    )


def non_mutating_gate(evidence_ids: tuple[str, ...]) -> JvcOutputEmissionGate:
    return JvcOutputEmissionGate(
        "non_mutating_plan_requires_explicit_emission",
        "The default JVC maker-note plan is read-only and does not emit bytes.",
        evidence_ids,
    )


def first_integer(raw_payload: bytes, exif_type: JvcExifTypeName, byte_order: JvcByteOrder) -> int:
    if not raw_payload:
        return 0
    if exif_type in {"byte", "ascii", "undefined"}:
        return raw_payload[0]
    if exif_type == "short":
        return int.from_bytes(raw_payload[:2], byte_order)
    if exif_type == "slong":
        return int.from_bytes(raw_payload[:4], byte_order, signed=True)
    return int.from_bytes(raw_payload[:4], byte_order)


def decode_unknown_exif_raw_value(
    entry: JvcExifEntryPlan,
    byte_order: JvcByteOrder,
) -> JvcRawValue:
    if entry.exif_type == "ascii":
        return decode_text(entry.raw_payload).rstrip("\x00")
    if entry.count == 1 and entry.exif_type in {"byte", "short", "long", "slong"}:
        return first_integer(entry.raw_payload, entry.exif_type, byte_order)
    return entry.raw_payload


def quality_label(raw_value: int) -> str | None:
    return EXIF_QUALITY_LABELS.get(raw_value)


def convert_cpu_versions(raw_payload: bytes) -> str:
    text = decode_text(raw_payload)
    text = re.sub(r"(\s*\x00)+$", "", text)
    text = re.sub(r"(\s*\x00)+", ", ", text)
    return text


def decode_text(raw_payload: bytes) -> str:
    return raw_payload.decode("latin-1")


def read_u16(source_data: bytes, offset: int, byte_order: JvcByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 2], byte_order)


def read_u32(source_data: bytes, offset: int, byte_order: JvcByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 4], byte_order)


def collect_evidence_ids(
    fields: tuple[JvcFieldPlan, ...],
    actions: tuple[JvcActionPlan, ...],
    gates: tuple[JvcOutputEmissionGate, ...],
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
