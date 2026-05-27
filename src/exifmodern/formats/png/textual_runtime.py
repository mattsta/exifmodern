"""Runtime extraction for PNG textual metadata chunks.

The helper in this module is intentionally package-local.  It promotes the
source-backed textual route facts already used by the PNG transaction planner
into read-time records without decoding nested raw profile payloads.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from exifmodern.formats.png.read_chunks import (
    DATA_CHUNK_TYPES,
    EXIF_CHUNK_TYPES,
    ICC_CHUNK_TYPE,
    OBSOLETE_XMP_CHUNK_TYPE,
    PHYS_CHUNK_TYPE,
    PNG_AFTER_IDAT_WARNING_SOURCE,
    PNG_CHUNK_ENUMERATION_SOURCE,
    PNG_CRC_SOURCE,
    PNG_EXIF_SOURCE,
    PNG_ICC_CHUNK_SOURCE,
    PNG_PHYS_CHUNK_SOURCE,
    PNG_PHYS_TABLE_SOURCE,
    PNG_TEXT_ROUTING_SOURCE,
    PNG_TEXT_TABLE_SOURCE,
    PNG_XMP_SOURCE,
    TEXT_CHUNK_TYPES,
    PngChunkPlan,
    ascii_chunk_id,
    build_png_read_chunk_plan,
    unique_sources,
)
from exifmodern.json_types import JsonArray, JsonObject, JsonValue, json_string_array_or_none

if TYPE_CHECKING:
    from exifmodern.formats.png.chunk_transaction_plan import PngTextChunkRequest
    from exifmodern.formats.xmp.property_write import (
        XmpLocalizedTextPropertyWrite,
        XmpPropertySpec,
    )

type PngEvidenceId = str
type PngTextualRuntimeStatus = Literal["extracted", "unsupported"]
type PngTextualRuntimeIssueCode = Literal[
    "missing_text_separator",
    "missing_compression_method",
    "unsupported_compression_method",
    "compressed_payload_decode_failed",
    "malformed_itxt_payload",
    "malformed_raw_profile",
    "unsupported_raw_profile_type",
    "nested_raw_profile_decode_failed",
    "native_exif_decode_failed",
    "native_icc_payload_decode_failed",
    "native_icc_decode_failed",
    "native_physical_pixel_decode_failed",
]
type PngTextualValueEncoding = Literal["latin-1", "utf-8"]
type PngRawProfileNestedKind = Literal["exif", "icc", "iptc", "photoshop", "xmp"]
type PngRawProfileNestedTagValue = str | int | float | bool | None | list[str]
type PngNativeMetadataKind = Literal["exif", "icc", "physical_pixel", "exiftool_warning"]
type PngXmpItxtWriteStatus = Literal["planned", "blocked"]
type PngMetadataKind = Literal["text", "xmp", "exif", "icc", "physical_pixel", "unknown"]
type PngTextCharset = Literal["Latin", "UTF8"]
type PngTextRoute = Literal["tEXt", "zTXt", "iTXt"]
type PngTextualKeywordSource = Literal[
    "textual_data_source_index",
    "textual_data_database_plan",
    "arbitrary_textual_keyword",
    "png_chunk_table",
]
type PngTextualStorageFamily = Literal[
    "textual_keyword",
    "standard_xmp_keyword",
    "raw_profile_keyword",
    "png_exif_chunk",
    "icc_profile_chunk",
]
type PngXmpItxtWriteIssueCode = Literal[
    "unsupported_xmp_property",
    "invalid_xmp_language_code",
    "invalid_charset_value",
    "xmp_packet_mutation_failed",
]

PNG_TEXT_RUNTIME_TEXT_SOURCE: PngEvidenceId = "png.png_text_runtime_text"
PNG_TEXT_RUNTIME_COMPRESSED_SOURCE: PngEvidenceId = "png.png_text_runtime_compressed"
PNG_TEXT_RUNTIME_ITXT_SOURCE: PngEvidenceId = "png.png_text_runtime_itxt"
PNG_TEXT_RUNTIME_ARBITRARY_SOURCE: PngEvidenceId = "png.png_text_runtime_arbitrary"
PNG_TEXT_RUNTIME_PROFILE_SOURCE: PngEvidenceId = "png.png_text_runtime_profile"
PNG_XMP_APP1_PREFIX = b"http://ns.adobe.com/xap/1.0/\0"

PNG_NATIVE_EXIF_RUNTIME_SOURCE: PngEvidenceId = "png.png_native_exif_runtime"
PNG_NATIVE_ICC_RUNTIME_SOURCE: PngEvidenceId = "png.png_native_icc_runtime"
PNG_NATIVE_PHYS_RUNTIME_SOURCE: PngEvidenceId = "png.png_native_phys_runtime"
PNG_TEST4_XMP_DESCRIPTION_SOURCE: PngEvidenceId = "png.png_test4_xmp_description"
XMP_PROPERTY_TABLE_SOURCE: PngEvidenceId = "png.xmp_property_table"
XMP_PROPERTY_WRITE_SOURCE: PngEvidenceId = "png.xmp_property_write"
XMP_DC_DESCRIPTION_LANG_ALT_SOURCE: PngEvidenceId = "png.xmp_dc_description_lang_alt"
XMP_LANG_ALT_SOURCE: PngEvidenceId = "png.xmp_lang_alt"


@dataclass(frozen=True)
class PngXmpAlternateLanguageWriteRequest:
    tag_name: str
    value: bytes
    charset: PngTextCharset = "UTF8"


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
class PngReadMetadataRoute:
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


@dataclass(frozen=True)
class PngXmpItxtWriteIssue:
    code: PngXmpItxtWriteIssueCode
    reason: str
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PngXmpItxtWritePlan:
    status: PngXmpItxtWriteStatus
    requests: tuple[PngXmpAlternateLanguageWriteRequest, ...]
    xmp_payload: bytes | None
    text_request: PngTextChunkRequest | None
    changed_properties: int
    deleted_properties: int
    issues: tuple[PngXmpItxtWriteIssue, ...]
    evidence_ids: tuple[PngEvidenceId, ...]

    @property
    def can_emit_text_request(self) -> bool:
        return self.status == "planned" and self.text_request is not None and not self.issues

    def to_json(self) -> JsonObject:
        return {
            "can_emit_text_request": self.can_emit_text_request,
            "changed_properties": self.changed_properties,
            "deleted_properties": self.deleted_properties,
            "issues": [issue.to_json() for issue in self.issues],
            "request_tags": [request.tag_name for request in self.requests],
            "status": self.status,
            "text_request_keyword": None
            if self.text_request is None
            else self.text_request.keyword,
            "xmp_payload_length": None if self.xmp_payload is None else len(self.xmp_payload),
        }


@dataclass(frozen=True)
class PngRawProfileNestedTag:
    group: str
    name: str
    value: PngRawProfileNestedTagValue
    table_name: str
    source: str

    def to_json(self) -> JsonObject:
        value: JsonValue
        if isinstance(self.value, list):
            items: JsonArray = [item for item in self.value]
            value = items
        else:
            value = self.value
        return {
            "group": self.group,
            "name": self.name,
            "source": self.source,
            "table_name": self.table_name,
            "value": value,
        }


@dataclass(frozen=True)
class PngNativeMetadataTag:
    group: str
    name: str
    value: PngRawProfileNestedTagValue
    table_name: str
    source: str

    def to_json(self) -> JsonObject:
        value: JsonValue
        value = [item for item in self.value] if isinstance(self.value, list) else self.value
        return {
            "group": self.group,
            "name": self.name,
            "source": self.source,
            "table_name": self.table_name,
            "value": value,
        }


@dataclass(frozen=True)
class PngNativeMetadataRecord:
    chunk_index: int
    chunk_type: bytes
    chunk_start_offset: int
    payload_offset: int
    metadata_kind: PngNativeMetadataKind
    tags: tuple[PngNativeMetadataTag, ...]
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_index": self.chunk_index,
            "chunk_start_offset": self.chunk_start_offset,
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "metadata_kind": self.metadata_kind,
            "payload_offset": self.payload_offset,
            "tags": [tag.to_json() for tag in self.tags],
        }


@dataclass(frozen=True)
class PngRawProfileNestedResult:
    kind: PngRawProfileNestedKind
    profile_type: str
    declared_length: int
    decoded_length: int
    tags: tuple[PngRawProfileNestedTag, ...]
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "decoded_length": self.decoded_length,
            "declared_length": self.declared_length,
            "kind": self.kind,
            "profile_type": self.profile_type,
            "tags": [tag.to_json() for tag in self.tags],
        }


@dataclass(frozen=True)
class PngTextualRuntimeIssue:
    chunk_index: int
    chunk_type: bytes
    code: PngTextualRuntimeIssueCode
    reason: str
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_index": self.chunk_index,
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PngTextualChunkRecord:
    chunk_index: int
    chunk_type: bytes
    chunk_start_offset: int
    payload_offset: int
    keyword: str
    tag_name: str | None
    metadata_kind: PngMetadataKind
    text_route: PngTextRoute
    textual_keyword_source: PngTextualKeywordSource
    textual_storage_family: PngTextualStorageFamily | None
    textual_registered: bool | None
    textual_subdirectory: str | None
    textual_non_standard: str | None
    textual_duplicate_variant_indexes: tuple[int, ...]
    language_code: str | None
    translated_keyword: str | None
    compressed: bool
    compression_method: int | None
    value: bytes
    value_encoding: PngTextualValueEncoding
    text: str
    evidence_ids: tuple[PngEvidenceId, ...]
    nested_raw_profile: PngRawProfileNestedResult | None

    @property
    def is_raw_profile(self) -> bool:
        return self.textual_storage_family == "raw_profile_keyword"

    @property
    def raw_profile_payload(self) -> bytes | None:
        if not self.is_raw_profile:
            return None
        return self.value

    def to_json(self) -> JsonObject:
        return {
            "chunk_index": self.chunk_index,
            "chunk_start_offset": self.chunk_start_offset,
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "compressed": self.compressed,
            "compression_method": self.compression_method,
            "keyword": self.keyword,
            "language_code": self.language_code,
            "metadata_kind": self.metadata_kind,
            "payload_offset": self.payload_offset,
            "tag_name": self.tag_name,
            "text": self.text,
            "text_route": self.text_route,
            "textual_duplicate_variant_indexes": list(self.textual_duplicate_variant_indexes),
            "textual_keyword_source": self.textual_keyword_source,
            "textual_non_standard": self.textual_non_standard,
            "textual_registered": self.textual_registered,
            "textual_storage_family": self.textual_storage_family,
            "textual_subdirectory": self.textual_subdirectory,
            "translated_keyword": self.translated_keyword,
            "value_encoding": self.value_encoding,
            "nested_raw_profile": self.nested_raw_profile.to_json()
            if self.nested_raw_profile is not None
            else None,
        }


@dataclass(frozen=True)
class PngTextualRuntimePlan:
    status: PngTextualRuntimeStatus
    records: tuple[PngTextualChunkRecord, ...]
    native_records: tuple[PngNativeMetadataRecord, ...]
    issues: tuple[PngTextualRuntimeIssue, ...]
    evidence_ids: tuple[PngEvidenceId, ...]

    def records_for_keyword(self, keyword: str) -> tuple[PngTextualChunkRecord, ...]:
        return tuple(record for record in self.records if record.keyword == keyword)

    def record_for_tag_name(self, tag_name: str) -> PngTextualChunkRecord | None:
        for record in self.records:
            if record.tag_name == tag_name:
                return record
        return None

    def to_json(self) -> JsonObject:
        return {
            "issues": [issue.to_json() for issue in self.issues],
            "native_records": [record.to_json() for record in self.native_records],
            "records": [record.to_json() for record in self.records],
            "status": self.status,
        }


@dataclass(frozen=True)
class _ParsedTextualPayload:
    keyword: str
    value: bytes
    value_encoding: PngTextualValueEncoding
    language_code: str | None
    translated_keyword: str | None
    compressed: bool
    compression_method: int | None
    evidence_ids: tuple[PngEvidenceId, ...]


def build_png_xmp_itxt_alternate_language_write_plan(
    requests: tuple[PngXmpAlternateLanguageWriteRequest, ...],
    *,
    source_xmp_packet: bytes | None = None,
) -> PngXmpItxtWritePlan:
    """Lower safe XMP alternate-language property writes to a standard PNG XMP iTXt request."""

    from exifmodern.formats.png.chunk_transaction_plan import PngTextChunkRequest
    from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
    from exifmodern.formats.xmp.packet import empty_xmp_packet
    from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan
    from exifmodern.formats.xmp.reader import parse_xmp_packet

    issues: list[PngXmpItxtWriteIssue] = []
    steps: list[XmpLocalizedTextPropertyWrite] = []
    for request in requests:
        lowered = _lower_xmp_alternate_language_request(request)
        if isinstance(lowered, PngXmpItxtWriteIssue):
            issues.append(lowered)
        else:
            steps.append(lowered)
    if issues:
        return _blocked_xmp_itxt_write_plan(requests, tuple(issues))

    plan = XmpPropertyWritePlan(
        tuple(steps),
        (),
        generated_specs=(_xmp_dc_description_spec(),),
    )
    try:
        mutation = apply_xmp_property_write_plan(source_xmp_packet or empty_xmp_packet(), plan)
        parse_xmp_packet(mutation.packet)
    except (SyntaxError, ValueError) as exc:
        issue = PngXmpItxtWriteIssue(
            code="xmp_packet_mutation_failed",
            reason=f"Existing XMP packet API could not produce parseable XMP: {exc}.",
            evidence_ids=(
                XMP_PROPERTY_WRITE_SOURCE,
                PNG_XMP_SOURCE,
                XMP_DC_DESCRIPTION_LANG_ALT_SOURCE,
            ),
        )
        return _blocked_xmp_itxt_write_plan(requests, (issue,))

    text_request = PngTextChunkRequest(
        keyword="XML:com.adobe.xmp",
        value=mutation.packet,
        charset="UTF8",
    )
    return PngXmpItxtWritePlan(
        status="planned",
        requests=requests,
        xmp_payload=mutation.packet,
        text_request=text_request,
        changed_properties=mutation.changed_properties,
        deleted_properties=mutation.deleted_properties,
        issues=(),
        evidence_ids=unique_sources(
            (
                PNG_TEST4_XMP_DESCRIPTION_SOURCE,
                PNG_XMP_SOURCE,
                PNG_TEXT_ROUTING_SOURCE,
                PNG_TEXT_TABLE_SOURCE,
                XMP_PROPERTY_TABLE_SOURCE,
                XMP_PROPERTY_WRITE_SOURCE,
                XMP_DC_DESCRIPTION_LANG_ALT_SOURCE,
                XMP_LANG_ALT_SOURCE,
            )
        ),
    )


def _lower_xmp_alternate_language_request(
    request: PngXmpAlternateLanguageWriteRequest,
) -> XmpLocalizedTextPropertyWrite | PngXmpItxtWriteIssue:
    from exifmodern.formats.xmp.property_write import (
        XmpLocalizedTextPropertyWrite,
        XmpLocalizedTextValue,
        normalized_xmp_language_code,
    )

    parsed = _parse_xmp_description_language_tag(request.tag_name)
    if parsed is None:
        return PngXmpItxtWriteIssue(
            code="unsupported_xmp_property",
            reason=(
                "PNG-local XMP iTXt lowering is limited to source-backed "
                "XMP:Description-LANG writes."
            ),
            evidence_ids=(
                PNG_TEST4_XMP_DESCRIPTION_SOURCE,
                XMP_DC_DESCRIPTION_LANG_ALT_SOURCE,
            ),
        )
    property_name, language_code = parsed
    normalized_language = normalized_xmp_language_code(language_code)
    if normalized_language is None:
        return PngXmpItxtWriteIssue(
            code="invalid_xmp_language_code",
            reason=f"{language_code!r} is not a valid XMP alternate-language suffix.",
            evidence_ids=(XMP_LANG_ALT_SOURCE,),
        )
    try:
        value = _decode_xmp_request_value(request.value, request.charset)
    except UnicodeDecodeError as exc:
        return PngXmpItxtWriteIssue(
            code="invalid_charset_value",
            reason=f"Request value could not be decoded as {request.charset}: {exc}.",
            evidence_ids=(PNG_TEST4_XMP_DESCRIPTION_SOURCE,),
        )
    return XmpLocalizedTextPropertyWrite(
        property_name=property_name,
        values=(XmpLocalizedTextValue(normalized_language, value),),
    )


def _parse_xmp_description_language_tag(tag_name: str) -> tuple[str, str] | None:
    if not tag_name.startswith("XMP:Description-"):
        return None
    language_code = tag_name.removeprefix("XMP:Description-")
    if not language_code:
        return None
    return "XMP-dc:Description", language_code


def _decode_xmp_request_value(value: bytes, charset: PngTextCharset) -> str:
    if charset == "Latin":
        return value.decode("latin-1")
    return value.decode("utf-8")


def _xmp_dc_description_spec() -> XmpPropertySpec:
    from exifmodern.formats.xmp.property_write import XmpPropertySpec

    return XmpPropertySpec(
        "XMP-dc:Description",
        "dc",
        "http://purl.org/dc/elements/1.1/",
        "description",
        "alt_text",
        (),
        "Alt",
    )


def _blocked_xmp_itxt_write_plan(
    requests: tuple[PngXmpAlternateLanguageWriteRequest, ...],
    issues: tuple[PngXmpItxtWriteIssue, ...],
) -> PngXmpItxtWritePlan:
    return PngXmpItxtWritePlan(
        status="blocked",
        requests=requests,
        xmp_payload=None,
        text_request=None,
        changed_properties=0,
        deleted_properties=0,
        issues=issues,
        evidence_ids=unique_sources(
            (
                PNG_TEST4_XMP_DESCRIPTION_SOURCE,
                PNG_XMP_SOURCE,
                XMP_DC_DESCRIPTION_LANG_ALT_SOURCE,
                XMP_LANG_ALT_SOURCE,
                *(source for issue in issues for source in issue.evidence_ids),
            )
        ),
    )


def extract_png_textual_runtime(png_data: bytes) -> PngTextualRuntimePlan:
    """Extract PNG textual chunks as typed route-aware runtime records."""

    read_plan = build_png_read_chunk_plan(png_data)
    routes_by_chunk_index = {
        route.chunk_index: route
        for route in (_read_route_existing_chunk(chunk) for chunk in read_plan.chunks)
        if route.chunk_index is not None
    }
    records: list[PngTextualChunkRecord] = []
    native_records: list[PngNativeMetadataRecord] = []
    issues: list[PngTextualRuntimeIssue] = []
    saw_data_chunk = False
    after_idat_text_exif_count = 0
    first_after_idat_chunk: PngChunkPlan | None = None
    for chunk in read_plan.chunks:
        if chunk.chunk_type in DATA_CHUNK_TYPES:
            saw_data_chunk = True
        elif saw_data_chunk and chunk.chunk_type in (*TEXT_CHUNK_TYPES, *EXIF_CHUNK_TYPES):
            after_idat_text_exif_count += 1
            if first_after_idat_chunk is None:
                first_after_idat_chunk = chunk
        if chunk.chunk_type == ICC_CHUNK_TYPE:
            native_record, native_issue = _native_icc_record(chunk)
            if native_record is not None:
                native_records.append(native_record)
            if native_issue is not None:
                issues.append(native_issue)
            continue
        if chunk.chunk_type in EXIF_CHUNK_TYPES:
            native_record, native_issue = _native_exif_record(chunk)
            if native_record is not None:
                native_records.append(native_record)
            if native_issue is not None:
                issues.append(native_issue)
            continue
        if chunk.chunk_type == PHYS_CHUNK_TYPE:
            native_record, native_issue = _native_physical_pixel_record(chunk)
            if native_record is not None:
                native_records.append(native_record)
            if native_issue is not None:
                issues.append(native_issue)
            continue
        if chunk.chunk_type not in TEXT_CHUNK_TYPES:
            continue
        route = routes_by_chunk_index.get(chunk.index)
        if route is None or route.text_route is None:
            continue
        parsed = _parse_textual_payload(chunk)
        if isinstance(parsed, PngTextualRuntimeIssue):
            issues.append(parsed)
            continue
        record, profile_issue = _runtime_record_from_payload(chunk, route, parsed)
        records.append(record)
        if profile_issue is not None:
            issues.append(profile_issue)
    if after_idat_text_exif_count and first_after_idat_chunk is not None:
        native_records.append(
            _after_idat_warning_record(first_after_idat_chunk, after_idat_text_exif_count)
        )
    status: PngTextualRuntimeStatus = "unsupported" if read_plan.issues or issues else "extracted"
    return PngTextualRuntimePlan(
        status=status,
        records=tuple(records),
        native_records=tuple(native_records),
        issues=tuple(issues),
        evidence_ids=unique_sources(
            (
                *read_plan.evidence_ids,
                PNG_TEXT_RUNTIME_TEXT_SOURCE,
                PNG_TEXT_RUNTIME_COMPRESSED_SOURCE,
                PNG_TEXT_RUNTIME_ITXT_SOURCE,
                PNG_TEXT_RUNTIME_ARBITRARY_SOURCE,
                PNG_TEXT_RUNTIME_PROFILE_SOURCE,
                PNG_NATIVE_EXIF_RUNTIME_SOURCE,
                PNG_NATIVE_ICC_RUNTIME_SOURCE,
                PNG_NATIVE_PHYS_RUNTIME_SOURCE,
                *(source for record in records for source in record.evidence_ids),
                *(source for record in native_records for source in record.evidence_ids),
                *(source for issue in read_plan.issues for source in issue.evidence_ids),
                *(source for issue in issues for source in issue.evidence_ids),
            )
        ),
    )


def _read_route_existing_chunk(chunk: PngChunkPlan) -> PngReadMetadataRoute:
    if chunk.chunk_type == PHYS_CHUNK_TYPE:
        return PngReadMetadataRoute(
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
        return PngReadMetadataRoute(
            chunk_index=chunk.index,
            chunk_type=chunk.chunk_type,
            metadata_kind="icc",
            keyword=_iccp_profile_name(chunk.payload),
            text_route=None,
            textual_keyword_source="png_chunk_table",
            textual_tag_name="ICC_Profile",
            textual_storage_family="icc_profile_chunk",
            textual_registered=None,
            textual_subdirectory="Image::ExifTool::ICC_Profile::Main",
            textual_non_standard=None,
            textual_duplicate_variant_indexes=(),
            evidence_ids=(PNG_ICC_CHUNK_SOURCE,),
        )
    if chunk.chunk_type in EXIF_CHUNK_TYPES:
        return PngReadMetadataRoute(
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
        return PngReadMetadataRoute(
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
        text_route = ascii_chunk_id(chunk.chunk_type)
        return PngReadMetadataRoute(
            chunk_index=chunk.index,
            chunk_type=chunk.chunk_type,
            metadata_kind=kind,
            keyword=keyword,
            text_route=_png_text_route(text_route),
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
                    *((PNG_XMP_SOURCE,) if kind == "xmp" else ()),
                    *facts.evidence_ids,
                )
            ),
        )
    return PngReadMetadataRoute(
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
        evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE, PNG_CRC_SOURCE),
    )


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

    from exifmodern.formats.png.textual_data_database_plan import png_textual_data_database_plan

    try:
        entry = png_textual_data_database_plan().entry(keyword)
    except KeyError:
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
    return PngTextualRouteFacts(
        keyword_source="textual_data_database_plan",
        tag_name=entry.tag_name,
        storage_family=_png_textual_storage_family(entry.storage_family),
        registered=entry.registered,
        subdirectory=entry.subdirectory,
        non_standard=entry.non_standard,
        duplicate_variant_indexes=_database_duplicate_variant_indexes(keyword),
        evidence_ids=(entry.evidence_id,),
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


def _database_duplicate_variant_indexes(keyword: str) -> tuple[int, ...]:
    if keyword == "Raw profile type APP1":
        return (1,)
    return ()


def _png_textual_source_path() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent.parent / "exiftool" / "lib" / "Image" / "ExifTool" / "PNG.pm"
        if candidate.exists():
            return candidate
    return None


def _record_source_reference(keyword: str, source_path: str, source_line: int) -> PngEvidenceId:
    normalized_keyword = (
        keyword.lower().replace(":", "_").replace(" ", "_").replace("/", "_").replace("-", "_")
    )
    normalized_path = source_path.rsplit("/", maxsplit=1)[-1].lower().replace(".", "_")
    return f"png.textual_data.{normalized_path}.{source_line}.{normalized_keyword}"


def _png_textual_storage_family(storage_family: str) -> PngTextualStorageFamily:
    if storage_family == "standard_xmp_keyword":
        return "standard_xmp_keyword"
    if storage_family == "raw_profile_keyword":
        return "raw_profile_keyword"
    if storage_family == "png_exif_chunk":
        return "png_exif_chunk"
    if storage_family == "icc_profile_chunk":
        return "icc_profile_chunk"
    return "textual_keyword"


def _text_keyword(chunk_type: bytes, payload: bytes) -> str | None:
    if b"\0" not in payload:
        return None
    keyword = payload.split(b"\0", 1)[0]
    encoding = "utf-8" if chunk_type == b"iTXt" else "latin-1"
    try:
        return keyword.decode(encoding)
    except UnicodeDecodeError:
        return keyword.decode("latin-1", errors="replace")


def _iccp_profile_name(payload: bytes) -> str | None:
    name, separator, _compressed = payload.partition(b"\0")
    if not separator:
        return None
    return name.decode("latin-1")


def _png_text_route(route: str | None) -> PngTextRoute | None:
    if route == "tEXt":
        return "tEXt"
    if route == "zTXt":
        return "zTXt"
    if route == "iTXt":
        return "iTXt"
    return None


def png_textual_xmp_packets(png_data: bytes) -> tuple[bytes, ...]:
    """Return source textual XMP packet bytes from standard PNG text routes."""

    return png_textual_xmp_packets_from_runtime_plan(extract_png_textual_runtime(png_data))


def png_textual_xmp_packets_from_runtime_plan(
    plan: PngTextualRuntimePlan,
) -> tuple[bytes, ...]:
    return tuple(
        record.value for record in plan.records if _is_standard_textual_xmp_packet_record(record)
    )


def _is_standard_textual_xmp_packet_record(record: PngTextualChunkRecord) -> bool:
    # PNG.pm routes XML:com.adobe.xmp textual chunks directly to XMP::Main.
    # Raw-profile XMP is decoded through a different profile container path.
    return (
        not record.is_raw_profile
        and record.textual_subdirectory == "Image::ExifTool::XMP::Main"
        and len(record.value) > 0
    )


def _native_exif_record(
    chunk: PngChunkPlan,
) -> tuple[PngNativeMetadataRecord | None, PngTextualRuntimeIssue | None]:
    payload = chunk.payload
    if chunk.chunk_type == b"zXIf":
        if len(payload) < 5 or payload[0] != 0:
            return None, _issue(
                chunk,
                "native_exif_decode_failed",
                "zXIf payload does not contain ExifTool's compression method and length header.",
                (PNG_NATIVE_EXIF_RUNTIME_SOURCE, PNG_EXIF_SOURCE),
            )
        try:
            payload = zlib.decompress(payload[5:])
        except zlib.error as exc:
            return None, _issue(
                chunk,
                "native_exif_decode_failed",
                f"zXIf payload could not be inflated: {exc}.",
                (PNG_NATIVE_EXIF_RUNTIME_SOURCE, PNG_EXIF_SOURCE),
            )
    try:
        from exifmodern.formats.tiff.primitives import inspect_ifd0

        inspection = inspect_ifd0(payload)
    except ValueError as exc:
        return None, _issue(
            chunk,
            "native_exif_decode_failed",
            f"Native PNG EXIF payload could not be parsed as TIFF: {exc}.",
            (PNG_NATIVE_EXIF_RUNTIME_SOURCE, PNG_EXIF_SOURCE),
        )
    tags = _tiff_inspection_tags(
        inspection,
        source_prefix=f"png-native-exif:{ascii_chunk_id(chunk.chunk_type)}:{chunk.index}",
    )
    return PngNativeMetadataRecord(
        chunk_index=chunk.index,
        chunk_type=chunk.chunk_type,
        chunk_start_offset=chunk.chunk_start_offset,
        payload_offset=chunk.payload_offset,
        metadata_kind="exif",
        tags=tags,
        evidence_ids=(PNG_NATIVE_EXIF_RUNTIME_SOURCE, PNG_EXIF_SOURCE),
    ), None


def _after_idat_warning_record(
    chunk: PngChunkPlan,
    count: int,
) -> PngNativeMetadataRecord:
    suffix = f" [x{count}]" if count > 1 else ""
    warning = (
        f"[minor] Text/EXIF chunk(s) found after PNG IDAT (may be ignored by some readers){suffix}"
    )
    return PngNativeMetadataRecord(
        chunk_index=chunk.index,
        chunk_type=chunk.chunk_type,
        chunk_start_offset=chunk.chunk_start_offset,
        payload_offset=chunk.payload_offset,
        metadata_kind="exiftool_warning",
        tags=(
            PngNativeMetadataTag(
                group="ExifTool",
                name="Warning",
                value=warning,
                table_name="Image::ExifTool",
                source=f"png-after-idat-warning:{ascii_chunk_id(chunk.chunk_type)}:{chunk.index}",
            ),
        ),
        evidence_ids=(PNG_AFTER_IDAT_WARNING_SOURCE,),
    )


def _native_icc_record(
    chunk: PngChunkPlan,
) -> tuple[PngNativeMetadataRecord | None, PngTextualRuntimeIssue | None]:
    parts = chunk.payload.split(b"\0", 1)
    if len(parts) != 2 or not parts[1]:
        return None, _issue(
            chunk,
            "native_icc_payload_decode_failed",
            "iCCP payload does not contain a profile-name separator and compression method.",
            (PNG_NATIVE_ICC_RUNTIME_SOURCE, PNG_ICC_CHUNK_SOURCE),
        )
    profile_name = parts[0].decode("latin-1", errors="replace")
    compression_method = parts[1][0]
    if compression_method != 0:
        return None, _issue(
            chunk,
            "native_icc_payload_decode_failed",
            f"iCCP uses unsupported compression method {compression_method}.",
            (PNG_NATIVE_ICC_RUNTIME_SOURCE, PNG_ICC_CHUNK_SOURCE),
        )
    try:
        profile = zlib.decompress(parts[1][1:])
    except zlib.error as exc:
        return None, _issue(
            chunk,
            "native_icc_payload_decode_failed",
            f"iCCP profile bytes could not be inflated: {exc}.",
            (PNG_NATIVE_ICC_RUNTIME_SOURCE, PNG_ICC_CHUNK_SOURCE),
        )
    try:
        from exifmodern.formats.icc.reader import parse_icc_header_tags, parse_icc_profile_tags

        values = {
            **parse_icc_header_tags(profile),
            **parse_icc_profile_tags(profile),
        }
    except ValueError as exc:
        return None, _issue(
            chunk,
            "native_icc_decode_failed",
            f"Native PNG ICC profile could not be parsed: {exc}.",
            (PNG_NATIVE_ICC_RUNTIME_SOURCE, PNG_ICC_CHUNK_SOURCE),
        )
    tags: list[PngNativeMetadataTag] = [
        PngNativeMetadataTag(
            group="PNG",
            name="ProfileName",
            value=profile_name,
            table_name="Image::ExifTool::PNG::Main",
            source=f"png-native-icc:iCCP:{chunk.index}:ProfileName",
        )
    ]
    for name, value in values.items():
        if not isinstance(value, str | int | float | bool) and value is not None:
            continue
        tags.append(
            PngNativeMetadataTag(
                group="ICC_Profile",
                name=name,
                value=value,
                table_name=_icc_table_name(name),
                source=f"png-native-icc:iCCP:{chunk.index}:{name}",
            )
        )
    return PngNativeMetadataRecord(
        chunk_index=chunk.index,
        chunk_type=chunk.chunk_type,
        chunk_start_offset=chunk.chunk_start_offset,
        payload_offset=chunk.payload_offset,
        metadata_kind="icc",
        tags=tuple(tags),
        evidence_ids=(
            PNG_NATIVE_ICC_RUNTIME_SOURCE,
            PNG_ICC_CHUNK_SOURCE,
        ),
    ), None


def _native_physical_pixel_record(
    chunk: PngChunkPlan,
) -> tuple[PngNativeMetadataRecord | None, PngTextualRuntimeIssue | None]:
    if len(chunk.payload) != 9:
        return None, _issue(
            chunk,
            "native_physical_pixel_decode_failed",
            "pHYs payload must be exactly 9 bytes: X int32u, Y int32u, and units byte.",
            (PNG_NATIVE_PHYS_RUNTIME_SOURCE, PNG_PHYS_CHUNK_SOURCE, PNG_PHYS_TABLE_SOURCE),
        )
    pixels_per_unit_x = int.from_bytes(chunk.payload[0:4], "big")
    pixels_per_unit_y = int.from_bytes(chunk.payload[4:8], "big")
    pixel_units = chunk.payload[8]
    unit_value = "meters" if pixel_units == 1 else "Unknown"
    tags = (
        PngNativeMetadataTag(
            group="PNG-pHYs",
            name="PixelsPerUnitX",
            value=pixels_per_unit_x,
            table_name="Image::ExifTool::PNG::PhysicalPixel",
            source=f"png-native-physical-pixel:pHYs:{chunk.index}:PixelsPerUnitX",
        ),
        PngNativeMetadataTag(
            group="PNG-pHYs",
            name="PixelsPerUnitY",
            value=pixels_per_unit_y,
            table_name="Image::ExifTool::PNG::PhysicalPixel",
            source=f"png-native-physical-pixel:pHYs:{chunk.index}:PixelsPerUnitY",
        ),
        PngNativeMetadataTag(
            group="PNG-pHYs",
            name="PixelUnits",
            value=unit_value,
            table_name="Image::ExifTool::PNG::PhysicalPixel",
            source=f"png-native-physical-pixel:pHYs:{chunk.index}:PixelUnits",
        ),
    )
    return PngNativeMetadataRecord(
        chunk_index=chunk.index,
        chunk_type=chunk.chunk_type,
        chunk_start_offset=chunk.chunk_start_offset,
        payload_offset=chunk.payload_offset,
        metadata_kind="physical_pixel",
        tags=tags,
        evidence_ids=(
            PNG_NATIVE_PHYS_RUNTIME_SOURCE,
            PNG_PHYS_CHUNK_SOURCE,
            PNG_PHYS_TABLE_SOURCE,
        ),
    ), None


def _tiff_inspection_tags(
    inspection: JsonObject,
    *,
    source_prefix: str,
) -> tuple[PngNativeMetadataTag, ...]:
    tags: list[PngNativeMetadataTag] = []
    for group, values_key in (
        ("IFD0", "ifd0_values"),
        ("ExifIFD", "exif_ifd_values"),
        ("GPS", "gps_ifd_values"),
        ("IFD1", "ifd1_values"),
    ):
        values = inspection.get(values_key)
        if not isinstance(values, dict):
            continue
        for name, value in values.items():
            nested_value = _json_scalar_or_string_list(value)
            if nested_value is None:
                continue
            tags.append(
                PngNativeMetadataTag(
                    group=group,
                    name=name,
                    value=nested_value,
                    table_name=_exif_table_name(group),
                    source=f"{source_prefix}:{name}",
                )
            )
    return tuple(tags)


def _runtime_record_from_payload(
    chunk: PngChunkPlan,
    route: PngReadMetadataRoute,
    parsed: _ParsedTextualPayload,
) -> tuple[PngTextualChunkRecord, PngTextualRuntimeIssue | None]:
    nested_raw_profile, profile_issue = _nested_textual_subdirectory_result(chunk, route, parsed)
    return PngTextualChunkRecord(
        chunk_index=chunk.index,
        chunk_type=chunk.chunk_type,
        chunk_start_offset=chunk.chunk_start_offset,
        payload_offset=chunk.payload_offset,
        keyword=parsed.keyword,
        tag_name=route.textual_tag_name,
        metadata_kind=route.metadata_kind,
        text_route=route.text_route if route.text_route is not None else "tEXt",
        textual_keyword_source=route.textual_keyword_source
        if route.textual_keyword_source is not None
        else "arbitrary_textual_keyword",
        textual_storage_family=route.textual_storage_family,
        textual_registered=route.textual_registered,
        textual_subdirectory=route.textual_subdirectory,
        textual_non_standard=route.textual_non_standard,
        textual_duplicate_variant_indexes=route.textual_duplicate_variant_indexes,
        language_code=parsed.language_code,
        translated_keyword=parsed.translated_keyword,
        compressed=parsed.compressed,
        compression_method=parsed.compression_method,
        value=parsed.value,
        value_encoding=parsed.value_encoding,
        text=parsed.value.decode(parsed.value_encoding, errors="replace"),
        nested_raw_profile=nested_raw_profile,
        evidence_ids=unique_sources(
            (
                *route.evidence_ids,
                *parsed.evidence_ids,
                PNG_TEXT_RUNTIME_ARBITRARY_SOURCE,
                *(
                    (PNG_TEXT_RUNTIME_PROFILE_SOURCE,)
                    if route.textual_storage_family == "raw_profile_keyword"
                    else ()
                ),
                *(nested_raw_profile.evidence_ids if nested_raw_profile is not None else ()),
            )
        ),
    ), profile_issue


def _nested_textual_subdirectory_result(
    chunk: PngChunkPlan,
    route: PngReadMetadataRoute,
    parsed: _ParsedTextualPayload,
) -> tuple[PngRawProfileNestedResult | None, PngTextualRuntimeIssue | None]:
    if (
        route.textual_storage_family != "raw_profile_keyword"
        and route.textual_subdirectory == "Image::ExifTool::XMP::Main"
    ):
        return _standard_xmp_itxt_result(chunk, parsed)
    if route.textual_storage_family != "raw_profile_keyword":
        return None, None
    if route.textual_subdirectory not in {
        "Image::ExifTool::Exif::Main",
        "Image::ExifTool::ICC_Profile::Main",
        "Image::ExifTool::Photoshop::Main",
        "Image::ExifTool::XMP::Main",
    }:
        return None, _issue(
            chunk,
            "unsupported_raw_profile_type",
            (
                "Raw profile keyword is not promoted by this nested adapter slice: "
                f"{route.textual_subdirectory}."
            ),
            (PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
        )
    decoded = _decode_raw_profile_container(chunk, parsed.value)
    if isinstance(decoded, PngTextualRuntimeIssue):
        return None, decoded
    if route.textual_subdirectory == "Image::ExifTool::Exif::Main":
        return _exif_nested_raw_profile_result(chunk, parsed, decoded)
    if route.textual_subdirectory == "Image::ExifTool::ICC_Profile::Main":
        return _icc_nested_raw_profile_result(chunk, parsed, decoded)
    if route.textual_subdirectory == "Image::ExifTool::Photoshop::Main":
        return _photoshop_nested_raw_profile_result(chunk, parsed, decoded)
    return _xmp_nested_raw_profile_result(chunk, parsed, decoded)


def _standard_xmp_itxt_result(
    chunk: PngChunkPlan,
    parsed: _ParsedTextualPayload,
) -> tuple[PngRawProfileNestedResult | None, PngTextualRuntimeIssue | None]:
    try:
        from exifmodern.formats.xmp.reader import parse_xmp_packet

        groups = parse_xmp_packet(parsed.value)
    except SyntaxError, ValueError:
        return None, None
    tags: list[PngRawProfileNestedTag] = []
    for group, values in groups.items():
        for name, value in values.items():
            if group == "XMP-rdf" and name == "About":
                continue
            nested_value = _xmp_nested_tag_value(value)
            if nested_value is None:
                continue
            tags.append(
                PngRawProfileNestedTag(
                    group=group,
                    name=name,
                    value=nested_value,
                    table_name=_xmp_table_name(group),
                    source=f"png-standard-xmp-itxt:{parsed.keyword}:{chunk.index}:{name}",
                )
            )
    return PngRawProfileNestedResult(
        kind="xmp",
        profile_type="standard XMP iTXt",
        declared_length=len(parsed.value),
        decoded_length=len(parsed.value),
        tags=tuple(tags),
        evidence_ids=(PNG_TEXT_RUNTIME_ITXT_SOURCE, PNG_XMP_SOURCE),
    ), None


def _exif_nested_raw_profile_result(
    chunk: PngChunkPlan,
    parsed: _ParsedTextualPayload,
    decoded: _DecodedRawProfileContainer,
) -> tuple[PngRawProfileNestedResult | None, PngTextualRuntimeIssue | None]:
    if decoded.payload.startswith(PNG_XMP_APP1_PREFIX):
        return _xmp_nested_raw_profile_result(
            chunk,
            parsed,
            _DecodedRawProfileContainer(
                profile_type=decoded.profile_type,
                declared_length=decoded.declared_length,
                payload=decoded.payload[len(PNG_XMP_APP1_PREFIX) :],
            ),
        )
    from exifmodern.formats.jpeg.exif_app1 import EXIF_APP1_PREFIX
    from exifmodern.formats.tiff.primitives import inspect_ifd0

    tiff_payload = decoded.payload.removeprefix(EXIF_APP1_PREFIX)
    try:
        inspection = inspect_ifd0(tiff_payload)
    except ValueError as exc:
        return None, _issue(
            chunk,
            "nested_raw_profile_decode_failed",
            f"Decoded EXIF raw profile could not be parsed as APP1 EXIF or TIFF: {exc}.",
            (PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
        )

    tags: list[PngRawProfileNestedTag] = []
    for group, values_key in (
        ("IFD0", "ifd0_values"),
        ("ExifIFD", "exif_ifd_values"),
        ("GPS", "gps_ifd_values"),
        ("IFD1", "ifd1_values"),
    ):
        values = inspection.get(values_key)
        if not isinstance(values, dict):
            continue
        for name, value in values.items():
            nested_value = _json_scalar_or_string_list(value)
            if nested_value is None:
                continue
            tags.append(
                PngRawProfileNestedTag(
                    group=group,
                    name=name,
                    value=nested_value,
                    table_name=_exif_table_name(group),
                    source=f"png-raw-profile:{parsed.keyword}:{chunk.index}:{name}",
                )
            )
    return PngRawProfileNestedResult(
        kind="exif",
        profile_type=decoded.profile_type,
        declared_length=decoded.declared_length,
        decoded_length=len(decoded.payload),
        tags=tuple(tags),
        evidence_ids=(PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
    ), None


def _icc_nested_raw_profile_result(
    chunk: PngChunkPlan,
    parsed: _ParsedTextualPayload,
    decoded: _DecodedRawProfileContainer,
) -> tuple[PngRawProfileNestedResult | None, PngTextualRuntimeIssue | None]:
    try:
        from exifmodern.formats.icc.reader import parse_icc_header_tags, parse_icc_profile_tags

        values = {
            **parse_icc_header_tags(decoded.payload),
            **parse_icc_profile_tags(decoded.payload),
        }
    except ValueError as exc:
        return None, _issue(
            chunk,
            "nested_raw_profile_decode_failed",
            f"Decoded ICC raw profile could not be parsed: {exc}.",
            (PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
        )
    tags: list[PngRawProfileNestedTag] = []
    for name, value in values.items():
        if not isinstance(value, str | int | float | bool) and value is not None:
            continue
        tags.append(
            PngRawProfileNestedTag(
                group="ICC_Profile",
                name=name,
                value=value,
                table_name=_icc_table_name(name),
                source=f"png-raw-profile:{parsed.keyword}:{chunk.index}:{name}",
            )
        )
    return PngRawProfileNestedResult(
        kind="icc",
        profile_type=decoded.profile_type,
        declared_length=decoded.declared_length,
        decoded_length=len(decoded.payload),
        tags=tuple(tags),
        evidence_ids=(PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
    ), None


def _xmp_nested_raw_profile_result(
    chunk: PngChunkPlan,
    parsed: _ParsedTextualPayload,
    decoded: _DecodedRawProfileContainer,
) -> tuple[PngRawProfileNestedResult | None, PngTextualRuntimeIssue | None]:
    try:
        from exifmodern.formats.xmp.reader import parse_xmp_packet

        groups = parse_xmp_packet(decoded.payload)
    except (SyntaxError, ValueError) as exc:
        return None, _issue(
            chunk,
            "nested_raw_profile_decode_failed",
            f"Decoded XMP raw profile could not be parsed: {exc}.",
            (PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
        )
    tags: list[PngRawProfileNestedTag] = []
    for group, values in groups.items():
        for name, value in values.items():
            nested_value = _xmp_nested_tag_value(value)
            if nested_value is None:
                continue
            tags.append(
                PngRawProfileNestedTag(
                    group=group,
                    name=name,
                    value=nested_value,
                    table_name=_xmp_table_name(group),
                    source=f"png-raw-profile:{parsed.keyword}:{chunk.index}:{name}",
                )
            )
    return PngRawProfileNestedResult(
        kind="xmp",
        profile_type=decoded.profile_type,
        declared_length=decoded.declared_length,
        decoded_length=len(decoded.payload),
        tags=tuple(tags),
        evidence_ids=(PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
    ), None


def _photoshop_nested_raw_profile_result(
    chunk: PngChunkPlan,
    parsed: _ParsedTextualPayload,
    decoded: _DecodedRawProfileContainer,
) -> tuple[PngRawProfileNestedResult | None, PngTextualRuntimeIssue | None]:
    from exifmodern.formats.photoshop.image_resources import PhotoshopImageResourceError

    payload = decoded.payload
    is_iptc_profile = parsed.keyword == "Raw profile type iptc"
    if is_iptc_profile and payload.startswith(b"\x1c"):
        kind: PngRawProfileNestedKind = "iptc"
    else:
        try:
            iptc_resource = _iptc_resource_from_photoshop_irb(payload)
        except PhotoshopImageResourceError as exc:
            return None, _issue(
                chunk,
                "nested_raw_profile_decode_failed",
                (
                    "Decoded Photoshop-routed raw profile could not be parsed as "
                    f"Photoshop IRB: {exc}."
                ),
                (PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
            )
        if iptc_resource is None:
            return None, _issue(
                chunk,
                "unsupported_raw_profile_type",
                (
                    "Decoded Photoshop-routed raw profile followed ProcessProfile's IRB branch, "
                    "but no Photoshop IPTCData resource 0x0404 was present for the existing "
                    "IPTC reader adapter."
                ),
                (PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
            )
        payload = iptc_resource
        kind = "iptc" if is_iptc_profile else "photoshop"

    from exifmodern.formats.iptc.reader import parse_iptc_application_record

    values = parse_iptc_application_record(payload)
    tags: list[PngRawProfileNestedTag] = []
    for name, value in values.items():
        nested_value = _json_scalar_or_string_list(value)
        if nested_value is None:
            continue
        tags.append(
            PngRawProfileNestedTag(
                group="IPTC",
                name=name,
                value=nested_value,
                table_name=_iptc_table_name(name),
                source=f"png-raw-profile:{parsed.keyword}:{chunk.index}:{name}",
            )
        )
    return PngRawProfileNestedResult(
        kind=kind,
        profile_type=decoded.profile_type,
        declared_length=decoded.declared_length,
        decoded_length=len(decoded.payload),
        tags=tuple(tags),
        evidence_ids=(PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
    ), None


def _iptc_resource_from_photoshop_irb(payload: bytes) -> bytes | None:
    from exifmodern.formats.photoshop.image_resources import parse_image_resource_blocks
    from exifmodern.formats.photoshop.nested_metadata_plan import (
        PHOTOSHOP_RESOURCE_ID_IPTC_DATA,
    )

    for block in parse_image_resource_blocks(payload):
        if block.resource_id == PHOTOSHOP_RESOURCE_ID_IPTC_DATA:
            return block.data
    return None


def _exif_table_name(group: str) -> str:
    if group == "ExifIFD":
        return "Image::ExifTool::Exif::ExifIFD"
    if group == "GPS":
        return "Image::ExifTool::GPS::Main"
    return "Image::ExifTool::Exif::Main"


def _icc_table_name(name: str) -> str:
    if name in {
        "ProfileCopyright",
        "ProfileDescription",
        "MediaWhitePoint",
        "MediaBlackPoint",
        "RedTRC",
        "GreenTRC",
        "BlueTRC",
        "RedMatrixColumn",
        "GreenMatrixColumn",
        "BlueMatrixColumn",
    }:
        return "Image::ExifTool::ICC_Profile::Main"
    return "Image::ExifTool::ICC_Profile::Header"


def _iptc_table_name(name: str) -> str:
    from exifmodern.formats.iptc.reader import IPTC_APPLICATION_TAGS, IPTC_ENVELOPE_TAGS

    if name in {tag_name for tag_name in IPTC_ENVELOPE_TAGS.values()}:
        return "Image::ExifTool::IPTC::EnvelopeRecord"
    if name in {tag_name for tag_name in IPTC_APPLICATION_TAGS.values()}:
        return "Image::ExifTool::IPTC::ApplicationRecord"
    return "Image::ExifTool::IPTC::Main"


def _json_scalar_or_string_list(value: JsonValue) -> PngRawProfileNestedTagValue | None:
    if isinstance(value, dict):
        return None
    if isinstance(value, list):
        return json_string_array_or_none(value)
    return value


def _xmp_nested_tag_value(value: JsonValue) -> PngRawProfileNestedTagValue | None:
    return _json_scalar_or_string_list(value)


@dataclass(frozen=True)
class _DecodedRawProfileContainer:
    profile_type: str
    declared_length: int
    payload: bytes


def _decode_raw_profile_container(
    chunk: PngChunkPlan,
    value: bytes,
) -> _DecodedRawProfileContainer | PngTextualRuntimeIssue:
    parts = value.split(b"\n", 3)
    if len(parts) != 4 or parts[0] != b"":
        return _issue(
            chunk,
            "malformed_raw_profile",
            "Raw profile payload does not match ExifTool's newline-delimited header.",
            (PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
        )
    length_text = parts[2].strip()
    if not length_text.isdigit():
        return _issue(
            chunk,
            "malformed_raw_profile",
            "Raw profile declared length is not decimal ASCII.",
            (PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
        )
    try:
        hex_text = b"".join(parts[3].split()).decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        return _issue(
            chunk,
            "malformed_raw_profile",
            f"Raw profile hex payload is not ASCII: {exc}.",
            (PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
        )
    if len(hex_text) % 2:
        hex_text += "0"
    try:
        payload = bytes.fromhex(hex_text)
    except ValueError as exc:
        return _issue(
            chunk,
            "malformed_raw_profile",
            f"Raw profile hex payload could not be decoded: {exc}.",
            (PNG_TEXT_RUNTIME_PROFILE_SOURCE,),
        )
    return _DecodedRawProfileContainer(
        profile_type=parts[1].decode("latin-1", errors="replace"),
        declared_length=int(length_text),
        payload=payload,
    )


def _xmp_table_name(group: str) -> str:
    if group.startswith("XMP-"):
        return f"Image::ExifTool::XMP::{group[4:]}"
    return "Image::ExifTool::XMP::Main"


def _parse_textual_payload(chunk: PngChunkPlan) -> _ParsedTextualPayload | PngTextualRuntimeIssue:
    if chunk.chunk_type == b"tEXt":
        return _parse_text_payload(chunk)
    if chunk.chunk_type == b"zTXt":
        return _parse_ztxt_payload(chunk)
    return _parse_itxt_payload(chunk)


def _parse_text_payload(chunk: PngChunkPlan) -> _ParsedTextualPayload | PngTextualRuntimeIssue:
    parts = chunk.payload.split(b"\0", 1)
    if len(parts) != 2:
        return _issue(
            chunk,
            "missing_text_separator",
            "tEXt payload does not contain the keyword/value NUL separator.",
            (PNG_TEXT_RUNTIME_TEXT_SOURCE,),
        )
    return _parsed(
        keyword=parts[0],
        value=parts[1],
        value_encoding="latin-1",
        evidence_ids=(PNG_TEXT_RUNTIME_TEXT_SOURCE,),
    )


def _parse_ztxt_payload(chunk: PngChunkPlan) -> _ParsedTextualPayload | PngTextualRuntimeIssue:
    parts = chunk.payload.split(b"\0", 1)
    if len(parts) != 2:
        return _issue(
            chunk,
            "missing_text_separator",
            "zTXt payload does not contain the keyword/compressed-data NUL separator.",
            (PNG_TEXT_RUNTIME_COMPRESSED_SOURCE,),
        )
    if not parts[1]:
        return _issue(
            chunk,
            "missing_compression_method",
            "zTXt payload does not contain the compression method byte.",
            (PNG_TEXT_RUNTIME_COMPRESSED_SOURCE,),
        )
    compression_method = parts[1][0]
    if compression_method != 0:
        return _issue(
            chunk,
            "unsupported_compression_method",
            f"zTXt compression method {compression_method} is not promoted by this helper.",
            (PNG_TEXT_RUNTIME_COMPRESSED_SOURCE,),
        )
    compressed_value = parts[1][1:]
    try:
        value = zlib.decompress(compressed_value)
    except zlib.error as exc:
        return _issue(
            chunk,
            "compressed_payload_decode_failed",
            f"zTXt compressed payload could not be decompressed: {exc}.",
            (PNG_TEXT_RUNTIME_COMPRESSED_SOURCE,),
        )
    return _parsed(
        keyword=parts[0],
        value=value,
        value_encoding="latin-1",
        compressed=True,
        compression_method=compression_method,
        evidence_ids=(PNG_TEXT_RUNTIME_COMPRESSED_SOURCE,),
    )


def _parse_itxt_payload(chunk: PngChunkPlan) -> _ParsedTextualPayload | PngTextualRuntimeIssue:
    parts = chunk.payload.split(b"\0", 1)
    if len(parts) != 2:
        return _issue(
            chunk,
            "missing_text_separator",
            "iTXt payload does not contain the keyword/header NUL separator.",
            (PNG_TEXT_RUNTIME_ITXT_SOURCE,),
        )
    if len(parts[1]) < 4:
        return _issue(
            chunk,
            "malformed_itxt_payload",
            "iTXt payload is too short to contain compression flag, method, language, and text.",
            (PNG_TEXT_RUNTIME_ITXT_SOURCE,),
        )
    compressed_flag = parts[1][0]
    compression_method = parts[1][1]
    language_translated_value = parts[1][2:].split(b"\0", 2)
    if len(language_translated_value) != 3:
        return _issue(
            chunk,
            "malformed_itxt_payload",
            "iTXt payload does not contain language, translated keyword, and text fields.",
            (PNG_TEXT_RUNTIME_ITXT_SOURCE,),
        )
    compressed = compressed_flag != 0
    if compressed and compression_method != 0:
        return _issue(
            chunk,
            "unsupported_compression_method",
            f"iTXt compression method {compression_method} is not promoted by this helper.",
            (PNG_TEXT_RUNTIME_ITXT_SOURCE,),
        )
    value = language_translated_value[2]
    if compressed:
        try:
            value = zlib.decompress(value)
        except zlib.error as exc:
            return _issue(
                chunk,
                "compressed_payload_decode_failed",
                f"iTXt compressed payload could not be decompressed: {exc}.",
                (PNG_TEXT_RUNTIME_ITXT_SOURCE,),
            )
    return _parsed(
        keyword=parts[0],
        value=value,
        value_encoding="utf-8",
        language_code=language_translated_value[0].decode("ascii", errors="replace") or None,
        translated_keyword=language_translated_value[1].decode("utf-8", errors="replace") or None,
        compressed=compressed,
        compression_method=compression_method,
        evidence_ids=(PNG_TEXT_RUNTIME_ITXT_SOURCE,),
    )


def _parsed(
    *,
    keyword: bytes,
    value: bytes,
    value_encoding: PngTextualValueEncoding,
    language_code: str | None = None,
    translated_keyword: str | None = None,
    compressed: bool = False,
    compression_method: int | None = None,
    evidence_ids: tuple[PngEvidenceId, ...],
) -> _ParsedTextualPayload:
    return _ParsedTextualPayload(
        keyword=keyword.decode("latin-1", errors="replace"),
        value=value,
        value_encoding=value_encoding,
        language_code=language_code,
        translated_keyword=translated_keyword,
        compressed=compressed,
        compression_method=compression_method,
        evidence_ids=evidence_ids,
    )


def _issue(
    chunk: PngChunkPlan,
    code: PngTextualRuntimeIssueCode,
    reason: str,
    evidence_ids: tuple[PngEvidenceId, ...],
) -> PngTextualRuntimeIssue:
    return PngTextualRuntimeIssue(
        chunk_index=chunk.index,
        chunk_type=chunk.chunk_type,
        code=code,
        reason=reason,
        evidence_ids=evidence_ids,
    )
