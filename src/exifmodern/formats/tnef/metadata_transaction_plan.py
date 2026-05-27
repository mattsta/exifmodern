"""Source-grounded, non-mutating TNEF metadata transaction planning."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat

TNEF_SIGNATURE = b"\x78\x9f\x3e\x22"
TNEF_HEADER_PROBE_SIZE = 0x15
TNEF_ATTRIBUTE_START = 6
TNEF_ATTRIBUTE_HEADER_SIZE = 9
TNEF_CHECKSUM_SIZE = 2
TNEF_VERSION_TAG = 0x089006
TNEF_ATTACH_START_TAG = 0x069002
TNEF_ATTACH_END_TAG = 0x069005

type TnefPlanStatus = Literal["planned", "unsupported"]
type TnefLevel = Literal["message", "attachment", "unknown"]
type TnefResponsibilityKind = Literal[
    "message_metadata",
    "attachment_metadata",
    "class_metadata",
    "name_metadata",
    "date_metadata",
    "mapi_property",
    "attachment_payload",
]
type TnefOutputGateCode = Literal[
    "truncated_tnef_header",
    "unsupported_tnef_signature",
    "truncated_attribute_header",
    "truncated_attribute_payload",
    "truncated_attribute_checksum",
    "attribute_checksum_mismatch",
    "truncated_mapi_property_directory",
    "truncated_mapi_property_header",
    "truncated_named_property_identity",
    "truncated_named_property_text",
    "unsupported_named_property_id_type",
    "truncated_mapi_multi_count",
    "unsupported_mapi_property_type",
    "truncated_mapi_property_value",
    "non_mutating_plan_requires_explicit_emission",
]
type TnefRewriteGateCode = Literal[
    "tnef_writer_not_implemented",
    "attribute_checksum_recalculation_required",
    "attachment_payload_preservation_required",
    "mapi_property_serialization_required",
]
type TnefPropertyFormat = Literal[
    "null",
    "int16s",
    "int32s",
    "float",
    "double",
    "int64s",
    "int64u",
    "string",
    "Unicode",
    "GUID",
    "undef",
]

TNEF_FORMAT_SOURCE = "tnef.format"
TNEF_MAIN_TABLE_SOURCE = "tnef.main_table"
TNEF_MSG_PROPS_SOURCE = "tnef.msg_props"
TNEF_ATTACH_PROPS_SOURCE = "tnef.attach_props"
TNEF_PROCESS_PROPS_SOURCE = "tnef.process_props"
TNEF_PROCESS_SOURCE = "tnef.process"
TNEF_NON_MUTATING_SOURCE = "tnef.non_mutating"

TNEF_TRANSACTION_SOURCES = (
    TNEF_FORMAT_SOURCE,
    TNEF_MAIN_TABLE_SOURCE,
    TNEF_MSG_PROPS_SOURCE,
    TNEF_ATTACH_PROPS_SOURCE,
    TNEF_PROCESS_PROPS_SOURCE,
    TNEF_PROCESS_SOURCE,
    TNEF_NON_MUTATING_SOURCE,
)

PROP_TYPES: dict[int, TnefPropertyFormat] = {
    0x01: "null",
    0x02: "int16s",
    0x03: "int32s",
    0x04: "float",
    0x05: "double",
    0x06: "int64s",
    0x07: "double",
    0x0A: "int32s",
    0x0B: "int16s",
    0x0D: "undef",
    0x14: "int64s",
    0x1E: "string",
    0x1F: "Unicode",
    0x40: "int64u",
    0x48: "GUID",
    0x102: "undef",
}
FIXED_SIZES: dict[TnefPropertyFormat, int] = {
    "null": 0,
    "float": 4,
    "double": 8,
    "GUID": 16,
}

MAIN_TAG_NAMES: dict[int, str] = {
    0x069007: "CodePage",
    TNEF_VERSION_TAG: "TNEFVersion",
    0x078008: "MessageClass",
    0x008000: "From",
    0x018004: "Subject",
    0x038005: "SentDate",
    0x038006: "ReceivedDate",
    0x068007: "MessageStatus",
    0x018009: "MessageID",
    0x02800C: "MessageBody",
    0x04800D: "Priority",
    0x038020: "MessageModifyDate",
    0x069003: "MessageProps",
    0x069004: "RecipientTable",
    0x070600: "OriginalMessageClass",
    0x060000: "Owner",
    0x060001: "SentFor",
    0x060002: "Delegate",
    0x030006: "StartDate",
    0x030007: "EndDate",
    0x050008: "OwnerAppointmentID",
    0x040009: "ResponseRequested",
    0x06800F: "AttachData",
    0x018010: "AttachTitle",
    0x068011: "AttachMetaFile",
    0x038012: "AttachCreateDate",
    0x038013: "AttachModifyDate",
    0x069001: "AttachTransportFilename",
    TNEF_ATTACH_START_TAG: "AttachRenderingData",
    TNEF_ATTACH_END_TAG: "AttachInfo",
}
DATE_TAGS = frozenset((0x038005, 0x038006, 0x038020, 0x030006, 0x030007, 0x038012, 0x038013))
CLASS_TAGS = frozenset((0x078008, 0x070600))
NAME_TAGS = frozenset(
    (0x008000, 0x018004, 0x018009, 0x060000, 0x060001, 0x060002, 0x018010, 0x069001)
)
ATTACHMENT_PAYLOAD_TAGS = frozenset((0x06800F, 0x068011, TNEF_ATTACH_START_TAG))
MAPI_ATTRIBUTE_TAGS = frozenset((0x069003, TNEF_ATTACH_END_TAG))

MESSAGE_PROP_NAMES: dict[int, str] = {
    0x0002: "AlternateRecipientAllowed",
    0x0039: "ClientSubmitTime",
    0x0040: "ReceivedByName",
    0x0044: "ReceivedRepresentingName",
    0x004D: "OriginalAuthorName",
    0x0055: "OriginalDeliveryTime",
    0x0070: "Subject",
    0x0075: "ReceivedByAddressType",
    0x0076: "ReceivedByEmailAddress",
    0x0077: "ReceivedRepresentingAddressType",
    0x0078: "ReceivedRepresentingEmailAddress",
    0x007F: "CorrelationKey",
    0x0C1A: "SenderName",
    0x0C1D: "SenderSearchKey",
    0x0E06: "MessageDeliveryTime",
    0x0E1D: "NormalizedSubject",
    0x0E28: "PrimarySendAccount",
    0x0E29: "NextSendAccount",
    0x0F02: "DeliveryOrRenewTime",
    0x1000: "MessageBodyText",
    0x1007: "SyncBodyCount",
    0x1008: "SyncBodyData",
    0x1009: "MessageBodyRTF",
    0x1013: "MessageBodyHTML",
    0x1035: "InternetMessageID",
    0x10F4: "Hidden",
    0x10F6: "ReadOnly",
    0x3007: "CreateDate",
    0x3008: "ModifyDate",
    0x3FDE: "InternetCodePage",
    0x3FF1: "LocalUserID",
    0x3FF8: "CreatorName",
    0x3FFA: "LastModifierName",
    0x3FFD: "MessageCodePage",
    0x4076: "SpamConfidenceLevel",
}
ATTACH_PROP_NAMES: dict[int, str] = {
    0x0E20: "AttachSize",
    0x0E21: "AttachNum",
    0x0FF8: "MappingSignature",
    0x3001: "AttachFileName",
    0x3703: "AttachFileExtension",
    0x3701: "AttachBinary",
    0x3705: "AttachMethod",
    0x3707: "AttachLongFileName",
    0x3708: "AttachPathName",
    0x370D: "AttachLongPathName",
    0x370E: "AttachMIMEType",
    0x7FFB: "ExceptionStartTime",
    0x7FFC: "ExceptionEndTime",
}


@dataclass(frozen=True)
class TnefSignaturePlan:
    is_valid: bool
    signature: bytes
    header_probe_range: tuple[int, int]
    attribute_scan_start: int
    reason: TnefOutputGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TnefAttributePlan:
    index: int
    level: TnefLevel
    raw_level: int
    tag_id: int
    tag_name: str
    length: int
    attribute_range: tuple[int, int]
    payload_range: tuple[int, int]
    checksum_range: tuple[int, int]
    checksum_expected: int
    checksum_calculated: int
    checksum_valid: bool
    attachment_index: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TnefMapiPropertyPlan:
    table_kind: TnefLevel
    attribute_index: int
    property_index: int
    tag_id: int | None
    tag_key: str
    tag_name: str
    property_type: int
    value_format: TnefPropertyFormat
    is_multi_value: bool
    value_count: int
    value_range: tuple[int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TnefMetadataResponsibility:
    kind: TnefResponsibilityKind
    attribute_index: int
    tag_name: str
    byte_range: tuple[int, int]
    attachment_index: int | None
    property_key: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TnefAttachmentPayloadPlan:
    attribute_index: int
    tag_name: str
    payload_range: tuple[int, int]
    attachment_index: int | None
    checksum_range: tuple[int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TnefOutputEmissionGate:
    code: TnefOutputGateCode
    reason: str
    byte_range: tuple[int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TnefRewriteGate:
    code: TnefRewriteGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TnefMetadataTransactionPlan:
    status: TnefPlanStatus
    source: bytes
    signature: TnefSignaturePlan
    attributes: tuple[TnefAttributePlan, ...]
    mapi_properties: tuple[TnefMapiPropertyPlan, ...]
    responsibilities: tuple[TnefMetadataResponsibility, ...]
    attachment_payloads: tuple[TnefAttachmentPayloadPlan, ...]
    rewrite_gates: tuple[TnefRewriteGate, ...]
    output_emission_gates: tuple[TnefOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"TNEF output emission blocked by: {gate_codes}")
        return self.source


def build_tnef_metadata_transaction_plan(
    source: bytes,
    *,
    allow_output_emission: bool = False,
) -> TnefMetadataTransactionPlan:
    gates: list[TnefOutputEmissionGate] = []
    signature = _signature_plan(source, gates)
    if not signature.is_valid:
        return _finish_plan(source, signature, (), (), (), (), gates, allow_output_emission)

    attributes: list[TnefAttributePlan] = []
    properties: list[TnefMapiPropertyPlan] = []
    responsibilities: list[TnefMetadataResponsibility] = []
    attachment_payloads: list[TnefAttachmentPayloadPlan] = []
    position = TNEF_ATTRIBUTE_START
    attribute_index = 0
    attachment_index: int | None = None
    next_attachment_index = 0

    while position < len(source):
        if position + TNEF_ATTRIBUTE_HEADER_SIZE > len(source):
            gates.append(
                _gate(
                    "truncated_attribute_header",
                    "Attribute header is short.",
                    (position, len(source)),
                    (TNEF_PROCESS_SOURCE,),
                )
            )
            break
        raw_level = source[position]
        tag_id = int.from_bytes(source[position + 1 : position + 5], "little")
        length = int.from_bytes(source[position + 5 : position + 9], "little")
        payload_start = position + TNEF_ATTRIBUTE_HEADER_SIZE
        payload_end = payload_start + length
        if payload_end > len(source):
            gates.append(
                _gate(
                    "truncated_attribute_payload",
                    "Attribute payload length exceeds available bytes.",
                    (payload_start, len(source)),
                    (TNEF_PROCESS_SOURCE,),
                )
            )
            break
        checksum_start = payload_end
        checksum_end = checksum_start + TNEF_CHECKSUM_SIZE
        if checksum_end > len(source):
            gates.append(
                _gate(
                    "truncated_attribute_checksum",
                    "Attribute checksum bytes are missing.",
                    (checksum_start, len(source)),
                    (TNEF_PROCESS_SOURCE,),
                )
            )
            break
        if tag_id == TNEF_ATTACH_START_TAG:
            next_attachment_index += 1
            attachment_index = next_attachment_index
        payload = source[payload_start:payload_end]
        checksum_expected = int.from_bytes(source[checksum_start:checksum_end], "little")
        checksum_calculated = sum(payload) & 0xFFFF
        attribute = TnefAttributePlan(
            index=attribute_index,
            level=_level(raw_level),
            raw_level=raw_level,
            tag_id=tag_id,
            tag_name=MAIN_TAG_NAMES.get(tag_id, _hex_tag(tag_id, 6)),
            length=length,
            attribute_range=(position, checksum_end),
            payload_range=(payload_start, payload_end),
            checksum_range=(checksum_start, checksum_end),
            checksum_expected=checksum_expected,
            checksum_calculated=checksum_calculated,
            checksum_valid=checksum_expected == checksum_calculated,
            attachment_index=attachment_index,
            evidence_ids=(TNEF_MAIN_TABLE_SOURCE, TNEF_PROCESS_SOURCE),
        )
        attributes.append(attribute)
        if not attribute.checksum_valid:
            gates.append(
                _gate(
                    "attribute_checksum_mismatch",
                    "Attribute checksum does not match payload bytes.",
                    (checksum_start, checksum_end),
                    (TNEF_PROCESS_SOURCE,),
                )
            )
        responsibilities.extend(_attribute_responsibilities(attribute))
        if tag_id in ATTACHMENT_PAYLOAD_TAGS:
            attachment_payloads.append(
                TnefAttachmentPayloadPlan(
                    attribute.index,
                    attribute.tag_name,
                    attribute.payload_range,
                    attribute.attachment_index,
                    attribute.checksum_range,
                    (TNEF_MAIN_TABLE_SOURCE, TNEF_PROCESS_SOURCE),
                )
            )
        if tag_id in MAPI_ATTRIBUTE_TAGS:
            parsed = _parse_mapi_properties(attribute, source, gates)
            properties.extend(parsed)
            responsibilities.extend(_mapi_responsibilities(parsed))
        position = checksum_end
        attribute_index += 1
        if tag_id == TNEF_ATTACH_END_TAG:
            attachment_index = None

    return _finish_plan(
        source,
        signature,
        tuple(attributes),
        tuple(properties),
        tuple(responsibilities),
        tuple(attachment_payloads),
        gates,
        allow_output_emission,
    )


plan_tnef_metadata_transaction = build_tnef_metadata_transaction_plan


def _signature_plan(source: bytes, gates: list[TnefOutputEmissionGate]) -> TnefSignaturePlan:
    probe_end = min(len(source), TNEF_HEADER_PROBE_SIZE)
    if len(source) < TNEF_HEADER_PROBE_SIZE:
        gates.append(
            _gate(
                "truncated_tnef_header",
                "TNEF header probe is shorter than ExifTool requires.",
                (0, len(source)),
                (TNEF_PROCESS_SOURCE,),
            )
        )
        return TnefSignaturePlan(
            False,
            source[:4],
            (0, probe_end),
            TNEF_ATTRIBUTE_START,
            "truncated_tnef_header",
            (TNEF_PROCESS_SOURCE,),
        )
    is_valid = (
        source.startswith(TNEF_SIGNATURE)
        and source[TNEF_ATTRIBUTE_START : TNEF_ATTRIBUTE_START + 5] == b"\x01\x06\x90\x08\x00"
    )
    if not is_valid:
        gates.append(
            _gate(
                "unsupported_tnef_signature",
                "TNEF signature or required version marker is absent.",
                (0, TNEF_HEADER_PROBE_SIZE),
                (TNEF_PROCESS_SOURCE,),
            )
        )
    return TnefSignaturePlan(
        is_valid,
        source[:4],
        (0, TNEF_HEADER_PROBE_SIZE),
        TNEF_ATTRIBUTE_START,
        None if is_valid else "unsupported_tnef_signature",
        (TNEF_PROCESS_SOURCE,),
    )


def _parse_mapi_properties(
    attribute: TnefAttributePlan,
    source: bytes,
    gates: list[TnefOutputEmissionGate],
) -> tuple[TnefMapiPropertyPlan, ...]:
    start, end = attribute.payload_range
    data = source[start:end]
    if len(data) <= 4:
        gates.append(
            _gate(
                "truncated_mapi_property_directory",
                "MAPI directory is shorter than the entry count guard.",
                attribute.payload_range,
                (TNEF_PROCESS_PROPS_SOURCE,),
            )
        )
        return ()
    properties: list[TnefMapiPropertyPlan] = []
    entry_count = int.from_bytes(data[:4], "little")
    position = 4
    table_kind: TnefLevel = "attachment" if attribute.tag_id == TNEF_ATTACH_END_TAG else "message"
    names = ATTACH_PROP_NAMES if table_kind == "attachment" else MESSAGE_PROP_NAMES
    table_source = TNEF_ATTACH_PROPS_SOURCE if table_kind == "attachment" else TNEF_MSG_PROPS_SOURCE
    for property_index in range(entry_count):
        if position + 4 > len(data):
            gates.append(
                _gate(
                    "truncated_mapi_property_header",
                    "MAPI property header ended before type and tag fields.",
                    (start + position, end),
                    (TNEF_PROCESS_PROPS_SOURCE,),
                )
            )
            break
        raw_type = int.from_bytes(data[position : position + 2], "little")
        tag_id = int.from_bytes(data[position + 2 : position + 4], "little")
        tag_key = _hex_tag(tag_id, 4)
        position += 4
        if tag_id & 0x8000:
            named = _read_named_property_key(data, start, end, position, gates)
            if named is None:
                break
            tag_key, position = named
            numeric_tag: int | None = None
        else:
            numeric_tag = tag_id
        is_multi = bool(raw_type & 0x1000)
        property_type = raw_type & 0x0FFF if is_multi else raw_type
        value_count = 1
        if is_multi:
            if position + 4 > len(data):
                gates.append(
                    _gate(
                        "truncated_mapi_multi_count",
                        "MAPI multi-value property lacks its value count.",
                        (start + position, end),
                        (TNEF_PROCESS_PROPS_SOURCE,),
                    )
                )
                break
            value_count = int.from_bytes(data[position : position + 4], "little")
            position += 4
        value_format = PROP_TYPES.get(property_type)
        if value_format is None:
            gates.append(
                _gate(
                    "unsupported_mapi_property_type",
                    "MAPI property type is absent from ExifTool's TNEF type map.",
                    (start + position - 4, start + position),
                    (TNEF_FORMAT_SOURCE, TNEF_PROCESS_PROPS_SOURCE),
                )
            )
            break
        entries, position = _read_property_values(
            data=data,
            base_start=start,
            directory_end=end,
            position=position,
            table_kind=table_kind,
            attribute_index=attribute.index,
            property_index=property_index,
            tag_id=numeric_tag,
            tag_key=tag_key,
            tag_name=names.get(numeric_tag or -1, tag_key),
            property_type=property_type,
            value_format=value_format,
            is_multi=is_multi,
            value_count=value_count,
            sources=(TNEF_PROCESS_PROPS_SOURCE, table_source),
            gates=gates,
        )
        properties.extend(entries)
        if len(entries) == 0 and any(gate.byte_range[0] >= start for gate in gates):
            break
    return tuple(properties)


def _read_named_property_key(
    data: bytes,
    base_start: int,
    directory_end: int,
    position: int,
    gates: list[TnefOutputEmissionGate],
) -> tuple[str, int] | None:
    if position + 24 > len(data):
        gates.append(
            _gate(
                "truncated_named_property_identity",
                "Named MAPI property identity ended before GUID and identifier fields.",
                (base_start + position, directory_end),
                (TNEF_PROCESS_PROPS_SOURCE,),
            )
        )
        return None
    guid = _guid_text(data[position : position + 16]).removesuffix("-0000-0000-c000-000000000046")
    identity_kind = int.from_bytes(data[position + 16 : position + 20], "little")
    identity_value = int.from_bytes(data[position + 20 : position + 24], "little")
    position += 24
    if identity_kind == 0:
        return f"{guid}_{identity_value:08x}", position
    if identity_kind == 1:
        if position + identity_value > len(data) or identity_value < 2:
            gates.append(
                _gate(
                    "truncated_named_property_text",
                    "Named MAPI property text ended before its declared UTF-16 bytes.",
                    (base_start + position, directory_end),
                    (TNEF_PROCESS_PROPS_SOURCE,),
                )
            )
            return None
        name = data[position : position + identity_value - 2].decode("utf-16-le", "replace")
        return f"{guid}_{name}", position + _padded_size(identity_value)
    gates.append(
        _gate(
            "unsupported_named_property_id_type",
            "Named MAPI property identifier kind is not number or string.",
            (base_start + position - 8, base_start + position),
            (TNEF_PROCESS_PROPS_SOURCE,),
        )
    )
    return None


def _read_property_values(
    *,
    data: bytes,
    base_start: int,
    directory_end: int,
    position: int,
    table_kind: TnefLevel,
    attribute_index: int,
    property_index: int,
    tag_id: int | None,
    tag_key: str,
    tag_name: str,
    property_type: int,
    value_format: TnefPropertyFormat,
    is_multi: bool,
    value_count: int,
    sources: tuple[str, ...],
    gates: list[TnefOutputEmissionGate],
) -> tuple[tuple[TnefMapiPropertyPlan, ...], int]:
    fixed_size = _fixed_value_size(value_format, value_count)
    if fixed_size is not None:
        if position + fixed_size > len(data):
            gates.append(_truncated_value_gate(base_start, directory_end, position, sources))
            return (), position
        return (
            (
                TnefMapiPropertyPlan(
                    table_kind,
                    attribute_index,
                    property_index,
                    tag_id,
                    tag_key,
                    tag_name,
                    property_type,
                    value_format,
                    is_multi,
                    value_count,
                    (base_start + position, base_start + position + fixed_size),
                    sources,
                ),
            ),
            position + _padded_size(fixed_size),
        )

    properties: list[TnefMapiPropertyPlan] = []
    remaining = value_count
    while remaining > 0:
        if not is_multi:
            position += 4
        if position + 4 > len(data):
            gates.append(
                _truncated_value_gate(base_start, directory_end, min(position, len(data)), sources)
            )
            return tuple(properties), position
        value_size = int.from_bytes(data[position : position + 4], "little")
        position += 4
        if position + value_size > len(data):
            gates.append(_truncated_value_gate(base_start, directory_end, position, sources))
            return tuple(properties), position
        properties.append(
            TnefMapiPropertyPlan(
                table_kind,
                attribute_index,
                property_index,
                tag_id,
                tag_key,
                tag_name,
                property_type,
                value_format,
                is_multi,
                value_count,
                (base_start + position, base_start + position + value_size),
                sources,
            )
        )
        position += _padded_size(value_size)
        remaining -= 1
    return tuple(properties), position


def _fixed_value_size(value_format: TnefPropertyFormat, value_count: int) -> int | None:
    fixed = FIXED_SIZES.get(value_format)
    if fixed is not None:
        return fixed * value_count
    if value_format == "int16s":
        return 2 * value_count
    if value_format == "int32s":
        return 4 * value_count
    if value_format in {"int64s", "int64u"}:
        return 8 * value_count
    return None


def _attribute_responsibilities(
    attribute: TnefAttributePlan,
) -> tuple[TnefMetadataResponsibility, ...]:
    kinds: list[TnefResponsibilityKind] = []
    if attribute.level == "attachment":
        kinds.append("attachment_metadata")
    else:
        kinds.append("message_metadata")
    if attribute.tag_id in CLASS_TAGS:
        kinds.append("class_metadata")
    if attribute.tag_id in NAME_TAGS:
        kinds.append("name_metadata")
    if attribute.tag_id in DATE_TAGS:
        kinds.append("date_metadata")
    if attribute.tag_id in ATTACHMENT_PAYLOAD_TAGS:
        kinds.append("attachment_payload")
    return tuple(
        TnefMetadataResponsibility(
            kind,
            attribute.index,
            attribute.tag_name,
            attribute.payload_range,
            attribute.attachment_index,
            None,
            (TNEF_MAIN_TABLE_SOURCE, TNEF_PROCESS_SOURCE),
        )
        for kind in kinds
    )


def _mapi_responsibilities(
    properties: Iterable[TnefMapiPropertyPlan],
) -> tuple[TnefMetadataResponsibility, ...]:
    return tuple(
        TnefMetadataResponsibility(
            "mapi_property",
            prop.attribute_index,
            prop.tag_name,
            prop.value_range,
            None,
            prop.tag_key,
            prop.evidence_ids,
        )
        for prop in properties
    )


def _finish_plan(
    source: bytes,
    signature: TnefSignaturePlan,
    attributes: tuple[TnefAttributePlan, ...],
    mapi_properties: tuple[TnefMapiPropertyPlan, ...],
    responsibilities: tuple[TnefMetadataResponsibility, ...],
    attachment_payloads: tuple[TnefAttachmentPayloadPlan, ...],
    gates: list[TnefOutputEmissionGate],
    allow_output_emission: bool,
) -> TnefMetadataTransactionPlan:
    if not allow_output_emission:
        gates.append(
            _gate(
                "non_mutating_plan_requires_explicit_emission",
                "TNEF transaction plans preserve bytes unless output emission is explicit.",
                (0, len(source)),
                (TNEF_NON_MUTATING_SOURCE,),
            )
        )
    status: TnefPlanStatus = "unsupported" if _has_structural_gate(gates) else "planned"
    return TnefMetadataTransactionPlan(
        status,
        source,
        signature,
        attributes,
        mapi_properties,
        responsibilities,
        attachment_payloads,
        _rewrite_gates(attachment_payloads, mapi_properties),
        _unique_gates(tuple(gates)),
        _unique_sources(TNEF_TRANSACTION_SOURCES),
    )


def _rewrite_gates(
    attachment_payloads: tuple[TnefAttachmentPayloadPlan, ...],
    mapi_properties: tuple[TnefMapiPropertyPlan, ...],
) -> tuple[TnefRewriteGate, ...]:
    gates = [
        TnefRewriteGate(
            "tnef_writer_not_implemented",
            "ExifTool TNEF.pm is a reader; this planner has no TNEF writer.",
            (TNEF_PROCESS_SOURCE, TNEF_NON_MUTATING_SOURCE),
        ),
        TnefRewriteGate(
            "attribute_checksum_recalculation_required",
            "Changing attribute bytes requires checksum recalculation.",
            (TNEF_PROCESS_SOURCE,),
        ),
    ]
    if attachment_payloads:
        gates.append(
            TnefRewriteGate(
                "attachment_payload_preservation_required",
                "Attachment payload attributes must be preserved byte-for-byte.",
                (TNEF_MAIN_TABLE_SOURCE, TNEF_PROCESS_SOURCE),
            )
        )
    if mapi_properties:
        gates.append(
            TnefRewriteGate(
                "mapi_property_serialization_required",
                "MAPI property directories require ExifTool-compatible padding.",
                (TNEF_PROCESS_PROPS_SOURCE,),
            )
        )
    return tuple(gates)


def _level(raw_level: int) -> TnefLevel:
    if raw_level == 1:
        return "message"
    if raw_level == 2:
        return "attachment"
    return "unknown"


def _hex_tag(tag_id: int, width: int) -> str:
    return f"0x{tag_id:0{width}X}"


def _padded_size(size: int) -> int:
    return (size + 3) & 0xFFFFFFFC


def _guid_text(data: bytes) -> str:
    return (
        f"{int.from_bytes(data[0:4], 'little'):08x}-"
        f"{int.from_bytes(data[4:6], 'little'):04x}-"
        f"{int.from_bytes(data[6:8], 'little'):04x}-"
        f"{data[8:10].hex()}-{data[10:16].hex()}"
    )


def _truncated_value_gate(
    base_start: int,
    directory_end: int,
    position: int,
    sources: tuple[str, ...],
) -> TnefOutputEmissionGate:
    return _gate(
        "truncated_mapi_property_value",
        "MAPI property value ended before its declared bytes.",
        (base_start + position, directory_end),
        sources,
    )


def _gate(
    code: TnefOutputGateCode,
    reason: str,
    byte_range: tuple[int, int],
    sources: tuple[str, ...],
) -> TnefOutputEmissionGate:
    return TnefOutputEmissionGate(code, reason, byte_range, sources)


def _has_structural_gate(gates: Iterable[TnefOutputEmissionGate]) -> bool:
    return any(gate.code != "non_mutating_plan_requires_explicit_emission" for gate in gates)


def _unique_gates(gates: tuple[TnefOutputEmissionGate, ...]) -> tuple[TnefOutputEmissionGate, ...]:
    unique: list[TnefOutputEmissionGate] = []
    seen: set[tuple[TnefOutputGateCode, tuple[int, int]]] = set()
    for gate in gates:
        key = (gate.code, gate.byte_range)
        if key not in seen:
            seen.add(key)
            unique.append(gate)
    return tuple(unique)


def _unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if reference not in seen:
            seen.add(reference)
            unique.append(reference)
    return tuple(unique)


install_evidence_reference_compat(globals())
