"""Archive::Zip member attribute planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.zip.archive_transaction_plan import COMPRESSION_METHOD_NAMES

type ZipMemberAttributeStatus = Literal["planned"]
type ZipMemberAttributeTag = Literal[
    "ExtractVersion",
    "BitFlag",
    "Compression",
    "ModifyDate",
    "CRC",
    "CompressedSize",
    "UncompressedSize",
    "ArchivedFileName",
    "Comment",
]
type ZipMemberAttributeEvidenceId = Literal[
    "zip.archive_member.handle_member",
    "zip.archive_member.value_conversions",
]
type ZipMemberAttributeProvenance = tuple[ZipMemberAttributeEvidenceId, ...]

ZIP_HANDLE_MEMBER_EVIDENCE_ID: ZipMemberAttributeEvidenceId = "zip.archive_member.handle_member"
ZIP_MEMBER_VALUE_CONVERSION_EVIDENCE_ID: ZipMemberAttributeEvidenceId = (
    "zip.archive_member.value_conversions"
)


@dataclass(frozen=True)
class ZipMemberAttributeInput:
    extract_version: int
    bit_flag: int
    compression_method: int
    modified_datetime: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    file_name: str
    comment: str | None = None


@dataclass(frozen=True)
class ZipMemberAttributePlan:
    tag: ZipMemberAttributeTag
    value: str | int
    display_value: str | int | None = None


@dataclass(frozen=True)
class ZipMemberAttributesPlan:
    status: ZipMemberAttributeStatus
    tags: tuple[ZipMemberAttributePlan, ...]
    provenance: ZipMemberAttributeProvenance


def build_zip_member_attributes_plan(member: ZipMemberAttributeInput) -> ZipMemberAttributesPlan:
    tags = [
        ZipMemberAttributePlan("ExtractVersion", member.extract_version),
        ZipMemberAttributePlan("BitFlag", member.bit_flag, _render_zip_bit_flag(member.bit_flag)),
        ZipMemberAttributePlan(
            "Compression",
            member.compression_method,
            COMPRESSION_METHOD_NAMES.get(member.compression_method),
        ),
        ZipMemberAttributePlan(
            "ModifyDate",
            member.modified_datetime,
            render_zip_dos_datetime(member.modified_datetime),
        ),
        ZipMemberAttributePlan("CRC", member.crc32, f"0x{member.crc32:08x}"),
        ZipMemberAttributePlan("CompressedSize", member.compressed_size),
        ZipMemberAttributePlan("UncompressedSize", member.uncompressed_size),
        ZipMemberAttributePlan("ArchivedFileName", member.file_name),
    ]
    if member.comment:
        tags.append(ZipMemberAttributePlan("Comment", member.comment))
    return ZipMemberAttributesPlan(
        status="planned",
        tags=tuple(tags),
        provenance=(ZIP_HANDLE_MEMBER_EVIDENCE_ID, ZIP_MEMBER_VALUE_CONVERSION_EVIDENCE_ID),
    )


def render_zip_dos_datetime(value: int) -> str:
    return (
        f"{(value >> 25) + 1980:04d}:"
        f"{(value >> 21) & 0x0F:02d}:"
        f"{(value >> 16) & 0x1F:02d} "
        f"{(value >> 11) & 0x1F:02d}:"
        f"{(value >> 5) & 0x3F:02d}:"
        f"{(value & 0x1F) * 2:02d}"
    )


def _render_zip_bit_flag(value: int) -> str | int:
    if value:
        return f"0x{value:04x}"
    return value
