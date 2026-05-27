"""EXIF exact-helper compatibility adapters."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from exifmodern.exiftool_compat.core import scalar_to_float
from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolContextUpdate,
    ExifToolEffectResult,
    ExifToolScalar,
    ExifToolValue,
    byte_values,
    hash_reference_value,
    numeric_scalar_or_none,
    numeric_value,
    scalar_value,
    string_hash_field,
    string_value,
)

FRACTION_RE = re.compile(r"([-+]?\d+)/(\d+)")
EXIF_DATE_RE = re.compile(r"(\d{4})[^\d]*(\d{2})[^\d]*(\d{2})$")
EXIF_COMPACT_TIME_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})")
EXIF_TIMEZONE_RE = re.compile(r"([+-]\d{2})(\d{2})\s*$")
PARAMETER_NORMAL_RE = re.compile(r"\bn", re.IGNORECASE)
PARAMETER_SOFT_RE = re.compile(r"\b(s|l)", re.IGNORECASE)
PARAMETER_HARD_RE = re.compile(r"\bh", re.IGNORECASE)
RGGB_LOOKUP: tuple[tuple[int, int, int, int], ...] = (
    (0, 1, 2, 3),
    (0, 1, 3, 2),
    (0, 2, 3, 1),
    (1, 0, 3, 2),
    (1, 0, 2, 3),
    (2, 3, 0, 1),
    (0, 1, 1, 2),
    (1, 0, 0, 2),
    (0, 256, 256, 1),
)
CFA_COLORS: tuple[str, ...] = ("Red", "Green", "Blue", "Cyan", "Magenta", "Yellow", "White")
CFA_LOOKUP: dict[str, int] = {
    "red": 0,
    "green": 1,
    "blue": 2,
    "cyan": 3,
    "magenta": 4,
    "yellow": 5,
    "white": 6,
}
SCALE_FACTOR_DIAGONAL_35MM = math.sqrt(36 * 36 + 24 * 24)
SCALE_FACTOR_UNIT_MM: dict[str, float] = {
    "3": 10,
    "4": 1,
    "5": 0.001,
    "cm": 10,
    "mm": 1,
    "um": 0.001,
}


def convert_fraction(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value)
    match = FRACTION_RE.search(text)
    if match is None:
        return value
    numerator = int(match.group(1))
    denominator = int(match.group(2))
    if denominator != 0:
        return numerator / denominator
    if numerator != 0:
        return "inf"
    return "undef"


def exif_date(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value).removesuffix("\0")
    return EXIF_DATE_RE.sub(r"\1:\2:\3", text)


def exif_time(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value).replace(" ", ":").removesuffix("\0")
    text = EXIF_COMPACT_TIME_RE.sub(r"\1:\2:\3", text)
    return EXIF_TIMEZONE_RE.sub(r"\1:\2", text)


def convert_exif_text(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 2 <= len(values) <= 4:
        raise ExifToolCompatibilityError(
            f"ConvertExifText expected 2 to 4 arguments, got {len(values)}."
        )
    text = string_value(values[1])
    if len(text) < 8:
        return values[1]
    encoding_id = text[:8]
    payload = text[8:]
    if exif_ascii_header(encoding_id):
        return payload.split("\0", 1)[0].rstrip(" ")
    if encoding_id.startswith("UNICODE") and encoding_id[7] in {"\0", " "}:
        return decode_exif_text_payload(payload, "utf-16")
    if encoding_id.startswith("JIS") and encoding_id[3:] in {"\0\0\0\0\0", "     "}:
        return payload.rstrip(" ")
    return text.rstrip(" ")


def encode_exif_text(values: list[ExifToolScalar]) -> ExifToolScalar:
    if len(values) != 2:
        raise ExifToolCompatibilityError(f"EncodeExifText expected 2 arguments, got {len(values)}.")
    text = string_value(values[1])
    if exif_text_requires_unicode(text):
        raise ExifToolCompatibilityError(
            "EncodeExifText non-ASCII encoding requires typed EXIF byte-order context."
        )
    return f"ASCII\0\0\0{text}"


def convert_parameter(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value)
    number = numeric_scalar_or_none(value)
    if PARAMETER_NORMAL_RE.search(text) is not None or number == 0:
        return 0
    if PARAMETER_SOFT_RE.search(text) is not None or (number is not None and number < 0):
        return 1
    if PARAMETER_HARD_RE.search(text) is not None or number is not None:
        return 2
    return None


def calculate_lv(values: list[ExifToolScalar]) -> ExifToolScalar:
    if len(values) != 3:
        raise ExifToolCompatibilityError(f"CalculateLV expected 3 arguments, got {len(values)}.")
    parsed_values = [positive_numeric_prefix_or_none(value) for value in values]
    if any(value is None for value in parsed_values):
        return None
    aperture = parsed_values[0]
    shutter_speed = parsed_values[1]
    iso = parsed_values[2]
    if aperture is None or shutter_speed is None or iso is None:
        return None
    return math.log2(aperture * aperture * 100 / (shutter_speed * iso))


def red_blue_balance(values: list[ExifToolScalar]) -> ExifToolScalar:
    if len(values) < 2:
        raise ExifToolCompatibilityError(
            f"RedBlueBalance expected at least 2 arguments, got {len(values)}."
        )
    blue = int(numeric_value(values[0]))
    remaining = values[1:]
    for index, lookup in enumerate(RGGB_LOOKUP):
        if index >= len(remaining) or not remaining[index]:
            continue
        levels = [numeric_value(part) for part in string_value(remaining[index]).split()]
        if len(levels) < 2:
            continue
        green_index = lookup[1]
        if green_index < 4:
            if len(levels) < 3:
                continue
            green = (levels[green_index] + levels[lookup[2]]) / 2
            if green == 0:
                continue
        elif levels[lookup[blue * 3]] < 4:
            green = 1.0
        else:
            green = float(green_index)
        return levels[lookup[blue * 3]] / green
    if len(remaining) >= 2 and remaining[0] and remaining[1]:
        return numeric_value(remaining[0]) / numeric_value(remaining[1])
    return None


def identify_raw_file_compression(values: list[ExifToolValue]) -> ExifToolEffectResult:
    if len(values) != 1:
        return ExifToolEffectResult(value=None)
    value = scalar_value(values[0], "EXIF raw compression value")
    return ExifToolEffectResult(
        value=value,
        context_updates=(
            ExifToolContextUpdate(namespace="$$self", path=("Compression",), value=value),
        ),
    )


def print_cfa_pattern(value: ExifToolScalar) -> ExifToolScalar:
    values = [int(numeric_value(part)) for part in string_value(value).split()]
    if len(values) < 2:
        return "<truncated data>"
    columns = values[0]
    rows = values[1]
    if columns == 0 or rows == 0:
        return "<zero pattern size>"
    end = 2 + columns * rows
    if end > len(values):
        return "<invalid pattern size>"
    rows_text: list[str] = []
    for row_index in range(rows):
        row_values: list[str] = []
        for column_index in range(columns):
            color_index = values[2 + row_index * columns + column_index]
            try:
                row_values.append(CFA_COLORS[color_index])
            except IndexError:
                row_values.append("Unknown")
        rows_text.append(",".join(row_values))
    return "[" + "][".join(rows_text) + "]"


def get_cfa_pattern(value: ExifToolScalar) -> ExifToolScalar:
    rows = re.split(r"\]\s*\[", string_value(value))
    if not rows:
        return None
    first_row = rows[0].split(",")
    if not first_row:
        return None
    column_count = len(first_row)
    values: list[int] = [len(rows), column_count]
    for row in rows:
        columns = row.split(",")
        if len(columns) != column_count:
            return None
        for column in columns:
            color = column.translate(str.maketrans("", "", " []")).lower()
            color_value = CFA_LOOKUP.get(color)
            if color_value is None:
                return None
            values.append(color_value)
    return " ".join(str(item) for item in values)


def decode_cfa_pattern(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 2:
        return None
    exiftool_context = hash_reference_value(values[0], "DecodeCFAPattern ExifTool context")
    payload = string_value(scalar_value(values[1], "DecodeCFAPattern payload"))
    if re.fullmatch(r"[0-6]+", payload) is not None:
        payload = "".join(chr(int(character)) for character in payload)
    if len(payload) < 4:
        return payload
    byte_order = string_hash_field(exiftool_context, "ByteOrder") or "II"
    values_from_payload = cfa_pattern_values(payload, byte_order)
    end = 2 + values_from_payload[0] * values_from_payload[1]
    if end > len(values_from_payload):
        swapped_columns = int.from_bytes(
            int(values_from_payload[0]).to_bytes(2, "little"),
            "big",
        )
        swapped_rows = int.from_bytes(
            int(values_from_payload[1]).to_bytes(2, "little"),
            "big",
        )
        if len(values_from_payload) >= 2 + swapped_columns * swapped_rows:
            values_from_payload[0] = swapped_columns
            values_from_payload[1] = swapped_rows
    return " ".join(str(item) for item in values_from_payload)


def cfa_pattern_values(payload: str, byte_order: str) -> list[int]:
    data = byte_values(payload)
    endian: Literal["little", "big"] = "little" if byte_order == "II" else "big"
    columns = int.from_bytes(bytes(data[0:2]), endian)
    rows = int.from_bytes(bytes(data[2:4]), endian)
    return [columns, rows, *data[4:]]


def calc_scale_factor_35efl(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) < 3:
        return None
    hash_reference_value(values[0], "CalcScaleFactor35efl ExifTool context")
    arguments = [scalar_value(value, "CalcScaleFactor35efl argument") for value in values[1:]]
    return scale_factor_35efl(arguments)


def scale_factor_35efl(arguments: list[ExifToolScalar]) -> float | None:
    resolution_unit = argument_or_none(arguments, 7)
    sensor_xy = string_value(argument_or_none(arguments, 4))
    numeric_arguments = [to_float_or_none(argument) for argument in arguments]
    focal_length = numeric_argument_or_none(numeric_arguments, 0)
    focal_length_35mm = numeric_argument_or_none(numeric_arguments, 1)
    if focal_length is not None and focal_length_35mm is not None and focal_length != 0:
        return focal_length_35mm / focal_length
    digital_zoom = numeric_argument_or_none(numeric_arguments, 2) or 1
    diagonal = numeric_argument_or_none(numeric_arguments, 3)
    sensor_x = numeric_argument_or_none(numeric_arguments, 4)
    if diagonal is None or diagonal == 0:
        diagonal = sensor_diagonal_or_none(sensor_x, sensor_xy)
    if diagonal is None:
        diagonal = focal_plane_size_diagonal_or_none(arguments, numeric_arguments, resolution_unit)
    if diagonal is None or diagonal == 0:
        return None
    return SCALE_FACTOR_DIAGONAL_35MM * digital_zoom / diagonal


def argument_or_none(arguments: list[ExifToolScalar], index: int) -> ExifToolScalar:
    if index >= len(arguments):
        return None
    return arguments[index]


def numeric_argument_or_none(arguments: list[float | None], index: int) -> float | None:
    if index >= len(arguments):
        return None
    return arguments[index]


def to_float_or_none(value: ExifToolScalar) -> float | None:
    converted = scalar_to_float(value)
    if isinstance(converted, bool) or converted is None:
        return None
    return float(converted)


def sensor_diagonal_or_none(sensor_x: float | None, sensor_xy: str) -> float | None:
    match = re.search(r" (\d+(?:\.?\d*)?)$", sensor_xy)
    if sensor_x is None or match is None:
        return None
    sensor_y = float(match.group(1))
    return math.sqrt(sensor_x * sensor_x + sensor_y * sensor_y)


def focal_plane_size_diagonal_or_none(
    arguments: list[ExifToolScalar],
    numeric_arguments: list[float | None],
    resolution_unit: ExifToolScalar,
) -> float | None:
    x_size = numeric_argument_or_none(numeric_arguments, 5)
    y_size = numeric_argument_or_none(numeric_arguments, 6)
    diagonal = focal_plane_dimension_diagonal_or_none(x_size, y_size)
    if diagonal is not None:
        return diagonal
    units = scale_factor_units(argument_or_none(arguments, 7), resolution_unit)
    x_resolution = numeric_argument_or_none(numeric_arguments, 8)
    y_resolution = numeric_argument_or_none(numeric_arguments, 9) or x_resolution
    if x_resolution is None or y_resolution is None or x_resolution == 0 or y_resolution == 0:
        return None
    image_dimensions = first_reasonable_image_dimensions(numeric_arguments[10:])
    if image_dimensions is None:
        return None
    width = image_dimensions.width * units / x_resolution
    height = image_dimensions.height * units / y_resolution
    diagonal = math.sqrt(width * width + height * height)
    if not 1 < diagonal < 100:
        return None
    return diagonal


def focal_plane_dimension_diagonal_or_none(
    x_size: float | None,
    y_size: float | None,
) -> float | None:
    if x_size is None or y_size is None or x_size == 0 or y_size == 0:
        return None
    aspect_ratio = x_size / y_size
    if abs(aspect_ratio - 1.3333) < 0.1 or abs(aspect_ratio - 1.5) < 0.1:
        return math.sqrt(x_size * x_size + y_size * y_size)
    return None


@dataclass(frozen=True)
class ImageDimensions:
    width: float
    height: float


def first_reasonable_image_dimensions(values: list[float | None]) -> ImageDimensions | None:
    index = 0
    while index + 1 < len(values):
        width = values[index]
        height = values[index + 1]
        index += 2
        if width is None or height is None or width == 0 or height == 0:
            continue
        aspect_ratio = width / height
        if 0.5 < aspect_ratio < 2:
            return ImageDimensions(width=width, height=height)
    return None


def scale_factor_units(unit_argument: ExifToolScalar, fallback_unit: ExifToolScalar) -> float:
    unit = string_value(unit_argument or fallback_unit)
    return SCALE_FACTOR_UNIT_MM.get(unit, 25.4)


def positive_numeric_prefix_or_none(value: ExifToolScalar) -> float | None:
    match = re.search(r"([+-]?(?=\d|\.\d)\d*(?:\.\d*)?(?:[Ee](?:[+-]?\d+))?)", string_value(value))
    if match is None:
        return None
    number = float(match.group(1))
    if number <= 0:
        return None
    return number


def exif_text_requires_unicode(text: str) -> bool:
    return any(ord(character) > 0x7F for character in text)


def exif_ascii_header(encoding_id: str) -> bool:
    if encoding_id.startswith("ASCII"):
        return all(character in {"\0", " "} for character in encoding_id[5:])
    return all(character in {"\0", " "} for character in encoding_id)


def decode_exif_text_payload(payload: str, encoding: str) -> str:
    data = bytes(byte_values(payload))
    try:
        return data.decode(encoding).rstrip(" ")
    except UnicodeError:
        return payload.rstrip(" ")


def print_exposure_time(value: ExifToolScalar) -> ExifToolScalar:
    seconds = numeric_scalar_or_none(value)
    if seconds is None:
        return value
    if 0 < seconds < 0.25001:
        return f"1/{int(0.5 + 1 / seconds)}"
    rendered = f"{seconds:.1f}"
    if rendered.endswith(".0"):
        return rendered[:-2]
    return rendered


def print_fnumber(value: ExifToolScalar) -> ExifToolScalar:
    number = numeric_scalar_or_none(value)
    if number is None or number <= 0:
        return value
    if number < 1:
        return f"{number:.2f}"
    return f"{number:.1f}"


def print_fraction(value: ExifToolScalar) -> ExifToolScalar:
    number = numeric_scalar_or_none(value)
    if number is None:
        return value
    adjusted = number * 1.00001
    if adjusted == 0:
        return "0"
    if int(adjusted) / adjusted > 0.999:
        return f"{int(adjusted):+d}"
    if int(adjusted * 2) / (adjusted * 2) > 0.999:
        return f"{int(adjusted * 2):+d}/2"
    if int(adjusted * 3) / (adjusted * 3) > 0.999:
        return f"{int(adjusted * 3):+d}/3"
    return f"{adjusted:+.3g}"
