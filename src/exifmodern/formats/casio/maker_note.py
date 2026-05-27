"""Source-grounded Casio maker-note mutation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_LONG,
    TIFF_TYPE_SHORT,
    TIFF_TYPE_UNDEFINED,
    TYPE_SIZES,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)

type CasioMakerNoteFamily = Literal["type1", "type2"]
type CasioMakerNoteTagName = Literal["FocusMode", "ObjectDistance", "FirmwareDate"]

EXIF_IFD_POINTER = 0x8769
MAKER_NOTE_TAG = 0x927C
CASIO_TYPE2_HEADER = b"QVC\x00\x00\x00"
CASIO_TYPE1_FOCUS_MODE_TAG = 0x0003
CASIO_TYPE1_FIRMWARE_DATE_TAG = 0x0015
CASIO_TYPE2_FIRMWARE_DATE_TAG = 0x2001
CASIO_TYPE2_OBJECT_DISTANCE_TAG = 0x2022
CASIO_FIRMWARE_DATE_COUNT = 18

CASIO_TYPE1_SOURCE = "format.casio.makernote.type1.scalars"
CASIO_TYPE2_SOURCE = "format.casio.makernote.type2.object_distance"
CASIO_TYPE1_FIRMWARE_DATE_SOURCE = "format.casio.makernote.type1.firmware_date"
CASIO_TYPE2_FIRMWARE_DATE_SOURCE = "format.casio.makernote.type2.firmware_date"
CASIO_WRITE_TEST_SOURCE = "format.casio.writer.tests.casio_t_5_6"


@dataclass(frozen=True)
class CasioMakerNoteWriteStep:
    family: CasioMakerNoteFamily
    tag_name: CasioMakerNoteTagName
    tag_id: int
    field_type: int
    raw_value: int | bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CasioMakerNoteWritePlan:
    steps: tuple[CasioMakerNoteWriteStep, ...]


@dataclass(frozen=True)
class CasioMakerNoteRewriteResult:
    data: bytes
    changed_properties: int


@dataclass(frozen=True)
class CasioMakerNoteValueLocation:
    value_offset: int
    field_type_offset: int
    entry_field_type: int
    endian: Literal["little", "big"]
    raw_value: int | bytes
    byte_count: int


def build_casio_maker_note_write_plan(
    focus_mode: str | None,
    object_distance: str | None,
    firmware_date: str | None = None,
    firmware_date_family: CasioMakerNoteFamily | None = None,
) -> CasioMakerNoteWritePlan:
    steps: list[CasioMakerNoteWriteStep] = []
    if focus_mode is not None:
        steps.append(casio_type1_focus_mode_step(focus_mode))
    if object_distance is not None:
        steps.append(casio_type2_object_distance_step(object_distance))
    if firmware_date is not None:
        if firmware_date_family is None:
            raise ValueError("Casio FirmwareDate write requires an explicit maker-note family.")
        steps.append(casio_firmware_date_step(firmware_date, firmware_date_family))
    if not steps:
        raise ValueError("Casio maker-note write plan requires at least one value.")
    return CasioMakerNoteWritePlan(tuple(steps))


def casio_type1_focus_mode_step(value: str) -> CasioMakerNoteWriteStep:
    return CasioMakerNoteWriteStep(
        family="type1",
        tag_name="FocusMode",
        tag_id=CASIO_TYPE1_FOCUS_MODE_TAG,
        field_type=TIFF_TYPE_SHORT,
        raw_value=normalize_casio_type1_focus_mode(value),
        evidence_ids=(CASIO_TYPE1_SOURCE, CASIO_WRITE_TEST_SOURCE),
    )


def casio_type2_object_distance_step(value: str) -> CasioMakerNoteWriteStep:
    return CasioMakerNoteWriteStep(
        family="type2",
        tag_name="ObjectDistance",
        tag_id=CASIO_TYPE2_OBJECT_DISTANCE_TAG,
        field_type=TIFF_TYPE_LONG,
        raw_value=normalize_casio_object_distance(value),
        evidence_ids=(CASIO_TYPE2_SOURCE, CASIO_WRITE_TEST_SOURCE),
    )


def casio_firmware_date_step(
    value: str,
    family: CasioMakerNoteFamily,
) -> CasioMakerNoteWriteStep:
    if family == "type1":
        tag_id = CASIO_TYPE1_FIRMWARE_DATE_TAG
        evidence_ids = (CASIO_TYPE1_FIRMWARE_DATE_SOURCE,)
    else:
        tag_id = CASIO_TYPE2_FIRMWARE_DATE_TAG
        evidence_ids = (CASIO_TYPE2_FIRMWARE_DATE_SOURCE,)
    return CasioMakerNoteWriteStep(
        family=family,
        tag_name="FirmwareDate",
        tag_id=tag_id,
        field_type=TIFF_TYPE_UNDEFINED,
        raw_value=normalize_casio_firmware_date(value),
        evidence_ids=evidence_ids,
    )


def rewrite_casio_maker_notes_in_tiff(
    tiff_data: bytes,
    plan: CasioMakerNoteWritePlan,
) -> CasioMakerNoteRewriteResult:
    mutable = bytearray(tiff_data)
    changed_properties = 0
    for step in plan.steps:
        location = casio_maker_note_value_location(bytes(mutable), step)
        value_changed = location.raw_value != step.raw_value
        field_type_changed = (
            step.tag_name == "FirmwareDate" and location.entry_field_type != TIFF_TYPE_UNDEFINED
        )
        if not value_changed and not field_type_changed:
            continue
        if field_type_changed:
            mutable[location.field_type_offset : location.field_type_offset + 2] = (
                TIFF_TYPE_UNDEFINED.to_bytes(2, location.endian)
            )
        if value_changed:
            mutable[location.value_offset : location.value_offset + location.byte_count] = (
                encode_casio_maker_note_value(step, location.endian)
            )
        changed_properties += 1
    return CasioMakerNoteRewriteResult(bytes(mutable), changed_properties)


def encode_casio_maker_note_value(
    step: CasioMakerNoteWriteStep,
    endian: Literal["little", "big"],
) -> bytes:
    byte_count = casio_step_byte_count(step)
    if isinstance(step.raw_value, bytes):
        if len(step.raw_value) != byte_count:
            raise ValueError(f"Casio {step.tag_name} value must be {byte_count} bytes.")
        return step.raw_value
    max_value = (1 << (byte_count * 8)) - 1
    if step.raw_value < 0 or step.raw_value > max_value:
        raise ValueError(f"Casio {step.tag_name} value is outside {byte_count}-byte range.")
    return step.raw_value.to_bytes(byte_count, endian)


def read_casio_maker_note_value(
    tiff_data: bytes,
    step: CasioMakerNoteWriteStep,
) -> int | bytes:
    return casio_maker_note_value_location(tiff_data, step).raw_value


def casio_maker_note_value_location(
    tiff_data: bytes,
    step: CasioMakerNoteWriteStep,
) -> CasioMakerNoteValueLocation:
    header = parse_tiff_header(tiff_data)
    maker_note_offset = casio_maker_note_offset(tiff_data)
    maker_note_ifd = parse_ifd(
        tiff_data,
        casio_maker_note_ifd_offset(tiff_data, maker_note_offset, step.family),
        header.endian,
    )
    entry = required_ifd_entry(maker_note_ifd, step.tag_id, f"Casio {step.tag_name}")
    validate_casio_maker_note_entry(entry, step)
    byte_count = casio_step_byte_count(step)
    value_offset = entry.entry_offset + 8
    if byte_count > 4:
        value_offset = entry.value_offset
    if isinstance(step.raw_value, bytes):
        value_end = value_offset + byte_count
        if value_end > len(tiff_data):
            raise ValueError(f"Truncated Casio {step.tag_name} value at offset {value_offset}.")
        value: int | bytes = tiff_data[value_offset:value_end]
    else:
        read_value = read_entry_value(tiff_data, entry, header.endian)
        if not isinstance(read_value, int):
            raise ValueError(f"Casio {step.tag_name} value is not a scalar integer.")
        value = read_value
    return CasioMakerNoteValueLocation(
        value_offset=value_offset,
        field_type_offset=entry.entry_offset + 2,
        entry_field_type=entry.field_type,
        endian=header.endian,
        raw_value=value,
        byte_count=byte_count,
    )


def casio_maker_note_offset(tiff_data: bytes) -> int:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    exif_ifd_pointer = required_ifd_entry(ifd0, EXIF_IFD_POINTER, "IFD0 ExifIFD pointer")
    exif_ifd = parse_ifd(tiff_data, exif_ifd_pointer.value_offset, header.endian)
    maker_note_entry = required_ifd_entry(exif_ifd, MAKER_NOTE_TAG, "ExifIFD MakerNoteCasio")
    if maker_note_entry.field_type != TIFF_TYPE_UNDEFINED:
        raise ValueError("Casio MakerNote tag is not undefined data.")
    return maker_note_entry.value_offset


def casio_maker_note_ifd_offset(
    tiff_data: bytes,
    maker_note_offset: int,
    family: CasioMakerNoteFamily,
) -> int:
    if family == "type1":
        return maker_note_offset
    header_end = maker_note_offset + len(CASIO_TYPE2_HEADER)
    if header_end > len(tiff_data) or tiff_data[maker_note_offset:header_end] != CASIO_TYPE2_HEADER:
        raise ValueError("Unsupported Casio Type2 MakerNote header.")
    return header_end


def required_ifd_entry(ifd: Ifd, tag_id: int, label: str) -> IfdEntry:
    for entry in ifd.entries:
        if entry.tag_id == tag_id:
            return entry
    raise ValueError(f"Missing {label} tag 0x{tag_id:04x}.")


def validate_casio_maker_note_entry(
    entry: IfdEntry,
    step: CasioMakerNoteWriteStep,
) -> None:
    expected_count = casio_step_count(step)
    expected_field_types = {step.field_type}
    if step.tag_name == "FirmwareDate":
        expected_field_types.add(TIFF_TYPE_ASCII)
    if entry.field_type not in expected_field_types or entry.count != expected_count:
        raise ValueError(f"Casio {step.tag_name} is not a scalar writable field.")


def casio_step_byte_count(step: CasioMakerNoteWriteStep) -> int:
    field_size = TYPE_SIZES.get(step.field_type)
    if field_size is None:
        raise ValueError(f"Unsupported Casio maker-note field type: {step.field_type}")
    return field_size * casio_step_count(step)


def casio_step_count(step: CasioMakerNoteWriteStep) -> int:
    if step.tag_name == "FirmwareDate":
        return CASIO_FIRMWARE_DATE_COUNT
    return 1


def normalize_casio_type1_focus_mode(value: str) -> int:
    normalized = value.strip().lower()
    if normalized == "macro":
        return 2
    if normalized == "auto":
        return 3
    if normalized == "manual":
        return 4
    if normalized == "infinity":
        return 5
    if normalized == "spot af":
        return 7
    if normalized.isdecimal():
        return int(normalized)
    raise ValueError("Casio FocusMode must be Macro, Auto, Manual, Infinity, Spot AF, or int.")


def normalize_casio_object_distance(value: str) -> int:
    normalized = value.strip().lower()
    if normalized == "inf":
        return 0x20000000
    if normalized.endswith("m"):
        normalized = normalized[:-1].strip()
    distance = Fraction(normalized)
    if distance < 0:
        raise ValueError("Casio ObjectDistance must be non-negative.")
    return int(distance * 1000)


def normalize_casio_firmware_date(value: str) -> bytes:
    date, separator, time = value.strip().partition(" ")
    date_parts = date.split(":")
    time_parts = time.split(":") if separator else []
    if (
        len(date_parts) != 3
        or len(time_parts) != 2
        or len(date_parts[0]) != 4
        or date_parts[0][:2] not in {"19", "20"}
        or any(len(part) != 2 or not part.isdecimal() for part in (*date_parts[1:], *time_parts))
        or not date_parts[0].isdecimal()
    ):
        raise ValueError("Casio FirmwareDate must match YYYY:MM:DD HH:MM.")
    year = date_parts[0][2:]
    month, day = date_parts[1], date_parts[2]
    hour, minute = time_parts
    return f"{year}{month}\0\0{day}{hour}\0\0{minute}\0\0\0\0".encode("latin-1")
