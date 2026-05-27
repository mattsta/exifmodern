"""FLIR exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.tiff import make_tiff_header
from exifmodern.exiftool_compat.types import (
    ExifToolHashReference,
    ExifToolScalar,
    ExifToolValue,
    hash_reference_value,
    int_value,
    scalar_hash_field,
    scalar_value,
    string_value,
)


def get_image_type(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 3:
        return None
    exiftool_context = hash_reference_value(values[0], "FLIR GetImageType ExifTool context")
    payload = string_value(scalar_value(values[1], "FLIR GetImageType image data"))
    tag = string_value(scalar_value(values[2], "FLIR GetImageType tag"))
    width = scalar_hash_field(exiftool_context, f"{tag}Width")
    height = scalar_hash_field(exiftool_context, f"{tag}Height")
    if payload.startswith("\x89PNG\r\n\x1a\n"):
        return "PNG"
    if payload.startswith("\xff\xd8\xff"):
        return "JPG"
    if width is None or height is None:
        return "DAT"
    pixel_count = int_value(width) * int_value(height)
    if len(payload) != pixel_count * 2:
        return "DAT"
    if string_value(scalar_hash_field(exiftool_context, "ByteOrder")) == "MM":
        return "DAT"
    return "TIFF"


def flir_tiff_payload(
    exiftool_context: ExifToolHashReference,
    payload: str,
    tag: str,
) -> str | None:
    width = scalar_hash_field(exiftool_context, f"{tag}Width")
    height = scalar_hash_field(exiftool_context, f"{tag}Height")
    if width is None or height is None:
        return None
    return string_value(make_tiff_header([width, height, 1, 16])) + payload
