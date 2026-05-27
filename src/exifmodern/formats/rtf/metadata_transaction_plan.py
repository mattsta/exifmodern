"""Source-backed, non-mutating RTF metadata transaction plans.

The planner mirrors the RTF metadata discovery responsibilities in ExifTool's
``RTF.pm``: validate the RTF signature, determine the declared character set,
scan control-word groups, route ``\\info`` metadata, tolerate user properties,
and keep byte emission behind explicit gates. It does not rewrite RTF bytes.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.json_types import JsonObject, JsonValue

RTF_INITIAL_READ_SIZE = 64
RTF_SOURCE_PATH = "lib/Image/ExifTool/RTF.pm"

type RtfGroupAction = Literal[
    "validate_rtf_signature",
    "route_info_group",
    "route_user_properties",
    "preserve_nested_group",
    "preserve_unknown_group",
]
type RtfMetadataSection = Literal["info", "user_properties"]
type RtfMetadataValueKind = Literal["text", "date"]
type RtfRouteAction = Literal[
    "upsert_info",
    "delete_info",
    "upsert_user_property",
    "delete_user_property",
]
type RtfEmissionGateCode = Literal[
    "truncated_rtf_header",
    "unsupported_rtf_signature",
    "malformed_closing_brace",
    "unterminated_rtf_group",
    "unterminated_information_group",
    "unterminated_user_properties",
    "metadata_rewrite_not_implemented",
    "planner_is_non_mutating",
    "full_rtf_writer_not_implemented",
]
type RtfControlScanConcern = Literal[
    "signature_group_validation",
    "control_word_group_scanning",
    "info_group_metadata_routing",
    "date_control_word_parsing",
    "escaped_text_decoding",
    "nested_group_preservation",
    "malformed_brace_blockers",
    "rewrite_blockers",
    "output_emission_gate",
]

RTF_ENTITY_CODEPOINTS: dict[str, int] = {
    "par": 0x0A,
    "tab": 0x09,
    "endash": 0x2013,
    "emdash": 0x2014,
    "lquote": 0x2018,
    "rquote": 0x2019,
    "ldblquote": 0x201C,
    "rdblquote": 0x201D,
    "bullet": 0x2022,
}

RTF_INFO_TAG_NAMES: dict[str, str] = {
    "title": "Title",
    "subject": "Subject",
    "author": "Author",
    "manager": "Manager",
    "company": "Company",
    "copyright": "Copyright",
    "operator": "LastModifiedBy",
    "category": "Category",
    "keywords": "Keywords",
    "comment": "Comment",
    "doccomm": "Comments",
    "hlinkbase": "HyperlinkBase",
    "creatim": "CreateDate",
    "revtim": "ModifyDate",
    "printim": "LastPrinted",
    "buptim": "BackupTime",
    "edmins": "TotalEditTime",
    "nofpages": "Pages",
    "nofwords": "Words",
    "nofchars": "Characters",
    "nofcharsws": "CharactersWithSpaces",
    "id": "InternalIDNumber",
    "version": "RevisionNumber",
    "vern": "InternalVersionNumber",
}
RTF_AUTHOR_GROUP_TAGS = frozenset(("author", "copyright"))
RTF_DATE_TAGS = frozenset(("creatim", "revtim", "printim", "buptim"))
RTF_DOCUMENT_TAGS_OF_INTEREST = frozenset(("title", "subject", "keywords", "comment"))

RTF_ENTITY_SOURCE = "rtf.entity"
RTF_MAIN_TAG_SOURCE = "rtf.main_tag"
RTF_USER_PROPS_SOURCE = "rtf.user_props"
RTF_READ_TO_NESTED_SOURCE = "rtf.read_to_nested"
RTF_UNESCAPE_SOURCE = "rtf.unescape"
RTF_SIGNATURE_SOURCE = "rtf.signature"
RTF_CHARSET_SOURCE = "rtf.charset"
RTF_INFO_SCAN_SOURCE = "rtf.info_scan"
RTF_DATE_PARSE_SOURCE = "rtf.date_parse"
RTF_USER_PROPS_SCAN_SOURCE = "rtf.user_props_scan"
RTF_READ_ONLY_SOURCE = "rtf.read_only"


@dataclass(frozen=True)
class RtfSignatureValidation:
    is_valid: bool
    signature_prefix: str
    declared_charset: str
    python_encoding: str
    reason: RtfEmissionGateCode | None
    warnings: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "declared_charset": self.declared_charset,
            "is_valid": self.is_valid,
            "python_encoding": self.python_encoding,
            "reason": self.reason,
            "signature_prefix": self.signature_prefix,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class RtfGroupPlan:
    control_word: str | None
    action: RtfGroupAction
    start_offset: int
    end_offset: int | None
    depth: int
    parent_control_word: str | None
    evidence_ids: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return self.end_offset is not None

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "control_word": self.control_word,
            "depth": self.depth,
            "end_offset": self.end_offset,
            "is_complete": self.is_complete,
            "parent_control_word": self.parent_control_word,
            "start_offset": self.start_offset,
        }


@dataclass(frozen=True)
class RtfEscapedTextBoundary:
    escape_kind: str
    raw_text: str
    decoded_text: str
    start_offset: int
    end_offset: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "decoded_text": self.decoded_text,
            "end_offset": self.end_offset,
            "escape_kind": self.escape_kind,
            "raw_text": self.raw_text,
            "start_offset": self.start_offset,
        }


@dataclass(frozen=True)
class RtfMetadataEntryPlan:
    section: RtfMetadataSection
    control_word: str
    tag_name: str
    family2_group: str
    value: str
    value_kind: RtfMetadataValueKind
    raw_value: str
    group_start_offset: int
    group_end_offset: int
    decode_boundaries: tuple[RtfEscapedTextBoundary, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "control_word": self.control_word,
            "decode_boundaries": [boundary.to_json() for boundary in self.decode_boundaries],
            "family2_group": self.family2_group,
            "group_end_offset": self.group_end_offset,
            "group_start_offset": self.group_start_offset,
            "raw_value": self.raw_value,
            "section": self.section,
            "tag_name": self.tag_name,
            "value": self.value,
            "value_kind": self.value_kind,
        }


@dataclass(frozen=True)
class RtfMetadataWriteRequest:
    control_word: str
    value: str | None
    section: RtfMetadataSection = "info"


@dataclass(frozen=True)
class RtfMetadataRoute:
    action: RtfRouteAction
    section: RtfMetadataSection
    control_word: str
    tag_name: str
    existing_value: str | None
    requested_value: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "control_word": self.control_word,
            "existing_value": self.existing_value,
            "requested_value": self.requested_value,
            "section": self.section,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class RtfControlScanResponsibility:
    order: int
    concern: RtfControlScanConcern
    description: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "description": self.description,
            "order": self.order,
        }


@dataclass(frozen=True)
class RtfRewriteBlocker:
    code: RtfEmissionGateCode
    reason: str
    requested_control_word: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
            "requested_control_word": self.requested_control_word,
        }


@dataclass(frozen=True)
class RtfEmissionGate:
    code: RtfEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RtfMetadataTransactionPlan:
    signature_validation: RtfSignatureValidation
    groups: tuple[RtfGroupPlan, ...]
    metadata_entries: tuple[RtfMetadataEntryPlan, ...]
    routes: tuple[RtfMetadataRoute, ...]
    responsibilities: tuple[RtfControlScanResponsibility, ...]
    rewrite_blockers: tuple[RtfRewriteBlocker, ...]
    output_emission_gates: tuple[RtfEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def control_words(self) -> tuple[str, ...]:
        return tuple(group.control_word for group in self.groups if group.control_word is not None)

    @property
    def metadata_by_tag(self) -> dict[str, str]:
        return {entry.tag_name: entry.value for entry in self.metadata_entries}

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"RTF metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "control_words": list(self.control_words),
            "groups": [group.to_json() for group in self.groups],
            "metadata_by_tag": dict(self.metadata_by_tag),
            "metadata_entries": [entry.to_json() for entry in self.metadata_entries],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "rewrite_blockers": [blocker.to_json() for blocker in self.rewrite_blockers],
            "routes": [route.to_json() for route in self.routes],
            "signature_validation": self.signature_validation.to_json(),
        }


def build_rtf_metadata_transaction_plan(
    data: bytes,
    metadata_writes: tuple[RtfMetadataWriteRequest, ...] = (),
) -> RtfMetadataTransactionPlan:
    """Build a source-grounded, non-mutating RTF metadata transaction plan."""

    text = data.decode("latin-1")
    signature_validation, signature_gates = validate_signature_and_charset(text, data)
    groups, group_gates = scan_rtf_groups(text) if signature_validation.is_valid else ((), ())
    metadata_entries, metadata_gates = extract_metadata_entries(
        text,
        groups,
        signature_validation.python_encoding,
    )
    routes = route_metadata_writes(metadata_entries, metadata_writes)
    rewrite_blockers = build_rewrite_blockers(metadata_writes)
    responsibilities = default_responsibilities()
    gates = [
        *signature_gates,
        *group_gates,
        *metadata_gates,
        *(
            RtfEmissionGate(
                blocker.code,
                blocker.reason,
                True,
                blocker.evidence_ids,
            )
            for blocker in rewrite_blockers
        ),
        RtfEmissionGate(
            "planner_is_non_mutating",
            "RTF metadata transaction plans record decisions but do not mutate bytes.",
            True,
            (RTF_READ_ONLY_SOURCE,),
        ),
        RtfEmissionGate(
            "full_rtf_writer_not_implemented",
            "Safe RTF emission requires a writer that can rebuild nested groups and escaped text.",
            True,
            (RTF_READ_ONLY_SOURCE, RTF_READ_TO_NESTED_SOURCE, RTF_UNESCAPE_SOURCE),
        ),
    ]
    sources = unique_sources(
        (
            *signature_validation.evidence_ids,
            *(source for group in groups for source in group.evidence_ids),
            *(source for entry in metadata_entries for source in entry.evidence_ids),
            *(source for route in routes for source in route.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
            *(source for blocker in rewrite_blockers for source in blocker.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return RtfMetadataTransactionPlan(
        signature_validation=signature_validation,
        groups=groups,
        metadata_entries=metadata_entries,
        routes=routes,
        responsibilities=responsibilities,
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
    )


def validate_signature_and_charset(
    text: str,
    data: bytes,
) -> tuple[RtfSignatureValidation, tuple[RtfEmissionGate, ...]]:
    prefix = text[:RTF_INITIAL_READ_SIZE]
    if len(data) < RTF_INITIAL_READ_SIZE:
        return (
            RtfSignatureValidation(
                False,
                prefix,
                "Latin",
                "latin-1",
                "truncated_rtf_header",
                ("RTF header is shorter than ExifTool's initial 64-byte read.",),
                (RTF_SIGNATURE_SOURCE,),
            ),
            (
                RtfEmissionGate(
                    "truncated_rtf_header",
                    "Input ended before ExifTool's initial 64-byte RTF header read.",
                    True,
                    (RTF_SIGNATURE_SOURCE,),
                ),
            ),
        )

    if re.match(r"^[\n\r]*\{[\n\r]*\\rtf[^a-zA-Z]", prefix) is None:
        return (
            RtfSignatureValidation(
                False,
                prefix,
                "Latin",
                "latin-1",
                "unsupported_rtf_signature",
                (),
                (RTF_SIGNATURE_SOURCE,),
            ),
            (
                RtfEmissionGate(
                    "unsupported_rtf_signature",
                    "ExifTool RTF processing accepts only files beginning with an RTF group.",
                    True,
                    (RTF_SIGNATURE_SOURCE,),
                ),
            ),
        )

    declared_charset, python_encoding, warnings = determine_charset(prefix)
    return (
        RtfSignatureValidation(
            True,
            prefix,
            declared_charset,
            python_encoding,
            None,
            warnings,
            (RTF_SIGNATURE_SOURCE, RTF_CHARSET_SOURCE),
        ),
        (),
    )


def determine_charset(prefix: str) -> tuple[str, str, tuple[str, ...]]:
    ansicpg = re.search(r"\\ansicpg(\d*)", prefix)
    if ansicpg is not None:
        declared = f"cp{ansicpg.group(1)}"
        python_encoding = declared
    else:
        charset_match = re.search(r"\\(ansi|mac|pc|pca)[^a-zA-Z]", prefix)
        if charset_match is None:
            return (
                "Latin",
                "latin-1",
                ("Unspecified RTF encoding; matching ExifTool's Latin fallback.",),
            )
        declared, python_encoding = {
            "ansi": ("Latin", "latin-1"),
            "mac": ("MacRoman", "mac_roman"),
            "pc": ("cp437", "cp437"),
            "pca": ("cp850", "cp850"),
        }[charset_match.group(1)]

    try:
        codecs.lookup(python_encoding)
    except LookupError:
        return (
            declared,
            "latin-1",
            (f"Unsupported RTF encoding {declared}; matching ExifTool's Latin fallback.",),
        )
    return declared, python_encoding, ()


def scan_rtf_groups(text: str) -> tuple[tuple[RtfGroupPlan, ...], tuple[RtfEmissionGate, ...]]:
    stack: list[tuple[int, int, str | None]] = []
    groups: list[RtfGroupPlan] = []
    gates: list[RtfEmissionGate] = []
    for index, char in enumerate(text):
        if char not in "{}" or is_escaped_brace(text, index):
            continue
        if char == "{":
            depth = len(stack)
            control_word = first_control_word(text, index)
            stack.append((index, depth, control_word))
            continue
        if not stack:
            gates.append(
                RtfEmissionGate(
                    "malformed_closing_brace",
                    f"Unmatched closing brace at offset {index}.",
                    True,
                    (RTF_READ_TO_NESTED_SOURCE,),
                )
            )
            continue
        start, depth, control_word = stack.pop()
        parent_control_word = stack[-1][2] if stack else None
        groups.append(
            RtfGroupPlan(
                control_word=control_word,
                action=group_action(control_word, depth),
                start_offset=start,
                end_offset=index + 1,
                depth=depth,
                parent_control_word=parent_control_word,
                evidence_ids=group_sources(control_word),
            )
        )

    for start, depth, control_word in stack:
        gates.append(
            RtfEmissionGate(
                "unterminated_rtf_group",
                f"RTF group starting at offset {start} is missing its closing brace.",
                True,
                (RTF_READ_TO_NESTED_SOURCE,),
            )
        )
        groups.append(
            RtfGroupPlan(
                control_word=control_word,
                action=group_action(control_word, depth),
                start_offset=start,
                end_offset=None,
                depth=depth,
                parent_control_word=None,
                evidence_ids=group_sources(control_word),
            )
        )

    return tuple(sorted(groups, key=lambda group: group.start_offset)), tuple(gates)


def extract_metadata_entries(
    text: str,
    groups: tuple[RtfGroupPlan, ...],
    python_encoding: str,
) -> tuple[tuple[RtfMetadataEntryPlan, ...], tuple[RtfEmissionGate, ...]]:
    entries: list[RtfMetadataEntryPlan] = []
    gates: list[RtfEmissionGate] = []
    complete_groups = tuple(group for group in groups if group.end_offset is not None)
    for info_group in complete_groups:
        if info_group.action != "route_info_group":
            continue
        info_end = checked_end(info_group)
        child_groups = immediate_child_groups(info_group, complete_groups)
        if not child_groups and not group_has_closing_brace(info_group):
            gates.append(
                RtfEmissionGate(
                    "unterminated_information_group",
                    f"Information group at offset {info_group.start_offset} is unterminated.",
                    True,
                    (RTF_INFO_SCAN_SOURCE, RTF_READ_TO_NESTED_SOURCE),
                )
            )
            continue
        for child in child_groups:
            if child.control_word is None or child.end_offset is None:
                continue
            payload_start, payload_end = group_payload_bounds(text, child)
            if payload_start >= payload_end:
                continue
            raw_value = text[payload_start:payload_end]
            entries.append(
                build_info_entry(
                    child.control_word,
                    raw_value,
                    child.start_offset,
                    checked_end(child),
                    python_encoding,
                )
            )
        if info_end > len(text):
            gates.append(
                RtfEmissionGate(
                    "unterminated_information_group",
                    f"Information group at offset {info_group.start_offset} extends beyond input.",
                    True,
                    (RTF_INFO_SCAN_SOURCE, RTF_READ_TO_NESTED_SOURCE),
                )
            )

    entries.extend(extract_user_property_entries(text, complete_groups, python_encoding))
    return tuple(entries), tuple(gates)


def build_info_entry(
    control_word: str,
    raw_value: str,
    group_start_offset: int,
    group_end_offset: int,
    python_encoding: str,
) -> RtfMetadataEntryPlan:
    tag_name = RTF_INFO_TAG_NAMES.get(control_word, ucfirst(control_word))
    if control_word in RTF_DATE_TAGS:
        value = parse_rtf_date(raw_value)
        value_kind: RtfMetadataValueKind = "date"
        boundaries: tuple[RtfEscapedTextBoundary, ...] = ()
        sources = (RTF_MAIN_TAG_SOURCE, RTF_INFO_SCAN_SOURCE, RTF_DATE_PARSE_SOURCE)
    else:
        value, boundaries = unescape_rtf(raw_value, python_encoding, group_start_offset)
        value_kind = "text"
        sources = (RTF_MAIN_TAG_SOURCE, RTF_INFO_SCAN_SOURCE, RTF_UNESCAPE_SOURCE)

    return RtfMetadataEntryPlan(
        section="info",
        control_word=control_word,
        tag_name=tag_name,
        family2_group=family2_group_for_info(control_word),
        value=value,
        value_kind=value_kind,
        raw_value=raw_value,
        group_start_offset=group_start_offset,
        group_end_offset=group_end_offset,
        decode_boundaries=boundaries,
        evidence_ids=sources,
    )


def extract_user_property_entries(
    text: str,
    groups: tuple[RtfGroupPlan, ...],
    python_encoding: str,
) -> tuple[RtfMetadataEntryPlan, ...]:
    entries: list[RtfMetadataEntryPlan] = []
    for props_group in groups:
        if props_group.action != "route_user_properties":
            continue
        pending_tag: str | None = None
        for child in nested_user_property_groups(props_group, groups):
            if child.control_word is None or child.end_offset is None:
                continue
            payload_start, payload_end = group_payload_bounds(text, child)
            raw_value = text[payload_start:payload_end]
            value, boundaries = unescape_rtf(raw_value, python_encoding, child.start_offset)
            if child.control_word == "propname":
                pending_tag = sanitize_user_property_tag(value)
                continue
            if child.control_word != "staticval" or pending_tag is None:
                continue
            entries.append(
                RtfMetadataEntryPlan(
                    section="user_properties",
                    control_word=child.control_word,
                    tag_name=pending_tag,
                    family2_group="Document",
                    value=value,
                    value_kind="text",
                    raw_value=raw_value,
                    group_start_offset=child.start_offset,
                    group_end_offset=checked_end(child),
                    decode_boundaries=boundaries,
                    evidence_ids=(
                        RTF_USER_PROPS_SOURCE,
                        RTF_USER_PROPS_SCAN_SOURCE,
                        RTF_UNESCAPE_SOURCE,
                    ),
                )
            )
            pending_tag = None
    return tuple(entries)


def unescape_rtf(
    value: str,
    python_encoding: str,
    base_offset: int,
) -> tuple[str, tuple[RtfEscapedTextBoundary, ...]]:
    value = normalize_rtf_newline_controls(value)
    output: list[str] = []
    boundaries: list[RtfEscapedTextBoundary] = []
    index = 0
    unicode_skip = 1
    while index < len(value):
        char = value[index]
        if char != "\\":
            output.append(char)
            index += 1
            continue
        if index + 1 >= len(value):
            break
        next_char = value[index + 1]
        if next_char.isalpha():
            control, parameter, after = parse_control_word(value, index + 1)
            raw_text = value[index:after]
            if control == "uc" and parameter is not None:
                unicode_skip = max(0, parameter)
            elif control == "u" and parameter is not None:
                decoded = "?" if parameter < 0 else chr(parameter)
                output.append(decoded)
                skip_end = skip_rtf_fallback(value, after, unicode_skip)
                boundaries.append(
                    RtfEscapedTextBoundary(
                        "unicode_control",
                        value[index:skip_end],
                        decoded,
                        base_offset + index,
                        base_offset + skip_end,
                        (RTF_UNESCAPE_SOURCE,),
                    )
                )
                index = skip_end
                continue
            elif control in RTF_ENTITY_CODEPOINTS:
                decoded = chr(RTF_ENTITY_CODEPOINTS[control])
                output.append(decoded)
                boundaries.append(
                    RtfEscapedTextBoundary(
                        "entity_control",
                        raw_text,
                        decoded,
                        base_offset + index,
                        base_offset + after,
                        (RTF_ENTITY_SOURCE, RTF_UNESCAPE_SOURCE),
                    )
                )
            index = after
            continue
        if next_char == "'":
            raw_text = value[index : index + 4]
            hex_decoded = decode_hex_escape(raw_text, python_encoding)
            if hex_decoded is not None:
                output.append(hex_decoded)
                boundaries.append(
                    RtfEscapedTextBoundary(
                        "hex_escape",
                        raw_text,
                        hex_decoded,
                        base_offset + index,
                        base_offset + index + len(raw_text),
                        (RTF_UNESCAPE_SOURCE, RTF_CHARSET_SOURCE),
                    )
                )
            index += 4
            continue
        output.append(next_char)
        boundaries.append(
            RtfEscapedTextBoundary(
                "control_symbol",
                value[index : index + 2],
                next_char,
                base_offset + index,
                base_offset + index + 2,
                (RTF_UNESCAPE_SOURCE,),
            )
        )
        index += 2
    return "".join(output), tuple(boundaries)


def normalize_rtf_newline_controls(value: str) -> str:
    if "\\" not in value:
        return value.replace("\r", "").replace("\n", "")
    output: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            output.append(char)
            index += 1
            continue
        if index + 1 >= len(value):
            output.append(char)
            index += 1
            continue
        next_index = index + 1
        next_char = value[next_index]
        if next_char.isalpha():
            control_start = next_index
            cursor = control_start
            while cursor < len(value) and value[cursor].isalpha():
                cursor += 1
            if cursor < len(value) and value[cursor] == "-":
                cursor += 1
            while cursor < len(value) and value[cursor].isdigit():
                cursor += 1
            if cursor < len(value) and value[cursor] in "\r\n":
                output.append("\\" + value[control_start:cursor] + " ")
                index = skip_newline_sequence(value, cursor)
                continue
        if next_char in "\r\n":
            output.append(r"\par ")
            index = skip_newline_sequence(value, next_index)
            continue
        output.append("\\" + next_char)
        index += 2
    return "".join(output).replace("\r", "").replace("\n", "")


def skip_newline_sequence(value: str, index: int) -> int:
    if index + 1 < len(value) and value[index : index + 2] in {"\r\n", "\n\r"}:
        return index + 2
    return index + 1


def parse_control_word(value: str, start: int) -> tuple[str, int | None, int]:
    index = start
    while index < len(value) and value[index].isalpha():
        index += 1
    control = value[start:index]
    sign = 1
    if index < len(value) and value[index] == "-":
        sign = -1
        index += 1
    number_start = index
    while index < len(value) and value[index].isdigit():
        index += 1
    parameter = sign * int(value[number_start:index]) if index > number_start else None
    if index < len(value) and value[index] == " ":
        index += 1
    return control, parameter, index


def skip_rtf_fallback(value: str, start: int, count: int) -> int:
    index = start
    for _ in range(count):
        if index >= len(value):
            return index
        if value[index] != "\\":
            index += 1
            continue
        if index + 1 >= len(value):
            return len(value)
        if value[index + 1] == "'":
            index = min(len(value), index + 4)
            continue
        if value[index + 1].isalpha():
            _, _, index = parse_control_word(value, index + 1)
            continue
        index += 2
    return index


def decode_hex_escape(raw_text: str, python_encoding: str) -> str | None:
    if len(raw_text) != 4 or not re.match(r"^\\'[0-9a-fA-F]{2}$", raw_text):
        return None
    return bytes((int(raw_text, 0),)).decode(python_encoding, errors="replace")


def parse_rtf_date(raw_value: str) -> str:
    fields = {"yr": 0, "mo": 0, "dy": 0, "hr": 0, "min": 0, "sec": 0}
    for match in re.finditer(r"\\([a-z]+)(\d+)", raw_value):
        field = match.group(1)
        if field in fields:
            fields[field] = int(match.group(2))
    return (
        f"{fields['yr']:04d}:{fields['mo']:02d}:{fields['dy']:02d} "
        f"{fields['hr']:02d}:{fields['min']:02d}:{fields['sec']:02d}"
    )


def route_metadata_writes(
    entries: tuple[RtfMetadataEntryPlan, ...],
    metadata_writes: tuple[RtfMetadataWriteRequest, ...],
) -> tuple[RtfMetadataRoute, ...]:
    routes: list[RtfMetadataRoute] = []
    for request in metadata_writes:
        existing = next(
            (
                entry
                for entry in entries
                if entry.section == request.section and entry.control_word == request.control_word
            ),
            None,
        )
        tag_name = (
            existing.tag_name
            if existing is not None
            else RTF_INFO_TAG_NAMES.get(request.control_word, ucfirst(request.control_word))
        )
        if request.section == "info":
            action: RtfRouteAction = "delete_info" if request.value is None else "upsert_info"
        else:
            action = "delete_user_property" if request.value is None else "upsert_user_property"
        routes.append(
            RtfMetadataRoute(
                action=action,
                section=request.section,
                control_word=request.control_word,
                tag_name=tag_name,
                existing_value=None if existing is None else existing.value,
                requested_value=request.value,
                evidence_ids=(RTF_INFO_SCAN_SOURCE, RTF_USER_PROPS_SCAN_SOURCE),
            )
        )
    return tuple(routes)


def build_rewrite_blockers(
    metadata_writes: tuple[RtfMetadataWriteRequest, ...],
) -> tuple[RtfRewriteBlocker, ...]:
    return tuple(
        RtfRewriteBlocker(
            "metadata_rewrite_not_implemented",
            (
                "RTF metadata rewrites are intentionally blocked because this surface "
                "only plans ExifTool's read/discovery behavior."
            ),
            request.control_word,
            (RTF_READ_ONLY_SOURCE, RTF_READ_TO_NESTED_SOURCE, RTF_UNESCAPE_SOURCE),
        )
        for request in metadata_writes
    )


def default_responsibilities() -> tuple[RtfControlScanResponsibility, ...]:
    return (
        RtfControlScanResponsibility(
            1,
            "signature_group_validation",
            "Validate that the file begins with ExifTool's accepted RTF signature.",
            (RTF_SIGNATURE_SOURCE,),
        ),
        RtfControlScanResponsibility(
            2,
            "control_word_group_scanning",
            "Scan brace-delimited RTF groups while respecting escaped braces.",
            (RTF_READ_TO_NESTED_SOURCE,),
        ),
        RtfControlScanResponsibility(
            3,
            "info_group_metadata_routing",
            "Route child control-word groups in the information group through RTF main tags.",
            (RTF_MAIN_TAG_SOURCE, RTF_INFO_SCAN_SOURCE),
        ),
        RtfControlScanResponsibility(
            4,
            "date_control_word_parsing",
            "Parse creatim/revtim/printim/buptim date controls into ExifTool date strings.",
            (RTF_MAIN_TAG_SOURCE, RTF_DATE_PARSE_SOURCE),
        ),
        RtfControlScanResponsibility(
            5,
            "escaped_text_decoding",
            "Decode RTF hex, Unicode, entity, and control-symbol text boundaries.",
            (RTF_UNESCAPE_SOURCE, RTF_ENTITY_SOURCE),
        ),
        RtfControlScanResponsibility(
            6,
            "nested_group_preservation",
            "Preserve non-metadata and nested groups instead of flattening document structure.",
            (RTF_READ_TO_NESTED_SOURCE, RTF_INFO_SCAN_SOURCE),
        ),
        RtfControlScanResponsibility(
            7,
            "malformed_brace_blockers",
            "Block emission when brace scanning finds unmatched or unterminated groups.",
            (RTF_READ_TO_NESTED_SOURCE,),
        ),
        RtfControlScanResponsibility(
            8,
            "rewrite_blockers",
            "Record requested metadata routes but block rewrites without a complete writer.",
            (RTF_READ_ONLY_SOURCE,),
        ),
        RtfControlScanResponsibility(
            9,
            "output_emission_gate",
            "Keep byte emission disabled for this non-mutating planning surface.",
            (RTF_READ_ONLY_SOURCE,),
        ),
    )


def group_payload_bounds(text: str, group: RtfGroupPlan) -> tuple[int, int]:
    control_start = group.start_offset + 1
    while control_start < len(text) and text[control_start] in "\n\r":
        control_start += 1
    if text.startswith(r"\*", control_start):
        control_start += 2
        while control_start < len(text) and text[control_start] in "\n\r":
            control_start += 1
    if control_start < len(text) and text[control_start] == "\\":
        _, _, control_end = parse_control_word(text, control_start + 1)
    else:
        control_end = control_start
    group_end = checked_end(group)
    return control_end, max(control_end, group_end - 1)


def first_control_word(text: str, group_start: int) -> str | None:
    index = group_start + 1
    while index < len(text) and text[index] in "\n\r":
        index += 1
    if text.startswith(r"\*", index):
        index += 2
        while index < len(text) and text[index] in "\n\r":
            index += 1
    if index >= len(text) or text[index] != "\\":
        return None
    control, _, _ = parse_control_word(text, index + 1)
    return control or None


def group_action(control_word: str | None, depth: int) -> RtfGroupAction:
    if control_word == "rtf":
        return "validate_rtf_signature"
    if control_word == "info":
        return "route_info_group"
    if control_word == "userprops":
        return "route_user_properties"
    if depth > 0:
        return "preserve_nested_group"
    return "preserve_unknown_group"


def group_sources(control_word: str | None) -> tuple[str, ...]:
    if control_word == "rtf":
        return (RTF_SIGNATURE_SOURCE, RTF_READ_TO_NESTED_SOURCE)
    if control_word == "info":
        return (RTF_INFO_SCAN_SOURCE, RTF_READ_TO_NESTED_SOURCE)
    if control_word == "userprops":
        return (RTF_USER_PROPS_SCAN_SOURCE, RTF_READ_TO_NESTED_SOURCE)
    return (RTF_READ_TO_NESTED_SOURCE,)


def immediate_child_groups(
    parent: RtfGroupPlan,
    groups: tuple[RtfGroupPlan, ...],
) -> tuple[RtfGroupPlan, ...]:
    parent_end = checked_end(parent)
    return tuple(
        group
        for group in groups
        if group.depth == parent.depth + 1
        and group.start_offset > parent.start_offset
        and group.end_offset is not None
        and group.end_offset <= parent_end
    )


def nested_user_property_groups(
    parent: RtfGroupPlan,
    groups: tuple[RtfGroupPlan, ...],
) -> tuple[RtfGroupPlan, ...]:
    parent_end = checked_end(parent)
    return tuple(
        group
        for group in groups
        if group.depth > parent.depth
        and group.start_offset > parent.start_offset
        and group.end_offset is not None
        and group.end_offset <= parent_end
        and group.control_word in {"propname", "staticval", "proptype", "linkval"}
    )


def checked_end(group: RtfGroupPlan) -> int:
    if group.end_offset is None:
        return group.start_offset
    return group.end_offset


def group_has_closing_brace(group: RtfGroupPlan) -> bool:
    return group.end_offset is not None


def is_escaped_brace(text: str, index: int) -> bool:
    slash_count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        slash_count += 1
        cursor -= 1
    return slash_count % 2 == 1


def family2_group_for_info(control_word: str) -> str:
    if control_word in RTF_AUTHOR_GROUP_TAGS:
        return "Author"
    if control_word in RTF_DATE_TAGS:
        return "Time"
    return "Document"


def sanitize_user_property_tag(value: str) -> str:
    result: list[str] = []
    capitalize_next = False
    for char in value:
        if char.isspace():
            capitalize_next = True
            continue
        if char in "-_" or char.isalnum():
            result.append(char.upper() if capitalize_next else char)
            capitalize_next = False
    return "".join(result)


def ucfirst(value: str) -> str:
    if not value:
        return value
    return value[0].upper() + value[1:]


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for source in sources:
        if source not in unique:
            unique.append(source)
    return tuple(unique)


def unique_gates(gates: tuple[RtfEmissionGate, ...]) -> tuple[RtfEmissionGate, ...]:
    unique: list[RtfEmissionGate] = []
    seen_codes: set[RtfEmissionGateCode] = set()
    for gate in gates:
        if gate.code not in seen_codes:
            unique.append(gate)
            seen_codes.add(gate.code)
    return tuple(unique)


def metadata_value_to_json(value: str | None) -> JsonValue:
    return value


install_evidence_reference_compat(globals())
