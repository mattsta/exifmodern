"""FLIR FPF coded value planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type FlirFpfValueStatus = Literal["planned", "unknown"]
type FlirFpfValueKind = Literal["image_type", "pixel_format"]
type FlirFpfValueEvidenceId = Literal["flir.fpf.value_names"]
type FlirFpfValueProvenance = tuple[FlirFpfValueEvidenceId, ...]

FLIR_FPF_VALUE_EVIDENCE_ID: FlirFpfValueEvidenceId = "flir.fpf.value_names"

FPF_IMAGE_TYPE_NAMES: dict[int, str] = {
    0: "Temperature",
    1: "Temperature Difference",
    2: "Object Signal",
    3: "Object Signal Difference",
}
FPF_PIXEL_FORMAT_NAMES: dict[int, str] = {
    0: "2-byte short integer",
    1: "4-byte long integer",
    2: "4-byte float",
    3: "8-byte double",
}


@dataclass(frozen=True)
class FlirFpfValuePlan:
    status: FlirFpfValueStatus
    value_kind: FlirFpfValueKind
    raw_value: int
    display_name: str | None
    provenance: FlirFpfValueProvenance


def build_flir_fpf_value_plan(value_kind: FlirFpfValueKind, raw_value: int) -> FlirFpfValuePlan:
    table = FPF_IMAGE_TYPE_NAMES if value_kind == "image_type" else FPF_PIXEL_FORMAT_NAMES
    display_name = table.get(raw_value)
    return FlirFpfValuePlan(
        status="planned" if display_name is not None else "unknown",
        value_kind=value_kind,
        raw_value=raw_value,
        display_name=display_name,
        provenance=(FLIR_FPF_VALUE_EVIDENCE_ID,),
    )
