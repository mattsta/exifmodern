"""GPS exact-helper compatibility adapters."""

from __future__ import annotations

import re

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    numeric_value,
    perl_truthy,
    string_value,
)

GPS_NUMERIC_RE = re.compile(r"([+-]?(?=\d|\.\d)\d*(?:\.\d*)?(?:[Ee][+-]\d+)?)")
GPS_COMBINED_COORDINATES_RE = re.compile(
    r"^(.*(?:N(?:orth)?|S(?:outh)?)),\s*(.*(?:E(?:ast)?|W(?:est)?))$",
    re.IGNORECASE,
)
GPS_NEGATIVE_REFERENCE_RE = re.compile(r"[^A-Z](S(outh)?|W(est)?)\s*$", re.IGNORECASE)
GPS_TIMESTAMP_FRACTION_RE = re.compile(r":(\d{2}\.\d+)$")


def convert_time_stamp(value: ExifToolScalar) -> ExifToolScalar:
    parts = string_value(value).split()
    hours = gps_time_part(parts, 0)
    minutes = gps_time_part(parts, 1)
    seconds = gps_time_part(parts, 2)
    total_seconds = ((hours * 60) + minutes) * 60 + seconds
    rendered_hours = int(total_seconds / 3600)
    total_seconds -= rendered_hours * 3600
    rendered_minutes = int(total_seconds / 60)
    total_seconds -= rendered_minutes * 60
    rendered_seconds = f"{total_seconds:012.9f}"
    if float(rendered_seconds) >= 60:
        rendered_seconds = "00"
        rendered_minutes += 1
        if rendered_minutes >= 60:
            rendered_minutes -= 60
            rendered_hours += 1
    else:
        rendered_seconds = rendered_seconds.rstrip("0").removesuffix(".")
    return f"{rendered_hours:02d}:{rendered_minutes:02d}:{rendered_seconds}"


def gps_time_part(parts: list[str], index: int) -> float:
    if index >= len(parts):
        return 0.0
    try:
        return float(parts[index])
    except ValueError:
        return 0.0


