"""Source-grounded, non-mutating DJI metadata transaction planning."""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.protobuf.metadata_transaction_plan import (
    ProtobufFieldDatabase,
    ProtobufFieldDefinition,
    ProtobufMetadataTransactionPlan,
    build_protobuf_metadata_transaction_plan,
)
from exifmodern.json_types import JsonArray, JsonObject, JsonValue

DJI_PM_SOURCE_PATH = "lib/Image/ExifTool/DJI.pm"

type DjiEvidenceId = Literal[
    "dji.known-protocols",
    "dji.main-makernote-table",
    "dji.info-debug-table",
    "dji.thermal-params-tables",
    "dji.xmp-drone-namespace",
    "dji.glamour-settings-table",
    "dji.protobuf-table",
    "dji.protobuf-subdirectories",
    "dji.settings-process",
    "dji.info-process",
    "dji.reader-boundary",
]
type DjiPlanStatus = Literal["planned", "unsupported"]
type DjiMetadataRouteKind = Literal[
    "main_makernote",
    "info_debug",
    "settings",
    "thermal_app4",
    "xmp",
    "protobuf",
    "unknown_payload",
]
type DjiResponsibilityKind = Literal[
    "camera_metadata",
    "gps_metadata",
    "flight_metadata",
    "gimbal_metadata",
    "thermal_metadata",
    "settings_metadata",
    "debug_metadata",
    "video_metadata",
    "time_metadata",
    "image_metadata",
    "unknown_payload",
]
type DjiScalarValue = str | int | float | bytes | bool
type DjiMainValueFormat = Literal["string", "float", "bytes"]
type DjiThermalTable = Literal["ThermalParams", "ThermalParams2", "ThermalParams3"]
type DjiRewriteTarget = Literal[
    "main_makernote",
    "info_debug",
    "settings",
    "thermal_app4",
    "xmp",
    "protobuf",
    "unknown_payload",
]
type DjiRewriteOperation = Literal["replace", "delete", "insert"]
type DjiActionKind = Literal[
    "route_main_makernote_tag",
    "parse_info_debug_tag",
    "parse_settings_tag",
    "route_thermal_app4_field",
    "route_xmp_property",
    "route_protobuf_protocol",
    "route_protobuf_field",
    "preserve_payload",
    "block_requested_rewrite",
    "route_source_backed_rewrite",
    "no_metadata_mutation",
]
type DjiBlockerCode = Literal[
    "truncated_main_makernote_record",
    "invalid_info_debug_slice",
    "truncated_thermal_app4_field",
    "malformed_protobuf_payload",
]
type DjiEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_main_makernote_record",
    "invalid_info_debug_slice",
    "truncated_thermal_app4_field",
    "malformed_protobuf_payload",
    "unsupported_rewrite_requested",
    "source_backed_rewrite_requires_downstream_writer",
]

DJI_KNOWN_PROTOCOLS = frozenset(
    {
        "dvtm_ac203.proto",
        "dvtm_ac204.proto",
        "dvtm_ac206.proto",
        "dvtm_AVATA2.proto",
        "dvtm_wm265e.proto",
        "dvtm_pm320.proto",
        "dvtm_Mini4_Pro.proto",
        "dvtm_dji_neo.proto",
        "dvtm_Air3.proto",
        "dvtm_Air3s.proto",
        "dvtm_PP-101.proto",
        "dvtm_oq101.proto",
        "dvtm_wa345e.proto",
        "dvtm_wm261.proto",
        "dvtm_Mavic4.proto",
        "dvtm_Mini5Pro.proto",
    }
)

DJI_MAIN_TAGS: dict[int, tuple[str, DjiMainValueFormat, DjiResponsibilityKind]] = {
    0x01: ("Make", "string", "camera_metadata"),
    0x03: ("SpeedX", "float", "flight_metadata"),
    0x04: ("SpeedY", "float", "flight_metadata"),
    0x05: ("SpeedZ", "float", "flight_metadata"),
    0x06: ("Pitch", "float", "flight_metadata"),
    0x07: ("Yaw", "float", "flight_metadata"),
    0x08: ("Roll", "float", "flight_metadata"),
    0x09: ("CameraPitch", "float", "gimbal_metadata"),
    0x0A: ("CameraYaw", "float", "gimbal_metadata"),
    0x0B: ("CameraRoll", "float", "gimbal_metadata"),
}

DJI_INFO_TAGS: dict[str, str] = {
    "ae_dbg_info": "AEDebugInfo",
    "ae_histogram_info": "AEHistogramInfo",
    "ae_local_histogram": "AELocalHistogram",
    "ae_liveview_histogram_info": "AELiveViewHistogramInfo",
    "ae_liveview_local_histogram": "AELiveViewLocalHistogram",
    "awb_dbg_info": "AWBDebugInfo",
    "af_dbg_info": "AFDebugInfo",
    "hiso": "Histogram",
    "xidiri": "Xidiri",
    "GimbalDegree(Y,P,R)": "GimbalDegree",
    "FlightDegree(Y,P,R)": "FlightDegree",
    "adj_dbg_info": "ADJDebugInfo",
    "sensor_id": "SensorID",
    "FlightSpeed(X,Y,Z)": "FlightSpeed",
    "hyperlapse_dbg_info": "HyperlapsDebugInfo",
}

DJI_SETTINGS_TAGS: dict[str, str] = {
    "beauty_enable": "BeautyEnable",
    "smoother": "Smoother",
    "whitening": "Whitening",
    "face_slimming": "FaceSlimming",
    "eye_enlarge": "EyeEnlarge",
    "nose_slimming": "NoseSlimming",
    "mouth_beautify": "MouthModify",
    "teeth_whitening": "TeethWhitening",
    "leg_longer": "LegLonger",
    "head_shrinking": "HeadShrinking",
    "lipstick": "Lipstick",
    "blush": "Blush",
    "dark_circle": "DarkCircle",
    "acne_spot_removal": "AcneSpotRemoval",
    "eyebrows": "Eyebrows",
}

DJI_THERMAL_FIELDS: dict[DjiThermalTable, dict[int, tuple[str, str]]] = {
    "ThermalParams": {
        0x24: ("K1", "float"),
        0x28: ("K2", "float"),
        0x2C: ("K3", "float"),
        0x30: ("K4", "float"),
        0x34: ("KF", "float"),
        0x38: ("B1", "float"),
        0x3C: ("B2", "float"),
        0x44: ("ObjectDistance", "int16u"),
        0x46: ("RelativeHumidity", "int16u"),
        0x48: ("Emissivity", "int16u"),
        0x4A: ("Reflection", "int16u"),
        0x4C: ("AmbientTemperature", "int16u"),
        0x50: ("D2", "int32s"),
        0x54: ("KJ", "int16u"),
        0x56: ("DB", "int16u"),
        0x58: ("KK", "int16u"),
    },
    "ThermalParams2": {
        0x00: ("AmbientTemperature", "float"),
        0x04: ("ObjectDistance", "float"),
        0x08: ("Emissivity", "float"),
        0x0C: ("RelativeHumidity", "float"),
        0x10: ("ReflectedTemperature", "float"),
        0x65: ("IDString", "string[16]"),
    },
    "ThermalParams3": {
        0x04: ("RelativeHumidity", "int16u"),
        0x06: ("ObjectDistance", "int16u/10"),
        0x08: ("Emissivity", "int16u/100"),
        0x0A: ("ReflectedTemperature", "int16u/10"),
    },
}

