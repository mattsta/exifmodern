"""Source-grounded, non-mutating Apple iWork package transaction plans.

The planner mirrors ExifTool's iWork reader on top of the shared ZIP planner:
it records member-level ZIP handling, detects iWork package identity, routes
index metadata and preview JPEG entries, preserves unrelated package/media
entries, and keeps byte emission behind explicit gates.
"""

from __future__ import annotations

import html
import re
import zlib
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.zip import (
    ZipArchiveTransactionPlan,
    ZipLocalFileHeaderPlan,
    ZipOutputEmissionGate,
    build_zip_archive_transaction_plan,
)

IWORK_PM_SOURCE_PATH = "lib/Image/ExifTool/iWork.pm"
ZIP_PM_SOURCE_PATH = "lib/Image/ExifTool/ZIP.pm"

IWORK_EXTENSION_TYPES: dict[str, str] = {
    "NUMBERS": "NUMBERS",
    "PAGES": "PAGES",
    "KEY": "KEY",
    "KTH": "KTH",
    "NMBTEMPLATE": "NMBTEMPLATE",
}
IWORK_ROOT_TYPES: dict[str, str] = {
    "ls:document": "NUMBERS",
    "sl:document": "PAGES",
    "key:presentation": "KEY",
}
IWORK_MIME_TYPES: dict[str, str] = {
    "NUMBERS": "application/x-iwork-numbers-sffnumbers",
    "PAGES": "application/x-iwork-pages-sffpages",
    "KEY": "application/x-iWork-keynote-sffkey",
    "NMBTEMPLATE": "application/x-iwork-numbers-sfftemplate",
    "PAGES.TEMPLATE": "application/x-iwork-pages-sfftemplate",
    "KTH": "application/x-iWork-keynote-sffkth",
}
IWORK_MAX_DELEGATE_PAYLOAD_BYTES = 8 * 1024 * 1024


def _zip_evidence_ids(evidence_ids: tuple[str, ...]) -> tuple[str, ...]:
    return evidence_ids


IWORK_TYPE_SOURCE = "iwork.type"
IWORK_TAG_TABLE_SOURCE = "iwork.tag.table"
IWORK_TAG_ID_SOURCE = "iwork.tag.id"
IWORK_TYPE_DETECTION_SOURCE = "iwork.type.detection"
IWORK_MEMBER_SOURCE = "iwork.member"
IWORK_ROUTE_SOURCE = "iwork.route"
IWORK_METADATA_SOURCE = "iwork.metadata"
IWORK_DOC_PATH_SOURCE = "iwork.doc.path"
ZIP_IWORK_DELEGATION_SOURCE = "zip.iwork.delegation"

IWORK_TRANSACTION_SOURCES = (
    IWORK_TYPE_SOURCE,
    IWORK_TAG_TABLE_SOURCE,
    IWORK_TAG_ID_SOURCE,
    IWORK_TYPE_DETECTION_SOURCE,
    IWORK_MEMBER_SOURCE,
    IWORK_ROUTE_SOURCE,
    IWORK_METADATA_SOURCE,
    IWORK_DOC_PATH_SOURCE,
    ZIP_IWORK_DELEGATION_SOURCE,
)

type IworkPlanStatus = Literal["planned", "unsupported"]
type IworkIdentityMethod = Literal[
    "file_extension",
    "index_root",
    "nested_package_path",
    "zip_fallback",
    "unsupported",
]
type IworkEntryResponsibility = Literal[
    "index_metadata",
    "document_index_metadata",
    "unsupported_document_index_archive",
    "preview_image",
    "media_preservation",
    "package_member_preservation",
]
type IworkIndexMetadataAction = Literal[
    "parse_metadata_section",
    "detect_document_type_only",
    "block_nested_index_archive",
]
type IworkPreviewKind = Literal["preview", "thumbnail", "other"]
type IworkMetadataResponsibilityKind = Literal[
    "author",
    "comment",
    "copyright",
    "keywords",
    "projects",
    "title",
    "unknown_dynamic_tag",
]
type IworkRewriteOperation = Literal["upsert", "delete", "replace"]
type IworkRewriteTarget = Literal[
    "author",
    "comment",
    "copyright",
    "keywords",
    "projects",
    "title",
    "index_metadata",
    "preview_image",
]
type IworkEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "unsupported_zip_package",
    "unsupported_iwork_package",
    "encrypted_entry_blocker",
    "zip64_blocker",
    "data_descriptor_blocker",
    "nested_iwork_index_archive_blocker",
    "rewrite_requested_requires_iwork_writer",
]


