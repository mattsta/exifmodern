"""Read-only PNG chunk enumeration helpers.

This module intentionally avoids importing the write-capable PNG transaction
planner. Public read paths need deterministic chunk boundaries, CRC facts, and
small metadata routing hints, but they do not need mutation planning.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonObject

type PngEvidenceId = str
type PngReadIssueCode = Literal[
    "truncated_png_signature",
    "unsupported_png_signature",
    "truncated_png_chunk_header",
    "truncated_png_chunk_payload",
    "invalid_png_chunk_size",
]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_CHUNK_HEADER_SIZE = 8
PNG_CRC_SIZE = 4
PNG_MAX_EXIFTOOL_CHUNK_LENGTH = 0x7FFFFFFF

IHDR_CHUNK_TYPE = b"IHDR"
IEND_CHUNK_TYPE = b"IEND"
TEXT_CHUNK_TYPES = frozenset((b"tEXt", b"zTXt", b"iTXt"))
EXIF_CHUNK_TYPES = frozenset((b"eXIf", b"zXIf"))
ICC_CHUNK_TYPE = b"iCCP"
PHYS_CHUNK_TYPE = b"pHYs"
DATA_CHUNK_TYPES = frozenset((b"IDAT", b"JDAT", b"JDAA"))
OBSOLETE_XMP_CHUNK_TYPE = b"tXMP"

PNG_SIGNATURE_SOURCE: PngEvidenceId = "png.png_signature"
PNG_PROCESS_SIGNATURE_SOURCE: PngEvidenceId = "png.png_process_signature"
PNG_CHUNK_ENUMERATION_SOURCE: PngEvidenceId = "png.png_chunk_enumeration"
PNG_CRC_SOURCE: PngEvidenceId = "png.png_crc"
PNG_AFTER_IDAT_WARNING_SOURCE: PngEvidenceId = "png.png_after_idat_warning"
PNG_EXIF_SOURCE: PngEvidenceId = "png.png_exif"
PNG_ICC_CHUNK_SOURCE: PngEvidenceId = "png.png_icc_chunk"
PNG_PHYS_CHUNK_SOURCE: PngEvidenceId = "png.png_phys_chunk"
PNG_PHYS_TABLE_SOURCE: PngEvidenceId = "png.png_phys_table"
PNG_TEXT_ROUTING_SOURCE: PngEvidenceId = "png.png_text_routing"
PNG_TEXT_TABLE_SOURCE: PngEvidenceId = "png.png_text_table"
PNG_XMP_SOURCE: PngEvidenceId = "png.png_xmp"


@dataclass(frozen=True)
class PngChunkPlan:
    index: int
    chunk_type: bytes
    chunk_start_offset: int
    payload_offset: int
    payload_length: int
    crc_offset: int
    end_offset: int
    payload: bytes
    stored_crc: int
    calculated_crc: int
    crc_matches: bool
    after_idat: bool
    after_iend: bool
    evidence_ids: tuple[PngEvidenceId, ...]

    @property
    def encoded_length(self) -> int:
        return PNG_CHUNK_HEADER_SIZE + self.payload_length + PNG_CRC_SIZE

    def to_json(self) -> JsonObject:
        return {
            "after_idat": self.after_idat,
            "after_iend": self.after_iend,
            "calculated_crc": self.calculated_crc,
            "chunk_start_offset": self.chunk_start_offset,
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "crc_matches": self.crc_matches,
            "crc_offset": self.crc_offset,
            "encoded_length": self.encoded_length,
            "end_offset": self.end_offset,
            "index": self.index,
            "payload_length": self.payload_length,
            "payload_offset": self.payload_offset,
            "stored_crc": self.stored_crc,
        }


@dataclass(frozen=True)
class PngReadIssue:
    code: PngReadIssueCode
    reason: str
    evidence_ids: tuple[PngEvidenceId, ...]


@dataclass(frozen=True)
class PngReadChunkPlan:
    status: Literal["planned", "unsupported"]
    chunks: tuple[PngChunkPlan, ...]
    trailer: bytes
    issues: tuple[PngReadIssue, ...]
    evidence_ids: tuple[PngEvidenceId, ...]


def build_png_read_chunk_plan(png_data: bytes) -> PngReadChunkPlan:
    issues: list[PngReadIssue] = []
    if len(png_data) < len(PNG_SIGNATURE):
        issues.append(
            PngReadIssue(
                "truncated_png_signature",
                "Input ended before a complete PNG signature could be read.",
                (PNG_SIGNATURE_SOURCE, PNG_PROCESS_SIGNATURE_SOURCE),
            )
        )
        return _unsupported_read_plan(issues)
    if png_data[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
        issues.append(
            PngReadIssue(
                "unsupported_png_signature",
                "Input does not start with the PNG signature.",
                (PNG_SIGNATURE_SOURCE, PNG_PROCESS_SIGNATURE_SOURCE),
            )
        )
        return _unsupported_read_plan(issues)

    chunks, trailer, issues_tuple = enumerate_png_chunks(png_data)
    issues.extend(issues_tuple)
    return PngReadChunkPlan(
        status="unsupported" if issues else "planned",
        chunks=chunks,
        trailer=trailer,
        issues=tuple(issues),
        evidence_ids=unique_sources(
            (
                PNG_SIGNATURE_SOURCE,
                PNG_PROCESS_SIGNATURE_SOURCE,
                PNG_CHUNK_ENUMERATION_SOURCE,
                PNG_CRC_SOURCE,
                *(source for chunk in chunks for source in chunk.evidence_ids),
                *(source for issue in issues for source in issue.evidence_ids),
            )
        ),
    )


def enumerate_png_chunks(
    png_data: bytes,
) -> tuple[tuple[PngChunkPlan, ...], bytes, tuple[PngReadIssue, ...]]:
    chunks: list[PngChunkPlan] = []
    issues: list[PngReadIssue] = []
    offset = len(PNG_SIGNATURE)
    was_idat = False
    while offset < len(png_data):
        if len(png_data) - offset < PNG_CHUNK_HEADER_SIZE:
            issues.append(
                PngReadIssue(
                    "truncated_png_chunk_header",
                    "Input ended before a complete PNG chunk header could be read.",
                    (PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(chunks), b"", tuple(issues)

        chunk_start = offset
        payload_length = int.from_bytes(png_data[offset : offset + 4], "big")
        chunk_type = png_data[offset + 4 : offset + 8]
        offset += PNG_CHUNK_HEADER_SIZE
        if payload_length > PNG_MAX_EXIFTOOL_CHUNK_LENGTH:
            issues.append(
                PngReadIssue(
                    "invalid_png_chunk_size",
                    (
                        f"{ascii_chunk_id(chunk_type)} declares a chunk length larger "
                        "than ExifTool accepts."
                    ),
                    (PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(chunks), b"", tuple(issues)

        payload_end = offset + payload_length
        crc_end = payload_end + PNG_CRC_SIZE
        if crc_end > len(png_data):
            issues.append(
                PngReadIssue(
                    "truncated_png_chunk_payload",
                    f"{ascii_chunk_id(chunk_type)} payload or CRC is truncated.",
                    (PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(chunks), b"", tuple(issues)

        payload = png_data[offset:payload_end]
        stored_crc = int.from_bytes(png_data[payload_end:crc_end], "big")
        calculated_crc = png_crc(chunk_type, payload)
        chunk = PngChunkPlan(
            index=len(chunks),
            chunk_type=chunk_type,
            chunk_start_offset=chunk_start,
            payload_offset=offset,
            payload_length=payload_length,
            crc_offset=payload_end,
            end_offset=crc_end,
            payload=payload,
            stored_crc=stored_crc,
            calculated_crc=calculated_crc,
            crc_matches=stored_crc == calculated_crc,
            after_idat=was_idat and chunk_type not in DATA_CHUNK_TYPES,
            after_iend=False,
            evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE, PNG_CRC_SOURCE),
        )
        chunks.append(chunk)
        offset = crc_end
        if chunk_type in DATA_CHUNK_TYPES:
            was_idat = True
        if chunk_type == IEND_CHUNK_TYPE:
            return tuple(chunks), png_data[offset:], tuple(issues)
    return tuple(chunks), b"", tuple(issues)


def png_crc(chunk_type: bytes, payload: bytes) -> int:
    return zlib.crc32(chunk_type + payload) & 0xFFFFFFFF


def ascii_chunk_id(chunk_id: bytes | None) -> str | None:
    if chunk_id is None:
        return None
    return chunk_id.decode("latin-1")


def unique_sources(references: Iterable[PngEvidenceId]) -> tuple[PngEvidenceId, ...]:
    seen: set[PngEvidenceId] = set()
    unique: list[PngEvidenceId] = []
    for reference in references:
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(reference)
    return tuple(unique)


def _unsupported_read_plan(issues: list[PngReadIssue]) -> PngReadChunkPlan:
    return PngReadChunkPlan(
        status="unsupported",
        chunks=(),
        trailer=b"",
        issues=tuple(issues),
        evidence_ids=unique_sources(source for issue in issues for source in issue.evidence_ids),
    )
