"""JPEG APP3 Kodak Meta adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.formats.kodak.reader import KODAK_META_PREFIX, parse_kodak_meta_tags
from exifmodern.json_types import JsonObject


def read_kodak_meta_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xE3:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if payload.startswith(KODAK_META_PREFIX):
            return parse_kodak_meta_tags(payload)
    raise ValueError(f"No Kodak APP3 Meta segment found: {path}")
