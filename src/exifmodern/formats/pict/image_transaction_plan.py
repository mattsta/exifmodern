"""Source-grounded, preserve-only PICT image transaction plans.

ExifTool's PICT module reads PICT resources or files with a 512-byte prefix,
extracts image bounds plus optional extended resolution, and only walks image
opcodes when Verbose or Unknown extraction is enabled. This planner records the
same read boundaries and preserves the original byte stream; PICT rewrites are
blocked because PICT.pm provides no writer.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

PICT_FILE_HEADER_SIZE = 512
PICT_PROBE_SIZE = 12
PICT_V2_EXTENSION_SIZE = 28
PICT_V1_HEADER_OPCODE = 0x1101
PICT_V2_HEADER_OPCODE = 0x0011
PICT_V2_STANDARD_MARKER = b"\x02\xff\x0c\x00\xff\xff"
PICT_V2_EXTENDED_MARKER = b"\x02\xff\x0c\x00\xff\xfe"
PICT_END_OPCODE = 0x00FF
PICT_BASE_DPI = 72.0

type PictPlanStatus = Literal["planned", "unsupported"]
type PictVersion = Literal[1, 2]
type PictHeaderLocation = Literal["resource", "file_header_prefixed"]
type PictRewriteOperation = Literal["insert", "replace", "delete"]
type PictRewriteTarget = Literal[
    "image_bounds",
    "resolution",
    "opcode_stream",
    "long_comment",
    "preview_image",
]
type PictOpcodeKind = Literal["known", "reserved", "unknown", "end"]
type PictOpcodePayloadKind = Literal[
    "fixed",
    "none",
    "int16_data",
    "int32_data",
    "long_comment",
    "unknown_remainder",
]
type PictActionKind = Literal[
    "probe_header",
    "skip_file_header",
    "extract_image_bounds",
    "extract_extended_resolution",
    "scan_opcode_stream",
    "preserve_prefix",
    "preserve_header",
    "preserve_opcode",
    "preserve_embedded_payload",
    "preserve_unknown_opcode_remainder",
    "block_requested_rewrite",
]
type PictEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_pict_header",
    "unsupported_pict_header",
    "invalid_pict_bounds",
    "invalid_pict_extended_resolution",
    "truncated_pict_opcode",
    "truncated_pict_opcode_payload",
    "rewrite_requested_requires_pict_writer",
]

PICT_DESCRIPTION_SOURCE = "pict.description"
PICT_STRUCT_SOURCE = "pict.structs"
PICT_MAIN_TABLE_SOURCE = "pict.main_table"
PICT_COMMENT_KIND_SOURCE = "pict.comment_kind"
PICT_HEADER_GATE_SOURCE = "pict.header_gate"
PICT_EXTENDED_SOURCE = "pict.extended_header"
PICT_OPTIONAL_OPCODE_SOURCE = "pict.optional_opcode_scan"
PICT_RESERVED_OPCODE_SOURCE = "pict.reserved_opcode_lookup"
PICT_OPCODE_READ_SOURCE = "pict.opcode_reader"
PICT_READ_VALUE_SOURCE = "pict.read_value"

PICT_TRANSACTION_SOURCES = (
    PICT_DESCRIPTION_SOURCE,
    PICT_STRUCT_SOURCE,
    PICT_MAIN_TABLE_SOURCE,
    PICT_COMMENT_KIND_SOURCE,
    PICT_HEADER_GATE_SOURCE,
    PICT_EXTENDED_SOURCE,
    PICT_OPTIONAL_OPCODE_SOURCE,
    PICT_RESERVED_OPCODE_SOURCE,
    PICT_OPCODE_READ_SOURCE,
    PICT_READ_VALUE_SOURCE,
)

PICT_FIXED_OPCODE_SIZES: dict[int, tuple[str, int]] = {
    0x0000: ("Nop", 0),
    0x0001: ("ClipRgn", 10),
    0x0002: ("BkPat", 8),
    0x0003: ("TxFont", 2),
    0x0004: ("TxFace", 1),
    0x0005: ("TxMode", 2),
    0x0006: ("SpExtra", 4),
    0x0007: ("PnSize", 4),
    0x0008: ("PnMode", 2),
    0x0009: ("PnPat", 8),
    0x000A: ("FillPat", 8),
    0x000B: ("OvSize", 4),
    0x000C: ("Origin", 4),
    0x000D: ("TxSize", 2),
    0x000E: ("FgColor", 4),
    0x000F: ("BkColor", 4),
    0x0010: ("TxRatio", 8),
    0x0011: ("VersionOp", 1),
    0x0015: ("PnLocHFrac", 2),
    0x0016: ("ChExtra", 2),
    0x001A: ("RGBFgCol", 6),
    0x001B: ("RGBBkCol", 6),
    0x001C: ("HiliteMode", 0),
    0x001D: ("HiliteColor", 6),
    0x001E: ("DefHilite", 0),
    0x001F: ("OpColor", 6),
    0x0020: ("Line", 8),
    0x0021: ("LineFrom", 4),
    0x0022: ("ShortLine", 6),
    0x0023: ("ShortLineFrom", 2),
    0x002D: ("LineJustify", 10),
    0x002E: ("GlyphState", 8),
    0x0030: ("FrameRect", 8),
    0x0031: ("PaintRect", 8),
    0x0032: ("EraseRect", 8),
    0x0033: ("InvertRect", 8),
    0x0034: ("FillRect", 8),
    0x0038: ("FrameSameRect", 0),
    0x0039: ("PaintSameRect", 0),
    0x003A: ("EraseSameRect", 0),
    0x003B: ("InvertSameRect", 0),
    0x003C: ("FillSameRect", 0),
    0x0050: ("FrameOval", 8),
    0x0051: ("PaintOval", 8),
    0x0052: ("EraseOval", 8),
    0x0053: ("InvertOval", 8),
    0x0054: ("FillOval", 8),
    0x0058: ("FrameSameOval", 0),
    0x0059: ("PaintSameOval", 0),
    0x005A: ("EraseSameOval", 0),
    0x005B: ("InvertSameOval", 0),
    0x005C: ("FillSameOval", 0),
    0x0068: ("FrameSameArc", 4),
    0x0069: ("PaintSameArc", 4),
    0x006A: ("EraseSameArc", 4),
    0x006B: ("InvertSameArc", 4),
    0x006C: ("FillSameArc", 4),
    0x00A0: ("ShortComment", 2),
    0x0100: ("Reserved", 2),
    0x0200: ("Reserved", 4),
    0x02FF: ("Version", 2),
    0x0300: ("Reserved", 2),
    0x0BFF: ("Reserved", 22),
    0x0C00: ("HeaderOp", 24),
    0x0C01: ("Reserved", 24),
    0x7F00: ("Reserved", 254),
    0x8000: ("Reserved", 0),
}

PICT_RECT_RESERVED_STARTS = frozenset({0x0035, 0x0045, 0x0055})
PICT_NULL_RESERVED_STARTS = frozenset({0x003D, 0x004D, 0x005D, 0x007D, 0x008D, 0x00B0})
PICT_INT16_DATA_STARTS = frozenset({0x0024, 0x002F, 0x0092, 0x009C, 0x009D, 0x009E, 0x009F})
PICT_INT32_DATA_STARTS = frozenset({0x00D0, 0x8100, 0x8201, 0xFFFF})
PICT_RESERVED_RANGES = (
    (0x0017, 0x0019, 0x0017),
    (0x0024, 0x0027, 0x0024),
    (0x0035, 0x0037, 0x0035),
    (0x003D, 0x003F, 0x003D),
    (0x0045, 0x0047, 0x0045),
    (0x004D, 0x004F, 0x004D),
    (0x0055, 0x0057, 0x0055),
    (0x005D, 0x005F, 0x005D),
    (0x006D, 0x006F, 0x006D),
    (0x007D, 0x007F, 0x007D),
    (0x008D, 0x008F, 0x008D),
    (0x0092, 0x0097, 0x0092),
    (0x00A2, 0x00AF, 0x00A2),
    (0x00B0, 0x00CF, 0x00B0),
    (0x00D0, 0x00FE, 0x00D0),
    (0x0100, 0x01FF, 0x0100),
    (0x0300, 0x0BFE, 0x0300),
    (0x0C01, 0x7EFF, 0x0C01),
    (0x7F00, 0x7FFF, 0x7F00),
    (0x8000, 0x80FF, 0x8000),
    (0x8100, 0x81FF, 0x8100),
    (0x8201, 0xFFFF, 0x8201),
)


@dataclass(frozen=True)
class PictRewriteRequest:
    target: PictRewriteTarget
    operation: PictRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class PictOutputEmissionGate:
    code: PictEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PictBoundsPlan:
    top: int | None
    left: int | None
    bottom: int | None
    right: int | None
    frame_width: int | None
    frame_height: int | None
    image_width: int | None
    image_height: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PictResolutionPlan:
    x_resolution: float | None
    y_resolution: float | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PictHeaderPlan:
    header_location: PictHeaderLocation | None
    file_header_range: tuple[int, int] | None
    header_range: tuple[int, int] | None
    opcode_stream_range: tuple[int, int] | None
    version: PictVersion | None
    extended: bool
    bounds: PictBoundsPlan
    resolution: PictResolutionPlan
    reason: PictEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class PictOpcodePlan:
    index: int
    opcode: int
    name: str
    kind: PictOpcodeKind
    payload_kind: PictOpcodePayloadKind
    opcode_range: tuple[int, int]
    payload_range: tuple[int, int]
    full_range: tuple[int, int]
    padding_range: tuple[int, int] | None
    embedded_kind: str | None
    reason: PictEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def payload_size(self) -> int:
        start, end = self.payload_range
        return end - start


@dataclass(frozen=True)
class PictOpcodeScanPlan:
    requested_by_oracle_options: bool
    scanned_range: tuple[int, int] | None
    opcodes: tuple[PictOpcodePlan, ...]
    found_end_opcode: bool
    stop_reason: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PictActionPlan:
    kind: PictActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PictImageTransactionPlan:
    status: PictPlanStatus
    source_data: bytes
    header: PictHeaderPlan
    opcode_scan: PictOpcodeScanPlan
    actions: tuple[PictActionPlan, ...]
    output_emission_gates: tuple[PictOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"PICT image transaction output is gated: {gate_codes}")
        return self.source_data


def build_pict_image_transaction_plan(
    pict_data: bytes,
    *,
    rewrite_requests: tuple[PictRewriteRequest, ...] = (),
    scan_opcodes: bool = True,
    allow_output_emission: bool = False,
) -> PictImageTransactionPlan:
    """Build a preserve-only PICT image transaction plan from in-memory bytes."""

    gates: list[PictOutputEmissionGate] = []
    header = build_pict_header_plan(pict_data)
    if header.reason is not None:
        gates.append(
            PictOutputEmissionGate(
                code=header.reason,
                reason="Input does not satisfy ExifTool's PICT header/resource gate.",
                evidence_ids=header.evidence_ids,
            )
        )

    opcode_scan = build_pict_opcode_scan_plan(pict_data, header, scan_opcodes)
    for opcode in opcode_scan.opcodes:
        if opcode.reason is not None:
            gates.append(
                PictOutputEmissionGate(
                    code=opcode.reason,
                    reason=f"Opcode 0x{opcode.opcode:04x} could not be fully bounded.",
                    evidence_ids=opcode.evidence_ids,
                )
            )
    actions = build_pict_actions(header, opcode_scan, rewrite_requests)
    if rewrite_requests:
        gates.append(
            PictOutputEmissionGate(
                code="rewrite_requested_requires_pict_writer",
                reason="PICT.pm provides read behavior only, so requested rewrites are blocked.",
                evidence_ids=(PICT_DESCRIPTION_SOURCE,),
            )
        )
    add_non_mutating_gate(gates, allow_output_emission)
    unique_gates = unique_emission_gates(tuple(gates))
    status: PictPlanStatus = "unsupported" if structural_gate_present(unique_gates) else "planned"
    sources = unique_sources(
        (
            *PICT_TRANSACTION_SOURCES,
            *header.evidence_ids,
            *header.bounds.evidence_ids,
            *header.resolution.evidence_ids,
            *opcode_scan.evidence_ids,
            *(source for opcode in opcode_scan.opcodes for source in opcode.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in unique_gates for source in gate.evidence_ids),
        )
    )
    return PictImageTransactionPlan(
        status=status,
        source_data=pict_data,
        header=header,
        opcode_scan=opcode_scan,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=sources,
    )


def build_pict_header_plan(pict_data: bytes) -> PictHeaderPlan:
    direct = parse_header_at(pict_data, 0, "resource")
    if direct.reason is None:
        return direct
    prefixed = parse_header_at(pict_data, PICT_FILE_HEADER_SIZE, "file_header_prefixed")
    if prefixed.reason is None or direct.reason == "unsupported_pict_header":
        return prefixed
    return direct


def parse_header_at(
    pict_data: bytes,
    offset: int,
    location: PictHeaderLocation,
) -> PictHeaderPlan:
    if len(pict_data) < offset + PICT_PROBE_SIZE:
        return empty_header_plan(
            location if offset == 0 else None,
            (0, min(len(pict_data), PICT_FILE_HEADER_SIZE)) if offset else None,
            "truncated_pict_header",
            (PICT_HEADER_GATE_SOURCE,),
        )
    probe = pict_data[offset : offset + PICT_PROBE_SIZE]
    top = read_i16be(probe, 2)
    left = read_i16be(probe, 4)
    bottom = read_i16be(probe, 6)
    right = read_i16be(probe, 8)
    header_opcode = read_u16be(probe, 10)
    if header_opcode == PICT_V1_HEADER_OPCODE:
        return accepted_header_plan(
            location,
            pict_data,
            offset,
            1,
            False,
            top,
            left,
            bottom,
            right,
            None,
            None,
        )
    if header_opcode != PICT_V2_HEADER_OPCODE:
        return empty_header_plan(
            location,
            (0, PICT_FILE_HEADER_SIZE) if offset else None,
            "unsupported_pict_header",
            (PICT_HEADER_GATE_SOURCE,),
        )
    if len(pict_data) < offset + PICT_PROBE_SIZE + PICT_V2_EXTENSION_SIZE:
        return empty_header_plan(
            location,
            (0, PICT_FILE_HEADER_SIZE) if offset else None,
            "truncated_pict_header",
            (PICT_HEADER_GATE_SOURCE,),
        )
    extension = pict_data[
        offset + PICT_PROBE_SIZE : offset + PICT_PROBE_SIZE + PICT_V2_EXTENSION_SIZE
    ]
    if extension.startswith(PICT_V2_STANDARD_MARKER):
        return accepted_header_plan(
            location,
            pict_data,
            offset,
            2,
            False,
            top,
            left,
            bottom,
            right,
            None,
            None,
        )
    if extension.startswith(PICT_V2_EXTENDED_MARKER):
        x_resolution = read_fixed32s(extension, 8)
        y_resolution = read_fixed32s(extension, 12)
        return accepted_header_plan(
            location,
            pict_data,
            offset,
            2,
            True,
            top,
            left,
            bottom,
            right,
            x_resolution,
            y_resolution,
        )
    return empty_header_plan(
        location,
        (0, PICT_FILE_HEADER_SIZE) if offset else None,
        "unsupported_pict_header",
        (PICT_HEADER_GATE_SOURCE,),
    )


def accepted_header_plan(
    location: PictHeaderLocation,
    pict_data: bytes,
    offset: int,
    version: PictVersion,
    extended: bool,
    top: int,
    left: int,
    bottom: int,
    right: int,
    x_resolution: float | None,
    y_resolution: float | None,
) -> PictHeaderPlan:
    frame_width = right - left
    frame_height = bottom - top
    header_size = PICT_PROBE_SIZE if version == 1 else PICT_PROBE_SIZE + PICT_V2_EXTENSION_SIZE
    reason: PictEmissionGateCode | None = None
    if frame_width <= 0 or frame_height <= 0:
        reason = "invalid_pict_bounds"
    if extended and (not x_resolution or not y_resolution):
        reason = "invalid_pict_extended_resolution"
    image_width = frame_width
    image_height = frame_height
    if extended and x_resolution is not None and y_resolution is not None:
        image_width = int(frame_width * x_resolution / PICT_BASE_DPI + 0.5)
        image_height = int(frame_height * y_resolution / PICT_BASE_DPI + 0.5)
    file_header_range = (0, PICT_FILE_HEADER_SIZE) if offset == PICT_FILE_HEADER_SIZE else None
    header_range = (offset, offset + header_size)
    opcode_stream_range = (offset + header_size, len(pict_data))
    bounds = PictBoundsPlan(
        top=top,
        left=left,
        bottom=bottom,
        right=right,
        frame_width=frame_width,
        frame_height=frame_height,
        image_width=image_width if reason is None else None,
        image_height=image_height if reason is None else None,
        evidence_ids=(PICT_HEADER_GATE_SOURCE, PICT_EXTENDED_SOURCE),
    )
    resolution = PictResolutionPlan(
        x_resolution=x_resolution,
        y_resolution=y_resolution,
        evidence_ids=(PICT_EXTENDED_SOURCE,),
    )
    return PictHeaderPlan(
        header_location=location,
        file_header_range=file_header_range,
        header_range=header_range,
        opcode_stream_range=opcode_stream_range,
        version=version,
        extended=extended,
        bounds=bounds,
        resolution=resolution,
        reason=reason,
        evidence_ids=(PICT_HEADER_GATE_SOURCE, PICT_EXTENDED_SOURCE),
    )


def empty_header_plan(
    location: PictHeaderLocation | None,
    file_header_range: tuple[int, int] | None,
    reason: PictEmissionGateCode,
    sources: tuple[str, ...],
) -> PictHeaderPlan:
    return PictHeaderPlan(
        header_location=location,
        file_header_range=file_header_range,
        header_range=None,
        opcode_stream_range=None,
        version=None,
        extended=False,
        bounds=PictBoundsPlan(
            top=None,
            left=None,
            bottom=None,
            right=None,
            frame_width=None,
            frame_height=None,
            image_width=None,
            image_height=None,
            evidence_ids=sources,
        ),
        resolution=PictResolutionPlan(
            x_resolution=None,
            y_resolution=None,
            evidence_ids=(PICT_EXTENDED_SOURCE,),
        ),
        reason=reason,
        evidence_ids=sources,
    )


def build_pict_opcode_scan_plan(
    pict_data: bytes,
    header: PictHeaderPlan,
    scan_opcodes: bool,
) -> PictOpcodeScanPlan:
    if not scan_opcodes or not header.is_exiftool_accepted or header.opcode_stream_range is None:
        return PictOpcodeScanPlan(
            requested_by_oracle_options=scan_opcodes,
            scanned_range=None,
            opcodes=(),
            found_end_opcode=False,
            stop_reason=None,
            evidence_ids=(PICT_OPTIONAL_OPCODE_SOURCE,),
        )
    assert header.version is not None
    cursor = header.opcode_stream_range[0]
    index = 0
    opcodes: list[PictOpcodePlan] = []
    stop_reason: str | None = None
    found_end = False
    while cursor < len(pict_data):
        opcode, next_cursor, padding_range, truncated = read_opcode(
            pict_data,
            cursor,
            header.version,
        )
        if truncated or opcode is None:
            opcodes.append(
                PictOpcodePlan(
                    index=index,
                    opcode=0,
                    name="TruncatedOpcode",
                    kind="unknown",
                    payload_kind="unknown_remainder",
                    opcode_range=(cursor, len(pict_data)),
                    payload_range=(len(pict_data), len(pict_data)),
                    full_range=(cursor, len(pict_data)),
                    padding_range=padding_range,
                    embedded_kind=None,
                    reason="truncated_pict_opcode",
                    evidence_ids=(PICT_OPTIONAL_OPCODE_SOURCE,),
                )
            )
            stop_reason = "truncated_opcode"
            break
        if opcode == PICT_END_OPCODE:
            opcodes.append(
                PictOpcodePlan(
                    index=index,
                    opcode=opcode,
                    name="OpEndPic",
                    kind="end",
                    payload_kind="none",
                    opcode_range=(next_cursor - opcode_width(header.version), next_cursor),
                    payload_range=(next_cursor, next_cursor),
                    full_range=(cursor, next_cursor),
                    padding_range=padding_range,
                    embedded_kind=None,
                    reason=None,
                    evidence_ids=(PICT_MAIN_TABLE_SOURCE, PICT_OPCODE_READ_SOURCE),
                )
            )
            found_end = True
            stop_reason = "end_opcode"
            cursor = next_cursor
            break
        opcode_plan = build_opcode_plan(
            pict_data,
            index,
            opcode,
            cursor,
            next_cursor,
            padding_range,
            header.version,
        )
        opcodes.append(opcode_plan)
        if opcode_plan.reason is not None:
            stop_reason = "truncated_payload"
            cursor = opcode_plan.full_range[1]
            break
        if opcode_plan.kind == "unknown":
            stop_reason = "unknown_opcode"
            cursor = opcode_plan.full_range[1]
            break
        cursor = opcode_plan.full_range[1]
        index += 1
    return PictOpcodeScanPlan(
        requested_by_oracle_options=scan_opcodes,
        scanned_range=(header.opcode_stream_range[0], cursor),
        opcodes=tuple(opcodes),
        found_end_opcode=found_end,
        stop_reason=stop_reason,
        evidence_ids=(
            PICT_OPTIONAL_OPCODE_SOURCE,
            PICT_RESERVED_OPCODE_SOURCE,
            PICT_OPCODE_READ_SOURCE,
            PICT_READ_VALUE_SOURCE,
        ),
    )


def build_opcode_plan(
    pict_data: bytes,
    index: int,
    opcode: int,
    full_start: int,
    payload_start: int,
    padding_range: tuple[int, int] | None,
    version: PictVersion,
) -> PictOpcodePlan:
    opcode_start = payload_start - opcode_width(version)
    reserved_start = reserved_lookup_start(opcode)
    if opcode == 0x00A1:
        return variable_data_opcode_plan(
            pict_data,
            index,
            opcode,
            "LongComment",
            "known",
            "long_comment",
            full_start,
            opcode_start,
            payload_start,
            padding_range,
            2,
            2,
            PICT_COMMENT_KIND_SOURCE,
        )
    if reserved_start in PICT_INT16_DATA_STARTS:
        return variable_data_opcode_plan(
            pict_data,
            index,
            opcode,
            "Reserved",
            "reserved",
            "int16_data",
            full_start,
            opcode_start,
            payload_start,
            padding_range,
            2,
            0,
            PICT_RESERVED_OPCODE_SOURCE,
        )
    if reserved_start in PICT_INT32_DATA_STARTS:
        return variable_data_opcode_plan(
            pict_data,
            index,
            opcode,
            "Reserved",
            "reserved",
            "int32_data",
            full_start,
            opcode_start,
            payload_start,
            padding_range,
            4,
            0,
            PICT_RESERVED_OPCODE_SOURCE,
        )
    fixed = fixed_opcode(opcode, reserved_start)
    if fixed is not None:
        name, payload_size, kind = fixed
        payload_end = payload_start + payload_size
        reason: PictEmissionGateCode | None = None
        if payload_end > len(pict_data):
            payload_end = len(pict_data)
            reason = "truncated_pict_opcode_payload"
        return PictOpcodePlan(
            index=index,
            opcode=opcode,
            name=name,
            kind=kind,
            payload_kind="none" if payload_size == 0 else "fixed",
            opcode_range=(opcode_start, payload_start),
            payload_range=(payload_start, payload_end),
            full_range=(full_start, payload_end),
            padding_range=padding_range,
            embedded_kind=None,
            reason=reason,
            evidence_ids=(PICT_MAIN_TABLE_SOURCE, PICT_READ_VALUE_SOURCE),
        )
    return PictOpcodePlan(
        index=index,
        opcode=opcode,
        name="Unknown",
        kind="unknown",
        payload_kind="unknown_remainder",
        opcode_range=(opcode_start, payload_start),
        payload_range=(payload_start, len(pict_data)),
        full_range=(full_start, len(pict_data)),
        padding_range=padding_range,
        embedded_kind=None,
        reason=None,
        evidence_ids=(PICT_RESERVED_OPCODE_SOURCE, PICT_OPCODE_READ_SOURCE),
    )


def variable_data_opcode_plan(
    pict_data: bytes,
    index: int,
    opcode: int,
    name: str,
    kind: PictOpcodeKind,
    payload_kind: PictOpcodePayloadKind,
    full_start: int,
    opcode_start: int,
    payload_start: int,
    padding_range: tuple[int, int] | None,
    size_width: Literal[2, 4],
    leading_size_bytes: Literal[0, 2],
    extra_source: str,
) -> PictOpcodePlan:
    header_end = payload_start + leading_size_bytes + size_width
    if header_end > len(pict_data):
        return PictOpcodePlan(
            index=index,
            opcode=opcode,
            name=name,
            kind=kind,
            payload_kind=payload_kind,
            opcode_range=(opcode_start, payload_start),
            payload_range=(payload_start, len(pict_data)),
            full_range=(full_start, len(pict_data)),
            padding_range=padding_range,
            embedded_kind=None,
            reason="truncated_pict_opcode_payload",
            evidence_ids=(PICT_MAIN_TABLE_SOURCE, PICT_READ_VALUE_SOURCE, extra_source),
        )
    data_size_offset = payload_start + leading_size_bytes
    data_size = (
        read_u32be(pict_data, data_size_offset)
        if size_width == 4
        else read_u16be(pict_data, data_size_offset)
    )
    payload_end = header_end + data_size
    reason: PictEmissionGateCode | None = None
    if payload_end > len(pict_data):
        payload_end = len(pict_data)
        reason = "truncated_pict_opcode_payload"
    embedded_kind = None
    if opcode == 0x00A1 and header_end <= len(pict_data):
        embedded_kind = comment_kind_name(read_u16be(pict_data, payload_start))
    return PictOpcodePlan(
        index=index,
        opcode=opcode,
        name=name,
        kind=kind,
        payload_kind=payload_kind,
        opcode_range=(opcode_start, payload_start),
        payload_range=(payload_start, payload_end),
        full_range=(full_start, payload_end),
        padding_range=padding_range,
        embedded_kind=embedded_kind,
        reason=reason,
        evidence_ids=(PICT_MAIN_TABLE_SOURCE, PICT_READ_VALUE_SOURCE, extra_source),
    )


def build_pict_actions(
    header: PictHeaderPlan,
    opcode_scan: PictOpcodeScanPlan,
    rewrite_requests: tuple[PictRewriteRequest, ...],
) -> tuple[PictActionPlan, ...]:
    actions: list[PictActionPlan] = [
        PictActionPlan(
            kind="probe_header",
            target="pict_header",
            byte_range=header.header_range,
            reason="Mirror ExifTool's PICT resource/header recognition gate.",
            evidence_ids=(PICT_HEADER_GATE_SOURCE,),
        )
    ]
    if header.file_header_range is not None:
        actions.append(
            PictActionPlan(
                kind="skip_file_header",
                target="macbinary_or_file_header_prefix",
                byte_range=header.file_header_range,
                reason="ExifTool retries PICT recognition at offset 512 for PICT files.",
                evidence_ids=(PICT_HEADER_GATE_SOURCE,),
            )
        )
        actions.append(
            PictActionPlan(
                kind="preserve_prefix",
                target="macbinary_or_file_header_prefix",
                byte_range=header.file_header_range,
                reason="Keep the ignored 512-byte PICT file prefix unchanged.",
                evidence_ids=(PICT_HEADER_GATE_SOURCE, PICT_DESCRIPTION_SOURCE),
            )
        )
    if header.header_range is not None:
        actions.append(
            PictActionPlan(
                kind="preserve_header",
                target="pict_header",
                byte_range=header.header_range,
                reason="Keep the accepted PICT header bytes unchanged.",
                evidence_ids=(PICT_HEADER_GATE_SOURCE, PICT_DESCRIPTION_SOURCE),
            )
        )
    if header.is_exiftool_accepted:
        actions.append(
            PictActionPlan(
                kind="extract_image_bounds",
                target="image_bounds",
                byte_range=header.header_range,
                reason="Extract the signed PICT bounding rectangle and derived dimensions.",
                evidence_ids=(PICT_HEADER_GATE_SOURCE,),
            )
        )
    if header.extended:
        actions.append(
            PictActionPlan(
                kind="extract_extended_resolution",
                target="resolution",
                byte_range=header.header_range,
                reason="Extract fixed32 resolution from extended version 2 headers.",
                evidence_ids=(PICT_EXTENDED_SOURCE,),
            )
        )
    if opcode_scan.scanned_range is not None:
        actions.append(
            PictActionPlan(
                kind="scan_opcode_stream",
                target="opcode_stream",
                byte_range=opcode_scan.scanned_range,
                reason="Mirror the optional Verbose/Unknown opcode scan boundaries.",
                evidence_ids=(PICT_OPTIONAL_OPCODE_SOURCE,),
            )
        )
    for opcode in opcode_scan.opcodes:
        action_kind: PictActionKind = "preserve_opcode"
        if opcode.kind == "unknown":
            action_kind = "preserve_unknown_opcode_remainder"
        if opcode.payload_kind == "long_comment":
            action_kind = "preserve_embedded_payload"
        actions.append(
            PictActionPlan(
                kind=action_kind,
                target=f"{opcode.name}:0x{opcode.opcode:04x}",
                byte_range=opcode.full_range,
                reason="Keep source opcode bytes unchanged.",
                evidence_ids=opcode.evidence_ids,
            )
        )
    for request in rewrite_requests:
        actions.append(
            PictActionPlan(
                kind="block_requested_rewrite",
                target=f"{request.operation}:{request.target}",
                byte_range=None,
                reason="PICT.pm does not provide a writer for this requested mutation.",
                evidence_ids=(PICT_DESCRIPTION_SOURCE,),
            )
        )
    return tuple(actions)


def read_opcode(
    pict_data: bytes,
    cursor: int,
    version: PictVersion,
) -> tuple[int | None, int, tuple[int, int] | None, bool]:
    padding_range: tuple[int, int] | None = None
    if version == 2 and cursor & 0x01:
        padding_range = (cursor, min(cursor + 1, len(pict_data)))
        cursor += 1
    width = opcode_width(version)
    if cursor + width > len(pict_data):
        return None, cursor, padding_range, True
    if version == 1:
        return pict_data[cursor], cursor + 1, padding_range, False
    return read_u16be(pict_data, cursor), cursor + 2, padding_range, False


def fixed_opcode(opcode: int, reserved_start: int | None) -> tuple[str, int, PictOpcodeKind] | None:
    fixed = PICT_FIXED_OPCODE_SIZES.get(opcode)
    if fixed is not None:
        name, size = fixed
        return name, size, "known"
    if reserved_start in PICT_RECT_RESERVED_STARTS:
        return "Reserved", 8, "reserved"
    if reserved_start in PICT_NULL_RESERVED_STARTS:
        return "Reserved", 0, "reserved"
    if reserved_start == 0x006D:
        return "Reserved", 4, "reserved"
    return None


def reserved_lookup_start(opcode: int) -> int | None:
    for start, end, lookup_start in PICT_RESERVED_RANGES:
        if start <= opcode <= end:
            return lookup_start
    return None


def opcode_width(version: PictVersion) -> int:
    if version == 1:
        return 1
    return 2


def comment_kind_name(kind: int) -> str | None:
    names = {
        150: "TextBegin",
        151: "TextEnd",
        152: "StringBegin",
        153: "StringEnd",
        154: "TextCenter",
        155: "LineLayoutOff",
        156: "LineLayoutOn",
        157: "ClientLineLayout",
        160: "PolyBegin",
        161: "PolyEnd",
        163: "PolyIgnore",
        164: "PolySmooth",
        165: "PolyClose",
        180: "DashedLine",
        181: "DashedStop",
        182: "SetLineWidth",
        190: "PostScriptBegin",
        191: "PostScriptEnd",
        192: "PostScriptHandle",
        193: "PostScriptFile",
        194: "TextIsPostScript",
        195: "ResourcePS",
        196: "PSBeginNoSave",
        197: "SetGrayLevel",
        200: "RotateBegin",
        201: "RotateEnd",
        202: "RotateCenter",
        210: "FormsPrinting",
        211: "EndFormsPrinting",
        224: "<ICC Profile>",
        498: "<Photoshop Data>",
        1000: "BitMapThinningOff",
        1001: "BitMapThinningOn",
    }
    return names.get(kind)


def add_non_mutating_gate(
    gates: list[PictOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        PictOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="PICT transaction plans are preserve-only unless output emission is explicit.",
            evidence_ids=(PICT_DESCRIPTION_SOURCE,),
        )
    )


def structural_gate_present(gates: tuple[PictOutputEmissionGate, ...]) -> bool:
    non_structural_codes = {
        "rewrite_requested_requires_pict_writer",
        "non_mutating_plan_requires_explicit_emission",
    }
    return any(gate.code not in non_structural_codes for gate in gates)


def unique_emission_gates(
    gates: tuple[PictOutputEmissionGate, ...],
) -> tuple[PictOutputEmissionGate, ...]:
    seen: set[PictEmissionGateCode] = set()
    unique: list[PictOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def read_u16be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def read_i16be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big", signed=True)


def read_u32be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def read_fixed32s(data: bytes, offset: int) -> float:
    raw = int.from_bytes(data[offset : offset + 4], "big", signed=True)
    return raw / 65536.0


plan_pict_image_transaction = build_pict_image_transaction_plan
