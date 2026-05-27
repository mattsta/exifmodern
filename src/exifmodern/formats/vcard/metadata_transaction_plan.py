"""Source-backed, preserving vCard metadata transaction plans."""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Literal

type VCardPlanStatus = Literal["planned", "blocked", "unsupported"]
type VCardContainerKind = Literal["vcard", "vcalendar", "vnote", "unknown"]
type VCardLineAction = Literal["boundary", "property", "malformed"]
type VCardValueKind = Literal["binary", "list", "text"]
type VCardRewriteAction = Literal["set", "delete"]
type VCardEvidenceId = str
type VCardEmissionGateCode = Literal[
    "unsupported_signature",
    "unsupported_container",
    "missing_vcard_end",
    "malformed_property_name",
    "invalid_property_line",
    "requested_rewrite_not_supported",
    "output_emission_requires_explicit_opt_in",
]
type VCardRewriteBlockerCode = Literal[
    "vcard_writer_not_defined",
    "raw_line_layout_preservation_required",
    "charset_parameter_is_not_a_write_contract",
    "encoding_parameter_is_decode_only",
]

VCARD_TABLE_SOURCE = "vcard.main_table"
VCALENDAR_TABLE_SOURCE = "vcard.vcalendar_table"
VCALENDAR_COMPONENT_SOURCE = "vcard.vcalendar_components"
VCARD_DYNAMIC_TAG_SOURCE = "vcard.dynamic_tag"
VCARD_DECODE_SOURCE = "vcard.decode_text"
VCARD_SIGNATURE_SOURCE = "vcard.signature"
VCARD_UNFOLD_SOURCE = "vcard.unfold"
VCARD_BOUNDARY_SOURCE = "vcard.boundary"
VCARD_PROPERTY_SOURCE = "vcard.property"
VCARD_PARAM_SOURCE = "vcard.parameter"
VCARD_DATA_URI_SOURCE = "vcard.data_uri"
VCARD_PARAM_TAG_SOURCE = "vcard.parameter_tag"
VCARD_END_SOURCE = "vcard.end"

VCARD_TRANSACTION_SOURCES = (
    VCARD_TABLE_SOURCE,
    VCALENDAR_TABLE_SOURCE,
    VCALENDAR_COMPONENT_SOURCE,
    VCARD_DYNAMIC_TAG_SOURCE,
    VCARD_DECODE_SOURCE,
    VCARD_SIGNATURE_SOURCE,
    VCARD_UNFOLD_SOURCE,
    VCARD_BOUNDARY_SOURCE,
    VCARD_PROPERTY_SOURCE,
    VCARD_PARAM_SOURCE,
    VCARD_DATA_URI_SOURCE,
    VCARD_PARAM_TAG_SOURCE,
    VCARD_END_SOURCE,
)

KNOWN_VCARD_TAGS: dict[str, tuple[str, str | None]] = {
    "Version": ("VCardVersion", None),
    "Fn": ("FormattedName", "Author"),
    "N": ("Name", "Author"),
    "Bday": ("Birthday", "Time"),
    "Tz": ("TimeZone", "Time"),
    "Adr": ("Address", "Location"),
    "Geo": ("Geolocation", "Location"),
    "Email": ("Email", None),
    "Impp": ("IMPP", None),
    "Lang": ("Language", None),
    "Org": ("Organization", None),
    "Photo": ("Photo", "Preview"),
    "Prodid": ("Software", None),
    "Rev": ("Revision", None),
    "Tel": ("Telephone", None),
    "Title": ("JobTitle", None),
    "Uid": ("UID", None),
    "Url": ("URL", None),
    "X-ablabel": ("ABLabel", None),
    "X-abdate": ("ABDate", "Time"),
    "X-aim": ("AIM", None),
    "X-icq": ("ICQ", None),
    "X-abuid": ("AB_UID", None),
    "X-abrelatednames": ("ABRelatedNames", None),
    "X-socialprofile": ("SocialProfile", None),
}

