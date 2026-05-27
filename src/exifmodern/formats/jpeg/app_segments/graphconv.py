"""GraphicConverter APP15 reader."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.json_types import JsonObject


def read_graphconv_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xEF:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"Q"):
            continue
        return parse_graphconv_payload(payload)
    raise ValueError(f"No JPEG GraphicConverter APP15 segment found: {path}")


def parse_graphconv_payload(payload: bytes) -> JsonObject:
    quality_text = payload[1:].decode("ascii", errors="ignore").strip()
    if not quality_text.isdecimal():
        raise ValueError("Unreadable JPEG GraphicConverter APP15 quality")
    return {"Quality": int(quality_text)}
