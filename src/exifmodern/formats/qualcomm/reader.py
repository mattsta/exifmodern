"""Qualcomm APP7 Camera Attributes reader."""

from __future__ import annotations

import re

from exifmodern.formats.jpeg.container import exiftool_binary_summary
from exifmodern.json_types import JsonObject, JsonValue
from exifmodern.services.binary import ieee754_float32, ieee754_float64

QUALCOMM_APP7_NAME = b"Qualcomm Camera Attributes"
QUALCOMM_APP7_PREFIX = bytes((len(QUALCOMM_APP7_NAME),)) + QUALCOMM_APP7_NAME

type QualcommFormatName = str
type QualcommValue = int | float | str

QUALCOMM_FORMATS: tuple[QualcommFormatName, ...] = (
    "int8u",
    "int8s",
    "int16u",
    "int16s",
    "int32u",
    "int32s",
    "float",
    "double",
)
QUALCOMM_KNOWN_TAG_NAMES = {
    "aec_current_sensor_luma": "AECCurrentSensorLuma",
    "af_position": "AFPosition",
    "aec_current_exp_index": "AECCurrentExpIndex",
    "awb_sample_decision": "AWBSampleDecision",
    "asf5_enable": "ASF5Enable",
    "asf5_filter_mode": "ASF5FilterMode",
    "asf5_exposure_index_1": "ASF5ExposureIndex1",
    "asf5_exposure_index_2": "ASF5ExposureIndex2",
    "asf5_max_exposure_index": "ASF5MaxExposureIndex",
}


def parse_qualcomm_app7_tags(payload: bytes) -> JsonObject:
    if not payload.startswith(QUALCOMM_APP7_PREFIX):
        raise ValueError("No Qualcomm APP7 Camera Attributes payload found")
    position = len(QUALCOMM_APP7_PREFIX)
    values: JsonObject = {}
    while position + 3 < len(payload):
        value_length = int.from_bytes(payload[position : position + 2], "little")
        tag_length = payload[position + 2]
        record_header_end = position + 8 + tag_length
        record_end = record_header_end + value_length
        if record_end > len(payload):
            break
        tag_id = payload[position + 3 : position + 3 + tag_length].decode(
            "utf-8",
            errors="replace",
        )
        format_code = payload[position + 3 + tag_length]
        raw_value = payload[record_header_end:record_end]
        tag_name = qualcomm_tag_name(tag_id)
        if tag_name:
            values[tag_name] = qualcomm_value(format_code, raw_value)
        position = record_end
    return values


def qualcomm_tag_name(tag_id: str) -> str:
    known_name = QUALCOMM_KNOWN_TAG_NAMES.get(tag_id)
    if known_name is not None:
        return known_name
    return qualcomm_dynamic_tag_name(tag_id)


def qualcomm_dynamic_tag_name(tag_id: str) -> str:
    parts = [qualcomm_name_part(part) for part in tag_id.split("_") if part]
    return re.sub("[^A-Za-z0-9-]", "", "".join(parts))


def qualcomm_name_part(part: str) -> str:
    if part in {"asf", "awb", "aec", "afr", "af", "la", "tl"}:
        return part.upper()
    if part.startswith("r2"):
        return "R2" + part[2:].capitalize()
    subscript_match = re.fullmatch(r"([A-Za-z0-9]+)\[(\d+)\]", part)
    if subscript_match:
        return f"{subscript_match.group(1).capitalize()}{int(subscript_match.group(2)):02d}"
    return part.capitalize()


def qualcomm_value(format_code: int, raw_value: bytes) -> JsonValue:
    if format_code >= len(QUALCOMM_FORMATS):
        return exiftool_binary_summary(len(raw_value))
    format_name = QUALCOMM_FORMATS[format_code]
    value = qualcomm_numeric_value(format_name, raw_value)
    if value is not None:
        return value
    return exiftool_binary_summary(len(raw_value))


def qualcomm_numeric_value(
    format_name: QualcommFormatName, raw_value: bytes
) -> QualcommValue | None:
    if format_name == "int8u" and len(raw_value) >= 1:
        return raw_value[0]
    if format_name == "int8s" and len(raw_value) >= 1:
        return int.from_bytes(raw_value[:1], "little", signed=True)
    if format_name == "int16u" and len(raw_value) >= 2:
        return int.from_bytes(raw_value[:2], "little")
    if format_name == "int16s" and len(raw_value) >= 2:
        return int.from_bytes(raw_value[:2], "little", signed=True)
    if format_name == "int32u" and len(raw_value) >= 4:
        return int.from_bytes(raw_value[:4], "little")
    if format_name == "int32s" and len(raw_value) >= 4:
        return int.from_bytes(raw_value[:4], "little", signed=True)
    if format_name == "float" and len(raw_value) >= 4:
        return ieee754_float32(raw_value[:4], "little")
    if format_name == "double" and len(raw_value) >= 8:
        return ieee754_float64(raw_value[:8], "little")
    return None
