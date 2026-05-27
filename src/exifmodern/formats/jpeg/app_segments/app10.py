"""APP10 Unicode comment reader."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.json_types import JsonObject


def read_app10_comment_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xEA:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"UNICODE\x00"):
            continue
        return {"Comment": parse_app10_unicode_comment(payload)}
    raise ValueError(f"No JPEG APP10 Unicode comment segment found: {path}")


def parse_app10_unicode_comment(payload: bytes) -> str:
    return payload[8:].decode("utf-16-be", errors="replace")
