"""Source-backed, non-mutating LIGOGPSINFO transaction planning."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonValue

LIGOGPS_PM_SOURCE_PATH = "lib/Image/ExifTool/LigoGPS.pm"
LIGOGPS_SIGNATURE = b"LIGOGPSINFO\x00"
LIGOGPS_JSON_SIGNATURE = b"LIGOGPSINFO {"
LIGOGPS_RECORD_OFFSET = 0x14
LIGOGPS_RECORD_SIZE = 0x84
KNOTS_TO_KPH = 1.852

type LigoGpsPlanStatus = Literal["planned", "unsupported"]
type LigoGpsHeaderKind = Literal["fixed_records", "json_trailer", "unknown"]
type LigoGpsRecordKind = Literal[
    "plaintext",
    "encrypted",
    "blank",
    "unrecognized",
    "truncated_tail",
]
type LigoGpsResponsibilityKind = Literal[
    "sample",
    "gps_time",
    "local_time",
    "location",
    "original_location",
    "speed",
    "track",
    "altitude",
    "magnetic_variation",
    "accelerometer",
]
type LigoGpsValue = str | int | float | tuple[float, float]
type LigoGpsRewriteOperation = Literal["replace_record", "delete_record", "insert_record"]
type LigoGpsActionKind = Literal[
    "validate_header",
    "enumerate_fixed_record",
    "enumerate_json_packet",
    "route_record_tags",
    "preserve_record",
    "preserve_packet",
    "preserve_trailing_payload",
    "block_requested_rewrite",
]
type LigoGpsBlockerCode = Literal[
    "truncated_ligogps_header",
    "unsupported_ligogps_header",
    "truncated_ligogps_record",
    "ligogps_record_format_error",
    "encrypted_ligogps_record_requires_cipher_port",
    "invalid_ligogps_json_packet",
    "rewrite_requested_requires_ligogps_writer",
]
type LigoGpsEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_ligogps_header",
    "unsupported_ligogps_header",
    "truncated_ligogps_record",
    "ligogps_record_format_error",
    "encrypted_ligogps_record_requires_cipher_port",
    "invalid_ligogps_json_packet",
    "rewrite_requested_requires_ligogps_writer",
]

LIGOGPS_PROCESS_SOURCE = "ligogps.process"
LIGOGPS_PARSE_SOURCE = "ligogps.parse"
LIGOGPS_CIPHER_SOURCE = "ligogps.cipher"
LIGOGPS_JSON_GKU_SOURCE = "ligogps.json.gku"
LIGOGPS_JSON_SOURCE = "ligogps.json"
LIGOGPS_READ_ONLY_SOURCE = "ligogps.read.only"
LIGOGPS_TRANSACTION_SOURCES = (
    LIGOGPS_PROCESS_SOURCE,
    LIGOGPS_PARSE_SOURCE,
    LIGOGPS_CIPHER_SOURCE,
    LIGOGPS_JSON_GKU_SOURCE,
    LIGOGPS_JSON_SOURCE,
    LIGOGPS_READ_ONLY_SOURCE,
)

PLAINTEXT_RECORD_RE = re.compile(
    rb"^.{4}(\S+ \S+)\s+([NS?]):(-?)([.\d]+)\s+([EW?]):(-?)([.\d]+)\s+([.\d]+)",
    re.DOTALL,
)
PLAINTEXT_CANDIDATE_RE = re.compile(rb"^.{4}\d{4}/\d{2}/\d{2} ", re.DOTALL)
JSON_PACKET_RE = re.compile(rb"LIGOGPSINFO (\{.*?\})", re.DOTALL)
OPTIONAL_PLAINTEXT_FIELDS: tuple[tuple[LigoGpsResponsibilityKind, str, str, bytes], ...] = (
    ("track", "GPSTrack", "A", rb"\bA:(\S+)"),
    ("altitude", "GPSAltitude", "H", rb"\bH:(\S+)"),
    ("magnetic_variation", "MagneticVariation", "M", rb"\bM:(\S+)"),
)


@dataclass(frozen=True)
class LigoGpsRewriteRequest:
    operation: LigoGpsRewriteOperation
    record_index: int | None = None
    payload: bytes | None = None


@dataclass(frozen=True)
class LigoGpsTransactionBlocker:
    code: LigoGpsBlockerCode
    reason: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LigoGpsOutputEmissionGate:
    code: LigoGpsEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LigoGpsHeaderValidationPlan:
    header_kind: LigoGpsHeaderKind
    signature_range: tuple[int, int]
    signature: bytes
    record_start: int | None
    record_size: int | None
    json_start: int | None
    no_fuzz_header_detected: bool
    reason: LigoGpsBlockerCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class LigoGpsResponsibilityPlan:
    kind: LigoGpsResponsibilityKind
    tag_name: str
    value: LigoGpsValue
    source_field: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LigoGpsRecordPlan:
    index: int
    byte_range: tuple[int, int]
    kind: LigoGpsRecordKind
    raw_record: bytes
    parsed_text: str | None
    responsibilities: tuple[LigoGpsResponsibilityPlan, ...]
    preserved: bool
    blocker: LigoGpsTransactionBlocker | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LigoGpsJsonPacketPlan:
    index: int
    byte_range: tuple[int, int]
    raw_packet: bytes
    active_status: bool
    responsibilities: tuple[LigoGpsResponsibilityPlan, ...]
    preserved: bool
    blocker: LigoGpsTransactionBlocker | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LigoGpsPayloadPreservationPlan:
    payload_range: tuple[int, int]
    fixed_record_ranges: tuple[tuple[int, int], ...]
    json_packet_ranges: tuple[tuple[int, int], ...]
    trailing_payload_range: tuple[int, int] | None
    preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LigoGpsActionPlan:
    kind: LigoGpsActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LigoGpsMetadataTransactionPlan:
    status: LigoGpsPlanStatus
    source_payload: bytes
    header_validation: LigoGpsHeaderValidationPlan
    records: tuple[LigoGpsRecordPlan, ...]
    json_packets: tuple[LigoGpsJsonPacketPlan, ...]
    payload_preservation: LigoGpsPayloadPreservationPlan | None
    rewrite_requests: tuple[LigoGpsRewriteRequest, ...]
    actions: tuple[LigoGpsActionPlan, ...]
    blockers: tuple[LigoGpsTransactionBlocker, ...]
    output_emission_gates: tuple[LigoGpsOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"LigoGPS metadata transaction output is gated: {gate_codes}")
        return self.source_payload

    @property
    def responsibilities(self) -> tuple[LigoGpsResponsibilityPlan, ...]:
        return tuple(
            responsibility for record in self.records for responsibility in record.responsibilities
        ) + tuple(
            responsibility
            for packet in self.json_packets
            for responsibility in packet.responsibilities
        )


def build_ligogps_metadata_transaction_plan(
    source_payload: bytes,
    *,
    rewrite_requests: Iterable[LigoGpsRewriteRequest] = (),
    allow_output_emission: bool = False,
) -> LigoGpsMetadataTransactionPlan:
    """Build a preserve-only LIGOGPSINFO metadata transaction plan."""

    blockers: list[LigoGpsTransactionBlocker] = []
    actions: list[LigoGpsActionPlan] = []
    header = _build_header_validation(source_payload, blockers, actions)
    records: tuple[LigoGpsRecordPlan, ...] = ()
    json_packets: tuple[LigoGpsJsonPacketPlan, ...] = ()

    if header.header_kind == "fixed_records" and header.is_exiftool_accepted:
        records = _enumerate_fixed_records(source_payload, blockers, actions)
    elif header.header_kind == "json_trailer" and header.is_exiftool_accepted:
        json_packets = _enumerate_json_packets(source_payload, blockers, actions)

    rewrite_request_tuple = tuple(rewrite_requests)
    for request in rewrite_request_tuple:
        blocker = LigoGpsTransactionBlocker(
            code="rewrite_requested_requires_ligogps_writer",
            reason=(
                f"LigoGPS {request.operation} was requested, but this slice only "
                "ports source-backed read routing and preservation."
            ),
            byte_range=None,
            evidence_ids=(LIGOGPS_READ_ONLY_SOURCE,),
        )
        blockers.append(blocker)
        actions.append(
            LigoGpsActionPlan(
                kind="block_requested_rewrite",
                target=_rewrite_target(request),
                byte_range=None,
                reason="LigoGPS rewrites are blocked until a writer is source-backed.",
                evidence_ids=(LIGOGPS_READ_ONLY_SOURCE,),
            )
        )

    payload_preservation = _payload_preservation(source_payload, records, json_packets)
    status: LigoGpsPlanStatus = "unsupported" if _has_structural_blocker(blockers) else "planned"
    gates = _build_output_gates(blockers, allow_output_emission)
    return LigoGpsMetadataTransactionPlan(
        status=status,
        source_payload=source_payload,
        header_validation=header,
        records=records,
        json_packets=json_packets,
        payload_preservation=payload_preservation,
        rewrite_requests=rewrite_request_tuple,
        actions=tuple(actions),
        blockers=tuple(blockers),
        output_emission_gates=gates,
        evidence_ids=LIGOGPS_TRANSACTION_SOURCES,
    )


def _build_header_validation(
    source_payload: bytes,
    blockers: list[LigoGpsTransactionBlocker],
    actions: list[LigoGpsActionPlan],
) -> LigoGpsHeaderValidationPlan:
    if len(source_payload) < len(LIGOGPS_SIGNATURE):
        blocker = LigoGpsTransactionBlocker(
            code="truncated_ligogps_header",
            reason="Input is too short for the LIGOGPSINFO header.",
            byte_range=(0, len(source_payload)),
            evidence_ids=(LIGOGPS_PROCESS_SOURCE,),
        )
        blockers.append(blocker)
        return LigoGpsHeaderValidationPlan(
            header_kind="unknown",
            signature_range=(0, len(source_payload)),
            signature=source_payload,
            record_start=None,
            record_size=None,
            json_start=None,
            no_fuzz_header_detected=False,
            reason=blocker.code,
            evidence_ids=(LIGOGPS_PROCESS_SOURCE, LIGOGPS_JSON_GKU_SOURCE),
        )

    if source_payload.startswith(LIGOGPS_SIGNATURE):
        if len(source_payload) < LIGOGPS_RECORD_OFFSET:
            blocker = LigoGpsTransactionBlocker(
                code="truncated_ligogps_header",
                reason="The fixed-record LIGOGPSINFO header is shorter than 0x14 bytes.",
                byte_range=(0, len(source_payload)),
                evidence_ids=(LIGOGPS_PROCESS_SOURCE,),
            )
            blockers.append(blocker)
            reason: LigoGpsBlockerCode | None = blocker.code
        else:
            reason = None
            actions.append(
                LigoGpsActionPlan(
                    kind="validate_header",
                    target="LIGOGPSINFO fixed records",
                    byte_range=(0, LIGOGPS_RECORD_OFFSET),
                    reason="Input matches the fixed-record LIGOGPSINFO header.",
                    evidence_ids=(LIGOGPS_PROCESS_SOURCE,),
                )
            )
        return LigoGpsHeaderValidationPlan(
            header_kind="fixed_records",
            signature_range=(0, len(LIGOGPS_SIGNATURE)),
            signature=source_payload[: len(LIGOGPS_SIGNATURE)],
            record_start=LIGOGPS_RECORD_OFFSET,
            record_size=LIGOGPS_RECORD_SIZE,
            json_start=None,
            no_fuzz_header_detected=_no_fuzz_header_detected(source_payload),
            reason=reason,
            evidence_ids=(LIGOGPS_PROCESS_SOURCE,),
        )

    json_start = _json_start_from_gku_pointer(source_payload)
    if json_start is not None:
        actions.append(
            LigoGpsActionPlan(
                kind="validate_header",
                target="GKU LIGOGPSINFO JSON pointer",
                byte_range=(0, json_start + len(LIGOGPS_JSON_SIGNATURE)),
                reason="Input matches the GKU pointer to a LIGOGPSINFO JSON packet.",
                evidence_ids=(LIGOGPS_JSON_GKU_SOURCE,),
            )
        )
        return LigoGpsHeaderValidationPlan(
            header_kind="json_trailer",
            signature_range=(json_start, json_start + len(LIGOGPS_JSON_SIGNATURE)),
            signature=source_payload[json_start : json_start + len(LIGOGPS_JSON_SIGNATURE)],
            record_start=None,
            record_size=None,
            json_start=json_start,
            no_fuzz_header_detected=False,
            reason=None,
            evidence_ids=(LIGOGPS_JSON_GKU_SOURCE, LIGOGPS_JSON_SOURCE),
        )

    blocker = LigoGpsTransactionBlocker(
        code="unsupported_ligogps_header",
        reason="Input does not match fixed-record LIGOGPSINFO or GKU JSON detection.",
        byte_range=(0, min(len(source_payload), LIGOGPS_RECORD_OFFSET)),
        evidence_ids=(LIGOGPS_PROCESS_SOURCE, LIGOGPS_JSON_GKU_SOURCE),
    )
    blockers.append(blocker)
    return LigoGpsHeaderValidationPlan(
        header_kind="unknown",
        signature_range=(0, min(len(source_payload), len(LIGOGPS_SIGNATURE))),
        signature=source_payload[: len(LIGOGPS_SIGNATURE)],
        record_start=None,
        record_size=None,
        json_start=None,
        no_fuzz_header_detected=False,
        reason=blocker.code,
        evidence_ids=(LIGOGPS_PROCESS_SOURCE, LIGOGPS_JSON_GKU_SOURCE),
    )


def _enumerate_fixed_records(
    source_payload: bytes,
    blockers: list[LigoGpsTransactionBlocker],
    actions: list[LigoGpsActionPlan],
) -> tuple[LigoGpsRecordPlan, ...]:
    records: list[LigoGpsRecordPlan] = []
    offset = LIGOGPS_RECORD_OFFSET
    index = 0
    while offset + LIGOGPS_RECORD_SIZE <= len(source_payload):
        raw_record = source_payload[offset : offset + LIGOGPS_RECORD_SIZE]
        record = _build_fixed_record(index, offset, raw_record)
        records.append(record)
        if record.blocker is not None:
            blockers.append(record.blocker)
        actions.append(
            LigoGpsActionPlan(
                kind="enumerate_fixed_record",
                target=f"LigoGPS record {index}",
                byte_range=record.byte_range,
                reason="ProcessLigoGPS scans complete 0x84-byte records from offset 0x14.",
                evidence_ids=(LIGOGPS_PROCESS_SOURCE,),
            )
        )
        if record.responsibilities:
            actions.append(
                LigoGpsActionPlan(
                    kind="route_record_tags",
                    target=f"LigoGPS record {index}",
                    byte_range=record.byte_range,
                    reason="Record text matched ParseLigoGPS tag routing.",
                    evidence_ids=(LIGOGPS_PARSE_SOURCE,),
                )
            )
        actions.append(
            LigoGpsActionPlan(
                kind="preserve_record",
                target=f"LigoGPS record {index}",
                byte_range=record.byte_range,
                reason="This non-mutating plan preserves source record bytes.",
                evidence_ids=(LIGOGPS_PROCESS_SOURCE,),
            )
        )
        index += 1
        offset += LIGOGPS_RECORD_SIZE

    if offset < len(source_payload):
        blocker = LigoGpsTransactionBlocker(
            code="truncated_ligogps_record",
            reason="Trailing bytes after fixed records do not fill a 0x84-byte record.",
            byte_range=(offset, len(source_payload)),
            evidence_ids=(LIGOGPS_PROCESS_SOURCE,),
        )
        blockers.append(blocker)
        records.append(
            LigoGpsRecordPlan(
                index=index,
                byte_range=(offset, len(source_payload)),
                kind="truncated_tail",
                raw_record=source_payload[offset:],
                parsed_text=None,
                responsibilities=(),
                preserved=True,
                blocker=blocker,
                evidence_ids=(LIGOGPS_PROCESS_SOURCE,),
            )
        )
    return tuple(records)


def _build_fixed_record(index: int, offset: int, raw_record: bytes) -> LigoGpsRecordPlan:
    byte_range = (offset, offset + len(raw_record))
    if raw_record.startswith(b"####"):
        encrypted_blocker = LigoGpsTransactionBlocker(
            code="encrypted_ligogps_record_requires_cipher_port",
            reason="Encrypted LigoGPS records require DecryptLigoGPS or DecipherLigoGPS.",
            byte_range=byte_range,
            evidence_ids=(LIGOGPS_CIPHER_SOURCE,),
        )
        return LigoGpsRecordPlan(
            index=index,
            byte_range=byte_range,
            kind="encrypted",
            raw_record=raw_record,
            parsed_text=None,
            responsibilities=(),
            preserved=True,
            blocker=encrypted_blocker,
            evidence_ids=(LIGOGPS_PROCESS_SOURCE, LIGOGPS_CIPHER_SOURCE),
        )

    if not PLAINTEXT_CANDIDATE_RE.match(raw_record):
        return LigoGpsRecordPlan(
            index=index,
            byte_range=byte_range,
            kind="blank" if raw_record.rstrip(b"\x00") == b"" else "unrecognized",
            raw_record=raw_record,
            parsed_text=None,
            responsibilities=(),
            preserved=True,
            blocker=None,
            evidence_ids=(LIGOGPS_PROCESS_SOURCE,),
        )

    text_record = raw_record.rstrip(b"\x00")
    parsed = _parse_plaintext_responsibilities(text_record, index + 1)
    record_blocker: LigoGpsTransactionBlocker | None
    if parsed is None:
        record_blocker = LigoGpsTransactionBlocker(
            code="ligogps_record_format_error",
            reason="Record looked like plaintext LIGOGPSINFO but did not match ParseLigoGPS.",
            byte_range=byte_range,
            evidence_ids=(LIGOGPS_PARSE_SOURCE,),
        )
        responsibilities: tuple[LigoGpsResponsibilityPlan, ...] = ()
    else:
        record_blocker = None
        responsibilities = parsed
    return LigoGpsRecordPlan(
        index=index,
        byte_range=byte_range,
        kind="plaintext",
        raw_record=raw_record,
        parsed_text=_decode_ascii(text_record),
        responsibilities=responsibilities,
        preserved=True,
        blocker=record_blocker,
        evidence_ids=(LIGOGPS_PROCESS_SOURCE, LIGOGPS_PARSE_SOURCE),
    )


def _parse_plaintext_responsibilities(
    record: bytes,
    sample_number: int,
) -> tuple[LigoGpsResponsibilityPlan, ...] | None:
    match = PLAINTEXT_RECORD_RE.match(record)
    if match is None:
        return None
    time_raw = _decode_ascii(match.group(1)).replace("/", ":")
    lat_ref = _decode_ascii(match.group(2))
    lat_negative = match.group(3) == b"-"
    latitude = float(match.group(4))
    lon_ref = _decode_ascii(match.group(5))
    lon_negative = match.group(6) == b"-"
    longitude = float(match.group(7))
    speed = float(match.group(8))
    if lat_negative or lat_ref == "S":
        latitude = -latitude
    if lon_negative or lon_ref == "W":
        longitude = -longitude
    if abs(latitude) > 90 or abs(longitude) > 180:
        return None

    responsibilities = [
        LigoGpsResponsibilityPlan(
            kind="sample",
            tag_name="DOC_NUM",
            value=sample_number,
            source_field="record_order",
            evidence_ids=(LIGOGPS_PARSE_SOURCE,),
        ),
        LigoGpsResponsibilityPlan(
            kind="gps_time",
            tag_name="GPSDateTime",
            value=time_raw,
            source_field="date_time",
            evidence_ids=(LIGOGPS_PARSE_SOURCE,),
        ),
        LigoGpsResponsibilityPlan(
            kind="location",
            tag_name="GPSLatitude/GPSLongitude",
            value=(latitude, longitude),
            source_field="lat_lon",
            evidence_ids=(LIGOGPS_PARSE_SOURCE,),
        ),
        LigoGpsResponsibilityPlan(
            kind="speed",
            tag_name="GPSSpeed",
            value=speed,
            source_field="speed_kmh",
            evidence_ids=(LIGOGPS_PARSE_SOURCE,),
        ),
    ]
    for kind, tag_name, field, pattern in OPTIONAL_PLAINTEXT_FIELDS:
        field_match = re.search(pattern, record)
        if field_match is not None:
            responsibilities.append(
                LigoGpsResponsibilityPlan(
                    kind=kind,
                    tag_name=tag_name,
                    value=_decode_ascii(field_match.group(1)),
                    source_field=field,
                    evidence_ids=(LIGOGPS_PARSE_SOURCE,),
                )
            )
    accel_match = re.search(rb"x:(\S+)\sy:(\S+)\sz:(\S+)", record)
    if accel_match is not None:
        responsibilities.append(
            LigoGpsResponsibilityPlan(
                kind="accelerometer",
                tag_name="Accelerometer",
                value=" ".join(_decode_ascii(accel_match.group(item)) for item in (1, 2, 3)),
                source_field="x_y_z",
                evidence_ids=(LIGOGPS_PARSE_SOURCE,),
            )
        )
    return tuple(responsibilities)


def _enumerate_json_packets(
    source_payload: bytes,
    blockers: list[LigoGpsTransactionBlocker],
    actions: list[LigoGpsActionPlan],
) -> tuple[LigoGpsJsonPacketPlan, ...]:
    packets: list[LigoGpsJsonPacketPlan] = []
    for index, match in enumerate(JSON_PACKET_RE.finditer(source_payload)):
        raw_json = match.group(1)
        packet = _build_json_packet(index, match.start(), match.end(), raw_json)
        packets.append(packet)
        if packet.blocker is not None:
            blockers.append(packet.blocker)
        actions.append(
            LigoGpsActionPlan(
                kind="enumerate_json_packet",
                target=f"LigoGPS JSON packet {index}",
                byte_range=packet.byte_range,
                reason="ProcessLigoJSON scans LIGOGPSINFO JSON packet payloads.",
                evidence_ids=(LIGOGPS_JSON_SOURCE,),
            )
        )
        if packet.responsibilities:
            actions.append(
                LigoGpsActionPlan(
                    kind="route_record_tags",
                    target=f"LigoGPS JSON packet {index}",
                    byte_range=packet.byte_range,
                    reason="JSON packet had active GPS status and routeable fields.",
                    evidence_ids=(LIGOGPS_JSON_SOURCE,),
                )
            )
        actions.append(
            LigoGpsActionPlan(
                kind="preserve_packet",
                target=f"LigoGPS JSON packet {index}",
                byte_range=packet.byte_range,
                reason="This non-mutating plan preserves source JSON packet bytes.",
                evidence_ids=(LIGOGPS_JSON_SOURCE,),
            )
        )
    if not packets:
        blocker = LigoGpsTransactionBlocker(
            code="invalid_ligogps_json_packet",
            reason="The GKU pointer was valid but no LIGOGPSINFO JSON packet was found.",
            byte_range=None,
            evidence_ids=(LIGOGPS_JSON_GKU_SOURCE, LIGOGPS_JSON_SOURCE),
        )
        blockers.append(blocker)
    return tuple(packets)


def _build_json_packet(
    index: int,
    start: int,
    end: int,
    raw_json: bytes,
) -> LigoGpsJsonPacketPlan:
    byte_range = (start, end)
    payload: JsonValue
    try:
        payload = json.loads(_decode_ascii(raw_json))
    except json.JSONDecodeError:
        blocker = LigoGpsTransactionBlocker(
            code="invalid_ligogps_json_packet",
            reason="LIGOGPSINFO JSON payload could not be parsed.",
            byte_range=byte_range,
            evidence_ids=(LIGOGPS_JSON_SOURCE,),
        )
        return LigoGpsJsonPacketPlan(
            index=index,
            byte_range=byte_range,
            raw_packet=raw_json,
            active_status=False,
            responsibilities=(),
            preserved=True,
            blocker=blocker,
            evidence_ids=(LIGOGPS_JSON_SOURCE,),
        )
    if not isinstance(payload, dict):
        blocker = LigoGpsTransactionBlocker(
            code="invalid_ligogps_json_packet",
            reason="LIGOGPSINFO JSON payload was not a key-value packet.",
            byte_range=byte_range,
            evidence_ids=(LIGOGPS_JSON_SOURCE,),
        )
        return LigoGpsJsonPacketPlan(
            index=index,
            byte_range=byte_range,
            raw_packet=raw_json,
            active_status=False,
            responsibilities=(),
            preserved=True,
            blocker=blocker,
            evidence_ids=(LIGOGPS_JSON_SOURCE,),
        )
    active_status = payload.get("status") == "A"
    responsibilities = _json_responsibilities(payload, index + 1) if active_status else ()
    return LigoGpsJsonPacketPlan(
        index=index,
        byte_range=byte_range,
        raw_packet=raw_json,
        active_status=active_status,
        responsibilities=responsibilities,
        preserved=True,
        blocker=None,
        evidence_ids=(LIGOGPS_JSON_SOURCE,),
    )


def _json_responsibilities(
    payload: dict[str, JsonValue],
    sample_number: int,
) -> tuple[LigoGpsResponsibilityPlan, ...]:
    responsibilities: list[LigoGpsResponsibilityPlan] = [
        LigoGpsResponsibilityPlan(
            kind="sample",
            tag_name="DOC_NUM",
            value=sample_number,
            source_field="packet_order",
            evidence_ids=(LIGOGPS_JSON_SOURCE,),
        )
    ]
    gps_time = _format_json_time(payload, "Year", "Month", "Day", "Hour", "Minute", "Second", "Z")
    if gps_time is not None:
        responsibilities.append(
            LigoGpsResponsibilityPlan(
                kind="gps_time",
                tag_name="GPSDateTime",
                value=gps_time,
                source_field="Year/Month/Day/Hour/Minute/Second",
                evidence_ids=(LIGOGPS_JSON_SOURCE,),
            )
        )
    location = _json_location(payload, "Latitude", "Longitude")
    if location is not None:
        responsibilities.append(
            LigoGpsResponsibilityPlan(
                kind="location",
                tag_name="GPSLatitude/GPSLongitude",
                value=location,
                source_field="Latitude/Longitude",
                evidence_ids=(LIGOGPS_JSON_SOURCE,),
            )
        )
    speed = _numeric(payload, "Speed")
    if speed is not None:
        responsibilities.append(
            LigoGpsResponsibilityPlan(
                kind="speed",
                tag_name="GPSSpeed",
                value=speed * KNOTS_TO_KPH,
                source_field="Speed",
                evidence_ids=(LIGOGPS_JSON_SOURCE,),
            )
        )
    accelerometer = _json_accelerometer(payload)
    if accelerometer is not None:
        responsibilities.append(
            LigoGpsResponsibilityPlan(
                kind="accelerometer",
                tag_name="Accelerometer",
                value=accelerometer,
                source_field="GsensorX/GsensorY/GsensorZ",
                evidence_ids=(LIGOGPS_JSON_SOURCE,),
            )
        )
    local_time = _format_json_time(
        payload, "MYear", "MMonth", "MDay", "MHour", "MMinute", "MSecond", ""
    )
    if local_time is not None:
        responsibilities.append(
            LigoGpsResponsibilityPlan(
                kind="local_time",
                tag_name="DateTimeOriginal",
                value=local_time,
                source_field="MYear/MMonth/MDay/MHour/MMinute/MSecond",
                evidence_ids=(LIGOGPS_JSON_SOURCE,),
            )
        )
    original_location = _json_location(payload, "OLatitude", "OLongitude")
    if original_location is not None:
        responsibilities.append(
            LigoGpsResponsibilityPlan(
                kind="original_location",
                tag_name="GPSLatitude2/GPSLongitude2",
                value=original_location,
                source_field="OLatitude/OLongitude",
                evidence_ids=(LIGOGPS_JSON_SOURCE,),
            )
        )
    return tuple(responsibilities)


def _payload_preservation(
    source_payload: bytes,
    records: tuple[LigoGpsRecordPlan, ...],
    json_packets: tuple[LigoGpsJsonPacketPlan, ...],
) -> LigoGpsPayloadPreservationPlan | None:
    if not records and not json_packets:
        return None
    record_ranges = tuple(record.byte_range for record in records)
    json_ranges = tuple(packet.byte_range for packet in json_packets)
    ranges = (*record_ranges, *json_ranges)
    max_end = max(end for _, end in ranges)
    trailing = (max_end, len(source_payload)) if max_end < len(source_payload) else None
    return LigoGpsPayloadPreservationPlan(
        payload_range=(0, len(source_payload)),
        fixed_record_ranges=record_ranges,
        json_packet_ranges=json_ranges,
        trailing_payload_range=trailing,
        preserved=True,
        evidence_ids=(LIGOGPS_PROCESS_SOURCE, LIGOGPS_JSON_SOURCE),
    )


def _build_output_gates(
    blockers: list[LigoGpsTransactionBlocker],
    allow_output_emission: bool,
) -> tuple[LigoGpsOutputEmissionGate, ...]:
    gates = [
        LigoGpsOutputEmissionGate(
            code=blocker.code,
            reason=blocker.reason,
            evidence_ids=blocker.evidence_ids,
        )
        for blocker in blockers
    ]
    if not gates and not allow_output_emission:
        gates.append(
            LigoGpsOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="LigoGPS transaction plans are non-mutating unless emission is explicit.",
                evidence_ids=(LIGOGPS_READ_ONLY_SOURCE,),
            )
        )
    return tuple(gates)


def _has_structural_blocker(blockers: list[LigoGpsTransactionBlocker]) -> bool:
    structural_codes: tuple[LigoGpsBlockerCode, ...] = (
        "truncated_ligogps_header",
        "unsupported_ligogps_header",
        "truncated_ligogps_record",
        "ligogps_record_format_error",
        "invalid_ligogps_json_packet",
    )
    return any(blocker.code in structural_codes for blocker in blockers)


def _no_fuzz_header_detected(source_payload: bytes) -> bool:
    if len(source_payload) < 16:
        return False
    return source_payload[12:16] in (b"\x00\x00\x00\x01", b"\x00\x00\x00\x14")


def _json_start_from_gku_pointer(source_payload: bytes) -> int | None:
    if len(source_payload) < 4:
        return None
    pos = int.from_bytes(source_payload[:4], "little")
    if pos + len(LIGOGPS_JSON_SIGNATURE) > len(source_payload):
        return None
    if source_payload[pos : pos + len(LIGOGPS_JSON_SIGNATURE)] != LIGOGPS_JSON_SIGNATURE:
        return None
    return pos


def _format_json_time(
    payload: dict[str, JsonValue],
    year_key: str,
    month_key: str,
    day_key: str,
    hour_key: str,
    minute_key: str,
    second_key: str,
    suffix: str,
) -> str | None:
    values = tuple(
        _int_like(payload, key)
        for key in (year_key, month_key, day_key, hour_key, minute_key, second_key)
    )
    if any(value is None for value in values):
        return None
    year, month, day, hour, minute, second = values
    if (
        year is None
        or month is None
        or day is None
        or hour is None
        or minute is None
        or second is None
    ):
        return None
    return f"{year:04d}:{month:02d}:{day:02d} {hour:02d}:{minute:02d}:{second:02d}{suffix}"


def _json_location(
    payload: dict[str, JsonValue],
    latitude_key: str,
    longitude_key: str,
) -> tuple[float, float] | None:
    latitude = _numeric(payload, latitude_key)
    longitude = _numeric(payload, longitude_key)
    if latitude is None or longitude is None:
        return None
    if payload.get("NS") == "S":
        latitude = -latitude
    if payload.get("EW") == "W":
        longitude = -longitude
    return (latitude, longitude)


def _json_accelerometer(payload: dict[str, JsonValue]) -> str | None:
    values = tuple(_scalar_string(payload, key) for key in ("GsensorX", "GsensorY", "GsensorZ"))
    if any(value is None for value in values):
        return None
    x_value, y_value, z_value = values
    if x_value is None or y_value is None or z_value is None:
        return None
    return f"{x_value} {y_value} {z_value}"


def _int_like(payload: dict[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _numeric(payload: dict[str, JsonValue], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _scalar_string(payload: dict[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _rewrite_target(request: LigoGpsRewriteRequest) -> str:
    if request.record_index is None:
        return request.operation
    return f"{request.operation}:{request.record_index}"


def _decode_ascii(payload: bytes) -> str:
    return payload.decode("ascii", errors="replace")
