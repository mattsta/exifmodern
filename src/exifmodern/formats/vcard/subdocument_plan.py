"""Source-backed vCard subdocument table routing for VCalendar and VNote."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type VCardSubdocumentStatus = Literal["planned", "unsupported"]
type VCardSubdocumentKind = Literal["vcalendar", "vnote", "vcard", "unknown"]
type VCardSubdocumentGateCode = Literal["missing_begin_line", "unsupported_begin_line"]
type VCardSubdocumentEvidenceId = str

VCALENDAR_TABLE_SOURCE = "vcard.vcalendar_table"
VNOTE_TABLE_SOURCE = "vcard.vnote_table"
VCARD_SIGNATURE_SOURCE = "vcard.signature"

VCALENDAR_KNOWN_TAGS: dict[str, str] = {
    "VERSION": "VCalendarVersion",
    "CALSCALE": "CalendarScale",
    "METHOD": "Method",
    "PRODID": "Software",
    "ATTACH": "Attachment",
    "CATEGORIES": "Categories",
    "CLASS": "Classification",
    "COMMENT": "Comment",
    "DESCRIPTION": "Description",
    "GEO": "Geolocation",
}
VNOTE_KNOWN_TAGS: dict[str, str] = {
    "VERSION": "Version",
    "BODY": "Body",
    "DCREATED": "CreateDate",
    "LAST-MODIFIED": "ModifyDate",
}


@dataclass(frozen=True)
class VCardSubdocumentGate:
    code: VCardSubdocumentGateCode
    reason: str
    evidence_ids: tuple[VCardSubdocumentEvidenceId, ...]


@dataclass(frozen=True)
class VCardComponentPlan:
    name: str
    family1_group: str | None
    embedded_prefix: str | None


@dataclass(frozen=True)
class VCardSubdocumentTagPlan:
    source_name: str
    routed_name: str
    family1_group: str | None
    embedded_prefix: str | None
    known_table_tag: bool


@dataclass(frozen=True)
class VCardSubdocumentPlan:
    status: VCardSubdocumentStatus
    kind: VCardSubdocumentKind
    source_table: str | None
    components: tuple[VCardComponentPlan, ...]
    tags: tuple[VCardSubdocumentTagPlan, ...]
    output_emission_gates: tuple[VCardSubdocumentGate, ...]
    evidence_ids: tuple[VCardSubdocumentEvidenceId, ...]


def build_vcard_subdocument_plan(text: str) -> VCardSubdocumentPlan:
    lines = tuple(line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip())
    if not lines:
        return _unsupported("missing_begin_line", "No BEGIN line was present.")
    first_line = lines[0].upper()
    if first_line == "BEGIN:VCALENDAR":
        return _planned("vcalendar", "Image::ExifTool::VCard::VCalendar", lines)
    if first_line == "BEGIN:VNOTE":
        return _planned("vnote", "Image::ExifTool::VCard::VNote", lines)
    if first_line == "BEGIN:VCARD":
        return _planned("vcard", "Image::ExifTool::VCard::Main", lines)
    return _unsupported("unsupported_begin_line", "The BEGIN line is not routed by VCard.pm.")


def _planned(
    kind: VCardSubdocumentKind,
    source_table: str,
    lines: tuple[str, ...],
) -> VCardSubdocumentPlan:
    components: list[VCardComponentPlan] = []
    tags: list[VCardSubdocumentTagPlan] = []
    stack: list[str] = []
    for line in lines:
        upper = line.upper()
        if upper.startswith("BEGIN:"):
            component = upper.removeprefix("BEGIN:")
            if component not in {"VCALENDAR", "VNOTE", "VCARD"}:
                stack.append(component.title())
                components.append(_component_plan(stack))
            continue
        if upper.startswith("END:"):
            component = upper.removeprefix("END:").title()
            if stack and stack[-1] == component:
                stack.pop()
            continue
        if ":" not in line:
            continue
        tag_name = line.split(":", 1)[0].split(";", 1)[0].upper()
        tags.append(_tag_plan(kind, tag_name, stack))
    return VCardSubdocumentPlan(
        status="planned",
        kind=kind,
        source_table=source_table,
        components=tuple(components),
        tags=tuple(tags),
        output_emission_gates=(),
        evidence_ids=_evidence_ids_for_kind(kind),
    )


def _component_plan(stack: list[str]) -> VCardComponentPlan:
    family1_group = stack[0] if stack else None
    embedded_prefix = stack[-1] if len(stack) > 1 else None
    return VCardComponentPlan(stack[-1], family1_group, embedded_prefix)


def _tag_plan(
    kind: VCardSubdocumentKind,
    tag_name: str,
    stack: list[str],
) -> VCardSubdocumentTagPlan:
    known_tags = VCALENDAR_KNOWN_TAGS if kind == "vcalendar" else VNOTE_KNOWN_TAGS
    routed_name = known_tags.get(tag_name, tag_name.title().replace("-", ""))
    embedded_prefix = stack[-1] if kind == "vcalendar" and len(stack) > 1 else None
    family1_group = stack[0] if kind == "vcalendar" and stack else None
    return VCardSubdocumentTagPlan(
        source_name=tag_name,
        routed_name=routed_name,
        family1_group=family1_group,
        embedded_prefix=embedded_prefix,
        known_table_tag=tag_name in known_tags,
    )


def _evidence_ids_for_kind(kind: VCardSubdocumentKind) -> tuple[VCardSubdocumentEvidenceId, ...]:
    if kind == "vcalendar":
        return (VCALENDAR_TABLE_SOURCE, VCARD_SIGNATURE_SOURCE)
    if kind == "vnote":
        return (VNOTE_TABLE_SOURCE, VCARD_SIGNATURE_SOURCE)
    return (VCARD_SIGNATURE_SOURCE,)


def _unsupported(code: VCardSubdocumentGateCode, reason: str) -> VCardSubdocumentPlan:
    return VCardSubdocumentPlan(
        status="unsupported",
        kind="unknown",
        source_table=None,
        components=(),
        tags=(),
        output_emission_gates=(VCardSubdocumentGate(code, reason, (VCARD_SIGNATURE_SOURCE,)),),
        evidence_ids=(VCARD_SIGNATURE_SOURCE,),
    )
