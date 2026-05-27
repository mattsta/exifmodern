"""Source-grounded, non-mutating BPG image metadata transaction plans.

ExifTool's BPG module is a reader: it validates the BPG magic, decodes the
packed image descriptor and ue7 image dimensions, enumerates optional metadata
extensions, and preserves the following HEVC payload.  This planner mirrors
those responsibilities without implementing a BPG writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BPG_MAGIC = b"BPG\xfb"
BPG_EXIFTOOL_HEADER_READ_SIZE = 21
BPG_EXTENSION_FLAG = 0x0008
BPG_MAX_EXTENSION_SIZE = 10_000_000

type BpgPlanStatus = Literal["planned", "unsupported"]
type BpgExtensionKind = Literal[
    "exif",
    "icc_profile",
    "xmp",
    "thumbnail_bpg",
    "animation_control",
    "unknown",
]
type BpgRewriteOperation = Literal["insert", "replace", "delete"]
type BpgActionKind = Literal[
    "validate_magic",
    "extract_image_header_fields",
    "enumerate_extensions",
    "route_metadata_extension",
    "preserve_metadata_extension",
    "preserve_hevc_payload",
    "block_unrecognized_extension",
    "block_requested_rewrite",
]
type BpgEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_bpg_header",
    "unsupported_bpg_magic",
    "truncated_header_ue7",
    "malformed_header_ue7",
    "missing_bpg_extension_data",
    "corrupted_bpg_extension_length",
    "bpg_extension_too_large",
    "truncated_bpg_extension",
    "corrupted_bpg_extension",
    "invalid_bpg_extension_size",
    "unrecognized_bpg_extension",
    "hevc_payload_exceeds_input",
    "rewrite_requested_requires_bpg_writer",
]

type BpgEvidenceId = str

BPG_DESCRIPTION_SOURCE = "bpg.description"
BPG_MAIN_TABLE_SOURCE = "bpg.main_table"
BPG_EXTENSION_TABLE_SOURCE = "bpg.extension_table"
BPG_UE7_SOURCE = "bpg.ue7"
BPG_PROCESS_GATE_SOURCE = "bpg.process_gate"
BPG_EXTENSION_LENGTH_SOURCE = "bpg.extension_length"
BPG_EXTENSION_LOOP_SOURCE = "bpg.extension_loop"
BPG_EXIF_PADDING_SOURCE = "bpg.exif_padding"

BPG_TRANSACTION_SOURCES = (
    BPG_DESCRIPTION_SOURCE,
    BPG_MAIN_TABLE_SOURCE,
    BPG_EXTENSION_TABLE_SOURCE,
    BPG_UE7_SOURCE,
    BPG_PROCESS_GATE_SOURCE,
    BPG_EXTENSION_LENGTH_SOURCE,
    BPG_EXTENSION_LOOP_SOURCE,
    BPG_EXIF_PADDING_SOURCE,
)


@dataclass(frozen=True)
class BpgOutputEmissionGate:
    code: BpgEmissionGateCode
    reason: str
    evidence_ids: tuple[BpgEvidenceId, ...]


@dataclass(frozen=True)
class BpgUe7Plan:
    start_offset: int
    end_offset: int
    encoded: bytes
    value: int | None
    reason: BpgEmissionGateCode | None
    evidence_ids: tuple[BpgEvidenceId, ...]

    @property
    def is_valid(self) -> bool:
        return self.reason is None and self.value is not None


@dataclass(frozen=True)
class BpgImageHeaderPlan:
    magic: bytes
    descriptor: int | None
    pixel_format: int | None
    pixel_format_description: str | None
    alpha: int | None
    alpha_description: str | None
    bit_depth: int | None
    color_space: int | None
    color_space_description: str | None
    flags: int | None
    flag_descriptions: tuple[str, ...]
    extension_present: bool
    image_width: int | None
    image_height: int | None
    image_length: int | None
    width_ue7: BpgUe7Plan | None
    height_ue7: BpgUe7Plan | None
    image_length_ue7: BpgUe7Plan | None
    header_end_offset: int | None
    evidence_ids: tuple[BpgEvidenceId, ...]


@dataclass(frozen=True)
class BpgExtensionPlan:
    index: int
    type_code: int
    kind: BpgExtensionKind
    name: str
    extension_offset: int
    length_ue7: BpgUe7Plan
    payload_offset: int
    payload_length: int
    logical_payload_offset: int
    logical_payload_length: int
    ignored_exif_padding: bool
    action: BpgActionKind
    evidence_ids: tuple[BpgEvidenceId, ...]

    @property
    def payload_range(self) -> tuple[int, int]:
        return (self.payload_offset, self.payload_offset + self.payload_length)

    @property
    def logical_payload_range(self) -> tuple[int, int]:
        return (
            self.logical_payload_offset,
            self.logical_payload_offset + self.logical_payload_length,
        )


@dataclass(frozen=True)
class BpgHevcPayloadPlan:
    start_offset: int | None
    end_offset: int | None
    declared_length: int | None
    length_to_eof: bool
    action: Literal["preserve"]
    evidence_ids: tuple[BpgEvidenceId, ...]

    @property
    def payload_length(self) -> int | None:
        if self.start_offset is None or self.end_offset is None:
            return None
        return self.end_offset - self.start_offset


@dataclass(frozen=True)
class BpgRewriteRequest:
    target: BpgExtensionKind
    operation: BpgRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class BpgActionPlan:
    kind: BpgActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[BpgEvidenceId, ...]


@dataclass(frozen=True)
class BpgImageTransactionPlan:
    status: BpgPlanStatus
    source_data: bytes
    header: BpgImageHeaderPlan
    extension_length: BpgUe7Plan | None
    extensions: tuple[BpgExtensionPlan, ...]
    hevc_payload: BpgHevcPayloadPlan
    rewrite_requests: tuple[BpgRewriteRequest, ...]
    actions: tuple[BpgActionPlan, ...]
    output_emission_gates: tuple[BpgOutputEmissionGate, ...]
    evidence_ids: tuple[BpgEvidenceId, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"BPG image transaction output is gated: {gate_codes}")
        return self.source_data


def build_bpg_image_transaction_plan(
    bpg_data: bytes,
    *,
    rewrite_requests: tuple[BpgRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> BpgImageTransactionPlan:
    """Build a source-backed BPG header/metadata transaction plan."""

    gates: list[BpgOutputEmissionGate] = []
    actions: list[BpgActionPlan] = []

    if len(bpg_data) < BPG_EXIFTOOL_HEADER_READ_SIZE:
        header = _empty_header(bpg_data[:4])
        gates.append(
            BpgOutputEmissionGate(
                code="truncated_bpg_header",
                reason="ExifTool's BPG reader requires a 21-byte initial header read.",
                evidence_ids=(BPG_PROCESS_GATE_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=bpg_data,
            header=header,
            extension_length=None,
            extensions=(),
            hevc_payload=_unknown_hevc_payload(),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    if not bpg_data.startswith(BPG_MAGIC):
        header = _empty_header(bpg_data[:4])
        gates.append(
            BpgOutputEmissionGate(
                code="unsupported_bpg_magic",
                reason="Input does not match ExifTool's /^BPG\\xfb/ BPG signature gate.",
                evidence_ids=(BPG_PROCESS_GATE_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=bpg_data,
            header=header,
            extension_length=None,
            extensions=(),
            hevc_payload=_unknown_hevc_payload(),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    actions.append(
        BpgActionPlan(
            kind="validate_magic",
            target="BPG",
            byte_range=(0, 4),
            reason="Input satisfied ExifTool's BPG magic gate.",
            evidence_ids=(BPG_PROCESS_GATE_SOURCE,),
        )
    )
    header = _build_header_plan(bpg_data)
    actions.append(
        BpgActionPlan(
            kind="extract_image_header_fields",
            target="BPG::Main",
            byte_range=(
                (0, header.header_end_offset) if header.header_end_offset is not None else None
            ),
            reason="Decoded the same BPG::Main image/header fields ExifTool models.",
            evidence_ids=(BPG_MAIN_TABLE_SOURCE, BPG_UE7_SOURCE),
        )
    )

    header_gate = _header_ue7_gate(header)
    if header_gate is not None:
        gates.append(header_gate)
        return _final_plan(
            status="unsupported",
            source_data=bpg_data,
            header=header,
            extension_length=None,
            extensions=(),
            hevc_payload=_unknown_hevc_payload(),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    extension_length: BpgUe7Plan | None = None
    extensions: tuple[BpgExtensionPlan, ...] = ()
    hevc_start = header.header_end_offset
    if header.extension_present and header.header_end_offset is not None:
        extension_length, extensions, hevc_start = _build_extension_plans(
            bpg_data,
            header.header_end_offset,
            gates,
            actions,
        )

    hevc_payload = _build_hevc_payload_plan(bpg_data, header.image_length, hevc_start, gates)
    if hevc_payload.start_offset is not None and hevc_payload.end_offset is not None:
        actions.append(
            BpgActionPlan(
                kind="preserve_hevc_payload",
                target="hevc_payload",
                byte_range=(hevc_payload.start_offset, hevc_payload.end_offset),
                reason="The BPG reader does not rewrite the HEVC image payload.",
                evidence_ids=(BPG_MAIN_TABLE_SOURCE, BPG_EXTENSION_LENGTH_SOURCE),
            )
        )

    for request in rewrite_requests:
        gates.append(
            BpgOutputEmissionGate(
                code="rewrite_requested_requires_bpg_writer",
                reason=(
                    f"BPG {request.operation} for {request.target} was requested, but "
                    "ExifTool's BPG module has no writer."
                ),
                evidence_ids=(BPG_DESCRIPTION_SOURCE,),
            )
        )
        actions.append(
            BpgActionPlan(
                kind="block_requested_rewrite",
                target=request.target,
                byte_range=None,
                reason="BPG metadata rewrites are blocked until a source-backed writer exists.",
                evidence_ids=(BPG_DESCRIPTION_SOURCE,),
            )
        )

    structural_codes = {
        "truncated_bpg_header",
        "unsupported_bpg_magic",
        "truncated_header_ue7",
        "malformed_header_ue7",
        "missing_bpg_extension_data",
        "corrupted_bpg_extension_length",
        "bpg_extension_too_large",
        "truncated_bpg_extension",
        "corrupted_bpg_extension",
        "invalid_bpg_extension_size",
        "hevc_payload_exceeds_input",
    }
    status: BpgPlanStatus = (
        "unsupported" if any(gate.code in structural_codes for gate in gates) else "planned"
    )
    return _final_plan(
        status=status,
        source_data=bpg_data,
        header=header,
        extension_length=extension_length,
        extensions=extensions,
        hevc_payload=hevc_payload,
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        gates=gates,
        allow_output_emission=allow_output_emission,
    )


plan_bpg_image_transaction = build_bpg_image_transaction_plan


def _build_header_plan(bpg_data: bytes) -> BpgImageHeaderPlan:
    descriptor = int.from_bytes(bpg_data[4:6], "big")
    pixel_format = (descriptor & 0xE000) >> 13
    alpha = descriptor & 0x1004
    bit_depth = ((descriptor & 0x0F00) >> 8) + 8
    color_space = (descriptor & 0x00F0) >> 4
    flags = descriptor & 0x000B
    width = _read_ue7(
        bpg_data,
        6,
        BPG_EXIFTOOL_HEADER_READ_SIZE,
        "truncated_header_ue7",
        "malformed_header_ue7",
    )
    height = (
        _read_ue7(
            bpg_data,
            width.end_offset,
            BPG_EXIFTOOL_HEADER_READ_SIZE,
            "truncated_header_ue7",
            "malformed_header_ue7",
        )
        if width.is_valid
        else None
    )
    image_length = (
        _read_ue7(
            bpg_data,
            height.end_offset,
            BPG_EXIFTOOL_HEADER_READ_SIZE,
            "truncated_header_ue7",
            "malformed_header_ue7",
        )
        if height is not None and height.is_valid
        else None
    )

    return BpgImageHeaderPlan(
        magic=bpg_data[:4],
        descriptor=descriptor,
        pixel_format=pixel_format,
        pixel_format_description=_pixel_format_description(pixel_format),
        alpha=alpha,
        alpha_description=_alpha_description(alpha),
        bit_depth=bit_depth,
        color_space=color_space,
        color_space_description=_color_space_description(color_space),
        flags=flags,
        flag_descriptions=_flag_descriptions(flags),
        extension_present=bool(flags & BPG_EXTENSION_FLAG),
        image_width=width.value if width.is_valid else None,
        image_height=height.value if height is not None and height.is_valid else None,
        image_length=image_length.value
        if image_length is not None and image_length.is_valid
        else None,
        width_ue7=width,
        height_ue7=height,
        image_length_ue7=image_length,
        header_end_offset=image_length.end_offset
        if image_length is not None and image_length.is_valid
        else None,
        evidence_ids=(BPG_MAIN_TABLE_SOURCE, BPG_UE7_SOURCE, BPG_PROCESS_GATE_SOURCE),
    )


def _build_extension_plans(
    bpg_data: bytes,
    extension_length_offset: int,
    gates: list[BpgOutputEmissionGate],
    actions: list[BpgActionPlan],
) -> tuple[BpgUe7Plan | None, tuple[BpgExtensionPlan, ...], int | None]:
    if len(bpg_data) < extension_length_offset + 5:
        gates.append(
            BpgOutputEmissionGate(
                code="missing_bpg_extension_data",
                reason="The extension-present flag is set but ExifTool cannot read five bytes.",
                evidence_ids=(BPG_EXTENSION_LENGTH_SOURCE,),
            )
        )
        return None, (), None

    length_plan = _read_ue7(
        bpg_data,
        extension_length_offset,
        extension_length_offset + 5,
        "corrupted_bpg_extension_length",
        "corrupted_bpg_extension_length",
    )
    if not length_plan.is_valid or length_plan.value is None:
        gates.append(
            BpgOutputEmissionGate(
                code="corrupted_bpg_extension_length",
                reason="ExifTool's Get_ue7 rejected the BPG extension length.",
                evidence_ids=(BPG_EXTENSION_LENGTH_SOURCE, BPG_UE7_SOURCE),
            )
        )
        return length_plan, (), None

    if length_plan.value > BPG_MAX_EXTENSION_SIZE:
        gates.append(
            BpgOutputEmissionGate(
                code="bpg_extension_too_large",
                reason="ExifTool refuses BPG extension payloads larger than 10 MB.",
                evidence_ids=(BPG_EXTENSION_LENGTH_SOURCE,),
            )
        )
        return length_plan, (), None

    payload_start = length_plan.end_offset
    payload_end = payload_start + length_plan.value
    if payload_end > len(bpg_data):
        gates.append(
            BpgOutputEmissionGate(
                code="truncated_bpg_extension",
                reason="Input ended before the declared BPG extension payload was available.",
                evidence_ids=(BPG_EXTENSION_LENGTH_SOURCE,),
            )
        )
        return length_plan, (), None

    extensions = _enumerate_extensions(bpg_data, payload_start, payload_end, gates, actions)
    actions.append(
        BpgActionPlan(
            kind="enumerate_extensions",
            target="BPG::Extensions",
            byte_range=(payload_start, payload_end),
            reason="Extension records were enumerated as type plus ue7 length entries.",
            evidence_ids=(BPG_EXTENSION_LOOP_SOURCE, BPG_EXTENSION_TABLE_SOURCE),
        )
    )
    return length_plan, extensions, payload_end


def _enumerate_extensions(
    bpg_data: bytes,
    payload_start: int,
    payload_end: int,
    gates: list[BpgOutputEmissionGate],
    actions: list[BpgActionPlan],
) -> tuple[BpgExtensionPlan, ...]:
    extensions: list[BpgExtensionPlan] = []
    cursor = payload_start
    while cursor < payload_end:
        extension_offset = cursor
        type_code = bpg_data[cursor]
        length_plan = _read_ue7(
            bpg_data,
            cursor + 1,
            payload_end,
            "corrupted_bpg_extension",
            "corrupted_bpg_extension",
        )
        if not length_plan.is_valid or length_plan.value is None:
            gates.append(
                BpgOutputEmissionGate(
                    code="corrupted_bpg_extension",
                    reason="ExifTool's Get_ue7 rejected an individual BPG extension length.",
                    evidence_ids=(BPG_EXTENSION_LOOP_SOURCE, BPG_UE7_SOURCE),
                )
            )
            break
        item_payload_start = length_plan.end_offset
        item_payload_end = item_payload_start + length_plan.value
        if item_payload_end > payload_end:
            gates.append(
                BpgOutputEmissionGate(
                    code="invalid_bpg_extension_size",
                    reason="An individual BPG extension length exceeds the extension block.",
                    evidence_ids=(BPG_EXTENSION_LOOP_SOURCE,),
                )
            )
            break

        kind, name = _extension_kind(type_code)
        logical_offset = item_payload_start
        logical_length = length_plan.value
        ignored_exif_padding = False
        sources = [BPG_EXTENSION_LOOP_SOURCE, BPG_EXTENSION_TABLE_SOURCE]
        if (
            type_code == 1
            and length_plan.value > 3
            and bpg_data[item_payload_start + 1 : item_payload_start + 3] in (b"II", b"MM")
        ):
            logical_offset += 1
            logical_length -= 1
            ignored_exif_padding = True
            sources.append(BPG_EXIF_PADDING_SOURCE)

        if kind == "unknown":
            action: BpgActionKind = "block_unrecognized_extension"
            gates.append(
                BpgOutputEmissionGate(
                    code="unrecognized_bpg_extension",
                    reason=f"ExifTool warns for unrecognized BPG extension {type_code}.",
                    evidence_ids=(BPG_EXTENSION_LOOP_SOURCE,),
                )
            )
        elif kind in ("exif", "icc_profile", "xmp"):
            action = "route_metadata_extension"
        else:
            action = "preserve_metadata_extension"

        extension = BpgExtensionPlan(
            index=len(extensions),
            type_code=type_code,
            kind=kind,
            name=name,
            extension_offset=extension_offset,
            length_ue7=length_plan,
            payload_offset=item_payload_start,
            payload_length=length_plan.value,
            logical_payload_offset=logical_offset,
            logical_payload_length=logical_length,
            ignored_exif_padding=ignored_exif_padding,
            action=action,
            evidence_ids=tuple(sources),
        )
        extensions.append(extension)
        actions.append(
            BpgActionPlan(
                kind=action,
                target=name,
                byte_range=extension.logical_payload_range,
                reason=_extension_action_reason(kind),
                evidence_ids=extension.evidence_ids,
            )
        )
        cursor = item_payload_end
    return tuple(extensions)


def _build_hevc_payload_plan(
    bpg_data: bytes,
    image_length: int | None,
    start_offset: int | None,
    gates: list[BpgOutputEmissionGate],
) -> BpgHevcPayloadPlan:
    if start_offset is None or image_length is None:
        return _unknown_hevc_payload()
    if image_length == 0:
        return BpgHevcPayloadPlan(
            start_offset=start_offset,
            end_offset=len(bpg_data),
            declared_length=0,
            length_to_eof=True,
            action="preserve",
            evidence_ids=(BPG_MAIN_TABLE_SOURCE, BPG_EXTENSION_LENGTH_SOURCE),
        )
    end_offset = start_offset + image_length
    if end_offset > len(bpg_data):
        gates.append(
            BpgOutputEmissionGate(
                code="hevc_payload_exceeds_input",
                reason="The BPG ImageLength field points beyond the available HEVC payload.",
                evidence_ids=(BPG_MAIN_TABLE_SOURCE,),
            )
        )
        return BpgHevcPayloadPlan(
            start_offset=start_offset,
            end_offset=None,
            declared_length=image_length,
            length_to_eof=False,
            action="preserve",
            evidence_ids=(BPG_MAIN_TABLE_SOURCE,),
        )
    return BpgHevcPayloadPlan(
        start_offset=start_offset,
        end_offset=end_offset,
        declared_length=image_length,
        length_to_eof=False,
        action="preserve",
        evidence_ids=(BPG_MAIN_TABLE_SOURCE,),
    )


def _read_ue7(
    data: bytes,
    start_offset: int,
    limit_offset: int,
    truncated_code: BpgEmissionGateCode,
    malformed_code: BpgEmissionGateCode,
) -> BpgUe7Plan:
    value = 0
    encoded = bytearray()
    index = 0
    while True:
        absolute_offset = start_offset + index
        if absolute_offset >= limit_offset:
            return BpgUe7Plan(
                start_offset=start_offset,
                end_offset=absolute_offset,
                encoded=bytes(encoded),
                value=None,
                reason=truncated_code,
                evidence_ids=(BPG_UE7_SOURCE,),
            )
        if index >= 5:
            return BpgUe7Plan(
                start_offset=start_offset,
                end_offset=absolute_offset,
                encoded=bytes(encoded),
                value=None,
                reason=malformed_code,
                evidence_ids=(BPG_UE7_SOURCE,),
            )
        byte = data[absolute_offset]
        encoded.append(byte)
        value = (value << 7) | (byte & 0x7F)
        if byte & 0x80 == 0:
            if index == 4 and byte & 0x70:
                return BpgUe7Plan(
                    start_offset=start_offset,
                    end_offset=absolute_offset + 1,
                    encoded=bytes(encoded),
                    value=None,
                    reason=malformed_code,
                    evidence_ids=(BPG_UE7_SOURCE,),
                )
            return BpgUe7Plan(
                start_offset=start_offset,
                end_offset=absolute_offset + 1,
                encoded=bytes(encoded),
                value=value,
                reason=None,
                evidence_ids=(BPG_UE7_SOURCE,),
            )
        if index == 0 and byte == 0x80:
            return BpgUe7Plan(
                start_offset=start_offset,
                end_offset=absolute_offset + 1,
                encoded=bytes(encoded),
                value=None,
                reason=malformed_code,
                evidence_ids=(BPG_UE7_SOURCE,),
            )
        index += 1


def _header_ue7_gate(header: BpgImageHeaderPlan) -> BpgOutputEmissionGate | None:
    ue7_values = (header.width_ue7, header.height_ue7, header.image_length_ue7)
    for ue7_value in ue7_values:
        if ue7_value is not None and ue7_value.reason is not None:
            return BpgOutputEmissionGate(
                code=ue7_value.reason,
                reason="ExifTool's BPG header ue7 decoder rejected an image header field.",
                evidence_ids=(BPG_MAIN_TABLE_SOURCE, BPG_UE7_SOURCE),
            )
    if header.image_length_ue7 is None:
        return BpgOutputEmissionGate(
            code="truncated_header_ue7",
            reason="ExifTool could not decode all three BPG header ue7 fields.",
            evidence_ids=(BPG_MAIN_TABLE_SOURCE, BPG_UE7_SOURCE),
        )
    return None


def _final_plan(
    *,
    status: BpgPlanStatus,
    source_data: bytes,
    header: BpgImageHeaderPlan,
    extension_length: BpgUe7Plan | None,
    extensions: tuple[BpgExtensionPlan, ...],
    hevc_payload: BpgHevcPayloadPlan,
    rewrite_requests: tuple[BpgRewriteRequest, ...],
    actions: tuple[BpgActionPlan, ...],
    gates: list[BpgOutputEmissionGate],
    allow_output_emission: bool,
) -> BpgImageTransactionPlan:
    if not allow_output_emission:
        gates.append(
            BpgOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="BPG transaction plans are non-mutating unless emission is explicit.",
                evidence_ids=(BPG_DESCRIPTION_SOURCE,),
            )
        )
    unique_gates = _unique_gates(tuple(gates))
    evidence_ids = _unique_evidence_ids(
        (
            *BPG_TRANSACTION_SOURCES,
            *header.evidence_ids,
            *hevc_payload.evidence_ids,
            *(source_id for gate in unique_gates for source_id in gate.evidence_ids),
            *(source_id for extension in extensions for source_id in extension.evidence_ids),
            *(source_id for action in actions for source_id in action.evidence_ids),
        )
    )
    return BpgImageTransactionPlan(
        status=status,
        source_data=source_data,
        header=header,
        extension_length=extension_length,
        extensions=extensions,
        hevc_payload=hevc_payload,
        rewrite_requests=rewrite_requests,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=evidence_ids,
    )


def _empty_header(magic: bytes) -> BpgImageHeaderPlan:
    return BpgImageHeaderPlan(
        magic=magic,
        descriptor=None,
        pixel_format=None,
        pixel_format_description=None,
        alpha=None,
        alpha_description=None,
        bit_depth=None,
        color_space=None,
        color_space_description=None,
        flags=None,
        flag_descriptions=(),
        extension_present=False,
        image_width=None,
        image_height=None,
        image_length=None,
        width_ue7=None,
        height_ue7=None,
        image_length_ue7=None,
        header_end_offset=None,
        evidence_ids=(BPG_PROCESS_GATE_SOURCE,),
    )


def _unknown_hevc_payload() -> BpgHevcPayloadPlan:
    return BpgHevcPayloadPlan(
        start_offset=None,
        end_offset=None,
        declared_length=None,
        length_to_eof=False,
        action="preserve",
        evidence_ids=(BPG_MAIN_TABLE_SOURCE,),
    )


def _pixel_format_description(pixel_format: int) -> str | None:
    descriptions = {
        0: "Grayscale",
        1: "4:2:0 (chroma at 0.5, 0.5)",
        2: "4:2:2 (chroma at 0.5, 0)",
        3: "4:4:4",
        4: "4:2:0 (chroma at 0, 0.5)",
        5: "4:2:2 (chroma at 0, 0)",
    }
    return descriptions.get(pixel_format)


def _alpha_description(alpha: int) -> str | None:
    descriptions = {
        0x0000: "No Alpha Plane",
        0x1000: "Alpha Exists (color not premultiplied)",
        0x1004: "Alpha Exists (color premultiplied)",
        0x0004: "Alpha Exists (W color component)",
    }
    return descriptions.get(alpha)


def _color_space_description(color_space: int) -> str | None:
    descriptions = {
        0: "YCbCr (BT 601)",
        1: "RGB",
        2: "YCgCo",
        3: "YCbCr (BT 709)",
        4: "YCbCr (BT 2020)",
        5: "BT 2020 Constant Luminance",
    }
    return descriptions.get(color_space)


def _flag_descriptions(flags: int) -> tuple[str, ...]:
    descriptions: list[str] = []
    if flags & 0x0001:
        descriptions.append("Animation")
    if flags & 0x0002:
        descriptions.append("Limited Range")
    if flags & BPG_EXTENSION_FLAG:
        descriptions.append("Extension Present")
    return tuple(descriptions)


def _extension_kind(type_code: int) -> tuple[BpgExtensionKind, str]:
    if type_code == 1:
        return "exif", "EXIF"
    if type_code == 2:
        return "icc_profile", "ICC_Profile"
    if type_code == 3:
        return "xmp", "XMP"
    if type_code == 4:
        return "thumbnail_bpg", "ThumbnailBPG"
    if type_code == 5:
        return "animation_control", "AnimationControl"
    return "unknown", f"UnknownExtension{type_code}"


def _extension_action_reason(kind: BpgExtensionKind) -> str:
    if kind == "unknown":
        return "Unrecognized BPG extensions are warning-only reads and block planned emission."
    if kind in ("exif", "icc_profile", "xmp"):
        return "Known metadata extension is routed to the ExifTool-modeled subdirectory."
    return "Known binary BPG extension is preserved as metadata-adjacent payload."


def _unique_gates(gates: tuple[BpgOutputEmissionGate, ...]) -> tuple[BpgOutputEmissionGate, ...]:
    unique: list[BpgOutputEmissionGate] = []
    seen: set[tuple[BpgEmissionGateCode, str]] = set()
    for gate in gates:
        key = (gate.code, gate.reason)
        if key not in seen:
            seen.add(key)
            unique.append(gate)
    return tuple(unique)


def _unique_evidence_ids(sources: tuple[BpgEvidenceId, ...]) -> tuple[BpgEvidenceId, ...]:
    unique: list[BpgEvidenceId] = []
    seen: set[BpgEvidenceId] = set()
    for source_id in sources:
        if source_id not in seen:
            seen.add(source_id)
            unique.append(source_id)
    return tuple(unique)
