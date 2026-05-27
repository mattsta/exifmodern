"""Source-backed, non-mutating PNG chunk transaction plans.

The planner mirrors the PNG write decisions in ExifTool's ``PNG.pm`` and
``WritePNG.pl`` without mutating files.  It validates the PNG signature,
enumerates chunks and CRCs, routes text/XMP/EXIF metadata chunks, preserves
unknown chunks and trailers, and keeps byte emission behind explicit gates.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

type PngEvidenceId = str

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_CHUNK_HEADER_SIZE = 8
PNG_CRC_SIZE = 4
PNG_MAX_EXIFTOOL_CHUNK_LENGTH = 0x7FFFFFFF

IHDR_CHUNK_TYPE = b"IHDR"
IDAT_CHUNK_TYPE = b"IDAT"
IEND_CHUNK_TYPE = b"IEND"
TEXT_CHUNK_TYPES = frozenset((b"tEXt", b"zTXt", b"iTXt"))
EXIF_CHUNK_TYPES = frozenset((b"eXIf", b"zXIf"))
ICC_CHUNK_TYPE = b"iCCP"
PHYS_CHUNK_TYPE = b"pHYs"
SRGB_CHUNK_TYPE = b"sRGB"
PLTE_CHUNK_TYPE = b"PLTE"
MOVABLE_TEXT_CHUNK_TYPES = frozenset((*TEXT_CHUNK_TYPES, b"eXIf"))
DATA_CHUNK_TYPES = frozenset((b"IDAT", b"JDAT", b"JDAA"))
NO_LEAPFROG_CHUNK_TYPES = frozenset(
    (
        b"SAVE",
        b"SEEK",
        b"IHDR",
        b"JHDR",
        b"IEND",
        b"MEND",
        b"DHDR",
        b"BASI",
        b"CLON",
        b"PAST",
        b"SHOW",
        b"MAGN",
    )
)
XMP_ITXT_KEYWORD = "XML:com.adobe.xmp"
OBSOLETE_XMP_CHUNK_TYPE = b"tXMP"
EXIF_APP1_PREFIX = b"Exif\0\0"
PNG_XMP_APP1_PREFIX = b"http://ns.adobe.com/xap/1.0/\0"

type PngPlanStatus = Literal["planned", "unsupported"]
type PngCopyTextRequestStatus = Literal["planned", "blocked"]
type PngCopyTextRequestSourceKind = Literal[
    "jpeg_app1_xmp",
    "jpeg_app13_photoshop_iptc",
]
type PngCopyTextRequestIssueCode = Literal[
    "unsupported_jpeg_app1_xmp_payload",
    "unsupported_jpeg_app13_photoshop_payload",
    "malformed_photoshop_resource_payload",
    "missing_photoshop_iptc_resource",
    "unsupported_iptc_payload",
    "unsupported_xmp_payload",
]
type PngRawProfileConstructionStatus = Literal["planned", "blocked"]
type PngRawProfileConstructionIssueCode = Literal[
    "unsupported_raw_profile_keyword",
    "unsupported_raw_profile_construction",
    "unsupported_raw_profile_reserialization",
    "malformed_raw_profile_source",
    "unsupported_app1_payload",
    "unsupported_exif_payload",
    "unsupported_iptc_payload",
    "unsupported_xmp_payload",
]
type PngMetadataKind = Literal["text", "xmp", "exif", "icc", "physical_pixel", "unknown"]
type PngPixelUnits = Literal[0, 1]
type PngTextCharset = Literal["Latin", "UTF8"]
type PngTextRoute = Literal["tEXt", "zTXt", "iTXt"]
type PngTextualStorageFamily = Literal[
    "textual_keyword",
    "standard_xmp_keyword",
    "raw_profile_keyword",
    "png_exif_chunk",
    "icc_profile_chunk",
]
type PngTextualKeywordSource = Literal[
    "textual_data_source_index",
    "textual_data_database_plan",
    "arbitrary_textual_keyword",
    "png_chunk_table",
]
type PngChunkActionKind = Literal[
    "copy",
    "move_before_idat",
    "delete_metadata",
    "replace_metadata",
    "insert_text",
    "insert_xmp",
    "insert_exif",
    "insert_icc",
    "insert_physical_pixel",
    "preserve_trailer",
    "recompute_crc",
]
type PngEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_png_signature",
    "unsupported_png_signature",
    "truncated_png_chunk_header",
    "truncated_png_chunk_payload",
    "invalid_png_chunk_size",
    "missing_ihdr",
    "ihdr_not_first",
    "missing_iend",
    "chunk_after_iend_requires_trailer_preservation",
    "bad_crc",
    "text_after_idat_cannot_move_across_no_leapfrog",
    "planned_chunk_too_large",
]

PNG_SIGNATURE_SOURCE: PngEvidenceId = "png.png_signature"
PNG_PROCESS_SIGNATURE_SOURCE: PngEvidenceId = "png.png_process_signature"
PNG_CHUNK_ENUMERATION_SOURCE: PngEvidenceId = "png.png_chunk_enumeration"
PNG_HEADER_ORDER_SOURCE: PngEvidenceId = "png.png_header_order"
PNG_IEND_TRAILER_SOURCE: PngEvidenceId = "png.png_iend_trailer"
PNG_CRC_SOURCE: PngEvidenceId = "png.png_crc"
PNG_WRITE_CRC_VALIDATION_SOURCE: PngEvidenceId = "png.png_write_crc_validation"
PNG_TEXT_ROUTING_SOURCE: PngEvidenceId = "png.png_text_routing"
PNG_TEXT_TABLE_SOURCE: PngEvidenceId = "png.png_text_table"
PNG_TEXT_TAG_DELETE_SOURCE: PngEvidenceId = "png.png_text_tag_delete"
PNG_XMP_SOURCE: PngEvidenceId = "png.png_xmp"
PNG_EXIF_SOURCE: PngEvidenceId = "png.png_exif"
PNG_ICC_CHUNK_SOURCE: PngEvidenceId = "png.png_icc_chunk"
PNG_ICC_WRITE_SOURCE: PngEvidenceId = "png.png_icc_write"
PNG_ADD_ICCP_SOURCE: PngEvidenceId = "png.png_add_iccp"
PNG_SRGB_ICC_SOURCE: PngEvidenceId = "png.png_srgb_icc"
PNG_DIRECTORY_ROUTING_SOURCE: PngEvidenceId = "png.png_directory_routing"
PNG_PHYS_CHUNK_SOURCE: PngEvidenceId = "png.png_phys_chunk"
PNG_PHYS_TABLE_SOURCE: PngEvidenceId = "png.png_phys_table"
PNG_PHYS_WRITE_SOURCE: PngEvidenceId = "png.png_phys_write"
PNG_TEXTUAL_GROUP_DELETE_SOURCE: PngEvidenceId = "png.png_textual_group_delete"
PNG_RAW_PROFILE_SOURCE: PngEvidenceId = "png.png_raw_profile"
PNG_RAW_PROFILE_DELETE_SOURCE: PngEvidenceId = "png.png_raw_profile_delete"
PNG_RAW_PROFILE_RESERIALIZE_SOURCE: PngEvidenceId = "png.png_raw_profile_reserialize"
PNG_RAW_PROFILE_WRITE_PROFILE_SOURCE: PngEvidenceId = "png.png_raw_profile_write_profile"
PNG_RAW_PROFILE_HEX_SOURCE: PngEvidenceId = "png.png_raw_profile_hex"
PNG_RAW_PROFILE_IPTC_DIRECT_SOURCE: PngEvidenceId = "png.png_raw_profile_iptc_direct"
JPEG_XMP_APP1_SOURCE: PngEvidenceId = "png.jpeg_xmp_app1"
JPEG_APP13_PHOTOSHOP_SOURCE: PngEvidenceId = "png.jpeg_app13_photoshop"
PHOTOSHOP_IPTC_RESOURCE_SOURCE: PngEvidenceId = "png.photoshop_iptc_resource"
PHOTOSHOP_RESOURCE_SCAN_SOURCE: PngEvidenceId = "png.photoshop_resource_scan"
IPTC_PROCESS_DATASET_SOURCE: PngEvidenceId = "png.iptc_process_dataset"
PNG_ADDCHUNKS_ORDER_SOURCE: PngEvidenceId = "png.png_addchunks_order"
PNG_MOVE_TEXT_SOURCE: PngEvidenceId = "png.png_move_text"
PNG_AFTER_IDAT_WARNING_SOURCE: PngEvidenceId = "png.png_after_idat_warning"
WRITER_PROTECTED_TAG_SOURCE: PngEvidenceId = "png.writer_protected_tag"
WRITER_DELETE_GROUP_VERBOSE_SOURCE: PngEvidenceId = "png.writer_delete_group_verbose"
WRITER_WRITE_AFTER_DELETE_SOURCE: PngEvidenceId = "png.writer_write_after_delete"
WRITER_EDIT_CREATE_DIRS_SOURCE: PngEvidenceId = "png.writer_edit_create_dirs"
XMP_TOOLKIT_PROTECTED_SOURCE: PngEvidenceId = "png.xmp_toolkit_protected"


@dataclass(frozen=True)
class PngTextChunkRequest:
    keyword: str
    value: bytes
    language_code: str = ""
    force_itxt: bool = False
    compress: bool = False
    charset: PngTextCharset = "UTF8"


@dataclass(frozen=True)
class PngCopyTextRequestIssue:
    code: PngCopyTextRequestIssueCode
    reason: str
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PngCopyTextRequestPlan:
    status: PngCopyTextRequestStatus
    source_kind: PngCopyTextRequestSourceKind
    text_request: PngTextChunkRequest | None
    payload_length: int
    issues: tuple[PngCopyTextRequestIssue, ...]
    evidence_ids: tuple[PngEvidenceId, ...]

    @property
    def can_emit_text_request(self) -> bool:
        return self.status == "planned" and self.text_request is not None and not self.issues

    def to_json(self) -> JsonObject:
        return {
            "can_emit_text_request": self.can_emit_text_request,
            "issues": json_object_array(issue.to_json() for issue in self.issues),
            "payload_length": self.payload_length,
            "source_kind": self.source_kind,
            "status": self.status,
            "text_request_keyword": None
            if self.text_request is None
            else self.text_request.keyword,
        }


@dataclass(frozen=True)
class PngPhysicalPixelRequest:
    pixels_per_unit_x: int | None = None
    pixels_per_unit_y: int | None = None
    pixel_units: PngPixelUnits | None = None

    def resolved_pixels_per_unit_x(self) -> int:
        return 2834 if self.pixels_per_unit_x is None else self.pixels_per_unit_x

    def resolved_pixels_per_unit_y(self) -> int:
        return 2834 if self.pixels_per_unit_y is None else self.pixels_per_unit_y

    def resolved_pixel_units(self) -> PngPixelUnits:
        return 1 if self.pixel_units is None else self.pixel_units


@dataclass(frozen=True)
class PngRawProfileConstructionIssue:
    code: PngRawProfileConstructionIssueCode
    reason: str
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PngRawProfileConstructionPlan:
    status: PngRawProfileConstructionStatus
    keyword: str
    profile_type: str | None
    payload_length: int
    text_request: PngTextChunkRequest | None
    issues: tuple[PngRawProfileConstructionIssue, ...]
    evidence_ids: tuple[PngEvidenceId, ...]

    @property
    def can_emit_text_request(self) -> bool:
        return self.status == "planned" and self.text_request is not None and not self.issues

    def to_json(self) -> JsonObject:
        return {
            "can_emit_text_request": self.can_emit_text_request,
            "issues": json_object_array(issue.to_json() for issue in self.issues),
            "keyword": self.keyword,
            "payload_length": self.payload_length,
            "profile_type": self.profile_type,
            "status": self.status,
        }


@dataclass(frozen=True)
class _DecodedRawProfileSource:
    profile_type: str
    declared_length: int
    payload: bytes


@dataclass(frozen=True)
class PngSignaturePlan:
    signature: bytes
    file_type: str | None
    header_chunk_type: bytes | None
    end_chunk_type: bytes | None
    is_supported_png: bool
    reason: PngEmissionGateCode | None
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "end_chunk_type": ascii_chunk_id(self.end_chunk_type),
            "file_type": self.file_type,
            "header_chunk_type": ascii_chunk_id(self.header_chunk_type),
            "is_supported_png": self.is_supported_png,
            "reason": self.reason,
            "signature": self.signature.hex(),
        }


@dataclass(frozen=True)
class PngChunkPlan:
    index: int
    chunk_type: bytes
    chunk_start_offset: int
    payload_offset: int
    payload_length: int
    crc_offset: int
    end_offset: int
    payload: bytes
    stored_crc: int
    calculated_crc: int
    crc_matches: bool
    after_idat: bool
    after_iend: bool
    evidence_ids: tuple[PngEvidenceId, ...]

    @property
    def encoded_length(self) -> int:
        return PNG_CHUNK_HEADER_SIZE + self.payload_length + PNG_CRC_SIZE

    def to_output_chunk(self) -> PngOutputChunk:
        return PngOutputChunk(self.chunk_type, self.payload)

    def to_json(self) -> JsonObject:
        return {
            "after_idat": self.after_idat,
            "after_iend": self.after_iend,
            "calculated_crc": self.calculated_crc,
            "chunk_start_offset": self.chunk_start_offset,
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "crc_matches": self.crc_matches,
            "crc_offset": self.crc_offset,
            "encoded_length": self.encoded_length,
            "end_offset": self.end_offset,
            "index": self.index,
            "payload_length": self.payload_length,
            "payload_offset": self.payload_offset,
            "stored_crc": self.stored_crc,
        }


@dataclass(frozen=True)
class PngMetadataRoutingPlan:
    chunk_index: int | None
    chunk_type: bytes
    metadata_kind: PngMetadataKind
    keyword: str | None
    text_route: PngTextRoute | None
    textual_keyword_source: PngTextualKeywordSource | None
    textual_tag_name: str | None
    textual_storage_family: PngTextualStorageFamily | None
    textual_registered: bool | None
    textual_subdirectory: str | None
    textual_non_standard: str | None
    textual_duplicate_variant_indexes: tuple[int, ...]
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_index": self.chunk_index,
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "keyword": self.keyword,
            "metadata_kind": self.metadata_kind,
            "textual_duplicate_variant_indexes": list(self.textual_duplicate_variant_indexes),
            "textual_keyword_source": self.textual_keyword_source,
            "textual_non_standard": self.textual_non_standard,
            "textual_registered": self.textual_registered,
            "textual_storage_family": self.textual_storage_family,
            "textual_subdirectory": self.textual_subdirectory,
            "textual_tag_name": self.textual_tag_name,
            "text_route": self.text_route,
        }


@dataclass(frozen=True)
class PngTextualRouteFacts:
    keyword_source: PngTextualKeywordSource
    tag_name: str | None
    storage_family: PngTextualStorageFamily | None
    registered: bool | None
    subdirectory: str | None
    non_standard: str | None
    duplicate_variant_indexes: tuple[int, ...]
    evidence_ids: tuple[PngEvidenceId, ...]


@dataclass(frozen=True)
class PngOutputChunk:
    chunk_type: bytes
    payload: bytes


@dataclass(frozen=True)
class PngChunkActionPlan:
    kind: PngChunkActionKind
    chunk_type: bytes
    source_index: int | None
    output_index: int | None
    payload_length: int
    reason: str
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "kind": self.kind,
            "output_index": self.output_index,
            "payload_length": self.payload_length,
            "reason": self.reason,
            "source_index": self.source_index,
        }


@dataclass(frozen=True)
class PngOutputEmissionGate:
    code: PngEmissionGateCode
    reason: str
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PngOutputSizePlan:
    input_file_size: int
    planned_file_size: int | None
    trailer_size: int
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "input_file_size": self.input_file_size,
            "planned_file_size": self.planned_file_size,
            "trailer_size": self.trailer_size,
        }


@dataclass(frozen=True)
class PngChunkTransactionPlan:
    status: PngPlanStatus
    signature: PngSignaturePlan
    chunks: tuple[PngChunkPlan, ...]
    metadata_routes: tuple[PngMetadataRoutingPlan, ...]
    actions: tuple[PngChunkActionPlan, ...]
    output_chunks: tuple[PngOutputChunk, ...]
    output_size: PngOutputSizePlan
    output_emission_gates: tuple[PngOutputEmissionGate, ...]
    trailer: bytes
    evidence_ids: tuple[PngEvidenceId, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"PNG chunk transaction output is gated: {gate_codes}")
        return encode_png_chunks(self.output_chunks, trailer=self.trailer)

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "chunks": json_object_array(chunk.to_json() for chunk in self.chunks),
            "metadata_routes": json_object_array(route.to_json() for route in self.metadata_routes),
            "output_chunk_types": [
                ascii_chunk_id(chunk.chunk_type) for chunk in self.output_chunks
            ],
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "output_size": self.output_size.to_json(),
            "signature": self.signature.to_json(),
            "status": self.status,
            "trailer_size": len(self.trailer),
        }


def build_png_chunk_transaction_plan(
    png_data: bytes,
    *,
    icc_payload: bytes | None = None,
    icc_profile_name: str | None = None,
    exif_payload: bytes | None = None,
    xmp_payload: bytes | None = None,
    physical_pixel: PngPhysicalPixelRequest | None = None,
    text_chunks: Iterable[PngTextChunkRequest] = (),
    delete_text_keywords: Iterable[str] = (),
    delete_metadata_groups: Iterable[str] = (),
    delete_all_metadata: bool = False,
    allow_output_emission: bool = False,
    validate_crc: bool = True,
) -> PngChunkTransactionPlan:
    """Build a non-mutating PNG chunk transaction plan."""

    signature = build_png_signature_plan(png_data)
    gates: list[PngOutputEmissionGate] = []
    if signature.reason is not None:
        gates.append(
            PngOutputEmissionGate(
                code=signature.reason,
                reason="Input does not satisfy the PNG signature gate.",
                evidence_ids=(PNG_SIGNATURE_SOURCE, PNG_PROCESS_SIGNATURE_SOURCE),
            )
        )
        return _unsupported_plan(signature, png_data, gates)

    chunks, trailer, parse_gates = enumerate_png_chunks(png_data)
    gates.extend(parse_gates)
    if not parse_gates:
        gates.extend(_structural_gates(chunks))
    if validate_crc and not parse_gates:
        gates.extend(_crc_gates(chunks))

    routes = tuple(_route_existing_chunk(chunk) for chunk in chunks)
    requested_text = tuple(text_chunks)
    requested_delete_text_keywords = frozenset(delete_text_keywords)
    requested_delete_groups = _normalize_delete_groups(delete_metadata_groups)
    requested_routes = tuple(_route_text_request(request) for request in requested_text)
    if physical_pixel is not None:
        requested_routes = (*requested_routes, _route_physical_pixel_request())
    routes = (*routes, *requested_routes)

    output_chunks, actions, planning_gates = _plan_output_chunks(
        chunks,
        requested_text,
        icc_payload=icc_payload,
        icc_profile_name=icc_profile_name,
        exif_payload=exif_payload,
        xmp_payload=xmp_payload,
        physical_pixel=physical_pixel,
        delete_text_keywords=requested_delete_text_keywords,
        delete_metadata_groups=requested_delete_groups,
        delete_all_metadata=delete_all_metadata,
    )
    gates.extend(planning_gates)

    if trailer:
        actions = (
            *actions,
            PngChunkActionPlan(
                kind="preserve_trailer",
                chunk_type=b"TRLR",
                source_index=None,
                output_index=None,
                payload_length=len(trailer),
                reason=(
                    "Preserve existing bytes after IEND unless a trailer delete is "
                    "explicitly planned."
                ),
                evidence_ids=(PNG_IEND_TRAILER_SOURCE,),
            ),
        )

    for output_index, output_chunk in enumerate(output_chunks):
        actions = (
            *actions,
            PngChunkActionPlan(
                kind="recompute_crc",
                chunk_type=output_chunk.chunk_type,
                source_index=None,
                output_index=output_index,
                payload_length=len(output_chunk.payload),
                reason="PNG output CRC is calculated over the output chunk type and payload.",
                evidence_ids=(PNG_CRC_SOURCE,),
            ),
        )
        if len(output_chunk.payload) > PNG_MAX_EXIFTOOL_CHUNK_LENGTH:
            gates.append(
                PngOutputEmissionGate(
                    code="planned_chunk_too_large",
                    reason=(
                        f"Planned {ascii_chunk_id(output_chunk.chunk_type)} chunk "
                        "exceeds ExifTool's chunk length gate."
                    ),
                    evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )

    if not allow_output_emission:
        gates.append(
            PngOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason=(
                    "PNG transaction plans are non-mutating unless emission is explicitly allowed."
                ),
                evidence_ids=(PNG_PROCESS_SIGNATURE_SOURCE,),
            )
        )

    status: PngPlanStatus = "unsupported" if parse_gates else "planned"
    output_size = PngOutputSizePlan(
        input_file_size=len(png_data),
        planned_file_size=len(encode_png_chunks(output_chunks, trailer=trailer))
        if output_chunks
        else None,
        trailer_size=len(trailer),
        evidence_ids=(PNG_IEND_TRAILER_SOURCE, PNG_CRC_SOURCE),
    )
    sources = unique_sources(
        (
            PNG_SIGNATURE_SOURCE,
            PNG_PROCESS_SIGNATURE_SOURCE,
            PNG_CHUNK_ENUMERATION_SOURCE,
            PNG_HEADER_ORDER_SOURCE,
            PNG_IEND_TRAILER_SOURCE,
            PNG_CRC_SOURCE,
            PNG_WRITE_CRC_VALIDATION_SOURCE,
            PNG_TEXT_ROUTING_SOURCE,
            PNG_TEXT_TABLE_SOURCE,
            PNG_TEXT_TAG_DELETE_SOURCE,
            PNG_XMP_SOURCE,
            PNG_EXIF_SOURCE,
            PNG_ICC_CHUNK_SOURCE,
            PNG_ICC_WRITE_SOURCE,
            PNG_ADD_ICCP_SOURCE,
            PNG_SRGB_ICC_SOURCE,
            PNG_PHYS_CHUNK_SOURCE,
            PNG_PHYS_TABLE_SOURCE,
            PNG_PHYS_WRITE_SOURCE,
            PNG_DIRECTORY_ROUTING_SOURCE,
            PNG_TEXTUAL_GROUP_DELETE_SOURCE,
            PNG_RAW_PROFILE_SOURCE,
            PNG_RAW_PROFILE_DELETE_SOURCE,
            PNG_RAW_PROFILE_RESERIALIZE_SOURCE,
            PNG_RAW_PROFILE_WRITE_PROFILE_SOURCE,
            PNG_RAW_PROFILE_HEX_SOURCE,
            PNG_RAW_PROFILE_IPTC_DIRECT_SOURCE,
            IPTC_PROCESS_DATASET_SOURCE,
            PNG_ADDCHUNKS_ORDER_SOURCE,
            PNG_MOVE_TEXT_SOURCE,
            PNG_AFTER_IDAT_WARNING_SOURCE,
            *(source for route in routes for source in route.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return PngChunkTransactionPlan(
        status=status,
        signature=signature,
        chunks=chunks,
        metadata_routes=routes,
        actions=actions,
        output_chunks=output_chunks,
        output_size=output_size,
        output_emission_gates=unique_gates(tuple(gates)),
        trailer=trailer,
        evidence_ids=sources,
    )


plan_png_chunk_transaction = build_png_chunk_transaction_plan


def build_png_signature_plan(png_data: bytes) -> PngSignaturePlan:
    if len(png_data) < len(PNG_SIGNATURE):
        return PngSignaturePlan(
            signature=png_data,
            file_type=None,
            header_chunk_type=None,
            end_chunk_type=None,
            is_supported_png=False,
            reason="truncated_png_signature",
            evidence_ids=(PNG_SIGNATURE_SOURCE, PNG_PROCESS_SIGNATURE_SOURCE),
        )
    signature = png_data[: len(PNG_SIGNATURE)]
    if signature != PNG_SIGNATURE:
        return PngSignaturePlan(
            signature=signature,
            file_type=None,
            header_chunk_type=None,
            end_chunk_type=None,
            is_supported_png=False,
            reason="unsupported_png_signature",
            evidence_ids=(PNG_SIGNATURE_SOURCE, PNG_PROCESS_SIGNATURE_SOURCE),
        )
    return PngSignaturePlan(
        signature=signature,
        file_type="PNG",
        header_chunk_type=IHDR_CHUNK_TYPE,
        end_chunk_type=IEND_CHUNK_TYPE,
        is_supported_png=True,
        reason=None,
        evidence_ids=(PNG_SIGNATURE_SOURCE, PNG_PROCESS_SIGNATURE_SOURCE),
    )


def enumerate_png_chunks(
    png_data: bytes,
) -> tuple[tuple[PngChunkPlan, ...], bytes, tuple[PngOutputEmissionGate, ...]]:
    chunks: list[PngChunkPlan] = []
    gates: list[PngOutputEmissionGate] = []
    offset = len(PNG_SIGNATURE)
    was_idat = False
    while offset < len(png_data):
        if len(png_data) - offset < PNG_CHUNK_HEADER_SIZE:
            gates.append(
                PngOutputEmissionGate(
                    code="truncated_png_chunk_header",
                    reason="Input ended before a complete PNG chunk header could be read.",
                    evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(chunks), b"", tuple(gates)

        chunk_start = offset
        payload_length = int.from_bytes(png_data[offset : offset + 4], "big")
        chunk_type = png_data[offset + 4 : offset + 8]
        offset += PNG_CHUNK_HEADER_SIZE
        if payload_length > PNG_MAX_EXIFTOOL_CHUNK_LENGTH:
            gates.append(
                PngOutputEmissionGate(
                    code="invalid_png_chunk_size",
                    reason=(
                        f"{ascii_chunk_id(chunk_type)} declares a chunk length larger "
                        "than ExifTool accepts."
                    ),
                    evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(chunks), b"", tuple(gates)

        payload_end = offset + payload_length
        crc_end = payload_end + PNG_CRC_SIZE
        if crc_end > len(png_data):
            gates.append(
                PngOutputEmissionGate(
                    code="truncated_png_chunk_payload",
                    reason=f"{ascii_chunk_id(chunk_type)} payload or CRC is truncated.",
                    evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(chunks), b"", tuple(gates)

        payload = png_data[offset:payload_end]
        stored_crc = int.from_bytes(png_data[payload_end:crc_end], "big")
        calculated_crc = png_crc(chunk_type, payload)
        chunk = PngChunkPlan(
            index=len(chunks),
            chunk_type=chunk_type,
            chunk_start_offset=chunk_start,
            payload_offset=offset,
            payload_length=payload_length,
            crc_offset=payload_end,
            end_offset=crc_end,
            payload=payload,
            stored_crc=stored_crc,
            calculated_crc=calculated_crc,
            crc_matches=stored_crc == calculated_crc,
            after_idat=was_idat and chunk_type not in DATA_CHUNK_TYPES,
            after_iend=False,
            evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE, PNG_CRC_SOURCE),
        )
        chunks.append(chunk)
        offset = crc_end
        if chunk_type in DATA_CHUNK_TYPES:
            was_idat = True
        if chunk_type == IEND_CHUNK_TYPE:
            return tuple(chunks), png_data[offset:], tuple(gates)
    return tuple(chunks), b"", tuple(gates)


def encode_png_chunks(chunks: Iterable[PngOutputChunk], *, trailer: bytes = b"") -> bytes:
    encoded = bytearray(PNG_SIGNATURE)
    for chunk in chunks:
        encoded.extend(len(chunk.payload).to_bytes(4, "big"))
        encoded.extend(chunk.chunk_type)
        encoded.extend(chunk.payload)
        encoded.extend(png_crc(chunk.chunk_type, chunk.payload).to_bytes(4, "big"))
    encoded.extend(trailer)
    return bytes(encoded)


def png_crc(chunk_type: bytes, payload: bytes) -> int:
    return zlib.crc32(chunk_type + payload) & 0xFFFFFFFF


def build_text_chunk_payload(request: PngTextChunkRequest) -> tuple[bytes, bytes]:
    route = _route_text_request(request).text_route
    if route == "iTXt":
        value = _itxt_value_bytes(request)
        return (
            b"iTXt",
            request.keyword.encode("latin-1")
            + b"\0\0\0"
            + request.language_code.encode("ascii")
            + b"\0\0"
            + value,
        )
    if route == "zTXt":
        return b"zTXt", request.keyword.encode("latin-1") + b"\0\0" + zlib.compress(request.value)
    return b"tEXt", request.keyword.encode("latin-1") + b"\0" + request.value


def build_png_xmp_copy_text_request_from_jpeg_app1_payload(
    app1_payload: bytes,
) -> PngCopyTextRequestPlan:
    """Lower a JPEG standard XMP APP1 payload to PNG's standard XMP iTXt request."""

    common_sources = (
        JPEG_XMP_APP1_SOURCE,
        PNG_XMP_SOURCE,
        PNG_TEXT_ROUTING_SOURCE,
        PNG_TEXT_TABLE_SOURCE,
    )
    if not app1_payload.startswith(PNG_XMP_APP1_PREFIX):
        return _blocked_copy_text_request(
            source_kind="jpeg_app1_xmp",
            payload_length=len(app1_payload),
            code="unsupported_jpeg_app1_xmp_payload",
            reason=(
                "JPEG-to-PNG XMP copy lowering is limited to standard APP1 XMP "
                "payloads with ExifTool's XMP APP1 namespace prefix."
            ),
            evidence_ids=(JPEG_XMP_APP1_SOURCE,),
        )
    xmp_packet = app1_payload[len(PNG_XMP_APP1_PREFIX) :]
    try:
        from exifmodern.formats.xmp.reader import parse_xmp_packet

        parse_xmp_packet(xmp_packet)
    except (SyntaxError, ValueError) as exc:
        return _blocked_copy_text_request(
            source_kind="jpeg_app1_xmp",
            payload_length=len(app1_payload),
            code="unsupported_xmp_payload",
            reason=f"JPEG APP1 XMP payload could not be parsed by the bounded XMP adapter: {exc}.",
            evidence_ids=(JPEG_XMP_APP1_SOURCE, PNG_XMP_SOURCE),
        )
    return PngCopyTextRequestPlan(
        status="planned",
        source_kind="jpeg_app1_xmp",
        text_request=PngTextChunkRequest(
            keyword=XMP_ITXT_KEYWORD,
            value=xmp_packet,
            charset="UTF8",
        ),
        payload_length=len(xmp_packet),
        issues=(),
        evidence_ids=unique_sources(common_sources),
    )


