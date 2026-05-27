"""MacOS xattr value routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type MacOSXAttrValueStatus = Literal["planned", "unsupported"]
type MacOSXAttrValueKind = Literal["bplist", "binary", "text"]
type MacOSXAttrValueGroup2 = Literal["Other", "Time"]
type MacOSXAttrValueGateCode = Literal["bplist_dictionary_not_scalar", "bplist_decode_failed"]
type MacOSXAttrValueEvidenceId = Literal["macos.xattr.value_routing"]
type MacOSXAttrValueProvenance = tuple[MacOSXAttrValueEvidenceId, ...]

XATTR_VALUE_EVIDENCE_ID: MacOSXAttrValueEvidenceId = "macos.xattr.value_routing"


@dataclass(frozen=True)
class MacOSXAttrValueGate:
    code: MacOSXAttrValueGateCode
    reason: str
    provenance: MacOSXAttrValueProvenance


@dataclass(frozen=True)
class MacOSXAttrValuePlan:
    status: MacOSXAttrValueStatus
    source_name: str
    routed_tag: str
    group2: MacOSXAttrValueGroup2
    value_kind: MacOSXAttrValueKind
    payload_preserved: bool
    output_emission_gates: tuple[MacOSXAttrValueGate, ...]
    provenance: MacOSXAttrValueProvenance


def build_macos_xattr_value_plan(
    source_name: str,
    payload: bytes,
    bplist_scalar_decoded: bool = True,
) -> MacOSXAttrValuePlan:
    routed_tag = _routed_tag(source_name)
    if payload.startswith(b"bplist0"):
        if not bplist_scalar_decoded:
            return _unsupported(
                source_name,
                routed_tag,
                "bplist_dictionary_not_scalar",
                "MacOS.pm drops decoded bplist dictionaries instead of emitting scalar tags.",
            )
        value_kind: MacOSXAttrValueKind = "bplist"
    elif b"\0" in payload or len(payload) > 200 or routed_tag == "XAttrMDLabel":
        value_kind = "binary"
    else:
        value_kind = "text"
    return MacOSXAttrValuePlan(
        status="planned",
        source_name=source_name,
        routed_tag=routed_tag,
        group2="Time" if source_name.endswith("Date") else "Other",
        value_kind=value_kind,
        payload_preserved=value_kind == "binary",
        output_emission_gates=(),
        provenance=(XATTR_VALUE_EVIDENCE_ID,),
    )


def _routed_tag(source_name: str) -> str:
    if source_name.startswith("com.apple."):
        name = source_name.removeprefix("com.apple.")
        name = name.removeprefix("metadata:_?k")
        name = name.removeprefix("metadata:k")
        name = name.removeprefix("metadata:")
    else:
        name = source_name
    pieces = name.replace(".", "_").replace(":", "_").split("_")
    return "XAttr" + "".join(piece[:1].upper() + piece[1:] for piece in pieces if piece)


def _unsupported(
    source_name: str,
    routed_tag: str,
    code: MacOSXAttrValueGateCode,
    reason: str,
) -> MacOSXAttrValuePlan:
    return MacOSXAttrValuePlan(
        status="unsupported",
        source_name=source_name,
        routed_tag=routed_tag,
        group2="Time" if source_name.endswith("Date") else "Other",
        value_kind="bplist",
        payload_preserved=False,
        output_emission_gates=(MacOSXAttrValueGate(code, reason, (XATTR_VALUE_EVIDENCE_ID,)),),
        provenance=(XATTR_VALUE_EVIDENCE_ID,),
    )