KNOWN_VCALENDAR_TAGS: dict[str, tuple[str, str | None]] = {
    "Version": ("VCalendarVersion", None),
    "Calscale": ("CalendarScale", None),
    "Method": ("Method", None),
    "Prodid": ("Software", None),
    "Attach": ("Attachment", None),
    "Categories": ("Categories", None),
    "Class": ("Classification", None),
    "Comment": ("Comment", None),
    "Description": ("Description", None),
    "Geo": ("Geolocation", "Location"),
    "Location": ("Location", "Location"),
    "Percent-complete": ("PercentComplete", None),
    "Priority": ("Priority", None),
    "Resources": ("Resources", None),
    "Status": ("Status", None),
    "Summary": ("Summary", None),
    "Completed": ("DateTimeCompleted", "Time"),
    "Dtend": ("DateTimeEnd", "Time"),
    "Due": ("DateTimeDue", "Time"),
    "Dtstart": ("DateTimeStart", "Time"),
    "Duration": ("Duration", None),
    "Freebusy": ("FreeBusyTime", None),
    "Transp": ("TimeTransparency", None),
    "Tzid": ("TimezoneID", "Time"),
    "Tzname": ("TimezoneName", "Time"),
    "Tzoffsetfrom": ("TimezoneOffsetFrom", "Time"),
    "Tzoffsetto": ("TimezoneOffsetTo", "Time"),
    "Tzurl": ("TimeZoneURL", "Time"),
    "Attendee": ("Attendee", None),
    "Contact": ("Contact", None),
    "Organizer": ("Organizer", None),
    "Recurrence-id": ("RecurrenceID", None),
    "Related-to": ("RelatedTo", None),
    "Url": ("URL", None),
    "Uid": ("UID", None),
    "Exdate": ("ExceptionDateTimes", "Time"),
    "Rdate": ("RecurrenceDateTimes", "Time"),
    "Rrule": ("RecurrenceRule", "Time"),
    "Action": ("Action", None),
    "Repeat": ("Repeat", None),
    "Trigger": ("Trigger", None),
    "Created": ("DateCreated", "Time"),
    "Dtstamp": ("DateTimeStamp", "Time"),
    "Last-modified": ("ModifyDate", "Time"),
    "Sequence": ("SequenceNumber", None),
    "Request-status": ("RequestStatus", None),
    "Acknowledged": ("Acknowledged", "Time"),
    "X-apple-calendar-color": ("CalendarColor", None),
    "X-apple-default-alarm": ("DefaultAlarm", None),
    "X-apple-local-default-alarm": ("LocalDefaultAlarm", None),
    "X-wr-caldesc": ("CalendarDescription", None),
    "X-wr-calname": ("CalendarName", None),
    "X-wr-relcalid": ("CalendarID", None),
    "X-wr-timezone": ("TimeZone2", "Time"),
    "X-wr-alarmuid": ("AlarmUID", None),
}

VCALENDAR_TIME_TAGS = frozenset(
    tag for tag, (_display, group) in KNOWN_VCALENDAR_TAGS.items() if group == "Time"
)
VCALENDAR_COMPONENTS = frozenset({"Event", "Todo", "Journal", "Freebusy", "Timezone", "Alarm"})

PARAM_TAGS: dict[str, tuple[str, str | None]] = {
    "Geo": ("Geolocation", "Location"),
    "Label": ("Label", None),
    "Tzid": ("Tzid", None),
}

UNESCAPE_VCARD = {"\\": "\\", ",": ",", "n": "\n", "N": "\n"}


@dataclass(frozen=True)
class VCardRewriteRequest:
    action: VCardRewriteAction
    tag: str
    value: str | bytes | None = None


@dataclass(frozen=True)
class VCardEmissionGate:
    code: VCardEmissionGateCode
    reason: str
    evidence_ids: tuple[VCardEvidenceId, ...]


@dataclass(frozen=True)
class VCardRewriteBlocker:
    code: VCardRewriteBlockerCode
    reason: str
    evidence_ids: tuple[VCardEvidenceId, ...]


@dataclass(frozen=True)
class VCardSignaturePlan:
    accepted: bool
    kind: VCardContainerKind
    first_line: str | None
    sniffed_length: int
    requires_crlf: bool
    evidence_ids: tuple[VCardEvidenceId, ...]


@dataclass(frozen=True)
class VCardRawBoundaryPlan:
    raw_source_length: int
    first_line_end: int | None
    complete_crlf_line_count: int
    trailing_bytes: bytes
    evidence_ids: tuple[VCardEvidenceId, ...]


