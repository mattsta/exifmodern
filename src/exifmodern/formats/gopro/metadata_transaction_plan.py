"""Source-backed, non-mutating GoPro GPMF metadata transaction planning."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

type GoproContainerKind = Literal["quicktime_gpmf_box", "quicktime_gpmd_sample", "jpeg_app6"]
type GoproFormatName = Literal[
    "container",
    "int8s",
    "int8u",
    "string",
    "int16s",
    "int16u",
    "int32s",
    "int32u",
    "float",
    "double",
    "fourcc",
    "uuid",
    "int64s",
    "int64u",
    "fixed32s",
    "fixed64s",
    "date16",
    "structure",
    "undef",
]
type GoproRecordRole = Literal[
    "device_container",
    "stream_container",
    "telemetry_sample",
    "stream_configuration",
    "camera_metadata",
    "gps_metadata",
    "imu_metadata",
    "image_sensor_metadata",
    "time_metadata",
    "preserved_unknown",
    "other_metadata",
]
type GoproRewriteOperation = Literal["replace_record", "insert_record", "delete_record"]
type GoproEmissionGateCode = Literal[
    "truncated_gpmf_record_header",
    "unrecognized_gopro_record",
    "truncated_gopro_record",
    "malformed_gopro_structure",
    "unsupported_gopro_rewrite",
    "raw_payload_preservation_required",
    "planner_is_non_mutating",
    "gopro_writer_not_implemented",
]
type GoproPlanningConcern = Literal[
    "gpmf_record_header_decoding",
    "quicktime_and_app6_group_routing",
    "device_container_recursion",
    "stream_container_recursion",
    "stream_configuration_state",
    "telemetry_sample_field_routing",
    "gps_tag_surface",
    "imu_tag_surface",
    "camera_tag_surface",
    "unknown_key_preservation",
    "malformed_and_truncation_blockers",
    "non_mutating_rewrite_gates",
]
type GoproScalar = int | float | str | bytes
type GoproDecodedValue = GoproScalar | tuple[GoproScalar, ...] | tuple[tuple[GoproScalar, ...], ...]


@dataclass(frozen=True)
class EvidenceAnchor:
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


GOPRO_FORMAT_SOURCE = EvidenceAnchor(
    path="lib/Image/ExifTool/GoPro.pm",
    line_start=32,
    line_end=55,
    symbol="%goProFmt and %goProSize",
    evidence="GoPro.pm maps GPMF format bytes to ExifTool formats and special sizes.",
)
GOPRO_GPMF_TABLE_SOURCE = EvidenceAnchor(
    path="lib/Image/ExifTool/GoPro.pm",
    line_start=65,
    line_end=485,
    symbol="%Image::ExifTool::GoPro::GPMF",
    evidence="The GPMF table declares GoPro device, stream, camera, GPS, IMU, and sensor tags.",
)
GOPRO_GPS5_SOURCE = EvidenceAnchor(
    path="lib/Image/ExifTool/GoPro.pm",
    line_start=487,
    line_end=514,
    symbol="%Image::ExifTool::GoPro::GPS5",
    evidence=(
        "GPS5 samples route indexes 0..4 to latitude, longitude, altitude, speed, and 3D speed."
    ),
)
GOPRO_GPS9_SOURCE = EvidenceAnchor(
    path="lib/Image/ExifTool/GoPro.pm",
    line_start=516,
    line_end=563,
    symbol="%Image::ExifTool::GoPro::GPS9",
    evidence="GPS9 samples extend GPS5 with days, date/time seconds, DOP, and measure mode.",
)
GOPRO_GPRI_SOURCE = EvidenceAnchor(
    path="lib/Image/ExifTool/GoPro.pm",
    line_start=565,
    line_end=595,
    symbol="%Image::ExifTool::GoPro::GPRI",
    evidence="Karma raw GPS samples define raw date/time, position, speed, and track fields.",
)
GOPRO_GLPI_SOURCE = EvidenceAnchor(
    path="lib/Image/ExifTool/GoPro.pm",
    line_start=597,
    line_end=626,
    symbol="%Image::ExifTool::GoPro::GLPI",
    evidence="Karma GPS position samples define date/time, position, velocity, and track fields.",
)
GOPRO_KBAT_SOURCE = EvidenceAnchor(
    path="lib/Image/ExifTool/GoPro.pm",
    line_start=628,
    line_end=649,
    symbol="%Image::ExifTool::GoPro::KBAT",
    evidence=(
        "Karma battery samples define current, capacity, temperature, voltage, time, and level."
    ),
)
GOPRO_PROCESS_STRING_SOURCE = EvidenceAnchor(
    path="lib/Image/ExifTool/GoPro.pm",
    line_start=745,
    line_end=777,
    symbol="ProcessString",
    evidence="ProcessString splits sample strings into indexed sub-tags and advances sub-docs.",
)
GOPRO_GP6_SOURCE = EvidenceAnchor(
    path="lib/Image/ExifTool/GoPro.pm",
    line_start=779,
    line_end=803,
    symbol="ProcessGP6",
    evidence="MP4 mdat GP records are scanned for DEVC payloads before GPMF processing.",
)
GOPRO_PROCESS_SOURCE = EvidenceAnchor(
    path="lib/Image/ExifTool/GoPro.pm",
    line_start=805,
    line_end=899,
    symbol="ProcessGoPro",
    evidence=(
        "ProcessGoPro routes APP6 or QuickTime groups, decodes padded GPMF records, "
        "recurses subdirectories, preserves data ranges, warns on malformed records, "
        "and records TYPE/UNIT/SCAL state."
    ),
)

FORMAT_NAMES: dict[int, GoproFormatName] = {
    0x00: "container",
    0x62: "int8s",
    0x42: "int8u",
    0x63: "string",
    0x73: "int16s",
    0x53: "int16u",
    0x6C: "int32s",
    0x4C: "int32u",
    0x66: "float",
    0x64: "double",
    0x46: "fourcc",
    0x47: "uuid",
    0x6A: "int64s",
    0x4A: "int64u",
    0x71: "fixed32s",
    0x51: "fixed64s",
    0x55: "date16",
    0x3F: "structure",
}
FORMAT_SIZES: dict[int, int] = {
    0x62: 1,
    0x42: 1,
    0x73: 2,
    0x53: 2,
    0x6C: 4,
    0x4C: 4,
    0x66: 4,
    0x64: 8,
    0x46: 4,
    0x47: 16,
    0x6A: 8,
    0x4A: 8,
    0x71: 4,
    0x51: 8,
    0x55: 16,
}
STRUCT_FORMATS: dict[int, str] = {
    0x62: ">b",
    0x42: ">B",
    0x73: ">h",
    0x53: ">H",
    0x6C: ">i",
    0x4C: ">I",
    0x66: ">f",
    0x64: ">d",
    0x6A: ">q",
    0x4A: ">Q",
    0x71: ">i",
    0x51: ">q",
}
TAG_ID_RE = re.compile(rb"^[-_a-zA-Z0-9 ]{4}$")

GPMF_TAG_NAMES: dict[str, str] = {
    "ABSC": "AutoBoostScore",
    "ACCL": "Accelerometer",
    "ALLD": "AutoLowLightDuration",
    "APTO": "AudioProtuneOption",
    "ARUW": "AspectRatioUnwarped",
    "ARWA": "AspectRatioWarped",
    "ATTD": "Attitude",
    "ATTR": "AttitudeTarget",
    "AUBT": "AudioBlueTooth",
    "AUDO": "AudioSetting",
    "AUPT": "AutoProtune",
    "BITR": "BitrateSetting",
    "BPOS": "Controller",
    "CASN": "CameraSerialNumber",
    "CDAT": "CreationDate",
    "CDTM": "CaptureDelayTimer",
    "CLDP": "ClassificationDataPresent",
    "CPIN": "ChapterNumber",
    "CSEN": "CoyoteSense",
    "CTRL": "ControlLevel",
    "CYTS": "CoyoteStatus",
    "DEVC": "DeviceContainer",
    "DUST": "DurationSetting",
    "DVID": "DeviceID",
    "DVNM": "DeviceName",
    "DZOM": "DigitalZoomOn",
    "DZMX": "DigitalZoomAmount",
    "DZST": "DigitalZoom",
    "EISA": "ElectronicImageStabilization",
    "EISE": "ElectronicStabilizationOn",
    "EMPT": "Empty",
    "ESCS": "EscapeStatus",
    "EXPT": "ExposureType",
    "FACE": "FaceDetected",
    "FCNM": "FaceNumbers",
    "FMWR": "FirmwareVersion",
    "FWVS": "OtherFirmware",
    "GLPI": "GPSPos",
    "GPRI": "GPSRaw",
    "GPS5": "GPSInfo",
    "GPS9": "GPSInfo9",
    "GPSA": "GPSAltitudeSystem",
    "GPSF": "GPSMeasureMode",
    "GPSP": "GPSHPositioningError",
    "GPSU": "GPSDateTime",
    "GYRO": "Gyroscope",
    "LOGS": "HealthLogs",
    "HCTL": "HorizonControl",
    "HDRV": "HDRVideo",
    "HSGT": "HindsightSettings",
    "ISOE": "ISOSpeeds",
    "ISOG": "ImageSensorGain",
    "KBAT": "BatteryStatus",
    "LNED": "LocalPositionNED",
    "MAGN": "Magnetometer",
    "MAPX": "MappingXCoefficients",
    "MAPY": "MappingYCoefficients",
    "MINF": "Model",
    "MMOD": "MediaMode",
    "MTRX": "AccelerometerMatrix",
    "MUID": "MediaUniqueID",
    "MXCF": "MappingXMode",
    "MYCF": "MappingYMode",
    "ORDP": "OrientationDataPresent",
    "OREN": "AutoRotation",
    "ORIN": "InputOrientation",
    "ORIO": "OutputOrientation",
    "PHDR": "HDRSetting",
    "PIMD": "ProtuneISOMode",
    "PIMN": "AutoISOMin",
    "PIMX": "AutoISOMax",
    "POLY": "PolynomialCoefficients",
    "PRES": "PhotoResolution",
    "PRJT": "LensProjection",
    "PRTN": "Protune",
    "PTCL": "ColorMode",
    "PTEV": "ExposureCompensation",
    "PTSH": "Sharpness",
    "PTWB": "WhiteBalance",
    "PWPR": "PowerProfile",
    "PYCF": "PolynomialPower",
    "RAMP": "SpeedRampSetting",
    "RATE": "Rate",
    "RMRK": "Comments",
    "SCAL": "ScaleFactor",
    "SCAP": "ScheduleCapture",
    "SCPR": "ScaledPressure",
    "SCTM": "ScheduleCaptureTime",
    "SHUT": "ExposureTimes",
    "SIMU": "ScaledIMU",
    "SIUN": "SIUnits",
    "SMTR": "SpotMeter",
    "SROT": "SensorReadoutTime",
    "STMP": "TimeStamp",
    "STRM": "NestedSignalStream",
    "STNM": "StreamName",
    "SYST": "SystemTime",
    "TMPC": "CameraTemperature",
    "TSMP": "TotalSamples",
    "TIMO": "TimeOffset",
    "TYPE": "StructureType",
    "TZON": "TimeZone",
    "UNIT": "Units",
    "UNIF": "InputUniformity",
    "VERS": "MetadataVersion",
    "VFOV": "FieldOfView",
    "VFPS": "VideoFrameRate",
    "VFRH": "VisualFlightRulesHUD",
    "VRES": "VideoFrameSize",
    "WBAL": "ColorTemperatures",
    "WRGB": "WhiteBalanceRGB",
    "ZFOV": "DiagonalFieldOfView",
    "ZMPL": "ZoomScaleNormalization",
    "CORI": "CameraOrientation",
    "AALP": "AudioLevel",
    "GRAV": "GravityVector",
    "HUES": "PredominantHue",
    "IORI": "ImageOrientation",
    "MWET": "MicrophoneWet",
    "SCEN": "SceneClassification",
    "WNDM": "WindProcessing",
    "YAVG": "LumaAverage",
}
GPS5_FIELDS = ("GPSLatitude", "GPSLongitude", "GPSAltitude", "GPSSpeed", "GPSSpeed3D")
GPS9_FIELDS = (
    "GPSLatitude",
    "GPSLongitude",
    "GPSAltitude",
    "GPSSpeed",
    "GPSSpeed3D",
    "GPSDays",
    "GPSDateTime",
    "GPSDOP",
    "GPSMeasureMode",
)
GPS9_HIDDEN_FIELDS = frozenset(("GPSDays",))
GPRI_FIELDS = (
    "GPSDateTimeRaw",
    "GPSLatitudeRaw",
    "GPSLongitudeRaw",
    "GPSAltitudeRaw",
    "GPRI_Unknown4",
    "GPRI_Unknown5",
    "GPSSpeedRaw",
    "GPSTrackRaw",
    "GPRI_Unknown8",
    "GPRI_Unknown9",
)
GPRI_HIDDEN_FIELDS = frozenset(("GPRI_Unknown4", "GPRI_Unknown5", "GPRI_Unknown8", "GPRI_Unknown9"))
GLPI_FIELDS = (
    "GPSDateTime",
    "GPSLatitude",
    "GPSLongitude",
    "GPSAltitude",
    "GLPI_Unknown4",
    "GPSSpeedX",
    "GPSSpeedY",
    "GPSSpeedZ",
    "GPSTrack",
)
GLPI_HIDDEN_FIELDS = frozenset(("GLPI_Unknown4",))
KBAT_FIELDS = (
    "BatteryCurrent",
    "BatteryCapacity",
    "KBAT_Unknown2",
    "BatteryTemperature",
    "BatteryVoltage1",
    "BatteryVoltage2",
    "BatteryVoltage3",
    "BatteryVoltage4",
    "BatteryTime",
    "KBAT_Unknown9",
    "KBAT_Unknown10",
    "KBAT_Unknown11",
    "KBAT_Unknown12",
    "KBAT_Unknown13",
    "BatteryLevel",
)
KBAT_HIDDEN_FIELDS = frozenset(
    (
        "KBAT_Unknown2",
        "KBAT_Unknown9",
        "KBAT_Unknown10",
        "KBAT_Unknown11",
        "KBAT_Unknown12",
        "KBAT_Unknown13",
    )
)
SAMPLE_FIELDS: dict[str, tuple[str, ...]] = {
    "GPS5": GPS5_FIELDS,
    "GPS9": GPS9_FIELDS,
    "GPRI": GPRI_FIELDS,
    "GLPI": GLPI_FIELDS,
    "KBAT": KBAT_FIELDS,
}
HIDDEN_SAMPLE_FIELDS: dict[str, frozenset[str]] = {
    "GPS9": GPS9_HIDDEN_FIELDS,
    "GPRI": GPRI_HIDDEN_FIELDS,
    "GLPI": GLPI_HIDDEN_FIELDS,
    "KBAT": KBAT_HIDDEN_FIELDS,
}
SAMPLE_SOURCES: dict[str, EvidenceAnchor] = {
    "GPS5": GOPRO_GPS5_SOURCE,
    "GPS9": GOPRO_GPS9_SOURCE,
    "GPRI": GOPRO_GPRI_SOURCE,
    "GLPI": GOPRO_GLPI_SOURCE,
    "KBAT": GOPRO_KBAT_SOURCE,
}
GPS_TAGS = frozenset(("GPS5", "GPS9", "GPRI", "GLPI", "GPSA", "GPSF", "GPSP", "GPSU"))
IMU_TAGS = frozenset(
    ("ACCL", "GYRO", "GRAV", "MAGN", "MTRX", "SIMU", "ATTD", "ATTR", "CSEN", "CYTS", "LNED")
)
IMAGE_SENSOR_TAGS = frozenset(("ISOG", "ISOE", "SHUT", "WBAL", "WRGB", "CORI", "IORI"))
TIME_TAGS = frozenset(("CDAT", "GPSU", "STMP", "SYST", "TIMO", "TZON"))
STREAM_CONFIGURATION_TAGS = frozenset(("TYPE", "UNIT", "SIUN", "SCAL", "STNM", "TSMP", "STMP"))


@dataclass(frozen=True)
class GoproRewriteRequest:
    operation: GoproRewriteOperation
    target_path: tuple[str, ...]
    tag_key: str
    payload: bytes = b""


@dataclass(frozen=True)
class GoproSampleFieldPlan:
    sample_index: int
    field_index: int
    tag_name: str
    value: GoproScalar
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "field_index": self.field_index,
            "sample_index": self.sample_index,
            "tag_name": self.tag_name,
            "value": scalar_to_json(self.value),
        }


@dataclass(frozen=True)
class GoproRecordPlan:
    tag_key: str
    tag_name: str
    role: GoproRecordRole
    path: tuple[str, ...]
    group0: str
    format_code: int
    format_name: GoproFormatName
    element_size: int
    element_count: int
    payload_size: int
    header_range: tuple[int, int]
    payload_range: tuple[int, int]
    raw_record_range: tuple[int, int]
    raw_payload: bytes
    decoded_value: GoproDecodedValue | None
    sample_fields: tuple[GoproSampleFieldPlan, ...]
    child_records: tuple[GoproRecordPlan, ...]
    is_known: bool
    evidence_anchors: tuple[EvidenceAnchor, ...]

    @property
    def is_container(self) -> bool:
        return self.role in ("device_container", "stream_container")

    def to_json(self) -> JsonObject:
        return {
            "child_records": [record.to_json() for record in self.child_records],
            "decoded_value": decoded_to_json(self.decoded_value),
            "element_count": self.element_count,
            "element_size": self.element_size,
            "format_code": self.format_code,
            "format_name": self.format_name,
            "group0": self.group0,
            "header_range": range_to_json(self.header_range),
            "is_known": self.is_known,
            "path": list(self.path),
            "payload_range": range_to_json(self.payload_range),
            "payload_size": self.payload_size,
            "raw_payload_hex": self.raw_payload.hex(),
            "raw_record_range": range_to_json(self.raw_record_range),
            "role": self.role,
            "sample_fields": [field.to_json() for field in self.sample_fields],
            "tag_key": self.tag_key,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class GoproMetadataEntryPlan:
    tag_key: str
    tag_name: str
    path: tuple[str, ...]
    group0: str
    role: GoproRecordRole
    value: GoproDecodedValue | None
    raw_payload: bytes
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "group0": self.group0,
            "path": list(self.path),
            "raw_payload_hex": self.raw_payload.hex(),
            "role": self.role,
            "tag_key": self.tag_key,
            "tag_name": self.tag_name,
            "value": decoded_to_json(self.value),
        }


@dataclass(frozen=True)
class GoproPlanningResponsibility:
    concern: GoproPlanningConcern
    detail: str
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GoproEmissionGate:
    code: GoproEmissionGateCode
    reason: str
    offset: int | None
    blocks_emission: bool
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "offset": self.offset,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GoproMetadataTransactionPlan:
    container_kind: GoproContainerKind
    group0: str
    records: tuple[GoproRecordPlan, ...]
    metadata_entries: tuple[GoproMetadataEntryPlan, ...]
    responsibilities: tuple[GoproPlanningResponsibility, ...]
    output_emission_gates: tuple[GoproEmissionGate, ...]
    rewrite_requests: tuple[GoproRewriteRequest, ...]
    evidence_anchors: tuple[EvidenceAnchor, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def unknown_records(self) -> tuple[GoproRecordPlan, ...]:
        return tuple(record for record in flatten_records(self.records) if not record.is_known)

    @property
    def telemetry_records(self) -> tuple[GoproRecordPlan, ...]:
        return tuple(
            record for record in flatten_records(self.records) if record.role == "telemetry_sample"
        )

    @property
    def device_records(self) -> tuple[GoproRecordPlan, ...]:
        return tuple(
            record for record in flatten_records(self.records) if record.role == "device_container"
        )

    @property
    def stream_records(self) -> tuple[GoproRecordPlan, ...]:
        return tuple(
            record for record in flatten_records(self.records) if record.role == "stream_container"
        )

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"GoPro metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "container_kind": self.container_kind,
            "group0": self.group0,
            "metadata_entries": [entry.to_json() for entry in self.metadata_entries],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "records": [record.to_json() for record in self.records],
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "rewrite_requests": [
                {
                    "operation": request.operation,
                    "payload_hex": request.payload.hex(),
                    "tag_key": request.tag_key,
                    "target_path": list(request.target_path),
                }
                for request in self.rewrite_requests
            ],
        }


def build_gopro_metadata_transaction_plan(
    data: bytes,
    *,
    container_kind: GoproContainerKind = "quicktime_gpmf_box",
    rewrite_requests: tuple[GoproRewriteRequest, ...] = (),
    include_hidden_sample_fields: bool = False,
) -> GoproMetadataTransactionPlan:
    """Build a source-backed GoPro GPMF plan without mutating bytes."""

    group0 = "APP6" if container_kind == "jpeg_app6" else "QuickTime"
    records, parse_gates = parse_gpmf_records(
        data,
        0,
        len(data),
        (),
        group0,
        include_hidden_sample_fields=include_hidden_sample_fields,
    )
    gates = [*parse_gates]
    for request in rewrite_requests:
        gates.append(
            GoproEmissionGate(
                "unsupported_gopro_rewrite",
                (
                    f"Rewrite request {request.operation} for {request.tag_key} is not "
                    "enabled because GoPro.pm supplies read-side routing only."
                ),
                None,
                True,
                (GOPRO_GPMF_TABLE_SOURCE, GOPRO_PROCESS_SOURCE),
            )
        )
    gates.extend(non_mutating_gates())
    responsibilities = default_responsibilities()
    metadata_entries = tuple(
        entry
        for record in flatten_records(records)
        for entry in metadata_entries_for_record(record)
    )
    sources = unique_evidence_anchors(
        (
            *(source for record in flatten_records(records) for source in record.evidence_anchors),
            *(source for entry in metadata_entries for source in entry.evidence_anchors),
            *(source for gate in gates for source in gate.evidence_anchors),
            *(source for item in responsibilities for source in item.evidence_anchors),
            GOPRO_GP6_SOURCE,
        )
    )
    return GoproMetadataTransactionPlan(
        container_kind=container_kind,
        group0=group0,
        records=records,
        metadata_entries=metadata_entries,
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        rewrite_requests=rewrite_requests,
        evidence_anchors=sources,
    )


def parse_gpmf_records(
    data: bytes,
    start: int,
    end: int,
    parent_path: tuple[str, ...],
    group0: str,
    *,
    include_hidden_sample_fields: bool = False,
) -> tuple[tuple[GoproRecordPlan, ...], tuple[GoproEmissionGate, ...]]:
    records: list[GoproRecordPlan] = []
    gates: list[GoproEmissionGate] = []
    offset = start
    active_type: str | None = None
    active_scale: tuple[float, ...] = ()
    while offset < end:
        if offset + 8 > end:
            gates.append(
                GoproEmissionGate(
                    "truncated_gpmf_record_header",
                    f"GPMF record header at offset {offset} exceeds container end {end}.",
                    offset,
                    True,
                    (GOPRO_PROCESS_SOURCE,),
                )
            )
            break
        tag_bytes = data[offset : offset + 4]
        if tag_bytes == b"\x00\x00\x00\x00":
            break
        if not TAG_ID_RE.match(tag_bytes):
            gates.append(
                GoproEmissionGate(
                    "unrecognized_gopro_record",
                    f"Record id at offset {offset} is outside GoPro.pm's accepted tag syntax.",
                    offset,
                    True,
                    (GOPRO_PROCESS_SOURCE,),
                )
            )
            break
        tag_key = tag_bytes.decode("latin-1")
        format_code = data[offset + 4]
        element_size = data[offset + 5]
        element_count = int.from_bytes(data[offset + 6 : offset + 8], "big")
        payload_size = element_size * element_count
        payload_offset = offset + 8
        payload_end = payload_offset + payload_size
        padded_end = payload_offset + padded_size(payload_size)
        if payload_end > end:
            gates.append(
                GoproEmissionGate(
                    "truncated_gopro_record",
                    (
                        f"GPMF record {tag_key} payload ends at {payload_end}, "
                        f"past container end {end}."
                    ),
                    offset,
                    True,
                    (GOPRO_PROCESS_SOURCE,),
                )
            )
            break
        raw_payload = data[payload_offset:payload_end]
        path = (*parent_path, f"{tag_key}[{count_prior_tags(records, tag_key)}]")
        role = role_for_tag(tag_key)
        format_name = FORMAT_NAMES.get(format_code, "undef")
        decoded_value, decode_gates = decode_record_value(
            raw_payload,
            format_code,
            element_size,
            element_count,
            active_type,
            offset,
        )
        gates.extend(decode_gates)
        if active_scale and tag_key != "SCAL" and payload_end + 3 >= end:
            decoded_value = scale_value(decoded_value, active_scale)
        if tag_key == "TYPE":
            active_type = type_state(decoded_value)
        if tag_key in ("UNIT", "SIUN"):
            pass
        if tag_key == "SCAL":
            active_scale = scale_state(decoded_value)
        child_records: tuple[GoproRecordPlan, ...] = ()
        if format_code == 0x00 and payload_size:
            child_records, child_gates = parse_gpmf_records(
                data,
                payload_offset,
                payload_end,
                path,
                group0,
                include_hidden_sample_fields=include_hidden_sample_fields,
            )
            gates.extend(child_gates)
        sample_fields = sample_fields_for(
            tag_key,
            decoded_value,
            include_hidden=include_hidden_sample_fields,
        )
        sources = sources_for_tag(tag_key, format_code, sample_fields)
        records.append(
            GoproRecordPlan(
                tag_key=tag_key,
                tag_name=GPMF_TAG_NAMES.get(tag_key, f"GoPro_{tag_key.strip()}"),
                role=role,
                path=path,
                group0=group0,
                format_code=format_code,
                format_name=format_name,
                element_size=element_size,
                element_count=element_count,
                payload_size=payload_size,
                header_range=(offset, offset + 8),
                payload_range=(payload_offset, payload_end),
                raw_record_range=(offset, min(padded_end, end)),
                raw_payload=raw_payload,
                decoded_value=decoded_value,
                sample_fields=sample_fields,
                child_records=child_records,
                is_known=tag_key in GPMF_TAG_NAMES,
                evidence_anchors=sources,
            )
        )
        offset = padded_end
    return tuple(records), tuple(gates)


def decode_record_value(
    payload: bytes,
    format_code: int,
    element_size: int,
    element_count: int,
    active_type: str | None,
    record_offset: int,
) -> tuple[GoproDecodedValue | None, tuple[GoproEmissionGate, ...]]:
    format_name = FORMAT_NAMES.get(format_code, "undef")
    if format_name == "container":
        return None, ()
    if not payload:
        return None, ()
    if format_name == "structure":
        if active_type is None:
            return payload, (
                GoproEmissionGate(
                    "malformed_gopro_structure",
                    "GPMF structure payload has no preceding TYPE record.",
                    record_offset,
                    True,
                    (GOPRO_PROCESS_SOURCE,),
                ),
            )
        return decode_structure(payload, element_size, element_count, active_type, record_offset)
    if format_name == "string":
        if element_count > 1 and element_size > 1:
            return tuple(
                decode_text(payload[index : index + element_size])
                for index in range(0, len(payload), element_size)
            ), ()
        return decode_text(payload), ()
    if format_name == "fourcc":
        if element_count > 1 and element_size > 1:
            return tuple(
                payload[index : index + element_size] for index in range(0, len(payload), 4)
            ), ()
        return decode_text(payload), ()
    if format_name in ("uuid", "date16", "undef"):
        if element_count > 1 and element_size > 1:
            return tuple(
                payload[index : index + element_size]
                for index in range(0, len(payload), element_size)
            ), ()
        return payload, ()
    return decode_numeric_payload(payload, format_code)


def decode_structure(
    payload: bytes,
    row_size: int,
    row_count: int,
    active_type: str,
    record_offset: int,
) -> tuple[GoproDecodedValue | None, tuple[GoproEmissionGate, ...]]:
    rows: list[tuple[GoproScalar, ...]] = []
    gates: list[GoproEmissionGate] = []
    type_codes = active_type.encode("latin-1")
    for row_index in range(row_count):
        row_start = row_index * row_size
        cursor = row_start
        values: list[GoproScalar] = []
        for code in type_codes:
            size = FORMAT_SIZES.get(code)
            if size is None or cursor + size > row_start + row_size or cursor + size > len(payload):
                gates.append(
                    GoproEmissionGate(
                        "malformed_gopro_structure",
                        (
                            f"GPMF structure row {row_index} cannot satisfy TYPE "
                            f"{active_type!r} within element size {row_size}."
                        ),
                        record_offset,
                        True,
                        (GOPRO_PROCESS_SOURCE, GOPRO_FORMAT_SOURCE),
                    )
                )
                break
            values.append(decode_struct_item(payload[cursor : cursor + size], code))
            cursor += size
        if values:
            rows.append(tuple(values))
    if not rows:
        return None, tuple(gates)
    if len(rows) == 1:
        return rows[0], tuple(gates)
    return tuple(rows), tuple(gates)


def decode_numeric_payload(
    payload: bytes,
    format_code: int,
) -> tuple[GoproDecodedValue, tuple[GoproEmissionGate, ...]]:
    size = FORMAT_SIZES[format_code]
    values = tuple(
        decode_struct_item(payload[index : index + size], format_code)
        for index in range(0, len(payload), size)
        if index + size <= len(payload)
    )
    if len(values) == 1:
        return values[0], ()
    return values, ()


def decode_struct_item(payload: bytes, format_code: int) -> GoproScalar:
    if format_code in (0x46, 0x63):
        return decode_text(payload)
    if format_code in (0x47, 0x55):
        return payload
    if format_code == 0x62:
        return int.from_bytes(payload, "big", signed=True)
    if format_code == 0x42:
        return int.from_bytes(payload, "big")
    if format_code == 0x73:
        return int.from_bytes(payload, "big", signed=True)
    if format_code == 0x53:
        return int.from_bytes(payload, "big")
    if format_code == 0x6C:
        return int.from_bytes(payload, "big", signed=True)
    if format_code == 0x4C:
        return int.from_bytes(payload, "big")
    if format_code == 0x6A:
        return int.from_bytes(payload, "big", signed=True)
    if format_code == 0x4A:
        return int.from_bytes(payload, "big")
    if format_code == 0x71:
        value = int.from_bytes(payload, "big", signed=True)
        return value / 65536
    if format_code == 0x51:
        value = int.from_bytes(payload, "big", signed=True)
        return value / 4294967296
    if format_code == 0x66:
        return float(struct.unpack(">f", payload)[0])
    if format_code == 0x64:
        return float(struct.unpack(">d", payload)[0])
    return payload


def sample_fields_for(
    tag_key: str,
    decoded_value: GoproDecodedValue | None,
    *,
    include_hidden: bool = False,
) -> tuple[GoproSampleFieldPlan, ...]:
    field_names = SAMPLE_FIELDS.get(tag_key)
    if field_names is None or decoded_value is None:
        return ()
    rows = rows_for_sample(decoded_value, len(field_names))
    source = SAMPLE_SOURCES[tag_key]
    fields: list[GoproSampleFieldPlan] = []
    for sample_index, row in enumerate(rows):
        row_values = {
            field_names[index]: value for index, value in enumerate(row) if index < len(field_names)
        }
        for field_index, value in enumerate(row):
            if field_index < len(field_names):
                tag_name = field_names[field_index]
                if not include_hidden and tag_name in HIDDEN_SAMPLE_FIELDS.get(
                    tag_key,
                    frozenset(),
                ):
                    continue
                fields.append(
                    GoproSampleFieldPlan(
                        sample_index=sample_index,
                        field_index=field_index,
                        tag_name=tag_name,
                        value=sample_field_value(tag_key, tag_name, value, row_values),
                        evidence_anchors=(source, GOPRO_PROCESS_STRING_SOURCE),
                    )
                )
    return tuple(fields)


def sample_field_value(
    tag_key: str,
    tag_name: str,
    value: GoproScalar,
    row_values: dict[str, GoproScalar],
) -> GoproScalar:
    if tag_key in {"GPS5", "GPS9"} and tag_name in {"GPSSpeed", "GPSSpeed3D"}:
        if isinstance(value, (int, float)):
            return value * 3.6
    if tag_key == "GPS9" and tag_name == "GPSDateTime":
        days = row_values.get("GPSDays")
        if isinstance(days, (int, float)) and isinstance(value, (int, float)):
            return gopro_gps9_datetime(days, value)
    if tag_key == "GPS9" and tag_name == "GPSMeasureMode":
        if value == 2:
            return "2-Dimensional Measurement"
        if value == 3:
            return "3-Dimensional Measurement"
    return value


def gopro_gps9_datetime(days_since_2000: int | float, seconds: int | float) -> str:
    base = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(days=float(days_since_2000))
    timestamp = base + timedelta(seconds=float(seconds))
    whole = timestamp.strftime("%Y:%m:%d %H:%M:%S")
    milliseconds = timestamp.microsecond // 1000
    if milliseconds:
        return f"{whole}.{milliseconds:03d}"
    return whole


def rows_for_sample(
    decoded_value: GoproDecodedValue,
    width: int,
) -> tuple[tuple[GoproScalar, ...], ...]:
    if isinstance(decoded_value, tuple):
        if not decoded_value:
            return ()
        rows: list[tuple[GoproScalar, ...]] = []
        scalars: list[GoproScalar] = []
        for item in decoded_value:
            if isinstance(item, tuple):
                rows.append(item)
            else:
                scalars.append(item)
        if rows:
            return tuple(rows)
        return tuple(
            tuple(scalars[index : index + width]) for index in range(0, len(scalars), width)
        )
    return ((decoded_value,),)


def metadata_entries_for_record(record: GoproRecordPlan) -> tuple[GoproMetadataEntryPlan, ...]:
    if record.role in ("device_container", "stream_container", "preserved_unknown"):
        return ()
    entries = [
        GoproMetadataEntryPlan(
            tag_key=record.tag_key,
            tag_name=record.tag_name,
            path=record.path,
            group0=record.group0,
            role=record.role,
            value=record.decoded_value,
            raw_payload=record.raw_payload,
            evidence_anchors=record.evidence_anchors,
        )
    ]
    for field in record.sample_fields:
        entries.append(
            GoproMetadataEntryPlan(
                tag_key=record.tag_key,
                tag_name=field.tag_name,
                path=(*record.path, f"{field.tag_name}[{field.sample_index}]"),
                group0=record.group0,
                role=record.role,
                value=field.value,
                raw_payload=record.raw_payload,
                evidence_anchors=field.evidence_anchors,
            )
        )
    return tuple(entries)


def role_for_tag(tag_key: str) -> GoproRecordRole:
    if tag_key == "DEVC":
        return "device_container"
    if tag_key == "STRM":
        return "stream_container"
    if tag_key in SAMPLE_FIELDS or tag_key in ("ACCL", "GYRO", "GRAV", "MAGN", "SIMU"):
        return "telemetry_sample"
    if tag_key in STREAM_CONFIGURATION_TAGS:
        return "stream_configuration"
    if tag_key in GPS_TAGS:
        return "gps_metadata"
    if tag_key in IMU_TAGS:
        return "imu_metadata"
    if tag_key in IMAGE_SENSOR_TAGS:
        return "image_sensor_metadata"
    if tag_key in TIME_TAGS:
        return "time_metadata"
    if tag_key not in GPMF_TAG_NAMES:
        return "preserved_unknown"
    return "camera_metadata"


def sources_for_tag(
    tag_key: str,
    format_code: int,
    sample_fields: tuple[GoproSampleFieldPlan, ...],
) -> tuple[EvidenceAnchor, ...]:
    sources: list[EvidenceAnchor] = [GOPRO_PROCESS_SOURCE, GOPRO_FORMAT_SOURCE]
    if tag_key in GPMF_TAG_NAMES:
        sources.append(GOPRO_GPMF_TABLE_SOURCE)
    if format_code == 0x00:
        sources.append(GOPRO_PROCESS_SOURCE)
    if tag_key in SAMPLE_SOURCES:
        sources.extend((SAMPLE_SOURCES[tag_key], GOPRO_PROCESS_STRING_SOURCE))
    for field in sample_fields:
        sources.extend(field.evidence_anchors)
    return unique_evidence_anchors(tuple(sources))


def default_responsibilities() -> tuple[GoproPlanningResponsibility, ...]:
    return (
        GoproPlanningResponsibility(
            "gpmf_record_header_decoding",
            "Decode tag, format, element size, count, payload, and 4-byte padding boundaries.",
            (GOPRO_PROCESS_SOURCE, GOPRO_FORMAT_SOURCE),
        ),
        GoproPlanningResponsibility(
            "quicktime_and_app6_group_routing",
            "Assign QuickTime for MP4 GPMF/gpmd inputs and APP6 for JPEG APP6 inputs.",
            (GOPRO_PROCESS_SOURCE,),
        ),
        GoproPlanningResponsibility(
            "device_container_recursion",
            "Treat DEVC as the device-level recursive GPMF container.",
            (GOPRO_GPMF_TABLE_SOURCE, GOPRO_PROCESS_SOURCE),
        ),
        GoproPlanningResponsibility(
            "stream_container_recursion",
            "Treat STRM as nested signal stream recursion within a device.",
            (GOPRO_GPMF_TABLE_SOURCE, GOPRO_PROCESS_SOURCE),
        ),
        GoproPlanningResponsibility(
            "stream_configuration_state",
            "Track TYPE, UNIT/SIUN, and SCAL state for subsequent sample decoding.",
            (GOPRO_PROCESS_SOURCE,),
        ),
        GoproPlanningResponsibility(
            "telemetry_sample_field_routing",
            "Route indexed ProcessString sample values to GPS, Karma GPS, and battery field tags.",
            (
                GOPRO_PROCESS_STRING_SOURCE,
                GOPRO_GPS5_SOURCE,
                GOPRO_GPS9_SOURCE,
                GOPRO_GPRI_SOURCE,
                GOPRO_GLPI_SOURCE,
                GOPRO_KBAT_SOURCE,
            ),
        ),
        GoproPlanningResponsibility(
            "gps_tag_surface",
            "Expose GPS5, GPS9, GPRI, GLPI, GPS status, and GPS timing tags from GoPro.pm.",
            (GOPRO_GPMF_TABLE_SOURCE, GOPRO_GPS5_SOURCE, GOPRO_GPS9_SOURCE),
        ),
        GoproPlanningResponsibility(
            "imu_tag_surface",
            "Expose accelerometer, gyroscope, gravity, magnetometer, and related IMU payload tags.",
            (GOPRO_GPMF_TABLE_SOURCE,),
        ),
        GoproPlanningResponsibility(
            "camera_tag_surface",
            "Expose camera model, firmware, serial, video, exposure, color, and sensor tags.",
            (GOPRO_GPMF_TABLE_SOURCE,),
        ),
        GoproPlanningResponsibility(
            "unknown_key_preservation",
            "Preserve raw payload and byte ranges for unrecognized but syntactically valid keys.",
            (GOPRO_PROCESS_SOURCE,),
        ),
        GoproPlanningResponsibility(
            "malformed_and_truncation_blockers",
            (
                "Gate output when headers, payload bounds, tag syntax, or TYPE "
                "structures are malformed."
            ),
            (GOPRO_PROCESS_SOURCE,),
        ),
        GoproPlanningResponsibility(
            "non_mutating_rewrite_gates",
            (
                "Surface rewrite requests but keep byte emission blocked until a "
                "source-backed writer exists."
            ),
            (GOPRO_GPMF_TABLE_SOURCE, GOPRO_PROCESS_SOURCE),
        ),
    )


def non_mutating_gates() -> tuple[GoproEmissionGate, ...]:
    return (
        GoproEmissionGate(
            "raw_payload_preservation_required",
            (
                "GoPro transaction planning preserves raw GPMF payloads and byte "
                "ranges before any writer."
            ),
            None,
            True,
            (GOPRO_PROCESS_SOURCE,),
        ),
        GoproEmissionGate(
            "planner_is_non_mutating",
            "GoPro metadata transaction plans record extraction and routing decisions only.",
            None,
            True,
            (GOPRO_PROCESS_SOURCE,),
        ),
        GoproEmissionGate(
            "gopro_writer_not_implemented",
            (
                "GoPro.pm is read-side metadata processing; this slice has no "
                "source-backed GPMF writer."
            ),
            None,
            True,
            (GOPRO_GPMF_TABLE_SOURCE, GOPRO_PROCESS_SOURCE),
        ),
    )


def count_prior_tags(records: list[GoproRecordPlan], tag_key: str) -> int:
    return sum(1 for record in records if record.tag_key == tag_key)


def padded_size(size: int) -> int:
    return (size + 3) & 0xFFFFFFFC


def decode_text(payload: bytes) -> str:
    return payload.decode("latin-1").rstrip("\x00 ")


def type_state(value: GoproDecodedValue | None) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return decode_text(value)
    return None


def scale_state(value: GoproDecodedValue | None) -> tuple[float, ...]:
    values = scalar_sequence(value)
    scales: list[float] = []
    for item in values:
        if isinstance(item, (int, float)):
            scales.append(float(item))
        elif isinstance(item, str):
            for part in item.replace(",", " ").split():
                scales.append(float(part))
    return tuple(scale for scale in scales if scale != 0)


def scale_value(
    value: GoproDecodedValue | None,
    scales: tuple[float, ...],
) -> GoproDecodedValue | None:
    if value is None or not scales:
        return value
    if isinstance(value, tuple):
        if not value:
            return value
        rows: list[tuple[GoproScalar, ...]] = []
        scalars: list[GoproScalar] = []
        for item in value:
            if isinstance(item, tuple):
                rows.append(
                    tuple(
                        scale_scalar(child, scales[index % len(scales)])
                        for index, child in enumerate(item)
                    )
                )
            else:
                scalars.append(scale_scalar(item, scales[len(scalars) % len(scales)]))
        if rows:
            return tuple(rows)
        return tuple(scalars)
    return scale_scalar(value, scales[0])


def scale_scalar(value: GoproScalar, scale: float) -> GoproScalar:
    if isinstance(value, (int, float)):
        return value / scale
    return value


def scalar_sequence(value: GoproDecodedValue | None) -> tuple[GoproScalar, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        if not value:
            return ()
        scalars: list[GoproScalar] = []
        for item in value:
            if isinstance(item, tuple):
                scalars.extend(item)
            else:
                scalars.append(item)
        return tuple(scalars)
    return (value,)


def flatten_records(records: tuple[GoproRecordPlan, ...]) -> tuple[GoproRecordPlan, ...]:
    flattened: list[GoproRecordPlan] = []
    for record in records:
        flattened.append(record)
        flattened.extend(flatten_records(record.child_records))
    return tuple(flattened)


def unique_evidence_anchors(sources: tuple[EvidenceAnchor, ...]) -> tuple[EvidenceAnchor, ...]:
    unique: list[EvidenceAnchor] = []
    for source in sources:
        if source not in unique:
            unique.append(source)
    return tuple(unique)


def unique_gates(gates: tuple[GoproEmissionGate, ...]) -> tuple[GoproEmissionGate, ...]:
    unique: list[GoproEmissionGate] = []
    seen: set[tuple[GoproEmissionGateCode, int | None, str]] = set()
    for gate in gates:
        key = (gate.code, gate.offset, gate.reason)
        if key not in seen:
            unique.append(gate)
            seen.add(key)
    return tuple(unique)


def range_to_json(value: tuple[int, int]) -> JsonArray:
    return [value[0], value[1]]


def scalar_to_json(value: GoproScalar) -> JsonValue:
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    return value


def decoded_to_json(value: GoproDecodedValue | None) -> JsonValue:
    if value is None:
        return None
    if isinstance(value, tuple):
        return [decoded_to_json(item) for item in value]
    return scalar_to_json(value)


def evidence_anchors_to_json(sources: tuple[EvidenceAnchor, ...]) -> JsonArray:
    return [
        {
            "evidence": source.evidence,
            "line_end": source.line_end,
            "line_start": source.line_start,
            "path": source.path,
            "symbol": source.symbol,
        }
        for source in sources
    ]