def gps_to_degrees(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 1 <= len(values) <= 3:
        raise ExifToolCompatibilityError(
            f"Image::ExifTool::GPS::ToDegrees expected 1 to 3 arguments, got {len(values)}."
        )
    value_text = string_value(values[0])
    if re.search(r"\b(inf|undef)\b", value_text):
        return ""
    coordinate = string_value(values[2]) if len(values) >= 3 and values[2] is not None else ""
    if coordinate in {"lat", "lon"}:
        combined = GPS_COMBINED_COORDINATES_RE.match(value_text)
        if combined is not None:
            value_text = combined.group(1) if coordinate == "lat" else combined.group(2)
    numeric_parts = [float(match) for match in GPS_NUMERIC_RE.findall(value_text)]
    if not numeric_parts:
        return ""
    degrees = numeric_parts[0]
    minutes = numeric_parts[1] if len(numeric_parts) >= 2 else 0.0
    seconds = numeric_parts[2] if len(numeric_parts) >= 3 else 0.0
    result = degrees + (minutes + seconds / 60) / 60
    do_sign = len(values) >= 2 and perl_truthy(values[1])
    if do_sign:
        if GPS_NEGATIVE_REFERENCE_RE.search(value_text):
            result = -result
    elif result < 0:
        result = -result
    return result


def geolocate_print_conv_inv(values: list[ExifToolScalar]) -> ExifToolScalar:
    if len(values) != 1:
        return None
    converted: list[str] = []
    latitude = True
    for argument in re.split(r"\s*,\s*", string_value(values[0])):
        if re.match(r"^[-+]?\d", argument) is None:
            converted.append(argument)
            continue
        if len(re.findall(r"\.\d+", argument)) > 1:
            converted.append(argument)
            continue
        coordinate = "lat" if latitude else "lon"
        converted.append(string_value(gps_to_degrees([argument, 1, coordinate])))
        latitude = not latitude
    return ",".join(converted)


def print_time_stamp(value: ExifToolScalar) -> ExifToolScalar:
    text = string_value(value)
    fraction = GPS_TIMESTAMP_FRACTION_RE.search(text)
    if fraction is None:
        return value
    rounded_seconds = int(float(fraction.group(1)) * 1_000_000 + 0.5) / 1_000_000
    rendered_seconds = perl_float_text(rounded_seconds)
    if rounded_seconds < 10:
        rendered_seconds = f"0{rendered_seconds}"
    return f"{text[: fraction.start()]}:{rendered_seconds}"


def perl_float_text(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def gps_to_dms(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 2 <= len(values) <= 4:
        raise ExifToolCompatibilityError(
            f"Image::ExifTool::GPS::ToDMS expected 2 to 4 arguments, got {len(values)}."
        )
    value = values[1]
    value_text = string_value(value)
    do_print_conv = values[2] if len(values) >= 3 else None
    do_print_conv_text = string_value(do_print_conv) if do_print_conv is not None else ""
    reference = string_value(values[3]) if len(values) >= 4 and values[3] is not None else ""
    if len(value_text) == 0:
        if do_print_conv_text == "1":
            return value
        return None
    degrees_value = numeric_value(value)
    sign = ""
    minus = ""
    negative_unformatted = False
    if reference:
        if degrees_value < 0:
            degrees_value = -degrees_value
            reference = negative_gps_reference(reference)
            sign = "-"
            minus = "-"
        else:
            sign = "+"
        if do_print_conv_text != "2":
            reference = f" {reference}"
    else:
        if do_print_conv_text == "3":
            negative_unformatted = degrees_value < 0
            do_print_conv_text = ""
        degrees_value = abs(degrees_value)
    if do_print_conv_text:
        if do_print_conv_text == "1":
            template = gps_default_print_template(reference, sign, minus)
            coordinate_count = 3
        else:
            template = f"%d,%.8f{reference}"
            coordinate_count = 2
    else:
        template = ""
        coordinate_count = 3
    coordinates = gps_dms_coordinates(degrees_value, coordinate_count, template)
    if do_print_conv_text:
        rendered = template % tuple(coordinates)
        if do_print_conv_text == "2":
            rendered = trim_xmp_gps_dms(rendered, reference)
        return rendered
    if negative_unformatted:
        coordinates = [-coordinate for coordinate in coordinates]
    return " ".join(str(coordinate) for coordinate in coordinates) + reference


def negative_gps_reference(reference: str) -> str:
    if reference == "N":
        return "S"
    if reference == "E":
        return "W"
    return reference


def gps_default_print_template(reference: str, sign: str, minus: str) -> str:
    template = "%d deg %d' %.2f\"" + reference
    if "%+" in template:
        return template.replace("%+", f"{sign}%")
    if "%-" in template:
        return template.replace("%-", f"{minus}%")
    return template


def gps_dms_coordinates(
    degrees_value: float,
    coordinate_count: int,
    template: str,
) -> list[float | int]:
    coordinates: list[float | int] = [degrees_value]
    if coordinate_count > 1:
        degree_component = int(degrees_value)
        minute_value = (degrees_value - degree_component) * 60
        coordinates[0] = degree_component
        coordinates.append(minute_value)
        if coordinate_count > 2:
            minute_component = int(minute_value)
            second_value = (degrees_value - degree_component - minute_component / 60) * 3600
            coordinates[1] = minute_component
            coordinates.append(normalize_gps_roundoff(second_value))
        rendered_last = gps_render_last_coordinate(coordinates[-1], template)
        if rendered_last >= 60:
            coordinates[-1] = rendered_last - 60
            coordinates[-2] = coordinates[-2] + 1
            if coordinate_count > 2 and coordinates[-2] >= 60:
                coordinates[-2] = coordinates[-2] - 60
                coordinates[-3] = coordinates[-3] + 1
    return coordinates


def normalize_gps_roundoff(value: float) -> float:
    if abs(value) < 1e-10:
        return 0.0
    return value


def gps_render_last_coordinate(value: float | int, template: str) -> float:
    if not template:
        return float(value)
    last_directive = "%d" if "%.8f" not in template and "%.2f" not in template else "%.8f"
    if "%.2f" in template:
        last_directive = "%.2f"
    return float(last_directive % value)


def trim_xmp_gps_dms(rendered: str, reference: str) -> str:
    if not reference:
        return re.sub(r"(\d)0+$", r"\1", rendered)
    escaped_reference = re.escape(reference)
    return re.sub(rf"(\d)0+{escaped_reference}$", rf"\1{reference}", rendered)
