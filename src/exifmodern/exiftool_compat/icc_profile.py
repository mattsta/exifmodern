"""ICC_Profile exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import ExifToolScalar, int_value, string_value


def hex_id(value: ExifToolScalar) -> ExifToolScalar:
    values = [part for part in string_value(value).split(" ") if part]
    if not any(int_value(part) != 0 for part in values):
        return 0
    return "".join(f"{int_value(part):02x}" for part in values)
