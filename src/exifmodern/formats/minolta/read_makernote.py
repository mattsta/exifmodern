"""Minolta MakerNote reader slice backed by ExifTool Minolta.pm."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from operator import attrgetter
from pathlib import Path

from exifmodern.formats.jpeg.container import (
    read_exif_app1,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
    tiff_long_tag_value,
)
from exifmodern.formats.tiff.primitives import parse_ifd, parse_tiff_header, read_entry_value
from exifmodern.public_interface.unknown import (
    ProcessBinaryDataKnownSpan,
    ProcessBinaryDataUnknownReadResult,
    ProcessBinaryDataUnknownReadTag,
    ProcessBinaryDataUnknownTablePolicy,
    process_binarydata_unknown_tags_from_payload,
)


@dataclass(frozen=True)
class MinoltaMakerNoteField:
    name: str
    value: str | int | float
    tag_id: int
    family_2_group: str = "Camera"
    source_table: str = "Image::ExifTool::Minolta::CameraSettings"


@dataclass(frozen=True)
class MinoltaMakerNoteReadResult:
    fields: tuple[MinoltaMakerNoteField, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class MinoltaCameraSettingsPayload:
    payload: bytes
    model: str | None
    initial_fields: tuple[MinoltaMakerNoteField, ...]


MINOLTA_SOURCE_TABLE = "Image::ExifTool::Minolta::CameraSettings"
MINOLTA_MAIN_SOURCE_TABLE = "Image::ExifTool::Minolta::Main"
MINOLTA_CAMERA_SETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "minolta.read.camera_settings.main_route",
    "minolta.read.camera_settings.binarydata_policy",
    "public.unknown.binary-block.process-binarydata",
    "public.unknown.binary-block.gettaginfo",
)
MINOLTA_CAMERA_SETTINGS7D_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "minolta.read.camera_settings7d.main_route",
    "minolta.read.camera_settings7d.binarydata_policy",
    "public.unknown.binary-block.process-binarydata",
    "public.unknown.binary-block.gettaginfo",
)
MINOLTA_CAMERA_SETTINGS5D_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "minolta.read.camera_settings5d.main_route",
    "minolta.read.camera_settings5d.binarydata_policy",
    "public.unknown.binary-block.process-binarydata",
    "public.unknown.binary-block.gettaginfo",
)
MINOLTA_CAMERA_SETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "minolta-camerasettings-process-binarydata-unknown"
)
MINOLTA_CAMERA_SETTINGS7D_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "minolta-camerasettings7d-process-binarydata-unknown"
)
MINOLTA_CAMERA_SETTINGS5D_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "minolta-camerasettings5d-process-binarydata-unknown"
)
_shared_evidence_ids = attrgetter("evidence_ids")
type MinoltaFieldRenderer = Callable[[int], str | int | float]
type MinoltaCameraSettingsUnknownReadTag = ProcessBinaryDataUnknownReadTag
type MinoltaCameraSettingsUnknownReadResult = ProcessBinaryDataUnknownReadResult
_MAKER_NOTE_TAG = 0x927C
_CAMERA_SETTINGS_TAG = 0x0003
_CAMERA_SETTINGS_7D_TAG = 0x0004
_CAMERA_SETTINGS_5D_A100_TAG = 0x0114
_CAMERA_SETTINGS_FIELD_SIZE = 4
_CAMERA_SETTINGS_INT16_FIELD_SIZE = 2
_MINOLTA_CAMERA_SETTINGS_NON_7HI_KNOWN_SPANS = (
    ProcessBinaryDataKnownSpan(start_index=1, entry_count=14),
    ProcessBinaryDataKnownSpan(start_index=16, entry_count=8),
    ProcessBinaryDataKnownSpan(start_index=26, entry_count=25),
    ProcessBinaryDataKnownSpan(start_index=63, entry_count=1),
)
_MINOLTA_CAMERA_SETTINGS_7HI_KNOWN_SPANS = (
    ProcessBinaryDataKnownSpan(start_index=1, entry_count=14),
    ProcessBinaryDataKnownSpan(start_index=16, entry_count=8),
    ProcessBinaryDataKnownSpan(start_index=26, entry_count=27),
    ProcessBinaryDataKnownSpan(start_index=63, entry_count=1),
)
_MINOLTA_CAMERA_SETTINGS7D_KNOWN_SPANS = tuple(
    ProcessBinaryDataKnownSpan(start_index=index, entry_count=1)
    for index in (
        0x00,
        0x02,
        0x03,
        0x04,
        0x0E,
        0x10,
        0x15,
        0x16,
        0x1C,
        0x1E,
        0x25,
        0x26,
        0x27,
        0x28,
        0x2D,
        0x3F,
        0x40,
        0x46,
        0x47,
        0x48,
        0x4A,
        0x5E,
        0x60,
        0x62,
        0x71,
        0x75,
    )
)
_MINOLTA_CAMERA_SETTINGS5D_KNOWN_SPANS = tuple(
    ProcessBinaryDataKnownSpan(start_index=index, entry_count=1)
    for index in (
        0x0A,
        0x0C,
        0x0D,
        0x0E,
        0x1F,
        0x20,
        0x25,
        0x26,
        0x2F,
        0x30,
        0x31,
        0x32,
        0x35,
        0x36,
        0x37,
        0x49,
        0x4A,
        0x50,
        0x53,
        0x54,
        0x65,
        0x6E,
        0x71,
        0xAE,
        0xB0,
        0xBD,
    )
)

_EXPOSURE_MODE = {
    0: "Program",
    1: "Aperture Priority",
    2: "Shutter Priority",
    3: "Manual",
}
_FLASH_MODE = {
    0: "Fill flash",
    1: "Red-eye reduction",
    2: "Rear flash sync",
    3: "Wireless",
    4: "Off?",
}
_WHITE_BALANCE = {
    0: "Auto",
    1: "Daylight",
    2: "Cloudy",
    3: "Tungsten",
    5: "Custom",
}
_IMAGE_SIZE = {
    0: "Full",
    1: "1600x1200",
    2: "1280x960",
    3: "640x480",
    6: "2080x1560",
    7: "2560x1920",
    8: "3264x2176",
}
_QUALITY = {
    0: "Raw",
    1: "Super Fine",
    2: "Fine",
    3: "Standard",
    4: "Economy",
    5: "Extra Fine",
}
_DRIVE_MODE = {
    0: "Single",
    1: "Continuous",
    2: "Self-timer",
    4: "Bracketing",
    5: "Interval",
    6: "UHS continuous",
    7: "HS continuous",
}
_METERING_MODE = {
    0: "Multi-segment",
    1: "Center-weighted average",
    2: "Spot",
}
_OFF_ON = {0: "Off", 1: "On"}
_ON_OFF = {0: "On", 1: "Off"}
_NO_YES = {0: "No", 1: "Yes"}
_BRACKET_STEP = {0: "1/3 EV", 1: "2/3 EV", 2: "1 EV"}
_SHARPNESS = {0: "Hard", 1: "Normal", 2: "Soft"}
_MODEL_ID = {
    0: "DiMAGE 7, X1, X21 or X31",
    1: "DiMAGE 5",
    2: "DiMAGE S304",
    3: "DiMAGE S404",
    4: "DiMAGE 7i",
    5: "DiMAGE 7Hi",
    6: "DiMAGE A1",
    7: "DiMAGE A2 or S414",
}
_INTERVAL_MODE = {0: "Still Image", 1: "Time-lapse Movie"}
_FOLDER_NAME = {0: "Standard Form", 1: "Data Form"}
_COLOR_MODE = {
    0: "Natural color",
    1: "Black & White",
    2: "Vivid color",
    3: "Solarization",
    4: "Adobe RGB",
}
_WIDE_FOCUS_ZONE = {
    0: "No zone",
    1: "Center zone (horizontal orientation)",
    2: "Center zone (vertical orientation)",
    3: "Left zone",
    4: "Right zone",
}
_FOCUS_MODE = {0: "AF", 1: "MF"}
_FOCUS_AREA = {0: "Wide Focus (normal)", 1: "Spot Focus"}
_DEC_POSITION = {0: "Exposure", 1: "Contrast", 2: "Saturation", 3: "Filter"}


def read_minolta_maker_note_from_jpeg(path: Path) -> MinoltaMakerNoteReadResult:
    payload_result = _camera_settings_payload_from_jpeg(path)
    if isinstance(payload_result, MinoltaMakerNoteReadResult):
        return payload_result
    fields = list(payload_result.initial_fields)
    fields.extend(_camera_settings_fields(payload_result.payload))
    return MinoltaMakerNoteReadResult(
        tuple(fields),
        (
            "Minolta MakerNote bridge ready: Minolta.pm Main tag 0x0003 routed "
            "big-endian CameraSettings BinaryData fields.",
        ),
    )


def collect_minolta_camera_settings_process_binary_unknown_read_tags(
    path: Path,
) -> MinoltaCameraSettingsUnknownReadResult:
    payload_result = _camera_settings_payload_from_jpeg(path)
    if isinstance(payload_result, MinoltaMakerNoteReadResult):
        return ProcessBinaryDataUnknownReadResult(
            (),
            tuple(
                diagnostic.replace(
                    "Minolta MakerNote blocked",
                    "Minolta CameraSettings ProcessBinaryData unknown discovery blocked",
                )
                for diagnostic in payload_result.diagnostics
            ),
            MINOLTA_CAMERA_SETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    result = process_binarydata_unknown_tags_from_payload(
        payload_result.payload,
        _minolta_camera_settings_unknown_policy(payload_result.model),
    )
    return ProcessBinaryDataUnknownReadResult(
        result.tags,
        tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                "Minolta CameraSettings ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        _shared_evidence_ids(result),
    )


def collect_minolta_camera_settings7d_process_binary_unknown_read_tags(
    path: Path,
) -> MinoltaCameraSettingsUnknownReadResult:
    return _collect_minolta_int16_process_binary_unknown_read_tags(
        path,
        _CAMERA_SETTINGS_7D_TAG,
        ProcessBinaryDataUnknownTablePolicy(
            "Minolta_CameraSettings7D",
            0,
            _CAMERA_SETTINGS_INT16_FIELD_SIZE,
            _MINOLTA_CAMERA_SETTINGS7D_KNOWN_SPANS,
            MINOLTA_CAMERA_SETTINGS7D_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        ),
        "Minolta CameraSettings7D",
    )


def collect_minolta_camera_settings5d_process_binary_unknown_read_tags(
    path: Path,
) -> MinoltaCameraSettingsUnknownReadResult:
    payload_result = _minolta_main_payload_from_jpeg(
        path,
        _CAMERA_SETTINGS_5D_A100_TAG,
        "MinoltaCameraSettings5D tag 0x0114",
    )
    if isinstance(payload_result, MinoltaMakerNoteReadResult):
        return ProcessBinaryDataUnknownReadResult(
            (),
            tuple(
                diagnostic.replace(
                    "Minolta MakerNote blocked",
                    "Minolta CameraSettings5D ProcessBinaryData unknown discovery blocked",
                )
                for diagnostic in payload_result.diagnostics
            ),
            MINOLTA_CAMERA_SETTINGS5D_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    if payload_result.model is None or not _model_selects_5d_camera_settings(payload_result.model):
        return ProcessBinaryDataUnknownReadResult(
            (),
            (
                "Minolta CameraSettings5D ProcessBinaryData unknown discovery blocked: "
                "ExifTool condition requires Model DYNAX 5D, MAXXUM 5D, or ALPHA SWEET.",
            ),
            MINOLTA_CAMERA_SETTINGS5D_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    result = process_binarydata_unknown_tags_from_payload(
        payload_result.payload,
        ProcessBinaryDataUnknownTablePolicy(
            "Minolta_CameraSettings5D",
            0,
            _CAMERA_SETTINGS_INT16_FIELD_SIZE,
            _MINOLTA_CAMERA_SETTINGS5D_KNOWN_SPANS,
            MINOLTA_CAMERA_SETTINGS5D_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        ),
    )
    return ProcessBinaryDataUnknownReadResult(
        result.tags,
        tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                "Minolta CameraSettings5D ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        _shared_evidence_ids(result),
    )


def _collect_minolta_int16_process_binary_unknown_read_tags(
    path: Path,
    tag_id: int,
    policy: ProcessBinaryDataUnknownTablePolicy,
    diagnostic_prefix: str,
) -> MinoltaCameraSettingsUnknownReadResult:
    payload_result = _minolta_main_payload_from_jpeg(
        path,
        tag_id,
        f"{diagnostic_prefix} tag 0x{tag_id:04x}",
    )
    if isinstance(payload_result, MinoltaMakerNoteReadResult):
        return ProcessBinaryDataUnknownReadResult(
            (),
            tuple(
                diagnostic.replace(
                    "Minolta MakerNote blocked",
                    f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked",
                )
                for diagnostic in payload_result.diagnostics
            ),
            _shared_evidence_ids(policy),
        )
    result = process_binarydata_unknown_tags_from_payload(payload_result.payload, policy)
    return ProcessBinaryDataUnknownReadResult(
        result.tags,
        tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        _shared_evidence_ids(result),
    )


def _camera_settings_payload_from_jpeg(
    path: Path,
) -> MinoltaCameraSettingsPayload | MinoltaMakerNoteReadResult:
    return _minolta_main_payload_from_jpeg(
        path,
        _CAMERA_SETTINGS_TAG,
        "MinoltaCameraSettings tag 0x0003",
        reject_x31=True,
    )


def _minolta_main_payload_from_jpeg(
    path: Path,
    binary_data_tag_id: int,
    label: str,
    reject_x31: bool = False,
) -> MinoltaCameraSettingsPayload | MinoltaMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    model = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x0110, header.endian)
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return MinoltaMakerNoteReadResult(
            (), ("Minolta MakerNote blocked: missing ExifIFD pointer.",)
        )
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    entry = next(
        (candidate for candidate in exif_ifd.entries if candidate.tag_id == _MAKER_NOTE_TAG),
        None,
    )
    if entry is None:
        return MinoltaMakerNoteReadResult((), ("Minolta MakerNote blocked: missing tag 0x927c.",))
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, entry, header.endian)
    if raw_location is None:
        return MinoltaMakerNoteReadResult(
            (), ("Minolta MakerNote blocked: raw value is truncated.",)
        )
    maker_offset, raw = raw_location
    if make is None or "MINOLTA" not in make.upper():
        return MinoltaMakerNoteReadResult(
            (), ("Minolta MakerNote blocked: IFD0 Make did not select Minolta.",)
        )
    try:
        maker_ifd = parse_ifd(exif.tiff_data, maker_offset, header.endian)
    except ValueError as exc:
        return MinoltaMakerNoteReadResult((), (f"Minolta MakerNote blocked: {exc}",))

    fields: list[MinoltaMakerNoteField] = []
    version_entry = next(
        (candidate for candidate in maker_ifd.entries if candidate.tag_id == 0),
        None,
    )
    if version_entry is not None:
        version_value = read_entry_value(exif.tiff_data, version_entry, header.endian)
        if isinstance(version_value, bytes):
            fields.append(
                MinoltaMakerNoteField(
                    "MakerNoteVersion",
                    version_value.decode("ascii", errors="replace"),
                    0,
                    source_table=MINOLTA_MAIN_SOURCE_TABLE,
                )
            )

    if reject_x31 and model == "DiMAGE X31":
        return MinoltaMakerNoteReadResult(
            tuple(fields),
            ("Minolta MakerNote blocked: DiMAGE X31 uses a different CameraSettings route.",),
        )

    settings_entry = next(
        (candidate for candidate in maker_ifd.entries if candidate.tag_id == binary_data_tag_id),
        None,
    )
    if settings_entry is None:
        return MinoltaMakerNoteReadResult(
            tuple(fields),
            (f"Minolta MakerNote blocked: missing {label}.",),
        )

    settings_start = settings_entry.value_offset
    settings_end = settings_start + settings_entry.count
    if settings_start < maker_offset or settings_end > maker_offset + len(raw):
        return MinoltaMakerNoteReadResult(
            tuple(fields),
            ("Minolta MakerNote blocked: CameraSettings payload is out of bounds.",),
        )
    return MinoltaCameraSettingsPayload(
        payload=exif.tiff_data[settings_start:settings_end],
        model=model,
        initial_fields=tuple(fields),
    )


def _model_selects_5d_camera_settings(model: str) -> bool:
    return model.startswith(("DYNAX 5D", "MAXXUM 5D", "ALPHA SWEET"))


def _minolta_camera_settings_unknown_policy(
    model: str | None,
) -> ProcessBinaryDataUnknownTablePolicy:
    return ProcessBinaryDataUnknownTablePolicy(
        "Minolta_CameraSettings",
        0,
        _CAMERA_SETTINGS_FIELD_SIZE,
        (
            _MINOLTA_CAMERA_SETTINGS_7HI_KNOWN_SPANS
            if model == "DiMAGE 7Hi"
            else _MINOLTA_CAMERA_SETTINGS_NON_7HI_KNOWN_SPANS
        ),
        MINOLTA_CAMERA_SETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def _camera_settings_fields(payload: bytes) -> tuple[MinoltaMakerNoteField, ...]:
    values = tuple(
        int.from_bytes(payload[offset : offset + _CAMERA_SETTINGS_FIELD_SIZE], "big")
        for offset in range(
            0,
            len(payload) - (_CAMERA_SETTINGS_FIELD_SIZE - 1),
            _CAMERA_SETTINGS_FIELD_SIZE,
        )
    )
    field_specs: tuple[tuple[int, str, MinoltaFieldRenderer, str], ...] = (
        (1, "ExposureMode", _lookup(_EXPOSURE_MODE), "Camera"),
        (2, "FlashMode", _lookup(_FLASH_MODE), "Camera"),
        (3, "WhiteBalance", _lookup(_WHITE_BALANCE), "Camera"),
        (4, "MinoltaImageSize", _lookup(_IMAGE_SIZE), "Camera"),
        (5, "MinoltaQuality", _lookup(_QUALITY), "Camera"),
        (6, "DriveMode", _lookup(_DRIVE_MODE), "Camera"),
        (7, "MeteringMode", _lookup(_METERING_MODE), "Camera"),
        (8, "ISO", _iso, "Camera"),
        (9, "ExposureTime", _exposure_time, "Camera"),
        (10, "FNumber", _f_number, "Camera"),
        (11, "MacroMode", _lookup(_OFF_ON), "Camera"),
        (12, "DigitalZoom", _digital_zoom, "Camera"),
        (14, "BracketStep", _lookup(_BRACKET_STEP), "Camera"),
        (16, "IntervalLength", _identity, "Camera"),
        (17, "IntervalNumber", _identity, "Camera"),
        (18, "FocalLength", _focal_length, "Camera"),
        (19, "FocusDistance", _focus_distance, "Camera"),
        (20, "FlashFired", _lookup(_NO_YES), "Camera"),
        (21, "MinoltaDate", _date, "Time"),
        (22, "MinoltaTime", _time, "Time"),
        (23, "MaxAperture", _f_number, "Camera"),
        (26, "FileNumberMemory", _lookup(_ON_OFF), "Camera"),
        (27, "LastFileNumber", _identity, "Camera"),
        (31, "Saturation", _parameter, "Camera"),
        (32, "Contrast", _parameter, "Camera"),
        (33, "Sharpness", _lookup(_SHARPNESS), "Camera"),
        (37, "MinoltaModelID", _lookup(_MODEL_ID), "Camera"),
        (38, "IntervalMode", _lookup(_INTERVAL_MODE), "Camera"),
        (39, "FolderName", _lookup(_FOLDER_NAME), "Camera"),
        (40, "ColorMode", _lookup(_COLOR_MODE), "Camera"),
        (43, "InternalFlash", _lookup(_NO_YES), "Camera"),
        (47, "WideFocusZone", _lookup(_WIDE_FOCUS_ZONE), "Camera"),
        (48, "FocusMode", _lookup(_FOCUS_MODE), "Camera"),
        (49, "FocusArea", _lookup(_FOCUS_AREA), "Camera"),
        (50, "DECPosition", _lookup(_DEC_POSITION), "Camera"),
    )
    fields: list[MinoltaMakerNoteField] = []
    for index, name, renderer, family_2_group in field_specs:
        if index < len(values):
            fields.append(
                MinoltaMakerNoteField(
                    name,
                    renderer(values[index]),
                    index,
                    family_2_group=family_2_group,
                )
            )
    return tuple(fields)


def _lookup(table: dict[int, str]) -> MinoltaFieldRenderer:
    def render(value: int) -> str | int | float:
        return table.get(value, f"Unknown ({value})")

    return render


def _identity(value: int) -> str | int | float:
    return value


def _iso(value: int) -> str | int | float:
    return int((2 ** ((value - 48) / 8) * 100) + 0.5)


def _exposure_time(value: int) -> str | int | float:
    seconds = 2 ** ((48 - value) / 8)
    if seconds < 1:
        denominator = round(1 / seconds)
        return f"1/{denominator}"
    return round(seconds, 3)


def _f_number(value: int) -> str | int | float:
    return f"{2 ** ((value - 8) / 16):.1f}"


def _digital_zoom(value: int) -> str | int | float:
    return {0: "Off", 1: "Electronic magnification", 2: "2x"}.get(value, f"Unknown ({value})")


def _focal_length(value: int) -> str | int | float:
    return f"{value / 256:.1f} mm"


def _focus_distance(value: int) -> str | int | float:
    return "inf" if value == 0 else f"{value / 1000:g} m"


def _date(value: int) -> str | int | float:
    return f"{value >> 16:04d}:{(value & 0xFF00) >> 8:02d}:{value & 0xFF:02d}"


def _time(value: int) -> str | int | float:
    return f"{value >> 16:02d}:{(value & 0xFF00) >> 8:02d}:{value & 0xFF:02d}"


def _parameter(value: int) -> str | int | float:
    converted = value - 3
    return "Normal" if converted == 0 else converted
