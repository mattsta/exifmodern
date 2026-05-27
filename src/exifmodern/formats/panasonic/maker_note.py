"""Source-grounded Panasonic maker-note scalar adapters."""

from __future__ import annotations

from exifmodern.formats.makernote.inline_ifd import (
    InlineMakerNoteIfdLocator,
    InlineMakerNoteScalarWritePlan,
    InlineMakerNoteScalarWriteStep,
)

PANASONIC_SHOOTING_MODE_TAG = 0x001F
PANASONIC_INLINE_IFD_LOCATOR = InlineMakerNoteIfdLocator(
    maker_note_header=b"Panasonic\x00\x00\x00",
    ifd_offset_from_maker_note=12,
)
PANASONIC_SHOOTING_MODE_VALUES = {
    "normal": 1,
    "portrait": 2,
    "scenery": 3,
    "sports": 4,
    "night portrait": 5,
    "program": 6,
    "aperture priority": 7,
    "shutter priority": 8,
    "macro": 9,
    "spot": 10,
    "manual": 11,
    "movie preview": 12,
    "panning": 13,
    "simple": 14,
    "color effects": 15,
    "self portrait": 16,
    "economy": 17,
    "fireworks": 18,
    "party": 19,
    "snow": 20,
    "night scenery": 21,
    "food": 22,
    "baby": 23,
    "soft skin": 24,
    "candlelight": 25,
    "starry night": 26,
    "high sensitivity": 27,
    "panorama assist": 28,
    "underwater": 29,
}
PANASONIC_SHOOTING_MODE_SOURCE = "panasonic.makernote.shooting_mode_print"
PANASONIC_SHOOTING_MODE_TAG_SOURCE = "panasonic.makernote.shooting_mode_tag"
PANASONIC_WRITE_TEST_SOURCE = "panasonic.makernote.write_test_3"


def build_panasonic_shooting_mode_write_plan(value: str) -> InlineMakerNoteScalarWritePlan:
    return InlineMakerNoteScalarWritePlan((panasonic_shooting_mode_write_step(value),))


def panasonic_shooting_mode_write_step(value: str) -> InlineMakerNoteScalarWriteStep:
    return InlineMakerNoteScalarWriteStep(
        domain="Panasonic",
        tag_name="ShootingMode",
        tag_id=PANASONIC_SHOOTING_MODE_TAG,
        field_type="SHORT",
        raw_value=normalize_panasonic_shooting_mode(value),
        locator=PANASONIC_INLINE_IFD_LOCATOR,
        evidence_ids=(
            PANASONIC_SHOOTING_MODE_SOURCE,
            PANASONIC_SHOOTING_MODE_TAG_SOURCE,
            PANASONIC_WRITE_TEST_SOURCE,
        ),
    )


def normalize_panasonic_shooting_mode(value: str) -> int:
    normalized = " ".join(value.strip().lower().replace("-", " ").split())
    mapped = PANASONIC_SHOOTING_MODE_VALUES.get(normalized)
    if mapped is not None:
        return mapped
    if normalized.isdecimal():
        return int(normalized)
    raise ValueError("Panasonic ShootingMode must be a source-defined mode or an integer.")
