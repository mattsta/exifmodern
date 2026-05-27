"""Photoshop exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    string_value,
)


def convert_pascal_string(values: list[ExifToolScalar]) -> ExifToolScalar:
    if len(values) != 2:
        raise ExifToolCompatibilityError(
            f"ConvertPascalString expected 2 arguments, got {len(values)}."
        )
    text = string_value(values[1])
    rendered_values: list[str] = []
    position = 0
    while position < len(text):
        length = ord(text[position])
        if position + length >= len(text):
            break
        rendered_values.append(text[position + 1 : position + 1 + length])
        position += length + 1
    return ", ".join(rendered_values)
