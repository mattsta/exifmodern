"""Shared inline maker-note IFD scalar mutation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_BYTE,
    TIFF_TYPE_LONG,
    TIFF_TYPE_SHORT,
    TIFF_TYPE_SLONG,
    TIFF_TYPE_UNDEFINED,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)

type InlineMakerNoteScalarFieldType = Literal["BYTE", "SHORT", "LONG", "SLONG"]
type InlineMakerNoteStringEncoding = Literal["ascii"]
type InlineMakerNoteEvidenceId = str

EXIF_IFD_POINTER = 0x8769
MAKER_NOTE_TAG = 0x927C
TIFF_OFFSET_TAGS = {
    0x0111,
    0x0201,
    0x8769,
    0x8825,
}


@dataclass(frozen=True)
class InlineMakerNoteIfdLocator:
    maker_note_header: bytes
    ifd_offset_from_maker_note: int


@dataclass(frozen=True)
class InlineMakerNoteScalarWriteStep:
    domain: str
    tag_name: str
    tag_id: int
    field_type: InlineMakerNoteScalarFieldType
    raw_value: int
    locator: InlineMakerNoteIfdLocator
    evidence_ids: tuple[InlineMakerNoteEvidenceId, ...] = ()


@dataclass(frozen=True)
class InlineMakerNoteScalarWritePlan:
    steps: tuple[InlineMakerNoteScalarWriteStep, ...]

    @property
    def is_empty(self) -> bool:
        return not self.steps


@dataclass(frozen=True)
class InlineMakerNoteStringWriteStep:
    domain: str
    tag_name: str
    tag_id: int
    value: str
    encoding: InlineMakerNoteStringEncoding
    locator: InlineMakerNoteIfdLocator
    evidence_ids: tuple[InlineMakerNoteEvidenceId, ...] = ()


@dataclass(frozen=True)
class InlineMakerNoteStringWritePlan:
    steps: tuple[InlineMakerNoteStringWriteStep, ...]

    @property
    def is_empty(self) -> bool:
        return not self.steps


@dataclass(frozen=True)
class InlineMakerNoteScalarRewriteResult:
    data: bytes
    changed_properties: int


@dataclass(frozen=True)
class InlineMakerNoteStringRewriteResult:
    data: bytes
    changed_properties: int


@dataclass(frozen=True)
class InlineMakerNoteScalarLocation:
    value_offset: int
    endian: Literal["little", "big"]
    raw_value: int
    byte_count: int


@dataclass(frozen=True)
class InlineMakerNoteStringLocation:
    value_offset: int
    raw_value: str
    byte_count: int


def rewrite_inline_maker_note_scalars_in_tiff(
    tiff_data: bytes,
    plan: InlineMakerNoteScalarWritePlan,
) -> InlineMakerNoteScalarRewriteResult:
    mutable = bytearray(tiff_data)
    changed_properties = 0
    for step in plan.steps:
        location = inline_maker_note_scalar_location(bytes(mutable), step)
        if location.raw_value == step.raw_value:
            continue
        mutable[location.value_offset : location.value_offset + location.byte_count] = (
            step.raw_value.to_bytes(
                location.byte_count,
                location.endian,
                signed=step.field_type == "SLONG",
            )
        )
        changed_properties += 1
    return InlineMakerNoteScalarRewriteResult(bytes(mutable), changed_properties)


def rewrite_inline_maker_note_strings_in_tiff(
    tiff_data: bytes,
    plan: InlineMakerNoteStringWritePlan,
) -> InlineMakerNoteStringRewriteResult:
    mutable = bytearray(tiff_data)
    changed_properties = 0
    for step in plan.steps:
        location = inline_maker_note_string_location(bytes(mutable), step)
        if location.raw_value == step.value:
            continue
        encoded_value = step.value.encode(step.encoding) + b"\x00"
        if len(encoded_value) <= location.byte_count:
            replacement = encoded_value + b"\x00" * (location.byte_count - len(encoded_value))
            mutable[location.value_offset : location.value_offset + location.byte_count] = (
                replacement
            )
        else:
            mutable = bytearray(
                expand_inline_maker_note_string_at_tiff_end(bytes(mutable), step, encoded_value)
            )
        changed_properties += 1
    return InlineMakerNoteStringRewriteResult(bytes(mutable), changed_properties)


def read_inline_maker_note_scalar_value(
    tiff_data: bytes,
    step: InlineMakerNoteScalarWriteStep,
) -> int:
    return inline_maker_note_scalar_location(tiff_data, step).raw_value


def read_inline_maker_note_string_value(
    tiff_data: bytes,
    step: InlineMakerNoteStringWriteStep,
) -> str:
    return inline_maker_note_string_location(tiff_data, step).raw_value


def inline_maker_note_scalar_location(
    tiff_data: bytes,
    step: InlineMakerNoteScalarWriteStep,
) -> InlineMakerNoteScalarLocation:
    header = parse_tiff_header(tiff_data)
    maker_note_offset = inline_maker_note_offset(tiff_data)
    validate_inline_maker_note_header(tiff_data, maker_note_offset, step.locator)
    maker_note_ifd = parse_ifd(
        tiff_data,
        maker_note_offset + step.locator.ifd_offset_from_maker_note,
        header.endian,
    )
    entry = required_ifd_entry(maker_note_ifd, step.tag_id, f"{step.domain} {step.tag_name}")
    validate_inline_maker_note_entry(entry, step)
    value = read_entry_value(tiff_data, entry, header.endian)
    if not isinstance(value, int):
        raise ValueError(f"{step.domain} {step.tag_name} value is not a scalar integer.")
    return InlineMakerNoteScalarLocation(
        value_offset=entry.entry_offset + 8,
        endian=header.endian,
        raw_value=value,
        byte_count=inline_maker_note_scalar_byte_count(step),
    )


def inline_maker_note_string_location(
    tiff_data: bytes,
    step: InlineMakerNoteStringWriteStep,
) -> InlineMakerNoteStringLocation:
    header = parse_tiff_header(tiff_data)
    maker_note_offset = inline_maker_note_offset(tiff_data)
    validate_inline_maker_note_header(tiff_data, maker_note_offset, step.locator)
    maker_note_ifd = parse_ifd(
        tiff_data,
        maker_note_offset + step.locator.ifd_offset_from_maker_note,
        header.endian,
    )
    entry = required_ifd_entry(maker_note_ifd, step.tag_id, f"{step.domain} {step.tag_name}")
    validate_inline_maker_note_string_entry(entry, step)
    value_offset = inline_maker_note_value_storage_offset(entry)
    raw_value = inline_maker_note_raw_bytes(tiff_data, entry, header.endian).rstrip(b"\x00")
    return InlineMakerNoteStringLocation(
        value_offset=value_offset,
        raw_value=raw_value.decode(step.encoding),
        byte_count=entry.count,
    )


def expand_inline_maker_note_string_at_tiff_end(
    tiff_data: bytes,
    step: InlineMakerNoteStringWriteStep,
    encoded_value: bytes,
) -> bytes:
    header = parse_tiff_header(tiff_data)
    maker_note_offset = inline_maker_note_offset(tiff_data)
    validate_inline_maker_note_header(tiff_data, maker_note_offset, step.locator)
    maker_note_ifd = parse_ifd(
        tiff_data,
        maker_note_offset + step.locator.ifd_offset_from_maker_note,
        header.endian,
    )
    maker_note_entry = inline_maker_note_entry(tiff_data)
    maker_note_end = maker_note_entry.value_offset + maker_note_entry.count
    entry = required_ifd_entry(maker_note_ifd, step.tag_id, f"{step.domain} {step.tag_name}")
    validate_inline_maker_note_string_entry(entry, step)
    mutable = bytearray(tiff_data)
    shift_known_tiff_offsets_after_insert(
        mutable, maker_note_end, len(encoded_value), header.endian
    )
    mutable[entry.entry_offset + 4 : entry.entry_offset + 8] = len(encoded_value).to_bytes(
        4,
        header.endian,
    )
    mutable[entry.entry_offset + 8 : entry.entry_offset + 12] = maker_note_end.to_bytes(
        4,
        header.endian,
    )
    mutable[maker_note_entry.entry_offset + 4 : maker_note_entry.entry_offset + 8] = (
        maker_note_entry.count + len(encoded_value)
    ).to_bytes(4, header.endian)
    mutable[maker_note_end:maker_note_end] = encoded_value
    return bytes(mutable)


def shift_known_tiff_offsets_after_insert(
    mutable: bytearray,
    insertion_offset: int,
    inserted_byte_count: int,
    endian: Literal["little", "big"],
) -> None:
    for entry in known_tiff_offset_entries(bytes(mutable), endian):
        if entry.value_offset >= insertion_offset:
            mutable[entry.entry_offset + 8 : entry.entry_offset + 12] = (
                entry.value_offset + inserted_byte_count
            ).to_bytes(4, endian)


def known_tiff_offset_entries(
    tiff_data: bytes,
    endian: Literal["little", "big"],
) -> tuple[IfdEntry, ...]:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, endian)
    entries: list[IfdEntry] = [entry for entry in ifd0.entries if entry.tag_id in TIFF_OFFSET_TAGS]
    if ifd0.next_ifd_offset:
        ifd1 = parse_ifd(tiff_data, ifd0.next_ifd_offset, endian)
        entries.extend(entry for entry in ifd1.entries if entry.tag_id in TIFF_OFFSET_TAGS)
    exif_ifd_pointer = next(
        (entry for entry in ifd0.entries if entry.tag_id == EXIF_IFD_POINTER), None
    )
    if exif_ifd_pointer is not None:
        exif_ifd = parse_ifd(tiff_data, exif_ifd_pointer.value_offset, endian)
        entries.extend(entry for entry in exif_ifd.entries if entry.tag_id in TIFF_OFFSET_TAGS)
    return tuple(entries)


def inline_maker_note_offset(tiff_data: bytes) -> int:
    return inline_maker_note_entry(tiff_data).value_offset


def inline_maker_note_entry(tiff_data: bytes) -> IfdEntry:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    exif_ifd_pointer = required_ifd_entry(ifd0, EXIF_IFD_POINTER, "IFD0 ExifIFD pointer")
    exif_ifd = parse_ifd(tiff_data, exif_ifd_pointer.value_offset, header.endian)
    maker_note_entry = required_ifd_entry(exif_ifd, MAKER_NOTE_TAG, "ExifIFD MakerNote")
    if maker_note_entry.field_type != TIFF_TYPE_UNDEFINED:
        raise ValueError("ExifIFD MakerNote tag is not undefined data.")
    return maker_note_entry


def inline_maker_note_encoded_string_value(
    step: InlineMakerNoteStringWriteStep,
    byte_count: int,
) -> bytes:
    encoded = step.value.encode(step.encoding) + b"\x00"
    if len(encoded) > byte_count:
        raise ValueError(f"{step.domain} {step.tag_name} exceeds existing string storage.")
    return encoded + b"\x00" * (byte_count - len(encoded))


def validate_inline_maker_note_header(
    tiff_data: bytes,
    maker_note_offset: int,
    locator: InlineMakerNoteIfdLocator,
) -> None:
    header = locator.maker_note_header
    if not header:
        return
    header_end = maker_note_offset + len(header)
    if header_end > len(tiff_data) or tiff_data[maker_note_offset:header_end] != header:
        raise ValueError("Unsupported maker-note header for inline IFD scalar write.")


def required_ifd_entry(ifd: Ifd, tag_id: int, label: str) -> IfdEntry:
    for entry in ifd.entries:
        if entry.tag_id == tag_id:
            return entry
    raise ValueError(f"Missing {label} tag 0x{tag_id:04x}.")


def validate_inline_maker_note_entry(
    entry: IfdEntry,
    step: InlineMakerNoteScalarWriteStep,
) -> None:
    if entry.field_type != inline_maker_note_tiff_field_type(step.field_type) or entry.count != 1:
        raise ValueError(f"{step.domain} {step.tag_name} is not a scalar writable field.")


def validate_inline_maker_note_string_entry(
    entry: IfdEntry,
    step: InlineMakerNoteStringWriteStep,
) -> None:
    if entry.field_type != TIFF_TYPE_ASCII:
        raise ValueError(f"{step.domain} {step.tag_name} is not a writable string field.")


def inline_maker_note_tiff_field_type(field_type: InlineMakerNoteScalarFieldType) -> int:
    if field_type == "BYTE":
        return TIFF_TYPE_BYTE
    if field_type == "SHORT":
        return TIFF_TYPE_SHORT
    if field_type == "LONG":
        return TIFF_TYPE_LONG
    return TIFF_TYPE_SLONG


def inline_maker_note_scalar_byte_count(step: InlineMakerNoteScalarWriteStep) -> int:
    if step.field_type == "BYTE":
        return 1
    if step.field_type == "SHORT":
        return 2
    return 4


def inline_maker_note_value_storage_offset(entry: IfdEntry) -> int:
    byte_count = TYPE_BYTE_COUNTS[entry.field_type] * entry.count
    if byte_count <= 4:
        return entry.entry_offset + 8
    return entry.value_offset


def inline_maker_note_raw_bytes(
    tiff_data: bytes,
    entry: IfdEntry,
    endian: Literal["little", "big"],
) -> bytes:
    byte_count = TYPE_BYTE_COUNTS[entry.field_type] * entry.count
    if byte_count <= 4:
        return entry.value_offset.to_bytes(4, endian)[:byte_count]
    value_end = entry.value_offset + byte_count
    if value_end > len(tiff_data):
        raise ValueError("Truncated inline maker-note value.")
    return tiff_data[entry.value_offset : value_end]


TYPE_BYTE_COUNTS = {
    TIFF_TYPE_ASCII: 1,
    TIFF_TYPE_BYTE: 1,
    TIFF_TYPE_SHORT: 2,
    TIFF_TYPE_LONG: 4,
    TIFF_TYPE_SLONG: 4,
}
