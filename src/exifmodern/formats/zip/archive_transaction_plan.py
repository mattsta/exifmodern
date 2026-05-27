"""Source-backed, non-mutating ZIP archive transaction plans.

The planner mirrors the ZIP responsibilities in ExifTool's ``ZIP.pm`` without
mutating files. It validates local file headers, central directory records and
EOCD state, enumerates archive entries, routes ZIP-delegated metadata documents,
preserves unknown entries, and keeps byte emission behind explicit gates.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.read_graph import TagProvenance

LOCAL_FILE_HEADER_SIGNATURE = b"PK\x03\x04"
CENTRAL_DIRECTORY_SIGNATURE = b"PK\x01\x02"
END_OF_CENTRAL_DIRECTORY_SIGNATURE = b"PK\x05\x06"
ZIP64_EXTRA_FIELD_ID = 0x0001

LOCAL_FILE_HEADER_SIZE = 30
CENTRAL_DIRECTORY_HEADER_SIZE = 46
END_OF_CENTRAL_DIRECTORY_SIZE = 22
ZIP_UINT16_MAX = 0xFFFF
ZIP_UINT32_MAX = 0xFFFFFFFF

OPEN_DOCUMENT_MIME_TYPES: dict[str, str] = {
    "application/vnd.oasis.opendocument.database": "ODB",
    "application/vnd.oasis.opendocument.chart": "ODC",
    "application/vnd.oasis.opendocument.formula": "ODF",
    "application/vnd.oasis.opendocument.graphics": "ODG",
    "application/vnd.oasis.opendocument.image": "ODI",
    "application/vnd.oasis.opendocument.presentation": "ODP",
    "application/vnd.oasis.opendocument.spreadsheet": "ODS",
    "application/vnd.oasis.opendocument.text": "ODT",
    "application/vnd.adobe.indesign-idml-package": "IDML",
    "application/epub+zip": "EPUB",
}

IWORK_ENTRY_TYPES: dict[str, str] = {
    "Index/Slide.iwa": "KEY",
    "Index/Tables/DataList.iwa": "NUMBERS",
}
IWORK_EXTENSION_TYPES = frozenset(("KEY", "KTH", "NMBTEMPLATE", "NUMBERS", "PAGES"))

COMPRESSION_METHOD_NAMES: dict[int, str] = {
    0: "None",
    1: "Shrunk",
    2: "Reduced with compression factor 1",
    3: "Reduced with compression factor 2",
    4: "Reduced with compression factor 3",
    5: "Reduced with compression factor 4",
    6: "Imploded",
    7: "Tokenized",
    8: "Deflated",
    9: "Enhanced Deflate using Deflate64(tm)",
    10: "Imploded (old IBM TERSE)",
    12: "BZIP2",
    14: "LZMA (EFS)",
    18: "IBM TERSE (new)",
    19: "IBM LZ77 z Architecture (PFS)",
    96: "JPEG recompressed",
    97: "WavPack compressed",
    98: "PPMd version I, Rev 1",
}

type ZipPlanStatus = Literal["planned", "unsupported"]
type ZipMetadataFamily = Literal[
    "ooxml",
    "iwork",
    "open_document",
    "idml",
    "epub",
    "sketch",
    "generic_zip",
]
type ZipMetadataKind = Literal[
    "ooxml_content_types",
    "ooxml_docprops_xml",
    "ooxml_docprops_preview",
    "iwork_index",
    "iwork_preview",
    "open_document_mimetype",
    "open_document_metadata",
    "epub_container",
    "epub_package",
    "preview_image",
    "sketch_meta",
    "unknown",
]
type ZipEntryActionKind = Literal["preserve_entry", "preserve_unknown_entry"]
type ZipCompressionResponsibility = Literal[
    "preserve_without_recompression",
    "metadata_payload_route_supported",
    "preserve_unknown_method",
]
type ZipEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_local_file_header",
    "unsupported_local_file_header_signature",
    "truncated_local_file_header_fields",
    "missing_end_of_central_directory",
    "truncated_end_of_central_directory",
    "multi_disk_archive_blocker",
    "central_directory_offset_blocker",
    "truncated_central_directory_header",
    "unsupported_central_directory_signature",
    "truncated_central_directory_fields",
    "central_directory_entry_count_mismatch",
    "central_directory_local_header_mismatch",
    "zip64_blocker",
    "encrypted_entry_blocker",
    "data_descriptor_blocker",
]


class ZipSourceCarrier(Protocol):
    @property
    def evidence_ids(self) -> tuple[ZipSourceAnchor, ...]: ...


type ZipSourceAnchor = str


class ZipSourceId(str):
    @property
    def path(self) -> str:
        return str(self)

    @property
    def line_start(self) -> int:
        return 0

    @property
    def line_end(self) -> int:
        return 0

    @property
    def symbol(self) -> str:
        return str(self)


ZIP_METADATA_SCOPE_SOURCE_ID = "zip.archive.metadata_scope"
ZIP_OPEN_DOCUMENT_TYPE_SOURCE_ID = "zip.archive.open_document_type"
ZIP_IWORK_TABLE_SOURCE_ID = "zip.archive.iwork_table"
ZIP_MEMBER_TAG_SOURCE_ID = "zip.archive.member_tags"
ZIP_ARCHIVE_ZIP_SOURCE_ID = "zip.archive.archive_zip_path"
ZIP_OOXML_DELEGATION_SOURCE_ID = "zip.archive.ooxml_delegation"
ZIP_IWORK_DELEGATION_SOURCE_ID = "zip.archive.iwork_delegation"
ZIP_OPEN_DOCUMENT_EPUB_SOURCE_ID = "zip.archive.open_document_epub_routing"
ZIP_GENERIC_MEMBER_SOURCE_ID = "zip.archive.generic_member_enumeration"
ZIP_LOCAL_HEADER_SOURCE_ID = "zip.archive.local_header_layout"
ZIP_DATA_DESCRIPTOR_SOURCE_ID = "zip.archive.data_descriptor_warning"
ZIP_COMPRESSION_SOURCE_ID = "zip.archive.compression_printconv"
ZIP_BITFLAG_SOURCE_ID = "zip.archive.bitflag"
OOXML_DOCPROPS_SOURCE_ID = "zip.archive.ooxml_docprops_routing"
IWORK_METADATA_SOURCE_ID = "zip.archive.iwork_metadata_routing"
ZIP_NON_MUTATING_SOURCE_ID = "zip.archive.non_mutating_planner"


def _zip_source_reference(source_id: str) -> ZipSourceId:
    return ZipSourceId(source_id)


def zip_tag_provenance(
    *,
    group: str,
    table_name: str,
    tag_id: str | None,
    sources: tuple[ZipSourceAnchor, ...],
    duplicate_instance_ordinal: int | None = None,
) -> TagProvenance:
    return TagProvenance(
        group=group,
        table_name=table_name,
        tag_id=tag_id,
        source=_zip_source_reference_text(sources),
        family_0_group=group,
        family_1_group=group,
        family_2_group=group if group in {"Audio", "Video", "Image"} else None,
        duplicate_instance_ordinal=duplicate_instance_ordinal,
    )


def _zip_source_reference_text(sources: tuple[ZipSourceAnchor, ...]) -> str:
    if not sources:
        return "package-local-reader-plan"
    reference = sources[0]
    return f"{reference}:0-0:{reference}"


def zip_plan_sources(carrier: ZipSourceCarrier) -> tuple[ZipSourceAnchor, ...]:
    return carrier.evidence_ids


ZIP_METADATA_SCOPE_SOURCE = _zip_source_reference(ZIP_METADATA_SCOPE_SOURCE_ID)
ZIP_OPEN_DOCUMENT_TYPE_SOURCE = _zip_source_reference(ZIP_OPEN_DOCUMENT_TYPE_SOURCE_ID)
ZIP_IWORK_TABLE_SOURCE = _zip_source_reference(ZIP_IWORK_TABLE_SOURCE_ID)
ZIP_MEMBER_TAG_SOURCE = _zip_source_reference(ZIP_MEMBER_TAG_SOURCE_ID)
ZIP_ARCHIVE_ZIP_SOURCE = _zip_source_reference(ZIP_ARCHIVE_ZIP_SOURCE_ID)
ZIP_OOXML_DELEGATION_SOURCE = _zip_source_reference(ZIP_OOXML_DELEGATION_SOURCE_ID)
ZIP_IWORK_DELEGATION_SOURCE = _zip_source_reference(ZIP_IWORK_DELEGATION_SOURCE_ID)
ZIP_OPEN_DOCUMENT_EPUB_SOURCE = _zip_source_reference(ZIP_OPEN_DOCUMENT_EPUB_SOURCE_ID)
ZIP_GENERIC_MEMBER_SOURCE = _zip_source_reference(ZIP_GENERIC_MEMBER_SOURCE_ID)
ZIP_LOCAL_HEADER_SOURCE = _zip_source_reference(ZIP_LOCAL_HEADER_SOURCE_ID)
ZIP_DATA_DESCRIPTOR_SOURCE = _zip_source_reference(ZIP_DATA_DESCRIPTOR_SOURCE_ID)
ZIP_COMPRESSION_SOURCE = _zip_source_reference(ZIP_COMPRESSION_SOURCE_ID)
ZIP_BITFLAG_SOURCE = _zip_source_reference(ZIP_BITFLAG_SOURCE_ID)
OOXML_DOCPROPS_SOURCE = _zip_source_reference(OOXML_DOCPROPS_SOURCE_ID)
IWORK_METADATA_SOURCE = _zip_source_reference(IWORK_METADATA_SOURCE_ID)
ZIP_NON_MUTATING_SOURCE = _zip_source_reference(ZIP_NON_MUTATING_SOURCE_ID)

ZIP_TRANSACTION_SOURCES = (
    ZIP_METADATA_SCOPE_SOURCE,
    ZIP_OPEN_DOCUMENT_TYPE_SOURCE,
    ZIP_IWORK_TABLE_SOURCE,
    ZIP_MEMBER_TAG_SOURCE,
    ZIP_ARCHIVE_ZIP_SOURCE,
    ZIP_OOXML_DELEGATION_SOURCE,
    ZIP_IWORK_DELEGATION_SOURCE,
    ZIP_OPEN_DOCUMENT_EPUB_SOURCE,
    ZIP_GENERIC_MEMBER_SOURCE,
    ZIP_LOCAL_HEADER_SOURCE,
    ZIP_DATA_DESCRIPTOR_SOURCE,
    ZIP_COMPRESSION_SOURCE,
    ZIP_BITFLAG_SOURCE,
)


@dataclass(frozen=True)
class ZipOutputEntry:
    file_name: str
    payload: bytes
    compression_method: int = 0
    bit_flag: int = 0
    extra_field: bytes = b""
    file_comment: bytes = b""
    version_needed: int = 20
    version_made_by: int = 20
    modified_time: int = 0
    modified_date: int = 0
    external_attributes: int = 0


@dataclass(frozen=True)
class ZipEndOfCentralDirectoryPlan:
    offset: int | None
    disk_number: int | None
    central_directory_disk: int | None
    entries_on_disk: int | None
    total_entries: int | None
    central_directory_size: int | None
    central_directory_offset: int | None
    comment: bytes
    is_valid: bool
    reason: ZipEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "central_directory_disk": self.central_directory_disk,
            "central_directory_offset": self.central_directory_offset,
            "central_directory_size": self.central_directory_size,
            "comment_hex": self.comment.hex(),
            "disk_number": self.disk_number,
            "entries_on_disk": self.entries_on_disk,
            "is_valid": self.is_valid,
            "offset": self.offset,
            "reason": self.reason,
            "total_entries": self.total_entries,
        }


@dataclass(frozen=True)
class ZipCentralDirectoryEntryPlan:
    index: int
    header_offset: int
    file_name: str
    version_needed: int
    bit_flag: int
    compression_method: int
    compression_method_name: str | None
    compression_responsibility: ZipCompressionResponsibility
    crc32: int
    compressed_size: int
    uncompressed_size: int
    local_header_offset: int
    extra_field: bytes
    file_comment: bytes
    end_offset: int
    has_zip64_marker: bool
    is_encrypted: bool
    uses_data_descriptor: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "bit_flag": self.bit_flag,
            "compressed_size": self.compressed_size,
            "compression_method": self.compression_method,
            "compression_method_name": self.compression_method_name,
            "compression_responsibility": self.compression_responsibility,
            "crc32": self.crc32,
            "end_offset": self.end_offset,
            "file_comment_hex": self.file_comment.hex(),
            "file_name": self.file_name,
            "has_zip64_marker": self.has_zip64_marker,
            "header_offset": self.header_offset,
            "index": self.index,
            "is_encrypted": self.is_encrypted,
            "local_header_offset": self.local_header_offset,
            "uncompressed_size": self.uncompressed_size,
            "uses_data_descriptor": self.uses_data_descriptor,
            "version_needed": self.version_needed,
        }


@dataclass(frozen=True)
class ZipLocalFileHeaderPlan:
    index: int
    header_offset: int
    file_name: str
    version_needed: int
    bit_flag: int
    compression_method: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    file_name_length: int
    extra_field_length: int
    payload_offset: int
    payload_end_offset: int
    next_header_offset: int
    extra_field: bytes
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "bit_flag": self.bit_flag,
            "compressed_size": self.compressed_size,
            "compression_method": self.compression_method,
            "crc32": self.crc32,
            "extra_field_length": self.extra_field_length,
            "file_name": self.file_name,
            "file_name_length": self.file_name_length,
            "header_offset": self.header_offset,
            "index": self.index,
            "next_header_offset": self.next_header_offset,
            "payload_end_offset": self.payload_end_offset,
            "payload_offset": self.payload_offset,
            "uncompressed_size": self.uncompressed_size,
            "version_needed": self.version_needed,
        }


@dataclass(frozen=True)
class ZipMetadataRoutePlan:
    file_name: str
    entry_index: int | None
    family: ZipMetadataFamily
    metadata_kind: ZipMetadataKind
    routed_payload_length: int | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "entry_index": self.entry_index,
            "family": self.family,
            "file_name": self.file_name,
            "metadata_kind": self.metadata_kind,
            "reason": self.reason,
            "routed_payload_length": self.routed_payload_length,
        }


@dataclass(frozen=True)
class ZipEntryActionPlan:
    kind: ZipEntryActionKind
    file_name: str
    source_index: int
    output_index: int
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "file_name": self.file_name,
            "kind": self.kind,
            "output_index": self.output_index,
            "reason": self.reason,
            "source_index": self.source_index,
        }


@dataclass(frozen=True)
class ZipOutputEmissionGate:
    code: ZipEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ZipArchiveTransactionPlan:
    status: ZipPlanStatus
    original_bytes: bytes
    eocd: ZipEndOfCentralDirectoryPlan
    central_directory_entries: tuple[ZipCentralDirectoryEntryPlan, ...]
    local_file_headers: tuple[ZipLocalFileHeaderPlan, ...]
    metadata_routes: tuple[ZipMetadataRoutePlan, ...]
    actions: tuple[ZipEntryActionPlan, ...]
    output_emission_gates: tuple[ZipOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"ZIP archive transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "central_directory_entries": json_object_array(
                entry.to_json() for entry in self.central_directory_entries
            ),
            "eocd": self.eocd.to_json(),
            "local_file_headers": json_object_array(
                header.to_json() for header in self.local_file_headers
            ),
            "metadata_routes": json_object_array(route.to_json() for route in self.metadata_routes),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "status": self.status,
        }


def build_zip_archive_transaction_plan(
    zip_data: bytes,
    *,
    allow_output_emission: bool = False,
) -> ZipArchiveTransactionPlan:
    gates: list[ZipOutputEmissionGate] = []
    eocd = build_zip_eocd_plan(zip_data)
    if eocd.reason is not None:
        gates.append(
            ZipOutputEmissionGate(
                eocd.reason,
                "The ZIP end of central directory cannot anchor a writable plan.",
                eocd.evidence_ids,
            )
        )
        return unsupported_zip_plan(zip_data, eocd, gates)

    central_entries, central_gates = enumerate_central_directory_entries(zip_data, eocd)
    gates.extend(central_gates)
    local_headers, local_gates = enumerate_local_file_headers(zip_data, central_entries)
    gates.extend(local_gates)
    gates.extend(mode_blockers(central_entries, eocd))
    routes = tuple(_route_entry(entry, zip_data) for entry in central_entries)
    actions = tuple(
        ZipEntryActionPlan(
            kind=(
                "preserve_unknown_entry" if route.metadata_kind == "unknown" else "preserve_entry"
            ),
            file_name=entry.file_name,
            source_index=entry.index,
            output_index=entry.index,
            reason="ZIP archive planning preserves existing entries unless a later writer acts.",
            evidence_ids=(ZIP_GENERIC_MEMBER_SOURCE,),
        )
        for entry, route in zip(central_entries, routes, strict=True)
    )
    if not allow_output_emission:
        gates.append(
            ZipOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                (
                    "ZIP archive transaction plans are non-mutating unless emission is explicitly "
                    "allowed."
                ),
                (ZIP_NON_MUTATING_SOURCE,),
            )
        )

    status: ZipPlanStatus = "unsupported" if structural_gate_exists(gates) else "planned"
    sources = unique_sources(
        (
            *ZIP_TRANSACTION_SOURCES,
            *(source for route in routes for source in route.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
        )
    )
    return ZipArchiveTransactionPlan(
        status=status,
        original_bytes=zip_data,
        eocd=eocd,
        central_directory_entries=central_entries,
        local_file_headers=local_headers,
        metadata_routes=routes,
        actions=actions,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
    )


plan_zip_archive_transaction = build_zip_archive_transaction_plan


def build_zip_eocd_plan(zip_data: bytes) -> ZipEndOfCentralDirectoryPlan:
    search_start = max(0, len(zip_data) - (ZIP_UINT16_MAX + END_OF_CENTRAL_DIRECTORY_SIZE))
    offset = zip_data.rfind(END_OF_CENTRAL_DIRECTORY_SIGNATURE, search_start)
    if offset < 0:
        return ZipEndOfCentralDirectoryPlan(
            offset=None,
            disk_number=None,
            central_directory_disk=None,
            entries_on_disk=None,
            total_entries=None,
            central_directory_size=None,
            central_directory_offset=None,
            comment=b"",
            is_valid=False,
            reason="missing_end_of_central_directory",
            evidence_ids=(ZIP_ARCHIVE_ZIP_SOURCE,),
        )
    if offset + END_OF_CENTRAL_DIRECTORY_SIZE > len(zip_data):
        return ZipEndOfCentralDirectoryPlan(
            offset=offset,
            disk_number=None,
            central_directory_disk=None,
            entries_on_disk=None,
            total_entries=None,
            central_directory_size=None,
            central_directory_offset=None,
            comment=b"",
            is_valid=False,
            reason="truncated_end_of_central_directory",
            evidence_ids=(ZIP_ARCHIVE_ZIP_SOURCE,),
        )
    comment_length = read_uint16(zip_data, offset + 20)
    comment_start = offset + END_OF_CENTRAL_DIRECTORY_SIZE
    comment_end = comment_start + comment_length
    if comment_end > len(zip_data):
        return ZipEndOfCentralDirectoryPlan(
            offset=offset,
            disk_number=None,
            central_directory_disk=None,
            entries_on_disk=None,
            total_entries=None,
            central_directory_size=None,
            central_directory_offset=None,
            comment=zip_data[comment_start:],
            is_valid=False,
            reason="truncated_end_of_central_directory",
            evidence_ids=(ZIP_ARCHIVE_ZIP_SOURCE,),
        )
    disk_number = read_uint16(zip_data, offset + 4)
    central_directory_disk = read_uint16(zip_data, offset + 6)
    entries_on_disk = read_uint16(zip_data, offset + 8)
    total_entries = read_uint16(zip_data, offset + 10)
    central_directory_size = read_uint32(zip_data, offset + 12)
    central_directory_offset = read_uint32(zip_data, offset + 16)
    reason: ZipEmissionGateCode | None = None
    if disk_number or central_directory_disk or entries_on_disk != total_entries:
        reason = "multi_disk_archive_blocker"
    elif (
        total_entries == ZIP_UINT16_MAX
        or central_directory_size == ZIP_UINT32_MAX
        or central_directory_offset == ZIP_UINT32_MAX
    ):
        reason = "zip64_blocker"
    elif central_directory_offset + central_directory_size > offset:
        reason = "central_directory_offset_blocker"
    return ZipEndOfCentralDirectoryPlan(
        offset=offset,
        disk_number=disk_number,
        central_directory_disk=central_directory_disk,
        entries_on_disk=entries_on_disk,
        total_entries=total_entries,
        central_directory_size=central_directory_size,
        central_directory_offset=central_directory_offset,
        comment=zip_data[comment_start:comment_end],
        is_valid=reason is None,
        reason=reason,
        evidence_ids=(ZIP_ARCHIVE_ZIP_SOURCE,),
    )


def enumerate_central_directory_entries(
    zip_data: bytes,
    eocd: ZipEndOfCentralDirectoryPlan,
) -> tuple[tuple[ZipCentralDirectoryEntryPlan, ...], tuple[ZipOutputEmissionGate, ...]]:
    if eocd.central_directory_offset is None or eocd.total_entries is None:
        return (), ()
    offset = eocd.central_directory_offset
    entries: list[ZipCentralDirectoryEntryPlan] = []
    gates: list[ZipOutputEmissionGate] = []
    for index in range(eocd.total_entries):
        if offset + CENTRAL_DIRECTORY_HEADER_SIZE > len(zip_data):
            gates.append(
                ZipOutputEmissionGate(
                    "truncated_central_directory_header",
                    "The central directory entry header is truncated.",
                    (ZIP_ARCHIVE_ZIP_SOURCE,),
                )
            )
            break
        if zip_data[offset : offset + 4] != CENTRAL_DIRECTORY_SIGNATURE:
            gates.append(
                ZipOutputEmissionGate(
                    "central_directory_offset_blocker",
                    (
                        "The EOCD central directory offset does not point to a central directory "
                        "record."
                    ),
                    (ZIP_ARCHIVE_ZIP_SOURCE,),
                )
            )
            gates.append(
                ZipOutputEmissionGate(
                    "unsupported_central_directory_signature",
                    "The expected central directory signature was not found.",
                    (ZIP_ARCHIVE_ZIP_SOURCE,),
                )
            )
            break
        file_name_length = read_uint16(zip_data, offset + 28)
        extra_field_length = read_uint16(zip_data, offset + 30)
        file_comment_length = read_uint16(zip_data, offset + 32)
        end_offset = (
            offset
            + CENTRAL_DIRECTORY_HEADER_SIZE
            + file_name_length
            + extra_field_length
            + file_comment_length
        )
        if end_offset > len(zip_data):
            gates.append(
                ZipOutputEmissionGate(
                    "truncated_central_directory_fields",
                    "The central directory variable fields are truncated.",
                    (ZIP_ARCHIVE_ZIP_SOURCE,),
                )
            )
            break
        name_start = offset + CENTRAL_DIRECTORY_HEADER_SIZE
        extra_start = name_start + file_name_length
        comment_start = extra_start + extra_field_length
        bit_flag = read_uint16(zip_data, offset + 8)
        method = read_uint16(zip_data, offset + 10)
        compressed_size = read_uint32(zip_data, offset + 20)
        uncompressed_size = read_uint32(zip_data, offset + 24)
        local_header_offset = read_uint32(zip_data, offset + 42)
        extra_field = zip_data[extra_start:comment_start]
        entries.append(
            ZipCentralDirectoryEntryPlan(
                index=index,
                header_offset=offset,
                file_name=decode_zip_name(zip_data[name_start:extra_start], bit_flag),
                version_needed=read_uint16(zip_data, offset + 6),
                bit_flag=bit_flag,
                compression_method=method,
                compression_method_name=COMPRESSION_METHOD_NAMES.get(method),
                compression_responsibility=compression_responsibility(method),
                crc32=read_uint32(zip_data, offset + 16),
                compressed_size=compressed_size,
                uncompressed_size=uncompressed_size,
                local_header_offset=local_header_offset,
                extra_field=extra_field,
                file_comment=zip_data[comment_start:end_offset],
                end_offset=end_offset,
                has_zip64_marker=(
                    compressed_size == ZIP_UINT32_MAX
                    or uncompressed_size == ZIP_UINT32_MAX
                    or local_header_offset == ZIP_UINT32_MAX
                    or extra_field_has_zip64(extra_field)
                ),
                is_encrypted=bool(bit_flag & 0x0001),
                uses_data_descriptor=bool(bit_flag & 0x0008),
                evidence_ids=(
                    ZIP_MEMBER_TAG_SOURCE,
                    ZIP_COMPRESSION_SOURCE,
                    ZIP_BITFLAG_SOURCE,
                ),
            )
        )
        offset = end_offset
    if len(entries) != eocd.total_entries:
        gates.append(
            ZipOutputEmissionGate(
                "central_directory_entry_count_mismatch",
                "The parsed central directory entry count differs from EOCD.",
                (ZIP_ARCHIVE_ZIP_SOURCE,),
            )
        )
    return tuple(entries), unique_gates(tuple(gates))


def enumerate_local_file_headers(
    zip_data: bytes,
    central_entries: tuple[ZipCentralDirectoryEntryPlan, ...],
) -> tuple[tuple[ZipLocalFileHeaderPlan, ...], tuple[ZipOutputEmissionGate, ...]]:
    headers: list[ZipLocalFileHeaderPlan] = []
    gates: list[ZipOutputEmissionGate] = []
    for entry in central_entries:
        offset = entry.local_header_offset
        if offset + LOCAL_FILE_HEADER_SIZE > len(zip_data):
            gates.append(
                ZipOutputEmissionGate(
                    "truncated_local_file_header",
                    f"The local header for {entry.file_name} is truncated.",
                    (ZIP_LOCAL_HEADER_SOURCE,),
                )
            )
            continue
        if zip_data[offset : offset + 4] != LOCAL_FILE_HEADER_SIGNATURE:
            gates.append(
                ZipOutputEmissionGate(
                    "unsupported_local_file_header_signature",
                    f"The local header signature for {entry.file_name} was not found.",
                    (ZIP_LOCAL_HEADER_SOURCE,),
                )
            )
            continue
        file_name_length = read_uint16(zip_data, offset + 26)
        extra_field_length = read_uint16(zip_data, offset + 28)
        payload_offset = offset + LOCAL_FILE_HEADER_SIZE + file_name_length + extra_field_length
        if payload_offset > len(zip_data):
            gates.append(
                ZipOutputEmissionGate(
                    "truncated_local_file_header_fields",
                    f"The local header fields for {entry.file_name} are truncated.",
                    (ZIP_LOCAL_HEADER_SOURCE,),
                )
            )
            continue
        name_start = offset + LOCAL_FILE_HEADER_SIZE
        extra_start = name_start + file_name_length
        payload_end_offset = payload_offset + entry.compressed_size
        if payload_end_offset > len(zip_data):
            gates.append(
                ZipOutputEmissionGate(
                    "central_directory_offset_blocker",
                    f"The central directory compressed size for {entry.file_name} points past EOF.",
                    (ZIP_LOCAL_HEADER_SOURCE, ZIP_ARCHIVE_ZIP_SOURCE),
                )
            )
            continue
        file_name = decode_zip_name(zip_data[name_start:extra_start], entry.bit_flag)
        if file_name != entry.file_name:
            gates.append(
                ZipOutputEmissionGate(
                    "central_directory_local_header_mismatch",
                    (
                        f"The local header name for {entry.file_name} does not match the central "
                        "directory."
                    ),
                    (ZIP_LOCAL_HEADER_SOURCE, ZIP_ARCHIVE_ZIP_SOURCE),
                )
            )
        headers.append(
            ZipLocalFileHeaderPlan(
                index=entry.index,
                header_offset=offset,
                file_name=file_name,
                version_needed=read_uint16(zip_data, offset + 4),
                bit_flag=read_uint16(zip_data, offset + 6),
                compression_method=read_uint16(zip_data, offset + 8),
                crc32=read_uint32(zip_data, offset + 14),
                compressed_size=read_uint32(zip_data, offset + 18),
                uncompressed_size=read_uint32(zip_data, offset + 22),
                file_name_length=file_name_length,
                extra_field_length=extra_field_length,
                payload_offset=payload_offset,
                payload_end_offset=payload_end_offset,
                next_header_offset=payload_end_offset,
                extra_field=zip_data[extra_start:payload_offset],
                evidence_ids=(ZIP_LOCAL_HEADER_SOURCE,),
            )
        )
    return tuple(headers), unique_gates(tuple(gates))


def mode_blockers(
    entries: tuple[ZipCentralDirectoryEntryPlan, ...],
    eocd: ZipEndOfCentralDirectoryPlan,
) -> tuple[ZipOutputEmissionGate, ...]:
    gates: list[ZipOutputEmissionGate] = []
    if eocd.reason == "zip64_blocker":
        gates.append(
            ZipOutputEmissionGate(
                "zip64_blocker",
                "The EOCD uses ZIP64 sentinel values, which require ZIP64 offset handling.",
                (ZIP_ARCHIVE_ZIP_SOURCE,),
            )
        )
    for entry in entries:
        if entry.has_zip64_marker:
            gates.append(
                ZipOutputEmissionGate(
                    "zip64_blocker",
                    f"{entry.file_name} uses ZIP64 size or offset markers.",
                    (ZIP_ARCHIVE_ZIP_SOURCE, ZIP_MEMBER_TAG_SOURCE),
                )
            )
        if entry.is_encrypted:
            gates.append(
                ZipOutputEmissionGate(
                    "encrypted_entry_blocker",
                    f"{entry.file_name} sets the ZIP encrypted-entry bit flag.",
                    (ZIP_BITFLAG_SOURCE, ZIP_MEMBER_TAG_SOURCE),
                )
            )
        if entry.uses_data_descriptor:
            gates.append(
                ZipOutputEmissionGate(
                    "data_descriptor_blocker",
                    f"{entry.file_name} uses stream mode data descriptors.",
                    (ZIP_DATA_DESCRIPTOR_SOURCE, ZIP_BITFLAG_SOURCE),
                )
            )
    return unique_gates(tuple(gates))


def unsupported_zip_plan(
    zip_data: bytes,
    eocd: ZipEndOfCentralDirectoryPlan,
    gates: list[ZipOutputEmissionGate],
) -> ZipArchiveTransactionPlan:
    sources = unique_sources(
        (*ZIP_TRANSACTION_SOURCES, *(source for gate in gates for source in gate.evidence_ids))
    )
    return ZipArchiveTransactionPlan(
        status="unsupported",
        original_bytes=zip_data,
        eocd=eocd,
        central_directory_entries=(),
        local_file_headers=(),
        metadata_routes=(),
        actions=(),
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
    )


def _route_entry(entry: ZipCentralDirectoryEntryPlan, zip_data: bytes) -> ZipMetadataRoutePlan:
    payload = entry_payload(zip_data, entry)
    lower_name = entry.file_name.lower()
    if entry.file_name == "[Content_Types].xml":
        return ZipMetadataRoutePlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            family="ooxml",
            metadata_kind="ooxml_content_types",
            routed_payload_length=len(payload),
            reason=(
                "[Content_Types].xml is the OOXML MIME discriminator used before DOCX delegation."
            ),
            evidence_ids=(ZIP_OOXML_DELEGATION_SOURCE,),
        )
    if re.fullmatch(r"docProps/.*\.(xml|XML)", entry.file_name):
        return ZipMetadataRoutePlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            family="ooxml",
            metadata_kind="ooxml_docprops_xml",
            routed_payload_length=len(payload),
            reason="OOXML delegates docProps XML entries to OOXML metadata parsing.",
            evidence_ids=(ZIP_OOXML_DELEGATION_SOURCE, OOXML_DOCPROPS_SOURCE),
        )
    if re.fullmatch(r"docProps/thumbnail\.(jpe?g|wmf)", entry.file_name, flags=re.IGNORECASE):
        return ZipMetadataRoutePlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            family="ooxml",
            metadata_kind="ooxml_docprops_preview",
            routed_payload_length=len(payload),
            reason="OOXML extracts docProps thumbnail previews as preview image metadata.",
            evidence_ids=(OOXML_DOCPROPS_SOURCE,),
        )
    if iwork_trigger(entry.file_name):
        kind: ZipMetadataKind = "iwork_preview" if lower_name.endswith(".jpg") else "iwork_index"
        return ZipMetadataRoutePlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            family="iwork",
            metadata_kind=kind,
            routed_payload_length=len(payload),
            reason="ZIP.pm delegates recognized iWork index and preview paths to iWork.pm.",
            evidence_ids=(ZIP_IWORK_DELEGATION_SOURCE, IWORK_METADATA_SOURCE),
        )
    if entry.file_name == "mimetype":
        mime = first_mimetype_token(payload)
        if mime == "application/epub+zip":
            family: ZipMetadataFamily = "epub"
        elif mime == "application/vnd.adobe.indesign-idml-package":
            family = "idml"
        elif mime in OPEN_DOCUMENT_MIME_TYPES:
            family = "open_document"
        else:
            family = "generic_zip"
        return ZipMetadataRoutePlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            family=family,
            metadata_kind="open_document_mimetype",
            routed_payload_length=len(payload),
            reason="ZIP.pm reads mimetype to select OpenDocument, IDML or EPUB metadata routing.",
            evidence_ids=(ZIP_OPEN_DOCUMENT_EPUB_SOURCE, ZIP_OPEN_DOCUMENT_TYPE_SOURCE),
        )
    if entry.file_name in {"meta.xml", "META-INF/metadata.xml"}:
        family = "idml" if entry.file_name == "META-INF/metadata.xml" else "open_document"
        return ZipMetadataRoutePlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            family=family,
            metadata_kind="open_document_metadata",
            routed_payload_length=len(payload),
            reason="ZIP.pm routes OpenDocument meta.xml and IDML META-INF/metadata.xml to XMP XML.",
            evidence_ids=(ZIP_OPEN_DOCUMENT_EPUB_SOURCE,),
        )
    if entry.file_name == "META-INF/container.xml":
        return ZipMetadataRoutePlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            family="epub",
            metadata_kind="epub_container",
            routed_payload_length=len(payload),
            reason="ZIP.pm reads EPUB container.xml to locate the package rootfile.",
            evidence_ids=(ZIP_OPEN_DOCUMENT_EPUB_SOURCE,),
        )
    if entry.file_name == epub_rootfile_path(zip_data):
        return ZipMetadataRoutePlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            family="epub",
            metadata_kind="epub_package",
            routed_payload_length=len(payload),
            reason="ZIP.pm routes the EPUB package rootfile selected by container.xml.",
            evidence_ids=(ZIP_OPEN_DOCUMENT_EPUB_SOURCE,),
        )
    if entry.file_name in {"Thumbnails/thumbnail.jpg", "Thumbnails/thumbnail.png"}:
        return ZipMetadataRoutePlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            family="open_document",
            metadata_kind="preview_image",
            routed_payload_length=len(payload),
            reason="ZIP.pm extracts OpenDocument thumbnail preview images when present.",
            evidence_ids=(ZIP_OPEN_DOCUMENT_EPUB_SOURCE,),
        )
    if entry.file_name == "meta.json" or entry.file_name == "previews/preview.png":
        return ZipMetadataRoutePlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            family="sketch",
            metadata_kind="sketch_meta" if entry.file_name == "meta.json" else "preview_image",
            routed_payload_length=len(payload),
            reason="Generic ZIP processing extracts Sketch meta.json and preview PNG entries.",
            evidence_ids=(ZIP_GENERIC_MEMBER_SOURCE,),
        )
    return ZipMetadataRoutePlan(
        file_name=entry.file_name,
        entry_index=entry.index,
        family="generic_zip",
        metadata_kind="unknown",
        routed_payload_length=None,
        reason="Entry is not metadata-routed by ZIP.pm and is preserved as an unknown member.",
        evidence_ids=(ZIP_GENERIC_MEMBER_SOURCE,),
    )


def enumerate_central_directory_entries_no_gates(
    zip_data: bytes,
) -> tuple[ZipCentralDirectoryEntryPlan, ...]:
    eocd = build_zip_eocd_plan(zip_data)
    entries, _gates = enumerate_central_directory_entries(zip_data, eocd)
    return entries


def iwork_trigger(file_name: str) -> bool:
    if file_name in {"index.xml", "index.apxl", "QuickLook/Thumbnail.jpg"}:
        return True
    if re.fullmatch(r"[^/]+\.(pages|numbers|key)/Index\.(zip|xml|apxl)", file_name, re.IGNORECASE):
        return True
    if re.fullmatch(r"[^/]+/preview(-micro|-web)?\.jpg", file_name, re.IGNORECASE):
        return True
    return file_name in IWORK_ENTRY_TYPES


def entry_payload(zip_data: bytes, entry: ZipCentralDirectoryEntryPlan) -> bytes:
    offset = entry.local_header_offset
    if offset + LOCAL_FILE_HEADER_SIZE > len(zip_data):
        return b""
    file_name_length = read_uint16(zip_data, offset + 26)
    extra_field_length = read_uint16(zip_data, offset + 28)
    payload_start = offset + LOCAL_FILE_HEADER_SIZE + file_name_length + extra_field_length
    payload_end = payload_start + entry.compressed_size
    if payload_end > len(zip_data):
        return b""
    payload = zip_data[payload_start:payload_end]
    if entry.compression_method == 0:
        return payload
    return b""


def first_mimetype_token(payload: bytes) -> str | None:
    match = re.search(rb"([\x21-\xfe]+)", payload, flags=re.DOTALL)
    if match is None:
        return None
    return match.group(1).decode("latin-1").lower()


def epub_rootfile_path(zip_data: bytes) -> str | None:
    for entry in enumerate_central_directory_entries_no_gates(zip_data):
        if entry.file_name != "META-INF/container.xml":
            continue
        payload = entry_payload(zip_data, entry)
        match = re.search(rb"<rootfile\s+[^>]*?\bfull-path=(['\"])(.*?)\1", payload, re.DOTALL)
        if match is None:
            return None
        return match.group(2).decode("utf-8", errors="replace")
    return None


def compression_responsibility(method: int) -> ZipCompressionResponsibility:
    if method not in COMPRESSION_METHOD_NAMES:
        return "preserve_unknown_method"
    if method in {0, 8}:
        return "metadata_payload_route_supported"
    return "preserve_without_recompression"


def extra_field_has_zip64(extra_field: bytes) -> bool:
    offset = 0
    while offset + 4 <= len(extra_field):
        header_id = read_uint16(extra_field, offset)
        data_size = read_uint16(extra_field, offset + 2)
        if offset + 4 + data_size > len(extra_field):
            return False
        if header_id == ZIP64_EXTRA_FIELD_ID:
            return True
        offset += 4 + data_size
    return False


def encode_zip_entries(
    entries: Iterable[ZipOutputEntry],
    *,
    comment: bytes = b"",
) -> bytes:
    local_parts: list[bytes] = []
    central_parts: list[bytes] = []
    offset = 0
    for entry in entries:
        name = entry.file_name.encode("utf-8")
        bit_flag = entry.bit_flag | 0x0800
        crc = zlib.crc32(entry.payload) & ZIP_UINT32_MAX
        compressed_size = len(entry.payload)
        uncompressed_size = len(entry.payload)
        local_header = (
            LOCAL_FILE_HEADER_SIGNATURE
            + entry.version_needed.to_bytes(2, "little")
            + bit_flag.to_bytes(2, "little")
            + entry.compression_method.to_bytes(2, "little")
            + entry.modified_time.to_bytes(2, "little")
            + entry.modified_date.to_bytes(2, "little")
            + crc.to_bytes(4, "little")
            + compressed_size.to_bytes(4, "little")
            + uncompressed_size.to_bytes(4, "little")
            + len(name).to_bytes(2, "little")
            + len(entry.extra_field).to_bytes(2, "little")
            + name
            + entry.extra_field
        )
        local_parts.append(local_header + entry.payload)
        central_parts.append(
            CENTRAL_DIRECTORY_SIGNATURE
            + entry.version_made_by.to_bytes(2, "little")
            + entry.version_needed.to_bytes(2, "little")
            + bit_flag.to_bytes(2, "little")
            + entry.compression_method.to_bytes(2, "little")
            + entry.modified_time.to_bytes(2, "little")
            + entry.modified_date.to_bytes(2, "little")
            + crc.to_bytes(4, "little")
            + compressed_size.to_bytes(4, "little")
            + uncompressed_size.to_bytes(4, "little")
            + len(name).to_bytes(2, "little")
            + len(entry.extra_field).to_bytes(2, "little")
            + len(entry.file_comment).to_bytes(2, "little")
            + (0).to_bytes(2, "little")
            + (0).to_bytes(2, "little")
            + entry.external_attributes.to_bytes(4, "little")
            + offset.to_bytes(4, "little")
            + name
            + entry.extra_field
            + entry.file_comment
        )
        offset += len(local_header) + len(entry.payload)
    central_directory = b"".join(central_parts)
    entry_count = len(central_parts)
    return (
        b"".join(local_parts)
        + central_directory
        + END_OF_CENTRAL_DIRECTORY_SIGNATURE
        + (0).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + entry_count.to_bytes(2, "little")
        + entry_count.to_bytes(2, "little")
        + len(central_directory).to_bytes(4, "little")
        + offset.to_bytes(4, "little")
        + len(comment).to_bytes(2, "little")
        + comment
    )


def read_uint16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def read_uint32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def decode_zip_name(raw_name: bytes, bit_flag: int) -> str:
    encoding = "utf-8" if bit_flag & 0x0800 else "cp437"
    return raw_name.decode(encoding, errors="replace")


def structural_gate_exists(gates: list[ZipOutputEmissionGate]) -> bool:
    return any(gate.code != "non_mutating_plan_requires_explicit_emission" for gate in gates)


def unique_gates(gates: tuple[ZipOutputEmissionGate, ...]) -> tuple[ZipOutputEmissionGate, ...]:
    seen: set[tuple[ZipEmissionGateCode, str]] = set()
    unique: list[ZipOutputEmissionGate] = []
    for gate in gates:
        key = (gate.code, gate.reason)
        if key not in seen:
            seen.add(key)
            unique.append(gate)
    return tuple(unique)


def unique_sources(sources: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        if source not in seen:
            seen.add(source)
            unique.append(source)
    return tuple(unique)


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return list(values)


install_evidence_reference_compat(globals())
