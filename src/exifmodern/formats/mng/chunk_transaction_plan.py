"""Source-backed, non-mutating MNG/JNG chunk transaction plans."""

from __future__ import annotations

import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

MNG_SIGNATURE = b"\x8aMNG\r\n\x1a\n"
JNG_SIGNATURE = b"\x8bJNG\r\n\x1a\n"
MNG_CHUNK_HEADER_SIZE = 8
MNG_CRC_SIZE = 4
MNG_MAX_EXIFTOOL_CHUNK_LENGTH = 0x7FFFFFFF

MNG_HEADER_CHUNK_TYPE = b"MHDR"
MNG_END_CHUNK_TYPE = b"MEND"
JNG_HEADER_CHUNK_TYPE = b"JHDR"
JNG_END_CHUNK_TYPE = b"IEND"
TEXT_CHUNK_TYPES = frozenset((b"tEXt", b"zTXt", b"iTXt"))
PNG_METADATA_CHUNK_TYPES = frozenset((b"eXIf", b"zXIf"))
IMAGE_DATA_CHUNK_TYPES = frozenset((b"IDAT", b"JDAT", b"JDAA", b"IJNG", b"IPNG"))
XMP_ITXT_KEYWORD = "XML:com.adobe.xmp"

type MngFileType = Literal["MNG", "JNG"]
type MngPlanStatus = Literal["planned", "unsupported"]
type MngResponsibilityKind = Literal[
    "mng_control",
    "jng_control",
    "textual_metadata",
    "png_metadata",
    "image_data",
    "end",
    "unknown",
]
type MngHandlingKind = Literal[
    "structured_subdirectory",
    "binary_payload",
    "value_conversion",
    "png_physical_pixel",
    "textual_payload",
    "png_superset_metadata",
    "image_payload",
    "container_end",
    "preserve_unknown",
]
type MngActionKind = Literal["copy", "preserve_trailer", "recompute_crc", "block_rewrite"]
type MngEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_mng_signature",
    "unsupported_mng_signature",
    "truncated_mng_chunk_header",
    "truncated_mng_chunk_payload",
    "invalid_mng_chunk_size",
    "missing_mng_header",
    "mng_header_not_first",
    "missing_mng_end",
    "bad_crc",
    "unsupported_rewrite_request",
]


PNG_LOOKUP_SOURCE = "png_lookup"
PNG_PROCESS_SOURCE = "png_process"
PNG_CHUNK_ENUMERATION_SOURCE = "png_chunk_enumeration"
PNG_CRC_SOURCE = "png_crc"
PNG_WRITE_CRC_VALIDATION_SOURCE = "png_write_crc_validation"
PNG_TRAILER_SOURCE = "png_trailer"
MNG_TABLE_SOURCE = "mng_table"
MNG_SUPERSET_SOURCE = "mng_superset"
MNG_HEADER_SOURCE = "mng_header"
JNG_HEADER_SOURCE = "jng_header"
MNG_BINARY_SOURCE = "mng_binary"
MNG_VALUE_CONVERSION_SOURCE = "mng_value_conversion"
MNG_REWRITE_BOUNDARY_SOURCE = "mng_rewrite_boundary"

STRUCTURED_CHUNK_NAMES: dict[bytes, str] = {
    b"BACK": "Background",
    b"BASI": "BasisObject",
    b"CLIP": "ClipObjects",
    b"CLON": "CloneObject",
    b"DEFI": "DefineObject",
    b"DHDR": "DeltaPNGHeader",
    b"eXPi": "ExportImage",
    b"fPRI": "FramePriority",
    b"JHDR": "JNGHeader",
    b"LOOP": "Loop",
    b"MAGN": "MagnifyObject",
    b"MHDR": "MNGHeader",
    b"MOVE": "MoveObjects",
    b"PAST": "PasteImage",
    b"PROM": "PromoteParent",
    b"SHOW": "ShowObjects",
    b"TERM": "TerminationAction",
}
BINARY_CHUNK_NAMES: dict[bytes, str] = {
    b"DBYK": "DropByKeyword",
    b"FRAM": "Frame",
    b"nEED": "ResourcesNeeded",
    b"ORDR": "OrderingRestrictions",
    b"PPLT": "PartialPalette",
    b"SAVE": "SaveObjects",
}
VALUE_CONVERSION_CHUNK_NAMES: dict[bytes, str] = {
    b"DISC": "DiscardObjects",
    b"DROP": "DropChunks",
    b"SEEK": "SeekPoint",
}


