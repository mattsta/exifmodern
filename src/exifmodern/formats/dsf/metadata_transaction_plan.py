"""Source-backed, non-mutating DSF/DSD metadata transaction plans.

ExifTool's DSF module is a reader: it validates the DSD header and adjacent
``fmt `` chunk, processes audio properties from that binary header, and
delegates bounded trailing metadata to the ID3 processor when the DSD metadata
offset allows it. This planner mirrors those responsibilities and records why
real byte emission remains gated.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

DSD_HEADER_SIZE = 28
DSF_INITIAL_READ_SIZE = 40
DSF_CHUNK_HEADER_SIZE = 12
DSF_FULL_FMT_SIZE = 48
DSF_METADATA_LENGTH_LIMIT = 20_000_000
DSD_SIGNATURE = b"DSD "
FMT_CHUNK_ID = b"fmt "
DATA_CHUNK_ID = b"data"

type DsfPlanStatus = Literal["planned", "unsupported"]
type DsfEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_dsd_header",
    "unsupported_dsd_signature",
    "unsupported_dsd_header_size",
    "unsupported_fmt_signature",
    "invalid_fmt_chunk_size",
    "truncated_fmt_chunk_payload",
    "truncated_fmt_audio_fields",
    "truncated_data_chunk_header",
    "unsupported_data_signature",
    "invalid_data_chunk_size",
    "truncated_data_chunk_payload",
    "declared_file_size_mismatch",
    "metadata_offset_out_of_bounds",
    "metadata_length_exceeds_exiftool_limit",
    "metadata_offset_rewrite_required",
    "file_size_rewrite_required",
]
type DsfMetadataRouteKind = Literal["none", "id3", "ignored"]
type DsfActionKind = Literal[
    "preserve_dsd_header",
    "preserve_fmt_chunk",
    "preserve_data_chunk",
    "delegate_id3_metadata",
    "preserve_trailing_metadata",
    "replace_id3_metadata",
    "delete_id3_metadata",
    "no_existing_metadata",
]

DSF_MAIN_TABLE_EVIDENCE_ID = "dsf.main_table"
DSF_MAIN_TABLE_SOURCE = DSF_MAIN_TABLE_EVIDENCE_ID
DSF_HEADER_EVIDENCE_ID = "dsf.header"
DSF_HEADER_SOURCE = DSF_HEADER_EVIDENCE_ID
DSF_FMT_READ_EVIDENCE_ID = "dsf.fmt_read"
DSF_FMT_READ_SOURCE = DSF_FMT_READ_EVIDENCE_ID
DSF_POINTER_EVIDENCE_ID = "dsf.pointer"
DSF_POINTER_SOURCE = DSF_POINTER_EVIDENCE_ID
DSF_ID3_EVIDENCE_ID = "dsf.id3"
DSF_ID3_SOURCE = DSF_ID3_EVIDENCE_ID
DSF_READ_ONLY_EVIDENCE_ID = "dsf.read_only"
DSF_READ_ONLY_SOURCE = DSF_READ_ONLY_EVIDENCE_ID

DSF_TRANSACTION_EVIDENCE_IDS = (
    DSF_MAIN_TABLE_EVIDENCE_ID,
    DSF_HEADER_EVIDENCE_ID,
    DSF_FMT_READ_EVIDENCE_ID,
    DSF_POINTER_EVIDENCE_ID,
    DSF_ID3_EVIDENCE_ID,
    DSF_READ_ONLY_EVIDENCE_ID,
)


@dataclass(frozen=True)
class DsfDsdHeaderPlan:
    signature: bytes
    dsd_chunk_size: int | None
    declared_file_size: int | None
    metadata_offset: int | None
    actual_file_size: int
    declared_size_matches_file: bool
    is_supported_dsd: bool
    reason: DsfEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "actual_file_size": self.actual_file_size,
            "declared_file_size": self.declared_file_size,
            "declared_size_matches_file": self.declared_size_matches_file,
            "dsd_chunk_size": self.dsd_chunk_size,
            "is_supported_dsd": self.is_supported_dsd,
            "metadata_offset": self.metadata_offset,
            "reason": self.reason,
            "signature": ascii_chunk_id(self.signature),
        }


@dataclass(frozen=True)
class DsfFmtChunkPlan:
    chunk_id: bytes
    chunk_offset: int
    declared_size: int | None
    payload_offset: int | None
    payload_length: int | None
    chunk_end_offset: int | None
    format_version: int | None
    format_id: int | None
    channel_type: int | None
    channel_count: int | None
    sample_rate: int | None
    bits_per_sample: int | None
    sample_count: int | None
    block_size: int | None
    duration_seconds: float | None
    is_complete_for_audio_properties: bool
    reason: DsfEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "bits_per_sample": self.bits_per_sample,
            "block_size": self.block_size,
            "channel_count": self.channel_count,
            "channel_type": self.channel_type,
            "chunk_end_offset": self.chunk_end_offset,
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "chunk_offset": self.chunk_offset,
            "declared_size": self.declared_size,
            "duration_seconds": self.duration_seconds,
            "format_id": self.format_id,
            "format_version": self.format_version,
            "is_complete_for_audio_properties": self.is_complete_for_audio_properties,
            "payload_length": self.payload_length,
            "payload_offset": self.payload_offset,
            "reason": self.reason,
            "sample_count": self.sample_count,
            "sample_rate": self.sample_rate,
        }


@dataclass(frozen=True)
class DsfAudioPropertyPlan:
    channel_type: int | None
    channel_count: int | None
    sample_rate: int | None
    bits_per_sample: int | None
    sample_count: int | None
    block_size: int | None
    duration_seconds: float | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "bits_per_sample": self.bits_per_sample,
            "block_size": self.block_size,
            "channel_count": self.channel_count,
            "channel_type": self.channel_type,
            "duration_seconds": self.duration_seconds,
            "sample_count": self.sample_count,
            "sample_rate": self.sample_rate,
        }


@dataclass(frozen=True)
class DsfDataChunkPlan:
    chunk_id: bytes
    chunk_offset: int | None
    declared_size: int | None
    payload_offset: int | None
    payload_length: int | None
    chunk_end_offset: int | None
    preserved: bool
    reason: DsfEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_end_offset": self.chunk_end_offset,
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "chunk_offset": self.chunk_offset,
            "declared_size": self.declared_size,
            "payload_length": self.payload_length,
            "payload_offset": self.payload_offset,
            "preserved": self.preserved,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DsfMetadataPointerPlan:
    metadata_offset: int | None
    declared_file_size: int | None
    metadata_length: int | None
    route_kind: DsfMetadataRouteKind
    id3_payload: bytes
    reason: DsfEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "declared_file_size": self.declared_file_size,
            "id3_payload_length": len(self.id3_payload),
            "metadata_length": self.metadata_length,
            "metadata_offset": self.metadata_offset,
            "reason": self.reason,
            "route_kind": self.route_kind,
        }


@dataclass(frozen=True)
class DsfMetadataActionPlan:
    kind: DsfActionKind
    byte_range_start: int | None
    byte_range_end: int | None
    input_payload_length: int | None
    planned_payload_length: int | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "input_payload_length": self.input_payload_length,
            "kind": self.kind,
            "planned_payload_length": self.planned_payload_length,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DsfOutputEmissionGate:
    code: DsfEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DsfMetadataTransactionPlan:
    status: DsfPlanStatus
    header: DsfDsdHeaderPlan
    fmt_chunk: DsfFmtChunkPlan
    audio_properties: DsfAudioPropertyPlan
    data_chunk: DsfDataChunkPlan
    metadata_pointer: DsfMetadataPointerPlan
    actions: tuple[DsfMetadataActionPlan, ...]
    output_emission_gates: tuple[DsfOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"DSF metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "audio_properties": self.audio_properties.to_json(),
            "can_emit_output": self.can_emit_output,
            "data_chunk": self.data_chunk.to_json(),
            "fmt_chunk": self.fmt_chunk.to_json(),
            "header": self.header.to_json(),
            "metadata_pointer": self.metadata_pointer.to_json(),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "status": self.status,
        }


def build_dsf_metadata_transaction_plan(
    dsf_data: bytes,
    *,
    id3_payload: bytes | None = None,
    delete_id3_metadata: bool = False,
    allow_output_emission: bool = False,
) -> DsfMetadataTransactionPlan:
    header = build_dsd_header_plan(dsf_data)
    fmt_chunk = build_fmt_chunk_plan(dsf_data)
    audio_properties = audio_properties_from_fmt(fmt_chunk)
    data_chunk = build_data_chunk_plan(dsf_data, fmt_chunk)
    metadata_pointer = build_metadata_pointer_plan(dsf_data, header)
    gates = validation_gates(header, fmt_chunk, data_chunk, metadata_pointer)
    actions = build_actions(
        fmt_chunk,
        data_chunk,
        metadata_pointer,
        id3_payload,
        delete_id3_metadata,
    )
    if metadata_edit_requested(metadata_pointer, id3_payload, delete_id3_metadata):
        gates.extend(metadata_rewrite_gates(id3_payload, delete_id3_metadata))
    if not allow_output_emission:
        gates.append(
            DsfOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason=(
                    "DSF transaction plans are non-mutating unless emission is explicitly allowed."
                ),
                evidence_ids=(DSF_READ_ONLY_EVIDENCE_ID,),
            )
        )
    status: DsfPlanStatus = "unsupported" if any_validation_gate(gates) else "planned"
    sources = unique_sources(
        (
            *DSF_TRANSACTION_EVIDENCE_IDS,
            *header.evidence_ids,
            *fmt_chunk.evidence_ids,
            *audio_properties.evidence_ids,
            *data_chunk.evidence_ids,
            *metadata_pointer.evidence_ids,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return DsfMetadataTransactionPlan(
        status=status,
        header=header,
        fmt_chunk=fmt_chunk,
        audio_properties=audio_properties,
        data_chunk=data_chunk,
        metadata_pointer=metadata_pointer,
        actions=actions,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_bytes=dsf_data,
    )


def build_dsd_header_plan(dsf_data: bytes) -> DsfDsdHeaderPlan:
    signature = dsf_data[:4]
    dsd_chunk_size = read_u64le(dsf_data, 4) if len(dsf_data) >= 12 else None
    declared_file_size = read_u64le(dsf_data, 12) if len(dsf_data) >= 20 else None
    metadata_offset = read_u64le(dsf_data, 20) if len(dsf_data) >= DSD_HEADER_SIZE else None
    reason: DsfEmissionGateCode | None = None
    if len(dsf_data) < DSF_INITIAL_READ_SIZE:
        reason = "truncated_dsd_header"
    elif signature != DSD_SIGNATURE:
        reason = "unsupported_dsd_signature"
    elif dsd_chunk_size != DSD_HEADER_SIZE:
        reason = "unsupported_dsd_header_size"
    return DsfDsdHeaderPlan(
        signature=signature,
        dsd_chunk_size=dsd_chunk_size,
        declared_file_size=declared_file_size,
        metadata_offset=metadata_offset,
        actual_file_size=len(dsf_data),
        declared_size_matches_file=declared_file_size == len(dsf_data),
        is_supported_dsd=reason is None,
        reason=reason,
        evidence_ids=(DSF_HEADER_EVIDENCE_ID, DSF_POINTER_EVIDENCE_ID),
    )


def build_fmt_chunk_plan(dsf_data: bytes) -> DsfFmtChunkPlan:
    chunk_id = dsf_data[28:32] if len(dsf_data) >= 32 else b""
    declared_size = read_u64le(dsf_data, 32) if len(dsf_data) >= DSF_INITIAL_READ_SIZE else None
    payload_offset = DSF_INITIAL_READ_SIZE if declared_size is not None else None
    payload_length = declared_size - DSF_CHUNK_HEADER_SIZE if declared_size is not None else None
    chunk_end = 28 + declared_size if declared_size is not None else None
    reason: DsfEmissionGateCode | None = None
    if len(dsf_data) < DSF_INITIAL_READ_SIZE:
        reason = "truncated_dsd_header"
    elif chunk_id != FMT_CHUNK_ID:
        reason = "unsupported_fmt_signature"
    elif declared_size is None or declared_size <= DSF_CHUNK_HEADER_SIZE or declared_size >= 1000:
        reason = "invalid_fmt_chunk_size"
    elif chunk_end is not None and chunk_end > len(dsf_data):
        reason = "truncated_fmt_chunk_payload"
    elif declared_size < DSF_FULL_FMT_SIZE:
        reason = "truncated_fmt_audio_fields"
    format_version = read_u32le(dsf_data, 40) if field_available(dsf_data, 40, chunk_end) else None
    format_id = read_u32le(dsf_data, 44) if field_available(dsf_data, 44, chunk_end) else None
    channel_type = read_u32le(dsf_data, 48) if field_available(dsf_data, 48, chunk_end) else None
    channel_count = read_u32le(dsf_data, 52) if field_available(dsf_data, 52, chunk_end) else None
    sample_rate = read_u32le(dsf_data, 56) if field_available(dsf_data, 56, chunk_end) else None
    bits_per_sample = read_u32le(dsf_data, 60) if field_available(dsf_data, 60, chunk_end) else None
    sample_count = read_u64le(dsf_data, 64) if field_available(dsf_data, 64, chunk_end, 8) else None
    block_size = read_u32le(dsf_data, 72) if field_available(dsf_data, 72, chunk_end) else None
    return DsfFmtChunkPlan(
        chunk_id=chunk_id,
        chunk_offset=DSD_HEADER_SIZE,
        declared_size=declared_size,
        payload_offset=payload_offset,
        payload_length=payload_length,
        chunk_end_offset=chunk_end,
        format_version=format_version,
        format_id=format_id,
        channel_type=channel_type,
        channel_count=channel_count,
        sample_rate=sample_rate,
        bits_per_sample=bits_per_sample,
        sample_count=sample_count,
        block_size=block_size,
        duration_seconds=duration_seconds(sample_count, sample_rate),
        is_complete_for_audio_properties=reason is None,
        reason=reason,
        evidence_ids=(DSF_HEADER_EVIDENCE_ID, DSF_FMT_READ_EVIDENCE_ID, DSF_MAIN_TABLE_EVIDENCE_ID),
    )


def audio_properties_from_fmt(fmt_chunk: DsfFmtChunkPlan) -> DsfAudioPropertyPlan:
    return DsfAudioPropertyPlan(
        channel_type=fmt_chunk.channel_type,
        channel_count=fmt_chunk.channel_count,
        sample_rate=fmt_chunk.sample_rate,
        bits_per_sample=fmt_chunk.bits_per_sample,
        sample_count=fmt_chunk.sample_count,
        block_size=fmt_chunk.block_size,
        duration_seconds=fmt_chunk.duration_seconds,
        evidence_ids=(DSF_MAIN_TABLE_EVIDENCE_ID, DSF_FMT_READ_EVIDENCE_ID),
    )


def build_data_chunk_plan(dsf_data: bytes, fmt_chunk: DsfFmtChunkPlan) -> DsfDataChunkPlan:
    chunk_offset = fmt_chunk.chunk_end_offset
    if chunk_offset is None or fmt_chunk.reason is not None:
        return DsfDataChunkPlan(
            chunk_id=b"",
            chunk_offset=chunk_offset,
            declared_size=None,
            payload_offset=None,
            payload_length=None,
            chunk_end_offset=None,
            preserved=False,
            reason="truncated_data_chunk_header",
            evidence_ids=(DSF_FMT_READ_EVIDENCE_ID,),
        )
    if chunk_offset + DSF_CHUNK_HEADER_SIZE > len(dsf_data):
        return DsfDataChunkPlan(
            chunk_id=dsf_data[chunk_offset : chunk_offset + 4],
            chunk_offset=chunk_offset,
            declared_size=None,
            payload_offset=None,
            payload_length=None,
            chunk_end_offset=None,
            preserved=False,
            reason="truncated_data_chunk_header",
            evidence_ids=(DSF_POINTER_EVIDENCE_ID,),
        )
    chunk_id = dsf_data[chunk_offset : chunk_offset + 4]
    declared_size = read_u64le(dsf_data, chunk_offset + 4)
    payload_offset = chunk_offset + DSF_CHUNK_HEADER_SIZE
    payload_length = declared_size - DSF_CHUNK_HEADER_SIZE
    chunk_end = chunk_offset + declared_size
    reason: DsfEmissionGateCode | None = None
    if chunk_id != DATA_CHUNK_ID:
        reason = "unsupported_data_signature"
    elif declared_size <= DSF_CHUNK_HEADER_SIZE:
        reason = "invalid_data_chunk_size"
    elif chunk_end > len(dsf_data):
        reason = "truncated_data_chunk_payload"
    return DsfDataChunkPlan(
        chunk_id=chunk_id,
        chunk_offset=chunk_offset,
        declared_size=declared_size,
        payload_offset=payload_offset,
        payload_length=payload_length,
        chunk_end_offset=chunk_end,
        preserved=reason is None,
        reason=reason,
        evidence_ids=(DSF_POINTER_EVIDENCE_ID, DSF_READ_ONLY_EVIDENCE_ID),
    )


def build_metadata_pointer_plan(
    dsf_data: bytes,
    header: DsfDsdHeaderPlan,
) -> DsfMetadataPointerPlan:
    metadata_offset = header.metadata_offset
    declared_file_size = header.declared_file_size
    if metadata_offset is None or declared_file_size is None or metadata_offset == 0:
        return DsfMetadataPointerPlan(
            metadata_offset=metadata_offset,
            declared_file_size=declared_file_size,
            metadata_length=None,
            route_kind="none",
            id3_payload=b"",
            reason=None,
            evidence_ids=(DSF_POINTER_EVIDENCE_ID, DSF_ID3_EVIDENCE_ID),
        )
    metadata_length = declared_file_size - metadata_offset
    reason: DsfEmissionGateCode | None = None
    route_kind: DsfMetadataRouteKind = "ignored"
    id3_payload = b""
    if metadata_offset > declared_file_size or metadata_offset > len(dsf_data):
        reason = "metadata_offset_out_of_bounds"
    elif metadata_length <= 0:
        route_kind = "none"
    elif metadata_length >= DSF_METADATA_LENGTH_LIMIT:
        reason = "metadata_length_exceeds_exiftool_limit"
    elif metadata_offset + metadata_length > len(dsf_data):
        reason = "declared_file_size_mismatch"
    else:
        route_kind = "id3"
        id3_payload = dsf_data[metadata_offset : metadata_offset + metadata_length]
    return DsfMetadataPointerPlan(
        metadata_offset=metadata_offset,
        declared_file_size=declared_file_size,
        metadata_length=metadata_length,
        route_kind=route_kind,
        id3_payload=id3_payload,
        reason=reason,
        evidence_ids=(DSF_POINTER_EVIDENCE_ID, DSF_ID3_EVIDENCE_ID),
    )


def build_actions(
    fmt_chunk: DsfFmtChunkPlan,
    data_chunk: DsfDataChunkPlan,
    metadata_pointer: DsfMetadataPointerPlan,
    id3_payload: bytes | None,
    delete_id3_metadata: bool,
) -> tuple[DsfMetadataActionPlan, ...]:
    actions: list[DsfMetadataActionPlan] = [
        DsfMetadataActionPlan(
            kind="preserve_dsd_header",
            byte_range_start=0,
            byte_range_end=DSD_HEADER_SIZE,
            input_payload_length=DSD_HEADER_SIZE,
            planned_payload_length=DSD_HEADER_SIZE,
            reason="Preserve the DSD header while planning metadata responsibilities.",
            evidence_ids=(DSF_HEADER_EVIDENCE_ID, DSF_POINTER_EVIDENCE_ID),
        )
    ]
    if fmt_chunk.chunk_end_offset is not None:
        actions.append(
            DsfMetadataActionPlan(
                kind="preserve_fmt_chunk",
                byte_range_start=fmt_chunk.chunk_offset,
                byte_range_end=fmt_chunk.chunk_end_offset,
                input_payload_length=fmt_chunk.declared_size,
                planned_payload_length=fmt_chunk.declared_size,
                reason="Preserve the ExifTool-modeled fmt chunk bytes.",
                evidence_ids=fmt_chunk.evidence_ids,
            )
        )
    if data_chunk.chunk_offset is not None and data_chunk.chunk_end_offset is not None:
        actions.append(
            DsfMetadataActionPlan(
                kind="preserve_data_chunk",
                byte_range_start=data_chunk.chunk_offset,
                byte_range_end=data_chunk.chunk_end_offset,
                input_payload_length=data_chunk.declared_size,
                planned_payload_length=data_chunk.declared_size,
                reason="Preserve DSD audio data bytes; DSF.pm does not model them as metadata.",
                evidence_ids=data_chunk.evidence_ids,
            )
        )
    actions.extend(metadata_actions(metadata_pointer, id3_payload, delete_id3_metadata))
    return tuple(actions)


def metadata_actions(
    metadata_pointer: DsfMetadataPointerPlan,
    id3_payload: bytes | None,
    delete_id3_metadata: bool,
) -> tuple[DsfMetadataActionPlan, ...]:
    if delete_id3_metadata and metadata_pointer.route_kind == "id3":
        return (
            DsfMetadataActionPlan(
                kind="delete_id3_metadata",
                byte_range_start=metadata_pointer.metadata_offset,
                byte_range_end=metadata_end(metadata_pointer),
                input_payload_length=metadata_pointer.metadata_length,
                planned_payload_length=0,
                reason="Plan removal of trailing ID3 metadata while gating DSF pointer rewrites.",
                evidence_ids=(DSF_ID3_EVIDENCE_ID, DSF_READ_ONLY_EVIDENCE_ID),
            ),
        )
    if id3_payload is not None:
        return (
            DsfMetadataActionPlan(
                kind="replace_id3_metadata",
                byte_range_start=metadata_pointer.metadata_offset,
                byte_range_end=metadata_end(metadata_pointer),
                input_payload_length=metadata_pointer.metadata_length,
                planned_payload_length=len(id3_payload),
                reason="Plan replacement or insertion of ID3 metadata at the DSF metadata pointer.",
                evidence_ids=(DSF_ID3_EVIDENCE_ID, DSF_READ_ONLY_EVIDENCE_ID),
            ),
        )
    if metadata_pointer.route_kind == "id3":
        return (
            DsfMetadataActionPlan(
                kind="delegate_id3_metadata",
                byte_range_start=metadata_pointer.metadata_offset,
                byte_range_end=metadata_end(metadata_pointer),
                input_payload_length=metadata_pointer.metadata_length,
                planned_payload_length=metadata_pointer.metadata_length,
                reason="Delegate the pointed trailing metadata to ExifTool's ID3 table.",
                evidence_ids=metadata_pointer.evidence_ids,
            ),
            DsfMetadataActionPlan(
                kind="preserve_trailing_metadata",
                byte_range_start=metadata_pointer.metadata_offset,
                byte_range_end=metadata_end(metadata_pointer),
                input_payload_length=metadata_pointer.metadata_length,
                planned_payload_length=metadata_pointer.metadata_length,
                reason="Preserve existing trailing metadata bytes during non-mutating planning.",
                evidence_ids=(DSF_ID3_EVIDENCE_ID, DSF_READ_ONLY_EVIDENCE_ID),
            ),
        )
    return (
        DsfMetadataActionPlan(
            kind="no_existing_metadata",
            byte_range_start=None,
            byte_range_end=None,
            input_payload_length=None,
            planned_payload_length=None,
            reason="No ExifTool-readable DSF metadata pointer is present.",
            evidence_ids=(DSF_POINTER_EVIDENCE_ID, DSF_ID3_EVIDENCE_ID),
        ),
    )


def validation_gates(
    header: DsfDsdHeaderPlan,
    fmt_chunk: DsfFmtChunkPlan,
    data_chunk: DsfDataChunkPlan,
    metadata_pointer: DsfMetadataPointerPlan,
) -> list[DsfOutputEmissionGate]:
    gates: list[DsfOutputEmissionGate] = []
    append_reason_gate(
        gates,
        header.reason,
        "DSD header validation failed.",
        header.evidence_ids,
    )
    append_reason_gate(
        gates,
        fmt_chunk.reason,
        "DSF fmt chunk validation failed.",
        fmt_chunk.evidence_ids,
    )
    append_reason_gate(
        gates,
        data_chunk.reason,
        "DSF data chunk preservation validation failed.",
        data_chunk.evidence_ids,
    )
    append_reason_gate(
        gates,
        metadata_pointer.reason,
        "DSF metadata pointer cannot be read with ExifTool's constraints.",
        metadata_pointer.evidence_ids,
    )
    if (
        header.declared_file_size is not None
        and header.reason is None
        and header.declared_file_size != header.actual_file_size
    ):
        gates.append(
            DsfOutputEmissionGate(
                code="declared_file_size_mismatch",
                reason="The DSD FileSize field does not match the available input bytes.",
                evidence_ids=(DSF_POINTER_EVIDENCE_ID,),
            )
        )
    return gates


def metadata_rewrite_gates(
    id3_payload: bytes | None,
    delete_id3_metadata: bool,
) -> tuple[DsfOutputEmissionGate, ...]:
    planned_length = 0 if delete_id3_metadata else len(id3_payload or b"")
    return (
        DsfOutputEmissionGate(
            code="metadata_offset_rewrite_required",
            reason=(
                "Changing DSF metadata requires updating or clearing the DSD MetadataPointer "
                f"for the planned {planned_length}-byte metadata payload."
            ),
            evidence_ids=(DSF_POINTER_EVIDENCE_ID, DSF_READ_ONLY_EVIDENCE_ID),
        ),
        DsfOutputEmissionGate(
            code="file_size_rewrite_required",
            reason="Changing DSF metadata requires rewriting the DSD FileSize field.",
            evidence_ids=(DSF_POINTER_EVIDENCE_ID, DSF_READ_ONLY_EVIDENCE_ID),
        ),
    )


def metadata_edit_requested(
    metadata_pointer: DsfMetadataPointerPlan,
    id3_payload: bytes | None,
    delete_id3_metadata: bool,
) -> bool:
    if delete_id3_metadata:
        return metadata_pointer.route_kind == "id3"
    if id3_payload is None:
        return False
    return id3_payload != metadata_pointer.id3_payload


def append_reason_gate(
    gates: list[DsfOutputEmissionGate],
    code: DsfEmissionGateCode | None,
    reason: str,
    evidence_ids: tuple[str, ...],
) -> None:
    if code is None:
        return
    gates.append(
        DsfOutputEmissionGate(
            code=code,
            reason=reason,
            evidence_ids=evidence_ids,
        )
    )


def any_validation_gate(gates: list[DsfOutputEmissionGate]) -> bool:
    validation_codes = {
        "truncated_dsd_header",
        "unsupported_dsd_signature",
        "unsupported_dsd_header_size",
        "unsupported_fmt_signature",
        "invalid_fmt_chunk_size",
        "truncated_fmt_chunk_payload",
        "truncated_fmt_audio_fields",
        "truncated_data_chunk_header",
        "unsupported_data_signature",
        "invalid_data_chunk_size",
        "truncated_data_chunk_payload",
        "declared_file_size_mismatch",
        "metadata_offset_out_of_bounds",
        "metadata_length_exceeds_exiftool_limit",
    }
    return any(gate.code in validation_codes for gate in gates)


def metadata_end(metadata_pointer: DsfMetadataPointerPlan) -> int | None:
    if metadata_pointer.metadata_offset is None or metadata_pointer.metadata_length is None:
        return None
    return metadata_pointer.metadata_offset + metadata_pointer.metadata_length


def duration_seconds(sample_count: int | None, sample_rate: int | None) -> float | None:
    if sample_count is None or sample_rate is None or sample_rate == 0:
        return None
    return sample_count / sample_rate


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def read_u64le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little")


def field_available(
    data: bytes,
    offset: int,
    chunk_end: int | None,
    length: int = 4,
) -> bool:
    return chunk_end is not None and offset + length <= chunk_end and offset + length <= len(data)


def ascii_chunk_id(chunk_id: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else f"\\x{byte:02x}" for byte in chunk_id)


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return [value for value in values]


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for reference in references:
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(reference)
    return tuple(unique)


def unique_gates(gates: tuple[DsfOutputEmissionGate, ...]) -> tuple[DsfOutputEmissionGate, ...]:
    seen: set[DsfEmissionGateCode] = set()
    unique: list[DsfOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