@dataclass(frozen=True)
class IworkOutputEmissionGate:
    code: IworkEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IworkPackageIdentityPlan:
    file_type: str
    mime_type: str | None
    detection_method: IworkIdentityMethod
    file_extension: str | None
    index_file_name: str | None
    root_element: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IworkMetadataTagResponsibility:
    tag_id: str
    responsibility: IworkMetadataResponsibilityKind
    exiftool_name: str
    family2_group: str
    list_value: bool
    rewrite_supported: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IworkMetadataValuePlan:
    file_name: str
    entry_index: int
    tag_id: str
    responsibility: IworkMetadataResponsibilityKind
    exiftool_name: str
    value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IworkIndexMetadataFilePlan:
    file_name: str
    entry_index: int
    action: IworkIndexMetadataAction
    payload_length: int
    root_element: str | None
    metadata_namespace: str | None
    metadata_section_range: tuple[int, int] | None
    values: tuple[IworkMetadataValuePlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IworkZipEntryRoutePlan:
    entry_index: int
    file_name: str
    responsibility: IworkEntryResponsibility
    records_zip_member_metadata: bool
    payload_boundary: tuple[int, int] | None
    preview_kind: IworkPreviewKind | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IworkRewriteRequest:
    target: IworkRewriteTarget
    operation: IworkRewriteOperation
    value: str | None = None


@dataclass(frozen=True)
class IworkPackageTransactionPlan:
    status: IworkPlanStatus
    source_data: bytes
    zip_plan: ZipArchiveTransactionPlan
    identity: IworkPackageIdentityPlan
    entry_routes: tuple[IworkZipEntryRoutePlan, ...]
    index_metadata_files: tuple[IworkIndexMetadataFilePlan, ...]
    tag_responsibilities: tuple[IworkMetadataTagResponsibility, ...]
    rewrite_requests: tuple[IworkRewriteRequest, ...]
    output_emission_gates: tuple[IworkOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"iWork package transaction output is gated: {gate_codes}")
        return self.source_data


def build_iwork_package_transaction_plan(
    package_data: bytes,
    *,
    file_extension: str | None = None,
    rewrite_requests: tuple[IworkRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> IworkPackageTransactionPlan:
    zip_plan = build_zip_archive_transaction_plan(package_data, allow_output_emission=True)
    headers_by_index = {header.index: header for header in zip_plan.local_file_headers}
    identity = build_identity_plan(package_data, zip_plan, file_extension, headers_by_index)
    routes = tuple(
        route_entry(entry.index, entry.file_name, headers_by_index.get(entry.index))
        for entry in zip_plan.central_directory_entries
    )
    index_files = tuple(
        build_index_metadata_file(package_data, route, headers_by_index[route.entry_index])
        for route in routes
        if route.entry_index in headers_by_index
        and route.responsibility
        in {
            "index_metadata",
            "document_index_metadata",
            "unsupported_document_index_archive",
        }
    )
    gates = [
        convert_zip_gate(gate)
        for gate in zip_plan.output_emission_gates
        if gate.code != "non_mutating_plan_requires_explicit_emission"
    ]
    if identity.detection_method == "unsupported":
        gates.append(
            IworkOutputEmissionGate(
                "unsupported_iwork_package",
                "No iWork extension, top-level index root, or nested package path was detected.",
                identity.evidence_ids,
            )
        )
    gates.extend(
        IworkOutputEmissionGate(
            "nested_iwork_index_archive_blocker",
            f"{route.file_name} is a nested Index.zip package boundary, not parsed by iWork.pm.",
            route.evidence_ids,
        )
        for route in routes
        if route.responsibility == "unsupported_document_index_archive"
    )
    if rewrite_requests:
        gates.append(
            IworkOutputEmissionGate(
                "rewrite_requested_requires_iwork_writer",
                "iWork.pm models read extraction only; package metadata rewrite is not planned.",
                (IWORK_TAG_TABLE_SOURCE, IWORK_ROUTE_SOURCE),
            )
        )
    if not allow_output_emission:
        gates.append(
            IworkOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "iWork package transaction plans do not emit bytes unless explicitly allowed.",
                (IWORK_ROUTE_SOURCE,),
            )
        )
    unique_gate_tuple = unique_gates(tuple(gates))
    structural_codes = {
        "unsupported_zip_package",
        "unsupported_iwork_package",
        "encrypted_entry_blocker",
        "zip64_blocker",
        "data_descriptor_blocker",
        "nested_iwork_index_archive_blocker",
    }
    status: IworkPlanStatus = (
        "unsupported"
        if any(gate.code in structural_codes for gate in unique_gate_tuple)
        else "planned"
    )
    sources = unique_sources(
        (
            *IWORK_TRANSACTION_SOURCES,
            *_zip_evidence_ids(zip_plan.evidence_ids),
            *identity.evidence_ids,
            *(source for route in routes for source in route.evidence_ids),
            *(source for index_file in index_files for source in index_file.evidence_ids),
            *(source for gate in unique_gate_tuple for source in gate.evidence_ids),
            *(source for tag in IWORK_TAG_RESPONSIBILITIES for source in tag.evidence_ids),
        )
    )
    return IworkPackageTransactionPlan(
        status=status,
        source_data=package_data,
        zip_plan=zip_plan,
        identity=identity,
        entry_routes=routes,
        index_metadata_files=index_files,
        tag_responsibilities=IWORK_TAG_RESPONSIBILITIES,
        rewrite_requests=rewrite_requests,
        output_emission_gates=unique_gate_tuple,
        evidence_ids=sources,
    )


def build_identity_plan(
    package_data: bytes,
    zip_plan: ZipArchiveTransactionPlan,
    file_extension: str | None,
    headers_by_index: dict[int, ZipLocalFileHeaderPlan],
) -> IworkPackageIdentityPlan:
    extension = normalize_extension(file_extension)
    if extension in IWORK_EXTENSION_TYPES:
        file_type = IWORK_EXTENSION_TYPES[extension]
        return IworkPackageIdentityPlan(
            file_type=file_type,
            mime_type=IWORK_MIME_TYPES.get(file_type),
            detection_method="file_extension",
            file_extension=extension,
            index_file_name=None,
            root_element=None,
            evidence_ids=(IWORK_TYPE_SOURCE, IWORK_TYPE_DETECTION_SOURCE),
        )
    index = first_top_level_index(zip_plan, headers_by_index)
    if index is not None:
        payload = stored_payload(package_data, index.header)
        root = xml_root_element(payload)
        if root in IWORK_ROOT_TYPES:
            file_type = IWORK_ROOT_TYPES[root]
            return IworkPackageIdentityPlan(
                file_type=file_type,
                mime_type=IWORK_MIME_TYPES.get(file_type),
                detection_method="index_root",
                file_extension=extension,
                index_file_name=index.file_name,
                root_element=root,
                evidence_ids=(IWORK_TYPE_SOURCE, IWORK_TYPE_DETECTION_SOURCE),
            )
    nested = first_nested_index(zip_plan)
    if nested is not None:
        file_type = nested_file_type(nested.file_name)
        return IworkPackageIdentityPlan(
            file_type=file_type,
            mime_type=IWORK_MIME_TYPES.get(file_type),
            detection_method="nested_package_path",
            file_extension=extension,
            index_file_name=nested.file_name,
            root_element=None,
            evidence_ids=(
                IWORK_TYPE_SOURCE,
                IWORK_DOC_PATH_SOURCE,
                ZIP_IWORK_DELEGATION_SOURCE,
            ),
        )
    if zip_plan.status == "planned" and zip_plan.central_directory_entries:
        return IworkPackageIdentityPlan(
            file_type="ZIP",
            mime_type=None,
            detection_method="unsupported",
            file_extension=extension,
            index_file_name=None,
            root_element=None,
            evidence_ids=(IWORK_TYPE_DETECTION_SOURCE, ZIP_IWORK_DELEGATION_SOURCE),
        )
    return IworkPackageIdentityPlan(
        file_type="ZIP",
        mime_type=None,
        detection_method="zip_fallback",
        file_extension=extension,
        index_file_name=None,
        root_element=None,
        evidence_ids=(IWORK_TYPE_DETECTION_SOURCE,),
    )


@dataclass(frozen=True)
class IndexCandidate:
    file_name: str
    header: ZipLocalFileHeaderPlan


def first_top_level_index(
    zip_plan: ZipArchiveTransactionPlan,
    headers_by_index: dict[int, ZipLocalFileHeaderPlan],
) -> IndexCandidate | None:
    for entry in zip_plan.central_directory_entries:
        if entry.file_name.lower() not in {"index.xml", "index.apxl"}:
            continue
        header = headers_by_index.get(entry.index)
        if header is not None:
            return IndexCandidate(file_name=entry.file_name, header=header)
    return None


def first_nested_index(zip_plan: ZipArchiveTransactionPlan) -> IworkZipEntryRoutePlan | None:
    for entry in zip_plan.central_directory_entries:
        if nested_index_match(entry.file_name):
            return route_entry(entry.index, entry.file_name, None)
    return None


def route_entry(
    index: int,
    file_name: str,
    header: ZipLocalFileHeaderPlan | None,
) -> IworkZipEntryRoutePlan:
    lower_name = file_name.lower()
    boundary = payload_boundary(header)
    if lower_name in {"index.xml", "index.apxl"}:
        return IworkZipEntryRoutePlan(
            entry_index=index,
            file_name=file_name,
            responsibility="index_metadata",
            records_zip_member_metadata=True,
            payload_boundary=boundary,
            preview_kind=None,
            reason="Top-level iWork index XML/APXL is parsed for metadata sections.",
            evidence_ids=(IWORK_ROUTE_SOURCE, IWORK_METADATA_SOURCE),
        )
    if nested_index_match(file_name):
        responsibility: IworkEntryResponsibility = (
            "unsupported_document_index_archive"
            if lower_name.endswith("/index.zip")
            else "document_index_metadata"
        )
        return IworkZipEntryRoutePlan(
            entry_index=index,
            file_name=file_name,
            responsibility=responsibility,
            records_zip_member_metadata=True,
            payload_boundary=boundary,
            preview_kind=None,
            reason=(
                "Nested iWork document Index paths select package type; nested Index.zip "
                "is a preservation boundary."
            ),
            evidence_ids=(IWORK_DOC_PATH_SOURCE, ZIP_IWORK_DELEGATION_SOURCE),
        )
    preview_kind = preview_kind_for_name(file_name)
    if preview_kind is not None:
        return IworkZipEntryRoutePlan(
            entry_index=index,
            file_name=file_name,
            responsibility="preview_image",
            records_zip_member_metadata=True,
            payload_boundary=boundary,
            preview_kind=preview_kind,
            reason="iWork.pm extracts selected JPEG thumbnail and preview entries.",
            evidence_ids=(IWORK_ROUTE_SOURCE,),
        )
    if is_media_entry(file_name):
        return IworkZipEntryRoutePlan(
            entry_index=index,
            file_name=file_name,
            responsibility="media_preservation",
            records_zip_member_metadata=True,
            payload_boundary=boundary,
            preview_kind=None,
            reason="Media entries are outside iWork.pm metadata routing and are preserved.",
            evidence_ids=(IWORK_MEMBER_SOURCE, IWORK_ROUTE_SOURCE),
        )
    return IworkZipEntryRoutePlan(
        entry_index=index,
        file_name=file_name,
        responsibility="package_member_preservation",
        records_zip_member_metadata=True,
        payload_boundary=boundary,
        preview_kind=None,
        reason="Unrouted iWork package entries keep ZIP member metadata and payload boundaries.",
        evidence_ids=(IWORK_MEMBER_SOURCE,),
    )


def build_index_metadata_file(
    package_data: bytes,
    route: IworkZipEntryRoutePlan,
    header: ZipLocalFileHeaderPlan,
) -> IworkIndexMetadataFilePlan:
    payload = stored_payload(package_data, header)
    root = xml_root_element(payload)
    if route.responsibility == "unsupported_document_index_archive":
        return IworkIndexMetadataFilePlan(
            file_name=route.file_name,
            entry_index=route.entry_index,
            action="block_nested_index_archive",
            payload_length=len(payload),
            root_element=None,
            metadata_namespace=None,
            metadata_section_range=None,
            values=(),
            evidence_ids=(IWORK_DOC_PATH_SOURCE, ZIP_IWORK_DELEGATION_SOURCE),
        )
    if route.responsibility == "document_index_metadata":
        return IworkIndexMetadataFilePlan(
            file_name=route.file_name,
            entry_index=route.entry_index,
            action="detect_document_type_only",
            payload_length=len(payload),
            root_element=root,
            metadata_namespace=None,
            metadata_section_range=None,
            values=(),
            evidence_ids=(IWORK_DOC_PATH_SOURCE,),
        )
    metadata = metadata_section(payload)
    values: tuple[IworkMetadataValuePlan, ...] = ()
    namespace = None
    section_range = None
    if metadata is not None:
        namespace = metadata.namespace
        section_range = metadata.section_range
        values = tuple(
            metadata_value(route.file_name, route.entry_index, tag_id, value)
            for tag_id, value in metadata_values(metadata.text)
        )
    return IworkIndexMetadataFilePlan(
        file_name=route.file_name,
        entry_index=route.entry_index,
        action="parse_metadata_section",
        payload_length=len(payload),
        root_element=root,
        metadata_namespace=namespace,
        metadata_section_range=section_range,
        values=values,
        evidence_ids=(IWORK_ROUTE_SOURCE, IWORK_METADATA_SOURCE, IWORK_TAG_ID_SOURCE),
    )


@dataclass(frozen=True)
class MetadataSection:
    namespace: str
    section_range: tuple[int, int]
    text: str


def metadata_section(payload: bytes) -> MetadataSection | None:
    text = payload.decode("utf-8", errors="replace")
    open_match = re.search(r"<(\w+):metadata>", text)
    if open_match is None:
        return None
    namespace = open_match.group(1)
    close_match = re.search(rf"</{re.escape(namespace)}:metadata>", text[open_match.end() :])
    if close_match is None:
        return None
    start = open_match.end()
    end = open_match.end() + close_match.start()
    return MetadataSection(namespace=namespace, section_range=(start, end), text=text[start:end])


def metadata_values(metadata_text: str) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for match in re.finditer(
        r"<(?:\w+:)?([A-Za-z][\w.-]*)\b[^>]*>(.*?)</(?:\w+:)?\1>",
        metadata_text,
        re.DOTALL,
    ):
        tag_id = match.group(1)
        if tag_id == "ID":
            continue
        body = match.group(2)
        string_values = re.findall(r'\bsfa:string="([^"]*)"', body)
        if string_values:
            values.extend((tag_id, html.unescape(value)) for value in string_values)
            continue
        raw_value = re.sub(r"<[^>]+>", "", body)
        value = html.unescape(raw_value).strip()
        if value:
            values.append((tag_id, value))
    return tuple(values)


def metadata_value(
    file_name: str, entry_index: int, tag_id: str, value: str
) -> IworkMetadataValuePlan:
    responsibility = responsibility_for_tag(tag_id)
    tag = tag_responsibility_by_id(tag_id)
    exiftool_name = tag.exiftool_name if tag is not None else tag_id[:1].upper() + tag_id[1:]
    return IworkMetadataValuePlan(
        file_name=file_name,
        entry_index=entry_index,
        tag_id=tag_id,
        responsibility=responsibility,
        exiftool_name=exiftool_name,
        value=value,
        evidence_ids=(IWORK_TAG_ID_SOURCE, IWORK_TAG_TABLE_SOURCE),
    )


def normalize_extension(file_extension: str | None) -> str | None:
    if file_extension is None:
        return None
    return file_extension.removeprefix(".").upper()


def xml_root_element(payload: bytes) -> str | None:
    text = payload.decode("utf-8", errors="replace")
    match = re.search(r"^\s*(?:<\?xml\b[^>]*>\s*)?<(\w+:\w+)", text, re.DOTALL)
    if match is None:
        return None
    return match.group(1)


def nested_index_match(file_name: str) -> bool:
    return (
        re.fullmatch(r"[^/]+\.(pages|numbers|key)/Index\.(zip|xml|apxl)", file_name, re.IGNORECASE)
        is not None
    )


def nested_file_type(file_name: str) -> str:
    match = re.search(r"\.(pages|numbers|key)/Index\.", file_name, re.IGNORECASE)
    if match is None:
        return "ZIP"
    return match.group(1).upper()


def preview_kind_for_name(file_name: str) -> IworkPreviewKind | None:
    if re.fullmatch(r"QuickLook/Thumbnail\.jpg", file_name, re.IGNORECASE):
        return "preview"
    match = re.fullmatch(r"[^/]+/preview(-micro|-web)?\.jpg", file_name, re.IGNORECASE)
    if match is None:
        return None
    suffix = match.group(1)
    if suffix == "-micro":
        return "thumbnail"
    if suffix == "-web":
        return "other"
    return "preview"


def is_media_entry(file_name: str) -> bool:
    lower_name = file_name.lower()
    media_prefixes = ("data/", "media/", "quicklook/")
    media_suffixes = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".pdf", ".mov", ".mp4", ".iwa")
    return lower_name.startswith(media_prefixes) or lower_name.endswith(media_suffixes)


def payload_boundary(header: ZipLocalFileHeaderPlan | None) -> tuple[int, int] | None:
    if header is None:
        return None
    return (header.payload_offset, header.payload_end_offset)


def stored_payload(package_data: bytes, header: ZipLocalFileHeaderPlan) -> bytes:
    if header.payload_end_offset > len(package_data):
        return b""
    if header.uncompressed_size > IWORK_MAX_DELEGATE_PAYLOAD_BYTES:
        return b""
    payload = package_data[header.payload_offset : header.payload_end_offset]
    if header.compression_method == 0:
        return payload
    if header.compression_method == 8:
        try:
            inflated = zlib.decompress(payload, -zlib.MAX_WBITS)
        except zlib.error:
            return b""
        if len(inflated) != header.uncompressed_size:
            return b""
        return inflated
    return b""


def convert_zip_gate(gate: ZipOutputEmissionGate) -> IworkOutputEmissionGate:
    if gate.code == "encrypted_entry_blocker":
        code: IworkEmissionGateCode = "encrypted_entry_blocker"
    elif gate.code == "zip64_blocker":
        code = "zip64_blocker"
    elif gate.code == "data_descriptor_blocker":
        code = "data_descriptor_blocker"
    else:
        code = "unsupported_zip_package"
    return IworkOutputEmissionGate(code, gate.reason, _zip_evidence_ids(gate.evidence_ids))


def responsibility_for_tag(tag_id: str) -> IworkMetadataResponsibilityKind:
    tag = tag_responsibility_by_id(tag_id)
    if tag is not None:
        return tag.responsibility
    return "unknown_dynamic_tag"


def tag_responsibility_by_id(tag_id: str) -> IworkMetadataTagResponsibility | None:
    for tag in IWORK_TAG_RESPONSIBILITIES:
        if tag.tag_id == tag_id:
            return tag
    return None


def unique_gates(
    gates: tuple[IworkOutputEmissionGate, ...],
) -> tuple[IworkOutputEmissionGate, ...]:
    seen: set[tuple[IworkEmissionGateCode, str]] = set()
    unique: list[IworkOutputEmissionGate] = []
    for gate in gates:
        key = (gate.code, gate.reason)
        if key not in seen:
            seen.add(key)
            unique.append(gate)
    return tuple(unique)


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        key = source
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return tuple(unique)


IWORK_TAG_RESPONSIBILITIES = (
    IworkMetadataTagResponsibility(
        tag_id="authors",
        responsibility="author",
        exiftool_name="Author",
        family2_group="Author",
        list_value=False,
        rewrite_supported=False,
        evidence_ids=(IWORK_TAG_TABLE_SOURCE,),
    ),
    IworkMetadataTagResponsibility(
        tag_id="comment",
        responsibility="comment",
        exiftool_name="Comment",
        family2_group="Document",
        list_value=False,
        rewrite_supported=False,
        evidence_ids=(IWORK_TAG_TABLE_SOURCE,),
    ),
    IworkMetadataTagResponsibility(
        tag_id="copyright",
        responsibility="copyright",
        exiftool_name="Copyright",
        family2_group="Author",
        list_value=False,
        rewrite_supported=False,
        evidence_ids=(IWORK_TAG_TABLE_SOURCE,),
    ),
    IworkMetadataTagResponsibility(
        tag_id="keywords",
        responsibility="keywords",
        exiftool_name="Keywords",
        family2_group="Document",
        list_value=False,
        rewrite_supported=False,
        evidence_ids=(IWORK_TAG_TABLE_SOURCE,),
    ),
    IworkMetadataTagResponsibility(
        tag_id="projects",
        responsibility="projects",
        exiftool_name="Projects",
        family2_group="Document",
        list_value=True,
        rewrite_supported=False,
        evidence_ids=(IWORK_TAG_TABLE_SOURCE,),
    ),
    IworkMetadataTagResponsibility(
        tag_id="title",
        responsibility="title",
        exiftool_name="Title",
        family2_group="Document",
        list_value=False,
        rewrite_supported=False,
        evidence_ids=(IWORK_TAG_TABLE_SOURCE,),
    ),
)