@dataclass(frozen=True)
class VCardLogicalLinePlan:
    index: int
    action: VCardLineAction
    raw_line_ranges: tuple[tuple[int, int], ...]
    unfolded_text: str
    continuation_count: int
    evidence_ids: tuple[VCardEvidenceId, ...]


@dataclass(frozen=True)
class VCardParameterPlan:
    name: str
    normalized_name: str
    raw_value: str
    value: str
    legacy_type_parameter: bool
    evidence_ids: tuple[VCardEvidenceId, ...]


@dataclass(frozen=True)
class VCardValuePlan:
    kind: VCardValueKind
    raw_value: str
    display_values: tuple[str, ...]
    binary_value: bytes | None
    encoding: str | None
    charset_parameter: str | None
    data_uri_media_suffix: str | None
    evidence_ids: tuple[VCardEvidenceId, ...]


@dataclass(frozen=True)
class VCardPropertyPlan:
    line_index: int
    raw_property_name: str
    group: str | None
    normalized_tag: str
    routed_tag: str
    display_name: str
    family2_group: str | None
    family1_group: str | None
    known_table_tag: bool
    type_suffix: str | None
    language: str | None
    parameters: tuple[VCardParameterPlan, ...]
    value: VCardValuePlan
    evidence_ids: tuple[VCardEvidenceId, ...]


@dataclass(frozen=True)
class VCardParameterTagPlan:
    property_line_index: int
    parameter_name: str
    routed_tag: str
    display_name: str
    values: tuple[str, ...]
    evidence_ids: tuple[VCardEvidenceId, ...]


@dataclass(frozen=True)
class VCardMetadataTransactionPlan:
    status: VCardPlanStatus
    signature: VCardSignaturePlan
    raw_boundaries: VCardRawBoundaryPlan
    logical_lines: tuple[VCardLogicalLinePlan, ...]
    properties: tuple[VCardPropertyPlan, ...]
    parameter_tags: tuple[VCardParameterTagPlan, ...]
    rewrite_request: VCardRewriteRequest | None
    rewrite_blockers: tuple[VCardRewriteBlocker, ...]
    output_emission_gates: tuple[VCardEmissionGate, ...]
    output_bytes: bytes | None
    evidence_ids: tuple[VCardEvidenceId, ...] = VCARD_TRANSACTION_SOURCES

    @property
    def can_emit_output(self) -> bool:
        return (
            self.status == "planned"
            and not self.output_emission_gates
            and self.output_bytes is not None
        )

    @property
    def routed_tag_names(self) -> tuple[str, ...]:
        primary = [property_plan.routed_tag for property_plan in self.properties]
        primary.extend(parameter_tag.routed_tag for parameter_tag in self.parameter_tags)
        return tuple(primary)

    def emit(self) -> bytes:
        if not self.can_emit_output or self.output_bytes is None:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"vCard metadata transaction output is gated: {gate_codes}")
        return self.output_bytes


@dataclass(frozen=True)
class _ParsedParameter:
    parameter: VCardParameterPlan
    next_offset: int


@dataclass(frozen=True)
class _PropertyParse:
    property_plan: VCardPropertyPlan | None
    parameter_tags: tuple[VCardParameterTagPlan, ...]
    gate: VCardEmissionGate | None


@dataclass(frozen=True)
class _BoundaryParts:
    begin: bool
    v_prefix: bool
    what: str


