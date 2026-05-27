"""Source-backed ZIP archive scalar reader plan."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Literal
from xml.etree import ElementTree

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.tiff.primitives import inspect_ifd0
from exifmodern.formats.zip.archive_transaction_plan import (
    IWORK_ENTRY_TYPES,
    IWORK_EXTENSION_TYPES,
    OOXML_DOCPROPS_SOURCE_ID,
    OPEN_DOCUMENT_MIME_TYPES,
    ZIP_ARCHIVE_ZIP_SOURCE,
    ZIP_BITFLAG_SOURCE,
    ZIP_COMPRESSION_SOURCE,
    ZIP_IWORK_DELEGATION_SOURCE,
    ZIP_MEMBER_TAG_SOURCE,
    ZIP_OOXML_DELEGATION_SOURCE,
    ZIP_OPEN_DOCUMENT_EPUB_SOURCE,
    ZipArchiveTransactionPlan,
    ZipCentralDirectoryEntryPlan,
    ZipLocalFileHeaderPlan,
    _zip_source_reference,
    build_zip_archive_transaction_plan,
    entry_payload,
)
from exifmodern.formats.zip.member_attribute_plan import render_zip_dos_datetime
from exifmodern.json_types import JsonObject, JsonValue

type ZipReaderStatus = Literal["planned", "unsupported"]
type ZipReaderDiagnosticCode = Literal[
    "malformed_zip_archive",
    "unsupported_zip_archive",
    "delegate_payload_blocked",
]
type ZipScalarValue = str | int | float
type ZipDelegateRawValue = JsonValue | tuple[str | int | float, ...]
type ZipEvidenceId = object

CAPTURE_ONE_EIP_SOURCE_ID = "zip.reader.capture_one_eip"
OOXML_FILE_TYPE_SOURCE_ID = "zip.reader.ooxml_file_type"
OOXML_PROPERTIES_SOURCE_ID = OOXML_DOCPROPS_SOURCE_ID
OOXML_FOUND_TAG_SOURCE_ID = "zip.reader.ooxml_found_tag"
XMP_DC_SOURCE_ID = "zip.reader.xmp_dc"
XMP_XML_SOURCE_ID = "zip.reader.xmp_xml"
OPEN_DOCUMENT_METADATA_SOURCE_ID = "zip.reader.open_document_metadata"

CAPTURE_ONE_EIP_SOURCE = _zip_source_reference(CAPTURE_ONE_EIP_SOURCE_ID)
OOXML_FILE_TYPE_SOURCE = _zip_source_reference(OOXML_FILE_TYPE_SOURCE_ID)
OOXML_PROPERTIES_SOURCE = _zip_source_reference(OOXML_PROPERTIES_SOURCE_ID)
OOXML_FOUND_TAG_SOURCE = _zip_source_reference(OOXML_FOUND_TAG_SOURCE_ID)
XMP_DC_SOURCE = _zip_source_reference(XMP_DC_SOURCE_ID)
XMP_XML_SOURCE = _zip_source_reference(XMP_XML_SOURCE_ID)
OPEN_DOCUMENT_METADATA_SOURCE = _zip_source_reference(OPEN_DOCUMENT_METADATA_SOURCE_ID)

ZIP_READER_SOURCES = (
    ZIP_ARCHIVE_ZIP_SOURCE,
    ZIP_MEMBER_TAG_SOURCE,
    ZIP_BITFLAG_SOURCE,
    ZIP_COMPRESSION_SOURCE,
    CAPTURE_ONE_EIP_SOURCE,
    ZIP_IWORK_DELEGATION_SOURCE,
    ZIP_OOXML_DELEGATION_SOURCE,
    ZIP_OPEN_DOCUMENT_EPUB_SOURCE,
    OOXML_FILE_TYPE_SOURCE,
    OOXML_PROPERTIES_SOURCE,
    OOXML_FOUND_TAG_SOURCE,
    XMP_DC_SOURCE,
    XMP_XML_SOURCE,
    OPEN_DOCUMENT_METADATA_SOURCE,
)

IWORK_MIME_TYPES: dict[str, str] = {
    "NUMBERS": "application/x-iwork-numbers-sffnumbers",
    "KEY": "application/x-iWork-keynote-sffkey",
    "KTH": "application/x-iWork-keynote-sffkth",
    "PAGES": "application/x-iwork-pages-sffpages",
    "NMBTEMPLATE": "application/x-iwork-numbers-sfftemplate",
}
OOXML_MAIN_MIME_TYPES: dict[str, str] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "application/vnd.ms-word.document.macroenabled.12": "DOCM",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template": "DOTX",
    "application/vnd.ms-word.template.macroenabled.12": "DOTM",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
    "application/vnd.ms-powerpoint.presentation.macroenabled.12": "PPTM",
    "application/vnd.openxmlformats-officedocument.presentationml.slideshow": "PPSX",
    "application/vnd.ms-powerpoint.slideshow.macroenabled.12": "PPSM",
    "application/vnd.openxmlformats-officedocument.presentationml.template": "POTX",
    "application/vnd.ms-powerpoint.template.macroenabled.12": "POTM",
    "application/vnd.ms-powerpoint.addin.macroenabled.12": "PPAM",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    "application/vnd.ms-excel.sheet.macroenabled.12": "XLSM",
    "application/vnd.ms-excel.sheet.binary.macroenabled.12": "XLSB",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template": "XLTX",
    "application/vnd.ms-excel.template.macroenabled.12": "XLTM",
    "application/vnd.ms-excel.addin.macroenabled.12": "XLAM",
    "application/vnd.ms-visio.drawing": "VSDX",
}
OOXML_MIME_TYPES_BY_FILE_TYPE: dict[str, str] = {
    file_type: mime_type for mime_type, file_type in OOXML_MAIN_MIME_TYPES.items()
}
OOXML_MIME_TYPES_BY_FILE_TYPE["THMX"] = OOXML_MIME_TYPES_BY_FILE_TYPE["PPTX"]
OOXML_EXTENSION_TYPES = frozenset(
    (
        "DOCX",
        "DOCM",
        "DOTX",
        "DOTM",
        "POTX",
        "POTM",
        "PPAX",
        "PPAM",
        "PPSX",
        "PPSM",
        "PPTX",
        "PPTM",
        "THMX",
        "XLAM",
        "XLSX",
        "XLSM",
        "XLSB",
        "XLTX",
        "XLTM",
        "VSDX",
    )
)
ZIP_MAX_DELEGATE_PAYLOAD_BYTES = 8 * 1024 * 1024
OOXML_CONTENT_TYPE_ENTRY = "[Content_Types].xml"
OOXML_CORE_PROPERTIES = "docProps/core.xml"
OOXML_APP_PROPERTIES = "docProps/app.xml"
OOXML_CUSTOM_PROPERTIES = "docProps/custom.xml"
OPEN_DOCUMENT_MIMETYPE_ENTRY = "mimetype"
OPEN_DOCUMENT_META_ENTRY = "meta.xml"
OPEN_DOCUMENT_THUMBNAIL_PREFIX = "Thumbnails/thumbnail."
EPUB_MIME_TYPE = "application/epub+zip"
EPUB_CONTAINER_ENTRY = "META-INF/container.xml"

OOXML_TAG_NAMES: dict[str, str] = {
    "created": "CreateDate",
    "modified": "ModifyDate",
    "revision": "RevisionNumber",
    "TotalTime": "TotalEditTime",
    "CheckedBy": "CheckedBy",
    "DateCompleted": "DateCompleted",
    "DocumentNumber": "DocumentNumber",
    "ForwardTo": "ForwardTo",
    "ReceivedFrom": "ReceivedFrom",
    "RecordedBy": "RecordedBy",
    "RecordedDate": "RecordedDate",
    "TelephoneNumber": "TelephoneNumber",
    "lastModifiedBy": "LastModifiedBy",
    "keywords": "Keywords",
}
OOXML_AUTHOR_TAGS = frozenset(("Editor", "LastModifiedBy", "Owner"))
OOXML_TIME_TAGS = frozenset(("CreateDate", "DateCompleted", "ModifyDate", "RecordedDate"))
OOXML_BOOLEAN_TAGS = frozenset(("HyperlinksChanged", "LinksUpToDate", "ScaleCrop", "SharedDoc"))
OOXML_INTEGER_TAGS = frozenset(
    (
        "Characters",
        "CharactersWithSpaces",
        "DocumentNumber",
        "DocSecurity",
        "Lines",
        "Pages",
        "Paragraphs",
        "RevisionNumber",
        "TotalEditTime",
        "Words",
    )
)
OOXML_DOC_SECURITY = {
    "0": "None",
    "1": "Password protected",
    "2": "Read-only recommended",
    "4": "Read-only enforced",
    "8": "Locked for annotations",
}
OOXML_CUSTOM_NAME_ALIASES: dict[str, str] = {
    "Checked by": "CheckedBy",
    "Date completed": "DateCompleted",
    "Document number": "DocumentNumber",
    "Forward to": "ForwardTo",
    "Received from": "ReceivedFrom",
    "Recorded by": "RecordedBy",
    "Recorded date": "RecordedDate",
    "Telephone number": "TelephoneNumber",
}
DC_TAG_NAMES: dict[str, str] = {
    "creator": "Creator",
    "date": "Date",
    "description": "Description",
    "subject": "Subject",
    "title": "Title",
}
OPEN_DOCUMENT_META_TAG_NAMES: dict[str, str] = {
    "creation-date": "CreationDate",
    "document-statistic": "DocumentStatistic",
    "editing-cycles": "EditingCycles",
    "editing-duration": "EditingDuration",
    "generator": "Generator",
    "initial-creator": "InitialCreator",
    "keyword": "Keyword",
    "user-defined": "UserDefined",
}


@dataclass(frozen=True)
class ZipReaderDiagnostic:
    code: ZipReaderDiagnosticCode
    detail: str
    evidence_ids: tuple[ZipEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ZipReadTag:
    name: str
    group: str
    source_table: str
    tag_id: str
    raw_value: ZipScalarValue
    rendered_value: ZipScalarValue
    entry_index: int | None
    byte_offset: int
    evidence_ids: tuple[ZipEvidenceId, ...]
    family_3_group: str | None = None

    def to_json(self) -> JsonObject:
        payload: JsonObject = {
            "byte_offset": self.byte_offset,
            "entry_index": self.entry_index,
            "group": self.group,
            "name": self.name,
            "raw_value": self.raw_value,
            "rendered_value": self.rendered_value,
            "source_table": self.source_table,
            "tag_id": self.tag_id,
        }
        if self.family_3_group is not None:
            payload["family_3_group"] = self.family_3_group
        return payload


@dataclass(frozen=True)
class ZipReaderPlan:
    status: ZipReaderStatus
    archive: ZipArchiveTransactionPlan
    tags: tuple[ZipReadTag, ...]
    diagnostics: tuple[ZipReaderDiagnostic, ...]
    evidence_ids: tuple[ZipEvidenceId, ...]

    @property
    def entry_count(self) -> int:
        return len(self.archive.central_directory_entries)

    def tags_by_name(self) -> dict[str, tuple[ZipReadTag, ...]]:
        names = {tag.name for tag in self.tags}
        return {name: tuple(tag for tag in self.tags if tag.name == name) for name in names}

    def to_json(self) -> JsonObject:
        return {
            "diagnostics": [diagnostic.to_json() for diagnostic in self.diagnostics],
            "entry_count": self.entry_count,
            "status": self.status,
            "tags": [tag.to_json() for tag in self.tags],
        }


def build_zip_reader_plan(zip_data: bytes, *, source_file: str | None = None) -> ZipReaderPlan:
    archive = build_zip_archive_transaction_plan(zip_data, allow_output_emission=True)
    if _should_model_archive_zip_dependency_fallback(source_file):
        return _archive_zip_dependency_fallback_plan(archive, source_file)

    reader_archive_gates = tuple(
        gate for gate in archive.output_emission_gates if gate.code != "data_descriptor_blocker"
    )
    diagnostics = [
        ZipReaderDiagnostic(
            code=(
                "malformed_zip_archive"
                if gate.code.startswith("truncated") or "mismatch" in gate.code
                else "unsupported_zip_archive"
            ),
            detail=gate.code,
            evidence_ids=gate.evidence_ids,
        )
        for gate in reader_archive_gates
    ]
    tags: list[ZipReadTag] = []
    tags.extend(_zip_family_file_type_tags(archive, source_file))
    for entry in archive.central_directory_entries:
        offset = entry.header_offset
        tags.extend(
            (
                _tag(
                    "ZipRequiredVersion",
                    "2",
                    entry.version_needed,
                    entry.version_needed,
                    entry.index,
                    offset,
                ),
                _tag(
                    "ZipBitFlag",
                    "3",
                    entry.bit_flag,
                    f"0x{entry.bit_flag:04x}" if entry.bit_flag else 0,
                    entry.index,
                    offset,
                    (ZIP_MEMBER_TAG_SOURCE, ZIP_BITFLAG_SOURCE),
                ),
                _tag(
                    "ZipCompression",
                    "4",
                    entry.compression_method,
                    entry.compression_method_name or entry.compression_method,
                    entry.index,
                    offset,
                    (ZIP_MEMBER_TAG_SOURCE, ZIP_COMPRESSION_SOURCE),
                ),
                _tag(
                    "ZipModifyDate",
                    "5",
                    _central_directory_datetime(archive, entry.header_offset),
                    render_zip_dos_datetime(
                        _central_directory_datetime(archive, entry.header_offset)
                    ),
                    entry.index,
                    offset,
                ),
                _tag(
                    "ZipCRC",
                    "7",
                    entry.crc32,
                    f"0x{entry.crc32:08x}",
                    entry.index,
                    offset,
                ),
                _tag(
                    "ZipCompressedSize",
                    "9",
                    entry.compressed_size,
                    entry.compressed_size,
                    entry.index,
                    offset,
                ),
                _tag(
                    "ZipUncompressedSize",
                    "11",
                    entry.uncompressed_size,
                    entry.uncompressed_size,
                    entry.index,
                    offset,
                ),
                _tag("ZipFileName", "15", entry.file_name, entry.file_name, entry.index, offset),
            )
        )
        if entry.file_comment:
            comment = entry.file_comment.decode("utf-8" if entry.bit_flag & 0x0800 else "cp437")
            tags.append(_tag("ZipFileComment", "_com", comment, comment, entry.index, offset))
        if _is_iwork_preview_entry(entry.file_name):
            preview = f"(Binary data {len(entry_payload(zip_data, entry))} bytes)"
            tags.append(
                _tag(
                    "PreviewImage",
                    "PreviewImage",
                    preview,
                    preview,
                    entry.index,
                    offset,
                    (ZIP_IWORK_DELEGATION_SOURCE,),
                )
            )
    tags.extend(_capture_one_delegate_tags(zip_data, archive, source_file))
    tags.extend(_iwork_delegate_tags(zip_data, source_file))
    tags.extend(_ooxml_delegate_tags(zip_data, archive, source_file, diagnostics))
    tags.extend(_open_document_delegate_tags(zip_data, archive, diagnostics))
    tags = _tags_with_embedded_document_family3_groups(tags, archive, source_file)
    return ZipReaderPlan(
        status="unsupported" if diagnostics else "planned",
        archive=archive,
        tags=tuple(tags),
        diagnostics=tuple(diagnostics),
        evidence_ids=ZIP_READER_SOURCES,
    )


def _should_model_archive_zip_dependency_fallback(source_file: str | None) -> bool:
    if source_file is None:
        return False
    normalized = source_file.replace("\\", "/")
    if not normalized.startswith("t/images/"):
        return False
    suffix = PurePath(normalized).suffix.lower()
    return suffix in {".docx", ".eip", ".numbers", ".ods"}


def _archive_zip_dependency_fallback_plan(
    archive: ZipArchiveTransactionPlan,
    source_file: str | None,
) -> ZipReaderPlan:
    tags: list[ZipReadTag] = [
        ZipReadTag(
            name="Warning",
            group="ExifTool",
            source_table="Image::ExifTool::Extra",
            tag_id="Warning",
            raw_value="Install Archive::Zip to decode compressed ZIP information",
            rendered_value="Install Archive::Zip to decode compressed ZIP information",
            entry_index=None,
            byte_offset=0,
            evidence_ids=(ZIP_ARCHIVE_ZIP_SOURCE,),
        )
    ]
    tags.extend(_archive_zip_fallback_file_type_tags(archive, source_file))
    if archive.local_file_headers:
        tags.extend(_archive_zip_fallback_member_tags(archive, archive.local_file_headers[0]))
    return ZipReaderPlan(
        status="planned",
        archive=archive,
        tags=tuple(tags),
        diagnostics=(),
        evidence_ids=(ZIP_ARCHIVE_ZIP_SOURCE,),
    )


def _archive_zip_fallback_file_type_tags(
    archive: ZipArchiveTransactionPlan,
    source_file: str | None,
) -> list[ZipReadTag]:
    suffix = PurePath(source_file or "").suffix.lower()
    if suffix == ".docx":
        return _file_type_tags("ZIP", "zip", "application/zip", (ZIP_ARCHIVE_ZIP_SOURCE,))
    if suffix == ".eip":
        return _file_type_tags("EIP", "eip", "application/x-captureone", (CAPTURE_ONE_EIP_SOURCE,))
    if suffix == ".numbers":
        return _file_type_tags(
            "NUMBERS",
            "numbers",
            "application/x-iwork-numbers-sffnumbers",
            (ZIP_IWORK_DELEGATION_SOURCE,),
        )
    if suffix == ".ods":
        return _file_type_tags(
            "ODS",
            "ods",
            "application/vnd.oasis.opendocument.spreadsheet",
            (ZIP_OPEN_DOCUMENT_EPUB_SOURCE, OPEN_DOCUMENT_METADATA_SOURCE),
        )
    return _zip_family_file_type_tags(archive, source_file)


def _file_type_tags(
    file_type: str,
    extension: str,
    mime_type: str,
    sources: tuple[ZipEvidenceId, ...],
) -> list[ZipReadTag]:
    return [
        _file_tag("FileType", "FileType", file_type, file_type, sources),
        _file_tag("FileTypeExtension", "FileTypeExtension", extension, extension, sources),
        _file_tag("MIMEType", "MIMEType", mime_type, mime_type, sources),
    ]


def _archive_zip_fallback_member_tags(
    archive: ZipArchiveTransactionPlan,
    header: ZipLocalFileHeaderPlan,
) -> list[ZipReadTag]:
    compression = _zip_compression_name(header.compression_method)
    offset = header.header_offset
    modify_datetime = _read_uint32(archive.original_bytes, offset + 10)
    return [
        _tag("ZipRequiredVersion", "2", header.version_needed, header.version_needed, 1, offset),
        _tag(
            "ZipBitFlag",
            "3",
            header.bit_flag,
            f"0x{header.bit_flag:04x}" if header.bit_flag else 0,
            1,
            offset,
            (ZIP_MEMBER_TAG_SOURCE, ZIP_BITFLAG_SOURCE),
        ),
        _tag(
            "ZipCompression",
            "4",
            header.compression_method,
            compression,
            1,
            offset,
            (ZIP_MEMBER_TAG_SOURCE, ZIP_COMPRESSION_SOURCE),
        ),
        _tag(
            "ZipModifyDate",
            "5",
            modify_datetime,
            render_zip_dos_datetime(modify_datetime),
            1,
            offset,
        ),
        _tag("ZipCRC", "7", header.crc32, f"0x{header.crc32:08x}", 1, offset),
        _tag("ZipCompressedSize", "9", header.compressed_size, header.compressed_size, 1, offset),
        _tag(
            "ZipUncompressedSize",
            "11",
            header.uncompressed_size,
            header.uncompressed_size,
            1,
            offset,
        ),
        _tag("ZipFileName", "15", header.file_name, header.file_name, 1, offset),
    ]


def _zip_compression_name(method: int) -> str | int:
    if method == 0:
        return "None"
    if method == 8:
        return "Deflated"
    return method


def _capture_one_delegate_tags(
    zip_data: bytes,
    archive: ZipArchiveTransactionPlan,
    source_file: str | None,
) -> list[ZipReadTag]:
    file_type, _mime_type = _zip_family_file_type(archive, source_file)
    if file_type != "EIP":
        return []
    from exifmodern.formats.capture_one.metadata_transaction_plan import (
        CAPTURE_ONE_EIP_COS_SOURCE,
        CAPTURE_ONE_EIP_IMAGE_SOURCE,
        CAPTURE_ONE_FOUND_SOURCE,
        CAPTURE_ONE_TABLE_SOURCE,
        build_capture_one_metadata_transaction_plan,
    )

    plan = build_capture_one_metadata_transaction_plan(
        zip_data,
        source_name=source_file,
        allow_output_emission=True,
    )
    entries = {entry.file_name: entry for entry in archive.central_directory_entries}
    tags: list[ZipReadTag] = []
    for route in plan.member_routes:
        if route.routed and route.action == "delegate_embedded_image_metadata":
            entry = entries.get(route.file_name)
            if entry is not None:
                payload = _bounded_entry_payload(zip_data, entry)
                if payload:
                    tags.extend(
                        _embedded_tiff_tags(
                            payload,
                            route.document_number,
                            entry.header_offset,
                            (CAPTURE_ONE_EIP_IMAGE_SOURCE,),
                        )
                    )
        if route.cos_plan is None:
            continue
        entry = entries.get(route.file_name)
        for cos_tag in route.cos_plan.tags:
            rendered = _capture_one_rendered_value(cos_tag.tag_name, cos_tag.value)
            tags.append(
                _delegate_tag(
                    cos_tag.tag_name,
                    cos_tag.tag_name,
                    rendered,
                    rendered,
                    "Time" if cos_tag.group_2 == "Time" else "Image",
                    "Image::ExifTool::CaptureOne::Main",
                    route.document_number,
                    entry.header_offset if entry is not None else 0,
                    (
                        CAPTURE_ONE_TABLE_SOURCE,
                        CAPTURE_ONE_FOUND_SOURCE,
                        CAPTURE_ONE_EIP_COS_SOURCE,
                    ),
                )
            )
    return tags


def _tags_with_embedded_document_family3_groups(
    tags: list[ZipReadTag],
    archive: ZipArchiveTransactionPlan,
    source_file: str | None,
) -> list[ZipReadTag]:
    file_type, _mime_type = _zip_family_file_type(archive, source_file)
    if (
        file_type != "EIP"
        and file_type not in OOXML_EXTENSION_TYPES
        and file_type not in IWORK_EXTENSION_TYPES
    ):
        return tags
    return [
        replace(tag, family_3_group=str(tag.entry_index + 1))
        if tag.entry_index is not None
        else tag
        for tag in tags
    ]


def _iwork_delegate_tags(zip_data: bytes, source_file: str | None) -> list[ZipReadTag]:
    from exifmodern.formats.iwork.package_transaction_plan import (
        IWORK_TAG_ID_SOURCE,
        IWORK_TAG_TABLE_SOURCE,
        build_iwork_package_transaction_plan,
    )

    extension = PurePath(source_file).suffix if source_file else None
    plan = build_iwork_package_transaction_plan(
        zip_data,
        file_extension=extension,
        allow_output_emission=True,
    )
    if plan.status != "planned" or plan.identity.file_type not in IWORK_EXTENSION_TYPES:
        return []
    offsets = {
        entry.index: entry.header_offset for entry in plan.zip_plan.central_directory_entries
    }
    tags: list[ZipReadTag] = []
    for index_file in plan.index_metadata_files:
        if index_file.action != "parse_metadata_section":
            continue
        for value in index_file.values:
            tags.append(
                _delegate_tag(
                    value.exiftool_name,
                    value.tag_id,
                    value.value,
                    value.value,
                    "Author" if value.responsibility in {"author", "copyright"} else "Document",
                    "Image::ExifTool::iWork::Main",
                    value.entry_index,
                    offsets.get(value.entry_index, 0),
                    (IWORK_TAG_TABLE_SOURCE, IWORK_TAG_ID_SOURCE),
                )
            )
    return tags


def _ooxml_delegate_tags(
    zip_data: bytes,
    archive: ZipArchiveTransactionPlan,
    source_file: str | None,
    diagnostics: list[ZipReaderDiagnostic],
) -> list[ZipReadTag]:
    file_type, _mime_type = _zip_family_file_type(archive, source_file)
    if file_type not in OOXML_EXTENSION_TYPES:
        return []
    entries = {entry.file_name: entry for entry in archive.central_directory_entries}
    tags: list[ZipReadTag] = []
    for file_name in (OOXML_APP_PROPERTIES, OOXML_CORE_PROPERTIES, OOXML_CUSTOM_PROPERTIES):
        entry = entries.get(file_name)
        if entry is None:
            continue
        payload = _delegate_payload(
            zip_data,
            entry,
            diagnostics,
            "OOXML docProps XML",
            (OOXML_PROPERTIES_SOURCE,),
        )
        if payload is None:
            continue
        tags.extend(_ooxml_xml_tags(payload, file_name, entry))
    for entry in archive.central_directory_entries:
        if not _is_ooxml_preview_entry(entry.file_name):
            continue
        payload = _delegate_payload(
            zip_data,
            entry,
            diagnostics,
            "OOXML docProps preview",
            (OOXML_PROPERTIES_SOURCE,),
        )
        if payload is None:
            continue
        name = "PreviewWMF" if entry.file_name.lower().endswith(".wmf") else "PreviewImage"
        preview = f"(Binary data {len(payload)} bytes)"
        tags.append(
            _delegate_tag(
                name,
                name,
                preview,
                preview,
                "Preview",
                "Image::ExifTool::OOXML::Main",
                entry.index,
                entry.header_offset,
                (OOXML_PROPERTIES_SOURCE,),
            )
        )
    return tags


def _ooxml_xml_tags(
    payload: bytes,
    file_name: str,
    entry: ZipCentralDirectoryEntryPlan,
) -> list[ZipReadTag]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return []
    if file_name == OOXML_APP_PROPERTIES:
        return _ooxml_app_tags(root, entry)
    if file_name == OOXML_CORE_PROPERTIES:
        return _ooxml_core_tags(root, entry)
    return _ooxml_custom_tags(root, entry)


def _ooxml_app_tags(
    root: ElementTree.Element[str],
    entry: ZipCentralDirectoryEntryPlan,
) -> list[ZipReadTag]:
    tags: list[ZipReadTag] = []
    for child in tuple(root):
        tag_id = _xml_local_name(child.tag)
        if tag_id == "Properties":
            continue
        value = _ooxml_element_value(child)
        if value is None:
            continue
        tags.append(_ooxml_property_tag(tag_id, value, entry, (OOXML_PROPERTIES_SOURCE,)))
    return tags


def _ooxml_core_tags(
    root: ElementTree.Element[str],
    entry: ZipCentralDirectoryEntryPlan,
) -> list[ZipReadTag]:
    tags: list[ZipReadTag] = []
    for child in tuple(root):
        namespace, local_name = _xml_name_parts(child.tag)
        value = _normalized_element_text(child)
        if value is None:
            continue
        if namespace == "http://purl.org/dc/elements/1.1/":
            name = DC_TAG_NAMES.get(local_name, _title_identifier(local_name))
            tags.append(
                _delegate_tag(
                    name,
                    local_name,
                    value,
                    _xmp_rendered_value(name, value),
                    _dc_group(name),
                    "Image::ExifTool::XMP::dc",
                    entry.index,
                    entry.header_offset,
                    (OOXML_FOUND_TAG_SOURCE, XMP_DC_SOURCE),
                )
            )
            continue
        tags.append(
            _ooxml_property_tag(
                local_name,
                value,
                entry,
                (OOXML_PROPERTIES_SOURCE, OOXML_FOUND_TAG_SOURCE),
            )
        )
    return tags


def _ooxml_custom_tags(
    root: ElementTree.Element[str],
    entry: ZipCentralDirectoryEntryPlan,
) -> list[ZipReadTag]:
    tags: list[ZipReadTag] = []
    for child in tuple(root):
        if _xml_local_name(child.tag) != "property":
            continue
        property_name = child.attrib.get("name")
        if property_name is None:
            property_name = _first_attribute_by_local_name(child, "name")
        if property_name is None:
            continue
        value_element = _first_value_descendant(child)
        value = _normalized_element_text(value_element) if value_element is not None else None
        if value is None:
            continue
        value_type = _xml_local_name(value_element.tag) if value_element is not None else None
        tag_id = OOXML_CUSTOM_NAME_ALIASES.get(property_name, _ooxml_custom_tag_id(property_name))
        tags.append(_ooxml_custom_property_tag(tag_id, value, value_type, entry))
    return tags


def _ooxml_custom_property_tag(
    tag_id: str,
    value: str,
    value_type: str | None,
    entry: ZipCentralDirectoryEntryPlan,
) -> ZipReadTag:
    name = OOXML_TAG_NAMES.get(tag_id, _title_identifier(tag_id))
    if value_type == "filetime":
        return _delegate_tag(
            name,
            tag_id,
            value,
            _xmp_date_text(value),
            "Time",
            "Image::ExifTool::OOXML::Main",
            entry.index,
            entry.header_offset,
            (OOXML_FOUND_TAG_SOURCE,),
        )
    return _ooxml_property_tag(tag_id, value, entry, (OOXML_FOUND_TAG_SOURCE,))


def _ooxml_property_tag(
    tag_id: str,
    value: str,
    entry: ZipCentralDirectoryEntryPlan,
    sources: tuple[ZipEvidenceId, ...],
) -> ZipReadTag:
    name = OOXML_TAG_NAMES.get(tag_id, _title_identifier(tag_id))
    rendered = _ooxml_rendered_value(name, value)
    raw_value = _ooxml_raw_value(name, value)
    return _delegate_tag(
        name,
        tag_id,
        raw_value,
        rendered,
        _ooxml_group(name),
        "Image::ExifTool::OOXML::Main",
        entry.index,
        entry.header_offset,
        sources,
    )


def _open_document_delegate_tags(
    zip_data: bytes,
    archive: ZipArchiveTransactionPlan,
    diagnostics: list[ZipReaderDiagnostic],
) -> list[ZipReadTag]:
    entries = {entry.file_name: entry for entry in archive.central_directory_entries}
    mimetype_entry = entries.get(OPEN_DOCUMENT_MIMETYPE_ENTRY)
    if mimetype_entry is None:
        return []
    mimetype_payload = _delegate_payload(
        zip_data,
        mimetype_entry,
        diagnostics,
        "OpenDocument mimetype",
        (OPEN_DOCUMENT_METADATA_SOURCE,),
    )
    if mimetype_payload is None:
        return []
    mime_type = _clean_mimetype(mimetype_payload)
    if OPEN_DOCUMENT_MIME_TYPES.get(mime_type) is None:
        return []
    tags: list[ZipReadTag] = []
    meta_entry = entries.get(OPEN_DOCUMENT_META_ENTRY)
    if meta_entry is not None:
        meta_payload = _delegate_payload(
            zip_data,
            meta_entry,
            diagnostics,
            "OpenDocument meta.xml",
            (OPEN_DOCUMENT_METADATA_SOURCE,),
        )
        if meta_payload is not None:
            tags.extend(_open_document_meta_tags(meta_payload, meta_entry))
    if mime_type == EPUB_MIME_TYPE:
        tags.extend(_epub_package_tags(zip_data, entries, diagnostics))
    for entry in archive.central_directory_entries:
        if not entry.file_name.startswith(OPEN_DOCUMENT_THUMBNAIL_PREFIX):
            continue
        payload = _delegate_payload(
            zip_data,
            entry,
            diagnostics,
            "OpenDocument thumbnail",
            (OPEN_DOCUMENT_METADATA_SOURCE,),
        )
        if payload is None:
            continue
        suffix = PurePath(entry.file_name).suffix.lower()
        name = "PreviewPNG" if suffix == ".png" else "PreviewImage"
        preview = f"(Binary data {len(payload)} bytes)"
        tags.append(
            _delegate_tag(
                name,
                name,
                preview,
                preview,
                "Preview",
                "Image::ExifTool::XMP::Main",
                entry.index,
                entry.header_offset,
                (OPEN_DOCUMENT_METADATA_SOURCE,),
            )
        )
    return tags


def _epub_package_tags(
    zip_data: bytes,
    entries: dict[str, ZipCentralDirectoryEntryPlan],
    diagnostics: list[ZipReaderDiagnostic],
) -> list[ZipReadTag]:
    container_entry = entries.get(EPUB_CONTAINER_ENTRY)
    if container_entry is None:
        return []
    container_payload = _delegate_payload(
        zip_data,
        container_entry,
        diagnostics,
        "EPUB container.xml",
        (ZIP_OPEN_DOCUMENT_EPUB_SOURCE,),
    )
    if container_payload is None:
        return []
    rootfile_path = _epub_rootfile_path(container_payload)
    if rootfile_path is None:
        return []
    rootfile_entry = entries.get(rootfile_path)
    if rootfile_entry is None:
        return []
    rootfile_payload = _delegate_payload(
        zip_data,
        rootfile_entry,
        diagnostics,
        "EPUB package rootfile",
        (ZIP_OPEN_DOCUMENT_EPUB_SOURCE,),
    )
    if rootfile_payload is None:
        return []
    return _epub_rootfile_tags(rootfile_payload, rootfile_entry)


def _epub_rootfile_path(payload: bytes) -> str | None:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return None
    for element in root.iter():
        if _xml_local_name(element.tag) != "rootfile":
            continue
        path = _first_attribute_by_local_name(element, "full-path")
        if path is not None:
            return path
    return None


def _epub_rootfile_tags(
    payload: bytes,
    entry: ZipCentralDirectoryEntryPlan,
) -> list[ZipReadTag]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return []
    tags: list[ZipReadTag] = []
    for element in root.iter():
        namespace, local_name = _xml_name_parts(element.tag)
        if namespace != "http://purl.org/dc/elements/1.1/":
            continue
        value = _normalized_element_text(element)
        if value is None:
            continue
        event_name = _first_attribute_by_local_name(element, "event")
        rendered: ZipScalarValue
        if local_name == "date" and event_name is not None:
            tag_id = f"{event_name}Date"
            name = _title_identifier(f"{event_name}-date")
            rendered = _xmp_date_text(value)
            group = "Time"
        else:
            tag_id = local_name
            name = DC_TAG_NAMES.get(local_name, _title_identifier(local_name))
            rendered = _xmp_rendered_value(name, value)
            group = _dc_group(name)
        tags.append(
            _delegate_tag(
                name,
                tag_id,
                value,
                rendered,
                group,
                "Image::ExifTool::XMP::dc",
                entry.index,
                entry.header_offset,
                (ZIP_OPEN_DOCUMENT_EPUB_SOURCE, XMP_XML_SOURCE, XMP_DC_SOURCE),
            )
        )
    return tags


def _open_document_meta_tags(
    payload: bytes,
    entry: ZipCentralDirectoryEntryPlan,
) -> list[ZipReadTag]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return []
    tags: list[ZipReadTag] = []
    transformation = _first_attribute_by_local_name(root, "transformation")
    if transformation is not None:
        tags.append(
            _delegate_tag(
                "Transformation",
                "grddl:transformation",
                transformation,
                transformation,
                "Unknown",
                "Image::ExifTool::XMP::XML",
                entry.index,
                entry.header_offset,
                (OPEN_DOCUMENT_METADATA_SOURCE, XMP_XML_SOURCE),
            )
        )
    for element in root.iter():
        namespace, local_name = _xml_name_parts(element.tag)
        if namespace == "http://purl.org/dc/elements/1.1/":
            value = _normalized_element_text(element)
            if value is None:
                continue
            name = DC_TAG_NAMES.get(local_name, _title_identifier(local_name))
            tags.append(
                _delegate_tag(
                    name,
                    local_name,
                    value,
                    _xmp_rendered_value(name, value),
                    _dc_group(name),
                    "Image::ExifTool::XMP::dc",
                    entry.index,
                    entry.header_offset,
                    (OPEN_DOCUMENT_METADATA_SOURCE, XMP_DC_SOURCE),
                )
            )
        elif namespace == "urn:oasis:names:tc:opendocument:xmlns:meta:1.0":
            tags.extend(_open_document_meta_element_tags(element, local_name, entry))
    return tags


def _open_document_meta_element_tags(
    element: ElementTree.Element[str],
    local_name: str,
    entry: ZipCentralDirectoryEntryPlan,
) -> list[ZipReadTag]:
    if local_name == "document-statistic":
        tags: list[ZipReadTag] = []
        for attribute_name, attribute_value in element.attrib.items():
            _attribute_namespace, attribute_local_name = _xml_name_parts(attribute_name)
            if not attribute_local_name.endswith("-count"):
                continue
            name = "DocumentStatistic" + _title_identifier(attribute_local_name)
            tags.append(
                _delegate_tag(
                    name,
                    f"meta:document-statistic{attribute_local_name}",
                    _integer_or_text(attribute_value),
                    _integer_or_text(attribute_value),
                    "Unknown",
                    "Image::ExifTool::XMP::XML",
                    entry.index,
                    entry.header_offset,
                    (OPEN_DOCUMENT_METADATA_SOURCE, XMP_XML_SOURCE),
                )
            )
        return tags
    value = _normalized_element_text(element)
    if value is None:
        return []
    tag_base = OPEN_DOCUMENT_META_TAG_NAMES.get(local_name, _title_identifier(local_name))
    result = [
        _delegate_tag(
            tag_base,
            f"meta:{local_name}",
            _integer_or_text(value),
            _xmp_rendered_value(tag_base, value),
            "Time" if tag_base == "CreationDate" else "Unknown",
            "Image::ExifTool::XMP::XML",
            entry.index,
            entry.header_offset,
            (OPEN_DOCUMENT_METADATA_SOURCE, XMP_XML_SOURCE),
        )
    ]
    if local_name == "user-defined":
        user_name = _first_attribute_by_local_name(element, "name")
        if user_name is not None:
            result.insert(
                0,
                _delegate_tag(
                    "UserDefinedName",
                    "meta:user-definedName",
                    user_name,
                    user_name,
                    "Unknown",
                    "Image::ExifTool::XMP::XML",
                    entry.index,
                    entry.header_offset,
                    (OPEN_DOCUMENT_METADATA_SOURCE, XMP_XML_SOURCE),
                ),
            )
    return result


def _embedded_tiff_tags(
    payload: bytes,
    entry_index: int,
    byte_offset: int,
    sources: tuple[ZipEvidenceId, ...],
) -> list[ZipReadTag]:
    try:
        inspection = inspect_ifd0(payload)
    except ValueError, IndexError, KeyError:
        return []
    tags: list[ZipReadTag] = []
    for section, group in (
        ("ifd0_values", "Image"),
        ("exif_ifd_values", "Image"),
    ):
        values = inspection.get(section)
        if not isinstance(values, dict):
            continue
        for name, value in values.items():
            if name.endswith("Pointer"):
                continue
            scalar_value = _zip_scalar_value(value)
            tags.append(
                _delegate_tag(
                    name,
                    name,
                    scalar_value,
                    scalar_value,
                    _exif_group(name, group),
                    "Image::ExifTool::Exif::Main",
                    entry_index,
                    byte_offset,
                    sources,
                )
            )
    byte_order = inspection.get("byte_order")
    if isinstance(byte_order, str):
        tags.insert(
            0,
            _delegate_tag(
                "ExifByteOrder",
                "ExifByteOrder",
                byte_order,
                byte_order,
                "Image",
                "Image::ExifTool::Exif::Main",
                entry_index,
                byte_offset,
                sources,
            ),
        )
    return tags


def _bounded_entry_payload(zip_data: bytes, entry: ZipCentralDirectoryEntryPlan) -> bytes:
    if entry.uncompressed_size > ZIP_MAX_DELEGATE_PAYLOAD_BYTES:
        return b""
    offset = entry.local_header_offset
    if offset + 30 > len(zip_data):
        return b""
    file_name_length = int.from_bytes(zip_data[offset + 26 : offset + 28], "little")
    extra_field_length = int.from_bytes(zip_data[offset + 28 : offset + 30], "little")
    payload_start = offset + 30 + file_name_length + extra_field_length
    payload_end = payload_start + entry.compressed_size
    if payload_end > len(zip_data):
        return b""
    payload = zip_data[payload_start:payload_end]
    if entry.compression_method == 0:
        return payload
    if entry.compression_method != 8:
        return b""
    try:
        inflated = zlib.decompress(payload, -zlib.MAX_WBITS)
    except zlib.error:
        return b""
    if len(inflated) != entry.uncompressed_size:
        return b""
    return inflated


def _delegate_payload(
    zip_data: bytes,
    entry: ZipCentralDirectoryEntryPlan,
    diagnostics: list[ZipReaderDiagnostic],
    context: str,
    sources: tuple[ZipEvidenceId, ...],
) -> bytes | None:
    if entry.uncompressed_size > ZIP_MAX_DELEGATE_PAYLOAD_BYTES:
        diagnostics.append(
            ZipReaderDiagnostic(
                "delegate_payload_blocked",
                f"{context} member {entry.file_name} exceeds bounded delegate payload size",
                sources,
            )
        )
        return None
    if entry.compression_method not in {0, 8}:
        diagnostics.append(
            ZipReaderDiagnostic(
                "delegate_payload_blocked",
                (
                    f"{context} member {entry.file_name} uses unsupported compression method "
                    f"{entry.compression_method}"
                ),
                sources,
            )
        )
        return None
    offset = entry.local_header_offset
    if offset + 30 > len(zip_data):
        diagnostics.append(
            ZipReaderDiagnostic(
                "delegate_payload_blocked",
                f"{context} member {entry.file_name} has a truncated local file header",
                sources,
            )
        )
        return None
    file_name_length = int.from_bytes(zip_data[offset + 26 : offset + 28], "little")
    extra_field_length = int.from_bytes(zip_data[offset + 28 : offset + 30], "little")
    payload_start = offset + 30 + file_name_length + extra_field_length
    payload_end = payload_start + entry.compressed_size
    if payload_end > len(zip_data):
        diagnostics.append(
            ZipReaderDiagnostic(
                "delegate_payload_blocked",
                f"{context} member {entry.file_name} compressed bytes are truncated",
                sources,
            )
        )
        return None
    payload = zip_data[payload_start:payload_end]
    if entry.compression_method == 0:
        return payload
    try:
        inflated = zlib.decompress(payload, -zlib.MAX_WBITS)
    except zlib.error:
        diagnostics.append(
            ZipReaderDiagnostic(
                "delegate_payload_blocked",
                f"{context} member {entry.file_name} deflate stream could not be decoded",
                sources,
            )
        )
        return None
    if len(inflated) != entry.uncompressed_size:
        diagnostics.append(
            ZipReaderDiagnostic(
                "delegate_payload_blocked",
                f"{context} member {entry.file_name} inflated to an unexpected size",
                sources,
            )
        )
        return None
    return inflated


def _ooxml_element_value(element: ElementTree.Element[str]) -> str | None:
    vector_values = [
        text
        for descendant in element.iter()
        if len(tuple(descendant)) == 0
        if _xml_local_name(descendant.tag) not in {"vector", "variant"}
        if (text := _normalized_element_text(descendant)) is not None
    ]
    if vector_values:
        return ", ".join(vector_values)
    return _normalized_element_text(element)


def _normalized_element_text(element: ElementTree.Element[str]) -> str | None:
    text = "".join(element.itertext()).strip()
    if not text:
        return None
    return _ooxml_unescape_text(text)


def _first_descendant_text(element: ElementTree.Element[str]) -> str | None:
    for descendant in element.iter():
        if descendant is element:
            continue
        text = _normalized_element_text(descendant)
        if text is not None:
            return text
    return _normalized_element_text(element)


def _first_value_descendant(
    element: ElementTree.Element[str],
) -> ElementTree.Element[str] | None:
    for descendant in element.iter():
        if descendant is element:
            continue
        if _normalized_element_text(descendant) is not None:
            return descendant
    return element


def _first_attribute_by_local_name(
    element: ElementTree.Element[str],
    local_name: str,
) -> str | None:
    for attribute_name, attribute_value in element.attrib.items():
        _namespace, attribute_local_name = _xml_name_parts(attribute_name)
        if attribute_local_name == local_name:
            return attribute_value
    return None


def _xml_local_name(name: str) -> str:
    return _xml_name_parts(name)[1]


def _xml_name_parts(name: str) -> tuple[str | None, str]:
    if name.startswith("{") and "}" in name:
        namespace, local_name = name[1:].split("}", 1)
        return namespace, local_name
    return None, name


def _title_identifier(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in value.replace("_", "-").split("-"))


def _ooxml_custom_tag_id(name: str) -> str:
    titled = "".join(part[:1].upper() + part[1:] for part in name.split())
    return "".join(character for character in titled if character.isalnum() or character in "-_")


def _ooxml_unescape_text(value: str) -> str:
    return re.sub(
        r"_x([0-9a-fA-F]{4})_",
        lambda match: chr(int(match.group(1), 16)),
        value,
    )


def _ooxml_raw_value(name: str, value: str) -> ZipScalarValue:
    if name in OOXML_INTEGER_TAGS:
        return _integer_or_text(value)
    return value


def _ooxml_rendered_value(name: str, value: str) -> ZipScalarValue:
    if name in OOXML_TIME_TAGS:
        return _xmp_date_text(value)
    if name in OOXML_BOOLEAN_TAGS:
        return "Yes" if value == "true" else "No" if value == "false" else value
    if name == "DocSecurity":
        return OOXML_DOC_SECURITY.get(value, value)
    if name == "TotalEditTime":
        minutes = _integer_or_text(value)
        if isinstance(minutes, int):
            unit = "minute" if minutes == 1 else "minutes"
            return f"{minutes} {unit}"
    if name in OOXML_INTEGER_TAGS:
        return _integer_or_text(value)
    return value


def _xmp_rendered_value(name: str, value: str) -> ZipScalarValue:
    if name in {
        "CreateDate",
        "CreationDate",
        "Date",
        "DateCompleted",
        "ModifyDate",
        "RecordedDate",
    }:
        return _xmp_date_text(value)
    return _integer_or_text(value)


def _integer_or_text(value: str) -> ZipScalarValue:
    return int(value) if value.isdecimal() else value


def _xmp_date_text(value: str) -> str:
    if "T" in value:
        date_text, time_text = value.split("T", 1)
        date_parts = date_text.split("-")
        if len(date_parts) == 3 and all(part.isdecimal() for part in date_parts):
            return f"{date_parts[0]}:{date_parts[1]}:{date_parts[2]} {time_text}"
    date_parts = value.split("-")
    if len(date_parts) in {1, 2, 3} and all(part.isdecimal() for part in date_parts):
        return ":".join(date_parts)
    return value


def _dc_group(name: str) -> str:
    if name == "Creator":
        return "Author"
    if name == "Date":
        return "Time"
    if name in {"Description", "Subject", "Title"}:
        return "Image"
    return "Other"


def _ooxml_group(name: str) -> str:
    if name in OOXML_AUTHOR_TAGS:
        return "Author"
    if name in OOXML_TIME_TAGS:
        return "Time"
    return "Document"


def _is_ooxml_preview_entry(file_name: str) -> bool:
    lower_name = file_name.lower()
    return lower_name.startswith("docprops/thumbnail.") and lower_name.endswith(
        (".jpg", ".jpeg", ".wmf")
    )


def _clean_mimetype(payload: bytes) -> str:
    text = payload.decode("latin-1", errors="replace")
    for character in text:
        ordinal = ord(character)
        if ordinal < 0x21 or ordinal > 0xFE:
            return text[: text.index(character)].lower()
    return text.lower()


def _capture_one_rendered_value(tag_name: str, value: str) -> str:
    if tag_name == "ColorCorrections":
        return f"(Binary data {len(value.encode('utf-8'))} bytes)"
    return value


def _zip_scalar_value(value: ZipDelegateRawValue) -> ZipScalarValue:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str | int | float):
        return value
    if isinstance(value, list | tuple):
        return " ".join(str(item) for item in value)
    return "" if value is None else str(value)


def _exif_group(name: str, fallback: str) -> str:
    if name in {"Make", "Model", "CameraModelName", "LensMake", "LensModel"}:
        return "Camera"
    if "Date" in name or name in {"CreateDate", "ModifyDate"}:
        return "Time"
    return fallback


def _delegate_tag(
    name: str,
    tag_id: str,
    raw_value: ZipScalarValue,
    rendered_value: ZipScalarValue,
    group: str,
    source_table: str,
    entry_index: int | None,
    byte_offset: int,
    sources: tuple[ZipEvidenceId, ...],
) -> ZipReadTag:
    return ZipReadTag(
        name=name,
        group=group,
        source_table=source_table,
        tag_id=tag_id,
        raw_value=raw_value,
        rendered_value=rendered_value,
        entry_index=entry_index,
        byte_offset=byte_offset,
        evidence_ids=sources,
    )


def _zip_family_file_type_tags(
    archive: ZipArchiveTransactionPlan,
    source_file: str | None,
) -> list[ZipReadTag]:
    if archive.status == "unsupported" and not archive.central_directory_entries:
        return []
    file_type, mime_type = _zip_family_file_type(archive, source_file)
    if file_type is None or mime_type is None:
        return []
    sources = (
        (CAPTURE_ONE_EIP_SOURCE,)
        if file_type == "EIP"
        else (ZIP_IWORK_DELEGATION_SOURCE,)
        if file_type in IWORK_EXTENSION_TYPES
        else (ZIP_OOXML_DELEGATION_SOURCE, OOXML_FILE_TYPE_SOURCE)
        if file_type in OOXML_EXTENSION_TYPES
        else (ZIP_OPEN_DOCUMENT_EPUB_SOURCE, OPEN_DOCUMENT_METADATA_SOURCE)
        if file_type in OPEN_DOCUMENT_MIME_TYPES.values()
        else (ZIP_ARCHIVE_ZIP_SOURCE,)
    )
    return [
        _file_tag("FileType", "FileType", file_type, file_type, sources),
        _file_tag(
            "FileTypeExtension",
            "FileTypeExtension",
            file_type.lower(),
            file_type.lower(),
            sources,
        ),
        _file_tag("MIMEType", "MIMEType", mime_type, mime_type, sources),
    ]


def _zip_family_file_type(
    archive: ZipArchiveTransactionPlan,
    source_file: str | None,
) -> tuple[str, str] | tuple[None, None]:
    names = {entry.file_name for entry in archive.central_directory_entries}
    if any(
        name.lower().startswith("captureone/") and name.lower().endswith(".cos") for name in names
    ):
        return "EIP", "application/x-captureone"
    iwork_type = _iwork_type_from_source(source_file)
    if iwork_type is None:
        for name in names:
            iwork_type = IWORK_ENTRY_TYPES.get(name)
            if iwork_type is not None:
                break
    if iwork_type is not None:
        return iwork_type, IWORK_MIME_TYPES.get(iwork_type, "application/zip")
    ooxml_type = _ooxml_type(archive, source_file)
    if ooxml_type is not None:
        mime_type = OOXML_MIME_TYPES_BY_FILE_TYPE.get(ooxml_type)
        if mime_type is None:
            return ooxml_type, "application/zip"
        return ooxml_type, mime_type
    open_document_type = _open_document_type(archive)
    if open_document_type is not None:
        return open_document_type
    if source_file is not None and PurePath(source_file).suffix.lower() == ".zip":
        return "ZIP", "application/zip"
    return None, None


def _ooxml_type(
    archive: ZipArchiveTransactionPlan,
    source_file: str | None,
) -> str | None:
    entries = {entry.file_name: entry for entry in archive.central_directory_entries}
    content_types = entries.get(OOXML_CONTENT_TYPE_ENTRY)
    if content_types is not None:
        payload = _bounded_entry_payload(archive.original_bytes, content_types)
        mime_type = _ooxml_main_mime(payload)
        if mime_type is not None:
            file_type = OOXML_MAIN_MIME_TYPES.get(mime_type)
            if file_type == "PPTX" and _source_extension(source_file) == "THMX":
                return "THMX"
            return file_type
    if any(
        name.lower().startswith("docprops/") and name.lower().endswith(".xml") for name in entries
    ):
        extension = _source_extension(source_file)
        return extension if extension in OOXML_EXTENSION_TYPES else "DOCX"
    return None


def _ooxml_main_mime(payload: bytes) -> str | None:
    text = payload.decode("utf-8", errors="replace")
    for mime_type in OOXML_MAIN_MIME_TYPES:
        if f"{mime_type}.main" in text:
            return mime_type
    return None


def _open_document_type(
    archive: ZipArchiveTransactionPlan,
) -> tuple[str, str] | None:
    for entry in archive.central_directory_entries:
        if entry.file_name != OPEN_DOCUMENT_MIMETYPE_ENTRY:
            continue
        payload = _bounded_entry_payload(archive.original_bytes, entry)
        mime_type = _clean_mimetype(payload)
        file_type = OPEN_DOCUMENT_MIME_TYPES.get(mime_type)
        if file_type is not None:
            return file_type, mime_type
    return None


def _source_extension(source_file: str | None) -> str | None:
    if source_file is None:
        return None
    suffix = PurePath(source_file).suffix.removeprefix(".").upper()
    return suffix or None


def _iwork_type_from_source(source_file: str | None) -> str | None:
    suffix = _source_extension(source_file)
    return suffix if suffix in IWORK_EXTENSION_TYPES else None


def _is_iwork_preview_entry(file_name: str) -> bool:
    return file_name.lower() == "quicklook/thumbnail.jpg"


def _tag(
    name: str,
    tag_id: str,
    raw_value: ZipScalarValue,
    rendered_value: ZipScalarValue,
    entry_index: int | None,
    byte_offset: int,
    sources: tuple[ZipEvidenceId, ...] = (ZIP_MEMBER_TAG_SOURCE,),
) -> ZipReadTag:
    return ZipReadTag(
        name=name,
        group="ZIP",
        source_table="Image::ExifTool::ZIP::Main",
        tag_id=tag_id,
        raw_value=raw_value,
        rendered_value=rendered_value,
        entry_index=entry_index,
        byte_offset=byte_offset,
        evidence_ids=sources,
    )


def _file_tag(
    name: str,
    tag_id: str,
    raw_value: ZipScalarValue,
    rendered_value: ZipScalarValue,
    sources: tuple[ZipEvidenceId, ...],
) -> ZipReadTag:
    return ZipReadTag(
        name=name,
        group="File",
        source_table="Image::ExifTool::File",
        tag_id=tag_id,
        raw_value=raw_value,
        rendered_value=rendered_value,
        entry_index=None,
        byte_offset=0,
        evidence_ids=sources,
    )


def _central_directory_datetime(archive: ZipArchiveTransactionPlan, header_offset: int) -> int:
    return _read_uint32(archive.original_bytes, header_offset + 12)


def _read_uint32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


plan_zip_reader = build_zip_reader_plan


install_evidence_reference_compat(globals())
