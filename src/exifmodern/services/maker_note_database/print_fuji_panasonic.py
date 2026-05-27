"""FujiFilm and Panasonic maker-note PrintConv domain adapters."""

from __future__ import annotations

import re

from exifmodern.services.maker_note_database.print_helpers import (
    convert_indexed_values,
    mapped_integer_value_with_unknown,
)
from exifmodern.services.maker_note_database.print_scalar import parse_float
from exifmodern.services.maker_note_tables import MakerNoteTagLocation


def is_fuji_main_print_domain_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::FujiFilm"
        and location.table.name == "Main"
        and location.entry.name
        in {"InternalSerialNumber", "ImageStabilization", "FaceElementTypes"}
    )


def fuji_main_print_domain_conversion(tag_name: str, raw_value: str) -> str | None:
    if tag_name == "InternalSerialNumber":
        return fuji_internal_serial_number(raw_value)
    if tag_name == "ImageStabilization":
        return convert_indexed_values(
            raw_value.split(),
            (fuji_image_stabilization_type, fuji_image_stabilization_mode),
        )
    if tag_name == "FaceElementTypes":
        return convert_indexed_values(
            raw_value.split(),
            (fuji_face_element_type,),
            repeat_last=True,
        )
    return None


def fuji_internal_serial_number(raw_value: str) -> str:
    match = re.fullmatch(
        r"(.*?\s*)([0-9a-fA-F]*)(\d{2})(\d{2})(\d{2})(.{12})\s*\x00*",
        raw_value,
        flags=re.DOTALL,
    )
    if match and 1 <= int(match.group(4)) <= 12 and 1 <= int(match.group(5)) <= 31:
        year = int(match.group(3))
        full_year = year + (2000 if year < 70 else 1900)
        serial = pack_hex_string(match.group(2))
        return (
            f"{match.group(1)}{serial} "
            f"{full_year}:{match.group(4)}:{match.group(5)} {match.group(6)}"
        )
    return re.sub(
        r"\b(592D(?:3[0-9])+)",
        lambda match: pack_hex_string(match.group(1)) + " ",
        raw_value,
        count=1,
    )


def pack_hex_string(hex_value: str) -> str:
    if len(hex_value) % 2:
        hex_value += "0"
    try:
        return bytes.fromhex(hex_value).decode("latin1")
    except ValueError:
        return hex_value


def fuji_image_stabilization_type(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0: "None",
            1: "Optical",
            2: "Sensor-shift",
            3: "OIS Lens",
            258: "IBIS/OIS + DIS",
            512: "Digital",
        },
    )


def fuji_image_stabilization_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0: "Off",
            1: "On (mode 1, continuous)",
            2: "On (mode 2, shooting only)",
        },
    )


def fuji_face_element_type(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            1: "Face",
            2: "Left Eye",
            3: "Right Eye",
            7: "Body",
            8: "Head",
            9: "Both Eyes",
            11: "Bike",
            12: "Body of Car",
            13: "Front of Car",
            14: "Animal Body",
            15: "Animal Head",
            16: "Animal Face",
            17: "Animal Left Eye",
            18: "Animal Right Eye",
            19: "Bird Body",
            20: "Bird Head",
            21: "Bird Left Eye",
            22: "Bird Right Eye",
            23: "Aircraft Body",
            25: "Aircraft Cockpit",
            26: "Train Front",
            27: "Train Cockpit",
            28: "Animal Head (28)",
            29: "Animal Body (29)",
        },
    )


def is_panasonic_print_domain_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Panasonic"
        and location.table.name == "Main"
        and location.entry.name in {"InternalSerialNumber", "TimeSincePowerOn"}
        and location.entry.print_conv_kind in {"scalar", "code"}
    )


def panasonic_print_domain_conversion(tag_name: str, raw_value: str) -> str | None:
    if tag_name == "InternalSerialNumber":
        return panasonic_internal_serial_number(raw_value)
    if tag_name == "TimeSincePowerOn":
        return panasonic_time_since_power_on(raw_value)
    return None


def panasonic_internal_serial_number(raw_value: str) -> str:
    match = re.match(r"([A-Z][0-9A-Z]{2})(\d{2})(\d{2})(\d{2})(\d{4})", raw_value)
    if match is None:
        return raw_value
    prefix, year, month, day, number = match.groups()
    year_value = int(year) + (2000 if int(year) < 70 else 1900)
    return f"({prefix}) {year_value}:{month}:{day} no. {number}"


def panasonic_time_since_power_on(raw_value: str) -> str | None:
    value = parse_float(raw_value)
    if value is None:
        return None
    prefix = ""
    if value >= 24 * 3600:
        days = int(value / (24 * 3600))
        prefix = f"{days} days "
        value -= days * 24 * 3600
    hours = int(value / 3600)
    value -= hours * 3600
    minutes = int(value / 60)
    value -= minutes * 60
    seconds = f"{value:05.2f}"
    if float(seconds) >= 60:
        seconds = "00.00"
        minutes += 1
        if minutes >= 60:
            minutes -= 60
            hours += 1
    return f"{prefix}{hours:02d}:{minutes:02d}:{seconds}"
