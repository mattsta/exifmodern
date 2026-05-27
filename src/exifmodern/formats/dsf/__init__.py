"""DSF/DSD metadata planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.dsf.metadata_transaction_plan import (
    DSF_CHUNK_HEADER_SIZE,
    DSF_INITIAL_READ_SIZE,
    DsfAudioPropertyPlan,
    audio_properties_from_fmt,
    build_dsd_header_plan,
    build_dsf_metadata_transaction_plan,
    build_fmt_chunk_plan,
)
from exifmodern.media_source import FileMediaSource
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = (
    "build_dsf_metadata_transaction_plan",
    "build_dsf_read_graph",
    "invoke_dsf",
)

DSF_EXIFTOOL_FMT_PROBE_LIMIT = 1028


def build_dsf_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_dsf_metadata_transaction_plan(data)
    return build_dsf_audio_read_graph_from_properties(
        source_file,
        status=plan.status,
        diagnostics=[
            f"DSF package-local reader gate: {gate.code}: {gate.reason}"
            for gate in plan.output_emission_gates
        ],
        audio=plan.audio_properties,
    )


def build_dsf_bounded_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Build the currently emitted DSF read surface from ExifTool's bounded fmt read."""

    header = build_dsd_header_plan(data)
    fmt_chunk = build_fmt_chunk_plan(data)
    status = (
        "unsupported" if header.reason is not None or fmt_chunk.reason is not None else "planned"
    )
    diagnostics: list[str] = []
    if header.reason is not None:
        diagnostics.append(
            f"DSF package-local reader gate: {header.reason}: DSD header probe failed"
        )
    if fmt_chunk.reason is not None:
        diagnostics.append(
            f"DSF package-local reader gate: {fmt_chunk.reason}: fmt chunk probe failed"
        )
    return build_dsf_audio_read_graph_from_properties(
        source_file,
        status=status,
        diagnostics=diagnostics,
        audio=audio_properties_from_fmt(fmt_chunk),
    )


def build_dsf_audio_read_graph_from_properties(
    source_file: str,
    *,
    status: str,
    diagnostics: list[str],
    audio: DsfAudioPropertyPlan,
) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value, _references
    from exifmodern.read_graph import ReadTag

    rendered_diagnostics = [f"DSF package-local reader status: {status}", *diagnostics]
    tags: list[ReadTag] = []
    for field in (
        "channel_type",
        "channel_count",
        "sample_rate",
        "bits_per_sample",
        "sample_count",
        "block_size",
        "duration_seconds",
    ):
        value = getattr(audio, field)
        if value is None:
            continue
        tags.append(
            ReadTag(
                name=field,
                value=_read_value(value),
                provenance=_provenance(
                    group="DSF",
                    table_name="Image::ExifTool::DSF::Main",
                    tag_id=field,
                    references=_references(audio),
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, rendered_diagnostics)


def invoke_dsf(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _dsf_fmt_probe(path, prefix)
    return build_dsf_bounded_read_graph(data, source_file)


def _dsf_fmt_probe(path: Path, prefix: bytes) -> bytes:
    if len(prefix) >= DSF_INITIAL_READ_SIZE:
        initial = prefix[:DSF_INITIAL_READ_SIZE]
    else:
        initial = FileMediaSource(path).prefix(DSF_INITIAL_READ_SIZE)
    if len(initial) < DSF_INITIAL_READ_SIZE:
        return initial
    fmt_size = int.from_bytes(initial[32:40], "little")
    if fmt_size <= DSF_CHUNK_HEADER_SIZE or fmt_size >= 1000:
        return initial
    probe_size = min(28 + fmt_size, DSF_EXIFTOOL_FMT_PROBE_LIMIT)
    if len(prefix) >= probe_size:
        return prefix[:probe_size]
    return FileMediaSource(path).prefix(probe_size)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="dsf",
        builder_ref="exifmodern.formats.dsf:invoke_dsf",
        patterns=(Pattern(0, b"DSD "),),
    ),
)
