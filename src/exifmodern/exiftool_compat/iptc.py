"""IPTC exact-helper compatibility adapters."""

from __future__ import annotations

import re
import time

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    byte_values,
    int_value,
    string_value,
)

IPTC_TIME_RE = re.compile(
    r"(.*?)\b(\d{1,2})(:?)(\d{2})(:?)(\d{2})(\S*)\s*$",
    re.DOTALL,
)
IPTC_DATE_INPUT_RE = re.compile(r"^.*?(\d{4})[-:/.]?(\d{2})[-:/.]?(\d{2}).*", re.DOTALL)
IPTC_EXPLICIT_TIMEZONE_RE = re.compile(r"([+-]\d{1,2}):?(\d{2})")
IPTC_DATE_RE = re.compile(r"^(\d{4}):(\d{2}):(\d{2})\s*$")
IPTC_PICTURE_NUMBER_DIGIT_RE = re.compile(r"[^0-9]")
IPTC_PICTURE_NUMBER_DESCRIPTION_RE = re.compile(r"\(.*?\)")

IPTC_PICTURE_NUMBER_MANUFACTURERS: dict[int, str] = {
    1: "Associated Press, USA",
    2: "Eastman Kodak Co, USA",
    3: "Hasselblad Electronic Imaging, Sweden",
    4: "Tecnavia SA, Switzerland",
    5: "Nikon Corporation, Japan",
    6: "Coatsworth Communications Inc, Canada",
    7: "Agence France Presse, France",
    8: "T/One Inc, USA",
    9: "Associated Newspapers, UK",
    10: "Reuters London",
    11: "Sandia Imaging Systems Inc, USA",
    12: "Visualize, Spain",
}


def inverse_date_or_time(values: list[ExifToolScalar]) -> ExifToolScalar:
    if len(values) != 2:
        raise ExifToolCompatibilityError(
            f"InverseDateOrTime expected 2 arguments, got {len(values)}."
        )
    value = string_value(values[1])
    if value.lower() == "now":
        return exiftool_time_now()
    return values[1]


def iptc_date(value: ExifToolScalar) -> ExifToolScalar:
    match = IPTC_DATE_INPUT_RE.match(string_value(value))
    if match is None:
        return None
    return f"{match.group(1)}{match.group(2)}{match.group(3)}"


def iptc_time(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value)
    match = IPTC_TIME_RE.search(text)
    if match is None:
        return None
    if not match.group(3) and match.group(5):
        return None
    rendered = f"{int(match.group(2)):02d}{int(match.group(4)):02d}{int(match.group(6)):02d}"
    timezone = iptc_timezone(match.group(1), match.group(7), rendered)
    if timezone is None:
        return None
    return rendered + timezone


def convert_picture_number(value: ExifToolScalar) -> ExifToolScalar:
    data = byte_values(value)
    if data == [0] * 16:
        return "Unknown"
    if len(data) < 16:
        return "<format error>"
    manufacturer_code = uint16_be(data, 0)
    equipment_number = uint32_be(data, 2)
    date_text = string_value_from_bytes(data[6:14])
    picture_number = uint16_be(data, 14)
    manufacturer = IPTC_PICTURE_NUMBER_MANUFACTURERS.get(manufacturer_code)
    manufacturer_text = f" ({manufacturer})" if manufacturer is not None else ""
    formatted_date = f"{date_text[0:4]}:{date_text[4:6]}:{date_text[6:8]}"
    return (
        f"{manufacturer_code}{manufacturer_text}, equip {equipment_number}, "
        f"{formatted_date}, no. {picture_number}"
    )


def inv_convert_picture_number(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value)
    text = IPTC_PICTURE_NUMBER_DESCRIPTION_RE.sub("", text)
    text = text.replace(":", "")
    numeric_text = IPTC_PICTURE_NUMBER_DIGIT_RE.sub(" ", text)
    values = [int_value(part) for part in numeric_text.split()]
    if len(values) >= 4:
        return (
            uint16_be_text(values[0])
            + uint32_be_text(values[1])
            + fixed_ascii_text(str(values[2]), 8)
            + uint16_be_text(values[3])
        )
    if "unknown" in text.lower():
        return "\0" * 16
    return None


def uint16_be(values: list[int], offset: int) -> int:
    return (values[offset] << 8) | values[offset + 1]


def uint32_be(values: list[int], offset: int) -> int:
    return (
        (values[offset] << 24)
        | (values[offset + 1] << 16)
        | (values[offset + 2] << 8)
        | values[offset + 3]
    )


def uint16_be_text(value: int) -> str:
    return chr((value >> 8) & 0xFF) + chr(value & 0xFF)


def uint32_be_text(value: int) -> str:
    return "".join(chr((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def fixed_ascii_text(value: str, length: int) -> str:
    return value[:length].ljust(length)


def string_value_from_bytes(values: list[int]) -> str:
    return "".join(chr(value) for value in values)


def iptc_timezone(date_text: str, timezone_text: str, rendered_time: str) -> str | None:
    explicit_timezone = IPTC_EXPLICIT_TIMEZONE_RE.search(timezone_text)
    if explicit_timezone is not None:
        hours = int(explicit_timezone.group(1))
        minutes = int(explicit_timezone.group(2))
        return f"{hours:+03d}{minutes:02d}"
    if "Z" in timezone_text.upper():
        return "+0000"
    timestamp = iptc_local_timestamp(date_text, rendered_time)
    date_parts = time.localtime(timestamp)
    timezone = time.strftime("%z", date_parts)
    return timezone if len(timezone) == 5 else None


def iptc_local_timestamp(date_text: str, rendered_time: str) -> float:
    date_match = IPTC_DATE_RE.match(date_text)
    if date_match is None:
        return time.time()
    return time.mktime(
        (
            int(date_match.group(1)),
            int(date_match.group(2)),
            int(date_match.group(3)),
            int(rendered_time[0:2]),
            int(rendered_time[2:4]),
            int(rendered_time[4:6]),
            0,
            0,
            -1,
        )
    )


def exiftool_time_now() -> str:
    timestamp = time.time()
    date_parts = time.localtime(timestamp)
    timezone = time.strftime("%z", date_parts)
    timezone_text = f"{timezone[:3]}:{timezone[3:]}" if len(timezone) == 5 else ""
    return (
        f"{date_parts.tm_year:04d}:{date_parts.tm_mon:02d}:{date_parts.tm_mday:02d} "
        f"{date_parts.tm_hour:02d}:{date_parts.tm_min:02d}:{date_parts.tm_sec:02d}"
        f"{timezone_text}"
    )
