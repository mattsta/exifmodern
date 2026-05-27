"""JPEG FotoStation trailer adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.fotostation.reader import parse_fotostation_tags
from exifmodern.formats.jpeg.container import read_jpeg_data
from exifmodern.json_types import JsonObject


def read_fotostation_tags(path: Path) -> JsonObject:
    tags = parse_fotostation_tags(read_jpeg_data(path))
    if not tags:
        raise ValueError(f"No JPEG FotoStation trailer found: {path}")
    return tags
