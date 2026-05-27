"""Kodak exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    int_value,
    numeric_value,
    perl_truthy,
    string_value,
)


def calculate_rgb_levels(values: list[ExifToolScalar]) -> ExifToolScalar:
    if len(values) < 9:
        raise ExifToolCompatibilityError(
            f"CalculateRGBLevels expected at least 9 arguments, got {len(values)}."
        )
    if len(values) > 10 and perl_truthy(values[10]):
        return None
    white_balance_index = int_value(values[0])
    if white_balance_index < 0 or white_balance_index > 3:
        return None
    multipliers = string_value(values[white_balance_index + 1]).split(maxsplit=12)
    coefficients = string_value(values[white_balance_index + 5]).split()
    white_balance_temperature = numeric_value(values[9]) if len(values) > 9 and values[9] else 6500
    white_balance_temperature_100 = white_balance_temperature / 100
    if len(multipliers) < 3 or len(coefficients) < 12:
        return None
    camera_multipliers: list[float] = []
    coefficient_index = 0
    for color_index in range(3):
        coefficient_sum = 0.0
        for exponent in range(4):
            coefficient_sum += numeric_value(coefficients[coefficient_index]) * (
                white_balance_temperature_100**exponent
            )
            coefficient_index += 1
        camera_multipliers.append(
            2048 / (coefficient_sum * numeric_value(multipliers[color_index]))
        )
    return " ".join(str(value) for value in camera_multipliers)
