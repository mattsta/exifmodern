"""Canon JPEG MakerNote readiness diagnostics and source-backed field decoding."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.maker_notes import render_maker_note_package_print_value
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_LONG,
    TIFF_TYPE_SHORT,
    TIFF_TYPE_UNDEFINED,
    TYPE_SIZES,
    Endian,
    IfdEntry,
    parse_ifd,
)

type CanonMakerNoteValue = str | int | float

CANON_MAKER_NOTE_SOURCE_ANCHORS = (
    "lib/Image/ExifTool/Exif.pm:2496 tag 0x927c MakerNotes conditional list",
    "lib/Image/ExifTool/MakerNotes.pm:61-68 MakerNoteCanon Make route",
    "lib/Image/ExifTool/MakerNotes.pm:1694-1724 ProcessCanon delegates to ProcessExif",
    "lib/Image/ExifTool/Canon.pm:1221-1855 Canon Main table",
)


@dataclass(frozen=True)
class CanonMainTagDefinition:
    tag_id: int
    name: str
    subdirectory_table: str | None = None


@dataclass(frozen=True)
class CanonMakerNoteEntryReadiness:
    tag_id: int
    name: str
    field_type: int
    count: int
    subdirectory_table: str | None


@dataclass(frozen=True)
class CanonMakerNoteReadinessReport:
    ready: bool
    entry_count: int
    entries: tuple[CanonMakerNoteEntryReadiness, ...]
    diagnostics: tuple[str, ...]
    source_anchors: tuple[str, ...]


@dataclass(frozen=True)
class CanonMakerNoteField:
    name: str
    value: CanonMakerNoteValue
    tag_id: int
    table_name: str
    source: str
    family_2_group: str


@dataclass(frozen=True)
class CanonMakerNoteDecodeResult:
    fields: tuple[CanonMakerNoteField, ...]
    diagnostics: tuple[str, ...]
    source_anchors: tuple[str, ...]


CANON_MAIN_TAGS = {
    0x0001: CanonMainTagDefinition(
        0x0001,
        "CanonCameraSettings",
        "Image::ExifTool::Canon::CameraSettings",
    ),
    0x0002: CanonMainTagDefinition(
        0x0002,
        "CanonFocalLength",
        "Image::ExifTool::Canon::FocalLength",
    ),
    0x0003: CanonMainTagDefinition(0x0003, "CanonFlashInfo"),
    0x0004: CanonMainTagDefinition(0x0004, "CanonShotInfo", "Image::ExifTool::Canon::ShotInfo"),
    0x0005: CanonMainTagDefinition(0x0005, "CanonPanorama", "Image::ExifTool::Canon::Panorama"),
    0x0006: CanonMainTagDefinition(0x0006, "CanonImageType"),
    0x0007: CanonMainTagDefinition(0x0007, "CanonFirmwareVersion"),
    0x0008: CanonMainTagDefinition(0x0008, "FileNumber"),
    0x0009: CanonMainTagDefinition(0x0009, "OwnerName"),
    0x000A: CanonMainTagDefinition(0x000A, "UnknownD30", "Image::ExifTool::Canon::UnknownD30"),
    0x000C: CanonMainTagDefinition(0x000C, "SerialNumber"),
    0x000D: CanonMainTagDefinition(0x000D, "CanonCameraInfo", "model-specific CanonCameraInfo"),
    0x000F: CanonMainTagDefinition(0x000F, "CustomFunctions", "Image::ExifTool::CanonCustom"),
    0x0093: CanonMainTagDefinition(0x0093, "CanonFileInfo", "Image::ExifTool::Canon::FileInfo"),
    0x0094: CanonMainTagDefinition(0x0094, "AFPointsInFocus1D"),
    0x0095: CanonMainTagDefinition(0x0095, "LensModel"),
    0x0096: CanonMainTagDefinition(0x0096, "InternalSerialNumber"),
    0x0097: CanonMainTagDefinition(0x0097, "DustRemovalData"),
}

CANON_MAIN_TABLE = "Image::ExifTool::Canon::Main"
CANON_CAMERA_SETTINGS_TABLE = "Image::ExifTool::Canon::CameraSettings"
CANON_FOCAL_LENGTH_TABLE = "Image::ExifTool::Canon::FocalLength"
CANON_SHOT_INFO_TABLE = "Image::ExifTool::Canon::ShotInfo"
CANON_FILE_INFO_TABLE = "Image::ExifTool::Canon::FileInfo"

CANON_MAIN_SCALAR_TAGS = {
    0x0006: "CanonImageType",
    0x0007: "CanonFirmwareVersion",
    0x0008: "FileNumber",
    0x0009: "OwnerName",
    0x000C: "SerialNumber",
    0x0010: "CanonModelID",
    0x0013: "ThumbnailImageValidArea",
    0x0015: "SerialNumberFormat",
    0x001A: "SuperMacro",
    0x001C: "DateStampMode",
    0x001E: "FirmwareRevision",
    0x0083: "OriginalDecisionDataOffset",
    0x0095: "LensModel",
    0x0096: "InternalSerialNumber",
}
CANON_MAIN_IMAGE_TAGS = {"CanonImageType", "FileNumber"}

OPTICAL_ZOOM_CODE_NA = 8

CAMERA_SETTINGS_FIELD_NAMES = {
    1: "MacroMode",
    4: "CanonFlashMode",
    23: "MaxFocalLength",
    24: "MinFocalLength",
    25: "FocalUnits",
}
FOCAL_LENGTH_FIELD_NAMES = {
    0: "FocalType",
    1: "FocalLength",
}
SHOT_INFO_FIELD_NAMES = {
    1: "AutoISO",
    2: "BaseISO",
    3: "MeasuredEV",
    8: "SlowShutter",
    9: "SequenceNumber",
    10: "OpticalZoomCode",
    12: "CameraTemperature",
}
FILE_INFO_FIELD_NAMES = {
    3: "BracketMode",
    4: "BracketValue",
    5: "BracketShotNumber",
    7: "RawJpgSize",
    8: "LongExposureNoiseReduction2",
    9: "WBBracketMode",
    12: "WBBracketValueAB",
    13: "WBBracketValueGM",
    19: "LiveViewShooting",
    20: "FocusDistanceUpper",
    21: "FocusDistanceLower",
}


def inspect_canon_maker_note_readiness(
    raw_maker_note: bytes,
    byte_order: Endian,
) -> CanonMakerNoteReadinessReport:
    try:
        maker_ifd = parse_ifd(raw_maker_note, 0, byte_order)
    except ValueError as exc:
        return CanonMakerNoteReadinessReport(
            ready=False,
            entry_count=0,
            entries=(),
            diagnostics=(f"Canon MakerNote bridge blocked: {exc}",),
            source_anchors=CANON_MAKER_NOTE_SOURCE_ANCHORS,
        )

    entries = tuple(canon_entry_readiness(entry) for entry in maker_ifd.entries)
    diagnostics = ["Canon MakerNote bridge ready: tag 0x927c routed to Canon.pm Main IFD."]
    diagnostics.extend(unsupported_table_diagnostics(entries))
    return CanonMakerNoteReadinessReport(
        ready=True,
        entry_count=len(entries),
        entries=entries,
        diagnostics=tuple(diagnostics),
        source_anchors=CANON_MAKER_NOTE_SOURCE_ANCHORS,
    )


def canon_entry_readiness(entry: IfdEntry) -> CanonMakerNoteEntryReadiness:
    definition = CANON_MAIN_TAGS.get(entry.tag_id)
    if definition is None:
        return CanonMakerNoteEntryReadiness(
            tag_id=entry.tag_id,
            name=f"Canon_0x{entry.tag_id:04x}",
            field_type=entry.field_type,
            count=entry.count,
            subdirectory_table=None,
        )
    return CanonMakerNoteEntryReadiness(
        tag_id=entry.tag_id,
        name=definition.name,
        field_type=entry.field_type,
        count=entry.count,
        subdirectory_table=definition.subdirectory_table,
    )


def unsupported_table_diagnostics(
    entries: tuple[CanonMakerNoteEntryReadiness, ...],
) -> tuple[str, ...]:
    diagnostics: list[str] = []
    seen_tables: set[str] = set()
    for entry in entries:
        if entry.subdirectory_table is None or entry.subdirectory_table in seen_tables:
            continue
        seen_tables.add(entry.subdirectory_table)
        diagnostics.append(
            f"Canon MakerNote table {entry.subdirectory_table} from tag "
            f"0x{entry.tag_id:04x} ({entry.name}) is present but not decoded by "
            "the current Canon JPEG MakerNote adapter."
        )
    return tuple(diagnostics)


def decode_canon_maker_note(
    raw_maker_note: bytes,
    byte_order: Endian,
    maker_note_tiff_offset: int = 0,
) -> CanonMakerNoteDecodeResult:
    try:
        maker_ifd = parse_ifd(raw_maker_note, 0, byte_order)
    except ValueError as exc:
        return CanonMakerNoteDecodeResult(
            fields=(),
            diagnostics=(f"Canon MakerNote decode blocked: {exc}",),
            source_anchors=CANON_MAKER_NOTE_SOURCE_ANCHORS,
        )

    fields: list[CanonMakerNoteField] = []
    diagnostics: list[str] = [
        "Canon MakerNote bridge ready: tag 0x927c routed to Canon.pm Main IFD."
    ]
    seen_unsupported_tables: set[str] = set()

    focal_units = 1
    for entry in maker_ifd.entries:
        definition = CANON_MAIN_TAGS.get(entry.tag_id)
        if entry.tag_id in CANON_MAIN_SCALAR_TAGS:
            field = _decode_main_scalar_field(
                raw_maker_note,
                entry,
                byte_order,
                maker_note_tiff_offset,
            )
            if field is not None:
                fields.append(field)
            continue
        if entry.tag_id == 0x0001:
            camera_fields, focal_units = _decode_camera_settings(
                raw_maker_note,
                entry,
                byte_order,
                maker_note_tiff_offset,
                focal_units,
            )
            fields.extend(camera_fields)
            continue
        if entry.tag_id == 0x0002:
            fields.extend(
                _decode_focal_length(
                    raw_maker_note,
                    entry,
                    byte_order,
                    maker_note_tiff_offset,
                    focal_units,
                )
            )
            continue
        if entry.tag_id == 0x0004:
            fields.extend(
                _decode_shot_info(raw_maker_note, entry, byte_order, maker_note_tiff_offset)
            )
            continue
        if entry.tag_id == 0x0093:
            file_info_fields = _decode_file_info(
                raw_maker_note,
                entry,
                byte_order,
                maker_note_tiff_offset,
            )
            if file_info_fields:
                fields.extend(file_info_fields)
                continue
        if definition is None or definition.subdirectory_table is None:
            continue
        if definition.subdirectory_table in seen_unsupported_tables:
            continue
        seen_unsupported_tables.add(definition.subdirectory_table)
        diagnostics.append(
            f"Canon MakerNote unsupported table {definition.subdirectory_table} from tag "
            f"0x{entry.tag_id:04x} ({definition.name}) remains diagnostic-only."
        )

    return CanonMakerNoteDecodeResult(
        fields=tuple(fields),
        diagnostics=tuple(diagnostics),
        source_anchors=CANON_MAKER_NOTE_SOURCE_ANCHORS,
    )


def _decode_main_scalar_field(
    raw_maker_note: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_note_tiff_offset: int,
) -> CanonMakerNoteField | None:
    name = CANON_MAIN_SCALAR_TAGS[entry.tag_id]
    value = _read_scalar_value(raw_maker_note, entry, byte_order, maker_note_tiff_offset)
    if value is None:
        return None
    if name == "FileNumber" and isinstance(value, int):
        value = _canon_file_number(value)
    elif name == "SerialNumber" and isinstance(value, int):
        value = f"{value:010d}"
    elif name == "InternalSerialNumber" and isinstance(value, str):
        value = value.rstrip("\xff")
    return CanonMakerNoteField(
        name=name,
        value=value,
        tag_id=entry.tag_id,
        table_name=CANON_MAIN_TABLE,
        source="canon-main-scalar",
        family_2_group="Image" if name in CANON_MAIN_IMAGE_TAGS else "Camera",
    )


def _decode_camera_settings(
    raw_maker_note: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_note_tiff_offset: int,
    fallback_focal_units: int,
) -> tuple[tuple[CanonMakerNoteField, ...], int]:
    values = _entry_int16_values(
        raw_maker_note,
        entry,
        byte_order,
        maker_note_tiff_offset,
        signed=True,
    )
    fields: list[CanonMakerNoteField] = []
    focal_units = fallback_focal_units
    for index, name in CAMERA_SETTINGS_FIELD_NAMES.items():
        value = _binary_data_value(values, index)
        if value is None:
            continue
        emitted: CanonMakerNoteValue
        if name == "MacroMode" or name == "CanonFlashMode":
            package_value = _package_print(CANON_CAMERA_SETTINGS_TABLE, name, value, index)
            emitted = package_value if package_value is not None else value
        elif name in {"MaxFocalLength", "MinFocalLength"}:
            units = focal_units or 1
            emitted = f"{_format_decimal(value / units)} mm"
        elif name == "FocalUnits":
            focal_units = value
            emitted = f"{value}/mm"
        else:
            emitted = value
        fields.append(
            CanonMakerNoteField(
                name=name,
                value=emitted,
                tag_id=index,
                table_name=CANON_CAMERA_SETTINGS_TABLE,
                source="canon-camera-settings-int16s",
                family_2_group="Camera",
            )
        )
    return tuple(fields), focal_units


def _decode_focal_length(
    raw_maker_note: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_note_tiff_offset: int,
    focal_units: int,
) -> tuple[CanonMakerNoteField, ...]:
    values = _entry_int16_values(
        raw_maker_note,
        entry,
        byte_order,
        maker_note_tiff_offset,
        signed=False,
    )
    fields: list[CanonMakerNoteField] = []
    for index, name in FOCAL_LENGTH_FIELD_NAMES.items():
        value = _binary_data_value(values, index)
        if value is None or value == 0:
            continue
        emitted: CanonMakerNoteValue
        if name == "FocalType":
            package_value = _package_print(CANON_FOCAL_LENGTH_TABLE, name, value, index)
            emitted = package_value if package_value is not None else value
        elif name == "FocalLength":
            units = focal_units or 1
            emitted = f"{_format_decimal(value / units)} mm"
        else:
            emitted = value
        fields.append(
            CanonMakerNoteField(
                name=name,
                value=emitted,
                tag_id=index,
                table_name=CANON_FOCAL_LENGTH_TABLE,
                source="canon-focal-length-int16u",
                family_2_group="Image",
            )
        )
    return tuple(fields)


def _decode_shot_info(
    raw_maker_note: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_note_tiff_offset: int,
) -> tuple[CanonMakerNoteField, ...]:
    values = _entry_int16_values(
        raw_maker_note,
        entry,
        byte_order,
        maker_note_tiff_offset,
        signed=True,
    )
    fields: list[CanonMakerNoteField] = []
    for index, name in SHOT_INFO_FIELD_NAMES.items():
        value = _binary_data_value(values, index)
        if value is None:
            continue
        emitted: CanonMakerNoteValue
        family_2_group = "Image"
        if name == "AutoISO":
            emitted = round(2 ** (value / 32) * 100)
        elif name == "BaseISO":
            if value == 0:
                continue
            emitted = round(2 ** (value / 32) * 100 / 32)
        elif name == "MeasuredEV":
            emitted = round(value / 32 + 5, 2)
        elif name == "SlowShutter":
            package_value = _package_print(CANON_SHOT_INFO_TABLE, name, value, index)
            emitted = package_value if package_value is not None else value
        elif name == "OpticalZoomCode":
            emitted = "n/a" if value == OPTICAL_ZOOM_CODE_NA else value
            family_2_group = "Camera"
        elif name == "CameraTemperature":
            if value == 0:
                continue
            emitted = f"{value - 128} C"
            family_2_group = "Camera"
        else:
            emitted = value
        fields.append(
            CanonMakerNoteField(
                name=name,
                value=emitted,
                tag_id=index,
                table_name=CANON_SHOT_INFO_TABLE,
                source="canon-shot-info-int16s",
                family_2_group=family_2_group,
            )
        )
    return tuple(fields)


def _decode_file_info(
    raw_maker_note: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_note_tiff_offset: int,
) -> tuple[CanonMakerNoteField, ...]:
    values = _entry_int16_values(
        raw_maker_note,
        entry,
        byte_order,
        maker_note_tiff_offset,
        signed=True,
    )
    fields: list[CanonMakerNoteField] = []
    for index, name in FILE_INFO_FIELD_NAMES.items():
        value = _binary_data_value(values, index)
        if value is None:
            continue
        emitted: CanonMakerNoteValue
        if name == "BracketMode":
            package_value = _package_print(CANON_FILE_INFO_TABLE, name, value, index)
            emitted = package_value if package_value is not None else value
        elif name == "RawJpgSize" or name == "LongExposureNoiseReduction2":
            if value < 0:
                continue
            package_value = _package_print(CANON_FILE_INFO_TABLE, name, value, index)
            emitted = package_value if package_value is not None else value
        elif name == "WBBracketMode" or name == "LiveViewShooting":
            package_value = _package_print(CANON_FILE_INFO_TABLE, name, value, index)
            emitted = package_value if package_value is not None else value
        elif name in {"FocusDistanceUpper", "FocusDistanceLower"}:
            emitted = "inf" if value / 100 > 655.345 else f"{_format_decimal(value / 100)} m"
        else:
            emitted = value
        fields.append(
            CanonMakerNoteField(
                name=name,
                value=emitted,
                tag_id=index,
                table_name=CANON_FILE_INFO_TABLE,
                source="canon-file-info-int16s",
                family_2_group="Image",
            )
        )
    return tuple(fields)


def _read_scalar_value(
    raw_maker_note: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_note_tiff_offset: int,
) -> CanonMakerNoteValue | None:
    if entry.field_type == TIFF_TYPE_ASCII:
        raw = _entry_raw_value(raw_maker_note, entry, byte_order, maker_note_tiff_offset)
        if raw is None:
            return None
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    if entry.field_type in {TIFF_TYPE_SHORT, TIFF_TYPE_LONG}:
        value = _read_numeric_entry_value(
            raw_maker_note,
            entry,
            byte_order,
            maker_note_tiff_offset,
        )
        if isinstance(value, int):
            return value
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
    return None


def _package_print(table_name: str, tag_name: str, raw_value: int | str, tag_id: int) -> str | None:
    return render_maker_note_package_print_value(
        module="Image::ExifTool::Canon",
        table=table_name.removeprefix("Image::ExifTool::Canon::"),
        tag_name=tag_name,
        raw_value=raw_value,
        tag_id=tag_id,
    )


def _entry_int16_values(
    raw_maker_note: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_note_tiff_offset: int,
    *,
    signed: bool,
) -> tuple[int, ...]:
    if entry.field_type not in {TIFF_TYPE_SHORT, TIFF_TYPE_UNDEFINED}:
        return ()
    raw = _entry_raw_value(raw_maker_note, entry, byte_order, maker_note_tiff_offset)
    if raw is None:
        return ()
    return tuple(
        int.from_bytes(raw[offset : offset + 2], byte_order, signed=signed)
        for offset in range(0, len(raw) - 1, 2)
    )


def _entry_raw_value(
    raw_maker_note: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_note_tiff_offset: int,
) -> bytes | None:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        return None
    byte_count = field_size * entry.count
    if byte_count <= 4:
        return entry.value_offset.to_bytes(4, byte_order)[:byte_count]
    value_start = entry.value_offset - maker_note_tiff_offset
    value_end = value_start + byte_count
    if value_start < 0 or value_end > len(raw_maker_note):
        return None
    return raw_maker_note[value_start:value_end]


def _read_numeric_entry_value(
    raw_maker_note: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_note_tiff_offset: int,
) -> int | list[int] | None:
    raw = _entry_raw_value(raw_maker_note, entry, byte_order, maker_note_tiff_offset)
    if raw is None:
        return None
    if entry.field_type == TIFF_TYPE_SHORT:
        values = [
            int.from_bytes(raw[index * 2 : index * 2 + 2], byte_order)
            for index in range(entry.count)
        ]
    elif entry.field_type == TIFF_TYPE_LONG:
        values = [
            int.from_bytes(raw[index * 4 : index * 4 + 4], byte_order)
            for index in range(entry.count)
        ]
    else:
        return None
    return values[0] if entry.count == 1 else values


def _binary_data_value(
    values: tuple[int, ...],
    index: int,
) -> int | None:
    offset = index
    if offset < 0 or offset >= len(values):
        return None
    return values[offset]


def _canon_file_number(value: int) -> str:
    text = str(value)
    if len(text) <= 4:
        return text
    return f"{text[:-4]}-{text[-4:]}"


def _format_decimal(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"
