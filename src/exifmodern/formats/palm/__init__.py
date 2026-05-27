"""Palm/PDB metadata planning public API."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.palm.database_transaction_plan import (
    PalmAuxiliaryInfoMutation,
    PalmDatabaseMutationRequest,
    PalmPayloadMutation,
    build_palm_database_transaction_plan,
)
from exifmodern.formats.palm.mobi_exth_plan import (
    MobiExthPlan,
    build_mobi_exth_plan,
)
from exifmodern.formats.palm.reader_plan import (
    PalmReaderDiagnostic,
    PalmReaderPlan,
    PalmReadTag,
    build_palm_reader_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, TagProvenance

_PALM_PUBLIC_READ_LIMIT = 64 * 1024 * 1024

__all__ = (
    "MobiExthPlan",
    "PalmAuxiliaryInfoMutation",
    "PalmDatabaseMutationRequest",
    "PalmPayloadMutation",
    "PalmReadTag",
    "PalmReaderDiagnostic",
    "PalmReaderPlan",
    "build_mobi_exth_plan",
    "build_palm_database_transaction_plan",
    "build_palm_read_graph",
    "build_palm_reader_plan",
    "invoke_palm",
)


def build_palm_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_palm_reader_plan(data)
    diagnostics = [
        f"Palm package-local reader diagnostic: {diagnostic.code}: {diagnostic.detail}"
        for diagnostic in plan.diagnostics
    ]
    tags = [
        ReadTag(
            name=tag.name,
            value=_read_value(tag.value),
            provenance=_palm_provenance(tag),
            schema=None,
        )
        for tag in plan.tags
    ]
    return _graph(source_file, tags, diagnostics)


def _palm_provenance(tag: PalmReadTag) -> TagProvenance:
    from exifmodern.read_graph import TagProvenance

    family_1_group = (
        "MOBI"
        if tag.source_table in {"Image::ExifTool::Palm::MOBI", "Image::ExifTool::Palm::EXTH"}
        else tag.group
    )
    return TagProvenance(
        group=tag.group,
        table_name=tag.source_table,
        tag_id=tag.tag_id,
        source=", ".join(tag.evidence_ids),
        family_0_group=tag.group,
        family_1_group=family_1_group,
        family_2_group=_palm_family_2_group(tag),
    )


def _palm_family_2_group(tag: PalmReadTag) -> str:
    if tag.group == "File":
        return "Other"
    if tag.name in {"CreateDate", "ModifyDate", "LastBackupDate", "PublishDate"}:
        return "Time"
    if tag.name in {"Author", "Rights"}:
        return "Author"
    return "Document"


def invoke_palm(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    data = _read_palm_public_probe(path)
    return build_palm_read_graph(data, source_file)


def _read_palm_public_probe(path: Path) -> bytes:
    # Palm.pm probes the PDB header, then seeks to first MOBI/EXTH records as needed.
    with path.open("rb") as file:
        return file.read(_PALM_PUBLIC_READ_LIMIT)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="palm/mobi",
        builder_ref="exifmodern.formats.palm:invoke_palm",
        patterns=(Pattern(60, b"BOOKMOBI"),),
        extensions=(".mobi", ".azw", ".azw3"),
    ),
)
