"""Source-backed, non-mutating AIFF chunk transaction plans.

The planner mirrors ExifTool's AIFF read responsibilities without mutating
files. It validates FORM/AIFF/AIFC headers, walks big-endian IFF chunks with
odd-byte padding, routes ExifTool-modeled metadata chunks, preserves media and
unknown chunks, and keeps byte emission behind explicit gates.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

AIFF_FORM_HEADER_SIZE = 12
AIFF_CHUNK_HEADER_SIZE = 8
AIFF_FORM_SIGNATURE = b"FORM"
AIFF_FILE_TYPES = frozenset((b"AIFF", b"AIFC"))
AIFF_MAX_FORM_SIZE = 0xFFFFFFFF

NAME_CHUNK_ID = b"NAME"
AUTHOR_CHUNK_ID = b"AUTH"
ANNOTATION_CHUNK_ID = b"ANNO"
COPYRIGHT_CHUNK_ID = b"(c) "
ID3_CHUNK_ID = b"ID3 "
SOUND_DATA_CHUNK_ID = b"SSND"
APPLICATION_DATA_CHUNK_ID = b"APPL"

AIFF_METADATA_CHUNK_IDS = frozenset(
    (NAME_CHUNK_ID, AUTHOR_CHUNK_ID, ANNOTATION_CHUNK_ID, COPYRIGHT_CHUNK_ID)
)
AIFF_KNOWN_SUBDIRECTORY_CHUNK_IDS = frozenset((b"FVER", b"COMM", b"COMT", ID3_CHUNK_ID))

type AiffPlanStatus = Literal["planned", "unsupported"]
type AiffFileType = Literal["AIFF", "AIFC"]
type AiffMetadataKind = Literal[
    "name",
    "author",
    "annotation",
    "copyright",
    "id3",
    "media",
    "application_data",
    "known_subdirectory",
    "unknown",
]
type AiffChunkActionKind = Literal[
    "copy",
    "preserve_media",
    "preserve_unknown",
    "delete_metadata",
    "replace_metadata",
    "insert_metadata",
    "replace_id3",
    "insert_id3",
    "update_form_size",
]
type AiffEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_form_header",
    "unsupported_form_signature",
    "unsupported_form_type",
    "truncated_aiff_chunk_header",
    "truncated_aiff_chunk_payload",
    "missing_odd_chunk_padding",
    "planned_form_size_exceeds_uint32",
]
type AiffTerminalKind = Literal[
    "format_version_time",
    "num_channels",
    "num_sample_frames",
    "sample_size",
    "sample_rate",
    "compression_type",
    "compressor_name",
    "comment_time",
    "marker_id",
    "comment",
]
type AiffTerminalStatus = Literal["parsed", "malformed", "unsupported"]

AIFF_PM_SOURCE_PATH = "lib/Image/ExifTool/AIFF.pm"

AIFF_HEADER_SOURCE = "aiff.header"
AIFF_MAIN_TABLE_SOURCE = "aiff.main_table"
AIFF_TEXT_METADATA_SOURCE = "aiff.text_metadata"
AIFF_ID3_SOURCE = "aiff.id3"
AIFF_MEDIA_PRESERVATION_SOURCE = "aiff.media_preservation"
AIFF_CHUNK_ENUMERATION_SOURCE = "aiff.chunk_enumeration"
AIFF_PAYLOAD_HANDLING_SOURCE = "aiff.payload_handling"
AIFF_UNKNOWN_CHUNK_SOURCE = "aiff.unknown_chunk"
AIFF_FORM_SIZE_SOURCE = "aiff.form_size"
AIFF_COMMON_SOURCE = "aiff.common"
AIFF_FORMAT_VERSION_SOURCE = "aiff.format_version"
AIFF_COMMENT_SOURCE = "aiff.comment"
AIFF_NON_MUTATING_SOURCE = "aiff.non_mutating"

AIFF_TRANSACTION_SOURCES = (
    AIFF_HEADER_SOURCE,
    AIFF_MAIN_TABLE_SOURCE,
    AIFF_TEXT_METADATA_SOURCE,
    AIFF_ID3_SOURCE,
    AIFF_MEDIA_PRESERVATION_SOURCE,
    AIFF_CHUNK_ENUMERATION_SOURCE,
    AIFF_PAYLOAD_HANDLING_SOURCE,
    AIFF_UNKNOWN_CHUNK_SOURCE,
    AIFF_FORM_SIZE_SOURCE,
    AIFF_COMMON_SOURCE,
    AIFF_FORMAT_VERSION_SOURCE,
    AIFF_COMMENT_SOURCE,
    AIFF_NON_MUTATING_SOURCE,
)

AIFF_COMPRESSION_TYPES: dict[str, str] = {
    "NONE": "None",
    "ACE2": "ACE 2-to-1",
    "ACE8": "ACE 8-to-3",
    "MAC3": "MAC 3-to-1",
    "MAC6": "MAC 6-to-1",
    "sowt": "Little-endian, no compression",
    "alaw": "a-law",
    "ALAW": "A-law",
    "ulaw": "mu-law",
    "ULAW": "Mu-law",
    "GSM ": "GSM",
    "G722": "G722",
    "G726": "G726",
    "G728": "G728",
}

AIFF_1904_TO_UNIX_SECONDS = (66 * 365 + 17) * 24 * 3600


@dataclass(frozen=True)
class AiffMetadataChunkRequest:
    chunk_id: bytes
    payload: bytes


@dataclass(frozen=True)
class AiffOutputChunk:
    chunk_id: bytes
    payload: bytes
    padding_byte: bytes = b"\x00"

    @property
    def padding_length(self) -> int:
        return len(self.payload) & 1

    @property
    def encoded_length(self) -> int:
        return AIFF_CHUNK_HEADER_SIZE + len(self.payload) + self.padding_length


@dataclass(frozen=True)
class AiffFormHeaderPlan:
    signature: bytes
    declared_size: int | None
    form_type: bytes
    file_type: AiffFileType | None
    actual_file_size: int
    declared_file_size: int | None
    declared_size_matches_file: bool
    is_supported_aiff: bool
    reason: AiffEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "actual_file_size": self.actual_file_size,
            "declared_file_size": self.declared_file_size,
            "declared_size": self.declared_size,
            "declared_size_matches_file": self.declared_size_matches_file,
            "file_type": self.file_type,
            "form_type": ascii_chunk_id(self.form_type),
            "is_supported_aiff": self.is_supported_aiff,
            "reason": self.reason,
            "signature": ascii_chunk_id(self.signature),
        }


@dataclass(frozen=True)
class AiffChunkPlan:
    index: int
    chunk_id: bytes
    chunk_start_offset: int
    payload_offset: int
    payload_length: int
    payload_end_offset: int
    padding_length: int
    padding_byte: bytes
    padded_end_offset: int
    payload: bytes
    evidence_ids: tuple[str, ...]

    @property
    def encoded_length(self) -> int:
        return AIFF_CHUNK_HEADER_SIZE + self.payload_length + self.padding_length

    def to_output_chunk(self) -> AiffOutputChunk:
        return AiffOutputChunk(self.chunk_id, self.payload, self.padding_byte or b"\x00")

    def to_json(self) -> JsonObject:
        return {
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "chunk_start_offset": self.chunk_start_offset,
            "encoded_length": self.encoded_length,
            "index": self.index,
            "padded_end_offset": self.padded_end_offset,
            "padding_byte": self.padding_byte.hex(),
            "padding_length": self.padding_length,
            "payload_end_offset": self.payload_end_offset,
            "payload_length": self.payload_length,
            "payload_offset": self.payload_offset,
        }


@dataclass(frozen=True)
class AiffMetadataRoutePlan:
    chunk_id: bytes
    chunk_index: int | None
    metadata_kind: AiffMetadataKind
    tag_name: str | None
    payload_length: int | None
    routed_payload: bytes | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "chunk_index": self.chunk_index,
            "metadata_kind": self.metadata_kind,
            "payload_length": self.payload_length,
            "reason": self.reason,
            "routed_payload_hex": (
                self.routed_payload.hex() if self.routed_payload is not None else None
            ),
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class AiffTerminalTagPlan:
    chunk_id: bytes
    chunk_index: int
    kind: AiffTerminalKind
    tag_name: str
    status: AiffTerminalStatus
    raw_value: int | float | str | None
    rendered_value: int | float | str | None
    byte_offset: int | None
    byte_length: int | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_length": self.byte_length,
            "byte_offset": self.byte_offset,
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "chunk_index": self.chunk_index,
            "kind": self.kind,
            "raw_value": self.raw_value,
            "reason": self.reason,
            "rendered_value": self.rendered_value,
            "status": self.status,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class AiffChunkActionPlan:
    kind: AiffChunkActionKind
    chunk_id: bytes
    source_index: int | None
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
            "original_payload_length": self.original_payload_length,
            "output_index": self.output_index,
            "output_payload_length": self.output_payload_length,
            "padding_length": self.padding_length,
            "reason": self.reason,
            "source_index": self.source_index,
        }


@dataclass(frozen=True)
class AiffFormSizeUpdatePlan:
    original_declared_size: int | None
    planned_declared_size: int | None
    planned_file_size: int | None
    size_field_changes: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "original_declared_size": self.original_declared_size,
            "planned_declared_size": self.planned_declared_size,
            "planned_file_size": self.planned_file_size,
            "size_field_changes": self.size_field_changes,
        }


@dataclass(frozen=True)
class AiffOutputEmissionGate:
    code: AiffEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AiffChunkTransactionPlan:
    status: AiffPlanStatus
    header: AiffFormHeaderPlan
    chunks: tuple[AiffChunkPlan, ...]
    metadata_routes: tuple[AiffMetadataRoutePlan, ...]
    terminal_tags: tuple[AiffTerminalTagPlan, ...]
    actions: tuple[AiffChunkActionPlan, ...]
    output_chunks: tuple[AiffOutputChunk, ...]
    form_size_update: AiffFormSizeUpdatePlan
    output_emission_gates: tuple[AiffOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"AIFF chunk transaction output is gated: {gate_codes}")
        if self.header.file_type is None:
            raise ValueError("AIFF chunk transaction output is gated: unsupported_form_type")
        return encode_aiff_chunks(self.header.file_type.encode("ascii"), self.output_chunks)

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "chunks": json_object_array(chunk.to_json() for chunk in self.chunks),
            "form_size_update": self.form_size_update.to_json(),
            "header": self.header.to_json(),
            "metadata_routes": json_object_array(route.to_json() for route in self.metadata_routes),
            "terminal_tags": json_object_array(tag.to_json() for tag in self.terminal_tags),
            "output_chunk_ids": [ascii_chunk_id(chunk.chunk_id) for chunk in self.output_chunks],
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "status": self.status,
        }


def build_aiff_chunk_transaction_plan(
    aiff_data: bytes,
    *,
    metadata_chunks: Iterable[AiffMetadataChunkRequest] = (),
    id3_payload: bytes | None = None,
    delete_all_metadata: bool = False,
    allow_output_emission: bool = False,
) -> AiffChunkTransactionPlan:
    header = build_aiff_form_header_plan(aiff_data)
    gates: list[AiffOutputEmissionGate] = []
    if header.reason is not None:
        gates.append(
            AiffOutputEmissionGate(
                header.reason,
                "FORM/AIFF header is not writable.",
                header.evidence_ids,
            )
        )
        return unsupported_plan(header, gates)

    chunks, chunk_gates = enumerate_aiff_chunks(aiff_data)
    gates.extend(chunk_gates)
    if chunk_gates:
        return unsupported_plan(header, gates, chunks=chunks)

    requests = tuple(metadata_chunks)
    output_chunks, actions = plan_aiff_chunk_actions(
        chunks,
        metadata_chunks=requests,
        id3_payload=id3_payload,
        delete_all_metadata=delete_all_metadata,
    )
    planned_declared_size = planned_form_declared_size(output_chunks)
    form_size_update = AiffFormSizeUpdatePlan(
        original_declared_size=header.declared_size,
        planned_declared_size=(
            planned_declared_size if planned_declared_size <= AIFF_MAX_FORM_SIZE else None
        ),
        planned_file_size=(
            planned_declared_size + 8 if planned_declared_size <= AIFF_MAX_FORM_SIZE else None
        ),
        size_field_changes=header.declared_size != planned_declared_size,
        evidence_ids=(AIFF_FORM_SIZE_SOURCE,),
    )
    actions = (
        *actions,
        AiffChunkActionPlan(
            kind="update_form_size",
            chunk_id=AIFF_FORM_SIGNATURE,
            source_index=None,
            output_index=None,
            original_payload_length=header.declared_size,
            output_payload_length=form_size_update.planned_declared_size,
            padding_length=0,
            reason="Update the FORM size field from planned output chunk bytes.",
            evidence_ids=(AIFF_FORM_SIZE_SOURCE,),
        ),
    )
    if planned_declared_size > AIFF_MAX_FORM_SIZE:
        gates.append(
            AiffOutputEmissionGate(
                "planned_form_size_exceeds_uint32",
                "The planned FORM size does not fit in the AIFF uint32 size field.",
                (AIFF_FORM_SIZE_SOURCE,),
            )
        )
    if not allow_output_emission:
        gates.append(
            AiffOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "Chunk transaction plans are non-mutating unless emission is explicitly allowed.",
                (AIFF_NON_MUTATING_SOURCE,),
            )
        )

    routes = tuple(_route_existing_chunk(chunk) for chunk in chunks)
    terminal_tags = tuple(tag for chunk in chunks for tag in _terminal_tags_for_chunk(chunk))
    sources = unique_evidence_ids(
        (
            *AIFF_TRANSACTION_SOURCES,
            *(source for action in actions for source in action.evidence_ids),
            *(source for route in routes for source in route.evidence_ids),
            *(source for tag in terminal_tags for source in tag.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return AiffChunkTransactionPlan(
        status="planned",
        header=header,
        chunks=chunks,
        metadata_routes=routes,
        terminal_tags=terminal_tags,
        actions=actions,
        output_chunks=output_chunks,
        form_size_update=form_size_update,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
    )


plan_aiff_chunk_transaction = build_aiff_chunk_transaction_plan


def build_aiff_form_header_plan(aiff_data: bytes) -> AiffFormHeaderPlan:
    signature = aiff_data[:4]
    declared_size = (
        int.from_bytes(aiff_data[4:8], "big") if len(aiff_data) >= AIFF_FORM_HEADER_SIZE else None
    )
    form_type = aiff_data[8:12] if len(aiff_data) >= AIFF_FORM_HEADER_SIZE else b""
    declared_file_size = declared_size + 8 if declared_size is not None else None
    reason: AiffEmissionGateCode | None = None
    file_type: AiffFileType | None = None
    if len(aiff_data) < AIFF_FORM_HEADER_SIZE:
        reason = "truncated_form_header"
    elif signature != AIFF_FORM_SIGNATURE:
        reason = "unsupported_form_signature"
    elif form_type not in AIFF_FILE_TYPES:
        reason = "unsupported_form_type"
    elif form_type == b"AIFF":
        file_type = "AIFF"
    else:
        file_type = "AIFC"
    return AiffFormHeaderPlan(
        signature=signature,
        declared_size=declared_size,
        form_type=form_type,
        file_type=file_type,
        actual_file_size=len(aiff_data),
        declared_file_size=declared_file_size,
        declared_size_matches_file=declared_file_size == len(aiff_data),
        is_supported_aiff=reason is None,
        reason=reason,
        evidence_ids=(AIFF_HEADER_SOURCE,),
    )


def enumerate_aiff_chunks(
    aiff_data: bytes,
) -> tuple[tuple[AiffChunkPlan, ...], tuple[AiffOutputEmissionGate, ...]]:
    chunks: list[AiffChunkPlan] = []
    gates: list[AiffOutputEmissionGate] = []
    offset = AIFF_FORM_HEADER_SIZE
    while offset < len(aiff_data):
        if len(aiff_data) - offset < AIFF_CHUNK_HEADER_SIZE:
            gates.append(
                AiffOutputEmissionGate(
                    "truncated_aiff_chunk_header",
                    "Input ended before a complete AIFF chunk header could be read.",
                    (AIFF_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            break
        chunk_start = offset
        chunk_id = aiff_data[offset : offset + 4]
        payload_length = int.from_bytes(aiff_data[offset + 4 : offset + 8], "big")
        payload_offset = offset + AIFF_CHUNK_HEADER_SIZE
        payload_end = payload_offset + payload_length
        padding_length = payload_length & 1
        padded_end = payload_end + padding_length
        if payload_end > len(aiff_data):
            gates.append(
                AiffOutputEmissionGate(
                    "truncated_aiff_chunk_payload",
                    f"Chunk {ascii_chunk_id(chunk_id)} declares {payload_length} payload bytes.",
                    (AIFF_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            break
        if padded_end > len(aiff_data):
            gates.append(
                AiffOutputEmissionGate(
                    "missing_odd_chunk_padding",
                    f"Odd-sized chunk {ascii_chunk_id(chunk_id)} has no padding byte.",
                    (AIFF_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            break
        chunks.append(
            AiffChunkPlan(
                index=len(chunks),
                chunk_id=chunk_id,
                chunk_start_offset=chunk_start,
                payload_offset=payload_offset,
                payload_length=payload_length,
                payload_end_offset=payload_end,
                padding_length=padding_length,
                padding_byte=aiff_data[payload_end:padded_end],
                padded_end_offset=padded_end,
                payload=aiff_data[payload_offset:payload_end],
                evidence_ids=(AIFF_CHUNK_ENUMERATION_SOURCE,),
            )
        )
        offset = padded_end
    return tuple(chunks), tuple(gates)


def plan_aiff_chunk_actions(
    chunks: tuple[AiffChunkPlan, ...],
    *,
    metadata_chunks: tuple[AiffMetadataChunkRequest, ...],
    id3_payload: bytes | None,
    delete_all_metadata: bool,
) -> tuple[tuple[AiffOutputChunk, ...], tuple[AiffChunkActionPlan, ...]]:
    actions: list[AiffChunkActionPlan] = []
    output_chunks: list[AiffOutputChunk] = []
    request_by_chunk_id = {request.chunk_id: request.payload for request in metadata_chunks}
    handled_request_ids: set[bytes] = set()
    id3_written = False

    for chunk in chunks:
        route = _route_existing_chunk(chunk)
        if delete_all_metadata and route.metadata_kind in {
            "name",
            "author",
            "annotation",
            "copyright",
            "id3",
        }:
            actions.append(_delete_metadata_action(chunk, route))
            continue
        if route.metadata_kind in {"name", "author", "annotation", "copyright"}:
            replacement = request_by_chunk_id.get(chunk.chunk_id)
            if replacement is not None:
                handled_request_ids.add(chunk.chunk_id)
                _append_output_chunk(
                    output_chunks,
                    actions,
                    AiffOutputChunk(chunk.chunk_id, replacement),
                    "replace_metadata",
                    chunk.index,
                    chunk.payload_length,
                    "Replace an ExifTool-modeled AIFF text metadata chunk.",
                    route.evidence_ids,
                )
                continue
        if chunk.chunk_id == ID3_CHUNK_ID and id3_payload is not None:
            if id3_written:
                actions.append(_delete_metadata_action(chunk, route))
                continue
            _append_output_chunk(
                output_chunks,
                actions,
                AiffOutputChunk(ID3_CHUNK_ID, id3_payload),
                "replace_id3",
                chunk.index,
                chunk.payload_length,
                "Replace the AIFF ID3 subdirectory chunk payload.",
                route.evidence_ids,
            )
            id3_written = True
            continue
        _append_output_chunk(
            output_chunks,
            actions,
            chunk.to_output_chunk(),
            _preserve_action_kind(route.metadata_kind),
            chunk.index,
            chunk.payload_length,
            _preserve_action_reason(route.metadata_kind),
            route.evidence_ids,
        )

    insertion_index = _first_media_output_index(output_chunks)
    for request in metadata_chunks:
        if request.chunk_id in handled_request_ids:
            continue
        output_chunks.insert(insertion_index, AiffOutputChunk(request.chunk_id, request.payload))
        actions.append(
            AiffChunkActionPlan(
                kind="insert_metadata",
                chunk_id=request.chunk_id,
                source_index=None,
                output_index=insertion_index,
                original_payload_length=None,
                output_payload_length=len(request.payload),
                padding_length=len(request.payload) & 1,
                reason="Insert an ExifTool-modeled AIFF text metadata chunk before sound data.",
                evidence_ids=(AIFF_TEXT_METADATA_SOURCE, AIFF_CHUNK_ENUMERATION_SOURCE),
            )
        )
        insertion_index += 1
    if id3_payload is not None and not id3_written and not delete_all_metadata:
        output_chunks.insert(insertion_index, AiffOutputChunk(ID3_CHUNK_ID, id3_payload))
        actions.append(
            AiffChunkActionPlan(
                kind="insert_id3",
                chunk_id=ID3_CHUNK_ID,
                source_index=None,
                output_index=insertion_index,
                original_payload_length=None,
                output_payload_length=len(id3_payload),
                padding_length=len(id3_payload) & 1,
                reason="Insert an AIFF ID3 chunk before sound data.",
                evidence_ids=(AIFF_ID3_SOURCE, AIFF_CHUNK_ENUMERATION_SOURCE),
            )
        )
    return tuple(output_chunks), _with_output_indexes(tuple(actions), tuple(output_chunks))


def encode_aiff_chunks(form_type: bytes, chunks: Iterable[AiffOutputChunk]) -> bytes:
    encoded_chunks = bytearray()
    for chunk in chunks:
        encoded_chunks.extend(chunk.chunk_id)
        encoded_chunks.extend(len(chunk.payload).to_bytes(4, "big"))
        encoded_chunks.extend(chunk.payload)
        if len(chunk.payload) & 1:
            encoded_chunks.extend(chunk.padding_byte[:1] or b"\x00")
    declared_size = 4 + len(encoded_chunks)
    if declared_size > AIFF_MAX_FORM_SIZE:
        raise ValueError("AIFF FORM size exceeds uint32")
    return (
        AIFF_FORM_SIGNATURE + declared_size.to_bytes(4, "big") + form_type + bytes(encoded_chunks)
    )


def planned_form_declared_size(chunks: Iterable[AiffOutputChunk]) -> int:
    return 4 + sum(chunk.encoded_length for chunk in chunks)


def _route_existing_chunk(chunk: AiffChunkPlan) -> AiffMetadataRoutePlan:
    if chunk.chunk_id == NAME_CHUNK_ID:
        return _text_route(chunk, "name", "Name")
    if chunk.chunk_id == AUTHOR_CHUNK_ID:
        return _text_route(chunk, "author", "Author")
    if chunk.chunk_id == ANNOTATION_CHUNK_ID:
        return _text_route(chunk, "annotation", "Annotation")
    if chunk.chunk_id == COPYRIGHT_CHUNK_ID:
        return _text_route(chunk, "copyright", "Copyright")
    if chunk.chunk_id == ID3_CHUNK_ID:
        return AiffMetadataRoutePlan(
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.index,
            metadata_kind="id3",
            tag_name="ID3",
            payload_length=chunk.payload_length,
            routed_payload=chunk.payload,
            reason="Route ID3 chunk to the ID3 subdirectory processor.",
            evidence_ids=(AIFF_ID3_SOURCE, AIFF_CHUNK_ENUMERATION_SOURCE),
        )
    if chunk.chunk_id == SOUND_DATA_CHUNK_ID:
        return AiffMetadataRoutePlan(
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.index,
            metadata_kind="media",
            tag_name=None,
            payload_length=chunk.payload_length,
            routed_payload=None,
            reason="Preserve sound data as media, not AIFF metadata.",
            evidence_ids=(AIFF_MEDIA_PRESERVATION_SOURCE, AIFF_UNKNOWN_CHUNK_SOURCE),
        )
    if chunk.chunk_id == APPLICATION_DATA_CHUNK_ID:
        return AiffMetadataRoutePlan(
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.index,
            metadata_kind="application_data",
            tag_name="ApplicationData",
            payload_length=chunk.payload_length,
            routed_payload=chunk.payload,
            reason="Route APPL through ExifTool's application data tag.",
            evidence_ids=(AIFF_MAIN_TABLE_SOURCE, AIFF_CHUNK_ENUMERATION_SOURCE),
        )
    if chunk.chunk_id in AIFF_KNOWN_SUBDIRECTORY_CHUNK_IDS:
        return AiffMetadataRoutePlan(
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.index,
            metadata_kind="known_subdirectory",
            tag_name=ascii_chunk_id(chunk.chunk_id),
            payload_length=chunk.payload_length,
            routed_payload=chunk.payload,
            reason="Preserve known AIFF subdirectory payload for its specialized parser.",
            evidence_ids=(AIFF_MAIN_TABLE_SOURCE, AIFF_PAYLOAD_HANDLING_SOURCE),
        )
    return AiffMetadataRoutePlan(
        chunk_id=chunk.chunk_id,
        chunk_index=chunk.index,
        metadata_kind="unknown",
        tag_name=None,
        payload_length=chunk.payload_length,
        routed_payload=None,
        reason="Preserve unknown AIFF chunk bytes.",
        evidence_ids=(AIFF_UNKNOWN_CHUNK_SOURCE, AIFF_CHUNK_ENUMERATION_SOURCE),
    )


def _text_route(
    chunk: AiffChunkPlan, metadata_kind: AiffMetadataKind, tag_name: str
) -> AiffMetadataRoutePlan:
    return AiffMetadataRoutePlan(
        chunk_id=chunk.chunk_id,
        chunk_index=chunk.index,
        metadata_kind=metadata_kind,
        tag_name=tag_name,
        payload_length=chunk.payload_length,
        routed_payload=chunk.payload.rstrip(b"\x00"),
        reason="Route AIFF text metadata and trim trailing NUL bytes like ExifTool.",
        evidence_ids=(
            AIFF_TEXT_METADATA_SOURCE,
            AIFF_PAYLOAD_HANDLING_SOURCE,
            AIFF_CHUNK_ENUMERATION_SOURCE,
        ),
    )


def _terminal_tags_for_chunk(chunk: AiffChunkPlan) -> tuple[AiffTerminalTagPlan, ...]:
    if chunk.chunk_id == b"FVER":
        return _format_version_tags(chunk)
    if chunk.chunk_id == b"COMM":
        return _common_tags(chunk)
    if chunk.chunk_id == b"COMT":
        return _comment_tags(chunk)
    return ()


def terminal_tags_for_aiff_chunk(chunk: AiffChunkPlan) -> tuple[AiffTerminalTagPlan, ...]:
    """Return ExifTool-modeled terminal tags for a bounded AIFF chunk payload."""

    return _terminal_tags_for_chunk(chunk)


def _format_version_tags(chunk: AiffChunkPlan) -> tuple[AiffTerminalTagPlan, ...]:
    if chunk.payload_length < 4:
        return (
            _malformed_terminal(
                chunk,
                "format_version_time",
                "FormatVersionTime",
                "FVER payload ended before the uint32 FormatVersionTime field.",
                AIFF_FORMAT_VERSION_SOURCE,
            ),
        )
    raw = int.from_bytes(chunk.payload[:4], "big")
    return (
        AiffTerminalTagPlan(
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.index,
            kind="format_version_time",
            tag_name="FormatVersionTime",
            status="parsed",
            raw_value=raw,
            rendered_value=raw - AIFF_1904_TO_UNIX_SECONDS,
            byte_offset=chunk.payload_offset,
            byte_length=4,
            reason="Parsed FormatVersionTime from the FVER uint32 field.",
            evidence_ids=(AIFF_FORMAT_VERSION_SOURCE,),
        ),
    )


def _common_tags(chunk: AiffChunkPlan) -> tuple[AiffTerminalTagPlan, ...]:
    if chunk.payload_length < 18:
        return (
            _malformed_terminal(
                chunk,
                "num_channels",
                "Common",
                "COMM payload ended before the required AIFF Common scalar fields.",
                AIFF_COMMON_SOURCE,
            ),
        )
    payload = chunk.payload
    tags = [
        _parsed_terminal(
            chunk,
            "num_channels",
            "NumChannels",
            int.from_bytes(payload[0:2], "big"),
            0,
            2,
            AIFF_COMMON_SOURCE,
        ),
        _parsed_terminal(
            chunk,
            "num_sample_frames",
            "NumSampleFrames",
            int.from_bytes(payload[2:6], "big"),
            2,
            4,
            AIFF_COMMON_SOURCE,
        ),
        _parsed_terminal(
            chunk,
            "sample_size",
            "SampleSize",
            int.from_bytes(payload[6:8], "big"),
            6,
            2,
            AIFF_COMMON_SOURCE,
        ),
        _parsed_terminal(
            chunk,
            "sample_rate",
            "SampleRate",
            _decode_aiff_extended(payload[8:18]),
            8,
            10,
            AIFF_COMMON_SOURCE,
        ),
    ]
    if chunk.payload_length >= 22:
        compression = payload[18:22].decode("latin-1")
        tags.append(
            _parsed_terminal(
                chunk,
                "compression_type",
                "CompressionType",
                compression,
                18,
                4,
                AIFF_COMMON_SOURCE,
                rendered_value=AIFF_COMPRESSION_TYPES.get(compression, compression),
            )
        )
    if chunk.payload_length >= 23:
        name_length = payload[22]
        available = max(0, chunk.payload_length - 23)
        if name_length <= available:
            name = payload[23 : 23 + name_length].decode("mac_roman")
            tags.append(
                _parsed_terminal(
                    chunk,
                    "compressor_name",
                    "CompressorName",
                    name,
                    22,
                    1 + name_length,
                    AIFF_COMMON_SOURCE,
                )
            )
        else:
            tags.append(
                _malformed_terminal(
                    chunk,
                    "compressor_name",
                    "CompressorName",
                    "COMM compressor Pascal string extends beyond the chunk payload.",
                    AIFF_COMMON_SOURCE,
                )
            )
    return tuple(tags)


def _comment_tags(chunk: AiffChunkPlan) -> tuple[AiffTerminalTagPlan, ...]:
    if chunk.payload_length < 2:
        return (
            _malformed_terminal(
                chunk,
                "comment",
                "Comment",
                "COMT payload ended before the uint16 comment count.",
                AIFF_COMMENT_SOURCE,
            ),
        )
    count = int.from_bytes(chunk.payload[:2], "big")
    pos = 2
    tags: list[AiffTerminalTagPlan] = []
    for _index in range(count):
        if pos + 8 > chunk.payload_length:
            tags.append(
                _malformed_terminal(
                    chunk,
                    "comment",
                    "Comment",
                    "COMT payload ended before a complete comment record header.",
                    AIFF_COMMENT_SOURCE,
                )
            )
            return tuple(tags)
        comment_time = int.from_bytes(chunk.payload[pos : pos + 4], "big")
        marker_id = int.from_bytes(chunk.payload[pos + 4 : pos + 6], "big")
        size = int.from_bytes(chunk.payload[pos + 6 : pos + 8], "big")
        record_data_offset = pos + 8
        if record_data_offset + size > chunk.payload_length:
            tags.append(
                _malformed_terminal(
                    chunk,
                    "comment",
                    "Comment",
                    "COMT comment text extends beyond the chunk payload.",
                    AIFF_COMMENT_SOURCE,
                )
            )
            return tuple(tags)
        tags.append(
            _parsed_terminal(
                chunk,
                "comment_time",
                "CommentTime",
                comment_time,
                pos,
                4,
                AIFF_COMMENT_SOURCE,
                rendered_value=comment_time - AIFF_1904_TO_UNIX_SECONDS,
            )
        )
        if marker_id:
            tags.append(
                _parsed_terminal(
                    chunk,
                    "marker_id",
                    "MarkerID",
                    marker_id,
                    pos + 4,
                    2,
                    AIFF_COMMENT_SOURCE,
                )
            )
        tags.append(
            _parsed_terminal(
                chunk,
                "comment",
                "Comment",
                chunk.payload[record_data_offset : record_data_offset + size].decode("mac_roman"),
                record_data_offset,
                size,
                AIFF_COMMENT_SOURCE,
            )
        )
        pos = record_data_offset + size + (size & 1)
    return tuple(tags)


def _parsed_terminal(
    chunk: AiffChunkPlan,
    kind: AiffTerminalKind,
    tag_name: str,
    raw_value: int | float | str,
    relative_offset: int,
    byte_length: int,
    source: str,
    *,
    rendered_value: int | float | str | None = None,
) -> AiffTerminalTagPlan:
    return AiffTerminalTagPlan(
        chunk_id=chunk.chunk_id,
        chunk_index=chunk.index,
        kind=kind,
        tag_name=tag_name,
        status="parsed",
        raw_value=raw_value,
        rendered_value=raw_value if rendered_value is None else rendered_value,
        byte_offset=chunk.payload_offset + relative_offset,
        byte_length=byte_length,
        reason=f"Parsed {tag_name} from the source-defined AIFF subdirectory field.",
        evidence_ids=(source,),
    )


def _malformed_terminal(
    chunk: AiffChunkPlan,
    kind: AiffTerminalKind,
    tag_name: str,
    reason: str,
    source: str,
) -> AiffTerminalTagPlan:
    return AiffTerminalTagPlan(
        chunk_id=chunk.chunk_id,
        chunk_index=chunk.index,
        kind=kind,
        tag_name=tag_name,
        status="malformed",
        raw_value=None,
        rendered_value=None,
        byte_offset=None,
        byte_length=None,
        reason=reason,
        evidence_ids=(source,),
    )


def _decode_aiff_extended(raw: bytes) -> float:
    exponent = int.from_bytes(raw[0:2], "big")
    sign = -1 if exponent & 0x8000 else 1
    exponent &= 0x7FFF
    mantissa = int.from_bytes(raw[2:10], "big")
    if exponent == 0 and mantissa == 0:
        return 0.0
    return sign * mantissa * (2.0 ** (exponent - 16383 - 63))


def _append_output_chunk(
    output_chunks: list[AiffOutputChunk],
    actions: list[AiffChunkActionPlan],
    output_chunk: AiffOutputChunk,
    kind: AiffChunkActionKind,
    source_index: int | None,
    original_payload_length: int | None,
    reason: str,
    evidence_ids: tuple[str, ...],
) -> None:
    output_index = len(output_chunks)
    output_chunks.append(output_chunk)
    actions.append(
        AiffChunkActionPlan(
            kind=kind,
            chunk_id=output_chunk.chunk_id,
            source_index=source_index,
            output_index=output_index,
            original_payload_length=original_payload_length,
            output_payload_length=len(output_chunk.payload),
            padding_length=output_chunk.padding_length,
            reason=reason,
            evidence_ids=evidence_ids,
        )
    )


def _delete_metadata_action(
    chunk: AiffChunkPlan, route: AiffMetadataRoutePlan
) -> AiffChunkActionPlan:
    return AiffChunkActionPlan(
        kind="delete_metadata",
        chunk_id=chunk.chunk_id,
        source_index=chunk.index,
        output_index=None,
        original_payload_length=chunk.payload_length,
        output_payload_length=None,
        padding_length=0,
        reason="Delete AIFF metadata chunk for all-metadata removal or duplicate suppression.",
        evidence_ids=route.evidence_ids,
    )


def _preserve_action_kind(metadata_kind: AiffMetadataKind) -> AiffChunkActionKind:
    if metadata_kind == "media":
        return "preserve_media"
    if metadata_kind == "unknown":
        return "preserve_unknown"
    return "copy"


def _preserve_action_reason(metadata_kind: AiffMetadataKind) -> str:
    if metadata_kind == "media":
        return "Preserve AIFF sound/media chunk unchanged."
    if metadata_kind == "unknown":
        return "Preserve unknown AIFF chunk unchanged."
    return "Copy AIFF chunk unchanged."


def _first_media_output_index(
    output_chunks: tuple[AiffOutputChunk, ...] | list[AiffOutputChunk],
) -> int:
    for index, chunk in enumerate(output_chunks):
        if chunk.chunk_id == SOUND_DATA_CHUNK_ID:
            return index
    return len(output_chunks)


def _with_output_indexes(
    actions: tuple[AiffChunkActionPlan, ...],
    output_chunks: tuple[AiffOutputChunk, ...],
) -> tuple[AiffChunkActionPlan, ...]:
    remaining_indexes_by_type: dict[bytes, list[int]] = {}
    for index, chunk in enumerate(output_chunks):
        remaining_indexes_by_type.setdefault(chunk.chunk_id, []).append(index)
    updated: list[AiffChunkActionPlan] = []
    for action in actions:
        output_index = action.output_index
        if action.kind in {
            "copy",
            "preserve_media",
            "preserve_unknown",
            "replace_metadata",
            "insert_metadata",
            "replace_id3",
            "insert_id3",
        }:
            indexes = remaining_indexes_by_type.get(action.chunk_id) or []
            output_index = indexes.pop(0) if indexes else None
        updated.append(
            AiffChunkActionPlan(
                kind=action.kind,
                chunk_id=action.chunk_id,
                source_index=action.source_index,
                output_index=output_index,
                original_payload_length=action.original_payload_length,
                output_payload_length=action.output_payload_length,
                padding_length=action.padding_length,
                reason=action.reason,
                evidence_ids=action.evidence_ids,
            )
        )
    return tuple(updated)


def unsupported_plan(
    header: AiffFormHeaderPlan,
    gates: list[AiffOutputEmissionGate],
    *,
    chunks: tuple[AiffChunkPlan, ...] = (),
) -> AiffChunkTransactionPlan:
    sources = unique_evidence_ids(
        (
            AIFF_HEADER_SOURCE,
            AIFF_CHUNK_ENUMERATION_SOURCE,
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return AiffChunkTransactionPlan(
        status="unsupported",
        header=header,
        chunks=chunks,
        metadata_routes=(),
        terminal_tags=(),
        actions=(),
        output_chunks=(),
        form_size_update=AiffFormSizeUpdatePlan(
            original_declared_size=header.declared_size,
            planned_declared_size=None,
            planned_file_size=None,
            size_field_changes=False,
            evidence_ids=(AIFF_FORM_SIZE_SOURCE,),
        ),
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
    )


def ascii_chunk_id(chunk_id: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else f"\\x{byte:02x}" for byte in chunk_id)


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return [value for value in values]


def unique_evidence_ids(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def unique_gates(gates: tuple[AiffOutputEmissionGate, ...]) -> tuple[AiffOutputEmissionGate, ...]:
    seen: set[AiffEmissionGateCode] = set()
    unique: list[AiffOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
