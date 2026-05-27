"""Source-grounded, non-mutating OpenEXR header transaction plans.

The planner mirrors ExifTool's ``OpenEXR.pm`` reader: it validates the magic
bytes, decodes the version/flag word, enumerates null-terminated attributes,
routes the value types ExifTool models, and preserves all post-header image
payload bytes.  It never rewrites OpenEXR bytes unless output emission is
explicitly allowed.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

OPENEXR_MAGIC = b"\x76\x2f\x31\x01"
OPENEXR_HEADER_SIZE = 8
OPENEXR_CHUNK_OFFSET_SIZE = 8

type OpenExrPlanStatus = Literal["planned", "unsupported"]
type OpenExrReadValue = str | int | float
type OpenExrAttributeRoute = Literal[
    "scalar_format",
    "channel_list",
    "tile_description",
    "string_vector",
    "subdirectory",
    "binary_preserve",
    "unknown_binary",
]
type OpenExrAttributeRole = Literal[
    "channels",
    "compression",
    "data_window",
    "display_window",
    "chromaticities",
    "tiles",
    "chunk_count",
    "exif",
    "xmp",
    "generic",
]
type OpenExrActionKind = Literal[
    "validate_magic",
    "decode_version_flags",
    "enumerate_attribute",
    "route_attribute_value",
    "preserve_header",
    "preserve_chunk_table",
    "preserve_pixel_data",
    "preserve_image_payload",
]
type OpenExrEmissionGateCode = Literal[
    "truncated_openexr_header",
    "unsupported_openexr_magic",
    "malformed_attribute_header",
    "truncated_attribute_value",
    "missing_header_terminator",
    "chunk_table_exceeds_input",
    "non_mutating_plan_requires_explicit_emission",
]
type OpenExrRewriteBlockerCode = Literal[
    "openexr_writer_not_modeled_by_exiftool_oracle",
    "attribute_rewrite_requires_header_relayout",
    "chunk_offsets_must_be_recomputed_after_header_size_change",
    "multipart_embedded_headers_require_extract_embedded_policy",
]

OPENEXR_FORMAT_TYPES_SOURCE = "openexr_format_types"
OPENEXR_TAG_TABLE_SOURCE = "openexr_tag_table"
OPENEXR_MAGIC_SOURCE = "openexr_magic"
OPENEXR_FLAGS_SOURCE = "openexr_flags"
OPENEXR_ATTRIBUTE_ENUM_SOURCE = "openexr_attribute_enum"
OPENEXR_ATTRIBUTE_ROUTING_SOURCE = "openexr_attribute_routing"
OPENEXR_TILE_SOURCE = "openexr_tile"
OPENEXR_CHANNEL_SOURCE = "openexr_channel"
OPENEXR_STRING_VECTOR_SOURCE = "openexr_string_vector"
OPENEXR_TRUNCATION_SOURCE = "openexr_truncation"
OPENEXR_DIMENSION_SOURCE = "openexr_dimension"

OPENEXR_TRANSACTION_SOURCES = (
    OPENEXR_FORMAT_TYPES_SOURCE,
    OPENEXR_TAG_TABLE_SOURCE,
    OPENEXR_MAGIC_SOURCE,
    OPENEXR_FLAGS_SOURCE,
    OPENEXR_ATTRIBUTE_ENUM_SOURCE,
    OPENEXR_ATTRIBUTE_ROUTING_SOURCE,
    OPENEXR_TILE_SOURCE,
    OPENEXR_CHANNEL_SOURCE,
    OPENEXR_STRING_VECTOR_SOURCE,
    OPENEXR_TRUNCATION_SOURCE,
    OPENEXR_DIMENSION_SOURCE,
)

SCALAR_FORMAT_TYPES: dict[str, str] = {
    "box2f": "float[4]",
    "box2i": "int32s[4]",
    "chromaticities": "float[8]",
    "compression": "int8u",
    "double": "double",
    "envmap": "int8u",
    "float": "float",
    "int": "int32s",
    "keycode": "int32s[7]",
    "lineOrder": "int8u",
    "m33f": "float[9]",
    "m44f": "float[16]",
    "rational": "rational64s",
    "string": "string",
    "timecode": "int32u[2]",
    "v2f": "float[2]",
    "v2i": "int32s[2]",
    "v3f": "float[3]",
    "v3i": "int32s[3]",
}
CUSTOM_FORMAT_TYPES = {"chlist", "stringvector", "tiledesc"}
SUBDIRECTORY_TAGS = {"exif", "xmp"}
COMPRESSION_LABELS: dict[int, str] = {
    0: "None",
    1: "RLE",
    2: "ZIPS",
    3: "ZIP",
    4: "PIZ",
    5: "PXR24",
    6: "B44",
    7: "B44A",
    8: "DWAA",
    9: "DWAB",
}
CHANNEL_PIXEL_TYPES: dict[int, str] = {0: "int8u", 1: "half", 2: "float"}
LINE_ORDER_LABELS: dict[int, str] = {0: "Increasing Y", 1: "Decreasing Y", 2: "Random Y"}


@dataclass(frozen=True)
class OpenExrMagicPlan:
    magic: bytes
    is_openexr: bool
    reason: OpenExrEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "is_openexr": self.is_openexr,
            "magic": self.magic.hex(),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OpenExrVersionFlagPlan:
    version: int | None
    raw_flags: int | None
    typed_flags: int | None
    max_attribute_name_length: int
    is_tiled: bool
    has_long_names: bool
    is_deep: bool
    is_multipart: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "has_long_names": self.has_long_names,
            "is_deep": self.is_deep,
            "is_multipart": self.is_multipart,
            "is_tiled": self.is_tiled,
            "max_attribute_name_length": self.max_attribute_name_length,
            "raw_flags": self.raw_flags,
            "typed_flags": self.typed_flags,
            "version": self.version,
        }


@dataclass(frozen=True)
class OpenExrAttributePlan:
    frame_index: int
    name: str
    type_name: str
    size: int
    header_range: tuple[int, int]
    value_range: tuple[int, int]
    total_range: tuple[int, int]
    route: OpenExrAttributeRoute
    role: OpenExrAttributeRole
    format_code: str | None
    value_summary: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "format_code": self.format_code,
            "frame_index": self.frame_index,
            "header_range": json_range(self.header_range),
            "name": self.name,
            "role": self.role,
            "route": self.route,
            "size": self.size,
            "total_range": json_range(self.total_range),
            "type_name": self.type_name,
            "value_range": json_range(self.value_range),
            "value_summary": self.value_summary,
        }


@dataclass(frozen=True)
class OpenExrChannelDescription:
    name: str
    pixel_type: str
    linear: bool
    x_sampling: int
    y_sampling: int

    def to_json(self) -> JsonObject:
        return {
            "linear": self.linear,
            "name": self.name,
            "pixel_type": self.pixel_type,
            "x_sampling": self.x_sampling,
            "y_sampling": self.y_sampling,
        }


@dataclass(frozen=True)
class OpenExrChannelResponsibilityPlan:
    attribute_name: str | None
    channels: tuple[OpenExrChannelDescription, ...]
    malformed_tail_bytes: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "attribute_name": self.attribute_name,
            "channels": json_object_array(channel.to_json() for channel in self.channels),
            "malformed_tail_bytes": self.malformed_tail_bytes,
        }


@dataclass(frozen=True)
class OpenExrCompressionResponsibilityPlan:
    attribute_name: str | None
    code: int | None
    label: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "attribute_name": self.attribute_name,
            "code": self.code,
            "label": self.label,
        }


@dataclass(frozen=True)
class OpenExrWindowResponsibilityPlan:
    data_window: tuple[int, int, int, int] | None
    display_window: tuple[int, int, int, int] | None
    image_width: int | None
    image_height: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "data_window": json_int_tuple(self.data_window),
            "display_window": json_int_tuple(self.display_window),
            "image_height": self.image_height,
            "image_width": self.image_width,
        }


@dataclass(frozen=True)
class OpenExrChromaticitiesResponsibilityPlan:
    values: tuple[float, float, float, float, float, float, float, float] | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "values": None if self.values is None else list(self.values),
        }


@dataclass(frozen=True)
class OpenExrTileResponsibilityPlan:
    tile_size_x: int | None
    tile_size_y: int | None
    level_mode: str | None
    rounding_mode: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "level_mode": self.level_mode,
            "rounding_mode": self.rounding_mode,
            "tile_size_x": self.tile_size_x,
            "tile_size_y": self.tile_size_y,
        }


@dataclass(frozen=True)
class OpenExrImagePayloadPlan:
    header_range: tuple[int, int] | None
    attribute_directory_range: tuple[int, int] | None
    terminator_range: tuple[int, int] | None
    chunk_table_range: tuple[int, int] | None
    pixel_data_range: tuple[int, int] | None
    image_payload_range: tuple[int, int] | None
    chunk_count: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "attribute_directory_range": json_range(self.attribute_directory_range),
            "chunk_count": self.chunk_count,
            "chunk_table_range": json_range(self.chunk_table_range),
            "header_range": json_range(self.header_range),
            "image_payload_range": json_range(self.image_payload_range),
            "pixel_data_range": json_range(self.pixel_data_range),
            "terminator_range": json_range(self.terminator_range),
        }


@dataclass(frozen=True)
class OpenExrRewriteBlocker:
    code: OpenExrRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OpenExrOutputEmissionGate:
    code: OpenExrEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OpenExrActionPlan:
    kind: OpenExrActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "kind": self.kind,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class OpenExrReadTagRecord:
    name: str
    group: str
    raw_value: OpenExrReadValue
    rendered_value: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "group": self.group,
            "name": self.name,
            "raw_value": self.raw_value,
            "rendered_value": self.rendered_value,
        }


@dataclass(frozen=True)
class OpenExrHeaderTransactionPlan:
    status: OpenExrPlanStatus
    source_data: bytes
    magic: OpenExrMagicPlan
    version_flags: OpenExrVersionFlagPlan
    attributes: tuple[OpenExrAttributePlan, ...]
    channels: OpenExrChannelResponsibilityPlan
    compression: OpenExrCompressionResponsibilityPlan
    windows: OpenExrWindowResponsibilityPlan
    chromaticities: OpenExrChromaticitiesResponsibilityPlan
    tiles: OpenExrTileResponsibilityPlan
    image_payload: OpenExrImagePayloadPlan
    read_tags: tuple[OpenExrReadTagRecord, ...]
    rewrite_blockers: tuple[OpenExrRewriteBlocker, ...]
    actions: tuple[OpenExrActionPlan, ...]
    output_emission_gates: tuple[OpenExrOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"OpenEXR header transaction output is gated: {gate_codes}")
        return self.source_data

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "attributes": json_object_array(attribute.to_json() for attribute in self.attributes),
            "can_emit_output": self.can_emit_output,
            "channels": self.channels.to_json(),
            "chromaticities": self.chromaticities.to_json(),
            "compression": self.compression.to_json(),
            "image_payload": self.image_payload.to_json(),
            "magic": self.magic.to_json(),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "read_tags": json_object_array(read_tag.to_json() for read_tag in self.read_tags),
            "rewrite_blockers": json_object_array(
                blocker.to_json() for blocker in self.rewrite_blockers
            ),
            "status": self.status,
            "tiles": self.tiles.to_json(),
            "version_flags": self.version_flags.to_json(),
            "windows": self.windows.to_json(),
        }


def build_openexr_header_transaction_plan(
    exr_data: bytes,
    *,
    allow_output_emission: bool = False,
    extract_embedded_headers: bool = False,
) -> OpenExrHeaderTransactionPlan:
    """Build a non-mutating OpenEXR header transaction plan from in-memory bytes."""

    gates: list[OpenExrOutputEmissionGate] = []
    magic = build_magic_plan(exr_data)
    if magic.reason is not None:
        gates.append(
            OpenExrOutputEmissionGate(
                code=magic.reason,
                reason="Input does not satisfy ExifTool's OpenEXR magic/read gate.",
                evidence_ids=magic.evidence_ids,
            )
        )
        return unsupported_plan(exr_data, magic, gates)

    version_flags = build_version_flag_plan(exr_data)
    attributes, terminator_range, header_end = enumerate_attributes(
        exr_data,
        version_flags,
        extract_embedded_headers,
        gates,
    )
    image_payload = build_image_payload_plan(
        exr_data, attributes, terminator_range, header_end, gates
    )
    channels = build_channel_responsibilities(exr_data, attributes)
    compression = build_compression_responsibility(exr_data, attributes)
    windows = build_window_responsibility(exr_data, attributes)
    chromaticities = build_chromaticities_responsibility(exr_data, attributes)
    tiles = build_tile_responsibility(exr_data, attributes)
    read_tags = build_openexr_read_tags(
        version_flags,
        attributes,
        compression,
        windows,
        tiles,
    )
    rewrite_blockers = build_rewrite_blockers(version_flags)
    actions = build_actions(attributes, image_payload)
    add_non_mutating_gate(gates, allow_output_emission)
    unique_gate_tuple = unique_emission_gates(tuple(gates))
    status: OpenExrPlanStatus = "unsupported" if structural_gate_present(gates) else "planned"
    sources = unique_sources(
        (
            *OPENEXR_TRANSACTION_SOURCES,
            *(source for gate in unique_gate_tuple for source in gate.evidence_ids),
            *(source for blocker in rewrite_blockers for source in blocker.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
        )
    )
    return OpenExrHeaderTransactionPlan(
        status=status,
        source_data=exr_data,
        magic=magic,
        version_flags=version_flags,
        attributes=attributes,
        channels=channels,
        compression=compression,
        windows=windows,
        chromaticities=chromaticities,
        tiles=tiles,
        image_payload=image_payload,
        read_tags=read_tags,
        rewrite_blockers=rewrite_blockers,
        actions=actions,
        output_emission_gates=unique_gate_tuple,
        evidence_ids=sources,
    )


plan_openexr_header_transaction = build_openexr_header_transaction_plan


def build_magic_plan(exr_data: bytes) -> OpenExrMagicPlan:
    if len(exr_data) < OPENEXR_HEADER_SIZE:
        return OpenExrMagicPlan(
            magic=exr_data[:4],
            is_openexr=False,
            reason="truncated_openexr_header",
            evidence_ids=(OPENEXR_MAGIC_SOURCE,),
        )
    magic = exr_data[:4]
    if magic != OPENEXR_MAGIC:
        return OpenExrMagicPlan(
            magic=magic,
            is_openexr=False,
            reason="unsupported_openexr_magic",
            evidence_ids=(OPENEXR_MAGIC_SOURCE,),
        )
    return OpenExrMagicPlan(
        magic=magic,
        is_openexr=True,
        reason=None,
        evidence_ids=(OPENEXR_MAGIC_SOURCE,),
    )


def build_version_flag_plan(exr_data: bytes) -> OpenExrVersionFlagPlan:
    raw_flags = read_u32le(exr_data, 4)
    return OpenExrVersionFlagPlan(
        version=raw_flags & 0xFF,
        raw_flags=raw_flags,
        typed_flags=raw_flags & 0xFFFFFF00,
        max_attribute_name_length=255 if raw_flags & 0x400 else 31,
        is_tiled=bool(raw_flags & 0x200),
        has_long_names=bool(raw_flags & 0x400),
        is_deep=bool(raw_flags & 0x800),
        is_multipart=bool(raw_flags & 0x1000),
        evidence_ids=(OPENEXR_FLAGS_SOURCE, OPENEXR_TAG_TABLE_SOURCE),
    )


def enumerate_attributes(
    exr_data: bytes,
    flags: OpenExrVersionFlagPlan,
    extract_embedded_headers: bool,
    gates: list[OpenExrOutputEmissionGate],
) -> tuple[tuple[OpenExrAttributePlan, ...], tuple[int, int] | None, int | None]:
    attributes: list[OpenExrAttributePlan] = []
    offset = OPENEXR_HEADER_SIZE
    frame_index = 0
    terminator_range: tuple[int, int] | None = None
    while True:
        if offset >= len(exr_data):
            gates.append(
                OpenExrOutputEmissionGate(
                    code="missing_header_terminator",
                    reason="Input ended before the null byte that terminates the OpenEXR header.",
                    evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE,),
                )
            )
            return tuple(attributes), terminator_range, None
        if exr_data[offset] == 0:
            terminator_range = (offset, offset + 1)
            offset += 1
            if not flags.is_multipart or not extract_embedded_headers:
                return tuple(attributes), terminator_range, offset
            if offset >= len(exr_data) or exr_data[offset] == 0:
                if offset < len(exr_data) and exr_data[offset] == 0:
                    terminator_range = (offset - 1, offset + 1)
                    offset += 1
                return tuple(attributes), terminator_range, offset
            frame_index += 1
            continue

        parsed = parse_attribute_at(exr_data, offset, frame_index, flags.max_attribute_name_length)
        if parsed.attribute is None:
            gates.append(parsed.gate)
            return tuple(attributes), terminator_range, None
        attributes.append(parsed.attribute)
        offset = parsed.attribute.total_range[1]


@dataclass(frozen=True)
class ParsedAttribute:
    attribute: OpenExrAttributePlan | None
    gate: OpenExrOutputEmissionGate


def parse_attribute_at(
    exr_data: bytes,
    offset: int,
    frame_index: int,
    max_length: int,
) -> ParsedAttribute:
    name_end = bounded_null_index(exr_data, offset, max_length)
    if name_end is None or name_end == offset:
        return malformed_attribute(offset)
    type_start = name_end + 1
    type_end = bounded_null_index(exr_data, type_start, max_length)
    if type_end is None or type_end == type_start:
        return malformed_attribute(offset)
    size_offset = type_end + 1
    size_end = size_offset + 4
    if size_end > len(exr_data):
        return malformed_attribute(offset)

    name = decode_latin1(exr_data[offset:name_end])
    type_name = decode_latin1(exr_data[type_start:type_end])
    size = read_u32le(exr_data, size_offset)
    value_start = size_end
    value_end = value_start + size
    if value_end > len(exr_data):
        return ParsedAttribute(
            attribute=None,
            gate=OpenExrOutputEmissionGate(
                code="truncated_attribute_value",
                reason="OpenEXR attribute value length points beyond available input.",
                evidence_ids=(OPENEXR_ATTRIBUTE_ROUTING_SOURCE, OPENEXR_TRUNCATION_SOURCE),
            ),
        )

    value = exr_data[value_start:value_end]
    route, format_code, route_sources = route_attribute(name, type_name)
    return ParsedAttribute(
        attribute=OpenExrAttributePlan(
            frame_index=frame_index,
            name=name,
            type_name=type_name,
            size=size,
            header_range=(offset, size_end),
            value_range=(value_start, value_end),
            total_range=(offset, value_end),
            route=route,
            role=attribute_role(name),
            format_code=format_code,
            value_summary=summarize_attribute_value(type_name, value),
            evidence_ids=route_sources,
        ),
        gate=OpenExrOutputEmissionGate(
            code="malformed_attribute_header",
            reason="Unused success placeholder.",
            evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE,),
        ),
    )


def malformed_attribute(offset: int) -> ParsedAttribute:
    return ParsedAttribute(
        attribute=None,
        gate=OpenExrOutputEmissionGate(
            code="malformed_attribute_header",
            reason=(
                f"OpenEXR attribute header at byte {offset} does not match "
                "ExifTool's null-terminated name/type/size pattern."
            ),
            evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE,),
        ),
    )


def route_attribute(
    name: str,
    type_name: str,
) -> tuple[OpenExrAttributeRoute, str | None, tuple[str, ...]]:
    if name in SUBDIRECTORY_TAGS:
        return "subdirectory", None, (OPENEXR_TAG_TABLE_SOURCE, OPENEXR_ATTRIBUTE_ROUTING_SOURCE)
    if type_name in SCALAR_FORMAT_TYPES:
        return (
            "scalar_format",
            SCALAR_FORMAT_TYPES[type_name],
            (OPENEXR_FORMAT_TYPES_SOURCE, OPENEXR_ATTRIBUTE_ROUTING_SOURCE),
        )
    if type_name == "chlist":
        return "channel_list", None, (OPENEXR_FORMAT_TYPES_SOURCE, OPENEXR_CHANNEL_SOURCE)
    if type_name == "tiledesc":
        return "tile_description", None, (OPENEXR_FORMAT_TYPES_SOURCE, OPENEXR_TILE_SOURCE)
    if type_name == "stringvector":
        return "string_vector", None, (OPENEXR_FORMAT_TYPES_SOURCE, OPENEXR_STRING_VECTOR_SOURCE)
    if type_name in CUSTOM_FORMAT_TYPES:
        return (
            "binary_preserve",
            None,
            (OPENEXR_FORMAT_TYPES_SOURCE, OPENEXR_ATTRIBUTE_ROUTING_SOURCE),
        )
    return "unknown_binary", None, (OPENEXR_ATTRIBUTE_ROUTING_SOURCE,)


def attribute_role(name: str) -> OpenExrAttributeRole:
    if name == "channels":
        return "channels"
    if name == "compression":
        return "compression"
    if name == "dataWindow":
        return "data_window"
    if name == "displayWindow":
        return "display_window"
    if name == "chromaticities":
        return "chromaticities"
    if name == "tiles":
        return "tiles"
    if name == "chunkCount":
        return "chunk_count"
    if name == "exif":
        return "exif"
    if name == "xmp":
        return "xmp"
    return "generic"


def build_channel_responsibilities(
    exr_data: bytes,
    attributes: tuple[OpenExrAttributePlan, ...],
) -> OpenExrChannelResponsibilityPlan:
    attribute = first_attribute(attributes, "channels")
    if attribute is None:
        return OpenExrChannelResponsibilityPlan(
            attribute_name=None,
            channels=(),
            malformed_tail_bytes=0,
            evidence_ids=(OPENEXR_CHANNEL_SOURCE,),
        )
    value = exr_data[attribute.value_range[0] : attribute.value_range[1]]
    channels, tail_bytes = parse_channels(value)
    return OpenExrChannelResponsibilityPlan(
        attribute_name=attribute.name,
        channels=channels,
        malformed_tail_bytes=tail_bytes,
        evidence_ids=(OPENEXR_CHANNEL_SOURCE,),
    )


def parse_channels(value: bytes) -> tuple[tuple[OpenExrChannelDescription, ...], int]:
    channels: list[OpenExrChannelDescription] = []
    offset = 0
    while offset < len(value):
        if value[offset] == 0:
            offset += 1
            break
        name_end = bounded_null_index(value, offset, 31)
        if name_end is None:
            break
        record_start = name_end + 1
        record_end = record_start + 16
        if record_end > len(value):
            break
        pixel_type_code = read_u32le(value, record_start)
        channels.append(
            OpenExrChannelDescription(
                name=decode_latin1(value[offset:name_end]),
                pixel_type=CHANNEL_PIXEL_TYPES.get(pixel_type_code, f"unknown({pixel_type_code})"),
                linear=bool(value[record_start + 4]),
                x_sampling=read_u32le(value, record_start + 8),
                y_sampling=read_u32le(value, record_start + 12),
            )
        )
        offset = record_end
    return tuple(channels), len(value) - offset


def build_compression_responsibility(
    exr_data: bytes,
    attributes: tuple[OpenExrAttributePlan, ...],
) -> OpenExrCompressionResponsibilityPlan:
    attribute = first_attribute(attributes, "compression")
    if attribute is None or attribute.size < 1:
        return OpenExrCompressionResponsibilityPlan(
            attribute_name=None,
            code=None,
            label=None,
            evidence_ids=(OPENEXR_TAG_TABLE_SOURCE,),
        )
    code = exr_data[attribute.value_range[0]]
    return OpenExrCompressionResponsibilityPlan(
        attribute_name=attribute.name,
        code=code,
        label=COMPRESSION_LABELS.get(code, f"Unknown ({code})"),
        evidence_ids=(OPENEXR_TAG_TABLE_SOURCE, OPENEXR_FORMAT_TYPES_SOURCE),
    )


def build_window_responsibility(
    exr_data: bytes,
    attributes: tuple[OpenExrAttributePlan, ...],
) -> OpenExrWindowResponsibilityPlan:
    data_window = read_box2i_attribute(exr_data, first_attribute(attributes, "dataWindow"))
    display_window = read_box2i_attribute(exr_data, first_attribute(attributes, "displayWindow"))
    dimension_window = data_window if data_window is not None else display_window
    image_width: int | None = None
    image_height: int | None = None
    if dimension_window is not None:
        image_width = dimension_window[2] - dimension_window[0] + 1
        image_height = dimension_window[3] - dimension_window[1] + 1
    return OpenExrWindowResponsibilityPlan(
        data_window=data_window,
        display_window=display_window,
        image_width=image_width,
        image_height=image_height,
        evidence_ids=(OPENEXR_DIMENSION_SOURCE, OPENEXR_FORMAT_TYPES_SOURCE),
    )


def build_chromaticities_responsibility(
    exr_data: bytes,
    attributes: tuple[OpenExrAttributePlan, ...],
) -> OpenExrChromaticitiesResponsibilityPlan:
    attribute = first_attribute(attributes, "chromaticities")
    values: tuple[float, float, float, float, float, float, float, float] | None = None
    if attribute is not None and attribute.size >= 32:
        value_start = attribute.value_range[0]
        values = struct.unpack("<8f", exr_data[value_start : value_start + 32])
    return OpenExrChromaticitiesResponsibilityPlan(
        values=values,
        evidence_ids=(OPENEXR_TAG_TABLE_SOURCE, OPENEXR_FORMAT_TYPES_SOURCE),
    )


def build_tile_responsibility(
    exr_data: bytes,
    attributes: tuple[OpenExrAttributePlan, ...],
) -> OpenExrTileResponsibilityPlan:
    attribute = first_attribute(attributes, "tiles")
    if attribute is None or attribute.size < 9:
        return OpenExrTileResponsibilityPlan(
            tile_size_x=None,
            tile_size_y=None,
            level_mode=None,
            rounding_mode=None,
            evidence_ids=(OPENEXR_TILE_SOURCE,),
        )
    value_offset = attribute.value_range[0]
    mode = exr_data[value_offset + 8]
    level_code = mode & 0x0F
    rounding_code = mode >> 4
    return OpenExrTileResponsibilityPlan(
        tile_size_x=read_u32le(exr_data, value_offset),
        tile_size_y=read_u32le(exr_data, value_offset + 4),
        level_mode={0: "One Level", 1: "MIMAP Levels", 2: "RIPMAP Levels"}.get(
            level_code, f"Unknown Levels ({level_code})"
        ),
        rounding_mode={0: "Round Down", 1: "Round Up"}.get(
            rounding_code, f"Unknown Rounding ({rounding_code})"
        ),
        evidence_ids=(OPENEXR_TILE_SOURCE,),
    )


def build_image_payload_plan(
    exr_data: bytes,
    attributes: tuple[OpenExrAttributePlan, ...],
    terminator_range: tuple[int, int] | None,
    header_end: int | None,
    gates: list[OpenExrOutputEmissionGate],
) -> OpenExrImagePayloadPlan:
    chunk_count = read_chunk_count(exr_data, attributes)
    header_range = (0, header_end) if header_end is not None else None
    attribute_directory_range = (
        (OPENEXR_HEADER_SIZE, terminator_range[0]) if terminator_range is not None else None
    )
    image_payload_range = (header_end, len(exr_data)) if header_end is not None else None
    chunk_table_range: tuple[int, int] | None = None
    pixel_data_range: tuple[int, int] | None = None
    if header_end is not None and chunk_count is not None:
        chunk_table_end = header_end + chunk_count * OPENEXR_CHUNK_OFFSET_SIZE
        if chunk_table_end > len(exr_data):
            gates.append(
                OpenExrOutputEmissionGate(
                    code="chunk_table_exceeds_input",
                    reason=(
                        "OpenEXR chunkCount requires more chunk-offset table bytes "
                        "than the input contains."
                    ),
                    evidence_ids=(OPENEXR_TAG_TABLE_SOURCE, OPENEXR_ATTRIBUTE_ROUTING_SOURCE),
                )
            )
        else:
            chunk_table_range = (header_end, chunk_table_end)
            pixel_data_range = (chunk_table_end, len(exr_data))
    elif header_end is not None:
        pixel_data_range = (header_end, len(exr_data))
    return OpenExrImagePayloadPlan(
        header_range=header_range,
        attribute_directory_range=attribute_directory_range,
        terminator_range=terminator_range,
        chunk_table_range=chunk_table_range,
        pixel_data_range=pixel_data_range,
        image_payload_range=image_payload_range,
        chunk_count=chunk_count,
        evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE, OPENEXR_TAG_TABLE_SOURCE),
    )


def build_openexr_read_tags(
    flags: OpenExrVersionFlagPlan,
    attributes: tuple[OpenExrAttributePlan, ...],
    compression: OpenExrCompressionResponsibilityPlan,
    windows: OpenExrWindowResponsibilityPlan,
    tiles: OpenExrTileResponsibilityPlan,
) -> tuple[OpenExrReadTagRecord, ...]:
    tags: list[OpenExrReadTagRecord] = []
    if flags.version is not None:
        tags.append(
            _openexr_tag("EXRVersion", flags.version, str(flags.version), OPENEXR_FLAGS_SOURCE)
        )
    if flags.typed_flags is not None:
        rendered_flags = ", ".join(
            label
            for active, label in (
                (flags.is_tiled, "Tiled"),
                (flags.has_long_names, "Long names"),
                (flags.is_deep, "Deep data"),
                (flags.is_multipart, "Multipart"),
            )
            if active
        )
        if not rendered_flags:
            rendered_flags = "(none)"
        tags.append(_openexr_tag("Flags", flags.typed_flags, rendered_flags, OPENEXR_FLAGS_SOURCE))
    if compression.code is not None and compression.label is not None:
        tags.append(
            _openexr_tag(
                "Compression",
                compression.code,
                compression.label,
                OPENEXR_TAG_TABLE_SOURCE,
            )
        )
    if windows.image_width is not None:
        tags.append(
            _openexr_tag(
                "ImageWidth",
                windows.image_width,
                str(windows.image_width),
                OPENEXR_DIMENSION_SOURCE,
            )
        )
    if windows.image_height is not None:
        tags.append(
            _openexr_tag(
                "ImageHeight",
                windows.image_height,
                str(windows.image_height),
                OPENEXR_DIMENSION_SOURCE,
            )
        )
    if windows.image_width is not None and windows.image_height is not None:
        megapixels = windows.image_width * windows.image_height / 1_000_000
        tags.append(
            _openexr_tag(
                "ImageSize",
                f"{windows.image_width}x{windows.image_height}",
                f"{windows.image_width}x{windows.image_height}",
                OPENEXR_DIMENSION_SOURCE,
                group="Composite",
            )
        )
        tags.append(
            _openexr_tag(
                "Megapixels",
                megapixels,
                _format_openexr_float(megapixels),
                OPENEXR_DIMENSION_SOURCE,
                group="Composite",
            )
        )
    if tiles.tile_size_x is not None and tiles.tile_size_y is not None:
        rendered = (
            f"{tiles.tile_size_x}x{tiles.tile_size_y}; {tiles.level_mode}; {tiles.rounding_mode}"
        )
        tags.append(_openexr_tag("Tiles", rendered, rendered, OPENEXR_TILE_SOURCE))
    for attribute in attributes:
        if attribute.value_summary is None or attribute.name in {"compression", "tiles"}:
            continue
        tags.append(
            _openexr_tag(
                openexr_tag_name(attribute.name),
                attribute.value_summary,
                attribute.value_summary,
                attribute.evidence_ids[0],
            )
        )
    return tuple(tags)


def _openexr_tag(
    name: str,
    raw_value: OpenExrReadValue,
    rendered_value: str,
    source: str,
    *,
    group: str = "OpenEXR",
) -> OpenExrReadTagRecord:
    return OpenExrReadTagRecord(
        name=name,
        group=group,
        raw_value=raw_value,
        rendered_value=rendered_value,
        evidence_ids=(source,),
    )


def openexr_tag_name(attribute_name: str) -> str:
    names = {
        "altitude": "GPSAltitude",
        "capDate": "DateTimeOriginal",
        "envmap": "EnvironmentMap",
        "expTime": "ExposureTime",
        "focus": "FocusDistance",
        "isoSpeed": "ISO",
        "latitude": "GPSLatitude",
        "longitude": "GPSLongitude",
        "utcOffset": "TimeZone",
        "wrapmodes": "WrapModes",
        "xDensity": "XResolution",
    }
    if attribute_name in names:
        return names[attribute_name]
    return attribute_name[:1].upper() + attribute_name[1:]


def read_chunk_count(exr_data: bytes, attributes: tuple[OpenExrAttributePlan, ...]) -> int | None:
    attribute = first_attribute(attributes, "chunkCount")
    if attribute is None or attribute.size < 4:
        return None
    return read_u32le(exr_data, attribute.value_range[0])


def build_rewrite_blockers(
    flags: OpenExrVersionFlagPlan,
) -> tuple[OpenExrRewriteBlocker, ...]:
    blockers = [
        OpenExrRewriteBlocker(
            code="openexr_writer_not_modeled_by_exiftool_oracle",
            reason=(
                "The ExifTool OpenEXR oracle only implements ProcessEXR read "
                "behavior, not a write path."
            ),
            evidence_ids=(OPENEXR_MAGIC_SOURCE,),
        ),
        OpenExrRewriteBlocker(
            code="attribute_rewrite_requires_header_relayout",
            reason=(
                "OpenEXR attributes are variable-length null-terminated records; "
                "changing them can move the image payload."
            ),
            evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE,),
        ),
        OpenExrRewriteBlocker(
            code="chunk_offsets_must_be_recomputed_after_header_size_change",
            reason=(
                "The chunk offset table follows the header terminator, so "
                "header-size changes require offset repair."
            ),
            evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE,),
        ),
    ]
    if flags.is_multipart:
        blockers.append(
            OpenExrRewriteBlocker(
                code="multipart_embedded_headers_require_extract_embedded_policy",
                reason=(
                    "ExifTool processes additional multipart headers only under ExtractEmbedded."
                ),
                evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE, OPENEXR_FLAGS_SOURCE),
            )
        )
    return tuple(blockers)


def build_actions(
    attributes: tuple[OpenExrAttributePlan, ...],
    image_payload: OpenExrImagePayloadPlan,
) -> tuple[OpenExrActionPlan, ...]:
    actions = [
        OpenExrActionPlan(
            kind="validate_magic",
            target=OPENEXR_MAGIC.hex(),
            byte_range=(0, 4),
            reason="Validate OpenEXR magic bytes before header parsing.",
            evidence_ids=(OPENEXR_MAGIC_SOURCE,),
        ),
        OpenExrActionPlan(
            kind="decode_version_flags",
            target="version_flags",
            byte_range=(4, 8),
            reason="Decode the version/flag word used for long names and multipart routing.",
            evidence_ids=(OPENEXR_FLAGS_SOURCE,),
        ),
    ]
    for attribute in attributes:
        actions.append(
            OpenExrActionPlan(
                kind="enumerate_attribute",
                target=attribute.name,
                byte_range=attribute.total_range,
                reason="Preserve an ExifTool-enumerated null-terminated OpenEXR attribute.",
                evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE,),
            )
        )
        actions.append(
            OpenExrActionPlan(
                kind="route_attribute_value",
                target=f"{attribute.name}:{attribute.route}",
                byte_range=attribute.value_range,
                reason=(
                    "Route the attribute value according to ExifTool's format table and handlers."
                ),
                evidence_ids=attribute.evidence_ids,
            )
        )
    if image_payload.header_range is not None:
        actions.append(
            OpenExrActionPlan(
                kind="preserve_header",
                target="openexr_header",
                byte_range=image_payload.header_range,
                reason="Preserve the complete OpenEXR header through the terminator.",
                evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE,),
            )
        )
    if image_payload.chunk_table_range is not None:
        actions.append(
            OpenExrActionPlan(
                kind="preserve_chunk_table",
                target="chunk_offset_table",
                byte_range=image_payload.chunk_table_range,
                reason="Preserve the chunk offset table that follows the header.",
                evidence_ids=(OPENEXR_TAG_TABLE_SOURCE,),
            )
        )
    if image_payload.pixel_data_range is not None:
        actions.append(
            OpenExrActionPlan(
                kind="preserve_pixel_data",
                target="pixel_data",
                byte_range=image_payload.pixel_data_range,
                reason="Preserve image chunk/pixel bytes after the header or chunk table.",
                evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE,),
            )
        )
    if image_payload.image_payload_range is not None:
        actions.append(
            OpenExrActionPlan(
                kind="preserve_image_payload",
                target="chunk_table_and_pixel_data",
                byte_range=image_payload.image_payload_range,
                reason="Preserve all bytes after the OpenEXR header terminator.",
                evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE,),
            )
        )
    return tuple(actions)


def unsupported_plan(
    exr_data: bytes,
    magic: OpenExrMagicPlan,
    gates: list[OpenExrOutputEmissionGate],
) -> OpenExrHeaderTransactionPlan:
    sources = unique_sources(
        (
            *OPENEXR_TRANSACTION_SOURCES,
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return OpenExrHeaderTransactionPlan(
        status="unsupported",
        source_data=exr_data,
        magic=magic,
        version_flags=empty_version_flags(),
        attributes=(),
        channels=OpenExrChannelResponsibilityPlan(None, (), 0, (OPENEXR_CHANNEL_SOURCE,)),
        compression=OpenExrCompressionResponsibilityPlan(
            None, None, None, (OPENEXR_TAG_TABLE_SOURCE,)
        ),
        windows=OpenExrWindowResponsibilityPlan(
            None, None, None, None, (OPENEXR_DIMENSION_SOURCE,)
        ),
        chromaticities=OpenExrChromaticitiesResponsibilityPlan(
            None, (OPENEXR_FORMAT_TYPES_SOURCE,)
        ),
        tiles=OpenExrTileResponsibilityPlan(None, None, None, None, (OPENEXR_TILE_SOURCE,)),
        image_payload=OpenExrImagePayloadPlan(
            header_range=None,
            attribute_directory_range=None,
            terminator_range=None,
            chunk_table_range=None,
            pixel_data_range=None,
            image_payload_range=None,
            chunk_count=None,
            evidence_ids=(OPENEXR_ATTRIBUTE_ENUM_SOURCE,),
        ),
        read_tags=(),
        rewrite_blockers=(),
        actions=(),
        output_emission_gates=unique_emission_gates(tuple(gates)),
        evidence_ids=sources,
    )


def empty_version_flags() -> OpenExrVersionFlagPlan:
    return OpenExrVersionFlagPlan(
        version=None,
        raw_flags=None,
        typed_flags=None,
        max_attribute_name_length=31,
        is_tiled=False,
        has_long_names=False,
        is_deep=False,
        is_multipart=False,
        evidence_ids=(OPENEXR_FLAGS_SOURCE,),
    )


def first_attribute(
    attributes: tuple[OpenExrAttributePlan, ...],
    name: str,
) -> OpenExrAttributePlan | None:
    for attribute in attributes:
        if attribute.name == name and attribute.frame_index == 0:
            return attribute
    return None


def read_box2i_attribute(
    exr_data: bytes,
    attribute: OpenExrAttributePlan | None,
) -> tuple[int, int, int, int] | None:
    if attribute is None or attribute.size < 16:
        return None
    return (
        read_i32le(exr_data, attribute.value_range[0]),
        read_i32le(exr_data, attribute.value_range[0] + 4),
        read_i32le(exr_data, attribute.value_range[0] + 8),
        read_i32le(exr_data, attribute.value_range[0] + 12),
    )


def summarize_attribute_value(type_name: str, value: bytes) -> str | None:
    if type_name == "compression" and value:
        code = value[0]
        return COMPRESSION_LABELS.get(code, f"Unknown ({code})")
    if type_name == "lineOrder" and value:
        code = value[0]
        return LINE_ORDER_LABELS.get(code, f"Unknown ({code})")
    if type_name == "float" and len(value) >= 4:
        return _format_openexr_float(struct.unpack("<f", value[:4])[0])
    if type_name == "v2f" and len(value) >= 8:
        parts = struct.unpack("<2f", value[:8])
        return f"{_format_openexr_float(parts[0])} {_format_openexr_float(parts[1])}"
    if type_name == "string":
        return decode_latin1(value)
    if type_name == "box2i" and len(value) >= 16:
        parts = (
            read_i32le(value, 0),
            read_i32le(value, 4),
            read_i32le(value, 8),
            read_i32le(value, 12),
        )
        return f"{parts[0]} {parts[1]} {parts[2]} {parts[3]}"
    if type_name == "chlist":
        channels, _tail = parse_channels(value)
        return ", ".join(
            f"{channel.name} {channel.pixel_type}"
            f"{' linear' if channel.linear else ''} {channel.x_sampling} {channel.y_sampling}"
            for channel in channels
        )
    if type_name == "tiledesc" and len(value) >= 9:
        tile_size_x, tile_size_y, level_mode, rounding_mode = parse_tile_description(value)
        return f"{tile_size_x}x{tile_size_y}; {level_mode}; {rounding_mode}"
    if type_name == "stringvector":
        return ", ".join(parse_string_vector(value))
    return None


def _format_openexr_float(value: float) -> str:
    return f"{value:.6g}"


def parse_string_vector(value: bytes) -> tuple[str, ...]:
    strings: list[str] = []
    offset = 0
    while offset + 4 <= len(value):
        size = read_u32le(value, offset)
        start = offset + 4
        end = start + size
        if end > len(value):
            break
        strings.append(decode_latin1(value[start:end]))
        offset = end
    return tuple(strings)


def parse_tile_description(value: bytes) -> tuple[int, int, str, str]:
    mode = value[8]
    level_code = mode & 0x0F
    rounding_code = mode >> 4
    return (
        read_u32le(value, 0),
        read_u32le(value, 4),
        {0: "One Level", 1: "MIMAP Levels", 2: "RIPMAP Levels"}.get(
            level_code, f"Unknown Levels ({level_code})"
        ),
        {0: "Round Down", 1: "Round Up"}.get(rounding_code, f"Unknown Rounding ({rounding_code})"),
    )


def bounded_null_index(data: bytes, offset: int, max_length: int) -> int | None:
    end = min(offset + max_length + 1, len(data))
    found = data.find(b"\0", offset, end)
    return None if found < 0 else found


def add_non_mutating_gate(
    gates: list[OpenExrOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        OpenExrOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="OpenEXR header transaction plans are non-mutating unless emission is allowed.",
            evidence_ids=(OPENEXR_MAGIC_SOURCE,),
        )
    )


def structural_gate_present(gates: list[OpenExrOutputEmissionGate]) -> bool:
    return any(gate.code != "non_mutating_plan_requires_explicit_emission" for gate in gates)


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def read_i32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=True)


def decode_latin1(data: bytes) -> str:
    return data.decode("latin-1")


def json_range(value: tuple[int, int] | None) -> JsonArray | None:
    return None if value is None else [value[0], value[1]]


def json_int_tuple(value: tuple[int, ...] | None) -> JsonArray | None:
    return None if value is None else list(value)


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return list(values)


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(reference)
    return tuple(unique)


def unique_emission_gates(
    gates: tuple[OpenExrOutputEmissionGate, ...],
) -> tuple[OpenExrOutputEmissionGate, ...]:
    unique: list[OpenExrOutputEmissionGate] = []
    seen: set[OpenExrEmissionGateCode] = set()
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
