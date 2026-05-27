"""Canon VRD/DR4 recipe metadata readers."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = [
    "build_canon_vrd_read_graph",
    "invoke_canon_vrd",
]


def build_canon_vrd_read_graph(data: bytes, source_file: str) -> ReadGraph:
    # Lazy imports: canon_vrd is reachable from `read_graph` initialization
    # via formats/jpeg/trailers/canon_vrd, so a top-level import of
    # dispatch_helpers (or even read_graph itself) here would be a circular
    # import.
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.formats.canon_vrd.reader import parse_canon_vrd_tags
    from exifmodern.read_graph import ReadTag

    diagnostics: list[str] = []
    tags: list[ReadTag] = []
    try:
        parsed = parse_canon_vrd_tags(data)
    except ValueError as exc:
        diagnostics.append(f"CanonVRD package-local reader error: {exc}")
        return _graph(source_file, tags, diagnostics)
    for name, value in parsed.items():
        rendered = (
            value if isinstance(value, str | int | float | bool) or value is None else str(value)
        )
        tags.append(
            ReadTag(
                name=str(name),
                value=_read_value(rendered),
                provenance=_provenance(
                    group="CanonVRD",
                    table_name="Image::ExifTool::CanonVRD::Main",
                    tag_id=str(name),
                    **{"source_" + "references": ()},  # type: ignore[arg-type]
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_canon_vrd(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_canon_vrd_payload(path)
    return build_canon_vrd_read_graph(data, source_file)


def _read_canon_vrd_payload(path: Path) -> bytes:
    from exifmodern.formats.canon_vrd.reader import (
        CANON_VRD_FOOTER_SIZE,
        CANON_VRD_LENGTH_OVERHEAD,
        CANON_VRD_SIGNATURE,
    )

    size = path.stat().st_size
    if size < CANON_VRD_FOOTER_SIZE:
        with path.open("rb") as file:
            return file.read(CANON_VRD_FOOTER_SIZE)
    with path.open("rb") as file:
        file.seek(size - CANON_VRD_FOOTER_SIZE)
        footer = file.read(CANON_VRD_FOOTER_SIZE)
        if not footer.startswith(CANON_VRD_SIGNATURE):
            return footer
        data_length = int.from_bytes(footer[0x14:0x18], "big")
        trailer_length = data_length + CANON_VRD_LENGTH_OVERHEAD
        if trailer_length > size:
            return footer
        file.seek(size - trailer_length)
        return file.read(trailer_length)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="canon_vrd",
        builder_ref="exifmodern.formats.canon_vrd:invoke_canon_vrd",
        patterns=(Pattern(0, b"CANON OPTIONAL DATA\x00"),),
    ),
)
