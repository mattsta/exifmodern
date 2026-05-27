"""Audible metadata transaction planning public API."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.audible.metadata_transaction_plan import (
    AUDIBLE_AA_HEADER_SIZE,
    AUDIBLE_AA_MAGIC,
    AUDIBLE_AA_MAX_CHUNK_BYTES,
    AUDIBLE_AA_MAX_TOC_BYTES,
    AUDIBLE_AA_TOC_ENTRY_SIZE,
    AudibleMetadataTransactionPlan,
    AudibleMetadataWriteRequest,
    build_audible_metadata_transaction_plan,
)
from exifmodern.formats.audible.read_graph_adapter import (
    audible_transaction_plan_to_read_graph,
    build_audible_read_graph,
    is_audible_aa_prefix,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "AudibleMetadataTransactionPlan",
    "AudibleMetadataWriteRequest",
    "audible_transaction_plan_to_read_graph",
    "build_audible_metadata_transaction_plan",
    "build_audible_read_graph",
    "invoke_audible",
    "is_audible_aa_prefix",
)


def invoke_audible(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    file_size = path.stat().st_size
    data = _read_audible_aa_metadata_bytes(path, prefix, file_size=file_size)
    return build_audible_read_graph(data, source_file=source_file, actual_file_size=file_size)


def _read_audible_aa_metadata_bytes(path: Path, prefix: bytes, *, file_size: int) -> bytes:
    """Read ExifTool's AA header/TOC plus selected metadata chunks."""

    header = prefix[:AUDIBLE_AA_HEADER_SIZE]
    if len(header) < AUDIBLE_AA_HEADER_SIZE or header[4:8] != AUDIBLE_AA_MAGIC:
        return header
    toc_entry_count = int.from_bytes(header[8:12], "big")
    toc_byte_count = AUDIBLE_AA_TOC_ENTRY_SIZE * toc_entry_count
    if toc_byte_count > AUDIBLE_AA_MAX_TOC_BYTES:
        return header
    with path.open("rb") as file:
        file.seek(AUDIBLE_AA_HEADER_SIZE)
        toc = file.read(toc_byte_count)
        data = bytearray(header + toc)
        if len(toc) != toc_byte_count:
            return bytes(data)

        chunk_reads: list[tuple[int, int]] = []
        for index in range(toc_entry_count):
            entry_offset = index * AUDIBLE_AA_TOC_ENTRY_SIZE
            chunk_type = int.from_bytes(toc[entry_offset : entry_offset + 4], "big")
            offset = int.from_bytes(toc[entry_offset + 4 : entry_offset + 8], "big")
            length = int.from_bytes(toc[entry_offset + 8 : entry_offset + 12], "big")
            if length == 0 or length > AUDIBLE_AA_MAX_CHUNK_BYTES or offset >= file_size:
                continue
            if chunk_type == 6:
                chunk_reads.append((offset, min(length, 4)))
            elif chunk_type in {2, 11}:
                chunk_reads.append((offset, length))

        required_size = max((offset + length for offset, length in chunk_reads), default=len(data))
        if required_size > len(data):
            data.extend(b"\x00" * (required_size - len(data)))
        for offset, length in chunk_reads:
            file.seek(offset)
            chunk = file.read(length)
            data[offset : offset + len(chunk)] = chunk
        return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="audible/aa",
        builder_ref="exifmodern.formats.audible:invoke_audible",
        patterns=(Pattern(4, b"\x57\x90\x75\x36"),),
    ),
)
