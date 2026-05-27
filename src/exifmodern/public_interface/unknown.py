"""Bounded unknown-tag helpers for ExifTool-compatible public reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonObject
from exifmodern.provenance.public_interface import public_evidence_values

PROCESS_BINARYDATA_UNKNOWN_SCAN_LIMIT = 65_536
type ProcessBinaryDataByteOrder = Literal["big", "little"]


@dataclass(frozen=True)
class ProcessBinaryDataKnownSpan:
    start_index: int
    entry_count: int

    def contains(self, index: int) -> bool:
        return self.start_index <= index < self.start_index + self.entry_count


@dataclass(frozen=True, init=False)
class ProcessBinaryDataUnknownTablePolicy:
    tag_prefix: str
    first_entry: int
    increment: int
    known_spans: tuple[ProcessBinaryDataKnownSpan, ...]
    evidence_ids: tuple[str, ...]
    byte_order: ProcessBinaryDataByteOrder = "big"

    def __init__(
        self,
        tag_prefix: str,
        first_entry: int,
        increment: int,
        known_spans: tuple[ProcessBinaryDataKnownSpan, ...],
        evidence_ids: tuple[str, ...] | None = None,
        byte_order: ProcessBinaryDataByteOrder = "big",
    ) -> None:
        resolved_evidence_ids = _resolve_evidence_ids(evidence_ids)
        object.__setattr__(self, "tag_prefix", tag_prefix)
        object.__setattr__(self, "first_entry", first_entry)
        object.__setattr__(self, "increment", increment)
        object.__setattr__(self, "known_spans", known_spans)
        object.__setattr__(self, "evidence_ids", resolved_evidence_ids)
        object.__setattr__(self, "byte_order", byte_order)


@dataclass(frozen=True, init=False)
class ProcessBinaryDataUnknownReadTag:
    name: str
    value: int
    tag_id: int
    raw_payload: bytes
    evidence_ids: tuple[str, ...]

    def __init__(
        self,
        name: str,
        value: int,
        tag_id: int,
        raw_payload: bytes,
        evidence_ids: tuple[str, ...] | None = None,
    ) -> None:
        resolved_evidence_ids = _resolve_evidence_ids(evidence_ids)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "tag_id", tag_id)
        object.__setattr__(self, "raw_payload", raw_payload)
        object.__setattr__(self, "evidence_ids", resolved_evidence_ids)

    def to_json_value(self, *, include_evidence_ids: bool = False) -> JsonObject:
        payload: JsonObject = {
            "name": self.name,
            "value": self.value,
            "tag_id": self.tag_id,
            "raw_payload_byte_count": len(self.raw_payload),
        }
        if include_evidence_ids:
            payload["evidence_ids"] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True, init=False)
class ProcessBinaryDataUnknownReadResult:
    tags: tuple[ProcessBinaryDataUnknownReadTag, ...]
    diagnostics: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def __init__(
        self,
        tags: tuple[ProcessBinaryDataUnknownReadTag, ...],
        diagnostics: tuple[str, ...],
        evidence_ids: tuple[str, ...] | None = None,
    ) -> None:
        resolved_evidence_ids = _resolve_evidence_ids(evidence_ids)
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "evidence_ids", resolved_evidence_ids)

    def to_json_value(self, *, include_evidence_ids: bool = False) -> JsonObject:
        payload: JsonObject = {
            "tags": [
                tag.to_json_value(include_evidence_ids=include_evidence_ids) for tag in self.tags
            ],
            "diagnostics": list(self.diagnostics),
        }
        if include_evidence_ids:
            payload["evidence_ids"] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True, init=False)
class UnknownReadBlocker:
    code: str
    message: str
    evidence_ids: tuple[str, ...]

    def __init__(
        self,
        code: str,
        message: str,
        evidence_ids: tuple[str, ...] | None = None,
    ) -> None:
        resolved_evidence_ids = _resolve_evidence_ids(evidence_ids)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "evidence_ids", resolved_evidence_ids)

    def to_json_value(self, *, include_evidence_ids: bool = False) -> JsonObject:
        payload: JsonObject = {
            "code": self.code,
            "message": self.message,
        }
        if include_evidence_ids:
            payload["evidence_ids"] = list(public_evidence_values(self.evidence_ids))
        return payload


def _resolve_evidence_ids(evidence_ids: tuple[str, ...] | None) -> tuple[str, ...]:
    if evidence_ids is not None:
        return evidence_ids
    raise TypeError("missing required evidence_ids")


PROCESS_BINARYDATA_TABLE_LOCAL_BLOCKERS = (
    UnknownReadBlocker(
        code="process_binarydata_variable_format_blocked",
        message=(
            "ProcessBinaryData unknown discovery blocked for variable-length formats "
            "until table-local VarFormatData/format-count semantics are represented."
        ),
        evidence_ids=("public.unknown.process-binarydata-varsize",),
    ),
    UnknownReadBlocker(
        code="process_binarydata_masked_or_conditional_blocked",
        message=(
            "ProcessBinaryData unknown discovery blocked for masked or conditional "
            "entries until tag-specific mask/Condition/next-index behavior is represented."
        ),
        evidence_ids=("public.unknown.process-binarydata-entry-gates",),
    ),
    UnknownReadBlocker(
        code="process_binarydata_subdirectory_or_hook_blocked",
        message=(
            "ProcessBinaryData unknown discovery blocked for subdirectory, encrypted, "
            "or hook-backed tables until their package-local payload routing is represented."
        ),
        evidence_ids=("public.unknown.process-binarydata-subdirectory-hooks",),
    ),
)

REQUEST_ALL_EXTRA_BLOCKERS = (
    UnknownReadBlocker(
        code="requestall_volatile_extra_blocked",
        message=(
            "RequestAll=3 Extra volatile values blocked: ProcessingTime, Now, and "
            "NewGUID depend on runtime clock, process, sequence, or random state."
        ),
        evidence_ids=("public.unknown.requestall-volatile-extra",),
    ),
    UnknownReadBlocker(
        code="requestall_write_only_extra_blocked",
        message=(
            "RequestAll=3 Extra write-only values blocked: Geotag, Geotime, Geosync, "
            "and ForceWrite are write workflow controls, not safe read scalar fanout."
        ),
        evidence_ids=("public.unknown.requestall-write-only-extra",),
    ),
    UnknownReadBlocker(
        code="requestall_hash_or_binary_extra_blocked",
        message=(
            "RequestAll=3 Extra hash/binary values blocked unless explicitly requested "
            "or covered by a safe binary output policy: ImageDataHash, Trailer, and "
            "SphericalVideoXML."
        ),
        evidence_ids=("public.unknown.requestall-binary-extra",),
    ),
)


def process_binarydata_unknown_tags_from_payload(
    payload: bytes,
    policy: ProcessBinaryDataUnknownTablePolicy,
) -> ProcessBinaryDataUnknownReadResult:
    """Synthesize ExifTool Unknown>1 tags for safe fixed-width binary tables.

    This intentionally models only the bounded FIRST_ENTRY scan and known-span
    skipping from ProcessBinaryData. Variable formats, hooks and subdirectories
    must stay table-local until their source state is explicitly represented.
    """

    return process_binarydata_unknown_tags_from_payload_with_known_spans(
        payload,
        policy,
        policy.known_spans,
    )


def process_binarydata_unknown_tags_from_payload_with_known_spans(
    payload: bytes,
    policy: ProcessBinaryDataUnknownTablePolicy,
    known_spans: tuple[ProcessBinaryDataKnownSpan, ...],
) -> ProcessBinaryDataUnknownReadResult:
    """Synthesize unknown tags with table-local stateful known-entry spans."""

    if policy.increment <= 0:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=("ProcessBinaryData unknown discovery blocked: invalid increment.",),
            evidence_ids=policy.evidence_ids,
        )
    top_index = min(len(payload), PROCESS_BINARYDATA_UNKNOWN_SCAN_LIMIT) // policy.increment
    diagnostics: tuple[str, ...] = ()
    if len(payload) > PROCESS_BINARYDATA_UNKNOWN_SCAN_LIMIT:
        diagnostics = (
            "ProcessBinaryData unknown discovery limited to first 65536 bytes, "
            "matching ExifTool's unknown binary-table scan guard.",
        )
    return ProcessBinaryDataUnknownReadResult(
        tags=tuple(
            tag
            for index in range(policy.first_entry, top_index)
            if not process_binarydata_index_is_known(index, known_spans)
            for tag in (process_binarydata_unknown_tag(payload, policy, index),)
        ),
        diagnostics=diagnostics,
        evidence_ids=policy.evidence_ids,
    )


def process_binarydata_index_is_known(
    index: int,
    known_spans: tuple[ProcessBinaryDataKnownSpan, ...],
) -> bool:
    return any(span.contains(index) for span in known_spans)


def process_binarydata_unknown_tag(
    payload: bytes,
    policy: ProcessBinaryDataUnknownTablePolicy,
    index: int,
) -> ProcessBinaryDataUnknownReadTag:
    entry_start = index * policy.increment
    raw_payload = payload[entry_start : entry_start + policy.increment]
    return ProcessBinaryDataUnknownReadTag(
        name=f"{policy.tag_prefix}_0x{index:04x}",
        value=int.from_bytes(raw_payload, policy.byte_order),
        tag_id=index,
        raw_payload=raw_payload,
        evidence_ids=policy.evidence_ids,
    )
