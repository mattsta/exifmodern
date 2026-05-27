"""Canon CIFF metadata reader."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from exifmodern.formats.jpeg.container import exiftool_binary_summary
from exifmodern.json_types import JsonObject, JsonValue
from exifmodern.services.binary import ByteOrder, ieee754_float32

CIFF_SIGNATURE = b"HEAPJPGM"
CIFF_DIRECTORY_POINTER_SIZE = 4

CIFF_SIMPLE_TAGS = {
    0x0001: "FreeBytes",
    0x0805: "CanonFileDescription",
    0x080B: "CanonFirmwareVersion",
    0x080D: "ROMOperationMode",
    0x0810: "OwnerName",
    0x0815: "CanonImageType",
    0x0816: "OriginalFileName",
    0x0817: "ThumbnailFileName",
    0x100A: "TargetImageType",
    0x1010: "ShutterReleaseMethod",
    0x1011: "ShutterReleaseTiming",
    0x101C: "BaseISO",
    0x1804: "RecordID",
    0x1807: "TargetDistanceSetting",
    0x1814: "MeasuredEV",
    0x1817: "FileNumber",
}

CIFF_BINARY_TABLE_TAGS = {
    0x080A,
    0x1029,
    0x1803,
    0x180E,
    0x1810,
    0x1813,
    0x1818,
}

CIFF_INT16_PRINTS = {
    "TargetImageType": {
        0: "Real-world Subject",
        1: "Written Document",
    },
    "ShutterReleaseMethod": {
        0: "Single Shot",
        2: "Continuous Shooting",
    },
    "ShutterReleaseTiming": {
        0: "Priority on shutter",
        1: "Priority on focus",
    },
}


@dataclass(frozen=True)
class CiffEntry:
    tag: int
    tag_id: int
    tag_type: int
    value_in_directory: bool
    size: int
    value_pointer: int
    entry_offset: int


@dataclass(frozen=True)
class CiffLocatedEntry:
    entry: CiffEntry
    block_start: int


@dataclass(frozen=True)
class CiffContext:
    byte_order: ByteOrder
    data: bytes


def parse_ciff_tags(payload: bytes) -> JsonObject:
    context, block_start, block_size = parse_ciff_header(payload)
    tags: JsonObject = {}
    parse_ciff_directory(context, block_start, block_size, tags)
    return tags


def parse_ciff_header(payload: bytes) -> tuple[CiffContext, int, int]:
    if len(payload) < 14:
        raise ValueError("Truncated Canon CIFF header")
    if payload[:2] == b"II":
        byte_order: ByteOrder = "little"
    elif payload[:2] == b"MM":
        byte_order = "big"
    else:
        raise ValueError("Invalid Canon CIFF byte-order marker")
    header_length = read_u32(payload, 2, byte_order)
    if payload[6:14] != CIFF_SIGNATURE:
        raise ValueError("Invalid Canon CIFF signature")
    if header_length >= len(payload):
        raise ValueError("Invalid Canon CIFF header length")
    return (
        CiffContext(byte_order=byte_order, data=payload),
        header_length,
        len(payload) - header_length,
    )


def parse_ciff_directory(
    context: CiffContext,
    block_start: int,
    block_size: int,
    tags: JsonObject,
) -> None:
    if block_size < CIFF_DIRECTORY_POINTER_SIZE:
        return
    directory_pointer_offset = block_start + block_size - CIFF_DIRECTORY_POINTER_SIZE
    directory_offset = block_start + read_u32(
        context.data, directory_pointer_offset, context.byte_order
    )
    if directory_offset + 2 > len(context.data):
        return
    entry_count = read_u16(context.data, directory_offset, context.byte_order)
    entries_start = directory_offset + 2
    entries_end = entries_start + entry_count * 10
    if entries_end > len(context.data):
        return
    for index in range(entry_count):
        entry = read_ciff_entry(context, entries_start + index * 10)
        parse_ciff_entry(context, block_start, entry, tags)


def find_ciff_entry(
    context: CiffContext,
    block_start: int,
    block_size: int,
    tag_id: int,
) -> CiffLocatedEntry | None:
    if block_size < CIFF_DIRECTORY_POINTER_SIZE:
        return None
    directory_pointer_offset = block_start + block_size - CIFF_DIRECTORY_POINTER_SIZE
    directory_offset = block_start + read_u32(
        context.data, directory_pointer_offset, context.byte_order
    )
    if directory_offset + 2 > len(context.data):
        return None
    entry_count = read_u16(context.data, directory_offset, context.byte_order)
    entries_start = directory_offset + 2
    entries_end = entries_start + entry_count * 10
    if entries_end > len(context.data):
        return None
    for index in range(entry_count):
        entry = read_ciff_entry(context, entries_start + index * 10)
        if entry.tag_id == tag_id:
            return CiffLocatedEntry(entry=entry, block_start=block_start)
        if entry.tag_type in {0x28, 0x30} and not entry.value_in_directory:
            nested = find_ciff_entry(context, block_start + entry.value_pointer, entry.size, tag_id)
            if nested is not None:
                return nested
    return None


def read_ciff_entry(context: CiffContext, offset: int) -> CiffEntry:
    tag = read_u16(context.data, offset, context.byte_order)
    return CiffEntry(
        tag=tag,
        tag_id=tag & 0x3FFF,
        tag_type=(tag >> 8) & 0x38,
        value_in_directory=bool(tag & 0x4000),
        size=read_u32(context.data, offset + 2, context.byte_order),
        value_pointer=read_u32(context.data, offset + 6, context.byte_order),
        entry_offset=offset,
    )


def parse_ciff_entry(
    context: CiffContext,
    block_start: int,
    entry: CiffEntry,
    tags: JsonObject,
) -> None:
    if entry.tag_type in {0x28, 0x30} and not entry.value_in_directory:
        parse_ciff_directory(context, block_start + entry.value_pointer, entry.size, tags)
        return
    raw_value = ciff_entry_bytes(context, block_start, entry)
    if entry.tag_id in CIFF_BINARY_TABLE_TAGS:
        tags.update(ciff_binary_table_tags(context, entry.tag_id, raw_value))
        return
    tag_name = CIFF_SIMPLE_TAGS.get(entry.tag_id)
    if tag_name is None:
        return
    tags[tag_name] = ciff_simple_value(context, tag_name, entry.tag_type, raw_value)


def ciff_entry_bytes(context: CiffContext, block_start: int, entry: CiffEntry) -> bytes:
    if entry.value_in_directory:
        return context.data[entry.entry_offset + 2 : entry.entry_offset + 10]
    value_start = block_start + entry.value_pointer
    value_end = value_start + entry.size
    if value_start < 0 or value_end > len(context.data):
        raise ValueError("Invalid Canon CIFF value offset")
    return context.data[value_start:value_end]


def ciff_simple_value(
    context: CiffContext,
    tag_name: str,
    tag_type: int,
    raw_value: bytes,
) -> JsonValue:
    if tag_name == "FreeBytes":
        return exiftool_binary_summary(len(raw_value))
    if tag_type == 0x08:
        return ciff_string(raw_value)
    if tag_type == 0x10:
        value = read_u16(raw_value, 0, context.byte_order)
        return CIFF_INT16_PRINTS.get(tag_name, {}).get(value, value)
    if tag_type == 0x18:
        value = read_u32(raw_value, 0, context.byte_order)
        if tag_name == "TargetDistanceSetting":
            return f"{integral_float(ciff_float(raw_value, context.byte_order))} mm"
        if tag_name == "MeasuredEV":
            return integral_float(ciff_float(raw_value, context.byte_order) + 5)
        return value
    return exiftool_binary_summary(len(raw_value))


def ciff_binary_table_tags(context: CiffContext, tag_id: int, raw_value: bytes) -> JsonObject:
    if tag_id == 0x080A:
        return ciff_make_model_tags(raw_value)
    if tag_id == 0x1029:
        return ciff_focal_length_tags(context, raw_value)
    if tag_id == 0x1803:
        return ciff_image_format_tags(context, raw_value)
    if tag_id == 0x180E:
        return ciff_timestamp_tags(context, raw_value)
    if tag_id == 0x1810:
        return ciff_image_info_tags(context, raw_value)
    if tag_id == 0x1813:
        return ciff_flash_info_tags(context, raw_value)
    if tag_id == 0x1818:
        return ciff_exposure_info_tags(context, raw_value)
    return {}


def ciff_make_model_tags(raw_value: bytes) -> JsonObject:
    return {
        "Make": ciff_string(raw_value[:6]),
        "Model": ciff_string(raw_value[6:]),
    }


def ciff_focal_length_tags(context: CiffContext, raw_value: bytes) -> JsonObject:
    values = ciff_u16_values(context, raw_value)
    tags: JsonObject = {}
    if len(values) > 0 and values[0] != 0:
        tags["FocalType"] = {1: "Fixed", 2: "Zoom"}.get(values[0], values[0])
    if len(values) > 1 and values[1] != 0:
        tags["FocalLength"] = f"{values[1]} mm"
    if len(values) > 2 and values[2] >= 40:
        tags["FocalPlaneXSize"] = f"{values[2] * 25.4 / 1000:.2f} mm"
    if len(values) > 3 and values[3] >= 40:
        tags["FocalPlaneYSize"] = f"{values[3] * 25.4 / 1000:.2f} mm"
    return tags


def ciff_image_format_tags(context: CiffContext, raw_value: bytes) -> JsonObject:
    file_format = read_u32(raw_value, 0, context.byte_order)
    return {
        "FileFormat": {
            0x00010000: "JPEG (lossy)",
            0x00010002: "JPEG (non-quantization)",
            0x00010003: "JPEG (lossy/non-quantization toggled)",
            0x00020001: "CRW",
        }.get(file_format, file_format),
        "TargetCompressionRatio": integral_float(ciff_float(raw_value[4:8], context.byte_order)),
    }


def ciff_timestamp_tags(context: CiffContext, raw_value: bytes) -> JsonObject:
    timestamp = read_u32(raw_value, 0, context.byte_order)
    time_zone_code = read_s32(raw_value, 4, context.byte_order)
    return {
        "DateTimeOriginal": time.strftime("%Y:%m:%d %H:%M:%S", time.gmtime(timestamp)),
        "TimeZoneCode": integral_float(time_zone_code / 3600),
        "TimeZoneInfo": read_u32(raw_value, 8, context.byte_order),
    }


def ciff_image_info_tags(context: CiffContext, raw_value: bytes) -> JsonObject:
    return {
        "ImageWidth": read_u32(raw_value, 0, context.byte_order),
        "ImageHeight": read_u32(raw_value, 4, context.byte_order),
        "PixelAspectRatio": integral_float(ciff_float(raw_value[8:12], context.byte_order)),
        "Rotation": read_s32(raw_value, 12, context.byte_order),
        "ComponentBitDepth": read_u32(raw_value, 16, context.byte_order),
        "ColorBitDepth": read_u32(raw_value, 20, context.byte_order),
        "ColorBW": read_u32(raw_value, 24, context.byte_order),
    }


def ciff_flash_info_tags(context: CiffContext, raw_value: bytes) -> JsonObject:
    return {
        "FlashGuideNumber": integral_float(ciff_float(raw_value[0:4], context.byte_order)),
        "FlashThreshold": integral_float(ciff_float(raw_value[4:8], context.byte_order)),
    }


def ciff_exposure_info_tags(context: CiffContext, raw_value: bytes) -> JsonObject:
    exposure_compensation = ciff_float(raw_value[0:4], context.byte_order)
    shutter_raw = ciff_float(raw_value[4:8], context.byte_order)
    aperture_raw = ciff_float(raw_value[8:12], context.byte_order)
    return {
        "ExposureCompensation": integral_float(exposure_compensation),
        "ShutterSpeedValue": ciff_exposure_time(shutter_raw),
        "ApertureValue": round_half_up(math.pow(2, aperture_raw / 2), 1),
    }


def ciff_exposure_time(value: float) -> str | int | float:
    seconds = 1 / math.pow(2, value) if abs(value) < 100 else 0
    if seconds > 0 and seconds < 1:
        return f"1/{round(1 / seconds)}"
    if abs(seconds - round(seconds)) < 1e-9:
        return round(seconds)
    return round_half_up(seconds, 2)


def ciff_u16_values(context: CiffContext, raw_value: bytes) -> list[int]:
    return [
        read_u16(raw_value, offset, context.byte_order)
        for offset in range(0, len(raw_value) - 1, 2)
    ]


def ciff_float(raw_value: bytes, byte_order: ByteOrder) -> float:
    if len(raw_value) < 4:
        raise ValueError("Truncated Canon CIFF float")
    return ieee754_float32(raw_value[:4], byte_order)


def ciff_string(raw_value: bytes) -> str:
    return raw_value.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def integral_float(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def round_half_up(value: float, digits: int) -> float:
    scale = 10**digits
    return float(math.floor(value * scale + 0.5) / scale)


def read_u16(data: bytes, offset: int, byte_order: ByteOrder) -> int:
    if offset + 2 > len(data):
        raise ValueError(f"Truncated Canon CIFF 16-bit value at offset {offset}")
    return int.from_bytes(data[offset : offset + 2], byte_order)


def read_u32(data: bytes, offset: int, byte_order: ByteOrder) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"Truncated Canon CIFF 32-bit value at offset {offset}")
    return int.from_bytes(data[offset : offset + 4], byte_order)


def read_s32(data: bytes, offset: int, byte_order: ByteOrder) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"Truncated Canon CIFF signed 32-bit value at offset {offset}")
    return int.from_bytes(data[offset : offset + 4], byte_order, signed=True)
