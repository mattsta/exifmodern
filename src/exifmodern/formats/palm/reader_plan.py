"""Source-backed Palm/PDB and MOBI reader plan."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.palm.database_transaction_plan import (
    PALM_MOBI_SOURCE,
    PALM_PROCESS_SOURCE,
    PALM_TYPE_SOURCE,
    PalmEvidenceId,
    PalmRecordEntryPlan,
    build_palm_database_transaction_plan,
)

type PalmReaderStatus = Literal["planned", "unsupported"]
type PalmReaderDiagnosticCode = Literal["unsupported_palm_database"]

PALM_EXTH_TABLE_SOURCE: PalmEvidenceId = "palm.exth_table"
PALM_EXTH_PROCESS_SOURCE: PalmEvidenceId = "palm.process_exth"


@dataclass(frozen=True)
class PalmReaderDiagnostic:
    code: PalmReaderDiagnosticCode
    detail: str
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmReadTag:
    name: str
    value: str | int
    group: str
    source_table: str
    tag_id: str
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmReaderPlan:
    status: PalmReaderStatus
    tags: tuple[PalmReadTag, ...]
    diagnostics: tuple[PalmReaderDiagnostic, ...]
    evidence_ids: tuple[PalmEvidenceId, ...]


def build_palm_reader_plan(data: bytes) -> PalmReaderPlan:
    transaction = build_palm_database_transaction_plan(data, allow_output_emission=True)
    blocking_gate_codes = {
        "truncated_palm_header",
        "unsupported_palm_type_creator",
        "truncated_entry_list",
        "truncated_mobi_header",
        "invalid_mobi_header",
        "invalid_mobi_extended_header",
        "truncated_mobi_extended_header",
    }
    blocking_gates = tuple(
        gate for gate in transaction.output_emission_gates if gate.code in blocking_gate_codes
    )
    if blocking_gates:
        return PalmReaderPlan(
            status="unsupported",
            tags=(),
            diagnostics=tuple(
                PalmReaderDiagnostic(
                    code="unsupported_palm_database",
                    detail=gate.code,
                    evidence_ids=gate.evidence_ids,
                )
                for gate in blocking_gates
            ),
            evidence_ids=transaction.evidence_ids,
        )
    tags: list[PalmReadTag] = [
        PalmReadTag(
            "FileType",
            "MOBI",
            "File",
            "Image::ExifTool::Palm::Main",
            "FileType",
            (PALM_TYPE_SOURCE,),
        ),
        PalmReadTag(
            "FileTypeExtension",
            "mobi",
            "File",
            "Image::ExifTool::Palm::Main",
            "FileTypeExtension",
            (PALM_TYPE_SOURCE,),
        ),
        PalmReadTag(
            "MIMEType",
            "application/x-mobipocket-ebook",
            "File",
            "Image::ExifTool::Palm::Main",
            "MIMEType",
            (PALM_TYPE_SOURCE,),
        ),
    ]
    header = transaction.header
    if header.database_name is not None:
        tags.append(_main_tag("DatabaseName", header.database_name, "0"))
    for timestamp in (
        header.create_timestamp,
        header.modify_timestamp,
        header.last_backup_timestamp,
    ):
        if timestamp.unix_seconds is None:
            continue
        rendered_date = (
            "0000:00:00 00:00:00"
            if timestamp.raw_value == 0
            else _format_palm_datetime(timestamp.unix_seconds)
        )
        tags.append(
            PalmReadTag(
                timestamp.tag_name,
                rendered_date,
                "Palm",
                "Image::ExifTool::Palm::Main",
                {"CreateDate": "9", "ModifyDate": "10", "LastBackupDate": "11"}[timestamp.tag_name],
                timestamp.evidence_ids,
            )
        )
    if header.modification_number is not None:
        tags.append(_main_tag("ModificationNumber", header.modification_number, "12"))
    if header.recognized_type_name is not None:
        tags.append(_main_tag("PalmFileType", header.recognized_type_name, "15"))

    mobi = transaction.mobi
    if (
        mobi.should_process
        and mobi.first_record_offset is not None
        and mobi.header_length is not None
    ):
        record_end = _record_end(data, mobi.first_record_offset, transaction.entry_list.records)
        first_record = data[mobi.first_record_offset : record_end]
        tags.extend(_mobi_tags(first_record, mobi.book_name))
        if mobi.exth_offset is not None and mobi.exth_size is not None:
            tags.extend(_exth_tags(data[mobi.exth_offset + 12 : mobi.exth_offset + mobi.exth_size]))

    return PalmReaderPlan(
        status="planned",
        tags=tuple(tags),
        diagnostics=(),
        evidence_ids=transaction.evidence_ids,
    )


def _main_tag(name: str, value: str | int, tag_id: str) -> PalmReadTag:
    return PalmReadTag(
        name, value, "Palm", "Image::ExifTool::Palm::Main", tag_id, (PALM_PROCESS_SOURCE,)
    )


def _mobi_tags(first_record: bytes, book_name: str | None) -> tuple[PalmReadTag, ...]:
    if len(first_record) < 108:
        return ()
    specs: list[tuple[str, str | int, str]] = [
        ("Compression", _compression_name(_u16(first_record, 0)), "0"),
        ("UncompressedTextLength", _format_file_size(_u32(first_record, 4)), "1"),
        ("Encryption", _encryption_name(_u32(first_record, 12)), "3"),
        ("MobiType", _mobi_type_name(_u32(first_record, 24)), "6"),
        ("CodePage", _code_page_name(_u32(first_record, 28)), "7"),
        ("MobiVersion", _u32(first_record, 36), "9"),
        ("MinimumVersion", _u32(first_record, 104), "26"),
    ]
    if book_name is not None:
        specs.append(("BookName", book_name, "21"))
    return tuple(
        PalmReadTag(name, value, "Palm", "Image::ExifTool::Palm::MOBI", tag_id, (PALM_MOBI_SOURCE,))
        for name, value, tag_id in specs
    )


def _exth_tags(payload: bytes) -> tuple[PalmReadTag, ...]:
    tags: list[PalmReadTag] = []
    offset = 0
    while offset + 8 <= len(payload):
        tag_id = _u32(payload, offset)
        length = _u32(payload, offset + 4)
        if length < 8 or offset + length > len(payload):
            break
        raw = payload[offset + 8 : offset + length]
        spec = _exth_spec(tag_id)
        if spec is not None:
            name, is_int = spec
            value: str | int = (
                _u32(raw, 0) if is_int and len(raw) >= 4 else raw.decode("cp1252", errors="replace")
            )
            tags.append(
                PalmReadTag(
                    name,
                    _creator_software_name(value)
                    if name == "CreatorSoftware" and isinstance(value, int)
                    else value,
                    "Palm",
                    "Image::ExifTool::Palm::EXTH",
                    str(tag_id),
                    (PALM_EXTH_TABLE_SOURCE, PALM_EXTH_PROCESS_SOURCE),
                )
            )
        offset += length
    return tuple(tags)


def _record_end(
    data: bytes,
    first_record_offset: int,
    records: tuple[PalmRecordEntryPlan, ...],
) -> int:
    next_offsets = [
        record.payload_offset for record in records if record.payload_offset > first_record_offset
    ]
    return min(next_offsets) if next_offsets else len(data)


def _exth_spec(tag_id: int) -> tuple[str, bool] | None:
    specs = {
        100: ("Author", False),
        103: ("Description", False),
        108: ("Contributor", False),
        204: ("CreatorSoftware", True),
        205: ("CreatorMajorVersion", True),
        206: ("CreatorMinorVersion", True),
        207: ("CreatorBuildNumber", True),
    }
    return specs.get(tag_id)


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def _compression_name(value: int) -> str:
    return {1: "None", 2: "PalmDOC", 17480: "HUFF/CDIC"}.get(value, str(value))


def _encryption_name(value: int) -> str:
    return {0: "None", 1: "Old Mobipocket", 2: "Mobipocket"}.get(value, str(value))


def _mobi_type_name(value: int) -> str:
    return {2: "Mobipocket Book", 3: "PalmDoc Book", 248: "KF8: generated by kindlegen2"}.get(
        value, str(value)
    )


def _code_page_name(value: int) -> str:
    return {1252: "Windows Latin 1 (Western European)", 65001: "Unicode (UTF-8)"}.get(
        value, str(value)
    )


def _creator_software_name(value: int) -> str | int:
    return {
        1: "Mobigen",
        2: "Mobipocket",
        200: "Kindlegen (Windows)",
        201: "Kindlegen (Linux)",
        202: "Kindlegen (Mac)",
    }.get(value, value)


def _format_palm_datetime(unix_seconds: int) -> str:
    rendered = time.strftime("%Y:%m:%d %H:%M:%S%z", time.localtime(unix_seconds))
    return f"{rendered[:-2]}:{rendered[-2:]}"


def _format_file_size(byte_count: int) -> str | int:
    if byte_count < 1000:
        return byte_count
    return f"{round(byte_count / 1000)} kB"
