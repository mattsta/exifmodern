"""Source-grounded, non-mutating generic trailer transaction plans.

ExifTool's Trailer module routes phone JPEG trailers for Vivo, OnePlus, and
Google.  This planner mirrors the source-backed discovery and extraction
boundaries while keeping mutation and container rewrites gated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonValue

TRAILER_PM_SOURCE_PATH = "lib/Image/ExifTool/Trailer.pm"
VIVO_FOOTER = b"\xff\xff\xff\xff\x1b*9HWfu\x84\x93\xa2\xb1"
VIVO_STREAM_PREFIX = b"streamdata\xff\xd8\xff"
ONEPLUS_FOOTER_PREFIX = b"jxrs"
ONEPLUS_FOOTER_SIZE = 8
GOOGLE_MIN_SIGNATURE_READ_SIZE = 16

type TrailerKind = Literal["vivo", "oneplus", "google", "unknown"]
type TrailerPlanStatus = Literal["planned", "unsupported"]
type TrailerPayloadKind = Literal["binary", "json", "directory_json"]
type TrailerGroup2 = Literal["Image", "Preview", "Video", "Unknown"]
type TrailerRoute = Literal[
    "vivo_hdr_image",
    "vivo_json_info",
    "oneplus_json_info",
    "oneplus_named_payload",
    "google_motion_photo_video",
    "google_gain_map_image",
    "google_depth_map_image",
    "google_confidence_map_image",
    "google_dynamic_image",
    "google_dynamic_video",
    "preserve_unknown_payload",
]
type TrailerActionKind = Literal[
    "scan_for_trailer_start",
    "validate_vivo_footer",
    "route_vivo_hdr_image",
    "route_vivo_json_info",
    "detect_oneplus_footer",
    "parse_oneplus_directory_json",
    "route_oneplus_payload",
    "route_google_directory_item",
    "scan_google_item_signature",
    "preserve_payload",
    "plan_copy_existing_trailer",
    "plan_delete_existing_trailer",
    "block_requested_rewrite",
]
type TrailerRewriteOperation = Literal["copy_existing", "delete_existing", "rewrite_payload"]
type TrailerEmissionGateCode = Literal[
    "invalid_trailer_bounds",
    "unrecognized_trailer_signature",
    "vivo_trailer_start_not_found",
    "vivo_json_terminator_missing",
    "invalid_oneplus_footer_length",
    "malformed_oneplus_json",
    "oneplus_payload_out_of_range",
    "invalid_google_directory_item",
    "truncated_google_trailer_item",
    "google_trailer_signature_mismatch",
    "trailer_payload_rewrite_not_source_backed",
    "non_mutating_plan_requires_explicit_emission",
]

TRAILER_TABLE_SOURCE = "trailer.table"
VIVO_PROCESS_SOURCE = "vivo.process"
ONEPLUS_PROCESS_SOURCE = "oneplus.process"
GOOGLE_PROCESS_SOURCE = "google.process"
TRAILER_WRITE_GATE_SOURCE = "trailer.write.gate"

TRAILER_TRANSACTION_SOURCES = (
    TRAILER_TABLE_SOURCE,
    VIVO_PROCESS_SOURCE,
    ONEPLUS_PROCESS_SOURCE,
    GOOGLE_PROCESS_SOURCE,
    TRAILER_WRITE_GATE_SOURCE,
)


@dataclass(frozen=True)
class GoogleTrailerDirectoryItem:
    semantic: str
    mime: str
    length: int
    padding: int = 0


@dataclass(frozen=True)
class TrailerRewriteRequest:
    operation: TrailerRewriteOperation
    target: str = "all"


@dataclass(frozen=True)
class TrailerOutputEmissionGate:
    code: TrailerEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TrailerResponsibilityPlan:
    trailer_kind: TrailerKind
    source_tag: str
    tag_name: str
    group2: TrailerGroup2
    route: TrailerRoute
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TrailerPayloadPlan:
    trailer_kind: TrailerKind
    route: TrailerRoute
    source_tag: str
    tag_name: str
    group2: TrailerGroup2
    payload_kind: TrailerPayloadKind
    mime: str | None
    data_pos: int
    data_len: int
    payload: bytes
    preserve_original: bool
    known: bool
    evidence_ids: tuple[str, ...]

    @property
    def byte_range(self) -> tuple[int, int]:
        return (self.data_pos, self.data_pos + self.data_len)


@dataclass(frozen=True)
class TrailerSignaturePlan:
    trailer_kind: TrailerKind
    data_pos: int | None
    data_len: int | None
    signature: bytes
    signature_name: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TrailerActionPlan:
    kind: TrailerActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TrailerTransactionPlan:
    status: TrailerPlanStatus
    source_data: bytes
    trailer_kind: TrailerKind
    signature: TrailerSignaturePlan
    responsibilities: tuple[TrailerResponsibilityPlan, ...]
    payloads: tuple[TrailerPayloadPlan, ...]
    rewrite_requests: tuple[TrailerRewriteRequest, ...]
    actions: tuple[TrailerActionPlan, ...]
    output_emission_gates: tuple[TrailerOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Trailer transaction output is gated: {gate_codes}")
        return self.source_data


def build_trailer_transaction_plan(
    source_data: bytes,
    *,
    trailer_start: int = 0,
    trailer_offset_from_eof: int = 0,
    google_directory_items: tuple[GoogleTrailerDirectoryItem, ...] = (),
    rewrite_requests: tuple[TrailerRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> TrailerTransactionPlan:
    """Build a preserve-only generic trailer transaction plan from bytes."""

    trailer_end = len(source_data) - trailer_offset_from_eof
    if trailer_offset_from_eof < 0 or trailer_start < 0 or trailer_start > trailer_end:
        return _final_plan(
            status="unsupported",
            source_data=source_data,
            trailer_kind="unknown",
            signature=_empty_signature(),
            responsibilities=(),
            payloads=(),
            rewrite_requests=rewrite_requests,
            actions=(),
            gates=(
                TrailerOutputEmissionGate(
                    code="invalid_trailer_bounds",
                    reason="The requested trailer range cannot be derived from the input bytes.",
                    evidence_ids=(TRAILER_WRITE_GATE_SOURCE,),
                ),
            ),
            allow_output_emission=allow_output_emission,
        )

    vivo_plan = _plan_vivo(
        source_data,
        trailer_start,
        trailer_end,
        rewrite_requests,
        allow_output_emission,
    )
    if vivo_plan is not None:
        return vivo_plan

    oneplus_plan = _plan_oneplus(
        source_data,
        trailer_start,
        trailer_end,
        rewrite_requests,
        allow_output_emission,
    )
    if oneplus_plan is not None:
        return oneplus_plan

    if google_directory_items:
        return _plan_google(
            source_data,
            trailer_start,
            trailer_end,
            google_directory_items,
            rewrite_requests,
            allow_output_emission,
        )

    return _final_plan(
        status="unsupported",
        source_data=source_data,
        trailer_kind="unknown",
        signature=_empty_signature(),
        responsibilities=(),
        payloads=(),
        rewrite_requests=rewrite_requests,
        actions=(),
        gates=(
            TrailerOutputEmissionGate(
                code="unrecognized_trailer_signature",
                reason="Input did not match the source-backed Vivo, OnePlus, or Google routes.",
                evidence_ids=(TRAILER_TABLE_SOURCE,),
            ),
        ),
        allow_output_emission=allow_output_emission,
    )


plan_trailer_transaction = build_trailer_transaction_plan


def _plan_vivo(
    source_data: bytes,
    trailer_start: int,
    trailer_end: int,
    rewrite_requests: tuple[TrailerRewriteRequest, ...],
    allow_output_emission: bool,
) -> TrailerTransactionPlan | None:
    candidate = source_data[trailer_start:trailer_end]
    if not candidate.endswith(VIVO_FOOTER):
        return None

    stream_start = candidate.find(b"streamdata")
    json_start = candidate.find(b'vivo{"')
    starts = tuple(start for start in (stream_start, json_start) if start >= 0)
    if not starts:
        return _final_plan(
            status="unsupported",
            source_data=source_data,
            trailer_kind="vivo",
            signature=TrailerSignaturePlan(
                trailer_kind="vivo",
                data_pos=trailer_end - len(VIVO_FOOTER),
                data_len=len(VIVO_FOOTER),
                signature=VIVO_FOOTER,
                signature_name="Vivo footer",
                evidence_ids=(VIVO_PROCESS_SOURCE,),
            ),
            responsibilities=_responsibilities_for_kind("vivo"),
            payloads=(),
            rewrite_requests=rewrite_requests,
            actions=(
                TrailerActionPlan(
                    kind="validate_vivo_footer",
                    target="Vivo footer",
                    byte_range=(trailer_end - len(VIVO_FOOTER), trailer_end),
                    reason="The fixed Vivo trailer footer matched Trailer.pm.",
                    evidence_ids=(VIVO_PROCESS_SOURCE,),
                ),
            ),
            gates=(
                TrailerOutputEmissionGate(
                    code="vivo_trailer_start_not_found",
                    reason=(
                        "A Vivo footer was found, but no streamdata or vivo JSON start was found."
                    ),
                    evidence_ids=(VIVO_PROCESS_SOURCE,),
                ),
            ),
            allow_output_emission=allow_output_emission,
        )

    relative_start = min(starts)
    data_pos = trailer_start + relative_start
    trailer_payload = source_data[data_pos:trailer_end]
    payloads: list[TrailerPayloadPlan] = []
    actions: list[TrailerActionPlan] = [
        TrailerActionPlan(
            kind="scan_for_trailer_start",
            target="Vivo trailer",
            byte_range=(data_pos, trailer_end),
            reason="ProcessVivo scans for streamdata or vivo JSON to set DataPos and DirLen.",
            evidence_ids=(VIVO_PROCESS_SOURCE,),
        ),
        TrailerActionPlan(
            kind="validate_vivo_footer",
            target="Vivo footer",
            byte_range=(trailer_end - len(VIVO_FOOTER), trailer_end),
            reason="The fixed Vivo trailer footer matched Trailer.pm.",
            evidence_ids=(VIVO_PROCESS_SOURCE,),
        ),
    ]
    if trailer_payload.startswith(VIVO_STREAM_PREFIX):
        stream_end = trailer_payload.find(b"\xff\xd9streaminfo")
        if stream_end < 0:
            stream_end = trailer_payload.find(b"\xff\xd9streamcoun")
        if stream_end >= 0:
            payload = trailer_payload[10:stream_end]
            payloads.append(
                TrailerPayloadPlan(
                    trailer_kind="vivo",
                    route="vivo_hdr_image",
                    source_tag="HDRImage",
                    tag_name="HDRImage",
                    group2="Preview",
                    payload_kind="binary",
                    mime="image/jpeg",
                    data_pos=data_pos + 10,
                    data_len=len(payload),
                    payload=payload,
                    preserve_original=True,
                    known=True,
                    evidence_ids=(TRAILER_TABLE_SOURCE, VIVO_PROCESS_SOURCE),
                )
            )
            actions.append(
                TrailerActionPlan(
                    kind="route_vivo_hdr_image",
                    target="HDRImage",
                    byte_range=(data_pos + 10, data_pos + 10 + len(payload)),
                    reason="ProcessVivo routes the streamdata JPEG payload to HDRImage.",
                    evidence_ids=(VIVO_PROCESS_SOURCE,),
                )
            )
    vivo_json_relative = trailer_payload.find(b'vivo{"')
    gates: list[TrailerOutputEmissionGate] = []
    if vivo_json_relative >= 0:
        json_terminator = trailer_payload.find(b"}\x00", vivo_json_relative)
        if json_terminator < 0:
            gates.append(
                TrailerOutputEmissionGate(
                    code="vivo_json_terminator_missing",
                    reason="ProcessVivo found vivo JSON, but the JSON terminator was missing.",
                    evidence_ids=(VIVO_PROCESS_SOURCE,),
                )
            )
        else:
            json_len = json_terminator + 1 - vivo_json_relative
            json_pos = data_pos + vivo_json_relative
            payload = source_data[json_pos : json_pos + json_len]
            payloads.append(
                TrailerPayloadPlan(
                    trailer_kind="vivo",
                    route="vivo_json_info",
                    source_tag="JSONInfo",
                    tag_name="JSONInfo",
                    group2="Image",
                    payload_kind="json",
                    mime="application/json",
                    data_pos=json_pos,
                    data_len=json_len,
                    payload=payload,
                    preserve_original=True,
                    known=True,
                    evidence_ids=(TRAILER_TABLE_SOURCE, VIVO_PROCESS_SOURCE),
                )
            )
            actions.append(
                TrailerActionPlan(
                    kind="route_vivo_json_info",
                    target="JSONInfo",
                    byte_range=(json_pos, json_pos + json_len),
                    reason="ProcessVivo routes the vivo JSON slice to JSONInfo.",
                    evidence_ids=(VIVO_PROCESS_SOURCE,),
                )
            )

    actions.extend(_rewrite_actions_and_gates(rewrite_requests, gates))
    status: TrailerPlanStatus = "unsupported" if _has_structural_gate(gates) else "planned"
    return _final_plan(
        status=status,
        source_data=source_data,
        trailer_kind="vivo",
        signature=TrailerSignaturePlan(
            trailer_kind="vivo",
            data_pos=data_pos,
            data_len=trailer_end - data_pos,
            signature=VIVO_FOOTER,
            signature_name="Vivo footer",
            evidence_ids=(VIVO_PROCESS_SOURCE,),
        ),
        responsibilities=_responsibilities_for_kind("vivo"),
        payloads=tuple(payloads),
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        gates=tuple(gates),
        allow_output_emission=allow_output_emission,
    )


def _plan_oneplus(
    source_data: bytes,
    trailer_start: int,
    trailer_end: int,
    rewrite_requests: tuple[TrailerRewriteRequest, ...],
    allow_output_emission: bool,
) -> TrailerTransactionPlan | None:
    if trailer_end - trailer_start < ONEPLUS_FOOTER_SIZE:
        return None
    footer_start = trailer_end - ONEPLUS_FOOTER_SIZE
    footer = source_data[footer_start:trailer_end]
    if not _is_oneplus_footer(footer):
        return None

    jlen = int.from_bytes(footer[4:8], "little")
    signature = TrailerSignaturePlan(
        trailer_kind="oneplus",
        data_pos=footer_start,
        data_len=ONEPLUS_FOOTER_SIZE,
        signature=footer,
        signature_name="OnePlus jxrs footer",
        evidence_ids=(ONEPLUS_PROCESS_SOURCE,),
    )
    actions: list[TrailerActionPlan] = [
        TrailerActionPlan(
            kind="detect_oneplus_footer",
            target="OnePlus jxrs footer",
            byte_range=(footer_start, trailer_end),
            reason="ProcessOnePlus matches a jxrs footer and reads its little-endian length.",
            evidence_ids=(ONEPLUS_PROCESS_SOURCE,),
        )
    ]
    gates: list[TrailerOutputEmissionGate] = []
    if jlen <= ONEPLUS_FOOTER_SIZE or jlen >= trailer_end - trailer_start:
        gates.append(
            TrailerOutputEmissionGate(
                code="invalid_oneplus_footer_length",
                reason="The OnePlus jxrs length is outside the source-backed bounds.",
                evidence_ids=(ONEPLUS_PROCESS_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=source_data,
            trailer_kind="oneplus",
            signature=signature,
            responsibilities=_responsibilities_for_kind("oneplus"),
            payloads=(),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=tuple(gates),
            allow_output_emission=allow_output_emission,
        )

    json_pos = trailer_end - jlen
    json_len = jlen - ONEPLUS_FOOTER_SIZE
    raw_json = source_data[json_pos : json_pos + json_len]
    json_payload = raw_json.rstrip(b"\x00")
    payloads: list[TrailerPayloadPlan] = [
        TrailerPayloadPlan(
            trailer_kind="oneplus",
            route="oneplus_json_info",
            source_tag="JSONInfo",
            tag_name="JSONInfo",
            group2="Image",
            payload_kind="directory_json",
            mime="application/json",
            data_pos=json_pos,
            data_len=len(json_payload),
            payload=json_payload,
            preserve_original=True,
            known=True,
            evidence_ids=(TRAILER_TABLE_SOURCE, ONEPLUS_PROCESS_SOURCE),
        )
    ]
    actions.append(
        TrailerActionPlan(
            kind="parse_oneplus_directory_json",
            target="JSONInfo",
            byte_range=(json_pos, json_pos + len(json_payload)),
            reason="ProcessOnePlus strips trailing nulls and parses the JSON directory list.",
            evidence_ids=(ONEPLUS_PROCESS_SOURCE,),
        )
    )

    parsed = _load_json(json_payload)
    if not isinstance(parsed, list):
        gates.append(
            TrailerOutputEmissionGate(
                code="malformed_oneplus_json",
                reason="The OnePlus JSON directory did not parse to the array used by Trailer.pm.",
                evidence_ids=(ONEPLUS_PROCESS_SOURCE,),
            )
        )
    else:
        max_offset = 0
        for item in parsed:
            if not isinstance(item, dict):
                gates.append(
                    TrailerOutputEmissionGate(
                        code="malformed_oneplus_json",
                        reason="A OnePlus JSON directory entry was not a mapping.",
                        evidence_ids=(ONEPLUS_PROCESS_SOURCE,),
                    )
                )
                continue
            offset = _positive_int(item.get("offset"))
            name = item.get("name")
            length = _positive_int(item.get("length"))
            if offset is None or not isinstance(name, str) or length is None:
                continue
            max_offset = max(max_offset, offset)
            payload_start = trailer_end - jlen - offset
            payload_end = payload_start + length
            if payload_start < trailer_start or payload_end > json_pos:
                gates.append(
                    TrailerOutputEmissionGate(
                        code="oneplus_payload_out_of_range",
                        reason=f"OnePlus payload {name} points outside the trailer body.",
                        evidence_ids=(ONEPLUS_PROCESS_SOURCE,),
                    )
                )
                continue
            tag_name = _oneplus_tag_name(name)
            payload = source_data[payload_start:payload_end]
            payloads.append(
                TrailerPayloadPlan(
                    trailer_kind="oneplus",
                    route="oneplus_named_payload",
                    source_tag=name,
                    tag_name=tag_name,
                    group2="Image",
                    payload_kind="binary",
                    mime=None,
                    data_pos=payload_start,
                    data_len=length,
                    payload=payload,
                    preserve_original=True,
                    known=name in {"private.emptyspace", "watermark.device"},
                    evidence_ids=(TRAILER_TABLE_SOURCE, ONEPLUS_PROCESS_SOURCE),
                )
            )
            actions.append(
                TrailerActionPlan(
                    kind="route_oneplus_payload",
                    target=name,
                    byte_range=(payload_start, payload_end),
                    reason="ProcessOnePlus reads named payloads by offset and length.",
                    evidence_ids=(ONEPLUS_PROCESS_SOURCE,),
                )
            )
        if max_offset and trailer_end - (max_offset + jlen) < trailer_start:
            gates.append(
                TrailerOutputEmissionGate(
                    code="oneplus_payload_out_of_range",
                    reason="The OnePlus computed trailer length starts before TrailerStart.",
                    evidence_ids=(ONEPLUS_PROCESS_SOURCE,),
                )
            )

    actions.extend(_rewrite_actions_and_gates(rewrite_requests, gates))
    status: TrailerPlanStatus = "unsupported" if _has_structural_gate(gates) else "planned"
    data_len = jlen
    if len(payloads) > 1:
        earliest = min(payload.data_pos for payload in payloads)
        data_len = trailer_end - earliest
        signature = TrailerSignaturePlan(
            trailer_kind="oneplus",
            data_pos=earliest,
            data_len=data_len,
            signature=footer,
            signature_name="OnePlus jxrs footer",
            evidence_ids=(ONEPLUS_PROCESS_SOURCE,),
        )
    return _final_plan(
        status=status,
        source_data=source_data,
        trailer_kind="oneplus",
        signature=signature,
        responsibilities=_responsibilities_for_kind("oneplus"),
        payloads=tuple(payloads),
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        gates=tuple(gates),
        allow_output_emission=allow_output_emission,
    )


def _plan_google(
    source_data: bytes,
    trailer_start: int,
    trailer_end: int,
    directory_items: tuple[GoogleTrailerDirectoryItem, ...],
    rewrite_requests: tuple[TrailerRewriteRequest, ...],
    allow_output_emission: bool,
) -> TrailerTransactionPlan:
    actions: list[TrailerActionPlan] = []
    gates: list[TrailerOutputEmissionGate] = []
    payloads: list[TrailerPayloadPlan] = []
    pos = 0
    first_payload_pos: int | None = None

    for index, item in enumerate(directory_items[1:], start=1):
        remaining = trailer_end - trailer_start - pos
        if remaining < GOOGLE_MIN_SIGNATURE_READ_SIZE:
            break
        if item.length <= 0 or not item.semantic:
            gates.append(
                TrailerOutputEmissionGate(
                    code="invalid_google_directory_item",
                    reason=f"Google directory item {index} is missing a semantic or length.",
                    evidence_ids=(GOOGLE_PROCESS_SOURCE,),
                )
            )
            continue
        if item.length > remaining:
            gates.append(
                TrailerOutputEmissionGate(
                    code="truncated_google_trailer_item",
                    reason=(
                        f"Google directory item {item.semantic} exceeds remaining trailer bytes."
                    ),
                    evidence_ids=(GOOGLE_PROCESS_SOURCE,),
                )
            )
            break
        item_start = trailer_start + pos
        if not _matches_google_signature(source_data, item_start, trailer_end, item.mime):
            if pos:
                gates.append(
                    TrailerOutputEmissionGate(
                        code="google_trailer_signature_mismatch",
                        reason=f"Google item {item.semantic} did not match its MIME signature.",
                        evidence_ids=(GOOGLE_PROCESS_SOURCE,),
                    )
                )
                break
            signature_pos = _find_google_signature(source_data, item_start, trailer_end, item.mime)
            if signature_pos is None:
                gates.append(
                    TrailerOutputEmissionGate(
                        code="google_trailer_signature_mismatch",
                        reason=f"Google item {item.semantic} signature was not found.",
                        evidence_ids=(GOOGLE_PROCESS_SOURCE,),
                    )
                )
                break
            pos = signature_pos - trailer_start
            item_start = signature_pos
            remaining = trailer_end - item_start
            actions.append(
                TrailerActionPlan(
                    kind="scan_google_item_signature",
                    target=item.semantic,
                    byte_range=(signature_pos, trailer_end),
                    reason="ProcessGoogle scans from TrailerStart when the first item is shifted.",
                    evidence_ids=(GOOGLE_PROCESS_SOURCE,),
                )
            )
            if item.length > remaining:
                gates.append(
                    TrailerOutputEmissionGate(
                        code="truncated_google_trailer_item",
                        reason=(
                            f"Google directory item {item.semantic} exceeds shifted trailer bytes."
                        ),
                        evidence_ids=(GOOGLE_PROCESS_SOURCE,),
                    )
                )
                break
        payload = source_data[item_start : item_start + item.length]
        route, tag_name, group2, known = _google_route(item.semantic, item.mime)
        payloads.append(
            TrailerPayloadPlan(
                trailer_kind="google",
                route=route,
                source_tag=item.semantic,
                tag_name=tag_name,
                group2=group2,
                payload_kind="binary",
                mime=item.mime,
                data_pos=item_start,
                data_len=item.length,
                payload=payload,
                preserve_original=True,
                known=known,
                evidence_ids=(TRAILER_TABLE_SOURCE, GOOGLE_PROCESS_SOURCE),
            )
        )
        actions.append(
            TrailerActionPlan(
                kind="route_google_directory_item",
                target=item.semantic,
                byte_range=(item_start, item_start + item.length),
                reason="ProcessGoogle routes XMP directory items by semantic, MIME, and length.",
                evidence_ids=(GOOGLE_PROCESS_SOURCE,),
            )
        )
        first_payload_pos = (
            item_start if first_payload_pos is None else min(first_payload_pos, item_start)
        )
        pos += item.length + item.padding

    actions.extend(_rewrite_actions_and_gates(rewrite_requests, gates))
    status: TrailerPlanStatus = (
        "unsupported" if _has_structural_gate(gates) or not payloads else "planned"
    )
    if not payloads and not gates:
        gates.append(
            TrailerOutputEmissionGate(
                code="invalid_google_directory_item",
                reason="No Google trailer payloads were planned from the directory items.",
                evidence_ids=(GOOGLE_PROCESS_SOURCE,),
            )
        )
        status = "unsupported"
    data_pos = first_payload_pos
    data_len = pos if first_payload_pos is not None else None
    return _final_plan(
        status=status,
        source_data=source_data,
        trailer_kind="google",
        signature=TrailerSignaturePlan(
            trailer_kind="google",
            data_pos=data_pos,
            data_len=data_len,
            signature=b"",
            signature_name="Google XMP directory items",
            evidence_ids=(GOOGLE_PROCESS_SOURCE,),
        ),
        responsibilities=_responsibilities_for_kind("google"),
        payloads=tuple(payloads),
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        gates=tuple(gates),
        allow_output_emission=allow_output_emission,
    )


def _rewrite_actions_and_gates(
    rewrite_requests: tuple[TrailerRewriteRequest, ...],
    gates: list[TrailerOutputEmissionGate],
) -> tuple[TrailerActionPlan, ...]:
    actions: list[TrailerActionPlan] = []
    for request in rewrite_requests:
        if request.operation == "copy_existing":
            actions.append(
                TrailerActionPlan(
                    kind="plan_copy_existing_trailer",
                    target=request.target,
                    byte_range=None,
                    reason="Trailer.pm returns to ProcessTrailers for output-time copy handling.",
                    evidence_ids=(TRAILER_WRITE_GATE_SOURCE,),
                )
            )
            continue
        if request.operation == "delete_existing":
            actions.append(
                TrailerActionPlan(
                    kind="plan_delete_existing_trailer",
                    target=request.target,
                    byte_range=None,
                    reason="Trailer.pm returns to ProcessTrailers for output-time delete handling.",
                    evidence_ids=(TRAILER_WRITE_GATE_SOURCE,),
                )
            )
            continue
        gates.append(
            TrailerOutputEmissionGate(
                code="trailer_payload_rewrite_not_source_backed",
                reason="Trailer.pm does not provide a generic payload rewrite implementation.",
                evidence_ids=(TRAILER_WRITE_GATE_SOURCE,),
            )
        )
        actions.append(
            TrailerActionPlan(
                kind="block_requested_rewrite",
                target=request.target,
                byte_range=None,
                reason="Payload rewrites are blocked until a source-backed writer exists.",
                evidence_ids=(TRAILER_WRITE_GATE_SOURCE,),
            )
        )
    return tuple(actions)


def _final_plan(
    *,
    status: TrailerPlanStatus,
    source_data: bytes,
    trailer_kind: TrailerKind,
    signature: TrailerSignaturePlan,
    responsibilities: tuple[TrailerResponsibilityPlan, ...],
    payloads: tuple[TrailerPayloadPlan, ...],
    rewrite_requests: tuple[TrailerRewriteRequest, ...],
    actions: tuple[TrailerActionPlan, ...],
    gates: tuple[TrailerOutputEmissionGate, ...],
    allow_output_emission: bool,
) -> TrailerTransactionPlan:
    final_gates = list(gates)
    if status == "planned" and not allow_output_emission:
        final_gates.append(
            TrailerOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="Trailer transaction plans are preserve-only unless emission is allowed.",
                evidence_ids=(TRAILER_WRITE_GATE_SOURCE,),
            )
        )
    return TrailerTransactionPlan(
        status=status,
        source_data=source_data,
        trailer_kind=trailer_kind,
        signature=signature,
        responsibilities=responsibilities,
        payloads=payloads,
        rewrite_requests=rewrite_requests,
        actions=actions,
        output_emission_gates=tuple(final_gates),
        evidence_ids=TRAILER_TRANSACTION_SOURCES,
    )


def _responsibilities_for_kind(kind: TrailerKind) -> tuple[TrailerResponsibilityPlan, ...]:
    if kind == "vivo":
        return (
            TrailerResponsibilityPlan(
                "vivo",
                "HDRImage",
                "HDRImage",
                "Preview",
                "vivo_hdr_image",
                (TRAILER_TABLE_SOURCE, VIVO_PROCESS_SOURCE),
            ),
            TrailerResponsibilityPlan(
                "vivo",
                "JSONInfo",
                "JSONInfo",
                "Image",
                "vivo_json_info",
                (TRAILER_TABLE_SOURCE, VIVO_PROCESS_SOURCE),
            ),
        )
    if kind == "oneplus":
        return (
            TrailerResponsibilityPlan(
                "oneplus",
                "JSONInfo",
                "JSONInfo",
                "Image",
                "oneplus_json_info",
                (TRAILER_TABLE_SOURCE, ONEPLUS_PROCESS_SOURCE),
            ),
            TrailerResponsibilityPlan(
                "oneplus",
                "watermark.device",
                "Device",
                "Image",
                "oneplus_named_payload",
                (TRAILER_TABLE_SOURCE, ONEPLUS_PROCESS_SOURCE),
            ),
        )
    if kind == "google":
        return (
            TrailerResponsibilityPlan(
                "google",
                "MotionPhoto",
                "MotionPhotoVideo",
                "Video",
                "google_motion_photo_video",
                (TRAILER_TABLE_SOURCE, GOOGLE_PROCESS_SOURCE),
            ),
            TrailerResponsibilityPlan(
                "google",
                "GainMap",
                "GainMapImage",
                "Preview",
                "google_gain_map_image",
                (TRAILER_TABLE_SOURCE, GOOGLE_PROCESS_SOURCE),
            ),
            TrailerResponsibilityPlan(
                "google",
                "Depth",
                "DepthMapImage",
                "Preview",
                "google_depth_map_image",
                (TRAILER_TABLE_SOURCE, GOOGLE_PROCESS_SOURCE),
            ),
            TrailerResponsibilityPlan(
                "google",
                "Confidence",
                "ConfidenceMapImage",
                "Preview",
                "google_confidence_map_image",
                (TRAILER_TABLE_SOURCE, GOOGLE_PROCESS_SOURCE),
            ),
        )
    return ()


def _is_oneplus_footer(footer: bytes) -> bool:
    return (
        len(footer) == ONEPLUS_FOOTER_SIZE
        and footer.startswith(ONEPLUS_FOOTER_PREFIX)
        and footer[-1:] == b"\x00"
    )


def _load_json(payload: bytes) -> JsonValue | None:
    try:
        parsed: JsonValue = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError, UnicodeDecodeError:
        return None
    return parsed


def _positive_int(value: JsonValue | None) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _oneplus_tag_name(source_tag: str) -> str:
    if source_tag == "watermark.device":
        return "Device"
    if source_tag == "private.emptyspace":
        return "OnePlusTrailerLen"
    return _make_tag_name(source_tag)


def _google_route(
    semantic: str,
    mime: str,
) -> tuple[TrailerRoute, str, TrailerGroup2, bool]:
    if semantic == "MotionPhoto":
        return ("google_motion_photo_video", "MotionPhotoVideo", "Video", True)
    if semantic == "GainMap":
        return ("google_gain_map_image", "GainMapImage", "Preview", True)
    if semantic in {"Depth", "android/depthmap"}:
        return ("google_depth_map_image", "DepthMapImage", "Preview", True)
    if semantic in {"Confidence", "android/confidencemap"}:
        return ("google_confidence_map_image", "ConfidenceMapImage", "Preview", True)
    tag_name = _make_tag_name(semantic)
    if mime == "image/jpeg":
        return ("google_dynamic_image", f"{tag_name}Image", "Preview", False)
    if mime == "video/mp4":
        return ("google_dynamic_video", f"{tag_name}Video", "Video", False)
    return ("preserve_unknown_payload", tag_name, "Unknown", False)


def _make_tag_name(source_tag: str) -> str:
    words: list[str] = []
    current = ""
    for character in source_tag:
        if character.isalnum():
            current += character
        elif current:
            words.append(current)
            current = ""
    if current:
        words.append(current)
    if not words:
        return "Unknown"
    return "".join(word[:1].upper() + word[1:] for word in words)


def _matches_google_signature(data: bytes, start: int, end: int, mime: str) -> bool:
    if mime == "image/jpeg":
        return (
            start + 4 <= end
            and data[start : start + 3] == b"\xff\xd8\xff"
            and data[start + 3] in {0xDB, 0xE0, 0xE1}
        )
    if mime == "video/mp4":
        return (
            start + 12 <= end
            and data[start : start + 3] == b"\x00\x00\x00"
            and data[start + 4 : start + 8] == b"ftyp"
            and data[start + 8 : start + 12] in {b"mp42", b"isom"}
        )
    return False


def _find_google_signature(data: bytes, start: int, end: int, mime: str) -> int | None:
    for offset in range(start, max(start, end - 3)):
        if _matches_google_signature(data, offset, end, mime):
            return offset
    return None


def _has_structural_gate(gates: list[TrailerOutputEmissionGate]) -> bool:
    return any(gate.code != "non_mutating_plan_requires_explicit_emission" for gate in gates)


def _empty_signature() -> TrailerSignaturePlan:
    return TrailerSignaturePlan(
        trailer_kind="unknown",
        data_pos=None,
        data_len=None,
        signature=b"",
        signature_name="unknown",
        evidence_ids=(TRAILER_TABLE_SOURCE,),
    )
