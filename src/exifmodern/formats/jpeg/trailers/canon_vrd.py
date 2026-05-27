"""JPEG CanonVRD trailer adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.canon_vrd.reader import parse_canon_vrd_tags
from exifmodern.formats.jpeg.container import read_jpeg_data
from exifmodern.json_types import JsonObject


def read_canon_vrd_tags(path: Path) -> JsonObject:
    return parse_canon_vrd_tags(read_jpeg_data(path))
