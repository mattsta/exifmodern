"""MPF APP2 reader for currently proven ExifTool parity slices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.jpeg.container import exiftool_binary_summary
from exifmodern.json_types import JsonObject

type ByteOrder = Literal["little", "big"]
type MpfGroupName = str
type MpfGroups = dict[MpfGroupName, JsonObject]

MPF_PREFIX = b"MPF\x00"
TIFF_MAGIC = 42
TIFF_HEADER_SIZE = 8
IFD_ENTRY_SIZE = 12
MP_IMAGE_ENTRY_SIZE = 16

MPF_VERSION_TAG = 0xB000
NUMBER_OF_IMAGES_TAG = 0xB001
MP_IMAGE_LIST_TAG = 0xB002

TIFF_TYPE_UNDEFINED = 7
TIFF_TYPE_LONG = 4

MP_IMAGE_FORMATS = {
    0: "JPEG",
}
MP_IMAGE_TYPES = {
    0x000000: "Undefined",
    0x010001: "Large Thumbnail (VGA equivalent)",
    0x010002: "Large Thumbnail (full HD equivalent)",
    0x010003: "Large Thumbnail (4K equivalent)",
    0x010004: "Large Thumbnail (8K equivalent)",
    0x010005: "Large Thumbnail (16K equivalent)",
    0x020001: "Multi-frame Panorama",
    0x020002: "Multi-frame Disparity",
    0x020003: "Multi-angle",
    0x030000: "Baseline MP Primary Image",
    0x040000: "Original Preservation Image",
    0x050000: "Gain Map Image",
}
MP_IMAGE_FLAG_BITS = (
    (2, "Representative image"),
    (3, "Dependent child image"),
    (4, "Dependent parent image"),
)


@dataclass(frozen=True)
class TiffEntry:
    tag_id: int
    value_type: int
    count: int
    value_or_offset: bytes


@dataclass(frozen=True)
class MpfTiff:
    data: bytes
    byte_order: ByteOrder
    tiff_file_offset: int


@dataclass(frozen=True)
class MpImageValues:
    flags: str
    image_format: str
    image_type: str
    image_type_code: int
    image_length: int
    image_start: int
    dependent_image_1_entry_number: int
    dependent_image_2_entry_number: int


def parse_mpf_groups(payload: bytes, tiff_file_offset: int) -> MpfGroups:
    tiff = parse_mpf_tiff(payload, tiff_file_offset)
    entries = read_ifd_entries(tiff)
    mpf0: JsonObject = {}
    image_list_offset = 0
    image_list_size = 0

    for entry in entries:
        if entry.tag_id == MPF_VERSION_TAG:
            mpf0["MPFVersion"] = read_inline_ascii(entry)
        elif entry.tag_id == NUMBER_OF_IMAGES_TAG:
            mpf0["NumberOfImages"] = read_long_entry(tiff, entry)
        elif entry.tag_id == MP_IMAGE_LIST_TAG:
            image_list_offset = read_entry_offset(tiff, entry)
            image_list_size = entry.count

    if not mpf0:
        raise ValueError("No MPF0 tags found in MPF APP2 payload")

    groups: MpfGroups = {"MPF0": mpf0}
    if image_list_offset and image_list_size:
        add_mp_image_groups(groups, tiff, image_list_offset, image_list_size)
    return groups


def parse_mpf_tiff(payload: bytes, tiff_file_offset: int) -> MpfTiff:
    if not payload.startswith(MPF_PREFIX):
        raise ValueError("Invalid MPF APP2 payload prefix")
    data = payload[len(MPF_PREFIX) :]
    if len(data) < TIFF_HEADER_SIZE:
        raise ValueError("Truncated MPF TIFF header")
    marker = data[:2]
    if marker == b"II":
        byte_order: ByteOrder = "little"
    elif marker == b"MM":
        byte_order = "big"
    else:
        raise ValueError("Invalid MPF TIFF byte order")
    if read_uint(data, 2, 2, byte_order) != TIFF_MAGIC:
        raise ValueError("Invalid MPF TIFF magic")
    return MpfTiff(data=data, byte_order=byte_order, tiff_file_offset=tiff_file_offset)


def read_ifd_entries(tiff: MpfTiff) -> list[TiffEntry]:
    first_ifd_offset = read_uint(tiff.data, 4, 4, tiff.byte_order)
    if first_ifd_offset + 2 > len(tiff.data):
        raise ValueError("Truncated MPF IFD entry count")
    entry_count = read_uint(tiff.data, first_ifd_offset, 2, tiff.byte_order)
    entries: list[TiffEntry] = []
    entries_offset = first_ifd_offset + 2
    for index in range(entry_count):
        offset = entries_offset + index * IFD_ENTRY_SIZE
        if offset + IFD_ENTRY_SIZE > len(tiff.data):
            raise ValueError("Truncated MPF IFD entry")
        entries.append(
            TiffEntry(
                tag_id=read_uint(tiff.data, offset, 2, tiff.byte_order),
                value_type=read_uint(tiff.data, offset + 2, 2, tiff.byte_order),
                count=read_uint(tiff.data, offset + 4, 4, tiff.byte_order),
                value_or_offset=tiff.data[offset + 8 : offset + 12],
            )
        )
    return entries


def read_inline_ascii(entry: TiffEntry) -> str:
    if entry.value_type != TIFF_TYPE_UNDEFINED:
        return ""
    return entry.value_or_offset[: entry.count].decode("latin-1", errors="replace")


def read_long_entry(tiff: MpfTiff, entry: TiffEntry) -> int:
    if entry.value_type != TIFF_TYPE_LONG or entry.count != 1:
        return 0
    return int.from_bytes(entry.value_or_offset, tiff.byte_order)


def read_entry_offset(tiff: MpfTiff, entry: TiffEntry) -> int:
    return int.from_bytes(entry.value_or_offset, tiff.byte_order)


def add_mp_image_groups(
    groups: MpfGroups,
    tiff: MpfTiff,
    image_list_offset: int,
    image_list_size: int,
) -> None:
    entry_count = image_list_size // MP_IMAGE_ENTRY_SIZE
    preview_recorded = False
    for index in range(entry_count):
        offset = image_list_offset + index * MP_IMAGE_ENTRY_SIZE
        if offset + MP_IMAGE_ENTRY_SIZE > len(tiff.data):
            raise ValueError("Truncated MPF MPImage entry")
        values = read_mp_image_values(tiff, tiff.data[offset : offset + MP_IMAGE_ENTRY_SIZE])
        group_name = mp_image_group_name(index + 1)
        groups[group_name] = mp_image_tag_map(values)
        if not preview_recorded and is_large_thumbnail(values.image_type_code):
            groups[group_name]["PreviewImage"] = exiftool_binary_summary(values.image_length)
            preview_recorded = True


def read_mp_image_values(tiff: MpfTiff, entry: bytes) -> MpImageValues:
    attributes = read_uint(entry, 0, 4, tiff.byte_order)
    image_type_code = attributes & 0x00FFFFFF
    raw_image_start = read_uint(entry, 8, 4, tiff.byte_order)
    return MpImageValues(
        flags=mp_image_flags((attributes & 0xF8000000) >> 27),
        image_format=mp_image_format((attributes & 0x07000000) >> 24),
        image_type=mp_image_type(image_type_code),
        image_type_code=image_type_code,
        image_length=read_uint(entry, 4, 4, tiff.byte_order),
        image_start=mp_image_start(raw_image_start, tiff.tiff_file_offset),
        dependent_image_1_entry_number=read_uint(entry, 12, 2, tiff.byte_order),
        dependent_image_2_entry_number=read_uint(entry, 14, 2, tiff.byte_order),
    )


def mp_image_tag_map(values: MpImageValues) -> JsonObject:
    return {
        "MPImageFlags": values.flags,
        "MPImageFormat": values.image_format,
        "MPImageType": values.image_type,
        "MPImageLength": values.image_length,
        "MPImageStart": values.image_start,
        "DependentImage1EntryNumber": values.dependent_image_1_entry_number,
        "DependentImage2EntryNumber": values.dependent_image_2_entry_number,
    }


def mp_image_group_name(entry_number: int) -> MpfGroupName:
    return f"MPImage{entry_number}"


def mp_image_flags(value: int) -> str:
    labels = [label for bit, label in MP_IMAGE_FLAG_BITS if value & (1 << bit)]
    return ", ".join(labels) if labels else "(none)"


def mp_image_format(value: int) -> str:
    return MP_IMAGE_FORMATS.get(value, str(value))


def mp_image_type(value: int) -> str:
    return MP_IMAGE_TYPES.get(value, f"Unknown (0x{value:06x})")


def mp_image_start(raw_start: int, tiff_file_offset: int) -> int:
    if raw_start == 0:
        return 0
    return raw_start + tiff_file_offset


def is_large_thumbnail(image_type_code: int) -> bool:
    return image_type_code & 0x0F0000 == 0x010000


def read_mpf_image(jpeg_data: bytes, mp_image_tags: JsonObject, tag_name: str) -> bytes:
    image_start = mp_image_int(mp_image_tags, "MPImageStart")
    image_length = mp_image_int(mp_image_tags, "MPImageLength")
    if image_start <= 0 or image_length <= 0:
        raise ValueError(f"MPF {tag_name} requires non-zero MPImageStart and MPImageLength")
    end_offset = image_start + image_length
    if end_offset > len(jpeg_data):
        raise ValueError(f"MPF {tag_name} extends beyond the JPEG data")
    return jpeg_data[image_start:end_offset]


def mp_image_int(mp_image_tags: JsonObject, tag_name: str) -> int:
    value = mp_image_tags.get(tag_name)
    if isinstance(value, int):
        return value
    raise ValueError(f"MPF image payload requires integer {tag_name}")


def read_mpf_preview_image(jpeg_data: bytes, mp_image_tags: JsonObject) -> bytes:
    return read_mpf_image(jpeg_data, mp_image_tags, "PreviewImage")


def read_uint(data: bytes, offset: int, size: int, byte_order: ByteOrder) -> int:
    if offset + size > len(data):
        raise ValueError("Truncated MPF integer value")
    return int.from_bytes(data[offset : offset + size], byte_order)
