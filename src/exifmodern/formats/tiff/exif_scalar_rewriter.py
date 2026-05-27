"""Source-grounded TIFF EXIF scalar rewrite primitives."""

from __future__ import annotations

from dataclasses import replace

from exifmodern.exif_scalar_write_plan import (
    ExifScalarAsciiWriteValue,
    ExifScalarDeleteWriteValue,
    ExifScalarDirectoryName,
    ExifScalarRationalWriteValue,
    ExifScalarShortWriteValue,
    ExifScalarSignedRationalWriteValue,
    ExifScalarUndefinedWriteValue,
    ExifScalarWritePlan,
    ExifScalarWriteStep,
)
from exifmodern.formats.tiff.mutation import (
    RawTiffDirectory,
    RawTiffEntry,
    encode_tiff_mutation_model,
    minimal_tiff_mutation_model,
    parse_tiff_mutation_model,
    remove_raw_entry,
    upsert_raw_entry,
)
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_RATIONAL,
    TIFF_TYPE_SHORT,
    TIFF_TYPE_SRATIONAL,
    TIFF_TYPE_UNDEFINED,
    Endian,
    TiffFieldType,
)

EXIF_VERSION = 0x9000
COMPONENTS_CONFIGURATION = 0x9101
COLOR_SPACE = 0xA001
YCBCR_POSITIONING = 0x0213


def rewrite_exif_scalars_creating_if_needed(
    tiff_data: bytes,
    plan: ExifScalarWritePlan,
) -> bytes:
    parsed = parse_tiff_mutation_model(tiff_data)
    ifd0 = replace(
        parsed.ifd0,
        entries=apply_exif_scalar_write_plan(parsed.ifd0.entries, plan, "IFD0", parsed.endian),
    )
    exif_ifd = parsed.exif_ifd
    if has_exif_ifd_steps(plan):
        if exif_ifd is None:
            if has_exif_ifd_upsert_steps(plan):
                exif_ifd = RawTiffDirectory(
                    entries=apply_exif_scalar_write_plan(
                        default_exif_ifd_entries(parsed.endian),
                        plan,
                        "ExifIFD",
                        parsed.endian,
                    ),
                    next_ifd_offset=0,
                )
        else:
            exif_ifd = RawTiffDirectory(
                entries=apply_exif_scalar_write_plan(
                    exif_ifd.entries,
                    plan,
                    "ExifIFD",
                    parsed.endian,
                ),
                next_ifd_offset=0,
            )
    return encode_tiff_mutation_model(replace(parsed, ifd0=ifd0, exif_ifd=exif_ifd))


def create_minimal_exif_scalar_tiff(plan: ExifScalarWritePlan) -> bytes:
    endian: Endian = "big"
    ifd0 = RawTiffDirectory(
        entries=apply_exif_scalar_write_plan(default_ifd0_entries(endian), plan, "IFD0", endian),
        next_ifd_offset=0,
    )
    exif_ifd = None
    if has_exif_ifd_upsert_steps(plan):
        exif_ifd = RawTiffDirectory(
            entries=apply_exif_scalar_write_plan(
                default_exif_ifd_entries(endian),
                plan,
                "ExifIFD",
                endian,
            ),
            next_ifd_offset=0,
        )
    parsed = minimal_tiff_mutation_model(endian, ifd0, exif_ifd)
    return encode_tiff_mutation_model(parsed)


def apply_exif_scalar_write_plan(
    entries: tuple[RawTiffEntry, ...],
    plan: ExifScalarWritePlan,
    directory_name: ExifScalarDirectoryName,
    endian: Endian,
) -> tuple[RawTiffEntry, ...]:
    updated = entries
    for step in plan.steps:
        if step.directory_name != directory_name:
            continue
        if step.operation == "delete":
            updated = remove_raw_entry(RawTiffDirectory(updated, 0), int(step.tag_id, 16)).entries
            continue
        updated = upsert_raw_entry(updated, exif_scalar_step_entry(step, endian))
    return tuple(sorted(updated, key=lambda entry: entry.tag_id))


def exif_scalar_step_entry(step: ExifScalarWriteStep, endian: Endian) -> RawTiffEntry:
    return RawTiffEntry(
        tag_id=int(step.tag_id, 16),
        field_type=exif_scalar_step_field_type(step),
        count=step.count,
        raw_value=exif_scalar_step_raw_value(step, endian),
    )


def exif_scalar_step_field_type(step: ExifScalarWriteStep) -> TiffFieldType:
    if step.field_type == "ASCII":
        return TIFF_TYPE_ASCII
    if step.field_type == "SHORT":
        return TIFF_TYPE_SHORT
    if step.field_type == "RATIONAL":
        return TIFF_TYPE_RATIONAL
    if step.field_type == "UNDEFINED":
        return TIFF_TYPE_UNDEFINED
    if step.field_type == "SRATIONAL":
        return TIFF_TYPE_SRATIONAL
    raise ValueError(f"Unsupported EXIF scalar write field type: {step.field_type}")


def exif_scalar_step_raw_value(step: ExifScalarWriteStep, endian: Endian) -> bytes:
    if isinstance(step.value, ExifScalarAsciiWriteValue):
        raw = step.value.text.encode("ascii")
        return raw + b"\x00" if step.value.nul_terminated else raw
    if isinstance(step.value, ExifScalarShortWriteValue):
        return step.value.value.to_bytes(2, endian)
    if isinstance(step.value, ExifScalarRationalWriteValue):
        return step.value.numerator.to_bytes(4, endian) + step.value.denominator.to_bytes(
            4,
            endian,
        )
    if isinstance(step.value, ExifScalarUndefinedWriteValue):
        return step.value.value
    if isinstance(step.value, ExifScalarSignedRationalWriteValue):
        return step.value.numerator.to_bytes(
            4, endian, signed=True
        ) + step.value.denominator.to_bytes(
            4,
            endian,
            signed=True,
        )
    if isinstance(step.value, ExifScalarDeleteWriteValue):
        raise ValueError(f"Delete step has no raw EXIF scalar value for tag {step.tag_name}")
    raise ValueError(f"Unsupported EXIF scalar write value for tag {step.tag_name}")


def default_ifd0_entries(endian: Endian) -> tuple[RawTiffEntry, ...]:
    return (
        RawTiffEntry(
            tag_id=YCBCR_POSITIONING,
            field_type=TIFF_TYPE_SHORT,
            count=1,
            raw_value=(1).to_bytes(2, endian),
        ),
    )


def default_exif_ifd_entries(endian: Endian) -> tuple[RawTiffEntry, ...]:
    return (
        RawTiffEntry(
            tag_id=EXIF_VERSION,
            field_type=TIFF_TYPE_UNDEFINED,
            count=4,
            raw_value=b"0232",
        ),
        RawTiffEntry(
            tag_id=COMPONENTS_CONFIGURATION,
            field_type=TIFF_TYPE_UNDEFINED,
            count=4,
            raw_value=bytes((1, 2, 3, 0)),
        ),
        RawTiffEntry(
            tag_id=COLOR_SPACE,
            field_type=TIFF_TYPE_SHORT,
            count=1,
            raw_value=(0xFFFF).to_bytes(2, endian),
        ),
    )


def has_exif_ifd_steps(plan: ExifScalarWritePlan) -> bool:
    return any(step.directory_name == "ExifIFD" for step in plan.steps)


def has_exif_ifd_upsert_steps(plan: ExifScalarWritePlan) -> bool:
    return any(
        step.directory_name == "ExifIFD" and step.operation != "delete" for step in plan.steps
    )
