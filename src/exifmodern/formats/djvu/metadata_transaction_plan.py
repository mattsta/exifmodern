"""Source-backed, non-mutating DjVu metadata transaction plans.

The planner mirrors the DjVu extraction responsibilities in ExifTool's
``DjVu.pm`` and the delegated IFF chunk walk in ``AIFF.pm``. It validates the
AT&T FORM header, enumerates chunks, routes DjVu metadata surfaces, preserves
image/page bytes, and keeps byte emission behind explicit gates.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonValue

DJVU_PREFIX = b"AT&T"
DJVU_FORM_SIGNATURE = b"FORM"
DJVU_HEADER_SIZE = 16
DJVU_CHUNK_HEADER_SIZE = 8
DJVU_FILE_TYPES = frozenset((b"DJVU", b"DJVM"))
DJVU_MAX_FORM_SIZE = 0xFFFFFFFF

INFO_CHUNK_ID = b"INFO"
FORM_CHUNK_ID = b"FORM"
ANTA_CHUNK_ID = b"ANTa"
ANTZ_CHUNK_ID = b"ANTz"
INCL_CHUNK_ID = b"INCL"
TXTZ_CHUNK_ID = b"TXTz"
IMAGE_PAYLOAD_CHUNK_IDS = frozenset(
    (
        b"Sjbz",
        b"BG44",
        b"FG44",
        b"BGjp",
        b"FGjp",
        b"FGbz",
        b"Djbz",
        b"CIDa",
        b"NDir",
        b"Dirm",
        b"NAVI",
    )
)
DJVU_MAIN_MODELED_CHUNK_IDS = frozenset(
    (INFO_CHUNK_ID, FORM_CHUNK_ID, ANTA_CHUNK_ID, ANTZ_CHUNK_ID, INCL_CHUNK_ID)
)
DJVU_FORM_TYPES = {
    b"DJVU": "Single-page image",
    b"DJVM": "Multi-page document",
    b"PM44": "Color IW44",
    b"BM44": "Grayscale IW44",
    b"DJVI": "Shared component",
    b"THUM": "Thumbnail image",
}
DJVU_STANDARD_META_TAGS = frozenset(
    (
        "address",
        "annote",
        "author",
        "booktitle",
        "chapter",
        "crossref",
        "edition",
        "eprint",
        "howpublished",
        "institution",
        "journal",
        "key",
        "month",
        "note",
        "number",
        "organization",
        "pages",
        "publisher",
        "school",
        "series",
        "title",
        "type",
        "url",
        "volume",
        "year",
        "Title",
        "Author",
        "Subject",
        "Keywords",
        "Creator",
        "Producer",
        "CreationDate",
        "ModDate",
        "Trapped",
    )
)

type DjvuPlanStatus = Literal["planned", "unsupported"]
type DjvuFileType = Literal["DJVU", "DJVM"]
type DjvuMetadataKind = Literal[
    "info",
    "form",
    "annotation",
    "compressed_annotation",
    "included_file",
    "compressed_text",
    "image_or_page_payload",
    "unknown",
]
type DjvuChunkActionKind = Literal[
    "copy",
    "preserve_metadata",
    "preserve_compressed_metadata",
    "preserve_included_file",
    "preserve_compressed_text",
    "preserve_image_payload",
    "preserve_unknown",
    "update_form_size",
]
type DjvuEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_djvu_header",
    "unsupported_djvu_prefix",
    "unsupported_form_signature",
    "unsupported_djvu_form_type",
    "declared_form_size_mismatch",
    "truncated_djvu_chunk_header",
    "truncated_djvu_chunk_payload",
    "missing_odd_chunk_padding",
    "metadata_rewrite_not_supported_by_oracle",
    "compressed_metadata_requires_bzz_decode",
    "compressed_text_rewrite_not_planned",
    "planned_form_size_exceeds_uint32",
]
type DjvuAnnotationNode = str | tuple[DjvuAnnotationNode, ...]

DJVU_AIFF_DELEGATION_EVIDENCE_ID = "djvu.aiff_delegation"
DJVU_AIFF_DELEGATION_SOURCE = DJVU_AIFF_DELEGATION_EVIDENCE_ID
DJVU_HEADER_EVIDENCE_ID = "djvu.header"
DJVU_HEADER_SOURCE = DJVU_HEADER_EVIDENCE_ID
DJVU_CHUNK_ENUMERATION_EVIDENCE_ID = "djvu.chunk_enumeration"
DJVU_CHUNK_ENUMERATION_SOURCE = DJVU_CHUNK_ENUMERATION_EVIDENCE_ID
DJVU_CHUNK_PAYLOAD_EVIDENCE_ID = "djvu.chunk_payload"
DJVU_CHUNK_PAYLOAD_SOURCE = DJVU_CHUNK_PAYLOAD_EVIDENCE_ID
DJVU_UNKNOWN_SKIP_EVIDENCE_ID = "djvu.unknown_skip"
DJVU_UNKNOWN_SKIP_SOURCE = DJVU_UNKNOWN_SKIP_EVIDENCE_ID
DJVU_MAIN_TABLE_EVIDENCE_ID = "djvu.main_table"
DJVU_MAIN_TABLE_SOURCE = DJVU_MAIN_TABLE_EVIDENCE_ID
DJVU_INFO_EVIDENCE_ID = "djvu.info"
DJVU_INFO_SOURCE = DJVU_INFO_EVIDENCE_ID
DJVU_FORM_EVIDENCE_ID = "djvu.form"
DJVU_FORM_SOURCE = DJVU_FORM_EVIDENCE_ID
DJVU_ANNOTATION_EVIDENCE_ID = "djvu.annotation"
DJVU_ANNOTATION_SOURCE = DJVU_ANNOTATION_EVIDENCE_ID
DJVU_METADATA_EVIDENCE_ID = "djvu.metadata"
DJVU_METADATA_SOURCE = DJVU_METADATA_EVIDENCE_ID
DJVU_PARSE_ANT_EVIDENCE_ID = "djvu.parse_ant"
DJVU_PARSE_ANT_SOURCE = DJVU_PARSE_ANT_EVIDENCE_ID
DJVU_PROCESS_ANT_EVIDENCE_ID = "djvu.process_ant"
DJVU_PROCESS_ANT_SOURCE = DJVU_PROCESS_ANT_EVIDENCE_ID
DJVU_PROCESS_META_EVIDENCE_ID = "djvu.process_meta"
DJVU_PROCESS_META_SOURCE = DJVU_PROCESS_META_EVIDENCE_ID
DJVU_BZZ_EVIDENCE_ID = "djvu.bzz"
DJVU_BZZ_SOURCE = DJVU_BZZ_EVIDENCE_ID
DJVU_READ_ONLY_EVIDENCE_ID = "djvu.read_only"
DJVU_READ_ONLY_SOURCE = DJVU_READ_ONLY_EVIDENCE_ID

DJVU_TRANSACTION_EVIDENCE_IDS = (
    DJVU_AIFF_DELEGATION_EVIDENCE_ID,
    DJVU_HEADER_EVIDENCE_ID,
    DJVU_CHUNK_ENUMERATION_EVIDENCE_ID,
    DJVU_CHUNK_PAYLOAD_EVIDENCE_ID,
    DJVU_UNKNOWN_SKIP_EVIDENCE_ID,
    DJVU_MAIN_TABLE_EVIDENCE_ID,
    DJVU_INFO_EVIDENCE_ID,
    DJVU_FORM_EVIDENCE_ID,
    DJVU_ANNOTATION_EVIDENCE_ID,
    DJVU_METADATA_EVIDENCE_ID,
    DJVU_PARSE_ANT_EVIDENCE_ID,
    DJVU_PROCESS_ANT_EVIDENCE_ID,
    DJVU_PROCESS_META_EVIDENCE_ID,
    DJVU_BZZ_EVIDENCE_ID,
    DJVU_READ_ONLY_EVIDENCE_ID,
)


@dataclass(frozen=True)
class DjvuMetadataRequest:
    tag_id: str
    value: str


@dataclass(frozen=True)
class DjvuOutputChunk:
    chunk_id: bytes
    payload: bytes
    padding_byte: bytes = b"\x00"

    @property
    def padding_length(self) -> int:
        return len(self.payload) & 1

    @property
    def encoded_length(self) -> int:
        return DJVU_CHUNK_HEADER_SIZE + len(self.payload) + self.padding_length


@dataclass(frozen=True)
class DjvuFormHeaderPlan:
    prefix: bytes
    form_signature: bytes
    declared_size: int | None
    form_type: bytes
    file_type: DjvuFileType | None
    actual_file_size: int
    declared_file_size: int | None
    declared_size_matches_file: bool
    reason: DjvuEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_supported_djvu(self) -> bool:
        return self.reason is None or self.reason == "declared_form_size_mismatch"

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "actual_file_size": self.actual_file_size,
            "declared_file_size": self.declared_file_size,
            "declared_size": self.declared_size,
            "declared_size_matches_file": self.declared_size_matches_file,
            "file_type": self.file_type,
            "form_signature": ascii_chunk_id(self.form_signature),
            "form_type": ascii_chunk_id(self.form_type),
            "is_supported_djvu": self.is_supported_djvu,
            "prefix": ascii_chunk_id(self.prefix),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DjvuChunkPlan:
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
        return DJVU_CHUNK_HEADER_SIZE + self.payload_length + self.padding_length

    def to_output_chunk(self) -> DjvuOutputChunk:
        return DjvuOutputChunk(self.chunk_id, self.payload, self.padding_byte or b"\x00")

    def to_json(self) -> dict[str, JsonValue]:
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
class DjvuInfoPlan:
    width: int | None
    height: int | None
    version: str | None
    spatial_resolution: int | None
    gamma: float | None
    orientation_code: int | None
    orientation: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "gamma": self.gamma,
            "height": self.height,
            "orientation": self.orientation,
            "orientation_code": self.orientation_code,
            "spatial_resolution": self.spatial_resolution,
            "version": self.version,
            "width": self.width,
        }


@dataclass(frozen=True)
class DjvuMetadataEntryPlan:
    tag_id: str
    value: str | None
    valid_simple_pair: bool
    standard_tag: bool
    dynamic_tag_name: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "dynamic_tag_name": self.dynamic_tag_name,
            "standard_tag": self.standard_tag,
            "tag_id": self.tag_id,
            "valid_simple_pair": self.valid_simple_pair,
            "value": self.value,
        }


@dataclass(frozen=True)
class DjvuAnnotationPlan:
    has_metadata_or_xmp_prescan_hit: bool
    metadata_entries: tuple[DjvuMetadataEntryPlan, ...]
    xmp_payload: str | None
    invalid_entry_count: int
    parsed: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "has_metadata_or_xmp_prescan_hit": self.has_metadata_or_xmp_prescan_hit,
            "invalid_entry_count": self.invalid_entry_count,
            "metadata_entries": json_array(item.to_json() for item in self.metadata_entries),
            "parsed": self.parsed,
            "xmp_payload": self.xmp_payload,
        }


@dataclass(frozen=True)
class DjvuMetadataRoutePlan:
    chunk_id: bytes
    chunk_index: int
    metadata_kind: DjvuMetadataKind
    tag_name: str | None
    info: DjvuInfoPlan | None
    annotation: DjvuAnnotationPlan | None
    subfile_type: str | None
    extraction_blocker: DjvuEmissionGateCode | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "annotation": self.annotation.to_json() if self.annotation is not None else None,
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "chunk_index": self.chunk_index,
            "extraction_blocker": self.extraction_blocker,
            "info": self.info.to_json() if self.info is not None else None,
            "metadata_kind": self.metadata_kind,
            "reason": self.reason,
            "subfile_type": self.subfile_type,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class DjvuChunkActionPlan:
    kind: DjvuChunkActionKind
    chunk_id: bytes
    source_index: int | None
    output_index: int | None
    payload_length: int | None
    padding_length: int
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "kind": self.kind,
            "output_index": self.output_index,
            "padding_length": self.padding_length,
            "payload_length": self.payload_length,
            "reason": self.reason,
            "source_index": self.source_index,
        }


@dataclass(frozen=True)
class DjvuFormSizePlan:
    original_declared_size: int | None
    planned_declared_size: int | None
    planned_file_size: int | None
    size_field_changes: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "original_declared_size": self.original_declared_size,
            "planned_declared_size": self.planned_declared_size,
            "planned_file_size": self.planned_file_size,
            "size_field_changes": self.size_field_changes,
        }


@dataclass(frozen=True)
class DjvuOutputEmissionGate:
    code: DjvuEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DjvuMetadataTransactionPlan:
    status: DjvuPlanStatus
    header: DjvuFormHeaderPlan
    chunks: tuple[DjvuChunkPlan, ...]
    metadata_routes: tuple[DjvuMetadataRoutePlan, ...]
    actions: tuple[DjvuChunkActionPlan, ...]
    output_chunks: tuple[DjvuOutputChunk, ...]
    form_size: DjvuFormSizePlan
    output_emission_gates: tuple[DjvuOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"DjVu metadata transaction output is gated: {gate_codes}")
        if self.header.file_type is None:
            raise ValueError("DjVu metadata transaction output is gated: unsupported form type")
        return encode_djvu_chunks(self.header.file_type.encode("ascii"), self.output_chunks)

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "actions": json_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "chunks": json_array(chunk.to_json() for chunk in self.chunks),
            "form_size": self.form_size.to_json(),
            "header": self.header.to_json(),
            "metadata_routes": json_array(route.to_json() for route in self.metadata_routes),
            "output_chunk_ids": [ascii_chunk_id(chunk.chunk_id) for chunk in self.output_chunks],
            "output_emission_gates": json_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "status": self.status,
        }


def build_djvu_metadata_transaction_plan(
    djvu_data: bytes,
    *,
    metadata_entries: Iterable[DjvuMetadataRequest] = (),
    xmp_payload: str | None = None,
    annotation_text: str | None = None,
    delete_all_metadata: bool = False,
    allow_output_emission: bool = False,
) -> DjvuMetadataTransactionPlan:
    header = build_djvu_form_header_plan(djvu_data)
    gates: list[DjvuOutputEmissionGate] = []
    if header.reason is not None and header.reason != "declared_form_size_mismatch":
        gates.append(
            DjvuOutputEmissionGate(
                header.reason,
                "DjVu AT&T FORM header is not supported.",
                header.evidence_ids,
            )
        )
        return unsupported_plan(header, gates)
    if header.reason == "declared_form_size_mismatch":
        gates.append(
            DjvuOutputEmissionGate(
                "declared_form_size_mismatch",
                "The DjVu FORM size field does not match the current byte length.",
                (DJVU_HEADER_EVIDENCE_ID,),
            )
        )

    chunks, chunk_gates = enumerate_djvu_chunks(djvu_data)
    gates.extend(chunk_gates)
    if chunk_gates:
        return unsupported_plan(header, gates, chunks=chunks)

    routes = tuple(route_existing_chunk(chunk) for chunk in chunks)
    rewrite_requested = (
        tuple(metadata_entries) != ()
        or xmp_payload is not None
        or annotation_text is not None
        or delete_all_metadata
    )
    if rewrite_requested:
        gates.append(
            DjvuOutputEmissionGate(
                "metadata_rewrite_not_supported_by_oracle",
                "The DjVu oracle source defines extraction tables but no write procedure.",
                (DJVU_READ_ONLY_EVIDENCE_ID,),
            )
        )
        if any(route.metadata_kind == "compressed_annotation" for route in routes):
            gates.append(
                DjvuOutputEmissionGate(
                    "compressed_metadata_requires_bzz_decode",
                    "ANTz metadata rewrite would require BZZ decode and re-encode support.",
                    (DJVU_BZZ_EVIDENCE_ID,),
                )
            )
        if any(route.metadata_kind == "compressed_text" for route in routes):
            gates.append(
                DjvuOutputEmissionGate(
                    "compressed_text_rewrite_not_planned",
                    "TXTz is not routed by DjVu.pm and is preserved unchanged.",
                    (DJVU_MAIN_TABLE_EVIDENCE_ID, DJVU_UNKNOWN_SKIP_EVIDENCE_ID),
                )
            )

    output_chunks, actions = plan_preservation_actions(chunks, routes)
    planned_declared_size = planned_form_declared_size(output_chunks)
    form_size = DjvuFormSizePlan(
        original_declared_size=header.declared_size,
        planned_declared_size=(
            planned_declared_size if planned_declared_size <= DJVU_MAX_FORM_SIZE else None
        ),
        planned_file_size=(
            planned_declared_size + 12 if planned_declared_size <= DJVU_MAX_FORM_SIZE else None
        ),
        size_field_changes=header.declared_size != planned_declared_size,
        evidence_ids=(DJVU_HEADER_EVIDENCE_ID,),
    )
    actions = (
        *actions,
        DjvuChunkActionPlan(
            "update_form_size",
            DJVU_FORM_SIGNATURE,
            None,
            None,
            form_size.planned_declared_size,
            0,
            "Preserve or update the DjVu FORM size from planned chunk bytes.",
            (DJVU_HEADER_EVIDENCE_ID,),
        ),
    )
    if planned_declared_size > DJVU_MAX_FORM_SIZE:
        gates.append(
            DjvuOutputEmissionGate(
                "planned_form_size_exceeds_uint32",
                "The planned FORM size does not fit in the DjVu uint32 size field.",
                (DJVU_HEADER_EVIDENCE_ID,),
            )
        )
    if not allow_output_emission:
        gates.append(
            DjvuOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "DjVu transaction plans are non-mutating unless emission is explicitly allowed.",
                (DJVU_READ_ONLY_EVIDENCE_ID,),
            )
        )

    sources = unique_sources(
        (
            *DJVU_TRANSACTION_EVIDENCE_IDS,
            *(source for route in routes for source in route.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return DjvuMetadataTransactionPlan(
        "planned",
        header,
        chunks,
        routes,
        actions,
        output_chunks,
        form_size,
        unique_gates(tuple(gates)),
        sources,
    )


plan_djvu_metadata_transaction = build_djvu_metadata_transaction_plan


def build_djvu_form_header_plan(djvu_data: bytes) -> DjvuFormHeaderPlan:
    prefix = djvu_data[:4]
    form_signature = djvu_data[4:8] if len(djvu_data) >= 8 else b""
    declared_size = int.from_bytes(djvu_data[8:12], "big") if len(djvu_data) >= 12 else None
    form_type = djvu_data[12:16] if len(djvu_data) >= DJVU_HEADER_SIZE else b""
    declared_file_size = declared_size + 12 if declared_size is not None else None
    reason: DjvuEmissionGateCode | None = None
    file_type: DjvuFileType | None = None
    if len(djvu_data) < DJVU_HEADER_SIZE:
        reason = "truncated_djvu_header"
    elif prefix != DJVU_PREFIX:
        reason = "unsupported_djvu_prefix"
    elif form_signature != DJVU_FORM_SIGNATURE:
        reason = "unsupported_form_signature"
    elif form_type not in DJVU_FILE_TYPES:
        reason = "unsupported_djvu_form_type"
    elif form_type == b"DJVU":
        file_type = "DJVU"
    else:
        file_type = "DJVM"
    if reason is None and declared_file_size != len(djvu_data):
        reason = "declared_form_size_mismatch"
    return DjvuFormHeaderPlan(
        prefix,
        form_signature,
        declared_size,
        form_type,
        file_type,
        len(djvu_data),
        declared_file_size,
        declared_file_size == len(djvu_data),
        reason,
        (DJVU_HEADER_EVIDENCE_ID, DJVU_AIFF_DELEGATION_EVIDENCE_ID),
    )


def enumerate_djvu_chunks(
    djvu_data: bytes,
) -> tuple[tuple[DjvuChunkPlan, ...], tuple[DjvuOutputEmissionGate, ...]]:
    chunks: list[DjvuChunkPlan] = []
    gates: list[DjvuOutputEmissionGate] = []
    offset = DJVU_HEADER_SIZE
    while offset < len(djvu_data):
        if len(djvu_data) - offset < DJVU_CHUNK_HEADER_SIZE:
            gates.append(
                DjvuOutputEmissionGate(
                    "truncated_djvu_chunk_header",
                    "Input ended before a complete DjVu chunk header could be read.",
                    (DJVU_CHUNK_ENUMERATION_EVIDENCE_ID,),
                )
            )
            break
        chunk_start = offset
        chunk_id = djvu_data[offset : offset + 4]
        payload_length = int.from_bytes(djvu_data[offset + 4 : offset + 8], "big")
        payload_offset = offset + DJVU_CHUNK_HEADER_SIZE
        payload_end = payload_offset + payload_length
        padding_length = payload_length & 1
        padded_end = payload_end + padding_length
        if payload_end > len(djvu_data):
            gates.append(
                DjvuOutputEmissionGate(
                    "truncated_djvu_chunk_payload",
                    f"Chunk {ascii_chunk_id(chunk_id)} declares {payload_length} payload bytes.",
                    (DJVU_CHUNK_ENUMERATION_EVIDENCE_ID,),
                )
            )
            break
        if padded_end > len(djvu_data):
            gates.append(
                DjvuOutputEmissionGate(
                    "missing_odd_chunk_padding",
                    f"Odd-sized chunk {ascii_chunk_id(chunk_id)} has no padding byte.",
                    (DJVU_CHUNK_ENUMERATION_EVIDENCE_ID,),
                )
            )
            break
        chunks.append(
            DjvuChunkPlan(
                len(chunks),
                chunk_id,
                chunk_start,
                payload_offset,
                payload_length,
                payload_end,
                padding_length,
                djvu_data[payload_end:padded_end],
                padded_end,
                djvu_data[payload_offset:payload_end],
                (DJVU_CHUNK_ENUMERATION_EVIDENCE_ID,),
            )
        )
        offset = padded_end
    return tuple(chunks), tuple(gates)


def plan_preservation_actions(
    chunks: tuple[DjvuChunkPlan, ...],
    routes: tuple[DjvuMetadataRoutePlan, ...],
) -> tuple[tuple[DjvuOutputChunk, ...], tuple[DjvuChunkActionPlan, ...]]:
    output_chunks: list[DjvuOutputChunk] = []
    actions: list[DjvuChunkActionPlan] = []
    for chunk, route in zip(chunks, routes, strict=True):
        output_index = len(output_chunks)
        output_chunk = chunk.to_output_chunk()
        output_chunks.append(output_chunk)
        actions.append(
            DjvuChunkActionPlan(
                preservation_action_kind(route.metadata_kind),
                chunk.chunk_id,
                chunk.index,
                output_index,
                chunk.payload_length,
                chunk.padding_length,
                preservation_action_reason(route.metadata_kind),
                route.evidence_ids,
            )
        )
    return tuple(output_chunks), tuple(actions)


def route_existing_chunk(chunk: DjvuChunkPlan) -> DjvuMetadataRoutePlan:
    if chunk.chunk_id == INFO_CHUNK_ID:
        return DjvuMetadataRoutePlan(
            chunk.chunk_id,
            chunk.index,
            "info",
            "INFO",
            parse_info_payload(chunk.payload),
            None,
            None,
            None,
            "Route INFO through the DjVu binary info table.",
            (DJVU_INFO_EVIDENCE_ID, DJVU_CHUNK_PAYLOAD_EVIDENCE_ID),
        )
    if chunk.chunk_id == FORM_CHUNK_ID:
        subfile = chunk.payload[:4]
        return DjvuMetadataRoutePlan(
            chunk.chunk_id,
            chunk.index,
            "form",
            "SubfileType",
            None,
            None,
            DJVU_FORM_TYPES.get(subfile, ascii_chunk_id(subfile)),
            None,
            "Route FORM type bytes through the DjVu subfile table.",
            (DJVU_FORM_EVIDENCE_ID, DJVU_MAIN_TABLE_EVIDENCE_ID, DJVU_CHUNK_PAYLOAD_EVIDENCE_ID),
        )
    if chunk.chunk_id == ANTA_CHUNK_ID:
        return DjvuMetadataRoutePlan(
            chunk.chunk_id,
            chunk.index,
            "annotation",
            "ANTa",
            None,
            parse_annotation_payload(chunk.payload),
            None,
            None,
            "Route text annotation payload through ProcessAnt.",
            (DJVU_ANNOTATION_EVIDENCE_ID, DJVU_PROCESS_ANT_EVIDENCE_ID, DJVU_PARSE_ANT_EVIDENCE_ID),
        )
    if chunk.chunk_id == ANTZ_CHUNK_ID:
        from exifmodern.formats.djvu.bzz import BzzDecodeError, decode_bzz

        try:
            decoded = decode_bzz(chunk.payload).decoded
        except BzzDecodeError:
            return DjvuMetadataRoutePlan(
                chunk.chunk_id,
                chunk.index,
                "compressed_annotation",
                "CompressedAnnotation",
                None,
                None,
                None,
                "compressed_metadata_requires_bzz_decode",
                "Preserve ANTz when bounded BZZ decode fails or reaches unsupported data.",
                (DJVU_ANNOTATION_EVIDENCE_ID, DJVU_BZZ_EVIDENCE_ID),
            )
        return DjvuMetadataRoutePlan(
            chunk.chunk_id,
            chunk.index,
            "compressed_annotation",
            "CompressedAnnotation",
            None,
            parse_annotation_payload(decoded),
            None,
            None,
            "Decode ANTz with BZZ and route the annotation payload through ProcessAnt.",
            (DJVU_ANNOTATION_EVIDENCE_ID, DJVU_BZZ_EVIDENCE_ID, DJVU_PROCESS_ANT_EVIDENCE_ID),
        )
    if chunk.chunk_id == INCL_CHUNK_ID:
        return DjvuMetadataRoutePlan(
            chunk.chunk_id,
            chunk.index,
            "included_file",
            "IncludedFileID",
            None,
            None,
            ascii_chunk_id(chunk.payload.rstrip(b"\x00")),
            None,
            "Route INCL as an included file identifier.",
            (DJVU_MAIN_TABLE_EVIDENCE_ID, DJVU_CHUNK_PAYLOAD_EVIDENCE_ID),
        )
    if chunk.chunk_id == TXTZ_CHUNK_ID:
        return DjvuMetadataRoutePlan(
            chunk.chunk_id,
            chunk.index,
            "compressed_text",
            "TXTz",
            None,
            None,
            None,
            "compressed_text_rewrite_not_planned",
            "Preserve TXTz because DjVu.pm does not route it as metadata.",
            (DJVU_MAIN_TABLE_EVIDENCE_ID, DJVU_UNKNOWN_SKIP_EVIDENCE_ID),
        )
    if chunk.chunk_id in IMAGE_PAYLOAD_CHUNK_IDS:
        return DjvuMetadataRoutePlan(
            chunk.chunk_id,
            chunk.index,
            "image_or_page_payload",
            None,
            None,
            None,
            None,
            None,
            "Preserve DjVu image/page payload outside the metadata tables.",
            (DJVU_MAIN_TABLE_EVIDENCE_ID, DJVU_UNKNOWN_SKIP_EVIDENCE_ID),
        )
    return DjvuMetadataRoutePlan(
        chunk.chunk_id,
        chunk.index,
        "unknown",
        None,
        None,
        None,
        None,
        None,
        "Preserve unknown DjVu chunk bytes.",
        (DJVU_UNKNOWN_SKIP_EVIDENCE_ID, DJVU_CHUNK_ENUMERATION_EVIDENCE_ID),
    )


def parse_info_payload(payload: bytes) -> DjvuInfoPlan:
    width = int.from_bytes(payload[0:2], "big") if len(payload) >= 2 else None
    height = int.from_bytes(payload[2:4], "big") if len(payload) >= 4 else None
    version = parse_djvu_version(payload)
    spatial_resolution = ((payload[7] & 0xFF) << 8) + payload[6] if len(payload) >= 8 else None
    gamma = payload[8] / 10 if len(payload) >= 9 else None
    orientation_code = payload[9] & 0x07 if len(payload) >= 10 else None
    orientation = (
        {
            1: "Horizontal (normal)",
            2: "Rotate 180",
            5: "Rotate 90 CW",
            6: "Rotate 270 CW",
        }.get(orientation_code)
        if orientation_code is not None
        else None
    )
    return DjvuInfoPlan(
        width,
        height,
        version,
        spatial_resolution,
        gamma,
        orientation_code,
        orientation,
        (DJVU_INFO_EVIDENCE_ID,),
    )


def parse_djvu_version(payload: bytes) -> str | None:
    if len(payload) < 5:
        return None
    major = payload[4]
    if len(payload) >= 6:
        minor = payload[5]
        return f"{minor}.{major}"
    return f"0.{major}"


def parse_annotation_payload(payload: bytes) -> DjvuAnnotationPlan:
    text = payload.decode("latin-1")
    prescan_hit = has_annotation_metadata_prescan_hit(text)
    sources = (
        DJVU_ANNOTATION_EVIDENCE_ID,
        DJVU_PROCESS_ANT_EVIDENCE_ID,
        DJVU_PARSE_ANT_EVIDENCE_ID,
    )
    if not prescan_hit:
        return DjvuAnnotationPlan(False, (), None, 0, False, sources)
    parser = DjvuAnnotationParser(text)
    parsed = parser.parse_all()
    if parsed is None:
        return DjvuAnnotationPlan(True, (), None, 1, False, sources)
    entries: list[DjvuMetadataEntryPlan] = []
    xmp_payload: str | None = None
    invalid_count = 0
    for annotation in parsed:
        if not isinstance(annotation, tuple) or len(annotation) < 2:
            continue
        tag = annotation[0]
        if not isinstance(tag, str):
            continue
        if tag == "metadata":
            parsed_entries, invalid_entries = parse_metadata_entries(annotation[1:])
            entries.extend(parsed_entries)
            invalid_count += invalid_entries
        elif tag == "xmp" and isinstance(annotation[1], str):
            xmp_payload = annotation[1]
    return DjvuAnnotationPlan(
        True,
        tuple(entries),
        xmp_payload,
        invalid_count,
        True,
        (*sources, DJVU_PROCESS_META_EVIDENCE_ID, DJVU_METADATA_EVIDENCE_ID),
    )


def has_annotation_metadata_prescan_hit(text: str) -> bool:
    index = 0
    while True:
        start = text.find("(", index)
        if start < 0:
            return False
        cursor = start + 1
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if text.startswith("metadata", cursor):
            end = cursor + len("metadata")
            if end < len(text) and (text[end].isspace() or text[end] in '("'):
                return True
        if text.startswith("xmp", cursor):
            end = cursor + len("xmp")
            if end < len(text) and (text[end].isspace() or text[end] in '("'):
                return True
        index = start + 1


def parse_metadata_entries(
    nodes: tuple[DjvuAnnotationNode, ...],
) -> tuple[tuple[DjvuMetadataEntryPlan, ...], int]:
    entries: list[DjvuMetadataEntryPlan] = []
    invalid_count = 0
    for node in nodes:
        if not isinstance(node, tuple) or len(node) < 2:
            invalid_count += 1
            continue
        tag_node = node[0]
        value_node = node[1]
        if not isinstance(tag_node, str) or not isinstance(value_node, str):
            invalid_count += 1
            continue
        standard = tag_node in DJVU_STANDARD_META_TAGS
        entries.append(
            DjvuMetadataEntryPlan(
                tag_node,
                value_node,
                True,
                standard,
                None if standard else dynamic_tag_name(tag_node),
                (DJVU_PROCESS_META_EVIDENCE_ID, DJVU_METADATA_EVIDENCE_ID),
            )
        )
    return tuple(entries), invalid_count


def dynamic_tag_name(tag_id: str) -> str | None:
    allowed = "-_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    clean = "".join(char for char in tag_id if char in allowed)
    if not clean:
        return None
    return clean[:1].upper() + clean[1:]


class DjvuAnnotationParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.position = 0

    def parse_all(self) -> tuple[DjvuAnnotationNode, ...] | None:
        nodes: list[DjvuAnnotationNode] = []
        while self.skip_whitespace():
            node = self.parse_node()
            if node is None:
                return None
            nodes.append(node)
        return tuple(nodes) if nodes else None

    def parse_node(self) -> DjvuAnnotationNode | None:
        if self.position >= len(self.text):
            return None
        char = self.text[self.position]
        if char == "(":
            return self.parse_list()
        if char == '"':
            return self.parse_quoted()
        if char == ")":
            return None
        return self.parse_symbol()

    def parse_list(self) -> tuple[DjvuAnnotationNode, ...] | None:
        self.position += 1
        nodes: list[DjvuAnnotationNode] = []
        while self.skip_whitespace():
            if self.position < len(self.text) and self.text[self.position] == ")":
                self.position += 1
                return tuple(nodes)
            node = self.parse_node()
            if node is None:
                return None
            nodes.append(node)
        return None

    def parse_quoted(self) -> str | None:
        self.position += 1
        chars: list[str] = []
        while self.position < len(self.text):
            char = self.text[self.position]
            self.position += 1
            if char == '"':
                return "".join(chars)
            if char == "\\" and self.position < len(self.text):
                escape = self.text[self.position]
                self.position += 1
                chars.append(
                    {
                        "a": "\a",
                        "b": "\b",
                        "f": "\f",
                        "n": "\n",
                        "r": "\r",
                        "t": "\t",
                        '"': '"',
                        "\\": "\\",
                    }.get(escape, "\\" + escape)
                )
                continue
            chars.append(char)
        return None

    def parse_symbol(self) -> str | None:
        start = self.position
        while self.position < len(self.text):
            char = self.text[self.position]
            if char.isspace() or char in '()"':
                break
            self.position += 1
        if self.position == start:
            return None
        return self.text[start : self.position]

    def skip_whitespace(self) -> bool:
        while self.position < len(self.text) and self.text[self.position].isspace():
            self.position += 1
        return self.position < len(self.text)


def encode_djvu_chunks(form_type: bytes, chunks: Iterable[DjvuOutputChunk]) -> bytes:
    encoded_chunks = bytearray()
    for chunk in chunks:
        encoded_chunks.extend(chunk.chunk_id)
        encoded_chunks.extend(len(chunk.payload).to_bytes(4, "big"))
        encoded_chunks.extend(chunk.payload)
        if len(chunk.payload) & 1:
            encoded_chunks.extend(chunk.padding_byte[:1] or b"\x00")
    declared_size = 4 + len(encoded_chunks)
    if declared_size > DJVU_MAX_FORM_SIZE:
        raise ValueError("DjVu FORM size exceeds uint32")
    return (
        DJVU_PREFIX
        + DJVU_FORM_SIGNATURE
        + declared_size.to_bytes(4, "big")
        + form_type
        + bytes(encoded_chunks)
    )


def planned_form_declared_size(chunks: Iterable[DjvuOutputChunk]) -> int:
    return 4 + sum(chunk.encoded_length for chunk in chunks)


def preservation_action_kind(metadata_kind: DjvuMetadataKind) -> DjvuChunkActionKind:
    if metadata_kind == "compressed_annotation":
        return "preserve_compressed_metadata"
    if metadata_kind == "included_file":
        return "preserve_included_file"
    if metadata_kind == "compressed_text":
        return "preserve_compressed_text"
    if metadata_kind == "image_or_page_payload":
        return "preserve_image_payload"
    if metadata_kind == "unknown":
        return "preserve_unknown"
    if metadata_kind in {"info", "form", "annotation"}:
        return "preserve_metadata"
    return "copy"


def preservation_action_reason(metadata_kind: DjvuMetadataKind) -> str:
    if metadata_kind == "compressed_annotation":
        return "Preserve ANTz compressed annotation bytes unchanged."
    if metadata_kind == "included_file":
        return "Preserve included file reference bytes unchanged."
    if metadata_kind == "compressed_text":
        return "Preserve compressed text layer bytes unchanged."
    if metadata_kind == "image_or_page_payload":
        return "Preserve DjVu image/page payload bytes unchanged."
    if metadata_kind == "unknown":
        return "Preserve unknown DjVu chunk bytes unchanged."
    return "Preserve DjVu metadata chunk bytes unchanged."


def unsupported_plan(
    header: DjvuFormHeaderPlan,
    gates: list[DjvuOutputEmissionGate],
    *,
    chunks: tuple[DjvuChunkPlan, ...] = (),
) -> DjvuMetadataTransactionPlan:
    sources = unique_sources(
        (
            DJVU_HEADER_EVIDENCE_ID,
            DJVU_CHUNK_ENUMERATION_EVIDENCE_ID,
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return DjvuMetadataTransactionPlan(
        "unsupported",
        header,
        chunks,
        (),
        (),
        (),
        DjvuFormSizePlan(
            header.declared_size,
            None,
            None,
            False,
            (DJVU_HEADER_EVIDENCE_ID,),
        ),
        unique_gates(tuple(gates)),
        sources,
    )


def ascii_chunk_id(chunk_id: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else f"\\x{byte:02x}" for byte in chunk_id)


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def json_array(values: Iterable[JsonValue]) -> JsonArray:
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


def unique_gates(
    gates: tuple[DjvuOutputEmissionGate, ...],
) -> tuple[DjvuOutputEmissionGate, ...]:
    seen: set[DjvuEmissionGateCode] = set()
    unique: list[DjvuOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