def build_png_iptc_copy_text_request_from_jpeg_app13_payload(
    app13_payload: bytes,
    *,
    compress: bool = True,
) -> PngCopyTextRequestPlan:
    """Lower JPEG Photoshop APP13 IPTC resources to PNG's raw IPTC profile request."""

    from exifmodern.formats.photoshop.image_resources import (
        PhotoshopImageResourceError,
        parse_image_resource_blocks,
    )
    from exifmodern.formats.photoshop.nested_metadata_plan import (
        PHOTOSHOP_RESOURCE_ID_IPTC_DATA,
    )

    resource_section = _jpeg_app13_photoshop_resource_section(app13_payload)
    if resource_section is None:
        return _blocked_copy_text_request(
            source_kind="jpeg_app13_photoshop_iptc",
            payload_length=len(app13_payload),
            code="unsupported_jpeg_app13_photoshop_payload",
            reason=(
                "JPEG-to-PNG IPTC copy lowering is limited to ExifTool's Photoshop "
                "APP13 payload prefixes."
            ),
            evidence_ids=(JPEG_APP13_PHOTOSHOP_SOURCE,),
        )
    try:
        blocks = parse_image_resource_blocks(resource_section)
    except PhotoshopImageResourceError as exc:
        return _blocked_copy_text_request(
            source_kind="jpeg_app13_photoshop_iptc",
            payload_length=len(app13_payload),
            code="malformed_photoshop_resource_payload",
            reason=f"JPEG APP13 Photoshop resource payload could not be parsed: {exc}.",
            evidence_ids=(JPEG_APP13_PHOTOSHOP_SOURCE, PHOTOSHOP_RESOURCE_SCAN_SOURCE),
        )
    iptc_payload = next(
        (block.data for block in blocks if block.resource_id == PHOTOSHOP_RESOURCE_ID_IPTC_DATA),
        None,
    )
    if iptc_payload is None:
        return _blocked_copy_text_request(
            source_kind="jpeg_app13_photoshop_iptc",
            payload_length=len(app13_payload),
            code="missing_photoshop_iptc_resource",
            reason="JPEG APP13 Photoshop payload contains no IPTCData resource 0x0404.",
            evidence_ids=(
                JPEG_APP13_PHOTOSHOP_SOURCE,
                PHOTOSHOP_IPTC_RESOURCE_SOURCE,
                PHOTOSHOP_RESOURCE_SCAN_SOURCE,
            ),
        )
    if not _is_direct_iptc_iim_payload(iptc_payload):
        return _blocked_copy_text_request(
            source_kind="jpeg_app13_photoshop_iptc",
            payload_length=len(app13_payload),
            code="unsupported_iptc_payload",
            reason=(
                "JPEG APP13 IPTCData must be direct IPTC IIM bytes that exactly "
                "round-trip through the package-local IPTC dataset parser/encoder."
            ),
            evidence_ids=(
                PHOTOSHOP_IPTC_RESOURCE_SOURCE,
                IPTC_PROCESS_DATASET_SOURCE,
            ),
        )
    text_request = PngTextChunkRequest(
        keyword="Raw profile type iptc",
        value=encode_raw_profile_container("IPTC profile", resource_section),
        compress=compress,
    )
    return PngCopyTextRequestPlan(
        status="planned",
        source_kind="jpeg_app13_photoshop_iptc",
        text_request=text_request,
        payload_length=len(resource_section),
        issues=(),
        evidence_ids=unique_sources(
            (
                JPEG_APP13_PHOTOSHOP_SOURCE,
                PHOTOSHOP_RESOURCE_SCAN_SOURCE,
                PHOTOSHOP_IPTC_RESOURCE_SOURCE,
                PNG_RAW_PROFILE_SOURCE,
                PNG_RAW_PROFILE_WRITE_PROFILE_SOURCE,
                PNG_RAW_PROFILE_HEX_SOURCE,
                IPTC_PROCESS_DATASET_SOURCE,
                PNG_TEXT_ROUTING_SOURCE,
                PNG_TEXT_TABLE_SOURCE,
            )
        ),
    )


