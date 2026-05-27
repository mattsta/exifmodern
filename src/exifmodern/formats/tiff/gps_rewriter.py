"""Source-grounded TIFF GPS IFD rewrite primitives."""

from __future__ import annotations

from dataclasses import replace

from exifmodern.formats.tiff.mutation import (
    GPS_INFO_IFD_POINTER,
    RawTiffDirectory,
    RawTiffEntry,
    TiffMutationModel,
    encode_tiff_mutation_model,
    parse_tiff_mutation_model,
    raw_entry_by_tag,
    remove_raw_entry,
    upsert_raw_entry,
)
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_BYTE,
    TIFF_TYPE_RATIONAL,
    TIFF_TYPE_SHORT,
    Endian,
    TiffFieldType,
)
from exifmodern.formats.tiff.writer_primitives import ascii_raw_value, rational_array_raw_value
from exifmodern.write_plan import (
    AsciiWriteValue,
    ByteWriteValue,
    ExifGpsWritePlan,
    ExifGpsWriteStep,
    GpsDeleteWriteValue,
    RationalArrayWriteValue,
)

YCBCR_POSITIONING = 0x0213


def rewrite_existing_gps_ifd(tiff_data: bytes, plan: ExifGpsWritePlan) -> bytes:
    parsed = parse_tiff_mutation_model(tiff_data, require_existing_gps=True)
    if parsed.gps_ifd is None:
        raise ValueError("GPS IFD creation requires a dedicated source-confirmed oracle probe.")
    gps_ifd = RawTiffDirectory(
        entries=apply_gps_write_plan(parsed.gps_ifd.entries, plan, parsed.endian),
        next_ifd_offset=0,
    )
    return encode_gps_tiff_mutation_model(replace(parsed, gps_ifd=gps_ifd))


def rewrite_gps_ifd_creating_if_needed(tiff_data: bytes, plan: ExifGpsWritePlan) -> bytes:
    parsed = parse_tiff_mutation_model(tiff_data)
    source_entries = () if parsed.gps_ifd is None else parsed.gps_ifd.entries
    gps_ifd = RawTiffDirectory(
        entries=apply_gps_write_plan(source_entries, plan, parsed.endian),
        next_ifd_offset=0,
    )
    return encode_gps_tiff_mutation_model(replace(parsed, gps_ifd=gps_ifd))


def create_minimal_gps_tiff(plan: ExifGpsWritePlan) -> bytes:
    endian: Endian = "big"
    ifd0 = RawTiffDirectory(
        entries=(
            RawTiffEntry(
                tag_id=YCBCR_POSITIONING,
                field_type=TIFF_TYPE_SHORT,
                count=1,
                raw_value=(1).to_bytes(2, endian),
            ),
        ),
        next_ifd_offset=0,
    )
    gps_ifd = RawTiffDirectory(
        entries=apply_gps_write_plan((), plan, endian),
        next_ifd_offset=0,
    )
    return encode_tiff_mutation_model(
        TiffMutationModel(
            endian=endian,
            ifd0=ifd0,
            exif_ifd=None,
            gps_ifd=gps_ifd,
            ifd1=None,
            thumbnail=b"",
            suffix=b"",
        )
    )


def delete_gps_ifd(tiff_data: bytes) -> bytes:
    parsed = parse_tiff_mutation_model(tiff_data)
    if parsed.gps_ifd is None:
        return tiff_data
    ifd0 = remove_raw_entry(parsed.ifd0, GPS_INFO_IFD_POINTER)
    return encode_tiff_mutation_model(replace(parsed, ifd0=ifd0, gps_ifd=None))


def encode_gps_tiff_mutation_model(parsed: TiffMutationModel) -> bytes:
    if parsed.gps_ifd is None:
        raise ValueError("GPS rewrite requires a planned GPS IFD.")
    return encode_tiff_mutation_model(parsed)


def apply_gps_write_plan(
    entries: tuple[RawTiffEntry, ...],
    plan: ExifGpsWritePlan,
    endian: Endian,
) -> tuple[RawTiffEntry, ...]:
    updated = entries
    for step in plan.steps:
        tag_id = int(step.tag_id, 16)
        if step.operation == "delete":
            updated = remove_raw_entry(RawTiffDirectory(updated, 0), tag_id).entries
            continue
        if step.operation == "ensure" and raw_entry_by_tag(updated, tag_id) is not None:
            continue
        updated = upsert_raw_entry(updated, gps_step_entry(step, endian))
    return tuple(sorted(updated, key=lambda entry: entry.tag_id))


def gps_step_entry(step: ExifGpsWriteStep, endian: Endian) -> RawTiffEntry:
    return RawTiffEntry(
        tag_id=int(step.tag_id, 16),
        field_type=gps_step_field_type(step),
        count=step.count,
        raw_value=gps_step_raw_value(step, endian),
    )


def gps_step_field_type(step: ExifGpsWriteStep) -> TiffFieldType:
    if step.field_type == "ASCII":
        return TIFF_TYPE_ASCII
    if step.field_type == "BYTE":
        return TIFF_TYPE_BYTE
    if step.field_type == "RATIONAL":
        return TIFF_TYPE_RATIONAL
    raise ValueError(f"Unsupported GPS write field type: {step.field_type}")


def gps_step_raw_value(step: ExifGpsWriteStep, endian: Endian) -> bytes:
    if isinstance(step.value, AsciiWriteValue):
        return ascii_raw_value(step.value)
    if isinstance(step.value, ByteWriteValue):
        return bytes(step.value.values)
    if isinstance(step.value, RationalArrayWriteValue):
        return rational_array_raw_value(step.value, endian)
    if isinstance(step.value, GpsDeleteWriteValue):
        raise ValueError(f"Delete step has no raw GPS value for tag {step.tag_name}")
    raise ValueError(f"Unsupported GPS write value for tag {step.tag_name}")
