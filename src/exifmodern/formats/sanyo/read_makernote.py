"""Sanyo JPEG MakerNote reader backed by Sanyo.pm Main."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.jpeg.container import (
    read_exif_app1,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
    tiff_long_tag_value,
)
from exifmodern.formats.sanyo.maker_note import render_sanyo_main_tag
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_LONG,
    TIFF_TYPE_RATIONAL,
    TIFF_TYPE_SHORT,
    TIFF_TYPE_UNDEFINED,
    TYPE_SIZES,
    Endian,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
)
from exifmodern.public_interface.unknown import (
    ProcessBinaryDataKnownSpan,
    ProcessBinaryDataUnknownReadResult,
    ProcessBinaryDataUnknownReadTag,
    ProcessBinaryDataUnknownTablePolicy,
    process_binarydata_unknown_tags_from_payload,
)

type SanyoDecodedScalar = int | str | bytes | tuple[int, ...] | tuple[int, int]

SANYO_SOURCE_TABLE = "Image::ExifTool::Sanyo::Main"
SANYO_FACEINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE = "sanyo-faceinfo-process-binarydata-unknown"
SANYO_FACEINFO_PROCESS_BINARYDATA_EVIDENCE_IDS = (
    "sanyo.faceinfo.main_route",
    "sanyo.faceinfo.binary_table",
    "sanyo.faceinfo.unknown_scan",
    "sanyo.faceinfo.tag_prefix",
)
_SANYO_HEADER = b"SANYO\x00\x01\x00"
_SANYO_FACEINFO_TAG = 0x0223
_SANYO_FACEINFO_FIELD_SIZE = 4
type SanyoFaceInfoUnknownReadTag = ProcessBinaryDataUnknownReadTag
type SanyoFaceInfoUnknownReadResult = ProcessBinaryDataUnknownReadResult
_SANYO_RENDERED_TAG_IDS = frozenset(
    {
        0x00FF,
        0x0200,
        0x0201,
        0x0202,
        0x0204,
        0x020E,
        0x020F,
        0x0210,
        0x0213,
        0x0214,
        0x0216,
        0x0217,
        0x0218,
        0x0219,
        0x021B,
        0x021D,
        0x021E,
        0x021F,
        0x0223,
        0x0224,
        0x0225,
    }
)


@dataclass(frozen=True)
class SanyoMakerNoteField:
    name: str
    value: str | int | float
    tag_id: int
    family_2_group: str = "Camera"


@dataclass(frozen=True)
class SanyoMakerNoteReadResult:
    fields: tuple[SanyoMakerNoteField, ...]
    diagnostics: tuple[str, ...]
    source_table: str = SANYO_SOURCE_TABLE


@dataclass(frozen=True)
class SanyoMakerNoteReadContext:
    data: bytes
    maker_ifd: Ifd
    endian: Endian
    maker_ifd_offset: int


def read_sanyo_maker_note_from_jpeg(path: Path) -> SanyoMakerNoteReadResult:
    context = _sanyo_maker_note_context_from_jpeg(path)
    if isinstance(context, SanyoMakerNoteReadResult):
        return context
    fields = _read_sanyo_fields(
        context.data,
        context.maker_ifd,
        context.endian,
        context.maker_ifd_offset,
    )
    return SanyoMakerNoteReadResult(
        fields,
        (
            "Sanyo MakerNote bridge ready: SANYO inline IFD routed through "
            "Image::ExifTool::Sanyo::Main render_sanyo_main_tag.",
            "Sanyo MakerNote blocked: SanyoThumbnail, PrintIM, and DataDump "
            "subdirectory/binary payloads remain unported.",
        ),
    )


def collect_sanyo_faceinfo_process_binary_unknown_read_tags(
    path: Path,
) -> SanyoFaceInfoUnknownReadResult:
    context = _sanyo_maker_note_context_from_jpeg(path)
    if isinstance(context, SanyoMakerNoteReadResult):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=tuple(
                diagnostic.replace(
                    "Sanyo MakerNote blocked",
                    "Sanyo FaceInfo ProcessBinaryData unknown discovery blocked",
                )
                for diagnostic in context.diagnostics
            ),
            evidence_ids=SANYO_FACEINFO_PROCESS_BINARYDATA_EVIDENCE_IDS,
        )
    logical_value_offset = context.maker_ifd_offset + 2 + len(context.maker_ifd.entries) * 12 + 4
    for entry in context.maker_ifd.entries:
        payload = _entry_payload(context.data, entry, context.endian, logical_value_offset)
        logical_value_offset = _next_logical_value_offset(entry, logical_value_offset)
        if entry.tag_id != _SANYO_FACEINFO_TAG or payload is None:
            continue
        if entry.field_type == TIFF_TYPE_RATIONAL:
            return ProcessBinaryDataUnknownReadResult(
                tags=(),
                diagnostics=(
                    "Sanyo FaceInfo ProcessBinaryData unknown discovery blocked: "
                    "tag 0x0223 selected ManualFocusDistance rational64u branch.",
                ),
                evidence_ids=SANYO_FACEINFO_PROCESS_BINARYDATA_EVIDENCE_IDS,
            )
        result = process_binarydata_unknown_tags_from_payload(
            payload,
            _sanyo_faceinfo_unknown_policy(context.endian),
        )
        return ProcessBinaryDataUnknownReadResult(
            tags=result.tags,
            diagnostics=tuple(
                diagnostic.replace(
                    "ProcessBinaryData unknown discovery",
                    "Sanyo FaceInfo ProcessBinaryData unknown discovery",
                )
                for diagnostic in result.diagnostics
            ),
            evidence_ids=result.evidence_ids,
        )
    return ProcessBinaryDataUnknownReadResult(
        tags=(),
        diagnostics=(
            "Sanyo FaceInfo ProcessBinaryData unknown discovery blocked: "
            "missing FaceInfo tag 0x0223.",
        ),
        evidence_ids=SANYO_FACEINFO_PROCESS_BINARYDATA_EVIDENCE_IDS,
    )


def _sanyo_maker_note_context_from_jpeg(
    path: Path,
) -> SanyoMakerNoteReadContext | SanyoMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    if make is None or "SANYO" not in make.upper():
        return SanyoMakerNoteReadResult((), ())
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return SanyoMakerNoteReadResult((), ("Sanyo MakerNote blocked: missing ExifIFD.",))
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return SanyoMakerNoteReadResult((), ())
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return SanyoMakerNoteReadResult((), ("Sanyo MakerNote blocked: raw value is truncated.",))
    maker_note_offset, raw_maker_note = raw_location
    if not raw_maker_note.startswith(_SANYO_HEADER):
        return SanyoMakerNoteReadResult(
            (), ("Sanyo MakerNote blocked: missing SANYO inline IFD header.",)
        )
    maker_ifd_offset = maker_note_offset + len(_SANYO_HEADER)
    try:
        maker_ifd = parse_ifd(exif.tiff_data, maker_ifd_offset, header.endian)
    except ValueError as exc:
        return SanyoMakerNoteReadResult((), (f"Sanyo MakerNote blocked: {exc}",))
    return SanyoMakerNoteReadContext(
        data=exif.tiff_data,
        maker_ifd=maker_ifd,
        endian=header.endian,
        maker_ifd_offset=maker_ifd_offset,
    )


def _read_sanyo_fields(
    data: bytes,
    maker_ifd: Ifd,
    endian: Endian,
    maker_ifd_offset: int,
) -> tuple[SanyoMakerNoteField, ...]:
    fields: list[SanyoMakerNoteField] = []
    logical_value_offset = maker_ifd_offset + 2 + len(maker_ifd.entries) * 12 + 4
    for entry in maker_ifd.entries:
        payload = _entry_payload(data, entry, endian, logical_value_offset)
        logical_value_offset = _next_logical_value_offset(entry, logical_value_offset)
        if entry.tag_id not in _SANYO_RENDERED_TAG_IDS or payload is None:
            continue
        raw_value = _decode_sanyo_payload(payload, entry, endian)
        if raw_value is None:
            continue
        rendered = render_sanyo_main_tag(entry.tag_id, raw_value)
        fields.append(
            SanyoMakerNoteField(
                rendered.tag_name,
                _graph_value(rendered.rendered_value),
                entry.tag_id,
            )
        )
    return tuple(fields)


def _sanyo_faceinfo_unknown_policy(endian: Endian) -> ProcessBinaryDataUnknownTablePolicy:
    return ProcessBinaryDataUnknownTablePolicy(
        tag_prefix="Sanyo_FaceInfo",
        first_entry=0,
        increment=_SANYO_FACEINFO_FIELD_SIZE,
        known_spans=(
            ProcessBinaryDataKnownSpan(start_index=0, entry_count=1),
            ProcessBinaryDataKnownSpan(start_index=4, entry_count=4),
        ),
        evidence_ids=SANYO_FACEINFO_PROCESS_BINARYDATA_EVIDENCE_IDS,
        byte_order=endian,
    )


def _entry_payload(
    data: bytes,
    entry: IfdEntry,
    endian: Endian,
    logical_value_offset: int,
) -> bytes | None:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        return None
    byte_count = field_size * entry.count
    if byte_count <= 4:
        return entry.value_offset.to_bytes(4, endian)[:byte_count]
    candidates = (entry.value_offset, logical_value_offset)
    for start in candidates:
        end = start + byte_count
        if start >= 0 and end <= len(data):
            return data[start:end]
    return None


def _next_logical_value_offset(entry: IfdEntry, logical_value_offset: int) -> int:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        return logical_value_offset
    byte_count = field_size * entry.count
    if byte_count <= 4 or entry.tag_id == 0x0100:
        return logical_value_offset
    next_offset = logical_value_offset + byte_count
    if byte_count % 2:
        next_offset += 1
    return next_offset


def _decode_sanyo_payload(
    payload: bytes,
    entry: IfdEntry,
    endian: Endian,
) -> SanyoDecodedScalar | None:
    if entry.field_type == TIFF_TYPE_ASCII:
        return payload.rstrip(b"\x00").decode("latin-1", errors="replace")
    if entry.field_type == TIFF_TYPE_UNDEFINED:
        return payload
    if entry.field_type == TIFF_TYPE_SHORT:
        values = tuple(
            int.from_bytes(payload[index * 2 : index * 2 + 2], endian)
            for index in range(entry.count)
        )
        return values[0] if entry.count == 1 else values
    if entry.field_type == TIFF_TYPE_LONG:
        values = tuple(
            int.from_bytes(payload[index * 4 : index * 4 + 4], endian)
            for index in range(entry.count)
        )
        return values[0] if entry.count == 1 else values
    if entry.field_type == TIFF_TYPE_RATIONAL:
        if entry.count != 1:
            return None
        return (
            int.from_bytes(payload[:4], endian),
            int.from_bytes(payload[4:8], endian),
        )
    return None


def _graph_value(value: int | float | str | tuple[int, ...]) -> str | int | float:
    if isinstance(value, tuple):
        return " ".join(str(item) for item in value)
    return value
