"""RIFF exact-helper compatibility adapters."""

from __future__ import annotations

import re

from exifmodern.exiftool_compat.types import (
    ExifToolContextUpdate,
    ExifToolEffectResult,
    ExifToolHashReference,
    ExifToolScalar,
    ExifToolScalarReference,
    ExifToolValue,
    hash_field,
    hash_reference_value,
    int_value,
    numeric_scalar_or_none,
    numeric_value,
    scalar_value,
    string_value,
)

RIFF_MONTH_NUMBERS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
RIFF_CASIO_DATE_RE = re.compile(r"(\d{4})/\s*(\d+)/\s*(\d+)/?\s+(\d+):\s*(\d+)\s*(P?)")
RIFF_KONICA_DATE_RE = re.compile(r"(\d{4})[-/](\d+)[-/](\d+)\s+(\d+:\d+:\d+)")


def convert_riff_date(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value)
    parts = text.split()
    if len(parts) >= 5:
        month = RIFF_MONTH_NUMBERS.get(parts[1].lower().capitalize())
        if month is not None:
            return f"{int(parts[4]):04d}:{month:02d}:{int(parts[2]):02d} {parts[3]}"
    casio_date = RIFF_CASIO_DATE_RE.search(text)
    if casio_date is not None:
        hour = int(casio_date.group(4)) + (12 if casio_date.group(6) else 0)
        return (
            f"{int(casio_date.group(1)):04d}:{int(casio_date.group(2)):02d}:"
            f"{int(casio_date.group(3)):02d} {hour:02d}:{int(casio_date.group(5)):02d}:00"
        )
    konica_date = RIFF_KONICA_DATE_RE.search(text)
    if konica_date is not None:
        return (
            f"{konica_date.group(1)}:{konica_date.group(2)}:{konica_date.group(3)} "
            f"{konica_date.group(4)}"
        )
    return value


def calc_duration(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) < 3:
        return None
    frame_rate = scalar_number_or_none(values[1])
    frame_count = scalar_number_or_none(values[2])
    if frame_rate is None or frame_count is None or frame_rate == 0:
        return None
    duration = frame_count / frame_rate
    if len(values) >= 5:
        video_frame_rate = scalar_number_or_none(values[3])
        video_frame_count = scalar_number_or_none(values[4])
        if video_frame_rate is not None and video_frame_count is not None and video_frame_rate != 0:
            video_duration = video_frame_count / video_frame_rate
            ratio = duration / video_duration
            if 1.9 < ratio < 3.1:
                return video_duration
    return duration


def anmf_frame_duration(values: list[ExifToolValue]) -> ExifToolEffectResult:
    if len(values) != 2:
        return ExifToolEffectResult(value=None)
    exiftool_context = hash_reference_value(values[0], "RIFF ANMF ExifTool context")
    frame_duration = int_value(scalar_value(values[1], "RIFF ANMF frame duration")) & 0x0FFF
    value_record = hash_field(exiftool_context, "VALUE")
    if not isinstance(value_record, ExifToolHashReference):
        return ExifToolEffectResult(value=frame_duration)
    current_duration = hash_field(value_record, "Duration")
    if current_duration is None:
        return ExifToolEffectResult(value=frame_duration)
    updated_duration = numeric_value(scalar_value(current_duration, "RIFF Duration value"))
    updated_duration += frame_duration
    return ExifToolEffectResult(
        value=None,
        context_updates=(
            ExifToolContextUpdate(
                namespace="$$self",
                path=("VALUE", "Duration"),
                value=updated_duration,
            ),
        ),
    )


def scalar_number_or_none(value: ExifToolValue) -> float | None:
    if isinstance(value, (tuple, ExifToolHashReference, ExifToolScalarReference)):
        return None
    return numeric_scalar_or_none(value)
