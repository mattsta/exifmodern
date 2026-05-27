"""JFIF/JFXX APP0 readers."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.app_segments.common import jfif_resolution_unit
from exifmodern.formats.jpeg.container import exiftool_binary_summary, read_jpeg_file
from exifmodern.json_types import JsonObject


def read_jfif_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xE0:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"JFIF\x00") or len(payload) < 14:
            continue
        major = payload[5]
        minor = payload[6]
        return {
            "JFIFVersion": major + minor / 100,
            "ResolutionUnit": jfif_resolution_unit(payload[7]),
            "XResolution": int.from_bytes(payload[8:10], "big"),
            "YResolution": int.from_bytes(payload[10:12], "big"),
        }
    raise ValueError(f"No JPEG JFIF APP0 segment found: {path}")


def read_jfxx_tags(path: Path) -> JsonObject:
    thumbnail = read_jfxx_thumbnail_image(path)
    return {"ThumbnailImage": exiftool_binary_summary(len(thumbnail))}


def read_jfxx_thumbnail_image(path: Path) -> bytes:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xE0:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"JFXX\x00\x10"):
            continue
        return payload[6:]
    raise ValueError(f"No JPEG JFXX APP0 thumbnail segment found: {path}")
