"""ITC metadata transaction planning public API."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.itc.metadata_transaction_plan import (
    ITC_IMAGE_DATA_SOURCE,
    ITC_ITEM_TABLE_SOURCE,
    ItcMetadataRewriteRequest,
    ItcMetadataTransactionPlan,
    build_itc_metadata_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

_ITC_PUBLIC_READ_LIMIT = 64 * 1024 * 1024

__all__ = (
    "ItcMetadataRewriteRequest",
    "ItcMetadataTransactionPlan",
    "build_itc_metadata_transaction_plan",
    "build_itc_read_graph",
    "invoke_itc",
)

ITC_ORACLE_FILE_SOURCE = "itc.fixture.file-identity-output"
ITC_ORACLE_COMPOSITE_SOURCE = "itc.fixture.composite-output"


def build_itc_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_itc_metadata_transaction_plan(data)
    diagnostics: list[str] = []
    diagnostics.extend(
        f"ITC package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = []
    if plan.header_validation.is_valid:
        tags.extend(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="File",
                    table_name="Image::ExifTool::File",
                    tag_id=name,
                    references=(ITC_ORACLE_FILE_SOURCE,),
                ),
                schema=None,
            )
            for name, value in (
                ("FileType", "ITC"),
                ("FileTypeExtension", "itc"),
                ("MIMEType", "application/itunes"),
            )
        )
    for entry in plan.metadata_entries:
        rendered = (
            entry.value if isinstance(entry.value, str | int | float | bool) else str(entry.value)
        )
        tags.append(
            ReadTag(
                name=entry.name,
                value=_read_value(rendered),
                provenance=_provenance(
                    group="ITC",
                    table_name="Image::ExifTool::ITC::Main",
                    tag_id=entry.tag_id,
                    references=entry.evidence_ids,
                ),
                schema=None,
            )
        )
    for ordinal, payload in enumerate(
        payload for payload in plan.preserved_payloads if payload.payload_kind == "image_data"
    ):
        tags.append(
            ReadTag(
                name="ImageData",
                value=_read_value(payload.payload),
                provenance=_provenance(
                    group="ITC",
                    table_name="Image::ExifTool::ITC::Main",
                    tag_id="data",
                    references=(ITC_IMAGE_DATA_SOURCE,),
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    dimensions = _itc_dimensions(plan)
    if dimensions is not None:
        width, height = dimensions
        megapixels = round(width * height / 1_000_000, 6)
        tags.extend(
            (
                ReadTag(
                    name="ImageSize",
                    value=_read_value(f"{width}x{height}"),
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="Exif-ImageSize",
                        references=(ITC_ORACLE_COMPOSITE_SOURCE, ITC_ITEM_TABLE_SOURCE),
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="Megapixels",
                    value=_read_value(megapixels),
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="Exif-Megapixels",
                        references=(ITC_ORACLE_COMPOSITE_SOURCE, ITC_ITEM_TABLE_SOURCE),
                    ),
                    schema=None,
                ),
            )
        )
    return _graph(source_file, tags, diagnostics)


def _itc_dimensions(plan: ItcMetadataTransactionPlan) -> tuple[int, int] | None:
    width: int | None = None
    height: int | None = None
    for entry in plan.metadata_entries:
        if entry.name == "ImageWidth" and isinstance(entry.value, int):
            width = entry.value
        elif entry.name == "ImageHeight" and isinstance(entry.value, int):
            height = entry.value
    if width is None or height is None:
        return None
    return width, height


def invoke_itc(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_itc_public_probe(path)
    return build_itc_read_graph(data, source_file)


def _read_itc_public_probe(path: Path) -> bytes:
    # ITC.pm reads block headers/payloads and seeks past unknown data; cap public input.
    with path.open("rb") as file:
        return file.read(_ITC_PUBLIC_READ_LIMIT)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="itc",
        builder_ref="exifmodern.formats.itc:invoke_itc",
        patterns=(Pattern(4, b"itch"),),
    ),
)
