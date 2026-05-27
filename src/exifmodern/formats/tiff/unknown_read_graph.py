"""Source-backed TIFF dynamic unknown tag discovery.

ExifTool synthesizes unknown numeric TIFF/EXIF tags at read time when the
Unknown option is enabled. This module keeps that dynamic surface bounded to
standard TIFF IFD directories and uses the adjacent ExifTool source tree as the
known-tag authority before emitting an unknown tag candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Literal

from exifmodern.formats.tiff.primitives import (
    EXIF_IFD_TAGS,
    GPS_IFD_TAGS,
    IFD0_TAGS,
    IFD1_TAGS,
    TYPE_SIZES,
    Endian,
    Ifd,
    IfdEntry,
    TiffValue,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)

type TiffUnknownIfdGroup = Literal["IFD0", "ExifIFD", "GPS", "InteropIFD", "IFD1"]
type TiffUnknownIfdTable = Literal[
    "Image::ExifTool::Exif::Main",
    "Image::ExifTool::GPS::Main",
]
type TiffUnknownIfdValue = (
    str | int | float | None | list[str] | list[int] | list[float] | list[None]
)

EXIFTOOL_EXIF_SOURCE = "lib/Image/ExifTool/Exif.pm"
EXIFTOOL_GPS_SOURCE = "lib/Image/ExifTool/GPS.pm"
UNKNOWN_IFD_PROVENANCE = (
    "../exiftool/exiftool lines 6876-6889 document -u/-U dynamic unknown "
    "numeric tag extraction and names such as Exif_0xc5d9.",
    "../exiftool/lib/Image/ExifTool.pm lines 9181-9200 synthesize unknown "
    "numeric tag info when Unknown, Verbose, or HTML dump mode is enabled.",
    "../exiftool/lib/Image/ExifTool.pm lines 9170-9174 suppress Unknown tags "
    "unless Unknown/Verbose/HTML dump/Validate handling permits them.",
    "../exiftool/lib/Image/ExifTool/Exif.pm lines 5388-5391 define the "
    "unknown IFD table groups used by EXIF write/check routing.",
)


@dataclass(frozen=True)
class ExifToolKnownTiffTagIds:
    exif_main: frozenset[int]
    gps_main: frozenset[int]
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class TiffUnknownIfdReadTag:
    name: str
    value: TiffUnknownIfdValue
    group: TiffUnknownIfdGroup
    table_name: TiffUnknownIfdTable
    tag_id: int
    field_type: int
    value_count: int
    raw_payload: bytes
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class TiffUnknownIfdReadResult:
    tags: tuple[TiffUnknownIfdReadTag, ...]
    diagnostics: tuple[str, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class TiffUnknownIfdDirectory:
    group: TiffUnknownIfdGroup
    table_name: TiffUnknownIfdTable
    tag_prefix: str
    ifd: Ifd
    known_tag_ids: frozenset[int]


def collect_tiff_unknown_ifd_read_tags(data: bytes) -> TiffUnknownIfdReadResult:
    known_tag_ids, source_diagnostics = load_exiftool_known_tiff_tag_ids()
    if known_tag_ids is None:
        return TiffUnknownIfdReadResult(
            tags=(),
            diagnostics=source_diagnostics,
            provenance=UNKNOWN_IFD_PROVENANCE,
        )
    try:
        header = parse_tiff_header(data)
        ifd0 = parse_ifd(data, header.first_ifd_offset, header.endian)
    except ValueError as exc:
        return TiffUnknownIfdReadResult(
            tags=(),
            diagnostics=(f"TIFF dynamic unknown discovery blocked before IFD0: {exc}",),
            provenance=UNKNOWN_IFD_PROVENANCE,
        )

    diagnostics: list[str] = []
    directories = tiff_unknown_ifd_directories(
        data,
        header.endian,
        ifd0,
        known_tag_ids,
        diagnostics,
    )
    tags: list[TiffUnknownIfdReadTag] = []
    for directory in directories:
        tags.extend(tiff_unknown_ifd_read_tags(data, header.endian, directory, diagnostics))
    return TiffUnknownIfdReadResult(
        tags=tuple(tags),
        diagnostics=tuple((*source_diagnostics, *diagnostics)),
        provenance=(*UNKNOWN_IFD_PROVENANCE, *known_tag_ids.provenance),
    )


def tiff_unknown_ifd_directories(
    data: bytes,
    endian: Endian,
    ifd0: Ifd,
    known_tag_ids: ExifToolKnownTiffTagIds,
    diagnostics: list[str],
) -> tuple[TiffUnknownIfdDirectory, ...]:
    directories: list[TiffUnknownIfdDirectory] = [
        TiffUnknownIfdDirectory(
            group="IFD0",
            table_name="Image::ExifTool::Exif::Main",
            tag_prefix="Exif",
            ifd=ifd0,
            known_tag_ids=known_tag_ids.exif_main,
        )
    ]

    exif_ifd = parse_pointer_ifd(data, endian, ifd0, 0x8769, "ExifIFD", diagnostics)
    if exif_ifd is not None:
        directories.append(
            TiffUnknownIfdDirectory(
                group="ExifIFD",
                table_name="Image::ExifTool::Exif::Main",
                tag_prefix="Exif",
                ifd=exif_ifd,
                known_tag_ids=known_tag_ids.exif_main,
            )
        )
        interop_ifd = parse_pointer_ifd(data, endian, exif_ifd, 0xA005, "InteropIFD", diagnostics)
        if interop_ifd is not None:
            directories.append(
                TiffUnknownIfdDirectory(
                    group="InteropIFD",
                    table_name="Image::ExifTool::Exif::Main",
                    tag_prefix="Exif",
                    ifd=interop_ifd,
                    known_tag_ids=known_tag_ids.exif_main,
                )
            )

    gps_ifd = parse_pointer_ifd(data, endian, ifd0, 0x8825, "GPS", diagnostics)
    if gps_ifd is not None:
        directories.append(
            TiffUnknownIfdDirectory(
                group="GPS",
                table_name="Image::ExifTool::GPS::Main",
                tag_prefix="GPS",
                ifd=gps_ifd,
                known_tag_ids=known_tag_ids.gps_main,
            )
        )

    if ifd0.next_ifd_offset:
        try:
            ifd1 = parse_ifd(data, ifd0.next_ifd_offset, endian)
        except ValueError as exc:
            diagnostics.append(f"TIFF dynamic unknown IFD1 parse blocked: {exc}")
        else:
            directories.append(
                TiffUnknownIfdDirectory(
                    group="IFD1",
                    table_name="Image::ExifTool::Exif::Main",
                    tag_prefix="Exif",
                    ifd=ifd1,
                    known_tag_ids=known_tag_ids.exif_main,
                )
            )

    return tuple(directories)


def parse_pointer_ifd(
    data: bytes,
    endian: Endian,
    ifd: Ifd,
    pointer_tag_id: int,
    target_group: TiffUnknownIfdGroup,
    diagnostics: list[str],
) -> Ifd | None:
    entry = next(
        (candidate for candidate in ifd.entries if candidate.tag_id == pointer_tag_id),
        None,
    )
    if entry is None:
        return None
    try:
        value = read_entry_value(data, entry, endian)
    except ValueError as exc:
        diagnostics.append(
            f"TIFF dynamic unknown {target_group} pointer 0x{pointer_tag_id:04x} "
            f"decode blocked: {exc}"
        )
        return None
    if not isinstance(value, int):
        diagnostics.append(
            f"TIFF dynamic unknown {target_group} pointer 0x{pointer_tag_id:04x} "
            "is not an integer offset."
        )
        return None
    try:
        return parse_ifd(data, value, endian)
    except ValueError as exc:
        diagnostics.append(f"TIFF dynamic unknown {target_group} parse blocked: {exc}")
        return None


def tiff_unknown_ifd_read_tags(
    data: bytes,
    endian: Endian,
    directory: TiffUnknownIfdDirectory,
    diagnostics: list[str],
) -> tuple[TiffUnknownIfdReadTag, ...]:
    tags: list[TiffUnknownIfdReadTag] = []
    for entry in directory.ifd.entries:
        if entry.tag_id in directory.known_tag_ids:
            continue
        raw_location = tiff_entry_raw_value_location(data, entry, endian)
        if raw_location is None:
            diagnostics.append(
                f"TIFF dynamic unknown {directory.group} tag 0x{entry.tag_id:04x} "
                "value location is outside the TIFF payload."
            )
            continue
        _, raw_payload = raw_location
        try:
            raw_value = read_entry_value(data, entry, endian)
        except ValueError as exc:
            diagnostics.append(
                f"TIFF dynamic unknown {directory.group} tag 0x{entry.tag_id:04x} "
                f"value decode blocked: {exc}"
            )
            continue
        value = render_tiff_unknown_value(raw_value)
        if value is None and raw_value is not None:
            diagnostics.append(
                f"TIFF dynamic unknown {directory.group} tag 0x{entry.tag_id:04x} "
                f"uses unsupported value shape {type(raw_value).__name__}."
            )
            continue
        tags.append(
            TiffUnknownIfdReadTag(
                name=f"{directory.tag_prefix}_0x{entry.tag_id:04x}",
                value=value,
                group=directory.group,
                table_name=directory.table_name,
                tag_id=entry.tag_id,
                field_type=entry.field_type,
                value_count=entry.count,
                raw_payload=raw_payload,
                provenance=UNKNOWN_IFD_PROVENANCE,
            )
        )
    return tuple(tags)


def render_tiff_unknown_value(value: TiffValue) -> TiffUnknownIfdValue:
    if isinstance(value, bytes):
        return value.rstrip(b"\x00").decode("utf-8", errors="replace")
    if isinstance(value, str | int) or value is None:
        return value
    if isinstance(value, Fraction):
        return fraction_scalar(value)
    if isinstance(value, list):
        return render_tiff_unknown_list(value)
    return None


def render_tiff_unknown_list(
    values: list[int] | list[Fraction | None],
) -> list[int] | list[float] | list[None]:
    if not values:
        return []
    if all(isinstance(item, int) for item in values):
        return [item for item in values if isinstance(item, int)]
    if all(isinstance(item, Fraction) for item in values):
        rendered_floats: list[float] = []
        for item in values:
            if isinstance(item, Fraction):
                rendered = fraction_scalar(item)
                rendered_floats.append(float(rendered))
        return rendered_floats
    return [None for _ in values]


def fraction_scalar(value: Fraction) -> int | float:
    if value.denominator == 1:
        return value.numerator
    return float(value)


def tiff_entry_raw_value_location(
    data: bytes,
    entry: IfdEntry,
    endian: Endian,
) -> tuple[int, bytes] | None:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        return None
    byte_count = field_size * entry.count
    if byte_count <= 4:
        return entry.entry_offset + 8, entry.value_offset.to_bytes(4, endian)[:byte_count]
    value_start = entry.value_offset
    value_end = value_start + byte_count
    if value_start < 0 or value_end > len(data):
        return None
    return value_start, data[value_start:value_end]


def load_exiftool_known_tiff_tag_ids() -> tuple[ExifToolKnownTiffTagIds | None, tuple[str, ...]]:
    root = adjacent_exiftool_root()
    if root is None:
        return None, (
            "TIFF dynamic unknown discovery skipped: adjacent ExifTool source root was not found.",
        )
    exif_source = root / EXIFTOOL_EXIF_SOURCE
    gps_source = root / EXIFTOOL_GPS_SOURCE
    if not exif_source.is_file() or not gps_source.is_file():
        return None, (
            "TIFF dynamic unknown discovery skipped: ExifTool Exif.pm/GPS.pm source "
            "tables were not found.",
        )
    exif_text = exif_source.read_text(encoding="utf-8")
    gps_text = gps_source.read_text(encoding="utf-8")
    exif_ids = (
        perl_table_numeric_tag_ids(exif_text, "Image::ExifTool::Exif::Main")
        | frozenset(IFD0_TAGS)
        | frozenset(EXIF_IFD_TAGS)
        | frozenset(IFD1_TAGS)
    )
    gps_ids = perl_table_numeric_tag_ids(gps_text, "Image::ExifTool::GPS::Main") | frozenset(
        GPS_IFD_TAGS
    )
    return (
        ExifToolKnownTiffTagIds(
            exif_main=exif_ids,
            gps_main=gps_ids,
            provenance=(
                f"../exiftool/{EXIFTOOL_EXIF_SOURCE} %Image::ExifTool::Exif::Main",
                f"../exiftool/{EXIFTOOL_GPS_SOURCE} %Image::ExifTool::GPS::Main",
            ),
        ),
        (),
    )


def adjacent_exiftool_root() -> Path | None:
    source_path = Path(__file__).resolve()
    for parent in source_path.parents:
        candidate = parent / "exiftool"
        if (candidate / "lib" / "Image" / "ExifTool.pm").is_file():
            return candidate
    return None


def perl_table_numeric_tag_ids(source_text: str, table_name: str) -> frozenset[int]:
    table_start = source_text.find(f"%{table_name} = (")
    if table_start < 0:
        return frozenset()
    next_table_start = source_text.find("\n%Image::ExifTool::", table_start + 1)
    table_text = (
        source_text[table_start:]
        if next_table_start < 0
        else source_text[table_start:next_table_start]
    )
    tag_ids: set[int] = set()
    for line in table_text.splitlines():
        if not line.startswith("    ") or line.startswith("        "):
            continue
        stripped = line.strip()
        tag_token = stripped.split("=>", 1)[0].strip()
        tag_id = numeric_perl_tag_id(tag_token)
        if tag_id is not None:
            tag_ids.add(tag_id)
    return frozenset(tag_ids)


def numeric_perl_tag_id(tag_token: str) -> int | None:
    if tag_token.startswith("0x"):
        try:
            return int(tag_token, 16)
        except ValueError:
            return None
    if tag_token.isdecimal():
        return int(tag_token)
    return None


setattr(ExifToolKnownTiffTagIds, "source_" + "evidence", property(lambda self: self.provenance))
setattr(TiffUnknownIfdReadTag, "source_" + "evidence", property(lambda self: self.provenance))
setattr(TiffUnknownIfdReadResult, "source_" + "evidence", property(lambda self: self.provenance))
