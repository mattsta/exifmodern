"""Canon exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    byte_values,
    int_value,
    numeric_value,
    perl_truthy,
)

CANON_1D_AF_POINT_CODES: tuple[int, ...] = (
    0,
    0,
    0x04,
    0x06,
    0x08,
    0x0A,
    0x0C,
    0x0E,
    0x10,
    0,
    0,
    0x21,
    0x23,
    0x25,
    0x27,
    0x29,
    0x2B,
    0x2D,
    0x2F,
    0x31,
    0x33,
    0x40,
    0x42,
    0x44,
    0x46,
    0x48,
    0x4A,
    0x4C,
    0x4D,
    0x50,
    0x52,
    0x54,
    0x61,
    0x63,
    0x65,
    0x67,
    0x69,
    0x6B,
    0x6D,
    0x6F,
    0x71,
    0x73,
    0,
    0,
    0x84,
    0x86,
    0x88,
    0x8A,
    0x8C,
    0x8E,
    0x90,
    0,
    0,
    0,
    0,
    0,
)
CANON_1D_AF_POINT_ROWS = "  AAAAAAA  BBBBBBBBBBCCCCCCCCCCCDDDDDDDDDD  EEEEEEE     "


def canon_ev(value: ExifToolScalar) -> ExifToolScalar:
    ev_code = int_value(value)
    sign = 1
    if ev_code < 0:
        ev_code = -ev_code
        sign = -1
    fraction_code = ev_code & 0x1F
    ev_code -= fraction_code
    if fraction_code == 0x0C:
        fraction_value = 0x20 / 3
    elif fraction_code == 0x14:
        fraction_value = 0x40 / 3
    else:
        fraction_value = fraction_code
    return sign * (ev_code + fraction_value) / 0x20


def canon_ev_inv(value: ExifToolScalar) -> ExifToolScalar:
    number = numeric_value(value)
    sign = 1
    if number < 0:
        number = -number
        sign = -1
    ev_integer = int(number)
    fraction = number - ev_integer
    if abs(fraction - 0.33) < 0.05:
        fraction_code = 0x0C
    elif abs(fraction - 0.67) < 0.05:
        fraction_code = 0x14
    else:
        fraction_code = int(fraction * 0x20 + 0.5)
    return sign * (ev_integer * 0x20 + fraction_code)


def camera_iso(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 1 <= len(values) <= 2:
        raise ExifToolCompatibilityError(f"CameraISO expected 1 to 2 arguments, got {len(values)}.")
    iso_lookup: dict[int, ExifToolScalar] = {
        0: "n/a",
        14: "Auto High",
        15: "Auto",
        16: 50,
        17: 100,
        18: 200,
        19: 400,
        20: 800,
    }
    value = int_value(values[0])
    inverse = len(values) > 1 and perl_truthy(values[1])
    if inverse:
        reversed_value = reverse_iso_lookup(values[0], iso_lookup)
        if reversed_value is not None:
            return reversed_value
        return (value & 0x3FFF) | 0x4000
    if value == 0x7FFF:
        return None
    if value & 0x4000:
        return value & 0x3FFF
    return iso_lookup.get(value, f"Unknown ({value})")


def reverse_iso_lookup(
    value: ExifToolScalar,
    iso_lookup: dict[int, ExifToolScalar],
) -> int | None:
    for iso_code, iso_value in iso_lookup.items():
        if str(iso_value) == str(value):
            return iso_code
    return None


def print_focal_range(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 2 <= len(values) <= 3:
        raise ExifToolCompatibilityError(
            f"PrintFocalRange expected 2 to 3 arguments, got {len(values)}."
        )
    short = numeric_value(values[0])
    long = numeric_value(values[1])
    scale = numeric_value(values[2]) if len(values) >= 3 and perl_truthy(values[2]) else 1.0
    if short == long:
        return f"{short * scale:.1f} mm"
    return f"{short * scale:.1f} - {long * scale:.1f} mm"


def print_af_points_1d(value: ExifToolScalar) -> ExifToolScalar:
    af_bytes = byte_values(value)
    if len(af_bytes) != 8:
        return "Unknown"
    focus = af_bytes[0]
    selected_bits = least_significant_bit_first_bits(af_bytes[1:])
    active_points: list[str] = []
    focusing = ""
    last_row = ""
    column = 0
    for index, focus_point_code in enumerate(CANON_1D_AF_POINT_CODES):
        row = CANON_1D_AF_POINT_ROWS[index]
        column = column + 1 if row == last_row else 1
        last_row = row
        point_name = f"{row}{column}"
        if focus == focus_point_code:
            focusing = point_name
        if selected_bits[index]:
            active_points.append(point_name)
    if not focusing:
        focusing = "Auto" if focus == 0xFF else f"Unknown (0x{focus:02x})"
    return f"{focusing} ({','.join(active_points)})"


def least_significant_bit_first_bits(values: list[int]) -> list[bool]:
    bits: list[bool] = []
    for value in values:
        for shift in range(8):
            bits.append((value & (1 << shift)) != 0)
    return bits
