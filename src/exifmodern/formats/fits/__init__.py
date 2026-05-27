"""FITS format planning surfaces."""

from pathlib import Path

from exifmodern.dispatch_helpers import build_fits_read_graph
from exifmodern.formats.fits.header_transaction_plan import (
    FITS_BLOCK_SIZE,
    FITS_CARD_SIZE,
    FitsReadTagRecord,
    build_fits_header_transaction_plan,
)
from exifmodern.media_source import FileMediaSource
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "FitsReadTagRecord",
    "build_fits_header_transaction_plan",
    "invoke_fits",
    "read_fits_header_blocks",
]


def invoke_fits(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_fits_read_graph(read_fits_header_blocks(path, prefix), source_file)


def read_fits_header_blocks(path: Path, prefix: bytes) -> bytes:
    """Read only FITS header blocks needed by ExifTool's card loop.

    FITS.pm validates the initial 80-byte SIMPLE card, then reads 80-byte
    header cards until END. FITS headers are padded to 2880-byte blocks, so a
    valid default read does not need to materialize the following image data.
    """
    source = FileMediaSource(path)
    header = bytearray(prefix)
    if len(header) < FITS_BLOCK_SIZE:
        header = bytearray(source.prefix(FITS_BLOCK_SIZE))
    offset = 0
    while True:
        while offset + FITS_CARD_SIZE <= len(header):
            if header[offset : offset + FITS_CARD_SIZE].startswith(b"END"):
                padded_end = _fits_padded_header_end(offset + FITS_CARD_SIZE)
                if len(header) >= padded_end:
                    return bytes(header[:padded_end])
                return source.prefix(padded_end)
            offset += FITS_CARD_SIZE
        next_size = len(header) + FITS_BLOCK_SIZE
        expanded = source.prefix(next_size)
        if len(expanded) <= len(header):
            return bytes(expanded)
        header = bytearray(expanded)


def _fits_padded_header_end(header_cards_end: int) -> int:
    return ((header_cards_end + FITS_BLOCK_SIZE - 1) // FITS_BLOCK_SIZE) * FITS_BLOCK_SIZE


SIGNATURES: tuple[Signature, ...] = (
    # Magic-byte signature: every conforming FITS file starts with
    # `SIMPLE  =` (spaces are part of the spec).
    Signature(
        format_id="fits",
        builder_ref="exifmodern.formats.fits:invoke_fits",
        patterns=(Pattern(0, b"SIMPLE  ="),),
    ),
    # Extension fallback: catches non-conforming `.fits`/`.fit`/`.fts`
    # files (e.g. headers truncated by an upstream tool). Same builder.
    Signature(
        format_id="fits/by-ext",
        builder_ref="exifmodern.formats.fits:invoke_fits",
        patterns=(),
        extensions=(".fit", ".fits", ".fts"),
    ),
)
