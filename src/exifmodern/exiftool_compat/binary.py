"""Binary payload helpers for ExifTool compatibility adapters."""

from __future__ import annotations

from exifmodern.services.binary import ieee754_float32


def binary_text_bytes(value: str) -> list[int]:
    return [ord(character) & 0xFF for character in value]


def uint16_big_endian(data: list[int], offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def uint16_little_endian(data: list[int], offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def uint32_big_endian(data: list[int], offset: int) -> int:
    return (
        (data[offset] << 24) | (data[offset + 1] << 16) | (data[offset + 2] << 8) | data[offset + 3]
    )


def uint32_little_endian(data: list[int], offset: int) -> int:
    return (
        data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16) | (data[offset + 3] << 24)
    )


def float32_little_endian(data: list[int], offset: int) -> float:
    return ieee754_float32(bytes(data[offset : offset + 4]), "little")


def float32_big_endian(data: list[int], offset: int) -> float:
    return ieee754_float32(bytes(data[offset : offset + 4]), "big")
