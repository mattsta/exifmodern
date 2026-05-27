"""Rawzor/RWZ metadata transaction planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.rawzor.metadata_transaction_plan import (
    RawzorMetadataRewriteRequest,
    RawzorMetadataTransactionPlan,
    build_rawzor_metadata_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = (
    "RawzorMetadataRewriteRequest",
    "RawzorMetadataTransactionPlan",
    "build_rawzor_metadata_transaction_plan",
    "build_rawzor_read_graph",
    "invoke_rawzor",
)


_RAWZOR_TABLE = "Image::ExifTool::Rawzor::Main"
_RAWZOR_MAX_SPARSE_MATERIALIZATION = 16 * 1024 * 1024


def build_rawzor_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a Rawzor metadata transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_rawzor_metadata_transaction_plan(data)
    diagnostics = [
        f"Rawzor package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"Rawzor package-local reader status: {plan.status}")

    tags: list[ReadTag] = []
    header = plan.header
    header_scalars: tuple[tuple[str, int | float | str | None], ...] = (
        ("RequiredSDKVersion", header.required_sdk_version),
        ("CreatorSDKVersion", header.creator_sdk_version),
        ("DeclaredRwzSize", header.declared_rwz_size),
        ("ActualRwzSize", header.actual_rwz_size),
        ("OriginalFileSize", header.original_file_size),
        ("CompressionFactor", header.compression_factor),
    )
    for name, value in header_scalars:
        if value is None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="File",
                    table_name=_RAWZOR_TABLE,
                    tag_id=name,
                    evidence_ids=header.evidence_ids,
                ),
                schema=None,
            )
        )
    original_file_type = plan.original_file_type
    if original_file_type.detected_original_file_type is not None:
        tags.append(
            ReadTag(
                name=original_file_type.original_file_type_tag,
                value=_read_value(original_file_type.detected_original_file_type),
                provenance=_provenance(
                    group="File",
                    table_name=_RAWZOR_TABLE,
                    tag_id=original_file_type.original_file_type_tag,
                    evidence_ids=original_file_type.evidence_ids,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_rawzor(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_rawzor_read_graph(_read_rawzor_metadata_bytes(path), source_file)


def _read_rawzor_metadata_bytes(path: Path) -> bytes:
    from exifmodern.formats.rawzor.metadata_transaction_plan import (
        RAWZOR_HEADER_SIZE,
        RAWZOR_METADATA_HEADER_SIZE,
    )

    file_size = path.stat().st_size
    with path.open("rb") as file:
        header = file.read(RAWZOR_HEADER_SIZE)
        if len(header) < RAWZOR_HEADER_SIZE:
            return header
        metadata_offset = int.from_bytes(header[38:46], "little")
        if metadata_offset > file_size:
            return header
        file.seek(metadata_offset)
        metadata_header = file.read(RAWZOR_METADATA_HEADER_SIZE)
        if len(metadata_header) < RAWZOR_METADATA_HEADER_SIZE:
            return _sparse_bytes(file_size, ((0, header), (metadata_offset, metadata_header)))
        compressed_size = int.from_bytes(metadata_header[40:44], "little")
        compressed_offset = metadata_offset + RAWZOR_METADATA_HEADER_SIZE
        file.seek(compressed_offset)
        compressed_payload = file.read(compressed_size)
    return _sparse_bytes(
        file_size,
        (
            (0, header),
            (metadata_offset, metadata_header),
            (compressed_offset, compressed_payload),
        ),
    )


def _sparse_bytes(size: int, chunks: tuple[tuple[int, bytes], ...]) -> bytes:
    materialized_size = max((offset + len(chunk) for offset, chunk in chunks), default=0)
    if materialized_size > _RAWZOR_MAX_SPARSE_MATERIALIZATION:
        return chunks[0][1] if chunks else b""
    result = bytearray(b"\0" * min(max(size, materialized_size), materialized_size))
    for offset, chunk in chunks:
        result[offset : offset + len(chunk)] = chunk
    return bytes(result)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="rawzor",
        builder_ref="exifmodern.formats.rawzor:invoke_rawzor",
        patterns=(Pattern(0, b"rawzor"),),
    ),
)
