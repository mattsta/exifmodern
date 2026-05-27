"""AFCP trailer rewrite helpers for JPEG byte-range deletion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type AfcpByteOrder = Literal["big", "little"]

AFCP_SIGNATURE_BIG_ENDIAN = b"AXS!"
AFCP_SIGNATURE_LITTLE_ENDIAN = b"AXS*"


@dataclass(frozen=True)
class AfcpOffsetAdjustment:
    header_offset: int
    entry_count: int
    adjusted_offsets: int


def adjust_afcp_offsets_after_delete(
    data: bytes,
    deleted_start: int,
    deleted_length: int,
) -> bytes:
    if deleted_length <= 0:
        return data
    updated = bytearray(data)
    for header_offset in afcp_header_offsets(data):
        adjust_afcp_directory_offsets(updated, header_offset, deleted_start, deleted_length)
    return bytes(updated)


def adjust_afcp_directory_offsets(
    data: bytearray,
    header_offset: int,
    deleted_start: int,
    deleted_length: int,
) -> AfcpOffsetAdjustment | None:
    if header_offset + 12 > len(data):
        return None
    signature = bytes(data[header_offset : header_offset + 4])
    byte_order = afcp_byte_order(signature)
    if byte_order is None:
        return None
    entry_count = int.from_bytes(data[header_offset + 6 : header_offset + 8], byte_order)
    adjusted_offsets = 0
    directory_offset = header_offset + 12
    for index in range(entry_count):
        entry_offset = directory_offset + index * 12
        if entry_offset + 12 > len(data):
            return None
        value_offset_field = entry_offset + 8
        value_offset = int.from_bytes(data[value_offset_field : value_offset_field + 4], byte_order)
        if value_offset < deleted_start + deleted_length:
            continue
        adjusted_value_offset = value_offset - deleted_length
        data[value_offset_field : value_offset_field + 4] = adjusted_value_offset.to_bytes(
            4,
            byte_order,
        )
        adjusted_offsets += 1
    return AfcpOffsetAdjustment(
        header_offset=header_offset,
        entry_count=entry_count,
        adjusted_offsets=adjusted_offsets,
    )


def afcp_header_offsets(data: bytes) -> tuple[int, ...]:
    offsets: list[int] = []
    for signature in (AFCP_SIGNATURE_BIG_ENDIAN, AFCP_SIGNATURE_LITTLE_ENDIAN):
        position = data.find(signature)
        while position >= 0:
            offsets.append(position)
            position = data.find(signature, position + 1)
    return tuple(sorted(offsets))


def afcp_byte_order(signature: bytes) -> AfcpByteOrder | None:
    if signature == AFCP_SIGNATURE_BIG_ENDIAN:
        return "big"
    if signature == AFCP_SIGNATURE_LITTLE_ENDIAN:
        return "little"
    return None
