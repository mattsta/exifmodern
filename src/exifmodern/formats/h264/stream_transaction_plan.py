"""Source-backed, non-mutating H.264 stream transaction planning.

The planner mirrors ExifTool's H264.pm read boundaries: scan Annex B start-code
NAL units, route only SEI and SPS NAL units for metadata discovery, preserve all
stream bytes, and keep byte emission behind explicit gates.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonValue

ANNEX_B_START_CODE_3 = b"\x00\x00\x01"
ANNEX_B_START_CODE_4 = b"\x00\x00\x00\x01"
H264_MDPM_UUID_AND_MARKER = bytes.fromhex("17ee8c60f84d11d98cd60800200c9a66") + b"MDPM"

type H264PlanStatus = Literal["planned", "unsupported"]
type H264NalStatus = Literal["valid", "empty", "invalid"]
type H264NalRouteKind = Literal[
    "sei_metadata",
    "sps_metadata",
    "preserved_unparsed",
    "blocked",
]
type H264SeiMessageKind = Literal[
    "picture_timing",
    "unregistered_user_data",
    "mdpm_user_data",
    "ignored",
    "terminator",
]
type H264ResponsibilityKind = Literal[
    "annex_b_nal_scan",
    "sps_image_size",
    "sei_user_data",
    "mdpm_metadata",
    "stream_preservation",
    "rewrite_boundary",
]
type H264PreservationKind = Literal["annex_b_nal_unit"]
type H264ReadTagGroup = Literal["Video", "Camera", "Image", "Time", "Location"]
type H264EmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "missing_annex_b_start_code",
    "empty_nal_unit",
    "forbidden_zero_bit_set",
    "truncated_sps_rbsp",
    "truncated_sei_message",
    "h264_metadata_rewrite_not_supported",
    "h264_stream_rewrite_not_implemented",
]

H264_MAIN_TABLE_SOURCE = "h264.main_table"
H264_MDPM_TABLE_SOURCE = "h264.mdpm_table"
H264_BITSTREAM_SOURCE = "h264.bitstream_helpers"
H264_SPS_SOURCE = "h264.sps_parser"
H264_SEI_SOURCE = "h264.sei_parser"
H264_PARSE_SOURCE = "h264.annex_b_parser"
H264_NON_MUTATING_SOURCE = "h264.non_mutating_plan"

H264_TRANSACTION_SOURCES = (
    H264_MAIN_TABLE_SOURCE,
    H264_MDPM_TABLE_SOURCE,
    H264_BITSTREAM_SOURCE,
    H264_SPS_SOURCE,
    H264_SEI_SOURCE,
    H264_PARSE_SOURCE,
    H264_NON_MUTATING_SOURCE,
)


@dataclass(frozen=True)
class H264MetadataRewriteRequest:
    image_width: int | None = None
    image_height: int | None = None
    mdpm_payload: bytes | None = None


@dataclass(frozen=True)
class H264StartCodePlan:
    offset: int
    length: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class H264SpsPlan:
    nal_index: int
    payload_offset: int
    rbsp_length: int
    status: Literal["valid", "truncated", "metadata_absent"]
    image_width: int | None
    image_height: int | None
    blocker_code: H264EmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class H264SeiMessagePlan:
    nal_index: int
    payload_type: int
    payload_size: int | None
    payload_offset: int
    payload_end_offset: int | None
    kind: H264SeiMessageKind
    mdpm_entry_count: int | None
    mdpm_payload: bytes | None
    status: Literal["valid", "truncated"]
    blocker_code: H264EmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class H264NalUnitPlan:
    index: int
    start_code: H264StartCodePlan
    header_offset: int
    end_offset: int
    raw_bytes: bytes
    header: int | None
    forbidden_zero_bit: bool | None
    nal_ref_idc: int | None
    nal_unit_type: int | None
    nal_unit_type_name: str
    route_kind: H264NalRouteKind
    status: H264NalStatus
    rbsp_payload: bytes
    blocker_code: H264EmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class H264PreservationPlan:
    nal_index: int
    kind: H264PreservationKind
    offset: int
    end_offset: int
    payload: bytes
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class H264ResponsibilityPlan:
    kind: H264ResponsibilityKind
    available: bool
    value: int | str | bool | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class H264ReadTagPlan:
    name: str
    value: JsonValue
    group: H264ReadTagGroup
    table_name: str
    tag_id: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class H264OutputEmissionGate:
    code: H264EmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class H264StreamTransactionPlan:
    status: H264PlanStatus
    input_size: int
    start_codes: tuple[H264StartCodePlan, ...]
    nal_units: tuple[H264NalUnitPlan, ...]
    sps_plans: tuple[H264SpsPlan, ...]
    sei_messages: tuple[H264SeiMessagePlan, ...]
    read_tags: tuple[H264ReadTagPlan, ...]
    preservation_actions: tuple[H264PreservationPlan, ...]
    responsibilities: tuple[H264ResponsibilityPlan, ...]
    output_emission_gates: tuple[H264OutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"H.264 stream transaction output is gated: {gate_codes}")
        return self.original_bytes


def build_h264_stream_transaction_plan(
    h264_data: bytes,
    *,
    requested_metadata: H264MetadataRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> H264StreamTransactionPlan:
    start_codes = _find_start_codes(h264_data)
    nal_units = _enumerate_nal_units(h264_data, start_codes)
    sps_plans = tuple(
        _build_sps_plan(unit)
        for unit in nal_units
        if unit.status == "valid" and unit.nal_unit_type == 7
    )
    sei_messages = tuple(
        message
        for unit in nal_units
        if unit.status == "valid" and unit.nal_unit_type == 6
        for message in _build_sei_messages(unit)
    )
    read_tags = _build_read_tags(sps_plans, sei_messages)
    preservation_actions = tuple(_preservation_action(unit) for unit in nal_units)
    gates = [
        *(_gate_for_nal_unit(unit) for unit in nal_units if unit.blocker_code is not None),
        *(_gate_for_sps(plan) for plan in sps_plans if plan.blocker_code is not None),
        *(_gate_for_sei(message) for message in sei_messages if message.blocker_code is not None),
    ]
    if not start_codes:
        gates.insert(
            0,
            H264OutputEmissionGate(
                "missing_annex_b_start_code",
                "H264.pm discovers NAL units by Annex B start-code scanning.",
                (H264_PARSE_SOURCE,),
            ),
        )
    if _has_rewrite_request(requested_metadata):
        gates.extend(
            (
                H264OutputEmissionGate(
                    "h264_metadata_rewrite_not_supported",
                    (
                        "H264.pm defines read extraction for SPS image size and MDPM, "
                        "not writable tags."
                    ),
                    (H264_MAIN_TABLE_SOURCE, H264_MDPM_TABLE_SOURCE, H264_SPS_SOURCE),
                ),
                H264OutputEmissionGate(
                    "h264_stream_rewrite_not_implemented",
                    "This planner preserves Annex B byte ranges and does not rebuild NAL payloads.",
                    (H264_PARSE_SOURCE, H264_NON_MUTATING_SOURCE),
                ),
            )
        )
    if not allow_output_emission:
        gates.append(
            H264OutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "H.264 stream transaction plans are non-mutating unless emission is explicit.",
                (H264_NON_MUTATING_SOURCE,),
            )
        )

    unique_output_gates = _unique_gates(tuple(gates))
    status: H264PlanStatus = (
        "unsupported" if _has_structural_gate(unique_output_gates) else "planned"
    )
    responsibilities = _responsibility_plans(
        nal_units=nal_units,
        sps_plans=sps_plans,
        sei_messages=sei_messages,
        preservation_actions=preservation_actions,
    )
    return H264StreamTransactionPlan(
        status=status,
        input_size=len(h264_data),
        start_codes=start_codes,
        nal_units=nal_units,
        sps_plans=sps_plans,
        sei_messages=sei_messages,
        read_tags=read_tags,
        preservation_actions=preservation_actions,
        responsibilities=responsibilities,
        output_emission_gates=unique_output_gates,
        evidence_ids=_unique_evidence_ids(
            (
                *H264_TRANSACTION_SOURCES,
                *(source for unit in nal_units for source in unit.evidence_ids),
                *(source for plan in sps_plans for source in plan.evidence_ids),
                *(source for message in sei_messages for source in message.evidence_ids),
                *(source for tag in read_tags for source in tag.evidence_ids),
                *(source for gate in unique_output_gates for source in gate.evidence_ids),
            )
        ),
        original_bytes=h264_data,
    )


plan_h264_stream_transaction = build_h264_stream_transaction_plan


def _find_start_codes(h264_data: bytes) -> tuple[H264StartCodePlan, ...]:
    start_codes: list[H264StartCodePlan] = []
    offset = 0
    while offset < len(h264_data):
        if h264_data.startswith(ANNEX_B_START_CODE_4, offset):
            start_codes.append(H264StartCodePlan(offset, 4, (H264_PARSE_SOURCE,)))
            offset += 4
        elif h264_data.startswith(ANNEX_B_START_CODE_3, offset):
            start_codes.append(H264StartCodePlan(offset, 3, (H264_PARSE_SOURCE,)))
            offset += 3
        else:
            offset += 1
    return tuple(start_codes)


def _enumerate_nal_units(
    h264_data: bytes,
    start_codes: tuple[H264StartCodePlan, ...],
) -> tuple[H264NalUnitPlan, ...]:
    units: list[H264NalUnitPlan] = []
    for index, start_code in enumerate(start_codes):
        header_offset = start_code.offset + start_code.length
        end_offset = (
            start_codes[index + 1].offset if index + 1 < len(start_codes) else len(h264_data)
        )
        raw_bytes = h264_data[start_code.offset : end_offset]
        if header_offset >= end_offset:
            units.append(
                H264NalUnitPlan(
                    index=index,
                    start_code=start_code,
                    header_offset=header_offset,
                    end_offset=end_offset,
                    raw_bytes=raw_bytes,
                    header=None,
                    forbidden_zero_bit=None,
                    nal_ref_idc=None,
                    nal_unit_type=None,
                    nal_unit_type_name="empty",
                    route_kind="blocked",
                    status="empty",
                    rbsp_payload=b"",
                    blocker_code="empty_nal_unit",
                    evidence_ids=(H264_PARSE_SOURCE,),
                )
            )
            continue

        header = h264_data[header_offset]
        forbidden_zero_bit = (header & 0x80) != 0
        nal_unit_type = header & 0x1F
        route_kind = _route_for_nal_type(nal_unit_type)
        blocker_code: H264EmissionGateCode | None = None
        status: H264NalStatus = "valid"
        if forbidden_zero_bit:
            route_kind = "blocked"
            status = "invalid"
            blocker_code = "forbidden_zero_bit_set"
        payload = h264_data[header_offset + 1 : end_offset]
        units.append(
            H264NalUnitPlan(
                index=index,
                start_code=start_code,
                header_offset=header_offset,
                end_offset=end_offset,
                raw_bytes=raw_bytes,
                header=header,
                forbidden_zero_bit=forbidden_zero_bit,
                nal_ref_idc=(header >> 5) & 0x03,
                nal_unit_type=nal_unit_type,
                nal_unit_type_name=_nal_type_name(nal_unit_type),
                route_kind=route_kind,
                status=status,
                rbsp_payload=_remove_emulation_prevention_bytes(payload),
                blocker_code=blocker_code,
                evidence_ids=(H264_PARSE_SOURCE,),
            )
        )
    return tuple(units)


def _route_for_nal_type(nal_unit_type: int) -> H264NalRouteKind:
    if nal_unit_type == 6:
        return "sei_metadata"
    if nal_unit_type == 7:
        return "sps_metadata"
    return "preserved_unparsed"


def _nal_type_name(nal_unit_type: int) -> str:
    names = {
        1: "coded_slice_non_idr",
        5: "coded_slice_idr",
        6: "sei_rbsp",
        7: "sequence_parameter_set_rbsp",
        8: "picture_parameter_set_rbsp",
        9: "access_unit_delimiter",
    }
    return names.get(nal_unit_type, f"nal_type_{nal_unit_type}")


def _remove_emulation_prevention_bytes(payload: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(payload):
        if index + 2 < len(payload) and payload[index : index + 3] == b"\x00\x00\x03":
            output.extend(b"\x00\x00")
            index += 3
        else:
            output.append(payload[index])
            index += 1
    return bytes(output)


def _build_sps_plan(unit: H264NalUnitPlan) -> H264SpsPlan:
    try:
        width, height = _parse_sps_dimensions(unit.rbsp_payload)
    except _BitReadError:
        return H264SpsPlan(
            nal_index=unit.index,
            payload_offset=unit.header_offset + 1,
            rbsp_length=len(unit.rbsp_payload),
            status="truncated",
            image_width=None,
            image_height=None,
            blocker_code="truncated_sps_rbsp",
            evidence_ids=(H264_SPS_SOURCE, H264_BITSTREAM_SOURCE),
        )
    status: Literal["valid", "truncated", "metadata_absent"] = (
        "valid" if width is not None and height is not None else "metadata_absent"
    )
    return H264SpsPlan(
        nal_index=unit.index,
        payload_offset=unit.header_offset + 1,
        rbsp_length=len(unit.rbsp_payload),
        status=status,
        image_width=width,
        image_height=height,
        blocker_code=None,
        evidence_ids=(H264_SPS_SOURCE, H264_BITSTREAM_SOURCE, H264_MAIN_TABLE_SOURCE),
    )


def _parse_sps_dimensions(rbsp_payload: bytes) -> tuple[int | None, int | None]:
    reader = _BitReader(rbsp_payload)
    profile_idc = reader.read_bits(8)
    reader.read_bits(16)
    reader.read_unsigned_golomb()
    if profile_idc >= 100:
        chroma_format_idc = reader.read_unsigned_golomb()
        scaling_count = 12 if chroma_format_idc == 3 else 8
        if chroma_format_idc == 3:
            reader.read_bits(1)
        reader.read_unsigned_golomb()
        reader.read_unsigned_golomb()
        reader.read_bits(1)
        _decode_scaling_matrices(reader, scaling_count)
    reader.read_unsigned_golomb()
    pic_order_cnt_type = reader.read_unsigned_golomb()
    if pic_order_cnt_type == 0:
        reader.read_unsigned_golomb()
    elif pic_order_cnt_type == 1:
        reader.read_bits(1)
        reader.read_signed_golomb()
        reader.read_signed_golomb()
        ref_count = reader.read_unsigned_golomb()
        for _ in range(ref_count):
            reader.read_signed_golomb()
    reader.read_unsigned_golomb()
    reader.read_bits(1)
    width_in_mbs_minus_1 = reader.read_unsigned_golomb()
    height_in_map_units_minus_1 = reader.read_unsigned_golomb()
    frame_mbs_only_flag = reader.read_bits(1)
    if frame_mbs_only_flag == 0:
        reader.read_bits(1)
    reader.read_bits(1)
    width = (width_in_mbs_minus_1 + 1) * 16
    height = (2 - frame_mbs_only_flag) * (height_in_map_units_minus_1 + 1) * 16
    if reader.read_bits(1):
        crop_unit_y = 4 - frame_mbs_only_flag * 2
        width -= 4 * reader.read_unsigned_golomb()
        width -= 4 * reader.read_unsigned_golomb()
        height -= crop_unit_y * reader.read_unsigned_golomb()
        height -= crop_unit_y * reader.read_unsigned_golomb()
    if 160 <= width <= 4096 and 120 <= height <= 3072:
        return width, height
    return None, None


def _decode_scaling_matrices(reader: _BitReader, scaling_count: int) -> None:
    if not reader.read_bits(1):
        return
    for index in range(scaling_count):
        size = 16 if index < 6 else 64
        if not reader.read_bits(1):
            continue
        last_scale = 8
        next_scale = 8
        for matrix_index in range(size):
            if next_scale:
                next_scale = (last_scale + reader.read_signed_golomb()) & 0xFF
            if matrix_index != 0 and next_scale == 0:
                break
            last_scale = next_scale


def _build_sei_messages(unit: H264NalUnitPlan) -> tuple[H264SeiMessagePlan, ...]:
    messages: list[H264SeiMessagePlan] = []
    position = 0
    rbsp_payload = unit.rbsp_payload
    while position < len(rbsp_payload):
        type_start = position
        payload_type = 0
        while True:
            if position >= len(rbsp_payload):
                messages.append(_truncated_sei(unit, type_start, position))
                return tuple(messages)
            current = rbsp_payload[position]
            position += 1
            payload_type += current
            if current != 255:
                break
        if payload_type == 0x80:
            messages.append(
                H264SeiMessagePlan(
                    nal_index=unit.index,
                    payload_type=payload_type,
                    payload_size=0,
                    payload_offset=position,
                    payload_end_offset=position,
                    kind="terminator",
                    mdpm_entry_count=None,
                    mdpm_payload=None,
                    status="valid",
                    blocker_code=None,
                    evidence_ids=(H264_SEI_SOURCE,),
                )
            )
            return tuple(messages)

        size_start = position
        payload_size = 0
        while True:
            if position >= len(rbsp_payload):
                messages.append(_truncated_sei(unit, size_start, position))
                return tuple(messages)
            current = rbsp_payload[position]
            position += 1
            payload_size += current
            if current != 255:
                break
        payload_offset = position
        payload_end = position + payload_size
        if payload_end > len(rbsp_payload):
            messages.append(_truncated_sei(unit, payload_offset, len(rbsp_payload)))
            return tuple(messages)
        payload = rbsp_payload[payload_offset:payload_end]
        kind = _sei_kind(payload_type, payload)
        mdpm_payload = payload if kind == "mdpm_user_data" else None
        messages.append(
            H264SeiMessagePlan(
                nal_index=unit.index,
                payload_type=payload_type,
                payload_size=payload_size,
                payload_offset=unit.header_offset + 1 + payload_offset,
                payload_end_offset=unit.header_offset + 1 + payload_end,
                kind=kind,
                mdpm_entry_count=payload[20] if kind == "mdpm_user_data" else None,
                mdpm_payload=mdpm_payload,
                status="valid",
                blocker_code=None,
                evidence_ids=(H264_SEI_SOURCE, H264_MDPM_TABLE_SOURCE)
                if kind == "mdpm_user_data"
                else (H264_SEI_SOURCE,),
            )
        )
        position = payload_end
    return tuple(messages)


def _truncated_sei(
    unit: H264NalUnitPlan,
    payload_offset: int,
    available_end: int,
) -> H264SeiMessagePlan:
    return H264SeiMessagePlan(
        nal_index=unit.index,
        payload_type=0,
        payload_size=None,
        payload_offset=unit.header_offset + 1 + payload_offset,
        payload_end_offset=unit.header_offset + 1 + available_end,
        kind="ignored",
        mdpm_entry_count=None,
        mdpm_payload=None,
        status="truncated",
        blocker_code="truncated_sei_message",
        evidence_ids=(H264_SEI_SOURCE,),
    )


def _sei_kind(payload_type: int, payload: bytes) -> H264SeiMessageKind:
    if payload_type == 1:
        return "picture_timing"
    if payload_type == 5:
        if len(payload) > 20 and payload.startswith(H264_MDPM_UUID_AND_MARKER):
            return "mdpm_user_data"
        return "unregistered_user_data"
    return "ignored"


def _build_read_tags(
    sps_plans: tuple[H264SpsPlan, ...],
    sei_messages: tuple[H264SeiMessagePlan, ...],
) -> tuple[H264ReadTagPlan, ...]:
    tags: list[H264ReadTagPlan] = []
    for sps in sps_plans:
        if sps.status != "valid" or sps.image_width is None or sps.image_height is None:
            continue
        tags.extend(
            (
                H264ReadTagPlan(
                    "ImageWidth",
                    sps.image_width,
                    "Video",
                    "Image::ExifTool::H264::Main",
                    "ImageWidth",
                    sps.evidence_ids,
                ),
                H264ReadTagPlan(
                    "ImageHeight",
                    sps.image_height,
                    "Video",
                    "Image::ExifTool::H264::Main",
                    "ImageHeight",
                    sps.evidence_ids,
                ),
            )
        )
        break
    for message in sei_messages:
        if message.kind != "mdpm_user_data" or message.mdpm_payload is None:
            continue
        tags.extend(_build_mdpm_read_tags(message.mdpm_payload, message.evidence_ids))
        break
    return tuple(tags)


def _build_mdpm_read_tags(payload: bytes, sources: tuple[str, ...]) -> tuple[H264ReadTagPlan, ...]:
    if len(payload) <= 20 or not payload.startswith(H264_MDPM_UUID_AND_MARKER):
        return ()
    entry_count = payload[20]
    position = 21
    last_tag = 0
    entries: dict[int, bytes] = {}
    for _ in range(entry_count):
        if position + 5 > len(payload):
            break
        tag_id = payload[position]
        if tag_id <= last_tag:
            break
        last_tag = tag_id
        entries[tag_id] = payload[position + 1 : position + 5]
        position += 5

    tags: list[H264ReadTagPlan] = []
    date_value = _mdpm_date_time_original(entries)
    if date_value is not None:
        tags.append(_h264_tag("DateTimeOriginal", date_value, "Time", "0x18", sources))
    camera1 = entries.get(0x70)
    if camera1 is not None:
        aperture = _mdpm_camera1_aperture(camera1[0])
        if aperture is not None:
            tags.append(_h264_tag("ApertureSetting", aperture, "Camera", "0x70.0", sources))
        gain = _mdpm_camera1_gain(camera1[1])
        if gain is not None:
            tags.append(_h264_tag("Gain", gain, "Camera", "0x70.1", sources))
    camera2 = entries.get(0x71)
    if camera2 is not None and len(camera2) > 1:
        tags.append(
            _h264_tag(
                "ImageStabilization",
                _mdpm_image_stabilization(camera2[1]),
                "Camera",
                "0x71.1",
                sources,
            )
        )
    shutter = entries.get(0x7F)
    if shutter is not None:
        exposure_time = _mdpm_shutter_exposure_time(shutter)
        if exposure_time is not None:
            tags.append(_h264_tag("ExposureTime", exposure_time, "Image", "0x7f.1.1", sources))
    make = _mdpm_make(entries.get(0xE0))
    if make is not None:
        tags.append(_h264_tag("Make", make, "Camera", "0xe0.0", sources))
    rec_info = entries.get(0xE1)
    if make == "Canon" and rec_info is not None:
        mode = {0x02: "XP+", 0x04: "SP", 0x05: "LP", 0x06: "FXP", 0x07: "MXP"}.get(rec_info[0])
        if mode is not None:
            tags.append(_h264_tag("RecordingMode", mode, "Camera", "0xe1.0", sources))
    return tuple(tags)


def _h264_tag(
    name: str,
    value: JsonValue,
    group: H264ReadTagGroup,
    tag_id: str,
    sources: tuple[str, ...],
) -> H264ReadTagPlan:
    return H264ReadTagPlan(name, value, group, "Image::ExifTool::H264::MDPM", tag_id, sources)


def _mdpm_date_time_original(entries: dict[int, bytes]) -> str | None:
    first = entries.get(0x18)
    second = entries.get(0x19)
    if first is None or second is None:
        return None
    combined = first + second
    if len(combined) != 8:
        return None
    tz = combined[0]
    digits = "".join(f"{value:02x}" for value in combined[1:])
    sign = "-" if tz & 0x20 else "+"
    hours = (tz >> 1) & 0x0F
    minutes = "30" if tz & 0x01 else "00"
    suffix = " DST" if tz & 0x40 else ""
    return (
        f"{digits[0:4]}:{digits[4:6]}:{digits[6:8]} "
        f"{digits[8:10]}:{digits[10:12]}:{digits[12:14]}{sign}{hours:02d}:{minutes}{suffix}"
    )


def _mdpm_camera1_aperture(value: int) -> str | None:
    if value == 0xFF:
        return "Auto"
    if value == 0xFE:
        return "Closed"
    return f"{2 ** ((value & 0x3F) / 8):.1f}"


def _mdpm_camera1_gain(value: int) -> str | None:
    converted = ((value & 0x0F) - 1) * 3
    return "Out of range" if converted == 42 else f"{converted} dB"


def _mdpm_image_stabilization(value: int) -> str:
    if value == 0:
        return "Off"
    if value == 0x3F:
        return "On (0x3f)"
    if value == 0xBF:
        return "Off (0xbf)"
    if value == 0xFF:
        return "n/a"
    return f"{'On' if value & 0x10 else 'Off'} (0x{value:02x})"


def _mdpm_shutter_exposure_time(payload: bytes) -> str | None:
    if len(payload) < 4:
        return None
    raw = int.from_bytes(payload[2:4], "little") & 0x7FFF
    if raw == 0x7FFF:
        return None
    seconds = raw / 28125
    if seconds <= 0:
        return None
    denominator = round(1 / seconds)
    if denominator > 0 and abs(seconds - (1 / denominator)) < 0.0001:
        return f"1/{denominator}"
    return f"{seconds:g}"


def _mdpm_make(payload: bytes | None) -> str | None:
    if payload is None or len(payload) < 2:
        return None
    make_code = int.from_bytes(payload[:2], "big")
    return {0x0103: "Panasonic", 0x0108: "Sony", 0x1011: "Canon", 0x1104: "JVC"}.get(make_code)


def _preservation_action(unit: H264NalUnitPlan) -> H264PreservationPlan:
    return H264PreservationPlan(
        nal_index=unit.index,
        kind="annex_b_nal_unit",
        offset=unit.start_code.offset,
        end_offset=unit.end_offset,
        payload=unit.raw_bytes,
        reason="Preserve the exact Annex B NAL byte range.",
        evidence_ids=(H264_PARSE_SOURCE, H264_NON_MUTATING_SOURCE),
    )


def _responsibility_plans(
    *,
    nal_units: tuple[H264NalUnitPlan, ...],
    sps_plans: tuple[H264SpsPlan, ...],
    sei_messages: tuple[H264SeiMessagePlan, ...],
    preservation_actions: tuple[H264PreservationPlan, ...],
) -> tuple[H264ResponsibilityPlan, ...]:
    first_sps = sps_plans[0] if sps_plans else None
    mdpm_found = any(message.kind == "mdpm_user_data" for message in sei_messages)
    sei_found = any(unit.nal_unit_type == 6 for unit in nal_units)
    width_value = first_sps.image_width if first_sps is not None else None
    return (
        H264ResponsibilityPlan(
            "annex_b_nal_scan",
            bool(nal_units),
            len(nal_units),
            "ParseH264Video locates NAL units with 00 00 01 and 00 00 00 01 start codes.",
            (H264_PARSE_SOURCE,),
        ),
        H264ResponsibilityPlan(
            "sps_image_size",
            first_sps is not None and first_sps.status == "valid",
            width_value,
            "NAL type 7 is routed to SPS image-size discovery.",
            (H264_SPS_SOURCE, H264_MAIN_TABLE_SOURCE),
        ),
        H264ResponsibilityPlan(
            "sei_user_data",
            sei_found,
            "nal_type_6" if sei_found else None,
            "NAL type 6 is routed to SEI payload scanning.",
            (H264_PARSE_SOURCE, H264_SEI_SOURCE),
        ),
        H264ResponsibilityPlan(
            "mdpm_metadata",
            mdpm_found,
            "MDPM" if mdpm_found else None,
            "Only unregistered user data with the MDPM UUID and marker is modeled here.",
            (H264_SEI_SOURCE, H264_MDPM_TABLE_SOURCE),
        ),
        H264ResponsibilityPlan(
            "stream_preservation",
            len(preservation_actions) == len(nal_units),
            len(preservation_actions),
            "Every discovered Annex B NAL range is preserved byte-for-byte.",
            (H264_PARSE_SOURCE, H264_NON_MUTATING_SOURCE),
        ),
        H264ResponsibilityPlan(
            "rewrite_boundary",
            False,
            None,
            "H264.pm is a read extractor; this planner does not synthesize rewritten NAL bytes.",
            (H264_MAIN_TABLE_SOURCE, H264_NON_MUTATING_SOURCE),
        ),
    )


def _gate_for_nal_unit(unit: H264NalUnitPlan) -> H264OutputEmissionGate:
    code = unit.blocker_code or "empty_nal_unit"
    reason_by_code: dict[H264EmissionGateCode, str] = {
        "empty_nal_unit": "A start code was not followed by a NAL header byte.",
        "forbidden_zero_bit_set": "H264.pm warns and stops when the NAL forbidden bit is set.",
        "missing_annex_b_start_code": "No Annex B start code was found.",
        "truncated_sps_rbsp": "SPS RBSP ended before the image-size fields were readable.",
        "truncated_sei_message": "SEI payload type or size coding extended beyond available data.",
        "non_mutating_plan_requires_explicit_emission": "Byte emission was not explicitly allowed.",
        "h264_metadata_rewrite_not_supported": "Metadata rewrite is not implemented.",
        "h264_stream_rewrite_not_implemented": "Stream rewrite is not implemented.",
    }
    return H264OutputEmissionGate(code, reason_by_code[code], unit.evidence_ids)


def _gate_for_sps(plan: H264SpsPlan) -> H264OutputEmissionGate:
    return H264OutputEmissionGate(
        "truncated_sps_rbsp",
        "SPS RBSP ended before the image-size fields were readable.",
        plan.evidence_ids,
    )


def _gate_for_sei(message: H264SeiMessagePlan) -> H264OutputEmissionGate:
    return H264OutputEmissionGate(
        "truncated_sei_message",
        "SEI payload type or size coding extended beyond available data.",
        message.evidence_ids,
    )


def _has_rewrite_request(requested_metadata: H264MetadataRewriteRequest | None) -> bool:
    if requested_metadata is None:
        return False
    return (
        requested_metadata.image_width is not None
        or requested_metadata.image_height is not None
        or requested_metadata.mdpm_payload is not None
    )


def _has_structural_gate(gates: tuple[H264OutputEmissionGate, ...]) -> bool:
    structural_codes: set[H264EmissionGateCode] = {
        "missing_annex_b_start_code",
        "empty_nal_unit",
        "forbidden_zero_bit_set",
        "truncated_sps_rbsp",
        "truncated_sei_message",
    }
    return any(gate.code in structural_codes for gate in gates)


def _unique_gates(gates: tuple[H264OutputEmissionGate, ...]) -> tuple[H264OutputEmissionGate, ...]:
    seen: set[H264EmissionGateCode] = set()
    unique: list[H264OutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def _unique_evidence_ids(sources: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        unique.append(source)
    return tuple(unique)


class _BitReadError(ValueError):
    pass


@dataclass
class _BitReader:
    data: bytes
    bit_offset: int = 0

    def read_bits(self, bit_count: int) -> int:
        if self.bit_offset + bit_count > len(self.data) * 8:
            raise _BitReadError("not enough SPS bits")
        value = 0
        for _ in range(bit_count):
            byte_index = self.bit_offset // 8
            shift = 7 - (self.bit_offset % 8)
            value = (value << 1) | ((self.data[byte_index] >> shift) & 1)
            self.bit_offset += 1
        return value

    def read_unsigned_golomb(self) -> int:
        zero_count = 0
        while self.read_bits(1) == 0:
            zero_count += 1
        if zero_count == 0:
            return 0
        return (1 << zero_count) - 1 + self.read_bits(zero_count)

    def read_signed_golomb(self) -> int:
        value = self.read_unsigned_golomb() + 1
        if value & 1:
            return -(value >> 1)
        return value >> 1
