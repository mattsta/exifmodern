"""Source-backed FujiFilm RAF embedded-JPEG mutation planning.

Generic RAW-family classification already maps RAF writes to the embedded JPEG
and RAF header offsets.  This module consumes that classification and deepens it
into the ordered container rewrite steps from ExifTool's FujiFilm::WriteRAF.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.fujifilm_raw.embedded_jpeg_handoff import (
    FUJIFILM_RAF_JPEG_HANDOFF_EVIDENCE_ID,
    FUJIFILM_RAF_USER_COMMENT_TEST_EVIDENCE_ID,
    FUJIFILM_RAF_WRITE_JPEG_EVIDENCE_ID,
    FujiFilmRafEmbeddedJpegMetadataRewriteResult,
    rewrite_raf_embedded_jpeg_metadata_from_write_args,
)
from exifmodern.formats.raw_family.write_plan import (
    RawFamilyBlockerCode,
    RawFamilyWriteRequestClassification,
    RawFamilyWriteSurface,
    classify_raw_family_golden_request_file,
)
from exifmodern.json_types import JsonObject, load_json_object

type FujiFilmRafMutationPlanStatus = Literal["source_mapped_deferred", "unsupported"]
type FujiFilmRafMutationStepKind = Literal[
    "validate_raf_header",
    "read_embedded_jpeg",
    "rewrite_embedded_jpeg_metadata",
    "pad_rewritten_jpeg_to_four_bytes",
    "patch_raf_header_jpeg_length",
    "patch_downstream_raf_offsets",
    "plan_container_output_segments",
    "copy_remaining_raf_blocks",
]
type FujiFilmRafSafetyBlocker = Literal[
    "requires_jpeg_container_rewrite",
    "requires_raf_header_pointer_rebuild",
    "requires_padding_validation",
    "requires_remaining_raf_stream_copy",
    "requires_raw_family_raf_routing",
]
type FujiFilmRafOutputSegmentKind = Literal[
    "patched_raf_header_prefix",
    "rewritten_embedded_jpeg",
    "new_jpeg_padding",
    "preserved_remaining_raf_stream",
]
type FujiFilmRafStreamOperationKind = Literal[
    "write_patched_header_prefix",
    "write_rewritten_embedded_jpeg",
    "write_new_jpeg_padding",
    "copy_remaining_raf_stream",
]
type FujiFilmRafHeaderPatchKind = Literal[
    "jpeg_length",
    "raf_pointer",
    "mraw_pointer_high_word",
]
type FujiFilmRafEmissionGateCode = Literal[
    "bad_raf_pointer_0x5c",
    "empty_jpeg_writer_output",
    "embedded_jpeg_input_range_unavailable",
    "non_null_padding",
    "invalid_raf_header_offset",
    "raf_header_offset_error",
    "embedded_jpeg_metadata_rewrite_unsupported",
    "requires_embedded_jpeg_metadata_rewrite",
    "remaining_raf_stream_range_unavailable",
]

RAF_MIN_HEADER_SIZE = 0x94
RAF_HEADER_POINTER_OFFSETS = (0x5C, 0x64, 0x78, 0x80, 0xCC, 0x114, 0x164)
MAX_OLD_PADDING_LENGTH = 1_000_000
UINT32_MAX = 0xFFFFFFFF

WRITER_RAF_ROUTING_SOURCE = "writer.raf.routing.source"
FUJIFILM_RAF_HEADER_SOURCE = "fujifilm.raf.header.source"
FUJIFILM_WRITE_RAF_VALIDATE_SOURCE = "fujifilm.write.raf.validate.source"
FUJIFILM_WRITE_RAF_JPEG_SOURCE = "fujifilm.write.raf.jpeg.source"
FUJIFILM_RAF_JPEG_HANDOFF_SOURCE = "fujifilm.raf.jpeg.handoff.source"
FUJIFILM_RAF_WRITE_JPEG_SOURCE = "fujifilm.raf.write.jpeg.source"
FUJIFILM_RAF_USER_COMMENT_TEST_SOURCE = "fujifilm.raf.user.comment.test.source"
FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE = "fujifilm.write.raf.header.patch.source"
FUJIFILM_WRITE_RAF_COPY_SOURCE = "fujifilm.write.raf.copy.source"


@dataclass(frozen=True)
class FujiFilmRafHeaderPointer:
    field_offset: int
    old_value: int
    patched_when_jpeg_delta_changes: bool

    def to_json(self) -> JsonObject:
        return {
            "field_offset": f"0x{self.field_offset:04x}",
            "old_value": self.old_value,
            "patched_when_jpeg_delta_changes": self.patched_when_jpeg_delta_changes,
        }


@dataclass(frozen=True)
class FujiFilmRafHeaderSummary:
    version: str
    mraw_header_offset: int
    mraw_header_length: int
    jpeg_offset: int
    jpeg_length: int
    next_block_offset: int
    old_padding_length: int | None
    old_padding_is_zero_filled: bool | None
    header_pointers: tuple[FujiFilmRafHeaderPointer, ...]

    def to_json(self) -> JsonObject:
        return {
            "header_pointers": [pointer.to_json() for pointer in self.header_pointers],
            "jpeg_length": self.jpeg_length,
            "jpeg_offset": self.jpeg_offset,
            "mraw_header_length": self.mraw_header_length,
            "mraw_header_offset": self.mraw_header_offset,
            "next_block_offset": self.next_block_offset,
            "old_padding_is_zero_filled": self.old_padding_is_zero_filled,
            "old_padding_length": self.old_padding_length,
            "version": self.version,
        }


@dataclass(frozen=True)
class FujiFilmRafRequestedMutation:
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
class FujiFilmRafMutationStep:
    kind: FujiFilmRafMutationStepKind
    description: str
    blockers: tuple[FujiFilmRafSafetyBlocker, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "description": self.description,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class FujiFilmRafEmissionGate:
    code: FujiFilmRafEmissionGateCode
    detail: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FujiFilmRafByteRange:
    offset: int
    length: int

    @property
    def end_offset(self) -> int:
        return self.offset + self.length

    def to_json(self) -> JsonObject:
        return {
            "end_offset": self.end_offset,
            "length": self.length,
            "offset": self.offset,
        }


@dataclass(frozen=True)
class FujiFilmRafEmbeddedJpegRewriteHandoff:
    accepted: bool
    input_range: FujiFilmRafByteRange
    output_range: FujiFilmRafByteRange
    output_bytes: bytes
    padding_length: int | None
    validation_gates: tuple[FujiFilmRafEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "accepted": self.accepted,
            "input_range": self.input_range.to_json(),
            "output_length": len(self.output_bytes),
            "output_range": self.output_range.to_json(),
            "output_sample_hex": self.output_bytes[:16].hex(),
            "padding_length": self.padding_length,
            "validation_gates": [gate.to_json() for gate in self.validation_gates],
        }


@dataclass(frozen=True)
class FujiFilmRafHeaderPatch:
    kind: FujiFilmRafHeaderPatchKind
    field_offset: int
    old_value: int
    new_value: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "field_offset": f"0x{self.field_offset:04x}",
            "kind": self.kind,
            "new_value": self.new_value,
            "old_value": self.old_value,
        }


@dataclass(frozen=True)
class FujiFilmRafOutputSegment:
    kind: FujiFilmRafOutputSegmentKind
    source_offset: int | None
    source_length: int | None
    output_length: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "output_length": self.output_length,
            "source_length": self.source_length,
            "source_offset": self.source_offset,
        }


@dataclass(frozen=True)
class FujiFilmRafStreamOperation:
    kind: FujiFilmRafStreamOperationKind
    output_offset: int
    source_offset: int | None
    source_length: int | None
    output_length: int | None
    applied_header_patch_offsets: tuple[int, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "applied_header_patch_offsets": [
                f"0x{field_offset:04x}" for field_offset in self.applied_header_patch_offsets
            ],
            "kind": self.kind,
            "output_length": self.output_length,
            "output_offset": self.output_offset,
            "source_length": self.source_length,
            "source_offset": self.source_offset,
        }


@dataclass(frozen=True)
class FujiFilmRafHeaderPatchApplication:
    byte_order: Literal["big"]
    header_prefix_length: int
    applied_patch_offsets: tuple[int, ...]
    skipped_patch_offsets: tuple[int, ...]
    output_header_prefix_length: int | None
    evidence_ids: tuple[str, ...]

    @property
    def all_patches_applied(self) -> bool:
        return not self.skipped_patch_offsets

    def to_json(self) -> JsonObject:
        return {
            "all_patches_applied": self.all_patches_applied,
            "applied_patch_offsets": [
                f"0x{field_offset:04x}" for field_offset in self.applied_patch_offsets
            ],
            "byte_order": self.byte_order,
            "header_prefix_length": self.header_prefix_length,
            "output_header_prefix_length": self.output_header_prefix_length,
            "skipped_patch_offsets": [
                f"0x{field_offset:04x}" for field_offset in self.skipped_patch_offsets
            ],
        }


@dataclass(frozen=True)
class FujiFilmRafMaterializedOutputSegment:
    kind: FujiFilmRafOutputSegmentKind
    output_offset: int
    source_range: FujiFilmRafByteRange | None
    output_length: int
    output_bytes: bytes | None
    zero_filled: bool
    evidence_ids: tuple[str, ...]

    @property
    def bytes_materialized(self) -> bool:
        return self.output_bytes is not None

    def to_json(self) -> JsonObject:
        return {
            "bytes_materialized": self.bytes_materialized,
            "kind": self.kind,
            "output_length": self.output_length,
            "output_offset": self.output_offset,
            "output_sample_hex": (
                self.output_bytes[:16].hex() if self.output_bytes is not None else None
            ),
            "source_range": (
                self.source_range.to_json() if self.source_range is not None else None
            ),
            "zero_filled": self.zero_filled,
        }


@dataclass(frozen=True)
class FujiFilmRafStreamEmitterBoundary:
    can_emit_stream: bool
    patched_header_prefix: bytes | None
    header_patch_application: FujiFilmRafHeaderPatchApplication
    operations: tuple[FujiFilmRafStreamOperation, ...]
    materialized_segments: tuple[FujiFilmRafMaterializedOutputSegment, ...]
    output_length: int | None
    output_emission_gates: tuple[FujiFilmRafEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_emit_stream": self.can_emit_stream,
            "header_patch_application": self.header_patch_application.to_json(),
            "materialized_segments": [segment.to_json() for segment in self.materialized_segments],
            "operations": [operation.to_json() for operation in self.operations],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "output_length": self.output_length,
            "patched_header_prefix_hex": (
                self.patched_header_prefix.hex() if self.patched_header_prefix is not None else None
            ),
        }


@dataclass(frozen=True)
class FujiFilmRafMaterializedOutputResult:
    can_install: bool
    output_bytes: bytes | None
    output_length: int | None
    materialized_segments: tuple[FujiFilmRafMaterializedOutputSegment, ...]
    output_emission_gates: tuple[FujiFilmRafEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_install": self.can_install,
            "materialized_segments": [segment.to_json() for segment in self.materialized_segments],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "output_length": self.output_length,
            "output_sample_hex": (
                self.output_bytes[:16].hex() if self.output_bytes is not None else None
            ),
        }

    def require_output_bytes(self) -> bytes:
        if self.output_bytes is None:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"FujiFilm RAF output is gated: {gate_codes}")
        return self.output_bytes


@dataclass(frozen=True)
class FujiFilmRafAtomicInstallationResult:
    materialized_output: FujiFilmRafMaterializedOutputResult
    transaction: FileWriteTransactionResult
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "bytes_written": self.transaction.bytes_written,
            "materialized_output": self.materialized_output.to_json(),
            "output_path": str(self.transaction.output_path),
            "replaced_existing": self.transaction.replaced_existing,
        }


@dataclass(frozen=True)
class FujiFilmRafTransactionalOutputPlan:
    can_emit_output: bool
    embedded_jpeg_rewrite_handoff: FujiFilmRafEmbeddedJpegRewriteHandoff | None
    rewritten_jpeg_length: int | None
    rewritten_jpeg_padding_length: int | None
    pointer_delta: int | None
    header_patches: tuple[FujiFilmRafHeaderPatch, ...]
    output_segments: tuple[FujiFilmRafOutputSegment, ...]
    output_emission_gates: tuple[FujiFilmRafEmissionGate, ...]
    stream_emitter_boundary: FujiFilmRafStreamEmitterBoundary
    materialized_output: FujiFilmRafMaterializedOutputResult | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "embedded_jpeg_rewrite_handoff": (
                self.embedded_jpeg_rewrite_handoff.to_json()
                if self.embedded_jpeg_rewrite_handoff is not None
                else None
            ),
            "header_patches": [patch.to_json() for patch in self.header_patches],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "output_segments": [segment.to_json() for segment in self.output_segments],
            "pointer_delta": self.pointer_delta,
            "rewritten_jpeg_length": self.rewritten_jpeg_length,
            "rewritten_jpeg_padding_length": self.rewritten_jpeg_padding_length,
            "materialized_output": (
                self.materialized_output.to_json() if self.materialized_output is not None else None
            ),
            "stream_emitter_boundary": self.stream_emitter_boundary.to_json(),
        }


@dataclass(frozen=True)
class FujiFilmRafEmbeddedJpegMutationPlan:
    status: FujiFilmRafMutationPlanStatus
    can_mutate: bool
    raw_family_request_id: str | None
    header: FujiFilmRafHeaderSummary | None
    requested_mutations: tuple[FujiFilmRafRequestedMutation, ...]
    steps: tuple[FujiFilmRafMutationStep, ...]
    transactional_output: FujiFilmRafTransactionalOutputPlan | None
    blockers: tuple[FujiFilmRafSafetyBlocker, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "can_mutate": self.can_mutate,
            "header": self.header.to_json() if self.header is not None else None,
            "raw_family_request_id": self.raw_family_request_id,
            "requested_mutations": [
                requested_mutation.to_json() for requested_mutation in self.requested_mutations
            ],
            "status": self.status,
            "steps": [step.to_json() for step in self.steps],
            "transactional_output": (
                self.transactional_output.to_json()
                if self.transactional_output is not None
                else None
            ),
        }


def load_fujifilm_raf_golden_mutation_plan(
    request_path: Path,
    data: bytes,
) -> FujiFilmRafEmbeddedJpegMutationPlan:
    header = parse_raf_header(data)
    rewrite_result = (
        rewrite_raf_embedded_jpeg_metadata_from_write_args(
            data,
            header.jpeg_offset,
            header.jpeg_length,
            write_args_from_request_path(request_path),
        )
        if header is not None
        else None
    )
    return build_fujifilm_raf_embedded_jpeg_mutation_plan(
        data,
        classify_raw_family_golden_request_file(request_path),
        rewrite_result.output_bytes if rewrite_result is not None else None,
        rewrite_result,
    )


def build_fujifilm_raf_embedded_jpeg_mutation_plan_from_write_args(
    data: bytes,
    raw_family_classification: RawFamilyWriteRequestClassification | None,
    write_args: tuple[str, ...],
) -> FujiFilmRafEmbeddedJpegMutationPlan:
    header = parse_raf_header(data)
    rewrite_result = (
        rewrite_raf_embedded_jpeg_metadata_from_write_args(
            data,
            header.jpeg_offset,
            header.jpeg_length,
            write_args,
        )
        if header is not None
        else None
    )
    return build_fujifilm_raf_embedded_jpeg_mutation_plan(
        data,
        raw_family_classification,
        rewrite_result.output_bytes if rewrite_result is not None else None,
        rewrite_result,
    )


def build_fujifilm_raf_embedded_jpeg_mutation_plan(
    data: bytes,
    raw_family_classification: RawFamilyWriteRequestClassification | None = None,
    rewritten_embedded_jpeg: bytes | None = None,
    embedded_jpeg_rewrite_result: FujiFilmRafEmbeddedJpegMetadataRewriteResult | None = None,
) -> FujiFilmRafEmbeddedJpegMutationPlan:
    header = parse_raf_header(data)
    requested_mutations = requested_mutations_from_raw_family(raw_family_classification)
    steps = fujifilm_raf_mutation_steps() if header is not None else ()
    transactional_output = (
        build_transactional_raf_output_plan(
            data,
            header,
            rewritten_embedded_jpeg,
            embedded_jpeg_rewrite_result,
        )
        if header is not None
        else None
    )
    status: FujiFilmRafMutationPlanStatus = (
        "source_mapped_deferred"
        if header is not None and raw_family_classification_is_raf(raw_family_classification)
        else "unsupported"
    )
    return FujiFilmRafEmbeddedJpegMutationPlan(
        status=status,
        can_mutate=False,
        raw_family_request_id=(
            raw_family_classification.request_id if raw_family_classification is not None else None
        ),
        header=header,
        requested_mutations=requested_mutations,
        steps=steps,
        transactional_output=transactional_output,
        blockers=unique_blockers(steps),
        evidence_ids=plan_evidence_ids(raw_family_classification),
    )


def parse_raf_header(data: bytes) -> FujiFilmRafHeaderSummary | None:
    if len(data) < RAF_MIN_HEADER_SIZE or not data.startswith(b"FUJIFILM"):
        return None
    version = data[0x3C:0x40].decode("ascii", errors="replace")
    if not version.isdecimal():
        return None
    mraw_header_offset = read_u32_be(data, 0x48)
    mraw_header_length = read_u32_be(data, 0x4C)
    jpeg_offset = read_u32_be(data, 0x54)
    jpeg_length = read_u32_be(data, 0x58)
    next_block_offset = read_u32_be(data, 0x5C)
    if not raf_jpeg_layout_is_supported(
        jpeg_offset,
        jpeg_length,
        mraw_header_offset,
        mraw_header_length,
    ):
        return None
    return FujiFilmRafHeaderSummary(
        version=version,
        mraw_header_offset=mraw_header_offset,
        mraw_header_length=mraw_header_length,
        jpeg_offset=jpeg_offset,
        jpeg_length=jpeg_length,
        next_block_offset=next_block_offset,
        old_padding_length=old_padding_length(data, jpeg_offset, jpeg_length, next_block_offset),
        old_padding_is_zero_filled=old_padding_is_zero_filled(
            data, jpeg_offset, jpeg_length, next_block_offset
        ),
        header_pointers=parse_raf_header_pointers(data, jpeg_offset),
    )


def build_transactional_raf_output_plan(
    data: bytes,
    header: FujiFilmRafHeaderSummary,
    rewritten_embedded_jpeg: bytes | None,
    embedded_jpeg_rewrite_result: FujiFilmRafEmbeddedJpegMetadataRewriteResult | None = None,
) -> FujiFilmRafTransactionalOutputPlan:
    embedded_jpeg_rewrite_handoff = (
        build_embedded_jpeg_rewrite_handoff(data, header, rewritten_embedded_jpeg)
        if rewritten_embedded_jpeg is not None
        else None
    )
    rewritten_jpeg_length = (
        embedded_jpeg_rewrite_handoff.output_range.length
        if embedded_jpeg_rewrite_handoff is not None and embedded_jpeg_rewrite_handoff.accepted
        else None
    )
    rewritten_jpeg_padding_length = (
        jpeg_padding_length(rewritten_jpeg_length) if rewritten_jpeg_length is not None else None
    )
    pointer_delta = (
        rewritten_jpeg_length
        + rewritten_jpeg_padding_length
        - (header.jpeg_length + header.old_padding_length)
        if rewritten_jpeg_length is not None
        and rewritten_jpeg_padding_length is not None
        and header.old_padding_length is not None
        else None
    )
    header_patches, pointer_gates = plan_header_patches(
        data, header, rewritten_jpeg_length, pointer_delta
    )
    output_segments = plan_output_segments(header, len(data), rewritten_jpeg_length)
    jpeg_handoff_gates = (
        (
            FujiFilmRafEmissionGate(
                code="requires_embedded_jpeg_metadata_rewrite",
                detail=(
                    "RAF byte emission requires source-backed embedded JPEG rewrite "
                    "integration before the rewritten JPEG bytes may be trusted."
                ),
                evidence_ids=(FUJIFILM_WRITE_RAF_JPEG_SOURCE,),
            ),
        )
        if embedded_jpeg_rewrite_handoff is None
        else embedded_jpeg_rewrite_handoff.validation_gates
    )
    if embedded_jpeg_rewrite_result is not None and embedded_jpeg_rewrite_result.diagnostics:
        jpeg_handoff_gates = jpeg_handoff_gates + tuple(
            FujiFilmRafEmissionGate(
                code="embedded_jpeg_metadata_rewrite_unsupported",
                detail=diagnostic.detail,
                evidence_ids=embedded_jpeg_handoff_evidence_ids(diagnostic.evidence_ids),
            )
            for diagnostic in embedded_jpeg_rewrite_result.diagnostics
        )
    output_gates = validate_old_padding_gate(header) + pointer_gates + jpeg_handoff_gates
    stream_emitter_boundary = build_stream_emitter_boundary(
        data,
        header,
        embedded_jpeg_rewrite_handoff,
        header_patches,
        output_segments,
        output_gates,
    )
    materialized_output = materialize_raf_transactional_output(data, stream_emitter_boundary)
    return FujiFilmRafTransactionalOutputPlan(
        can_emit_output=materialized_output.can_install,
        embedded_jpeg_rewrite_handoff=embedded_jpeg_rewrite_handoff,
        rewritten_jpeg_length=rewritten_jpeg_length,
        rewritten_jpeg_padding_length=rewritten_jpeg_padding_length,
        pointer_delta=pointer_delta,
        header_patches=header_patches,
        output_segments=output_segments,
        output_emission_gates=output_gates,
        stream_emitter_boundary=stream_emitter_boundary,
        materialized_output=materialized_output,
        evidence_ids=(
            FUJIFILM_WRITE_RAF_JPEG_SOURCE,
            FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,
            FUJIFILM_WRITE_RAF_COPY_SOURCE,
        ),
    )


def build_embedded_jpeg_rewrite_handoff(
    data: bytes,
    header: FujiFilmRafHeaderSummary,
    output_bytes: bytes,
) -> FujiFilmRafEmbeddedJpegRewriteHandoff:
    validation_gates: list[FujiFilmRafEmissionGate] = []
    input_range = FujiFilmRafByteRange(
        offset=header.jpeg_offset,
        length=header.jpeg_length,
    )
    output_range = FujiFilmRafByteRange(
        offset=header.jpeg_offset,
        length=len(output_bytes),
    )
    if input_range.end_offset > len(data):
        validation_gates.append(
            FujiFilmRafEmissionGate(
                code="embedded_jpeg_input_range_unavailable",
                detail=(
                    "WriteRAF must read the complete embedded JPEG before handing it to "
                    "the JPEG writer."
                ),
                evidence_ids=(FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,),
            )
        )
    if len(output_bytes) == 0:
        validation_gates.append(
            FujiFilmRafEmissionGate(
                code="empty_jpeg_writer_output",
                detail=(
                    "WriteRAF rejects a JPEG writer handoff unless WriteJPEG succeeds "
                    "and outputs bytes."
                ),
                evidence_ids=(FUJIFILM_WRITE_RAF_JPEG_SOURCE,),
            )
        )
    return FujiFilmRafEmbeddedJpegRewriteHandoff(
        accepted=not validation_gates,
        input_range=input_range,
        output_range=output_range,
        output_bytes=output_bytes,
        padding_length=jpeg_padding_length(len(output_bytes)) if output_bytes else None,
        validation_gates=tuple(validation_gates),
        evidence_ids=(
            FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
            FUJIFILM_WRITE_RAF_JPEG_SOURCE,
            FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,
        ),
    )


def plan_header_patches(
    data: bytes,
    header: FujiFilmRafHeaderSummary,
    rewritten_jpeg_length: int | None,
    pointer_delta: int | None,
) -> tuple[tuple[FujiFilmRafHeaderPatch, ...], tuple[FujiFilmRafEmissionGate, ...]]:
    if pointer_delta is None or rewritten_jpeg_length is None:
        return (), ()
    patches = [
        FujiFilmRafHeaderPatch(
            kind="jpeg_length",
            field_offset=0x58,
            old_value=header.jpeg_length,
            new_value=rewritten_jpeg_length,
            evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
        )
    ]
    gates: list[FujiFilmRafEmissionGate] = []
    for pointer in header.header_pointers:
        if pointer.old_value == 0:
            continue
        adjusted_value = pointer.old_value + pointer_delta
        if 0 <= adjusted_value <= UINT32_MAX:
            patches.append(
                FujiFilmRafHeaderPatch(
                    kind="raf_pointer",
                    field_offset=pointer.field_offset,
                    old_value=pointer.old_value,
                    new_value=adjusted_value,
                    evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
                )
            )
            continue
        if pointer.field_offset < 0xCC:
            gates.append(
                FujiFilmRafEmissionGate(
                    code="invalid_raf_header_offset",
                    detail="WriteRAF rejects base RAF header pointer underflow or overflow.",
                    evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
                )
            )
            continue
        high_word_offset = pointer.field_offset - 4
        high_word = read_u32_be(data, high_word_offset)
        high_word_delta = -1 if adjusted_value < 0 else 1
        new_high_word = high_word + high_word_delta
        if not 0 <= new_high_word <= UINT32_MAX:
            gates.append(
                FujiFilmRafEmissionGate(
                    code="raf_header_offset_error",
                    detail="WriteRAF rejects M-RAW high-word pointer fixups that overflow.",
                    evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
                )
            )
            continue
        patches.append(
            FujiFilmRafHeaderPatch(
                kind="mraw_pointer_high_word",
                field_offset=high_word_offset,
                old_value=high_word,
                new_value=new_high_word,
                evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
            )
        )
        patches.append(
            FujiFilmRafHeaderPatch(
                kind="raf_pointer",
                field_offset=pointer.field_offset,
                old_value=pointer.old_value,
                new_value=adjusted_value % (UINT32_MAX + 1),
                evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
            )
        )
    return tuple(patches), tuple(gates)


def plan_output_segments(
    header: FujiFilmRafHeaderSummary,
    source_length: int,
    rewritten_jpeg_length: int | None,
) -> tuple[FujiFilmRafOutputSegment, ...]:
    suffix_length = (
        source_length - header.next_block_offset
        if 0 <= header.next_block_offset <= source_length
        else None
    )
    padding_length = (
        jpeg_padding_length(rewritten_jpeg_length) if rewritten_jpeg_length is not None else None
    )
    return (
        FujiFilmRafOutputSegment(
            kind="patched_raf_header_prefix",
            source_offset=0,
            source_length=header.jpeg_offset,
            output_length=header.jpeg_offset,
            evidence_ids=(FUJIFILM_WRITE_RAF_COPY_SOURCE,),
        ),
        FujiFilmRafOutputSegment(
            kind="rewritten_embedded_jpeg",
            source_offset=header.jpeg_offset,
            source_length=header.jpeg_length,
            output_length=rewritten_jpeg_length,
            evidence_ids=(FUJIFILM_WRITE_RAF_JPEG_SOURCE, FUJIFILM_WRITE_RAF_COPY_SOURCE),
        ),
        FujiFilmRafOutputSegment(
            kind="new_jpeg_padding",
            source_offset=None,
            source_length=None,
            output_length=padding_length,
            evidence_ids=(
                FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,
                FUJIFILM_WRITE_RAF_COPY_SOURCE,
            ),
        ),
        FujiFilmRafOutputSegment(
            kind="preserved_remaining_raf_stream",
            source_offset=header.next_block_offset,
            source_length=suffix_length,
            output_length=suffix_length,
            evidence_ids=(FUJIFILM_WRITE_RAF_COPY_SOURCE,),
        ),
    )


def build_stream_emitter_boundary(
    data: bytes,
    header: FujiFilmRafHeaderSummary,
    embedded_jpeg_rewrite_handoff: FujiFilmRafEmbeddedJpegRewriteHandoff | None,
    header_patches: tuple[FujiFilmRafHeaderPatch, ...],
    output_segments: tuple[FujiFilmRafOutputSegment, ...],
    output_gates: tuple[FujiFilmRafEmissionGate, ...],
) -> FujiFilmRafStreamEmitterBoundary:
    patched_header_prefix = (
        patched_raf_header_prefix(data, header.jpeg_offset, header_patches)
        if embedded_jpeg_rewrite_handoff is not None
        and embedded_jpeg_rewrite_handoff.accepted
        and header_patches
        else None
    )
    header_patch_application = build_header_patch_application(
        header.jpeg_offset, header_patches, patched_header_prefix
    )
    operations = plan_stream_operations(output_segments, header_patches)
    materialized_segments = materialize_output_segments(
        output_segments,
        operations,
        patched_header_prefix,
        embedded_jpeg_rewrite_handoff,
    )
    output_length = planned_output_length(output_segments)
    return FujiFilmRafStreamEmitterBoundary(
        can_emit_stream=not output_gates and bool(materialized_segments),
        patched_header_prefix=patched_header_prefix,
        header_patch_application=header_patch_application,
        operations=operations,
        materialized_segments=materialized_segments,
        output_length=output_length,
        output_emission_gates=output_gates,
        evidence_ids=(
            FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,
            FUJIFILM_WRITE_RAF_COPY_SOURCE,
        ),
    )


def materialize_raf_transactional_output(
    data: bytes,
    boundary: FujiFilmRafStreamEmitterBoundary,
) -> FujiFilmRafMaterializedOutputResult:
    if boundary.output_emission_gates or boundary.output_length is None:
        return FujiFilmRafMaterializedOutputResult(
            can_install=False,
            output_bytes=None,
            output_length=boundary.output_length,
            materialized_segments=boundary.materialized_segments,
            output_emission_gates=boundary.output_emission_gates,
            evidence_ids=(FUJIFILM_WRITE_RAF_COPY_SOURCE,),
        )

    output = bytearray()
    gates: list[FujiFilmRafEmissionGate] = []
    for segment in boundary.materialized_segments:
        if segment.output_bytes is not None:
            output.extend(segment.output_bytes)
            continue
        if segment.source_range is None or segment.source_range.end_offset > len(data):
            gates.append(
                FujiFilmRafEmissionGate(
                    code="remaining_raf_stream_range_unavailable",
                    detail=(
                        "WriteRAF copies the remaining RAF stream after the original next "
                        "block pointer; that source range must be available before install."
                    ),
                    evidence_ids=(FUJIFILM_WRITE_RAF_COPY_SOURCE,),
                )
            )
            break
        output.extend(data[segment.source_range.offset : segment.source_range.end_offset])

    if gates or len(output) != boundary.output_length:
        return FujiFilmRafMaterializedOutputResult(
            can_install=False,
            output_bytes=None,
            output_length=boundary.output_length,
            materialized_segments=boundary.materialized_segments,
            output_emission_gates=tuple(gates),
            evidence_ids=(FUJIFILM_WRITE_RAF_COPY_SOURCE,),
        )
    return FujiFilmRafMaterializedOutputResult(
        can_install=True,
        output_bytes=bytes(output),
        output_length=len(output),
        materialized_segments=boundary.materialized_segments,
        output_emission_gates=(),
        evidence_ids=(FUJIFILM_WRITE_RAF_COPY_SOURCE,),
    )


def install_materialized_fujifilm_raf_output(
    materialized_output: FujiFilmRafMaterializedOutputResult,
    output_path: Path,
) -> FujiFilmRafAtomicInstallationResult:
    transaction = write_bytes_transactionally(
        output_path,
        materialized_output.require_output_bytes(),
    )
    return FujiFilmRafAtomicInstallationResult(
        materialized_output=materialized_output,
        transaction=transaction,
        evidence_ids=(FUJIFILM_WRITE_RAF_COPY_SOURCE,),
    )


def planned_output_length(output_segments: tuple[FujiFilmRafOutputSegment, ...]) -> int | None:
    total = 0
    for segment in output_segments:
        if segment.output_length is None:
            return None
        total += segment.output_length
    return total


def build_header_patch_application(
    header_prefix_length: int,
    header_patches: tuple[FujiFilmRafHeaderPatch, ...],
    patched_header_prefix: bytes | None,
) -> FujiFilmRafHeaderPatchApplication:
    applied_offsets = tuple(
        patch.field_offset
        for patch in header_patches
        if patch.field_offset + 4 <= header_prefix_length
    )
    skipped_offsets = tuple(
        patch.field_offset
        for patch in header_patches
        if patch.field_offset + 4 > header_prefix_length
    )
    return FujiFilmRafHeaderPatchApplication(
        byte_order="big",
        header_prefix_length=header_prefix_length,
        applied_patch_offsets=applied_offsets if patched_header_prefix is not None else (),
        skipped_patch_offsets=skipped_offsets
        + (applied_offsets if patched_header_prefix is None else ()),
        output_header_prefix_length=(
            len(patched_header_prefix) if patched_header_prefix is not None else None
        ),
        evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
    )


def patched_raf_header_prefix(
    data: bytes,
    header_prefix_length: int,
    header_patches: tuple[FujiFilmRafHeaderPatch, ...],
) -> bytes:
    patched = bytearray(data[:header_prefix_length])
    for patch in header_patches:
        if patch.field_offset + 4 <= header_prefix_length:
            patched[patch.field_offset : patch.field_offset + 4] = patch.new_value.to_bytes(
                4, "big"
            )
    return bytes(patched)


def materialize_output_segments(
    output_segments: tuple[FujiFilmRafOutputSegment, ...],
    operations: tuple[FujiFilmRafStreamOperation, ...],
    patched_header_prefix: bytes | None,
    embedded_jpeg_rewrite_handoff: FujiFilmRafEmbeddedJpegRewriteHandoff | None,
) -> tuple[FujiFilmRafMaterializedOutputSegment, ...]:
    materialized_segments: list[FujiFilmRafMaterializedOutputSegment] = []
    for segment, operation in zip(output_segments, operations, strict=True):
        if segment.output_length is None:
            return ()
        output_bytes = materialized_segment_bytes(
            segment,
            patched_header_prefix,
            embedded_jpeg_rewrite_handoff,
        )
        if output_bytes is None and segment.kind != "preserved_remaining_raf_stream":
            return ()
        source_range = (
            FujiFilmRafByteRange(segment.source_offset, segment.source_length)
            if segment.source_offset is not None and segment.source_length is not None
            else None
        )
        materialized_segments.append(
            FujiFilmRafMaterializedOutputSegment(
                kind=segment.kind,
                output_offset=operation.output_offset,
                source_range=source_range,
                output_length=segment.output_length,
                output_bytes=output_bytes,
                zero_filled=output_bytes == (b"\0" * segment.output_length),
                evidence_ids=segment.evidence_ids,
            )
        )
    return tuple(materialized_segments)


def materialized_segment_bytes(
    segment: FujiFilmRafOutputSegment,
    patched_header_prefix: bytes | None,
    embedded_jpeg_rewrite_handoff: FujiFilmRafEmbeddedJpegRewriteHandoff | None,
) -> bytes | None:
    if segment.kind == "patched_raf_header_prefix":
        return patched_header_prefix
    if segment.kind == "rewritten_embedded_jpeg":
        if embedded_jpeg_rewrite_handoff is None or not embedded_jpeg_rewrite_handoff.accepted:
            return None
        return embedded_jpeg_rewrite_handoff.output_bytes
    if segment.kind == "new_jpeg_padding":
        return b"\0" * segment.output_length if segment.output_length is not None else None
    return None


def plan_stream_operations(
    output_segments: tuple[FujiFilmRafOutputSegment, ...],
    header_patches: tuple[FujiFilmRafHeaderPatch, ...],
) -> tuple[FujiFilmRafStreamOperation, ...]:
    operation_kinds: tuple[FujiFilmRafStreamOperationKind, ...] = (
        "write_patched_header_prefix",
        "write_rewritten_embedded_jpeg",
        "write_new_jpeg_padding",
        "copy_remaining_raf_stream",
    )
    operations: list[FujiFilmRafStreamOperation] = []
    output_offset = 0
    for segment, operation_kind in zip(output_segments, operation_kinds, strict=True):
        operations.append(
            FujiFilmRafStreamOperation(
                kind=operation_kind,
                output_offset=output_offset,
                source_offset=segment.source_offset,
                source_length=segment.source_length,
                output_length=segment.output_length,
                applied_header_patch_offsets=(
                    tuple(patch.field_offset for patch in header_patches)
                    if operation_kind == "write_patched_header_prefix"
                    else ()
                ),
                evidence_ids=segment.evidence_ids,
            )
        )
        if segment.output_length is not None:
            output_offset += segment.output_length
    return tuple(operations)


def validate_old_padding_gate(
    header: FujiFilmRafHeaderSummary,
) -> tuple[FujiFilmRafEmissionGate, ...]:
    if header.old_padding_length is None:
        return (
            FujiFilmRafEmissionGate(
                code="bad_raf_pointer_0x5c",
                detail=(
                    "WriteRAF rejects RAF pointer 0x5c when old JPEG padding cannot be "
                    "bounded from the source stream."
                ),
                evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
            ),
        )
    if header.old_padding_length < 0 or header.old_padding_length > MAX_OLD_PADDING_LENGTH:
        return (
            FujiFilmRafEmissionGate(
                code="bad_raf_pointer_0x5c",
                detail="WriteRAF rejects negative or oversized old embedded-JPEG padding.",
                evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
            ),
        )
    if header.old_padding_is_zero_filled is False:
        return (
            FujiFilmRafEmissionGate(
                code="non_null_padding",
                detail=(
                    "WriteRAF treats non-null bytes between the embedded JPEG and next RAF "
                    "block as unsafe padding."
                ),
                evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
            ),
        )
    return ()


def jpeg_padding_length(jpeg_length: int) -> int:
    return 4 - (jpeg_length % 4)


def raf_jpeg_layout_is_supported(
    jpeg_offset: int,
    jpeg_length: int,
    mraw_header_offset: int,
    mraw_header_length: int,
) -> bool:
    if (
        mraw_header_offset > RAF_MIN_HEADER_SIZE
        or jpeg_offset > RAF_MIN_HEADER_SIZE + mraw_header_length
    ):
        return False
    if jpeg_offset < 0x68 or jpeg_offset % 4 != 0:
        return False
    return jpeg_length > 0


def old_padding_length(
    data: bytes,
    jpeg_offset: int,
    jpeg_length: int,
    next_block_offset: int,
) -> int | None:
    padding_start = jpeg_offset + jpeg_length
    if next_block_offset < padding_start or next_block_offset > len(data):
        return None
    return next_block_offset - padding_start


def old_padding_is_zero_filled(
    data: bytes,
    jpeg_offset: int,
    jpeg_length: int,
    next_block_offset: int,
) -> bool | None:
    padding_start = jpeg_offset + jpeg_length
    if next_block_offset < padding_start or next_block_offset > len(data):
        return None
    return all(byte == 0 for byte in data[padding_start:next_block_offset])


def parse_raf_header_pointers(
    data: bytes,
    jpeg_offset: int,
) -> tuple[FujiFilmRafHeaderPointer, ...]:
    pointers: list[FujiFilmRafHeaderPointer] = []
    for field_offset in RAF_HEADER_POINTER_OFFSETS:
        if field_offset >= jpeg_offset or field_offset + 4 > len(data):
            break
        old_value = read_u32_be(data, field_offset)
        pointers.append(
            FujiFilmRafHeaderPointer(
                field_offset=field_offset,
                old_value=old_value,
                patched_when_jpeg_delta_changes=old_value != 0,
            )
        )
    return tuple(pointers)


def requested_mutations_from_raw_family(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> tuple[FujiFilmRafRequestedMutation, ...]:
    if raw_family_classification is None:
        return ()
    return tuple(
        FujiFilmRafRequestedMutation(
            requested_tag=argument.requested_tag,
            requested_value=argument.requested_value,
            generic_surfaces=argument.target_surfaces,
            generic_blockers=argument.blocker_codes,
        )
        for argument in raw_family_classification.arguments
    )


def raw_family_classification_is_raf(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> bool:
    if raw_family_classification is None:
        return True
    return (
        raw_family_classification.container == "raf_fuji_embedded_jpeg"
        and raw_family_classification.status == "source_mapped_deferred"
        and all(
            "raf_embedded_jpeg_exif" in argument.target_surfaces
            and "raf_header_offsets" in argument.target_surfaces
            for argument in raw_family_classification.arguments
        )
    )


def fujifilm_raf_mutation_steps() -> tuple[FujiFilmRafMutationStep, ...]:
    return (
        FujiFilmRafMutationStep(
            kind="validate_raf_header",
            description="Validate RAF signature, version, embedded JPEG pointer, and M-RAW layout.",
            blockers=("requires_raw_family_raf_routing",),
            evidence_ids=(WRITER_RAF_ROUTING_SOURCE, FUJIFILM_WRITE_RAF_VALIDATE_SOURCE),
        ),
        FujiFilmRafMutationStep(
            kind="read_embedded_jpeg",
            description="Read the embedded JPEG segment selected by RAF header offset and length.",
            blockers=("requires_jpeg_container_rewrite",),
            evidence_ids=(FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,),
        ),
        FujiFilmRafMutationStep(
            kind="rewrite_embedded_jpeg_metadata",
            description="Rewrite requested metadata through JPEG write directories inside the RAF.",
            blockers=("requires_jpeg_container_rewrite",),
            evidence_ids=(FUJIFILM_WRITE_RAF_JPEG_SOURCE,),
        ),
        FujiFilmRafMutationStep(
            kind="pad_rewritten_jpeg_to_four_bytes",
            description="Pad the rewritten JPEG to a 4-byte boundary and validate old RAF padding.",
            blockers=("requires_padding_validation",),
            evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,),
        ),
        FujiFilmRafMutationStep(
            kind="patch_raf_header_jpeg_length",
            description="Patch header offset 0x58 with rewritten JPEG length before padding.",
            blockers=("requires_raf_header_pointer_rebuild",),
            evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE, FUJIFILM_RAF_HEADER_SOURCE),
        ),
        FujiFilmRafMutationStep(
            kind="patch_downstream_raf_offsets",
            description=(
                "Apply JPEG-size delta to downstream RAF header pointers before image copy."
            ),
            blockers=("requires_raf_header_pointer_rebuild",),
            evidence_ids=(FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE, FUJIFILM_RAF_HEADER_SOURCE),
        ),
        FujiFilmRafMutationStep(
            kind="plan_container_output_segments",
            description=(
                "Plan patched RAF header, rewritten JPEG, new padding, and preserved suffix "
                "segments before emission."
            ),
            blockers=("requires_remaining_raf_stream_copy",),
            evidence_ids=(
                FUJIFILM_WRITE_RAF_JPEG_SOURCE,
                FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,
                FUJIFILM_WRITE_RAF_COPY_SOURCE,
            ),
        ),
        FujiFilmRafMutationStep(
            kind="copy_remaining_raf_blocks",
            description="Write patched header/JPEG bytes, then stream all remaining RAF blocks.",
            blockers=("requires_remaining_raf_stream_copy",),
            evidence_ids=(FUJIFILM_WRITE_RAF_COPY_SOURCE,),
        ),
    )


def plan_evidence_ids(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> tuple[str, ...]:
    references = [
        WRITER_RAF_ROUTING_SOURCE,
        FUJIFILM_RAF_HEADER_SOURCE,
        FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
        FUJIFILM_WRITE_RAF_JPEG_SOURCE,
        FUJIFILM_WRITE_RAF_HEADER_PATCH_SOURCE,
        FUJIFILM_WRITE_RAF_COPY_SOURCE,
    ]
    if raw_family_classification is not None:
        references.extend(raw_family_classification.evidence_ids)
    return unique_evidence_ids(tuple(references))


FUJIFILM_RAF_EMBEDDED_JPEG_HANDOFF_SOURCES_BY_ID = {
    FUJIFILM_RAF_JPEG_HANDOFF_EVIDENCE_ID: FUJIFILM_RAF_JPEG_HANDOFF_SOURCE,
    FUJIFILM_RAF_WRITE_JPEG_EVIDENCE_ID: FUJIFILM_RAF_WRITE_JPEG_SOURCE,
    FUJIFILM_RAF_USER_COMMENT_TEST_EVIDENCE_ID: FUJIFILM_RAF_USER_COMMENT_TEST_SOURCE,
}


def embedded_jpeg_handoff_evidence_ids(
    evidence_ids: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(FUJIFILM_RAF_EMBEDDED_JPEG_HANDOFF_SOURCES_BY_ID[id_] for id_ in evidence_ids)


def write_args_from_request_path(request_path: Path) -> tuple[str, ...]:
    payload = load_json_object(request_path)
    write_args = payload.get("write_args")
    if not isinstance(write_args, list):
        return ()
    return tuple(arg for arg in write_args if isinstance(arg, str))


def read_u32_be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def unique_blockers(
    steps: tuple[FujiFilmRafMutationStep, ...],
) -> tuple[FujiFilmRafSafetyBlocker, ...]:
    blockers: list[FujiFilmRafSafetyBlocker] = []
    for step in steps:
        for blocker in step.blockers:
            if blocker not in blockers:
                blockers.append(blocker)
    return tuple(blockers)


def unique_evidence_ids(
    references: tuple[str, ...],
) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)
