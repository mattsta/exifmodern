"""MOI metadata transaction planning public API."""

from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.moi.metadata_transaction_plan import (
    MOI_EXIFTOOL_READ_SIZE,
    MoiMetadataTransactionPlan,
    MoiRewriteRequest,
    build_moi_metadata_transaction_plan,
)
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "MoiMetadataTransactionPlan",
    "MoiRewriteRequest",
    "build_moi_metadata_transaction_plan",
    "build_moi_read_graph",
    "invoke_moi",
)


def build_moi_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_moi_metadata_transaction_plan(data)
    return _moi_read_graph_from_plan(plan, source_file)


def _moi_tag(
    name: str,
    value: str | int | float,
    group: str,
    tag_id: str,
    evidence_ids: tuple[str, ...],
    *,
    duplicate_instance_ordinal: int | None = None,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group=group,
            table_name=(
                "Image::ExifTool::MOI::Main" if group == "MOI" else "Image::ExifTool::File"
            ),
            tag_id=tag_id,
            evidence_ids=evidence_ids,
            duplicate_instance_ordinal=duplicate_instance_ordinal,
        ),
        schema=None,
    )


def _moi_print_value(name: str, value: str | int | float) -> str | int | float:
    if name == "Duration" and isinstance(value, int | float):
        return f"{value:g} s"
    if name == "AudioBitrate" and isinstance(value, int | float):
        return f"{value / 1000:g} kbps"
    if name == "VideoBitrate" and isinstance(value, int | float):
        return f"{value / 1_000_000:g} Mbps"
    return value


def invoke_moi(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_moi_exiftool_probe(path, prefix)
    plan = build_moi_metadata_transaction_plan(data, actual_file_size=path.stat().st_size)
    return _moi_read_graph_from_plan(plan, source_file)


def _moi_read_graph_from_plan(plan: MoiMetadataTransactionPlan, source_file: str) -> ReadGraph:
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"MOI package-local reader status: {plan.status}")
    diagnostics.extend(
        f"MOI package-local reader gate: {gate.code}" for gate in plan.output_emission_gates
    )
    diagnostics.extend(
        f"MOI package-local reader blocker: {blocker.code}" for blocker in plan.blockers
    )
    tags: list[ReadTag] = [
        _moi_tag("FileType", "MOI", "File", "FileType", plan.evidence_ids),
        _moi_tag(
            "FileTypeExtension",
            "moi",
            "File",
            "FileTypeExtension",
            plan.evidence_ids,
        ),
        _moi_tag(
            "MIMEType",
            "application/octet-stream",
            "File",
            "MIMEType",
            plan.evidence_ids,
        ),
    ]
    for ordinal, field in enumerate(plan.fields):
        if field.name == "MOIFileSize":
            continue
        rendered = field.parsed_value
        if rendered is None:
            rendered = field.raw_value.hex()
        tags.append(
            _moi_tag(
                field.name,
                _moi_print_value(field.name, rendered),
                "MOI",
                field.name,
                field.evidence_ids,
                duplicate_instance_ordinal=ordinal,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _read_moi_exiftool_probe(path: Path, prefix: bytes) -> bytes:
    # MOI.pm reads exactly the 256-byte sidecar metadata window before binary
    # tag extraction; trailing bytes are unrelated to the public read surface.
    data = bytearray(prefix)
    if len(data) >= MOI_EXIFTOOL_READ_SIZE:
        return bytes(data[:MOI_EXIFTOOL_READ_SIZE])
    with path.open("rb") as file:
        file.seek(len(data))
        data.extend(file.read(MOI_EXIFTOOL_READ_SIZE - len(data)))
    return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="moi",
        builder_ref="exifmodern.formats.moi:invoke_moi",
        patterns=(Pattern(0, b"V6"),),
        weak=True,
    ),
)
