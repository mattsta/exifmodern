"""ASF exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import ExifToolScalar, byte_values


def get_guid(value: ExifToolScalar) -> ExifToolScalar:
    data = byte_values(value)
    if len(data) != 16:
        return value
    first = int.from_bytes(bytes(data[0:4]), "little")
    second = int.from_bytes(bytes(data[4:6]), "little")
    third = int.from_bytes(bytes(data[6:8]), "little")
    fourth = bytes(data[8:10]).hex()
    fifth = bytes(data[10:16]).hex()
    return f"{first:08x}-{second:04x}-{third:04x}-{fourth}-{fifth}".upper()
