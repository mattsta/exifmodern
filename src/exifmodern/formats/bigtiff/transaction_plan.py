"""Source-grounded, non-mutating BigTIFF metadata transaction plans.

The planner mirrors ExifTool's ``BigTIFF.pm`` reader closely enough to make
future write work explicit: validate the 16-byte header, classify byte order
and 8-byte offsets, walk 20-byte IFD entries, preserve external value payloads,
follow next-IFD and SubIFD routing, and gate output because ExifTool does not
support writing BigTIFF images.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from exifmodern.formats.tiff.primitives import TiffValue
from exifmodern.json_types import JsonArray, JsonObject

BIGTIFF_MAX_SUPPORTED_OFFSET = 0x7FFFFFFF
BIGTIFF_HEADER_SIZE = 16
BIGTIFF_DIRECTORY_COUNT_SIZE = 8
BIGTIFF_DIRECTORY_ENTRY_SIZE = 20
BIGTIFF_NEXT_IFD_POINTER_SIZE = 8
BIGTIFF_INLINE_VALUE_SIZE = 8
SUB_IFD_POINTER_TAG = 0x014A
EXIF_IFD_POINTER_TAG = 0x8769
GPS_IFD_POINTER_TAG = 0x8825

type BigTiffEndian = Literal["big", "little"]
type BigTiffEntryStorage = Literal["inline_value", "external_payload"]
type BigTiffDirectoryRoute = Literal["ifd_chain", "subifd"]
type BigTiffRouteRequest = tuple[str, str, int, BigTiffDirectoryRoute]
type BigTiffPlanStatus = Literal["planned", "blocked", "unsupported"]
type BigTiffGateCode = Literal[
    "truncated_bigtiff_header",
    "invalid_bigtiff_byte_order",
    "invalid_bigtiff_magic",
    "invalid_bigtiff_offset_size",
    "invalid_bigtiff_reserved_word",
    "bad_bigtiff_ifd_offset",
    "huge_bigtiff_offsets_require_large_file_support",
    "truncated_bigtiff_directory_count",
    "huge_bigtiff_directory_count_not_supported",
    "truncated_bigtiff_directory",
    "truncated_bigtiff_next_ifd_pointer",
    "unknown_bigtiff_entry_format",
    "huge_bigtiff_entry_size_not_supported",
    "bigtiff_entry_large_file_support_required",
    "bigtiff_entry_payload_read_error",
    "bigtiff_ifd_loop_detected",
    "planner_is_non_mutating",
    "bigtiff_writer_unsupported_by_exiftool",
]
type BigTiffRewriteBlockerCode = Literal[
    "exiftool_does_not_support_bigtiff_writes",
    "bigtiff_rewrite_requires_64_bit_ifd_relayout",
    "bigtiff_payload_offsets_must_be_preserved_or_recomputed",
]
type BigTiffSourceMaterializationStatus = Literal["materialized", "blocked", "unsupported"]
type BigTiffSourceMaterializerDiagnosticCode = Literal[
    "bigtiff_parse_blocked",
    "bigtiff_source_directory_blocked",
    "bigtiff_source_tag_value_unsupported",
]

BIGTIFF_MAX_OFFSET_EVIDENCE_ID = "bigtiff.max_offset"
BIGTIFF_MAX_OFFSET_SOURCE = BIGTIFF_MAX_OFFSET_EVIDENCE_ID
BIGTIFF_DIRECTORY_EVIDENCE_ID = "bigtiff.directory"
BIGTIFF_DIRECTORY_SOURCE = BIGTIFF_DIRECTORY_EVIDENCE_ID
BIGTIFF_ENTRY_EVIDENCE_ID = "bigtiff.entry"
BIGTIFF_ENTRY_SOURCE = BIGTIFF_ENTRY_EVIDENCE_ID
BIGTIFF_SUBIFD_EVIDENCE_ID = "bigtiff.subifd"
BIGTIFF_SUBIFD_SOURCE = BIGTIFF_SUBIFD_EVIDENCE_ID
BIGTIFF_IFD_CHAIN_EVIDENCE_ID = "bigtiff.ifd_chain"
BIGTIFF_IFD_CHAIN_SOURCE = BIGTIFF_IFD_CHAIN_EVIDENCE_ID
BIGTIFF_HEADER_EVIDENCE_ID = "bigtiff.header"
BIGTIFF_HEADER_SOURCE = BIGTIFF_HEADER_EVIDENCE_ID
BIGTIFF_WRITE_UNSUPPORTED_EVIDENCE_ID = "bigtiff.write_unsupported"
BIGTIFF_WRITE_UNSUPPORTED_SOURCE = BIGTIFF_WRITE_UNSUPPORTED_EVIDENCE_ID
BIGTIFF_DIRECTORY_ROUTE_EVIDENCE_ID = "bigtiff.directory_route"
BIGTIFF_DIRECTORY_ROUTE_SOURCE = BIGTIFF_DIRECTORY_ROUTE_EVIDENCE_ID

BIGTIFF_TRANSACTION_EVIDENCE_IDS = (
    BIGTIFF_MAX_OFFSET_EVIDENCE_ID,
    BIGTIFF_HEADER_EVIDENCE_ID,
    BIGTIFF_DIRECTORY_ROUTE_EVIDENCE_ID,
    BIGTIFF_DIRECTORY_EVIDENCE_ID,
    BIGTIFF_ENTRY_EVIDENCE_ID,
    BIGTIFF_SUBIFD_EVIDENCE_ID,
    BIGTIFF_IFD_CHAIN_EVIDENCE_ID,
    BIGTIFF_WRITE_UNSUPPORTED_EVIDENCE_ID,
)

FORMAT_SIZES: dict[int, int] = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    6: 1,
    7: 1,
    8: 2,
    9: 4,
    10: 8,
    11: 4,
    12: 8,
    13: 4,
    16: 8,
    17: 8,
    18: 8,
}
FORMAT_NAMES: dict[int, str] = {
    1: "int8u",
    2: "string",
    3: "int16u",
    4: "int32u",
    5: "rational64u",
    6: "int8s",
    7: "undef",
    8: "int16s",
    9: "int32s",
    10: "rational64s",
    11: "float",
    12: "double",
    13: "ifd",
    16: "int64u",
    17: "int64s",
    18: "ifd64",
}
SUBIFD_FORMAT_CODES = frozenset({4, 13, 16, 18})
BIGTIFF_EVIDENCE_ID_POINTER_FORMAT_CODES = frozenset({4, 13, 16, 18})
BIGTIFF_IFD0_EVIDENCE_ID_TAGS = {
    0x010E: "ImageDescription",
    0x010F: "Make",
    0x0110: "Model",
    0x0112: "Orientation",
    0x011A: "XResolution",
    0x011B: "YResolution",
    0x0128: "ResolutionUnit",
    0x0132: "ModifyDate",
    0x013B: "Artist",
    0x0213: "YCbCrPositioning",
    0x8298: "Copyright",
}
BIGTIFF_EXIF_EVIDENCE_ID_TAGS = {
    0x829A: "ExposureTime",
    0x829D: "FNumber",
    0x8827: "ISO",
    0x9000: "ExifVersion",
    0x9003: "DateTimeOriginal",
    0x9004: "CreateDate",
    0x9101: "ComponentsConfiguration",
    0x9102: "CompressedBitsPerPixel",
    0x9201: "ShutterSpeedValue",
    0x9202: "ApertureValue",
    0x9204: "ExposureCompensation",
    0x9205: "MaxApertureValue",
    0x9207: "MeteringMode",
    0x920A: "FocalLength",
    0x9286: "UserComment",
    0xA000: "FlashpixVersion",
    0xA001: "ColorSpace",
    0xA002: "ExifImageWidth",
    0xA003: "ExifImageHeight",
    0xA20E: "FocalPlaneXResolution",
    0xA20F: "FocalPlaneYResolution",
    0xA210: "FocalPlaneResolutionUnit",
    0xA217: "SensingMethod",
    0xA300: "FileSource",
    0xA401: "CustomRendered",
    0xA402: "ExposureMode",
    0xA403: "WhiteBalance",
    0xA406: "SceneCaptureType",
}
BIGTIFF_GPS_EVIDENCE_ID_TAGS = {
    0x0002: "GPSLatitude",
    0x0004: "GPSLongitude",
    0x0005: "GPSAltitudeRef",
    0x0006: "GPSAltitude",
    0x0008: "GPSSatellites",
    0x0009: "GPSStatus",
    0x000A: "GPSMeasureMode",
    0x000B: "GPSDOP",
    0x000C: "GPSSpeedRef",
    0x000D: "GPSSpeed",
    0x000E: "GPSTrackRef",
    0x000F: "GPSTrack",
    0x0010: "GPSImgDirectionRef",
    0x0011: "GPSImgDirection",
    0x0012: "GPSMapDatum",
    0x0014: "GPSDestLatitude",
    0x0016: "GPSDestLongitude",
    0x0017: "GPSDestBearingRef",
    0x0018: "GPSDestBearing",
    0x0019: "GPSDestDistanceRef",
    0x001A: "GPSDestDistance",
    0x001E: "GPSDifferential",
    0x001F: "GPSHPositioningError",
}


@dataclass(frozen=True)
class BigTiffGate:
    code: BigTiffGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BigTiffRewriteBlocker:
    code: BigTiffRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BigTiffHeaderPlan:
    raw_header: bytes
    byte_order_marker: bytes
    endian: BigTiffEndian | None
    magic: int | None
    offset_size: int | None
    reserved_word: int | None
    first_ifd_offset: int | None
    is_valid: bool
    reason: BigTiffGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_order_marker": self.byte_order_marker.hex(),
            "endian": self.endian,
            "first_ifd_offset": self.first_ifd_offset,
            "is_valid": self.is_valid,
            "magic": self.magic,
            "offset_size": self.offset_size,
            "raw_header": self.raw_header.hex(),
            "reason": self.reason,
            "reserved_word": self.reserved_word,
        }


@dataclass(frozen=True)
class BigTiffPayloadPlan:
    tag_id: int
    byte_range: tuple[int, int]
    byte_count: int
    payload_preview: bytes
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_count": self.byte_count,
            "byte_range": json_range(self.byte_range),
            "payload_preview_hex": self.payload_preview.hex(),
            "tag_id": tag_id_hex(self.tag_id),
        }


@dataclass(frozen=True)
class BigTiffEntryPlan:
    index: int
    tag_id: int
    format_code: int
    format_name: str | None
    count: int
    decoded_byte_count: int | None
    storage: BigTiffEntryStorage | None
    entry_range: tuple[int, int]
    value_field_range: tuple[int, int]
    value_offset: int | None
    payload_range: tuple[int, int] | None
    payload_preview: bytes
    subifd_offsets: tuple[int, ...]
    gates: tuple[BigTiffGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "count": self.count,
            "decoded_byte_count": self.decoded_byte_count,
            "entry_range": json_range(self.entry_range),
            "format_code": self.format_code,
            "format_name": self.format_name,
            "gates": json_object_array(gate.to_json() for gate in self.gates),
            "index": self.index,
            "payload_preview_hex": self.payload_preview.hex(),
            "payload_range": json_range(self.payload_range),
            "storage": self.storage,
            "subifd_offsets": list(self.subifd_offsets),
            "tag_id": tag_id_hex(self.tag_id),
            "value_field_range": json_range(self.value_field_range),
            "value_offset": self.value_offset,
        }


@dataclass(frozen=True)
class BigTiffDirectoryPlan:
    name: str
    route: BigTiffDirectoryRoute
    parent_name: str
    start_offset: int
    entry_count: int | None
    count_range: tuple[int, int] | None
    entries_range: tuple[int, int] | None
    next_ifd_pointer_range: tuple[int, int] | None
    next_ifd_offset: int | None
    entries: tuple[BigTiffEntryPlan, ...]
    gates: tuple[BigTiffGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.gates and all(not entry.gates for entry in self.entries)

    def to_json(self) -> JsonObject:
        return {
            "count_range": json_range(self.count_range),
            "entries": json_object_array(entry.to_json() for entry in self.entries),
            "entries_range": json_range(self.entries_range),
            "entry_count": self.entry_count,
            "gates": json_object_array(gate.to_json() for gate in self.gates),
            "is_valid": self.is_valid,
            "name": self.name,
            "next_ifd_offset": self.next_ifd_offset,
            "next_ifd_pointer_range": json_range(self.next_ifd_pointer_range),
            "parent_name": self.parent_name,
            "route": self.route,
            "start_offset": self.start_offset,
        }


@dataclass(frozen=True)
class BigTiffMetadataTransactionPlan:
    status: BigTiffPlanStatus
    source_data: bytes
    header: BigTiffHeaderPlan
    directories: tuple[BigTiffDirectoryPlan, ...]
    preserved_payloads: tuple[BigTiffPayloadPlan, ...]
    rewrite_blockers: tuple[BigTiffRewriteBlocker, ...]
    output_emission_gates: tuple[BigTiffGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def can_rewrite_metadata(self) -> bool:
        return False

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"BigTIFF metadata transaction output is gated: {gate_codes}")
        return self.source_data

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_rewrite_metadata": self.can_rewrite_metadata,
            "directories": json_object_array(directory.to_json() for directory in self.directories),
            "header": self.header.to_json(),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "preserved_payloads": json_object_array(
                payload.to_json() for payload in self.preserved_payloads
            ),
            "rewrite_blockers": json_object_array(
                blocker.to_json() for blocker in self.rewrite_blockers
            ),
            "status": self.status,
        }


@dataclass(frozen=True)
class BigTiffSourceMaterializerDiagnostic:
    code: BigTiffSourceMaterializerDiagnosticCode
    detail: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class BigTiffSourceTag:
    group: str
    name: str
    value: TiffValue
    field_type: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "field_type": self.field_type,
            "group": self.group,
            "name": self.name,
            "value": json_tiff_value(self.value),
        }


@dataclass(frozen=True)
class BigTiffExifGpsSourceMaterialization:
    status: BigTiffSourceMaterializationStatus
    plan: BigTiffMetadataTransactionPlan
    tags: tuple[BigTiffSourceTag, ...]
    diagnostics: tuple[BigTiffSourceMaterializerDiagnostic, ...]
    evidence_ids: tuple[str, ...]

    @property
    def tag_values(self) -> dict[tuple[str, str], TiffValue]:
        return {(tag.group, tag.name): tag.value for tag in self.tags}

    def to_json(self) -> JsonObject:
        return {
            "diagnostics": json_object_array(
                diagnostic.to_json() for diagnostic in self.diagnostics
            ),
            "status": self.status,
            "tags": json_object_array(tag.to_json() for tag in self.tags),
        }


def build_bigtiff_metadata_transaction_plan(
    data: bytes,
    *,
    allow_output_emission: bool = False,
    requested_rewrite: bool = False,
    large_file_support: bool = False,
) -> BigTiffMetadataTransactionPlan:
    """Build a source-backed BigTIFF metadata transaction plan without mutation."""

    header, header_gates = inspect_bigtiff_header(data)
    directories: tuple[BigTiffDirectoryPlan, ...] = ()
    parse_gates = header_gates

    if header.is_valid and header.endian is not None and header.first_ifd_offset is not None:
        directories, directory_gates = inspect_bigtiff_directories(
            data,
            endian=header.endian,
            first_ifd_offset=header.first_ifd_offset,
            large_file_support=large_file_support,
        )
        parse_gates = (*parse_gates, *directory_gates)

    rewrite_blockers = bigtiff_rewrite_blockers()
    output_gates = parse_gates
    if requested_rewrite:
        output_gates = (
            *output_gates,
            gate(
                "bigtiff_writer_unsupported_by_exiftool",
                "ExifTool's BigTIFF reader explicitly refuses BigTIFF output writes.",
                (BIGTIFF_WRITE_UNSUPPORTED_EVIDENCE_ID,),
            ),
        )
    if not allow_output_emission:
        output_gates = (
            *output_gates,
            gate(
                "planner_is_non_mutating",
                "BigTIFF transaction plans record metadata routing but do not mutate bytes.",
                (BIGTIFF_WRITE_UNSUPPORTED_EVIDENCE_ID,),
            ),
        )

    status: BigTiffPlanStatus = "planned"
    if parse_gates:
        status = "blocked"
    if not header.is_valid:
        status = "unsupported"

    return BigTiffMetadataTransactionPlan(
        status=status,
        source_data=data,
        header=header,
        directories=directories,
        preserved_payloads=preserved_payloads_from_directories(directories),
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=output_gates,
        evidence_ids=BIGTIFF_TRANSACTION_EVIDENCE_IDS,
    )


def materialize_bigtiff_exif_gps_source(
    data: bytes,
    *,
    large_file_support: bool = False,
) -> BigTiffExifGpsSourceMaterialization:
    """Expose source-backed BigTIFF EXIF/GPS scalar tags for exact-copy planning."""

    plan = build_bigtiff_metadata_transaction_plan(
        data,
        allow_output_emission=True,
        large_file_support=large_file_support,
    )
    if plan.status != "planned" or plan.header.endian is None:
        return BigTiffExifGpsSourceMaterialization(
            status="unsupported" if plan.status == "unsupported" else "blocked",
            plan=plan,
            tags=(),
            diagnostics=(
                BigTiffSourceMaterializerDiagnostic(
                    "bigtiff_parse_blocked",
                    "BigTIFF EXIF/GPS source tags require a valid parsed BigTIFF directory plan.",
                    plan.evidence_ids,
                ),
            ),
            evidence_ids=BIGTIFF_TRANSACTION_EVIDENCE_IDS,
        )

    tags: list[BigTiffSourceTag] = []
    diagnostics: list[BigTiffSourceMaterializerDiagnostic] = []
    ifd0 = first_bigtiff_directory(plan.directories, "IFD0")
    if ifd0 is not None:
        tags.extend(bigtiff_source_tags_from_directory(data, ifd0, plan.header.endian))
        for pointer_tag, directory_name, source_names in (
            (EXIF_IFD_POINTER_TAG, "ExifIFD", BIGTIFF_EXIF_EVIDENCE_ID_TAGS),
            (GPS_IFD_POINTER_TAG, "GPS", BIGTIFF_GPS_EVIDENCE_ID_TAGS),
        ):
            pointer_offset = bigtiff_pointer_offset(ifd0, pointer_tag, plan.header.endian)
            if pointer_offset is None:
                continue
            directory, directory_gates, _routes = parse_bigtiff_directory(
                data,
                endian=plan.header.endian,
                name=directory_name,
                parent_name="IFD0",
                start_offset=pointer_offset,
                route="subifd",
                large_file_support=large_file_support,
            )
            if directory_gates:
                diagnostics.append(
                    BigTiffSourceMaterializerDiagnostic(
                        "bigtiff_source_directory_blocked",
                        f"{directory_name} source directory could not be parsed.",
                        directory.evidence_ids,
                    )
                )
                continue
            tags.extend(
                bigtiff_source_tags_from_directory(
                    data,
                    directory,
                    plan.header.endian,
                    tag_names=source_names,
                )
            )
    status: BigTiffSourceMaterializationStatus = "materialized"
    if diagnostics:
        status = "blocked"
    return BigTiffExifGpsSourceMaterialization(
        status=status,
        plan=plan,
        tags=tuple(tags),
        diagnostics=tuple(diagnostics),
        evidence_ids=BIGTIFF_TRANSACTION_EVIDENCE_IDS,
    )


def inspect_bigtiff_header(data: bytes) -> tuple[BigTiffHeaderPlan, tuple[BigTiffGate, ...]]:
    raw_header = data[:BIGTIFF_HEADER_SIZE]
    if len(raw_header) < BIGTIFF_HEADER_SIZE:
        header = BigTiffHeaderPlan(
            raw_header=raw_header,
            byte_order_marker=raw_header[:2],
            endian=None,
            magic=None,
            offset_size=None,
            reserved_word=None,
            first_ifd_offset=None,
            is_valid=False,
            reason="truncated_bigtiff_header",
            evidence_ids=(BIGTIFF_HEADER_EVIDENCE_ID,),
        )
        return header, (
            gate(
                "truncated_bigtiff_header",
                "BigTIFF header reads require the first 16 bytes.",
                (BIGTIFF_HEADER_EVIDENCE_ID,),
            ),
        )

    marker = raw_header[:2]
    endian = endian_from_marker(marker)
    if endian is None:
        return invalid_header(
            raw_header,
            marker,
            None,
            None,
            None,
            None,
            "invalid_bigtiff_byte_order",
            "BigTIFF headers must begin with MM or II byte order markers.",
        )

    magic = read_u16(raw_header, 2, endian)
    offset_size = read_u16(raw_header, 4, endian)
    reserved_word = read_u16(raw_header, 6, endian)
    first_ifd_offset = read_u64(raw_header, 8, endian)
    if magic != 43:
        return invalid_header(
            raw_header,
            marker,
            endian,
            magic,
            offset_size,
            reserved_word,
            "invalid_bigtiff_magic",
            "BigTIFF headers must use TIFF magic 43.",
        )
    if offset_size != BIGTIFF_INLINE_VALUE_SIZE:
        return invalid_header(
            raw_header,
            marker,
            endian,
            magic,
            offset_size,
            reserved_word,
            "invalid_bigtiff_offset_size",
            "BigTIFF.pm accepts only 8-byte offset fields.",
        )
    if reserved_word != 0:
        return invalid_header(
            raw_header,
            marker,
            endian,
            magic,
            offset_size,
            reserved_word,
            "invalid_bigtiff_reserved_word",
            "The BigTIFF header reserved word must be zero.",
        )

    header = BigTiffHeaderPlan(
        raw_header=raw_header,
        byte_order_marker=marker,
        endian=endian,
        magic=magic,
        offset_size=offset_size,
        reserved_word=reserved_word,
        first_ifd_offset=first_ifd_offset,
        is_valid=True,
        reason=None,
        evidence_ids=(BIGTIFF_HEADER_EVIDENCE_ID,),
    )
    return header, ()


def inspect_bigtiff_directories(
    data: bytes,
    *,
    endian: BigTiffEndian,
    first_ifd_offset: int,
    large_file_support: bool,
) -> tuple[tuple[BigTiffDirectoryPlan, ...], tuple[BigTiffGate, ...]]:
    directories: list[BigTiffDirectoryPlan] = []
    gates: list[BigTiffGate] = []
    visited: dict[int, str] = {}
    worklist: tuple[BigTiffRouteRequest, ...] = (
        ("IFD0", "BigTIFF", first_ifd_offset, "ifd_chain"),
    )

    while worklist:
        directory_name, parent_name, start_offset, route = worklist[0]
        worklist = worklist[1:]
        if start_offset in visited:
            gates.append(
                gate(
                    "bigtiff_ifd_loop_detected",
                    f"{directory_name} points to an already processed {visited[start_offset]}.",
                    (BIGTIFF_IFD_CHAIN_EVIDENCE_ID,),
                )
            )
            continue
        visited[start_offset] = directory_name

        directory, directory_gates, routed_directories = parse_bigtiff_directory(
            data,
            endian=endian,
            name=directory_name,
            parent_name=parent_name,
            start_offset=start_offset,
            route=route,
            large_file_support=large_file_support,
        )
        directories.append(directory)
        gates.extend(directory_gates)
        worklist = (*routed_directories, *worklist)

    return tuple(directories), tuple(gates)


def parse_bigtiff_directory(
    data: bytes,
    *,
    endian: BigTiffEndian,
    name: str,
    parent_name: str,
    start_offset: int,
    route: BigTiffDirectoryRoute,
    large_file_support: bool,
) -> tuple[BigTiffDirectoryPlan, tuple[BigTiffGate, ...], tuple[BigTiffRouteRequest, ...]]:
    if start_offset > BIGTIFF_MAX_SUPPORTED_OFFSET and not large_file_support:
        directory_gate = gate(
            "huge_bigtiff_offsets_require_large_file_support",
            "Directory offsets above 0x7fffffff require LargeFileSupport.",
            (BIGTIFF_MAX_OFFSET_EVIDENCE_ID, BIGTIFF_DIRECTORY_EVIDENCE_ID),
        )
        return (
            empty_directory(name, parent_name, start_offset, route, (directory_gate,)),
            (directory_gate,),
            (),
        )
    if start_offset < 0 or start_offset >= len(data):
        directory_gate = gate(
            "bad_bigtiff_ifd_offset",
            "Directory offset is outside the input byte range.",
            (BIGTIFF_DIRECTORY_EVIDENCE_ID,),
        )
        return (
            empty_directory(name, parent_name, start_offset, route, (directory_gate,)),
            (directory_gate,),
            (),
        )

    count_end = start_offset + BIGTIFF_DIRECTORY_COUNT_SIZE
    if count_end > len(data):
        directory_gate = gate(
            "truncated_bigtiff_directory_count",
            "BigTIFF directory entry count is shorter than 8 bytes.",
            (BIGTIFF_DIRECTORY_EVIDENCE_ID,),
        )
        return (
            empty_directory(name, parent_name, start_offset, route, (directory_gate,)),
            (directory_gate,),
            (),
        )

    entry_count = read_u64(data, start_offset, endian)
    entries_size = entry_count * BIGTIFF_DIRECTORY_ENTRY_SIZE
    if entries_size > BIGTIFF_MAX_SUPPORTED_OFFSET:
        directory_gate = gate(
            "huge_bigtiff_directory_count_not_supported",
            "BigTIFF.pm does not support directory byte counts above 0x7fffffff.",
            (BIGTIFF_MAX_OFFSET_EVIDENCE_ID, BIGTIFF_DIRECTORY_EVIDENCE_ID),
        )
        directory = BigTiffDirectoryPlan(
            name=name,
            route=route,
            parent_name=parent_name,
            start_offset=start_offset,
            entry_count=entry_count,
            count_range=(start_offset, count_end),
            entries_range=None,
            next_ifd_pointer_range=None,
            next_ifd_offset=None,
            entries=(),
            gates=(directory_gate,),
            evidence_ids=(BIGTIFF_DIRECTORY_EVIDENCE_ID,),
        )
        return directory, (directory_gate,), ()

    entries_start = count_end
    entries_end = entries_start + entries_size
    if entries_end > len(data):
        directory_gate = gate(
            "truncated_bigtiff_directory",
            "BigTIFF directory entries extend beyond the input.",
            (BIGTIFF_DIRECTORY_EVIDENCE_ID,),
        )
        directory = BigTiffDirectoryPlan(
            name=name,
            route=route,
            parent_name=parent_name,
            start_offset=start_offset,
            entry_count=entry_count,
            count_range=(start_offset, count_end),
            entries_range=(entries_start, min(entries_end, len(data))),
            next_ifd_pointer_range=None,
            next_ifd_offset=None,
            entries=(),
            gates=(directory_gate,),
            evidence_ids=(BIGTIFF_DIRECTORY_EVIDENCE_ID,),
        )
        return directory, (directory_gate,), ()

    pointer_end = entries_end + BIGTIFF_NEXT_IFD_POINTER_SIZE
    if pointer_end > len(data):
        directory_gate = gate(
            "truncated_bigtiff_next_ifd_pointer",
            "BigTIFF directories require an 8-byte next-IFD pointer after entries.",
            (BIGTIFF_DIRECTORY_EVIDENCE_ID, BIGTIFF_IFD_CHAIN_EVIDENCE_ID),
        )
        directory = BigTiffDirectoryPlan(
            name=name,
            route=route,
            parent_name=parent_name,
            start_offset=start_offset,
            entry_count=entry_count,
            count_range=(start_offset, count_end),
            entries_range=(entries_start, entries_end),
            next_ifd_pointer_range=(entries_end, len(data)),
            next_ifd_offset=None,
            entries=(),
            gates=(directory_gate,),
            evidence_ids=(BIGTIFF_DIRECTORY_EVIDENCE_ID,),
        )
        return directory, (directory_gate,), ()

    entries: list[BigTiffEntryPlan] = []
    gates: list[BigTiffGate] = []
    routed_directories: list[BigTiffRouteRequest] = []
    for index in range(entry_count):
        entry_offset = entries_start + index * BIGTIFF_DIRECTORY_ENTRY_SIZE
        entry = parse_bigtiff_entry(
            data,
            endian=endian,
            directory_name=name,
            index=index,
            entry_offset=entry_offset,
            large_file_support=large_file_support,
        )
        entries.append(entry)
        gates.extend(entry.gates)
        for subifd_index, subifd_offset in enumerate(entry.subifd_offsets):
            subifd_name = "SubIFD" if subifd_index == 0 else f"SubIFD{subifd_index}"
            routed_directories.append((subifd_name, name, subifd_offset, "subifd"))

    next_ifd_offset = read_u64(data, entries_end, endian)
    if next_ifd_offset:
        routed_directories.append((next_ifd_name(name), name, next_ifd_offset, "ifd_chain"))

    directory = BigTiffDirectoryPlan(
        name=name,
        route=route,
        parent_name=parent_name,
        start_offset=start_offset,
        entry_count=entry_count,
        count_range=(start_offset, count_end),
        entries_range=(entries_start, entries_end),
        next_ifd_pointer_range=(entries_end, pointer_end),
        next_ifd_offset=next_ifd_offset,
        entries=tuple(entries),
        gates=tuple(gates),
        evidence_ids=(BIGTIFF_DIRECTORY_EVIDENCE_ID, BIGTIFF_IFD_CHAIN_EVIDENCE_ID),
    )
    return directory, tuple(gates), tuple(routed_directories)


def parse_bigtiff_entry(
    data: bytes,
    *,
    endian: BigTiffEndian,
    directory_name: str,
    index: int,
    entry_offset: int,
    large_file_support: bool,
) -> BigTiffEntryPlan:
    entry_end = entry_offset + BIGTIFF_DIRECTORY_ENTRY_SIZE
    value_field_start = entry_offset + 12
    value_field_range = (value_field_start, value_field_start + BIGTIFF_INLINE_VALUE_SIZE)
    tag_id = read_u16(data, entry_offset, endian)
    format_code = read_u16(data, entry_offset + 2, endian)
    count = read_u64(data, entry_offset + 4, endian)
    format_size = FORMAT_SIZES.get(format_code)
    if format_size is None:
        entry_gate = gate(
            "unknown_bigtiff_entry_format",
            f"Unknown BigTIFF format {format_code} for {directory_name} tag {tag_id_hex(tag_id)}.",
            (BIGTIFF_ENTRY_EVIDENCE_ID,),
        )
        return BigTiffEntryPlan(
            index=index,
            tag_id=tag_id,
            format_code=format_code,
            format_name=None,
            count=count,
            decoded_byte_count=None,
            storage=None,
            entry_range=(entry_offset, entry_end),
            value_field_range=value_field_range,
            value_offset=None,
            payload_range=None,
            payload_preview=b"",
            subifd_offsets=(),
            gates=(entry_gate,),
            evidence_ids=(BIGTIFF_ENTRY_EVIDENCE_ID,),
        )

    byte_count = count * format_size
    if byte_count <= BIGTIFF_INLINE_VALUE_SIZE:
        payload = data[value_field_start : value_field_start + byte_count]
        subifd_offsets = subifd_offsets_from_payload(tag_id, format_code, payload, endian)
        return BigTiffEntryPlan(
            index=index,
            tag_id=tag_id,
            format_code=format_code,
            format_name=FORMAT_NAMES[format_code],
            count=count,
            decoded_byte_count=byte_count,
            storage="inline_value",
            entry_range=(entry_offset, entry_end),
            value_field_range=value_field_range,
            value_offset=value_field_start,
            payload_range=(
                value_field_range if byte_count else (value_field_start, value_field_start)
            ),
            payload_preview=payload[:32],
            subifd_offsets=subifd_offsets,
            gates=(),
            evidence_ids=(BIGTIFF_ENTRY_EVIDENCE_ID,),
        )

    entry_gates: list[BigTiffGate] = []
    if byte_count > BIGTIFF_MAX_SUPPORTED_OFFSET:
        entry_gates.append(
            gate(
                "huge_bigtiff_entry_size_not_supported",
                "BigTIFF.pm skips external entry values above 0x7fffffff bytes.",
                (BIGTIFF_MAX_OFFSET_EVIDENCE_ID, BIGTIFF_ENTRY_EVIDENCE_ID),
            )
        )
    value_offset = read_u64(data, value_field_start, endian)
    if value_offset > BIGTIFF_MAX_SUPPORTED_OFFSET and not large_file_support:
        entry_gates.append(
            gate(
                "bigtiff_entry_large_file_support_required",
                "External value offsets above 0x7fffffff require LargeFileSupport.",
                (BIGTIFF_MAX_OFFSET_EVIDENCE_ID, BIGTIFF_ENTRY_EVIDENCE_ID),
            )
        )
    payload_end = value_offset + byte_count
    if not entry_gates and payload_end > len(data):
        entry_gates.append(
            gate(
                "bigtiff_entry_payload_read_error",
                "External BigTIFF entry payload cannot be read completely.",
                (BIGTIFF_ENTRY_EVIDENCE_ID,),
            )
        )

    payload = b"" if entry_gates else data[value_offset:payload_end]
    subifd_offsets = subifd_offsets_from_payload(tag_id, format_code, payload, endian)
    return BigTiffEntryPlan(
        index=index,
        tag_id=tag_id,
        format_code=format_code,
        format_name=FORMAT_NAMES[format_code],
        count=count,
        decoded_byte_count=byte_count,
        storage="external_payload",
        entry_range=(entry_offset, entry_end),
        value_field_range=value_field_range,
        value_offset=value_offset,
        payload_range=(value_offset, payload_end),
        payload_preview=payload[:32],
        subifd_offsets=subifd_offsets,
        gates=tuple(entry_gates),
        evidence_ids=(BIGTIFF_ENTRY_EVIDENCE_ID,),
    )


def subifd_offsets_from_payload(
    tag_id: int,
    format_code: int,
    payload: bytes,
    endian: BigTiffEndian,
) -> tuple[int, ...]:
    if tag_id != SUB_IFD_POINTER_TAG or format_code not in SUBIFD_FORMAT_CODES:
        return ()
    step = FORMAT_SIZES[format_code]
    offsets: list[int] = []
    for offset in range(0, len(payload), step):
        if offset + step > len(payload):
            break
        if step == 4:
            subifd_offset = read_u32(payload, offset, endian)
        else:
            subifd_offset = read_u64(payload, offset, endian)
        if subifd_offset:
            offsets.append(subifd_offset)
    return tuple(offsets)


def preserved_payloads_from_directories(
    directories: tuple[BigTiffDirectoryPlan, ...],
) -> tuple[BigTiffPayloadPlan, ...]:
    payloads: list[BigTiffPayloadPlan] = []
    for directory in directories:
        for entry in directory.entries:
            if entry.storage == "external_payload" and entry.payload_range is not None:
                payloads.append(
                    BigTiffPayloadPlan(
                        tag_id=entry.tag_id,
                        byte_range=entry.payload_range,
                        byte_count=entry.decoded_byte_count or 0,
                        payload_preview=entry.payload_preview,
                        evidence_ids=(BIGTIFF_ENTRY_EVIDENCE_ID,),
                    )
                )
    return tuple(payloads)


def first_bigtiff_directory(
    directories: tuple[BigTiffDirectoryPlan, ...],
    name: str,
) -> BigTiffDirectoryPlan | None:
    for directory in directories:
        if directory.name == name:
            return directory
    return None


def bigtiff_pointer_offset(
    directory: BigTiffDirectoryPlan,
    pointer_tag: int,
    endian: BigTiffEndian,
) -> int | None:
    for entry in directory.entries:
        if (
            entry.tag_id != pointer_tag
            or entry.format_code not in BIGTIFF_EVIDENCE_ID_POINTER_FORMAT_CODES
        ):
            continue
        value = bigtiff_entry_value_from_payload(entry.payload_preview, entry.format_code, endian)
        if isinstance(value, int):
            return value
        if isinstance(value, list) and value and isinstance(value[0], int):
            return value[0]
    return None


def bigtiff_source_tags_from_directory(
    data: bytes,
    directory: BigTiffDirectoryPlan,
    endian: BigTiffEndian,
    tag_names: dict[int, str] | None = None,
) -> tuple[BigTiffSourceTag, ...]:
    names = tag_names if tag_names is not None else BIGTIFF_IFD0_EVIDENCE_ID_TAGS
    tags: list[BigTiffSourceTag] = []
    for entry in directory.entries:
        name = names.get(entry.tag_id)
        if name is None:
            continue
        value = bigtiff_source_entry_tiff_value(data, entry, endian)
        tags.append(
            BigTiffSourceTag(
                group=directory.name,
                name=name,
                value=value,
                field_type=entry.format_code,
                evidence_ids=(BIGTIFF_ENTRY_EVIDENCE_ID,),
            )
        )
    return tuple(tags)


def bigtiff_source_entry_tiff_value(
    data: bytes,
    entry: BigTiffEntryPlan,
    endian: BigTiffEndian,
) -> TiffValue:
    payload = bigtiff_source_entry_payload(data, entry)
    return bigtiff_entry_value_from_payload(payload, entry.format_code, endian)


def bigtiff_source_entry_payload(data: bytes, entry: BigTiffEntryPlan) -> bytes:
    byte_count = entry.decoded_byte_count or 0
    if byte_count == 0:
        return b""
    if entry.storage == "inline_value":
        start, _end = entry.value_field_range
        return data[start : start + byte_count]
    if entry.storage == "external_payload" and entry.payload_range is not None:
        start, end = entry.payload_range
        return data[start:end]
    return b""


def bigtiff_entry_value_from_payload(
    payload: bytes,
    format_code: int,
    endian: BigTiffEndian,
) -> TiffValue:
    if format_code == 1:
        return payload[0] if len(payload) == 1 else list(payload)
    if format_code == 2:
        return payload.rstrip(b"\0").decode("utf-8", errors="replace")
    if format_code == 3:
        short_values = [
            read_u16(payload, offset, endian)
            for offset in range(0, len(payload) - (len(payload) % 2), 2)
        ]
        return short_values[0] if len(short_values) == 1 else short_values
    if format_code in {4, 13}:
        long_values = [
            read_u32(payload, offset, endian)
            for offset in range(0, len(payload) - (len(payload) % 4), 4)
        ]
        return long_values[0] if len(long_values) == 1 else long_values
    if format_code == 5:
        rational_values: list[Fraction | None] = []
        for offset in range(0, len(payload) - (len(payload) % 8), 8):
            numerator = read_u32(payload, offset, endian)
            denominator = read_u32(payload, offset + 4, endian)
            rational_values.append(Fraction(numerator, denominator) if denominator else None)
        return rational_values[0] if len(rational_values) == 1 else rational_values
    if format_code == 7:
        return payload
    if format_code == 9:
        signed_long_values = [
            int.from_bytes(payload[offset : offset + 4], byte_order(endian), signed=True)
            for offset in range(0, len(payload) - (len(payload) % 4), 4)
        ]
        return signed_long_values[0] if len(signed_long_values) == 1 else signed_long_values
    if format_code == 10:
        signed_rational_values: list[Fraction | None] = []
        for offset in range(0, len(payload) - (len(payload) % 8), 8):
            numerator = int.from_bytes(
                payload[offset : offset + 4],
                byte_order(endian),
                signed=True,
            )
            denominator = int.from_bytes(
                payload[offset + 4 : offset + 8],
                byte_order(endian),
                signed=True,
            )
            signed_rational_values.append(Fraction(numerator, denominator) if denominator else None)
        return (
            signed_rational_values[0]
            if len(signed_rational_values) == 1
            else signed_rational_values
        )
    if format_code in {16, 18}:
        long8_values = [
            read_u64(payload, offset, endian)
            for offset in range(0, len(payload) - (len(payload) % 8), 8)
        ]
        return long8_values[0] if len(long8_values) == 1 else long8_values
    if format_code == 17:
        signed_long8_values = [
            int.from_bytes(payload[offset : offset + 8], byte_order(endian), signed=True)
            for offset in range(0, len(payload) - (len(payload) % 8), 8)
        ]
        return signed_long8_values[0] if len(signed_long8_values) == 1 else signed_long8_values
    if format_code in {11, 12}:
        return payload
    return None


def bigtiff_rewrite_blockers() -> tuple[BigTiffRewriteBlocker, ...]:
    return (
        BigTiffRewriteBlocker(
            code="exiftool_does_not_support_bigtiff_writes",
            reason="ExifTool BigTIFF.pm returns an error when asked to write BigTIFF.",
            evidence_ids=(BIGTIFF_WRITE_UNSUPPORTED_EVIDENCE_ID,),
        ),
        BigTiffRewriteBlocker(
            code="bigtiff_rewrite_requires_64_bit_ifd_relayout",
            reason="BigTIFF directory counts, value counts, and next pointers are 64-bit fields.",
            evidence_ids=(BIGTIFF_DIRECTORY_EVIDENCE_ID, BIGTIFF_ENTRY_EVIDENCE_ID),
        ),
        BigTiffRewriteBlocker(
            code="bigtiff_payload_offsets_must_be_preserved_or_recomputed",
            reason="External entry payloads use absolute offsets that must remain valid.",
            evidence_ids=(BIGTIFF_ENTRY_EVIDENCE_ID,),
        ),
    )


def invalid_header(
    raw_header: bytes,
    marker: bytes,
    endian: BigTiffEndian | None,
    magic: int | None,
    offset_size: int | None,
    reserved_word: int | None,
    reason: BigTiffGateCode,
    message: str,
) -> tuple[BigTiffHeaderPlan, tuple[BigTiffGate, ...]]:
    first_ifd_offset = read_u64(raw_header, 8, endian) if endian is not None else None
    header = BigTiffHeaderPlan(
        raw_header=raw_header,
        byte_order_marker=marker,
        endian=endian,
        magic=magic,
        offset_size=offset_size,
        reserved_word=reserved_word,
        first_ifd_offset=first_ifd_offset,
        is_valid=False,
        reason=reason,
        evidence_ids=(BIGTIFF_HEADER_EVIDENCE_ID,),
    )
    return header, (gate(reason, message, (BIGTIFF_HEADER_EVIDENCE_ID,)),)


def empty_directory(
    name: str,
    parent_name: str,
    start_offset: int,
    route: BigTiffDirectoryRoute,
    gates: tuple[BigTiffGate, ...],
) -> BigTiffDirectoryPlan:
    return BigTiffDirectoryPlan(
        name=name,
        route=route,
        parent_name=parent_name,
        start_offset=start_offset,
        entry_count=None,
        count_range=None,
        entries_range=None,
        next_ifd_pointer_range=None,
        next_ifd_offset=None,
        entries=(),
        gates=gates,
        evidence_ids=(BIGTIFF_DIRECTORY_EVIDENCE_ID,),
    )


def next_ifd_name(name: str) -> str:
    if name.startswith("SubIFD"):
        suffix = name.removeprefix("SubIFD")
        number = int(suffix) if suffix else 0
        return f"SubIFD{number + 1}"
    if name.startswith("IFD"):
        suffix = name.removeprefix("IFD")
        number = int(suffix) if suffix else 0
        return f"IFD{number + 1}"
    return f"{name}Next"


def endian_from_marker(marker: bytes) -> BigTiffEndian | None:
    if marker == b"MM":
        return "big"
    if marker == b"II":
        return "little"
    return None


def byte_order(endian: BigTiffEndian) -> Literal["big", "little"]:
    return endian


def read_u16(data: bytes, offset: int, endian: BigTiffEndian) -> int:
    return int.from_bytes(data[offset : offset + 2], byte_order(endian))


def read_u32(data: bytes, offset: int, endian: BigTiffEndian) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order(endian))


def read_u64(data: bytes, offset: int, endian: BigTiffEndian) -> int:
    return int.from_bytes(data[offset : offset + 8], byte_order(endian))


def gate(
    code: BigTiffGateCode,
    reason: str,
    evidence_ids: tuple[str, ...],
) -> BigTiffGate:
    return BigTiffGate(code=code, reason=reason, evidence_ids=evidence_ids)


def tag_id_hex(tag_id: int) -> str:
    return f"0x{tag_id:04x}"


def json_range(byte_range: tuple[int, int] | None) -> JsonArray | None:
    if byte_range is None:
        return None
    return [byte_range[0], byte_range[1]]


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return list(values)


def json_tiff_value(value: TiffValue) -> str | int | JsonArray | None:
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list):
        return [json_tiff_list_item(item) for item in value]
    return value


def json_tiff_list_item(value: int | Fraction | None) -> str | int | None:
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    return value


def evidence_ids_to_json(references: Iterable[str]) -> JsonArray:
    return list(references)


plan_bigtiff_metadata_transaction = build_bigtiff_metadata_transaction_plan
