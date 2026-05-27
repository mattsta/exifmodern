"""Portable FloatMap reader public API."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.pfm.reader_plan import (
    PfmDiagnostic,
    PfmReaderPlan,
    PfmReadTag,
    build_pfm_reader_plan,
)
from exifmodern.media_source import FileMediaSource
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = (
    "PfmDiagnostic",
    "PfmReadTag",
    "PfmReaderPlan",
    "build_pfm_read_graph",
    "build_pfm_reader_plan",
    "invoke_pfm",
)

PFM_HEADER_PROBE_BYTES = 256


def build_pfm_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_pfm_reader_plan(data)
    diagnostics = [
        f"PFM package-local reader diagnostic: {diagnostic.code}: {diagnostic.detail}"
        for diagnostic in plan.diagnostics
    ]
    tags = [
        ReadTag(
            name=tag.name,
            value=_read_value(tag.value),
            provenance=_provenance(
                group=tag.group,
                table_name=tag.source_table,
                tag_id=tag.tag_id,
                evidence_ids=tag.evidence_ids,
            ),
            schema=None,
        )
        for tag in plan.tags
    ]
    return _graph(source_file, tags, diagnostics)


def invoke_pfm(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    data = (
        prefix[:PFM_HEADER_PROBE_BYTES]
        if len(prefix) >= PFM_HEADER_PROBE_BYTES
        else FileMediaSource(path).prefix(PFM_HEADER_PROBE_BYTES)
    )
    return build_pfm_read_graph(data, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="pfm/rgb",
        builder_ref="exifmodern.formats.pfm:invoke_pfm",
        patterns=(Pattern(0, b"PF\n"),),
        extensions=(".pfm",),
    ),
    Signature(
        format_id="pfm/mono",
        builder_ref="exifmodern.formats.pfm:invoke_pfm",
        patterns=(Pattern(0, b"Pf\n"),),
        extensions=(".pfm",),
    ),
)
