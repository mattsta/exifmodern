"""MPEG stream transaction planning helpers."""

from pathlib import Path

from exifmodern.formats.mpeg.read_graph_adapter import (
    build_mp3_read_graph,
    build_mpeg_read_graph,
    mp3_audio_transaction_plan_to_read_graph,
    render_mp3_audio_transaction_plan_record,
)
from exifmodern.formats.mpeg.stream_transaction_plan import (
    MPEG_START_CODE_PREFIX,
    MpegAudioHeaderPlan,
    MpegDurationPlan,
    MpegOutputEmissionGate,
    MpegPayloadPreservationPlan,
    MpegResponsibilityPlan,
    MpegStartCodePlan,
    MpegStreamRoutePlan,
    MpegStreamTransactionPlan,
    MpegVideoSequenceHeaderPlan,
    build_mp3_audio_transaction_plan,
    build_mpeg_stream_transaction_plan,
    plan_mpeg_stream_transaction,
    scan_mpeg_start_codes,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

MP3_EXIFTOOL_SCAN_BYTES = 0x10000
MP3_EXTENSION_SCAN_BYTES = 8192
MP3_ID3_HEADER_BYTES = 10
MP3_TAIL_TAG_BYTES = 355
MPEG_EXIFTOOL_SCAN_BYTES = 65536 * 4

__all__ = [
    "MPEG_START_CODE_PREFIX",
    "MpegAudioHeaderPlan",
    "MpegDurationPlan",
    "MpegOutputEmissionGate",
    "MpegPayloadPreservationPlan",
    "MpegResponsibilityPlan",
    "MpegStartCodePlan",
    "MpegStreamRoutePlan",
    "MpegStreamTransactionPlan",
    "MpegVideoSequenceHeaderPlan",
    "build_mp3_audio_transaction_plan",
    "build_mp3_read_graph",
    "build_mpeg_read_graph",
    "build_mpeg_stream_transaction_plan",
    "invoke_mp3",
    "invoke_mpeg",
    "mp3_audio_transaction_plan_to_read_graph",
    "plan_mpeg_stream_transaction",
    "render_mp3_audio_transaction_plan_record",
    "scan_mpeg_start_codes",
]


def invoke_mp3(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_mp3_invoker_bytes(path, prefix)
    return build_mp3_read_graph(data, source_file=source_file, file_size=path.stat().st_size)


def invoke_mpeg(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_prefix(path, MPEG_EXIFTOOL_SCAN_BYTES, prefix)
    return build_mpeg_read_graph(data, source_file=source_file, file_size=path.stat().st_size)


def _read_mp3_invoker_bytes(path: Path, prefix: bytes) -> bytes:
    file_size = path.stat().st_size
    leading_size = _leading_id3v2_size_from_prefix(path, prefix)
    prefix_size = max(MP3_EXTENSION_SCAN_BYTES, leading_size + MP3_EXIFTOOL_SCAN_BYTES)
    head = _read_prefix(path, min(prefix_size, file_size), prefix)
    tail_size = min(MP3_TAIL_TAG_BYTES, file_size)
    if len(head) >= file_size or tail_size == 0:
        return head
    tail = _read_tail(path, tail_size)
    overlap = max(0, len(head) + len(tail) - file_size)
    return head + tail[overlap:]


def _leading_id3v2_size_from_prefix(path: Path, prefix: bytes) -> int:
    if not prefix.startswith(b"ID3"):
        return 0
    header = _read_prefix(path, MP3_ID3_HEADER_BYTES, prefix)
    if len(header) < MP3_ID3_HEADER_BYTES:
        return 0
    size_bytes = header[6:10]
    if any(byte & 0x80 for byte in size_bytes):
        return 0
    payload_size = (
        (size_bytes[0] << 21) | (size_bytes[1] << 14) | (size_bytes[2] << 7) | size_bytes[3]
    )
    return MP3_ID3_HEADER_BYTES + payload_size


def _read_prefix(path: Path, byte_count: int, prefix: bytes = b"") -> bytes:
    if len(prefix) >= byte_count:
        return prefix[:byte_count]
    with path.open("rb") as file:
        return file.read(byte_count)


def _read_tail(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        file.seek(-byte_count, 2)
        return file.read(byte_count)


# MP3 has no usable magic byte (the optional ID3v2 tag is handled by the
# id3 module; the raw MPEG audio frame sync `\xff\xfb` etc. collides
# with too many other things to dispatch on safely). So MP3 is an
# extension-only signature: the trie never matches a magic for it; the
# runtime's extension-fallback table consults this entry when a `.mp3`
# file's prefix didn't match any signature.
SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="mp3",
        builder_ref="exifmodern.formats.mpeg:invoke_mp3",
        patterns=(),  # extension-only — no magic
        extensions=(".mp3",),
        weak=True,
    ),
    *tuple(
        Signature(
            format_id=f"mpeg/v{code - 0xB0}",
            builder_ref="exifmodern.formats.mpeg:invoke_mpeg",
            patterns=(Pattern(0, b"\x00\x00\x01" + bytes((code,))),),
        )
        for code in range(0xB0, 0xC0)
    ),
)
