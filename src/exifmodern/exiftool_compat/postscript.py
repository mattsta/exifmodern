"""PostScript helper adapters with exact ExifTool-compatible contracts."""

from __future__ import annotations

import re

from exifmodern.exiftool_compat.types import (
    ExifToolArrayReference,
    ExifToolCompatibilityError,
    ExifToolHashReference,
    ExifToolScalar,
    ExifToolScalarReference,
    ExifToolValue,
    int_value,
    string_value,
)

IMAGE_DATA_RE = re.compile(r"^(\d+) (\d+)")
BOUNDING_BOX_RE = re.compile(r"^(\d+) (\d+) (\d+) (\d+)")


def image_size(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 2:
        raise ExifToolCompatibilityError(
            f"PostScript ImageSize expected 2 arguments, got {len(values)}."
        )
    size_values = array_reference_value(values[0])
    get_height = int_value(scalar_value(values[1])) != 0
    width, height = image_size_dimensions(size_values)
    return height if get_height else width


def image_size_dimensions(values: ExifToolArrayReference) -> tuple[int | None, int | None]:
    if len(values) >= 1 and values[0]:
        match = IMAGE_DATA_RE.match(string_value(scalar_value(values[0])))
        if match is not None:
            return int(match.group(1)), int(match.group(2))
    if len(values) >= 2 and values[1]:
        match = BOUNDING_BOX_RE.match(string_value(scalar_value(values[1])))
        if match is not None:
            left = int(match.group(1))
            bottom = int(match.group(2))
            right = int(match.group(3))
            top = int(match.group(4))
            return right - left, top - bottom
    return None, None


def array_reference_value(value: ExifToolValue) -> ExifToolArrayReference:
    if isinstance(value, tuple):
        return value
    raise ExifToolCompatibilityError("PostScript ImageSize first argument must be an array ref.")


def scalar_value(value: ExifToolValue) -> ExifToolScalar:
    if isinstance(value, (tuple, ExifToolHashReference, ExifToolScalarReference)):
        raise ExifToolCompatibilityError("PostScript ImageSize scalar argument is a reference.")
    return value
