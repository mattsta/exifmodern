"""Reusable XMP packet parsing."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.public_payload import (
    oversized_public_payload_graph,
    read_public_document_payload,
)
from exifmodern.json_types import JsonValue
from exifmodern.signature_trie.signature import Pattern, PreprocessKind, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = (
    "build_xmp_read_graph",
    "invoke_xmp",
    "is_xmp_payload",
)


_XMP_TABLE = "Image::ExifTool::XMP::Main"
_XMP_EXTENSIONS = (".xmp",)


def is_xmp_payload(prefix: bytes, path: Path) -> bool:
    """Structural validator the dispatcher runs after a tentative match.

    The XMP signature is a loose `<` prefix that collides with HTML,
    SVG, plist, and arbitrary XML. This predicate confirms the payload
    actually contains an XMP packet wrapper (`<x:xmpmeta`) or the
    XMP packet processing instruction (`<?xpacket`). Mirrors the
    `is_html_payload` pattern in `exifmodern.formats.html`.
    """

    if path.suffix.lower() in _XMP_EXTENSIONS:
        return True
    head = prefix[:4096]
    return b"<x:xmpmeta" in head or b"<?xpacket" in head


def _xmp_value_to_string(value: JsonValue) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        rendered: list[str] = []
        for item in value:
            text = _xmp_value_to_string(item)
            if text is not None:
                rendered.append(text)
        return ", ".join(rendered) if rendered else None
    if isinstance(value, dict):
        return str(value)
    return str(value)


def build_xmp_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate an XMP packet into a ReadGraph by walking the parsed
    `dict[XmpGroup, JsonObject]` returned by `parse_xmp_packet`.
    """
    from exifmodern.dispatch_helpers import (
        _family_2_group,
        _graph,
        _read_value,
        _source_reference_text,
    )
    from exifmodern.formats.xmp.reader import parse_xmp_packet
    from exifmodern.read_graph import ReadTag, TagProvenance
    from exifmodern.write_plan import EvidenceAnchor

    diagnostics: list[str] = []
    try:
        values_by_group = parse_xmp_packet(data)
    except Exception as error:
        diagnostics.append(f"XMP package-local reader error: {type(error).__name__}: {error}")
        return _graph(source_file, [], diagnostics)

    source_reference = EvidenceAnchor(
        path="lib/Image/ExifTool/XMP.pm",
        line_start=1,
        line_end=1,
        symbol="parse_xmp_packet",
        evidence="XMP packet parsed via exifmodern.formats.xmp.reader.parse_xmp_packet.",
    )

    tags: list[ReadTag] = []
    for group, properties in values_by_group.items():
        if not isinstance(properties, dict):
            continue
        for index, (tag_name, raw_value) in enumerate(properties.items()):
            text = _xmp_value_to_string(raw_value)
            if text is None:
                continue
            tags.append(
                ReadTag(
                    name=tag_name,
                    value=_read_value(text),
                    provenance=TagProvenance(
                        group=group,
                        table_name=_XMP_TABLE,
                        tag_id=tag_name,
                        source=_source_reference_text((source_reference,)),
                        family_0_group=group,
                        family_1_group=group,
                        family_2_group=_family_2_group(group),
                        duplicate_instance_ordinal=index,
                    ),
                    schema=None,
                )
            )
    return _graph(source_file, tags, diagnostics)


def invoke_xmp(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = read_public_document_payload(path)
    if data is None:
        return oversized_public_payload_graph(source_file, format_name="XMP")
    return build_xmp_read_graph(data, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="xmp",
        builder_ref="exifmodern.formats.xmp:invoke_xmp",
        patterns=(Pattern(0, b"<"),),
        preprocess=PreprocessKind.LSTRIP_WHITESPACE_AND_BOM,
        structural_check="exifmodern.formats.xmp:is_xmp_payload",
        notes=("loose; structural check confirms actual XMP packet wrapper",),
    ),
    Signature(
        format_id="xmp/by-ext",
        builder_ref="exifmodern.formats.xmp:invoke_xmp",
        patterns=(),
        extensions=_XMP_EXTENSIONS,
        structural_check="exifmodern.formats.xmp:is_xmp_payload",
    ),
)
