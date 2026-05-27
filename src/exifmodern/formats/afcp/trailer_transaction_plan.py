"""Source-grounded, non-mutating AFCP trailer transaction plans.

The planner mirrors ExifTool's ``AFCP.pm`` trailer surface: it discovers the
``AXS!`` or ``AXS*`` EOF record, selects the matching byte order, validates or
scans for the start header, enumerates 12-byte directory entries, preserves
entry payloads, and records the offset fix-up responsibility needed when AFCP
absolute offsets have shifted. AFCP is modeled as read/write/delete when a
source trailer already exists, but creation is explicitly blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AFCP_EOF_RECORD_SIZE = 12
AFCP_START_HEADER_SIZE = 12
AFCP_DIRECTORY_ENTRY_SIZE = 12
AFCP_MAX_DIRECTORY_VALUE_SIZE = 0x80000000
AFCP_BIG_ENDIAN_HEADER = b"AXS!"
AFCP_LITTLE_ENDIAN_HEADER = b"AXS*"
AFCP_JPEG_SOI_PREFIX = b"\xff\xd8\xff"
AFCP_PREVIEW_SCAN_OFFSET = 10
AFCP_PREVIEW_FALLBACK_OFFSET = 18

type AfcpPlanStatus = Literal["planned", "unsupported"]
type AfcpByteOrder = Literal["big", "little", "unknown"]
type AfcpStructByteOrder = Literal["big", "little"]
type AfcpTagRoute = Literal[
    "iptc_subdirectory",
    "text_value",
    "thumbnail_image",
    "preview_image",
    "preserve_unknown",
]
type AfcpRewriteOperation = Literal["delete_all", "rewrite_existing", "create"]
type AfcpActionKind = Literal[
    "detect_eof_record",
    "select_byte_order",
    "validate_start_header",
    "fix_shifted_offsets",
    "enumerate_directory",
    "read_entry_payload",
    "route_iptc_subdirectory",
    "route_text_value",
    "route_thumbnail_image",
    "route_preview_image",
    "preserve_unknown_payload",
    "plan_delete_all",
    "plan_rewrite_existing",
    "block_create",
]
type AfcpEmissionGateCode = Literal[
    "truncated_afcp_eof_record",
    "no_afcp_eof_record",
    "invalid_afcp_trailer_offset",
    "start_header_mismatch",
    "truncated_afcp_start_header",
    "truncated_afcp_directory",
    "bad_afcp_directory_entry",
    "afcp_creation_unsupported",
    "non_mutating_plan_requires_explicit_emission",
]

AFCP_PM_SOURCE_PATH = "lib/Image/ExifTool/AFCP.pm"

AFCP_DESCRIPTION_SOURCE = "afcp.description"
AFCP_TAG_TABLE_SOURCE = "afcp.tag_table"
AFCP_EOF_SOURCE = "afcp.eof"
AFCP_SCAN_FIX_SOURCE = "afcp.scan_fix"
AFCP_DIRECTORY_SOURCE = "afcp.directory"
AFCP_EXTRACT_SOURCE = "afcp.extract"
AFCP_WRITE_SOURCE = "afcp.write"
AFCP_REWRITE_SOURCE = "afcp.rewrite"

AFCP_TRANSACTION_SOURCES = (
    AFCP_DESCRIPTION_SOURCE,
    AFCP_TAG_TABLE_SOURCE,
    AFCP_EOF_SOURCE,
    AFCP_SCAN_FIX_SOURCE,
    AFCP_DIRECTORY_SOURCE,
    AFCP_EXTRACT_SOURCE,
    AFCP_WRITE_SOURCE,
    AFCP_REWRITE_SOURCE,
)


@dataclass(frozen=True)
class AfcpOutputEmissionGate:
    code: AfcpEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AfcpEofRecordPlan:
    offset: int | None
    marker: bytes
    byte_order: AfcpByteOrder
    declared_start_offset: int | None
    checksum: int | None
    is_afcp: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AfcpStartHeaderPlan:
    declared_start_offset: int | None
    actual_start_offset: int | None
    marker: bytes
    version: bytes
    directory_entry_count: int | None
    checksum: int | None
    start_header_matches_eof: bool
    offset_fix_shift: int | None
    trailer_length: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AfcpDirectoryEntryPlan:
    index: int
    tag: bytes
    tag_name: str
    declared_size: int
    declared_offset: int
    effective_offset: int | None
    payload_end_offset: int | None
    payload: bytes | None
    route: AfcpTagRoute
    preview_payload_offset: int | None
    preview_payload: bytes | None
    is_valid: bool
    evidence_ids: tuple[str, ...]

    @property
    def payload_range(self) -> tuple[int, int] | None:
        if self.effective_offset is None or self.payload_end_offset is None:
            return None
        return (self.effective_offset, self.payload_end_offset)


@dataclass(frozen=True)
class AfcpRewriteRequest:
    operation: AfcpRewriteOperation
    target_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class AfcpActionPlan:
    kind: AfcpActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AfcpTrailerTransactionPlan:
    status: AfcpPlanStatus
    source_data: bytes
    eof_record: AfcpEofRecordPlan
    start_header: AfcpStartHeaderPlan
    directory_entries: tuple[AfcpDirectoryEntryPlan, ...]
    rewrite_request: AfcpRewriteRequest | None
    actions: tuple[AfcpActionPlan, ...]
    output_emission_gates: tuple[AfcpOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"AFCP trailer transaction output is gated: {gate_codes}")
        return self.source_data


def build_afcp_trailer_transaction_plan(
    afcp_data: bytes,
    *,
    rewrite_request: AfcpRewriteRequest | None = None,
    allow_output_emission: bool = False,
    scan_for_trailer: bool = False,
    scan_start_offset: int = 0,
    trailer_offset_from_eof: int = 0,
) -> AfcpTrailerTransactionPlan:
    """Build a source-backed AFCP trailer transaction plan."""

    gates: list[AfcpOutputEmissionGate] = []
    actions: list[AfcpActionPlan] = []
    if len(afcp_data) < AFCP_EOF_RECORD_SIZE:
        eof_record = _empty_eof_record()
        gates.append(
            AfcpOutputEmissionGate(
                code="truncated_afcp_eof_record",
                reason="ExifTool requires a 12-byte AFCP EOF record read.",
                evidence_ids=(AFCP_EOF_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=afcp_data,
            eof_record=eof_record,
            start_header=_empty_start_header(),
            directory_entries=(),
            rewrite_request=rewrite_request,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    eof_record_offset = len(afcp_data) - AFCP_EOF_RECORD_SIZE - trailer_offset_from_eof
    if trailer_offset_from_eof < 0 or eof_record_offset < 0:
        eof_record = _empty_eof_record()
        gates.append(
            AfcpOutputEmissionGate(
                code="invalid_afcp_trailer_offset",
                reason="The AFCP EOF record cannot be located from the requested offset.",
                evidence_ids=(AFCP_EOF_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=afcp_data,
            eof_record=eof_record,
            start_header=_empty_start_header(),
            directory_entries=(),
            rewrite_request=rewrite_request,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    end_record = afcp_data[eof_record_offset : eof_record_offset + AFCP_EOF_RECORD_SIZE]
    marker = end_record[:4]
    byte_order = _byte_order(marker)
    is_afcp = byte_order != "unknown"
    declared_start = _read_u32(end_record, 4, byte_order) if is_afcp else None
    eof_record = AfcpEofRecordPlan(
        offset=eof_record_offset,
        marker=marker,
        byte_order=byte_order,
        declared_start_offset=declared_start,
        checksum=_read_u32(end_record, 8, byte_order) if is_afcp else None,
        is_afcp=is_afcp,
        evidence_ids=(AFCP_EOF_SOURCE,),
    )
    if not is_afcp:
        gates.append(
            AfcpOutputEmissionGate(
                code="no_afcp_eof_record",
                reason="Input does not satisfy ExifTool's AXS! or AXS* AFCP EOF gate.",
                evidence_ids=(AFCP_EOF_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=afcp_data,
            eof_record=eof_record,
            start_header=_empty_start_header(),
            directory_entries=(),
            rewrite_request=rewrite_request,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    actions.extend(
        (
            AfcpActionPlan(
                kind="detect_eof_record",
                target="AFCP EOF record",
                byte_range=(eof_record_offset, eof_record_offset + AFCP_EOF_RECORD_SIZE),
                reason="Input satisfied ExifTool's AXS EOF record gate.",
                evidence_ids=(AFCP_EOF_SOURCE,),
            ),
            AfcpActionPlan(
                kind="select_byte_order",
                target=marker.decode("ascii"),
                byte_range=(eof_record_offset, eof_record_offset + 4),
                reason="AXS! selects big-endian; AXS* selects little-endian.",
                evidence_ids=(AFCP_EOF_SOURCE,),
            ),
        )
    )
    if declared_start is None:
        raise AssertionError("AFCP declared start is required after EOF marker validation")

    actual_start = _actual_start_offset(
        afcp_data,
        marker,
        declared_start,
        eof_record_offset,
        scan_for_trailer,
        scan_start_offset,
    )
    if actual_start is None:
        gates.append(
            AfcpOutputEmissionGate(
                code="start_header_mismatch",
                reason=(
                    "The AFCP EOF record declared a start offset whose header does not "
                    "match, and scanning did not find a usable start header."
                ),
                evidence_ids=(AFCP_SCAN_FIX_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=afcp_data,
            eof_record=eof_record,
            start_header=AfcpStartHeaderPlan(
                declared_start_offset=declared_start,
                actual_start_offset=None,
                marker=b"",
                version=b"",
                directory_entry_count=None,
                checksum=None,
                start_header_matches_eof=False,
                offset_fix_shift=None,
                trailer_length=None,
                evidence_ids=(AFCP_SCAN_FIX_SOURCE,),
            ),
            directory_entries=(),
            rewrite_request=rewrite_request,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    if actual_start + AFCP_START_HEADER_SIZE > eof_record_offset:
        gates.append(
            AfcpOutputEmissionGate(
                code="truncated_afcp_start_header",
                reason="The AFCP start header cannot be read before the EOF record.",
                evidence_ids=(AFCP_SCAN_FIX_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=afcp_data,
            eof_record=eof_record,
            start_header=AfcpStartHeaderPlan(
                declared_start_offset=declared_start,
                actual_start_offset=actual_start,
                marker=afcp_data[actual_start:eof_record_offset],
                version=b"",
                directory_entry_count=None,
                checksum=None,
                start_header_matches_eof=actual_start == declared_start,
                offset_fix_shift=actual_start - declared_start,
                trailer_length=eof_record_offset + AFCP_EOF_RECORD_SIZE - actual_start,
                evidence_ids=(AFCP_SCAN_FIX_SOURCE,),
            ),
            directory_entries=(),
            rewrite_request=rewrite_request,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    start_header_data = afcp_data[actual_start : actual_start + AFCP_START_HEADER_SIZE]
    entry_count = _read_u16(start_header_data, 6, byte_order)
    offset_fix_shift = actual_start - declared_start
    start_header = AfcpStartHeaderPlan(
        declared_start_offset=declared_start,
        actual_start_offset=actual_start,
        marker=start_header_data[:4],
        version=start_header_data[4:6],
        directory_entry_count=entry_count,
        checksum=_read_u32(start_header_data, 8, byte_order),
        start_header_matches_eof=actual_start == declared_start,
        offset_fix_shift=offset_fix_shift,
        trailer_length=eof_record_offset + AFCP_EOF_RECORD_SIZE - actual_start,
        evidence_ids=(AFCP_SCAN_FIX_SOURCE, AFCP_DIRECTORY_SOURCE),
    )
    actions.append(
        AfcpActionPlan(
            kind="validate_start_header",
            target="AFCP start header",
            byte_range=(actual_start, actual_start + AFCP_START_HEADER_SIZE),
            reason="The AFCP start header matches the EOF record marker.",
            evidence_ids=(AFCP_SCAN_FIX_SOURCE,),
        )
    )
    if offset_fix_shift:
        actions.append(
            AfcpActionPlan(
                kind="fix_shifted_offsets",
                target="AFCP absolute offsets",
                byte_range=None,
                reason=(
                    f"AFCP directory payload offsets require a shift of {offset_fix_shift} bytes."
                ),
                evidence_ids=(AFCP_SCAN_FIX_SOURCE,),
            )
        )

    directory_start = actual_start + AFCP_START_HEADER_SIZE
    directory_end = directory_start + (entry_count * AFCP_DIRECTORY_ENTRY_SIZE)
    if directory_end > eof_record_offset:
        gates.append(
            AfcpOutputEmissionGate(
                code="truncated_afcp_directory",
                reason="The AFCP directory entry table extends beyond the EOF record.",
                evidence_ids=(AFCP_DIRECTORY_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=afcp_data,
            eof_record=eof_record,
            start_header=start_header,
            directory_entries=(),
            rewrite_request=rewrite_request,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    actions.append(
        AfcpActionPlan(
            kind="enumerate_directory",
            target="AFCP directory",
            byte_range=(directory_start, directory_end),
            reason="AFCP directory entries are fixed 12-byte tag, size, and offset records.",
            evidence_ids=(AFCP_DIRECTORY_SOURCE,),
        )
    )
    entries, entry_gates, entry_actions = _directory_entries(
        afcp_data,
        byte_order,
        directory_start,
        entry_count,
        offset_fix_shift,
        eof_record_offset,
    )
    gates.extend(entry_gates)
    actions.extend(entry_actions)
    _apply_rewrite_request(rewrite_request, gates, actions, entries)

    structural_gate_codes = {
        "truncated_afcp_directory",
        "bad_afcp_directory_entry",
        "afcp_creation_unsupported",
    }
    status: AfcpPlanStatus = (
        "unsupported" if any(gate.code in structural_gate_codes for gate in gates) else "planned"
    )
    return _final_plan(
        status=status,
        source_data=afcp_data,
        eof_record=eof_record,
        start_header=start_header,
        directory_entries=entries,
        rewrite_request=rewrite_request,
        actions=tuple(actions),
        gates=gates,
        allow_output_emission=allow_output_emission,
    )


plan_afcp_trailer_transaction = build_afcp_trailer_transaction_plan


def afcp_trailer_byte_range(
    afcp_data: bytes,
    *,
    scan_for_trailer: bool = False,
    scan_start_offset: int = 0,
    trailer_offset_from_eof: int = 0,
) -> tuple[int, int] | None:
    """Return the actual AFCP trailer byte range when ExifTool's trailer gate succeeds."""

    plan = build_afcp_trailer_transaction_plan(
        afcp_data,
        allow_output_emission=True,
        scan_for_trailer=scan_for_trailer,
        scan_start_offset=scan_start_offset,
        trailer_offset_from_eof=trailer_offset_from_eof,
    )
    actual_start = plan.start_header.actual_start_offset
    trailer_length = plan.start_header.trailer_length
    if plan.status != "planned" or actual_start is None or trailer_length is None:
        return None
    return (actual_start, actual_start + trailer_length)


