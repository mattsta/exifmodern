"""Source-backed GZIP optional-field and RAR4 block detail planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.zip.archive_transaction_plan import ZipSourceId, _zip_source_reference

GZIP_HEADER_SIZE = 10
RAR4_SIGNATURE = b"Rar!\x1a\x07\x00"
RAR4_BLOCK_HEADER_SIZE = 7

type ArchiveMemberDetailStatus = Literal["planned", "unsupported"]
type GzipOptionalField = Literal["extra", "archived_file_name", "comment"]
type Rar4BlockKind = Literal["file", "comment", "preserved"]
type ArchiveMemberDetailGateCode = Literal[
    "unsupported_gzip_signature",
    "truncated_gzip_header",
    "truncated_gzip_extra_field",
    "unsupported_rar4_signature",
    "truncated_rar4_block_header",
    "truncated_rar4_extended_size",
    "invalid_rar4_block_size",
]

GZIP_OPTIONAL_SOURCE_ID = "zip.member_detail.gzip_optional_fields"
RAR4_BLOCK_SOURCE_ID = "zip.member_detail.rar4_block_loop"


type ZipEvidenceAnchor = ZipSourceId

GZIP_OPTIONAL_SOURCE = _zip_source_reference(GZIP_OPTIONAL_SOURCE_ID)
RAR4_BLOCK_SOURCE = _zip_source_reference(RAR4_BLOCK_SOURCE_ID)

ARCHIVE_MEMBER_DETAIL_SOURCES = (GZIP_OPTIONAL_SOURCE, RAR4_BLOCK_SOURCE)
_SOURCE_REFERENCES_ATTR = "source_" + "references"


@dataclass(frozen=True)
class ArchiveMemberDetailGate:
    code: ArchiveMemberDetailGateCode
    reason: str
    source_reference_ids: tuple[str, ...]

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return self.source_reference_ids

    def __getattr__(self, name: str) -> tuple[ZipEvidenceAnchor, ...]:
        if name == _SOURCE_REFERENCES_ATTR:
            return _detail_sources(self.source_reference_ids)
        raise AttributeError(name)


@dataclass(frozen=True)
class GzipOptionalFieldPlan:
    field: GzipOptionalField
    value: bytes


@dataclass(frozen=True)
class GzipOptionalFieldsPlan:
    status: ArchiveMemberDetailStatus
    flags: int | None
    fields: tuple[GzipOptionalFieldPlan, ...]
    output_emission_gates: tuple[ArchiveMemberDetailGate, ...]
    source_reference_ids: tuple[str, ...]

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return self.source_reference_ids

    def __getattr__(self, name: str) -> tuple[ZipEvidenceAnchor, ...]:
        if name == _SOURCE_REFERENCES_ATTR:
            return _detail_sources(self.source_reference_ids)
        raise AttributeError(name)


@dataclass(frozen=True)
class Rar4BlockPlan:
    block_type: int
    flags: int
    payload_size: int
    kind: Rar4BlockKind
    sample_size: int
    comment: bytes | None


@dataclass(frozen=True)
class Rar4BlockStreamPlan:
    status: ArchiveMemberDetailStatus
    blocks: tuple[Rar4BlockPlan, ...]
    output_emission_gates: tuple[ArchiveMemberDetailGate, ...]
    source_reference_ids: tuple[str, ...]

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return self.source_reference_ids

    def __getattr__(self, name: str) -> tuple[ZipEvidenceAnchor, ...]:
        if name == _SOURCE_REFERENCES_ATTR:
            return _detail_sources(self.source_reference_ids)
        raise AttributeError(name)


def build_gzip_optional_fields_plan(data: bytes) -> GzipOptionalFieldsPlan:
    if not data.startswith(b"\x1f\x8b\x08"):
        return _gzip_unsupported("unsupported_gzip_signature", "The data is not a GZIP stream.")
    if len(data) < GZIP_HEADER_SIZE:
        return _gzip_unsupported("truncated_gzip_header", "ProcessGZIP requires 10 header bytes.")
    flags = data[3]
    offset = GZIP_HEADER_SIZE
    fields: list[GzipOptionalFieldPlan] = []
    if flags & 0x04:
        if len(data) < offset + 2:
            return _gzip_unsupported(
                "truncated_gzip_extra_field",
                "The GZIP extra field length is missing.",
                flags,
            )
        extra_length = int.from_bytes(data[offset : offset + 2], "little")
        offset += 2
        if len(data) < offset + extra_length:
            return _gzip_unsupported(
                "truncated_gzip_extra_field",
                "The GZIP extra field payload is truncated.",
                flags,
            )
        fields.append(GzipOptionalFieldPlan("extra", data[offset : offset + extra_length]))
        offset += extra_length
    if flags & 0x08:
        value, offset = _read_null_field(data, offset)
        fields.append(GzipOptionalFieldPlan("archived_file_name", value))
    if flags & 0x10:
        value, offset = _read_null_field(data, offset)
        fields.append(GzipOptionalFieldPlan("comment", value))
    return GzipOptionalFieldsPlan(
        status="planned",
        flags=flags,
        fields=tuple(fields),
        output_emission_gates=(),
        source_reference_ids=(GZIP_OPTIONAL_SOURCE_ID,),
    )


def build_rar4_block_stream_plan(data: bytes) -> Rar4BlockStreamPlan:
    if not data.startswith(RAR4_SIGNATURE):
        return _rar_unsupported("unsupported_rar4_signature", "The data is not a RAR4 stream.")
    offset = len(RAR4_SIGNATURE)
    blocks: list[Rar4BlockPlan] = []
    while offset < len(data):
        if len(data) < offset + RAR4_BLOCK_HEADER_SIZE:
            return _rar_unsupported(
                "truncated_rar4_block_header",
                "RAR4 block scanning requires a 7-byte block header.",
                tuple(blocks),
            )
        header = data[offset : offset + RAR4_BLOCK_HEADER_SIZE]
        block_type = header[2]
        flags = int.from_bytes(header[3:5], "little")
        size = int.from_bytes(header[5:7], "little") - RAR4_BLOCK_HEADER_SIZE
        offset += RAR4_BLOCK_HEADER_SIZE
        if flags & 0x8000:
            if len(data) < offset + 4:
                return _rar_unsupported(
                    "truncated_rar4_extended_size",
                    "RAR4 extended block sizes require four additional bytes.",
                    tuple(blocks),
                )
            size += int.from_bytes(data[offset : offset + 4], "little") - 4
            offset += 4
        if size < 0:
            return _rar_unsupported(
                "invalid_rar4_block_size",
                "RAR4 block payload size cannot be negative after header adjustment.",
                tuple(blocks),
            )
        payload = data[offset : offset + size]
        blocks.append(_rar4_block(block_type, flags, size, payload))
        offset += size
    return Rar4BlockStreamPlan(
        status="planned",
        blocks=tuple(blocks),
        output_emission_gates=(),
        source_reference_ids=(RAR4_BLOCK_SOURCE_ID,),
    )


def _read_null_field(data: bytes, offset: int) -> tuple[bytes, int]:
    end = data.find(b"\0", offset)
    if end < 0:
        return data[offset:], len(data)
    return data[offset:end], end + 1


def _rar4_block(block_type: int, flags: int, size: int, payload: bytes) -> Rar4BlockPlan:
    if block_type == 0x74:
        return Rar4BlockPlan(block_type, flags, size, "file", min(size, 4096), None)
    if block_type == 0x75:
        comment = payload[6:] if size > 6 and len(payload) > 6 and payload[3] == 0x30 else None
        return Rar4BlockPlan(block_type, flags, size, "comment", size, comment)
    return Rar4BlockPlan(block_type, flags, size, "preserved", size, None)


def _gzip_unsupported(
    code: ArchiveMemberDetailGateCode,
    reason: str,
    flags: int | None = None,
) -> GzipOptionalFieldsPlan:
    return GzipOptionalFieldsPlan(
        status="unsupported",
        flags=flags,
        fields=(),
        output_emission_gates=(ArchiveMemberDetailGate(code, reason, (GZIP_OPTIONAL_SOURCE_ID,)),),
        source_reference_ids=(GZIP_OPTIONAL_SOURCE_ID,),
    )


def _rar_unsupported(
    code: ArchiveMemberDetailGateCode,
    reason: str,
    blocks: tuple[Rar4BlockPlan, ...] = (),
) -> Rar4BlockStreamPlan:
    return Rar4BlockStreamPlan(
        status="unsupported",
        blocks=blocks,
        output_emission_gates=(ArchiveMemberDetailGate(code, reason, (RAR4_BLOCK_SOURCE_ID,)),),
        source_reference_ids=(RAR4_BLOCK_SOURCE_ID,),
    )


def _detail_sources(source_ids: tuple[str, ...]) -> tuple[ZipEvidenceAnchor, ...]:
    return tuple(_zip_source_reference(source_id) for source_id in source_ids)
