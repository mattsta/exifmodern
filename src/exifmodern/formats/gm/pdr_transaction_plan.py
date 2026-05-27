"""Source-grounded, non-mutating GM Marlin/PDR transaction planning."""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from typing import Literal

GM_PM_SOURCE_PATH = "lib/Image/ExifTool/GM.pm"
MRLD_RECORD_SIZE = 448
MRLD_PARSED_PREFIX_SIZE = 256
MRLH_VERSION_SIZE = 4

type GmPdrValue = str | int | float | bytes
type GmPdrCsvCell = str | int | float
type GmPdrGroup = Literal["Header", "Time", "Location", "Channel", "Other"]
type GmPdrRecordKind = Literal["full", "delta", "empty", "ignored"]
type GmPdrActionKind = Literal[
    "parse_mrlh_header",
    "parse_mrlv_value",
    "record_mrld_channel",
    "route_marl_timestamp",
    "route_marl_channel",
    "preserve_payload",
    "plan_csv_route",
    "block_requested_rewrite",
]
type GmPdrResponsibilityKind = Literal[
    "mrlh_header_version",
    "mrlv_values",
    "mrld_channel_dictionary",
    "marl_timed_metadata",
    "unit_conversion_boundaries",
    "gps_location",
    "time_correlation",
    "csv_and_embedded_extraction_boundary",
    "payload_preservation",
    "malformed_and_truncation_blockers",
    "unsupported_rewrite_gate",
    "non_mutating_defaults",
]
type GmPdrBlockerCode = Literal[
    "truncated_mrlh_header",
    "unknown_mrlv_format",
    "truncated_mrlv_value",
    "trailing_mrlv_bytes",
    "truncated_mrld_record",
    "pdr_channel_zero_reserved",
    "missing_marl_dictionary",
    "truncated_marl_record",
    "unknown_marl_channel",
    "rewrite_requested_requires_gm_writer",
]
type GmPdrEmissionGateCode = Literal[
    "planner_is_non_mutating",
    "gm_writer_not_implemented",
    "rewrite_requested_requires_gm_writer",
    "malformed_pdr_stream_blocks_rewrite",
    "truncated_pdr_stream_blocks_rewrite",
]
type GmPdrRewriteOperation = Literal["upsert_tag", "delete_tag"]


GM_HEADER_SOURCE = "gm.header"
GM_MRLV_TABLE_SOURCE = "gm.mrlv.table"
GM_MRLV_PROCESS_SOURCE = "gm.mrlv.process"
GM_UNIT_SOURCE = "gm.unit"
GM_CHANNEL_SOURCE = "gm.channel"
GM_MRLD_TABLE_SOURCE = "gm.mrld.table"
GM_MRLD_PROCESS_SOURCE = "gm.mrld.process"
GM_MARL_TABLE_SOURCE = "gm.marl.table"
GM_CSV_SOURCE = "gm.csv"
GM_MARL_PROCESS_SOURCE = "gm.marl.process"
GM_READ_ONLY_SOURCE = "gm.read.only"

GM_TRANSACTION_SOURCES = (
    GM_HEADER_SOURCE,
    GM_MRLV_TABLE_SOURCE,
    GM_MRLV_PROCESS_SOURCE,
    GM_UNIT_SOURCE,
    GM_CHANNEL_SOURCE,
    GM_MRLD_TABLE_SOURCE,
    GM_MRLD_PROCESS_SOURCE,
    GM_MARL_TABLE_SOURCE,
    GM_CSV_SOURCE,
    GM_MARL_PROCESS_SOURCE,
    GM_READ_ONLY_SOURCE,
)

MRLV_FORMAT_LENGTHS: dict[bytes, int] = {
    b"strs": 64,
    b"lang": 64,
    b"strl": 256,
    b"time": 32,
    b"date": 32,
    b"tmzn": 32,
    b"tstm": 8,
    b"focc": 4,
    b"kvp\0": 320,
}

MRLV_TAGS: dict[bytes, tuple[str, GmPdrGroup]] = {
    b"time": ("Time1", "Time"),
    b"date": ("Date1", "Time"),
    b"ltim": ("Time2", "Time"),
    b"ldat": ("Date2", "Time"),
    b"tstm": ("StartTime", "Time"),
    b"zone": ("TimeZone", "Time"),
    b"lang": ("Language", "Other"),
    b"unit": ("Units", "Other"),
    b"swvs": ("SoftwareVersion", "Other"),
}