DJI_XMP_ROUTES: dict[str, tuple[str, DjiResponsibilityKind, bool]] = {
    "AbsoluteAltitude": ("AbsoluteAltitude", "gps_metadata", True),
    "RelativeAltitude": ("RelativeAltitude", "gps_metadata", True),
    "GimbalRollDegree": ("GimbalRollDegree", "gimbal_metadata", True),
    "GimbalYawDegree": ("GimbalYawDegree", "gimbal_metadata", True),
    "GimbalPitchDegree": ("GimbalPitchDegree", "gimbal_metadata", True),
    "FlightRollDegree": ("FlightRollDegree", "flight_metadata", True),
    "FlightYawDegree": ("FlightYawDegree", "flight_metadata", True),
    "FlightPitchDegree": ("FlightPitchDegree", "flight_metadata", True),
    "GpsLatitude": ("GPSLatitude", "gps_metadata", True),
    "GpsLongtitude": ("GPSLongtitude", "gps_metadata", True),
    "GpsLongitude": ("GPSLongitude", "gps_metadata", True),
    "Latitude": ("Latitude", "gps_metadata", True),
    "Longitude": ("Longitude", "gps_metadata", True),
    "FlightXSpeed": ("FlightXSpeed", "flight_metadata", True),
    "FlightYSpeed": ("FlightYSpeed", "flight_metadata", True),
    "FlightZSpeed": ("FlightZSpeed", "flight_metadata", True),
    "CalibratedFocalLength": ("CalibratedFocalLength", "image_metadata", True),
    "CalibratedOpticalCenterX": ("CalibratedOpticalCenterX", "image_metadata", True),
    "CalibratedOpticalCenterY": ("CalibratedOpticalCenterY", "image_metadata", True),
    "SelfData": ("SelfData", "image_metadata", False),
    "DewarpData": ("DewarpData", "image_metadata", False),
    "DewarpFlag": ("DewarpFlag", "image_metadata", False),
    "RtkFlag": ("RtkFlag", "gps_metadata", False),
    "RtkStdLon": ("RtkStdLon", "gps_metadata", True),
    "RtkStdLat": ("RtkStdLat", "gps_metadata", True),
    "RtkStdHgt": ("RtkStdHgt", "gps_metadata", True),
}

DJI_PROTOBUF_FIELD_ROUTES: dict[str, tuple[str, DjiResponsibilityKind, str | None]] = {
    "1-1-5": ("SerialNumber", "camera_metadata", None),
    "1-1-10": ("Model", "camera_metadata", None),
    "2-2": ("FrameInfo", "video_metadata", "FrameInfo"),
    "2-3": ("FrameInfo", "video_metadata", "FrameInfo"),
    "3-1-2": ("TimeStamp", "time_metadata", None),
    "3-2-2-1": ("ISO", "camera_metadata", None),
    "3-2-3-1": ("ShutterSpeed", "camera_metadata", None),
    "3-2-4-1": ("ShutterSpeed", "camera_metadata", None),
    "3-2-6-1": ("ColorTemperature", "camera_metadata", None),
    "3-2-7-1": ("ISO", "camera_metadata", None),
    "3-2-9-1": ("ISO", "camera_metadata", None),
    "3-2-10-1": ("ShutterSpeed", "camera_metadata", None),
    "3-2-10-2": ("AccelerometerX", "camera_metadata", None),
    "3-2-10-3": ("AccelerometerY", "camera_metadata", None),
    "3-2-10-4": ("AccelerometerZ", "camera_metadata", None),
    "3-2-11-1": ("FNumber", "camera_metadata", None),
    "3-2-24-1": ("ColorTemperature", "camera_metadata", None),
    "3-2-32-1": ("ColorTemperature", "camera_metadata", None),
    "3-2-37-1": ("Temperature", "camera_metadata", None),
    "3-3-3": ("DroneInfo", "flight_metadata", "DroneInfo"),
    "3-3-4-1": ("GPSInfo", "gps_metadata", "GPSInfo"),
    "3-3-4-2": ("AbsoluteAltitude", "gps_metadata", None),
    "3-3-4-6-1": ("GPSDateTime", "time_metadata", None),
    "3-3-5-1": ("RelativeAltitude", "gps_metadata", None),
    "3-4-2-1": ("GPSInfo", "gps_metadata", "GPSInfo"),
    "3-4-2-2": ("GPSAltitude", "gps_metadata", None),
    "3-4-2-6-1": ("GPSDateTime", "time_metadata", None),
    "3-4-3": ("GimbalInfo", "gimbal_metadata", "GimbalInfo"),
    "3-4-4-1": ("GPSInfo", "gps_metadata", "GPSInfo"),
    "3-4-4-2": ("AbsoluteAltitude", "gps_metadata", None),
    "3-4-5-1": ("RelativeAltitude", "gps_metadata", None),
}

DJI_SUBDIRECTORY_ROUTES: dict[str, dict[str, tuple[str, DjiResponsibilityKind]]] = {
    "DroneInfo": {
        "1": ("DroneRoll", "flight_metadata"),
        "2": ("DronePitch", "flight_metadata"),
        "3": ("DroneYaw", "flight_metadata"),
    },
    "GimbalInfo": {
        "1": ("GimbalPitch", "gimbal_metadata"),
        "2": ("GimbalRoll", "gimbal_metadata"),
        "3": ("GimbalYaw", "gimbal_metadata"),
    },
    "FrameInfo": {
        "1": ("FrameWidth", "video_metadata"),
        "2": ("FrameHeight", "video_metadata"),
        "3": ("FrameRate", "video_metadata"),
    },
    "GPSInfo": {
        "1": ("CoordinateUnits", "gps_metadata"),
        "2": ("GPSLatitude", "gps_metadata"),
        "3": ("GPSLongitude", "gps_metadata"),
    },
}

