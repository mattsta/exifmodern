"""Source-backed Portable FloatMap metadata transaction planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

type PfmColorSpace = Literal["RGB", "Monochrome"]
type PfmByteOrder = Literal["Big-endian", "Little-endian"]
type PfmBlockerCode = Literal["invalid_header", "rewrite_not_supported"]


@dataclass(frozen=True)
class PfmRewriteRequest:
    tag_name: str
    value: str | int | float


@dataclass(frozen=True)
class PfmBlocker:
    code: PfmBlockerCode
    detail: str
    source_symbol: str


@dataclass(frozen=True)
class PfmMetadataTransactionPlan:
    color_space: PfmColorSpace | None
    image_width: int | None
    image_height: int | None
    byte_order: PfmByteOrder | None
    scale: float | None
    blockers: tuple[PfmBlocker, ...]
    source_symbols: tuple[str, ...]
    mime_type: str | None
    can_mutate_metadata: bool
    can_emit_metadata: bool


_PFM_RE = re.compile(rb"^(P[Ff])\x0a(\d+) (\d+)\x0a([-+0-9.]+)\x0a")
_SOURCE_SYMBOLS = ("Image::ExifTool::Other::PFM", "ProcessPFM2")


def build_pfm_metadata_transaction_plan(
    header: bytes,
    *,
    rewrite_requests: tuple[PfmRewriteRequest, ...] = (),
) -> PfmMetadataTransactionPlan:
    match = _PFM_RE.match(header[:256])
    if match is None:
        return _blocked_plan(
            PfmBlocker(
                code="invalid_header",
                detail=(
                    "ProcessPFM2 requires PF/Pf, dimensions, and scale in the first header lines."
                ),
                source_symbol="ProcessPFM2",
            )
        )
    marker = match.group(1)
    scale = float(match.group(4).decode("ascii"))
    blockers: tuple[PfmBlocker, ...] = ()
    if rewrite_requests:
        blockers = (
            PfmBlocker(
                code="rewrite_not_supported",
                detail="Other.pm reads PFM headers and does not define a writer.",
                source_symbol="ProcessPFM2",
            ),
        )
    return PfmMetadataTransactionPlan(
        color_space="RGB" if marker == b"PF" else "Monochrome",
        image_width=int(match.group(2)),
        image_height=int(match.group(3)),
        byte_order="Big-endian" if scale > 0 else "Little-endian",
        scale=scale,
        blockers=blockers,
        source_symbols=_SOURCE_SYMBOLS,
        mime_type="image/x-pfm",
        can_mutate_metadata=False,
        can_emit_metadata=not blockers,
    )


def _blocked_plan(blocker: PfmBlocker) -> PfmMetadataTransactionPlan:
    return PfmMetadataTransactionPlan(
        color_space=None,
        image_width=None,
        image_height=None,
        byte_order=None,
        scale=None,
        blockers=(blocker,),
        source_symbols=_SOURCE_SYMBOLS,
        mime_type=None,
        can_mutate_metadata=False,
        can_emit_metadata=False,
    )
