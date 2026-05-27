"""DPX transaction planning public API."""

from pathlib import Path

from exifmodern.dispatch_helpers import build_dpx_read_graph
from exifmodern.formats.dpx.image_transaction_plan import (
    DPX_EXIFTOOL_READ_SIZE,
    DpxImageTransactionPlan,
    DpxReadTagRecord,
    DpxRewriteRequest,
    build_dpx_image_transaction_plan,
)
from exifmodern.media_source import FileMediaSource
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "DPX_EXIFTOOL_READ_SIZE",
    "DpxImageTransactionPlan",
    "DpxReadTagRecord",
    "DpxRewriteRequest",
    "build_dpx_image_transaction_plan",
    "invoke_dpx",
)


def invoke_dpx(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = (
        prefix[:DPX_EXIFTOOL_READ_SIZE]
        if len(prefix) >= DPX_EXIFTOOL_READ_SIZE
        else FileMediaSource(path).prefix(DPX_EXIFTOOL_READ_SIZE)
    )
    return build_dpx_read_graph(data, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="dpx/be",
        builder_ref="exifmodern.formats.dpx:invoke_dpx",
        patterns=(Pattern(0, b"SDPX"),),
    ),
    Signature(
        format_id="dpx/le",
        builder_ref="exifmodern.formats.dpx:invoke_dpx",
        patterns=(Pattern(0, b"XPDS"),),
    ),
)
