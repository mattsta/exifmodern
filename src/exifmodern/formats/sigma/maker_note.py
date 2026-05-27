"""Source-grounded Sigma maker-note string adapters."""

from __future__ import annotations

from decimal import Decimal

from exifmodern.formats.makernote.inline_ifd import (
    InlineMakerNoteIfdLocator,
    InlineMakerNoteStringWritePlan,
    InlineMakerNoteStringWriteStep,
)

SIGMA_SHARPNESS_TAG = 0x0011
SIGMA_INLINE_IFD_LOCATOR = InlineMakerNoteIfdLocator(
    maker_note_header=b"SIGMA\x00\x00\x00\x01\x00",
    ifd_offset_from_maker_note=10,
)
SIGMA_SHARPNESS_SOURCE = "sigma.makernote.sharpness"
SIGMA_WRITE_TEST_SOURCE = "sigma.makernote.write_test_3"


def build_sigma_sharpness_write_plan(value: str) -> InlineMakerNoteStringWritePlan:
    return InlineMakerNoteStringWritePlan(
        (
            InlineMakerNoteStringWriteStep(
                domain="Sigma",
                tag_name="Sharpness",
                tag_id=SIGMA_SHARPNESS_TAG,
                value=normalize_sigma_sharpness(value),
                encoding="ascii",
                locator=SIGMA_INLINE_IFD_LOCATOR,
                evidence_ids=(SIGMA_SHARPNESS_SOURCE, SIGMA_WRITE_TEST_SOURCE),
            ),
        )
    )


def normalize_sigma_sharpness(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("Shar:"):
        return normalized
    return f"Shar:{Decimal(normalized):+.1f}"
