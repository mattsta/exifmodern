"""Source-grounded Kodak maker-note BinaryData write plans."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.makernote.binary_data import (
    MakerNoteBinaryDataWritePlan,
    MakerNoteBinaryDataWriteStep,
    MakerNoteBlockBinaryDataLocator,
)

KODAK_TYPE1A_HEADER = b"KDK INFO"
KODAK_TYPE1A_FIRST_ENTRY = 8
KODAK_YEAR_CREATED_TAG = 0x10
KODAK_MONTH_DAY_CREATED_TAG = 0x12
KODAK_DIGITAL_ZOOM_TAG = 0x68

KODAK_TYPE1A_SOURCE = "kodak.makernote.type1a"
KODAK_WRITE_TEST_SOURCE = "kodak.makernote.write_test_3"


@dataclass(frozen=True)
class KodakMakerNoteWriteValues:
    year_created: str | None = None
    month_day_created: str | None = None
    digital_zoom: str | None = None


def build_kodak_maker_note_write_plan(
    values: KodakMakerNoteWriteValues,
) -> MakerNoteBinaryDataWritePlan:
    steps: list[MakerNoteBinaryDataWriteStep] = []
    if values.year_created is not None:
        steps.append(kodak_year_created_step(values.year_created))
    if values.month_day_created is not None:
        steps.append(kodak_month_day_created_step(values.month_day_created))
    if values.digital_zoom is not None:
        steps.append(kodak_digital_zoom_step(values.digital_zoom))
    if not steps:
        raise ValueError("Kodak maker-note write plan requires at least one value.")
    return MakerNoteBinaryDataWritePlan(tuple(steps))


def kodak_year_created_step(value: str) -> MakerNoteBinaryDataWriteStep:
    return MakerNoteBinaryDataWriteStep(
        domain="Kodak",
        tag_name="YearCreated",
        tag_id=KODAK_YEAR_CREATED_TAG,
        field_type="int16u",
        raw_values=(normalize_kodak_year(value),),
        locator=kodak_type1a_locator(),
        evidence_ids=(KODAK_TYPE1A_SOURCE, KODAK_WRITE_TEST_SOURCE),
    )


def kodak_month_day_created_step(value: str) -> MakerNoteBinaryDataWriteStep:
    month, day = normalize_kodak_month_day(value)
    return MakerNoteBinaryDataWriteStep(
        domain="Kodak",
        tag_name="MonthDayCreated",
        tag_id=KODAK_MONTH_DAY_CREATED_TAG,
        field_type="int8u",
        raw_values=(month, day),
        locator=kodak_type1a_locator(),
        evidence_ids=(KODAK_TYPE1A_SOURCE, KODAK_WRITE_TEST_SOURCE),
    )


def kodak_digital_zoom_step(value: str) -> MakerNoteBinaryDataWriteStep:
    return MakerNoteBinaryDataWriteStep(
        domain="Kodak",
        tag_name="DigitalZoom",
        tag_id=KODAK_DIGITAL_ZOOM_TAG,
        field_type="int16u",
        raw_values=(normalize_kodak_digital_zoom(value),),
        locator=kodak_type1a_locator(),
        evidence_ids=(KODAK_TYPE1A_SOURCE, KODAK_WRITE_TEST_SOURCE),
    )


def kodak_type1a_locator() -> MakerNoteBlockBinaryDataLocator:
    return MakerNoteBlockBinaryDataLocator(
        maker_note_header=KODAK_TYPE1A_HEADER,
        binary_data_offset_from_maker_note=KODAK_TYPE1A_FIRST_ENTRY,
        byte_order="tiff",
    )


def normalize_kodak_year(value: str) -> int:
    year = int(value)
    if year < 0 or year > 0xFFFF:
        raise ValueError("Kodak YearCreated must fit in int16u.")
    return year


def normalize_kodak_month_day(value: str) -> tuple[int, int]:
    normalized = value.replace(".", ":")
    parts = normalized.split(":")
    if len(parts) != 2:
        raise ValueError("Kodak MonthDayCreated must be MM:DD.")
    month = int(parts[0])
    day = int(parts[1])
    if month < 1 or month > 12 or day < 1 or day > 31:
        raise ValueError("Kodak MonthDayCreated must contain valid month/day numbers.")
    return month, day


def normalize_kodak_digital_zoom(value: str) -> int:
    raw_value = round(float(value) * 100)
    if raw_value < 0 or raw_value > 0xFFFF:
        raise ValueError("Kodak DigitalZoom must fit in int16u after ValueConvInv.")
    return raw_value
