"""ASF metadata transaction planning."""

from pathlib import Path

from exifmodern.formats.asf.metadata_transaction_plan import (
    AsfMetadataTransactionPlan,
    AsfMetadataWriteRequest,
    build_asf_metadata_transaction_plan,
)
from exifmodern.formats.asf.read_graph_adapter import (
    asf_header_byte_count,
    build_asf_read_graph,
    build_asf_read_graph_from_file,
    is_asf_prefix,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "AsfMetadataTransactionPlan",
    "AsfMetadataWriteRequest",
    "asf_header_byte_count",
    "build_asf_metadata_transaction_plan",
    "build_asf_read_graph",
    "build_asf_read_graph_from_file",
    "invoke_asf",
    "is_asf_prefix",
]


def invoke_asf(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_asf_read_graph_from_file(path, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="asf",
        builder_ref="exifmodern.formats.asf:invoke_asf",
        patterns=(Pattern(0, b"\x30\x26\xb2\x75\x8e\x66\xcf\x11\xa6\xd9\x00\xaa\x00\x62\xce\x6c"),),
    ),
)
