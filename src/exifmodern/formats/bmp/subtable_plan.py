"""Source-backed BMP OS/2 and extra metadata subtable routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type BmpSubtableStatus = Literal["planned", "unsupported"]
type BmpDibFamily = Literal["os2", "windows", "unknown"]
type BmpExtraRoute = Literal[
    "embedded_jpg",
    "embedded_png",
    "icc_profile",
    "linked_profile_name",
]
type BmpSubtableGateCode = Literal["unsupported_dib_header_size"]
type BmpEvidenceId = str

BMP_OS2_TABLE_SOURCE: BmpEvidenceId = "bmp.subtable.os2"
BMP_EXTRA_TABLE_SOURCE: BmpEvidenceId = "bmp.subtable.extra"


@dataclass(frozen=True)
class BmpSubtableGate:
    code: BmpSubtableGateCode
    reason: str
    evidence_ids: tuple[BmpEvidenceId, ...]


@dataclass(frozen=True)
class BmpExtraRoutePlan:
    route: BmpExtraRoute
    source_tag: str
    source_table: str


@dataclass(frozen=True)
class BmpSubtablePlan:
    status: BmpSubtableStatus
    dib_family: BmpDibFamily
    dib_version: str | None
    header_table: str | None
    extra_routes: tuple[BmpExtraRoutePlan, ...]
    output_emission_gates: tuple[BmpSubtableGate, ...]
    evidence_ids: tuple[BmpEvidenceId, ...]


def build_bmp_subtable_plan(
    dib_header_size: int,
    compression: int | None = None,
    color_space: bytes | None = None,
) -> BmpSubtablePlan:
    header_table = _header_table(dib_header_size)
    if header_table is None:
        return BmpSubtablePlan(
            status="unsupported",
            dib_family="unknown",
            dib_version=None,
            header_table=None,
            extra_routes=(),
            output_emission_gates=(
                BmpSubtableGate(
                    code="unsupported_dib_header_size",
                    reason="BMP.pm does not route this DIB header size to BMP::OS2.",
                    evidence_ids=(BMP_OS2_TABLE_SOURCE,),
                ),
            ),
            evidence_ids=(BMP_OS2_TABLE_SOURCE,),
        )
    extra_routes = _extra_routes(compression, color_space)
    references = (
        (BMP_OS2_TABLE_SOURCE, BMP_EXTRA_TABLE_SOURCE) if extra_routes else (BMP_OS2_TABLE_SOURCE,)
    )
    return BmpSubtablePlan(
        status="planned",
        dib_family="os2" if dib_header_size in {12, 64} else "windows",
        dib_version=_dib_version(dib_header_size),
        header_table=header_table,
        extra_routes=extra_routes,
        output_emission_gates=(),
        evidence_ids=references,
    )


def _header_table(dib_header_size: int) -> str | None:
    if dib_header_size in {12, 64}:
        return "Image::ExifTool::BMP::OS2"
    if dib_header_size in {40, 52, 56, 108, 124}:
        return "Image::ExifTool::BMP::Main"
    return None


def _dib_version(dib_header_size: int) -> str | None:
    versions = {
        12: "OS/2 V1",
        40: "Windows V3",
        52: "Windows V3 BITFIELDS",
        56: "Windows V3 ALPHA",
        64: "OS/2 V2",
        108: "Windows V4",
        124: "Windows V5",
    }
    return versions.get(dib_header_size)


def _extra_routes(
    compression: int | None,
    color_space: bytes | None,
) -> tuple[BmpExtraRoutePlan, ...]:
    routes: list[BmpExtraRoutePlan] = []
    if compression == 4:
        routes.append(_extra_route("embedded_jpg", "EmbeddedJPG"))
    if compression == 5:
        routes.append(_extra_route("embedded_png", "EmbeddedPNG"))
    if color_space == b"MBED":
        routes.append(_extra_route("icc_profile", "ICC_Profile"))
    if color_space == b"LINK":
        routes.append(_extra_route("linked_profile_name", "LinkedProfileName"))
    return tuple(routes)


def _extra_route(route: BmpExtraRoute, source_tag: str) -> BmpExtraRoutePlan:
    return BmpExtraRoutePlan(
        route=route,
        source_tag=source_tag,
        source_table="Image::ExifTool::BMP::Extra",
    )
