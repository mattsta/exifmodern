"""Typed CR2 TIFF/IFD mutation-engine plan.

The plan is source-backed by oracle's CR2 writer, but it intentionally stops
at decomposition and validation.  CR2 byte rewriting must wait for a real TIFF
directory mutation engine with image-data offset preservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.canon_raw.write_plan import (
    CANON_FOCAL_PLANE_X_SIZE_SOURCE,
    CANON_OWNER_NAME_SOURCE,
    CR2_IPTC_DIRECTORY_SOURCE,
    EXIF_EXPOSURE_COMPENSATION_SOURCE,
    EXIF_OWNER_NAME_SOURCE,
    IPTC_KEYWORDS_SOURCE,
    WRITE_CR2_SOURCE,
    CanonRawWriteRequestClassification,
    CanonRawWriteSurface,
)
from exifmodern.formats.tiff.primitives import (
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_u16,
    read_u32,
)
from exifmodern.json_types import JsonObject

type EvidenceId = str

type Cr2HeaderStatus = Literal[
    "recognized_cr2",
    "unsupported_canon_raw",
    "unsupported_canon_1d_raw",
    "unrecognized",
    "truncated",
]
type Cr2ByteOrder = Literal["little", "big", "unknown"]
type TiffByteOrder = Literal["little", "big"]
type Cr2HeaderRebuildStatus = Literal[
    "ready",
    "unsupported_header",
    "missing_last_ifd",
    "last_ifd_out_of_range",
]
type Cr2PayloadPreservationStatus = Literal[
    "ready",
    "unsupported_header",
    "negative_tiff_payload_length",
    "image_data_out_of_range",
    "image_data_overlap",
    "suffix_out_of_range",
    "suffix_overlaps_image_data",
]
type Cr2PayloadCopyLedgerStatus = Literal[
    "ready",
    "unsupported_header",
    "image_data_out_of_range",
    "image_data_overlap",
    "suffix_out_of_range",
    "suffix_overlaps_image_data",
]
type Cr2MutationPlanStatus = Literal["plan_only_deferred"]
type Cr2MutationPrerequisiteCode = Literal[
    "recognized_cr2_signature",
    "random_access_input_available",
    "tiff_write_directory_engine_available",
    "embedded_iptc_writer_available",
    "canon_makernote_binary_writer_available",
    "image_data_copy_engine_available",
    "file_suffix_preservation_available",
]
type Cr2MutationOperationCode = Literal[
    "validate_cr2_signature",
    "start_tiff_rewrite_at_byte_16",
    "rewrite_ifd0_and_linked_ifds",
    "rewrite_embedded_iptc_directory",
    "rewrite_exif_scalar_entries",
    "rewrite_canon_makernote_entries",
    "capture_last_ifd_offset",
    "rebuild_cr2_header",
    "copy_or_relocate_image_data",
    "preserve_non_tiff_file_suffix",
]
type Cr2MutationSafetyGateCode = Literal[
    "reject_non_cr2_signature",
    "root_ifd_must_survive",
    "header_pointers_rebased_to_byte_16",
    "last_ifd_pointer_available",
    "image_data_offsets_validated_before_copy",
    "non_tiff_suffix_preserved",
    "maker_note_model_conditions_preserved",
]
type Cr2MutationArtifact = Literal[
    "validated_cr2_header",
    "new_tiff_directory_data",
    "updated_iptc_payload",
    "updated_exif_entries",
    "updated_canon_makernote_entries",
    "last_ifd_offset",
    "rebuilt_16_byte_header",
    "copied_image_data",
    "preserved_non_tiff_suffix",
]

WRITE_EXIF_IFD_ORDER_SOURCE = "canon_raw.write_exif_ifd_order"
WRITE_EXIF_LAST_IFD_SOURCE = "canon_raw.write_exif_last_ifd"
WRITE_EXIF_IMAGE_DATA_SOURCE = "canon_raw.write_exif_image_data"
WRITE_EXIF_DEFERRED_IMAGE_DATA_COPY_SOURCE = "canon_raw.write_exif_deferred_image_data_copy"
WRITER_COPY_IMAGE_DATA_SOURCE = "canon_raw.writer_copy_image_data"
CANON_RAW_CR2_SUFFIX_TEST_SOURCE = "canon_raw.canon_raw_cr2_suffix_test"


@dataclass(frozen=True)
class Cr2HeaderInspection:
    status: Cr2HeaderStatus
    byte_order: Cr2ByteOrder
    ifd0_offset: int | None
    last_ifd_offset: int | None

    @property
    def recognized(self) -> bool:
        return self.status == "recognized_cr2"


@dataclass(frozen=True)
class Cr2HeaderRebuildPlan:
    status: Cr2HeaderRebuildStatus
    byte_order: Cr2ByteOrder
    original_ifd0_offset: int | None
    original_last_ifd_offset: int | None
    rebuilt_ifd0_offset: int | None
    rebuilt_last_ifd_offset: int | None
    rebuilt_header: bytes | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_emit_header(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class Cr2ImageDataCopyRange:
    original_offset: int
    byte_count: int
    output_offset: int
    padding_byte_count: int = 0

    @property
    def original_end_offset(self) -> int:
        return self.original_offset + self.byte_count


@dataclass(frozen=True)
class Cr2SourceByteRange:
    start_offset: int
    end_offset: int

    @property
    def byte_count(self) -> int:
        return self.end_offset - self.start_offset


@dataclass(frozen=True)
class Cr2ImageDataCopySegment:
    copy_order: int
    ifd_offset: int
    offset_tag_id: int
    byte_count_tag_id: int
    original_offset: int
    byte_count: int
    padding_byte_count: int = 0

    @property
    def original_end_offset(self) -> int:
        return self.original_offset + self.byte_count

    @property
    def source_range(self) -> Cr2SourceByteRange:
        return Cr2SourceByteRange(self.original_offset, self.original_end_offset)


@dataclass(frozen=True)
class Cr2PayloadCopyLedger:
    status: Cr2PayloadCopyLedgerStatus
    original_tiff_span: Cr2SourceByteRange | None
    image_data_segments: tuple[Cr2ImageDataCopySegment, ...]
    suffix_range: Cr2SourceByteRange | None
    copy_order: tuple[str, ...]
    blocked_segment: Cr2ImageDataCopySegment | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_copy_payload_segments(self) -> bool:
        return self.status == "ready"

    @property
    def can_emit_bytes(self) -> bool:
        return False

    def to_json(self) -> JsonObject:
        return {
            "blocked_segment": (
                cr2_image_data_copy_segment_to_json(self.blocked_segment)
                if self.blocked_segment is not None
                else None
            ),
            "can_copy_payload_segments": self.can_copy_payload_segments,
            "can_emit_bytes": self.can_emit_bytes,
            "copy_order": list(self.copy_order),
            "image_data_segments": [
                cr2_image_data_copy_segment_to_json(segment) for segment in self.image_data_segments
            ],
            "original_tiff_span": cr2_source_byte_range_to_json(self.original_tiff_span),
            "status": self.status,
            "suffix_range": cr2_source_byte_range_to_json(self.suffix_range),
        }


@dataclass(frozen=True)
class Cr2PayloadPreservationStage:
    status: Cr2PayloadPreservationStatus
    tiff_payload_length: int
    image_data_ranges: tuple[Cr2ImageDataCopyRange, ...]
    suffix_start_offset: int | None
    preserved_suffix_byte_count: int
    blocked_range: Cr2ImageDataCopyRange | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_stage_payload_copy(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class Cr2MutationPrerequisite:
    code: Cr2MutationPrerequisiteCode
    requirement: str
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class Cr2MutationOperation:
    order: int
    code: Cr2MutationOperationCode
    description: str
    requires: tuple[Cr2MutationPrerequisiteCode, ...]
    produces: tuple[Cr2MutationArtifact, ...]
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class Cr2MutationSafetyGate:
    code: Cr2MutationSafetyGateCode
    must_pass_before: Cr2MutationOperationCode
    invariant: str
    failure_response: str
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class Cr2TiffIfdMutationPlan:
    status: Cr2MutationPlanStatus
    requested_tags: tuple[str, ...]
    target_surfaces: tuple[CanonRawWriteSurface, ...]
    prerequisites: tuple[Cr2MutationPrerequisite, ...]
    operations: tuple[Cr2MutationOperation, ...]
    safety_gates: tuple[Cr2MutationSafetyGate, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    def to_json(self) -> JsonObject:
        return {
            "can_mutate_bytes": self.can_mutate_bytes,
            "operations": [
                {
                    "code": operation.code,
                    "description": operation.description,
                    "order": operation.order,
                    "produces": list(operation.produces),
                    "requires": list(operation.requires),
                }
                for operation in self.operations
            ],
            "prerequisites": [
                {
                    "code": prerequisite.code,
                    "requirement": prerequisite.requirement,
                }
                for prerequisite in self.prerequisites
            ],
            "requested_tags": list(self.requested_tags),
            "safety_gates": [
                {
                    "code": safety_gate.code,
                    "failure_response": safety_gate.failure_response,
                    "invariant": safety_gate.invariant,
                    "must_pass_before": safety_gate.must_pass_before,
                }
                for safety_gate in self.safety_gates
            ],
            "status": self.status,
            "target_surfaces": list(self.target_surfaces),
        }


def inspect_cr2_tiff_header(data: bytes) -> Cr2HeaderInspection:
    if len(data) < 16:
        return Cr2HeaderInspection("truncated", "unknown", None, None)

    byte_order = cr2_byte_order(data)
    ifd0_offset = read_tiff_u32(data, 4, byte_order)
    last_ifd_offset = read_tiff_u32(data, 12, byte_order)
    signature = data[8:12]
    if signature == b"CR\x02\x00":
        return Cr2HeaderInspection("recognized_cr2", byte_order, ifd0_offset, last_ifd_offset)
    if data[8:10] == b"CR":
        return Cr2HeaderInspection(
            "unsupported_canon_raw", byte_order, ifd0_offset, last_ifd_offset
        )
    if signature == b"\xba\xb0\xac\xbb":
        return Cr2HeaderInspection(
            "unsupported_canon_1d_raw", byte_order, ifd0_offset, last_ifd_offset
        )
    return Cr2HeaderInspection("unrecognized", byte_order, ifd0_offset, last_ifd_offset)


def plan_cr2_rebuilt_header(data: bytes, last_ifd_offset: int | None) -> Cr2HeaderRebuildPlan:
    """Build the exact 16-byte CR2 header replacement without emitting file bytes."""

    inspection = inspect_cr2_tiff_header(data[:16])
    if not inspection.recognized:
        return Cr2HeaderRebuildPlan(
            "unsupported_header",
            inspection.byte_order,
            inspection.ifd0_offset,
            inspection.last_ifd_offset,
            None,
            None,
            None,
            (WRITE_CR2_SOURCE,),
        )
    if last_ifd_offset is None:
        return Cr2HeaderRebuildPlan(
            "missing_last_ifd",
            inspection.byte_order,
            inspection.ifd0_offset,
            inspection.last_ifd_offset,
            None,
            None,
            None,
            (WRITE_CR2_SOURCE, WRITE_EXIF_LAST_IFD_SOURCE),
        )
    if last_ifd_offset < 0 or last_ifd_offset > 0xFFFFFFFF:
        return Cr2HeaderRebuildPlan(
            "last_ifd_out_of_range",
            inspection.byte_order,
            inspection.ifd0_offset,
            inspection.last_ifd_offset,
            None,
            None,
            None,
            (WRITE_CR2_SOURCE, WRITE_EXIF_LAST_IFD_SOURCE),
        )

    byte_order = tiff_byte_order_or_none(inspection.byte_order)
    if byte_order is None:
        return Cr2HeaderRebuildPlan(
            "unsupported_header",
            inspection.byte_order,
            inspection.ifd0_offset,
            inspection.last_ifd_offset,
            None,
            None,
            None,
            (WRITE_CR2_SOURCE,),
        )
    header = bytearray(data[:16])
    header[4:8] = (16).to_bytes(4, byteorder=byte_order)
    header[12:16] = last_ifd_offset.to_bytes(4, byteorder=byte_order)
    return Cr2HeaderRebuildPlan(
        "ready",
        inspection.byte_order,
        inspection.ifd0_offset,
        inspection.last_ifd_offset,
        16,
        last_ifd_offset,
        bytes(header),
        (WRITE_CR2_SOURCE, WRITE_EXIF_LAST_IFD_SOURCE),
    )


def stage_cr2_payload_preservation(
    data: bytes,
    tiff_payload_length: int,
    image_data_ranges: tuple[Cr2ImageDataCopyRange, ...],
    suffix_start_offset: int | None,
) -> Cr2PayloadPreservationStage:
    """Validate CR2 image-data copy windows and non-TIFF suffix preservation.

    This mirrors oracle's emit boundary without writing bytes: WriteCR2 emits
    the rebuilt 16-byte header and TIFF payload first, then copies ImageData.
    CanonRaw.t test 6 proves the non-TIFF suffix must survive unchanged.
    """

    inspection = inspect_cr2_tiff_header(data[:16])
    if not inspection.recognized:
        return cr2_payload_preservation_stage(
            "unsupported_header",
            tiff_payload_length,
            image_data_ranges,
            suffix_start_offset,
            0,
            None,
        )
    if tiff_payload_length < 0:
        return cr2_payload_preservation_stage(
            "negative_tiff_payload_length",
            tiff_payload_length,
            image_data_ranges,
            suffix_start_offset,
            0,
            None,
        )
    for copy_range in image_data_ranges:
        if (
            copy_range.original_offset < 0
            or copy_range.byte_count < 0
            or copy_range.padding_byte_count < 0
            or copy_range.output_offset < 16 + tiff_payload_length
            or copy_range.original_end_offset > len(data)
        ):
            return cr2_payload_preservation_stage(
                "image_data_out_of_range",
                tiff_payload_length,
                image_data_ranges,
                suffix_start_offset,
                0,
                copy_range,
            )

    ordered_ranges = tuple(
        sorted(image_data_ranges, key=lambda copy_range: copy_range.original_offset)
    )
    previous_end = 0
    for copy_range in ordered_ranges:
        if copy_range.original_offset < previous_end:
            return cr2_payload_preservation_stage(
                "image_data_overlap",
                tiff_payload_length,
                image_data_ranges,
                suffix_start_offset,
                0,
                copy_range,
            )
        previous_end = copy_range.original_end_offset + copy_range.padding_byte_count

    if suffix_start_offset is None:
        return cr2_payload_preservation_stage(
            "ready",
            tiff_payload_length,
            image_data_ranges,
            None,
            0,
            None,
        )
    if suffix_start_offset < 16 or suffix_start_offset > len(data):
        return cr2_payload_preservation_stage(
            "suffix_out_of_range",
            tiff_payload_length,
            image_data_ranges,
            suffix_start_offset,
            0,
            None,
        )
    if image_data_ranges and suffix_start_offset < previous_end:
        return cr2_payload_preservation_stage(
            "suffix_overlaps_image_data",
            tiff_payload_length,
            image_data_ranges,
            suffix_start_offset,
            0,
            ordered_ranges[-1],
        )
    return cr2_payload_preservation_stage(
        "ready",
        tiff_payload_length,
        image_data_ranges,
        suffix_start_offset,
        len(data) - suffix_start_offset,
        None,
    )


def build_cr2_payload_copy_ledger(data: bytes) -> Cr2PayloadCopyLedger:
    """Record oracle's CR2 image-data/suffix copy contract without emitting bytes."""

    inspection = inspect_cr2_tiff_header(data[:16])
    evidence_ids = (
        WRITE_CR2_SOURCE,
        WRITE_EXIF_IMAGE_DATA_SOURCE,
        WRITE_EXIF_DEFERRED_IMAGE_DATA_COPY_SOURCE,
        WRITER_COPY_IMAGE_DATA_SOURCE,
        CANON_RAW_CR2_SUFFIX_TEST_SOURCE,
    )
    if not inspection.recognized:
        return Cr2PayloadCopyLedger(
            "unsupported_header",
            None,
            (),
            None,
            (),
            None,
            evidence_ids,
        )

    image_data_segments = discover_cr2_image_data_segments(data)
    ordered_segments = tuple(
        sorted(
            image_data_segments,
            key=lambda segment: (segment.original_offset, segment.copy_order),
        )
    )
    previous_end = 16
    for segment in ordered_segments:
        if (
            segment.original_offset < 16
            or segment.byte_count < 0
            or segment.padding_byte_count < 0
            or segment.original_end_offset > len(data)
        ):
            return cr2_payload_copy_ledger(
                "image_data_out_of_range",
                None,
                image_data_segments,
                None,
                segment,
                evidence_ids,
            )
        if segment.original_offset < previous_end:
            return cr2_payload_copy_ledger(
                "image_data_overlap",
                None,
                image_data_segments,
                None,
                segment,
                evidence_ids,
            )
        previous_end = segment.original_end_offset + segment.padding_byte_count

    tiff_end = previous_end if ordered_segments else len(data)
    if tiff_end > len(data):
        return cr2_payload_copy_ledger(
            "suffix_out_of_range",
            None,
            image_data_segments,
            None,
            None,
            evidence_ids,
        )
    suffix_range = Cr2SourceByteRange(tiff_end, len(data)) if tiff_end < len(data) else None
    if suffix_range is not None and ordered_segments and suffix_range.start_offset < previous_end:
        return cr2_payload_copy_ledger(
            "suffix_overlaps_image_data",
            Cr2SourceByteRange(0, tiff_end),
            image_data_segments,
            suffix_range,
            ordered_segments[-1],
            evidence_ids,
        )
    return cr2_payload_copy_ledger(
        "ready",
        Cr2SourceByteRange(0, tiff_end),
        image_data_segments,
        suffix_range,
        None,
        evidence_ids,
    )


