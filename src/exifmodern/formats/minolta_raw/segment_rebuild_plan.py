"""Minolta MRW segment rebuild primitives.

ExifTool's MRW writer rebuilds the metadata segment buffer and then streams the
raw image data unchanged.  This module models that byte choreography and exposes
a gated byte emitter for already-rewritten segment payloads.  It does not
perform TTW TIFF or BinaryData tag mutation itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.minolta_raw.mutation_plan import (
    MINOLTA_RAW_BINARY_EVIDENCE_ID,
    MINOLTA_RAW_MAIN_EVIDENCE_ID,
    MINOLTA_RAW_RIF_EVIDENCE_ID,
    MINOLTA_RAW_WBG_EVIDENCE_ID,
    MINOLTA_RAW_WRITE_EVIDENCE_ID,
    MRW_SEGMENT_HEADER_SIZE,
    MRW_SEGMENT_NAMES,
    WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
    MinoltaMrwMutationPlan,
    MinoltaMrwSafetyGate,
    MinoltaMrwSegmentName,
    MrwByteOrder,
    build_minolta_mrw_mutation_plan,
    read_uint,
    unique_evidence_ids,
    unique_safety_gates,
)
from exifmodern.json_types import JsonObject

type MinoltaMrwSegmentRebuildPlanStatus = Literal[
    "source_mapped_non_mutating",
    "unsupported",
]
type MinoltaMrwSegmentRebuildAction = Literal[
    "copy_original_segment",
    "handoff_ttw_to_tiff_writer",
    "rewrite_binary_subdirectory",
    "copy_padding_segment",
    "copy_unknown_segment",
]
type MinoltaMrwReplacementWriter = Literal[
    "tiff_writer",
    "binary_data_writer",
]
type MinoltaMrwReplacementOutcome = Literal[
    "written_payload",
    "copy_original_on_undef",
    "omit_empty_defined",
]
type MinoltaMrwBinaryDataTableName = Literal[
    "Image::ExifTool::MinoltaRaw::PRD",
    "Image::ExifTool::MinoltaRaw::WBG",
    "Image::ExifTool::MinoltaRaw::RIF",
]

MRW_HEADER_SIZE = 8
MRW_RAW_PARENT = "MRW"
MRW_TTW_TAG = b"\0TTW"
MRW_BINARY_SUBDIRECTORY_TAGS = frozenset((b"\0PRD", b"\0WBG", b"\0RIF"))


@dataclass(frozen=True)
class MrwByteRange:
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
class MinoltaMrwSegmentReplacement:
    segment_index: int
    writer: MinoltaMrwReplacementWriter
    payload: bytes = b""
    outcome: MinoltaMrwReplacementOutcome = "written_payload"


@dataclass(frozen=True)
class MinoltaMrwTtwRewriteHandoff:
    segment_index: int
    input_payload_range: MrwByteRange
    tag_table: str
    process_proc: str
    data_pos: int
    dir_start: int
    dir_len: int
    dir_name: str
    parent: str
    no_tiff_end: bool
    wrong_base_shift: int
    write_proc: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "data_pos": self.data_pos,
            "dir_len": self.dir_len,
            "dir_name": self.dir_name,
            "dir_start": self.dir_start,
            "input_payload_range": self.input_payload_range.to_json(),
            "no_tiff_end": self.no_tiff_end,
            "parent": self.parent,
            "process_proc": self.process_proc,
            "segment_index": self.segment_index,
            "tag_table": self.tag_table,
            "write_proc": self.write_proc,
            "wrong_base_shift": self.wrong_base_shift,
        }


@dataclass(frozen=True)
class MinoltaMrwBinaryDataRewriteHandoff:
    segment_index: int
    segment_name: MinoltaMrwSegmentName
    input_payload_range: MrwByteRange
    tag_table: MinoltaMrwBinaryDataTableName
    process_proc: str
    write_proc: str
    check_proc: str
    writable: bool
    first_entry: int
    data_pos: int
    dir_start: int
    dir_len: int
    dir_name: str
    parent: str
    no_tiff_end: bool
    wrong_base_shift: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "check_proc": self.check_proc,
            "data_pos": self.data_pos,
            "dir_len": self.dir_len,
            "dir_name": self.dir_name,
            "dir_start": self.dir_start,
            "first_entry": self.first_entry,
            "input_payload_range": self.input_payload_range.to_json(),
            "no_tiff_end": self.no_tiff_end,
            "parent": self.parent,
            "process_proc": self.process_proc,
            "segment_index": self.segment_index,
            "segment_name": self.segment_name,
            "tag_table": self.tag_table,
            "writable": self.writable,
            "write_proc": self.write_proc,
            "wrong_base_shift": self.wrong_base_shift,
        }


@dataclass(frozen=True)
class MinoltaMrwPaddingDecision:
    copied_original: bool
    input_payload_length: int
    padding_length: int
    output_payload_length: int

    def to_json(self) -> JsonObject:
        return {
            "copied_original": self.copied_original,
            "input_payload_length": self.input_payload_length,
            "output_payload_length": self.output_payload_length,
            "padding_length": self.padding_length,
        }


@dataclass(frozen=True)
class MinoltaMrwSegmentRebuildOperation:
    index: int
    tag_bytes_hex: str
    segment_name: MinoltaMrwSegmentName
    action: MinoltaMrwSegmentRebuildAction
    original_segment_range: MrwByteRange
    original_payload_range: MrwByteRange
    planned_output_range: MrwByteRange
    original_payload_length: int
    rewritten_payload_length: int | None
    planned_payload_length: int
    padding: MinoltaMrwPaddingDecision
    length_field_value: int
    emits_segment: bool
    ttw_handoff: MinoltaMrwTtwRewriteHandoff | None
    binary_data_handoff: MinoltaMrwBinaryDataRewriteHandoff | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "emits_segment": self.emits_segment,
            "index": self.index,
            "length_field_value": self.length_field_value,
            "original_payload_length": self.original_payload_length,
            "original_payload_range": self.original_payload_range.to_json(),
            "original_segment_range": self.original_segment_range.to_json(),
            "padding": self.padding.to_json(),
            "planned_output_range": self.planned_output_range.to_json(),
            "planned_payload_length": self.planned_payload_length,
            "rewritten_payload_length": self.rewritten_payload_length,
            "segment_name": self.segment_name,
            "tag_bytes_hex": self.tag_bytes_hex,
            "ttw_handoff": (self.ttw_handoff.to_json() if self.ttw_handoff is not None else None),
            "binary_data_handoff": (
                self.binary_data_handoff.to_json() if self.binary_data_handoff is not None else None
            ),
        }


@dataclass(frozen=True)
class MinoltaMrwMetadataLengthRewrite:
    length_field_range: MrwByteRange
    old_metadata_length: int
    planned_metadata_length: int
    rewrite_required: bool
    byte_order: MrwByteOrder
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_order": self.byte_order,
            "length_field_range": self.length_field_range.to_json(),
            "old_metadata_length": self.old_metadata_length,
            "planned_metadata_length": self.planned_metadata_length,
            "rewrite_required": self.rewrite_required,
        }


@dataclass(frozen=True)
class MinoltaMrwRawImageDataCopy:
    source_range: MrwByteRange
    planned_output_offset: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "planned_output_offset": self.planned_output_offset,
            "source_range": self.source_range.to_json(),
        }


@dataclass(frozen=True)
class MinoltaMrwSegmentRebuildPlan:
    status: MinoltaMrwSegmentRebuildPlanStatus
    can_mutate: bool
    mutation_plan: MinoltaMrwMutationPlan
    segments: tuple[MinoltaMrwSegmentRebuildOperation, ...]
    ttw_handoffs: tuple[MinoltaMrwTtwRewriteHandoff, ...]
    binary_data_handoffs: tuple[MinoltaMrwBinaryDataRewriteHandoff, ...]
    metadata_length_rewrite: MinoltaMrwMetadataLengthRewrite | None
    raw_image_data_copy: MinoltaMrwRawImageDataCopy | None
    safety_gates: tuple[MinoltaMrwSafetyGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_mutate": self.can_mutate,
            "metadata_length_rewrite": (
                self.metadata_length_rewrite.to_json()
                if self.metadata_length_rewrite is not None
                else None
            ),
            "mutation_plan": self.mutation_plan.to_json(),
            "raw_image_data_copy": (
                self.raw_image_data_copy.to_json() if self.raw_image_data_copy is not None else None
            ),
            "safety_gates": list(self.safety_gates),
            "segments": [segment.to_json() for segment in self.segments],
            "status": self.status,
            "ttw_handoffs": [handoff.to_json() for handoff in self.ttw_handoffs],
            "binary_data_handoffs": [handoff.to_json() for handoff in self.binary_data_handoffs],
        }


class MinoltaMrwSegmentEmissionError(ValueError):
    """Raised when an MRW segment rebuild cannot safely emit bytes."""


def build_minolta_mrw_segment_rebuild_plan(
    data: bytes,
    replacements: tuple[MinoltaMrwSegmentReplacement, ...] = (),
) -> MinoltaMrwSegmentRebuildPlan:
    mutation_plan = build_minolta_mrw_mutation_plan(data)
    header = mutation_plan.header
    evidence_ids = segment_rebuild_evidence_ids(mutation_plan)
    safety_gates = segment_rebuild_safety_gates(mutation_plan)
    if header is None:
        return MinoltaMrwSegmentRebuildPlan(
            status="unsupported",
            can_mutate=False,
            mutation_plan=mutation_plan,
            segments=(),
            ttw_handoffs=(),
            binary_data_handoffs=(),
            metadata_length_rewrite=None,
            raw_image_data_copy=None,
            safety_gates=safety_gates,
            evidence_ids=evidence_ids,
        )

    replacement_by_index = replacement_index_map(replacements)
    if replacement_by_index is None:
        return MinoltaMrwSegmentRebuildPlan(
            status="unsupported",
            can_mutate=False,
            mutation_plan=mutation_plan,
            segments=(),
            ttw_handoffs=(),
            binary_data_handoffs=(),
            metadata_length_rewrite=None,
            raw_image_data_copy=None,
            safety_gates=safety_gates,
            evidence_ids=evidence_ids,
        )
    enumerated = enumerate_mrw_segment_rebuild_operations(
        data=data,
        metadata_end_offset=header.metadata_end_offset,
        byte_order=header.byte_order,
        replacements=replacement_by_index,
    )
    if enumerated is None:
        return MinoltaMrwSegmentRebuildPlan(
            status="unsupported",
            can_mutate=False,
            mutation_plan=mutation_plan,
            segments=(),
            ttw_handoffs=(),
            binary_data_handoffs=(),
            metadata_length_rewrite=None,
            raw_image_data_copy=None,
            safety_gates=safety_gates,
            evidence_ids=evidence_ids,
        )

    segments, planned_metadata_length = enumerated
    ttw_handoffs = tuple(
        segment.ttw_handoff for segment in segments if segment.ttw_handoff is not None
    )
    binary_data_handoffs = tuple(
        segment.binary_data_handoff
        for segment in segments
        if segment.binary_data_handoff is not None
    )
    metadata_length_rewrite = MinoltaMrwMetadataLengthRewrite(
        length_field_range=MrwByteRange(4, 8),
        old_metadata_length=header.metadata_length,
        planned_metadata_length=planned_metadata_length,
        rewrite_required=planned_metadata_length != header.metadata_length,
        byte_order=header.byte_order,
        evidence_ids=(MINOLTA_RAW_WRITE_EVIDENCE_ID,),
    )
    raw_image_data_copy = MinoltaMrwRawImageDataCopy(
        source_range=MrwByteRange(header.metadata_end_offset, len(data)),
        planned_output_offset=MRW_HEADER_SIZE + planned_metadata_length,
        evidence_ids=(MINOLTA_RAW_WRITE_EVIDENCE_ID,),
    )

    return MinoltaMrwSegmentRebuildPlan(
        status="source_mapped_non_mutating",
        can_mutate=False,
        mutation_plan=mutation_plan,
        segments=segments,
        ttw_handoffs=ttw_handoffs,
        binary_data_handoffs=binary_data_handoffs,
        metadata_length_rewrite=metadata_length_rewrite,
        raw_image_data_copy=raw_image_data_copy,
        safety_gates=safety_gates,
        evidence_ids=evidence_ids,
    )


def emit_minolta_mrw_segment_rebuild_bytes(
    data: bytes,
    replacements: tuple[MinoltaMrwSegmentReplacement, ...] = (),
) -> bytes:
    """Rebuild MRW bytes from source-backed segment replacement payloads.

    Replacement payloads are expected to be the complete output of the relevant
    segment writer.  This function only performs the MRW container operation
    shown in MinoltaRaw.pm: segment header emission, four-byte payload padding,
    metadata-length rewrite, and raw image-data copy.
    """

    replacement_by_index = replacement_index_map(replacements)
    if replacement_by_index is None:
        raise MinoltaMrwSegmentEmissionError("duplicate MRW segment replacement index")

    plan = build_minolta_mrw_segment_rebuild_plan(data, replacements)
    header = plan.mutation_plan.header
    metadata_length_rewrite = plan.metadata_length_rewrite
    raw_image_data_copy = plan.raw_image_data_copy
    if (
        plan.status != "source_mapped_non_mutating"
        or header is None
        or metadata_length_rewrite is None
        or raw_image_data_copy is None
    ):
        raise MinoltaMrwSegmentEmissionError("MRW segment rebuild output is gated")

    output = bytearray()
    output.extend(data[:4])
    output.extend(metadata_length_rewrite.planned_metadata_length.to_bytes(4, header.byte_order))
    for segment in plan.segments:
        if not segment.emits_segment:
            continue
        tag_start = segment.original_segment_range.start_offset
        tag_bytes = data[tag_start : tag_start + 4]
        replacement = replacement_by_index.get(segment.index)
        if replacement is None or replacement.outcome == "copy_original_on_undef":
            payload_start = segment.original_payload_range.start_offset
            payload_end = segment.original_payload_range.end_offset
            payload = data[payload_start:payload_end]
        else:
            payload = pad_mrw_segment_payload(replacement.payload)
        if len(payload) != segment.length_field_value:
            raise MinoltaMrwSegmentEmissionError("MRW segment length plan mismatch")
        output.extend(tag_bytes)
        output.extend(segment.length_field_value.to_bytes(4, header.byte_order))
        output.extend(payload)

    output.extend(data[raw_image_data_copy.source_range.start_offset :])
    return bytes(output)


def enumerate_mrw_segment_rebuild_operations(
    data: bytes,
    metadata_end_offset: int,
    byte_order: MrwByteOrder,
    replacements: dict[int, MinoltaMrwSegmentReplacement],
) -> tuple[tuple[MinoltaMrwSegmentRebuildOperation, ...], int] | None:
    segments: list[MinoltaMrwSegmentRebuildOperation] = []
    input_position = MRW_HEADER_SIZE
    output_position = MRW_HEADER_SIZE
    index = 0
    while input_position < metadata_end_offset:
        if input_position + MRW_SEGMENT_HEADER_SIZE > metadata_end_offset:
            return None
        tag_bytes = data[input_position : input_position + 4]
        original_payload_length = read_uint(data, input_position + 4, byte_order)
        payload_start = input_position + MRW_SEGMENT_HEADER_SIZE
        payload_end = payload_start + original_payload_length
        if payload_end > metadata_end_offset:
            return None

        replacement = replacements.get(index)
        if replacement is not None and not replacement_matches_segment(tag_bytes, replacement):
            return None
        operation = build_segment_rebuild_operation(
            index=index,
            tag_bytes=tag_bytes,
            original_segment_range=MrwByteRange(input_position, payload_end),
            original_payload_range=MrwByteRange(payload_start, payload_end),
            planned_output_offset=output_position,
            original_payload_length=original_payload_length,
            replacement=replacement,
        )
        segments.append(operation)
        input_position = payload_end
        output_position = operation.planned_output_range.end_offset
        index += 1

    if input_position != metadata_end_offset:
        return None
    return tuple(segments), output_position - MRW_HEADER_SIZE


def build_segment_rebuild_operation(
    index: int,
    tag_bytes: bytes,
    original_segment_range: MrwByteRange,
    original_payload_range: MrwByteRange,
    planned_output_offset: int,
    original_payload_length: int,
    replacement: MinoltaMrwSegmentReplacement | None,
) -> MinoltaMrwSegmentRebuildOperation:
    segment_name = MRW_SEGMENT_NAMES.get(tag_bytes, "Unknown")
    if replacement is None or replacement.outcome == "copy_original_on_undef":
        rewritten_payload_length = None
        planned_payload_length = original_payload_length
    elif replacement.outcome == "omit_empty_defined":
        rewritten_payload_length = 0
        planned_payload_length = 0
    else:
        rewritten_payload_length = len(replacement.payload)
        planned_payload_length = rewritten_payload_length
    copied_original = replacement is None or replacement.outcome == "copy_original_on_undef"
    padding_length = (
        0
        if replacement is None or replacement.outcome != "written_payload"
        else mrw_four_byte_padding_length(planned_payload_length)
    )
    output_payload_length = planned_payload_length + padding_length
    emits_segment = replacement is None or replacement.outcome != "omit_empty_defined"
    planned_output_range = MrwByteRange(
        planned_output_offset,
        planned_output_offset
        + (MRW_SEGMENT_HEADER_SIZE + output_payload_length if emits_segment else 0),
    )
    ttw_handoff = (
        build_ttw_handoff(index, original_payload_range, original_payload_length)
        if tag_bytes == MRW_TTW_TAG
        else None
    )
    binary_data_handoff = (
        build_binary_data_handoff(index, tag_bytes, original_payload_range, original_payload_length)
        if tag_bytes in MRW_BINARY_SUBDIRECTORY_TAGS
        else None
    )

    return MinoltaMrwSegmentRebuildOperation(
        index=index,
        tag_bytes_hex=tag_bytes.hex(),
        segment_name=segment_name,
        action=segment_rebuild_action(tag_bytes, replacement),
        original_segment_range=original_segment_range,
        original_payload_range=original_payload_range,
        planned_output_range=planned_output_range,
        original_payload_length=original_payload_length,
        rewritten_payload_length=rewritten_payload_length,
        planned_payload_length=planned_payload_length,
        padding=MinoltaMrwPaddingDecision(
            copied_original=copied_original,
            input_payload_length=planned_payload_length,
            padding_length=padding_length,
            output_payload_length=output_payload_length,
        ),
        length_field_value=output_payload_length,
        emits_segment=emits_segment,
        ttw_handoff=ttw_handoff,
        binary_data_handoff=binary_data_handoff,
        evidence_ids=segment_operation_evidence_ids(tag_bytes, replacement),
    )


def build_ttw_handoff(
    index: int,
    original_payload_range: MrwByteRange,
    original_payload_length: int,
) -> MinoltaMrwTtwRewriteHandoff:
    return MinoltaMrwTtwRewriteHandoff(
        segment_index=index,
        input_payload_range=original_payload_range,
        tag_table="Image::ExifTool::Exif::Main",
        process_proc="Image::ExifTool::ProcessTIFF",
        data_pos=original_payload_range.start_offset,
        dir_start=0,
        dir_len=original_payload_length,
        dir_name="MinoltaTTW",
        parent=MRW_RAW_PARENT,
        no_tiff_end=True,
        wrong_base_shift=-original_payload_range.start_offset,
        write_proc="Image::ExifTool::WriteTIFF",
        evidence_ids=(MINOLTA_RAW_MAIN_EVIDENCE_ID, MINOLTA_RAW_WRITE_EVIDENCE_ID),
    )


def build_binary_data_handoff(
    index: int,
    tag_bytes: bytes,
    original_payload_range: MrwByteRange,
    original_payload_length: int,
) -> MinoltaMrwBinaryDataRewriteHandoff:
    return MinoltaMrwBinaryDataRewriteHandoff(
        segment_index=index,
        segment_name=MRW_SEGMENT_NAMES[tag_bytes],
        input_payload_range=original_payload_range,
        tag_table=binary_data_tag_table(tag_bytes),
        process_proc="Image::ExifTool::ProcessBinaryData",
        write_proc="Image::ExifTool::WriteBinaryData",
        check_proc="Image::ExifTool::CheckBinaryData",
        writable=True,
        first_entry=0,
        data_pos=original_payload_range.start_offset,
        dir_start=0,
        dir_len=original_payload_length,
        dir_name=MRW_SEGMENT_NAMES[tag_bytes],
        parent=MRW_RAW_PARENT,
        no_tiff_end=True,
        wrong_base_shift=-original_payload_range.start_offset,
        evidence_ids=segment_operation_evidence_ids(tag_bytes, None),
    )


def binary_data_tag_table(tag_bytes: bytes) -> MinoltaMrwBinaryDataTableName:
    if tag_bytes == b"\0PRD":
        return "Image::ExifTool::MinoltaRaw::PRD"
    if tag_bytes == b"\0WBG":
        return "Image::ExifTool::MinoltaRaw::WBG"
    return "Image::ExifTool::MinoltaRaw::RIF"


def segment_rebuild_action(
    tag_bytes: bytes,
    replacement: MinoltaMrwSegmentReplacement | None,
) -> MinoltaMrwSegmentRebuildAction:
    if replacement is None or replacement.outcome == "copy_original_on_undef":
        if tag_bytes == b"\0CSA":
            return "copy_padding_segment"
        if tag_bytes in MRW_SEGMENT_NAMES:
            return "copy_original_segment"
        return "copy_unknown_segment"
    if replacement.outcome == "omit_empty_defined":
        if tag_bytes == MRW_TTW_TAG:
            return "handoff_ttw_to_tiff_writer"
        if tag_bytes in MRW_BINARY_SUBDIRECTORY_TAGS:
            return "rewrite_binary_subdirectory"
        return "copy_unknown_segment"
    if tag_bytes == MRW_TTW_TAG and replacement.writer == "tiff_writer":
        return "handoff_ttw_to_tiff_writer"
    if tag_bytes in MRW_BINARY_SUBDIRECTORY_TAGS and replacement.writer == "binary_data_writer":
        return "rewrite_binary_subdirectory"
    return "copy_unknown_segment"


def replacement_matches_segment(
    tag_bytes: bytes,
    replacement: MinoltaMrwSegmentReplacement,
) -> bool:
    return (tag_bytes == MRW_TTW_TAG and replacement.writer == "tiff_writer") or (
        tag_bytes in MRW_BINARY_SUBDIRECTORY_TAGS and replacement.writer == "binary_data_writer"
    )


def segment_operation_evidence_ids(
    tag_bytes: bytes,
    replacement: MinoltaMrwSegmentReplacement | None,
) -> tuple[str, ...]:
    evidence_ids: list[str] = [MINOLTA_RAW_WRITE_EVIDENCE_ID]
    if tag_bytes == MRW_TTW_TAG:
        evidence_ids.extend([MINOLTA_RAW_MAIN_EVIDENCE_ID, WRITE_EXIF_MRW_TTW_EVIDENCE_ID])
    elif tag_bytes == b"\0PRD":
        evidence_ids.extend([MINOLTA_RAW_MAIN_EVIDENCE_ID, MINOLTA_RAW_BINARY_EVIDENCE_ID])
    elif tag_bytes == b"\0RIF":
        evidence_ids.extend([MINOLTA_RAW_MAIN_EVIDENCE_ID, MINOLTA_RAW_RIF_EVIDENCE_ID])
    elif tag_bytes == b"\0WBG":
        evidence_ids.extend([MINOLTA_RAW_MAIN_EVIDENCE_ID, MINOLTA_RAW_WBG_EVIDENCE_ID])
    if replacement is not None and tag_bytes == MRW_TTW_TAG:
        evidence_ids.append(WRITE_EXIF_MRW_TTW_EVIDENCE_ID)
    return unique_evidence_ids(tuple(evidence_ids))


def mrw_four_byte_padding_length(length: int) -> int:
    return (4 - (length & 0x03)) & 0x03


def pad_mrw_segment_payload(payload: bytes) -> bytes:
    return payload + (b"\0" * mrw_four_byte_padding_length(len(payload)))


def replacement_index_map(
    replacements: tuple[MinoltaMrwSegmentReplacement, ...],
) -> dict[int, MinoltaMrwSegmentReplacement] | None:
    replacement_by_index: dict[int, MinoltaMrwSegmentReplacement] = {}
    for replacement in replacements:
        if replacement.segment_index in replacement_by_index:
            return None
        if replacement.outcome == "written_payload" and not replacement.payload:
            return None
        if replacement.outcome != "written_payload" and replacement.payload:
            return None
        replacement_by_index[replacement.segment_index] = replacement
    return replacement_by_index


def segment_rebuild_evidence_ids(
    mutation_plan: MinoltaMrwMutationPlan,
) -> tuple[str, ...]:
    return unique_evidence_ids(
        (
            *mutation_plan.evidence_ids,
            MINOLTA_RAW_MAIN_EVIDENCE_ID,
            MINOLTA_RAW_WRITE_EVIDENCE_ID,
            WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
        )
    )


def segment_rebuild_safety_gates(
    mutation_plan: MinoltaMrwMutationPlan,
) -> tuple[MinoltaMrwSafetyGate, ...]:
    return unique_safety_gates(mutation_plan.steps)
