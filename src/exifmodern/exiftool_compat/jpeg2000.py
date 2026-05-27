"""JPEG 2000/JPEG XL exact-helper compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import (
    ExifToolContextUpdate,
    ExifToolEffectResult,
    ExifToolFoundTag,
    ExifToolValue,
    hash_reference_value,
    perl_truthy,
    scalar_hash_field,
    scalar_reference_value,
    string_value,
)

JXL_DIMENSION_BITS: tuple[int, ...] = (9, 13, 18, 30)
JXL_RATIO_DIMENSIONS: tuple[tuple[int, int], ...] = (
    (1, 1),
    (12, 10),
    (4, 3),
    (3, 2),
    (16, 9),
    (5, 4),
    (2, 1),
)


def process_jxl_codestream(values: list[ExifToolValue]) -> ExifToolEffectResult:
    if len(values) != 2:
        return ExifToolEffectResult(value=0)
    exiftool_context = hash_reference_value(values[0], "JPEG XL codestream ExifTool context")
    already_processed = scalar_hash_field(exiftool_context, "ProcessedJXLCodestream")
    if perl_truthy(already_processed):
        return ExifToolEffectResult(value=0)
    data_reference = scalar_reference_value(values[1], "JPEG XL codestream data")
    data = string_value(data_reference.value)
    if not jxl_codestream_header_is_valid(data):
        return ExifToolEffectResult(value=0)
    bitstream = jxl_dimension_bitstream(data)
    small_dimensions = consume_jxl_bits(bitstream, 1) != 0
    if small_dimensions:
        height = (consume_jxl_bits(bitstream, 5) + 1) * 8
    else:
        height = (
            consume_jxl_bits(
                bitstream,
                JXL_DIMENSION_BITS[consume_jxl_bits(bitstream, 2)],
            )
            + 1
        )
    ratio = consume_jxl_bits(bitstream, 3)
    if ratio == 0:
        if small_dimensions:
            width = (consume_jxl_bits(bitstream, 5) + 1) * 8
        else:
            width = (
                consume_jxl_bits(
                    bitstream,
                    JXL_DIMENSION_BITS[consume_jxl_bits(bitstream, 2)],
                )
                + 1
            )
    else:
        numerator, denominator = JXL_RATIO_DIMENSIONS[ratio - 1]
        width = int(height * numerator / denominator)
    return ExifToolEffectResult(
        value=1,
        context_updates=(
            ExifToolContextUpdate(
                namespace="$$self",
                path=("ProcessedJXLCodestream",),
                value=1,
            ),
        ),
        found_tags=(
            ExifToolFoundTag(name="ImageWidth", value=width),
            ExifToolFoundTag(name="ImageHeight", value=height),
        ),
    )


def jxl_codestream_header_is_valid(data: str) -> bool:
    return data.startswith("\xff\x0a") or data.startswith("\0\0\0\0\xff\x0a")


def jxl_dimension_bitstream(data: str) -> list[int]:
    if len(data) > 64:
        bounded_data = data[:64]
    elif len(data) < 18:
        bounded_data = data + ("\0" * (18 - len(data)))
    else:
        bounded_data = data
    bounded_data = bounded_data.removeprefix("\0\0\0\0")
    payload = bounded_data[2:14]
    if len(payload) < 12:
        payload += "\0" * (12 - len(payload))
    return [ord(character) & 0xFF for character in payload]


def consume_jxl_bits(values: list[int], bit_count: int) -> int:
    result = 0
    bit = 1
    remaining = bit_count
    while remaining:
        index = 0
        while index < len(values):
            bit_is_set = values[index] & 1
            values[index] >>= 1
            if index:
                if bit_is_set:
                    values[index - 1] |= 0x80
            else:
                if bit_is_set:
                    result |= bit
                bit <<= 1
            index += 1
        remaining -= 1
    return result
