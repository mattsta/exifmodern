"""TIFF construction helpers compatible with small ExifTool helper surfaces."""

from __future__ import annotations

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    byte_values,
    int_value,
    perl_truthy,
    string_value,
)


def make_tiff_header(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 4 <= len(values) <= 6:
        raise ExifToolCompatibilityError(
            f"MakeTiffHeader expected 4 to 6 arguments, got {len(values)}."
        )
    width = int_value(values[0])
    height = int_value(values[1])
    colors = int_value(values[2])
    bits = int_value(values[3])
    resolution = int_value(values[4]) if len(values) >= 5 and values[4] is not None else 72
    color_map = normalized_color_map(values[5], bits) if len(values) >= 6 else b""
    color_map_offset = 12 if color_map else 0
    header = (
        b"II*\0\x08\0\0\0\x0e\0"
        + b"\xfe\x00\x04\0\x01\0\0\0\x00\0\0\0"
        + b"\x00\x01\x04\0\x01\0\0\0"
        + set32u(width)
        + b"\x01\x01\x04\0\x01\0\0\0"
        + set32u(height)
        + b"\x02\x01\x03\0"
        + set32u(colors)
        + set32u(bits if colors == 1 else 0xB6 + color_map_offset)
        + b"\x03\x01\x03\0\x01\0\0\0\x01\0\0\0"
        + b"\x06\x01\x03\0\x01\0\0\0"
        + set32u(3 if color_map else 1 if colors == 1 else 2)
        + b"\x11\x01\x04\0\x01\0\0\0"
        + set32u(0xCC + color_map_offset + len(color_map))
        + b"\x15\x01\x03\0\x01\0\0\0"
        + set32u(colors)
        + b"\x16\x01\x04\0\x01\0\0\0"
        + set32u(height)
        + b"\x17\x01\x04\0\x01\0\0\0"
        + set32u(width * height * colors * int((bits + 7) / 8))
        + b"\x1a\x01\x05\0\x01\0\0\0"
        + set32u(0xBC + color_map_offset)
        + b"\x1b\x01\x05\0\x01\0\0\0"
        + set32u(0xC4 + color_map_offset)
        + b"\x1c\x01\x03\0\x01\0\0\0\x01\0\0\0"
        + b"\x28\x01\x03\0\x01\0\0\0\x02\0\0\0"
        + (color_map_ifd_entry(bits) if color_map else b"")
    )
    header += (
        b"\0\0\0\0"
        + (set16u(bits) * 3)
        + set32u(resolution)
        + b"\x01\0\0\0"
        + set32u(resolution)
        + b"\x01\0\0\0"
        + color_map
    )
    return header.decode("latin-1")


def normalized_color_map(value: ExifToolScalar, bits: int) -> bytes:
    if not perl_truthy(value):
        return b""
    color_map = bytes(byte_values(string_value(value)))
    single_byte_length = 3 * (2**bits)
    double_byte_length = 6 * (2**bits)
    if len(color_map) == single_byte_length:
        expanded = bytearray()
        for item in color_map:
            expanded.extend(set16u(item | (item << 8)))
        return bytes(expanded)
    if len(color_map) != double_byte_length:
        return b""
    return color_map


def color_map_ifd_entry(bits: int) -> bytes:
    return b"\x40\x01\x03\0" + set32u(3 * (2**bits)) + b"\xd8\0\0\0"


def set16u(value: int) -> bytes:
    return value.to_bytes(2, "little", signed=False)


def set32u(value: int) -> bytes:
    return value.to_bytes(4, "little", signed=False)
