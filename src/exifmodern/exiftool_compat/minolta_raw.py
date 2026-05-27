"""MinoltaRaw exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import ExifToolScalar, int_value

MINOLTA_RAW_WB_MODE: dict[int, str] = {
    0: "Auto",
    1: "Daylight",
    2: "Cloudy",
    3: "Tungsten",
    4: "Flash/Fluorescent",
    5: "Fluorescent",
    6: "Shade",
    7: "User 1",
    8: "User 2",
    9: "User 3",
    10: "Temperature",
}


def convert_wb_mode(value: ExifToolScalar) -> ExifToolScalar:
    numeric_value = int_value(value)
    low_nibble = numeric_value & 0x0F
    white_balance = MINOLTA_RAW_WB_MODE.get(low_nibble, f"Unknown ({low_nibble})")
    high_nibble = numeric_value >> 4
    if 6 <= high_nibble <= 12:
        white_balance += f" ({high_nibble - 8})"
    return white_balance
