"""JPEG Universal Metadata Box Format readers."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = [
    "build_jumbf_read_graph",
    "invoke_jumbf",
]

JUMBF_PUBLIC_READ_LIMIT_BYTES = 64 * 1024 * 1024


def build_jumbf_read_graph(data: bytes, source_file: str) -> ReadGraph:
    # Lazy imports: jumbf is reachable from `read_graph` initialization via
    # formats/jpeg/app_segments/jumbf, so a top-level import of
    # dispatch_helpers (or read_graph) here would be a circular import.
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.formats.jumbf.reader import parse_jumbf_tags
    from exifmodern.read_graph import ReadTag

    diagnostics: list[str] = []
    tags: list[ReadTag] = []
    try:
        parsed = parse_jumbf_tags(data)
    except Exception as exc:  # pragma: no cover - defensive
        diagnostics.append(f"JUMBF package-local reader error: {exc}")
        return _graph(source_file, tags, diagnostics)
    no_refs: tuple[str, ...] = ()
    for ordinal, (name, value) in enumerate(parsed.items()):
        rendered = (
            value if isinstance(value, str | int | float | bool) or value is None else str(value)
        )
        tags.append(
            ReadTag(
                name=str(name),
                value=_read_value(rendered),
                provenance=_provenance(
                    group="JUMBF",
                    table_name="Image::ExifTool::Jpeg2000::JUMBF",
                    tag_id=str(name),
                    evidence_ids=no_refs,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_jumbf(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    size = path.stat().st_size
    read_size = min(size, JUMBF_PUBLIC_READ_LIMIT_BYTES)
    with path.open("rb") as file:
        data = file.read(read_size)
    graph = build_jumbf_read_graph(data, source_file)
    if size > JUMBF_PUBLIC_READ_LIMIT_BYTES:
        graph.diagnostics.append(
            "JUMBF package-local reader warning: metadata payload exceeded bounded read cap"
        )
    return graph


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="jumbf",
        builder_ref="exifmodern.formats.jumbf:invoke_jumbf",
        patterns=(Pattern(4, b"jumb\x00"), Pattern(12, b"jumd")),
    ),
)
