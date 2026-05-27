"""RTF metadata planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.rtf.metadata_transaction_plan import (
    RtfMetadataWriteRequest,
    build_rtf_metadata_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, PreprocessKind, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = (
    "RtfMetadataWriteRequest",
    "build_rtf_metadata_transaction_plan",
    "build_rtf_read_graph",
    "invoke_rtf",
)


_RTF_TABLE = "Image::ExifTool::RTF::Main"
_RTF_INTEGER_TAGS = frozenset(
    (
        "Characters",
        "CharactersWithSpaces",
        "CustomNumber",
        "InternalIDNumber",
        "InternalVersionNumber",
        "Pages",
        "RevisionNumber",
        "Words",
    )
)
_RTF_METADATA_SCAN_LIMIT = 8 * 1024 * 1024


def build_rtf_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate an RTF metadata transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_rtf_metadata_transaction_plan(data)
    diagnostics = [
        f"RTF package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]

    file_sources = plan.signature_validation.evidence_ids
    tags: list[ReadTag] = [
        ReadTag(
            name="FileType",
            value="RTF",
            provenance=_provenance(
                group="File",
                table_name=_RTF_TABLE,
                tag_id="FileType",
                evidence_ids=file_sources,
            ),
            schema=None,
        ),
        ReadTag(
            name="FileTypeExtension",
            value="rtf",
            provenance=_provenance(
                group="File",
                table_name=_RTF_TABLE,
                tag_id="FileTypeExtension",
                evidence_ids=file_sources,
            ),
            schema=None,
        ),
        ReadTag(
            name="MIMEType",
            value="text/rtf",
            provenance=_provenance(
                group="File",
                table_name=_RTF_TABLE,
                tag_id="MIMEType",
                evidence_ids=file_sources,
            ),
            schema=None,
        ),
    ]
    for index, entry in enumerate(plan.metadata_entries):
        value: str | int = entry.value
        if entry.tag_name in _RTF_INTEGER_TAGS:
            try:
                value = int(entry.value)
            except ValueError:
                value = entry.value
        tags.append(
            ReadTag(
                name=entry.tag_name,
                value=_read_value(value),
                provenance=_provenance(
                    group="RTF",
                    table_name=_RTF_TABLE,
                    tag_id=entry.control_word,
                    evidence_ids=entry.evidence_ids,
                    duplicate_instance_ordinal=index,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_rtf(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_rtf_read_graph(_read_bounded_prefix(path, _RTF_METADATA_SCAN_LIMIT), source_file)


def _read_bounded_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="rtf",
        builder_ref="exifmodern.formats.rtf:invoke_rtf",
        patterns=(Pattern(0, b"{\\rtf"),),
        preprocess=PreprocessKind.LSTRIP_WHITESPACE,
    ),
)


install_evidence_reference_compat(globals())