def _byte_order(marker: bytes) -> AfcpByteOrder:
    if marker == AFCP_BIG_ENDIAN_HEADER:
        return "big"
    if marker == AFCP_LITTLE_ENDIAN_HEADER:
        return "little"
    return "unknown"


def _read_u16(data: bytes, offset: int, byte_order: AfcpByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 2], _struct_byte_order(byte_order))


def _read_u32(data: bytes, offset: int, byte_order: AfcpByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], _struct_byte_order(byte_order))


def _struct_byte_order(byte_order: AfcpByteOrder) -> AfcpStructByteOrder:
    if byte_order == "little":
        return "little"
    if byte_order == "big":
        return "big"
    raise ValueError("AFCP numeric reads require a known byte order")


def _actual_start_offset(
    afcp_data: bytes,
    marker: bytes,
    declared_start: int,
    eof_record_offset: int,
    scan_for_trailer: bool,
    scan_start_offset: int,
) -> int | None:
    if (
        declared_start >= 0
        and declared_start + AFCP_START_HEADER_SIZE <= eof_record_offset
        and afcp_data[declared_start : declared_start + 4] == marker
    ):
        return declared_start
    if not scan_for_trailer:
        return None
    actual_start = afcp_data.find(marker, max(scan_start_offset, 0), eof_record_offset)
    if actual_start < 0 or actual_start + AFCP_START_HEADER_SIZE > eof_record_offset:
        return None
    return actual_start


