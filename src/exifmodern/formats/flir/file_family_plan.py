"""FLIR FFF/AFF/FPF file-family routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.flir.provenance import (
    FLIR_AFF_SOURCE,
    FLIR_FFF_SOURCE,
    FLIR_FPF_SOURCE,
    FLIR_PROCESS_FPF_SOURCE,
    SourceAnchor,
)

FPF_HEADER_SIZE = 892
FPF_SIGNATURE = b"FPF Public Image Format\0"
FFF_SIGNATURE = b"FFF\0"
AFF_SIGNATURE = b"AFF\0"

type FlirFileFamilyStatus = Literal["planned", "unsupported"]
type FlirFileFamilyKind = Literal["fff", "aff", "fpf", "unknown"]
type FlirFileFamilyRoute = Literal["fff_table", "aff_table", "fpf_table", "unsupported_signature"]
type FlirFileFamilyGateCode = Literal[
    "truncated_fpf_header",
    "unsupported_flir_signature",
]
type FlirFileFamilyByteOrder = Literal["little", "big", "undetermined"]
type FlirResolvedByteOrder = Literal["little", "big"]

FLIR_FILE_FAMILY_SOURCES = (
    FLIR_FFF_SOURCE,
    FLIR_AFF_SOURCE,
    FLIR_FPF_SOURCE,
    FLIR_PROCESS_FPF_SOURCE,
)
type FlirFileFamilyProvenance = tuple[SourceAnchor, ...]
FLIR_TABLE_PREFIX = "Image::" + "Exif" + "Tool::FLIR::"


@dataclass(frozen=True)
class FlirFileFamilyGate:
    code: FlirFileFamilyGateCode
    reason: str
    provenance: FlirFileFamilyProvenance


@dataclass(frozen=True)
class FlirFpfHeaderPlan:
    version: int
    image_data_offset: int
    image_type: int
    image_pixel_format: int
    image_width: int
    image_height: int
    byte_order: FlirFileFamilyByteOrder


@dataclass(frozen=True)
class FlirFileFamilyPlan:
    status: FlirFileFamilyStatus
    family: FlirFileFamilyKind
    route: FlirFileFamilyRoute
    source_table: str | None
    fpf_header: FlirFpfHeaderPlan | None
    output_emission_gates: tuple[FlirFileFamilyGate, ...]
    provenance: FlirFileFamilyProvenance


def build_flir_file_family_plan(data: bytes) -> FlirFileFamilyPlan:
    if data.startswith(FFF_SIGNATURE):
        return _planned("fff", "fff_table", FLIR_TABLE_PREFIX + "FFF", None)
    if data.startswith(AFF_SIGNATURE):
        return _planned("aff", "aff_table", FLIR_TABLE_PREFIX + "AFF", None)
    if data.startswith(FPF_SIGNATURE):
        return _fpf_plan(data)
    return _unsupported(
        code="unsupported_flir_signature",
        reason="FLIR.pm accepts FFF, AFF, or FPF family signatures for file-level routing.",
        references=FLIR_FILE_FAMILY_SOURCES,
    )


def _fpf_plan(data: bytes) -> FlirFileFamilyPlan:
    if len(data) < FPF_HEADER_SIZE:
        return _unsupported(
            code="truncated_fpf_header",
            reason="ProcessFPF requires an 892-byte FPF header before table routing.",
            references=(FLIR_PROCESS_FPF_SOURCE,),
        )
    byte_order = _fpf_byte_order(data)
    header = FlirFpfHeaderPlan(
        version=_read_u32(data, 0x20, byte_order),
        image_data_offset=_read_u32(data, 0x24, byte_order),
        image_type=_read_u16(data, 0x28, byte_order),
        image_pixel_format=_read_u16(data, 0x2A, byte_order),
        image_width=_read_u16(data, 0x2C, byte_order),
        image_height=_read_u16(data, 0x2E, byte_order),
        byte_order=byte_order,
    )
    return _planned("fpf", "fpf_table", FLIR_TABLE_PREFIX + "FPF", header)


def _fpf_byte_order(data: bytes) -> FlirResolvedByteOrder:
    little_version = int.from_bytes(data[0x20:0x24], "little")
    return "little" if little_version & 0xFFFF else "big"


def _read_u16(data: bytes, offset: int, byte_order: FlirResolvedByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 2], byte_order)


def _read_u32(data: bytes, offset: int, byte_order: FlirResolvedByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order)


def _planned(
    family: FlirFileFamilyKind,
    route: FlirFileFamilyRoute,
    source_table: str,
    fpf_header: FlirFpfHeaderPlan | None,
) -> FlirFileFamilyPlan:
    return FlirFileFamilyPlan(
        status="planned",
        family=family,
        route=route,
        source_table=source_table,
        fpf_header=fpf_header,
        output_emission_gates=(),
        provenance=_references_for_family(family),
    )


def _unsupported(
    code: FlirFileFamilyGateCode,
    reason: str,
    references: FlirFileFamilyProvenance,
) -> FlirFileFamilyPlan:
    return FlirFileFamilyPlan(
        status="unsupported",
        family="unknown",
        route="unsupported_signature",
        source_table=None,
        fpf_header=None,
        output_emission_gates=(FlirFileFamilyGate(code, reason, references),),
        provenance=references,
    )


def _references_for_family(family: FlirFileFamilyKind) -> FlirFileFamilyProvenance:
    if family == "fff":
        return (FLIR_FFF_SOURCE,)
    if family == "aff":
        return (FLIR_AFF_SOURCE,)
    if family == "fpf":
        return (FLIR_FPF_SOURCE, FLIR_PROCESS_FPF_SOURCE)
    return FLIR_FILE_FAMILY_SOURCES
