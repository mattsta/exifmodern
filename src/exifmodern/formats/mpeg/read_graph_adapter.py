"""MP3 audio transaction-plan adapters for shared read graph contracts."""

from __future__ import annotations

import time

from exifmodern.exiftool_compat.core import convert_bitrate, convert_duration
from exifmodern.formats.mpeg.stream_transaction_plan import (
    Mp3Id3RenderedFramePlan,
    MpegAudioHeaderPlan,
    MpegStreamTransactionPlan,
    MpegVideoSequenceHeaderPlan,
    build_mp3_audio_transaction_plan,
    build_mpeg_stream_transaction_plan,
)
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue
from exifmodern.renderer import JsonRecord, RenderIssue, graph_record_for_request


def build_mp3_read_graph(
    mp3_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
    file_size: int | None = None,
) -> ReadGraph:
    return mp3_audio_transaction_plan_to_read_graph(
        build_mp3_audio_transaction_plan(
            mp3_data,
            file_size=file_size,
            allow_output_emission=True,
        ),
        source_file,
        generated_at_epoch,
    )


def build_mpeg_read_graph(
    mpeg_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
    file_size: int | None = None,
) -> ReadGraph:
    plan = build_mpeg_stream_transaction_plan(
        mpeg_data,
        file_size=file_size,
        allow_output_emission=True,
    )
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=mpeg_graph_tags(plan),
        diagnostics=mp3_plan_diagnostics(plan),
    )


def mp3_audio_transaction_plan_to_read_graph(
    plan: MpegStreamTransactionPlan,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=mp3_graph_tags(plan),
        diagnostics=mp3_plan_diagnostics(plan),
    )


def render_mp3_audio_transaction_plan_record(
    plan: MpegStreamTransactionPlan,
    source_file: str,
    args: tuple[str, ...],
    generated_at_epoch: int | None = None,
) -> tuple[JsonRecord, list[RenderIssue]]:
    graph = mp3_audio_transaction_plan_to_read_graph(plan, source_file, generated_at_epoch)
    return graph_record_for_request(graph, source_file, args)


def mpeg_graph_tags(plan: MpegStreamTransactionPlan) -> list[ReadTag]:
    tags = [
        mp3_file_tag("FileType", "MPEG", "FileType"),
        mp3_file_tag("FileTypeExtension", "mpg", "FileTypeExtension"),
        mp3_file_tag("MIMEType", "video/mpeg", "MIMEType"),
    ]
    video_header = next((header for header in plan.video_headers if header.status == "valid"), None)
    if video_header is not None:
        tags.extend(mpeg_video_header_tags(video_header))
    audio_header = next((header for header in plan.audio_headers if header.status == "valid"), None)
    if audio_header is not None:
        tags.extend(mp3_audio_header_tags(audio_header))
    if plan.duration.approximate_seconds is not None:
        tags.append(mp3_duration_tag(plan.duration.approximate_seconds))
    return tags


def mp3_graph_tags(plan: MpegStreamTransactionPlan) -> list[ReadTag]:
    tags = [
        mp3_file_tag("FileType", "MP3", "FileType"),
        mp3_file_tag("FileTypeExtension", "mp3", "FileTypeExtension"),
        mp3_file_tag("MIMEType", "audio/mpeg", "MIMEType"),
        mp3_file_tag("ID3Size", plan.duration.id3_size, "ID3Size"),
    ]
    audio_header = next((header for header in plan.audio_headers if header.status == "valid"), None)
    if audio_header is not None:
        tags.extend(mp3_audio_header_tags(audio_header))
    tags.extend(mp3_id3_frame_to_graph_tag(frame) for frame in plan.id3_rendered_frames)
    if plan.duration.approximate_seconds is not None:
        tags.append(mp3_duration_tag(plan.duration.approximate_seconds))
    return tags


def mp3_file_tag(name: str, value: TagValue, tag_id: str) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::File",
            tag_id=tag_id,
            source=f"mp3-reader:file:{tag_id}",
            family_0_group="File",
            family_1_group="File",
            family_2_group="Image" if name == "ID3Size" else "Other",
        ),
        schema=None,
    )


def mp3_audio_header_tags(header: MpegAudioHeaderPlan) -> list[ReadTag]:
    return [
        mp3_audio_tag(
            "MPEGAudioVersion",
            mp3_rendered_audio_version(header.version),
            "Bit11-12",
            header.sync_offset,
        ),
        mp3_audio_tag("AudioLayer", header.audio_layer, "Bit13-14", header.sync_offset),
        mp3_audio_tag(
            "AudioBitrate",
            mp3_rendered_bitrate(header.bitrate),
            "Bit16-19",
            header.sync_offset,
        ),
        mp3_audio_tag("SampleRate", header.sample_rate, "Bit20-21", header.sync_offset),
        mp3_audio_tag("ChannelMode", header.channel_mode, "Bit24-25", header.sync_offset),
        *(
            [
                mp3_audio_tag(
                    "ModeExtension",
                    header.mode_extension,
                    "Bit26-27",
                    header.sync_offset,
                )
            ]
            if header.mode_extension is not None
            else []
        ),
        mp3_audio_tag("MSStereo", on_off_value(header.ms_stereo), "Bit26", header.sync_offset),
        mp3_audio_tag(
            "IntensityStereo",
            on_off_value(header.intensity_stereo),
            "Bit27",
            header.sync_offset,
        ),
        mp3_audio_tag(
            "CopyrightFlag",
            true_false_value(header.copyright_flag),
            "Bit28",
            header.sync_offset,
        ),
        mp3_audio_tag(
            "OriginalMedia",
            true_false_value(header.original_media),
            "Bit29",
            header.sync_offset,
        ),
        mp3_audio_tag("Emphasis", header.emphasis, "Bit30-31", header.sync_offset),
    ]


