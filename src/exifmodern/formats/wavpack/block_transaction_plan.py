"""Source-backed, non-mutating WavPack block transaction planning.

The planner mirrors ExifTool's WavPack read responsibilities: validate the
native WavPack header signature/version, extract ExifTool-modeled audio header
fields, preserve audio blocks by byte extent, and record RIFF/APE/ID3
delegation facts without rewriting bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

WAVPACK_SIGNATURE = b"wvpk"
WAVPACK_BLOCK_HEADER_SIZE = 32
WAVPACK_BLOCK_SIZE_FIELD_ADJUSTMENT = 8
WAVPACK_MIN_DECLARED_BLOCK_SIZE = WAVPACK_BLOCK_HEADER_SIZE - WAVPACK_BLOCK_SIZE_FIELD_ADJUSTMENT
WAVPACK_VERSION_LOW_BYTES = frozenset((0x02, 0x10))
WAVPACK_VERSION_HIGH_BYTE = 0x04
WAVPACK_UNKNOWN_TOTAL_SAMPLES = 0xFFFFFFFF

APE_DESCRIPTOR_SIZE = 32
APE_SIGNATURE = b"APETAGEX"
ID3V1_TRAILER_SIZE = 128
ID3V1_MARKER = b"TAG"
ID3V2_MARKER = b"ID3"

_SAMPLE_RATES: dict[int, int | None] = {
    0: 6000,
    1: 8000,
    2: 9600,
    3: 11025,
    4: 12000,
    5: 16000,
    6: 22050,
    7: 24000,
    8: 32000,
    9: 44100,
    10: 48000,
    11: 64000,
    12: 88200,
    13: 96000,
    14: 192000,
    15: None,
}

type WavPackPlanStatus = Literal["planned", "unsupported"]
type WavPackAudioType = Literal["stereo", "mono"]
type WavPackCompression = Literal["lossless", "hybrid"]
type WavPackDataFormat = Literal["integer", "floating_point"]
type WavPackBlockActionKind = Literal["preserve_audio_block"]
type WavPackEmissionGateCode = Literal[
    "truncated_wavpack_header",
    "unsupported_wavpack_signature",
    "unsupported_wavpack_version",
    "wavpack_block_size_smaller_than_header",
    "truncated_wavpack_block_header",
    "truncated_wavpack_block_payload",
    "wavpack_rewrite_not_implemented",
    "wavpack_identity_emission_not_requested",
    "wavpack_planner_is_non_mutating",
]

WAVPACK_PM_SOURCE_PATH = "lib/Image/ExifTool/WavPack.pm"
APE_PM_SOURCE_PATH = "lib/Image/ExifTool/APE.pm"

WAVPACK_HEADER_VALIDATION_SOURCE = "wavpack.header.validation"
WAVPACK_AUDIO_FIELDS_SOURCE = "wavpack.audio.fields"
WAVPACK_BLOCK_PRESERVATION_SOURCE = "wavpack.block.preservation"
WAVPACK_METADATA_NOTES_SOURCE = "wavpack.metadata.notes"
WAVPACK_DELEGATION_SOURCE = "wavpack.delegation"
APE_ID3_PRECHECK_SOURCE = "ape.id3.precheck"
APE_ID3V1_FOOTER_SOURCE = "ape.id3v1.footer"
WAVPACK_NON_MUTATING_SOURCE = "wavpack.non.mutating"

WAVPACK_BLOCK_TRANSACTION_SOURCES = (
    WAVPACK_HEADER_VALIDATION_SOURCE,
    WAVPACK_AUDIO_FIELDS_SOURCE,
    WAVPACK_BLOCK_PRESERVATION_SOURCE,
    WAVPACK_METADATA_NOTES_SOURCE,
    WAVPACK_DELEGATION_SOURCE,
    APE_ID3_PRECHECK_SOURCE,
    APE_ID3V1_FOOTER_SOURCE,
    WAVPACK_NON_MUTATING_SOURCE,
)


@dataclass(frozen=True)
class WavPackPlanIssue:
    code: WavPackEmissionGateCode
    message: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WavPackEmissionGate:
    code: WavPackEmissionGateCode
    passed: bool
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WavPackRewriteRequest:
    requested_audio_block_payload: bytes | None = None
    requested_apev2_payload: bytes | None = None
    requested_id3_payload: bytes | None = None
    delete_existing_tags: bool = False

    @property
    def requested(self) -> bool:
        return (
            self.requested_audio_block_payload is not None
            or self.requested_apev2_payload is not None
            or self.requested_id3_payload is not None
            or self.delete_existing_tags
        )

    @property
    def requested_operations(self) -> tuple[str, ...]:
        operations: list[str] = []
        if self.requested_audio_block_payload is not None:
            operations.append("replace_audio_block_payload")
        if self.requested_apev2_payload is not None:
            operations.append("write_apev2_payload")
        if self.requested_id3_payload is not None:
            operations.append("write_id3_payload")
        if self.delete_existing_tags:
            operations.append("delete_existing_tags")
        return tuple(operations)


@dataclass(frozen=True)
class WavPackHeaderValidationPlan:
    signature: bytes
    declared_block_size: int | None
    version_raw: int | None
    version_low_byte: int | None
    version_high_byte: int | None
    version_pattern_valid: bool
    is_wavpack: bool
    issue: WavPackPlanIssue | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WavPackAudioHeaderPlan:
    bytes_per_sample: int
    audio_type: WavPackAudioType
    channel_count: int
    compression: WavPackCompression
    data_format: WavPackDataFormat
    sample_rate_code: int
    sample_rate_hz: int | None
    sample_rate_label: str
    total_samples: int | None
    block_index: int
    block_samples: int
    duration_seconds: float | None
    flags: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WavPackBlockPlan:
    index: int
    block_start_offset: int
    header_offset: int
    payload_offset: int
    declared_block_size: int
    encoded_length: int
    payload_length: int
    block_end_offset: int
    version_raw: int
    track_number: int
    index_number: int
    total_samples_raw: int
    block_index: int
    block_samples: int
    flags: int
    crc: int
    audio_header: WavPackAudioHeaderPlan
    evidence_ids: tuple[str, ...]

    @property
    def action_kind(self) -> WavPackBlockActionKind:
        return "preserve_audio_block"


@dataclass(frozen=True)
class WavPackAudioPreservationPlan:
    audio_block_count: int
    preserved_block_indices: tuple[int, ...]
    audio_data_size: int
    tag_tail_offset: int
    tag_tail_size: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WavPackTagDelegationPlan:
    riff_delegation_attempted: bool
    ape_delegation_attempted: bool
    ape_delegation_checks_id3: bool
    leading_id3v2_present: bool
    trailing_id3v1_present: bool
    apev2_header_at_tag_tail: bool
    trailing_apev2_footer_present: bool
    ape_footer_search_end_offset: int
    tag_tail_offset: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WavPackRewritePlan:
    requested_operations: tuple[str, ...]
    blockers: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class WavPackBlockTransactionPlan:
    status: WavPackPlanStatus
    input_size: int
    header: WavPackHeaderValidationPlan
    blocks: tuple[WavPackBlockPlan, ...]
    audio_preservation: WavPackAudioPreservationPlan
    tag_delegation: WavPackTagDelegationPlan
    rewrite_plan: WavPackRewritePlan
    output_emission_gates: tuple[WavPackEmissionGate, ...]
    output_data: bytes | None
    evidence_ids: tuple[str, ...] = WAVPACK_BLOCK_TRANSACTION_SOURCES

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.output_data is not None and all(
            gate.passed for gate in self.output_emission_gates
        )

    @property
    def failed_gates(self) -> tuple[WavPackEmissionGate, ...]:
        return tuple(gate for gate in self.output_emission_gates if not gate.passed)

    @property
    def audio_header(self) -> WavPackAudioHeaderPlan | None:
        if not self.blocks:
            return None
        return self.blocks[0].audio_header

    def emit(self) -> bytes:
        if self.output_data is None or not self.can_emit_output:
            failed = ", ".join(gate.code for gate in self.failed_gates)
            raise WavPackBlockTransactionBlocked(
                f"WavPack block transaction output is gated: {failed}"
            )
        return self.output_data


class WavPackBlockTransactionBlocked(ValueError):
    """Raised when a planned WavPack transaction cannot emit bytes."""


def build_wavpack_block_transaction_plan(
    data: bytes,
    *,
    rewrite_request: WavPackRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> WavPackBlockTransactionPlan:
    request = rewrite_request or WavPackRewriteRequest()
    header = inspect_wavpack_header(data)
    blocks: tuple[WavPackBlockPlan, ...] = ()
    block_gates: tuple[WavPackEmissionGate, ...] = ()
    gates: list[WavPackEmissionGate] = []

    if header.issue is not None:
        gates.append(
            WavPackEmissionGate(
                code=header.issue.code,
                passed=False,
                reason=header.issue.message,
                evidence_ids=header.issue.evidence_ids,
            )
        )
        tag_tail_offset = 0
    else:
        blocks, block_gates = enumerate_wavpack_blocks(data)
        gates.extend(block_gates)
        tag_tail_offset = blocks[-1].block_end_offset if blocks else 0

    audio_preservation = build_audio_preservation_plan(blocks, len(data), tag_tail_offset)
    tag_delegation = inspect_tag_delegation(data, tag_tail_offset)
    rewrite_plan = plan_wavpack_rewrite(request)
    for blocker in rewrite_plan.blockers:
        gates.append(
            WavPackEmissionGate(
                code="wavpack_rewrite_not_implemented",
                passed=False,
                reason=blocker,
                evidence_ids=rewrite_plan.evidence_ids,
            )
        )

    if not allow_output_emission:
        gates.append(
            WavPackEmissionGate(
                code="wavpack_identity_emission_not_requested",
                passed=False,
                reason=(
                    "WavPack block transaction plans are non-mutating; opt in to "
                    "identity-only emission explicitly."
                ),
                evidence_ids=(WAVPACK_NON_MUTATING_SOURCE,),
            )
        )
        output_data = None
    elif gates:
        output_data = None
    else:
        gates.append(
            WavPackEmissionGate(
                code="wavpack_planner_is_non_mutating",
                passed=True,
                reason=(
                    "Explicit identity emission returns the original WavPack byte sequence only."
                ),
                evidence_ids=(WAVPACK_NON_MUTATING_SOURCE,),
            )
        )
        output_data = data

    status: WavPackPlanStatus = (
        "unsupported" if header.issue is not None or block_gates else "planned"
    )
    sources = unique_sources(
        (
            *WAVPACK_BLOCK_TRANSACTION_SOURCES,
            *header.evidence_ids,
            *(source for block in blocks for source in block.evidence_ids),
            *audio_preservation.evidence_ids,
            *tag_delegation.evidence_ids,
            *rewrite_plan.evidence_ids,
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return WavPackBlockTransactionPlan(
        status=status,
        input_size=len(data),
        header=header,
        blocks=blocks,
        audio_preservation=audio_preservation,
        tag_delegation=tag_delegation,
        rewrite_plan=rewrite_plan,
        output_emission_gates=unique_gates(tuple(gates)),
        output_data=output_data,
        evidence_ids=sources,
    )


def inspect_wavpack_header(data: bytes) -> WavPackHeaderValidationPlan:
    signature = data[:4]
    declared_block_size = (
        int.from_bytes(data[4:8], "little") if len(data) >= WAVPACK_BLOCK_HEADER_SIZE else None
    )
    version_low = data[8] if len(data) >= WAVPACK_BLOCK_HEADER_SIZE else None
    version_high = data[9] if len(data) >= WAVPACK_BLOCK_HEADER_SIZE else None
    version_raw = (
        int.from_bytes(data[8:10], "little") if len(data) >= WAVPACK_BLOCK_HEADER_SIZE else None
    )
    version_valid = (
        version_low in WAVPACK_VERSION_LOW_BYTES and version_high == WAVPACK_VERSION_HIGH_BYTE
    )
    issue: WavPackPlanIssue | None = None
    if len(data) < WAVPACK_BLOCK_HEADER_SIZE:
        issue = WavPackPlanIssue(
            code="truncated_wavpack_header",
            message="Input ended before ExifTool's 32-byte WavPack header probe.",
            evidence_ids=(WAVPACK_HEADER_VALIDATION_SOURCE,),
        )
    elif signature != WAVPACK_SIGNATURE:
        issue = WavPackPlanIssue(
            code="unsupported_wavpack_signature",
            message="Input does not start with the native WavPack wvpk signature.",
            evidence_ids=(WAVPACK_HEADER_VALIDATION_SOURCE,),
        )
    elif not version_valid:
        issue = WavPackPlanIssue(
            code="unsupported_wavpack_version",
            message="Input does not match ExifTool's accepted WavPack version byte pattern.",
            evidence_ids=(WAVPACK_HEADER_VALIDATION_SOURCE,),
        )
    return WavPackHeaderValidationPlan(
        signature=signature,
        declared_block_size=declared_block_size,
        version_raw=version_raw,
        version_low_byte=version_low,
        version_high_byte=version_high,
        version_pattern_valid=version_valid,
        is_wavpack=issue is None,
        issue=issue,
        evidence_ids=(WAVPACK_HEADER_VALIDATION_SOURCE,),
    )


def enumerate_wavpack_blocks(
    data: bytes,
) -> tuple[tuple[WavPackBlockPlan, ...], tuple[WavPackEmissionGate, ...]]:
    blocks: list[WavPackBlockPlan] = []
    gates: list[WavPackEmissionGate] = []
    offset = 0
    while offset < len(data):
        if data[offset : offset + 4] != WAVPACK_SIGNATURE:
            break
        if len(data) - offset < WAVPACK_BLOCK_HEADER_SIZE:
            gates.append(
                WavPackEmissionGate(
                    code="truncated_wavpack_block_header",
                    passed=False,
                    reason="A WavPack block signature was found without a complete 32-byte header.",
                    evidence_ids=(WAVPACK_BLOCK_PRESERVATION_SOURCE,),
                )
            )
            break
        block_or_gate = inspect_wavpack_block(data, offset, len(blocks))
        if isinstance(block_or_gate, WavPackEmissionGate):
            gates.append(block_or_gate)
            break
        blocks.append(block_or_gate)
        offset = block_or_gate.block_end_offset
    return tuple(blocks), tuple(gates)


def inspect_wavpack_block(
    data: bytes,
    offset: int,
    index: int,
) -> WavPackBlockPlan | WavPackEmissionGate:
    declared_block_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
    if declared_block_size < WAVPACK_MIN_DECLARED_BLOCK_SIZE:
        return WavPackEmissionGate(
            code="wavpack_block_size_smaller_than_header",
            passed=False,
            reason="The WavPack block size field is smaller than the remaining header bytes.",
            evidence_ids=(WAVPACK_BLOCK_PRESERVATION_SOURCE,),
        )
    encoded_length = declared_block_size + WAVPACK_BLOCK_SIZE_FIELD_ADJUSTMENT
    block_end = offset + encoded_length
    if block_end > len(data):
        return WavPackEmissionGate(
            code="truncated_wavpack_block_payload",
            passed=False,
            reason="A WavPack block declares bytes beyond the available input.",
            evidence_ids=(WAVPACK_BLOCK_PRESERVATION_SOURCE,),
        )
    version_low = data[offset + 8]
    version_high = data[offset + 9]
    if version_low not in WAVPACK_VERSION_LOW_BYTES or version_high != WAVPACK_VERSION_HIGH_BYTE:
        return WavPackEmissionGate(
            code="unsupported_wavpack_version",
            passed=False,
            reason="A WavPack block does not match ExifTool's accepted version byte pattern.",
            evidence_ids=(WAVPACK_HEADER_VALIDATION_SOURCE,),
        )
    version_raw = int.from_bytes(data[offset + 8 : offset + 10], "little")
    total_samples = int.from_bytes(data[offset + 12 : offset + 16], "little")
    block_index = int.from_bytes(data[offset + 16 : offset + 20], "little")
    block_samples = int.from_bytes(data[offset + 20 : offset + 24], "little")
    flags = int.from_bytes(data[offset + 24 : offset + 28], "little")
    audio_header = build_audio_header_plan(total_samples, block_index, block_samples, flags)
    return WavPackBlockPlan(
        index=index,
        block_start_offset=offset,
        header_offset=offset,
        payload_offset=offset + WAVPACK_BLOCK_HEADER_SIZE,
        declared_block_size=declared_block_size,
        encoded_length=encoded_length,
        payload_length=encoded_length - WAVPACK_BLOCK_HEADER_SIZE,
        block_end_offset=block_end,
        version_raw=version_raw,
        track_number=data[offset + 10],
        index_number=data[offset + 11],
        total_samples_raw=total_samples,
        block_index=block_index,
        block_samples=block_samples,
        flags=flags,
        crc=int.from_bytes(data[offset + 28 : offset + 32], "little"),
        audio_header=audio_header,
        evidence_ids=(WAVPACK_HEADER_VALIDATION_SOURCE, WAVPACK_BLOCK_PRESERVATION_SOURCE),
    )


def build_audio_header_plan(
    total_samples_raw: int, block_index: int, block_samples: int, flags: int
) -> WavPackAudioHeaderPlan:
    sample_rate_code = (flags & 0x07800000) >> 23
    sample_rate_hz = _SAMPLE_RATES[sample_rate_code]
    total_samples = (
        None if total_samples_raw == WAVPACK_UNKNOWN_TOTAL_SAMPLES else total_samples_raw
    )
    duration_seconds = (
        total_samples / sample_rate_hz
        if total_samples is not None and sample_rate_hz is not None
        else None
    )
    is_mono = bool(flags & 0x04)
    return WavPackAudioHeaderPlan(
        bytes_per_sample=(flags & 0x03) + 1,
        audio_type="mono" if is_mono else "stereo",
        channel_count=1 if is_mono else 2,
        compression="hybrid" if flags & 0x08 else "lossless",
        data_format="floating_point" if flags & 0x80 else "integer",
        sample_rate_code=sample_rate_code,
        sample_rate_hz=sample_rate_hz,
        sample_rate_label="Custom" if sample_rate_hz is None else str(sample_rate_hz),
        total_samples=total_samples,
        block_index=block_index,
        block_samples=block_samples,
        duration_seconds=duration_seconds,
        flags=flags,
        evidence_ids=(WAVPACK_AUDIO_FIELDS_SOURCE,),
    )


def build_audio_preservation_plan(
    blocks: tuple[WavPackBlockPlan, ...], input_size: int, tag_tail_offset: int
) -> WavPackAudioPreservationPlan:
    return WavPackAudioPreservationPlan(
        audio_block_count=len(blocks),
        preserved_block_indices=tuple(block.index for block in blocks),
        audio_data_size=sum(block.encoded_length for block in blocks),
        tag_tail_offset=tag_tail_offset,
        tag_tail_size=input_size - tag_tail_offset,
        evidence_ids=(WAVPACK_BLOCK_PRESERVATION_SOURCE,),
    )


def inspect_tag_delegation(data: bytes, tag_tail_offset: int) -> WavPackTagDelegationPlan:
    trailing_id3v1 = len(data) >= ID3V1_TRAILER_SIZE and data[-ID3V1_TRAILER_SIZE:].startswith(
        ID3V1_MARKER
    )
    footer_search_end = len(data) - ID3V1_TRAILER_SIZE if trailing_id3v1 else len(data)
    footer_offset = footer_search_end - APE_DESCRIPTOR_SIZE
    trailing_apev2_footer = (
        footer_offset >= tag_tail_offset
        and data[footer_offset : footer_offset + len(APE_SIGNATURE)] == APE_SIGNATURE
    )
    apev2_header_at_tail = data[tag_tail_offset : tag_tail_offset + len(APE_SIGNATURE)] == (
        APE_SIGNATURE
    )
    return WavPackTagDelegationPlan(
        riff_delegation_attempted=True,
        ape_delegation_attempted=True,
        ape_delegation_checks_id3=True,
        leading_id3v2_present=data.startswith(ID3V2_MARKER),
        trailing_id3v1_present=trailing_id3v1,
        apev2_header_at_tag_tail=apev2_header_at_tail,
        trailing_apev2_footer_present=trailing_apev2_footer,
        ape_footer_search_end_offset=footer_search_end,
        tag_tail_offset=tag_tail_offset,
        evidence_ids=(
            WAVPACK_METADATA_NOTES_SOURCE,
            WAVPACK_DELEGATION_SOURCE,
            APE_ID3_PRECHECK_SOURCE,
            APE_ID3V1_FOOTER_SOURCE,
        ),
    )


def plan_wavpack_rewrite(request: WavPackRewriteRequest) -> WavPackRewritePlan:
    blockers = tuple(
        f"{operation} is delegated to a future WavPack transaction writer"
        for operation in request.requested_operations
    )
    return WavPackRewritePlan(
        requested_operations=request.requested_operations,
        blockers=blockers,
        evidence_ids=(
            WAVPACK_BLOCK_PRESERVATION_SOURCE,
            WAVPACK_DELEGATION_SOURCE,
            WAVPACK_NON_MUTATING_SOURCE,
        ),
    )


def unique_sources(references: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for reference in references:
        key = reference
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return tuple(unique)


def unique_gates(gates: tuple[WavPackEmissionGate, ...]) -> tuple[WavPackEmissionGate, ...]:
    unique: list[WavPackEmissionGate] = []
    seen: set[tuple[WavPackEmissionGateCode, bool, str]] = set()
    for gate in gates:
        key = (gate.code, gate.passed, gate.reason)
        if key in seen:
            continue
        seen.add(key)
        unique.append(gate)
    return tuple(unique)
