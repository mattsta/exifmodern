"""GoPro exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolContextUpdate,
    ExifToolEffectResult,
    ExifToolHashReference,
    ExifToolScalar,
    ExifToolValue,
    hash_field,
    hash_reference_value,
    scalar_value,
    string_value,
)


def add_units(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 3:
        raise ExifToolCompatibilityError(f"GoPro AddUnits expected 3 arguments, got {len(values)}.")
    exiftool_context = hash_reference_value(values[0], "GoPro AddUnits ExifTool context")
    value = scalar_value(values[1], "GoPro AddUnits value")
    tag = string_value(scalar_value(values[2], "GoPro AddUnits tag"))
    units = gopro_tag_units(exiftool_context, tag)
    if not units:
        return value
    parts = string_value(value).split()
    if len(units) != len(parts):
        return value
    return " ".join(
        f"{part} {unit}" if unit else part for part, unit in zip(parts, units, strict=True)
    )


def system_time_list_update(values: list[ExifToolValue]) -> ExifToolEffectResult:
    if len(values) != 2:
        return ExifToolEffectResult(value=None)
    exiftool_context = hash_reference_value(
        values[0],
        "GoPro SystemTimeList ExifTool context",
    )
    value = scalar_value(values[1], "GoPro SystemTimeList payload")
    parts = tuple(string_value(value).split())
    if len(parts) != 2:
        return ExifToolEffectResult(value=value)
    existing = hash_field(exiftool_context, "SystemTimeList")
    existing_entries = existing if isinstance(existing, tuple) else ()
    return ExifToolEffectResult(
        value=value,
        context_updates=(
            ExifToolContextUpdate(
                namespace="$$self",
                path=("SystemTimeList",),
                value=(*existing_entries, parts),
            ),
        ),
    )


def gopro_tag_units(exiftool_context: ExifToolHashReference, tag: str) -> tuple[str, ...]:
    tag_extra = hash_field(exiftool_context, "TAG_EXTRA")
    if not isinstance(tag_extra, ExifToolHashReference):
        return ()
    tag_record = hash_field(tag_extra, tag)
    if not isinstance(tag_record, ExifToolHashReference):
        return ()
    units = hash_field(tag_record, "Units")
    if isinstance(units, tuple):
        return tuple(
            string_value(scalar_value(unit, "GoPro AddUnits Units item")) for unit in units
        )
    if units is None:
        return ()
    return (string_value(scalar_value(units, "GoPro AddUnits Units field")),)
