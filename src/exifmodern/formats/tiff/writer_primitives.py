"""TIFF IFD encoding primitives for future safe write transactions."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_BYTE,
    TIFF_TYPE_RATIONAL,
    Endian,
    TiffFieldType,
)
from exifmodern.write_plan import (
    AsciiWriteValue,
    ByteWriteValue,
    ExifGpsWritePlan,
    GpsDeleteWriteValue,
    RationalArrayWriteValue,
)

type RawTiffWriteValue = bytes


@dataclass(frozen=True)
class TiffIfdWriteEntry:
    tag_id: int
    field_type: TiffFieldType
    count: int
    raw_value: RawTiffWriteValue


def gps_ifd_entries_from_write_plan(plan: ExifGpsWritePlan) -> tuple[TiffIfdWriteEntry, ...]:
    entries: list[TiffIfdWriteEntry] = []
    for step in plan.steps:
        tag_id = int(step.tag_id, 16)
        if isinstance(step.value, AsciiWriteValue):
            entries.append(
                TiffIfdWriteEntry(
                    tag_id=tag_id,
                    field_type=TIFF_TYPE_ASCII,
                    count=step.count,
                    raw_value=ascii_raw_value(step.value),
                )
            )
        elif isinstance(step.value, ByteWriteValue):
            entries.append(
                TiffIfdWriteEntry(
                    tag_id=tag_id,
                    field_type=TIFF_TYPE_BYTE,
                    count=step.count,
                    raw_value=bytes(step.value.values),
                )
            )
        elif isinstance(step.value, RationalArrayWriteValue):
            entries.append(
                TiffIfdWriteEntry(
                    tag_id=tag_id,
                    field_type=TIFF_TYPE_RATIONAL,
                    count=step.count,
                    raw_value=rational_array_raw_value(step.value, "little"),
                )
            )
        elif isinstance(step.value, GpsDeleteWriteValue):
            continue
    return tuple(entries)


def encode_gps_ifd_from_write_plan(plan: ExifGpsWritePlan, endian: Endian) -> bytes:
    entries = gps_ifd_entries_from_write_plan(plan)
    return encode_ifd(entries, endian)


def encode_ifd(entries: tuple[TiffIfdWriteEntry, ...], endian: Endian) -> bytes:
    sorted_entries = tuple(sorted(entries, key=lambda entry: entry.tag_id))
    external_start = 2 + len(sorted_entries) * 12 + 4
    encoded_entries: list[bytes] = []
    external_values: list[bytes] = []
    external_offset = external_start
    for entry in sorted_entries:
        raw_value = endian_adjusted_raw_value(entry, endian)
        if len(raw_value) <= 4:
            value_offset = int.from_bytes(raw_value.ljust(4, b"\x00"), endian)
        else:
            value_offset = external_offset
            external_values.append(raw_value)
            external_offset += len(raw_value)
        encoded_entries.append(
            encode_ifd_entry(entry.tag_id, entry.field_type, entry.count, value_offset, endian)
        )
    return (
        len(sorted_entries).to_bytes(2, endian)
        + b"".join(encoded_entries)
        + (0).to_bytes(4, endian)
        + b"".join(external_values)
    )


def endian_adjusted_raw_value(entry: TiffIfdWriteEntry, endian: Endian) -> bytes:
    if entry.field_type != TIFF_TYPE_RATIONAL:
        return entry.raw_value
    return entry.raw_value if endian == "little" else swap_rational_array_bytes(entry.raw_value)


def encode_ifd_entry(
    tag_id: int,
    field_type: TiffFieldType,
    count: int,
    value_offset: int,
    endian: Endian,
) -> bytes:
    return (
        tag_id.to_bytes(2, endian)
        + field_type.to_bytes(2, endian)
        + count.to_bytes(4, endian)
        + value_offset.to_bytes(4, endian)
    )


def ascii_raw_value(value: AsciiWriteValue) -> bytes:
    raw = value.text.encode("ascii")
    return raw + b"\x00" if value.nul_terminated else raw


def rational_array_raw_value(value: RationalArrayWriteValue, endian: Endian) -> bytes:
    return b"".join(
        item.numerator.to_bytes(4, endian) + item.denominator.to_bytes(4, endian)
        for item in value.values
    )


def swap_rational_array_bytes(value: bytes) -> bytes:
    if len(value) % 4 != 0:
        raise ValueError("RATIONAL raw value length must align to 32-bit words.")
    return b"".join(value[index : index + 4][::-1] for index in range(0, len(value), 4))