def build_raw_profile_text_request_plan(
    keyword: str,
    payload: bytes,
    *,
    compress: bool = True,
) -> PngRawProfileConstructionPlan:
    """Build a source-backed PNG raw-profile textual request when bounded."""

    profile_type = _raw_profile_write_profile_type(keyword)
    common_sources = (
        PNG_RAW_PROFILE_SOURCE,
        PNG_RAW_PROFILE_RESERIALIZE_SOURCE,
        PNG_RAW_PROFILE_WRITE_PROFILE_SOURCE,
        PNG_RAW_PROFILE_HEX_SOURCE,
        PNG_RAW_PROFILE_IPTC_DIRECT_SOURCE,
        IPTC_PROCESS_DATASET_SOURCE,
        PNG_TEXT_TABLE_SOURCE,
        PNG_TEXT_ROUTING_SOURCE,
    )
    if profile_type is None:
        return _blocked_raw_profile_construction(
            keyword=keyword,
            profile_type=None,
            payload_length=len(payload),
            code="unsupported_raw_profile_keyword",
            reason=f"{keyword} is not a source-enumerated PNG raw-profile keyword.",
            evidence_ids=(PNG_RAW_PROFILE_SOURCE,),
        )
    if keyword == "Raw profile type 8bim":
        return _blocked_raw_profile_construction(
            keyword=keyword,
            profile_type=profile_type,
            payload_length=len(payload),
            code="unsupported_raw_profile_construction",
            reason=(
                "ExifTool routes this raw profile through Photoshop IRB writers; "
                "this helper does not construct Photoshop IRB bytes without a "
                "bounded nested Photoshop writer."
            ),
            evidence_ids=(
                PNG_RAW_PROFILE_SOURCE,
                PNG_RAW_PROFILE_RESERIALIZE_SOURCE,
                PNG_RAW_PROFILE_WRITE_PROFILE_SOURCE,
                PNG_RAW_PROFILE_DELETE_SOURCE,
            ),
        )
    if keyword == "Raw profile type iptc" and not _is_direct_iptc_iim_payload(payload):
        return _blocked_raw_profile_construction(
            keyword=keyword,
            profile_type=profile_type,
            payload_length=len(payload),
            code="unsupported_iptc_payload",
            reason=(
                "IPTC raw-profile construction is limited to direct IPTC IIM bytes "
                "that exactly round-trip through the package-local IPTC dataset "
                "parser/encoder. Photoshop IRB IPTC construction remains blocked."
            ),
            evidence_ids=(
                PNG_RAW_PROFILE_SOURCE,
                PNG_RAW_PROFILE_IPTC_DIRECT_SOURCE,
                IPTC_PROCESS_DATASET_SOURCE,
            ),
        )
    if keyword == "Raw profile type APP1" and not _is_app1_raw_profile_payload(payload):
        return _blocked_raw_profile_construction(
            keyword=keyword,
            profile_type=profile_type,
            payload_length=len(payload),
            code="unsupported_app1_payload",
            reason=(
                "APP1 raw-profile construction is limited to copy-backed APP1 EXIF "
                "or APP1 XMP payloads that already include ExifTool's APP1 headers."
            ),
            evidence_ids=(PNG_RAW_PROFILE_SOURCE, PNG_RAW_PROFILE_DELETE_SOURCE),
        )
    if keyword == "Raw profile type exif" and not _is_exif_raw_profile_payload(payload):
        return _blocked_raw_profile_construction(
            keyword=keyword,
            profile_type=profile_type,
            payload_length=len(payload),
            code="unsupported_exif_payload",
            reason=(
                "EXIF raw-profile construction is limited to copy-backed APP1 EXIF "
                "or bare TIFF payloads matching ProcessProfile's EXIF/TIFF branches."
            ),
            evidence_ids=(PNG_RAW_PROFILE_SOURCE, PNG_RAW_PROFILE_DELETE_SOURCE),
        )

    text_request = PngTextChunkRequest(
        keyword=keyword,
        value=encode_raw_profile_container(profile_type, payload),
        compress=compress,
    )
    return PngRawProfileConstructionPlan(
        status="planned",
        keyword=keyword,
        profile_type=profile_type,
        payload_length=len(payload),
        text_request=text_request,
        issues=(),
        evidence_ids=unique_sources(common_sources),
    )


