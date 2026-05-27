"""JPEG MIE trailer adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_data
from exifmodern.formats.mie.reader import parse_mie_trailer_tags
from exifmodern.json_types import JsonObject


def read_mie_main_tags(path: Path) -> JsonObject:
    tags = parse_mie_trailer_tags(read_jpeg_data(path))
    trailer_signature = tags.get("TrailerSignature")
    if isinstance(trailer_signature, str):
        return {"TrailerSignature": trailer_signature}
    return {}


def read_mie_doc_tags(path: Path) -> JsonObject:
    tags = parse_mie_trailer_tags(read_jpeg_data(path))
    copyright_value = tags.get("Copyright")
    if isinstance(copyright_value, str):
        return {"Copyright": copyright_value}
    return {}