CONVERT_UNITS: dict[str, str] = {
    "°": "deg",
    "°C": "C",
    "°/sec": "deg/sec",
    "ltr": "L",
}
CHANGE_OFFSET: dict[str, float] = {"C": -273.15}
CHANGE_SCALE: dict[str, float] = {
    "G": 1 / 9.80665,
    "kph": 3.6,
    "deg": 180 / math.pi,
    "deg/sec": 180 / math.pi,
    "%": 100,
    "kPa": 1 / 1000,
    "rpm": 10,
    "km": 1 / 1000,
    "L": 1000,
    "mm": 1000,
}

MARL_ROUTE_OVERRIDES: dict[str, tuple[str, GmPdrGroup]] = {
    "Latitude": ("GPSLatitude", "Location"),
    "Longitude": ("GPSLongitude", "Location"),
    "Altitude": ("GPSAltitude", "Location"),
    "Heading": ("GPSTrack", "Location"),
    "Speed": ("Speed", "Location"),
}
GEAR_CSV_CONVERSION: dict[float, int] = {13: -1, 14: -100}


@dataclass(frozen=True)
class GmPdrAtomPayloads:
    mrlh: bytes = b""
    mrlv: bytes = b""
    mrld: bytes = b""
    marl_samples: tuple[bytes, ...] = ()


@dataclass(frozen=True)
class GmPdrRewriteRequest:
    operation: GmPdrRewriteOperation
    tag_name: str
    value: GmPdrValue | None = None


