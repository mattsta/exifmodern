"""JPEG APP11 JUMBF adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.formats.jumbf.reader import (
    APP11_JUMBF_PREFIX,
    parse_jumbf_json_tags,
    parse_jumbf_tags,
)
from exifmodern.json_types import JsonObject


def read_jumbf_tags(path: Path) -> JsonObject:
    return parse_jumbf_tags(read_jumbf_app11_payload(path))


def read_jumbf_json_tags(path: Path) -> JsonObject:
    return parse_jumbf_json_tags(read_jumbf_app11_payload(path))


def read_jumbf_app11_payload(path: Path) -> bytes:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xEB:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if payload.startswith(APP11_JUMBF_PREFIX):
            return payload
    raise ValueError(f"No JPEG JUMBF APP11 segment found: {path}")
