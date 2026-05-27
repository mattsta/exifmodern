"""WPG image transaction planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.public_payload import (
    oversized_public_payload_graph,
    read_public_document_payload,
)
from exifmodern.formats.wpg.image_transaction_plan import (
    WpgImageTransactionPlan,
    WpgRewriteRequest,
    build_wpg_image_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = (
    "WpgImageTransactionPlan",
    "WpgRewriteRequest",
    "build_wpg_image_transaction_plan",
    "build_wpg_read_graph",
    "invoke_wpg",
)


_WPG_TABLE = "Image::ExifTool::WPG::Main"
_FILE_TABLE = "Image::ExifTool::File"


def build_wpg_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a WPG image transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_wpg_image_transaction_plan(data)
    diagnostics = [
        f"WPG package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"WPG package-local reader status: {plan.status}")

    tags: list[ReadTag] = []
    header = plan.header_validation
    if plan.status == "planned":
        for name, value in (
            ("FileType", "WPG"),
            ("FileTypeExtension", "wpg"),
            ("MIMEType", "image/x-wpg"),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_provenance(
                        group="File",
                        table_name=_FILE_TABLE,
                        tag_id=name,
                        evidence_ids=header.evidence_ids,
                    ),
                    schema=None,
                )
            )
    header_scalars: tuple[tuple[str, int | float | None], ...] = (
        ("WPGVersion", None if header.version is None else float(header.version)),
    )
    for name, header_value in header_scalars:
        if header_value is None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(header_value),
                provenance=_provenance(
                    group="File",
                    table_name=_WPG_TABLE,
                    tag_id=name,
                    evidence_ids=header.evidence_ids,
                ),
                schema=None,
            )
        )
    dimensions = plan.dimensions
    dim_scalars: tuple[tuple[str, int | float | None], ...] = (
        (
            "ImageWidthInches",
            None if dimensions.width_inches is None else round(dimensions.width_inches, 2),
        ),
        (
            "ImageHeightInches",
            None if dimensions.height_inches is None else round(dimensions.height_inches, 2),
        ),
    )
    for name, dimension_value in dim_scalars:
        if dimension_value is None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(dimension_value),
                provenance=_provenance(
                    group="File",
                    table_name=_WPG_TABLE,
                    tag_id=name,
                    evidence_ids=dimensions.evidence_ids,
                ),
                schema=None,
            )
        )
    if plan.collapsed_records:
        tags.append(
            ReadTag(
                name=header.record_table or "Records",
                value=[
                    _render_wpg_record(collapsed.display_value)
                    for collapsed in plan.collapsed_records
                ],
                provenance=_provenance(
                    group="File",
                    table_name=_WPG_TABLE,
                    tag_id=header.record_table or "Records",
                    evidence_ids=plan.collapsed_records[0].evidence_ids,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _render_wpg_record(value: str) -> str:
    return (
        value.replace(" Type 1", " (Type 1)")
        .replace(" Type 2", " (Type 2)")
        .replace(" Type 3", " (Type 3)")
    )


def invoke_wpg(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = read_public_document_payload(path)
    if data is None:
        return oversized_public_payload_graph(source_file, format_name="WPG")
    return build_wpg_read_graph(data, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="wpg",
        builder_ref="exifmodern.formats.wpg:invoke_wpg",
        patterns=(Pattern(0, b"\xffWPC"),),
    ),
)
