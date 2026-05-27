"""Samsung STMN MakerNote reader slice backed by ExifTool Samsung.pm."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.jpeg.container import (
    read_exif_app1,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
    tiff_long_tag_value,
)
from exifmodern.formats.tiff.primitives import parse_ifd, parse_tiff_header
from exifmodern.public_interface.unknown import (
    ProcessBinaryDataKnownSpan,
    ProcessBinaryDataUnknownReadResult,
    ProcessBinaryDataUnknownReadTag,
    ProcessBinaryDataUnknownTablePolicy,
    UnknownReadBlocker,
    process_binarydata_unknown_tags_from_payload,
)


@dataclass(frozen=True)
class SamsungMakerNoteField:
    name: str
    value: str | int
    tag_id: int
    family_2_group: str = "Image"


@dataclass(frozen=True)
class SamsungMakerNoteReadResult:
    fields: tuple[SamsungMakerNoteField, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class SamsungStmnPayload:
    payload: bytes
    conditional_subdirectory_present: bool


SAMSUNG_SOURCE_TABLE = "Image::ExifTool::Samsung::Main"
SAMSUNG_STMN_PROCESS_BINARYDATA_UNKNOWN_SOURCE = "samsung-stmn-process-binarydata-unknown"
SAMSUNG_STMN_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "samsung.read.stmn_route",
    "samsung.read.stmn_binarydata_policy",
    "samsung.read.stmn_known_layout",
    "samsung.read.stmn_unknown_scan",
)
SAMSUNG_STMN_TABLE_LOCAL_BLOCKERS = (
    UnknownReadBlocker(
        code="samsung_stmn_conditional_subdirectory_blocked",
        message=(
            "Samsung STMN conditional SamsungIFD subdirectory bytes are recognized and "
            "skipped, but nested ProcessSamsungIFD extraction remains unported."
        ),
        evidence_ids=("samsung.read.stmn_conditional_subdirectory",),
    ),
    UnknownReadBlocker(
        code="samsung_type2_encrypted_hidden_blocked",
        message=(
            "Samsung Type2 encrypted Unknown/Hidden ProcessBinaryData fields remain "
            "terminal for public unknown scalar fanout until Samsung::Crypt "
            "table-local RawConv state is represented."
        ),
        evidence_ids=("samsung.read.type2_encrypted_hidden",),
    ),
    UnknownReadBlocker(
        code="samsung_dualshot_hook_blocked",
        message=(
            "Samsung DualShotExtra ProcessBinaryData remains terminal for generic "
            "unknown fanout because tag positions are moved by a Hook over payload bytes."
        ),
        evidence_ids=("samsung.read.dualshot_hook",),
    ),
)
type SamsungStmnUnknownReadTag = ProcessBinaryDataUnknownReadTag
type SamsungStmnUnknownReadResult = ProcessBinaryDataUnknownReadResult
_MAKER_NOTE_TAG = 0x927C
_SAMSUNG_STMN_FIELD_SIZE = 4
_SAMSUNG_STMN_CONDITIONAL_SUBDIRECTORY_INDEX = 11
_SAMSUNG_STMN_CONDITIONAL_SUBDIRECTORY_OFFSET = 44


def read_samsung_maker_note_from_jpeg(path: Path) -> SamsungMakerNoteReadResult:
    payload_result = _samsung_stmn_payload_from_jpeg(path)
    if isinstance(payload_result, SamsungMakerNoteReadResult):
        return payload_result
    payload = payload_result.payload
    fields = [
        SamsungMakerNoteField("MakerNoteVersion", _trim_ascii(payload[:8]), 0),
    ]
    if len(payload) >= 16:
        fields.extend(
            (
                SamsungMakerNoteField("PreviewImageStart", _u32(payload, 8), 2, "Preview"),
                SamsungMakerNoteField("PreviewImageLength", _u32(payload, 12), 3, "Preview"),
            )
        )
    diagnostics = [
        "Samsung MakerNote bridge ready: MakerNotes.pm STMN route decoded Samsung.pm Main.",
    ]
    if payload_result.conditional_subdirectory_present:
        diagnostics.append(
            f"Samsung MakerNote blocked: {SAMSUNG_STMN_TABLE_LOCAL_BLOCKERS[0].message}"
        )
    return SamsungMakerNoteReadResult(tuple(fields), tuple(diagnostics))


def collect_samsung_stmn_process_binary_unknown_read_tags(
    path: Path,
) -> SamsungStmnUnknownReadResult:
    payload_result = _samsung_stmn_payload_from_jpeg(path)
    if isinstance(payload_result, SamsungMakerNoteReadResult):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=tuple(
                diagnostic.replace(
                    "Samsung MakerNote blocked",
                    "Samsung STMN ProcessBinaryData unknown discovery blocked",
                )
                for diagnostic in payload_result.diagnostics
            ),
            evidence_ids=SAMSUNG_STMN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    result = process_binarydata_unknown_tags_from_payload(
        payload_result.payload,
        _samsung_stmn_unknown_policy(
            len(payload_result.payload),
            payload_result.conditional_subdirectory_present,
        ),
    )
    diagnostics = [
        diagnostic.replace(
            "ProcessBinaryData unknown discovery",
            "Samsung STMN ProcessBinaryData unknown discovery",
        )
        for diagnostic in result.diagnostics
    ]
    if payload_result.conditional_subdirectory_present:
        diagnostics.append(
            "Samsung STMN ProcessBinaryData unknown discovery skipped conditional "
            "SamsungIFD variable span at entry 0x000b."
        )
    return ProcessBinaryDataUnknownReadResult(
        tags=result.tags,
        diagnostics=tuple(diagnostics),
        evidence_ids=result.evidence_ids,
    )


def _samsung_stmn_payload_from_jpeg(
    path: Path,
) -> SamsungStmnPayload | SamsungMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    if make is None or make.upper() != "SAMSUNG":
        return SamsungMakerNoteReadResult(
            (), ("Samsung MakerNote blocked: IFD0 Make did not select Samsung.",)
        )
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return SamsungMakerNoteReadResult(
            (), ("Samsung MakerNote blocked: missing ExifIFD pointer.",)
        )
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    maker_entry = next(
        (entry for entry in exif_ifd.entries if entry.tag_id == _MAKER_NOTE_TAG), None
    )
    if maker_entry is None:
        return SamsungMakerNoteReadResult((), ("Samsung MakerNote blocked: missing tag 0x927c.",))
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, maker_entry, header.endian)
    if raw_location is None:
        return SamsungMakerNoteReadResult(
            (), ("Samsung MakerNote blocked: raw value is truncated.",)
        )
    _maker_offset, payload = raw_location
    if not _is_stmn_payload(payload):
        return SamsungMakerNoteReadResult(
            (), ("Samsung MakerNote blocked: MakerNote payload did not match STMN route.",)
        )
    return SamsungStmnPayload(
        payload=payload,
        conditional_subdirectory_present=_has_conditional_samsung_ifd(payload),
    )


def _samsung_stmn_unknown_policy(
    payload_size: int,
    conditional_subdirectory_present: bool,
) -> ProcessBinaryDataUnknownTablePolicy:
    known_spans = [
        ProcessBinaryDataKnownSpan(start_index=0, entry_count=2),
        ProcessBinaryDataKnownSpan(start_index=2, entry_count=2),
    ]
    if conditional_subdirectory_present:
        subdirectory_entry_count = max(
            1,
            (payload_size - _SAMSUNG_STMN_CONDITIONAL_SUBDIRECTORY_OFFSET)
            // _SAMSUNG_STMN_FIELD_SIZE,
        )
        known_spans.append(
            ProcessBinaryDataKnownSpan(
                start_index=_SAMSUNG_STMN_CONDITIONAL_SUBDIRECTORY_INDEX,
                entry_count=subdirectory_entry_count,
            )
        )
    return ProcessBinaryDataUnknownTablePolicy(
        tag_prefix="Samsung",
        first_entry=0,
        increment=_SAMSUNG_STMN_FIELD_SIZE,
        known_spans=tuple(known_spans),
        evidence_ids=SAMSUNG_STMN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def _has_conditional_samsung_ifd(payload: bytes) -> bool:
    candidate = payload[
        _SAMSUNG_STMN_CONDITIONAL_SUBDIRECTORY_OFFSET : (
            _SAMSUNG_STMN_CONDITIONAL_SUBDIRECTORY_OFFSET + _SAMSUNG_STMN_FIELD_SIZE
        )
    ]
    return (
        len(candidate) == _SAMSUNG_STMN_FIELD_SIZE
        and candidate[0] != 0
        and candidate[1:] == b"\0\0\0"
    )


def _is_stmn_payload(payload: bytes) -> bool:
    return (
        len(payload) >= 12
        and payload[:4] == b"STMN"
        and all(0x30 <= value <= 0x39 for value in payload[4:7])
    )


def _trim_ascii(data: bytes) -> str:
    return data.rstrip(b"\x00 ").decode("ascii", errors="replace")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")