def build_source_backed_raw_profile_reserialize_plan(
    keyword: str,
    source_raw_profile_payload: bytes,
    rewritten_payload: bytes,
    *,
    compress: bool = True,
) -> PngRawProfileConstructionPlan:
    """Rewrap changed nested raw-profile bytes using ProcessProfile's source header."""

    profile_type = _raw_profile_write_profile_type(keyword)
    common_sources = (
        PNG_RAW_PROFILE_SOURCE,
        PNG_RAW_PROFILE_RESERIALIZE_SOURCE,
        PNG_RAW_PROFILE_HEX_SOURCE,
        PNG_RAW_PROFILE_IPTC_DIRECT_SOURCE,
        IPTC_PROCESS_DATASET_SOURCE,
        PNG_TEXT_TABLE_SOURCE,
        PNG_TEXT_ROUTING_SOURCE,
    )
    if profile_type is None:
        return _blocked_raw_profile_construction(
            keyword=keyword,
            profile_type=None,
            payload_length=len(rewritten_payload),
            code="unsupported_raw_profile_keyword",
            reason=f"{keyword} is not a source-enumerated PNG raw-profile keyword.",
            evidence_ids=(PNG_RAW_PROFILE_SOURCE,),
        )

    decoded = _decode_raw_profile_source(source_raw_profile_payload)
    if decoded is None:
        return _blocked_raw_profile_construction(
            keyword=keyword,
            profile_type=profile_type,
            payload_length=len(rewritten_payload),
            code="malformed_raw_profile_source",
            reason=(
                "Source raw-profile payload does not match ProcessProfile's "
                "newline-delimited profile header and hex body."
            ),
            evidence_ids=(PNG_RAW_PROFILE_SOURCE, PNG_RAW_PROFILE_RESERIALIZE_SOURCE),
        )

    if keyword == "Raw profile type 8bim":
        return _blocked_raw_profile_construction(
            keyword=keyword,
            profile_type=decoded.profile_type,
            payload_length=len(rewritten_payload),
            code="unsupported_raw_profile_reserialization",
            reason=(
                "Source-backed reserialization remains blocked for Photoshop raw "
                "profiles because ProcessProfile writes them through nested "
                "Photoshop directories, not a bounded direct byte wrapper."
            ),
            evidence_ids=(
                PNG_RAW_PROFILE_SOURCE,
                PNG_RAW_PROFILE_RESERIALIZE_SOURCE,
                PNG_RAW_PROFILE_DELETE_SOURCE,
            ),
        )
    if keyword == "Raw profile type iptc":
        if not _is_direct_iptc_iim_payload(decoded.payload):
            return _blocked_raw_profile_construction(
                keyword=keyword,
                profile_type=decoded.profile_type,
                payload_length=len(rewritten_payload),
                code="unsupported_raw_profile_reserialization",
                reason=(
                    "Source IPTC raw profile is not direct IIM bytes that exactly "
                    "round-trip through the package-local IPTC dataset parser/encoder. "
                    "Photoshop IRB IPTC reserialization remains blocked."
                ),
                evidence_ids=(
                    PNG_RAW_PROFILE_SOURCE,
                    PNG_RAW_PROFILE_RESERIALIZE_SOURCE,
                    PNG_RAW_PROFILE_IPTC_DIRECT_SOURCE,
                    IPTC_PROCESS_DATASET_SOURCE,
                ),
            )
        if not _is_direct_iptc_iim_payload(rewritten_payload):
            return _blocked_raw_profile_construction(
                keyword=keyword,
                profile_type=decoded.profile_type,
                payload_length=len(rewritten_payload),
                code="unsupported_iptc_payload",
                reason=(
                    "Rewritten IPTC raw profile must stay in the direct IIM branch "
                    "and exactly round-trip through the package-local IPTC dataset "
                    "parser/encoder."
                ),
                evidence_ids=(
                    PNG_RAW_PROFILE_SOURCE,
                    PNG_RAW_PROFILE_RESERIALIZE_SOURCE,
                    PNG_RAW_PROFILE_IPTC_DIRECT_SOURCE,
                    IPTC_PROCESS_DATASET_SOURCE,
                ),
            )

    validation_issue = _raw_profile_reserialization_validation_issue(
        keyword,
        decoded.payload,
        rewritten_payload,
    )
    if validation_issue is not None:
        code, reason = validation_issue
        return _blocked_raw_profile_construction(
            keyword=keyword,
            profile_type=decoded.profile_type,
            payload_length=len(rewritten_payload),
            code=code,
            reason=reason,
            evidence_ids=(PNG_RAW_PROFILE_SOURCE, PNG_RAW_PROFILE_RESERIALIZE_SOURCE),
        )

    text_request = PngTextChunkRequest(
        keyword=keyword,
        value=encode_raw_profile_container(decoded.profile_type, rewritten_payload),
        compress=compress,
    )
    return PngRawProfileConstructionPlan(
        status="planned",
        keyword=keyword,
        profile_type=decoded.profile_type,
        payload_length=len(rewritten_payload),
        text_request=text_request,
        issues=(),
        evidence_ids=unique_sources(common_sources),
    )


