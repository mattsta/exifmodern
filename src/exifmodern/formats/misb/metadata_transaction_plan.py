"""Source-backed, non-mutating MISB KLV metadata transaction plans."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

MISB_TRANSPORT_HEADER_SIZE = 5
MISB_TOP_LEVEL_KEY_SIZE = 16
MISB_DEFAULT_PRESERVED_PREFIX_SIZE = 65_536

MISB_UAS_DATALINK_KEY = "060e2b34020b01010e01030101000000"
MISB_CHURCHILL_NAV_KEY = "060e2b3402030101434e415644494147"
MISB_SECURITY_KEY = "060e2b34030101010e01030302000000"

type MisbBerLengthForm = Literal["short", "long"]
type MisbTopLevelAction = Literal[
    "process_uas_datalink_local_set",
    "process_security_local_set",
    "process_churchill_nav_local_set",
    "preserve_unknown_klv",
]
type MisbLocalSetAction = Literal[
    "route_known_tag",
    "process_security_local_set",
    "process_nested_unknown_local_set",
    "preserve_unknown_tag",
]
type MisbBoundary = Literal[
    "checksum",
    "geospatial",
    "mission",
    "payload",
    "platform",
    "security",
    "sensor",
    "time",
    "unknown",
    "weather",
]
type MisbTableName = Literal["UASDatalink", "Security", "ChurchillNav", "Unknown"]
type MisbResponsibilityConcern = Literal[
    "transport_header_boundary",
    "top_level_klv_routing",
    "ber_length_decoding",
    "local_set_tag_routing",
    "geospatial_time_platform_boundaries",
    "security_payload_preservation",
    "unknown_payload_preservation",
    "malformed_truncation_blockers",
    "unsupported_rewrite_gate",
    "output_emission_gate",
]
type MisbEmissionGateCode = Literal[
    "truncated_transport_header",
    "truncated_transport_payload",
    "truncated_klv_key",
    "invalid_ber_length",
    "truncated_ber_length",
    "truncated_klv_value",
    "truncated_local_set_tag_or_length",
    "truncated_local_set_length",
    "truncated_local_set_value",
    "rewrite_request_not_supported",
    "planner_is_non_mutating",
    "full_misb_writer_not_implemented",
]

MISB_PM_SOURCE_PATH = "lib/Image/ExifTool/MISB.pm"

MISB_MAIN_TABLE_SOURCE = "misb.main.table"
MISB_UAS_TABLE_SOURCE = "misb.uas.table"
MISB_SECURITY_TABLE_SOURCE = "misb.security.table"
MISB_CHURCHILL_TABLE_SOURCE = "misb.churchill.table"
MISB_UNKNOWN_TABLE_SOURCE = "misb.unknown.table"
MISB_LOCAL_SET_SOURCE = "misb.local.set"
MISB_PARSE_SOURCE = "misb.parse"
MISB_TRANSACTION_SOURCES = (
    MISB_MAIN_TABLE_SOURCE,
    MISB_UAS_TABLE_SOURCE,
    MISB_SECURITY_TABLE_SOURCE,
    MISB_CHURCHILL_TABLE_SOURCE,
    MISB_UNKNOWN_TABLE_SOURCE,
    MISB_LOCAL_SET_SOURCE,
    MISB_PARSE_SOURCE,
)


@dataclass(frozen=True)
class MisbTagDefinition:
    name: str
    boundary: MisbBoundary
    format_name: str | None = None
    nested_table: MisbTableName | None = None


@dataclass(frozen=True)
class MisbRewriteRequest:
    replacements: Mapping[str, bytes] | None = None
    delete_tags: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.replacements and not self.delete_tags


@dataclass(frozen=True)
class MisbBerLengthPlan:
    form: MisbBerLengthForm
    first_byte: int
    encoded_size: int
    value_length: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "encoded_size": self.encoded_size,
            "first_byte": self.first_byte,
            "form": self.form,
            "value_length": self.value_length,
        }


@dataclass(frozen=True)
class MisbTransportHeaderPlan:
    metadata_service_id: int | None
    sequence_number: int | None
    flags: int | None
    declared_payload_size: int | None
    actual_payload_size: int
    evidence_ids: tuple[str, ...]

    @property
    def declared_payload_fits(self) -> bool:
        return self.declared_payload_size is not None and (
            self.declared_payload_size <= self.actual_payload_size
        )

    def to_json(self) -> JsonObject:
        return {
            "actual_payload_size": self.actual_payload_size,
            "declared_payload_fits": self.declared_payload_fits,
            "declared_payload_size": self.declared_payload_size,
            "flags": self.flags,
            "metadata_service_id": self.metadata_service_id,
            "sequence_number": self.sequence_number,
        }


@dataclass(frozen=True)
class MisbTopLevelKlvPlan:
    key: str
    name: str
    table_name: MisbTableName
    action: MisbTopLevelAction
    packet_offset: int
    value_offset: int
    declared_value_size: int
    available_value_size: int
    length_plan: MisbBerLengthPlan
    byte_order: Literal["big", "little"]
    preserved_prefix_size: int
    extracted_by_default: bool
    evidence_ids: tuple[str, ...]

    @property
    def is_truncated(self) -> bool:
        return self.available_value_size < self.declared_value_size

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "available_value_size": self.available_value_size,
            "byte_order": self.byte_order,
            "declared_value_size": self.declared_value_size,
            "extracted_by_default": self.extracted_by_default,
            "is_truncated": self.is_truncated,
            "key": self.key,
            "length_plan": self.length_plan.to_json(),
            "name": self.name,
            "packet_offset": self.packet_offset,
            "preserved_prefix_size": self.preserved_prefix_size,
            "table_name": self.table_name,
            "value_offset": self.value_offset,
        }


@dataclass(frozen=True)
class MisbLocalSetTagPlan:
    set_name: str
    table_name: MisbTableName
    tag_id: int
    tag_name: str
    action: MisbLocalSetAction
    boundary: MisbBoundary
    item_offset: int
    value_offset: int
    declared_value_size: int
    available_value_size: int
    length_plan: MisbBerLengthPlan
    preserved_payload: bool
    nested_table: MisbTableName | None
    evidence_ids: tuple[str, ...]

    @property
    def is_truncated(self) -> bool:
        return self.available_value_size < self.declared_value_size

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "available_value_size": self.available_value_size,
            "boundary": self.boundary,
            "declared_value_size": self.declared_value_size,
            "is_truncated": self.is_truncated,
            "item_offset": self.item_offset,
            "length_plan": self.length_plan.to_json(),
            "nested_table": self.nested_table,
            "preserved_payload": self.preserved_payload,
            "set_name": self.set_name,
            "table_name": self.table_name,
            "tag_id": self.tag_id,
            "tag_name": self.tag_name,
            "value_offset": self.value_offset,
        }


@dataclass(frozen=True)
class MisbResponsibilityPlan:
    order: int
    concern: MisbResponsibilityConcern
    detail: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "detail": self.detail,
            "order": self.order,
        }


@dataclass(frozen=True)
class MisbEmissionGate:
    code: MisbEmissionGateCode
    detail: str
    blocks_output: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_output": self.blocks_output,
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class MisbMetadataTransactionPlan:
    transport_header: MisbTransportHeaderPlan
    klv_packets: tuple[MisbTopLevelKlvPlan, ...]
    local_set_tags: tuple[MisbLocalSetTagPlan, ...]
    responsibilities: tuple[MisbResponsibilityPlan, ...]
    output_emission_gates: tuple[MisbEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return False

    @property
    def packet_names(self) -> tuple[str, ...]:
        return tuple(packet.name for packet in self.klv_packets)

    @property
    def tag_names(self) -> tuple[str, ...]:
        return tuple(tag.tag_name for tag in self.local_set_tags)

    @property
    def preserved_payload_bytes(self) -> int:
        return sum(packet.available_value_size for packet in self.klv_packets)

    def emit(self) -> bytes:
        raise ValueError("MISB metadata transaction output is gated.")

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "klv_packets": [packet.to_json() for packet in self.klv_packets],
            "local_set_tags": [tag.to_json() for tag in self.local_set_tags],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "transport_header": self.transport_header.to_json(),
        }


UAS_DATALINK_TAGS: dict[int, MisbTagDefinition] = {
    1: MisbTagDefinition("Checksum", "checksum", "int16u"),
    2: MisbTagDefinition("GPSDateTime", "time", "int64u"),
    3: MisbTagDefinition("MissionID", "mission", "string"),
    4: MisbTagDefinition("TailNumber", "platform", "string"),
    5: MisbTagDefinition("GPSTrack", "platform", "int16u"),
    6: MisbTagDefinition("PitchAngle", "platform", "int16s"),
    7: MisbTagDefinition("RollAngle", "platform", "int16s"),
    8: MisbTagDefinition("TrueAirspeed", "platform", "int8u"),
    9: MisbTagDefinition("IndicatedAirspeed", "platform", "int8u"),
    10: MisbTagDefinition("ProjectIDCode", "mission", "string"),
    11: MisbTagDefinition("SensorName", "sensor", "string"),
    12: MisbTagDefinition("ImageCoordinateSystem", "sensor", "string"),
    13: MisbTagDefinition("GPSLatitude", "geospatial", "int32s"),
    14: MisbTagDefinition("GPSLongitude", "geospatial", "int32s"),
    15: MisbTagDefinition("GPSAltitude", "geospatial", "int16u"),
    16: MisbTagDefinition("HorizontalFieldOfView", "sensor", "int16u"),
    17: MisbTagDefinition("VerticalFieldOfView", "sensor", "int16u"),
    18: MisbTagDefinition("SensorRelativeAzimuthAngle", "sensor", "int32u"),
    19: MisbTagDefinition("SensorRelativeElevationAngle", "sensor", "int32s"),
    20: MisbTagDefinition("SensorRelativeRollAngle", "sensor", "int32u"),
    21: MisbTagDefinition("SlantRange", "sensor", "int32u"),
    22: MisbTagDefinition("TargetWidth", "geospatial", "int16u"),
    23: MisbTagDefinition("FrameCenterLatitude", "geospatial", "int32s"),
    24: MisbTagDefinition("FrameCenterLongitude", "geospatial", "int32s"),
    25: MisbTagDefinition("FrameCenterElevation", "geospatial", "int16u"),
    26: MisbTagDefinition("OffsetCornerLatitude1", "geospatial", "int16s"),
    27: MisbTagDefinition("OffsetCornerLongitude1", "geospatial", "int16s"),
    28: MisbTagDefinition("OffsetCornerLatitude2", "geospatial", "int16s"),
    29: MisbTagDefinition("OffsetCornerLongitude2", "geospatial", "int16s"),
    30: MisbTagDefinition("OffsetCornerLatitude3", "geospatial", "int16s"),
    31: MisbTagDefinition("OffsetCornerLongitude3", "geospatial", "int16s"),
    32: MisbTagDefinition("OffsetCornerLatitude4", "geospatial", "int16s"),
    33: MisbTagDefinition("OffsetCornerLongitude4", "geospatial", "int16s"),
    34: MisbTagDefinition("IcingDetected", "weather", "int8u"),
    35: MisbTagDefinition("WindDirection", "weather", "int16u"),
    36: MisbTagDefinition("WindSpeed", "weather", "int8u"),
    37: MisbTagDefinition("StaticPressure", "weather", "int16u"),
    38: MisbTagDefinition("DensityAltitude", "platform", "int16u"),
    39: MisbTagDefinition("AirTemperature", "weather", "int8s"),
    40: MisbTagDefinition("TargetLocationLatitude", "geospatial", "int32s"),
    41: MisbTagDefinition("TargetLocationLongitude", "geospatial", "int32s"),
    42: MisbTagDefinition("TargetLocationElevation", "geospatial", "int16u"),
    43: MisbTagDefinition("TargetTrackGateWidth", "geospatial", "int8u"),
    44: MisbTagDefinition("TargetTrackGateHeight", "geospatial", "int8u"),
    45: MisbTagDefinition("TargetErrorEstimateCE90", "geospatial", "int16u"),
    46: MisbTagDefinition("TargetErrorEstimateLE90", "geospatial", "int16u"),
    47: MisbTagDefinition("GenericFlagData01", "payload", "int8u"),
    48: MisbTagDefinition("SecurityLocalMetadataSet", "security", None, "Security"),
    49: MisbTagDefinition("DifferentialPressure", "weather", "int16u"),
    50: MisbTagDefinition("AngleOfAttack", "platform", "int16s"),
    51: MisbTagDefinition("VerticalSpeed", "platform", "int16s"),
    52: MisbTagDefinition("SideslipAngle", "platform", "int16s"),
    53: MisbTagDefinition("AirfieldBarometricPressure", "weather", "int16u"),
    54: MisbTagDefinition("AirfieldElevation", "geospatial", "int16u"),
    55: MisbTagDefinition("RelativeHumidity", "weather", "int8u"),
    56: MisbTagDefinition("GPSSpeed", "platform", "int8u"),
    57: MisbTagDefinition("GroundRange", "geospatial", "int32u"),
    58: MisbTagDefinition("FuelRemaining", "platform", "int16u"),
    59: MisbTagDefinition("CallSign", "platform", "string"),
    60: MisbTagDefinition("WeaponLoad", "platform", "int16u"),
    61: MisbTagDefinition("WeaponFired", "platform", "int8u"),
    62: MisbTagDefinition("LaserPRFCode", "sensor", "int16u"),
    63: MisbTagDefinition("SensorFieldOfViewName", "sensor", "int8u"),
    64: MisbTagDefinition("MagneticHeading", "platform", "int16u"),
    65: MisbTagDefinition("UAS_LSVersionNumber", "payload", "int8u"),
    66: MisbTagDefinition("TargetLocationCovarianceMatrix", "payload", "undef"),
    67: MisbTagDefinition("AlternateLatitude", "geospatial", "int32s"),
    68: MisbTagDefinition("AlternateLongitude", "geospatial", "int32s"),
    69: MisbTagDefinition("AlternateAltitude", "geospatial", "int16u"),
    70: MisbTagDefinition("AlternateName", "mission", "string"),
    71: MisbTagDefinition("AlternateHeading", "platform", "int16u"),
    72: MisbTagDefinition("EventStartTime", "time", "int64u"),
    73: MisbTagDefinition("RVTLocalSet", "payload", None, "Unknown"),
    74: MisbTagDefinition("VMTIDataSet", "payload", None, "Unknown"),
    75: MisbTagDefinition("SensorEllipsoidHeight", "geospatial", "int16u"),
    76: MisbTagDefinition("AlternateEllipsoidHeight", "geospatial", "int16u"),
    77: MisbTagDefinition("OperationalMode", "platform", "int8u"),
    78: MisbTagDefinition("FrameCenterHeightAboveEllipsoid", "geospatial", "int16u"),
    79: MisbTagDefinition("SensorVelocityNorth", "platform", "int16s"),
    80: MisbTagDefinition("SensorVelocityEast", "platform", "int16s"),
    81: MisbTagDefinition("ImageHorizonPixelPack", "payload", "undef"),
    82: MisbTagDefinition("CornerLatitude1", "geospatial", "int32s"),
    83: MisbTagDefinition("CornerLongitude1", "geospatial", "int32s"),
    84: MisbTagDefinition("CornerLatitude2", "geospatial", "int32s"),
    85: MisbTagDefinition("CornerLongitude2", "geospatial", "int32s"),
    86: MisbTagDefinition("CornerLatitude3", "geospatial", "int32s"),
    87: MisbTagDefinition("CornerLongitude3", "geospatial", "int32s"),
    88: MisbTagDefinition("CornerLatitude4", "geospatial", "int32s"),
    89: MisbTagDefinition("CornerLongitude4", "geospatial", "int32s"),
    90: MisbTagDefinition("FullPitchAngle", "platform", "int32s"),
    91: MisbTagDefinition("FullRollAngle", "platform", "int32s"),
    92: MisbTagDefinition("FullAngleOfAttack", "platform", "int32s"),
    93: MisbTagDefinition("FullSideslipAngle", "platform", "int32s"),
    94: MisbTagDefinition("MIISCoreIdentifier", "payload", "undef"),
    95: MisbTagDefinition("SARMotionImageryData", "payload", None, "Unknown"),
    96: MisbTagDefinition("TargetWidthExtended", "payload", "undef"),
    97: MisbTagDefinition("RangeImageLocalSet", "payload", None, "Unknown"),
    98: MisbTagDefinition("GeoregistrationLocalSet", "payload", None, "Unknown"),
    99: MisbTagDefinition("CompositeImagingLocalSet", "payload", None, "Unknown"),
    100: MisbTagDefinition("SegmentLocalSet", "payload", None, "Unknown"),
    101: MisbTagDefinition("AmendLocalSet", "payload", None, "Unknown"),
    102: MisbTagDefinition("SDCC-FLP", "payload", "undef"),
    103: MisbTagDefinition("DensityAltitudeExtended", "payload", "undef"),
    104: MisbTagDefinition("SensorEllipsoidHeightExtended", "payload", "undef"),
    105: MisbTagDefinition("AlternateEllipsoidHeightExtended", "payload", "undef"),
}
SECURITY_TAGS: dict[int, MisbTagDefinition] = {
    1: MisbTagDefinition("SecurityClassification", "security"),
    2: MisbTagDefinition("ClassifyingCountryCodeMethod", "security"),
    3: MisbTagDefinition("ClassifyingCountry", "security", "string"),
    4: MisbTagDefinition("SecuritySCI-SHIInformation", "security"),
    5: MisbTagDefinition("Caveats", "security", "string"),
    6: MisbTagDefinition("ReleasingInstructions", "security", "string"),
    7: MisbTagDefinition("ClassifiedBy", "security", "string"),
    8: MisbTagDefinition("DerivedFrom", "security", "string"),
    9: MisbTagDefinition("ClassificationReason", "security", "string"),
    10: MisbTagDefinition("DeclassificationDate", "time", "string"),
    11: MisbTagDefinition("ClassificationAndMarkingSystem", "security"),
    12: MisbTagDefinition("ObjectCountryCodingMethod", "security"),
    13: MisbTagDefinition("ObjectCountryCodes", "security", "string"),
    14: MisbTagDefinition("ClassificationComments", "security", "string"),
    15: MisbTagDefinition("UMID", "security"),
    16: MisbTagDefinition("StreamID", "security"),
    17: MisbTagDefinition("TransportStreamID", "security"),
    21: MisbTagDefinition("ItemDesignatorID", "security"),
    22: MisbTagDefinition("SecurityVersion", "security", "int16u"),
    23: MisbTagDefinition("ClassifyingCountryCodingMethodDate", "time", "string"),
    24: MisbTagDefinition("ObjectCountryCodingMethodDate", "time", "string"),
}
CHURCHILL_NAV_TAGS: dict[int, MisbTagDefinition] = {
    1: MisbTagDefinition("ChurchillNav_0x0001", "unknown", "double"),
    2: MisbTagDefinition("ChurchillNav_0x0002", "unknown", "double"),
    3: MisbTagDefinition("ChurchillNav_0x0003", "unknown", "double"),
    4: MisbTagDefinition("ChurchillNav_0x0004", "unknown", "double"),
    5: MisbTagDefinition("ChurchillNav_0x0005", "unknown", "double"),
    6: MisbTagDefinition("ChurchillNav_0x0006", "unknown", "double"),
    9: MisbTagDefinition("ChurchillNav_0x0009", "unknown", "double"),
    10: MisbTagDefinition("ChurchillNav_0x000a", "unknown", "double"),
    11: MisbTagDefinition("ChurchillNav_0x000b", "unknown", "string"),
    12: MisbTagDefinition("ChurchillNav_0x000c", "unknown", "double"),
    13: MisbTagDefinition("ChurchillNav_0x000d", "unknown", "double"),
    14: MisbTagDefinition("ChurchillNav_0x000e", "unknown", "double"),
    16: MisbTagDefinition("ChurchillNav_0x0010", "unknown", "double"),
    17: MisbTagDefinition("ChurchillNav_0x0011", "unknown", "double"),
    18: MisbTagDefinition("ChurchillNav_0x0012", "unknown", "double"),
    20: MisbTagDefinition("ChurchillNav_0x0014", "unknown", "double"),
}
TAG_TABLES: dict[MisbTableName, Mapping[int, MisbTagDefinition]] = {
    "UASDatalink": UAS_DATALINK_TAGS,
    "Security": SECURITY_TAGS,
    "ChurchillNav": CHURCHILL_NAV_TAGS,
    "Unknown": {},
}


def build_misb_metadata_transaction_plan(
    data: bytes,
    rewrite_request: MisbRewriteRequest | None = None,
    *,
    include_unknown: bool = False,
    verbose: bool = False,
) -> MisbMetadataTransactionPlan:
    gates: list[MisbEmissionGate] = []
    packets: list[MisbTopLevelKlvPlan] = []
    local_tags: list[MisbLocalSetTagPlan] = []
    transport_header = parse_transport_header(data, gates)
    if len(data) >= MISB_TRANSPORT_HEADER_SIZE:
        parse_top_level_klv(data, include_unknown or verbose, packets, local_tags, gates)
    if rewrite_request is not None and not rewrite_request.is_empty:
        gates.append(
            MisbEmissionGate(
                "rewrite_request_not_supported",
                "MISB.pm only reads KLV metadata; tag replacement and deletion need a writer.",
                True,
                (MISB_PARSE_SOURCE,),
            )
        )
    gates.extend(default_output_gates())
    all_sources: list[str] = [*MISB_TRANSACTION_SOURCES]
    for packet in packets:
        all_sources.extend(packet.evidence_ids)
        all_sources.extend(packet.length_plan.evidence_ids)
    for tag in local_tags:
        all_sources.extend(tag.evidence_ids)
        all_sources.extend(tag.length_plan.evidence_ids)
    for gate in gates:
        all_sources.extend(gate.evidence_ids)
    return MisbMetadataTransactionPlan(
        transport_header=transport_header,
        klv_packets=tuple(packets),
        local_set_tags=tuple(local_tags),
        responsibilities=default_responsibilities(),
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=unique_sources(all_sources),
    )


def parse_transport_header(data: bytes, gates: list[MisbEmissionGate]) -> MisbTransportHeaderPlan:
    actual_payload_size = max(0, len(data) - MISB_TRANSPORT_HEADER_SIZE)
    if len(data) < MISB_TRANSPORT_HEADER_SIZE:
        gates.append(
            MisbEmissionGate(
                "truncated_transport_header",
                "MISB metadata is shorter than the 5-byte STANAG metadata header.",
                True,
                (MISB_PARSE_SOURCE,),
            )
        )
        return MisbTransportHeaderPlan(
            None,
            None,
            None,
            None,
            actual_payload_size,
            (MISB_PARSE_SOURCE,),
        )
    declared_payload_size = int.from_bytes(data[3:5], "big")
    if declared_payload_size > actual_payload_size:
        gates.append(
            MisbEmissionGate(
                "truncated_transport_payload",
                "The 5-byte MISB header declares more payload bytes than are available.",
                True,
                (MISB_PARSE_SOURCE,),
            )
        )
    return MisbTransportHeaderPlan(
        data[0],
        data[1],
        data[2],
        declared_payload_size,
        actual_payload_size,
        (MISB_PARSE_SOURCE,),
    )


def parse_top_level_klv(
    data: bytes,
    expose_unknown: bool,
    packets: list[MisbTopLevelKlvPlan],
    local_tags: list[MisbLocalSetTagPlan],
    gates: list[MisbEmissionGate],
) -> None:
    end = len(data)
    pos = MISB_TRANSPORT_HEADER_SIZE
    while pos + MISB_TOP_LEVEL_KEY_SIZE < end:
        packet_offset = pos
        key = data[pos : pos + MISB_TOP_LEVEL_KEY_SIZE].hex()
        pos += MISB_TOP_LEVEL_KEY_SIZE
        length_result = read_ber_length(data, pos, end, (MISB_PARSE_SOURCE,), gates, "klv")
        if length_result is None:
            return
        length_plan, value_offset = length_result
        declared_value_size = length_plan.value_length
        available_value_size = min(declared_value_size, max(0, end - value_offset))
        if value_offset + declared_value_size > end:
            gates.append(
                MisbEmissionGate(
                    "truncated_klv_value",
                    "A top-level MISB KLV record declares more bytes than remain.",
                    True,
                    (MISB_PARSE_SOURCE,),
                )
            )
        name, table_name, action, byte_order, extracted_by_default, sources = (
            classify_top_level_key(key)
        )
        packet = MisbTopLevelKlvPlan(
            key,
            name,
            table_name,
            action,
            packet_offset,
            value_offset,
            declared_value_size,
            available_value_size,
            length_plan,
            byte_order,
            min(available_value_size, MISB_DEFAULT_PRESERVED_PREFIX_SIZE),
            extracted_by_default,
            sources,
        )
        packets.append(packet)
        if extracted_by_default or expose_unknown:
            parse_local_set(data, packet, local_tags, gates)
        pos = value_offset + declared_value_size
        if value_offset + declared_value_size > end:
            return
    if pos < end:
        gates.append(
            MisbEmissionGate(
                "truncated_klv_key",
                "Trailing MISB bytes are too short for a 16-byte top-level KLV key.",
                True,
                (MISB_PARSE_SOURCE,),
            )
        )


def parse_local_set(
    data: bytes,
    packet: MisbTopLevelKlvPlan,
    local_tags: list[MisbLocalSetTagPlan],
    gates: list[MisbEmissionGate],
) -> None:
    end = packet.value_offset + packet.available_value_size
    pos = packet.value_offset
    while pos < end - 1:
        item_offset = pos
        tag_id = data[pos]
        pos += 1
        length_result = read_ber_length(data, pos, end, (MISB_LOCAL_SET_SOURCE,), gates, "local")
        if length_result is None:
            return
        length_plan, value_offset = length_result
        declared_value_size = length_plan.value_length
        available_value_size = min(declared_value_size, max(0, end - value_offset))
        if value_offset + declared_value_size > end:
            gates.append(
                MisbEmissionGate(
                    "truncated_local_set_value",
                    f"Local set {packet.name} tag {tag_id} declares more bytes than remain.",
                    True,
                    (MISB_LOCAL_SET_SOURCE,),
                )
            )
        definition = TAG_TABLES[packet.table_name].get(tag_id)
        tag = build_local_tag_plan(
            packet,
            tag_id,
            definition,
            item_offset,
            value_offset,
            declared_value_size,
            available_value_size,
            length_plan,
        )
        local_tags.append(tag)
        if definition is not None and definition.nested_table in {"Security", "Unknown"}:
            parse_local_set(
                data,
                nested_local_set_packet(packet, tag, definition.nested_table),
                local_tags,
                gates,
            )
        pos = value_offset + declared_value_size
        if value_offset + declared_value_size > end:
            return
    if pos < end:
        gates.append(
            MisbEmissionGate(
                "truncated_local_set_tag_or_length",
                f"Local set {packet.name} ended with a partial tag or length byte.",
                True,
                (MISB_LOCAL_SET_SOURCE,),
            )
        )


def build_local_tag_plan(
    packet: MisbTopLevelKlvPlan,
    tag_id: int,
    definition: MisbTagDefinition | None,
    item_offset: int,
    value_offset: int,
    declared_value_size: int,
    available_value_size: int,
    length_plan: MisbBerLengthPlan,
) -> MisbLocalSetTagPlan:
    if definition is None:
        action: MisbLocalSetAction = "preserve_unknown_tag"
        return MisbLocalSetTagPlan(
            packet.name,
            packet.table_name,
            tag_id,
            f"{packet.table_name}_0x{tag_id:02x}",
            action,
            "unknown",
            item_offset,
            value_offset,
            declared_value_size,
            available_value_size,
            length_plan,
            True,
            None,
            (MISB_LOCAL_SET_SOURCE, table_source(packet.table_name), MISB_UNKNOWN_TABLE_SOURCE),
        )
    action = local_action_for_definition(definition)
    sources: tuple[str, ...] = (
        MISB_LOCAL_SET_SOURCE,
        table_source(packet.table_name),
    )
    if definition.nested_table is not None:
        sources = (*sources, table_source(definition.nested_table))
    return MisbLocalSetTagPlan(
        packet.name,
        packet.table_name,
        tag_id,
        definition.name,
        action,
        definition.boundary,
        item_offset,
        value_offset,
        declared_value_size,
        available_value_size,
        length_plan,
        True,
        definition.nested_table,
        sources,
    )


def local_action_for_definition(definition: MisbTagDefinition) -> MisbLocalSetAction:
    if definition.nested_table == "Security":
        return "process_security_local_set"
    if definition.nested_table == "Unknown":
        return "process_nested_unknown_local_set"
    return "route_known_tag"


def nested_local_set_packet(
    parent: MisbTopLevelKlvPlan,
    tag: MisbLocalSetTagPlan,
    nested_table: MisbTableName | None,
) -> MisbTopLevelKlvPlan:
    table_name: MisbTableName = "Unknown" if nested_table is None else nested_table
    action: MisbTopLevelAction = (
        "process_security_local_set" if table_name == "Security" else "preserve_unknown_klv"
    )
    return MisbTopLevelKlvPlan(
        f"{parent.key}:{tag.tag_id}",
        tag.tag_name,
        table_name,
        action,
        tag.item_offset,
        tag.value_offset,
        tag.declared_value_size,
        tag.available_value_size,
        tag.length_plan,
        parent.byte_order,
        min(tag.available_value_size, MISB_DEFAULT_PRESERVED_PREFIX_SIZE),
        True,
        (MISB_LOCAL_SET_SOURCE, table_source(table_name)),
    )


def read_ber_length(
    data: bytes,
    pos: int,
    end: int,
    sources: tuple[str, ...],
    gates: list[MisbEmissionGate],
    scope: Literal["klv", "local"],
) -> tuple[MisbBerLengthPlan, int] | None:
    if pos >= end:
        missing_code: MisbEmissionGateCode = (
            "truncated_ber_length" if scope == "klv" else "truncated_local_set_length"
        )
        gates.append(
            MisbEmissionGate(
                missing_code,
                "A MISB BER length byte is missing.",
                True,
                sources,
            )
        )
        return None
    first_byte = data[pos]
    pos += 1
    if first_byte < 0x80:
        return MisbBerLengthPlan("short", first_byte, 1, first_byte, sources), pos
    byte_count = first_byte & 0x7F
    if byte_count == 0:
        gates.append(
            MisbEmissionGate(
                "invalid_ber_length",
                "MISB BER indefinite lengths are not supported by MISB.pm.",
                True,
                sources,
            )
        )
        return None
    if pos + byte_count > end:
        truncated_code: MisbEmissionGateCode = (
            "truncated_ber_length" if scope == "klv" else "truncated_local_set_length"
        )
        gates.append(
            MisbEmissionGate(
                truncated_code,
                "A MISB BER long-form length extends beyond available bytes.",
                True,
                sources,
            )
        )
        return None
    value_length = int.from_bytes(data[pos : pos + byte_count], "big")
    return (
        MisbBerLengthPlan("long", first_byte, 1 + byte_count, value_length, sources),
        pos + byte_count,
    )


def classify_top_level_key(
    key: str,
) -> tuple[
    str,
    MisbTableName,
    MisbTopLevelAction,
    Literal["big", "little"],
    bool,
    tuple[str, ...],
]:
    normalized = key.lower()
    if normalized == MISB_UAS_DATALINK_KEY:
        return (
            "UASDataLink",
            "UASDatalink",
            "process_uas_datalink_local_set",
            "big",
            True,
            (MISB_MAIN_TABLE_SOURCE, MISB_UAS_TABLE_SOURCE, MISB_PARSE_SOURCE),
        )
    if normalized == MISB_CHURCHILL_NAV_KEY:
        return (
            "ChurchillNav",
            "ChurchillNav",
            "process_churchill_nav_local_set",
            "little",
            True,
            (MISB_MAIN_TABLE_SOURCE, MISB_CHURCHILL_TABLE_SOURCE, MISB_PARSE_SOURCE),
        )
    if normalized == MISB_SECURITY_KEY:
        return (
            "Security",
            "Security",
            "process_security_local_set",
            "big",
            True,
            (MISB_MAIN_TABLE_SOURCE, MISB_SECURITY_TABLE_SOURCE, MISB_PARSE_SOURCE),
        )
    return (
        f"MISB_{key}",
        "Unknown",
        "preserve_unknown_klv",
        "big",
        False,
        (MISB_MAIN_TABLE_SOURCE, MISB_UNKNOWN_TABLE_SOURCE, MISB_PARSE_SOURCE),
    )


def table_source(table_name: MisbTableName) -> str:
    if table_name == "UASDatalink":
        return MISB_UAS_TABLE_SOURCE
    if table_name == "Security":
        return MISB_SECURITY_TABLE_SOURCE
    if table_name == "ChurchillNav":
        return MISB_CHURCHILL_TABLE_SOURCE
    return MISB_UNKNOWN_TABLE_SOURCE


def default_responsibilities() -> tuple[MisbResponsibilityPlan, ...]:
    return (
        MisbResponsibilityPlan(
            1,
            "transport_header_boundary",
            "Skip the 5-byte STANAG metadata header.",
            (MISB_PARSE_SOURCE,),
        ),
        MisbResponsibilityPlan(
            2,
            "top_level_klv_routing",
            "Route 16-byte MISB keys to known local sets.",
            (MISB_MAIN_TABLE_SOURCE, MISB_PARSE_SOURCE),
        ),
        MisbResponsibilityPlan(
            3,
            "ber_length_decoding",
            "Decode short and long BER lengths.",
            (MISB_PARSE_SOURCE, MISB_LOCAL_SET_SOURCE),
        ),
        MisbResponsibilityPlan(
            4,
            "local_set_tag_routing",
            "Route one-byte local-set tag IDs.",
            (MISB_LOCAL_SET_SOURCE, MISB_UAS_TABLE_SOURCE, MISB_SECURITY_TABLE_SOURCE),
        ),
        MisbResponsibilityPlan(
            5,
            "geospatial_time_platform_boundaries",
            "Keep GPS, time, platform, sensor, mission, weather, and payload tags separated.",
            (MISB_UAS_TABLE_SOURCE, MISB_SECURITY_TABLE_SOURCE),
        ),
        MisbResponsibilityPlan(
            6,
            "security_payload_preservation",
            "Preserve checksum bytes and Security local-set payloads.",
            (MISB_UAS_TABLE_SOURCE, MISB_SECURITY_TABLE_SOURCE),
        ),
        MisbResponsibilityPlan(
            7,
            "unknown_payload_preservation",
            "Preserve unknown top-level KLV and Unknown local-set payload ranges.",
            (MISB_MAIN_TABLE_SOURCE, MISB_UNKNOWN_TABLE_SOURCE),
        ),
        MisbResponsibilityPlan(
            8,
            "malformed_truncation_blockers",
            "Block emission for incomplete BER lengths, KLV values, or local-set values.",
            (MISB_PARSE_SOURCE, MISB_LOCAL_SET_SOURCE),
        ),
        MisbResponsibilityPlan(
            9,
            "unsupported_rewrite_gate",
            "Reject MISB tag edits until a writer can recalculate KLV lengths.",
            (MISB_PARSE_SOURCE,),
        ),
        MisbResponsibilityPlan(
            10,
            "output_emission_gate",
            "Keep transaction planning non-mutating because MISB.pm provides no writer.",
            (MISB_PARSE_SOURCE,),
        ),
    )


def default_output_gates() -> tuple[MisbEmissionGate, ...]:
    return (
        MisbEmissionGate(
            "planner_is_non_mutating",
            "The MISB transaction plan records byte ranges but does not mutate source bytes.",
            True,
            (MISB_PARSE_SOURCE,),
        ),
        MisbEmissionGate(
            "full_misb_writer_not_implemented",
            "Length-safe MISB KLV rewrite and emission are intentionally unsupported.",
            True,
            (MISB_PARSE_SOURCE,),
        ),
    )


def encode_ber_length(length: int) -> bytes:
    """Encode a BER length for synthetic MISB fixtures."""

    if length < 0:
        raise ValueError("MISB BER length must be non-negative.")
    if length < 0x80:
        return bytes((length,))
    size = max(1, (length.bit_length() + 7) // 8)
    return bytes((0x80 | size,)) + length.to_bytes(size, "big")


def encode_misb_klv(key: str, payload: bytes) -> bytes:
    """Encode a top-level MISB KLV record for synthetic fixtures."""

    return bytes.fromhex(key) + encode_ber_length(len(payload)) + payload


def encode_local_set_item(tag_id: int, payload: bytes) -> bytes:
    """Encode one ProcessKLV local-set item for synthetic fixtures."""

    if not 0 <= tag_id <= 0xFF:
        raise ValueError("MISB local-set tag IDs are one byte.")
    return bytes((tag_id,)) + encode_ber_length(len(payload)) + payload


def encode_misb_transport_packet(payload: bytes, *, sequence_number: int = 1) -> bytes:
    """Encode the 5-byte STANAG metadata header plus KLV payload."""

    if not 0 <= sequence_number <= 0xFF:
        raise ValueError("MISB sequence number must fit one byte.")
    return b"\x00" + bytes((sequence_number, 0x0F)) + len(payload).to_bytes(2, "big") + payload


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in references:
        key = source
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return tuple(unique)


def unique_gates(gates: tuple[MisbEmissionGate, ...]) -> tuple[MisbEmissionGate, ...]:
    unique: list[MisbEmissionGate] = []
    seen: set[MisbEmissionGateCode] = set()
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
