"""JPEG APP6 EPPIM adapter for PrintIM metadata."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.formats.printim.reader import EPPIM_APP6_PREFIX, parse_eppim_printim_tags
from exifmodern.json_types import JsonObject


def read_eppim_printim_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    eppim_segment_seen = False
    for segment in jpeg_file.segments:
        if segment.marker != 0xE6:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(EPPIM_APP6_PREFIX):
            continue
        eppim_segment_seen = True
        return parse_eppim_printim_tags(payload)
    if eppim_segment_seen:
        raise ValueError(f"No readable JPEG EPPIM APP6 segment found: {path}")
    raise ValueError(f"No JPEG EPPIM APP6 segment found: {path}")
