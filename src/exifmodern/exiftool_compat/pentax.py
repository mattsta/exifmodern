"""Pentax exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    int_value,
    numeric_value,
    string_value,
)


def pentax_ev(value: ExifToolScalar) -> ExifToolScalar:
    ev_code = int_value(value)
    adjusted_ev_code = float(ev_code)
    if ev_code & 0x01:
        sign = -1 if ev_code < 0 else 1
        fraction = (ev_code * sign) & 0x07
        if fraction == 0x03:
            adjusted_ev_code += sign * (8 / 3 - fraction)
        elif fraction == 0x05:
            adjusted_ev_code += sign * (16 / 3 - fraction)
    return adjusted_ev_code / 8


def pentax_ev_inv(value: ExifToolScalar) -> ExifToolScalar:
    number = numeric_value(value)
    ev_code = number * 8
    sign = -1 if number < 0 else 1
    fraction = number * sign - int(number * sign)
    if 0.29 < fraction < 0.4:
        ev_code += sign / 3
    elif 0.6 < fraction < 0.71:
        ev_code -= sign / 3
    return int(ev_code + 0.5 * sign)


def decode_af_points(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 4 <= len(values) <= 5:
        raise ExifToolCompatibilityError(
            f"Pentax DecodeAFPoints expected 4 to 5 arguments, got {len(values)}."
        )
    byte_values = [int(part) for part in string_value(values[0]).split()]
    if not byte_values:
        return "(none)"
    point_count = int_value(values[1])
    bits_per_point = int_value(values[2])
    mask = int_value(values[3])
    bit_value = int_value(values[4]) if len(values) == 5 else None
    point_index = 1
    shift = 8 - bits_per_point
    byte_index = 0
    selected_points: list[str] = []
    while True:
        byte = byte_values[byte_index]
        decoded = (byte >> shift) & mask
        if (bit_value is not None and decoded == bit_value) or (bit_value is None and decoded != 0):
            selected_points.append(str(point_index))
        point_index += 1
        if point_index > point_count:
            break
        shift -= bits_per_point
        if shift < 0:
            byte_index += 1
            if byte_index >= len(byte_values):
                break
            shift += 8
    return ",".join(selected_points)
