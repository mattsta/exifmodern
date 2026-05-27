"""Reconyx compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import ExifToolScalar, ExifToolValue, int_value, scalar_value


def hyperfire_datetime(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 1:
        return None
    parts = [int_value(part) for part in str(scalar_value(values[0], "Reconyx datetime")).split()]
    if len(parts) < 6:
        return None
    if parts[0] & 0xFF00 and not parts[0] & 0xFF:
        parts = [((part >> 8) | ((part & 0xFF) << 8)) for part in parts]
    return (
        f"{parts[5]:04d}:{parts[3]:02d}:{parts[4]:02d} {parts[2]:02d}:{parts[1]:02d}:{parts[0]:02d}"
    )
