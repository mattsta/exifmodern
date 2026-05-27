"""Source-grounded, non-mutating MOI metadata transaction plans.

ExifTool's MOI reader validates a 256-byte ``V6`` sidecar metadata window,
checks the big-endian file-size field when FileSize is available, decodes fixed
binary fields for camcorder sidecar metadata, and has no writer. This planner
keeps the same preserve-first boundary: it decodes only MOI.pm-modeled fields
and blocks all requested rewrites.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MOI_PM_SOURCE_PATH = "lib/Image/ExifTool/MOI.pm"
MOI_EXIFTOOL_READ_SIZE = 256
MOI_VERSION = b"V6"

type MoiPlanStatus = Literal["planned", "unsupported"]
type MoiByteOrder = Literal["MM"]
type MoiMetadataRole = Literal[
    "version",
    "file_size_gate",
    "timestamp",
    "duration",
    "video",
    "audio",
]
type MoiRewriteTarget = Literal[
    "metadata_window",
    "sidecar_payload",
    "timestamp",
    "duration",
    "video",
    "audio",
    "camera_sidecar",
]
type MoiRewriteOperation = Literal["insert", "replace", "delete"]
type MoiActionKind = Literal[
    "validate_probe_window",
    "validate_version",
    "validate_declared_file_size",
    "set_big_endian",
    "decode_timestamp",
    "decode_duration",
    "decode_video_metadata",
    "decode_audio_metadata",
    "preserve_metadata_window",
    "preserve_sidecar_payload",
    "block_requested_rewrite",
]
type MoiBlockerCode = Literal[
    "truncated_moi_probe",
    "invalid_moi_version",
    "declared_file_size_mismatch",
    "rewrite_requested_requires_moi_writer",
    "non_mutating_plan_requires_explicit_emission",
]

MOI_DESCRIPTION_SOURCE = "moi_description"
MOI_NOTES_SOURCE = "moi_notes"
MOI_MAIN_TABLE_SOURCE = "moi_main_table"
MOI_TIME_SOURCE = "moi_time"
MOI_DURATION_SOURCE = "moi_duration"
MOI_VIDEO_SOURCE = "moi_video"
MOI_AUDIO_SOURCE = "moi_audio"
MOI_VIDEO_BITRATE_SOURCE = "moi_video_bitrate"
MOI_PROCESS_SOURCE = "moi_process"

MOI_TRANSACTION_SOURCES = (
    MOI_DESCRIPTION_SOURCE,
    MOI_NOTES_SOURCE,
    MOI_MAIN_TABLE_SOURCE,
    MOI_TIME_SOURCE,
    MOI_DURATION_SOURCE,
    MOI_VIDEO_SOURCE,
    MOI_AUDIO_SOURCE,
    MOI_VIDEO_BITRATE_SOURCE,
    MOI_PROCESS_SOURCE,
)

MOI_AUDIO_CODEC_NAMES: dict[int, str] = {
    0x00C1: "AC3",
    0x4001: "MPEG",
}
MOI_VIDEO_BITRATE_VALUES: dict[int, int] = {
    0x5896: 8_500_000,
    0x813D: 5_500_000,
}


@dataclass(frozen=True)
class MoiRewriteRequest:
    target: MoiRewriteTarget
    operation: MoiRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class MoiTransactionBlocker:
    code: MoiBlockerCode
    reason: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MoiOutputEmissionGate:
    code: MoiBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MoiHeaderValidationPlan:
    probe_range: tuple[int, int]
    version: bytes
    declared_file_size: int | None
    actual_file_size: int
    byte_order: MoiByteOrder | None
    reason: MoiBlockerCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class MoiFieldPlan:
    name: str
    role: MoiMetadataRole
    offset: int
    length: int
    raw_value: bytes
    parsed_value: str | int | float | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MoiTimestampPlan:
    raw_components: tuple[int, int, int, int, int, int]
    date_time_original: str
    field: MoiFieldPlan
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MoiDurationPlan:
    duration_milliseconds: int
    duration_seconds: float
    field: MoiFieldPlan
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MoiVideoMetadataPlan:
    aspect_ratio_code: int
    aspect_ratio: str
    tv_system: str | None
    aspect_ratio_description: str
    video_bitrate_code: int
    video_bitrate_bps: int | None
    fields: tuple[MoiFieldPlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MoiAudioMetadataPlan:
    audio_codec_code: int
    audio_codec: str | None
    audio_bitrate_index: int
    audio_bitrate_bps: int
    fields: tuple[MoiFieldPlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MoiCameraSidecarPlan:
    associated_media_extensions: tuple[str, ...]
    writer_families: tuple[str, ...]
    note: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MoiPayloadPreservationPlan:
    metadata_window_range: tuple[int, int]
    sidecar_payload_range: tuple[int, int] | None
    sidecar_payload: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MoiActionPlan:
    kind: MoiActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MoiMetadataTransactionPlan:
    status: MoiPlanStatus
    source_data: bytes
    header_validation: MoiHeaderValidationPlan
    fields: tuple[MoiFieldPlan, ...]
    timestamp: MoiTimestampPlan | None
    duration: MoiDurationPlan | None
    video: MoiVideoMetadataPlan | None
    audio: MoiAudioMetadataPlan | None
    camera_sidecar: MoiCameraSidecarPlan | None
    payload_preservation: MoiPayloadPreservationPlan | None
    rewrite_requests: tuple[MoiRewriteRequest, ...]
    actions: tuple[MoiActionPlan, ...]
    blockers: tuple[MoiTransactionBlocker, ...]
    output_emission_gates: tuple[MoiOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"MOI metadata transaction output is gated: {gate_codes}")
        return self.source_data


def build_moi_metadata_transaction_plan(
    moi_data: bytes,
    *,
    actual_file_size: int | None = None,
    rewrite_requests: tuple[MoiRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> MoiMetadataTransactionPlan:
    """Build a source-backed MOI metadata transaction plan."""

    blockers: list[MoiTransactionBlocker] = []
    actions: list[MoiActionPlan] = []
    effective_file_size = len(moi_data) if actual_file_size is None else actual_file_size
    header = _build_header_validation(moi_data, effective_file_size, blockers, actions)
    if not header.is_exiftool_accepted:
        return _finish_plan(
            status="unsupported",
            source_data=moi_data,
            header_validation=header,
            fields=(),
            timestamp=None,
            duration=None,
            video=None,
            audio=None,
            camera_sidecar=None,
            payload_preservation=None,
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            blockers=tuple(blockers),
            allow_output_emission=allow_output_emission,
        )

    fields = _build_fields(moi_data)
    timestamp = _build_timestamp(moi_data, fields, actions)
    duration = _build_duration(moi_data, fields, actions)
    video = _build_video(moi_data, fields, actions)
    audio = _build_audio(moi_data, fields, actions)
    camera_sidecar = _build_camera_sidecar()
    payload_preservation = _build_payload_preservation(moi_data, actions)

    for request in rewrite_requests:
        blocker = MoiTransactionBlocker(
            code="rewrite_requested_requires_moi_writer",
            reason=(
                f"MOI {request.operation} for {request.target} was requested, "
                "but ExifTool's MOI module is read-only."
            ),
            byte_range=None,
            evidence_ids=(MOI_DESCRIPTION_SOURCE,),
        )
        blockers.append(blocker)
        actions.append(
            MoiActionPlan(
                kind="block_requested_rewrite",
                target=request.target,
                byte_range=None,
                reason="MOI rewrites are blocked until a source-backed writer exists.",
                evidence_ids=(MOI_DESCRIPTION_SOURCE,),
            )
        )

    return _finish_plan(
        status="planned",
        source_data=moi_data,
        header_validation=header,
        fields=fields,
        timestamp=timestamp,
        duration=duration,
        video=video,
        audio=audio,
        camera_sidecar=camera_sidecar,
        payload_preservation=payload_preservation,
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        blockers=tuple(blockers),
        allow_output_emission=allow_output_emission,
    )


def _build_header_validation(
    moi_data: bytes,
    actual_file_size: int,
    blockers: list[MoiTransactionBlocker],
    actions: list[MoiActionPlan],
) -> MoiHeaderValidationPlan:
    probe_range = (0, min(len(moi_data), MOI_EXIFTOOL_READ_SIZE))
    version = moi_data[:2]
    declared_size = _optional_u32(moi_data, 2)
    if len(moi_data) < MOI_EXIFTOOL_READ_SIZE:
        blockers.append(
            MoiTransactionBlocker(
                code="truncated_moi_probe",
                reason="ExifTool's MOI reader requires a complete 256-byte probe read.",
                byte_range=probe_range,
                evidence_ids=(MOI_PROCESS_SOURCE,),
            )
        )
        return MoiHeaderValidationPlan(
            probe_range=probe_range,
            version=version,
            declared_file_size=declared_size,
            actual_file_size=actual_file_size,
            byte_order=None,
            reason="truncated_moi_probe",
            evidence_ids=(MOI_PROCESS_SOURCE,),
        )

    actions.append(
        MoiActionPlan(
            kind="validate_probe_window",
            target="MOI",
            byte_range=(0, MOI_EXIFTOOL_READ_SIZE),
            reason="Input satisfies ExifTool's 256-byte MOI probe read.",
            evidence_ids=(MOI_PROCESS_SOURCE,),
        )
    )

    if version != MOI_VERSION:
        blockers.append(
            MoiTransactionBlocker(
                code="invalid_moi_version",
                reason="ExifTool's MOI reader requires the probe buffer to start with V6.",
                byte_range=(0, 2),
                evidence_ids=(MOI_PROCESS_SOURCE,),
            )
        )
        return MoiHeaderValidationPlan(
            probe_range=(0, MOI_EXIFTOOL_READ_SIZE),
            version=version,
            declared_file_size=declared_size,
            actual_file_size=actual_file_size,
            byte_order=None,
            reason="invalid_moi_version",
            evidence_ids=(MOI_PROCESS_SOURCE,),
        )

    actions.append(
        MoiActionPlan(
            kind="validate_version",
            target="V6",
            byte_range=(0, 2),
            reason="Input satisfied ExifTool's /^V6/ MOI signature gate.",
            evidence_ids=(MOI_PROCESS_SOURCE,),
        )
    )

    if declared_size != actual_file_size:
        blockers.append(
            MoiTransactionBlocker(
                code="declared_file_size_mismatch",
                reason="The MOI file-size field does not match the sidecar file length.",
                byte_range=(2, 6),
                evidence_ids=(MOI_PROCESS_SOURCE,),
            )
        )
        return MoiHeaderValidationPlan(
            probe_range=(0, MOI_EXIFTOOL_READ_SIZE),
            version=version,
            declared_file_size=declared_size,
            actual_file_size=actual_file_size,
            byte_order=None,
            reason="declared_file_size_mismatch",
            evidence_ids=(MOI_PROCESS_SOURCE,),
        )

    actions.append(
        MoiActionPlan(
            kind="validate_declared_file_size",
            target="MOIFileSize",
            byte_range=(2, 6),
            reason="The big-endian size field matches the sidecar length available to the plan.",
            evidence_ids=(MOI_PROCESS_SOURCE,),
        )
    )
    actions.append(
        MoiActionPlan(
            kind="set_big_endian",
            target="MM",
            byte_range=(0, MOI_EXIFTOOL_READ_SIZE),
            reason="ExifTool sets big-endian byte order before processing MOI Main.",
            evidence_ids=(MOI_PROCESS_SOURCE,),
        )
    )
    return MoiHeaderValidationPlan(
        probe_range=(0, MOI_EXIFTOOL_READ_SIZE),
        version=version,
        declared_file_size=declared_size,
        actual_file_size=actual_file_size,
        byte_order="MM",
        reason=None,
        evidence_ids=(MOI_PROCESS_SOURCE,),
    )


def _build_fields(moi_data: bytes) -> tuple[MoiFieldPlan, ...]:
    return (
        MoiFieldPlan(
            name="MOIVersion",
            role="version",
            offset=0x00,
            length=2,
            raw_value=moi_data[0x00:0x02],
            parsed_value=moi_data[0x00:0x02].decode("ascii", errors="replace"),
            evidence_ids=(MOI_MAIN_TABLE_SOURCE,),
        ),
        MoiFieldPlan(
            name="MOIFileSize",
            role="file_size_gate",
            offset=0x02,
            length=4,
            raw_value=moi_data[0x02:0x06],
            parsed_value=_u32(moi_data, 0x02),
            evidence_ids=(MOI_PROCESS_SOURCE,),
        ),
        MoiFieldPlan(
            name="DateTimeOriginal",
            role="timestamp",
            offset=0x06,
            length=8,
            raw_value=moi_data[0x06:0x0E],
            parsed_value=_format_timestamp(moi_data, 0x06),
            evidence_ids=(MOI_TIME_SOURCE,),
        ),
        MoiFieldPlan(
            name="Duration",
            role="duration",
            offset=0x0E,
            length=4,
            raw_value=moi_data[0x0E:0x12],
            parsed_value=_u32(moi_data, 0x0E) / 1000,
            evidence_ids=(MOI_DURATION_SOURCE,),
        ),
        MoiFieldPlan(
            name="AspectRatio",
            role="video",
            offset=0x80,
            length=1,
            raw_value=moi_data[0x80:0x81],
            parsed_value=_aspect_ratio_description(moi_data[0x80]),
            evidence_ids=(MOI_VIDEO_SOURCE,),
        ),
        MoiFieldPlan(
            name="AudioCodec",
            role="audio",
            offset=0x84,
            length=2,
            raw_value=moi_data[0x84:0x86],
            parsed_value=MOI_AUDIO_CODEC_NAMES.get(_u16(moi_data, 0x84)),
            evidence_ids=(MOI_AUDIO_SOURCE,),
        ),
        MoiFieldPlan(
            name="AudioBitrate",
            role="audio",
            offset=0x86,
            length=1,
            raw_value=moi_data[0x86:0x87],
            parsed_value=_audio_bitrate_bps(moi_data[0x86]),
            evidence_ids=(MOI_AUDIO_SOURCE,),
        ),
        MoiFieldPlan(
            name="VideoBitrate",
            role="video",
            offset=0xDA,
            length=2,
            raw_value=moi_data[0xDA:0xDC],
            parsed_value=MOI_VIDEO_BITRATE_VALUES.get(_u16(moi_data, 0xDA)),
            evidence_ids=(MOI_VIDEO_BITRATE_SOURCE,),
        ),
    )


def _build_timestamp(
    moi_data: bytes,
    fields: tuple[MoiFieldPlan, ...],
    actions: list[MoiActionPlan],
) -> MoiTimestampPlan:
    raw_components = _timestamp_components(moi_data, 0x06)
    plan = MoiTimestampPlan(
        raw_components=raw_components,
        date_time_original=_format_timestamp(moi_data, 0x06),
        field=_field_by_name(fields, "DateTimeOriginal"),
        evidence_ids=(MOI_TIME_SOURCE,),
    )
    actions.append(
        MoiActionPlan(
            kind="decode_timestamp",
            target="DateTimeOriginal",
            byte_range=(0x06, 0x0E),
            reason="Decoded the DateTimeOriginal field using MOI.pm's unpack pattern.",
            evidence_ids=(MOI_TIME_SOURCE,),
        )
    )
    return plan


def _build_duration(
    moi_data: bytes,
    fields: tuple[MoiFieldPlan, ...],
    actions: list[MoiActionPlan],
) -> MoiDurationPlan:
    duration_ms = _u32(moi_data, 0x0E)
    plan = MoiDurationPlan(
        duration_milliseconds=duration_ms,
        duration_seconds=duration_ms / 1000,
        field=_field_by_name(fields, "Duration"),
        evidence_ids=(MOI_DURATION_SOURCE,),
    )
    actions.append(
        MoiActionPlan(
            kind="decode_duration",
            target="Duration",
            byte_range=(0x0E, 0x12),
            reason="Decoded Duration as big-endian milliseconds divided by 1000.",
            evidence_ids=(MOI_DURATION_SOURCE,),
        )
    )
    return plan


def _build_video(
    moi_data: bytes,
    fields: tuple[MoiFieldPlan, ...],
    actions: list[MoiActionPlan],
) -> MoiVideoMetadataPlan:
    aspect_code = moi_data[0x80]
    bitrate_code = _u16(moi_data, 0xDA)
    plan = MoiVideoMetadataPlan(
        aspect_ratio_code=aspect_code,
        aspect_ratio=_aspect_ratio(aspect_code),
        tv_system=_tv_system(aspect_code),
        aspect_ratio_description=_aspect_ratio_description(aspect_code),
        video_bitrate_code=bitrate_code,
        video_bitrate_bps=MOI_VIDEO_BITRATE_VALUES.get(bitrate_code),
        fields=(
            _field_by_name(fields, "AspectRatio"),
            _field_by_name(fields, "VideoBitrate"),
        ),
        evidence_ids=(MOI_VIDEO_SOURCE, MOI_VIDEO_BITRATE_SOURCE),
    )
    actions.append(
        MoiActionPlan(
            kind="decode_video_metadata",
            target="AspectRatio/VideoBitrate",
            byte_range=(0x80, 0xDC),
            reason="Decoded MOI.pm video fields and preserved the unmodeled bytes between them.",
            evidence_ids=(MOI_VIDEO_SOURCE, MOI_VIDEO_BITRATE_SOURCE),
        )
    )
    return plan


def _build_audio(
    moi_data: bytes,
    fields: tuple[MoiFieldPlan, ...],
    actions: list[MoiActionPlan],
) -> MoiAudioMetadataPlan:
    codec_code = _u16(moi_data, 0x84)
    bitrate_index = moi_data[0x86]
    plan = MoiAudioMetadataPlan(
        audio_codec_code=codec_code,
        audio_codec=MOI_AUDIO_CODEC_NAMES.get(codec_code),
        audio_bitrate_index=bitrate_index,
        audio_bitrate_bps=_audio_bitrate_bps(bitrate_index),
        fields=(
            _field_by_name(fields, "AudioCodec"),
            _field_by_name(fields, "AudioBitrate"),
        ),
        evidence_ids=(MOI_AUDIO_SOURCE,),
    )
    actions.append(
        MoiActionPlan(
            kind="decode_audio_metadata",
            target="AudioCodec/AudioBitrate",
            byte_range=(0x84, 0x87),
            reason="Decoded MOI.pm audio codec and bitrate fields.",
            evidence_ids=(MOI_AUDIO_SOURCE,),
        )
    )
    return plan


def _build_camera_sidecar() -> MoiCameraSidecarPlan:
    return MoiCameraSidecarPlan(
        associated_media_extensions=("MOD", "TOD"),
        writer_families=("JVC", "Canon", "Panasonic"),
        note=(
            "MOI.pm identifies MOI as camcorder sidecar metadata for associated MOD "
            "or TOD files; it does not expose camera make/model tags."
        ),
        evidence_ids=(MOI_NOTES_SOURCE,),
    )


def _build_payload_preservation(
    moi_data: bytes,
    actions: list[MoiActionPlan],
) -> MoiPayloadPreservationPlan:
    payload = moi_data[MOI_EXIFTOOL_READ_SIZE:]
    payload_range: tuple[int, int] | None = None
    if payload:
        payload_range = (MOI_EXIFTOOL_READ_SIZE, len(moi_data))
    actions.append(
        MoiActionPlan(
            kind="preserve_metadata_window",
            target="moi_metadata_window",
            byte_range=(0, MOI_EXIFTOOL_READ_SIZE),
            reason="The ExifTool-processed MOI metadata window is preserved byte-for-byte.",
            evidence_ids=(MOI_PROCESS_SOURCE,),
        )
    )
    actions.append(
        MoiActionPlan(
            kind="preserve_sidecar_payload",
            target="sidecar_payload",
            byte_range=payload_range,
            reason="Bytes after ExifTool's MOI metadata window are outside MOI.pm decoding.",
            evidence_ids=(MOI_PROCESS_SOURCE,),
        )
    )
    return MoiPayloadPreservationPlan(
        metadata_window_range=(0, MOI_EXIFTOOL_READ_SIZE),
        sidecar_payload_range=payload_range,
        sidecar_payload=payload,
        evidence_ids=(MOI_PROCESS_SOURCE,),
    )


def _finish_plan(
    *,
    status: MoiPlanStatus,
    source_data: bytes,
    header_validation: MoiHeaderValidationPlan,
    fields: tuple[MoiFieldPlan, ...],
    timestamp: MoiTimestampPlan | None,
    duration: MoiDurationPlan | None,
    video: MoiVideoMetadataPlan | None,
    audio: MoiAudioMetadataPlan | None,
    camera_sidecar: MoiCameraSidecarPlan | None,
    payload_preservation: MoiPayloadPreservationPlan | None,
    rewrite_requests: tuple[MoiRewriteRequest, ...],
    actions: tuple[MoiActionPlan, ...],
    blockers: tuple[MoiTransactionBlocker, ...],
    allow_output_emission: bool,
) -> MoiMetadataTransactionPlan:
    gates = tuple(
        MoiOutputEmissionGate(
            code=blocker.code,
            reason=blocker.reason,
            evidence_ids=blocker.evidence_ids,
        )
        for blocker in blockers
    )
    if status == "planned" and not gates and not allow_output_emission:
        gates = (
            MoiOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason=(
                    "MOI transaction plans preserve bytes and require explicit emission approval."
                ),
                evidence_ids=(MOI_DESCRIPTION_SOURCE,),
            ),
        )
    return MoiMetadataTransactionPlan(
        status=status,
        source_data=source_data,
        header_validation=header_validation,
        fields=fields,
        timestamp=timestamp,
        duration=duration,
        video=video,
        audio=audio,
        camera_sidecar=camera_sidecar,
        payload_preservation=payload_preservation,
        rewrite_requests=rewrite_requests,
        actions=actions,
        blockers=blockers,
        output_emission_gates=gates,
        evidence_ids=MOI_TRANSACTION_SOURCES,
    )


def _field_by_name(fields: tuple[MoiFieldPlan, ...], name: str) -> MoiFieldPlan:
    for field in fields:
        if field.name == name:
            return field
    raise ValueError(f"MOI field plan missing: {name}")


def _timestamp_components(data: bytes, offset: int) -> tuple[int, int, int, int, int, int]:
    return (
        _u16(data, offset),
        data[offset + 2],
        data[offset + 3],
        data[offset + 4],
        data[offset + 5],
        _u16(data, offset + 6),
    )


def _format_timestamp(data: bytes, offset: int) -> str:
    year, month, day, hour, minute, second_milliseconds = _timestamp_components(data, offset)
    seconds = second_milliseconds / 1000
    return f"{year:04d}:{month:02d}:{day:02d} {hour:02d}:{minute:02d}:{seconds:06.3f}"


def _aspect_ratio(code: int) -> str:
    low_nibble = code & 0x0F
    if low_nibble < 2:
        return "4:3"
    if low_nibble in (4, 5):
        return "16:9"
    return "Unknown"


def _tv_system(code: int) -> str | None:
    high_nibble = code >> 4
    if high_nibble == 4:
        return "NTSC"
    if high_nibble == 5:
        return "PAL"
    return None


def _aspect_ratio_description(code: int) -> str:
    aspect = _aspect_ratio(code)
    system = _tv_system(code)
    if system is None:
        return aspect
    return f"{aspect} {system}"


def _audio_bitrate_bps(index: int) -> int:
    return index * 16_000 + 48_000


def _optional_u32(data: bytes, offset: int) -> int | None:
    if len(data) < offset + 4:
        return None
    return _u32(data, offset)


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")