def build_vcard_metadata_transaction_plan(
    data: bytes,
    *,
    allow_output_emission: bool = False,
    rewrite_request: VCardRewriteRequest | None = None,
) -> VCardMetadataTransactionPlan:
    signature = _sniff_signature(data)
    raw_boundaries = _raw_boundaries(data)
    gates: list[VCardEmissionGate] = []
    if not signature.accepted:
        gates.append(
            VCardEmissionGate(
                code="unsupported_signature",
                reason="Initial bytes do not match the VCard.pm BEGIN line and CRLF check.",
                evidence_ids=(VCARD_SIGNATURE_SOURCE,),
            )
        )
    elif signature.kind == "vnote":
        gates.append(
            VCardEmissionGate(
                code="unsupported_container",
                reason="This package-local planner models VCARD and VCALENDAR, not VNOTE.",
                evidence_ids=(VCARD_SIGNATURE_SOURCE,),
            )
        )

    logical_lines = _unfold_lines(data)
    properties: list[VCardPropertyPlan] = []
    parameter_tags: list[VCardParameterTagPlan] = []
    saw_document_end = False
    if signature.kind in {"vcard", "vcalendar"}:
        calendar_state = _CalendarComponentState()
        for line in logical_lines:
            boundary = _boundary_parts(line.unfolded_text)
            if boundary is not None:
                if _is_document_end(boundary, signature.kind):
                    saw_document_end = True
                if signature.kind == "vcalendar":
                    calendar_state.update(boundary)
                continue
            parsed = _parse_property_line(
                line,
                container_kind=signature.kind,
                family1_group=(
                    calendar_state.family1_group if signature.kind == "vcalendar" else None
                ),
                nested_tag_prefix=(
                    calendar_state.nested_tag_prefix if signature.kind == "vcalendar" else None
                ),
            )
            if parsed.gate is not None:
                gates.append(parsed.gate)
            if parsed.property_plan is not None:
                properties.append(parsed.property_plan)
                parameter_tags.extend(parsed.parameter_tags)
        if not saw_document_end:
            document_label = "END:VCALENDAR" if signature.kind == "vcalendar" else "END:VCARD"
            gates.append(
                VCardEmissionGate(
                    code="missing_vcard_end",
                    reason=f"No complete {document_label} marker was seen.",
                    evidence_ids=(VCARD_END_SOURCE,),
                )
            )

    if rewrite_request is not None:
        gates.append(
            VCardEmissionGate(
                code="requested_rewrite_not_supported",
                reason="VCard.pm does not define a vCard metadata write path.",
                evidence_ids=(VCARD_TABLE_SOURCE, VCARD_END_SOURCE),
            )
        )

    if not allow_output_emission:
        gates.append(
            VCardEmissionGate(
                code="output_emission_requires_explicit_opt_in",
                reason=(
                    "vCard transaction plans preserve bytes and do not emit output "
                    "unless explicitly allowed."
                ),
                evidence_ids=(VCARD_UNFOLD_SOURCE,),
            )
        )

    rewrite_blockers = (
        VCardRewriteBlocker(
            code="vcard_writer_not_defined",
            reason="VCard.pm defines read extraction only; no grounded writer is present.",
            evidence_ids=(VCARD_TABLE_SOURCE, VCARD_END_SOURCE),
        ),
        VCardRewriteBlocker(
            code="raw_line_layout_preservation_required",
            reason=(
                "Folded lines, parameter spellings, and raw value bytes are preserved "
                "rather than canonicalized."
            ),
            evidence_ids=(VCARD_UNFOLD_SOURCE, VCARD_PARAM_SOURCE),
        ),
        VCardRewriteBlocker(
            code="charset_parameter_is_not_a_write_contract",
            reason=(
                "DecodeVCardText decodes non-binary text as UTF8 and does not define "
                "charset-driven rewrite behavior."
            ),
            evidence_ids=(VCARD_DECODE_SOURCE,),
        ),
        VCardRewriteBlocker(
            code="encoding_parameter_is_decode_only",
            reason="Encoding controls read decoding only in VCard.pm.",
            evidence_ids=(VCARD_DECODE_SOURCE, VCARD_DATA_URI_SOURCE),
        ),
    )

    blocking_codes = {
        "unsupported_signature",
        "unsupported_container",
        "missing_vcard_end",
        "malformed_property_name",
        "invalid_property_line",
    }
    status: VCardPlanStatus
    if rewrite_request is not None:
        status = "unsupported"
    elif any(gate.code in blocking_codes for gate in gates):
        status = "blocked"
    else:
        status = "planned"
    output_bytes = data if status == "planned" and allow_output_emission else None
    return VCardMetadataTransactionPlan(
        status=status,
        signature=signature,
        raw_boundaries=raw_boundaries,
        logical_lines=logical_lines,
        properties=tuple(properties),
        parameter_tags=tuple(parameter_tags),
        rewrite_request=rewrite_request,
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=tuple(gates),
        output_bytes=output_bytes,
    )


