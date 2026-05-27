"""Source-grounded HP maker-note and TDHD transaction plans."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

HP_PM_SOURCE_PATH = "lib/Image/ExifTool/HP.pm"
HP_TDHD_SUBDIRECTORY_TYPE = 0x10001

type HpMetadataFamily = Literal["main", "type2", "type4", "type6", "tdhd"]
type HpPlanStatus = Literal["planned", "unsupported"]
type HpGroup2 = Literal["Camera", "Image", "Preview", "Time", "Unknown"]
type HpTagRole = Literal[
    "printim_payload",
    "text_metadata",
    "preview_payload",
    "binary_metadata",
    "tdhd_metadata",
    "tdhd_subdirectory",
    "unknown_tag",
]
type HpValueBoundary = Literal[
    "ifd_payload",
    "printable_ascii",
    "jpeg_image",
    "int16u",
    "int32u",
    "fixed_string",
    "serial_raw_conversion",
    "tdhd_record_payload",
    "unknown_payload",
]
type HpActionKind = Literal[
    "route_main_ifd",
    "route_type2_text_scan",
    "route_type4_binary_data",
    "route_type6_binary_data",
    "route_tdhd_records",
    "route_tdhd_subdirectory",
    "extract_known_tag",
    "preserve_unknown_bytes",
    "apply_source_backed_rewrite",
    "block_requested_rewrite",
    "no_metadata_mutation",
]
type HpEmissionGateCode = Literal[
    "unsupported_hp_metadata_family",
    "truncated_hp_main_ifd",
    "malformed_hp_main_ifd",
    "truncated_hp_binary_data",
    "malformed_hp_preview_image",
    "truncated_tdhd_record_header",
    "truncated_tdhd_record_payload",
    "unknown_rewrite_tag",
    "unknown_tag_rewrite_not_source_backed",
    "duplicate_rewrite_tag",
    "rewrite_requires_source_backed_request",
    "rewrite_payload_size_mismatch",
    "rewrite_requires_explicit_output_emission",
    "non_mutating_plan_requires_explicit_emission",
]
type HpParsedValue = int | float | str | bytes | None
type HpByteOrder = Literal["little", "big"]


@dataclass(frozen=True)
class HpMetadataRewriteRequest:
    tag_name: str
    replacement_payload: bytes
    source_backed: bool = False


@dataclass(frozen=True)
class HpRoutingPlan:
    requested_family: HpMetadataFamily | None
    selected_family: HpMetadataFamily | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HpFieldPlan:
    tag_name: str
    tag_id: str
    family: HpMetadataFamily
    group2: HpGroup2
    role: HpTagRole
    value_boundary: HpValueBoundary
    byte_range: tuple[int, int]
    raw_payload: bytes
    interpreted_value: HpParsedValue
    evidence_ids: tuple[str, ...]

    @property
    def is_known_rewrite_target(self) -> bool:
        return self.role != "unknown_tag" and self.role != "tdhd_subdirectory"


@dataclass(frozen=True)
class HpPreservationPlan:
    payload_range: tuple[int, int]
    unknown_ranges: tuple[tuple[int, int], ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HpRewriteStepPlan:
    tag_name: str
    byte_range: tuple[int, int]
    replacement_payload: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HpActionPlan:
    kind: HpActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HpOutputEmissionGate:
    code: HpEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HpMetadataTransactionPlan:
    status: HpPlanStatus
    source_data: bytes
    routing: HpRoutingPlan
    fields: tuple[HpFieldPlan, ...]
    preservation: HpPreservationPlan
    rewrite_steps: tuple[HpRewriteStepPlan, ...]
    actions: tuple[HpActionPlan, ...]
    output_emission_gates: tuple[HpOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def known_tag_names(self) -> tuple[str, ...]:
        return tuple(field.tag_name for field in self.fields if field.is_known_rewrite_target)

    def field(self, tag_name: str) -> HpFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"HP metadata transaction output is gated: {gate_codes}")
        mutable = bytearray(self.source_data)
        for step in self.rewrite_steps:
            start, end = step.byte_range
            mutable[start:end] = step.replacement_payload
        return bytes(mutable)


HP_MAIN_TABLE_SOURCE = "hp.main.table"
HP_TYPE2_TABLE_SOURCE = "hp.type2.table"
HP_TYPE4_TABLE_SOURCE = "hp.type4.table"
HP_TYPE6_TABLE_SOURCE = "hp.type6.table"
HP_TDHD_TABLE_SOURCE = "hp.tdhd.table"
HP_TDHD_PROCESS_SOURCE = "hp.tdhd.process"
HP_PROCESS_HP_SOURCE = "hp.process.hp"


@dataclass(frozen=True)
class HpBinaryTagSpec:
    tag_name: str
    tag_id: int
    byte_count: int
    group2: HpGroup2
    value_boundary: HpValueBoundary
    evidence_ids: tuple[str, ...]


TYPE4_TAGS: tuple[HpBinaryTagSpec, ...] = (
    HpBinaryTagSpec("MaxAperture", 0x0C, 2, "Camera", "int16u", (HP_TYPE4_TABLE_SOURCE,)),
    HpBinaryTagSpec("ExposureTime", 0x10, 4, "Camera", "int32u", (HP_TYPE4_TABLE_SOURCE,)),
    HpBinaryTagSpec("CameraDateTime", 0x14, 20, "Time", "fixed_string", (HP_TYPE4_TABLE_SOURCE,)),
    HpBinaryTagSpec("ISO", 0x34, 2, "Camera", "int16u", (HP_TYPE4_TABLE_SOURCE,)),
    HpBinaryTagSpec(
        "SerialNumber", 0x5C, 26, "Camera", "serial_raw_conversion", (HP_TYPE4_TABLE_SOURCE,)
    ),
)
TYPE6_TAGS: tuple[HpBinaryTagSpec, ...] = (
    HpBinaryTagSpec("FNumber", 0x0C, 2, "Camera", "int16u", (HP_TYPE6_TABLE_SOURCE,)),
    HpBinaryTagSpec("ExposureTime", 0x10, 4, "Camera", "int32u", (HP_TYPE6_TABLE_SOURCE,)),
    HpBinaryTagSpec("CameraDateTime", 0x14, 20, "Time", "fixed_string", (HP_TYPE6_TABLE_SOURCE,)),
    HpBinaryTagSpec("ISO", 0x34, 2, "Camera", "int16u", (HP_TYPE6_TABLE_SOURCE,)),
    HpBinaryTagSpec(
        "SerialNumber", 0x58, 26, "Camera", "serial_raw_conversion", (HP_TYPE6_TABLE_SOURCE,)
    ),
)
TEXT_TAGS: tuple[tuple[str, str], ...] = (
    ("Lens Shading", "LensShading"),
    ("Serial Number", "SerialNumber"),
)
TIFF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 7: 1}
PREVIEW_PATTERN = re.compile(rb"(\xff\xd8\xff\xdb.*\xff\xd9)", re.DOTALL)


def build_hp_metadata_transaction_plan(
    source_data: bytes,
    *,
    family: HpMetadataFamily | None = None,
    rewrite_requests: tuple[HpMetadataRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
    byte_order: HpByteOrder = "little",
) -> HpMetadataTransactionPlan:
    selected_family = family or detect_family(source_data)
    if selected_family is None:
        return unsupported_plan(
            source_data,
            family,
            "unsupported_hp_metadata_family",
            "The byte stream does not match a source-backed HP maker-note surface.",
        )

    parse_result = parse_family(source_data, selected_family, byte_order)
    fields, unknown_ranges, parse_gates, actions = parse_result
    gates = list(parse_gates)
    rewrite_steps, rewrite_gates, rewrite_actions = plan_rewrites(
        fields, rewrite_requests, allow_output_emission
    )
    gates.extend(rewrite_gates)
    actions.extend(rewrite_actions)
    if not rewrite_requests and not allow_output_emission and not parse_gates:
        gates.append(
            HpOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "HP plans preserve source bytes unless output emission is explicitly allowed.",
                (selected_source(selected_family),),
            )
        )
        actions.append(
            HpActionPlan(
                "no_metadata_mutation",
                selected_family,
                None,
                "Default HP transaction planning is non-mutating.",
                (selected_source(selected_family),),
            )
        )
    status: HpPlanStatus = "unsupported" if parse_gates else "planned"
    route = HpRoutingPlan(
        requested_family=family,
        selected_family=selected_family,
        reason=f"Selected HP {selected_family} routing from HP.pm.",
        evidence_ids=(selected_source(selected_family),),
    )
    sources = unique_sources(
        route.evidence_ids
        + tuple(source for field in fields for source in field.evidence_ids)
        + tuple(source for gate in gates for source in gate.evidence_ids)
        + tuple(source for action in actions for source in action.evidence_ids)
    )
    return HpMetadataTransactionPlan(
        status=status,
        source_data=source_data,
        routing=route,
        fields=tuple(fields),
        preservation=HpPreservationPlan(
            payload_range=(0, len(source_data)),
            unknown_ranges=tuple(unknown_ranges),
            evidence_ids=(selected_source(selected_family),),
        ),
        rewrite_steps=tuple(rewrite_steps),
        actions=tuple(actions),
        output_emission_gates=tuple(gates),
        evidence_ids=sources,
    )


def detect_family(source_data: bytes) -> HpMetadataFamily | None:
    if looks_like_tdhd(source_data):
        return "tdhd"
    if b"Serial Number:" in source_data or b"Lens Shading:" in source_data:
        return "type2"
    return None


def looks_like_tdhd(source_data: bytes) -> bool:
    if len(source_data) < 12:
        return False
    tag = source_data[:4]
    return tag.isalpha() and int.from_bytes(source_data[8:12], "little") <= len(source_data) - 12


def parse_family(
    source_data: bytes, family: HpMetadataFamily, byte_order: HpByteOrder
) -> tuple[
    list[HpFieldPlan],
    list[tuple[int, int]],
    list[HpOutputEmissionGate],
    list[HpActionPlan],
]:
    if family == "main":
        return parse_main_ifd(source_data, byte_order)
    if family == "type2":
        return parse_type2(source_data)
    if family == "type4":
        return parse_binary_data(source_data, family, TYPE4_TAGS, HP_TYPE4_TABLE_SOURCE)
    if family == "type6":
        return parse_binary_data(source_data, family, TYPE6_TAGS, HP_TYPE6_TABLE_SOURCE)
    return parse_tdhd(source_data)


def parse_main_ifd(
    source_data: bytes, byte_order: HpByteOrder
) -> tuple[
    list[HpFieldPlan],
    list[tuple[int, int]],
    list[HpOutputEmissionGate],
    list[HpActionPlan],
]:
    actions = [
        HpActionPlan(
            "route_main_ifd",
            "HP::Main",
            (0, len(source_data)),
            "Route EXIF-format HP maker-note IFD entries.",
            (HP_MAIN_TABLE_SOURCE,),
        )
    ]
    if len(source_data) < 2:
        return (
            [],
            [(0, len(source_data))],
            [gate("truncated_hp_main_ifd", HP_MAIN_TABLE_SOURCE)],
            actions,
        )
    entry_count = int.from_bytes(source_data[:2], byte_order)
    table_end = 2 + entry_count * 12 + 4
    if table_end > len(source_data):
        return (
            [],
            [(0, len(source_data))],
            [gate("truncated_hp_main_ifd", HP_MAIN_TABLE_SOURCE)],
            actions,
        )

    fields: list[HpFieldPlan] = []
    unknown_ranges: list[tuple[int, int]] = []
    gates: list[HpOutputEmissionGate] = []
    covered: list[tuple[int, int]] = [(0, table_end)]
    for index in range(entry_count):
        entry_start = 2 + index * 12
        entry = source_data[entry_start : entry_start + 12]
        tag_id = int.from_bytes(entry[0:2], byte_order)
        tiff_type = int.from_bytes(entry[2:4], byte_order)
        count = int.from_bytes(entry[4:8], byte_order)
        value_or_offset = int.from_bytes(entry[8:12], byte_order)
        type_size = TIFF_TYPE_SIZES.get(tiff_type)
        if type_size is None:
            gates.append(gate("malformed_hp_main_ifd", HP_MAIN_TABLE_SOURCE))
            unknown_ranges.append((entry_start, entry_start + 12))
            continue
        payload_size = type_size * count
        payload_range = (entry_start + 8, entry_start + 8 + min(payload_size, 4))
        if payload_size > 4:
            payload_range = (value_or_offset, value_or_offset + payload_size)
        start, end = payload_range
        if start < 0 or end > len(source_data) or start > end:
            gates.append(gate("malformed_hp_main_ifd", HP_MAIN_TABLE_SOURCE))
            unknown_ranges.append((entry_start, entry_start + 12))
            continue
        covered.append(payload_range)
        raw_payload = source_data[start:end]
        if tag_id == 0x0E00:
            fields.append(
                HpFieldPlan(
                    "PrintIM",
                    "0x0e00",
                    "main",
                    "Image",
                    "printim_payload",
                    "ifd_payload",
                    payload_range,
                    raw_payload,
                    raw_payload,
                    (HP_MAIN_TABLE_SOURCE,),
                )
            )
            actions.append(extract_action("PrintIM", payload_range, HP_MAIN_TABLE_SOURCE))
        else:
            unknown_ranges.append((entry_start, entry_start + 12))
    unknown_ranges.extend(complement_ranges(len(source_data), tuple(covered)))
    return fields, sorted_unique_ranges(unknown_ranges), gates, actions


def parse_type2(
    source_data: bytes,
) -> tuple[
    list[HpFieldPlan],
    list[tuple[int, int]],
    list[HpOutputEmissionGate],
    list[HpActionPlan],
]:
    fields: list[HpFieldPlan] = []
    actions = [
        HpActionPlan(
            "route_type2_text_scan",
            "HP::Type2",
            (0, len(source_data)),
            "Scan HP Type2 maker-note text tags and preview bytes.",
            (HP_TYPE2_TABLE_SOURCE, HP_PROCESS_HP_SOURCE),
        )
    ]
    gates: list[HpOutputEmissionGate] = []
    covered: list[tuple[int, int]] = []
    scan_data = source_data
    preview_start = source_data.find(b"\xff\xd8\xff\xdb")
    preview_match = PREVIEW_PATTERN.search(source_data)
    if preview_match is not None:
        raw_payload = preview_match.group(1)
        byte_range = preview_match.span(1)
        fields.append(
            HpFieldPlan(
                "PreviewImage",
                "PreviewImage",
                "type2",
                "Preview",
                "preview_payload",
                "jpeg_image",
                byte_range,
                raw_payload,
                raw_payload,
                (HP_TYPE2_TABLE_SOURCE, HP_PROCESS_HP_SOURCE),
            )
        )
        covered.append(byte_range)
        scan_data = source_data[: byte_range[0]]
        actions.append(extract_action("PreviewImage", byte_range, HP_PROCESS_HP_SOURCE))
    elif preview_start >= 0:
        gates.append(gate("malformed_hp_preview_image", HP_PROCESS_HP_SOURCE))

    for label, name in TEXT_TAGS:
        pattern = re.compile(
            re.escape(label).encode("ascii") + rb":\s*([\x20-\x7e]+)", re.IGNORECASE
        )
        match = pattern.search(scan_data)
        if match is None:
            continue
        value_range = match.span(1)
        raw_payload = source_data[value_range[0] : value_range[1]]
        fields.append(
            HpFieldPlan(
                name,
                label,
                "type2",
                "Camera",
                "text_metadata",
                "printable_ascii",
                value_range,
                raw_payload,
                raw_payload.decode("ascii"),
                (HP_TYPE2_TABLE_SOURCE, HP_PROCESS_HP_SOURCE),
            )
        )
        covered.append(value_range)
        actions.append(extract_action(name, value_range, HP_PROCESS_HP_SOURCE))
    return fields, complement_ranges(len(source_data), tuple(covered)), gates, actions


def parse_binary_data(
    source_data: bytes,
    family: Literal["type4", "type6"],
    specs: tuple[HpBinaryTagSpec, ...],
    table_source: str,
) -> tuple[
    list[HpFieldPlan],
    list[tuple[int, int]],
    list[HpOutputEmissionGate],
    list[HpActionPlan],
]:
    action_kind: HpActionKind = (
        "route_type4_binary_data" if family == "type4" else "route_type6_binary_data"
    )
    actions = [
        HpActionPlan(
            action_kind,
            f"HP::{family.title()}",
            (0, len(source_data)),
            "Route HP BinaryData maker-note fields at source-backed offsets.",
            (table_source,),
        )
    ]
    required_len = max(spec.tag_id + spec.byte_count for spec in specs)
    if len(source_data) < required_len:
        return (
            [],
            [(0, len(source_data))],
            [gate("truncated_hp_binary_data", table_source)],
            actions,
        )
    fields: list[HpFieldPlan] = []
    covered: list[tuple[int, int]] = []
    for spec in specs:
        byte_range = (spec.tag_id, spec.tag_id + spec.byte_count)
        raw_payload = source_data[byte_range[0] : byte_range[1]]
        interpreted_value = interpret_binary_field(spec.tag_name, raw_payload)
        fields.append(
            HpFieldPlan(
                spec.tag_name,
                f"0x{spec.tag_id:02x}",
                family,
                spec.group2,
                "binary_metadata",
                spec.value_boundary,
                byte_range,
                raw_payload,
                interpreted_value,
                spec.evidence_ids,
            )
        )
        covered.append(byte_range)
        actions.append(extract_action(spec.tag_name, byte_range, table_source))
    return fields, complement_ranges(len(source_data), tuple(covered)), [], actions


def parse_tdhd(
    source_data: bytes,
) -> tuple[
    list[HpFieldPlan],
    list[tuple[int, int]],
    list[HpOutputEmissionGate],
    list[HpActionPlan],
]:
    fields: list[HpFieldPlan] = []
    unknown_ranges: list[tuple[int, int]] = []
    gates: list[HpOutputEmissionGate] = []
    actions = [
        HpActionPlan(
            "route_tdhd_records",
            "HP::TDHD",
            (0, len(source_data)),
            "Walk HP TDHD records using little-endian type and size fields.",
            (HP_TDHD_TABLE_SOURCE, HP_TDHD_PROCESS_SOURCE),
        )
    ]
    parse_tdhd_records(source_data, 0, len(source_data), "", fields, unknown_ranges, gates, actions)
    return fields, sorted_unique_ranges(unknown_ranges), gates, actions


def parse_tdhd_records(
    source_data: bytes,
    start: int,
    end: int,
    prefix: str,
    fields: list[HpFieldPlan],
    unknown_ranges: list[tuple[int, int]],
    gates: list[HpOutputEmissionGate],
    actions: list[HpActionPlan],
) -> None:
    position = start
    while position < end:
        if position + 12 > end:
            gates.append(gate("truncated_tdhd_record_header", HP_TDHD_PROCESS_SOURCE))
            unknown_ranges.append((position, end))
            return
        tag = source_data[position : position + 4].decode("latin-1")
        record_type = int.from_bytes(source_data[position + 4 : position + 8], "little")
        size = int.from_bytes(source_data[position + 8 : position + 12], "little")
        payload_start = position + 12
        payload_end = payload_start + size
        record_range = (position, min(payload_end, end))
        if payload_end > end:
            gates.append(gate("truncated_tdhd_record_payload", HP_TDHD_PROCESS_SOURCE))
            unknown_ranges.append((position, end))
            return
        tag_path = f"{prefix}/{tag}" if prefix else tag
        if record_type == HP_TDHD_SUBDIRECTORY_TYPE:
            fields.append(
                HpFieldPlan(
                    tag,
                    tag_path,
                    "tdhd",
                    "Camera",
                    "tdhd_subdirectory",
                    "tdhd_record_payload",
                    (payload_start, payload_end),
                    source_data[payload_start:payload_end],
                    tag_path,
                    (HP_TDHD_TABLE_SOURCE, HP_TDHD_PROCESS_SOURCE),
                )
            )
            actions.append(
                HpActionPlan(
                    "route_tdhd_subdirectory",
                    tag_path,
                    record_range,
                    "TDHD record type 0x10001 routes to another HP TDHD table walk.",
                    (HP_TDHD_TABLE_SOURCE, HP_TDHD_PROCESS_SOURCE),
                )
            )
            parse_tdhd_records(
                source_data,
                payload_start,
                payload_end,
                tag_path,
                fields,
                unknown_ranges,
                gates,
                actions,
            )
        elif tag == "FWRV" or tag == "CMSN":
            tag_name = "FirmwareVersion" if tag == "FWRV" else "SerialNumber"
            fields.append(
                HpFieldPlan(
                    tag_name,
                    tag_path,
                    "tdhd",
                    "Camera",
                    "tdhd_metadata",
                    "tdhd_record_payload",
                    (payload_start, payload_end),
                    source_data[payload_start:payload_end],
                    decode_c_string(source_data[payload_start:payload_end]),
                    (HP_TDHD_TABLE_SOURCE, HP_TDHD_PROCESS_SOURCE),
                )
            )
            actions.append(
                extract_action(tag_path, (payload_start, payload_end), HP_TDHD_PROCESS_SOURCE)
            )
        else:
            unknown_ranges.append(record_range)
            fields.append(
                unknown_tdhd_field(tag, tag_path, payload_start, payload_end, source_data)
            )
            actions.append(
                HpActionPlan(
                    "preserve_unknown_bytes",
                    tag_path,
                    record_range,
                    "Unknown TDHD records are retained with their raw payload.",
                    (HP_TDHD_TABLE_SOURCE, HP_TDHD_PROCESS_SOURCE),
                )
            )
        position = payload_end


def unknown_tdhd_field(
    tag: str, tag_path: str, start: int, end: int, source_data: bytes
) -> HpFieldPlan:
    safe_name = "".join(character for character in tag if character.isalnum() or character in "-_")
    return HpFieldPlan(
        f"HP_TDHD_{safe_name}",
        tag_path,
        "tdhd",
        "Unknown",
        "unknown_tag",
        "unknown_payload",
        (start, end),
        source_data[start:end],
        interpret_tdhd_unknown(source_data[start:end]),
        (HP_TDHD_TABLE_SOURCE, HP_TDHD_PROCESS_SOURCE),
    )


def plan_rewrites(
    fields: list[HpFieldPlan],
    rewrite_requests: tuple[HpMetadataRewriteRequest, ...],
    allow_output_emission: bool,
) -> tuple[list[HpRewriteStepPlan], list[HpOutputEmissionGate], list[HpActionPlan]]:
    field_by_name = {field.tag_name: field for field in fields}
    seen: set[str] = set()
    steps: list[HpRewriteStepPlan] = []
    gates: list[HpOutputEmissionGate] = []
    actions: list[HpActionPlan] = []
    for request in rewrite_requests:
        field = field_by_name.get(request.tag_name)
        if request.tag_name in seen:
            gates.append(gate("duplicate_rewrite_tag", HP_PROCESS_HP_SOURCE))
            actions.append(
                block_rewrite_action(request.tag_name, "Duplicate HP rewrite tag request.")
            )
            continue
        seen.add(request.tag_name)
        if field is None:
            gates.append(gate("unknown_rewrite_tag", HP_PROCESS_HP_SOURCE))
            actions.append(
                block_rewrite_action(request.tag_name, "The requested tag is not in the HP plan.")
            )
            continue
        if not field.is_known_rewrite_target:
            gates.append(gate("unknown_tag_rewrite_not_source_backed", field.evidence_ids[0]))
            actions.append(
                block_rewrite_action(
                    request.tag_name, "Unknown HP tag bytes are preservation-only."
                )
            )
            continue
        if not request.source_backed:
            gates.append(gate("rewrite_requires_source_backed_request", field.evidence_ids[0]))
            actions.append(
                block_rewrite_action(
                    request.tag_name, "HP rewrite requests must opt into raw source backing."
                )
            )
            continue
        start, end = field.byte_range
        if len(request.replacement_payload) != end - start:
            gates.append(gate("rewrite_payload_size_mismatch", field.evidence_ids[0]))
            actions.append(
                block_rewrite_action(
                    request.tag_name, "HP raw replacements must preserve byte length."
                )
            )
            continue
        steps.append(
            HpRewriteStepPlan(
                request.tag_name,
                field.byte_range,
                request.replacement_payload,
                field.evidence_ids,
            )
        )
        actions.append(
            HpActionPlan(
                "apply_source_backed_rewrite",
                request.tag_name,
                field.byte_range,
                "Apply an explicitly source-backed same-size HP raw payload replacement.",
                field.evidence_ids,
            )
        )
    if steps and not allow_output_emission:
        gates.append(gate("rewrite_requires_explicit_output_emission", steps[0].evidence_ids[0]))
    return steps, gates, actions


def interpret_binary_field(tag_name: str, raw_payload: bytes) -> HpParsedValue:
    if tag_name == "MaxAperture" or tag_name == "FNumber":
        return int.from_bytes(raw_payload, "little") / 10
    if tag_name == "ExposureTime":
        return int.from_bytes(raw_payload, "little") / 1_000_000
    if tag_name == "CameraDateTime":
        return decode_c_string(raw_payload)
    if tag_name == "ISO":
        return int.from_bytes(raw_payload, "little")
    if tag_name == "SerialNumber":
        value = decode_c_string(raw_payload)
        prefix = "SERIAL NUMBER:"
        if value.startswith(prefix):
            return value.removeprefix(prefix)
        return None
    return raw_payload


def interpret_tdhd_unknown(raw_payload: bytes) -> HpParsedValue:
    if len(raw_payload) == 1:
        return raw_payload[0]
    if len(raw_payload) == 2:
        return int.from_bytes(raw_payload, "little")
    if len(raw_payload) == 4:
        return int.from_bytes(raw_payload, "little", signed=True)
    if is_printable(raw_payload):
        return decode_c_string(raw_payload)
    return raw_payload


def decode_c_string(raw_payload: bytes) -> str:
    return raw_payload.split(b"\x00", 1)[0].decode("latin-1")


def is_printable(raw_payload: bytes) -> bool:
    return all(0x20 <= byte <= 0x7E or byte == 0 for byte in raw_payload)


def extract_action(tag_name: str, byte_range: tuple[int, int], source: str) -> HpActionPlan:
    return HpActionPlan(
        "extract_known_tag",
        tag_name,
        byte_range,
        "Extract an HP tag defined by HP.pm.",
        (source,),
    )


def block_rewrite_action(tag_name: str, reason: str) -> HpActionPlan:
    return HpActionPlan("block_requested_rewrite", tag_name, None, reason, (HP_PROCESS_HP_SOURCE,))


def gate(code: HpEmissionGateCode, source: str) -> HpOutputEmissionGate:
    return HpOutputEmissionGate(code, gate_reason(code), (source,))


def gate_reason(code: HpEmissionGateCode) -> str:
    reasons = {
        "unsupported_hp_metadata_family": (
            "The input is not routed to an HP.pm-backed metadata family."
        ),
        "truncated_hp_main_ifd": "The HP EXIF maker-note IFD is truncated.",
        "malformed_hp_main_ifd": "The HP EXIF maker-note IFD points outside the source bytes.",
        "truncated_hp_binary_data": (
            "The HP BinaryData maker-note is shorter than the last known tag."
        ),
        "malformed_hp_preview_image": (
            "The HP preview starts like a JPEG but has no bounded end marker."
        ),
        "truncated_tdhd_record_header": "The TDHD stream ended inside a record header.",
        "truncated_tdhd_record_payload": "The TDHD stream ended inside a record payload.",
        "unknown_rewrite_tag": "The requested HP rewrite target is not present as a known field.",
        "unknown_tag_rewrite_not_source_backed": "Unknown HP tags are retained but not rewritten.",
        "duplicate_rewrite_tag": "The same HP tag was requested more than once.",
        "rewrite_requires_source_backed_request": (
            "HP raw replacement requires explicit source backing."
        ),
        "rewrite_payload_size_mismatch": (
            "The HP raw replacement does not match the source byte length."
        ),
        "rewrite_requires_explicit_output_emission": (
            "HP raw replacement output requires emission permission."
        ),
        "non_mutating_plan_requires_explicit_emission": (
            "HP plans are non-mutating unless emission is allowed."
        ),
    }
    return reasons[code]


def unsupported_plan(
    source_data: bytes,
    family: HpMetadataFamily | None,
    code: HpEmissionGateCode,
    reason: str,
) -> HpMetadataTransactionPlan:
    source = HP_MAIN_TABLE_SOURCE
    output_gate = HpOutputEmissionGate(code, reason, (source,))
    return HpMetadataTransactionPlan(
        status="unsupported",
        source_data=source_data,
        routing=HpRoutingPlan(family, None, reason, (source,)),
        fields=(),
        preservation=HpPreservationPlan((0, len(source_data)), ((0, len(source_data)),), (source,)),
        rewrite_steps=(),
        actions=(),
        output_emission_gates=(output_gate,),
        evidence_ids=(source,),
    )


def selected_source(family: HpMetadataFamily) -> str:
    if family == "main":
        return HP_MAIN_TABLE_SOURCE
    if family == "type2":
        return HP_TYPE2_TABLE_SOURCE
    if family == "type4":
        return HP_TYPE4_TABLE_SOURCE
    if family == "type6":
        return HP_TYPE6_TABLE_SOURCE
    return HP_TDHD_TABLE_SOURCE


def complement_ranges(
    length: int, covered_ranges: tuple[tuple[int, int], ...]
) -> list[tuple[int, int]]:
    ranges = sorted_unique_ranges(
        [(max(0, start), min(length, end)) for start, end in covered_ranges if start < end]
    )
    unknown: list[tuple[int, int]] = []
    position = 0
    for start, end in ranges:
        if position < start:
            unknown.append((position, start))
        position = max(position, end)
    if position < length:
        unknown.append((position, length))
    return unknown


def sorted_unique_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    ordered = sorted((start, end) for start, end in ranges if start < end)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return merged


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for source in sources:
        if source not in unique:
            unique.append(source)
    return tuple(unique)
