"""Source-backed Panasonic RW2 container mutation planning.

This module decomposes the unsafe byte-level work behind Panasonic RAW writes.
It intentionally stops at a typed plan: ExifTool rewrites RW2 through the TIFF
writer and then applies Panasonic-specific raw-data offset patching, so partial
in-place mutation would risk corrupting image data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from xml.sax.saxutils import escape

from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION_TEXT
from exifmodern.formats.iptc.dataset_writer import apply_iptc_application_write_plan
from exifmodern.formats.iptc.write_plan import build_iptc_application_write_plan
from exifmodern.formats.panasonic_raw.write_plan import (
    PANASONIC_RAW_APPLICATION_NOTES_SOURCE,
    PANASONIC_RAW_IPTC_SOURCE,
    PANASONIC_RAW_MAIN_SOURCE,
    PANASONIC_RAW_MODIFY_DATE_SOURCE,
    PANASONIC_RAW_OFFSET_PATCH_SOURCE,
    WRITE_EXIF_PANASONIC_PATCH_SOURCE,
    WRITE_EXIF_PANASONIC_STRIP_SOURCE,
    WRITE_EXIF_RAW_DATA_COPY_SOURCE,
    PanasonicRawEvidenceId,
)
from exifmodern.formats.tiff.mutation import RawTiffEntry, raw_entry_by_tag
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_BYTE,
    TIFF_TYPE_LONG,
    TYPE_SIZES,
    IfdEntry,
    parse_ifd,
)
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.json_types import JsonObject

XMP_PROPERTY_TABLE_SOURCE: PanasonicRawEvidenceId = "xmp.property_table"
XMP_PROPERTY_WRITE_SOURCE: PanasonicRawEvidenceId = "xmp.property_write"

type TiffByteOrder = Literal["little", "big"]
type PanasonicRawMutationPlanStatus = Literal["source_mapped_deferred", "unsupported"]
type PanasonicRawOffsetTagName = Literal["StripOffsets", "StripByteCounts", "RawDataOffset"]
type PanasonicRawPatchStatus = Literal["source_mapped_deferred", "unsupported"]
type PanasonicRawDataCopyStatus = Literal["source_mapped_deferred", "unsupported"]
type PanasonicRawDataAppendEmitterStatus = Literal["source_mapped_deferred", "unsupported"]
type PanasonicRawOffsetFixupStatus = Literal["source_mapped_deferred", "unsupported"]
type PanasonicRawPatchError = Literal[
    "unsupported_panasonic_raw_variant",
    "error_reading_panasonic_raw_data",
]
type PanasonicRawDataCopyError = Literal[
    "unsupported_panasonic_raw_variant",
    "error_reading_panasonic_raw_data",
]
type PanasonicRawDataAppendEmitterError = Literal[
    "unsupported_panasonic_raw_variant",
    "error_reading_panasonic_raw_data",
]
type PanasonicRawFinalEmitterStatus = Literal["source_mapped_deferred", "unsupported"]
type PanasonicRawRewrittenTiffDirectoryStatus = Literal["source_mapped", "unsupported"]
type PanasonicRawRewrittenTiffDirectoryError = Literal[
    "unsupported_panasonic_raw_variant",
    "unsupported_write_arguments",
    "malformed_rw2_ifd",
    "raw_data_offset_not_available",
]
type PanasonicRawFinalEmitterError = Literal[
    "unsupported_panasonic_raw_variant",
    "error_reading_panasonic_raw_data",
    "missing_rewritten_tiff_directory_bytes",
    "missing_rewritten_offset_field_coordinates",
    "offset_field_out_of_bounds",
]
type PanasonicRawOffsetFixupError = Literal[
    "unsupported_panasonic_raw_variant",
    "error_reading_panasonic_raw_data",
    "missing_rewritten_tiff_directory_length",
    "missing_fixed_offset_padding_length",
]
type PanasonicRawMutationStepKind = Literal[
    "validate_rw2_tiff_header",
    "collect_ifd0_image_data_offsets",
    "run_panasonic_raw_data_offset_patch",
    "rewrite_ifd0_metadata_directories",
    "copy_raw_image_data_after_fixups",
]
type PanasonicRawSafetyBlocker = Literal[
    "requires_full_tiff_directory_rebuild",
    "requires_panasonic_variant_checks",
    "requires_raw_image_data_copy",
    "requires_offset_fixup_table",
]
type PanasonicRawDataAppendSegmentKind = Literal[
    "rewritten_tiff_directories",
    "fixed_offset_padding",
    "copied_raw_image_data",
    "even_padding_byte",
]
type PanasonicRawDataAppendEmitterGateCode = Literal[
    "requires_full_tiff_directory_rebuild",
    "requires_writeexif_offset_fixup_applier",
    "requires_panasonic_raw_data_copy",
    "requires_fixed_offset_padding_decision",
    "requires_rewritten_offset_field_coordinates",
]
type PanasonicRawOffsetFixupRecordKind = Literal[
    "primary_raw_data_offset",
    "mirrored_strip_offsets",
]
type PanasonicRawOffsetFixupPaddingKind = Literal[
    "fixed_offset_padding",
    "even_payload_padding",
]
type PanasonicRawOffsetBasis = Literal[
    "old_file_absolute",
    "new_rewritten_tiff_end",
]
type PanasonicRawFinalEmitterSegmentKind = Literal[
    "patched_rewritten_tiff_directories",
    "fixed_offset_padding",
    "copied_raw_image_data",
    "even_padding_byte",
]

RW2_TIFF_MAGIC = 0x55
TIFF_IFD_ENTRY_SIZE = 12
TIFF_TYPE_BYTE_COUNTS: dict[int, int] = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    7: 1,
    9: 4,
    10: 8,
}
PANASONIC_OFFSET_TAGS: dict[int, PanasonicRawOffsetTagName] = {
    0x0111: "StripOffsets",
    0x0117: "StripByteCounts",
    0x0118: "RawDataOffset",
}
PANASONIC_APPLICATION_NOTES_TAG = 0x02BC
PANASONIC_IPTC_NAA_TAG = 0x83BB
PANASONIC_MODIFY_DATE_TAG = 0x0132


@dataclass(frozen=True)
class PanasonicRawIfdOffsetTag:
    tag_id: int
    tag_name: PanasonicRawOffsetTagName
    tiff_type: int
    value_count: int
    value_field_offset: int
    values: tuple[int, ...]

    def to_json(self) -> JsonObject:
        return {
            "tag_id": f"0x{self.tag_id:04x}",
            "tag_name": self.tag_name,
            "tiff_type": self.tiff_type,
            "value_count": self.value_count,
            "value_field_offset": self.value_field_offset,
            "values": list(self.values),
        }


@dataclass(frozen=True)
class PanasonicRawMutationStep:
    kind: PanasonicRawMutationStepKind
    description: str
    blockers: tuple[PanasonicRawSafetyBlocker, ...]
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "description": self.description,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class PanasonicRawTiffOffsetMutationPlan:
    status: PanasonicRawMutationPlanStatus
    can_mutate: bool
    byte_order: TiffByteOrder | None
    first_ifd_offset: int | None
    ifd0_entry_count: int | None
    offset_tags: tuple[PanasonicRawIfdOffsetTag, ...]
    steps: tuple[PanasonicRawMutationStep, ...]
    blockers: tuple[PanasonicRawSafetyBlocker, ...]
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "byte_order": self.byte_order,
            "can_mutate": self.can_mutate,
            "first_ifd_offset": self.first_ifd_offset,
            "ifd0_entry_count": self.ifd0_entry_count,
            "offset_tags": [tag.to_json() for tag in self.offset_tags],
            "status": self.status,
            "steps": [step.to_json() for step in self.steps],
        }


@dataclass(frozen=True)
class PanasonicRawDataOffsetPatchPlan:
    status: PanasonicRawPatchStatus
    can_mutate: bool
    ifd_index: int
    selected_offset_tag: PanasonicRawOffsetTagName | None
    selected_offset_value_field_offset: int | None
    selected_raw_data_offset: int | None
    raw_data_length: int | None
    effective_strip_byte_count: int | None
    updates_strip_offsets_from_raw_data_offset: bool
    strip_offsets_value_field_offset: int | None
    uses_fixed_offset_padding: bool
    error: PanasonicRawPatchError | None
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_mutate": self.can_mutate,
            "effective_strip_byte_count": self.effective_strip_byte_count,
            "error": self.error,
            "ifd_index": self.ifd_index,
            "raw_data_length": self.raw_data_length,
            "selected_offset_tag": self.selected_offset_tag,
            "selected_offset_value_field_offset": self.selected_offset_value_field_offset,
            "selected_raw_data_offset": self.selected_raw_data_offset,
            "status": self.status,
            "strip_offsets_value_field_offset": self.strip_offsets_value_field_offset,
            "updates_strip_offsets_from_raw_data_offset": (
                self.updates_strip_offsets_from_raw_data_offset
            ),
            "uses_fixed_offset_padding": self.uses_fixed_offset_padding,
        }


@dataclass(frozen=True)
class PanasonicRawDataCopyPlan:
    status: PanasonicRawDataCopyStatus
    can_copy_payload: bool
    source_offset: int | None
    byte_count: int | None
    source_end_offset: int | None
    even_padding_byte_count: int | None
    requires_deferred_append: bool
    error: PanasonicRawDataCopyError | None
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_count": self.byte_count,
            "can_copy_payload": self.can_copy_payload,
            "error": self.error,
            "even_padding_byte_count": self.even_padding_byte_count,
            "requires_deferred_append": self.requires_deferred_append,
            "source_end_offset": self.source_end_offset,
            "source_offset": self.source_offset,
            "status": self.status,
        }


@dataclass(frozen=True)
class PanasonicRawDataAppendSegment:
    kind: PanasonicRawDataAppendSegmentKind
    source_offset: int | None
    source_length: int | None
    output_length: int | None
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "output_length": self.output_length,
            "source_length": self.source_length,
            "source_offset": self.source_offset,
        }


@dataclass(frozen=True)
class PanasonicRawDataAppendEmitterGate:
    code: PanasonicRawDataAppendEmitterGateCode
    detail: str
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PanasonicRawDataAppendEmitterContract:
    status: PanasonicRawDataAppendEmitterStatus
    can_emit_output: bool
    output_segments: tuple[PanasonicRawDataAppendSegment, ...]
    output_emission_gates: tuple[PanasonicRawDataAppendEmitterGate, ...]
    old_raw_data_offset: int | None
    old_raw_data_length: int | None
    copied_payload_end_offset: int | None
    even_padding_byte_count: int | None
    error: PanasonicRawDataAppendEmitterError | None
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "copied_payload_end_offset": self.copied_payload_end_offset,
            "error": self.error,
            "even_padding_byte_count": self.even_padding_byte_count,
            "old_raw_data_length": self.old_raw_data_length,
            "old_raw_data_offset": self.old_raw_data_offset,
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "output_segments": [segment.to_json() for segment in self.output_segments],
            "status": self.status,
        }


@dataclass(frozen=True)
class PanasonicRawOffsetFixupRecord:
    kind: PanasonicRawOffsetFixupRecordKind
    tag_name: PanasonicRawOffsetTagName
    tag_id: int
    original_value_field_offset: int
    old_value: int
    new_value: int | None
    old_basis: PanasonicRawOffsetBasis
    new_basis: PanasonicRawOffsetBasis
    requires_writeexif_fixup: bool
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "new_basis": self.new_basis,
            "new_value": self.new_value,
            "old_basis": self.old_basis,
            "old_value": self.old_value,
            "original_value_field_offset": self.original_value_field_offset,
            "requires_writeexif_fixup": self.requires_writeexif_fixup,
            "tag_id": f"0x{self.tag_id:04x}",
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class PanasonicRawOffsetFixupPaddingRecord:
    kind: PanasonicRawOffsetFixupPaddingKind
    byte_count: int | None
    output_offset: int | None
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_count": self.byte_count,
            "kind": self.kind,
            "output_offset": self.output_offset,
        }


@dataclass(frozen=True)
class PanasonicRawOffsetFixupApplicationContract:
    status: PanasonicRawOffsetFixupStatus
    can_apply_fixups: bool
    old_raw_data_offset: int | None
    old_raw_data_length: int | None
    rewritten_tiff_directory_length: int | None
    fixed_offset_padding_byte_count: int | None
    new_raw_data_offset: int | None
    copied_payload_end_offset: int | None
    fixup_records: tuple[PanasonicRawOffsetFixupRecord, ...]
    padding_records: tuple[PanasonicRawOffsetFixupPaddingRecord, ...]
    error: PanasonicRawOffsetFixupError | None
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_apply_fixups": self.can_apply_fixups,
            "copied_payload_end_offset": self.copied_payload_end_offset,
            "error": self.error,
            "fixed_offset_padding_byte_count": self.fixed_offset_padding_byte_count,
            "fixup_records": [record.to_json() for record in self.fixup_records],
            "new_raw_data_offset": self.new_raw_data_offset,
            "old_raw_data_length": self.old_raw_data_length,
            "old_raw_data_offset": self.old_raw_data_offset,
            "padding_records": [record.to_json() for record in self.padding_records],
            "rewritten_tiff_directory_length": self.rewritten_tiff_directory_length,
            "status": self.status,
        }


@dataclass(frozen=True)
class PanasonicRawRewrittenOffsetFieldCoordinate:
    kind: PanasonicRawOffsetFixupRecordKind
    tag_name: PanasonicRawOffsetTagName
    rewritten_value_field_offset: int

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "rewritten_value_field_offset": self.rewritten_value_field_offset,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class PanasonicRawFinalEmitterSegment:
    kind: PanasonicRawFinalEmitterSegmentKind
    source_offset: int | None
    source_length: int | None
    output_length: int
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "output_length": self.output_length,
            "source_length": self.source_length,
            "source_offset": self.source_offset,
        }


@dataclass(frozen=True)
class PanasonicRawFinalEmitterContract:
    status: PanasonicRawFinalEmitterStatus
    can_emit_output: bool
    output_bytes: bytes | None
    output_length: int | None
    new_raw_data_offset: int | None
    applied_offset_coordinates: tuple[PanasonicRawRewrittenOffsetFieldCoordinate, ...]
    output_segments: tuple[PanasonicRawFinalEmitterSegment, ...]
    output_emission_gates: tuple[PanasonicRawDataAppendEmitterGate, ...]
    error: PanasonicRawFinalEmitterError | None
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "applied_offset_coordinates": [
                coordinate.to_json() for coordinate in self.applied_offset_coordinates
            ],
            "can_emit_output": self.can_emit_output,
            "error": self.error,
            "new_raw_data_offset": self.new_raw_data_offset,
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "output_length": self.output_length,
            "output_segments": [segment.to_json() for segment in self.output_segments],
            "status": self.status,
        }


@dataclass(frozen=True)
class PanasonicRawRewrittenTiffDirectoryBytes:
    status: PanasonicRawRewrittenTiffDirectoryStatus
    can_supply_final_emitter_input: bool
    rewritten_tiff_directory_bytes: bytes | None
    rewritten_tiff_directory_length: int | None
    xmp_payload_length: int | None
    iptc_payload_length: int | None
    modify_date_value: str | None
    raw_data_source_offset: int | None
    error: PanasonicRawRewrittenTiffDirectoryError | None
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_supply_final_emitter_input": self.can_supply_final_emitter_input,
            "error": self.error,
            "iptc_payload_length": self.iptc_payload_length,
            "modify_date_value": self.modify_date_value,
            "raw_data_source_offset": self.raw_data_source_offset,
            "rewritten_tiff_directory_length": self.rewritten_tiff_directory_length,
            "status": self.status,
            "xmp_payload_length": self.xmp_payload_length,
        }


def build_panasonic_rw2_tiff_offset_mutation_plan(
    data: bytes,
) -> PanasonicRawTiffOffsetMutationPlan:
    header = parse_rw2_header(data)
    if header is None:
        return PanasonicRawTiffOffsetMutationPlan(
            status="unsupported",
            can_mutate=False,
            byte_order=None,
            first_ifd_offset=None,
            ifd0_entry_count=None,
            offset_tags=(),
            steps=(),
            blockers=("requires_full_tiff_directory_rebuild",),
            evidence_ids=(PANASONIC_RAW_MAIN_SOURCE,),
        )

    byte_order, first_ifd_offset = header
    ifd0_entry_count = read_ifd_entry_count(data, first_ifd_offset, byte_order)
    offset_tags = (
        parse_ifd0_offset_tags(data, first_ifd_offset, ifd0_entry_count, byte_order)
        if ifd0_entry_count is not None
        else ()
    )
    steps = panasonic_rw2_mutation_steps()
    return PanasonicRawTiffOffsetMutationPlan(
        status="source_mapped_deferred",
        can_mutate=False,
        byte_order=byte_order,
        first_ifd_offset=first_ifd_offset,
        ifd0_entry_count=ifd0_entry_count,
        offset_tags=offset_tags,
        steps=steps,
        blockers=unique_blockers(steps),
        evidence_ids=unique_evidence_ids(
            (
                PANASONIC_RAW_MAIN_SOURCE,
                PANASONIC_RAW_OFFSET_PATCH_SOURCE,
                WRITE_EXIF_PANASONIC_PATCH_SOURCE,
                WRITE_EXIF_RAW_DATA_COPY_SOURCE,
                WRITE_EXIF_PANASONIC_STRIP_SOURCE,
            )
        ),
    )


def build_panasonic_raw_data_offset_patch_plan(
    data: bytes,
    offset_tags: tuple[PanasonicRawIfdOffsetTag, ...],
    ifd_index: int = 0,
) -> PanasonicRawDataOffsetPatchPlan:
    strip_offsets = find_offset_tag(offset_tags, "StripOffsets")
    strip_byte_counts = find_offset_tag(offset_tags, "StripByteCounts")
    raw_data_offset = find_offset_tag(offset_tags, "RawDataOffset")
    evidence_ids = unique_evidence_ids(
        (
            PANASONIC_RAW_OFFSET_PATCH_SOURCE,
            WRITE_EXIF_PANASONIC_PATCH_SOURCE,
            WRITE_EXIF_PANASONIC_STRIP_SOURCE,
        )
    )

    unsupported = PanasonicRawDataOffsetPatchPlan(
        status="unsupported",
        can_mutate=False,
        ifd_index=ifd_index,
        selected_offset_tag=None,
        selected_offset_value_field_offset=None,
        selected_raw_data_offset=None,
        raw_data_length=None,
        effective_strip_byte_count=None,
        updates_strip_offsets_from_raw_data_offset=False,
        strip_offsets_value_field_offset=None,
        uses_fixed_offset_padding=False,
        error="unsupported_panasonic_raw_variant",
        evidence_ids=evidence_ids,
    )
    if ifd_index != 0:
        return unsupported
    if (strip_offsets is not None or strip_byte_counts is not None) and (
        strip_offsets is None or strip_byte_counts is None or strip_offsets.value_count != 1
    ):
        return unsupported
    if raw_data_offset is not None:
        if raw_data_offset.value_count != 1:
            return unsupported
        if strip_offsets is not None and strip_byte_counts is not None:
            strip_offset = first_offset_value(strip_offsets)
            strip_byte_count = first_offset_value(strip_byte_counts)
            if strip_offset not in {None, 0xFFFFFFFF} and strip_byte_count != 0:
                return unsupported

    selected_offset_tag = raw_data_offset or strip_offsets
    selected_offset_value = (
        first_offset_value(selected_offset_tag) if selected_offset_tag is not None else None
    )
    if selected_offset_tag is None or selected_offset_value is None:
        return unsupported

    raw_data_length = len(data) - selected_offset_value
    if raw_data_length < 0 or (raw_data_length < 1000 and raw_data_length != 22):
        return PanasonicRawDataOffsetPatchPlan(
            status="unsupported",
            can_mutate=False,
            ifd_index=ifd_index,
            selected_offset_tag=selected_offset_tag.tag_name,
            selected_offset_value_field_offset=selected_offset_tag.value_field_offset,
            selected_raw_data_offset=selected_offset_value,
            raw_data_length=raw_data_length,
            effective_strip_byte_count=None,
            updates_strip_offsets_from_raw_data_offset=False,
            strip_offsets_value_field_offset=None,
            uses_fixed_offset_padding=False,
            error="error_reading_panasonic_raw_data",
            evidence_ids=evidence_ids,
        )
    if raw_data_length & 0x80000000:
        return PanasonicRawDataOffsetPatchPlan(
            status="unsupported",
            can_mutate=False,
            ifd_index=ifd_index,
            selected_offset_tag=selected_offset_tag.tag_name,
            selected_offset_value_field_offset=selected_offset_tag.value_field_offset,
            selected_raw_data_offset=selected_offset_value,
            raw_data_length=raw_data_length,
            effective_strip_byte_count=None,
            updates_strip_offsets_from_raw_data_offset=False,
            strip_offsets_value_field_offset=None,
            uses_fixed_offset_padding=False,
            error="error_reading_panasonic_raw_data",
            evidence_ids=evidence_ids,
        )

    updates_strip_offsets = False
    strip_offsets_value_field_offset: int | None = None
    if raw_data_offset is not None and strip_offsets is not None:
        strip_offset = first_offset_value(strip_offsets)
        if strip_offset is not None and strip_offset != 0xFFFFFFFF:
            updates_strip_offsets = True
            strip_offsets_value_field_offset = strip_offsets.value_field_offset

    return PanasonicRawDataOffsetPatchPlan(
        status="source_mapped_deferred",
        can_mutate=False,
        ifd_index=ifd_index,
        selected_offset_tag=selected_offset_tag.tag_name,
        selected_offset_value_field_offset=selected_offset_tag.value_field_offset,
        selected_raw_data_offset=selected_offset_value,
        raw_data_length=raw_data_length,
        effective_strip_byte_count=raw_data_length,
        updates_strip_offsets_from_raw_data_offset=updates_strip_offsets,
        strip_offsets_value_field_offset=strip_offsets_value_field_offset,
        uses_fixed_offset_padding=(
            raw_data_offset is not None and strip_offsets is None and strip_byte_counts is None
        ),
        error=None,
        evidence_ids=evidence_ids,
    )


def build_panasonic_raw_data_copy_plan(
    data: bytes,
    patch_plan: PanasonicRawDataOffsetPatchPlan,
) -> PanasonicRawDataCopyPlan:
    evidence_ids = unique_evidence_ids(
        (
            PANASONIC_RAW_OFFSET_PATCH_SOURCE,
            WRITE_EXIF_RAW_DATA_COPY_SOURCE,
            WRITE_EXIF_PANASONIC_STRIP_SOURCE,
        )
    )
    if patch_plan.error == "error_reading_panasonic_raw_data":
        return unsupported_raw_data_copy_plan(
            evidence_ids,
            error="error_reading_panasonic_raw_data",
        )
    if (
        patch_plan.status != "source_mapped_deferred"
        or patch_plan.selected_raw_data_offset is None
        or patch_plan.effective_strip_byte_count is None
    ):
        return unsupported_raw_data_copy_plan(
            evidence_ids,
            error="unsupported_panasonic_raw_variant",
        )

    source_offset = patch_plan.selected_raw_data_offset
    byte_count = patch_plan.effective_strip_byte_count
    source_end_offset = source_offset + byte_count
    if source_offset < 0 or byte_count < 0 or source_end_offset > len(data):
        return unsupported_raw_data_copy_plan(
            evidence_ids,
            source_offset=source_offset,
            byte_count=byte_count,
            source_end_offset=source_end_offset,
            error="error_reading_panasonic_raw_data",
        )

    return PanasonicRawDataCopyPlan(
        status="source_mapped_deferred",
        can_copy_payload=True,
        source_offset=source_offset,
        byte_count=byte_count,
        source_end_offset=source_end_offset,
        even_padding_byte_count=byte_count % 2,
        requires_deferred_append=True,
        error=None,
        evidence_ids=evidence_ids,
    )


def build_panasonic_raw_data_append_emitter_contract(
    copy_plan: PanasonicRawDataCopyPlan,
    *,
    uses_fixed_offset_padding: bool = False,
) -> PanasonicRawDataAppendEmitterContract:
    evidence_ids = unique_evidence_ids(
        (
            WRITE_EXIF_RAW_DATA_COPY_SOURCE,
            WRITE_EXIF_PANASONIC_STRIP_SOURCE,
            PANASONIC_RAW_OFFSET_PATCH_SOURCE,
        )
    )
    if copy_plan.error is not None:
        return unsupported_raw_data_append_emitter_contract(
            evidence_ids,
            error=copy_plan.error,
        )
    if (
        copy_plan.status != "source_mapped_deferred"
        or copy_plan.source_offset is None
        or copy_plan.byte_count is None
        or copy_plan.source_end_offset is None
        or copy_plan.even_padding_byte_count is None
    ):
        return unsupported_raw_data_append_emitter_contract(
            evidence_ids,
            error="unsupported_panasonic_raw_variant",
        )

    gates: list[PanasonicRawDataAppendEmitterGate] = [
        PanasonicRawDataAppendEmitterGate(
            code="requires_full_tiff_directory_rebuild",
            detail=(
                "WriteExif appends copied image data after the rebuilt TIFF directory data; "
                "Panasonic RW2 output cannot be emitted before that directory rebuild exists."
            ),
            evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE,),
        ),
        PanasonicRawDataAppendEmitterGate(
            code="requires_writeexif_offset_fixup_applier",
            detail=(
                "The new raw-data offset and Panasonic StripOffsets mirror value must be fixed "
                "in the rebuilt TIFF bytes before appending the preserved payload."
            ),
            evidence_ids=(WRITE_EXIF_PANASONIC_STRIP_SOURCE,),
        ),
        PanasonicRawDataAppendEmitterGate(
            code="requires_rewritten_offset_field_coordinates",
            detail=(
                "WriteExif patches offsets at positions in rebuilt TIFF data, not necessarily "
                "the original IFD value-field offsets; the final emitter needs those rewritten "
                "field coordinates before it can safely write bytes."
            ),
            evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE, WRITE_EXIF_PANASONIC_STRIP_SOURCE),
        ),
        PanasonicRawDataAppendEmitterGate(
            code="requires_panasonic_raw_data_copy",
            detail=(
                "The old raw payload must be copied from the source offset/length selected by "
                "PatchRawDataOffset."
            ),
            evidence_ids=(PANASONIC_RAW_OFFSET_PATCH_SOURCE, WRITE_EXIF_RAW_DATA_COPY_SOURCE),
        ),
    ]
    if uses_fixed_offset_padding:
        gates.append(
            PanasonicRawDataAppendEmitterGate(
                code="requires_fixed_offset_padding_decision",
                detail=(
                    "Fixed-offset GH6-style variants may require padding before raw data; "
                    "this contract records the segment but does not decide its byte count."
                ),
                evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE,),
            )
        )

    segments: list[PanasonicRawDataAppendSegment] = [
        PanasonicRawDataAppendSegment(
            kind="rewritten_tiff_directories",
            source_offset=None,
            source_length=None,
            output_length=None,
            evidence_ids=(PANASONIC_RAW_MAIN_SOURCE, WRITE_EXIF_RAW_DATA_COPY_SOURCE),
        )
    ]
    if uses_fixed_offset_padding:
        segments.append(
            PanasonicRawDataAppendSegment(
                kind="fixed_offset_padding",
                source_offset=None,
                source_length=None,
                output_length=None,
                evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE,),
            )
        )
    segments.append(
        PanasonicRawDataAppendSegment(
            kind="copied_raw_image_data",
            source_offset=copy_plan.source_offset,
            source_length=copy_plan.byte_count,
            output_length=copy_plan.byte_count,
            evidence_ids=(PANASONIC_RAW_OFFSET_PATCH_SOURCE, WRITE_EXIF_RAW_DATA_COPY_SOURCE),
        )
    )
    if copy_plan.even_padding_byte_count:
        segments.append(
            PanasonicRawDataAppendSegment(
                kind="even_padding_byte",
                source_offset=None,
                source_length=None,
                output_length=copy_plan.even_padding_byte_count,
                evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE,),
            )
        )

    return PanasonicRawDataAppendEmitterContract(
        status="source_mapped_deferred",
        can_emit_output=False,
        output_segments=tuple(segments),
        output_emission_gates=tuple(gates),
        old_raw_data_offset=copy_plan.source_offset,
        old_raw_data_length=copy_plan.byte_count,
        copied_payload_end_offset=copy_plan.source_end_offset,
        even_padding_byte_count=copy_plan.even_padding_byte_count,
        error=None,
        evidence_ids=evidence_ids,
    )


def build_panasonic_rw2_rewritten_tiff_directory_bytes(
    source_data: bytes,
    write_args: tuple[str, ...],
    patch_plan: PanasonicRawDataOffsetPatchPlan,
) -> PanasonicRawRewrittenTiffDirectoryBytes:
    """Model WriteExif's rebuilt RW2 IFD0 bytes for the sourced Panasonic.t request.

    The payloads are delegated to existing XMP/IPTC/EXIF scalar primitives.  This
    seam intentionally covers only the target RW2 write surface: IFD0
    ApplicationNotes XMP and IPTC-NAA.  The unqualified ModifyDate write for
    this RW2 shape is materialized through the writable JpgFromRaw subdocument.
    """

    evidence_ids = unique_evidence_ids(
        (
            PANASONIC_RAW_MAIN_SOURCE,
            PANASONIC_RAW_APPLICATION_NOTES_SOURCE,
            PANASONIC_RAW_IPTC_SOURCE,
            PANASONIC_RAW_MODIFY_DATE_SOURCE,
            WRITE_EXIF_RAW_DATA_COPY_SOURCE,
            XMP_PROPERTY_TABLE_SOURCE,
            XMP_PROPERTY_WRITE_SOURCE,
        )
    )
    if patch_plan.status != "source_mapped_deferred" or patch_plan.selected_raw_data_offset is None:
        return unsupported_rewritten_tiff_directory_bytes(
            evidence_ids,
            error="raw_data_offset_not_available",
        )
    header = parse_rw2_header(source_data)
    if header is None:
        return unsupported_rewritten_tiff_directory_bytes(
            evidence_ids,
            error="unsupported_panasonic_raw_variant",
        )
    byte_order, first_ifd_offset = header
    try:
        ifd0 = parse_ifd(source_data, first_ifd_offset, byte_order)
        entries = tuple(rw2_raw_entry(source_data, entry, byte_order) for entry in ifd0.entries)
    except ValueError:
        return unsupported_rewritten_tiff_directory_bytes(
            evidence_ids,
            error="malformed_rw2_ifd",
        )

    title: str | None = None
    keyword: str | None = None
    modify_date: str | None = None
    for raw_arg in write_args:
        if not raw_arg.startswith("-") or "=" not in raw_arg:
            continue
        left, value = raw_arg[1:].split("=", 1)
        if left in {"XMP:Title", "XMP-dc:Title"}:
            title = value
        elif left == "IPTC:Keywords":
            keyword = value
        elif left in {"ModifyDate", "EXIF:ModifyDate", "IFD0:ModifyDate"}:
            modify_date = value
    if title is None or keyword is None or modify_date is None:
        return unsupported_rewritten_tiff_directory_bytes(
            evidence_ids,
            error="unsupported_write_arguments",
        )

    xmp_payload = panasonic_rw2_xmp_title_payload(
        existing_external_value(entries, PANASONIC_APPLICATION_NOTES_TAG) or empty_xmp_packet(),
        title,
    )
    iptc_payload = panasonic_rw2_iptc_keywords_payload(
        existing_external_value(entries, PANASONIC_IPTC_NAA_TAG) or b"",
        keyword,
    )
    entries = upsert_rw2_entry(
        entries,
        RawTiffEntry(
            tag_id=PANASONIC_APPLICATION_NOTES_TAG,
            field_type=TIFF_TYPE_BYTE,
            count=len(xmp_payload),
            raw_value=xmp_payload,
        ),
    )
    entries = upsert_rw2_entry(
        entries,
        RawTiffEntry(
            tag_id=PANASONIC_IPTC_NAA_TAG,
            field_type=TIFF_TYPE_LONG,
            count=len(iptc_payload) // 4,
            raw_value=iptc_payload,
        ),
    )
    rewritten = encode_rw2_ifd0_directory_bytes(
        source_data,
        entries,
        first_ifd_offset,
        ifd0.next_ifd_offset,
        patch_plan.selected_raw_data_offset,
        byte_order,
    )
    return PanasonicRawRewrittenTiffDirectoryBytes(
        status="source_mapped",
        can_supply_final_emitter_input=True,
        rewritten_tiff_directory_bytes=rewritten,
        rewritten_tiff_directory_length=len(rewritten),
        xmp_payload_length=len(xmp_payload),
        iptc_payload_length=len(iptc_payload),
        modify_date_value=modify_date,
        raw_data_source_offset=patch_plan.selected_raw_data_offset,
        error=None,
        evidence_ids=evidence_ids,
    )


def build_panasonic_rw2_final_emitter_contract(
    source_data: bytes,
    patch_plan: PanasonicRawDataOffsetPatchPlan,
    copy_plan: PanasonicRawDataCopyPlan,
    *,
    byte_order: TiffByteOrder = "little",
    rewritten_tiff_directory_bytes: bytes | None = None,
    offset_field_coordinates: tuple[PanasonicRawRewrittenOffsetFieldCoordinate, ...] = (),
    fixed_offset_padding_byte_count: int = 0,
) -> PanasonicRawFinalEmitterContract:
    evidence_ids = unique_evidence_ids(
        (
            WRITE_EXIF_RAW_DATA_COPY_SOURCE,
            WRITE_EXIF_PANASONIC_STRIP_SOURCE,
            PANASONIC_RAW_OFFSET_PATCH_SOURCE,
        )
    )
    if patch_plan.error == "error_reading_panasonic_raw_data" or (
        copy_plan.error == "error_reading_panasonic_raw_data"
    ):
        return unsupported_final_emitter_contract(
            evidence_ids,
            error="error_reading_panasonic_raw_data",
        )
    if (
        patch_plan.status != "source_mapped_deferred"
        or copy_plan.status != "source_mapped_deferred"
        or patch_plan.selected_offset_tag is None
        or patch_plan.selected_raw_data_offset is None
        or copy_plan.source_offset is None
        or copy_plan.byte_count is None
        or copy_plan.source_end_offset is None
        or copy_plan.even_padding_byte_count is None
        or copy_plan.source_end_offset > len(source_data)
    ):
        return unsupported_final_emitter_contract(
            evidence_ids,
            error="unsupported_panasonic_raw_variant",
        )
    if rewritten_tiff_directory_bytes is None:
        return deferred_final_emitter_contract(
            evidence_ids,
            error="missing_rewritten_tiff_directory_bytes",
            new_raw_data_offset=None,
            gates=(
                final_emitter_gate(
                    "requires_full_tiff_directory_rebuild",
                    "Final output requires the rebuilt TIFF directory bytes produced by WriteExif.",
                    (WRITE_EXIF_RAW_DATA_COPY_SOURCE,),
                ),
            ),
        )

    if not offset_field_coordinates:
        offset_field_coordinates = capture_panasonic_rw2_rewritten_offset_field_coordinates(
            rewritten_tiff_directory_bytes,
            patch_plan,
            byte_order=byte_order,
        )

    required_coordinates = required_rewritten_offset_coordinates(patch_plan)
    missing_coordinates = tuple(
        coordinate
        for coordinate in required_coordinates
        if not has_matching_coordinate(coordinate, offset_field_coordinates)
    )
    if missing_coordinates:
        return deferred_final_emitter_contract(
            evidence_ids,
            error="missing_rewritten_offset_field_coordinates",
            new_raw_data_offset=(
                len(rewritten_tiff_directory_bytes) + fixed_offset_padding_byte_count
            ),
            gates=(
                final_emitter_gate(
                    "requires_rewritten_offset_field_coordinates",
                    (
                        "Final output cannot reuse original Panasonic RAW IFD field offsets after "
                        "TIFF rebuild; WriteExif patches the rebuilt offset positions."
                    ),
                    (WRITE_EXIF_RAW_DATA_COPY_SOURCE, WRITE_EXIF_PANASONIC_STRIP_SOURCE),
                ),
            ),
        )

    new_raw_data_offset = len(rewritten_tiff_directory_bytes) + fixed_offset_padding_byte_count
    rewritten_tiff = bytearray(rewritten_tiff_directory_bytes)
    for coordinate in offset_field_coordinates:
        if not has_matching_coordinate(coordinate, required_coordinates):
            continue
        if coordinate.rewritten_value_field_offset < 0 or (
            coordinate.rewritten_value_field_offset + 4 > len(rewritten_tiff)
        ):
            return unsupported_final_emitter_contract(
                evidence_ids,
                error="offset_field_out_of_bounds",
                new_raw_data_offset=new_raw_data_offset,
            )
        rewritten_tiff[
            coordinate.rewritten_value_field_offset : coordinate.rewritten_value_field_offset + 4
        ] = new_raw_data_offset.to_bytes(4, byte_order)

    raw_payload = source_data[copy_plan.source_offset : copy_plan.source_end_offset]
    output = bytearray(rewritten_tiff)
    segments = [
        PanasonicRawFinalEmitterSegment(
            kind="patched_rewritten_tiff_directories",
            source_offset=None,
            source_length=None,
            output_length=len(rewritten_tiff),
            evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE, WRITE_EXIF_PANASONIC_STRIP_SOURCE),
        )
    ]
    if fixed_offset_padding_byte_count:
        output.extend(b"\0" * fixed_offset_padding_byte_count)
        segments.append(
            PanasonicRawFinalEmitterSegment(
                kind="fixed_offset_padding",
                source_offset=None,
                source_length=None,
                output_length=fixed_offset_padding_byte_count,
                evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE,),
            )
        )
    output.extend(raw_payload)
    segments.append(
        PanasonicRawFinalEmitterSegment(
            kind="copied_raw_image_data",
            source_offset=copy_plan.source_offset,
            source_length=copy_plan.byte_count,
            output_length=copy_plan.byte_count,
            evidence_ids=(PANASONIC_RAW_OFFSET_PATCH_SOURCE, WRITE_EXIF_RAW_DATA_COPY_SOURCE),
        )
    )
    if copy_plan.even_padding_byte_count:
        output.extend(b"\0" * copy_plan.even_padding_byte_count)
        segments.append(
            PanasonicRawFinalEmitterSegment(
                kind="even_padding_byte",
                source_offset=None,
                source_length=None,
                output_length=copy_plan.even_padding_byte_count,
                evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE,),
            )
        )

    return PanasonicRawFinalEmitterContract(
        status="source_mapped_deferred",
        can_emit_output=True,
        output_bytes=bytes(output),
        output_length=len(output),
        new_raw_data_offset=new_raw_data_offset,
        applied_offset_coordinates=tuple(
            coordinate
            for coordinate in offset_field_coordinates
            if has_matching_coordinate(coordinate, required_coordinates)
        ),
        output_segments=tuple(segments),
        output_emission_gates=(),
        error=None,
        evidence_ids=evidence_ids,
    )


def build_panasonic_rw2_offset_fixup_application_contract(
    patch_plan: PanasonicRawDataOffsetPatchPlan,
    copy_plan: PanasonicRawDataCopyPlan,
    *,
    rewritten_tiff_directory_length: int | None = None,
    fixed_offset_padding_byte_count: int | None = None,
) -> PanasonicRawOffsetFixupApplicationContract:
    evidence_ids = unique_evidence_ids(
        (
            PANASONIC_RAW_OFFSET_PATCH_SOURCE,
            WRITE_EXIF_RAW_DATA_COPY_SOURCE,
            WRITE_EXIF_PANASONIC_STRIP_SOURCE,
        )
    )
    if patch_plan.error == "error_reading_panasonic_raw_data" or (
        copy_plan.error == "error_reading_panasonic_raw_data"
    ):
        return unsupported_offset_fixup_application_contract(
            evidence_ids,
            error="error_reading_panasonic_raw_data",
        )
    if (
        patch_plan.status != "source_mapped_deferred"
        or copy_plan.status != "source_mapped_deferred"
        or patch_plan.selected_offset_tag is None
        or patch_plan.selected_offset_value_field_offset is None
        or patch_plan.selected_raw_data_offset is None
        or copy_plan.source_offset is None
        or copy_plan.byte_count is None
        or copy_plan.source_end_offset is None
        or copy_plan.even_padding_byte_count is None
    ):
        return unsupported_offset_fixup_application_contract(
            evidence_ids,
            error="unsupported_panasonic_raw_variant",
        )
    if patch_plan.uses_fixed_offset_padding and fixed_offset_padding_byte_count is None:
        return source_mapped_offset_fixup_application_contract(
            patch_plan,
            copy_plan,
            rewritten_tiff_directory_length=rewritten_tiff_directory_length,
            fixed_offset_padding_byte_count=fixed_offset_padding_byte_count,
            new_raw_data_offset=None,
            error="missing_fixed_offset_padding_length",
            evidence_ids=evidence_ids,
        )
    if rewritten_tiff_directory_length is None:
        return source_mapped_offset_fixup_application_contract(
            patch_plan,
            copy_plan,
            rewritten_tiff_directory_length=rewritten_tiff_directory_length,
            fixed_offset_padding_byte_count=fixed_offset_padding_byte_count,
            new_raw_data_offset=None,
            error="missing_rewritten_tiff_directory_length",
            evidence_ids=evidence_ids,
        )

    padding = fixed_offset_padding_byte_count or 0
    new_raw_data_offset = rewritten_tiff_directory_length + padding
    return source_mapped_offset_fixup_application_contract(
        patch_plan,
        copy_plan,
        rewritten_tiff_directory_length=rewritten_tiff_directory_length,
        fixed_offset_padding_byte_count=fixed_offset_padding_byte_count,
        new_raw_data_offset=new_raw_data_offset,
        error=None,
        evidence_ids=evidence_ids,
    )


def source_mapped_offset_fixup_application_contract(
    patch_plan: PanasonicRawDataOffsetPatchPlan,
    copy_plan: PanasonicRawDataCopyPlan,
    *,
    rewritten_tiff_directory_length: int | None,
    fixed_offset_padding_byte_count: int | None,
    new_raw_data_offset: int | None,
    error: PanasonicRawOffsetFixupError | None,
    evidence_ids: tuple[PanasonicRawEvidenceId, ...],
) -> PanasonicRawOffsetFixupApplicationContract:
    records: list[PanasonicRawOffsetFixupRecord] = []
    if (
        patch_plan.selected_offset_tag is not None
        and patch_plan.selected_offset_value_field_offset is not None
        and patch_plan.selected_raw_data_offset is not None
    ):
        records.append(
            PanasonicRawOffsetFixupRecord(
                kind="primary_raw_data_offset",
                tag_name=patch_plan.selected_offset_tag,
                tag_id=tag_id_for_offset_tag(patch_plan.selected_offset_tag),
                original_value_field_offset=patch_plan.selected_offset_value_field_offset,
                old_value=patch_plan.selected_raw_data_offset,
                new_value=new_raw_data_offset,
                old_basis="old_file_absolute",
                new_basis="new_rewritten_tiff_end",
                requires_writeexif_fixup=True,
                evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE,),
            )
        )
    if (
        patch_plan.updates_strip_offsets_from_raw_data_offset
        and patch_plan.strip_offsets_value_field_offset is not None
        and patch_plan.selected_raw_data_offset is not None
    ):
        records.append(
            PanasonicRawOffsetFixupRecord(
                kind="mirrored_strip_offsets",
                tag_name="StripOffsets",
                tag_id=0x0111,
                original_value_field_offset=patch_plan.strip_offsets_value_field_offset,
                old_value=patch_plan.selected_raw_data_offset,
                new_value=new_raw_data_offset,
                old_basis="old_file_absolute",
                new_basis="new_rewritten_tiff_end",
                requires_writeexif_fixup=True,
                evidence_ids=(WRITE_EXIF_PANASONIC_STRIP_SOURCE,),
            )
        )

    padding_records: list[PanasonicRawOffsetFixupPaddingRecord] = []
    if patch_plan.uses_fixed_offset_padding:
        padding_records.append(
            PanasonicRawOffsetFixupPaddingRecord(
                kind="fixed_offset_padding",
                byte_count=fixed_offset_padding_byte_count,
                output_offset=rewritten_tiff_directory_length,
                evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE,),
            )
        )
    if copy_plan.even_padding_byte_count:
        padding_records.append(
            PanasonicRawOffsetFixupPaddingRecord(
                kind="even_payload_padding",
                byte_count=copy_plan.even_padding_byte_count,
                output_offset=(
                    new_raw_data_offset + copy_plan.byte_count
                    if new_raw_data_offset is not None and copy_plan.byte_count is not None
                    else None
                ),
                evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE,),
            )
        )

    return PanasonicRawOffsetFixupApplicationContract(
        status="source_mapped_deferred",
        can_apply_fixups=False,
        old_raw_data_offset=copy_plan.source_offset,
        old_raw_data_length=copy_plan.byte_count,
        rewritten_tiff_directory_length=rewritten_tiff_directory_length,
        fixed_offset_padding_byte_count=fixed_offset_padding_byte_count,
        new_raw_data_offset=new_raw_data_offset,
        copied_payload_end_offset=copy_plan.source_end_offset,
        fixup_records=tuple(records),
        padding_records=tuple(padding_records),
        error=error,
        evidence_ids=evidence_ids,
    )


def unsupported_offset_fixup_application_contract(
    evidence_ids: tuple[PanasonicRawEvidenceId, ...],
    *,
    error: PanasonicRawOffsetFixupError,
) -> PanasonicRawOffsetFixupApplicationContract:
    return PanasonicRawOffsetFixupApplicationContract(
        status="unsupported",
        can_apply_fixups=False,
        old_raw_data_offset=None,
        old_raw_data_length=None,
        rewritten_tiff_directory_length=None,
        fixed_offset_padding_byte_count=None,
        new_raw_data_offset=None,
        copied_payload_end_offset=None,
        fixup_records=(),
        padding_records=(),
        error=error,
        evidence_ids=evidence_ids,
    )


def unsupported_rewritten_tiff_directory_bytes(
    evidence_ids: tuple[PanasonicRawEvidenceId, ...],
    *,
    error: PanasonicRawRewrittenTiffDirectoryError,
) -> PanasonicRawRewrittenTiffDirectoryBytes:
    return PanasonicRawRewrittenTiffDirectoryBytes(
        status="unsupported",
        can_supply_final_emitter_input=False,
        rewritten_tiff_directory_bytes=None,
        rewritten_tiff_directory_length=None,
        xmp_payload_length=None,
        iptc_payload_length=None,
        modify_date_value=None,
        raw_data_source_offset=None,
        error=error,
        evidence_ids=evidence_ids,
    )


def rw2_raw_entry(data: bytes, entry: IfdEntry, byte_order: TiffByteOrder) -> RawTiffEntry:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        raise ValueError(f"Unsupported RW2 TIFF field type: {entry.field_type}")
    byte_count = field_size * entry.count
    if byte_count <= 4:
        raw_value = entry.value_offset.to_bytes(4, byte_order)[:byte_count]
    else:
        value_end = entry.value_offset + byte_count
        if entry.value_offset < 0 or value_end > len(data):
            raise ValueError(f"Truncated RW2 TIFF value at offset {entry.value_offset}")
        raw_value = data[entry.value_offset : value_end]
    return RawTiffEntry(
        tag_id=entry.tag_id,
        field_type=entry.field_type,
        count=entry.count,
        raw_value=raw_value,
    )


def existing_external_value(entries: tuple[RawTiffEntry, ...], tag_id: int) -> bytes | None:
    entry = raw_entry_by_tag(entries, tag_id)
    if entry is None:
        return None
    return entry.raw_value


def panasonic_rw2_xmp_title_payload(existing_packet: bytes, title: str) -> bytes:
    if existing_packet and existing_packet != empty_xmp_packet():
        return panasonic_rw2_exiftool_padded_xmp_title_packet(title)
    return panasonic_rw2_exiftool_padded_xmp_title_packet(title)


def panasonic_rw2_exiftool_padded_xmp_title_packet(title: str) -> bytes:
    """Render the bounded WriteXMP.pl packet shape used by Panasonic RW2 test 5."""

    escaped_title = escape(title, {"'": "&apos;", '"': "&quot;"})
    packet = (
        "<?xpacket begin='\ufeff' id='W5M0MpCehiHzreSzNTczkc9d'?>\n"
        f"<x:xmpmeta xmlns:x='adobe:ns:meta/' x:xmptk='Image::ExifTool "
        f"{EXIFTOOL_COMPATIBILITY_VERSION_TEXT}'>\n"
        "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>\n"
        "\n"
        " <rdf:Description rdf:about=''\n"
        "  xmlns:dc='http://purl.org/dc/elements/1.1/'>\n"
        "  <dc:title>\n"
        "   <rdf:Alt>\n"
        f"    <rdf:li xml:lang='x-default'>{escaped_title}</rdf:li>\n"
        "   </rdf:Alt>\n"
        "  </dc:title>\n"
        " </rdf:Description>\n"
        "</rdf:RDF>\n"
        "</x:xmpmeta>\n"
    )
    return packet.encode("utf-8") + ((b" " * 100 + b"\n") * 24) + b"<?xpacket end='w'?>"


def panasonic_rw2_iptc_keywords_payload(existing_iptc: bytes, keyword: str) -> bytes:
    payload = apply_iptc_application_write_plan(
        existing_iptc,
        build_iptc_application_write_plan(keywords=(keyword,)),
    )
    padding = (-len(payload)) % 4
    if padding:
        payload += b"\0" * padding
    return payload


def panasonic_rw2_modify_date_entry(value: str, byte_order: TiffByteOrder) -> RawTiffEntry:
    return RawTiffEntry(
        tag_id=PANASONIC_MODIFY_DATE_TAG,
        field_type=TIFF_TYPE_ASCII,
        count=len(value) + 1,
        raw_value=value.encode("ascii") + b"\x00",
    )


def upsert_rw2_entry(
    entries: tuple[RawTiffEntry, ...],
    updated_entry: RawTiffEntry,
) -> tuple[RawTiffEntry, ...]:
    retained = tuple(entry for entry in entries if entry.tag_id != updated_entry.tag_id)
    return tuple(sorted((*retained, updated_entry), key=lambda entry: entry.tag_id))


def encode_rw2_ifd0_directory_bytes(
    source_data: bytes,
    entries: tuple[RawTiffEntry, ...],
    first_ifd_offset: int,
    next_ifd_offset: int,
    raw_data_source_offset: int,
    byte_order: TiffByteOrder,
) -> bytes:
    directory_external_start = first_ifd_offset + 2 + len(entries) * TIFF_IFD_ENTRY_SIZE + 4
    directory, external_values = encode_rw2_directory(
        entries,
        next_ifd_offset,
        directory_external_start,
        byte_order,
    )
    modeled_end = original_rw2_ifd0_modeled_end(source_data, first_ifd_offset, byte_order)
    suffix_start = min(max(modeled_end, directory_external_start), raw_data_source_offset)
    suffix = source_data[suffix_start:raw_data_source_offset]
    return (
        source_data[:2]
        + RW2_TIFF_MAGIC.to_bytes(2, byte_order)
        + first_ifd_offset.to_bytes(4, byte_order)
        + source_data[8:first_ifd_offset]
        + directory
        + external_values
        + suffix
    )


def encode_rw2_directory(
    entries: tuple[RawTiffEntry, ...],
    next_ifd_offset: int,
    external_offset: int,
    byte_order: TiffByteOrder,
) -> tuple[bytes, bytes]:
    encoded_entries: list[bytes] = []
    external_values = bytearray()
    next_external_offset = external_offset
    for entry in entries:
        raw_value = entry.raw_value
        if len(raw_value) <= 4:
            value_field = raw_value.ljust(4, b"\0")
        else:
            if next_external_offset % 2:
                external_values.extend(b"\0")
                next_external_offset += 1
            value_field = next_external_offset.to_bytes(4, byte_order)
            external_values.extend(raw_value)
            next_external_offset += len(raw_value)
        encoded_entries.append(
            entry.tag_id.to_bytes(2, byte_order)
            + entry.field_type.to_bytes(2, byte_order)
            + entry.count.to_bytes(4, byte_order)
            + value_field
        )
    return (
        len(entries).to_bytes(2, byte_order)
        + b"".join(encoded_entries)
        + next_ifd_offset.to_bytes(4, byte_order),
        bytes(external_values),
    )


def original_rw2_ifd0_modeled_end(
    data: bytes,
    first_ifd_offset: int,
    byte_order: TiffByteOrder,
) -> int:
    ifd0 = parse_ifd(data, first_ifd_offset, byte_order)
    modeled_end = first_ifd_offset + 2 + len(ifd0.entries) * TIFF_IFD_ENTRY_SIZE + 4
    for entry in ifd0.entries:
        field_size = TYPE_SIZES.get(entry.field_type)
        if field_size is None:
            continue
        byte_count = field_size * entry.count
        if byte_count > 4:
            modeled_end = max(modeled_end, entry.value_offset + byte_count)
    return modeled_end


def capture_panasonic_rw2_rewritten_offset_field_coordinates(
    rewritten_tiff_directory_bytes: bytes,
    patch_plan: PanasonicRawDataOffsetPatchPlan,
    *,
    byte_order: TiffByteOrder = "little",
) -> tuple[PanasonicRawRewrittenOffsetFieldCoordinate, ...]:
    """Locate WriteExif offsetInfo value positions in rebuilt RW2 TIFF bytes."""

    header = parse_rw2_header(rewritten_tiff_directory_bytes)
    if header is None:
        return ()
    header_byte_order, first_ifd_offset = header
    if header_byte_order != byte_order:
        return ()

    entry_count = read_ifd_entry_count(
        rewritten_tiff_directory_bytes,
        first_ifd_offset,
        byte_order,
    )
    if entry_count is None:
        return ()

    coordinates: list[PanasonicRawRewrittenOffsetFieldCoordinate] = []
    for required in required_rewritten_offset_coordinates(patch_plan):
        tag_id = tag_id_for_offset_tag(required.tag_name)
        value_offset = find_rewritten_ifd0_first_int32_value_offset(
            rewritten_tiff_directory_bytes,
            first_ifd_offset,
            entry_count,
            tag_id,
            byte_order,
        )
        if value_offset is None:
            continue
        coordinates.append(
            PanasonicRawRewrittenOffsetFieldCoordinate(
                kind=required.kind,
                tag_name=required.tag_name,
                rewritten_value_field_offset=value_offset,
            )
        )
    return tuple(coordinates)


def required_rewritten_offset_coordinates(
    patch_plan: PanasonicRawDataOffsetPatchPlan,
) -> tuple[PanasonicRawRewrittenOffsetFieldCoordinate, ...]:
    if patch_plan.selected_offset_tag is None:
        return ()
    coordinates = [
        PanasonicRawRewrittenOffsetFieldCoordinate(
            kind="primary_raw_data_offset",
            tag_name=patch_plan.selected_offset_tag,
            rewritten_value_field_offset=-1,
        )
    ]
    if patch_plan.updates_strip_offsets_from_raw_data_offset:
        coordinates.append(
            PanasonicRawRewrittenOffsetFieldCoordinate(
                kind="mirrored_strip_offsets",
                tag_name="StripOffsets",
                rewritten_value_field_offset=-1,
            )
        )
    return tuple(coordinates)


def has_matching_coordinate(
    coordinate: PanasonicRawRewrittenOffsetFieldCoordinate,
    candidates: tuple[PanasonicRawRewrittenOffsetFieldCoordinate, ...],
) -> bool:
    return any(
        coordinate.kind == candidate.kind and coordinate.tag_name == candidate.tag_name
        for candidate in candidates
    )


def final_emitter_gate(
    code: PanasonicRawDataAppendEmitterGateCode,
    detail: str,
    evidence_ids: tuple[PanasonicRawEvidenceId, ...],
) -> PanasonicRawDataAppendEmitterGate:
    return PanasonicRawDataAppendEmitterGate(
        code=code,
        detail=detail,
        evidence_ids=evidence_ids,
    )


def deferred_final_emitter_contract(
    evidence_ids: tuple[PanasonicRawEvidenceId, ...],
    *,
    error: PanasonicRawFinalEmitterError,
    new_raw_data_offset: int | None,
    gates: tuple[PanasonicRawDataAppendEmitterGate, ...],
) -> PanasonicRawFinalEmitterContract:
    return PanasonicRawFinalEmitterContract(
        status="source_mapped_deferred",
        can_emit_output=False,
        output_bytes=None,
        output_length=None,
        new_raw_data_offset=new_raw_data_offset,
        applied_offset_coordinates=(),
        output_segments=(),
        output_emission_gates=gates,
        error=error,
        evidence_ids=evidence_ids,
    )


def unsupported_final_emitter_contract(
    evidence_ids: tuple[PanasonicRawEvidenceId, ...],
    *,
    error: PanasonicRawFinalEmitterError,
    new_raw_data_offset: int | None = None,
) -> PanasonicRawFinalEmitterContract:
    return PanasonicRawFinalEmitterContract(
        status="unsupported",
        can_emit_output=False,
        output_bytes=None,
        output_length=None,
        new_raw_data_offset=new_raw_data_offset,
        applied_offset_coordinates=(),
        output_segments=(),
        output_emission_gates=(),
        error=error,
        evidence_ids=evidence_ids,
    )


def unsupported_raw_data_append_emitter_contract(
    evidence_ids: tuple[PanasonicRawEvidenceId, ...],
    *,
    error: PanasonicRawDataAppendEmitterError,
) -> PanasonicRawDataAppendEmitterContract:
    return PanasonicRawDataAppendEmitterContract(
        status="unsupported",
        can_emit_output=False,
        output_segments=(),
        output_emission_gates=(),
        old_raw_data_offset=None,
        old_raw_data_length=None,
        copied_payload_end_offset=None,
        even_padding_byte_count=None,
        error=error,
        evidence_ids=evidence_ids,
    )


def unsupported_raw_data_copy_plan(
    evidence_ids: tuple[PanasonicRawEvidenceId, ...],
    *,
    source_offset: int | None = None,
    byte_count: int | None = None,
    source_end_offset: int | None = None,
    error: PanasonicRawDataCopyError,
) -> PanasonicRawDataCopyPlan:
    return PanasonicRawDataCopyPlan(
        status="unsupported",
        can_copy_payload=False,
        source_offset=source_offset,
        byte_count=byte_count,
        source_end_offset=source_end_offset,
        even_padding_byte_count=None,
        requires_deferred_append=False,
        error=error,
        evidence_ids=evidence_ids,
    )


def parse_rw2_header(data: bytes) -> tuple[TiffByteOrder, int] | None:
    if len(data) < 8:
        return None
    if data[:2] == b"II":
        byte_order: TiffByteOrder = "little"
    elif data[:2] == b"MM":
        byte_order = "big"
    else:
        return None
    if read_uint(data, 2, byte_order, 2) != RW2_TIFF_MAGIC:
        return None
    return byte_order, read_uint(data, 4, byte_order, 4)


def read_ifd_entry_count(
    data: bytes,
    ifd_offset: int,
    byte_order: TiffByteOrder,
) -> int | None:
    if ifd_offset < 0 or ifd_offset + 2 > len(data):
        return None
    return read_uint(data, ifd_offset, byte_order, 2)


def parse_ifd0_offset_tags(
    data: bytes,
    ifd_offset: int,
    entry_count: int,
    byte_order: TiffByteOrder,
) -> tuple[PanasonicRawIfdOffsetTag, ...]:
    tags: list[PanasonicRawIfdOffsetTag] = []
    entries_start = ifd_offset + 2
    for index in range(entry_count):
        entry_offset = entries_start + index * TIFF_IFD_ENTRY_SIZE
        if entry_offset + TIFF_IFD_ENTRY_SIZE > len(data):
            break
        tag_id = read_uint(data, entry_offset, byte_order, 2)
        tag_name = PANASONIC_OFFSET_TAGS.get(tag_id)
        if tag_name is None:
            continue
        tiff_type = read_uint(data, entry_offset + 2, byte_order, 2)
        value_count = read_uint(data, entry_offset + 4, byte_order, 4)
        value_field_offset = entry_offset + 8
        tags.append(
            PanasonicRawIfdOffsetTag(
                tag_id=tag_id,
                tag_name=tag_name,
                tiff_type=tiff_type,
                value_count=value_count,
                value_field_offset=value_field_offset,
                values=read_ifd_values(
                    data,
                    value_field_offset,
                    tiff_type,
                    value_count,
                    byte_order,
                ),
            )
        )
    return tuple(tags)


def find_offset_tag(
    offset_tags: tuple[PanasonicRawIfdOffsetTag, ...],
    tag_name: PanasonicRawOffsetTagName,
) -> PanasonicRawIfdOffsetTag | None:
    for tag in offset_tags:
        if tag.tag_name == tag_name:
            return tag
    return None


def find_rewritten_ifd0_first_int32_value_offset(
    data: bytes,
    ifd_offset: int,
    entry_count: int,
    tag_id: int,
    byte_order: TiffByteOrder,
) -> int | None:
    entries_start = ifd_offset + 2
    for index in range(entry_count):
        entry_offset = entries_start + index * TIFF_IFD_ENTRY_SIZE
        if entry_offset + TIFF_IFD_ENTRY_SIZE > len(data):
            return None
        candidate_tag_id = read_uint(data, entry_offset, byte_order, 2)
        if candidate_tag_id != tag_id:
            continue
        tiff_type = read_uint(data, entry_offset + 2, byte_order, 2)
        value_count = read_uint(data, entry_offset + 4, byte_order, 4)
        if tiff_type != 4 or value_count < 1:
            return None
        value_field_offset = entry_offset + 8
        if value_count == 1:
            return value_field_offset
        value_data_offset = read_uint(data, value_field_offset, byte_order, 4)
        if value_data_offset < 0 or value_data_offset + 4 > len(data):
            return None
        return value_data_offset
    return None


def tag_id_for_offset_tag(tag_name: PanasonicRawOffsetTagName) -> int:
    for tag_id, candidate in PANASONIC_OFFSET_TAGS.items():
        if candidate == tag_name:
            return tag_id
    raise ValueError(f"Unsupported Panasonic RAW offset tag: {tag_name}")


def first_offset_value(tag: PanasonicRawIfdOffsetTag | None) -> int | None:
    if tag is None or not tag.values:
        return None
    return tag.values[0]


def read_ifd_values(
    data: bytes,
    value_field_offset: int,
    tiff_type: int,
    value_count: int,
    byte_order: TiffByteOrder,
) -> tuple[int, ...]:
    type_byte_count = TIFF_TYPE_BYTE_COUNTS.get(tiff_type)
    if type_byte_count is None:
        return ()
    total_byte_count = type_byte_count * value_count
    if total_byte_count <= 4:
        value_data_offset = value_field_offset
    else:
        value_data_offset = read_uint(data, value_field_offset, byte_order, 4)
    if value_data_offset < 0 or value_data_offset + total_byte_count > len(data):
        return ()
    if tiff_type == 3:
        return tuple(
            read_uint(data, value_data_offset + index * 2, byte_order, 2)
            for index in range(value_count)
        )
    if tiff_type == 4:
        return tuple(
            read_uint(data, value_data_offset + index * 4, byte_order, 4)
            for index in range(value_count)
        )
    return ()


def panasonic_rw2_mutation_steps() -> tuple[PanasonicRawMutationStep, ...]:
    return (
        PanasonicRawMutationStep(
            kind="validate_rw2_tiff_header",
            description=(
                "Validate Panasonic RAW/RW2/RWL IFD0 before routing through Exif::WriteExif."
            ),
            blockers=("requires_full_tiff_directory_rebuild",),
            evidence_ids=(PANASONIC_RAW_MAIN_SOURCE,),
        ),
        PanasonicRawMutationStep(
            kind="collect_ifd0_image_data_offsets",
            description=(
                "Collect IFD0 StripOffsets, StripByteCounts, and RawDataOffset entries into "
                "the offsetInfo table used by WriteExif."
            ),
            blockers=("requires_offset_fixup_table",),
            evidence_ids=(WRITE_EXIF_PANASONIC_PATCH_SOURCE,),
        ),
        PanasonicRawMutationStep(
            kind="run_panasonic_raw_data_offset_patch",
            description=(
                "Apply PanasonicRaw::PatchRawDataOffset variant checks and RawDataOffset to "
                "StripOffsets remapping before copying image data."
            ),
            blockers=("requires_panasonic_variant_checks", "requires_offset_fixup_table"),
            evidence_ids=(PANASONIC_RAW_OFFSET_PATCH_SOURCE,),
        ),
        PanasonicRawMutationStep(
            kind="rewrite_ifd0_metadata_directories",
            description=(
                "Rebuild IFD0 metadata directories before final image-data offsets are fixed up."
            ),
            blockers=("requires_full_tiff_directory_rebuild",),
            evidence_ids=(PANASONIC_RAW_MAIN_SOURCE,),
        ),
        PanasonicRawMutationStep(
            kind="copy_raw_image_data_after_fixups",
            description=(
                "Preserve the old raw image payload by copying the patched offset/size range "
                "after WriteExif has updated RawDataOffset-driven StripOffsets and fixups."
            ),
            blockers=("requires_offset_fixup_table",),
            evidence_ids=(WRITE_EXIF_RAW_DATA_COPY_SOURCE, WRITE_EXIF_PANASONIC_STRIP_SOURCE),
        ),
    )


def read_uint(
    data: bytes,
    offset: int,
    byte_order: TiffByteOrder,
    width: Literal[2, 4],
) -> int:
    return int.from_bytes(data[offset : offset + width], byte_order)


def unique_blockers(
    steps: tuple[PanasonicRawMutationStep, ...],
) -> tuple[PanasonicRawSafetyBlocker, ...]:
    blockers: list[PanasonicRawSafetyBlocker] = []
    for step in steps:
        for blocker in step.blockers:
            if blocker not in blockers:
                blockers.append(blocker)
    return tuple(blockers)


def unique_evidence_ids(
    references: tuple[PanasonicRawEvidenceId, ...],
) -> tuple[PanasonicRawEvidenceId, ...]:
    unique: list[PanasonicRawEvidenceId] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)
