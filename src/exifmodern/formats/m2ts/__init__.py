"""M2TS transport-stream planning and package-local read surfaces."""

import re
from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.m2ts.transport_transaction_plan import (
    M2T_PACKET_SIZE,
    M2TS_PACKET_SIZE,
    M2TS_PES_SOURCE,
    NULL_PACKET_PID,
    SYNC_BYTE,
    M2tsAc3DescriptorPlan,
    M2tsEmissionGate,
    M2tsPesPlan,
    M2tsProgramPlan,
    M2tsResponsibility,
    M2tsStreamPlan,
    M2tsSyncPlan,
    M2tsTimestampPlan,
    M2tsTransportPacketPlan,
    M2tsTransportTransactionPlan,
    build_m2ts_transport_transaction_plan,
    detect_transport_sync,
    stream_type_name,
)
from exifmodern.json_types import JsonValue
from exifmodern.read_graph import ReadTag, TagProvenance
from exifmodern.signature_trie.signature import Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = [
    "M2TS_PACKET_SIZE",
    "M2T_PACKET_SIZE",
    "NULL_PACKET_PID",
    "SYNC_BYTE",
    "M2tsAc3DescriptorPlan",
    "M2tsEmissionGate",
    "M2tsPesPlan",
    "M2tsProgramPlan",
    "M2tsResponsibility",
    "M2tsStreamPlan",
    "M2tsSyncPlan",
    "M2tsTimestampPlan",
    "M2tsTransportPacketPlan",
    "M2tsTransportTransactionPlan",
    "build_m2ts_read_graph",
    "build_m2ts_transport_transaction_plan",
    "detect_transport_sync",
    "invoke_m2ts",
    "is_m2ts_prefix",
    "stream_type_name",
]

M2TS_BOUNDED_READ_BYTES = M2TS_PACKET_SIZE * 256
_INNOVV_N2_TIMED_GPS_SOURCE = "m2ts.process.innovv_n2_timed_gps"
_INNOVV_N2_NUMBER = rb"[+-]?\d+(?:\.\d+)?"
_INNOVV_N2_TIMED_GPS_PATTERN = re.compile(
    rb"^Viidure"
    rb"(20\d{2})/(\d{2})/(\d{2}) "
    rb"(\d{2}:\d{2}:\d{2}) "
    rb"([NS]):(" + _INNOVV_N2_NUMBER + rb") "
    rb"([EW]):(" + _INNOVV_N2_NUMBER + rb") "
    rb"(" + _INNOVV_N2_NUMBER + rb") km/h "
    rb"(" + _INNOVV_N2_NUMBER + rb") "
    rb"(" + _INNOVV_N2_NUMBER + rb") "
    rb"(" + _INNOVV_N2_NUMBER + rb") "
    rb"x:(" + _INNOVV_N2_NUMBER + rb") "
    rb"y:(" + _INNOVV_N2_NUMBER + rb") "
    rb"z:(" + _INNOVV_N2_NUMBER + rb")",
    re.DOTALL,
)


