"""ICO/CUR directory adapters for the shared read graph contract."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance

ICO_HEADER_SIZE = 6
ICO_DIRECTORY_ENTRY_SIZE = 16
ICO_MAX_DIRECTORY_BYTES = ICO_HEADER_SIZE + 255 * ICO_DIRECTORY_ENTRY_SIZE

type IcoEvidenceId = str


@dataclass(frozen=True)
class IcoEvidenceAnchor:
    evidence_id: IcoEvidenceId
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


ICO_MAIN_TABLE_SOURCE: IcoEvidenceId = "ico.read.table.main"
ICO_ICONDIR_TABLE_SOURCE: IcoEvidenceId = "ico.read.table.icondir"
ICO_PROCESS_SOURCE: IcoEvidenceId = "ico.read.process"
ICO_DOC_NUM_SOURCE: IcoEvidenceId = "ico.read.doc-num"
ICO_DIRECTORY_ONLY_SOURCE: IcoEvidenceId = "ico.read.directory-only"
ICO_ORACLE_SOURCE: IcoEvidenceId = "ico.read.oracle-output"

ICO_READ_EVIDENCE_ANCHORS: dict[IcoEvidenceId, IcoEvidenceAnchor] = {
    ICO_MAIN_TABLE_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_MAIN_TABLE_SOURCE,
        path="lib/Image/ExifTool/ICO.pm",
        line_start=19,
        line_end=37,
        symbol="%Image::ExifTool::ICO::Main",
        evidence="ICO.pm defines ImageCount at offset 4 and the IconDir subdirectory at offset 6.",
    ),
    ICO_ICONDIR_TABLE_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_ICONDIR_TABLE_SOURCE,
        path="lib/Image/ExifTool/ICO.pm",
        line_start=39,
        line_end=75,
        symbol="%Image::ExifTool::ICO::IconDir",
        evidence=(
            "IconDir maps width/height with zero as 256, NumColors, ICO color planes and "
            "bits-per-pixel, CUR hotspots, and ImageLength."
        ),
    ),
    ICO_PROCESS_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_PROCESS_SOURCE,
        path="lib/Image/ExifTool/ICO.pm",
        line_start=86,
        line_end=100,
        symbol="ProcessICO",
        evidence=(
            "ProcessICO validates the six-byte ICO/CUR header, handles ImageCount, "
            "then reads fixed 16-byte directory entries."
        ),
    ),
    ICO_DOC_NUM_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_DOC_NUM_SOURCE,
        path="lib/Image/ExifTool/ICO.pm",
        line_start=96,
        line_end=101,
        symbol="ProcessICO IconDir DOC_NUM",
        evidence=(
            "ProcessICO assigns DOC_NUM before each IconDir HandleTag call, so "
            "directory-record tags carry TAG_EXTRA G3 family-3 document numbers."
        ),
    ),
    ICO_DIRECTORY_ONLY_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_DIRECTORY_ONLY_SOURCE,
        path="lib/Image/ExifTool/ICO.pm",
        line_start=96,
        line_end=102,
        symbol="ProcessICO directory-only processing",
        evidence=(
            "ProcessICO handles IconDir records only and returns without seeking into "
            "embedded image payloads."
        ),
    ),
    ICO_ORACLE_SOURCE: IcoEvidenceAnchor(
        evidence_id=ICO_ORACLE_SOURCE,
        path="t/ICO_2.out",
        line_start=9,
        line_end=20,
        symbol="ICO fixture scalar output",
        evidence=(
            "The ICO fixture oracle emits file type tags, ImageCount, IconDir scalars, "
            "and Composite ImageSize/Megapixels."
        ),
    ),
}

type IcoFileKind = Literal["ICO", "CUR"]


@dataclass(frozen=True)
class IcoDirectoryEntryRead:
    index: int
    directory_offset: int
    image_width: int
    image_height: int
    num_colors: int
    color_planes: int | None
    bits_per_pixel: int | None
    hotspot_x: int | None
    hotspot_y: int | None
    image_length: int
    image_offset: int


def is_ico_prefix(data: bytes) -> bool:
    """Return whether bytes satisfy ExifTool's ICO/CUR header gate."""

    return (
        len(data) >= ICO_HEADER_SIZE
        and data[0:2] == b"\x00\x00"
        and data[2:4] in {b"\x01\x00", b"\x02\x00"}
        and data[4] != 0
        and data[5] == 0
    )


