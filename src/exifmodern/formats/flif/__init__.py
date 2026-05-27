"""FLIF image transaction planning primitives translated from ExifTool FLIF.pm."""

from pathlib import Path

from exifmodern.formats.flif.image_transaction_plan import (
    FlifImageTransactionPlan,
    build_flif_image_transaction_plan,
)
from exifmodern.formats.flif.read_graph_adapter import (
    build_flif_read_graph,
    build_flif_read_graph_from_file,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "FlifImageTransactionPlan",
    "build_flif_image_transaction_plan",
    "build_flif_read_graph",
    "build_flif_read_graph_from_file",
    "invoke_flif",
]


def invoke_flif(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_flif_read_graph_from_file(path, source_file=source_file)


_VALID_FLIF_TYPES = (b"1", b"3", b"4", b"A", b"C", b"D", b"Q", b"S", b"T", b"a", b"c", b"d")
_VALID_FLIF_DEPTHS = (b"0", b"1", b"2")
_EXIFTOOL_TRANSLATED_FLIF_PATTERNS: tuple[tuple[str, bytes], ...] = (
    ("flif/v0", b"FLIF--"),
    ("flif/v1", b"FLIF-0"),
    ("flif/v2", b"FLIF-2"),
    ("flif/v3", b"FLIF0-"),
    ("flif/v4", b"FLIF00"),
    ("flif/v5", b"FLIF02"),
    ("flif/v6", b"FLIFo-"),
    ("flif/v7", b"FLIFo0"),
    ("flif/v8", b"FLIFo2"),
)

SIGNATURES: tuple[Signature, ...] = (
    *(
        Signature(
            format_id=f"flif/{image_type.decode('ascii')}/{bit_depth.decode('ascii')}",
            builder_ref="exifmodern.formats.flif:invoke_flif",
            patterns=(Pattern(0, b"FLIF" + image_type + bit_depth),),
        )
        for image_type in _VALID_FLIF_TYPES
        for bit_depth in _VALID_FLIF_DEPTHS
    ),
    *(
        Signature(
            format_id=format_id,
            builder_ref="exifmodern.formats.flif:invoke_flif",
            patterns=(Pattern(0, pattern),),
        )
        for format_id, pattern in _EXIFTOOL_TRANSLATED_FLIF_PATTERNS
    ),
)
