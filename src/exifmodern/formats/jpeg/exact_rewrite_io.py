"""Exact byte materialization for JPEG writer replacement streams."""

from __future__ import annotations

from pathlib import Path


def read_exact_jpeg_rewrite_source(path: Path) -> bytes:
    """Read a JPEG source when the writer must emit a complete replacement file.

    ExifTool's Writer.pl WriteJPEG copies the entropy-coded image stream and any
    retained trailer bytes while rewriting metadata segments. The current Python
    JPEG writer APIs likewise return a complete replacement byte stream, so a
    range probe is not a safe substitute at these file-wrapper boundaries.
    """
    with path.open("rb") as file:
        return file.read()


def read_exact_sidecar_payload(path: Path) -> bytes:
    """Read an EXIF/XMP sidecar whose entire file is the copy payload."""
    with path.open("rb") as file:
        return file.read()
