"""FlashPix and FPXR metadata support."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.flashpix.reader import (
    CFB_SIGNATURE,
    FLASHPIX_PROCESS_FPX_SOURCE,
    FLASHPIX_PROCESS_PROPERTIES_SOURCE,
    FlashPixOleReadResult,
    FlashPixOleTag,
    read_flashpix_ole_file,
)
from exifmodern.services.system_metadata import read_system_tags
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = [
    "FlashPixOleReadResult",
    "build_flashpix_ole_read_graph",
    "invoke_flashpix",
    "read_flashpix_ole_file",
]


def build_flashpix_ole_read_graph(path: Path, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph
    from exifmodern.json_types import JsonValue
    from exifmodern.read_graph import BinaryTagValue, ReadTag, ScalarTagValue, TagProvenance

    def flashpix_read_value(
        value: JsonValue | bytes,
    ) -> ScalarTagValue | list[ScalarTagValue] | BinaryTagValue:
        if isinstance(value, bytes):
            return BinaryTagValue(value)
        if isinstance(value, str | int | float | bool) or value is None:
            return value
        if isinstance(value, list):
            scalars: list[ScalarTagValue] = []
            for item in value:
                if not isinstance(item, str | int | float | bool) and item is not None:
                    return str(value)
                scalars.append(item)
            return scalars
        return str(value)

    result = read_flashpix_ole_file(path)
    tags = _system_tags(path, source_file)
    tags.extend(
        [
            ReadTag(
                name=name,
                value=value,
                provenance=TagProvenance(
                    group="File",
                    table_name="Image::ExifTool::File",
                    tag_id=name,
                    source=FLASHPIX_PROCESS_FPX_SOURCE,
                    family_0_group="File",
                    family_1_group="File",
                    family_2_group="Other",
                ),
                schema=None,
            )
            for name, value in (
                ("FileType", result.file_type),
                ("FileTypeExtension", result.file_type_extension),
                ("MIMEType", result.mime_type),
            )
        ]
    )
    tags.extend(
        ReadTag(
            name=tag.name,
            value=flashpix_read_value(tag.value),
            provenance=TagProvenance(
                group=tag.group,
                table_name=tag.table_name,
                tag_id=tag.tag_id,
                source=FLASHPIX_PROCESS_PROPERTIES_SOURCE,
                family_0_group=tag.group,
                family_1_group=tag.group,
                family_2_group="Document",
                duplicate_instance_ordinal=tag.duplicate_instance_ordinal,
            ),
            schema=None,
        )
        for tag in exiftool_json_visible_flashpix_tags(result.tags)
    )
    diagnostics = [
        f"FlashPix CFB/OLE package-local reader diagnostic: {diagnostic}"
        for diagnostic in result.diagnostics
    ]
    return _graph(source_file, tags, diagnostics)


def exiftool_json_visible_flashpix_tags(
    tags: tuple[FlashPixOleTag, ...],
) -> tuple[FlashPixOleTag, ...]:
    """Keep the final same-group/name property occurrence for ExifTool JSON parity."""

    final_indices: dict[tuple[str, str], int] = {}
    for index, tag in enumerate(tags):
        final_indices[(tag.group, tag.name)] = index
    return tuple(
        tag for index, tag in enumerate(tags) if final_indices[(tag.group, tag.name)] == index
    )


def _system_tags(path: Path, source_file: str) -> list[ReadTag]:
    from exifmodern.read_graph import ReadTag, TagProvenance

    return [
        ReadTag(
            name=name,
            value=value,
            provenance=TagProvenance(
                group="System",
                table_name="Image::ExifTool::Extra",
                tag_id=name,
                source="filesystem",
                family_0_group="File",
                family_1_group="System",
                family_2_group="Other",
            ),
            schema=None,
        )
        for name, value in read_system_tags(path, source_file).items()
        if isinstance(value, str | int | float | bool) or value is None
    ]


def invoke_flashpix(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    if not prefix.startswith(CFB_SIGNATURE):
        raise ValueError("Invalid FlashPix CFB/OLE signature")
    return build_flashpix_ole_read_graph(path, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="flashpix/cfb-ole",
        builder_ref="exifmodern.formats.flashpix:invoke_flashpix",
        patterns=(Pattern(0, CFB_SIGNATURE),),
        weak=True,
        extensions=(
            ".doc",
            ".dot",
            ".fla",
            ".fpx",
            ".pot",
            ".pps",
            ".ppt",
            ".vsd",
            ".xls",
            ".xla",
            ".xlt",
        ),
    ),
)
