"""Motorola MakerNote reader adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.jpeg.container import read_exif_app1, tiff_entry_raw_value_location
from exifmodern.formats.motorola.makernote_transaction_plan import MOTOROLA_TAG_SPECS
from exifmodern.formats.tiff.primitives import TIFF_TYPE_ASCII, Endian, parse_ifd, parse_tiff_header


@dataclass(frozen=True)
class MotorolaMakerNoteField:
    name: str
    value: str
    tag_id: int
    family_2_group: str = "Camera"


@dataclass(frozen=True)
class MotorolaMakerNoteReadResult:
    fields: tuple[MotorolaMakerNoteField, ...]
    diagnostics: tuple[str, ...]


MOTOROLA_SOURCE_TABLE = "Image::ExifTool::Motorola::Main"


def read_motorola_maker_note_from_jpeg(path: Path) -> MotorolaMakerNoteReadResult:
    app1 = read_exif_app1(path)
    header = parse_tiff_header(app1.tiff_data)
    ifd0 = parse_ifd(app1.tiff_data, header.first_ifd_offset, header.endian)
    exif_entry = next((entry for entry in ifd0.entries if entry.tag_id == 0x8769), None)
    if exif_entry is None:
        return MotorolaMakerNoteReadResult(
            (), ("Motorola MakerNote bridge missing ExifIFD pointer.",)
        )
    exif_ifd = parse_ifd(app1.tiff_data, exif_entry.value_offset, header.endian)
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return MotorolaMakerNoteReadResult(
            (), ("Motorola MakerNote bridge missing MakerNote tag 0x927c.",)
        )
    raw_location = tiff_entry_raw_value_location(app1.tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return MotorolaMakerNoteReadResult(
            (), ("Motorola MakerNote bridge truncated MakerNote value.",)
        )
    maker_note_tiff_offset, maker_note = raw_location
    fields = _read_motorola_fields(
        maker_note,
        app1.tiff_data,
        maker_note_tiff_offset,
        header.endian,
    )
    return MotorolaMakerNoteReadResult(fields, ())


def _read_motorola_fields(
    data: bytes,
    tiff_data: bytes,
    maker_note_tiff_offset: int,
    byte_order: Endian,
) -> tuple[MotorolaMakerNoteField, ...]:
    entry_count_offset = 0
    first_entry_offset = 2
    if data.startswith(b"MOT\x00") and len(data) >= 10:
        entry_count_offset = 8
        first_entry_offset = 10
    if len(data) < entry_count_offset + 2:
        return ()
    entry_count = int.from_bytes(data[entry_count_offset : entry_count_offset + 2], byte_order)
    fields: list[MotorolaMakerNoteField] = []
    for index in range(entry_count):
        offset = first_entry_offset + index * 12
        if offset + 12 > len(data):
            break
        tag_id = int.from_bytes(data[offset : offset + 2], byte_order)
        spec = MOTOROLA_TAG_SPECS.get(tag_id)
        if spec is None:
            continue
        field_type = int.from_bytes(data[offset + 2 : offset + 4], byte_order)
        count = int.from_bytes(data[offset + 4 : offset + 8], byte_order)
        value_or_offset = int.from_bytes(data[offset + 8 : offset + 12], byte_order)
        if field_type != TIFF_TYPE_ASCII:
            continue
        value = _read_ascii(
            data,
            tiff_data,
            maker_note_tiff_offset,
            byte_order,
            count,
            value_or_offset,
        )
        if value is not None:
            fields.append(MotorolaMakerNoteField(spec.name, value, tag_id))
    return tuple(fields)


def _read_ascii(
    data: bytes,
    tiff_data: bytes,
    maker_note_tiff_offset: int,
    byte_order: Endian,
    count: int,
    value_or_offset: int,
) -> str | None:
    if count <= 4:
        raw = value_or_offset.to_bytes(4, byte_order)[:count]
    else:
        offset_payload = _read_offset_payload(
            data,
            tiff_data,
            maker_note_tiff_offset,
            value_or_offset,
            count,
        )
        if offset_payload is None:
            return None
        raw = offset_payload
    return raw.rstrip(b"\x00").decode("latin-1", errors="replace")


def _read_offset_payload(
    data: bytes,
    tiff_data: bytes,
    maker_note_tiff_offset: int,
    value_offset: int,
    count: int,
) -> bytes | None:
    if 0 <= value_offset <= len(data) - count:
        return data[value_offset : value_offset + count]
    relative_offset = value_offset - maker_note_tiff_offset
    if 0 <= relative_offset <= len(data) - count:
        return data[relative_offset : relative_offset + count]
    if 0 <= value_offset <= len(tiff_data) - count:
        return tiff_data[value_offset : value_offset + count]
    return None
