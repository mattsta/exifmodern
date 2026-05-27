"""Source-backed, non-mutating Garmin FIT metadata transaction planning.

This first Garmin slice mirrors the routing and safety boundaries in
ExifTool's ``Garmin.pm`` for FIT files.  It validates the FIT header, records
local message definitions, routes data messages through source-backed tables,
preserves raw binary payloads, and records blockers instead of rewriting bytes.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

GARMIN_PM_SOURCE_PATH = "lib/Image/ExifTool/Garmin.pm"
FIT_SIGNATURE = b".FIT"
FIT_MIN_HEADER_SIZE = 12
FIT_DEFINITION_PREFIX_SIZE = 5
FIT_FIELD_DEFINITION_SIZE = 3
FIT_HEADER_CRC_SIZE = 2

type GarminEndian = Literal["little", "big"]
type GarminActionKind = Literal[
    "validate_fit_header",
    "record_definition",
    "route_data_message",
    "route_common_time",
    "preserve_payload",
    "preserve_unknown_record",
    "preserve_developer_payload",
    "route_developer_field",
    "block_requested_rewrite",
]
type GarminResponsibilityKind = Literal[
    "product_file_identity",
    "fit_table_routing",
    "gps_location",
    "time_correlation",
    "track_motion",
    "activity_summary",
    "device_identity",
    "binary_payload_preservation",
    "malformed_and_truncation_blockers",
    "unsupported_rewrite_gate",
    "non_mutating_defaults",
]
type GarminValueKind = Literal["integer", "real", "string", "binary"]
type GarminValueConversion = Literal[
    "activity_milliseconds",
    "altitude_meters",
    "centimeters_to_meters",
    "centi_degrees",
    "divide_by_10",
    "divide_by_100",
    "divide_by_128",
    "divide_by_256",
    "divide_by_1000",
    "divide_by_2",
    "divide_by_5",
    "divide_by_65536",
    "fit_epoch_seconds",
    "fractional_seconds_32768",
    "garmin_semicircles_degrees",
    "local_epoch_seconds",
    "meters_per_second_from_millimeters",
    "speed_kmh_from_millimeters",
    "software_version",
]
type GarminPrintConversion = Literal[
    "date_time_local",
    "date_time_with_zone",
    "garmin_latitude_dms",
    "garmin_longitude_dms",
    "unit_bpm",
    "unit_breaths_per_min",
    "unit_bar_per_min",
    "unit_cm_per_s",
    "unit_cycles",
    "unit_celsius",
    "unit_flow",
    "unit_gdl",
    "unit_if",
    "unit_joules",
    "unit_kg",
    "unit_kgrit",
    "unit_kcal",
    "unit_kmh",
    "unit_l_per_min",
    "unit_lengths",
    "unit_m",
    "unit_ml",
    "unit_mm",
    "unit_ms",
    "unit_newton",
    "unit_otus",
    "unit_pa",
    "unit_percent",
    "unit_mps",
    "unit_rpm",
    "unit_s",
    "unit_strokes_per_lap",
    "unit_tss",
    "unit_v",
    "unit_watts",
    "developer_units",
]
type GarminDecodedValue = int | float | str | bytes
type GarminFieldGroup = Literal[
    "product",
    "file",
    "gps",
    "time",
    "track",
    "activity",
    "device",
    "common",
    "unknown",
    "developer",
]
type GarminBlockerCode = Literal[
    "truncated_fit_header",
    "unsupported_fit_signature",
    "invalid_fit_header_size",
    "truncated_extended_fit_header",
    "truncated_definition_prefix",
    "truncated_definition_fields",
    "truncated_developer_definition",
    "missing_local_message_definition",
    "truncated_data_message",
    "unknown_fit_base_type",
    "bad_fit_field_count",
    "incomplete_developer_field_definition",
    "rewrite_requested_requires_fit_writer",
]
type GarminEmissionGateCode = Literal[
    "planner_is_non_mutating",
    "fit_writer_not_implemented",
    "rewrite_requested_requires_fit_writer",
    "malformed_fit_stream_blocks_rewrite",
    "unknown_fit_base_type_blocks_rewrite",
    "truncated_fit_stream_blocks_rewrite",
]
type GarminRewriteOperation = Literal["upsert_field", "delete_field"]


GARMIN_HEADER_SOURCE = "garmin.header"
GARMIN_BASE_TYPE_SOURCE = "garmin.base.type"
GARMIN_FILE_ENUM_SOURCE = "garmin.file.enum"
GARMIN_MESSAGE_TABLE_SOURCE = "garmin.message.table"
GARMIN_FIT_TABLE_SOURCE = "garmin.fit.table"
GARMIN_COMMON_SOURCE = "garmin.common"
GARMIN_FILE_ID_SOURCE = "garmin.file.id"
GARMIN_TIME_CORRELATION_SOURCE = "garmin.time.correlation"
GARMIN_ACTIVITY_SOURCE = "garmin.activity"
GARMIN_SESSION_SOURCE = "garmin.session"
GARMIN_LAP_SOURCE = "garmin.lap"
GARMIN_RECORD_SOURCE = "garmin.record"
GARMIN_DEVICE_INFO_SOURCE = "garmin.device.info"
GARMIN_GPS_SOURCE = "garmin.gps"
GARMIN_PROCESS_DEFINITION_SOURCE = "garmin.process.definition"
GARMIN_PROCESS_DATA_SOURCE = "garmin.process.data"
GARMIN_DEVELOPER_SOURCE = "garmin.developer"
GARMIN_READ_ONLY_SOURCE = "garmin.read.only"

GARMIN_TRANSACTION_SOURCES = (
    GARMIN_HEADER_SOURCE,
    GARMIN_BASE_TYPE_SOURCE,
    GARMIN_FILE_ENUM_SOURCE,
    GARMIN_MESSAGE_TABLE_SOURCE,
    GARMIN_FIT_TABLE_SOURCE,
    GARMIN_COMMON_SOURCE,
    GARMIN_FILE_ID_SOURCE,
    GARMIN_TIME_CORRELATION_SOURCE,
    GARMIN_ACTIVITY_SOURCE,
    GARMIN_SESSION_SOURCE,
    GARMIN_LAP_SOURCE,
    GARMIN_RECORD_SOURCE,
    GARMIN_DEVICE_INFO_SOURCE,
    GARMIN_GPS_SOURCE,
    GARMIN_PROCESS_DEFINITION_SOURCE,
    GARMIN_PROCESS_DATA_SOURCE,
    GARMIN_DEVELOPER_SOURCE,
    GARMIN_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class GarminBaseType:
    read_format: str
    fit_name: str
    size: int
    invalid_integer: int | None = None
    invalid_string: str | None = None


BASE_TYPES: dict[int, GarminBaseType] = {
    0x00: GarminBaseType("int8u", "enum", 1, 0xFF),
    0x01: GarminBaseType("int8s", "sint8", 1, 0x7F),
    0x02: GarminBaseType("int8u", "uint8", 1, 0xFF),
    0x83: GarminBaseType("int16s", "sint16", 2, 0x7FFF),
    0x84: GarminBaseType("int16u", "uint16", 2, 0xFFFF),
    0x85: GarminBaseType("int32s", "sint32", 4, 0x7FFFFFFF),
    0x86: GarminBaseType("int32u", "uint32", 4, 0xFFFFFFFF),
    0x07: GarminBaseType("string", "string", 1, invalid_string=""),
    0x88: GarminBaseType("float", "float32", 4),
    0x89: GarminBaseType("double", "float64", 8),
    0x0A: GarminBaseType("int8u", "uint8z", 1, 0),
    0x0D: GarminBaseType("undef", "byte", 1, 0xFF),
    0x8B: GarminBaseType("int16u", "uint16z", 2, 0),
    0x8C: GarminBaseType("int32u", "uint32z", 4, 0),
    0x8E: GarminBaseType("int64s", "sint64", 8, 0x7FFFFFFFFFFFFFFF),
    0x8F: GarminBaseType("int64u", "uint64", 8, 0xFFFFFFFFFFFFFFFF),
    0x90: GarminBaseType("int64u", "uint64z", 8, 0),
}

FILE_TYPES: dict[int, str] = {
    1: "Device",
    2: "Settings",
    3: "Sport",
    4: "Activity",
    5: "Workout",
    6: "Course",
    9: "Weight",
    10: "Totals",
    29: "Records",
    49: "Sleep",
    61: "ECG",
}


@dataclass(frozen=True)
class GarminFieldDefinition:
    tag_name: str
    group: GarminFieldGroup
    evidence_ids: tuple[str, ...]
    is_timestamp: bool = False
    preserve_binary: bool = False
    value_conversion: GarminValueConversion | None = None
    print_conversion: GarminPrintConversion | None = None
    print_suffix: str | None = None
    enum_values: dict[int, str] | None = None


@dataclass(frozen=True)
class GarminMessageDefinition:
    message_number: int
    message_name: str
    table_name: str
    evidence_ids: tuple[str, ...]
    unknown_by_default: bool
    fields: dict[int, GarminFieldDefinition]


COMMON_FIELDS: dict[int, GarminFieldDefinition] = {
    250: GarminFieldDefinition("PartIndex", "common", (GARMIN_COMMON_SOURCE,)),
    253: GarminFieldDefinition(
        "TimeStamp",
        "time",
        (GARMIN_COMMON_SOURCE,),
        is_timestamp=True,
        value_conversion="fit_epoch_seconds",
        print_conversion="date_time_with_zone",
    ),
    254: GarminFieldDefinition("MessageIndex", "common", (GARMIN_COMMON_SOURCE,)),
}


SPORT_ENUM = {
    0: "Generic",
    16: "Mountaineering",
    254: "All",
}
SUB_SPORT_ENUM = {
    0: "Generic",
    254: "All",
}
ACTIVITY_ENUM = {
    0: "Manual",
    1: "Auto Multi Sport",
}
ACTIVITY_TYPE_ENUM = {
    0: "Generic",
    1: "Running",
    2: "Cycling",
    3: "Transition",
    4: "Fitness Equipment",
    5: "Swimming",
    6: "Walking",
    8: "Sedentary",
    254: "All",
}
EVENT_ENUM = {
    8: "Session",
    9: "Lap",
}
EVENT_TYPE_ENUM = {
    0: "Start",
    1: "Stop",
}
INTENSITY_ENUM = {
    0: "Active",
    1: "Rest",
    2: "Warmup",
    3: "Cooldown",
    4: "Recovery",
    5: "Interval",
    6: "Other",
}
SESSION_TRIGGER_ENUM = {
    0: "Activity End",
    1: "Manual",
    2: "Auto Multi Sport",
    3: "Fitness Equipment",
}
LAP_TRIGGER_ENUM = {
    0: "Manual",
    1: "time",
    2: "Distance",
    3: "Position Start",
    4: "Position Lap",
    5: "Position Waypoint",
    6: "Position Marked",
    7: "Session End",
    8: "Fitness Equipment",
}
PRIMARY_BENEFIT_ENUM = {
    0: "No Benefit",
    1: "Recovery",
    2: "Base",
    3: "Tempo",
    4: "Threshold",
    5: "VO2 Max",
    6: "Anaerobic",
    7: "Sprint",
}


def _field(
    tag_name: str,
    group: GarminFieldGroup,
    source: str,
    *,
    value_conversion: GarminValueConversion | None = None,
    print_conversion: GarminPrintConversion | None = None,
    enum_values: dict[int, str] | None = None,
) -> GarminFieldDefinition:
    return GarminFieldDefinition(
        tag_name,
        group,
        (source,),
        value_conversion=value_conversion,
        print_conversion=print_conversion,
        enum_values=enum_values,
    )


def _time_field(tag_name: str, source: str) -> GarminFieldDefinition:
    return GarminFieldDefinition(
        tag_name,
        "time",
        (source,),
        is_timestamp=True,
        value_conversion="fit_epoch_seconds",
        print_conversion="date_time_with_zone",
    )


def _lat_field(tag_name: str, source: str) -> GarminFieldDefinition:
    return _field(
        tag_name,
        "gps",
        source,
        value_conversion="garmin_semicircles_degrees",
        print_conversion="garmin_latitude_dms",
    )


def _lon_field(tag_name: str, source: str) -> GarminFieldDefinition:
    return _field(
        tag_name,
        "gps",
        source,
        value_conversion="garmin_semicircles_degrees",
        print_conversion="garmin_longitude_dms",
    )


def _meters_field(tag_name: str, group: GarminFieldGroup, source: str) -> GarminFieldDefinition:
    return _field(
        tag_name,
        group,
        source,
        value_conversion="centimeters_to_meters",
        print_conversion="unit_m",
    )


def _alt_field(tag_name: str, source: str) -> GarminFieldDefinition:
    return _field(
        tag_name,
        "gps",
        source,
        value_conversion="altitude_meters",
        print_conversion="unit_m",
    )


def _mps_field(tag_name: str, group: GarminFieldGroup, source: str) -> GarminFieldDefinition:
    return _field(
        tag_name,
        group,
        source,
        value_conversion="meters_per_second_from_millimeters",
        print_conversion="unit_mps",
    )


def _ms_field(tag_name: str, source: str) -> GarminFieldDefinition:
    return _field(
        tag_name,
        "activity",
        source,
        value_conversion="activity_milliseconds",
        print_conversion="unit_s",
    )


def _unit_field(
    tag_name: str,
    group: GarminFieldGroup,
    source: str,
    print_conversion: GarminPrintConversion,
) -> GarminFieldDefinition:
    return _field(tag_name, group, source, print_conversion=print_conversion)


MESSAGE_DEFINITIONS: dict[int, GarminMessageDefinition] = {
    0: GarminMessageDefinition(
        0,
        "FileID",
        "Image::ExifTool::Garmin::FileID",
        (GARMIN_FIT_TABLE_SOURCE, GARMIN_FILE_ID_SOURCE),
        True,
        {
            0: GarminFieldDefinition("FITFileType", "file", (GARMIN_FILE_ID_SOURCE,)),
            1: GarminFieldDefinition("Manufacturer", "product", (GARMIN_FILE_ID_SOURCE,)),
            2: GarminFieldDefinition("Product", "product", (GARMIN_FILE_ID_SOURCE,)),
            3: GarminFieldDefinition("SerialNumber", "product", (GARMIN_FILE_ID_SOURCE,)),
            4: GarminFieldDefinition(
                "TimeCreated",
                "time",
                (GARMIN_FILE_ID_SOURCE,),
                value_conversion="fit_epoch_seconds",
                print_conversion="date_time_with_zone",
            ),
            5: GarminFieldDefinition("Number", "file", (GARMIN_FILE_ID_SOURCE,)),
            8: GarminFieldDefinition("ProductName", "product", (GARMIN_FILE_ID_SOURCE,)),
        },
    ),
    18: GarminMessageDefinition(
        18,
        "Session",
        "Image::ExifTool::Garmin::Session",
        (GARMIN_FIT_TABLE_SOURCE, GARMIN_SESSION_SOURCE),
        False,
        {
            0: _field("Event", "activity", GARMIN_SESSION_SOURCE, enum_values=EVENT_ENUM),
            1: _field("EventType", "activity", GARMIN_SESSION_SOURCE, enum_values=EVENT_TYPE_ENUM),
            2: GarminFieldDefinition(
                "GPSDateTime",
                "time",
                (GARMIN_SESSION_SOURCE,),
                is_timestamp=True,
                value_conversion="fit_epoch_seconds",
                print_conversion="date_time_with_zone",
            ),
            3: GarminFieldDefinition(
                "GPSLatitude",
                "gps",
                (GARMIN_SESSION_SOURCE,),
                value_conversion="garmin_semicircles_degrees",
                print_conversion="garmin_latitude_dms",
            ),
            4: GarminFieldDefinition(
                "GPSLongitude",
                "gps",
                (GARMIN_SESSION_SOURCE,),
                value_conversion="garmin_semicircles_degrees",
                print_conversion="garmin_longitude_dms",
            ),
            5: _field("Sport", "activity", GARMIN_SESSION_SOURCE, enum_values=SPORT_ENUM),
            6: _field("SubSport", "activity", GARMIN_SESSION_SOURCE, enum_values=SUB_SPORT_ENUM),
            7: _ms_field("TotalElapsedTime", GARMIN_SESSION_SOURCE),
            8: _ms_field("TotalTimerTime", GARMIN_SESSION_SOURCE),
            9: _meters_field("TotalDistance", "track", GARMIN_SESSION_SOURCE),
            10: _unit_field("TotalCycles", "activity", GARMIN_SESSION_SOURCE, "unit_cycles"),
            11: _unit_field("TotalCalories", "activity", GARMIN_SESSION_SOURCE, "unit_kcal"),
            13: _unit_field("TotalFatCalories", "activity", GARMIN_SESSION_SOURCE, "unit_kcal"),
            14: GarminFieldDefinition(
                "AvgSpeed",
                "track",
                (GARMIN_SESSION_SOURCE,),
                value_conversion="meters_per_second_from_millimeters",
                print_conversion="unit_mps",
            ),
            15: GarminFieldDefinition(
                "MaxSpeed",
                "track",
                (GARMIN_SESSION_SOURCE,),
                value_conversion="meters_per_second_from_millimeters",
                print_conversion="unit_mps",
            ),
            16: _unit_field("AvgHeartRate", "track", GARMIN_SESSION_SOURCE, "unit_bpm"),
            17: _unit_field("MaxHeartRate", "track", GARMIN_SESSION_SOURCE, "unit_bpm"),
            18: _unit_field("AvgCadence", "track", GARMIN_SESSION_SOURCE, "unit_rpm"),
            19: _unit_field("MaxCadence", "track", GARMIN_SESSION_SOURCE, "unit_rpm"),
            20: _unit_field("AvgPower", "track", GARMIN_SESSION_SOURCE, "unit_watts"),
            21: _unit_field("MaxPower", "track", GARMIN_SESSION_SOURCE, "unit_watts"),
            22: _unit_field("TotalAscent", "track", GARMIN_SESSION_SOURCE, "unit_m"),
            23: _unit_field("TotalDescent", "track", GARMIN_SESSION_SOURCE, "unit_m"),
            24: _field(
                "TotalTrainingEffect",
                "activity",
                GARMIN_SESSION_SOURCE,
                value_conversion="divide_by_10",
            ),
            25: GarminFieldDefinition("FirstLapIndex", "activity", (GARMIN_SESSION_SOURCE,)),
            26: GarminFieldDefinition("NumLaps", "activity", (GARMIN_SESSION_SOURCE,)),
            28: _field(
                "Trigger", "activity", GARMIN_SESSION_SOURCE, enum_values=SESSION_TRIGGER_ENUM
            ),
            29: _lat_field("NECLatitude", GARMIN_SESSION_SOURCE),
            30: _lon_field("NECLongitude", GARMIN_SESSION_SOURCE),
            31: _lat_field("SWCLatitude", GARMIN_SESSION_SOURCE),
            32: _lon_field("SWCLongitude", GARMIN_SESSION_SOURCE),
            33: _unit_field("NumLengths", "activity", GARMIN_SESSION_SOURCE, "unit_lengths"),
            38: _lat_field("GPSDestLatitude", GARMIN_SESSION_SOURCE),
            39: _lon_field("GPSDestLongitude", GARMIN_SESSION_SOURCE),
            41: _field(
                "AvgStrokeCount",
                "activity",
                GARMIN_SESSION_SOURCE,
                value_conversion="divide_by_10",
                print_conversion="unit_strokes_per_lap",
            ),
            42: _meters_field("AvgStrokeDistance", "track", GARMIN_SESSION_SOURCE),
            44: _meters_field("PoolLength", "track", GARMIN_SESSION_SOURCE),
            49: _alt_field("AvgAltitude", GARMIN_SESSION_SOURCE),
            50: _alt_field("MaxAltitude", GARMIN_SESSION_SOURCE),
            57: _unit_field("AvgTemperature", "activity", GARMIN_SESSION_SOURCE, "unit_celsius"),
            58: _unit_field("MaxTemperature", "activity", GARMIN_SESSION_SOURCE, "unit_celsius"),
            64: _unit_field("MinHeartRate", "track", GARMIN_SESSION_SOURCE, "unit_bpm"),
            69: _ms_field("AvgLapTime", GARMIN_SESSION_SOURCE),
            71: _alt_field("MinAltitude", GARMIN_SESSION_SOURCE),
            92: _field(
                "AvgFractionalCadence",
                "track",
                GARMIN_SESSION_SOURCE,
                value_conversion="divide_by_128",
                print_conversion="unit_rpm",
            ),
            93: _field(
                "MaxFractionalCadence",
                "track",
                GARMIN_SESSION_SOURCE,
                value_conversion="divide_by_128",
                print_conversion="unit_rpm",
            ),
            94: _field(
                "TotalFractionalCycles",
                "activity",
                GARMIN_SESSION_SOURCE,
                value_conversion="divide_by_128",
                print_conversion="unit_cycles",
            ),
            110: GarminFieldDefinition("SportProfileName", "activity", (GARMIN_SESSION_SOURCE,)),
            116: GarminFieldDefinition("AvgLeftPowerPhase", "track", (GARMIN_SESSION_SOURCE,)),
            117: GarminFieldDefinition("AvgLeftPowerPhasePeak", "track", (GARMIN_SESSION_SOURCE,)),
            118: GarminFieldDefinition("AvgRightPowerPhase", "track", (GARMIN_SESSION_SOURCE,)),
            119: GarminFieldDefinition("AvgRightPowerPhasePeak", "track", (GARMIN_SESSION_SOURCE,)),
            120: GarminFieldDefinition("AvgPowerPosition", "track", (GARMIN_SESSION_SOURCE,)),
            121: GarminFieldDefinition("MaxPowerPosition", "track", (GARMIN_SESSION_SOURCE,)),
            122: GarminFieldDefinition("AvgCadencePosition", "track", (GARMIN_SESSION_SOURCE,)),
            123: GarminFieldDefinition("MaxCadencePosition", "track", (GARMIN_SESSION_SOURCE,)),
            124: _mps_field("EnhancedAvgSpeed", "track", GARMIN_SESSION_SOURCE),
            125: _mps_field("EnhancedMaxSpeed", "track", GARMIN_SESSION_SOURCE),
            126: _alt_field("EnhancedAvgAltitude", GARMIN_SESSION_SOURCE),
            127: _alt_field("EnhancedMinAltitude", GARMIN_SESSION_SOURCE),
            128: _alt_field("EnhancedMaxAltitude", GARMIN_SESSION_SOURCE),
            137: _field(
                "TotalAnaerobicTrainingEffect",
                "activity",
                GARMIN_SESSION_SOURCE,
                value_conversion="divide_by_10",
            ),
            150: _unit_field("MinTemperature", "activity", GARMIN_SESSION_SOURCE, "unit_celsius"),
            151: GarminFieldDefinition("TotalSets", "activity", (GARMIN_SESSION_SOURCE,)),
            152: _field(
                "Volume",
                "activity",
                GARMIN_SESSION_SOURCE,
                value_conversion="centimeters_to_meters",
                print_conversion="unit_kg",
            ),
            168: _field(
                "TrainingLoadPeak",
                "activity",
                GARMIN_SESSION_SOURCE,
                value_conversion="divide_by_65536",
            ),
            178: _unit_field("EstSweatLoss", "activity", GARMIN_SESSION_SOURCE, "unit_ml"),
            188: _field(
                "PrimaryBenefit",
                "activity",
                GARMIN_SESSION_SOURCE,
                enum_values=PRIMARY_BENEFIT_ENUM,
            ),
            196: _unit_field("MetabolicCalories", "activity", GARMIN_SESSION_SOURCE, "unit_kcal"),
            215: GarminFieldDefinition(
                "BeginningBodyBattery", "activity", (GARMIN_SESSION_SOURCE,)
            ),
            216: GarminFieldDefinition("EndingBodyBattery", "activity", (GARMIN_SESSION_SOURCE,)),
        },
    ),
    19: GarminMessageDefinition(
        19,
        "Lap",
        "Image::ExifTool::Garmin::Lap",
        (GARMIN_FIT_TABLE_SOURCE, GARMIN_LAP_SOURCE),
        False,
        {
            0: _field("Event", "activity", GARMIN_LAP_SOURCE, enum_values=EVENT_ENUM),
            1: _field("EventType", "activity", GARMIN_LAP_SOURCE, enum_values=EVENT_TYPE_ENUM),
            2: _time_field("GPSDateTime", GARMIN_LAP_SOURCE),
            3: _lat_field("GPSLatitude", GARMIN_LAP_SOURCE),
            4: _lon_field("GPSLongitude", GARMIN_LAP_SOURCE),
            5: _lat_field("GPSDestLatitude", GARMIN_LAP_SOURCE),
            6: _lon_field("GPSDestLongitude", GARMIN_LAP_SOURCE),
            7: _ms_field("TotalElapsedTime", GARMIN_LAP_SOURCE),
            8: _ms_field("TotalTimerTime", GARMIN_LAP_SOURCE),
            9: _meters_field("TotalDistance", "track", GARMIN_LAP_SOURCE),
            10: _unit_field("TotalCycles", "activity", GARMIN_LAP_SOURCE, "unit_cycles"),
            11: _unit_field("TotalCalories", "activity", GARMIN_LAP_SOURCE, "unit_kcal"),
            12: _unit_field("TotalFatCalories", "activity", GARMIN_LAP_SOURCE, "unit_kcal"),
            13: _mps_field("AvgSpeed", "track", GARMIN_LAP_SOURCE),
            14: _mps_field("MaxSpeed", "track", GARMIN_LAP_SOURCE),
            15: _unit_field("AvgHeartRate", "track", GARMIN_LAP_SOURCE, "unit_bpm"),
            16: _unit_field("MaxHeartRate", "track", GARMIN_LAP_SOURCE, "unit_bpm"),
            17: _unit_field("AvgCadence", "track", GARMIN_LAP_SOURCE, "unit_rpm"),
            18: _unit_field("MaxCadence", "track", GARMIN_LAP_SOURCE, "unit_rpm"),
            19: _unit_field("AvgPower", "track", GARMIN_LAP_SOURCE, "unit_watts"),
            20: _unit_field("MaxPower", "track", GARMIN_LAP_SOURCE, "unit_watts"),
            21: _unit_field("TotalAscent", "track", GARMIN_LAP_SOURCE, "unit_m"),
            22: _unit_field("TotalDescent", "track", GARMIN_LAP_SOURCE, "unit_m"),
            23: _field("Intensity", "activity", GARMIN_LAP_SOURCE, enum_values=INTENSITY_ENUM),
            24: _field("LapTrigger", "activity", GARMIN_LAP_SOURCE, enum_values=LAP_TRIGGER_ENUM),
            25: _field("Sport", "activity", GARMIN_LAP_SOURCE, enum_values=SPORT_ENUM),
            27: _lat_field("NECLatitude", GARMIN_LAP_SOURCE),
            28: _lon_field("NECLongitude", GARMIN_LAP_SOURCE),
            29: _lat_field("SWCLatitude", GARMIN_LAP_SOURCE),
            30: _lon_field("SWCLongitude", GARMIN_LAP_SOURCE),
            32: _unit_field("NumLengths", "activity", GARMIN_LAP_SOURCE, "unit_lengths"),
            39: _field("SubSport", "activity", GARMIN_LAP_SOURCE, enum_values=SUB_SPORT_ENUM),
            42: _alt_field("AvgAltitude", GARMIN_LAP_SOURCE),
            43: _alt_field("MaxAltitude", GARMIN_LAP_SOURCE),
            50: _unit_field("AvgTemperature", "activity", GARMIN_LAP_SOURCE, "unit_celsius"),
            51: _unit_field("MaxTemperature", "activity", GARMIN_LAP_SOURCE, "unit_celsius"),
            62: _alt_field("MinAltitude", GARMIN_LAP_SOURCE),
            80: _field(
                "AvgFractionalCadence",
                "track",
                GARMIN_LAP_SOURCE,
                value_conversion="divide_by_128",
                print_conversion="unit_rpm",
            ),
            81: _field(
                "MaxFractionalCadence",
                "track",
                GARMIN_LAP_SOURCE,
                value_conversion="divide_by_128",
                print_conversion="unit_rpm",
            ),
            82: _field(
                "TotalFractionalCycles",
                "activity",
                GARMIN_LAP_SOURCE,
                value_conversion="divide_by_128",
                print_conversion="unit_cycles",
            ),
            102: GarminFieldDefinition("AvgLeftPowerPhase", "track", (GARMIN_LAP_SOURCE,)),
            103: GarminFieldDefinition("AvgLeftPowerPhasePeak", "track", (GARMIN_LAP_SOURCE,)),
            104: GarminFieldDefinition("AvgRightPowerPhase", "track", (GARMIN_LAP_SOURCE,)),
            105: GarminFieldDefinition("AvgRightPowerPhasePeak", "track", (GARMIN_LAP_SOURCE,)),
            106: GarminFieldDefinition("AvgPowerPosition", "track", (GARMIN_LAP_SOURCE,)),
            107: GarminFieldDefinition("MaxPowerPosition", "track", (GARMIN_LAP_SOURCE,)),
            108: GarminFieldDefinition("AvgCadencePosition", "track", (GARMIN_LAP_SOURCE,)),
            109: GarminFieldDefinition("MaxCadencePosition", "track", (GARMIN_LAP_SOURCE,)),
            110: _mps_field("EnhancedAvgSpeed", "track", GARMIN_LAP_SOURCE),
            111: _mps_field("EnhancedMaxSpeed", "track", GARMIN_LAP_SOURCE),
            112: _alt_field("EnhancedAvgAltitude", GARMIN_LAP_SOURCE),
            113: _alt_field("EnhancedMinAltitude", GARMIN_LAP_SOURCE),
            114: _alt_field("EnhancedMaxAltitude", GARMIN_LAP_SOURCE),
            124: _unit_field("MinTemperature", "activity", GARMIN_LAP_SOURCE, "unit_celsius"),
            145: GarminFieldDefinition("EstSweatLoss", "activity", (GARMIN_LAP_SOURCE,)),
            155: _unit_field("RestingCalories", "activity", GARMIN_LAP_SOURCE, "unit_kcal"),
        },
    ),
    20: GarminMessageDefinition(
        20,
        "Record",
        "Image::ExifTool::Garmin::Record",
        (GARMIN_FIT_TABLE_SOURCE, GARMIN_RECORD_SOURCE),
        False,
        {
            0: GarminFieldDefinition(
                "GPSLatitude",
                "gps",
                (GARMIN_RECORD_SOURCE,),
                value_conversion="garmin_semicircles_degrees",
                print_conversion="garmin_latitude_dms",
            ),
            1: GarminFieldDefinition(
                "GPSLongitude",
                "gps",
                (GARMIN_RECORD_SOURCE,),
                value_conversion="garmin_semicircles_degrees",
                print_conversion="garmin_longitude_dms",
            ),
            2: GarminFieldDefinition(
                "GPSAltitude",
                "gps",
                (GARMIN_RECORD_SOURCE,),
                value_conversion="altitude_meters",
                print_conversion="unit_m",
            ),
            3: GarminFieldDefinition(
                "HeartRate", "track", (GARMIN_RECORD_SOURCE,), print_conversion="unit_bpm"
            ),
            4: GarminFieldDefinition(
                "Cadence", "track", (GARMIN_RECORD_SOURCE,), print_conversion="unit_rpm"
            ),
            5: GarminFieldDefinition(
                "Distance",
                "track",
                (GARMIN_RECORD_SOURCE,),
                value_conversion="centimeters_to_meters",
                print_conversion="unit_m",
            ),
            6: GarminFieldDefinition(
                "GPSSpeed",
                "track",
                (GARMIN_RECORD_SOURCE,),
                value_conversion="speed_kmh_from_millimeters",
                print_conversion="unit_kmh",
            ),
            7: GarminFieldDefinition("Power", "track", (GARMIN_RECORD_SOURCE,)),
            8: GarminFieldDefinition(
                "CompressedSpeedDistance",
                "track",
                (GARMIN_RECORD_SOURCE,),
                preserve_binary=True,
            ),
            9: _field(
                "Grade",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_100",
                print_conversion="unit_percent",
            ),
            10: GarminFieldDefinition("Resistance", "track", (GARMIN_RECORD_SOURCE,)),
            11: _field(
                "TimeFromCourse",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="activity_milliseconds",
                print_conversion="unit_s",
            ),
            12: _meters_field("CycleLength", "track", GARMIN_RECORD_SOURCE),
            13: _unit_field("Temperature", "track", GARMIN_RECORD_SOURCE, "unit_celsius"),
            18: _unit_field("Cycles", "track", GARMIN_RECORD_SOURCE, "unit_cycles"),
            19: _unit_field("TotalCycles", "track", GARMIN_RECORD_SOURCE, "unit_cycles"),
            28: _unit_field(
                "CompressedAccumulatedPower", "track", GARMIN_RECORD_SOURCE, "unit_watts"
            ),
            29: _unit_field("AccumulatedPower", "track", GARMIN_RECORD_SOURCE, "unit_watts"),
            31: _unit_field("GPSAccuracy", "gps", GARMIN_RECORD_SOURCE, "unit_m"),
            32: GarminFieldDefinition(
                "VerticalSpeed",
                "track",
                (GARMIN_RECORD_SOURCE,),
                value_conversion="meters_per_second_from_millimeters",
                print_conversion="unit_mps",
            ),
            33: _unit_field("Calories", "activity", GARMIN_RECORD_SOURCE, "unit_kcal"),
            39: _field(
                "VerticalOscillation",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_10",
                print_conversion="unit_mm",
            ),
            40: _field(
                "StanceTimePercent",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_100",
                print_conversion="unit_percent",
            ),
            41: _field(
                "StanceTime",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_10",
                print_conversion="unit_ms",
            ),
            42: _field(
                "ActivityType", "activity", GARMIN_RECORD_SOURCE, enum_values=ACTIVITY_TYPE_ENUM
            ),
            43: _field(
                "LeftTorqueEffectiveness",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_2",
                print_conversion="unit_percent",
            ),
            44: _field(
                "RightTorqueEffectiveness",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_2",
                print_conversion="unit_percent",
            ),
            45: _field(
                "LeftPedalSmoothness",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_2",
                print_conversion="unit_percent",
            ),
            46: _field(
                "RightPedalSmoothness",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_2",
                print_conversion="unit_percent",
            ),
            47: _field(
                "CombinedPedalSmoothness",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_2",
                print_conversion="unit_percent",
            ),
            48: _field(
                "Time128",
                "time",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_128",
                print_conversion="unit_s",
            ),
            51: _field(
                "BallSpeed",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_100",
                print_conversion="unit_mps",
            ),
            52: _field(
                "Cadence256",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_100",
                print_conversion="unit_rpm",
            ),
            53: _field(
                "FractionalCadence",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_128",
                print_conversion="unit_rpm",
            ),
            73: GarminFieldDefinition(
                "GPSSpeed",
                "track",
                (GARMIN_RECORD_SOURCE,),
                value_conversion="speed_kmh_from_millimeters",
                print_conversion="unit_kmh",
            ),
            78: GarminFieldDefinition(
                "GPSAltitude",
                "gps",
                (GARMIN_RECORD_SOURCE,),
                value_conversion="altitude_meters",
                print_conversion="unit_m",
            ),
            81: _field(
                "BatterySoc",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_2",
                print_conversion="unit_percent",
            ),
            82: _unit_field("MotorPower", "track", GARMIN_RECORD_SOURCE, "unit_watts"),
            83: _field(
                "VerticalRatio",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_100",
                print_conversion="unit_percent",
            ),
            84: _field(
                "StanceTimeBalance",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_100",
                print_conversion="unit_percent",
            ),
            85: _field(
                "StepLength",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_10",
                print_conversion="unit_mm",
            ),
            87: _meters_field("CycleLength16", "track", GARMIN_RECORD_SOURCE),
            91: _unit_field("AbsolutePressure", "track", GARMIN_RECORD_SOURCE, "unit_pa"),
            92: _field(
                "Depth",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_1000",
                print_conversion="unit_m",
            ),
            108: _field(
                "EnhancedRespirationRate",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_100",
                print_conversion="unit_breaths_per_min",
            ),
            116: _field(
                "CurrentStress", "activity", GARMIN_RECORD_SOURCE, value_conversion="divide_by_100"
            ),
            121: _unit_field("TotalAscent", "track", GARMIN_RECORD_SOURCE, "unit_m"),
            136: _unit_field("WristHeartRate", "track", GARMIN_RECORD_SOURCE, "unit_bpm"),
            139: _field(
                "CoreTemperature",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_100",
                print_conversion="unit_celsius",
            ),
            140: _mps_field("GradeAdjustedSpeed", "track", GARMIN_RECORD_SOURCE),
            143: GarminFieldDefinition("BodyBattery", "activity", (GARMIN_RECORD_SOURCE,)),
            144: _unit_field("ExternalHeartRate", "track", GARMIN_RECORD_SOURCE, "unit_bpm"),
            146: _field(
                "StepSpeedLossDistance",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_100",
                print_conversion="unit_cm_per_s",
            ),
            147: _field(
                "StepSpeedLossPercentage",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_100",
                print_conversion="unit_percent",
            ),
            148: _field(
                "Force",
                "track",
                GARMIN_RECORD_SOURCE,
                value_conversion="divide_by_1000",
                print_conversion="unit_newton",
            ),
        },
    ),
    23: GarminMessageDefinition(
        23,
        "DeviceInfo",
        "Image::ExifTool::Garmin::DeviceInfo",
        (GARMIN_FIT_TABLE_SOURCE, GARMIN_DEVICE_INFO_SOURCE),
        True,
        {
            0: GarminFieldDefinition("DeviceIndex", "device", (GARMIN_DEVICE_INFO_SOURCE,)),
            1: GarminFieldDefinition("DeviceType", "device", (GARMIN_DEVICE_INFO_SOURCE,)),
            2: GarminFieldDefinition("Manufacturer", "device", (GARMIN_DEVICE_INFO_SOURCE,)),
            3: GarminFieldDefinition("SerialNumber", "device", (GARMIN_DEVICE_INFO_SOURCE,)),
            4: GarminFieldDefinition("Product", "device", (GARMIN_DEVICE_INFO_SOURCE,)),
            5: GarminFieldDefinition(
                "SoftwareVersion",
                "device",
                (GARMIN_DEVICE_INFO_SOURCE,),
                value_conversion="software_version",
            ),
            6: GarminFieldDefinition("HardwareVersion", "device", (GARMIN_DEVICE_INFO_SOURCE,)),
            7: _unit_field("CumOperatingTime", "device", GARMIN_DEVICE_INFO_SOURCE, "unit_s"),
            10: _field(
                "BatteryVoltage",
                "device",
                GARMIN_DEVICE_INFO_SOURCE,
                value_conversion="divide_by_256",
                print_conversion="unit_v",
            ),
            27: GarminFieldDefinition("ProductName", "device", (GARMIN_DEVICE_INFO_SOURCE,)),
            32: _unit_field("BatteryLevel", "device", GARMIN_DEVICE_INFO_SOURCE, "unit_percent"),
        },
    ),
    34: GarminMessageDefinition(
        34,
        "Activity",
        "Image::ExifTool::Garmin::Activity",
        (GARMIN_FIT_TABLE_SOURCE, GARMIN_ACTIVITY_SOURCE),
        True,
        {
            0: GarminFieldDefinition(
                "TotalTimerTime",
                "activity",
                (GARMIN_ACTIVITY_SOURCE,),
                value_conversion="activity_milliseconds",
                print_conversion="unit_s",
            ),
            1: GarminFieldDefinition("NumSessions", "activity", (GARMIN_ACTIVITY_SOURCE,)),
            2: _field(
                "ActivityType", "activity", GARMIN_ACTIVITY_SOURCE, enum_values=ACTIVITY_ENUM
            ),
            3: _field("Event", "activity", GARMIN_ACTIVITY_SOURCE, enum_values=EVENT_ENUM),
            4: _field("EventType", "activity", GARMIN_ACTIVITY_SOURCE, enum_values=EVENT_TYPE_ENUM),
            5: GarminFieldDefinition(
                "LocalTimeStamp",
                "time",
                (GARMIN_ACTIVITY_SOURCE,),
                value_conversion="local_epoch_seconds",
                print_conversion="date_time_local",
            ),
        },
    ),
    160: GarminMessageDefinition(
        160,
        "GPS",
        "Image::ExifTool::Garmin::GPS",
        (GARMIN_FIT_TABLE_SOURCE, GARMIN_GPS_SOURCE),
        False,
        {
            0: GarminFieldDefinition("TimeStamp_ms", "time", (GARMIN_GPS_SOURCE,)),
            1: GarminFieldDefinition(
                "GPSLatitude",
                "gps",
                (GARMIN_GPS_SOURCE,),
                value_conversion="garmin_semicircles_degrees",
                print_conversion="garmin_latitude_dms",
            ),
            2: GarminFieldDefinition(
                "GPSLongitude",
                "gps",
                (GARMIN_GPS_SOURCE,),
                value_conversion="garmin_semicircles_degrees",
                print_conversion="garmin_longitude_dms",
            ),
            3: GarminFieldDefinition(
                "GPSAltitude",
                "gps",
                (GARMIN_GPS_SOURCE,),
                value_conversion="altitude_meters",
                print_conversion="unit_m",
            ),
            4: GarminFieldDefinition(
                "GPSSpeed",
                "track",
                (GARMIN_GPS_SOURCE,),
                value_conversion="speed_kmh_from_millimeters",
                print_conversion="unit_kmh",
            ),
            5: GarminFieldDefinition(
                "GPSTrack",
                "track",
                (GARMIN_GPS_SOURCE,),
                value_conversion="centi_degrees",
            ),
            6: GarminFieldDefinition(
                "GPSDateTime",
                "time",
                (GARMIN_GPS_SOURCE,),
                True,
                value_conversion="fit_epoch_seconds",
                print_conversion="date_time_with_zone",
            ),
            7: GarminFieldDefinition(
                "Velocity", "track", (GARMIN_GPS_SOURCE,), preserve_binary=True
            ),
        },
    ),
    162: GarminMessageDefinition(
        162,
        "TimeStampCorrelation",
        "Image::ExifTool::Garmin::TimeStampCorrelation",
        (GARMIN_FIT_TABLE_SOURCE, GARMIN_TIME_CORRELATION_SOURCE),
        True,
        {
            0: GarminFieldDefinition(
                "FractionalTimeStamp",
                "time",
                (GARMIN_TIME_CORRELATION_SOURCE,),
                value_conversion="fractional_seconds_32768",
                print_conversion="unit_s",
            ),
            1: GarminFieldDefinition(
                "SystemTimeStamp",
                "time",
                (GARMIN_TIME_CORRELATION_SOURCE,),
                value_conversion="fit_epoch_seconds",
                print_conversion="date_time_with_zone",
            ),
            2: GarminFieldDefinition(
                "FractionalSystemTimeStamp",
                "time",
                (GARMIN_TIME_CORRELATION_SOURCE,),
                value_conversion="fractional_seconds_32768",
                print_conversion="unit_s",
            ),
            3: GarminFieldDefinition(
                "LocalTimeStamp",
                "time",
                (GARMIN_TIME_CORRELATION_SOURCE,),
                value_conversion="local_epoch_seconds",
                print_conversion="date_time_local",
            ),
            4: GarminFieldDefinition(
                "TimeStamp_ms",
                "time",
                (GARMIN_TIME_CORRELATION_SOURCE,),
                print_conversion="unit_ms",
            ),
            5: GarminFieldDefinition(
                "SystemTimeStamp_ms",
                "time",
                (GARMIN_TIME_CORRELATION_SOURCE,),
                print_conversion="unit_ms",
            ),
        },
    ),
    206: GarminMessageDefinition(
        206,
        "FieldDescription",
        "Image::ExifTool::Garmin::FieldDescription",
        (GARMIN_FIT_TABLE_SOURCE, GARMIN_DEVELOPER_SOURCE),
        True,
        {
            0: GarminFieldDefinition("DeveloperDataIndex", "developer", (GARMIN_DEVELOPER_SOURCE,)),
            1: GarminFieldDefinition(
                "FieldDefinitionNumber", "developer", (GARMIN_DEVELOPER_SOURCE,)
            ),
            2: GarminFieldDefinition("FitBaseTypeID", "developer", (GARMIN_DEVELOPER_SOURCE,)),
            3: GarminFieldDefinition("FieldName", "developer", (GARMIN_DEVELOPER_SOURCE,)),
            8: GarminFieldDefinition("Units", "developer", (GARMIN_DEVELOPER_SOURCE,)),
        },
    ),
    207: GarminMessageDefinition(
        207,
        "DeveloperDataID",
        "Image::ExifTool::Garmin::DeveloperDataID",
        (GARMIN_FIT_TABLE_SOURCE, GARMIN_DEVELOPER_SOURCE),
        True,
        {
            0: GarminFieldDefinition(
                "DeveloperID", "developer", (GARMIN_DEVELOPER_SOURCE,), preserve_binary=True
            ),
            1: GarminFieldDefinition(
                "ApplicationID", "developer", (GARMIN_DEVELOPER_SOURCE,), preserve_binary=True
            ),
            2: GarminFieldDefinition("ManufacturerID", "developer", (GARMIN_DEVELOPER_SOURCE,)),
            3: GarminFieldDefinition("DeveloperDataIndex", "developer", (GARMIN_DEVELOPER_SOURCE,)),
            4: GarminFieldDefinition("ApplicationVersion", "developer", (GARMIN_DEVELOPER_SOURCE,)),
        },
    ),
}


@dataclass(frozen=True)
class GarminRewriteRequest:
    operation: GarminRewriteOperation
    message_name: str
    field_name: str
    value: GarminDecodedValue | None = None


@dataclass(frozen=True)
class GarminTransactionBlocker:
    code: GarminBlockerCode
    reason: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GarminOutputEmissionGate:
    code: GarminEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GarminFitHeaderPlan:
    header_size: int | None
    protocol_version: int | None
    data_size: int | None
    data_start_offset: int | None
    data_end_offset: int | None
    signature: bytes
    is_supported_fit: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "data_end_offset": self.data_end_offset,
            "data_size": self.data_size,
            "data_start_offset": self.data_start_offset,
            "header_size": self.header_size,
            "is_supported_fit": self.is_supported_fit,
            "protocol_version": self.protocol_version,
            "signature": self.signature.decode("ascii", errors="replace"),
        }


@dataclass(frozen=True)
class GarminFieldLayoutPlan:
    field_number: int
    size: int
    base_type: int
    byte_offset: int
    developer_index: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GarminLocalMessageDefinitionPlan:
    local_number: int
    message_number: int
    message_name: str
    table_name: str
    byte_order: GarminEndian
    definition_range: tuple[int, int]
    data_size: int
    fields: tuple[GarminFieldLayoutPlan, ...]
    developer_fields: tuple[GarminFieldLayoutPlan, ...]
    extracts_by_default: bool
    extracts_unknown_fields: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GarminDecodedFieldPlan:
    message_name: str
    field_number: int | str
    field_name: str
    group: GarminFieldGroup
    value_kind: GarminValueKind
    value: GarminDecodedValue
    print_value: str | None
    raw_range: tuple[int, int]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        value: JsonValue
        value = self.value.hex() if isinstance(self.value, bytes) else self.value
        return {
            "field_name": self.field_name,
            "field_number": str(self.field_number),
            "group": self.group,
            "message_name": self.message_name,
            "print_value": self.print_value,
            "raw_range": [self.raw_range[0], self.raw_range[1]],
            "value": value,
            "value_kind": self.value_kind,
        }


@dataclass(frozen=True)
class GarminDataMessagePlan:
    local_number: int
    message_number: int
    message_name: str
    record_range: tuple[int, int]
    payload_range: tuple[int, int]
    action: GarminActionKind
    fields: tuple[GarminDecodedFieldPlan, ...]
    preserved_payload: bytes
    skipped_by_default: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GarminResponsibilityPlan:
    kind: GarminResponsibilityKind
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GarminActionPlan:
    action: GarminActionKind
    target: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GarminMetadataTransactionPlan:
    source_payload: bytes
    header: GarminFitHeaderPlan
    definitions: tuple[GarminLocalMessageDefinitionPlan, ...]
    data_messages: tuple[GarminDataMessagePlan, ...]
    decoded_fields: tuple[GarminDecodedFieldPlan, ...]
    preserved_unknown_records: tuple[GarminDataMessagePlan, ...]
    actions: tuple[GarminActionPlan, ...]
    responsibilities: tuple[GarminResponsibilityPlan, ...]
    rewrite_requests: tuple[GarminRewriteRequest, ...]
    blockers: tuple[GarminTransactionBlocker, ...]
    output_emission_gates: tuple[GarminOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not self.output_emission_gates

    def emit(self) -> bytes:
        if self.output_emission_gates:
            codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Garmin FIT metadata transaction output is gated: {codes}")
        return self.source_payload


@dataclass(frozen=True)
class _MessageRuntimeDefinition:
    local_number: int
    message_number: int
    message_name: str
    table_name: str
    byte_order: GarminEndian
    fields: tuple[GarminFieldLayoutPlan, ...]
    developer_fields: tuple[GarminFieldLayoutPlan, ...]
    data_size: int
    extracts_by_default: bool
    extracts_unknown_fields: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class _DeveloperFieldDescription:
    developer_index: int
    field_number: int
    base_type: int
    field_name: str
    units: str


@dataclass(frozen=True)
class _DeveloperDataIdentifier:
    developer_index: int
    application_id: bytes


@dataclass(frozen=True)
class _DecodedFieldsResult:
    fields: tuple[GarminDecodedFieldPlan, ...]
    standard_field_values: dict[int, GarminDecodedValue]
    raw_standard_field_values: dict[int, GarminDecodedValue]
    developer_field_values: dict[int | str, GarminDecodedValue]


@dataclass(frozen=True)
class _ReadDataMessageResult:
    next_pos: int
    timestamp: int | None


def build_garmin_metadata_transaction_plan(
    source_payload: bytes,
    rewrite_requests: tuple[GarminRewriteRequest, ...] = (),
    *,
    extract_unknown: bool = False,
    extract_embedded: bool = False,
) -> GarminMetadataTransactionPlan:
    header = _read_fit_header(source_payload)
    definitions: list[GarminLocalMessageDefinitionPlan] = []
    data_messages: list[GarminDataMessagePlan] = []
    fields: list[GarminDecodedFieldPlan] = []
    actions: list[GarminActionPlan] = [
        GarminActionPlan(
            "validate_fit_header",
            "FIT header",
            (0, min(len(source_payload), FIT_MIN_HEADER_SIZE)),
            (GARMIN_HEADER_SOURCE,),
        )
    ]
    blockers: list[GarminTransactionBlocker] = []
    gates: list[GarminOutputEmissionGate] = []
    runtime: dict[int, _MessageRuntimeDefinition] = {}
    developer_descriptions: dict[tuple[int, int], _DeveloperFieldDescription] = {}
    developer_identifiers: dict[int, _DeveloperDataIdentifier] = {}
    seen_messages: set[int] = set()

    header_blocker = _header_blocker(source_payload, header)
    if header_blocker is not None:
        blockers.append(header_blocker)
    elif header.data_start_offset is not None and header.data_end_offset is not None:
        _walk_fit_records(
            source_payload,
            header.data_start_offset,
            min(header.data_end_offset, len(source_payload)),
            runtime,
            developer_descriptions,
            developer_identifiers,
            seen_messages,
            definitions,
            data_messages,
            fields,
            actions,
            blockers,
            extract_unknown,
            extract_embedded,
        )

    if rewrite_requests:
        blockers.append(
            GarminTransactionBlocker(
                "rewrite_requested_requires_fit_writer",
                "Garmin.pm provides read-side FIT routing only; this slice does not rewrite.",
                None,
                (GARMIN_READ_ONLY_SOURCE,),
            )
        )
        actions.append(
            GarminActionPlan(
                "block_requested_rewrite",
                "rewrite request",
                None,
                (GARMIN_READ_ONLY_SOURCE,),
            )
        )

    gates.extend(_output_gates(blockers, rewrite_requests))

    return GarminMetadataTransactionPlan(
        source_payload=source_payload,
        header=header,
        definitions=tuple(definitions),
        data_messages=tuple(data_messages),
        decoded_fields=tuple(fields),
        preserved_unknown_records=tuple(
            message
            for message in data_messages
            if message.action in {"preserve_unknown_record", "preserve_developer_payload"}
        ),
        actions=tuple(actions),
        responsibilities=_responsibilities(),
        rewrite_requests=rewrite_requests,
        blockers=tuple(blockers),
        output_emission_gates=tuple(gates),
        evidence_ids=GARMIN_TRANSACTION_SOURCES,
    )


def _read_fit_header(source_payload: bytes) -> GarminFitHeaderPlan:
    if len(source_payload) < FIT_MIN_HEADER_SIZE:
        return GarminFitHeaderPlan(
            None,
            None,
            None,
            None,
            None,
            source_payload[8:12],
            False,
            (GARMIN_HEADER_SOURCE,),
        )
    header_size = source_payload[0]
    protocol_version = source_payload[1]
    data_size = int.from_bytes(source_payload[4:8], "little")
    signature = source_payload[8:12]
    data_start = header_size if header_size >= FIT_MIN_HEADER_SIZE else None
    data_end = data_start + data_size if data_start is not None else None
    return GarminFitHeaderPlan(
        header_size,
        protocol_version,
        data_size,
        data_start,
        data_end,
        signature,
        signature == FIT_SIGNATURE and data_start is not None,
        (GARMIN_HEADER_SOURCE,),
    )


def _header_blocker(
    source_payload: bytes, header: GarminFitHeaderPlan
) -> GarminTransactionBlocker | None:
    if len(source_payload) < FIT_MIN_HEADER_SIZE:
        return GarminTransactionBlocker(
            "truncated_fit_header",
            "A FIT header requires at least the 12 bytes read by Garmin.pm.",
            (0, len(source_payload)),
            (GARMIN_HEADER_SOURCE,),
        )
    if header.signature != FIT_SIGNATURE:
        return GarminTransactionBlocker(
            "unsupported_fit_signature",
            "Garmin.pm accepts FIT data only when bytes 8..11 are .FIT.",
            (8, 12),
            (GARMIN_HEADER_SOURCE,),
        )
    if header.header_size is None or header.header_size < FIT_MIN_HEADER_SIZE:
        return GarminTransactionBlocker(
            "invalid_fit_header_size",
            "FIT header size was smaller than the minimum ProcessFIT header read.",
            (0, 1),
            (GARMIN_HEADER_SOURCE,),
        )
    if len(source_payload) < header.header_size:
        return GarminTransactionBlocker(
            "truncated_extended_fit_header",
            "The declared FIT header length extends beyond the available payload.",
            (0, len(source_payload)),
            (GARMIN_HEADER_SOURCE,),
        )
    return None


def _walk_fit_records(
    source_payload: bytes,
    data_start: int,
    data_end: int,
    runtime: dict[int, _MessageRuntimeDefinition],
    developer_descriptions: dict[tuple[int, int], _DeveloperFieldDescription],
    developer_identifiers: dict[int, _DeveloperDataIdentifier],
    seen_messages: set[int],
    definitions: list[GarminLocalMessageDefinitionPlan],
    data_messages: list[GarminDataMessagePlan],
    decoded_fields: list[GarminDecodedFieldPlan],
    actions: list[GarminActionPlan],
    blockers: list[GarminTransactionBlocker],
    extract_unknown: bool,
    extract_embedded: bool,
) -> None:
    pos = data_start
    timestamp = 0
    while pos < data_end:
        record_start = pos
        flags = source_payload[pos]
        pos += 1
        if flags & 0x80:
            local_number = (flags >> 5) & 0x03
            time_offset = flags & 0x1F
            compressed_timestamp: int | None = None
            if time_offset:
                low_bits = timestamp & 0x1F
                compressed_timestamp = (timestamp & 0xFFFFFFE0) + time_offset
                if time_offset < low_bits:
                    compressed_timestamp += 0x20
            result = _read_data_message(
                source_payload,
                data_end,
                record_start,
                pos,
                local_number,
                compressed_timestamp,
                runtime,
                developer_descriptions,
                developer_identifiers,
                seen_messages,
                data_messages,
                decoded_fields,
                actions,
                blockers,
                extract_embedded,
            )
            pos = result.next_pos
            if result.timestamp is not None:
                timestamp = result.timestamp
            if blockers and blockers[-1].byte_range == (record_start, data_end):
                return
            continue
        local_number = flags & 0x0F
        if flags & 0x40:
            parsed = _read_definition_message(
                source_payload,
                data_end,
                record_start,
                pos,
                local_number,
                flags,
                extract_unknown,
                definitions,
                actions,
                blockers,
            )
            if parsed is None:
                return
            runtime[local_number] = parsed[0]
            pos = parsed[1]
            continue
        result = _read_data_message(
            source_payload,
            data_end,
            record_start,
            pos,
            local_number,
            None,
            runtime,
            developer_descriptions,
            developer_identifiers,
            seen_messages,
            data_messages,
            decoded_fields,
            actions,
            blockers,
            extract_embedded,
        )
        pos = result.next_pos
        if result.timestamp is not None:
            timestamp = result.timestamp
        if blockers and blockers[-1].byte_range == (record_start, data_end):
            return


def _read_definition_message(
    source_payload: bytes,
    data_end: int,
    record_start: int,
    pos: int,
    local_number: int,
    flags: int,
    extract_unknown: bool,
    definitions: list[GarminLocalMessageDefinitionPlan],
    actions: list[GarminActionPlan],
    blockers: list[GarminTransactionBlocker],
) -> tuple[_MessageRuntimeDefinition, int] | None:
    if pos + FIT_DEFINITION_PREFIX_SIZE > data_end:
        blockers.append(
            GarminTransactionBlocker(
                "truncated_definition_prefix",
                "Definition messages require five bytes after the record header.",
                (record_start, data_end),
                (GARMIN_PROCESS_DEFINITION_SOURCE,),
            )
        )
        return None
    architecture = source_payload[pos + 1]
    byte_order: GarminEndian = "big" if architecture else "little"
    message_number = int.from_bytes(source_payload[pos + 2 : pos + 4], byte_order)
    field_count = source_payload[pos + 4]
    pos += FIT_DEFINITION_PREFIX_SIZE
    field_bytes = field_count * FIT_FIELD_DEFINITION_SIZE
    if pos + field_bytes > data_end:
        blockers.append(
            GarminTransactionBlocker(
                "truncated_definition_fields",
                "Definition field declarations were shorter than the declared field count.",
                (record_start, data_end),
                (GARMIN_PROCESS_DEFINITION_SOURCE,),
            )
        )
        return None
    fields: list[GarminFieldLayoutPlan] = []
    offset = 0
    for field_pos in range(pos, pos + field_bytes, FIT_FIELD_DEFINITION_SIZE):
        field_number = source_payload[field_pos]
        size = source_payload[field_pos + 1]
        base_type = source_payload[field_pos + 2]
        field_source_refs = (GARMIN_PROCESS_DEFINITION_SOURCE, GARMIN_BASE_TYPE_SOURCE)
        fields.append(
            GarminFieldLayoutPlan(field_number, size, base_type, offset, None, field_source_refs)
        )
        offset += size
        if base_type not in BASE_TYPES:
            blockers.append(
                GarminTransactionBlocker(
                    "unknown_fit_base_type",
                    f"FIT field {field_number} declared unsupported base type 0x{base_type:02x}.",
                    (field_pos, field_pos + FIT_FIELD_DEFINITION_SIZE),
                    field_source_refs,
                )
            )
    pos += field_bytes
    developer_fields: list[GarminFieldLayoutPlan] = []
    if flags & 0x20:
        if pos >= data_end:
            blockers.append(
                GarminTransactionBlocker(
                    "truncated_developer_definition",
                    "Developer-data definitions require a developer field count byte.",
                    (record_start, data_end),
                    (GARMIN_PROCESS_DEFINITION_SOURCE, GARMIN_DEVELOPER_SOURCE),
                )
            )
            return None
        developer_count = source_payload[pos]
        pos += 1
        developer_bytes = developer_count * FIT_FIELD_DEFINITION_SIZE
        if pos + developer_bytes > data_end:
            blockers.append(
                GarminTransactionBlocker(
                    "truncated_developer_definition",
                    "Developer field declarations were shorter than the declared field count.",
                    (record_start, data_end),
                    (GARMIN_PROCESS_DEFINITION_SOURCE, GARMIN_DEVELOPER_SOURCE),
                )
            )
            return None
        for field_pos in range(pos, pos + developer_bytes, FIT_FIELD_DEFINITION_SIZE):
            field_number = source_payload[field_pos]
            size = source_payload[field_pos + 1]
            developer_index = source_payload[field_pos + 2]
            developer_fields.append(
                GarminFieldLayoutPlan(
                    field_number,
                    size,
                    developer_index,
                    offset,
                    developer_index,
                    (GARMIN_PROCESS_DEFINITION_SOURCE, GARMIN_DEVELOPER_SOURCE),
                )
            )
            offset += size
        pos += developer_bytes

    message_definition = MESSAGE_DEFINITIONS.get(message_number)
    source_refs: tuple[str, ...]
    if message_definition is None:
        message_name = f"Unknown{message_number}"
        table_name = f"Image::ExifTool::Garmin::{message_name}"
        unknown_by_default = True
        source_refs = (GARMIN_FIT_TABLE_SOURCE, GARMIN_MESSAGE_TABLE_SOURCE)
    else:
        message_name = message_definition.message_name
        table_name = message_definition.table_name
        unknown_by_default = message_definition.unknown_by_default
        source_refs = message_definition.evidence_ids
    extracts_by_default = not unknown_by_default
    extracts = extract_unknown or extracts_by_default
    stored_fields = (
        tuple(fields)
        if extracts
        else tuple(field for field in fields if message_number == 34 and field.field_number == 253)
    )
    runtime = _MessageRuntimeDefinition(
        local_number,
        message_number,
        message_name,
        table_name,
        byte_order,
        stored_fields,
        tuple(developer_fields) if extracts else (),
        offset,
        extracts_by_default,
        extract_unknown,
        (*source_refs, GARMIN_PROCESS_DEFINITION_SOURCE),
    )
    definition_plan = GarminLocalMessageDefinitionPlan(
        local_number,
        message_number,
        message_name,
        table_name,
        byte_order,
        (record_start, pos),
        offset,
        tuple(fields),
        tuple(developer_fields),
        extracts_by_default,
        extract_unknown,
        (*source_refs, GARMIN_PROCESS_DEFINITION_SOURCE),
    )
    definitions.append(definition_plan)
    actions.append(
        GarminActionPlan(
            "record_definition",
            message_name,
            (record_start, pos),
            (*source_refs, GARMIN_PROCESS_DEFINITION_SOURCE),
        )
    )
    return runtime, pos


def _read_data_message(
    source_payload: bytes,
    data_end: int,
    record_start: int,
    pos: int,
    local_number: int,
    compressed_timestamp: int | None,
    runtime: dict[int, _MessageRuntimeDefinition],
    developer_descriptions: dict[tuple[int, int], _DeveloperFieldDescription],
    developer_identifiers: dict[int, _DeveloperDataIdentifier],
    seen_messages: set[int],
    data_messages: list[GarminDataMessagePlan],
    decoded_fields: list[GarminDecodedFieldPlan],
    actions: list[GarminActionPlan],
    blockers: list[GarminTransactionBlocker],
    extract_embedded: bool,
) -> _ReadDataMessageResult:
    definition = runtime.get(local_number)
    if definition is None:
        blockers.append(
            GarminTransactionBlocker(
                "missing_local_message_definition",
                f"Data message local {local_number} had no prior definition.",
                (record_start, min(data_end, pos)),
                (GARMIN_PROCESS_DATA_SOURCE,),
            )
        )
        return _ReadDataMessageResult(data_end, None)
    payload_end = pos + definition.data_size
    if payload_end > data_end:
        blockers.append(
            GarminTransactionBlocker(
                "truncated_data_message",
                "Data message payload was shorter than the active local definition size.",
                (record_start, data_end),
                (GARMIN_PROCESS_DATA_SOURCE,),
            )
        )
        return _ReadDataMessageResult(data_end, None)
    payload = source_payload[pos:payload_end]
    skipped = not extract_embedded and definition.message_number in seen_messages
    if not skipped:
        seen_messages.add(definition.message_number)
    result = (
        _DecodedFieldsResult((), {}, {}, {})
        if skipped
        else _decode_fields(
            payload,
            pos,
            definition,
            developer_descriptions,
            developer_identifiers,
            blockers,
        )
    )
    fields = result.fields
    timestamp_value = compressed_timestamp
    if not skipped and compressed_timestamp is not None and extract_embedded:
        fields = (_compressed_timestamp_field(definition, compressed_timestamp, pos), *fields)
    if not skipped:
        field_timestamp = _int_value(result.raw_standard_field_values.get(253))
        if field_timestamp is not None:
            timestamp_value = field_timestamp
    if not skipped:
        _remember_developer_context(
            definition.message_number,
            result.standard_field_values,
            developer_descriptions,
            developer_identifiers,
        )
    decoded_fields.extend(fields)
    action: GarminActionKind
    if result.developer_field_values:
        action = "route_developer_field"
    elif definition.developer_fields:
        action = "preserve_developer_payload"
    elif not definition.fields and not definition.developer_fields:
        action = "preserve_unknown_record"
    else:
        action = "route_data_message"
    message_plan = GarminDataMessagePlan(
        local_number,
        definition.message_number,
        definition.message_name,
        (record_start, payload_end),
        (pos, payload_end),
        action,
        fields,
        payload,
        skipped,
        (*definition.evidence_ids, GARMIN_PROCESS_DATA_SOURCE),
    )
    data_messages.append(message_plan)
    actions.append(
        GarminActionPlan(
            action,
            definition.message_name,
            (record_start, payload_end),
            (*definition.evidence_ids, GARMIN_PROCESS_DATA_SOURCE),
        )
    )
    return _ReadDataMessageResult(payload_end, timestamp_value)


def _decode_fields(
    payload: bytes,
    payload_offset: int,
    definition: _MessageRuntimeDefinition,
    developer_descriptions: dict[tuple[int, int], _DeveloperFieldDescription],
    developer_identifiers: dict[int, _DeveloperDataIdentifier],
    blockers: list[GarminTransactionBlocker],
) -> _DecodedFieldsResult:
    decoded: list[GarminDecodedFieldPlan] = []
    standard_values: dict[int, GarminDecodedValue] = {}
    raw_standard_values: dict[int, GarminDecodedValue] = {}
    developer_values: dict[int | str, GarminDecodedValue] = {}
    message_definition = MESSAGE_DEFINITIONS.get(definition.message_number)
    for layout in definition.fields:
        base_type = BASE_TYPES.get(layout.base_type)
        raw = payload[layout.byte_offset : layout.byte_offset + layout.size]
        raw_range = (
            payload_offset + layout.byte_offset,
            payload_offset + layout.byte_offset + layout.size,
        )
        if base_type is None:
            continue
        raw_value = _raw_single_value(raw, base_type, definition.byte_order)
        if raw_value is not None:
            raw_standard_values[layout.field_number] = raw_value
        if layout.size % base_type.size:
            blockers.append(
                GarminTransactionBlocker(
                    "bad_fit_field_count",
                    (
                        f"Bad count for {base_type.read_format} "
                        f"{definition.message_name} field {layout.field_number}."
                    ),
                    raw_range,
                    (GARMIN_PROCESS_DATA_SOURCE, GARMIN_BASE_TYPE_SOURCE),
                )
            )
            continue
        field_definition = _field_definition(
            message_definition,
            layout.field_number,
            definition.extracts_unknown_fields,
        )
        if field_definition is None:
            continue
        decoded_field = _decode_standard_field(
            definition,
            layout,
            base_type,
            raw,
            raw_range,
            field_definition,
        )
        if decoded_field is not None:
            decoded.append(decoded_field)
            standard_values[layout.field_number] = decoded_field.value
    for layout in definition.developer_fields:
        base_info = _developer_base_type(layout, developer_descriptions)
        raw_range = (
            payload_offset + layout.byte_offset,
            payload_offset + layout.byte_offset + layout.size,
        )
        if base_info is None or layout.developer_index is None:
            blockers.append(
                GarminTransactionBlocker(
                    "incomplete_developer_field_definition",
                    (
                        "Developer fields require matching FieldDescription "
                        "and DeveloperDataID context."
                    ),
                    raw_range,
                    (GARMIN_DEVELOPER_SOURCE,),
                )
            )
            continue
        base_type, field_definition, field_number = base_info
        if layout.developer_index not in developer_identifiers:
            blockers.append(
                GarminTransactionBlocker(
                    "incomplete_developer_field_definition",
                    "Developer fields require an ApplicationID for the developer data index.",
                    raw_range,
                    (GARMIN_DEVELOPER_SOURCE,),
                )
            )
            continue
        raw = payload[layout.byte_offset : layout.byte_offset + layout.size]
        if layout.size % base_type.size:
            blockers.append(
                GarminTransactionBlocker(
                    "bad_fit_field_count",
                    f"Bad count for {base_type.read_format} developer field {layout.field_number}.",
                    raw_range,
                    (GARMIN_DEVELOPER_SOURCE, GARMIN_BASE_TYPE_SOURCE),
                )
            )
            continue
        decoded_field = _decode_standard_field(
            definition,
            layout,
            base_type,
            raw,
            raw_range,
            field_definition,
            field_number,
        )
        if decoded_field is not None:
            decoded.append(decoded_field)
            developer_values[field_number] = decoded_field.value
    return _DecodedFieldsResult(
        tuple(decoded),
        standard_values,
        raw_standard_values,
        developer_values,
    )


def _raw_single_value(
    raw: bytes, base_type: GarminBaseType, byte_order: GarminEndian
) -> GarminDecodedValue | None:
    if base_type.fit_name == "string":
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    if base_type.read_format == "undef" or len(raw) != base_type.size:
        return None
    if base_type.read_format in {"float", "double"}:
        values = _decode_float_values(raw, base_type, byte_order)
        return None if not values or math.isnan(values[0]) else values[0]
    return int.from_bytes(
        raw,
        byte_order,
        signed=base_type.read_format.endswith("s"),
    )


def _field_definition(
    message_definition: GarminMessageDefinition | None,
    field_number: int,
    extract_unknown: bool,
) -> GarminFieldDefinition | None:
    if message_definition is not None:
        field = message_definition.fields.get(field_number)
        if field is not None:
            return field
    common = COMMON_FIELDS.get(field_number)
    if common is not None:
        if (
            field_number == 253
            and message_definition is not None
            and message_definition.message_name == "Record"
            and not extract_unknown
        ):
            return None
        return common
    if not extract_unknown:
        return None
    if message_definition is None:
        tag_name = f"Unknown_{field_number}"
    else:
        tag_name = f"{message_definition.message_name}_{field_number}"
    return GarminFieldDefinition(tag_name, "unknown", (GARMIN_FIT_TABLE_SOURCE,))


def _compressed_timestamp_field(
    definition: _MessageRuntimeDefinition, timestamp: int, payload_offset: int
) -> GarminDecodedFieldPlan:
    field_definition = COMMON_FIELDS[253]
    converted = _apply_value_conversion(timestamp, field_definition.value_conversion)
    return GarminDecodedFieldPlan(
        definition.message_name,
        253,
        field_definition.tag_name,
        field_definition.group,
        "integer",
        converted,
        _apply_print_conversion(converted, field_definition),
        (payload_offset, payload_offset),
        (*field_definition.evidence_ids, GARMIN_PROCESS_DATA_SOURCE),
    )


def _decode_standard_field(
    definition: _MessageRuntimeDefinition,
    layout: GarminFieldLayoutPlan,
    base_type: GarminBaseType,
    raw: bytes,
    raw_range: tuple[int, int],
    field_definition: GarminFieldDefinition,
    field_number: int | str | None = None,
) -> GarminDecodedFieldPlan | None:
    resolved_field_number = layout.field_number if field_number is None else field_number
    if layout.size == 0:
        return None
    if base_type.fit_name == "string":
        string_value = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        if string_value == base_type.invalid_string:
            return None
        return GarminDecodedFieldPlan(
            definition.message_name,
            resolved_field_number,
            field_definition.tag_name,
            field_definition.group,
            "string",
            string_value,
            _apply_print_conversion(string_value, field_definition),
            raw_range,
            field_definition.evidence_ids,
        )
    if base_type.read_format == "undef" or field_definition.preserve_binary:
        invalid = bytes([base_type.invalid_integer or 0]) * len(raw)
        if base_type.invalid_integer is not None and raw == invalid:
            return None
        return GarminDecodedFieldPlan(
            definition.message_name,
            resolved_field_number,
            field_definition.tag_name,
            field_definition.group,
            "binary",
            raw,
            None,
            raw_range,
            field_definition.evidence_ids,
        )
    if layout.size % base_type.size:
        return None
    count = layout.size // base_type.size
    if count < 1:
        return None
    if base_type.read_format in {"float", "double"}:
        values_float = _decode_float_values(raw, base_type, definition.byte_order)
        values_float = tuple(value for value in values_float if not math.isnan(value))
        if not values_float:
            return None
        value_float: float | str
        if len(values_float) == 1:
            value_float = _apply_value_conversion(
                values_float[0], field_definition.value_conversion
            )
        else:
            converted_float_values = tuple(
                _apply_value_conversion(item, field_definition.value_conversion)
                for item in values_float
            )
            value_float = " ".join(_format_number(item) for item in converted_float_values)
        return GarminDecodedFieldPlan(
            definition.message_name,
            resolved_field_number,
            field_definition.tag_name,
            field_definition.group,
            "real" if isinstance(value_float, float) else "string",
            value_float,
            _apply_print_conversion(value_float, field_definition),
            raw_range,
            field_definition.evidence_ids,
        )
    values = tuple(
        int.from_bytes(
            raw[index : index + base_type.size],
            definition.byte_order,
            signed=base_type.read_format.endswith("s"),
        )
        for index in range(0, layout.size, base_type.size)
    )
    if (
        len(values) == 1
        and base_type.invalid_integer is not None
        and values[0] == base_type.invalid_integer
    ):
        return None
    value: int | float | str
    if len(values) == 1:
        value = _apply_value_conversion(values[0], field_definition.value_conversion)
    else:
        converted_values = tuple(
            _apply_value_conversion(item, field_definition.value_conversion) for item in values
        )
        value = " ".join(_format_number(item) for item in converted_values)
    value_kind: GarminValueKind
    if isinstance(value, float):
        value_kind = "real"
    elif isinstance(value, int):
        value_kind = "integer"
    else:
        value_kind = "string"
    return GarminDecodedFieldPlan(
        definition.message_name,
        resolved_field_number,
        field_definition.tag_name,
        field_definition.group,
        value_kind,
        value,
        _apply_print_conversion(value, field_definition),
        raw_range,
        field_definition.evidence_ids,
    )


def _decode_float_values(
    raw: bytes, base_type: GarminBaseType, byte_order: GarminEndian
) -> tuple[float, ...]:
    endian_prefix = "<" if byte_order == "little" else ">"
    format_code = "f" if base_type.read_format == "float" else "d"
    return tuple(
        struct.unpack(f"{endian_prefix}{format_code}", raw[index : index + base_type.size])[0]
        for index in range(0, len(raw), base_type.size)
    )


def _developer_base_type(
    layout: GarminFieldLayoutPlan,
    developer_descriptions: dict[tuple[int, int], _DeveloperFieldDescription],
) -> tuple[GarminBaseType, GarminFieldDefinition, str] | None:
    if layout.developer_index is None:
        return None
    description = developer_descriptions.get((layout.developer_index, layout.field_number))
    if description is None:
        return None
    base_type = BASE_TYPES.get(description.base_type)
    if base_type is None:
        return None
    field_number = f"dev{layout.developer_index}_{description.field_number}"
    field_definition = GarminFieldDefinition(
        _make_developer_tag_name(description.field_name),
        "developer",
        (GARMIN_DEVELOPER_SOURCE,),
        value_conversion=None,
        print_conversion="developer_units" if description.units else None,
        print_suffix=_sanitize_developer_units(description.units) if description.units else None,
    )
    return base_type, field_definition, field_number


def _remember_developer_context(
    message_number: int,
    values: dict[int, GarminDecodedValue],
    developer_descriptions: dict[tuple[int, int], _DeveloperFieldDescription],
    developer_identifiers: dict[int, _DeveloperDataIdentifier],
) -> None:
    if message_number == 207:
        developer_index = _int_value(values.get(3))
        application_id = values.get(1)
        if developer_index is not None and isinstance(application_id, bytes):
            developer_identifiers[developer_index] = _DeveloperDataIdentifier(
                developer_index, application_id
            )
    elif message_number == 206:
        developer_index = _int_value(values.get(0))
        field_number = _int_value(values.get(1))
        base_type = _int_value(values.get(2))
        field_name = values.get(3)
        units = values.get(8)
        if (
            developer_index is not None
            and field_number is not None
            and base_type is not None
            and isinstance(field_name, str)
        ):
            developer_descriptions[(developer_index, field_number)] = _DeveloperFieldDescription(
                developer_index,
                field_number,
                base_type,
                field_name,
                units if isinstance(units, str) else "",
            )


def _int_value(value: GarminDecodedValue | None) -> int | None:
    return value if isinstance(value, int) else None


def _make_developer_tag_name(value: str) -> str:
    pieces = value.replace("-", "_").replace(" ", "_").split("_")
    name = "".join(piece[:1].upper() + piece[1:] for piece in pieces if piece)
    return name or "DeveloperField"


def _apply_value_conversion(
    value: int | float, conversion: GarminValueConversion | None
) -> int | float:
    if conversion is None:
        return value
    if conversion == "activity_milliseconds":
        return _clean_float(value / 1000)
    if conversion == "altitude_meters":
        return _clean_float(value / 5 - 500)
    if conversion == "centimeters_to_meters":
        return _clean_float(value / 100)
    if conversion == "centi_degrees":
        return _clean_float(value / 100)
    if conversion == "divide_by_10":
        return _clean_float(value / 10)
    if conversion == "divide_by_100":
        return _clean_float(value / 100)
    if conversion == "divide_by_128":
        return _clean_float(value / 128)
    if conversion == "divide_by_256":
        return _clean_float(value / 256)
    if conversion == "divide_by_1000":
        return _clean_float(value / 1000)
    if conversion == "divide_by_2":
        return _clean_float(value / 2)
    if conversion == "divide_by_5":
        return _clean_float(value / 5)
    if conversion == "divide_by_65536":
        return round(value / 65536, 14)
    if conversion == "fit_epoch_seconds":
        return value + 631065600
    if conversion == "fractional_seconds_32768":
        return _clean_float(value / 32768)
    if conversion == "garmin_semicircles_degrees":
        return _clean_float(value * 180 / 0x80000000)
    if conversion == "local_epoch_seconds":
        return value + 631065600
    if conversion == "meters_per_second_from_millimeters":
        return _clean_float(value / 1000)
    if conversion == "speed_kmh_from_millimeters":
        return _clean_float(value * 3.6 / 1000)
    if conversion == "software_version":
        return _clean_float(value / 100)
    raise AssertionError(f"Unhandled Garmin value conversion: {conversion}")


def _apply_print_conversion(
    value: GarminDecodedValue, field_definition: GarminFieldDefinition
) -> str | None:
    if field_definition.enum_values is not None and isinstance(value, int):
        converted = field_definition.enum_values.get(value)
        if converted is not None:
            return converted
    conversion = field_definition.print_conversion
    if conversion is None:
        return None
    if conversion == "date_time_local":
        if isinstance(value, int):
            return datetime.fromtimestamp(value, UTC).strftime("%Y:%m:%d %H:%M:%S")
        return None
    if conversion == "date_time_with_zone":
        if isinstance(value, int):
            rendered = datetime.fromtimestamp(value).astimezone().strftime("%Y:%m:%d %H:%M:%S%z")
            return f"{rendered[:-2]}:{rendered[-2:]}"
        return None
    if conversion == "garmin_latitude_dms":
        if isinstance(value, int | float):
            return _dms(value, "N", "S")
        return None
    if conversion == "garmin_longitude_dms":
        if isinstance(value, int | float):
            return _dms(value, "E", "W")
        return None
    if conversion == "developer_units":
        if field_definition.print_suffix:
            return f"{_format_scalar_print_value(value)} {field_definition.print_suffix}"
        return None
    suffix = _unit_suffix(conversion)
    if suffix is not None:
        return f"{_format_scalar_print_value(value)} {suffix}"
    raise AssertionError(f"Unhandled Garmin print conversion: {conversion}")


def _unit_suffix(conversion: GarminPrintConversion) -> str | None:
    if conversion == "unit_bpm":
        return "bpm"
    if conversion == "unit_breaths_per_min":
        return "Breaths/min"
    if conversion == "unit_bar_per_min":
        return "bar/min"
    if conversion == "unit_cm_per_s":
        return "cm/s"
    if conversion == "unit_celsius":
        return "C"
    if conversion == "unit_cycles":
        return "cycles"
    if conversion == "unit_flow":
        return "Flow"
    if conversion == "unit_gdl":
        return "g/dL"
    if conversion == "unit_if":
        return "if"
    if conversion == "unit_joules":
        return "J"
    if conversion == "unit_kg":
        return "kg"
    if conversion == "unit_kgrit":
        return "kGrit"
    if conversion == "unit_kcal":
        return "kcal"
    if conversion == "unit_kmh":
        return "km/h"
    if conversion == "unit_l_per_min":
        return "L/min"
    if conversion == "unit_lengths":
        return "lengths"
    if conversion == "unit_m":
        return "m"
    if conversion == "unit_ml":
        return "ml"
    if conversion == "unit_mm":
        return "mm"
    if conversion == "unit_ms":
        return "ms"
    if conversion == "unit_mps":
        return "m/s"
    if conversion == "unit_newton":
        return "N"
    if conversion == "unit_otus":
        return "OTUs"
    if conversion == "unit_pa":
        return "Pa"
    if conversion == "unit_percent":
        return "%"
    if conversion == "unit_rpm":
        return "rpm"
    if conversion == "unit_s":
        return "s"
    if conversion == "unit_strokes_per_lap":
        return "strokes/lap"
    if conversion == "unit_tss":
        return "tss"
    if conversion == "unit_v":
        return "V"
    if conversion == "unit_watts":
        return "watts"
    return None


def _format_scalar_print_value(value: GarminDecodedValue) -> str:
    if isinstance(value, int | float):
        return _format_number(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def _format_number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _dms(value: int | float, positive_ref: str, negative_ref: str) -> str:
    ref = positive_ref if value >= 0 else negative_ref
    absolute = abs(float(value))
    degrees = int(absolute)
    minutes_float = (absolute - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    seconds_text = f"{seconds:.2f}".rstrip("0").rstrip(".")
    return f"{degrees} deg {minutes}' {seconds_text}\" {ref}"


def _sanitize_developer_units(value: str) -> str:
    return "".join(char for char in value if char.isalnum() or char in "-_/+*")


def _clean_float(value: float) -> int | float:
    normalized = round(value, 10)
    return int(normalized) if normalized.is_integer() else normalized


def _output_gates(
    blockers: list[GarminTransactionBlocker],
    rewrite_requests: tuple[GarminRewriteRequest, ...],
) -> list[GarminOutputEmissionGate]:
    gates = [
        GarminOutputEmissionGate(
            "planner_is_non_mutating",
            "This Garmin transaction planner records routes and blockers but "
            "does not mutate bytes.",
            (GARMIN_READ_ONLY_SOURCE,),
        ),
        GarminOutputEmissionGate(
            "fit_writer_not_implemented",
            "Garmin.pm provides no FIT writer for this modernization slice to port.",
            (GARMIN_READ_ONLY_SOURCE,),
        ),
    ]
    if rewrite_requests:
        gates.append(
            GarminOutputEmissionGate(
                "rewrite_requested_requires_fit_writer",
                "Requested Garmin metadata writes are blocked until a FIT writer exists.",
                (GARMIN_READ_ONLY_SOURCE,),
            )
        )
    if any(blocker.code.startswith("truncated_") for blocker in blockers):
        gates.append(
            GarminOutputEmissionGate(
                "truncated_fit_stream_blocks_rewrite",
                "Truncated FIT records must not be rewritten.",
                (GARMIN_PROCESS_DATA_SOURCE,),
            )
        )
    if any(blocker.code == "unknown_fit_base_type" for blocker in blockers):
        gates.append(
            GarminOutputEmissionGate(
                "unknown_fit_base_type_blocks_rewrite",
                "Unknown FIT base types cannot be safely decoded or rewritten.",
                (GARMIN_BASE_TYPE_SOURCE,),
            )
        )
    if any(
        blocker.code
        in {
            "unsupported_fit_signature",
            "invalid_fit_header_size",
            "missing_local_message_definition",
            "bad_fit_field_count",
        }
        for blocker in blockers
    ):
        gates.append(
            GarminOutputEmissionGate(
                "malformed_fit_stream_blocks_rewrite",
                "Malformed FIT structure blocks rewrite planning.",
                (GARMIN_PROCESS_DEFINITION_SOURCE, GARMIN_PROCESS_DATA_SOURCE),
            )
        )
    return gates


def _responsibilities() -> tuple[GarminResponsibilityPlan, ...]:
    return (
        GarminResponsibilityPlan(
            "product_file_identity",
            "FileID and DeviceInfo preserve source-backed Garmin product, file, and device fields.",
            (GARMIN_FILE_ID_SOURCE, GARMIN_DEVICE_INFO_SOURCE),
        ),
        GarminResponsibilityPlan(
            "fit_table_routing",
            "Global message numbers route through the FIT table and local message definitions.",
            (
                GARMIN_MESSAGE_TABLE_SOURCE,
                GARMIN_FIT_TABLE_SOURCE,
                GARMIN_PROCESS_DEFINITION_SOURCE,
            ),
        ),
        GarminResponsibilityPlan(
            "gps_location",
            "Session, Lap, Record, and GPS tables define location field boundaries.",
            (GARMIN_SESSION_SOURCE, GARMIN_LAP_SOURCE, GARMIN_RECORD_SOURCE, GARMIN_GPS_SOURCE),
        ),
        GarminResponsibilityPlan(
            "time_correlation",
            "Common timestamp and TimeStampCorrelation tables define FIT time boundaries.",
            (GARMIN_COMMON_SOURCE, GARMIN_TIME_CORRELATION_SOURCE),
        ),
        GarminResponsibilityPlan(
            "track_motion",
            "Record, Lap, Session, and GPS tables define speed, track, distance, "
            "and motion fields.",
            (GARMIN_RECORD_SOURCE, GARMIN_LAP_SOURCE, GARMIN_SESSION_SOURCE, GARMIN_GPS_SOURCE),
        ),
        GarminResponsibilityPlan(
            "activity_summary",
            "Activity, Session, and Lap tables define activity and summary metric fields.",
            (GARMIN_ACTIVITY_SOURCE, GARMIN_SESSION_SOURCE, GARMIN_LAP_SOURCE),
        ),
        GarminResponsibilityPlan(
            "device_identity",
            "DeviceInfo defines device index, type, manufacturer, product, "
            "versions, and battery fields.",
            (GARMIN_DEVICE_INFO_SOURCE,),
        ),
        GarminResponsibilityPlan(
            "binary_payload_preservation",
            "Raw data payloads, unknown messages, and developer fields are "
            "preserved byte-for-byte.",
            (GARMIN_PROCESS_DATA_SOURCE, GARMIN_DEVELOPER_SOURCE),
        ),
        GarminResponsibilityPlan(
            "malformed_and_truncation_blockers",
            "FIT header, definition, and data-message truncations become explicit blockers.",
            (GARMIN_HEADER_SOURCE, GARMIN_PROCESS_DEFINITION_SOURCE, GARMIN_PROCESS_DATA_SOURCE),
        ),
        GarminResponsibilityPlan(
            "unsupported_rewrite_gate",
            "Garmin FIT rewrite remains gated because this source module has no writer path.",
            (GARMIN_READ_ONLY_SOURCE,),
        ),
        GarminResponsibilityPlan(
            "non_mutating_defaults",
            "Default routing follows Garmin.pm Unknown and ExtractEmbedded read-side gates.",
            (GARMIN_FIT_TABLE_SOURCE, GARMIN_PROCESS_DATA_SOURCE),
        ),
    )


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)
