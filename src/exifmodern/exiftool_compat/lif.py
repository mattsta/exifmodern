"""LIF compatibility adapters."""

from __future__ import annotations

import re

from exifmodern.exiftool_compat.core import convert_unix_time
from exifmodern.exiftool_compat.types import (
    ExifToolScalar,
    ExifToolValue,
    scalar_value,
    string_value,
)

HEX_TEXT_RE = re.compile(r"^[0-9a-f]+$", re.IGNORECASE)
WINDOWS_TO_UNIX_SECONDS = 134774 * 24 * 3600


def timestamp_list(values: list[ExifToolValue]) -> ExifToolValue:
    if len(values) != 1:
        return ()
    payload = string_value(scalar_value(values[0], "LIF timestamp list payload"))
    converted: list[ExifToolScalar] = []
    for token in payload.split():
        converted.append(lif_timestamp_token(token))
    return tuple(converted)


def lif_timestamp_token(token: str) -> ExifToolScalar:
    if HEX_TEXT_RE.match(token) is None:
        return "0000:00:00 00:00:00"
    windows_ticks = int(token, 16)
    unix_seconds = 1e-7 * windows_ticks - WINDOWS_TO_UNIX_SECONDS
    return convert_unix_time([unix_seconds])
