"""JPEG Vivo trailer adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_data
from exifmodern.formats.vivo.reader import parse_vivo_trailer_tags
from exifmodern.json_types import JsonObject


def read_vivo_tags(path: Path) -> JsonObject:
    return parse_vivo_trailer_tags(read_jpeg_data(path))
