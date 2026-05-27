"""Garmin compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import (
    ExifToolScalar,
    ExifToolValue,
    numeric_value,
    perl_numeric_text,
    scalar_value,
    string_value,
)


def gps_hundredths(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 1:
        return None
    value = string_value(scalar_value(values[0], "Garmin GPS hundredths payload"))
    return " ".join(perl_numeric_text(numeric_value(token) / 100) for token in value.split())
