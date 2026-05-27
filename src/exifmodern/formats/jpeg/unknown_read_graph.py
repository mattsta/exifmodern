"""JPEG APP1 bridge for source-backed TIFF dynamic unknown tags."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.jpeg.container import read_exif_app1
from exifmodern.formats.tiff.unknown_read_graph import (
    TiffUnknownIfdReadTag,
    collect_tiff_unknown_ifd_read_tags,
)


@dataclass(frozen=True)
class JpegExifUnknownIfdReadResult:
    tags: tuple[TiffUnknownIfdReadTag, ...]
    diagnostics: tuple[str, ...]
    evidence_ids: tuple[str, ...]


def collect_jpeg_exif_unknown_ifd_read_tags(path: Path) -> JpegExifUnknownIfdReadResult:
    try:
        app1 = read_exif_app1(path)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("No JPEG EXIF APP1 segment found"):
            return JpegExifUnknownIfdReadResult(tags=(), diagnostics=(), evidence_ids=())
        return JpegExifUnknownIfdReadResult(
            tags=(),
            diagnostics=(f"JPEG EXIF dynamic unknown discovery blocked: {message}",),
            evidence_ids=(),
        )
    tiff_result = collect_tiff_unknown_ifd_read_tags(app1.tiff_data)
    return JpegExifUnknownIfdReadResult(
        tags=tiff_result.tags,
        diagnostics=tiff_result.diagnostics,
        evidence_ids=tiff_result.provenance,
    )
