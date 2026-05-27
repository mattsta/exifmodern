"""Minolta exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import ExifToolScalar, int_value

MINOLTA_WHITE_BALANCE: dict[int, str] = {
    0: "Auto",
    1: "Daylight",
    2: "Cloudy",
    3: "Tungsten",
    5: "Custom",
    7: "Fluorescent",
    8: "Fluorescent 2",
    11: "Custom 2",
    12: "Custom 3",
    0x0800000: "Auto",
    0x1800000: "Daylight",
    0x2800000: "Cloudy",
    0x3800000: "Tungsten",
    0x4800000: "Flash",
    0x5800000: "Fluorescent",
    0x6800000: "Shade",
    0x7800000: "Custom1",
    0x8800000: "Custom2",
    0x9800000: "Custom3",
}


def convert_white_balance(value: ExifToolScalar) -> ExifToolScalar:
    numeric_value = int_value(value)
    white_balance = MINOLTA_WHITE_BALANCE.get(numeric_value)
    if white_balance is not None:
        return white_balance
    if numeric_value & 0xFFFF0000:
        white_balance_type = (numeric_value & 0xFF000000) + 0x800000
        white_balance = MINOLTA_WHITE_BALANCE.get(white_balance_type)
        if white_balance is not None:
            offset = (numeric_value - white_balance_type) / 0x10000
            return f"{white_balance}{offset:+.8g}"
        return f"Unknown (0x{numeric_value:x})"
    return f"Unknown ({numeric_value})"
