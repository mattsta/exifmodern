"""Global ExifTool helper compatibility adapters."""

from __future__ import annotations

import calendar
import re
import time

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    byte_values,
    int_value,
    numeric_scalar_or_none,
    perl_truthy,
    string_value,
)

EXIF_DATETIME_RE = re.compile(r"^(\d+)[-:](\d+)[-:](\d+)\s+(\d+):(\d+):(\d+)(.*)")
TIMEZONE_RE = re.compile(r"(?:Z|([-+])(\d+):(\d+))", re.IGNORECASE)
FRACTIONAL_SECONDS_RE = re.compile(r"^(\.\d+)")
TO_FLOAT_RE = re.compile(r"([+-]?(?=\d|\.\d)\d*(?:\.\d*)?(?:[Ee](?:[+-]?\d+))?)")


def convert_duration(value: ExifToolScalar) -> ExifToolScalar:
    seconds = numeric_scalar_or_none(value)
    if seconds is None:
        return value
    if seconds == 0:
        return "0 s"
    sign = ""
    if seconds < 0:
        sign = "-"
        seconds = -seconds
    if seconds < 30:
        return f"{sign}{seconds:.2f} s"
    rounded = seconds + 0.5
    hours = int(rounded / 3600)
    rounded -= hours * 3600
    minutes = int(rounded / 60)
    rounded -= minutes * 60
    if hours > 24:
        days = int(hours / 24)
        hours -= days * 24
        sign = f"{sign}{days} days "
    return f"{sign}{hours}:{minutes:02d}:{int(rounded):02d}"


def convert_time_span(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 1 <= len(values) <= 2:
        raise ExifToolCompatibilityError(
            f"ConvertTimeSpan expected 1 to 2 arguments, got {len(values)}."
        )
    seconds = numeric_scalar_or_none(values[0])
    if seconds is None or seconds == 0:
        return values[0]
    multiplier = numeric_scalar_or_none(values[1]) if len(values) == 2 else None
    if multiplier is not None:
        seconds *= multiplier
    if seconds < 60:
        return f"{seconds:g} seconds"
    if seconds < 3600:
        template = "%.0f" if multiplier is not None and multiplier >= 60 else "%.1f"
        suffix = "" if seconds == 60 and multiplier is not None else "s"
        return f"{template % (seconds / 60)} minute{suffix}"
    if seconds < 24 * 3600:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / (24 * 3600):.1f} days"


