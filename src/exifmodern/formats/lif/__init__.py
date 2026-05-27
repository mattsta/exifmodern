"""LIF container transaction planning."""

from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.lif.container_transaction_plan import (
    LIF_HEADER_SIZE,
    LIF_XML_SIZE_LIMIT,
    LifContainerTransactionPlan,
    build_lif_container_transaction_plan,
)
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "LifContainerTransactionPlan",
    "build_lif_container_transaction_plan",
    "build_lif_read_graph",
    "invoke_lif",
]


def build_lif_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_lif_container_transaction_plan(data, allow_output_emission=True)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"LIF package-local reader status: {plan.status}")
    diagnostics.extend(
        f"LIF package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = []
    for ordinal, entry in enumerate(plan.metadata_entries):
        value = (
            " ".join(entry.converted_timestamp_values)
            if entry.converted_timestamp_values
            else entry.value
        )
        tags.append(
            ReadTag(
                name=entry.tag_name,
                value=_read_value(value),
                provenance=_provenance(
                    group="LIF",
                    table_name="Image::ExifTool::LIF::Main",
                    tag_id=entry.tag_path,
                    evidence_ids=entry.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    for ordinal, image in enumerate(plan.image_responsibilities, start=len(tags)):
        tags.append(
            ReadTag(
                name=image.tag_name,
                value=_read_value(image.value),
                provenance=_provenance(
                    group="LIF",
                    table_name="Image::ExifTool::LIF::Main",
                    tag_id=image.concern,
                    evidence_ids=image.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_lif(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_lif_read_graph(_read_lif_exiftool_metadata(path, prefix), source_file)


def _read_lif_exiftool_metadata(path: Path, prefix: bytes) -> bytes:
    # LIF.pm reads the 15-byte signature/header window, enforces the 100 MB XML
    # chunk guard, then reads only the declared UTF-16 XML/container chunk.
    data = bytearray(prefix)
    if len(data) < 15:
        with path.open("rb") as file:
            data = bytearray(file.read(15))
    if len(data) < LIF_HEADER_SIZE:
        return bytes(data)
    declared_chunk_size = int.from_bytes(data[4:8], "little")
    if declared_chunk_size > LIF_XML_SIZE_LIMIT:
        return bytes(data)
    target_size = LIF_HEADER_SIZE + declared_chunk_size
    if len(data) >= target_size:
        return bytes(data[:target_size])
    with path.open("rb") as file:
        file.seek(len(data))
        data.extend(file.read(target_size - len(data)))
    return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="lif",
        builder_ref="exifmodern.formats.lif:invoke_lif",
        patterns=(
            Pattern(0, b"\x70\x00\x00\x00"),
            Pattern(8, b"\x2a"),
            Pattern(13, b"<\x00"),
        ),
    ),
)
