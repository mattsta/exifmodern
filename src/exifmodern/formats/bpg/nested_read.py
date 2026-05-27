"""BPG-local nested metadata extraction records.

The BPG reader delegates extension payloads to EXIF/TIFF, ICC, and XMP
processors.  This module keeps that handoff package-local and only promotes
payloads through existing reusable readers when they accept the bytes directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.bpg.image_transaction_plan import (
    BPG_EXIF_PADDING_SOURCE,
    BPG_EXTENSION_TABLE_SOURCE,
    BpgEvidenceId,
    BpgExtensionPlan,
    BpgImageTransactionPlan,
)
from exifmodern.formats.icc.reader import parse_icc_header_tags, parse_icc_profile_tags
from exifmodern.formats.tiff.primitives import inspect_ifd0
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.json_types import JsonArray, JsonObject, JsonValue, json_string_array_or_none

type BpgNestedPayloadKind = Literal["exif", "icc_profile", "xmp"]
type BpgNestedExtractionStatus = Literal["extracted", "unsupported_payload"]
type BpgNestedTagValue = str | int | float | bool | None | list[str]

TIFF_POINTER_TAG_NAMES = {"ExifIFDPointer", "GPSInfoIFDPointer"}
XMP_COMPONENT_CONFIGURATION_PRINT = {
    "0": "-",
    "1": "Y",
    "2": "Cb",
    "3": "Cr",
    "4": "R",
    "5": "G",
    "6": "B",
}

BPG_EXIF_SUBDIRECTORY_SOURCE = "bpg.nested.exif_subdirectory"
BPG_ICC_SUBDIRECTORY_SOURCE = "bpg.nested.icc_subdirectory"
BPG_XMP_SUBDIRECTORY_SOURCE = "bpg.nested.xmp_subdirectory"
BPG_EXIF_PROCESS_TIFF_SOURCE = "bpg.nested.exif_process_tiff"
BPG_XMP_PROCESS_SOURCE = "bpg.nested.xmp_process"
BPG_XMP_PROCESS_PROC_SOURCE = "bpg.nested.xmp_process_proc"
BPG_ICC_MAIN_SOURCE = "bpg.nested.icc_main"
BPG_ICC_HEADER_SOURCE = "bpg.nested.icc_header"


@dataclass(frozen=True)
class BpgNestedTag:
    group: str
    name: str
    value: BpgNestedTagValue
    table_name: str
    source: str


@dataclass(frozen=True)
class BpgNestedPayloadExtraction:
    extension_index: int
    extension_type_code: int
    kind: BpgNestedPayloadKind
    name: str
    payload_offset: int
    payload_length: int
    logical_payload_offset: int
    logical_payload_length: int
    ignored_exif_padding: bool
    target_table: str
    process_proc: str | None
    status: BpgNestedExtractionStatus
    tags: tuple[BpgNestedTag, ...]
    reason: str | None
    evidence_ids: tuple[BpgEvidenceId, ...]


def extract_bpg_nested_payloads(
    plan: BpgImageTransactionPlan,
    data: bytes,
) -> tuple[BpgNestedPayloadExtraction, ...]:
    records: list[BpgNestedPayloadExtraction] = []
    for extension in plan.extensions:
        if extension.kind not in {"exif", "icc_profile", "xmp"}:
            continue
        payload = data[
            extension.logical_payload_offset : extension.logical_payload_offset
            + extension.logical_payload_length
        ]
        records.append(_extract_nested_payload(extension, payload))
    return tuple(records)


def _extract_nested_payload(
    extension: BpgExtensionPlan,
    payload: bytes,
) -> BpgNestedPayloadExtraction:
    if extension.kind == "exif":
        return _exif_extraction(extension, payload)
    if extension.kind == "icc_profile":
        return _icc_extraction(extension, payload)
    return _xmp_extraction(extension, payload)


def _exif_extraction(
    extension: BpgExtensionPlan,
    payload: bytes,
) -> BpgNestedPayloadExtraction:
    sources = _nested_sources(
        extension,
        (BPG_EXIF_SUBDIRECTORY_SOURCE, BPG_EXIF_PROCESS_TIFF_SOURCE),
    )
    try:
        inspection = inspect_ifd0(payload)
    except ValueError as exc:
        return _unsupported_record(
            extension,
            "Image::ExifTool::Exif::Main",
            "Image::ExifTool::ProcessTIFF",
            f"EXIF payload could not be parsed as TIFF: {exc}.",
            sources,
        )
    tags = [
        BpgNestedTag(
            group="File",
            name="ExifByteOrder",
            value=_string_value(inspection.get("byte_order")),
            table_name="Image::ExifTool::Exif::Main",
            source=f"bpg-nested-exif:{extension.index}:ExifByteOrder",
        )
    ]
    tags.extend(_tiff_inspection_tags(inspection, extension.index))
    return _extracted_record(
        extension,
        "Image::ExifTool::Exif::Main",
        "Image::ExifTool::ProcessTIFF",
        tuple(tags),
        sources,
    )


def _icc_extraction(
    extension: BpgExtensionPlan,
    payload: bytes,
) -> BpgNestedPayloadExtraction:
    sources = _nested_sources(
        extension,
        (BPG_ICC_SUBDIRECTORY_SOURCE, BPG_ICC_MAIN_SOURCE, BPG_ICC_HEADER_SOURCE),
    )
    try:
        values = {**parse_icc_header_tags(payload), **parse_icc_profile_tags(payload)}
    except ValueError as exc:
        return _unsupported_record(
            extension,
            "Image::ExifTool::ICC_Profile::Main",
            None,
            f"ICC_Profile payload could not be parsed: {exc}.",
            sources,
        )
    tags: list[BpgNestedTag] = []
    for name, value in values.items():
        tag_value = _json_scalar_or_string_list(value)
        if tag_value is None and value is not None:
            continue
        tags.append(
            BpgNestedTag(
                group=_icc_group_name(name),
                name=name,
                value=tag_value,
                table_name=_icc_table_name(name),
                source=f"bpg-nested-icc:{extension.index}:{name}",
            )
        )
    return _extracted_record(
        extension,
        "Image::ExifTool::ICC_Profile::Main",
        None,
        tuple(tags),
        sources,
    )


def _xmp_extraction(
    extension: BpgExtensionPlan,
    payload: bytes,
) -> BpgNestedPayloadExtraction:
    sources = _nested_sources(
        extension,
        (BPG_XMP_SUBDIRECTORY_SOURCE, BPG_XMP_PROCESS_SOURCE, BPG_XMP_PROCESS_PROC_SOURCE),
    )
    try:
        values_by_group = parse_xmp_packet(payload)
    except (ValueError, SyntaxError) as exc:
        return _unsupported_record(
            extension,
            "Image::ExifTool::XMP::Main",
            "Image::ExifTool::XMP::ProcessXMP",
            f"XMP payload could not be parsed: {exc}.",
            sources,
        )
    tags: list[BpgNestedTag] = []
    for group, values in values_by_group.items():
        for name, value in values.items():
            if group == "XMP-rdf" and name == "About":
                continue
            tag_value = _xmp_tag_value(group, name, value)
            if tag_value is None and value is not None:
                continue
            tags.append(
                BpgNestedTag(
                    group=group,
                    name=name,
                    value=tag_value,
                    table_name=_xmp_table_name(group),
                    source=f"bpg-nested-xmp:{extension.index}:{group}:{name}",
                )
            )
    return _extracted_record(
        extension,
        "Image::ExifTool::XMP::Main",
        "Image::ExifTool::XMP::ProcessXMP",
        tuple(tags),
        sources,
    )


def _tiff_inspection_tags(inspection: JsonObject, extension_index: int) -> list[BpgNestedTag]:
    tags: list[BpgNestedTag] = []
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
            if name in TIFF_POINTER_TAG_NAMES:
                continue
            tag_value = _json_scalar_or_string_list(value)
            if name in {"FocalPlaneXResolution", "FocalPlaneYResolution"} and isinstance(
                tag_value,
                float,
            ):
                tag_value = round(tag_value, 6)
            if tag_value is None:
                continue
            tags.append(
                BpgNestedTag(
                    group=group,
                    name=name,
                    value=tag_value,
                    table_name=_exif_table_name(group),
                    source=f"bpg-nested-exif:{extension_index}:{group}:{name}",
                )
            )
    return tags


def _extracted_record(
    extension: BpgExtensionPlan,
    target_table: str,
    process_proc: str | None,
    tags: tuple[BpgNestedTag, ...],
    sources: tuple[BpgEvidenceId, ...],
) -> BpgNestedPayloadExtraction:
    kind = _nested_payload_kind(extension)
    return BpgNestedPayloadExtraction(
        extension_index=extension.index,
        extension_type_code=extension.type_code,
        kind=kind,
        name=extension.name,
        payload_offset=extension.payload_offset,
        payload_length=extension.payload_length,
        logical_payload_offset=extension.logical_payload_offset,
        logical_payload_length=extension.logical_payload_length,
        ignored_exif_padding=extension.ignored_exif_padding,
        target_table=target_table,
        process_proc=process_proc,
        status="extracted",
        tags=tags,
        reason=None,
        evidence_ids=sources,
    )


def _unsupported_record(
    extension: BpgExtensionPlan,
    target_table: str,
    process_proc: str | None,
    reason: str,
    sources: tuple[BpgEvidenceId, ...],
) -> BpgNestedPayloadExtraction:
    kind = _nested_payload_kind(extension)
    return BpgNestedPayloadExtraction(
        extension_index=extension.index,
        extension_type_code=extension.type_code,
        kind=kind,
        name=extension.name,
        payload_offset=extension.payload_offset,
        payload_length=extension.payload_length,
        logical_payload_offset=extension.logical_payload_offset,
        logical_payload_length=extension.logical_payload_length,
        ignored_exif_padding=extension.ignored_exif_padding,
        target_table=target_table,
        process_proc=process_proc,
        status="unsupported_payload",
        tags=(),
        reason=reason,
        evidence_ids=sources,
    )


def _nested_payload_kind(extension: BpgExtensionPlan) -> BpgNestedPayloadKind:
    if extension.kind == "exif":
        return "exif"
    if extension.kind == "icc_profile":
        return "icc_profile"
    if extension.kind == "xmp":
        return extension.kind
    raise ValueError(f"BPG extension is not nested metadata: {extension.kind}")


def _nested_sources(
    extension: BpgExtensionPlan,
    sources: tuple[BpgEvidenceId, ...],
) -> tuple[BpgEvidenceId, ...]:
    extension_sources = (BPG_EXTENSION_TABLE_SOURCE, *extension.evidence_ids)
    if extension.ignored_exif_padding:
        extension_sources = (*extension_sources, BPG_EXIF_PADDING_SOURCE)
    return _unique_evidence_ids((*extension_sources, *sources))


def _json_scalar_or_string_list(value: JsonValue) -> BpgNestedTagValue | None:
    if isinstance(value, dict):
        return None
    if isinstance(value, list):
        return _json_string_array_or_none(value)
    return value


def _json_string_array_or_none(value: JsonArray) -> list[str] | None:
    return json_string_array_or_none(value)


def _string_value(value: JsonValue | None) -> str:
    if isinstance(value, str):
        return value
    return ""


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


def _icc_group_name(name: str) -> str:
    if _icc_table_name(name) == "Image::ExifTool::ICC_Profile::Header":
        return "ICC-header"
    return "ICC_Profile"


def _xmp_tag_value(group: str, name: str, value: JsonValue) -> BpgNestedTagValue | None:
    tag_value = _json_scalar_or_string_list(value)
    if group == "XMP-tiff" and name == "YCbCrPositioning" and tag_value == "1":
        return "Centered"
    if group == "XMP-tiff" and name == "YCbCrPositioning" and tag_value == "2":
        return "Co-sited"
    if name == "ComponentsConfiguration" and isinstance(tag_value, list):
        return [XMP_COMPONENT_CONFIGURATION_PRINT.get(item, item) for item in tag_value]
    return tag_value


def _xmp_table_name(group: str) -> str:
    if group.startswith("XMP-"):
        return f"Image::ExifTool::XMP::{group[4:]}"
    return "Image::ExifTool::XMP::Main"


def _unique_evidence_ids(sources: tuple[BpgEvidenceId, ...]) -> tuple[BpgEvidenceId, ...]:
    unique: list[BpgEvidenceId] = []
    seen: set[BpgEvidenceId] = set()
    for source_id in sources:
        if source_id not in seen:
            seen.add(source_id)
            unique.append(source_id)
    return tuple(unique)
