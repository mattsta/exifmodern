"""APP12 PictureInfo reader."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.json_types import JsonObject

type PictureInfoRawName = str
type PictureInfoTagName = str

PICTURE_INFO_TAG_NAMES: dict[PictureInfoRawName, PictureInfoTagName] = {
    "TimeDate": "DateTimeOriginal",
    "Shutter": "ExposureTime",
    "shtr": "ExposureTime",
    "ExpBias": "ExposureCompensation",
    "Type": "CameraType",
    "Serial#": "SerialNumber",
    "Q": "TagQ",
    "R": "TagR",
    "B": "TagB",
    "s0": "S0",
}


def read_picture_info_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xEC:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if b"[picture info]" not in payload.lower() and b"Type=" not in payload:
            continue
        return parse_picture_info_payload(payload)
    raise ValueError(f"No JPEG PictureInfo APP12 segment found: {path}")


def parse_picture_info_payload(payload: bytes) -> JsonObject:
    values: JsonObject = {}
    text = payload.decode("latin-1", errors="replace")
    for line in text.splitlines():
        token = line.strip().strip("\x00")
        if not token or token.startswith("[") or "=" not in token:
            continue
        raw_name, raw_value = token.split("=", 1)
        name = picture_info_tag_name(raw_name)
        values[name] = picture_info_value(raw_name, raw_value.strip())
    return values


def picture_info_tag_name(raw_name: str) -> str:
    return PICTURE_INFO_TAG_NAMES.get(raw_name, raw_name[:1].upper() + raw_name[1:])


def picture_info_value(raw_name: str, raw_value: str) -> str | int | float:
    if raw_name == "TimeDate":
        return picture_info_datetime(raw_value)
    if raw_name in {"Shutter", "shtr"}:
        return picture_info_exposure_time(raw_value)
    if raw_name == "FNumber":
        return round(
            float(raw_value.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ")), 1
        )
    if raw_name in {"Flash", "Macro"}:
        return picture_info_on_off(raw_value)
    if raw_name == "ImageSize":
        return raw_value.replace("-", "x")
    if raw_name == "ExpBias":
        return picture_info_exposure_compensation(raw_value)
    if raw_name in {"Serial#", "Type", "Version", "ID", "s0", "T0"}:
        return raw_value
    return picture_info_scalar(raw_value)


def picture_info_datetime(raw_value: str) -> str:
    if not raw_value.isdecimal():
        return raw_value
    value = datetime.fromtimestamp(int(raw_value), UTC)
    return value.strftime("%Y:%m:%d %H:%M:%S")


def picture_info_exposure_time(raw_value: str) -> str:
    microseconds = int(raw_value)
    denominator = round(1_000_000 / microseconds)
    return f"1/{denominator}"


def picture_info_on_off(raw_value: str) -> str | int:
    if not raw_value.isdecimal():
        return raw_value
    value = int(raw_value)
    if value == 0:
        return "Off"
    if value == 1:
        return "On"
    return value


def picture_info_exposure_compensation(raw_value: str) -> str:
    if raw_value.startswith(("+", "-")):
        return raw_value
    return f"+{raw_value}"


def picture_info_scalar(raw_value: str) -> str | int | float:
    if raw_value.isdecimal():
        return int(raw_value)
    if picture_info_is_decimal(raw_value):
        return float(raw_value)
    return raw_value


def picture_info_is_decimal(raw_value: str) -> bool:
    if raw_value.count(".") != 1:
        return False
    left, right = raw_value.split(".", 1)
    return left.isdecimal() and right.isdecimal()
