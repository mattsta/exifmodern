"""MNG/JNG transaction planning primitives translated from ExifTool MNG.pm."""

from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.mng.chunk_transaction_plan import (
    MngChunkTransactionPlan,
    MngRewriteRequest,
    build_mng_chunk_transaction_plan,
    plan_mng_chunk_transaction,
)
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "MngChunkTransactionPlan",
    "MngRewriteRequest",
    "build_mng_chunk_transaction_plan",
    "build_mng_read_graph",
    "invoke_mng",
    "plan_mng_chunk_transaction",
]


def build_mng_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_mng_chunk_transaction_plan(data, validate_crc=False)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"MNG package-local reader status: {plan.status}")
    diagnostics.extend(
        f"MNG package-local reader gate: {gate.code}" for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = []
    for ordinal, responsibility in enumerate(plan.responsibilities):
        if responsibility.tag_name is None:
            continue
        # Locate the chunk to derive a value (payload size for textual chunks).
        chunk = next(
            (c for c in plan.chunks if c.index == responsibility.chunk_index),
            None,
        )
        chunk_id = responsibility.chunk_type.decode("ascii", errors="replace")
        rendered: str | int = responsibility.keyword or chunk_id
        if chunk is not None and not responsibility.keyword:
            rendered = chunk.payload_length
        tags.append(
            ReadTag(
                name=responsibility.tag_name,
                value=_read_value(rendered),
                provenance=_provenance(
                    group="MNG",
                    table_name="Image::ExifTool::MNG::Main",
                    tag_id=chunk_id,
                    evidence_ids=responsibility.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_mng(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_mng_read_graph(_read_mng_exiftool_chunks(path), source_file)


def _read_mng_exiftool_chunks(path: Path) -> bytes:
    with path.open("rb") as file:
        data = bytearray(file.read(8))
        if len(data) < 8:
            return bytes(data)
        for _ in range(4096):
            chunk_header = file.read(8)
            if len(chunk_header) != 8:
                break
            chunk_type = chunk_header[4:8]
            payload_length = int.from_bytes(chunk_header[:4], "big")
            data.extend(chunk_header)
            if chunk_type in {b"IDAT", b"JDAT", b"JDAA", b"IJNG", b"IPNG"}:
                file.seek(payload_length + 4, 1)
                break
            data.extend(file.read(payload_length + 4))
            if chunk_type in {b"MEND", b"IEND"}:
                break
        return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="mng",
        builder_ref="exifmodern.formats.mng:invoke_mng",
        patterns=(Pattern(0, b"\x8aMNG\r\n\x1a\n"),),
    ),
    Signature(
        format_id="mng/jng",
        builder_ref="exifmodern.formats.mng:invoke_mng",
        patterns=(Pattern(0, b"\x8bJNG\r\n\x1a\n"),),
    ),
)
