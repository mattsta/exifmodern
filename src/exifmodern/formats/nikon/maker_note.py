"""Source-grounded Nikon maker-note write plans."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.makernote.inline_ifd import (
    InlineMakerNoteIfdLocator,
    InlineMakerNoteStringWritePlan,
    InlineMakerNoteStringWriteStep,
)
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_BYTE,
    TIFF_TYPE_LONG,
    TIFF_TYPE_UNDEFINED,
    Endian,
)
from exifmodern.services.lens_identity_repository import SourceLensIdentityRepository
from exifmodern.services.source_lens_identity_runtime import (
    NikonLensDataSourceLensIdentityReport,
    NikonMakerNoteLensDataBridgeReport,
    NikonMakerNoteTagMap,
    nikon_lensdata_runtime_handoff_report_from_makernote_tags,
    resolve_nikon_lensdata_source_lens_identity_runtime_from_facts,
)

NIKON_MAKER_NOTE_SOURCE_ID = "nikon.makernote.main"
NIKON_IMAGE_ADJUSTMENT_SOURCE_ID = "nikon.makernote.image_adjustment"
NIKON_TEST3_SOURCE_ID = "nikon.makernote.write_test_3"
NIKON_LENS_TYPE_TAG_SOURCE_ID = "nikon.makernote.lens_type"
NIKON_LENS_DATA_ROUTING_SOURCE_ID = "nikon.makernote.lens_data_routing"
NIKON_LENS_DATA_VERSION_ROUTING_SOURCE_ID = "nikon.makernote.lens_data_version_routing"
NIKON_SERIAL_KEY_SOURCE_ID = "nikon.makernote.serial_key"
NIKON_PROCESS_ENCRYPTED_KEY_SOURCE_ID = "nikon.makernote.process_encrypted_key"
NIKON_PROCESS_EXIF_IFD_SOURCE_ID = "nikon.makernote.process_exif_ifd"
NIKON_PRESCAN_EXIF_SOURCE_ID = "nikon.makernote.prescan_exif"
NIKON_SERIAL_NUMBER_TAG_SOURCE_ID = "nikon.makernote.serial_number"
NIKON_SHUTTER_COUNT_TAG_SOURCE_ID = "nikon.makernote.shutter_count"

NIKON_MAKER_NOTE_SOURCE = NIKON_MAKER_NOTE_SOURCE_ID
NIKON_IMAGE_ADJUSTMENT_SOURCE = NIKON_IMAGE_ADJUSTMENT_SOURCE_ID
NIKON_TEST3_SOURCE = NIKON_TEST3_SOURCE_ID
NIKON_LENS_TYPE_TAG_SOURCE = NIKON_LENS_TYPE_TAG_SOURCE_ID
NIKON_LENS_DATA_ROUTING_SOURCE = NIKON_LENS_DATA_ROUTING_SOURCE_ID
NIKON_LENS_DATA_VERSION_ROUTING_SOURCE = NIKON_LENS_DATA_VERSION_ROUTING_SOURCE_ID
NIKON_SERIAL_KEY_SOURCE = NIKON_SERIAL_KEY_SOURCE_ID
NIKON_PROCESS_ENCRYPTED_KEY_SOURCE = NIKON_PROCESS_ENCRYPTED_KEY_SOURCE_ID
NIKON_PROCESS_EXIF_IFD_SOURCE = NIKON_PROCESS_EXIF_IFD_SOURCE_ID
NIKON_PRESCAN_EXIF_SOURCE = NIKON_PRESCAN_EXIF_SOURCE_ID
NIKON_SERIAL_NUMBER_TAG_SOURCE = NIKON_SERIAL_NUMBER_TAG_SOURCE_ID
NIKON_SHUTTER_COUNT_TAG_SOURCE = NIKON_SHUTTER_COUNT_TAG_SOURCE_ID

NIKON_MAIN_FACT_TAG_NAMES = {
    0x001D: "Nikon:SerialNumber",
    0x0083: "Nikon:LensType",
    0x0098: "Nikon:LensData",
    0x00A7: "Nikon:ShutterCount",
}
NIKON_MAIN_FACT_SUPPORTED_TYPES = {
    0x001D: (TIFF_TYPE_ASCII, TIFF_TYPE_UNDEFINED),
    0x0083: (TIFF_TYPE_BYTE,),
    0x0098: (TIFF_TYPE_UNDEFINED, TIFF_TYPE_BYTE),
    0x00A7: (TIFF_TYPE_LONG,),
}

type NikonMakerNoteRawFactValue = bytes | int | str
type NikonMakerNoteFactParseStatus = Literal[
    "parsed",
    "truncated_ifd_header",
    "truncated_ifd_entry",
    "malformed_entry_type",
    "unsupported_entry_type",
    "oversized_value",
    "external_value_unavailable",
    "external_value_base_adjustment_required",
    "external_value_out_of_buffer",
    "truncated_tag_value",
]
type NikonMakerNoteLensDataRawHandoffStatus = Literal[
    "ready",
    "parse_blocked",
    "handoff_blocked",
]
type NikonMakerNoteSourceLensIdentityRawHandoffStatus = Literal[
    "resolved",
    "unresolved",
    "parse_blocked",
    "fact_emission_blocked",
]


@dataclass(frozen=True)
class NikonMakerNoteReaderPrimitive:
    name: str
    status: Literal["available", "missing"]
    reason: str
    evidence_id: str


@dataclass(frozen=True)
class NikonMakerNoteLensDataBridgeReadinessReport:
    status: Literal["decoded_tag_map_ready", "raw_reader_blocked"]
    decoded_tag_map_bridge_ready: bool
    raw_makernote_reader_ready: bool
    missing_reader_primitives: tuple[NikonMakerNoteReaderPrimitive, ...]
    evidence_ids: tuple[str, ...]
    reason: str

    @property
    def blocked(self) -> bool:
        return self.status == "raw_reader_blocked"


@dataclass(frozen=True)
class NikonMakerNoteRawParseContext:
    data_pos: int = 0
    base: int = 0
    byte_source: NikonMakerNoteByteSource | None = None

    @property
    def data_file_pos(self) -> int:
        return self.data_pos + self.base


@dataclass(frozen=True)
class NikonMakerNoteByteSource:
    """Caller-owned backing bytes for ExifTool RAF-equivalent value reads."""

    data: bytes = b""
    data_pos: int = 0
    description: str = "caller-owned backing byte source"
    range_reader: Callable[[int, int], bytes] | None = None

    def slice_at_file_offset(self, file_offset: int, size: int) -> bytes | None:
        if self.range_reader is not None:
            payload = self.range_reader(file_offset, size)
            return payload if len(payload) == size else None
        source_offset = file_offset - self.data_pos
        if source_offset < 0:
            return None
        source_end = source_offset + size
        if source_end > len(self.data):
            return None
        return self.data[source_offset:source_end]


@dataclass(frozen=True)
class NikonMakerNoteRawFact:
    name: str
    tag_id: int
    raw_value: NikonMakerNoteRawFactValue
    field_type: int
    count: int
    value_offset: int
    evidence_id: str


@dataclass(frozen=True)
class NikonMakerNoteFactParseBlocker:
    status: NikonMakerNoteFactParseStatus
    tag_id: int | None
    reason: str
    evidence_id: str


@dataclass(frozen=True)
class NikonMakerNoteMainIfdFactParseResult:
    status: Literal["parsed", "blocked"]
    facts: tuple[NikonMakerNoteRawFact, ...]
    blockers: tuple[NikonMakerNoteFactParseBlocker, ...]
    evidence_ids: tuple[str, ...]

    @property
    def parsed(self) -> bool:
        return self.status == "parsed"

    def tag_map(self) -> NikonMakerNoteTagMap:
        return {fact.name: fact.raw_value for fact in self.facts}


@dataclass(frozen=True)
class NikonMakerNoteLensDataRawHandoffResult:
    status: NikonMakerNoteLensDataRawHandoffStatus
    parse_context: NikonMakerNoteRawParseContext
    parse_result: NikonMakerNoteMainIfdFactParseResult
    tag_map: NikonMakerNoteTagMap
    lensdata_report: NikonMakerNoteLensDataBridgeReport
    evidence_ids: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def blockers(self) -> tuple[NikonMakerNoteFactParseBlocker, ...]:
        return self.parse_result.blockers


@dataclass(frozen=True)
class NikonMakerNoteSourceLensIdentityRawHandoffResult:
    status: NikonMakerNoteSourceLensIdentityRawHandoffStatus
    raw_handoff: NikonMakerNoteLensDataRawHandoffResult
    source_lens_identity_report: NikonLensDataSourceLensIdentityReport | None
    reason: str
    evidence_ids: tuple[str, ...]

    @property
    def resolved(self) -> bool:
        return (
            self.status == "resolved"
            and self.source_lens_identity_report is not None
            and self.source_lens_identity_report.resolved
        )

    @property
    def blockers(self) -> tuple[NikonMakerNoteFactParseBlocker, ...]:
        return self.raw_handoff.blockers


def build_nikon_image_adjustment_write_plan(value: str) -> InlineMakerNoteStringWritePlan:
    return InlineMakerNoteStringWritePlan((nikon_image_adjustment_write_step(value),))


def nikon_image_adjustment_write_step(value: str) -> InlineMakerNoteStringWriteStep:
    if not value:
        raise ValueError("Nikon ImageAdjustment must not be empty.")
    return InlineMakerNoteStringWriteStep(
        domain="Nikon",
        tag_name="ImageAdjustment",
        tag_id=0x0080,
        value=value,
        encoding="ascii",
        locator=nikon_type3_locator(),
        evidence_ids=(
            NIKON_MAKER_NOTE_SOURCE,
            NIKON_IMAGE_ADJUSTMENT_SOURCE,
            NIKON_TEST3_SOURCE,
        ),
    )


def nikon_type3_locator() -> InlineMakerNoteIfdLocator:
    return InlineMakerNoteIfdLocator(
        maker_note_header=b"",
        ifd_offset_from_maker_note=0,
    )


def nikon_lensdata_runtime_handoff_report_from_decoded_makernote_tags(
    tags: NikonMakerNoteTagMap,
    *,
    already_decoded: bool = False,
    make: str = "NIKON",
    model: str = "",
) -> NikonMakerNoteLensDataBridgeReport:
    """Connect already-decoded Nikon MakerNote facts to the source-backed bridge.

    The package has no raw Nikon MakerNote tag-map reader yet. Callers must
    supply decoded tag IDs/names and raw values from a trusted native reader.
    """

    return nikon_lensdata_runtime_handoff_report_from_makernote_tags(
        tags,
        already_decoded=already_decoded,
        make=make,
        model=model,
    )


def nikon_lensdata_runtime_handoff_report_from_raw_main_ifd(
    data: bytes,
    *,
    byte_order: Endian,
    data_pos: int = 0,
    context: NikonMakerNoteRawParseContext | None = None,
    already_decoded: bool = False,
    make: str = "NIKON",
    model: str = "",
) -> NikonMakerNoteLensDataBridgeReport:
    parsed = parse_nikon_makernote_main_ifd_facts(
        data,
        byte_order=byte_order,
        context=context or NikonMakerNoteRawParseContext(data_pos=data_pos),
    )
    return nikon_lensdata_runtime_handoff_report_from_makernote_tags(
        parsed.tag_map(),
        already_decoded=already_decoded,
        make=make,
        model=model,
    )


def nikon_lensdata_raw_handoff_result_from_main_ifd(
    data: bytes,
    *,
    byte_order: Endian,
    context: NikonMakerNoteRawParseContext | None = None,
    already_decoded: bool = False,
    make: str = "NIKON",
    model: str = "",
) -> NikonMakerNoteLensDataRawHandoffResult:
    parse_context = context or NikonMakerNoteRawParseContext()
    parsed = parse_nikon_makernote_main_ifd_facts(
        data,
        byte_order=byte_order,
        context=parse_context,
    )
    tag_map = parsed.tag_map()
    lensdata_report = nikon_lensdata_runtime_handoff_report_from_makernote_tags(
        tag_map,
        already_decoded=already_decoded,
        make=make,
        model=model,
    )
    if parsed.blockers:
        status: NikonMakerNoteLensDataRawHandoffStatus = "parse_blocked"
    elif lensdata_report.ready:
        status = "ready"
    else:
        status = "handoff_blocked"
    return NikonMakerNoteLensDataRawHandoffResult(
        status=status,
        parse_context=parse_context,
        parse_result=parsed,
        tag_map=tag_map,
        lensdata_report=lensdata_report,
        evidence_ids=(
            *parsed.evidence_ids,
            NIKON_LENS_DATA_VERSION_ROUTING_SOURCE,
            NIKON_SERIAL_KEY_SOURCE,
            NIKON_PROCESS_ENCRYPTED_KEY_SOURCE,
        ),
    )


def resolve_nikon_makernote_source_lens_identity_from_raw_main_ifd(
    repository: SourceLensIdentityRepository,
    data: bytes,
    *,
    byte_order: Endian,
    context: NikonMakerNoteRawParseContext | None = None,
    already_decoded: bool = False,
    make: str = "NIKON",
    model: str = "",
) -> NikonMakerNoteSourceLensIdentityRawHandoffResult:
    """Resolve Nikon source lens identity from caller-owned Main IFD bytes.

    This package-local integration seam consumes the raw facts emitted by
    ``parse_nikon_makernote_main_ifd_facts`` and delegates the LensData request
    to the existing source-lens identity runtime.  It intentionally refuses to
    resolve when the raw parser reports out-of-buffer or base/RAF blockers.
    """

    raw_handoff = nikon_lensdata_raw_handoff_result_from_main_ifd(
        data,
        byte_order=byte_order,
        context=context,
        already_decoded=already_decoded,
        make=make,
        model=model,
    )
    evidence_ids = (
        *raw_handoff.evidence_ids,
        NIKON_PROCESS_EXIF_IFD_SOURCE,
        NIKON_PRESCAN_EXIF_SOURCE,
    )
    if raw_handoff.blockers:
        return NikonMakerNoteSourceLensIdentityRawHandoffResult(
            status="parse_blocked",
            raw_handoff=raw_handoff,
            source_lens_identity_report=None,
            reason=(
                "Nikon source lens identity resolution is blocked because raw "
                "MakerNote Main IFD fact extraction reported unresolved value offsets."
            ),
            evidence_ids=evidence_ids,
        )

    source_report = resolve_nikon_lensdata_source_lens_identity_runtime_from_facts(
        repository,
        raw_handoff.lensdata_report.request,
    )
    return NikonMakerNoteSourceLensIdentityRawHandoffResult(
        status=source_report.status,
        raw_handoff=raw_handoff,
        source_lens_identity_report=source_report,
        reason=source_report.reason,
        evidence_ids=evidence_ids,
    )


def parse_nikon_makernote_main_ifd_facts(
    data: bytes,
    *,
    byte_order: Endian,
    data_pos: int = 0,
    context: NikonMakerNoteRawParseContext | None = None,
) -> NikonMakerNoteMainIfdFactParseResult:
    """Extract Nikon Main IFD raw facts needed by LensData runtime handoff.

    This is intentionally limited to caller-owned MakerNote Main IFD bytes. It
    follows ExifTool's generic EXIF IFD entry shape and in-buffer value pointer
    rule (`stored_offset - DataPos`).  The caller must provide ExifTool-style
    base-relative DataPos when Base is non-zero; this parser reports but does
    not repair file-absolute/base-mixed contexts.
    """

    parse_context = context or NikonMakerNoteRawParseContext(data_pos=data_pos)
    evidence_ids = (
        NIKON_MAKER_NOTE_SOURCE,
        NIKON_PROCESS_EXIF_IFD_SOURCE,
        NIKON_PRESCAN_EXIF_SOURCE,
        NIKON_SERIAL_NUMBER_TAG_SOURCE,
        NIKON_LENS_TYPE_TAG_SOURCE,
        NIKON_LENS_DATA_ROUTING_SOURCE,
        NIKON_SHUTTER_COUNT_TAG_SOURCE,
    )
    if len(data) < 2:
        return NikonMakerNoteMainIfdFactParseResult(
            status="blocked",
            facts=(),
            blockers=(
                NikonMakerNoteFactParseBlocker(
                    status="truncated_ifd_header",
                    tag_id=None,
                    reason="Nikon MakerNote Main IFD is shorter than the 2-byte entry count.",
                    evidence_id=NIKON_PROCESS_EXIF_IFD_SOURCE,
                ),
            ),
            evidence_ids=evidence_ids,
        )

    entry_count = int.from_bytes(data[0:2], byte_order)
    ifd_end = 2 + (entry_count * 12)
    if ifd_end > len(data):
        return NikonMakerNoteMainIfdFactParseResult(
            status="blocked",
            facts=(),
            blockers=(
                NikonMakerNoteFactParseBlocker(
                    status="truncated_ifd_entry",
                    tag_id=None,
                    reason="Nikon MakerNote Main IFD entry table is truncated.",
                    evidence_id=NIKON_PROCESS_EXIF_IFD_SOURCE,
                ),
            ),
            evidence_ids=evidence_ids,
        )

    facts: list[NikonMakerNoteRawFact] = []
    blockers: list[NikonMakerNoteFactParseBlocker] = []
    for index in range(entry_count):
        entry = 2 + (index * 12)
        tag_id = int.from_bytes(data[entry : entry + 2], byte_order)
        if tag_id not in NIKON_MAIN_FACT_TAG_NAMES:
            continue
        field_type = int.from_bytes(data[entry + 2 : entry + 4], byte_order)
        count = int.from_bytes(data[entry + 4 : entry + 8], byte_order)
        value_field = data[entry + 8 : entry + 12]
        if field_type not in NIKON_MAIN_FACT_SUPPORTED_TYPES[tag_id]:
            blockers.append(
                NikonMakerNoteFactParseBlocker(
                    status="unsupported_entry_type"
                    if field_type in _TIFF_FIELD_TYPE_SIZES
                    else "malformed_entry_type",
                    tag_id=tag_id,
                    reason=(
                        f"Nikon Main tag 0x{tag_id:04x} has unsupported TIFF field "
                        f"type {field_type}."
                    ),
                    evidence_id=_nikon_main_fact_evidence_id(tag_id),
                )
            )
            continue
        value_size = _nikon_tiff_value_size(field_type, count)
        if value_size is None:
            blockers.append(
                NikonMakerNoteFactParseBlocker(
                    status="malformed_entry_type",
                    tag_id=tag_id,
                    reason=(
                        f"Nikon Main tag 0x{tag_id:04x} has malformed TIFF field type {field_type}."
                    ),
                    evidence_id=NIKON_PROCESS_EXIF_IFD_SOURCE,
                )
            )
            continue
        if value_size > 0x1000000:
            blockers.append(
                NikonMakerNoteFactParseBlocker(
                    status="oversized_value",
                    tag_id=tag_id,
                    reason=(
                        f"Nikon Main tag 0x{tag_id:04x} value exceeds Nikon PrescanExif 16MB limit."
                    ),
                    evidence_id=NIKON_PRESCAN_EXIF_SOURCE,
                )
            )
            continue
        value_offset = entry + 8
        if value_size <= 4:
            payload = value_field[:value_size]
        else:
            stored_offset = int.from_bytes(value_field, byte_order)
            resolved_value = _resolve_nikon_external_value_payload(
                data,
                stored_offset=stored_offset,
                value_size=value_size,
                context=parse_context,
            )
            value_offset = resolved_value.value_offset
            if resolved_value.payload is None:
                blockers.append(
                    NikonMakerNoteFactParseBlocker(
                        status=resolved_value.status,
                        tag_id=tag_id,
                        reason=(
                            _nikon_external_value_offset_blocker_reason(
                                tag_id=tag_id,
                                status=resolved_value.status,
                                stored_offset=stored_offset,
                                value_size=value_size,
                                context=parse_context,
                            )
                        ),
                        evidence_id=NIKON_PROCESS_EXIF_IFD_SOURCE,
                    )
                )
                continue
            payload = resolved_value.payload
        raw_value = _decode_nikon_main_fact_value(tag_id, field_type, payload, byte_order)
        facts.append(
            NikonMakerNoteRawFact(
                name=NIKON_MAIN_FACT_TAG_NAMES[tag_id],
                tag_id=tag_id,
                raw_value=raw_value,
                field_type=field_type,
                count=count,
                value_offset=value_offset,
                evidence_id=_nikon_main_fact_evidence_id(tag_id),
            )
        )

    return NikonMakerNoteMainIfdFactParseResult(
        status="blocked" if blockers else "parsed",
        facts=tuple(facts),
        blockers=tuple(blockers),
        evidence_ids=evidence_ids,
    )


def nikon_makernote_lensdata_bridge_readiness() -> NikonMakerNoteLensDataBridgeReadinessReport:
    """Report whether Nikon MakerNote facts can feed the LensData bridge."""

    missing_primitives = (
        NikonMakerNoteReaderPrimitive(
            name="nikon_makernote_main_ifd_tag_walker",
            status="available",
            reason=(
                "parse_nikon_makernote_main_ifd_facts walks an in-buffer Nikon "
                "MakerNote Main IFD and emits bounded raw facts for LensData, "
                "LensType, SerialNumber, and ShutterCount."
            ),
            evidence_id=NIKON_PROCESS_EXIF_IFD_SOURCE,
        ),
        NikonMakerNoteReaderPrimitive(
            name="nikon_lensdata_raw_undef_value_reader",
            status="available",
            reason=(
                "The bounded parser extracts in-buffer tag 0x0098 undef/byte payloads "
                "using ExifTool's stored_offset - DataPos pointer rule; RAF/base-backed "
                "external reads remain deferred."
            ),
            evidence_id=NIKON_LENS_DATA_ROUTING_SOURCE,
        ),
        NikonMakerNoteReaderPrimitive(
            name="nikon_lens_type_int8u_reader",
            status="available",
            reason="The bounded parser emits tag 0x0083 LensType as its raw int8u byte.",
            evidence_id=NIKON_LENS_TYPE_TAG_SOURCE,
        ),
        NikonMakerNoteReaderPrimitive(
            name="nikon_serial_and_shutter_prescan_reader",
            status="available",
            reason=(
                "The bounded parser emits raw SerialNumber tag 0x001d and "
                "ShutterCount tag 0x00a7 from the same Main IFD prescan surface."
            ),
            evidence_id=NIKON_PRESCAN_EXIF_SOURCE,
        ),
        NikonMakerNoteReaderPrimitive(
            name="nikon_makernote_raf_base_backed_value_reader",
            status="available",
            reason=(
                "The bounded parser can resolve out-of-buffer value payloads when "
                "the caller supplies NikonMakerNoteByteSource with ExifTool-style "
                "DataPt/DataPos/Base context; shared read_graph wiring remains deferred."
            ),
            evidence_id=NIKON_PROCESS_EXIF_IFD_SOURCE,
        ),
    )
    evidence_ids = (
        NIKON_PROCESS_EXIF_IFD_SOURCE,
        NIKON_PRESCAN_EXIF_SOURCE,
        NIKON_SERIAL_NUMBER_TAG_SOURCE,
        NIKON_LENS_TYPE_TAG_SOURCE,
        NIKON_LENS_DATA_ROUTING_SOURCE,
        NIKON_SHUTTER_COUNT_TAG_SOURCE,
        NIKON_LENS_DATA_VERSION_ROUTING_SOURCE,
        NIKON_SERIAL_KEY_SOURCE,
        NIKON_PROCESS_ENCRYPTED_KEY_SOURCE,
    )
    return NikonMakerNoteLensDataBridgeReadinessReport(
        status="decoded_tag_map_ready",
        decoded_tag_map_bridge_ready=True,
        raw_makernote_reader_ready=True,
        missing_reader_primitives=missing_primitives,
        evidence_ids=evidence_ids,
        reason=(
            "Decoded Nikon tag maps and in-buffer Nikon Main IFD bytes can use the "
            "LensData runtime bridge. Out-of-buffer value payloads can also resolve "
            "from caller-owned backing bytes, but shared read_graph integration must "
            "wire that byte source before public runtime consumes it."
        ),
    )


_TIFF_FIELD_TYPE_SIZES = {
    TIFF_TYPE_BYTE: 1,
    TIFF_TYPE_ASCII: 1,
    TIFF_TYPE_LONG: 4,
    TIFF_TYPE_UNDEFINED: 1,
}


def _nikon_tiff_value_size(field_type: int, count: int) -> int | None:
    unit_size = _TIFF_FIELD_TYPE_SIZES.get(field_type)
    if unit_size is None:
        return None
    return unit_size * count


def _decode_nikon_main_fact_value(
    tag_id: int,
    field_type: int,
    payload: bytes,
    byte_order: Endian,
) -> NikonMakerNoteRawFactValue:
    if tag_id == 0x001D and field_type == TIFF_TYPE_ASCII:
        return payload.rstrip(b"\x00").decode("latin-1")
    if tag_id == 0x0083:
        return payload[0] if payload else 0
    if tag_id == 0x00A7:
        return int.from_bytes(payload[:4], byte_order)
    return payload


def _classify_nikon_external_value_offset_blocker(
    *,
    stored_offset: int,
    value_size: int,
    data_len: int,
    context: NikonMakerNoteRawParseContext,
) -> NikonMakerNoteFactParseStatus:
    base_adjusted_offset = stored_offset + context.base - context.data_pos
    if context.base and base_adjusted_offset >= 0 and base_adjusted_offset + value_size <= data_len:
        return "external_value_base_adjustment_required"
    return "external_value_out_of_buffer"


@dataclass(frozen=True)
class _NikonExternalValueResolution:
    status: NikonMakerNoteFactParseStatus
    payload: bytes | None
    value_offset: int


def _resolve_nikon_external_value_payload(
    data: bytes,
    *,
    stored_offset: int,
    value_size: int,
    context: NikonMakerNoteRawParseContext,
) -> _NikonExternalValueResolution:
    value_offset = stored_offset - context.data_pos
    value_end = value_offset + value_size
    if value_offset >= 0 and value_end <= len(data):
        return _NikonExternalValueResolution(
            status="parsed",
            payload=data[value_offset:value_end],
            value_offset=value_offset,
        )

    file_offset = context.base + stored_offset
    if context.byte_source is not None:
        payload = context.byte_source.slice_at_file_offset(file_offset, value_size)
        if payload is not None:
            return _NikonExternalValueResolution(
                status="parsed",
                payload=payload,
                value_offset=file_offset - context.byte_source.data_pos,
            )
        return _NikonExternalValueResolution(
            status="external_value_unavailable",
            payload=None,
            value_offset=value_offset,
        )

    return _NikonExternalValueResolution(
        status=_classify_nikon_external_value_offset_blocker(
            stored_offset=stored_offset,
            value_size=value_size,
            data_len=len(data),
            context=context,
        ),
        payload=None,
        value_offset=value_offset,
    )


def _nikon_external_value_offset_blocker_reason(
    *,
    tag_id: int,
    status: NikonMakerNoteFactParseStatus,
    stored_offset: int,
    value_size: int,
    context: NikonMakerNoteRawParseContext,
) -> str:
    if status == "external_value_base_adjustment_required":
        return (
            f"Nikon Main tag 0x{tag_id:04x} external value offset 0x{stored_offset:x} "
            "is not resolvable with ExifTool's stored_offset - DataPos rule, but "
            "would be in-buffer if DataPos were treated as file-absolute and adjusted "
            f"by Base 0x{context.base:x}; caller must pass base-relative DataPos."
        )
    if status == "external_value_unavailable":
        source = context.byte_source
        source_label = source.description if source else "no caller-owned backing byte source"
        file_offset = context.base + stored_offset
        return (
            f"Nikon Main tag 0x{tag_id:04x} external value offset 0x{stored_offset:x} "
            f"for {value_size} bytes maps to file offset 0x{file_offset:x}, but "
            f"{source_label} does not own that byte range."
        )
    return (
        f"Nikon Main tag 0x{tag_id:04x} external value offset 0x{stored_offset:x} "
        f"for {value_size} bytes points outside the supplied caller-owned DataPt "
        "buffer after ExifTool-style DataPos resolution; supply NikonMakerNoteByteSource "
        "to enable ExifTool-equivalent RAF/file-backed reads."
    )


def _nikon_main_fact_evidence_id(tag_id: int) -> str:
    if tag_id == 0x001D:
        return NIKON_SERIAL_NUMBER_TAG_SOURCE
    if tag_id == 0x0083:
        return NIKON_LENS_TYPE_TAG_SOURCE
    if tag_id == 0x0098:
        return NIKON_LENS_DATA_ROUTING_SOURCE
    if tag_id == 0x00A7:
        return NIKON_SHUTTER_COUNT_TAG_SOURCE
    return NIKON_PROCESS_EXIF_IFD_SOURCE
