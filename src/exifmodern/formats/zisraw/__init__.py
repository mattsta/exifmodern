"""ZISRAW/CZI transaction planning public API."""

from pathlib import Path

from exifmodern.formats.zisraw.metadata_transaction_plan import (
    ZisrawMetadataTransactionPlan,
    ZisrawRewriteRequest,
    build_zisraw_metadata_transaction_plan,
)
from exifmodern.formats.zisraw.read_graph_adapter import (
    build_zisraw_read_graph,
    build_zisraw_read_graph_from_file,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "ZisrawMetadataTransactionPlan",
    "ZisrawRewriteRequest",
    "build_zisraw_metadata_transaction_plan",
    "build_zisraw_read_graph",
    "build_zisraw_read_graph_from_file",
    "invoke_zisraw",
)


def invoke_zisraw(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_zisraw_read_graph_from_file(path, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    # We adopt ExifTool's canonical name "czi" (Carl Zeiss Image —
    # Zeiss Integrated Software RAW) so the merge dedupes against
    # ExifTool's CZI import. The Python module dir is "zisraw"
    # because that's the literal magic prefix in the file format.
    Signature(
        format_id="czi",
        builder_ref="exifmodern.formats.zisraw:invoke_zisraw",
        patterns=(Pattern(0, b"ZISRAWFILE\x00\x00\x00\x00\x00\x00"),),
    ),
)
