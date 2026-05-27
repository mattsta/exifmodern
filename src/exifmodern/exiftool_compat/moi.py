"""MOI compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import ExifToolScalar, ExifToolValue, int_value, scalar_value


def aspect_ratio(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 1:
        return None
    value = int_value(scalar_value(values[0], "MOI aspect ratio value"))
    low = value & 0x0F
    high = value >> 4
    if low < 2:
        aspect = "4:3"
    elif low in {4, 5}:
        aspect = "16:9"
    else:
        aspect = "Unknown"
    if high == 4:
        aspect += " NTSC"
    elif high == 5:
        aspect += " PAL"
    return aspect
