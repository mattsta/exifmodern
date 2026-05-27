"""RAF container rewrite planning for FujiFilm RAW files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonObject

type FujiFilmRafEvidenceId = str
type FujiFilmRafPlanStatus = Literal["source_mapped_deferred", "unsupported"]
type FujiFilmRafOutputSegmentKind = Literal[
    "patched_raf_header_prefix",
    "rewritten_embedded_jpeg",
    "new_jpeg_padding",
    "preserved_remaining_raf_stream",
]
type FujiFilmRafEmissionGateCode = Literal[
    "truncated_raf_header",
    "invalid_raf_signature",
    "invalid_raf_version",
    "unsupported_jpeg_layout",
    "truncated_embedded_jpeg",
    "unsupported_mraw_header_length",
    "truncated_mraw_header",
    "unexpected_mraw_layout",
    "bad_raf_pointer_0x5c",
    "non_null_padding",
    "invalid_raf_header_offset",
    "raf_header_offset_error",
    "requires_embedded_jpeg_metadata_rewrite",
    "requires_transactional_raf_stream_copy",
]

RAF_BASE_HEADER_SIZE = 0x94
RAF_HEADER_POINTER_OFFSETS = (0x5C, 0x64, 0x78, 0x80, 0xCC, 0x114, 0x164)
MAX_OLD_PADDING_LENGTH = 1_000_000
UINT32_MAX = 0xFFFFFFFF

FUJIFILM_RAF_HEADER_SOURCE = "fujifilm.raf.header"
FUJIFILM_WRITE_RAF_VALIDATE_SOURCE = "fujifilm.raf.write-validate"
FUJIFILM_WRITE_RAF_JPEG_SOURCE = "fujifilm.raf.write-jpeg"
FUJIFILM_WRITE_RAF_POINTER_SOURCE = "fujifilm.raf.write-pointer"
FUJIFILM_WRITE_RAF_COPY_SOURCE = "fujifilm.raf.write-copy"


@dataclass(frozen=True)
class FujiFilmRafEmissionGate:
    code: FujiFilmRafEmissionGateCode
    detail: str
    evidence_ids: tuple[FujiFilmRafEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FujiFilmRafPointerPatchPlan:
    field_offset: int
    old_value: int
    new_value: int
    high_word_field_offset: int | None
    old_high_word: int | None
    new_high_word: int | None
    evidence_ids: tuple[FujiFilmRafEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "field_offset": f"0x{self.field_offset:04x}",
            "high_word_field_offset": (
                f"0x{self.high_word_field_offset:04x}"
                if self.high_word_field_offset is not None
                else None
            ),
            "new_high_word": self.new_high_word,
            "new_value": self.new_value,
            "old_high_word": self.old_high_word,
            "old_value": self.old_value,
        }


@dataclass(frozen=True)
class FujiFilmRafOutputSegmentPlan:
    kind: FujiFilmRafOutputSegmentKind
    source_offset: int | None
    source_length: int | None
    output_length: int | None
    evidence_ids: tuple[FujiFilmRafEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "output_length": self.output_length,
            "source_length": self.source_length,
            "source_offset": self.source_offset,
        }


@dataclass(frozen=True)
class FujiFilmRafHeaderPlan:
    version: str
    mraw_header_offset: int
    mraw_header_length: int
    jpeg_offset: int
    jpeg_length: int
    next_block_offset: int
    old_padding_length: int
    old_padding_is_zero_filled: bool
    evidence_ids: tuple[FujiFilmRafEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "jpeg_length": self.jpeg_length,
            "jpeg_offset": self.jpeg_offset,
            "mraw_header_length": self.mraw_header_length,
            "mraw_header_offset": self.mraw_header_offset,
            "next_block_offset": self.next_block_offset,
            "old_padding_is_zero_filled": self.old_padding_is_zero_filled,
            "old_padding_length": self.old_padding_length,
            "version": self.version,
        }


@dataclass(frozen=True)
class FujiFilmRafContainerRewritePlan:
    status: FujiFilmRafPlanStatus
    can_emit_output: bool
    header: FujiFilmRafHeaderPlan | None
    rewritten_jpeg_length: int | None
    rewritten_jpeg_padding_length: int | None
    pointer_delta: int | None
    pointer_patches: tuple[FujiFilmRafPointerPatchPlan, ...]
    output_segments: tuple[FujiFilmRafOutputSegmentPlan, ...]
    output_emission_gates: tuple[FujiFilmRafEmissionGate, ...]
    evidence_ids: tuple[FujiFilmRafEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "header": self.header.to_json() if self.header is not None else None,
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "pointer_delta": self.pointer_delta,
            "pointer_patches": [patch.to_json() for patch in self.pointer_patches],
            "output_segments": [segment.to_json() for segment in self.output_segments],
            "rewritten_jpeg_length": self.rewritten_jpeg_length,
            "rewritten_jpeg_padding_length": self.rewritten_jpeg_padding_length,
            "status": self.status,
        }


def build_fujifilm_raf_container_rewrite_plan(
    data: bytes,
    rewritten_jpeg_length: int | None = None,
) -> FujiFilmRafContainerRewritePlan:
    header, parse_gates = parse_raf_container_header(data)
    if header is None:
        return FujiFilmRafContainerRewritePlan(
            status="unsupported",
            can_emit_output=False,
            header=None,
            rewritten_jpeg_length=rewritten_jpeg_length,
            rewritten_jpeg_padding_length=None,
            pointer_delta=None,
            pointer_patches=(),
            output_segments=(),
            output_emission_gates=parse_gates,
            evidence_ids=unique_evidence_ids(
                tuple(reference for gate in parse_gates for reference in gate.evidence_ids)
            ),
        )

    padding_length = (
        jpeg_padding_length(rewritten_jpeg_length) if rewritten_jpeg_length is not None else None
    )
    pointer_delta = (
        rewritten_jpeg_length + padding_length - (header.jpeg_length + header.old_padding_length)
        if rewritten_jpeg_length is not None and padding_length is not None
        else None
    )
    pointer_patches, pointer_gates = plan_pointer_patches(data, header, pointer_delta)
    output_segments = plan_output_segments(data, header, rewritten_jpeg_length, padding_length)
    output_gates = (
        parse_gates
        + pointer_gates
        + (
            FujiFilmRafEmissionGate(
                "requires_embedded_jpeg_metadata_rewrite",
                (
                    "RAF byte emission requires the embedded JPEG to be rewritten by a "
                    "JPEG metadata writer first."
                ),
                (FUJIFILM_WRITE_RAF_JPEG_SOURCE,),
            ),
            FujiFilmRafEmissionGate(
                "requires_transactional_raf_stream_copy",
                (
                    "RAF byte emission must write the patched header/JPEG and copy the "
                    "remaining RAF stream transactionally."
                ),
                (FUJIFILM_WRITE_RAF_COPY_SOURCE,),
            ),
        )
    )
    return FujiFilmRafContainerRewritePlan(
        status="source_mapped_deferred",
        can_emit_output=False,
        header=header,
        rewritten_jpeg_length=rewritten_jpeg_length,
        rewritten_jpeg_padding_length=padding_length,
        pointer_delta=pointer_delta,
        pointer_patches=pointer_patches,
        output_segments=output_segments,
        output_emission_gates=output_gates,
        evidence_ids=unique_evidence_ids(
            (
                FUJIFILM_RAF_HEADER_SOURCE,
                FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
                FUJIFILM_WRITE_RAF_JPEG_SOURCE,
                FUJIFILM_WRITE_RAF_POINTER_SOURCE,
                FUJIFILM_WRITE_RAF_COPY_SOURCE,
            )
        ),
    )


def parse_raf_container_header(
    data: bytes,
) -> tuple[FujiFilmRafHeaderPlan | None, tuple[FujiFilmRafEmissionGate, ...]]:
    if len(data) < RAF_BASE_HEADER_SIZE:
        return None, (
            gate(
                "truncated_raf_header",
                "RAF files must contain the 0x94-byte base header read by WriteRAF.",
                FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
            ),
        )
    if not data.startswith(b"FUJIFILM"):
        return None, (
            gate(
                "invalid_raf_signature",
                "WriteRAF accepts only sources beginning with the FUJIFILM RAF signature.",
                FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
            ),
        )
    version = data[0x3C:0x40].decode("ascii", errors="replace")
    if not version.isdecimal():
        return None, (
            gate(
                "invalid_raf_version",
                "WriteRAF requires a four-digit RAF version string.",
                FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
            ),
        )

    mraw_header_offset = read_u32_be(data, 0x48)
    mraw_header_length = read_u32_be(data, 0x4C)
    jpeg_offset = read_u32_be(data, 0x54)
    jpeg_length = read_u32_be(data, 0x58)
    next_block_offset = read_u32_be(data, 0x5C)
    if (
        mraw_header_offset > RAF_BASE_HEADER_SIZE
        or jpeg_offset > RAF_BASE_HEADER_SIZE + mraw_header_length
        or jpeg_offset < 0x68
        or jpeg_offset % 4 != 0
    ):
        return None, (
            gate(
                "unsupported_jpeg_layout",
                (
                    "WriteRAF rejects RAF files whose embedded JPEG does not start at the "
                    "expected aligned location."
                ),
                FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
            ),
        )
    if jpeg_offset + jpeg_length > len(data):
        return None, (
            gate(
                "truncated_embedded_jpeg",
                (
                    "WriteRAF must be able to read the complete embedded JPEG length from "
                    "the RAF header."
                ),
                FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
            ),
        )

    mraw_gate = validate_mraw_header(data, mraw_header_offset, mraw_header_length)
    if mraw_gate is not None:
        return None, (mraw_gate,)

    old_padding_length = next_block_offset - (jpeg_offset + jpeg_length)
    padding_gate = validate_old_padding(data, jpeg_offset, jpeg_length, old_padding_length)
    old_padding_is_zero_filled = padding_gate is None
    return (
        FujiFilmRafHeaderPlan(
            version=version,
            mraw_header_offset=mraw_header_offset,
            mraw_header_length=mraw_header_length,
            jpeg_offset=jpeg_offset,
            jpeg_length=jpeg_length,
            next_block_offset=next_block_offset,
            old_padding_length=old_padding_length,
            old_padding_is_zero_filled=old_padding_is_zero_filled,
            evidence_ids=(FUJIFILM_RAF_HEADER_SOURCE, FUJIFILM_WRITE_RAF_VALIDATE_SOURCE),
        ),
        () if padding_gate is None else (padding_gate,),
    )


def validate_mraw_header(
    data: bytes,
    mraw_header_offset: int,
    mraw_header_length: int,
) -> FujiFilmRafEmissionGate | None:
    if mraw_header_offset == 0:
        return None
    if mraw_header_length != 0x11C:
        return gate(
            "unsupported_mraw_header_length",
            "WriteRAF supports M-RAW headers only when the length is 0x11c.",
            FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
        )
    if mraw_header_offset + mraw_header_length > len(data):
        return gate(
            "truncated_mraw_header",
            "WriteRAF must be able to read the complete M-RAW header before patch planning.",
            FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
        )
    header = (
        data[:RAF_BASE_HEADER_SIZE]
        + data[mraw_header_offset : mraw_header_offset + mraw_header_length]
    )
    if header[0xC0:0xC8] != b"\0" * 8 or header[0xC8:0xD0] != header[0x110:0x118]:
        return gate(
            "unexpected_mraw_layout",
            "WriteRAF validates the first M-RAW image offset/length layout before RAF rewriting.",
            FUJIFILM_WRITE_RAF_VALIDATE_SOURCE,
        )
    return None


def validate_old_padding(
    data: bytes,
    jpeg_offset: int,
    jpeg_length: int,
    old_padding_length: int,
) -> FujiFilmRafEmissionGate | None:
    padding_offset = jpeg_offset + jpeg_length
    if old_padding_length < 0 or old_padding_length > MAX_OLD_PADDING_LENGTH:
        return gate(
            "bad_raf_pointer_0x5c",
            "WriteRAF rejects RAF pointer 0x5c when old JPEG padding is negative or too large.",
            FUJIFILM_WRITE_RAF_POINTER_SOURCE,
        )
    if old_padding_length == 0:
        return None
    if padding_offset + old_padding_length > len(data):
        return gate(
            "bad_raf_pointer_0x5c",
            "WriteRAF must be able to read old JPEG padding through the next RAF block pointer.",
            FUJIFILM_WRITE_RAF_POINTER_SOURCE,
        )
    padding = data[padding_offset : padding_offset + old_padding_length]
    if any(byte != 0 for byte in padding):
        return gate(
            "non_null_padding",
            (
                "WriteRAF treats non-null bytes between the embedded JPEG and next RAF block "
                "as unsafe padding."
            ),
            FUJIFILM_WRITE_RAF_POINTER_SOURCE,
        )
    return None


def plan_pointer_patches(
    data: bytes,
    header: FujiFilmRafHeaderPlan,
    pointer_delta: int | None,
) -> tuple[tuple[FujiFilmRafPointerPatchPlan, ...], tuple[FujiFilmRafEmissionGate, ...]]:
    if pointer_delta is None:
        return (), ()
    patches: list[FujiFilmRafPointerPatchPlan] = []
    gates: list[FujiFilmRafEmissionGate] = []
    for field_offset in RAF_HEADER_POINTER_OFFSETS:
        if field_offset >= header.jpeg_offset:
            break
        old_value = read_u32_be(data, field_offset)
        if old_value == 0:
            continue
        adjusted_value = old_value + pointer_delta
        if 0 <= adjusted_value <= UINT32_MAX:
            patches.append(
                FujiFilmRafPointerPatchPlan(
                    field_offset=field_offset,
                    old_value=old_value,
                    new_value=adjusted_value,
                    high_word_field_offset=None,
                    old_high_word=None,
                    new_high_word=None,
                    evidence_ids=(FUJIFILM_WRITE_RAF_POINTER_SOURCE,),
                )
            )
            continue
        if field_offset < 0xCC:
            gates.append(
                gate(
                    "invalid_raf_header_offset",
                    "WriteRAF rejects underflow or overflow in base RAF header pointers.",
                    FUJIFILM_WRITE_RAF_POINTER_SOURCE,
                )
            )
            continue
        high_word = read_u32_be(data, field_offset - 4)
        high_word_delta = -1 if adjusted_value < 0 else 1
        new_high_word = high_word + high_word_delta
        if new_high_word < 0 or new_high_word > UINT32_MAX:
            gates.append(
                gate(
                    "raf_header_offset_error",
                    (
                        "WriteRAF rejects M-RAW 64-bit-style pointer fixups if the high word "
                        "overflows."
                    ),
                    FUJIFILM_WRITE_RAF_POINTER_SOURCE,
                )
            )
            continue
        new_value = adjusted_value % (UINT32_MAX + 1)
        patches.append(
            FujiFilmRafPointerPatchPlan(
                field_offset=field_offset,
                old_value=old_value,
                new_value=new_value,
                high_word_field_offset=field_offset - 4,
                old_high_word=high_word,
                new_high_word=new_high_word,
                evidence_ids=(FUJIFILM_WRITE_RAF_POINTER_SOURCE,),
            )
        )
    return tuple(patches), tuple(gates)


def plan_output_segments(
    data: bytes,
    header: FujiFilmRafHeaderPlan,
    rewritten_jpeg_length: int | None,
    padding_length: int | None,
) -> tuple[FujiFilmRafOutputSegmentPlan, ...]:
    suffix_length = (
        len(data) - header.next_block_offset if 0 <= header.next_block_offset <= len(data) else None
    )
    return (
        FujiFilmRafOutputSegmentPlan(
            kind="patched_raf_header_prefix",
            source_offset=0,
            source_length=header.jpeg_offset,
            output_length=header.jpeg_offset,
            evidence_ids=(FUJIFILM_WRITE_RAF_COPY_SOURCE,),
        ),
        FujiFilmRafOutputSegmentPlan(
            kind="rewritten_embedded_jpeg",
            source_offset=header.jpeg_offset,
            source_length=header.jpeg_length,
            output_length=rewritten_jpeg_length,
            evidence_ids=(FUJIFILM_WRITE_RAF_JPEG_SOURCE, FUJIFILM_WRITE_RAF_COPY_SOURCE),
        ),
        FujiFilmRafOutputSegmentPlan(
            kind="new_jpeg_padding",
            source_offset=None,
            source_length=None,
            output_length=padding_length,
            evidence_ids=(FUJIFILM_WRITE_RAF_POINTER_SOURCE, FUJIFILM_WRITE_RAF_COPY_SOURCE),
        ),
        FujiFilmRafOutputSegmentPlan(
            kind="preserved_remaining_raf_stream",
            source_offset=header.next_block_offset,
            source_length=suffix_length,
            output_length=suffix_length,
            evidence_ids=(FUJIFILM_WRITE_RAF_COPY_SOURCE,),
        ),
    )


def jpeg_padding_length(jpeg_length: int) -> int:
    return 4 - (jpeg_length % 4)


def read_u32_be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def gate(
    code: FujiFilmRafEmissionGateCode,
    detail: str,
    evidence_id: FujiFilmRafEvidenceId,
) -> FujiFilmRafEmissionGate:
    return FujiFilmRafEmissionGate(code, detail, (evidence_id,))


def unique_evidence_ids(
    references: tuple[FujiFilmRafEvidenceId, ...],
) -> tuple[FujiFilmRafEvidenceId, ...]:
    unique: list[FujiFilmRafEvidenceId] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)