def build_m2ts_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _read_value
    from exifmodern.formats.h264 import build_h264_stream_transaction_plan
    from exifmodern.read_graph import ReadTag

    plan = build_m2ts_transport_transaction_plan(data)
    diagnostics = [
        f"M2TS package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if gate.code
        not in {
            "planner_is_non_mutating",
            "full_transport_writer_not_implemented",
        }
    ]
    if plan.sync.file_kind == "invalid":
        diagnostics.insert(0, "M2TS package-local reader status: unsupported")

    tags: list[ReadTag] = []

    def add_tag(
        name: str,
        value: str | int | float | bool,
        group: str,
        tag_id: str,
        table_name: str,
        family_2_group: str,
        evidence_ids: tuple[str, ...],
    ) -> None:
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_m2ts_provenance(
                    group=group,
                    table_name=table_name,
                    tag_id=tag_id,
                    family_2_group=family_2_group,
                    evidence_ids=evidence_ids,
                ),
                schema=None,
            )
        )

    if plan.sync.file_kind in {"m2t", "m2ts"}:
        tags.append(
            ReadTag(
                name="Warning",
                value="[minor] The ExtractEmbedded option may find more tags in the video data",
                provenance=_m2ts_provenance(
                    group="ExifTool",
                    table_name="Image::ExifTool",
                    tag_id="Warning",
                    family_2_group="Other",
                    evidence_ids=plan.evidence_ids,
                ),
                schema=None,
            )
        )
        add_tag(
            "FileType",
            "M2TS" if plan.sync.file_kind == "m2ts" else "M2T",
            "File",
            "FileType",
            "Image::ExifTool::File",
            "Other",
            plan.evidence_ids,
        )
        extension = "mts" if plan.sync.file_kind == "m2ts" else "m2t"
        add_tag(
            "FileTypeExtension",
            extension,
            "File",
            "FileTypeExtension",
            "Image::ExifTool::File",
            "Other",
            plan.evidence_ids,
        )
        add_tag(
            "MIMEType",
            "video/m2ts",
            "File",
            "MIMEType",
            "Image::ExifTool::File",
            "Other",
            plan.evidence_ids,
        )
    for stream in plan.streams:
        if stream.is_video:
            add_tag(
                "VideoStreamType",
                stream.stream_type_name,
                "M2TS",
                "VideoStreamType",
                "Image::ExifTool::M2TS::Main",
                "Video",
                stream.evidence_ids,
            )
        elif stream.is_audio:
            add_tag(
                "AudioStreamType",
                stream.stream_type_name,
                "M2TS",
                "AudioStreamType",
                "Image::ExifTool::M2TS::Main",
                "Video",
                stream.evidence_ids,
            )
    if plan.timestamp.duration_seconds is not None:
        add_tag(
            "Duration",
            _format_duration(plan.timestamp.duration_seconds),
            "M2TS",
            "Duration",
            "Image::ExifTool::M2TS::Main",
            "Video",
            plan.timestamp.evidence_ids,
        )
    first_ac3 = plan.ac3_descriptors[0] if plan.ac3_descriptors else None
    if first_ac3 is not None:
        if first_ac3.audio_bitrate is not None:
            bitrate = _format_bitrate(first_ac3.audio_bitrate)
            add_tag(
                "AudioBitrate",
                bitrate,
                "AC3",
                "AudioBitrate",
                "Image::ExifTool::AC3::Main",
                "Audio",
                first_ac3.evidence_ids,
            )
        if first_ac3.surround_mode is not None:
            add_tag(
                "SurroundMode",
                first_ac3.surround_mode,
                "AC3",
                "SurroundMode",
                "Image::ExifTool::AC3::Main",
                "Audio",
                first_ac3.evidence_ids,
            )
        if first_ac3.audio_channels is not None:
            add_tag(
                "AudioChannels",
                first_ac3.audio_channels,
                "AC3",
                "AudioChannels",
                "Image::ExifTool::AC3::Main",
                "Audio",
                first_ac3.evidence_ids,
            )
    ac3_payload = _elementary_payload(data, plan, stream_type=0x81)
    sample_rate = _ac3_sample_rate(ac3_payload)
    if sample_rate is not None:
        add_tag(
            "AudioSampleRate",
            sample_rate,
            "AC3",
            "AudioSampleRate",
            "Image::ExifTool::AC3::Main",
            "Audio",
            plan.evidence_ids,
        )

    innovv_payload = _elementary_payload(data, plan, stream_type=0x06, pid=0x0300)
    _append_innovv_n2_timed_gps_tags(innovv_payload, tags)

    h264_payload = _elementary_payload(data, plan, stream_type=0x1B)
    if h264_payload:
        h264_plan = build_h264_stream_transaction_plan(h264_payload, allow_output_emission=True)
        diagnostics.extend(
            f"H264 package-local reader gate: {gate.code}: {gate.reason}"
            for gate in h264_plan.output_emission_gates
        )
        for tag in h264_plan.read_tags:
            value = _h264_read_tag_value(tag.name, tag.value)
            if value is None and tag.value is not None:
                diagnostics.append(
                    f"H264 package-local reader gate: unsupported_read_tag_value: {tag.name}"
                )
                continue
            tags.append(
                ReadTag(
                    name=tag.name,
                    value=_read_value(value),
                    provenance=_m2ts_provenance(
                        group="H264",
                        table_name=tag.table_name,
                        tag_id=tag.tag_id,
                        family_2_group=tag.group,
                        evidence_ids=tag.evidence_ids,
                    ),
                    schema=None,
                )
            )
    _append_m2ts_composites(tags)
    return _graph(source_file, tags, diagnostics)


