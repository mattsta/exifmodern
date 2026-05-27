"""JPEG-HDR APP11 and HDR gain APP10 readers.

This module owns the APP11 HDR payload grammar so the generic JPEG container
reader does not become the home for every vendor/application extension.
"""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import exiftool_binary_summary, read_jpeg_file
from exifmodern.json_types import JsonObject


def read_jpeg_hdr_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xEB:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"HDR_RI "):
            continue
        return parse_jpeg_hdr_payload(payload)
    raise ValueError(f"No JPEG-HDR APP11 segment found: {path}")


def read_jpeg_hdr_gain_info_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xEA:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if payload.startswith(b"AROT\x00\x00"):
            return parse_jpeg_hdr_gain_info_payload(payload)
    raise ValueError(f"No JPEG HDRGainInfo APP10 segment found: {path}")


def parse_jpeg_hdr_gain_info_payload(payload: bytes) -> JsonObject:
    # Semantic source: jpeg.hdr-gain-info.binary-table.
    if len(payload) < 10:
        raise ValueError("Truncated JPEG HDRGainInfo APP10 segment")
    curve_size = int.from_bytes(payload[6:10], "big")
    curve_byte_count = min(max(curve_size, 0) * 4, max(len(payload) - 10, 0))
    return {
        "HDRGainCurveSize": curve_size,
        "HDRGainCurve": exiftool_binary_summary(curve_byte_count),
    }


def parse_jpeg_hdr_payload(payload: bytes) -> JsonObject:
    separator = payload.find(b"~\x00")
    if separator < 0:
        raise ValueError("Unrecognized JPEG-HDR APP11 segment")
    metadata = payload[7:separator].decode("ascii", errors="replace")
    values = jpeg_hdr_metadata_values(metadata)
    ratio_image_size = len(payload[separator + 2 :])
    values["RatioImage"] = exiftool_binary_summary(ratio_image_size)
    return values


def jpeg_hdr_metadata_values(metadata: str) -> JsonObject:
    tag_names = {
        "ver": "JPEG-HDRVersion",
        "ln0": "Ln0",
        "ln1": "Ln1",
        "s2n": "S2n",
        "alp": "Alpha",
        "bet": "Beta",
        "cor": "CorrectionMethod",
    }
    values: JsonObject = {}
    for token in metadata.replace(",", " ").split():
        if "=" not in token:
            continue
        key, raw_value = token.split("=", 1)
        name = tag_names.get(key)
        if name is None:
            continue
        values[name] = jpeg_hdr_number(raw_value)
    return values


def jpeg_hdr_number(value: str) -> int | float:
    number = float(value)
    if number.is_integer() and "e" not in value.lower() and "." not in value:
        return int(number)
    return number