DJI_KNOWN_PROTOCOL_SOURCE: DjiEvidenceId = "dji.known-protocols"
DJI_MAIN_SOURCE: DjiEvidenceId = "dji.main-makernote-table"
DJI_INFO_SOURCE: DjiEvidenceId = "dji.info-debug-table"
DJI_THERMAL_SOURCE: DjiEvidenceId = "dji.thermal-params-tables"
DJI_XMP_SOURCE: DjiEvidenceId = "dji.xmp-drone-namespace"
DJI_SETTINGS_TABLE_SOURCE: DjiEvidenceId = "dji.glamour-settings-table"
DJI_PROTOBUF_SOURCE: DjiEvidenceId = "dji.protobuf-table"
DJI_SUBDIRECTORY_SOURCE: DjiEvidenceId = "dji.protobuf-subdirectories"
DJI_SETTINGS_PROCESS_SOURCE: DjiEvidenceId = "dji.settings-process"
DJI_INFO_PROCESS_SOURCE: DjiEvidenceId = "dji.info-process"
DJI_READ_BOUNDARY_SOURCE: DjiEvidenceId = "dji.reader-boundary"
DJI_TRANSACTION_SOURCES: tuple[DjiEvidenceId, ...] = (
    DJI_KNOWN_PROTOCOL_SOURCE,
    DJI_MAIN_SOURCE,
    DJI_INFO_SOURCE,
    DJI_THERMAL_SOURCE,
    DJI_XMP_SOURCE,
    DJI_SETTINGS_TABLE_SOURCE,
    DJI_PROTOBUF_SOURCE,
    DJI_SUBDIRECTORY_SOURCE,
    DJI_SETTINGS_PROCESS_SOURCE,
    DJI_INFO_PROCESS_SOURCE,
    DJI_READ_BOUNDARY_SOURCE,
)


@dataclass(frozen=True)
class DjiEvidenceAnchor:
    evidence_id: DjiEvidenceId
    path: str
    line_start: int
    line_end: int
    symbol: str
    summary: str


DJI_EVIDENCE_ANCHORS: dict[DjiEvidenceId, DjiEvidenceAnchor] = {
    DJI_KNOWN_PROTOCOL_SOURCE: DjiEvidenceAnchor(
        DJI_KNOWN_PROTOCOL_SOURCE,
        DJI_PM_SOURCE_PATH,
        26,
        44,
        "%knownProtocol",
        "DJI.pm lists accepted dvtm protocol names and leaves dvtm_wm169 as unknown.",
    ),
    DJI_MAIN_SOURCE: DjiEvidenceAnchor(
        DJI_MAIN_SOURCE,
        DJI_PM_SOURCE_PATH,
        52,
        72,
        "%Image::ExifTool::DJI::Main",
        "Main maker notes route Make, speed, flight pose, and camera pose tags.",
    ),
    DJI_INFO_SOURCE: DjiEvidenceAnchor(
        DJI_INFO_SOURCE,
        DJI_PM_SOURCE_PATH,
        74,
        95,
        "%Image::ExifTool::DJI::Info",
        "The debug maker-note table maps bracketed tag names to DJI debug labels.",
    ),
    DJI_THERMAL_SOURCE: DjiEvidenceAnchor(
        DJI_THERMAL_SOURCE,
        DJI_PM_SOURCE_PATH,
        97,
        146,
        "DJI ThermalParams tables",
        "ThermalParams, ThermalParams2, and ThermalParams3 route APP4 binary offsets.",
    ),
    DJI_XMP_SOURCE: DjiEvidenceAnchor(
        DJI_XMP_SOURCE,
        DJI_PM_SOURCE_PATH,
        148,
        211,
        "%Image::ExifTool::DJI::XMP",
        "The XMP table defines drone-dji GPS, flight, gimbal, RTK, and calibration tags.",
    ),
    DJI_SETTINGS_TABLE_SOURCE: DjiEvidenceAnchor(
        DJI_SETTINGS_TABLE_SOURCE,
        DJI_PM_SOURCE_PATH,
        213,
        232,
        "%Image::ExifTool::DJI::Glamour",
        "Glamour settings route key names through ProcessSettings.",
    ),
    DJI_PROTOBUF_SOURCE: DjiEvidenceAnchor(
        DJI_PROTOBUF_SOURCE,
        DJI_PM_SOURCE_PATH,
        234,
        859,
        "%Image::ExifTool::DJI::Protobuf",
        (
            "The DJI protobuf table routes protocol field paths to camera, GPS, "
            "frame, drone, and gimbal tables."
        ),
    ),
    DJI_SUBDIRECTORY_SOURCE: DjiEvidenceAnchor(
        DJI_SUBDIRECTORY_SOURCE,
        DJI_PM_SOURCE_PATH,
        868,
        921,
        "DJI protobuf subdirectories",
        "DroneInfo, GimbalInfo, FrameInfo, and GPSInfo define nested protobuf responsibilities.",
    ),
    DJI_SETTINGS_PROCESS_SOURCE: DjiEvidenceAnchor(
        DJI_SETTINGS_PROCESS_SOURCE,
        DJI_PM_SOURCE_PATH,
        923,
        937,
        "ProcessSettings",
        (
            "ProcessSettings splits the payload on semicolons, then splits each "
            "part on the first equals sign."
        ),
    ),
    DJI_INFO_PROCESS_SOURCE: DjiEvidenceAnchor(
        DJI_INFO_PROCESS_SOURCE,
        DJI_PM_SOURCE_PATH,
        939,
        966,
        "ProcessDJIInfo",
        (
            "ProcessDJIInfo respects DirStart/DirLen, reads bracketed entries, "
            "and keeps binary values by reference."
        ),
    ),
    DJI_READ_BOUNDARY_SOURCE: DjiEvidenceAnchor(
        DJI_READ_BOUNDARY_SOURCE,
        DJI_PM_SOURCE_PATH,
        4,
        8,
        "DJI.pm module scope",
        (
            "DJI.pm is a reader plus source-backed Main/XMP write tables, "
            "not a general DJI file writer."
        ),
    ),
}

INFO_ENTRY_RE = re.compile(rb"\[(.*?)\](?=(\[|$))", re.DOTALL)


@dataclass(frozen=True)
class DjiMainTagInput:
    tag_id: int
    raw_value: bytes
    byte_range: tuple[int, int] | None = None


@dataclass(frozen=True)
class DjiPayloadInput:
    route_kind: DjiMetadataRouteKind
    payload: bytes
    byte_range: tuple[int, int] | None = None
    label: str | None = None


@dataclass(frozen=True)
class DjiRewriteRequest:
    target: DjiRewriteTarget
    operation: DjiRewriteOperation
    tag_name: str | None = None
    payload: bytes | None = None


@dataclass(frozen=True)
class DjiActionPlan:
    kind: DjiActionKind
    route_kind: DjiMetadataRouteKind
    tag_name: str | None
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[DjiEvidenceId, ...]


@dataclass(frozen=True)
class DjiTransactionBlocker:
    code: DjiBlockerCode
    route_kind: DjiMetadataRouteKind
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[DjiEvidenceId, ...]


