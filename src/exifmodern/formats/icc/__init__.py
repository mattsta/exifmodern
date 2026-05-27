"""ICC profile readers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.icc.materializer import materialize_source_icc_profile
from exifmodern.formats.icc.reader import (
    ICC_HEADER_GROUP_NAME,
    ICC_HEADER_TABLE_NAME,
    ICC_MAIN_GROUP_NAME,
    ICC_MAIN_TABLE_NAME,
    icc_group_name_for_tag,
    icc_table_name_for_tag,
    icc_tag_id_for_tag,
    parse_icc_header_tags,
    parse_icc_profile_tags,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.json_types import JsonValue
    from exifmodern.read_graph import ReadGraph, TagValue

__all__ = [
    "ICC_HEADER_GROUP_NAME",
    "ICC_HEADER_TABLE_NAME",
    "ICC_MAIN_GROUP_NAME",
    "ICC_MAIN_TABLE_NAME",
    "build_icc_read_graph",
    "icc_group_name_for_tag",
    "icc_table_name_for_tag",
    "icc_tag_id_for_tag",
    "invoke_icc",
    "materialize_source_icc_profile",
    "parse_icc_header_tags",
    "parse_icc_profile_tags",
]


def build_icc_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance
    from exifmodern.read_graph import ReadTag

    diagnostics: list[str] = []
    tags: list[ReadTag] = [
        ReadTag(
            name="FileType",
            value="ICC",
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id="FileType",
                evidence_ids=(),
            ),
            schema=None,
        ),
        ReadTag(
            name="FileTypeExtension",
            value="icc",
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id="FileTypeExtension",
                evidence_ids=(),
            ),
            schema=None,
        ),
        ReadTag(
            name="MIMEType",
            value="application/vnd.iccprofile",
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id="MIMEType",
                evidence_ids=(),
            ),
            schema=None,
        ),
    ]
    try:
        parsed = {
            **parse_icc_header_tags(data, strict_declared_length=True),
            **parse_icc_profile_tags(data, strict_declared_length=True),
        }
    except ValueError as exc:
        diagnostics.append(f"ICC package-local reader error: {exc}")
        return _graph(source_file, tags, diagnostics)

    for ordinal, (name, value) in enumerate(parsed.items()):
        tags.append(
            ReadTag(
                name=name,
                value=icc_read_value(value),
                provenance=_provenance(
                    group=icc_group_name_for_tag(name),
                    table_name=icc_table_name_for_tag(name),
                    tag_id=icc_tag_id_for_tag(name),
                    evidence_ids=(),
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def icc_read_value(value: JsonValue) -> TagValue:
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return str(value)
            strings.append(item)
        return strings
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def invoke_icc(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_icc_read_graph(_read_icc_profile_exiftool_payload(path), source_file)


def _read_icc_profile_exiftool_payload(path: Path) -> bytes:
    """Read ICC bytes using ExifTool's 24-byte gate and declared profile size."""
    with path.open("rb") as file:
        header = file.read(24)
        if len(header) < 24:
            return header
        declared_size = int.from_bytes(header[:4], "big")
        if declared_size < 128 or declared_size & 0x80000000:
            return header
        file.seek(0)
        return file.read(declared_size)


_ICC_BUILDER = "exifmodern.formats.icc:invoke_icc"

SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="icc/mntr-rgb-xyz",
        builder_ref=_ICC_BUILDER,
        patterns=(Pattern(12, b"mntr"), Pattern(16, b"RGB "), Pattern(20, b"XYZ ")),
    ),
    Signature(
        format_id="icc/scnr-rgb-xyz",
        builder_ref=_ICC_BUILDER,
        patterns=(Pattern(12, b"scnr"), Pattern(16, b"RGB "), Pattern(20, b"XYZ ")),
    ),
    Signature(
        format_id="icc/prtr-cmyk-lab",
        builder_ref=_ICC_BUILDER,
        patterns=(Pattern(12, b"prtr"), Pattern(16, b"CMYK"), Pattern(20, b"Lab ")),
    ),
    Signature(
        format_id="icc/link-rgb-xyz",
        builder_ref=_ICC_BUILDER,
        patterns=(Pattern(12, b"link"), Pattern(16, b"RGB "), Pattern(20, b"XYZ ")),
    ),
)
