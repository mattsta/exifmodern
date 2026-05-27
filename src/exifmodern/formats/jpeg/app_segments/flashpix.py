"""JPEG APP2 FlashPix FPXR adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.flashpix.reader import FPXR_PREFIX, parse_fpxr_tags
from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.json_types import JsonObject


def read_flashpix_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    payloads: list[bytes] = []
    for segment in jpeg_file.segments:
        if segment.marker != 0xE2:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if payload.startswith(FPXR_PREFIX):
            payloads.append(payload)
    if not payloads:
        raise ValueError(f"No JPEG FlashPix FPXR APP2 segment found: {path}")
    return parse_fpxr_tags(payloads)
