"""Source-backed Nikon NEF mutation planning.

NEF writes are TIFF writes with Nikon MakerNote and Nikon Capture subdirectory
rewrites layered inside ExifTool's WriteExif flow.  This module only builds a
typed, source-grounded plan and exposes read-only TIFF/MakerNote inspection.
It never performs byte mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.nikon_raw.sources import (
    EXIF_IMAGE_DATA_BYTE_COUNT_SOURCE,
    EXIF_IMAGE_DATA_OFFSET_PAIR_SOURCE,
    EXIF_IPTC_NAA_SOURCE,
    EXIF_TILE_IMAGE_DATA_SOURCE,
    IPTC_CAPTION_ABSTRACT_SOURCE,
    MAKER_NOTES_NIKON_TYPE2_LOCATION_SOURCE,
    NIKON_CAPTURE_MAKERNOTE_SOURCE,
    NIKON_CAPTURE_TAGS_SOURCE,
    NIKON_CAPTURE_WRITE_SOURCE,
    NIKON_PREVIEW_IFD_SOURCE,
    NIKON_PROCESS_SOURCE,
    NIKON_TYPE2_SOURCE,
    WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
    WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
    WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
    WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
    WRITE_IPTC_SOURCE,
    EvidenceId,
    unique_evidence_ids,
)
from exifmodern.formats.nikon_raw.tiff_routing import (
    TIFF_IFD_ENTRY_SIZE,
    TIFF_VALUE_FORMAT_SIZES,
    NikonNefIfdEntry,
    TiffByteOrder,
    collect_nef_ifd_entries,
    find_ifd_long_value,
    find_ifd_value_data_offset,
    find_ifd_value_field,
    first_entry_for_tag,
    parse_tiff_header,
    read_ascii_prefix,
    read_ifd_entries,
    read_ifd_entry_count,
    read_uint,
    tiff_value_data_offset,
)
from exifmodern.formats.raw_family.write_plan import (
    RawFamilyBlockerCode,
    RawFamilyWriteRequestClassification,
    RawFamilyWriteSurface,
    classify_raw_family_golden_request_file,
)
from exifmodern.json_types import JsonObject

type NikonNefMutationPlanStatus = Literal["source_mapped_deferred", "unsupported"]
type NikonNefMutationStepKind = Literal[
    "validate_nef_tiff_header",
    "prescan_nikon_makernote_keys",
    "rewrite_nef_tiff_directories",
    "apply_nikon_makernote_fixups",
    "rewrite_nikon_capture_scalar_entries",
    "rewrite_nikon_capture_iptc_subdirectory",
    "preserve_preview_image_offsets",
    "copy_image_data_after_offset_fixups",
]
type NikonNefPrerequisite = Literal[
    "classic_tiff_header",
    "nikon_type2_makernote",
    "requested_nef_raw_family_route",
    "nikon_capture_data_block",
    "writeexif_offset_tracking",
]
type NikonNefSafetyGate = Literal[
    "defer_without_full_tiff_rebuilder",
    "defer_without_makernote_fixup_application",
    "defer_without_nikon_key_prescan",
    "defer_without_nikon_capture_block_rewriter",
    "defer_without_iptc_subdirectory_rewriter",
    "defer_without_preview_offset_pair_protection",
    "defer_without_image_data_fixups",
]
type NikonNefImageDataLedgerStatus = Literal[
    "source_mapped_deferred",
    "unsupported",
]
type NikonNefImageDataPairKind = Literal[
    "strip_image_data",
    "tile_image_data",
]
type NikonNefImageDataCopyEmitterStatus = Literal[
    "source_mapped_deferred",
    "unsupported",
]
type NikonNefWriteExifOffsetFixupEmissionStatus = Literal[
    "emitted_writeexif_offset_fixup_bytes",
    "unsupported",
]
type NikonNefImageDataCopyStage = Literal["write_later_image_data",]
type NikonNefTiffIptcNaaRebuildStatus = Literal[
    "source_mapped_deferred",
    "unsupported",
]
type NikonNefMakerNoteFixupContractStatus = Literal[
    "source_mapped_deferred",
    "unsupported",
]
type NikonNefMakerNoteFixupApplicationStatus = Literal[
    "source_mapped_deferred",
    "unsupported",
]
type NikonNefMakerNoteFixupApplicationEmissionStatus = Literal[
    "emitted_makernote_fixup_value",
    "unsupported",
]
type NikonNefMakerNoteValueRebuildStatus = Literal[
    "emitted_type2_makernote_value",
    "unsupported",
]
type NikonNefMakerNoteFixupRuleKind = Literal[
    "locate_ifd_before_rewrite",
    "allocate_subdirectory_fixup",
    "restore_existing_header_before_subdir",
    "relative_offset_shift",
    "absolute_offset_shift",
    "preview_image_marker_fixup",
]
type NikonNefMakerNoteFixupApplicationKind = Literal[
    "relative_offset_shift",
    "absolute_offset_shift",
    "preview_marker_carry_forward",
]
type NikonNefFinalOutputMaterializationStatus = Literal[
    "blocked_on_writeexif_value_positions",
    "emitted_parent_tiff_value_positions",
    "unsupported",
]
type NikonNefParentTiffValuePositionMaterializationStatus = Literal[
    "emitted_parent_tiff_value_positions",
    "unsupported",
]
type NikonNefNativePromotionStatus = Literal[
    "native_output_deferred",
    "unsupported",
]
type NikonNefNikonCaptureDiscoveryStatus = Literal[
    "source_mapped_deferred",
    "unsupported",
]
type NikonNefFinalOutputComponentKind = Literal[
    "rebuilt_tiff_directory_bytes",
    "nikon_type2_makernote_fixups",
    "nikon_capture_block_payload",
    "iptc_subdirectory_payload",
    "image_data_copy_records",
    "offset_value_position_fixups",
]
type NikonNefRequestedInnerPayloadKind = Literal[
    "nikon_capture_scalar_payload",
    "nikon_capture_iptc_payload",
    "nef_tiff_iptc_naa_payload",
]

EXIF_IFD_POINTER_TAG = 0x8769
MAKER_NOTE_TAG = 0x927C
SUB_IFD_POINTER_TAG = 0x014A
STRIP_OFFSETS_TAG = 0x0111
STRIP_BYTE_COUNTS_TAG = 0x0117
TILE_OFFSETS_TAG = 0x0144
TILE_BYTE_COUNTS_TAG = 0x0145
IPTC_NAA_TAG = 0x83BB
NIKON_MAKERNOTE_TYPE2_SIGNATURE = b"Nikon\x00\x02"
NIKON_MAKERNOTE_TYPE2_TIFF_HEADER_OFFSET = 10
NIKON_CAPTURE_MAGIC = 0x7A86A940
NIKON_CAPTURE_HEADER_SIZE = 22
NIKON_CAPTURE_FIXED_HEADER_SIZE = 18
NIKON_CAPTURE_ENTRY_PREFIX_SIZE = 18
NIKON_CAPTURE_ENTRY_SIZE_BIAS = 4
NIKON_CAPTURE_IPTC_TAG_ID = 0x9EF5F6E0
NIKON_NEF_NATIVE_ACTION = "run_modern_nikon_nef_native_writer"


@dataclass(frozen=True)
class NikonNefTiffHeaderSummary:
    byte_order: TiffByteOrder
    tiff_magic: int
    first_ifd_offset: int
    ifd0_entry_count: int | None
    exif_ifd_offset: int | None
    maker_note_offset: int | None
    maker_note_signature: str | None

    def to_json(self) -> JsonObject:
        return {
            "byte_order": self.byte_order,
            "exif_ifd_offset": self.exif_ifd_offset,
            "first_ifd_offset": self.first_ifd_offset,
            "ifd0_entry_count": self.ifd0_entry_count,
            "maker_note_offset": self.maker_note_offset,
            "maker_note_signature": self.maker_note_signature,
            "tiff_magic": self.tiff_magic,
        }


@dataclass(frozen=True)
class NikonNefRequestedMutation:
    requested_tag: str
    requested_value: str
    generic_surfaces: tuple[RawFamilyWriteSurface, ...]
    generic_blockers: tuple[RawFamilyBlockerCode, ...]

    def to_json(self) -> JsonObject:
        return {
            "generic_blockers": list(self.generic_blockers),
            "generic_surfaces": list(self.generic_surfaces),
            "requested_tag": self.requested_tag,
            "requested_value": self.requested_value,
        }


@dataclass(frozen=True)
class NikonNefByteRange:
    start_offset: int
    end_offset: int

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset

    def to_json(self) -> JsonObject:
        return {
            "end_offset": self.end_offset,
            "length": self.length,
            "start_offset": self.start_offset,
        }


@dataclass(frozen=True)
class NikonNefMakerNoteDirectoryLocation:
    byte_order: TiffByteOrder
    maker_note_value_range: NikonNefByteRange
    tiff_header_range: NikonNefByteRange
    tiff_base_offset: int
    ifd_offset: int
    ifd_entry_count: int
    ifd_entry_table_range: NikonNefByteRange
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_order": self.byte_order,
            "ifd_entry_count": self.ifd_entry_count,
            "ifd_entry_table_range": self.ifd_entry_table_range.to_json(),
            "ifd_offset": self.ifd_offset,
            "maker_note_value_range": self.maker_note_value_range.to_json(),
            "tiff_base_offset": self.tiff_base_offset,
            "tiff_header_range": self.tiff_header_range.to_json(),
        }


@dataclass(frozen=True)
class NikonNefNikonCaptureMakerNoteEntry:
    tag_id: int
    format_id: int
    count: int
    entry_range: NikonNefByteRange
    value_field_offset: int
    value_range: NikonNefByteRange
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "count": self.count,
            "entry_range": self.entry_range.to_json(),
            "format_id": self.format_id,
            "tag_id": self.tag_id,
            "tag_id_hex": f"0x{self.tag_id:04x}",
            "value_field_offset": self.value_field_offset,
            "value_range": self.value_range.to_json(),
        }


@dataclass(frozen=True)
class NikonNefNikonCapturePayloadEntry:
    tag_id: int
    tag_name: str | None
    index: int
    entry_range: NikonNefByteRange
    value_range: NikonNefByteRange
    size_word_offset: int
    size_word_value: int
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "entry_range": self.entry_range.to_json(),
            "index": self.index,
            "size_word_offset": self.size_word_offset,
            "size_word_value": self.size_word_value,
            "tag_id": self.tag_id,
            "tag_id_hex": f"0x{self.tag_id:08x}",
            "tag_name": self.tag_name,
            "value_range": self.value_range.to_json(),
        }


@dataclass(frozen=True)
class NikonNefNikonCaptureDiscoveryPlan:
    status: NikonNefNikonCaptureDiscoveryStatus
    can_supply_existing_capture_data: bool
    can_supply_existing_iptc_entry: bool
    maker_note_directory: NikonNefMakerNoteDirectoryLocation | None
    capture_entry: NikonNefNikonCaptureMakerNoteEntry | None
    iptc_entry: NikonNefNikonCapturePayloadEntry | None
    blockers: tuple[str, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "can_supply_existing_capture_data": self.can_supply_existing_capture_data,
            "can_supply_existing_iptc_entry": self.can_supply_existing_iptc_entry,
            "capture_entry": (
                self.capture_entry.to_json() if self.capture_entry is not None else None
            ),
            "iptc_entry": self.iptc_entry.to_json() if self.iptc_entry is not None else None,
            "maker_note_directory": (
                self.maker_note_directory.to_json()
                if self.maker_note_directory is not None
                else None
            ),
            "status": self.status,
        }


@dataclass(frozen=True)
class NikonNefImageDataSegment:
    offset: int
    byte_count: int
    in_bounds: bool

    def to_json(self) -> JsonObject:
        return {
            "byte_count": self.byte_count,
            "in_bounds": self.in_bounds,
            "offset": self.offset,
        }


@dataclass(frozen=True)
class NikonNefImageDataPair:
    ifd_name: str
    kind: NikonNefImageDataPairKind
    offset_tag: int
    byte_count_tag: int
    offset_value_field_offset: int
    byte_count_value_field_offset: int
    offset_count: int
    byte_count_count: int
    counts_match: bool
    all_segments_in_bounds: bool
    copy_deferred_by_writeexif: bool
    segments: tuple[NikonNefImageDataSegment, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "all_segments_in_bounds": self.all_segments_in_bounds,
            "byte_count_count": self.byte_count_count,
            "byte_count_tag": self.byte_count_tag,
            "byte_count_tag_hex": f"0x{self.byte_count_tag:04x}",
            "byte_count_value_field_offset": self.byte_count_value_field_offset,
            "copy_deferred_by_writeexif": self.copy_deferred_by_writeexif,
            "counts_match": self.counts_match,
            "ifd_name": self.ifd_name,
            "kind": self.kind,
            "offset_count": self.offset_count,
            "offset_tag": self.offset_tag,
            "offset_tag_hex": f"0x{self.offset_tag:04x}",
            "offset_value_field_offset": self.offset_value_field_offset,
            "segments": [segment.to_json() for segment in self.segments],
        }


@dataclass(frozen=True)
class NikonNefImageDataPreservationPlan:
    status: NikonNefImageDataLedgerStatus
    can_preserve_image_data: bool
    scanned_ifds: tuple[str, ...]
    pairs: tuple[NikonNefImageDataPair, ...]
    blockers: tuple[str, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "can_preserve_image_data": self.can_preserve_image_data,
            "pairs": [pair.to_json() for pair in self.pairs],
            "scanned_ifds": list(self.scanned_ifds),
            "status": self.status,
        }


@dataclass(frozen=True)
class NikonNefImageDataCopyRecord:
    copy_order: int
    ifd_name: str
    kind: NikonNefImageDataPairKind
    stage: NikonNefImageDataCopyStage
    segment_index: int
    source_offset: int
    byte_count: int
    pad_byte_required: bool
    source_in_bounds: bool
    offset_value_field_offset: int
    byte_count_value_field_offset: int
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_count": self.byte_count,
            "byte_count_value_field_offset": self.byte_count_value_field_offset,
            "copy_order": self.copy_order,
            "ifd_name": self.ifd_name,
            "kind": self.kind,
            "offset_value_field_offset": self.offset_value_field_offset,
            "pad_byte_required": self.pad_byte_required,
            "segment_index": self.segment_index,
            "source_in_bounds": self.source_in_bounds,
            "source_offset": self.source_offset,
            "stage": self.stage,
        }


@dataclass(frozen=True)
class NikonNefImageDataCopyEmitter:
    status: NikonNefImageDataCopyEmitterStatus
    can_emit_bytes: bool
    records: tuple[NikonNefImageDataCopyRecord, ...]
    output_bytes: bytes | None
    output_gates: tuple[NikonNefSafetyGate, ...]
    blockers: tuple[str, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def total_byte_count(self) -> int:
        return sum(record.byte_count for record in self.records)

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "can_emit_bytes": self.can_emit_bytes,
            "output_available": self.output_bytes is not None,
            "output_length": len(self.output_bytes) if self.output_bytes is not None else None,
            "output_gates": list(self.output_gates),
            "record_count": self.record_count,
            "records": [record.to_json() for record in self.records],
            "status": self.status,
            "total_byte_count": self.total_byte_count,
        }


@dataclass(frozen=True)
class NikonNefWriteExifOffsetFixupRecord:
    copy_order: int
    ifd_name: str
    kind: NikonNefImageDataPairKind
    offset_value_field_offset: int
    byte_count_value_field_offset: int
    source_offset: int
    old_byte_count: int
    new_offset: int
    new_byte_count: int
    pad_byte_required: bool
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_count_value_field_offset": self.byte_count_value_field_offset,
            "copy_order": self.copy_order,
            "ifd_name": self.ifd_name,
            "kind": self.kind,
            "new_byte_count": self.new_byte_count,
            "new_offset": self.new_offset,
            "offset_value_field_offset": self.offset_value_field_offset,
            "old_byte_count": self.old_byte_count,
            "pad_byte_required": self.pad_byte_required,
            "source_offset": self.source_offset,
        }


@dataclass(frozen=True)
class NikonNefWriteExifOffsetFixupEmission:
    status: NikonNefWriteExifOffsetFixupEmissionStatus
    patched_tiff_bytes: bytes | None
    image_data_bytes: bytes | None
    records: tuple[NikonNefWriteExifOffsetFixupRecord, ...]
    remaining_blockers: tuple[str, ...]
    unsupported_reason: str | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def record_count(self) -> int:
        return len(self.records)

    def to_json(self) -> JsonObject:
        return {
            "image_data_bytes_available": self.image_data_bytes is not None,
            "image_data_length": (
                len(self.image_data_bytes) if self.image_data_bytes is not None else None
            ),
            "patched_tiff_bytes_available": self.patched_tiff_bytes is not None,
            "patched_tiff_length": (
                len(self.patched_tiff_bytes) if self.patched_tiff_bytes is not None else None
            ),
            "record_count": self.record_count,
            "records": [record.to_json() for record in self.records],
            "remaining_blockers": list(self.remaining_blockers),
            "status": self.status,
            "unsupported_reason": self.unsupported_reason,
        }


@dataclass(frozen=True)
class NikonNefTiffIptcNaaEntry:
    ifd_name: str
    tag_id: int
    format_id: int
    count: int
    entry_range: NikonNefByteRange
    value_field_offset: int
    value_range: NikonNefByteRange
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "count": self.count,
            "entry_range": self.entry_range.to_json(),
            "format_id": self.format_id,
            "ifd_name": self.ifd_name,
            "tag_id": self.tag_id,
            "tag_id_hex": f"0x{self.tag_id:04x}",
            "value_field_offset": self.value_field_offset,
            "value_range": self.value_range.to_json(),
        }


@dataclass(frozen=True)
class NikonNefTiffIptcNaaRebuildPlan:
    status: NikonNefTiffIptcNaaRebuildStatus
    can_emit_payload: bool
    iptc_naa_entry: NikonNefTiffIptcNaaEntry | None
    requested_caption_abstract: str | None
    rebuilt_payload: bytes | None
    planned_count: int | None
    planned_padding_length: int | None
    blockers: tuple[str, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "can_emit_payload": self.can_emit_payload,
            "emitted_size": len(self.rebuilt_payload) if self.rebuilt_payload is not None else None,
            "iptc_naa_entry": (
                self.iptc_naa_entry.to_json() if self.iptc_naa_entry is not None else None
            ),
            "planned_count": self.planned_count,
            "planned_padding_length": self.planned_padding_length,
            "rebuilt_payload_available": self.rebuilt_payload is not None,
            "requested_caption_abstract": self.requested_caption_abstract,
            "status": self.status,
        }


@dataclass(frozen=True)
class NikonNefMakerNoteFixupRule:
    kind: NikonNefMakerNoteFixupRuleKind
    description: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "description": self.description,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class NikonNefMakerNoteFixupContract:
    status: NikonNefMakerNoteFixupContractStatus
    can_apply_fixups: bool
    maker_note_signature: str | None
    rules: tuple[NikonNefMakerNoteFixupRule, ...]
    blockers: tuple[str, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "can_apply_fixups": self.can_apply_fixups,
            "maker_note_signature": self.maker_note_signature,
            "rules": [rule.to_json() for rule in self.rules],
            "status": self.status,
        }


@dataclass(frozen=True)
class NikonNefMakerNoteFixupPointer:
    pointer_name: str
    pointer_offset: int
    original_value: int
    data_tag: str | None = None

    def to_json(self) -> JsonObject:
        return {
            "data_tag": self.data_tag,
            "original_value": self.original_value,
            "pointer_name": self.pointer_name,
            "pointer_offset": self.pointer_offset,
        }


@dataclass(frozen=True)
class NikonNefMakerNotePreviewOffsetPair:
    data_tag: str
    start_tag: int
    length_tag: int
    start_pointer_offset: int
    length_pointer_offset: int
    start_value: int
    length_value: int
    marker_carried_forward: bool
    protected_by_preview_ifd: bool
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "data_tag": self.data_tag,
            "length_pointer_offset": self.length_pointer_offset,
            "length_tag": self.length_tag,
            "length_tag_hex": f"0x{self.length_tag:04x}",
            "length_value": self.length_value,
            "marker_carried_forward": self.marker_carried_forward,
            "protected_by_preview_ifd": self.protected_by_preview_ifd,
            "start_pointer_offset": self.start_pointer_offset,
            "start_tag": self.start_tag,
            "start_tag_hex": f"0x{self.start_tag:04x}",
            "start_value": self.start_value,
        }


@dataclass(frozen=True)
class NikonNefMakerNoteFixupApplicationContext:
    maker_note_header_length: int
    maker_note_value_buffer_offset: int
    value_data_position: int
    maker_note_value_pointer: int
    tiff_base: int
    original_maker_note_base: int
    fixed_by: int = 0
    relative_offsets: bool = False
    preview_present: bool = False
    preview_no_base_shift: bool = False

    @property
    def base_shift(self) -> int:
        if self.relative_offsets:
            return (
                self.value_data_position
                + self.maker_note_value_pointer
                + self.tiff_base
                - self.original_maker_note_base
            )
        return self.tiff_base - self.original_maker_note_base

    @property
    def applied_shift(self) -> int:
        if self.relative_offsets:
            return self.base_shift
        return self.base_shift + self.fixed_by

    @property
    def application_start(self) -> int:
        if self.relative_offsets:
            return self.maker_note_header_length
        return self.maker_note_value_buffer_offset + self.maker_note_header_length

    @property
    def deferred_value_fixup_start(self) -> int:
        return self.application_start + self.maker_note_value_buffer_offset

    @property
    def preview_base_shift(self) -> int | None:
        if not self.preview_present:
            return None
        if self.preview_no_base_shift and not self.relative_offsets:
            return None
        return self.base_shift

    def to_json(self) -> JsonObject:
        return {
            "application_start": self.application_start,
            "applied_shift": self.applied_shift,
            "base_shift": self.base_shift,
            "deferred_value_fixup_start": self.deferred_value_fixup_start,
            "fixed_by": self.fixed_by,
            "maker_note_header_length": self.maker_note_header_length,
            "maker_note_value_buffer_offset": self.maker_note_value_buffer_offset,
            "maker_note_value_pointer": self.maker_note_value_pointer,
            "original_maker_note_base": self.original_maker_note_base,
            "preview_base_shift": self.preview_base_shift,
            "preview_no_base_shift": self.preview_no_base_shift,
            "preview_present": self.preview_present,
            "relative_offsets": self.relative_offsets,
            "tiff_base": self.tiff_base,
            "value_data_position": self.value_data_position,
        }


@dataclass(frozen=True)
class NikonNefMakerNoteFixupApplicationRecord:
    kind: NikonNefMakerNoteFixupApplicationKind
    pointer_name: str
    data_tag: str | None
    pointer_offset: int
    application_start: int
    shift: int
    original_value: int
    shifted_value: int
    in_planned_value_bounds: bool
    deferred_to_value_fixups: bool
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "application_start": self.application_start,
            "data_tag": self.data_tag,
            "deferred_to_value_fixups": self.deferred_to_value_fixups,
            "in_planned_value_bounds": self.in_planned_value_bounds,
            "kind": self.kind,
            "original_value": self.original_value,
            "pointer_name": self.pointer_name,
            "pointer_offset": self.pointer_offset,
            "shift": self.shift,
            "shifted_value": self.shifted_value,
        }


@dataclass(frozen=True)
class NikonNefMakerNoteFixupApplicationPlan:
    status: NikonNefMakerNoteFixupApplicationStatus
    can_apply_to_nef_bytes: bool
    context: NikonNefMakerNoteFixupApplicationContext | None
    records: tuple[NikonNefMakerNoteFixupApplicationRecord, ...]
    preview_offset_pairs: tuple[NikonNefMakerNotePreviewOffsetPair, ...]
    output_gates: tuple[NikonNefSafetyGate, ...]
    blockers: tuple[str, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def record_count(self) -> int:
        return len(self.records)

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "can_apply_to_nef_bytes": self.can_apply_to_nef_bytes,
            "context": self.context.to_json() if self.context is not None else None,
            "output_gates": list(self.output_gates),
            "preview_offset_pairs": [pair.to_json() for pair in self.preview_offset_pairs],
            "record_count": self.record_count,
            "records": [record.to_json() for record in self.records],
            "status": self.status,
        }


@dataclass(frozen=True)
class NikonNefMakerNoteFixupApplicationEmission:
    status: NikonNefMakerNoteFixupApplicationEmissionStatus
    plan: NikonNefMakerNoteFixupApplicationPlan
    applied_maker_note_value: bytes | None
    remaining_blockers: tuple[str, ...]
    unsupported_reason: str | None
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "applied_maker_note_value_available": self.applied_maker_note_value is not None,
            "emitted_size": (
                len(self.applied_maker_note_value)
                if self.applied_maker_note_value is not None
                else None
            ),
            "plan": self.plan.to_json(),
            "remaining_blockers": list(self.remaining_blockers),
            "status": self.status,
            "unsupported_reason": self.unsupported_reason,
        }


@dataclass(frozen=True)
class NikonNefMakerNoteValuePositionPatch:
    tag_id: int
    tag_name: str
    count_field_offset: int
    value_field_offset: int
    old_count: int
    new_count: int
    old_value_offset: int
    new_value_offset: int
    new_value_range: NikonNefByteRange
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "count_field_offset": self.count_field_offset,
            "new_count": self.new_count,
            "new_value_offset": self.new_value_offset,
            "new_value_range": self.new_value_range.to_json(),
            "old_count": self.old_count,
            "old_value_offset": self.old_value_offset,
            "tag_id": self.tag_id,
            "tag_id_hex": f"0x{self.tag_id:04x}",
            "tag_name": self.tag_name,
            "value_field_offset": self.value_field_offset,
        }


@dataclass(frozen=True)
class NikonNefMakerNoteValueRebuildEmission:
    status: NikonNefMakerNoteValueRebuildStatus
    rebuilt_maker_note_value: bytes | None
    maker_note_value_range: NikonNefByteRange | None
    capture_value_patch: NikonNefMakerNoteValuePositionPatch | None
    maker_note_fixup_pointers: tuple[NikonNefMakerNoteFixupPointer, ...]
    remaining_blockers: tuple[str, ...]
    unsupported_reason: str | None
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "capture_value_patch": (
                self.capture_value_patch.to_json() if self.capture_value_patch is not None else None
            ),
            "emitted_size": (
                len(self.rebuilt_maker_note_value)
                if self.rebuilt_maker_note_value is not None
                else None
            ),
            "maker_note_value_range": (
                self.maker_note_value_range.to_json()
                if self.maker_note_value_range is not None
                else None
            ),
            "maker_note_fixup_pointers": [
                pointer.to_json() for pointer in self.maker_note_fixup_pointers
            ],
            "rebuilt_maker_note_value_available": self.rebuilt_maker_note_value is not None,
            "remaining_blockers": list(self.remaining_blockers),
            "status": self.status,
            "unsupported_reason": self.unsupported_reason,
        }


@dataclass(frozen=True)
class NikonNefFinalOutputComponent:
    kind: NikonNefFinalOutputComponentKind
    ready_for_materialization: bool
    blocker: str | None
    description: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocker": self.blocker,
            "description": self.description,
            "kind": self.kind,
            "ready_for_materialization": self.ready_for_materialization,
        }


@dataclass(frozen=True)
class NikonNefFinalOutputMaterializationPlan:
    status: NikonNefFinalOutputMaterializationStatus
    can_materialize_output: bool
    components: tuple[NikonNefFinalOutputComponent, ...]
    remaining_blockers: tuple[str, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_materialize_output": self.can_materialize_output,
            "components": [component.to_json() for component in self.components],
            "remaining_blockers": list(self.remaining_blockers),
            "status": self.status,
        }


@dataclass(frozen=True)
class NikonNefParentTiffValuePositionMaterialization:
    status: NikonNefParentTiffValuePositionMaterializationStatus
    output_bytes: bytes | None
    maker_note_value_field_offset: int | None
    maker_note_count_field_offset: int | None
    maker_note_output_offset: int | None
    maker_note_output_count: int | None
    iptc_naa_value_field_offset: int | None
    iptc_naa_count_field_offset: int | None
    iptc_naa_output_offset: int | None
    iptc_naa_output_count: int | None
    image_data_start_offset: int | None
    offset_fixup_emission: NikonNefWriteExifOffsetFixupEmission | None
    remaining_blockers: tuple[str, ...]
    unsupported_reason: str | None
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "image_data_start_offset": self.image_data_start_offset,
            "iptc_naa_count_field_offset": self.iptc_naa_count_field_offset,
            "iptc_naa_output_count": self.iptc_naa_output_count,
            "iptc_naa_output_offset": self.iptc_naa_output_offset,
            "iptc_naa_value_field_offset": self.iptc_naa_value_field_offset,
            "maker_note_count_field_offset": self.maker_note_count_field_offset,
            "maker_note_output_count": self.maker_note_output_count,
            "maker_note_output_offset": self.maker_note_output_offset,
            "maker_note_value_field_offset": self.maker_note_value_field_offset,
            "offset_fixup_emission": (
                self.offset_fixup_emission.to_json()
                if self.offset_fixup_emission is not None
                else None
            ),
            "output_available": self.output_bytes is not None,
            "output_length": len(self.output_bytes) if self.output_bytes is not None else None,
            "remaining_blockers": list(self.remaining_blockers),
            "status": self.status,
            "unsupported_reason": self.unsupported_reason,
        }


@dataclass(frozen=True)
class NikonNefRequestedInnerPayload:
    kind: NikonNefRequestedInnerPayloadKind
    requested_tag: str
    requested_value: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "requested_tag": self.requested_tag,
            "requested_value": self.requested_value,
        }


@dataclass(frozen=True)
class NikonNefNativePromotionPlan:
    status: NikonNefNativePromotionStatus
    can_promote_native: bool
    action: str
    raw_family_request_id: str | None
    requested_inner_payloads: tuple[NikonNefRequestedInnerPayload, ...]
    final_output_materialization: NikonNefFinalOutputMaterializationPlan
    remaining_blockers: tuple[str, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "can_promote_native": self.can_promote_native,
            "final_output_materialization": self.final_output_materialization.to_json(),
            "raw_family_request_id": self.raw_family_request_id,
            "remaining_blockers": list(self.remaining_blockers),
            "requested_inner_payloads": [
                requested_payload.to_json() for requested_payload in self.requested_inner_payloads
            ],
            "status": self.status,
        }


@dataclass(frozen=True)
class NikonNefMutationStep:
    kind: NikonNefMutationStepKind
    description: str
    prerequisites: tuple[NikonNefPrerequisite, ...]
    safety_gates: tuple[NikonNefSafetyGate, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "description": self.description,
            "kind": self.kind,
            "prerequisites": list(self.prerequisites),
            "safety_gates": list(self.safety_gates),
        }


@dataclass(frozen=True)
class NikonNefMutationPlan:
    status: NikonNefMutationPlanStatus
    can_mutate: bool
    raw_family_request_id: str | None
    header: NikonNefTiffHeaderSummary | None
    maker_note_fixup_contract: NikonNefMakerNoteFixupContract | None
    nikon_capture_discovery: NikonNefNikonCaptureDiscoveryPlan | None
    image_data_preservation: NikonNefImageDataPreservationPlan | None
    tiff_iptc_naa_rebuild: NikonNefTiffIptcNaaRebuildPlan | None
    final_output_materialization: NikonNefFinalOutputMaterializationPlan | None
    native_promotion: NikonNefNativePromotionPlan | None
    requested_mutations: tuple[NikonNefRequestedMutation, ...]
    steps: tuple[NikonNefMutationStep, ...]
    safety_gates: tuple[NikonNefSafetyGate, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_mutate": self.can_mutate,
            "header": self.header.to_json() if self.header is not None else None,
            "image_data_preservation": (
                self.image_data_preservation.to_json()
                if self.image_data_preservation is not None
                else None
            ),
            "tiff_iptc_naa_rebuild": (
                self.tiff_iptc_naa_rebuild.to_json()
                if self.tiff_iptc_naa_rebuild is not None
                else None
            ),
            "final_output_materialization": (
                self.final_output_materialization.to_json()
                if self.final_output_materialization is not None
                else None
            ),
            "maker_note_fixup_contract": (
                self.maker_note_fixup_contract.to_json()
                if self.maker_note_fixup_contract is not None
                else None
            ),
            "nikon_capture_discovery": (
                self.nikon_capture_discovery.to_json()
                if self.nikon_capture_discovery is not None
                else None
            ),
            "native_promotion": (
                self.native_promotion.to_json() if self.native_promotion is not None else None
            ),
            "raw_family_request_id": self.raw_family_request_id,
            "requested_mutations": [
                requested_mutation.to_json() for requested_mutation in self.requested_mutations
            ],
            "safety_gates": list(self.safety_gates),
            "status": self.status,
            "steps": [step.to_json() for step in self.steps],
        }


def load_nikon_nef_golden_mutation_plan(
    request_path: Path,
    data: bytes,
) -> NikonNefMutationPlan:
    return build_nikon_nef_mutation_plan(
        data,
        classify_raw_family_golden_request_file(request_path),
    )


def build_nikon_nef_mutation_plan(
    data: bytes,
    raw_family_classification: RawFamilyWriteRequestClassification | None = None,
) -> NikonNefMutationPlan:
    header = inspect_nef_tiff_header(data)
    maker_note_fixup_contract = (
        build_nikon_nef_makernote_fixup_contract(header) if header is not None else None
    )
    nikon_capture_discovery = (
        build_nikon_nef_nikon_capture_discovery_plan(data) if header is not None else None
    )
    image_data_preservation = (
        build_nikon_nef_image_data_preservation_plan(data) if header is not None else None
    )
    image_data_copy_emitter = (
        build_nikon_nef_image_data_copy_emitter(data, allow_output_emission=True)
        if header is not None
        else None
    )
    requested_caption_abstract = requested_nef_caption_abstract(raw_family_classification)
    tiff_iptc_naa_rebuild = (
        build_nikon_nef_tiff_iptc_naa_rebuild_plan(data, requested_caption_abstract)
        if header is not None
        else None
    )
    final_output_materialization = (
        build_nikon_nef_final_output_materialization_plan(
            maker_note_fixup_contract,
            image_data_copy_emitter,
            nikon_capture_block_payload_available=True,
            iptc_subdirectory_payload_available=True,
            maker_note_fixup_applier_available=True,
            maker_note_fixup_pointer_records_available=(
                nikon_capture_discovery is not None
                and nikon_capture_discovery.can_supply_existing_capture_data
            ),
            offset_value_position_fixups_available=(
                image_data_copy_emitter is not None and image_data_copy_emitter.can_emit_bytes
            ),
        )
        if header is not None
        else None
    )
    requested_mutations = requested_mutations_from_raw_family(raw_family_classification)
    native_promotion = (
        build_nikon_nef_native_promotion_plan(
            raw_family_classification,
            maker_note_fixup_contract,
            image_data_copy_emitter,
            nikon_capture_discovery,
            tiff_iptc_naa_payload_available=(
                tiff_iptc_naa_rebuild is not None and tiff_iptc_naa_rebuild.can_emit_payload
            ),
        )
        if header is not None
        else None
    )
    steps = nikon_nef_mutation_steps() if header is not None else ()
    status: NikonNefMutationPlanStatus = (
        "source_mapped_deferred"
        if header is not None and raw_family_classification_is_nef(raw_family_classification)
        else "unsupported"
    )
    return NikonNefMutationPlan(
        status=status,
        can_mutate=False,
        raw_family_request_id=(
            raw_family_classification.request_id if raw_family_classification is not None else None
        ),
        header=header,
        maker_note_fixup_contract=maker_note_fixup_contract,
        nikon_capture_discovery=nikon_capture_discovery,
        image_data_preservation=image_data_preservation,
        tiff_iptc_naa_rebuild=tiff_iptc_naa_rebuild,
        final_output_materialization=final_output_materialization,
        native_promotion=native_promotion,
        requested_mutations=requested_mutations,
        steps=steps,
        safety_gates=unique_safety_gates(steps),
        evidence_ids=plan_evidence_ids(raw_family_classification),
    )


def inspect_nef_tiff_header(data: bytes) -> NikonNefTiffHeaderSummary | None:
    header = parse_tiff_header(data)
    if header is None:
        return None
    byte_order, tiff_magic, first_ifd_offset = header
    if tiff_magic != 42:
        return None
    ifd0_entry_count = read_ifd_entry_count(data, first_ifd_offset, byte_order)
    exif_ifd_offset = find_ifd_long_value(
        data,
        first_ifd_offset,
        ifd0_entry_count,
        byte_order,
        EXIF_IFD_POINTER_TAG,
    )
    exif_entry_count = (
        read_ifd_entry_count(data, exif_ifd_offset, byte_order)
        if exif_ifd_offset is not None
        else None
    )
    maker_note_offset = (
        find_ifd_value_data_offset(
            data,
            exif_ifd_offset,
            exif_entry_count,
            byte_order,
            MAKER_NOTE_TAG,
        )
        if exif_ifd_offset is not None
        else None
    )
    return NikonNefTiffHeaderSummary(
        byte_order=byte_order,
        tiff_magic=tiff_magic,
        first_ifd_offset=first_ifd_offset,
        ifd0_entry_count=ifd0_entry_count,
        exif_ifd_offset=exif_ifd_offset,
        maker_note_offset=maker_note_offset,
        maker_note_signature=read_ascii_prefix(data, maker_note_offset, 10),
    )


def build_nikon_nef_nikon_capture_discovery_plan(
    data: bytes,
) -> NikonNefNikonCaptureDiscoveryPlan:
    evidence_ids = nikon_capture_discovery_evidence_ids()
    header = inspect_nef_tiff_header(data)
    if header is None:
        return unsupported_nikon_capture_discovery_plan(
            "requires_classic_tiff_header",
            evidence_ids,
        )
    maker_note_directory = locate_nikon_type2_makernote_ifd(data, header)
    if maker_note_directory is None:
        return unsupported_nikon_capture_discovery_plan(
            "requires_nikon_type2_makernote_ifd",
            evidence_ids,
        )

    capture_entry = find_nikon_capture_makernote_entry(data, maker_note_directory)
    if capture_entry is None:
        return NikonNefNikonCaptureDiscoveryPlan(
            status="unsupported",
            can_supply_existing_capture_data=False,
            can_supply_existing_iptc_entry=False,
            maker_note_directory=maker_note_directory,
            capture_entry=None,
            iptc_entry=None,
            blockers=("requires_existing_nikon_capture_data_payload",),
            evidence_ids=evidence_ids,
        )

    iptc_entry = find_nikon_capture_iptc_payload_entry(data, capture_entry.value_range)
    blockers: list[str] = []
    if iptc_entry is None:
        blockers.append("requires_existing_nikon_capture_iptc_entry")
    return NikonNefNikonCaptureDiscoveryPlan(
        status="source_mapped_deferred" if not blockers else "unsupported",
        can_supply_existing_capture_data=True,
        can_supply_existing_iptc_entry=iptc_entry is not None,
        maker_note_directory=maker_note_directory,
        capture_entry=capture_entry,
        iptc_entry=iptc_entry,
        blockers=tuple(blockers),
        evidence_ids=evidence_ids,
    )


def unsupported_nikon_capture_discovery_plan(
    blocker: str,
    evidence_ids: tuple[EvidenceId, ...],
) -> NikonNefNikonCaptureDiscoveryPlan:
    return NikonNefNikonCaptureDiscoveryPlan(
        status="unsupported",
        can_supply_existing_capture_data=False,
        can_supply_existing_iptc_entry=False,
        maker_note_directory=None,
        capture_entry=None,
        iptc_entry=None,
        blockers=(blocker,),
        evidence_ids=evidence_ids,
    )


def locate_nikon_type2_makernote_ifd(
    data: bytes,
    header: NikonNefTiffHeaderSummary,
) -> NikonNefMakerNoteDirectoryLocation | None:
    maker_note_offset = header.maker_note_offset
    if maker_note_offset is None:
        return None
    signature_end = maker_note_offset + len(NIKON_MAKERNOTE_TYPE2_SIGNATURE)
    tiff_base = maker_note_offset + NIKON_MAKERNOTE_TYPE2_TIFF_HEADER_OFFSET
    if (
        signature_end > len(data)
        or data[maker_note_offset:signature_end] != NIKON_MAKERNOTE_TYPE2_SIGNATURE
        or tiff_base + 8 > len(data)
    ):
        return None
    tiff_header = parse_tiff_header(data[tiff_base:])
    if tiff_header is None:
        return None
    byte_order, tiff_magic, first_ifd_offset = tiff_header
    if tiff_magic != 42:
        return None
    ifd_offset = tiff_base + first_ifd_offset
    entry_count = read_ifd_entry_count(data, ifd_offset, byte_order)
    if entry_count is None:
        return None
    table_end = ifd_offset + 2 + entry_count * TIFF_IFD_ENTRY_SIZE
    if table_end + 4 > len(data):
        return None
    return NikonNefMakerNoteDirectoryLocation(
        byte_order=byte_order,
        maker_note_value_range=NikonNefByteRange(maker_note_offset, len(data)),
        tiff_header_range=NikonNefByteRange(tiff_base, tiff_base + 8),
        tiff_base_offset=tiff_base,
        ifd_offset=ifd_offset,
        ifd_entry_count=entry_count,
        ifd_entry_table_range=NikonNefByteRange(ifd_offset + 2, table_end),
        evidence_ids=(MAKER_NOTES_NIKON_TYPE2_LOCATION_SOURCE, NIKON_TYPE2_SOURCE),
    )


def find_nikon_capture_makernote_entry(
    data: bytes,
    location: NikonNefMakerNoteDirectoryLocation,
) -> NikonNefNikonCaptureMakerNoteEntry | None:
    entries_start = location.ifd_offset + 2
    for index in range(location.ifd_entry_count):
        entry_offset = entries_start + index * TIFF_IFD_ENTRY_SIZE
        tag_id = read_uint(data, entry_offset, location.byte_order, 2)
        if tag_id != 0x0E01:
            continue
        format_id = read_uint(data, entry_offset + 2, location.byte_order, 2)
        count = read_uint(data, entry_offset + 4, location.byte_order, 4)
        value_field_offset = entry_offset + 8
        value_range = tiff_makernote_value_range(
            data,
            location,
            value_field_offset,
            format_id,
            count,
        )
        if value_range is None:
            return None
        return NikonNefNikonCaptureMakerNoteEntry(
            tag_id=tag_id,
            format_id=format_id,
            count=count,
            entry_range=NikonNefByteRange(entry_offset, entry_offset + TIFF_IFD_ENTRY_SIZE),
            value_field_offset=value_field_offset,
            value_range=value_range,
            evidence_ids=(
                NIKON_CAPTURE_MAKERNOTE_SOURCE,
                MAKER_NOTES_NIKON_TYPE2_LOCATION_SOURCE,
            ),
        )
    return None


def tiff_makernote_value_range(
    data: bytes,
    location: NikonNefMakerNoteDirectoryLocation,
    value_field_offset: int,
    format_id: int,
    count: int,
) -> NikonNefByteRange | None:
    format_size = TIFF_VALUE_FORMAT_SIZES.get(format_id)
    if format_size is None:
        return None
    byte_length = format_size * count
    if byte_length <= 4:
        value_offset = value_field_offset
    else:
        value_offset = location.tiff_base_offset + read_uint(
            data,
            value_field_offset,
            location.byte_order,
            4,
        )
    if value_offset < 0 or value_offset + byte_length > len(data):
        return None
    return NikonNefByteRange(value_offset, value_offset + byte_length)


def find_nikon_capture_iptc_payload_entry(
    data: bytes,
    capture_range: NikonNefByteRange,
) -> NikonNefNikonCapturePayloadEntry | None:
    capture_header = validate_nikon_capture_payload_header(data, capture_range)
    if capture_header is None:
        return None
    capture_start, capture_end = capture_header
    position = capture_start + NIKON_CAPTURE_HEADER_SIZE
    index = 0
    while position + NIKON_CAPTURE_HEADER_SIZE < capture_end:
        tag_id = read_uint(data, position, "little", 4)
        size_word_offset = position + NIKON_CAPTURE_ENTRY_PREFIX_SIZE
        size_word_value = read_uint(data, size_word_offset, "little", 4)
        if size_word_value < NIKON_CAPTURE_ENTRY_SIZE_BIAS:
            return None
        value_start = position + NIKON_CAPTURE_HEADER_SIZE
        value_end = value_start + size_word_value - NIKON_CAPTURE_ENTRY_SIZE_BIAS
        if value_end > capture_end:
            return None
        if tag_id == NIKON_CAPTURE_IPTC_TAG_ID:
            return NikonNefNikonCapturePayloadEntry(
                tag_id=tag_id,
                tag_name="IPTCData",
                index=index,
                entry_range=NikonNefByteRange(position, value_end),
                value_range=NikonNefByteRange(value_start, value_end),
                size_word_offset=size_word_offset,
                size_word_value=size_word_value,
                evidence_ids=(NIKON_CAPTURE_TAGS_SOURCE, NIKON_CAPTURE_WRITE_SOURCE),
            )
        position = value_end
        index += 1
    return None


def validate_nikon_capture_payload_header(
    data: bytes,
    capture_range: NikonNefByteRange,
) -> tuple[int, int] | None:
    capture_start = capture_range.start_offset
    capture_length = capture_range.length
    if capture_start < 0 or capture_length < NIKON_CAPTURE_HEADER_SIZE:
        return None
    if capture_range.end_offset > len(data):
        return None
    tag_id = read_uint(data, capture_start, "little", 4)
    declared_size = read_uint(data, capture_start + NIKON_CAPTURE_FIXED_HEADER_SIZE, "little", 4)
    pad_length = capture_length - declared_size - NIKON_CAPTURE_FIXED_HEADER_SIZE
    if tag_id != NIKON_CAPTURE_MAGIC or not (pad_length >= 0 or pad_length == -18):
        return None
    effective_length = (
        declared_size + NIKON_CAPTURE_FIXED_HEADER_SIZE if pad_length > 0 else capture_length
    )
    return capture_start, capture_start + effective_length


def nikon_capture_discovery_evidence_ids() -> tuple[EvidenceId, ...]:
    return unique_evidence_ids(
        (
            MAKER_NOTES_NIKON_TYPE2_LOCATION_SOURCE,
            NIKON_TYPE2_SOURCE,
            NIKON_CAPTURE_MAKERNOTE_SOURCE,
            NIKON_CAPTURE_TAGS_SOURCE,
            NIKON_CAPTURE_WRITE_SOURCE,
        )
    )


def build_nikon_nef_image_data_preservation_plan(
    data: bytes,
) -> NikonNefImageDataPreservationPlan:
    header = parse_tiff_header(data)
    if header is None:
        return unsupported_image_data_preservation_plan()

    byte_order, tiff_magic, first_ifd_offset = header
    if tiff_magic != 42:
        return unsupported_image_data_preservation_plan()

    visited: set[int] = set()
    ifds = collect_nef_ifd_entries(
        data,
        byte_order,
        first_ifd_offset,
        visited,
        "IFD0",
        sub_ifd_pointer_tag=SUB_IFD_POINTER_TAG,
    )
    pairs = tuple(
        pair
        for ifd_name, entries in ifds
        for pair in image_data_pairs_from_ifd(data, ifd_name, entries)
    )
    blockers = image_data_preservation_blockers(pairs)
    evidence_ids = unique_evidence_ids(
        (
            EXIF_IMAGE_DATA_OFFSET_PAIR_SOURCE,
            EXIF_IMAGE_DATA_BYTE_COUNT_SOURCE,
            EXIF_TILE_IMAGE_DATA_SOURCE,
            WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
            WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
        )
    )
    return NikonNefImageDataPreservationPlan(
        status="source_mapped_deferred",
        can_preserve_image_data=False,
        scanned_ifds=tuple(ifd_name for ifd_name, _entries in ifds),
        pairs=pairs,
        blockers=blockers,
        evidence_ids=evidence_ids,
    )


def build_nikon_nef_image_data_copy_emitter(
    data: bytes,
    *,
    allow_output_emission: bool = False,
) -> NikonNefImageDataCopyEmitter:
    preservation = build_nikon_nef_image_data_preservation_plan(data)
    if preservation.status == "unsupported":
        return NikonNefImageDataCopyEmitter(
            status="unsupported",
            can_emit_bytes=False,
            records=(),
            output_bytes=None,
            output_gates=("defer_without_image_data_fixups",),
            blockers=preservation.blockers,
            evidence_ids=preservation.evidence_ids,
        )

    records = image_data_copy_records_from_pairs(preservation.pairs)
    blockers = image_data_copy_emitter_blockers(
        preservation,
        records,
        allow_output_emission=allow_output_emission,
    )
    output_bytes = (
        emit_nikon_nef_image_data_copy_bytes(data, records)
        if allow_output_emission and not blockers
        else None
    )
    return NikonNefImageDataCopyEmitter(
        status="source_mapped_deferred",
        can_emit_bytes=output_bytes is not None,
        records=records,
        output_bytes=output_bytes,
        output_gates=() if output_bytes is not None else ("defer_without_image_data_fixups",),
        blockers=blockers,
        evidence_ids=unique_evidence_ids(
            (
                WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
                WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
                EXIF_IMAGE_DATA_OFFSET_PAIR_SOURCE,
                EXIF_IMAGE_DATA_BYTE_COUNT_SOURCE,
                EXIF_TILE_IMAGE_DATA_SOURCE,
            )
        ),
    )


def build_nikon_nef_tiff_iptc_naa_rebuild_plan(
    data: bytes,
    caption_abstract: str | None,
) -> NikonNefTiffIptcNaaRebuildPlan:
    """Emit the replacement TIFF IPTC-NAA payload, but not the parent TIFF IFD."""

    evidence_ids = unique_evidence_ids(
        (EXIF_IPTC_NAA_SOURCE, IPTC_CAPTION_ABSTRACT_SOURCE, WRITE_IPTC_SOURCE)
    )
    header = parse_tiff_header(data)
    if header is None:
        return unsupported_tiff_iptc_naa_rebuild_plan(
            "requires_classic_tiff_header",
            evidence_ids,
        )
    byte_order, tiff_magic, first_ifd_offset = header
    if tiff_magic != 42:
        return unsupported_tiff_iptc_naa_rebuild_plan(
            "requires_classic_tiff_header",
            evidence_ids,
        )

    iptc_naa_entry = find_tiff_iptc_naa_entry(data, byte_order, first_ifd_offset)
    if iptc_naa_entry is None:
        return unsupported_tiff_iptc_naa_rebuild_plan(
            "requires_existing_tiff_iptc_naa_entry",
            evidence_ids,
        )
    if caption_abstract is None:
        return NikonNefTiffIptcNaaRebuildPlan(
            status="source_mapped_deferred",
            can_emit_payload=False,
            iptc_naa_entry=iptc_naa_entry,
            requested_caption_abstract=None,
            rebuilt_payload=None,
            planned_count=None,
            planned_padding_length=None,
            blockers=("requires_requested_caption_abstract_value",),
            evidence_ids=evidence_ids,
        )

    from exifmodern.formats.nikon_raw.capture_rebuild_plan import (
        emit_nikon_capture_iptc_caption_payload,
    )

    caption_payload = caption_abstract.encode("utf-8")
    iptc_emission = emit_nikon_capture_iptc_caption_payload(
        data,
        caption_payload,
        dir_start=iptc_naa_entry.value_range.start_offset,
        dir_len=iptc_naa_entry.value_range.length,
    )
    if iptc_emission.rebuilt_payload is None:
        return unsupported_tiff_iptc_naa_rebuild_plan(
            iptc_emission.unsupported_reason or "requires_rebuildable_tiff_iptc_naa_payload",
            evidence_ids,
            iptc_naa_entry=iptc_naa_entry,
        )

    padding_length = padding_to_four_byte_count(len(iptc_emission.rebuilt_payload))
    rebuilt_payload = iptc_emission.rebuilt_payload + (b"\0" * padding_length)
    return NikonNefTiffIptcNaaRebuildPlan(
        status="source_mapped_deferred",
        can_emit_payload=True,
        iptc_naa_entry=iptc_naa_entry,
        requested_caption_abstract=caption_abstract,
        rebuilt_payload=rebuilt_payload,
        planned_count=len(rebuilt_payload) // 4,
        planned_padding_length=padding_length,
        blockers=(),
        evidence_ids=unique_evidence_ids((*evidence_ids, *iptc_emission.evidence_ids)),
    )


def find_tiff_iptc_naa_entry(
    data: bytes,
    byte_order: TiffByteOrder,
    ifd0_offset: int,
) -> NikonNefTiffIptcNaaEntry | None:
    entries = read_ifd_entries(data, ifd0_offset, byte_order, "IFD0")
    if entries is None:
        return None
    entry = first_entry_for_tag(entries, IPTC_NAA_TAG)
    if entry is None:
        return None
    format_size = TIFF_VALUE_FORMAT_SIZES.get(entry.format_id)
    if format_size is None:
        return None
    byte_length = format_size * entry.count
    if byte_length <= 0:
        return None
    value_range = NikonNefByteRange(
        entry.value_data_offset,
        entry.value_data_offset + byte_length,
    )
    if value_range.end_offset > len(data):
        return None
    return NikonNefTiffIptcNaaEntry(
        ifd_name=entry.ifd_name,
        tag_id=entry.tag_id,
        format_id=entry.format_id,
        count=entry.count,
        entry_range=NikonNefByteRange(
            entry.value_field_offset - 8,
            entry.value_field_offset + 4,
        ),
        value_field_offset=entry.value_field_offset,
        value_range=value_range,
        evidence_ids=(EXIF_IPTC_NAA_SOURCE, WRITE_IPTC_SOURCE),
    )


def padding_to_four_byte_count(length: int) -> int:
    remainder = length % 4
    return 0 if remainder == 0 else 4 - remainder


def unsupported_tiff_iptc_naa_rebuild_plan(
    blocker: str,
    evidence_ids: tuple[EvidenceId, ...],
    *,
    iptc_naa_entry: NikonNefTiffIptcNaaEntry | None = None,
) -> NikonNefTiffIptcNaaRebuildPlan:
    return NikonNefTiffIptcNaaRebuildPlan(
        status="unsupported",
        can_emit_payload=False,
        iptc_naa_entry=iptc_naa_entry,
        requested_caption_abstract=None,
        rebuilt_payload=None,
        planned_count=None,
        planned_padding_length=None,
        blockers=(blocker,),
        evidence_ids=evidence_ids,
    )


def unsupported_image_data_preservation_plan() -> NikonNefImageDataPreservationPlan:
    return NikonNefImageDataPreservationPlan(
        status="unsupported",
        can_preserve_image_data=False,
        scanned_ifds=(),
        pairs=(),
        blockers=("requires_classic_tiff_header",),
        evidence_ids=(
            EXIF_IMAGE_DATA_OFFSET_PAIR_SOURCE,
            WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
        ),
    )


def image_data_copy_records_from_pairs(
    pairs: tuple[NikonNefImageDataPair, ...],
) -> tuple[NikonNefImageDataCopyRecord, ...]:
    ordered_pairs = sorted(
        pairs,
        key=lambda pair: (ifd_copy_rank(pair.ifd_name), pair.offset_tag),
        reverse=True,
    )
    records: list[NikonNefImageDataCopyRecord] = []
    for pair in ordered_pairs:
        for segment_index, segment in enumerate(pair.segments):
            records.append(
                NikonNefImageDataCopyRecord(
                    copy_order=len(records),
                    ifd_name=pair.ifd_name,
                    kind=pair.kind,
                    stage="write_later_image_data",
                    segment_index=segment_index,
                    source_offset=segment.offset,
                    byte_count=segment.byte_count,
                    pad_byte_required=segment.byte_count % 2 == 1,
                    source_in_bounds=segment.in_bounds,
                    offset_value_field_offset=pair.offset_value_field_offset,
                    byte_count_value_field_offset=pair.byte_count_value_field_offset,
                    evidence_ids=pair.evidence_ids,
                )
            )
    return tuple(records)


def emit_nikon_nef_image_data_copy_bytes(
    data: bytes,
    records: tuple[NikonNefImageDataCopyRecord, ...],
) -> bytes:
    chunks: list[bytes] = []
    for record in records:
        end_offset = record.source_offset + record.byte_count
        chunks.append(data[record.source_offset : end_offset])
        if record.pad_byte_required:
            chunks.append(b"\0")
    return b"".join(chunks)


def emit_nikon_nef_writeexif_offset_fixup_bytes(
    planned_tiff_bytes: bytes,
    image_data_copy_emitter: NikonNefImageDataCopyEmitter,
    *,
    image_data_start_offset: int,
    byte_order: TiffByteOrder,
) -> NikonNefWriteExifOffsetFixupEmission:
    """Patch WriteExif offsetInfo positions and return deferred image-data bytes."""

    evidence_ids = unique_evidence_ids(
        (
            WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
            WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
            *image_data_copy_emitter.evidence_ids,
        )
    )
    if image_data_copy_emitter.status != "source_mapped_deferred":
        return unsupported_writeexif_offset_fixup_emission(
            "requires_source_mapped_image_data_copy_emitter",
            evidence_ids,
        )
    if image_data_copy_emitter.output_bytes is None:
        return unsupported_writeexif_offset_fixup_emission(
            "requires_emitted_image_data_copy_bytes",
            evidence_ids,
        )
    if not image_data_copy_emitter.records:
        return unsupported_writeexif_offset_fixup_emission(
            "requires_image_data_copy_records",
            evidence_ids,
        )
    if image_data_start_offset < 0:
        return unsupported_writeexif_offset_fixup_emission(
            "requires_non_negative_image_data_start_offset",
            evidence_ids,
        )
    if any(not record.source_in_bounds for record in image_data_copy_emitter.records):
        return unsupported_writeexif_offset_fixup_emission(
            "requires_bounded_image_data_segments",
            evidence_ids,
        )

    patched_tiff_bytes = bytearray(planned_tiff_bytes)
    records: list[NikonNefWriteExifOffsetFixupRecord] = []
    next_offset = image_data_start_offset
    for copy_record in image_data_copy_emitter.records:
        if not writeexif_offset_fixup_fields_in_bounds(patched_tiff_bytes, copy_record):
            return unsupported_writeexif_offset_fixup_emission(
                "requires_bounded_writeexif_offset_value_positions",
                evidence_ids,
            )
        patched_tiff_bytes[
            copy_record.offset_value_field_offset : copy_record.offset_value_field_offset + 4
        ] = next_offset.to_bytes(4, byte_order)
        patched_tiff_bytes[
            copy_record.byte_count_value_field_offset : copy_record.byte_count_value_field_offset
            + 4
        ] = copy_record.byte_count.to_bytes(4, byte_order)
        records.append(
            NikonNefWriteExifOffsetFixupRecord(
                copy_order=copy_record.copy_order,
                ifd_name=copy_record.ifd_name,
                kind=copy_record.kind,
                offset_value_field_offset=copy_record.offset_value_field_offset,
                byte_count_value_field_offset=copy_record.byte_count_value_field_offset,
                source_offset=copy_record.source_offset,
                old_byte_count=copy_record.byte_count,
                new_offset=next_offset,
                new_byte_count=copy_record.byte_count,
                pad_byte_required=copy_record.pad_byte_required,
                evidence_ids=copy_record.evidence_ids,
            )
        )
        next_offset += copy_record.byte_count
        if copy_record.pad_byte_required:
            next_offset += 1

    return NikonNefWriteExifOffsetFixupEmission(
        status="emitted_writeexif_offset_fixup_bytes",
        patched_tiff_bytes=bytes(patched_tiff_bytes),
        image_data_bytes=image_data_copy_emitter.output_bytes,
        records=tuple(records),
        remaining_blockers=(
            "requires_parent_tiff_value_position_materialization_hook",
            "requires_makernote_fixup_pointer_records_from_tiff_rebuild",
        ),
        unsupported_reason=None,
        evidence_ids=evidence_ids,
    )


def writeexif_offset_fixup_fields_in_bounds(
    planned_tiff_bytes: bytes | bytearray,
    copy_record: NikonNefImageDataCopyRecord,
) -> bool:
    offset_end = copy_record.offset_value_field_offset + 4
    byte_count_end = copy_record.byte_count_value_field_offset + 4
    return (
        copy_record.offset_value_field_offset >= 0
        and copy_record.byte_count_value_field_offset >= 0
        and offset_end <= len(planned_tiff_bytes)
        and byte_count_end <= len(planned_tiff_bytes)
    )


def unsupported_writeexif_offset_fixup_emission(
    reason: str,
    evidence_ids: tuple[EvidenceId, ...],
) -> NikonNefWriteExifOffsetFixupEmission:
    return NikonNefWriteExifOffsetFixupEmission(
        status="unsupported",
        patched_tiff_bytes=None,
        image_data_bytes=None,
        records=(),
        remaining_blockers=(reason,),
        unsupported_reason=reason,
        evidence_ids=evidence_ids,
    )


def emit_nikon_nef_parent_tiff_value_position_bytes(
    data: bytes,
    maker_note_emission: NikonNefMakerNoteValueRebuildEmission,
    tiff_iptc_naa_rebuild: NikonNefTiffIptcNaaRebuildPlan,
    image_data_copy_emitter: NikonNefImageDataCopyEmitter,
) -> NikonNefParentTiffValuePositionMaterialization:
    """Materialize the bounded NEF parent value-position handoff.

    This is not a general TIFF rebuilder.  It installs already rebuilt value
    payloads at deterministic parent-TIFF positions, patches the exact IFD
    count/offset fields that point at those payloads, then delegates image-data
    offset repairs to the WriteExif-style offset-fixup emitter.
    """

    evidence_ids = unique_evidence_ids(
        (
            WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
            WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
            WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
            WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
            EXIF_IPTC_NAA_SOURCE,
            *maker_note_emission.evidence_ids,
            *tiff_iptc_naa_rebuild.evidence_ids,
            *image_data_copy_emitter.evidence_ids,
        )
    )
    header = inspect_nef_tiff_header(data)
    if header is None:
        return unsupported_parent_tiff_value_position_materialization(
            "requires_classic_tiff_header",
            evidence_ids,
        )
    if maker_note_emission.rebuilt_maker_note_value is None:
        return unsupported_parent_tiff_value_position_materialization(
            "requires_rebuilt_makernote_value",
            evidence_ids,
        )
    if tiff_iptc_naa_rebuild.rebuilt_payload is None:
        return unsupported_parent_tiff_value_position_materialization(
            "requires_rebuilt_tiff_iptc_naa_payload",
            evidence_ids,
        )
    if tiff_iptc_naa_rebuild.iptc_naa_entry is None:
        return unsupported_parent_tiff_value_position_materialization(
            "requires_existing_tiff_iptc_naa_entry",
            evidence_ids,
        )
    if header.exif_ifd_offset is None:
        return unsupported_parent_tiff_value_position_materialization(
            "requires_exif_ifd_for_makernote_parent",
            evidence_ids,
        )
    exif_entry_count = read_ifd_entry_count(data, header.exif_ifd_offset, header.byte_order)
    maker_note_value_field_offset = find_ifd_value_field(
        data,
        header.exif_ifd_offset,
        exif_entry_count,
        header.byte_order,
        MAKER_NOTE_TAG,
    )
    if maker_note_value_field_offset is None:
        return unsupported_parent_tiff_value_position_materialization(
            "requires_existing_makernote_parent_entry",
            evidence_ids,
        )

    output = bytearray(data)
    maker_note_output_offset = append_even_aligned_value(
        output,
        maker_note_emission.rebuilt_maker_note_value,
    )
    output[maker_note_value_field_offset - 4 : maker_note_value_field_offset] = len(
        maker_note_emission.rebuilt_maker_note_value
    ).to_bytes(4, header.byte_order)
    output[maker_note_value_field_offset : maker_note_value_field_offset + 4] = (
        maker_note_output_offset.to_bytes(4, header.byte_order)
    )

    iptc_payload = tiff_iptc_naa_rebuild.rebuilt_payload
    iptc_naa_output_offset = append_even_aligned_value(output, iptc_payload)
    iptc_value_field_offset = tiff_iptc_naa_rebuild.iptc_naa_entry.value_field_offset
    output[iptc_value_field_offset - 4 : iptc_value_field_offset] = (
        tiff_iptc_naa_rebuild.planned_count or 0
    ).to_bytes(4, header.byte_order)
    output[iptc_value_field_offset : iptc_value_field_offset + 4] = iptc_naa_output_offset.to_bytes(
        4, header.byte_order
    )

    image_data_start_offset = len(output)
    offset_fixup_emission = emit_nikon_nef_writeexif_offset_fixup_bytes(
        bytes(output),
        image_data_copy_emitter,
        image_data_start_offset=image_data_start_offset,
        byte_order=header.byte_order,
    )
    if (
        offset_fixup_emission.status != "emitted_writeexif_offset_fixup_bytes"
        or offset_fixup_emission.patched_tiff_bytes is None
        or offset_fixup_emission.image_data_bytes is None
    ):
        return unsupported_parent_tiff_value_position_materialization(
            offset_fixup_emission.unsupported_reason or "requires_offset_fixup_emission",
            evidence_ids,
            offset_fixup_emission=offset_fixup_emission,
        )

    return NikonNefParentTiffValuePositionMaterialization(
        status="emitted_parent_tiff_value_positions",
        output_bytes=offset_fixup_emission.patched_tiff_bytes
        + offset_fixup_emission.image_data_bytes,
        maker_note_value_field_offset=maker_note_value_field_offset,
        maker_note_count_field_offset=maker_note_value_field_offset - 4,
        maker_note_output_offset=maker_note_output_offset,
        maker_note_output_count=len(maker_note_emission.rebuilt_maker_note_value),
        iptc_naa_value_field_offset=iptc_value_field_offset,
        iptc_naa_count_field_offset=iptc_value_field_offset - 4,
        iptc_naa_output_offset=iptc_naa_output_offset,
        iptc_naa_output_count=tiff_iptc_naa_rebuild.planned_count,
        image_data_start_offset=image_data_start_offset,
        offset_fixup_emission=offset_fixup_emission,
        remaining_blockers=(),
        unsupported_reason=None,
        evidence_ids=evidence_ids,
    )


def append_even_aligned_value(output: bytearray, value: bytes) -> int:
    if len(output) % 2:
        output.append(0)
    value_offset = len(output)
    output.extend(value)
    if len(output) % 2:
        output.append(0)
    return value_offset


def unsupported_parent_tiff_value_position_materialization(
    reason: str,
    evidence_ids: tuple[EvidenceId, ...],
    *,
    offset_fixup_emission: NikonNefWriteExifOffsetFixupEmission | None = None,
) -> NikonNefParentTiffValuePositionMaterialization:
    return NikonNefParentTiffValuePositionMaterialization(
        status="unsupported",
        output_bytes=None,
        maker_note_value_field_offset=None,
        maker_note_count_field_offset=None,
        maker_note_output_offset=None,
        maker_note_output_count=None,
        iptc_naa_value_field_offset=None,
        iptc_naa_count_field_offset=None,
        iptc_naa_output_offset=None,
        iptc_naa_output_count=None,
        image_data_start_offset=None,
        offset_fixup_emission=offset_fixup_emission,
        remaining_blockers=(reason,),
        unsupported_reason=reason,
        evidence_ids=evidence_ids,
    )


def ifd_copy_rank(ifd_name: str) -> int:
    if ifd_name.startswith("IFD") and ifd_name[3:].isdigit():
        return int(ifd_name[3:])
    if ":SubIFD" in ifd_name:
        return 1
    return 0


def image_data_copy_emitter_blockers(
    preservation: NikonNefImageDataPreservationPlan,
    records: tuple[NikonNefImageDataCopyRecord, ...],
    *,
    allow_output_emission: bool = False,
) -> tuple[str, ...]:
    blockers = [
        blocker
        for blocker in preservation.blockers
        if blocker != "requires_writeexif_offsetinfo_copy_emitter" or not allow_output_emission
    ]
    if not allow_output_emission:
        append_unique(blockers, "requires_writeexif_offsetinfo_copy_emitter")
        append_unique(blockers, "requires_writeexif_offset_fixup_runtime")
    if not records:
        append_unique(blockers, "requires_image_data_copy_records")
    if any(not record.source_in_bounds for record in records):
        append_unique(blockers, "requires_bounded_image_data_segments")
    if contains_strip_and_tile_pairs(preservation.pairs):
        append_unique(blockers, "requires_strip_tile_conflict_resolution")
    return tuple(blockers)


def contains_strip_and_tile_pairs(
    pairs: tuple[NikonNefImageDataPair, ...],
) -> bool:
    kinds_by_ifd: dict[str, set[NikonNefImageDataPairKind]] = {}
    for pair in pairs:
        kinds_by_ifd.setdefault(pair.ifd_name, set()).add(pair.kind)
    return any({"strip_image_data", "tile_image_data"} <= kinds for kinds in kinds_by_ifd.values())


def append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def build_nikon_nef_makernote_fixup_contract(
    header: NikonNefTiffHeaderSummary,
) -> NikonNefMakerNoteFixupContract:
    evidence_ids = unique_evidence_ids(
        (
            WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
            WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
            NIKON_PREVIEW_IFD_SOURCE,
        )
    )
    if header.maker_note_offset is None or not (
        header.maker_note_signature and header.maker_note_signature.startswith("Nikon")
    ):
        return NikonNefMakerNoteFixupContract(
            status="unsupported",
            can_apply_fixups=False,
            maker_note_signature=header.maker_note_signature,
            rules=(),
            blockers=("requires_nikon_type2_makernote_signature",),
            evidence_ids=evidence_ids,
        )
    return NikonNefMakerNoteFixupContract(
        status="source_mapped_deferred",
        can_apply_fixups=False,
        maker_note_signature=header.maker_note_signature,
        rules=nikon_nef_makernote_fixup_rules(),
        blockers=(
            "requires_writeexif_makernote_fixup_applier",
            "requires_preview_image_marker_pointer_filter",
        ),
        evidence_ids=evidence_ids,
    )


def build_nikon_nef_makernote_fixup_application_plan(
    planned_maker_note_value: bytes,
    context: NikonNefMakerNoteFixupApplicationContext,
    fixup_pointers: tuple[NikonNefMakerNoteFixupPointer, ...],
    preview_offset_pairs: tuple[NikonNefMakerNotePreviewOffsetPair, ...] = (),
) -> NikonNefMakerNoteFixupApplicationPlan:
    evidence_ids = unique_evidence_ids(
        (
            WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
            NIKON_PREVIEW_IFD_SOURCE,
            WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
        )
    )
    if context.maker_note_header_length < 0 or context.maker_note_value_buffer_offset < 0:
        return unsupported_makernote_fixup_application_plan(
            "requires_non_negative_makernote_fixup_context",
            evidence_ids,
        )

    records = makernote_fixup_application_records(
        planned_maker_note_value,
        context,
        fixup_pointers,
    )
    protected_pairs = protected_preview_offset_pairs(preview_offset_pairs, context)
    blockers = makernote_fixup_application_blockers(records, protected_pairs)
    return NikonNefMakerNoteFixupApplicationPlan(
        status="source_mapped_deferred",
        can_apply_to_nef_bytes=False,
        context=context,
        records=records,
        preview_offset_pairs=protected_pairs,
        output_gates=("defer_without_makernote_fixup_application",),
        blockers=blockers,
        evidence_ids=evidence_ids,
    )


def emit_nikon_nef_makernote_fixup_applied_value(
    planned_maker_note_value: bytes,
    context: NikonNefMakerNoteFixupApplicationContext,
    fixup_pointers: tuple[NikonNefMakerNoteFixupPointer, ...],
    *,
    byte_order: TiffByteOrder,
    preview_offset_pairs: tuple[NikonNefMakerNotePreviewOffsetPair, ...] = (),
) -> NikonNefMakerNoteFixupApplicationEmission:
    """Apply bounded WriteExif MakerNote fixups to a planned MakerNote value.

    Pointer discovery still belongs to the TIFF/WriteExif rebuild path.  This
    emitter owns only the byte application once those pointer records and the
    final value-buffer coordinates are known.
    """

    plan = build_nikon_nef_makernote_fixup_application_plan(
        planned_maker_note_value,
        context,
        fixup_pointers,
        preview_offset_pairs,
    )
    evidence_ids = unique_evidence_ids((*plan.evidence_ids, WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE))
    if plan.status != "source_mapped_deferred":
        return unsupported_makernote_fixup_application_emission(
            plan,
            "requires_source_mapped_makernote_fixup_plan",
            evidence_ids,
        )
    if not plan.records:
        return unsupported_makernote_fixup_application_emission(
            plan,
            "requires_makernote_fixup_pointer_records",
            evidence_ids,
        )
    if any(record.deferred_to_value_fixups for record in plan.records):
        return unsupported_makernote_fixup_application_emission(
            plan,
            "requires_deferred_preview_value_fixups",
            evidence_ids,
        )
    if any(not record.in_planned_value_bounds for record in plan.records):
        return unsupported_makernote_fixup_application_emission(
            plan,
            "requires_bounded_makernote_fixup_pointers",
            evidence_ids,
        )
    if any(
        record.shifted_value < 0 or record.shifted_value > 0xFFFFFFFF for record in plan.records
    ):
        return unsupported_makernote_fixup_application_emission(
            plan,
            "requires_uint32_makernote_fixup_values",
            evidence_ids,
        )

    output = bytearray(planned_maker_note_value)
    for record in plan.records:
        patch_offset = record.pointer_offset + record.application_start
        output[patch_offset : patch_offset + 4] = record.shifted_value.to_bytes(4, byte_order)
    return NikonNefMakerNoteFixupApplicationEmission(
        status="emitted_makernote_fixup_value",
        plan=plan,
        applied_maker_note_value=bytes(output),
        remaining_blockers=(
            "requires_parent_tiff_value_position_materialization_hook",
            "requires_writeexif_offset_fixup_runtime",
        ),
        unsupported_reason=None,
        evidence_ids=evidence_ids,
    )


def unsupported_makernote_fixup_application_emission(
    plan: NikonNefMakerNoteFixupApplicationPlan,
    reason: str,
    evidence_ids: tuple[EvidenceId, ...],
) -> NikonNefMakerNoteFixupApplicationEmission:
    return NikonNefMakerNoteFixupApplicationEmission(
        status="unsupported",
        plan=plan,
        applied_maker_note_value=None,
        remaining_blockers=(reason,),
        unsupported_reason=reason,
        evidence_ids=evidence_ids,
    )


def emit_nikon_nef_type2_makernote_with_replaced_capture_block(
    data: bytes,
    rebuilt_capture_block: bytes,
) -> NikonNefMakerNoteValueRebuildEmission:
    """Emit a replacement Nikon Type2 MakerNote value with a new Capture block.

    This is the package-local MakerNote value-position rebuild seam only.  It
    does not install the MakerNote into the parent NEF TIFF or apply final
    WriteExif offset fixups.
    """

    evidence_ids = unique_evidence_ids(
        (
            MAKER_NOTES_NIKON_TYPE2_LOCATION_SOURCE,
            NIKON_CAPTURE_MAKERNOTE_SOURCE,
            WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
            WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
        )
    )
    header = inspect_nef_tiff_header(data)
    if header is None:
        return unsupported_makernote_value_rebuild_emission(
            "requires_classic_tiff_header",
            evidence_ids,
        )
    maker_note_value_range = find_exif_makernote_value_range(data, header)
    if maker_note_value_range is None:
        return unsupported_makernote_value_rebuild_emission(
            "requires_bounded_makernote_value",
            evidence_ids,
        )
    location = locate_nikon_type2_makernote_ifd(data, header)
    if location is None:
        return unsupported_makernote_value_rebuild_emission(
            "requires_nikon_type2_makernote_ifd",
            evidence_ids,
            maker_note_value_range=maker_note_value_range,
        )
    capture_entry = find_nikon_capture_makernote_entry(data, location)
    if capture_entry is None:
        return unsupported_makernote_value_rebuild_emission(
            "requires_existing_nikon_capture_data_payload",
            evidence_ids,
            maker_note_value_range=maker_note_value_range,
        )
    if not value_range_is_inside(capture_entry.value_range, maker_note_value_range):
        return unsupported_makernote_value_rebuild_emission(
            "requires_capture_value_inside_makernote_value",
            evidence_ids,
            maker_note_value_range=maker_note_value_range,
        )

    rebuilt_value = bytearray(
        data[maker_note_value_range.start_offset : maker_note_value_range.end_offset]
    )
    local_count_field_offset = (
        capture_entry.value_field_offset - maker_note_value_range.start_offset - 4
    )
    local_value_field_offset = (
        capture_entry.value_field_offset - maker_note_value_range.start_offset
    )
    new_value_start = len(rebuilt_value)
    new_value_offset = (
        maker_note_value_range.start_offset + new_value_start - location.tiff_base_offset
    )
    rebuilt_value[local_count_field_offset : local_count_field_offset + 4] = len(
        rebuilt_capture_block
    ).to_bytes(4, location.byte_order)
    rebuilt_value[local_value_field_offset : local_value_field_offset + 4] = (
        new_value_offset.to_bytes(4, location.byte_order)
    )
    rebuilt_value.extend(rebuilt_capture_block)
    if len(rebuilt_value) % 2:
        rebuilt_value.append(0)

    local_capture_value_field_offset = (
        capture_entry.value_field_offset - maker_note_value_range.start_offset
    )
    patch = NikonNefMakerNoteValuePositionPatch(
        tag_id=capture_entry.tag_id,
        tag_name="NikonCaptureData",
        count_field_offset=capture_entry.value_field_offset - 4,
        value_field_offset=capture_entry.value_field_offset,
        old_count=capture_entry.count,
        new_count=len(rebuilt_capture_block),
        old_value_offset=capture_entry.value_range.start_offset - location.tiff_base_offset,
        new_value_offset=new_value_offset,
        new_value_range=NikonNefByteRange(
            maker_note_value_range.start_offset + new_value_start,
            maker_note_value_range.start_offset + new_value_start + len(rebuilt_capture_block),
        ),
        evidence_ids=(NIKON_CAPTURE_MAKERNOTE_SOURCE, WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE),
    )
    fixup_pointer = NikonNefMakerNoteFixupPointer(
        pointer_name="NikonCaptureData",
        pointer_offset=local_capture_value_field_offset - NIKON_MAKERNOTE_TYPE2_TIFF_HEADER_OFFSET,
        original_value=new_value_offset,
        data_tag="NikonCaptureData",
    )
    return NikonNefMakerNoteValueRebuildEmission(
        status="emitted_type2_makernote_value",
        rebuilt_maker_note_value=bytes(rebuilt_value),
        maker_note_value_range=maker_note_value_range,
        capture_value_patch=patch,
        maker_note_fixup_pointers=(fixup_pointer,),
        remaining_blockers=("requires_parent_tiff_value_position_materialization_hook",),
        unsupported_reason=None,
        evidence_ids=evidence_ids,
    )


def unsupported_makernote_value_rebuild_emission(
    reason: str,
    evidence_ids: tuple[EvidenceId, ...],
    *,
    maker_note_value_range: NikonNefByteRange | None = None,
) -> NikonNefMakerNoteValueRebuildEmission:
    return NikonNefMakerNoteValueRebuildEmission(
        status="unsupported",
        rebuilt_maker_note_value=None,
        maker_note_value_range=maker_note_value_range,
        capture_value_patch=None,
        maker_note_fixup_pointers=(),
        remaining_blockers=(reason,),
        unsupported_reason=reason,
        evidence_ids=evidence_ids,
    )


def find_exif_makernote_value_range(
    data: bytes,
    header: NikonNefTiffHeaderSummary,
) -> NikonNefByteRange | None:
    exif_ifd_offset = header.exif_ifd_offset
    if exif_ifd_offset is None:
        return None
    exif_entry_count = read_ifd_entry_count(data, exif_ifd_offset, header.byte_order)
    value_field_offset = find_ifd_value_field(
        data,
        exif_ifd_offset,
        exif_entry_count,
        header.byte_order,
        MAKER_NOTE_TAG,
    )
    if value_field_offset is None:
        return None
    entry_offset = value_field_offset - 8
    format_id = read_uint(data, entry_offset + 2, header.byte_order, 2)
    count = read_uint(data, entry_offset + 4, header.byte_order, 4)
    format_size = TIFF_VALUE_FORMAT_SIZES.get(format_id)
    if format_size is None:
        return None
    value_data_offset = tiff_value_data_offset(
        data,
        value_field_offset,
        format_id,
        count,
        header.byte_order,
    )
    if value_data_offset is None:
        return None
    byte_length = format_size * count
    value_range = NikonNefByteRange(
        value_data_offset,
        value_data_offset + byte_length,
    )
    if value_range.end_offset > len(data):
        return None
    return value_range


def value_range_is_inside(
    inner: NikonNefByteRange,
    outer: NikonNefByteRange,
) -> bool:
    return outer.start_offset <= inner.start_offset and inner.end_offset <= outer.end_offset


def unsupported_makernote_fixup_application_plan(
    blocker: str,
    evidence_ids: tuple[EvidenceId, ...],
) -> NikonNefMakerNoteFixupApplicationPlan:
    return NikonNefMakerNoteFixupApplicationPlan(
        status="unsupported",
        can_apply_to_nef_bytes=False,
        context=None,
        records=(),
        preview_offset_pairs=(),
        output_gates=("defer_without_makernote_fixup_application",),
        blockers=(blocker,),
        evidence_ids=evidence_ids,
    )


def makernote_fixup_application_records(
    planned_maker_note_value: bytes,
    context: NikonNefMakerNoteFixupApplicationContext,
    fixup_pointers: tuple[NikonNefMakerNoteFixupPointer, ...],
) -> tuple[NikonNefMakerNoteFixupApplicationRecord, ...]:
    records: list[NikonNefMakerNoteFixupApplicationRecord] = []
    for pointer in fixup_pointers:
        is_preview_pointer = pointer.pointer_name.endswith("_PreviewImage")
        deferred_to_value_fixups = context.preview_present and is_preview_pointer
        application_start = (
            context.deferred_value_fixup_start
            if deferred_to_value_fixups
            else context.application_start
        )
        kind: NikonNefMakerNoteFixupApplicationKind
        if deferred_to_value_fixups:
            kind = "preview_marker_carry_forward"
        elif context.relative_offsets:
            kind = "relative_offset_shift"
        else:
            kind = "absolute_offset_shift"
        records.append(
            NikonNefMakerNoteFixupApplicationRecord(
                kind=kind,
                pointer_name=pointer.pointer_name,
                data_tag=pointer.data_tag,
                pointer_offset=pointer.pointer_offset,
                application_start=application_start,
                shift=context.applied_shift,
                original_value=pointer.original_value,
                shifted_value=pointer.original_value + context.applied_shift,
                in_planned_value_bounds=pointer_is_in_bounds(
                    pointer.pointer_offset,
                    application_start,
                    len(planned_maker_note_value),
                ),
                deferred_to_value_fixups=deferred_to_value_fixups,
                evidence_ids=(
                    (WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE, NIKON_PREVIEW_IFD_SOURCE)
                    if deferred_to_value_fixups
                    else (WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,)
                ),
            )
        )
    return tuple(records)


def pointer_is_in_bounds(pointer_offset: int, application_start: int, value_length: int) -> bool:
    applied_offset = pointer_offset + application_start
    return applied_offset >= 0 and applied_offset + 4 <= value_length


def protected_preview_offset_pairs(
    preview_offset_pairs: tuple[NikonNefMakerNotePreviewOffsetPair, ...],
    context: NikonNefMakerNoteFixupApplicationContext,
) -> tuple[NikonNefMakerNotePreviewOffsetPair, ...]:
    return tuple(
        NikonNefMakerNotePreviewOffsetPair(
            data_tag=pair.data_tag,
            start_tag=pair.start_tag,
            length_tag=pair.length_tag,
            start_pointer_offset=pair.start_pointer_offset,
            length_pointer_offset=pair.length_pointer_offset,
            start_value=pair.start_value,
            length_value=pair.length_value,
            marker_carried_forward=context.preview_present or pair.marker_carried_forward,
            protected_by_preview_ifd=(
                pair.start_tag == 0x0201
                and pair.length_tag == 0x0202
                and pair.data_tag == "PreviewImage"
            ),
            evidence_ids=unique_evidence_ids((*pair.evidence_ids, NIKON_PREVIEW_IFD_SOURCE)),
        )
        for pair in preview_offset_pairs
    )


def makernote_fixup_application_blockers(
    records: tuple[NikonNefMakerNoteFixupApplicationRecord, ...],
    preview_offset_pairs: tuple[NikonNefMakerNotePreviewOffsetPair, ...],
) -> tuple[str, ...]:
    blockers = [
        "requires_writeexif_fixup_runtime_integration",
        "requires_parent_tiff_value_position_materialization_hook",
    ]
    if not records:
        blockers.append("requires_makernote_fixup_pointer_records")
    if any(not record.in_planned_value_bounds for record in records):
        blockers.append("requires_bounded_makernote_fixup_pointers")
    if any(not pair.protected_by_preview_ifd for pair in preview_offset_pairs):
        blockers.append("requires_preview_ifd_offset_pair_source_protection")
    return tuple(blockers)


def build_nikon_nef_final_output_materialization_plan(
    maker_note_fixup_contract: NikonNefMakerNoteFixupContract | None,
    image_data_copy_emitter: NikonNefImageDataCopyEmitter | None,
    *,
    rebuilt_tiff_directory_bytes_available: bool = False,
    nikon_capture_block_payload_available: bool = False,
    iptc_subdirectory_payload_available: bool = False,
    maker_note_fixup_applier_available: bool = False,
    maker_note_fixup_pointer_records_available: bool = False,
    offset_value_position_fixups_available: bool = False,
) -> NikonNefFinalOutputMaterializationPlan:
    if maker_note_fixup_contract is None or image_data_copy_emitter is None:
        return NikonNefFinalOutputMaterializationPlan(
            status="unsupported",
            can_materialize_output=False,
            components=(),
            remaining_blockers=("requires_nef_mutation_contracts",),
            evidence_ids=(
                WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
                WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
            ),
        )

    maker_note_fixups_ready = maker_note_fixup_contract.can_apply_fixups or (
        maker_note_fixup_applier_available and maker_note_fixup_pointer_records_available
    )
    components = (
        NikonNefFinalOutputComponent(
            kind="rebuilt_tiff_directory_bytes",
            ready_for_materialization=rebuilt_tiff_directory_bytes_available,
            blocker=(
                None
                if rebuilt_tiff_directory_bytes_available
                else "requires_parent_tiff_value_position_materialization_hook"
            ),
            description=(
                "Final NEF bytes require rebuilt TIFF/EXIF directory bytes and the exact "
                "value-field positions used by WriteExif for later fixups."
            ),
            evidence_ids=(
                WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
                WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
            ),
        ),
        NikonNefFinalOutputComponent(
            kind="nikon_type2_makernote_fixups",
            ready_for_materialization=maker_note_fixups_ready,
            blocker=(
                None
                if maker_note_fixups_ready
                else makernote_fixup_materialization_blocker(maker_note_fixup_applier_available)
            ),
            description=(
                "Nikon Type2 MakerNote reinsertion must restore the original header and "
                "apply relative/base-shift fixups before the value is installed."
            ),
            evidence_ids=maker_note_fixup_contract.evidence_ids,
        ),
        NikonNefFinalOutputComponent(
            kind="nikon_capture_block_payload",
            ready_for_materialization=nikon_capture_block_payload_available,
            blocker=(
                None
                if nikon_capture_block_payload_available
                else "requires_nikon_capture_block_rewriter"
            ),
            description=(
                "PhotoEffects and VignetteControlIntensity require a rebuilt "
                "NikonCaptureData payload before MakerNote reinsertion."
            ),
            evidence_ids=(NIKON_CAPTURE_TAGS_SOURCE, NIKON_CAPTURE_WRITE_SOURCE),
        ),
        NikonNefFinalOutputComponent(
            kind="iptc_subdirectory_payload",
            ready_for_materialization=iptc_subdirectory_payload_available,
            blocker=(
                None
                if iptc_subdirectory_payload_available
                else "requires_iptc_subdirectory_rewriter"
            ),
            description=(
                "Caption-Abstract lands in the NikonCaptureData IPTC subdirectory, which "
                "must be materialized before the Capture block is rebuilt."
            ),
            evidence_ids=(NIKON_CAPTURE_TAGS_SOURCE, NIKON_CAPTURE_WRITE_SOURCE),
        ),
        NikonNefFinalOutputComponent(
            kind="image_data_copy_records",
            ready_for_materialization=image_data_copy_emitter.can_emit_bytes,
            blocker=(
                None
                if image_data_copy_emitter.can_emit_bytes
                else "requires_writeexif_offsetinfo_copy_emitter"
            ),
            description=(
                "WriteExif copies deferred image data after offsetInfo processing, using "
                "the paired offset and byte-count values."
            ),
            evidence_ids=image_data_copy_emitter.evidence_ids,
        ),
        NikonNefFinalOutputComponent(
            kind="offset_value_position_fixups",
            ready_for_materialization=offset_value_position_fixups_available,
            blocker=(
                None
                if offset_value_position_fixups_available
                else "requires_writeexif_offset_fixup_runtime"
            ),
            description=(
                "Final output must know the new offset value positions before it can patch "
                "image-data offsets and MakerNote value fixups."
            ),
            evidence_ids=(
                WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
                WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
                WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
            ),
        ),
    )
    blockers = tuple(component.blocker for component in components if component.blocker is not None)
    return NikonNefFinalOutputMaterializationPlan(
        status=(
            "blocked_on_writeexif_value_positions"
            if blockers
            else "emitted_parent_tiff_value_positions"
        ),
        can_materialize_output=not blockers,
        components=components,
        remaining_blockers=blockers,
        evidence_ids=unique_evidence_ids(
            tuple(reference for component in components for reference in component.evidence_ids)
        ),
    )


def makernote_fixup_materialization_blocker(
    maker_note_fixup_applier_available: bool,
) -> str:
    if maker_note_fixup_applier_available:
        return "requires_makernote_fixup_pointer_records_from_tiff_rebuild"
    return "requires_writeexif_makernote_fixup_applier"


def build_nikon_nef_native_promotion_plan(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
    maker_note_fixup_contract: NikonNefMakerNoteFixupContract | None,
    image_data_copy_emitter: NikonNefImageDataCopyEmitter | None,
    nikon_capture_discovery: NikonNefNikonCaptureDiscoveryPlan | None = None,
    *,
    tiff_iptc_naa_payload_available: bool = False,
) -> NikonNefNativePromotionPlan:
    final_output_materialization = build_nikon_nef_final_output_materialization_plan(
        maker_note_fixup_contract,
        image_data_copy_emitter,
        nikon_capture_block_payload_available=True,
        iptc_subdirectory_payload_available=True,
        maker_note_fixup_applier_available=True,
        maker_note_fixup_pointer_records_available=(
            nikon_capture_discovery is not None
            and nikon_capture_discovery.can_supply_existing_capture_data
        ),
        offset_value_position_fixups_available=(
            image_data_copy_emitter is not None and image_data_copy_emitter.can_emit_bytes
        ),
    )
    requested_inner_payloads = requested_nef_inner_payloads(raw_family_classification)
    blockers = list(final_output_materialization.remaining_blockers)
    has_capture_payload = (
        nikon_capture_discovery is not None
        and nikon_capture_discovery.can_supply_existing_capture_data
    )
    has_iptc_entry = (
        nikon_capture_discovery is not None
        and nikon_capture_discovery.can_supply_existing_iptc_entry
    )
    if (
        any(payload.kind == "nikon_capture_scalar_payload" for payload in requested_inner_payloads)
        and not has_capture_payload
    ):
        append_unique(blockers, "requires_existing_nikon_capture_data_payload")
    if (
        any(payload.kind == "nikon_capture_iptc_payload" for payload in requested_inner_payloads)
        and not has_iptc_entry
    ):
        append_unique(blockers, "requires_existing_nikon_capture_iptc_entry")
    if (
        any(payload.kind == "nef_tiff_iptc_naa_payload" for payload in requested_inner_payloads)
        and not tiff_iptc_naa_payload_available
    ):
        append_unique(blockers, "requires_nef_tiff_iptc_naa_rebuild")
    return NikonNefNativePromotionPlan(
        status=(
            "unsupported"
            if final_output_materialization.status == "unsupported"
            else "native_output_deferred"
        ),
        can_promote_native=False,
        action=NIKON_NEF_NATIVE_ACTION,
        raw_family_request_id=(
            raw_family_classification.request_id if raw_family_classification is not None else None
        ),
        requested_inner_payloads=requested_inner_payloads,
        final_output_materialization=final_output_materialization,
        remaining_blockers=tuple(blockers),
        evidence_ids=unique_evidence_ids(
            (
                NIKON_TYPE2_SOURCE,
                MAKER_NOTES_NIKON_TYPE2_LOCATION_SOURCE,
                NIKON_CAPTURE_TAGS_SOURCE,
                NIKON_CAPTURE_WRITE_SOURCE,
                IPTC_CAPTION_ABSTRACT_SOURCE,
                EXIF_IPTC_NAA_SOURCE,
                WRITE_IPTC_SOURCE,
                WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
                WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
                WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
            )
        ),
    )


def requested_nef_inner_payloads(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> tuple[NikonNefRequestedInnerPayload, ...]:
    if raw_family_classification is None:
        return ()
    payloads: list[NikonNefRequestedInnerPayload] = []
    for argument in raw_family_classification.arguments:
        if "nef_nikon_capture_scalar" in argument.target_surfaces:
            payloads.append(
                NikonNefRequestedInnerPayload(
                    kind="nikon_capture_scalar_payload",
                    requested_tag=argument.requested_tag,
                    requested_value=argument.requested_value,
                    evidence_ids=(NIKON_CAPTURE_TAGS_SOURCE, NIKON_CAPTURE_WRITE_SOURCE),
                )
            )
        if "nef_nikon_capture_iptc" in argument.target_surfaces:
            payloads.append(
                NikonNefRequestedInnerPayload(
                    kind="nikon_capture_iptc_payload",
                    requested_tag=argument.requested_tag,
                    requested_value=argument.requested_value,
                    evidence_ids=(
                        NIKON_CAPTURE_TAGS_SOURCE,
                        NIKON_CAPTURE_WRITE_SOURCE,
                        IPTC_CAPTION_ABSTRACT_SOURCE,
                    ),
                )
            )
        if "nef_tiff_iptc_naa" in argument.target_surfaces:
            payloads.append(
                NikonNefRequestedInnerPayload(
                    kind="nef_tiff_iptc_naa_payload",
                    requested_tag=argument.requested_tag,
                    requested_value=argument.requested_value,
                    evidence_ids=(
                        WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
                        IPTC_CAPTION_ABSTRACT_SOURCE,
                    ),
                )
            )
    return tuple(payloads)


def requested_nef_caption_abstract(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> str | None:
    if raw_family_classification is None:
        return None
    for argument in raw_family_classification.arguments:
        if (
            argument.requested_tag == "Caption-abstract"
            and "nef_tiff_iptc_naa" in argument.target_surfaces
        ):
            return argument.requested_value
    return None


def nikon_nef_makernote_fixup_rules() -> tuple[NikonNefMakerNoteFixupRule, ...]:
    return (
        NikonNefMakerNoteFixupRule(
            kind="locate_ifd_before_rewrite",
            description=(
                "Locate IFD-style MakerNotes before calling WriteDirectory so fixup offsets "
                "are relative to the discovered subdirectory location."
            ),
            evidence_ids=(WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,),
        ),
        NikonNefMakerNoteFixupRule(
            kind="allocate_subdirectory_fixup",
            description=(
                "Attach a fresh Fixup ledger to the MakerNote subdirectory rewrite and "
                "discard unchanged subdirectories only when no fixups were produced."
            ),
            evidence_ids=(WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,),
        ),
        NikonNefMakerNoteFixupRule(
            kind="restore_existing_header_before_subdir",
            description=(
                "Preserve the original MakerNote bytes before the located subdirectory and "
                "substitute only the rebuilt subdirectory payload."
            ),
            evidence_ids=(WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,),
        ),
        NikonNefMakerNoteFixupRule(
            kind="relative_offset_shift",
            description=(
                "For relative MakerNotes, shift fixup starts by the located header length "
                "and convert offsets to the rewritten base before value reinsertion."
            ),
            evidence_ids=(WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,),
        ),
        NikonNefMakerNoteFixupRule(
            kind="absolute_offset_shift",
            description=(
                "For non-relative MakerNotes, shift fixup starts by value length plus the "
                "located header length and apply base/fixed-by offset corrections."
            ),
            evidence_ids=(WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,),
        ),
        NikonNefMakerNoteFixupRule(
            kind="preview_image_marker_fixup",
            description=(
                "When preview metadata is present, keep only PreviewImage marker pointers "
                "and defer their value fixup with the MakerNote value."
            ),
            evidence_ids=(
                WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
                NIKON_PREVIEW_IFD_SOURCE,
            ),
        ),
    )


def image_data_pairs_from_ifd(
    data: bytes,
    ifd_name: str,
    entries: tuple[NikonNefIfdEntry, ...],
) -> tuple[NikonNefImageDataPair, ...]:
    return tuple(
        pair
        for pair in (
            build_image_data_pair(
                data,
                ifd_name,
                entries,
                "strip_image_data",
                STRIP_OFFSETS_TAG,
                STRIP_BYTE_COUNTS_TAG,
                (
                    EXIF_IMAGE_DATA_OFFSET_PAIR_SOURCE,
                    EXIF_IMAGE_DATA_BYTE_COUNT_SOURCE,
                    WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
                ),
            ),
            build_image_data_pair(
                data,
                ifd_name,
                entries,
                "tile_image_data",
                TILE_OFFSETS_TAG,
                TILE_BYTE_COUNTS_TAG,
                (
                    EXIF_TILE_IMAGE_DATA_SOURCE,
                    WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
                ),
            ),
        )
        if pair is not None
    )


def build_image_data_pair(
    data: bytes,
    ifd_name: str,
    entries: tuple[NikonNefIfdEntry, ...],
    kind: NikonNefImageDataPairKind,
    offset_tag: int,
    byte_count_tag: int,
    evidence_ids: tuple[EvidenceId, ...],
) -> NikonNefImageDataPair | None:
    offset_entry = first_entry_for_tag(entries, offset_tag)
    byte_count_entry = first_entry_for_tag(entries, byte_count_tag)
    if offset_entry is None or byte_count_entry is None:
        return None

    counts_match = len(offset_entry.values) == len(byte_count_entry.values)
    segment_count = min(len(offset_entry.values), len(byte_count_entry.values))
    segments = tuple(
        NikonNefImageDataSegment(
            offset=offset_entry.values[index],
            byte_count=byte_count_entry.values[index],
            in_bounds=(
                offset_entry.values[index] <= len(data)
                and byte_count_entry.values[index] <= len(data) - offset_entry.values[index]
            ),
        )
        for index in range(segment_count)
    )
    all_segments_in_bounds = all(segment.in_bounds for segment in segments)
    return NikonNefImageDataPair(
        ifd_name=ifd_name,
        kind=kind,
        offset_tag=offset_tag,
        byte_count_tag=byte_count_tag,
        offset_value_field_offset=offset_entry.value_field_offset,
        byte_count_value_field_offset=byte_count_entry.value_field_offset,
        offset_count=offset_entry.count,
        byte_count_count=byte_count_entry.count,
        counts_match=counts_match,
        all_segments_in_bounds=all_segments_in_bounds,
        copy_deferred_by_writeexif=kind in ("strip_image_data", "tile_image_data"),
        segments=segments,
        evidence_ids=evidence_ids,
    )


def image_data_preservation_blockers(
    pairs: tuple[NikonNefImageDataPair, ...],
) -> tuple[str, ...]:
    blockers: list[str] = ["requires_writeexif_offsetinfo_copy_emitter"]
    if not pairs:
        blockers.append("requires_image_data_offset_pair_discovery")
    if any(not pair.counts_match for pair in pairs):
        blockers.append("requires_matching_offset_and_byte_count_cardinality")
    if any(not pair.all_segments_in_bounds for pair in pairs):
        blockers.append("requires_bounded_image_data_segments")
    return tuple(blockers)


def requested_mutations_from_raw_family(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> tuple[NikonNefRequestedMutation, ...]:
    if raw_family_classification is None:
        return ()
    return tuple(
        NikonNefRequestedMutation(
            requested_tag=argument.requested_tag,
            requested_value=argument.requested_value,
            generic_surfaces=argument.target_surfaces,
            generic_blockers=argument.blocker_codes,
        )
        for argument in raw_family_classification.arguments
    )


def raw_family_classification_is_nef(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> bool:
    if raw_family_classification is None:
        return True
    return (
        raw_family_classification.container == "nef_tiff_nikon"
        and raw_family_classification.status == "source_mapped_deferred"
        and all(
            "nef_tiff_iptc_naa" in argument.target_surfaces
            or "nef_nikon_capture_iptc" in argument.target_surfaces
            or "nef_nikon_capture_scalar" in argument.target_surfaces
            for argument in raw_family_classification.arguments
        )
    )


def nikon_nef_mutation_steps() -> tuple[NikonNefMutationStep, ...]:
    return (
        NikonNefMutationStep(
            kind="validate_nef_tiff_header",
            description="Validate the NEF classic TIFF header before any Nikon-specific rewrite.",
            prerequisites=("classic_tiff_header", "requested_nef_raw_family_route"),
            safety_gates=("defer_without_full_tiff_rebuilder",),
            evidence_ids=(NIKON_TYPE2_SOURCE, WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE),
        ),
        NikonNefMutationStep(
            kind="prescan_nikon_makernote_keys",
            description="Pre-scan SerialNumber and ShutterCount keys used by Nikon encrypted data.",
            prerequisites=("nikon_type2_makernote",),
            safety_gates=("defer_without_nikon_key_prescan",),
            evidence_ids=(NIKON_PROCESS_SOURCE,),
        ),
        NikonNefMutationStep(
            kind="rewrite_nef_tiff_directories",
            description="Run the TIFF/EXIF directory rebuild that hosts Nikon MakerNotes and IPTC.",
            prerequisites=("classic_tiff_header", "writeexif_offset_tracking"),
            safety_gates=("defer_without_full_tiff_rebuilder",),
            evidence_ids=(WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,),
        ),
        NikonNefMutationStep(
            kind="apply_nikon_makernote_fixups",
            description=(
                "Apply WriteExif MakerNote fixups before reinserting rebuilt Nikon Type2 data."
            ),
            prerequisites=("nikon_type2_makernote", "writeexif_offset_tracking"),
            safety_gates=("defer_without_makernote_fixup_application",),
            evidence_ids=(WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE, NIKON_PREVIEW_IFD_SOURCE),
        ),
        NikonNefMutationStep(
            kind="rewrite_nikon_capture_scalar_entries",
            description=(
                "Rewrite PhotoEffects and VignetteControlIntensity inside NikonCaptureData."
            ),
            prerequisites=("nikon_capture_data_block",),
            safety_gates=("defer_without_nikon_capture_block_rewriter",),
            evidence_ids=(NIKON_CAPTURE_TAGS_SOURCE, NIKON_CAPTURE_WRITE_SOURCE),
        ),
        NikonNefMutationStep(
            kind="rewrite_nikon_capture_iptc_subdirectory",
            description=(
                "Rewrite Caption-Abstract through the IPTC subdirectory in NikonCaptureData."
            ),
            prerequisites=("nikon_capture_data_block",),
            safety_gates=(
                "defer_without_nikon_capture_block_rewriter",
                "defer_without_iptc_subdirectory_rewriter",
            ),
            evidence_ids=(NIKON_CAPTURE_TAGS_SOURCE, NIKON_CAPTURE_WRITE_SOURCE),
        ),
        NikonNefMutationStep(
            kind="preserve_preview_image_offsets",
            description="Keep protected Nikon PreviewIFD offset/length pairs consistent.",
            prerequisites=("writeexif_offset_tracking",),
            safety_gates=("defer_without_preview_offset_pair_protection",),
            evidence_ids=(NIKON_PREVIEW_IFD_SOURCE,),
        ),
        NikonNefMutationStep(
            kind="copy_image_data_after_offset_fixups",
            description="Copy image data only after WriteExif offsetInfo fixups are resolved.",
            prerequisites=("writeexif_offset_tracking",),
            safety_gates=("defer_without_image_data_fixups",),
            evidence_ids=(WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,),
        ),
    )


def plan_evidence_ids(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> tuple[EvidenceId, ...]:
    references = [
        NIKON_TYPE2_SOURCE,
        NIKON_PREVIEW_IFD_SOURCE,
        NIKON_PROCESS_SOURCE,
        NIKON_CAPTURE_MAKERNOTE_SOURCE,
        NIKON_CAPTURE_TAGS_SOURCE,
        NIKON_CAPTURE_WRITE_SOURCE,
        EXIF_IPTC_NAA_SOURCE,
        WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
        WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE,
        WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
    ]
    return unique_evidence_ids(tuple(references))


def unique_safety_gates(
    steps: tuple[NikonNefMutationStep, ...],
) -> tuple[NikonNefSafetyGate, ...]:
    safety_gates: list[NikonNefSafetyGate] = []
    for step in steps:
        for safety_gate in step.safety_gates:
            if safety_gate not in safety_gates:
                safety_gates.append(safety_gate)
    return tuple(safety_gates)
