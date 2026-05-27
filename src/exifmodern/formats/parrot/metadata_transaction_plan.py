"""Source-grounded, non-mutating Parrot timed metadata transaction planning."""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

PARROT_PM_SOURCE_PATH = "lib/Image/ExifTool/Parrot.pm"
PARROT_PI = 3.14159

type ParrotPlanStatus = Literal["planned", "unsupported"]
type ParrotRouteKind = Literal["mett_record", "arcore_record", "unknown_payload"]
type ParrotResponsibilityKind = Literal[
    "gps_metadata",
    "flight_metadata",
    "camera_metadata",
    "attitude_metadata",
    "sensor_metadata",
    "device_metadata",
    "time_metadata",
    "image_metadata",
    "automation_metadata",
    "unknown_payload",
]
type ParrotScalarValue = int | float | bytes | tuple[int, ...] | tuple[float, ...]
type ParrotFormatName = Literal[
    "uint8",
    "int8s",
    "int16s",
    "int16u",
    "int16s[4]",
    "int16u[2]",
    "int32s",
    "int32u",
    "int64u",
    "undef[14]",
    "undef[16]",
]
type ParrotValueTransform = Literal[
    "none",
    "divide_256",
    "divide_16384",
    "divide_256000",
    "divide_1000",
    "divide_65536",
    "divide_1048576",
    "divide_4194304",
    "radians_4096_to_degrees",
    "vector_divide_4096",
    "vector_divide_16384",
    "fov_divide_256",
    "arcore_vector",
    "arcore_unknown_markers",
]
type ParrotRewriteOperation = Literal["replace", "insert", "delete"]
type ParrotActionKind = Literal[
    "route_record",
    "route_tag",
    "preserve_payload",
    "preserve_unknown_tag",
    "block_requested_rewrite",
    "route_source_backed_rewrite",
    "no_metadata_mutation",
]
type ParrotBlockerCode = Literal[
    "invalid_dir_start",
    "malformed_mett_record",
    "truncated_mett_record",
    "malformed_arcore_record",
    "truncated_arcore_record",
]
type ParrotEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "invalid_dir_start",
    "malformed_mett_record",
    "truncated_mett_record",
    "malformed_arcore_record",
    "truncated_arcore_record",
    "unsupported_rewrite_requested",
    "source_backed_rewrite_requires_downstream_writer",
]

METT_ID_RE = re.compile(r"^[EP]\d$")

METT_TABLE_SOURCE = "mett.table"
V1_SOURCE = "v1"
V2_SOURCE = "v2"
V3_SOURCE = "v3"
TIMESTAMP_SOURCE = "timestamp"
FOLLOW_ME_SOURCE = "follow.me"
AUTOMATION_SOURCE = "automation"
ARCORE_SOURCE = "arcore"
PROCESS_METT_SOURCE = "process.mett"

PARROT_TRANSACTION_SOURCES = (
    METT_TABLE_SOURCE,
    V1_SOURCE,
    V2_SOURCE,
    V3_SOURCE,
    TIMESTAMP_SOURCE,
    FOLLOW_ME_SOURCE,
    AUTOMATION_SOURCE,
    ARCORE_SOURCE,
    PROCESS_METT_SOURCE,
)


@dataclass(frozen=True)
class ParrotTagDefinition:
    key: str
    offset: int
    tag_name: str
    format_name: ParrotFormatName
    responsibility: ParrotResponsibilityKind
    transform: ParrotValueTransform = "none"
    mask: int | None = None
    unknown: bool = False


@dataclass(frozen=True)
class ParrotPayloadInput:
    route_kind: ParrotRouteKind
    payload: bytes
    byte_range: tuple[int, int] | None = None
    label: str | None = None


@dataclass(frozen=True)
class ParrotRewriteRequest:
    target: str
    operation: ParrotRewriteOperation
    tag_name: str | None = None
    payload: bytes | None = None


