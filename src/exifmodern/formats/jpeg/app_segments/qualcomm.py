"""JPEG APP7 Qualcomm Camera Attributes adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.formats.qualcomm.reader import (
    QUALCOMM_APP7_PREFIX,
    parse_qualcomm_app7_tags,
)
from exifmodern.json_types import JsonObject


def read_qualcomm_app7_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xE7:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if payload.startswith(QUALCOMM_APP7_PREFIX):
            return parse_qualcomm_app7_tags(payload)
    raise ValueError(f"No Qualcomm APP7 Camera Attributes segment found: {path}")
