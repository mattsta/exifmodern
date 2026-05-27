"""Source-grounded, non-mutating Rawzor/RWZ metadata transaction plans.

ExifTool's Rawzor module reads a fixed little-endian RWZ header, exposes SDK
and size tags, validates the embedded metadata pointer, bunzip2-decodes the
metadata side band, reassembles the original file with image data zero-filled,
and then delegates that synthetic original to normal format detection. This
planner mirrors those boundaries and records why RWZ rewriting remains gated.
"""

from __future__ import annotations

import bz2
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

RAWZOR_SIGNATURE = b"rawzor"
RAWZOR_HEADER_SIZE = 46
RAWZOR_METADATA_HEADER_SIZE = 44
RAWZOR_IMPLEMENTED_REQUIRED_VERSION = 199
RAWZOR_MAX_METADATA_OFFSET = 0x7FFFFFFF

type RawzorPlanStatus = Literal["planned", "unsupported"]
type RawzorFileTypeOperation = Literal["override_file_type_rwz", "set_file_type_rwz"]
type RawzorMetadataRoute = Literal["none", "compressed_bzip2", "not_read"]
type RawzorActionKind = Literal[
    "validate_rawzor_header",
    "expose_rawzor_versions",
    "expose_rawzor_sizes",
    "read_metadata_header",
    "preserve_compressed_metadata",
    "decode_metadata_for_original_reader",
    "delegate_original_metadata",
    "set_original_file_type",
    "plan_metadata_rewrite",
    "no_metadata_mutation",
]
type RawzorEmissionGateCode = Literal[
    "truncated_rawzor_header",
    "unsupported_rawzor_signature",
    "unsupported_required_version",
    "bad_metadata_offset",
    "metadata_header_truncated",
    "metadata_payload_truncated",
    "metadata_header_bounds_mismatch",
    "metadata_uncompress_error",
    "rawzor_metadata_rewrite_requires_full_rebuild",
    "rawzor_header_rewrite_required",
    "original_payload_recompression_required",
    "planner_is_non_mutating",
    "full_rawzor_writer_not_implemented",
]
type RawzorResponsibilityConcern = Literal[
    "signature_header_validation",
    "sdk_version_tags",
    "rwz_and_original_size_tags",
    "metadata_offset_validation",
    "metadata_header_validation",
    "bzip2_metadata_preservation",
    "bzip2_decode_boundary",
    "original_file_type_responsibility",
    "version_offset_truncation_uncompress_blockers",
    "unsupported_mutation_gates",
]

RAWZOR_MAIN_TABLE_SOURCE = "rawzor.main.table.source"
RAWZOR_HEADER_SOURCE = "rawzor.header.source"
RAWZOR_VERSION_SOURCE = "rawzor.version.source"
RAWZOR_VERSION_BLOCK_SOURCE = "rawzor.version.block.source"
RAWZOR_OFFSET_SOURCE = "rawzor.offset.source"
RAWZOR_BZIP2_REQUIRE_SOURCE = "rawzor.bzip2.require.source"
RAWZOR_METADATA_HEADER_SOURCE = "rawzor.metadata.header.source"
RAWZOR_METADATA_VALIDATE_SOURCE = "rawzor.metadata.validate.source"
RAWZOR_BZIP2_DECODE_SOURCE = "rawzor.bzip2.decode.source"
RAWZOR_REASSEMBLY_SOURCE = "rawzor.reassembly.source"
RAWZOR_ORIGINAL_TYPE_SOURCE = "rawzor.original.type.source"
RAWZOR_READ_ONLY_SOURCE = "rawzor.read.only.source"

