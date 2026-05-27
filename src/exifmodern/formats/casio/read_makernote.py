"""Casio MakerNote and QVCI reader slice backed by ExifTool Casio.pm."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Literal

from exifmodern.formats.casio.maker_note import (
    CASIO_TYPE2_HEADER,
    casio_maker_note_ifd_offset,
    casio_maker_note_offset,
)
from exifmodern.formats.jpeg.container import (
    read_exif_app1,
    read_jpeg_segment_probes,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
)
from exifmodern.formats.tiff.primitives import (
    Endian,
    Ifd,
    IfdEntry,
    TiffValue,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)
from exifmodern.media_source import FileMediaSource
from exifmodern.public_interface.unknown import (
    ProcessBinaryDataKnownSpan,
    ProcessBinaryDataUnknownReadResult,
    ProcessBinaryDataUnknownReadTag,
    ProcessBinaryDataUnknownTablePolicy,
    UnknownReadBlocker,
    process_binarydata_unknown_tags_from_payload,
    process_binarydata_unknown_tags_from_payload_with_known_spans,
)

type CasioReadFamily = Literal["type1", "type2"]


@dataclass(frozen=True)
class CasioMakerNoteField:
    name: str
    value: str | int | float
    tag_id: int
    family_2_group: str = "Camera"


@dataclass(frozen=True)
class CasioMakerNoteReadResult:
    fields: tuple[CasioMakerNoteField, ...]
    diagnostics: tuple[str, ...]
    source_table: str


CASIO_TYPE1_SOURCE_TABLE = "Image::ExifTool::Casio::Main"
CASIO_TYPE2_SOURCE_TABLE = "Image::ExifTool::Casio::Type2"
CASIO_QVCI_SOURCE_TABLE = "Image::ExifTool::Casio::QVCI"
CASIO_QVCI_PREFIX = b"QVCI\x00"
CASIO_QVCI_PROCESS_BINARYDATA_UNKNOWN_SOURCE = "casio-qvci-process-binarydata-unknown"
CASIO_FACEINFO1_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "casio-faceinfo1-process-binarydata-stateful-unknown"
)
CASIO_FACEINFO2_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "casio-faceinfo2-process-binarydata-stateful-unknown"
)
CASIO_AVI_PROCESS_BINARYDATA_TERMINAL_SOURCE = "casio-avi-process-binarydata-string-to-end-terminal"
CASIO_QVCI_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "casio.read.qvci_jpeg_route",
    "casio.read.qvci_binarydata_policy",
    "casio.read.qvci_unknown_scan",
    "casio.read.qvci_unknown_prefix",
)
CASIO_FACEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "casio.read.faceinfo_route",
    "casio.read.faceinfo_binarydata_policy",
    "casio.read.faceinfo_unknown_scan",
)
CASIO_AVI_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "casio.read.avi_binarydata_policy",
    "casio.read.avi_unknown_scan",
    "casio.read.avi_uncounted_string",
    "casio.read.avi_next_index_suppression",
)
CASIO_AVI_PROCESS_BINARYDATA_TERMINAL_DIAGNOSTIC = (
    "Casio AVI ProcessBinaryData unknown discovery blocked: Casio::AVI tag 0 Software "
    "uses uncounted Format string, which consumes the remaining table bytes and "
    "suppresses all later Unknown=2 scalar fanout via ProcessBinaryData nextIndex."
)
CASIO_TABLE_LOCAL_BLOCKERS = (
    UnknownReadBlocker(
        code="casio_avi_string_to_end_blocked",
        message=CASIO_AVI_PROCESS_BINARYDATA_TERMINAL_DIAGNOSTIC,
        evidence_ids=CASIO_AVI_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    ),
)
type CasioQvciUnknownReadTag = ProcessBinaryDataUnknownReadTag
type CasioQvciUnknownReadResult = ProcessBinaryDataUnknownReadResult
type CasioFaceInfoUnknownReadTag = ProcessBinaryDataUnknownReadTag
type CasioFaceInfoUnknownReadResult = ProcessBinaryDataUnknownReadResult
type CasioAviUnknownReadResult = ProcessBinaryDataUnknownReadResult
_CASIO_QVCI_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Casio_QVCI",
    first_entry=0,
    increment=1,
    known_spans=(
        ProcessBinaryDataKnownSpan(start_index=0x2C, entry_count=1),
        ProcessBinaryDataKnownSpan(start_index=0x37, entry_count=1),
        ProcessBinaryDataKnownSpan(start_index=0x4D, entry_count=20),
        ProcessBinaryDataKnownSpan(start_index=0x62, entry_count=7),
        ProcessBinaryDataKnownSpan(start_index=0x72, entry_count=9),
        ProcessBinaryDataKnownSpan(start_index=0x7C, entry_count=9),
    ),
    evidence_ids=CASIO_QVCI_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_CASIO_FACEINFO1_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Casio_FaceInfo1",
    first_entry=0,
    increment=1,
    known_spans=(),
    evidence_ids=CASIO_FACEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_CASIO_FACEINFO2_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Casio_FaceInfo2",
    first_entry=0,
    increment=1,
    known_spans=(),
    evidence_ids=CASIO_FACEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_CASIO_FACEINFO_TAG = 0x2089

_TYPE1_TAG_NAMES = {
    0x0001: "RecordingMode",
    0x0002: "Quality",
    0x0003: "FocusMode",
    0x0004: "FlashMode",
    0x0005: "FlashIntensity",
    0x0006: "ObjectDistance",
    0x0007: "WhiteBalance",
    0x000A: "DigitalZoom",
    0x000B: "Sharpness",
    0x000C: "Contrast",
    0x000D: "Saturation",
    0x0014: "ISO",
}
_TYPE2_TAG_NAMES = {
    0x0002: "PreviewImageSize",
    0x0003: "PreviewImageLength",
    0x0004: "PreviewImageStart",
    0x2001: "FirmwareDate",
    0x2011: "WhiteBalanceBias",
    0x2012: "WhiteBalance",
    0x2021: "AFPointPosition",
    0x2022: "ObjectDistance",
    0x2034: "FlashDistance",
    0x3000: "RecordMode",
    0x3001: "ReleaseMode",
    0x3002: "Quality",
    0x3003: "FocusMode",
    0x3006: "HometownCity",
    0x3007: "BestShotMode",
    0x3011: "Sharpness",
    0x3012: "Contrast",
    0x3013: "Saturation",
    0x3014: "ISO",
    0x3015: "ColorMode",
    0x3016: "Enhancement",
    0x3017: "ColorFilter",
    0x301B: "ArtMode",
}

_TYPE1_PRINTS = {
    "RecordingMode": {1: "Single Shutter", 2: "Panorama", 3: "Night Scene"},
    "Quality": {1: "Economy", 2: "Normal", 3: "Fine"},
    "FocusMode": {2: "Macro", 3: "Auto", 4: "Manual", 5: "Infinity", 7: "Spot AF"},
    "FlashMode": {1: "Auto", 2: "On", 3: "Off", 4: "Red-eye Reduction"},
    "FlashIntensity": {11: "Weak", 13: "Normal", 15: "Strong"},
    "WhiteBalance": {1: "Auto", 2: "Tungsten", 3: "Daylight", 4: "Fluorescent"},
    "DigitalZoom": {0x10000: "Off", 0x10001: "2x"},
    "Sharpness": {0: "Normal", 1: "Soft", 2: "Hard"},
    "Contrast": {0: "Normal", 1: "Low", 2: "High"},
    "Saturation": {0: "Normal", 1: "Low", 2: "High"},
}
_TYPE2_PRINTS = {
    "WhiteBalance": {
        0: "Manual",
        1: "Daylight",
        2: "Cloudy",
        3: "Shade",
        6: "Fluorescent",
        10: "Tungsten",
        12: "Flash",
    },
    "RecordMode": {2: "Program AE", 3: "Shutter Priority", 4: "Aperture Priority"},
    "ReleaseMode": {1: "Normal", 3: "AE Bracketing"},
    "Quality": {1: "Economy", 2: "Normal", 3: "Fine"},
    "FocusMode": {0: "Manual", 1: "Focus Lock", 2: "Macro", 3: "Single-Area Auto Focus"},
    "BestShotMode": {0: "Off"},
    "ColorMode": {0: "Off", 2: "Black & White", 3: "Sepia"},
    "Enhancement": {0: "Off", 1: "Scenery", 3: "Green", 5: "Underwater"},
    "ColorFilter": {0: "Off", 1: "Blue", 3: "Green", 4: "Yellow"},
    "ArtMode": {0: "Normal", 8: "Silent Movie", 39: "HDR"},
}


def read_casio_maker_note_from_jpeg(path: Path) -> CasioMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    if make is None or not make.upper().startswith("CASIO"):
        return CasioMakerNoteReadResult(
            (),
            ("Casio MakerNote blocked: IFD0 Make did not select Casio.",),
            CASIO_TYPE1_SOURCE_TABLE,
        )
    try:
        maker_note_offset = casio_maker_note_offset(exif.tiff_data)
    except ValueError as exc:
        return CasioMakerNoteReadResult(
            (), (f"Casio MakerNote blocked: {exc}",), CASIO_TYPE1_SOURCE_TABLE
        )

    family: CasioReadFamily = (
        "type2" if exif.tiff_data[maker_note_offset:].startswith(CASIO_TYPE2_HEADER) else "type1"
    )
    try:
        ifd_offset = casio_maker_note_ifd_offset(exif.tiff_data, maker_note_offset, family)
        maker_ifd = parse_ifd(exif.tiff_data, ifd_offset, header.endian)
    except ValueError as exc:
        return CasioMakerNoteReadResult(
            (), (f"Casio MakerNote blocked: {exc}",), CASIO_TYPE1_SOURCE_TABLE
        )

    fields = tuple(
        _type2_field(exif.tiff_data, entry, header.endian)
        if family == "type2"
        else _type1_field(exif.tiff_data, entry, header.endian)
        for entry in maker_ifd.entries
        if entry.tag_id in (_TYPE2_TAG_NAMES if family == "type2" else _TYPE1_TAG_NAMES)
    )
    table_name = CASIO_TYPE2_SOURCE_TABLE if family == "type2" else CASIO_TYPE1_SOURCE_TABLE
    return CasioMakerNoteReadResult(
        fields,
        (
            f"Casio MakerNote bridge ready: MakerNotes.pm Casio route decoded {table_name}.",
            "Casio MakerNote blocked: binary preview payloads and PrintIM subdirectories remain "
            "behind source-backed nested adapters.",
        ),
        table_name,
    )


def read_casio_qvci_from_jpeg(path: Path) -> CasioMakerNoteReadResult:
    source = FileMediaSource(path)
    try:
        probes = read_jpeg_segment_probes(path, prefix_length=len(CASIO_QVCI_PREFIX))
    except ValueError:
        return CasioMakerNoteReadResult((), (), CASIO_QVCI_SOURCE_TABLE)
    for segment in probes:
        if segment.marker != 0xE1 or not segment.payload_prefix.startswith(CASIO_QVCI_PREFIX):
            continue
        payload = source.read_at(segment.payload_offset, segment.payload_length)
        if payload.startswith(CASIO_QVCI_PREFIX):
            return CasioMakerNoteReadResult(
                _qvci_fields(payload),
                (
                    "Casio QVCI bridge ready: JPEG.pm APP1 QVCI route decoded "
                    "Casio.pm QVCI binary-data fields.",
                ),
                CASIO_QVCI_SOURCE_TABLE,
            )
    return CasioMakerNoteReadResult((), (), CASIO_QVCI_SOURCE_TABLE)


def collect_casio_qvci_process_binary_unknown_read_tags(
    path: Path,
) -> CasioQvciUnknownReadResult:
    source = FileMediaSource(path)
    try:
        segments = read_jpeg_segment_probes(path, prefix_length=len(CASIO_QVCI_PREFIX))
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(f"Casio QVCI ProcessBinaryData unknown discovery blocked: {exc}",),
            evidence_ids=CASIO_QVCI_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    tags: list[CasioQvciUnknownReadTag] = []
    diagnostics: list[str] = []
    for segment in segments:
        if segment.marker != 0xE1 or not segment.payload_prefix.startswith(CASIO_QVCI_PREFIX):
            continue
        payload = source.read_at(segment.payload_offset, segment.payload_length)
        if not payload.startswith(CASIO_QVCI_PREFIX):
            continue
        result = process_binarydata_unknown_tags_from_payload(payload, _CASIO_QVCI_UNKNOWN_POLICY)
        tags.extend(result.tags)
        diagnostics.extend(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                "Casio QVCI ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        )
    return ProcessBinaryDataUnknownReadResult(
        tags=tuple(tags),
        diagnostics=tuple(diagnostics),
        evidence_ids=CASIO_QVCI_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def collect_casio_faceinfo_process_binary_unknown_read_tags(
    path: Path,
) -> CasioFaceInfoUnknownReadResult:
    context = _casio_type2_maker_ifd(path)
    if isinstance(context, ProcessBinaryDataUnknownReadResult):
        return context
    data, maker_ifd, endian = context
    entry = next((candidate for candidate in maker_ifd.entries if candidate.tag_id == 0x2089), None)
    if entry is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=CASIO_FACEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    location = tiff_entry_raw_value_location(data, entry, endian)
    if location is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                "Casio FaceInfo ProcessBinaryData unknown discovery blocked: "
                "tag 0x2089 payload is truncated.",
            ),
            evidence_ids=CASIO_FACEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    _payload_offset, payload = location
    if _is_faceinfo1_payload(payload):
        result = process_binarydata_unknown_tags_from_payload_with_known_spans(
            payload,
            _CASIO_FACEINFO1_UNKNOWN_POLICY,
            _casio_faceinfo1_known_spans(payload),
        )
        return _casio_faceinfo_result(result, "Casio FaceInfo1")
    if payload.startswith(b"\x02\x01"):
        result = process_binarydata_unknown_tags_from_payload_with_known_spans(
            payload,
            _CASIO_FACEINFO2_UNKNOWN_POLICY,
            _casio_faceinfo2_known_spans(payload),
        )
        return _casio_faceinfo_result(result, "Casio FaceInfo2")
    return ProcessBinaryDataUnknownReadResult(
        tags=(),
        diagnostics=(
            "Casio FaceInfo ProcessBinaryData unknown discovery blocked: tag 0x2089 "
            "payload did not match FaceInfo1 or FaceInfo2 source Conditions.",
        ),
        evidence_ids=CASIO_FACEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def collect_casio_avi_process_binary_unknown_read_tags_from_payload(
    payload: bytes,
) -> CasioAviUnknownReadResult:
    """Classify Casio::AVI Unknown=2 fanout without guessing byte scalars."""

    diagnostic = CASIO_AVI_PROCESS_BINARYDATA_TERMINAL_DIAGNOSTIC if payload else ""
    return ProcessBinaryDataUnknownReadResult(
        tags=(),
        diagnostics=(diagnostic,) if diagnostic else (),
        evidence_ids=CASIO_AVI_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def _casio_type2_maker_ifd(
    path: Path,
) -> tuple[bytes, Ifd, Endian] | ProcessBinaryDataUnknownReadResult:
    try:
        exif = read_exif_app1(path)
        header = parse_tiff_header(exif.tiff_data)
        ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(f"Casio FaceInfo ProcessBinaryData unknown discovery blocked: {exc}",),
            evidence_ids=CASIO_FACEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    if make is None or not make.upper().startswith("CASIO"):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=CASIO_FACEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    try:
        maker_note_offset = casio_maker_note_offset(exif.tiff_data)
        ifd_offset = casio_maker_note_ifd_offset(exif.tiff_data, maker_note_offset, "type2")
        maker_ifd = parse_ifd(exif.tiff_data, ifd_offset, header.endian)
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(f"Casio FaceInfo ProcessBinaryData unknown discovery blocked: {exc}",),
            evidence_ids=CASIO_FACEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    return exif.tiff_data, maker_ifd, header.endian


def _is_faceinfo1_payload(payload: bytes) -> bool:
    return payload.startswith(b"\x00\x00") or (
        len(payload) >= 5 and payload[1:5] == b"\x02\x80\x01\xe0"
    )


def _casio_faceinfo1_known_spans(payload: bytes) -> tuple[ProcessBinaryDataKnownSpan, ...]:
    faces_detected = payload[0] if payload else 0
    spans = [ProcessBinaryDataKnownSpan(start_index=0x00, entry_count=1)]
    if faces_detected >= 1:
        spans.append(ProcessBinaryDataKnownSpan(start_index=0x01, entry_count=4))
    for face_index, start_index in enumerate(
        (0x0D, 0x7C, 0xEB, 0x15A, 0x1C9, 0x238, 0x2A7, 0x316, 0x385, 0x3F4),
        start=1,
    ):
        if faces_detected >= face_index:
            spans.append(ProcessBinaryDataKnownSpan(start_index=start_index, entry_count=8))
    return tuple(spans)


def _casio_faceinfo2_known_spans(payload: bytes) -> tuple[ProcessBinaryDataKnownSpan, ...]:
    faces_detected = payload[2] if len(payload) > 2 else 0
    spans = [ProcessBinaryDataKnownSpan(start_index=0x02, entry_count=1)]
    if faces_detected >= 1:
        spans.extend(
            (
                ProcessBinaryDataKnownSpan(start_index=0x04, entry_count=4),
                ProcessBinaryDataKnownSpan(start_index=0x08, entry_count=1),
            )
        )
    for face_index, start_index in enumerate(
        (0x18, 0x4C, 0x80, 0xB4, 0xE8, 0x11C, 0x150, 0x184, 0x1B8, 0x1EC),
        start=1,
    ):
        if faces_detected >= face_index:
            spans.append(ProcessBinaryDataKnownSpan(start_index=start_index, entry_count=8))
    return tuple(spans)


def _casio_faceinfo_result(
    result: ProcessBinaryDataUnknownReadResult,
    table_label: str,
) -> ProcessBinaryDataUnknownReadResult:
    return ProcessBinaryDataUnknownReadResult(
        tags=result.tags,
        diagnostics=tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                f"{table_label} ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        evidence_ids=CASIO_FACEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def _type1_field(data: bytes, entry: IfdEntry, endian: Endian) -> CasioMakerNoteField:
    name = _TYPE1_TAG_NAMES[entry.tag_id]
    raw_value = read_entry_value(data, entry, endian)
    if name == "ObjectDistance" and isinstance(raw_value, int):
        rendered: str | int | float = _meters(raw_value)
    elif name in _TYPE1_PRINTS and isinstance(raw_value, int):
        rendered = _TYPE1_PRINTS[name].get(raw_value, str(raw_value))
    else:
        rendered = _scalar_text(raw_value)
    return CasioMakerNoteField(name, rendered, entry.tag_id)


def _type2_field(data: bytes, entry: IfdEntry, endian: Endian) -> CasioMakerNoteField:
    name = _TYPE2_TAG_NAMES[entry.tag_id]
    raw_value = read_entry_value(data, entry, endian)
    values = _int_list(raw_value)
    if name == "PreviewImageSize" and values is not None:
        rendered: str | int | float = f"{values[0]}x{values[1]}" if len(values) >= 2 else ""
    elif name == "FirmwareDate" and isinstance(raw_value, bytes | str):
        rendered = _firmware_date(raw_value)
    elif name == "WhiteBalanceBias" and values is not None:
        rendered = " ".join(str(value) for value in values)
    elif name == "AFPointPosition" and values is not None:
        rendered = _af_point_position(values)
    elif name == "ObjectDistance" and isinstance(raw_value, int):
        rendered = "inf" if raw_value >= 0x20000000 else _meters(raw_value)
    elif name == "PreviewImageStart" and isinstance(raw_value, int):
        # MakerNotes.pm routes Type2 with Start => valuePtr + 6 and FixBase for offset tags.
        rendered = raw_value + 12
    elif name == "HometownCity" and isinstance(raw_value, str):
        rendered = raw_value.rstrip("\x00")
    elif name in {"Sharpness", "Contrast", "Saturation"}:
        rendered = _signed_int16_from_undefined(raw_value)
    elif name in _TYPE2_PRINTS and isinstance(raw_value, int):
        rendered = _TYPE2_PRINTS[name].get(raw_value, f"Unknown ({raw_value})")
    else:
        rendered = _scalar_text(raw_value)
    return CasioMakerNoteField(name, rendered, entry.tag_id, _type2_group(name))


def _qvci_fields(payload: bytes) -> tuple[CasioMakerNoteField, ...]:
    fields: list[CasioMakerNoteField] = []
    if len(payload) > 0x2C:
        fields.append(
            CasioMakerNoteField(
                "CasioQuality",
                {1: "Economy", 2: "Normal", 3: "Fine", 4: "Super Fine"}.get(
                    payload[0x2C], payload[0x2C]
                ),
                0x2C,
            )
        )
    fields.extend(
        (
            CasioMakerNoteField("DateTimeOriginal", _qvci_date(payload), 0x4D, "Time"),
            CasioMakerNoteField("ModelType", _qvci_string(payload, 0x62, 7), 0x62),
            CasioMakerNoteField("ManufactureIndex", _qvci_string(payload, 0x72, 9), 0x72),
            CasioMakerNoteField("ManufactureCode", _qvci_string(payload, 0x7C, 9), 0x7C),
        )
    )
    return tuple(field for field in fields if field.value != "")


def _firmware_date(raw: bytes | str) -> str:
    if isinstance(raw, str):
        raw = raw.encode("latin-1", errors="replace")
    if len(raw) >= 14 and raw[4:6] == b"\0\0" and raw[10:12] == b"\0\0":
        year = int(raw[0:2].decode("ascii", errors="ignore") or "0")
        century = 2000 if year < 70 else 1900
        return (
            f"{century + year:04d}:{raw[2:4].decode('ascii', errors='replace')}:"
            f"{raw[6:8].decode('ascii', errors='replace')} "
            f"{raw[8:10].decode('ascii', errors='replace')}:"
            f"{raw[12:14].decode('ascii', errors='replace')}"
        )
    text = raw.replace(b"\0", b".").rstrip(b".").decode("latin-1", errors="replace")
    return f"Unknown ({text})"


def _qvci_date(payload: bytes) -> str:
    text = _qvci_string(payload, 0x4D, 20).replace(".", ":")
    parts = text.split(":")
    if len(parts) >= 6:
        return f"{parts[0]}:{parts[1]}:{parts[2]} {parts[3]}:{parts[4]}:{parts[5]}"
    return text


def _qvci_string(payload: bytes, offset: int, count: int) -> str:
    if offset + count > len(payload):
        return ""
    return payload[offset : offset + count].rstrip(b"\0").decode("ascii", errors="replace")


def _af_point_position(values: list[int]) -> str:
    if len(values) < 4 or values[0] == 65535 or values[1] == 0 or values[3] == 0:
        return "n/a"
    x_position = _two_sig_digits(Fraction(values[0], values[1]))
    y_position = _two_sig_digits(Fraction(values[2], values[3]))
    return f"{x_position} {y_position}"


def _two_sig_digits(value: Fraction) -> str:
    return f"{float(value):.2g}"


def _meters(raw_value: int) -> str:
    meters = Fraction(raw_value, 1000)
    if meters.denominator == 1:
        return f"{meters.numerator} m"
    return f"{float(meters):g} m"


def _signed_int16_from_undefined(raw_value: TiffValue) -> str | int | float:
    if isinstance(raw_value, bytes) and len(raw_value) >= 2:
        return int.from_bytes(raw_value[:2], "big", signed=True)
    return _scalar_text(raw_value)


def _scalar_text(raw_value: TiffValue) -> str | int | float:
    if isinstance(raw_value, int | str):
        return raw_value
    if isinstance(raw_value, Fraction):
        return float(raw_value)
    if isinstance(raw_value, bytes):
        return raw_value.rstrip(b"\0").decode("latin-1", errors="replace")
    values = _int_list(raw_value)
    if values is not None:
        return " ".join(str(value) for value in values)
    return ""


def _int_list(raw_value: TiffValue) -> list[int] | None:
    if not isinstance(raw_value, list):
        return None
    values: list[int] = []
    for value in raw_value:
        if not isinstance(value, int):
            return None
        values.append(value)
    return values


def _type2_group(name: str) -> str:
    if name in {"PreviewImageSize", "PreviewImageLength", "PreviewImageStart"}:
        return "Image"
    return "Camera"
