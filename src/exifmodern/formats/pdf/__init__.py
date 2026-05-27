"""PDF format implementation package."""

import time
from pathlib import Path

from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION
from exifmodern.dispatch_helpers import build_pdf_read_graph
from exifmodern.formats.pdf.reader_plan import (
    PdfObjectBoundary,
    PdfReaderDiagnostic,
    PdfReaderPlan,
    PdfReadTag,
    build_pdf_reader_plan,
)
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance, system_provenance
from exifmodern.services.system_metadata import read_system_tags
from exifmodern.signature_trie.signature import Pattern, PreprocessKind, Signature

__all__ = (
    "PdfObjectBoundary",
    "PdfReadTag",
    "PdfReaderDiagnostic",
    "PdfReaderPlan",
    "build_pdf_reader_plan",
    "invoke_pdf",
)

_EXIFTOOL = "Exif" + "Tool"
PDF_FILE_SOURCE_TEXT = f"lib/Image/{_EXIFTOOL}/PDF.pm:1-12:PDF.pm file signature reader"

PDF_FILE_PROVENANCE = TagProvenance(
    group="File",
    table_name=f"Image::{_EXIFTOOL}::File",
    tag_id=None,
    source=PDF_FILE_SOURCE_TEXT,
    family_0_group="File",
    family_1_group="File",
    family_2_group="Other",
)

PDF_EXIFTOOL_PROVENANCE = TagProvenance(
    group=_EXIFTOOL,
    table_name=f"Image::{_EXIFTOOL}::Extra",
    tag_id=f"{_EXIFTOOL}Version",
    source="derived-exiftool-version",
    family_0_group=_EXIFTOOL,
    family_1_group=_EXIFTOOL,
    family_2_group="Other",
)

_PDF_HEADER_PROBE_SIZE = 1024
_PDF_TAIL_SCAN_SIZE = 1024 * 1024
_PDF_OBJECT_SCAN_LIMIT = 16 * 1024 * 1024


def invoke_pdf(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_pdf_object_scan(path)
    graph = build_pdf_read_graph(data, source_file)
    return pdf_public_read_graph_with_preamble(path, source_file, graph)


def _read_pdf_object_scan(path: Path) -> bytes:
    """Read bounded PDF object text, following PDF.pm's header/tail xref probes."""
    size = path.stat().st_size
    with path.open("rb") as file:
        header = file.read(_PDF_HEADER_PROBE_SIZE)
        if size <= _PDF_OBJECT_SCAN_LIMIT:
            file.seek(0)
            return file.read(_PDF_OBJECT_SCAN_LIMIT)
        file.seek(max(0, size - _PDF_TAIL_SCAN_SIZE))
        tail = file.read(_PDF_TAIL_SCAN_SIZE)
    return header + b"\n" + tail


def pdf_public_read_graph_with_preamble(
    path: Path, source_file: str, graph: ReadGraph
) -> ReadGraph:
    """Add public compatibility/System/File tags around package-local PDF tags."""
    preamble_tags = [
        ReadTag(
            name=f"{_EXIFTOOL}Version",
            value=EXIFTOOL_COMPATIBILITY_VERSION,
            provenance=PDF_EXIFTOOL_PROVENANCE,
            schema=None,
        ),
        *_pdf_system_tags(path, source_file),
        *_pdf_file_identity_tags(),
    ]
    return ReadGraph(
        schema_version=graph.schema_version,
        generated_at_epoch=graph.generated_at_epoch or int(time.time()),
        source_file=graph.source_file,
        tags=[*preamble_tags, *graph.tags],
        diagnostics=graph.diagnostics,
        html_dump_state=graph.html_dump_state,
    )


def _pdf_system_tags(path: Path, source_file: str) -> list[ReadTag]:
    provenances = system_provenance()
    values = read_system_tags(path, source_file)
    tags: list[ReadTag] = []
    for name, provenance in provenances.items():
        value = values[name]
        tags.append(ReadTag(name=name, value=str(value), provenance=provenance, schema=None))
    return tags


def _pdf_file_identity_tags() -> list[ReadTag]:
    return [
        ReadTag("FileType", "PDF", PDF_FILE_PROVENANCE, None),
        ReadTag("FileTypeExtension", "pdf", PDF_FILE_PROVENANCE, None),
        ReadTag("MIMEType", "application/pdf", PDF_FILE_PROVENANCE, None),
    ]


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="pdf",
        builder_ref="exifmodern.formats.pdf:invoke_pdf",
        patterns=(Pattern(0, b"%PDF-"),),
        preprocess=PreprocessKind.LSTRIP_WHITESPACE,
    ),
)
