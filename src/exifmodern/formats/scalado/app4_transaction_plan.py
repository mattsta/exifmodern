"""APP4 SCALADO transaction planning grounded in ExifTool Scalado.pm."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

SCALADO_PM_SOURCE_PATH = "lib/Image/ExifTool/Scalado.pm"
SCALADO_ENTRY_SIZE = 12
SCALADO_TAG_SIZE = 4
SCALADO_INT_SIZE = 4

type ScaladoPlanStatus = Literal["planned", "blocked"]
type ScaladoTagRoute = Literal["known", "unknown", "garbage_stop"]
type ScaladoValueMode = Literal["signed_int32", "absolute_or_undefined"]
type ScaladoEntryAction = Literal["preserve_known", "preserve_unknown", "stop_before_garbage"]
type ScaladoSpmoLengthMode = Literal[
    "not_present",
    "version_lt_5_trailer_length",
    "version_gte_5_directory_length",
]
type ScaladoEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_scalado_entry",
    "spmo_trailer_length_exceeds_payload",
    "spmo_directory_length_exceeds_payload",
    "scalado_rewrite_not_supported",
]
type ScaladoConvertedValue = int | None

SCALADO_MAIN_TABLE_SOURCE = "scalado.main.table"
SCALADO_PROCESS_SOURCE = "scalado.process"
SCALADO_READ_ONLY_SOURCE = "scalado.read.only"

SCALADO_TRANSACTION_SOURCES = (
    SCALADO_MAIN_TABLE_SOURCE,
    SCALADO_PROCESS_SOURCE,
    SCALADO_READ_ONLY_SOURCE,
)

KNOWN_TAGS: dict[bytes, tuple[str, ScaladoValueMode]] = {
    b"SPMO": ("DataLength", "signed_int32"),
    b"WDTH": ("PreviewImageWidth", "absolute_or_undefined"),
    b"HGHT": ("PreviewImageHeight", "absolute_or_undefined"),
    b"QUAL": ("PreviewQuality", "absolute_or_undefined"),
}
UNKNOWN_TAG_ALLOWED_BYTES = b"-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"


@dataclass(frozen=True)
class ScaladoApp4RewriteRequest:
    tag_name: str
    replacement_value: int | None = None


@dataclass(frozen=True)
class ScaladoOutputEmissionGate:
    code: ScaladoEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ScaladoApp4EntryPlan:
    index: int
    tag_code: str
    tag_name: str | None
    route: ScaladoTagRoute
    action: ScaladoEntryAction
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_entry: bytes
    raw_value: bytes
    version_unsigned: int
    raw_value_unsigned: int
    raw_value_signed: int
    converted_value: ScaladoConvertedValue
    value_mode: ScaladoValueMode
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ScaladoApp4StopPlan:
    offset: int
    raw_tag: bytes
    sanitized_name: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ScaladoSpmoBoundaryPlan:
    mode: ScaladoSpmoLengthMode
    entry_index: int | None
    version_unsigned: int | None
    value_unsigned: int | None
    effective_end: int
    trailer_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ScaladoApp4TransactionPlan:
    status: ScaladoPlanStatus
    source_payload: bytes
    entries: tuple[ScaladoApp4EntryPlan, ...]
    stop: ScaladoApp4StopPlan | None
    spmo_boundary: ScaladoSpmoBoundaryPlan
    parsed_range: tuple[int, int]
    unparsed_range: tuple[int, int] | None
    output_payload: bytes
    output_emission_gates: tuple[ScaladoOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def entry(self, tag_name: str) -> ScaladoApp4EntryPlan:
        for entry in self.entries:
            if entry.tag_name == tag_name:
                return entry
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"SCALADO APP4 transaction output is gated: {gate_codes}")
        return self.output_payload


def build_scalado_app4_transaction_plan(
    segment_payload: bytes,
    rewrite_requests: Sequence[ScaladoApp4RewriteRequest] = (),
    *,
    allow_output_emission: bool = False,
) -> ScaladoApp4TransactionPlan:
    entries: list[ScaladoApp4EntryPlan] = []
    gates: list[ScaladoOutputEmissionGate] = []
    pos = 0
    effective_end = len(segment_payload)
    stop: ScaladoApp4StopPlan | None = None
    spmo_mode: ScaladoSpmoLengthMode = "not_present"
    spmo_entry_index: int | None = None
    spmo_version: int | None = None
    spmo_value: int | None = None

    while pos + SCALADO_ENTRY_SIZE <= effective_end:
        raw_tag = segment_payload[pos : pos + SCALADO_TAG_SIZE]
        tag_code = raw_tag.decode("latin-1")
        tag_spec = KNOWN_TAGS.get(raw_tag)
        if tag_spec is None:
            sanitized_name = sanitize_unknown_tag_name(raw_tag)
            if not sanitized_name:
                stop = ScaladoApp4StopPlan(
                    offset=pos,
                    raw_tag=raw_tag,
                    sanitized_name=sanitized_name,
                    evidence_ids=(SCALADO_PROCESS_SOURCE,),
                )
                break
            tag_name = f"Scalado_{sanitized_name}"
            value_mode: ScaladoValueMode = "signed_int32"
            route: ScaladoTagRoute = "unknown"
            action: ScaladoEntryAction = "preserve_unknown"
            sources: tuple[str, ...] = (SCALADO_PROCESS_SOURCE,)
        else:
            tag_name, value_mode = tag_spec
            route = "known"
            action = "preserve_known"
            sources = (SCALADO_MAIN_TABLE_SOURCE, SCALADO_PROCESS_SOURCE)

        version_unsigned = read_u32(segment_payload, pos + 4)
        raw_value_unsigned = read_u32(segment_payload, pos + 8)
        raw_value_signed = read_i32(segment_payload, pos + 8)
        converted_value = convert_scalado_value(raw_value_signed, value_mode)
        entry = ScaladoApp4EntryPlan(
            index=len(entries),
            tag_code=tag_code,
            tag_name=tag_name,
            route=route,
            action=action,
            entry_range=(pos, pos + SCALADO_ENTRY_SIZE),
            value_range=(pos + 8, pos + 12),
            raw_entry=segment_payload[pos : pos + SCALADO_ENTRY_SIZE],
            raw_value=segment_payload[pos + 8 : pos + 12],
            version_unsigned=version_unsigned,
            raw_value_unsigned=raw_value_unsigned,
            raw_value_signed=raw_value_signed,
            converted_value=converted_value,
            value_mode=value_mode,
            evidence_ids=sources,
        )
        entries.append(entry)

        if raw_tag == b"SPMO":
            spmo_entry_index = entry.index
            spmo_version = version_unsigned
            spmo_value = raw_value_unsigned
            if version_unsigned < 5:
                spmo_mode = "version_lt_5_trailer_length"
                if raw_value_unsigned > effective_end:
                    gates.append(
                        ScaladoOutputEmissionGate(
                            code="spmo_trailer_length_exceeds_payload",
                            reason="SPMO version below 5 declares more trailer bytes than exist.",
                            evidence_ids=(SCALADO_PROCESS_SOURCE,),
                        )
                    )
                    effective_end = 0
                else:
                    effective_end -= raw_value_unsigned
            else:
                spmo_mode = "version_gte_5_directory_length"
                declared_end = raw_value_unsigned + SCALADO_ENTRY_SIZE
                if declared_end > len(segment_payload):
                    gates.append(
                        ScaladoOutputEmissionGate(
                            code="spmo_directory_length_exceeds_payload",
                            reason=(
                                "SPMO version 5 or newer declares a directory end past the "
                                "available APP4 payload."
                            ),
                            evidence_ids=(SCALADO_PROCESS_SOURCE,),
                        )
                    )
                effective_end = declared_end

        pos += SCALADO_ENTRY_SIZE

    if stop is None and 0 < effective_end - pos < SCALADO_ENTRY_SIZE:
        gates.append(
            ScaladoOutputEmissionGate(
                code="truncated_scalado_entry",
                reason="The effective SCALADO directory ends with fewer than 12 bytes remaining.",
                evidence_ids=(SCALADO_PROCESS_SOURCE,),
            )
        )

    if rewrite_requests:
        requested = ", ".join(request.tag_name for request in rewrite_requests)
        gates.append(
            ScaladoOutputEmissionGate(
                code="scalado_rewrite_not_supported",
                reason=f"Scalado.pm has no writer for requested tag updates: {requested}.",
                evidence_ids=(SCALADO_READ_ONLY_SOURCE,),
            )
        )

    if not allow_output_emission:
        code: ScaladoEmissionGateCode = "non_mutating_plan_requires_explicit_emission"
        gates.insert(
            0,
            ScaladoOutputEmissionGate(
                code=code,
                reason="Planner defaults preserve bytes and require explicit emission opt-in.",
                evidence_ids=SCALADO_TRANSACTION_SOURCES,
            ),
        )

    status: ScaladoPlanStatus = "blocked" if has_structural_gate(tuple(gates)) else "planned"
    parsed_end = pos
    bounded_effective_end = clamp_end(effective_end, len(segment_payload))
    trailer_range = build_trailer_range(spmo_mode, bounded_effective_end, len(segment_payload))
    spmo_boundary = ScaladoSpmoBoundaryPlan(
        mode=spmo_mode,
        entry_index=spmo_entry_index,
        version_unsigned=spmo_version,
        value_unsigned=spmo_value,
        effective_end=effective_end,
        trailer_range=trailer_range,
        evidence_ids=(SCALADO_PROCESS_SOURCE,),
    )

    return ScaladoApp4TransactionPlan(
        status=status,
        source_payload=segment_payload,
        entries=tuple(entries),
        stop=stop,
        spmo_boundary=spmo_boundary,
        parsed_range=(0, parsed_end),
        unparsed_range=build_unparsed_range(parsed_end, len(segment_payload)),
        output_payload=segment_payload,
        output_emission_gates=tuple(gates),
        evidence_ids=SCALADO_TRANSACTION_SOURCES,
    )


def read_u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + SCALADO_INT_SIZE], "big", signed=False)


def read_i32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + SCALADO_INT_SIZE], "big", signed=True)


def convert_scalado_value(value: int, mode: ScaladoValueMode) -> ScaladoConvertedValue:
    if mode == "absolute_or_undefined":
        if value == 0:
            return None
        return abs(value)
    return value


def sanitize_unknown_tag_name(raw_tag: bytes) -> str:
    return bytes(byte for byte in raw_tag if byte in UNKNOWN_TAG_ALLOWED_BYTES).decode("ascii")


def has_structural_gate(gates: tuple[ScaladoOutputEmissionGate, ...]) -> bool:
    structural_codes: tuple[ScaladoEmissionGateCode, ...] = (
        "truncated_scalado_entry",
        "spmo_trailer_length_exceeds_payload",
        "spmo_directory_length_exceeds_payload",
    )
    return any(gate.code in structural_codes for gate in gates)


def clamp_end(end: int, payload_length: int) -> int:
    if end < 0:
        return 0
    if end > payload_length:
        return payload_length
    return end


def build_trailer_range(
    spmo_mode: ScaladoSpmoLengthMode, effective_end: int, payload_length: int
) -> tuple[int, int] | None:
    if spmo_mode == "not_present" or effective_end >= payload_length:
        return None
    return (effective_end, payload_length)


def build_unparsed_range(parsed_end: int, payload_length: int) -> tuple[int, int] | None:
    if parsed_end >= payload_length:
        return None
    return (parsed_end, payload_length)
