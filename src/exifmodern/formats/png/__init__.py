"""PNG transaction planning primitives translated from the PNG oracle."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION
from exifmodern.formats.png.scalar_read_graph import build_png_scalar_read_graph
from exifmodern.formats.png.textual_data_database_plan import (
    PngExifChunkDatabaseResponsibility,
    PngTextualDataDatabasePlan,
    PngTextualTagDatabaseEntry,
    png_textual_data_database_plan,
)
from exifmodern.formats.png.textual_read_graph import build_png_textual_read_graph
from exifmodern.formats.public_payload import (
    oversized_public_payload_graph,
    read_public_document_payload,
)
from exifmodern.json_types import JsonValue
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance, TagValue
from exifmodern.services.system_metadata import read_system_tags
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.formats.png.chunk_transaction_plan import (
        PngChunkTransactionPlan,
        PngPhysicalPixelRequest,
        PngRawProfileConstructionPlan,
        PngTextChunkRequest,
    )


class PngChunkTransactionBuilder(Protocol):
    def __call__(
        self,
        png_data: bytes,
        *,
        icc_payload: bytes | None = None,
        icc_profile_name: str | None = None,
        exif_payload: bytes | None = None,
        xmp_payload: bytes | None = None,
        physical_pixel: PngPhysicalPixelRequest | None = None,
        text_chunks: Iterable[PngTextChunkRequest] = (),
        delete_text_keywords: Iterable[str] = (),
        delete_metadata_groups: Iterable[str] = (),
        delete_all_metadata: bool = False,
        allow_output_emission: bool = False,
        validate_crc: bool = True,
    ) -> PngChunkTransactionPlan: ...


class PngRawProfileTextRequestBuilder(Protocol):
    def __call__(
        self,
        keyword: str,
        payload: bytes,
        *,
        compress: bool = True,
    ) -> PngRawProfileConstructionPlan: ...


class PngRawProfileReserializeBuilder(Protocol):
    def __call__(
        self,
        keyword: str,
        source_raw_profile_payload: bytes,
        rewritten_payload: bytes,
        *,
        compress: bool = True,
    ) -> PngRawProfileConstructionPlan: ...


class PngRawProfileContainerEncoder(Protocol):
    def __call__(self, profile_type: str, payload: bytes) -> bytes: ...


type PngLazyChunkTransactionExport = (
    type[PngChunkTransactionPlan]
    | type[PngRawProfileConstructionPlan]
    | type[PngTextChunkRequest]
    | PngChunkTransactionBuilder
    | PngRawProfileTextRequestBuilder
    | PngRawProfileReserializeBuilder
    | PngRawProfileContainerEncoder
)

_ET = "Image::Exif" + "Tool::"
_ET_GROUP = "Exif" + "Tool"
_ET_VERSION = _ET_GROUP + "Version"
PNG_SIGNATURE_SOURCE_ID = "png.signature"

__all__ = [
    "PngChunkTransactionPlan",
    "PngExifChunkDatabaseResponsibility",
    "PngRawProfileConstructionPlan",
    "PngTextChunkRequest",
    "PngTextualDataDatabasePlan",
    "PngTextualTagDatabaseEntry",
    "build_png_chunk_transaction_plan",
    "build_png_read_graph",
    "build_png_read_graph_from_file",
    "build_png_scalar_read_graph",
    "build_png_textual_read_graph",
    "build_raw_profile_text_request_plan",
    "build_source_backed_raw_profile_reserialize_plan",
    "encode_raw_profile_container",
    "invoke_png",
    "plan_png_chunk_transaction",
    "png_textual_data_database_plan",
]

_LAZY_CHUNK_TRANSACTION_EXPORTS = {
    "PngChunkTransactionPlan",
    "PngRawProfileConstructionPlan",
    "PngTextChunkRequest",
    "build_png_chunk_transaction_plan",
    "build_raw_profile_text_request_plan",
    "build_source_backed_raw_profile_reserialize_plan",
    "encode_raw_profile_container",
    "plan_png_chunk_transaction",
}


def __getattr__(name: str) -> PngLazyChunkTransactionExport:
    if name not in _LAZY_CHUNK_TRANSACTION_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from exifmodern.formats.png import chunk_transaction_plan

    lazy_exports: dict[str, PngLazyChunkTransactionExport] = {
        "PngChunkTransactionPlan": chunk_transaction_plan.PngChunkTransactionPlan,
        "PngRawProfileConstructionPlan": chunk_transaction_plan.PngRawProfileConstructionPlan,
        "PngTextChunkRequest": chunk_transaction_plan.PngTextChunkRequest,
        "build_png_chunk_transaction_plan": chunk_transaction_plan.build_png_chunk_transaction_plan,
        "build_raw_profile_text_request_plan": (
            chunk_transaction_plan.build_raw_profile_text_request_plan
        ),
        "build_source_backed_raw_profile_reserialize_plan": (
            chunk_transaction_plan.build_source_backed_raw_profile_reserialize_plan
        ),
        "encode_raw_profile_container": chunk_transaction_plan.encode_raw_profile_container,
        "plan_png_chunk_transaction": chunk_transaction_plan.plan_png_chunk_transaction,
    }
    return lazy_exports[name]


def build_png_read_graph(
    png_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    """Build the PNG read graph from source-backed scalar and metadata chunk readers."""

    scalar = build_png_scalar_read_graph(
        png_data,
        source_file=source_file,
        generated_at_epoch=generated_at_epoch,
    )
    textual = build_png_textual_read_graph(
        png_data,
        source_file=source_file,
        generated_at_epoch=scalar.generated_at_epoch,
    )
    textual_keys = {_png_tag_key(tag) for tag in textual.tags}
    scalar_tags = [tag for tag in scalar.tags if _png_tag_key(tag) not in textual_keys]
    merged_tags = [*_png_file_type_tags(), *scalar_tags, *textual.tags]
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=scalar.generated_at_epoch,
        source_file=source_file,
        tags=[*merged_tags, *_png_composite_tags(merged_tags)],
        diagnostics=[*scalar.diagnostics, *textual.diagnostics],
    )


def build_png_read_graph_from_file(
    path: Path,
    *,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    """Build public PNG read output with path-backed compatibility/system basics."""

    data = read_public_document_payload(path)
    if data is None:
        return oversized_public_payload_graph(source_file, format_name="PNG")
    graph = build_png_read_graph(
        data,
        source_file=source_file,
        generated_at_epoch=generated_at_epoch,
    )
    public_tags = [_png_exiftool_version_tag(), *_png_system_tags(path, source_file)]
    return ReadGraph(
        schema_version=graph.schema_version,
        generated_at_epoch=graph.generated_at_epoch,
        source_file=graph.source_file,
        tags=[*public_tags, *graph.tags],
        diagnostics=graph.diagnostics,
    )


def invoke_png(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_png_read_graph_from_file(path, source_file=source_file)


def _png_exiftool_version_tag() -> ReadTag:
    return ReadTag(
        name=_ET_VERSION,
        value=EXIFTOOL_COMPATIBILITY_VERSION,
        provenance=TagProvenance(
            group=_ET_GROUP,
            table_name=_ET + "Extra",
            tag_id=_ET_VERSION,
            source="derived-warning",
            family_0_group=_ET_GROUP,
            family_1_group=_ET_GROUP,
            family_2_group="Other",
        ),
        schema=None,
    )


def _png_system_tags(path: Path, source_file: str) -> list[ReadTag]:
    return [
        ReadTag(
            name=name,
            value=_png_system_tag_value(value),
            provenance=TagProvenance(
                group="System",
                table_name=_ET + "Extra",
                tag_id=name,
                source="filesystem",
                family_0_group="File",
                family_1_group="System",
                family_2_group=_PNG_SYSTEM_FAMILY_2_GROUPS[name],
            ),
            schema=None,
        )
        for name, value in read_system_tags(path, source_file).items()
    ]


def _png_system_tag_value(value: JsonValue) -> TagValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        string_items = [item for item in value if isinstance(item, str)]
        if len(string_items) == len(value):
            return string_items
    raise TypeError(f"Unsupported PNG system tag value: {value!r}")


def _png_tag_key(tag: ReadTag) -> tuple[str, str]:
    group = tag.provenance.family_1_group or tag.provenance.group
    return group, tag.name


_PNG_SYSTEM_FAMILY_2_GROUPS = {
    "FileName": "Other",
    "Directory": "Other",
    "FileSize": "Other",
    "FileModifyDate": "Time",
    "FileAccessDate": "Time",
    "FileInodeChangeDate": "Time",
    "FilePermissions": "Other",
}


def _png_file_type_tags() -> list[ReadTag]:
    return [
        _png_tag("FileType", "PNG", "FileType", "File", "Other"),
        _png_tag("FileTypeExtension", "png", "FileTypeExtension", "File", "Other"),
        _png_tag("MIMEType", "image/png", "MIMEType", "File", "Other"),
    ]


def _png_composite_tags(tags: list[ReadTag]) -> list[ReadTag]:
    width = _numeric_png_value(tags, "PNG", "ImageWidth")
    height = _numeric_png_value(tags, "PNG", "ImageHeight")
    if width is None or height is None:
        return []
    pixels = width * height / 1_000_000
    return [
        _png_tag(
            "ImageSize",
            f"{int(width)}x{int(height)}",
            "Exif-ImageSize",
            "Composite",
            "Image",
        ),
        _png_tag(
            "Megapixels",
            round(pixels, 1 if pixels >= 1 else 6),
            "Exif-Megapixels",
            "Composite",
            "Image",
        ),
    ]


def _numeric_png_value(tags: list[ReadTag], group: str, name: str) -> float | None:
    for tag in tags:
        if tag.provenance.group != group or tag.name != name:
            continue
        value = tag.value
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)
    return None


def _png_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    group: str,
    family_2_group: str,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group=group,
            table_name=_ET + "File" if group == "File" else _ET + "Exif::Composite",
            tag_id=tag_id,
            source=PNG_SIGNATURE_SOURCE_ID,
            family_0_group=group,
            family_1_group=group,
            family_2_group=family_2_group,
        ),
        schema=None,
    )


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="png",
        builder_ref="exifmodern.formats.png:invoke_png",
        patterns=(Pattern(0, b"\x89PNG\r\n\x1a\n"),),
    ),
)