def _sniff_signature(data: bytes) -> VCardSignaturePlan:
    sniffed = data[:24]
    match = re.match(rb"^BEGIN:(VCARD|VCALENDAR|VNOTE)\r\n", sniffed, re.IGNORECASE)
    kind: VCardContainerKind = "unknown"
    first_line: str | None = None
    if match is not None:
        token = match.group(1).decode("ascii").upper()
        first_line = f"BEGIN:{token}"
        if token == "VCARD":
            kind = "vcard"
        elif token == "VCALENDAR":
            kind = "vcalendar"
        elif token == "VNOTE":
            kind = "vnote"
    return VCardSignaturePlan(
        accepted=match is not None,
        kind=kind,
        first_line=first_line,
        sniffed_length=len(sniffed),
        requires_crlf=True,
        evidence_ids=(VCARD_SIGNATURE_SOURCE,),
    )


def _raw_boundaries(data: bytes) -> VCardRawBoundaryPlan:
    first_end = data.find(b"\r\n")
    complete_lines = data.count(b"\r\n")
    tail_start = data.rfind(b"\r\n")
    if tail_start == len(data) - 2:
        trailing = b""
    elif tail_start >= 0:
        trailing = data[tail_start + 2 :]
    else:
        trailing = data
    return VCardRawBoundaryPlan(
        raw_source_length=len(data),
        first_line_end=first_end + 2 if first_end >= 0 else None,
        complete_crlf_line_count=complete_lines,
        trailing_bytes=trailing,
        evidence_ids=(VCARD_SIGNATURE_SOURCE, VCARD_UNFOLD_SOURCE),
    )


def _unfold_lines(data: bytes) -> tuple[VCardLogicalLinePlan, ...]:
    physical: list[tuple[bytes, int, int]] = []
    offset = 0
    while offset < len(data):
        end = data.find(b"\r\n", offset)
        if end < 0:
            physical.append((data[offset:], offset, len(data)))
            break
        physical.append((data[offset:end], offset, end + 2))
        offset = end + 2

    logical: list[VCardLogicalLinePlan] = []
    pending_text: bytes | None = None
    pending_ranges: list[tuple[int, int]] = []
    continuation_count = 0
    for raw_line, start, end in physical:
        if pending_text is not None and raw_line.startswith((b" ", b"\t")):
            pending_text += raw_line[1:]
            pending_ranges.append((start, end))
            continuation_count += 1
            continue
        if pending_text is not None:
            logical.append(
                _logical_line(len(logical), pending_text, tuple(pending_ranges), continuation_count)
            )
        pending_text = raw_line
        pending_ranges = [(start, end)]
        continuation_count = 0
    if pending_text is not None:
        logical.append(
            _logical_line(len(logical), pending_text, tuple(pending_ranges), continuation_count)
        )
    return tuple(logical)


def _logical_line(
    index: int,
    text_bytes: bytes,
    ranges: tuple[tuple[int, int], ...],
    continuation_count: int,
) -> VCardLogicalLinePlan:
    text = text_bytes.decode("latin-1")
    action: VCardLineAction = "property"
    if _boundary_kind(text) is not None:
        action = "boundary"
    elif re.match(r"^[-A-Za-z0-9.]+", text) is None:
        action = "malformed"
    return VCardLogicalLinePlan(
        index=index,
        action=action,
        raw_line_ranges=ranges,
        unfolded_text=text,
        continuation_count=continuation_count,
        evidence_ids=(VCARD_UNFOLD_SOURCE,),
    )


