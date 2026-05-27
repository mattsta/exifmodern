"""Shared ExifTool ProcessTIFF-compatible nested TIFF reader records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.tiff.primitives import inspect_ifd0, materialize_tiff_embedded_images
from exifmodern.json_types import JsonArray, JsonObject, JsonValue, json_string_array_or_none

type ProcessTiffGroup = Literal["IFD0", "ExifIFD", "GPS", "IFD1"]
type ProcessTiffScalar = str | int | float | bool | None | list[str]
type EvidenceId = str
type ProcessTiffDiagnosticCode = Literal["malformed_tiff_payload"]
type ProcessTiffBinaryBlockerStatus = Literal[
    "pair_present_extraction_deferred",
    "missing_start",
    "missing_length",
    "missing_start_and_length",
    "zero_length",
    "negative_start",
    "negative_length",
    "negative_exif_data_pos",
    "out_of_buffer_or_file_relative",
    "out_of_file_bounds",
]

PROCESS_TIFF_MAIN_SOURCE = "tiff.process.main"
PROCESS_TIFF_SUBIFD_SOURCE = "tiff.process.subifd"
PROCESS_TIFF_IFD1_THUMBNAIL_SOURCE = "tiff.process.ifd1_thumbnail"
PROCESS_TIFF_EXTRACT_IMAGE_SOURCE = "tiff.process.extract_image"

_PROCESS_TIFF_POINTER_TAGS = {"ExifIFDPointer", "GPSInfoIFDPointer"}
_PROCESS_TIFF_EXTRA_TAG_IDS = {
    "Noise": "0x920D",
}
_PROCESS_TIFF_TAG_IDS = {
    "ImageDescription": "0x010E",
    "Make": "0x010F",
    "Model": "0x0110",
    "Orientation": "0x0112",
    "XResolution": "0x011A",
    "YResolution": "0x011B",
    "ResolutionUnit": "0x0128",
    "Software": "0x0131",
    "ModifyDate": "0x0132",
    "Artist": "0x013B",
    "YCbCrPositioning": "0x0213",
    "Copyright": "0x8298",
    "GPSVersionID": "0x0000",
    "GPSLatitudeRef": "0x0001",
    "GPSLatitude": "0x0002",
    "GPSLongitudeRef": "0x0003",
    "GPSLongitude": "0x0004",
    "GPSAltitudeRef": "0x0005",
    "GPSAltitude": "0x0006",
    "GPSTimeStamp": "0x0007",
    "GPSMapDatum": "0x0012",
    "GPSDateStamp": "0x001D",
    "FNumber": "0x829D",
    "ExposureProgram": "0x8822",
    "ISO": "0x8827",
    "ExifVersion": "0x9000",
    "DateTimeOriginal": "0x9003",
    "CreateDate": "0x9004",
    "ComponentsConfiguration": "0x9101",
    "CompressedBitsPerPixel": "0x9102",
    "ShutterSpeedValue": "0x9201",
    "ApertureValue": "0x9202",
    "BrightnessValue": "0x9203",
    "ExposureCompensation": "0x9204",
    "MaxApertureValue": "0x9205",
    "MeteringMode": "0x9207",
    "Flash": "0x9209",
    "FlashpixVersion": "0xA000",
    "ColorSpace": "0xA001",
    "ExifImageWidth": "0xA002",
    "ExifImageHeight": "0xA003",
    "FocalPlaneXResolution": "0xA20E",
    "FocalPlaneYResolution": "0xA20F",
    "FocalPlaneResolutionUnit": "0xA210",
    "SensingMethod": "0xA217",
    "FileSource": "0xA300",
    "SceneType": "0xA301",
    "Compression": "0x0103",
    "ThumbnailOffset": "0x0201",
    "ThumbnailLength": "0x0202",
    **_PROCESS_TIFF_EXTRA_TAG_IDS,
}


@dataclass(frozen=True)
class ProcessTiffTag:
    name: str
    group: ProcessTiffGroup
    source_table: str
    tag_id: str
    value: ProcessTiffScalar
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class ProcessTiffDiagnostic:
    code: ProcessTiffDiagnosticCode
    detail: str
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class ProcessTiffBinaryBlocker:
    group: str
    data_tag: str
    status: ProcessTiffBinaryBlockerStatus
    start: int | None
    length: int | None
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class ProcessTiffResult:
    tags: tuple[ProcessTiffTag, ...]
    diagnostics: tuple[ProcessTiffDiagnostic, ...]
    binary_blockers: tuple[ProcessTiffBinaryBlocker, ...]
    evidence_ids: tuple[EvidenceId, ...]


def process_tiff_payload(
    data: bytes,
    route_sources: tuple[EvidenceId, ...] = (),
) -> ProcessTiffResult:
    """Process a nested TIFF payload through the shared Exif.pm-compatible slice."""

    evidence_ids = _unique_evidence_ids((*route_sources, PROCESS_TIFF_MAIN_SOURCE))
    try:
        inspection = inspect_ifd0(data)
    except ValueError as error:
        return ProcessTiffResult(
            tags=(),
            diagnostics=(
                ProcessTiffDiagnostic(
                    code="malformed_tiff_payload",
                    detail=f"ProcessTIFF payload could not be parsed: {error}",
                    evidence_ids=evidence_ids,
                ),
            ),
            binary_blockers=(),
            evidence_ids=evidence_ids,
        )
    tags = tuple(_process_tiff_tags(inspection, evidence_ids))
    return ProcessTiffResult(
        tags=tags,
        diagnostics=(),
        binary_blockers=_binary_blockers(data, evidence_ids),
        evidence_ids=evidence_ids,
    )


def _process_tiff_tags(
    inspection: JsonObject,
    route_sources: tuple[EvidenceId, ...],
) -> tuple[ProcessTiffTag, ...]:
    tags: list[ProcessTiffTag] = []
    group_specs: tuple[tuple[ProcessTiffGroup, str], ...] = (
        ("IFD0", "ifd0_values"),
        ("ExifIFD", "exif_ifd_values"),
        ("GPS", "gps_ifd_values"),
        ("IFD1", "ifd1_values"),
    )
    for group, values_key in group_specs:
        values = inspection.get(values_key)
        if not isinstance(values, dict):
            continue
        for name, value in values.items():
            if name in _PROCESS_TIFF_POINTER_TAGS:
                continue
            scalar = _process_tiff_scalar(name, value)
            if scalar is None and value is not None:
                continue
            tags.append(
                ProcessTiffTag(
                    name=name,
                    group=group,
                    source_table=_process_tiff_source_table(group),
                    tag_id=_PROCESS_TIFF_TAG_IDS.get(name, name),
                    value=scalar,
                    evidence_ids=_group_sources(group, route_sources),
                )
            )
    return tuple(tags)


def _process_tiff_scalar(name: str, value: JsonValue) -> ProcessTiffScalar | None:
    if isinstance(value, dict):
        return None
    if isinstance(value, list):
        return _json_string_array_or_none(value)
    if name == "CompressedBitsPerPixel" and isinstance(value, float):
        return round(value, 9)
    if name == "BrightnessValue" and isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _json_string_array_or_none(value: JsonArray) -> list[str] | None:
    return json_string_array_or_none(value)


def _process_tiff_source_table(group: ProcessTiffGroup) -> str:
    if group == "GPS":
        return "Image::ExifTool::GPS::Main"
    if group == "ExifIFD":
        return "Image::ExifTool::Exif::ExifIFD"
    return "Image::ExifTool::Exif::Main"


def _group_sources(
    group: ProcessTiffGroup,
    route_sources: tuple[EvidenceId, ...],
) -> tuple[EvidenceId, ...]:
    if group == "IFD1":
        return _unique_evidence_ids(
            (*route_sources, PROCESS_TIFF_MAIN_SOURCE, PROCESS_TIFF_IFD1_THUMBNAIL_SOURCE)
        )
    if group in {"ExifIFD", "GPS"}:
        return _unique_evidence_ids(
            (*route_sources, PROCESS_TIFF_MAIN_SOURCE, PROCESS_TIFF_SUBIFD_SOURCE)
        )
    return _unique_evidence_ids((*route_sources, PROCESS_TIFF_MAIN_SOURCE))


def _binary_blockers(
    data: bytes,
    route_sources: tuple[EvidenceId, ...],
) -> tuple[ProcessTiffBinaryBlocker, ...]:
    report = materialize_tiff_embedded_images(data)
    blockers: list[ProcessTiffBinaryBlocker] = []
    for image in report.images:
        if image.status == "extracted":
            continue
        blockers.append(
            ProcessTiffBinaryBlocker(
                group=image.context,
                data_tag=image.data_tag,
                status=image.status,
                start=image.start,
                length=image.length,
                evidence_ids=_unique_evidence_ids(
                    (*route_sources, PROCESS_TIFF_EXTRACT_IMAGE_SOURCE)
                ),
            )
        )
    return tuple(blockers)


def _unique_evidence_ids(evidence_ids: tuple[EvidenceId, ...]) -> tuple[EvidenceId, ...]:
    unique: list[EvidenceId] = []
    seen: set[EvidenceId] = set()
    for evidence_id in evidence_ids:
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        unique.append(evidence_id)
    return tuple(unique)
