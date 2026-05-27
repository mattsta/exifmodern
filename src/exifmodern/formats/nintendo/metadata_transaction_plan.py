"""Source-backed Nintendo maker-note transaction planning."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

NINTENDO_PM_SOURCE_PATH = "lib/Image/ExifTool/Nintendo.pm"
NINTENDO_EPOCH_UNIX_OFFSET_SECONDS = 10957 * 24 * 3600

type NintendoPayloadKind = Literal["auto", "main", "camera_info"]
type NintendoResolvedPayloadKind = Literal["main", "camera_info"]
type NintendoPlanStatus = Literal["planned", "unsupported"]
type NintendoByteOrder = Literal["little", "big"]
type NintendoGroup2 = Literal["Camera", "Image", "Time", "Unknown"]
type NintendoResponsibilityGroup = Literal[
    "table_routing",
    "device_metadata",
    "time_metadata",
    "game_metadata",
    "image_metadata",
    "unknown_preservation",
]
type NintendoValueBoundary = Literal[
    "ifd_subdirectory_payload",
    "undef4",
    "int32u_time",
    "hex_serial_raw_conversion",
    "float",
    "int16u_category",
    "commented_preserved_int32u",
    "unknown_payload",
]
type NintendoActionKind = Literal[
    "route_main_ifd",
    "route_camera_info_subdirectory",
    "route_camera_info_binary_data",
    "extract_known_tag",
    "preserve_comment_backed_payload",
    "preserve_unknown_tag",
    "preserve_unknown_payload",
    "apply_source_backed_rewrite",
    "block_requested_rewrite",
    "no_metadata_mutation",
]
type NintendoOutputGateCode = Literal[
    "truncated_main_ifd_header",
    "truncated_main_ifd_entry",
    "truncated_main_ifd_value",
    "malformed_main_ifd_entry_type",
    "truncated_camera_info_payload",
    "unknown_rewrite_tag",
    "unknown_tag_rewrite_not_source_backed",
    "subdirectory_payload_rewrite_not_supported",
    "duplicate_rewrite_tag",
    "rewrite_requires_source_backed_request",
    "rewrite_payload_size_mismatch",
    "rewrite_requires_explicit_output_emission",
    "non_mutating_plan_requires_explicit_emission",
]
type NintendoParsedValue = int | float | str | bytes | None
type NintendoCategoryPrintValue = Literal["(none)", "Mii", "Man", "Woman"] | str | None


def evidence_id(
    line_start: int,
    line_end: int,
    symbol: str,
    evidence: str,
) -> str:
    return "nintendo." + symbol.lower().replace("%image::exiftool::nintendo::", "").replace(
        " ", "_"
    ).replace("::", ".")


NINTENDO_MAIN_SOURCE = evidence_id(
    19,
    34,
    "%Image::ExifTool::Nintendo::Main",
    "The Main table is a writable MakerNotes/Camera EXIF table and routes tag 0x1101.",
)
NINTENDO_MAIN_WRITE_SOURCE = evidence_id(
    20,
    23,
    "Nintendo Main EXIF write surface",
    "Nintendo Main declares Exif::WriteExif, Exif::CheckExif, and WRITABLE => 1.",
)
NINTENDO_CAMERA_INFO_ROUTE_SOURCE = evidence_id(
    27,
    32,
    "CameraInfo SubDirectory",
    "Main tag 0x1101 routes CameraInfo to Image::ExifTool::Nintendo::CameraInfo little-endian.",
)
NINTENDO_CAMERA_INFO_TABLE_SOURCE = evidence_id(
    36,
    45,
    "%Image::ExifTool::Nintendo::CameraInfo",
    "CameraInfo is writable int8u BinaryData with ProcessBinaryData and WriteBinaryData.",
)
NINTENDO_MODEL_ID_SOURCE = evidence_id(
    46,
    49,
    "ModelID",
    "CameraInfo offset 0x00 is ModelID with undef[4] format.",
)
NINTENDO_TIMESTAMP_SOURCE = evidence_id(
    51,
    60,
    "TimeStamp",
    "CameraInfo offset 0x08 is int32u TimeStamp with the Nintendo 2000-01-01 epoch.",
)
NINTENDO_SERIAL_SOURCE = evidence_id(
    64,
    70,
    "InternalSerialNumber",
    "CameraInfo offset 0x18 is InternalSerialNumber with raw bytes converted to hex.",
)
NINTENDO_PARALLAX_SOURCE = evidence_id(
    71,
    75,
    "Parallax",
    "CameraInfo offset 0x28 is a float formatted to two decimals for printing.",
)
NINTENDO_CATEGORY_SOURCE = evidence_id(
    77,
    87,
    "Category",
    "CameraInfo offset 0x30 is int16u Category with source-backed print labels.",
)
NINTENDO_COMMENTED_PAYLOAD_SOURCE = evidence_id(
    50,
    63,
    "CameraInfo commented offsets",
    "Nintendo.pm documents unnamed CameraInfo offsets 0x04, 0x10, and 0x14 without tag names.",
)


@dataclass(frozen=True)
class NintendoMetadataRewriteRequest:
    tag_name: str
    replacement_payload: bytes
    source_backed: bool = False


@dataclass(frozen=True)
class NintendoIfdEntryPlan:
    tag_id: int
    exif_type: str
    count: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_payload: bytes
    payload_is_inline: bool


@dataclass(frozen=True)
class NintendoFieldPlan:
    tag_name: str
    tag_id: str
    payload_kind: NintendoResolvedPayloadKind
    group2: NintendoGroup2
    responsibility_group: NintendoResponsibilityGroup
    value_boundary: NintendoValueBoundary
    byte_range: tuple[int, int]
    raw_payload: bytes
    interpreted_value: NintendoParsedValue
    print_value: NintendoCategoryPrintValue
    is_unknown: bool
    is_rewrite_supported: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NintendoCommentedPayloadPlan:
    name: str
    offset: int
    byte_range: tuple[int, int]
    responsibility_group: NintendoResponsibilityGroup
    value_boundary: NintendoValueBoundary
    raw_payload: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NintendoRoutingPlan:
    requested_payload_kind: NintendoPayloadKind
    resolved_payload_kind: NintendoResolvedPayloadKind
    byte_order: NintendoByteOrder
    table: str
    entry_count: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NintendoPreservationPlan:
    payload_range: tuple[int, int]
    unknown_main_tag_ids: tuple[int, ...]
    unknown_camera_info_ranges: tuple[tuple[int, int], ...]
    commented_payloads: tuple[NintendoCommentedPayloadPlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NintendoRewriteStepPlan:
    tag_name: str
    byte_range: tuple[int, int]
    replacement_payload: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NintendoActionPlan:
    kind: NintendoActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NintendoOutputEmissionGate:
    code: NintendoOutputGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NintendoMetadataTransactionPlan:
    status: NintendoPlanStatus
    source_data: bytes
    routing: NintendoRoutingPlan
    fields: tuple[NintendoFieldPlan, ...]
    preservation: NintendoPreservationPlan
    rewrite_steps: tuple[NintendoRewriteStepPlan, ...]
    actions: tuple[NintendoActionPlan, ...]
    output_emission_gates: tuple[NintendoOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def rewrite_supported_tag_names(self) -> tuple[str, ...]:
        return tuple(field.tag_name for field in self.fields if field.is_rewrite_supported)

    def field(self, tag_name: str) -> NintendoFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Nintendo metadata transaction output is gated: {gate_codes}")
        mutable = bytearray(self.source_data)
        for step in self.rewrite_steps:
            start, end = step.byte_range
            mutable[start:end] = step.replacement_payload
        return bytes(mutable)


@dataclass(frozen=True)
class CameraInfoTagSpec:
    offset: int
    byte_count: int
    tag_name: str
    group2: NintendoGroup2
    responsibility_group: NintendoResponsibilityGroup
    value_boundary: NintendoValueBoundary
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CameraInfoCommentSpec:
    offset: int
    byte_count: int
    name: str
    responsibility_group: NintendoResponsibilityGroup


EXIF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 7: 1}
EXIF_TYPE_NAMES = {
    1: "byte",
    2: "ascii",
    3: "short",
    4: "long",
    7: "undefined",
}
CAMERA_INFO_REQUIRED_SIZE = 0x32
CAMERA_INFO_TAGS: tuple[CameraInfoTagSpec, ...] = (
    CameraInfoTagSpec(
        0x00,
        4,
        "ModelID",
        "Image",
        "device_metadata",
        "undef4",
        (NINTENDO_MODEL_ID_SOURCE,),
    ),
    CameraInfoTagSpec(
        0x08,
        4,
        "TimeStamp",
        "Time",
        "time_metadata",
        "int32u_time",
        (NINTENDO_TIMESTAMP_SOURCE,),
    ),
    CameraInfoTagSpec(
        0x18,
        4,
        "InternalSerialNumber",
        "Camera",
        "device_metadata",
        "hex_serial_raw_conversion",
        (NINTENDO_SERIAL_SOURCE,),
    ),
    CameraInfoTagSpec(
        0x28,
        4,
        "Parallax",
        "Image",
        "image_metadata",
        "float",
        (NINTENDO_PARALLAX_SOURCE,),
    ),
    CameraInfoTagSpec(
        0x30,
        2,
        "Category",
        "Image",
        "image_metadata",
        "int16u_category",
        (NINTENDO_CATEGORY_SOURCE,),
    ),
)
CAMERA_INFO_COMMENTS: tuple[CameraInfoCommentSpec, ...] = (
    CameraInfoCommentSpec(0x04, 4, "CameraInfoVersion", "device_metadata"),
    CameraInfoCommentSpec(0x10, 4, "TitleIDLow", "game_metadata"),
    CameraInfoCommentSpec(0x14, 4, "Flags", "image_metadata"),
)
CATEGORY_LABELS = {
    0x0000: "(none)",
    0x1000: "Mii",
    0x2000: "Man",
    0x4000: "Woman",
}


def build_nintendo_metadata_transaction_plan(
    source_data: bytes,
    *,
    payload_kind: NintendoPayloadKind = "auto",
    byte_order: NintendoByteOrder = "little",
    rewrite_requests: tuple[NintendoMetadataRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> NintendoMetadataTransactionPlan:
    """Build a Nintendo maker-note transaction plan from in-memory bytes."""

    resolved = resolve_payload_kind(source_data, payload_kind)
    if resolved == "camera_info":
        plan = build_camera_info_plan(
            source_data,
            requested_payload_kind=payload_kind,
            rewrite_requests=rewrite_requests,
            allow_output_emission=allow_output_emission,
        )
    else:
        plan = build_main_plan(
            source_data,
            requested_payload_kind=payload_kind,
            byte_order=byte_order,
            rewrite_requests=rewrite_requests,
            allow_output_emission=allow_output_emission,
        )
    return plan


def resolve_payload_kind(
    source_data: bytes, payload_kind: NintendoPayloadKind
) -> NintendoResolvedPayloadKind:
    if payload_kind == "camera_info":
        return "camera_info"
    if payload_kind == "main":
        return "main"
    if source_data.startswith(b"3DS1"):
        return "camera_info"
    return "main"


def build_main_plan(
    source_data: bytes,
    *,
    requested_payload_kind: NintendoPayloadKind,
    byte_order: NintendoByteOrder,
    rewrite_requests: tuple[NintendoMetadataRewriteRequest, ...],
    allow_output_emission: bool,
) -> NintendoMetadataTransactionPlan:
    base_routing = NintendoRoutingPlan(
        requested_payload_kind,
        "main",
        byte_order,
        "Image::ExifTool::Nintendo::Main",
        None,
        (NINTENDO_MAIN_SOURCE, NINTENDO_MAIN_WRITE_SOURCE),
    )
    if len(source_data) < 2:
        gate = NintendoOutputEmissionGate(
            "truncated_main_ifd_header",
            "Nintendo Main maker notes require a two-byte IFD entry count.",
            (NINTENDO_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, base_routing, (gate,))

    entry_count = read_u16(source_data, 0, byte_order)
    routing = NintendoRoutingPlan(
        requested_payload_kind,
        "main",
        byte_order,
        "Image::ExifTool::Nintendo::Main",
        entry_count,
        base_routing.evidence_ids,
    )
    entry_region_end = 2 + entry_count * 12 + 4
    if len(source_data) < entry_region_end:
        gate = NintendoOutputEmissionGate(
            "truncated_main_ifd_entry",
            "Nintendo Main IFD entries or the next-directory pointer are incomplete.",
            (NINTENDO_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entries: list[NintendoIfdEntryPlan] = []
    parse_gates: list[NintendoOutputEmissionGate] = []
    for index in range(entry_count):
        entry_offset = 2 + index * 12
        parsed = parse_ifd_entry(source_data, entry_offset, byte_order)
        if isinstance(parsed, NintendoOutputEmissionGate):
            parse_gates.append(parsed)
        else:
            entries.append(parsed)

    fields: list[NintendoFieldPlan] = []
    actions: list[NintendoActionPlan] = [
        NintendoActionPlan(
            "route_main_ifd",
            "Image::ExifTool::Nintendo::Main",
            (0, len(source_data)),
            "Use the Nintendo Main EXIF maker-note table.",
            (NINTENDO_MAIN_SOURCE,),
        )
    ]
    unknown_main_tag_ids: list[int] = []
    unknown_camera_ranges: list[tuple[int, int]] = []
    commented_payloads: list[NintendoCommentedPayloadPlan] = []

    if not parse_gates:
        for entry in entries:
            if entry.tag_id == 0x1101:
                fields.append(
                    NintendoFieldPlan(
                        "CameraInfo",
                        "0x1101",
                        "main",
                        "Camera",
                        "table_routing",
                        "ifd_subdirectory_payload",
                        entry.value_range,
                        entry.raw_payload,
                        None,
                        None,
                        False,
                        False,
                        (NINTENDO_CAMERA_INFO_ROUTE_SOURCE,),
                    )
                )
                actions.append(
                    NintendoActionPlan(
                        "route_camera_info_subdirectory",
                        "CameraInfo",
                        entry.value_range,
                        "Route tag 0x1101 to the little-endian Nintendo CameraInfo table.",
                        (NINTENDO_CAMERA_INFO_ROUTE_SOURCE,),
                    )
                )
                camera_result = parse_camera_info_payload(entry.raw_payload, entry.value_range[0])
                fields.extend(camera_result.fields)
                actions.extend(camera_result.actions)
                parse_gates.extend(camera_result.gates)
                unknown_camera_ranges.extend(camera_result.unknown_ranges)
                commented_payloads.extend(camera_result.commented_payloads)
            else:
                fields.append(unknown_main_field(entry))
                unknown_main_tag_ids.append(entry.tag_id)
                actions.append(
                    NintendoActionPlan(
                        "preserve_unknown_tag",
                        f"Nintendo_0x{entry.tag_id:04x}",
                        entry.value_range,
                        "The Nintendo Main table has no source-backed tag definition here.",
                        (NINTENDO_MAIN_SOURCE,),
                    )
                )

    rewrite_steps, rewrite_gates, rewrite_actions = plan_rewrites(
        fields, rewrite_requests, allow_output_emission
    )
    output_gates = [*parse_gates, *rewrite_gates]
    if not rewrite_requests and not allow_output_emission and not parse_gates:
        output_gates.append(non_mutating_gate((NINTENDO_MAIN_WRITE_SOURCE,)))
        actions.append(no_mutation_action((NINTENDO_MAIN_WRITE_SOURCE,)))
    actions.extend(rewrite_actions)
    status: NintendoPlanStatus = "unsupported" if parse_gates else "planned"
    preservation = NintendoPreservationPlan(
        (0, len(source_data)),
        tuple(unknown_main_tag_ids),
        tuple(unknown_camera_ranges),
        tuple(commented_payloads),
        (NINTENDO_MAIN_SOURCE, NINTENDO_CAMERA_INFO_TABLE_SOURCE),
    )
    return NintendoMetadataTransactionPlan(
        status,
        source_data,
        routing,
        tuple(fields),
        preservation,
        tuple(rewrite_steps),
        tuple(actions),
        tuple(output_gates),
        collect_sources(tuple(fields), tuple(actions), tuple(output_gates), preservation),
    )


def build_camera_info_plan(
    source_data: bytes,
    *,
    requested_payload_kind: NintendoPayloadKind,
    rewrite_requests: tuple[NintendoMetadataRewriteRequest, ...],
    allow_output_emission: bool,
) -> NintendoMetadataTransactionPlan:
    routing = NintendoRoutingPlan(
        requested_payload_kind,
        "camera_info",
        "little",
        "Image::ExifTool::Nintendo::CameraInfo",
        None,
        (NINTENDO_CAMERA_INFO_TABLE_SOURCE,),
    )
    camera_result = parse_camera_info_payload(source_data, 0)
    rewrite_steps, rewrite_gates, rewrite_actions = plan_rewrites(
        camera_result.fields, rewrite_requests, allow_output_emission
    )
    output_gates = [*camera_result.gates, *rewrite_gates]
    actions = list(camera_result.actions)
    if not rewrite_requests and not allow_output_emission and not camera_result.gates:
        output_gates.append(non_mutating_gate((NINTENDO_CAMERA_INFO_TABLE_SOURCE,)))
        actions.append(no_mutation_action((NINTENDO_CAMERA_INFO_TABLE_SOURCE,)))
    actions.extend(rewrite_actions)
    status: NintendoPlanStatus = "unsupported" if camera_result.gates else "planned"
    preservation = NintendoPreservationPlan(
        (0, len(source_data)),
        (),
        camera_result.unknown_ranges,
        camera_result.commented_payloads,
        (NINTENDO_CAMERA_INFO_TABLE_SOURCE,),
    )
    return NintendoMetadataTransactionPlan(
        status,
        source_data,
        routing,
        camera_result.fields,
        preservation,
        tuple(rewrite_steps),
        tuple(actions),
        tuple(output_gates),
        collect_sources(camera_result.fields, tuple(actions), tuple(output_gates), preservation),
    )


@dataclass(frozen=True)
class CameraInfoParseResult:
    fields: tuple[NintendoFieldPlan, ...]
    actions: tuple[NintendoActionPlan, ...]
    gates: tuple[NintendoOutputEmissionGate, ...]
    unknown_ranges: tuple[tuple[int, int], ...]
    commented_payloads: tuple[NintendoCommentedPayloadPlan, ...]


def parse_camera_info_payload(payload: bytes, base_offset: int) -> CameraInfoParseResult:
    route_action = NintendoActionPlan(
        "route_camera_info_binary_data",
        "Image::ExifTool::Nintendo::CameraInfo",
        (base_offset, base_offset + len(payload)),
        "Use the Nintendo CameraInfo little-endian BinaryData table.",
        (NINTENDO_CAMERA_INFO_TABLE_SOURCE,),
    )
    if len(payload) < CAMERA_INFO_REQUIRED_SIZE:
        gate = NintendoOutputEmissionGate(
            "truncated_camera_info_payload",
            "CameraInfo is too short to contain the source-backed fields through Category.",
            (NINTENDO_CAMERA_INFO_TABLE_SOURCE,),
        )
        return CameraInfoParseResult((), (route_action,), (gate,), (), ())

    fields = tuple(camera_info_field(payload, base_offset, spec) for spec in CAMERA_INFO_TAGS)
    field_actions = tuple(
        NintendoActionPlan(
            "extract_known_tag",
            field.tag_name,
            field.byte_range,
            "Extract a source-backed Nintendo CameraInfo tag.",
            field.evidence_ids,
        )
        for field in fields
    )
    commented_payloads = tuple(
        commented_payload(payload, base_offset, spec) for spec in CAMERA_INFO_COMMENTS
    )
    commented_actions = tuple(
        NintendoActionPlan(
            "preserve_comment_backed_payload",
            item.name,
            item.byte_range,
            "Nintendo.pm documents this offset but does not name it as a tag.",
            item.evidence_ids,
        )
        for item in commented_payloads
    )
    occupied = tuple(
        (spec.offset, spec.offset + spec.byte_count) for spec in CAMERA_INFO_TAGS
    ) + tuple((spec.offset, spec.offset + spec.byte_count) for spec in CAMERA_INFO_COMMENTS)
    unknown_ranges = tuple(
        (base_offset + start, base_offset + end)
        for start, end in complement_ranges(0, len(payload), occupied)
    )
    unknown_actions = tuple(
        NintendoActionPlan(
            "preserve_unknown_payload",
            f"camera_info:{start:#x}-{end:#x}",
            (start, end),
            "CameraInfo bytes outside source-backed named or commented offsets are preserved.",
            (NINTENDO_CAMERA_INFO_TABLE_SOURCE,),
        )
        for start, end in unknown_ranges
    )
    return CameraInfoParseResult(
        fields,
        (route_action, *field_actions, *commented_actions, *unknown_actions),
        (),
        unknown_ranges,
        commented_payloads,
    )


def parse_ifd_entry(
    source_data: bytes, entry_offset: int, byte_order: NintendoByteOrder
) -> NintendoIfdEntryPlan | NintendoOutputEmissionGate:
    entry_end = entry_offset + 12
    tag_id = read_u16(source_data, entry_offset, byte_order)
    type_id = read_u16(source_data, entry_offset + 2, byte_order)
    count = read_u32(source_data, entry_offset + 4, byte_order)
    unit_size = EXIF_TYPE_SIZES.get(type_id)
    if unit_size is None:
        return NintendoOutputEmissionGate(
            "malformed_main_ifd_entry_type",
            f"Nintendo Main IFD tag 0x{tag_id:04x} uses unsupported EXIF type {type_id}.",
            (NINTENDO_MAIN_SOURCE,),
        )
    value_size = unit_size * count
    value_field = source_data[entry_offset + 8 : entry_offset + 12]
    if value_size <= 4:
        value_start = entry_offset + 8
        value_end = value_start + value_size
        raw_payload = value_field[:value_size]
        payload_is_inline = True
    else:
        value_start = read_u32(source_data, entry_offset + 8, byte_order)
        value_end = value_start + value_size
        if value_end > len(source_data):
            return NintendoOutputEmissionGate(
                "truncated_main_ifd_value",
                f"Nintendo Main IFD tag 0x{tag_id:04x} points outside the maker-note payload.",
                (NINTENDO_MAIN_SOURCE,),
            )
        raw_payload = source_data[value_start:value_end]
        payload_is_inline = False
    return NintendoIfdEntryPlan(
        tag_id,
        EXIF_TYPE_NAMES[type_id],
        count,
        (entry_offset, entry_end),
        (value_start, value_end),
        raw_payload,
        payload_is_inline,
    )


def camera_info_field(
    payload: bytes, base_offset: int, spec: CameraInfoTagSpec
) -> NintendoFieldPlan:
    raw_payload = payload[spec.offset : spec.offset + spec.byte_count]
    interpreted_value: NintendoParsedValue
    print_value: NintendoCategoryPrintValue = None
    if spec.tag_name == "ModelID":
        interpreted_value = raw_payload
    elif spec.tag_name == "TimeStamp":
        interpreted_value = (
            int.from_bytes(raw_payload, "little") + NINTENDO_EPOCH_UNIX_OFFSET_SECONDS
        )
    elif spec.tag_name == "InternalSerialNumber":
        interpreted_value = "0x" + raw_payload.hex()
    elif spec.tag_name == "Parallax":
        parallax_value = struct.unpack("<f", raw_payload)[0]
        interpreted_value = parallax_value
        print_value = f"{parallax_value:.2f}"
    else:
        category = int.from_bytes(raw_payload, "little")
        interpreted_value = category
        print_value = CATEGORY_LABELS.get(category, f"0x{category:04x}")
    return NintendoFieldPlan(
        spec.tag_name,
        f"0x{spec.offset:02x}",
        "camera_info",
        spec.group2,
        spec.responsibility_group,
        spec.value_boundary,
        (base_offset + spec.offset, base_offset + spec.offset + spec.byte_count),
        raw_payload,
        interpreted_value,
        print_value,
        False,
        True,
        spec.evidence_ids,
    )


def commented_payload(
    payload: bytes, base_offset: int, spec: CameraInfoCommentSpec
) -> NintendoCommentedPayloadPlan:
    return NintendoCommentedPayloadPlan(
        spec.name,
        spec.offset,
        (base_offset + spec.offset, base_offset + spec.offset + spec.byte_count),
        spec.responsibility_group,
        "commented_preserved_int32u",
        payload[spec.offset : spec.offset + spec.byte_count],
        (NINTENDO_COMMENTED_PAYLOAD_SOURCE,),
    )


def unknown_main_field(entry: NintendoIfdEntryPlan) -> NintendoFieldPlan:
    return NintendoFieldPlan(
        f"Nintendo_0x{entry.tag_id:04x}",
        f"0x{entry.tag_id:04x}",
        "main",
        "Unknown",
        "unknown_preservation",
        "unknown_payload",
        entry.value_range,
        entry.raw_payload,
        entry.raw_payload,
        None,
        True,
        False,
        (NINTENDO_MAIN_SOURCE,),
    )


def plan_rewrites(
    fields: tuple[NintendoFieldPlan, ...] | list[NintendoFieldPlan],
    rewrite_requests: tuple[NintendoMetadataRewriteRequest, ...],
    allow_output_emission: bool,
) -> tuple[
    list[NintendoRewriteStepPlan],
    list[NintendoOutputEmissionGate],
    list[NintendoActionPlan],
]:
    steps: list[NintendoRewriteStepPlan] = []
    gates: list[NintendoOutputEmissionGate] = []
    actions: list[NintendoActionPlan] = []
    field_by_name = {field.tag_name: field for field in fields}
    seen: set[str] = set()
    for request in rewrite_requests:
        field = field_by_name.get(request.tag_name)
        gate_code: NintendoOutputGateCode | None = None
        gate_reason = ""
        gate_sources: tuple[str, ...] = (NINTENDO_CAMERA_INFO_TABLE_SOURCE,)
        if request.tag_name in seen:
            gate_code = "duplicate_rewrite_tag"
            gate_reason = "Only one Nintendo rewrite request may target a tag."
        elif field is None:
            gate_code = "unknown_rewrite_tag"
            gate_reason = "The requested Nintendo tag is absent from the parsed source payload."
        elif field.is_unknown:
            gate_code = "unknown_tag_rewrite_not_source_backed"
            gate_reason = "Unknown Nintendo tags are preserved, not rewritten."
            gate_sources = field.evidence_ids
        elif not field.is_rewrite_supported:
            gate_code = "subdirectory_payload_rewrite_not_supported"
            gate_reason = "CameraInfo subdirectory payload replacement is not supported here."
            gate_sources = field.evidence_ids
        elif not request.source_backed:
            gate_code = "rewrite_requires_source_backed_request"
            gate_reason = "Nintendo rewrites must explicitly declare source-backed intent."
            gate_sources = field.evidence_ids
        elif len(request.replacement_payload) != len(field.raw_payload):
            gate_code = "rewrite_payload_size_mismatch"
            gate_reason = "Nintendo BinaryData rewrites must preserve the source field size."
            gate_sources = field.evidence_ids
        elif not allow_output_emission:
            gate_code = "rewrite_requires_explicit_output_emission"
            gate_reason = (
                "Nintendo transaction planning is non-mutating unless emission is allowed."
            )
            gate_sources = field.evidence_ids

        seen.add(request.tag_name)
        if gate_code is not None:
            gates.append(NintendoOutputEmissionGate(gate_code, gate_reason, gate_sources))
            actions.append(
                NintendoActionPlan(
                    "block_requested_rewrite",
                    request.tag_name,
                    field.byte_range if field is not None else None,
                    gate_reason,
                    gate_sources,
                )
            )
            continue

        if field is not None:
            steps.append(
                NintendoRewriteStepPlan(
                    field.tag_name,
                    field.byte_range,
                    request.replacement_payload,
                    field.evidence_ids,
                )
            )
            actions.append(
                NintendoActionPlan(
                    "apply_source_backed_rewrite",
                    field.tag_name,
                    field.byte_range,
                    "Apply a same-size rewrite to a source-backed Nintendo CameraInfo field.",
                    field.evidence_ids,
                )
            )
    return steps, gates, actions


def unsupported_plan(
    source_data: bytes,
    routing: NintendoRoutingPlan,
    gates: tuple[NintendoOutputEmissionGate, ...],
) -> NintendoMetadataTransactionPlan:
    action_kind: NintendoActionKind = (
        "route_camera_info_binary_data"
        if routing.resolved_payload_kind == "camera_info"
        else "route_main_ifd"
    )
    actions = (
        NintendoActionPlan(
            action_kind,
            routing.table,
            (0, len(source_data)),
            "Nintendo source-backed routing could not be completed.",
            routing.evidence_ids,
        ),
    )
    preservation = NintendoPreservationPlan(
        (0, len(source_data)),
        (),
        (),
        (),
        routing.evidence_ids,
    )
    return NintendoMetadataTransactionPlan(
        "unsupported",
        source_data,
        routing,
        (),
        preservation,
        (),
        actions,
        gates,
        collect_sources((), actions, gates, preservation),
    )


def non_mutating_gate(
    sources: tuple[str, ...],
) -> NintendoOutputEmissionGate:
    return NintendoOutputEmissionGate(
        "non_mutating_plan_requires_explicit_emission",
        "Nintendo metadata plans preserve source bytes unless output emission is explicit.",
        sources,
    )


def no_mutation_action(sources: tuple[str, ...]) -> NintendoActionPlan:
    return NintendoActionPlan(
        "no_metadata_mutation",
        "source_payload",
        None,
        "Default Nintendo transaction planning is non-mutating.",
        sources,
    )


def read_u16(data: bytes, offset: int, byte_order: NintendoByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 2], byte_order)


def read_u32(data: bytes, offset: int, byte_order: NintendoByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order)


def complement_ranges(
    start: int, end: int, occupied_ranges: tuple[tuple[int, int], ...]
) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    cursor = start
    for occupied_start, occupied_end in sorted(occupied_ranges):
        if cursor < occupied_start:
            ranges.append((cursor, occupied_start))
        cursor = max(cursor, occupied_end)
    if cursor < end:
        ranges.append((cursor, end))
    return tuple(ranges)


def collect_sources(
    fields: tuple[NintendoFieldPlan, ...],
    actions: tuple[NintendoActionPlan, ...],
    gates: tuple[NintendoOutputEmissionGate, ...],
    preservation: NintendoPreservationPlan,
) -> tuple[str, ...]:
    return unique_sources(
        (
            *preservation.evidence_ids,
            *(source for field in fields for source in field.evidence_ids),
            *(source for item in preservation.commented_payloads for source in item.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for source in sources:
        if source not in unique:
            unique.append(source)
    return tuple(unique)
