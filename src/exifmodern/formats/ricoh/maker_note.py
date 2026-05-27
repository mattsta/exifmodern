"""Source-grounded Ricoh maker-note scalar adapters."""

from __future__ import annotations

from exifmodern.formats.makernote.inline_ifd import (
    InlineMakerNoteIfdLocator,
    InlineMakerNoteScalarWritePlan,
    InlineMakerNoteScalarWriteStep,
)

RICOH_SHARPNESS_TAG = 0x1003
RICOH_INLINE_IFD_LOCATOR = InlineMakerNoteIfdLocator(
    maker_note_header=b"RICOH\x00\x00\x00",
    ifd_offset_from_maker_note=8,
)
RICOH_SHARPNESS_VALUES = {
    "sharp": 0,
    "normal": 1,
    "soft": 2,
}
RICOH_SHARPNESS_SOURCE = "ricoh.makernote.sharpness"
RICOH_WRITE_TEST_SOURCE = "ricoh.makernote.write_test_3"


def build_ricoh_sharpness_write_plan(value: str) -> InlineMakerNoteScalarWritePlan:
    return InlineMakerNoteScalarWritePlan((ricoh_sharpness_write_step(value),))


def ricoh_sharpness_write_step(value: str) -> InlineMakerNoteScalarWriteStep:
    return InlineMakerNoteScalarWriteStep(
        domain="Ricoh",
        tag_name="Sharpness",
        tag_id=RICOH_SHARPNESS_TAG,
        field_type="SLONG",
        raw_value=normalize_ricoh_sharpness(value),
        locator=RICOH_INLINE_IFD_LOCATOR,
        evidence_ids=(RICOH_SHARPNESS_SOURCE, RICOH_WRITE_TEST_SOURCE),
    )


def normalize_ricoh_sharpness(value: str) -> int:
    normalized = value.strip().lower()
    mapped = RICOH_SHARPNESS_VALUES.get(normalized)
    if mapped is not None:
        return mapped
    if normalized.isdecimal():
        return int(normalized)
    raise ValueError("Ricoh Sharpness must be Sharp, Normal, Soft, or an integer.")
