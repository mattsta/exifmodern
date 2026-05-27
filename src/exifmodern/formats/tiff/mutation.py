"""Reusable TIFF mutation model and offset rebuild primitives."""

from __future__ import annotations

from dataclasses import dataclass, replace

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_LONG,
    TYPE_SIZES,
    Endian,
    Ifd,
    IfdEntry,
    TiffFieldType,
    parse_ifd,
    parse_tiff_header,
)

GPS_INFO_IFD_POINTER = 0x8825
EXIF_IFD_POINTER = 0x8769
THUMBNAIL_OFFSET = 0x0201
THUMBNAIL_LENGTH = 0x0202


@dataclass(frozen=True)
class RawTiffEntry:
    tag_id: int
    field_type: TiffFieldType
    count: int
    raw_value: bytes


@dataclass(frozen=True)
class RawTiffDirectory:
    entries: tuple[RawTiffEntry, ...]
    next_ifd_offset: int


@dataclass(frozen=True)
class TiffMutationModel:
    endian: Endian
    ifd0: RawTiffDirectory
    exif_ifd: RawTiffDirectory | None
    gps_ifd: RawTiffDirectory | None
    ifd1: RawTiffDirectory | None
    thumbnail: bytes
    suffix: bytes


@dataclass(frozen=True)
class DirectoryLayout:
    directory: RawTiffDirectory
    next_ifd_offset: int


def parse_tiff_mutation_model(
    tiff_data: bytes,
    require_existing_gps: bool = False,
) -> TiffMutationModel:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    raw_ifd0 = raw_directory(tiff_data, ifd0, header.endian)
    exif_offset = inline_u32(raw_entry_by_tag(raw_ifd0.entries, EXIF_IFD_POINTER), header.endian)
    gps_offset = inline_u32(raw_entry_by_tag(raw_ifd0.entries, GPS_INFO_IFD_POINTER), header.endian)
    if require_existing_gps and (gps_offset is None or gps_offset == 0):
        raise ValueError("GPS IFD creation requires a dedicated source-confirmed oracle probe.")
    modeled_end = parsed_ifd_data_end(ifd0)
    exif_ifd = None
    if exif_offset is not None:
        parsed_exif_ifd = parse_ifd(tiff_data, exif_offset, header.endian)
        modeled_end = max(modeled_end, parsed_ifd_data_end(parsed_exif_ifd))
        exif_ifd = raw_directory(tiff_data, parsed_exif_ifd, header.endian)
    gps_ifd = None
    if gps_offset is not None and gps_offset != 0:
        parsed_gps_ifd = parse_ifd(tiff_data, gps_offset, header.endian)
        modeled_end = max(modeled_end, parsed_ifd_data_end(parsed_gps_ifd))
        gps_ifd = raw_directory(tiff_data, parsed_gps_ifd, header.endian)
    ifd1 = None
    thumbnail = b""
    if ifd0.next_ifd_offset:
        parsed_ifd1 = parse_ifd(tiff_data, ifd0.next_ifd_offset, header.endian)
        modeled_end = max(modeled_end, parsed_ifd_data_end(parsed_ifd1))
        ifd1 = raw_directory(tiff_data, parsed_ifd1, header.endian)
        thumbnail = thumbnail_bytes(tiff_data, ifd1.entries, header.endian)
        modeled_end = max(modeled_end, thumbnail_data_end(ifd1.entries, header.endian))
    return TiffMutationModel(
        endian=header.endian,
        ifd0=raw_ifd0,
        exif_ifd=exif_ifd,
        gps_ifd=gps_ifd,
        ifd1=ifd1,
        thumbnail=thumbnail,
        suffix=tiff_data[modeled_end:],
    )


def minimal_tiff_mutation_model(
    endian: Endian,
    ifd0: RawTiffDirectory,
    exif_ifd: RawTiffDirectory | None = None,
    gps_ifd: RawTiffDirectory | None = None,
) -> TiffMutationModel:
    return TiffMutationModel(
        endian=endian,
        ifd0=ifd0,
        exif_ifd=exif_ifd,
        gps_ifd=gps_ifd,
        ifd1=None,
        thumbnail=b"",
        suffix=b"",
    )


def raw_directory(tiff_data: bytes, ifd: Ifd, endian: Endian) -> RawTiffDirectory:
    return RawTiffDirectory(
        entries=tuple(raw_entry(tiff_data, entry, endian) for entry in ifd.entries),
        next_ifd_offset=ifd.next_ifd_offset,
    )


