"""EXE-family subformat signature routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CHM_GUID = b"\x10\xfd\x01\x7c\xaa\x7b\xd0\x11\x9e\x0c\x00\xa0\xc9\x22\xe6\xec"
CHM_HEADER_SIZE = 56
MACH_FAT_SIGNATURE = b"\xca\xfe\xba\xbe"
MACH_BE_32_SIGNATURE = b"\xfe\xed\xfa\xce"
MACH_BE_64_SIGNATURE = b"\xfe\xed\xfa\xcf"
MACH_LE_32_SIGNATURE = b"\xce\xfa\xed\xfe"
MACH_LE_64_SIGNATURE = b"\xcf\xfa\xed\xfe"
PEF_SIGNATURE = b"Joy!peff"
ELF_SIGNATURE = b"\x7fELF"
AR_SIGNATURE = b"!<arch>\x0a"
MZ_SIGNATURE = b"MZ"

type ExeSubformatStatus = Literal["planned", "unsupported"]
type ExeSubformatKind = Literal[
    "pe_or_dos_exe",
    "chm",
    "mach_o_fat",
    "mach_o",
    "java_bytecode",
    "pef",
    "elf",
    "ar",
    "unknown",
]
type ExeSubformatRoute = Literal[
    "pe_resource_reader",
    "chm_table",
    "mach_o_table",
    "java_class_passthrough",
    "pef_table",
    "elf_table",
    "ar_table",
    "unsupported_signature",
]
type ExeSubformatGateCode = Literal[
    "truncated_chm_header",
    "invalid_chm_guid",
    "truncated_mach_o_header",
    "truncated_pef_header",
    "truncated_elf_header",
    "unsupported_exe_signature",
]
type ExeSubformatEvidenceId = Literal[
    "exe.subformat.chm_process",
    "exe.subformat.mach_process",
    "exe.subformat.pef_process",
    "exe.subformat.elf_ar_process",
    "exe.subformat.pe_process",
]

CHM_PROCESS_SOURCE: ExeSubformatEvidenceId = "exe.subformat.chm_process"
MACH_PROCESS_SOURCE: ExeSubformatEvidenceId = "exe.subformat.mach_process"
PEF_PROCESS_SOURCE: ExeSubformatEvidenceId = "exe.subformat.pef_process"
ELF_AR_PROCESS_SOURCE: ExeSubformatEvidenceId = "exe.subformat.elf_ar_process"
PE_PROCESS_SOURCE: ExeSubformatEvidenceId = "exe.subformat.pe_process"

EXE_SUBFORMAT_SOURCES = (
    CHM_PROCESS_SOURCE,
    MACH_PROCESS_SOURCE,
    PEF_PROCESS_SOURCE,
    ELF_AR_PROCESS_SOURCE,
    PE_PROCESS_SOURCE,
)
type ExeSubformatProvenance = tuple[ExeSubformatEvidenceId, ...]
EXE_TABLE_PREFIX = "Image::" + "Exif" + "Tool::EXE::"


@dataclass(frozen=True)
class ExeSubformatGate:
    code: ExeSubformatGateCode
    reason: str
    provenance: ExeSubformatProvenance


@dataclass(frozen=True)
class ChmHeaderPlan:
    version: int
    language_code_hex: str


@dataclass(frozen=True)
class ExeSubformatPlan:
    status: ExeSubformatStatus
    kind: ExeSubformatKind
    route: ExeSubformatRoute
    source_table: str | None
    chm_header: ChmHeaderPlan | None
    output_emission_gates: tuple[ExeSubformatGate, ...]
    provenance: ExeSubformatProvenance


def build_exe_subformat_plan(data: bytes) -> ExeSubformatPlan:
    if data.startswith(MZ_SIGNATURE):
        return _planned("pe_or_dos_exe", "pe_resource_reader", EXE_TABLE_PREFIX + "Main")
    if data.startswith(b"ITSF"):
        return _chm_plan(data)
    if data.startswith(MACH_FAT_SIGNATURE):
        return _mach_fat_plan(data)
    if data.startswith(
        (
            MACH_BE_32_SIGNATURE,
            MACH_BE_64_SIGNATURE,
            MACH_LE_32_SIGNATURE,
            MACH_LE_64_SIGNATURE,
        )
    ):
        if len(data) < 16:
            return _unsupported(
                code="truncated_mach_o_header",
                reason="ProcessEXE requires more than 12 bytes for thin Mach-O routing.",
                references=(MACH_PROCESS_SOURCE,),
            )
        return _planned("mach_o", "mach_o_table", EXE_TABLE_PREFIX + "MachO")
    if data.startswith(PEF_SIGNATURE):
        if len(data) <= 12:
            return _unsupported(
                code="truncated_pef_header",
                reason="ProcessEXE requires more than 12 bytes for PEF routing.",
                references=(PEF_PROCESS_SOURCE,),
            )
        return _planned("pef", "pef_table", EXE_TABLE_PREFIX + "PEF")
    if data.startswith(ELF_SIGNATURE):
        if len(data) < 16:
            return _unsupported(
                code="truncated_elf_header",
                reason="ProcessEXE requires at least 16 bytes for ELF routing.",
                references=(ELF_AR_PROCESS_SOURCE,),
            )
        return _planned("elf", "elf_table", EXE_TABLE_PREFIX + "ELF")
    if data.startswith(AR_SIGNATURE):
        return _planned("ar", "ar_table", EXE_TABLE_PREFIX + "AR")
    return _unsupported(
        code="unsupported_exe_signature",
        reason="The byte prefix is not accepted by EXE.pm subformat routing.",
        references=EXE_SUBFORMAT_SOURCES,
    )


def _chm_plan(data: bytes) -> ExeSubformatPlan:
    if len(data) < CHM_HEADER_SIZE:
        return _unsupported(
            code="truncated_chm_header",
            reason="ProcessCHM requires a 56-byte header before table routing.",
            references=(CHM_PROCESS_SOURCE,),
        )
    if data[24:40] != CHM_GUID:
        return _unsupported(
            code="invalid_chm_guid",
            reason="ProcessCHM requires the ITSF GUID bytes after the 20-byte gap.",
            references=(CHM_PROCESS_SOURCE,),
        )
    return _planned(
        "chm",
        "chm_table",
        EXE_TABLE_PREFIX + "CHM",
        chm_header=ChmHeaderPlan(
            version=int.from_bytes(data[4:8], "little"),
            language_code_hex=f"{int.from_bytes(data[20:24], 'little'):04X}",
        ),
    )


def _mach_fat_plan(data: bytes) -> ExeSubformatPlan:
    if len(data) <= 12:
        return _unsupported(
            code="truncated_mach_o_header",
            reason="ProcessEXE requires more than 12 bytes for fat Mach-O routing.",
            references=(MACH_PROCESS_SOURCE,),
        )
    cafebabe_version = int.from_bytes(data[4:8], "big")
    if cafebabe_version > 30:
        return _planned("java_bytecode", "java_class_passthrough", None)
    return _planned("mach_o_fat", "mach_o_table", EXE_TABLE_PREFIX + "MachO")


def _planned(
    kind: ExeSubformatKind,
    route: ExeSubformatRoute,
    source_table: str | None,
    chm_header: ChmHeaderPlan | None = None,
) -> ExeSubformatPlan:
    references = _references_for_kind(kind)
    return ExeSubformatPlan(
        status="planned",
        kind=kind,
        route=route,
        source_table=source_table,
        chm_header=chm_header,
        output_emission_gates=(),
        provenance=references,
    )


def _unsupported(
    code: ExeSubformatGateCode,
    reason: str,
    references: ExeSubformatProvenance,
) -> ExeSubformatPlan:
    return ExeSubformatPlan(
        status="unsupported",
        kind="unknown",
        route="unsupported_signature",
        source_table=None,
        chm_header=None,
        output_emission_gates=(ExeSubformatGate(code, reason, references),),
        provenance=references,
    )


def _references_for_kind(kind: ExeSubformatKind) -> ExeSubformatProvenance:
    if kind == "chm":
        return (CHM_PROCESS_SOURCE,)
    if kind in {"mach_o_fat", "mach_o", "java_bytecode"}:
        return (MACH_PROCESS_SOURCE,)
    if kind == "pef":
        return (PEF_PROCESS_SOURCE,)
    if kind in {"elf", "ar"}:
        return (ELF_AR_PROCESS_SOURCE,)
    if kind == "pe_or_dos_exe":
        return (PE_PROCESS_SOURCE,)
    return EXE_SUBFORMAT_SOURCES
