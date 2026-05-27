"""In-place writes for existing EXIF scalar values."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_LONG,
    TIFF_TYPE_RATIONAL,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
)

EXIF_IFD_POINTER = 0x8769
FOCAL_LENGTH_TAG = 0x920A

EXIF_FOCAL_LENGTH_SOURCE_ID = "format.exif.existing_scalar.focal_length"


@dataclass(frozen=True)
class ExistingExifRationalWriteStep:
    tag_name: str
    tag_id: int
    numerator: int
    denominator: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExistingExifRationalWritePlan:
    steps: tuple[ExistingExifRationalWriteStep, ...]

    @property
    def is_empty(self) -> bool:
        return not self.steps


@dataclass(frozen=True)
class ExistingExifRationalRewriteResult:
    data: bytes
    changed_properties: int


def focal_length_existing_rational_step(value: str) -> ExistingExifRationalWriteStep:
    normalized = value.strip().lower().removesuffix("mm").strip()
    focal_length = float(normalized)
    if focal_length < 0:
        raise ValueError("FocalLength must not be negative.")
    denominator = 10 if not focal_length.is_integer() else 1
    numerator = round(focal_length * denominator)
    return ExistingExifRationalWriteStep(
        tag_name="FocalLength",
        tag_id=FOCAL_LENGTH_TAG,
        numerator=numerator,
        denominator=denominator,
        evidence_ids=(EXIF_FOCAL_LENGTH_SOURCE_ID,),
    )


def rewrite_existing_exif_rationals_in_tiff(
    tiff_data: bytes,
    plan: ExistingExifRationalWritePlan,
) -> ExistingExifRationalRewriteResult:
    mutable = bytearray(tiff_data)
    changed_properties = 0
    for step in plan.steps:
        entry = existing_exif_entry(bytes(mutable), step.tag_id)
        if entry.field_type != TIFF_TYPE_RATIONAL or entry.count != 1:
            raise ValueError(f"Existing EXIF {step.tag_name} is not rational64u[1].")
        old_value = bytes(mutable[entry.value_offset : entry.value_offset + 8])
        header = parse_tiff_header(bytes(mutable))
        new_value = step.numerator.to_bytes(4, header.endian) + step.denominator.to_bytes(
            4,
            header.endian,
        )
        if old_value == new_value:
            continue
        mutable[entry.value_offset : entry.value_offset + 8] = new_value
        changed_properties += 1
    return ExistingExifRationalRewriteResult(bytes(mutable), changed_properties)


def existing_exif_entry(tiff_data: bytes, tag_id: int) -> IfdEntry:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    exif_ifd_pointer = required_ifd_entry(ifd0, EXIF_IFD_POINTER, "IFD0 ExifIFD pointer")
    if exif_ifd_pointer.field_type != TIFF_TYPE_LONG or exif_ifd_pointer.count != 1:
        raise ValueError("IFD0 ExifIFD pointer is not int32u[1].")
    exif_ifd = parse_ifd(tiff_data, exif_ifd_pointer.value_offset, header.endian)
    return required_ifd_entry(exif_ifd, tag_id, "ExifIFD existing scalar")


def required_ifd_entry(ifd: Ifd, tag_id: int, label: str) -> IfdEntry:
    for entry in ifd.entries:
        if entry.tag_id == tag_id:
            return entry
    raise ValueError(f"Missing {label} tag 0x{tag_id:04x}.")
