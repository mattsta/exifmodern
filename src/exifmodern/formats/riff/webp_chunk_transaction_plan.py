"""Source-backed, non-mutating RIFF/WebP chunk transaction plans.

ExifTool's WebP RIFF writer is a two-pass chunk rewriter: it validates a RIFF
WEBP header, walks padded chunks, edits metadata chunks with EXIF before XMP,
updates VP8X feature flags, and only then writes the final RIFF size.  This
module models those decisions without writing files.  Byte emission is gated to
the mutation boundary already supported by ``riff.webp_writer``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan
from exifmodern.formats.riff.webp_writer import (
    EXIF_CHUNK_ID,
    ICC_CHUNK_ID,
    INCORRECT_XMP_CHUNK_ID,
    VP8X_CHUNK_ID,
    WEBP_DELETABLE_METADATA_CHUNK_IDS,
    WEBP_FLAG_EXIF,
    WEBP_FLAG_ICC,
    WEBP_FLAG_XMP,
    WEBP_FORM_TYPE,
    XMP_CHUNK_ID,
    RiffChunk,
    create_vp8x_chunk,
    encode_webp_chunks,
    existing_chunk_payload,
    rewritten_exif_chunk,
    webp_chunks_need_vp8x,
    webp_image_dimensions,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan
from exifmodern.json_types import JsonArray, JsonObject

RIFF_CHUNK_HEADER_SIZE = 8
RIFF_WEBP_HEADER_SIZE = 12
VP8X_PAYLOAD_SIZE = 10

type WebpChunkActionKind = Literal[
    "copy",
    "delete_metadata",
    "delete_duplicate_metadata",
    "insert_metadata",
    "replace_metadata",
    "insert_vp8x",
    "replace_vp8x_flags",
    "delete_vp8x",
    "update_riff_size",
]
type WebpChunkPlanStatus = Literal["planned", "unsupported"]
type WebpEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_riff_header",
    "unsupported_riff_signature",
    "unsupported_riff_variant",
    "unsupported_riff_form_type",
    "truncated_riff_chunk",
    "missing_odd_chunk_padding",
    "trailing_partial_chunk_header",
    "empty_null_chunk",
    "truncated_vp8x_chunk",
    "vp8x_creation_requires_image_size_support",
]

RIFF_HEADER_SOURCE = "riff.webp_chunk.riff_header"
RIFF_CHUNK_ENUMERATION_SOURCE = "riff.webp_chunk.riff_chunk_enumeration"
WEBP_METADATA_ORDER_SOURCE = "riff.webp_chunk.webp_metadata_order"
WEBP_METADATA_CHUNK_SOURCE = "riff.webp_chunk.webp_metadata_chunk"
WEBP_DELETABLE_GROUP_SOURCE = "riff.webp_chunk.webp_deletable_group"
WEBP_VP8X_SOURCE = "riff.webp_chunk.webp_vp8x"
WEBP_VP8X_FLAGS_SOURCE = "riff.webp_chunk.webp_vp8x_flags"
RIFF_SIZE_SOURCE = "riff.webp_chunk.riff_size"
CURRENT_WRITER_BOUNDARY_SOURCE = "riff.webp_chunk.current_writer_boundary"


@dataclass(frozen=True)
class WebpRiffHeaderPlan:
    signature: bytes
    declared_size: int | None
    form_type: bytes
    actual_file_size: int
    declared_file_size: int | None
    declared_size_matches_file: bool
    is_valid_webp_riff: bool
    reason: WebpEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "actual_file_size": self.actual_file_size,
            "declared_file_size": self.declared_file_size,
            "declared_size": self.declared_size,
            "declared_size_matches_file": self.declared_size_matches_file,
            "form_type": ascii_chunk_id(self.form_type),
            "is_valid_webp_riff": self.is_valid_webp_riff,
            "reason": self.reason,
            "signature": ascii_chunk_id(self.signature),
        }


@dataclass(frozen=True)
class WebpChunkEnumerationPlan:
    index: int
    chunk_id: bytes
    chunk_start_offset: int
    payload_offset: int
    payload_length: int
    padding_length: int
    padded_end_offset: int
    payload: bytes
    evidence_ids: tuple[str, ...]

    @property
    def encoded_length(self) -> int:
        return RIFF_CHUNK_HEADER_SIZE + self.payload_length + self.padding_length

    def to_riff_chunk(self) -> RiffChunk:
        return RiffChunk(self.chunk_id, self.payload)

    def to_json(self) -> JsonObject:
        return {
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "chunk_start_offset": self.chunk_start_offset,
            "encoded_length": self.encoded_length,
            "index": self.index,
            "padded_end_offset": self.padded_end_offset,
            "padding_length": self.padding_length,
            "payload_length": self.payload_length,
            "payload_offset": self.payload_offset,
        }


@dataclass(frozen=True)
class WebpChunkActionPlan:
    kind: WebpChunkActionKind
    chunk_id: bytes
    original_index: int | None
    output_index: int | None
    original_payload_length: int | None
    output_payload_length: int | None
    padding_length: int
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "kind": self.kind,
            "original_index": self.original_index,
            "original_payload_length": self.original_payload_length,
            "output_index": self.output_index,
            "output_payload_length": self.output_payload_length,
            "padding_length": self.padding_length,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class WebpOutputEmissionGate:
    code: WebpEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class WebpRiffSizeUpdatePlan:
    original_declared_size: int | None
    planned_declared_size: int | None
    planned_file_size: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "original_declared_size": self.original_declared_size,
            "planned_declared_size": self.planned_declared_size,
            "planned_file_size": self.planned_file_size,
        }


@dataclass(frozen=True)
class WebpChunkTransactionPlan:
    status: WebpChunkPlanStatus
    header: WebpRiffHeaderPlan
    chunks: tuple[WebpChunkEnumerationPlan, ...]
    actions: tuple[WebpChunkActionPlan, ...]
    output_chunks: tuple[RiffChunk, ...]
    riff_size_update: WebpRiffSizeUpdatePlan
    output_emission_gates: tuple[WebpOutputEmissionGate, ...]
    deleted_metadata_chunks: int
    changed_exif_properties: int
    changed_xmp_properties: int
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"WebP chunk transaction output is gated: {gate_codes}")
        return encode_webp_chunks(self.output_chunks)

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "changed_exif_properties": self.changed_exif_properties,
            "changed_xmp_properties": self.changed_xmp_properties,
            "chunks": json_object_array(chunk.to_json() for chunk in self.chunks),
            "deleted_metadata_chunks": self.deleted_metadata_chunks,
            "header": self.header.to_json(),
            "output_chunk_ids": [ascii_chunk_id(chunk.chunk_id) for chunk in self.output_chunks],
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "riff_size_update": self.riff_size_update.to_json(),
            "status": self.status,
        }


def build_webp_metadata_write_transaction_plan(
    webp_data: bytes,
    exif_plan: ExifScalarWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    delete_all_metadata: bool,
    *,
    allow_output_emission: bool = False,
) -> WebpChunkTransactionPlan:
    """Build a chunk plan from the existing scalar/XMP writer plans."""

    preflight = build_webp_chunk_transaction_plan(
        webp_data,
        delete_all_metadata=False,
        allow_output_emission=False,
    )
    if preflight.status == "unsupported":
        return preflight

    chunks = tuple(chunk.to_riff_chunk() for chunk in preflight.chunks)
    exif_payload = None
    xmp_payload = None
    changed_exif_properties = 0
    changed_xmp_properties = 0
    if exif_plan is not None and not delete_all_metadata:
        exif_payload = rewritten_exif_chunk(chunks, exif_plan)
        changed_exif_properties = len(exif_plan.steps)
    if xmp_plan is not None and not delete_all_metadata:
        existing_xmp = existing_chunk_payload(chunks, XMP_CHUNK_ID) or empty_xmp_packet()
        xmp_result = apply_xmp_property_write_plan(existing_xmp, xmp_plan)
        xmp_payload = xmp_result.packet
        changed_xmp_properties = xmp_result.changed_properties

    plan = build_webp_chunk_transaction_plan(
        webp_data,
        exif_payload=exif_payload,
        xmp_payload=xmp_payload,
        delete_all_metadata=delete_all_metadata,
        allow_output_emission=allow_output_emission,
    )
    return WebpChunkTransactionPlan(
        status=plan.status,
        header=plan.header,
        chunks=plan.chunks,
        actions=plan.actions,
        output_chunks=plan.output_chunks,
        riff_size_update=plan.riff_size_update,
        output_emission_gates=plan.output_emission_gates,
        deleted_metadata_chunks=plan.deleted_metadata_chunks,
        changed_exif_properties=changed_exif_properties,
        changed_xmp_properties=changed_xmp_properties,
        evidence_ids=plan.evidence_ids,
    )


def build_webp_chunk_transaction_plan(
    webp_data: bytes,
    *,
    exif_payload: bytes | None = None,
    xmp_payload: bytes | None = None,
    delete_all_metadata: bool = False,
    allow_output_emission: bool = False,
) -> WebpChunkTransactionPlan:
    header = build_riff_header_plan(webp_data)
    gates: list[WebpOutputEmissionGate] = []
    if header.reason is not None:
        gates.append(
            WebpOutputEmissionGate(
                header.reason,
                "RIFF/WebP header is not writable.",
                (RIFF_HEADER_SOURCE,),
            )
        )
        return unsupported_plan(header, gates)

    chunks, chunk_gates = enumerate_webp_chunks(webp_data)
    gates.extend(chunk_gates)
    if chunk_gates:
        return unsupported_plan(header, gates, chunks=chunks)

    actions, output_chunks, deleted_metadata_chunks = plan_chunk_actions(
        chunks,
        exif_payload=exif_payload,
        xmp_payload=xmp_payload,
        delete_all_metadata=delete_all_metadata,
    )
    actions, output_chunks, vp8x_gates = plan_vp8x_actions(
        chunks,
        actions,
        output_chunks,
        metadata_changed=delete_all_metadata
        or exif_payload is not None
        or xmp_payload is not None
        or deleted_metadata_chunks > 0,
    )
    gates.extend(vp8x_gates)
    if not allow_output_emission:
        gates.append(
            WebpOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "Chunk transaction plans are non-mutating unless emission is explicitly allowed.",
                (CURRENT_WRITER_BOUNDARY_SOURCE,),
            )
        )

    planned_size = len(WEBP_FORM_TYPE) + sum(encoded_chunk_length(chunk) for chunk in output_chunks)
    riff_size_update = WebpRiffSizeUpdatePlan(
        original_declared_size=header.declared_size,
        planned_declared_size=planned_size,
        planned_file_size=planned_size + 8,
        evidence_ids=(RIFF_SIZE_SOURCE,),
    )
    actions = (
        *actions,
        WebpChunkActionPlan(
            kind="update_riff_size",
            chunk_id=b"RIFF",
            original_index=None,
            output_index=None,
            original_payload_length=header.declared_size,
            output_payload_length=planned_size,
            padding_length=0,
            reason="Set RIFF size to planned output bytes minus the eight-byte RIFF prefix.",
            evidence_ids=(RIFF_SIZE_SOURCE,),
        ),
    )
    sources = unique_sources(
        (
            RIFF_HEADER_SOURCE,
            RIFF_CHUNK_ENUMERATION_SOURCE,
            WEBP_METADATA_ORDER_SOURCE,
            WEBP_METADATA_CHUNK_SOURCE,
            WEBP_VP8X_SOURCE,
            WEBP_VP8X_FLAGS_SOURCE,
            RIFF_SIZE_SOURCE,
            CURRENT_WRITER_BOUNDARY_SOURCE,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return WebpChunkTransactionPlan(
        status="planned",
        header=header,
        chunks=chunks,
        actions=actions,
        output_chunks=output_chunks,
        riff_size_update=riff_size_update,
        output_emission_gates=unique_gates(tuple(gates)),
        deleted_metadata_chunks=deleted_metadata_chunks,
        changed_exif_properties=0,
        changed_xmp_properties=0,
        evidence_ids=sources,
    )


def build_riff_header_plan(webp_data: bytes) -> WebpRiffHeaderPlan:
    signature = webp_data[:4]
    form_type = webp_data[8:12] if len(webp_data) >= RIFF_WEBP_HEADER_SIZE else b""
    declared_size = (
        int.from_bytes(webp_data[4:8], "little")
        if len(webp_data) >= RIFF_WEBP_HEADER_SIZE
        else None
    )
    declared_file_size = declared_size + 8 if declared_size is not None else None
    reason: WebpEmissionGateCode | None = None
    if len(webp_data) < RIFF_WEBP_HEADER_SIZE:
        reason = "truncated_riff_header"
    elif signature == b"RF64":
        reason = "unsupported_riff_variant"
    elif signature != b"RIFF":
        reason = "unsupported_riff_signature"
    elif form_type != WEBP_FORM_TYPE:
        reason = "unsupported_riff_form_type"
    return WebpRiffHeaderPlan(
        signature=signature,
        declared_size=declared_size,
        form_type=form_type,
        actual_file_size=len(webp_data),
        declared_file_size=declared_file_size,
        declared_size_matches_file=declared_file_size == len(webp_data),
        is_valid_webp_riff=reason is None,
        reason=reason,
        evidence_ids=(RIFF_HEADER_SOURCE,),
    )


def enumerate_webp_chunks(
    webp_data: bytes,
) -> tuple[tuple[WebpChunkEnumerationPlan, ...], tuple[WebpOutputEmissionGate, ...]]:
    chunks: list[WebpChunkEnumerationPlan] = []
    gates: list[WebpOutputEmissionGate] = []
    offset = RIFF_WEBP_HEADER_SIZE
    while offset + RIFF_CHUNK_HEADER_SIZE <= len(webp_data):
        chunk_start = offset
        chunk_id = webp_data[offset : offset + 4]
        payload_length = int.from_bytes(webp_data[offset + 4 : offset + 8], "little")
        payload_offset = offset + RIFF_CHUNK_HEADER_SIZE
        payload_end = payload_offset + payload_length
        padding_length = payload_length & 1
        padded_end = payload_end + padding_length
        if payload_end > len(webp_data):
            gates.append(
                WebpOutputEmissionGate(
                    "truncated_riff_chunk",
                    f"Chunk {ascii_chunk_id(chunk_id)} declares {payload_length} payload bytes.",
                    (RIFF_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            break
        if payload_length == 0 and chunk_id == b"\x00\x00\x00\x00":
            gates.append(
                WebpOutputEmissionGate(
                    "empty_null_chunk",
                    "Empty null RIFF chunks abort ExifTool processing instead of being rewritten.",
                    (RIFF_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            break
        if padded_end > len(webp_data):
            gates.append(
                WebpOutputEmissionGate(
                    "missing_odd_chunk_padding",
                    f"Odd-sized chunk {ascii_chunk_id(chunk_id)} has no padding byte.",
                    (RIFF_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            break
        chunks.append(
            WebpChunkEnumerationPlan(
                index=len(chunks),
                chunk_id=chunk_id,
                chunk_start_offset=chunk_start,
                payload_offset=payload_offset,
                payload_length=payload_length,
                padding_length=padding_length,
                padded_end_offset=padded_end,
                payload=webp_data[payload_offset:payload_end],
                evidence_ids=(RIFF_CHUNK_ENUMERATION_SOURCE,),
            )
        )
        offset = padded_end
    if not gates and offset != len(webp_data):
        gates.append(
            WebpOutputEmissionGate(
                "trailing_partial_chunk_header",
                "Trailing bytes are not enough to form a RIFF chunk header.",
                (RIFF_CHUNK_ENUMERATION_SOURCE,),
            )
        )
    return tuple(chunks), tuple(gates)


def plan_chunk_actions(
    chunks: tuple[WebpChunkEnumerationPlan, ...],
    *,
    exif_payload: bytes | None,
    xmp_payload: bytes | None,
    delete_all_metadata: bool,
) -> tuple[tuple[WebpChunkActionPlan, ...], tuple[RiffChunk, ...], int]:
    actions: list[WebpChunkActionPlan] = []
    output_chunks: list[RiffChunk] = []
    deleted_metadata_chunks = 0
    exif_written = False
    xmp_written = False
    exif_is_add = exif_payload is not None and not any(
        chunk.chunk_id == EXIF_CHUNK_ID for chunk in chunks
    )

    for chunk in chunks:
        if delete_all_metadata and chunk.chunk_id in WEBP_DELETABLE_METADATA_CHUNK_IDS:
            deleted_metadata_chunks += 1
            actions.append(delete_metadata_action(chunk))
            continue
        if chunk.chunk_id == EXIF_CHUNK_ID and exif_payload is not None:
            if exif_written:
                actions.append(delete_duplicate_metadata_action(chunk))
                continue
            append_output_chunk(
                output_chunks,
                actions,
                RiffChunk(EXIF_CHUNK_ID, exif_payload),
                "replace_metadata",
                chunk.index,
                chunk.payload_length,
                "Replace the first EXIF chunk and suppress duplicate EXIF chunks.",
                (WEBP_METADATA_ORDER_SOURCE, WEBP_METADATA_CHUNK_SOURCE),
            )
            exif_written = True
            continue
        if chunk.chunk_id == XMP_CHUNK_ID:
            if exif_is_add and not exif_written:
                append_output_chunk(
                    output_chunks,
                    actions,
                    RiffChunk(EXIF_CHUNK_ID, exif_payload or b""),
                    "insert_metadata",
                    None,
                    None,
                    "Insert a newly-created EXIF chunk before the first XMP chunk.",
                    (WEBP_METADATA_ORDER_SOURCE, WEBP_METADATA_CHUNK_SOURCE),
                )
                exif_written = True
            if xmp_payload is not None:
                if xmp_written:
                    actions.append(delete_duplicate_metadata_action(chunk))
                    continue
                append_output_chunk(
                    output_chunks,
                    actions,
                    RiffChunk(XMP_CHUNK_ID, xmp_payload),
                    "replace_metadata",
                    chunk.index,
                    chunk.payload_length,
                    "Replace the first XMP chunk and suppress duplicate XMP chunks.",
                    (WEBP_METADATA_ORDER_SOURCE, WEBP_METADATA_CHUNK_SOURCE),
                )
                xmp_written = True
                continue
        append_output_chunk(
            output_chunks,
            actions,
            chunk.to_riff_chunk(),
            "copy",
            chunk.index,
            chunk.payload_length,
            "Copy chunk unchanged.",
            (RIFF_CHUNK_ENUMERATION_SOURCE,),
        )

    if exif_payload is not None and not exif_written:
        append_output_chunk(
            output_chunks,
            actions,
            RiffChunk(EXIF_CHUNK_ID, exif_payload),
            "insert_metadata",
            None,
            None,
            "Append a newly-created EXIF chunk because no XMP insertion point exists.",
            (WEBP_METADATA_ORDER_SOURCE, WEBP_METADATA_CHUNK_SOURCE),
        )
    if xmp_payload is not None and not xmp_written:
        append_output_chunk(
            output_chunks,
            actions,
            RiffChunk(XMP_CHUNK_ID, xmp_payload),
            "insert_metadata",
            None,
            None,
            "Append a newly-created XMP chunk after existing chunks.",
            (WEBP_METADATA_ORDER_SOURCE, WEBP_METADATA_CHUNK_SOURCE),
        )
    return tuple(actions), tuple(output_chunks), deleted_metadata_chunks


def plan_vp8x_actions(
    original_chunks: tuple[WebpChunkEnumerationPlan, ...],
    actions: tuple[WebpChunkActionPlan, ...],
    output_chunks: tuple[RiffChunk, ...],
    *,
    metadata_changed: bool,
) -> tuple[
    tuple[WebpChunkActionPlan, ...],
    tuple[RiffChunk, ...],
    tuple[WebpOutputEmissionGate, ...],
]:
    planned_actions = list(actions)
    planned_chunks = list(output_chunks)
    gates: list[WebpOutputEmissionGate] = []
    has_vp8x = any(chunk.chunk_id == VP8X_CHUNK_ID for chunk in planned_chunks)
    needs_vp8x = webp_chunks_need_vp8x(tuple(planned_chunks))
    original_vp8x = next(
        (chunk for chunk in original_chunks if chunk.chunk_id == VP8X_CHUNK_ID),
        None,
    )

    if has_vp8x and not needs_vp8x and metadata_changed:
        planned_chunks = [chunk for chunk in planned_chunks if chunk.chunk_id != VP8X_CHUNK_ID]
        planned_actions.append(
            WebpChunkActionPlan(
                kind="delete_vp8x",
                chunk_id=VP8X_CHUNK_ID,
                original_index=original_vp8x.index if original_vp8x is not None else None,
                output_index=None,
                original_payload_length=(
                    original_vp8x.payload_length if original_vp8x is not None else None
                ),
                output_payload_length=None,
                padding_length=0,
                reason="Source writer deletes VP8X when no extended WebP feature remains.",
                evidence_ids=(WEBP_VP8X_SOURCE,),
            )
        )
        return tuple(planned_actions), tuple(planned_chunks), tuple(gates)

    if needs_vp8x and not has_vp8x and metadata_changed:
        dimensions = webp_image_dimensions(tuple(planned_chunks))
        planned_actions.append(
            WebpChunkActionPlan(
                kind="insert_vp8x",
                chunk_id=VP8X_CHUNK_ID,
                original_index=None,
                output_index=0,
                original_payload_length=None,
                output_payload_length=VP8X_PAYLOAD_SIZE,
                padding_length=0,
                reason="Source writer requires VP8X when metadata or extended features exist.",
                evidence_ids=(WEBP_VP8X_SOURCE,),
            )
        )
        if dimensions is not None:
            planned_chunks.insert(0, create_vp8x_chunk(tuple(planned_chunks), dimensions))
            return tuple(planned_actions), tuple(planned_chunks), tuple(gates)
        gates.append(
            WebpOutputEmissionGate(
                "vp8x_creation_requires_image_size_support",
                "VP8X creation requires source-backed image size extraction.",
                (WEBP_VP8X_SOURCE, CURRENT_WRITER_BOUNDARY_SOURCE),
            )
        )
        return tuple(planned_actions), tuple(planned_chunks), tuple(gates)

    if not has_vp8x:
        return tuple(planned_actions), tuple(planned_chunks), tuple(gates)

    updated_chunks: list[RiffChunk] = []
    replaced = False
    for output_index, chunk in enumerate(planned_chunks):
        if chunk.chunk_id != VP8X_CHUNK_ID:
            updated_chunks.append(chunk)
            continue
        if len(chunk.payload) < VP8X_PAYLOAD_SIZE:
            gates.append(
                WebpOutputEmissionGate(
                    "truncated_vp8x_chunk",
                    "VP8X chunks must have at least ten payload bytes before flags can be updated.",
                    (WEBP_VP8X_FLAGS_SOURCE,),
                )
            )
            updated_chunks.append(chunk)
            continue
        if replaced:
            updated_chunks.append(chunk)
            continue
        flags = int.from_bytes(chunk.payload[:4], "little")
        updated_flags = planned_vp8x_flags(flags, planned_chunks)
        updated_payload = updated_flags.to_bytes(4, "little") + chunk.payload[4:]
        updated_chunks.append(RiffChunk(VP8X_CHUNK_ID, updated_payload))
        if updated_payload != chunk.payload:
            planned_actions.append(
                WebpChunkActionPlan(
                    kind="replace_vp8x_flags",
                    chunk_id=VP8X_CHUNK_ID,
                    original_index=(
                        original_vp8x.index if original_vp8x is not None else output_index
                    ),
                    output_index=output_index,
                    original_payload_length=len(chunk.payload),
                    output_payload_length=len(updated_payload),
                    padding_length=len(updated_payload) & 1,
                    reason=(
                        "Reset and set writable VP8X metadata flags from planned chunk presence."
                    ),
                    evidence_ids=(WEBP_VP8X_FLAGS_SOURCE,),
                )
            )
        replaced = True
    return tuple(planned_actions), tuple(updated_chunks), tuple(gates)


def planned_vp8x_flags(flags: int, chunks: Iterable[RiffChunk]) -> int:
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    flags &= ~(WEBP_FLAG_XMP | WEBP_FLAG_EXIF | WEBP_FLAG_ICC)
    if XMP_CHUNK_ID in chunk_ids:
        flags |= WEBP_FLAG_XMP
    if EXIF_CHUNK_ID in chunk_ids:
        flags |= WEBP_FLAG_EXIF
    if ICC_CHUNK_ID in chunk_ids:
        flags |= WEBP_FLAG_ICC
    return flags


def append_output_chunk(
    output_chunks: list[RiffChunk],
    actions: list[WebpChunkActionPlan],
    chunk: RiffChunk,
    kind: WebpChunkActionKind,
    original_index: int | None,
    original_payload_length: int | None,
    reason: str,
    evidence_ids: tuple[str, ...],
) -> None:
    output_index = len(output_chunks)
    output_chunks.append(chunk)
    actions.append(
        WebpChunkActionPlan(
            kind=kind,
            chunk_id=chunk.chunk_id,
            original_index=original_index,
            output_index=output_index,
            original_payload_length=original_payload_length,
            output_payload_length=len(chunk.payload),
            padding_length=len(chunk.payload) & 1,
            reason=reason,
            evidence_ids=evidence_ids,
        )
    )


def delete_metadata_action(chunk: WebpChunkEnumerationPlan) -> WebpChunkActionPlan:
    evidence_ids = (
        (WEBP_DELETABLE_GROUP_SOURCE,)
        if chunk.chunk_id == INCORRECT_XMP_CHUNK_ID
        else (WEBP_METADATA_ORDER_SOURCE, WEBP_METADATA_CHUNK_SOURCE)
    )
    return WebpChunkActionPlan(
        kind="delete_metadata",
        chunk_id=chunk.chunk_id,
        original_index=chunk.index,
        output_index=None,
        original_payload_length=chunk.payload_length,
        output_payload_length=None,
        padding_length=0,
        reason="Delete metadata chunk for all-metadata removal.",
        evidence_ids=evidence_ids,
    )


def delete_duplicate_metadata_action(chunk: WebpChunkEnumerationPlan) -> WebpChunkActionPlan:
    return WebpChunkActionPlan(
        kind="delete_duplicate_metadata",
        chunk_id=chunk.chunk_id,
        original_index=chunk.index,
        output_index=None,
        original_payload_length=chunk.payload_length,
        output_payload_length=None,
        padding_length=0,
        reason="Suppress duplicate metadata chunks after the first planned replacement.",
        evidence_ids=(WEBP_METADATA_ORDER_SOURCE, WEBP_METADATA_CHUNK_SOURCE),
    )


def unsupported_plan(
    header: WebpRiffHeaderPlan,
    gates: list[WebpOutputEmissionGate],
    *,
    chunks: tuple[WebpChunkEnumerationPlan, ...] = (),
) -> WebpChunkTransactionPlan:
    sources = unique_sources(
        (
            RIFF_HEADER_SOURCE,
            RIFF_CHUNK_ENUMERATION_SOURCE,
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return WebpChunkTransactionPlan(
        status="unsupported",
        header=header,
        chunks=chunks,
        actions=(),
        output_chunks=(),
        riff_size_update=WebpRiffSizeUpdatePlan(
            original_declared_size=header.declared_size,
            planned_declared_size=None,
            planned_file_size=None,
            evidence_ids=(RIFF_SIZE_SOURCE,),
        ),
        output_emission_gates=unique_gates(tuple(gates)),
        deleted_metadata_chunks=0,
        changed_exif_properties=0,
        changed_xmp_properties=0,
        evidence_ids=sources,
    )


def encoded_chunk_length(chunk: RiffChunk) -> int:
    return RIFF_CHUNK_HEADER_SIZE + len(chunk.payload) + (len(chunk.payload) & 1)


def ascii_chunk_id(chunk_id: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else f"\\x{byte:02x}" for byte in chunk_id)


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return [value for value in values]


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for reference in references:
        key = reference
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return tuple(unique)


def unique_gates(gates: tuple[WebpOutputEmissionGate, ...]) -> tuple[WebpOutputEmissionGate, ...]:
    seen: set[WebpEmissionGateCode] = set()
    unique: list[WebpOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
