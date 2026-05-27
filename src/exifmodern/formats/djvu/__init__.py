"""DjVu planning helpers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.djvu.metadata_transaction_plan import (
    DJVU_CHUNK_ENUMERATION_SOURCE,
    DJVU_CHUNK_HEADER_SIZE,
    FORM_CHUNK_ID,
    DjvuChunkPlan,
    DjvuMetadataRequest,
    DjvuMetadataRoutePlan,
    DjvuMetadataTransactionPlan,
    DjvuOutputChunk,
    build_djvu_metadata_transaction_plan,
    encode_djvu_chunks,
    route_existing_chunk,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.dispatch_helpers import EvidenceAnchors
    from exifmodern.read_graph import ReadGraph, ReadTag

_DJVU_PUBLIC_READ_LIMIT = 64 * 1024 * 1024

__all__ = [
    "DjvuMetadataRequest",
    "DjvuMetadataTransactionPlan",
    "DjvuOutputChunk",
    "build_djvu_metadata_transaction_plan",
    "build_djvu_read_graph",
    "encode_djvu_chunks",
    "invoke_djvu",
]


def build_djvu_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value, _references
    from exifmodern.formats.xmp import build_xmp_read_graph
    from exifmodern.read_graph import ReadTag

    plan = build_djvu_metadata_transaction_plan(data)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"DjVu package-local reader status: {plan.status}")
    diagnostics.extend(
        f"DjVu package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = []

    def add_tag(
        name: str,
        value: str | int | float,
        group: str,
        table_name: str,
        tag_id: str,
        references: EvidenceAnchors,
        duplicate_instance_ordinal: int | None = None,
    ) -> None:
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group=group,
                    table_name=table_name,
                    tag_id=tag_id,
                    references=references,
                    duplicate_instance_ordinal=duplicate_instance_ordinal,
                ),
                schema=None,
            )
        )

    if plan.header.file_type is not None:
        add_tag(
            "FileType",
            "DJVU (multi-page)" if plan.header.file_type == "DJVM" else "DJVU",
            "File",
            "File",
            "FileType",
            _references(plan.header),
        )
        add_tag(
            "FileTypeExtension",
            "djvu",
            "File",
            "File",
            "FileTypeExtension",
            _references(plan.header),
        )
        add_tag(
            "MIMEType",
            "image/vnd.djvu",
            "File",
            "File",
            "MIMEType",
            _references(plan.header),
        )

    for route in _iter_djvu_routes(plan.chunks):
        if route.extraction_blocker is not None:
            diagnostics.append(
                f"DjVu package-local reader blocker: {route.extraction_blocker}: {route.reason}"
            )
        if route.info is not None:
            info_fields = (
                ("width", "ImageWidth", "0"),
                ("height", "ImageHeight", "2"),
                ("version", "DjVuVersion", "4"),
                ("spatial_resolution", "SpatialResolution", "6"),
                ("gamma", "Gamma", "8"),
                ("orientation", "Orientation", "9"),
            )
            for field, name, tag_id in info_fields:
                value = getattr(route.info, field)
                if field == "orientation" and route.info.orientation_code == 0:
                    value = "Unknown (0)"
                if value is None:
                    continue
                add_tag(
                    name,
                    value,
                    "DjVu",
                    "Image::ExifTool::DjVu::Info",
                    tag_id,
                    _references(route.info),
                    route.chunk_index,
                )
        if route.subfile_type is not None:
            if route.subfile_type == "Shared component":
                continue
            add_tag(
                route.tag_name or "IncludedFileID",
                route.subfile_type,
                "DjVu",
                "Image::ExifTool::DjVu::Form",
                "0" if route.tag_name == "SubfileType" else route.tag_name or "",
                _references(route),
                route.chunk_index,
            )
        if route.annotation is not None:
            for entry in route.annotation.metadata_entries:
                if entry.value is None:
                    continue
                add_tag(
                    _djvu_meta_tag_name(entry.tag_id, entry.dynamic_tag_name),
                    _djvu_meta_value(entry.tag_id, entry.value),
                    "DjVu-Meta",
                    "Image::ExifTool::DjVu::Meta",
                    entry.tag_id,
                    _references(entry),
                    route.chunk_index,
                )
                if entry.tag_id == "note":
                    add_tag(
                        "Notes",
                        entry.value,
                        "XMP-album",
                        "Image::ExifTool::XMP::album",
                        "Notes",
                        _references(entry),
                        route.chunk_index,
                    )
            if route.annotation.xmp_payload is not None:
                xmp_graph = build_xmp_read_graph(
                    route.annotation.xmp_payload.encode("utf-8"), source_file
                )
                tags.extend(_djvu_xmp_tags(xmp_graph.tags))
                diagnostics.extend(
                    f"DjVu nested XMP diagnostic: {diagnostic}"
                    for diagnostic in xmp_graph.diagnostics
                )
                diagnostics.append("nested_metadata_extracted: XMP")
    dimensions = _first_dimensions(tags)
    if dimensions is not None:
        width, height = dimensions
        add_tag(
            "ImageSize",
            f"{width}x{height}",
            "Composite",
            "Image::ExifTool::Composite",
            "Exif-ImageSize",
            _references(plan),
        )
        add_tag(
            "Megapixels",
            round(width * height / 1_000_000, 6),
            "Composite",
            "Image::ExifTool::Composite",
            "Exif-Megapixels",
            _references(plan),
        )
    return _graph(source_file, tags, diagnostics)


def _djvu_xmp_tags(tags: list[ReadTag]) -> list[ReadTag]:
    from exifmodern.read_graph import ReadTag

    nested_tags: list[ReadTag] = []
    for tag in tags:
        if tag.provenance.group == "XMP-rdf" and tag.name == "About":
            continue
        if (
            tag.provenance.group == "XMP-pdf"
            and tag.name == "Trapped"
            and isinstance(tag.value, str)
        ):
            nested_tags.append(
                ReadTag(
                    name=tag.name,
                    value=tag.value.removeprefix("/"),
                    provenance=tag.provenance,
                    schema=tag.schema,
                )
            )
            continue
        if (
            tag.provenance.group == "XMP-dc"
            and tag.name == "Subject"
            and isinstance(tag.value, str)
        ):
            nested_tags.append(
                ReadTag(
                    name=tag.name,
                    value=[part.strip() for part in tag.value.split(",")],
                    provenance=tag.provenance,
                    schema=tag.schema,
                )
            )
            continue
        nested_tags.append(tag)
    return nested_tags


def _djvu_meta_tag_name(tag_id: str, dynamic_tag_name: str | None) -> str:
    return {
        "CreationDate": "CreateDate",
        "ModDate": "ModifyDate",
        "annote": "Annotation",
        "note": "Note",
        "url": "URL",
    }.get(tag_id, dynamic_tag_name or tag_id)


def _djvu_meta_value(tag_id: str, value: str) -> str:
    if tag_id in {"CreationDate", "ModDate"}:
        return _convert_xmp_date(value)
    if tag_id == "Trapped":
        return value.removeprefix("/")
    return value


def _convert_xmp_date(value: str) -> str:
    date, separator, time = value.partition("T")
    if separator != "T":
        return value
    return f"{date.replace('-', ':')} {time}"


def _first_dimensions(tags: list[ReadTag]) -> tuple[int, int] | None:
    width: int | None = None
    height: int | None = None
    for tag in tags:
        if tag.name == "ImageWidth" and isinstance(tag.value, int):
            width = tag.value
        if tag.name == "ImageHeight" and isinstance(tag.value, int):
            height = tag.value
    if width is None or height is None:
        return None
    return width, height


def _iter_djvu_routes(chunks: tuple[DjvuChunkPlan, ...]) -> Iterator[DjvuMetadataRoutePlan]:
    for chunk in chunks:
        route = route_existing_chunk(chunk)
        yield route
        if chunk.chunk_id == FORM_CHUNK_ID and len(chunk.payload) >= 4:
            yield from _iter_djvu_routes(_enumerate_nested_djvu_chunks(chunk))


def _enumerate_nested_djvu_chunks(parent: DjvuChunkPlan) -> tuple[DjvuChunkPlan, ...]:
    chunks: list[DjvuChunkPlan] = []
    offset = 4
    while offset + DJVU_CHUNK_HEADER_SIZE <= len(parent.payload):
        chunk_id = parent.payload[offset : offset + 4]
        payload_length = int.from_bytes(parent.payload[offset + 4 : offset + 8], "big")
        payload_offset = offset + DJVU_CHUNK_HEADER_SIZE
        payload_end = payload_offset + payload_length
        padding_length = payload_length & 1
        padded_end = payload_end + padding_length
        if padded_end > len(parent.payload):
            break
        absolute_chunk_start = parent.payload_offset + offset
        absolute_payload_offset = parent.payload_offset + payload_offset
        chunks.append(
            DjvuChunkPlan(
                parent.index * 1000 + len(chunks) + 1,
                chunk_id,
                absolute_chunk_start,
                absolute_payload_offset,
                payload_length,
                absolute_payload_offset + payload_length,
                padding_length,
                parent.payload[payload_end:padded_end],
                parent.payload_offset + padded_end,
                parent.payload[payload_offset:payload_end],
                (DJVU_CHUNK_ENUMERATION_SOURCE,),
            )
        )
        offset = padded_end
    return tuple(chunks)


def invoke_djvu(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_djvu_public_probe(path)
    return build_djvu_read_graph(data, source_file)


def _read_djvu_public_probe(path: Path) -> bytes:
    # DjVu.pm delegates IFF chunk walking to bounded RAF reads; avoid Path.read_bytes.
    with path.open("rb") as file:
        return file.read(_DJVU_PUBLIC_READ_LIMIT)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="djvu",
        builder_ref="exifmodern.formats.djvu:invoke_djvu",
        patterns=(Pattern(0, b"AT&TFORM"),),
    ),
)
