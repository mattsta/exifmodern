"""Source-grounded, non-mutating FLIR metadata transaction plans.

ExifTool's FLIR module reads maker-note temperature tags, FLIR FFF/AFF record
directories, raw thermal payload containers, camera/measurement/GPS records,
and unknown records. This planner mirrors those boundaries without attempting a
writer: known records are routed to their source tables, opaque image payloads
are preserved exactly, malformed/truncated inputs become blockers, and rewrite
requests are surfaced as unsupported gates.
"""

from __future__ import annotations

import struct
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.flir.provenance import SourceAnchor
from exifmodern.json_types import JsonArray, JsonObject, JsonValue

FLIR_PM_SOURCE_PATH = "lib/Image/ExifTool/FLIR.pm"
FLIR_HEADER_SIZE = 0x40
FLIR_RECORD_ENTRY_SIZE = 0x20

type FlirPlanStatus = Literal["planned", "unsupported"]
type FlirContainerKind = Literal["none", "FFF", "AFF"]
type FlirByteOrder = Literal["big", "little"]
type FlirTable = Literal[
    "Main",
    "FFF",
    "AFF",
    "Header",
    "RawData",
    "GainDeadData",
    "CoarseData",
    "EmbeddedImage",
    "CameraInfo",
    "MeasInfo",
    "PaletteInfo",
    "TextInfo",
    "PaintData",
    "PiP",
    "GPSInfo",
    "MeterLink",
    "ParamInfo",
    "Unknown",
]
type FlirGroup0 = Literal["MakerNotes", "APP1", "FLIR"]
type FlirGroup2 = Literal["Camera", "Image", "Location", "Preview", "Time", "Unknown"]
type FlirRecordRole = Literal[
    "fff_header",
    "main_makernote_scalar",
    "raw_thermal_payload",
    "calibration_payload",
    "embedded_image_payload",
    "camera_metadata",
    "measurement_metadata",
    "gps_subdirectory",
    "table_routed_payload",
    "unknown_record",
    "empty_record",
]
type FlirActionKind = Literal[
    "route_main_makernote_tag",
    "validate_fff_header",
    "route_fff_record",
    "preserve_raw_thermal_payload",
    "preserve_calibration_payload",
    "parse_camera_info_boundary",
    "parse_measurement_info_boundary",
    "route_gps_subdirectory",
    "preserve_unknown_record",
    "skip_empty_record",
    "block_requested_rewrite",
    "no_metadata_mutation",
]
type FlirEmissionGateCode = Literal[
    "bad_format_flir_data",
    "truncated_flir_header",
    "unsupported_flir_version",
    "truncated_flir_directory",
    "invalid_flir_record",
    "truncated_flir_record_payload",
    "unrecognized_thermal_payload",
    "flir_payload_rewrite_required",
    "flir_directory_delete_required",
    "flir_main_rewrite_required",
    "flir_raw_thermal_rewrite_required",
    "flir_gps_rewrite_required",
    "planner_is_non_mutating",
    "full_flir_writer_not_implemented",
]
type FlirResponsibilityConcern = Literal[
    "main_makernote_routing",
    "fff_header_table_routing",
    "raw_gain_camera_measurement_boundaries",
    "temperature_conversion_boundaries",
    "gps_exif_subdirectory_boundaries",
    "thermal_image_payload_preservation",
    "unknown_record_preservation",
    "malformed_truncation_blockers",
    "unsupported_rewrite_gates",
]
type FlirTemperatureBoundary = Literal[
    "unit_ambiguous_rational_temperature",
    "kelvin_float_to_celsius_read_conversion",
    "not_temperature",
]

FLIR_MAIN_SOURCE = SourceAnchor(
    evidence_id="flir.main.makernote_tags",
    path=FLIR_PM_SOURCE_PATH,
    line_start=53,
    line_end=91,
    symbol="%Image::ExifTool::FLIR::Main",
    evidence=(
        "FLIR maker notes route writable Main tags including image max/min "
        "temperatures and emissivity."
    ),
)
FLIR_FFF_SOURCE = SourceAnchor(
    evidence_id="flir.fff.table_routing",
    path=FLIR_PM_SOURCE_PATH,
    line_start=95,
    line_end=180,
    symbol="%Image::ExifTool::FLIR::FFF",
    evidence="FFF routes header and record types to FLIR sub-tables.",
)
FLIR_HEADER_SOURCE = SourceAnchor(
    evidence_id="flir.header.metadata",
    path=FLIR_PM_SOURCE_PATH,
    line_start=183,
    line_end=193,
    symbol="%Image::ExifTool::FLIR::Header",
    evidence="Header exposes FLIR FFF/AFF header metadata such as CreatorSoftware.",
)
FLIR_RAW_SOURCE = SourceAnchor(
    evidence_id="flir.raw_data.payload",
    path=FLIR_PM_SOURCE_PATH,
    line_start=197,
    line_end=247,
    symbol="%Image::ExifTool::FLIR::RawData",
    evidence="RawData records hold raw thermal image width, height, type, and bytes.",
)
FLIR_GAIN_SOURCE = SourceAnchor(
    evidence_id="flir.gain_dead_data.payload",
    path=FLIR_PM_SOURCE_PATH,
    line_start=250,
    line_end=277,
    symbol="%Image::ExifTool::FLIR::GainDeadData",
    evidence="GainDeadData follows RawData-style image payload boundaries.",
)
FLIR_CAMERA_SOURCE = SourceAnchor(
    evidence_id="flir.camera_info.tags",
    path=FLIR_PM_SOURCE_PATH,
    line_start=376,
    line_end=471,
    symbol="%Image::ExifTool::FLIR::CameraInfo",
    evidence="CameraInfo defines camera, Planck, emissivity, humidity, and Kelvin float tags.",
)
FLIR_MEAS_SOURCE = SourceAnchor(
    evidence_id="flir.measurement_info.tags",
    path=FLIR_PM_SOURCE_PATH,
    line_start=475,
    line_end=502,
    symbol="%Image::ExifTool::FLIR::MeasInfo",
    evidence="MeasInfo records dynamically expose measurement type, params, and label.",
)
FLIR_GPS_SOURCE = SourceAnchor(
    evidence_id="flir.gps_info.subdirectory",
    path=FLIR_PM_SOURCE_PATH,
    line_start=613,
    line_end=705,
    symbol="%Image::ExifTool::FLIR::GPSInfo",
    evidence="GPSInfo is a Location subdirectory with validity-gated GPS fields.",
)
FLIR_IMAGE_TYPE_SOURCE = SourceAnchor(
    evidence_id="flir.image_type.detect_payload",
    path=FLIR_PM_SOURCE_PATH,
    line_start=1326,
    line_end=1354,
    symbol="GetImageType",
    evidence="GetImageType detects PNG/JPG/TIFF/DAT and preserves the image bytes.",
)
FLIR_PROCESS_MEAS_SOURCE = SourceAnchor(
    evidence_id="flir.process_measurements.variable_records",
    path=FLIR_PM_SOURCE_PATH,
    line_start=1410,
    line_end=1459,
    symbol="ProcessMeasInfo",
    evidence="ProcessMeasInfo walks variable-length measurement records.",
)
FLIR_PROCESS_SOURCE = SourceAnchor(
    evidence_id="flir.process_flir.directory",
    path=FLIR_PM_SOURCE_PATH,
    line_start=1468,
    line_end=1591,
    symbol="ProcessFLIR",
    evidence=(
        "ProcessFLIR validates FFF/AFF headers, reads the record directory, routes "
        "known records, and warns on truncated directories or invalid records."
    ),
)
FLIR_READ_ONLY_SOURCE = SourceAnchor(
    evidence_id="flir.module.read_only",
    path=FLIR_PM_SOURCE_PATH,
    line_start=6,
    line_end=6,
    symbol="FLIR.pm module description",
    evidence="FLIR.pm is described as reading FLIR meta information.",
)