@dataclass(frozen=True)
class MngRewriteRequest:
    """A requested metadata rewrite that this package-local planner must block."""

    description: str


@dataclass(frozen=True)
class MngSignaturePlan:
    signature: bytes
    file_type: MngFileType | None
    header_chunk_type: bytes | None
    end_chunk_type: bytes | None
    is_supported_mng_family: bool
    reason: MngEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "end_chunk_type": ascii_chunk_id(self.end_chunk_type),
            "file_type": self.file_type,
            "header_chunk_type": ascii_chunk_id(self.header_chunk_type),
            "is_supported_mng_family": self.is_supported_mng_family,
            "reason": self.reason,
            "signature": self.signature.hex(),
        }


@dataclass(frozen=True)
class MngChunkPlan:
    index: int
    chunk_type: bytes
    chunk_start_offset: int
    payload_offset: int
    payload_length: int
    crc_offset: int
    end_offset: int
    payload: bytes
    stored_crc: int
    calculated_crc: int
    crc_matches: bool
    evidence_ids: tuple[str, ...]

    @property
    def encoded_length(self) -> int:
        return MNG_CHUNK_HEADER_SIZE + self.payload_length + MNG_CRC_SIZE

    def to_output_chunk(self) -> MngOutputChunk:
        return MngOutputChunk(self.chunk_type, self.payload)

    def to_json(self) -> JsonObject:
        return {
            "calculated_crc": self.calculated_crc,
            "chunk_start_offset": self.chunk_start_offset,
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "crc_matches": self.crc_matches,
            "crc_offset": self.crc_offset,
            "encoded_length": self.encoded_length,
            "end_offset": self.end_offset,
            "index": self.index,
            "payload_length": self.payload_length,
            "payload_offset": self.payload_offset,
            "stored_crc": self.stored_crc,
        }


@dataclass(frozen=True)
class MngResponsibilityPlan:
    chunk_index: int
    chunk_type: bytes
    responsibility_kind: MngResponsibilityKind
    handling_kind: MngHandlingKind
    tag_name: str | None
    keyword: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_index": self.chunk_index,
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "handling_kind": self.handling_kind,
            "keyword": self.keyword,
            "responsibility_kind": self.responsibility_kind,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class MngOutputChunk:
    chunk_type: bytes
    payload: bytes


@dataclass(frozen=True)
class MngChunkActionPlan:
    kind: MngActionKind
    chunk_type: bytes
    source_index: int | None
    output_index: int | None
    payload_length: int
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "kind": self.kind,
            "output_index": self.output_index,
            "payload_length": self.payload_length,
            "reason": self.reason,
            "source_index": self.source_index,
        }


@dataclass(frozen=True)
class MngOutputEmissionGate:
    code: MngEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MngOutputSizePlan:
    input_file_size: int
    planned_file_size: int | None
    trailer_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "input_file_size": self.input_file_size,
            "planned_file_size": self.planned_file_size,
            "trailer_size": self.trailer_size,
        }