def encode_raw_profile_container(profile_type: str, payload: bytes) -> bytes:
    header = f"\n{profile_type}\n{len(payload):8d}\n".encode("latin-1")
    return header + _hex_encode_raw_profile_payload(payload)


def _hex_encode_raw_profile_payload(payload: bytes) -> bytes:
    encoded = bytearray()
    for offset in range(0, len(payload), 36):
        encoded.extend(payload[offset : offset + 36].hex().encode("ascii"))
        encoded.extend(b"\n")
    return bytes(encoded)


def _raw_profile_write_profile_type(keyword: str) -> str | None:
    if keyword == "Raw profile type APP1":
        return "APP1"
    if keyword == "Raw profile type exif":
        return "exif"
    if keyword == "Raw profile type icc":
        return "ICC Profile"
    if keyword == "Raw profile type icm":
        return "ICM Profile"
    if keyword == "Raw profile type iptc":
        return "IPTC profile"
    if keyword == "Raw profile type xmp":
        return "xmp"
    if keyword == "Raw profile type 8bim":
        return "8bim"
    return None


def _is_app1_raw_profile_payload(payload: bytes) -> bool:
    return payload.startswith(EXIF_APP1_PREFIX) or payload.startswith(PNG_XMP_APP1_PREFIX)


def _is_exif_raw_profile_payload(payload: bytes) -> bool:
    return payload.startswith(EXIF_APP1_PREFIX) or payload.startswith((b"II*\0", b"MM\0*"))


def _is_direct_iptc_iim_payload(payload: bytes) -> bool:
    from exifmodern.formats.iptc.dataset_writer import encode_iptc_dataset, parse_iptc_datasets

    if not payload.startswith(b"\x1c"):
        return False
    datasets = parse_iptc_datasets(payload)
    if not datasets:
        return False
    try:
        reserialized = b"".join(encode_iptc_dataset(dataset) for dataset in datasets)
    except ValueError:
        return False
    return reserialized == payload


def _decode_raw_profile_source(payload: bytes) -> _DecodedRawProfileSource | None:
    if not payload.startswith(b"\n"):
        return None
    parts = payload.split(b"\n", 3)
    if len(parts) != 4:
        return None
    profile_type_bytes = parts[1]
    declared_length_bytes = parts[2].strip()
    if not declared_length_bytes.isdigit():
        return None
    try:
        hex_text = b"".join(parts[3].split())
        decoded_payload = bytes.fromhex(hex_text.decode("ascii"))
    except UnicodeDecodeError, ValueError:
        return None
    return _DecodedRawProfileSource(
        profile_type=profile_type_bytes.decode("latin-1", errors="replace"),
        declared_length=int(declared_length_bytes),
        payload=decoded_payload,
    )


def _raw_profile_reserialization_validation_issue(
    keyword: str,
    source_payload: bytes,
    rewritten_payload: bytes,
) -> tuple[PngRawProfileConstructionIssueCode, str] | None:
    if keyword == "Raw profile type APP1":
        if not _is_app1_raw_profile_payload(source_payload):
            return (
                "unsupported_app1_payload",
                "Source APP1 raw profile did not match ProcessProfile's APP1 EXIF/XMP branches.",
            )
        if not _is_app1_raw_profile_payload(rewritten_payload):
            return (
                "unsupported_app1_payload",
                "Rewritten APP1 raw profile must preserve an APP1 EXIF or APP1 XMP header.",
            )
        source_is_xmp = source_payload.startswith(PNG_XMP_APP1_PREFIX)
        rewritten_is_xmp = rewritten_payload.startswith(PNG_XMP_APP1_PREFIX)
        if source_is_xmp != rewritten_is_xmp:
            return (
                "unsupported_app1_payload",
                "Rewritten APP1 raw profile must stay in the source APP1 EXIF/XMP branch.",
            )
        if rewritten_is_xmp:
            return _validate_xmp_raw_profile_payload(rewritten_payload[len(PNG_XMP_APP1_PREFIX) :])
        return None
    if keyword == "Raw profile type exif" and not _is_exif_raw_profile_payload(rewritten_payload):
        return (
            "unsupported_exif_payload",
            "Rewritten EXIF raw profile must match ProcessProfile's APP1 EXIF or TIFF branches.",
        )
    if keyword == "Raw profile type xmp":
        return _validate_xmp_raw_profile_payload(rewritten_payload)
    return None


def _validate_xmp_raw_profile_payload(
    payload: bytes,
) -> tuple[PngRawProfileConstructionIssueCode, str] | None:
    try:
        from exifmodern.formats.xmp.reader import parse_xmp_packet

        parse_xmp_packet(payload)
    except (SyntaxError, ValueError) as exc:
        return (
            "unsupported_xmp_payload",
            f"Rewritten XMP raw profile could not be parsed by the bounded XMP adapter: {exc}.",
        )
    return None


def _blocked_copy_text_request(
    *,
    source_kind: PngCopyTextRequestSourceKind,
    payload_length: int,
    code: PngCopyTextRequestIssueCode,
    reason: str,
    evidence_ids: tuple[PngEvidenceId, ...],
) -> PngCopyTextRequestPlan:
    issue = PngCopyTextRequestIssue(
        code=code,
        reason=reason,
        evidence_ids=evidence_ids,
    )
    return PngCopyTextRequestPlan(
        status="blocked",
        source_kind=source_kind,
        text_request=None,
        payload_length=payload_length,
        issues=(issue,),
        evidence_ids=evidence_ids,
    )


def _jpeg_app13_photoshop_resource_section(app13_payload: bytes) -> bytes | None:
    photoshop_3_prefix = b"Photoshop 3.0\0"
    photoshop_25_prefix = b"Adobe_Photoshop2.5"
    if app13_payload.startswith(photoshop_3_prefix):
        return app13_payload[len(photoshop_3_prefix) :]
    if app13_payload.startswith(photoshop_25_prefix):
        return app13_payload[len(photoshop_25_prefix) :]
    return None


def _blocked_raw_profile_construction(
    *,
    keyword: str,
    profile_type: str | None,
    payload_length: int,
    code: PngRawProfileConstructionIssueCode,
    reason: str,
    evidence_ids: tuple[PngEvidenceId, ...],
) -> PngRawProfileConstructionPlan:
    issue = PngRawProfileConstructionIssue(
        code=code,
        reason=reason,
        evidence_ids=evidence_ids,
    )
    return PngRawProfileConstructionPlan(
        status="blocked",
        keyword=keyword,
        profile_type=profile_type,
        payload_length=payload_length,
        text_request=None,
        issues=(issue,),
        evidence_ids=evidence_ids,
    )


def build_xmp_itxt_payload(xmp_payload: bytes) -> bytes:
    return b"XML:com.adobe.xmp\0\0\0\0\0" + xmp_payload


def build_iccp_payload(icc_payload: bytes, profile_name: str | None = None) -> bytes:
    encoded_name = (profile_name or "icm").encode("latin-1")
    return encoded_name + b"\0\0" + zlib.compress(icc_payload)


def build_phys_payload(request: PngPhysicalPixelRequest) -> bytes:
    pixels_per_unit_x = request.resolved_pixels_per_unit_x()
    pixels_per_unit_y = request.resolved_pixels_per_unit_y()
    pixel_units = request.resolved_pixel_units()
    if pixels_per_unit_x < 0 or pixels_per_unit_x > 0xFFFFFFFF:
        raise ValueError("PixelsPerUnitX must fit PNG pHYs int32u storage.")
    if pixels_per_unit_y < 0 or pixels_per_unit_y > 0xFFFFFFFF:
        raise ValueError("PixelsPerUnitY must fit PNG pHYs int32u storage.")
    if pixel_units not in (0, 1):
        raise ValueError("PixelUnits must be 0 (Unknown) or 1 (meters).")
    return (
        pixels_per_unit_x.to_bytes(4, "big")
        + pixels_per_unit_y.to_bytes(4, "big")
        + bytes((pixel_units,))
    )


def _unsupported_plan(
    signature: PngSignaturePlan,
    png_data: bytes,
    gates: list[PngOutputEmissionGate],
    chunks: tuple[PngChunkPlan, ...] = (),
) -> PngChunkTransactionPlan:
    return PngChunkTransactionPlan(
        status="unsupported",
        signature=signature,
        chunks=chunks,
        metadata_routes=(),
        actions=(),
        output_chunks=(),
        output_size=PngOutputSizePlan(
            input_file_size=len(png_data),
            planned_file_size=None,
            trailer_size=0,
            evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
        ),
        output_emission_gates=unique_gates(tuple(gates)),
        trailer=b"",
        evidence_ids=unique_sources(
            (
                PNG_SIGNATURE_SOURCE,
                PNG_PROCESS_SIGNATURE_SOURCE,
                PNG_CHUNK_ENUMERATION_SOURCE,
                *(source for gate in gates for source in gate.evidence_ids),
            )
        ),
    )


