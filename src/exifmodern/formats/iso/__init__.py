"""ISO 9660 metadata transaction planning."""

from pathlib import Path

from exifmodern.formats.iso.read_graph_adapter import (
    build_iso_read_graph_from_path,
    iso_reader_plan_to_read_graph,
    read_iso_descriptors,
)
from exifmodern.formats.iso.transaction_plan import (
    ISO_DESCRIPTOR_OFFSET,
    ISO_DESCRIPTOR_SIZE,
    IsoDescriptorPlan,
    IsoMetadataTransactionPlan,
    IsoReaderPlan,
    IsoReadTag,
    IsoRewriteRequest,
    build_iso_metadata_transaction_plan,
    build_iso_reader_plan,
    iso_volume_size,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "ISO_DESCRIPTOR_OFFSET",
    "ISO_DESCRIPTOR_SIZE",
    "SIGNATURES",
    "IsoDescriptorPlan",
    "IsoMetadataTransactionPlan",
    "IsoReadTag",
    "IsoReaderPlan",
    "IsoRewriteRequest",
    "build_iso_metadata_transaction_plan",
    "build_iso_read_graph_from_path",
    "build_iso_reader_plan",
    "invoke_iso",
    "iso_reader_plan_to_read_graph",
    "iso_volume_size",
    "read_iso_descriptors",
]


def invoke_iso(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by trie-driven dispatch."""
    return build_iso_read_graph_from_path(path, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="iso",
        builder_ref="exifmodern.formats.iso:invoke_iso",
        patterns=(Pattern(ISO_DESCRIPTOR_OFFSET + 1, b"CD001"),),
        extensions=(".iso",),
    ),
)
