"""Composite-tag compatibility adapters for large legacy conversion blocks."""

from __future__ import annotations

import math

from exifmodern.exiftool_compat.core import scalar_to_float
from exifmodern.exiftool_compat.types import (
    ExifToolHashReference,
    ExifToolScalar,
    ExifToolValue,
    hash_field,
    int_value,
    numeric_scalar_or_none,
    perl_numeric_text,
    perl_truthy,
    scalar_value,
    string_value,
)


def canon_file_number(values: list[ExifToolValue]) -> ExifToolScalar:
    scalars = scalar_arguments(values)
    if len(scalars) < 2:
        return None
    directory_index = int_value(scalars[0])
    file_index = int_value(scalars[1])
    if file_index == 10000:
        file_index = 1
        directory_index += 1
    return f"{directory_index:03d}{file_index:04d}"


def depth_of_field(values: list[ExifToolValue]) -> ExifToolScalar:
    scalars = to_float_arguments(values)
    focal_length = float_or_none(scalars, 0)
    aperture = float_or_none(scalars, 1)
    circle_of_confusion = float_or_none(scalars, 2)
    distance = depth_distance(scalars)
    if distance is None:
        return None
    if (
        focal_length is None
        or focal_length == 0
        or circle_of_confusion is None
        or circle_of_confusion == 0
    ):
        return 0
    aperture_value = 0.0 if aperture is None else aperture
    focus_term = aperture_value * circle_of_confusion * (distance * 1000 - focal_length)
    focus_term /= focal_length * focal_length
    near = distance / (1 + focus_term)
    far = distance / (1 - focus_term)
    if far < 0:
        far = 0
    return f"{perl_numeric_text(near)} {perl_numeric_text(far)}"


def depth_distance(values: list[ExifToolScalar]) -> float | None:
    explicit_distance = float_or_none(values, 3)
    if explicit_distance is not None:
        return 1e10 if not perl_truthy(explicit_distance) else explicit_distance
    for index in (4, 5, 6):
        candidate = float_or_none(values, index)
        if perl_truthy(candidate):
            return candidate
    near = float_or_none(values, 7)
    far = float_or_none(values, 8)
    if near is None or far is None:
        return None
    return (near + far) / 2


def field_of_view(values: list[ExifToolValue]) -> ExifToolScalar:
    scalars = to_float_arguments(values)
    focal_length = float_or_none(scalars, 0)
    scale_factor = float_or_none(scalars, 1)
    if focal_length is None or focal_length == 0 or scale_factor is None or scale_factor == 0:
        return None
    subject_distance = float_or_none(scalars, 2)
    correction = 1.0
    if subject_distance is not None and subject_distance != 0:
        distance_offset = 1000 * subject_distance - focal_length
        if distance_offset > 0:
            correction += focal_length / distance_offset
    half_angle = math.atan2(36, 2 * focal_length * scale_factor * correction)
    fields = [half_angle * 360 / 3.14159]
    if subject_distance is not None and subject_distance > 0 and subject_distance < 10000:
        fields.append(2 * subject_distance * math.sin(half_angle) / math.cos(half_angle))
    return " ".join(perl_numeric_text(field) for field in fields)


def xmp_flash_value(values: list[ExifToolValue]) -> ExifToolScalar:
    flash_values = xmp_flash_components(values)
    fired = truth_text(flash_scalar(flash_values, 0))
    red_eye_mode = truth_text(flash_scalar(flash_values, 4))
    return (
        (0x01 if fired else 0)
        | (int_or_zero(flash_scalar(flash_values, 1)) << 1)
        | (int_or_zero(flash_scalar(flash_values, 2)) << 3)
        | (0x20 if truth_text(flash_scalar(flash_values, 3)) else 0)
        | (0x40 if red_eye_mode else 0)
    )


def xmp_flash_components(values: list[ExifToolValue]) -> list[ExifToolValue | None]:
    if len(values) > 5 and isinstance(values[5], ExifToolHashReference):
        return [
            hash_field(values[5], "Fired"),
            hash_field(values[5], "Return"),
            hash_field(values[5], "Mode"),
            hash_field(values[5], "Function"),
            hash_field(values[5], "RedEyeMode"),
        ]
    return list(values)


def flash_scalar(values: list[ExifToolValue | None], index: int) -> ExifToolScalar:
    if index >= len(values) or values[index] is None:
        return None
    return scalar_value(values[index], "XMP flash component")


def truth_text(value: ExifToolScalar) -> bool:
    return perl_truthy(value) and string_value(value).lower() == "true"


def int_or_zero(value: ExifToolScalar) -> int:
    return 0 if not perl_truthy(value) else int_value(value)


def scalar_arguments(values: list[ExifToolValue]) -> list[ExifToolScalar]:
    scalars: list[ExifToolScalar] = []
    for value in values:
        if isinstance(value, tuple):
            scalars.extend(scalar_value(item, "Composite adapter array argument") for item in value)
        else:
            scalars.append(scalar_value(value, "Composite adapter argument"))
    return scalars


def to_float_arguments(values: list[ExifToolValue]) -> list[ExifToolScalar]:
    return [scalar_to_float(value) for value in scalar_arguments(values)]


def float_or_none(values: list[ExifToolScalar], index: int) -> float | None:
    if index >= len(values):
        return None
    return numeric_scalar_or_none(values[index])
