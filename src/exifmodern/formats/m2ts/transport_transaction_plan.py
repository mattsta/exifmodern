"""Source-backed, non-mutating M2TS transport-stream transaction plans.

ExifTool's M2TS reader validates 188-byte MPEG transport packets and 192-byte
M2TS packets with a four-byte timecode prefix, routes PAT/PMT sections into PID
and stream-type state, gathers PES payload starts for media parsers, and uses
PCR timestamps to derive Duration.  This module records those responsibilities
for future metadata transactions without emitting modified transport streams.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SYNC_BYTE = 0x47
M2T_PACKET_SIZE = 188
M2TS_PACKET_SIZE = 192
TRANSPORT_PAYLOAD_SIZE = 188
NULL_PACKET_PID = 0x1FFF
PES_START_CODE_PREFIX = 0x00000100
PCR_CLOCK_HZ = 27_000_000

type M2tsFileKind = Literal["m2t", "m2ts", "invalid"]
type M2tsPacketAction = Literal[
    "parse_pat",
    "parse_pmt",
    "parse_pes_start",
    "accumulate_pes",
    "preserve_media_packet",
    "preserve_null_packet",
    "preserve_unknown_packet",
    "timestamp_only",
]
type M2tsRouteKind = Literal[
    "program_association_table",
    "program_map_table",
    "program_clock_reference",
    "elementary_stream",
    "pes_payload",
    "ac3_descriptor",
]
type M2tsResponsibilityConcern = Literal[
    "packet_size_and_sync_validation",
    "packet_alignment_and_truncation",
    "pid_program_and_pmt_routing",
    "pes_media_payload_routing",
    "timestamp_duration_scan",
    "stream_type_database",
    "media_packet_preservation",
    "output_emission_gate",
]
type M2tsEmissionGateCode = Literal[
    "sync_byte_detection_failed",
    "insufficient_packets_for_validation",
    "packet_alignment_offset",
    "truncated_packet_tail",
    "sync_byte_mismatch",
    "invalid_adaptation_field_length",
    "bad_pointer_field",
    "truncated_payload_section",
    "bad_table_syntax",
    "invalid_section_length",
    "truncated_pmt",
    "truncated_program_info",
    "truncated_es_info",
    "bad_pes_syntax",
    "planner_is_non_mutating",
    "full_transport_writer_not_implemented",
]

M2TS_SYNC_SOURCE = "m2ts.process.packet_size_sync_validation"
M2TS_PACKET_PREFIX_SOURCE = "m2ts.process.transport_packet_prefix"
M2TS_ADAPTATION_PCR_SOURCE = "m2ts.process.adaptation_pcr"
M2TS_PAT_PMT_SOURCE = "m2ts.process.pat_pmt"
M2TS_PES_SOURCE = "m2ts.process.pes_media_payload"
M2TS_DURATION_SOURCE = "m2ts.process.duration_calculation"
M2TS_STREAM_TYPE_SOURCE = "m2ts.stream_type_database"
M2TS_MAIN_TAG_SOURCE = "m2ts.main_tag_table"
M2TS_OUTPUT_BOUNDARY_SOURCE = "m2ts.transaction.non_mutating_output_boundary"

STREAM_TYPE_NAMES: dict[int, str] = {
    0x00: "Reserved",
    0x01: "MPEG-1 Video",
    0x02: "MPEG-2 Video",
    0x03: "MPEG-1 Audio",
    0x04: "MPEG-2 Audio",
    0x05: "ISO 13818-1 private sections",
    0x06: "ISO 13818-1 PES private data",
    0x0F: "MPEG-2 AAC Audio",
    0x10: "MPEG-4 Video",
    0x11: "MPEG-4 LATM AAC Audio",
    0x15: "Packetized metadata",
    0x1B: "H.264 (AVC) Video",
    0x24: "H.265 (HEVC) Video",
    0x81: "A52/AC-3 Audio",
    0x82: "HDMV DTS Audio",
    0x83: "LPCM Audio",
    0x86: "DTS-HD Audio",
    0x87: "E-AC-3 Audio",
    0x8A: "DTS Audio",
    0x90: "Presentation Graphic Stream (subtitle)",
    0x91: "A52b/AC-3 Audio",
    0xEA: "Private ES (VC-1)",
}
NO_SYNTAX_STREAM_IDS = frozenset({0xBC, 0xBE, 0xBF, 0xF0, 0xF1, 0xF2, 0xF8, 0xFF})


@dataclass(frozen=True)
class M2tsSyncPlan:
    file_kind: M2tsFileKind
    packet_size: int | None
    timecode_prefix_size: int | None
    packet_start_offset: int | None
    validated_sync_packets: int
    evidence_ids: tuple[str, ...] = (M2TS_SYNC_SOURCE,)


@dataclass(frozen=True)
class M2tsEmissionGate:
    code: M2tsEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class M2tsTransportPacketPlan:
    index: int
    offset: int
    payload_offset: int
    payload_end_offset: int
    pid: int
    action: M2tsPacketAction
    payload_unit_start_indicator: bool
    adaptation_field_exists: bool
    payload_data_exists: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class M2tsProgramPlan:
    program_number: int
    program_map_pid: int
    evidence_ids: tuple[str, ...] = (M2TS_PAT_PMT_SOURCE,)


@dataclass(frozen=True)
class M2tsStreamPlan:
    program_number: int
    pid: int
    stream_type: int
    stream_type_name: str
    is_audio: bool
    is_video: bool
    es_info_length: int
    evidence_ids: tuple[str, ...] = (M2TS_PAT_PMT_SOURCE, M2TS_STREAM_TYPE_SOURCE)


@dataclass(frozen=True)
class M2tsRoutePlan:
    kind: M2tsRouteKind
    pid: int
    name: str
    packet_index: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class M2tsPesPlan:
    pid: int
    packet_index: int
    stream_id: int
    pes_packet_length: int
    payload_offset: int
    retained_payload_size: int
    stream_type: int | None
    evidence_ids: tuple[str, ...] = (M2TS_PES_SOURCE,)


@dataclass(frozen=True)
class M2tsAc3DescriptorPlan:
    pid: int
    packet_index: int
    audio_bitrate: int | None
    surround_mode: str | None
    audio_channels: int | str | None
    evidence_ids: tuple[str, ...] = (M2TS_PAT_PMT_SOURCE, M2TS_MAIN_TAG_SOURCE)


@dataclass(frozen=True)
class M2tsTimestampPlan:
    start_ticks: int | None
    end_ticks: int | None
    duration_ticks: int | None
    duration_seconds: float | None
    pcr_packet_indexes: tuple[int, ...]
    evidence_ids: tuple[str, ...] = (
        M2TS_ADAPTATION_PCR_SOURCE,
        M2TS_DURATION_SOURCE,
        M2TS_MAIN_TAG_SOURCE,
    )


@dataclass(frozen=True)
class M2tsResponsibility:
    order: int
    concern: M2tsResponsibilityConcern
    description: str
    records: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class M2tsTransportTransactionPlan:
    sync: M2tsSyncPlan
    packets: tuple[M2tsTransportPacketPlan, ...]
    programs: tuple[M2tsProgramPlan, ...]
    streams: tuple[M2tsStreamPlan, ...]
    routes: tuple[M2tsRoutePlan, ...]
    pes_packets: tuple[M2tsPesPlan, ...]
    ac3_descriptors: tuple[M2tsAc3DescriptorPlan, ...]
    timestamp: M2tsTimestampPlan
    responsibilities: tuple[M2tsResponsibility, ...]
    output_emission_gates: tuple[M2tsEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def media_packet_count(self) -> int:
        return sum(
            packet.action in {"parse_pes_start", "accumulate_pes", "preserve_media_packet"}
            for packet in self.packets
        )

    @property
    def preserved_media_packet_count(self) -> int:
        return sum(
            packet.action
            in {
                "parse_pes_start",
                "accumulate_pes",
                "preserve_media_packet",
                "preserve_unknown_packet",
            }
            for packet in self.packets
        )

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"M2TS transport transaction output is gated: {gate_codes}")


def build_m2ts_transport_transaction_plan(data: bytes) -> M2tsTransportTransactionPlan:
    """Build a non-mutating transaction plan for MPEG-TS/M2TS transport routing."""

    sync, gates = detect_transport_sync(data)
    if sync.packet_size is None or sync.packet_start_offset is None:
        return _finish_plan(sync, (), (), (), (), (), (), gates, None, ())

    packets: list[M2tsTransportPacketPlan] = []
    programs: list[M2tsProgramPlan] = []
    streams: list[M2tsStreamPlan] = []
    routes: list[M2tsRoutePlan] = []
    pes_packets: list[M2tsPesPlan] = []
    ac3_descriptors: list[M2tsAc3DescriptorPlan] = []
    pmt_programs: dict[int, int] = {}
    pid_names: dict[int, str] = {
        0: "Program Association Table",
        1: "Conditional Access Table",
        2: "Transport Stream Description Table",
        NULL_PACKET_PID: "Null Packet",
    }
    pid_types: dict[int, int] = {}
    pending_pes_payloads: dict[int, bytes] = {}
    start_ticks: int | None = None
    end_ticks: int | None = None
    pcr_packet_indexes: list[int] = []

    packet_count = (len(data) - sync.packet_start_offset) // sync.packet_size
    for packet_index in range(packet_count):
        packet_offset = sync.packet_start_offset + packet_index * sync.packet_size
        transport_offset = packet_offset + (sync.timecode_prefix_size or 0)
        packet_end = packet_offset + sync.packet_size

        if data[transport_offset] != SYNC_BYTE:
            gates.append(
                M2tsEmissionGate(
                    "sync_byte_mismatch",
                    f"Packet {packet_index} does not contain sync byte 0x47.",
                    True,
                    (M2TS_PACKET_PREFIX_SOURCE,),
                )
            )
            break

        header1 = data[transport_offset + 1]
        header2 = data[transport_offset + 2]
        header3 = data[transport_offset + 3]
        payload_unit_start_indicator = bool(header1 & 0x40)
        pid = ((header1 & 0x1F) << 8) | header2
        adaptation_field_exists = bool(header3 & 0x20)
        payload_data_exists = bool(header3 & 0x10)
        payload_offset = transport_offset + 4

        if adaptation_field_exists:
            if payload_offset >= packet_end:
                gates.append(_invalid_adaptation_gate(packet_index))
                break
            adaptation_length = data[payload_offset]
            payload_offset += 1
            adaptation_end = payload_offset + adaptation_length
            if adaptation_end > packet_end:
                gates.append(_invalid_adaptation_gate(packet_index))
                break
            if adaptation_length > 6 and data[payload_offset] & 0x10:
                pcr_base = int.from_bytes(data[payload_offset + 1 : payload_offset + 5], "big")
                pcr_ext = int.from_bytes(data[payload_offset + 5 : payload_offset + 7], "big")
                pcr_ticks = 300 * (2 * pcr_base + (pcr_ext >> 15)) + (pcr_ext & 0x01FF)
                end_ticks = pcr_ticks
                if start_ticks is None:
                    start_ticks = pcr_ticks
                pcr_packet_indexes.append(packet_index)
            payload_offset = adaptation_end

        action: M2tsPacketAction = "timestamp_only"
        if not payload_data_exists:
            action = "timestamp_only"
        elif pid == NULL_PACKET_PID:
            action = "preserve_null_packet"
        elif pid == 0:
            action = "parse_pat"
            _parse_pat(
                data,
                payload_offset,
                packet_end,
                packet_index,
                payload_unit_start_indicator,
                programs,
                pmt_programs,
                pid_names,
                routes,
                gates,
            )
        elif pid in pmt_programs:
            action = "parse_pmt"
            _parse_pmt(
                data,
                payload_offset,
                packet_end,
                packet_index,
                payload_unit_start_indicator,
                pmt_programs[pid],
                pid_names,
                pid_types,
                streams,
                ac3_descriptors,
                routes,
                gates,
            )
        elif pid in pid_types or pid in pending_pes_payloads:
            action = _parse_pes_packet(
                data,
                payload_offset,
                packet_end,
                packet_index,
                payload_unit_start_indicator,
                pid,
                pid_types.get(pid),
                pid_names.get(pid, f"PID 0x{pid:04x}"),
                pending_pes_payloads,
                pes_packets,
                routes,
                gates,
            )
        else:
            action = "preserve_unknown_packet"

        packets.append(
            M2tsTransportPacketPlan(
                index=packet_index,
                offset=packet_offset,
                payload_offset=payload_offset,
                payload_end_offset=packet_end,
                pid=pid,
                action=action,
                payload_unit_start_indicator=payload_unit_start_indicator,
                adaptation_field_exists=adaptation_field_exists,
                payload_data_exists=payload_data_exists,
                evidence_ids=(M2TS_PACKET_PREFIX_SOURCE,),
            )
        )

    timestamp = build_timestamp_plan(start_ticks, end_ticks, tuple(pcr_packet_indexes))
    return _finish_plan(
        sync,
        tuple(packets),
        tuple(programs),
        tuple(streams),
        tuple(routes),
        tuple(pes_packets),
        tuple(ac3_descriptors),
        gates,
        timestamp,
        tuple(pending_pes_payloads),
    )


def detect_transport_sync(data: bytes) -> tuple[M2tsSyncPlan, list[M2tsEmissionGate]]:
    gates: list[M2tsEmissionGate] = []
    if len(data) < M2T_PACKET_SIZE * 4:
        gates.append(
            M2tsEmissionGate(
                "insufficient_packets_for_validation",
                "ExifTool requires enough bytes to validate at least four packets.",
                True,
                (M2TS_SYNC_SOURCE,),
            )
        )
        return M2tsSyncPlan("invalid", None, None, None, 0), gates

    best: tuple[int, int, int] | None = None
    for packet_size, timecode_size in (
        (M2T_PACKET_SIZE, 0),
        (M2TS_PACKET_SIZE, 4),
    ):
        max_start = min(190, len(data) - packet_size * 4)
        for packet_start in range(max_start + 1):
            transport_start = packet_start + timecode_size
            positions = tuple(transport_start + packet_size * index for index in range(4))
            if positions[-1] >= len(data):
                continue
            if all(data[position] == SYNC_BYTE for position in positions):
                best = (packet_size, timecode_size, packet_start)
                break
        if best is not None:
            break

    if best is None:
        gates.append(
            M2tsEmissionGate(
                "sync_byte_detection_failed",
                "No 188-byte or 192-byte transport sync-byte cadence was found.",
                True,
                (M2TS_SYNC_SOURCE,),
            )
        )
        return M2tsSyncPlan("invalid", None, None, None, 0), gates

    packet_size, timecode_size, packet_start = best
    if packet_start:
        gates.append(
            M2tsEmissionGate(
                "packet_alignment_offset",
                "Input has leading bytes before the first validated transport packet.",
                True,
                (M2TS_SYNC_SOURCE,),
            )
        )

    trailing_bytes = (len(data) - packet_start) % packet_size
    if trailing_bytes:
        gates.append(
            M2tsEmissionGate(
                "truncated_packet_tail",
                "Input ends with bytes that do not complete a transport packet.",
                True,
                (M2TS_SYNC_SOURCE,),
            )
        )

    file_kind: M2tsFileKind = "m2ts" if timecode_size else "m2t"
    return M2tsSyncPlan(file_kind, packet_size, timecode_size, packet_start, 4), gates


def build_timestamp_plan(
    start_ticks: int | None,
    end_ticks: int | None,
    pcr_packet_indexes: tuple[int, ...],
) -> M2tsTimestampPlan:
    duration_ticks: int | None = None
    duration_seconds: float | None = None
    if start_ticks is not None and end_ticks is not None:
        adjusted_end = end_ticks
        if start_ticks > adjusted_end:
            adjusted_end += 0x80000000 * 1200
        duration_ticks = adjusted_end - start_ticks
        duration_seconds = duration_ticks / PCR_CLOCK_HZ
    return M2tsTimestampPlan(
        start_ticks,
        end_ticks,
        duration_ticks,
        duration_seconds,
        pcr_packet_indexes,
    )


def stream_type_name(stream_type: int) -> str:
    known = STREAM_TYPE_NAMES.get(stream_type)
    if known is not None:
        return known
    if stream_type < 0x7F:
        return "Reserved"
    return "Private"


def _parse_pat(
    data: bytes,
    payload_offset: int,
    packet_end: int,
    packet_index: int,
    payload_unit_start_indicator: bool,
    programs: list[M2tsProgramPlan],
    pmt_programs: dict[int, int],
    pid_names: dict[int, str],
    routes: list[M2tsRoutePlan],
    gates: list[M2tsEmissionGate],
) -> None:
    section_offset = _section_payload_offset(
        data, payload_offset, packet_end, packet_index, payload_unit_start_indicator, gates
    )
    if section_offset is None:
        return
    section = _read_section(data, section_offset, packet_end, packet_index, 0x00, gates)
    if section is None:
        return
    pos = 8
    end = section.section_length + 3 - 4
    while pos <= end - 4:
        program_number = int.from_bytes(section.payload[pos : pos + 2], "big")
        program_map_pid = int.from_bytes(section.payload[pos + 2 : pos + 4], "big") & 0x1FFF
        programs.append(M2tsProgramPlan(program_number, program_map_pid))
        pmt_programs[program_map_pid] = program_number
        name = f"Program {program_number} Map"
        pid_names[program_map_pid] = name
        routes.append(
            M2tsRoutePlan(
                "program_association_table",
                program_map_pid,
                name,
                packet_index,
                (M2TS_PAT_PMT_SOURCE,),
            )
        )
        pos += 4


def _parse_pmt(
    data: bytes,
    payload_offset: int,
    packet_end: int,
    packet_index: int,
    payload_unit_start_indicator: bool,
    program_number: int,
    pid_names: dict[int, str],
    pid_types: dict[int, int],
    streams: list[M2tsStreamPlan],
    ac3_descriptors: list[M2tsAc3DescriptorPlan],
    routes: list[M2tsRoutePlan],
    gates: list[M2tsEmissionGate],
) -> None:
    section_offset = _section_payload_offset(
        data, payload_offset, packet_end, packet_index, payload_unit_start_indicator, gates
    )
    if section_offset is None:
        return
    section = _read_section(data, section_offset, packet_end, packet_index, 0x02, gates)
    if section is None:
        return
    pos = 8
    if pos + 4 > len(section.payload):
        gates.append(
            _simple_gate("truncated_pmt", packet_index, "PMT ended before PCR PID fields.")
        )
        return
    pcr_pid = int.from_bytes(section.payload[pos : pos + 2], "big") & 0x1FFF
    program_info_length = int.from_bytes(section.payload[pos + 2 : pos + 4], "big") & 0x0FFF
    pcr_name = f"Program {program_number} Clock Reference"
    pid_names[pcr_pid] = pcr_name
    routes.append(
        M2tsRoutePlan(
            "program_clock_reference",
            pcr_pid,
            pcr_name,
            packet_index,
            (M2TS_PAT_PMT_SOURCE, M2TS_ADAPTATION_PCR_SOURCE),
        )
    )
    pos += 4
    if pos + program_info_length > len(section.payload):
        gates.append(
            _simple_gate(
                "truncated_program_info",
                packet_index,
                "PMT program descriptor bytes exceed the available section payload.",
            )
        )
        return
    pos += program_info_length
    end = section.section_length + 3 - 4
    while pos <= end - 5:
        stream_type = section.payload[pos]
        elementary_pid = int.from_bytes(section.payload[pos + 1 : pos + 3], "big") & 0x1FFF
        es_info_length = int.from_bytes(section.payload[pos + 3 : pos + 5], "big") & 0x0FFF
        name = stream_type_name(stream_type)
        stream_name = f"Program {program_number} {name} (0x{stream_type:02x})"
        stream = M2tsStreamPlan(
            program_number,
            elementary_pid,
            stream_type,
            name,
            "Audio" in name,
            "Video" in name,
            es_info_length,
        )
        streams.append(stream)
        pid_names[elementary_pid] = stream_name
        pid_types[elementary_pid] = stream_type
        routes.append(
            M2tsRoutePlan(
                "elementary_stream",
                elementary_pid,
                stream_name,
                packet_index,
                (M2TS_PAT_PMT_SOURCE, M2TS_STREAM_TYPE_SOURCE, M2TS_MAIN_TAG_SOURCE),
            )
        )
        pos += 5
        if pos + es_info_length > len(section.payload):
            gates.append(
                _simple_gate(
                    "truncated_es_info",
                    packet_index,
                    "Elementary-stream descriptor bytes exceed the available PMT payload.",
                )
            )
            return
        descriptor_pos = pos
        while descriptor_pos + 2 <= pos + es_info_length:
            descriptor_tag = section.payload[descriptor_pos]
            descriptor_length = section.payload[descriptor_pos + 1]
            descriptor_pos += 2
            if descriptor_pos + descriptor_length > pos + es_info_length:
                break
            if descriptor_tag == 0x81:
                descriptor_payload = section.payload[
                    descriptor_pos : descriptor_pos + descriptor_length
                ]
                ac3_descriptors.append(
                    _parse_ac3_descriptor(elementary_pid, packet_index, descriptor_payload)
                )
                routes.append(
                    M2tsRoutePlan(
                        "ac3_descriptor",
                        elementary_pid,
                        "AC-3 stream descriptor",
                        packet_index,
                        (M2TS_PAT_PMT_SOURCE, M2TS_MAIN_TAG_SOURCE),
                    )
                )
            descriptor_pos += descriptor_length
        pos += es_info_length


def _parse_ac3_descriptor(
    pid: int,
    packet_index: int,
    descriptor_payload: bytes,
) -> M2tsAc3DescriptorPlan:
    if len(descriptor_payload) < 3:
        return M2tsAc3DescriptorPlan(pid, packet_index, None, None, None)
    bitrate_code = descriptor_payload[1] >> 2
    channel_code = (descriptor_payload[2] >> 1) & 0x0F
    bitrate_lookup: dict[int, int | None] = {
        0: 32000,
        1: 40000,
        2: 48000,
        3: 56000,
        4: 64000,
        5: 80000,
        6: 96000,
        7: 112000,
        8: 128000,
        9: 160000,
        10: 192000,
        11: 224000,
        12: 256000,
        13: 320000,
        14: 384000,
        15: 448000,
        16: 512000,
        17: 576000,
        18: 640000,
    }
    channels: dict[int, int | str] = {
        0: "1 + 1",
        1: 1,
        2: 2,
        3: 3,
        4: "2/1",
        5: "3/1",
        6: "2/2",
        7: "3/2",
        8: 1,
        9: "2 max",
        10: "3 max",
        11: "4 max",
        12: "5 max",
        13: "6 max",
    }
    surround = {0: "Not indicated", 1: "Not Dolby surround", 2: "Dolby surround"}.get(
        descriptor_payload[1] & 0x03
    )
    return M2tsAc3DescriptorPlan(
        pid,
        packet_index,
        bitrate_lookup.get(bitrate_code),
        surround,
        channels.get(channel_code),
    )


def _parse_pes_packet(
    data: bytes,
    payload_offset: int,
    packet_end: int,
    packet_index: int,
    payload_unit_start_indicator: bool,
    pid: int,
    stream_type: int | None,
    pid_name: str,
    pending_pes_payloads: dict[int, bytes],
    pes_packets: list[M2tsPesPlan],
    routes: list[M2tsRoutePlan],
    gates: list[M2tsEmissionGate],
) -> M2tsPacketAction:
    if not payload_unit_start_indicator:
        pending_pes_payloads[pid] = (
            pending_pes_payloads.get(pid, b"") + data[payload_offset:packet_end]
        )
        return "accumulate_pes"

    if payload_offset + 6 > packet_end:
        return "preserve_media_packet"

    start_code = int.from_bytes(data[payload_offset : payload_offset + 4], "big")
    if (start_code & 0xFFFFFF00) != PES_START_CODE_PREFIX:
        return "preserve_media_packet"

    stream_id = start_code & 0xFF
    pes_packet_length = int.from_bytes(data[payload_offset + 4 : payload_offset + 6], "big")
    pos = payload_offset + 6
    if stream_id not in NO_SYNTAX_STREAM_IDS:
        if pos + 3 > packet_end:
            return "preserve_media_packet"
        if data[pos] & 0xC0 != 0x80:
            gates.append(
                _simple_gate(
                    "bad_pes_syntax",
                    packet_index,
                    f"PES packet on PID 0x{pid:04x} does not have 0x80 syntax marker.",
                )
            )
            return "preserve_media_packet"
        pes_header_data_length = data[pos + 2]
        pos += 3 + pes_header_data_length
        if pos >= packet_end:
            return "preserve_media_packet"

    retained_payload = data[pos:packet_end]
    pending_pes_payloads[pid] = retained_payload
    pes_packets.append(
        M2tsPesPlan(
            pid,
            packet_index,
            stream_id,
            pes_packet_length,
            pos,
            len(retained_payload),
            stream_type,
        )
    )
    routes.append(
        M2tsRoutePlan(
            "pes_payload",
            pid,
            pid_name,
            packet_index,
            (M2TS_PES_SOURCE,),
        )
    )
    return "parse_pes_start"


@dataclass(frozen=True)
class _SectionPayload:
    payload: bytes
    section_length: int


def _section_payload_offset(
    data: bytes,
    payload_offset: int,
    packet_end: int,
    packet_index: int,
    payload_unit_start_indicator: bool,
    gates: list[M2tsEmissionGate],
) -> int | None:
    if not payload_unit_start_indicator:
        return payload_offset
    if payload_offset >= packet_end:
        gates.append(_simple_gate("bad_pointer_field", packet_index, "Missing pointer field."))
        return None
    pointer_field = data[payload_offset]
    section_offset = payload_offset + 1 + pointer_field
    if section_offset >= packet_end:
        gates.append(
            _simple_gate(
                "bad_pointer_field",
                packet_index,
                "Pointer field skips beyond the packet payload.",
            )
        )
        return None
    return section_offset


def _read_section(
    data: bytes,
    section_offset: int,
    packet_end: int,
    packet_index: int,
    expected_table_id: int,
    gates: list[M2tsEmissionGate],
) -> _SectionPayload | None:
    if section_offset + 8 > packet_end:
        gates.append(
            _simple_gate(
                "truncated_payload_section",
                packet_index,
                "Section header is shorter than the ExifTool PAT/PMT minimum.",
            )
        )
        return None
    table_id = data[section_offset]
    if table_id != expected_table_id:
        return None
    syntax = data[section_offset + 1] & 0xC0
    if syntax != 0x80:
        gates.append(
            _simple_gate("bad_table_syntax", packet_index, "PAT/PMT syntax bits are invalid.")
        )
        return None
    section_length = int.from_bytes(data[section_offset + 1 : section_offset + 3], "big") & 0x0FFF
    if section_length > 1021:
        gates.append(
            _simple_gate(
                "invalid_section_length",
                packet_index,
                "PAT/PMT section_length exceeds ExifTool's 1021-byte limit.",
            )
        )
        return None
    section_end = section_offset + section_length + 3
    if section_end > packet_end:
        gates.append(
            _simple_gate(
                "truncated_payload_section",
                packet_index,
                "PAT/PMT section_length extends beyond the packet payload.",
            )
        )
        return None
    return _SectionPayload(data[section_offset:section_end], section_length)


def _finish_plan(
    sync: M2tsSyncPlan,
    packets: tuple[M2tsTransportPacketPlan, ...],
    programs: tuple[M2tsProgramPlan, ...],
    streams: tuple[M2tsStreamPlan, ...],
    routes: tuple[M2tsRoutePlan, ...],
    pes_packets: tuple[M2tsPesPlan, ...],
    ac3_descriptors: tuple[M2tsAc3DescriptorPlan, ...],
    gates: list[M2tsEmissionGate],
    timestamp: M2tsTimestampPlan | None,
    pending_pids: tuple[int, ...],
) -> M2tsTransportTransactionPlan:
    if timestamp is None:
        timestamp = build_timestamp_plan(None, None, ())
    gates.extend(
        (
            M2tsEmissionGate(
                "planner_is_non_mutating",
                "The M2TS transport planner records transaction decisions only.",
                True,
                (M2TS_OUTPUT_BOUNDARY_SOURCE,),
            ),
            M2tsEmissionGate(
                "full_transport_writer_not_implemented",
                (
                    "Safe M2TS emission requires packet, PSI, PES, continuity, "
                    "and timestamp rebuilding."
                ),
                True,
                (M2TS_OUTPUT_BOUNDARY_SOURCE, M2TS_PAT_PMT_SOURCE, M2TS_PES_SOURCE),
            ),
        )
    )
    responsibilities = _build_responsibilities(
        sync,
        packets,
        programs,
        streams,
        routes,
        timestamp,
        pending_pids,
    )
    sources = (
        M2TS_SYNC_SOURCE,
        M2TS_PACKET_PREFIX_SOURCE,
        M2TS_ADAPTATION_PCR_SOURCE,
        M2TS_PAT_PMT_SOURCE,
        M2TS_PES_SOURCE,
        M2TS_DURATION_SOURCE,
        M2TS_STREAM_TYPE_SOURCE,
        M2TS_MAIN_TAG_SOURCE,
        M2TS_OUTPUT_BOUNDARY_SOURCE,
    )
    return M2tsTransportTransactionPlan(
        sync,
        packets,
        programs,
        streams,
        routes,
        pes_packets,
        ac3_descriptors,
        timestamp,
        responsibilities,
        tuple(gates),
        sources,
    )


def _build_responsibilities(
    sync: M2tsSyncPlan,
    packets: tuple[M2tsTransportPacketPlan, ...],
    programs: tuple[M2tsProgramPlan, ...],
    streams: tuple[M2tsStreamPlan, ...],
    routes: tuple[M2tsRoutePlan, ...],
    timestamp: M2tsTimestampPlan,
    pending_pids: tuple[int, ...],
) -> tuple[M2tsResponsibility, ...]:
    return (
        M2tsResponsibility(
            1,
            "packet_size_and_sync_validation",
            "Detect 188-byte M2T versus 192-byte M2TS packet cadence using sync bytes.",
            (sync.file_kind, f"packet_size={sync.packet_size}"),
            (M2TS_SYNC_SOURCE,),
        ),
        M2tsResponsibility(
            2,
            "packet_alignment_and_truncation",
            (
                "Expose leading alignment offsets and incomplete trailing packet bytes "
                "as emission blockers."
            ),
            (f"packet_start_offset={sync.packet_start_offset}", f"packets={len(packets)}"),
            (M2TS_SYNC_SOURCE,),
        ),
        M2tsResponsibility(
            3,
            "pid_program_and_pmt_routing",
            "Route PAT programs, PMT PIDs, PCR PIDs, and elementary stream PIDs.",
            (
                f"programs={len(programs)}",
                f"streams={len(streams)}",
                f"routes={len(routes)}",
            ),
            (M2TS_PAT_PMT_SOURCE,),
        ),
        M2tsResponsibility(
            4,
            "pes_media_payload_routing",
            "Preserve and identify PES payload starts before media parser handoff.",
            tuple(f"pending_pid=0x{pid:04x}" for pid in pending_pids),
            (M2TS_PES_SOURCE,),
        ),
        M2tsResponsibility(
            5,
            "timestamp_duration_scan",
            "Track first and last PCR ticks and derive Duration in the 27 MHz clock domain.",
            (
                f"start_ticks={timestamp.start_ticks}",
                f"end_ticks={timestamp.end_ticks}",
                f"duration_ticks={timestamp.duration_ticks}",
            ),
            (M2TS_ADAPTATION_PCR_SOURCE, M2TS_DURATION_SOURCE, M2TS_MAIN_TAG_SOURCE),
        ),
        M2tsResponsibility(
            6,
            "stream_type_database",
            "Map PMT stream_type values to ExifTool audio, video, and metadata names.",
            tuple(f"0x{stream.stream_type:02x}:{stream.stream_type_name}" for stream in streams),
            (M2TS_STREAM_TYPE_SOURCE, M2TS_MAIN_TAG_SOURCE),
        ),
        M2tsResponsibility(
            7,
            "media_packet_preservation",
            "Preserve media, null, and unknown packets; this planner never rewrites payload bytes.",
            tuple(f"packet={packet.index}:pid=0x{packet.pid:04x}" for packet in packets),
            (M2TS_PACKET_PREFIX_SOURCE, M2TS_PES_SOURCE, M2TS_OUTPUT_BOUNDARY_SOURCE),
        ),
        M2tsResponsibility(
            8,
            "output_emission_gate",
            "Keep output emission closed until a full transport-stream writer exists.",
            ("non_mutating=True",),
            (M2TS_OUTPUT_BOUNDARY_SOURCE,),
        ),
    )


def _invalid_adaptation_gate(packet_index: int) -> M2tsEmissionGate:
    return _simple_gate(
        "invalid_adaptation_field_length",
        packet_index,
        "Adaptation-field length extends beyond the packet boundary.",
    )


def _simple_gate(
    code: M2tsEmissionGateCode,
    packet_index: int,
    reason: str,
) -> M2tsEmissionGate:
    return M2tsEmissionGate(
        code,
        f"Packet {packet_index}: {reason}",
        True,
        (M2TS_PACKET_PREFIX_SOURCE, M2TS_PAT_PMT_SOURCE, M2TS_PES_SOURCE),
    )