def mpeg_video_header_tags(header: MpegVideoSequenceHeaderPlan) -> list[ReadTag]:
    return [
        mpeg_video_tag("ImageWidth", header.width, "Bit0-11", header.offset),
        mpeg_video_tag("ImageHeight", header.height, "Bit12-23", header.offset),
        mpeg_video_tag("AspectRatio", header.aspect_description, "Bit24-27", header.offset),
        mpeg_video_tag("FrameRate", header.frame_rate, "Bit28-31", header.offset),
        mpeg_video_tag(
            "VideoBitrate",
            mp3_rendered_bitrate(header.video_bitrate),
            "Bit32-49",
            header.offset,
        ),
    ]


def mpeg_video_tag(name: str, value: TagValue, tag_id: str, offset: int) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="MPEG",
            table_name="Image::ExifTool::MPEG::Video",
            tag_id=tag_id,
            source=f"mpeg-reader:video-sequence:{offset}:{tag_id}",
            family_0_group="MPEG",
            family_1_group="MPEG",
            family_2_group="Video",
        ),
        schema=None,
    )


def mp3_audio_tag(name: str, value: TagValue, tag_id: str, sync_offset: int) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="MPEG",
            table_name="Image::ExifTool::MPEG::Audio",
            tag_id=tag_id,
            source=f"mp3-reader:audio-header:{sync_offset}:{tag_id}",
            family_0_group="MPEG",
            family_1_group="MPEG",
            family_2_group="Audio",
        ),
        schema=None,
    )


def mp3_id3_frame_to_graph_tag(frame: Mp3Id3RenderedFramePlan) -> ReadTag:
    return ReadTag(
        name=frame.name,
        value=mp3_id3_frame_value(frame),
        provenance=TagProvenance(
            group=frame.group,
            table_name=mp3_id3_table_name(frame),
            tag_id=frame.tag_id,
            source=f"mp3-reader:id3-frame:{frame.group}:{frame.tag_id}:{frame.relative_offset}",
            family_0_group="ID3" if frame.group != "Composite" else "Composite",
            family_1_group=frame.group,
            family_2_group=frame.family_2_group,
        ),
        schema=None,
    )


def mp3_id3_frame_value(frame: Mp3Id3RenderedFramePlan) -> TagValue:
    if frame.value_kind == "source_binary" and isinstance(frame.raw_value, bytes):
        return BinaryTagValue(frame.raw_value)
    if frame.value_kind == "binary" and isinstance(frame.raw_value, bytes):
        return BinaryTagValue(frame.raw_value)
    if frame.name in {"Year", "DateTimeOriginal"}:
        return _integer_year_or_text(frame.rendered_value)
    return frame.rendered_value


def mp3_id3_table_name(frame: Mp3Id3RenderedFramePlan) -> str:
    if frame.group == "Composite":
        return "Image::ExifTool::ID3::Composite"
    return f"Image::ExifTool::ID3::{frame.group}"


def mp3_duration_tag(duration: float) -> ReadTag:
    return ReadTag(
        name="Duration",
        value=mp3_rendered_duration(duration),
        provenance=TagProvenance(
            group="Composite",
            table_name="Image::ExifTool::MPEG::Composite",
            tag_id="MPEG-Duration",
            source="mp3-reader:mpeg-composite:Duration",
            family_0_group="Composite",
            family_1_group="Composite",
            family_2_group="Video",
        ),
        schema=None,
    )


def mp3_plan_diagnostics(plan: MpegStreamTransactionPlan) -> list[str]:
    return [f"{gate.code}: {gate.reason}" for gate in plan.output_emission_gates]


def on_off_value(value: bool | None) -> str | None:
    if value is None:
        return None
    return "On" if value else "Off"


def true_false_value(value: bool | None) -> bool | None:
    if value is None:
        return None
    return value


def _integer_year_or_text(value: str) -> str | int:
    if len(value) == 4 and value.isdecimal():
        return int(value)
    return value


def mp3_rendered_audio_version(value: float | None) -> int | float | None:
    if value is not None and value.is_integer():
        return int(value)
    return value


def mp3_rendered_bitrate(value: int | None) -> str | None:
    if value is None:
        return None
    rendered = convert_bitrate(value)
    if isinstance(rendered, str):
        return rendered
    return str(rendered)


def mp3_rendered_duration(seconds: float) -> str:
    rendered = convert_duration(seconds)
    if isinstance(rendered, str):
        return f"{rendered} (approx)"
    return f"{rendered} (approx)"