@dataclass(frozen=True)
class MngChunkTransactionPlan:
    status: MngPlanStatus
    signature: MngSignaturePlan
    chunks: tuple[MngChunkPlan, ...]
    responsibilities: tuple[MngResponsibilityPlan, ...]
    actions: tuple[MngChunkActionPlan, ...]
    output_chunks: tuple[MngOutputChunk, ...]
    output_size: MngOutputSizePlan
    output_emission_gates: tuple[MngOutputEmissionGate, ...]
    trailer: bytes
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"MNG/JNG chunk transaction output is gated: {gate_codes}")
        file_type = self.signature.file_type
        if file_type is None:
            raise ValueError("MNG/JNG chunk transaction output is gated: unsupported_mng_signature")
        return encode_mng_chunks(file_type, self.output_chunks, trailer=self.trailer)

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "chunks": json_object_array(chunk.to_json() for chunk in self.chunks),
            "output_chunk_types": [
                ascii_chunk_id(chunk.chunk_type) for chunk in self.output_chunks
            ],
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "output_size": self.output_size.to_json(),
            "responsibilities": json_object_array(
                responsibility.to_json() for responsibility in self.responsibilities
            ),
            "signature": self.signature.to_json(),
            "status": self.status,
            "trailer_size": len(self.trailer),
        }


