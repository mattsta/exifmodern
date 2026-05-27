"""Source-backed Musepack/MPC metadata transaction planning.

ExifTool's MPC reader validates a 32-byte ``MP+`` header, extracts audio
properties only for stream version 7 via the shared FLAC bitstream processor,
checks leading ID3 before the MPC signature, and checks for a trailing APE tag
after audio parsing. This planner mirrors those read responsibilities and keeps
byte emission behind explicit gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MPC_HEADER_SIZE = 32
MPC_SIGNATURE = b"MP+"
ID3V2_HEADER_SIZE = 10
ID3V1_TRAILER_SIZE = 128
APE_DESCRIPTOR_SIZE = 32
ID3V2_MARKER = b"ID3"
ID3V1_MARKER = b"TAG"
APE_SIGNATURE = b"APETAGEX"

type MpcPlanStatus = Literal["planned", "unsupported"]
type MpcHeaderStatus = Literal["valid", "invalid_signature", "truncated"]
type MpcTagBoundaryKind = Literal["leading_id3v2", "trailing_ape", "trailing_id3v1"]
type MpcTagDelegate = Literal["ID3::ProcessID3", "APE::ProcessAPE"]
type MpcResponsibilityKind = Literal[
    "stream_version",
    "total_frames",
    "sample_rate",
    "channels",
    "bitrate",
    "quality",
    "max_band",
    "replay_gain",
    "fast_seek",
    "gapless",
    "encoder_version",
]
type MpcEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_mpc_header",
    "unsupported_mpc_signature",
    "invalid_leading_id3v2_size",
    "invalid_trailing_ape_bounds",
    "mpc_metadata_rewrite_not_supported",
    "mpc_audio_payload_rewrite_not_supported",
]
type MpcRewriteBlockerCode = Literal[
    "mpc_metadata_rewrite_not_supported",
    "mpc_audio_payload_rewrite_not_supported",
]

MPC_PM_SOURCE_PATH = "lib/Image/ExifTool/MPC.pm"
FLAC_PM_SOURCE_PATH = "lib/Image/ExifTool/FLAC.pm"

MPC_TAG_TABLE_SOURCE = "mpc_audio.tag_table"
MPC_ID3_PREFLIGHT_SOURCE = "mpc_audio.id3_preflight"
MPC_SIGNATURE_SOURCE = "mpc_audio.signature"
MPC_VERSION7_SOURCE = "mpc_audio.version7"
MPC_APE_TRAILER_SOURCE = "mpc_audio.ape_trailer"
MPC_DESCRIPTION_SOURCE = "mpc_audio.description"
FLAC_BITSTREAM_SOURCE = "flac.bitstream.2"
MPC_NON_MUTATING_SOURCE = "mpc_audio.non_mutating"

MPC_TRANSACTION_SOURCES = (
    MPC_TAG_TABLE_SOURCE,
    MPC_ID3_PREFLIGHT_SOURCE,
    MPC_SIGNATURE_SOURCE,
    MPC_VERSION7_SOURCE,
    MPC_APE_TRAILER_SOURCE,
    MPC_DESCRIPTION_SOURCE,
    FLAC_BITSTREAM_SOURCE,
    MPC_NON_MUTATING_SOURCE,
)

MPC_SAMPLE_RATES: dict[int, int] = {
    0: 44100,
    1: 48000,
    2: 37800,
    3: 32000,
}
MPC_QUALITY_LABELS: dict[int, str] = {
    1: "Unstable/Experimental",
    5: "0",
    6: "1",
    7: "2 (Telephone)",
    8: "3 (Thumb)",
    9: "4 (Radio)",
    10: "5 (Standard)",
    11: "6 (Xtreme)",
    12: "7 (Insane)",
    13: "8 (BrainDead)",
    14: "9",
    15: "10",
}


@dataclass(frozen=True)
class MpcAudioRewriteRequest:
    id3v2_payload: bytes | None = None
    ape_payload: bytes | None = None
    audio_payload: bytes | None = None


@dataclass(frozen=True)
class MpcHeaderValidationPlan:
    offset: int
    raw_header: bytes
    status: MpcHeaderStatus
    signature_valid: bool
    stream_version: int | None
    version_audio_fields_supported: bool
    reason: MpcEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpcVersion7AudioPlan:
    available: bool
    total_frames: int | None
    sample_rate_index: int | None
    sample_rate: int | None
    quality_raw: int | None
    quality: str | None
    max_band: int | None
    replay_gain_track_peak: int | None
    replay_gain_track_gain: int | None
    replay_gain_album_peak: int | None
    replay_gain_album_gain: int | None
    fast_seek: bool | None
    gapless: bool | None
    encoder_version_raw: int | None
    encoder_version: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpcTagBoundaryPlan:
    kind: MpcTagBoundaryKind
    offset: int
    end_offset: int
    payload_length: int
    delegated_to: MpcTagDelegate
    preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpcTagCoexistencePlan:
    leading_id3v2_present: bool
    leading_id3v2_end_offset: int
    trailing_ape_present: bool
    trailing_id3v1_present: bool
    audio_payload_end_offset: int
    boundaries: tuple[MpcTagBoundaryPlan, ...]
    reason: MpcEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpcAudioPayloadPreservationPlan:
    offset: int | None
    end_offset: int | None
    payload: bytes
    preserved: bool
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpcAudioResponsibilityPlan:
    kind: MpcResponsibilityKind
    available: bool
    value: int | str | bool | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpcRewriteBlocker:
    code: MpcRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpcOutputEmissionGate:
    code: MpcEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpcAudioTransactionPlan:
    status: MpcPlanStatus
    input_size: int
    tag_coexistence: MpcTagCoexistencePlan
    header: MpcHeaderValidationPlan
    version7_audio: MpcVersion7AudioPlan
    audio_payload_preservation: MpcAudioPayloadPreservationPlan
    responsibilities: tuple[MpcAudioResponsibilityPlan, ...]
    rewrite_blockers: tuple[MpcRewriteBlocker, ...]
    output_emission_gates: tuple[MpcOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"MPC audio transaction output is gated: {gate_codes}")
        return self.original_bytes


def build_mpc_audio_transaction_plan(
    mpc_data: bytes,
    *,
    rewrite_request: MpcAudioRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> MpcAudioTransactionPlan:
    tag_coexistence = build_tag_coexistence_plan(mpc_data)
    header = build_header_validation_plan(mpc_data, tag_coexistence.leading_id3v2_end_offset)
    version7_audio = build_version7_audio_plan(header)
    audio_payload_preservation = build_audio_payload_preservation_plan(
        mpc_data,
        header,
        tag_coexistence,
    )
    responsibilities = build_responsibilities(header, version7_audio)
    rewrite_blockers = build_rewrite_blockers(rewrite_request)
    gates = [
        *_validation_gates(tag_coexistence, header),
        *(_gate_from_rewrite_blocker(blocker) for blocker in rewrite_blockers),
    ]
    if not allow_output_emission:
        gates.append(
            MpcOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason=(
                    "MPC audio transaction plans are non-mutating unless emission is explicit."
                ),
                evidence_ids=(MPC_NON_MUTATING_SOURCE,),
            )
        )
    output_gates = unique_gates(tuple(gates))
    status: MpcPlanStatus = "unsupported" if has_structural_gate(output_gates) else "planned"
    return MpcAudioTransactionPlan(
        status=status,
        input_size=len(mpc_data),
        tag_coexistence=tag_coexistence,
        header=header,
        version7_audio=version7_audio,
        audio_payload_preservation=audio_payload_preservation,
        responsibilities=responsibilities,
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=output_gates,
        evidence_ids=unique_evidence_ids(
            (
                *MPC_TRANSACTION_SOURCES,
                *tag_coexistence.evidence_ids,
                *header.evidence_ids,
                *version7_audio.evidence_ids,
                *audio_payload_preservation.evidence_ids,
                *(source for item in responsibilities for source in item.evidence_ids),
                *(source for blocker in rewrite_blockers for source in blocker.evidence_ids),
                *(source for gate in output_gates for source in gate.evidence_ids),
            )
        ),
        original_bytes=mpc_data,
    )


def build_tag_coexistence_plan(mpc_data: bytes) -> MpcTagCoexistencePlan:
    boundaries: list[MpcTagBoundaryPlan] = []
    leading_end, leading_reason = leading_id3v2_end_offset(mpc_data)
    if leading_end > 0:
        boundaries.append(
            MpcTagBoundaryPlan(
                kind="leading_id3v2",
                offset=0,
                end_offset=leading_end,
                payload_length=leading_end,
                delegated_to="ID3::ProcessID3",
                preserved=True,
                evidence_ids=(MPC_ID3_PREFLIGHT_SOURCE,),
            )
        )

    trailing_id3v1_offset = trailing_id3v1_start_offset(mpc_data)
    search_end = trailing_id3v1_offset if trailing_id3v1_offset is not None else len(mpc_data)
    ape_boundary, ape_reason = trailing_ape_boundary(mpc_data, search_end)
    if ape_boundary is not None:
        boundaries.append(ape_boundary)
        search_end = ape_boundary.offset
    if trailing_id3v1_offset is not None:
        boundaries.append(
            MpcTagBoundaryPlan(
                kind="trailing_id3v1",
                offset=trailing_id3v1_offset,
                end_offset=len(mpc_data),
                payload_length=ID3V1_TRAILER_SIZE,
                delegated_to="ID3::ProcessID3",
                preserved=True,
                evidence_ids=(MPC_ID3_PREFLIGHT_SOURCE, MPC_APE_TRAILER_SOURCE),
            )
        )

    reason = leading_reason or ape_reason
    return MpcTagCoexistencePlan(
        leading_id3v2_present=leading_end > 0,
        leading_id3v2_end_offset=leading_end,
        trailing_ape_present=ape_boundary is not None,
        trailing_id3v1_present=trailing_id3v1_offset is not None,
        audio_payload_end_offset=search_end,
        boundaries=tuple(boundaries),
        reason=reason,
        evidence_ids=unique_evidence_ids(
            (
                MPC_ID3_PREFLIGHT_SOURCE,
                MPC_APE_TRAILER_SOURCE,
                *(source for boundary in boundaries for source in boundary.evidence_ids),
            )
        ),
    )


def leading_id3v2_end_offset(mpc_data: bytes) -> tuple[int, MpcEmissionGateCode | None]:
    if not mpc_data.startswith(ID3V2_MARKER):
        return 0, None
    if len(mpc_data) < ID3V2_HEADER_SIZE:
        return 0, "invalid_leading_id3v2_size"
    size_bytes = mpc_data[6:10]
    if any(byte & 0x80 for byte in size_bytes):
        return 0, "invalid_leading_id3v2_size"
    payload_size = (
        (size_bytes[0] << 21) | (size_bytes[1] << 14) | (size_bytes[2] << 7) | size_bytes[3]
    )
    end_offset = ID3V2_HEADER_SIZE + payload_size
    if end_offset > len(mpc_data):
        return 0, "invalid_leading_id3v2_size"
    return end_offset, None


def trailing_id3v1_start_offset(mpc_data: bytes) -> int | None:
    if len(mpc_data) >= ID3V1_TRAILER_SIZE and mpc_data[-ID3V1_TRAILER_SIZE:].startswith(
        ID3V1_MARKER
    ):
        return len(mpc_data) - ID3V1_TRAILER_SIZE
    return None


def trailing_ape_boundary(
    mpc_data: bytes,
    search_end: int,
) -> tuple[MpcTagBoundaryPlan | None, MpcEmissionGateCode | None]:
    footer_offset = search_end - APE_DESCRIPTOR_SIZE
    if footer_offset < 0 or mpc_data[footer_offset : footer_offset + 8] != APE_SIGNATURE:
        return None, None
    declared_size = read_u32le(mpc_data, footer_offset + 12)
    if declared_size < APE_DESCRIPTOR_SIZE or declared_size > search_end:
        return None, "invalid_trailing_ape_bounds"
    tag_start = search_end - declared_size
    if tag_start < 0:
        return None, "invalid_trailing_ape_bounds"
    return (
        MpcTagBoundaryPlan(
            kind="trailing_ape",
            offset=tag_start,
            end_offset=search_end,
            payload_length=declared_size,
            delegated_to="APE::ProcessAPE",
            preserved=True,
            evidence_ids=(MPC_APE_TRAILER_SOURCE,),
        ),
        None,
    )


def build_header_validation_plan(mpc_data: bytes, header_offset: int) -> MpcHeaderValidationPlan:
    raw_header = mpc_data[header_offset : header_offset + MPC_HEADER_SIZE]
    if len(raw_header) < MPC_HEADER_SIZE:
        return MpcHeaderValidationPlan(
            offset=header_offset,
            raw_header=raw_header,
            status="truncated",
            signature_valid=False,
            stream_version=None,
            version_audio_fields_supported=False,
            reason="truncated_mpc_header",
            evidence_ids=(MPC_SIGNATURE_SOURCE,),
        )
    signature_valid = raw_header.startswith(MPC_SIGNATURE)
    stream_version = raw_header[3] & 0x0F if signature_valid else None
    return MpcHeaderValidationPlan(
        offset=header_offset,
        raw_header=raw_header,
        status="valid" if signature_valid else "invalid_signature",
        signature_valid=signature_valid,
        stream_version=stream_version,
        version_audio_fields_supported=stream_version == 7,
        reason=None if signature_valid else "unsupported_mpc_signature",
        evidence_ids=(MPC_SIGNATURE_SOURCE, MPC_VERSION7_SOURCE),
    )


def build_version7_audio_plan(header: MpcHeaderValidationPlan) -> MpcVersion7AudioPlan:
    if header.status != "valid" or header.stream_version != 7:
        return MpcVersion7AudioPlan(
            available=False,
            total_frames=None,
            sample_rate_index=None,
            sample_rate=None,
            quality_raw=None,
            quality=None,
            max_band=None,
            replay_gain_track_peak=None,
            replay_gain_track_gain=None,
            replay_gain_album_peak=None,
            replay_gain_album_gain=None,
            fast_seek=None,
            gapless=None,
            encoder_version_raw=None,
            encoder_version=None,
            evidence_ids=(MPC_VERSION7_SOURCE,),
        )
    raw_header = header.raw_header
    sample_rate_index = extract_little_endian_bits(raw_header, 80, 81)
    quality_raw = extract_little_endian_bits(raw_header, 84, 87)
    encoder_version_raw = extract_little_endian_bits(raw_header, 216, 223)
    return MpcVersion7AudioPlan(
        available=True,
        total_frames=extract_little_endian_bits(raw_header, 32, 63),
        sample_rate_index=sample_rate_index,
        sample_rate=MPC_SAMPLE_RATES[sample_rate_index],
        quality_raw=quality_raw,
        quality=MPC_QUALITY_LABELS.get(quality_raw),
        max_band=extract_little_endian_bits(raw_header, 88, 93),
        replay_gain_track_peak=extract_little_endian_bits(raw_header, 96, 111),
        replay_gain_track_gain=extract_little_endian_bits(raw_header, 112, 127),
        replay_gain_album_peak=extract_little_endian_bits(raw_header, 128, 143),
        replay_gain_album_gain=extract_little_endian_bits(raw_header, 144, 159),
        fast_seek=extract_little_endian_bits(raw_header, 179, 179) == 1,
        gapless=extract_little_endian_bits(raw_header, 191, 191) == 1,
        encoder_version_raw=encoder_version_raw,
        encoder_version=format_encoder_version(encoder_version_raw),
        evidence_ids=(MPC_TAG_TABLE_SOURCE, MPC_VERSION7_SOURCE, FLAC_BITSTREAM_SOURCE),
    )


def build_audio_payload_preservation_plan(
    mpc_data: bytes,
    header: MpcHeaderValidationPlan,
    tag_coexistence: MpcTagCoexistencePlan,
) -> MpcAudioPayloadPreservationPlan:
    if header.status != "valid":
        return MpcAudioPayloadPreservationPlan(
            offset=None,
            end_offset=None,
            payload=b"",
            preserved=False,
            reason="MPC payload preservation requires a valid 32-byte MP+ header.",
            evidence_ids=(MPC_SIGNATURE_SOURCE,),
        )
    payload_offset = header.offset + MPC_HEADER_SIZE
    payload_end = max(payload_offset, tag_coexistence.audio_payload_end_offset)
    return MpcAudioPayloadPreservationPlan(
        offset=payload_offset,
        end_offset=payload_end,
        payload=mpc_data[payload_offset:payload_end],
        preserved=True,
        reason="Preserve audio frame bytes between the MPC header and trailing tag boundary.",
        evidence_ids=(MPC_SIGNATURE_SOURCE, MPC_APE_TRAILER_SOURCE),
    )


def build_responsibilities(
    header: MpcHeaderValidationPlan,
    audio: MpcVersion7AudioPlan,
) -> tuple[MpcAudioResponsibilityPlan, ...]:
    return (
        MpcAudioResponsibilityPlan(
            kind="stream_version",
            available=header.stream_version is not None,
            value=header.stream_version,
            reason="ProcessMPC derives the stream version from the MP+ header byte.",
            evidence_ids=(MPC_SIGNATURE_SOURCE,),
        ),
        MpcAudioResponsibilityPlan(
            kind="total_frames",
            available=audio.available,
            value=audio.total_frames,
            reason="Version 7 maps Bit032-063 to TotalFrames.",
            evidence_ids=(MPC_TAG_TABLE_SOURCE, FLAC_BITSTREAM_SOURCE),
        ),
        MpcAudioResponsibilityPlan(
            kind="sample_rate",
            available=audio.sample_rate is not None,
            value=audio.sample_rate,
            reason="Version 7 maps Bit080-081 through the MPC SampleRate PrintConv.",
            evidence_ids=(MPC_TAG_TABLE_SOURCE, FLAC_BITSTREAM_SOURCE),
        ),
        MpcAudioResponsibilityPlan(
            kind="channels",
            available=False,
            value=None,
            reason="MPC.pm does not define a channel-count tag for Musepack streams.",
            evidence_ids=(MPC_TAG_TABLE_SOURCE,),
        ),
        MpcAudioResponsibilityPlan(
            kind="bitrate",
            available=False,
            value=None,
            reason="MPC.pm does not define a bitrate tag for Musepack streams.",
            evidence_ids=(MPC_TAG_TABLE_SOURCE,),
        ),
        MpcAudioResponsibilityPlan(
            kind="quality",
            available=audio.quality_raw is not None,
            value=audio.quality,
            reason="Version 7 maps Bit084-087 through the MPC Quality PrintConv.",
            evidence_ids=(MPC_TAG_TABLE_SOURCE, FLAC_BITSTREAM_SOURCE),
        ),
        MpcAudioResponsibilityPlan(
            kind="max_band",
            available=audio.max_band is not None,
            value=audio.max_band,
            reason="Version 7 maps Bit088-093 to MaxBand.",
            evidence_ids=(MPC_TAG_TABLE_SOURCE, FLAC_BITSTREAM_SOURCE),
        ),
        MpcAudioResponsibilityPlan(
            kind="replay_gain",
            available=audio.replay_gain_track_peak is not None,
            value=audio.replay_gain_track_gain,
            reason="Version 7 exposes track and album ReplayGain fields.",
            evidence_ids=(MPC_TAG_TABLE_SOURCE, FLAC_BITSTREAM_SOURCE),
        ),
        MpcAudioResponsibilityPlan(
            kind="fast_seek",
            available=audio.fast_seek is not None,
            value=audio.fast_seek,
            reason="Version 7 maps Bit179 through the FastSeek yes/no conversion.",
            evidence_ids=(MPC_TAG_TABLE_SOURCE, FLAC_BITSTREAM_SOURCE),
        ),
        MpcAudioResponsibilityPlan(
            kind="gapless",
            available=audio.gapless is not None,
            value=audio.gapless,
            reason="Version 7 maps Bit191 through the Gapless yes/no conversion.",
            evidence_ids=(MPC_TAG_TABLE_SOURCE, FLAC_BITSTREAM_SOURCE),
        ),
        MpcAudioResponsibilityPlan(
            kind="encoder_version",
            available=audio.encoder_version is not None,
            value=audio.encoder_version,
            reason="Version 7 maps Bit216-223 through the EncoderVersion PrintConv.",
            evidence_ids=(MPC_TAG_TABLE_SOURCE, FLAC_BITSTREAM_SOURCE),
        ),
    )


def build_rewrite_blockers(
    rewrite_request: MpcAudioRewriteRequest | None,
) -> tuple[MpcRewriteBlocker, ...]:
    if rewrite_request is None:
        return ()
    blockers: list[MpcRewriteBlocker] = []
    if rewrite_request.id3v2_payload is not None or rewrite_request.ape_payload is not None:
        blockers.append(
            MpcRewriteBlocker(
                code="mpc_metadata_rewrite_not_supported",
                reason=(
                    "MPC.pm delegates ID3 and APE reads but does not provide MPC-specific "
                    "metadata write behavior."
                ),
                evidence_ids=(MPC_ID3_PREFLIGHT_SOURCE, MPC_APE_TRAILER_SOURCE),
            )
        )
    if rewrite_request.audio_payload is not None:
        blockers.append(
            MpcRewriteBlocker(
                code="mpc_audio_payload_rewrite_not_supported",
                reason=(
                    "MPC.pm reads audio fields from the header and does not rewrite audio frames."
                ),
                evidence_ids=(MPC_TAG_TABLE_SOURCE, MPC_VERSION7_SOURCE),
            )
        )
    return tuple(blockers)


def _validation_gates(
    tag_coexistence: MpcTagCoexistencePlan,
    header: MpcHeaderValidationPlan,
) -> tuple[MpcOutputEmissionGate, ...]:
    gates: list[MpcOutputEmissionGate] = []
    if tag_coexistence.reason is not None:
        gates.append(
            MpcOutputEmissionGate(
                code=tag_coexistence.reason,
                reason="Tag coexistence boundaries could not be validated.",
                evidence_ids=tag_coexistence.evidence_ids,
            )
        )
    if header.reason is not None:
        gates.append(
            MpcOutputEmissionGate(
                code=header.reason,
                reason="MPC signature/header validation failed.",
                evidence_ids=header.evidence_ids,
            )
        )
    return tuple(gates)


def _gate_from_rewrite_blocker(blocker: MpcRewriteBlocker) -> MpcOutputEmissionGate:
    return MpcOutputEmissionGate(
        code=blocker.code,
        reason=blocker.reason,
        evidence_ids=blocker.evidence_ids,
    )


def has_structural_gate(gates: tuple[MpcOutputEmissionGate, ...]) -> bool:
    return any(
        gate.code
        in {
            "truncated_mpc_header",
            "unsupported_mpc_signature",
            "invalid_leading_id3v2_size",
            "invalid_trailing_ape_bounds",
        }
        for gate in gates
    )


def extract_little_endian_bits(data: bytes, bit_start: int, bit_end: int) -> int:
    value = 0
    for output_bit, source_bit in enumerate(range(bit_start, bit_end + 1)):
        byte_index = source_bit // 8
        bit_index = source_bit % 8
        value |= ((data[byte_index] >> bit_index) & 1) << output_bit
    return value


def format_encoder_version(raw_value: int) -> str:
    digits = str(raw_value)
    if len(digits) < 3:
        return digits
    prefix = digits[:-3]
    separator = "." if prefix else ""
    return f"{prefix}{separator}{digits[-3]}.{digits[-2]}.{digits[-1]}"


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def unique_evidence_ids(references: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def unique_gates(gates: tuple[MpcOutputEmissionGate, ...]) -> tuple[MpcOutputEmissionGate, ...]:
    unique: list[MpcOutputEmissionGate] = []
    codes: set[MpcEmissionGateCode] = set()
    for gate in gates:
        if gate.code not in codes:
            unique.append(gate)
            codes.add(gate.code)
    return tuple(unique)


plan_mpc_audio_transaction = build_mpc_audio_transaction_plan
