"""Musepack/MPC metadata transaction planning public API."""

from pathlib import Path

from exifmodern.formats.mpc_audio.read_graph_adapter import (
    build_mpc_read_graph,
    build_mpc_read_graph_from_file,
    is_mpc_prefix,
)
from exifmodern.formats.mpc_audio.transaction_plan import (
    MpcAudioRewriteRequest,
    MpcAudioTransactionPlan,
    build_mpc_audio_transaction_plan,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "MpcAudioRewriteRequest",
    "MpcAudioTransactionPlan",
    "build_mpc_audio_transaction_plan",
    "build_mpc_read_graph",
    "build_mpc_read_graph_from_file",
    "invoke_mpc",
    "is_mpc_prefix",
]


def invoke_mpc(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_mpc_read_graph_from_file(path, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="mpc",
        builder_ref="exifmodern.formats.mpc_audio:invoke_mpc",
        patterns=(Pattern(0, b"MP+"),),
        structural_check="exifmodern.formats.mpc_audio.read_graph_adapter:is_mpc_prefix",
        extensions=(".mpc",),
    ),
)
