"""Minolta maker-note BinaryData write plans."""

from __future__ import annotations

import re

from exifmodern.formats.makernote.binary_data import (
    MakerNoteBinaryDataWritePlan,
    MakerNoteBinaryDataWriteStep,
    MakerNoteIfdBinaryDataLocator,
)

MINOLTA_CAMERA_SETTINGS_TAG = 0x0003
MINOLTA_DATE_TAG = 21
MINOLTA_DATE_PATTERN = re.compile(r"^(\d{4}):(\d{1,2}):(\d{1,2})$")

MINOLTA_MAIN_SOURCE_ID = "minolta.makernote.main"
MINOLTA_CAMERA_SETTINGS_SOURCE_ID = "minolta.makernote.camera_settings"
MINOLTA_WRITE_TEST_SOURCE_ID = "minolta.makernote.write_test_3"


def build_minolta_date_write_plan(value: str) -> MakerNoteBinaryDataWritePlan:
    return MakerNoteBinaryDataWritePlan(
        (
            MakerNoteBinaryDataWriteStep(
                domain="Minolta",
                tag_name="MinoltaDate",
                tag_id=MINOLTA_DATE_TAG * 4,
                field_type="int32u",
                raw_values=(normalize_minolta_date(value),),
                locator=MakerNoteIfdBinaryDataLocator(
                    maker_note_header=b"",
                    maker_note_ifd_offset_from_maker_note=0,
                    subdirectory_tag_id=MINOLTA_CAMERA_SETTINGS_TAG,
                    binary_data_offset_from_subdirectory=0,
                    byte_order="big",
                ),
                evidence_ids=(
                    MINOLTA_MAIN_SOURCE_ID,
                    MINOLTA_CAMERA_SETTINGS_SOURCE_ID,
                    MINOLTA_WRITE_TEST_SOURCE_ID,
                ),
            ),
        )
    )


def normalize_minolta_date(value: str) -> int:
    match = MINOLTA_DATE_PATTERN.match(value)
    if match is None:
        raise ValueError("MinoltaDate must be YYYY:MM:DD.")
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    if month < 1 or month > 12 or day < 1 or day > 31:
        raise ValueError("MinoltaDate must contain valid month/day numbers.")
    if year < 0 or year > 0xFFFF:
        raise ValueError("MinoltaDate year must fit in 16 bits.")
    return (year << 16) + (month << 8) + day
