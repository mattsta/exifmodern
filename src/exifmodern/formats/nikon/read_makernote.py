"""Nikon MakerNote reader slices backed by MakerNotes.pm and Nikon.pm."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from exifmodern.formats.jpeg.container import (
    inspect_jpeg_nikon_maker_note_bridge,
    read_exif_app1,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
)
from exifmodern.formats.maker_notes import render_maker_note_package_print_value
from exifmodern.formats.tiff.primitives import (
    Endian,
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
    process_binarydata_unknown_tags_from_payload,
)


@dataclass(frozen=True)
class NikonMakerNoteField:
    name: str
    value: str | int | float
    tag_id: int
    family_2_group: str = "Camera"


@dataclass(frozen=True)
class NikonMakerNoteReadResult:
    fields: tuple[NikonMakerNoteField, ...]
    diagnostics: tuple[str, ...]


NIKON_SOURCE_TABLE = "Image::ExifTool::Nikon::Main"
NIKON_SOURCE_MODULE = "Image::ExifTool::Nikon"
NIKON_UNKNOWNINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE = "nikon-unknowninfo-process-binarydata-unknown"
NIKON_UNKNOWNINFO2_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "nikon-unknowninfo2-process-binarydata-unknown"
)
NIKON_UNKNOWNINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "nikon.read.unknowninfo.main_route",
    "nikon.read.unknowninfo.binarydata_policy",
    "public.unknown.binary-block.process-binarydata",
    "public.unknown.binary-block.gettaginfo",
)
NIKON_UNKNOWNINFO2_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "nikon.read.unknowninfo2.main_route",
    "nikon.read.unknowninfo2.binarydata_policy",
    "public.unknown.binary-block.process-binarydata",
    "public.unknown.binary-block.gettaginfo",
)
_TAG_NAMES = {
    0x0001: "MakerNoteVersion",
    0x0002: "ISO",
    0x0003: "ColorMode",
    0x0004: "Quality",
    0x0005: "WhiteBalance",
    0x0006: "Sharpness",
    0x0007: "FocusMode",
    0x0008: "FlashSetting",
    0x000F: "ISOSelection",
    0x0010: "DataDump",
    0x0080: "ImageAdjustment",
    0x0082: "AuxiliaryLens",
    0x0085: "ManualFocusDistance",
    0x0086: "DigitalZoom",
    0x0088: "AFInfo",
    0x008F: "SceneMode",
    0x0E00: "PrintIM",
}
NIKON_AF_INFO_TABLE = "AFInfo"
type NikonProcessBinaryUnknownReadTag = ProcessBinaryDataUnknownReadTag
type NikonProcessBinaryUnknownReadResult = ProcessBinaryDataUnknownReadResult
_NIKON_UNKNOWNINFO_TAG = 0x002C
_NIKON_UNKNOWNINFO2_TAG = 0x0032
_NIKON_INT32U_FIELD_SIZE = 4
_NIKON_UNKNOWNINFO_POLICY = ProcessBinaryDataUnknownTablePolicy(
    "Nikon_UnknownInfo",
    0,
    _NIKON_INT32U_FIELD_SIZE,
    (ProcessBinaryDataKnownSpan(start_index=0, entry_count=1),),
    NIKON_UNKNOWNINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    "big",
)
_NIKON_UNKNOWNINFO2_POLICY = ProcessBinaryDataUnknownTablePolicy(
    "Nikon_UnknownInfo2",
    0,
    _NIKON_INT32U_FIELD_SIZE,
    (ProcessBinaryDataKnownSpan(start_index=0, entry_count=1),),
    NIKON_UNKNOWNINFO2_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    "big",
)


def _shared_evidence_ids(
    policy: ProcessBinaryDataUnknownTablePolicy | ProcessBinaryDataUnknownReadResult,
) -> tuple[str, ...]:
    value = policy.evidence_ids
    if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
        raise TypeError("ProcessBinaryDataUnknownTablePolicy evidence IDs must be strings.")
    return tuple(str(item) for item in value)


def read_nikon_maker_note_from_jpeg(path: Path) -> NikonMakerNoteReadResult:
    bridge = inspect_jpeg_nikon_maker_note_bridge(path)
    if bridge.status == "missing":
        return NikonMakerNoteReadResult((), ())
    if not bridge.ready or bridge.context is None:
        return NikonMakerNoteReadResult((), bridge.diagnostics)
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    if make is None or not make.upper().startswith("NIKON"):
        return NikonMakerNoteReadResult((), ())

    try:
        maker_ifd = parse_ifd(
            exif.tiff_data,
            bridge.context.maker_note_tiff_offset
            + (8 if bridge.raw_maker_note.startswith(b"Nikon\x00\x01") else 0),
            bridge.context.byte_order,
        )
    except ValueError as exc:
        return NikonMakerNoteReadResult((), (f"Nikon MakerNote blocked: {exc}",))

    fields: list[NikonMakerNoteField] = []
    focus_mode: str | None = None
    for entry in maker_ifd.entries:
        if entry.tag_id == 0x0088:
            fields.extend(_af_info_fields(exif.tiff_data, entry, bridge.context.byte_order))
            continue
        if entry.tag_id in _TAG_NAMES:
            field = _field(exif.tiff_data, entry, bridge.context.byte_order)
            if field.name == "PrintIM":
                printim_version = _printim_version(exif.tiff_data, entry, bridge.context.byte_order)
                if printim_version is not None:
                    fields.append(
                        NikonMakerNoteField(
                            "PrintIMVersion",
                            printim_version,
                            0,
                            "Printing",
                        )
                    )
                continue
            if field.name == "FocusMode" and isinstance(field.value, str):
                focus_mode = field.value
            fields.append(field)
    if focus_mode is not None:
        fields.append(
            NikonMakerNoteField(
                "AutoFocus",
                "Off" if focus_mode.lower().startswith("manual") else "On",
                0x0007,
            )
        )
    if not fields:
        return NikonMakerNoteReadResult((), bridge.diagnostics)
    return NikonMakerNoteReadResult(
        tuple(fields),
        (
            "Nikon MakerNote bridge ready: MakerNotes.pm Nikon Type1/headerless "
            "routing surfaced Nikon.pm Main fields.",
        ),
    )


def collect_nikon_unknowninfo_process_binary_unknown_read_tags(
    path: Path,
) -> NikonProcessBinaryUnknownReadResult:
    return _collect_nikon_process_binary_unknown_read_tags(
        path,
        _NIKON_UNKNOWNINFO_TAG,
        _NIKON_UNKNOWNINFO_POLICY,
        "Nikon UnknownInfo",
    )


def collect_nikon_unknowninfo2_process_binary_unknown_read_tags(
    path: Path,
) -> NikonProcessBinaryUnknownReadResult:
    return _collect_nikon_process_binary_unknown_read_tags(
        path,
        _NIKON_UNKNOWNINFO2_TAG,
        _NIKON_UNKNOWNINFO2_POLICY,
        "Nikon UnknownInfo2",
    )


def _collect_nikon_process_binary_unknown_read_tags(
    path: Path,
    binary_data_tag_id: int,
    policy: ProcessBinaryDataUnknownTablePolicy,
    diagnostic_prefix: str,
) -> NikonProcessBinaryUnknownReadResult:
    bridge = inspect_jpeg_nikon_maker_note_bridge(path)
    if bridge.status == "missing":
        return ProcessBinaryDataUnknownReadResult(
            (),
            (),
            _shared_evidence_ids(policy),
        )
    if not bridge.ready or bridge.context is None:
        return ProcessBinaryDataUnknownReadResult(
            (),
            tuple(
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked: {message}"
                for message in bridge.diagnostics
            ),
            _shared_evidence_ids(policy),
        )
    exif = read_exif_app1(path)
    maker_ifd_offset = bridge.context.maker_note_tiff_offset + (
        8 if bridge.raw_maker_note.startswith(b"Nikon\x00\x01") else 0
    )
    try:
        maker_ifd = parse_ifd(exif.tiff_data, maker_ifd_offset, bridge.context.byte_order)
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            (),
            (f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked: {exc}",),
            _shared_evidence_ids(policy),
        )
    entry = next(
        (candidate for candidate in maker_ifd.entries if candidate.tag_id == binary_data_tag_id),
        None,
    )
    if entry is None:
        return ProcessBinaryDataUnknownReadResult(
            (),
            (),
            _shared_evidence_ids(policy),
        )
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, entry, bridge.context.byte_order)
    if raw_location is None:
        return ProcessBinaryDataUnknownReadResult(
            (),
            (
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked: "
                "raw value is truncated.",
            ),
            _shared_evidence_ids(policy),
        )
    _, payload = raw_location
    result = process_binarydata_unknown_tags_from_payload(payload, policy)
    return ProcessBinaryDataUnknownReadResult(
        result.tags,
        tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        _shared_evidence_ids(result),
    )


def _field(raw: bytes, entry: IfdEntry, byte_order: Endian) -> NikonMakerNoteField:
    name = _TAG_NAMES[entry.tag_id]
    value = read_entry_value(raw, entry, byte_order)
    if name == "MakerNoteVersion" and isinstance(value, bytes):
        digits = "".join(str(part) for part in value)
        rendered: str | int | float = f"{int(digits[:2])}.{digits[2:]}" if digits else ""
    elif name == "DataDump":
        rendered = f"(Binary data {entry.count} bytes, use -b option to extract)"
    elif name == "ISO" and isinstance(value, list):
        rendered = _nikon_iso_value(value)
    elif name == "ManualFocusDistance" and value is None:
        rendered = "undef"
    elif isinstance(value, bytes):
        rendered = _format_nikon_string(value)
    elif isinstance(value, str):
        rendered = _format_nikon_text(value)
    elif isinstance(value, int):
        package_print = _package_print("Main", name, value, entry.tag_id)
        rendered = package_print if package_print is not None else value
    else:
        rendered = value if isinstance(value, (int, float)) else str(value)
    return NikonMakerNoteField(name, rendered, entry.tag_id)


def _nikon_iso_value(value: list[int] | list[Fraction | None]) -> str | int:
    if len(value) != 2 or not all(isinstance(part, int) for part in value):
        return " ".join(str(part) for part in value)
    hi_flag = value[0]
    iso_value = value[1]
    if not isinstance(hi_flag, int) or not isinstance(iso_value, int):
        return " ".join(str(part) for part in value)
    if hi_flag == 0:
        return iso_value
    if hi_flag == 1:
        return f"Hi {iso_value}"
    return f"{hi_flag} {iso_value}"


def _printim_version(raw: bytes, entry: IfdEntry, byte_order: Endian) -> str | None:
    value = read_entry_value(raw, entry, byte_order)
    if not isinstance(value, bytes) or not value.startswith(b"PrintIM\0"):
        return None
    raw_version = value[8:12]
    if len(raw_version) != 4:
        return None
    return raw_version.decode("ascii", errors="replace")


def _format_nikon_string(value: bytes) -> str:
    return _format_nikon_text(value.rstrip(b"\x00").decode("latin-1", errors="replace"))


def _format_nikon_text(value: str) -> str:
    text = value.strip()
    if text in {"AF-C", "AF-S"}:
        return text
    return text[:1] + text[1:].lower() if text.isupper() else text


def _af_info_fields(raw: bytes, entry: IfdEntry, byte_order: Endian) -> list[NikonMakerNoteField]:
    value = read_entry_value(raw, entry, byte_order)
    if not isinstance(value, bytes) or len(value) < 4:
        return []
    af_points = int.from_bytes(value[2:4], byte_order)
    return [
        NikonMakerNoteField(
            "AFAreaMode",
            _package_print(NIKON_AF_INFO_TABLE, "AFAreaMode", value[0], 0) or value[0],
            0,
        ),
        NikonMakerNoteField(
            "AFPoint",
            _package_print(NIKON_AF_INFO_TABLE, "AFPoint", value[1], 1) or value[1],
            1,
        ),
        NikonMakerNoteField(
            "AFPointsInFocus",
            _package_print(NIKON_AF_INFO_TABLE, "AFPointsInFocus", af_points, 2) or af_points,
            2,
        ),
    ]


def _package_print(
    table: str,
    tag_name: str,
    raw_value: int | str,
    tag_id: int | str,
) -> str | None:
    return render_maker_note_package_print_value(
        module=NIKON_SOURCE_MODULE,
        table=table,
        tag_name=tag_name,
        raw_value=raw_value,
        tag_id=tag_id,
    )
