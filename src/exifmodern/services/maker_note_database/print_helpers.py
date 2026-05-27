"""Shared helpers for source-backed maker-note PrintConv domain adapters."""

from __future__ import annotations

from collections.abc import Callable

from exifmodern.services.maker_note_database.print_scalar import parse_float, parse_int

type IndexedPrintConverter = Callable[[str], str | None]


def convert_indexed_values(
    values: list[str],
    converters: tuple[IndexedPrintConverter, ...],
    *,
    repeat_last: bool = False,
) -> str | None:
    converted: list[str] = []
    for index, value in enumerate(values):
        if index >= len(converters):
            if repeat_last:
                converter = converters[-1]
            else:
                converted.append(value)
                continue
        else:
            converter = converters[index]
        printed = converter(value)
        if printed is None:
            return None
        converted.append(printed)
    return " ".join(converted)


def mapped_integer_value(raw_value: str, mapping: dict[int, str]) -> str | None:
    value = parse_int(raw_value)
    if value is None:
        return None
    return mapping.get(value)


def mapped_integer_value_with_unknown(raw_value: str, mapping: dict[int, str]) -> str | None:
    value = parse_int(raw_value)
    if value is None:
        return None
    return mapping.get(value, f"Unknown ({raw_value})")


def mapped_float_key_value(raw_value: str, mapping: dict[str, str]) -> str | None:
    value = parse_float(raw_value)
    if value is None:
        return None
    return mapping.get(format_perl_float(value), f"Unknown ({raw_value})")


def mapped_string_value_with_unknown(raw_value: str, mapping: dict[str, str]) -> str:
    return mapping.get(raw_value, f"Unknown ({raw_value})")


def format_perl_float(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)
