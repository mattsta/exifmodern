"""Source-backed RIFF/WAV metadata transaction plans and narrow delete emission.

ExifTool reads RIFF/WAVE and RIFF/AVI by validating the RIFF/RF64 signature,
mapping the four-byte form type, walking padded chunks, and routing known
metadata chunks such as LIST/INFO, LIST/exif, XMP, and ID3.  Its RIFF writer is
currently WebP-only, so this module gates broad WAV/AVI metadata writing.  The
only executable non-WebP slice is delete-all-modeled-metadata for simple RIFF
WAV/AVI files where complete top-level metadata chunks can be removed and every
other encoded chunk can be copied byte-for-byte.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

RIFF_HEADER_SIZE = 12
RIFF_CHUNK_HEADER_SIZE = 8
LIST_TYPE_SIZE = 4
MAX_RIFF_DECLARED_SIZE = 0xFFFFFFFF

RIFF_FORM_TYPES: dict[bytes, str] = {
    b"WAVE": "WAV",
    b"AVI ": "AVI",
    b"WEBP": "WEBP",
}

INFO_TAG_NAMES: dict[bytes, str] = {
    b"IART": "Artist",
    b"ICMT": "Comment",
    b"ICOP": "Copyright",
    b"ICRD": "DateCreated",
    b"IGNR": "Genre",
    b"IKEY": "Keywords",
    b"INAM": "Title",
    b"IPRD": "Product",
    b"ISBJ": "Subject",
    b"ISFT": "Software",
    b"ITCH": "Technician",
}

EXIF_LIST_TAG_NAMES: dict[bytes, str] = {
    b"ever": "ExifVersion",
    b"erel": "RelatedImageFile",
    b"etim": "TimeCreated",
    b"ecor": "Make",
    b"emdl": "Model",
    b"emnt": "MakerNotes",
    b"eucm": "UserComment",
}

type RiffFormFamily = Literal["WAV", "AVI", "WEBP", "unknown"]
type RiffPlanStatus = Literal["planned", "unsupported"]
type RiffDeclaredSizeRelation = Literal[
    "matches_file",
    "declares_less_than_file",
    "declares_more_than_file",
    "unknown",
]
type RiffChunkAction = Literal[
    "route_list_info_metadata",
    "route_list_exif_metadata",
    "route_xmp_metadata",
    "route_id3_metadata",
    "route_c2pa_metadata",
    "preserve_media",
    "preserve_container",
    "preserve_padding",
    "preserve_unknown",
]
type RiffMetadataFamily = Literal[
    "info",
    "riff_exif",
    "xmp",
    "id3",
    "c2pa",
    "iptc",
    "media",
    "unknown",
]
type RiffMetadataRouteAction = Literal[
    "upsert_list_info_text",
    "upsert_list_exif_text",
    "replace_xmp_chunk",
    "replace_id3_chunk",
    "replace_c2pa_chunk",
    "unsupported_iptc_chunk",
]
type RiffMetadataDeleteScope = Literal["tag", "family", "all_metadata"]
type RiffMetadataDeleteAction = Literal[
    "delete_list_info_text",
    "delete_list_info_chunk",
    "delete_list_exif_text",
    "delete_list_exif_chunk",
    "delete_xmp_chunk",
    "delete_id3_chunk",
    "delete_c2pa_chunk",
    "delete_all_modeled_metadata",
    "unsupported_iptc_delete",
]
type RiffEmissionGateCode = Literal[
    "truncated_riff_header",
    "unsupported_riff_signature",
    "unsupported_riff_form_type",
    "webp_uses_existing_webp_planner",
    "rf64_size_model_not_supported",
    "truncated_riff_chunk",
    "missing_odd_chunk_padding",
    "trailing_partial_chunk_header",
    "truncated_list_type",
    "truncated_list_subchunk",
    "missing_odd_list_subchunk_padding",
    "size_growth_requires_full_riff_rewrite",
    "riff_size_update_exceeds_32bit_field",
    "planner_is_non_mutating",
    "full_wav_riff_writer_not_implemented",
]
type RiffConcern = Literal[
    "riff_wave_avi_signature_validation",
    "chunk_enumeration_and_padding",
    "list_info_metadata_routing",
    "id3_xmp_exif_c2pa_responsibilities",
    "metadata_deletion_routing",
    "iptc_not_modeled_by_exiftool_riff",
    "unknown_chunk_preservation",
    "data_media_chunk_preservation",
    "riff_size_update_gate",
    "output_emission_gate",
]

RIFF_TYPE_SOURCE = "riff.wav_metadata.riff_type"
RIFF_READ_HEADER_SOURCE = "riff.wav_metadata.riff_read_header"
RIFF_DECLARED_END_SOURCE = "riff.wav_metadata.riff_declared_end"
RIFF_CHUNK_SOURCE = "riff.wav_metadata.riff_chunk"
RIFF_PADDING_SOURCE = "riff.wav_metadata.riff_padding"
RIFF_MAIN_METADATA_SOURCE = "riff.wav_metadata.riff_main_metadata"
RIFF_INFO_SOURCE = "riff.wav_metadata.riff_info"
RIFF_EXIF_LIST_SOURCE = "riff.wav_metadata.riff_exif_list"
RIFF_METADATA_CHUNK_SOURCE = "riff.wav_metadata.riff_metadata_chunk"
RIFF_METADATA_DELETE_SOURCE = "riff.wav_metadata.riff_metadata_delete"
RIFF_MEDIA_SOURCE = "riff.wav_metadata.riff_media"
RIFF_DS64_SOURCE = "riff.wav_metadata.riff_ds64"
RIFF_WRITE_WEBP_ONLY_SOURCE = "riff.wav_metadata.riff_write_webp_only"
RIFF_WRITE_SIZE_SOURCE = "riff.wav_metadata.riff_write_size"
RIFF_WRITE_COPY_SOURCE = "riff.wav_metadata.riff_write_copy"


@dataclass(frozen=True)
class RiffMetadataWriteRequest:
    family: RiffMetadataFamily
    tag_name: str
    value: str | bytes
    estimated_payload_size: int

    def to_json(self) -> JsonObject:
        value: JsonValue = self.value.hex() if isinstance(self.value, bytes) else self.value
        return {
            "estimated_payload_size": self.estimated_payload_size,
            "family": self.family,
            "tag_name": self.tag_name,
            "value": value,
        }


@dataclass(frozen=True)
class RiffMetadataDeleteRequest:
    scope: RiffMetadataDeleteScope
    family: RiffMetadataFamily | None = None
    tag_name: str | None = None

    def to_json(self) -> JsonObject:
        return {
            "family": self.family,
            "scope": self.scope,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class RiffSignatureValidationPlan:
    signature: bytes
    form_type: bytes
    family: RiffFormFamily
    is_rf64: bool
    declared_size: int | None
    declared_file_size: int | None
    actual_file_size: int
    declared_size_matches_file: bool
    declared_size_relation: RiffDeclaredSizeRelation
    is_supported_reader_variant: bool
    reason: RiffEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "actual_file_size": self.actual_file_size,
            "declared_file_size": self.declared_file_size,
            "declared_size": self.declared_size,
            "declared_size_matches_file": self.declared_size_matches_file,
            "declared_size_relation": self.declared_size_relation,
            "family": self.family,
            "form_type": ascii_chunk_id(self.form_type),
            "is_rf64": self.is_rf64,
            "is_supported_reader_variant": self.is_supported_reader_variant,
            "reason": self.reason,
            "signature": ascii_chunk_id(self.signature),
        }


@dataclass(frozen=True)
class RiffChunkPlan:
    index: int
    chunk_id: bytes
    effective_id: str
    list_type: bytes | None
    chunk_start_offset: int
    payload_offset: int
    payload_length: int
    payload_body_offset: int
    payload_body_length: int
    padding_length: int
    padded_end_offset: int
    action: RiffChunkAction
    metadata_family: RiffMetadataFamily
    preservation_required: bool
    evidence_ids: tuple[str, ...]

    @property
    def encoded_length(self) -> int:
        return RIFF_CHUNK_HEADER_SIZE + self.payload_length + self.padding_length

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "chunk_start_offset": self.chunk_start_offset,
            "effective_id": self.effective_id,
            "encoded_length": self.encoded_length,
            "index": self.index,
            "list_type": ascii_chunk_id_or_none(self.list_type),
            "metadata_family": self.metadata_family,
            "padded_end_offset": self.padded_end_offset,
            "padding_length": self.padding_length,
            "payload_body_length": self.payload_body_length,
            "payload_body_offset": self.payload_body_offset,
            "payload_length": self.payload_length,
            "payload_offset": self.payload_offset,
            "preservation_required": self.preservation_required,
        }


@dataclass(frozen=True)
class RiffListSubchunkPlan:
    parent_chunk_index: int
    parent_list_type: bytes
    index: int
    chunk_id: bytes
    tag_name: str | None
    payload_offset: int
    payload_length: int
    padding_length: int
    padded_end_offset: int
    metadata_family: RiffMetadataFamily
    value_preview: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_id": ascii_chunk_id(self.chunk_id),
            "index": self.index,
            "metadata_family": self.metadata_family,
            "padded_end_offset": self.padded_end_offset,
            "padding_length": self.padding_length,
            "parent_chunk_index": self.parent_chunk_index,
            "parent_list_type": ascii_chunk_id(self.parent_list_type),
            "payload_length": self.payload_length,
            "payload_offset": self.payload_offset,
            "tag_name": self.tag_name,
            "value_preview": self.value_preview,
        }


@dataclass(frozen=True)
class RiffMetadataResponsibility:
    family: RiffMetadataFamily
    chunk_id: str
    route: str
    exiftool_modeled: bool
    writer_supported: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_id": self.chunk_id,
            "exiftool_modeled": self.exiftool_modeled,
            "family": self.family,
            "route": self.route,
            "writer_supported": self.writer_supported,
        }


@dataclass(frozen=True)
class RiffMetadataRoutePlan:
    action: RiffMetadataRouteAction
    family: RiffMetadataFamily
    tag_name: str
    target_chunk_id: str
    existing_payload_size: int | None
    estimated_payload_size: int
    estimated_growth: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "estimated_growth": self.estimated_growth,
            "estimated_payload_size": self.estimated_payload_size,
            "existing_payload_size": self.existing_payload_size,
            "family": self.family,
            "tag_name": self.tag_name,
            "target_chunk_id": self.target_chunk_id,
        }


@dataclass(frozen=True)
class RiffMetadataDeletePlan:
    action: RiffMetadataDeleteAction
    scope: RiffMetadataDeleteScope
    family: RiffMetadataFamily | None
    tag_name: str | None
    target_chunk_id: str
    estimated_removed_size: int
    estimated_size_delta: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "estimated_removed_size": self.estimated_removed_size,
            "estimated_size_delta": self.estimated_size_delta,
            "family": self.family,
            "scope": self.scope,
            "tag_name": self.tag_name,
            "target_chunk_id": self.target_chunk_id,
        }


@dataclass(frozen=True)
class RiffConcernPlan:
    concern: RiffConcern
    status: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "status": self.status,
        }


@dataclass(frozen=True)
class RiffSizeUpdatePlan:
    original_declared_size: int | None
    planned_declared_size: int | None
    planned_file_size: int | None
    estimated_growth: int
    requires_size_field_update: bool
    can_update_size_field: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_update_size_field": self.can_update_size_field,
            "estimated_growth": self.estimated_growth,
            "original_declared_size": self.original_declared_size,
            "planned_declared_size": self.planned_declared_size,
            "planned_file_size": self.planned_file_size,
            "requires_size_field_update": self.requires_size_field_update,
        }


@dataclass(frozen=True)
class RiffEmissionGate:
    code: RiffEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RiffWavMetadataTransactionPlan:
    status: RiffPlanStatus
    signature_validation: RiffSignatureValidationPlan
    chunks: tuple[RiffChunkPlan, ...]
    list_subchunks: tuple[RiffListSubchunkPlan, ...]
    responsibilities: tuple[RiffMetadataResponsibility, ...]
    routes: tuple[RiffMetadataRoutePlan, ...]
    deletions: tuple[RiffMetadataDeletePlan, ...]
    concerns: tuple[RiffConcernPlan, ...]
    riff_size_update: RiffSizeUpdatePlan
    output_emission_gates: tuple[RiffEmissionGate, ...]
    preserved_unknown_chunks: int
    preserved_media_chunks: int
    preserved_padding_bytes: int
    evidence_ids: tuple[str, ...]
    output_data: bytes | None = None

    @property
    def can_emit_output(self) -> bool:
        return self.output_data is not None

    @property
    def can_mutate_bytes(self) -> bool:
        return self.output_data is not None

    @property
    def full_paths(self) -> tuple[str, ...]:
        paths = [chunk.effective_id for chunk in self.chunks]
        for subchunk in self.list_subchunks:
            paths.append(
                f"LIST_{ascii_chunk_id(subchunk.parent_list_type)}/{ascii_chunk_id(subchunk.chunk_id)}"
            )
        return tuple(paths)

    def emit(self) -> bytes:
        if self.output_data is not None:
            return self.output_data
        gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
        raise ValueError(f"RIFF/WAV metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "chunks": json_object_array(chunk.to_json() for chunk in self.chunks),
            "concerns": json_object_array(concern.to_json() for concern in self.concerns),
            "deletions": json_object_array(deletion.to_json() for deletion in self.deletions),
            "full_paths": list(self.full_paths),
            "list_subchunks": json_object_array(
                subchunk.to_json() for subchunk in self.list_subchunks
            ),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "preserved_media_chunks": self.preserved_media_chunks,
            "preserved_padding_bytes": self.preserved_padding_bytes,
            "preserved_unknown_chunks": self.preserved_unknown_chunks,
            "responsibilities": json_object_array(
                responsibility.to_json() for responsibility in self.responsibilities
            ),
            "riff_size_update": self.riff_size_update.to_json(),
            "routes": json_object_array(route.to_json() for route in self.routes),
            "signature_validation": self.signature_validation.to_json(),
            "status": self.status,
        }


def build_wav_metadata_transaction_plan(
    riff_data: bytes,
    write_requests: tuple[RiffMetadataWriteRequest, ...] = (),
    delete_requests: tuple[RiffMetadataDeleteRequest, ...] = (),
    *,
    allow_size_growth: bool = False,
    allow_output_emission: bool = False,
) -> RiffWavMetadataTransactionPlan:
    """Build a source-backed RIFF/WAVE metadata transaction plan."""

    validation = validate_riff_signature(riff_data)
    gates: list[RiffEmissionGate] = []
    if validation.reason is not None:
        gates.append(
            RiffEmissionGate(
                validation.reason,
                "RIFF header is not a supported WAV/AVI planning input.",
                validation.evidence_ids,
            )
        )
        return build_plan(
            status="unsupported",
            validation=validation,
            chunks=(),
            list_subchunks=(),
            routes=(),
            deletions=(),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    chunks, chunk_gates = enumerate_riff_chunks(riff_data)
    gates.extend(chunk_gates)
    subchunks, list_gates = enumerate_list_subchunks(riff_data, chunks)
    gates.extend(list_gates)
    routes = plan_metadata_routes(write_requests, chunks, subchunks)
    deletions = plan_metadata_deletions(delete_requests, chunks, subchunks)
    estimated_size_delta = sum(route.estimated_growth for route in routes) + sum(
        deletion.estimated_size_delta for deletion in deletions
    )
    size_update = plan_riff_size_update(validation, estimated_size_delta)
    output_data: bytes | None = None
    if allow_output_emission and validation.is_rf64:
        gates.append(
            RiffEmissionGate(
                "rf64_size_model_not_supported",
                "RF64 requires ds64 64-bit size updates that this RIFF slice does not emit.",
                (RIFF_DS64_SOURCE, RIFF_WRITE_WEBP_ONLY_SOURCE),
            )
        )
    planned_emitted_declared_size = len(riff_data) + estimated_size_delta - 8
    if planned_emitted_declared_size < 0:
        gates.append(
            RiffEmissionGate(
                "truncated_riff_header",
                "The planned RIFF output would be shorter than a RIFF header.",
                (RIFF_READ_HEADER_SOURCE, RIFF_WRITE_SIZE_SOURCE),
            )
        )
    if estimated_size_delta > 0 and not allow_size_growth:
        gates.append(
            RiffEmissionGate(
                "size_growth_requires_full_riff_rewrite",
                (
                    "Growing WAV/AVI metadata requires a full RIFF rewrite and "
                    "offset-safe size update."
                ),
                (RIFF_WRITE_SIZE_SOURCE, RIFF_WRITE_WEBP_ONLY_SOURCE),
            )
        )
    if planned_emitted_declared_size > MAX_RIFF_DECLARED_SIZE:
        gates.append(
            RiffEmissionGate(
                "riff_size_update_exceeds_32bit_field",
                "The planned RIFF size exceeds the 32-bit RIFF header field.",
                (RIFF_WRITE_SIZE_SOURCE, RIFF_DS64_SOURCE),
            )
        )
    can_emit_delete_all = (
        allow_output_emission
        and not gates
        and not write_requests
        and is_delete_all_modeled_metadata_request(delete_requests)
        and planned_emitted_declared_size <= MAX_RIFF_DECLARED_SIZE
    )
    if can_emit_delete_all:
        output_data = emit_delete_all_modeled_metadata(riff_data, chunks, validation.form_type)
        size_update = plan_emitted_riff_size_update(validation, output_data)
    return build_plan(
        status="unsupported" if structural_gate_exists(gates) else "planned",
        validation=validation,
        chunks=chunks,
        list_subchunks=subchunks,
        routes=routes,
        deletions=deletions,
        gates=gates,
        allow_output_emission=allow_output_emission,
        size_update=size_update,
        output_data=output_data,
    )


def validate_riff_signature(riff_data: bytes) -> RiffSignatureValidationPlan:
    signature = riff_data[:4]
    form_type = riff_data[8:12] if len(riff_data) >= RIFF_HEADER_SIZE else b""
    declared_size = (
        int.from_bytes(riff_data[4:8], "little") if len(riff_data) >= RIFF_HEADER_SIZE else None
    )
    declared_file_size = declared_size + 8 if declared_size is not None else None
    if declared_file_size is None:
        declared_size_relation: RiffDeclaredSizeRelation = "unknown"
    elif declared_file_size == len(riff_data):
        declared_size_relation = "matches_file"
    elif declared_file_size < len(riff_data):
        declared_size_relation = "declares_less_than_file"
    else:
        declared_size_relation = "declares_more_than_file"
    family: RiffFormFamily = "unknown"
    if form_type == b"WAVE":
        family = "WAV"
    elif form_type == b"AVI ":
        family = "AVI"
    elif form_type == b"WEBP":
        family = "WEBP"
    reason: RiffEmissionGateCode | None = None
    if len(riff_data) < RIFF_HEADER_SIZE:
        reason = "truncated_riff_header"
    elif signature not in {b"RIFF", b"RF64"}:
        reason = "unsupported_riff_signature"
    elif family == "WEBP":
        reason = "webp_uses_existing_webp_planner"
    elif family == "unknown":
        reason = "unsupported_riff_form_type"
    return RiffSignatureValidationPlan(
        signature=signature,
        form_type=form_type,
        family=family,
        is_rf64=signature == b"RF64",
        declared_size=declared_size,
        declared_file_size=declared_file_size,
        actual_file_size=len(riff_data),
        declared_size_matches_file=declared_file_size == len(riff_data),
        declared_size_relation=declared_size_relation,
        is_supported_reader_variant=reason is None,
        reason=reason,
        evidence_ids=(RIFF_TYPE_SOURCE, RIFF_READ_HEADER_SOURCE),
    )


def enumerate_riff_chunks(
    riff_data: bytes,
) -> tuple[tuple[RiffChunkPlan, ...], tuple[RiffEmissionGate, ...]]:
    chunks: list[RiffChunkPlan] = []
    gates: list[RiffEmissionGate] = []
    offset = RIFF_HEADER_SIZE
    while offset + RIFF_CHUNK_HEADER_SIZE <= len(riff_data):
        chunk_start = offset
        chunk_id = riff_data[offset : offset + 4]
        payload_length = int.from_bytes(riff_data[offset + 4 : offset + 8], "little")
        payload_offset = offset + RIFF_CHUNK_HEADER_SIZE
        payload_end = payload_offset + payload_length
        padding_length = payload_length & 1
        padded_end = payload_end + padding_length
        if payload_end > len(riff_data):
            gates.append(
                RiffEmissionGate(
                    "truncated_riff_chunk",
                    f"Chunk {ascii_chunk_id(chunk_id)} declares {payload_length} payload bytes.",
                    (RIFF_CHUNK_SOURCE,),
                )
            )
            break
        if padded_end > len(riff_data):
            gates.append(
                RiffEmissionGate(
                    "missing_odd_chunk_padding",
                    f"Odd-sized chunk {ascii_chunk_id(chunk_id)} has no padding byte.",
                    (RIFF_PADDING_SOURCE,),
                )
            )
            break
        action, family, sources, list_type = classify_chunk(
            riff_data,
            chunk_id,
            payload_offset,
            payload_length,
        )
        body_offset = payload_offset + (LIST_TYPE_SIZE if list_type is not None else 0)
        body_length = payload_length - (LIST_TYPE_SIZE if list_type is not None else 0)
        chunks.append(
            RiffChunkPlan(
                index=len(chunks),
                chunk_id=chunk_id,
                effective_id=effective_chunk_id(chunk_id, list_type),
                list_type=list_type,
                chunk_start_offset=chunk_start,
                payload_offset=payload_offset,
                payload_length=payload_length,
                payload_body_offset=body_offset,
                payload_body_length=max(body_length, 0),
                padding_length=padding_length,
                padded_end_offset=padded_end,
                action=action,
                metadata_family=family,
                preservation_required=action.startswith("preserve"),
                evidence_ids=sources,
            )
        )
        offset = padded_end
    if not gates and offset != len(riff_data):
        gates.append(
            RiffEmissionGate(
                "trailing_partial_chunk_header",
                "Trailing bytes are not enough to form a RIFF chunk header.",
                (RIFF_CHUNK_SOURCE,),
            )
        )
    return tuple(chunks), tuple(gates)


def enumerate_list_subchunks(
    riff_data: bytes,
    chunks: tuple[RiffChunkPlan, ...],
) -> tuple[tuple[RiffListSubchunkPlan, ...], tuple[RiffEmissionGate, ...]]:
    subchunks: list[RiffListSubchunkPlan] = []
    gates: list[RiffEmissionGate] = []
    for chunk in chunks:
        if chunk.list_type not in {b"INFO", b"exif"}:
            continue
        offset = chunk.payload_body_offset
        limit = chunk.payload_offset + chunk.payload_length
        if chunk.payload_length < LIST_TYPE_SIZE:
            gates.append(
                RiffEmissionGate(
                    "truncated_list_type",
                    f"LIST chunk at {chunk.chunk_start_offset} has no four-byte list type.",
                    (RIFF_CHUNK_SOURCE,),
                )
            )
            continue
        while offset + RIFF_CHUNK_HEADER_SIZE <= limit:
            subchunk_id = riff_data[offset : offset + 4]
            payload_length = int.from_bytes(riff_data[offset + 4 : offset + 8], "little")
            payload_offset = offset + RIFF_CHUNK_HEADER_SIZE
            payload_end = payload_offset + payload_length
            padding_length = payload_length & 1
            padded_end = payload_end + padding_length
            if payload_end > limit:
                gates.append(
                    RiffEmissionGate(
                        "truncated_list_subchunk",
                        (
                            f"LIST_{ascii_chunk_id(chunk.list_type or b'')} subchunk "
                            f"{ascii_chunk_id(subchunk_id)} declares {payload_length} bytes."
                        ),
                        (RIFF_CHUNK_SOURCE,),
                    )
                )
                break
            if padded_end > limit:
                gates.append(
                    RiffEmissionGate(
                        "missing_odd_list_subchunk_padding",
                        f"Odd-sized LIST subchunk {ascii_chunk_id(subchunk_id)} lacks padding.",
                        (RIFF_PADDING_SOURCE,),
                    )
                )
                break
            family, tag_name, sources = classify_list_subchunk(chunk.list_type, subchunk_id)
            subchunks.append(
                RiffListSubchunkPlan(
                    parent_chunk_index=chunk.index,
                    parent_list_type=chunk.list_type,
                    index=len(subchunks),
                    chunk_id=subchunk_id,
                    tag_name=tag_name,
                    payload_offset=payload_offset,
                    payload_length=payload_length,
                    padding_length=padding_length,
                    padded_end_offset=padded_end,
                    metadata_family=family,
                    value_preview=preview_text(riff_data[payload_offset:payload_end]),
                    evidence_ids=sources,
                )
            )
            offset = padded_end
        if offset != limit and not gates:
            gates.append(
                RiffEmissionGate(
                    "trailing_partial_chunk_header",
                    f"LIST_{ascii_chunk_id(chunk.list_type)} has trailing partial subchunk bytes.",
                    (RIFF_CHUNK_SOURCE,),
                )
            )
    return tuple(subchunks), tuple(gates)


def classify_chunk(
    riff_data: bytes,
    chunk_id: bytes,
    payload_offset: int,
    payload_length: int,
) -> tuple[RiffChunkAction, RiffMetadataFamily, tuple[str, ...], bytes | None]:
    list_type = None
    if chunk_id == b"LIST" and payload_length >= LIST_TYPE_SIZE:
        list_type = riff_data[payload_offset : payload_offset + LIST_TYPE_SIZE]
    if list_type == b"INFO":
        return (
            "route_list_info_metadata",
            "info",
            (RIFF_MAIN_METADATA_SOURCE, RIFF_INFO_SOURCE),
            list_type,
        )
    if list_type == b"exif":
        return (
            "route_list_exif_metadata",
            "riff_exif",
            (RIFF_MAIN_METADATA_SOURCE, RIFF_EXIF_LIST_SOURCE),
            list_type,
        )
    if list_type == b"movi":
        return ("preserve_media", "media", (RIFF_MEDIA_SOURCE, RIFF_CHUNK_SOURCE), list_type)
    if chunk_id == b"_PMX":
        return ("route_xmp_metadata", "xmp", (RIFF_METADATA_CHUNK_SOURCE,), None)
    if chunk_id in {b"id3 ", b"ID3 "}:
        return ("route_id3_metadata", "id3", (RIFF_METADATA_CHUNK_SOURCE,), None)
    if chunk_id == b"C2PA":
        return ("route_c2pa_metadata", "c2pa", (RIFF_METADATA_CHUNK_SOURCE,), None)
    if chunk_id == b"data":
        return ("preserve_media", "media", (RIFF_MEDIA_SOURCE, RIFF_CHUNK_SOURCE), None)
    if chunk_id in {b"JUNK", b"PAD "}:
        return ("preserve_padding", "unknown", (RIFF_WRITE_COPY_SOURCE,), None)
    if chunk_id == b"LIST":
        return (
            "preserve_container",
            "unknown",
            (RIFF_CHUNK_SOURCE, RIFF_WRITE_COPY_SOURCE),
            list_type,
        )
    return ("preserve_unknown", "unknown", (RIFF_WRITE_COPY_SOURCE,), None)


def classify_list_subchunk(
    list_type: bytes,
    subchunk_id: bytes,
) -> tuple[RiffMetadataFamily, str | None, tuple[str, ...]]:
    if list_type == b"INFO":
        return "info", INFO_TAG_NAMES.get(subchunk_id), (RIFF_INFO_SOURCE,)
    if list_type == b"exif":
        return "riff_exif", EXIF_LIST_TAG_NAMES.get(subchunk_id), (RIFF_EXIF_LIST_SOURCE,)
    return "unknown", None, (RIFF_CHUNK_SOURCE,)


def plan_metadata_routes(
    write_requests: tuple[RiffMetadataWriteRequest, ...],
    chunks: tuple[RiffChunkPlan, ...],
    subchunks: tuple[RiffListSubchunkPlan, ...],
) -> tuple[RiffMetadataRoutePlan, ...]:
    routes: list[RiffMetadataRoutePlan] = []
    for request in write_requests:
        action, target_chunk_id, sources = route_target(request.family)
        existing_size = existing_payload_size(request, chunks, subchunks)
        estimated_growth = request.estimated_payload_size - (existing_size or 0)
        routes.append(
            RiffMetadataRoutePlan(
                action=action,
                family=request.family,
                tag_name=request.tag_name,
                target_chunk_id=target_chunk_id,
                existing_payload_size=existing_size,
                estimated_payload_size=request.estimated_payload_size,
                estimated_growth=estimated_growth,
                evidence_ids=sources,
            )
        )
    return tuple(routes)


def plan_metadata_deletions(
    delete_requests: tuple[RiffMetadataDeleteRequest, ...],
    chunks: tuple[RiffChunkPlan, ...],
    subchunks: tuple[RiffListSubchunkPlan, ...],
) -> tuple[RiffMetadataDeletePlan, ...]:
    deletions: list[RiffMetadataDeletePlan] = []
    for request in delete_requests:
        action, target_chunk_id, sources = delete_target(request)
        removed_size = estimated_removed_size(request, chunks, subchunks)
        deletions.append(
            RiffMetadataDeletePlan(
                action=action,
                scope=request.scope,
                family=request.family,
                tag_name=request.tag_name,
                target_chunk_id=target_chunk_id,
                estimated_removed_size=removed_size,
                estimated_size_delta=-removed_size,
                evidence_ids=sources,
            )
        )
    return tuple(deletions)


def route_target(
    family: RiffMetadataFamily,
) -> tuple[RiffMetadataRouteAction, str, tuple[str, ...]]:
    if family == "info":
        return "upsert_list_info_text", "LIST_INFO", (RIFF_MAIN_METADATA_SOURCE, RIFF_INFO_SOURCE)
    if family == "riff_exif":
        return (
            "upsert_list_exif_text",
            "LIST_exif",
            (RIFF_MAIN_METADATA_SOURCE, RIFF_EXIF_LIST_SOURCE),
        )
    if family == "xmp":
        return "replace_xmp_chunk", "_PMX", (RIFF_METADATA_CHUNK_SOURCE,)
    if family == "id3":
        return "replace_id3_chunk", "id3 ", (RIFF_METADATA_CHUNK_SOURCE,)
    if family == "c2pa":
        return "replace_c2pa_chunk", "C2PA", (RIFF_METADATA_CHUNK_SOURCE,)
    return "unsupported_iptc_chunk", "unmodeled", (RIFF_METADATA_CHUNK_SOURCE,)


def delete_target(
    request: RiffMetadataDeleteRequest,
) -> tuple[RiffMetadataDeleteAction, str, tuple[str, ...]]:
    if request.scope == "all_metadata":
        return (
            "delete_all_modeled_metadata",
            "modeled_metadata",
            (RIFF_METADATA_DELETE_SOURCE, RIFF_WRITE_WEBP_ONLY_SOURCE),
        )
    if request.family == "info":
        if request.scope == "tag":
            return (
                "delete_list_info_text",
                "LIST_INFO",
                (RIFF_MAIN_METADATA_SOURCE, RIFF_INFO_SOURCE, RIFF_METADATA_DELETE_SOURCE),
            )
        return (
            "delete_list_info_chunk",
            "LIST_INFO",
            (RIFF_MAIN_METADATA_SOURCE, RIFF_INFO_SOURCE, RIFF_METADATA_DELETE_SOURCE),
        )
    if request.family == "riff_exif":
        if request.scope == "tag":
            return (
                "delete_list_exif_text",
                "LIST_exif",
                (RIFF_MAIN_METADATA_SOURCE, RIFF_EXIF_LIST_SOURCE, RIFF_METADATA_DELETE_SOURCE),
            )
        return (
            "delete_list_exif_chunk",
            "LIST_exif",
            (RIFF_MAIN_METADATA_SOURCE, RIFF_EXIF_LIST_SOURCE, RIFF_METADATA_DELETE_SOURCE),
        )
    if request.family == "xmp":
        return "delete_xmp_chunk", "_PMX", (RIFF_METADATA_CHUNK_SOURCE, RIFF_METADATA_DELETE_SOURCE)
    if request.family == "id3":
        return (
            "delete_id3_chunk",
            "id3 /ID3 ",
            (RIFF_METADATA_CHUNK_SOURCE, RIFF_METADATA_DELETE_SOURCE),
        )
    if request.family == "c2pa":
        return (
            "delete_c2pa_chunk",
            "C2PA",
            (RIFF_METADATA_CHUNK_SOURCE, RIFF_METADATA_DELETE_SOURCE),
        )
    return "unsupported_iptc_delete", "unmodeled", (RIFF_METADATA_DELETE_SOURCE,)


def existing_payload_size(
    request: RiffMetadataWriteRequest,
    chunks: tuple[RiffChunkPlan, ...],
    subchunks: tuple[RiffListSubchunkPlan, ...],
) -> int | None:
    if request.family == "info":
        for subchunk in subchunks:
            if subchunk.metadata_family == "info" and subchunk.tag_name == request.tag_name:
                return subchunk.payload_length
    if request.family == "riff_exif":
        for subchunk in subchunks:
            if subchunk.metadata_family == "riff_exif" and subchunk.tag_name == request.tag_name:
                return subchunk.payload_length
    chunk_match = {
        "xmp": b"_PMX",
        "id3": b"id3 ",
        "c2pa": b"C2PA",
    }.get(request.family)
    if chunk_match is None:
        return None
    for chunk in chunks:
        if chunk.chunk_id == chunk_match:
            return chunk.payload_length
    return None


def estimated_removed_size(
    request: RiffMetadataDeleteRequest,
    chunks: tuple[RiffChunkPlan, ...],
    subchunks: tuple[RiffListSubchunkPlan, ...],
) -> int:
    if request.scope == "all_metadata":
        return sum(metadata_chunk_encoded_lengths(chunks))
    if request.scope == "tag":
        return estimated_removed_tag_size(request, subchunks)
    if request.family in {"info", "riff_exif"}:
        target = b"INFO" if request.family == "info" else b"exif"
        return sum(chunk.encoded_length for chunk in chunks if chunk.list_type == target)
    chunk_ids = metadata_chunk_ids_for_family(request.family)
    return sum(chunk.encoded_length for chunk in chunks if chunk.chunk_id in chunk_ids)


def estimated_removed_tag_size(
    request: RiffMetadataDeleteRequest,
    subchunks: tuple[RiffListSubchunkPlan, ...],
) -> int:
    if request.family is None or request.tag_name is None:
        return 0
    return sum(
        RIFF_CHUNK_HEADER_SIZE + subchunk.payload_length + subchunk.padding_length
        for subchunk in subchunks
        if subchunk.metadata_family == request.family and subchunk.tag_name == request.tag_name
    )


def metadata_chunk_encoded_lengths(chunks: tuple[RiffChunkPlan, ...]) -> tuple[int, ...]:
    return tuple(
        chunk.encoded_length
        for chunk in chunks
        if chunk.metadata_family in {"info", "riff_exif", "xmp", "id3", "c2pa"}
    )


def metadata_chunk_ids_for_family(family: RiffMetadataFamily | None) -> set[bytes]:
    if family == "xmp":
        return {b"_PMX"}
    if family == "id3":
        return {b"id3 ", b"ID3 "}
    if family == "c2pa":
        return {b"C2PA"}
    return set()


def plan_riff_size_update(
    validation: RiffSignatureValidationPlan,
    estimated_size_delta: int,
    can_update_size_field: bool = False,
) -> RiffSizeUpdatePlan:
    planned_declared_size = (
        validation.declared_size + estimated_size_delta
        if validation.declared_size is not None
        else None
    )
    planned_file_size = (
        validation.declared_file_size + estimated_size_delta
        if validation.declared_file_size is not None
        else None
    )
    return RiffSizeUpdatePlan(
        original_declared_size=validation.declared_size,
        planned_declared_size=planned_declared_size,
        planned_file_size=planned_file_size,
        estimated_growth=estimated_size_delta,
        requires_size_field_update=estimated_size_delta != 0,
        can_update_size_field=can_update_size_field,
        evidence_ids=(RIFF_WRITE_SIZE_SOURCE, RIFF_WRITE_WEBP_ONLY_SOURCE),
    )


def plan_emitted_riff_size_update(
    validation: RiffSignatureValidationPlan,
    output_data: bytes,
) -> RiffSizeUpdatePlan:
    planned_declared_size = len(output_data) - 8
    return RiffSizeUpdatePlan(
        original_declared_size=validation.declared_size,
        planned_declared_size=planned_declared_size,
        planned_file_size=len(output_data),
        estimated_growth=len(output_data) - validation.actual_file_size,
        requires_size_field_update=validation.declared_size != planned_declared_size,
        can_update_size_field=True,
        evidence_ids=(RIFF_WRITE_SIZE_SOURCE, RIFF_DECLARED_END_SOURCE),
    )


def build_plan(
    *,
    status: RiffPlanStatus,
    validation: RiffSignatureValidationPlan,
    chunks: tuple[RiffChunkPlan, ...],
    list_subchunks: tuple[RiffListSubchunkPlan, ...],
    routes: tuple[RiffMetadataRoutePlan, ...],
    deletions: tuple[RiffMetadataDeletePlan, ...],
    gates: list[RiffEmissionGate],
    allow_output_emission: bool,
    size_update: RiffSizeUpdatePlan | None = None,
    output_data: bytes | None = None,
) -> RiffWavMetadataTransactionPlan:
    if size_update is None:
        size_update = plan_riff_size_update(validation, 0)
    if output_data is None and not allow_output_emission:
        gates.append(
            RiffEmissionGate(
                "planner_is_non_mutating",
                "RIFF/WAV transaction plans record decisions but do not mutate bytes.",
                (RIFF_WRITE_WEBP_ONLY_SOURCE,),
            )
        )
    if output_data is None:
        gates.append(
            RiffEmissionGate(
                "full_wav_riff_writer_not_implemented",
                "ExifTool's RIFF writer does not emit general WAV/AVI metadata updates.",
                (RIFF_WRITE_WEBP_ONLY_SOURCE,),
            )
        )
    responsibilities = riff_metadata_responsibilities()
    concerns = riff_concerns()
    unique_gate_tuple = unique_gates(tuple(gates))
    evidence_ids = unique_sources(
        (
            *validation.evidence_ids,
            RIFF_CHUNK_SOURCE,
            RIFF_PADDING_SOURCE,
            RIFF_MAIN_METADATA_SOURCE,
            RIFF_INFO_SOURCE,
            RIFF_EXIF_LIST_SOURCE,
            RIFF_METADATA_CHUNK_SOURCE,
            RIFF_MEDIA_SOURCE,
            RIFF_WRITE_SIZE_SOURCE,
            RIFF_DECLARED_END_SOURCE,
            RIFF_WRITE_COPY_SOURCE,
            RIFF_WRITE_WEBP_ONLY_SOURCE,
            *(source for chunk in chunks for source in chunk.evidence_ids),
            *(source for subchunk in list_subchunks for source in subchunk.evidence_ids),
            *(source for route in routes for source in route.evidence_ids),
            *(source for deletion in deletions for source in deletion.evidence_ids),
            *(source for gate in unique_gate_tuple for source in gate.evidence_ids),
        )
    )
    return RiffWavMetadataTransactionPlan(
        status=status,
        signature_validation=validation,
        chunks=chunks,
        list_subchunks=list_subchunks,
        responsibilities=responsibilities,
        routes=routes,
        deletions=deletions,
        concerns=concerns,
        riff_size_update=size_update,
        output_emission_gates=unique_gate_tuple,
        preserved_unknown_chunks=sum(1 for chunk in chunks if chunk.action == "preserve_unknown"),
        preserved_media_chunks=sum(1 for chunk in chunks if chunk.action == "preserve_media"),
        preserved_padding_bytes=sum(
            chunk.payload_length for chunk in chunks if chunk.action == "preserve_padding"
        ),
        evidence_ids=evidence_ids,
        output_data=output_data,
    )


def is_delete_all_modeled_metadata_request(
    delete_requests: tuple[RiffMetadataDeleteRequest, ...],
) -> bool:
    return len(delete_requests) == 1 and delete_requests[0].scope == "all_metadata"


def emit_delete_all_modeled_metadata(
    riff_data: bytes,
    chunks: tuple[RiffChunkPlan, ...],
    form_type: bytes,
) -> bytes:
    retained_chunks = b"".join(
        riff_data[chunk.chunk_start_offset : chunk.padded_end_offset]
        for chunk in chunks
        if chunk.metadata_family not in {"info", "riff_exif", "xmp", "id3", "c2pa"}
    )
    riff_size = len(form_type) + len(retained_chunks)
    return b"RIFF" + riff_size.to_bytes(4, "little") + form_type + retained_chunks


def riff_metadata_responsibilities() -> tuple[RiffMetadataResponsibility, ...]:
    return (
        RiffMetadataResponsibility(
            "info",
            "LIST_INFO",
            "RIFF INFO text subchunks",
            True,
            False,
            (RIFF_MAIN_METADATA_SOURCE, RIFF_INFO_SOURCE),
        ),
        RiffMetadataResponsibility(
            "riff_exif",
            "LIST_exif",
            "RIFF EXIF 2.3 WAV text subchunks",
            True,
            False,
            (RIFF_MAIN_METADATA_SOURCE, RIFF_EXIF_LIST_SOURCE),
        ),
        RiffMetadataResponsibility(
            "xmp",
            "_PMX",
            "Adobe Bridge XMP chunk for AVI and WAV",
            True,
            False,
            (RIFF_METADATA_CHUNK_SOURCE,),
        ),
        RiffMetadataResponsibility(
            "id3",
            "id3 /ID3 ",
            "ID3 chunk payload",
            True,
            False,
            (RIFF_METADATA_CHUNK_SOURCE,),
        ),
        RiffMetadataResponsibility(
            "c2pa",
            "C2PA",
            "JUMBF/C2PA chunk payload",
            True,
            False,
            (RIFF_METADATA_CHUNK_SOURCE,),
        ),
        RiffMetadataResponsibility(
            "iptc",
            "unmodeled",
            "No IPTC RIFF chunk responsibility is modeled by RIFF.pm",
            False,
            False,
            (RIFF_METADATA_CHUNK_SOURCE,),
        ),
    )


def riff_concerns() -> tuple[RiffConcernPlan, ...]:
    return (
        RiffConcernPlan(
            "riff_wave_avi_signature_validation",
            "planned",
            (RIFF_TYPE_SOURCE, RIFF_READ_HEADER_SOURCE),
        ),
        RiffConcernPlan("chunk_enumeration_and_padding", "planned", (RIFF_CHUNK_SOURCE,)),
        RiffConcernPlan(
            "list_info_metadata_routing",
            "planned",
            (RIFF_MAIN_METADATA_SOURCE, RIFF_INFO_SOURCE),
        ),
        RiffConcernPlan(
            "id3_xmp_exif_c2pa_responsibilities",
            "planned",
            (RIFF_MAIN_METADATA_SOURCE, RIFF_EXIF_LIST_SOURCE, RIFF_METADATA_CHUNK_SOURCE),
        ),
        RiffConcernPlan(
            "metadata_deletion_routing",
            "gated",
            (RIFF_METADATA_DELETE_SOURCE, RIFF_WRITE_WEBP_ONLY_SOURCE),
        ),
        RiffConcernPlan(
            "iptc_not_modeled_by_exiftool_riff",
            "planned",
            (RIFF_METADATA_CHUNK_SOURCE,),
        ),
        RiffConcernPlan("unknown_chunk_preservation", "planned", (RIFF_WRITE_COPY_SOURCE,)),
        RiffConcernPlan("data_media_chunk_preservation", "planned", (RIFF_MEDIA_SOURCE,)),
        RiffConcernPlan(
            "riff_size_update_gate",
            "gated",
            (RIFF_WRITE_SIZE_SOURCE, RIFF_WRITE_WEBP_ONLY_SOURCE),
        ),
        RiffConcernPlan("output_emission_gate", "gated", (RIFF_WRITE_WEBP_ONLY_SOURCE,)),
    )


def structural_gate_exists(gates: list[RiffEmissionGate]) -> bool:
    structural_codes = {
        "truncated_riff_chunk",
        "missing_odd_chunk_padding",
        "trailing_partial_chunk_header",
        "truncated_list_type",
        "truncated_list_subchunk",
        "missing_odd_list_subchunk_padding",
        "riff_size_update_exceeds_32bit_field",
    }
    return any(gate.code in structural_codes for gate in gates)


def effective_chunk_id(chunk_id: bytes, list_type: bytes | None) -> str:
    if chunk_id == b"LIST" and list_type is not None:
        return f"LIST_{ascii_chunk_id(list_type)}"
    return ascii_chunk_id(chunk_id)


def preview_text(payload: bytes) -> str | None:
    stripped = payload.rstrip(b"\0 ")
    if not stripped:
        return ""
    try:
        return stripped.decode("utf-8")
    except UnicodeDecodeError:
        return None


def ascii_chunk_id_or_none(chunk_id: bytes | None) -> str | None:
    return None if chunk_id is None else ascii_chunk_id(chunk_id)


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


def unique_gates(gates: tuple[RiffEmissionGate, ...]) -> tuple[RiffEmissionGate, ...]:
    seen: set[tuple[RiffEmissionGateCode, str]] = set()
    unique: list[RiffEmissionGate] = []
    for gate in gates:
        key = (gate.code, gate.reason)
        if key in seen:
            continue
        seen.add(key)
        unique.append(gate)
    return tuple(unique)
