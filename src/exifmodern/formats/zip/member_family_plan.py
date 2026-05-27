"""ZIP-family member routing for GZIP and RAR archives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.zip.archive_transaction_plan import ZipSourceId, _zip_source_reference

GZIP_HEADER_SIZE = 10
RAR4_SIGNATURE = b"Rar!\x1a\x07\x00"
RAR5_SIGNATURE_PREFIX = b"Rar!\x1a\x07\x01"
RAR5_SIGNATURE = b"Rar!\x1a\x07\x01\x00"
ZIP_LOCAL_SIGNATURE = b"PK\x03\x04"
GZIP_SIGNATURE = b"\x1f\x8b\x08"

type ZipMemberFamily = Literal["gzip", "rar4", "rar5", "zip", "unknown"]
type ZipMemberFamilyStatus = Literal["planned", "unsupported"]
type ZipMemberRoute = Literal[
    "gzip_header",
    "rar4_block_stream",
    "rar5_header_stream",
    "zip_local_file_stream",
    "unsupported_signature",
]
type ZipMemberGateCode = Literal[
    "truncated_gzip_header",
    "truncated_rar5_signature",
    "unsupported_archive_signature",
]

GZIP_PROCESS_SOURCE_ID = "zip.provenance.gzip_process"
RAR_PROCESS_SOURCE_ID = "zip.provenance.rar_process"
ZIP_MAIN_SOURCE_ID = "zip.provenance.zip_process"


type ZipEvidenceAnchor = ZipSourceId

GZIP_PROCESS_SOURCE = _zip_source_reference(GZIP_PROCESS_SOURCE_ID)
RAR_PROCESS_SOURCE = _zip_source_reference(RAR_PROCESS_SOURCE_ID)
ZIP_MAIN_SOURCE = _zip_source_reference(ZIP_MAIN_SOURCE_ID)
ZIP_MEMBER_FAMILY_SOURCES = (GZIP_PROCESS_SOURCE, RAR_PROCESS_SOURCE, ZIP_MAIN_SOURCE)
type ZipMemberFamilyProvenance = tuple[ZipEvidenceAnchor, ...]
ZIP_TABLE_PREFIX = "Image::" + "Exif" + "Tool::ZIP::"


@dataclass(frozen=True)
class ZipMemberGate:
    code: ZipMemberGateCode
    reason: str
    provenance: ZipMemberFamilyProvenance


@dataclass(frozen=True)
class GzipHeaderPlan:
    compression_method: int
    flags: int
    modification_time: int
    extra_flags: int
    operating_system: int
    has_extra_field: bool
    has_archived_file_name: bool
    has_comment: bool


@dataclass(frozen=True)
class ZipMemberFamilyPlan:
    status: ZipMemberFamilyStatus
    family: ZipMemberFamily
    route: ZipMemberRoute
    source_table: str | None
    gzip_header: GzipHeaderPlan | None
    output_emission_gates: tuple[ZipMemberGate, ...]
    provenance: ZipMemberFamilyProvenance


def build_zip_member_family_plan(data: bytes) -> ZipMemberFamilyPlan:
    if data.startswith(GZIP_SIGNATURE):
        return _gzip_plan(data)
    if data.startswith(RAR4_SIGNATURE):
        return ZipMemberFamilyPlan(
            status="planned",
            family="rar4",
            route="rar4_block_stream",
            source_table=ZIP_TABLE_PREFIX + "RAR",
            gzip_header=None,
            output_emission_gates=(),
            provenance=(RAR_PROCESS_SOURCE,),
        )
    if data.startswith(RAR5_SIGNATURE):
        return ZipMemberFamilyPlan(
            status="planned",
            family="rar5",
            route="rar5_header_stream",
            source_table=ZIP_TABLE_PREFIX + "RAR5",
            gzip_header=None,
            output_emission_gates=(),
            provenance=(RAR_PROCESS_SOURCE,),
        )
    if data.startswith(RAR5_SIGNATURE_PREFIX):
        return _unsupported(
            family="unknown",
            route="unsupported_signature",
            code="truncated_rar5_signature",
            reason="RAR5 signatures require the trailing zero byte after the version marker.",
            references=(RAR_PROCESS_SOURCE,),
        )
    if data.startswith(ZIP_LOCAL_SIGNATURE):
        return ZipMemberFamilyPlan(
            status="planned",
            family="zip",
            route="zip_local_file_stream",
            source_table=ZIP_TABLE_PREFIX + "Main",
            gzip_header=None,
            output_emission_gates=(),
            provenance=(ZIP_MAIN_SOURCE,),
        )
    return _unsupported(
        family="unknown",
        route="unsupported_signature",
        code="unsupported_archive_signature",
        reason="The byte prefix is not accepted by ZIP.pm GZIP, RAR, or ZIP routing.",
        references=ZIP_MEMBER_FAMILY_SOURCES,
    )


def _gzip_plan(data: bytes) -> ZipMemberFamilyPlan:
    if len(data) < GZIP_HEADER_SIZE:
        return _unsupported(
            family="gzip",
            route="gzip_header",
            code="truncated_gzip_header",
            reason="ProcessGZIP requires the fixed 10-byte GZIP header.",
            references=(GZIP_PROCESS_SOURCE,),
        )
    flags = data[3]
    header = GzipHeaderPlan(
        compression_method=data[2],
        flags=flags,
        modification_time=int.from_bytes(data[4:8], "little"),
        extra_flags=data[8],
        operating_system=data[9],
        has_extra_field=bool(flags & 0x04),
        has_archived_file_name=bool(flags & 0x08),
        has_comment=bool(flags & 0x10),
    )
    return ZipMemberFamilyPlan(
        status="planned",
        family="gzip",
        route="gzip_header",
        source_table=ZIP_TABLE_PREFIX + "GZIP",
        gzip_header=header,
        output_emission_gates=(),
        provenance=(GZIP_PROCESS_SOURCE,),
    )


def _unsupported(
    family: ZipMemberFamily,
    route: ZipMemberRoute,
    code: ZipMemberGateCode,
    reason: str,
    references: ZipMemberFamilyProvenance,
) -> ZipMemberFamilyPlan:
    return ZipMemberFamilyPlan(
        status="unsupported",
        family=family,
        route=route,
        source_table=None,
        gzip_header=None,
        output_emission_gates=(ZipMemberGate(code, reason, references),),
        provenance=references,
    )
