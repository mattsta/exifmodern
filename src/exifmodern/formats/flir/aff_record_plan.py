"""FLIR AFF1/AFF5 sensor record planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.flir.provenance import FLIR_AFF1_SOURCE, FLIR_AFF5_SOURCE, SourceAnchor

type FlirAffRecordStatus = Literal["planned", "unsupported"]
type FlirAffRecordKind = Literal["aff1", "aff5", "unknown"]
type FlirAffByteOrder = Literal["little", "big"]
type FlirAffRecordGateCode = Literal[
    "unsupported_aff_record_type",
    "truncated_aff1_record",
    "truncated_aff5_record",
]

FLIR_AFF_RECORD_SOURCES = (FLIR_AFF1_SOURCE, FLIR_AFF5_SOURCE)
type FlirAffRecordProvenance = tuple[SourceAnchor, ...]
FLIR_TABLE_PREFIX = "Image::" + "Exif" + "Tool::FLIR::"


@dataclass(frozen=True)
class FlirAffRecordGate:
    code: FlirAffRecordGateCode
    reason: str
    provenance: FlirAffRecordProvenance


@dataclass(frozen=True)
class FlirAffRecordPlan:
    status: FlirAffRecordStatus
    kind: FlirAffRecordKind
    source_table: str | None
    byte_order: FlirAffByteOrder | None
    sensor_width: int | None
    sensor_height: int | None
    output_emission_gates: tuple[FlirAffRecordGate, ...]
    provenance: FlirAffRecordProvenance


def build_flir_aff_record_plan(record_type: int, payload: bytes) -> FlirAffRecordPlan:
    if record_type == 1:
        if len(payload) < 6:
            return _unsupported(
                "truncated_aff1_record",
                "AFF1 records require RawDataByteOrder, SensorWidth, and SensorHeight.",
            )
        return _planned("aff1", FLIR_TABLE_PREFIX + "AFF1", payload, 0, 2, 4)
    if record_type == 5:
        if len(payload) < 42:
            return _unsupported(
                "truncated_aff5_record",
                "AFF5 records require shifted RawDataByteOrder, SensorWidth, and SensorHeight.",
            )
        return _planned("aff5", FLIR_TABLE_PREFIX + "AFF5", payload, 0x24, 0x26, 0x28)
    return _unsupported(
        "unsupported_aff_record_type",
        "FLIR.pm AFF routing only defines AFF1 and AFF5 sensor records.",
    )


def _planned(
    kind: FlirAffRecordKind,
    source_table: str,
    payload: bytes,
    order_offset: int,
    width_offset: int,
    height_offset: int,
) -> FlirAffRecordPlan:
    byte_order = _byte_order(payload[order_offset : order_offset + 2])
    return FlirAffRecordPlan(
        status="planned",
        kind=kind,
        source_table=source_table,
        byte_order=byte_order,
        sensor_width=int.from_bytes(payload[width_offset : width_offset + 2], byte_order),
        sensor_height=int.from_bytes(payload[height_offset : height_offset + 2], byte_order),
        output_emission_gates=(),
        provenance=(FLIR_AFF1_SOURCE if kind == "aff1" else FLIR_AFF5_SOURCE,),
    )


def _byte_order(raw_value: bytes) -> FlirAffByteOrder:
    return "big" if int.from_bytes(raw_value, "little") >= 0x0100 else "little"


def _unsupported(code: FlirAffRecordGateCode, reason: str) -> FlirAffRecordPlan:
    return FlirAffRecordPlan(
        status="unsupported",
        kind="unknown",
        source_table=None,
        byte_order=None,
        sensor_width=None,
        sensor_height=None,
        output_emission_gates=(FlirAffRecordGate(code, reason, FLIR_AFF_RECORD_SOURCES),),
        provenance=FLIR_AFF_RECORD_SOURCES,
    )
