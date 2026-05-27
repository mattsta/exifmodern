"""JPEG APP5 Ricoh RMETA adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.formats.ricoh.reader import RICOH_RMETA_PREFIX, parse_ricoh_rmeta_tags
from exifmodern.json_types import JsonObject


def read_ricoh_rmeta_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xE5:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if payload.startswith(RICOH_RMETA_PREFIX):
            return parse_ricoh_rmeta_tags(payload)
    raise ValueError(f"No Ricoh RMETA APP5 segment found: {path}")