def _structural_gates(chunks: tuple[PngChunkPlan, ...]) -> tuple[PngOutputEmissionGate, ...]:
    gates: list[PngOutputEmissionGate] = []
    if not chunks:
        gates.append(
            PngOutputEmissionGate(
                code="missing_ihdr",
                reason="PNG contains no chunks, so IHDR is missing.",
                evidence_ids=(PNG_HEADER_ORDER_SOURCE,),
            )
        )
        return tuple(gates)
    if chunks[0].chunk_type != IHDR_CHUNK_TYPE:
        gates.append(
            PngOutputEmissionGate(
                code="ihdr_not_first",
                reason="PNG does not start with IHDR.",
                evidence_ids=(PNG_HEADER_ORDER_SOURCE,),
            )
        )
    if not any(chunk.chunk_type == IEND_CHUNK_TYPE for chunk in chunks):
        gates.append(
            PngOutputEmissionGate(
                code="missing_iend",
                reason="PNG has no IEND chunk.",
                evidence_ids=(PNG_IEND_TRAILER_SOURCE,),
            )
        )
    return tuple(gates)


def _crc_gates(chunks: tuple[PngChunkPlan, ...]) -> tuple[PngOutputEmissionGate, ...]:
    return tuple(
        PngOutputEmissionGate(
            code="bad_crc",
            reason=f"{ascii_chunk_id(chunk.chunk_type)} stored CRC does not match calculated CRC.",
            evidence_ids=(PNG_CRC_SOURCE, PNG_WRITE_CRC_VALIDATION_SOURCE),
        )
        for chunk in chunks
        if not chunk.crc_matches
    )


def _plan_output_chunks(
    chunks: tuple[PngChunkPlan, ...],
    text_requests: tuple[PngTextChunkRequest, ...],
    *,
    icc_payload: bytes | None,
    icc_profile_name: str | None,
    exif_payload: bytes | None,
    xmp_payload: bytes | None,
    physical_pixel: PngPhysicalPixelRequest | None,
    delete_text_keywords: frozenset[str],
    delete_metadata_groups: frozenset[str],
    delete_all_metadata: bool,
) -> tuple[
    tuple[PngOutputChunk, ...], tuple[PngChunkActionPlan, ...], tuple[PngOutputEmissionGate, ...]
]:
    if not chunks:
        return (), (), ()

    replace_keywords = {request.keyword for request in text_requests}
    replacing_exif = exif_payload is not None or delete_all_metadata
    replacing_xmp = xmp_payload is not None or delete_all_metadata
    replacing_icc = icc_payload is not None or delete_all_metadata
    replacing_physical_pixel = physical_pixel is not None or delete_all_metadata
    insert_at = _metadata_insertion_index(chunks)
    icc_insert_at = _icc_insertion_index(chunks)
    movable = _movable_after_idat_indexes(chunks)
    blocked_move_gates = _blocked_after_idat_text_gates(chunks, movable)

    before_icc_insert: list[PngOutputChunk] = []
    before_insert: list[PngOutputChunk] = []
    moved_metadata: list[PngOutputChunk] = []
    after_insert: list[PngOutputChunk] = []
    actions: list[PngChunkActionPlan] = []

    def should_remove(chunk: PngChunkPlan) -> tuple[bool, str]:
        route = _route_existing_chunk(chunk)
        if delete_all_metadata and route.metadata_kind in {
            "text",
            "xmp",
            "exif",
            "icc",
            "physical_pixel",
        }:
            return True, "Delete all PNG text/XMP/EXIF/ICC/pHYs metadata chunks."
        group_delete_reason = _delete_group_reason(route, delete_metadata_groups)
        if group_delete_reason is not None:
            return True, group_delete_reason
        if route.metadata_kind == "exif" and replacing_exif:
            return True, "Replace existing EXIF chunk with planned eXIf payload."
        if route.metadata_kind == "xmp" and replacing_xmp:
            return True, "Replace existing XMP chunk with planned standard iTXt payload."
        if route.metadata_kind == "icc" and replacing_icc:
            return True, "Replace existing ICC profile chunk with planned iCCP payload."
        if route.metadata_kind == "physical_pixel" and replacing_physical_pixel:
            return True, "Replace existing pHYs chunk with planned physical-pixel payload."
        if _is_raw_profile_route(route, {"icc", "icc_profile"}) and replacing_icc:
            return True, "Replace existing raw ICC profile TextualData with planned iCCP payload."
        if chunk.chunk_type == SRGB_CHUNK_TYPE and icc_payload is not None:
            return True, "Delete sRGB because ExifTool writes ICC_Profile as iCCP instead."
        if (
            route.chunk_type in TEXT_CHUNK_TYPES
            and route.keyword is not None
            and route.keyword in delete_text_keywords
        ):
            return True, "Delete existing PNG textual keyword by explicit tag delete."
        if (
            route.metadata_kind == "text"
            and route.keyword is not None
            and route.keyword in replace_keywords
        ):
            return True, "Replace existing text keyword with a planned text chunk."
        return False, ""

    for chunk in chunks:
        remove, reason = should_remove(chunk)
        if remove:
            route = _route_existing_chunk(chunk)
            evidence_ids = _delete_evidence_ids(route, delete_metadata_groups)
            deleting_text_keyword = (
                route.chunk_type in TEXT_CHUNK_TYPES
                and route.keyword is not None
                and route.keyword in delete_text_keywords
            )
            if deleting_text_keyword:
                evidence_ids = (
                    PNG_TEXT_TAG_DELETE_SOURCE,
                    PNG_TEXT_ROUTING_SOURCE,
                    PNG_TEXT_TABLE_SOURCE,
                )
            if chunk.chunk_type == SRGB_CHUNK_TYPE and icc_payload is not None:
                evidence_ids = (
                    PNG_ICC_CHUNK_SOURCE,
                    PNG_ICC_WRITE_SOURCE,
                    PNG_ADD_ICCP_SOURCE,
                    PNG_SRGB_ICC_SOURCE,
                )
            actions.append(
                PngChunkActionPlan(
                    kind="delete_metadata"
                    if delete_all_metadata
                    or _delete_group_reason(route, delete_metadata_groups)
                    or deleting_text_keyword
                    else "replace_metadata",
                    chunk_type=chunk.chunk_type,
                    source_index=chunk.index,
                    output_index=None,
                    payload_length=chunk.payload_length,
                    reason=reason,
                    evidence_ids=evidence_ids,
                )
            )
            continue

        output = chunk.to_output_chunk()
        if chunk.index in movable:
            moved_metadata.append(output)
            actions.append(
                PngChunkActionPlan(
                    kind="move_before_idat",
                    chunk_type=chunk.chunk_type,
                    source_index=chunk.index,
                    output_index=None,
                    payload_length=chunk.payload_length,
                    reason="Move text/EXIF chunk from after IDAT to before IDAT.",
                    evidence_ids=(PNG_MOVE_TEXT_SOURCE, PNG_AFTER_IDAT_WARNING_SOURCE),
                )
            )
        elif chunk.index < icc_insert_at:
            before_icc_insert.append(output)
            actions.append(_copy_action(chunk))
        elif chunk.index < insert_at:
            before_insert.append(output)
            actions.append(_copy_action(chunk))
        else:
            after_insert.append(output)
            actions.append(_copy_action(chunk))

    inserted_icc: list[PngOutputChunk] = []
    if icc_payload is not None and not delete_all_metadata:
        payload = build_iccp_payload(icc_payload, icc_profile_name)
        inserted_icc.append(PngOutputChunk(ICC_CHUNK_TYPE, payload))
        actions.append(
            PngChunkActionPlan(
                kind="insert_icc",
                chunk_type=ICC_CHUNK_TYPE,
                source_index=None,
                output_index=None,
                payload_length=len(payload),
                reason="Insert planned ICC profile as compressed iCCP before PLTE/IDAT.",
                evidence_ids=(
                    PNG_ICC_CHUNK_SOURCE,
                    PNG_ICC_WRITE_SOURCE,
                    PNG_ADD_ICCP_SOURCE,
                ),
            )
        )

    inserted: list[PngOutputChunk] = []
    for request in text_requests:
        chunk_type, payload = build_text_chunk_payload(request)
        inserted.append(PngOutputChunk(chunk_type, payload))
        actions.append(
            PngChunkActionPlan(
                kind="insert_text",
                chunk_type=chunk_type,
                source_index=None,
                output_index=None,
                payload_length=len(payload),
                reason="Insert planned PNG textual metadata before IDAT/IEND.",
                evidence_ids=(
                    PNG_TEXT_ROUTING_SOURCE,
                    PNG_TEXT_TABLE_SOURCE,
                    PNG_ADDCHUNKS_ORDER_SOURCE,
                ),
            )
        )
    if physical_pixel is not None and not delete_all_metadata:
        payload = build_phys_payload(physical_pixel)
        inserted.append(PngOutputChunk(PHYS_CHUNK_TYPE, payload))
        actions.append(
            PngChunkActionPlan(
                kind="insert_physical_pixel",
                chunk_type=PHYS_CHUNK_TYPE,
                source_index=None,
                output_index=None,
                payload_length=len(payload),
                reason=(
                    "Insert planned PNG PhysicalPixel data as pHYs before IDAT/IEND, "
                    "using ExifTool's default pHYs fields where unspecified."
                ),
                evidence_ids=(
                    PNG_PHYS_CHUNK_SOURCE,
                    PNG_PHYS_TABLE_SOURCE,
                    PNG_PHYS_WRITE_SOURCE,
                    PNG_ADDCHUNKS_ORDER_SOURCE,
                ),
            )
        )
    if xmp_payload is not None and not delete_all_metadata:
        inserted.append(PngOutputChunk(b"iTXt", build_xmp_itxt_payload(xmp_payload)))
        actions.append(
            PngChunkActionPlan(
                kind="insert_xmp",
                chunk_type=b"iTXt",
                source_index=None,
                output_index=None,
                payload_length=len(build_xmp_itxt_payload(xmp_payload)),
                reason="Insert standard PNG XMP as uncompressed iTXt before IDAT/IEND.",
                evidence_ids=(PNG_XMP_SOURCE, PNG_ADDCHUNKS_ORDER_SOURCE),
            )
        )
    if exif_payload is not None and not delete_all_metadata:
        inserted.append(PngOutputChunk(b"eXIf", exif_payload))
        actions.append(
            PngChunkActionPlan(
                kind="insert_exif",
                chunk_type=b"eXIf",
                source_index=None,
                output_index=None,
                payload_length=len(exif_payload),
                reason="Insert planned EXIF as eXIf before IDAT/IEND.",
                evidence_ids=(PNG_EXIF_SOURCE, PNG_ADDCHUNKS_ORDER_SOURCE),
            )
        )

    output_chunks = tuple(
        (
            *before_icc_insert,
            *inserted_icc,
            *before_insert,
            *moved_metadata,
            *inserted,
            *after_insert,
        )
    )
    indexed_actions = _with_output_indexes(tuple(actions), output_chunks)
    return output_chunks, indexed_actions, blocked_move_gates