def invoke_m2ts(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    with path.open("rb") as file:
        data = file.read(M2TS_BOUNDED_READ_BYTES)
    return build_m2ts_read_graph(data, source_file)


def is_m2ts_prefix(prefix: bytes) -> bool:
    sync, gates = detect_transport_sync(prefix)
    return sync.file_kind in {"m2t", "m2ts"} and not any(
        gate.code in {"sync_byte_detection_failed", "insufficient_packets_for_validation"}
        for gate in gates
    )


def _elementary_payload(
    data: bytes,
    plan: M2tsTransportTransactionPlan,
    *,
    stream_type: int,
    pid: int | None = None,
) -> bytes:
    pids = {
        stream.pid
        for stream in plan.streams
        if stream.stream_type == stream_type and (pid is None or stream.pid == pid)
    }
    if not pids:
        return b""
    start_offsets = {
        (pes.pid, pes.packet_index): pes.payload_offset
        for pes in plan.pes_packets
        if pes.stream_type == stream_type
    }
    chunks: list[bytes] = []
    for packet in plan.packets:
        if packet.pid not in pids or packet.action not in {"parse_pes_start", "accumulate_pes"}:
            continue
        payload_offset = start_offsets.get((packet.pid, packet.index), packet.payload_offset)
        chunks.append(data[payload_offset : packet.payload_end_offset])
    return b"".join(chunks)


def _append_innovv_n2_timed_gps_tags(payload: bytes, tags: list[ReadTag]) -> None:
    match = _INNOVV_N2_TIMED_GPS_PATTERN.search(payload)
    if match is None:
        return
    year, month, day, time, lat_ref, latitude, lon_ref, longitude = match.group(
        1, 2, 3, 4, 5, 6, 7, 8
    )
    speed, track, altitude, _unknown, accel_x, accel_y, accel_z = match.group(
        9, 10, 11, 12, 13, 14, 15
    )
    gps_datetime = f"{_ascii(year)}:{_ascii(month)}:{_ascii(day)} {_ascii(time)}Z"
    sources = (M2TS_PES_SOURCE, _INNOVV_N2_TIMED_GPS_SOURCE)
    _append_quicktime_stream_tag(tags, "GPSDateTime", gps_datetime, "Time", sources)
    _append_quicktime_stream_tag(
        tags,
        "GPSLatitude",
        _signed_coordinate(latitude, lat_ref, negative_ref=b"S"),
        "Location",
        sources,
    )
    _append_quicktime_stream_tag(
        tags,
        "GPSLongitude",
        _signed_coordinate(longitude, lon_ref, negative_ref=b"W"),
        "Location",
        sources,
    )
    _append_quicktime_stream_tag(tags, "GPSSpeed", float(speed), "Location", sources)
    _append_quicktime_stream_tag(tags, "GPSTrack", float(track), "Location", sources)
    _append_quicktime_stream_tag(tags, "GPSAltitude", float(altitude), "Location", sources)
    _append_quicktime_stream_tag(
        tags,
        "Accelerometer",
        f"{_ascii(accel_x)} {_ascii(accel_y)} {_ascii(accel_z)}",
        "Video",
        sources,
    )


def _append_quicktime_stream_tag(
    tags: list[ReadTag],
    name: str,
    value: str | float,
    family_2_group: str,
    evidence_ids: tuple[str, ...],
) -> None:
    tags.append(
        ReadTag(
            name=name,
            value=value,
            provenance=_m2ts_provenance(
                group="QuickTime",
                table_name="Image::ExifTool::QuickTime::Stream",
                tag_id=name,
                family_2_group=family_2_group,
                evidence_ids=evidence_ids,
            ),
            schema=None,
        )
    )


def _signed_coordinate(value: bytes, ref: bytes, *, negative_ref: bytes) -> float:
    coordinate = float(value)
    return -coordinate if ref == negative_ref else coordinate


def _ascii(value: bytes) -> str:
    return value.decode("ascii")


def _format_bitrate(bits_per_second: int) -> str:
    if bits_per_second % 1000 == 0:
        return f"{bits_per_second // 1000} kbps"
    return f"{bits_per_second} bps"


def _format_duration(seconds: float) -> str:
    return f"{round(seconds):d} s"


def _ac3_sample_rate(payload: bytes) -> int | None:
    sync_offset = payload.find(b"\x0b\x77")
    if sync_offset < 0 or sync_offset + 5 > len(payload):
        return None
    return {0: 48000, 1: 44100, 2: 32000}.get(payload[sync_offset + 4] >> 6)


def _h264_read_tag_value(
    name: str, value: JsonValue
) -> str | int | float | bool | list[str] | None:
    if name == "ApertureSetting" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if isinstance(item, str)]
    return None


