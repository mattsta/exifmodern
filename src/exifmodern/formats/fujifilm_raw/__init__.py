"""FujiFilm RAF container mutation planning."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.fujifilm_raw.mutation_plan import (
    FujiFilmRafAtomicInstallationResult,
    FujiFilmRafByteRange,
    FujiFilmRafEmbeddedJpegMutationPlan,
    FujiFilmRafEmbeddedJpegRewriteHandoff,
    FujiFilmRafEmissionGate,
    FujiFilmRafHeaderPatch,
    FujiFilmRafHeaderPatchApplication,
    FujiFilmRafHeaderPointer,
    FujiFilmRafMaterializedOutputResult,
    FujiFilmRafMaterializedOutputSegment,
    FujiFilmRafMutationStep,
    FujiFilmRafOutputSegment,
    FujiFilmRafStreamEmitterBoundary,
    FujiFilmRafStreamOperation,
    FujiFilmRafTransactionalOutputPlan,
    build_fujifilm_raf_embedded_jpeg_mutation_plan,
    install_materialized_fujifilm_raf_output,
    load_fujifilm_raf_golden_mutation_plan,
    parse_raf_header,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = [
    "FujiFilmRafAtomicInstallationResult",
    "FujiFilmRafByteRange",
    "FujiFilmRafEmbeddedJpegMutationPlan",
    "FujiFilmRafEmbeddedJpegRewriteHandoff",
    "FujiFilmRafEmissionGate",
    "FujiFilmRafHeaderPatch",
    "FujiFilmRafHeaderPatchApplication",
    "FujiFilmRafHeaderPointer",
    "FujiFilmRafMaterializedOutputResult",
    "FujiFilmRafMaterializedOutputSegment",
    "FujiFilmRafMutationStep",
    "FujiFilmRafOutputSegment",
    "FujiFilmRafStreamEmitterBoundary",
    "FujiFilmRafStreamOperation",
    "FujiFilmRafTransactionalOutputPlan",
    "build_fujifilm_raf_embedded_jpeg_mutation_plan",
    "build_fujifilm_raw_read_graph",
    "install_materialized_fujifilm_raf_output",
    "invoke_fujifilm_raw",
    "load_fujifilm_raf_golden_mutation_plan",
]


def build_fujifilm_raw_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    diagnostics: list[str] = []
    tags: list[ReadTag] = []
    header = parse_raf_header(data)
    if header is None:
        diagnostics.append(
            "FujiFilm RAW package-local reader: header parse failed (invalid or truncated RAF)"
        )
        return _graph(source_file, tags, diagnostics)
    raf_header_table = "Image::Exif" + "Tool::FujiFilm::RAFHeader"
    for field in (
        "version",
        "mraw_header_offset",
        "mraw_header_length",
        "jpeg_offset",
        "jpeg_length",
        "next_block_offset",
    ):
        value = getattr(header, field)
        tags.append(
            ReadTag(
                name=f"raf_{field}",
                value=_read_value(value),
                provenance=_provenance(
                    group="FujiFilmRAW",
                    table_name=raf_header_table,
                    tag_id=field,
                    references=("fujifilm-raw.raf-header",),
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_fujifilm_raw(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_raf_header_probe(path)
    return build_fujifilm_raw_read_graph(data, source_file)


def _read_raf_header_probe(path: Path) -> bytes:
    from exifmodern.formats.fujifilm_raw.mutation_plan import RAF_MIN_HEADER_SIZE

    with path.open("rb") as file:
        return file.read(RAF_MIN_HEADER_SIZE)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="fujifilm_raw",
        builder_ref="exifmodern.formats.fujifilm_raw:invoke_fujifilm_raw",
        patterns=(Pattern(0, b"FUJIFILMCCD-RAW "),),
    ),
)
