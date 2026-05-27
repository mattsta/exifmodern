"""Source-backed EXIF GPS metadata transaction planning.

This package is intentionally separate from geotag/geolocation application
flows.  It models GPS.pm tag-table responsibility, value conversion
boundaries, unknown GPS IFD preservation, malformed input blockers, and the
rewrite gates needed before any byte writer is enabled.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

GPS_PM_SOURCE_PATH = "lib/Image/ExifTool/GPS.pm"

type GpsValue = str | int | float | bytes | tuple[str | int | float, ...]
type GpsResponsibilityKind = Literal[
    "gps_ifd_table",
    "camera_location",
    "subject_location",
    "gps_time",
    "gps_motion",
    "measurement_quality",
    "image_direction",
    "gps_text",
    "read_only_composite",
    "unknown_tag_preservation",
    "malformed_input_blockers",
    "rewrite_gate",
    "non_mutating_defaults",
]
type GpsRouteAction = Literal[
    "route_writable_tag",
    "route_read_only_composite",
    "preserve_unknown_tag",
]
type GpsWritableFormat = Literal["int8u", "int16u", "rational64u", "string", "undef"]
type GpsConversionBoundary = Literal[
    "none",
    "latitude_ref",
    "longitude_ref",
    "latitude_coordinate",
    "longitude_coordinate",
    "altitude_ref",
    "altitude",
    "timestamp",
    "date_stamp",
    "exif_text",
]
type GpsBlockerCode = Literal[
    "tag_name_mismatch",
    "invalid_ref_value",
    "invalid_coordinate_value",
    "invalid_altitude_value",
    "invalid_timestamp_value",
    "invalid_date_stamp_value",
    "invalid_numeric_value",
    "unsupported_source_value",
    "rewrite_requested_requires_gps_writer",
]
type GpsEmissionGateCode = Literal[
    "planner_is_non_mutating",
    "gps_ifd_writer_not_implemented",
    "rewrite_requested_requires_gps_writer",
    "malformed_gps_input_blocks_rewrite",
]
type GpsRewriteOperation = Literal["upsert_tag", "delete_tag"]

GPS_TABLE_SOURCE = "gps.table"
GPS_COORD_CONV_SOURCE = "gps.coord.conv"
GPS_REF_CONV_SOURCE = "gps.ref.conv"
GPS_CAMERA_LOCATION_SOURCE = "gps.camera.location"
GPS_TIME_SOURCE = "gps.time"
GPS_STATUS_QUALITY_SOURCE = "gps.status.quality"
GPS_MOTION_SOURCE = "gps.motion"
GPS_SUBJECT_LOCATION_SOURCE = "gps.subject.location"
GPS_TEXT_SOURCE = "gps.text"
GPS_DATE_SOURCE = "gps.date"
GPS_DIFFERENTIAL_ERROR_SOURCE = "gps.differential.error"
GPS_UNKNOWN_PADDING_SOURCE = "gps.unknown.padding"
GPS_COMPOSITE_SOURCE = "gps.composite"
GPS_TO_DMS_SOURCE = "gps.to.dms"
GPS_TO_DEGREES_SOURCE = "gps.to.degrees"


@dataclass(frozen=True)
class GpsTagDefinition:
    tag_id: int
    tag_name: str
    writable_format: GpsWritableFormat
    count: int | None
    responsibility: GpsResponsibilityKind
    conversion_boundary: GpsConversionBoundary
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GpsCompositeDefinition:
    tag_name: str
    writable: bool
    responsibility: GpsResponsibilityKind
    conversion_boundary: GpsConversionBoundary
    evidence_ids: tuple[str, ...]


GPS_TAG_DEFINITIONS: dict[int, GpsTagDefinition] = {
    0x0000: GpsTagDefinition(
        0x0000,
        "GPSVersionID",
        "int8u",
        4,
        "gps_ifd_table",
        "none",
        (GPS_TABLE_SOURCE,),
    ),
    0x0001: GpsTagDefinition(
        0x0001,
        "GPSLatitudeRef",
        "string",
        2,
        "camera_location",
        "latitude_ref",
        (GPS_TABLE_SOURCE, GPS_REF_CONV_SOURCE, GPS_CAMERA_LOCATION_SOURCE),
    ),
    0x0002: GpsTagDefinition(
        0x0002,
        "GPSLatitude",
        "rational64u",
        3,
        "camera_location",
        "latitude_coordinate",
        (GPS_TABLE_SOURCE, GPS_COORD_CONV_SOURCE, GPS_CAMERA_LOCATION_SOURCE),
    ),
    0x0003: GpsTagDefinition(
        0x0003,
        "GPSLongitudeRef",
        "string",
        2,
        "camera_location",
        "longitude_ref",
        (GPS_TABLE_SOURCE, GPS_REF_CONV_SOURCE, GPS_CAMERA_LOCATION_SOURCE),
    ),
    0x0004: GpsTagDefinition(
        0x0004,
        "GPSLongitude",
        "rational64u",
        3,
        "camera_location",
        "longitude_coordinate",
        (GPS_TABLE_SOURCE, GPS_COORD_CONV_SOURCE, GPS_CAMERA_LOCATION_SOURCE),
    ),
    0x0005: GpsTagDefinition(
        0x0005,
        "GPSAltitudeRef",
        "int8u",
        1,
        "camera_location",
        "altitude_ref",
        (GPS_TABLE_SOURCE, GPS_CAMERA_LOCATION_SOURCE),
    ),
    0x0006: GpsTagDefinition(
        0x0006,
        "GPSAltitude",
        "rational64u",
        1,
        "camera_location",
        "altitude",
        (GPS_TABLE_SOURCE, GPS_CAMERA_LOCATION_SOURCE),
    ),
    0x0007: GpsTagDefinition(
        0x0007,
        "GPSTimeStamp",
        "rational64u",
        3,
        "gps_time",
        "timestamp",
        (GPS_TABLE_SOURCE, GPS_TIME_SOURCE),
    ),
    0x0008: GpsTagDefinition(
        0x0008,
        "GPSSatellites",
        "string",
        None,
        "measurement_quality",
        "none",
        (GPS_TABLE_SOURCE, GPS_STATUS_QUALITY_SOURCE),
    ),
    0x0009: GpsTagDefinition(
        0x0009,
        "GPSStatus",
        "string",
        2,
        "measurement_quality",
        "none",
        (GPS_TABLE_SOURCE, GPS_STATUS_QUALITY_SOURCE),
    ),
    0x000A: GpsTagDefinition(
        0x000A,
        "GPSMeasureMode",
        "string",
        2,
        "measurement_quality",
        "none",
        (GPS_TABLE_SOURCE, GPS_STATUS_QUALITY_SOURCE),
    ),
    0x000B: GpsTagDefinition(
        0x000B,
        "GPSDOP",
        "rational64u",
        1,
        "measurement_quality",
        "none",
        (GPS_TABLE_SOURCE, GPS_STATUS_QUALITY_SOURCE),
    ),
    0x000C: GpsTagDefinition(
        0x000C,
        "GPSSpeedRef",
        "string",
        2,
        "gps_motion",
        "none",
        (GPS_TABLE_SOURCE, GPS_MOTION_SOURCE),
    ),
    0x000D: GpsTagDefinition(
        0x000D,
        "GPSSpeed",
        "rational64u",
        1,
        "gps_motion",
        "none",
        (GPS_TABLE_SOURCE, GPS_MOTION_SOURCE),
    ),
    0x000E: GpsTagDefinition(
        0x000E,
        "GPSTrackRef",
        "string",
        2,
        "gps_motion",
        "none",
        (GPS_TABLE_SOURCE, GPS_MOTION_SOURCE),
    ),
    0x000F: GpsTagDefinition(
        0x000F,
        "GPSTrack",
        "rational64u",
        1,
        "gps_motion",
        "none",
        (GPS_TABLE_SOURCE, GPS_MOTION_SOURCE),
    ),
    0x0010: GpsTagDefinition(
        0x0010,
        "GPSImgDirectionRef",
        "string",
        2,
        "image_direction",
        "none",
        (GPS_TABLE_SOURCE, GPS_MOTION_SOURCE),
    ),
    0x0011: GpsTagDefinition(
        0x0011,
        "GPSImgDirection",
        "rational64u",
        1,
        "image_direction",
        "none",
        (GPS_TABLE_SOURCE, GPS_MOTION_SOURCE),
    ),
    0x0012: GpsTagDefinition(
        0x0012,
        "GPSMapDatum",
        "string",
        None,
        "gps_text",
        "none",
        (GPS_TABLE_SOURCE,),
    ),
    0x0013: GpsTagDefinition(
        0x0013,
        "GPSDestLatitudeRef",
        "string",
        2,
        "subject_location",
        "latitude_ref",
        (GPS_TABLE_SOURCE, GPS_REF_CONV_SOURCE, GPS_SUBJECT_LOCATION_SOURCE),
    ),
    0x0014: GpsTagDefinition(
        0x0014,
        "GPSDestLatitude",
        "rational64u",
        3,
        "subject_location",
        "latitude_coordinate",
        (GPS_TABLE_SOURCE, GPS_COORD_CONV_SOURCE, GPS_SUBJECT_LOCATION_SOURCE),
    ),
    0x0015: GpsTagDefinition(
        0x0015,
        "GPSDestLongitudeRef",
        "string",
        2,
        "subject_location",
        "longitude_ref",
        (GPS_TABLE_SOURCE, GPS_REF_CONV_SOURCE, GPS_SUBJECT_LOCATION_SOURCE),
    ),
    0x0016: GpsTagDefinition(
        0x0016,
        "GPSDestLongitude",
        "rational64u",
        3,
        "subject_location",
        "longitude_coordinate",
        (GPS_TABLE_SOURCE, GPS_COORD_CONV_SOURCE, GPS_SUBJECT_LOCATION_SOURCE),
    ),
    0x0017: GpsTagDefinition(
        0x0017,
        "GPSDestBearingRef",
        "string",
        2,
        "subject_location",
        "none",
        (GPS_TABLE_SOURCE, GPS_SUBJECT_LOCATION_SOURCE),
    ),
    0x0018: GpsTagDefinition(
        0x0018,
        "GPSDestBearing",
        "rational64u",
        1,
        "subject_location",
        "none",
        (GPS_TABLE_SOURCE, GPS_SUBJECT_LOCATION_SOURCE),
    ),
    0x0019: GpsTagDefinition(
        0x0019,
        "GPSDestDistanceRef",
        "string",
        2,
        "subject_location",
        "none",
        (GPS_TABLE_SOURCE, GPS_SUBJECT_LOCATION_SOURCE),
    ),
    0x001A: GpsTagDefinition(
        0x001A,
        "GPSDestDistance",
        "rational64u",
        1,
        "subject_location",
        "none",
        (GPS_TABLE_SOURCE, GPS_SUBJECT_LOCATION_SOURCE),
    ),
    0x001B: GpsTagDefinition(
        0x001B,
        "GPSProcessingMethod",
        "undef",
        None,
        "gps_text",
        "exif_text",
        (GPS_TABLE_SOURCE, GPS_TEXT_SOURCE),
    ),
    0x001C: GpsTagDefinition(
        0x001C,
        "GPSAreaInformation",
        "undef",
        None,
        "gps_text",
        "exif_text",
        (GPS_TABLE_SOURCE, GPS_TEXT_SOURCE),
    ),
    0x001D: GpsTagDefinition(
        0x001D,
        "GPSDateStamp",
        "string",
        11,
        "gps_time",
        "date_stamp",
        (GPS_TABLE_SOURCE, GPS_DATE_SOURCE),
    ),
    0x001E: GpsTagDefinition(
        0x001E,
        "GPSDifferential",
        "int16u",
        1,
        "measurement_quality",
        "none",
        (GPS_TABLE_SOURCE, GPS_DIFFERENTIAL_ERROR_SOURCE),
    ),
    0x001F: GpsTagDefinition(
        0x001F,
        "GPSHPositioningError",
        "rational64u",
        1,
        "measurement_quality",
        "none",
        (GPS_TABLE_SOURCE, GPS_DIFFERENTIAL_ERROR_SOURCE),
    ),
}

GPS_COMPOSITE_DEFINITIONS: dict[str, GpsCompositeDefinition] = {
    "GPSDateTime": GpsCompositeDefinition(
        "GPSDateTime",
        False,
        "read_only_composite",
        "timestamp",
        (GPS_COMPOSITE_SOURCE, GPS_TIME_SOURCE, GPS_DATE_SOURCE),
    ),
    "GPSLatitude": GpsCompositeDefinition(
        "GPSLatitude",
        True,
        "camera_location",
        "latitude_coordinate",
        (GPS_COMPOSITE_SOURCE, GPS_REF_CONV_SOURCE, GPS_TO_DEGREES_SOURCE),
    ),
    "GPSLongitude": GpsCompositeDefinition(
        "GPSLongitude",
        True,
        "camera_location",
        "longitude_coordinate",
        (GPS_COMPOSITE_SOURCE, GPS_REF_CONV_SOURCE, GPS_TO_DEGREES_SOURCE),
    ),
    "GPSAltitude": GpsCompositeDefinition(
        "GPSAltitude",
        False,
        "read_only_composite",
        "altitude",
        (GPS_COMPOSITE_SOURCE,),
    ),
    "GPSDestLatitude": GpsCompositeDefinition(
        "GPSDestLatitude",
        False,
        "read_only_composite",
        "latitude_coordinate",
        (GPS_COMPOSITE_SOURCE,),
    ),
    "GPSDestLongitude": GpsCompositeDefinition(
        "GPSDestLongitude",
        False,
        "read_only_composite",
        "longitude_coordinate",
        (GPS_COMPOSITE_SOURCE,),
    ),
}


@dataclass(frozen=True)
class GpsSourceTag:
    tag_id: int
    tag_name: str | None
    value: GpsValue


@dataclass(frozen=True)
class GpsRewriteRequest:
    operation: GpsRewriteOperation
    tag_name: str
    value: GpsValue | None = None


@dataclass(frozen=True)
class GpsRoutedTag:
    tag_id: int | None
    tag_name: str
    action: GpsRouteAction
    writable: bool
    writable_format: GpsWritableFormat | None
    count: int | None
    responsibility: GpsResponsibilityKind
    conversion_boundary: GpsConversionBoundary
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GpsPreservedUnknownTag:
    tag_id: int
    tag_name: str | None
    value: GpsValue
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GpsTransactionBlocker:
    code: GpsBlockerCode
    tag_name: str
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GpsOutputEmissionGate:
    code: GpsEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GpsResponsibilityPlan:
    kind: GpsResponsibilityKind
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GpsMetadataTransactionPlan:
    source_tags: tuple[GpsSourceTag, ...]
    routed_tags: tuple[GpsRoutedTag, ...]
    preserved_unknown_tags: tuple[GpsPreservedUnknownTag, ...]
    blockers: tuple[GpsTransactionBlocker, ...]
    output_emission_gates: tuple[GpsOutputEmissionGate, ...]
    responsibilities: tuple[GpsResponsibilityPlan, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return False

    def emit(self) -> bytes:
        gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
        raise ValueError(f"GPS metadata transaction output is gated: {gate_codes}")


def build_gps_metadata_transaction_plan(
    source_tags: tuple[GpsSourceTag, ...] = (),
    rewrite_requests: tuple[GpsRewriteRequest, ...] = (),
) -> GpsMetadataTransactionPlan:
    routed_tags: list[GpsRoutedTag] = []
    preserved_unknown_tags: list[GpsPreservedUnknownTag] = []
    blockers: list[GpsTransactionBlocker] = []
    evidence_ids: list[str] = [
        GPS_TABLE_SOURCE,
        GPS_UNKNOWN_PADDING_SOURCE,
    ]
    for source_tag in source_tags:
        route = route_gps_tag(source_tag.tag_id, source_tag.tag_name)
        routed_tags.append(route)
        evidence_ids.extend(route.evidence_ids)
        if route.action == "preserve_unknown_tag":
            preserved_unknown_tags.append(
                GpsPreservedUnknownTag(
                    source_tag.tag_id,
                    source_tag.tag_name,
                    source_tag.value,
                    route.evidence_ids,
                )
            )
            continue
        definition = GPS_TAG_DEFINITIONS.get(source_tag.tag_id)
        if definition is not None:
            blockers.extend(validate_source_tag(source_tag, definition))
    for request in rewrite_requests:
        blockers.append(
            GpsTransactionBlocker(
                "rewrite_requested_requires_gps_writer",
                request.tag_name,
                f"{request.operation} requires a GPS IFD writer; this slice only plans.",
                (GPS_TABLE_SOURCE,),
            )
        )
    output_emission_gates = gps_output_emission_gates(blockers, rewrite_requests)
    responsibilities = gps_responsibilities(routed_tags, blockers, preserved_unknown_tags)
    for responsibility in responsibilities:
        evidence_ids.extend(responsibility.evidence_ids)
    return GpsMetadataTransactionPlan(
        source_tags=source_tags,
        routed_tags=tuple(routed_tags),
        preserved_unknown_tags=tuple(preserved_unknown_tags),
        blockers=tuple(blockers),
        output_emission_gates=output_emission_gates,
        responsibilities=responsibilities,
        evidence_ids=dedupe_evidence_ids(tuple(evidence_ids)),
    )


def route_gps_tag(tag_id: int | None, tag_name: str | None = None) -> GpsRoutedTag:
    if tag_id is not None and tag_id in GPS_TAG_DEFINITIONS:
        definition = GPS_TAG_DEFINITIONS[tag_id]
        return GpsRoutedTag(
            definition.tag_id,
            definition.tag_name,
            "route_writable_tag",
            True,
            definition.writable_format,
            definition.count,
            definition.responsibility,
            definition.conversion_boundary,
            definition.evidence_ids,
        )
    if tag_name is not None and tag_name in GPS_COMPOSITE_DEFINITIONS:
        composite = GPS_COMPOSITE_DEFINITIONS[tag_name]
        action: GpsRouteAction = (
            "route_writable_tag" if composite.writable else "route_read_only_composite"
        )
        return GpsRoutedTag(
            None,
            composite.tag_name,
            action,
            composite.writable,
            None,
            None,
            composite.responsibility,
            composite.conversion_boundary,
            composite.evidence_ids,
        )
    unknown_name = tag_name if tag_name is not None else f"Unknown_{tag_id:#06x}"
    return GpsRoutedTag(
        tag_id,
        unknown_name,
        "preserve_unknown_tag",
        False,
        None,
        None,
        "unknown_tag_preservation",
        "none",
        (GPS_UNKNOWN_PADDING_SOURCE,),
    )


def validate_source_tag(
    source_tag: GpsSourceTag,
    definition: GpsTagDefinition,
) -> tuple[GpsTransactionBlocker, ...]:
    blockers: list[GpsTransactionBlocker] = []
    if source_tag.tag_name is not None and source_tag.tag_name != definition.tag_name:
        blockers.append(
            GpsTransactionBlocker(
                "tag_name_mismatch",
                source_tag.tag_name,
                f"Tag id {source_tag.tag_id:#06x} is {definition.tag_name} in GPS.pm.",
                definition.evidence_ids,
            )
        )
    conversion_blocker = validate_conversion_boundary(source_tag.value, definition)
    if conversion_blocker is not None:
        blockers.append(conversion_blocker)
    return tuple(blockers)


def validate_conversion_boundary(
    value: GpsValue,
    definition: GpsTagDefinition,
) -> GpsTransactionBlocker | None:
    boundary = definition.conversion_boundary
    if boundary == "latitude_ref":
        if latitude_ref_from_write_value(value) is None:
            return conversion_blocker("invalid_ref_value", definition)
    elif boundary == "longitude_ref":
        if longitude_ref_from_write_value(value) is None:
            return conversion_blocker("invalid_ref_value", definition)
    elif boundary in {"latitude_coordinate", "longitude_coordinate"}:
        coord_kind: Literal["lat", "lon"] = "lat" if boundary == "latitude_coordinate" else "lon"
        coordinate = gps_coordinate_to_degrees(value, True, coord_kind)
        if coordinate is None or not coordinate_in_range(coordinate, coord_kind):
            return conversion_blocker("invalid_coordinate_value", definition)
    elif boundary == "altitude_ref":
        if altitude_ref_from_write_value(value) is None:
            return conversion_blocker("invalid_altitude_value", definition)
    elif boundary == "altitude":
        if unsigned_decimal_from_value(value) is None:
            return conversion_blocker("invalid_altitude_value", definition)
    elif boundary == "timestamp":
        if gps_timestamp_to_utc_time(value) is None:
            return conversion_blocker("invalid_timestamp_value", definition)
    elif boundary == "date_stamp":
        if gps_date_stamp_from_value(value) is None:
            return conversion_blocker("invalid_date_stamp_value", definition)
    elif definition.writable_format in {"rational64u", "int8u", "int16u"}:
        if numeric_value_is_supported(value) is False:
            return conversion_blocker("invalid_numeric_value", definition)
    elif definition.writable_format in {"string", "undef"}:
        if isinstance(value, bytes):
            return conversion_blocker("unsupported_source_value", definition)
    return None


def conversion_blocker(
    code: GpsBlockerCode,
    definition: GpsTagDefinition,
) -> GpsTransactionBlocker:
    return GpsTransactionBlocker(
        code,
        definition.tag_name,
        f"{definition.tag_name} value does not satisfy GPS.pm {definition.conversion_boundary}.",
        definition.evidence_ids,
    )


def latitude_ref_from_write_value(value: GpsValue) -> str | None:
    return gps_ref_from_write_value(value, "NS", "N", "S")


def longitude_ref_from_write_value(value: GpsValue) -> str | None:
    return gps_ref_from_write_value(value, "EW", "E", "W")


def gps_ref_from_write_value(
    value: GpsValue,
    letters: str,
    positive_ref: str,
    negative_ref: str,
) -> str | None:
    if isinstance(value, int | float):
        if not math.isfinite(float(value)):
            return None
        return negative_ref if value < 0 else positive_ref
    if not isinstance(value, str):
        return None
    upper_value = value.upper()
    for letter in letters:
        if re.search(rf"(^|[^A-Z]){letter}([A-Z]*)\b", upper_value):
            return letter
    number_match = re.search(r"([-+]?)\d+", value)
    if number_match is None:
        return None
    return negative_ref if number_match.group(1) == "-" else positive_ref


def altitude_ref_from_write_value(value: GpsValue) -> int | None:
    if isinstance(value, int | float):
        if not math.isfinite(float(value)):
            return None
        return 1 if value < 0 else 0
    if isinstance(value, str):
        match = re.match(r"^([-+0-9])", value.strip())
        if match is None:
            return None
        return 1 if match.group(1) == "-" else 0
    return None


def gps_coordinate_to_degrees(
    value: GpsValue,
    apply_cardinal_sign: bool = False,
    coord_kind: Literal["lat", "lon"] | None = None,
) -> float | None:
    if isinstance(value, int | float):
        coordinate = float(value)
        return coordinate if math.isfinite(coordinate) else None
    if isinstance(value, tuple):
        numeric_values = tuple(float(item) for item in value if isinstance(item, int | float))
        if len(numeric_values) != len(value) or not 1 <= len(numeric_values) <= 3:
            return None
        if any(not math.isfinite(item) for item in numeric_values):
            return None
        degrees = numeric_values[0]
        minutes = numeric_values[1] if len(numeric_values) > 1 else 0.0
        seconds = numeric_values[2] if len(numeric_values) > 2 else 0.0
        coordinate = degrees + (minutes + seconds / 60.0) / 60.0
        return -coordinate if degrees < 0 else coordinate
    if not isinstance(value, str):
        return None
    if re.search(r"\b(inf|undef)\b", value, flags=re.IGNORECASE):
        return None
    coordinate_text = extract_coordinate_part(value, coord_kind)
    numbers = re.findall(r"[+-]?(?=\d|\.\d)\d*(?:\.\d*)?(?:[Ee][+-]?\d+)?", coordinate_text)
    if not numbers:
        return None
    degrees = float(numbers[0])
    minutes = float(numbers[1]) if len(numbers) > 1 else 0.0
    seconds = float(numbers[2]) if len(numbers) > 2 else 0.0
    coordinate = degrees + (minutes + seconds / 60.0) / 60.0
    if apply_cardinal_sign and re.search(
        r"[^A-Z](S(outh)?|W(est)?)\s*$", coordinate_text, re.IGNORECASE
    ):
        coordinate = -coordinate
    return coordinate


def extract_coordinate_part(value: str, coord_kind: Literal["lat", "lon"] | None) -> str:
    if coord_kind is None:
        return value
    match = re.match(
        r"^(.*(?:N(?:orth)?|S(?:outh)?)),\s*(.*(?:E(?:ast)?|W(?:est)?))$",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        return value
    return match.group(1) if coord_kind == "lat" else match.group(2)


def gps_degrees_to_dms(value: float) -> tuple[int, int, float] | None:
    if not math.isfinite(value):
        return None
    absolute = abs(value)
    degrees = int(absolute)
    raw_minutes = (absolute - degrees) * 60.0
    minutes = int(raw_minutes)
    seconds = (raw_minutes - minutes) * 60.0
    if round(seconds, 10) >= 60.0:
        seconds = 0.0
        minutes += 1
    if minutes >= 60:
        minutes = 0
        degrees += 1
    return degrees, minutes, seconds


def unsigned_decimal_from_value(value: GpsValue) -> float | None:
    if isinstance(value, int | float):
        decimal = abs(float(value))
        return decimal if math.isfinite(decimal) else None
    if not isinstance(value, str):
        return None
    match = re.search(r"(?=\d|\.\d)\d*(?:\.\d*)?", value)
    if match is None:
        return None
    decimal = float(match.group(0))
    return decimal if math.isfinite(decimal) else None


def gps_timestamp_to_utc_time(value: GpsValue) -> str | None:
    if isinstance(value, tuple):
        numeric_values = tuple(float(item) for item in value if isinstance(item, int | float))
        if len(numeric_values) != 3:
            return None
        return normalize_timestamp_numbers(numeric_values)
    if not isinstance(value, str):
        return None
    working_value = value.strip()
    timezone_match = re.search(r"([-+])(\d{1,2}):?(\d{2})\s*(DST)?$", working_value, re.IGNORECASE)
    timezone_delta: timedelta | None = None
    if timezone_match is not None:
        sign = 1 if timezone_match.group(1) == "-" else -1
        timezone_delta = timedelta(
            hours=sign * int(timezone_match.group(2)),
            minutes=sign * int(timezone_match.group(3)),
        )
        working_value = working_value[: timezone_match.start()].strip()
    date_time_match = re.match(
        r"^[^\d]*\d{4}[^\d]*\d{1,2}[^\d]*\d{1,2}[^\d]*(\d{1,2})"
        r"[^\d]*(\d{2})[^\d]*(\d{2}(?:\.\d+)?)[^\d]*$",
        working_value,
    )
    time_match = date_time_match or re.match(
        r"^[^\d]*(\d{1,2})[^\d]*(\d{2})[^\d]*(\d{2}(?:\.\d+)?)[^\d]*$",
        working_value,
    )
    if time_match is None:
        return None
    hour = float(time_match.group(1))
    minute = float(time_match.group(2))
    second = float(time_match.group(3))
    if timezone_delta is not None:
        base_datetime = datetime(2000, 1, 1, int(hour), int(minute), tzinfo=UTC)
        shifted = base_datetime + timezone_delta
        hour = float(shifted.hour)
        minute = float(shifted.minute)
    return normalize_timestamp_numbers((hour, minute, second))


def normalize_timestamp_numbers(values: tuple[float, float, float]) -> str | None:
    hour, minute, second = values
    if any(not math.isfinite(item) for item in values):
        return None
    total_seconds = hour * 3600.0 + minute * 60.0 + second
    if total_seconds < 0:
        return None
    normalized_hour = int(total_seconds // 3600)
    total_seconds -= normalized_hour * 3600
    normalized_minute = int(total_seconds // 60)
    normalized_second = total_seconds - normalized_minute * 60
    second_text = f"{normalized_second:012.9f}".rstrip("0").rstrip(".")
    if normalized_second >= 60:
        second_text = "00"
        normalized_minute += 1
        if normalized_minute >= 60:
            normalized_minute = 0
            normalized_hour += 1
    if normalized_second < 10:
        second_text = f"0{second_text}"
    return f"{normalized_hour:02d}:{normalized_minute:02d}:{second_text}"


def gps_date_stamp_from_value(value: GpsValue) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = parse_timezone_datetime(value)
    if parsed is not None:
        utc_datetime = parsed.astimezone(UTC)
        return f"{utc_datetime.year:04d}:{utc_datetime.month:02d}:{utc_datetime.day:02d}"
    match = re.search(r"(\d{4}).*?(\d{2}).*?(\d{2})", value)
    if match is None:
        return None
    return f"{match.group(1)}:{match.group(2)}:{match.group(3)}"


def parse_timezone_datetime(value: str) -> datetime | None:
    match = re.match(
        r"^\D*(\d{4})\D+(\d{2})\D+(\d{2})\D+(\d{2})\D+(\d{2})\D+(\d{2}(?:\.\d+)?)"
        r"\s*([-+])(\d{1,2}):?(\d{2})\s*$",
        value,
    )
    if match is None:
        return None
    second_decimal = float(match.group(6))
    second = int(second_decimal)
    microsecond = round((second_decimal - second) * 1_000_000)
    offset_sign = 1 if match.group(7) == "+" else -1
    offset = timezone(
        timedelta(
            hours=offset_sign * int(match.group(8)),
            minutes=offset_sign * int(match.group(9)),
        )
    )
    return datetime(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
        int(match.group(5)),
        second,
        microsecond,
        tzinfo=offset,
    )


def coordinate_in_range(coordinate: float, coord_kind: Literal["lat", "lon"]) -> bool:
    if coord_kind == "lat":
        return -90.0 <= coordinate <= 90.0
    return -180.0 <= coordinate <= 180.0


def numeric_value_is_supported(value: GpsValue) -> bool:
    if isinstance(value, int | float):
        return math.isfinite(float(value))
    if isinstance(value, tuple):
        numeric_values = tuple(float(item) for item in value if isinstance(item, int | float))
        return len(numeric_values) == len(value) and all(
            math.isfinite(item) for item in numeric_values
        )
    if isinstance(value, str):
        return bool(re.search(r"[+-]?(?=\d|\.\d)\d*(?:\.\d*)?", value))
    return False


def gps_output_emission_gates(
    blockers: list[GpsTransactionBlocker],
    rewrite_requests: tuple[GpsRewriteRequest, ...],
) -> tuple[GpsOutputEmissionGate, ...]:
    gates = [
        GpsOutputEmissionGate(
            "planner_is_non_mutating",
            "GPS transaction planning records decisions but does not rewrite bytes.",
            (GPS_TABLE_SOURCE,),
        ),
        GpsOutputEmissionGate(
            "gps_ifd_writer_not_implemented",
            "GPS.pm routes writes through Exif::WriteExif; this slice does not port that writer.",
            (GPS_TABLE_SOURCE,),
        ),
    ]
    if rewrite_requests:
        gates.append(
            GpsOutputEmissionGate(
                "rewrite_requested_requires_gps_writer",
                "Requested GPS tag changes require an enabled GPS IFD writer.",
                (GPS_TABLE_SOURCE,),
            )
        )
    if any(blocker.code != "rewrite_requested_requires_gps_writer" for blocker in blockers):
        gates.append(
            GpsOutputEmissionGate(
                "malformed_gps_input_blocks_rewrite",
                "Malformed GPS values must be resolved before writer enablement.",
                (
                    GPS_COORD_CONV_SOURCE,
                    GPS_TIME_SOURCE,
                    GPS_DATE_SOURCE,
                ),
            )
        )
    return tuple(gates)


def gps_responsibilities(
    routed_tags: list[GpsRoutedTag],
    blockers: list[GpsTransactionBlocker],
    preserved_unknown_tags: list[GpsPreservedUnknownTag],
) -> tuple[GpsResponsibilityPlan, ...]:
    planned: list[GpsResponsibilityPlan] = [
        GpsResponsibilityPlan(
            "gps_ifd_table",
            "GPS.pm owns EXIF group 1 GPS tag routing.",
            (GPS_TABLE_SOURCE,),
        ),
        GpsResponsibilityPlan(
            "non_mutating_defaults",
            "The planner records decisions without emitting rewritten GPS IFD bytes.",
            (GPS_TABLE_SOURCE,),
        ),
    ]
    for kind in responsibility_order():
        if any(route.responsibility == kind for route in routed_tags):
            planned.append(
                GpsResponsibilityPlan(
                    kind,
                    responsibility_reason(kind),
                    responsibility_sources(kind),
                )
            )
    if preserved_unknown_tags:
        planned.append(
            GpsResponsibilityPlan(
                "unknown_tag_preservation",
                "Unrecognized GPS IFD entries are preserved rather than discarded.",
                (GPS_UNKNOWN_PADDING_SOURCE,),
            )
        )
    if any(blocker.code != "rewrite_requested_requires_gps_writer" for blocker in blockers):
        planned.append(
            GpsResponsibilityPlan(
                "malformed_input_blockers",
                "GPS.pm conversion boundaries define values that block rewrite planning.",
                (GPS_COORD_CONV_SOURCE, GPS_TIME_SOURCE, GPS_DATE_SOURCE),
            )
        )
    if any(blocker.code == "rewrite_requested_requires_gps_writer" for blocker in blockers):
        planned.append(
            GpsResponsibilityPlan(
                "rewrite_gate",
                "GPS rewrite requests are blocked until a GPS IFD writer exists.",
                (GPS_TABLE_SOURCE,),
            )
        )
    return tuple(planned)


def responsibility_order() -> tuple[GpsResponsibilityKind, ...]:
    return (
        "camera_location",
        "subject_location",
        "gps_time",
        "measurement_quality",
        "gps_motion",
        "image_direction",
        "gps_text",
        "read_only_composite",
    )


def responsibility_reason(kind: GpsResponsibilityKind) -> str:
    reasons: dict[GpsResponsibilityKind, str] = {
        "camera_location": "Camera-location GPS tags cover latitude, longitude, and altitude.",
        "subject_location": "Destination GPS tags cover subject location, bearing, and distance.",
        "gps_time": "GPS time tags normalize timestamp and date-stamp values.",
        "measurement_quality": (
            "Status, measure mode, DOP, differential, and error tags describe fix quality."
        ),
        "gps_motion": "Speed and track tags describe GPS motion.",
        "image_direction": "Image-direction tags describe camera orientation relative to north.",
        "gps_text": "Text GPS tags use GPS.pm string or EXIF text boundaries.",
        "read_only_composite": "Composite GPS tags are derived unless GPS.pm marks them writable.",
        "gps_ifd_table": "GPS.pm owns EXIF group 1 GPS tag routing.",
        "unknown_tag_preservation": "Unknown GPS tags remain preserved.",
        "malformed_input_blockers": "Malformed values block rewrite planning.",
        "rewrite_gate": "Rewrite requests require a writer.",
        "non_mutating_defaults": "Default planning is non-mutating.",
    }
    return reasons[kind]


def responsibility_sources(kind: GpsResponsibilityKind) -> tuple[str, ...]:
    sources: dict[GpsResponsibilityKind, tuple[str, ...]] = {
        "camera_location": (GPS_CAMERA_LOCATION_SOURCE, GPS_REF_CONV_SOURCE),
        "subject_location": (GPS_SUBJECT_LOCATION_SOURCE, GPS_REF_CONV_SOURCE),
        "gps_time": (GPS_TIME_SOURCE, GPS_DATE_SOURCE),
        "measurement_quality": (GPS_STATUS_QUALITY_SOURCE, GPS_DIFFERENTIAL_ERROR_SOURCE),
        "gps_motion": (GPS_MOTION_SOURCE,),
        "image_direction": (GPS_MOTION_SOURCE,),
        "gps_text": (GPS_TEXT_SOURCE,),
        "read_only_composite": (GPS_COMPOSITE_SOURCE,),
        "gps_ifd_table": (GPS_TABLE_SOURCE,),
        "unknown_tag_preservation": (GPS_UNKNOWN_PADDING_SOURCE,),
        "malformed_input_blockers": (GPS_COORD_CONV_SOURCE, GPS_TIME_SOURCE, GPS_DATE_SOURCE),
        "rewrite_gate": (GPS_TABLE_SOURCE,),
        "non_mutating_defaults": (GPS_TABLE_SOURCE,),
    }
    return sources[kind]


def dedupe_evidence_ids(
    evidence_ids: tuple[str, ...],
) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for evidence_id in evidence_ids:
        key = evidence_id
        if key in seen:
            continue
        seen.add(key)
        deduped.append(evidence_id)
    return tuple(deduped)