def _directory_entries(
    afcp_data: bytes,
    byte_order: AfcpByteOrder,
    directory_start: int,
    entry_count: int,
    offset_fix_shift: int,
    eof_record_offset: int,
) -> tuple[
    tuple[AfcpDirectoryEntryPlan, ...],
    tuple[AfcpOutputEmissionGate, ...],
    tuple[AfcpActionPlan, ...],
]:
    entries: list[AfcpDirectoryEntryPlan] = []
    gates: list[AfcpOutputEmissionGate] = []
    actions: list[AfcpActionPlan] = []
    for index in range(entry_count):
        entry_offset = directory_start + (index * AFCP_DIRECTORY_ENTRY_SIZE)
        entry_data = afcp_data[entry_offset : entry_offset + AFCP_DIRECTORY_ENTRY_SIZE]
        tag = entry_data[:4]
        declared_size = _read_u32(entry_data, 4, byte_order)
        declared_offset = _read_u32(entry_data, 8, byte_order)
        effective_offset = declared_offset + offset_fix_shift
        payload_end_offset = effective_offset + declared_size
        route = _route_for_tag(tag)
        payload: bytes | None = None
        preview_payload_offset: int | None = None
        preview_payload: bytes | None = None
        is_valid = (
            declared_size < AFCP_MAX_DIRECTORY_VALUE_SIZE
            and effective_offset >= 0
            and payload_end_offset <= len(afcp_data)
            and payload_end_offset <= eof_record_offset
        )
        if is_valid:
            payload = afcp_data[effective_offset:payload_end_offset]
            preview_payload_offset, preview_payload = _preview_payload(payload, route)
            actions.append(
                AfcpActionPlan(
                    kind="read_entry_payload",
                    target=_tag_name(tag),
                    byte_range=(effective_offset, payload_end_offset),
                    reason="The AFCP directory entry points to a readable payload.",
                    evidence_ids=(AFCP_DIRECTORY_SOURCE, AFCP_EXTRACT_SOURCE),
                )
            )
            actions.append(_route_action(tag, route, effective_offset, payload_end_offset))
        else:
            gates.append(
                AfcpOutputEmissionGate(
                    code="bad_afcp_directory_entry",
                    reason=(
                        f"AFCP entry {index} has an invalid size or offset and cannot "
                        "be read safely."
                    ),
                    evidence_ids=(AFCP_DIRECTORY_SOURCE,),
                )
            )
        entries.append(
            AfcpDirectoryEntryPlan(
                index=index,
                tag=tag,
                tag_name=_tag_name(tag),
                declared_size=declared_size,
                declared_offset=declared_offset,
                effective_offset=effective_offset if is_valid else None,
                payload_end_offset=payload_end_offset if is_valid else None,
                payload=payload,
                route=route,
                preview_payload_offset=preview_payload_offset,
                preview_payload=preview_payload,
                is_valid=is_valid,
                evidence_ids=(AFCP_TAG_TABLE_SOURCE, AFCP_DIRECTORY_SOURCE),
            )
        )
    return (tuple(entries), tuple(gates), tuple(actions))


