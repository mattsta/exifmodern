"""Adobe InDesign metadata transaction planning."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.indesign.metadata_transaction_plan import (
    INDESIGN_SIGNATURE_EVIDENCE_ID,
    InDesignMetadataTransactionPlan,
    build_indesign_metadata_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance

_INDESIGN_PUBLIC_READ_LIMIT = 64 * 1024 * 1024

__all__ = (
    "InDesignMetadataTransactionPlan",
    "build_indesign_metadata_transaction_plan",
    "build_indesign_read_graph",
    "invoke_indesign",
)


def build_indesign_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.formats.xmp import build_xmp_read_graph
    from exifmodern.read_graph import ReadTag, TagProvenance

    plan = build_indesign_metadata_transaction_plan(data, allow_output_emission=True)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"InDesign package-local reader status: {plan.status}")
    diagnostics.extend(
        f"InDesign package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = []
    if plan.header is not None:
        tags.extend(
            (
                ReadTag(
                    name="FileType",
                    value=_read_value(plan.header.file_type),
                    provenance=_provenance(
                        group="File",
                        table_name="Image::ExifTool::File",
                        tag_id="FileType",
                        evidence_ids=(INDESIGN_SIGNATURE_EVIDENCE_ID,),
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="FileTypeExtension",
                    value=_read_value(plan.header.file_type.lower()),
                    provenance=_provenance(
                        group="File",
                        table_name="Image::ExifTool::File",
                        tag_id="FileTypeExtension",
                        evidence_ids=(INDESIGN_SIGNATURE_EVIDENCE_ID,),
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="MIMEType",
                    value=_read_value(
                        "application/x-indesign"
                        if plan.header.file_type == "INDD"
                        else "application/octet-stream"
                    ),
                    provenance=_provenance(
                        group="File",
                        table_name="Image::ExifTool::File",
                        tag_id="MIMEType",
                        evidence_ids=(INDESIGN_SIGNATURE_EVIDENCE_ID,),
                    ),
                    schema=None,
                ),
            )
        )
    for stream in plan.streams:
        if stream.metadata_kind == "xmp" and stream.xmp_payload is not None:
            xmp_length = stream.xmp_effective_length or len(stream.xmp_payload)
            xmp_graph = build_xmp_read_graph(stream.xmp_payload[:xmp_length], source_file)
            diagnostics.extend(xmp_graph.diagnostics)
            tags.extend(_indesign_xmp_tags(xmp_graph.tags, TagProvenance))
    return _graph(source_file, tags, diagnostics)


def _indesign_xmp_tags(
    tags: list[ReadTag],
    provenance_type: type[TagProvenance],
) -> list[ReadTag]:
    normalized: list[ReadTag] = []
    for tag in tags:
        if tag.provenance.family_1_group == "XMP-dc" and tag.name == "format":
            provenance = tag.provenance
            normalized.append(
                replace(
                    tag,
                    name="Format",
                    provenance=provenance_type(
                        provenance.group,
                        provenance.table_name,
                        "Format",
                        provenance.source,
                        family_0_group=provenance.family_0_group,
                        family_1_group=provenance.family_1_group,
                        family_2_group=provenance.family_2_group,
                        family_4_instance_group=provenance.family_4_instance_group,
                        duplicate_instance_ordinal=provenance.duplicate_instance_ordinal,
                    ),
                )
            )
            continue
        normalized.append(tag)
    return sorted(normalized, key=_indesign_xmp_sort_key)


def _indesign_xmp_sort_key(tag: ReadTag) -> tuple[int, str]:
    group = tag.provenance.family_1_group or tag.provenance.group
    if group == "XMP-x" and tag.name == "XMPToolkit":
        return (0, tag.name)
    if group == "XMP-rdf" and tag.name == "About":
        return (1, tag.name)
    if group == "XMP-xmp":
        return (2, tag.name)
    if group == "XMP-xmpMM":
        return (3, tag.name)
    if group == "XMP-dc" and tag.name == "Format":
        return (4, tag.name)
    return (5, tag.name)


def invoke_indesign(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_indesign_public_probe(path)
    return build_indesign_read_graph(data, source_file)


def _read_indesign_public_probe(path: Path) -> bytes:
    # InDesign.pm scans master pages and contiguous streams; XMP itself is capped there.
    with path.open("rb") as file:
        return file.read(_INDESIGN_PUBLIC_READ_LIMIT)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="indesign",
        builder_ref="exifmodern.formats.indesign:invoke_indesign",
        patterns=(
            Pattern(
                0,
                b"\x06\x06\xed\xf5\xd8\x1d\x46\xe5\xbd\x31\xef\xe7\xfe\x74\xb7\x1d",
            ),
        ),
    ),
)
