"""Source-grounded Pentax maker-note write plans."""

from __future__ import annotations

import math
from dataclasses import dataclass

from exifmodern.formats.makernote.binary_data import (
    MakerNoteBinaryDataWritePlan,
    MakerNoteBinaryDataWriteStep,
    MakerNoteIfdBinaryDataLocator,
)
from exifmodern.formats.makernote.inline_ifd import (
    InlineMakerNoteIfdLocator,
    InlineMakerNoteScalarWritePlan,
    InlineMakerNoteScalarWriteStep,
)

PENTAX_AOC_HEADER = b"AOC\x00"
PENTAX_AOC_IFD_OFFSET = 6
PENTAX_WHITE_BALANCE_TAG = 0x0019
PENTAX_FOCAL_LENGTH_TAG = 0x001D
PENTAX_LENS_INFO_TAG = 0x0207
PENTAX_LENS_DATA_OFFSET = 4
PENTAX_MAX_APERTURE_LENS_DATA_OFFSET = 14
PENTAX_MAX_APERTURE_MASK = 0x7F

PENTAX_MAKER_NOTE_SOURCE = "pentax.makernote.aoc_route"
PENTAX_WHITE_BALANCE_SOURCE = "pentax.makernote.white_balance"
PENTAX_FOCAL_LENGTH_SOURCE = "pentax.makernote.focal_length"
PENTAX_LENS_INFO_SOURCE = "pentax.makernote.lens_info"
PENTAX_MAX_APERTURE_SOURCE = "pentax.makernote.max_aperture"
PENTAX_WRITE_TEST_SOURCE = "pentax.makernote.write_test_3"

PENTAX_WHITE_BALANCE_PRINT_INV = {
    "auto": 0,
    "daylight": 1,
    "shade": 2,
    "fluorescent": 3,
    "tungsten": 4,
    "manual": 5,
    "daylight fluorescent": 6,
    "day white fluorescent": 7,
    "white fluorescent": 8,
    "flash": 9,
    "cloudy": 10,
    "warm white fluorescent": 11,
    "multi auto": 14,
    "color temperature enhancement": 15,
    "kelvin": 17,
    "unknown": 0xFFFE,
    "user-selected": 0xFFFF,
}


@dataclass(frozen=True)
class PentaxMakerNoteWriteValues:
    white_balance: str | None = None
    focal_length: str | None = None
    max_aperture: str | None = None


@dataclass(frozen=True)
class PentaxMakerNoteWritePlan:
    inline_scalar_plan: InlineMakerNoteScalarWritePlan | None
    binary_data_plan: MakerNoteBinaryDataWritePlan | None

    @property
    def is_empty(self) -> bool:
        return self.inline_scalar_plan is None and self.binary_data_plan is None


def build_pentax_maker_note_write_plan(
    values: PentaxMakerNoteWriteValues,
) -> PentaxMakerNoteWritePlan:
    inline_steps: list[InlineMakerNoteScalarWriteStep] = []
    binary_steps: list[MakerNoteBinaryDataWriteStep] = []
    if values.white_balance is not None:
        inline_steps.append(pentax_white_balance_step(values.white_balance))
    if values.focal_length is not None:
        inline_steps.append(pentax_focal_length_step(values.focal_length))
    if values.max_aperture is not None:
        binary_steps.append(pentax_max_aperture_step(values.max_aperture))
    if not inline_steps and not binary_steps:
        raise ValueError("Pentax maker-note write plan requires at least one value.")
    return PentaxMakerNoteWritePlan(
        inline_scalar_plan=InlineMakerNoteScalarWritePlan(tuple(inline_steps))
        if inline_steps
        else None,
        binary_data_plan=MakerNoteBinaryDataWritePlan(tuple(binary_steps))
        if binary_steps
        else None,
    )


def pentax_white_balance_step(value: str) -> InlineMakerNoteScalarWriteStep:
    return InlineMakerNoteScalarWriteStep(
        domain="Pentax",
        tag_name="WhiteBalance",
        tag_id=PENTAX_WHITE_BALANCE_TAG,
        field_type="SHORT",
        raw_value=normalize_pentax_white_balance(value),
        locator=pentax_aoc_locator(),
        evidence_ids=(
            PENTAX_MAKER_NOTE_SOURCE,
            PENTAX_WHITE_BALANCE_SOURCE,
            PENTAX_WRITE_TEST_SOURCE,
        ),
    )


def pentax_focal_length_step(value: str) -> InlineMakerNoteScalarWriteStep:
    return InlineMakerNoteScalarWriteStep(
        domain="Pentax",
        tag_name="FocalLength",
        tag_id=PENTAX_FOCAL_LENGTH_TAG,
        field_type="LONG",
        raw_value=normalize_pentax_focal_length(value),
        locator=pentax_aoc_locator(),
        evidence_ids=(
            PENTAX_MAKER_NOTE_SOURCE,
            PENTAX_FOCAL_LENGTH_SOURCE,
            PENTAX_WRITE_TEST_SOURCE,
        ),
    )


def pentax_max_aperture_step(value: str) -> MakerNoteBinaryDataWriteStep:
    return MakerNoteBinaryDataWriteStep(
        domain="Pentax",
        tag_name="MaxAperture",
        tag_id=PENTAX_MAX_APERTURE_LENS_DATA_OFFSET,
        field_type="int8u",
        raw_values=(normalize_pentax_max_aperture(value),),
        locator=MakerNoteIfdBinaryDataLocator(
            maker_note_header=PENTAX_AOC_HEADER,
            maker_note_ifd_offset_from_maker_note=PENTAX_AOC_IFD_OFFSET,
            subdirectory_tag_id=PENTAX_LENS_INFO_TAG,
            binary_data_offset_from_subdirectory=PENTAX_LENS_DATA_OFFSET,
            byte_order="big",
        ),
        evidence_ids=(
            PENTAX_MAKER_NOTE_SOURCE,
            PENTAX_LENS_INFO_SOURCE,
            PENTAX_MAX_APERTURE_SOURCE,
            PENTAX_WRITE_TEST_SOURCE,
        ),
        bit_mask=PENTAX_MAX_APERTURE_MASK,
    )


def pentax_aoc_locator() -> InlineMakerNoteIfdLocator:
    return InlineMakerNoteIfdLocator(
        maker_note_header=PENTAX_AOC_HEADER,
        ifd_offset_from_maker_note=PENTAX_AOC_IFD_OFFSET,
    )


def normalize_pentax_white_balance(value: str) -> int:
    normalized = value.strip().lower()
    if normalized in PENTAX_WHITE_BALANCE_PRINT_INV:
        return PENTAX_WHITE_BALANCE_PRINT_INV[normalized]
    raw_value = int(value)
    if raw_value < 0 or raw_value > 0xFFFF:
        raise ValueError("Pentax WhiteBalance must fit in int16u.")
    return raw_value


def normalize_pentax_focal_length(value: str) -> int:
    normalized = value.strip().lower().removesuffix("mm").strip()
    raw_value = round(float(normalized) * 100)
    if raw_value < 0 or raw_value > 0xFFFFFFFF:
        raise ValueError("Pentax FocalLength must fit in int32u after ValueConvInv.")
    return raw_value


def normalize_pentax_max_aperture(value: str) -> int:
    aperture = float(value.strip())
    if aperture <= 0:
        raise ValueError("Pentax MaxAperture must be positive.")
    raw_value = round(32 * math.log2(aperture) + 1)
    if raw_value < 0 or raw_value > PENTAX_MAX_APERTURE_MASK:
        raise ValueError("Pentax MaxAperture raw value must fit the 0x7f mask.")
    return raw_value
