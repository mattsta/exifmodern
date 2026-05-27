"""GZIP value-name planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type GzipValueStatus = Literal["planned", "unknown"]
type GzipValueKind = Literal["extra_flags", "operating_system"]
type GzipValueEvidenceId = Literal["zip.gzip.value_names"]
type GzipValueProvenance = tuple[GzipValueEvidenceId, ...]

GZIP_VALUE_EVIDENCE_ID: GzipValueEvidenceId = "zip.gzip.value_names"

GZIP_EXTRA_FLAG_NAMES: dict[int, str] = {
    0: "(none)",
    2: "Maximum Compression",
    4: "Fastest Algorithm",
}
GZIP_OPERATING_SYSTEM_NAMES: dict[int, str] = {
    0: "FAT filesystem (MS-DOS, OS/2, NT/Win32)",
    1: "Amiga",
    2: "VMS (or OpenVMS)",
    3: "Unix",
    4: "VM/CMS",
    5: "Atari TOS",
    6: "HPFS filesystem (OS/2, NT)",
    7: "Macintosh",
    8: "Z-System",
    9: "CP/M",
    10: "TOPS-20",
    11: "NTFS filesystem (NT)",
    12: "QDOS",
    13: "Acorn RISCOS",
    255: "unknown",
}


@dataclass(frozen=True)
class GzipValuePlan:
    status: GzipValueStatus
    value_kind: GzipValueKind
    raw_value: int
    display_name: str | None
    provenance: GzipValueProvenance


def build_gzip_value_plan(value_kind: GzipValueKind, raw_value: int) -> GzipValuePlan:
    table = GZIP_EXTRA_FLAG_NAMES if value_kind == "extra_flags" else GZIP_OPERATING_SYSTEM_NAMES
    display_name = table.get(raw_value)
    return GzipValuePlan(
        status="planned" if display_name is not None else "unknown",
        value_kind=value_kind,
        raw_value=raw_value,
        display_name=display_name,
        provenance=(GZIP_VALUE_EVIDENCE_ID,),
    )
