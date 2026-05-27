"""JPEG APP0 Canon CIFF adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.canon.ciff import CIFF_SIGNATURE, parse_ciff_tags
from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.json_types import JsonObject


def read_ciff_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xE0:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if len(payload) >= 14 and payload[:2] in {b"II", b"MM"} and payload[6:14] == CIFF_SIGNATURE:
            return parse_ciff_tags(payload)
    raise ValueError(f"No JPEG Canon CIFF APP0 segment found: {path}")