@dataclass(frozen=True)
class DjiOutputEmissionGate:
    code: DjiEmissionGateCode
    route_kind: DjiMetadataRouteKind | None
    reason: str
    evidence_ids: tuple[DjiEvidenceId, ...]


@dataclass(frozen=True)
class DjiTagRoutePlan:
    route_kind: DjiMetadataRouteKind
    tag_id: int | None
    source_name: str
    tag_name: str
    responsibility: DjiResponsibilityKind
    writable: bool
    value: DjiScalarValue | None
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[DjiEvidenceId, ...]


@dataclass(frozen=True)
class DjiThermalFieldPlan:
    table: DjiThermalTable
    offset: int
    tag_name: str
    format_name: str
    value: DjiScalarValue
    byte_range: tuple[int, int]
    evidence_ids: tuple[DjiEvidenceId, ...]


@dataclass(frozen=True)
class DjiProtobufProtocolPlan:
    protocol_name: str
    known: bool
    accepted_by_dbginfo_prefix: bool
    warning: str | None
    evidence_ids: tuple[DjiEvidenceId, ...]


@dataclass(frozen=True)
class DjiProtobufFieldRoutePlan:
    protocol_name: str | None
    field_path: str
    tag_name: str
    responsibility: DjiResponsibilityKind
    subdirectory: str | None
    known: bool
    evidence_ids: tuple[DjiEvidenceId, ...]


@dataclass(frozen=True)
class DjiPreservedPayloadPlan:
    route_kind: DjiMetadataRouteKind
    payload: bytes
    byte_range: tuple[int, int] | None
    label: str | None
    evidence_ids: tuple[DjiEvidenceId, ...]


@dataclass(frozen=True)
class DjiMetadataTransactionPlan:
    status: DjiPlanStatus
    main_routes: tuple[DjiTagRoutePlan, ...]
    info_routes: tuple[DjiTagRoutePlan, ...]
    settings_routes: tuple[DjiTagRoutePlan, ...]
    thermal_fields: tuple[DjiThermalFieldPlan, ...]
    xmp_routes: tuple[DjiTagRoutePlan, ...]
    protobuf_protocol: DjiProtobufProtocolPlan | None
    protobuf_field_routes: tuple[DjiProtobufFieldRoutePlan, ...]
    protobuf_plan: ProtobufMetadataTransactionPlan | None
    preserved_payloads: tuple[DjiPreservedPayloadPlan, ...]
    actions: tuple[DjiActionPlan, ...]
    blockers: tuple[DjiTransactionBlocker, ...]
    output_emission_gates: tuple[DjiOutputEmissionGate, ...]
    evidence_ids: tuple[DjiEvidenceId, ...]
    original_bytes: bytes

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"DJI metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def responsibilities(self, kind: DjiResponsibilityKind) -> tuple[str, ...]:
        names: list[str] = []
        names.extend(route.tag_name for route in self.main_routes if route.responsibility == kind)
        names.extend(route.tag_name for route in self.info_routes if route.responsibility == kind)
        names.extend(
            route.tag_name for route in self.settings_routes if route.responsibility == kind
        )
        names.extend(field.tag_name for field in self.thermal_fields if kind == "thermal_metadata")
        names.extend(route.tag_name for route in self.xmp_routes if route.responsibility == kind)
        names.extend(
            route.tag_name for route in self.protobuf_field_routes if route.responsibility == kind
        )
        return tuple(names)

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action_to_json(action) for action in self.actions),
            "blockers": json_object_array(blocker_to_json(blocker) for blocker in self.blockers),
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "info_routes": json_object_array(
                tag_route_to_json(route) for route in self.info_routes
            ),
            "main_routes": json_object_array(
                tag_route_to_json(route) for route in self.main_routes
            ),
            "output_emission_gates": json_object_array(
                emission_gate_to_json(gate) for gate in self.output_emission_gates
            ),
            "preserved_payloads": json_object_array(
                preserved_payload_to_json(payload) for payload in self.preserved_payloads
            ),
            "protobuf_field_routes": json_object_array(
                protobuf_field_route_to_json(route) for route in self.protobuf_field_routes
            ),
            "protobuf_protocol": protobuf_protocol_to_json(self.protobuf_protocol),
            "settings_routes": json_object_array(
                tag_route_to_json(route) for route in self.settings_routes
            ),
            "status": self.status,
            "thermal_fields": json_object_array(
                thermal_field_to_json(field) for field in self.thermal_fields
            ),
            "xmp_routes": json_object_array(tag_route_to_json(route) for route in self.xmp_routes),
        }


