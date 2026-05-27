"""BMP/DIB transaction planning primitives translated from ExifTool BMP.pm."""

from pathlib import Path

from exifmodern.formats.bmp.header_transaction_plan import (
    BmpHeaderTransactionPlan,
    build_bmp_header_transaction_plan,
    plan_bmp_header_transaction,
)
from exifmodern.formats.bmp.read_graph_adapter import (
    build_bmp_read_graph,
    render_bmp_header_transaction_plan_record,
)
from exifmodern.formats.bmp.subtable_plan import (
    BmpSubtablePlan,
    build_bmp_subtable_plan,
)
from exifmodern.formats.public_payload import (
    oversized_public_payload_graph,
    read_public_document_payload,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "BmpHeaderTransactionPlan",
    "BmpSubtablePlan",
    "build_bmp_header_transaction_plan",
    "build_bmp_read_graph",
    "build_bmp_subtable_plan",
    "invoke_bmp",
    "plan_bmp_header_transaction",
    "render_bmp_header_transaction_plan_record",
]


def invoke_bmp(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = read_public_document_payload(path)
    if data is None:
        return oversized_public_payload_graph(source_file, format_name="BMP")
    return build_bmp_read_graph(data, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="bmp",
        builder_ref="exifmodern.formats.bmp:invoke_bmp",
        patterns=(Pattern(0, b"BM"),),
    ),
)
