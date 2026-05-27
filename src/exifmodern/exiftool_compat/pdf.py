"""PDF helper adapters with exact ExifTool-compatible contracts."""

from __future__ import annotations

import re

from exifmodern.exiftool_compat.types import ExifToolScalar, string_value

PDF_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(.*)")
PDF_TIMEZONE_RE = re.compile(r"^\s*([-+])\s*(\d+)[': ]+(\d*)")


def convert_pdf_date(value: ExifToolScalar) -> ExifToolScalar:
    date = string_value(value)
    date = date.removeprefix("D:")
    default_date = "00000101000000"
    if len(date) < len(default_date):
        date += default_date[len(date) :]
    match = PDF_DATE_RE.match(date)
    if match is None:
        return date
    converted = (
        f"{match.group(1)}:{match.group(2)}:{match.group(3)} "
        f"{match.group(4)}:{match.group(5)}:{match.group(6)}"
    )
    timezone = match.group(7)
    if not timezone:
        return converted
    if timezone.strip().lower().startswith("z"):
        return f"{converted}Z"
    timezone_match = PDF_TIMEZONE_RE.match(timezone)
    if timezone_match is None:
        return converted
    minutes = timezone_match.group(3) or "00"
    return f"{converted}{timezone_match.group(1)}{timezone_match.group(2)}:{minutes}"