@dataclass(frozen=True)
class ParrotRecordPlan:
    record_id: str
    route_kind: ParrotRouteKind
    table_name: str
    known: bool
    byte_range: tuple[int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParrotTagRoutePlan:
    record_id: str
    table_name: str
    source_key: str
    tag_name: str
    responsibility: ParrotResponsibilityKind
    value: ParrotScalarValue
    byte_range: tuple[int, int]
    unknown: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParrotPreservedPayloadPlan:
    route_kind: ParrotRouteKind
    payload: bytes
    byte_range: tuple[int, int] | None
    label: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParrotActionPlan:
    kind: ParrotActionKind
    route_kind: ParrotRouteKind
    record_id: str | None
    tag_name: str | None
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParrotTransactionBlocker:
    code: ParrotBlockerCode
    route_kind: ParrotRouteKind
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParrotOutputEmissionGate:
    code: ParrotEmissionGateCode
    route_kind: ParrotRouteKind | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParrotMetadataTransactionPlan:
    status: ParrotPlanStatus
    records: tuple[ParrotRecordPlan, ...]
    tag_routes: tuple[ParrotTagRoutePlan, ...]
    preserved_payloads: tuple[ParrotPreservedPayloadPlan, ...]
    actions: tuple[ParrotActionPlan, ...]
    blockers: tuple[ParrotTransactionBlocker, ...]
    output_emission_gates: tuple[ParrotOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes
    rewrite_requests: tuple[ParrotRewriteRequest, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Parrot metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def responsibilities(self, kind: ParrotResponsibilityKind) -> tuple[str, ...]:
        return tuple(route.tag_name for route in self.tag_routes if route.responsibility == kind)


@dataclass(frozen=True)
class _ParseResult:
    records: tuple[ParrotRecordPlan, ...]
    tag_routes: tuple[ParrotTagRoutePlan, ...]
    preserved_payloads: tuple[ParrotPreservedPayloadPlan, ...]
    actions: tuple[ParrotActionPlan, ...]
    blockers: tuple[ParrotTransactionBlocker, ...]


P1_TAGS = (
    ParrotTagDefinition(
        "4", 4, "DroneYaw", "int16s", "attitude_metadata", "radians_4096_to_degrees"
    ),
    ParrotTagDefinition(
        "6", 6, "DronePitch", "int16s", "attitude_metadata", "radians_4096_to_degrees"
    ),
    ParrotTagDefinition(
        "8", 8, "DroneRoll", "int16s", "attitude_metadata", "radians_4096_to_degrees"
    ),
    ParrotTagDefinition(
        "10", 10, "CameraPan", "int16s", "camera_metadata", "radians_4096_to_degrees"
    ),
    ParrotTagDefinition(
        "12", 12, "CameraTilt", "int16s", "camera_metadata", "radians_4096_to_degrees"
    ),
    ParrotTagDefinition(
        "14", 14, "FrameView", "int16s[4]", "attitude_metadata", "vector_divide_4096"
    ),
    ParrotTagDefinition("22", 22, "ExposureTime", "int16s", "camera_metadata", "divide_256000"),
    ParrotTagDefinition("24", 24, "ISO", "int16s", "camera_metadata"),
    ParrotTagDefinition("26", 26, "WifiRSSI", "int8s", "device_metadata"),
    ParrotTagDefinition("27", 27, "Battery", "uint8", "device_metadata"),
    ParrotTagDefinition("28", 28, "GPSLatitude", "int32s", "gps_metadata", "divide_1048576"),
    ParrotTagDefinition("32", 32, "GPSLongitude", "int32s", "gps_metadata", "divide_1048576"),
    ParrotTagDefinition(
        "36", 36, "GPSAltitude", "int32s", "gps_metadata", "divide_256", 0xFFFFFF00
    ),
    ParrotTagDefinition("36.1", 36, "GPSSatellites", "int32s", "gps_metadata", "none", 0xFF),
    ParrotTagDefinition(
        "40", 40, "AltitudeFromTakeOff", "int32s", "flight_metadata", "divide_65536"
    ),
    ParrotTagDefinition("44", 44, "DistanceFromHome", "int32u", "flight_metadata", "divide_65536"),
    ParrotTagDefinition("48", 48, "SpeedX", "int16s", "flight_metadata", "divide_256"),
    ParrotTagDefinition("50", 50, "SpeedY", "int16s", "flight_metadata", "divide_256"),
    ParrotTagDefinition("52", 52, "SpeedZ", "int16s", "flight_metadata", "divide_256"),
    ParrotTagDefinition("54", 54, "Binning", "uint8", "device_metadata", "none", 0x80),
    ParrotTagDefinition("54.1", 54, "FlyingState", "uint8", "flight_metadata", "none", 0x7F),
    ParrotTagDefinition("55", 55, "Animation", "uint8", "flight_metadata", "none", 0x80),
    ParrotTagDefinition("55.1", 55, "PilotingMode", "uint8", "flight_metadata", "none", 0x7F),
)

P2_TAGS = (
    ParrotTagDefinition("4", 4, "Elevation", "int32s", "flight_metadata", "divide_65536"),
    ParrotTagDefinition("8", 8, "GPSLatitude", "int32s", "gps_metadata", "divide_4194304"),
    ParrotTagDefinition("12", 12, "GPSLongitude", "int32s", "gps_metadata", "divide_4194304"),
    ParrotTagDefinition(
        "16", 16, "GPSAltitude", "int32s", "gps_metadata", "divide_256", 0xFFFFFF00
    ),
    ParrotTagDefinition("16.1", 16, "GPSSatellites", "int32s", "gps_metadata", "none", 0xFF),
    ParrotTagDefinition("20", 20, "GPSVelocityNorth", "int16s", "gps_metadata", "divide_256"),
    ParrotTagDefinition("22", 22, "GPSVelocityEast", "int16s", "gps_metadata", "divide_256"),
    ParrotTagDefinition("24", 24, "GPSVelocityDown", "int16s", "gps_metadata", "divide_256"),
    ParrotTagDefinition("26", 26, "AirSpeed", "int16s", "flight_metadata", "divide_256"),
    ParrotTagDefinition(
        "28", 28, "DroneQuaternion", "int16s[4]", "attitude_metadata", "vector_divide_16384"
    ),
    ParrotTagDefinition(
        "36", 36, "FrameView", "int16s[4]", "attitude_metadata", "vector_divide_16384"
    ),
    ParrotTagDefinition(
        "44", 44, "CameraPan", "int16s", "camera_metadata", "radians_4096_to_degrees"
    ),
    ParrotTagDefinition(
        "46", 46, "CameraTilt", "int16s", "camera_metadata", "radians_4096_to_degrees"
    ),
    ParrotTagDefinition("48", 48, "ExposureTime", "int16u", "camera_metadata", "divide_256000"),
    ParrotTagDefinition("50", 50, "ISO", "int16u", "camera_metadata"),
    ParrotTagDefinition("52", 52, "Binning", "uint8", "device_metadata", "none", 0x80),
    ParrotTagDefinition("52.1", 52, "FlyingState", "uint8", "flight_metadata", "none", 0x7F),
    ParrotTagDefinition("53", 53, "Animation", "uint8", "flight_metadata", "none", 0x80),
    ParrotTagDefinition("53.1", 53, "PilotingMode", "uint8", "flight_metadata", "none", 0x7F),
    ParrotTagDefinition("54", 54, "WifiRSSI", "int8s", "device_metadata"),
    ParrotTagDefinition("55", 55, "Battery", "uint8", "device_metadata"),
)

P3_TAGS = (
    ParrotTagDefinition("4", 4, "Elevation", "int32s", "flight_metadata", "divide_65536"),
    ParrotTagDefinition("8", 8, "GPSLatitude", "int32s", "gps_metadata", "divide_4194304"),
    ParrotTagDefinition("12", 12, "GPSLongitude", "int32s", "gps_metadata", "divide_4194304"),
    ParrotTagDefinition(
        "16", 16, "GPSAltitude", "int32s", "gps_metadata", "divide_256", 0xFFFFFF00
    ),
    ParrotTagDefinition("16.1", 16, "GPSSatellites", "int32s", "gps_metadata", "none", 0xFF),
    ParrotTagDefinition("20", 20, "GPSVelocityNorth", "int16s", "gps_metadata", "divide_256"),
    ParrotTagDefinition("22", 22, "GPSVelocityEast", "int16s", "gps_metadata", "divide_256"),
    ParrotTagDefinition("24", 24, "GPSVelocityDown", "int16s", "gps_metadata", "divide_256"),
    ParrotTagDefinition("26", 26, "AirSpeed", "int16s", "flight_metadata", "divide_256"),
    ParrotTagDefinition(
        "28", 28, "DroneQuaternion", "int16s[4]", "attitude_metadata", "vector_divide_16384"
    ),
    ParrotTagDefinition(
        "36", 36, "FrameBaseView", "int16s[4]", "attitude_metadata", "vector_divide_16384"
    ),
    ParrotTagDefinition(
        "44", 44, "FrameView", "int16s[4]", "attitude_metadata", "vector_divide_16384"
    ),
    ParrotTagDefinition("52", 52, "ExposureTime", "int16u", "camera_metadata", "divide_256000"),
    ParrotTagDefinition("54", 54, "ISO", "int16u", "camera_metadata"),
    ParrotTagDefinition("56", 56, "RedBalance", "int16u", "camera_metadata", "divide_16384"),
    ParrotTagDefinition("58", 58, "BlueBalance", "int16u", "camera_metadata", "divide_16384"),
    ParrotTagDefinition("60", 60, "FOV", "int16u[2]", "image_metadata", "fov_divide_256"),
    ParrotTagDefinition("64", 64, "LinkGoodput", "int32u", "device_metadata", "none", 0xFFFFFF00),
    ParrotTagDefinition("64.1", 64, "LinkQuality", "int32u", "device_metadata", "none", 0xFF),
    ParrotTagDefinition("68", 68, "WifiRSSI", "int8s", "device_metadata"),
    ParrotTagDefinition("69", 69, "Battery", "uint8", "device_metadata"),
    ParrotTagDefinition("70", 70, "Binning", "uint8", "device_metadata", "none", 0x80),
    ParrotTagDefinition("70.1", 70, "FlyingState", "uint8", "flight_metadata", "none", 0x7F),
    ParrotTagDefinition("71", 71, "Animation", "uint8", "flight_metadata", "none", 0x80),
    ParrotTagDefinition("71.1", 71, "PilotingMode", "uint8", "flight_metadata", "none", 0x7F),
)

E1_TAGS = (ParrotTagDefinition("4", 4, "TimeStamp", "int64u", "time_metadata", "divide_1000"),)
E2_TAGS = (
    ParrotTagDefinition("4", 4, "GPSTargetLatitude", "int32s", "gps_metadata", "divide_4194304"),
    ParrotTagDefinition("8", 8, "GPSTargetLongitude", "int32s", "gps_metadata", "divide_4194304"),
    ParrotTagDefinition("12", 12, "GPSTargetAltitude", "int32s", "gps_metadata", "divide_65536"),
    ParrotTagDefinition("16", 16, "Follow-meMode", "uint8", "automation_metadata"),
    ParrotTagDefinition("17", 17, "Follow-meAnimation", "uint8", "automation_metadata"),
)
E3_TAGS = (
    ParrotTagDefinition("4", 4, "GPSFramingLatitude", "int32s", "gps_metadata", "divide_4194304"),
    ParrotTagDefinition("8", 8, "GPSFramingLongitude", "int32s", "gps_metadata", "divide_4194304"),
    ParrotTagDefinition("12", 12, "GPSFramingAltitude", "int32s", "gps_metadata", "divide_65536"),
    ParrotTagDefinition("16", 16, "GPSDestLatitude", "int32s", "gps_metadata", "divide_4194304"),
    ParrotTagDefinition("20", 20, "GPSDestLongitude", "int32s", "gps_metadata", "divide_4194304"),
    ParrotTagDefinition("24", 24, "GPSDestAltitude", "int32s", "gps_metadata", "divide_65536"),
    ParrotTagDefinition("28", 28, "AutomationAnimation", "uint8", "automation_metadata"),
    ParrotTagDefinition("29", 29, "AutomationFlags", "uint8", "automation_metadata"),
)
ARCORE_ACCEL_TAGS = (
    ParrotTagDefinition(
        "4",
        4,
        "AccelerometerUnknown",
        "undef[16]",
        "unknown_payload",
        "arcore_unknown_markers",
        unknown=True,
    ),
    ParrotTagDefinition("5", 5, "Accelerometer", "undef[14]", "sensor_metadata", "arcore_vector"),
)
ARCORE_ACCEL0_TAGS = (
    ParrotTagDefinition("9", 9, "Accelerometer", "undef[14]", "sensor_metadata", "arcore_vector"),
)
ARCORE_GYRO_TAGS = (
    ParrotTagDefinition(
        "4",
        4,
        "GyroscopeUnknown",
        "undef[16]",
        "unknown_payload",
        "arcore_unknown_markers",
        unknown=True,
    ),
    ParrotTagDefinition("5", 5, "Gyroscope", "undef[14]", "sensor_metadata", "arcore_vector"),
)
ARCORE_GYRO0_TAGS = (
    ParrotTagDefinition("9", 9, "Gyroscope", "undef[14]", "sensor_metadata", "arcore_vector"),
)

TAG_TABLES: dict[str, tuple[ParrotTagDefinition, ...]] = {
    "P1": P1_TAGS,
    "P2": P2_TAGS,
    "P3": P3_TAGS,
    "E1": E1_TAGS,
    "E2": E2_TAGS,
    "E3": E3_TAGS,
    "application/arcore-accel": ARCORE_ACCEL_TAGS,
    "application/arcore-accel-0": ARCORE_ACCEL0_TAGS,
    "application/arcore-gyro": ARCORE_GYRO_TAGS,
    "application/arcore-gyro-0": ARCORE_GYRO0_TAGS,
}

TABLE_SOURCES: dict[str, str] = {
    "P1": V1_SOURCE,
    "P2": V2_SOURCE,
    "P3": V3_SOURCE,
    "E1": TIMESTAMP_SOURCE,
    "E2": FOLLOW_ME_SOURCE,
    "E3": AUTOMATION_SOURCE,
    "application/arcore-accel": ARCORE_SOURCE,
    "application/arcore-accel-0": ARCORE_SOURCE,
    "application/arcore-gyro": ARCORE_SOURCE,
    "application/arcore-gyro-0": ARCORE_SOURCE,
}
ARCORE_META_TYPES = frozenset(
    {
        "application/arcore-accel",
        "application/arcore-accel-0",
        "application/arcore-gyro",
        "application/arcore-gyro-0",
        "application/arcore-video-0",
        "application/arcore-custom-event",
    }
)
ARCORE_EMPTY_TABLES = frozenset({"application/arcore-video-0", "application/arcore-custom-event"})
SOURCE_BACKED_TARGETS = frozenset(TAG_TABLES)


def build_parrot_metadata_transaction_plan(
    payload: bytes | None = None,
    *,
    source_bytes: bytes = b"",
    meta_type: str = "",
    dir_start: int = 0,
    unknown_payloads: Iterable[ParrotPayloadInput] = (),
    rewrite_requests: Iterable[ParrotRewriteRequest] = (),
    allow_output_emission: bool = False,
) -> ParrotMetadataTransactionPlan:
    data = source_bytes if payload is None else payload
    original_bytes = source_bytes or data
    rewrite_request_tuple = tuple(rewrite_requests)
    parse_result = parse_payload(data, meta_type, dir_start)
    preserved_payloads = [
        *parse_result.preserved_payloads,
        *plan_supplied_preserved_payloads(tuple(unknown_payloads)),
    ]
    actions = [
        *parse_result.actions,
        *preservation_actions(preserved_payloads),
    ]
    gates: list[ParrotOutputEmissionGate] = []
    gates.extend(gates_for_blockers(parse_result.blockers))
    rewrite_actions, rewrite_gates = plan_rewrite_gates(rewrite_request_tuple, original_bytes)
    actions.extend(rewrite_actions)
    gates.extend(rewrite_gates)
    if not allow_output_emission:
        gates.append(
            ParrotOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                None,
                "Parrot timed metadata planning is read-only until a caller opts into emission.",
                (PROCESS_METT_SOURCE,),
            )
        )
        actions.append(
            ParrotActionPlan(
                "no_metadata_mutation",
                "mett_record",
                None,
                None,
                None,
                "Default planning preserves input bytes and performs no mutation.",
                (PROCESS_METT_SOURCE,),
            )
        )
    status: ParrotPlanStatus = "unsupported" if parse_result.blockers else "planned"
    return ParrotMetadataTransactionPlan(
        status=status,
        records=parse_result.records,
        tag_routes=parse_result.tag_routes,
        preserved_payloads=tuple(preserved_payloads),
        actions=tuple(actions),
        blockers=parse_result.blockers,
        output_emission_gates=tuple(gates),
        evidence_ids=PARROT_TRANSACTION_SOURCES,
        original_bytes=original_bytes,
        rewrite_requests=rewrite_request_tuple,
    )


def parse_payload(data: bytes, meta_type: str, dir_start: int) -> _ParseResult:
    if dir_start < 0 or dir_start > len(data):
        blocker = ParrotTransactionBlocker(
            "invalid_dir_start",
            "mett_record",
            None,
            "DirStart must point inside the Parrot timed metadata payload.",
            (PROCESS_METT_SOURCE,),
        )
        return _ParseResult((), (), (), (), (blocker,))
    if meta_type in ARCORE_META_TYPES:
        return parse_arcore_payload(data, meta_type, dir_start)
    return parse_mett_payload(data, dir_start)


def parse_arcore_payload(data: bytes, meta_type: str, dir_start: int) -> _ParseResult:
    records: list[ParrotRecordPlan] = []
    routes: list[ParrotTagRoutePlan] = []
    preserved: list[ParrotPreservedPayloadPlan] = []
    actions: list[ParrotActionPlan] = []
    blockers: list[ParrotTransactionBlocker] = []
    pos = dir_start
    dir_end = len(data)
    while pos < dir_end - 2:
        if data[pos] != 0x0A:
            blockers.append(
                ParrotTransactionBlocker(
                    "malformed_arcore_record",
                    "arcore_record",
                    (pos, dir_end),
                    "ARCore Parrot timed metadata records must begin with byte 0x0a.",
                    (PROCESS_METT_SOURCE, ARCORE_SOURCE),
                )
            )
            preserved.append(
                preserved_payload("arcore_record", data[pos:dir_end], (pos, dir_end), "arcore-tail")
            )
            break
        length = data[pos + 1]
        if pos + length + 2 > dir_end:
            blockers.append(
                ParrotTransactionBlocker(
                    "truncated_arcore_record",
                    "arcore_record",
                    (pos, dir_end),
                    f"Unexpected length for {meta_type} record.",
                    (PROCESS_METT_SOURCE, ARCORE_SOURCE),
                )
            )
            preserved.append(
                preserved_payload("arcore_record", data[pos:dir_end], (pos, dir_end), meta_type)
            )
            break
        if length == 0:
            length = dir_end - pos - 2
        byte_range = (pos, pos + length + 2)
        known = meta_type in TAG_TABLES or meta_type in ARCORE_EMPTY_TABLES
        records.append(
            ParrotRecordPlan(
                meta_type,
                "arcore_record",
                meta_type,
                known,
                byte_range,
                (METT_TABLE_SOURCE, ARCORE_SOURCE),
            )
        )
        actions.append(
            route_record_action(
                "arcore_record", meta_type, byte_range, (METT_TABLE_SOURCE, ARCORE_SOURCE)
            )
        )
        if meta_type in TAG_TABLES:
            record_routes, record_preserved, record_actions = route_tags(
                meta_type, data, pos, length
            )
            routes.extend(record_routes)
            preserved.extend(record_preserved)
            actions.extend(record_actions)
        else:
            preserved.append(
                preserved_payload(
                    "arcore_record", data[pos : pos + length + 2], byte_range, meta_type
                )
            )
        pos += length + 2
    if pos < dir_end and not blockers:
        preserved.append(
            preserved_payload(
                "arcore_record", data[pos:dir_end], (pos, dir_end), "arcore-trailing-bytes"
            )
        )
    return _ParseResult(
        tuple(records), tuple(routes), tuple(preserved), tuple(actions), tuple(blockers)
    )


def parse_mett_payload(data: bytes, dir_start: int) -> _ParseResult:
    records: list[ParrotRecordPlan] = []
    routes: list[ParrotTagRoutePlan] = []
    preserved: list[ParrotPreservedPayloadPlan] = []
    actions: list[ParrotActionPlan] = []
    blockers: list[ParrotTransactionBlocker] = []
    pos = dir_start
    dir_end = len(data)
    while pos + 4 < dir_end:
        raw_id = data[pos : pos + 2].decode("latin-1")
        nwords = int.from_bytes(data[pos + 2 : pos + 4], "big")
        record_start = pos
        if not METT_ID_RE.match(raw_id):
            if dir_end == 60:
                record_id = "P1"
                record_start = pos + 4
                size = dir_end - record_start
            else:
                blockers.append(
                    ParrotTransactionBlocker(
                        "malformed_mett_record",
                        "mett_record",
                        (pos, dir_end),
                        (
                            "Parrot mett records need P/E IDs unless the payload is a "
                            "60-byte V1 sample."
                        ),
                        (PROCESS_METT_SOURCE,),
                    )
                )
                preserved.append(
                    preserved_payload(
                        "mett_record", data[pos:dir_end], (pos, dir_end), "malformed-mett"
                    )
                )
                break
        elif raw_id == "P2":
            record_id = raw_id
            size = 56
        elif raw_id == "P3":
            record_id = raw_id
            size = 72
        else:
            record_id = raw_id
            size = nwords * 4 + 4
        if record_start + size > dir_end:
            blockers.append(
                ParrotTransactionBlocker(
                    "truncated_mett_record",
                    "mett_record",
                    (pos, dir_end),
                    f"Parrot {record_id} record extends beyond the available payload.",
                    (PROCESS_METT_SOURCE,),
                )
            )
            preserved.append(
                preserved_payload("mett_record", data[pos:dir_end], (pos, dir_end), record_id)
            )
            break
        byte_range = (pos, record_start + size)
        known = record_id in TAG_TABLES
        source_refs = (METT_TABLE_SOURCE, table_source(record_id))
        records.append(
            ParrotRecordPlan(record_id, "mett_record", record_id, known, byte_range, source_refs)
        )
        actions.append(route_record_action("mett_record", record_id, byte_range, source_refs))
        if known:
            record_routes, record_preserved, record_actions = route_tags(
                record_id, data, record_start, size
            )
            routes.extend(record_routes)
            preserved.extend(record_preserved)
            actions.extend(record_actions)
        else:
            preserved.append(
                preserved_payload(
                    "unknown_payload", data[pos : record_start + size], byte_range, record_id
                )
            )
        pos = record_start + size
    if pos < dir_end and not blockers:
        preserved.append(
            preserved_payload("mett_record", data[pos:dir_end], (pos, dir_end), "trailing-bytes")
        )
    return _ParseResult(
        tuple(records), tuple(routes), tuple(preserved), tuple(actions), tuple(blockers)
    )


def route_tags(
    table_name: str,
    data: bytes,
    record_start: int,
    record_size: int,
) -> tuple[
    tuple[ParrotTagRoutePlan, ...],
    tuple[ParrotPreservedPayloadPlan, ...],
    tuple[ParrotActionPlan, ...],
]:
    routes: list[ParrotTagRoutePlan] = []
    preserved: list[ParrotPreservedPayloadPlan] = []
    actions: list[ParrotActionPlan] = []
    source_refs = (table_source(table_name),)
    for definition in TAG_TABLES[table_name]:
        absolute_offset = record_start + definition.offset
        field_size = format_size(definition.format_name)
        if absolute_offset + field_size > record_start + record_size:
            continue
        byte_range = (absolute_offset, absolute_offset + field_size)
        value = decode_value(data[absolute_offset : absolute_offset + field_size], definition)
        routes.append(
            ParrotTagRoutePlan(
                table_name,
                table_name,
                definition.key,
                definition.tag_name,
                definition.responsibility,
                value,
                byte_range,
                definition.unknown,
                source_refs,
            )
        )
        actions.append(
            ParrotActionPlan(
                "preserve_unknown_tag" if definition.unknown else "route_tag",
                "arcore_record" if table_name in ARCORE_META_TYPES else "mett_record",
                table_name,
                definition.tag_name,
                byte_range,
                "Unknown source-backed payload is preserved."
                if definition.unknown
                else "Source-backed tag routed from Parrot table.",
                source_refs,
            )
        )
        if definition.unknown:
            preserved.append(
                preserved_payload(
                    "unknown_payload",
                    data[absolute_offset : absolute_offset + field_size],
                    byte_range,
                    definition.tag_name,
                )
            )
    return tuple(routes), tuple(preserved), tuple(actions)


def decode_value(raw: bytes, definition: ParrotTagDefinition) -> ParrotScalarValue:
    value = decode_raw_value(raw, definition.format_name)
    if isinstance(value, int) and definition.mask is not None:
        value &= definition.mask
    return transform_value(value, definition.transform)


def decode_raw_value(raw: bytes, format_name: ParrotFormatName) -> ParrotScalarValue:
    if format_name == "uint8":
        return raw[0]
    if format_name == "int8s":
        return int.from_bytes(raw, "big", signed=True)
    if format_name == "int16s":
        return int.from_bytes(raw, "big", signed=True)
    if format_name == "int16u":
        return int.from_bytes(raw, "big")
    if format_name == "int32s":
        return int.from_bytes(raw, "big", signed=True)
    if format_name == "int32u":
        return int.from_bytes(raw, "big")
    if format_name == "int64u":
        return int.from_bytes(raw, "big")
    if format_name == "int16s[4]":
        return tuple(
            int.from_bytes(raw[index : index + 2], "big", signed=True) for index in range(0, 8, 2)
        )
    if format_name == "int16u[2]":
        return tuple(int.from_bytes(raw[index : index + 2], "big") for index in range(0, 4, 2))
    return raw


def transform_value(value: ParrotScalarValue, transform: ParrotValueTransform) -> ParrotScalarValue:
    if transform == "none":
        return value
    if transform == "divide_256" and isinstance(value, int):
        return value / 0x100
    if transform == "divide_16384" and isinstance(value, int):
        return value / 0x4000
    if transform == "divide_256000" and isinstance(value, int):
        return value / 0x100 / 1000
    if transform == "divide_1000" and isinstance(value, int):
        return value / 1_000_000
    if transform == "divide_65536" and isinstance(value, int):
        return value / 0x10000
    if transform == "divide_1048576" and isinstance(value, int):
        return value / 0x100000
    if transform == "divide_4194304" and isinstance(value, int):
        return value / 0x400000
    if transform == "radians_4096_to_degrees" and isinstance(value, int):
        return value / 0x1000 * 180 / PARROT_PI
    if transform == "vector_divide_4096" and isinstance(value, tuple):
        return tuple(item / 0x1000 for item in value)
    if transform == "vector_divide_16384" and isinstance(value, tuple):
        return tuple(item / 0x4000 for item in value)
    if transform == "fov_divide_256" and isinstance(value, tuple):
        return tuple(item / 0x100 for item in value)
    if transform == "arcore_vector" and isinstance(value, bytes):
        return (
            struct.unpack("<f", value[0:4])[0],
            struct.unpack("<f", value[5:9])[0],
            struct.unpack("<f", value[10:14])[0],
        )
    if transform == "arcore_unknown_markers" and isinstance(value, bytes):
        return (value[0], value[5], value[10], value[15])
    return value


def format_size(format_name: ParrotFormatName) -> int:
    if format_name in {"uint8", "int8s"}:
        return 1
    if format_name in {"int16s", "int16u"}:
        return 2
    if format_name in {"int32s", "int32u", "int16u[2]"}:
        return 4
    if format_name in {"int64u", "int16s[4]"}:
        return 8
    if format_name == "undef[14]":
        return 14
    return 16


def route_record_action(
    route_kind: ParrotRouteKind,
    record_id: str,
    byte_range: tuple[int, int],
    source_refs: tuple[str, ...],
) -> ParrotActionPlan:
    return ParrotActionPlan(
        "route_record",
        route_kind,
        record_id,
        None,
        byte_range,
        "Record routed using Parrot Process_mett table selection.",
        source_refs,
    )


def preserved_payload(
    route_kind: ParrotRouteKind,
    payload: bytes,
    byte_range: tuple[int, int] | None,
    label: str | None,
) -> ParrotPreservedPayloadPlan:
    return ParrotPreservedPayloadPlan(
        route_kind,
        payload,
        byte_range,
        label,
        (PROCESS_METT_SOURCE,),
    )


def plan_supplied_preserved_payloads(
    payloads: tuple[ParrotPayloadInput, ...],
) -> tuple[ParrotPreservedPayloadPlan, ...]:
    return tuple(
        ParrotPreservedPayloadPlan(
            payload.route_kind,
            payload.payload,
            payload.byte_range,
            payload.label,
            (PROCESS_METT_SOURCE,),
        )
        for payload in payloads
    )


def preservation_actions(
    payloads: list[ParrotPreservedPayloadPlan],
) -> tuple[ParrotActionPlan, ...]:
    return tuple(
        ParrotActionPlan(
            "preserve_payload",
            payload.route_kind,
            None,
            None,
            payload.byte_range,
            "Opaque Parrot metadata bytes are carried forward unchanged.",
            payload.evidence_ids,
        )
        for payload in payloads
    )


def gates_for_blockers(
    blockers: tuple[ParrotTransactionBlocker, ...],
) -> tuple[ParrotOutputEmissionGate, ...]:
    return tuple(
        ParrotOutputEmissionGate(
            blocker.code,
            blocker.route_kind,
            blocker.reason,
            blocker.evidence_ids,
        )
        for blocker in blockers
    )


def plan_rewrite_gates(
    rewrite_requests: tuple[ParrotRewriteRequest, ...],
    original_bytes: bytes,
) -> tuple[tuple[ParrotActionPlan, ...], tuple[ParrotOutputEmissionGate, ...]]:
    actions: list[ParrotActionPlan] = []
    gates: list[ParrotOutputEmissionGate] = []
    for request in rewrite_requests:
        if (
            request.target in SOURCE_BACKED_TARGETS
            and request.tag_name in table_tag_names(request.target)
            and original_bytes
        ):
            actions.append(
                ParrotActionPlan(
                    "route_source_backed_rewrite",
                    "mett_record" if request.target.startswith(("P", "E")) else "arcore_record",
                    request.target,
                    request.tag_name,
                    None,
                    "Rewrite request maps to a source-backed Parrot table but needs a writer.",
                    (table_source(request.target),),
                )
            )
            gates.append(
                ParrotOutputEmissionGate(
                    "source_backed_rewrite_requires_downstream_writer",
                    "mett_record" if request.target.startswith(("P", "E")) else "arcore_record",
                    (
                        "This planner identifies rewrite routing but does not mutate "
                        "Parrot timed metadata."
                    ),
                    (table_source(request.target), PROCESS_METT_SOURCE),
                )
            )
        else:
            actions.append(
                ParrotActionPlan(
                    "block_requested_rewrite",
                    "unknown_payload",
                    request.target,
                    request.tag_name,
                    None,
                    "Requested Parrot rewrite is not supported by this read-only planner.",
                    (PROCESS_METT_SOURCE,),
                )
            )
            gates.append(
                ParrotOutputEmissionGate(
                    "unsupported_rewrite_requested",
                    "unknown_payload",
                    "Requested Parrot rewrite is outside the ported source-backed behavior.",
                    (PROCESS_METT_SOURCE,),
                )
            )
    return tuple(actions), tuple(gates)


def table_tag_names(table_name: str) -> frozenset[str]:
    return frozenset(definition.tag_name for definition in TAG_TABLES.get(table_name, ()))


def table_source(table_name: str) -> str:
    return TABLE_SOURCES.get(table_name, PROCESS_METT_SOURCE)
