"""Windows LNK exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import ExifToolScalar, int_value


def dos_time(value: ExifToolScalar) -> ExifToolScalar:
    timestamp = int_value(value)
    return (
        f"{((timestamp >> 9) & 0x7F) + 1980:04d}:"
        f"{(timestamp >> 5) & 0x0F:02d}:"
        f"{timestamp & 0x1F:02d} "
        f"{(timestamp >> 27) & 0x1F:02d}:"
        f"{(timestamp >> 21) & 0x3F:02d}:"
        f"{(timestamp >> 15) & 0x3E:02d}"
    )