class _CalendarComponentState:
    def __init__(self) -> None:
        self._component: str | None = None
        self._component_counts: dict[str, int] = {}
        self._stack: list[dict[str, str | int]] = [{}]

    @property
    def family1_group(self) -> str | None:
        if self._component is None:
            return None
        count = self._component_counts.get(self._component, 0)
        return f"{self._component}{count}" if count else self._component

    @property
    def nested_tag_prefix(self) -> str | None:
        if len(self._stack) <= 1:
            return None
        parts: list[str] = []
        for index in range(len(self._stack) - 2, -1, -1):
            object_name = self._stack[index - 1].get("obj")
            if not isinstance(object_name, str):
                continue
            count = self._stack[index].get(object_name)
            suffix = str(count) if isinstance(count, int) else ""
            parts.append(f"{object_name}{suffix}")
        return "".join(parts) or None

    def update(self, boundary: _BoundaryParts) -> None:
        if boundary.what in {"Card", "Calendar", "Note"}:
            if boundary.begin:
                self._component = None
                self._component_counts.clear()
                self._stack = [{}]
            return
        if boundary.what in VCALENDAR_COMPONENTS:
            if boundary.begin and self._component is None:
                self._stack = [{}]
                self._component = boundary.what
                self._component_counts[boundary.what] = (
                    self._component_counts.get(boundary.what, 0) + 1
                )
                return
            if not boundary.begin and self._component == boundary.what:
                self._component = None
                return
        if boundary.begin:
            if boundary.v_prefix:
                current = self._stack[-1]
                old_count = current.get(boundary.what)
                current[boundary.what] = old_count + 1 if isinstance(old_count, int) else 1
            self._stack.append({"obj": boundary.what})
        elif len(self._stack) > 1:
            self._stack.pop()


def _boundary_kind(text: str) -> Literal["begin", "end"] | None:
    parts = _boundary_parts(text)
    if parts is None:
        return None
    return "begin" if parts.begin else "end"


def _boundary_parts(text: str) -> _BoundaryParts | None:
    match = re.fullmatch(r"(BEGIN|END):(V?)(\w+)", text, re.IGNORECASE)
    if match is None:
        return None
    what = match.group(3).lower()
    return _BoundaryParts(
        begin=match.group(1).lower() == "begin",
        v_prefix=bool(match.group(2)),
        what=what[:1].upper() + what[1:],
    )


def _is_document_end(boundary: _BoundaryParts, kind: VCardContainerKind) -> bool:
    expected = {
        "vcard": "Card",
        "vcalendar": "Calendar",
        "vnote": "Note",
        "unknown": "",
    }[kind]
    return not boundary.begin and boundary.what == expected


def _parse_property_line(
    line: VCardLogicalLinePlan,
    *,
    container_kind: VCardContainerKind = "vcard",
    family1_group: str | None = None,
    nested_tag_prefix: str | None = None,
) -> _PropertyParse:
    text = line.unfolded_text
    name_match = re.match(r"^([-A-Za-z0-9.]+)", text)
    if name_match is None:
        return _PropertyParse(
            None,
            (),
            VCardEmissionGate(
                code="malformed_property_name",
                reason="Line does not start with a VCard.pm property token.",
                evidence_ids=(VCARD_PROPERTY_SOURCE,),
            ),
        )

    raw_name = name_match.group(1)
    rest = text[name_match.end() :]
    group: str | None = None
    property_name = raw_name
    if "." in raw_name:
        prefix, suffix = raw_name.split(".", 1)
        if re.fullmatch(r"[-A-Za-z0-9]+", prefix):
            group = prefix[:1].upper() + prefix[1:].lower()
            property_name = suffix

    normalized_tag = property_name[:1].upper() + property_name[1:].lower()
    display_name = _display_name_for(property_name, normalized_tag)
    known_tags = KNOWN_VCALENDAR_TAGS if container_kind == "vcalendar" else KNOWN_VCARD_TAGS
    source_entry = known_tags.get(normalized_tag)
    family2_group = source_entry[1] if source_entry is not None else None
    if source_entry is not None:
        display_name = source_entry[0]

    parameters: list[VCardParameterPlan] = []
    cursor = 0
    while cursor < len(rest) and rest[cursor] == ";":
        parsed = _parse_parameter(rest, cursor)
        parameters.append(parsed.parameter)
        cursor = parsed.next_offset

    if cursor >= len(rest) or rest[cursor] != ":":
        return _PropertyParse(
            None,
            (),
            VCardEmissionGate(
                code="invalid_property_line",
                reason="Property parameters were not followed by a colon.",
                evidence_ids=(VCARD_PARAM_SOURCE,),
            ),
        )

    raw_value = rest[cursor + 1 :]
    param_lookup: dict[str, str] = {}
    for parameter in parameters:
        existing = param_lookup.get(parameter.normalized_name)
        param_lookup[parameter.normalized_name] = (
            parameter.value if existing is None else existing + parameter.value
        )
    type_suffix = param_lookup.get("Type") or None
    routed_tag = normalized_tag
    routed_display = display_name
    if nested_tag_prefix is not None:
        routed_tag = nested_tag_prefix + routed_tag
        routed_display = nested_tag_prefix + routed_display
    if type_suffix is not None:
        routed_tag += type_suffix
        routed_display += type_suffix
    data_uri_suffix, value_for_decode, forced_encoding = _strip_data_uri_prefix(raw_value)
    if data_uri_suffix is not None:
        routed_tag += data_uri_suffix
        routed_display += data_uri_suffix
    encoding = forced_encoding or param_lookup.get("Encoding")
    value = _decode_value(
        raw_value=raw_value,
        value_for_decode=value_for_decode,
        encoding=encoding,
        charset_parameter=param_lookup.get("Charset"),
        data_uri_media_suffix=data_uri_suffix,
        convert_icalendar_time=(
            container_kind == "vcalendar" and normalized_tag in VCALENDAR_TIME_TAGS
        ),
    )
    property_plan = VCardPropertyPlan(
        line_index=line.index,
        raw_property_name=raw_name,
        group=group,
        normalized_tag=normalized_tag,
        routed_tag=routed_tag,
        display_name=routed_display,
        family2_group=family2_group,
        family1_group=group or family1_group,
        known_table_tag=source_entry is not None,
        type_suffix=type_suffix,
        language=param_lookup.get("Language"),
        parameters=tuple(parameters),
        value=value,
        evidence_ids=(VCARD_PROPERTY_SOURCE, VCARD_PARAM_SOURCE, VCARD_PARAM_TAG_SOURCE),
    )
    param_tags = _parameter_tag_plans(property_plan, param_lookup)
    return _PropertyParse(property_plan, param_tags, None)


