"""Byte-order and string helpers for source-backed RIFF readers."""

from __future__ import annotations

import struct


def uint16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def uint32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def uint64(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little")


def int32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=True)


def uint16_be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def uint32_be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def double_le(data: bytes, offset: int) -> float:
    value: float
    (value,) = struct.unpack("<d", data[offset : offset + 8])
    return value


def float_le(data: bytes, offset: int) -> float:
    value: float
    (value,) = struct.unpack("<f", data[offset : offset + 4])
    return value


def signed_int8(value: int) -> int:
    return value - 0x100 if value >= 0x80 else value


def ascii_string(data: bytes) -> str:
    return data.decode("latin-1").rstrip("\x00")


def fixed_string(data: bytes, offset: int, length: int) -> str:
    return data[offset : offset + length].decode("latin-1").rstrip("\x00")


def broadcast_umid(data: bytes) -> str:
    value = data.hex().upper()
    return value[:-64] if value.endswith("0" * 64) else value
