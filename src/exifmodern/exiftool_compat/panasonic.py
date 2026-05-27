"""Panasonic compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import (
    ExifToolContextUpdate,
    ExifToolEffectResult,
    ExifToolValue,
    scalar_value,
    string_value,
)

JPEG_START = "\xff\xd8\xff"


def pana_thumb_type(values: list[ExifToolValue]) -> ExifToolEffectResult:
    if len(values) != 1:
        return ExifToolEffectResult(value=None)
    payload = string_value(scalar_value(values[0], "Panasonic PANA thumbnail payload"))
    thumb_type = pana_thumb_type_value(payload)
    return ExifToolEffectResult(
        value=None,
        context_updates=(
            ExifToolContextUpdate(namespace="$$self", path=("ThumbType",), value=thumb_type),
        ),
    )


def pana_thumb_type_value(payload: str) -> int:
    if payload[0x1C:0x1F] == JPEG_START:
        return 1
    if payload[0x506:0x509] == JPEG_START:
        return 2
    if payload[0x51E:0x521] == JPEG_START:
        return 3
    return 0
