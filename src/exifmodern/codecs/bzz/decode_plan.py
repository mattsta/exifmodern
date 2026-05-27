"""Source-backed BZZ decode capability planning.

This module models ExifTool's ``Image::ExifTool::BZZ`` boundaries without
porting the arithmetic decoder. It records initialization state, preserves the
compressed payload, exposes constants, and keeps decode execution behind an
explicit future native codec hook.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

FREQMAX = 4
CTXIDS = 3
MAXBLOCK = 4096
MAX_DECODED_BLOCK_SIZE = MAXBLOCK * 1024
FFZT_ENTRY_COUNT = 256
CONTEXT_ENTRY_COUNT = 300

type BzzNativeDecoder = Callable[[bytes, bool], bytes]
type BzzDecodePlanStatus = Literal["planned", "blocked", "decoded"]
type BzzDecodeGateCode = Literal[
    "decode_execution_not_requested",
    "native_bzz_decoder_not_available",
    "empty_payload",
    "truncated_initial_code_word",
    "negative_declared_decoded_size",
    "decoded_block_size_exceeds_maxblock",
]

BZZ_HEADER_SOURCE = "codec.bzz.header"
BZZ_CONSTANTS_SOURCE = "codec.bzz.constants"
BZZ_TABLE_INIT_SOURCE = "codec.bzz.table_init"
BZZ_INITIAL_CODE_SOURCE = "codec.bzz.initial_code"
BZZ_DECODE_ENTRY_SOURCE = "codec.bzz.decode_entry"
BZZ_DECODE_ALGORITHM_SOURCE = "codec.bzz.decode_algorithm"
BZZ_EOF_PADDING_SOURCE = "codec.bzz.eof_padding"
BZZ_NATIVE_CODEC_SOURCE = "codec.bzz.native_codec"

BZZ_EVIDENCE_IDS = (
    BZZ_HEADER_SOURCE,
    BZZ_CONSTANTS_SOURCE,
    BZZ_TABLE_INIT_SOURCE,
    BZZ_INITIAL_CODE_SOURCE,
    BZZ_DECODE_ENTRY_SOURCE,
    BZZ_DECODE_ALGORITHM_SOURCE,
    BZZ_EOF_PADDING_SOURCE,
    BZZ_NATIVE_CODEC_SOURCE,
)


@dataclass(frozen=True)
class BzzDecodeRequest:
    payload: bytes
    djvu_compatibility: bool = True
    execute_decode: bool = False
    declared_decoded_size: int | None = None


@dataclass(frozen=True)
class BzzConstantsPlan:
    freqmax: int
    ctxids: int
    maxblock: int
    max_decoded_block_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "ctxids": self.ctxids,
            "freqmax": self.freqmax,
            "max_decoded_block_size": self.max_decoded_block_size,
            "maxblock": self.maxblock,
        }


@dataclass(frozen=True)
class BzzInitializationPlan:
    payload_length: int
    initial_code: int
    initial_pos: int
    initial_byte: int
    initial_delay: int
    initial_scount: int
    initial_fence: int
    ffzt_entry_count: int
    context_entry_count: int
    djvu_compatibility: bool
    table_patch_applied: bool
    complete_initial_code_word: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "complete_initial_code_word": self.complete_initial_code_word,
            "context_entry_count": self.context_entry_count,
            "djvu_compatibility": self.djvu_compatibility,
            "ffzt_entry_count": self.ffzt_entry_count,
            "initial_byte": self.initial_byte,
            "initial_code": self.initial_code,
            "initial_delay": self.initial_delay,
            "initial_fence": self.initial_fence,
            "initial_pos": self.initial_pos,
            "initial_scount": self.initial_scount,
            "payload_length": self.payload_length,
            "table_patch_applied": self.table_patch_applied,
        }


@dataclass(frozen=True)
class BzzNativeCodecPlan:
    decoder_supplied: bool
    can_call_decoder: bool
    compatibility_mode_forwarded: bool
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_call_decoder": self.can_call_decoder,
            "compatibility_mode_forwarded": self.compatibility_mode_forwarded,
            "decoder_supplied": self.decoder_supplied,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BzzDecodeGate:
    code: BzzDecodeGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BzzDecodePlan:
    status: BzzDecodePlanStatus
    compressed_payload: bytes
    decoded_payload: bytes | None
    decode_requested: bool
    decode_executed: bool
    constants: BzzConstantsPlan
    initialization: BzzInitializationPlan
    native_codec: BzzNativeCodecPlan
    decode_gates: tuple[BzzDecodeGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def preserved_payload(self) -> bytes:
        return self.compressed_payload

    @property
    def can_execute_decode(self) -> bool:
        return self.decode_requested and not self.decode_gates

    def require_decoded_payload(self) -> bytes:
        if self.decoded_payload is None:
            gate_codes = ", ".join(gate.code for gate in self.decode_gates)
            raise ValueError(f"BZZ decode output is gated: {gate_codes}")
        return self.decoded_payload

    def to_json(self) -> JsonObject:
        return {
            "can_execute_decode": self.can_execute_decode,
            "compressed_payload_hex": self.compressed_payload.hex(),
            "constants": self.constants.to_json(),
            "decode_executed": self.decode_executed,
            "decode_gates": json_array(gate.to_json() for gate in self.decode_gates),
            "decode_requested": self.decode_requested,
            "decoded_payload_hex": (
                self.decoded_payload.hex() if self.decoded_payload is not None else None
            ),
            "initialization": self.initialization.to_json(),
            "native_codec": self.native_codec.to_json(),
            "status": self.status,
        }


def build_bzz_decode_plan(
    payload_or_request: bytes | BzzDecodeRequest,
    *,
    djvu_compatibility: bool | None = None,
    execute_decode: bool | None = None,
    declared_decoded_size: int | None = None,
    native_decoder: BzzNativeDecoder | None = None,
) -> BzzDecodePlan:
    request = normalize_request(
        payload_or_request,
        djvu_compatibility=djvu_compatibility,
        execute_decode=execute_decode,
        declared_decoded_size=declared_decoded_size,
    )
    initialization = build_initialization_plan(request.payload, request.djvu_compatibility)
    constants = BzzConstantsPlan(
        freqmax=FREQMAX,
        ctxids=CTXIDS,
        maxblock=MAXBLOCK,
        max_decoded_block_size=MAX_DECODED_BLOCK_SIZE,
        evidence_ids=(BZZ_CONSTANTS_SOURCE, BZZ_DECODE_ENTRY_SOURCE),
    )
    gates = build_decode_gates(request, native_decoder is not None)
    native_codec = BzzNativeCodecPlan(
        decoder_supplied=native_decoder is not None,
        can_call_decoder=request.execute_decode and native_decoder is not None and not gates,
        compatibility_mode_forwarded=True,
        reason="Native decoder callback accepts compressed bytes plus the DjVu compatibility flag.",
        evidence_ids=(BZZ_NATIVE_CODEC_SOURCE, BZZ_TABLE_INIT_SOURCE),
    )
    decoded_payload: bytes | None = None
    decode_executed = False
    if native_codec.can_call_decoder and native_decoder is not None:
        decoded_payload = native_decoder(request.payload, request.djvu_compatibility)
        decode_executed = True

    status = plan_status(gates, decode_executed)
    return BzzDecodePlan(
        status=status,
        compressed_payload=bytes(request.payload),
        decoded_payload=decoded_payload,
        decode_requested=request.execute_decode,
        decode_executed=decode_executed,
        constants=constants,
        initialization=initialization,
        native_codec=native_codec,
        decode_gates=gates,
        evidence_ids=BZZ_EVIDENCE_IDS,
    )


def normalize_request(
    payload_or_request: bytes | BzzDecodeRequest,
    *,
    djvu_compatibility: bool | None,
    execute_decode: bool | None,
    declared_decoded_size: int | None,
) -> BzzDecodeRequest:
    if isinstance(payload_or_request, BzzDecodeRequest):
        payload = payload_or_request.payload
        request_djvu_compatibility = payload_or_request.djvu_compatibility
        request_execute_decode = payload_or_request.execute_decode
        request_declared_size = payload_or_request.declared_decoded_size
    else:
        payload = payload_or_request
        request_djvu_compatibility = True
        request_execute_decode = False
        request_declared_size = None

    return BzzDecodeRequest(
        payload=bytes(payload),
        djvu_compatibility=(
            request_djvu_compatibility if djvu_compatibility is None else djvu_compatibility
        ),
        execute_decode=request_execute_decode if execute_decode is None else execute_decode,
        declared_decoded_size=(
            request_declared_size if declared_decoded_size is None else declared_decoded_size
        ),
    )


def build_initialization_plan(payload: bytes, djvu_compatibility: bool) -> BzzInitializationPlan:
    payload_length = len(payload)
    if payload_length >= 2:
        initial_code = int.from_bytes(payload[:2], "big")
        initial_pos = 2
    elif payload_length == 1:
        initial_code = (payload[0] << 8) | 0xFF
        initial_pos = 1
    else:
        initial_code = 0xFFFF
        initial_pos = 0

    return BzzInitializationPlan(
        payload_length=payload_length,
        initial_code=initial_code,
        initial_pos=initial_pos,
        initial_byte=initial_code & 0xFF,
        initial_delay=25,
        initial_scount=0,
        initial_fence=0x7FFF if initial_code >= 0x8000 else initial_code,
        ffzt_entry_count=FFZT_ENTRY_COUNT,
        context_entry_count=CONTEXT_ENTRY_COUNT,
        djvu_compatibility=djvu_compatibility,
        table_patch_applied=not djvu_compatibility,
        complete_initial_code_word=payload_length >= 2,
        evidence_ids=(BZZ_TABLE_INIT_SOURCE, BZZ_INITIAL_CODE_SOURCE),
    )


def build_decode_gates(
    request: BzzDecodeRequest,
    native_decoder_supplied: bool,
) -> tuple[BzzDecodeGate, ...]:
    gates: list[BzzDecodeGate] = []
    if not request.payload:
        gates.append(
            BzzDecodeGate(
                code="empty_payload",
                reason=(
                    "The planner will not execute BZZ decoding from an empty payload; "
                    "BZZ.pm would initialize with 0xffff and then rely on EOF padding."
                ),
                evidence_ids=(BZZ_INITIAL_CODE_SOURCE, BZZ_EOF_PADDING_SOURCE),
            )
        )
    elif len(request.payload) == 1:
        gates.append(
            BzzDecodeGate(
                code="truncated_initial_code_word",
                reason=(
                    "The payload has only one byte of the initial 16-bit code word; "
                    "BZZ.pm pads the low byte with 0xff."
                ),
                evidence_ids=(BZZ_INITIAL_CODE_SOURCE,),
            )
        )

    if request.declared_decoded_size is not None:
        if request.declared_decoded_size < 0:
            gates.append(
                BzzDecodeGate(
                    code="negative_declared_decoded_size",
                    reason="A decoded block-size hint cannot be negative.",
                    evidence_ids=(BZZ_DECODE_ENTRY_SOURCE,),
                )
            )
        elif request.declared_decoded_size > MAX_DECODED_BLOCK_SIZE:
            gates.append(
                BzzDecodeGate(
                    code="decoded_block_size_exceeds_maxblock",
                    reason="BZZ.pm rejects decoded block sizes above MAXBLOCK*1024.",
                    evidence_ids=(BZZ_CONSTANTS_SOURCE, BZZ_DECODE_ENTRY_SOURCE),
                )
            )

    if not request.execute_decode:
        gates.append(
            BzzDecodeGate(
                code="decode_execution_not_requested",
                reason="Planning preserves compressed bytes and does not run a decoder by default.",
                evidence_ids=(BZZ_DECODE_ALGORITHM_SOURCE,),
            )
        )
    elif not native_decoder_supplied:
        gates.append(
            BzzDecodeGate(
                code="native_bzz_decoder_not_available",
                reason=(
                    "Full arithmetic decoding is intentionally deferred until a native codec "
                    "callback is supplied."
                ),
                evidence_ids=(BZZ_DECODE_ALGORITHM_SOURCE, BZZ_NATIVE_CODEC_SOURCE),
            )
        )

    return tuple(gates)


def plan_status(gates: tuple[BzzDecodeGate, ...], decode_executed: bool) -> BzzDecodePlanStatus:
    if decode_executed:
        return "decoded"
    blocker_codes = {
        "empty_payload",
        "truncated_initial_code_word",
        "negative_declared_decoded_size",
        "decoded_block_size_exceeds_maxblock",
    }
    if any(gate.code in blocker_codes for gate in gates):
        return "blocked"
    return "planned"


def json_array(values: Iterable[JsonValue]) -> JsonArray:
    return [value for value in values]