def cr2_payload_copy_ledger(
    status: Cr2PayloadCopyLedgerStatus,
    original_tiff_span: Cr2SourceByteRange | None,
    image_data_segments: tuple[Cr2ImageDataCopySegment, ...],
    suffix_range: Cr2SourceByteRange | None,
    blocked_segment: Cr2ImageDataCopySegment | None,
    evidence_ids: tuple[EvidenceId, ...],
) -> Cr2PayloadCopyLedger:
    copy_order = (
        "rebuilt_cr2_header",
        "rebuilt_tiff_payload",
        "copy_recorded_image_data_segments",
        "preserve_original_suffix_bytes",
    )
    return Cr2PayloadCopyLedger(
        status,
        original_tiff_span,
        image_data_segments,
        suffix_range,
        copy_order,
        blocked_segment,
        evidence_ids,
    )


def discover_cr2_image_data_segments(data: bytes) -> tuple[Cr2ImageDataCopySegment, ...]:
    header = parse_tiff_header(data)
    visited: set[int] = set()
    ifd_offsets = [header.first_ifd_offset]
    segments: list[Cr2ImageDataCopySegment] = []

    while ifd_offsets:
        ifd_offset = ifd_offsets.pop(0)
        if ifd_offset == 0 or ifd_offset in visited or ifd_offset >= len(data):
            continue
        visited.add(ifd_offset)
        ifd = parse_ifd(data, ifd_offset, header.endian)
        entries = {entry.tag_id: entry for entry in ifd.entries}
        segments.extend(
            image_data_segments_from_ifd_entries(data, ifd.offset, entries, header.endian)
        )
        for tag_id in (0x8769, 0x8825):
            entry = entries.get(tag_id)
            if entry is not None:
                ifd_offsets.extend(read_tiff_entry_values(data, entry, header.endian))
        subifd_entry = entries.get(0x014A)
        if subifd_entry is not None:
            ifd_offsets.extend(read_tiff_entry_values(data, subifd_entry, header.endian))
        if ifd.next_ifd_offset:
            ifd_offsets.append(ifd.next_ifd_offset)

    return tuple(
        Cr2ImageDataCopySegment(
            copy_order=index + 1,
            ifd_offset=segment.ifd_offset,
            offset_tag_id=segment.offset_tag_id,
            byte_count_tag_id=segment.byte_count_tag_id,
            original_offset=segment.original_offset,
            byte_count=segment.byte_count,
            padding_byte_count=segment.padding_byte_count,
        )
        for index, segment in enumerate(sorted(segments, key=lambda item: item.original_offset))
    )


