"""APE tag transaction planning helpers."""

from pathlib import Path

from exifmodern.formats.ape.read_graph_adapter import (
    build_ape_read_graph,
    build_ape_read_graph_from_file,
    is_ape_prefix,
)
from exifmodern.formats.ape.tag_transaction_plan import (
    APE_DESCRIPTOR_SIZE,
    APE_SIGNATURE,
    ApeDescriptorValidationPlan,
    ApeEmissionGate,
    ApeId3CoexistencePlan,
    ApeItemDatabasePlan,
    ApeItemDefinitionPlan,
    ApeItemPlan,
    ApeItemValuePlan,
    ApeRewritePlan,
    ApeTagTransactionBlocked,
    ApeTagTransactionPlan,
    build_ape_tag_database_plan,
    build_ape_tag_transaction_plan,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "APE_DESCRIPTOR_SIZE",
    "APE_SIGNATURE",
    "ApeDescriptorValidationPlan",
    "ApeEmissionGate",
    "ApeId3CoexistencePlan",
    "ApeItemDatabasePlan",
    "ApeItemDefinitionPlan",
    "ApeItemPlan",
    "ApeItemValuePlan",
    "ApeRewritePlan",
    "ApeTagTransactionBlocked",
    "ApeTagTransactionPlan",
    "build_ape_read_graph",
    "build_ape_read_graph_from_file",
    "build_ape_tag_database_plan",
    "build_ape_tag_transaction_plan",
    "invoke_ape",
    "is_ape_prefix",
]


def invoke_ape(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_ape_read_graph_from_file(path, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="ape/mac",
        builder_ref="exifmodern.formats.ape:invoke_ape",
        patterns=(Pattern(0, b"MAC "),),
    ),
    Signature(
        format_id="ape/tag",
        builder_ref="exifmodern.formats.ape:invoke_ape",
        patterns=(Pattern(0, b"APETAGEX"),),
    ),
)
