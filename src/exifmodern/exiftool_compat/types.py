"""Shared scalar types and coercion helpers for ExifTool compatibility adapters."""

from __future__ import annotations

import math
from dataclasses import dataclass

type ExifToolScalar = str | int | float | bool | None
type ExifToolArrayReference = tuple[ExifToolValue, ...]


@dataclass(frozen=True)
class ExifToolScalarReference:
    value: ExifToolScalar


@dataclass(frozen=True)
class ExifToolFoundTag:
    name: str
    value: ExifToolScalar


@dataclass(frozen=True)
class ExifToolContextUpdate:
    namespace: str
    path: tuple[str, ...]
    value: ExifToolValue


@dataclass(frozen=True)
class ExifToolEffectResult:
    value: ExifToolScalar
    context_updates: tuple[ExifToolContextUpdate, ...] = ()
    found_tags: tuple[ExifToolFoundTag, ...] = ()


@dataclass(frozen=True)
class ExifToolHashEntry:
    key: str
    value: ExifToolValue


@dataclass(frozen=True)
class ExifToolHashReference:
    entries: tuple[ExifToolHashEntry, ...]


type ExifToolValue = (
    ExifToolScalar | ExifToolArrayReference | ExifToolScalarReference | ExifToolHashReference
)


class ExifToolCompatibilityError(ValueError):
    """Raised when an exact-name ExifTool helper receives invalid VM inputs."""


def scalar_value(value: ExifToolValue, context: str) -> ExifToolScalar:
    if isinstance(value, (tuple, ExifToolScalarReference, ExifToolHashReference)):
        raise ExifToolCompatibilityError(f"{context} must be scalar.")
    return value


def scalar_reference_value(value: ExifToolValue, context: str) -> ExifToolScalarReference:
    if isinstance(value, ExifToolScalarReference):
        return value
    raise ExifToolCompatibilityError(f"{context} must be a scalar reference.")


def hash_reference_value(value: ExifToolValue, context: str) -> ExifToolHashReference:
    if isinstance(value, ExifToolHashReference):
        return value
    raise ExifToolCompatibilityError(f"{context} must be a hash reference.")


def hash_field(value: ExifToolHashReference, key: str) -> ExifToolValue | None:
    for entry in value.entries:
        if entry.key == key:
            return entry.value
    return None


def scalar_hash_field(value: ExifToolHashReference, key: str) -> ExifToolScalar | None:
    field = hash_field(value, key)
    if field is None:
        return None
    return scalar_value(field, f"{key} field")


def string_hash_field(value: ExifToolHashReference, key: str) -> str | None:
    field = scalar_hash_field(value, key)
    if field is None:
        return None
    return string_value(field)


def int_array_hash_field(value: ExifToolHashReference, key: str) -> list[int]:
    field = hash_field(value, key)
    if not isinstance(field, tuple):
        return []
    return [int_value(scalar_value(item, f"{key} array item")) for item in field]


def numeric_value(value: ExifToolScalar) -> float:
    if isinstance(value, bool) or value is None:
        raise ExifToolCompatibilityError(f"ExifTool helper value is not numeric: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except ValueError as error:
        raise ExifToolCompatibilityError(
            f"ExifTool helper string value is not numeric: {value}"
        ) from error


def numeric_scalar_or_none(value: ExifToolScalar) -> float | None:
    try:
        return numeric_value(value)
    except ExifToolCompatibilityError:
        return None


def int_value(value: ExifToolScalar) -> int:
    return int(numeric_value(value))


def string_value(value: ExifToolScalar) -> str:
    if value is None:
        return ""
    return str(value)


def perl_numeric_text(value: float) -> str:
    if math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value)


def byte_values(value: ExifToolScalar) -> list[int]:
    return [ord(character) & 0xFF for character in string_value(value)]


def perl_truthy(value: ExifToolScalar) -> bool:
    if value is None:
        return False
    if value is False:
        return False
    if value == 0:
        return False
    if value == "":
        return False
    return value != "0"