RAWZOR_TRANSACTION_SOURCES = (
    RAWZOR_MAIN_TABLE_SOURCE,
    RAWZOR_HEADER_SOURCE,
    RAWZOR_VERSION_SOURCE,
    RAWZOR_VERSION_BLOCK_SOURCE,
    RAWZOR_OFFSET_SOURCE,
    RAWZOR_BZIP2_REQUIRE_SOURCE,
    RAWZOR_METADATA_HEADER_SOURCE,
    RAWZOR_METADATA_VALIDATE_SOURCE,
    RAWZOR_BZIP2_DECODE_SOURCE,
    RAWZOR_REASSEMBLY_SOURCE,
    RAWZOR_ORIGINAL_TYPE_SOURCE,
    RAWZOR_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class RawzorMetadataRewriteRequest:
    replacement_metadata_payload: bytes | None = None
    delete_metadata: bool = False


@dataclass(frozen=True)
class RawzorHeaderPlan:
    signature: bytes
    signature_valid: bool
    required_sdk_version_raw: int | None
    required_sdk_version: float | None
    creator_sdk_version_raw: int | None
    creator_sdk_version: float | None
    declared_rwz_size: int | None
    actual_rwz_size: int
    original_file_size: int | None
    compression_factor: float | None
    metadata_offset: int | None
    reason: RawzorEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "actual_rwz_size": self.actual_rwz_size,
            "compression_factor": self.compression_factor,
            "creator_sdk_version": self.creator_sdk_version,
            "creator_sdk_version_raw": self.creator_sdk_version_raw,
            "declared_rwz_size": self.declared_rwz_size,
            "metadata_offset": self.metadata_offset,
            "original_file_size": self.original_file_size,
            "reason": self.reason,
            "required_sdk_version": self.required_sdk_version,
            "required_sdk_version_raw": self.required_sdk_version_raw,
            "signature": self.signature.hex(),
            "signature_valid": self.signature_valid,
        }


@dataclass(frozen=True)
class RawzorMetadataHeaderPlan:
    was_read: bool
    route: RawzorMetadataRoute
    metadata_offset: int | None
    section0_end: int | None
    section1_start: int | None
    section1_end: int | None
    section2_start: int | None
    original_metadata_size: int | None
    compressed_metadata_size: int | None
    reason: RawzorEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "compressed_metadata_size": self.compressed_metadata_size,
            "metadata_offset": self.metadata_offset,
            "original_metadata_size": self.original_metadata_size,
            "reason": self.reason,
            "route": self.route,
            "section0_end": self.section0_end,
            "section1_end": self.section1_end,
            "section1_start": self.section1_start,
            "section2_start": self.section2_start,
            "was_read": self.was_read,
        }


@dataclass(frozen=True)
class RawzorMetadataPayloadPlan:
    compressed_byte_range_start: int | None
    compressed_byte_range_end: int | None
    compressed_metadata_payload: bytes
    decoded_metadata_payload: bytes
    reconstructed_original_bytes: bytes
    compressed_payload_preserved: bool
    decoded_for_original_reader: bool
    reason: RawzorEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "compressed_byte_range_end": self.compressed_byte_range_end,
            "compressed_byte_range_start": self.compressed_byte_range_start,
            "compressed_metadata_size": len(self.compressed_metadata_payload),
            "compressed_payload_preserved": self.compressed_payload_preserved,
            "decoded_for_original_reader": self.decoded_for_original_reader,
            "decoded_metadata_size": len(self.decoded_metadata_payload),
            "reason": self.reason,
            "reconstructed_original_size": len(self.reconstructed_original_bytes),
        }


@dataclass(frozen=True)
class RawzorOriginalFileTypePlan:
    delegated_to_original_reader: bool
    detected_original_file_type: str | None
    original_file_type_tag: str
    rwz_file_type_operation: RawzorFileTypeOperation
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "delegated_to_original_reader": self.delegated_to_original_reader,
            "detected_original_file_type": self.detected_original_file_type,
            "original_file_type_tag": self.original_file_type_tag,
            "rwz_file_type_operation": self.rwz_file_type_operation,
        }


@dataclass(frozen=True)
class RawzorActionPlan:
    kind: RawzorActionKind
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
class RawzorResponsibilityPlan:
    concern: RawzorResponsibilityConcern
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RawzorOutputEmissionGate:
    code: RawzorEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RawzorMetadataTransactionPlan:
    status: RawzorPlanStatus
    header: RawzorHeaderPlan
    metadata_header: RawzorMetadataHeaderPlan
    metadata_payload: RawzorMetadataPayloadPlan
    original_file_type: RawzorOriginalFileTypePlan
    actions: tuple[RawzorActionPlan, ...]
    responsibilities: tuple[RawzorResponsibilityPlan, ...]
    output_emission_gates: tuple[RawzorOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Rawzor metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "header": self.header.to_json(),
            "metadata_header": self.metadata_header.to_json(),
            "metadata_payload": self.metadata_payload.to_json(),
            "original_file_type": self.original_file_type.to_json(),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "responsibilities": json_object_array(
                responsibility.to_json() for responsibility in self.responsibilities
            ),
            "status": self.status,
        }


