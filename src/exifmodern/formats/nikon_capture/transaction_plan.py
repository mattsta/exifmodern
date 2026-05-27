"""Source-grounded Nikon Capture metadata transaction planning.

The planner mirrors the Nikon Capture directory and edit-version traversal in
``/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/NikonCapture.pm`` plus the
MakerNote surfaces declared in ``Nikon.pm``.  It preserves source bytes and
records routing decisions; it does not synthesize rewritten Nikon Capture data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

NIKON_CAPTURE_SOURCE_PATH = "lib/Image/ExifTool/NikonCapture.pm"
NIKON_SOURCE_PATH = "lib/Image/ExifTool/Nikon.pm"

NIKON_CAPTURE_MAGIC = 0x7A86A940
NIKON_CAPTURE_HEADER_SIZE = 22
NIKON_CAPTURE_FIXED_HEADER_SIZE = 18
NIKON_CAPTURE_ENTRY_HEADER_SIZE = 22
NIKON_CAPTURE_ENTRY_PREFIX_SIZE = 18
NIKON_CAPTURE_SIZE_WORD_BIAS = 4

type NikonCaptureSurface = Literal["auto", "nikon_capture", "edit_versions"]
type NikonCaptureInputKind = Literal["nikon_capture", "edit_versions", "unknown"]
type NikonCapturePlanStatus = Literal["planned", "blocked", "unsupported"]
type NikonCaptureTagResponsibility = Literal[
    "writable_scalar",
    "binary_payload",
    "binary_xml_payload",
    "capture_subdirectory",
    "iptc_subdirectory",
    "unknown_payload",
]
type NikonCaptureRouteAction = Literal[
    "route_writable_scalar",
    "route_binary_payload",
    "route_capture_subdirectory",
    "route_iptc_subdirectory",
    "preserve_unknown_entry",
    "preserve_nx2_size_tail",
    "preserve_trailing_padding",
]
type NikonCaptureGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "unrecognized_nikon_capture_input",
    "short_nikon_capture_data",
    "unrecognized_nikon_capture_header",
    "entry_size_word_underflow",
    "truncated_entry_payload",
    "improperly_terminated_nikon_capture_data",
    "short_edit_versions_data",
    "truncated_edit_version_length",
    "truncated_edit_version_payload",
    "unconsumed_edit_version_records",
    "unsupported_nikon_capture_rewrite",
    "unsupported_edit_versions_rewrite",
]

NIKON_CAPTURE_MAIN_SOURCE = "nikon.capture.main"
NIKON_CAPTURE_MAIN_TAGS_SOURCE = "nikon.capture.main-tags"
NIKON_CAPTURE_BINARY_TABLES_SOURCE = "nikon.capture.binary-tables"
NIKON_CAPTURE_WRITE_SOURCE = "nikon.capture.write"
NIKON_CAPTURE_PROCESS_SOURCE = "nikon.capture.process"
NIKON_CAPTURE_EDIT_PROCESS_SOURCE = "nikon.capture.edit-process"
NIKON_CAPTURE_MAKERNOTE_SOURCE = "nikon.capture.makernote-route"
NIKON_CAPTURE_EDIT_SURFACE_SOURCE = "nikon.capture.edit-surface"


@dataclass(frozen=True)
class NikonCaptureTagDefinition:
    tag_id: int
    tag_name: str
    responsibility: NikonCaptureTagResponsibility
    writable_format: str | None
    subdirectory_table: str | None
    binary: bool
    adjust_size: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCaptureRewriteTagRequest:
    tag_name: str
    payload: bytes


@dataclass(frozen=True)
class NikonCaptureRewriteRequest:
    tags: tuple[NikonCaptureRewriteTagRequest, ...] = ()
    edit_versions_payload: bytes | None = None

    @property
    def has_changes(self) -> bool:
        return bool(self.tags or self.edit_versions_payload is not None)


@dataclass(frozen=True)
class NikonCaptureEmissionGate:
    code: NikonCaptureGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCaptureByteRange:
    start_offset: int
    end_offset: int

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset


@dataclass(frozen=True)
class NikonCaptureHeaderPlan:
    tag_id: int
    declared_size: int
    effective_directory_range: NikonCaptureByteRange
    trailing_padding_range: NikonCaptureByteRange | None
    legacy_size_includes_header: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCaptureEntryPlan:
    index: int
    tag_id: int
    tag_id_hex: str
    tag_name: str | None
    responsibility: NikonCaptureTagResponsibility
    action: NikonCaptureRouteAction
    writable_format: str | None
    subdirectory_table: str | None
    entry_range: NikonCaptureByteRange
    payload_range: NikonCaptureByteRange
    payload_size: int
    payload: bytes
    payload_preserved: bool
    known: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCapturePreservedSegmentPlan:
    action: NikonCaptureRouteAction
    segment_range: NikonCaptureByteRange
    payload: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCaptureDirectoryPlan:
    document_number: int | None
    source_range: NikonCaptureByteRange
    header: NikonCaptureHeaderPlan | None
    entries: tuple[NikonCaptureEntryPlan, ...]
    preserved_segments: tuple[NikonCapturePreservedSegmentPlan, ...]
    gates: tuple[NikonCaptureEmissionGate, ...]
    payload_preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCaptureEditVersionPlan:
    document_number: int
    length_word_range: NikonCaptureByteRange
    payload_range: NikonCaptureByteRange
    declared_length: int
    directory_plan: NikonCaptureDirectoryPlan | None
    payload_preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCaptureEditVersionsPlan:
    declared_count: int
    versions: tuple[NikonCaptureEditVersionPlan, ...]
    gates: tuple[NikonCaptureEmissionGate, ...]
    payload_preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCaptureTransactionPlan:
    status: NikonCapturePlanStatus
    input_kind: NikonCaptureInputKind
    original_bytes: bytes
    directory_plan: NikonCaptureDirectoryPlan | None
    edit_versions_plan: NikonCaptureEditVersionsPlan | None
    output_emission_gates: tuple[NikonCaptureEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Nikon Capture transaction output is gated: {gate_codes}")
        return self.original_bytes


def build_nikon_capture_transaction_plan(
    source_bytes: bytes,
    *,
    surface: NikonCaptureSurface = "auto",
    rewrite_request: NikonCaptureRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> NikonCaptureTransactionPlan:
    gates = list(_rewrite_gates(rewrite_request, surface))
    input_kind = _detect_input_kind(source_bytes, surface)

    if input_kind == "nikon_capture":
        directory = _build_directory_plan(source_bytes, 0, len(source_bytes), None)
        gates.extend(directory.gates)
        if not allow_output_emission:
            gates.append(_non_mutating_gate())
        output_gates = _unique_gates(tuple(gates))
        return NikonCaptureTransactionPlan(
            status=_status_from_gates(output_gates),
            input_kind=input_kind,
            original_bytes=source_bytes,
            directory_plan=directory,
            edit_versions_plan=None,
            output_emission_gates=output_gates,
            evidence_ids=_unique_sources(
                (
                    NIKON_CAPTURE_MAKERNOTE_SOURCE,
                    *directory.evidence_ids,
                    *(source for gate in output_gates for source in gate.evidence_ids),
                )
            ),
        )

    if input_kind == "edit_versions":
        edit_versions = _build_edit_versions_plan(source_bytes)
        gates.extend(edit_versions.gates)
        if not allow_output_emission:
            gates.append(_non_mutating_gate())
        output_gates = _unique_gates(tuple(gates))
        return NikonCaptureTransactionPlan(
            status=_status_from_gates(output_gates),
            input_kind=input_kind,
            original_bytes=source_bytes,
            directory_plan=None,
            edit_versions_plan=edit_versions,
            output_emission_gates=output_gates,
            evidence_ids=_unique_sources(
                (
                    NIKON_CAPTURE_EDIT_SURFACE_SOURCE,
                    *edit_versions.evidence_ids,
                    *(source for gate in output_gates for source in gate.evidence_ids),
                )
            ),
        )

    gates.append(
        NikonCaptureEmissionGate(
            "unrecognized_nikon_capture_input",
            "Input is neither a Nikon Capture directory nor an edit-version list.",
            (NIKON_CAPTURE_MAKERNOTE_SOURCE, NIKON_CAPTURE_EDIT_SURFACE_SOURCE),
        )
    )
    if not allow_output_emission:
        gates.append(_non_mutating_gate())
    output_gates = _unique_gates(tuple(gates))
    return NikonCaptureTransactionPlan(
        status="blocked",
        input_kind="unknown",
        original_bytes=source_bytes,
        directory_plan=None,
        edit_versions_plan=None,
        output_emission_gates=output_gates,
        evidence_ids=_unique_sources(
            (
                NIKON_CAPTURE_MAKERNOTE_SOURCE,
                NIKON_CAPTURE_EDIT_SURFACE_SOURCE,
                *(source for gate in output_gates for source in gate.evidence_ids),
            )
        ),
    )


plan_nikon_capture_transaction = build_nikon_capture_transaction_plan


def _build_directory_plan(
    source_bytes: bytes,
    start_offset: int,
    end_offset: int,
    document_number: int | None,
) -> NikonCaptureDirectoryPlan:
    gates: list[NikonCaptureEmissionGate] = []
    entries: list[NikonCaptureEntryPlan] = []
    preserved_segments: list[NikonCapturePreservedSegmentPlan] = []
    data = source_bytes[start_offset:end_offset]

    if len(data) < NIKON_CAPTURE_HEADER_SIZE:
        gate = NikonCaptureEmissionGate(
            "short_nikon_capture_data",
            "Nikon Capture data is shorter than the 22-byte header used by the reader.",
            (NIKON_CAPTURE_WRITE_SOURCE, NIKON_CAPTURE_PROCESS_SOURCE),
        )
        return NikonCaptureDirectoryPlan(
            document_number=document_number,
            source_range=NikonCaptureByteRange(start_offset, end_offset),
            header=None,
            entries=(),
            preserved_segments=(),
            gates=(gate,),
            payload_preserved=True,
            evidence_ids=(NIKON_CAPTURE_WRITE_SOURCE, NIKON_CAPTURE_PROCESS_SOURCE),
        )

    tag_id = _read_u32(data, 0)
    declared_size = _read_u32(data, NIKON_CAPTURE_FIXED_HEADER_SIZE)
    padding_length = len(data) - declared_size - NIKON_CAPTURE_FIXED_HEADER_SIZE
    if tag_id != NIKON_CAPTURE_MAGIC or (padding_length < 0 and padding_length != -18):
        gate = NikonCaptureEmissionGate(
            "unrecognized_nikon_capture_header",
            "Nikon Capture header failed the magic and contained-size checks.",
            (NIKON_CAPTURE_WRITE_SOURCE,),
        )
        return NikonCaptureDirectoryPlan(
            document_number=document_number,
            source_range=NikonCaptureByteRange(start_offset, end_offset),
            header=None,
            entries=(),
            preserved_segments=(),
            gates=(gate,),
            payload_preserved=True,
            evidence_ids=(NIKON_CAPTURE_WRITE_SOURCE, NIKON_CAPTURE_PROCESS_SOURCE),
        )

    effective_end = (
        declared_size + NIKON_CAPTURE_FIXED_HEADER_SIZE if padding_length > 0 else len(data)
    )
    trailing_padding_range = None
    if padding_length > 0:
        trailing_padding_range = NikonCaptureByteRange(
            start_offset + effective_end,
            end_offset,
        )
        preserved_segments.append(
            NikonCapturePreservedSegmentPlan(
                action="preserve_trailing_padding",
                segment_range=trailing_padding_range,
                payload=source_bytes[start_offset + effective_end : end_offset],
                evidence_ids=(NIKON_CAPTURE_WRITE_SOURCE,),
            )
        )

    header = NikonCaptureHeaderPlan(
        tag_id=tag_id,
        declared_size=declared_size,
        effective_directory_range=NikonCaptureByteRange(start_offset, start_offset + effective_end),
        trailing_padding_range=trailing_padding_range,
        legacy_size_includes_header=padding_length == -18,
        evidence_ids=(NIKON_CAPTURE_WRITE_SOURCE,),
    )

    pos = NIKON_CAPTURE_HEADER_SIZE
    entry_index = 1
    while pos + NIKON_CAPTURE_ENTRY_HEADER_SIZE < effective_end:
        size_word = _read_u32(data, pos + NIKON_CAPTURE_ENTRY_PREFIX_SIZE)
        if size_word < NIKON_CAPTURE_SIZE_WORD_BIAS:
            gates.append(
                NikonCaptureEmissionGate(
                    "entry_size_word_underflow",
                    "Nikon Capture entry size word is smaller than its four-byte bias.",
                    (NIKON_CAPTURE_WRITE_SOURCE, NIKON_CAPTURE_PROCESS_SOURCE),
                )
            )
            break
        payload_size = size_word - NIKON_CAPTURE_SIZE_WORD_BIAS
        payload_start = pos + NIKON_CAPTURE_ENTRY_HEADER_SIZE
        payload_end = payload_start + payload_size
        if payload_end > effective_end:
            gates.append(
                NikonCaptureEmissionGate(
                    "truncated_entry_payload",
                    "Nikon Capture entry payload extends beyond the contained directory.",
                    (NIKON_CAPTURE_WRITE_SOURCE, NIKON_CAPTURE_PROCESS_SOURCE),
                )
            )
            break
        entries.append(
            _build_entry_plan(
                source_bytes,
                start_offset,
                pos,
                payload_start,
                payload_end,
                entry_index,
            )
        )
        pos = payload_end
        entry_index += 1

    remaining = effective_end - pos
    if remaining == 4:
        tail_range = NikonCaptureByteRange(start_offset + pos, start_offset + effective_end)
        preserved_segments.append(
            NikonCapturePreservedSegmentPlan(
                action="preserve_nx2_size_tail",
                segment_range=tail_range,
                payload=source_bytes[start_offset + pos : start_offset + effective_end],
                evidence_ids=(NIKON_CAPTURE_WRITE_SOURCE,),
            )
        )
    elif remaining != 0 and not gates:
        gates.append(
            NikonCaptureEmissionGate(
                "improperly_terminated_nikon_capture_data",
                "Nikon Capture directory ended with a partial entry header.",
                (NIKON_CAPTURE_WRITE_SOURCE,),
            )
        )

    return NikonCaptureDirectoryPlan(
        document_number=document_number,
        source_range=NikonCaptureByteRange(start_offset, end_offset),
        header=header,
        entries=tuple(entries),
        preserved_segments=tuple(preserved_segments),
        gates=tuple(gates),
        payload_preserved=True,
        evidence_ids=_unique_sources(
            (
                NIKON_CAPTURE_MAIN_SOURCE,
                NIKON_CAPTURE_MAIN_TAGS_SOURCE,
                NIKON_CAPTURE_WRITE_SOURCE,
                NIKON_CAPTURE_PROCESS_SOURCE,
                *(source for entry in entries for source in entry.evidence_ids),
                *(source for segment in preserved_segments for source in segment.evidence_ids),
                *(source for gate in gates for source in gate.evidence_ids),
            )
        ),
    )


def _build_entry_plan(
    source_bytes: bytes,
    directory_start: int,
    entry_start: int,
    payload_start: int,
    payload_end: int,
    index: int,
) -> NikonCaptureEntryPlan:
    absolute_entry_start = directory_start + entry_start
    absolute_payload_start = directory_start + payload_start
    absolute_payload_end = directory_start + payload_end
    tag_id = _read_u32(source_bytes, absolute_entry_start)
    definition = _tag_definitions().get(tag_id)
    payload = source_bytes[absolute_payload_start:absolute_payload_end]

    if definition is None:
        return NikonCaptureEntryPlan(
            index=index,
            tag_id=tag_id,
            tag_id_hex=f"0x{tag_id:08x}",
            tag_name=None,
            responsibility="unknown_payload",
            action="preserve_unknown_entry",
            writable_format=None,
            subdirectory_table=None,
            entry_range=NikonCaptureByteRange(absolute_entry_start, absolute_payload_end),
            payload_range=NikonCaptureByteRange(absolute_payload_start, absolute_payload_end),
            payload_size=len(payload),
            payload=payload,
            payload_preserved=True,
            known=False,
            evidence_ids=(NIKON_CAPTURE_WRITE_SOURCE, NIKON_CAPTURE_PROCESS_SOURCE),
        )

    return NikonCaptureEntryPlan(
        index=index,
        tag_id=tag_id,
        tag_id_hex=f"0x{tag_id:08x}",
        tag_name=definition.tag_name,
        responsibility=definition.responsibility,
        action=_action_for_responsibility(definition.responsibility),
        writable_format=definition.writable_format,
        subdirectory_table=definition.subdirectory_table,
        entry_range=NikonCaptureByteRange(absolute_entry_start, absolute_payload_end),
        payload_range=NikonCaptureByteRange(absolute_payload_start, absolute_payload_end),
        payload_size=len(payload),
        payload=payload,
        payload_preserved=True,
        known=True,
        evidence_ids=definition.evidence_ids,
    )


def _build_edit_versions_plan(source_bytes: bytes) -> NikonCaptureEditVersionsPlan:
    gates: list[NikonCaptureEmissionGate] = []
    versions: list[NikonCaptureEditVersionPlan] = []

    if len(source_bytes) <= 4:
        return NikonCaptureEditVersionsPlan(
            declared_count=0,
            versions=(),
            gates=(
                NikonCaptureEmissionGate(
                    "short_edit_versions_data",
                    "Edit-version data must contain a count followed by length words.",
                    (NIKON_CAPTURE_EDIT_PROCESS_SOURCE,),
                ),
            ),
            payload_preserved=True,
            evidence_ids=(NIKON_CAPTURE_EDIT_PROCESS_SOURCE,),
        )

    declared_count = _read_u32(source_bytes, 0)
    pos = 4
    document_number = 1
    remaining_count = declared_count
    while remaining_count:
        if pos + 4 > len(source_bytes):
            gates.append(
                NikonCaptureEmissionGate(
                    "truncated_edit_version_length",
                    "Edit-version list ended before the next length word.",
                    (NIKON_CAPTURE_EDIT_PROCESS_SOURCE,),
                )
            )
            break
        declared_length = _read_u32(source_bytes, pos)
        payload_start = pos + 4
        payload_end = payload_start + declared_length
        length_word_range = NikonCaptureByteRange(pos, payload_start)
        payload_range = NikonCaptureByteRange(payload_start, min(payload_end, len(source_bytes)))
        if payload_end > len(source_bytes):
            gates.append(
                NikonCaptureEmissionGate(
                    "truncated_edit_version_payload",
                    "Edit-version payload extends beyond the source data.",
                    (NIKON_CAPTURE_EDIT_PROCESS_SOURCE,),
                )
            )
            versions.append(
                NikonCaptureEditVersionPlan(
                    document_number=document_number,
                    length_word_range=length_word_range,
                    payload_range=payload_range,
                    declared_length=declared_length,
                    directory_plan=None,
                    payload_preserved=True,
                    evidence_ids=(NIKON_CAPTURE_EDIT_PROCESS_SOURCE,),
                )
            )
            break
        directory = _build_directory_plan(source_bytes, payload_start, payload_end, document_number)
        gates.extend(directory.gates)
        versions.append(
            NikonCaptureEditVersionPlan(
                document_number=document_number,
                length_word_range=length_word_range,
                payload_range=payload_range,
                declared_length=declared_length,
                directory_plan=directory,
                payload_preserved=True,
                evidence_ids=_unique_sources(
                    (NIKON_CAPTURE_EDIT_PROCESS_SOURCE, *directory.evidence_ids)
                ),
            )
        )
        pos = payload_end
        document_number += 1
        remaining_count -= 1

    if remaining_count and not gates:
        gates.append(
            NikonCaptureEmissionGate(
                "unconsumed_edit_version_records",
                "Edit-version traversal stopped before all declared versions were consumed.",
                (NIKON_CAPTURE_EDIT_PROCESS_SOURCE,),
            )
        )

    return NikonCaptureEditVersionsPlan(
        declared_count=declared_count,
        versions=tuple(versions),
        gates=tuple(gates),
        payload_preserved=True,
        evidence_ids=_unique_sources(
            (
                NIKON_CAPTURE_EDIT_PROCESS_SOURCE,
                NIKON_CAPTURE_EDIT_SURFACE_SOURCE,
                *(source for version in versions for source in version.evidence_ids),
                *(source for gate in gates for source in gate.evidence_ids),
            )
        ),
    )


def _rewrite_gates(
    rewrite_request: NikonCaptureRewriteRequest | None,
    surface: NikonCaptureSurface,
) -> tuple[NikonCaptureEmissionGate, ...]:
    if rewrite_request is None or not rewrite_request.has_changes:
        return ()
    gates: list[NikonCaptureEmissionGate] = []
    if rewrite_request.tags:
        gates.append(
            NikonCaptureEmissionGate(
                "unsupported_nikon_capture_rewrite",
                (
                    "This planner records WriteNikonCapture routing but does not emit "
                    "rewritten Nikon Capture entries."
                ),
                (NIKON_CAPTURE_WRITE_SOURCE,),
            )
        )
    if rewrite_request.edit_versions_payload is not None or surface == "edit_versions":
        gates.append(
            NikonCaptureEmissionGate(
                "unsupported_edit_versions_rewrite",
                "Nikon.pm declares the edit-version WriteProc as unsupported.",
                (NIKON_CAPTURE_EDIT_SURFACE_SOURCE,),
            )
        )
    return tuple(gates)


def _detect_input_kind(source_bytes: bytes, surface: NikonCaptureSurface) -> NikonCaptureInputKind:
    if surface == "nikon_capture":
        return "nikon_capture"
    if surface == "edit_versions":
        return "edit_versions"
    if len(source_bytes) >= 4 and _read_u32(source_bytes, 0) == NIKON_CAPTURE_MAGIC:
        return "nikon_capture"
    if _looks_like_edit_versions(source_bytes):
        return "edit_versions"
    return "unknown"


def _looks_like_edit_versions(source_bytes: bytes) -> bool:
    if len(source_bytes) <= 4:
        return False
    count = _read_u32(source_bytes, 0)
    if count == 0 or count > 256:
        return False
    pos = 4
    remaining = count
    while remaining:
        if pos + 4 > len(source_bytes):
            return False
        length = _read_u32(source_bytes, pos)
        pos += 4 + length
        if pos > len(source_bytes):
            return False
        remaining -= 1
    return True


def _action_for_responsibility(
    responsibility: NikonCaptureTagResponsibility,
) -> NikonCaptureRouteAction:
    if responsibility == "iptc_subdirectory":
        return "route_iptc_subdirectory"
    if responsibility == "capture_subdirectory":
        return "route_capture_subdirectory"
    if responsibility in {"binary_payload", "binary_xml_payload"}:
        return "route_binary_payload"
    if responsibility == "unknown_payload":
        return "preserve_unknown_entry"
    return "route_writable_scalar"


def _status_from_gates(
    gates: tuple[NikonCaptureEmissionGate, ...],
) -> NikonCapturePlanStatus:
    if any(
        gate.code
        in {
            "unrecognized_nikon_capture_input",
            "short_nikon_capture_data",
            "unrecognized_nikon_capture_header",
            "entry_size_word_underflow",
            "truncated_entry_payload",
            "improperly_terminated_nikon_capture_data",
            "short_edit_versions_data",
            "truncated_edit_version_length",
            "truncated_edit_version_payload",
            "unconsumed_edit_version_records",
        }
        for gate in gates
    ):
        return "blocked"
    if any(
        gate.code in {"unsupported_nikon_capture_rewrite", "unsupported_edit_versions_rewrite"}
        for gate in gates
    ):
        return "unsupported"
    return "planned"


def _non_mutating_gate() -> NikonCaptureEmissionGate:
    return NikonCaptureEmissionGate(
        "non_mutating_plan_requires_explicit_emission",
        "Nikon Capture transaction plans preserve source bytes unless emission is explicit.",
        (NIKON_CAPTURE_WRITE_SOURCE,),
    )


def _read_u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def _tag_definitions() -> dict[int, NikonCaptureTagDefinition]:
    main = (NIKON_CAPTURE_MAIN_TAGS_SOURCE,)
    subdir = (NIKON_CAPTURE_MAIN_TAGS_SOURCE, NIKON_CAPTURE_BINARY_TABLES_SOURCE)
    iptc = (
        NIKON_CAPTURE_MAIN_TAGS_SOURCE,
        NIKON_CAPTURE_WRITE_SOURCE,
    )
    tags = {
        0x008AE85E: _scalar_tag("LCHEditor", "int8u", main),
        0x0C89224B: _scalar_tag("ColorAberrationControl", "int8u", main),
        0x116FEA21: _subdirectory_tag("HighlightData", "NikonCapture::HighlightData", subdir),
        0x2175EB78: _scalar_tag("D-LightingHQ", "int8u", main),
        0x2FC08431: _scalar_tag("StraightenAngle", "double", main),
        0x374233E0: _subdirectory_tag("CropData", "NikonCapture::CropData", subdir),
        0x39C456AC: _subdirectory_tag("PictureCtrl", "NikonCapture::PictureCtrl", subdir),
        0x3CFC73C6: _subdirectory_tag("RedEyeData", "NikonCapture::RedEyeData", subdir),
        0x3D136244: _scalar_tag("EditVersionName", "string", main),
        0x416391C6: _scalar_tag("QuickFix", "int8u", main),
        0x56A54260: _subdirectory_tag("Exposure", "NikonCapture::Exposure", subdir),
        0x5F0E7D23: _scalar_tag("ColorBooster", "int8u", main),
        0x6A6E36B6: _scalar_tag("D-LightingHQSelected", "int8u", main),
        0x753DCBC0: _scalar_tag("NoiseReduction", "int8u", main),
        0x76A43200: _scalar_tag("UnsharpMask", "int8u", main),
        0x76A43201: _scalar_tag("Curves", "int8u", main),
        0x76A43202: _scalar_tag("ColorBalanceAdj", "int8u", main),
        0x76A43203: _scalar_tag("AdvancedRaw", "int8u", main),
        0x76A43204: _scalar_tag("WhiteBalanceAdj", "int8u", main),
        0x76A43205: _scalar_tag("VignetteControl", "int8u", main),
        0x76A43206: _scalar_tag("FlipHorizontal", "int8u", main),
        0x76A43207: _scalar_tag("Rotation", "int16u", main),
        0x083A1A25: _binary_tag("HistogramXML", True, 4, main),
        0x84589434: _subdirectory_tag("BrightnessData", "NikonCapture::Brightness", subdir),
        0x890FF591: _subdirectory_tag("D-LightingHQData", "NikonCapture::DLightingHQ", subdir),
        0x926F13E0: _subdirectory_tag(
            "NoiseReductionData",
            "NikonCapture::NoiseReduction",
            subdir,
        ),
        0x9EF5F6E0: _iptc_tag(iptc),
        0xAB5ECA5E: _scalar_tag("PhotoEffects", "int8u", main),
        0xAC6BD5C0: _scalar_tag("VignetteControlIntensity", "int16s", main),
        0xB0384E1E: _subdirectory_tag("PhotoEffectsData", "NikonCapture::PhotoEffects", subdir),
        0xB999A36F: _subdirectory_tag("ColorBoostData", "NikonCapture::ColorBoost", subdir),
        0xBF3C6C20: _subdirectory_tag("WBAdjData", "NikonCapture::WBAdjData", subdir),
        0xCE5554AA: _scalar_tag("D-LightingHS", "int8u", main),
        0xE2173C47: _scalar_tag("PictureControl", "int8u", main),
        0xE37B4337: _subdirectory_tag("D-LightingHSData", "NikonCapture::DLightingHS", subdir),
        0xE42B5161: _subdirectory_tag("UnsharpData", "NikonCapture::UnsharpData", subdir),
        0xE9651831: _binary_tag("PhotoEffectHistoryXML", True, 0, main),
        0xFE28A44F: _scalar_tag("AutoRedEye", "int8u", main),
        0xFE443A45: _scalar_tag("ImageDustOff", "int8u", main),
    }
    return {
        tag_id: NikonCaptureTagDefinition(
            tag_id=tag_id,
            tag_name=definition.tag_name,
            responsibility=definition.responsibility,
            writable_format=definition.writable_format,
            subdirectory_table=definition.subdirectory_table,
            binary=definition.binary,
            adjust_size=definition.adjust_size,
            evidence_ids=definition.evidence_ids,
        )
        for tag_id, definition in tags.items()
    }


def _scalar_tag(
    name: str,
    writable_format: str,
    sources: tuple[str, ...],
) -> NikonCaptureTagDefinition:
    return NikonCaptureTagDefinition(
        tag_id=0,
        tag_name=name,
        responsibility="writable_scalar",
        writable_format=writable_format,
        subdirectory_table=None,
        binary=False,
        adjust_size=0,
        evidence_ids=sources,
    )


def _subdirectory_tag(
    name: str,
    table: str,
    sources: tuple[str, ...],
) -> NikonCaptureTagDefinition:
    return NikonCaptureTagDefinition(
        tag_id=0,
        tag_name=name,
        responsibility="capture_subdirectory",
        writable_format=None,
        subdirectory_table=table,
        binary=False,
        adjust_size=0,
        evidence_ids=sources,
    )


def _iptc_tag(sources: tuple[str, ...]) -> NikonCaptureTagDefinition:
    return NikonCaptureTagDefinition(
        tag_id=0,
        tag_name="IPTCData",
        responsibility="iptc_subdirectory",
        writable_format=None,
        subdirectory_table="IPTC::Main",
        binary=False,
        adjust_size=0,
        evidence_ids=sources,
    )


def _binary_tag(
    name: str,
    xml_payload: bool,
    adjust_size: int,
    sources: tuple[str, ...],
) -> NikonCaptureTagDefinition:
    responsibility: NikonCaptureTagResponsibility = (
        "binary_xml_payload" if xml_payload else "binary_payload"
    )
    return NikonCaptureTagDefinition(
        tag_id=0,
        tag_name=name,
        responsibility=responsibility,
        writable_format="undef",
        subdirectory_table=None,
        binary=True,
        adjust_size=adjust_size,
        evidence_ids=sources,
    )


def _unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: dict[str, str] = {}
    for source in sources:
        unique[source] = source
    return tuple(unique.values())


def _unique_gates(
    gates: tuple[NikonCaptureEmissionGate, ...],
) -> tuple[NikonCaptureEmissionGate, ...]:
    unique: dict[tuple[NikonCaptureGateCode, str], NikonCaptureEmissionGate] = {}
    for gate in gates:
        unique[(gate.code, gate.reason)] = gate
    return tuple(unique.values())
