"""General Imaging MakerNote reader adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.ge.makernote_transaction_plan import (
    GE_TAGS_BY_ID,
    MACRO_LABELS,
    GeByteOrder,
)
from exifmodern.formats.jpeg.container import read_exif_app1, tiff_entry_raw_value_location
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_SHORT,
    parse_ifd,
    parse_tiff_header,
)


@dataclass(frozen=True)
class GeMakerNoteField:
    name: str
    value: str | int
    tag_id: int
    family_2_group: str = "Camera"


@dataclass(frozen=True)
class GeMakerNoteReadResult:
    fields: tuple[GeMakerNoteField, ...]
    diagnostics: tuple[str, ...]


GE_SOURCE_TABLE = "Image::ExifTool::GE::Main"


def read_ge_maker_note_from_jpeg(path: Path) -> GeMakerNoteReadResult:
    app1 = read_exif_app1(path)
    header = parse_tiff_header(app1.tiff_data)
    ifd0 = parse_ifd(app1.tiff_data, header.first_ifd_offset, header.endian)
    exif_entry = next((entry for entry in ifd0.entries if entry.tag_id == 0x8769), None)
    if exif_entry is None:
        return GeMakerNoteReadResult((), ("GE MakerNote bridge missing ExifIFD pointer.",))
    exif_ifd = parse_ifd(app1.tiff_data, exif_entry.value_offset, header.endian)
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return GeMakerNoteReadResult((), ("GE MakerNote bridge missing MakerNote tag 0x927c.",))
    raw_location = tiff_entry_raw_value_location(app1.tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return GeMakerNoteReadResult((), ("GE MakerNote bridge truncated MakerNote value.",))
    maker_note_tiff_offset, maker_note = raw_location
    fields = _read_ge_fields(maker_note, app1.tiff_data, maker_note_tiff_offset, header.endian)
    return GeMakerNoteReadResult(fields, ())


def _read_ge_fields(
    data: bytes,
    tiff_data: bytes,
    maker_note_tiff_offset: int,
    byte_order: GeByteOrder,
) -> tuple[GeMakerNoteField, ...]:
    if data.startswith(b"GE\x00\x00") and len(data) >= 18:
        ge_tiff = data[10:]
        header = parse_tiff_header(ge_tiff)
        ifd = parse_ifd(ge_tiff, header.first_ifd_offset, header.endian)
        return _read_ge_entries(
            data,
            tiff_data,
            2,
            header.endian,
            tuple(
                (entry.tag_id, entry.field_type, entry.count, entry.value_offset)
                for entry in ifd.entries
            ),
        )
    if len(data) < 2:
        return ()
    entry_count = int.from_bytes(data[:2], byte_order)
    entries: list[tuple[int, int, int, int]] = []
    for index in range(entry_count):
        offset = 2 + index * 12
        if offset + 12 > len(data):
            break
        entries.append(
            (
                int.from_bytes(data[offset : offset + 2], byte_order),
                int.from_bytes(data[offset + 2 : offset + 4], byte_order),
                int.from_bytes(data[offset + 4 : offset + 8], byte_order),
                int.from_bytes(data[offset + 8 : offset + 12], byte_order),
            )
        )
    return _read_ge_entries(data, tiff_data, maker_note_tiff_offset, byte_order, tuple(entries))


def _read_ge_entries(
    data: bytes,
    tiff_data: bytes,
    maker_note_tiff_offset: int,
    byte_order: GeByteOrder,
    entries: tuple[tuple[int, int, int, int], ...],
) -> tuple[GeMakerNoteField, ...]:
    fields: list[GeMakerNoteField] = []
    for tag_id, field_type, count, value_or_offset in entries:
        spec = GE_TAGS_BY_ID.get(tag_id)
        if spec is None:
            continue
        value = _read_ge_value(
            data,
            tiff_data,
            maker_note_tiff_offset,
            byte_order,
            field_type,
            count,
            value_or_offset,
        )
        if value is None:
            continue
        if spec.name == "Macro" and isinstance(value, int):
            value = MACRO_LABELS.get(value, value)
        fields.append(GeMakerNoteField(spec.name, value, tag_id))
    if not any(field.name == "GEMake" for field in fields):
        make = _find_ge_make_string(data)
        if make is not None:
            fields.append(GeMakerNoteField("GEMake", make, 0x0300))
    return tuple(fields)


def _read_ge_value(
    data: bytes,
    tiff_data: bytes,
    maker_note_tiff_offset: int,
    byte_order: GeByteOrder,
    field_type: int,
    count: int,
    value_or_offset: int,
) -> str | int | None:
    if field_type == TIFF_TYPE_SHORT and count == 1:
        if byte_order == "big":
            return value_or_offset >> 16
        return value_or_offset & 0xFFFF
    if field_type != TIFF_TYPE_ASCII:
        return None
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
    relative_offset = value_offset - maker_note_tiff_offset
    if 0 <= relative_offset <= len(data) - count:
        return data[relative_offset : relative_offset + count]
    if 0 <= value_offset <= len(data) - count:
        return data[value_offset : value_offset + count]
    if 0 <= value_offset <= len(tiff_data) - count:
        return tiff_data[value_offset : value_offset + count]
    return None


def _find_ge_make_string(data: bytes) -> str | None:
    marker = b"GE DIGITAL CAMERA\x00"
    offset = data.find(marker)
    if offset < 0:
        return None
    return marker.rstrip(b"\x00").decode("latin-1")
