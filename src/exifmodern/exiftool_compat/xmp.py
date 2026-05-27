"""XMP exact-helper compatibility adapters."""

from __future__ import annotations

import re
from base64 import b64decode, b64encode

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    byte_values,
    perl_truthy,
    string_value,
)

XMP_STANDARD_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2})(:\d{2})?\s*(\S*)$")
XMP_PARTIAL_DATE_RE = re.compile(r"^(\d{4})(-\d{2}){0,2}")
FORMAT_XMP_EXIF_DATE_RE = re.compile(
    r"(\d{4}):(\d{2}):(\d{2}) (\d{2}:\d{2}(?::\d{2}(?:\.\d*)?)?)(.*)"
)
FORMAT_XMP_STANDARD_DATE_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}(?::\d{2}(?:\.\d*)?)?)(.*)"
)
FORMAT_XMP_PARTIAL_DATE_RE = re.compile(r"^\s*\d{4}(:\d{2}){0,2}\s*$")
FORMAT_XMP_TIME_RE = re.compile(r"^\s*(\d{2}:\d{2}(?::\d{2}(?:\.\d*)?)?)(.*)\s*$")
FORMAT_XMP_TIMEZONE_RE = re.compile(r"^(Z|[+-]\d{2}:\d{2})$")
BASE64_INVALID_RE = re.compile(r"[^A-Za-z0-9+/= \t\n\r\f]")
BASE64_WHITESPACE_RE = re.compile(r"[ \t\n\r\f]")


def convert_xmp_date(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 1 <= len(values) <= 2:
        raise ExifToolCompatibilityError(
            f"Image::ExifTool::XMP::ConvertXMPDate expected 1 to 2 arguments, got {len(values)}."
        )
    value = values[0]
    text = string_value(value)
    standard_date = XMP_STANDARD_DATE_RE.match(text)
    if standard_date is not None:
        seconds = standard_date.group(5) or ""
        timezone = standard_date.group(6)
        return (
            f"{standard_date.group(1)}:{standard_date.group(2)}:{standard_date.group(3)} "
            f"{standard_date.group(4)}{seconds}{timezone}"
        )
    unsure = len(values) >= 2 and perl_truthy(values[1])
    if not unsure and XMP_PARTIAL_DATE_RE.match(text):
        return text.replace("-", ":")
    return value


def format_xmp_date(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value)
    timezone = ""
    exif_date = FORMAT_XMP_EXIF_DATE_RE.search(text)
    xmp_date = FORMAT_XMP_STANDARD_DATE_RE.search(text)
    if exif_date is not None:
        text, timezone = formatted_xmp_date_from_match(exif_date)
    elif xmp_date is not None:
        text, timezone = formatted_xmp_date_from_match(xmp_date)
    elif FORMAT_XMP_PARTIAL_DATE_RE.match(text):
        return text.replace(":", "-")
    else:
        xmp_time = FORMAT_XMP_TIME_RE.match(text)
        if xmp_time is None:
            return None
        text = xmp_time.group(1)
        timezone = xmp_time.group(2)
    if timezone:
        if FORMAT_XMP_TIMEZONE_RE.match(timezone) is None:
            return None
        text += timezone
    return text


def formatted_xmp_date_from_match(match: re.Match[str]) -> tuple[str, str]:
    return (
        f"{match.group(1)}-{match.group(2)}-{match.group(3)}T{match.group(4)}",
        match.group(5),
    )


def decode_base64(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value)
    invalid = BASE64_INVALID_RE.search(text)
    if invalid is not None:
        text = text[: invalid.start()]
    compact = BASE64_WHITESPACE_RE.sub("", text)
    padding = len(compact) % 4
    if padding:
        compact = compact + "=" * (4 - padding)
    return b64decode(compact, validate=False).decode("latin-1")


def encode_base64(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 1 <= len(values) <= 2:
        raise ExifToolCompatibilityError(
            f"Image::ExifTool::XMP::EncodeBase64 expected 1 to 2 arguments, got {len(values)}."
        )
    encoded = b64encode(bytes(byte_values(values[0]))).decode("ascii")
    if len(values) >= 2 and perl_truthy(values[1]):
        return encoded
    chunks = [encoded[index : index + 60] for index in range(0, len(encoded), 60)]
    return "\n".join(chunks) + "\n"