def _normalize_delete_groups(delete_metadata_groups: Iterable[str]) -> frozenset[str]:
    aliases = {
        "all": "png",
        "ifd0": "exif",
        "icc_profile": "icc",
        "iptc": "photoshop",
        "physicalpixel": "png_phys",
        "png_phys": "png_phys",
        "png_phys_chunk": "png_phys",
    }
    normalized: set[str] = set()
    for group in delete_metadata_groups:
        cleaned = group.strip().lower().replace("-", "_")
        normalized.add(aliases.get(cleaned, cleaned))
    return frozenset(normalized)


def _delete_group_reason(
    route: PngMetadataRoutingPlan,
    delete_groups: frozenset[str],
) -> str | None:
    if not delete_groups:
        return None
    if "png" in delete_groups and route.metadata_kind in {
        "text",
        "xmp",
        "exif",
        "icc",
        "physical_pixel",
    }:
        return "Delete PNG metadata chunk because the PNG group is being deleted."
    if route.metadata_kind == "exif" and "exif" in delete_groups:
        return "Delete PNG EXIF chunk because the EXIF/IFD0 group is being deleted."
    if route.metadata_kind == "xmp" and "xmp" in delete_groups:
        return "Delete PNG XMP chunk because the XMP group is being deleted."
    if route.metadata_kind == "icc" and "icc" in delete_groups:
        return "Delete PNG ICC chunk because the ICC_Profile group is being deleted."
    if route.metadata_kind == "physical_pixel" and "png_phys" in delete_groups:
        return "Delete PNG pHYs chunk because the PNG-pHYs group is being deleted."
    if _is_raw_profile_route(route, delete_groups):
        return "Delete raw-profile TextualData chunk because its nested group is being deleted."
    return None


def _is_raw_profile_route(
    route: PngMetadataRoutingPlan,
    delete_groups: frozenset[str] | set[str],
) -> bool:
    if route.textual_storage_family != "raw_profile_keyword" or route.keyword is None:
        return False
    raw_profile_groups = _raw_profile_groups(route.keyword)
    return bool(raw_profile_groups.intersection(delete_groups))


def _raw_profile_groups(keyword: str) -> frozenset[str]:
    normalized = keyword.lower()
    if normalized == "raw profile type app1":
        return frozenset(("exif", "xmp"))
    if normalized == "raw profile type exif":
        return frozenset(("exif",))
    if normalized in {"raw profile type icc", "raw profile type icm"}:
        return frozenset(("icc",))
    if normalized == "raw profile type iptc":
        return frozenset(("photoshop",))
    if normalized == "raw profile type xmp":
        return frozenset(("xmp",))
    if normalized == "raw profile type 8bim":
        return frozenset(("photoshop",))
    return frozenset()


def _delete_evidence_ids(
    route: PngMetadataRoutingPlan,
    delete_groups: frozenset[str],
) -> tuple[PngEvidenceId, ...]:
    sources = route.evidence_ids
    if "png" in delete_groups and route.chunk_type in TEXT_CHUNK_TYPES:
        sources = (*sources, PNG_TEXTUAL_GROUP_DELETE_SOURCE)
    if route.textual_storage_family == "raw_profile_keyword":
        sources = (
            *sources,
            PNG_DIRECTORY_ROUTING_SOURCE,
            PNG_RAW_PROFILE_SOURCE,
            PNG_RAW_PROFILE_DELETE_SOURCE,
        )
    elif route.metadata_kind in {"xmp", "exif", "icc"}:
        sources = (*sources, PNG_DIRECTORY_ROUTING_SOURCE)
    elif route.metadata_kind == "physical_pixel":
        sources = (
            *sources,
            PNG_DIRECTORY_ROUTING_SOURCE,
            PNG_PHYS_CHUNK_SOURCE,
            PNG_PHYS_TABLE_SOURCE,
        )
    return unique_sources(sources)


def _copy_action(chunk: PngChunkPlan) -> PngChunkActionPlan:
    return PngChunkActionPlan(
        kind="copy",
        chunk_type=chunk.chunk_type,
        source_index=chunk.index,
        output_index=None,
        payload_length=chunk.payload_length,
        reason="Preserve existing PNG chunk payload.",
        evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
    )


def _with_output_indexes(
    actions: tuple[PngChunkActionPlan, ...],
    output_chunks: tuple[PngOutputChunk, ...],
) -> tuple[PngChunkActionPlan, ...]:
    remaining_indexes_by_type: dict[bytes, list[int]] = {}
    for index, chunk in enumerate(output_chunks):
        remaining_indexes_by_type.setdefault(chunk.chunk_type, []).append(index)
    updated: list[PngChunkActionPlan] = []
    for action in actions:
        output_index = action.output_index
        if action.kind in {
            "copy",
            "move_before_idat",
            "insert_text",
            "insert_xmp",
            "insert_exif",
            "insert_icc",
            "insert_physical_pixel",
        }:
            indexes = remaining_indexes_by_type.get(action.chunk_type) or []
            output_index = indexes.pop(0) if indexes else None
        updated.append(
            PngChunkActionPlan(
                kind=action.kind,
                chunk_type=action.chunk_type,
                source_index=action.source_index,
                output_index=output_index,
                payload_length=action.payload_length,
                reason=action.reason,
                evidence_ids=action.evidence_ids,
            )
        )
    return tuple(updated)


def _metadata_insertion_index(chunks: tuple[PngChunkPlan, ...]) -> int:
    for index, chunk in enumerate(chunks):
        if chunk.chunk_type in DATA_CHUNK_TYPES or chunk.chunk_type == IEND_CHUNK_TYPE:
            return index
    return len(chunks)


def _icc_insertion_index(chunks: tuple[PngChunkPlan, ...]) -> int:
    for index, chunk in enumerate(chunks):
        if (
            chunk.chunk_type == PLTE_CHUNK_TYPE
            or chunk.chunk_type in DATA_CHUNK_TYPES
            or chunk.chunk_type == IEND_CHUNK_TYPE
        ):
            return index
    return len(chunks)


def _movable_after_idat_indexes(chunks: tuple[PngChunkPlan, ...]) -> set[int]:
    first_data_index = next(
        (index for index, chunk in enumerate(chunks) if chunk.chunk_type in DATA_CHUNK_TYPES),
        None,
    )
    if first_data_index is None:
        return set()
    movable: set[int] = set()
    for chunk in chunks[first_data_index + 1 :]:
        if chunk.chunk_type in NO_LEAPFROG_CHUNK_TYPES:
            break
        if chunk.chunk_type in MOVABLE_TEXT_CHUNK_TYPES:
            movable.add(chunk.index)
    return movable


def _blocked_after_idat_text_gates(
    chunks: tuple[PngChunkPlan, ...],
    movable: set[int],
) -> tuple[PngOutputEmissionGate, ...]:
    first_data_index = next(
        (index for index, chunk in enumerate(chunks) if chunk.chunk_type in DATA_CHUNK_TYPES),
        None,
    )
    if first_data_index is None:
        return ()
    blocked = [
        chunk
        for chunk in chunks[first_data_index + 1 :]
        if chunk.chunk_type in MOVABLE_TEXT_CHUNK_TYPES and chunk.index not in movable
    ]
    return tuple(
        PngOutputEmissionGate(
            code="text_after_idat_cannot_move_across_no_leapfrog",
            reason=(
                f"{ascii_chunk_id(chunk.chunk_type)} after IDAT cannot be moved "
                "across a no-leapfrog chunk."
            ),
            evidence_ids=(PNG_MOVE_TEXT_SOURCE, PNG_AFTER_IDAT_WARNING_SOURCE),
        )
        for chunk in blocked
    )


def _route_existing_chunk(chunk: PngChunkPlan) -> PngMetadataRoutingPlan:
    if chunk.chunk_type == PHYS_CHUNK_TYPE:
        return PngMetadataRoutingPlan(
            chunk_index=chunk.index,
            chunk_type=chunk.chunk_type,
            metadata_kind="physical_pixel",
            keyword=None,
            text_route=None,
            textual_keyword_source="png_chunk_table",
            textual_tag_name="PhysicalPixel",
            textual_storage_family=None,
            textual_registered=None,
            textual_subdirectory="Image::ExifTool::PNG::PhysicalPixel",
            textual_non_standard=None,
            textual_duplicate_variant_indexes=(),
            evidence_ids=(PNG_PHYS_CHUNK_SOURCE, PNG_PHYS_TABLE_SOURCE),
        )
    if chunk.chunk_type == ICC_CHUNK_TYPE:
        profile_name = _iccp_profile_name(chunk.payload)
        return PngMetadataRoutingPlan(
            chunk_index=chunk.index,
            chunk_type=chunk.chunk_type,
            metadata_kind="icc",
            keyword=profile_name,
            text_route=None,
            textual_keyword_source="png_chunk_table",
            textual_tag_name="ICC_Profile",
            textual_storage_family="icc_profile_chunk",
            textual_registered=None,
            textual_subdirectory="Image::ExifTool::ICC_Profile::Main",
            textual_non_standard=None,
            textual_duplicate_variant_indexes=(),
            evidence_ids=(PNG_ICC_CHUNK_SOURCE, PNG_ICC_WRITE_SOURCE),
        )
    if chunk.chunk_type in EXIF_CHUNK_TYPES:
        return PngMetadataRoutingPlan(
            chunk_index=chunk.index,
            chunk_type=chunk.chunk_type,
            metadata_kind="exif",
            keyword=None,
            text_route=None,
            textual_keyword_source="png_chunk_table",
            textual_tag_name=ascii_chunk_id(chunk.chunk_type),
            textual_storage_family="png_exif_chunk",
            textual_registered=None,
            textual_subdirectory="Image::ExifTool::Exif::Main",
            textual_non_standard="compressed EXIF" if chunk.chunk_type == b"zXIf" else None,
            textual_duplicate_variant_indexes=(),
            evidence_ids=(PNG_EXIF_SOURCE,),
        )
    if chunk.chunk_type == OBSOLETE_XMP_CHUNK_TYPE:
        return PngMetadataRoutingPlan(
            chunk_index=chunk.index,
            chunk_type=chunk.chunk_type,
            metadata_kind="xmp",
            keyword=None,
            text_route=None,
            textual_keyword_source="png_chunk_table",
            textual_tag_name="XMP",
            textual_storage_family="standard_xmp_keyword",
            textual_registered=False,
            textual_subdirectory="Image::ExifTool::XMP::Main",
            textual_non_standard="obsolete tXMP chunk",
            textual_duplicate_variant_indexes=(),
            evidence_ids=(PNG_XMP_SOURCE,),
        )
    if chunk.chunk_type in TEXT_CHUNK_TYPES:
        keyword = _text_keyword(chunk.chunk_type, chunk.payload)
        facts = _textual_route_facts(keyword)
        kind: PngMetadataKind = "xmp" if facts.storage_family == "standard_xmp_keyword" else "text"
        return PngMetadataRoutingPlan(
            chunk_index=chunk.index,
            chunk_type=chunk.chunk_type,
            metadata_kind=kind,
            keyword=keyword,
            text_route=ascii_chunk_id(chunk.chunk_type),  # type: ignore[arg-type]
            textual_keyword_source=facts.keyword_source,
            textual_tag_name=facts.tag_name,
            textual_storage_family=facts.storage_family,
            textual_registered=facts.registered,
            textual_subdirectory=facts.subdirectory,
            textual_non_standard=facts.non_standard,
            textual_duplicate_variant_indexes=facts.duplicate_variant_indexes,
            evidence_ids=unique_sources(
                (
                    PNG_TEXT_TABLE_SOURCE,
                    *(_xmp_sources_for_kind(kind)),
                    *facts.evidence_ids,
                )
            ),
        )
    return PngMetadataRoutingPlan(
        chunk_index=chunk.index,
        chunk_type=chunk.chunk_type,
        metadata_kind="unknown",
        keyword=None,
        text_route=None,
        textual_keyword_source=None,
        textual_tag_name=None,
        textual_storage_family=None,
        textual_registered=None,
        textual_subdirectory=None,
        textual_non_standard=None,
        textual_duplicate_variant_indexes=(),
        evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
    )