def image_data_segments_from_ifd_entries(
    data: bytes,
    ifd_offset: int,
    entries: dict[int, IfdEntry],
    endian: TiffByteOrder,
) -> tuple[Cr2ImageDataCopySegment, ...]:
    segments: list[Cr2ImageDataCopySegment] = []
    for offset_tag_id, byte_count_tag_id in ((0x0111, 0x0117), (0x0144, 0x0145)):
        offset_entry = entries.get(offset_tag_id)
        byte_count_entry = entries.get(byte_count_tag_id)
        if offset_entry is None or byte_count_entry is None:
            continue
        offsets = read_tiff_entry_values(data, offset_entry, endian)
        byte_counts = read_tiff_entry_values(data, byte_count_entry, endian)
        for original_offset, byte_count in zip(offsets, byte_counts, strict=False):
            segments.append(
                Cr2ImageDataCopySegment(
                    0,
                    ifd_offset,
                    offset_tag_id,
                    byte_count_tag_id,
                    original_offset,
                    byte_count,
                )
            )
    return tuple(segments)


def read_tiff_entry_values(data: bytes, entry: IfdEntry, endian: TiffByteOrder) -> tuple[int, ...]:
    if entry.field_type == 3:
        unit_size = 2
        reader = read_u16
    elif entry.field_type == 4:
        unit_size = 4
        reader = read_u32
    else:
        return ()

    byte_count = entry.count * unit_size
    if byte_count <= 4:
        inline_value = entry.value_offset.to_bytes(4, byteorder=endian)
        return tuple(
            reader(inline_value, index * unit_size, endian) for index in range(entry.count)
        )
    if entry.value_offset < 0 or entry.value_offset + byte_count > len(data):
        return ()
    return tuple(
        reader(data, entry.value_offset + index * unit_size, endian) for index in range(entry.count)
    )


