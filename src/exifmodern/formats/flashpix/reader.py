"""FlashPix APP2 FPXR reader."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.jpeg.container import exiftool_binary_summary
from exifmodern.json_types import JsonArray, JsonObject, JsonValue

CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FPXR_PREFIX = b"FPXR\x00"
FPXR_HEADER_SIZE = 13
FPXR_CONTENTS_LIST_TYPE = 1
FPXR_STREAM_DATA_TYPE = 2
FPXR_SCREEN_NAIL_HEADER_SIZE = 0x1C
WINDOWS_FILETIME_UNIX_EPOCH_SECONDS = 11_644_473_600
CFB_HEADER_SIZE = 512
FREE_SECTOR = 0xFFFFFFFF
END_OF_CHAIN = 0xFFFFFFFE
DIF_SECTOR = 0xFFFFFFFC
FAT_SECTOR = 0xFFFFFFFD
MAX_CFB_SECTORS_PER_CHAIN = 4096
MAX_CFB_STREAM_BYTES = 16 * 1024 * 1024

FLASHPIX_EXTENSION_TAGS = {
    0x0001: "ExtensionName",
    0x0002: "ExtensionClassID",
    0x0003: "ExtensionPersistence",
    0x0004: "ExtensionCreateDate",
    0x0005: "ExtensionModifyDate",
    0x0006: "CreatingApplication",
    0x0007: "ExtensionDescription",
    0x1000: "Storage-StreamPathname",
}

FLASHPIX_CODE_PAGES = {
    10000: "Mac Roman (Western European)",
    1252: "Windows Latin 1 (Western European)",
    1200: "Unicode UTF-16, little endian",
}

FLASHPIX_EXTENSION_PERSISTENCE = {
    0: "Always Valid",
    1: "Invalidated By Modification",
    2: "Potentially Invalidated By Modification",
}

SUMMARY_INFO_TAGS: dict[int | str, str] = {
    0x01: "CodePage",
    0x02: "Title",
    0x03: "Subject",
    0x04: "Author",
    0x05: "Keywords",
    0x06: "Comments",
    0x08: "LastModifiedBy",
    0x09: "RevisionNumber",
    0x0A: "TotalEditTime",
    0x0C: "CreateDate",
    0x0D: "ModifyDate",
    0x0F: "Words",
    0x12: "Software",
}

DOCUMENT_INFO_TAGS: dict[int | str, str] = {
    0x02: "Category",
    0x03: "PresentationTarget",
    0x04: "Bytes",
    0x06: "Paragraphs",
    0x07: "Slides",
    0x08: "Notes",
    0x09: "HiddenSlides",
    0x0A: "MMClips",
    0x0B: "ScaleCrop",
    0x0C: "HeadingPairs",
    0x0D: "TitleOfParts",
    0x0E: "Manager",
    0x0F: "Company",
    0x10: "LinksUpToDate",
    0x13: "SharedDoc",
    0x16: "HyperlinksChanged",
    0x17: "AppVersion",
    "_PID_LINKBASE": "HyperlinkBase",
    "_PID_HLINKS": "Hyperlinks",
}

DOCUMENT_BOOLEAN_TAGS = {
    "ScaleCrop",
    "LinksUpToDate",
    "SharedDoc",
    "HyperlinksChanged",
}

OLE_SIMPLE_TYPE_SIZES = {
    2: 2,
    3: 4,
    4: 4,
    5: 8,
    10: 4,
    11: 2,
    16: 1,
    17: 1,
    18: 2,
    19: 4,
    20: 8,
    21: 8,
    64: 8,
    72: 16,
}

OLE_SIGNED_TYPES = {2, 3, 10, 16, 20}
VT_VECTOR = 0x1000
VT_VARIANT = 12
VT_LPSTR = 30
VT_LPWSTR = 31
VT_FILETIME = 64
VT_BLOB = 65
VT_CF = 71
VT_CLSID = 72

FLASHPIX_PROCESS_FPX_SOURCE = "lib/Image/ExifTool/FlashPix.pm:2040-2384:ProcessFPX"
FLASHPIX_PROCESS_PROPERTIES_SOURCE = "lib/Image/ExifTool/FlashPix.pm:1688-1844:ProcessProperties"


@dataclass(frozen=True)
class FpxrContent:
    name: str
    size: int
    default: int


@dataclass(frozen=True)
class FpxrSegment:
    segment_type: int
    payload: bytes


@dataclass(frozen=True)
class CfbDirectoryEntry:
    name: str
    entry_type: int
    left: int
    right: int
    child: int
    start_sector: int
    size: int


@dataclass(frozen=True)
class FlashPixOleTag:
    name: str
    value: JsonValue | bytes
    table_name: str
    tag_id: str
    group: str
    duplicate_instance_ordinal: int | None = None


@dataclass(frozen=True)
class FlashPixOleReadResult:
    tags: tuple[FlashPixOleTag, ...]
    diagnostics: tuple[str, ...]
    file_type: str
    file_type_extension: str
    mime_type: str


class CfbDocumentReader:
    def __init__(self, path: Path, diagnostics: list[str]) -> None:
        self.path = path
        self.diagnostics = diagnostics
        self._file = path.open("rb")
        self._file_size = path.stat().st_size
        header = self._read_at(0, CFB_HEADER_SIZE)
        if len(header) != CFB_HEADER_SIZE or not header.startswith(CFB_SIGNATURE):
            raise ValueError("Invalid CFB/OLE FlashPix signature")
        if header[0x1C:0x1E] != b"\xfe\xff":
            diagnostics.append("Bad FPX property byte order mark")
        self.sector_size = 1 << read_u16(header, 0x1E)
        self.mini_sector_size = 1 << read_u16(header, 0x20)
        self.fat_sector_count = read_u32(header, 0x2C)
        self.directory_start_sector = read_u32(header, 0x30)
        self.mini_stream_cutoff = read_u32(header, 0x38)
        self.mini_fat_start_sector = read_u32(header, 0x3C)
        self.mini_fat_sector_count = read_u32(header, 0x40)
        self.dif_start_sector = read_u32(header, 0x44)
        self.dif_sector_count = read_u32(header, 0x48)
        self.header_size = max(self.sector_size, CFB_HEADER_SIZE)
        self.fat = self._load_fat(header)
        self.mini_fat = self._load_chain(self.mini_fat_start_sector, self.fat, self.sector_size)
        self.directory_stream = self._load_chain(
            self.directory_start_sector,
            self.fat,
            self.sector_size,
        )
        self.directory_entries = parse_cfb_directory(self.directory_stream, diagnostics)
        self.mini_stream = self._load_root_ministream()

    def close(self) -> None:
        self._file.close()

    def _read_at(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > self._file_size:
            return b""
        self._file.seek(offset)
        return self._file.read(size)

    def _sector_offset(self, sector: int) -> int:
        return sector * self.sector_size + self.header_size

    def _read_sector(self, sector: int) -> bytes:
        return self._read_at(self._sector_offset(sector), self.sector_size)

    def _load_fat(self, header: bytes) -> bytes:
        fat = bytearray()
        loaded = 0
        loaded += self._load_fat_sector_entries(
            header,
            0x4C,
            CFB_HEADER_SIZE,
            fat,
            self.fat_sector_count - loaded,
        )
        loaded_dif_sectors: set[int] = set()
        dif_sector = self.dif_start_sector
        dif_count = 0
        while dif_sector < END_OF_CHAIN and loaded < self.fat_sector_count:
            dif_count += 1
            if dif_count > self.dif_sector_count:
                self.diagnostics.append("Unterminated DIF FAT")
                break
            if dif_sector in loaded_dif_sectors:
                self.diagnostics.append("Cyclical reference in DIF FAT")
                break
            loaded_dif_sectors.add(dif_sector)
            dif_data = self._read_sector(dif_sector)
            if len(dif_data) != self.sector_size:
                self.diagnostics.append(f"Error reading DIF sector {dif_sector}")
                break
            loaded += self._load_fat_sector_entries(
                dif_data,
                0,
                self.sector_size - 4,
                fat,
                self.fat_sector_count - loaded,
            )
            dif_sector = read_u32(dif_data, self.sector_size - 4)
        if loaded != self.fat_sector_count:
            self.diagnostics.append(
                f"Bad number of FAT sectors (expected {self.fat_sector_count} but found {loaded})"
            )
        return bytes(fat)

    def _load_fat_sector_entries(
        self,
        data: bytes,
        start_offset: int,
        end_offset: int,
        fat: bytearray,
        remaining_fat_sectors: int,
    ) -> int:
        loaded = 0
        for offset in range(start_offset, end_offset, 4):
            sector = read_u32(data, offset)
            if sector == FREE_SECTOR:
                continue
            if sector in {END_OF_CHAIN, DIF_SECTOR, FAT_SECTOR}:
                continue
            sector_data = self._read_sector(sector)
            if len(sector_data) != self.sector_size:
                self.diagnostics.append(f"Error reading FAT from sector {sector}")
                continue
            fat.extend(sector_data)
            loaded += 1
            if loaded >= remaining_fat_sectors:
                break
        return loaded

    def _load_chain(self, start_sector: int, fat: bytes, sector_size: int) -> bytes:
        if start_sector >= END_OF_CHAIN:
            return b""
        chain = bytearray()
        sector = start_sector
        visited: set[int] = set()
        while sector < END_OF_CHAIN:
            if sector in visited:
                self.diagnostics.append("Cyclical reference in CFB FAT chain")
                break
            if len(visited) >= MAX_CFB_SECTORS_PER_CHAIN:
                self.diagnostics.append("CFB FAT chain exceeds bounded sector traversal limit")
                break
            visited.add(sector)
            if sector * 4 + 4 > len(fat):
                self.diagnostics.append("Truncated CFB FAT sector chain")
                break
            if sector_size == self.sector_size:
                data = self._read_sector(sector)
            else:
                offset = sector * sector_size
                data = self.mini_stream[offset : offset + sector_size]
            if len(data) != sector_size:
                self.diagnostics.append("Truncated CFB sector data")
                break
            chain.extend(data)
            if len(chain) > MAX_CFB_STREAM_BYTES:
                self.diagnostics.append("CFB stream exceeds bounded read limit")
                return bytes(chain[:MAX_CFB_STREAM_BYTES])
            sector = read_u32(fat, sector * 4)
        return bytes(chain)

    def _load_root_ministream(self) -> bytes:
        if not self.directory_entries:
            return b""
        root = self.directory_entries[0]
        if root.start_sector >= END_OF_CHAIN:
            return b""
        return self._load_chain(root.start_sector, self.fat, self.sector_size)[: root.size]

    def stream_data(self, entry: CfbDirectoryEntry) -> bytes:
        if entry.entry_type != 2:
            return b""
        if entry.size >= self.mini_stream_cutoff:
            data = self._load_chain(entry.start_sector, self.fat, self.sector_size)
        elif entry.size:
            data = self._load_chain(entry.start_sector, self.mini_fat, self.mini_sector_size)
        else:
            data = b""
        if entry.size > len(data):
            self.diagnostics.append(f"Truncated FlashPix/OLE stream: {entry.name}")
        return data[: entry.size]


def parse_fpxr_tags(payloads: list[bytes]) -> JsonObject:
    contents: list[FpxrContent] = []
    streams: dict[int, bytes] = {}
    for payload in payloads:
        segment = parse_fpxr_segment(payload)
        if segment.segment_type == FPXR_CONTENTS_LIST_TYPE:
            contents = parse_fpxr_contents_list(segment.payload)
        elif segment.segment_type == FPXR_STREAM_DATA_TYPE:
            index = int.from_bytes(segment.payload[7:9], "big")
            stream_offset = int.from_bytes(segment.payload[9:13], "big")
            stream_payload = segment.payload[FPXR_HEADER_SIZE:]
            existing = streams.get(index, b"")
            if existing and stream_offset < len(existing):
                stream_payload = stream_payload[len(existing) - stream_offset :]
            streams[index] = existing + stream_payload
    return flashpix_tags_from_streams(contents, streams)


def read_flashpix_ole_file(path: Path) -> FlashPixOleReadResult:
    diagnostics: list[str] = []
    reader = CfbDocumentReader(path, diagnostics)
    try:
        tags: list[FlashPixOleTag] = []
        software: str | None = None
        user_type: str | None = None
        duplicate_counts: dict[str, int] = {}
        for entry in reader.directory_entries:
            stream_name = ole_stream_name(entry.name)
            if stream_name in {"EncryptedPackage", "EncryptionInfo"}:
                diagnostics.append(
                    "Encrypted CFB/OLE package streams are detected but not decrypted"
                )
                continue
            if stream_name not in {
                "SummaryInformation",
                "DocumentSummaryInformation",
                "CompObj",
                "Current User",
            }:
                continue
            stream = reader.stream_data(entry)
            if stream_name == "SummaryInformation":
                stream_tags = parse_ole_property_set(
                    stream,
                    SUMMARY_INFO_TAGS,
                    "Image::ExifTool::FlashPix::SummaryInfo",
                    duplicate_counts,
                    diagnostics,
                    multi=False,
                )
                tags.extend(stream_tags)
                software = string_tag_value(stream_tags, "Software")
            elif stream_name == "DocumentSummaryInformation":
                tags.extend(
                    parse_ole_property_set(
                        stream,
                        DOCUMENT_INFO_TAGS,
                        "Image::ExifTool::FlashPix::DocumentInfo",
                        duplicate_counts,
                        diagnostics,
                        multi=True,
                    )
                )
            elif stream_name == "CompObj":
                user_type = read_comp_obj_user_type(stream)
            elif stream_name == "Current User":
                current_user = read_current_user(stream)
                if current_user:
                    tags.append(
                        FlashPixOleTag(
                            name="CurrentUser",
                            value=current_user,
                            table_name="Image::ExifTool::FlashPix::Main",
                            tag_id="Current User",
                            group="FlashPix",
                        )
                    )
        file_type, extension, mime_type = flashpix_ole_file_type(path, software, user_type)
        return FlashPixOleReadResult(
            tags=tuple(tags),
            diagnostics=tuple(diagnostics),
            file_type=file_type,
            file_type_extension=extension,
            mime_type=mime_type,
        )
    finally:
        reader.close()


def parse_cfb_directory(data: bytes, diagnostics: list[str]) -> tuple[CfbDirectoryEntry, ...]:
    entries: list[CfbDirectoryEntry] = []
    for offset in range(0, len(data) - 127, 128):
        entry_type = data[offset + 0x42]
        if entry_type == 0:
            continue
        if entry_type > 5:
            diagnostics.append(f"Invalid directory entry type {entry_type}")
            break
        name_length = min(read_u16(data, offset + 0x40), 64)
        raw_name = data[offset : offset + name_length]
        name = raw_name.decode("utf-16-le", errors="replace").split("\x00", 1)[0]
        entries.append(
            CfbDirectoryEntry(
                name=name,
                entry_type=entry_type,
                left=read_u32(data, offset + 0x44),
                right=read_u32(data, offset + 0x48),
                child=read_u32(data, offset + 0x4C),
                start_sector=read_u32(data, offset + 0x74),
                size=read_u32(data, offset + 0x78),
            )
        )
    return tuple(entries)


def parse_ole_property_set(
    stream: bytes,
    known_tags: dict[int | str, str],
    table_name: str,
    duplicate_counts: dict[str, int],
    diagnostics: list[str],
    *,
    multi: bool,
) -> tuple[FlashPixOleTag, ...]:
    if len(stream) < 48:
        diagnostics.append("Truncated FPX properties")
        return ()
    if stream[:2] != b"\xfe\xff":
        diagnostics.append("Bad FPX property byte order mark")
        return ()
    section_offset = read_u32(stream, 44)
    tags: list[FlashPixOleTag] = []
    sections_read = 0
    while section_offset + 8 <= len(stream) and (multi or sections_read == 0):
        section_size = read_u32(stream, section_offset)
        if section_size == 0:
            break
        section_end = min(len(stream), section_offset + section_size)
        entry_count = read_u32(stream, section_offset + 4)
        if section_offset + 8 + entry_count * 8 > section_end:
            diagnostics.append("Truncated property list")
            break
        dictionary: dict[int, str] = {}
        code_page: int | None = None
        for index in range(entry_count):
            entry_offset = section_offset + 8 + index * 8
            property_id = read_u32(stream, entry_offset)
            value_offset = read_u32(stream, entry_offset + 4)
            type_offset = section_offset + value_offset
            value_offset_absolute = type_offset + 4
            if value_offset_absolute > section_end:
                diagnostics.append("Truncated property data")
                break
            value_type = read_u32(stream, type_offset)
            if property_id == 0:
                dictionary.update(
                    read_property_dictionary(stream, value_offset_absolute, section_end)
                )
                continue
            tag_key: int | str = dictionary.get(property_id, property_id)
            tag_name = common_flashpix_property_tag_name(tag_key)
            if tag_name is None:
                tag_name = known_tags.get(tag_key)
            if tag_name is None:
                if not isinstance(tag_key, str):
                    continue
                tag_name = ole_custom_tag_name(tag_key)
            value = read_ole_property_value(
                stream,
                value_offset_absolute,
                value_type,
                section_end,
                code_page,
            )
            if tag_name == "CodePage" and isinstance(value, int):
                code_page = value
                value = FLASHPIX_CODE_PAGES.get(value, value)
            value = render_document_value(tag_name, value)
            if tag_name == "Hyperlinks" and isinstance(value, bytes):
                value = read_hyperlinks(value, code_page)
            ordinal = duplicate_counts.get(tag_name, 0)
            duplicate_counts[tag_name] = ordinal + 1
            tags.append(
                FlashPixOleTag(
                    name=tag_name,
                    value=value,
                    table_name=table_name,
                    tag_id=str(tag_key),
                    group="FlashPix",
                    duplicate_instance_ordinal=ordinal or None,
                )
            )
        sections_read += 1
        section_offset += section_size
    return tuple(tags)


def common_flashpix_property_tag_name(tag_key: int | str) -> str | None:
    if tag_key == 0x01:
        return "CodePage"
    return None


def read_property_dictionary(
    stream: bytes,
    offset: int,
    section_end: int,
) -> dict[int, str]:
    count = read_u32(stream, offset - 4)
    position = offset
    dictionary: dict[int, str] = {}
    for _ in range(count):
        if position + 8 > section_end:
            break
        property_id = read_u32(stream, position)
        byte_count = read_u32(stream, position + 4)
        raw_name = stream[position + 8 : min(position + 8 + byte_count, section_end)]
        name = raw_name.decode("latin-1", errors="replace").split("\x00", 1)[0]
        if name:
            dictionary[property_id] = name
        position += 8 + byte_count
    return dictionary


def read_ole_property_value(
    stream: bytes,
    offset: int,
    value_type: int,
    section_end: int,
    code_page: int | None,
) -> JsonValue | bytes:
    flags = value_type & 0xF000
    base_type = value_type & 0x0FFF
    if flags == VT_VECTOR:
        count = read_u32(stream, offset)
        position = offset + 4
        values: list[JsonValue] = []
        for _ in range(count):
            value, position = read_ole_scalar_value(
                stream,
                position,
                base_type,
                section_end,
                code_page,
                no_padding=True,
            )
            values.append(value if not isinstance(value, bytes) else json_scalar_text(value))
        return values
    value, _ = read_ole_scalar_value(
        stream,
        offset,
        base_type,
        section_end,
        code_page,
        no_padding=False,
    )
    return value


def read_ole_scalar_value(
    stream: bytes,
    offset: int,
    value_type: int,
    section_end: int,
    code_page: int | None,
    *,
    no_padding: bool,
) -> tuple[JsonValue | bytes, int]:
    if value_type == VT_VARIANT:
        subtype = read_u32(stream, offset)
        return read_ole_scalar_value(
            stream,
            offset + 4,
            subtype,
            section_end,
            code_page,
            no_padding=no_padding,
        )
    if value_type in {VT_LPSTR, VT_LPWSTR}:
        byte_count = read_u32(stream, offset)
        if value_type == VT_LPWSTR:
            byte_count *= 2
        raw = stream[offset + 4 : min(offset + 4 + byte_count, section_end)]
        if value_type == VT_LPWSTR:
            value = raw.decode("utf-16-le", errors="replace").split("\x00", 1)[0]
        else:
            value = decode_lpstr(raw, code_page)
        padded = byte_count if no_padding else align4(byte_count)
        return value, offset + 4 + padded
    if value_type in {VT_BLOB, VT_CF}:
        byte_count = read_u32(stream, offset)
        raw = stream[offset + 4 : min(offset + 4 + byte_count, section_end)]
        return raw, offset + 4 + align4(byte_count)
    if value_type == VT_FILETIME:
        return read_ole_filetime(stream, offset), offset + 8
    if value_type == VT_CLSID:
        return read_guid(stream, offset), offset + 16
    size = OLE_SIMPLE_TYPE_SIZES.get(value_type)
    if size is None or offset + size > section_end:
        return "", offset
    raw = stream[offset : offset + size]
    if value_type in {4, 5}:
        return "", offset + size
    scalar_value = int.from_bytes(raw, "little", signed=value_type in OLE_SIGNED_TYPES)
    if value_type == 11:
        scalar_value = 1 if scalar_value else 0
    return scalar_value, offset + size


def decode_lpstr(raw: bytes, code_page: int | None) -> str:
    if code_page == 10000:
        encoding = "mac_roman"
    elif code_page == 1200:
        return raw.decode("utf-16-le", errors="replace").split("\x00", 1)[0]
    elif code_page == 1252:
        encoding = "cp1252"
    else:
        encoding = "latin-1"
    return raw.decode(encoding, errors="replace").split("\x00", 1)[0]


def render_document_value(tag_name: str, value: JsonValue | bytes) -> JsonValue | bytes:
    if tag_name == "TotalEditTime" and isinstance(value, int | float):
        minutes = value / 60
        return f"{minutes:.1f} minutes"
    if tag_name == "HyperlinkBase" and isinstance(value, bytes):
        return value.decode("utf-16-le", errors="replace").split("\x00", 1)[0]
    if tag_name in DOCUMENT_BOOLEAN_TAGS and isinstance(value, int):
        return "Yes" if value else "No"
    if tag_name == "AppVersion" and isinstance(value, int):
        return f"{value >> 16}.{value & 0xFFFF:04d}"
    return value


def read_ole_filetime(stream: bytes, value_start: int) -> JsonValue:
    filetime_seconds = int.from_bytes(stream[value_start : value_start + 8], "little") * 1e-7
    if filetime_seconds <= 365 * 24 * 3600:
        return round(filetime_seconds, 7)
    return read_filetime(stream, value_start)


def ole_custom_tag_name(name: str) -> str:
    return "".join(character for character in name.title() if character.isalnum())


def read_hyperlinks(raw: bytes, code_page: int | None) -> JsonArray:
    if len(raw) < 4:
        return []
    count = read_u32(raw, 0)
    position = 4
    values: list[JsonValue] = []
    for _ in range(count):
        value, position = read_ole_scalar_value(
            raw,
            position,
            VT_VARIANT,
            len(raw),
            code_page,
            no_padding=False,
        )
        values.append(value if not isinstance(value, bytes) else json_scalar_text(value))
    links: JsonArray = []
    for index in range(0, len(values), 6):
        if index + 4 >= len(values):
            break
        address = json_scalar_text(values[index + 4])
        if index + 5 < len(values):
            subaddress = json_scalar_text(values[index + 5])
            if subaddress:
                address = f"{address}#{subaddress}"
        links.append(address)
    return links


def read_comp_obj_user_type(stream: bytes) -> str | None:
    if len(stream) < 0x20:
        return None
    offset = 0x1C
    byte_count = read_u32(stream, offset)
    raw = stream[offset + 4 : offset + 4 + byte_count]
    return raw.decode("latin-1", errors="replace").split("\x00", 1)[0]


def read_current_user(stream: bytes) -> str | None:
    if len(stream) < 12:
        return None
    size = read_u32(stream, 4)
    position = read_u32(stream, 8)
    byte_count = size - position - 4
    if byte_count < 0 or len(stream) < size + 8:
        return None
    return stream[8 + position : 8 + position + byte_count].decode("latin-1", errors="replace")


def flashpix_ole_file_type(
    path: Path,
    software: str | None,
    user_type: str | None,
) -> tuple[str, str, str]:
    suffix = path.suffix.lower().lstrip(".")
    if (
        suffix == "ppt"
        or (software and "PowerPoint" in software)
        or user_type == "Microsoft PowerPoint"
    ):
        return "PPT", "ppt", "application/vnd.ms-powerpoint"
    if suffix == "doc" or (software and "Word" in software):
        return "DOC", "doc", "application/msword"
    if suffix == "xls" or (software and "Excel" in software):
        return "XLS", "xls", "application/vnd.ms-excel"
    if suffix == "fpx":
        return "FPX", "fpx", "image/vnd.fpx"
    return "FPX", "fpx", "image/vnd.fpx"


def string_tag_value(tags: tuple[FlashPixOleTag, ...], name: str) -> str | None:
    for tag in tags:
        if tag.name == name and isinstance(tag.value, str):
            return tag.value
    return None


def json_scalar_text(value: JsonValue | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("latin-1", errors="replace").split("\x00", 1)[0]
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return ""
    return str(value)


def align4(value: int) -> int:
    return (value + 3) & 0xFFFFFFFC


def parse_fpxr_segment(payload: bytes) -> FpxrSegment:
    if len(payload) < FPXR_HEADER_SIZE or not payload.startswith(FPXR_PREFIX):
        raise ValueError("Invalid FlashPix FPXR segment")
    return FpxrSegment(segment_type=payload[6], payload=payload)


def parse_fpxr_contents_list(payload: bytes) -> list[FpxrContent]:
    entry_count = int.from_bytes(payload[7:9], "big")
    position = 9
    contents: list[FpxrContent] = []
    for _ in range(entry_count):
        if position + 5 > len(payload):
            raise ValueError("Truncated FlashPix FPXR contents list")
        size = int.from_bytes(payload[position : position + 4], "big")
        default = payload[position + 4]
        position += 5
        name, position = read_fpxr_stream_name(payload, position)
        if size == 0xFFFFFFFF:
            position += 16
        contents.append(FpxrContent(name=name.rsplit("/", 1)[-1], size=size, default=default))
    return contents


def read_fpxr_stream_name(payload: bytes, position: int) -> tuple[str, int]:
    end = position
    while end + 1 < len(payload):
        if payload[end : end + 2] == b"\x00\x00":
            raw_name = payload[position:end]
            return raw_name.decode("utf-16-le", errors="replace"), end + 2
        end += 2
    raise ValueError("Invalid FlashPix FPXR stream name")


def flashpix_tags_from_streams(
    contents: list[FpxrContent], streams: dict[int, bytes]
) -> JsonObject:
    tags: JsonObject = {}
    for index, content in enumerate(contents):
        stream = streams.get(index, b"")
        if len(stream) > content.size and content.size != 0xFFFFFFFF:
            stream = stream[: content.size]
        stream_name = ole_stream_name(content.name)
        if stream_name == "Extension List":
            tags.update(parse_flashpix_extension_properties(stream))
        if stream_name.startswith("Screen Nail") and len(stream) > FPXR_SCREEN_NAIL_HEADER_SIZE:
            screen_nail = stream[FPXR_SCREEN_NAIL_HEADER_SIZE:]
            tags["ScreenNail"] = exiftool_binary_summary(len(screen_nail))
            preview = screen_nail_preview(screen_nail)
            if preview is not None:
                tags["PreviewImage"] = exiftool_binary_summary(len(preview))
    return tags


def ole_stream_name(name: str) -> str:
    short_name = name.rsplit("/", 1)[-1]
    if short_name and ord(short_name[0]) < 0x20:
        return short_name[1:]
    return short_name


def screen_nail_preview(screen_nail: bytes) -> bytes | None:
    position = screen_nail.find(b"\xff\xd8\xff")
    if position < 0:
        return None
    return screen_nail[position:]


def parse_flashpix_extension_properties(stream: bytes) -> JsonObject:
    if len(stream) < 48 or stream[:2] != b"\xfe\xff":
        raise ValueError("Invalid FlashPix property stream")
    section_offset = read_u32(stream, 44)
    section_size = read_u32(stream, section_offset)
    entry_count = read_u32(stream, section_offset + 4)
    section_end = min(len(stream), section_offset + section_size)
    tags: JsonObject = {}
    for index in range(entry_count):
        entry_offset = section_offset + 8 + index * 8
        if entry_offset + 8 > section_end:
            break
        property_id = read_u32(stream, entry_offset)
        value_offset = read_u32(stream, entry_offset + 4)
        tag_name = flashpix_extension_tag_name(property_id)
        if tag_name is None:
            continue
        value_type_offset = section_offset + value_offset
        value_start = value_type_offset + 4
        if value_type_offset + 4 > section_end:
            continue
        value_type = read_u32(stream, value_type_offset)
        tags[tag_name] = flashpix_property_value(
            tag_name, value_type, stream, value_start, section_end
        )
    return tags


def flashpix_extension_tag_name(property_id: int) -> str | None:
    if property_id == 0x00000001:
        return "CodePage"
    if property_id == 0x10000000:
        return "UsedExtensionNumbers"
    extension_tag_id = property_id & 0x0000FFFF
    return FLASHPIX_EXTENSION_TAGS.get(extension_tag_id)


def flashpix_property_value(
    tag_name: str,
    value_type: int,
    stream: bytes,
    value_start: int,
    section_end: int,
) -> JsonValue:
    if value_type == 0x0002:
        value = read_u16(stream, value_start)
        if tag_name == "CodePage":
            return FLASHPIX_CODE_PAGES.get(value, value)
        return value
    if value_type == 0x1012:
        values = read_vector_u16(stream, value_start, section_end)
        return values[0] if len(values) == 1 else " ".join(str(value) for value in values)
    if value_type == 0x101F:
        text_values = read_vector_lpwstr(stream, value_start, section_end)
        if len(text_values) == 1:
            return text_values[0]
        json_values: JsonArray = [text_value for text_value in text_values]
        return json_values
    if value_type == 0x0012:
        value = read_u16(stream, value_start)
        if tag_name == "ExtensionPersistence":
            return FLASHPIX_EXTENSION_PERSISTENCE.get(value, value)
        return value
    if value_type == 0x001F:
        return read_lpwstr(stream, value_start, section_end)
    if value_type == 0x0040:
        return read_filetime(stream, value_start)
    if value_type == 0x0048:
        return read_guid(stream, value_start)
    return ""


def read_vector_u16(stream: bytes, value_start: int, section_end: int) -> list[int]:
    count = read_u32(stream, value_start)
    position = value_start + 4
    values: list[int] = []
    for _ in range(count):
        if position + 2 > section_end:
            break
        values.append(read_u16(stream, position))
        position += 2
    return values


def read_vector_lpwstr(stream: bytes, value_start: int, section_end: int) -> list[str]:
    count = read_u32(stream, value_start)
    position = value_start + 4
    values: list[str] = []
    for _ in range(count):
        value = read_lpwstr(stream, position, section_end)
        values.append(value)
        byte_count = read_u32(stream, position) * 2
        position += 4 + ((byte_count + 3) & 0xFFFFFFFC)
    return values


def read_lpwstr(stream: bytes, value_start: int, section_end: int) -> str:
    character_count = read_u32(stream, value_start)
    byte_count = character_count * 2
    raw_value = stream[value_start + 4 : min(value_start + 4 + byte_count, section_end)]
    return raw_value.decode("utf-16-le", errors="replace").split("\x00", 1)[0]


def read_filetime(stream: bytes, value_start: int) -> str:
    filetime = int.from_bytes(stream[value_start : value_start + 8], "little")
    unix_seconds = int(filetime / 10_000_000 - WINDOWS_FILETIME_UNIX_EPOCH_SECONDS)
    return time.strftime("%Y:%m:%d %H:%M:%S", time.gmtime(unix_seconds))


def read_guid(stream: bytes, value_start: int) -> str:
    raw_value = stream[value_start : value_start + 16]
    if len(raw_value) != 16:
        raise ValueError("Truncated FlashPix GUID")
    return (
        f"{int.from_bytes(raw_value[0:4], 'little'):08X}-"
        f"{int.from_bytes(raw_value[4:6], 'little'):04X}-"
        f"{int.from_bytes(raw_value[6:8], 'little'):04X}-"
        f"{raw_value[8:10].hex().upper()}-"
        f"{raw_value[10:16].hex().upper()}"
    )


def read_u16(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise ValueError(f"Truncated FlashPix 16-bit value at offset {offset}")
    return int.from_bytes(data[offset : offset + 2], "little")


def read_u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"Truncated FlashPix 32-bit value at offset {offset}")
    return int.from_bytes(data[offset : offset + 4], "little")