def _append_m2ts_composites(tags: list[ReadTag]) -> None:
    values = {tag.name: tag.value for tag in tags}
    width = values.get("ImageWidth")
    height = values.get("ImageHeight")
    if isinstance(width, int) and isinstance(height, int):
        evidence_ids = ()
        tags.append(
            ReadTag(
                name="ImageSize",
                value=f"{width}x{height}",
                provenance=_m2ts_provenance(
                    group="Composite",
                    table_name="Image::ExifTool::Exif::Composite",
                    tag_id="Exif-ImageSize",
                    family_2_group="Image",
                    evidence_ids=evidence_ids,
                ),
                schema=None,
            )
        )
        tags.append(
            ReadTag(
                name="Megapixels",
                value=round(width * height / 1_000_000, 1),
                provenance=_m2ts_provenance(
                    group="Composite",
                    table_name="Image::ExifTool::Exif::Composite",
                    tag_id="Exif-Megapixels",
                    family_2_group="Image",
                    evidence_ids=evidence_ids,
                ),
                schema=None,
            )
        )
    exposure_time = values.get("ExposureTime")
    if isinstance(exposure_time, str):
        tags.append(
            ReadTag(
                name="ShutterSpeed",
                value=exposure_time,
                provenance=_m2ts_provenance(
                    group="Composite",
                    table_name="Image::ExifTool::Exif::Composite",
                    tag_id="Exif-ShutterSpeed",
                    family_2_group="Image",
                    evidence_ids=(),
                ),
                schema=None,
            )
        )


def _m2ts_provenance(
    *,
    group: str,
    table_name: str,
    tag_id: str | None,
    family_2_group: str,
    evidence_ids: tuple[str, ...],
) -> TagProvenance:
    return TagProvenance(
        group=group,
        table_name=table_name,
        tag_id=tag_id,
        source=_m2ts_evidence_anchor_text(evidence_ids),
        family_0_group=group,
        family_1_group=group,
        family_2_group=family_2_group,
    )


def _m2ts_evidence_anchor_text(evidence_ids: tuple[str, ...]) -> str:
    if not evidence_ids:
        return "m2ts-reader:computed-composite"
    return evidence_ids[0]


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="m2ts",
        builder_ref="exifmodern.formats.m2ts:invoke_m2ts",
        patterns=(),
        structural_check="exifmodern.formats.m2ts:is_m2ts_prefix",
        extensions=(".m2ts", ".mts", ".m2t", ".ts"),
    ),
)
