"""Garmin FIT metadata transaction planning public API."""

from pathlib import Path

from exifmodern.formats.garmin.metadata_transaction_plan import (
    GarminMetadataTransactionPlan,
    GarminRewriteRequest,
    build_garmin_metadata_transaction_plan,
)
from exifmodern.formats.garmin.read_graph_adapter import (
    build_garmin_read_graph,
    build_garmin_read_graph_from_file,
    is_fit_prefix,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "GarminMetadataTransactionPlan",
    "GarminRewriteRequest",
    "build_garmin_metadata_transaction_plan",
    "build_garmin_read_graph",
    "build_garmin_read_graph_from_file",
    "invoke_garmin",
    "is_fit_prefix",
)


def invoke_garmin(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_garmin_read_graph_from_file(path, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="fit",
        builder_ref="exifmodern.formats.garmin:invoke_garmin",
        patterns=(Pattern(8, b".FIT"),),
        structural_check="exifmodern.formats.garmin.read_graph_adapter:is_fit_prefix",
        extensions=(".fit",),
    ),
    Signature(
        format_id="garmin/fit",
        builder_ref="exifmodern.formats.garmin:invoke_garmin",
        patterns=(Pattern(8, b".FIT"),),
        structural_check="exifmodern.formats.garmin.read_graph_adapter:is_fit_prefix",
    ),
)