def build_dji_metadata_transaction_plan(
    *,
    source_bytes: bytes = b"",
    main_entries: Iterable[DjiMainTagInput] = (),
    main_payload: bytes | None = None,
    info_payload: bytes | None = None,
    info_dir_start: int = 0,
    info_dir_len: int | None = None,
    settings_payload: bytes | None = None,
    thermal_payload: bytes | None = None,
    thermal_table: DjiThermalTable = "ThermalParams",
    protobuf_protocol: str | None = None,
    protobuf_fields: Iterable[str] = (),
    protobuf_payload: bytes | None = None,
    xmp_properties: Mapping[str, DjiScalarValue] | None = None,
    unknown_payloads: Iterable[DjiPayloadInput] = (),
    rewrite_requests: Iterable[DjiRewriteRequest] = (),
    allow_output_emission: bool = False,
) -> DjiMetadataTransactionPlan:
    main_result = plan_main_routes(tuple(main_entries), main_payload)
    info_result = plan_info_routes(info_payload, info_dir_start, info_dir_len)
    settings_routes = plan_settings_routes(settings_payload)
    thermal_result = plan_thermal_fields(thermal_payload, thermal_table)
    xmp_routes = plan_xmp_routes(xmp_properties or {})
    protocol_plan = plan_protobuf_protocol(protobuf_protocol)
    protobuf_field_routes = plan_protobuf_field_routes(protobuf_protocol, tuple(protobuf_fields))
    protobuf_plan = plan_protobuf_payload(
        protobuf_payload,
        protobuf_protocol,
        allow_output_emission,
    )
    preserved_payloads = plan_preserved_payloads(tuple(unknown_payloads))
    actions = [
        *main_result.actions,
        *info_result.actions,
        *settings_actions(settings_routes),
        *thermal_result.actions,
        *xmp_actions(xmp_routes),
        *protobuf_actions(protocol_plan, protobuf_field_routes),
        *preservation_actions(preserved_payloads),
    ]
    blockers = [*main_result.blockers, *info_result.blockers, *thermal_result.blockers]
    gates: list[DjiOutputEmissionGate] = []
    gates.extend(gates_for_blockers(blockers))
    if protobuf_plan is not None:
        protobuf_validation_gates = tuple(
            gate
            for gate in protobuf_plan.output_emission_gates
            if gate.code
            not in {
                "non_mutating_plan_requires_explicit_emission",
                "rewrite_requested_requires_protobuf_writer",
            }
        )
        if protobuf_validation_gates:
            blockers.append(
                DjiTransactionBlocker(
                    code="malformed_protobuf_payload",
                    route_kind="protobuf",
                    byte_range=None,
                    reason="The delegated protobuf planner reported malformed or truncated data.",
                    evidence_ids=(DJI_PROTOBUF_SOURCE,),
                )
            )
            gates.append(
                DjiOutputEmissionGate(
                    code="malformed_protobuf_payload",
                    route_kind="protobuf",
                    reason="Malformed protobuf payload prevents safe DJI metadata emission.",
                    evidence_ids=(DJI_PROTOBUF_SOURCE,),
                )
            )
    for request in tuple(rewrite_requests):
        action, gate = rewrite_action_and_gate(request)
        actions.append(action)
        gates.append(gate)
    if not allow_output_emission:
        gates.append(
            DjiOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                route_kind=None,
                reason="DJI transaction plans preserve source bytes unless emission is explicit.",
                evidence_ids=(DJI_READ_BOUNDARY_SOURCE,),
            )
        )
        actions.append(
            DjiActionPlan(
                kind="no_metadata_mutation",
                route_kind="unknown_payload",
                tag_name=None,
                byte_range=None,
                reason=(
                    "The planner records routes and preservation boundaries without byte mutation."
                ),
                evidence_ids=(DJI_READ_BOUNDARY_SOURCE,),
            )
        )
    status: DjiPlanStatus = "unsupported" if blockers else "planned"
    gates_tuple = unique_gates(tuple(gates))
    sources = unique_evidence_ids(
        (
            *DJI_TRANSACTION_SOURCES,
            *(source for route in main_result.routes for source in route.evidence_ids),
            *(source for route in info_result.routes for source in route.evidence_ids),
            *(source for route in settings_routes for source in route.evidence_ids),
            *(source for field in thermal_result.fields for source in field.evidence_ids),
            *(source for route in xmp_routes for source in route.evidence_ids),
            *(protocol_plan.evidence_ids if protocol_plan is not None else ()),
            *(source for route in protobuf_field_routes for source in route.evidence_ids),
            *(source for payload in preserved_payloads for source in payload.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for blocker in blockers for source in blocker.evidence_ids),
            *(source for gate in gates_tuple for source in gate.evidence_ids),
        )
    )
    return DjiMetadataTransactionPlan(
        status=status,
        main_routes=main_result.routes,
        info_routes=info_result.routes,
        settings_routes=settings_routes,
        thermal_fields=thermal_result.fields,
        xmp_routes=xmp_routes,
        protobuf_protocol=protocol_plan,
        protobuf_field_routes=protobuf_field_routes,
        protobuf_plan=protobuf_plan,
        preserved_payloads=preserved_payloads,
        actions=tuple(actions),
        blockers=tuple(blockers),
        output_emission_gates=gates_tuple,
        evidence_ids=sources,
        original_bytes=source_bytes,
    )


@dataclass(frozen=True)
class RouteResult:
    routes: tuple[DjiTagRoutePlan, ...]
    actions: tuple[DjiActionPlan, ...]
    blockers: tuple[DjiTransactionBlocker, ...]


@dataclass(frozen=True)
class ThermalResult:
    fields: tuple[DjiThermalFieldPlan, ...]
    actions: tuple[DjiActionPlan, ...]
    blockers: tuple[DjiTransactionBlocker, ...]


def plan_main_routes(entries: tuple[DjiMainTagInput, ...], payload: bytes | None) -> RouteResult:
    inputs = list(entries)
    blockers: list[DjiTransactionBlocker] = []
    if payload is not None:
        parsed, parsed_blockers = parse_main_payload(payload)
        inputs.extend(parsed)
        blockers.extend(parsed_blockers)
    routes: list[DjiTagRoutePlan] = []
    actions: list[DjiActionPlan] = []
    for entry in inputs:
        definition = DJI_MAIN_TAGS.get(entry.tag_id)
        if definition is None:
            tag_name = f"Unknown_0x{entry.tag_id:04X}"
            responsibility: DjiResponsibilityKind = "unknown_payload"
            format_name: DjiMainValueFormat = "bytes"
            writable = False
        else:
            tag_name, format_name, responsibility = definition
            writable = True
        value = decode_main_value(entry.raw_value, format_name)
        route = DjiTagRoutePlan(
            route_kind="main_makernote",
            tag_id=entry.tag_id,
            source_name=f"0x{entry.tag_id:02X}",
            tag_name=tag_name,
            responsibility=responsibility,
            writable=writable,
            value=value,
            byte_range=entry.byte_range,
            evidence_ids=(DJI_MAIN_SOURCE,),
        )
        routes.append(route)
        actions.append(
            DjiActionPlan(
                kind="route_main_makernote_tag",
                route_kind="main_makernote",
                tag_name=tag_name,
                byte_range=entry.byte_range,
                reason="DJI Main maker-note tag routed through the source-backed table.",
                evidence_ids=(DJI_MAIN_SOURCE,),
            )
        )
    return RouteResult(tuple(routes), tuple(actions), tuple(blockers))


def parse_main_payload(payload: bytes) -> tuple[list[DjiMainTagInput], list[DjiTransactionBlocker]]:
    entries: list[DjiMainTagInput] = []
    blockers: list[DjiTransactionBlocker] = []
    offset = 0
    while offset < len(payload):
        if offset + 4 > len(payload):
            blockers.append(
                DjiTransactionBlocker(
                    code="truncated_main_makernote_record",
                    route_kind="main_makernote",
                    byte_range=(offset, len(payload)),
                    reason="Synthetic DJI Main TLV record header is incomplete.",
                    evidence_ids=(DJI_MAIN_SOURCE,),
                )
            )
            break
        tag_id = int.from_bytes(payload[offset : offset + 2], "big")
        length = int.from_bytes(payload[offset + 2 : offset + 4], "big")
        value_start = offset + 4
        value_end = value_start + length
        if value_end > len(payload):
            blockers.append(
                DjiTransactionBlocker(
                    code="truncated_main_makernote_record",
                    route_kind="main_makernote",
                    byte_range=(offset, len(payload)),
                    reason="Synthetic DJI Main TLV value extends beyond the available payload.",
                    evidence_ids=(DJI_MAIN_SOURCE,),
                )
            )
            break
        entries.append(
            DjiMainTagInput(
                tag_id=tag_id,
                raw_value=payload[value_start:value_end],
                byte_range=(offset, value_end),
            )
        )
        offset = value_end
    return entries, blockers


