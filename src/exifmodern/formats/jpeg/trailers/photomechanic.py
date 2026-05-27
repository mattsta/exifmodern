"""JPEG PhotoMechanic trailer adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_data
from exifmodern.formats.photomechanic.reader import (
    parse_photo_mechanic_trailer_tags,
    photo_mechanic_trailer_payload,
)
from exifmodern.json_types import JsonObject


def read_photo_mechanic_tags(path: Path) -> JsonObject:
    payload = photo_mechanic_trailer_payload(read_jpeg_data(path))
    if payload is None:
        raise ValueError(f"No JPEG PhotoMechanic trailer found: {path}")
    return parse_photo_mechanic_trailer_tags(payload)