def to_float(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not values:
        raise ExifToolCompatibilityError("ToFloat expected at least 1 argument, got 0.")
    result: ExifToolScalar = None
    for value in values:
        result = scalar_to_float(value)
    return result


def scalar_to_float(value: ExifToolScalar) -> ExifToolScalar:
    if value is None:
        return None
    match = TO_FLOAT_RE.search(string_value(value))
    if match is None:
        return None
    numeric = float(match.group(1))
    if numeric.is_integer():
        return int(numeric)
    return numeric


def convert_bitrate(value: ExifToolScalar) -> ExifToolScalar:
    bitrate = numeric_scalar_or_none(value)
    if bitrate is None:
        return value
    units = ["bps", "kbps", "Mbps", "Gbps"]
    unit_index = 0
    while bitrate >= 1000 and unit_index < len(units) - 1:
        bitrate /= 1000
        unit_index += 1
    template = "%.3g" if bitrate < 100 else "%.0f"
    return f"{template % bitrate} {units[unit_index]}"


def convert_file_size(value: ExifToolScalar) -> ExifToolScalar:
    size = numeric_scalar_or_none(value)
    if size is None:
        return value
    if size < 2000:
        return f"{size:g} bytes"
    if size < 10000:
        return f"{size / 1000:.1f} kB"
    if size < 2_000_000:
        return f"{size / 1000:.0f} kB"
    if size < 10_000_000:
        return f"{size / 1_000_000:.1f} MB"
    if size < 2_000_000_000:
        return f"{size / 1_000_000:.0f} MB"
    if size < 10_000_000_000:
        return f"{size / 1_000_000_000:.1f} GB"
    return f"{size / 1_000_000_000:.0f} GB"


def convert_date_time(values: list[ExifToolScalar]) -> ExifToolScalar:
    if len(values) != 1:
        raise ExifToolCompatibilityError(f"ConvertDateTime expected 1 argument, got {len(values)}.")
    return values[0]


def time_zone_string(value: ExifToolScalar) -> ExifToolScalar:
    minutes = numeric_scalar_or_none(value)
    if minutes is None:
        return value
    sign = "+"
    if minutes < 0:
        sign = "-"
        minutes = -minutes
    rounded_minutes = int(minutes + 0.5)
    hours = int(rounded_minutes / 60)
    return f"{sign}{hours:02d}:{rounded_minutes - hours * 60:02d}"


def decode_bits(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 2 <= len(values) <= 3:
        raise ExifToolCompatibilityError(
            f"DecodeBits expected 2 to 3 arguments, got {len(values)}."
        )
    if values[1] is not None:
        raise ExifToolCompatibilityError(
            "DecodeBits lookup-table decoding requires a typed lookup adapter."
        )
    bit_width = int_value(values[2]) if len(values) == 3 and values[2] is not None else 32
    if bit_width <= 0:
        raise ExifToolCompatibilityError(f"DecodeBits bit width must be positive: {bit_width}.")
    decoded_bits: list[str] = []
    bit_offset = 0
    for token in string_value(values[0]).split():
        value = decode_bits_integer_token(token)
        for bit_index in range(bit_width):
            if value & (1 << bit_index):
                decoded_bits.append(str(bit_index + bit_offset))
        bit_offset += bit_width
    if not decoded_bits:
        return "(none)"
    return ",".join(decoded_bits)


def decode_bits_integer_token(token: str) -> int:
    try:
        return int(token, 0)
    except ValueError:
        return int_value(token)


def convert_unix_time(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 1 <= len(values) <= 3:
        raise ExifToolCompatibilityError(
            f"ConvertUnixTime expected 1 to 3 arguments, got {len(values)}."
        )
    timestamp = numeric_scalar_or_none(values[0])
    if timestamp is None:
        return values[0]
    if timestamp == 0:
        return "0000:00:00 00:00:00"
    to_local = len(values) >= 2 and perl_truthy(values[1])
    decimals = int_value(values[2]) if len(values) >= 3 and values[2] is not None else 0
    trim = decimals < 0
    if trim:
        decimals = -decimals
    integer_timestamp = int(timestamp)
    fraction = timestamp - integer_timestamp
    if fraction < 0:
        fraction += 1
        integer_timestamp -= 1
    fraction_text = f"{fraction:.{decimals}f}"
    if fraction_text[0] == "1":
        integer_timestamp += 1
    fraction_text = fraction_text[1:]
    if trim:
        fraction_text = fraction_text.rstrip("0").removesuffix(".")
    if to_local:
        date_parts = time.localtime(integer_timestamp)
        timezone = unix_timezone_text(date_parts)
    else:
        date_parts = time.gmtime(integer_timestamp)
        timezone = ""
    return (
        f"{date_parts.tm_year:04d}:{date_parts.tm_mon:02d}:{date_parts.tm_mday:02d} "
        f"{date_parts.tm_hour:02d}:{date_parts.tm_min:02d}:{date_parts.tm_sec:02d}"
        f"{fraction_text}{timezone}"
    )


def unix_timezone_text(date_parts: time.struct_time) -> str:
    offset = time.strftime("%z", date_parts)
    if len(offset) != 5:
        return ""
    return f"{offset[:3]}:{offset[3:]}"


def get_unix_time(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 1 <= len(values) <= 2:
        raise ExifToolCompatibilityError(
            f"GetUnixTime expected 1 to 2 arguments, got {len(values)}."
        )
    time_text = string_value(values[0])
    if time_text == "0000:00:00 00:00:00":
        return 0
    match = EXIF_DATETIME_RE.match(time_text)
    if match is None:
        return None
    is_local = len(values) >= 2 and perl_truthy(values[1])
    timezone_text = match.group(7)
    timezone_seconds = 0
    timezone_match = TIMEZONE_RE.search(timezone_text)
    if is_local:
        if timezone_match is not None:
            sign = timezone_match.group(1)
            if sign is not None:
                timezone_seconds = (
                    int(timezone_match.group(2)) * 60 + int(timezone_match.group(3))
                ) * (-60 if sign == "-" else 60)
            is_local = False
        elif len(values) >= 2 and string_value(values[1]) == "2":
            is_local = False
    try:
        timestamp = unix_timestamp(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6)),
            is_local,
        )
    except ValueError:
        return None
    result = timestamp - timezone_seconds
    fractional_seconds = FRACTIONAL_SECONDS_RE.match(timezone_text)
    if fractional_seconds is not None:
        result += float(fractional_seconds.group(1))
    if result.is_integer():
        return int(result)
    return result


def unix_timestamp(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    is_local: bool,
) -> float:
    date_tuple = (year, month, day, hour, minute, second, 0, 0, -1)
    if is_local:
        return time.mktime(date_tuple)
    return float(calendar.timegm(date_tuple))


def print_hex(value: ExifToolScalar) -> ExifToolScalar:
    return " ".join(f"{byte:02x}" for byte in byte_values(value))
