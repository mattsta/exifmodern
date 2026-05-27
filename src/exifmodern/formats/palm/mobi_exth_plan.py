"""Source-backed MOBI and EXTH first-record routing for Palm databases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MOBI_MIN_HEADER_SIZE = 274
MOBI_MARKER_OFFSET = 16
MOBI_HEADER_LENGTH_OFFSET = 20
MOBI_BOOK_NAME_OFFSET_OFFSET = 84
MOBI_BOOK_NAME_LENGTH_OFFSET = 88
MOBI_EXTH_FLAG_OFFSET = 128
MOBI_EXTH_FLAG = 0x40
MOBI_PALMDOC_HEADER_SIZE = 16
EXTH_FIXED_HEADER_SIZE = 12

type MobiExthStatus = Literal["planned", "unsupported"]
type MobiExthRoute = Literal["mobi_header", "mobi_exth_header", "invalid_mobi_header"]
type MobiExthGateCode = Literal[
    "truncated_mobi_header",
    "invalid_mobi_marker",
    "invalid_mobi_extended_header",
    "truncated_mobi_extended_header",
]

type PalmEvidenceId = str

MOBI_PROCESS_SOURCE: PalmEvidenceId = "palm.process_pdb_mobi"
EXTH_PROCESS_SOURCE: PalmEvidenceId = "palm.process_pdb_exth"

MOBI_EXTH_SOURCES = (MOBI_PROCESS_SOURCE, EXTH_PROCESS_SOURCE)


@dataclass(frozen=True)
class MobiExthGate:
    code: MobiExthGateCode
    reason: str
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class MobiBookNamePlan:
    offset: int
    length: int
    raw_value: bytes | None
    available: bool


@dataclass(frozen=True)
class MobiExthHeaderPlan:
    offset: int
    size: int
    entry_count: int
    payload_length: int


@dataclass(frozen=True)
class MobiExthPlan:
    status: MobiExthStatus
    route: MobiExthRoute
    source_tables: tuple[str, ...]
    mobi_header_length: int | None
    exth_expected: bool
    book_name: MobiBookNamePlan | None
    exth_header: MobiExthHeaderPlan | None
    output_emission_gates: tuple[MobiExthGate, ...]
    evidence_ids: tuple[PalmEvidenceId, ...]


def build_mobi_exth_plan(first_record: bytes) -> MobiExthPlan:
    if len(first_record) < MOBI_MIN_HEADER_SIZE:
        return _unsupported(
            route="invalid_mobi_header",
            code="truncated_mobi_header",
            reason="Palm.pm requires 274 bytes from the first MOBI record.",
            references=(MOBI_PROCESS_SOURCE,),
        )
    if first_record[MOBI_MARKER_OFFSET : MOBI_MARKER_OFFSET + 4] != b"MOBI":
        return _unsupported(
            route="invalid_mobi_header",
            code="invalid_mobi_marker",
            reason="Palm.pm requires the MOBI marker at byte 16 in the first record.",
            references=(MOBI_PROCESS_SOURCE,),
        )
    mobi_header_length = int.from_bytes(
        first_record[MOBI_HEADER_LENGTH_OFFSET : MOBI_HEADER_LENGTH_OFFSET + 4],
        "big",
    )
    book_name = _book_name_plan(first_record)
    exth_expected = bool(
        int.from_bytes(
            first_record[MOBI_EXTH_FLAG_OFFSET : MOBI_EXTH_FLAG_OFFSET + 4],
            "big",
        )
        & MOBI_EXTH_FLAG
    )
    if not exth_expected:
        return MobiExthPlan(
            status="planned",
            route="mobi_header",
            source_tables=("Image::ExifTool::Palm::MOBI",),
            mobi_header_length=mobi_header_length,
            exth_expected=False,
            book_name=book_name,
            exth_header=None,
            output_emission_gates=(),
            evidence_ids=(MOBI_PROCESS_SOURCE,),
        )
    return _exth_plan(first_record, mobi_header_length, book_name)


def _book_name_plan(first_record: bytes) -> MobiBookNamePlan:
    offset = int.from_bytes(
        first_record[MOBI_BOOK_NAME_OFFSET_OFFSET : MOBI_BOOK_NAME_OFFSET_OFFSET + 4],
        "big",
    )
    length = int.from_bytes(
        first_record[MOBI_BOOK_NAME_LENGTH_OFFSET : MOBI_BOOK_NAME_LENGTH_OFFSET + 4],
        "big",
    )
    end = offset + length
    if length == 0 or offset >= len(first_record) or end > len(first_record):
        return MobiBookNamePlan(offset, length, None, False)
    return MobiBookNamePlan(offset, length, first_record[offset:end], True)


def _exth_plan(
    first_record: bytes,
    mobi_header_length: int,
    book_name: MobiBookNamePlan,
) -> MobiExthPlan:
    exth_offset = mobi_header_length + MOBI_PALMDOC_HEADER_SIZE
    if len(first_record) < exth_offset + EXTH_FIXED_HEADER_SIZE:
        return _unsupported(
            route="mobi_exth_header",
            code="invalid_mobi_extended_header",
            reason="Palm.pm requires a readable 12-byte EXTH header at the derived offset.",
            references=(EXTH_PROCESS_SOURCE,),
        )
    fixed_header = first_record[exth_offset : exth_offset + EXTH_FIXED_HEADER_SIZE]
    size = int.from_bytes(fixed_header[4:8], "big")
    if fixed_header[:4] != b"EXTH" or size <= EXTH_FIXED_HEADER_SIZE:
        return _unsupported(
            route="mobi_exth_header",
            code="invalid_mobi_extended_header",
            reason="Palm.pm requires the EXTH marker and a size greater than 12 bytes.",
            references=(EXTH_PROCESS_SOURCE,),
        )
    if len(first_record) < exth_offset + size:
        return _unsupported(
            route="mobi_exth_header",
            code="truncated_mobi_extended_header",
            reason="Palm.pm warns when the declared EXTH payload cannot be read.",
            references=(EXTH_PROCESS_SOURCE,),
        )
    return MobiExthPlan(
        status="planned",
        route="mobi_exth_header",
        source_tables=("Image::ExifTool::Palm::MOBI", "Image::ExifTool::Palm::EXTH"),
        mobi_header_length=mobi_header_length,
        exth_expected=True,
        book_name=book_name,
        exth_header=MobiExthHeaderPlan(
            offset=exth_offset,
            size=size,
            entry_count=int.from_bytes(fixed_header[8:12], "big"),
            payload_length=size - EXTH_FIXED_HEADER_SIZE,
        ),
        output_emission_gates=(),
        evidence_ids=MOBI_EXTH_SOURCES,
    )


def _unsupported(
    route: MobiExthRoute,
    code: MobiExthGateCode,
    reason: str,
    references: tuple[PalmEvidenceId, ...],
) -> MobiExthPlan:
    return MobiExthPlan(
        status="unsupported",
        route=route,
        source_tables=(),
        mobi_header_length=None,
        exth_expected=False,
        book_name=None,
        exth_header=None,
        output_emission_gates=(MobiExthGate(code, reason, references),),
        evidence_ids=references,
    )
