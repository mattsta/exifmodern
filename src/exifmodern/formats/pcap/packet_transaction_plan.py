"""Source-backed, non-mutating PCAP packet transaction planning.

The planner mirrors ExifTool's classic PCAP read responsibilities: validate the
global-header magic and endian mode, expose version/linktype/timestamp fields,
preserve packet payload bytes, surface truncation blockers, and keep byte
emission behind explicit non-mutating gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PCAP_GLOBAL_HEADER_SIZE = 24
PCAP_PACKET_HEADER_SIZE = 16
PCAPNG_BLOCK_HEADER_SIZE = 12
PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"
PCAPNG_BYTE_ORDER_MAGIC_BE = b"\x1a\x2b\x3c\x4d"
PCAPNG_BYTE_ORDER_MAGIC_LE = b"\x4d\x3c\x2b\x1a"

type PcapPlanStatus = Literal["planned", "unsupported"]
type PcapByteOrder = Literal["II", "MM"]
type PcapTimestampResolution = Literal["microsecond", "nanosecond"]
type PcapMagicStatus = Literal["valid", "invalid", "truncated"]
type PcapPacketStatus = Literal["valid", "truncated_record_header", "truncated_payload"]
type PcapPayloadPreservationKind = Literal["packet_payload", "packet_record"]
type PcapResponsibilityKind = Literal[
    "global_header_magic",
    "byte_order",
    "timestamp_resolution",
    "version",
    "hardware",
    "operating_system",
    "user_application",
    "device_name",
    "snaplen",
    "network",
    "linktype",
    "packet_enumeration",
    "packet_timestamp",
    "captured_length",
    "original_length",
    "payload_preservation",
]
type PcapEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_global_header",
    "invalid_pcap_magic",
    "truncated_packet_record_header",
    "truncated_packet_payload",
    "pcap_metadata_rewrite_not_supported",
    "pcap_packet_rewrite_not_implemented",
]

PCAP_PM_SOURCE_PATH = "lib/Image/ExifTool/PCAP.pm"

PCAP_MAIN_TABLE_SOURCE = "pcap_main_table"
PCAP_LINKTYPE_TABLE_SOURCE = "pcap_linktype_table"
PCAP_TIMESTAMP_SOURCE = "pcap_timestamp"
PCAP_MAGIC_SOURCE = "pcap_magic"
PCAP_HEADER_TAG_SOURCE = "pcap_header_tag"
PCAP_FIRST_PACKET_SOURCE = "pcap_first_packet"
PCAPNG_HEADER_SOURCE = "pcapng_header"
PCAPNG_OPTIONS_SOURCE = "pcapng_options"
PCAP_NON_MUTATING_SOURCE = "pcap_non_mutating"

PCAP_TRANSACTION_SOURCES = (
    PCAP_MAIN_TABLE_SOURCE,
    PCAP_LINKTYPE_TABLE_SOURCE,
    PCAP_TIMESTAMP_SOURCE,
    PCAP_MAGIC_SOURCE,
    PCAP_HEADER_TAG_SOURCE,
    PCAP_FIRST_PACKET_SOURCE,
    PCAPNG_HEADER_SOURCE,
    PCAPNG_OPTIONS_SOURCE,
    PCAP_NON_MUTATING_SOURCE,
)

PCAP_MAGIC_MODES: dict[bytes, tuple[PcapByteOrder, PcapTimestampResolution, float]] = {
    b"\xa1\xb2\xc3\xd4": ("MM", "microsecond", 1e-6),
    b"\xd4\xc3\xb2\xa1": ("II", "microsecond", 1e-6),
    b"\xa1\xb2\x3c\x4d": ("MM", "nanosecond", 1e-9),
    b"\x4d\x3c\xb2\xa1": ("II", "nanosecond", 1e-9),
}

PCAP_LINKTYPE_NAMES: dict[int, str] = {
    0: "BSD Loopback",
    1: "IEEE 802.3 Ethernet",
    101: "Raw",
    105: "IEEE 802.11",
    113: "Linux SLL",
    127: "IEEE 802.11 Radiotap",
    228: "IPv4",
    229: "IPv6",
    276: "Linux SLL2",
}


@dataclass(frozen=True)
class PcapMetadataRewriteRequest:
    version: str | None = None
    snaplen: int | None = None
    linktype: int | None = None


@dataclass(frozen=True)
class PcapMagicPlan:
    raw_magic: bytes
    status: PcapMagicStatus
    byte_order: PcapByteOrder | None
    timestamp_resolution: PcapTimestampResolution | None
    timestamp_scale: float | None
    blocker_code: PcapEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcapGlobalHeaderPlan:
    offset: int
    size: int
    raw_header: bytes
    magic: PcapMagicPlan
    version_major: int | None
    version_minor: int | None
    version_label: str | None
    hardware: str | None
    operating_system: str | None
    user_application: str | None
    device_name: str | None
    timestamp_resolution_value: float | None
    snaplen: int | None
    network: int | None
    linktype_name: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcapPacketRecordPlan:
    index: int
    offset: int
    header_offset: int
    payload_offset: int | None
    declared_end_offset: int | None
    available_end_offset: int
    timestamp_seconds: int | None
    timestamp_fraction: int | None
    timestamp: float | None
    captured_length: int | None
    original_length: int | None
    payload: bytes
    status: PcapPacketStatus
    blocker_code: PcapEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcapPayloadPreservationPlan:
    packet_index: int
    kind: PcapPayloadPreservationKind
    offset: int
    end_offset: int
    payload: bytes
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcapResponsibilityPlan:
    kind: PcapResponsibilityKind
    available: bool
    value: int | float | str | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcapRewriteBlocker:
    code: PcapEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcapOutputEmissionGate:
    code: PcapEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcapPacketTransactionPlan:
    status: PcapPlanStatus
    input_size: int
    global_header: PcapGlobalHeaderPlan
    packets: tuple[PcapPacketRecordPlan, ...]
    preservation_actions: tuple[PcapPayloadPreservationPlan, ...]
    responsibilities: tuple[PcapResponsibilityPlan, ...]
    rewrite_blockers: tuple[PcapRewriteBlocker, ...]
    output_emission_gates: tuple[PcapOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"PCAP packet transaction output is gated: {gate_codes}")
        return self.original_bytes


def build_pcap_packet_transaction_plan(
    pcap_data: bytes,
    *,
    requested_metadata: PcapMetadataRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> PcapPacketTransactionPlan:
    global_header = parse_pcap_global_header(pcap_data)
    packets, packet_gates = enumerate_pcap_packet_records(pcap_data, global_header)
    preservation_actions = tuple(
        _preservation_action(packet, pcap_data) for packet in packets if packet.status == "valid"
    )
    responsibilities = _responsibility_plans(global_header, packets, preservation_actions)
    rewrite_blockers = _rewrite_blockers(requested_metadata)

    gates = [*packet_gates]
    if global_header.magic.blocker_code is not None:
        gates.insert(
            0,
            PcapOutputEmissionGate(
                global_header.magic.blocker_code,
                _reason_for_gate(global_header.magic.blocker_code),
                global_header.magic.evidence_ids,
            ),
        )
    gates.extend(
        PcapOutputEmissionGate(blocker.code, blocker.reason, blocker.evidence_ids)
        for blocker in rewrite_blockers
    )
    if not allow_output_emission:
        gates.append(
            PcapOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "PCAP transaction plans are non-mutating unless emission is explicit.",
                (PCAP_NON_MUTATING_SOURCE,),
            )
        )

    unique_output_gates = unique_gates(tuple(gates))
    status: PcapPlanStatus = (
        "unsupported" if _has_structural_gate(unique_output_gates) else "planned"
    )
    return PcapPacketTransactionPlan(
        status=status,
        input_size=len(pcap_data),
        global_header=global_header,
        packets=packets,
        preservation_actions=preservation_actions,
        responsibilities=responsibilities,
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=unique_output_gates,
        evidence_ids=unique_sources(
            (
                *PCAP_TRANSACTION_SOURCES,
                *global_header.evidence_ids,
                *(source for packet in packets for source in packet.evidence_ids),
                *(source for action in preservation_actions for source in action.evidence_ids),
                *(source for gate in unique_output_gates for source in gate.evidence_ids),
            )
        ),
        original_bytes=pcap_data,
    )


plan_pcap_packet_transaction = build_pcap_packet_transaction_plan


def parse_pcap_global_header(pcap_data: bytes) -> PcapGlobalHeaderPlan:
    raw_header = pcap_data[:PCAP_GLOBAL_HEADER_SIZE]
    magic = _magic_plan(raw_header)
    if magic.status != "valid":
        return PcapGlobalHeaderPlan(
            offset=0,
            size=PCAP_GLOBAL_HEADER_SIZE,
            raw_header=raw_header,
            magic=magic,
            version_major=None,
            version_minor=None,
            version_label=None,
            hardware=None,
            operating_system=None,
            user_application=None,
            device_name=None,
            timestamp_resolution_value=None,
            snaplen=None,
            network=None,
            linktype_name=None,
            evidence_ids=(PCAP_MAGIC_SOURCE,),
        )

    endian = _byte_order_name(_required_byte_order(magic.byte_order))
    if raw_header[:4] == PCAPNG_MAGIC:
        pcapng = _scan_pcapng_section(pcap_data, endian)
        version_major = int.from_bytes(raw_header[12:14], endian)
        version_minor = int.from_bytes(raw_header[14:16], endian)
        return PcapGlobalHeaderPlan(
            offset=0,
            size=PCAP_GLOBAL_HEADER_SIZE,
            raw_header=raw_header,
            magic=magic,
            version_major=version_major,
            version_minor=version_minor,
            version_label=f"PCAPNG {version_major}.{version_minor}",
            hardware=pcapng.hardware,
            operating_system=pcapng.operating_system,
            user_application=pcapng.user_application,
            device_name=pcapng.device_name,
            timestamp_resolution_value=pcapng.timestamp_resolution,
            snaplen=None,
            network=pcapng.linktype,
            linktype_name=(
                PCAP_LINKTYPE_NAMES.get(pcapng.linktype) if pcapng.linktype is not None else None
            ),
            evidence_ids=(
                PCAPNG_HEADER_SOURCE,
                PCAPNG_OPTIONS_SOURCE,
                PCAP_LINKTYPE_TABLE_SOURCE,
            ),
        )

    version_major = int.from_bytes(raw_header[4:6], endian)
    version_minor = int.from_bytes(raw_header[6:8], endian)
    snaplen = int.from_bytes(raw_header[16:20], endian)
    network = int.from_bytes(raw_header[22:24], endian)
    return PcapGlobalHeaderPlan(
        offset=0,
        size=PCAP_GLOBAL_HEADER_SIZE,
        raw_header=raw_header,
        magic=magic,
        version_major=version_major,
        version_minor=version_minor,
        version_label=f"PCAP {version_major}.{version_minor}",
        hardware=None,
        operating_system=None,
        user_application=None,
        device_name=None,
        timestamp_resolution_value=magic.timestamp_scale,
        snaplen=snaplen,
        network=network,
        linktype_name=PCAP_LINKTYPE_NAMES.get(network),
        evidence_ids=(PCAP_MAGIC_SOURCE, PCAP_HEADER_TAG_SOURCE, PCAP_LINKTYPE_TABLE_SOURCE),
    )


def enumerate_pcap_packet_records(
    pcap_data: bytes,
    global_header: PcapGlobalHeaderPlan,
) -> tuple[tuple[PcapPacketRecordPlan, ...], tuple[PcapOutputEmissionGate, ...]]:
    if global_header.magic.status != "valid":
        return (), ()
    if global_header.magic.raw_magic == PCAPNG_MAGIC:
        return enumerate_pcapng_packet_records(pcap_data, global_header)

    packets: list[PcapPacketRecordPlan] = []
    gates: list[PcapOutputEmissionGate] = []
    offset = PCAP_GLOBAL_HEADER_SIZE
    endian = _byte_order_name(_required_byte_order(global_header.magic.byte_order))
    scale = _required_float(global_header.magic.timestamp_scale)

    while offset < len(pcap_data):
        packet = _packet_record_plan(len(packets), offset, pcap_data, endian, scale)
        packets.append(packet)
        if packet.blocker_code is not None:
            gates.append(
                PcapOutputEmissionGate(
                    packet.blocker_code,
                    _reason_for_gate(packet.blocker_code),
                    packet.evidence_ids,
                )
            )
            break
        offset = _required_int(packet.declared_end_offset)

    return tuple(packets), tuple(gates)


@dataclass(frozen=True)
class PcapNgSectionScan:
    hardware: str | None
    operating_system: str | None
    user_application: str | None
    device_name: str | None
    linktype: int | None
    timestamp_resolution: float | None
    timestamp_offset: int
    first_packet: PcapPacketRecordPlan | None
    gates: tuple[PcapOutputEmissionGate, ...]


def enumerate_pcapng_packet_records(
    pcap_data: bytes,
    global_header: PcapGlobalHeaderPlan,
) -> tuple[tuple[PcapPacketRecordPlan, ...], tuple[PcapOutputEmissionGate, ...]]:
    endian = _byte_order_name(_required_byte_order(global_header.magic.byte_order))
    scan = _scan_pcapng_section(pcap_data, endian)
    packets = () if scan.first_packet is None else (scan.first_packet,)
    return packets, scan.gates


def _scan_pcapng_section(
    pcap_data: bytes,
    endian: Literal["little", "big"],
) -> PcapNgSectionScan:
    hardware: str | None = None
    operating_system: str | None = None
    user_application: str | None = None
    device_name: str | None = None
    linktype: int | None = None
    timestamp_resolution = 1e-6
    timestamp_offset = 0
    previous_block_length: int | None = None
    first_packet: PcapPacketRecordPlan | None = None
    gates: list[PcapOutputEmissionGate] = []
    offset = 0
    while offset + PCAPNG_BLOCK_HEADER_SIZE <= len(pcap_data):
        block_type = int.from_bytes(pcap_data[offset : offset + 4], endian)
        block_length = int.from_bytes(pcap_data[offset + 4 : offset + 8], endian)
        if block_length < PCAPNG_BLOCK_HEADER_SIZE or offset + block_length > len(pcap_data):
            gates.append(
                PcapOutputEmissionGate(
                    "truncated_packet_payload",
                    "A PCAPNG block length extends beyond available input.",
                    (PCAPNG_OPTIONS_SOURCE,),
                )
            )
            break
        body_start = offset + 8
        body_end = offset + block_length - 4
        body = pcap_data[body_start:body_end]
        if block_type == 0x0A0D0D0A:
            parsed = _parse_pcapng_options(body[16:], endian, "SHB")
            hardware = parsed.hardware
            operating_system = parsed.operating_system
            user_application = parsed.user_application
        elif block_type == 1 and len(body) >= 8:
            linktype = int.from_bytes(body[0:2], endian)
            parsed = _parse_pcapng_options(body[8:], endian, "IDB")
            device_name = parsed.device_name
            operating_system = parsed.operating_system or operating_system
            timestamp_resolution = parsed.timestamp_resolution or timestamp_resolution
            timestamp_offset = parsed.timestamp_offset or timestamp_offset
        elif block_type == 6 and len(body) >= 20:
            high = int.from_bytes(body[4:8], endian)
            low = _pcapng_exiftool_timestamp_low_word(body, previous_block_length, endian)
            captured_length = int.from_bytes(body[12:16], endian)
            original_length = int.from_bytes(body[16:20], endian)
            timestamp = (high * 4_294_967_296 + low) * timestamp_resolution + timestamp_offset
            payload_offset = body_start + 20
            declared_end = payload_offset + captured_length
            available_end = min(declared_end, len(pcap_data))
            first_packet = PcapPacketRecordPlan(
                index=0,
                offset=offset,
                header_offset=offset,
                payload_offset=payload_offset,
                declared_end_offset=declared_end,
                available_end_offset=available_end,
                timestamp_seconds=None,
                timestamp_fraction=None,
                timestamp=timestamp,
                captured_length=captured_length,
                original_length=original_length,
                payload=pcap_data[payload_offset:available_end],
                status="valid" if declared_end <= body_end else "truncated_payload",
                blocker_code=None if declared_end <= body_end else "truncated_packet_payload",
                evidence_ids=(PCAPNG_OPTIONS_SOURCE, PCAP_TIMESTAMP_SOURCE),
            )
            if first_packet.blocker_code is not None:
                gates.append(
                    PcapOutputEmissionGate(
                        first_packet.blocker_code,
                        _reason_for_gate(first_packet.blocker_code),
                        first_packet.evidence_ids,
                    )
                )
            break
        previous_block_length = block_length
        offset += block_length
    return PcapNgSectionScan(
        hardware=hardware,
        operating_system=operating_system,
        user_application=user_application,
        device_name=device_name,
        linktype=linktype,
        timestamp_resolution=timestamp_resolution,
        timestamp_offset=timestamp_offset,
        first_packet=first_packet,
        gates=tuple(gates),
    )


def _pcapng_exiftool_timestamp_low_word(
    enhanced_packet_body: bytes,
    previous_block_length: int | None,
    endian: Literal["little", "big"],
) -> int:
    # PCAP.pm reuses its option-read buffer when adding the low timestamp word.
    # The focused PCAPNG fixture therefore renders with the preceding block
    # length as the low word rather than the EPD body's low timestamp field.
    if previous_block_length is not None:
        return previous_block_length
    return int.from_bytes(enhanced_packet_body[8:12], endian)


@dataclass(frozen=True)
class PcapNgOptionScan:
    hardware: str | None
    operating_system: str | None
    user_application: str | None
    device_name: str | None
    timestamp_resolution: float | None
    timestamp_offset: int | None


def _parse_pcapng_options(
    option_data: bytes,
    endian: Literal["little", "big"],
    directory: Literal["SHB", "IDB"],
) -> PcapNgOptionScan:
    hardware: str | None = None
    operating_system: str | None = None
    user_application: str | None = None
    device_name: str | None = None
    timestamp_resolution: float | None = None
    timestamp_offset: int | None = None
    offset = 0
    while offset + 4 <= len(option_data):
        option = int.from_bytes(option_data[offset : offset + 2], endian)
        length = int.from_bytes(option_data[offset + 2 : offset + 4], endian)
        offset += 4
        padded_length = (length + 3) & 0xFFFC
        if offset + padded_length > len(option_data) or option == 0:
            break
        payload = option_data[offset : offset + length]
        text = _decode_pcapng_text(payload)
        if directory == "SHB" and option == 2:
            hardware = text
        elif directory == "SHB" and option == 3:
            operating_system = text
        elif directory == "SHB" and option == 4:
            user_application = text
        elif directory == "IDB" and option == 2:
            device_name = text
        elif directory == "IDB" and option == 9 and payload:
            resolution_byte = payload[0]
            timestamp_resolution = (
                2 ** -(resolution_byte & 0x7F) if resolution_byte & 0x80 else 10**-resolution_byte
            )
        elif directory == "IDB" and option == 12:
            operating_system = text
        elif directory == "IDB" and option == 14 and len(payload) >= 8:
            timestamp_offset = int.from_bytes(payload[:8], endian)
        offset += padded_length
    return PcapNgOptionScan(
        hardware=hardware,
        operating_system=operating_system,
        user_application=user_application,
        device_name=device_name,
        timestamp_resolution=timestamp_resolution,
        timestamp_offset=timestamp_offset,
    )


def _decode_pcapng_text(payload: bytes) -> str:
    return payload.rstrip(b"\0").decode("utf-8", errors="replace")


def _packet_record_plan(
    index: int,
    offset: int,
    pcap_data: bytes,
    endian: Literal["little", "big"],
    timestamp_scale: float,
) -> PcapPacketRecordPlan:
    raw_header = pcap_data[offset : offset + PCAP_PACKET_HEADER_SIZE]
    if len(raw_header) < PCAP_PACKET_HEADER_SIZE:
        return PcapPacketRecordPlan(
            index=index,
            offset=offset,
            header_offset=offset,
            payload_offset=None,
            declared_end_offset=None,
            available_end_offset=len(pcap_data),
            timestamp_seconds=None,
            timestamp_fraction=None,
            timestamp=None,
            captured_length=None,
            original_length=None,
            payload=b"",
            status="truncated_record_header",
            blocker_code="truncated_packet_record_header",
            evidence_ids=(PCAP_FIRST_PACKET_SOURCE,),
        )

    timestamp_seconds = int.from_bytes(raw_header[0:4], endian)
    timestamp_fraction = int.from_bytes(raw_header[4:8], endian)
    captured_length = int.from_bytes(raw_header[8:12], endian)
    original_length = int.from_bytes(raw_header[12:16], endian)
    payload_offset = offset + PCAP_PACKET_HEADER_SIZE
    declared_end = payload_offset + captured_length
    available_end = min(declared_end, len(pcap_data))
    payload = pcap_data[payload_offset:available_end]
    timestamp = timestamp_seconds + timestamp_fraction * timestamp_scale

    if declared_end > len(pcap_data):
        return PcapPacketRecordPlan(
            index=index,
            offset=offset,
            header_offset=offset,
            payload_offset=payload_offset,
            declared_end_offset=declared_end,
            available_end_offset=len(pcap_data),
            timestamp_seconds=timestamp_seconds,
            timestamp_fraction=timestamp_fraction,
            timestamp=timestamp,
            captured_length=captured_length,
            original_length=original_length,
            payload=payload,
            status="truncated_payload",
            blocker_code="truncated_packet_payload",
            evidence_ids=(PCAP_FIRST_PACKET_SOURCE, PCAP_TIMESTAMP_SOURCE),
        )

    return PcapPacketRecordPlan(
        index=index,
        offset=offset,
        header_offset=offset,
        payload_offset=payload_offset,
        declared_end_offset=declared_end,
        available_end_offset=declared_end,
        timestamp_seconds=timestamp_seconds,
        timestamp_fraction=timestamp_fraction,
        timestamp=timestamp,
        captured_length=captured_length,
        original_length=original_length,
        payload=payload,
        status="valid",
        blocker_code=None,
        evidence_ids=(PCAP_FIRST_PACKET_SOURCE, PCAP_TIMESTAMP_SOURCE),
    )


def _magic_plan(raw_header: bytes) -> PcapMagicPlan:
    raw_magic = raw_header[:4]
    raw_header_length = len(raw_header)
    if raw_header_length < PCAP_GLOBAL_HEADER_SIZE:
        return PcapMagicPlan(
            raw_magic=raw_magic,
            status="truncated",
            byte_order=None,
            timestamp_resolution=None,
            timestamp_scale=None,
            blocker_code="truncated_global_header",
            evidence_ids=(PCAP_MAGIC_SOURCE,),
        )
    if raw_magic == PCAPNG_MAGIC:
        return _pcapng_magic_plan(raw_header, raw_header_length)
    mode = PCAP_MAGIC_MODES.get(raw_magic)
    if mode is None:
        return PcapMagicPlan(
            raw_magic=raw_magic,
            status="invalid",
            byte_order=None,
            timestamp_resolution=None,
            timestamp_scale=None,
            blocker_code="invalid_pcap_magic",
            evidence_ids=(PCAP_MAGIC_SOURCE,),
        )
    return PcapMagicPlan(
        raw_magic=raw_magic,
        status="valid",
        byte_order=mode[0],
        timestamp_resolution=mode[1],
        timestamp_scale=mode[2],
        blocker_code=None,
        evidence_ids=(PCAP_MAGIC_SOURCE,),
    )


def _pcapng_magic_plan(raw_header: bytes, raw_header_length: int) -> PcapMagicPlan:
    raw_magic = raw_header[:4]
    if raw_header_length < PCAP_GLOBAL_HEADER_SIZE:
        return PcapMagicPlan(
            raw_magic=raw_magic,
            status="truncated",
            byte_order=None,
            timestamp_resolution=None,
            timestamp_scale=None,
            blocker_code="truncated_global_header",
            evidence_ids=(PCAPNG_HEADER_SOURCE,),
        )
    byte_order_magic = raw_header[8:12]
    if byte_order_magic == PCAPNG_BYTE_ORDER_MAGIC_BE:
        byte_order: PcapByteOrder | None = "MM"
    elif byte_order_magic == PCAPNG_BYTE_ORDER_MAGIC_LE:
        byte_order = "II"
    else:
        return PcapMagicPlan(
            raw_magic=raw_magic,
            status="invalid",
            byte_order=None,
            timestamp_resolution=None,
            timestamp_scale=None,
            blocker_code="invalid_pcap_magic",
            evidence_ids=(PCAPNG_HEADER_SOURCE,),
        )
    return PcapMagicPlan(
        raw_magic=raw_magic,
        status="valid",
        byte_order=byte_order,
        timestamp_resolution="microsecond",
        timestamp_scale=1e-6,
        blocker_code=None,
        evidence_ids=(PCAPNG_HEADER_SOURCE,),
    )


def _preservation_action(
    packet: PcapPacketRecordPlan,
    pcap_data: bytes,
) -> PcapPayloadPreservationPlan:
    end_offset = _required_int(packet.declared_end_offset)
    return PcapPayloadPreservationPlan(
        packet_index=packet.index,
        kind="packet_record",
        offset=packet.offset,
        end_offset=end_offset,
        payload=pcap_data[packet.offset : end_offset],
        reason="Complete PCAP packet records are preserved byte-for-byte by this planner.",
        evidence_ids=(PCAP_FIRST_PACKET_SOURCE,),
    )


def _responsibility_plans(
    global_header: PcapGlobalHeaderPlan,
    packets: tuple[PcapPacketRecordPlan, ...],
    preservation_actions: tuple[PcapPayloadPreservationPlan, ...],
) -> tuple[PcapResponsibilityPlan, ...]:
    first_packet = packets[0] if packets else None
    return (
        _responsibility(
            "global_header_magic",
            global_header.magic.status == "valid",
            global_header.magic.raw_magic.hex(),
            PCAP_MAGIC_SOURCE,
        ),
        _responsibility(
            "byte_order",
            global_header.magic.byte_order is not None,
            global_header.magic.byte_order,
            PCAP_MAGIC_SOURCE,
        ),
        _responsibility(
            "timestamp_resolution",
            global_header.timestamp_resolution_value is not None,
            global_header.timestamp_resolution_value
            if global_header.magic.raw_magic == PCAPNG_MAGIC
            else global_header.magic.timestamp_resolution,
            PCAPNG_OPTIONS_SOURCE
            if global_header.magic.raw_magic == PCAPNG_MAGIC
            else PCAP_MAGIC_SOURCE,
        ),
        _responsibility(
            "version",
            global_header.version_label is not None,
            global_header.version_label,
            PCAPNG_HEADER_SOURCE
            if global_header.magic.raw_magic == PCAPNG_MAGIC
            else PCAP_HEADER_TAG_SOURCE,
        ),
        _responsibility(
            "hardware",
            global_header.hardware is not None,
            global_header.hardware,
            PCAPNG_OPTIONS_SOURCE,
        ),
        _responsibility(
            "operating_system",
            global_header.operating_system is not None,
            global_header.operating_system,
            PCAPNG_OPTIONS_SOURCE,
        ),
        _responsibility(
            "user_application",
            global_header.user_application is not None,
            global_header.user_application,
            PCAPNG_OPTIONS_SOURCE,
        ),
        _responsibility(
            "device_name",
            global_header.device_name is not None,
            global_header.device_name,
            PCAPNG_OPTIONS_SOURCE,
        ),
        _responsibility(
            "snaplen",
            global_header.snaplen is not None,
            global_header.snaplen,
            PCAP_HEADER_TAG_SOURCE,
            reason=(
                "Snaplen is part of the classic PCAP global header even though PCAP.pm "
                "does not emit it as a tag."
            ),
        ),
        _responsibility(
            "network",
            global_header.network is not None,
            global_header.network,
            PCAP_HEADER_TAG_SOURCE,
        ),
        _responsibility(
            "linktype",
            global_header.network is not None,
            global_header.linktype_name,
            PCAP_LINKTYPE_TABLE_SOURCE,
        ),
        _responsibility(
            "packet_enumeration",
            bool(packets),
            len(packets),
            PCAP_FIRST_PACKET_SOURCE,
            reason=(
                "ExifTool reads the first packet for TimeStamp; this planner enumerates "
                "packet records to preserve payloads."
            ),
        ),
        _responsibility(
            "packet_timestamp",
            first_packet is not None and first_packet.timestamp is not None,
            first_packet.timestamp if first_packet else None,
            PCAP_FIRST_PACKET_SOURCE,
        ),
        _responsibility(
            "captured_length",
            first_packet is not None and first_packet.captured_length is not None,
            first_packet.captured_length if first_packet else None,
            PCAP_FIRST_PACKET_SOURCE,
        ),
        _responsibility(
            "original_length",
            first_packet is not None and first_packet.original_length is not None,
            first_packet.original_length if first_packet else None,
            PCAP_FIRST_PACKET_SOURCE,
        ),
        _responsibility(
            "payload_preservation",
            bool(preservation_actions),
            len(preservation_actions),
            PCAP_FIRST_PACKET_SOURCE,
        ),
    )


def _responsibility(
    kind: PcapResponsibilityKind,
    available: bool,
    value: int | float | str | None,
    source: str,
    *,
    reason: str | None = None,
) -> PcapResponsibilityPlan:
    return PcapResponsibilityPlan(
        kind=kind,
        available=available,
        value=value,
        reason=reason
        or (
            "Value is available from the PCAP transaction plan."
            if available
            else "Value is unavailable for this PCAP input."
        ),
        evidence_ids=(source,),
    )


def _rewrite_blockers(
    requested_metadata: PcapMetadataRewriteRequest | None,
) -> tuple[PcapRewriteBlocker, ...]:
    if requested_metadata is None:
        return ()
    requested = (
        requested_metadata.version is not None
        or requested_metadata.snaplen is not None
        or requested_metadata.linktype is not None
    )
    if not requested:
        return ()
    return (
        PcapRewriteBlocker(
            "pcap_metadata_rewrite_not_supported",
            "PCAP.pm models classic PCAP values as read-only extraction responsibilities.",
            (PCAP_MAIN_TABLE_SOURCE, PCAP_HEADER_TAG_SOURCE),
        ),
        PcapRewriteBlocker(
            "pcap_packet_rewrite_not_implemented",
            "This planner preserves packet records and does not rebuild PCAP packet bytes.",
            (PCAP_FIRST_PACKET_SOURCE, PCAP_NON_MUTATING_SOURCE),
        ),
    )


def _reason_for_gate(code: PcapEmissionGateCode) -> str:
    reasons: dict[PcapEmissionGateCode, str] = {
        "non_mutating_plan_requires_explicit_emission": (
            "Emission requires an explicit caller opt-in."
        ),
        "truncated_global_header": "Input ended before ExifTool's 24-byte PCAP header read.",
        "invalid_pcap_magic": "Classic PCAP magic did not match ExifTool's accepted variants.",
        "truncated_packet_record_header": "A packet record ended before its 16-byte header.",
        "truncated_packet_payload": (
            "A packet captured-length value extends beyond available input."
        ),
        "pcap_metadata_rewrite_not_supported": "PCAP metadata rewrite is not supported.",
        "pcap_packet_rewrite_not_implemented": "PCAP packet rewrite is not implemented.",
    }
    return reasons[code]


def _has_structural_gate(gates: tuple[PcapOutputEmissionGate, ...]) -> bool:
    structural_codes: set[PcapEmissionGateCode] = {
        "truncated_global_header",
        "invalid_pcap_magic",
        "truncated_packet_record_header",
        "truncated_packet_payload",
    }
    return any(gate.code in structural_codes for gate in gates)


def _byte_order_name(byte_order: PcapByteOrder) -> Literal["little", "big"]:
    return "little" if byte_order == "II" else "big"


def _required_byte_order(value: PcapByteOrder | None) -> PcapByteOrder:
    if value is None:
        raise ValueError("Expected parsed PCAP byte order.")
    return value


def _required_int(value: int | None) -> int:
    if value is None:
        raise ValueError("Expected parsed PCAP integer value.")
    return value


def _required_float(value: float | None) -> float:
    if value is None:
        raise ValueError("Expected parsed PCAP timestamp scale.")
    return value


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        unique.append(source)
    return tuple(unique)


def unique_gates(
    gates: tuple[PcapOutputEmissionGate, ...],
) -> tuple[PcapOutputEmissionGate, ...]:
    seen: set[PcapEmissionGateCode] = set()
    unique: list[PcapOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
