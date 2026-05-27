"""Parsing plan for macOS xattr -lx output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

type MacOSXAttrOutputStatus = Literal["planned", "unsupported"]
type MacOSXAttrOutputGateCode = Literal[
    "orphan_hex_line",
    "invalid_hex_line",
    "attribute_name_missing_colon",
    "unterminated_attribute",
]
type MacOSXAttrOutputEvidenceId = Literal["macos.xattr.output_parsing"]
type MacOSXAttrOutputProvenance = tuple[MacOSXAttrOutputEvidenceId, ...]

XATTR_EXTRACT_EVIDENCE_ID: MacOSXAttrOutputEvidenceId = "macos.xattr.output_parsing"

HEX_LINE_PATTERN = re.compile(r"^[\dA-Fa-f]{8}(.*)$")


@dataclass(frozen=True)
class MacOSXAttrOutputGate:
    code: MacOSXAttrOutputGateCode
    reason: str
    provenance: MacOSXAttrOutputProvenance


@dataclass(frozen=True)
class MacOSXAttrOutputValuePlan:
    source_name: str
    normalized_name: str
    payload: bytes


@dataclass(frozen=True)
class MacOSXAttrOutputPlan:
    status: MacOSXAttrOutputStatus
    values: tuple[MacOSXAttrOutputValuePlan, ...]
    output_emission_gates: tuple[MacOSXAttrOutputGate, ...]
    provenance: MacOSXAttrOutputProvenance


def build_macos_xattr_output_plan(lines: tuple[str, ...]) -> MacOSXAttrOutputPlan:
    values: list[MacOSXAttrOutputValuePlan] = []
    gates: list[MacOSXAttrOutputGate] = []
    current_name: str | None = None
    current_payload = bytearray()
    for line in (*lines, ""):
        hex_match = HEX_LINE_PATTERN.match(line)
        if hex_match is not None:
            if current_name is None:
                gates.append(_gate("orphan_hex_line", "A hex dump line appeared before a name."))
                continue
            hex_text = hex_match.group(1).split("|", 1)[0].replace(" ", "")
            if len(hex_text) % 2 or re.search(r"[^0-9A-Fa-f]", hex_text):
                gates.append(_gate("invalid_hex_line", "The xattr hex dump line is malformed."))
                continue
            current_payload.extend(bytes.fromhex(hex_text))
            continue
        if current_name is not None:
            values.append(
                MacOSXAttrOutputValuePlan(
                    source_name=current_name,
                    normalized_name=_normalize_xattr_name(current_name),
                    payload=bytes(current_payload),
                )
            )
            current_name = None
            current_payload = bytearray()
        if not line:
            continue
        if not line.endswith(":"):
            gates.append(
                _gate(
                    "attribute_name_missing_colon",
                    "MacOS.pm requires xattr attribute names to end with a colon.",
                )
            )
            continue
        current_name = _collapse_label_identifier(line[:-1])
    if current_name is not None:
        gates.append(_gate("unterminated_attribute", "The xattr attribute had no terminator."))
    return MacOSXAttrOutputPlan(
        status="unsupported" if gates else "planned",
        values=tuple(values),
        output_emission_gates=tuple(gates),
        provenance=(XATTR_EXTRACT_EVIDENCE_ID,),
    )


def _collapse_label_identifier(name: str) -> str:
    if name.startswith("com.apple.metadata:kMDLabel_"):
        return "com.apple.metadata:kMDLabel"
    return name


def _normalize_xattr_name(name: str) -> str:
    if name.startswith("com.apple."):
        core = name.removeprefix("com.apple.")
        core = core.removeprefix("metadata:_?k")
        core = core.removeprefix("metadata:k")
        core = core.removeprefix("metadata:")
    else:
        core = name
    pieces = re.split(r"[.:_]", core)
    return "XAttr" + "".join(piece[:1].upper() + piece[1:] for piece in pieces if piece)


def _gate(code: MacOSXAttrOutputGateCode, reason: str) -> MacOSXAttrOutputGate:
    return MacOSXAttrOutputGate(code, reason, (XATTR_EXTRACT_EVIDENCE_ID,))
