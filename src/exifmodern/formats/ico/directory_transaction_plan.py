"""Source-grounded, non-mutating ICO/CUR directory image transaction plans.

The planner mirrors ExifTool's ``ICO.pm`` reader: validate the ICO/CUR header,
traverse fixed-size directory records, expose icon/cursor fields, and preserve
the embedded image byte ranges.  ExifTool does not write ICO/CUR files or
delegate into embedded PNG/DIB payloads from this module, so metadata delegation
and byte emission are explicit gates instead of implicit mutations.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

ICO_HEADER_SIZE = 6
ICO_DIRECTORY_ENTRY_SIZE = 16
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
KNOWN_DIB_HEADER_SIZES = frozenset((12, 40, 52, 56, 108, 124))

type IcoFileKind = Literal["ICO", "CUR"]
type IcoPlanStatus = Literal["planned", "unsupported"]
type IcoEmbeddedImageKind = Literal["png", "bmp_dib", "unknown"]
type IcoDirectoryActionKind = Literal[
    "preserve_header",
    "preserve_directory_entry",
    "preserve_image_payload",
    "route_embedded_png",
    "route_embedded_bmp_dib",
    "route_unknown_payload",
    "block_metadata_delegation",
]
type IcoEmissionGateCode = Literal[
    "truncated_header",
    "invalid_reserved",
    "unsupported_image_type",
    "invalid_image_count",
    "image_count_exceeds_exiftool_header_gate",
    "truncated_directory_entry",
    "truncated_image_payload",
    "image_payload_overlaps_directory",
    "image_payload_overlaps_payload",
    "metadata_delegation_request_blocked",
    "non_mutating_plan_requires_explicit_emission",
]
type IcoMetadataDelegationGateCode = Literal[
    "embedded_png_metadata_delegation_not_supported",
    "embedded_bmp_dib_metadata_delegation_not_supported",
    "unknown_embedded_metadata_delegation_not_supported",
]
type IcoEvidenceId = str


@dataclass(frozen=True)
class IcoEvidenceAnchor:
    evidence_id: IcoEvidenceId
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


ICO_MAIN_TABLE_SOURCE: IcoEvidenceId = "ico.table.main"
ICO_ICONDIR_TABLE_SOURCE: IcoEvidenceId = "ico.table.icondir"
ICO_HEADER_VALIDATION_SOURCE: IcoEvidenceId = "ico.process.header-validation"
ICO_DIRECTORY_TRAVERSAL_SOURCE: IcoEvidenceId = "ico.process.directory-traversal"
ICO_DIRECTORY_ONLY_SOURCE: IcoEvidenceId = "ico.process.directory-only"

ICO_EVIDENCE_ANCHORS: dict[IcoEvidenceId, IcoEvidenceAnchor] = {
    ICO_MAIN_TABLE_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_MAIN_TABLE_SOURCE,
        path="lib/Image/ExifTool/ICO.pm",
        line_start=19,
        line_end=37,
        symbol="%Image::ExifTool::ICO::Main",
        evidence="ICO.pm exposes ImageType, ImageCount, and IconDir from the ICO/CUR header.",
    ),
    ICO_ICONDIR_TABLE_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_ICONDIR_TABLE_SOURCE,
        path="lib/Image/ExifTool/ICO.pm",
        line_start=39,
        line_end=75,
        symbol="%Image::ExifTool::ICO::IconDir",
        evidence=(
            "IconDir maps width/height with zero as 256, NumColors, ICO color planes and "
            "bits-per-pixel, CUR hotspots, and ImageLength."
        ),
    ),
    ICO_HEADER_VALIDATION_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_HEADER_VALIDATION_SOURCE,
        path="lib/Image/ExifTool/ICO.pm",
        line_start=86,
        line_end=91,
        symbol="ProcessICO header validation",
        evidence=(
            "ProcessICO reads six bytes and accepts reserved zero, type 1 or 2, and a "
            "nonzero one-byte image count before setting ICO/CUR file type."
        ),
    ),
    ICO_DIRECTORY_TRAVERSAL_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_DIRECTORY_TRAVERSAL_SOURCE,
        path="lib/Image/ExifTool/ICO.pm",
        line_start=94,
        line_end=100,
        symbol="ProcessICO directory entry traversal",
        evidence=(
            "ProcessICO reads ImageCount and then traverses 16-byte directory entries, "
            "warning when an entry is truncated."
        ),
    ),
    ICO_DIRECTORY_ONLY_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_DIRECTORY_ONLY_SOURCE,
        path="lib/Image/ExifTool/ICO.pm",
        line_start=96,
        line_end=102,
        symbol="ProcessICO directory-only processing",
        evidence=(
            "ProcessICO handles directory records only; it does not seek into embedded "
            "PNG or DIB payloads for metadata extraction or mutation."
        ),
    ),
}

ICO_DIRECTORY_TRANSACTION_SOURCES = (
    ICO_MAIN_TABLE_SOURCE,
    ICO_ICONDIR_TABLE_SOURCE,
    ICO_HEADER_VALIDATION_SOURCE,
    ICO_DIRECTORY_TRAVERSAL_SOURCE,
    ICO_DIRECTORY_ONLY_SOURCE,
)


@dataclass(frozen=True)
class IcoMetadataDelegationRequest:
    entry_index: int
    metadata_kind: str


@dataclass(frozen=True)
class IcoOutputEmissionGate:
    code: IcoEmissionGateCode
    reason: str
    evidence_ids: tuple[IcoEvidenceId, ...]


@dataclass(frozen=True)
class IcoMetadataDelegationGate:
    code: IcoMetadataDelegationGateCode
    entry_index: int
    embedded_image_kind: IcoEmbeddedImageKind
    requested_metadata_kind: str | None
    reason: str
    evidence_ids: tuple[IcoEvidenceId, ...]


@dataclass(frozen=True)
class IcoHeaderPlan:
    reserved: int | None
    image_type_code: int | None
    file_kind: IcoFileKind | None
    image_count: int | None
    is_supported: bool
    reason: IcoEmissionGateCode | None
    evidence_ids: tuple[IcoEvidenceId, ...]


@dataclass(frozen=True)
class IcoDirectoryEntryPlan:
    index: int
    directory_offset: int
    width_byte: int
    height_byte: int
    image_width: int
    image_height: int
    num_colors: int
    reserved_byte: int
    color_planes: int | None
    bits_per_pixel: int | None
    hotspot_x: int | None
    hotspot_y: int | None
    image_length: int
    image_offset: int
    payload_end_offset: int
    embedded_image_kind: IcoEmbeddedImageKind
    payload: bytes | None
    evidence_ids: tuple[IcoEvidenceId, ...]

    @property
    def payload_is_preserved(self) -> bool:
        return self.payload is not None and len(self.payload) == self.image_length


@dataclass(frozen=True)
class IcoDirectoryActionPlan:
    kind: IcoDirectoryActionKind
    entry_index: int | None
    target: str
    offset: int
    size: int
    reason: str
    evidence_ids: tuple[IcoEvidenceId, ...]


@dataclass(frozen=True)
class IcoOutputSizePlan:
    input_file_size: int
    directory_table_size: int | None
    preserved_payload_size: int
    planned_file_size: int | None
    evidence_ids: tuple[IcoEvidenceId, ...]


@dataclass(frozen=True)
class IcoDirectoryImageTransactionPlan:
    status: IcoPlanStatus
    header: IcoHeaderPlan
    entries: tuple[IcoDirectoryEntryPlan, ...]
    actions: tuple[IcoDirectoryActionPlan, ...]
    metadata_delegation_gates: tuple[IcoMetadataDelegationGate, ...]
    output_emission_gates: tuple[IcoOutputEmissionGate, ...]
    output_size: IcoOutputSizePlan
    evidence_ids: tuple[IcoEvidenceId, ...]
    source_data: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"ICO/CUR directory image transaction output is gated: {gate_codes}")
        return self.source_data


def build_ico_directory_image_transaction_plan(
    data: bytes,
    *,
    metadata_delegation_requests: Iterable[IcoMetadataDelegationRequest] = (),
    allow_output_emission: bool = False,
) -> IcoDirectoryImageTransactionPlan:
    """Build a non-mutating ICO/CUR directory and embedded-image preservation plan."""

    requests = tuple(metadata_delegation_requests)
    header = _build_header_plan(data)
    gates: list[IcoOutputEmissionGate] = []
    actions: list[IcoDirectoryActionPlan] = []
    entries: tuple[IcoDirectoryEntryPlan, ...] = ()

    if header.reason is not None:
        gates.append(
            IcoOutputEmissionGate(
                code=header.reason,
                reason="Input does not satisfy ExifTool's ICO/CUR header gate.",
                evidence_ids=header.evidence_ids,
            )
        )
    else:
        actions.append(
            IcoDirectoryActionPlan(
                kind="preserve_header",
                entry_index=None,
                target=header.file_kind or "ICO/CUR",
                offset=0,
                size=ICO_HEADER_SIZE,
                reason="Preserve the validated ICO/CUR header bytes.",
                evidence_ids=(ICO_MAIN_TABLE_SOURCE, ICO_HEADER_VALIDATION_SOURCE),
            )
        )
        entries, parse_gates = _parse_directory_entries(data, header)
        gates.extend(parse_gates)
        actions.extend(_entry_actions(entries))
        gates.extend(_range_gates(entries, header.image_count or 0))

    metadata_gates = _metadata_delegation_gates(entries, requests)
    if requests:
        for metadata_gate in metadata_gates:
            if metadata_gate.requested_metadata_kind is not None:
                entry = entries[metadata_gate.entry_index]
                actions.append(
                    IcoDirectoryActionPlan(
                        kind="block_metadata_delegation",
                        entry_index=metadata_gate.entry_index,
                        target=metadata_gate.requested_metadata_kind,
                        offset=entry.image_offset,
                        size=entry.image_length,
                        reason=metadata_gate.reason,
                        evidence_ids=metadata_gate.evidence_ids,
                    )
                )
                gates.append(
                    IcoOutputEmissionGate(
                        code="metadata_delegation_request_blocked",
                        reason=metadata_gate.reason,
                        evidence_ids=metadata_gate.evidence_ids,
                    )
                )

    if not allow_output_emission:
        gates.append(
            IcoOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason=(
                    "ICO/CUR directory image plans preserve bytes and require explicit "
                    "permission before emitting the non-mutated source."
                ),
                evidence_ids=(ICO_DIRECTORY_ONLY_SOURCE,),
            )
        )

    status: IcoPlanStatus = "unsupported" if _has_unsupported_gate(gates) else "planned"
    output_size = IcoOutputSizePlan(
        input_file_size=len(data),
        directory_table_size=(header.image_count * ICO_DIRECTORY_ENTRY_SIZE)
        if header.image_count is not None
        else None,
        preserved_payload_size=sum(entry.image_length for entry in entries if entry.payload),
        planned_file_size=len(data) if status == "planned" else None,
        evidence_ids=(ICO_DIRECTORY_TRAVERSAL_SOURCE, ICO_DIRECTORY_ONLY_SOURCE),
    )
    evidence_ids = _unique_ids(
        (
            *ICO_DIRECTORY_TRANSACTION_SOURCES,
            *header.evidence_ids,
            *(evidence_id for entry in entries for evidence_id in entry.evidence_ids),
            *(evidence_id for action in actions for evidence_id in action.evidence_ids),
            *(evidence_id for gate in gates for evidence_id in gate.evidence_ids),
            *(evidence_id for gate in metadata_gates for evidence_id in gate.evidence_ids),
        )
    )
    return IcoDirectoryImageTransactionPlan(
        status=status,
        header=header,
        entries=entries,
        actions=tuple(actions),
        metadata_delegation_gates=metadata_gates,
        output_emission_gates=_unique_output_gates(tuple(gates)),
        output_size=output_size,
        evidence_ids=evidence_ids,
        source_data=data,
    )


plan_ico_directory_image_transaction = build_ico_directory_image_transaction_plan


def _build_header_plan(data: bytes) -> IcoHeaderPlan:
    if len(data) < ICO_HEADER_SIZE:
        return IcoHeaderPlan(
            reserved=None,
            image_type_code=None,
            file_kind=None,
            image_count=None,
            is_supported=False,
            reason="truncated_header",
            evidence_ids=(ICO_HEADER_VALIDATION_SOURCE,),
        )

    reserved = int.from_bytes(data[0:2], "little")
    image_type_code = int.from_bytes(data[2:4], "little")
    image_count = int.from_bytes(data[4:6], "little")
    file_kind = _file_kind(image_type_code)
    reason: IcoEmissionGateCode | None = None
    if reserved != 0:
        reason = "invalid_reserved"
    elif file_kind is None:
        reason = "unsupported_image_type"
    elif image_count == 0:
        reason = "invalid_image_count"
    elif image_count > 255:
        reason = "image_count_exceeds_exiftool_header_gate"

    return IcoHeaderPlan(
        reserved=reserved,
        image_type_code=image_type_code,
        file_kind=file_kind,
        image_count=image_count,
        is_supported=reason is None,
        reason=reason,
        evidence_ids=(ICO_MAIN_TABLE_SOURCE, ICO_HEADER_VALIDATION_SOURCE),
    )


def _parse_directory_entries(
    data: bytes,
    header: IcoHeaderPlan,
) -> tuple[tuple[IcoDirectoryEntryPlan, ...], tuple[IcoOutputEmissionGate, ...]]:
    entries: list[IcoDirectoryEntryPlan] = []
    gates: list[IcoOutputEmissionGate] = []
    image_count = header.image_count or 0
    file_kind = header.file_kind
    for index in range(image_count):
        directory_offset = ICO_HEADER_SIZE + index * ICO_DIRECTORY_ENTRY_SIZE
        entry_end = directory_offset + ICO_DIRECTORY_ENTRY_SIZE
        if entry_end > len(data):
            gates.append(
                IcoOutputEmissionGate(
                    code="truncated_directory_entry",
                    reason=f"Directory entry {index} ended before 16 bytes could be read.",
                    evidence_ids=(ICO_DIRECTORY_TRAVERSAL_SOURCE,),
                )
            )
            break
        raw = data[directory_offset:entry_end]
        width_byte = raw[0]
        height_byte = raw[1]
        image_length = int.from_bytes(raw[8:12], "little")
        image_offset = int.from_bytes(raw[12:16], "little")
        payload_end = image_offset + image_length
        payload = data[image_offset:payload_end] if payload_end <= len(data) else None
        color_planes = int.from_bytes(raw[4:6], "little") if file_kind == "ICO" else None
        bits_per_pixel = int.from_bytes(raw[6:8], "little") if file_kind == "ICO" else None
        hotspot_x = int.from_bytes(raw[4:6], "little") if file_kind == "CUR" else None
        hotspot_y = int.from_bytes(raw[6:8], "little") if file_kind == "CUR" else None
        entries.append(
            IcoDirectoryEntryPlan(
                index=index,
                directory_offset=directory_offset,
                width_byte=width_byte,
                height_byte=height_byte,
                image_width=_ico_dimension(width_byte),
                image_height=_ico_dimension(height_byte),
                num_colors=raw[2],
                reserved_byte=raw[3],
                color_planes=color_planes,
                bits_per_pixel=bits_per_pixel,
                hotspot_x=hotspot_x,
                hotspot_y=hotspot_y,
                image_length=image_length,
                image_offset=image_offset,
                payload_end_offset=payload_end,
                embedded_image_kind=_embedded_image_kind(payload),
                payload=payload,
                evidence_ids=(ICO_ICONDIR_TABLE_SOURCE, ICO_DIRECTORY_TRAVERSAL_SOURCE),
            )
        )
        if payload is None:
            gates.append(
                IcoOutputEmissionGate(
                    code="truncated_image_payload",
                    reason=(
                        f"Directory entry {index} points to bytes "
                        f"{image_offset}:{payload_end}, past end of file."
                    ),
                    evidence_ids=(ICO_DIRECTORY_TRAVERSAL_SOURCE, ICO_DIRECTORY_ONLY_SOURCE),
                )
            )
    return tuple(entries), tuple(gates)


def _entry_actions(
    entries: tuple[IcoDirectoryEntryPlan, ...],
) -> tuple[IcoDirectoryActionPlan, ...]:
    actions: list[IcoDirectoryActionPlan] = []
    for entry in entries:
        actions.append(
            IcoDirectoryActionPlan(
                kind="preserve_directory_entry",
                entry_index=entry.index,
                target="IconDir",
                offset=entry.directory_offset,
                size=ICO_DIRECTORY_ENTRY_SIZE,
                reason="Preserve the fixed 16-byte directory entry and its data offset fields.",
                evidence_ids=(ICO_ICONDIR_TABLE_SOURCE, ICO_DIRECTORY_TRAVERSAL_SOURCE),
            )
        )
        route_kind: IcoDirectoryActionKind
        if entry.embedded_image_kind == "png":
            route_kind = "route_embedded_png"
            target = "embedded PNG"
        elif entry.embedded_image_kind == "bmp_dib":
            route_kind = "route_embedded_bmp_dib"
            target = "embedded BMP/DIB"
        else:
            route_kind = "route_unknown_payload"
            target = "embedded image payload"
        actions.append(
            IcoDirectoryActionPlan(
                kind=route_kind,
                entry_index=entry.index,
                target=target,
                offset=entry.image_offset,
                size=entry.image_length,
                reason=(
                    "Route the embedded image bytes for preservation only; ICO.pm does "
                    "not delegate into these payloads."
                ),
                evidence_ids=(ICO_DIRECTORY_ONLY_SOURCE,),
            )
        )
        actions.append(
            IcoDirectoryActionPlan(
                kind="preserve_image_payload",
                entry_index=entry.index,
                target=target,
                offset=entry.image_offset,
                size=entry.image_length,
                reason="Preserve directory-declared image data offset and size unchanged.",
                evidence_ids=(ICO_ICONDIR_TABLE_SOURCE, ICO_DIRECTORY_ONLY_SOURCE),
            )
        )
    return tuple(actions)


def _range_gates(
    entries: tuple[IcoDirectoryEntryPlan, ...],
    image_count: int,
) -> tuple[IcoOutputEmissionGate, ...]:
    gates: list[IcoOutputEmissionGate] = []
    directory_end = ICO_HEADER_SIZE + image_count * ICO_DIRECTORY_ENTRY_SIZE
    for entry in entries:
        if entry.image_length == 0:
            continue
        if entry.image_offset < directory_end and entry.payload_end_offset > ICO_HEADER_SIZE:
            gates.append(
                IcoOutputEmissionGate(
                    code="image_payload_overlaps_directory",
                    reason=f"Image payload {entry.index} overlaps the ICO/CUR directory table.",
                    evidence_ids=(ICO_DIRECTORY_TRAVERSAL_SOURCE, ICO_DIRECTORY_ONLY_SOURCE),
                )
            )
    for left_index, left in enumerate(entries):
        if left.image_length == 0:
            continue
        for right in entries[left_index + 1 :]:
            if right.image_length == 0:
                continue
            if (
                left.image_offset < right.payload_end_offset
                and right.image_offset < left.payload_end_offset
            ):
                gates.append(
                    IcoOutputEmissionGate(
                        code="image_payload_overlaps_payload",
                        reason=(
                            f"Image payload {left.index} overlaps image payload {right.index}."
                        ),
                        evidence_ids=(
                            ICO_DIRECTORY_TRAVERSAL_SOURCE,
                            ICO_DIRECTORY_ONLY_SOURCE,
                        ),
                    )
                )
    return tuple(gates)


def _metadata_delegation_gates(
    entries: tuple[IcoDirectoryEntryPlan, ...],
    requests: tuple[IcoMetadataDelegationRequest, ...],
) -> tuple[IcoMetadataDelegationGate, ...]:
    gates: list[IcoMetadataDelegationGate] = []
    for entry in entries:
        requested = tuple(request for request in requests if request.entry_index == entry.index)
        if not requested:
            gates.append(_metadata_gate(entry, None))
        else:
            for request in requested:
                gates.append(_metadata_gate(entry, request.metadata_kind))
    return tuple(gates)


def _metadata_gate(
    entry: IcoDirectoryEntryPlan,
    requested_metadata_kind: str | None,
) -> IcoMetadataDelegationGate:
    if entry.embedded_image_kind == "png":
        code: IcoMetadataDelegationGateCode = "embedded_png_metadata_delegation_not_supported"
    elif entry.embedded_image_kind == "bmp_dib":
        code = "embedded_bmp_dib_metadata_delegation_not_supported"
    else:
        code = "unknown_embedded_metadata_delegation_not_supported"
    request_text = (
        f" Requested {requested_metadata_kind} metadata cannot be delegated."
        if requested_metadata_kind is not None
        else ""
    )
    return IcoMetadataDelegationGate(
        code=code,
        entry_index=entry.index,
        embedded_image_kind=entry.embedded_image_kind,
        requested_metadata_kind=requested_metadata_kind,
        reason=(
            "ICO.pm reads directory entries only and has no embedded image metadata "
            f"delegation path for entry {entry.index}.{request_text}"
        ),
        evidence_ids=(ICO_DIRECTORY_ONLY_SOURCE,),
    )


def _file_kind(image_type_code: int) -> IcoFileKind | None:
    if image_type_code == 1:
        return "ICO"
    if image_type_code == 2:
        return "CUR"
    return None


def _ico_dimension(value: int) -> int:
    if value == 0:
        return 256
    return value


def _embedded_image_kind(payload: bytes | None) -> IcoEmbeddedImageKind:
    if payload is None:
        return "unknown"
    if payload.startswith(PNG_SIGNATURE):
        return "png"
    if len(payload) >= 4 and int.from_bytes(payload[0:4], "little") in KNOWN_DIB_HEADER_SIZES:
        return "bmp_dib"
    return "unknown"


def _has_unsupported_gate(gates: list[IcoOutputEmissionGate]) -> bool:
    unsupported_codes = {
        "truncated_header",
        "invalid_reserved",
        "unsupported_image_type",
        "invalid_image_count",
        "image_count_exceeds_exiftool_header_gate",
        "truncated_directory_entry",
        "truncated_image_payload",
        "image_payload_overlaps_directory",
        "image_payload_overlaps_payload",
    }
    return any(gate.code in unsupported_codes for gate in gates)


def _unique_output_gates(
    gates: tuple[IcoOutputEmissionGate, ...],
) -> tuple[IcoOutputEmissionGate, ...]:
    unique: list[IcoOutputEmissionGate] = []
    seen: set[tuple[IcoEmissionGateCode, str]] = set()
    for gate in gates:
        key = (gate.code, gate.reason)
        if key not in seen:
            seen.add(key)
            unique.append(gate)
    return tuple(unique)


def _unique_ids(evidence_ids: Iterable[IcoEvidenceId]) -> tuple[IcoEvidenceId, ...]:
    unique: list[IcoEvidenceId] = []
    seen: set[IcoEvidenceId] = set()
    for evidence_id in evidence_ids:
        if evidence_id not in seen:
            seen.add(evidence_id)
            unique.append(evidence_id)
    return tuple(unique)
