"""Pentax AOC MakerNote reader slice backed by MakerNotes.pm and Pentax.pm."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.jpeg.container import (
    read_exif_app1,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
    tiff_long_tag_value,
)
from exifmodern.formats.maker_notes import render_maker_note_package_print_value
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_BYTE,
    TIFF_TYPE_LONG,
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
    UnknownReadBlocker,
    process_binarydata_unknown_tags_from_payload,
)


@dataclass(frozen=True)
class PentaxMakerNoteField:
    name: str
    value: str | int | float
    tag_id: int
    family_2_group: str = "Camera"


@dataclass(frozen=True)
class PentaxMakerNoteReadResult:
    fields: tuple[PentaxMakerNoteField, ...]
    diagnostics: tuple[str, ...]


PENTAX_SOURCE_TABLE = "Image::ExifTool::Pentax::Main"
PENTAX_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "pentax-camerasettingsunknown-process-binarydata-unknown"
)
PENTAX_AEINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE = "pentax-aeinfo-process-binarydata-unknown"
PENTAX_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "pentax.read.camera_settings_unknown_route",
    "pentax.read.binarydata_attrs",
    "pentax.read.camera_settings_unknown_table",
)
PENTAX_AEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "pentax.read.aeinfo_route",
    "pentax.read.aeinfo_base_table",
    "pentax.read.aeinfo_variant_tables",
    "pentax.read.aeinfo_unknown_synthesis",
)
PENTAX_TABLE_LOCAL_BLOCKERS = (
    UnknownReadBlocker(
        code="pentax_aeinfo_base_hook_blocked",
        message=(
            "Pentax AEInfo ProcessBinaryData unknown discovery blocked: base AEInfo uses "
            "DATAMEMBER and an AEFlags Hook that shifts later offsets for some counts."
        ),
        evidence_ids=("pentax.read.aeinfo_hook_blocker",),
    ),
    UnknownReadBlocker(
        code="pentax_aeinfo_count_gt_20_hook_terminal",
        message=(
            "Pentax AEInfo count > 20 remains terminal for generic unknown fanout "
            "because the AEFlags Hook changes later offsets before scalar extraction."
        ),
        evidence_ids=("pentax.read.aeflags_hook_terminal",),
    ),
    UnknownReadBlocker(
        code="pentax_lensdata_hook_blocked",
        message=(
            "Pentax LensData ProcessBinaryData unknown discovery blocked: LensData uses "
            "DATAMEMBER, model Conditions, masks, and NewLensData Hook offset changes; "
            "this remains terminal for generic unknown fanout."
        ),
        evidence_ids=("pentax.read.lensdata_hook_blocker",),
    ),
)
type PentaxProcessBinaryUnknownReadTag = ProcessBinaryDataUnknownReadTag
type PentaxProcessBinaryUnknownReadResult = ProcessBinaryDataUnknownReadResult
_PENTAX_CAMERA_SETTINGS_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Pentax_CameraSettingsUnknown",
    first_entry=0,
    increment=1,
    known_spans=(),
    evidence_ids=PENTAX_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_PENTAX_AEINFO_BASE_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Pentax_AEInfo",
    first_entry=0,
    increment=1,
    known_spans=(ProcessBinaryDataKnownSpan(start_index=0, entry_count=15),),
    evidence_ids=PENTAX_AEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_PENTAX_AEINFO2_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Pentax_AEInfo2",
    first_entry=0,
    increment=1,
    known_spans=(
        ProcessBinaryDataKnownSpan(start_index=2, entry_count=5),
        ProcessBinaryDataKnownSpan(start_index=8, entry_count=1),
        ProcessBinaryDataKnownSpan(start_index=11, entry_count=1),
        ProcessBinaryDataKnownSpan(start_index=15, entry_count=5),
    ),
    evidence_ids=PENTAX_AEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_PENTAX_AEINFO3_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Pentax_AEInfo3",
    first_entry=0,
    increment=1,
    known_spans=(
        ProcessBinaryDataKnownSpan(start_index=16, entry_count=3),
        ProcessBinaryDataKnownSpan(start_index=28, entry_count=4),
    ),
    evidence_ids=PENTAX_AEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_PENTAX_AEINFO_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Pentax_AEInfoUnknown",
    first_entry=0,
    increment=1,
    known_spans=(),
    evidence_ids=PENTAX_AEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_TAG_NAMES = {
    0x0000: "PentaxVersion",
    0x0005: "PentaxModelID",
    0x0008: "Quality",
    0x0019: "WhiteBalance",
    0x0023: "HometownCity",
}
_PACKAGE_PRINT_TAGS = frozenset(
    {
        "PentaxModelID",
        "Quality",
        "WhiteBalance",
        "HometownCity",
    }
)


def read_pentax_maker_note_from_jpeg(path: Path) -> PentaxMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    model = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x0110, header.endian) or ""
    if make is None or not make.startswith("PENTAX"):
        return PentaxMakerNoteReadResult((), ())
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return PentaxMakerNoteReadResult((), ("Pentax MakerNote blocked: missing ExifIFD.",))
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return PentaxMakerNoteReadResult((), ())
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return PentaxMakerNoteReadResult((), ("Pentax MakerNote blocked: truncated value.",))
    maker_offset, raw_maker_note = raw_location
    if not raw_maker_note.startswith(b"AOC\x00"):
        return PentaxMakerNoteReadResult((), ())
    if model.startswith(("PENTAX Optio 330RS", "PENTAX Optio 430RS")):
        return PentaxMakerNoteReadResult(
            (), ("Pentax MakerNote blocked: AOC payload selects MakerNotePentax3 Casio route.",)
        )
    byte_order = _aoc_byte_order(raw_maker_note)
    if byte_order is None:
        return PentaxMakerNoteReadResult(
            (), ("Pentax MakerNote blocked: AOC byte-order marker is not MM or II.",)
        )
    maker_ifd_offset = maker_offset + 6
    try:
        maker_ifd = parse_ifd(exif.tiff_data, maker_ifd_offset, byte_order)
    except ValueError as exc:
        return PentaxMakerNoteReadResult((), (f"Pentax MakerNote blocked: {exc}",))
    fields = [
        _field(exif.tiff_data, entry, byte_order, maker_offset, maker_ifd_offset)
        for entry in maker_ifd.entries
        if entry.tag_id in _TAG_NAMES
    ]
    return PentaxMakerNoteReadResult(
        tuple(field for field in fields if field is not None),
        (
            "Pentax MakerNote bridge ready: MakerNotes.pm MakerNotePentax AOC "
            "routing used Unknown byte order and FixBase-compatible value offsets.",
            "Pentax MakerNote blocked: encrypted ShutterCount and nested LensInfo/LensType "
            "binary tables remain unported.",
        ),
    )


def collect_pentax_camerasettings_unknown_process_binary_unknown_read_tags(
    path: Path,
) -> PentaxProcessBinaryUnknownReadResult:
    try:
        maker_ifd, raw, byte_order, maker_offset, maker_ifd_offset = _pentax_aoc_maker_ifd(path)
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                f"Pentax CameraSettingsUnknown ProcessBinaryData unknown discovery blocked: {exc}",
            ),
            evidence_ids=PENTAX_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    entry = next((candidate for candidate in maker_ifd.entries if candidate.tag_id == 0x0205), None)
    if entry is None or entry.count < 25:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=PENTAX_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    payload = _entry_payload(raw, entry, byte_order, maker_offset, maker_ifd_offset)
    if payload is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                "Pentax CameraSettingsUnknown ProcessBinaryData unknown discovery blocked: "
                "subdirectory payload is truncated.",
            ),
            evidence_ids=PENTAX_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    result = process_binarydata_unknown_tags_from_payload(
        payload,
        _PENTAX_CAMERA_SETTINGS_UNKNOWN_POLICY,
    )
    return ProcessBinaryDataUnknownReadResult(
        tags=result.tags,
        diagnostics=tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                "Pentax CameraSettingsUnknown ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        evidence_ids=PENTAX_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def collect_pentax_aeinfo_process_binary_unknown_read_tags(
    path: Path,
) -> PentaxProcessBinaryUnknownReadResult:
    try:
        maker_ifd, raw, byte_order, maker_offset, maker_ifd_offset = _pentax_aoc_maker_ifd(path)
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(f"Pentax AEInfo ProcessBinaryData unknown discovery blocked: {exc}",),
            evidence_ids=PENTAX_AEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    entry = next((candidate for candidate in maker_ifd.entries if candidate.tag_id == 0x0206), None)
    if entry is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=PENTAX_AEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    policy = _pentax_aeinfo_policy_for_count(entry.count)
    if policy is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(PENTAX_TABLE_LOCAL_BLOCKERS[0].message,),
            evidence_ids=PENTAX_AEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    payload = _entry_payload(raw, entry, byte_order, maker_offset, maker_ifd_offset)
    if payload is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                "Pentax AEInfo ProcessBinaryData unknown discovery blocked: "
                "subdirectory payload is truncated.",
            ),
            evidence_ids=PENTAX_AEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    result = process_binarydata_unknown_tags_from_payload(payload, policy)
    return ProcessBinaryDataUnknownReadResult(
        tags=result.tags,
        diagnostics=tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                "Pentax AEInfo ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        evidence_ids=PENTAX_AEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def _pentax_aeinfo_policy_for_count(count: int) -> ProcessBinaryDataUnknownTablePolicy | None:
    if 15 < count <= 20:
        return _PENTAX_AEINFO_BASE_POLICY
    if count == 21:
        return _PENTAX_AEINFO2_POLICY
    if count == 48 or count == 64:
        return _PENTAX_AEINFO3_POLICY
    if count <= 25 and count != 21:
        return None
    return _PENTAX_AEINFO_UNKNOWN_POLICY


def _aoc_byte_order(raw_maker_note: bytes) -> Endian | None:
    if raw_maker_note[4:6] == b"II":
        return "little"
    if raw_maker_note[4:6] == b"MM":
        return "big"
    return None


def _pentax_aoc_maker_ifd(path: Path) -> tuple[Ifd, bytes, Endian, int, int]:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    model = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x0110, header.endian) or ""
    if make is None or not make.startswith("PENTAX"):
        raise ValueError("IFD0 Make did not select Pentax.")
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
    if not raw_maker_note.startswith(b"AOC\x00"):
        raise ValueError("missing AOC header.")
    if model.startswith(("PENTAX Optio 330RS", "PENTAX Optio 430RS")):
        raise ValueError("AOC payload selects MakerNotePentax3 Casio route.")
    byte_order = _aoc_byte_order(raw_maker_note)
    if byte_order is None:
        raise ValueError("AOC byte-order marker is not MM or II.")
    maker_ifd_offset = maker_offset + 6
    return (
        parse_ifd(exif.tiff_data, maker_ifd_offset, byte_order),
        exif.tiff_data,
        byte_order,
        maker_offset,
        maker_ifd_offset,
    )


def _field(
    raw: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_offset: int,
    maker_ifd_offset: int,
) -> PentaxMakerNoteField | None:
    payload = _entry_payload(raw, entry, byte_order, maker_offset, maker_ifd_offset)
    if payload is None:
        return None
    name = _TAG_NAMES[entry.tag_id]
    value = _decode_payload(payload, entry, byte_order)
    if name == "PentaxVersion" and isinstance(value, list):
        rendered: str | int | float = ".".join(str(part) for part in value)
    elif name in _PACKAGE_PRINT_TAGS and isinstance(value, int):
        rendered = _package_print(name, value, entry.tag_id) or value
    else:
        rendered = value if isinstance(value, (int, float)) else str(value)
    return PentaxMakerNoteField(name, rendered, entry.tag_id)


def _package_print(tag_name: str, raw_value: int, tag_id: int) -> str | None:
    return render_maker_note_package_print_value(
        module="Image::ExifTool::Pentax",
        table="Main",
        tag_name=tag_name,
        tag_id=tag_id,
        raw_value=raw_value,
    )


def _entry_payload(
    raw: bytes,
    entry: IfdEntry,
    byte_order: Endian,
    maker_offset: int,
    maker_ifd_offset: int,
) -> bytes | None:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        return None
    byte_count = field_size * entry.count
    if byte_count <= 4:
        return entry.value_offset.to_bytes(4, byte_order)[:byte_count]
    for start in (
        entry.value_offset,
        maker_offset + entry.value_offset,
        maker_ifd_offset + entry.value_offset,
    ):
        end = start + byte_count
        if start >= 0 and end <= len(raw):
            return raw[start:end]
    return None


def _decode_payload(
    payload: bytes,
    entry: IfdEntry,
    byte_order: Endian,
) -> str | int | list[int] | bytes:
    if entry.field_type == TIFF_TYPE_ASCII:
        return payload.rstrip(b"\x00").decode("latin-1", errors="replace")
    if entry.field_type in {TIFF_TYPE_BYTE, TIFF_TYPE_UNDEFINED}:
        values = list(payload)
        return values[0] if entry.count == 1 else values
    if entry.field_type == TIFF_TYPE_SHORT:
        values = [
            int.from_bytes(payload[index * 2 : index * 2 + 2], byte_order)
            for index in range(entry.count)
        ]
        return values[0] if entry.count == 1 else values
    if entry.field_type == TIFF_TYPE_LONG:
        values = [
            int.from_bytes(payload[index * 4 : index * 4 + 4], byte_order)
            for index in range(entry.count)
        ]
        return values[0] if entry.count == 1 else values
    return payload
