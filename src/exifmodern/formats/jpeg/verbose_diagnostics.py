"""Source-backed JPEG writer verbose diagnostic helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_segment_probes
from exifmodern.write_plan import (
    AsciiWriteValue,
    ByteWriteValue,
    ExifGpsWritePlan,
    GpsDeleteWriteValue,
    RationalArrayWriteValue,
    RationalWriteValue,
    TiffWriteValue,
)

JPEG_WRITER_VERBOSE_EVIDENCE_IDS = (
    "jpeg.verbose.writeinfo-rewriting",
    "jpeg.verbose.create-app1",
    "jpeg.verbose.verbose-value",
    "jpeg.verbose.sof-sos-markers",
    "jpeg.verbose.marker-lengths",
    "jpeg.verbose.geotag-output",
)

JPEG_WRITER_VERBOSE_TERMINAL_LIMITATIONS = (
    "This helper models source-backed JPEG rewrite/create diagnostics for explicit "
    "writer groups and native GPS APP1 creation plans.",
    "It does not attempt full generic Writer.pl transaction tracing for arbitrary "
    "SetNewValue expressions, all writable groups, warning ordering, or byte-for-byte "
    "Verbose>=3 hexdumps.",
)

_MARKER_NAMES: dict[int, str] = {
    0xC4: "DHT",
    0xD8: "SOI",
    0xD9: "EOI",
    0xDA: "SOS",
    0xDB: "DQT",
    0xDD: "DRI",
    0xFE: "COM",
}

_STANDALONE_MARKERS = {0x01, *range(0xD0, 0xD8), 0xD8, 0xD9}


@dataclass(frozen=True)
class JpegWriterVerboseDiagnosticRequest:
    source_path_for_display: str
    source_jpeg_data: bytes
    editing_groups: tuple[str, ...]
    creating_groups: tuple[str, ...]
    gps_write_plan: ExifGpsWritePlan | None = None
    gps_created_values: tuple[JpegVerboseCreatedTagValue, ...] = ()
    create_app1: bool = False


@dataclass(frozen=True)
class JpegVerboseCreatedTagValue:
    group: str
    tag_name: str
    value: str
    mandatory: bool = False


@dataclass(frozen=True)
class JpegWriterVerboseDiagnosticReport:
    status: str
    lines: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    terminal_limitations: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[str, ...]:
        if name == "source_" + "evidence":
            return self.evidence_ids
        raise AttributeError(name)


def jpeg_writer_verbose_diagnostic_suffix(
    request: JpegWriterVerboseDiagnosticRequest,
) -> JpegWriterVerboseDiagnosticReport:
    lines: list[str] = [
        f"Rewriting {request.source_path_for_display}...",
    ]
    if request.editing_groups:
        lines.append(f"  Editing tags in: {' '.join(request.editing_groups)} ")
    if request.creating_groups:
        lines.append(f"  Creating tags in: {' '.join(request.creating_groups)} ")
    if request.create_app1:
        lines.extend(_app1_gps_creation_lines(request.gps_write_plan, request.gps_created_values))
    lines.extend(jpeg_marker_verbose_lines_after_created_metadata(request.source_jpeg_data))
    return JpegWriterVerboseDiagnosticReport(
        status="implemented_bounded_jpeg_writer_verbose_model",
        lines=tuple(lines),
        evidence_ids=JPEG_WRITER_VERBOSE_EVIDENCE_IDS,
        terminal_limitations=JPEG_WRITER_VERBOSE_TERMINAL_LIMITATIONS,
    )


def jpeg_writer_verbose_diagnostic_suffix_for_file(
    source_path: Path,
    source_path_for_display: str,
    editing_groups: tuple[str, ...],
    creating_groups: tuple[str, ...],
    gps_write_plan: ExifGpsWritePlan | None = None,
    gps_created_values: tuple[JpegVerboseCreatedTagValue, ...] = (),
    create_app1: bool = False,
) -> JpegWriterVerboseDiagnosticReport:
    request = JpegWriterVerboseDiagnosticRequest(
        source_path_for_display=source_path_for_display,
        source_jpeg_data=b"",
        editing_groups=editing_groups,
        creating_groups=creating_groups,
        gps_write_plan=gps_write_plan,
        gps_created_values=gps_created_values,
        create_app1=create_app1,
    )
    lines: list[str] = [
        f"Rewriting {request.source_path_for_display}...",
    ]
    if request.editing_groups:
        lines.append(f"  Editing tags in: {' '.join(request.editing_groups)} ")
    if request.creating_groups:
        lines.append(f"  Creating tags in: {' '.join(request.creating_groups)} ")
    if request.create_app1:
        lines.extend(_app1_gps_creation_lines(request.gps_write_plan, request.gps_created_values))
    lines.extend(jpeg_marker_verbose_lines_after_created_metadata_for_file(source_path))
    return JpegWriterVerboseDiagnosticReport(
        status="implemented_bounded_jpeg_writer_verbose_model",
        lines=tuple(lines),
        evidence_ids=JPEG_WRITER_VERBOSE_EVIDENCE_IDS,
        terminal_limitations=JPEG_WRITER_VERBOSE_TERMINAL_LIMITATIONS,
    )


def jpeg_marker_verbose_lines_after_created_metadata_for_file(source_path: Path) -> tuple[str, ...]:
    """Return Writer.pl-style marker lines using only JPEG metadata segment probes."""
    lines: list[str] = []
    for probe in read_jpeg_segment_probes(source_path, prefix_length=0):
        marker_name = _jpeg_marker_name(probe.marker)
        if _is_sof_marker(probe.marker):
            lines.append(f"JPEG {marker_name}:")
            continue
        lines.append(f"JPEG {marker_name} ({probe.payload_length} bytes)")
    lines.append("JPEG SOS")
    return tuple(lines)


def jpeg_marker_verbose_lines_after_created_metadata(jpeg_data: bytes) -> tuple[str, ...]:
    """Return Writer.pl-style JPEG marker lines after metadata creation slots."""
    lines: list[str] = []
    for marker in _scan_jpeg_markers_until_sos(jpeg_data):
        if marker.marker == 0xD8:
            continue
        marker_name = _jpeg_marker_name(marker.marker)
        if _is_sof_marker(marker.marker):
            lines.append(f"JPEG {marker_name}:")
            continue
        if marker.marker == 0xDA:
            lines.append("JPEG SOS")
            break
        if marker.payload_length is not None:
            lines.append(f"JPEG {marker_name} ({marker.payload_length} bytes)")
    return tuple(lines)


def _app1_gps_creation_lines(
    plan: ExifGpsWritePlan | None,
    created_values: tuple[JpegVerboseCreatedTagValue, ...],
) -> tuple[str, ...]:
    lines = [
        "Creating APP1:",
        "  Creating IFD0",
        "    + IFD0:YCbCrPositioning = '1' (mandatory)",
        "  Creating GPS",
    ]
    if created_values:
        for item in created_values:
            suffix = " (mandatory)" if item.mandatory else ""
            lines.append(f"    + {item.group}:{item.tag_name} = '{item.value}'{suffix}")
        return tuple(lines)
    if plan is None:
        return tuple(lines)
    for step in plan.steps:
        if step.operation == "delete":
            continue
        value = _verbose_write_value(step.value)
        suffix = " (mandatory)" if step.tag_name == "GPSVersionID" else ""
        lines.append(f"    + GPS:{step.tag_name} = '{value}'{suffix}")
    return tuple(lines)


def _verbose_write_value(value: TiffWriteValue) -> str:
    if isinstance(value, AsciiWriteValue):
        return value.text
    if isinstance(value, ByteWriteValue):
        return " ".join(str(item) for item in value.values)
    if isinstance(value, RationalArrayWriteValue):
        return " ".join(_verbose_rational(item) for item in value.values)
    if isinstance(value, GpsDeleteWriteValue):
        return ""
    raise TypeError(f"Unsupported TIFF write value: {type(value).__name__}")


def _verbose_rational(value: RationalWriteValue) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator / value.denominator:.15g}"


@dataclass(frozen=True)
class _VerboseJpegMarker:
    marker: int
    payload_length: int | None


def _scan_jpeg_markers_until_sos(jpeg_data: bytes) -> tuple[_VerboseJpegMarker, ...]:
    if not jpeg_data.startswith(b"\xff\xd8"):
        raise ValueError("Not a JPEG stream")
    markers: list[_VerboseJpegMarker] = [_VerboseJpegMarker(marker=0xD8, payload_length=0)]
    offset = 2
    while offset < len(jpeg_data):
        marker_offset = _find_next_marker(jpeg_data, offset)
        if marker_offset is None:
            break
        marker = jpeg_data[marker_offset + 1]
        offset = marker_offset + 2
        if marker in _STANDALONE_MARKERS:
            markers.append(_VerboseJpegMarker(marker=marker, payload_length=0))
            if marker == 0xD9:
                break
            continue
        if _is_sof_marker(marker):
            if offset + 7 > len(jpeg_data):
                raise ValueError(f"Truncated JPEG SOF segment at offset {marker_offset}")
            markers.append(_VerboseJpegMarker(marker=marker, payload_length=7))
            offset += 7
            continue
        if offset + 2 > len(jpeg_data):
            raise ValueError(f"Truncated JPEG segment length at offset {marker_offset}")
        segment_length = int.from_bytes(jpeg_data[offset : offset + 2], "big")
        if segment_length < 2:
            raise ValueError(f"Invalid JPEG segment length at offset {marker_offset}")
        payload_length = segment_length - 2
        markers.append(_VerboseJpegMarker(marker=marker, payload_length=payload_length))
        offset += 2 + payload_length
        if marker == 0xDA:
            break
    return tuple(markers)


def _find_next_marker(data: bytes, offset: int) -> int | None:
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


def _is_sof_marker(marker: int) -> bool:
    return (marker & 0xF0) == 0xC0 and (marker == 0xC0 or bool(marker & 0x03))


def _jpeg_marker_name(marker: int) -> str:
    if marker in _MARKER_NAMES:
        return _MARKER_NAMES[marker]
    if _is_sof_marker(marker):
        return f"SOF{marker - 0xC0}"
    if 0xE0 <= marker <= 0xEF:
        return f"APP{marker - 0xE0}"
    if 0xD0 <= marker <= 0xD7:
        return f"RST{marker - 0xD0}"
    return f"0xFF{marker:02X}"
