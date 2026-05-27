"""Minimal JPEG container scanning for the first modern read slices."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Literal

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_BYTE,
    TIFF_TYPE_UNDEFINED,
    TYPE_SIZES,
    Endian,
    IfdEntry,
    inspect_ifd0,
    parse_ifd,
    parse_tiff_header,
    read_exif_ifd_values,
    read_gps_ifd_values,
    read_ifd0_values,
    read_ifd1_values,
    read_named_ifd_values,
)
from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.media_source import FileMediaSource

type NikonMakerNoteBridgeStatus = Literal[
    "ready",
    "missing",
    "blocked_non_nikon",
    "blocked_unsupported_entry_type",
    "blocked_truncated_value",
    "blocked_type2_tiff_header",
]
type AppleMakerNoteBridgeStatus = Literal[
    "ready",
    "missing",
    "blocked_non_apple",
    "blocked_unsupported_entry_type",
    "blocked_truncated_value",
    "blocked_unrecognized_header",
]
type JvcMakerNoteBridgeStatus = Literal[
    "ready",
    "missing",
    "blocked_non_jvc",
    "blocked_unsupported_entry_type",
    "blocked_truncated_value",
]
type CanonMakerNoteBridgeStatus = Literal[
    "ready",
    "missing",
    "blocked_non_canon",
    "blocked_unsupported_entry_type",
    "blocked_truncated_value",
]

SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}
STANDALONE_MARKERS = {0x01, *range(0xD0, 0xD8), 0xD8, 0xD9}
IFD0_PREVIEW_TAGS = {
    0x0201: "PreviewImageStart",
    0x0202: "PreviewImageLength",
}


@dataclass(frozen=True)
class JpegSegment:
    marker: int
    offset: int
    payload_offset: int
    payload_length: int

    @property
    def marker_name(self) -> str:
        if self.marker == 0xE0:
            return "APP0"
        if self.marker == 0xE1:
            return "APP1"
        if self.marker == 0xFE:
            return "COM"
        if self.marker in SOF_MARKERS:
            return f"SOF{self.marker - 0xC0}"
        return f"0xFF{self.marker:02X}"


@dataclass(frozen=True)
class JpegSegmentProbe:
    marker: int
    offset: int
    payload_offset: int
    payload_length: int
    payload_prefix: bytes


@dataclass(frozen=True)
class JpegFile:
    data: bytes
    segments: tuple[JpegSegment, ...]


@dataclass(frozen=True)
class JpegDimensions:
    width: int
    height: int
    bits_per_sample: int
    color_components: int
    sof_marker: int
    segment_offset: int
    ycbcr_subsampling: str | None


@dataclass(frozen=True)
class ExifApp1:
    segment_offset: int
    payload_offset: int
    byte_order: str
    tiff_header_offset: int
    tiff_data: bytes


@dataclass(frozen=True)
class NikonMakerNoteBridgeContext:
    byte_order: Endian
    data_pos: int
    base: int
    maker_note_tiff_offset: int
    maker_note_file_offset: int
    maker_note_length: int


@dataclass(frozen=True)
class JpegNikonMakerNoteBridgeReport:
    status: NikonMakerNoteBridgeStatus
    context: NikonMakerNoteBridgeContext | None
    raw_maker_note: bytes
    raw_main_ifd: bytes
    diagnostics: tuple[str, ...]
    source_anchors: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_json(self) -> JsonObject:
        context: JsonObject | None = None
        if self.context is not None:
            context = {
                "byte_order": self.context.byte_order,
                "data_pos": self.context.data_pos,
                "base": self.context.base,
                "maker_note_tiff_offset": self.context.maker_note_tiff_offset,
                "maker_note_file_offset": self.context.maker_note_file_offset,
                "maker_note_length": self.context.maker_note_length,
            }
        return {
            "status": self.status,
            "context": context,
            "raw_maker_note_length": len(self.raw_maker_note),
            "raw_main_ifd_length": len(self.raw_main_ifd),
            "raw_maker_note_prefix_hex": self.raw_maker_note[:32].hex(),
            "diagnostics": list(self.diagnostics),
            "source_anchors": list(self.source_anchors),
        }


@dataclass(frozen=True)
class JpegAppleMakerNoteBridgeReport:
    status: AppleMakerNoteBridgeStatus
    raw_maker_note: bytes
    diagnostics: tuple[str, ...]
    source_anchors: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_json(self) -> JsonObject:
        return {
            "status": self.status,
            "raw_maker_note_length": len(self.raw_maker_note),
            "raw_maker_note_prefix_hex": self.raw_maker_note[:32].hex(),
            "diagnostics": list(self.diagnostics),
            "source_anchors": list(self.source_anchors),
        }


@dataclass(frozen=True)
class JpegJvcMakerNoteBridgeContext:
    byte_order: Endian
    maker_note_tiff_offset: int
    maker_note_file_offset: int
    maker_note_length: int
    note_kind: Literal["exif", "text"]


@dataclass(frozen=True)
class JpegJvcMakerNoteBridgeReport:
    status: JvcMakerNoteBridgeStatus
    context: JpegJvcMakerNoteBridgeContext | None
    raw_maker_note: bytes
    diagnostics: tuple[str, ...]
    source_anchors: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_json(self) -> JsonObject:
        context: JsonObject | None = None
        if self.context is not None:
            context = {
                "byte_order": self.context.byte_order,
                "maker_note_tiff_offset": self.context.maker_note_tiff_offset,
                "maker_note_file_offset": self.context.maker_note_file_offset,
                "maker_note_length": self.context.maker_note_length,
                "note_kind": self.context.note_kind,
            }
        return {
            "status": self.status,
            "context": context,
            "raw_maker_note_length": len(self.raw_maker_note),
            "raw_maker_note_prefix_hex": self.raw_maker_note[:32].hex(),
            "diagnostics": list(self.diagnostics),
            "source_anchors": list(self.source_anchors),
        }


@dataclass(frozen=True)
class JpegCanonMakerNoteBridgeContext:
    byte_order: Endian
    maker_note_tiff_offset: int
    maker_note_file_offset: int
    maker_note_length: int


@dataclass(frozen=True)
class JpegCanonMakerNoteBridgeReport:
    status: CanonMakerNoteBridgeStatus
    context: JpegCanonMakerNoteBridgeContext | None
    raw_maker_note: bytes
    diagnostics: tuple[str, ...]
    source_anchors: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_json(self) -> JsonObject:
        context: JsonObject | None = None
        if self.context is not None:
            context = {
                "byte_order": self.context.byte_order,
                "maker_note_tiff_offset": self.context.maker_note_tiff_offset,
                "maker_note_file_offset": self.context.maker_note_file_offset,
                "maker_note_length": self.context.maker_note_length,
            }
        return {
            "status": self.status,
            "context": context,
            "raw_maker_note_length": len(self.raw_maker_note),
            "raw_maker_note_prefix_hex": self.raw_maker_note[:32].hex(),
            "diagnostics": list(self.diagnostics),
            "source_anchors": list(self.source_anchors),
        }


def read_jpeg_dimensions(path: Path) -> JpegDimensions:
    return read_jpeg_dimensions_from_source(FileMediaSource(path), path.as_posix())


def read_jpeg_dimensions_from_source(
    source: FileMediaSource,
    source_name: str | None = None,
) -> JpegDimensions:
    for probe in read_jpeg_segment_probes_from_source(source, prefix_length=16):
        if probe.marker not in SOF_MARKERS:
            continue
        payload = probe.payload_prefix
        if len(payload) < 6:
            raise ValueError(f"Truncated JPEG SOF segment at offset {probe.offset}")
        return JpegDimensions(
            width=int.from_bytes(payload[3:5], "big"),
            height=int.from_bytes(payload[1:3], "big"),
            bits_per_sample=payload[0],
            color_components=payload[5],
            sof_marker=probe.marker,
            segment_offset=probe.offset,
            ycbcr_subsampling=ycbcr_subsampling_from_sof(payload),
        )
    display_name = source_name if source_name is not None else source.path.as_posix()
    raise ValueError(f"No JPEG SOF segment found: {display_name}")


def read_jpeg_file(path: Path) -> JpegFile:
    stat = path.stat()
    return _read_jpeg_file_cached(path.as_posix(), stat.st_size, stat.st_mtime_ns)


def read_jpeg_data(path: Path) -> bytes:
    return read_jpeg_file(path).data


def read_jpeg_segment_probes(path: Path, prefix_length: int = 64) -> tuple[JpegSegmentProbe, ...]:
    return read_jpeg_segment_probes_from_source(FileMediaSource(path), prefix_length=prefix_length)


def read_jpeg_segment_probes_from_source(
    source: FileMediaSource,
    prefix_length: int = 64,
) -> tuple[JpegSegmentProbe, ...]:
    if prefix_length < 0:
        raise ValueError("JPEG segment probe prefix length must be non-negative")
    probes: list[JpegSegmentProbe] = []
    with source.open() as file:
        if file.read(2) != b"\xff\xd8":
            raise ValueError("Not a JPEG stream")
        while True:
            next_marker = _read_next_jpeg_marker_or_none(file)
            if next_marker is None:
                break
            marker_offset, marker = next_marker
            if marker in {0xDA, 0xD9}:
                break
            payload_offset = file.tell()
            if marker in STANDALONE_MARKERS:
                probes.append(
                    JpegSegmentProbe(
                        marker=marker,
                        offset=marker_offset,
                        payload_offset=payload_offset,
                        payload_length=0,
                        payload_prefix=b"",
                    )
                )
                continue
            length_bytes = file.read(2)
            if len(length_bytes) != 2:
                raise ValueError(f"Truncated JPEG segment length at offset {marker_offset}")
            segment_length = int.from_bytes(length_bytes, "big")
            if segment_length < 2:
                raise ValueError(f"Invalid JPEG segment length at offset {marker_offset}")
            payload_offset = file.tell()
            payload_length = segment_length - 2
            payload_prefix = file.read(min(payload_length, prefix_length))
            if len(payload_prefix) != min(payload_length, prefix_length):
                raise ValueError(f"Truncated JPEG segment payload at offset {marker_offset}")
            file.seek(payload_length - len(payload_prefix), 1)
            probes.append(
                JpegSegmentProbe(
                    marker=marker,
                    offset=marker_offset,
                    payload_offset=payload_offset,
                    payload_length=payload_length,
                    payload_prefix=payload_prefix,
                )
            )
    return tuple(probes)


@lru_cache(maxsize=8)
def _read_jpeg_file_cached(path: str, size: int, mtime_ns: int) -> JpegFile:
    del size, mtime_ns
    data = Path(path).read_bytes()
    return JpegFile(data=data, segments=tuple(scan_jpeg_segments(data)))


def read_exif_app1(path: Path) -> ExifApp1:
    stat = path.stat()
    return _read_exif_app1_cached(path.as_posix(), stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=16)
def _read_exif_app1_cached(path: str, size: int, mtime_ns: int) -> ExifApp1:
    del size, mtime_ns
    return _read_exif_app1_uncached(Path(path))


def _read_exif_app1_uncached(path: Path) -> ExifApp1:
    with path.open("rb") as file:
        if file.read(2) != b"\xff\xd8":
            raise ValueError("Not a JPEG stream")
        while True:
            marker_offset, marker = _read_next_jpeg_marker(file)
            if marker in {0xDA, 0xD9}:
                break
            if marker in STANDALONE_MARKERS:
                continue
            length_bytes = file.read(2)
            if len(length_bytes) != 2:
                raise ValueError(f"Truncated JPEG segment length at offset {marker_offset}")
            segment_length = int.from_bytes(length_bytes, "big")
            if segment_length < 2:
                raise ValueError(f"Invalid JPEG segment length at offset {marker_offset}")
            payload_offset = file.tell()
            payload_length = segment_length - 2
            payload = file.read(payload_length)
            if len(payload) != payload_length:
                raise ValueError(f"Truncated JPEG segment payload at offset {marker_offset}")
            if marker != 0xE1 or not payload.startswith(b"Exif\x00\x00"):
                continue
            tiff_header_offset = payload_offset + 6
            byte_order_marker = payload[6:8]
            if byte_order_marker == b"II":
                byte_order = "Little-endian (Intel, II)"
            elif byte_order_marker == b"MM":
                byte_order = "Big-endian (Motorola, MM)"
            else:
                raise ValueError(f"Invalid EXIF byte order at offset {tiff_header_offset}")
            return ExifApp1(
                segment_offset=marker_offset,
                payload_offset=payload_offset,
                byte_order=byte_order,
                tiff_header_offset=tiff_header_offset,
                tiff_data=payload[6:],
            )
    raise ValueError(f"No JPEG EXIF APP1 segment found: {path}")


def _read_next_jpeg_marker(file: BinaryIO) -> tuple[int, int]:
    marker = _read_next_jpeg_marker_or_none(file)
    if marker is None:
        raise ValueError("Truncated JPEG stream before marker")
    return marker


def _read_next_jpeg_marker_or_none(file: BinaryIO) -> tuple[int, int] | None:
    while True:
        marker_prefix = file.read(1)
        if marker_prefix == b"":
            return None
        if marker_prefix != b"\xff":
            continue
        marker_offset = file.tell() - 1
        marker_byte = file.read(1)
        while marker_byte == b"\xff":
            marker_offset = file.tell() - 1
            marker_byte = file.read(1)
        if marker_byte == b"":
            return None
        marker = marker_byte[0]
        if marker == 0x00:
            continue
        return marker_offset, marker


def read_ifd0_tags(path: Path) -> JsonObject:
    app1 = read_exif_app1(path)
    tags = read_ifd0_values(app1.tiff_data)
    preview_tags = read_ifd0_preview_values(app1.tiff_data)
    preview_start = preview_tags.get("PreviewImageStart")
    preview_length = preview_tags.get("PreviewImageLength")
    if isinstance(preview_start, int) and isinstance(preview_length, int):
        if preview_length > 0:
            tags = {
                **tags,
                "PreviewImage": exiftool_binary_summary(preview_length),
            }
        tags = {**tags, "PreviewImageStart": preview_start + app1.tiff_header_offset}
    if isinstance(preview_length, int):
        tags = {**tags, "PreviewImageLength": preview_length}
    return tags


def read_ifd0_preview_values(tiff_data: bytes) -> JsonObject:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    return read_named_ifd_values(tiff_data, ifd0, header.endian, IFD0_PREVIEW_TAGS)


def read_ifd0_preview_image(path: Path) -> bytes:
    app1 = read_exif_app1(path)
    preview_tags = read_ifd0_preview_values(app1.tiff_data)
    preview_start = preview_tags.get("PreviewImageStart")
    preview_length = preview_tags.get("PreviewImageLength")
    if not isinstance(preview_start, int) or not isinstance(preview_length, int):
        raise ValueError(f"JPEG EXIF IFD0 preview references are missing: {path}")
    if preview_length <= 0:
        raise ValueError(f"JPEG EXIF IFD0 preview has no payload: {path}")
    preview_end = preview_start + preview_length
    if preview_start < 0 or preview_end > len(app1.tiff_data):
        raise ValueError(f"JPEG EXIF IFD0 preview payload is truncated: {path}")
    return app1.tiff_data[preview_start:preview_end]


def read_ifd1_tags(path: Path) -> JsonObject:
    app1 = read_exif_app1(path)
    tags = read_ifd1_values(app1.tiff_data)
    thumbnail_offset = tags.get("ThumbnailOffset")
    thumbnail_length = tags.get("ThumbnailLength")
    if isinstance(thumbnail_offset, int) and isinstance(thumbnail_length, int):
        if thumbnail_length > 0:
            tags = {
                **tags,
                "ThumbnailImage": exiftool_binary_summary(thumbnail_length),
            }
    if isinstance(thumbnail_offset, int):
        tags = {**tags, "ThumbnailOffset": thumbnail_offset + app1.tiff_header_offset}
    return tags


def read_ifd1_thumbnail_image(path: Path) -> bytes:
    app1 = read_exif_app1(path)
    tags = read_ifd1_values(app1.tiff_data)
    thumbnail_offset = tags.get("ThumbnailOffset")
    thumbnail_length = tags.get("ThumbnailLength")
    if not isinstance(thumbnail_offset, int) or not isinstance(thumbnail_length, int):
        raise ValueError(f"JPEG EXIF IFD1 thumbnail references are missing: {path}")
    if thumbnail_length <= 0:
        raise ValueError(f"JPEG EXIF IFD1 thumbnail has no payload: {path}")
    thumbnail_end = thumbnail_offset + thumbnail_length
    if thumbnail_offset < 0 or thumbnail_end > len(app1.tiff_data):
        raise ValueError(f"JPEG EXIF IFD1 thumbnail payload is truncated: {path}")
    return app1.tiff_data[thumbnail_offset:thumbnail_end]


def read_exif_ifd_tags(path: Path) -> JsonObject:
    return read_exif_ifd_values(read_exif_app1(path).tiff_data)


def read_gps_ifd_tags(path: Path) -> JsonObject:
    return read_gps_ifd_values(read_exif_app1(path).tiff_data)


def inspect_jpeg_nikon_maker_note_bridge(path: Path) -> JpegNikonMakerNoteBridgeReport:
    app1 = read_exif_app1(path)
    return inspect_tiff_nikon_maker_note_bridge(app1.tiff_data, app1.tiff_header_offset)


def inspect_jpeg_apple_maker_note_bridge(path: Path) -> JpegAppleMakerNoteBridgeReport:
    app1 = read_exif_app1(path)
    return inspect_tiff_apple_maker_note_bridge(app1.tiff_data)


def inspect_jpeg_jvc_maker_note_bridge(path: Path) -> JpegJvcMakerNoteBridgeReport:
    app1 = read_exif_app1(path)
    return inspect_tiff_jvc_maker_note_bridge(app1.tiff_data, app1.tiff_header_offset)


def inspect_jpeg_canon_maker_note_bridge(path: Path) -> JpegCanonMakerNoteBridgeReport:
    app1 = read_exif_app1(path)
    return inspect_tiff_canon_maker_note_bridge(app1.tiff_data, app1.tiff_header_offset)


def inspect_tiff_canon_maker_note_bridge(
    tiff_data: bytes,
    tiff_header_file_offset: int = 0,
) -> JpegCanonMakerNoteBridgeReport:
    source_anchors = (
        "jpeg.makernote.exif-conditional-list",
        "jpeg.makernote.canon-route",
        "jpeg.makernote.canon-process-exif",
        "jpeg.makernote.canon-main-table",
    )
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(tiff_data, ifd0.entries, 0x010F, header.endian)
    exif_ifd_offset = tiff_long_tag_value(tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return JpegCanonMakerNoteBridgeReport(
            status="missing",
            context=None,
            raw_maker_note=b"",
            diagnostics=("IFD0 does not contain an ExifIFD pointer.",),
            source_anchors=source_anchors,
        )
    exif_ifd = parse_ifd(tiff_data, exif_ifd_offset, header.endian)
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return JpegCanonMakerNoteBridgeReport(
            status="missing",
            context=None,
            raw_maker_note=b"",
            diagnostics=("ExifIFD does not contain MakerNote tag 0x927c.",),
            source_anchors=source_anchors,
        )
    if maker_note_entry.field_type not in {TIFF_TYPE_UNDEFINED, TIFF_TYPE_BYTE}:
        return JpegCanonMakerNoteBridgeReport(
            status="blocked_unsupported_entry_type",
            context=None,
            raw_maker_note=b"",
            diagnostics=(
                f"MakerNote tag 0x927c uses unsupported TIFF field type "
                f"{maker_note_entry.field_type}.",
            ),
            source_anchors=source_anchors,
        )
    raw_location = tiff_entry_raw_value_location(tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return JpegCanonMakerNoteBridgeReport(
            status="blocked_truncated_value",
            context=None,
            raw_maker_note=b"",
            diagnostics=("MakerNote tag 0x927c value points outside the TIFF APP1 payload.",),
            source_anchors=source_anchors,
        )
    maker_note_tiff_offset, raw_maker_note = raw_location
    if make is None or not make.startswith("Canon"):
        return JpegCanonMakerNoteBridgeReport(
            status="blocked_non_canon",
            context=None,
            raw_maker_note=raw_maker_note,
            diagnostics=(
                "MakerNote tag 0x927c is present, but IFD0 Make does not select "
                "ExifTool's MakerNoteCanon route.",
            ),
            source_anchors=source_anchors,
        )
    maker_note_file_offset = tiff_header_file_offset + maker_note_tiff_offset
    return JpegCanonMakerNoteBridgeReport(
        status="ready",
        context=JpegCanonMakerNoteBridgeContext(
            byte_order=header.endian,
            maker_note_tiff_offset=maker_note_tiff_offset,
            maker_note_file_offset=maker_note_file_offset,
            maker_note_length=len(raw_maker_note),
        ),
        raw_maker_note=raw_maker_note,
        diagnostics=(
            "Canon MakerNote bridge ready: IFD0 Make selected ExifTool's "
            "MakerNoteCanon route and raw MakerNote IFD bytes were surfaced.",
        ),
        source_anchors=source_anchors,
    )


def inspect_tiff_jvc_maker_note_bridge(
    tiff_data: bytes,
    tiff_header_file_offset: int = 0,
) -> JpegJvcMakerNoteBridgeReport:
    source_anchors = (
        "jpeg.makernote.exif-conditional-list",
        "jpeg.makernote.jvc-start",
        "jpeg.makernote.jvc-text-route",
        "jpeg.makernote.jvc-main-table",
        "jpeg.makernote.jvc-text-table",
        "jpeg.makernote.jvc-process-text",
    )
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(tiff_data, ifd0.entries, 0x010F, header.endian)
    exif_ifd_offset = tiff_long_tag_value(tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return JpegJvcMakerNoteBridgeReport(
            status="missing",
            context=None,
            raw_maker_note=b"",
            diagnostics=("IFD0 does not contain an ExifIFD pointer.",),
            source_anchors=source_anchors,
        )
    exif_ifd = parse_ifd(tiff_data, exif_ifd_offset, header.endian)
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return JpegJvcMakerNoteBridgeReport(
            status="missing",
            context=None,
            raw_maker_note=b"",
            diagnostics=("ExifIFD does not contain MakerNote tag 0x927c.",),
            source_anchors=source_anchors,
        )
    if maker_note_entry.field_type not in {TIFF_TYPE_UNDEFINED, TIFF_TYPE_BYTE}:
        return JpegJvcMakerNoteBridgeReport(
            status="blocked_unsupported_entry_type",
            context=None,
            raw_maker_note=b"",
            diagnostics=(
                f"MakerNote tag 0x927c uses unsupported TIFF field type "
                f"{maker_note_entry.field_type}.",
            ),
            source_anchors=source_anchors,
        )
    raw_location = tiff_entry_raw_value_location(tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return JpegJvcMakerNoteBridgeReport(
            status="blocked_truncated_value",
            context=None,
            raw_maker_note=b"",
            diagnostics=("MakerNote tag 0x927c value points outside the TIFF APP1 payload.",),
            source_anchors=source_anchors,
        )
    maker_note_tiff_offset, raw_maker_note = raw_location
    maker_note_file_offset = tiff_header_file_offset + maker_note_tiff_offset
    if raw_maker_note.startswith(b"JVC "):
        context = JpegJvcMakerNoteBridgeContext(
            byte_order=header.endian,
            maker_note_tiff_offset=maker_note_tiff_offset,
            maker_note_file_offset=maker_note_file_offset,
            maker_note_length=len(raw_maker_note),
            note_kind="exif",
        )
        return JpegJvcMakerNoteBridgeReport(
            status="ready",
            context=context,
            raw_maker_note=raw_maker_note,
            diagnostics=(
                "JVC MakerNote bridge ready: raw MakerNote bytes with the JVC header "
                "were surfaced with the EXIF value offset required by Start=$valuePtr+4.",
            ),
            source_anchors=source_anchors,
        )
    if _is_jvc_make(make) and raw_maker_note.startswith(b"VER:"):
        context = JpegJvcMakerNoteBridgeContext(
            byte_order=header.endian,
            maker_note_tiff_offset=maker_note_tiff_offset,
            maker_note_file_offset=maker_note_file_offset,
            maker_note_length=len(raw_maker_note),
            note_kind="text",
        )
        return JpegJvcMakerNoteBridgeReport(
            status="ready",
            context=context,
            raw_maker_note=raw_maker_note,
            diagnostics=(
                "JVC MakerNote bridge ready: IFD0 Make and VER: payload selected "
                "ExifTool's MakerNoteJVCText route.",
            ),
            source_anchors=source_anchors,
        )
    return JpegJvcMakerNoteBridgeReport(
        status="blocked_non_jvc",
        context=None,
        raw_maker_note=raw_maker_note,
        diagnostics=(
            "MakerNote tag 0x927c is present, but the value does not match "
            "ExifTool's MakerNoteJVC header route or JVC/Victor VER: text route.",
        ),
        source_anchors=source_anchors,
    )


def inspect_tiff_apple_maker_note_bridge(tiff_data: bytes) -> JpegAppleMakerNoteBridgeReport:
    source_anchors = (
        "jpeg.makernote.exif-conditional-list",
        "jpeg.makernote.apple-start-base",
        "jpeg.makernote.apple-main-table",
    )
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(tiff_data, ifd0.entries, 0x010F, header.endian)
    exif_ifd_offset = tiff_long_tag_value(tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return JpegAppleMakerNoteBridgeReport(
            status="missing",
            raw_maker_note=b"",
            diagnostics=("IFD0 does not contain an ExifIFD pointer.",),
            source_anchors=source_anchors,
        )
    exif_ifd = parse_ifd(tiff_data, exif_ifd_offset, header.endian)
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return JpegAppleMakerNoteBridgeReport(
            status="missing",
            raw_maker_note=b"",
            diagnostics=("ExifIFD does not contain MakerNote tag 0x927c.",),
            source_anchors=source_anchors,
        )
    if maker_note_entry.field_type not in {TIFF_TYPE_UNDEFINED, TIFF_TYPE_BYTE}:
        return JpegAppleMakerNoteBridgeReport(
            status="blocked_unsupported_entry_type",
            raw_maker_note=b"",
            diagnostics=(
                f"MakerNote tag 0x927c uses unsupported TIFF field type "
                f"{maker_note_entry.field_type}.",
            ),
            source_anchors=source_anchors,
        )
    raw_location = tiff_entry_raw_value_location(tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return JpegAppleMakerNoteBridgeReport(
            status="blocked_truncated_value",
            raw_maker_note=b"",
            diagnostics=("MakerNote tag 0x927c value points outside the TIFF APP1 payload.",),
            source_anchors=source_anchors,
        )
    _, raw_maker_note = raw_location
    if make is None or not make.upper().startswith("APPLE"):
        return JpegAppleMakerNoteBridgeReport(
            status="blocked_non_apple",
            raw_maker_note=raw_maker_note,
            diagnostics=(
                "MakerNote tag 0x927c is present, but IFD0 Make does not select "
                "ExifTool's MakerNoteApple route.",
            ),
            source_anchors=source_anchors,
        )
    if not raw_maker_note.startswith(b"Apple iOS\x00"):
        return JpegAppleMakerNoteBridgeReport(
            status="blocked_unrecognized_header",
            raw_maker_note=raw_maker_note,
            diagnostics=(
                "Apple MakerNote tag 0x927c is present, but the value does not start "
                "with ExifTool's Apple iOS header.",
            ),
            source_anchors=source_anchors,
        )
    return JpegAppleMakerNoteBridgeReport(
        status="ready",
        raw_maker_note=raw_maker_note,
        diagnostics=(
            "Apple MakerNote bridge ready: raw MakerNote bytes with Apple iOS header "
            "were surfaced to the package-local Apple reader.",
        ),
        source_anchors=source_anchors,
    )


def inspect_tiff_nikon_maker_note_bridge(
    tiff_data: bytes,
    tiff_header_file_offset: int = 0,
) -> JpegNikonMakerNoteBridgeReport:
    source_anchors = (
        "jpeg.makernote.exif-conditional-list",
        "jpeg.makernote.exif-external-value",
        "jpeg.makernote.exif-subdirectory-handoff",
        "jpeg.makernote.nikon-type2-start-base",
        "jpeg.makernote.nikon3-headerless",
        "jpeg.makernote.nikon-prescan-exif",
        "jpeg.makernote.nikon-process-nikon",
    )
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(tiff_data, ifd0.entries, 0x010F, header.endian)
    exif_ifd_offset = tiff_long_tag_value(tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return JpegNikonMakerNoteBridgeReport(
            status="missing",
            context=None,
            raw_maker_note=b"",
            raw_main_ifd=b"",
            diagnostics=("IFD0 does not contain an ExifIFD pointer.",),
            source_anchors=source_anchors,
        )
    exif_ifd = parse_ifd(tiff_data, exif_ifd_offset, header.endian)
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return JpegNikonMakerNoteBridgeReport(
            status="missing",
            context=None,
            raw_maker_note=b"",
            raw_main_ifd=b"",
            diagnostics=("ExifIFD does not contain MakerNote tag 0x927c.",),
            source_anchors=source_anchors,
        )
    if maker_note_entry.field_type not in {TIFF_TYPE_UNDEFINED, TIFF_TYPE_BYTE}:
        return JpegNikonMakerNoteBridgeReport(
            status="blocked_unsupported_entry_type",
            context=None,
            raw_maker_note=b"",
            raw_main_ifd=b"",
            diagnostics=(
                f"MakerNote tag 0x927c uses unsupported TIFF field type "
                f"{maker_note_entry.field_type}.",
            ),
            source_anchors=source_anchors,
        )
    raw_location = tiff_entry_raw_value_location(tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return JpegNikonMakerNoteBridgeReport(
            status="blocked_truncated_value",
            context=None,
            raw_maker_note=b"",
            raw_main_ifd=b"",
            diagnostics=("MakerNote tag 0x927c value points outside the TIFF APP1 payload.",),
            source_anchors=source_anchors,
        )
    maker_note_tiff_offset, raw_maker_note = raw_location
    maker_note_file_offset = tiff_header_file_offset + maker_note_tiff_offset
    if raw_maker_note.startswith(b"Nikon\x00\x02"):
        type2_header = parse_nikon_type2_tiff_header(raw_maker_note)
        if type2_header is None:
            return JpegNikonMakerNoteBridgeReport(
                status="blocked_type2_tiff_header",
                context=None,
                raw_maker_note=raw_maker_note,
                raw_main_ifd=b"",
                diagnostics=(
                    "Nikon Type2 MakerNote has the Nikon signature but not the "
                    "source-backed TIFF header and first-IFD offset at MakerNote+0x0a.",
                ),
                source_anchors=source_anchors,
            )
        type2_byte_order = type2_header
        start_offset = 18
        base = maker_note_tiff_offset + start_offset - 8
        context = NikonMakerNoteBridgeContext(
            byte_order=type2_byte_order,
            data_pos=8,
            base=base,
            maker_note_tiff_offset=maker_note_tiff_offset,
            maker_note_file_offset=maker_note_file_offset,
            maker_note_length=len(raw_maker_note),
        )
        return JpegNikonMakerNoteBridgeReport(
            status="ready",
            context=context,
            raw_maker_note=raw_maker_note,
            raw_main_ifd=raw_maker_note[start_offset:],
            diagnostics=(
                "Nikon Type2 MakerNote uses ExifTool Start=$valuePtr+18 and "
                "Base=$start-8; the JPEG bridge adapted these to caller-owned "
                "Main IFD bytes with base-relative DataPos for in-buffer value reads.",
            ),
            source_anchors=source_anchors,
        )
    if make is None or not make.upper().startswith("NIKON"):
        return JpegNikonMakerNoteBridgeReport(
            status="blocked_non_nikon",
            context=None,
            raw_maker_note=raw_maker_note,
            raw_main_ifd=b"",
            diagnostics=(
                "MakerNote tag 0x927c is present, but IFD0 Make does not select "
                "ExifTool's headerless MakerNoteNikon3 route.",
            ),
            source_anchors=source_anchors,
        )
    context = NikonMakerNoteBridgeContext(
        byte_order=header.endian,
        data_pos=maker_note_tiff_offset,
        base=0,
        maker_note_tiff_offset=maker_note_tiff_offset,
        maker_note_file_offset=maker_note_file_offset,
        maker_note_length=len(raw_maker_note),
    )
    return JpegNikonMakerNoteBridgeReport(
        status="ready",
        context=context,
        raw_maker_note=raw_maker_note,
        raw_main_ifd=raw_maker_note,
        diagnostics=(),
        source_anchors=source_anchors,
    )


def parse_nikon_type2_tiff_header(raw_maker_note: bytes) -> Endian | None:
    if len(raw_maker_note) < 18:
        return None
    type2_tiff_header = raw_maker_note[10:]
    try:
        header = parse_tiff_header(type2_tiff_header)
    except ValueError:
        return None
    if header.first_ifd_offset != 8:
        return None
    if len(raw_maker_note) < 18 + 2:
        return None
    return header.endian


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


def tiff_long_tag_value(
    data: bytes,
    entries: list[IfdEntry],
    tag_id: int,
    endian: Endian,
) -> int | None:
    entry = next((candidate for candidate in entries if candidate.tag_id == tag_id), None)
    if entry is None:
        return None
    raw_location = tiff_entry_raw_value_location(data, entry, endian)
    if raw_location is None:
        return None
    _, raw = raw_location
    if len(raw) != 4:
        return None
    return int.from_bytes(raw, endian)


def tiff_ascii_tag_value(
    data: bytes,
    entries: list[IfdEntry],
    tag_id: int,
    endian: Endian,
) -> str | None:
    entry = next((candidate for candidate in entries if candidate.tag_id == tag_id), None)
    if entry is None:
        return None
    raw_location = tiff_entry_raw_value_location(data, entry, endian)
    if raw_location is None:
        return None
    _, raw = raw_location
    return raw.rstrip(b"\x00").decode("ascii", errors="replace")


def _is_jvc_make(make: str | None) -> bool:
    if make is None:
        return False
    normalized = make.strip()
    return normalized.startswith("JVC") or normalized.startswith("Victor")


def exiftool_binary_summary(size_bytes: int) -> str:
    return f"(Binary data {size_bytes} bytes, use -b option to extract)"


def ycbcr_subsampling_from_sof(payload: bytes) -> str | None:
    if len(payload) < 15 or payload[5] != 3:
        return None
    first_component_sampling = payload[7]
    horizontal = first_component_sampling >> 4
    vertical = first_component_sampling & 0x0F
    return ycbcr_subsampling_print(horizontal, vertical)


def ycbcr_subsampling_print(horizontal: int, vertical: int) -> str | None:
    if horizontal == 1 and vertical == 1:
        return "YCbCr4:4:4 (1 1)"
    if horizontal == 2 and vertical == 1:
        return "YCbCr4:2:2 (2 1)"
    if horizontal == 2 and vertical == 2:
        return "YCbCr4:2:0 (2 2)"
    if horizontal == 4 and vertical == 1:
        return "YCbCr4:1:1 (4 1)"
    return None


def build_jpeg_inspection(path: Path) -> JsonObject:
    from exifmodern.formats.jpeg.app_segments.registry import JPEG_APP_SEGMENT_READERS

    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    segments = jpeg_file.segments
    dimensions: JsonObject | None = None
    try:
        raw_dimensions = read_jpeg_dimensions(path)
        dimensions = {
            "width": raw_dimensions.width,
            "height": raw_dimensions.height,
            "bits_per_sample": raw_dimensions.bits_per_sample,
            "color_components": raw_dimensions.color_components,
            "sof_marker": raw_dimensions.sof_marker,
            "segment_offset": raw_dimensions.segment_offset,
            "ycbcr_subsampling": raw_dimensions.ycbcr_subsampling,
        }
    except ValueError:
        dimensions = None
    exif_app1: JsonObject | None = None
    exif_ifd0: JsonObject | None = None
    app_segment_values: JsonObject = {}
    for reader in JPEG_APP_SEGMENT_READERS:
        try:
            app_segment_values[reader.inspection_key] = reader.read(path)
        except ValueError:
            app_segment_values[reader.inspection_key] = None
    try:
        app1 = read_exif_app1(path)
        exif_app1 = {
            "segment_offset": app1.segment_offset,
            "payload_offset": app1.payload_offset,
            "byte_order": app1.byte_order,
            "tiff_header_offset": app1.tiff_header_offset,
            "tiff_length": len(app1.tiff_data),
        }
        exif_ifd0 = inspect_ifd0(app1.tiff_data)
    except ValueError:
        exif_app1 = None
        exif_ifd0 = None
    try:
        nikon_maker_note_bridge: JsonObject | None = inspect_jpeg_nikon_maker_note_bridge(
            path
        ).to_json()
    except ValueError:
        nikon_maker_note_bridge = None
    try:
        jvc_maker_note_bridge: JsonObject | None = inspect_jpeg_jvc_maker_note_bridge(
            path
        ).to_json()
    except ValueError:
        jvc_maker_note_bridge = None
    segment_payloads: JsonArray = [jpeg_segment_inspection(data, segment) for segment in segments]
    return {
        "schema_version": 1,
        "generated_at_epoch": int(time.time()),
        "path": str(path),
        "size_bytes": len(data),
        "is_jpeg": data.startswith(b"\xff\xd8"),
        "dimensions": dimensions,
        **app_segment_values,
        "exif_app1": exif_app1,
        "exif_ifd0": exif_ifd0,
        "jvc_maker_note_bridge": jvc_maker_note_bridge,
        "nikon_maker_note_bridge": nikon_maker_note_bridge,
        "segments": segment_payloads,
    }


def jpeg_segment_inspection(data: bytes, segment: JpegSegment) -> JsonObject:
    payload_prefix = data[
        segment.payload_offset : segment.payload_offset + min(segment.payload_length, 96)
    ]
    return {
        "marker": f"0xFF{segment.marker:02X}",
        "marker_name": segment.marker_name,
        "offset": segment.offset,
        "payload_offset": segment.payload_offset,
        "payload_length": segment.payload_length,
        "payload_prefix_hex": payload_prefix.hex(),
        "payload_prefix_text": payload_prefix.decode("utf-8", errors="replace"),
    }


def write_jpeg_inspection(path: Path, output: Path | None) -> None:
    payload = json.dumps(build_jpeg_inspection(path), indent=2, sort_keys=True) + "\n"
    if output is None:
        print(payload, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")


def scan_jpeg_segments(data: bytes) -> list[JpegSegment]:
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Not a JPEG stream")

    segments: list[JpegSegment] = []
    offset = 2
    while offset < len(data):
        marker_offset = find_next_marker(data, offset)
        if marker_offset is None:
            break
        marker = data[marker_offset + 1]
        offset = marker_offset + 2

        if marker == 0xDA:
            break
        if marker in STANDALONE_MARKERS:
            segments.append(
                JpegSegment(
                    marker=marker,
                    offset=marker_offset,
                    payload_offset=offset,
                    payload_length=0,
                )
            )
            continue
        if offset + 2 > len(data):
            raise ValueError(f"Truncated JPEG segment length at offset {marker_offset}")

        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2:
            raise ValueError(f"Invalid JPEG segment length at offset {marker_offset}")
        payload_offset = offset + 2
        payload_length = segment_length - 2
        segment_end = payload_offset + payload_length
        if segment_end > len(data):
            raise ValueError(f"Truncated JPEG segment payload at offset {marker_offset}")

        segments.append(
            JpegSegment(
                marker=marker,
                offset=marker_offset,
                payload_offset=payload_offset,
                payload_length=payload_length,
            )
        )
        offset = segment_end

    return segments


def find_next_marker(data: bytes, offset: int) -> int | None:
    cursor = offset
    while cursor + 1 < len(data):
        if data[cursor] != 0xFF:
            cursor += 1
            continue
        while cursor + 1 < len(data) and data[cursor + 1] == 0xFF:
            cursor += 1
        if cursor + 1 >= len(data):
            return None
        if data[cursor + 1] == 0x00:
            cursor += 2
            continue
        return cursor
    return None
