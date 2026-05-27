"""Nikon exact-helper compatibility adapters."""

from __future__ import annotations

import re

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolContextUpdate,
    ExifToolEffectResult,
    ExifToolHashReference,
    ExifToolScalar,
    ExifToolValue,
    hash_field,
    hash_reference_value,
    int_value,
    numeric_scalar_or_none,
    numeric_value,
    perl_numeric_text,
    perl_truthy,
    scalar_hash_field,
    scalar_value,
    string_value,
)

NUMERIC_TEXT_RE = re.compile(r"^[-+]?\d+(\.\d+)?$")


def nikon_print_pc(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 1 <= len(values) <= 4:
        raise ExifToolCompatibilityError(
            f"Image::ExifTool::Nikon::PrintPC expected 1 to 4 arguments, got {len(values)}."
        )
    value = numeric_value(values[0])
    normal = values[1] if len(values) >= 2 else None
    template = string_value(values[2]) if len(values) >= 3 and values[2] is not None else "%+d"
    divisor = numeric_value(values[3]) if len(values) >= 4 and values[3] is not None else 1.0
    if value == 0:
        return string_value(normal) if normal is not None and perl_truthy(normal) else "Normal"
    if value == 0x7F:
        return "n/a"
    if value == -128:
        return "Auto"
    if value == -127:
        return "User"
    return template % (value / divisor)


def nikon_print_pc_inv(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 1 <= len(values) <= 2:
        raise ExifToolCompatibilityError(
            f"Image::ExifTool::Nikon::PrintPCInv expected 1 to 2 arguments, got {len(values)}."
        )
    text = string_value(values[0])
    divisor = numeric_value(values[1]) if len(values) >= 2 and values[1] is not None else 1.0
    if NUMERIC_TEXT_RE.match(text):
        result = numeric_value(values[0]) * divisor
        if result.is_integer():
            return int(result)
        return result
    lowered = text.lower()
    if "n/a" in lowered:
        return 0x7F
    if "auto" in lowered:
        return -128
    if "user" in lowered:
        return -127
    return 0


def nikon_print_pc_inv2(values: list[ExifToolScalar]) -> ExifToolScalar:
    return nikon_print_pc_inv(values)


def auto_capture_trigger_bits(values: list[ExifToolValue]) -> ExifToolScalar:
    return decode_bit_labels(
        values,
        (
            "Distance",
            "Motion",
            "Subject Detection",
        ),
    )


def auto_capture_area_bits(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 1:
        return None
    value = scalar_value(values[0], "Nikon auto-capture area bits")
    if string_value(value) == "255":
        return "All"
    return decode_bit_labels(
        values,
        (
            "Top Left",
            "Top Right",
            "Bottom Left",
            "Bottom Right",
            "Left",
            "Right",
            "Top Center",
            "Bottom Center",
        ),
    )


def decode_bit_labels(values: list[ExifToolValue], labels: tuple[str, ...]) -> ExifToolScalar:
    if len(values) != 1:
        return None
    bits = int_value(scalar_value(values[0], "Nikon bit-field value"))
    selected = [label for index, label in enumerate(labels) if bits & (1 << index)]
    return ", ".join(selected) if selected else "(none)"


def lens_drive_end(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 2:
        return None
    focus_distance_range_width = scalar_value(
        values[0],
        "Nikon FocusDistanceRangeWidth value",
    )
    current_value = scalar_value(values[1], "Nikon LensDriveEnd value")
    if focus_distance_range_width is not None and not perl_truthy(focus_distance_range_width):
        return "Inf"
    return "No" if not perl_truthy(current_value) else "CFD"


def lens_drive_end_update(values: list[ExifToolValue]) -> ExifToolEffectResult:
    if len(values) != 2:
        return ExifToolEffectResult(value=None)
    exiftool_context = hash_reference_value(values[0], "Nikon LensDriveEnd ExifTool context")
    focus_distance_range_width = scalar_hash_field(exiftool_context, "FocusDistanceRangeWidth")
    result = lens_drive_end([focus_distance_range_width, values[1]])
    return ExifToolEffectResult(
        value=result,
        context_updates=(
            ExifToolContextUpdate(namespace="$$self", path=("LensDriveEnd",), value=result),
        ),
    )


def focus_shift_frame(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 2:
        return None
    exiftool_context = hash_reference_value(values[0], "Nikon FocusShift ExifTool context")
    frame = numeric_value(scalar_value(values[1], "Nikon focus-shift frame"))
    if frame == 0:
        return "Off"
    pixel_shift_active = scalar_hash_field(exiftool_context, "PixelShiftActive")
    if pixel_shift_active == 1:
        return f"On: Frame {perl_numeric_text(round_half_up(frame))}"
    shot_count = scalar_hash_field(exiftool_context, "FocusShiftNumberShots")
    shot_count_value = 0.0 if shot_count is None else numeric_value(shot_count)
    return (
        f"On: Frame {perl_numeric_text(round_half_up(frame))} "
        f"of {perl_numeric_text(round_half_up(shot_count_value))}"
    )


def z9_af_area_x(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 2:
        return None
    context = hash_reference_value(values[0], "Nikon Z9 AF-area X context")
    position = numeric_value(scalar_value(values[1], "Nikon Z9 AF-area X value"))
    image_area = int_context_value(context, "ImageArea")
    af_area_mode = int_value_record(context, "AFAreaMode")
    start = 502
    increment = 259
    if image_area == 8:
        start += 5 * increment
    if position < 49 and image_area in {0, 4}:
        start -= increment
    if image_area == 8 and af_area_mode == 6:
        start -= increment
    if image_area == 1:
        start = 636
        increment = 388
        if af_area_mode == 3:
            start = 591
            increment = 393
        if af_area_mode == 6:
            start -= increment
    divisor = 3.99
    if position >= 50:
        divisor = 4.01
    if image_area in {1, 8}:
        divisor = 6
    focus_box_width = numeric_context_value(context, "AFAreaInitialWidth")
    if image_area in {1, 8}:
        focus_box_width = int(focus_box_width * 2 / 3)
    skip_positions = int(focus_box_width / 2)
    rounded_position = round_half_up(position / divisor)
    return start + increment * (rounded_position + skip_positions - 1)


def z9_af_area_y(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 2:
        return None
    context = hash_reference_value(values[0], "Nikon Z9 AF-area Y context")
    position = numeric_value(scalar_value(values[1], "Nikon Z9 AF-area Y value"))
    image_area = int_context_value(context, "ImageArea")
    af_area_mode = int_value_record(context, "AFAreaMode")
    start = 424
    increment = 291
    if image_area == 4 and position > 0:
        start += increment
    if image_area == 1:
        start = 572
        increment = 436
        if af_area_mode == 3:
            start = 542
            increment = 442
    divisor = 6.67
    if image_area == 1:
        divisor = 10.01
    if image_area == 4:
        divisor = 8.01
    focus_box_height = numeric_context_value(context, "AFAreaInitialHeight")
    if image_area == 1:
        focus_box_height = int(focus_box_height * 2 / 3)
    skip_positions = int(focus_box_height / 2)
    rounded_position = round_half_up(position / divisor)
    return start + increment * (rounded_position + skip_positions - 1)


def round_half_up(value: float) -> int:
    return int(value + 0.5)


def int_context_value(context: ExifToolHashReference, key: str) -> int:
    return int(numeric_context_value(context, key))


def numeric_context_value(context: ExifToolHashReference, key: str) -> float:
    value = scalar_hash_field(context, key)
    numeric = numeric_scalar_or_none(value)
    return 0.0 if numeric is None else numeric


def int_value_record(context: ExifToolHashReference, key: str) -> int:
    value_record = hash_field(context, "VALUE")
    if not isinstance(value_record, ExifToolHashReference):
        return 0
    value = scalar_hash_field(value_record, key)
    numeric = numeric_scalar_or_none(value)
    return 0 if numeric is None else int(numeric)