def build_mng_chunk_transaction_plan(
    mng_data: bytes,
    *,
    rewrite_request: MngRewriteRequest | None = None,
    allow_output_emission: bool = False,
    validate_crc: bool = True,
) -> MngChunkTransactionPlan:
    """Build a non-mutating MNG/JNG chunk transaction plan."""

    signature = build_mng_signature_plan(mng_data)
    gates: list[MngOutputEmissionGate] = []
    if signature.reason is not None:
        gates.append(
            MngOutputEmissionGate(
                code=signature.reason,
                reason="Input does not satisfy the MNG/JNG signature gate.",
                evidence_ids=(PNG_LOOKUP_SOURCE, PNG_PROCESS_SOURCE),
            )
        )
        return _unsupported_plan(signature, mng_data, gates)

    chunks, trailer, parse_gates = enumerate_mng_chunks(mng_data, signature)
    gates.extend(parse_gates)
    if not parse_gates:
        gates.extend(_structural_gates(chunks, signature))
    if validate_crc and not parse_gates:
        gates.extend(_crc_gates(chunks))

    responsibilities = tuple(_responsibility_for_chunk(chunk) for chunk in chunks)
    output_chunks = tuple(chunk.to_output_chunk() for chunk in chunks)
    actions = tuple(_copy_action(chunk) for chunk in chunks)

    if trailer:
        actions = (
            *actions,
            MngChunkActionPlan(
                kind="preserve_trailer",
                chunk_type=b"TRLR",
                source_index=None,
                output_index=None,
                payload_length=len(trailer),
                reason="Preserve existing bytes after the MNG/JNG end chunk.",
                evidence_ids=(PNG_TRAILER_SOURCE,),
            ),
        )

    if rewrite_request is not None:
        gates.append(
            MngOutputEmissionGate(
                code="unsupported_rewrite_request",
                reason=(
                    "MNG.pm declares read responsibilities, so this slice blocks "
                    f"rewrite request: {rewrite_request.description}"
                ),
                evidence_ids=(MNG_REWRITE_BOUNDARY_SOURCE,),
            )
        )
        actions = (
            *actions,
            MngChunkActionPlan(
                kind="block_rewrite",
                chunk_type=b"MNG*",
                source_index=None,
                output_index=None,
                payload_length=0,
                reason="Block rewrite request at the MNG.pm read-table boundary.",
                evidence_ids=(MNG_REWRITE_BOUNDARY_SOURCE,),
            ),
        )

    for output_index, output_chunk in enumerate(output_chunks):
        actions = (
            *actions,
            MngChunkActionPlan(
                kind="recompute_crc",
                chunk_type=output_chunk.chunk_type,
                source_index=None,
                output_index=output_index,
                payload_length=len(output_chunk.payload),
                reason="MNG/JNG output CRC is calculated over chunk name and payload.",
                evidence_ids=(PNG_CRC_SOURCE,),
            ),
        )

    if not allow_output_emission:
        gates.append(
            MngOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason=(
                    "MNG/JNG transaction plans are non-mutating unless emission is "
                    "explicitly allowed."
                ),
                evidence_ids=(PNG_PROCESS_SOURCE,),
            )
        )

    status: MngPlanStatus = "unsupported" if parse_gates else "planned"
    planned_size = (
        len(encode_mng_chunks(signature.file_type, output_chunks, trailer=trailer))
        if signature.file_type is not None and output_chunks
        else None
    )
    sources = unique_sources(
        (
            PNG_LOOKUP_SOURCE,
            PNG_PROCESS_SOURCE,
            PNG_CHUNK_ENUMERATION_SOURCE,
            PNG_CRC_SOURCE,
            PNG_WRITE_CRC_VALIDATION_SOURCE,
            PNG_TRAILER_SOURCE,
            MNG_TABLE_SOURCE,
            MNG_SUPERSET_SOURCE,
            MNG_HEADER_SOURCE,
            JNG_HEADER_SOURCE,
            MNG_BINARY_SOURCE,
            MNG_VALUE_CONVERSION_SOURCE,
            MNG_REWRITE_BOUNDARY_SOURCE,
            *(source for item in responsibilities for source in item.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return MngChunkTransactionPlan(
        status=status,
        signature=signature,
        chunks=chunks,
        responsibilities=responsibilities,
        actions=actions,
        output_chunks=output_chunks,
        output_size=MngOutputSizePlan(
            input_file_size=len(mng_data),
            planned_file_size=planned_size,
            trailer_size=len(trailer),
            evidence_ids=(PNG_TRAILER_SOURCE, PNG_CRC_SOURCE),
        ),
        output_emission_gates=unique_gates(tuple(gates)),
        trailer=trailer,
        evidence_ids=sources,
    )


plan_mng_chunk_transaction = build_mng_chunk_transaction_plan


def build_mng_signature_plan(mng_data: bytes) -> MngSignaturePlan:
    if len(mng_data) < len(MNG_SIGNATURE):
        return MngSignaturePlan(
            signature=mng_data,
            file_type=None,
            header_chunk_type=None,
            end_chunk_type=None,
            is_supported_mng_family=False,
            reason="truncated_mng_signature",
            evidence_ids=(PNG_LOOKUP_SOURCE, PNG_PROCESS_SOURCE),
        )

    signature = mng_data[: len(MNG_SIGNATURE)]
    if signature == MNG_SIGNATURE:
        return MngSignaturePlan(
            signature=signature,
            file_type="MNG",
            header_chunk_type=MNG_HEADER_CHUNK_TYPE,
            end_chunk_type=MNG_END_CHUNK_TYPE,
            is_supported_mng_family=True,
            reason=None,
            evidence_ids=(PNG_LOOKUP_SOURCE, PNG_PROCESS_SOURCE),
        )
    if signature == JNG_SIGNATURE:
        return MngSignaturePlan(
            signature=signature,
            file_type="JNG",
            header_chunk_type=JNG_HEADER_CHUNK_TYPE,
            end_chunk_type=JNG_END_CHUNK_TYPE,
            is_supported_mng_family=True,
            reason=None,
            evidence_ids=(PNG_LOOKUP_SOURCE, PNG_PROCESS_SOURCE),
        )
    return MngSignaturePlan(
        signature=signature,
        file_type=None,
        header_chunk_type=None,
        end_chunk_type=None,
        is_supported_mng_family=False,
        reason="unsupported_mng_signature",
        evidence_ids=(PNG_LOOKUP_SOURCE, PNG_PROCESS_SOURCE),
    )


def enumerate_mng_chunks(
    mng_data: bytes,
    signature: MngSignaturePlan,
) -> tuple[tuple[MngChunkPlan, ...], bytes, tuple[MngOutputEmissionGate, ...]]:
    chunks: list[MngChunkPlan] = []
    gates: list[MngOutputEmissionGate] = []
    offset = len(MNG_SIGNATURE)
    while offset < len(mng_data):
        if len(mng_data) - offset < MNG_CHUNK_HEADER_SIZE:
            gates.append(
                MngOutputEmissionGate(
                    code="truncated_mng_chunk_header",
                    reason="Input ended before a complete MNG/JNG chunk header could be read.",
                    evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(chunks), b"", tuple(gates)

        chunk_start = offset
        payload_length = int.from_bytes(mng_data[offset : offset + 4], "big")
        chunk_type = mng_data[offset + 4 : offset + 8]
        offset += MNG_CHUNK_HEADER_SIZE
        if payload_length > MNG_MAX_EXIFTOOL_CHUNK_LENGTH:
            gates.append(
                MngOutputEmissionGate(
                    code="invalid_mng_chunk_size",
                    reason=(
                        f"{ascii_chunk_id(chunk_type)} declares a chunk length larger "
                        "than ExifTool accepts."
                    ),
                    evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(chunks), b"", tuple(gates)

        payload_end = offset + payload_length
        crc_end = payload_end + MNG_CRC_SIZE
        if crc_end > len(mng_data):
            gates.append(
                MngOutputEmissionGate(
                    code="truncated_mng_chunk_payload",
                    reason=f"{ascii_chunk_id(chunk_type)} payload or CRC is truncated.",
                    evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(chunks), b"", tuple(gates)

        payload = mng_data[offset:payload_end]
        stored_crc = int.from_bytes(mng_data[payload_end:crc_end], "big")
        calculated_crc = mng_crc(chunk_type, payload)
        chunks.append(
            MngChunkPlan(
                index=len(chunks),
                chunk_type=chunk_type,
                chunk_start_offset=chunk_start,
                payload_offset=offset,
                payload_length=payload_length,
                crc_offset=payload_end,
                end_offset=crc_end,
                payload=payload,
                stored_crc=stored_crc,
                calculated_crc=calculated_crc,
                crc_matches=stored_crc == calculated_crc,
                evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE, PNG_CRC_SOURCE),
            )
        )
        offset = crc_end
        if chunk_type == signature.end_chunk_type:
            return tuple(chunks), mng_data[offset:], tuple(gates)
    return tuple(chunks), b"", tuple(gates)


def encode_mng_chunks(
    file_type: MngFileType,
    chunks: Iterable[MngOutputChunk],
    *,
    trailer: bytes = b"",
) -> bytes:
    encoded = bytearray(MNG_SIGNATURE if file_type == "MNG" else JNG_SIGNATURE)
    for chunk in chunks:
        encoded.extend(len(chunk.payload).to_bytes(4, "big"))
        encoded.extend(chunk.chunk_type)
        encoded.extend(chunk.payload)
        encoded.extend(mng_crc(chunk.chunk_type, chunk.payload).to_bytes(4, "big"))
    encoded.extend(trailer)
    return bytes(encoded)


def mng_crc(chunk_type: bytes, payload: bytes) -> int:
    return zlib.crc32(chunk_type + payload) & 0xFFFFFFFF


def _unsupported_plan(
    signature: MngSignaturePlan,
    mng_data: bytes,
    gates: list[MngOutputEmissionGate],
) -> MngChunkTransactionPlan:
    return MngChunkTransactionPlan(
        status="unsupported",
        signature=signature,
        chunks=(),
        responsibilities=(),
        actions=(),
        output_chunks=(),
        output_size=MngOutputSizePlan(
            input_file_size=len(mng_data),
            planned_file_size=None,
            trailer_size=0,
            evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
        ),
        output_emission_gates=unique_gates(tuple(gates)),
        trailer=b"",
        evidence_ids=unique_sources(
            (
                PNG_LOOKUP_SOURCE,
                PNG_PROCESS_SOURCE,
                PNG_CHUNK_ENUMERATION_SOURCE,
                *(source for gate in gates for source in gate.evidence_ids),
            )
        ),
    )


def _structural_gates(
    chunks: tuple[MngChunkPlan, ...],
    signature: MngSignaturePlan,
) -> tuple[MngOutputEmissionGate, ...]:
    gates: list[MngOutputEmissionGate] = []
    if not chunks:
        gates.append(
            MngOutputEmissionGate(
                code="missing_mng_header",
                reason="MNG/JNG contains no chunks, so the expected header is missing.",
                evidence_ids=(PNG_LOOKUP_SOURCE, PNG_PROCESS_SOURCE),
            )
        )
        return tuple(gates)
    if chunks[0].chunk_type != signature.header_chunk_type:
        gates.append(
            MngOutputEmissionGate(
                code="mng_header_not_first",
                reason=(
                    f"MNG/JNG does not start with {ascii_chunk_id(signature.header_chunk_type)}."
                ),
                evidence_ids=(PNG_LOOKUP_SOURCE, PNG_PROCESS_SOURCE),
            )
        )
    if not any(chunk.chunk_type == signature.end_chunk_type for chunk in chunks):
        gates.append(
            MngOutputEmissionGate(
                code="missing_mng_end",
                reason=f"MNG/JNG has no {ascii_chunk_id(signature.end_chunk_type)} chunk.",
                evidence_ids=(PNG_TRAILER_SOURCE,),
            )
        )
    return tuple(gates)


def _crc_gates(chunks: tuple[MngChunkPlan, ...]) -> tuple[MngOutputEmissionGate, ...]:
    return tuple(
        MngOutputEmissionGate(
            code="bad_crc",
            reason=f"{ascii_chunk_id(chunk.chunk_type)} stored CRC does not match calculated CRC.",
            evidence_ids=(PNG_CRC_SOURCE, PNG_WRITE_CRC_VALIDATION_SOURCE),
        )
        for chunk in chunks
        if not chunk.crc_matches
    )


def _responsibility_for_chunk(chunk: MngChunkPlan) -> MngResponsibilityPlan:
    chunk_type = chunk.chunk_type
    if chunk_type in STRUCTURED_CHUNK_NAMES:
        is_jng = chunk_type == JNG_HEADER_CHUNK_TYPE
        return MngResponsibilityPlan(
            chunk_index=chunk.index,
            chunk_type=chunk_type,
            responsibility_kind="jng_control" if is_jng else "mng_control",
            handling_kind="structured_subdirectory",
            tag_name=STRUCTURED_CHUNK_NAMES[chunk_type],
            keyword=None,
            evidence_ids=(
                JNG_HEADER_SOURCE if is_jng else MNG_TABLE_SOURCE,
                MNG_HEADER_SOURCE if chunk_type == MNG_HEADER_CHUNK_TYPE else MNG_TABLE_SOURCE,
            ),
        )
    if chunk_type == b"pHYg":
        return MngResponsibilityPlan(
            chunk_index=chunk.index,
            chunk_type=chunk_type,
            responsibility_kind="mng_control",
            handling_kind="png_physical_pixel",
            tag_name="GlobalPixelSize",
            keyword=None,
            evidence_ids=(MNG_TABLE_SOURCE, MNG_SUPERSET_SOURCE),
        )
    if chunk_type in BINARY_CHUNK_NAMES:
        return MngResponsibilityPlan(
            chunk_index=chunk.index,
            chunk_type=chunk_type,
            responsibility_kind="mng_control",
            handling_kind="binary_payload",
            tag_name=BINARY_CHUNK_NAMES[chunk_type],
            keyword=None,
            evidence_ids=(MNG_TABLE_SOURCE, MNG_BINARY_SOURCE),
        )
    if chunk_type in VALUE_CONVERSION_CHUNK_NAMES:
        return MngResponsibilityPlan(
            chunk_index=chunk.index,
            chunk_type=chunk_type,
            responsibility_kind="mng_control",
            handling_kind="value_conversion",
            tag_name=VALUE_CONVERSION_CHUNK_NAMES[chunk_type],
            keyword=None,
            evidence_ids=(MNG_TABLE_SOURCE, MNG_VALUE_CONVERSION_SOURCE),
        )
    if chunk_type in TEXT_CHUNK_TYPES:
        return MngResponsibilityPlan(
            chunk_index=chunk.index,
            chunk_type=chunk_type,
            responsibility_kind="textual_metadata",
            handling_kind="textual_payload",
            tag_name="TextualData",
            keyword=_text_keyword(chunk_type, chunk.payload),
            evidence_ids=(MNG_SUPERSET_SOURCE,),
        )
    if chunk_type in PNG_METADATA_CHUNK_TYPES:
        return MngResponsibilityPlan(
            chunk_index=chunk.index,
            chunk_type=chunk_type,
            responsibility_kind="png_metadata",
            handling_kind="png_superset_metadata",
            tag_name=ascii_chunk_id(chunk_type),
            keyword=None,
            evidence_ids=(MNG_SUPERSET_SOURCE,),
        )
    if chunk_type in IMAGE_DATA_CHUNK_TYPES:
        return MngResponsibilityPlan(
            chunk_index=chunk.index,
            chunk_type=chunk_type,
            responsibility_kind="image_data",
            handling_kind="image_payload",
            tag_name=None,
            keyword=None,
            evidence_ids=(MNG_TABLE_SOURCE,),
        )
    if chunk_type in {MNG_END_CHUNK_TYPE, JNG_END_CHUNK_TYPE}:
        return MngResponsibilityPlan(
            chunk_index=chunk.index,
            chunk_type=chunk_type,
            responsibility_kind="end",
            handling_kind="container_end",
            tag_name=None,
            keyword=None,
            evidence_ids=(PNG_TRAILER_SOURCE,),
        )
    return MngResponsibilityPlan(
        chunk_index=chunk.index,
        chunk_type=chunk_type,
        responsibility_kind="unknown",
        handling_kind="preserve_unknown",
        tag_name=None,
        keyword=None,
        evidence_ids=(MNG_TABLE_SOURCE,),
    )


def _copy_action(chunk: MngChunkPlan) -> MngChunkActionPlan:
    return MngChunkActionPlan(
        kind="copy",
        chunk_type=chunk.chunk_type,
        source_index=chunk.index,
        output_index=chunk.index,
        payload_length=chunk.payload_length,
        reason="Copy existing MNG/JNG chunk payload unchanged.",
        evidence_ids=(PNG_CHUNK_ENUMERATION_SOURCE,),
    )


def _text_keyword(chunk_type: bytes, payload: bytes) -> str | None:
    delimiter = payload.find(b"\0")
    if delimiter < 0:
        return None
    encoding = "utf-8" if chunk_type == b"iTXt" else "latin-1"
    try:
        keyword = payload[:delimiter].decode(encoding)
    except UnicodeDecodeError:
        return None
    return "XMP" if chunk_type == b"iTXt" and keyword == XMP_ITXT_KEYWORD else keyword


def ascii_chunk_id(chunk_type: bytes | None) -> str | None:
    if chunk_type is None:
        return None
    return chunk_type.decode("latin-1")


def evidence_ids_to_json(sources: tuple[str, ...]) -> JsonArray:
    return list(sources)


def json_object_array(items: Iterable[JsonObject]) -> JsonArray:
    return list(items)


def unique_sources(sources: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source not in seen:
            seen.add(source)
            unique.append(source)
    return tuple(unique)


def unique_gates(gates: tuple[MngOutputEmissionGate, ...]) -> tuple[MngOutputEmissionGate, ...]:
    unique: list[MngOutputEmissionGate] = []
    seen: set[MngEmissionGateCode] = set()
    for gate in gates:
        if gate.code not in seen:
            seen.add(gate.code)
            unique.append(gate)
    return tuple(unique)
