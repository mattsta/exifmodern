"""Olympus MakerNote reader slice backed by ExifTool Olympus.pm."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from exifmodern.formats.jpeg.container import (
    read_exif_app1,
    tiff_entry_raw_value_location,
    tiff_long_tag_value,
)
from exifmodern.formats.maker_notes import render_maker_note_package_runtime_print_value
from exifmodern.formats.maker_notes.context import MakerNoteRuntimeContext, maker_note_self_context
from exifmodern.formats.tiff.primitives import (
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)
from exifmodern.public_interface.unknown import (
    ProcessBinaryDataKnownSpan,
    ProcessBinaryDataUnknownReadResult,
    ProcessBinaryDataUnknownReadTag,
    ProcessBinaryDataUnknownTablePolicy,
    process_binarydata_unknown_tags_from_payload,
)

type OlympusRawValue = (
    int | str | float | bytes | Fraction | list[int] | list[Fraction | None] | None
)


@dataclass(frozen=True)
class OlympusMakerNoteField:
    name: str
    value: str | int | float
    tag_id: int
    family_2_group: str = "Camera"


@dataclass(frozen=True)
class OlympusMakerNoteReadResult:
    fields: tuple[OlympusMakerNoteField, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class OlympusBinaryDataPayload:
    payload: bytes
    table_name: str
    evidence_ids: tuple[str, ...]


OLYMPUS_SOURCE_TABLE = "Image::ExifTool::Olympus::Main"
OLYMPUS_SOURCE_MODULE = "Image::ExifTool::Olympus"
OLYMPUS_AFTARGETINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "olympus-aftargetinfo-process-binarydata-unknown"
)
OLYMPUS_SUBJECTDETECTINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "olympus-subjectdetectinfo-process-binarydata-unknown"
)
OLYMPUS_AFTARGETINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "olympus.read.camera_settings_route",
    "olympus.read.aftargetinfo_route",
    "olympus.read.aftargetinfo_binarydata_policy",
    "olympus.read.aftargetinfo_unknown_scan",
    "olympus.read.aftargetinfo_unknown_prefix",
)
OLYMPUS_SUBJECTDETECTINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "olympus.read.camera_settings_route",
    "olympus.read.subjectdetectinfo_route",
    "olympus.read.subjectdetectinfo_binarydata_policy",
    "olympus.read.subjectdetectinfo_unknown_scan",
    "olympus.read.subjectdetectinfo_unknown_prefix",
)
_TAG_NAMES = {
    0x0200: "SpecialMode",
    0x0201: "Quality",
    0x0202: "Macro",
    0x0203: "BWMode",
    0x0204: "DigitalZoom",
    0x0205: "FocalPlaneDiagonal",
    0x0206: "LensDistortionParams",
    0x0207: "CameraType",
    0x0209: "CameraID",
}
_PACKAGE_PRINT_TAGS = frozenset(
    {
        "SpecialMode",
        "Quality",
        "Macro",
        "BWMode",
        "DigitalZoom",
        "FocalPlaneDiagonal",
        "CameraType",
    }
)
type OlympusProcessBinaryUnknownReadTag = ProcessBinaryDataUnknownReadTag
type OlympusProcessBinaryUnknownReadResult = ProcessBinaryDataUnknownReadResult
_CAMERA_SETTINGS_TAG = 0x2020
_AF_TARGET_INFO_TAG = 0x030A
_SUBJECT_DETECT_INFO_TAG = 0x030B
_OLYMPUS_INT16U_FIELD_SIZE = 2
_OLYMPUS_AF_TARGET_INFO_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Olympus_AFTargetInfo",
    first_entry=0,
    increment=_OLYMPUS_INT16U_FIELD_SIZE,
    known_spans=(
        ProcessBinaryDataKnownSpan(start_index=0, entry_count=2),
        ProcessBinaryDataKnownSpan(start_index=2, entry_count=4),
        ProcessBinaryDataKnownSpan(start_index=6, entry_count=4),
    ),
    evidence_ids=OLYMPUS_AFTARGETINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    byte_order="little",
)
_OLYMPUS_SUBJECT_DETECT_INFO_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Olympus_SubjectDetectInfo",
    first_entry=0,
    increment=_OLYMPUS_INT16U_FIELD_SIZE,
    known_spans=(
        ProcessBinaryDataKnownSpan(start_index=0, entry_count=2),
        ProcessBinaryDataKnownSpan(start_index=2, entry_count=4),
        ProcessBinaryDataKnownSpan(start_index=6, entry_count=4),
    ),
    evidence_ids=OLYMPUS_SUBJECTDETECTINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    byte_order="little",
)


def read_olympus_maker_note_from_jpeg(path: Path) -> OlympusMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return OlympusMakerNoteReadResult(
            (), ("Olympus MakerNote blocked: missing ExifIFD pointer.",)
        )
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    entry = next((candidate for candidate in exif_ifd.entries if candidate.tag_id == 0x927C), None)
    if entry is None:
        return OlympusMakerNoteReadResult((), ("Olympus MakerNote blocked: missing tag 0x927c.",))
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, entry, header.endian)
    if raw_location is None:
        return OlympusMakerNoteReadResult(
            (), ("Olympus MakerNote blocked: raw value is truncated.",)
        )
    maker_offset, raw = raw_location
    if not raw.startswith((b"OLYMP\x00", b"EPSON\x00")):
        return OlympusMakerNoteReadResult(
            (), ("Olympus MakerNote blocked: missing OLYMP/EPSON header.",)
        )
    try:
        maker_ifd = parse_ifd(exif.tiff_data, maker_offset + 8, "little")
    except ValueError as exc:
        return OlympusMakerNoteReadResult((), (f"Olympus MakerNote blocked: {exc}",))
    context = _runtime_context(exif.tiff_data, maker_ifd.entries)
    return OlympusMakerNoteReadResult(
        tuple(
            _field(exif.tiff_data, entry, context)
            for entry in maker_ifd.entries
            if entry.tag_id in _TAG_NAMES
        ),
        (
            "Olympus MakerNote bridge ready: MakerNotes.pm MakerNoteOlympus routed "
            "OLYMP header to Olympus.pm Main.",
        ),
    )


def collect_olympus_aftargetinfo_process_binary_unknown_read_tags(
    path: Path,
) -> OlympusProcessBinaryUnknownReadResult:
    return _collect_olympus_process_binary_unknown_read_tags(
        path,
        _AF_TARGET_INFO_TAG,
        _OLYMPUS_AF_TARGET_INFO_POLICY,
        "Olympus AFTargetInfo",
    )


def collect_olympus_subjectdetectinfo_process_binary_unknown_read_tags(
    path: Path,
) -> OlympusProcessBinaryUnknownReadResult:
    return _collect_olympus_process_binary_unknown_read_tags(
        path,
        _SUBJECT_DETECT_INFO_TAG,
        _OLYMPUS_SUBJECT_DETECT_INFO_POLICY,
        "Olympus SubjectDetectInfo",
    )


def _collect_olympus_process_binary_unknown_read_tags(
    path: Path,
    binary_data_tag_id: int,
    policy: ProcessBinaryDataUnknownTablePolicy,
    diagnostic_prefix: str,
) -> OlympusProcessBinaryUnknownReadResult:
    payload_result = _olympus_camerasettings_binary_data_payload(path, binary_data_tag_id, policy)
    if isinstance(payload_result, OlympusMakerNoteReadResult):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=tuple(
                diagnostic.replace(
                    "Olympus MakerNote blocked",
                    f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked",
                )
                for diagnostic in payload_result.diagnostics
            ),
            evidence_ids=policy.evidence_ids,
        )
    result = process_binarydata_unknown_tags_from_payload(payload_result.payload, policy)
    return ProcessBinaryDataUnknownReadResult(
        tags=result.tags,
        diagnostics=tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        evidence_ids=result.evidence_ids,
    )


def _olympus_camerasettings_binary_data_payload(
    path: Path,
    binary_data_tag_id: int,
    policy: ProcessBinaryDataUnknownTablePolicy,
) -> OlympusBinaryDataPayload | OlympusMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return OlympusMakerNoteReadResult(
            (), ("Olympus MakerNote blocked: missing ExifIFD pointer.",)
        )
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    maker_note_entry = next(
        (candidate for candidate in exif_ifd.entries if candidate.tag_id == 0x927C),
        None,
    )
    if maker_note_entry is None:
        return OlympusMakerNoteReadResult((), ("Olympus MakerNote blocked: missing tag 0x927c.",))
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return OlympusMakerNoteReadResult(
            (), ("Olympus MakerNote blocked: raw value is truncated.",)
        )
    maker_offset, raw = raw_location
    if not raw.startswith((b"OLYMP\x00", b"EPSON\x00")):
        return OlympusMakerNoteReadResult(
            (), ("Olympus MakerNote blocked: missing OLYMP/EPSON header.",)
        )
    try:
        maker_ifd = parse_ifd(exif.tiff_data, maker_offset + 8, "little")
    except ValueError as exc:
        return OlympusMakerNoteReadResult((), (f"Olympus MakerNote blocked: {exc}",))
    camera_settings_entry = next(
        (candidate for candidate in maker_ifd.entries if candidate.tag_id == _CAMERA_SETTINGS_TAG),
        None,
    )
    if camera_settings_entry is None:
        return OlympusMakerNoteReadResult(
            (), ("Olympus MakerNote blocked: missing CameraSettings tag 0x2020.",)
        )
    camera_settings_location = tiff_entry_raw_value_location(
        exif.tiff_data,
        camera_settings_entry,
        "little",
    )
    if camera_settings_location is None:
        return OlympusMakerNoteReadResult(
            (), ("Olympus MakerNote blocked: CameraSettings value is truncated.",)
        )
    camera_settings_offset, _camera_settings_payload = camera_settings_location
    try:
        camera_settings_ifd = parse_ifd(exif.tiff_data, camera_settings_offset, "little")
    except ValueError as exc:
        return OlympusMakerNoteReadResult((), (f"Olympus MakerNote blocked: CameraSettings {exc}",))
    binary_data_entry = next(
        (
            candidate
            for candidate in camera_settings_ifd.entries
            if candidate.tag_id == binary_data_tag_id
        ),
        None,
    )
    if binary_data_entry is None:
        return OlympusMakerNoteReadResult(
            (),
            (
                "Olympus MakerNote blocked: missing "
                f"{policy.tag_prefix} source tag 0x{binary_data_tag_id:04x}.",
            ),
        )
    binary_data_location = tiff_entry_raw_value_location(
        exif.tiff_data,
        binary_data_entry,
        "little",
    )
    if binary_data_location is None:
        return OlympusMakerNoteReadResult(
            (), (f"Olympus MakerNote blocked: {policy.tag_prefix} value is truncated.",)
        )
    _binary_data_offset, binary_data_payload = binary_data_location
    return OlympusBinaryDataPayload(
        payload=binary_data_payload,
        table_name=policy.tag_prefix,
        evidence_ids=policy.evidence_ids,
    )


def _field(
    data: bytes,
    entry: IfdEntry,
    runtime_context: MakerNoteRuntimeContext | None = None,
) -> OlympusMakerNoteField:
    context = runtime_context or _runtime_context(data, ())
    name = _TAG_NAMES[entry.tag_id]
    if name == "LensDistortionParams":
        lens_rendered = " ".join(
            str(_read_s16(data, entry.value_offset + index * 2)) for index in range(entry.count)
        )
        return OlympusMakerNoteField(name, lens_rendered, entry.tag_id)
    value = read_entry_value(data, entry, "little")
    rendered = _package_or_raw(name, value, context)
    return OlympusMakerNoteField(name, rendered, entry.tag_id)


def _runtime_context(
    data: bytes, entries: tuple[IfdEntry, ...] | list[IfdEntry]
) -> MakerNoteRuntimeContext:
    camera_type = _raw_camera_type(data, entries)
    return MakerNoteRuntimeContext(
        values=(maker_note_self_context(("CameraType",), camera_type or ""),)
    )


def _raw_camera_type(data: bytes, entries: tuple[IfdEntry, ...] | list[IfdEntry]) -> str | None:
    camera_type_entry = next((entry for entry in entries if entry.tag_id == 0x0207), None)
    if camera_type_entry is None:
        return None
    value = read_entry_value(data, camera_type_entry, "little")
    if isinstance(value, str):
        return value.rstrip()
    if isinstance(value, bytes):
        return value.rstrip(b"\x00 ").decode("ascii", errors="replace")
    return None


def _package_or_raw(
    tag_name: str,
    value: OlympusRawValue,
    runtime_context: MakerNoteRuntimeContext,
) -> str | int | float:
    if tag_name in _PACKAGE_PRINT_TAGS:
        package_value = _package_print(tag_name, _package_raw_key(value), runtime_context)
        if package_value is not None:
            return package_value
    if tag_name == "DigitalZoom" and isinstance(value, Fraction):
        return f"{float(value):.1f}"
    if tag_name == "FocalPlaneDiagonal" and isinstance(value, Fraction):
        return f"{_fraction_decimal(value)} mm"
    return _render_raw_value(value)


def _package_raw_key(value: OlympusRawValue) -> str | int:
    if isinstance(value, list):
        return " ".join("" if part is None else str(part) for part in value)
    if isinstance(value, bytes):
        return value.rstrip(b"\x00").decode("ascii", errors="replace")
    if isinstance(value, Fraction):
        return _fraction_decimal(value)
    if isinstance(value, float):
        return str(value)
    if value is None:
        return ""
    return value


def _render_raw_value(value: OlympusRawValue) -> str | int | float:
    if isinstance(value, int | float):
        return value
    if isinstance(value, bytes):
        return value.rstrip(b"\x00").decode("ascii", errors="replace")
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, list):
        return " ".join("" if part is None else str(part) for part in value)
    if value is None:
        return ""
    return value.rstrip("\x00")


def _fraction_decimal(value: Fraction) -> str:
    as_float = float(value)
    return str(int(as_float)) if as_float.is_integer() else str(as_float)


def _package_print(
    tag_name: str,
    raw_value: int | str,
    runtime_context: MakerNoteRuntimeContext,
) -> str | None:
    return render_maker_note_package_runtime_print_value(
        module=OLYMPUS_SOURCE_MODULE,
        table="Main",
        tag_name=tag_name,
        raw_value=raw_value,
        runtime_context=runtime_context,
    )


def _read_s16(data: bytes, offset: int) -> int:
    value = int.from_bytes(data[offset : offset + 2], "little")
    return value - 0x10000 if value & 0x8000 else value
