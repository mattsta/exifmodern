"""Source-grounded, non-mutating Radiance RGBE/HDR image transaction plans.

The planner mirrors ExifTool's Radiance.pm reader: accept only #?RADIANCE and
#?RGBE signatures, parse variable text header lines until the first blank or
oversized line, extract comments, commands, and key-value metadata, read the
resolution line for orientation plus dimensions, and preserve the remaining
pixel bytes without decoding them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RADIANCE_MAX_HEADER_LINE_LENGTH = 4095
RADIANCE_SIGNATURE_RE = re.compile(rb"^#\?(RADIANCE|RGBE)\n", re.DOTALL)
RADIANCE_ASSIGNMENT_RE = re.compile(r"^(.*)?\s*=\s*(.*)")
RADIANCE_RESOLUTION_RE = re.compile(r"([-+][XY])\s*(\d+)\s*([-+][XY])\s*(\d+)")

type RadiancePlanStatus = Literal["planned", "unsupported"]
type RadianceSignatureKind = Literal["RADIANCE", "RGBE"]
type RadianceHeaderLineKind = Literal["comment", "command", "known_metadata", "dynamic_metadata"]
type RadianceKnownTagName = Literal[
    "software",
    "view",
    "format",
    "exposure",
    "gamma",
    "colorcorr",
    "pixaspect",
    "primaries",
]
type RadianceActionKind = Literal[
    "validate_signature",
    "extract_comment",
    "extract_command",
    "extract_known_metadata",
    "extract_dynamic_metadata",
    "parse_resolution_line",
    "preserve_pixel_data",
    "block_requested_rewrite",
]
type RadianceEmissionGateCode = Literal[
    "truncated_radiance_signature",
    "unsupported_radiance_signature",
    "truncated_radiance_header",
    "malformed_radiance_header_line",
    "missing_radiance_resolution_line",
    "malformed_radiance_resolution_line",
    "radiance_rewrite_not_implemented",
    "non_mutating_plan_requires_explicit_emission",
]

RADIANCE_DESCRIPTION_SOURCE = "radiance.description"
RADIANCE_TAG_TABLE_SOURCE = "radiance.tag_table"
RADIANCE_SIGNATURE_SOURCE = "radiance.signature"
RADIANCE_HEADER_LOOP_SOURCE = "radiance.header_loop"
RADIANCE_METADATA_SOURCE = "radiance.metadata"
RADIANCE_RESOLUTION_SOURCE = "radiance.resolution"
RADIANCE_READ_ONLY_SOURCE = "radiance.read_only"

RADIANCE_TRANSACTION_SOURCES = (
    RADIANCE_DESCRIPTION_SOURCE,
    RADIANCE_TAG_TABLE_SOURCE,
    RADIANCE_SIGNATURE_SOURCE,
    RADIANCE_HEADER_LOOP_SOURCE,
    RADIANCE_METADATA_SOURCE,
    RADIANCE_RESOLUTION_SOURCE,
    RADIANCE_READ_ONLY_SOURCE,
)

KNOWN_TAG_DISPLAY_NAMES: dict[RadianceKnownTagName, str] = {
    "software": "Software",
    "view": "View",
    "format": "Format",
    "exposure": "Exposure",
    "gamma": "Gamma",
    "colorcorr": "ColorCorrection",
    "pixaspect": "PixelAspectRatio",
    "primaries": "ColorPrimaries",
}
ORIENTATION_PRINT_VALUES: dict[str, str] = {
    "-Y +X": "Horizontal (normal)",
    "-Y -X": "Mirror horizontal",
    "+Y -X": "Rotate 180",
    "+Y +X": "Mirror vertical",
    "+X -Y": "Mirror horizontal and rotate 270 CW",
    "+X +Y": "Rotate 90 CW",
    "-X +Y": "Mirror horizontal and rotate 90 CW",
    "-X -Y": "Rotate 270 CW",
}


@dataclass(frozen=True)
class RadianceOutputEmissionGate:
    code: RadianceEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RadianceSignaturePlan:
    raw_line: str | None
    kind: RadianceSignatureKind | None
    byte_range: tuple[int, int] | None
    supported_by_oracle: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RadianceHeaderEntryPlan:
    kind: RadianceHeaderLineKind
    raw_line: str
    byte_range: tuple[int, int]
    tag_key: str | None
    tag_name: str
    value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RadianceMetadataResponsibilityPlan:
    tag_key: RadianceKnownTagName
    tag_name: str
    extracted_value: str | None
    present: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RadianceHeaderPlan:
    entries: tuple[RadianceHeaderEntryPlan, ...]
    header_start_offset: int | None
    header_end_offset: int | None
    terminator_range: tuple[int, int] | None
    terminated_by: Literal["blank_line", "oversized_line", "eof", "unavailable"]
    metadata_responsibilities: tuple[RadianceMetadataResponsibilityPlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RadianceResolutionPlan:
    raw_line: str | None
    byte_range: tuple[int, int] | None
    orientation_axes: str | None
    orientation_description: str | None
    image_height: int | None
    image_width: int | None
    parsed: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RadiancePixelDataPlan:
    start_offset: int | None
    end_offset: int
    observed_length: int | None
    action: Literal["preserve", "unavailable"]
    validation_model: Literal[
        "preserved_after_resolution_line_without_pixel_decode",
        "unavailable_without_resolution_line",
    ]
    evidence_ids: tuple[str, ...]

    @property
    def byte_range(self) -> tuple[int, int] | None:
        if self.start_offset is None:
            return None
        return (self.start_offset, self.end_offset)


@dataclass(frozen=True)
class RadianceRewriteRequest:
    target: Literal["comment", "command", "metadata", "resolution"]
    operation: Literal["replace", "delete", "insert"]
    value: str | None = None


@dataclass(frozen=True)
class RadianceActionPlan:
    kind: RadianceActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RadianceImageTransactionPlan:
    status: RadiancePlanStatus
    source_data: bytes
    signature: RadianceSignaturePlan
    header: RadianceHeaderPlan
    resolution: RadianceResolutionPlan
    pixel_data: RadiancePixelDataPlan
    rewrite_requests: tuple[RadianceRewriteRequest, ...]
    actions: tuple[RadianceActionPlan, ...]
    output_emission_gates: tuple[RadianceOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Radiance image transaction output is gated: {gate_codes}")
        return self.source_data


@dataclass(frozen=True)
class _LineRead:
    line: bytes
    byte_range: tuple[int, int]
    has_lf: bool
    next_offset: int


def build_radiance_image_transaction_plan(
    radiance_data: bytes,
    *,
    rewrite_requests: tuple[RadianceRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> RadianceImageTransactionPlan:
    """Build a source-backed Radiance RGBE/HDR transaction plan."""

    gates: list[RadianceOutputEmissionGate] = []
    actions: list[RadianceActionPlan] = []
    signature_line = _read_line(radiance_data, 0)
    if signature_line is None:
        gates.append(
            RadianceOutputEmissionGate(
                code="truncated_radiance_signature",
                reason="Input does not contain the LF-terminated Radiance signature line.",
                evidence_ids=(RADIANCE_SIGNATURE_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=radiance_data,
            signature=_empty_signature(),
            header=_empty_header("unavailable"),
            resolution=_empty_resolution(),
            pixel_data=_unavailable_pixel_data(radiance_data),
            rewrite_requests=rewrite_requests,
            actions=(),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    signature = _signature_from_line(signature_line)
    if signature.kind is None:
        gate_code: RadianceEmissionGateCode = (
            "truncated_radiance_signature"
            if _has_supported_signature_without_lf(signature_line)
            else "unsupported_radiance_signature"
        )
        gates.append(
            RadianceOutputEmissionGate(
                code=gate_code,
                reason=(
                    "Input does not contain the LF required by ExifTool's Radiance signature gate."
                    if gate_code == "truncated_radiance_signature"
                    else "Input does not match ExifTool's #?RADIANCE or #?RGBE signature gate."
                ),
                evidence_ids=(RADIANCE_SIGNATURE_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=radiance_data,
            signature=signature,
            header=_empty_header("unavailable"),
            resolution=_empty_resolution(),
            pixel_data=_unavailable_pixel_data(radiance_data),
            rewrite_requests=rewrite_requests,
            actions=(),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    actions.append(
        RadianceActionPlan(
            kind="validate_signature",
            target=signature.kind,
            byte_range=signature.byte_range,
            reason="Input satisfied ExifTool's Radiance signature gate.",
            evidence_ids=(RADIANCE_SIGNATURE_SOURCE,),
        )
    )

    header, header_gates, header_actions = _parse_header(radiance_data, signature_line.next_offset)
    gates.extend(header_gates)
    actions.extend(header_actions)
    resolution, resolution_gate = _parse_resolution(radiance_data, header.header_end_offset)
    if resolution_gate is not None:
        gates.append(resolution_gate)
    else:
        actions.append(
            RadianceActionPlan(
                kind="parse_resolution_line",
                target="Orientation/ImageHeight/ImageWidth",
                byte_range=resolution.byte_range,
                reason=(
                    "The post-header resolution line provides orientation axes and "
                    "the two image dimensions."
                ),
                evidence_ids=(RADIANCE_RESOLUTION_SOURCE, RADIANCE_TAG_TABLE_SOURCE),
            )
        )

    pixel_data = _pixel_data_plan(radiance_data, resolution)
    if pixel_data.action == "preserve":
        actions.append(
            RadianceActionPlan(
                kind="preserve_pixel_data",
                target="pixel_data",
                byte_range=pixel_data.byte_range,
                reason=(
                    "Radiance.pm stops metadata extraction after the resolution line, "
                    "so the planner preserves remaining pixel bytes unchanged."
                ),
                evidence_ids=(RADIANCE_RESOLUTION_SOURCE, RADIANCE_READ_ONLY_SOURCE),
            )
        )

    for request in rewrite_requests:
        gates.append(
            RadianceOutputEmissionGate(
                code="radiance_rewrite_not_implemented",
                reason=(
                    f"Radiance {request.operation} for {request.target} is blocked because "
                    "the oracle module does not define a byte writer."
                ),
                evidence_ids=(RADIANCE_READ_ONLY_SOURCE,),
            )
        )
        actions.append(
            RadianceActionPlan(
                kind="block_requested_rewrite",
                target=request.target,
                byte_range=None,
                reason=(
                    "Rewrite requests are surfaced but this planner does not mutate Radiance bytes."
                ),
                evidence_ids=(RADIANCE_READ_ONLY_SOURCE,),
            )
        )

    status: RadiancePlanStatus = "unsupported" if _has_hard_gate(gates) else "planned"
    return _final_plan(
        status=status,
        source_data=radiance_data,
        signature=signature,
        header=header,
        resolution=resolution,
        pixel_data=pixel_data,
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        gates=gates,
        allow_output_emission=allow_output_emission,
    )


def _read_line(data: bytes, offset: int) -> _LineRead | None:
    if offset >= len(data):
        return None
    line_end = data.find(b"\n", offset)
    if line_end < 0:
        return _LineRead(
            line=data[offset:],
            byte_range=(offset, len(data)),
            has_lf=False,
            next_offset=len(data),
        )
    next_offset = line_end + 1
    return _LineRead(
        line=data[offset:next_offset],
        byte_range=(offset, next_offset),
        has_lf=True,
        next_offset=next_offset,
    )


def _signature_from_line(line_read: _LineRead) -> RadianceSignaturePlan:
    match = RADIANCE_SIGNATURE_RE.match(line_read.line)
    if match is None:
        return RadianceSignaturePlan(
            raw_line=line_read.line.decode("latin-1"),
            kind=None,
            byte_range=line_read.byte_range,
            supported_by_oracle=False,
            evidence_ids=(RADIANCE_SIGNATURE_SOURCE,),
        )
    kind: RadianceSignatureKind = "RADIANCE" if match.group(1) == b"RADIANCE" else "RGBE"
    return RadianceSignaturePlan(
        raw_line=line_read.line.decode("latin-1"),
        kind=kind,
        byte_range=line_read.byte_range,
        supported_by_oracle=True,
        evidence_ids=(RADIANCE_SIGNATURE_SOURCE,),
    )


def _has_supported_signature_without_lf(line_read: _LineRead) -> bool:
    return not line_read.has_lf and line_read.line in {b"#?RADIANCE", b"#?RGBE"}


def _parse_header(
    data: bytes,
    offset: int,
) -> tuple[
    RadianceHeaderPlan,
    tuple[RadianceOutputEmissionGate, ...],
    tuple[RadianceActionPlan, ...],
]:
    gates: list[RadianceOutputEmissionGate] = []
    actions: list[RadianceActionPlan] = []
    entries: list[RadianceHeaderEntryPlan] = []
    cursor = offset
    header_end_offset: int | None = None
    terminator_range: tuple[int, int] | None = None
    terminated_by: Literal["blank_line", "oversized_line", "eof", "unavailable"] = "eof"

    while True:
        line_read = _read_line(data, cursor)
        if line_read is None:
            gates.append(
                RadianceOutputEmissionGate(
                    code="missing_radiance_resolution_line",
                    reason="Input ended before a Radiance header terminator and resolution line.",
                    evidence_ids=(RADIANCE_HEADER_LOOP_SOURCE, RADIANCE_RESOLUTION_SOURCE),
                )
            )
            header_end_offset = None
            break
        line_without_lf = line_read.line[:-1] if line_read.has_lf else line_read.line
        if not line_read.has_lf:
            gates.append(
                RadianceOutputEmissionGate(
                    code="truncated_radiance_header",
                    reason="A Radiance header line was not LF-terminated.",
                    evidence_ids=(RADIANCE_HEADER_LOOP_SOURCE,),
                )
            )
            header_end_offset = None
            break
        if len(line_without_lf) == 0:
            header_end_offset = line_read.next_offset
            terminator_range = line_read.byte_range
            terminated_by = "blank_line"
            break
        if len(line_without_lf) > RADIANCE_MAX_HEADER_LINE_LENGTH:
            gates.append(
                RadianceOutputEmissionGate(
                    code="malformed_radiance_header_line",
                    reason=(
                        "ExifTool stops variable header parsing when a line is "
                        "4096 bytes or longer."
                    ),
                    evidence_ids=(RADIANCE_HEADER_LOOP_SOURCE,),
                )
            )
            header_end_offset = line_read.next_offset
            terminator_range = line_read.byte_range
            terminated_by = "oversized_line"
            break

        entry = _header_entry_from_line(line_without_lf, line_read.byte_range)
        entries.append(entry)
        if entry.kind == "comment":
            actions.append(
                RadianceActionPlan(
                    kind="extract_comment",
                    target="Comment",
                    byte_range=entry.byte_range,
                    reason="Hash-prefixed non-empty header lines are routed to the Comment tag.",
                    evidence_ids=(RADIANCE_HEADER_LOOP_SOURCE, RADIANCE_TAG_TABLE_SOURCE),
                )
            )
        elif entry.kind == "command":
            actions.append(
                RadianceActionPlan(
                    kind="extract_command",
                    target="Command",
                    byte_range=entry.byte_range,
                    reason=(
                        "Non-empty header lines without an assignment are routed to "
                        "the Command tag."
                    ),
                    evidence_ids=(RADIANCE_HEADER_LOOP_SOURCE, RADIANCE_TAG_TABLE_SOURCE),
                )
            )
        elif entry.kind == "known_metadata":
            actions.append(
                RadianceActionPlan(
                    kind="extract_known_metadata",
                    target=entry.tag_name,
                    byte_range=entry.byte_range,
                    reason=(
                        "Known Radiance assignment keys are lowercased and routed "
                        "through the tag table."
                    ),
                    evidence_ids=(RADIANCE_METADATA_SOURCE, RADIANCE_TAG_TABLE_SOURCE),
                )
            )
        else:
            actions.append(
                RadianceActionPlan(
                    kind="extract_dynamic_metadata",
                    target=entry.tag_name,
                    byte_range=entry.byte_range,
                    reason="Unknown assignment keys are sanitized into dynamic tag names.",
                    evidence_ids=(RADIANCE_METADATA_SOURCE,),
                )
            )
        cursor = line_read.next_offset

    header = RadianceHeaderPlan(
        entries=tuple(entries),
        header_start_offset=offset,
        header_end_offset=header_end_offset,
        terminator_range=terminator_range,
        terminated_by=terminated_by,
        metadata_responsibilities=_metadata_responsibilities(tuple(entries)),
        evidence_ids=(RADIANCE_HEADER_LOOP_SOURCE, RADIANCE_METADATA_SOURCE),
    )
    return header, tuple(gates), tuple(actions)


def _header_entry_from_line(
    raw_line_bytes: bytes,
    byte_range: tuple[int, int],
) -> RadianceHeaderEntryPlan:
    raw_line = raw_line_bytes.decode("latin-1")
    if raw_line.startswith("#"):
        value = raw_line[1:].lstrip(" ")
        return RadianceHeaderEntryPlan(
            kind="comment",
            raw_line=raw_line,
            byte_range=byte_range,
            tag_key=None,
            tag_name="Comment",
            value=value,
            evidence_ids=(RADIANCE_HEADER_LOOP_SOURCE, RADIANCE_TAG_TABLE_SOURCE),
        )

    assignment = RADIANCE_ASSIGNMENT_RE.match(raw_line)
    if assignment is None:
        return RadianceHeaderEntryPlan(
            kind="command",
            raw_line=raw_line,
            byte_range=byte_range,
            tag_key=None,
            tag_name="Command",
            value=raw_line,
            evidence_ids=(RADIANCE_HEADER_LOOP_SOURCE, RADIANCE_TAG_TABLE_SOURCE),
        )

    tag_key = assignment.group(1).lower()
    value = assignment.group(2)
    known_tag = _known_tag_key(tag_key)
    if known_tag is not None:
        return RadianceHeaderEntryPlan(
            kind="known_metadata",
            raw_line=raw_line,
            byte_range=byte_range,
            tag_key=tag_key,
            tag_name=KNOWN_TAG_DISPLAY_NAMES[known_tag],
            value=value,
            evidence_ids=(RADIANCE_METADATA_SOURCE, RADIANCE_TAG_TABLE_SOURCE),
        )
    return RadianceHeaderEntryPlan(
        kind="dynamic_metadata",
        raw_line=raw_line,
        byte_range=byte_range,
        tag_key=tag_key,
        tag_name=_dynamic_tag_name(tag_key),
        value=value,
        evidence_ids=(RADIANCE_METADATA_SOURCE,),
    )


def _known_tag_key(tag_key: str) -> RadianceKnownTagName | None:
    for known_key in KNOWN_TAG_DISPLAY_NAMES:
        if tag_key == known_key:
            return known_key
    return None


def _dynamic_tag_name(tag_key: str) -> str:
    sanitized = "".join(character for character in tag_key if _is_dynamic_tag_character(character))
    if len(sanitized) <= 1:
        return ""
    return sanitized[:1].upper() + sanitized[1:]


def _is_dynamic_tag_character(character: str) -> bool:
    return (
        character == "-"
        or character == "_"
        or "a" <= character <= "z"
        or "A" <= character <= "Z"
        or "0" <= character <= "9"
    )


def _metadata_responsibilities(
    entries: tuple[RadianceHeaderEntryPlan, ...],
) -> tuple[RadianceMetadataResponsibilityPlan, ...]:
    responsibilities: list[RadianceMetadataResponsibilityPlan] = []
    for tag_key, tag_name in KNOWN_TAG_DISPLAY_NAMES.items():
        value = _first_known_value(entries, tag_key)
        responsibilities.append(
            RadianceMetadataResponsibilityPlan(
                tag_key=tag_key,
                tag_name=tag_name,
                extracted_value=value,
                present=value is not None,
                evidence_ids=(RADIANCE_TAG_TABLE_SOURCE, RADIANCE_METADATA_SOURCE),
            )
        )
    return tuple(responsibilities)


def _first_known_value(
    entries: tuple[RadianceHeaderEntryPlan, ...],
    tag_key: RadianceKnownTagName,
) -> str | None:
    for entry in entries:
        if entry.tag_key == tag_key:
            return entry.value
    return None


def _parse_resolution(
    data: bytes,
    header_end_offset: int | None,
) -> tuple[RadianceResolutionPlan, RadianceOutputEmissionGate | None]:
    if header_end_offset is None:
        return (
            _empty_resolution(),
            RadianceOutputEmissionGate(
                code="missing_radiance_resolution_line",
                reason=(
                    "The planner cannot locate a resolution line without a complete "
                    "header boundary."
                ),
                evidence_ids=(RADIANCE_HEADER_LOOP_SOURCE, RADIANCE_RESOLUTION_SOURCE),
            ),
        )
    line_read = _read_line(data, header_end_offset)
    if line_read is None:
        return (
            _empty_resolution(),
            RadianceOutputEmissionGate(
                code="missing_radiance_resolution_line",
                reason="Input ended before the Radiance resolution line.",
                evidence_ids=(RADIANCE_RESOLUTION_SOURCE,),
            ),
        )
    if not line_read.has_lf:
        return (
            RadianceResolutionPlan(
                raw_line=line_read.line.decode("latin-1"),
                byte_range=line_read.byte_range,
                orientation_axes=None,
                orientation_description=None,
                image_height=None,
                image_width=None,
                parsed=False,
                evidence_ids=(RADIANCE_RESOLUTION_SOURCE,),
            ),
            RadianceOutputEmissionGate(
                code="malformed_radiance_resolution_line",
                reason="The Radiance resolution line is not LF-terminated.",
                evidence_ids=(RADIANCE_RESOLUTION_SOURCE,),
            ),
        )
    raw_line = line_read.line[:-1].decode("latin-1")
    match = RADIANCE_RESOLUTION_RE.search(raw_line)
    if match is None:
        return (
            RadianceResolutionPlan(
                raw_line=raw_line,
                byte_range=line_read.byte_range,
                orientation_axes=None,
                orientation_description=None,
                image_height=None,
                image_width=None,
                parsed=False,
                evidence_ids=(RADIANCE_RESOLUTION_SOURCE,),
            ),
            RadianceOutputEmissionGate(
                code="malformed_radiance_resolution_line",
                reason=(
                    "The post-header line does not match ExifTool's Radiance resolution pattern."
                ),
                evidence_ids=(RADIANCE_RESOLUTION_SOURCE,),
            ),
        )
    orientation_axes = f"{match.group(1)} {match.group(3)}"
    return (
        RadianceResolutionPlan(
            raw_line=raw_line,
            byte_range=line_read.byte_range,
            orientation_axes=orientation_axes,
            orientation_description=ORIENTATION_PRINT_VALUES.get(orientation_axes),
            image_height=int(match.group(2)),
            image_width=int(match.group(4)),
            parsed=True,
            evidence_ids=(RADIANCE_RESOLUTION_SOURCE, RADIANCE_TAG_TABLE_SOURCE),
        ),
        None,
    )


def _pixel_data_plan(data: bytes, resolution: RadianceResolutionPlan) -> RadiancePixelDataPlan:
    if resolution.byte_range is None or not resolution.parsed:
        return _unavailable_pixel_data(data)
    start_offset = resolution.byte_range[1]
    return RadiancePixelDataPlan(
        start_offset=start_offset,
        end_offset=len(data),
        observed_length=len(data) - start_offset,
        action="preserve",
        validation_model="preserved_after_resolution_line_without_pixel_decode",
        evidence_ids=(RADIANCE_RESOLUTION_SOURCE, RADIANCE_READ_ONLY_SOURCE),
    )


def _empty_signature() -> RadianceSignaturePlan:
    return RadianceSignaturePlan(
        raw_line=None,
        kind=None,
        byte_range=None,
        supported_by_oracle=False,
        evidence_ids=(RADIANCE_SIGNATURE_SOURCE,),
    )


def _empty_header(
    terminated_by: Literal["blank_line", "oversized_line", "eof", "unavailable"],
) -> RadianceHeaderPlan:
    return RadianceHeaderPlan(
        entries=(),
        header_start_offset=None,
        header_end_offset=None,
        terminator_range=None,
        terminated_by=terminated_by,
        metadata_responsibilities=_metadata_responsibilities(()),
        evidence_ids=(RADIANCE_HEADER_LOOP_SOURCE, RADIANCE_METADATA_SOURCE),
    )


def _empty_resolution() -> RadianceResolutionPlan:
    return RadianceResolutionPlan(
        raw_line=None,
        byte_range=None,
        orientation_axes=None,
        orientation_description=None,
        image_height=None,
        image_width=None,
        parsed=False,
        evidence_ids=(RADIANCE_RESOLUTION_SOURCE,),
    )


def _unavailable_pixel_data(data: bytes) -> RadiancePixelDataPlan:
    return RadiancePixelDataPlan(
        start_offset=None,
        end_offset=len(data),
        observed_length=None,
        action="unavailable",
        validation_model="unavailable_without_resolution_line",
        evidence_ids=(RADIANCE_RESOLUTION_SOURCE, RADIANCE_READ_ONLY_SOURCE),
    )


def _final_plan(
    *,
    status: RadiancePlanStatus,
    source_data: bytes,
    signature: RadianceSignaturePlan,
    header: RadianceHeaderPlan,
    resolution: RadianceResolutionPlan,
    pixel_data: RadiancePixelDataPlan,
    rewrite_requests: tuple[RadianceRewriteRequest, ...],
    actions: tuple[RadianceActionPlan, ...],
    gates: list[RadianceOutputEmissionGate],
    allow_output_emission: bool,
) -> RadianceImageTransactionPlan:
    if not allow_output_emission:
        gates.append(
            RadianceOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason=(
                    "Radiance image transaction plans are non-mutating unless emission is allowed."
                ),
                evidence_ids=(RADIANCE_READ_ONLY_SOURCE,),
            )
        )
    return RadianceImageTransactionPlan(
        status=status,
        source_data=source_data,
        signature=signature,
        header=header,
        resolution=resolution,
        pixel_data=pixel_data,
        rewrite_requests=rewrite_requests,
        actions=actions,
        output_emission_gates=_unique_gates(tuple(gates)),
        evidence_ids=_unique_sources(
            signature.evidence_ids
            + header.evidence_ids
            + resolution.evidence_ids
            + pixel_data.evidence_ids
            + tuple(reference for action in actions for reference in action.evidence_ids)
            + tuple(reference for gate in gates for reference in gate.evidence_ids)
        ),
    )


def _has_hard_gate(gates: list[RadianceOutputEmissionGate]) -> bool:
    return any(
        gate.code
        in {
            "truncated_radiance_signature",
            "unsupported_radiance_signature",
            "truncated_radiance_header",
            "malformed_radiance_header_line",
            "missing_radiance_resolution_line",
            "malformed_radiance_resolution_line",
        }
        for gate in gates
    )


def _unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        unique.append(source)
    return tuple(unique)


def _unique_gates(
    gates: tuple[RadianceOutputEmissionGate, ...],
) -> tuple[RadianceOutputEmissionGate, ...]:
    unique: list[RadianceOutputEmissionGate] = []
    seen: set[RadianceEmissionGateCode] = set()
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


plan_radiance_image_transaction = build_radiance_image_transaction_plan