def _route_for_tag(tag: bytes) -> AfcpTagRoute:
    if tag == b"IPTC":
        return "iptc_subdirectory"
    if tag == b"TEXT":
        return "text_value"
    if tag == b"Nail":
        return "thumbnail_image"
    if tag == b"PrVw":
        return "preview_image"
    return "preserve_unknown"


def _tag_name(tag: bytes) -> str:
    return tag.decode("latin-1")


def _preview_payload(payload: bytes, route: AfcpTagRoute) -> tuple[int | None, bytes | None]:
    if route not in {"thumbnail_image", "preview_image"}:
        return (None, None)
    found_offset = payload.find(AFCP_JPEG_SOI_PREFIX, AFCP_PREVIEW_SCAN_OFFSET)
    start = found_offset if found_offset >= 0 else AFCP_PREVIEW_FALLBACK_OFFSET
    if start > len(payload):
        return (start, b"")
    return (start, payload[start:])


def _route_action(
    tag: bytes,
    route: AfcpTagRoute,
    payload_start: int,
    payload_end: int,
) -> AfcpActionPlan:
    if route == "iptc_subdirectory":
        return AfcpActionPlan(
            kind="route_iptc_subdirectory",
            target="IPTC",
            byte_range=(payload_start, payload_end),
            reason="AFCP.pm routes IPTC entries to the IPTC subdirectory.",
            evidence_ids=(AFCP_TAG_TABLE_SOURCE, AFCP_REWRITE_SOURCE),
        )
    if route == "text_value":
        return AfcpActionPlan(
            kind="route_text_value",
            target="TEXT",
            byte_range=(payload_start, payload_end),
            reason="AFCP.pm exposes TEXT entries as Text.",
            evidence_ids=(AFCP_TAG_TABLE_SOURCE, AFCP_EXTRACT_SOURCE),
        )
    if route == "thumbnail_image":
        return AfcpActionPlan(
            kind="route_thumbnail_image",
            target="Nail",
            byte_range=(payload_start, payload_end),
            reason="AFCP.pm routes Nail entries to ThumbnailImage.",
            evidence_ids=(AFCP_TAG_TABLE_SOURCE,),
        )
    if route == "preview_image":
        return AfcpActionPlan(
            kind="route_preview_image",
            target="PrVw",
            byte_range=(payload_start, payload_end),
            reason="AFCP.pm routes PrVw entries to PreviewImage.",
            evidence_ids=(AFCP_TAG_TABLE_SOURCE,),
        )
    return AfcpActionPlan(
        kind="preserve_unknown_payload",
        target=_tag_name(tag),
        byte_range=(payload_start, payload_end),
        reason="Unknown AFCP entries are preserved as source payload bytes.",
        evidence_ids=(AFCP_DIRECTORY_SOURCE, AFCP_REWRITE_SOURCE),
    )