def _display_name_for(property_name: str, normalized_tag: str) -> str:
    if property_name and any(character.islower() for character in property_name):
        name = property_name[:1].upper() + property_name[1:]
    else:
        name = normalized_tag
    if name.startswith("X-"):
        name = name[2:]
        name = name[:1].upper() + name[1:]
    return name


def _parse_parameter(rest: str, cursor: int) -> _ParsedParameter:
    name_start = cursor + 1
    name_end = name_start
    while name_end < len(rest) and re.match(r"[-A-Za-z0-9]", rest[name_end]):
        name_end += 1
    name = rest[name_start:name_end]
    normalized = name[:1].upper() + name[1:].lower()
    legacy = name_end >= len(rest) or rest[name_end] != "="
    if legacy:
        normalized = "Type"
        raw_value = name
        value = name[:1].upper() + name[1:].lower()
        return _ParsedParameter(
            VCardParameterPlan(
                name=name,
                normalized_name=normalized,
                raw_value=raw_value,
                value=value,
                legacy_type_parameter=True,
                evidence_ids=(VCARD_PARAM_SOURCE,),
            ),
            name_end,
        )

    value_start = name_end + 1
    value_end = value_start
    pieces: list[str] = []
    while value_end < len(rest):
        if rest[value_end] == '"':
            quote_end = rest.find('"', value_end + 1)
            if quote_end < 0:
                pieces.append(rest[value_end + 1 :])
                value_end = len(rest)
                break
            pieces.append(rest[value_end + 1 : quote_end])
            value_end = quote_end + 1
            if value_end < len(rest) and rest[value_end] == ",":
                pieces.append(",")
                value_end += 1
            continue
        if rest[value_end] in ";:":
            break
        pieces.append(rest[value_end])
        value_end += 1
    raw_value = rest[value_start:value_end]
    value = _unescape_vcard("".join(pieces))
    if normalized == "Type":
        value = "".join(part[:1].upper() + part[1:].lower() for part in value.split(","))
    return _ParsedParameter(
        VCardParameterPlan(
            name=name,
            normalized_name=normalized,
            raw_value=raw_value,
            value=value,
            legacy_type_parameter=False,
            evidence_ids=(VCARD_PARAM_SOURCE,),
        ),
        value_end,
    )


def _strip_data_uri_prefix(raw_value: str) -> tuple[str | None, str, str | None]:
    match = re.match(r"^data:(\w+)/(\w+);base64,", raw_value)
    if match is None:
        return None, raw_value, None
    suffix = match.group(1).capitalize() + match.group(2).capitalize()
    return suffix, raw_value[match.end() :], "base64"


