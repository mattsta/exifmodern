"""FujiFilm compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import (
    ExifToolHashReference,
    ExifToolScalar,
    ExifToolValue,
    numeric_value,
    perl_numeric_text,
    perl_truthy,
    scalar_hash_field,
    scalar_value,
    string_value,
)


def raf_layout_dimensions(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 2 or not isinstance(values[0], ExifToolHashReference):
        return None
    payload = string_value(scalar_value(values[1], "FujiFilm RAF layout payload"))
    dimensions = [numeric_value(part) for part in reversed(payload.split())]
    if len(dimensions) >= 2 and perl_truthy(scalar_hash_field(values[0], "FujiLayout")):
        dimensions[0] /= 2
        dimensions[1] *= 2
    return " ".join(perl_numeric_text(dimension) for dimension in dimensions)
