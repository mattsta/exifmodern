"""Phase One maker-note transaction planning and IIQ read dispatch."""

from pathlib import Path

from exifmodern.formats.phaseone.reader import (
    build_phaseone_iiq_read_graph,
    build_phaseone_iiq_read_graph_from_file,
    is_phaseone_iiq_prefix,
)
from exifmodern.formats.phaseone.transaction_plan import (
    PhaseOneRewriteRequest,
    PhaseOneTransactionPlan,
    build_phaseone_transaction_plan,
    plan_phaseone_transaction,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "PhaseOneRewriteRequest",
    "PhaseOneTransactionPlan",
    "build_phaseone_iiq_read_graph",
    "build_phaseone_iiq_read_graph_from_file",
    "build_phaseone_transaction_plan",
    "invoke_phaseone_iiq",
    "is_phaseone_iiq_prefix",
    "plan_phaseone_transaction",
]


def invoke_phaseone_iiq(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_phaseone_iiq_read_graph_from_file(path, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="phaseone/iiq-le",
        builder_ref="exifmodern.formats.phaseone:invoke_phaseone_iiq",
        patterns=(Pattern(0, b"II*\x00"), Pattern(8, b"IIII")),
        structural_check="exifmodern.formats.phaseone:is_phaseone_iiq_prefix",
        extensions=(".iiq",),
    ),
    Signature(
        format_id="phaseone/iiq-be",
        builder_ref="exifmodern.formats.phaseone:invoke_phaseone_iiq",
        patterns=(Pattern(0, b"MM\x00*"), Pattern(8, b"MMMM")),
        structural_check="exifmodern.formats.phaseone:is_phaseone_iiq_prefix",
        extensions=(".iiq",),
    ),
)
