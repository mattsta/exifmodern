"""DV stream transaction planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.dv.stream_transaction_plan import build_dv_stream_transaction_plan
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.dispatch_helpers import EvidenceAnchors
    from exifmodern.read_graph import ReadGraph, ReadTag

type DvGraphValue = str | int | float | bool | None

DV_COMPOSITE_EVIDENCE_ID = "dv.composite.image-size-megapixels"
DV_EXIFTOOL_READ_BYTES = 12000

__all__ = (
    "build_dv_read_graph",
    "build_dv_stream_transaction_plan",
    "invoke_dv",
)


def build_dv_read_graph(data: bytes, source_file: str, file_size: int | None = None) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value, _references
    from exifmodern.read_graph import ReadTag

    def _emit_field(
        tags_out: list[ReadTag],
        *,
        name: str,
        value: DvGraphValue,
        references: EvidenceAnchors,
        group: str = "DV",
        tag_id: str | None = None,
        family_1_group: str | None = None,
    ) -> None:
        if value is None:
            return
        rendered = value if isinstance(value, str | int | float | bool) else str(value)
        provenance = _provenance(
            group=group,
            table_name=dv_table_name(group),
            tag_id=name if tag_id is None else tag_id,
            references=references,
        )
        if family_1_group is not None:
            from dataclasses import replace

            provenance = replace(provenance, family_1_group=family_1_group)
        tags_out.append(
            ReadTag(
                name=name,
                value=_read_value(rendered),
                provenance=provenance,
                schema=None,
            )
        )

    plan = build_dv_stream_transaction_plan(data, file_size=file_size)
    diagnostics: list[str] = [f"DV package-local reader status: {plan.status}"]
    diagnostics.extend(
        f"DV package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = []
    if plan.status == "planned":
        for file_tag_name, file_tag_value in (
            ("FileType", "DV"),
            ("FileTypeExtension", "dv"),
            ("MIMEType", "video/x-dv"),
        ):
            _emit_field(
                tags,
                name=file_tag_name,
                value=file_tag_value,
                references=_references(plan.header),
                group="File",
            )
    time_meta = plan.time_metadata
    _emit_field(
        tags,
        name="DateTimeOriginal",
        value=time_meta.date_time_original,
        references=_references(time_meta),
    )
    video_meta = plan.video_metadata
    for video_tag_name, video_tag_value in (
        ("ImageWidth", video_meta.image_width),
        ("ImageHeight", video_meta.image_height),
        ("Duration", _dv_duration(video_meta.duration)),
        ("TotalBitrate", _dv_total_bitrate(video_meta.total_bitrate)),
        ("VideoFormat", video_meta.video_format),
        ("VideoScanType", video_meta.video_scan_type),
        ("FrameRate", _dv_frame_rate(video_meta.frame_rate)),
        ("AspectRatio", video_meta.aspect_ratio),
        ("Colorimetry", video_meta.colorimetry),
    ):
        _emit_field(
            tags,
            name=video_tag_name,
            value=video_tag_value,
            references=_references(video_meta),
            group="DV",
        )
    if video_meta.image_width is not None and video_meta.image_height is not None:
        width = video_meta.image_width
        height = video_meta.image_height
        megapixels = width * height / 1_000_000
        _emit_field(
            tags,
            name="ImageSize",
            value=f"{width}x{height}",
            references=(DV_COMPOSITE_EVIDENCE_ID,),
            group="Composite",
            tag_id="Exif-ImageSize",
        )
        _emit_field(
            tags,
            name="Megapixels",
            value=round_dv_megapixels(megapixels),
            references=(DV_COMPOSITE_EVIDENCE_ID,),
            group="Composite",
            tag_id="Exif-Megapixels",
        )
    audio_meta = plan.audio_metadata
    for audio_tag_name, audio_tag_value in (
        ("AudioChannels", audio_meta.audio_channels),
        ("AudioSampleRate", audio_meta.audio_sample_rate),
        ("AudioBitsPerSample", audio_meta.audio_bits_per_sample),
    ):
        _emit_field(
            tags,
            name=audio_tag_name,
            value=audio_tag_value,
            references=_references(audio_meta),
            group="Audio",
            family_1_group="DV",
        )
    return _graph(source_file, tags, diagnostics)


def dv_table_name(group: str) -> str:
    if group == "Composite":
        return "Image::ExifTool::Composite"
    if group == "File":
        return "Image::ExifTool::File"
    return "Image::ExifTool::DV::Main"


def round_dv_megapixels(value: float) -> float:
    if value >= 1:
        return round(value, 1)
    if value >= 0.001:
        return round(value, 3)
    return round(value, 6)


def _dv_duration(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f} s"


def _dv_total_bitrate(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value / 1_000_000:.1f} Mbps"


def _dv_frame_rate(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value.is_integer() else value


def invoke_dv(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    if len(prefix) >= DV_EXIFTOOL_READ_BYTES:
        data = prefix[:DV_EXIFTOOL_READ_BYTES]
    else:
        with path.open("rb") as file:
            data = file.read(DV_EXIFTOOL_READ_BYTES)
    return build_dv_read_graph(data, source_file, file_size=path.stat().st_size)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="dv/ntsc",
        builder_ref="exifmodern.formats.dv:invoke_dv",
        patterns=(Pattern(0, b"\x1f\x07\x00\x3f"),),
        weak=True,
    ),
    Signature(
        format_id="dv/pal",
        builder_ref="exifmodern.formats.dv:invoke_dv",
        patterns=(Pattern(0, b"\x1f\x07\x00\xbf"),),
        weak=True,
    ),
)