def cr2_source_byte_range_to_json(byte_range: Cr2SourceByteRange | None) -> JsonObject | None:
    if byte_range is None:
        return None
    return {
        "byte_count": byte_range.byte_count,
        "end_offset": byte_range.end_offset,
        "start_offset": byte_range.start_offset,
    }


def cr2_image_data_copy_segment_to_json(
    segment: Cr2ImageDataCopySegment | None,
) -> JsonObject | None:
    if segment is None:
        return None
    return {
        "byte_count": segment.byte_count,
        "byte_count_tag_id": segment.byte_count_tag_id,
        "copy_order": segment.copy_order,
        "ifd_offset": segment.ifd_offset,
        "offset_tag_id": segment.offset_tag_id,
        "original_end_offset": segment.original_end_offset,
        "original_offset": segment.original_offset,
        "padding_byte_count": segment.padding_byte_count,
        "source_range": cr2_source_byte_range_to_json(segment.source_range),
    }


def cr2_payload_preservation_stage(
    status: Cr2PayloadPreservationStatus,
    tiff_payload_length: int,
    image_data_ranges: tuple[Cr2ImageDataCopyRange, ...],
    suffix_start_offset: int | None,
    preserved_suffix_byte_count: int,
    blocked_range: Cr2ImageDataCopyRange | None,
) -> Cr2PayloadPreservationStage:
    return Cr2PayloadPreservationStage(
        status,
        tiff_payload_length,
        image_data_ranges,
        suffix_start_offset,
        preserved_suffix_byte_count,
        blocked_range,
        (
            WRITE_CR2_SOURCE,
            WRITE_EXIF_IMAGE_DATA_SOURCE,
            CANON_RAW_CR2_SUFFIX_TEST_SOURCE,
        ),
    )