def _apply_rewrite_request(
    rewrite_request: AfcpRewriteRequest | None,
    gates: list[AfcpOutputEmissionGate],
    actions: list[AfcpActionPlan],
    entries: tuple[AfcpDirectoryEntryPlan, ...],
) -> None:
    if rewrite_request is None:
        return
    if rewrite_request.operation == "create":
        gates.append(
            AfcpOutputEmissionGate(
                code="afcp_creation_unsupported",
                reason="ExifTool's AFCP surface is write-capable only for an existing trailer.",
                evidence_ids=(AFCP_DESCRIPTION_SOURCE,),
            )
        )
        actions.append(
            AfcpActionPlan(
                kind="block_create",
                target="AFCP",
                byte_range=None,
                reason="AFCP creation is not supported by the ExifTool oracle.",
                evidence_ids=(AFCP_DESCRIPTION_SOURCE,),
            )
        )
        return
    if rewrite_request.operation == "delete_all":
        actions.append(
            AfcpActionPlan(
                kind="plan_delete_all",
                target="AFCP",
                byte_range=None,
                reason="AFCP.pm allows deleting the existing AFCP group during output.",
                evidence_ids=(AFCP_WRITE_SOURCE,),
            )
        )
        return
    targets = rewrite_request.target_tags or tuple(entry.tag_name for entry in entries)
    actions.append(
        AfcpActionPlan(
            kind="plan_rewrite_existing",
            target=",".join(targets),
            byte_range=None,
            reason=(
                "AFCP.pm rewrites existing directory entries and preserves payloads unless "
                "a routed subdirectory supplies replacement bytes."
            ),
            evidence_ids=(AFCP_REWRITE_SOURCE,),
        )
    )