def _decode_value(
    *,
    raw_value: str,
    value_for_decode: str,
    encoding: str | None,
    charset_parameter: str | None,
    data_uri_media_suffix: str | None,
    convert_icalendar_time: bool = False,
) -> VCardValuePlan:
    normalized_encoding = encoding.lower() if encoding is not None else None
    if normalized_encoding in {"b", "base64"}:
        try:
            binary_value = base64.b64decode(value_for_decode.encode("ascii"), validate=False)
        except binascii.Error, UnicodeEncodeError:
            binary_value = b""
        return VCardValuePlan(
            kind="binary",
            raw_value=raw_value,
            display_values=(),
            binary_value=binary_value,
            encoding=encoding,
            charset_parameter=charset_parameter,
            data_uri_media_suffix=data_uri_media_suffix,
            evidence_ids=(VCARD_DECODE_SOURCE, VCARD_DATA_URI_SOURCE),
        )

    text = value_for_decode
    if normalized_encoding == "quoted-printable":
        text = re.sub(
            r"=([0-9a-fA-F]{2})",
            lambda match: chr(int(match.group(1), 16)),
            text,
        )
    text = _decode_utf8_text(text)
    if convert_icalendar_time:
        text = _convert_icalendar_time(text)
    values = tuple(_unescape_vcard(value) for value in _split_vcard_list(text))
    return VCardValuePlan(
        kind="list" if len(values) > 1 else "text",
        raw_value=raw_value,
        display_values=tuple(values),
        binary_value=None,
        encoding=encoding,
        charset_parameter=charset_parameter,
        data_uri_media_suffix=data_uri_media_suffix,
        evidence_ids=(VCARD_DECODE_SOURCE,),
    )


def _convert_icalendar_time(text: str) -> str:
    text = re.sub(
        r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)",
        r"\1:\2:\3 \4:\5:\6\7",
        text,
    )
    text = re.sub(r"(\d{4})(\d{2})(\d{2})", r"\1:\2:\3", text)
    return re.sub(r"(\d{4})-(\d{2})-(\d{2})", r"\1:\2:\3", text)


def _decode_utf8_text(text: str) -> str:
    try:
        return text.encode("latin-1").decode("utf-8")
    except UnicodeDecodeError:
        return text


def _unescape_vcard(text: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            escaped = text[index + 1]
            result.append(UNESCAPE_VCARD.get(escaped, escaped))
            index += 2
            continue
        result.append(text[index])
        index += 1
    return "".join(result)


def _split_vcard_list(text: str) -> tuple[str, ...]:
    values: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            current.append(text[index])
            current.append(text[index + 1])
            index += 2
            continue
        if text[index] == ",":
            values.append("".join(current))
            current = []
            index += 1
            continue
        current.append(text[index])
        index += 1
    values.append("".join(current))
    return tuple(values)


def _parameter_tag_plans(
    property_plan: VCardPropertyPlan,
    param_lookup: dict[str, str],
) -> tuple[VCardParameterTagPlan, ...]:
    plans: list[VCardParameterTagPlan] = []
    for parameter_name in ("Geo", "Label", "Tzid"):
        raw_value = param_lookup.get(parameter_name)
        if raw_value is None:
            continue
        if property_plan.normalized_tag in KNOWN_VCALENDAR_TAGS:
            display, _family2 = KNOWN_VCALENDAR_TAGS.get(
                parameter_name,
                PARAM_TAGS[parameter_name],
            )
        else:
            display, _family2 = PARAM_TAGS[parameter_name]
        decoded = _decode_value(
            raw_value=raw_value,
            value_for_decode=raw_value,
            encoding=None,
            charset_parameter=None,
            data_uri_media_suffix=None,
            convert_icalendar_time=False,
        )
        values = decoded.display_values
        if parameter_name == "Geo":
            values = tuple(value.removeprefix("geo:") for value in values)
        plans.append(
            VCardParameterTagPlan(
                property_line_index=property_plan.line_index,
                parameter_name=parameter_name,
                routed_tag=property_plan.routed_tag + parameter_name,
                display_name=property_plan.display_name + display,
                values=values,
                evidence_ids=(VCARD_PARAM_TAG_SOURCE,),
            )
        )
    return tuple(plans)