def raw_entry(tiff_data: bytes, entry: IfdEntry, endian: Endian) -> RawTiffEntry:
    byte_count = entry_byte_count(entry)
    if byte_count <= 4:
        raw_value = entry.value_offset.to_bytes(4, endian)[:byte_count]
    else:
        value_end = entry.value_offset + byte_count
        if value_end > len(tiff_data):
            raise ValueError(f"Truncated TIFF value at offset {entry.value_offset}")
        raw_value = tiff_data[entry.value_offset : value_end]
    return RawTiffEntry(
        tag_id=entry.tag_id,
        field_type=entry.field_type,
        count=entry.count,
        raw_value=raw_value,
    )


def entry_byte_count(entry: IfdEntry) -> int:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        raise ValueError(f"Unsupported TIFF field type: {entry.field_type}")
    return field_size * entry.count


def parsed_ifd_data_end(ifd: Ifd) -> int:
    directory_end = ifd.offset + directory_size_from_count(len(ifd.entries))
    value_end = directory_end
    for entry in ifd.entries:
        byte_count = entry_byte_count(entry)
        if byte_count > 4:
            value_end = max(value_end, entry.value_offset + byte_count)
    return value_end


def encode_tiff_mutation_model(parsed: TiffMutationModel) -> bytes:
    gps_ifd = parsed.gps_ifd
    sized_ifd0 = parsed.ifd0
    if gps_ifd is not None:
        sized_ifd0 = ensure_long_pointer_entry(sized_ifd0, GPS_INFO_IFD_POINTER, parsed.endian)
    if parsed.exif_ifd is not None:
        sized_ifd0 = ensure_long_pointer_entry(sized_ifd0, EXIF_IFD_POINTER, parsed.endian)
    exif_offset = 0
    gps_offset = 0
    next_directory_offset = 8 + directory_size(sized_ifd0)
    if parsed.exif_ifd is not None:
        exif_offset = next_directory_offset
        next_directory_offset += directory_size(parsed.exif_ifd)
    if gps_ifd is not None:
        gps_offset = next_directory_offset
        next_directory_offset += directory_size(gps_ifd)
    ifd1_offset = next_directory_offset if parsed.ifd1 is not None else 0
    directory_end = next_directory_offset
    if parsed.ifd1 is not None:
        directory_end += directory_size(parsed.ifd1)

    ifd0 = update_pointer_entry(sized_ifd0, EXIF_IFD_POINTER, exif_offset, parsed.endian)
    if gps_ifd is not None:
        ifd0 = update_pointer_entry(ifd0, GPS_INFO_IFD_POINTER, gps_offset, parsed.endian)
    ifd1 = parsed.ifd1
    if ifd1 is not None:
        thumbnail_offset = thumbnail_target_offset(
            (ifd0, parsed.exif_ifd, gps_ifd, ifd1),
            directory_end,
            parsed.thumbnail,
        )
        ifd1 = update_pointer_entry(ifd1, THUMBNAIL_OFFSET, thumbnail_offset, parsed.endian)

    layouts = (
        DirectoryLayout(ifd0, ifd1_offset),
        *optional_layout(parsed.exif_ifd, exif_offset),
        *optional_layout(gps_ifd, gps_offset),
        *optional_layout(ifd1, ifd1_offset),
    )
    return encode_tiff(parsed.endian, layouts, directory_end, parsed.thumbnail, parsed.suffix)


def optional_layout(
    directory: RawTiffDirectory | None,
    offset: int,
) -> tuple[DirectoryLayout, ...]:
    if directory is None or offset == 0:
        return ()
    return (DirectoryLayout(directory, 0),)


def thumbnail_target_offset(
    directories: tuple[RawTiffDirectory | None, ...],
    directory_end: int,
    thumbnail: bytes,
) -> int:
    if not thumbnail:
        return 0
    return directory_end + sum(external_values_size(directory) for directory in directories)


def encode_tiff(
    endian: Endian,
    layouts: tuple[DirectoryLayout, ...],
    external_start: int,
    thumbnail: bytes,
    suffix: bytes,
) -> bytes:
    encoded_directories: list[bytes] = []
    external_values: list[bytes] = []
    external_offset = external_start
    for layout in layouts:
        encoded_directory, directory_external, external_offset = encode_directory(
            layout,
            endian,
            external_offset,
        )
        encoded_directories.append(encoded_directory)
        external_values.append(directory_external)
    return (
        byte_order_marker(endian)
        + (42).to_bytes(2, endian)
        + (8).to_bytes(4, endian)
        + b"".join(encoded_directories)
        + b"".join(external_values)
        + thumbnail
        + suffix
    )


