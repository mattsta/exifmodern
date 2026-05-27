"""Olympus exact-helper compatibility adapters."""

from __future__ import annotations

import re

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    ExifToolValue,
    int_value,
    numeric_value,
    scalar_value,
    string_value,
)

LENS_MAX_APERTURE_RE = re.compile(r" F(\d+(?:\.\d+)?)")
OLYMPUS_AF_POINT_NAMES: dict[int, str] = {
    0x36794285: "Left",
    0x79798585: "Center",
    0xBD79C985: "Right",
}


def extender_status(values: list[ExifToolScalar]) -> ExifToolScalar:
    if len(values) != 3:
        raise ExifToolCompatibilityError(f"ExtenderStatus expected 3 arguments, got {len(values)}.")
    extender = string_value(values[0])
    info = extender.split()
    if len(info) < 2 or int(info[1], 16) == 0:
        return 0
    if f"{info[0]} {info[1]}" != "0 04":
        return 1
    match = LENS_MAX_APERTURE_RE.search(string_value(values[1]))
    if match is None:
        return 1
    return 1 if numeric_value(values[2]) - float(match.group(1)) > 0.2 else 2


def print_af_areas(value: ExifToolScalar) -> ExifToolScalar:
    rendered_points: list[str] = []
    for point in string_value(value).split():
        numeric_point = int_value(point)
        if numeric_point == 0:
            continue
        point_name = OLYMPUS_AF_POINT_NAMES.get(numeric_point)
        rendered_point = "" if point_name is None else point_name + " "
        point_bytes = uint32_be_bytes(numeric_point)
        rendered_point += f"({point_bytes[0]},{point_bytes[1]})-({point_bytes[2]},{point_bytes[3]})"
        rendered_points.append(rendered_point)
    return ", ".join(rendered_points) if rendered_points else "none"


def panorama_direction(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 1:
        return None
    parts = string_value(scalar_value(values[0], "Olympus panorama direction")).split()
    if len(parts) < 2 or int_value(parts[0]) == 0:
        return "Off"
    directions = {
        1: "Left to Right",
        2: "Right to Left",
        3: "Bottom to Top",
        4: "Top to Bottom",
    }
    direction = directions.get(int_value(parts[0]), f"Unknown ({parts[0]})")
    return f"{direction}, Shot {parts[1]}"


def uint32_be_bytes(value: int) -> tuple[int, int, int, int]:
    return (
        (value >> 24) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF,
    )
