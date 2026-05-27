"""AAC/ADTS transaction planning helpers."""

from pathlib import Path

from exifmodern.formats.aac.read_graph_adapter import (
    aac_first_frame_byte_count,
    build_aac_read_graph,
    is_aac_prefix,
)
from exifmodern.formats.aac.stream_transaction_plan import (
    AacMetadataRewriteRequest,
    AacStreamTransactionPlan,
    build_aac_stream_transaction_plan,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "AacMetadataRewriteRequest",
    "AacStreamTransactionPlan",
    "aac_first_frame_byte_count",
    "build_aac_read_graph",
    "build_aac_stream_transaction_plan",
    "invoke_aac",
    "is_aac_prefix",
]


def invoke_aac(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    byte_count = aac_first_frame_byte_count(prefix)
    if byte_count is None:
        data = prefix[:0]
    elif len(prefix) >= byte_count:
        data = prefix[:byte_count]
    else:
        with path.open("rb") as file:
            data = file.read(byte_count)
    return build_aac_read_graph(data, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="aac",
        builder_ref="exifmodern.formats.aac:invoke_aac",
        patterns=(Pattern(0, b"\xff\xf0"),),
        structural_check="exifmodern.formats.aac.read_graph_adapter:is_aac_prefix",
    ),
    Signature(
        format_id="aac/short",
        builder_ref="exifmodern.formats.aac:invoke_aac",
        patterns=(Pattern(0, b"\xff\xf1"),),
        structural_check="exifmodern.formats.aac.read_graph_adapter:is_aac_prefix",
    ),
)
