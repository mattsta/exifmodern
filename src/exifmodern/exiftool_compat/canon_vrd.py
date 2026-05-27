"""Canon VRD exact-helper compatibility adapters."""

from __future__ import annotations

import re

from exifmodern.exiftool_compat.types import ExifToolScalar, string_value

TONE_CURVE_POINT_RE = re.compile(r"\((\d+),(\d+)\)")


def tone_curve_print(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value)
    values = text.split()
    if len(values) != 21:
        return value
    point_count = int(values[0])
    if point_count < 2 or point_count > 10:
        return value
    coordinates = values[1:]
    points: list[str] = []
    for point_index in range(point_count):
        coordinate_index = point_index * 2
        points.append(f"({coordinates[coordinate_index]},{coordinates[coordinate_index + 1]})")
    return " ".join(points)


def tone_curve_print_inv(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value)
    values: list[str] = []
    for match in TONE_CURVE_POINT_RE.finditer(text):
        values.append(match.group(1))
        values.append(match.group(2))
    if len(values) < 4 or len(values) > 20 or len(values) & 0x01:
        return None
    encoded_values: list[str] = [str(len(values) // 2), *values]
    while len(encoded_values) < 21:
        encoded_values.append("0")
    return " ".join(encoded_values)
