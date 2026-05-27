"""Parsing plan for macOS stat FileCreateDate output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

type MacOSFileCreateDateStatus = Literal["planned", "unsupported"]
type MacOSFileCreateDateGateCode = Literal["empty_stat_output", "invalid_stat_time_zone"]
type MacOSFileCreateDateEvidenceId = Literal["macos.file_create_date.stat_timezone"]
type MacOSFileCreateDateProvenance = tuple[MacOSFileCreateDateEvidenceId, ...]

FILE_CREATE_DATE_EVIDENCE_ID: MacOSFileCreateDateEvidenceId = "macos.file_create_date.stat_timezone"

STAT_TIME_ZONE_PATTERN = re.compile(r"([-+]\d{2})(\d{2})\s*$")


@dataclass(frozen=True)
class MacOSFileCreateDateGate:
    code: MacOSFileCreateDateGateCode
    reason: str
    provenance: MacOSFileCreateDateProvenance


@dataclass(frozen=True)
class MacOSFileCreateDatePlan:
    status: MacOSFileCreateDateStatus
    raw_output: str
    file_create_date: str | None
    output_emission_gates: tuple[MacOSFileCreateDateGate, ...]
    provenance: MacOSFileCreateDateProvenance


def build_macos_file_create_date_plan(stat_output: str) -> MacOSFileCreateDatePlan:
    stripped = stat_output.strip()
    if not stripped:
        return _unsupported(
            "empty_stat_output",
            "MacOS.pm requires non-empty stat output for FileCreateDate.",
            stat_output,
        )
    match = STAT_TIME_ZONE_PATTERN.search(stripped)
    if match is None:
        return _unsupported(
            "invalid_stat_time_zone",
            "MacOS.pm requires a trailing numeric timezone in HHMM form.",
            stat_output,
        )
    normalized = STAT_TIME_ZONE_PATTERN.sub(r"\1:\2", stripped)
    return MacOSFileCreateDatePlan(
        status="planned",
        raw_output=stat_output,
        file_create_date=normalized,
        output_emission_gates=(),
        provenance=(FILE_CREATE_DATE_EVIDENCE_ID,),
    )


def _unsupported(
    code: MacOSFileCreateDateGateCode,
    reason: str,
    raw_output: str,
) -> MacOSFileCreateDatePlan:
    return MacOSFileCreateDatePlan(
        status="unsupported",
        raw_output=raw_output,
        file_create_date=None,
        output_emission_gates=(
            MacOSFileCreateDateGate(code, reason, (FILE_CREATE_DATE_EVIDENCE_ID,)),
        ),
        provenance=(FILE_CREATE_DATE_EVIDENCE_ID,),
    )
