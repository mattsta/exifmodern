"""NITF-specific metadata readers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.nitf.reader import NITF_APP6_READ_SIZE, parse_nitf_app6_tags
from exifmodern.media_source import FileMediaSource
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = [
    "build_nitf_read_graph",
    "invoke_nitf",
    "parse_nitf_app6_tags",
]


def build_nitf_read_graph(data: bytes, source_file: str) -> ReadGraph:
    # Deferred imports: this module is loaded transitively during
    # `exifmodern.read_graph` initialization (via the JPEG app-segment
    # registry), so importing dispatch_helpers / read_graph at top-level
    # would create a circular import.
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    diagnostics: list[str] = [
        "NITF package-local reader handles APP6-prefixed payloads only; "
        "top-level NITF files yield no tags via this reader.",
    ]
    try:
        parsed = parse_nitf_app6_tags(data)
    except ValueError as error:
        diagnostics.append(f"NITF package-local reader gate: {error}")
        return _graph(source_file, [], diagnostics)
    tags: list[ReadTag] = []
    for ordinal, (name, value) in enumerate(parsed.items()):
        rendered = (
            value if isinstance(value, str | int | float | bool) or value is None else str(value)
        )
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(rendered),
                provenance=_provenance(
                    group="NITF",
                    table_name="Image::ExifTool::NITF::Main",
                    tag_id=name,
                    evidence_ids=(),
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_nitf(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = (
        prefix[:NITF_APP6_READ_SIZE]
        if len(prefix) >= NITF_APP6_READ_SIZE
        else FileMediaSource(path).prefix(NITF_APP6_READ_SIZE)
    )
    return build_nitf_read_graph(data, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="nitf",
        builder_ref="exifmodern.formats.nitf:invoke_nitf",
        patterns=(Pattern(0, b"NITF"),),
        notes=(
            "current reader handles APP6-prefixed payloads, not the top-level NITF file format",
        ),
    ),
)
