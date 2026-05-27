"""JPEG APP1 XMP packet adapter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree

from exifmodern.formats.jpeg.container import (
    read_jpeg_data,
    read_jpeg_segment_probes_from_source,
    scan_jpeg_segments,
)
from exifmodern.formats.xmp.reader import XmpGroup, parse_xmp_packet
from exifmodern.json_types import JsonObject
from exifmodern.media_source import FileMediaSource

XMP_APP1_PREFIX = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_EXTENDED_APP1_PREFIX = b"http://ns.adobe.com/xmp/extension/\x00"
_HAS_EXTENDED_XMP_RE = re.compile(rb":HasExtendedXMP\s*(?:=\s*['\"]|>)([A-Za-z0-9]{32})")


@dataclass(frozen=True)
class JpegXmpPacket:
    packet: bytes
    is_extended: bool


@dataclass(frozen=True)
class _ExtendedXmpChunk:
    guid: str
    total_size: int
    offset: int
    payload: bytes


def read_xmp_group_tags(path: Path, group: XmpGroup) -> JsonObject:
    values_by_group = read_xmp_groups(path)
    return values_by_group.get(group, {})


def read_xmp_x_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-x")


def read_xmp_xmp_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-xmp")


def read_xmp_rdf_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-rdf")


def read_xmp_aux_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-aux")


def read_xmp_acdsee_region_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-acdsee-rs")


def read_xmp_crd_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-crd")


def read_xmp_crs_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-crs")


def read_xmp_dc_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-dc")


def read_xmp_exif_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-exif")


def read_xmp_exif_ex_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-exifEX")


def read_xmp_hdrgm_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-hdrgm")


def read_xmp_ics_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-ics")


def read_xmp_iptc_core_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-iptcCore")


def read_xmp_iptc_ext_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-iptcExt")


def read_xmp_pdf_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-pdf")


def read_xmp_photoshop_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-photoshop")


def read_xmp_prism_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-prism")


def read_xmp_tiff_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-tiff")


def read_xmp_bj_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-xmpBJ")


def read_xmp_creator_atom_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-creatorAtom")


def read_xmp_dm_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-xmpDM")


def read_xmp_mm_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-xmpMM")


def read_xmp_rights_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-xmpRights")


def read_xmp_tpg_tags(path: Path) -> JsonObject:
    return read_xmp_group_tags(path, "XMP-xmpTPg")


def read_xmp_groups(path: Path) -> dict[XmpGroup, JsonObject]:
    stat = path.stat()
    groups = _read_xmp_groups_cached(str(path), stat.st_size, stat.st_mtime_ns)
    return {group: dict(values) for group, values in groups.items()}


@lru_cache(maxsize=32)
def _read_xmp_groups_cached(path_text: str, size: int, mtime_ns: int) -> dict[XmpGroup, JsonObject]:
    _ = (size, mtime_ns)
    path = Path(path_text)
    data = read_jpeg_data(path)
    packets = jpeg_xmp_packets_from_app1_segments(data)
    if not packets:
        raise ValueError(f"No JPEG XMP APP1 segment found: {path}")

    merged_groups: dict[XmpGroup, JsonObject] = {}
    for packet in packets:
        try:
            groups = parse_xmp_packet(packet.packet)
        except ElementTree.ParseError:
            if packet.is_extended:
                continue
            raise
        for group, values in groups.items():
            merged_group = merged_groups.setdefault(group, {})
            merged_group.update(values)
    if merged_groups:
        return merged_groups
    raise ValueError(f"No JPEG XMP APP1 segment found: {path}")


def jpeg_xmp_packets_from_app1_segments(data: bytes) -> tuple[JpegXmpPacket, ...]:
    """Recover standard and complete matching extended XMP APP1 packet bytes.

    ExifTool stores extended APP1 chunks by GUID and offset, then processes only
    complete chunks whose GUID matches the main packet's HasExtendedXMP value by
    default. Nonmatching or incomplete extended chunks are deliberately omitted
    here so flattened values are not treated as safely structured.
    """

    standard_packets: list[bytes] = []
    extended_chunks: dict[str, list[_ExtendedXmpChunk]] = {}
    for segment in scan_jpeg_segments(data):
        if segment.marker != 0xE1:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        _collect_jpeg_xmp_app1_payload(payload, standard_packets, extended_chunks)
    return _jpeg_xmp_packets_from_collected_payloads(standard_packets, extended_chunks)


def jpeg_xmp_packets_from_app1_file(path: Path) -> tuple[JpegXmpPacket, ...]:
    """Read JPEG APP1 XMP packets without materializing the whole JPEG file."""

    source = FileMediaSource(path)
    standard_packets: list[bytes] = []
    extended_chunks: dict[str, list[_ExtendedXmpChunk]] = {}
    for probe in read_jpeg_segment_probes_from_source(source, prefix_length=0):
        if probe.marker != 0xE1:
            continue
        payload = source.read_at(probe.payload_offset, probe.payload_length)
        _collect_jpeg_xmp_app1_payload(payload, standard_packets, extended_chunks)
    return _jpeg_xmp_packets_from_collected_payloads(standard_packets, extended_chunks)


def _collect_jpeg_xmp_app1_payload(
    payload: bytes,
    standard_packets: list[bytes],
    extended_chunks: dict[str, list[_ExtendedXmpChunk]],
) -> None:
    standard_packet = standard_xmp_packet_from_app1_payload(payload)
    if standard_packet is not None:
        standard_packets.append(standard_packet)
        return
    extended_chunk = extended_xmp_chunk_from_app1_payload(payload)
    if extended_chunk is not None:
        extended_chunks.setdefault(extended_chunk.guid, []).append(extended_chunk)


def _jpeg_xmp_packets_from_collected_payloads(
    standard_packets: list[bytes],
    extended_chunks: dict[str, list[_ExtendedXmpChunk]],
) -> tuple[JpegXmpPacket, ...]:
    packets = [JpegXmpPacket(packet=packet, is_extended=False) for packet in standard_packets]
    standard_guid = _standard_extended_xmp_guid(standard_packets)
    if standard_guid is None:
        return tuple(packets)
    assembled_packet = _assemble_extended_xmp_packet(extended_chunks.get(standard_guid, ()))
    if assembled_packet is not None:
        packets.append(JpegXmpPacket(packet=assembled_packet, is_extended=True))
    return tuple(packets)


def standard_xmp_packet_from_app1_payload(payload: bytes) -> bytes | None:
    """Return APP1 standard XMP packet bytes following ExifTool JPEG.pm dispatch.

    JPEG.pm declares APP1 ExtendedXMP before XMP and routes regular XMP when the
    payload starts with ``http`` or contains an ``<exif:`` element.  Extended XMP
    chunks need assembly with the standard packet's HasExtendedXMP GUID, so this
    adapter deliberately skips them here instead of parsing chunk headers as XML.
    """

    if payload.startswith(XMP_EXTENDED_APP1_PREFIX):
        return None
    if payload.startswith(XMP_APP1_PREFIX):
        return payload[len(XMP_APP1_PREFIX) :]
    if payload.startswith(b"http"):
        _, separator, packet = payload.partition(b"\x00")
        if separator:
            return packet
        return None
    exif_index = payload.find(b"<exif:")
    if exif_index >= 0:
        return payload[exif_index:]
    return None


def extended_xmp_chunk_from_app1_payload(payload: bytes) -> _ExtendedXmpChunk | None:
    if not payload.startswith(XMP_EXTENDED_APP1_PREFIX):
        return None
    chunk = payload[len(XMP_EXTENDED_APP1_PREFIX) :]
    if len(chunk) <= 40:
        return None
    try:
        guid = chunk[:32].decode("ascii")
    except UnicodeDecodeError:
        return None
    if not guid.isalnum():
        return None
    total_size = int.from_bytes(chunk[32:36], "big")
    offset = int.from_bytes(chunk[36:40], "big")
    chunk_payload = chunk[40:]
    if offset + len(chunk_payload) > total_size:
        return None
    return _ExtendedXmpChunk(
        guid=guid,
        total_size=total_size,
        offset=offset,
        payload=chunk_payload,
    )


def _standard_extended_xmp_guid(standard_packets: list[bytes]) -> str | None:
    for packet in reversed(standard_packets):
        match = _HAS_EXTENDED_XMP_RE.search(packet)
        if match is not None:
            return match.group(1).decode("ascii")
    return None


def _assemble_extended_xmp_packet(
    chunks: tuple[_ExtendedXmpChunk, ...] | list[_ExtendedXmpChunk],
) -> bytes | None:
    total_size: int | None = None
    chunks_by_offset: dict[int, bytes] = {}
    for chunk in chunks:
        if total_size is None:
            total_size = chunk.total_size
        elif total_size != chunk.total_size:
            return None
        chunks_by_offset[chunk.offset] = chunk.payload
    if total_size is None:
        return None

    offset = 0
    parts: list[bytes] = []
    while offset < total_size:
        payload = chunks_by_offset.get(offset)
        if not payload:
            return None
        parts.append(payload)
        offset += len(payload)
    if offset != total_size:
        return None
    return b"".join(parts)
