"""AIFF planning helpers."""

from pathlib import Path

from exifmodern.formats.aiff.chunk_transaction_plan import (
    AiffChunkTransactionPlan,
    AiffMetadataChunkRequest,
    build_aiff_chunk_transaction_plan,
)
from exifmodern.formats.aiff.read_graph_adapter import (
    build_aiff_read_graph,
    build_aiff_read_graph_from_file,
    is_aiff_prefix,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "AiffChunkTransactionPlan",
    "AiffMetadataChunkRequest",
    "build_aiff_chunk_transaction_plan",
    "build_aiff_read_graph",
    "build_aiff_read_graph_from_file",
    "invoke_aiff",
    "is_aiff_prefix",
]


def invoke_aiff(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_aiff_read_graph_from_file(path, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="aiff",
        builder_ref="exifmodern.formats.aiff:invoke_aiff",
        patterns=(Pattern(0, b"FORM"), Pattern(8, b"AIFF")),
    ),
    Signature(
        format_id="aiff/aifc",
        builder_ref="exifmodern.formats.aiff:invoke_aiff",
        patterns=(Pattern(0, b"FORM"), Pattern(8, b"AIFC")),
    ),
)
