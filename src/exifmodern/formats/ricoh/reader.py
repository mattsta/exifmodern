"""Ricoh RMETA APP5 reader for proven custom-field metadata."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.json_types import JsonObject

RICOH_RMETA_PREFIX = b"RMETA\x00"

type RicohPrintMap = dict[int, str]
type RicohPrintMaps = dict[str, RicohPrintMap]
type RicohTagNames = dict[str, str]

RICOH_RMETA_TAG_NAMES: RicohTagNames = {
    "Sign type": "SignType",
    "Location": "Location",
    "Lit": "Lit",
    "Condition": "Condition",
    "Azimuth": "Azimuth",
}

RICOH_RMETA_PRINT_CONVERSIONS: RicohPrintMaps = {
    "SignType": {
        1: "Directional",
        2: "Warning",
        3: "Information",
    },
    "Location": {
        1: "Verge",
        2: "Gantry",
        3: "Central reservation",
        4: "Roundabout",
    },
    "Lit": {
        1: "Yes",
        2: "No",
    },
    "Condition": {
        1: "Good",
        2: "Fair",
        3: "Poor",
        4: "Damaged",
    },
    "Azimuth": {
        1: "N",
        2: "NNE",
        3: "NE",
        4: "ENE",
        5: "E",
        6: "ESE",
        7: "SE",
        8: "SSE",
        9: "S",
        10: "SSW",
        11: "SW",
        12: "WSW",
        13: "W",
        14: "WNW",
        15: "NW",
        16: "NNW",
    },
}


@dataclass(frozen=True)
class RicohRmetaSections:
    names: list[str]
    values: list[str]
    numbers: list[int]


def parse_ricoh_rmeta_tags(payload: bytes) -> JsonObject:
    if not payload.startswith(RICOH_RMETA_PREFIX):
        raise ValueError("No Ricoh RMETA APP5 payload found")
    data = payload[len(RICOH_RMETA_PREFIX) :]
    if len(data) < 20:
        raise ValueError("Truncated Ricoh RMETA data")
    byte_order = data[0:2]
    if byte_order not in {b"II", b"MM"}:
        raise ValueError("Bad Ricoh RMETA byte order")
    rmeta_number = ricoh_rmeta_int16(data, 4, byte_order)
    if rmeta_number != 0:
        return {}
    directory_offset = ricoh_rmeta_int16(data, 8, byte_order)
    if directory_offset + 10 > len(data):
        raise ValueError("Truncated Ricoh RMETA directory")
    entry_count = ricoh_rmeta_int16(data, directory_offset, byte_order)
    if entry_count > 100:
        raise ValueError("Bad Ricoh RMETA entry count")
    sections = ricoh_rmeta_sections(data, directory_offset + 10, entry_count, byte_order)
    return ricoh_rmeta_values(sections, entry_count)


def ricoh_rmeta_sections(
    data: bytes,
    offset: int,
    entry_count: int,
    byte_order: bytes,
) -> RicohRmetaSections:
    names: list[str] = []
    values: list[str] = []
    numbers: list[int] = []
    position = offset
    while position <= len(data) - 4:
        section_type = ricoh_rmeta_int16(data, position, byte_order)
        section_size = ricoh_rmeta_int16(data, position + 2, byte_order)
        if section_size == 0:
            break
        if section_size < 2:
            raise ValueError("Corrupted Ricoh RMETA section")
        position += 4
        data_size = section_size - 2
        section_end = position + data_size
        if section_end > len(data):
            raise ValueError("Corrupted Ricoh RMETA data")
        section_data = data[position:section_end]
        if section_type == 1:
            names = ricoh_rmeta_strings(section_data, entry_count)
        elif section_type in {2, 18}:
            values = ricoh_rmeta_strings(section_data, entry_count)
        elif section_type == 3:
            numbers = ricoh_rmeta_numbers(section_data, entry_count, byte_order)
        position = section_end
    return RicohRmetaSections(names=names, values=values, numbers=numbers)


def ricoh_rmeta_values(sections: RicohRmetaSections, entry_count: int) -> JsonObject:
    values: JsonObject = {}
    for index in range(entry_count):
        raw_name = ricoh_rmeta_item(sections.names, index)
        tag_name = RICOH_RMETA_TAG_NAMES.get(raw_name)
        if tag_name is None:
            continue
        string_value = ricoh_rmeta_item(sections.values, index)
        number_value = ricoh_rmeta_number_item(sections.numbers, index)
        if string_value:
            values[tag_name] = string_value
        elif number_value is not None:
            values[tag_name] = ricoh_rmeta_print_value(tag_name, number_value)
    return values


def ricoh_rmeta_int16(data: bytes, offset: int, byte_order: bytes) -> int:
    return int.from_bytes(
        data[offset : offset + 2],
        "little" if byte_order == b"II" else "big",
    )


def ricoh_rmeta_strings(data: bytes, entry_count: int) -> list[str]:
    return [
        item.decode("utf-8", errors="replace")
        for item in data.split(b"\x00", entry_count)[:entry_count]
    ]


def ricoh_rmeta_numbers(data: bytes, entry_count: int, byte_order: bytes) -> list[int]:
    numbers: list[int] = []
    for index in range(entry_count):
        offset = index * 2
        if offset + 2 > len(data):
            break
        numbers.append(ricoh_rmeta_int16(data, offset, byte_order))
    return numbers


def ricoh_rmeta_item(items: list[str], index: int) -> str:
    return items[index] if index < len(items) else ""


def ricoh_rmeta_number_item(items: list[int], index: int) -> int | None:
    return items[index] if index < len(items) else None


def ricoh_rmeta_print_value(tag_name: str, value: int) -> str | int:
    return RICOH_RMETA_PRINT_CONVERSIONS.get(tag_name, {}).get(value, value)