@dataclass(frozen=True)
class GmPdrTransactionBlocker:
    code: GmPdrBlockerCode
    reason: str
    atom: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GmPdrOutputEmissionGate:
    code: GmPdrEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GmPdrActionPlan:
    action: GmPdrActionKind
    target: str
    atom: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GmPdrMrlhPlan:
    marlin_data_version: str | None
    version_parts: tuple[int, int] | None
    payload_range: tuple[int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GmPdrMrlvValuePlan:
    tag_id: str
    tag_name: str
    format_id: str
    group: GmPdrGroup
    value: GmPdrValue
    raw_value: bytes
    byte_range: tuple[int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GmPdrChannelPlan:
    channel_id: int
    tag_name: str
    measurement_type: int
    units_number: int
    units: str
    normalized_units: str
    flags: int
    interval_100ns: int
    min_raw: int
    max_raw: int
    display_min: float
    display_max: float
    multiplier: float
    offset: float
    effective_multiplier: float
    effective_offset: float
    initial_delta_value: int
    source_name: str
    description: str
    record_range: tuple[int, int]
    preserved_payload: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GmPdrTimedValuePlan:
    sample_index: int
    record_kind: GmPdrRecordKind
    tag_name: str
    group: GmPdrGroup
    channel_id: int | None
    timestamp_100ns: int
    timestamp_seconds: float
    raw_value: int
    scaled_value: float
    record_range: tuple[int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GmPdrMarlRecordPlan:
    sample_index: int
    record_kind: GmPdrRecordKind
    channel_id: int | None
    timestamp_100ns: int | None
    raw_value: int | None
    record_range: tuple[int, int]
    preserved_payload: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GmPdrCsvRoutePlan:
    header: tuple[str, ...]
    rows: tuple[tuple[GmPdrCsvCell, ...], ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GmPdrResponsibilityPlan:
    kind: GmPdrResponsibilityKind
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GmPdrTransactionPlan:
    source_payloads: GmPdrAtomPayloads
    mrlh: GmPdrMrlhPlan
    mrlv_values: tuple[GmPdrMrlvValuePlan, ...]
    channels: tuple[GmPdrChannelPlan, ...]
    marl_records: tuple[GmPdrMarlRecordPlan, ...]
    timed_values: tuple[GmPdrTimedValuePlan, ...]
    csv_route: GmPdrCsvRoutePlan | None
    actions: tuple[GmPdrActionPlan, ...]
    responsibilities: tuple[GmPdrResponsibilityPlan, ...]
    rewrite_requests: tuple[GmPdrRewriteRequest, ...]
    blockers: tuple[GmPdrTransactionBlocker, ...]
    output_emission_gates: tuple[GmPdrOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not self.output_emission_gates

    def emit(self) -> GmPdrAtomPayloads:
        if self.output_emission_gates:
            codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"GM PDR transaction output is gated: {codes}")
        return self.source_payloads


def build_gm_pdr_transaction_plan(
    source_payloads: GmPdrAtomPayloads,
    rewrite_requests: tuple[GmPdrRewriteRequest, ...] = (),
    *,
    request_gps_datetime: bool = False,
    request_timestamp: bool = True,
    print_csv: bool = False,
) -> GmPdrTransactionPlan:
    blockers: list[GmPdrTransactionBlocker] = []
    actions: list[GmPdrActionPlan] = []
    mrlh = _parse_mrlh(source_payloads.mrlh, blockers, actions)
    mrlv_values = _parse_mrlv(source_payloads.mrlv, blockers, actions)
    channels = _parse_mrld(source_payloads.mrld, blockers, actions)
    dictionary, dictionary_available = _channel_dictionary(channels, blockers)
    csv_route = _csv_header(channels) if print_csv and dictionary_available else None
    marl_records: list[GmPdrMarlRecordPlan] = []
    timed_values: list[GmPdrTimedValuePlan] = []
    csv_rows: list[tuple[GmPdrCsvCell, ...]] = []
    start_time_seconds = _start_time_seconds(mrlv_values)

    if source_payloads.marl_samples and not dictionary_available:
        blockers.append(
            GmPdrTransactionBlocker(
                "missing_marl_dictionary",
                "Process_marl requires the Marlin dictionary built by Process_mrld.",
                "marl",
                None,
                (GM_MRLD_PROCESS_SOURCE, GM_MARL_PROCESS_SOURCE),
            )
        )
    elif source_payloads.marl_samples:
        _parse_marl_samples(
            source_payloads.marl_samples,
            dictionary,
            start_time_seconds,
            request_gps_datetime,
            request_timestamp,
            print_csv,
            marl_records,
            timed_values,
            csv_rows,
            blockers,
            actions,
        )

    if csv_route is not None:
        csv_route = GmPdrCsvRoutePlan(csv_route.header, tuple(csv_rows), csv_route.evidence_ids)
        actions.append(
            GmPdrActionPlan("plan_csv_route", "PrintCSV", "marl", None, (GM_CSV_SOURCE,))
        )

    if rewrite_requests:
        blockers.append(
            GmPdrTransactionBlocker(
                "rewrite_requested_requires_gm_writer",
                "GM.pm provides read-side PDR routing only; this slice does not rewrite.",
                "gm",
                None,
                (GM_READ_ONLY_SOURCE,),
            )
        )
        actions.append(
            GmPdrActionPlan(
                "block_requested_rewrite",
                "rewrite request",
                "gm",
                None,
                (GM_READ_ONLY_SOURCE,),
            )
        )

    return GmPdrTransactionPlan(
        source_payloads,
        mrlh,
        tuple(mrlv_values),
        channels,
        tuple(marl_records),
        tuple(timed_values),
        csv_route,
        tuple(actions),
        _responsibilities(),
        rewrite_requests,
        tuple(blockers),
        tuple(_output_gates(blockers, rewrite_requests)),
        GM_TRANSACTION_SOURCES,
    )


def _parse_mrlh(
    payload: bytes,
    blockers: list[GmPdrTransactionBlocker],
    actions: list[GmPdrActionPlan],
) -> GmPdrMrlhPlan:
    actions.append(
        GmPdrActionPlan(
            "parse_mrlh_header",
            "MarlinDataVersion",
            "mrlh",
            (0, min(len(payload), MRLH_VERSION_SIZE)),
            (GM_HEADER_SOURCE,),
        )
    )
    if len(payload) < MRLH_VERSION_SIZE:
        if payload:
            blockers.append(
                GmPdrTransactionBlocker(
                    "truncated_mrlh_header",
                    "MarlinDataVersion requires two unsigned 16-bit values.",
                    "mrlh",
                    (0, len(payload)),
                    (GM_HEADER_SOURCE,),
                )
            )
        return GmPdrMrlhPlan(None, None, (0, len(payload)), (GM_HEADER_SOURCE,))
    parts = (
        int.from_bytes(payload[0:2], "big"),
        int.from_bytes(payload[2:4], "big"),
    )
    return GmPdrMrlhPlan(f"{parts[0]}.{parts[1]}", parts, (0, 4), (GM_HEADER_SOURCE,))


def _parse_mrlv(
    payload: bytes,
    blockers: list[GmPdrTransactionBlocker],
    actions: list[GmPdrActionPlan],
) -> list[GmPdrMrlvValuePlan]:
    values: list[GmPdrMrlvValuePlan] = []
    pos = 0
    while pos + 8 <= len(payload):
        tag = payload[pos : pos + 4]
        fmt = payload[pos + 4 : pos + 8]
        size = MRLV_FORMAT_LENGTHS.get(fmt)
        if size is None:
            blockers.append(
                GmPdrTransactionBlocker(
                    "unknown_mrlv_format",
                    f"Unknown mrlv format {_printable_id(fmt)} for tag {_printable_id(tag)}.",
                    "mrlv",
                    (pos, pos + 8),
                    (GM_MRLV_PROCESS_SOURCE,),
                )
            )
            break
        value_start = pos + 8
        value_end = value_start + size
        if value_end > len(payload):
            blockers.append(
                GmPdrTransactionBlocker(
                    "truncated_mrlv_value",
                    "The mrlv value is shorter than its fixed format length.",
                    "mrlv",
                    (pos, len(payload)),
                    (GM_MRLV_PROCESS_SOURCE,),
                )
            )
            break
        tag_name, group = MRLV_TAGS.get(tag, (_printable_id(tag), "Other"))
        raw_value = payload[value_start:value_end]
        value = _mrlv_value(tag, fmt, raw_value)
        values.append(
            GmPdrMrlvValuePlan(
                _printable_id(tag),
                tag_name,
                _printable_id(fmt),
                group,
                value,
                raw_value,
                (pos, value_end),
                (GM_MRLV_TABLE_SOURCE, GM_MRLV_PROCESS_SOURCE),
            )
        )
        actions.append(
            GmPdrActionPlan(
                "parse_mrlv_value",
                tag_name,
                "mrlv",
                (pos, value_end),
                (GM_MRLV_TABLE_SOURCE, GM_MRLV_PROCESS_SOURCE),
            )
        )
        pos = value_end
    if pos < len(payload) and not blockers:
        blockers.append(
            GmPdrTransactionBlocker(
                "trailing_mrlv_bytes",
                "Trailing mrlv bytes are too short for a tag and format header.",
                "mrlv",
                (pos, len(payload)),
                (GM_MRLV_PROCESS_SOURCE,),
            )
        )
    return values


def _parse_mrld(
    payload: bytes,
    blockers: list[GmPdrTransactionBlocker],
    actions: list[GmPdrActionPlan],
) -> tuple[GmPdrChannelPlan, ...]:
    channels: list[GmPdrChannelPlan] = []
    pos = 0
    while pos + MRLD_RECORD_SIZE <= len(payload):
        record = payload[pos : pos + MRLD_RECORD_SIZE]
        parsed_prefix = record[:MRLD_PARSED_PREFIX_SIZE]
        channel_id = int.from_bytes(parsed_prefix[0:4], "big")
        measurement_type = int.from_bytes(parsed_prefix[4:8], "big")
        units_number = int.from_bytes(parsed_prefix[8:12], "big")
        units = _decode_c_string(parsed_prefix[12:76])
        normalized_units = CONVERT_UNITS.get(units, units)
        flags = int.from_bytes(parsed_prefix[76:80], "big")
        interval = int.from_bytes(parsed_prefix[80:88], "big")
        min_raw = int.from_bytes(parsed_prefix[88:92], "big", signed=True)
        max_raw = int.from_bytes(parsed_prefix[92:96], "big", signed=True)
        display_min = struct.unpack(">d", parsed_prefix[96:104])[0]
        display_max = struct.unpack(">d", parsed_prefix[104:112])[0]
        multiplier = struct.unpack(">d", parsed_prefix[112:120])[0]
        offset = struct.unpack(">d", parsed_prefix[120:128])[0]
        source_name = _decode_c_string(parsed_prefix[128:192])
        description = _decode_c_string(parsed_prefix[192:256])
        scale = CHANGE_SCALE.get(normalized_units, 1.0)
        effective_multiplier = multiplier * scale
        effective_offset = offset * scale + CHANGE_OFFSET.get(normalized_units, 0.0)
        channel = GmPdrChannelPlan(
            channel_id,
            _make_tag_name(source_name),
            measurement_type,
            units_number,
            units,
            normalized_units,
            flags,
            interval,
            min_raw,
            max_raw,
            display_min,
            display_max,
            multiplier,
            offset,
            effective_multiplier,
            effective_offset,
            int((min_raw + max_raw) / 2),
            source_name,
            description,
            (pos, pos + MRLD_RECORD_SIZE),
            record,
            (GM_CHANNEL_SOURCE, GM_MRLD_PROCESS_SOURCE, GM_UNIT_SOURCE),
        )
        channels.append(channel)
        actions.append(
            GmPdrActionPlan(
                "record_mrld_channel",
                channel.tag_name,
                "mrld",
                channel.record_range,
                (GM_CHANNEL_SOURCE, GM_MRLD_PROCESS_SOURCE),
            )
        )
        pos += MRLD_RECORD_SIZE
    if pos < len(payload):
        blockers.append(
            GmPdrTransactionBlocker(
                "truncated_mrld_record",
                "Process_mrld reads only complete 448-byte channel records.",
                "mrld",
                (pos, len(payload)),
                (GM_MRLD_PROCESS_SOURCE,),
            )
        )
    return tuple(channels)


def _channel_dictionary(
    channels: tuple[GmPdrChannelPlan, ...],
    blockers: list[GmPdrTransactionBlocker],
) -> tuple[list[GmPdrChannelPlan | None], bool]:
    if not channels:
        return [], False
    max_channel = max(channel.channel_id for channel in channels)
    dictionary: list[GmPdrChannelPlan | None] = [None] * (max_channel + 1)
    for channel in channels:
        dictionary[channel.channel_id] = channel
    if dictionary[0] is not None:
        blockers.append(
            GmPdrTransactionBlocker(
                "pdr_channel_zero_reserved",
                "Process_mrld reserves channel 0 for TimeStamp and drops the dictionary if used.",
                "mrld",
                dictionary[0].record_range,
                (GM_MRLD_PROCESS_SOURCE, GM_MARL_PROCESS_SOURCE),
            )
        )
        return dictionary, False
    return dictionary, True


def _parse_marl_samples(
    samples: tuple[bytes, ...],
    dictionary: list[GmPdrChannelPlan | None],
    start_time_seconds: float | None,
    request_gps_datetime: bool,
    request_timestamp: bool,
    print_csv: bool,
    marl_records: list[GmPdrMarlRecordPlan],
    timed_values: list[GmPdrTimedValuePlan],
    csv_rows: list[tuple[GmPdrCsvCell, ...]],
    blockers: list[GmPdrTransactionBlocker],
    actions: list[GmPdrActionPlan],
) -> None:
    running_values: dict[int, int] = {0: -1}
    running_channel: int | None = None
    timestamp = -1
    max_timestamp = 0
    pending_csv_channels: list[int] = []
    for sample_index, payload in enumerate(samples):
        pos = 0
        while pos + 8 <= len(payload):
            record_start = pos
            first = int.from_bytes(payload[pos : pos + 4], "big")
            second = int.from_bytes(payload[pos + 4 : pos + 8], "big")
            high = first >> 24
            marker = high & 0xC0
            if marker == 0xC0:
                if high == 0xFF:
                    marl_records.append(
                        GmPdrMarlRecordPlan(
                            sample_index,
                            "empty",
                            None,
                            None,
                            None,
                            (record_start, record_start + 8),
                            payload[record_start : record_start + 8],
                            (GM_MARL_PROCESS_SOURCE,),
                        )
                    )
                    break
                channel_id = first & 0x0FFFFFFF
                raw_value = _signed32(second)
                running_values[channel_id] = raw_value
                if pos + 16 > len(payload):
                    blockers.append(
                        GmPdrTransactionBlocker(
                            "truncated_marl_record",
                            "A full marl record requires an 8-byte timestamp after its value.",
                            "marl",
                            (record_start, len(payload)),
                            (GM_MARL_PROCESS_SOURCE,),
                        )
                    )
                    pos = len(payload)
                    break
                timestamp = int.from_bytes(payload[pos + 8 : pos + 16], "big")
                running_channel = channel_id
                pos += 16
                _record_marl_value(
                    sample_index,
                    "full",
                    channel_id,
                    raw_value,
                    timestamp,
                    record_start,
                    pos,
                    payload,
                    dictionary,
                    start_time_seconds,
                    request_gps_datetime,
                    request_timestamp,
                    print_csv,
                    running_values,
                    pending_csv_channels,
                    csv_rows,
                    max_timestamp,
                    marl_records,
                    timed_values,
                    blockers,
                    actions,
                )
                if timestamp > max_timestamp:
                    max_timestamp = timestamp
                continue
            if marker == 0x40:
                if running_channel is None:
                    marl_records.append(
                        GmPdrMarlRecordPlan(
                            sample_index,
                            "ignored",
                            None,
                            None,
                            None,
                            (record_start, record_start + 8),
                            payload[record_start : record_start + 8],
                            (GM_MARL_PROCESS_SOURCE,),
                        )
                    )
                    pos += 8
                    continue
                timestamp += second
                channel_diff = (high & 0x3F) - (0x40 if high & 0x20 else 0)
                channel_id = running_channel + channel_diff
                channel = _channel_at(dictionary, channel_id)
                if channel is None:
                    blockers.append(
                        GmPdrTransactionBlocker(
                            "unknown_marl_channel",
                            f"marl delta record routed to missing channel {channel_id}.",
                            "marl",
                            (record_start, record_start + 8),
                            (GM_MARL_PROCESS_SOURCE,),
                        )
                    )
                    pos += 8
                    continue
                if channel_id not in running_values:
                    running_values[channel_id] = channel.initial_delta_value
                value_diff = (first & 0x00FFFFFF) - (0x01000000 if first & 0x00800000 else 0)
                raw_value = running_values[channel_id] + value_diff
                running_values[channel_id] = raw_value
                running_channel = channel_id
                pos += 8
                _record_marl_value(
                    sample_index,
                    "delta",
                    channel_id,
                    raw_value,
                    timestamp,
                    record_start,
                    pos,
                    payload,
                    dictionary,
                    start_time_seconds,
                    request_gps_datetime,
                    request_timestamp,
                    print_csv,
                    running_values,
                    pending_csv_channels,
                    csv_rows,
                    max_timestamp,
                    marl_records,
                    timed_values,
                    blockers,
                    actions,
                )
                if timestamp > max_timestamp:
                    max_timestamp = timestamp
                continue
            marl_records.append(
                GmPdrMarlRecordPlan(
                    sample_index,
                    "ignored",
                    None,
                    timestamp,
                    None,
                    (record_start, record_start + 8),
                    payload[record_start : record_start + 8],
                    (GM_MARL_PROCESS_SOURCE,),
                )
            )
            pos += 8
        sample_ended_on_empty = (
            bool(marl_records)
            and marl_records[-1].record_kind == "empty"
            and marl_records[-1].sample_index == sample_index
        )
        if pos < len(payload) and not sample_ended_on_empty:
            blockers.append(
                GmPdrTransactionBlocker(
                    "truncated_marl_record",
                    "Trailing marl bytes are shorter than one 8-byte record.",
                    "marl",
                    (pos, len(payload)),
                    (GM_MARL_PROCESS_SOURCE,),
                )
            )
    if print_csv and pending_csv_channels:
        csv_rows.append(_csv_row(dictionary, running_values, max_timestamp, pending_csv_channels))


def _record_marl_value(
    sample_index: int,
    record_kind: GmPdrRecordKind,
    channel_id: int,
    raw_value: int,
    timestamp: int,
    record_start: int,
    record_end: int,
    payload: bytes,
    dictionary: list[GmPdrChannelPlan | None],
    start_time_seconds: float | None,
    request_gps_datetime: bool,
    request_timestamp: bool,
    print_csv: bool,
    running_values: dict[int, int],
    pending_csv_channels: list[int],
    csv_rows: list[tuple[GmPdrCsvCell, ...]],
    max_timestamp: int,
    marl_records: list[GmPdrMarlRecordPlan],
    timed_values: list[GmPdrTimedValuePlan],
    blockers: list[GmPdrTransactionBlocker],
    actions: list[GmPdrActionPlan],
) -> None:
    channel = _channel_at(dictionary, channel_id)
    if channel is None:
        blockers.append(
            GmPdrTransactionBlocker(
                "unknown_marl_channel",
                f"marl record routed to missing channel {channel_id}.",
                "marl",
                (record_start, record_end),
                (GM_MARL_PROCESS_SOURCE,),
            )
        )
        return
    marl_records.append(
        GmPdrMarlRecordPlan(
            sample_index,
            record_kind,
            channel_id,
            timestamp,
            raw_value,
            (record_start, record_end),
            payload[record_start:record_end],
            (GM_MARL_PROCESS_SOURCE,),
        )
    )
    if timestamp > max_timestamp:
        if print_csv:
            if pending_csv_channels:
                csv_rows.append(
                    _csv_row(dictionary, running_values, max_timestamp, pending_csv_channels)
                )
                pending_csv_channels.clear()
        else:
            _append_timestamp_values(
                sample_index,
                record_kind,
                timestamp,
                record_start,
                record_end,
                request_gps_datetime,
                request_timestamp,
                start_time_seconds,
                timed_values,
                actions,
            )
    if print_csv:
        pending_csv_channels.append(channel_id)
        return
    tag_name, group = MARL_ROUTE_OVERRIDES.get(channel.tag_name, (channel.tag_name, "Other"))
    scaled = raw_value * channel.effective_multiplier + channel.effective_offset
    timed_values.append(
        GmPdrTimedValuePlan(
            sample_index,
            record_kind,
            tag_name,
            group,
            channel_id,
            timestamp,
            timestamp / 1e7,
            raw_value,
            scaled,
            (record_start, record_end),
            (GM_MARL_TABLE_SOURCE, GM_MARL_PROCESS_SOURCE, GM_UNIT_SOURCE),
        )
    )
    actions.append(
        GmPdrActionPlan(
            "route_marl_channel",
            tag_name,
            "marl",
            (record_start, record_end),
            (GM_MARL_TABLE_SOURCE, GM_MARL_PROCESS_SOURCE),
        )
    )


def _append_timestamp_values(
    sample_index: int,
    record_kind: GmPdrRecordKind,
    timestamp: int,
    record_start: int,
    record_end: int,
    request_gps_datetime: bool,
    request_timestamp: bool,
    start_time_seconds: float | None,
    timed_values: list[GmPdrTimedValuePlan],
    actions: list[GmPdrActionPlan],
) -> None:
    if request_timestamp:
        timed_values.append(
            GmPdrTimedValuePlan(
                sample_index,
                record_kind,
                "TimeStamp",
                "Time",
                None,
                timestamp,
                timestamp / 1e7,
                timestamp,
                timestamp / 1e7,
                (record_start, record_end),
                (GM_MARL_TABLE_SOURCE, GM_MARL_PROCESS_SOURCE),
            )
        )
        actions.append(
            GmPdrActionPlan(
                "route_marl_timestamp",
                "TimeStamp",
                "marl",
                (record_start, record_end),
                (GM_MARL_TABLE_SOURCE, GM_MARL_PROCESS_SOURCE),
            )
        )
    if request_gps_datetime and start_time_seconds is not None:
        seconds = timestamp / 1e7 + start_time_seconds
        timed_values.append(
            GmPdrTimedValuePlan(
                sample_index,
                record_kind,
                "GPSDateTime",
                "Time",
                None,
                timestamp,
                seconds,
                timestamp,
                seconds,
                (record_start, record_end),
                (GM_MARL_TABLE_SOURCE, GM_MARL_PROCESS_SOURCE, GM_MRLV_TABLE_SOURCE),
            )
        )


def _csv_header(channels: tuple[GmPdrChannelPlan, ...]) -> GmPdrCsvRoutePlan:
    max_channel = max((channel.channel_id for channel in channels), default=0)
    header = [""] * (max_channel + 1)
    header[0] = "Time (s)"
    for channel in channels:
        suffix = f" ({channel.units})" if channel.units else ""
        header[channel.channel_id] = f"{channel.source_name}{suffix}"
    return GmPdrCsvRoutePlan(tuple(header), (), (GM_CSV_SOURCE, GM_MRLD_PROCESS_SOURCE))


def _csv_row(
    dictionary: list[GmPdrChannelPlan | None],
    running_values: dict[int, int],
    timestamp: int,
    pending_channels: list[int],
) -> tuple[GmPdrCsvCell, ...]:
    items: list[GmPdrCsvCell] = [""] * len(dictionary)
    items[0] = timestamp / 1e7
    for channel_id in pending_channels:
        channel = _channel_at(dictionary, channel_id)
        if channel is None:
            continue
        raw_value = running_values.get(channel_id)
        if raw_value is None:
            continue
        scaled = raw_value * channel.effective_multiplier + channel.effective_offset
        if channel.tag_name == "Gear":
            items[channel_id] = GEAR_CSV_CONVERSION.get(scaled, scaled)
        else:
            items[channel_id] = scaled
    return tuple(items)


def _mrlv_value(tag: bytes, fmt: bytes, raw: bytes) -> GmPdrValue:
    if fmt == b"tstm":
        return int.from_bytes(raw, "big")
    if fmt == b"focc":
        return int.from_bytes(raw, "big")
    text = _decode_c_string(raw)
    if tag in {b"time", b"date", b"ltim", b"ldat"}:
        return text.replace("-", ":")
    if tag == b"unit" and text == "usim":
        return "U.S. Imperial"
    return text


def _start_time_seconds(values: list[GmPdrMrlvValuePlan]) -> float | None:
    for value in values:
        if value.tag_name == "StartTime" and isinstance(value.value, int):
            return value.value / 1e7
    return None


def _channel_at(
    dictionary: list[GmPdrChannelPlan | None], channel_id: int
) -> GmPdrChannelPlan | None:
    if channel_id < 0 or channel_id >= len(dictionary):
        return None
    return dictionary[channel_id]


def _signed32(value: int) -> int:
    return value - 4294967296 if value & 0x80000000 else value


def _decode_c_string(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def _printable_id(value: bytes) -> str:
    return "".join(chr(item) if 32 <= item <= 126 else f"\\x{item:02x}" for item in value)


def _make_tag_name(value: str) -> str:
    parts = [part for part in re.split(r"[^0-9A-Za-z]+", value) if part]
    return "".join(part if part.isupper() else part[:1].upper() + part[1:] for part in parts)


def _output_gates(
    blockers: list[GmPdrTransactionBlocker],
    rewrite_requests: tuple[GmPdrRewriteRequest, ...],
) -> list[GmPdrOutputEmissionGate]:
    gates = [
        GmPdrOutputEmissionGate(
            "planner_is_non_mutating",
            "This GM PDR planner records routes and blockers but does not mutate bytes.",
            (GM_READ_ONLY_SOURCE,),
        ),
        GmPdrOutputEmissionGate(
            "gm_writer_not_implemented",
            "GM.pm provides no PDR writer for this modernization slice to port.",
            (GM_READ_ONLY_SOURCE,),
        ),
    ]
    if rewrite_requests:
        gates.append(
            GmPdrOutputEmissionGate(
                "rewrite_requested_requires_gm_writer",
                "Requested GM PDR metadata writes are blocked until a writer exists.",
                (GM_READ_ONLY_SOURCE,),
            )
        )
    if any(
        blocker.code.startswith("truncated_") or blocker.code == "trailing_mrlv_bytes"
        for blocker in blockers
    ):
        gates.append(
            GmPdrOutputEmissionGate(
                "truncated_pdr_stream_blocks_rewrite",
                "Truncated GM PDR data must not be rewritten.",
                (GM_MRLV_PROCESS_SOURCE, GM_MRLD_PROCESS_SOURCE, GM_MARL_PROCESS_SOURCE),
            )
        )
    if any(
        blocker.code
        in {
            "unknown_mrlv_format",
            "pdr_channel_zero_reserved",
            "missing_marl_dictionary",
            "unknown_marl_channel",
        }
        for blocker in blockers
    ):
        gates.append(
            GmPdrOutputEmissionGate(
                "malformed_pdr_stream_blocks_rewrite",
                "Malformed GM PDR structure blocks rewrite planning.",
                (GM_MRLD_PROCESS_SOURCE, GM_MARL_PROCESS_SOURCE),
            )
        )
    return gates


def _responsibilities() -> tuple[GmPdrResponsibilityPlan, ...]:
    return (
        GmPdrResponsibilityPlan(
            "mrlh_header_version",
            "mrlh contributes the two-part MarlinDataVersion header.",
            (GM_HEADER_SOURCE,),
        ),
        GmPdrResponsibilityPlan(
            "mrlv_values",
            "mrlv contributes fixed-format time, unit, language, timezone, and software values.",
            (GM_MRLV_TABLE_SOURCE, GM_MRLV_PROCESS_SOURCE),
        ),
        GmPdrResponsibilityPlan(
            "mrld_channel_dictionary",
            "mrld contributes channel definitions used to name and scale timed PDR samples.",
            (GM_CHANNEL_SOURCE, GM_MRLD_PROCESS_SOURCE),
        ),
        GmPdrResponsibilityPlan(
            "marl_timed_metadata",
            "marl contributes full and delta timed samples routed through the channel dictionary.",
            (GM_MARL_TABLE_SOURCE, GM_MARL_PROCESS_SOURCE),
        ),
        GmPdrResponsibilityPlan(
            "unit_conversion_boundaries",
            "Unit renames, scale factors, and offsets are applied only at channel sample routing.",
            (GM_UNIT_SOURCE, GM_MRLD_PROCESS_SOURCE),
        ),
        GmPdrResponsibilityPlan(
            "gps_location",
            "Latitude, Longitude, Altitude, Heading, and Speed route to location-group tags.",
            (GM_MARL_TABLE_SOURCE,),
        ),
        GmPdrResponsibilityPlan(
            "time_correlation",
            "StartTime from mrlv and TimeStamp/GPSDateTime from marl define time responsibilities.",
            (GM_MRLV_TABLE_SOURCE, GM_MARL_TABLE_SOURCE, GM_MARL_PROCESS_SOURCE),
        ),
        GmPdrResponsibilityPlan(
            "csv_and_embedded_extraction_boundary",
            "Timed marl metadata is an embedded route, while PrintCSV switches sample handling "
            "to rows.",
            (GM_MARL_TABLE_SOURCE, GM_CSV_SOURCE),
        ),
        GmPdrResponsibilityPlan(
            "payload_preservation",
            "Atom payloads and timed record byte ranges are preserved by the plan.",
            (GM_MRLV_PROCESS_SOURCE, GM_MRLD_PROCESS_SOURCE, GM_MARL_PROCESS_SOURCE),
        ),
        GmPdrResponsibilityPlan(
            "malformed_and_truncation_blockers",
            "Unknown formats, reserved channel 0, missing dictionaries, and truncations become "
            "blockers.",
            (GM_MRLV_PROCESS_SOURCE, GM_MRLD_PROCESS_SOURCE, GM_MARL_PROCESS_SOURCE),
        ),
        GmPdrResponsibilityPlan(
            "unsupported_rewrite_gate",
            "GM PDR rewrite remains gated because this source module has no writer path.",
            (GM_READ_ONLY_SOURCE,),
        ),
        GmPdrResponsibilityPlan(
            "non_mutating_defaults",
            "The default plan is read-side only and keeps source payload bytes unchanged.",
            (GM_READ_ONLY_SOURCE,),
        ),
    )
