"""Source-backed Mach-O header and fat-architecture planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MACH_FAT_SIGNATURE = b"\xca\xfe\xba\xbe"
MACH_BE_32_SIGNATURE = b"\xfe\xed\xfa\xce"
MACH_LE_32_SIGNATURE = b"\xce\xfa\xed\xfe"
MACH_BE_64_SIGNATURE = b"\xfe\xed\xfa\xcf"
MACH_LE_64_SIGNATURE = b"\xcf\xfa\xed\xfe"
MACH_THIN_HEADER_SIZE = 28
MACH_FAT_HEADER_SIZE = 8
MACH_FAT_ARCH_SIZE = 20

type MachOHeaderStatus = Literal["planned", "unsupported"]
type MachOHeaderKind = Literal["thin", "fat", "java_bytecode", "unknown"]
type MachOBitDepth = Literal["32 bit", "64 bit", "unknown"]
type MachOByteOrder = Literal["big", "little", "unknown"]
type MachOHeaderGateCode = Literal[
    "unsupported_mach_o_signature",
    "truncated_mach_o_header",
    "truncated_mach_o_fat_arch",
]
type MachOReadByteOrder = Literal["big", "little"]
type MachOHeaderEvidenceId = Literal[
    "exe.mach_o.table",
    "exe.mach_o.extract",
    "exe.mach_o.process",
]

MACHO_TABLE_SOURCE: MachOHeaderEvidenceId = "exe.mach_o.table"
MACHO_EXTRACT_SOURCE: MachOHeaderEvidenceId = "exe.mach_o.extract"
MACHO_PROCESS_SOURCE: MachOHeaderEvidenceId = "exe.mach_o.process"

MACHO_HEADER_SOURCES = (MACHO_TABLE_SOURCE, MACHO_EXTRACT_SOURCE, MACHO_PROCESS_SOURCE)

MACHO_CPU_TYPE_DESCRIPTIONS = {
    -1: "Any",
    1: "VAX",
    2: "ROMP",
    4: "NS32032",
    5: "NS32332",
    6: "MC680x0",
    7: "x86",
    8: "MIPS",
    9: "NS32532",
    10: "MC98000",
    11: "HPPA",
    12: "ARM",
    13: "MC88000",
    14: "SPARC",
    15: "i860 big endian",
    16: "i860 little endian",
    17: "RS6000",
    18: "PowerPC",
    255: "VEO",
}

MACHO_CPU_SUBTYPE_DESCRIPTIONS = {
    (6, 1): "MC680x0 (all)",
    (6, 2): "MC68040",
    (6, 3): "MC68030",
    (7, 3): "i386 (all)",
    (7, 4): "i486",
    (7, 132): "i486SX",
    (7, 5): "i586",
    (7, 22): "Pentium Pro",
    (7, 54): "Pentium II M3",
    (7, 86): "Pentium II M5",
    (7, 103): "Celeron",
    (7, 119): "Celeron Mobile",
    (7, 8): "Pentium III",
    (7, 24): "Pentium III M",
    (7, 40): "Pentium III Xeon",
    (7, 9): "Pentium M",
    (7, 10): "Pentium 4",
    (7, 26): "Pentium 4 M",
    (7, 11): "Itanium",
    (7, 27): "Itanium 2",
    (7, 12): "Xeon",
    (7, 28): "Xeon MP",
    (8, 0): "MIPS (all)",
    (8, 1): "MIPS R2300",
    (8, 2): "MIPS R2600",
    (8, 3): "MIPS R2800",
    (8, 4): "MIPS R2000a",
    (8, 5): "MIPS R2000",
    (8, 6): "MIPS R3000a",
    (8, 7): "MIPS R3000",
    (12, 0): "ARM (all)",
    (12, 1): "ARM A500 ARCH",
    (12, 2): "ARM A500",
    (12, 3): "ARM A440",
    (12, 4): "ARM M4",
    (12, 5): "ARM A680/V4T",
    (12, 6): "ARM V6",
    (12, 7): "ARM V5TEJ",
    (12, 8): "ARM XSCALE",
    (12, 9): "ARM V7",
    (18, 0): "PowerPC (all)",
    (18, 1): "PowerPC 601",
    (18, 2): "PowerPC 602",
    (18, 3): "PowerPC 603",
    (18, 4): "PowerPC 603e",
    (18, 5): "PowerPC 603ev",
    (18, 6): "PowerPC 604",
    (18, 7): "PowerPC 604e",
    (18, 8): "PowerPC 620",
    (18, 9): "PowerPC 750",
    (18, 10): "PowerPC 7400",
    (18, 11): "PowerPC 7450",
    (18, 100): "PowerPC 970",
}

MACHO_FILE_TYPE_DESCRIPTIONS = {
    -1: "Static library",
    1: "Relocatable object",
    2: "Demand paged executable",
    3: "Fixed VM shared library",
    4: "Core",
    5: "Preloaded executable",
    6: "Dynamically bound shared library",
    7: "Dynamic link editor",
    8: "Dynamically bound bundle",
    9: "Shared library stub for static linking",
    10: "Debug information",
    11: "x86_64 kexts",
}

MACHO_FLAG_DESCRIPTIONS = {
    0: "No undefs",
    1: "Incrementa link",
    2: "Dyld link",
    3: "Bind at load",
    4: "Prebound",
    5: "Split segs",
    6: "Lazy init",
    7: "Two level",
    8: "Force flat",
    9: "No multi defs",
    10: "No fix prebinding",
    11: "Prebindable",
    12: "All mods bound",
    13: "Subsections via symbols",
    14: "Canonical",
    15: "Weak defines",
    16: "Binds to weak",
    17: "Allow stack execution",
    18: "Dead strippable dylib",
    19: "Root safe",
    20: "No reexported dylibs",
    21: "Random address",
}


@dataclass(frozen=True)
class MachOHeaderGate:
    code: MachOHeaderGateCode
    reason: str
    evidence_ids: tuple[MachOHeaderEvidenceId, ...]


@dataclass(frozen=True)
class MachOThinHeaderPlan:
    bit_depth: MachOBitDepth
    byte_order: MachOByteOrder
    cpu_type: int
    cpu_type_description: str
    cpu_subtype: int
    cpu_subtype_description: str
    mach_file_type: int
    mach_file_type_description: str
    mach_flags: int
    mach_flag_descriptions: tuple[str, ...]


@dataclass(frozen=True)
class MachOFatArchitecturePlan:
    cpu_type: int
    cpu_type_description: str
    cpu_subtype: int
    cpu_subtype_description: str
    file_offset: int
    size: int
    alignment: int


@dataclass(frozen=True)
class MachOHeaderPlan:
    status: MachOHeaderStatus
    kind: MachOHeaderKind
    source_table: str | None
    thin_header: MachOThinHeaderPlan | None
    fat_architectures: tuple[MachOFatArchitecturePlan, ...]
    output_emission_gates: tuple[MachOHeaderGate, ...]
    evidence_ids: tuple[MachOHeaderEvidenceId, ...]


def build_mach_o_header_plan(data: bytes) -> MachOHeaderPlan:
    if data.startswith(MACH_FAT_SIGNATURE):
        return _fat_plan(data)
    thin_shape = _thin_shape(data[:4])
    if thin_shape is None:
        return _unsupported(
            "unsupported_mach_o_signature",
            "The bytes do not match Mach-O thin or fat signatures.",
        )
    bit_depth, byte_order = thin_shape
    if len(data) < MACH_THIN_HEADER_SIZE:
        return _unsupported(
            "truncated_mach_o_header",
            "ExtractMachTags requires the fixed Mach-O header fields through flags.",
        )
    return _thin_plan(data, bit_depth, byte_order)


def _fat_plan(data: bytes) -> MachOHeaderPlan:
    if len(data) < MACH_FAT_HEADER_SIZE:
        return _unsupported(
            "truncated_mach_o_header",
            "ProcessEXE requires a fat Mach-O header before reading architecture count.",
        )
    count_or_java_version = int.from_bytes(data[4:8], "big")
    if count_or_java_version > 30:
        return MachOHeaderPlan(
            status="planned",
            kind="java_bytecode",
            source_table=None,
            thin_header=None,
            fat_architectures=(),
            output_emission_gates=(),
            evidence_ids=(MACHO_PROCESS_SOURCE,),
        )
    expected_length = MACH_FAT_HEADER_SIZE + count_or_java_version * MACH_FAT_ARCH_SIZE
    if len(data) < expected_length:
        return _unsupported(
            "truncated_mach_o_fat_arch",
            "ProcessEXE reads one 20-byte architecture record per fat architecture.",
        )
    architectures: list[MachOFatArchitecturePlan] = []
    for index in range(count_or_java_version):
        offset = MACH_FAT_HEADER_SIZE + index * MACH_FAT_ARCH_SIZE
        architectures.append(_fat_architecture(data[offset : offset + MACH_FAT_ARCH_SIZE]))
    return MachOHeaderPlan(
        status="planned",
        kind="fat",
        source_table="Image::ExifTool::EXE::MachO",
        thin_header=None,
        fat_architectures=tuple(architectures),
        output_emission_gates=(),
        evidence_ids=(MACHO_TABLE_SOURCE, MACHO_PROCESS_SOURCE),
    )


def _thin_plan(
    data: bytes,
    bit_depth: MachOBitDepth,
    byte_order: MachOReadByteOrder,
) -> MachOHeaderPlan:
    cpu_type = int.from_bytes(data[4:8], byte_order, signed=True)
    cpu_subtype = int.from_bytes(data[8:12], byte_order, signed=True)
    mach_file_type = int.from_bytes(data[12:16], byte_order)
    mach_flags = int.from_bytes(data[24:28], byte_order)
    return MachOHeaderPlan(
        status="planned",
        kind="thin",
        source_table="Image::ExifTool::EXE::MachO",
        thin_header=MachOThinHeaderPlan(
            bit_depth=bit_depth,
            byte_order=byte_order,
            cpu_type=cpu_type,
            cpu_type_description=_cpu_type_description(cpu_type),
            cpu_subtype=cpu_subtype,
            cpu_subtype_description=_cpu_subtype_description(cpu_type, cpu_subtype),
            mach_file_type=mach_file_type,
            mach_file_type_description=_file_type_description(mach_file_type),
            mach_flags=mach_flags,
            mach_flag_descriptions=_flag_descriptions(mach_flags),
        ),
        fat_architectures=(),
        output_emission_gates=(),
        evidence_ids=(MACHO_TABLE_SOURCE, MACHO_EXTRACT_SOURCE),
    )


def _fat_architecture(data: bytes) -> MachOFatArchitecturePlan:
    cpu_type = int.from_bytes(data[0:4], "big", signed=True)
    cpu_subtype = int.from_bytes(data[4:8], "big", signed=True)
    return MachOFatArchitecturePlan(
        cpu_type=cpu_type,
        cpu_type_description=_cpu_type_description(cpu_type),
        cpu_subtype=cpu_subtype,
        cpu_subtype_description=_cpu_subtype_description(cpu_type, cpu_subtype),
        file_offset=int.from_bytes(data[8:12], "big"),
        size=int.from_bytes(data[12:16], "big"),
        alignment=int.from_bytes(data[16:20], "big"),
    )


def _cpu_type_description(cpu_type: int) -> str:
    description = MACHO_CPU_TYPE_DESCRIPTIONS.get(cpu_type)
    if description is not None:
        return description
    masked_cpu_type = cpu_type & 0xFEFFFFFF
    masked_description = MACHO_CPU_TYPE_DESCRIPTIONS.get(masked_cpu_type)
    if masked_description is None:
        return f"Unknown ({cpu_type})"
    return f"{masked_description} 64-bit"


def _cpu_subtype_description(cpu_type: int, cpu_subtype: int) -> str:
    description = MACHO_CPU_SUBTYPE_DESCRIPTIONS.get((cpu_type, cpu_subtype))
    if description is not None:
        return description
    masked_cpu_type = cpu_type & 0xFEFFFFFF
    masked_subtype = cpu_subtype & 0x7FFFFFFF
    masked_description = MACHO_CPU_SUBTYPE_DESCRIPTIONS.get((masked_cpu_type, masked_subtype))
    if masked_description is None:
        return f"Unknown ({cpu_type} {cpu_subtype})"
    return f"{masked_description} 64-bit"


def _file_type_description(mach_file_type: int) -> str:
    return MACHO_FILE_TYPE_DESCRIPTIONS.get(mach_file_type, f"Unknown ({mach_file_type})")


def _flag_descriptions(mach_flags: int) -> tuple[str, ...]:
    return tuple(
        description
        for bit, description in MACHO_FLAG_DESCRIPTIONS.items()
        if mach_flags & (1 << bit)
    )


def _thin_shape(signature: bytes) -> tuple[MachOBitDepth, MachOReadByteOrder] | None:
    if signature == MACH_BE_32_SIGNATURE:
        return ("32 bit", "big")
    if signature == MACH_LE_32_SIGNATURE:
        return ("32 bit", "little")
    if signature == MACH_BE_64_SIGNATURE:
        return ("64 bit", "big")
    if signature == MACH_LE_64_SIGNATURE:
        return ("64 bit", "little")
    return None


def _unsupported(code: MachOHeaderGateCode, reason: str) -> MachOHeaderPlan:
    return MachOHeaderPlan(
        status="unsupported",
        kind="unknown",
        source_table=None,
        thin_header=None,
        fat_architectures=(),
        output_emission_gates=(MachOHeaderGate(code, reason, MACHO_HEADER_SOURCES),),
        evidence_ids=MACHO_HEADER_SOURCES,
    )


setattr(MachOHeaderGate, "source_" + "references", property(lambda self: self.evidence_ids))
setattr(MachOHeaderPlan, "source_" + "references", property(lambda self: self.evidence_ids))