FLIR_TRANSACTION_EVIDENCE_ANCHORS = (
    FLIR_MAIN_SOURCE,
    FLIR_FFF_SOURCE,
    FLIR_HEADER_SOURCE,
    FLIR_RAW_SOURCE,
    FLIR_GAIN_SOURCE,
    FLIR_CAMERA_SOURCE,
    FLIR_MEAS_SOURCE,
    FLIR_GPS_SOURCE,
    FLIR_IMAGE_TYPE_SOURCE,
    FLIR_PROCESS_MEAS_SOURCE,
    FLIR_PROCESS_SOURCE,
    FLIR_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class FlirMainTagInput:
    tag_id: int
    numerator: int
    denominator: int = 1


@dataclass(frozen=True)
class FlirMetadataRewriteRequest:
    replacement_flir_payload: bytes | None = None
    replacement_raw_thermal_payload: bytes | None = None
    replacement_gps_payload: bytes | None = None
    replacement_main_tags: tuple[FlirMainTagInput, ...] = ()
    delete_flir_directory: bool = False


@dataclass(frozen=True)
class FlirByteRange:
    start: int
    end: int
    reason: str

    def to_json(self) -> JsonObject:
        return {"end": self.end, "reason": self.reason, "start": self.start}


@dataclass(frozen=True)
class FlirMainTagPlan:
    tag_id: int
    tag_name: str
    group0: FlirGroup0
    group2: FlirGroup2
    raw_numerator: int
    raw_denominator: int
    parsed_value: float
    temperature_boundary: FlirTemperatureBoundary
    evidence_anchors: tuple[SourceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "group0": self.group0,
            "group2": self.group2,
            "parsed_value": self.parsed_value,
            "raw_denominator": self.raw_denominator,
            "raw_numerator": self.raw_numerator,
            "tag_id": self.tag_id,
            "tag_name": self.tag_name,
            "temperature_boundary": self.temperature_boundary,
        }


@dataclass(frozen=True)
class FlirMeasurementPlan:
    index: int
    type_code: int
    type_name: str
    params: tuple[int, ...]
    label: str

    def to_json(self) -> JsonObject:
        return {
            "index": self.index,
            "label": self.label,
            "params": json_array(self.params),
            "type_code": self.type_code,
            "type_name": self.type_name,
        }


@dataclass(frozen=True)
class FlirRecordPlan:
    record_index: int
    record_type: int
    record_subtype: int
    record_version: int
    table: FlirTable
    record_name: str
    group0: FlirGroup0
    group2: FlirGroup2
    role: FlirRecordRole
    observed: bool
    preserved: bool
    directory_entry_range: FlirByteRange
    payload_range: FlirByteRange
    payload: bytes
    parsed_tags: JsonObject
    image_type: str | None
    image_width: int | None
    image_height: int | None
    thermal_payload_range: FlirByteRange | None
    measurements: tuple[FlirMeasurementPlan, ...]
    evidence_anchors: tuple[SourceAnchor, ...]

    @property
    def payload_length(self) -> int:
        return self.payload_range.end - self.payload_range.start

    def to_json(self) -> JsonObject:
        thermal_range = (
            self.thermal_payload_range.to_json() if self.thermal_payload_range is not None else None
        )
        return {
            "directory_entry_range": self.directory_entry_range.to_json(),
            "group0": self.group0,
            "group2": self.group2,
            "image_height": self.image_height,
            "image_type": self.image_type,
            "image_width": self.image_width,
            "measurements": json_array(item.to_json() for item in self.measurements),
            "observed": self.observed,
            "parsed_tags": self.parsed_tags,
            "payload_length": self.payload_length,
            "payload_range": self.payload_range.to_json(),
            "payload_sample_hex": self.payload[:32].hex(),
            "preserved": self.preserved,
            "record_index": self.record_index,
            "record_name": self.record_name,
            "record_subtype": self.record_subtype,
            "record_type": self.record_type,
            "record_version": self.record_version,
            "role": self.role,
            "table": self.table,
            "thermal_payload_range": thermal_range,
        }


@dataclass(frozen=True)
class FlirHeaderPlan:
    container_kind: FlirContainerKind
    byte_order: FlirByteOrder
    version: int
    directory_offset: int
    directory_count: int
    creator_software: str
    header_range: FlirByteRange
    evidence_anchors: tuple[SourceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_order": self.byte_order,
            "container_kind": self.container_kind,
            "creator_software": self.creator_software,
            "directory_count": self.directory_count,
            "directory_offset": self.directory_offset,
            "header_range": self.header_range.to_json(),
            "version": self.version,
        }


@dataclass(frozen=True)
class FlirPayloadBoundaryPlan:
    raw_thermal_ranges: tuple[FlirByteRange, ...]
    calibration_ranges: tuple[FlirByteRange, ...]
    camera_info_ranges: tuple[FlirByteRange, ...]
    measurement_info_ranges: tuple[FlirByteRange, ...]
    gps_info_ranges: tuple[FlirByteRange, ...]
    unknown_record_ranges: tuple[FlirByteRange, ...]
    evidence_anchors: tuple[SourceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "calibration_ranges": json_array(item.to_json() for item in self.calibration_ranges),
            "camera_info_ranges": json_array(item.to_json() for item in self.camera_info_ranges),
            "gps_info_ranges": json_array(item.to_json() for item in self.gps_info_ranges),
            "measurement_info_ranges": json_array(
                item.to_json() for item in self.measurement_info_ranges
            ),
            "raw_thermal_ranges": json_array(item.to_json() for item in self.raw_thermal_ranges),
            "unknown_record_ranges": json_array(
                item.to_json() for item in self.unknown_record_ranges
            ),
        }


@dataclass(frozen=True)
class FlirResponsibilityPlan:
    concern: FlirResponsibilityConcern
    reason: str
    evidence_anchors: tuple[SourceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FlirActionPlan:
    kind: FlirActionKind
    byte_range_start: int | None
    byte_range_end: int | None
    input_payload_length: int | None
    planned_payload_length: int | None
    reason: str
    evidence_anchors: tuple[SourceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "input_payload_length": self.input_payload_length,
            "kind": self.kind,
            "planned_payload_length": self.planned_payload_length,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FlirOutputEmissionGate:
    code: FlirEmissionGateCode
    reason: str
    evidence_anchors: tuple[SourceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FlirMetadataTransactionPlan:
    status: FlirPlanStatus
    container_kind: FlirContainerKind
    main_tags: tuple[FlirMainTagPlan, ...]
    header: FlirHeaderPlan | None
    records: tuple[FlirRecordPlan, ...]
    payload_boundaries: FlirPayloadBoundaryPlan
    responsibilities: tuple[FlirResponsibilityPlan, ...]
    actions: tuple[FlirActionPlan, ...]
    output_emission_gates: tuple[FlirOutputEmissionGate, ...]
    evidence_anchors: tuple[SourceAnchor, ...]
    original_bytes: bytes

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def records_by_type(self) -> dict[int, FlirRecordPlan]:
        return {record.record_type: record for record in self.records}

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"FLIR metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> JsonObject:
        header = self.header.to_json() if self.header is not None else None
        return {
            "actions": json_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "container_kind": self.container_kind,
            "header": header,
            "main_tags": json_array(tag.to_json() for tag in self.main_tags),
            "output_emission_gates": json_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "payload_boundaries": self.payload_boundaries.to_json(),
            "records": json_array(record.to_json() for record in self.records),
            "responsibilities": json_array(item.to_json() for item in self.responsibilities),
            "status": self.status,
        }


@dataclass(frozen=True)
class FlirParseResult:
    container_kind: FlirContainerKind
    header: FlirHeaderPlan | None
    records: tuple[FlirRecordPlan, ...]
    gates: tuple[FlirOutputEmissionGate, ...]


@dataclass(frozen=True)
class FlirRecordDefinition:
    table: FlirTable
    name: str
    group0: FlirGroup0
    group2: FlirGroup2
    role: FlirRecordRole
    evidence_anchors: tuple[SourceAnchor, ...]


@dataclass(frozen=True)
class FlirImageParse:
    parsed_tags: JsonObject
    image_type: str | None
    image_width: int | None
    image_height: int | None
    thermal_payload_range: FlirByteRange | None
    gates: tuple[FlirOutputEmissionGate, ...]


def build_flir_metadata_transaction_plan(
    flir_payload: bytes,
    rewrite_request: FlirMetadataRewriteRequest | None = None,
    *,
    main_makernote_tags: tuple[FlirMainTagInput, ...] = (),
    allow_output_emission: bool = False,
) -> FlirMetadataTransactionPlan:
    request = rewrite_request if rewrite_request is not None else FlirMetadataRewriteRequest()
    main_tags = tuple(build_main_tag_plan(item) for item in main_makernote_tags)
    parse = parse_flir_payload(flir_payload)
    boundaries = build_payload_boundary_plan(parse.records)
    responsibilities = build_responsibilities()
    gates = [*parse.gates, *rewrite_gates(request)]
    if not allow_output_emission:
        gates.extend(non_mutating_gates())
    actions = build_actions(flir_payload, main_tags, parse, request)
    status: FlirPlanStatus = "unsupported" if any_validation_gate(tuple(gates)) else "planned"
    sources = unique_evidence_anchors(
        (
            *FLIR_TRANSACTION_EVIDENCE_ANCHORS,
            *(source for tag in main_tags for source in tag.evidence_anchors),
            *(source for record in parse.records for source in record.evidence_anchors),
            *(source for item in responsibilities for source in item.evidence_anchors),
            *(source for action in actions for source in action.evidence_anchors),
            *(source for gate in gates for source in gate.evidence_anchors),
        )
    )
    return FlirMetadataTransactionPlan(
        status=status,
        container_kind=parse.container_kind,
        main_tags=main_tags,
        header=parse.header,
        records=parse.records,
        payload_boundaries=boundaries,
        responsibilities=responsibilities,
        actions=actions,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_anchors=sources,
        original_bytes=flir_payload,
    )


def parse_flir_payload(data: bytes) -> FlirParseResult:
    if not data:
        return FlirParseResult(
            container_kind="none",
            header=None,
            records=(),
            gates=(),
        )
    if len(data) < FLIR_HEADER_SIZE:
        return parse_failure(
            "none",
            "truncated_flir_header",
            "FLIR header is shorter than 64 bytes.",
        )
    signature = data[:4]
    if signature not in {b"FFF\0", b"AFF\0"}:
        return parse_failure("none", "bad_format_flir_data", "FLIR FFF/AFF signature is missing.")
    container_kind: FlirContainerKind = "FFF" if signature == b"FFF\0" else "AFF"
    byte_order = detect_header_byte_order(data[:FLIR_HEADER_SIZE])
    if byte_order is None:
        return parse_failure(
            container_kind,
            "unsupported_flir_version",
            f"Unsupported FLIR {container_kind} version.",
        )
    version = read_u32(data, 0x14, byte_order)
    directory_offset = read_u32(data, 0x18, byte_order)
    directory_count = read_u32(data, 0x1C, byte_order)
    directory_start = directory_offset
    directory_end = directory_start + directory_count * FLIR_RECORD_ENTRY_SIZE
    header = FlirHeaderPlan(
        container_kind=container_kind,
        byte_order=byte_order,
        version=version,
        directory_offset=directory_offset,
        directory_count=directory_count,
        creator_software=read_c_string(data[4:20]),
        header_range=FlirByteRange(
            start=0,
            end=FLIR_HEADER_SIZE,
            reason="FLIR FFF/AFF 64-byte header read by ProcessFLIR.",
        ),
        evidence_anchors=(FLIR_HEADER_SOURCE, FLIR_PROCESS_SOURCE),
    )
    if directory_end > len(data):
        gate = FlirOutputEmissionGate(
            code="truncated_flir_directory",
            reason="FLIR record directory extends beyond available bytes.",
            evidence_anchors=(FLIR_PROCESS_SOURCE,),
        )
        return FlirParseResult(container_kind, header, (), (gate,))
    records: list[FlirRecordPlan] = []
    gates: list[FlirOutputEmissionGate] = []
    for index in range(directory_count):
        entry_start = directory_start + index * FLIR_RECORD_ENTRY_SIZE
        entry = data[entry_start : entry_start + FLIR_RECORD_ENTRY_SIZE]
        record_type = read_u16(entry, 0, byte_order)
        record_subtype = read_u16(entry, 2, byte_order)
        record_version = read_u32(entry, 4, byte_order)
        record_offset = read_u32(entry, 0x0C, byte_order)
        record_length = read_u32(entry, 0x10, byte_order)
        entry_range = FlirByteRange(
            start=entry_start,
            end=entry_start + FLIR_RECORD_ENTRY_SIZE,
            reason="FLIR record directory entry.",
        )
        if record_type == 0:
            records.append(empty_record(index, entry_range, record_subtype, record_version))
            continue
        if record_offset + record_length > len(data):
            gates.append(
                FlirOutputEmissionGate(
                    code="invalid_flir_record",
                    reason=f"FLIR record 0x{record_type:02x} points outside available bytes.",
                    evidence_anchors=(FLIR_PROCESS_SOURCE,),
                )
            )
            continue
        record_parse = build_record_plan(
            data,
            index,
            record_type,
            record_subtype,
            record_version,
            record_offset,
            record_length,
            entry_range,
            byte_order,
        )
        records.append(record_parse.record)
        gates.extend(record_parse.gates)
    return FlirParseResult(
        container_kind=container_kind,
        header=header,
        records=tuple(records),
        gates=tuple(gates),
    )


@dataclass(frozen=True)
class FlirRecordParse:
    record: FlirRecordPlan
    gates: tuple[FlirOutputEmissionGate, ...]


def build_record_plan(
    data: bytes,
    index: int,
    record_type: int,
    record_subtype: int,
    record_version: int,
    record_offset: int,
    record_length: int,
    entry_range: FlirByteRange,
    container_byte_order: FlirByteOrder,
) -> FlirRecordParse:
    payload = data[record_offset : record_offset + record_length]
    definition = record_definition(record_type)
    image_parse = parse_record_payload(definition, payload, record_offset, container_byte_order)
    record = FlirRecordPlan(
        record_index=index,
        record_type=record_type,
        record_subtype=record_subtype,
        record_version=record_version,
        table=definition.table,
        record_name=definition.name,
        group0=definition.group0,
        group2=definition.group2,
        role=definition.role,
        observed=definition.role != "unknown_record",
        preserved=True,
        directory_entry_range=entry_range,
        payload_range=FlirByteRange(
            start=record_offset,
            end=record_offset + record_length,
            reason=f"FLIR payload for {definition.name}.",
        ),
        payload=payload,
        parsed_tags=image_parse.parsed_tags,
        image_type=image_parse.image_type,
        image_width=image_parse.image_width,
        image_height=image_parse.image_height,
        thermal_payload_range=image_parse.thermal_payload_range,
        measurements=parse_measurements(payload, container_byte_order)
        if definition.table == "MeasInfo"
        else (),
        evidence_anchors=definition.evidence_anchors,
    )
    return FlirRecordParse(record=record, gates=image_parse.gates)


def parse_record_payload(
    definition: FlirRecordDefinition,
    payload: bytes,
    payload_offset: int,
    container_byte_order: FlirByteOrder,
) -> FlirImageParse:
    if definition.table == "RawData":
        return parse_image_payload(
            payload,
            payload_offset,
            container_byte_order,
            "RawThermalImage",
            0x20,
            FLIR_RAW_SOURCE,
        )
    if definition.table == "GainDeadData":
        return parse_image_payload(
            payload,
            payload_offset,
            container_byte_order,
            "GainDeadMapImage",
            0x20,
            FLIR_GAIN_SOURCE,
        )
    if definition.table == "CoarseData":
        return parse_image_payload(
            payload,
            payload_offset,
            container_byte_order,
            "CoarseMapImage",
            0x20,
            FLIR_GAIN_SOURCE,
        )
    if definition.table == "EmbeddedImage":
        return parse_image_payload(
            payload,
            payload_offset,
            container_byte_order,
            "EmbeddedImage",
            0x20,
            FLIR_IMAGE_TYPE_SOURCE,
        )
    if definition.table == "CameraInfo":
        return FlirImageParse(
            parsed_tags=parse_camera_info(payload, container_byte_order),
            image_type=None,
            image_width=None,
            image_height=None,
            thermal_payload_range=None,
            gates=(),
        )
    if definition.table == "PaletteInfo":
        return FlirImageParse(
            parsed_tags=parse_palette_info(payload, container_byte_order),
            image_type=None,
            image_width=None,
            image_height=None,
            thermal_payload_range=None,
            gates=(),
        )
    if definition.table == "GPSInfo":
        return FlirImageParse(
            parsed_tags=parse_gps_info(payload, container_byte_order),
            image_type=None,
            image_width=None,
            image_height=None,
            thermal_payload_range=None,
            gates=(),
        )
    return FlirImageParse(
        parsed_tags={},
        image_type=None,
        image_width=None,
        image_height=None,
        thermal_payload_range=None,
        gates=(),
    )


def parse_image_payload(
    payload: bytes,
    payload_offset: int,
    container_byte_order: FlirByteOrder,
    image_name: str,
    image_data_offset: int,
    source: SourceAnchor,
) -> FlirImageParse:
    if len(payload) < image_data_offset:
        gate = FlirOutputEmissionGate(
            code="truncated_flir_record_payload",
            reason=f"{image_name} record is shorter than its image-data boundary.",
            evidence_anchors=(source, FLIR_IMAGE_TYPE_SOURCE),
        )
        return FlirImageParse({}, None, None, None, None, (gate,))
    local_byte_order = image_record_byte_order(payload, container_byte_order)
    width = read_u16(payload, 2, local_byte_order) if len(payload) >= 4 else 0
    height = read_u16(payload, 4, local_byte_order) if len(payload) >= 6 else 0
    image_data = payload[image_data_offset:]
    image_type = image_payload_type(image_data, width, height, local_byte_order)
    thermal_range = FlirByteRange(
        start=payload_offset + image_data_offset,
        end=payload_offset + len(payload),
        reason=f"Opaque {image_name} bytes preserved exactly.",
    )
    parsed_tags: JsonObject = {
        f"{image_name}Height": height,
        image_name: True,
        f"{image_name}Type": image_type,
        f"{image_name}Width": width,
    }
    gates: tuple[FlirOutputEmissionGate, ...] = ()
    known_magic = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")
    if image_type == "DAT" and image_data and not image_data.startswith(known_magic):
        gates = (
            FlirOutputEmissionGate(
                code="unrecognized_thermal_payload",
                reason=f"{image_name} payload is not PNG/JPG and does not match raw dimensions.",
                evidence_anchors=(source, FLIR_IMAGE_TYPE_SOURCE),
            ),
        )
    return FlirImageParse(
        parsed_tags=parsed_tags,
        image_type=image_type,
        image_width=width,
        image_height=height,
        thermal_payload_range=thermal_range,
        gates=gates,
    )


def parse_camera_info(payload: bytes, byte_order: FlirByteOrder) -> JsonObject:
    local_byte_order = image_record_byte_order(payload, byte_order)
    tags: JsonObject = {}
    add_float_tag(tags, payload, 0x20, local_byte_order, "Emissivity")
    add_float_tag(tags, payload, 0x24, local_byte_order, "ObjectDistance")
    add_kelvin_tag(tags, payload, 0x28, local_byte_order, "ReflectedApparentTemperature")
    add_kelvin_tag(tags, payload, 0x2C, local_byte_order, "AtmosphericTemperature")
    add_kelvin_tag(tags, payload, 0x30, local_byte_order, "IRWindowTemperature")
    add_float_tag(tags, payload, 0x34, local_byte_order, "IRWindowTransmission")
    if len(payload) >= 0x40:
        humidity = read_float(payload, 0x3C, local_byte_order)
        tags["RelativeHumidity"] = humidity / 100 if humidity > 2 else humidity
    add_float_tag(tags, payload, 0x58, local_byte_order, "PlanckR1")
    add_float_tag(tags, payload, 0x5C, local_byte_order, "PlanckB")
    add_float_tag(tags, payload, 0x60, local_byte_order, "PlanckF")
    add_float_tag(tags, payload, 0x70, local_byte_order, "AtmosphericTransAlpha1")
    add_float_tag(tags, payload, 0x74, local_byte_order, "AtmosphericTransAlpha2")
    add_float_tag(tags, payload, 0x78, local_byte_order, "AtmosphericTransBeta1")
    add_float_tag(tags, payload, 0x7C, local_byte_order, "AtmosphericTransBeta2")
    add_float_tag(tags, payload, 0x80, local_byte_order, "AtmosphericTransX")
    add_kelvin_tag(tags, payload, 0x90, local_byte_order, "CameraTemperatureRangeMax")
    add_kelvin_tag(tags, payload, 0x94, local_byte_order, "CameraTemperatureRangeMin")
    add_kelvin_tag(tags, payload, 0x98, local_byte_order, "CameraTemperatureMaxClip")
    add_kelvin_tag(tags, payload, 0x9C, local_byte_order, "CameraTemperatureMinClip")
    add_kelvin_tag(tags, payload, 0xA0, local_byte_order, "CameraTemperatureMaxWarn")
    add_kelvin_tag(tags, payload, 0xA4, local_byte_order, "CameraTemperatureMinWarn")
    add_kelvin_tag(tags, payload, 0xA8, local_byte_order, "CameraTemperatureMaxSaturated")
    add_kelvin_tag(tags, payload, 0xAC, local_byte_order, "CameraTemperatureMinSaturated")
    add_string_tag(tags, payload, 0xD4, 32, "CameraModel")
    add_string_tag(tags, payload, 0xF4, 16, "CameraPartNumber")
    add_string_tag(tags, payload, 0x104, 16, "CameraSerialNumber")
    add_string_tag(tags, payload, 0x114, 16, "CameraSoftware")
    add_string_tag(tags, payload, 0x170, 32, "LensModel")
    add_string_tag(tags, payload, 0x190, 16, "LensPartNumber")
    add_string_tag(tags, payload, 0x1A0, 16, "LensSerialNumber")
    add_float_tag(tags, payload, 0x1B4, local_byte_order, "FieldOfView")
    add_string_tag(tags, payload, 0x1EC, 16, "FilterModel")
    add_string_tag(tags, payload, 0x1FC, 32, "FilterPartNumber")
    add_string_tag(tags, payload, 0x21C, 32, "FilterSerialNumber")
    if len(payload) >= 0x30C:
        tags["PlanckO"] = read_i32(payload, 0x308, local_byte_order)
    add_float_tag(tags, payload, 0x30C, local_byte_order, "PlanckR2")
    add_u16_tag(tags, payload, 0x310, local_byte_order, "RawValueRangeMin")
    add_u16_tag(tags, payload, 0x312, local_byte_order, "RawValueRangeMax")
    add_u16_tag(tags, payload, 0x338, local_byte_order, "RawValueMedian")
    add_u16_tag(tags, payload, 0x33C, local_byte_order, "RawValueRange")
    add_flir_datetime_tag(tags, payload, 0x384, local_byte_order, "DateTimeOriginal")
    add_u16_tag(tags, payload, 0x390, local_byte_order, "FocusStepCount")
    add_float_tag(tags, payload, 0x45C, local_byte_order, "FocusDistance")
    add_u16_tag(tags, payload, 0x464, local_byte_order, "FrameRate")
    return tags


def parse_palette_info(payload: bytes, byte_order: FlirByteOrder) -> JsonObject:
    local_byte_order = image_record_byte_order(payload, byte_order)
    tags: JsonObject = {}
    add_u16_tag(tags, payload, 0x00, local_byte_order, "PaletteColors")
    for offset, name in (
        (0x06, "AboveColor"),
        (0x09, "BelowColor"),
        (0x0C, "OverflowColor"),
        (0x0F, "UnderflowColor"),
        (0x12, "Isotherm1Color"),
        (0x15, "Isotherm2Color"),
    ):
        if len(payload) >= offset + 3:
            tags[name] = [payload[offset], payload[offset + 1], payload[offset + 2]]
    add_u8_tag(tags, payload, 0x1A, "PaletteMethod")
    add_u8_tag(tags, payload, 0x1B, "PaletteStretch")
    add_printable_string_tag(tags, payload, 0x30, 32, "PaletteFileName")
    add_printable_string_tag(tags, payload, 0x50, 32, "PaletteName")
    if isinstance(tags.get("PaletteColors"), int):
        tags["Palette"] = True
    return tags


def parse_gps_info(payload: bytes, byte_order: FlirByteOrder) -> JsonObject:
    tags: JsonObject = {}
    if len(payload) < 4:
        return tags
    valid = read_u32(payload, 0, byte_order)
    tags["GPSValid"] = valid
    add_string_tag(tags, payload, 0x08, 2, "GPSLatitudeRef")
    add_string_tag(tags, payload, 0x0A, 2, "GPSLongitudeRef")
    if valid:
        if len(payload) >= 0x18:
            tags["GPSLatitude"] = read_double(payload, 0x10, byte_order)
        if len(payload) >= 0x20:
            tags["GPSLongitude"] = read_double(payload, 0x18, byte_order)
        add_float_tag(tags, payload, 0x20, byte_order, "GPSAltitude")
    add_float_tag(tags, payload, 0x40, byte_order, "GPSDOP")
    add_string_tag(tags, payload, 0x44, 2, "GPSSpeedRef")
    add_string_tag(tags, payload, 0x46, 2, "GPSTrackRef")
    add_string_tag(tags, payload, 0x48, 2, "GPSImgDirectionRef")
    add_float_tag(tags, payload, 0x4C, byte_order, "GPSSpeed")
    add_float_tag(tags, payload, 0x50, byte_order, "GPSTrack")
    add_float_tag(tags, payload, 0x54, byte_order, "GPSImgDirection")
    add_string_tag(tags, payload, 0x58, 16, "GPSMapDatum")
    return tags


def parse_measurements(
    payload: bytes,
    byte_order: FlirByteOrder,
) -> tuple[FlirMeasurementPlan, ...]:
    if len(payload) < 12:
        return ()
    local_byte_order = image_record_byte_order(payload, byte_order)
    pos = 12
    measurements: list[FlirMeasurementPlan] = []
    while pos + 2 <= len(payload):
        record_length = read_u16(payload, pos, local_byte_order)
        if record_length < 0x28 or pos + record_length > len(payload):
            break
        coord_length = read_u16(payload, pos + 4, local_byte_order)
        type_code = read_u16(payload, pos + 0x0A, local_byte_order)
        params_start = pos + 0x24
        params_end = min(params_start + coord_length, pos + record_length)
        params = tuple(
            read_u16(payload, offset, local_byte_order)
            for offset in range(params_start, params_end - 1, 2)
        )
        label = read_measurement_label(payload, params_end, pos + record_length, local_byte_order)
        measurements.append(
            FlirMeasurementPlan(
                index=len(measurements) + 1,
                type_code=type_code,
                type_name=MEASUREMENT_TYPE_NAMES.get(type_code, "Unknown"),
                params=params,
                label=label,
            )
        )
        pos += record_length
    return tuple(measurements)


def build_main_tag_plan(tag: FlirMainTagInput) -> FlirMainTagPlan:
    name = MAIN_TAG_NAMES.get(tag.tag_id, f"UnknownFLIRMain0x{tag.tag_id:02x}")
    parsed = tag.numerator / tag.denominator
    boundary: FlirTemperatureBoundary = "not_temperature"
    if tag.tag_id in {0x01, 0x02, 0x04, 0x05, 0x06}:
        boundary = "unit_ambiguous_rational_temperature"
    return FlirMainTagPlan(
        tag_id=tag.tag_id,
        tag_name=name,
        group0="MakerNotes",
        group2="Camera",
        raw_numerator=tag.numerator,
        raw_denominator=tag.denominator,
        parsed_value=parsed,
        temperature_boundary=boundary,
        evidence_anchors=(FLIR_MAIN_SOURCE,),
    )


def build_payload_boundary_plan(records: tuple[FlirRecordPlan, ...]) -> FlirPayloadBoundaryPlan:
    raw_ranges = tuple(
        record.thermal_payload_range
        for record in records
        if record.role == "raw_thermal_payload" and record.thermal_payload_range is not None
    )
    calibration_ranges = tuple(
        record.thermal_payload_range
        for record in records
        if record.role == "calibration_payload" and record.thermal_payload_range is not None
    )
    return FlirPayloadBoundaryPlan(
        raw_thermal_ranges=raw_ranges,
        calibration_ranges=calibration_ranges,
        camera_info_ranges=tuple(
            record.payload_range for record in records if record.role == "camera_metadata"
        ),
        measurement_info_ranges=tuple(
            record.payload_range for record in records if record.role == "measurement_metadata"
        ),
        gps_info_ranges=tuple(
            record.payload_range for record in records if record.role == "gps_subdirectory"
        ),
        unknown_record_ranges=tuple(
            record.payload_range for record in records if record.role == "unknown_record"
        ),
        evidence_anchors=(
            FLIR_FFF_SOURCE,
            FLIR_RAW_SOURCE,
            FLIR_GAIN_SOURCE,
            FLIR_CAMERA_SOURCE,
            FLIR_MEAS_SOURCE,
            FLIR_GPS_SOURCE,
            FLIR_PROCESS_SOURCE,
        ),
    )


def build_actions(
    flir_payload: bytes,
    main_tags: tuple[FlirMainTagPlan, ...],
    parse: FlirParseResult,
    request: FlirMetadataRewriteRequest,
) -> tuple[FlirActionPlan, ...]:
    actions: list[FlirActionPlan] = []
    for tag in main_tags:
        actions.append(
            FlirActionPlan(
                kind="route_main_makernote_tag",
                byte_range_start=None,
                byte_range_end=None,
                input_payload_length=None,
                planned_payload_length=None,
                reason=f"Route FLIR Main maker-note tag {tag.tag_name}.",
                evidence_anchors=tag.evidence_anchors,
            )
        )
    if parse.header is not None:
        actions.append(
            FlirActionPlan(
                kind="validate_fff_header",
                byte_range_start=parse.header.header_range.start,
                byte_range_end=parse.header.header_range.end,
                input_payload_length=FLIR_HEADER_SIZE,
                planned_payload_length=FLIR_HEADER_SIZE,
                reason=f"Validate and preserve the FLIR {parse.container_kind} header.",
                evidence_anchors=(FLIR_HEADER_SOURCE, FLIR_PROCESS_SOURCE),
            )
        )
    for record in parse.records:
        actions.append(record_action(record))
    if has_rewrite_request(request):
        actions.append(
            FlirActionPlan(
                kind="block_requested_rewrite",
                byte_range_start=0,
                byte_range_end=len(flir_payload),
                input_payload_length=len(flir_payload),
                planned_payload_length=None,
                reason="Requested FLIR byte changes are recorded only as blocked work.",
                evidence_anchors=(FLIR_READ_ONLY_SOURCE,),
            )
        )
    actions.append(
        FlirActionPlan(
            kind="no_metadata_mutation",
            byte_range_start=0,
            byte_range_end=len(flir_payload),
            input_payload_length=len(flir_payload),
            planned_payload_length=len(flir_payload),
            reason="The FLIR planner preserves source bytes and does not rewrite metadata.",
            evidence_anchors=(FLIR_READ_ONLY_SOURCE,),
        )
    )
    return tuple(actions)


def record_action(record: FlirRecordPlan) -> FlirActionPlan:
    kind: FlirActionKind = "route_fff_record"
    if record.role == "raw_thermal_payload":
        kind = "preserve_raw_thermal_payload"
    elif record.role == "calibration_payload":
        kind = "preserve_calibration_payload"
    elif record.role == "camera_metadata":
        kind = "parse_camera_info_boundary"
    elif record.role == "measurement_metadata":
        kind = "parse_measurement_info_boundary"
    elif record.role == "gps_subdirectory":
        kind = "route_gps_subdirectory"
    elif record.role == "unknown_record":
        kind = "preserve_unknown_record"
    elif record.role == "empty_record":
        kind = "skip_empty_record"
    return FlirActionPlan(
        kind=kind,
        byte_range_start=record.payload_range.start,
        byte_range_end=record.payload_range.end,
        input_payload_length=record.payload_length,
        planned_payload_length=record.payload_length,
        reason=f"Preserve FLIR record payload for {record.record_name}.",
        evidence_anchors=record.evidence_anchors,
    )


def build_responsibilities() -> tuple[FlirResponsibilityPlan, ...]:
    return (
        FlirResponsibilityPlan(
            concern="main_makernote_routing",
            reason="Route FLIR Main maker-note temperature and emissivity fields.",
            evidence_anchors=(FLIR_MAIN_SOURCE,),
        ),
        FlirResponsibilityPlan(
            concern="fff_header_table_routing",
            reason="Validate the FFF/AFF header and route record directory entries.",
            evidence_anchors=(FLIR_FFF_SOURCE, FLIR_PROCESS_SOURCE),
        ),
        FlirResponsibilityPlan(
            concern="raw_gain_camera_measurement_boundaries",
            reason=(
                "Keep RawData, GainDeadData, CameraInfo, and MeasInfo responsibilities separate."
            ),
            evidence_anchors=(
                FLIR_RAW_SOURCE,
                FLIR_GAIN_SOURCE,
                FLIR_CAMERA_SOURCE,
                FLIR_MEAS_SOURCE,
            ),
        ),
        FlirResponsibilityPlan(
            concern="temperature_conversion_boundaries",
            reason=(
                "Record unit-ambiguous Main temperatures and Kelvin-to-Celsius CameraInfo reads."
            ),
            evidence_anchors=(FLIR_MAIN_SOURCE, FLIR_CAMERA_SOURCE),
        ),
        FlirResponsibilityPlan(
            concern="gps_exif_subdirectory_boundaries",
            reason=(
                "Preserve FLIR maker-note/APP1 boundaries and route GPSInfo as Location metadata."
            ),
            evidence_anchors=(FLIR_MAIN_SOURCE, FLIR_GPS_SOURCE),
        ),
        FlirResponsibilityPlan(
            concern="thermal_image_payload_preservation",
            reason=(
                "Preserve raw thermal image bytes exactly instead of emitting TIFF/PNG rewrites."
            ),
            evidence_anchors=(FLIR_RAW_SOURCE, FLIR_IMAGE_TYPE_SOURCE),
        ),
        FlirResponsibilityPlan(
            concern="unknown_record_preservation",
            reason="Keep unknown FLIR record payloads even when no source table route exists.",
            evidence_anchors=(FLIR_PROCESS_SOURCE,),
        ),
        FlirResponsibilityPlan(
            concern="malformed_truncation_blockers",
            reason="Surface bad signatures, unsupported versions, and truncated records as gates.",
            evidence_anchors=(FLIR_PROCESS_SOURCE,),
        ),
        FlirResponsibilityPlan(
            concern="unsupported_rewrite_gates",
            reason="Block rewrites because this slice ports FLIR.pm read planning only.",
            evidence_anchors=(FLIR_READ_ONLY_SOURCE,),
        ),
    )


def rewrite_gates(request: FlirMetadataRewriteRequest) -> tuple[FlirOutputEmissionGate, ...]:
    gates: list[FlirOutputEmissionGate] = []
    if request.replacement_flir_payload is not None:
        gates.append(
            FlirOutputEmissionGate(
                code="flir_payload_rewrite_required",
                reason="Replacing a FLIR FFF/AFF payload requires a source-backed writer.",
                evidence_anchors=(FLIR_PROCESS_SOURCE, FLIR_READ_ONLY_SOURCE),
            )
        )
    if request.delete_flir_directory:
        gates.append(
            FlirOutputEmissionGate(
                code="flir_directory_delete_required",
                reason="Deleting FLIR metadata is outside FLIR.pm read behavior.",
                evidence_anchors=(FLIR_FFF_SOURCE, FLIR_READ_ONLY_SOURCE),
            )
        )
    if request.replacement_main_tags:
        gates.append(
            FlirOutputEmissionGate(
                code="flir_main_rewrite_required",
                reason="Main maker-note writes are not implemented by this transaction planner.",
                evidence_anchors=(FLIR_MAIN_SOURCE, FLIR_READ_ONLY_SOURCE),
            )
        )
    if request.replacement_raw_thermal_payload is not None:
        gates.append(
            FlirOutputEmissionGate(
                code="flir_raw_thermal_rewrite_required",
                reason="Raw thermal image replacement is not implemented for FLIR metadata.",
                evidence_anchors=(FLIR_RAW_SOURCE, FLIR_IMAGE_TYPE_SOURCE, FLIR_READ_ONLY_SOURCE),
            )
        )
    if request.replacement_gps_payload is not None:
        gates.append(
            FlirOutputEmissionGate(
                code="flir_gps_rewrite_required",
                reason="FLIR GPSInfo replacement is not implemented by this planner.",
                evidence_anchors=(FLIR_GPS_SOURCE, FLIR_READ_ONLY_SOURCE),
            )
        )
    return tuple(gates)


def non_mutating_gates() -> tuple[FlirOutputEmissionGate, ...]:
    return (
        FlirOutputEmissionGate(
            code="planner_is_non_mutating",
            reason="FLIR metadata transaction plans require explicit output emission approval.",
            evidence_anchors=(FLIR_READ_ONLY_SOURCE,),
        ),
        FlirOutputEmissionGate(
            code="full_flir_writer_not_implemented",
            reason="This slice ports FLIR.pm read planning only; no FLIR writer is emitted.",
            evidence_anchors=(FLIR_READ_ONLY_SOURCE,),
        ),
    )


def parse_failure(
    container_kind: FlirContainerKind,
    code: FlirEmissionGateCode,
    reason: str,
) -> FlirParseResult:
    gate = FlirOutputEmissionGate(
        code=code,
        reason=reason,
        evidence_anchors=(FLIR_PROCESS_SOURCE,),
    )
    return FlirParseResult(container_kind=container_kind, header=None, records=(), gates=(gate,))


def any_validation_gate(gates: tuple[FlirOutputEmissionGate, ...]) -> bool:
    validation_codes: set[FlirEmissionGateCode] = {
        "bad_format_flir_data",
        "truncated_flir_header",
        "unsupported_flir_version",
        "truncated_flir_directory",
        "invalid_flir_record",
        "truncated_flir_record_payload",
        "unrecognized_thermal_payload",
    }
    return any(gate.code in validation_codes for gate in gates)


def has_rewrite_request(request: FlirMetadataRewriteRequest) -> bool:
    return (
        request.replacement_flir_payload is not None
        or request.replacement_raw_thermal_payload is not None
        or request.replacement_gps_payload is not None
        or bool(request.replacement_main_tags)
        or request.delete_flir_directory
    )


def detect_header_byte_order(header: bytes) -> FlirByteOrder | None:
    big_version = read_u32(header, 0x14, "big")
    if 100 <= big_version < 200:
        return "big"
    little_version = read_u32(header, 0x14, "little")
    if 100 <= little_version < 200:
        return "little"
    return None


def image_record_byte_order(payload: bytes, fallback: FlirByteOrder) -> FlirByteOrder:
    if len(payload) < 2:
        return fallback
    return opposite_byte_order(fallback) if read_u16(payload, 0, fallback) >= 0x0100 else fallback


def opposite_byte_order(byte_order: FlirByteOrder) -> FlirByteOrder:
    return "little" if byte_order == "big" else "big"


def image_payload_type(
    image_data: bytes,
    width: int,
    height: int,
    byte_order: FlirByteOrder,
) -> str:
    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if image_data.startswith(b"\xff\xd8\xff"):
        return "JPG"
    raw_image_size = width * height * 2
    if width > 0 and height > 0 and len(image_data) == raw_image_size and byte_order == "little":
        return "TIFF"
    return "DAT"


def empty_record(
    index: int,
    entry_range: FlirByteRange,
    record_subtype: int,
    record_version: int,
) -> FlirRecordPlan:
    return FlirRecordPlan(
        record_index=index,
        record_type=0,
        record_subtype=record_subtype,
        record_version=record_version,
        table="Unknown",
        record_name="Empty",
        group0="APP1",
        group2="Unknown",
        role="empty_record",
        observed=False,
        preserved=True,
        directory_entry_range=entry_range,
        payload_range=FlirByteRange(
            start=entry_range.end,
            end=entry_range.end,
            reason="Empty record.",
        ),
        payload=b"",
        parsed_tags={},
        image_type=None,
        image_width=None,
        image_height=None,
        thermal_payload_range=None,
        measurements=(),
        evidence_anchors=(FLIR_PROCESS_SOURCE,),
    )


def record_definition(record_type: int) -> FlirRecordDefinition:
    definition = RECORD_DEFINITIONS.get(record_type)
    if definition is not None:
        return definition
    return FlirRecordDefinition(
        table="Unknown",
        name=f"UnknownRecord0x{record_type:02x}",
        group0="APP1",
        group2="Unknown",
        role="unknown_record",
        evidence_anchors=(FLIR_PROCESS_SOURCE,),
    )


def read_u16(data: bytes, offset: int, byte_order: FlirByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 2], byte_order, signed=False)


def read_u32(data: bytes, offset: int, byte_order: FlirByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order, signed=False)


def read_i32(data: bytes, offset: int, byte_order: FlirByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order, signed=True)


def read_float(data: bytes, offset: int, byte_order: FlirByteOrder) -> float:
    marker = ">" if byte_order == "big" else "<"
    value: float = struct.unpack(f"{marker}f", data[offset : offset + 4])[0]
    return value


def read_double(data: bytes, offset: int, byte_order: FlirByteOrder) -> float:
    marker = ">" if byte_order == "big" else "<"
    value: float = struct.unpack(f"{marker}d", data[offset : offset + 8])[0]
    return value


def add_float_tag(
    tags: JsonObject,
    payload: bytes,
    offset: int,
    byte_order: FlirByteOrder,
    name: str,
) -> None:
    if len(payload) >= offset + 4:
        tags[name] = read_float(payload, offset, byte_order)


def add_u8_tag(tags: JsonObject, payload: bytes, offset: int, name: str) -> None:
    if len(payload) > offset:
        tags[name] = payload[offset]


def add_u16_tag(
    tags: JsonObject,
    payload: bytes,
    offset: int,
    byte_order: FlirByteOrder,
    name: str,
) -> None:
    if len(payload) >= offset + 2:
        tags[name] = read_u16(payload, offset, byte_order)


def add_kelvin_tag(
    tags: JsonObject,
    payload: bytes,
    offset: int,
    byte_order: FlirByteOrder,
    name: str,
) -> None:
    if len(payload) >= offset + 4:
        tags[name] = read_float(payload, offset, byte_order) - 273.15


def add_string_tag(
    tags: JsonObject,
    payload: bytes,
    offset: int,
    size: int,
    name: str,
) -> None:
    if len(payload) >= offset + size:
        value = read_c_string(payload[offset : offset + size])
        tags[name] = value


def add_flir_datetime_tag(
    tags: JsonObject,
    payload: bytes,
    offset: int,
    byte_order: FlirByteOrder,
    name: str,
) -> None:
    if len(payload) < offset + 10:
        return
    timestamp = read_u32(payload, offset, byte_order)
    subseconds = read_u32(payload, offset + 4, byte_order) & 0xFFFF
    timezone_minutes = int.from_bytes(payload[offset + 8 : offset + 10], byte_order, signed=True)
    utc_seconds = timestamp - timezone_minutes * 60
    offset_minutes = -timezone_minutes
    sign = "+" if offset_minutes >= 0 else "-"
    absolute_offset = abs(offset_minutes)
    tags[name] = (
        time.strftime("%Y:%m:%d %H:%M:%S", time.gmtime(utc_seconds))
        + f".{subseconds:03d}{sign}{absolute_offset // 60:02d}:{absolute_offset % 60:02d}"
    )


def add_printable_string_tag(
    tags: JsonObject,
    payload: bytes,
    offset: int,
    size: int,
    name: str,
) -> None:
    if len(payload) < offset + size:
        return
    value = read_c_string(payload[offset : offset + size])
    if 3 <= len(value) <= 31 and all(0x20 <= ord(char) <= 0x7E for char in value):
        tags[name] = value


def read_c_string(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("latin-1")


def read_measurement_label(
    payload: bytes,
    start: int,
    end: int,
    byte_order: FlirByteOrder,
) -> str:
    chars: list[str] = []
    for offset in range(start, end - 1, 2):
        code = read_u16(payload, offset, byte_order)
        if code < 0x20 or code > 0x7F:
            break
        chars.append(chr(code))
    return "".join(chars)


def evidence_anchors_to_json(references: tuple[SourceAnchor, ...]) -> JsonArray:
    return json_array(
        {
            "evidence": reference.evidence,
            "evidence_id": reference.evidence_id,
            "line_end": reference.line_end,
            "line_start": reference.line_start,
            "path": reference.path,
            "symbol": reference.symbol,
        }
        for reference in references
    )


def json_array(values: Iterable[JsonValue]) -> JsonArray:
    return [value for value in values]


def unique_evidence_anchors(references: Iterable[SourceAnchor]) -> tuple[SourceAnchor, ...]:
    seen: set[tuple[str, str, int, int, str]] = set()
    unique: list[SourceAnchor] = []
    for reference in references:
        key = (
            reference.evidence_id,
            reference.path,
            reference.line_start,
            reference.line_end,
            reference.symbol,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return tuple(unique)


def unique_gates(
    gates: tuple[FlirOutputEmissionGate, ...],
) -> tuple[FlirOutputEmissionGate, ...]:
    seen: set[FlirEmissionGateCode] = set()
    unique: list[FlirOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


MAIN_TAG_NAMES: dict[int, str] = {
    0x01: "ImageTemperatureMax",
    0x02: "ImageTemperatureMin",
    0x03: "Emissivity",
    0x04: "UnknownTemperature",
    0x05: "CameraTemperatureRangeMax",
    0x06: "CameraTemperatureRangeMin",
}

MEASUREMENT_TYPE_NAMES: dict[int, str] = {
    1: "Spot",
    2: "Area",
    3: "Ellipse",
    4: "Line",
    5: "Endpoint",
    6: "Alarm",
    7: "Unused",
    8: "Difference",
}

RECORD_DEFINITIONS: dict[int, FlirRecordDefinition] = {
    0x01: FlirRecordDefinition(
        table="RawData",
        name="RawData",
        group0="APP1",
        group2="Image",
        role="raw_thermal_payload",
        evidence_anchors=(FLIR_FFF_SOURCE, FLIR_RAW_SOURCE, FLIR_IMAGE_TYPE_SOURCE),
    ),
    0x05: FlirRecordDefinition(
        table="GainDeadData",
        name="GainDeadData",
        group0="APP1",
        group2="Image",
        role="calibration_payload",
        evidence_anchors=(FLIR_FFF_SOURCE, FLIR_GAIN_SOURCE, FLIR_IMAGE_TYPE_SOURCE),
    ),
    0x06: FlirRecordDefinition(
        table="CoarseData",
        name="CoarseData",
        group0="APP1",
        group2="Image",
        role="calibration_payload",
        evidence_anchors=(FLIR_FFF_SOURCE, FLIR_GAIN_SOURCE, FLIR_IMAGE_TYPE_SOURCE),
    ),
    0x0E: FlirRecordDefinition(
        table="EmbeddedImage",
        name="EmbeddedImage",
        group0="APP1",
        group2="Preview",
        role="embedded_image_payload",
        evidence_anchors=(FLIR_FFF_SOURCE, FLIR_IMAGE_TYPE_SOURCE),
    ),
    0x20: FlirRecordDefinition(
        table="CameraInfo",
        name="CameraInfo",
        group0="APP1",
        group2="Camera",
        role="camera_metadata",
        evidence_anchors=(FLIR_FFF_SOURCE, FLIR_CAMERA_SOURCE),
    ),
    0x21: FlirRecordDefinition(
        table="MeasInfo",
        name="MeasurementInfo",
        group0="APP1",
        group2="Image",
        role="measurement_metadata",
        evidence_anchors=(FLIR_FFF_SOURCE, FLIR_MEAS_SOURCE, FLIR_PROCESS_MEAS_SOURCE),
    ),
    0x22: FlirRecordDefinition(
        table="PaletteInfo",
        name="PaletteInfo",
        group0="APP1",
        group2="Image",
        role="table_routed_payload",
        evidence_anchors=(FLIR_FFF_SOURCE,),
    ),
    0x23: FlirRecordDefinition(
        table="TextInfo",
        name="TextInfo",
        group0="APP1",
        group2="Image",
        role="table_routed_payload",
        evidence_anchors=(FLIR_FFF_SOURCE,),
    ),
    0x28: FlirRecordDefinition(
        table="PaintData",
        name="PaintData",
        group0="APP1",
        group2="Image",
        role="table_routed_payload",
        evidence_anchors=(FLIR_FFF_SOURCE,),
    ),
    0x2A: FlirRecordDefinition(
        table="PiP",
        name="PiP",
        group0="APP1",
        group2="Image",
        role="table_routed_payload",
        evidence_anchors=(FLIR_FFF_SOURCE,),
    ),
    0x2B: FlirRecordDefinition(
        table="GPSInfo",
        name="GPSInfo",
        group0="APP1",
        group2="Location",
        role="gps_subdirectory",
        evidence_anchors=(FLIR_FFF_SOURCE, FLIR_GPS_SOURCE),
    ),
    0x2C: FlirRecordDefinition(
        table="MeterLink",
        name="MeterLink",
        group0="APP1",
        group2="Image",
        role="table_routed_payload",
        evidence_anchors=(FLIR_FFF_SOURCE,),
    ),
    0x2E: FlirRecordDefinition(
        table="ParamInfo",
        name="ParameterInfo",
        group0="APP1",
        group2="Image",
        role="table_routed_payload",
        evidence_anchors=(FLIR_FFF_SOURCE,),
    ),
}
