"""Source-grounded, non-mutating Kandao KVAR/KFIX/KSTB metadata plans."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

type KandaoDirectoryName = Literal["KVAR", "KFIX", "KSTB"]
type KandaoFormatName = Literal[
    "string",
    "int8u",
    "int16u",
    "int32u",
    "int64u",
    "int8s",
    "int16s",
    "int32s",
    "int64s",
    "float",
    "double",
    "undef",
]
type KandaoRecordTable = Literal["IMU", "GPS", "GPSX", "FrameISP"]
type KandaoMetadataRole = Literal[
    "kvar_scalar",
    "kfix_scalar",
    "kstb_scalar",
    "time_metadata",
    "lens_metadata",
    "model_metadata",
    "version_metadata",
    "presentation_timestamp",
    "imu_records",
    "gps_records",
    "gpsx_records",
    "frame_isp_records",
    "preserved_unknown",
]
type KandaoRewriteOperation = Literal["replace_tag", "delete_tag", "insert_tag"]
type KandaoEmissionGateCode = Literal[
    "truncated_kandao_count",
    "truncated_kandao_entry_header",
    "unknown_kandao_format",
    "truncated_kandao_payload",
    "malformed_kandao_record_payload",
    "unsupported_kandao_rewrite",
    "raw_payload_preservation_required",
    "planner_is_non_mutating",
    "kandao_writer_not_implemented",
]
type KandaoResponsibilityConcern = Literal[
    "format_code_routing",
    "kvar_table_routing",
    "kfix_table_routing",
    "kstb_group_routing",
    "camera_scalar_fields",
    "time_lens_model_version_fields",
    "timed_record_boundaries",
    "presentation_timestamp_binary_preservation",
    "unknown_tag_preservation",
    "malformed_and_truncation_blockers",
    "unsupported_rewrite_gates",
    "non_mutating_defaults",
]
type KandaoScalar = int | float | str | bytes
type KandaoDecodedValue = KandaoScalar | tuple[KandaoScalar, ...]

KANDAO_PM_SOURCE_PATH = "lib/Image/ExifTool/Kandao.pm"
KANDAO_ENTRY_HEADER_SIZE = 0x2C

KANDAO_FORMAT_SOURCE = "kandao.format"
KANDAO_MAIN_TABLE_SOURCE = "kandao.main.table"
KANDAO_GPS_TABLE_SOURCE = "kandao.gps.table"
KANDAO_GPSX_TABLE_SOURCE = "kandao.gpsx.table"
KANDAO_IMU_TABLE_SOURCE = "kandao.imu.table"
KANDAO_FRAME_ISP_TABLE_SOURCE = "kandao.frame.isp.table"
KANDAO_PROCESS_SOURCE = "kandao.process"
KANDAO_KVAR_FILE_SOURCE = "kandao.kvar.file"

FORMAT_NAMES: dict[str, KandaoFormatName] = {
    "CHAR": "string",
    "BOOL": "int8u",
    "U8": "int8u",
    "U16": "int16u",
    "U32": "int32u",
    "U64": "int64u",
    "S8": "int8s",
    "S16": "int16s",
    "S32": "int32s",
    "S64": "int64s",
    "FLOAT": "float",
    "DOUBLE": "double",
}
FORMAT_SIZES: dict[KandaoFormatName, int] = {
    "string": 1,
    "int8u": 1,
    "int16u": 2,
    "int32u": 4,
    "int64u": 8,
    "int8s": 1,
    "int16s": 2,
    "int32s": 4,
    "int64s": 8,
    "float": 4,
    "double": 8,
    "undef": 1,
}
STRUCT_FORMATS: dict[KandaoFormatName, str] = {
    "int8u": "<B",
    "int16u": "<H",
    "int32u": "<I",
    "int64u": "<Q",
    "int8s": "<b",
    "int16s": "<h",
    "int32s": "<i",
    "int64s": "<q",
    "float": "<f",
    "double": "<d",
}
TAG_ID_RE = re.compile(rb"^[A-Z0-9_]+$")


@dataclass(frozen=True)
class _TagDefinition:
    tag_name: str
    role: KandaoMetadataRole
    group2: str = "Camera"
    read_format: KandaoFormatName | None = None


TAG_DEFINITIONS: dict[str, _TagDefinition] = {
    "CPU_TEMP": _TagDefinition("CPUTemperature", "kvar_scalar"),
    "BAT_TEMP": _TagDefinition("BatteryTemperature", "kvar_scalar"),
    "PTS_UNIT": _TagDefinition("TimeStampUnit", "time_metadata", "Time"),
    "TOTAL_FRAME": _TagDefinition("TotalFrames", "kvar_scalar"),
    "TOTAL_TIME_MS": _TagDefinition("TotalTime", "time_metadata", "Time"),
    "LENS": _TagDefinition("LensData", "lens_metadata"),
    "DASHBOARD": _TagDefinition("Dashboard", "kvar_scalar"),
    "PROJECTION": _TagDefinition("Projection", "lens_metadata"),
    "CENTER_SHIFT": _TagDefinition("CenterShift", "lens_metadata"),
    "DISTORTION": _TagDefinition("Distortion", "lens_metadata"),
    "INFO": _TagDefinition("Info", "kvar_scalar"),
    "PTS": _TagDefinition("PresentationTimeStamp", "presentation_timestamp", read_format="undef"),
    "LENS_SN0": _TagDefinition("Lens0SerialNumber", "lens_metadata"),
    "LENS_SN1": _TagDefinition("Lens1SerialNumber", "lens_metadata"),
    "LENS_OTP_ID0": _TagDefinition("Lens0OTP_ID", "lens_metadata"),
    "LENS_OTP_ID1": _TagDefinition("Lens1OTP_ID", "lens_metadata"),
    "EXP": _TagDefinition("Exp", "kvar_scalar"),
    "ISP": _TagDefinition("ISP", "kvar_scalar"),
    "GAINMAP0": _TagDefinition("GainMap0", "kvar_scalar"),
    "GAINMAP1": _TagDefinition("GainMap1", "kvar_scalar"),
    "PRODUCT": _TagDefinition("Model", "model_metadata"),
    "PROJECT": _TagDefinition("Project", "model_metadata"),
    "SN": _TagDefinition("SerialNumber", "model_metadata"),
    "PR_VER": _TagDefinition("ProductVersion", "version_metadata"),
    "SW_VER": _TagDefinition("SoftwareVersion", "version_metadata"),
    "HW_VER": _TagDefinition("HardwareVersion", "version_metadata"),
    "VIDEO_CAPTIME": _TagDefinition("VideoCaptureTime", "time_metadata", "Time"),
    "GPS_CAPTIME": _TagDefinition("GPSCaptureTime", "time_metadata", "Time"),
    "LENS_INDEX": _TagDefinition("LensIndex", "lens_metadata", read_format="int16u"),
    "NEED_LSC": _TagDefinition("NeedLDSC", "lens_metadata"),
    "INPUT_INSERT": _TagDefinition("InputInsert", "kfix_scalar"),
    "VIDEO_RESOLUTION": _TagDefinition("VideoResolution", "kfix_scalar"),
    "VIDEO_CODECTYPE": _TagDefinition("VideoCodec", "kfix_scalar"),
    "VIDEO_BITRATE": _TagDefinition("VideoBitrate", "kfix_scalar"),
    "VIDEO_FORMAT": _TagDefinition("VideoFormat", "kfix_scalar"),
    "OUTPUT_INSERT": _TagDefinition("OutputInsert", "kfix_scalar"),
    "DYNAMIC_RANGE": _TagDefinition("DynamicRange", "kfix_scalar"),
    "AWB_CCT": _TagDefinition("AWB_CCT", "kfix_scalar"),
    "EV": _TagDefinition("EV", "kfix_scalar"),
    "ISO": _TagDefinition("ISO", "kfix_scalar"),
    "SHUTTER": _TagDefinition("Shutter", "kfix_scalar"),
    "IMAGE_STYLE": _TagDefinition("ImageStyle", "kfix_scalar"),
    "AE_METERING": _TagDefinition("AEMetering", "kfix_scalar"),
    "CAPTURE_MODE": _TagDefinition("CaptureMode", "kfix_scalar"),
    "HDR": _TagDefinition("HDR", "kfix_scalar"),
    "STITCHED": _TagDefinition("Stitched", "kfix_scalar"),
    "COVER_MODE": _TagDefinition("CoverMode", "kfix_scalar"),
    "STEREO": _TagDefinition("Stereo", "kfix_scalar"),
    "FOV": _TagDefinition("FOV", "kfix_scalar"),
    "AE_MODE": _TagDefinition("AEMode", "kfix_scalar"),
    "AF_FN": _TagDefinition("AF_FN", "kfix_scalar"),
    "AWB_MODE": _TagDefinition("AWBMode", "kfix_scalar"),
    "AUDIO_GAIN": _TagDefinition("AudioGain", "kfix_scalar"),
    "INTERVAL": _TagDefinition("Interval", "kfix_scalar"),
    "ISP_VER": _TagDefinition("ISPVersion", "version_metadata"),
    "YAW": _TagDefinition("Yaw", "kfix_scalar"),
    "FAN_LEVEL": _TagDefinition("FanLevel", "kfix_scalar"),
    "FAN_MODE": _TagDefinition("FanMode", "kfix_scalar"),
    "CUSTOMIZED": _TagDefinition("Customized", "kfix_scalar"),
}
RECORD_TABLES: dict[str, tuple[KandaoRecordTable, int, int, str]] = {
    "IMU": ("IMU", 20, 0, KANDAO_IMU_TABLE_SOURCE),
    "GPSX": ("GPSX", 36, 0, KANDAO_GPSX_TABLE_SOURCE),
    "FRAME_ISP": ("FrameISP", 12, 0, KANDAO_FRAME_ISP_TABLE_SOURCE),
}


@dataclass(frozen=True)
class KandaoRewriteRequest:
    operation: KandaoRewriteOperation
    tag_key: str
    payload: bytes = b""


@dataclass(frozen=True)
class KandaoRecordFieldPlan:
    tag_name: str
    offset: int
    format_name: KandaoFormatName
    value: KandaoDecodedValue
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class KandaoTimedRecordPlan:
    table: KandaoRecordTable
    index: int
    record_range: tuple[int, int]
    fields: tuple[KandaoRecordFieldPlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class KandaoMetadataEntryPlan:
    tag_key: str
    tag_name: str
    directory_name: KandaoDirectoryName
    family1_group: str
    family2_group: str
    role: KandaoMetadataRole
    value: KandaoDecodedValue | None
    raw_payload: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class KandaoTagPlan:
    index: int
    tag_key: str
    tag_name: str
    directory_name: KandaoDirectoryName
    family1_group: str
    family2_group: str
    role: KandaoMetadataRole
    declared_format_code: str
    declared_format_name: KandaoFormatName
    read_format_name: KandaoFormatName
    element_count: int
    payload_size: int
    header_range: tuple[int, int]
    payload_range: tuple[int, int]
    raw_payload: bytes
    value: KandaoDecodedValue | None
    timed_records: tuple[KandaoTimedRecordPlan, ...]
    is_known: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class KandaoPlanningResponsibility:
    concern: KandaoResponsibilityConcern
    detail: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class KandaoEmissionGate:
    code: KandaoEmissionGateCode
    reason: str
    offset: int | None
    blocks_emission: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class KandaoMetadataTransactionPlan:
    directory_name: KandaoDirectoryName
    tag_count: int | None
    tags: tuple[KandaoTagPlan, ...]
    metadata_entries: tuple[KandaoMetadataEntryPlan, ...]
    responsibilities: tuple[KandaoPlanningResponsibility, ...]
    output_emission_gates: tuple[KandaoEmissionGate, ...]
    rewrite_requests: tuple[KandaoRewriteRequest, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def unknown_tags(self) -> tuple[KandaoTagPlan, ...]:
        return tuple(tag for tag in self.tags if not tag.is_known)

    @property
    def timed_tags(self) -> tuple[KandaoTagPlan, ...]:
        return tuple(tag for tag in self.tags if tag.timed_records)

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"Kandao metadata transaction output is gated: {gate_codes}")


def build_kandao_metadata_transaction_plan(
    data: bytes,
    *,
    directory_name: KandaoDirectoryName = "KVAR",
    rewrite_requests: tuple[KandaoRewriteRequest, ...] = (),
) -> KandaoMetadataTransactionPlan:
    """Build a Kandao KVAR/KFIX/KSTB read-side plan without mutating bytes."""

    tags, tag_count, parse_gates = parse_kandao_tags(data, directory_name)
    gates = [*parse_gates]
    for request in rewrite_requests:
        gates.append(
            KandaoEmissionGate(
                "unsupported_kandao_rewrite",
                (
                    f"Rewrite request {request.operation} for {request.tag_key} is gated "
                    "because Kandao.pm supplies read-side KVAR/KFIX/KSTB routing only."
                ),
                None,
                True,
                (KANDAO_MAIN_TABLE_SOURCE, KANDAO_PROCESS_SOURCE),
            )
        )
    gates.extend(non_mutating_gates())
    responsibilities = default_responsibilities()
    metadata_entries = tuple(entry for tag in tags for entry in metadata_entries_for_tag(tag))
    sources = unique_sources(
        (
            *(source for tag in tags for source in tag.evidence_ids),
            *(source for entry in metadata_entries for source in entry.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
            KANDAO_KVAR_FILE_SOURCE,
        )
    )
    return KandaoMetadataTransactionPlan(
        directory_name=directory_name,
        tag_count=tag_count,
        tags=tags,
        metadata_entries=metadata_entries,
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        rewrite_requests=rewrite_requests,
        evidence_ids=sources,
    )


def parse_kandao_tags(
    data: bytes,
    directory_name: KandaoDirectoryName,
) -> tuple[tuple[KandaoTagPlan, ...], int | None, tuple[KandaoEmissionGate, ...]]:
    if len(data) < 4:
        return (
            (),
            None,
            (
                KandaoEmissionGate(
                    "truncated_kandao_count",
                    "Kandao metadata is shorter than the four-byte little-endian tag count.",
                    0,
                    True,
                    (KANDAO_PROCESS_SOURCE,),
                ),
            ),
        )

    tag_count = int.from_bytes(data[0:4], "little")
    offset = 4
    tags: list[KandaoTagPlan] = []
    gates: list[KandaoEmissionGate] = []
    for index in range(tag_count):
        header_end = offset + KANDAO_ENTRY_HEADER_SIZE
        if header_end > len(data):
            gates.append(
                KandaoEmissionGate(
                    "truncated_kandao_entry_header",
                    f"Kandao entry {index} header at offset {offset} exceeds input length.",
                    offset,
                    True,
                    (KANDAO_PROCESS_SOURCE,),
                )
            )
            break
        header = data[offset:header_end]
        tag_key = decode_header_text(header[0:0x20])
        format_code = decode_header_text(header[0x20:0x28])
        format_name = FORMAT_NAMES.get(format_code)
        if format_name is None:
            gates.append(
                KandaoEmissionGate(
                    "unknown_kandao_format",
                    f"Kandao entry {tag_key or index} uses unknown format {format_code!r}.",
                    offset + 0x20,
                    True,
                    (KANDAO_FORMAT_SOURCE, KANDAO_PROCESS_SOURCE),
                )
            )
            break
        element_count = int.from_bytes(header[0x28:0x2C], "little")
        payload_size = element_count * FORMAT_SIZES[format_name]
        payload_offset = header_end
        payload_end = payload_offset + payload_size
        if payload_end > len(data):
            gates.append(
                KandaoEmissionGate(
                    "truncated_kandao_payload",
                    (
                        f"Kandao entry {tag_key or index} payload ends at {payload_end}, "
                        f"past input length {len(data)}."
                    ),
                    payload_offset,
                    True,
                    (KANDAO_PROCESS_SOURCE,),
                )
            )
            break
        payload = data[payload_offset:payload_end]
        tag_plan, tag_gates = build_tag_plan(
            index=index,
            tag_key=tag_key,
            directory_name=directory_name,
            declared_format_code=format_code,
            declared_format_name=format_name,
            element_count=element_count,
            header_range=(offset, header_end),
            payload_range=(payload_offset, payload_end),
            raw_payload=payload,
        )
        tags.append(tag_plan)
        gates.extend(tag_gates)
        offset = payload_end
    return tuple(tags), tag_count, tuple(gates)


def build_tag_plan(
    *,
    index: int,
    tag_key: str,
    directory_name: KandaoDirectoryName,
    declared_format_code: str,
    declared_format_name: KandaoFormatName,
    element_count: int,
    header_range: tuple[int, int],
    payload_range: tuple[int, int],
    raw_payload: bytes,
) -> tuple[KandaoTagPlan, tuple[KandaoEmissionGate, ...]]:
    definition = TAG_DEFINITIONS.get(tag_key)
    is_known = definition is not None or tag_key in RECORD_TABLES or tag_key == "GPS"
    tag_name = definition.tag_name if definition is not None else dynamic_tag_name(tag_key)
    role = role_for_tag(tag_key, definition, directory_name)
    family1_group = directory_name
    family2_group = definition.group2 if definition is not None else group2_for_role(role)
    read_format = definition.read_format if definition is not None else None
    if read_format is None:
        read_format = declared_format_name
    timed_records: tuple[KandaoTimedRecordPlan, ...] = ()
    value: KandaoDecodedValue | None
    gates: tuple[KandaoEmissionGate, ...] = ()
    sources = sources_for_tag(tag_key, is_known)

    record_spec = record_spec_for_tag(tag_key, raw_payload)
    if record_spec is not None:
        table, record_size, start_offset, source = record_spec
        timed_records, gates = parse_timed_records(
            tag_key,
            raw_payload,
            payload_range[0],
            table,
            record_size,
            start_offset,
            source,
        )
        value = None
        sources = unique_sources((*sources, source))
    elif should_preserve_binary(declared_format_code, element_count, read_format):
        value = raw_payload
    else:
        value = apply_value_conversion(
            tag_key,
            decode_payload(
                raw_payload, read_format, element_count_for_read(raw_payload, read_format)
            ),
        )

    return (
        KandaoTagPlan(
            index=index,
            tag_key=tag_key,
            tag_name=tag_name,
            directory_name=directory_name,
            family1_group=family1_group,
            family2_group=family2_group,
            role=role,
            declared_format_code=declared_format_code,
            declared_format_name=declared_format_name,
            read_format_name=read_format,
            element_count=element_count,
            payload_size=len(raw_payload),
            header_range=header_range,
            payload_range=payload_range,
            raw_payload=raw_payload,
            value=value,
            timed_records=timed_records,
            is_known=is_known,
            evidence_ids=sources,
        ),
        gates,
    )


def record_spec_for_tag(
    tag_key: str,
    payload: bytes,
) -> tuple[KandaoRecordTable, int, int, str] | None:
    if tag_key == "GPS":
        if payload.startswith(b"\xff\xff\xff\xff"):
            return "GPS", 28, 4, KANDAO_GPS_TABLE_SOURCE
        return "GPS", 20, 0, KANDAO_GPS_TABLE_SOURCE
    return RECORD_TABLES.get(tag_key)


def parse_timed_records(
    tag_key: str,
    payload: bytes,
    payload_absolute_offset: int,
    table: KandaoRecordTable,
    record_size: int,
    start_offset: int,
    source: str,
) -> tuple[tuple[KandaoTimedRecordPlan, ...], tuple[KandaoEmissionGate, ...]]:
    records: list[KandaoTimedRecordPlan] = []
    gates: list[KandaoEmissionGate] = []
    usable_length = len(payload) - start_offset
    if usable_length < 0 or usable_length % record_size:
        gates.append(
            KandaoEmissionGate(
                "malformed_kandao_record_payload",
                (
                    f"Kandao {tag_key} payload length {len(payload)} does not align to "
                    f"{record_size}-byte {table} records from start {start_offset}."
                ),
                payload_absolute_offset,
                True,
                (KANDAO_PROCESS_SOURCE, source),
            )
        )
    stop = start_offset + (usable_length // record_size) * record_size
    for index, cursor in enumerate(range(start_offset, stop, record_size)):
        record_payload = payload[cursor : cursor + record_size]
        records.append(
            KandaoTimedRecordPlan(
                table=table,
                index=index,
                record_range=(
                    payload_absolute_offset + cursor,
                    payload_absolute_offset + cursor + record_size,
                ),
                fields=fields_for_record(table, record_payload, cursor),
                evidence_ids=(source, KANDAO_PROCESS_SOURCE),
            )
        )
    return tuple(records), tuple(gates)


def fields_for_record(
    table: KandaoRecordTable,
    record_payload: bytes,
    base_offset: int,
) -> tuple[KandaoRecordFieldPlan, ...]:
    if table == "IMU":
        return (
            field("TimeStamp", base_offset, "int64u", read_int(record_payload[0:8], signed=False)),
            field("Gyroscope", base_offset + 8, "int16s", read_i16_tuple(record_payload[8:14])),
            field(
                "Accelerometer", base_offset + 14, "int16s", read_i16_tuple(record_payload[14:20])
            ),
        )
    if table == "GPS":
        fields = [
            field("TimeStamp", base_offset, "int32u", read_int(record_payload[0:4], signed=False)),
            field("GPSLatitude", base_offset + 4, "double", read_double(record_payload[4:12])),
            field("GPSLongitude", base_offset + 12, "double", read_double(record_payload[12:20])),
        ]
        if len(record_payload) >= 28:
            fields.append(
                field("GPSAltitude", base_offset + 20, "double", read_double(record_payload[20:28]))
            )
        return tuple(fields)
    if table == "GPSX":
        return (
            field("TimeStamp", base_offset, "int32u", read_int(record_payload[0:4], signed=False)),
            field(
                "GPSDateTime",
                base_offset + 4,
                "int64u",
                unix_millis_to_utc(read_int(record_payload[4:12], signed=False)),
            ),
            field("GPSLatitude", base_offset + 12, "double", read_double(record_payload[12:20])),
            field("GPSLongitude", base_offset + 20, "double", read_double(record_payload[20:28])),
            field("GPSAltitude", base_offset + 28, "double", read_double(record_payload[28:36])),
        )
    return (
        field("TimeStamp", base_offset, "int32u", read_int(record_payload[0:4], signed=False)),
        field("FrameISP_4", base_offset + 4, "float", read_float_tuple(record_payload[4:12])),
    )


def field(
    tag_name: str,
    offset: int,
    format_name: KandaoFormatName,
    value: KandaoDecodedValue,
) -> KandaoRecordFieldPlan:
    return KandaoRecordFieldPlan(
        tag_name=tag_name,
        offset=offset,
        format_name=format_name,
        value=value,
        evidence_ids=(KANDAO_PROCESS_SOURCE,),
    )


def metadata_entries_for_tag(tag: KandaoTagPlan) -> tuple[KandaoMetadataEntryPlan, ...]:
    if tag.role == "preserved_unknown":
        return ()
    entries = [
        KandaoMetadataEntryPlan(
            tag_key=tag.tag_key,
            tag_name=tag.tag_name,
            directory_name=tag.directory_name,
            family1_group=tag.family1_group,
            family2_group=tag.family2_group,
            role=tag.role,
            value=tag.value,
            raw_payload=tag.raw_payload,
            evidence_ids=tag.evidence_ids,
        )
    ]
    for record in tag.timed_records:
        for record_field in record.fields:
            entries.append(
                KandaoMetadataEntryPlan(
                    tag_key=tag.tag_key,
                    tag_name=record_field.tag_name,
                    directory_name=tag.directory_name,
                    family1_group="GPS" if record.table == "GPSX" else tag.family1_group,
                    family2_group="Location" if record.table in ("GPS", "GPSX", "IMU") else "Other",
                    role=tag.role,
                    value=record_field.value,
                    raw_payload=tag.raw_payload,
                    evidence_ids=unique_sources((*tag.evidence_ids, *record_field.evidence_ids)),
                )
            )
    return tuple(entries)


def decode_payload(
    payload: bytes,
    format_name: KandaoFormatName,
    element_count: int,
) -> KandaoDecodedValue | None:
    if not payload:
        return None
    if format_name == "undef":
        return payload
    if format_name == "string":
        return decode_header_text(payload)
    struct_format = STRUCT_FORMATS[format_name]
    size = FORMAT_SIZES[format_name]
    values: list[KandaoScalar] = []
    for cursor in range(0, min(len(payload), element_count * size), size):
        chunk = payload[cursor : cursor + size]
        if len(chunk) == size:
            values.append(struct.unpack(struct_format, chunk)[0])
    if len(values) == 1:
        return values[0]
    return tuple(values)


def apply_value_conversion(
    tag_key: str,
    value: KandaoDecodedValue | None,
) -> KandaoDecodedValue | None:
    if value is None:
        return None
    if tag_key == "CPU_TEMP" and isinstance(value, int | float):
        return value / 10
    if tag_key == "TOTAL_TIME_MS" and isinstance(value, int | float):
        return value / 1000
    if tag_key == "VIDEO_CAPTIME" and isinstance(value, str):
        return re.sub(r"^(\d{4})-(\d{2})-", r"\1:\2:", value)
    if tag_key == "GPS_CAPTIME" and isinstance(value, int | float):
        return unix_millis_to_utc(value)
    return value


def role_for_tag(
    tag_key: str,
    definition: _TagDefinition | None,
    directory_name: KandaoDirectoryName,
) -> KandaoMetadataRole:
    if tag_key == "IMU":
        return "imu_records"
    if tag_key == "GPS":
        return "gps_records"
    if tag_key == "GPSX":
        return "gpsx_records"
    if tag_key == "FRAME_ISP":
        return "frame_isp_records"
    if definition is None:
        return "preserved_unknown"
    if directory_name == "KSTB" and definition.role in ("kvar_scalar", "kfix_scalar"):
        return "kstb_scalar"
    return definition.role


def group2_for_role(role: KandaoMetadataRole) -> str:
    if role == "time_metadata":
        return "Time"
    if role in ("gps_records", "gpsx_records", "imu_records"):
        return "Location"
    if role == "frame_isp_records":
        return "Other"
    return "Camera"


def should_preserve_binary(
    declared_format_code: str,
    element_count: int,
    read_format: KandaoFormatName,
) -> bool:
    return read_format == "undef" or (declared_format_code == "U8" and element_count > 1)


def element_count_for_read(payload: bytes, format_name: KandaoFormatName) -> int:
    return len(payload) // FORMAT_SIZES[format_name]


def sources_for_tag(tag_key: str, is_known: bool) -> tuple[str, ...]:
    sources: list[str] = [KANDAO_PROCESS_SOURCE, KANDAO_FORMAT_SOURCE]
    if is_known:
        sources.append(KANDAO_MAIN_TABLE_SOURCE)
    return tuple(sources)


def default_responsibilities() -> tuple[KandaoPlanningResponsibility, ...]:
    return (
        KandaoPlanningResponsibility(
            "format_code_routing",
            "Route Kandao CHAR/BOOL/U/S/FLOAT/DOUBLE format strings to little-endian decoders.",
            (KANDAO_FORMAT_SOURCE, KANDAO_PROCESS_SOURCE),
        ),
        KandaoPlanningResponsibility(
            "kvar_table_routing",
            "Expose KVAR scalar, lens, PTS, IMU, GPS, GPSX, and FrameISP table entries.",
            (KANDAO_MAIN_TABLE_SOURCE,),
        ),
        KandaoPlanningResponsibility(
            "kfix_table_routing",
            "Expose KFIX model, version, capture time, video, exposure, and fan entries.",
            (KANDAO_MAIN_TABLE_SOURCE,),
        ),
        KandaoPlanningResponsibility(
            "kstb_group_routing",
            "Preserve the ProcessKandao family-1 group override for non-KVAR directories.",
            (KANDAO_MAIN_TABLE_SOURCE, KANDAO_PROCESS_SOURCE),
        ),
        KandaoPlanningResponsibility(
            "camera_scalar_fields",
            "Apply CPUTemperature and TotalTime conversions while preserving raw payload bytes.",
            (KANDAO_MAIN_TABLE_SOURCE,),
        ),
        KandaoPlanningResponsibility(
            "time_lens_model_version_fields",
            "Route capture time, GPS time, lens serial/index, model, serial, and version fields.",
            (KANDAO_MAIN_TABLE_SOURCE,),
        ),
        KandaoPlanningResponsibility(
            "timed_record_boundaries",
            (
                "Split IMU, GPS, GPSX, and FrameISP payloads on the record sizes "
                "declared by Kandao.pm."
            ),
            (
                KANDAO_IMU_TABLE_SOURCE,
                KANDAO_GPS_TABLE_SOURCE,
                KANDAO_GPSX_TABLE_SOURCE,
                KANDAO_FRAME_ISP_TABLE_SOURCE,
            ),
        ),
        KandaoPlanningResponsibility(
            "presentation_timestamp_binary_preservation",
            (
                "Keep PTS payload bytes intact because Kandao.pm marks "
                "PresentationTimeStamp as binary undef."
            ),
            (KANDAO_MAIN_TABLE_SOURCE,),
        ),
        KandaoPlanningResponsibility(
            "unknown_tag_preservation",
            "Retain raw payload and byte ranges for dynamically-added unknown Kandao tags.",
            (KANDAO_PROCESS_SOURCE,),
        ),
        KandaoPlanningResponsibility(
            "malformed_and_truncation_blockers",
            (
                "Gate output on truncated count/header/payload data, unknown "
                "formats, and record misalignment."
            ),
            (KANDAO_PROCESS_SOURCE,),
        ),
        KandaoPlanningResponsibility(
            "unsupported_rewrite_gates",
            (
                "Surface requested rewrites but block them because this slice has "
                "no source-backed writer."
            ),
            (KANDAO_PROCESS_SOURCE,),
        ),
        KandaoPlanningResponsibility(
            "non_mutating_defaults",
            "Default plans preserve input analysis only and never emit modified bytes.",
            (KANDAO_PROCESS_SOURCE,),
        ),
    )


def non_mutating_gates() -> tuple[KandaoEmissionGate, ...]:
    return (
        KandaoEmissionGate(
            "raw_payload_preservation_required",
            "Kandao transaction planning keeps raw typed payload bytes before any writer exists.",
            None,
            True,
            (KANDAO_PROCESS_SOURCE,),
        ),
        KandaoEmissionGate(
            "planner_is_non_mutating",
            "Kandao metadata transaction plans describe read-side extraction only.",
            None,
            True,
            (KANDAO_PROCESS_SOURCE,),
        ),
        KandaoEmissionGate(
            "kandao_writer_not_implemented",
            (
                "Kandao.pm is a read-side module; this modernization slice does "
                "not implement rewriting."
            ),
            None,
            True,
            (KANDAO_MAIN_TABLE_SOURCE, KANDAO_PROCESS_SOURCE),
        ),
    )


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for source in sources:
        key = source
        if key not in seen:
            seen.add(key)
            result.append(source)
    return tuple(result)


def unique_gates(gates: tuple[KandaoEmissionGate, ...]) -> tuple[KandaoEmissionGate, ...]:
    seen: set[tuple[KandaoEmissionGateCode, int | None, str]] = set()
    result: list[KandaoEmissionGate] = []
    for gate in gates:
        key = (gate.code, gate.offset, gate.reason)
        if key not in seen:
            seen.add(key)
            result.append(gate)
    return tuple(result)


def dynamic_tag_name(tag_key: str) -> str:
    pieces = tag_key.lower().split("_")
    return "".join(piece.capitalize() for piece in pieces if piece) or "KandaoTag"


def decode_header_text(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("latin-1")


def read_int(payload: bytes, *, signed: bool) -> int:
    return int.from_bytes(payload, "little", signed=signed)


def read_double(payload: bytes) -> float:
    return float(struct.unpack("<d", payload)[0])


def read_i16_tuple(payload: bytes) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(payload[index : index + 2], "little", signed=True)
        for index in range(0, len(payload), 2)
    )


def read_float_tuple(payload: bytes) -> tuple[float, ...]:
    return tuple(
        float(struct.unpack("<f", payload[index : index + 4])[0])
        for index in range(0, len(payload), 4)
    )


def unix_millis_to_utc(value: int | float) -> str:
    return (
        datetime.fromtimestamp(value / 1000, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