def decode_main_value(raw_value: bytes, format_name: DjiMainValueFormat) -> DjiScalarValue:
    if format_name == "float" and len(raw_value) >= 4:
        return round(float(struct.unpack("<f", raw_value[:4])[0]), 6)
    if format_name == "string":
        return trim_ascii(raw_value)
    return raw_value


def plan_info_routes(
    payload: bytes | None,
    dir_start: int,
    dir_len: int | None,
) -> RouteResult:
    if payload is None:
        return RouteResult((), (), ())
    if dir_start < 0 or dir_start > len(payload):
        blocker = DjiTransactionBlocker(
            code="invalid_info_debug_slice",
            route_kind="info_debug",
            byte_range=None,
            reason="DJI Info DirStart is outside the payload.",
            evidence_ids=(DJI_INFO_PROCESS_SOURCE,),
        )
        return RouteResult((), (), (blocker,))
    slice_end = len(payload) if dir_len is None else dir_start + dir_len
    if dir_len is not None and (dir_len < 0 or slice_end > len(payload)):
        blocker = DjiTransactionBlocker(
            code="invalid_info_debug_slice",
            route_kind="info_debug",
            byte_range=(dir_start, len(payload)),
            reason="DJI Info DirLen extends beyond the payload.",
            evidence_ids=(DJI_INFO_PROCESS_SOURCE,),
        )
        return RouteResult((), (), (blocker,))
    data = payload[dir_start:slice_end]
    routes: list[DjiTagRoutePlan] = []
    actions: list[DjiActionPlan] = []
    for match in INFO_ENTRY_RE.finditer(data):
        body = match.group(1)
        tag_raw, separator, value_raw = body.partition(b":")
        if not separator:
            continue
        source_name = tag_raw.decode("latin-1")
        tag_name = DJI_INFO_TAGS.get(source_name, source_name)
        value: DjiScalarValue = decoded_info_value(value_raw)
        byte_range = (dir_start + match.start(), dir_start + match.end())
        routes.append(
            DjiTagRoutePlan(
                route_kind="info_debug",
                tag_id=None,
                source_name=source_name,
                tag_name=tag_name,
                responsibility=info_responsibility(tag_name),
                writable=False,
                value=value,
                byte_range=byte_range,
                evidence_ids=(DJI_INFO_SOURCE, DJI_INFO_PROCESS_SOURCE),
            )
        )
        actions.append(
            DjiActionPlan(
                kind="parse_info_debug_tag",
                route_kind="info_debug",
                tag_name=tag_name,
                byte_range=byte_range,
                reason="DJI Info bracket entry routed through ProcessDJIInfo semantics.",
                evidence_ids=(DJI_INFO_SOURCE, DJI_INFO_PROCESS_SOURCE),
            )
        )
    return RouteResult(tuple(routes), tuple(actions), ())


def decoded_info_value(value: bytes) -> DjiScalarValue:
    stripped = value.rstrip(b"\x00")
    if stripped and all(0x20 <= byte <= 0x7E for byte in stripped):
        return stripped.decode("latin-1")
    return value


def info_responsibility(tag_name: str) -> DjiResponsibilityKind:
    if tag_name.startswith("Gimbal"):
        return "gimbal_metadata"
    if tag_name.startswith("Flight"):
        return "flight_metadata"
    return "debug_metadata"


def plan_settings_routes(payload: bytes | None) -> tuple[DjiTagRoutePlan, ...]:
    if payload is None:
        return ()
    text = payload.decode("latin-1")
    routes: list[DjiTagRoutePlan] = []
    offset = 0
    for part in text.split(";"):
        part_start = offset
        offset += len(part) + 1
        tag, separator, value = part.partition("=")
        if not tag or not separator:
            continue
        tag_name = DJI_SETTINGS_TAGS.get(tag, tag)
        routes.append(
            DjiTagRoutePlan(
                route_kind="settings",
                tag_id=None,
                source_name=tag,
                tag_name=tag_name,
                responsibility="settings_metadata",
                writable=False,
                value=value,
                byte_range=(part_start, part_start + len(part)),
                evidence_ids=(DJI_SETTINGS_TABLE_SOURCE, DJI_SETTINGS_PROCESS_SOURCE),
            )
        )
    return tuple(routes)


def settings_actions(routes: tuple[DjiTagRoutePlan, ...]) -> tuple[DjiActionPlan, ...]:
    return tuple(
        DjiActionPlan(
            kind="parse_settings_tag",
            route_kind="settings",
            tag_name=route.tag_name,
            byte_range=route.byte_range,
            reason="DJI settings entry routed after semicolon and equals splitting.",
            evidence_ids=(DJI_SETTINGS_TABLE_SOURCE, DJI_SETTINGS_PROCESS_SOURCE),
        )
        for route in routes
    )


def plan_thermal_fields(payload: bytes | None, table: DjiThermalTable) -> ThermalResult:
    if payload is None:
        return ThermalResult((), (), ())
    fields: list[DjiThermalFieldPlan] = []
    actions: list[DjiActionPlan] = []
    blockers: list[DjiTransactionBlocker] = []
    for offset, definition in DJI_THERMAL_FIELDS[table].items():
        name, format_name = definition
        field_size = thermal_field_size(format_name)
        end = offset + field_size
        if end > len(payload):
            blockers.append(
                DjiTransactionBlocker(
                    code="truncated_thermal_app4_field",
                    route_kind="thermal_app4",
                    byte_range=(offset, len(payload)),
                    reason=f"{table} field {name} extends beyond the APP4 payload.",
                    evidence_ids=(DJI_THERMAL_SOURCE,),
                )
            )
            continue
        raw = payload[offset:end]
        value = decode_thermal_value(raw, format_name)
        field = DjiThermalFieldPlan(
            table=table,
            offset=offset,
            tag_name=name,
            format_name=format_name,
            value=value,
            byte_range=(offset, end),
            evidence_ids=(DJI_THERMAL_SOURCE,),
        )
        fields.append(field)
        actions.append(
            DjiActionPlan(
                kind="route_thermal_app4_field",
                route_kind="thermal_app4",
                tag_name=name,
                byte_range=(offset, end),
                reason="DJI thermal APP4 binary field routed from the ThermalParams table.",
                evidence_ids=(DJI_THERMAL_SOURCE,),
            )
        )
    return ThermalResult(tuple(fields), tuple(actions), tuple(blockers))


def thermal_field_size(format_name: str) -> int:
    if format_name == "float" or format_name == "int32s":
        return 4
    if format_name == "string[16]":
        return 16
    return 2


def decode_thermal_value(raw: bytes, format_name: str) -> DjiScalarValue:
    if format_name == "float":
        return round(float(struct.unpack("<f", raw)[0]), 6)
    if format_name == "int32s":
        return int.from_bytes(raw, "little", signed=True)
    if format_name == "string[16]":
        return trim_ascii(raw)
    base = int.from_bytes(raw, "little", signed=False)
    if format_name == "int16u/10":
        return base / 10
    if format_name == "int16u/100":
        return base / 100
    return base


