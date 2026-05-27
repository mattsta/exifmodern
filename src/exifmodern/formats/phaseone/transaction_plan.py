"""Source-grounded Phase One maker-note transaction planning."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

PHASEONE_HEADER_SIZE = 12
PHASEONE_DIRECTORY_PREFIX_SIZE = 8
PHASEONE_MAIN_ENTRY_SIZE = 16
PHASEONE_SENSOR_ENTRY_SIZE = 12
PHASEONE_INLINE_VALUE_SIZE = 4
PHASEONE_MAX_ENTRY_COUNT = 300
PHASEONE_MAX_VALUE_SIZE = 0x7FFFFFFF

type PhaseOneByteOrder = Literal["little", "big"]
type PhaseOneTableKind = Literal["main", "sensor_calibration"]
type PhaseOnePlanStatus = Literal["planned", "unsupported"]
type PhaseOneFormatName = Literal[
    "string",
    "int16s",
    "int16u",
    "int32s",
    "int32u",
    "float",
    "double",
    "undef",
]
type PhaseOneGroup2 = Literal["Camera", "Time"]
type PhaseOneTagRoute = Literal["main_table", "sensor_calibration_subdirectory"]
type PhaseOneValueClass = Literal[
    "writable_scalar",
    "read_only_image_data",
    "read_only_subdirectory",
    "read_only_source_value",
    "hidden_unknown_source_value",
    "binary_source_value",
    "unknown_preserved",
]
type PhaseOneActionKind = Literal[
    "route_main_table",
    "route_sensor_calibration_table",
    "extract_source_tag",
    "preserve_binary_payload",
    "preserve_image_data",
    "preserve_unknown_tag",
    "preserve_hidden_unknown_tag",
    "route_sensor_calibration_subdirectory",
    "block_requested_rewrite",
]
type PhaseOneGateCode = Literal[
    "truncated_phaseone_header",
    "unrecognized_phaseone_header",
    "truncated_phaseone_ifd_prefix",
    "invalid_phaseone_entry_count",
    "truncated_phaseone_entry_table",
    "invalid_phaseone_value_size",
    "truncated_phaseone_value",
    "unknown_rewrite_tag",
    "missing_source_tag_for_rewrite",
    "read_only_rewrite_tag",
    "duplicate_rewrite_tag",
    "phaseone_rewrite_requires_full_directory_rebuild",
    "non_mutating_plan_requires_explicit_emission",
]
type PhaseOneRawValue = str | int | float | tuple[int, ...] | tuple[float, ...] | bytes | None


def evidence_anchor(
    _line_start: int,
    _line_end: int,
    symbol: str,
    _evidence: str,
) -> str:
    return f"phaseone.{symbol}"


PHASEONE_FORMAT_SOURCE = evidence_anchor(
    23,
    24,
    "@formatName",
    "Main entries map Phase One format-size codes to string, int16s, and int32s defaults.",
)
PHASEONE_MAIN_SOURCE = evidence_anchor(
    27,
    35,
    "%Image::ExifTool::PhaseOne::Main",
    "Main declares ProcessPhaseOne, WritePhaseOne, MakerNotes/Camera groups, and 16-byte entries.",
)
PHASEONE_RAW_DATA_SOURCE = evidence_anchor(
    84,
    92,
    "0x010f RawData",
    "RawData is undef, binary image data, PutFirst, non-writable, and dropped on copy.",
)
PHASEONE_SENSOR_ROUTE_SOURCE = evidence_anchor(
    93,
    96,
    "0x0110 SensorCalibration",
    "SensorCalibration routes to Image::ExifTool::PhaseOne::SensorCalibration.",
)
PHASEONE_DATETIME_SOURCE = evidence_anchor(
    97,
    110,
    "0x0112 DateTimeOriginal",
    "DateTimeOriginal is int32u, Time grouped, and explicitly non-writable "
    "because it can key raw data encryption.",
)
PHASEONE_TIME_UNKNOWN_SOURCE = evidence_anchor(
    129,
    140,
    "0x0212 UnknownDate",
    "UnknownDate is int32u, Time grouped, unknown, and shifted as time metadata.",
)
PHASEONE_STRIP_SOURCE = evidence_anchor(
    144,
    150,
    "StripOffsets and BlackLevelData",
    "StripOffsets is binary and non-writable; BlackLevelData is source binary int16u data.",
)
PHASEONE_SEQUENCE_SOURCE = evidence_anchor(
    196,
    213,
    "Sequence tags",
    "PhaseOne.pm defines SequenceID, SequenceKind, SequenceFrameNumber, "
    "SequenceFrameCount, and FirmwareVersions.",
)
PHASEONE_EXPOSURE_SOURCE = evidence_anchor(
    215,
    271,
    "Exposure and lens tags",
    "Exposure, focal-length, model, lens, aperture, and viewfinder tags are "
    "source-declared Phase One fields.",
)
PHASEONE_SENSOR_SOURCE = evidence_anchor(
    275,
    396,
    "%Image::ExifTool::PhaseOne::SensorCalibration",
    "SensorCalibration declares 12-byte entries, Camera grouping, binary "
    "calibration payloads, and sensor serial number.",
)
PHASEONE_WRITE_SOURCE = evidence_anchor(
    447,
    587,
    "WritePhaseOne",
    "Writes require a rebuilt Phase One block with value padding, fixups, "
    "subdirectory writes, and IFD pointer patching.",
)
PHASEONE_PROCESS_SOURCE = evidence_anchor(
    590,
    720,
    "ProcessPhaseOne",
    "ProcessPhaseOne validates headers, entry counts, entry formats, value sizes, "
    "and routes both directory types.",
)


@dataclass(frozen=True)
class PhaseOneRewriteRequest:
    tag_name: str
    raw_payload: bytes


@dataclass(frozen=True)
class PhaseOneTagSpec:
    table_kind: PhaseOneTableKind
    tag_id: int
    name: str
    format_name: PhaseOneFormatName | None
    group_2: PhaseOneGroup2
    writable: bool
    binary: bool
    hidden_unknown: bool
    route: PhaseOneTagRoute
    evidence_ids: tuple[str, ...]

    @property
    def value_class(self) -> PhaseOneValueClass:
        if self.route == "sensor_calibration_subdirectory":
            return "read_only_subdirectory"
        if self.name == "RawData":
            return "read_only_image_data"
        if self.hidden_unknown:
            return "hidden_unknown_source_value"
        if self.binary:
            return "binary_source_value"
        if not self.writable:
            return "read_only_source_value"
        return "writable_scalar"


@dataclass(frozen=True)
class PhaseOneIfdEntryPlan:
    index: int
    tag_id: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_payload: bytes
    raw_format_size: int | None
    source_format_name: PhaseOneFormatName
    source_size: int
    payload_is_inline: bool


@dataclass(frozen=True)
class PhaseOneSensorCalibrationPlan:
    payload_range: tuple[int, int]
    status: PhaseOnePlanStatus
    fields: tuple[PhaseOneFieldPlan, ...]
    output_emission_gates: tuple[PhaseOneOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PhaseOneFieldPlan:
    table_kind: PhaseOneTableKind
    tag_name: str
    tag_id: int
    index: int
    group_0: Literal["MakerNotes"]
    group_2: PhaseOneGroup2
    format_name: PhaseOneFormatName
    raw_format_size: int | None
    byte_range: tuple[int, int]
    raw_payload: bytes
    raw_value: PhaseOneRawValue
    value_class: PhaseOneValueClass
    route: PhaseOneTagRoute
    is_unknown: bool
    is_writable: bool
    sensor_calibration: PhaseOneSensorCalibrationPlan | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PhaseOneRoutingPlan:
    table: str
    table_kind: PhaseOneTableKind
    byte_order: PhaseOneByteOrder
    entry_size: int
    ifd_start: int
    entry_count: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PhaseOnePreservationPlan:
    payload_range: tuple[int, int]
    unknown_tag_ids: tuple[int, ...]
    binary_payload_ranges: tuple[tuple[int, int], ...]
    image_data_ranges: tuple[tuple[int, int], ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PhaseOneActionPlan:
    kind: PhaseOneActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PhaseOneOutputEmissionGate:
    code: PhaseOneGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PhaseOneTransactionPlan:
    status: PhaseOnePlanStatus
    source_data: bytes
    routing: PhaseOneRoutingPlan | None
    fields: tuple[PhaseOneFieldPlan, ...]
    preservation: PhaseOnePreservationPlan
    actions: tuple[PhaseOneActionPlan, ...]
    output_emission_gates: tuple[PhaseOneOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def writable_tags(self) -> tuple[str, ...]:
        return tuple(field.tag_name for field in self.fields if field.is_writable)

    def field(self, tag_name: str) -> PhaseOneFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Phase One transaction output is gated: {gate_codes}")
        return self.source_data


def tag_spec(
    table_kind: PhaseOneTableKind,
    tag_id: int,
    name: str,
    format_name: PhaseOneFormatName | None,
    group_2: PhaseOneGroup2,
    writable: bool,
    binary: bool,
    hidden_unknown: bool,
    route: PhaseOneTagRoute,
    evidence_ids: tuple[str, ...],
) -> PhaseOneTagSpec:
    return PhaseOneTagSpec(
        table_kind,
        tag_id,
        name,
        format_name,
        group_2,
        writable,
        binary,
        hidden_unknown,
        route,
        evidence_ids,
    )


MAIN_TAG_SPECS: tuple[PhaseOneTagSpec, ...] = (
    tag_spec(
        "main",
        0x0100,
        "CameraOrientation",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0102,
        "SerialNumber",
        "string",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0105,
        "ISO",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0106,
        "ColorMatrix1",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0107,
        "WB_RGBLevels",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0108,
        "SensorWidth",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0109,
        "SensorHeight",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x010A,
        "SensorLeftMargin",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x010B,
        "SensorTopMargin",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x010C,
        "ImageWidth",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x010D,
        "ImageHeight",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x010E,
        "RawFormat",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x010F,
        "RawData",
        "undef",
        "Camera",
        False,
        True,
        False,
        "main_table",
        (PHASEONE_RAW_DATA_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0110,
        "SensorCalibration",
        None,
        "Camera",
        False,
        False,
        False,
        "sensor_calibration_subdirectory",
        (PHASEONE_SENSOR_ROUTE_SOURCE, PHASEONE_SENSOR_SOURCE),
    ),
    tag_spec(
        "main",
        0x0112,
        "DateTimeOriginal",
        "int32u",
        "Time",
        False,
        False,
        False,
        "main_table",
        (PHASEONE_DATETIME_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0113,
        "ImageNumber",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0203,
        "Software",
        "string",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0204,
        "System",
        "string",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0210,
        "SensorTemperature",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0211,
        "SensorTemperature2",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0212,
        "UnknownDate",
        "int32u",
        "Time",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_TIME_UNKNOWN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x021C,
        "StripOffsets",
        None,
        "Camera",
        False,
        True,
        False,
        "main_table",
        (PHASEONE_STRIP_SOURCE,),
    ),
    tag_spec(
        "main",
        0x021D,
        "BlackLevel",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0222,
        "SplitColumn",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0223,
        "BlackLevelData",
        "int16u",
        "Camera",
        True,
        True,
        False,
        "main_table",
        (PHASEONE_STRIP_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0225,
        "PhaseOne_0x0225",
        "int16s",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0226,
        "ColorMatrix2",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x022B,
        "PhaseOne_0x022b",
        "float",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0258,
        "PhaseOne_0x0258",
        "int16s",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x025A,
        "PhaseOne_0x025a",
        "int16s",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0262,
        "SequenceID",
        "string",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_SEQUENCE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0263,
        "SequenceKind",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_SEQUENCE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0264,
        "SequenceFrameNumber",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_SEQUENCE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0265,
        "SequenceFrameCount",
        None,
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_SEQUENCE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0267,
        "AFAdjustment",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_MAIN_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0301,
        "FirmwareVersions",
        "string",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_SEQUENCE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0400,
        "ShutterSpeedValue",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_EXPOSURE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0401,
        "ApertureValue",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_EXPOSURE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0402,
        "ExposureCompensation",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_EXPOSURE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0403,
        "FocalLength",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_EXPOSURE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0410,
        "CameraModel",
        "string",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_EXPOSURE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0412,
        "LensModel",
        "string",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_EXPOSURE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0414,
        "MaxApertureValue",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_EXPOSURE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0415,
        "MinApertureValue",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_EXPOSURE_SOURCE,),
    ),
    tag_spec(
        "main",
        0x0455,
        "Viewfinder",
        "string",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_EXPOSURE_SOURCE,),
    ),
)

SENSOR_TAG_SPECS: tuple[PhaseOneTagSpec, ...] = (
    tag_spec(
        "sensor_calibration",
        0x0400,
        "SensorDefects",
        "undef",
        "Camera",
        True,
        True,
        False,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0401,
        "AllColorFlatField1",
        "undef",
        "Camera",
        True,
        True,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0404,
        "SensorCalibration_0x0404",
        "string",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0405,
        "SensorCalibration_0x0405",
        "string",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0406,
        "SensorCalibration_0x0406",
        "string",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0407,
        "SerialNumber",
        "string",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0408,
        "SensorCalibration_0x0408",
        "float",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x040B,
        "RedBlueFlatField",
        "undef",
        "Camera",
        True,
        True,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x040F,
        "SensorCalibration_0x040f",
        "undef",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0410,
        "AllColorFlatField2",
        "undef",
        "Camera",
        True,
        True,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0413,
        "SensorCalibration_0x0413",
        "double",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0414,
        "SensorCalibration_0x0414",
        "undef",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0416,
        "AllColorFlatField3",
        "undef",
        "Camera",
        True,
        True,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0418,
        "SensorCalibration_0x0418",
        "undef",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x0419,
        "LinearizationCoefficients1",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x041A,
        "LinearizationCoefficients2",
        "float",
        "Camera",
        True,
        False,
        False,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x041C,
        "SensorCalibration_0x041c",
        "float",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
    tag_spec(
        "sensor_calibration",
        0x041E,
        "SensorCalibration_0x041e",
        "undef",
        "Camera",
        True,
        False,
        True,
        "main_table",
        (PHASEONE_SENSOR_SOURCE,),
    ),
)

SPECS_BY_TABLE_AND_ID = {("main", spec.tag_id): spec for spec in MAIN_TAG_SPECS} | {
    ("sensor_calibration", spec.tag_id): spec for spec in SENSOR_TAG_SPECS
}
SPECS_BY_NAME = {spec.name: spec for spec in (*MAIN_TAG_SPECS, *SENSOR_TAG_SPECS)}


def build_phaseone_transaction_plan(
    source_data: bytes,
    *,
    rewrite_requests: tuple[PhaseOneRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> PhaseOneTransactionPlan:
    parsed = parse_phaseone_directory(source_data)
    if isinstance(parsed, PhaseOneOutputEmissionGate):
        return unsupported_plan(source_data, (parsed,))

    routing, entries = parsed
    fields, actions = build_fields(source_data, routing, entries)
    rewrite_gates, rewrite_actions = plan_rewrites(fields, rewrite_requests)
    output_gates = list(rewrite_gates)
    if not rewrite_requests and not allow_output_emission:
        output_gates.append(
            PhaseOneOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "The default Phase One plan is read-only and does not emit bytes.",
                (PHASEONE_WRITE_SOURCE,),
            )
        )

    route_action = PhaseOneActionPlan(
        "route_main_table" if routing.table_kind == "main" else "route_sensor_calibration_table",
        routing.table,
        (0, len(source_data)),
        "Route Phase One payload to the source-declared table.",
        routing.evidence_ids,
    )
    all_actions = (route_action, *actions, *rewrite_actions)
    all_gates = tuple(output_gates)
    preservation = build_preservation(source_data, fields)
    return PhaseOneTransactionPlan(
        status="planned",
        source_data=source_data,
        routing=routing,
        fields=fields,
        preservation=preservation,
        actions=all_actions,
        output_emission_gates=all_gates,
        evidence_ids=collect_evidence_ids(fields, all_actions, all_gates),
    )


plan_phaseone_transaction = build_phaseone_transaction_plan


def unsupported_plan(
    source_data: bytes,
    gates: tuple[PhaseOneOutputEmissionGate, ...],
) -> PhaseOneTransactionPlan:
    return PhaseOneTransactionPlan(
        status="unsupported",
        source_data=source_data,
        routing=None,
        fields=(),
        preservation=PhaseOnePreservationPlan(
            (0, len(source_data)), (), (), (), (PHASEONE_PROCESS_SOURCE,)
        ),
        actions=(),
        output_emission_gates=gates,
        evidence_ids=unique_references(
            tuple(reference for gate in gates for reference in gate.evidence_ids)
        ),
    )


def parse_phaseone_directory(
    source_data: bytes,
) -> tuple[PhaseOneRoutingPlan, tuple[PhaseOneIfdEntryPlan, ...]] | PhaseOneOutputEmissionGate:
    if len(source_data) < PHASEONE_HEADER_SIZE:
        return PhaseOneOutputEmissionGate(
            "truncated_phaseone_header",
            "Phase One directories require a 12-byte header.",
            (PHASEONE_PROCESS_SOURCE,),
        )

    header = source_data[:PHASEONE_HEADER_SIZE]
    header_info = phaseone_header_info(header)
    if header_info is None:
        return PhaseOneOutputEmissionGate(
            "unrecognized_phaseone_header",
            "PhaseOne.pm accepts only Main IIII.waR/MMMMRaw. or SensorCalibration version headers.",
            (PHASEONE_MAIN_SOURCE, PHASEONE_SENSOR_SOURCE, PHASEONE_PROCESS_SOURCE),
        )
    table_kind, byte_order, entry_size = header_info
    ifd_start = read_u32(source_data, 8, byte_order)
    if ifd_start + PHASEONE_DIRECTORY_PREFIX_SIZE > len(source_data):
        return PhaseOneOutputEmissionGate(
            "truncated_phaseone_ifd_prefix",
            "The Phase One IFD offset does not leave room for entry count and padding.",
            (PHASEONE_PROCESS_SOURCE,),
        )
    entry_count = read_u32(source_data, ifd_start, byte_order)
    if entry_count < 2 or entry_count > PHASEONE_MAX_ENTRY_COUNT:
        return PhaseOneOutputEmissionGate(
            "invalid_phaseone_entry_count",
            "PhaseOne.pm rejects entry counts outside 2..300.",
            (PHASEONE_PROCESS_SOURCE,),
        )
    entries_start = ifd_start + PHASEONE_DIRECTORY_PREFIX_SIZE
    entry_table_end = entries_start + entry_count * entry_size
    if entry_table_end > len(source_data):
        return PhaseOneOutputEmissionGate(
            "truncated_phaseone_entry_table",
            "Phase One entry table extends beyond the source payload.",
            (PHASEONE_PROCESS_SOURCE,),
        )

    routing = PhaseOneRoutingPlan(
        table=table_name_for_kind(table_kind),
        table_kind=table_kind,
        byte_order=byte_order,
        entry_size=entry_size,
        ifd_start=ifd_start,
        entry_count=entry_count,
        evidence_ids=(
            PHASEONE_MAIN_SOURCE if table_kind == "main" else PHASEONE_SENSOR_SOURCE,
            PHASEONE_PROCESS_SOURCE,
        ),
    )
    entries: list[PhaseOneIfdEntryPlan] = []
    for index in range(entry_count):
        entry_offset = entries_start + index * entry_size
        parsed_entry = parse_entry(source_data, routing, index, entry_offset)
        if isinstance(parsed_entry, PhaseOneOutputEmissionGate):
            return parsed_entry
        entries.append(parsed_entry)
    return routing, tuple(entries)


def phaseone_header_info(
    header: bytes,
) -> tuple[PhaseOneTableKind, PhaseOneByteOrder, int] | None:
    if header.startswith(b"IIII") and header[5:8] == b"waR":
        return "main", "little", PHASEONE_MAIN_ENTRY_SIZE
    if header.startswith(b"MMMM") and header[4:7] == b"Raw":
        return "main", "big", PHASEONE_MAIN_ENTRY_SIZE
    if header[:8] == b"IIII\x01\x00\x00\x00":
        return "sensor_calibration", "little", PHASEONE_SENSOR_ENTRY_SIZE
    if header[:8] == b"MMMM\x00\x00\x00\x01":
        return "sensor_calibration", "big", PHASEONE_SENSOR_ENTRY_SIZE
    return None


def parse_entry(
    source_data: bytes,
    routing: PhaseOneRoutingPlan,
    index: int,
    entry_offset: int,
) -> PhaseOneIfdEntryPlan | PhaseOneOutputEmissionGate:
    entry_size = routing.entry_size
    tag_id = read_u32(source_data, entry_offset, routing.byte_order)
    raw_format_size: int | None = None
    if routing.table_kind == "main":
        raw_format_size = read_u32(source_data, entry_offset + 4, routing.byte_order)
    source_size = read_u32(source_data, entry_offset + entry_size - 8, routing.byte_order)
    if source_size > PHASEONE_MAX_VALUE_SIZE:
        return PhaseOneOutputEmissionGate(
            "invalid_phaseone_value_size",
            f"Phase One entry {index} has a value size greater than the source-backed limit.",
            (PHASEONE_PROCESS_SOURCE, PHASEONE_WRITE_SOURCE),
        )

    value_field_offset = entry_offset + entry_size - PHASEONE_INLINE_VALUE_SIZE
    if source_size <= PHASEONE_INLINE_VALUE_SIZE:
        value_range = (value_field_offset, value_field_offset + source_size)
        raw_payload = source_data[value_range[0] : value_range[1]]
        payload_is_inline = True
    else:
        value_offset = read_u32(source_data, value_field_offset, routing.byte_order)
        value_end = value_offset + source_size
        if value_offset > len(source_data) or value_end > len(source_data):
            return PhaseOneOutputEmissionGate(
                "truncated_phaseone_value",
                f"Phase One entry {index} points outside the source payload.",
                (PHASEONE_PROCESS_SOURCE, PHASEONE_WRITE_SOURCE),
            )
        value_range = (value_offset, value_end)
        raw_payload = source_data[value_offset:value_end]
        payload_is_inline = False

    return PhaseOneIfdEntryPlan(
        index=index,
        tag_id=tag_id,
        entry_range=(entry_offset, entry_offset + entry_size),
        value_range=value_range,
        raw_payload=raw_payload,
        raw_format_size=raw_format_size,
        source_format_name=entry_format_name(routing, raw_format_size, source_size),
        source_size=source_size,
        payload_is_inline=payload_is_inline,
    )


def build_fields(
    source_data: bytes,
    routing: PhaseOneRoutingPlan,
    entries: tuple[PhaseOneIfdEntryPlan, ...],
) -> tuple[tuple[PhaseOneFieldPlan, ...], tuple[PhaseOneActionPlan, ...]]:
    fields: list[PhaseOneFieldPlan] = []
    actions: list[PhaseOneActionPlan] = []
    for entry in entries:
        spec = SPECS_BY_TABLE_AND_ID.get((routing.table_kind, entry.tag_id))
        if spec is None:
            field = unknown_field_plan(routing, entry)
            action = PhaseOneActionPlan(
                "preserve_unknown_tag",
                field.tag_name,
                field.byte_range,
                "Preserve Phase One tag not declared by PhaseOne.pm.",
                (PHASEONE_PROCESS_SOURCE,),
            )
        else:
            field = source_field_plan(source_data, routing, entry, spec)
            action = PhaseOneActionPlan(
                action_kind_for_field(field),
                field.tag_name,
                field.byte_range,
                action_reason_for_field(field),
                field.evidence_ids,
            )
        fields.append(field)
        actions.append(action)
    return tuple(fields), tuple(actions)


def unknown_field_plan(
    routing: PhaseOneRoutingPlan,
    entry: PhaseOneIfdEntryPlan,
) -> PhaseOneFieldPlan:
    return PhaseOneFieldPlan(
        table_kind=routing.table_kind,
        tag_name=f"PhaseOne_0x{entry.tag_id:04x}",
        tag_id=entry.tag_id,
        index=entry.index,
        group_0="MakerNotes",
        group_2="Camera",
        format_name=entry.source_format_name,
        raw_format_size=entry.raw_format_size,
        byte_range=entry.value_range,
        raw_payload=entry.raw_payload,
        raw_value=entry.raw_payload,
        value_class="unknown_preserved",
        route="main_table",
        is_unknown=True,
        is_writable=False,
        sensor_calibration=None,
        evidence_ids=(PHASEONE_PROCESS_SOURCE,),
    )


def source_field_plan(
    source_data: bytes,
    routing: PhaseOneRoutingPlan,
    entry: PhaseOneIfdEntryPlan,
    spec: PhaseOneTagSpec,
) -> PhaseOneFieldPlan:
    format_name = spec.format_name or entry.source_format_name
    sensor_calibration = (
        sensor_calibration_plan(entry) if spec.route == "sensor_calibration_subdirectory" else None
    )
    return PhaseOneFieldPlan(
        table_kind=routing.table_kind,
        tag_name=spec.name,
        tag_id=entry.tag_id,
        index=entry.index,
        group_0="MakerNotes",
        group_2=spec.group_2,
        format_name=format_name,
        raw_format_size=entry.raw_format_size,
        byte_range=entry.value_range,
        raw_payload=entry.raw_payload,
        raw_value=interpret_value(entry.raw_payload, format_name, routing.byte_order),
        value_class=spec.value_class,
        route=spec.route,
        is_unknown=spec.hidden_unknown,
        is_writable=spec.writable and spec.value_class == "writable_scalar",
        sensor_calibration=sensor_calibration,
        evidence_ids=spec.evidence_ids,
    )


def sensor_calibration_plan(entry: PhaseOneIfdEntryPlan) -> PhaseOneSensorCalibrationPlan:
    nested = build_phaseone_transaction_plan(entry.raw_payload, allow_output_emission=True)
    return PhaseOneSensorCalibrationPlan(
        payload_range=entry.value_range,
        status=nested.status,
        fields=nested.fields,
        output_emission_gates=nested.output_emission_gates,
        evidence_ids=nested.evidence_ids or (PHASEONE_SENSOR_SOURCE,),
    )


def action_kind_for_field(field: PhaseOneFieldPlan) -> PhaseOneActionKind:
    if field.route == "sensor_calibration_subdirectory":
        return "route_sensor_calibration_subdirectory"
    if field.value_class == "read_only_image_data":
        return "preserve_image_data"
    if field.value_class == "binary_source_value":
        return "preserve_binary_payload"
    if field.value_class == "hidden_unknown_source_value":
        return "preserve_hidden_unknown_tag"
    return "extract_source_tag"


def action_reason_for_field(field: PhaseOneFieldPlan) -> str:
    if field.route == "sensor_calibration_subdirectory":
        return "Route SensorCalibration bytes into the nested Phase One calibration table."
    if field.value_class == "read_only_image_data":
        return "Preserve RawData image bytes because PhaseOne.pm marks the tag non-writable."
    if field.value_class == "binary_source_value":
        return "Preserve source binary payload declared by PhaseOne.pm."
    if field.value_class == "hidden_unknown_source_value":
        return "Preserve source-declared hidden unknown Phase One tag."
    return "Extract source-declared Phase One tag."


def plan_rewrites(
    fields: tuple[PhaseOneFieldPlan, ...],
    rewrite_requests: tuple[PhaseOneRewriteRequest, ...],
) -> tuple[tuple[PhaseOneOutputEmissionGate, ...], tuple[PhaseOneActionPlan, ...]]:
    fields_by_name = {field.tag_name: field for field in fields}
    seen_names: set[str] = set()
    gates: list[PhaseOneOutputEmissionGate] = []
    actions: list[PhaseOneActionPlan] = []
    for request in rewrite_requests:
        field = fields_by_name.get(request.tag_name)
        gate = rewrite_gate_for_request(request, field, seen_names)
        seen_names.add(request.tag_name)
        gates.append(gate)
        actions.append(
            PhaseOneActionPlan(
                "block_requested_rewrite",
                request.tag_name,
                field.byte_range if field is not None else None,
                gate.reason,
                gate.evidence_ids,
            )
        )
    return tuple(gates), tuple(actions)


def rewrite_gate_for_request(
    request: PhaseOneRewriteRequest,
    field: PhaseOneFieldPlan | None,
    seen_names: set[str],
) -> PhaseOneOutputEmissionGate:
    spec = SPECS_BY_NAME.get(request.tag_name)
    if request.tag_name in seen_names:
        return PhaseOneOutputEmissionGate(
            "duplicate_rewrite_tag",
            f"Phase One rewrite for {request.tag_name} was requested more than once.",
            (PHASEONE_WRITE_SOURCE,),
        )
    if spec is None:
        return PhaseOneOutputEmissionGate(
            "unknown_rewrite_tag",
            f"PhaseOne.pm does not define a tag named {request.tag_name}.",
            (PHASEONE_MAIN_SOURCE, PHASEONE_SENSOR_SOURCE),
        )
    if field is None:
        return PhaseOneOutputEmissionGate(
            "missing_source_tag_for_rewrite",
            f"Phase One tag {request.tag_name} is not present in the source payload.",
            spec.evidence_ids,
        )
    if not field.is_writable:
        return PhaseOneOutputEmissionGate(
            "read_only_rewrite_tag",
            f"Phase One tag {request.tag_name} is not a writable scalar in this planner.",
            field.evidence_ids,
        )
    return PhaseOneOutputEmissionGate(
        "phaseone_rewrite_requires_full_directory_rebuild",
        "PhaseOne.pm rewrites by rebuilding the full directory; this planner "
        "slice is non-mutating.",
        (PHASEONE_WRITE_SOURCE,),
    )


def build_preservation(
    source_data: bytes,
    fields: tuple[PhaseOneFieldPlan, ...],
) -> PhaseOnePreservationPlan:
    return PhaseOnePreservationPlan(
        payload_range=(0, len(source_data)),
        unknown_tag_ids=tuple(
            field.tag_id for field in fields if field.value_class == "unknown_preserved"
        ),
        binary_payload_ranges=tuple(
            field.byte_range for field in fields if field.value_class == "binary_source_value"
        ),
        image_data_ranges=tuple(
            field.byte_range for field in fields if field.value_class == "read_only_image_data"
        ),
        evidence_ids=(
            PHASEONE_PROCESS_SOURCE,
            PHASEONE_RAW_DATA_SOURCE,
            PHASEONE_SENSOR_SOURCE,
        ),
    )


def entry_format_name(
    routing: PhaseOneRoutingPlan,
    raw_format_size: int | None,
    source_size: int,
) -> PhaseOneFormatName:
    if routing.table_kind == "sensor_calibration":
        return "undef" if source_size % 4 else "int32s"
    if raw_format_size == 1:
        return "string"
    if raw_format_size == 2:
        return "int16s"
    if raw_format_size == 4:
        return "int32s"
    return "undef"


def interpret_value(
    raw_payload: bytes,
    format_name: PhaseOneFormatName,
    byte_order: PhaseOneByteOrder,
) -> PhaseOneRawValue:
    if format_name == "string":
        return raw_payload.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    if format_name in {"undef", "int32u"} and len(raw_payload) % 4 != 0:
        return raw_payload
    if format_name in {"int16s", "int16u"} and len(raw_payload) % 2 == 0:
        return tuple(read_i16_values(raw_payload, byte_order, signed=format_name == "int16s"))
    if format_name in {"int32s", "int32u"} and len(raw_payload) % 4 == 0:
        signed = format_name == "int32s"
        return tuple(read_i32_values(raw_payload, byte_order, signed=signed))
    if format_name == "float" and len(raw_payload) % 4 == 0:
        return tuple(read_float_values(raw_payload, byte_order))
    if format_name == "double" and len(raw_payload) % 8 == 0:
        return tuple(read_double_values(raw_payload, byte_order))
    return raw_payload


def table_name_for_kind(table_kind: PhaseOneTableKind) -> str:
    if table_kind == "main":
        return "Image::ExifTool::PhaseOne::Main"
    return "Image::ExifTool::PhaseOne::SensorCalibration"


def read_u32(data: bytes, offset: int, byte_order: PhaseOneByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order)


def read_i16_values(
    data: bytes,
    byte_order: PhaseOneByteOrder,
    *,
    signed: bool,
) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(data[offset : offset + 2], byte_order, signed=signed)
        for offset in range(0, len(data), 2)
    )


def read_i32_values(
    data: bytes,
    byte_order: PhaseOneByteOrder,
    *,
    signed: bool,
) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(data[offset : offset + 4], byte_order, signed=signed)
        for offset in range(0, len(data), 4)
    )


def read_float_values(data: bytes, byte_order: PhaseOneByteOrder) -> tuple[float, ...]:
    prefix = "<" if byte_order == "little" else ">"
    return tuple(
        struct.unpack(f"{prefix}f", data[offset : offset + 4])[0]
        for offset in range(0, len(data), 4)
    )


def read_double_values(data: bytes, byte_order: PhaseOneByteOrder) -> tuple[float, ...]:
    prefix = "<" if byte_order == "little" else ">"
    return tuple(
        struct.unpack(f"{prefix}d", data[offset : offset + 8])[0]
        for offset in range(0, len(data), 8)
    )


def collect_evidence_ids(
    fields: tuple[PhaseOneFieldPlan, ...],
    actions: tuple[PhaseOneActionPlan, ...],
    gates: tuple[PhaseOneOutputEmissionGate, ...],
) -> tuple[str, ...]:
    references: list[str] = [
        PHASEONE_FORMAT_SOURCE,
        PHASEONE_MAIN_SOURCE,
        PHASEONE_SENSOR_SOURCE,
        PHASEONE_PROCESS_SOURCE,
        PHASEONE_WRITE_SOURCE,
    ]
    for field in fields:
        references.extend(field.evidence_ids)
        if field.sensor_calibration is not None:
            references.extend(field.sensor_calibration.evidence_ids)
    for action in actions:
        references.extend(action.evidence_ids)
    for gate in gates:
        references.extend(gate.evidence_ids)
    return unique_references(tuple(references))


def unique_references(references: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)