def build_cr2_tiff_ifd_mutation_plan(
    classification: CanonRawWriteRequestClassification | None = None,
) -> Cr2TiffIfdMutationPlan:
    if classification is not None and classification.container_kind != "cr2_tiff":
        raise ValueError(f"Expected cr2_tiff classification, got {classification.container_kind}")
    requested_tags = (
        tuple(tag.requested_tag for tag in classification.tags) if classification else ()
    )
    target_surfaces = (
        tuple(
            dict.fromkeys(
                surface
                for tag in classification.tags
                for surface in tag.target_surfaces
                if surface.startswith("cr2_")
            )
        )
        if classification
        else ("cr2_tiff_iptc", "cr2_tiff_exif", "cr2_canon_makernote")
    )
    evidence_ids = unique_sources(
        (
            WRITE_CR2_SOURCE,
            WRITE_EXIF_IFD_ORDER_SOURCE,
            WRITE_EXIF_LAST_IFD_SOURCE,
            WRITE_EXIF_IMAGE_DATA_SOURCE,
            WRITE_EXIF_DEFERRED_IMAGE_DATA_COPY_SOURCE,
            WRITER_COPY_IMAGE_DATA_SOURCE,
            CANON_RAW_CR2_SUFFIX_TEST_SOURCE,
            CR2_IPTC_DIRECTORY_SOURCE,
            IPTC_KEYWORDS_SOURCE,
            EXIF_OWNER_NAME_SOURCE,
            EXIF_EXPOSURE_COMPENSATION_SOURCE,
            CANON_OWNER_NAME_SOURCE,
            CANON_FOCAL_PLANE_X_SIZE_SOURCE,
        )
    )
    return Cr2TiffIfdMutationPlan(
        status="plan_only_deferred",
        requested_tags=requested_tags,
        target_surfaces=target_surfaces,
        prerequisites=CR2_PREREQUISITES,
        operations=CR2_OPERATIONS,
        safety_gates=CR2_SAFETY_GATES,
        evidence_ids=evidence_ids,
    )