def plan_xmp_routes(properties: Mapping[str, DjiScalarValue]) -> tuple[DjiTagRoutePlan, ...]:
    routes: list[DjiTagRoutePlan] = []
    for source_name, value in properties.items():
        definition = DJI_XMP_ROUTES.get(source_name)
        if definition is None:
            tag_name = source_name
            responsibility: DjiResponsibilityKind = "unknown_payload"
            writable = False
        else:
            tag_name, responsibility, writable = definition
        routes.append(
            DjiTagRoutePlan(
                route_kind="xmp",
                tag_id=None,
                source_name=source_name,
                tag_name=tag_name,
                responsibility=responsibility,
                writable=writable,
                value=value,
                byte_range=None,
                evidence_ids=(DJI_XMP_SOURCE,),
            )
        )
    return tuple(routes)


def xmp_actions(routes: tuple[DjiTagRoutePlan, ...]) -> tuple[DjiActionPlan, ...]:
    return tuple(
        DjiActionPlan(
            kind="route_xmp_property",
            route_kind="xmp",
            tag_name=route.tag_name,
            byte_range=None,
            reason="DJI XMP property routed through the drone-dji namespace table.",
            evidence_ids=(DJI_XMP_SOURCE,),
        )
        for route in routes
    )


def plan_protobuf_protocol(protocol: str | None) -> DjiProtobufProtocolPlan | None:
    if protocol is None:
        return None
    known = protocol in DJI_KNOWN_PROTOCOLS
    dbginfo = protocol.startswith("dbginfo")
    warning = None if known or dbginfo else f"Unknown protocol {protocol}"
    return DjiProtobufProtocolPlan(
        protocol_name=protocol,
        known=known,
        accepted_by_dbginfo_prefix=dbginfo,
        warning=warning,
        evidence_ids=(DJI_KNOWN_PROTOCOL_SOURCE, DJI_PROTOBUF_SOURCE),
    )


def plan_protobuf_field_routes(
    protocol: str | None,
    fields: tuple[str, ...],
) -> tuple[DjiProtobufFieldRoutePlan, ...]:
    routes: list[DjiProtobufFieldRoutePlan] = []
    for field in fields:
        protocol_name, path = split_protobuf_field(protocol, field)
        tag_name, responsibility, subdirectory, known = protobuf_route_for_path(path)
        routes.append(
            DjiProtobufFieldRoutePlan(
                protocol_name=protocol_name,
                field_path=path,
                tag_name=tag_name,
                responsibility=responsibility,
                subdirectory=subdirectory,
                known=known,
                evidence_ids=(DJI_PROTOBUF_SOURCE, DJI_SUBDIRECTORY_SOURCE),
            )
        )
    return tuple(routes)


def split_protobuf_field(protocol: str | None, field: str) -> tuple[str | None, str]:
    for marker in ("_dvtm_", "_dbginfo_"):
        if marker in f"_{field}":
            pieces = field.rsplit("_", maxsplit=1)
            if len(pieces) == 2:
                proto_prefix, path = pieces
                return proto_prefix_to_name(proto_prefix), path
    if protocol is not None:
        prefix = protocol.removesuffix(".proto")
        if field.startswith(f"{prefix}_"):
            return protocol, field[len(prefix) + 1 :]
    return protocol, field


def proto_prefix_to_name(prefix: str) -> str:
    return f"{prefix}.proto" if prefix.startswith("dvtm_") else prefix


def protobuf_route_for_path(path: str) -> tuple[str, DjiResponsibilityKind, str | None, bool]:
    direct = DJI_PROTOBUF_FIELD_ROUTES.get(path)
    if direct is not None:
        name, responsibility, subdirectory = direct
        return name, responsibility, subdirectory, True
    for subdirectory, routes in DJI_SUBDIRECTORY_ROUTES.items():
        if path in routes:
            name, responsibility = routes[path]
            return name, responsibility, subdirectory, True
    return path, "unknown_payload", None, False


def protobuf_actions(
    protocol: DjiProtobufProtocolPlan | None,
    fields: tuple[DjiProtobufFieldRoutePlan, ...],
) -> tuple[DjiActionPlan, ...]:
    actions: list[DjiActionPlan] = []
    if protocol is not None:
        actions.append(
            DjiActionPlan(
                kind="route_protobuf_protocol",
                route_kind="protobuf",
                tag_name="Protocol",
                byte_range=None,
                reason="DJI protobuf protocol routed with knownProtocol/dbginfo handling.",
                evidence_ids=(DJI_KNOWN_PROTOCOL_SOURCE, DJI_PROTOBUF_SOURCE),
            )
        )
    for field in fields:
        actions.append(
            DjiActionPlan(
                kind="route_protobuf_field",
                route_kind="protobuf",
                tag_name=field.tag_name,
                byte_range=None,
                reason="DJI protobuf field path routed through top-level or nested tables.",
                evidence_ids=(DJI_PROTOBUF_SOURCE, DJI_SUBDIRECTORY_SOURCE),
            )
        )
    return tuple(actions)


def plan_protobuf_payload(
    payload: bytes | None,
    protocol: str | None,
    allow_output_emission: bool,
) -> ProtobufMetadataTransactionPlan | None:
    if payload is None:
        return None
    field_database = ProtobufFieldDatabase(
        definitions=protobuf_field_definitions(protocol),
        tag_prefix=protocol.removesuffix(".proto") + "_" if protocol is not None else None,
    )
    return build_protobuf_metadata_transaction_plan(
        payload,
        field_database=field_database,
        allow_output_emission=allow_output_emission,
    )


def protobuf_field_definitions(protocol: str | None) -> tuple[ProtobufFieldDefinition, ...]:
    prefix = "" if protocol is None else f"{protocol.removesuffix('.proto')}_"
    definitions: list[ProtobufFieldDefinition] = [
        ProtobufFieldDefinition("1-1-1", "Protocol", expected_wire_type=2, format_name="string")
    ]
    for path, route in DJI_PROTOBUF_FIELD_ROUTES.items():
        tag_name, _responsibility, subdirectory = route
        definitions.append(
            ProtobufFieldDefinition(
                f"{prefix}{path}",
                tag_name,
                has_subdirectory=subdirectory is not None,
            )
        )
    return tuple(definitions)


def plan_preserved_payloads(
    payloads: tuple[DjiPayloadInput, ...],
) -> tuple[DjiPreservedPayloadPlan, ...]:
    return tuple(
        DjiPreservedPayloadPlan(
            route_kind=payload.route_kind,
            payload=payload.payload,
            byte_range=payload.byte_range,
            label=payload.label,
            evidence_ids=(DJI_READ_BOUNDARY_SOURCE,),
        )
        for payload in payloads
    )


