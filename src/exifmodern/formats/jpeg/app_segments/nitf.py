"""JPEG APP6 NITF adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.formats.nitf.reader import NITF_APP6_PREFIX, parse_nitf_app6_tags
from exifmodern.json_types import JsonObject


def read_nitf_app6_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xE6:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if payload.startswith(NITF_APP6_PREFIX):
            return parse_nitf_app6_tags(payload)
    raise ValueError(f"No NITF APP6 segment found: {path}")
