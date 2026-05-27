"""Write planning primitives for safe metadata mutation.

This module does not mutate files. It converts requested writes into explicit,
validated operations that a later container mutation engine can apply inside a
transaction.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Literal

from exifmodern.json_types import JsonObject, JsonValue

type ExifGpsTagName = Literal[
    "GPSVersionID",
    "GPSLatitudeRef",
    "GPSLatitude",
    "GPSLongitudeRef",
    "GPSLongitude",
    "GPSAltitudeRef",
    "GPSAltitude",
    "GPSTimeStamp",
    "GPSMeasureMode",
    "GPSDOP",
    "GPSSpeedRef",
    "GPSSpeed",
    "GPSTrackRef",
    "GPSTrack",
    "GPSImgDirectionRef",
    "GPSImgDirection",
    "GPSMapDatum",
    "GPSDateStamp",
]
type TiffWriteFieldType = Literal["ASCII", "BYTE", "RATIONAL"]
type WriteOperation = Literal["ensure", "upsert", "delete"]
type WritePlanStatus = Literal["planned"]
type WritePlanScope = Literal["exif_gps_plan_only"]
type GpsAxis = Literal["latitude", "longitude"]
type GpsCoordinateReferencePolicy = Literal["preserve_existing", "write_from_signed"]
type SourceEvidenceId = str

GPS_TAG_IDS: dict[ExifGpsTagName, str] = {
    "GPSVersionID": "0x0000",
    "GPSLatitudeRef": "0x0001",
    "GPSLatitude": "0x0002",
    "GPSLongitudeRef": "0x0003",
    "GPSLongitude": "0x0004",
    "GPSAltitudeRef": "0x0005",
    "GPSAltitude": "0x0006",
    "GPSTimeStamp": "0x0007",
    "GPSMeasureMode": "0x000A",
    "GPSDOP": "0x000B",
    "GPSSpeedRef": "0x000C",
    "GPSSpeed": "0x000D",
    "GPSTrackRef": "0x000E",
    "GPSTrack": "0x000F",
    "GPSImgDirectionRef": "0x0010",
    "GPSImgDirection": "0x0011",
    "GPSMapDatum": "0x0012",
    "GPSDateStamp": "0x001D",
}


@dataclass(frozen=True)
class EvidenceAnchor:
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


PngEvidenceId = EvidenceAnchor

GPS_MAIN_SOURCE_ID: SourceEvidenceId = "gps.write.main_table"
GPS_COORDINATE_SOURCE_ID: SourceEvidenceId = "gps.write.coordinate_conversion"
GPS_LATITUDE_SOURCE_ID: SourceEvidenceId = "gps.write.latitude_tags"
GPS_LONGITUDE_SOURCE_ID: SourceEvidenceId = "gps.write.longitude_tags"
GPS_ALTITUDE_SOURCE_ID: SourceEvidenceId = "gps.write.altitude_tags"
GPS_TIME_STAMP_SOURCE_ID: SourceEvidenceId = "gps.write.timestamp_tag"
GPS_MOTION_SOURCE_ID: SourceEvidenceId = "gps.write.motion_tags"
GPS_DOP_SOURCE_ID: SourceEvidenceId = "gps.write.dop_tags"
GPS_IMAGE_DIRECTION_SOURCE_ID: SourceEvidenceId = "gps.write.image_direction_tags"
GEOTAG_MOTION_SOURCE_ID: SourceEvidenceId = "gps.write.geotag_motion"
GEOTAG_DOP_SOURCE_ID: SourceEvidenceId = "gps.write.geotag_dop"
GEOTAG_DELETE_SOURCE_ID: SourceEvidenceId = "gps.write.geotag_deletion"
GPS_MAP_DATUM_SOURCE_ID: SourceEvidenceId = "gps.write.map_datum"
GPS_DATE_STAMP_SOURCE_ID: SourceEvidenceId = "gps.write.date_stamp"
GPS_VERSION_SOURCE_ID: SourceEvidenceId = "gps.write.version_tag"
GPS_VERSION_DEFAULT_SOURCE_ID: SourceEvidenceId = "gps.write.version_default"
GPS_COMPOSITE_WRITE_ALSO_SOURCE_ID: SourceEvidenceId = "gps.write.composite_write_also"
GPS_INFO_POINTER_SOURCE_ID: SourceEvidenceId = "gps.write.gps_info_pointer"
WRITER_DIRECTORY_MAP_SOURCE_ID: SourceEvidenceId = "gps.write.writer_directory_map"


@dataclass(frozen=True)
class RationalWriteValue:
    numerator: int
    denominator: int


@dataclass(frozen=True)
class AsciiWriteValue:
    text: str
    nul_terminated: bool = True


@dataclass(frozen=True)
class ByteWriteValue:
    values: tuple[int, ...]


@dataclass(frozen=True)
class RationalArrayWriteValue:
    values: tuple[RationalWriteValue, ...]


@dataclass(frozen=True)
class GpsDeleteWriteValue:
    pass


type TiffWriteValue = (
    AsciiWriteValue | ByteWriteValue | RationalArrayWriteValue | GpsDeleteWriteValue
)


@dataclass(frozen=True)
class ExifGpsWriteStep:
    operation: WriteOperation
    group: str
    table_name: str
    tag_name: ExifGpsTagName
    tag_id: str
    field_type: TiffWriteFieldType
    count: int
    value: TiffWriteValue
    evidence_ids: tuple[SourceEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "operation": self.operation,
            "group": self.group,
            "table_name": self.table_name,
            "tag_name": self.tag_name,
            "tag_id": self.tag_id,
            "field_type": self.field_type,
            "count": self.count,
            "value": tiff_write_value_to_json(self.value),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class WritePlanContainerAction:
    action: str
    reason: str
    evidence_ids: tuple[SourceEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "reason": self.reason,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class ExifGpsWritePlan:
    schema_version: int
    generated_at_epoch: int
    status: WritePlanStatus
    scope: WritePlanScope
    steps: tuple[ExifGpsWriteStep, ...]
    container_actions: tuple[WritePlanContainerAction, ...]
    safety_gates: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(exif_gps_write_plan_to_json(self), indent=2, sort_keys=True) + "\n"


def exif_gps_write_plan_to_json(plan: ExifGpsWritePlan) -> JsonObject:
    return {
        "schema_version": plan.schema_version,
        "generated_at_epoch": plan.generated_at_epoch,
        "status": plan.status,
        "scope": plan.scope,
        "steps": [step.to_json() for step in plan.steps],
        "container_actions": [action.to_json() for action in plan.container_actions],
        "safety_gates": list(plan.safety_gates),
    }


def tiff_write_value_to_json(value: TiffWriteValue) -> JsonObject:
    if isinstance(value, AsciiWriteValue):
        return {"kind": "ascii", "text": value.text, "nul_terminated": value.nul_terminated}
    if isinstance(value, ByteWriteValue):
        return {"kind": "byte", "values": list(value.values)}
    if isinstance(value, RationalArrayWriteValue):
        return {
            "kind": "rational_array",
            "values": [
                {"numerator": item.numerator, "denominator": item.denominator}
                for item in value.values
            ],
        }
    return {"kind": "delete"}


def build_exif_gps_write_plan(
    latitude: float | None,
    longitude: float | None,
    altitude_meters: float | None = None,
    gps_timestamp_seconds: float | None = None,
    gps_speed_knots: float | None = None,
    gps_track_degrees: float | None = None,
    gps_img_direction_degrees: float | None = None,
    gps_measure_mode: int | None = None,
    gps_dop: float | None = None,
    gps_timestamp_has_date: bool = True,
    map_datum: str | None = "WGS-84",
    coordinate_reference_policy: GpsCoordinateReferencePolicy = "write_from_signed",
) -> ExifGpsWritePlan:
    steps: list[ExifGpsWriteStep] = [
        gps_version_step(),
    ]
    if latitude is not None:
        steps.extend(gps_coordinate_steps("latitude", latitude, coordinate_reference_policy))
    if longitude is not None:
        steps.extend(gps_coordinate_steps("longitude", longitude, coordinate_reference_policy))
    if altitude_meters is not None:
        steps.extend(gps_altitude_steps(altitude_meters))
    if gps_timestamp_seconds is not None:
        steps.extend(gps_timestamp_steps(gps_timestamp_seconds, gps_timestamp_has_date))
    if gps_speed_knots is not None:
        steps.extend(gps_speed_steps(gps_speed_knots))
    if gps_track_degrees is not None:
        steps.extend(gps_track_steps(gps_track_degrees))
    if gps_img_direction_degrees is not None:
        steps.extend(gps_img_direction_steps(gps_img_direction_degrees))
    if gps_measure_mode is not None and gps_dop is not None:
        steps.extend(gps_dop_steps(gps_measure_mode, gps_dop))
    if map_datum is not None and map_datum:
        steps.append(gps_ascii_step("GPSMapDatum", map_datum))
    if len(steps) == 1 and map_datum is None:
        raise ValueError("GPS write plan requires at least one GPS value.")
    return ExifGpsWritePlan(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        status="planned",
        scope="exif_gps_plan_only",
        steps=tuple(steps),
        container_actions=(
            WritePlanContainerAction(
                action="ensure_jpeg_app1_exif_segment",
                reason="GPS EXIF writes require an APP1 Exif segment in JPEG containers.",
                evidence_ids=(WRITER_DIRECTORY_MAP_SOURCE_ID,),
            ),
            WritePlanContainerAction(
                action="ensure_ifd0_gps_info_pointer",
                reason="IFD0 tag 0x8825 must point to the GPS IFD.",
                evidence_ids=(GPS_INFO_POINTER_SOURCE_ID,),
            ),
            WritePlanContainerAction(
                action="upsert_gps_ifd_entries",
                reason=(
                    "GPS tag entries must be written into the GPS IFD with recalculated offsets."
                ),
                evidence_ids=(GPS_MAIN_SOURCE_ID, GPS_INFO_POINTER_SOURCE_ID),
            ),
            WritePlanContainerAction(
                action="rewrite_container_transactionally",
                reason="Container mutation must use temp-file, backup, and rollback semantics.",
                evidence_ids=(WRITER_DIRECTORY_MAP_SOURCE_ID,),
            ),
        ),
        safety_gates=(
            "plan_only_no_file_mutation",
            "preserve_existing_gps_version_id_unless_gps_ifd_created",
            "validate_coordinate_bounds_before_encoding",
            "recalculate_tiff_offsets_before_write",
            "oracle_binary_round_trip_required_before_enabling_mutation",
        ),
    )


def gps_coordinate_steps(
    axis: GpsAxis,
    coordinate: float,
    reference_policy: GpsCoordinateReferencePolicy,
) -> tuple[ExifGpsWriteStep, ...]:
    validate_coordinate(axis, coordinate)
    tag_name: ExifGpsTagName = "GPSLatitude" if axis == "latitude" else "GPSLongitude"
    ref_tag_name: ExifGpsTagName = "GPSLatitudeRef" if axis == "latitude" else "GPSLongitudeRef"
    reference = gps_coordinate_reference(axis, coordinate)
    coordinate_step = ExifGpsWriteStep(
        operation="upsert",
        group="GPS",
        table_name="Image::ExifTool::GPS::Main",
        tag_name=tag_name,
        tag_id=GPS_TAG_IDS[tag_name],
        field_type="RATIONAL",
        count=3,
        value=RationalArrayWriteValue(decimal_degrees_to_dms_rationals(coordinate)),
        evidence_ids=coordinate_evidence_ids(axis),
    )
    if reference_policy == "preserve_existing":
        return (coordinate_step,)
    return (
        gps_ascii_step(ref_tag_name, reference),
        coordinate_step,
    )


def gps_altitude_steps(altitude_meters: float) -> tuple[ExifGpsWriteStep, ...]:
    if not math.isfinite(altitude_meters):
        raise ValueError("GPS altitude must be finite.")
    altitude_reference = 1 if altitude_meters < 0 else 0
    return (
        ExifGpsWriteStep(
            operation="upsert",
            group="GPS",
            table_name="Image::ExifTool::GPS::Main",
            tag_name="GPSAltitude",
            tag_id=GPS_TAG_IDS["GPSAltitude"],
            field_type="RATIONAL",
            count=1,
            value=RationalArrayWriteValue((rational_write_value(abs(altitude_meters)),)),
            evidence_ids=(GPS_MAIN_SOURCE_ID, GPS_ALTITUDE_SOURCE_ID),
        ),
        ExifGpsWriteStep(
            operation="upsert",
            group="GPS",
            table_name="Image::ExifTool::GPS::Main",
            tag_name="GPSAltitudeRef",
            tag_id=GPS_TAG_IDS["GPSAltitudeRef"],
            field_type="BYTE",
            count=1,
            value=ByteWriteValue((altitude_reference,)),
            evidence_ids=(GPS_MAIN_SOURCE_ID, GPS_ALTITUDE_SOURCE_ID),
        ),
    )


def gps_timestamp_steps(
    timestamp_seconds: float,
    include_date_stamp: bool,
) -> tuple[ExifGpsWriteStep, ...]:
    if not math.isfinite(timestamp_seconds):
        raise ValueError("GPS timestamp must be finite.")
    utc_time = time.gmtime(int(timestamp_seconds))
    date_stamp = f"{utc_time.tm_year:04d}:{utc_time.tm_mon:02d}:{utc_time.tm_mday:02d}"
    time_stamp_step = ExifGpsWriteStep(
        operation="upsert",
        group="GPS",
        table_name="Image::ExifTool::GPS::Main",
        tag_name="GPSTimeStamp",
        tag_id=GPS_TAG_IDS["GPSTimeStamp"],
        field_type="RATIONAL",
        count=3,
        value=RationalArrayWriteValue(
            (
                RationalWriteValue(utc_time.tm_hour, 1),
                RationalWriteValue(utc_time.tm_min, 1),
                rational_write_value(timestamp_seconds % 60),
            )
        ),
        evidence_ids=(GPS_MAIN_SOURCE_ID, GPS_TIME_STAMP_SOURCE_ID),
    )
    if not include_date_stamp:
        return (time_stamp_step,)
    return (
        gps_ascii_step("GPSDateStamp", date_stamp),
        time_stamp_step,
    )


def gps_speed_steps(speed_knots: float) -> tuple[ExifGpsWriteStep, ...]:
    validate_non_negative_finite("GPS speed", speed_knots)
    return (
        gps_ascii_step("GPSSpeedRef", "N"),
        gps_rational_step(
            "GPSSpeed",
            speed_knots,
            (GPS_MAIN_SOURCE_ID, GPS_MOTION_SOURCE_ID, GEOTAG_MOTION_SOURCE_ID),
        ),
    )


def gps_track_steps(track_degrees: float) -> tuple[ExifGpsWriteStep, ...]:
    validate_angle_degrees("GPS track", track_degrees)
    return (
        gps_ascii_step("GPSTrackRef", "T"),
        gps_rational_step(
            "GPSTrack",
            track_degrees,
            (GPS_MAIN_SOURCE_ID, GPS_MOTION_SOURCE_ID, GEOTAG_MOTION_SOURCE_ID),
        ),
    )


def gps_img_direction_steps(direction_degrees: float) -> tuple[ExifGpsWriteStep, ...]:
    validate_angle_degrees("GPS image direction", direction_degrees)
    return (
        gps_ascii_step("GPSImgDirectionRef", "T"),
        gps_rational_step(
            "GPSImgDirection",
            direction_degrees,
            (GPS_MAIN_SOURCE_ID, GPS_IMAGE_DIRECTION_SOURCE_ID, GEOTAG_MOTION_SOURCE_ID),
        ),
    )


def gps_dop_steps(measure_mode: int, dop: float) -> tuple[ExifGpsWriteStep, ...]:
    if measure_mode not in {2, 3}:
        raise ValueError("GPS measure mode must be 2 or 3.")
    validate_non_negative_finite("GPS DOP", dop)
    return (
        gps_ascii_step("GPSMeasureMode", str(measure_mode)),
        gps_rational_step(
            "GPSDOP",
            dop,
            (GPS_MAIN_SOURCE_ID, GPS_DOP_SOURCE_ID, GEOTAG_DOP_SOURCE_ID),
        ),
    )


def append_gps_delete_steps(
    plan: ExifGpsWritePlan,
    tag_names: tuple[ExifGpsTagName, ...],
) -> ExifGpsWritePlan:
    if not tag_names:
        return plan
    return ExifGpsWritePlan(
        schema_version=plan.schema_version,
        generated_at_epoch=plan.generated_at_epoch,
        status=plan.status,
        scope=plan.scope,
        steps=plan.steps + tuple(gps_delete_step(tag_name) for tag_name in tag_names),
        container_actions=plan.container_actions,
        safety_gates=plan.safety_gates,
    )


def gps_delete_step(tag_name: ExifGpsTagName) -> ExifGpsWriteStep:
    return ExifGpsWriteStep(
        operation="delete",
        group="GPS",
        table_name="Image::ExifTool::GPS::Main",
        tag_name=tag_name,
        tag_id=GPS_TAG_IDS[tag_name],
        field_type=gps_tag_field_type(tag_name),
        count=0,
        value=GpsDeleteWriteValue(),
        evidence_ids=delete_evidence_ids(tag_name),
    )


def gps_rational_step(
    tag_name: ExifGpsTagName,
    value: float,
    evidence_ids: tuple[SourceEvidenceId, ...],
) -> ExifGpsWriteStep:
    return ExifGpsWriteStep(
        operation="upsert",
        group="GPS",
        table_name="Image::ExifTool::GPS::Main",
        tag_name=tag_name,
        tag_id=GPS_TAG_IDS[tag_name],
        field_type="RATIONAL",
        count=1,
        value=RationalArrayWriteValue((rational_write_value(value),)),
        evidence_ids=evidence_ids,
    )


def gps_tag_field_type(tag_name: ExifGpsTagName) -> TiffWriteFieldType:
    if tag_name in {
        "GPSLatitudeRef",
        "GPSLongitudeRef",
        "GPSSpeedRef",
        "GPSTrackRef",
        "GPSImgDirectionRef",
        "GPSMapDatum",
        "GPSDateStamp",
        "GPSMeasureMode",
    }:
        return "ASCII"
    if tag_name in {"GPSVersionID", "GPSAltitudeRef"}:
        return "BYTE"
    return "RATIONAL"


def delete_evidence_ids(tag_name: ExifGpsTagName) -> tuple[SourceEvidenceId, ...]:
    if tag_name in {"GPSLatitudeRef", "GPSLatitude"}:
        return (GPS_MAIN_SOURCE_ID, GPS_LATITUDE_SOURCE_ID, GEOTAG_DELETE_SOURCE_ID)
    if tag_name in {"GPSLongitudeRef", "GPSLongitude"}:
        return (GPS_MAIN_SOURCE_ID, GPS_LONGITUDE_SOURCE_ID, GEOTAG_DELETE_SOURCE_ID)
    if tag_name in {"GPSAltitude", "GPSAltitudeRef"}:
        return (GPS_MAIN_SOURCE_ID, GPS_ALTITUDE_SOURCE_ID, GEOTAG_DELETE_SOURCE_ID)
    if tag_name in {"GPSDateStamp", "GPSTimeStamp"}:
        return (GPS_MAIN_SOURCE_ID, GPS_DATE_STAMP_SOURCE_ID, GEOTAG_DELETE_SOURCE_ID)
    if tag_name in {"GPSSpeed", "GPSSpeedRef", "GPSTrack", "GPSTrackRef"}:
        return (GPS_MAIN_SOURCE_ID, GPS_MOTION_SOURCE_ID, GEOTAG_DELETE_SOURCE_ID)
    if tag_name in {"GPSImgDirection", "GPSImgDirectionRef"}:
        return (GPS_MAIN_SOURCE_ID, GPS_IMAGE_DIRECTION_SOURCE_ID, GEOTAG_DELETE_SOURCE_ID)
    if tag_name in {"GPSMeasureMode", "GPSDOP"}:
        return (GPS_MAIN_SOURCE_ID, GPS_DOP_SOURCE_ID, GEOTAG_DELETE_SOURCE_ID)
    return (GPS_MAIN_SOURCE_ID,)


def gps_ascii_step(tag_name: ExifGpsTagName, text: str) -> ExifGpsWriteStep:
    return ExifGpsWriteStep(
        operation="upsert",
        group="GPS",
        table_name="Image::ExifTool::GPS::Main",
        tag_name=tag_name,
        tag_id=GPS_TAG_IDS[tag_name],
        field_type="ASCII",
        count=len(text) + 1,
        value=AsciiWriteValue(text),
        evidence_ids=ascii_evidence_ids(tag_name),
    )


def gps_version_step() -> ExifGpsWriteStep:
    values = (2, 3, 0, 0)
    return ExifGpsWriteStep(
        operation="ensure",
        group="GPS",
        table_name="Image::ExifTool::GPS::Main",
        tag_name="GPSVersionID",
        tag_id=GPS_TAG_IDS["GPSVersionID"],
        field_type="BYTE",
        count=len(values),
        value=ByteWriteValue(values),
        evidence_ids=(GPS_MAIN_SOURCE_ID, GPS_VERSION_SOURCE_ID, GPS_VERSION_DEFAULT_SOURCE_ID),
    )


def coordinate_evidence_ids(axis: GpsAxis) -> tuple[SourceEvidenceId, ...]:
    coordinate_source_id = GPS_LATITUDE_SOURCE_ID if axis == "latitude" else GPS_LONGITUDE_SOURCE_ID
    return (
        GPS_MAIN_SOURCE_ID,
        GPS_COORDINATE_SOURCE_ID,
        coordinate_source_id,
        GPS_COMPOSITE_WRITE_ALSO_SOURCE_ID,
    )


def ascii_evidence_ids(tag_name: ExifGpsTagName) -> tuple[SourceEvidenceId, ...]:
    if tag_name in {"GPSLatitudeRef", "GPSLatitude"}:
        return (GPS_MAIN_SOURCE_ID, GPS_LATITUDE_SOURCE_ID, GPS_COMPOSITE_WRITE_ALSO_SOURCE_ID)
    if tag_name in {"GPSLongitudeRef", "GPSLongitude"}:
        return (GPS_MAIN_SOURCE_ID, GPS_LONGITUDE_SOURCE_ID, GPS_COMPOSITE_WRITE_ALSO_SOURCE_ID)
    if tag_name == "GPSMapDatum":
        return (GPS_MAIN_SOURCE_ID, GPS_MAP_DATUM_SOURCE_ID)
    if tag_name == "GPSDateStamp":
        return (GPS_MAIN_SOURCE_ID, GPS_DATE_STAMP_SOURCE_ID)
    if tag_name in {"GPSSpeedRef", "GPSTrackRef"}:
        return (GPS_MAIN_SOURCE_ID, GPS_MOTION_SOURCE_ID, GEOTAG_MOTION_SOURCE_ID)
    if tag_name == "GPSImgDirectionRef":
        return (GPS_MAIN_SOURCE_ID, GPS_IMAGE_DIRECTION_SOURCE_ID, GEOTAG_MOTION_SOURCE_ID)
    if tag_name == "GPSMeasureMode":
        return (GPS_MAIN_SOURCE_ID, GPS_DOP_SOURCE_ID, GEOTAG_DOP_SOURCE_ID)
    if tag_name == "GPSVersionID":
        return (GPS_MAIN_SOURCE_ID, GPS_VERSION_SOURCE_ID)
    raise ValueError(f"Unsupported GPS ASCII tag: {tag_name}")


def validate_coordinate(axis: GpsAxis, coordinate: float) -> None:
    if not math.isfinite(coordinate):
        raise ValueError(f"GPS {axis} must be finite.")
    if axis == "latitude" and not -90 <= coordinate <= 90:
        raise ValueError("GPS latitude must be between -90 and 90 degrees.")
    if axis == "longitude" and not -180 <= coordinate <= 180:
        raise ValueError("GPS longitude must be between -180 and 180 degrees.")


def validate_non_negative_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite.")
    if value < 0:
        raise ValueError(f"{name} must not be negative.")


def validate_angle_degrees(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite.")
    if not 0 <= value < 360:
        raise ValueError(f"{name} must be in the range [0, 360).")


def gps_coordinate_reference(axis: GpsAxis, coordinate: float) -> str:
    if axis == "latitude":
        return "S" if coordinate < 0 else "N"
    return "W" if coordinate < 0 else "E"


def decimal_degrees_to_dms_rationals(
    coordinate: float,
) -> tuple[RationalWriteValue, RationalWriteValue, RationalWriteValue]:
    absolute = abs(coordinate)
    degrees = int(absolute)
    raw_minutes = (absolute - degrees) * 60
    minutes = int(raw_minutes)
    seconds = (raw_minutes - minutes) * 60
    return (
        RationalWriteValue(degrees, 1),
        RationalWriteValue(minutes, 1),
        rational_write_value(seconds),
    )


def rational_write_value(value: float) -> RationalWriteValue:
    fraction = Fraction(f"{value:.6f}").limit_denominator(1_000_000)
    return RationalWriteValue(fraction.numerator, fraction.denominator)


def write_exif_gps_write_plan(
    output: Path | None,
    latitude: float | None,
    longitude: float | None,
    altitude_meters: float | None = None,
    gps_timestamp_seconds: float | None = None,
    gps_speed_knots: float | None = None,
    gps_track_degrees: float | None = None,
    gps_img_direction_degrees: float | None = None,
    gps_measure_mode: int | None = None,
    gps_dop: float | None = None,
    gps_timestamp_has_date: bool = True,
    map_datum: str | None = "WGS-84",
    coordinate_reference_policy: GpsCoordinateReferencePolicy = "write_from_signed",
) -> ExifGpsWritePlan:
    plan = build_exif_gps_write_plan(
        latitude=latitude,
        longitude=longitude,
        altitude_meters=altitude_meters,
        gps_timestamp_seconds=gps_timestamp_seconds,
        gps_speed_knots=gps_speed_knots,
        gps_track_degrees=gps_track_degrees,
        gps_img_direction_degrees=gps_img_direction_degrees,
        gps_measure_mode=gps_measure_mode,
        gps_dop=gps_dop,
        gps_timestamp_has_date=gps_timestamp_has_date,
        map_datum=map_datum,
        coordinate_reference_policy=coordinate_reference_policy,
    )
    payload = plan.to_json()
    if output is None:
        print(payload, end="")
        return plan
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")
    return plan


def exif_gps_write_plan_summary(plan: ExifGpsWritePlan) -> dict[str, JsonValue]:
    return {
        "status": plan.status,
        "scope": plan.scope,
        "step_count": len(plan.steps),
        "container_action_count": len(plan.container_actions),
        "safety_gate_count": len(plan.safety_gates),
    }