def cr2_byte_order(data: bytes) -> Cr2ByteOrder:
    if data[:4] == b"II*\x00":
        return "little"
    if data[:4] == b"MM\x00*":
        return "big"
    return "unknown"


def read_tiff_u32(data: bytes, offset: int, byte_order: Cr2ByteOrder) -> int | None:
    parsed_byte_order = tiff_byte_order_or_none(byte_order)
    if offset + 4 > len(data) or parsed_byte_order is None:
        return None
    return int.from_bytes(data[offset : offset + 4], byteorder=parsed_byte_order)


def tiff_byte_order_or_none(byte_order: Cr2ByteOrder) -> TiffByteOrder | None:
    if byte_order == "little":
        return byte_order
    if byte_order == "big":
        return byte_order
    return None


def unique_sources(references: tuple[EvidenceId, ...]) -> tuple[EvidenceId, ...]:
    unique: list[EvidenceId] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


CR2_PREREQUISITES: tuple[Cr2MutationPrerequisite, ...] = (
    Cr2MutationPrerequisite(
        "recognized_cr2_signature",
        "Input must have a supported CR2 signature at bytes 8-11.",
        (WRITE_CR2_SOURCE,),
    ),
    Cr2MutationPrerequisite(
        "random_access_input_available",
        "The writer needs RAF-backed random access before CR2 rewrite can begin.",
        (WRITE_CR2_SOURCE,),
    ),
    Cr2MutationPrerequisite(
        "tiff_write_directory_engine_available",
        "A TIFF IFD writer must rebuild IFD0 and linked directories from byte 16.",
        (WRITE_CR2_SOURCE, WRITE_EXIF_IFD_ORDER_SOURCE),
    ),
    Cr2MutationPrerequisite(
        "embedded_iptc_writer_available",
        "IPTC writes must flow through the TIFF IPTC-NAA subdirectory, not an appended block.",
        (CR2_IPTC_DIRECTORY_SOURCE, IPTC_KEYWORDS_SOURCE),
    ),
    Cr2MutationPrerequisite(
        "canon_makernote_binary_writer_available",
        "Canon maker-note fields require Canon-specific binary conversion and model gates.",
        (CANON_OWNER_NAME_SOURCE, CANON_FOCAL_PLANE_X_SIZE_SOURCE),
    ),
    Cr2MutationPrerequisite(
        "image_data_copy_engine_available",
        "Image data referenced by rewritten IFDs must be copied or relocated after directory data.",
        (WRITE_CR2_SOURCE, WRITE_EXIF_IMAGE_DATA_SOURCE, CANON_RAW_CR2_SUFFIX_TEST_SOURCE),
    ),
    Cr2MutationPrerequisite(
        "file_suffix_preservation_available",
        "The rewrite must preserve CR2 bytes after the TIFF/image-data payload that oracle keeps.",
        (CANON_RAW_CR2_SUFFIX_TEST_SOURCE,),
    ),
)