def build_rawzor_metadata_transaction_plan(
    rwz_data: bytes,
    rewrite_request: RawzorMetadataRewriteRequest | None = None,
) -> RawzorMetadataTransactionPlan:
    header = build_header_plan(rwz_data)
    version_code = required_version_gate(header)
    offset_code = metadata_offset_gate(header)
    can_read_metadata_header = (
        header.reason is None and version_code is None and offset_code is None
    )
    metadata_header = build_metadata_header_plan(
        rwz_data,
        header,
        can_read_metadata_header,
    )
    metadata_payload = build_metadata_payload_plan(rwz_data, header, metadata_header)
    original_file_type = build_original_file_type_plan(metadata_payload)
    actions = build_actions(header, metadata_header, metadata_payload, rewrite_request)
    gates = validation_gates(header, version_code, offset_code, metadata_header, metadata_payload)
    if rewrite_request is not None and rewrite_requested(rewrite_request):
        gates.extend(rewrite_gates(rewrite_request))
    gates.extend(non_mutating_default_gates())
    status: RawzorPlanStatus = "unsupported" if any_validation_gate(gates) else "planned"
    sources = unique_sources(
        (
            *RAWZOR_TRANSACTION_SOURCES,
            *header.evidence_ids,
            *metadata_header.evidence_ids,
            *metadata_payload.evidence_ids,
            *original_file_type.evidence_ids,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return RawzorMetadataTransactionPlan(
        status=status,
        header=header,
        metadata_header=metadata_header,
        metadata_payload=metadata_payload,
        original_file_type=original_file_type,
        actions=actions,
        responsibilities=build_responsibilities(),
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_bytes=rwz_data,
    )


def build_header_plan(rwz_data: bytes) -> RawzorHeaderPlan:
    signature = rwz_data[: len(RAWZOR_SIGNATURE)]
    reason: RawzorEmissionGateCode | None = None
    if len(rwz_data) < RAWZOR_HEADER_SIZE:
        reason = "truncated_rawzor_header"
    elif not rwz_data.startswith(RAWZOR_SIGNATURE):
        reason = "unsupported_rawzor_signature"
    declared_rwz_size = read_u64le(rwz_data, 10) if len(rwz_data) >= 18 else None
    original_file_size = read_u64le(rwz_data, 18) if len(rwz_data) >= 26 else None
    compression_factor: float | None = None
    if original_file_size is not None and declared_rwz_size is not None and declared_rwz_size != 0:
        compression_factor = original_file_size / declared_rwz_size
    required_raw = read_u16le(rwz_data, 6) if len(rwz_data) >= 8 else None
    creator_raw = read_u16le(rwz_data, 8) if len(rwz_data) >= 10 else None
    return RawzorHeaderPlan(
        signature=signature,
        signature_valid=reason is None,
        required_sdk_version_raw=required_raw,
        required_sdk_version=version_number(required_raw),
        creator_sdk_version_raw=creator_raw,
        creator_sdk_version=version_number(creator_raw),
        declared_rwz_size=declared_rwz_size,
        actual_rwz_size=len(rwz_data),
        original_file_size=original_file_size,
        compression_factor=compression_factor,
        metadata_offset=read_u64le(rwz_data, 38) if len(rwz_data) >= RAWZOR_HEADER_SIZE else None,
        reason=reason,
        evidence_ids=(RAWZOR_HEADER_SOURCE, RAWZOR_MAIN_TABLE_SOURCE),
    )


def build_metadata_header_plan(
    rwz_data: bytes,
    header: RawzorHeaderPlan,
    can_read_metadata_header: bool,
) -> RawzorMetadataHeaderPlan:
    metadata_offset = header.metadata_offset
    if not can_read_metadata_header or metadata_offset is None:
        return RawzorMetadataHeaderPlan(
            was_read=False,
            route="not_read",
            metadata_offset=metadata_offset,
            section0_end=None,
            section1_start=None,
            section1_end=None,
            section2_start=None,
            original_metadata_size=None,
            compressed_metadata_size=None,
            reason=None,
            evidence_ids=(RAWZOR_METADATA_HEADER_SOURCE,),
        )
    if metadata_offset + RAWZOR_METADATA_HEADER_SIZE > len(rwz_data):
        return RawzorMetadataHeaderPlan(
            was_read=False,
            route="not_read",
            metadata_offset=metadata_offset,
            section0_end=None,
            section1_start=None,
            section1_end=None,
            section2_start=None,
            original_metadata_size=None,
            compressed_metadata_size=None,
            reason="metadata_header_truncated",
            evidence_ids=(RAWZOR_METADATA_HEADER_SOURCE,),
        )
    section0_end = read_u64le(rwz_data, metadata_offset)
    section1_start = read_u64le(rwz_data, metadata_offset + 8)
    section1_end = read_u64le(rwz_data, metadata_offset + 16)
    section2_start = read_u64le(rwz_data, metadata_offset + 24)
    original_metadata_size = read_u32le(rwz_data, metadata_offset + 36)
    compressed_metadata_size = read_u32le(rwz_data, metadata_offset + 40)
    return RawzorMetadataHeaderPlan(
        was_read=True,
        route="compressed_bzip2" if original_metadata_size else "none",
        metadata_offset=metadata_offset,
        section0_end=section0_end,
        section1_start=section1_start,
        section1_end=section1_end,
        section2_start=section2_start,
        original_metadata_size=original_metadata_size,
        compressed_metadata_size=compressed_metadata_size,
        reason=None,
        evidence_ids=(RAWZOR_METADATA_HEADER_SOURCE, RAWZOR_METADATA_VALIDATE_SOURCE),
    )


def build_metadata_payload_plan(
    rwz_data: bytes,
    header: RawzorHeaderPlan,
    metadata_header: RawzorMetadataHeaderPlan,
) -> RawzorMetadataPayloadPlan:
    if metadata_header.route != "compressed_bzip2":
        return empty_payload_plan(None, None, metadata_header.evidence_ids)
    metadata_offset = required_int(metadata_header.metadata_offset)
    compressed_metadata_size = required_int(metadata_header.compressed_metadata_size)
    compressed_start = metadata_offset + RAWZOR_METADATA_HEADER_SIZE
    compressed_end = compressed_start + compressed_metadata_size
    compressed_payload = rwz_data[compressed_start : min(compressed_end, len(rwz_data))]
    if compressed_end > len(rwz_data):
        return RawzorMetadataPayloadPlan(
            compressed_byte_range_start=compressed_start,
            compressed_byte_range_end=compressed_end,
            compressed_metadata_payload=compressed_payload,
            decoded_metadata_payload=b"",
            reconstructed_original_bytes=b"",
            compressed_payload_preserved=False,
            decoded_for_original_reader=False,
            reason="metadata_payload_truncated",
            evidence_ids=(RAWZOR_METADATA_VALIDATE_SOURCE,),
        )
    bounds_code = metadata_bounds_gate(header, metadata_header)
    if bounds_code is not None:
        return RawzorMetadataPayloadPlan(
            compressed_byte_range_start=compressed_start,
            compressed_byte_range_end=compressed_end,
            compressed_metadata_payload=compressed_payload,
            decoded_metadata_payload=b"",
            reconstructed_original_bytes=b"",
            compressed_payload_preserved=True,
            decoded_for_original_reader=False,
            reason=bounds_code,
            evidence_ids=(RAWZOR_METADATA_VALIDATE_SOURCE,),
        )
    try:
        decoded_payload = bz2.decompress(compressed_payload)
    except OSError:
        return RawzorMetadataPayloadPlan(
            compressed_byte_range_start=compressed_start,
            compressed_byte_range_end=compressed_end,
            compressed_metadata_payload=compressed_payload,
            decoded_metadata_payload=b"",
            reconstructed_original_bytes=b"",
            compressed_payload_preserved=True,
            decoded_for_original_reader=False,
            reason="metadata_uncompress_error",
            evidence_ids=(RAWZOR_BZIP2_DECODE_SOURCE, RAWZOR_BZIP2_REQUIRE_SOURCE),
        )
    if len(decoded_payload) != metadata_header.original_metadata_size:
        return RawzorMetadataPayloadPlan(
            compressed_byte_range_start=compressed_start,
            compressed_byte_range_end=compressed_end,
            compressed_metadata_payload=compressed_payload,
            decoded_metadata_payload=decoded_payload,
            reconstructed_original_bytes=b"",
            compressed_payload_preserved=True,
            decoded_for_original_reader=False,
            reason="metadata_uncompress_error",
            evidence_ids=(RAWZOR_BZIP2_DECODE_SOURCE,),
        )
    reconstructed = reassemble_original_metadata(header, metadata_header, decoded_payload)
    return RawzorMetadataPayloadPlan(
        compressed_byte_range_start=compressed_start,
        compressed_byte_range_end=compressed_end,
        compressed_metadata_payload=compressed_payload,
        decoded_metadata_payload=decoded_payload,
        reconstructed_original_bytes=reconstructed,
        compressed_payload_preserved=True,
        decoded_for_original_reader=True,
        reason=None,
        evidence_ids=(RAWZOR_BZIP2_DECODE_SOURCE, RAWZOR_REASSEMBLY_SOURCE),
    )


def empty_payload_plan(
    compressed_start: int | None,
    compressed_end: int | None,
    evidence_ids: tuple[str, ...],
) -> RawzorMetadataPayloadPlan:
    return RawzorMetadataPayloadPlan(
        compressed_byte_range_start=compressed_start,
        compressed_byte_range_end=compressed_end,
        compressed_metadata_payload=b"",
        decoded_metadata_payload=b"",
        reconstructed_original_bytes=b"",
        compressed_payload_preserved=False,
        decoded_for_original_reader=False,
        reason=None,
        evidence_ids=evidence_ids,
    )


def build_original_file_type_plan(
    metadata_payload: RawzorMetadataPayloadPlan,
) -> RawzorOriginalFileTypePlan:
    detected = (
        detect_original_file_type(metadata_payload.reconstructed_original_bytes)
        if metadata_payload.decoded_for_original_reader
        else None
    )
    return RawzorOriginalFileTypePlan(
        delegated_to_original_reader=metadata_payload.decoded_for_original_reader,
        detected_original_file_type=detected,
        original_file_type_tag=detected or "Unknown",
        rwz_file_type_operation="override_file_type_rwz" if detected else "set_file_type_rwz",
        evidence_ids=(RAWZOR_REASSEMBLY_SOURCE, RAWZOR_ORIGINAL_TYPE_SOURCE),
    )


def build_actions(
    header: RawzorHeaderPlan,
    metadata_header: RawzorMetadataHeaderPlan,
    metadata_payload: RawzorMetadataPayloadPlan,
    rewrite_request: RawzorMetadataRewriteRequest | None,
) -> tuple[RawzorActionPlan, ...]:
    actions: list[RawzorActionPlan] = [
        RawzorActionPlan(
            kind="validate_rawzor_header",
            byte_range_start=0,
            byte_range_end=min(RAWZOR_HEADER_SIZE, header.actual_rwz_size),
            input_payload_length=RAWZOR_HEADER_SIZE,
            planned_payload_length=RAWZOR_HEADER_SIZE,
            reason="Validate the fixed Rawzor signature and little-endian header layout.",
            evidence_ids=(RAWZOR_HEADER_SOURCE,),
        ),
        RawzorActionPlan(
            kind="expose_rawzor_versions",
            byte_range_start=6,
            byte_range_end=10,
            input_payload_length=4 if header.required_sdk_version_raw is not None else None,
            planned_payload_length=4 if header.required_sdk_version_raw is not None else None,
            reason="Expose RawzorRequiredVersion and RawzorCreatorVersion using Rawzor.pm scaling.",
            evidence_ids=(RAWZOR_HEADER_SOURCE, RAWZOR_MAIN_TABLE_SOURCE),
        ),
        RawzorActionPlan(
            kind="expose_rawzor_sizes",
            byte_range_start=10,
            byte_range_end=26,
            input_payload_length=16 if header.declared_rwz_size is not None else None,
            planned_payload_length=16 if header.declared_rwz_size is not None else None,
            reason="Expose RWZ size, original file size, and compression factor.",
            evidence_ids=(RAWZOR_HEADER_SOURCE, RAWZOR_MAIN_TABLE_SOURCE),
        ),
    ]
    if metadata_header.was_read:
        metadata_offset = required_int(metadata_header.metadata_offset)
        actions.append(
            RawzorActionPlan(
                kind="read_metadata_header",
                byte_range_start=metadata_offset,
                byte_range_end=metadata_offset + RAWZOR_METADATA_HEADER_SIZE,
                input_payload_length=RAWZOR_METADATA_HEADER_SIZE,
                planned_payload_length=RAWZOR_METADATA_HEADER_SIZE,
                reason="Read the Rawzor metadata section header before any bzip2 decode.",
                evidence_ids=metadata_header.evidence_ids,
            )
        )
    if metadata_payload.compressed_byte_range_start is not None:
        actions.append(
            RawzorActionPlan(
                kind="preserve_compressed_metadata",
                byte_range_start=metadata_payload.compressed_byte_range_start,
                byte_range_end=metadata_payload.compressed_byte_range_end,
                input_payload_length=len(metadata_payload.compressed_metadata_payload),
                planned_payload_length=len(metadata_payload.compressed_metadata_payload),
                reason="Preserve the exact compressed bzip2 metadata bytes in the RWZ container.",
                evidence_ids=(RAWZOR_METADATA_VALIDATE_SOURCE, RAWZOR_READ_ONLY_SOURCE),
            )
        )
    if metadata_payload.decoded_for_original_reader:
        actions.extend(
            (
                RawzorActionPlan(
                    kind="decode_metadata_for_original_reader",
                    byte_range_start=metadata_payload.compressed_byte_range_start,
                    byte_range_end=metadata_payload.compressed_byte_range_end,
                    input_payload_length=len(metadata_payload.compressed_metadata_payload),
                    planned_payload_length=len(metadata_payload.decoded_metadata_payload),
                    reason=(
                        "Decode bzip2 metadata only as a read-side boundary for original parsing."
                    ),
                    evidence_ids=metadata_payload.evidence_ids,
                ),
                RawzorActionPlan(
                    kind="delegate_original_metadata",
                    byte_range_start=None,
                    byte_range_end=None,
                    input_payload_length=len(metadata_payload.reconstructed_original_bytes),
                    planned_payload_length=len(metadata_payload.reconstructed_original_bytes),
                    reason="Delegate the reconstructed original byte stream to format detection.",
                    evidence_ids=(RAWZOR_REASSEMBLY_SOURCE, RAWZOR_ORIGINAL_TYPE_SOURCE),
                ),
            )
        )
    actions.append(
        RawzorActionPlan(
            kind="set_original_file_type",
            byte_range_start=None,
            byte_range_end=None,
            input_payload_length=None,
            planned_payload_length=None,
            reason="Set OriginalFileType from delegated detection or Unknown, then mark RWZ.",
            evidence_ids=(RAWZOR_ORIGINAL_TYPE_SOURCE,),
        )
    )
    if rewrite_request is not None and rewrite_requested(rewrite_request):
        planned_length = (
            0
            if rewrite_request.delete_metadata
            else len(rewrite_request.replacement_metadata_payload or b"")
        )
        actions.append(
            RawzorActionPlan(
                kind="plan_metadata_rewrite",
                byte_range_start=metadata_payload.compressed_byte_range_start,
                byte_range_end=metadata_payload.compressed_byte_range_end,
                input_payload_length=len(metadata_payload.compressed_metadata_payload),
                planned_payload_length=planned_length,
                reason="Record the requested metadata change while keeping RWZ emission gated.",
                evidence_ids=(RAWZOR_READ_ONLY_SOURCE,),
            )
        )
    else:
        actions.append(
            RawzorActionPlan(
                kind="no_metadata_mutation",
                byte_range_start=None,
                byte_range_end=None,
                input_payload_length=None,
                planned_payload_length=None,
                reason="No RWZ metadata mutation was requested.",
                evidence_ids=(RAWZOR_READ_ONLY_SOURCE,),
            )
        )
    return tuple(actions)


def build_responsibilities() -> tuple[RawzorResponsibilityPlan, ...]:
    return (
        RawzorResponsibilityPlan(
            concern="signature_header_validation",
            reason="Validate the fixed rawzor signature and header size before parsing fields.",
            evidence_ids=(RAWZOR_HEADER_SOURCE,),
        ),
        RawzorResponsibilityPlan(
            concern="sdk_version_tags",
            reason="Expose required and creator SDK versions with raw-value to version scaling.",
            evidence_ids=(RAWZOR_MAIN_TABLE_SOURCE, RAWZOR_HEADER_SOURCE),
        ),
        RawzorResponsibilityPlan(
            concern="rwz_and_original_size_tags",
            reason=(
                "Expose original size and compute compression factor as original size "
                "over RWZ size."
            ),
            evidence_ids=(RAWZOR_MAIN_TABLE_SOURCE, RAWZOR_HEADER_SOURCE),
        ),
        RawzorResponsibilityPlan(
            concern="metadata_offset_validation",
            reason="Reject offsets above Rawzor.pm's signed 32-bit seek boundary.",
            evidence_ids=(RAWZOR_OFFSET_SOURCE,),
        ),
        RawzorResponsibilityPlan(
            concern="metadata_header_validation",
            reason="Validate metadata section ordering and original metadata size accounting.",
            evidence_ids=(RAWZOR_METADATA_HEADER_SOURCE, RAWZOR_METADATA_VALIDATE_SOURCE),
        ),
        RawzorResponsibilityPlan(
            concern="bzip2_metadata_preservation",
            reason="Keep the exact compressed metadata bytes as the RWZ container payload.",
            evidence_ids=(RAWZOR_METADATA_VALIDATE_SOURCE, RAWZOR_READ_ONLY_SOURCE),
        ),
        RawzorResponsibilityPlan(
            concern="bzip2_decode_boundary",
            reason="Decode bzip2 metadata only to feed the delegated original-file reader.",
            evidence_ids=(RAWZOR_BZIP2_DECODE_SOURCE, RAWZOR_REASSEMBLY_SOURCE),
        ),
        RawzorResponsibilityPlan(
            concern="original_file_type_responsibility",
            reason=(
                "Set OriginalFileType from delegated original parsing or Unknown, then mark RWZ."
            ),
            evidence_ids=(RAWZOR_ORIGINAL_TYPE_SOURCE,),
        ),
        RawzorResponsibilityPlan(
            concern="version_offset_truncation_uncompress_blockers",
            reason="Surface Rawzor.pm's version, offset, truncation, metadata, and bzip2 blockers.",
            evidence_ids=(
                RAWZOR_VERSION_BLOCK_SOURCE,
                RAWZOR_OFFSET_SOURCE,
                RAWZOR_METADATA_HEADER_SOURCE,
                RAWZOR_METADATA_VALIDATE_SOURCE,
                RAWZOR_BZIP2_DECODE_SOURCE,
            ),
        ),
        RawzorResponsibilityPlan(
            concern="unsupported_mutation_gates",
            reason="Gate RWZ mutation because Rawzor.pm only models read-side behavior.",
            evidence_ids=(RAWZOR_READ_ONLY_SOURCE,),
        ),
    )


def validation_gates(
    header: RawzorHeaderPlan,
    version_code: RawzorEmissionGateCode | None,
    offset_code: RawzorEmissionGateCode | None,
    metadata_header: RawzorMetadataHeaderPlan,
    metadata_payload: RawzorMetadataPayloadPlan,
) -> list[RawzorOutputEmissionGate]:
    gates: list[RawzorOutputEmissionGate] = []
    append_reason_gate(
        gates,
        header.reason,
        "Rawzor header validation failed.",
        header.evidence_ids,
    )
    append_reason_gate(
        gates,
        version_code,
        "The Rawzor required SDK version is newer than Rawzor.pm implements.",
        (RAWZOR_VERSION_SOURCE, RAWZOR_VERSION_BLOCK_SOURCE),
    )
    append_reason_gate(
        gates,
        offset_code,
        "The Rawzor metadata offset exceeds Rawzor.pm's supported boundary.",
        (RAWZOR_OFFSET_SOURCE,),
    )
    append_reason_gate(
        gates,
        metadata_header.reason,
        "The Rawzor metadata header could not be read.",
        metadata_header.evidence_ids,
    )
    append_reason_gate(
        gates,
        metadata_payload.reason,
        "The Rawzor compressed metadata boundary could not be decoded.",
        metadata_payload.evidence_ids,
    )
    return gates


def rewrite_gates(
    rewrite_request: RawzorMetadataRewriteRequest,
) -> tuple[RawzorOutputEmissionGate, ...]:
    planned_length = (
        0
        if rewrite_request.delete_metadata
        else len(rewrite_request.replacement_metadata_payload or b"")
    )
    return (
        RawzorOutputEmissionGate(
            code="rawzor_metadata_rewrite_requires_full_rebuild",
            reason=(
                "Changing Rawzor metadata requires rebuilding the compressed metadata side band "
                f"for the planned {planned_length}-byte payload."
            ),
            evidence_ids=(RAWZOR_METADATA_VALIDATE_SOURCE, RAWZOR_READ_ONLY_SOURCE),
        ),
        RawzorOutputEmissionGate(
            code="rawzor_header_rewrite_required",
            reason=(
                "Changing Rawzor metadata may require rewriting RWZ size and metadata-size fields."
            ),
            evidence_ids=(RAWZOR_HEADER_SOURCE, RAWZOR_METADATA_HEADER_SOURCE),
        ),
        RawzorOutputEmissionGate(
            code="original_payload_recompression_required",
            reason="RWZ mutation requires Rawzor-compatible recompression of the original payload.",
            evidence_ids=(RAWZOR_REASSEMBLY_SOURCE, RAWZOR_READ_ONLY_SOURCE),
        ),
    )


def non_mutating_default_gates() -> tuple[RawzorOutputEmissionGate, ...]:
    return (
        RawzorOutputEmissionGate(
            code="planner_is_non_mutating",
            reason="Rawzor transaction plans do not mutate bytes.",
            evidence_ids=(RAWZOR_READ_ONLY_SOURCE,),
        ),
        RawzorOutputEmissionGate(
            code="full_rawzor_writer_not_implemented",
            reason="No full RWZ writer is implemented for recompression and header updates.",
            evidence_ids=(RAWZOR_READ_ONLY_SOURCE,),
        ),
    )


def required_version_gate(header: RawzorHeaderPlan) -> RawzorEmissionGateCode | None:
    if (
        header.required_sdk_version_raw is not None
        and header.required_sdk_version_raw > RAWZOR_IMPLEMENTED_REQUIRED_VERSION
    ):
        return "unsupported_required_version"
    return None


def metadata_offset_gate(header: RawzorHeaderPlan) -> RawzorEmissionGateCode | None:
    if header.metadata_offset is not None and header.metadata_offset > RAWZOR_MAX_METADATA_OFFSET:
        return "bad_metadata_offset"
    return None


def metadata_bounds_gate(
    header: RawzorHeaderPlan,
    metadata_header: RawzorMetadataHeaderPlan,
) -> RawzorEmissionGateCode | None:
    if (
        header.original_file_size is None
        or metadata_header.section0_end is None
        or metadata_header.section1_start is None
        or metadata_header.section1_end is None
        or metadata_header.section2_start is None
        or metadata_header.original_metadata_size is None
    ):
        return "metadata_header_bounds_mismatch"
    if not (
        metadata_header.section0_end
        <= metadata_header.section1_start
        <= metadata_header.section1_end
        <= metadata_header.section2_start
        <= header.original_file_size
    ):
        return "metadata_header_bounds_mismatch"
    expected_size = (
        metadata_header.section0_end
        + (metadata_header.section1_end - metadata_header.section1_start)
        + (header.original_file_size - metadata_header.section2_start)
    )
    if expected_size != metadata_header.original_metadata_size:
        return "metadata_header_bounds_mismatch"
    return None


def reassemble_original_metadata(
    header: RawzorHeaderPlan,
    metadata_header: RawzorMetadataHeaderPlan,
    decoded_payload: bytes,
) -> bytes:
    section0_end = required_int(metadata_header.section0_end)
    section1_start = required_int(metadata_header.section1_start)
    section1_end = required_int(metadata_header.section1_end)
    section2_start = required_int(metadata_header.section2_start)
    original_file_size = required_int(header.original_file_size)
    section1_length = section1_end - section1_start
    section2_length = original_file_size - section2_start
    section0 = decoded_payload[:section0_end]
    section1_offset = section0_end
    section2_offset = section1_offset + section1_length
    section1 = decoded_payload[section1_offset:section2_offset]
    section2 = decoded_payload[section2_offset : section2_offset + section2_length]
    return (
        section0
        + (b"\x00" * (section1_start - section0_end))
        + section1
        + (b"\x00" * (section2_start - section1_end))
        + section2
    )


def detect_original_file_type(reconstructed: bytes) -> str | None:
    if reconstructed.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if reconstructed.startswith(b"II*\x00") or reconstructed.startswith(b"MM\x00*"):
        return "TIFF"
    if reconstructed.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if reconstructed.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if reconstructed.startswith(b"%PDF-"):
        return "PDF"
    return None


def rewrite_requested(rewrite_request: RawzorMetadataRewriteRequest) -> bool:
    return (
        rewrite_request.delete_metadata or rewrite_request.replacement_metadata_payload is not None
    )


def append_reason_gate(
    gates: list[RawzorOutputEmissionGate],
    code: RawzorEmissionGateCode | None,
    reason: str,
    evidence_ids: tuple[str, ...],
) -> None:
    if code is None:
        return
    gates.append(
        RawzorOutputEmissionGate(
            code=code,
            reason=reason,
            evidence_ids=evidence_ids,
        )
    )


def any_validation_gate(gates: list[RawzorOutputEmissionGate]) -> bool:
    validation_codes = {
        "truncated_rawzor_header",
        "unsupported_rawzor_signature",
        "unsupported_required_version",
        "bad_metadata_offset",
        "metadata_header_truncated",
        "metadata_payload_truncated",
        "metadata_header_bounds_mismatch",
        "metadata_uncompress_error",
    }
    return any(gate.code in validation_codes for gate in gates)


def version_number(raw_value: int | None) -> float | None:
    if raw_value is None:
        return None
    return raw_value / 100


def required_int(value: int | None) -> int:
    if value is None:
        raise ValueError("Expected Rawzor metadata field to be present after validation")
    return value


def read_u16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def read_u64le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little")


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


def unique_gates(
    gates: tuple[RawzorOutputEmissionGate, ...],
) -> tuple[RawzorOutputEmissionGate, ...]:
    seen: set[RawzorEmissionGateCode] = set()
    unique: list[RawzorOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
