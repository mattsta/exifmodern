"""Source-backed, non-mutating AAC/ADTS stream transaction planning.

The planner mirrors ExifTool's AAC.pm read responsibilities: validate the
initial ADTS header, expose the MPEG/profile/sample-rate/channel fields handled
by the bit table, preserve complete media frames, estimate frame-derived
duration and average bitrate, and keep byte emission behind explicit gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ADTS_FIXED_HEADER_SIZE = 7
ADTS_CRC_SIZE = 2

type AacPlanStatus = Literal["planned", "unsupported"]
type AacAdtsHeaderStatus = Literal["valid", "invalid", "truncated"]
type AacFrameStatus = Literal["valid", "invalid_header", "sync_loss", "truncated"]
type AacId3RouteKind = Literal["no_id3", "present_but_aac_source_has_no_delegation"]
type AacPreservationKind = Literal["media_frame"]
type AacResponsibilityKind = Literal[
    "mpeg_version",
    "profile",
    "sample_rate",
    "channels",
    "frame_bitrate",
    "average_bitrate",
    "duration",
    "encoder",
    "id3_coexistence",
]
type AacEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "leading_id3_not_delegated_by_aac_source",
    "truncated_adts_header",
    "invalid_adts_sync",
    "reserved_profile_type",
    "invalid_sample_rate_index",
    "invalid_frame_length",
    "truncated_adts_frame",
    "adts_sync_loss",
    "aac_metadata_rewrite_not_supported",
    "aac_stream_rewrite_not_implemented",
]

AAC_PM_SOURCE_PATH = "lib/Image/ExifTool/AAC.pm"
FLAC_PM_SOURCE_PATH = "lib/Image/ExifTool/FLAC.pm"

AAC_SAMPLE_RATE_SOURCE = "aac.sample_rate"
AAC_TAG_TABLE_SOURCE = "aac.tag_table"
AAC_HEADER_FORMAT_SOURCE = "aac.header_format"
AAC_PROCESS_VALIDATION_SOURCE = "aac.process_validation"
AAC_ENCODER_SOURCE = "aac.encoder"
AAC_ID3_ABSENCE_SOURCE = "aac.id3_absence"
FLAC_ID3_CONTRAST_SOURCE = "flac.id3_contrast"
FLAC_BITSTREAM_SOURCE = "flac.bitstream"
AAC_TAGNAMES_SOURCE = "aac.tagnames"
AAC_NON_MUTATING_SOURCE = "aac.non_mutating"

AAC_TRANSACTION_SOURCES = (
    AAC_SAMPLE_RATE_SOURCE,
    AAC_TAG_TABLE_SOURCE,
    AAC_HEADER_FORMAT_SOURCE,
    AAC_PROCESS_VALIDATION_SOURCE,
    AAC_ENCODER_SOURCE,
    AAC_ID3_ABSENCE_SOURCE,
    FLAC_ID3_CONTRAST_SOURCE,
    FLAC_BITSTREAM_SOURCE,
    AAC_TAGNAMES_SOURCE,
    AAC_NON_MUTATING_SOURCE,
)

AAC_SAMPLE_RATES: dict[int, int] = {
    0: 96000,
    1: 88200,
    2: 64000,
    3: 48000,
    4: 44100,
    5: 32000,
    6: 24000,
    7: 22050,
    8: 16000,
    9: 12000,
    10: 11025,
    11: 8000,
    12: 7350,
}
AAC_PROFILE_TYPES: dict[int, str] = {
    0: "Main",
    1: "Low Complexity",
    2: "Scalable Sampling Rate",
}
AAC_CHANNELS: dict[int, str] = {
    0: "?",
    1: "1",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "5+1",
    7: "7+1",
}
AAC_MPEG_VERSION_LABELS: dict[int, str] = {
    0: "MPEG-4",
    1: "MPEG-2",
}


@dataclass(frozen=True)
class AacMetadataRewriteRequest:
    encoder: str | None = None


@dataclass(frozen=True)
class AacAdtsHeaderPlan:
    offset: int
    raw_header: bytes
    status: AacAdtsHeaderStatus
    blocker_code: AacEmissionGateCode | None
    sync_valid: bool
    mpeg_version_id: int | None
    mpeg_version: str | None
    layer: int | None
    protection_absent: bool | None
    header_size: int | None
    profile_index: int | None
    profile: str | None
    sample_rate_index: int | None
    sample_rate: int | None
    channel_config: int | None
    channels: str | None
    frame_length: int | None
    buffer_fullness: int | None
    raw_blocks_in_frame: int | None
    blocks_in_frame: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AacFramePlan:
    index: int
    offset: int
    header: AacAdtsHeaderPlan
    payload_offset: int | None
    declared_end_offset: int | None
    available_end_offset: int
    declared_length: int | None
    available_length: int
    samples: int | None
    frame_bitrate: float | None
    status: AacFrameStatus
    blocker_code: AacEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AacEncoderPlan:
    present: bool
    value: str | None
    frame_index: int | None
    payload_offset: int | None
    payload_length: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AacId3CoexistencePlan:
    leading_id3_present: bool
    route_kind: AacId3RouteKind
    delegated: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AacMediaPreservationPlan:
    frame_index: int
    kind: AacPreservationKind
    offset: int
    end_offset: int
    payload: bytes
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AacResponsibilityPlan:
    kind: AacResponsibilityKind
    available: bool
    value: int | float | str | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AacDurationPlan:
    frame_count: int
    complete_frame_count: int
    sample_rate: int | None
    total_samples: int
    total_declared_frame_bytes: int
    approximate_seconds: float | None
    average_bitrate: float | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AacOutputEmissionGate:
    code: AacEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AacStreamTransactionPlan:
    status: AacPlanStatus
    input_size: int
    frames: tuple[AacFramePlan, ...]
    primary_header: AacAdtsHeaderPlan | None
    encoder: AacEncoderPlan
    id3_coexistence: AacId3CoexistencePlan
    preservation_actions: tuple[AacMediaPreservationPlan, ...]
    responsibilities: tuple[AacResponsibilityPlan, ...]
    duration: AacDurationPlan
    output_emission_gates: tuple[AacOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"AAC stream transaction output is gated: {gate_codes}")
        return self.original_bytes


def build_aac_stream_transaction_plan(
    aac_data: bytes,
    *,
    requested_metadata: AacMetadataRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> AacStreamTransactionPlan:
    id3_coexistence = _id3_coexistence_plan(aac_data)
    frames, frame_gates = enumerate_adts_frames(aac_data)
    primary_header = frames[0].header if frames else None
    encoder = _encoder_plan(frames, aac_data)
    preservation_actions = tuple(
        _preservation_action(frame, aac_data) for frame in frames if frame.status == "valid"
    )
    duration = _duration_plan(frames)
    responsibilities = _responsibility_plans(primary_header, duration, encoder, id3_coexistence)

    gates = [*frame_gates]
    if id3_coexistence.leading_id3_present:
        gates.insert(
            0,
            AacOutputEmissionGate(
                "leading_id3_not_delegated_by_aac_source",
                "AAC.pm has no ID3 preflight before ADTS header validation.",
                id3_coexistence.evidence_ids,
            ),
        )
    if requested_metadata is not None and requested_metadata.encoder is not None:
        gates.extend(
            (
                AacOutputEmissionGate(
                    "aac_metadata_rewrite_not_supported",
                    "AAC.pm exposes Encoder as a first-frame filler read, not as a writable tag.",
                    (AAC_ENCODER_SOURCE, AAC_TAGNAMES_SOURCE),
                ),
                AacOutputEmissionGate(
                    "aac_stream_rewrite_not_implemented",
                    (
                        "This planner preserves complete ADTS frames and does not "
                        "rewrite AAC payloads."
                    ),
                    (AAC_TAG_TABLE_SOURCE, AAC_NON_MUTATING_SOURCE),
                ),
            )
        )
    if not allow_output_emission:
        gates.append(
            AacOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "AAC stream transaction plans are non-mutating unless emission is explicit.",
                (AAC_NON_MUTATING_SOURCE,),
            )
        )

    unique_output_gates = unique_gates(tuple(gates))
    status: AacPlanStatus = (
        "unsupported" if _has_structural_gate(unique_output_gates) else "planned"
    )
    return AacStreamTransactionPlan(
        status=status,
        input_size=len(aac_data),
        frames=frames,
        primary_header=primary_header,
        encoder=encoder,
        id3_coexistence=id3_coexistence,
        preservation_actions=preservation_actions,
        responsibilities=responsibilities,
        duration=duration,
        output_emission_gates=unique_output_gates,
        evidence_ids=unique_evidence_ids(
            (
                *AAC_TRANSACTION_SOURCES,
                *id3_coexistence.evidence_ids,
                *(source for frame in frames for source in frame.evidence_ids),
                *(source for action in preservation_actions for source in action.evidence_ids),
                *(source for gate in unique_output_gates for source in gate.evidence_ids),
            )
        ),
        original_bytes=aac_data,
    )


plan_aac_stream_transaction = build_aac_stream_transaction_plan


def enumerate_adts_frames(
    aac_data: bytes,
) -> tuple[tuple[AacFramePlan, ...], tuple[AacOutputEmissionGate, ...]]:
    frames: list[AacFramePlan] = []
    gates: list[AacOutputEmissionGate] = []
    offset = 0
    while offset < len(aac_data):
        header = parse_adts_header(aac_data, offset)
        frame = _frame_plan(len(frames), offset, header, aac_data)
        frames.append(frame)
        if frame.blocker_code is not None:
            gates.append(_gate_for_frame(frame))
            break
        if frame.declared_end_offset is None:
            break
        offset = frame.declared_end_offset
    if not frames and not aac_data:
        header = parse_adts_header(aac_data, 0)
        frame = _frame_plan(0, 0, header, aac_data)
        frames = [frame]
        gates = [_gate_for_frame(frame)]
    return tuple(frames), tuple(gates)


def parse_adts_header(aac_data: bytes, offset: int = 0) -> AacAdtsHeaderPlan:
    raw_header = aac_data[offset : offset + ADTS_FIXED_HEADER_SIZE]
    if len(raw_header) < ADTS_FIXED_HEADER_SIZE:
        return _truncated_header(offset, raw_header)

    mpeg_version_id = (raw_header[1] >> 3) & 0x01
    layer = (raw_header[1] >> 1) & 0x03
    protection_absent = (raw_header[1] & 0x01) == 1
    profile_index = (raw_header[2] >> 6) & 0x03
    sample_rate_index = (raw_header[2] >> 2) & 0x0F
    channel_config = ((raw_header[2] & 0x01) << 2) | ((raw_header[3] >> 6) & 0x03)
    frame_length = (
        ((raw_header[3] & 0x03) << 11) | (raw_header[4] << 3) | ((raw_header[5] >> 5) & 0x07)
    )
    buffer_fullness = ((raw_header[5] & 0x1F) << 6) | ((raw_header[6] >> 2) & 0x3F)
    raw_blocks = raw_header[6] & 0x03

    blocker = _header_blocker(
        raw_header,
        profile_index=profile_index,
        sample_rate_index=sample_rate_index,
        frame_length=frame_length,
    )
    return AacAdtsHeaderPlan(
        offset=offset,
        raw_header=raw_header,
        status="valid" if blocker is None else "invalid",
        blocker_code=blocker,
        sync_valid=_has_exiftool_adts_sync(raw_header),
        mpeg_version_id=mpeg_version_id,
        mpeg_version=AAC_MPEG_VERSION_LABELS[mpeg_version_id],
        layer=layer,
        protection_absent=protection_absent,
        header_size=ADTS_FIXED_HEADER_SIZE
        if protection_absent
        else ADTS_FIXED_HEADER_SIZE + ADTS_CRC_SIZE,
        profile_index=profile_index,
        profile=AAC_PROFILE_TYPES.get(profile_index),
        sample_rate_index=sample_rate_index,
        sample_rate=AAC_SAMPLE_RATES.get(sample_rate_index),
        channel_config=channel_config,
        channels=AAC_CHANNELS[channel_config],
        frame_length=frame_length,
        buffer_fullness=buffer_fullness,
        raw_blocks_in_frame=raw_blocks,
        blocks_in_frame=raw_blocks + 1,
        evidence_ids=(
            AAC_HEADER_FORMAT_SOURCE,
            AAC_PROCESS_VALIDATION_SOURCE,
            AAC_TAG_TABLE_SOURCE,
            AAC_SAMPLE_RATE_SOURCE,
            FLAC_BITSTREAM_SOURCE,
        ),
    )


def _truncated_header(offset: int, raw_header: bytes) -> AacAdtsHeaderPlan:
    return AacAdtsHeaderPlan(
        offset=offset,
        raw_header=raw_header,
        status="truncated",
        blocker_code="truncated_adts_header",
        sync_valid=False,
        mpeg_version_id=None,
        mpeg_version=None,
        layer=None,
        protection_absent=None,
        header_size=None,
        profile_index=None,
        profile=None,
        sample_rate_index=None,
        sample_rate=None,
        channel_config=None,
        channels=None,
        frame_length=None,
        buffer_fullness=None,
        raw_blocks_in_frame=None,
        blocks_in_frame=None,
        evidence_ids=(AAC_PROCESS_VALIDATION_SOURCE,),
    )


def _header_blocker(
    raw_header: bytes,
    *,
    profile_index: int,
    sample_rate_index: int,
    frame_length: int,
) -> AacEmissionGateCode | None:
    if not _has_exiftool_adts_sync(raw_header):
        return "invalid_adts_sync"
    if profile_index == 3:
        return "reserved_profile_type"
    if sample_rate_index > 12:
        return "invalid_sample_rate_index"
    if frame_length < ADTS_FIXED_HEADER_SIZE:
        return "invalid_frame_length"
    return None


def _has_exiftool_adts_sync(raw_header: bytes) -> bool:
    return len(raw_header) >= 2 and raw_header[0] == 0xFF and raw_header[1] in {0xF0, 0xF1}


def _frame_plan(
    index: int,
    offset: int,
    header: AacAdtsHeaderPlan,
    aac_data: bytes,
) -> AacFramePlan:
    if header.status == "truncated":
        return AacFramePlan(
            index=index,
            offset=offset,
            header=header,
            payload_offset=None,
            declared_end_offset=None,
            available_end_offset=len(aac_data),
            declared_length=None,
            available_length=max(0, len(aac_data) - offset),
            samples=None,
            frame_bitrate=None,
            status="truncated",
            blocker_code="truncated_adts_header",
            evidence_ids=header.evidence_ids,
        )
    if header.status == "invalid":
        status: AacFrameStatus = (
            "sync_loss" if header.blocker_code == "invalid_adts_sync" else "invalid_header"
        )
        return AacFramePlan(
            index=index,
            offset=offset,
            header=header,
            payload_offset=None,
            declared_end_offset=None,
            available_end_offset=len(aac_data),
            declared_length=header.frame_length,
            available_length=max(0, len(aac_data) - offset),
            samples=None,
            frame_bitrate=None,
            status=status,
            blocker_code=header.blocker_code,
            evidence_ids=header.evidence_ids,
        )

    declared_length = _required_int(header.frame_length)
    declared_end = offset + declared_length
    samples = _required_int(header.blocks_in_frame) * 1024
    frame_bitrate = (
        declared_length * 8 * _required_int(header.sample_rate) / samples if samples else None
    )
    if declared_end > len(aac_data):
        return AacFramePlan(
            index=index,
            offset=offset,
            header=header,
            payload_offset=offset + ADTS_FIXED_HEADER_SIZE,
            declared_end_offset=declared_end,
            available_end_offset=len(aac_data),
            declared_length=declared_length,
            available_length=max(0, len(aac_data) - offset),
            samples=samples,
            frame_bitrate=frame_bitrate,
            status="truncated",
            blocker_code="truncated_adts_frame",
            evidence_ids=(AAC_PROCESS_VALIDATION_SOURCE, AAC_TAG_TABLE_SOURCE),
        )
    return AacFramePlan(
        index=index,
        offset=offset,
        header=header,
        payload_offset=offset + ADTS_FIXED_HEADER_SIZE,
        declared_end_offset=declared_end,
        available_end_offset=declared_end,
        declared_length=declared_length,
        available_length=declared_length,
        samples=samples,
        frame_bitrate=frame_bitrate,
        status="valid",
        blocker_code=None,
        evidence_ids=(AAC_PROCESS_VALIDATION_SOURCE, AAC_TAG_TABLE_SOURCE),
    )


def _gate_for_frame(frame: AacFramePlan) -> AacOutputEmissionGate:
    code = frame.blocker_code or "adts_sync_loss"
    reason_by_code: dict[AacEmissionGateCode, str] = {
        "truncated_adts_header": "Input ended before the seven-byte ADTS header could be read.",
        "invalid_adts_sync": "ADTS frame sync did not match ExifTool's FF F0/F1 test.",
        "reserved_profile_type": "ADTS profile type 3 is reserved and rejected by AAC.pm.",
        "invalid_sample_rate_index": "ADTS sampling-frequency indexes above 12 are rejected.",
        "invalid_frame_length": "ADTS frame length must include at least the seven-byte header.",
        "truncated_adts_frame": "Declared ADTS frame length extends beyond the available input.",
        "adts_sync_loss": (
            "A later ADTS frame boundary did not contain an ExifTool-valid sync word."
        ),
        "leading_id3_not_delegated_by_aac_source": (
            "AAC.pm does not delegate ID3 before AAC parsing."
        ),
        "non_mutating_plan_requires_explicit_emission": (
            "Emission requires an explicit caller opt-in."
        ),
        "aac_metadata_rewrite_not_supported": "AAC metadata rewrite is not supported.",
        "aac_stream_rewrite_not_implemented": "AAC stream rewrite is not implemented.",
    }
    return AacOutputEmissionGate(code, reason_by_code[code], frame.evidence_ids)


def _encoder_plan(frames: tuple[AacFramePlan, ...], aac_data: bytes) -> AacEncoderPlan:
    if not frames or frames[0].status != "valid":
        return AacEncoderPlan(False, None, None, None, None, (AAC_ENCODER_SOURCE,))
    frame = frames[0]
    header = frame.header
    payload_offset = _required_int(frame.payload_offset)
    payload_end = _required_int(frame.declared_end_offset)
    payload = aac_data[payload_offset:payload_end]
    blocks = _required_int(header.raw_blocks_in_frame)
    position = 0
    if header.protection_absent is False:
        position += 2 + 2 * blocks
    if position + 2 > len(payload):
        return AacEncoderPlan(False, None, frame.index, None, None, (AAC_ENCODER_SOURCE,))

    two_bytes = int.from_bytes(payload[position : position + 2], "big")
    element_id = two_bytes >> 13
    if element_id != 6:
        return AacEncoderPlan(False, None, frame.index, None, None, (AAC_ENCODER_SOURCE,))
    count = (two_bytes >> 9) & 0x0F
    position += 1
    if count == 15:
        count += ((two_bytes >> 1) & 0xFF) - 1
        position += 1
    if position + count > len(payload):
        return AacEncoderPlan(False, None, frame.index, None, None, (AAC_ENCODER_SOURCE,))

    data = payload[position : position + count].strip(b"\x00")
    if data and all(0x20 <= byte <= 0x7E for byte in data):
        return AacEncoderPlan(
            True,
            data.decode("ascii"),
            frame.index,
            payload_offset + position,
            count,
            (AAC_ENCODER_SOURCE,),
        )
    return AacEncoderPlan(False, None, frame.index, None, None, (AAC_ENCODER_SOURCE,))


def _id3_coexistence_plan(aac_data: bytes) -> AacId3CoexistencePlan:
    leading = aac_data.startswith(b"ID3")
    return AacId3CoexistencePlan(
        leading_id3_present=leading,
        route_kind="present_but_aac_source_has_no_delegation" if leading else "no_id3",
        delegated=False,
        evidence_ids=(AAC_ID3_ABSENCE_SOURCE, FLAC_ID3_CONTRAST_SOURCE),
    )


def _preservation_action(frame: AacFramePlan, aac_data: bytes) -> AacMediaPreservationPlan:
    end_offset = _required_int(frame.declared_end_offset)
    return AacMediaPreservationPlan(
        frame_index=frame.index,
        kind="media_frame",
        offset=frame.offset,
        end_offset=end_offset,
        payload=aac_data[frame.offset : end_offset],
        reason="Complete ADTS media frames are preserved byte-for-byte by this planner.",
        evidence_ids=(AAC_PROCESS_VALIDATION_SOURCE, AAC_TAG_TABLE_SOURCE),
    )


def _duration_plan(frames: tuple[AacFramePlan, ...]) -> AacDurationPlan:
    complete_frames = tuple(frame for frame in frames if frame.status == "valid")
    sample_rates = {
        _required_int(frame.header.sample_rate)
        for frame in complete_frames
        if frame.header.sample_rate is not None
    }
    sample_rate = next(iter(sample_rates)) if len(sample_rates) == 1 else None
    total_samples = sum(frame.samples or 0 for frame in complete_frames)
    total_bytes = sum(frame.declared_length or 0 for frame in complete_frames)
    approximate_seconds = total_samples / sample_rate if sample_rate else None
    average_bitrate = (
        total_bytes * 8 / approximate_seconds
        if approximate_seconds is not None and approximate_seconds > 0
        else None
    )
    return AacDurationPlan(
        frame_count=len(frames),
        complete_frame_count=len(complete_frames),
        sample_rate=sample_rate,
        total_samples=total_samples,
        total_declared_frame_bytes=total_bytes,
        approximate_seconds=approximate_seconds,
        average_bitrate=average_bitrate,
        evidence_ids=(AAC_TAG_TABLE_SOURCE,),
    )


def _responsibility_plans(
    header: AacAdtsHeaderPlan | None,
    duration: AacDurationPlan,
    encoder: AacEncoderPlan,
    id3: AacId3CoexistencePlan,
) -> tuple[AacResponsibilityPlan, ...]:
    return (
        _responsibility(
            "mpeg_version",
            header is not None,
            header.mpeg_version if header else None,
            AAC_HEADER_FORMAT_SOURCE,
        ),
        _responsibility(
            "profile",
            header is not None and header.profile is not None,
            header.profile if header else None,
            AAC_TAG_TABLE_SOURCE,
        ),
        _responsibility(
            "sample_rate",
            header is not None and header.sample_rate is not None,
            header.sample_rate if header else None,
            AAC_SAMPLE_RATE_SOURCE,
        ),
        _responsibility(
            "channels",
            header is not None and header.channels is not None,
            header.channels if header else None,
            AAC_TAG_TABLE_SOURCE,
        ),
        _responsibility(
            "frame_bitrate",
            header is not None and duration.complete_frame_count > 0,
            None,
            AAC_TAG_TABLE_SOURCE,
            reason="Per-frame bitrate is stored on each AacFramePlan from the AAC.pm formula.",
        ),
        _responsibility(
            "average_bitrate",
            duration.average_bitrate is not None,
            duration.average_bitrate,
            AAC_TAG_TABLE_SOURCE,
        ),
        _responsibility(
            "duration",
            duration.approximate_seconds is not None,
            duration.approximate_seconds,
            AAC_TAG_TABLE_SOURCE,
        ),
        _responsibility("encoder", encoder.present, encoder.value, AAC_ENCODER_SOURCE),
        AacResponsibilityPlan(
            kind="id3_coexistence",
            available=not id3.leading_id3_present,
            value=id3.route_kind,
            reason=(
                "AAC.pm has no ID3 delegation before ADTS parsing; leading ID3 is therefore "
                "represented as coexistence, not delegated metadata."
            ),
            evidence_ids=id3.evidence_ids,
        ),
    )


def _responsibility(
    kind: AacResponsibilityKind,
    available: bool,
    value: int | float | str | None,
    source: str,
    *,
    reason: str | None = None,
) -> AacResponsibilityPlan:
    return AacResponsibilityPlan(
        kind=kind,
        available=available,
        value=value,
        reason=reason
        or (
            "Value is available from the AAC/ADTS plan."
            if available
            else "Value is unavailable for this stream."
        ),
        evidence_ids=(source,),
    )


def _has_structural_gate(gates: tuple[AacOutputEmissionGate, ...]) -> bool:
    structural_codes: set[AacEmissionGateCode] = {
        "leading_id3_not_delegated_by_aac_source",
        "truncated_adts_header",
        "invalid_adts_sync",
        "reserved_profile_type",
        "invalid_sample_rate_index",
        "invalid_frame_length",
        "truncated_adts_frame",
        "adts_sync_loss",
    }
    return any(gate.code in structural_codes for gate in gates)


def _required_int(value: int | None) -> int:
    if value is None:
        raise ValueError("Expected parsed ADTS integer value.")
    return value


def unique_evidence_ids(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for source in sources:
        if source not in unique:
            unique.append(source)
    return tuple(unique)


def unique_gates(gates: tuple[AacOutputEmissionGate, ...]) -> tuple[AacOutputEmissionGate, ...]:
    seen: set[AacEmissionGateCode] = set()
    unique: list[AacOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