def _route_text_request(request: PngTextChunkRequest) -> PngMetadataRoutingPlan:
    facts = _textual_route_facts(request.keyword)
    route: PngTextRoute
    if facts.storage_family == "standard_xmp_keyword":
        route = "iTXt"
    elif facts.storage_family == "raw_profile_keyword":
        route = "zTXt" if request.compress else "tEXt"
    elif request.language_code or request.force_itxt or _needs_unicode_itxt_route(request):
        route = "iTXt"
    elif request.compress:
        route = "zTXt"
    else:
        route = "tEXt"
    return PngMetadataRoutingPlan(
        chunk_index=None,
        chunk_type=route.encode("ascii"),
        metadata_kind="xmp" if facts.storage_family == "standard_xmp_keyword" else "text",
        keyword=request.keyword,
        text_route=route,
        textual_keyword_source=facts.keyword_source,
        textual_tag_name=facts.tag_name,
        textual_storage_family=facts.storage_family,
        textual_registered=facts.registered,
        textual_subdirectory=facts.subdirectory,
        textual_non_standard=facts.non_standard,
        textual_duplicate_variant_indexes=facts.duplicate_variant_indexes,
        evidence_ids=unique_sources(
            (
                PNG_TEXT_ROUTING_SOURCE,
                PNG_TEXT_TABLE_SOURCE,
                *facts.evidence_ids,
            )
        ),
    )


def _route_physical_pixel_request() -> PngMetadataRoutingPlan:
    return PngMetadataRoutingPlan(
        chunk_index=None,
        chunk_type=PHYS_CHUNK_TYPE,
        metadata_kind="physical_pixel",
        keyword=None,
        text_route=None,
        textual_keyword_source="png_chunk_table",
        textual_tag_name="PhysicalPixel",
        textual_storage_family=None,
        textual_registered=None,
        textual_subdirectory="Image::ExifTool::PNG::PhysicalPixel",
        textual_non_standard=None,
        textual_duplicate_variant_indexes=(),
        evidence_ids=(PNG_PHYS_CHUNK_SOURCE, PNG_PHYS_TABLE_SOURCE, PNG_PHYS_WRITE_SOURCE),
    )


def _xmp_sources_for_kind(kind: PngMetadataKind) -> tuple[PngEvidenceId, ...]:
    return (PNG_XMP_SOURCE,) if kind == "xmp" else ()


def _iccp_profile_name(payload: bytes) -> str | None:
    name, separator, _compressed = payload.partition(b"\0")
    if not separator:
        return None
    return name.decode("latin-1")


def _textual_route_facts(keyword: str | None) -> PngTextualRouteFacts:
    if keyword is None:
        return PngTextualRouteFacts(
            keyword_source="arbitrary_textual_keyword",
            tag_name=None,
            storage_family=None,
            registered=None,
            subdirectory=None,
            non_standard=None,
            duplicate_variant_indexes=(),
            evidence_ids=(PNG_TEXT_TABLE_SOURCE,),
        )

    source_facts = _textual_route_facts_from_source_index(keyword)
    if source_facts is not None:
        return source_facts

    database_facts = _textual_route_facts_from_database_plan(keyword)
    if database_facts is not None:
        return database_facts

    return PngTextualRouteFacts(
        keyword_source="arbitrary_textual_keyword",
        tag_name=keyword,
        storage_family="textual_keyword",
        registered=False,
        subdirectory=None,
        non_standard="user-defined or extracted arbitrary TextualData keyword",
        duplicate_variant_indexes=(),
        evidence_ids=(PNG_TEXT_TABLE_SOURCE,),
    )


def _textual_route_facts_from_source_index(keyword: str) -> PngTextualRouteFacts | None:
    source_path = _png_textual_source_path()
    if source_path is None:
        return None

    from exifmodern.formats.png.textual_data_database_plan import (
        png_textual_data_source_table_from_source_path,
    )

    source_index = png_textual_data_source_table_from_source_path(source_path).index()
    record = source_index.record_for_keyword(keyword)
    if record is None:
        return None
    duplicate = source_index.duplicate_variant_explanation(keyword)
    duplicate_indexes = () if duplicate is None else duplicate.duplicate_variant_indexes
    duplicate_sources = () if duplicate is None else duplicate.evidence_ids
    return PngTextualRouteFacts(
        keyword_source="textual_data_source_index",
        tag_name=record.tag_name,
        storage_family=_png_textual_storage_family(record.storage_family),
        registered=record.registered,
        subdirectory=record.subdirectory,
        non_standard=record.non_standard,
        duplicate_variant_indexes=duplicate_indexes,
        evidence_ids=unique_sources(
            (
                _record_source_reference(record.keyword, record.source_path, record.source_line),
                record.to_plan_entry().evidence_id,
                *duplicate_sources,
            )
        ),
    )


def _textual_route_facts_from_database_plan(keyword: str) -> PngTextualRouteFacts | None:
    from exifmodern.formats.png.textual_data_database_plan import png_textual_data_database_plan

    try:
        entry = png_textual_data_database_plan().entry(keyword)
    except KeyError:
        return None
    return PngTextualRouteFacts(
        keyword_source="textual_data_database_plan",
        tag_name=entry.tag_name,
        storage_family=_png_textual_storage_family(entry.storage_family),
        registered=entry.registered,
        subdirectory=entry.subdirectory,
        non_standard=entry.non_standard,
        duplicate_variant_indexes=(),
        evidence_ids=(entry.evidence_id,),
    )


def _png_textual_source_path() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent.parent / "exiftool" / "lib" / "Image" / "ExifTool" / "PNG.pm"
        if candidate.exists():
            return candidate
    return None


def _png_textual_storage_family(storage_family: str) -> PngTextualStorageFamily:
    if storage_family == "standard_xmp_keyword":
        return "standard_xmp_keyword"
    if storage_family == "raw_profile_keyword":
        return "raw_profile_keyword"
    if storage_family == "png_exif_chunk":
        return "png_exif_chunk"
    return "textual_keyword"


def _record_source_reference(keyword: str, source_path: str, source_line: int) -> PngEvidenceId:
    normalized_keyword = (
        keyword.lower().replace(":", "_").replace(" ", "_").replace("/", "_").replace("-", "_")
    )
    normalized_path = source_path.rsplit("/", maxsplit=1)[-1].lower().replace(".", "_")
    return f"png.textual_data.{normalized_path}.{source_line}.{normalized_keyword}"


def _text_keyword(chunk_type: bytes, payload: bytes) -> str | None:
    if b"\0" not in payload:
        return None
    keyword = payload.split(b"\0", 1)[0]
    encoding = "utf-8" if chunk_type == b"iTXt" else "latin-1"
    try:
        return keyword.decode(encoding)
    except UnicodeDecodeError:
        return keyword.decode("latin-1", errors="replace")


def _contains_non_latin_bytes(value: bytes) -> bool:
    return any(byte >= 0x80 for byte in value)


def _needs_unicode_itxt_route(request: PngTextChunkRequest) -> bool:
    return request.charset != "Latin" and _contains_non_latin_bytes(request.value)


def _itxt_value_bytes(request: PngTextChunkRequest) -> bytes:
    facts = _textual_route_facts(request.keyword)
    if facts.storage_family == "standard_xmp_keyword":
        return request.value
    if request.charset == "Latin":
        return request.value.decode("latin-1").encode("utf-8")
    return request.value


def ascii_chunk_id(chunk_id: bytes | None) -> str | None:
    if chunk_id is None:
        return None
    return chunk_id.decode("latin-1")


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return list(values)


def unique_sources(references: Iterable[PngEvidenceId]) -> tuple[PngEvidenceId, ...]:
    seen: set[PngEvidenceId] = set()
    unique: list[PngEvidenceId] = []
    for reference in references:
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(reference)
    return tuple(unique)


def unique_gates(gates: tuple[PngOutputEmissionGate, ...]) -> tuple[PngOutputEmissionGate, ...]:
    seen: set[tuple[PngEmissionGateCode, str]] = set()
    unique: list[PngOutputEmissionGate] = []
    for gate in gates:
        key = (gate.code, gate.reason)
        if key in seen:
            continue
        seen.add(key)
        unique.append(gate)
    return tuple(unique)


from exifmodern.formats.png.textout_report import (  # noqa: E402, F401
    PngTextOutLineKind,
    PngTransactionTextOutLine,
    PngTransactionTextOutReport,
    build_png_transaction_textout_report,
    build_png_xmp_move_textout_report,
)
