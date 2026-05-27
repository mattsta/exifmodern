"""Samsung exact-helper compatibility adapters."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolContextUpdate,
    ExifToolEffectResult,
    ExifToolScalar,
    ExifToolValue,
    hash_reference_value,
    int_array_hash_field,
    int_value,
    scalar_value,
    string_hash_field,
    string_value,
)

FORMAT_MIN_MAX: dict[str, tuple[int, int]] = {
    "int16u": (0, 65_535),
    "int32u": (0, 4_294_967_295),
    "int16s": (-32_768, 32_767),
    "int32s": (-2_147_483_648, 2_147_483_647),
}


@dataclass(frozen=True)
class SamsungSalt:
    sign: int
    offset: int


def crypt(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) < 4:
        raise ExifToolCompatibilityError(
            f"Samsung Crypt expected at least 4 arguments, got {len(values)}."
        )
    exiftool_context = hash_reference_value(values[0], "Samsung Crypt ExifTool context")
    text_value = scalar_value(values[1], "Samsung Crypt value")
    tag_info = hash_reference_value(values[2], "Samsung Crypt tagInfo")
    encryption_key = int_array_hash_field(exiftool_context, "EncryptionKey")
    if not encryption_key:
        return None
    format_name = string_hash_field(tag_info, "Writable") or string_hash_field(
        tag_info,
        "Format",
    )
    if format_name not in FORMAT_MIN_MAX:
        return None
    minimum, maximum = FORMAT_MIN_MAX[format_name]
    encrypted_values = [int(part) for part in string_value(text_value).split()]
    salts = [salt_value(value) for value in values[3:]]
    skip_length_entry = len(salts) > 1
    next_salt_index = 0
    segment_start = 1 if skip_length_entry else 0
    index = segment_start
    while index < len(encrypted_values):
        salt = salts[next_salt_index]
        next_salt_index += 1
        segment_end = len(encrypted_values)
        if next_salt_index < len(salts):
            segment_end = segment_start + encrypted_values[0]
        apply_samsung_salt(
            encrypted_values,
            encryption_key,
            salt,
            segment_start,
            segment_end,
            minimum,
            maximum,
        )
        index = segment_end
        segment_start = segment_end
    return " ".join(str(value) for value in encrypted_values)


def encryption_key_update(values: list[ExifToolValue]) -> ExifToolEffectResult:
    if len(values) != 1:
        return ExifToolEffectResult(value=None)
    value = scalar_value(values[0], "Samsung encryption-key payload")
    key = tuple(int_value(part) for part in string_value(value).split())
    return ExifToolEffectResult(
        value=value,
        context_updates=(
            ExifToolContextUpdate(namespace="$$self", path=("EncryptionKey",), value=key),
        ),
    )


def apply_samsung_salt(
    values: list[int],
    encryption_key: list[int],
    salt: SamsungSalt,
    start: int,
    end: int,
    minimum: int,
    maximum: int,
) -> None:
    value_span = maximum - minimum + 1
    for index in range(start, min(end, len(values))):
        key_index = (salt.offset + index - start) % len(encryption_key)
        values[index] += salt.sign * encryption_key[key_index]
        if salt.sign > 0 and values[index] > maximum:
            values[index] -= value_span
        elif salt.sign < 0 and values[index] < minimum:
            values[index] += value_span


def salt_value(value: ExifToolValue) -> SamsungSalt:
    scalar = scalar_value(value, "Samsung Crypt salt")
    text = string_value(scalar)
    sign = -1 if text.startswith("-") else 1
    return SamsungSalt(sign=sign, offset=abs(int_value(scalar)))
