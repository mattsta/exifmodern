"""Source-backed, non-mutating OOXML package transaction plans."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.zip import (
    ZipArchiveTransactionPlan,
    ZipCentralDirectoryEntryPlan,
    build_zip_archive_transaction_plan,
)

type OoxmlPlanStatus = Literal["planned", "unsupported"]
type OoxmlPackageKind = Literal["ooxml", "not_ooxml"]
type OoxmlEntryResponsibility = Literal[
    "content_types_discriminator",
    "package_relationships_preserve",
    "core_properties_read",
    "app_properties_read",
    "custom_properties_read",
    "docprops_xml_read",
    "docprops_preview_read",
    "document_main_preserve",
    "embedded_media_preserve",
    "embedded_document_preserve",
    "encrypted_package_block",
    "unknown_preserve",
]
type OoxmlPropertyFamily = Literal[
    "core",
    "app",
    "custom",
    "other_docprops_xml",
    "thumbnail_preview",
]
type OoxmlContentTypeResponsibility = Literal[
    "detect_main_document_mime",
    "preserve_content_type_registry",
    "absent",
]
type OoxmlRelationshipResponsibility = Literal[
    "preserve_package_relationships",
    "absent",
]
type OoxmlEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "zip_archive_blocker",
    "encrypted_entry_blocker",
    "encrypted_package_blocker",
    "unsupported_package_blocker",
]
type OoxmlRewriteBlockerCode = Literal[
    "docprops_xml_rewrite_not_implemented",
    "content_types_rewrite_not_implemented",
    "relationships_rewrite_not_implemented",
    "document_part_rewrite_not_implemented",
    "embedded_payload_rewrite_not_supported",
]

OOXML_PM_SOURCE_PATH = "lib/Image/ExifTool/OOXML.pm"
ZIP_PM_SOURCE_PATH = "lib/Image/ExifTool/ZIP.pm"

OOXML_EXTENSION_SOURCE = "ooxml.extension"
OOXML_NOTES_SOURCE = "ooxml.notes"
OOXML_TAG_TABLE_SOURCE = "ooxml.tag_table"
OOXML_CUSTOM_PROPERTY_SOURCE = "ooxml.custom_property"
OOXML_VECTOR_SOURCE = "ooxml.vector"
OOXML_FILE_TYPE_SOURCE = "ooxml.file_type"
OOXML_DOCPROPS_SOURCE = "ooxml.docprops"
OOXML_PREVIEW_SOURCE = "ooxml.preview"
ZIP_OOXML_DETECTION_SOURCE = "ooxml.zip_ooxml_detection"
ZIP_MEMBER_SOURCE = "ooxml.zip_member"
ZIP_STREAM_MODE_SOURCE = "ooxml.zip_stream_mode"
OOXML_NON_MUTATING_SOURCE = "ooxml.non_mutating"

OOXML_MAIN_MIME_TO_TYPE: dict[str, str] = {
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
EXPECTED_MAIN_PARTS = frozenset(("/ppt/presentation.xml", "/word/document.xml", "/xl/workbook.xml"))
ENCRYPTED_PACKAGE_ENTRY_NAMES = frozenset(("EncryptionInfo", "EncryptedPackage"))


@dataclass(frozen=True)
class OoxmlEntryResponsibilityPlan:
    file_name: str
    entry_index: int
    responsibility: OoxmlEntryResponsibility
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OoxmlPropertyPartPlan:
    file_name: str
    entry_index: int
    family: OoxmlPropertyFamily
    read_responsibility: str
    rewrite_responsibility: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OoxmlContentTypesPlan:
    file_name: str | None
    entry_index: int | None
    responsibility: OoxmlContentTypeResponsibility
    main_part_name: str | None
    main_content_type: str | None
    inferred_file_type: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OoxmlRelationshipsPlan:
    relationship_entry_names: tuple[str, ...]
    responsibility: OoxmlRelationshipResponsibility
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OoxmlDocumentMetadataPathPlan:
    document_part_name: str
    entry_index: int | None
    inferred_file_type: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OoxmlPreservationBoundaryPlan:
    file_name: str
    entry_index: int
    boundary_kind: Literal["embedded_media", "embedded_document", "structural_xml", "unknown"]
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OoxmlRewriteBlocker:
    code: OoxmlRewriteBlockerCode
    file_name: str
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OoxmlOutputEmissionGate:
    code: OoxmlEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OoxmlPackageTransactionPlan:
    status: OoxmlPlanStatus
    package_kind: OoxmlPackageKind
    zip_plan: ZipArchiveTransactionPlan
    content_types: OoxmlContentTypesPlan
    relationships: OoxmlRelationshipsPlan
    entry_responsibilities: tuple[OoxmlEntryResponsibilityPlan, ...]
    property_parts: tuple[OoxmlPropertyPartPlan, ...]
    document_metadata_paths: tuple[OoxmlDocumentMetadataPathPlan, ...]
    preservation_boundaries: tuple[OoxmlPreservationBoundaryPlan, ...]
    rewrite_blockers: tuple[OoxmlRewriteBlocker, ...]
    output_emission_gates: tuple[OoxmlOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"OOXML package transaction output is gated: {gate_codes}")
        return self.zip_plan.original_bytes


def build_ooxml_package_transaction_plan(
    package_data: bytes,
    *,
    file_extension: str | None = None,
    allow_output_emission: bool = False,
) -> OoxmlPackageTransactionPlan:
    zip_plan = build_zip_archive_transaction_plan(package_data, allow_output_emission=True)
    payloads = _entry_payloads(zip_plan)
    content_types = _build_content_types_plan(zip_plan, payloads, file_extension)
    relationships = _build_relationships_plan(zip_plan)
    entry_responsibilities = tuple(
        _entry_responsibility(entry, content_types) for entry in zip_plan.central_directory_entries
    )
    property_parts = tuple(
        part
        for entry in zip_plan.central_directory_entries
        if (part := _property_part(entry)) is not None
    )
    document_paths = _document_metadata_paths(zip_plan, content_types)
    preservation_boundaries = tuple(
        boundary
        for entry in zip_plan.central_directory_entries
        if (boundary := _preservation_boundary(entry, content_types)) is not None
    )
    rewrite_blockers = _rewrite_blockers(
        property_parts,
        content_types,
        relationships,
        document_paths,
        preservation_boundaries,
    )
    gates = list(_zip_gates(zip_plan))
    package_kind = _package_kind(zip_plan, content_types, property_parts)
    if package_kind == "not_ooxml":
        gates.append(
            OoxmlOutputEmissionGate(
                code="unsupported_package_blocker",
                reason="The ZIP entries do not match ExifTool OOXML delegation triggers.",
                evidence_ids=(ZIP_OOXML_DETECTION_SOURCE,),
            )
        )
    for entry in zip_plan.central_directory_entries:
        if entry.file_name in ENCRYPTED_PACKAGE_ENTRY_NAMES:
            gates.append(
                OoxmlOutputEmissionGate(
                    code="encrypted_package_blocker",
                    reason=f"{entry.file_name} marks an encrypted OOXML package payload.",
                    evidence_ids=(OOXML_NOTES_SOURCE, OOXML_DOCPROPS_SOURCE),
                )
            )
    if not allow_output_emission:
        gates.append(
            OoxmlOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="OOXML package transaction plans do not emit bytes unless allowed.",
                evidence_ids=(OOXML_NON_MUTATING_SOURCE,),
            )
        )
    status: OoxmlPlanStatus = "unsupported" if _unsupported_gate_exists(gates) else "planned"
    evidence_ids = _unique_sources(
        (
            OOXML_EXTENSION_SOURCE,
            OOXML_NOTES_SOURCE,
            OOXML_TAG_TABLE_SOURCE,
            OOXML_CUSTOM_PROPERTY_SOURCE,
            OOXML_VECTOR_SOURCE,
            OOXML_FILE_TYPE_SOURCE,
            OOXML_DOCPROPS_SOURCE,
            OOXML_PREVIEW_SOURCE,
            ZIP_OOXML_DETECTION_SOURCE,
            ZIP_MEMBER_SOURCE,
            ZIP_STREAM_MODE_SOURCE,
            OOXML_NON_MUTATING_SOURCE,
            *content_types.evidence_ids,
            *relationships.evidence_ids,
            *(source for route in entry_responsibilities for source in route.evidence_ids),
            *(source for part in property_parts for source in part.evidence_ids),
            *(source for path in document_paths for source in path.evidence_ids),
            *(source for item in preservation_boundaries for source in item.evidence_ids),
            *(source for blocker in rewrite_blockers for source in blocker.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return OoxmlPackageTransactionPlan(
        status=status,
        package_kind=package_kind,
        zip_plan=zip_plan,
        content_types=content_types,
        relationships=relationships,
        entry_responsibilities=entry_responsibilities,
        property_parts=property_parts,
        document_metadata_paths=document_paths,
        preservation_boundaries=preservation_boundaries,
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=_unique_gates(tuple(gates)),
        evidence_ids=evidence_ids,
    )


def _entry_payloads(plan: ZipArchiveTransactionPlan) -> dict[int, bytes]:
    headers = {header.index: header for header in plan.local_file_headers}
    payloads: dict[int, bytes] = {}
    for entry in plan.central_directory_entries:
        header = headers.get(entry.index)
        if header is None or entry.compression_method != 0:
            payloads[entry.index] = b""
            continue
        payloads[entry.index] = plan.original_bytes[
            header.payload_offset : header.payload_end_offset
        ]
    return payloads


def _build_content_types_plan(
    zip_plan: ZipArchiveTransactionPlan,
    payloads: dict[int, bytes],
    file_extension: str | None,
) -> OoxmlContentTypesPlan:
    for entry in zip_plan.central_directory_entries:
        if entry.file_name != "[Content_Types].xml":
            continue
        main_part, content_type = _main_override(payloads.get(entry.index, b""))
        inferred = _inferred_file_type(content_type, file_extension)
        return OoxmlContentTypesPlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            responsibility="detect_main_document_mime",
            main_part_name=main_part,
            main_content_type=content_type,
            inferred_file_type=inferred,
            evidence_ids=(ZIP_OOXML_DETECTION_SOURCE, OOXML_FILE_TYPE_SOURCE),
        )
    fallback_type = _extension_fallback(file_extension)
    return OoxmlContentTypesPlan(
        file_name=None,
        entry_index=None,
        responsibility="absent",
        main_part_name=None,
        main_content_type=None,
        inferred_file_type=fallback_type,
        evidence_ids=(ZIP_OOXML_DETECTION_SOURCE, OOXML_FILE_TYPE_SOURCE),
    )


def _build_relationships_plan(zip_plan: ZipArchiveTransactionPlan) -> OoxmlRelationshipsPlan:
    names = tuple(
        entry.file_name
        for entry in zip_plan.central_directory_entries
        if entry.file_name == "_rels/.rels"
        or re.fullmatch(r".*/_rels/[^/]+\.rels", entry.file_name) is not None
    )
    if names:
        return OoxmlRelationshipsPlan(
            relationship_entry_names=names,
            responsibility="preserve_package_relationships",
            evidence_ids=(OOXML_NOTES_SOURCE, OOXML_DOCPROPS_SOURCE),
        )
    return OoxmlRelationshipsPlan(
        relationship_entry_names=(),
        responsibility="absent",
        evidence_ids=(OOXML_NOTES_SOURCE, OOXML_DOCPROPS_SOURCE),
    )


def _entry_responsibility(
    entry: ZipCentralDirectoryEntryPlan,
    content_types: OoxmlContentTypesPlan,
) -> OoxmlEntryResponsibilityPlan:
    file_name = entry.file_name
    responsibility: OoxmlEntryResponsibility
    reason: str
    sources: tuple[str, ...]
    if file_name == "[Content_Types].xml":
        responsibility = "content_types_discriminator"
        reason = "ZIP.pm reads this entry to detect the OOXML main document MIME."
        sources = (ZIP_OOXML_DETECTION_SOURCE,)
    elif file_name == "_rels/.rels" or re.fullmatch(r".*/_rels/[^/]+\.rels", file_name):
        responsibility = "package_relationships_preserve"
        reason = "OOXML relationship XML is package structure; ExifTool OOXML reads docProps only."
        sources = (OOXML_NOTES_SOURCE, OOXML_DOCPROPS_SOURCE)
    elif file_name == "docProps/core.xml":
        responsibility = "core_properties_read"
        reason = "Core properties are routed through OOXML XML tag handling."
        sources = (OOXML_TAG_TABLE_SOURCE, OOXML_DOCPROPS_SOURCE)
    elif file_name == "docProps/app.xml":
        responsibility = "app_properties_read"
        reason = "App properties are routed through OOXML XML tag handling."
        sources = (OOXML_TAG_TABLE_SOURCE, OOXML_DOCPROPS_SOURCE)
    elif file_name == "docProps/custom.xml":
        responsibility = "custom_properties_read"
        reason = "Custom properties use queued attributes and dynamic tag naming."
        sources = (OOXML_CUSTOM_PROPERTY_SOURCE, OOXML_VECTOR_SOURCE, OOXML_DOCPROPS_SOURCE)
    elif re.fullmatch(r"docProps/.*\.(xml|XML)", file_name):
        responsibility = "docprops_xml_read"
        reason = "All docProps XML entries are routed to OOXML XML parsing."
        sources = (OOXML_DOCPROPS_SOURCE,)
    elif re.fullmatch(r"docProps/thumbnail\.(jpe?g|wmf)", file_name, flags=re.IGNORECASE):
        responsibility = "docprops_preview_read"
        reason = "docProps thumbnails are routed as preview metadata."
        sources = (OOXML_PREVIEW_SOURCE,)
    elif _entry_is_document_main(file_name, content_types):
        responsibility = "document_main_preserve"
        reason = "The main document part selects file type but is not parsed by OOXML.pm."
        sources = (ZIP_OOXML_DETECTION_SOURCE, OOXML_DOCPROPS_SOURCE)
    elif _is_embedded_media(file_name):
        responsibility = "embedded_media_preserve"
        reason = "Embedded media is outside docProps metadata routing."
        sources = (OOXML_DOCPROPS_SOURCE,)
    elif _is_embedded_document(file_name):
        responsibility = "embedded_document_preserve"
        reason = "Embedded document payloads are outside docProps metadata routing."
        sources = (OOXML_DOCPROPS_SOURCE,)
    elif file_name in ENCRYPTED_PACKAGE_ENTRY_NAMES:
        responsibility = "encrypted_package_block"
        reason = "Encrypted package payloads are not handled by OOXML.pm metadata routing."
        sources = (OOXML_NOTES_SOURCE, OOXML_DOCPROPS_SOURCE)
    else:
        responsibility = "unknown_preserve"
        reason = "Entries outside docProps are preserved by the package plan."
        sources = (OOXML_DOCPROPS_SOURCE,)
    return OoxmlEntryResponsibilityPlan(
        file_name=file_name,
        entry_index=entry.index,
        responsibility=responsibility,
        reason=reason,
        evidence_ids=sources,
    )


def _property_part(entry: ZipCentralDirectoryEntryPlan) -> OoxmlPropertyPartPlan | None:
    family: OoxmlPropertyFamily
    sources: tuple[str, ...]
    if entry.file_name == "docProps/core.xml":
        family = "core"
        sources = (OOXML_TAG_TABLE_SOURCE, OOXML_DOCPROPS_SOURCE)
    elif entry.file_name == "docProps/app.xml":
        family = "app"
        sources = (OOXML_TAG_TABLE_SOURCE, OOXML_DOCPROPS_SOURCE)
    elif entry.file_name == "docProps/custom.xml":
        family = "custom"
        sources = (OOXML_CUSTOM_PROPERTY_SOURCE, OOXML_VECTOR_SOURCE, OOXML_DOCPROPS_SOURCE)
    elif re.fullmatch(r"docProps/.*\.(xml|XML)", entry.file_name):
        family = "other_docprops_xml"
        sources = (OOXML_DOCPROPS_SOURCE,)
    elif re.fullmatch(r"docProps/thumbnail\.(jpe?g|wmf)", entry.file_name, flags=re.IGNORECASE):
        family = "thumbnail_preview"
        sources = (OOXML_PREVIEW_SOURCE,)
    else:
        return None
    return OoxmlPropertyPartPlan(
        file_name=entry.file_name,
        entry_index=entry.index,
        family=family,
        read_responsibility=(
            "extract_metadata" if family != "thumbnail_preview" else "extract_preview"
        ),
        rewrite_responsibility="non_mutating_preserve",
        evidence_ids=sources,
    )


def _document_metadata_paths(
    zip_plan: ZipArchiveTransactionPlan,
    content_types: OoxmlContentTypesPlan,
) -> tuple[OoxmlDocumentMetadataPathPlan, ...]:
    if content_types.main_part_name is None or content_types.inferred_file_type is None:
        return ()
    part_name = content_types.main_part_name.removeprefix("/")
    entry_index = next(
        (
            entry.index
            for entry in zip_plan.central_directory_entries
            if entry.file_name == part_name
        ),
        None,
    )
    return (
        OoxmlDocumentMetadataPathPlan(
            document_part_name=part_name,
            entry_index=entry_index,
            inferred_file_type=content_types.inferred_file_type,
            evidence_ids=(ZIP_OOXML_DETECTION_SOURCE, OOXML_FILE_TYPE_SOURCE),
        ),
    )


def _preservation_boundary(
    entry: ZipCentralDirectoryEntryPlan,
    content_types: OoxmlContentTypesPlan,
) -> OoxmlPreservationBoundaryPlan | None:
    if _is_embedded_media(entry.file_name):
        return OoxmlPreservationBoundaryPlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            boundary_kind="embedded_media",
            reason="Embedded media payloads are preserved outside OOXML docProps routing.",
            evidence_ids=(OOXML_DOCPROPS_SOURCE,),
        )
    if _is_embedded_document(entry.file_name):
        return OoxmlPreservationBoundaryPlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            boundary_kind="embedded_document",
            reason="Embedded document payloads are preserved outside OOXML docProps routing.",
            evidence_ids=(OOXML_DOCPROPS_SOURCE,),
        )
    if entry.file_name == "_rels/.rels" or re.fullmatch(r".*/_rels/[^/]+\.rels", entry.file_name):
        return OoxmlPreservationBoundaryPlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            boundary_kind="structural_xml",
            reason="Relationship XML is preserved as package structure.",
            evidence_ids=(OOXML_NOTES_SOURCE, OOXML_DOCPROPS_SOURCE),
        )
    if _entry_is_document_main(entry.file_name, content_types):
        return OoxmlPreservationBoundaryPlan(
            file_name=entry.file_name,
            entry_index=entry.index,
            boundary_kind="structural_xml",
            reason="The main document part identifies type but is preserved here.",
            evidence_ids=(ZIP_OOXML_DETECTION_SOURCE, OOXML_DOCPROPS_SOURCE),
        )
    return None


def _rewrite_blockers(
    property_parts: tuple[OoxmlPropertyPartPlan, ...],
    content_types: OoxmlContentTypesPlan,
    relationships: OoxmlRelationshipsPlan,
    document_paths: tuple[OoxmlDocumentMetadataPathPlan, ...],
    boundaries: tuple[OoxmlPreservationBoundaryPlan, ...],
) -> tuple[OoxmlRewriteBlocker, ...]:
    blockers: list[OoxmlRewriteBlocker] = []
    for part in property_parts:
        if part.family == "thumbnail_preview":
            continue
        blockers.append(
            OoxmlRewriteBlocker(
                code="docprops_xml_rewrite_not_implemented",
                file_name=part.file_name,
                reason="OOXML.pm extracts docProps XML metadata; this planner does not rewrite it.",
                evidence_ids=part.evidence_ids,
            )
        )
    if content_types.file_name is not None:
        blockers.append(
            OoxmlRewriteBlocker(
                code="content_types_rewrite_not_implemented",
                file_name=content_types.file_name,
                reason="[Content_Types].xml is used for detection and preserved without edits.",
                evidence_ids=content_types.evidence_ids,
            )
        )
    for file_name in relationships.relationship_entry_names:
        blockers.append(
            OoxmlRewriteBlocker(
                code="relationships_rewrite_not_implemented",
                file_name=file_name,
                reason="Relationship XML updates are outside ExifTool OOXML docProps parsing.",
                evidence_ids=relationships.evidence_ids,
            )
        )
    for path in document_paths:
        blockers.append(
            OoxmlRewriteBlocker(
                code="document_part_rewrite_not_implemented",
                file_name=path.document_part_name,
                reason="Main document XML is preserved by this package-level plan.",
                evidence_ids=path.evidence_ids,
            )
        )
    for boundary in boundaries:
        if boundary.boundary_kind in {"embedded_media", "embedded_document"}:
            blockers.append(
                OoxmlRewriteBlocker(
                    code="embedded_payload_rewrite_not_supported",
                    file_name=boundary.file_name,
                    reason="Embedded payload bytes are preservation boundaries.",
                    evidence_ids=boundary.evidence_ids,
                )
            )
    return tuple(blockers)


def _zip_gates(zip_plan: ZipArchiveTransactionPlan) -> tuple[OoxmlOutputEmissionGate, ...]:
    gates: list[OoxmlOutputEmissionGate] = []
    for gate in zip_plan.output_emission_gates:
        if gate.code == "encrypted_entry_blocker":
            gates.append(
                OoxmlOutputEmissionGate(
                    code="encrypted_entry_blocker",
                    reason=gate.reason,
                    evidence_ids=gate.evidence_ids,
                )
            )
        else:
            gates.append(
                OoxmlOutputEmissionGate(
                    code="zip_archive_blocker",
                    reason=f"ZIP archive planning blocked emission: {gate.code}",
                    evidence_ids=gate.evidence_ids,
                )
            )
    return tuple(gates)


def _package_kind(
    zip_plan: ZipArchiveTransactionPlan,
    content_types: OoxmlContentTypesPlan,
    property_parts: tuple[OoxmlPropertyPartPlan, ...],
) -> OoxmlPackageKind:
    if content_types.main_content_type is not None or property_parts:
        return "ooxml"
    if zip_plan.status == "unsupported":
        return "not_ooxml"
    return "not_ooxml"


def _main_override(payload: bytes) -> tuple[str | None, str | None]:
    fallbacks: list[tuple[str, str]] = []
    for attrs in _override_attrs(payload):
        part_name = attrs.get("partname")
        content_type = attrs.get("contenttype")
        if part_name is None or content_type is None:
            continue
        base_content_type = content_type.removesuffix("+xml").removesuffix(".main")
        if part_name in EXPECTED_MAIN_PARTS and ".main" in content_type:
            return part_name, base_content_type
        if ".main" in content_type:
            fallbacks.append((part_name, base_content_type))
    if fallbacks:
        return fallbacks[0]
    return None, None


def _override_attrs(payload: bytes) -> Iterable[dict[str, str]]:
    for match in re.finditer(rb"<Override\b([^>]*)>", payload, flags=re.IGNORECASE | re.DOTALL):
        attrs: dict[str, str] = {}
        for attr in re.finditer(
            rb"([A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*(['\"])(.*?)\2",
            match.group(1),
            flags=re.DOTALL,
        ):
            attrs[attr.group(1).decode("ascii", errors="ignore").lower()] = attr.group(3).decode(
                "utf-8", errors="replace"
            )
        yield attrs


def _inferred_file_type(content_type: str | None, file_extension: str | None) -> str | None:
    if content_type is None:
        return _extension_fallback(file_extension)
    file_type = OOXML_MAIN_MIME_TO_TYPE.get(content_type.lower())
    if file_type == "PPTX" and _normalized_extension(file_extension) == "THMX":
        return "THMX"
    if file_type is not None:
        return file_type
    return _extension_fallback(file_extension) or "DOCX"


def _extension_fallback(file_extension: str | None) -> str | None:
    normalized = _normalized_extension(file_extension)
    if normalized in OOXML_EXTENSION_TYPES:
        return normalized
    return None


def _normalized_extension(file_extension: str | None) -> str | None:
    if file_extension is None:
        return None
    return file_extension.lstrip(".").upper()


def _entry_is_document_main(
    file_name: str,
    content_types: OoxmlContentTypesPlan,
) -> bool:
    if content_types.main_part_name is not None:
        return file_name == content_types.main_part_name.removeprefix("/")
    return file_name in {"word/document.xml", "ppt/presentation.xml", "xl/workbook.xml"}


def _is_embedded_media(file_name: str) -> bool:
    return re.fullmatch(r"(word|ppt|xl)/media/.+", file_name) is not None


def _is_embedded_document(file_name: str) -> bool:
    return re.fullmatch(r"(word|ppt|xl)/embeddings/.+", file_name) is not None


def _unsupported_gate_exists(gates: list[OoxmlOutputEmissionGate]) -> bool:
    return any(gate.code != "non_mutating_plan_requires_explicit_emission" for gate in gates)


def _unique_gates(
    gates: tuple[OoxmlOutputEmissionGate, ...],
) -> tuple[OoxmlOutputEmissionGate, ...]:
    seen: set[tuple[OoxmlEmissionGateCode, str]] = set()
    unique: list[OoxmlOutputEmissionGate] = []
    for gate in gates:
        key = (gate.code, gate.reason)
        if key not in seen:
            seen.add(key)
            unique.append(gate)
    return tuple(unique)


def _unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for reference in references:
        if reference not in seen:
            seen.add(reference)
            unique.append(reference)
    return tuple(unique)


install_evidence_reference_compat(globals())