def _final_plan(
    *,
    status: AfcpPlanStatus,
    source_data: bytes,
    eof_record: AfcpEofRecordPlan,
    start_header: AfcpStartHeaderPlan,
    directory_entries: tuple[AfcpDirectoryEntryPlan, ...],
    rewrite_request: AfcpRewriteRequest | None,
    actions: tuple[AfcpActionPlan, ...],
    gates: list[AfcpOutputEmissionGate],
    allow_output_emission: bool,
) -> AfcpTrailerTransactionPlan:
    if status == "planned" and not allow_output_emission:
        gates.append(
            AfcpOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason=(
                    "AFCP planning is non-mutating unless output emission is explicitly allowed."
                ),
                evidence_ids=(AFCP_DESCRIPTION_SOURCE,),
            )
        )
    return AfcpTrailerTransactionPlan(
        status=status,
        source_data=source_data,
        eof_record=eof_record,
        start_header=start_header,
        directory_entries=directory_entries,
        rewrite_request=rewrite_request,
        actions=actions,
        output_emission_gates=tuple(gates),
        evidence_ids=AFCP_TRANSACTION_SOURCES,
    )


def _empty_eof_record() -> AfcpEofRecordPlan:
    return AfcpEofRecordPlan(
        offset=None,
        marker=b"",
        byte_order="unknown",
        declared_start_offset=None,
        checksum=None,
        is_afcp=False,
        evidence_ids=(AFCP_EOF_SOURCE,),
    )


def _empty_start_header() -> AfcpStartHeaderPlan:
    return AfcpStartHeaderPlan(
        declared_start_offset=None,
        actual_start_offset=None,
        marker=b"",
        version=b"",
        directory_entry_count=None,
        checksum=None,
        start_header_matches_eof=False,
        offset_fix_shift=None,
        trailer_length=None,
        evidence_ids=(AFCP_SCAN_FIX_SOURCE,),
    )
