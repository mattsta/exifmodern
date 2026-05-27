"""Sony MakerNote reader slice backed by MakerNotes.pm and Sony.pm."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.jpeg.container import (
    exiftool_binary_summary,
    read_exif_app1,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
    tiff_long_tag_value,
)
from exifmodern.formats.maker_notes import render_maker_note_package_print_value
from exifmodern.formats.maker_notes.context import MakerNoteRuntimeContext, maker_note_self_context
from exifmodern.formats.tiff.primitives import (
    Endian,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)
from exifmodern.public_interface.unknown import (
    ProcessBinaryDataKnownSpan,
    ProcessBinaryDataUnknownReadResult,
    ProcessBinaryDataUnknownReadTag,
    ProcessBinaryDataUnknownTablePolicy,
    UnknownReadBlocker,
    process_binarydata_unknown_tags_from_payload,
)


@dataclass(frozen=True)
class SonyMakerNoteField:
    name: str
    value: str | int
    tag_id: int
    family_2_group: str = "Camera"


@dataclass(frozen=True)
class SonyMakerNoteReadResult:
    fields: tuple[SonyMakerNoteField, ...]
    diagnostics: tuple[str, ...]


SONY_SOURCE_TABLE = "Image::ExifTool::Sony::Main"
SONY_CAMERAINFO_UNKNOWN_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "sony-camerainfounknown-process-binarydata-unknown"
)
SONY_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "sony-camerasettingsunknown-process-binarydata-unknown"
)
SONY_MOREINFO_DYNAMIC_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "sony-moreinfo-dynamic-process-binarydata-unknown"
)
SONY_MOREINFO0201_PROCESS_BINARYDATA_UNKNOWN_SOURCE = "sony-moreinfo0201-process-binarydata-unknown"
SONY_MOREINFO0401_PROCESS_BINARYDATA_UNKNOWN_SOURCE = "sony-moreinfo0401-process-binarydata-unknown"
SONY_CAMERAINFO_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "sony.read.camerainfo_unknown_route",
    "sony.read.binarydata_attrs",
    "sony.read.camerainfo_unknown_table",
)
SONY_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "sony.read.camera_settings_unknown_route",
    "sony.read.camera_settings_unknown_table",
    "sony.read.camera_settings_unknown_synthesis",
)
SONY_MOREINFO_DYNAMIC_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "sony.read.moreinfo_route",
    "sony.read.moreinfo_known_blocks",
    "sony.read.moreinfo_dynamic_table_creation",
)
SONY_MOREINFO_KNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "sony.read.moreinfo_route",
    "sony.read.moreinfo_known_subdirectories",
    "sony.read.moreinfo0201_table",
    "sony.read.moreinfo0401_table",
    "sony.read.moreinfo_known_unknown_synthesis",
)
SONY_MOREINFO_KNOWN_BLOCK_IDS = (0x0001, 0x0002, 0x0107, 0x0201, 0x0401)
SONY_MOREINFO_IMPLEMENTED_KNOWN_BLOCK_IDS = (0x0201, 0x0401)
SONY_TABLE_LOCAL_BLOCKERS = (
    UnknownReadBlocker(
        code="sony_enciphered_process_binarydata_blocked",
        message=(
            "Sony encrypted ProcessBinaryData unknown discovery blocked: ProcessEnciphered "
            "tables require model/key-specific deciphering before scalar fanout."
        ),
        evidence_ids=("sony.read.enciphered_process_binarydata",),
    ),
    UnknownReadBlocker(
        code="sony_moreinfo_known_block_subdirectory_blocked",
        message=(
            "Sony MoreInfo known-block subdirectory extraction remains blocked: "
            "ProcessMoreInfo routes source-declared block IDs into nested tables "
            "with their own conditions and binary conversion behavior."
        ),
        evidence_ids=("sony.read.moreinfo_subdirectory_dispatch",),
    ),
    UnknownReadBlocker(
        code="sony_moreinfo_moresettings_conditions_blocked",
        message=(
            "Sony MoreInfo block 0x0001 MoreSettings unknown discovery remains "
            "terminal: source-declared entries use model Conditions, signed formats, "
            "ValueConv, and PrintConv state rather than safe scalar unknown fanout."
        ),
        evidence_ids=("sony.read.moreinfo_moresettings_conditions",),
    ),
    UnknownReadBlocker(
        code="sony_moreinfo_faceinfo_datamember_blocked",
        message=(
            "Sony MoreInfo block 0x0002 FaceInfo unknown discovery remains terminal: "
            "FaceInfo and FaceInfoA depend on DATAMEMBER face counts and hidden "
            "stateful Conditions before offsets can be interpreted."
        ),
        evidence_ids=("sony.read.moreinfo_faceinfo_datamember",),
    ),
    UnknownReadBlocker(
        code="sony_moreinfo_tiffmeteringimage_binary_conversion_blocked",
        message=(
            "Sony MoreInfo block 0x0107 TiffMeteringImage remains terminal for "
            "public unknown scalar fanout: the source treats it as a binary TIFF "
            "conversion surface gated by binary extraction policy."
        ),
        evidence_ids=("sony.read.moreinfo_tiffmeteringimage_binary",),
    ),
    UnknownReadBlocker(
        code="sony_hidden_trailer_payload_blocked",
        message=(
            "Sony HiddenData trailer payloads remain terminal for default public "
            "runtime surfacing: source parsing seeks trailer offsets and lengths "
            "before routing nested hidden data."
        ),
        evidence_ids=("sony.read.hidden_trailer_payload",),
    ),
)
type SonyProcessBinaryUnknownReadTag = ProcessBinaryDataUnknownReadTag
type SonyProcessBinaryUnknownReadResult = ProcessBinaryDataUnknownReadResult
_SONY_CAMERAINFO_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Sony_CameraInfoUnknown",
    first_entry=0,
    increment=1,
    known_spans=(),
    evidence_ids=SONY_CAMERAINFO_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_SONY_CAMERA_SETTINGS_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Sony_CameraSettingsUnknown",
    first_entry=0,
    increment=2,
    known_spans=(),
    evidence_ids=SONY_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_SONY_MOREINFO0201_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="MoreInfo0201",
    first_entry=0,
    increment=1,
    known_spans=(
        ProcessBinaryDataKnownSpan(start_index=0x011B, entry_count=4),
        ProcessBinaryDataKnownSpan(start_index=0x0125, entry_count=4),
        ProcessBinaryDataKnownSpan(start_index=0x014A, entry_count=4),
    ),
    evidence_ids=SONY_MOREINFO_KNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    byte_order="little",
)
_SONY_MOREINFO0401_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="MoreInfo0401",
    first_entry=0,
    increment=1,
    known_spans=(ProcessBinaryDataKnownSpan(start_index=0x044E, entry_count=4),),
    evidence_ids=SONY_MOREINFO_KNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    byte_order="little",
)
_TAG_NAMES = {
    0x201B: "FocusMode",
    0xB001: "SonyModelID",
    0xB020: "CreativeStyle",
    0xB040: "Macro",
}


def read_sony_maker_note_from_jpeg(path: Path) -> SonyMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    model = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x0110, header.endian)
    if make is None or not make.startswith("SONY"):
        return SonyMakerNoteReadResult((), ())
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return SonyMakerNoteReadResult((), ("Sony MakerNote blocked: missing ExifIFD.",))
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return SonyMakerNoteReadResult((), ())
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return SonyMakerNoteReadResult((), ("Sony MakerNote blocked: truncated value.",))
    maker_offset, raw_maker_note = raw_location
    if not raw_maker_note.startswith((b"SONY DSC \x00", b"SONY CAM \x00")):
        return SonyMakerNoteReadResult((), ())
    try:
        maker_ifd = parse_ifd(exif.tiff_data, maker_offset + 12, header.endian)
    except ValueError as exc:
        return SonyMakerNoteReadResult((), (f"Sony MakerNote blocked: {exc}",))
    fields: list[SonyMakerNoteField] = []
    context = _runtime_context(make, model)
    top_level_printim = _printim_version_from_block(exif.tiff_data)
    if top_level_printim is not None:
        fields.append(SonyMakerNoteField("PrintIMVersion", top_level_printim, 0xC4A5))
    for entry in maker_ifd.entries:
        if entry.tag_id == 0x0E00:
            printim_version = _printim_version(exif.tiff_data, entry, header.endian)
            if printim_version is not None:
                fields.append(SonyMakerNoteField("PrintIMVersion", printim_version, entry.tag_id))
            continue
        if entry.tag_id in _TAG_NAMES or entry.tag_id == 0x2000 or 0x9001 <= entry.tag_id <= 0x9008:
            fields.append(_field(exif.tiff_data, entry, header.endian, context))
    return SonyMakerNoteReadResult(
        tuple(fields),
        (
            "Sony MakerNote bridge ready: MakerNotes.pm MakerNoteSony matched "
            "SONY DSC/CAM header and used Start=$valuePtr+12 for Sony.pm Main.",
            "Sony MakerNote blocked: encrypted/opaque Sony 0x9001-0x9008 binary "
            "tables remain unported; emitted only source-table unknown payload summaries.",
        ),
    )


def collect_sony_camerainfo_unknown_process_binary_unknown_read_tags(
    path: Path,
) -> SonyProcessBinaryUnknownReadResult:
    return _collect_sony_binary_unknown_read_tags(
        path,
        maker_note_tag_id=0x0010,
        policy=_SONY_CAMERAINFO_UNKNOWN_POLICY,
        evidence_ids=SONY_CAMERAINFO_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        diagnostic_prefix="Sony CameraInfoUnknown",
        blocked_counts=(368, 5478, 5506, 6118, 15360),
    )


def collect_sony_camerasettings_unknown_process_binary_unknown_read_tags(
    path: Path,
) -> SonyProcessBinaryUnknownReadResult:
    return _collect_sony_binary_unknown_read_tags(
        path,
        maker_note_tag_id=0x0114,
        policy=_SONY_CAMERA_SETTINGS_UNKNOWN_POLICY,
        evidence_ids=SONY_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        diagnostic_prefix="Sony CameraSettingsUnknown",
        blocked_counts=(280, 332, 364, 1536, 2048),
    )


def collect_sony_moreinfo_dynamic_process_binary_unknown_read_tags(
    path: Path,
) -> SonyProcessBinaryUnknownReadResult:
    try:
        maker_ifd, raw, endian = _sony_maker_ifd_and_tiff_data(path)
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(f"Sony MoreInfo dynamic unknown discovery blocked: {exc}",),
            evidence_ids=SONY_MOREINFO_DYNAMIC_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    entry = next((candidate for candidate in maker_ifd.entries if candidate.tag_id == 0x0020), None)
    if entry is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=SONY_MOREINFO_DYNAMIC_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    payload = read_entry_value(raw, entry, endian)
    if not isinstance(payload, bytes):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                "Sony MoreInfo dynamic unknown discovery blocked: payload is not byte data.",
            ),
            evidence_ids=SONY_MOREINFO_DYNAMIC_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    return collect_sony_moreinfo_dynamic_process_binary_unknown_read_tags_from_payload(payload)


def collect_sony_moreinfo0201_process_binary_unknown_read_tags(
    path: Path,
) -> SonyProcessBinaryUnknownReadResult:
    return _collect_sony_moreinfo_known_process_binary_unknown_read_tags(
        path,
        block_id=0x0201,
        policy=_SONY_MOREINFO0201_POLICY,
        diagnostic_prefix="Sony MoreInfo0201",
    )


def collect_sony_moreinfo0401_process_binary_unknown_read_tags(
    path: Path,
) -> SonyProcessBinaryUnknownReadResult:
    return _collect_sony_moreinfo_known_process_binary_unknown_read_tags(
        path,
        block_id=0x0401,
        policy=_SONY_MOREINFO0401_POLICY,
        diagnostic_prefix="Sony MoreInfo0401",
    )


def collect_sony_moreinfo0201_process_binary_unknown_read_tags_from_payload(
    payload: bytes,
) -> SonyProcessBinaryUnknownReadResult:
    return _collect_sony_moreinfo_known_process_binary_unknown_read_tags_from_payload(
        payload,
        block_id=0x0201,
        policy=_SONY_MOREINFO0201_POLICY,
        diagnostic_prefix="Sony MoreInfo0201",
    )


def collect_sony_moreinfo0401_process_binary_unknown_read_tags_from_payload(
    payload: bytes,
) -> SonyProcessBinaryUnknownReadResult:
    return _collect_sony_moreinfo_known_process_binary_unknown_read_tags_from_payload(
        payload,
        block_id=0x0401,
        policy=_SONY_MOREINFO0401_POLICY,
        diagnostic_prefix="Sony MoreInfo0401",
    )


def collect_sony_moreinfo_dynamic_process_binary_unknown_read_tags_from_payload(
    payload: bytes,
) -> SonyProcessBinaryUnknownReadResult:
    parsed = _parse_sony_moreinfo_payload(payload)
    if isinstance(parsed, ProcessBinaryDataUnknownReadResult):
        return parsed
    block_refs, block_sizes, diagnostics = parsed
    tags: list[ProcessBinaryDataUnknownReadTag] = []
    for block_ref in block_refs:
        if block_ref.offset > len(payload) or block_ref.tag_id in SONY_MOREINFO_KNOWN_BLOCK_IDS:
            continue
        block_size = block_sizes.get(block_ref.offset)
        if block_size is None or block_size <= 0:
            continue
        policy = ProcessBinaryDataUnknownTablePolicy(
            tag_prefix=f"MoreInfo{block_ref.tag_id:04x}",
            first_entry=0,
            increment=1,
            known_spans=(),
            evidence_ids=SONY_MOREINFO_DYNAMIC_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
            byte_order="little",
        )
        block_payload = payload[block_ref.offset : block_ref.offset + block_size]
        block_result = process_binarydata_unknown_tags_from_payload(block_payload, policy)
        diagnostics.extend(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                f"Sony MoreInfo{block_ref.tag_id:04x} dynamic unknown discovery",
            )
            for diagnostic in block_result.diagnostics
        )
        tags.extend(block_result.tags)

    return ProcessBinaryDataUnknownReadResult(
        tags=tuple(tags),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        evidence_ids=SONY_MOREINFO_DYNAMIC_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def _collect_sony_moreinfo_known_process_binary_unknown_read_tags(
    path: Path,
    *,
    block_id: int,
    policy: ProcessBinaryDataUnknownTablePolicy,
    diagnostic_prefix: str,
) -> SonyProcessBinaryUnknownReadResult:
    try:
        maker_ifd, raw, endian = _sony_maker_ifd_and_tiff_data(path)
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked: {exc}",
            ),
            evidence_ids=SONY_MOREINFO_KNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    entry = next((candidate for candidate in maker_ifd.entries if candidate.tag_id == 0x0020), None)
    if entry is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=SONY_MOREINFO_KNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    payload = read_entry_value(raw, entry, endian)
    if not isinstance(payload, bytes):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked: "
                "payload is not byte data.",
            ),
            evidence_ids=SONY_MOREINFO_KNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    return _collect_sony_moreinfo_known_process_binary_unknown_read_tags_from_payload(
        payload,
        block_id=block_id,
        policy=policy,
        diagnostic_prefix=diagnostic_prefix,
    )


def _collect_sony_moreinfo_known_process_binary_unknown_read_tags_from_payload(
    payload: bytes,
    *,
    block_id: int,
    policy: ProcessBinaryDataUnknownTablePolicy,
    diagnostic_prefix: str,
) -> SonyProcessBinaryUnknownReadResult:
    parsed = _parse_sony_moreinfo_payload(payload)
    if isinstance(parsed, ProcessBinaryDataUnknownReadResult):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=tuple(
                diagnostic.replace(
                    "Sony MoreInfo dynamic unknown discovery",
                    f"{diagnostic_prefix} ProcessBinaryData unknown discovery",
                )
                for diagnostic in parsed.diagnostics
            ),
            evidence_ids=SONY_MOREINFO_KNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    block_refs, block_sizes, diagnostics = parsed
    tags: list[ProcessBinaryDataUnknownReadTag] = []
    for block_ref in block_refs:
        if block_ref.tag_id != block_id or block_ref.offset > len(payload):
            continue
        block_size = block_sizes.get(block_ref.offset)
        if block_size is None or block_size <= 0:
            continue
        block_payload = payload[block_ref.offset : block_ref.offset + block_size]
        block_result = process_binarydata_unknown_tags_from_payload(block_payload, policy)
        diagnostics.extend(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery",
            )
            for diagnostic in block_result.diagnostics
        )
        tags.extend(block_result.tags)
    return ProcessBinaryDataUnknownReadResult(
        tags=tuple(tags),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        evidence_ids=SONY_MOREINFO_KNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def _parse_sony_moreinfo_payload(
    payload: bytes,
) -> (
    tuple[list[SonyMoreInfoBlockRef], dict[int, int], list[str]]
    | SonyProcessBinaryUnknownReadResult
):
    if len(payload) < 4:
        return _sony_moreinfo_blocked("Truncated MoreInfo data")
    entry_count = int.from_bytes(payload[0:2], "little")
    declared_length = int.from_bytes(payload[2:4], "little")
    if len(payload) < 4 + entry_count * 4:
        return _sony_moreinfo_blocked("Truncated MoreInfo data")
    if entry_count > 50:
        return _sony_moreinfo_blocked("Possibly corrupted MoreInfo data")

    effective_length = declared_length
    diagnostics: list[str] = []
    if effective_length > len(payload):
        diagnostics.append(
            "Sony MoreInfo dynamic unknown discovery adjusted oversized MoreInfo data length."
        )
        effective_length = len(payload)

    block_refs: list[SonyMoreInfoBlockRef] = []
    for index in range(entry_count):
        entry_offset = 4 + index * 4
        tag_id = int.from_bytes(payload[entry_offset : entry_offset + 2], "little")
        block_offset = int.from_bytes(payload[entry_offset + 2 : entry_offset + 4], "little")
        if block_offset > effective_length and block_offset <= len(payload):
            diagnostics.append(
                "Sony MoreInfo dynamic unknown discovery adjusted undersized MoreInfo data length."
            )
            effective_length = len(payload)
        block_refs.append(SonyMoreInfoBlockRef(tag_id=tag_id, offset=block_offset))

    block_sizes = _sony_moreinfo_block_sizes(block_refs, effective_length)
    return block_refs, block_sizes, diagnostics


@dataclass(frozen=True)
class SonyMoreInfoBlockRef:
    tag_id: int
    offset: int


def _sony_moreinfo_block_sizes(
    block_refs: list[SonyMoreInfoBlockRef],
    effective_length: int,
) -> dict[int, int]:
    sorted_offsets = sorted(block_ref.offset for block_ref in block_refs)
    sorted_offsets.append(0xFFFF)
    block_sizes: dict[int, int] = {}
    for index, offset in enumerate(sorted_offsets[:-1]):
        size = sorted_offsets[index + 1] - offset
        remaining_size = effective_length - offset
        if size > remaining_size:
            size = remaining_size
        if offset not in block_sizes:
            block_sizes[offset] = size
    return block_sizes


def _sony_moreinfo_blocked(message: str) -> SonyProcessBinaryUnknownReadResult:
    return ProcessBinaryDataUnknownReadResult(
        tags=(),
        diagnostics=(f"Sony MoreInfo dynamic unknown discovery blocked: {message}.",),
        evidence_ids=SONY_MOREINFO_DYNAMIC_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def _field(
    raw: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    runtime_context: MakerNoteRuntimeContext | None = None,
) -> SonyMakerNoteField:
    context = runtime_context or _runtime_context(None, None)
    name = _TAG_NAMES.get(entry.tag_id, f"Sony0x{entry.tag_id:04x}")
    value = read_entry_value(raw, entry, byte_order)
    if entry.tag_id in _TAG_NAMES and isinstance(value, int):
        rendered: str | int = _package_print(name, value, entry.tag_id, context) or value
    elif entry.tag_id in _TAG_NAMES and isinstance(value, str):
        text = value.rstrip("\x00")
        rendered = _package_print(name, text, entry.tag_id, context) or text
    elif entry.tag_id == 0x2000 and isinstance(value, bytes) and len(value) == 1:
        rendered = value[0]
    elif isinstance(value, bytes):
        rendered = exiftool_binary_summary(entry.count)
    else:
        rendered = value if isinstance(value, int) else str(value)
    return SonyMakerNoteField(name, rendered, entry.tag_id)


def _collect_sony_binary_unknown_read_tags(
    path: Path,
    *,
    maker_note_tag_id: int,
    policy: ProcessBinaryDataUnknownTablePolicy,
    evidence_ids: tuple[str, ...],
    diagnostic_prefix: str,
    blocked_counts: tuple[int, ...],
) -> SonyProcessBinaryUnknownReadResult:
    try:
        maker_ifd, raw, endian = _sony_maker_ifd_and_tiff_data(path)
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked: {exc}",
            ),
            evidence_ids=evidence_ids,
        )
    entry = next(
        (candidate for candidate in maker_ifd.entries if candidate.tag_id == maker_note_tag_id),
        None,
    )
    if entry is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=evidence_ids,
        )
    if entry.count in blocked_counts:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=evidence_ids,
        )
    payload = read_entry_value(raw, entry, endian)
    if not isinstance(payload, bytes):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked: "
                "subdirectory payload is not byte data.",
            ),
            evidence_ids=evidence_ids,
        )
    result = process_binarydata_unknown_tags_from_payload(payload, policy)
    return ProcessBinaryDataUnknownReadResult(
        tags=result.tags,
        diagnostics=tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        evidence_ids=evidence_ids,
    )


def _sony_maker_ifd_and_tiff_data(path: Path) -> tuple[Ifd, bytes, Endian]:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    if make is None or not make.startswith("SONY"):
        raise ValueError("IFD0 Make did not select Sony.")
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        raise ValueError("missing ExifIFD.")
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        raise ValueError("missing tag 0x927c.")
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        raise ValueError("truncated value.")
    maker_offset, raw_maker_note = raw_location
    if not raw_maker_note.startswith((b"SONY DSC \x00", b"SONY CAM \x00")):
        raise ValueError("missing SONY DSC/CAM header.")
    return (
        parse_ifd(exif.tiff_data, maker_offset + 12, header.endian),
        exif.tiff_data,
        header.endian,
    )


def _runtime_context(make: str | None, model: str | None) -> MakerNoteRuntimeContext:
    return MakerNoteRuntimeContext(
        values=(
            maker_note_self_context(("Make",), make or ""),
            maker_note_self_context(("Model",), model or ""),
        )
    )


def _package_print(
    tag_name: str,
    raw_value: int | str,
    tag_id: int,
    runtime_context: MakerNoteRuntimeContext,
) -> str | None:
    return render_maker_note_package_print_value(
        module="Image::ExifTool::Sony",
        table="Main",
        tag_name=tag_name,
        raw_value=raw_value,
        tag_id=tag_id,
        runtime_context=runtime_context,
    )


def _printim_version(raw: bytes, entry: IfdEntry, byte_order: Endian) -> str | None:
    value = read_entry_value(raw, entry, byte_order)
    if not isinstance(value, bytes):
        return None
    return _printim_version_from_block(value)


def _printim_version_from_block(value: bytes) -> str | None:
    offset = value.find(b"PrintIM\x00")
    if offset < 0 or offset + 12 > len(value):
        return None
    return value[offset + 8 : offset + 12].decode("ascii", errors="replace")
