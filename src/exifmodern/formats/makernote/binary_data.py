"""Reusable fixed-layout maker-note BinaryData mutation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_UNDEFINED,
    Endian,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
)

type MakerNoteBinaryDataFieldType = Literal["int8u", "int16u", "int32u"]
type MakerNoteBinaryDataByteOrder = Literal["little", "big", "tiff"]

EXIF_IFD_POINTER = 0x8769
MAKER_NOTE_TAG = 0x927C


@dataclass(frozen=True)
class MakerNoteBlockBinaryDataLocator:
    maker_note_header: bytes
    binary_data_offset_from_maker_note: int
    byte_order: MakerNoteBinaryDataByteOrder


@dataclass(frozen=True)
class MakerNoteIfdBinaryDataLocator:
    maker_note_header: bytes
    maker_note_ifd_offset_from_maker_note: int
    subdirectory_tag_id: int
    binary_data_offset_from_subdirectory: int
    byte_order: MakerNoteBinaryDataByteOrder


type MakerNoteBinaryDataLocator = MakerNoteBlockBinaryDataLocator | MakerNoteIfdBinaryDataLocator
type MakerNoteBinaryDataEvidenceId = str


@dataclass(frozen=True)
class MakerNoteBinaryDataWriteStep:
    domain: str
    tag_name: str
    tag_id: int
    field_type: MakerNoteBinaryDataFieldType
    raw_values: tuple[int, ...]
    locator: MakerNoteBinaryDataLocator
    bit_mask: int | None = None
    evidence_ids: tuple[MakerNoteBinaryDataEvidenceId, ...] = ()


@dataclass(frozen=True)
class MakerNoteBinaryDataWritePlan:
    steps: tuple[MakerNoteBinaryDataWriteStep, ...]

    @property
    def is_empty(self) -> bool:
        return not self.steps


@dataclass(frozen=True)
class MakerNoteBinaryDataRewriteResult:
    data: bytes
    changed_properties: int


@dataclass(frozen=True)
class MakerNoteBinaryDataLocation:
    value_offset: int
    endian: Endian
    raw_values: tuple[int, ...]
    byte_count: int


def rewrite_maker_note_binary_data_in_tiff(
    tiff_data: bytes,
    plan: MakerNoteBinaryDataWritePlan,
) -> MakerNoteBinaryDataRewriteResult:
    mutable = bytearray(tiff_data)
    changed_properties = 0
    for step in plan.steps:
        location = maker_note_binary_data_location(bytes(mutable), step)
        if location.raw_values == step.raw_values:
            continue
        current_value = bytes(
            mutable[location.value_offset : location.value_offset + location.byte_count]
        )
        mutable[location.value_offset : location.value_offset + location.byte_count] = (
            encode_binary_data_values(step, location.endian, current_value)
        )
        changed_properties += 1
    return MakerNoteBinaryDataRewriteResult(bytes(mutable), changed_properties)


def read_maker_note_binary_data_values(
    tiff_data: bytes,
    step: MakerNoteBinaryDataWriteStep,
) -> tuple[int, ...]:
    return maker_note_binary_data_location(tiff_data, step).raw_values


def maker_note_binary_data_location(
    tiff_data: bytes,
    step: MakerNoteBinaryDataWriteStep,
) -> MakerNoteBinaryDataLocation:
    header = parse_tiff_header(tiff_data)
    maker_note_offset = maker_note_value_offset(tiff_data)
    validate_maker_note_header(tiff_data, maker_note_offset, step.locator.maker_note_header)
    binary_data_offset = maker_note_binary_data_offset(tiff_data, maker_note_offset, step.locator)
    endian = binary_data_endian(header.endian, step.locator.byte_order)
    value_offset = binary_data_offset + step.tag_id
    byte_count = binary_data_step_byte_count(step)
    value_end = value_offset + byte_count
    if value_end > len(tiff_data):
        raise ValueError(f"Truncated {step.domain} {step.tag_name} BinaryData value.")
    return MakerNoteBinaryDataLocation(
        value_offset=value_offset,
        endian=endian,
        raw_values=decode_binary_data_values(
            tiff_data[value_offset:value_end],
            step.field_type,
            endian,
            step.bit_mask,
        ),
        byte_count=byte_count,
    )


def maker_note_value_offset(tiff_data: bytes) -> int:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    exif_ifd_pointer = required_ifd_entry(ifd0, EXIF_IFD_POINTER, "IFD0 ExifIFD pointer")
    exif_ifd = parse_ifd(tiff_data, exif_ifd_pointer.value_offset, header.endian)
    maker_note_entry = required_ifd_entry(exif_ifd, MAKER_NOTE_TAG, "ExifIFD MakerNote")
    if maker_note_entry.field_type != TIFF_TYPE_UNDEFINED:
        raise ValueError("ExifIFD MakerNote tag is not undefined data.")
    return maker_note_entry.value_offset


def maker_note_binary_data_offset(
    tiff_data: bytes,
    maker_note_offset: int,
    locator: MakerNoteBinaryDataLocator,
) -> int:
    if isinstance(locator, MakerNoteBlockBinaryDataLocator):
        return maker_note_offset + locator.binary_data_offset_from_maker_note
    header = parse_tiff_header(tiff_data)
    maker_note_ifd = parse_ifd(
        tiff_data,
        maker_note_offset + locator.maker_note_ifd_offset_from_maker_note,
        header.endian,
    )
    subdirectory_entry = required_ifd_entry(
        maker_note_ifd,
        locator.subdirectory_tag_id,
        "MakerNote BinaryData subdirectory",
    )
    return subdirectory_entry.value_offset + locator.binary_data_offset_from_subdirectory


def validate_maker_note_header(
    tiff_data: bytes,
    maker_note_offset: int,
    maker_note_header: bytes,
) -> None:
    if not maker_note_header:
        return
    header_end = maker_note_offset + len(maker_note_header)
    if header_end > len(tiff_data) or tiff_data[maker_note_offset:header_end] != maker_note_header:
        raise ValueError("Unsupported maker-note header for BinaryData write.")


def required_ifd_entry(ifd: Ifd, tag_id: int, label: str) -> IfdEntry:
    for entry in ifd.entries:
        if entry.tag_id == tag_id:
            return entry
    raise ValueError(f"Missing {label} tag 0x{tag_id:04x}.")


def binary_data_endian(tiff_endian: Endian, byte_order: MakerNoteBinaryDataByteOrder) -> Endian:
    if byte_order == "tiff":
        return tiff_endian
    return byte_order


def binary_data_step_byte_count(step: MakerNoteBinaryDataWriteStep) -> int:
    return binary_data_field_byte_count(step.field_type) * len(step.raw_values)


def binary_data_field_byte_count(field_type: MakerNoteBinaryDataFieldType) -> int:
    if field_type == "int8u":
        return 1
    if field_type == "int16u":
        return 2
    return 4


def decode_binary_data_values(
    data: bytes,
    field_type: MakerNoteBinaryDataFieldType,
    endian: Endian,
    bit_mask: int | None = None,
) -> tuple[int, ...]:
    byte_count = binary_data_field_byte_count(field_type)
    return tuple(
        decode_binary_data_value(data[index : index + byte_count], endian, bit_mask)
        for index in range(0, len(data), byte_count)
    )


def decode_binary_data_value(data: bytes, endian: Endian, bit_mask: int | None) -> int:
    value = int.from_bytes(data, endian)
    if bit_mask is None:
        return value
    return value & bit_mask


def encode_binary_data_values(
    step: MakerNoteBinaryDataWriteStep,
    endian: Endian,
    current_value: bytes,
) -> bytes:
    byte_count = binary_data_field_byte_count(step.field_type)
    if step.bit_mask is None:
        return b"".join(value.to_bytes(byte_count, endian) for value in step.raw_values)
    return b"".join(
        encode_masked_binary_data_value(
            value,
            current_value[index * byte_count : index * byte_count + byte_count],
            byte_count,
            endian,
            step.bit_mask,
        )
        for index, value in enumerate(step.raw_values)
    )


def encode_masked_binary_data_value(
    value: int,
    current_value: bytes,
    byte_count: int,
    endian: Endian,
    bit_mask: int,
) -> bytes:
    current = int.from_bytes(current_value, endian)
    merged = (current & ~bit_mask) | (value & bit_mask)
    return merged.to_bytes(byte_count, endian)
