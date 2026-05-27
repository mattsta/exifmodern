"""Parsing plan for macOS mdls MDItem output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

type MacOSMDItemOutputStatus = Literal["planned", "unsupported"]
type MacOSMDItemOutputValueKind = Literal["scalar", "list"]
type MacOSMDItemOutputGroup2 = Literal["Audio", "Author", "Other", "Time"]
type MacOSMDItemOutputGateCode = Literal["malformed_list", "malformed_assignment"]
type MacOSMDItemOutputEvidenceId = Literal["macos.mditem.output_parsing"]
type MacOSMDItemOutputProvenance = tuple[MacOSMDItemOutputEvidenceId, ...]

MDITEM_EXTRACT_EVIDENCE_ID: MacOSMDItemOutputEvidenceId = "macos.mditem.output_parsing"

MDITEM_TAG_PATTERN = re.compile(r"^k?(\w+)\s*= (.*)$")
MDITEM_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


@dataclass(frozen=True)
class MacOSMDItemOutputGate:
    code: MacOSMDItemOutputGateCode
    reason: str
    provenance: MacOSMDItemOutputProvenance


@dataclass(frozen=True)
class MacOSMDItemOutputValuePlan:
    source_tag: str
    routed_tag: str
    value_kind: MacOSMDItemOutputValueKind
    scalar_value: str | None
    list_values: tuple[str, ...]
    group2: MacOSMDItemOutputGroup2
    dynamic_tag: bool


@dataclass(frozen=True)
class MacOSMDItemOutputPlan:
    status: MacOSMDItemOutputStatus
    values: tuple[MacOSMDItemOutputValuePlan, ...]
    output_emission_gates: tuple[MacOSMDItemOutputGate, ...]
    provenance: MacOSMDItemOutputProvenance


def build_macos_mditem_output_plan(lines: tuple[str, ...]) -> MacOSMDItemOutputPlan:
    values: list[MacOSMDItemOutputValuePlan] = []
    pending_tag: str | None = None
    pending_items: list[str] = []
    gates: list[MacOSMDItemOutputGate] = []
    for line in lines:
        if pending_tag is not None:
            if line == ")":
                values.append(_value_plan(pending_tag, None, tuple(pending_items)))
                pending_tag = None
                pending_items = []
                continue
            pending_items.append(_clean_list_item(line))
            continue
        match = MDITEM_TAG_PATTERN.match(line)
        if match is None:
            gates.append(
                MacOSMDItemOutputGate(
                    "malformed_assignment",
                    "MacOS.pm mdls parsing expects tag assignments with an equals separator.",
                    (MDITEM_EXTRACT_EVIDENCE_ID,),
                )
            )
            continue
        tag = match.group(1)
        raw_value = match.group(2)
        if raw_value == "(":
            pending_tag = tag
            pending_items = []
            continue
        values.append(_value_plan(tag, _clean_scalar(raw_value), ()))
    if pending_tag is not None:
        gates.append(
            MacOSMDItemOutputGate(
                "malformed_list",
                "MacOS.pm list parsing requires a closing parenthesis.",
                (MDITEM_EXTRACT_EVIDENCE_ID,),
            )
        )
    return MacOSMDItemOutputPlan(
        status="unsupported" if gates else "planned",
        values=tuple(values),
        output_emission_gates=tuple(gates),
        provenance=(MDITEM_EXTRACT_EVIDENCE_ID,),
    )


def _value_plan(
    source_tag: str,
    scalar_value: str | None,
    list_values: tuple[str, ...],
) -> MacOSMDItemOutputValuePlan:
    return MacOSMDItemOutputValuePlan(
        source_tag=source_tag,
        routed_tag=_routed_tag(source_tag),
        value_kind="list" if list_values else "scalar",
        scalar_value=scalar_value,
        list_values=list_values,
        group2=_group2(source_tag, scalar_value, list_values),
        dynamic_tag=source_tag.startswith("com_") or source_tag.startswith("kMD"),
    )


def _clean_scalar(raw_value: str) -> str:
    if raw_value == "(null)":
        return ""
    return _unquote(raw_value)


def _clean_list_item(raw_value: str) -> str:
    item = raw_value.strip()
    item = item.removesuffix(",")
    if item == "(null)":
        return ""
    return _unquote(item).replace(r"\"", '"').replace(r"\\", "\\")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def _routed_tag(source_tag: str) -> str:
    if source_tag.startswith("com_"):
        trimmed = source_tag.removeprefix("com_")
        pieces = trimmed.split("_")
        return "".join(piece[:1].upper() + piece[1:] for piece in pieces if piece)
    return source_tag


def _group2(
    source_tag: str,
    scalar_value: str | None,
    list_values: tuple[str, ...],
) -> MacOSMDItemOutputGroup2:
    first_value = (
        scalar_value if scalar_value is not None else (list_values[0] if list_values else "")
    )
    if MDITEM_DATE_PATTERN.match(first_value):
        return "Time"
    if "Audio" in source_tag:
        return "Audio"
    if "Copyright" in source_tag or "Author" in source_tag:
        return "Author"
    return "Other"
