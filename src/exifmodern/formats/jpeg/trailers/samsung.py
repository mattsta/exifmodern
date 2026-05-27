"""JPEG Samsung SEFT trailer adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_data
from exifmodern.formats.samsung.reader import parse_samsung_seft_trailer_tags
from exifmodern.json_types import JsonObject


def read_samsung_trailer_tags(path: Path) -> JsonObject:
    return parse_samsung_seft_trailer_tags(read_jpeg_data(path))
