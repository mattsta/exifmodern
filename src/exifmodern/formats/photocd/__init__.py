"""PhotoCD metadata transaction planning public API."""

from pathlib import Path

from exifmodern.formats.photocd.metadata_transaction_plan import (
    PhotoCdMetadataTransactionPlan,
    build_photocd_metadata_transaction_plan,
)
from exifmodern.formats.photocd.read_graph_adapter import (
    build_photocd_read_graph,
    build_photocd_read_graph_from_file,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "PhotoCdMetadataTransactionPlan",
    "build_photocd_metadata_transaction_plan",
    "build_photocd_read_graph",
    "build_photocd_read_graph_from_file",
    "invoke_photocd",
)


def invoke_photocd(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_photocd_read_graph_from_file(path, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="photocd",
        builder_ref="exifmodern.formats.photocd:invoke_photocd",
        patterns=(Pattern(2048, b"PCD_IPI"),),
    ),
)
