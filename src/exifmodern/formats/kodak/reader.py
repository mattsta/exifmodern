"""Kodak APP3 MetaIFD reader."""

from __future__ import annotations

from exifmodern.formats.tiff.primitives import (
    TiffValue,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)
from exifmodern.json_types import JsonObject, JsonValue

KODAK_META_PREFIX = b"Meta\x00\x00"

KODAK_META_TAGS = {
    0xC350: "FilmProductCode",
    0xC351: "ImageSourceEK",
    0xC352: "CaptureConditionsPAR",
    0xC353: "CameraOwner",
    0xC354: "SerialNumber",
    0xC359: "FrameNumber",
    0xC35A: "FilmCategory",
    0xC35B: "FilmGencode",
    0xC35C: "ModelAndVersion",
    0xC35D: "FilmSize",
    0xC35E: "SBA_RGBShifts",
    0xC35F: "SBAInputImageColorspace",
    0xC360: "SBAInputImageBitDepth",
    0xC361: "SBAExposureRecord",
    0xC362: "UserAdjSBA_RGBShifts",
    0xC363: "ImageRotationStatus",
    0xC364: "RollGuidElements",
    0xC365: "MetadataNumber",
}

KODAK_META_BINARY_TAGS = {
    "SBAExposureRecord",
    "UserAdjSBA_RGBShifts",
}

KODAK_META_SPACE_JOINED_TAGS = {
    "SBA_RGBShifts",
    "SBAInputImageBitDepth",
}


def parse_kodak_meta_tags(payload: bytes) -> JsonObject:
    if not payload.startswith(KODAK_META_PREFIX):
        raise ValueError("Invalid Kodak APP3 Meta segment")
    tiff_data = payload[len(KODAK_META_PREFIX) :]
    header = parse_tiff_header(tiff_data)
    ifd = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    tags: JsonObject = {}
    for entry in ifd.entries:
        tag_name = KODAK_META_TAGS.get(entry.tag_id)
        if tag_name is None:
            continue
        raw_value = read_entry_value(tiff_data, entry, header.endian)
        tags[tag_name] = kodak_meta_value(tag_name, raw_value)
    return tags


def kodak_meta_value(tag_name: str, value: TiffValue) -> JsonValue:
    if tag_name in {"CameraOwner", "SerialNumber"} and isinstance(value, bytes):
        return kodak_text_value(value)
    if tag_name in KODAK_META_BINARY_TAGS:
        return binary_summary(binary_source(value))
    if tag_name in KODAK_META_SPACE_JOINED_TAGS:
        return space_joined_value(value)
    if (
        tag_name in {"FilmProductCode", "FilmGencode"}
        and isinstance(value, str)
        and value.isdecimal()
    ):
        return int(value)
    if tag_name == "RollGuidElements" and isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    if tag_name == "MetadataNumber" and isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    if isinstance(value, (str, int)) or value is None:
        return value
    raise ValueError(f"Unhandled Kodak MetaIFD value for {tag_name}: {value!r}")


def kodak_text_value(value: bytes) -> str | int:
    text = value.rstrip(b"\x00").decode("utf-8", errors="replace")
    return int(text) if text.isdecimal() else text


def binary_source(value: TiffValue) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, list):
        return space_joined_value(value).encode("utf-8")
    if isinstance(value, (str, int)):
        return str(value).encode("utf-8")
    if value is None:
        return b""
    raise ValueError(f"Unhandled Kodak MetaIFD binary value: {value!r}")


def binary_summary(value: bytes) -> str:
    return f"(Binary data {len(value)} bytes, use -b option to extract)"


def space_joined_value(value: TiffValue) -> str:
    if isinstance(value, list) and all(isinstance(item, int) for item in value):
        return " ".join(str(item) for item in value)
    if isinstance(value, int):
        return str(value)
    raise ValueError(f"Unhandled Kodak MetaIFD list value: {value!r}")
