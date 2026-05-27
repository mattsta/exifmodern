"""Classic TIFF routing helpers used by Nikon NEF mutation planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type TiffByteOrder = Literal["little", "big"]

TIFF_IFD_ENTRY_SIZE = 12
TIFF_VALUE_FORMAT_SIZES = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    6: 1,
    7: 1,
    8: 2,
    9: 4,
    10: 8,
    11: 4,
    12: 8,
}


@dataclass(frozen=True)
class NikonNefIfdEntry:
    ifd_name: str
    tag_id: int
    format_id: int
    count: int
    value_field_offset: int
    value_data_offset: int
    values: tuple[int, ...]


def parse_tiff_header(data: bytes) -> tuple[TiffByteOrder, int, int] | None:
    if len(data) < 8:
        return None
    marker = data[:2]
    if marker == b"II":
        byte_order: TiffByteOrder = "little"
    elif marker == b"MM":
        byte_order = "big"
    else:
        return None
    return byte_order, read_uint(data, 2, byte_order, 2), read_uint(data, 4, byte_order, 4)


def read_ifd_entry_count(
    data: bytes,
    ifd_offset: int | None,
    byte_order: TiffByteOrder,
) -> int | None:
    if ifd_offset is None or ifd_offset < 0 or ifd_offset + 2 > len(data):
        return None
    return read_uint(data, ifd_offset, byte_order, 2)


def find_ifd_long_value(
    data: bytes,
    ifd_offset: int | None,
    entry_count: int | None,
    byte_order: TiffByteOrder,
    tag_id: int,
) -> int | None:
    value_offset = find_ifd_value_field(data, ifd_offset, entry_count, byte_order, tag_id)
    if value_offset is None:
        return None
    return read_uint(data, value_offset, byte_order, 4)


def find_ifd_value_data_offset(
    data: bytes,
    ifd_offset: int | None,
    entry_count: int | None,
    byte_order: TiffByteOrder,
    tag_id: int,
) -> int | None:
    return find_ifd_long_value(data, ifd_offset, entry_count, byte_order, tag_id)


def find_ifd_value_field(
    data: bytes,
    ifd_offset: int | None,
    entry_count: int | None,
    byte_order: TiffByteOrder,
    tag_id: int,
) -> int | None:
    if ifd_offset is None or entry_count is None:
        return None
    entries_start = ifd_offset + 2
    for index in range(entry_count):
        entry_offset = entries_start + index * TIFF_IFD_ENTRY_SIZE
        if entry_offset + TIFF_IFD_ENTRY_SIZE > len(data):
            return None
        current_tag_id = read_uint(data, entry_offset, byte_order, 2)
        if current_tag_id == tag_id:
            return entry_offset + 8
    return None


def collect_nef_ifd_entries(
    data: bytes,
    byte_order: TiffByteOrder,
    ifd_offset: int,
    visited: set[int],
    ifd_name: str,
    *,
    sub_ifd_pointer_tag: int,
) -> tuple[tuple[str, tuple[NikonNefIfdEntry, ...]], ...]:
    if ifd_offset in visited:
        return ()
    visited.add(ifd_offset)

    entries = read_ifd_entries(data, ifd_offset, byte_order, ifd_name)
    if entries is None:
        return ()

    collected: list[tuple[str, tuple[NikonNefIfdEntry, ...]]] = [(ifd_name, entries)]
    for index, sub_ifd_offset in enumerate(values_for_tag(entries, sub_ifd_pointer_tag)):
        collected.extend(
            collect_nef_ifd_entries(
                data,
                byte_order,
                sub_ifd_offset,
                visited,
                f"{ifd_name}:SubIFD{index}",
                sub_ifd_pointer_tag=sub_ifd_pointer_tag,
            )
        )

    next_ifd_offset = next_ifd_offset_from_entries(data, ifd_offset, len(entries), byte_order)
    if next_ifd_offset:
        collected.extend(
            collect_nef_ifd_entries(
                data,
                byte_order,
                next_ifd_offset,
                visited,
                next_sibling_ifd_name(ifd_name),
                sub_ifd_pointer_tag=sub_ifd_pointer_tag,
            )
        )
    return tuple(collected)


def read_ifd_entries(
    data: bytes,
    ifd_offset: int,
    byte_order: TiffByteOrder,
    ifd_name: str,
) -> tuple[NikonNefIfdEntry, ...] | None:
    entry_count = read_ifd_entry_count(data, ifd_offset, byte_order)
    if entry_count is None:
        return None

    entries: list[NikonNefIfdEntry] = []
    entries_start = ifd_offset + 2
    for index in range(entry_count):
        entry_offset = entries_start + index * TIFF_IFD_ENTRY_SIZE
        if entry_offset + TIFF_IFD_ENTRY_SIZE > len(data):
            return None
        tag_id = read_uint(data, entry_offset, byte_order, 2)
        format_id = read_uint(data, entry_offset + 2, byte_order, 2)
        count = read_uint(data, entry_offset + 4, byte_order, 4)
        value_field_offset = entry_offset + 8
        values = read_tiff_integer_values(data, value_field_offset, format_id, count, byte_order)
        value_data_offset = tiff_value_data_offset(
            data,
            value_field_offset,
            format_id,
            count,
            byte_order,
        )
        if values is None or value_data_offset is None:
            continue
        entries.append(
            NikonNefIfdEntry(
                ifd_name=ifd_name,
                tag_id=tag_id,
                format_id=format_id,
                count=count,
                value_field_offset=value_field_offset,
                value_data_offset=value_data_offset,
                values=values,
            )
        )
    return tuple(entries)


def next_ifd_offset_from_entries(
    data: bytes,
    ifd_offset: int,
    entry_count: int,
    byte_order: TiffByteOrder,
) -> int | None:
    next_offset_position = ifd_offset + 2 + entry_count * TIFF_IFD_ENTRY_SIZE
    if next_offset_position + 4 > len(data):
        return None
    return read_uint(data, next_offset_position, byte_order, 4)


def next_sibling_ifd_name(ifd_name: str) -> str:
    if ifd_name.startswith("IFD") and ifd_name[3:].isdigit():
        return f"IFD{int(ifd_name[3:]) + 1}"
    return f"{ifd_name}:NextIFD"


def first_entry_for_tag(
    entries: tuple[NikonNefIfdEntry, ...],
    tag_id: int,
) -> NikonNefIfdEntry | None:
    return next((entry for entry in entries if entry.tag_id == tag_id), None)


def values_for_tag(
    entries: tuple[NikonNefIfdEntry, ...],
    tag_id: int,
) -> tuple[int, ...]:
    entry = first_entry_for_tag(entries, tag_id)
    return entry.values if entry is not None else ()


def read_tiff_integer_values(
    data: bytes,
    value_field_offset: int,
    format_id: int,
    count: int,
    byte_order: TiffByteOrder,
) -> tuple[int, ...] | None:
    if format_id not in (3, 4):
        return None
    value_data_offset = tiff_value_data_offset(
        data,
        value_field_offset,
        format_id,
        count,
        byte_order,
    )
    if value_data_offset is None:
        return None
    width: Literal[2, 4] = 2 if format_id == 3 else 4
    if value_data_offset + count * width > len(data):
        return None
    return tuple(
        read_uint(data, value_data_offset + index * width, byte_order, width)
        for index in range(count)
    )


def tiff_value_data_offset(
    data: bytes,
    value_field_offset: int,
    format_id: int,
    count: int,
    byte_order: TiffByteOrder,
) -> int | None:
    format_size = TIFF_VALUE_FORMAT_SIZES.get(format_id)
    if format_size is None:
        return None
    byte_length = format_size * count
    if byte_length <= 4:
        return value_field_offset
    value_data_offset = read_uint(data, value_field_offset, byte_order, 4)
    if value_data_offset < 0 or value_data_offset + byte_length > len(data):
        return None
    return value_data_offset


def read_ascii_prefix(data: bytes, offset: int | None, size: int) -> str | None:
    if offset is None or offset < 0 or offset + size > len(data):
        return None
    return data[offset : offset + size].decode("ascii", errors="replace").rstrip("\0")


def read_uint(data: bytes, offset: int, byte_order: TiffByteOrder, size: int) -> int:
    return int.from_bytes(data[offset : offset + size], byte_order)
