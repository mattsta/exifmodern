"""JPEG AFCP and trailing IPTC readers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.afcp.trailer_transaction_plan import (
    afcp_trailer_byte_range,
    build_afcp_trailer_transaction_plan,
)
from exifmodern.formats.iptc.reader import parse_iptc_application_record
from exifmodern.formats.jpeg.container import find_next_marker, read_jpeg_data, scan_jpeg_segments
from exifmodern.json_types import JsonObject

type ByteOrder = Literal["big", "little"]

AFCP_SIGNATURE_BIG_ENDIAN = b"AXS!"
AFCP_SIGNATURE_LITTLE_ENDIAN = b"AXS*"


@dataclass(frozen=True)
class AfcpJpegTrailerRoutingReport:
    """Package-local routing facts needed by the shared JPEG trailer layer."""

    afcp_trailer_range: tuple[int, int] | None
    afcp_iptc_payload_ranges: tuple[tuple[int, int], ...]
    generic_trailing_iptc_range: tuple[int, int] | None
    generic_trailing_iptc_range_excluded: bool
    controller_owned_group_blocker: str | None


def read_afcp_iptc_tags(path: Path) -> JsonObject:
    data = read_jpeg_data(path)
    payload = afcp_iptc_payload(data)
    if payload is None:
        raise ValueError(f"No JPEG AFCP IPTC trailer found: {path}")
    return parse_iptc_application_record(payload)


def read_trailing_iptc_tags(path: Path) -> JsonObject:
    data = read_jpeg_data(path)
    payload = trailing_iptc_payload(data)
    if payload is None:
        raise ValueError(f"No JPEG trailing IPTC data found: {path}")
    return parse_iptc_application_record(payload)


def afcp_iptc_payload(data: bytes) -> bytes | None:
    plan = build_afcp_trailer_transaction_plan(data, allow_output_emission=True)
    if plan.status == "planned":
        for entry in plan.directory_entries:
            if entry.route == "iptc_subdirectory" and entry.payload is not None:
                return entry.payload
    for header_offset in afcp_header_offsets(data):
        payload = afcp_iptc_payload_at(data, header_offset)
        if payload is not None:
            return payload
    return None


def afcp_header_offsets(data: bytes) -> list[int]:
    offsets: list[int] = []
    for signature in (AFCP_SIGNATURE_BIG_ENDIAN, AFCP_SIGNATURE_LITTLE_ENDIAN):
        position = data.find(signature)
        while position >= 0:
            offsets.append(position)
            position = data.find(signature, position + 1)
    return sorted(offsets)


def afcp_iptc_payload_at(data: bytes, header_offset: int) -> bytes | None:
    if header_offset + 12 > len(data):
        return None
    signature = data[header_offset : header_offset + 4]
    byte_order: ByteOrder = "big" if signature == AFCP_SIGNATURE_BIG_ENDIAN else "little"
    entry_count = int.from_bytes(data[header_offset + 6 : header_offset + 8], byte_order)
    directory_offset = header_offset + 12
    for index in range(entry_count):
        entry_offset = directory_offset + index * 12
        if entry_offset + 12 > len(data):
            return None
        tag = data[entry_offset : entry_offset + 4]
        size = int.from_bytes(data[entry_offset + 4 : entry_offset + 8], byte_order)
        value_offset = int.from_bytes(data[entry_offset + 8 : entry_offset + 12], byte_order)
        value_end = value_offset + size
        if tag == b"IPTC" and value_end <= len(data):
            return data[value_offset:value_end]
    return None


def afcp_iptc_payload_ranges(data: bytes) -> tuple[tuple[int, int], ...]:
    """Return AFCP directory payload ranges routed to IPTC subdirectories."""

    plan = build_afcp_trailer_transaction_plan(data, allow_output_emission=True)
    if plan.status != "planned":
        return ()
    ranges: list[tuple[int, int]] = []
    for entry in plan.directory_entries:
        if entry.route == "iptc_subdirectory" and entry.payload_range is not None:
            ranges.append(entry.payload_range)
    return tuple(ranges)


def afcp_aware_jpeg_trailer_routing_report(data: bytes) -> AfcpJpegTrailerRoutingReport:
    """Report whether generic trailing IPTC would consume AFCP-contained IPTC bytes."""

    generic_range = trailing_iptc_payload_range(data, exclude_afcp_contained=False)
    afcp_ranges = afcp_iptc_payload_ranges(data)
    excluded = generic_range is not None and _range_overlaps_any(generic_range, afcp_ranges)
    return AfcpJpegTrailerRoutingReport(
        afcp_trailer_range=afcp_trailer_byte_range(data),
        afcp_iptc_payload_ranges=afcp_ranges,
        generic_trailing_iptc_range=generic_range,
        generic_trailing_iptc_range_excluded=excluded,
        controller_owned_group_blocker=None,
    )


def trailing_iptc_payload(
    data: bytes,
    *,
    exclude_afcp_contained: bool = True,
) -> bytes | None:
    payload_range = trailing_iptc_payload_range(
        data,
        exclude_afcp_contained=exclude_afcp_contained,
    )
    if payload_range is None:
        return None
    start, end = payload_range
    return data[start:end]


def trailing_iptc_payload_range(
    data: bytes,
    *,
    exclude_afcp_contained: bool = True,
) -> tuple[int, int] | None:
    app_version_marker = b"\x1c\x02\x00\x00\x02"
    candidate_position = data.rfind(app_version_marker)
    if candidate_position < 0:
        return None
    eoi_offset = main_jpeg_eoi_offset(data)
    if eoi_offset is None:
        return None
    position = data.rfind(app_version_marker, eoi_offset + 2)
    if position < 0:
        return None
    start = position
    while position + 5 <= len(data):
        if data[position] != 0x1C:
            break
        size = int.from_bytes(data[position + 3 : position + 5], "big")
        next_position = position + 5 + size
        if next_position > len(data):
            break
        position = next_position
    if position == start:
        return None
    payload_range = (start, position)
    if exclude_afcp_contained and _range_overlaps_any(
        payload_range,
        afcp_iptc_payload_ranges(data),
    ):
        return None
    return payload_range


def main_jpeg_eoi_offset(data: bytes) -> int | None:
    segments = scan_jpeg_segments(data)
    if not segments:
        return None
    scan_marker_offset = find_next_marker(
        data,
        segments[-1].payload_offset + segments[-1].payload_length,
    )
    if scan_marker_offset is None or data[scan_marker_offset + 1] != 0xDA:
        return None
    scan_length_offset = scan_marker_offset + 2
    if scan_length_offset + 2 > len(data):
        return None
    scan_length = int.from_bytes(data[scan_length_offset : scan_length_offset + 2], "big")
    position = scan_length_offset + scan_length
    while position + 1 < len(data):
        if data[position] != 0xFF:
            position += 1
            continue
        marker = data[position + 1]
        if marker == 0x00:
            position += 2
            continue
        if marker == 0xD9:
            return position
        position += 2
    return None


def _range_overlaps_any(
    candidate: tuple[int, int],
    ranges: tuple[tuple[int, int], ...],
) -> bool:
    start, end = candidate
    return any(start < range_end and end > range_start for range_start, range_end in ranges)
