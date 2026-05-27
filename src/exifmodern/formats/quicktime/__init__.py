"""QuickTime/ISO BMFF container adapters."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = ["invoke_quicktime"]


def invoke_quicktime(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    from exifmodern.formats.quicktime.read_graph_adapter import build_quicktime_read_graph

    return build_quicktime_read_graph(prefix, path, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="quicktime/free",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"free"),),
    ),
    Signature(
        format_id="quicktime/skip",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"skip"),),
    ),
    Signature(
        format_id="quicktime/wide",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"wide"),),
    ),
    Signature(
        format_id="quicktime/pnot",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"pnot"),),
    ),
    Signature(
        format_id="quicktime/PICT",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"PICT"),),
    ),
    Signature(
        format_id="quicktime/pict",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"pict"),),
    ),
    Signature(
        format_id="quicktime/moov",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"moov"),),
    ),
    Signature(
        format_id="quicktime/mdat",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"mdat"),),
    ),
    Signature(
        format_id="quicktime/junk",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"junk"),),
    ),
    Signature(
        format_id="quicktime/uuid",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"uuid"),),
    ),
    Signature(
        format_id="quicktime/ftyp",
        builder_ref="exifmodern.formats.quicktime:invoke_quicktime",
        patterns=(Pattern(4, b"ftyp"),),
    ),
)