CR2_OPERATIONS: tuple[Cr2MutationOperation, ...] = (
    Cr2MutationOperation(
        1,
        "validate_cr2_signature",
        "Reject unsupported Canon RAW variants before any rewrite planning advances.",
        ("recognized_cr2_signature",),
        ("validated_cr2_header",),
        (WRITE_CR2_SOURCE,),
    ),
    Cr2MutationOperation(
        2,
        "start_tiff_rewrite_at_byte_16",
        "Set the TIFF rewrite base to byte 16, matching the CR2 header boundary.",
        ("recognized_cr2_signature", "tiff_write_directory_engine_available"),
        (),
        (WRITE_CR2_SOURCE,),
    ),
    Cr2MutationOperation(
        3,
        "rewrite_ifd0_and_linked_ifds",
        "Rebuild IFD0, SubIFD, EXIF, GPS, Interop, and linked IFD directories in WriteExif order.",
        ("tiff_write_directory_engine_available",),
        ("new_tiff_directory_data",),
        (WRITE_CR2_SOURCE, WRITE_EXIF_IFD_ORDER_SOURCE),
    ),
    Cr2MutationOperation(
        4,
        "rewrite_embedded_iptc_directory",
        "Materialize Keywords/Subject through the IFD0 IPTC-NAA protected subdirectory.",
        ("embedded_iptc_writer_available",),
        ("updated_iptc_payload",),
        (CR2_IPTC_DIRECTORY_SOURCE, IPTC_KEYWORDS_SOURCE),
    ),
    Cr2MutationOperation(
        5,
        "rewrite_exif_scalar_entries",
        "Apply scalar EXIF updates such as OwnerName and ExposureCompensation inside rebuilt IFDs.",
        ("tiff_write_directory_engine_available",),
        ("updated_exif_entries",),
        (EXIF_OWNER_NAME_SOURCE, EXIF_EXPOSURE_COMPENSATION_SOURCE),
    ),
    Cr2MutationOperation(
        6,
        "rewrite_canon_makernote_entries",
        "Apply Canon maker-note binary updates only after Canon conversion and model gates pass.",
        ("canon_makernote_binary_writer_available",),
        ("updated_canon_makernote_entries",),
        (CANON_OWNER_NAME_SOURCE, CANON_FOCAL_PLANE_X_SIZE_SOURCE),
    ),
    Cr2MutationOperation(
        7,
        "capture_last_ifd_offset",
        "Capture WriteExif's final linked-IFD marker for the last four bytes of the CR2 header.",
        ("tiff_write_directory_engine_available",),
        ("last_ifd_offset",),
        (WRITE_EXIF_LAST_IFD_SOURCE,),
    ),
    Cr2MutationOperation(
        8,
        "rebuild_cr2_header",
        "Copy the original 16-byte header, set IFD0 to 16, and set the final IFD pointer.",
        ("recognized_cr2_signature", "tiff_write_directory_engine_available"),
        ("rebuilt_16_byte_header",),
        (WRITE_CR2_SOURCE, WRITE_EXIF_LAST_IFD_SOURCE),
    ),
    Cr2MutationOperation(
        9,
        "copy_or_relocate_image_data",
        "Copy image data recorded by the TIFF rewrite engine after header and directory output.",
        ("image_data_copy_engine_available",),
        ("copied_image_data",),
        (WRITE_CR2_SOURCE, WRITE_EXIF_IMAGE_DATA_SOURCE),
    ),
    Cr2MutationOperation(
        10,
        "preserve_non_tiff_file_suffix",
        "Preserve the CR2 non-TIFF suffix bytes proven by CanonRaw.t test 6 after image-data copy.",
        ("image_data_copy_engine_available", "file_suffix_preservation_available"),
        ("preserved_non_tiff_suffix",),
        (CANON_RAW_CR2_SUFFIX_TEST_SOURCE,),
    ),
)

