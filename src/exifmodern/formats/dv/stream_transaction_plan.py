"""Source-backed, non-mutating DV stream transaction planning.

The planner mirrors ExifTool's DV.pm read responsibilities: find the first DV
DIF header, validate enough header blocks to select a profile, enumerate DIF
blocks and profile-sized frames, expose only the date/video/audio metadata that
DV.pm extracts, preserve payload bytes, and keep emission behind explicit gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DIF_BLOCK_SIZE = 80
DV_HEADER_BLOCK_COUNT = 6
DV_HEADER_MIN_SIZE = DIF_BLOCK_SIZE * DV_HEADER_BLOCK_COUNT
DV_SCAN_LIMIT = 12000
DV_AUDIO_PACK_OFFSET = DIF_BLOCK_SIZE * 6 + DIF_BLOCK_SIZE * 16 * 3 + 3

type DvPlanStatus = Literal["planned", "unsupported"]
type DvDifHeaderStatus = Literal["valid", "not_found", "truncated"]
type DvDifBlockRouteKind = Literal[
    "dif_header",
    "vaux_metadata",
    "audio_payload",
    "video_payload",
    "unknown_payload",
    "leading_payload",
]
type DvTimecodeMode = Literal["not_exposed_by_dv_pm"]
type DvResponsibilityKind = Literal[
    "date_time_original",
    "timecode",
    "camera_metadata",
    "video_profile",
    "duration",
    "total_bitrate",
    "aspect_ratio",
    "video_scan_type",
    "audio_channels",
    "audio_sample_rate",
    "audio_bits_per_sample",
    "payload_preservation",
]
type DvEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "dv_signature_not_found",
    "truncated_dif_header",
    "truncated_dif_block",
    "truncated_dv_frame",
    "unrecognized_dv_profile",
    "dv_metadata_rewrite_not_supported",
    "dv_stream_rewrite_not_implemented",
]

DV_PROFILE_EVIDENCE_ID = "dv.profile"
DV_PROFILE_SOURCE = DV_PROFILE_EVIDENCE_ID
DV_TAG_TABLE_EVIDENCE_ID = "dv.tag_table"
DV_TAG_TABLE_SOURCE = DV_TAG_TABLE_EVIDENCE_ID
DV_HEADER_VALIDATION_EVIDENCE_ID = "dv.header_validation"
DV_HEADER_VALIDATION_SOURCE = DV_HEADER_VALIDATION_EVIDENCE_ID
DV_DURATION_EVIDENCE_ID = "dv.duration"
DV_DURATION_SOURCE = DV_DURATION_EVIDENCE_ID
DV_VAUX_EVIDENCE_ID = "dv.vaux"
DV_VAUX_SOURCE = DV_VAUX_EVIDENCE_ID
DV_AUDIO_EVIDENCE_ID = "dv.audio"
DV_AUDIO_SOURCE = DV_AUDIO_EVIDENCE_ID
DV_EMIT_EVIDENCE_ID = "dv.emit"
DV_EMIT_SOURCE = DV_EMIT_EVIDENCE_ID
DV_READ_ONLY_DESCRIPTION_EVIDENCE_ID = "dv.read_only_description"
DV_READ_ONLY_DESCRIPTION_SOURCE = DV_READ_ONLY_DESCRIPTION_EVIDENCE_ID

DV_TRANSACTION_EVIDENCE_IDS = (
    DV_PROFILE_EVIDENCE_ID,
    DV_TAG_TABLE_EVIDENCE_ID,
    DV_HEADER_VALIDATION_EVIDENCE_ID,
    DV_DURATION_EVIDENCE_ID,
    DV_VAUX_EVIDENCE_ID,
    DV_AUDIO_EVIDENCE_ID,
    DV_EMIT_EVIDENCE_ID,
    DV_READ_ONLY_DESCRIPTION_EVIDENCE_ID,
)


@dataclass(frozen=True)
class DvProfile:
    dsf: int
    video_stype: int
    frame_size: int
    video_format: str
    colorimetry: str
    frame_rate: float
    image_height: int
    image_width: int


DV_PROFILES: tuple[DvProfile, ...] = (
    DvProfile(
        0, 0x0, 120000, "IEC 61834, SMPTE-314M - 525/60 (NTSC)", "4:1:1", 30000 / 1001, 480, 720
    ),
    DvProfile(1, 0x0, 144000, "IEC 61834 - 625/50 (PAL)", "4:2:0", 25 / 1, 576, 720),
    DvProfile(1, 0x0, 144000, "SMPTE-314M - 625/50 (PAL)", "4:1:1", 25 / 1, 576, 720),
    DvProfile(
        0,
        0x4,
        240000,
        "DVCPRO50: SMPTE-314M - 525/60 (NTSC) 50 Mbps",
        "4:2:2",
        30000 / 1001,
        480,
        720,
    ),
    DvProfile(
        1, 0x4, 288000, "DVCPRO50: SMPTE-314M - 625/50 (PAL) 50 Mbps", "4:2:2", 25 / 1, 576, 720
    ),
    DvProfile(
        0,
        0x14,
        480000,
        "DVCPRO HD: SMPTE-370M - 1080i60 100 Mbps",
        "4:2:2",
        30000 / 1001,
        1080,
        1280,
    ),
    DvProfile(
        1, 0x14, 576000, "DVCPRO HD: SMPTE-370M - 1080i50 100 Mbps", "4:2:2", 25 / 1, 1080, 1440
    ),
    DvProfile(
        0, 0x18, 240000, "DVCPRO HD: SMPTE-370M - 720p60 100 Mbps", "4:2:2", 60000 / 1001, 720, 960
    ),
    DvProfile(
        1, 0x18, 288000, "DVCPRO HD: SMPTE-370M - 720p50 100 Mbps", "4:2:2", 50 / 1, 720, 960
    ),
    DvProfile(1, 0x1, 144000, "IEC 61883-5 - 625/50 (PAL)", "4:2:0", 25 / 1, 576, 720),
)


@dataclass(frozen=True)
class DvMetadataRewriteRequest:
    date_time_original: str | None = None
    timecode: str | None = None
    camera_model: str | None = None
    aspect_ratio: str | None = None
    audio_sample_rate: int | None = None

    @property
    def has_requested_values(self) -> bool:
        return (
            self.date_time_original is not None
            or self.timecode is not None
            or self.camera_model is not None
            or self.aspect_ratio is not None
            or self.audio_sample_rate is not None
        )


@dataclass(frozen=True)
class DvDifHeaderPlan:
    start_offset: int | None
    status: DvDifHeaderStatus
    sync_pattern: str | None
    raw_signature: bytes
    dsf: int | None
    apt: int | None
    video_stype: int | None
    profile: DvProfile | None
    blocker_code: DvEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DvDifBlockPlan:
    index: int
    frame_index: int | None
    offset: int
    end_offset: int
    route_kind: DvDifBlockRouteKind
    type_byte: int
    payload: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DvFramePlan:
    index: int
    offset: int
    declared_end_offset: int | None
    available_end_offset: int
    declared_size: int | None
    available_size: int
    block_count: int
    complete: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DvTimeMetadataPlan:
    date_pack_found: bool
    time_pack_found: bool
    date_time_original: str | None
    timecode: str | None
    timecode_mode: DvTimecodeMode
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DvVideoMetadataPlan:
    image_width: int | None
    image_height: int | None
    duration: float | None
    total_bitrate: float | None
    video_format: str | None
    video_scan_type: str | None
    frame_rate: float | None
    aspect_ratio: str | None
    colorimetry: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DvAudioMetadataPlan:
    pack_present: bool
    samples_byte: int | None
    frequency_code: int | None
    stream_type: int | None
    quantization_code: int | None
    audio_channels: int | None
    audio_sample_rate: int | None
    audio_bits_per_sample: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DvResponsibilityPlan:
    kind: DvResponsibilityKind
    available: bool
    value: int | float | str | bool | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DvPayloadPreservationPlan:
    kind: DvDifBlockRouteKind
    offset: int
    end_offset: int
    payload: bytes
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DvOutputEmissionGate:
    code: DvEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DvStreamTransactionPlan:
    status: DvPlanStatus
    input_size: int
    header: DvDifHeaderPlan
    frames: tuple[DvFramePlan, ...]
    blocks: tuple[DvDifBlockPlan, ...]
    time_metadata: DvTimeMetadataPlan
    video_metadata: DvVideoMetadataPlan
    audio_metadata: DvAudioMetadataPlan
    preservation_actions: tuple[DvPayloadPreservationPlan, ...]
    responsibilities: tuple[DvResponsibilityPlan, ...]
    output_emission_gates: tuple[DvOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"DV stream transaction output is gated: {gate_codes}")
        return self.original_bytes


def build_dv_stream_transaction_plan(
    dv_data: bytes,
    *,
    file_size: int | None = None,
    requested_metadata: DvMetadataRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> DvStreamTransactionPlan:
    input_size = len(dv_data) if file_size is None else file_size
    header = parse_dif_header(dv_data)
    frames = enumerate_dv_frames(dv_data, header)
    blocks = enumerate_dif_blocks(dv_data, header)
    time_metadata = _time_metadata_plan(dv_data, header)
    video_metadata = _video_metadata_plan(dv_data, header, time_metadata, file_size=input_size)
    audio_metadata = _audio_metadata_plan(dv_data, header)
    preservation_actions = _preservation_actions(dv_data, header, blocks)
    responsibilities = _responsibility_plans(
        header,
        time_metadata,
        video_metadata,
        audio_metadata,
        preservation_actions,
    )
    gates = _structural_gates(dv_data, header, frames)
    if requested_metadata is not None and requested_metadata.has_requested_values:
        gates.extend(_rewrite_gates())
    if not allow_output_emission:
        gates.append(
            DvOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "DV stream transaction plans are non-mutating unless emission is explicit.",
                (DV_EMIT_EVIDENCE_ID, DV_READ_ONLY_DESCRIPTION_EVIDENCE_ID),
            )
        )

    output_gates = _unique_gates(tuple(gates))
    status: DvPlanStatus = "unsupported" if _has_unsupported_gate(output_gates) else "planned"
    return DvStreamTransactionPlan(
        status=status,
        input_size=input_size,
        header=header,
        frames=frames,
        blocks=blocks,
        time_metadata=time_metadata,
        video_metadata=video_metadata,
        audio_metadata=audio_metadata,
        preservation_actions=preservation_actions,
        responsibilities=responsibilities,
        output_emission_gates=output_gates,
        evidence_ids=_unique_sources(
            (
                *DV_TRANSACTION_EVIDENCE_IDS,
                *header.evidence_ids,
                *(source for frame in frames for source in frame.evidence_ids),
                *(source for block in blocks for source in block.evidence_ids),
                *time_metadata.evidence_ids,
                *video_metadata.evidence_ids,
                *audio_metadata.evidence_ids,
                *(source for action in preservation_actions for source in action.evidence_ids),
                *(source for gate in output_gates for source in gate.evidence_ids),
            )
        ),
        original_bytes=dv_data,
    )


plan_dv_stream_transaction = build_dv_stream_transaction_plan


def parse_dif_header(dv_data: bytes) -> DvDifHeaderPlan:
    start = _find_dv_start(dv_data)
    if start is None:
        return DvDifHeaderPlan(
            start_offset=None,
            status="not_found",
            sync_pattern=None,
            raw_signature=dv_data[:4],
            dsf=None,
            apt=None,
            video_stype=None,
            profile=None,
            blocker_code="dv_signature_not_found",
            evidence_ids=(DV_HEADER_VALIDATION_EVIDENCE_ID,),
        )
    if start + DV_HEADER_MIN_SIZE > len(dv_data):
        return DvDifHeaderPlan(
            start_offset=start,
            status="truncated",
            sync_pattern=_sync_pattern(dv_data, start),
            raw_signature=dv_data[start : start + 4],
            dsf=None,
            apt=None,
            video_stype=None,
            profile=None,
            blocker_code="truncated_dif_header",
            evidence_ids=(DV_HEADER_VALIDATION_EVIDENCE_ID,),
        )

    dsf = (dv_data[start + 3] & 0x80) >> 7
    apt = dv_data[start + 4] & 0x07
    video_stype = dv_data[start + DIF_BLOCK_SIZE * 5 + 48 + 3] & 0x1F
    profile = _select_profile(dv_data, dsf, video_stype)
    blocker: DvEmissionGateCode | None = None if profile is not None else "unrecognized_dv_profile"
    return DvDifHeaderPlan(
        start_offset=start,
        status="valid",
        sync_pattern=_sync_pattern(dv_data, start),
        raw_signature=dv_data[start : start + 4],
        dsf=dsf,
        apt=apt,
        video_stype=video_stype,
        profile=profile,
        blocker_code=blocker,
        evidence_ids=(DV_HEADER_VALIDATION_EVIDENCE_ID, DV_PROFILE_EVIDENCE_ID),
    )


def enumerate_dif_blocks(
    dv_data: bytes,
    header: DvDifHeaderPlan,
) -> tuple[DvDifBlockPlan, ...]:
    if header.start_offset is None:
        return ()
    start = header.start_offset
    complete_block_count = max(0, len(dv_data) - start) // DIF_BLOCK_SIZE
    frame_size = header.profile.frame_size if header.profile is not None else None
    blocks: list[DvDifBlockPlan] = []
    for block_index in range(complete_block_count):
        offset = start + block_index * DIF_BLOCK_SIZE
        end_offset = offset + DIF_BLOCK_SIZE
        payload = dv_data[offset:end_offset]
        frame_index = None if frame_size is None else (offset - start) // frame_size
        blocks.append(
            DvDifBlockPlan(
                index=block_index,
                frame_index=frame_index,
                offset=offset,
                end_offset=end_offset,
                route_kind=_block_route(block_index, payload[0]),
                type_byte=payload[0],
                payload=payload,
                evidence_ids=(DV_HEADER_VALIDATION_EVIDENCE_ID,),
            )
        )
    return tuple(blocks)


def enumerate_dv_frames(
    dv_data: bytes,
    header: DvDifHeaderPlan,
) -> tuple[DvFramePlan, ...]:
    if header.start_offset is None or header.profile is None:
        return ()
    start = header.start_offset
    frame_size = header.profile.frame_size
    available = max(0, len(dv_data) - start)
    if available == 0:
        return ()
    frame_count = (available + frame_size - 1) // frame_size
    frames: list[DvFramePlan] = []
    for frame_index in range(frame_count):
        offset = start + frame_index * frame_size
        declared_end = offset + frame_size
        available_end = min(len(dv_data), declared_end)
        available_size = max(0, available_end - offset)
        frames.append(
            DvFramePlan(
                index=frame_index,
                offset=offset,
                declared_end_offset=declared_end,
                available_end_offset=available_end,
                declared_size=frame_size,
                available_size=available_size,
                block_count=available_size // DIF_BLOCK_SIZE,
                complete=declared_end <= len(dv_data),
                evidence_ids=(DV_PROFILE_EVIDENCE_ID, DV_DURATION_EVIDENCE_ID),
            )
        )
    return tuple(frames)


def _find_dv_start(dv_data: bytes) -> int | None:
    window = dv_data[:DV_SCAN_LIMIT]
    for offset in range(max(0, len(window) - 3)):
        if window[offset : offset + 3] == b"\x1f\x07\x00" and window[offset + 3] in {
            0x3F,
            0xBF,
        }:
            return offset
    fallback_match_size = 84
    for offset in range(max(0, len(window) - fallback_match_size + 1)):
        start = offset - 79
        if start < 0:
            continue
        if (
            window[offset] in {0x00, 0xFF}
            and window[offset + 1 : offset + 4] == b"\x3f\x07\x00"
            and window[offset + 80 : offset + 84] == b"\xff\x3f\x07\x01"
        ):
            return start
    return None


def _sync_pattern(dv_data: bytes, start: int) -> str:
    if dv_data[start : start + 3] == b"\x1f\x07\x00" and dv_data[start + 3] in {0x3F, 0xBF}:
        return "primary"
    return "fallback"


def _select_profile(dv_data: bytes, dsf: int, video_stype: int) -> DvProfile | None:
    if dsf == 1 and video_stype == 0 and len(dv_data) > 4 and dv_data[4] & 0x07:
        return DV_PROFILES[2]
    for profile in DV_PROFILES:
        if profile.dsf == dsf and profile.video_stype == video_stype:
            return profile
    return None


def _block_route(block_index: int, type_byte: int) -> DvDifBlockRouteKind:
    high_nibble = type_byte & 0xF0
    if block_index == 0:
        return "dif_header"
    if high_nibble == 0x50:
        return "vaux_metadata"
    if high_nibble == 0x70:
        return "audio_payload"
    if high_nibble == 0x90:
        return "video_payload"
    return "unknown_payload"


def _time_metadata_plan(dv_data: bytes, header: DvDifHeaderPlan) -> DvTimeMetadataPlan:
    if header.start_offset is None or header.status != "valid":
        return DvTimeMetadataPlan(
            date_pack_found=False,
            time_pack_found=False,
            date_time_original=None,
            timecode=None,
            timecode_mode="not_exposed_by_dv_pm",
            evidence_ids=(DV_VAUX_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
        )
    start = header.start_offset
    date: str | None = None
    time: str | None = None
    date_pack_found = False
    time_pack_found = False
    for block_number in range(1, 6):
        pos = start + block_number * DIF_BLOCK_SIZE
        if pos >= len(dv_data) or (dv_data[pos] & 0xF0) != 0x50:
            continue
        for pack_index in range(15):
            pack_offset = pos + pack_index * 5 + 3
            if pack_offset + 4 >= len(dv_data):
                break
            pack_type = dv_data[pack_offset]
            if pack_type == 0x62:
                date_pack_found = True
                date = _dv_date(dv_data[pack_offset + 1 : pack_offset + 5])
                time = None
            elif pack_type == 0x63 and date is not None:
                time_pack_found = True
                time = _dv_time(dv_data[pack_offset + 1 : pack_offset + 5])
                break
            elif pack_type != 0x61:
                time = None
    date_time = f"{date} {time}" if date is not None and time is not None else None
    return DvTimeMetadataPlan(
        date_pack_found=date_pack_found,
        time_pack_found=time_pack_found,
        date_time_original=date_time,
        timecode=None,
        timecode_mode="not_exposed_by_dv_pm",
        evidence_ids=(DV_VAUX_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
    )


def _dv_date(raw: bytes) -> str | None:
    if len(raw) < 4:
        return None
    candidate = f"{raw[3]:02x}:{raw[2] & 0x1F:02x}:{raw[1] & 0x3F:02x}"
    if any(char in "abcdef" for char in candidate):
        return None
    century = "20" if candidate < "9" else "19"
    return f"{century}{candidate}"


def _dv_time(raw: bytes) -> str | None:
    if len(raw) < 4:
        return None
    return f"{raw[3] & 0x3F:02x}:{raw[2] & 0x7F:02x}:{raw[1] & 0x7F:02x}"


def _video_metadata_plan(
    dv_data: bytes,
    header: DvDifHeaderPlan,
    time_metadata: DvTimeMetadataPlan,
    *,
    file_size: int | None = None,
) -> DvVideoMetadataPlan:
    profile = header.profile
    aspect_ratio: str | None = None
    video_scan_type: str | None = None
    if header.start_offset is not None and time_metadata.date_time_original is not None:
        aspect_ratio, video_scan_type = _vaux_video_control(dv_data, header.start_offset)

    duration: float | None = None
    total_bitrate: float | None = None
    if profile is not None:
        byte_rate = profile.frame_size * profile.frame_rate
        total_bitrate = 8 * byte_rate
        duration = (len(dv_data) if file_size is None else file_size) / byte_rate
    return DvVideoMetadataPlan(
        image_width=None if profile is None else profile.image_width,
        image_height=None if profile is None else profile.image_height,
        duration=duration,
        total_bitrate=total_bitrate,
        video_format=None if profile is None else profile.video_format,
        video_scan_type=video_scan_type,
        frame_rate=None if profile is None else profile.frame_rate,
        aspect_ratio=aspect_ratio,
        colorimetry=None if profile is None else profile.colorimetry,
        evidence_ids=(
            DV_PROFILE_EVIDENCE_ID,
            DV_DURATION_EVIDENCE_ID,
            DV_VAUX_EVIDENCE_ID,
            DV_TAG_TABLE_EVIDENCE_ID,
        ),
    )


def _vaux_video_control(dv_data: bytes, start: int) -> tuple[str | None, str | None]:
    for block_number in range(1, 6):
        pos = start + block_number * DIF_BLOCK_SIZE
        if pos >= len(dv_data) or (dv_data[pos] & 0xF0) != 0x50:
            continue
        for pack_index in range(15):
            pack_offset = pos + pack_index * 5 + 3
            if pack_offset + 3 >= len(dv_data):
                break
            if dv_data[pack_offset] == 0x61:
                apt = dv_data[start + 4] & 0x07
                aspect_code = dv_data[pack_offset + 2] & 0x07
                is_16_9 = aspect_code == 0x02 or (apt == 0 and aspect_code == 0x07)
                interlace = (dv_data[pack_offset + 3] & 0x10) != 0
                return ("16:9" if is_16_9 else "4:3", "Interlaced" if interlace else "Progressive")
    return None, None


def _audio_metadata_plan(dv_data: bytes, header: DvDifHeaderPlan) -> DvAudioMetadataPlan:
    if header.start_offset is None:
        return _empty_audio_plan()
    pos = header.start_offset + DV_AUDIO_PACK_OFFSET
    if pos + 4 >= len(dv_data) or dv_data[pos] != 0x50:
        return _empty_audio_plan()
    samples_byte = dv_data[pos + 1]
    frequency_code = (dv_data[pos + 4] >> 3) & 0x07
    stream_type = dv_data[pos + 3] & 0x1F
    quantization_code = dv_data[pos + 4] & 0x07
    sample_rate_by_code = {0: 48000, 1: 44100, 2: 32000}
    audio_sample_rate = sample_rate_by_code.get(frequency_code)
    adjusted_stream_type = stream_type
    if stream_type == 0 and quantization_code and frequency_code == 2:
        adjusted_stream_type = 2
    channels_by_type = {0: 2, 1: 0, 2: 4, 3: 8}
    audio_channels = channels_by_type.get(adjusted_stream_type) if stream_type < 3 else None
    return DvAudioMetadataPlan(
        pack_present=True,
        samples_byte=samples_byte,
        frequency_code=frequency_code,
        stream_type=stream_type,
        quantization_code=quantization_code,
        audio_channels=audio_channels,
        audio_sample_rate=audio_sample_rate,
        audio_bits_per_sample=12 if quantization_code else 16,
        evidence_ids=(DV_AUDIO_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
    )


def _empty_audio_plan() -> DvAudioMetadataPlan:
    return DvAudioMetadataPlan(
        pack_present=False,
        samples_byte=None,
        frequency_code=None,
        stream_type=None,
        quantization_code=None,
        audio_channels=None,
        audio_sample_rate=None,
        audio_bits_per_sample=None,
        evidence_ids=(DV_AUDIO_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
    )


def _preservation_actions(
    dv_data: bytes,
    header: DvDifHeaderPlan,
    blocks: tuple[DvDifBlockPlan, ...],
) -> tuple[DvPayloadPreservationPlan, ...]:
    actions: list[DvPayloadPreservationPlan] = []
    if header.start_offset is not None and header.start_offset > 0:
        actions.append(
            DvPayloadPreservationPlan(
                kind="leading_payload",
                offset=0,
                end_offset=header.start_offset,
                payload=dv_data[: header.start_offset],
                reason="Bytes before the detected DV header are preserved outside DV parsing.",
                evidence_ids=(DV_HEADER_VALIDATION_EVIDENCE_ID,),
            )
        )
    for block in blocks:
        actions.append(
            DvPayloadPreservationPlan(
                kind=block.route_kind,
                offset=block.offset,
                end_offset=block.end_offset,
                payload=block.payload,
                reason="Complete 80-byte DIF blocks are preserved without mutation.",
                evidence_ids=block.evidence_ids,
            )
        )
    return tuple(actions)


def _responsibility_plans(
    header: DvDifHeaderPlan,
    time_metadata: DvTimeMetadataPlan,
    video_metadata: DvVideoMetadataPlan,
    audio_metadata: DvAudioMetadataPlan,
    preservation_actions: tuple[DvPayloadPreservationPlan, ...],
) -> tuple[DvResponsibilityPlan, ...]:
    profile_available = header.profile is not None
    return (
        DvResponsibilityPlan(
            "date_time_original",
            time_metadata.date_time_original is not None,
            time_metadata.date_time_original,
            "DV.pm emits DateTimeOriginal only when valid date and time packs are found.",
            (DV_VAUX_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
        ),
        DvResponsibilityPlan(
            "timecode",
            False,
            None,
            "DV.pm ignores frame/timecode detail beyond DateTimeOriginal and has no timecode tag.",
            (DV_VAUX_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
        ),
        DvResponsibilityPlan(
            "camera_metadata",
            False,
            None,
            "DV.pm's tag table contains no camera make/model or lens metadata.",
            (DV_TAG_TABLE_EVIDENCE_ID,),
        ),
        DvResponsibilityPlan(
            "video_profile",
            profile_available,
            video_metadata.video_format,
            "DV.pm identifies video profile from DSF and VideoSType.",
            (DV_HEADER_VALIDATION_EVIDENCE_ID, DV_PROFILE_EVIDENCE_ID),
        ),
        DvResponsibilityPlan(
            "duration",
            video_metadata.duration is not None,
            video_metadata.duration,
            "DV.pm derives duration from file size and profile byte rate.",
            (DV_DURATION_EVIDENCE_ID,),
        ),
        DvResponsibilityPlan(
            "total_bitrate",
            video_metadata.total_bitrate is not None,
            video_metadata.total_bitrate,
            "DV.pm derives total bitrate from profile byte rate.",
            (DV_DURATION_EVIDENCE_ID,),
        ),
        DvResponsibilityPlan(
            "aspect_ratio",
            video_metadata.aspect_ratio is not None,
            video_metadata.aspect_ratio,
            "DV.pm emits AspectRatio from VAUX video control only with DateTimeOriginal.",
            (DV_VAUX_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
        ),
        DvResponsibilityPlan(
            "video_scan_type",
            video_metadata.video_scan_type is not None,
            video_metadata.video_scan_type,
            "DV.pm emits VideoScanType from VAUX video control only with DateTimeOriginal.",
            (DV_VAUX_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
        ),
        DvResponsibilityPlan(
            "audio_channels",
            audio_metadata.audio_channels is not None,
            audio_metadata.audio_channels,
            "DV.pm emits AudioChannels only when the fixed audio pack exposes a known stream type.",
            (DV_AUDIO_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
        ),
        DvResponsibilityPlan(
            "audio_sample_rate",
            audio_metadata.audio_sample_rate is not None,
            audio_metadata.audio_sample_rate,
            "DV.pm emits AudioSampleRate only for frequency codes 0 through 2.",
            (DV_AUDIO_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
        ),
        DvResponsibilityPlan(
            "audio_bits_per_sample",
            audio_metadata.audio_bits_per_sample is not None,
            audio_metadata.audio_bits_per_sample,
            "DV.pm maps non-zero audio quantization to 12 bits and zero to 16 bits.",
            (DV_AUDIO_EVIDENCE_ID, DV_TAG_TABLE_EVIDENCE_ID),
        ),
        DvResponsibilityPlan(
            "payload_preservation",
            bool(preservation_actions),
            len(preservation_actions),
            "The transaction planner preserves complete DIF blocks and does not rewrite payloads.",
            (DV_HEADER_VALIDATION_EVIDENCE_ID, DV_READ_ONLY_DESCRIPTION_EVIDENCE_ID),
        ),
    )


def _structural_gates(
    dv_data: bytes,
    header: DvDifHeaderPlan,
    frames: tuple[DvFramePlan, ...],
) -> list[DvOutputEmissionGate]:
    gates: list[DvOutputEmissionGate] = []
    if header.blocker_code is not None:
        gates.append(_gate(header.blocker_code))
    if header.start_offset is not None and header.status == "valid":
        payload_size = max(0, len(dv_data) - header.start_offset)
        if payload_size % DIF_BLOCK_SIZE:
            gates.append(_gate("truncated_dif_block"))
    return gates


def _rewrite_gates() -> tuple[DvOutputEmissionGate, DvOutputEmissionGate]:
    return (
        DvOutputEmissionGate(
            "dv_metadata_rewrite_not_supported",
            "DV.pm exposes read tags only and has no writable DV metadata table.",
            (DV_TAG_TABLE_EVIDENCE_ID, DV_EMIT_EVIDENCE_ID, DV_READ_ONLY_DESCRIPTION_EVIDENCE_ID),
        ),
        DvOutputEmissionGate(
            "dv_stream_rewrite_not_implemented",
            "This planner preserves DIF blocks and does not rewrite DV audio/video payloads.",
            (DV_HEADER_VALIDATION_EVIDENCE_ID, DV_READ_ONLY_DESCRIPTION_EVIDENCE_ID),
        ),
    )


def _gate(code: DvEmissionGateCode) -> DvOutputEmissionGate:
    if code == "dv_signature_not_found":
        return DvOutputEmissionGate(
            code,
            "No DV signature was found in the first 12000 bytes scanned by DV.pm.",
            (DV_HEADER_VALIDATION_EVIDENCE_ID,),
        )
    if code == "truncated_dif_header":
        return DvOutputEmissionGate(
            code,
            "Input ended before the six 80-byte DIF header blocks required by DV.pm.",
            (DV_HEADER_VALIDATION_EVIDENCE_ID,),
        )
    if code == "truncated_dif_block":
        return DvOutputEmissionGate(
            code,
            "The DV payload ends in a partial 80-byte DIF block.",
            (DV_HEADER_VALIDATION_EVIDENCE_ID,),
        )
    if code == "truncated_dv_frame":
        return DvOutputEmissionGate(
            code,
            "The DV payload does not contain complete profile-sized frames.",
            (DV_PROFILE_EVIDENCE_ID, DV_DURATION_EVIDENCE_ID),
        )
    if code == "unrecognized_dv_profile":
        return DvOutputEmissionGate(
            code,
            (
                "DV.pm warns and stops metadata extraction when DSF and VideoSType "
                "do not match a profile."
            ),
            (DV_HEADER_VALIDATION_EVIDENCE_ID, DV_PROFILE_EVIDENCE_ID),
        )
    return DvOutputEmissionGate(
        code,
        "DV stream output is gated.",
        (DV_READ_ONLY_DESCRIPTION_EVIDENCE_ID,),
    )


def _has_unsupported_gate(gates: tuple[DvOutputEmissionGate, ...]) -> bool:
    return any(
        gate.code
        in {
            "dv_signature_not_found",
            "truncated_dif_header",
            "truncated_dif_block",
        }
        for gate in gates
    )


def _unique_gates(gates: tuple[DvOutputEmissionGate, ...]) -> tuple[DvOutputEmissionGate, ...]:
    seen: set[DvEmissionGateCode] = set()
    result: list[DvOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        result.append(gate)
    return tuple(result)


def _unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        result.append(source)
    return tuple(result)
