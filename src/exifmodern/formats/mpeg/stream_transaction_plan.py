"""Source-backed, non-mutating MPEG stream transaction planning.

The planner mirrors ExifTool's MPEG.pm read responsibilities: validate the
program-stream start signature, scan MPEG start codes, route only the video
sequence and C0 audio stream headers ExifTool actively parses, preserve all
other payload bytes, and keep mutation/rewrite emission behind explicit gates.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from exifmodern.formats.id3.frame_transaction_plan import (
    Id3FramePlan,
    Id3FrameTransactionPlan,
    build_id3_frame_transaction_plan,
)
from exifmodern.read_graph import BinaryTagValue

MPEG_START_CODE_PREFIX = b"\x00\x00\x01"
MPEG_SCAN_LIMIT = 65536 * 4
MPEG_AUDIO_FRAME_SYNC_MASK = 0xFFE00000
MPEG_AUDIO_FRAME_SYNC_VALUE = 0xFFE00000
MP3_ID3V2_HEADER_SIZE = 10
MP3_ID3V2_MARKER = b"ID3"
MP3_ID3V1_TRAILER_SIZE = 128
MP3_ID3V1_ENHANCED_TRAILER_SIZE = 227
MP3_ID3V1_MARKER = b"TAG"
MP3_ID3V1_ENHANCED_MARKER = b"TAG+"

type MpegPlanStatus = Literal["planned", "unsupported"]
type MpegStartCodeRouteKind = Literal[
    "audio_stream_header",
    "pack_header_preserved",
    "program_control_preserved",
    "program_map_preserved_unparsed",
    "system_header_preserved",
    "private_stream_preserved",
    "padding_stream_preserved",
    "user_data_preserved_unmodeled",
    "video_elementary_stream_preserved_unparsed",
    "video_sequence_header",
    "unknown_payload_preserved",
]
type MpegPreservationKind = Literal[
    "media",
    "program_control",
    "system",
    "unknown",
    "user_data",
]
type MpegEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_initial_start_code",
    "unsupported_initial_start_code",
    "truncated_start_code_prefix",
    "truncated_video_sequence_header",
    "invalid_video_sequence_header",
    "invalid_audio_frame_header",
    "invalid_mp3_audio_layer",
    "mpeg_payload_size_rewrite_not_implemented",
    "mpeg_stream_rewrite_not_implemented",
]
type MpegResponsibilityKind = Literal[
    "aspect",
    "audio_bitrate",
    "audio_header",
    "comment_metadata",
    "duration",
    "resolution",
    "video_bitrate",
]
type Mp3Id3RenderedValueKind = Literal["text", "binary", "source_binary"]

MPEG_PM_SOURCE_PATH = "lib/Image/ExifTool/MPEG.pm"
ID3V1_TABLE_SOURCE = "id3.v1_table"
ID3V1_TRAILER_SOURCE = "id3.v1_trailer"
ID3V2_2_TABLE_SOURCE = "id3.v2_2_table"

MPEG_AUDIO_TABLE_SOURCE = "mpeg.audio_table"
MPEG_VIDEO_TABLE_SOURCE = "mpeg.video_table"
MPEG_COMPOSITE_SOURCE = "mpeg.composite"
MPEG_FRAME_HEADER_SOURCE = "mpeg.frame_header"
MPEG_AUDIO_PARSE_SOURCE = "mpeg.audio_parse"
MPEG_MP3_AUDIO_LAYER_SOURCE = "mpeg.mp3_audio_layer"
MPEG_VIDEO_PARSE_SOURCE = "mpeg.video_parse"
MPEG_TODO_STREAM_SOURCE = "mpeg.todo_stream"
MPEG_AUDIO_VIDEO_SCAN_SOURCE = "mpeg.audio_video_scan"
MPEG_PROCESS_SOURCE = "mpeg.process"
MPEG_MP3_ID3_BOUNDARY_SOURCE = "mpeg.mp3_id3_boundary"
MPEG_MP3_ID3_DECODE_STRING_SOURCE = "mpeg.mp3_id3_decode_string"
MPEG_MP3_ID3_FRAME_VALUE_SOURCE = "mpeg.mp3_id3_frame_value"
MPEG_MP3_ID3_PICTURE_SOURCE = "mpeg.mp3_id3_picture"
MPEG_MP3_ID3_GENRE_SOURCE = "mpeg.mp3_id3_genre"
MPEG_MP3_ID3V1_ENHANCED_SOURCE = "mpeg.mp3_id3v1_enhanced"
MPEG_MP3_ID3_COMPOSITE_SOURCE = "mpeg.mp3_id3_composite"
MPEG_COMMENT_ABSENCE_SOURCE = "mpeg.comment_absence"
MPEG_NON_MUTATING_SOURCE = "mpeg.non_mutating"

MPEG_TRANSACTION_SOURCES = (
    MPEG_PROCESS_SOURCE,
    MPEG_AUDIO_VIDEO_SCAN_SOURCE,
    MPEG_TODO_STREAM_SOURCE,
    MPEG_VIDEO_PARSE_SOURCE,
    MPEG_AUDIO_PARSE_SOURCE,
    MPEG_FRAME_HEADER_SOURCE,
    MPEG_VIDEO_TABLE_SOURCE,
    MPEG_AUDIO_TABLE_SOURCE,
    MPEG_COMPOSITE_SOURCE,
    MPEG_COMMENT_ABSENCE_SOURCE,
    MPEG_NON_MUTATING_SOURCE,
)

ASPECT_RATIOS: dict[int, float] = {
    1: 1.0,
    2: 0.6735,
    3: 0.7031,
    4: 0.7615,
    5: 0.8055,
    6: 0.8437,
    7: 0.8935,
    8: 0.9157,
    9: 0.9815,
    10: 1.0255,
    11: 1.0695,
    12: 1.0950,
    13: 1.1575,
    14: 1.2015,
}
ASPECT_DESCRIPTIONS: dict[int, str] = {
    1: "1:1",
    3: "16:9, 625 line, PAL",
    6: "16:9, 525 line, NTSC",
    8: "4:3, 625 line, PAL, CCIR601",
    12: "4:3, 525 line, NTSC, CCIR601",
}
FRAME_RATES: dict[int, float] = {
    1: 23.976,
    2: 24.0,
    3: 25.0,
    4: 29.97,
    5: 30.0,
    6: 50.0,
    7: 59.94,
    8: 60.0,
}
MPEG_AUDIO_VERSION_LABELS: dict[int, float] = {0: 2.5, 2: 2.0, 3: 1.0}
MPEG_AUDIO_LAYER_LABELS: dict[int, int] = {1: 3, 2: 2, 3: 1}
MPEG_SAMPLE_RATES: dict[int, dict[int, int]] = {
    3: {0: 44100, 1: 48000, 2: 32000},
    2: {0: 22050, 1: 24000, 2: 16000},
    0: {0: 11025, 1: 12000, 2: 8000},
}
MPEG_CHANNEL_MODES: dict[int, str] = {
    0: "Stereo",
    1: "Joint Stereo",
    2: "Dual Channel",
    3: "Single Channel",
}


@dataclass(frozen=True)
class MpegStartCodePlan:
    index: int
    offset: int
    code: int
    name: str
    payload_offset: int
    payload_end_offset: int
    payload_length: int
    route_kind: MpegStartCodeRouteKind
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpegVideoSequenceHeaderPlan:
    start_code_index: int
    offset: int
    width: int | None
    height: int | None
    aspect_ratio_code: int | None
    aspect_ratio: float | None
    aspect_description: str | None
    frame_rate_code: int | None
    frame_rate: float | None
    video_bitrate: int | None
    variable_bitrate: bool
    status: Literal["valid", "invalid", "truncated"]
    blocker_code: MpegEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpegAudioHeaderPlan:
    start_code_index: int | None
    stream_offset: int
    sync_offset: int
    raw_header: int
    version_id: int
    version: float | None
    layer_description: int
    audio_layer: int | None
    bitrate: int | None
    sample_rate: int | None
    channel_mode: str | None
    mode_extension: str | None
    ms_stereo: bool | None
    intensity_stereo: bool | None
    copyright_flag: bool | None
    original_media: bool | None
    emphasis: str | None
    status: Literal["valid", "invalid"]
    blocker_code: MpegEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpegStreamRoutePlan:
    start_code_index: int
    code: int
    route_kind: MpegStartCodeRouteKind
    parser: str | None
    payload_preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpegPayloadPreservationPlan:
    start_code_index: int
    code: int
    kind: MpegPreservationKind
    payload_offset: int
    payload_end_offset: int
    payload: bytes
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpegResponsibilityPlan:
    kind: MpegResponsibilityKind
    available: bool
    value: int | float | str | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpegDurationPlan:
    file_size: int
    id3_size: int
    audio_bitrate: int | None
    video_bitrate: int | None
    vbr_frames: int | None
    sample_rate: int | None
    audio_version_id: int | None
    approximate_seconds: float | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Mp3Id3RenderedFramePlan:
    group: str
    family_2_group: str
    tag_id: str
    name: str
    value_kind: Mp3Id3RenderedValueKind
    raw_value: str | bytes
    rendered_value: str
    relative_offset: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpegOutputEmissionGate:
    code: MpegEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MpegStreamTransactionPlan:
    status: MpegPlanStatus
    input_size: int
    scanned_size: int
    start_codes: tuple[MpegStartCodePlan, ...]
    routes: tuple[MpegStreamRoutePlan, ...]
    video_headers: tuple[MpegVideoSequenceHeaderPlan, ...]
    audio_headers: tuple[MpegAudioHeaderPlan, ...]
    preservation_actions: tuple[MpegPayloadPreservationPlan, ...]
    id3_rendered_frames: tuple[Mp3Id3RenderedFramePlan, ...]
    responsibilities: tuple[MpegResponsibilityPlan, ...]
    duration: MpegDurationPlan
    output_emission_gates: tuple[MpegOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"MPEG stream transaction output is gated: {gate_codes}")
        return self.original_bytes


def build_mpeg_stream_transaction_plan(
    mpeg_data: bytes,
    *,
    id3_size: int = 0,
    file_size: int | None = None,
    requested_user_data_comment: bytes | None = None,
    allow_output_emission: bool = False,
) -> MpegStreamTransactionPlan:
    scanned = mpeg_data[:MPEG_SCAN_LIMIT]
    gates: list[MpegOutputEmissionGate] = []
    status: MpegPlanStatus = "planned"
    initial_gate = _initial_validation_gate(scanned)
    if initial_gate is not None:
        gates.append(initial_gate)
        status = "unsupported"

    start_codes, scan_gates = scan_mpeg_start_codes(scanned)
    gates.extend(scan_gates)
    if scan_gates:
        status = "unsupported"

    routes = tuple(_route_start_code(start_code) for start_code in start_codes)
    video_headers = tuple(
        _parse_video_sequence_header(start_code, scanned)
        for start_code in start_codes
        if start_code.route_kind == "video_sequence_header"
    )
    audio_headers = _audio_headers_for_streams(start_codes, scanned)
    gates.extend(_header_gates(video_headers, audio_headers))

    preservation_actions = tuple(
        _preservation_action(start_code, scanned)
        for start_code in start_codes
        if _preservation_kind(start_code) is not None
    )
    input_size = len(mpeg_data) if file_size is None else file_size
    duration = _duration_plan(input_size, id3_size, audio_headers, video_headers)
    responsibilities = _responsibility_plans(video_headers, audio_headers, duration, start_codes)

    if requested_user_data_comment is not None:
        gates.extend(
            (
                MpegOutputEmissionGate(
                    "mpeg_payload_size_rewrite_not_implemented",
                    "MPEG user-data/comment replacement may change payload sizes.",
                    (MPEG_TODO_STREAM_SOURCE, MPEG_COMMENT_ABSENCE_SOURCE),
                ),
                MpegOutputEmissionGate(
                    "mpeg_stream_rewrite_not_implemented",
                    "MPEG stream byte rewriting is not implemented for this planner.",
                    (MPEG_AUDIO_VIDEO_SCAN_SOURCE, MPEG_NON_MUTATING_SOURCE),
                ),
            )
        )
    if not allow_output_emission:
        gates.append(
            MpegOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "MPEG stream transaction plans are non-mutating unless emission is explicit.",
                (MPEG_NON_MUTATING_SOURCE,),
            )
        )

    sources = unique_evidence_ids(
        (
            *MPEG_TRANSACTION_SOURCES,
            *(source for start_code in start_codes for source in start_code.evidence_ids),
            *(source for route in routes for source in route.evidence_ids),
            *(source for header in video_headers for source in header.evidence_ids),
            *(source for header in audio_headers for source in header.evidence_ids),
            *(source for action in preservation_actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return MpegStreamTransactionPlan(
        status=status,
        input_size=input_size,
        scanned_size=len(scanned),
        start_codes=start_codes,
        routes=routes,
        video_headers=video_headers,
        audio_headers=audio_headers,
        preservation_actions=preservation_actions,
        id3_rendered_frames=(),
        responsibilities=responsibilities,
        duration=duration,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_bytes=mpeg_data,
    )


plan_mpeg_stream_transaction = build_mpeg_stream_transaction_plan


def build_mp3_audio_transaction_plan(
    mp3_data: bytes,
    *,
    file_size: int | None = None,
    allow_output_emission: bool = False,
) -> MpegStreamTransactionPlan:
    """Plan ExifTool's MP3 direct audio-frame path after leading ID3 metadata."""

    leading_id3_size, audio_offset = _leading_id3v2_size(mp3_data)
    id3_size = leading_id3_size + _trailing_id3v1_size(mp3_data)
    id3_plan = build_id3_frame_transaction_plan(mp3_data)
    id3_rendered_frames = _mp3_id3_rendered_frames(mp3_data, id3_plan)
    audio_payload = mp3_data[audio_offset:]
    audio_header = _parse_audio_header(
        audio_payload,
        start_code_index=None,
        stream_offset=audio_offset,
        require_layer_3=True,
    )
    audio_headers = () if audio_header is None else (audio_header,)
    gates = list(_header_gates((), audio_headers))
    status: MpegPlanStatus = "planned"
    if audio_header is None:
        gates.append(
            MpegOutputEmissionGate(
                "invalid_audio_frame_header",
                "ParseMPEGAudio did not find a valid MPEG layer-3 audio frame header.",
                (MPEG_AUDIO_PARSE_SOURCE,),
            )
        )
        status = "unsupported"
    elif audio_header.status == "invalid":
        status = "unsupported"
    if not allow_output_emission:
        gates.append(
            MpegOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "MPEG stream transaction plans are non-mutating unless emission is explicit.",
                (MPEG_NON_MUTATING_SOURCE,),
            )
        )
    input_size = len(mp3_data) if file_size is None else file_size
    duration = _duration_plan(input_size, id3_size, audio_headers, ())
    sources = unique_evidence_ids(
        (
            MPEG_MP3_ID3_BOUNDARY_SOURCE,
            MPEG_AUDIO_PARSE_SOURCE,
            MPEG_AUDIO_TABLE_SOURCE,
            MPEG_COMPOSITE_SOURCE,
            MPEG_NON_MUTATING_SOURCE,
            *(source for frame in id3_rendered_frames for source in _id3_evidence_ids(frame)),
            *(source for header in audio_headers for source in header.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return MpegStreamTransactionPlan(
        status=status,
        input_size=input_size,
        scanned_size=min(len(mp3_data), MPEG_SCAN_LIMIT),
        start_codes=(),
        routes=(),
        video_headers=(),
        audio_headers=audio_headers,
        preservation_actions=(),
        id3_rendered_frames=id3_rendered_frames,
        responsibilities=_responsibility_plans((), audio_headers, duration, ()),
        duration=duration,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_bytes=mp3_data,
    )


def scan_mpeg_start_codes(
    mpeg_data: bytes,
) -> tuple[tuple[MpegStartCodePlan, ...], tuple[MpegOutputEmissionGate, ...]]:
    offsets: list[int] = []
    gates: list[MpegOutputEmissionGate] = []
    search_from = 0
    while True:
        offset = mpeg_data.find(MPEG_START_CODE_PREFIX, search_from)
        if offset < 0:
            break
        if offset + 4 > len(mpeg_data):
            gates.append(
                MpegOutputEmissionGate(
                    "truncated_start_code_prefix",
                    "Input ended after an MPEG start-code prefix but before the code byte.",
                    (MPEG_AUDIO_VIDEO_SCAN_SOURCE,),
                )
            )
            break
        offsets.append(offset)
        search_from = offset + 4

    start_codes: list[MpegStartCodePlan] = []
    for index, offset in enumerate(offsets):
        payload_offset = offset + 4
        payload_end = offsets[index + 1] if index + 1 < len(offsets) else len(mpeg_data)
        code = mpeg_data[offset + 3]
        route_kind = _route_kind_for_code(code)
        start_codes.append(
            MpegStartCodePlan(
                index=index,
                offset=offset,
                code=code,
                name=_start_code_name(code),
                payload_offset=payload_offset,
                payload_end_offset=payload_end,
                payload_length=payload_end - payload_offset,
                route_kind=route_kind,
                evidence_ids=_start_code_sources(route_kind),
            )
        )
    return tuple(start_codes), tuple(gates)


def _initial_validation_gate(mpeg_data: bytes) -> MpegOutputEmissionGate | None:
    if len(mpeg_data) < 4:
        return MpegOutputEmissionGate(
            "truncated_initial_start_code",
            "ProcessMPEG requires four bytes for the initial MPEG start code.",
            (MPEG_PROCESS_SOURCE,),
        )
    if not (mpeg_data.startswith(MPEG_START_CODE_PREFIX) and 0xB0 <= mpeg_data[3] <= 0xBF):
        return MpegOutputEmissionGate(
            "unsupported_initial_start_code",
            "ProcessMPEG only accepts initial start codes in the B0-BF range.",
            (MPEG_PROCESS_SOURCE,),
        )
    return None


def _audio_headers_for_streams(
    start_codes: tuple[MpegStartCodePlan, ...], mpeg_data: bytes
) -> tuple[MpegAudioHeaderPlan, ...]:
    headers: list[MpegAudioHeaderPlan] = []
    first_modeled_start = next(
        (
            start_code
            for start_code in start_codes
            if start_code.route_kind in {"video_sequence_header", "audio_stream_header"}
        ),
        None,
    )
    if first_modeled_start is not None:
        prefix = mpeg_data[: max(0, first_modeled_start.payload_offset - 3)]
        prefix_header = _parse_audio_header(prefix, start_code_index=None, stream_offset=0)
        if prefix_header is not None and prefix_header.status == "valid":
            headers.append(prefix_header)

    for start_code in start_codes:
        if start_code.route_kind != "audio_stream_header":
            continue
        payload = mpeg_data[start_code.payload_offset : start_code.payload_end_offset]
        candidate = _parse_audio_header(
            payload[:256],
            start_code_index=start_code.index,
            stream_offset=start_code.payload_offset,
        )
        if candidate is not None:
            headers.append(candidate)
    return tuple(headers)


def _parse_audio_header(
    payload: bytes,
    *,
    start_code_index: int | None,
    stream_offset: int,
    require_layer_3: bool = False,
) -> MpegAudioHeaderPlan | None:
    search_from = 0
    while True:
        local_offset = payload.find(b"\xff", search_from)
        if local_offset < 0 or local_offset + 4 > len(payload):
            return None
        word = int.from_bytes(payload[local_offset : local_offset + 4], "big")
        if (word & MPEG_AUDIO_FRAME_SYNC_MASK) != MPEG_AUDIO_FRAME_SYNC_VALUE:
            search_from = local_offset + 1
            continue
        header = _decode_audio_word(
            word,
            start_code_index=start_code_index,
            stream_offset=stream_offset,
            sync_offset=stream_offset + local_offset,
        )
        if require_layer_3 and header.audio_layer != 3:
            return _mp3_layer_gate_header(header)
        return header


def _decode_audio_word(
    word: int, *, start_code_index: int | None, stream_offset: int, sync_offset: int
) -> MpegAudioHeaderPlan:
    version_id = (word >> 19) & 0x03
    layer_description = (word >> 17) & 0x03
    bitrate_index = (word >> 12) & 0x0F
    sample_rate_index = (word >> 10) & 0x03
    channel_mode_index = (word >> 6) & 0x03
    mode_extension = (word >> 4) & 0x03
    layer = MPEG_AUDIO_LAYER_LABELS.get(layer_description)
    emphasis = word & 0x03
    blocker = _audio_header_blocker(
        version_id, layer_description, bitrate_index, sample_rate_index, emphasis
    )
    bitrate = (
        _audio_bitrate(version_id, layer_description, bitrate_index) if blocker is None else None
    )
    sample_rate = MPEG_SAMPLE_RATES.get(version_id, {}).get(sample_rate_index)
    return MpegAudioHeaderPlan(
        start_code_index=start_code_index,
        stream_offset=stream_offset,
        sync_offset=sync_offset,
        raw_header=word,
        version_id=version_id,
        version=MPEG_AUDIO_VERSION_LABELS.get(version_id),
        layer_description=layer_description,
        audio_layer=layer,
        bitrate=bitrate,
        sample_rate=sample_rate,
        channel_mode=MPEG_CHANNEL_MODES.get(channel_mode_index),
        mode_extension=_mode_extension_description(mode_extension) if layer in {1, 2} else None,
        ms_stereo=bool(mode_extension & 0x02) if layer == 3 else None,
        intensity_stereo=bool(mode_extension & 0x01) if layer == 3 else None,
        copyright_flag=bool((word >> 3) & 0x01),
        original_media=bool((word >> 2) & 0x01),
        emphasis=_emphasis_description(emphasis),
        status="valid" if blocker is None else "invalid",
        blocker_code=blocker,
        evidence_ids=(MPEG_AUDIO_PARSE_SOURCE, MPEG_AUDIO_TABLE_SOURCE),
    )


def _mp3_layer_gate_header(header: MpegAudioHeaderPlan) -> MpegAudioHeaderPlan:
    return MpegAudioHeaderPlan(
        start_code_index=header.start_code_index,
        stream_offset=header.stream_offset,
        sync_offset=header.sync_offset,
        raw_header=header.raw_header,
        version_id=header.version_id,
        version=header.version,
        layer_description=header.layer_description,
        audio_layer=header.audio_layer,
        bitrate=None,
        sample_rate=header.sample_rate,
        channel_mode=header.channel_mode,
        mode_extension=header.mode_extension,
        ms_stereo=header.ms_stereo,
        intensity_stereo=header.intensity_stereo,
        copyright_flag=header.copyright_flag,
        original_media=header.original_media,
        emphasis=header.emphasis,
        status="invalid",
        blocker_code="invalid_mp3_audio_layer",
        evidence_ids=unique_evidence_ids((*header.evidence_ids, MPEG_MP3_AUDIO_LAYER_SOURCE)),
    )


def _audio_header_blocker(
    version_id: int,
    layer_description: int,
    bitrate_index: int,
    sample_rate_index: int,
    emphasis: int,
) -> MpegEmissionGateCode | None:
    if version_id == 1:
        return "invalid_audio_frame_header"
    if layer_description == 0:
        return "invalid_audio_frame_header"
    if bitrate_index in {0, 15}:
        return "invalid_audio_frame_header"
    if sample_rate_index == 3:
        return "invalid_audio_frame_header"
    if emphasis == 2:
        return "invalid_audio_frame_header"
    return None


def _audio_bitrate(version_id: int, layer_description: int, bitrate_index: int) -> int | None:
    if version_id == 3 and layer_description == 3:
        table = (
            0,
            32000,
            64000,
            96000,
            128000,
            160000,
            192000,
            224000,
            256000,
            288000,
            320000,
            352000,
            384000,
            416000,
            448000,
        )
    elif version_id == 3 and layer_description == 2:
        table = (
            0,
            32000,
            48000,
            56000,
            64000,
            80000,
            96000,
            112000,
            128000,
            160000,
            192000,
            224000,
            256000,
            320000,
            384000,
        )
    elif version_id == 3 and layer_description == 1:
        table = (
            0,
            32000,
            40000,
            48000,
            56000,
            64000,
            80000,
            96000,
            112000,
            128000,
            160000,
            192000,
            224000,
            256000,
            320000,
        )
    elif version_id != 3 and layer_description == 3:
        table = (
            0,
            32000,
            48000,
            56000,
            64000,
            80000,
            96000,
            112000,
            128000,
            144000,
            160000,
            176000,
            192000,
            224000,
            256000,
        )
    else:
        table = (
            0,
            8000,
            16000,
            24000,
            32000,
            40000,
            48000,
            56000,
            64000,
            80000,
            96000,
            112000,
            128000,
            144000,
            160000,
        )
    if 0 <= bitrate_index < len(table):
        return table[bitrate_index]
    return None


def _emphasis_description(emphasis: int) -> str | None:
    return {
        0: "None",
        1: "50/15 ms",
        2: "reserved",
        3: "CCIT J.17",
    }.get(emphasis)


def _mode_extension_description(mode_extension: int) -> str | None:
    return {
        0: "Bands 4-31",
        1: "Bands 8-31",
        2: "Bands 12-31",
        3: "Bands 16-31",
    }.get(mode_extension)


def _parse_video_sequence_header(
    start_code: MpegStartCodePlan, mpeg_data: bytes
) -> MpegVideoSequenceHeaderPlan:
    payload = mpeg_data[start_code.payload_offset : start_code.payload_end_offset]
    if len(payload) < 8:
        return MpegVideoSequenceHeaderPlan(
            start_code_index=start_code.index,
            offset=start_code.payload_offset,
            width=None,
            height=None,
            aspect_ratio_code=None,
            aspect_ratio=None,
            aspect_description=None,
            frame_rate_code=None,
            frame_rate=None,
            video_bitrate=None,
            variable_bitrate=False,
            status="truncated",
            blocker_code="truncated_video_sequence_header",
            evidence_ids=(MPEG_VIDEO_PARSE_SOURCE, MPEG_VIDEO_TABLE_SOURCE),
        )
    word1 = int.from_bytes(payload[:4], "big")
    word2 = int.from_bytes(payload[4:8], "big")
    width = (word1 >> 20) & 0xFFF
    height = (word1 >> 8) & 0xFFF
    aspect_code = (word1 >> 4) & 0x0F
    frame_rate_code = word1 & 0x0F
    raw_bitrate = (word2 >> 14) & 0x3FFFF
    invalid = aspect_code in {0, 15} or frame_rate_code == 0 or frame_rate_code > 8
    return MpegVideoSequenceHeaderPlan(
        start_code_index=start_code.index,
        offset=start_code.payload_offset,
        width=width,
        height=height,
        aspect_ratio_code=aspect_code,
        aspect_ratio=ASPECT_RATIOS.get(aspect_code),
        aspect_description=ASPECT_DESCRIPTIONS.get(
            aspect_code, str(ASPECT_RATIOS.get(aspect_code))
        ),
        frame_rate_code=frame_rate_code,
        frame_rate=FRAME_RATES.get(frame_rate_code),
        video_bitrate=None if raw_bitrate == 0x3FFFF else raw_bitrate * 400,
        variable_bitrate=raw_bitrate == 0x3FFFF,
        status="invalid" if invalid else "valid",
        blocker_code="invalid_video_sequence_header" if invalid else None,
        evidence_ids=(
            MPEG_VIDEO_PARSE_SOURCE,
            MPEG_VIDEO_TABLE_SOURCE,
            MPEG_FRAME_HEADER_SOURCE,
        ),
    )


def _duration_plan(
    file_size: int,
    id3_size: int,
    audio_headers: tuple[MpegAudioHeaderPlan, ...],
    video_headers: tuple[MpegVideoSequenceHeaderPlan, ...],
) -> MpegDurationPlan:
    audio_header = next((header for header in audio_headers if header.status == "valid"), None)
    video_header = next((header for header in video_headers if header.status == "valid"), None)
    audio_bitrate = audio_header.bitrate if audio_header is not None else None
    video_bitrate = video_header.video_bitrate if video_header is not None else None
    total_bitrate = (audio_bitrate or 0) + (video_bitrate or 0)
    approximate = None
    if total_bitrate:
        approximate = (8 * (file_size - id3_size)) / total_bitrate
    return MpegDurationPlan(
        file_size=file_size,
        id3_size=id3_size,
        audio_bitrate=audio_bitrate,
        video_bitrate=video_bitrate,
        vbr_frames=None,
        sample_rate=audio_header.sample_rate if audio_header is not None else None,
        audio_version_id=audio_header.version_id if audio_header is not None else None,
        approximate_seconds=approximate,
        evidence_ids=(MPEG_COMPOSITE_SOURCE,),
    )


def _responsibility_plans(
    video_headers: tuple[MpegVideoSequenceHeaderPlan, ...],
    audio_headers: tuple[MpegAudioHeaderPlan, ...],
    duration: MpegDurationPlan,
    start_codes: tuple[MpegStartCodePlan, ...],
) -> tuple[MpegResponsibilityPlan, ...]:
    video_header = next((header for header in video_headers if header.status == "valid"), None)
    audio_header = next((header for header in audio_headers if header.status == "valid"), None)
    has_user_data = any(start_code.code == 0xB2 for start_code in start_codes)
    resolution = None
    if (
        video_header is not None
        and video_header.width is not None
        and video_header.height is not None
    ):
        resolution = f"{video_header.width}x{video_header.height}"
    return (
        MpegResponsibilityPlan(
            "resolution",
            resolution is not None,
            resolution,
            "ImageWidth and ImageHeight come from MPEG video sequence-header bits.",
            (MPEG_VIDEO_TABLE_SOURCE,),
        ),
        MpegResponsibilityPlan(
            "aspect",
            video_header is not None and video_header.aspect_ratio is not None,
            video_header.aspect_ratio if video_header is not None else None,
            "AspectRatio is modeled by the video table and validated by ProcessMPEGVideo.",
            (MPEG_VIDEO_TABLE_SOURCE, MPEG_VIDEO_PARSE_SOURCE),
        ),
        MpegResponsibilityPlan(
            "video_bitrate",
            video_header is not None and video_header.video_bitrate is not None,
            video_header.video_bitrate if video_header is not None else None,
            "VideoBitrate is extracted from sequence-header bits; 0x3ffff means Variable.",
            (MPEG_VIDEO_TABLE_SOURCE,),
        ),
        MpegResponsibilityPlan(
            "audio_bitrate",
            audio_header is not None and audio_header.bitrate is not None,
            audio_header.bitrate if audio_header is not None else None,
            "AudioBitrate is selected from MPEG version/layer bitrate tables.",
            (MPEG_AUDIO_TABLE_SOURCE, MPEG_AUDIO_PARSE_SOURCE),
        ),
        MpegResponsibilityPlan(
            "audio_header",
            audio_header is not None,
            (
                None
                if audio_header is None
                else (
                    f"version={audio_header.version}, layer={audio_header.audio_layer}, "
                    f"sample_rate={audio_header.sample_rate}, "
                    f"channel_mode={audio_header.channel_mode}"
                )
            ),
            "ParseMPEGAudio extracts the first valid MPEG audio frame-header bit fields.",
            (MPEG_AUDIO_PARSE_SOURCE, MPEG_AUDIO_TABLE_SOURCE),
        ),
        MpegResponsibilityPlan(
            "duration",
            duration.approximate_seconds is not None,
            duration.approximate_seconds,
            "Duration is approximate from file size and numeric audio/video bitrates.",
            (MPEG_COMPOSITE_SOURCE,),
        ),
        MpegResponsibilityPlan(
            "comment_metadata",
            False,
            "user_data_preserved" if has_user_data else None,
            "MPEG.pm does not model user-data/comment tags; B2 payloads are preserved.",
            (MPEG_COMMENT_ABSENCE_SOURCE, MPEG_TODO_STREAM_SOURCE),
        ),
    )


def _header_gates(
    video_headers: tuple[MpegVideoSequenceHeaderPlan, ...],
    audio_headers: tuple[MpegAudioHeaderPlan, ...],
) -> tuple[MpegOutputEmissionGate, ...]:
    gates: list[MpegOutputEmissionGate] = []
    for video_header in video_headers:
        if video_header.blocker_code is not None:
            gates.append(
                MpegOutputEmissionGate(
                    video_header.blocker_code,
                    "A modeled MPEG video sequence header is invalid or truncated.",
                    video_header.evidence_ids,
                )
            )
    for audio_header in audio_headers:
        if audio_header.blocker_code is not None:
            gates.append(
                MpegOutputEmissionGate(
                    audio_header.blocker_code,
                    "A modeled MPEG audio frame header uses a reserved value.",
                    audio_header.evidence_ids,
                )
            )
    return tuple(gates)


def _route_start_code(start_code: MpegStartCodePlan) -> MpegStreamRoutePlan:
    parser = None
    if start_code.route_kind == "video_sequence_header":
        parser = "ProcessMPEGVideo"
    elif start_code.route_kind == "audio_stream_header":
        parser = "ParseMPEGAudio"
    return MpegStreamRoutePlan(
        start_code_index=start_code.index,
        code=start_code.code,
        route_kind=start_code.route_kind,
        parser=parser,
        payload_preserved=parser is None,
        evidence_ids=start_code.evidence_ids,
    )


def _preservation_action(
    start_code: MpegStartCodePlan, mpeg_data: bytes
) -> MpegPayloadPreservationPlan:
    kind = _preservation_kind(start_code)
    if kind is None:
        kind = "media"
    return MpegPayloadPreservationPlan(
        start_code_index=start_code.index,
        code=start_code.code,
        kind=kind,
        payload_offset=start_code.payload_offset,
        payload_end_offset=start_code.payload_end_offset,
        payload=mpeg_data[start_code.payload_offset : start_code.payload_end_offset],
        reason=_preservation_reason(kind),
        evidence_ids=start_code.evidence_ids,
    )


def _preservation_kind(start_code: MpegStartCodePlan) -> MpegPreservationKind | None:
    if start_code.route_kind in {"video_sequence_header", "audio_stream_header"}:
        return None
    if start_code.route_kind == "user_data_preserved_unmodeled":
        return "user_data"
    if start_code.route_kind in {
        "pack_header_preserved",
        "program_control_preserved",
        "program_map_preserved_unparsed",
        "padding_stream_preserved",
        "private_stream_preserved",
    }:
        return "program_control"
    if start_code.route_kind == "system_header_preserved":
        return "system"
    if start_code.route_kind == "video_elementary_stream_preserved_unparsed":
        return "media"
    return "unknown"


def _preservation_reason(kind: MpegPreservationKind) -> str:
    if kind == "user_data":
        return "Preserve MPEG user-data payload because MPEG.pm has no comment tag table."
    if kind == "system":
        return "Preserve system-header bytes; MPEG.pm documents this stream code as TODO."
    if kind == "program_control":
        return "Preserve MPEG program/control payload bytes unchanged."
    if kind == "media":
        return "Preserve MPEG elementary media payload bytes unchanged."
    return "Preserve unmodeled MPEG payload bytes unchanged."


def _route_kind_for_code(code: int) -> MpegStartCodeRouteKind:
    if code == 0xB2:
        return "user_data_preserved_unmodeled"
    if code == 0xB3:
        return "video_sequence_header"
    if code in {0xB0, 0xB1, 0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9}:
        return "program_control_preserved"
    if code == 0xBA:
        return "pack_header_preserved"
    if code == 0xBB:
        return "system_header_preserved"
    if code == 0xBC:
        return "program_map_preserved_unparsed"
    if code in {0xBD, 0xBF}:
        return "private_stream_preserved"
    if code == 0xBE:
        return "padding_stream_preserved"
    if code == 0xC0:
        return "audio_stream_header"
    if 0xC1 <= code <= 0xDF:
        return "unknown_payload_preserved"
    if 0xE0 <= code <= 0xEF:
        return "video_elementary_stream_preserved_unparsed"
    return "unknown_payload_preserved"


def _start_code_name(code: int) -> str:
    names = {
        0xB2: "user data",
        0xB3: "sequence header",
        0xB7: "sequence end",
        0xB9: "program end",
        0xBA: "pack header",
        0xBB: "system header",
        0xBC: "program stream map",
        0xBD: "private stream 1",
        0xBE: "padding stream",
        0xBF: "private stream 2",
        0xC0: "audio stream 0",
    }
    if code in names:
        return names[code]
    if 0xC0 <= code <= 0xDF:
        return f"audio stream {code - 0xC0}"
    if 0xE0 <= code <= 0xEF:
        return f"video stream {code - 0xE0}"
    return f"start code 0x{code:02x}"


def _start_code_sources(route_kind: MpegStartCodeRouteKind) -> tuple[str, ...]:
    if route_kind == "video_sequence_header":
        return (MPEG_AUDIO_VIDEO_SCAN_SOURCE, MPEG_VIDEO_PARSE_SOURCE)
    if route_kind == "audio_stream_header":
        return (MPEG_AUDIO_VIDEO_SCAN_SOURCE, MPEG_AUDIO_PARSE_SOURCE)
    if route_kind == "user_data_preserved_unmodeled":
        return (MPEG_TODO_STREAM_SOURCE, MPEG_COMMENT_ABSENCE_SOURCE)
    return (MPEG_TODO_STREAM_SOURCE, MPEG_AUDIO_VIDEO_SCAN_SOURCE)


def _leading_id3v2_size(data: bytes) -> tuple[int, int]:
    if not data.startswith(MP3_ID3V2_MARKER) or len(data) < MP3_ID3V2_HEADER_SIZE:
        return 0, 0
    size = _syncsafe_size(data[6:10])
    if size is None:
        return 0, 0
    id3_size = MP3_ID3V2_HEADER_SIZE + size
    if id3_size > len(data):
        return 0, 0
    return id3_size, id3_size


def _trailing_id3v1_size(data: bytes) -> int:
    if len(data) < MP3_ID3V1_TRAILER_SIZE:
        return 0
    if data[-MP3_ID3V1_TRAILER_SIZE:].startswith(MP3_ID3V1_MARKER):
        return MP3_ID3V1_TRAILER_SIZE
    return 0


def _mp3_id3_rendered_frames(
    data: bytes, id3_plan: Id3FrameTransactionPlan
) -> tuple[Mp3Id3RenderedFramePlan, ...]:
    rendered: list[Mp3Id3RenderedFramePlan] = []
    if id3_plan.id3v2_database is not None and id3_plan.id3v2_header.version_name == "ID3v2_2":
        for frame in id3_plan.id3v2_frames:
            rendered.extend(_mp3_id3v22_frame_rendered_frames(data, frame))
    elif id3_plan.id3v2_header.version_name in {"ID3v2_3", "ID3v2_4"}:
        for frame in id3_plan.id3v2_frames:
            rendered_frame = _mp3_id3v23_v24_frame_rendered_frame(data, frame, id3_plan)
            if rendered_frame is not None:
                rendered.append(rendered_frame)
    rendered.extend(_mp3_unknown_id3_binary_frames(id3_plan))
    rendered.extend(_mp3_id3v1_rendered_frames(id3_plan))
    rendered.extend(_mp3_id3v1_enhanced_rendered_frames(data, id3_plan))
    composite = _mp3_id3_datetime_original(rendered)
    if composite is not None:
        rendered.append(composite)
    return tuple(rendered)


class _MpegEvidenceCarrier(Protocol):
    @property
    def evidence_ids(self) -> tuple[str, ...]: ...


def _id3_evidence_ids(carrier: _MpegEvidenceCarrier) -> tuple[str, ...]:
    return carrier.evidence_ids


def _mp3_unknown_id3_binary_frames(
    id3_plan: Id3FrameTransactionPlan,
) -> tuple[Mp3Id3RenderedFramePlan, ...]:
    group = id3_plan.id3v2_header.version_name
    if group is None or group == "ID3v2_2":
        return ()
    return tuple(
        Mp3Id3RenderedFramePlan(
            group=group,
            family_2_group="Audio",
            tag_id=preservation.sanitized_frame_id,
            name=preservation.tag_name,
            value_kind="source_binary",
            raw_value=preservation.payload,
            rendered_value=(
                f"(Binary data {preservation.payload_size} bytes, use -b option to extract)"
            ),
            relative_offset=preservation.payload_offset,
            evidence_ids=_id3_evidence_ids(preservation),
        )
        for preservation in id3_plan.unknown_binary_preservations
    )


def _mp3_id3v23_v24_frame_rendered_frame(
    data: bytes,
    frame: Id3FramePlan,
    id3_plan: Id3FrameTransactionPlan,
) -> Mp3Id3RenderedFramePlan | None:
    version_name = id3_plan.id3v2_header.version_name
    if version_name not in {"ID3v2_3", "ID3v2_4"}:
        return None
    from exifmodern.formats.riff.id3_payload_reader import (
        id3v2_frame_tag as exiftool_id3v2_frame_tag,
    )

    rendered = exiftool_id3v2_frame_tag(data, frame, version_name)
    if rendered is None:
        return None
    raw_value: str | bytes
    rendered_value: str
    value_kind: Mp3Id3RenderedValueKind
    if isinstance(rendered.raw_value, BinaryTagValue) and frame.routing.route_kind == "private":
        raw_value = rendered.raw_value.data
        rendered_value = (
            f"(Binary data {rendered.raw_value.byte_count} bytes, use -b option to extract)"
        )
        value_kind = "source_binary"
    elif isinstance(rendered.rendered_value, BinaryTagValue):
        raw_value = rendered.rendered_value.data
        rendered_value = f"(Binary data {rendered.rendered_value.byte_count} bytes)"
        value_kind = "binary"
    elif isinstance(rendered.raw_value, BinaryTagValue):
        raw_value = rendered.raw_value.data
        rendered_value = str(rendered.rendered_value)
        value_kind = "source_binary"
    else:
        raw_value = str(rendered.raw_value)
        rendered_value = str(rendered.rendered_value)
        value_kind = "text"
    return Mp3Id3RenderedFramePlan(
        group=version_name,
        family_2_group=rendered.group,
        tag_id=rendered.tag_id,
        name=rendered.name,
        value_kind=value_kind,
        raw_value=raw_value,
        rendered_value=rendered_value,
        relative_offset=rendered.relative_offset,
        evidence_ids=(),
    )


def _mp3_id3v22_frame_rendered_frames(
    data: bytes, frame: Id3FramePlan
) -> tuple[Mp3Id3RenderedFramePlan, ...]:
    payload = data[frame.payload_offset : frame.payload_offset + frame.payload_size]
    tag_name = _MP3_ID3V22_TAG_NAMES.get(frame.frame_id, frame.routing.tag_name)
    if frame.routing.route_kind == "text" or (
        frame.frame_id in _MP3_ID3V22_TAG_NAMES and frame.frame_id.startswith("T")
    ):
        value = _decode_id3_text(payload)
        if value is None:
            return ()
        return (
            _mp3_id3_text_frame(
                "ID3v2_2",
                _id3v22_family_2_group(tag_name, frame.frame_id),
                frame.frame_id,
                tag_name,
                value,
                frame.payload_offset,
                (
                    *_id3_evidence_ids(frame),
                    ID3V2_2_TABLE_SOURCE,
                    MPEG_MP3_ID3_DECODE_STRING_SOURCE,
                ),
            ),
        )
    if frame.frame_id in {"COM", "ULT"}:
        value = _decode_id3_comment(payload)
        if value is None:
            return ()
        return (
            _mp3_id3_text_frame(
                "ID3v2_2",
                "Audio",
                frame.frame_id,
                tag_name,
                value,
                frame.payload_offset,
                (
                    *_id3_evidence_ids(frame),
                    ID3V2_2_TABLE_SOURCE,
                    MPEG_MP3_ID3_FRAME_VALUE_SOURCE,
                ),
            ),
        )
    if frame.frame_id == "RVA":
        value = _decode_id3_rva(payload)
        if value is None:
            return ()
        return (
            _mp3_id3_text_frame(
                "ID3v2_2",
                "Audio",
                frame.frame_id,
                tag_name,
                value,
                frame.payload_offset,
                (
                    *_id3_evidence_ids(frame),
                    ID3V2_2_TABLE_SOURCE,
                    MPEG_MP3_ID3_FRAME_VALUE_SOURCE,
                ),
            ),
        )
    if frame.frame_id == "PIC":
        return _mp3_id3_pic_rendered_frames(payload, frame)
    return ()


def _mp3_id3_pic_rendered_frames(
    payload: bytes, frame: Id3FramePlan
) -> tuple[Mp3Id3RenderedFramePlan, ...]:
    parsed = _parse_id3_pic(payload)
    if parsed is None:
        return ()
    image_format, picture_type, description, picture = parsed
    sources = unique_evidence_ids(
        (
            *_id3_evidence_ids(frame),
            ID3V2_2_TABLE_SOURCE,
            MPEG_MP3_ID3_PICTURE_SOURCE,
            MPEG_MP3_ID3_FRAME_VALUE_SOURCE,
            MPEG_MP3_ID3_DECODE_STRING_SOURCE,
        )
    )
    return (
        _mp3_id3_text_frame(
            "ID3v2_2",
            "Image",
            "PIC-1",
            "PictureFormat",
            image_format,
            frame.payload_offset + 1,
            sources,
        ),
        _mp3_id3_text_frame(
            "ID3v2_2",
            "Image",
            "PIC-2",
            "PictureType",
            picture_type,
            frame.payload_offset + 4,
            sources,
        ),
        _mp3_id3_text_frame(
            "ID3v2_2",
            "Image",
            "PIC-3",
            "PictureDescription",
            description,
            frame.payload_offset + 5,
            sources,
        ),
        Mp3Id3RenderedFramePlan(
            group="ID3v2_2",
            family_2_group="Preview",
            tag_id="PIC",
            name="Picture",
            value_kind="binary",
            raw_value=picture,
            rendered_value=f"(Binary data {len(picture)} bytes)",
            relative_offset=frame.payload_offset,
            evidence_ids=sources,
        ),
    )


def _mp3_id3v1_rendered_frames(
    id3_plan: Id3FrameTransactionPlan,
) -> tuple[Mp3Id3RenderedFramePlan, ...]:
    if not id3_plan.id3v1_trailer.present:
        return ()
    rendered: list[Mp3Id3RenderedFramePlan] = []
    for field in id3_plan.id3v1_trailer.fields:
        value = _render_id3v1_field(field.name, field.value)
        if value is None:
            continue
        rendered.append(
            _mp3_id3_text_frame(
                "ID3v1",
                _id3v1_family_2_group(field.name),
                str(field.value_offset - (id3_plan.id3v1_trailer.offset or 0)),
                field.name,
                value,
                field.value_offset,
                (
                    *_id3_evidence_ids(field),
                    ID3V1_TABLE_SOURCE,
                    ID3V1_TRAILER_SOURCE,
                    MPEG_MP3_ID3_GENRE_SOURCE,
                ),
            )
        )
    return tuple(rendered)


def _mp3_id3v1_enhanced_rendered_frames(
    data: bytes,
    id3_plan: Id3FrameTransactionPlan,
) -> tuple[Mp3Id3RenderedFramePlan, ...]:
    trailer_offset = id3_plan.id3v1_trailer.offset
    if trailer_offset is None:
        return ()
    enhanced_offset = trailer_offset - MP3_ID3V1_ENHANCED_TRAILER_SIZE
    if enhanced_offset < 0:
        return ()
    enhanced = data[enhanced_offset:trailer_offset]
    if len(enhanced) != MP3_ID3V1_ENHANCED_TRAILER_SIZE:
        return ()
    if not enhanced.startswith(MP3_ID3V1_ENHANCED_MARKER):
        return ()
    rendered: list[Mp3Id3RenderedFramePlan] = []
    for field in _ID3V1_ENHANCED_FIELDS:
        raw_value = enhanced[field.offset : field.offset + field.size]
        value = _render_id3v1_enhanced_field(field.name, raw_value)
        if value is None:
            continue
        rendered.append(
            _mp3_id3_text_frame(
                "ID3v1_Enh",
                field.family_2_group,
                str(field.offset),
                field.name,
                value,
                enhanced_offset + field.offset,
                (MPEG_MP3_ID3V1_ENHANCED_SOURCE, ID3V1_TRAILER_SOURCE),
            )
        )
    return tuple(rendered)


def _mp3_id3_datetime_original(
    rendered: list[Mp3Id3RenderedFramePlan],
) -> Mp3Id3RenderedFramePlan | None:
    year = next(
        (
            frame.rendered_value
            for frame in rendered
            if frame.group.startswith("ID3v2") and frame.name == "Year" and frame.rendered_value
        ),
        None,
    )
    if year is None:
        return None
    return _mp3_id3_text_frame(
        "Composite",
        "Time",
        "ID3-DateTimeOriginal",
        "DateTimeOriginal",
        year,
        -1,
        (MPEG_MP3_ID3_COMPOSITE_SOURCE,),
    )


def _mp3_id3_text_frame(
    group: str,
    family_2_group: str,
    tag_id: str,
    name: str,
    value: str,
    relative_offset: int,
    sources: tuple[str, ...],
) -> Mp3Id3RenderedFramePlan:
    return Mp3Id3RenderedFramePlan(
        group=group,
        family_2_group=family_2_group,
        tag_id=tag_id,
        name=name,
        value_kind="text",
        raw_value=value,
        rendered_value=value,
        relative_offset=relative_offset,
        evidence_ids=unique_evidence_ids(sources),
    )


def _decode_id3_text(payload: bytes) -> str | None:
    parts = _decode_id3_strings(payload)
    if parts is None:
        return None
    return "/".join(parts)


def _decode_id3_comment(payload: bytes) -> str | None:
    if len(payload) <= 4:
        return None
    parts = _decode_id3_strings(payload[4:], payload[0])
    if parts is None:
        return None
    description = parts[0] if parts else ""
    text = parts[1] if len(parts) > 1 else ""
    return f"({description}) {text}" if description else text


def _decode_id3_strings(payload: bytes, encoding: int | None = None) -> tuple[str, ...] | None:
    if not payload:
        return ("",)
    text_bytes = payload
    if encoding is None:
        encoding = payload[0]
        text_bytes = payload[1:]
    if encoding == 0:
        return tuple(part.decode("latin-1") for part in text_bytes.rstrip(b"\x00").split(b"\x00"))
    if encoding == 3:
        return tuple(
            part.decode("utf-8", errors="replace")
            for part in text_bytes.rstrip(b"\x00").split(b"\x00")
        )
    if encoding in {1, 2}:
        return _decode_utf16_id3_strings(text_bytes, encoding)
    stripped = text_bytes.rstrip(b"\x00").decode("latin-1")
    return (f"<Unknown encoding {encoding}> {stripped}",)


def _decode_utf16_id3_strings(payload: bytes, encoding: int) -> tuple[str, ...]:
    delimiter = b"\x00\x00"
    parts: list[bytes] = []
    start = 0
    index = 0
    while index + 1 < len(payload):
        if payload[index : index + 2] == delimiter and (index - start) % 2 == 0:
            parts.append(payload[start:index])
            start = index + 2
            index = start
            continue
        index += 2
    if start < len(payload):
        parts.append(payload[start:])
    codec = "utf-16-be" if encoding == 2 else "utf-16"
    return tuple(part.decode(codec, errors="replace") if part else "" for part in parts)


def _decode_id3_rva(payload: bytes) -> str | None:
    if len(payload) < 2:
        return None
    flags = payload[0]
    bits = payload[1]
    if bits == 0:
        return None
    field_bytes = (bits + 7) // 8
    values = payload[2:]
    denominator = (1 << bits) - 1
    parsed: list[str] = []
    for channel, relative_index, peak_index, sign_flag in (
        ("Right", 0, 2, 0x01),
        ("Left", 1, 3, 0x02),
        ("Back-right", 4, 6, 0x04),
        ("Back-left", 5, 7, 0x08),
        ("Center", 8, 9, 0x10),
        ("Bass", 10, 11, 0x20),
    ):
        peak_start = peak_index * field_bytes
        if len(values) < peak_start + field_bytes:
            break
        relative_start = relative_index * field_bytes
        relative = int.from_bytes(values[relative_start : relative_start + field_bytes], "big")
        if not flags & sign_flag:
            relative = -relative
        parsed.append(f"{100 * relative / denominator:+.1f}% {channel}")
    return ", ".join(parsed) if parsed else None


def _parse_id3_pic(payload: bytes) -> tuple[str, str, str, bytes] | None:
    if len(payload) < 5:
        return None
    encoding = payload[0]
    image_format = payload[1:4].decode("latin-1", errors="replace").strip()
    picture_type = _ID3_PICTURE_TYPES.get(payload[4], f"Unknown ({payload[4]})")
    description_payload = payload[5:]
    description_end = _encoded_string_terminator_offset(description_payload, encoding)
    if description_end is None:
        return None
    description_bytes = description_payload[: description_end + 1]
    description_parts = _decode_id3_strings(bytes((encoding,)) + description_bytes)
    if description_parts is None:
        return None
    terminator_size = 2 if encoding in {1, 2} else 1
    picture_offset = 5 + description_end + terminator_size
    description = description_parts[0] if description_parts else ""
    return image_format, picture_type, description, payload[picture_offset:]


def _encoded_string_terminator_offset(payload: bytes, encoding: int) -> int | None:
    if encoding not in {1, 2}:
        offset = payload.find(b"\x00")
        return None if offset < 0 else offset
    offset = 0
    while offset + 1 < len(payload):
        if payload[offset : offset + 2] == b"\x00\x00" and offset % 2 == 0:
            return offset
        offset += 2
    return None


def _render_id3v1_field(name: str, value: bytes) -> str | None:
    if name == "Track":
        if len(value) != 2 or value[0] != 0 or value[1] == 0:
            return None
        return str(value[1])
    if name == "Genre":
        if not value:
            return None
        return _ID3V1_GENRES.get(value[0], f"Unknown ({value[0]})")
    rendered = value.rstrip(b"\x00 ").decode("latin-1", errors="replace")
    return rendered or None


def _render_id3v1_enhanced_field(name: str, value: bytes) -> str | None:
    if name == "Speed":
        if not value:
            return None
        return _ID3V1_ENHANCED_SPEEDS.get(value[0], f"Unknown ({value[0]})")
    rendered = value.rstrip(b"\x00 ").decode("latin-1", errors="replace")
    return rendered or None


def _id3v22_family_2_group(tag_name: str, frame_id: str) -> str:
    if tag_name in {"Artist", "Copyright", "OriginalArtist", "ArtistURL", "CopyrightURL"}:
        return "Author"
    if tag_name in {"Date", "Time", "Year"}:
        return "Time"
    if frame_id == "PIC":
        return "Preview"
    return "Audio"


def _id3v1_family_2_group(tag_name: str) -> str:
    if tag_name == "Artist":
        return "Author"
    if tag_name == "Year":
        return "Time"
    return "Audio"


_ID3_PICTURE_TYPES: dict[int, str] = {
    0: "Other",
    1: "32x32 PNG Icon",
    2: "Other Icon",
    3: "Front Cover",
    4: "Back Cover",
}
_ID3V1_GENRES: dict[int, str] = {
    7: "Hip-Hop",
}
_ID3V1_ENHANCED_SPEEDS: dict[int, str] = {
    1: "Slow",
    2: "Medium",
    3: "Fast",
    4: "Hardcore",
}
_MP3_ID3V22_TAG_NAMES: dict[str, str] = {
    "COM": "Comment",
    "PIC": "Picture",
    "RVA": "RelativeVolumeAdjustment",
    "TAL": "Album",
    "TCM": "Composer",
    "TCO": "Genre",
    "TP1": "Artist",
    "TPA": "PartOfSet",
    "TRK": "Track",
    "TT1": "Grouping",
    "TT2": "Title",
    "TYE": "Year",
    "ULT": "Lyrics",
}


@dataclass(frozen=True)
class _Id3v1EnhancedField:
    name: str
    family_2_group: str
    offset: int
    size: int


_ID3V1_ENHANCED_FIELDS: tuple[_Id3v1EnhancedField, ...] = (
    _Id3v1EnhancedField("Title2", "Audio", 4, 60),
    _Id3v1EnhancedField("Artist2", "Author", 64, 60),
    _Id3v1EnhancedField("Album2", "Audio", 124, 60),
    _Id3v1EnhancedField("Speed", "Audio", 184, 1),
    _Id3v1EnhancedField("Genre", "Audio", 185, 30),
    _Id3v1EnhancedField("StartTime", "Audio", 215, 6),
    _Id3v1EnhancedField("EndTime", "Audio", 221, 6),
)


def _syncsafe_size(raw_size: bytes) -> int | None:
    if len(raw_size) != 4:
        return None
    value = int.from_bytes(raw_size, "big")
    if value & 0x80808080:
        return None
    return (
        (value & 0x0000007F)
        | ((value & 0x00007F00) >> 1)
        | ((value & 0x007F0000) >> 2)
        | ((value & 0x7F000000) >> 3)
    )


def unique_evidence_ids(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def unique_gates(
    gates: tuple[MpegOutputEmissionGate, ...],
) -> tuple[MpegOutputEmissionGate, ...]:
    seen: set[MpegEmissionGateCode] = set()
    unique: list[MpegOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