def ico_directory_byte_count(header: bytes) -> int | None:
    if not is_ico_prefix(header):
        return None
    return ICO_HEADER_SIZE + header[4] * ICO_DIRECTORY_ENTRY_SIZE


def build_ico_read_graph(
    directory_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    diagnostics: list[str] = []
    if not is_ico_prefix(directory_data):
        return ReadGraph(
            schema_version=1,
            generated_at_epoch=epoch,
            source_file=source_file,
            tags=[],
            diagnostics=["ICO package-local reader status: unsupported_header"],
        )

    file_kind = _file_kind(directory_data[2])
    image_count = directory_data[4]
    expected_size = ICO_HEADER_SIZE + image_count * ICO_DIRECTORY_ENTRY_SIZE
    if len(directory_data) < expected_size:
        diagnostics.append(
            "ICO package-local reader diagnostic: truncated_directory_entry: "
            f"expected {expected_size} header/directory bytes, got {len(directory_data)}"
        )

    entries = _directory_entries(directory_data, image_count, file_kind, diagnostics)
    tags = [
        *_file_type_tags(file_kind),
        _read_tag(
            name="ImageCount",
            value=image_count,
            group="File",
            table_name="Image::ExifTool::ICO::Main",
            tag_id="4",
            evidence_id=ICO_MAIN_TABLE_SOURCE,
            source=f"ico-header:4:{image_count}",
            duplicate_ordinal=None,
        ),
    ]
    for entry in entries:
        tags.extend(_entry_tags(file_kind, entry))
        tags.extend(_composite_tags(entry))
        diagnostics.append(
            "ICO package-local reader diagnostic: embedded_image_payload_deferred: "
            f"entry {entry.index} declares payload bytes "
            f"{entry.image_offset}:{entry.image_offset + entry.image_length}; "
            "ICO.pm ProcessICO reads IconDir records only."
        )

    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _file_kind(kind_byte: int) -> IcoFileKind:
    return "ICO" if kind_byte == 1 else "CUR"


def _directory_entries(
    data: bytes,
    image_count: int,
    file_kind: IcoFileKind,
    diagnostics: list[str],
) -> tuple[IcoDirectoryEntryRead, ...]:
    entries: list[IcoDirectoryEntryRead] = []
    for index in range(image_count):
        offset = ICO_HEADER_SIZE + index * ICO_DIRECTORY_ENTRY_SIZE
        raw = data[offset : offset + ICO_DIRECTORY_ENTRY_SIZE]
        if len(raw) < ICO_DIRECTORY_ENTRY_SIZE:
            break
        color_or_hotspot_x = int.from_bytes(raw[4:6], "little")
        bpp_or_hotspot_y = int.from_bytes(raw[6:8], "little")
        entries.append(
            IcoDirectoryEntryRead(
                index=index,
                directory_offset=offset,
                image_width=_ico_dimension(raw[0]),
                image_height=_ico_dimension(raw[1]),
                num_colors=raw[2],
                color_planes=color_or_hotspot_x if file_kind == "ICO" else None,
                bits_per_pixel=bpp_or_hotspot_y if file_kind == "ICO" else None,
                hotspot_x=color_or_hotspot_x if file_kind == "CUR" else None,
                hotspot_y=bpp_or_hotspot_y if file_kind == "CUR" else None,
                image_length=int.from_bytes(raw[8:12], "little"),
                image_offset=int.from_bytes(raw[12:16], "little"),
            )
        )
    if len(entries) != image_count:
        diagnostics.append(
            "ICO package-local reader diagnostic: directory_entries_deferred: "
            f"parsed {len(entries)} of {image_count} declared entries."
        )
    return tuple(entries)


def _ico_dimension(value: int) -> int:
    return value if value != 0 else 256


def _file_type_tags(file_kind: IcoFileKind) -> tuple[ReadTag, ...]:
    extension = file_kind.lower()
    tags = [
        _read_tag(
            name="FileType",
            value=file_kind,
            group="File",
            table_name="Image::ExifTool::File",
            tag_id="FileType",
            evidence_id=ICO_ORACLE_SOURCE,
            source=f"ico-file-type:{file_kind}:FileType",
            duplicate_ordinal=None,
        ),
        _read_tag(
            name="FileTypeExtension",
            value=extension,
            group="File",
            table_name="Image::ExifTool::File",
            tag_id="FileTypeExtension",
            evidence_id=ICO_ORACLE_SOURCE,
            source=f"ico-file-type:{file_kind}:FileTypeExtension",
            duplicate_ordinal=None,
        ),
    ]
    if file_kind == "ICO":
        tags.append(
            _read_tag(
                name="MIMEType",
                value="image/x-icon",
                group="File",
                table_name="Image::ExifTool::File",
                tag_id="MIMEType",
                evidence_id=ICO_ORACLE_SOURCE,
                source=f"ico-file-type:{file_kind}:MIMEType",
                duplicate_ordinal=None,
            )
        )
    return tuple(tags)


def _entry_tags(file_kind: IcoFileKind, entry: IcoDirectoryEntryRead) -> tuple[ReadTag, ...]:
    rows: list[tuple[str, str, int | None]] = [
        ("ImageWidth", "0", entry.image_width),
        ("ImageHeight", "1", entry.image_height),
        ("NumColors", "2", entry.num_colors),
    ]
    if file_kind == "ICO":
        rows.extend(
            (
                ("ColorPlanes", "4", entry.color_planes),
                ("BitsPerPixel", "6", entry.bits_per_pixel),
            )
        )
    else:
        rows.extend(
            (
                ("HotspotX", "4", entry.hotspot_x),
                ("HotspotY", "6", entry.hotspot_y),
            )
        )
    rows.append(("ImageLength", "8", entry.image_length))
    return tuple(
        _read_tag(
            name=name,
            value=value,
            group="File",
            table_name="Image::ExifTool::ICO::IconDir",
            tag_id=tag_id,
            evidence_id=ICO_ICONDIR_TABLE_SOURCE,
            source=f"ico-icondir:{entry.directory_offset + int(tag_id)}",
            duplicate_ordinal=entry.index,
            family_3_group=str(entry.index + 1),
        )
        for name, tag_id, value in rows
        if value is not None
    )


def _composite_tags(entry: IcoDirectoryEntryRead) -> tuple[ReadTag, ...]:
    megapixels = _round_megapixels(entry.image_width * entry.image_height / 1_000_000)
    return (
        _read_tag(
            name="ImageSize",
            value=f"{entry.image_width}x{entry.image_height}",
            group="Composite",
            table_name="Image::ExifTool::Composite",
            tag_id="Exif-ImageSize",
            evidence_id=ICO_ORACLE_SOURCE,
            source=f"ico-composite:{entry.index}:ImageWidth:ImageHeight",
            duplicate_ordinal=entry.index,
        ),
        _read_tag(
            name="Megapixels",
            value=megapixels,
            group="Composite",
            table_name="Image::ExifTool::Composite",
            tag_id="Exif-Megapixels",
            evidence_id=ICO_ORACLE_SOURCE,
            source=f"ico-composite:{entry.index}:ImageWidth:ImageHeight",
            duplicate_ordinal=entry.index,
        ),
    )


def _round_megapixels(value: float) -> float:
    return round(value, 6)


def _read_tag(
    *,
    name: str,
    value: str | int | float,
    group: str,
    table_name: str,
    tag_id: str,
    evidence_id: IcoEvidenceId,
    source: str,
    duplicate_ordinal: int | None,
    family_3_group: str | None = None,
) -> ReadTag:
    anchor = ICO_READ_EVIDENCE_ANCHORS[evidence_id]
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            source=(f"{anchor.path}:{anchor.line_start}-{anchor.line_end}:{source}"),
            family_0_group=group,
            family_1_group=group,
            family_2_group=_family_2_group(group, table_name),
            family_3_group=family_3_group,
            duplicate_instance_ordinal=duplicate_ordinal,
        ),
        schema=None,
    )


def _family_2_group(group: str, table_name: str) -> str:
    if group == "File" and table_name == "Image::ExifTool::File":
        return "Other"
    return "Image"
