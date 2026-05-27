"""WavPack planning surfaces."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.wavpack.block_transaction_plan import (
    APE_DESCRIPTOR_SIZE,
    APE_SIGNATURE,
    ID3V1_TRAILER_SIZE,
    WAVPACK_BLOCK_HEADER_SIZE,
    WAVPACK_BLOCK_SIZE_FIELD_ADJUSTMENT,
    WAVPACK_MIN_DECLARED_BLOCK_SIZE,
    WAVPACK_SIGNATURE,
    WavPackBlockTransactionBlocked,
    WavPackBlockTransactionPlan,
    WavPackRewriteRequest,
    build_audio_header_plan,
    build_wavpack_block_transaction_plan,
    inspect_wavpack_header,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = [
    "WavPackBlockTransactionBlocked",
    "WavPackBlockTransactionPlan",
    "WavPackRewriteRequest",
    "build_wavpack_block_transaction_plan",
    "build_wavpack_read_graph",
    "build_wavpack_read_graph_from_file",
    "invoke_wavpack",
]


_WAVPACK_TABLE = "Image::ExifTool::WavPack::Main"


def build_wavpack_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a WavPack block transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_wavpack_block_transaction_plan(data)
    diagnostics = [
        f"WavPack package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"WavPack package-local reader status: {plan.status}")

    tags: list[ReadTag] = []
    audio = plan.audio_header
    if audio is not None:
        audio_scalars: tuple[tuple[str, int | float | str | None], ...] = (
            ("BytesPerSample", audio.bytes_per_sample),
            ("AudioType", audio.audio_type),
            ("ChannelCount", audio.channel_count),
            ("Compression", audio.compression),
            ("DataFormat", audio.data_format),
            ("SampleRate", audio.sample_rate_hz),
            ("SampleRateLabel", audio.sample_rate_label),
            ("TotalSamples", audio.total_samples),
            ("BlockSamples", audio.block_samples),
            ("Duration", audio.duration_seconds),
        )
        for name, value in audio_scalars:
            if value is None:
                continue
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_provenance(
                        group="Audio",
                        table_name=_WAVPACK_TABLE,
                        tag_id=name,
                        evidence_ids=audio.evidence_ids,
                    ),
                    schema=None,
                )
            )
    delegation = plan.tag_delegation
    delegation_flags: tuple[tuple[str, bool], ...] = (
        ("ID3v2Present", delegation.leading_id3v2_present),
        ("ID3v1Present", delegation.trailing_id3v1_present),
        ("APEv2HeaderPresent", delegation.apev2_header_at_tag_tail),
        ("APEv2FooterPresent", delegation.trailing_apev2_footer_present),
    )
    for name, flag in delegation_flags:
        if not flag:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(True),
                provenance=_provenance(
                    group="Audio",
                    table_name=_WAVPACK_TABLE,
                    tag_id=name,
                    evidence_ids=delegation.evidence_ids,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_wavpack(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_wavpack_read_graph_from_file(path, prefix, source_file)


def build_wavpack_read_graph_from_file(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Build WavPack read tags from ExifTool's 32-byte header and tail probes."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    header_bytes = prefix[:WAVPACK_BLOCK_HEADER_SIZE]
    if len(header_bytes) < WAVPACK_BLOCK_HEADER_SIZE:
        with path.open("rb") as file:
            header_bytes = file.read(WAVPACK_BLOCK_HEADER_SIZE)
    header = inspect_wavpack_header(header_bytes)
    if header.issue is not None:
        return build_wavpack_read_graph(header_bytes, source_file)

    total_samples = int.from_bytes(header_bytes[12:16], "little")
    block_index = int.from_bytes(header_bytes[16:20], "little")
    block_samples = int.from_bytes(header_bytes[20:24], "little")
    flags = int.from_bytes(header_bytes[24:28], "little")
    audio = build_audio_header_plan(total_samples, block_index, block_samples, flags)

    tags: list[ReadTag] = []
    audio_scalars: tuple[tuple[str, int | float | str | None], ...] = (
        ("BytesPerSample", audio.bytes_per_sample),
        ("AudioType", audio.audio_type),
        ("ChannelCount", audio.channel_count),
        ("Compression", audio.compression),
        ("DataFormat", audio.data_format),
        ("SampleRate", audio.sample_rate_hz),
        ("SampleRateLabel", audio.sample_rate_label),
        ("TotalSamples", audio.total_samples),
        ("BlockSamples", audio.block_samples),
        ("Duration", audio.duration_seconds),
    )
    for name, value in audio_scalars:
        if value is None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="Audio",
                    table_name=_WAVPACK_TABLE,
                    tag_id=name,
                    evidence_ids=audio.evidence_ids,
                ),
                schema=None,
            )
        )

    file_size = path.stat().st_size
    audio_end = _wavpack_audio_end_offset(path, file_size)
    tail_flags = _wavpack_tail_flags(path, file_size, audio_end)
    for name, flag in tail_flags:
        if not flag:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(True),
                provenance=_provenance(
                    group="Audio",
                    table_name=_WAVPACK_TABLE,
                    tag_id=name,
                    evidence_ids=("wavpack.delegation",),
                ),
                schema=None,
            )
        )
    diagnostics = [
        "WavPack package-local reader gate: wavpack_identity_emission_not_requested: "
        "WavPack block transaction plans are non-mutating; opt in to identity-only "
        "emission explicitly."
    ]
    return _graph(source_file, tags, diagnostics)


def _wavpack_audio_end_offset(path: Path, file_size: int) -> int:
    offset = 0
    while offset + WAVPACK_BLOCK_HEADER_SIZE <= file_size:
        header = _read_at(path, offset, WAVPACK_BLOCK_HEADER_SIZE)
        if len(header) < WAVPACK_BLOCK_HEADER_SIZE or not header.startswith(WAVPACK_SIGNATURE):
            break
        declared_size = int.from_bytes(header[4:8], "little")
        if declared_size < WAVPACK_MIN_DECLARED_BLOCK_SIZE:
            break
        next_offset = offset + declared_size + WAVPACK_BLOCK_SIZE_FIELD_ADJUSTMENT
        if next_offset > file_size:
            break
        offset = next_offset
    return offset


def _wavpack_tail_flags(
    path: Path,
    file_size: int,
    audio_end: int,
) -> tuple[tuple[str, bool], ...]:
    leading_id3v2 = _read_at(path, 0, 3) == b"ID3"
    id3v1 = (
        file_size >= ID3V1_TRAILER_SIZE
        and _read_at(
            path,
            file_size - ID3V1_TRAILER_SIZE,
            3,
        )
        == b"TAG"
    )
    search_end = file_size - ID3V1_TRAILER_SIZE if id3v1 else file_size
    footer = _read_at(path, search_end - APE_DESCRIPTOR_SIZE, APE_DESCRIPTOR_SIZE)
    ape_footer = footer.startswith(APE_SIGNATURE)
    ape_header = _read_at(path, audio_end, len(APE_SIGNATURE)) == APE_SIGNATURE
    return (
        ("ID3v2Present", leading_id3v2),
        ("ID3v1Present", id3v1),
        ("APEv2HeaderPresent", ape_header),
        ("APEv2FooterPresent", ape_footer),
    )


def _read_at(path: Path, offset: int, byte_count: int) -> bytes:
    if offset < 0 or byte_count <= 0:
        return b""
    with path.open("rb") as file:
        file.seek(offset)
        return file.read(byte_count)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="wavpack",
        builder_ref="exifmodern.formats.wavpack:invoke_wavpack",
        patterns=(Pattern(0, b"wvpk"),),
    ),
)
