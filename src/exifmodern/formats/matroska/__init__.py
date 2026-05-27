"""Matroska EBML planning helpers."""

from pathlib import Path

from exifmodern.formats.matroska.ebml_transaction_plan import (
    EBML_HEADER_ID,
    INFO_ID,
    SEGMENT_ID,
    TAGS_ID,
    MatroskaEbmlTransactionPlan,
    MatroskaTagWriteRequest,
    build_matroska_ebml_transaction_plan,
    encode_ebml_element,
    encode_ebml_vint,
    inspect_matroska_ebml,
    read_ebml_vint,
)
from exifmodern.formats.matroska.read_graph_adapter import (
    build_matroska_read_graph,
    build_matroska_read_graph_from_file,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "EBML_HEADER_ID",
    "INFO_ID",
    "SEGMENT_ID",
    "TAGS_ID",
    "MatroskaEbmlTransactionPlan",
    "MatroskaTagWriteRequest",
    "build_matroska_ebml_transaction_plan",
    "build_matroska_read_graph",
    "build_matroska_read_graph_from_file",
    "encode_ebml_element",
    "encode_ebml_vint",
    "inspect_matroska_ebml",
    "invoke_matroska",
    "read_ebml_vint",
]


def invoke_matroska(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_matroska_read_graph_from_file(path, source_file=source_file, prefix=prefix)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="matroska",
        builder_ref="exifmodern.formats.matroska:invoke_matroska",
        patterns=(Pattern(0, b"\x1a\x45\xdf\xa3"),),
    ),
)
