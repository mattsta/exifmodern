"""RED/R3D transaction planning helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.red.metadata_transaction_plan import (
    RedMetadataRewriteRequest,
    RedMetadataTransactionPlan,
    build_red_metadata_transaction_plan,
)
from exifmodern.formats.red.reader import RedReaderResult, read_red_r3d_scalars
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = [
    "RedMetadataRewriteRequest",
    "RedMetadataTransactionPlan",
    "RedReaderResult",
    "build_red_metadata_transaction_plan",
    "build_red_read_graph",
    "invoke_red",
    "read_red_r3d_scalars",
]


def build_red_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate the RED/R3D scalar read result into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag, TagProvenance

    result = read_red_r3d_scalars(data)
    diagnostics = [
        f"RED package-local reader blocker: {blocker.code}: {blocker.reason}"
        for blocker in result.blockers
    ]
    if result.plan.status != "planned":
        diagnostics.insert(0, f"RED package-local reader status: {result.plan.status}")

    tags: list[ReadTag] = []
    if result.plan.status == "planned":
        for name, value, tag_id in (
            ("FileType", "R3D", "FileType"),
            ("FileTypeExtension", "r3d", "FileTypeExtension"),
            ("MIMEType", "video/x-red-r3d", "MIMEType"),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=TagProvenance(
                        group="File",
                        table_name="Image::ExifTool::File",
                        tag_id=tag_id,
                        source="red.header.validation",
                        family_0_group="File",
                        family_1_group="File",
                        family_2_group="Other",
                    ),
                    schema=None,
                )
            )
    for tag in result.tags:
        if tag.name.startswith("UnknownRedTag"):
            continue
        tags.append(
            ReadTag(
                name=tag.name,
                value=_read_value(_red_public_value(tag.name, tag.value)),
                provenance=_provenance(
                    group="Red",
                    table_name=tag.source_table,
                    tag_id=tag.tag_id,
                    references=(),
                ),
                schema=None,
            )
        )
    tags.extend(_red_composite_tags(tags))
    return _graph(source_file, tags, diagnostics)


def _red_public_value(name: str, value: str | int | float) -> str | int | float:
    """Apply Red.pm ValueConv/PrintConv-compatible default rendering."""
    if name in {
        "RedcodeVersion",
        "ColorTemperature",
        "ReelNumber",
        "ISO",
        "FocalLength",
    }:
        return _maybe_int(value)
    if name in {"FrameRate", "OriginalFrameRate", "FNumber"}:
        return _maybe_float(value)
    if name == "FocusDistance":
        return f"{_maybe_float(value)} m"
    return value


def _maybe_int(value: str | int | float) -> int | str | float:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    try:
        return int(value)
    except ValueError:
        return value


def _maybe_float(value: str | int | float) -> float | int | str:
    if isinstance(value, int | float):
        return value
    try:
        return float(value)
    except ValueError:
        return value


def _red_composite_tags(tags: list[ReadTag]) -> list[ReadTag]:
    values = {tag.name: tag.value for tag in tags if tag.provenance.group == "Red"}
    composites: list[ReadTag] = []
    f_number = values.get("FNumber")
    if isinstance(f_number, int | float):
        composites.append(_red_composite_tag("Aperture", f_number))
    if isinstance(values.get("DateCreated"), str) and isinstance(values.get("TimeCreated"), str):
        composites.append(
            _red_composite_tag(
                "DateTimeOriginal",
                f"{values['DateCreated']} {values['TimeCreated']}",
            )
        )
    width = values.get("ImageWidth")
    height = values.get("ImageHeight")
    if isinstance(width, int) and isinstance(height, int):
        composites.append(_red_composite_tag("ImageSize", f"{width}x{height}"))
        composites.append(_red_composite_tag("Megapixels", round(width * height / 1_000_000, 1)))
    focal_length = values.get("FocalLength")
    if isinstance(focal_length, int | float):
        composites.append(_red_composite_tag("FocalLength35efl", f"{float(focal_length):.1f} mm"))
    return composites


def _red_composite_tag(name: str, value: str | int | float) -> ReadTag:
    from exifmodern.dispatch_helpers import _read_value
    from exifmodern.read_graph import ReadTag, TagProvenance

    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=TagProvenance(
            group="Composite",
            table_name="Image::ExifTool::Composite",
            tag_id=f"Red-{name}",
            source="red.composite.default_tags",
            family_0_group="Composite",
            family_1_group="Composite",
            family_2_group="Other",
        ),
        schema=None,
    )


def invoke_red(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_red_read_graph(_read_red_exiftool_metadata_window(path), source_file)


def _read_red_exiftool_metadata_window(path: Path) -> bytes:
    """Read the R3D first block, plus ExifTool's RED1 directory window."""
    with path.open("rb") as file:
        header = file.read(8)
        if len(header) < 8:
            return header
        first_block_size = int.from_bytes(header[:4], "big")
        if first_block_size < 8:
            return header
        first_block_payload = file.read(first_block_size - 8)
        data = header + first_block_payload
        if header[4:8] == b"RED1" and len(first_block_payload) == first_block_size - 8:
            data += file.read(0x10000)
        return data


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="red/red1",
        builder_ref="exifmodern.formats.red:invoke_red",
        patterns=(Pattern(0, b"\x00\x00"), Pattern(4, b"RED1")),
        weak=True,
        extensions=(".r3d",),
    ),
    Signature(
        format_id="red/red2",
        builder_ref="exifmodern.formats.red:invoke_red",
        patterns=(Pattern(0, b"\x00\x00"), Pattern(4, b"RED2")),
        weak=True,
        extensions=(".r3d",),
    ),
)