def encode_directory(
    layout: DirectoryLayout,
    endian: Endian,
    external_offset: int,
) -> tuple[bytes, bytes, int]:
    entries = tuple(sorted(layout.directory.entries, key=lambda entry: entry.tag_id))
    encoded_entries: list[bytes] = []
    external_values: list[bytes] = []
    next_external_offset = external_offset
    for entry in entries:
        value_field = inline_value_field(entry.raw_value)
        if value_field is None:
            value_field = next_external_offset.to_bytes(4, endian)
            external_values.append(entry.raw_value)
            next_external_offset += len(entry.raw_value)
        encoded_entries.append(encode_entry(entry, value_field, endian))
    return (
        len(entries).to_bytes(2, endian)
        + b"".join(encoded_entries)
        + layout.next_ifd_offset.to_bytes(4, endian),
        b"".join(external_values),
        next_external_offset,
    )


def encode_entry(entry: RawTiffEntry, value_field: bytes, endian: Endian) -> bytes:
    return (
        entry.tag_id.to_bytes(2, endian)
        + entry.field_type.to_bytes(2, endian)
        + entry.count.to_bytes(4, endian)
        + value_field
    )


def inline_value_field(raw_value: bytes) -> bytes | None:
    if len(raw_value) > 4:
        return None
    return raw_value.ljust(4, b"\x00")


def directory_size(directory: RawTiffDirectory) -> int:
    return directory_size_from_count(len(directory.entries))


def directory_size_from_count(entry_count: int) -> int:
    return 2 + entry_count * 12 + 4


def external_values_size(directory: RawTiffDirectory | None) -> int:
    if directory is None:
        return 0
    return sum(len(entry.raw_value) for entry in directory.entries if len(entry.raw_value) > 4)


def upsert_raw_entry(
    entries: tuple[RawTiffEntry, ...],
    updated_entry: RawTiffEntry,
) -> tuple[RawTiffEntry, ...]:
    retained = tuple(entry for entry in entries if entry.tag_id != updated_entry.tag_id)
    return (*retained, updated_entry)


def remove_raw_entry(
    directory: RawTiffDirectory,
    tag_id: int,
) -> RawTiffDirectory:
    entries = tuple(entry for entry in directory.entries if entry.tag_id != tag_id)
    return replace(directory, entries=entries)


def update_pointer_entry(
    directory: RawTiffDirectory,
    tag_id: int,
    offset: int,
    endian: Endian,
) -> RawTiffDirectory:
    entry = raw_entry_by_tag(directory.entries, tag_id)
    if entry is None:
        if offset == 0:
            return directory
        entry = RawTiffEntry(
            tag_id=tag_id,
            field_type=TIFF_TYPE_LONG,
            count=1,
            raw_value=offset.to_bytes(4, endian),
        )
    else:
        entry = replace(
            entry, field_type=TIFF_TYPE_LONG, count=1, raw_value=offset.to_bytes(4, endian)
        )
    return replace(directory, entries=upsert_raw_entry(directory.entries, entry))


def ensure_long_pointer_entry(
    directory: RawTiffDirectory,
    tag_id: int,
    endian: Endian,
) -> RawTiffDirectory:
    if raw_entry_by_tag(directory.entries, tag_id) is not None:
        return directory
    entry = RawTiffEntry(
        tag_id=tag_id,
        field_type=TIFF_TYPE_LONG,
        count=1,
        raw_value=(0).to_bytes(4, endian),
    )
    return replace(directory, entries=upsert_raw_entry(directory.entries, entry))


def thumbnail_bytes(tiff_data: bytes, entries: tuple[RawTiffEntry, ...], endian: Endian) -> bytes:
    offset = inline_u32(raw_entry_by_tag(entries, THUMBNAIL_OFFSET), endian)
    length = inline_u32(raw_entry_by_tag(entries, THUMBNAIL_LENGTH), endian)
    if offset is None or length is None or length == 0:
        return b""
    end = offset + length
    if end > len(tiff_data):
        raise ValueError(f"Truncated TIFF thumbnail at offset {offset}")
    return tiff_data[offset:end]


def thumbnail_data_end(entries: tuple[RawTiffEntry, ...], endian: Endian) -> int:
    offset = inline_u32(raw_entry_by_tag(entries, THUMBNAIL_OFFSET), endian)
    length = inline_u32(raw_entry_by_tag(entries, THUMBNAIL_LENGTH), endian)
    if offset is None or length is None:
        return 0
    return offset + length


def raw_entry_by_tag(
    entries: tuple[RawTiffEntry, ...],
    tag_id: int,
) -> RawTiffEntry | None:
    for entry in entries:
        if entry.tag_id == tag_id:
            return entry
    return None


def inline_u32(entry: RawTiffEntry | None, endian: Endian) -> int | None:
    if entry is None or entry.field_type != TIFF_TYPE_LONG or entry.count != 1:
        return None
    if len(entry.raw_value) != 4:
        return None
    return int.from_bytes(entry.raw_value, endian)


def byte_order_marker(endian: Endian) -> bytes:
    if endian == "little":
        return b"II"
    return b"MM"
