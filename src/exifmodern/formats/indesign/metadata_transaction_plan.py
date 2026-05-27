"""Non-mutating Adobe InDesign metadata transaction plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MASTER_PAGE_GUID = b"\x06\x06\xed\xf5\xd8\x1d\x46\xe5\xbd\x31\xef\xe7\xfe\x74\xb7\x1d"
STREAM_HEADER_GUID = b"\xde\x39\x39\x79\x51\x88\x4b\x6c\x8e\x63\xee\xf8\xae\xe0\xdd\x38"
STREAM_TRAILER_GUID = b"\xfd\xce\xdb\x70\xf7\x86\x4b\x4f\xa4\xd3\xc7\x28\xb3\x41\x71\x06"
MASTER_PAGE_SIZE = 4096
MASTER_PAGE_PAIR_SIZE = MASTER_PAGE_SIZE * 2
STREAM_HEADER_SIZE = 32
STREAM_TRAILER_SIZE = 32
XMP_MINIMUM_PREFIX_SIZE = 56
XMP_MAX_EXIFTOOL_READ_SIZE = 300 * 1024 * 1024
WRITABLE_XMP_CLASS_FLAG = 0x40000000
DOCUMENT_FILE_TYPE_TOKEN = b"DOCUMENT"

type InDesignPlanStatus = Literal["planned", "unsupported"]
type InDesignFileType = Literal["IND", "INDD"]
type InDesignByteOrder = Literal["little", "big"]
type InDesignMetadataKind = Literal["xmp", "unknown"]
type InDesignRouteResponsibility = Literal["write_xmp_to_ind", "unsupported_by_indesign_pm"]
type InDesignEmissionGateCode = Literal[
    "output_emission_requires_explicit_opt_in",
    "truncated_initial_guid",
    "unsupported_master_page_guid",
    "truncated_file_type_token",
    "truncated_master_pages",
    "invalid_second_master_page",
    "invalid_stream_byte_order",
    "invalid_page_count",
    "large_file_support_not_modeled",
    "truncated_indesign_database",
    "truncated_stream_header",
    "corrupt_or_unsupported_indesign_version",
    "truncated_stream_data",
    "truncated_stream_trailer",
    "invalid_stream_trailer",
    "non_matching_stream_trailer",
    "truncated_xmp_stream",
    "xmp_stream_too_large",
    "xmp_stream_is_not_writable",
    "xmp_block_delete_not_supported",
    "no_xmp_stream_to_edit",
    "mutating_indesign_writer_not_ported",
    "unsupported_metadata_group",
]
type InDesignRewriteBlockerCode = Literal[
    "mutating_indesign_writer_not_ported",
    "xmp_stream_is_not_writable",
    "xmp_block_delete_not_supported",
    "no_xmp_stream_to_edit",
    "unsupported_metadata_group",
]

INDESIGN_WRITE_MAP_EVIDENCE_ID = "indesign.indesign-write-map"
INDESIGN_GUID_EVIDENCE_ID = "indesign.indesign-guid"
INDESIGN_SIGNATURE_EVIDENCE_ID = "indesign.indesign-signature"
INDESIGN_MASTER_PAGE_EVIDENCE_ID = "indesign.indesign-master-page"
INDESIGN_LARGE_FILE_EVIDENCE_ID = "indesign.indesign-large-file"
INDESIGN_WRITE_INIT_EVIDENCE_ID = "indesign.indesign-write-init"
INDESIGN_STREAM_SCAN_EVIDENCE_ID = "indesign.indesign-stream-scan"
INDESIGN_XMP_DETECTION_EVIDENCE_ID = "indesign.indesign-xmp-detection"
INDESIGN_XMP_LIMIT_EVIDENCE_ID = "indesign.indesign-xmp-limit"
INDESIGN_XMP_LENGTH_EVIDENCE_ID = "indesign.indesign-xmp-length"
INDESIGN_XMP_WRITE_EVIDENCE_ID = "indesign.indesign-xmp-write"
INDESIGN_TRAILER_EVIDENCE_ID = "indesign.indesign-trailer"
INDESIGN_PADDING_EVIDENCE_ID = "indesign.indesign-padding"
INDESIGN_NO_XMP_EVIDENCE_ID = "indesign.indesign-no-xmp"

INDESIGN_TRANSACTION_EVIDENCE_IDS = (
    INDESIGN_WRITE_MAP_EVIDENCE_ID,
    INDESIGN_GUID_EVIDENCE_ID,
    INDESIGN_SIGNATURE_EVIDENCE_ID,
    INDESIGN_MASTER_PAGE_EVIDENCE_ID,
    INDESIGN_STREAM_SCAN_EVIDENCE_ID,
    INDESIGN_XMP_DETECTION_EVIDENCE_ID,
    INDESIGN_XMP_LENGTH_EVIDENCE_ID,
    INDESIGN_XMP_WRITE_EVIDENCE_ID,
    INDESIGN_TRAILER_EVIDENCE_ID,
)


@dataclass(frozen=True)
class InDesignEmissionGate:
    code: InDesignEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class InDesignRewriteBlocker:
    code: InDesignRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class InDesignHeaderPlan:
    file_type: InDesignFileType
    file_type_token: bytes
    first_master_sequence: int
    second_master_sequence: int
    selected_master_page_index: int
    stream_int32_byte_order: InDesignByteOrder
    page_count: int
    contiguous_stream_start: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class InDesignPaddingPlan:
    offset: int
    payload: bytes
    null_only: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class InDesignContiguousStreamPlan:
    index: int
    header_offset: int
    payload_offset: int
    payload_length: int
    trailer_offset: int
    end_offset: int
    uid_and_class_id: bytes
    class_id: int
    checksum: int
    metadata_kind: InDesignMetadataKind
    payload: bytes
    xmp_payload: bytes | None
    xmp_declared_length: int | None
    xmp_available_length: int | None
    xmp_writable: bool
    xmp_effective_length: int | None
    evidence_ids: tuple[str, ...]

    @property
    def uid_and_class_id_hex(self) -> str:
        return self.uid_and_class_id.hex()


@dataclass(frozen=True)
class InDesignMetadataRoute:
    requested_group: str
    target_group: str | None
    responsibility: InDesignRouteResponsibility
    supported_by_exiftool: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class InDesignMetadataTransactionPlan:
    status: InDesignPlanStatus
    source: bytes
    header: InDesignHeaderPlan | None
    streams: tuple[InDesignContiguousStreamPlan, ...]
    padding: InDesignPaddingPlan | None
    metadata_routes: tuple[InDesignMetadataRoute, ...]
    output_emission_gates: tuple[InDesignEmissionGate, ...]
    rewrite_blockers: tuple[InDesignRewriteBlocker, ...]
    requested_xmp_payload: bytes | None
    requested_delete_xmp: bool
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return not self.output_emission_gates

    @property
    def xmp_streams(self) -> tuple[InDesignContiguousStreamPlan, ...]:
        return tuple(stream for stream in self.streams if stream.metadata_kind == "xmp")

    def emit(self) -> bytes:
        if self.output_emission_gates:
            codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"InDesign transaction cannot be emitted: {codes}")
        return self.source


def build_indesign_metadata_transaction_plan(
    data: bytes,
    *,
    requested_metadata_groups: tuple[str, ...] = (),
    xmp_payload: bytes | None = None,
    delete_xmp: bool = False,
    allow_output_emission: bool = False,
) -> InDesignMetadataTransactionPlan:
    routes = _metadata_routes(requested_metadata_groups, xmp_payload, delete_xmp)
    header, header_gates = _parse_header(data)
    streams: tuple[InDesignContiguousStreamPlan, ...] = ()
    padding: InDesignPaddingPlan | None = None
    stream_gates: tuple[InDesignEmissionGate, ...] = ()

    if header is not None and not header_gates:
        streams, padding, stream_gates = _parse_streams(data, header)

    gates = header_gates + stream_gates
    xmp_streams = tuple(stream for stream in streams if stream.metadata_kind == "xmp")
    gates += _request_gates(
        routes=routes,
        xmp_streams=xmp_streams,
        xmp_payload=xmp_payload,
        delete_xmp=delete_xmp,
    )
    if not allow_output_emission:
        gates += (
            InDesignEmissionGate(
                code="output_emission_requires_explicit_opt_in",
                reason="Plans preserve source bytes and require explicit opt-in before emission.",
                evidence_ids=(INDESIGN_WRITE_INIT_EVIDENCE_ID,),
            ),
        )

    return InDesignMetadataTransactionPlan(
        status="unsupported" if gates and header is None else "planned",
        source=data,
        header=header,
        streams=streams,
        padding=padding,
        metadata_routes=routes,
        output_emission_gates=gates,
        rewrite_blockers=_rewrite_blockers(routes, xmp_streams, xmp_payload, delete_xmp),
        requested_xmp_payload=xmp_payload,
        requested_delete_xmp=delete_xmp,
        evidence_ids=INDESIGN_TRANSACTION_EVIDENCE_IDS,
    )


plan_indesign_metadata_transaction = build_indesign_metadata_transaction_plan


def _parse_header(
    data: bytes,
) -> tuple[InDesignHeaderPlan | None, tuple[InDesignEmissionGate, ...]]:
    if len(data) < len(MASTER_PAGE_GUID):
        return None, (
            _gate(
                "truncated_initial_guid",
                "The file ends before the 16-byte InDesign master page GUID.",
                INDESIGN_SIGNATURE_EVIDENCE_ID,
            ),
        )
    if data[:16] != MASTER_PAGE_GUID:
        return None, (
            _gate(
                "unsupported_master_page_guid",
                "The first 16 bytes do not match the InDesign master page GUID.",
                INDESIGN_SIGNATURE_EVIDENCE_ID,
            ),
        )
    if len(data) < 24:
        return None, (
            _gate(
                "truncated_file_type_token",
                "The file ends before the eight-byte InDesign file type token.",
                INDESIGN_SIGNATURE_EVIDENCE_ID,
            ),
        )
    if len(data) < MASTER_PAGE_PAIR_SIZE:
        return None, (
            _gate(
                "truncated_master_pages",
                "The file ends before the two 4096-byte master pages required by ExifTool.",
                INDESIGN_MASTER_PAGE_EVIDENCE_ID,
            ),
        )

    second_page = data[MASTER_PAGE_SIZE:MASTER_PAGE_PAIR_SIZE]
    if second_page[:16] != MASTER_PAGE_GUID:
        return None, (
            _gate(
                "invalid_second_master_page",
                "The second master page does not start with the InDesign master page GUID.",
                INDESIGN_MASTER_PAGE_EVIDENCE_ID,
            ),
        )

    first_page = data[:MASTER_PAGE_SIZE]
    first_sequence = _uint64le(first_page, 264)
    second_sequence = _uint64le(second_page, 264)
    selected_page = second_page if second_sequence > first_sequence else first_page
    selected_index = 1 if second_sequence > first_sequence else 0
    byte_order_marker = selected_page[24]
    if byte_order_marker == 1:
        byte_order: InDesignByteOrder = "little"
    elif byte_order_marker == 2:
        byte_order = "big"
    else:
        return None, (
            _gate(
                "invalid_stream_byte_order",
                "The selected master page stream byte-order marker is neither 1 nor 2.",
                INDESIGN_MASTER_PAGE_EVIDENCE_ID,
            ),
        )

    page_count = _uint32le(selected_page, 280)
    if page_count < 2:
        return None, (
            _gate(
                "invalid_page_count",
                "The selected master page reports fewer than two 4096-byte pages.",
                INDESIGN_MASTER_PAGE_EVIDENCE_ID,
            ),
        )
    contiguous_start = page_count * MASTER_PAGE_SIZE
    if contiguous_start > 0x7FFFFFFF:
        return None, (
            _gate(
                "large_file_support_not_modeled",
                "This planner does not model ExifTool's LargeFileSupport write gate.",
                INDESIGN_LARGE_FILE_EVIDENCE_ID,
            ),
        )
    if contiguous_start > len(data):
        return None, (
            _gate(
                "truncated_indesign_database",
                "The master page page count points beyond the available bytes.",
                INDESIGN_WRITE_INIT_EVIDENCE_ID,
            ),
        )

    file_type: InDesignFileType = "INDD" if data[16:24] == DOCUMENT_FILE_TYPE_TOKEN else "IND"
    return (
        InDesignHeaderPlan(
            file_type=file_type,
            file_type_token=data[16:24],
            first_master_sequence=first_sequence,
            second_master_sequence=second_sequence,
            selected_master_page_index=selected_index,
            stream_int32_byte_order=byte_order,
            page_count=page_count,
            contiguous_stream_start=contiguous_start,
            evidence_ids=(
                INDESIGN_SIGNATURE_EVIDENCE_ID,
                INDESIGN_MASTER_PAGE_EVIDENCE_ID,
                INDESIGN_LARGE_FILE_EVIDENCE_ID,
            ),
        ),
        (),
    )


def _parse_streams(
    data: bytes,
    header: InDesignHeaderPlan,
) -> tuple[
    tuple[InDesignContiguousStreamPlan, ...],
    InDesignPaddingPlan | None,
    tuple[InDesignEmissionGate, ...],
]:
    streams: list[InDesignContiguousStreamPlan] = []
    gates: list[InDesignEmissionGate] = []
    offset = header.contiguous_stream_start
    padding: InDesignPaddingPlan | None = None

    while offset < len(data):
        remaining = len(data) - offset
        if remaining < STREAM_HEADER_SIZE:
            tail = data[offset:]
            if tail and not _is_all_zero(tail):
                gates.append(
                    _gate(
                        "truncated_stream_header",
                        "A terminal stream header is shorter than 32 bytes and not null padding.",
                        INDESIGN_STREAM_SCAN_EVIDENCE_ID,
                    )
                )
            padding = InDesignPaddingPlan(
                offset=offset,
                payload=tail,
                null_only=_is_all_zero(tail),
                evidence_ids=(INDESIGN_STREAM_SCAN_EVIDENCE_ID,),
            )
            break

        stream_header = data[offset : offset + STREAM_HEADER_SIZE]
        if not stream_header.startswith(STREAM_HEADER_GUID):
            padding_payload = data[offset:]
            if _is_all_zero(stream_header):
                padding = InDesignPaddingPlan(
                    offset=offset,
                    payload=padding_payload,
                    null_only=True,
                    evidence_ids=(INDESIGN_STREAM_SCAN_EVIDENCE_ID,),
                )
                break
            if len(padding_payload) > 8190 or len(padding_payload.rstrip(b"\0")) > 4095:
                gates.append(
                    _gate(
                        "corrupt_or_unsupported_indesign_version",
                        "Terminal non-null padding exceeds the length tolerated by ExifTool.",
                        INDESIGN_STREAM_SCAN_EVIDENCE_ID,
                    )
                )
            padding = InDesignPaddingPlan(
                offset=offset,
                payload=padding_payload,
                null_only=False,
                evidence_ids=(INDESIGN_STREAM_SCAN_EVIDENCE_ID,),
            )
            break

        payload_length = _uint32le(stream_header, 24)
        payload_offset = offset + STREAM_HEADER_SIZE
        payload_end = payload_offset + payload_length
        trailer_end = payload_end + STREAM_TRAILER_SIZE
        if payload_end > len(data):
            gates.append(
                _gate(
                    "truncated_stream_data",
                    "The stream payload length extends beyond the available bytes.",
                    INDESIGN_TRAILER_EVIDENCE_ID,
                )
            )
            break
        if trailer_end > len(data):
            gates.append(
                _gate(
                    "truncated_stream_trailer",
                    "The stream payload is not followed by a complete 32-byte trailer.",
                    INDESIGN_TRAILER_EVIDENCE_ID,
                )
            )
            break

        payload = data[payload_offset:payload_end]
        trailer = data[payload_end:trailer_end]
        if not trailer.startswith(STREAM_TRAILER_GUID):
            gates.append(
                _gate(
                    "invalid_stream_trailer",
                    "The stream trailer GUID does not match the InDesign trailer GUID.",
                    INDESIGN_TRAILER_EVIDENCE_ID,
                )
            )
            break
        if trailer[16:24] != stream_header[16:24]:
            gates.append(
                _gate(
                    "non_matching_stream_trailer",
                    "The stream trailer UID/ClassID bytes do not match the header bytes.",
                    INDESIGN_TRAILER_EVIDENCE_ID,
                )
            )
            break

        stream, stream_gates = _stream_plan(
            index=len(streams),
            offset=offset,
            stream_header=stream_header,
            payload=payload,
            payload_offset=payload_offset,
            trailer_offset=payload_end,
            end_offset=trailer_end,
            byte_order=header.stream_int32_byte_order,
        )
        streams.append(stream)
        gates.extend(stream_gates)
        offset = trailer_end

    return tuple(streams), padding, tuple(gates)


def _stream_plan(
    *,
    index: int,
    offset: int,
    stream_header: bytes,
    payload: bytes,
    payload_offset: int,
    trailer_offset: int,
    end_offset: int,
    byte_order: InDesignByteOrder,
) -> tuple[InDesignContiguousStreamPlan, tuple[InDesignEmissionGate, ...]]:
    class_id = _uint32le(stream_header, 20)
    checksum = _uint32le(stream_header, 28)
    metadata_kind: InDesignMetadataKind = "unknown"
    xmp_payload: bytes | None = None
    xmp_declared_length: int | None = None
    xmp_available_length: int | None = None
    xmp_effective_length: int | None = None
    gates: tuple[InDesignEmissionGate, ...] = ()
    references: tuple[str, ...] = (
        INDESIGN_STREAM_SCAN_EVIDENCE_ID,
        INDESIGN_TRAILER_EVIDENCE_ID,
    )

    if len(payload) > XMP_MINIMUM_PREFIX_SIZE and _has_xmp_prefix(
        payload[:XMP_MINIMUM_PREFIX_SIZE]
    ):
        metadata_kind = "xmp"
        xmp_available_length = len(payload) - 4
        xmp_payload = payload[4:]
        xmp_declared_length = _stream_length_word(payload[:4], byte_order)
        xmp_effective_length = min(xmp_declared_length, xmp_available_length)
        references = (
            INDESIGN_STREAM_SCAN_EVIDENCE_ID,
            INDESIGN_XMP_DETECTION_EVIDENCE_ID,
            INDESIGN_XMP_LENGTH_EVIDENCE_ID,
            INDESIGN_XMP_WRITE_EVIDENCE_ID,
            INDESIGN_TRAILER_EVIDENCE_ID,
        )
        if xmp_available_length > XMP_MAX_EXIFTOOL_READ_SIZE:
            gates += (
                _gate(
                    "xmp_stream_too_large",
                    "The XMP stream is larger than ExifTool's normal 300 MiB processing guard.",
                    INDESIGN_XMP_LIMIT_EVIDENCE_ID,
                ),
            )
        if xmp_declared_length > xmp_available_length:
            gates += (
                _gate(
                    "truncated_xmp_stream",
                    "The XMP length word declares more bytes than the stream provides.",
                    INDESIGN_XMP_LENGTH_EVIDENCE_ID,
                ),
            )

    return (
        InDesignContiguousStreamPlan(
            index=index,
            header_offset=offset,
            payload_offset=payload_offset,
            payload_length=len(payload),
            trailer_offset=trailer_offset,
            end_offset=end_offset,
            uid_and_class_id=stream_header[16:24],
            class_id=class_id,
            checksum=checksum,
            metadata_kind=metadata_kind,
            payload=payload,
            xmp_payload=xmp_payload,
            xmp_declared_length=xmp_declared_length,
            xmp_available_length=xmp_available_length,
            xmp_writable=bool(class_id & WRITABLE_XMP_CLASS_FLAG),
            xmp_effective_length=xmp_effective_length,
            evidence_ids=references,
        ),
        gates,
    )


def _metadata_routes(
    requested_groups: tuple[str, ...],
    xmp_payload: bytes | None,
    delete_xmp: bool,
) -> tuple[InDesignMetadataRoute, ...]:
    normalized: list[str] = []
    for group in requested_groups:
        upper = group.upper()
        if upper not in normalized:
            normalized.append(upper)
    if (xmp_payload is not None or delete_xmp) and "XMP" not in normalized:
        normalized.append("XMP")
    return tuple(_metadata_route(group) for group in normalized)


def _metadata_route(group: str) -> InDesignMetadataRoute:
    if group == "XMP":
        return InDesignMetadataRoute(
            requested_group=group,
            target_group="IND",
            responsibility="write_xmp_to_ind",
            supported_by_exiftool=True,
            evidence_ids=(INDESIGN_WRITE_MAP_EVIDENCE_ID, INDESIGN_XMP_WRITE_EVIDENCE_ID),
        )
    return InDesignMetadataRoute(
        requested_group=group,
        target_group=None,
        responsibility="unsupported_by_indesign_pm",
        supported_by_exiftool=False,
        evidence_ids=(INDESIGN_WRITE_MAP_EVIDENCE_ID,),
    )


def _request_gates(
    *,
    routes: tuple[InDesignMetadataRoute, ...],
    xmp_streams: tuple[InDesignContiguousStreamPlan, ...],
    xmp_payload: bytes | None,
    delete_xmp: bool,
) -> tuple[InDesignEmissionGate, ...]:
    gates: list[InDesignEmissionGate] = []
    for route in routes:
        if not route.supported_by_exiftool:
            gates.append(
                _gate(
                    "unsupported_metadata_group",
                    f"InDesign.pm does not route {route.requested_group} writes.",
                    INDESIGN_WRITE_MAP_EVIDENCE_ID,
                )
            )
    if xmp_payload is not None:
        gates.append(
            _gate(
                "mutating_indesign_writer_not_ported",
                (
                    "This slice records the ExifTool XMP write route but does not "
                    "emit rewritten bytes."
                ),
                INDESIGN_XMP_WRITE_EVIDENCE_ID,
            )
        )
    if delete_xmp:
        gates.append(
            _gate(
                "xmp_block_delete_not_supported",
                (
                    "ExifTool marks InDesign XMP NoDelete and warns that XMP cannot "
                    "be deleted as a block."
                ),
                INDESIGN_XMP_WRITE_EVIDENCE_ID,
            )
        )
    if (xmp_payload is not None or delete_xmp) and not xmp_streams:
        gates.append(
            _gate(
                "no_xmp_stream_to_edit",
                "ExifTool write completion warns when no XMP stream is present.",
                INDESIGN_NO_XMP_EVIDENCE_ID,
            )
        )
    if xmp_payload is not None or delete_xmp:
        for stream in xmp_streams:
            if not stream.xmp_writable:
                gates.append(
                    _gate(
                        "xmp_stream_is_not_writable",
                        "ExifTool requires the XMP stream class flag 0x40000000 before writing.",
                        INDESIGN_XMP_WRITE_EVIDENCE_ID,
                    )
                )
    return tuple(gates)


def _rewrite_blockers(
    routes: tuple[InDesignMetadataRoute, ...],
    xmp_streams: tuple[InDesignContiguousStreamPlan, ...],
    xmp_payload: bytes | None,
    delete_xmp: bool,
) -> tuple[InDesignRewriteBlocker, ...]:
    blockers: list[InDesignRewriteBlocker] = []
    for route in routes:
        if not route.supported_by_exiftool:
            blockers.append(
                _blocker(
                    "unsupported_metadata_group",
                    f"InDesign.pm has no write route for {route.requested_group}.",
                    INDESIGN_WRITE_MAP_EVIDENCE_ID,
                )
            )
    if xmp_payload is not None:
        blockers.append(
            _blocker(
                "mutating_indesign_writer_not_ported",
                "The planner is non-mutating and does not port ProcessIND byte rewriting.",
                INDESIGN_XMP_WRITE_EVIDENCE_ID,
            )
        )
    if delete_xmp:
        blockers.append(
            _blocker(
                "xmp_block_delete_not_supported",
                "InDesign XMP uses NoDelete in ExifTool write handling.",
                INDESIGN_XMP_WRITE_EVIDENCE_ID,
            )
        )
    if (xmp_payload is not None or delete_xmp) and not xmp_streams:
        blockers.append(
            _blocker(
                "no_xmp_stream_to_edit",
                "There is no XMP stream for the requested InDesign XMP operation.",
                INDESIGN_NO_XMP_EVIDENCE_ID,
            )
        )
    if xmp_payload is not None or delete_xmp:
        for stream in xmp_streams:
            if not stream.xmp_writable:
                blockers.append(
                    _blocker(
                        "xmp_stream_is_not_writable",
                        "The stream class flag does not include ExifTool's writable XMP bit.",
                        INDESIGN_XMP_WRITE_EVIDENCE_ID,
                    )
                )
    return tuple(blockers)


def _has_xmp_prefix(prefix: bytes) -> bool:
    if len(prefix) < XMP_MINIMUM_PREFIX_SIZE:
        return False
    if not prefix[4:].startswith(b"<?xpacket begin="):
        return False
    quote = prefix[20:21]
    if quote not in (b"'", b'"'):
        return False
    id_quote = prefix[29:30]
    if id_quote not in (b"'", b'"'):
        return False
    return (
        prefix[21:29] == b"\xef\xbb\xbf" + quote + b" id="
        and prefix[30:54] == b"W5M0MpCehiHzreSzNTczkc9d"
        and prefix[54:55] == id_quote
    )


def _stream_length_word(value: bytes, byte_order: InDesignByteOrder) -> int:
    return int.from_bytes(value, "little" if byte_order == "little" else "big")


def _uint32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def _uint64le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little")


def _is_all_zero(data: bytes) -> bool:
    return all(byte == 0 for byte in data)


def _gate(
    code: InDesignEmissionGateCode,
    reason: str,
    evidence_id: str,
) -> InDesignEmissionGate:
    return InDesignEmissionGate(
        code=code,
        reason=reason,
        evidence_ids=(evidence_id,),
    )


def _blocker(
    code: InDesignRewriteBlockerCode,
    reason: str,
    evidence_id: str,
) -> InDesignRewriteBlocker:
    return InDesignRewriteBlocker(
        code=code,
        reason=reason,
        evidence_ids=(evidence_id,),
    )