def preservation_actions(
    payloads: tuple[DjiPreservedPayloadPlan, ...],
) -> tuple[DjiActionPlan, ...]:
    return tuple(
        DjiActionPlan(
            kind="preserve_payload",
            route_kind=payload.route_kind,
            tag_name=payload.label,
            byte_range=payload.byte_range,
            reason="DJI planner preserves raw payload bytes outside source-backed routing.",
            evidence_ids=payload.evidence_ids,
        )
        for payload in payloads
    )


def rewrite_action_and_gate(
    request: DjiRewriteRequest,
) -> tuple[DjiActionPlan, DjiOutputEmissionGate]:
    if request.target in {"main_makernote", "xmp"}:
        source = DJI_MAIN_SOURCE if request.target == "main_makernote" else DJI_XMP_SOURCE
        return (
            DjiActionPlan(
                kind="route_source_backed_rewrite",
                route_kind=request.target,
                tag_name=request.tag_name,
                byte_range=None,
                reason=(
                    "Rewrite request targets a DJI table with source-backed writability, "
                    "but this planner does not mutate bytes."
                ),
                evidence_ids=(source,),
            ),
            DjiOutputEmissionGate(
                code="source_backed_rewrite_requires_downstream_writer",
                route_kind=request.target,
                reason="A downstream writer is required to apply this source-backed DJI rewrite.",
                evidence_ids=(source,),
            ),
        )
    return (
        DjiActionPlan(
            kind="block_requested_rewrite",
            route_kind=request.target,
            tag_name=request.tag_name,
            byte_range=None,
            reason="DJI.pm does not provide source-backed write behavior for this route.",
            evidence_ids=(DJI_READ_BOUNDARY_SOURCE,),
        ),
        DjiOutputEmissionGate(
            code="unsupported_rewrite_requested",
            route_kind=request.target,
            reason=(
                f"Requested {request.operation} rewrite is not source-backed for {request.target}."
            ),
            evidence_ids=(DJI_READ_BOUNDARY_SOURCE,),
        ),
    )


def gates_for_blockers(blockers: list[DjiTransactionBlocker]) -> tuple[DjiOutputEmissionGate, ...]:
    gates: list[DjiOutputEmissionGate] = []
    for blocker in blockers:
        gates.append(
            DjiOutputEmissionGate(
                code=blocker_code_to_gate_code(blocker.code),
                route_kind=blocker.route_kind,
                reason=blocker.reason,
                evidence_ids=blocker.evidence_ids,
            )
        )
    return tuple(gates)


def blocker_code_to_gate_code(code: DjiBlockerCode) -> DjiEmissionGateCode:
    if code == "truncated_main_makernote_record":
        return "truncated_main_makernote_record"
    if code == "invalid_info_debug_slice":
        return "invalid_info_debug_slice"
    if code == "truncated_thermal_app4_field":
        return "truncated_thermal_app4_field"
    return "malformed_protobuf_payload"


def trim_ascii(payload: bytes) -> str:
    return payload.split(b"\x00", maxsplit=1)[0].decode("latin-1")


def action_to_json(action: DjiActionPlan) -> JsonObject:
    return {
        "byte_range": tuple_to_json(action.byte_range),
        "kind": action.kind,
        "reason": action.reason,
        "route_kind": action.route_kind,
        "tag_name": action.tag_name,
    }


def blocker_to_json(blocker: DjiTransactionBlocker) -> JsonObject:
    return {
        "byte_range": tuple_to_json(blocker.byte_range),
        "code": blocker.code,
        "reason": blocker.reason,
        "route_kind": blocker.route_kind,
    }


def emission_gate_to_json(gate: DjiOutputEmissionGate) -> JsonObject:
    return {
        "code": gate.code,
        "reason": gate.reason,
        "route_kind": gate.route_kind,
    }


def tag_route_to_json(route: DjiTagRoutePlan) -> JsonObject:
    return {
        "byte_range": tuple_to_json(route.byte_range),
        "responsibility": route.responsibility,
        "route_kind": route.route_kind,
        "source_name": route.source_name,
        "tag_id": route.tag_id,
        "tag_name": route.tag_name,
        "value": scalar_to_json(route.value),
        "writable": route.writable,
    }


def thermal_field_to_json(field: DjiThermalFieldPlan) -> JsonObject:
    return {
        "byte_range": tuple_to_json(field.byte_range),
        "format_name": field.format_name,
        "offset": field.offset,
        "table": field.table,
        "tag_name": field.tag_name,
        "value": scalar_to_json(field.value),
    }


def protobuf_protocol_to_json(protocol: DjiProtobufProtocolPlan | None) -> JsonObject | None:
    if protocol is None:
        return None
    return {
        "accepted_by_dbginfo_prefix": protocol.accepted_by_dbginfo_prefix,
        "known": protocol.known,
        "protocol_name": protocol.protocol_name,
        "warning": protocol.warning,
    }


def protobuf_field_route_to_json(route: DjiProtobufFieldRoutePlan) -> JsonObject:
    return {
        "field_path": route.field_path,
        "known": route.known,
        "protocol_name": route.protocol_name,
        "responsibility": route.responsibility,
        "subdirectory": route.subdirectory,
        "tag_name": route.tag_name,
    }


def preserved_payload_to_json(payload: DjiPreservedPayloadPlan) -> JsonObject:
    return {
        "byte_range": tuple_to_json(payload.byte_range),
        "label": payload.label,
        "payload_hex": payload.payload.hex(),
        "route_kind": payload.route_kind,
    }


def scalar_to_json(value: DjiScalarValue | None) -> JsonValue:
    if isinstance(value, bytes):
        return value.hex()
    return value


def tuple_to_json(value: tuple[int, int] | None) -> JsonArray | None:
    if value is None:
        return None
    return [value[0], value[1]]


def json_object_array(items: Iterable[JsonObject]) -> JsonArray:
    return list(items)


def unique_evidence_ids(sources: tuple[DjiEvidenceId, ...]) -> tuple[DjiEvidenceId, ...]:
    unique: list[DjiEvidenceId] = []
    seen: set[DjiEvidenceId] = set()
    for source in sources:
        if source not in seen:
            unique.append(source)
            seen.add(source)
    return tuple(unique)


def unique_gates(gates: tuple[DjiOutputEmissionGate, ...]) -> tuple[DjiOutputEmissionGate, ...]:
    unique: list[DjiOutputEmissionGate] = []
    seen: set[tuple[DjiEmissionGateCode, DjiMetadataRouteKind | None, str]] = set()
    for gate in gates:
        key = (gate.code, gate.route_kind, gate.reason)
        if key not in seen:
            unique.append(gate)
            seen.add(key)
    return tuple(unique)
