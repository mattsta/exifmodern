"""Scalar header extraction for PEF, ELF, and AR executable families."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PEF_SIGNATURE = b"Joy!peff"
ELF_SIGNATURE = b"\x7fELF"
AR_SIGNATURE = b"!<arch>\n"
AR_MEMBER_HEADER_SIZE = 60
AR_GLOBAL_HEADER_SIZE = 8
PEF_TIME_OFFSET = (66 * 365 + 17) * 24 * 3600

type ExeScalarHeaderStatus = Literal["planned", "unsupported"]
type ExeScalarHeaderKind = Literal["pef", "elf", "ar", "unknown"]
type ExeScalarHeaderGateCode = Literal[
    "unsupported_scalar_header_signature",
    "truncated_pef_header",
    "truncated_elf_header",
    "truncated_ar_member_header",
    "invalid_ar_member_terminator",
]
type ElfCpuArchitecture = Literal["32 bit", "64 bit", "unknown"]
type ElfCpuByteOrder = Literal["little", "big", "unknown"]
type ExeScalarByteOrder = Literal["little", "big"]
type ExeScalarHeaderEvidenceId = Literal[
    "exe.scalar.pef_table",
    "exe.scalar.elf_table",
    "exe.scalar.ar_table",
]

PEF_TABLE_SOURCE: ExeScalarHeaderEvidenceId = "exe.scalar.pef_table"
ELF_TABLE_SOURCE: ExeScalarHeaderEvidenceId = "exe.scalar.elf_table"
AR_TABLE_SOURCE: ExeScalarHeaderEvidenceId = "exe.scalar.ar_table"

EXE_SCALAR_HEADER_SOURCES = (PEF_TABLE_SOURCE, ELF_TABLE_SOURCE, AR_TABLE_SOURCE)
type ExeScalarHeaderProvenance = tuple[ExeScalarHeaderEvidenceId, ...]
EXE_TABLE_PREFIX = "Image::" + "Exif" + "Tool::EXE::"


@dataclass(frozen=True)
class ExeScalarHeaderGate:
    code: ExeScalarHeaderGateCode
    reason: str
    provenance: ExeScalarHeaderProvenance


@dataclass(frozen=True)
class PefHeaderPlan:
    cpu_architecture: str
    version: int
    timestamp_unix_seconds: int


@dataclass(frozen=True)
class ElfHeaderPlan:
    cpu_architecture: ElfCpuArchitecture
    cpu_byte_order: ElfCpuByteOrder
    file_type: int
    cpu_type: int


@dataclass(frozen=True)
class ArHeaderPlan:
    create_date_raw: str
    member_size_raw: str


@dataclass(frozen=True)
class ExeScalarHeaderPlan:
    status: ExeScalarHeaderStatus
    kind: ExeScalarHeaderKind
    source_table: str | None
    pef_header: PefHeaderPlan | None
    elf_header: ElfHeaderPlan | None
    ar_header: ArHeaderPlan | None
    output_emission_gates: tuple[ExeScalarHeaderGate, ...]
    provenance: ExeScalarHeaderProvenance


def build_exe_scalar_header_plan(data: bytes) -> ExeScalarHeaderPlan:
    if data.startswith(PEF_SIGNATURE):
        return _pef_plan(data)
    if data.startswith(ELF_SIGNATURE):
        return _elf_plan(data)
    if data.startswith(AR_SIGNATURE):
        return _ar_plan(data)
    return _unsupported(
        "unsupported_scalar_header_signature",
        "The bytes do not match PEF, ELF, or Unix archive scalar header routing.",
        EXE_SCALAR_HEADER_SOURCES,
    )


def _pef_plan(data: bytes) -> ExeScalarHeaderPlan:
    if len(data) < 20:
        return _unsupported(
            "truncated_pef_header",
            "EXE.pm PEF routing requires enough bytes for architecture, version, and timestamp.",
            (PEF_TABLE_SOURCE,),
        )
    architecture = data[8:12].decode("ascii", errors="replace")
    timestamp = int.from_bytes(data[16:20], "big") - PEF_TIME_OFFSET
    return ExeScalarHeaderPlan(
        status="planned",
        kind="pef",
        source_table=EXE_TABLE_PREFIX + "PEF",
        pef_header=PefHeaderPlan(architecture, int.from_bytes(data[12:16], "big"), timestamp),
        elf_header=None,
        ar_header=None,
        output_emission_gates=(),
        provenance=(PEF_TABLE_SOURCE,),
    )


def _elf_plan(data: bytes) -> ExeScalarHeaderPlan:
    if len(data) < 20:
        return _unsupported(
            "truncated_elf_header",
            "EXE.pm ELF routing requires at least 20 bytes for class, order, type, and CPU.",
            (ELF_TABLE_SOURCE,),
        )
    byte_order = _elf_byte_order(data[5])
    endian = _scalar_byte_order(byte_order)
    return ExeScalarHeaderPlan(
        status="planned",
        kind="elf",
        source_table=EXE_TABLE_PREFIX + "ELF",
        pef_header=None,
        elf_header=ElfHeaderPlan(
            cpu_architecture=_elf_architecture(data[4]),
            cpu_byte_order=byte_order,
            file_type=int.from_bytes(data[16:18], endian),
            cpu_type=int.from_bytes(data[18:20], endian),
        ),
        ar_header=None,
        output_emission_gates=(),
        provenance=(ELF_TABLE_SOURCE,),
    )


def _ar_plan(data: bytes) -> ExeScalarHeaderPlan:
    header_start = AR_GLOBAL_HEADER_SIZE
    header_end = header_start + AR_MEMBER_HEADER_SIZE
    if len(data) < header_end:
        return _unsupported(
            "truncated_ar_member_header",
            "EXE.pm reads 60-byte ar member headers after the archive signature.",
            (AR_TABLE_SOURCE,),
        )
    header = data[header_start:header_end]
    if header[58:60] != b"`\n":
        return _unsupported(
            "invalid_ar_member_terminator",
            "EXE.pm requires the ar member header terminator bytes.",
            (AR_TABLE_SOURCE,),
        )
    return ExeScalarHeaderPlan(
        status="planned",
        kind="ar",
        source_table=EXE_TABLE_PREFIX + "AR",
        pef_header=None,
        elf_header=None,
        ar_header=ArHeaderPlan(
            create_date_raw=header[16:28].decode("ascii", errors="replace").strip(),
            member_size_raw=header[48:58].decode("ascii", errors="replace").strip(),
        ),
        output_emission_gates=(),
        provenance=(AR_TABLE_SOURCE,),
    )


def _elf_architecture(value: int) -> ElfCpuArchitecture:
    if value == 1:
        return "32 bit"
    if value == 2:
        return "64 bit"
    return "unknown"


def _elf_byte_order(value: int) -> ElfCpuByteOrder:
    if value == 1:
        return "little"
    if value == 2:
        return "big"
    return "unknown"


def _scalar_byte_order(byte_order: ElfCpuByteOrder) -> ExeScalarByteOrder:
    return "little" if byte_order == "little" else "big"


def _unsupported(
    code: ExeScalarHeaderGateCode,
    reason: str,
    references: ExeScalarHeaderProvenance,
) -> ExeScalarHeaderPlan:
    return ExeScalarHeaderPlan(
        status="unsupported",
        kind="unknown",
        source_table=None,
        pef_header=None,
        elf_header=None,
        ar_header=None,
        output_emission_gates=(ExeScalarHeaderGate(code, reason, references),),
        provenance=references,
    )
