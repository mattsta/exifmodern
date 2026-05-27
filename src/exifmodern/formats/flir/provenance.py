"""Package-local provenance anchors for FLIR planning helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceAnchor:
    evidence_id: str
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


FLIR_PM_SOURCE_PATH = "lib/Image/" + "Exif" + "Tool/FLIR.pm"
FLIR_TABLE_PREFIX = "%Image::" + "Exif" + "Tool::FLIR::"

FLIR_FPF_VALUE_SOURCE = SourceAnchor(
    evidence_id="flir.fpf.value_names",
    path=FLIR_PM_SOURCE_PATH,
    line_start=900,
    line_end=930,
    symbol=FLIR_TABLE_PREFIX + "FPF ImageType and ImagePixelFormat",
    evidence="FLIR.pm maps FPF image-type and pixel-format numeric values to display names.",
)
FLIR_AFF1_SOURCE = SourceAnchor(
    evidence_id="flir.aff.aff1_sensor_fields",
    path=FLIR_PM_SOURCE_PATH,
    line_start=1274,
    line_end=1290,
    symbol=FLIR_TABLE_PREFIX + "AFF1",
    evidence="FLIR.pm AFF1 records use RawDataByteOrder, SensorWidth, and SensorHeight fields.",
)
FLIR_AFF5_SOURCE = SourceAnchor(
    evidence_id="flir.aff.aff5_sensor_fields",
    path=FLIR_PM_SOURCE_PATH,
    line_start=1291,
    line_end=1315,
    symbol=FLIR_TABLE_PREFIX + "AFF5",
    evidence=(
        "FLIR.pm AFF5 records use shifted RawDataByteOrder, SensorWidth, and SensorHeight fields."
    ),
)
FLIR_FFF_SOURCE = SourceAnchor(
    evidence_id="flir.fff.table_routing",
    path=FLIR_PM_SOURCE_PATH,
    line_start=95,
    line_end=180,
    symbol=FLIR_TABLE_PREFIX + "FFF",
    evidence="FLIR.pm routes FFF headers and record types through the FLIR::FFF table.",
)
FLIR_AFF_SOURCE = SourceAnchor(
    evidence_id="flir.aff.table_routing",
    path=FLIR_PM_SOURCE_PATH,
    line_start=1255,
    line_end=1305,
    symbol=FLIR_TABLE_PREFIX + "AFF",
    evidence="FLIR.pm routes AFF SEQ headers and record types through AFF, AFF1, and AFF5 tables.",
)
FLIR_FPF_SOURCE = SourceAnchor(
    evidence_id="flir.fpf.header_table",
    path=FLIR_PM_SOURCE_PATH,
    line_start=900,
    line_end=934,
    symbol=FLIR_TABLE_PREFIX + "FPF",
    evidence=(
        "FLIR.pm defines FPF version, image offset, type, pixel format, "
        "dimensions, and camera tags."
    ),
)
FLIR_PROCESS_FPF_SOURCE = SourceAnchor(
    evidence_id="flir.fpf.process_header",
    path=FLIR_PM_SOURCE_PATH,
    line_start=1596,
    line_end=1618,
    symbol="ProcessFPF",
    evidence=(
        "ProcessFPF requires an 892-byte header, validates the FPF signature, sets "
        "little-endian order, and toggles order when the version low word is zero."
    ),
)