CR2_SAFETY_GATES: tuple[Cr2MutationSafetyGate, ...] = (
    Cr2MutationSafetyGate(
        "reject_non_cr2_signature",
        "validate_cr2_signature",
        "Bytes 8-11 must equal CR 02 00; Canon 1D RAW and unknown signatures stay unsupported.",
        "Abort with an unsupported Canon RAW classification before writing any output.",
        (WRITE_CR2_SOURCE,),
    ),
    Cr2MutationSafetyGate(
        "root_ifd_must_survive",
        "rewrite_ifd0_and_linked_ifds",
        "The TIFF rewrite must not delete the CR2 image IFD.",
        "Abort because oracle treats missing LastIFD as CR2 image IFD deletion.",
        (WRITE_CR2_SOURCE,),
    ),
    Cr2MutationSafetyGate(
        "header_pointers_rebased_to_byte_16",
        "rebuild_cr2_header",
        "The rebuilt header must set the IFD0 pointer to 16 even if the input was shifted.",
        "Abort rather than emit a CR2 whose header points at stale TIFF data.",
        (WRITE_CR2_SOURCE,),
    ),
    Cr2MutationSafetyGate(
        "last_ifd_pointer_available",
        "rebuild_cr2_header",
        "WriteExif must provide a final IFD offset when the top-level rewrite starts at byte 16.",
        "Abort rather than preserve or invent a stale last-IFD pointer.",
        (WRITE_EXIF_LAST_IFD_SOURCE,),
    ),
    Cr2MutationSafetyGate(
        "image_data_offsets_validated_before_copy",
        "copy_or_relocate_image_data",
        "All image-data records emitted by nested IFD rewrites must be validated before copying.",
        "Abort instead of copying raw image data with stale StripOffsets or byte counts.",
        (WRITE_EXIF_IMAGE_DATA_SOURCE, CANON_RAW_CR2_SUFFIX_TEST_SOURCE),
    ),
    Cr2MutationSafetyGate(
        "non_tiff_suffix_preserved",
        "preserve_non_tiff_file_suffix",
        "CR2 bytes after the copied image data must remain byte-for-byte preserved.",
        "Abort rather than emit a CR2 that fails oracle's non-TIFF suffix preservation check.",
        (CANON_RAW_CR2_SUFFIX_TEST_SOURCE,),
    ),
    Cr2MutationSafetyGate(
        "maker_note_model_conditions_preserved",
        "rewrite_canon_makernote_entries",
        "Canon maker-note writes must preserve tag-specific conversions and model conditions.",
        "Defer maker-note mutation until Canon binary-data helpers can enforce these conditions.",
        (CANON_OWNER_NAME_SOURCE, CANON_FOCAL_PLANE_X_SIZE_SOURCE),
    ),
)
