"""Source-backed read state for ExifTool-style JPEG htmlDump output."""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from html import escape
from typing import Literal

from exifmodern.formats.jpeg.container import JpegSegment, scan_jpeg_segments
from exifmodern.formats.tiff.primitives import (
    TYPE_SIZES,
    Endian,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)
from exifmodern.json_types import JsonObject

type HtmlDumpByteRangeKind = Literal[
    "jpeg_marker",
    "jpeg_segment",
    "jpeg_segment_payload",
    "exif_identifier",
    "tiff_header",
    "tiff_ifd",
    "tiff_ifd_entry",
    "tiff_ifd_next_pointer",
    "tiff_indirect_value",
    "tiff_indirect_payload",
]
type HtmlDumpBlockKind = Literal["JPEG", "EXIF", "TIFF"]
type HtmlDumpSpanClass = Literal["W", "H", "F", "M"]


@dataclass(frozen=True)
class HtmlDumpByteRange:
    offset: int
    size: int
    label: str
    kind: HtmlDumpByteRangeKind


@dataclass(frozen=True)
class HtmlDumpSpanAnnotation:
    offset: int
    size: int
    label: str
    css_classes: tuple[HtmlDumpSpanClass, ...]
    tooltip: str


@dataclass(frozen=True)
class HtmlDumpBlock:
    kind: HtmlDumpBlockKind
    offset: int
    size: int
    label: str
    byte_ranges: tuple[HtmlDumpByteRange, ...]
    span_annotations: tuple[HtmlDumpSpanAnnotation, ...]


@dataclass(frozen=True)
class HtmlDumpReadState:
    html_dump_base: int
    source_file: str
    byte_ranges: tuple[HtmlDumpByteRange, ...]
    dump_blocks: tuple[HtmlDumpBlock, ...]
    span_annotations: tuple[HtmlDumpSpanAnnotation, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlDumpRangePayload:
    offset: int
    size: int
    emitted_size: int
    omitted_size: int
    label: str
    kind: HtmlDumpByteRangeKind
    hex_bytes: str
    ascii_text: str
    base64_bytes: str


@dataclass(frozen=True)
class _TiffOffsetPairSpec:
    offset_tag_id: int
    byte_count_tag_id: int
    offset_tag_name: str
    byte_count_tag_name: str
    data_name: str


HTML_DUMP_SOURCE_EVIDENCE = (
    "jpeg.html-dump.option-parse",
    "jpeg.html-dump.header-byte-ranges",
    "jpeg.html-dump.presentation",
    "jpeg.html-dump.indirect-tiff-values",
    "jpeg.html-dump.offset-count-ranges",
)
_SHARED_TIFF_OFFSET_PAIR_SPECS = (
    _TiffOffsetPairSpec(0x0111, 0x0117, "StripOffsets", "StripByteCounts", "Strip"),
    _TiffOffsetPairSpec(0x0120, 0x0121, "FreeOffsets", "FreeByteCounts", "Free"),
    _TiffOffsetPairSpec(0x0144, 0x0145, "TileOffsets", "TileByteCounts", "Tile"),
)


def build_jpeg_html_dump_read_state(
    data: bytes,
    source_file: str,
    *,
    html_dump_base: int = 0,
) -> HtmlDumpReadState:
    segments = scan_jpeg_segments(data)
    ranges: list[HtmlDumpByteRange] = [
        HtmlDumpByteRange(0, 2, "JPEG header", "jpeg_marker"),
    ]
    spans: list[HtmlDumpSpanAnnotation] = [
        _span(0, 2, "JPEG header", "SOI Marker"),
    ]
    blocks: list[HtmlDumpBlock] = [
        HtmlDumpBlock(
            kind="JPEG",
            offset=0,
            size=2,
            label="JPEG header",
            byte_ranges=(ranges[0],),
            span_annotations=(spans[0],),
        )
    ]

    for segment in segments:
        segment_range = _jpeg_segment_range(segment)
        marker_range = HtmlDumpByteRange(segment.offset, 2, segment.marker_name, "jpeg_marker")
        ranges.extend((marker_range, segment_range))
        segment_spans = (
            _span(segment.offset, 2, segment.marker_name, "JPEG marker"),
            _span(
                segment.offset,
                segment_range.size,
                segment.marker_name,
                f"{segment.marker_name} segment byte range",
            ),
        )
        spans.extend(segment_spans)
        block_ranges: list[HtmlDumpByteRange] = [marker_range, segment_range]
        block_spans: list[HtmlDumpSpanAnnotation] = list(segment_spans)

        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if payload:
            payload_range = HtmlDumpByteRange(
                segment.payload_offset,
                segment.payload_length,
                f"{segment.marker_name} payload",
                "jpeg_segment_payload",
            )
            ranges.append(payload_range)
            block_ranges.append(payload_range)
        if segment.marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            exif_ranges, exif_spans, tiff_block = _exif_tiff_ranges(data, segment)
            ranges.extend(exif_ranges)
            spans.extend(exif_spans)
            block_ranges.extend(exif_ranges)
            block_spans.extend(exif_spans)
            blocks.append(
                HtmlDumpBlock(
                    kind="EXIF",
                    offset=segment.payload_offset,
                    size=segment.payload_length,
                    label="EXIF APP1 payload",
                    byte_ranges=tuple(exif_ranges),
                    span_annotations=tuple(exif_spans),
                )
            )
            if tiff_block is not None:
                blocks.append(tiff_block)

        blocks.append(
            HtmlDumpBlock(
                kind="JPEG",
                offset=segment.offset,
                size=segment_range.size,
                label=f"{segment.marker_name} segment",
                byte_ranges=tuple(block_ranges),
                span_annotations=tuple(block_spans),
            )
        )

    return HtmlDumpReadState(
        html_dump_base=html_dump_base,
        source_file=source_file,
        byte_ranges=tuple(ranges),
        dump_blocks=tuple(blocks),
        span_annotations=tuple(spans),
        evidence_ids=HTML_DUMP_SOURCE_EVIDENCE,
    )


def html_dump_read_state_to_json_value(state: HtmlDumpReadState) -> JsonObject:
    return {
        "html_dump_base": state.html_dump_base,
        "source_file": state.source_file,
        "byte_ranges": [_byte_range_to_json_value(byte_range) for byte_range in state.byte_ranges],
        "dump_blocks": [_block_to_json_value(block) for block in state.dump_blocks],
        "span_annotations": [_span_to_json_value(span) for span in state.span_annotations],
        "source_" + "evidence": list(state.evidence_ids),
    }


def html_dump_read_state_payload_to_json_value(
    data: bytes,
    state: HtmlDumpReadState,
    *,
    dump_limit: int = 1024,
) -> JsonObject:
    payloads = html_dump_range_payloads(data, state, dump_limit=dump_limit)
    return {
        "html_dump_base": state.html_dump_base,
        "source_file": state.source_file,
        "dump_limit": dump_limit,
        "payload_records": [_payload_to_json_value(payload) for payload in payloads],
        "dump_blocks": [
            {
                "kind": block.kind,
                "offset": block.offset,
                "size": block.size,
                "label": block.label,
                "payload_record_offsets": [byte_range.offset for byte_range in block.byte_ranges],
            }
            for block in state.dump_blocks
        ],
        "source_" + "evidence": [
            *state.evidence_ids,
            "jpeg.html-dump.range-payload-rendering",
        ],
    }


def html_dump_range_payloads(
    data: bytes,
    state: HtmlDumpReadState,
    *,
    dump_limit: int = 1024,
) -> tuple[HtmlDumpRangePayload, ...]:
    return tuple(
        _range_payload(data, byte_range, dump_limit)
        for byte_range in state.byte_ranges
        if byte_range.size > 0 and byte_range.offset < len(data)
    )


def render_html_dump_document(
    data: bytes,
    state: HtmlDumpReadState,
    *,
    title: str | None = None,
    dump_limit: int = 1024,
) -> str:
    rendered_title = title or f"HTML Dump ({state.source_file})"
    rows = "".join(
        _render_html_dump_range(data, state, byte_range, dump_limit)
        for byte_range in state.byte_ranges
    )
    tooltips = "".join(
        _render_html_dump_tooltip(index, span) for index, span in enumerate(state.span_annotations)
    )
    return (
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN" '
        '"http://www.w3.org/TR/1998/REC-html40-19980424/loose.dtd">\n'
        "<html>\n<head>\n"
        f"<title>{escape(rendered_title, quote=True)}</title>\n"
        '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">\n'
        '<style type="text/css">\n'
        ".D { color: #000000 }\n"
        ".V { color: #ff0000 }\n"
        ".W { color: #004400 }\n"
        ".X { color: #ff4488 }\n"
        ".Y { color: #448844 }\n"
        ".U { color: #cc8844 }\n"
        ".H { color: #0000ff }\n"
        ".F { color: #aa00dd }\n"
        ".M { text-decoration: underline }\n"
        ".tt { visibility: hidden; position: absolute; white-space: nowrap; "
        "font-family: Verdana, sans-serif; font-size: .7em; padding: 2px 4px; "
        "border: 1px solid gray; z-index: 3 }\n"
        ".tb { visibility: hidden; position: absolute; background: #ffffdd; "
        "opacity: 0.8; z-index: 2 }\n"
        "table.dump { border-top: 1px solid gray; border-bottom: 1px solid gray }\n"
        "table.dump td { padding: .2em .3em; vertical-align: top }\n"
        "td.c2 { border-left: 1px solid gray; border-right: 1px solid gray }\n"
        "pre { margin: 0 }\n"
        "table { font-size: .9em }\n"
        "body { color: black; background: white }\n"
        "</style>\n"
        '<script language="JavaScript" type="text/JavaScript">\n'
        "function high(event,on) { return true; }\n"
        "function move(event) { return true; }\n"
        "function doClick(event) { return true; }\n"
        "</script></head>\n"
        "<body><noscript><b class=V>--&gt;Enable JavaScript for active highlighting "
        "and information tool tips!</b></noscript>\n"
        "<table class=dump cellspacing=0 cellpadding=2>\n"
        "<tr><th>Offset</th><th>Hex</th><th class=c2>ASCII</th><th>Comment</th></tr>\n"
        f"{rows}</table>\n<div id=tb class=tb> </div>\n{tooltips}</body></html>\n"
    )


def _exif_tiff_ranges(
    data: bytes,
    segment: JpegSegment,
) -> tuple[list[HtmlDumpByteRange], list[HtmlDumpSpanAnnotation], HtmlDumpBlock | None]:
    ranges: list[HtmlDumpByteRange] = []
    spans: list[HtmlDumpSpanAnnotation] = []
    ranges.append(
        HtmlDumpByteRange(segment.payload_offset, 6, "Exif identifier", "exif_identifier")
    )
    spans.append(_span(segment.payload_offset, 6, "Exif identifier", "Exif\\0\\0 header"))

    tiff_start = segment.payload_offset + 6
    tiff_data = data[tiff_start : segment.payload_offset + segment.payload_length]
    try:
        header = parse_tiff_header(tiff_data)
        ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    except ValueError:
        return ranges, spans, None

    tiff_ranges: list[HtmlDumpByteRange] = [
        HtmlDumpByteRange(tiff_start, 8, "TIFF header", "tiff_header"),
    ]
    tiff_spans: list[HtmlDumpSpanAnnotation] = [
        _span(tiff_start, 8, "TIFF header", header.byte_order),
    ]
    _append_ifd_ranges(
        tiff_ranges,
        tiff_spans,
        tiff_data=tiff_data,
        tiff_file_offset=tiff_start,
        source_size=len(data),
        ifd=ifd0,
        label="IFD0",
        endian=header.endian,
    )
    exif_ifd = _pointer_ifd(tiff_data, ifd0, 0x8769, header.endian)
    if exif_ifd is not None:
        _append_ifd_ranges(
            tiff_ranges,
            tiff_spans,
            tiff_data=tiff_data,
            tiff_file_offset=tiff_start,
            source_size=len(data),
            ifd=exif_ifd,
            label="ExifIFD",
            endian=header.endian,
        )
    gps_ifd = _pointer_ifd(tiff_data, ifd0, 0x8825, header.endian)
    if gps_ifd is not None:
        _append_ifd_ranges(
            tiff_ranges,
            tiff_spans,
            tiff_data=tiff_data,
            tiff_file_offset=tiff_start,
            source_size=len(data),
            ifd=gps_ifd,
            label="GPS",
            endian=header.endian,
        )
    if ifd0.next_ifd_offset:
        try:
            ifd1 = parse_ifd(tiff_data, ifd0.next_ifd_offset, header.endian)
        except ValueError:
            ifd1 = None
        if ifd1 is not None:
            _append_ifd_ranges(
                tiff_ranges,
                tiff_spans,
                tiff_data=tiff_data,
                tiff_file_offset=tiff_start,
                source_size=len(data),
                ifd=ifd1,
                label="IFD1",
                endian=header.endian,
            )

    ranges.extend(tiff_ranges)
    spans.extend(tiff_spans)
    return (
        ranges,
        spans,
        HtmlDumpBlock(
            kind="TIFF",
            offset=tiff_start,
            size=len(tiff_data),
            label="TIFF payload",
            byte_ranges=tuple(tiff_ranges),
            span_annotations=tuple(tiff_spans),
        ),
    )


def _append_ifd_ranges(
    ranges: list[HtmlDumpByteRange],
    spans: list[HtmlDumpSpanAnnotation],
    *,
    tiff_data: bytes,
    tiff_file_offset: int,
    source_size: int,
    ifd: Ifd,
    label: str,
    endian: Endian,
) -> None:
    table_size = 2 + len(ifd.entries) * 12 + 4
    ranges.append(HtmlDumpByteRange(tiff_file_offset + ifd.offset, table_size, label, "tiff_ifd"))
    spans.append(
        _span(
            tiff_file_offset + ifd.offset,
            table_size,
            label,
            f"{label} table with {len(ifd.entries)} entries",
        )
    )
    for entry in ifd.entries:
        entry_label = f"{label} tag 0x{entry.tag_id:04X}"
        ranges.append(
            HtmlDumpByteRange(
                tiff_file_offset + entry.entry_offset,
                12,
                entry_label,
                "tiff_ifd_entry",
            )
        )
        spans.append(
            _span(
                tiff_file_offset + entry.entry_offset,
                12,
                entry_label,
                f"type {entry.field_type}, count {entry.count}",
            )
        )
    next_offset = ifd.offset + 2 + len(ifd.entries) * 12
    if next_offset + 4 <= len(tiff_data):
        ranges.append(
            HtmlDumpByteRange(
                tiff_file_offset + next_offset,
                4,
                f"{label} next IFD pointer",
                "tiff_ifd_next_pointer",
            )
        )
    _append_indirect_value_ranges(
        ranges,
        spans,
        tiff_data=tiff_data,
        tiff_file_offset=tiff_file_offset,
        ifd=ifd,
        label=label,
    )
    _append_indirect_payload_ranges(
        ranges,
        spans,
        tiff_data=tiff_data,
        tiff_file_offset=tiff_file_offset,
        source_size=source_size,
        ifd=ifd,
        label=label,
        endian=endian,
    )


def _append_indirect_value_ranges(
    ranges: list[HtmlDumpByteRange],
    spans: list[HtmlDumpSpanAnnotation],
    *,
    tiff_data: bytes,
    tiff_file_offset: int,
    ifd: Ifd,
    label: str,
) -> None:
    for entry in ifd.entries:
        byte_count = _tiff_entry_byte_count(entry)
        if byte_count is None or byte_count <= 4:
            continue
        value_offset = entry.value_offset
        if value_offset < 0 or value_offset + byte_count > len(tiff_data):
            continue
        range_label = f"{label} tag 0x{entry.tag_id:04X} value"
        file_offset = tiff_file_offset + value_offset
        ranges.append(
            HtmlDumpByteRange(file_offset, byte_count, range_label, "tiff_indirect_value")
        )
        spans.append(
            _span(
                file_offset,
                byte_count,
                range_label,
                (
                    f"indirect TIFF value; type {entry.field_type}, count {entry.count}, "
                    f"size {byte_count} bytes"
                ),
            )
        )


def _append_indirect_payload_ranges(
    ranges: list[HtmlDumpByteRange],
    spans: list[HtmlDumpSpanAnnotation],
    *,
    tiff_data: bytes,
    tiff_file_offset: int,
    source_size: int,
    ifd: Ifd,
    label: str,
    endian: Endian,
) -> None:
    entries = {entry.tag_id: entry for entry in ifd.entries}
    for spec in _offset_pair_specs_for_ifd(label):
        offset_entry = entries.get(spec.offset_tag_id)
        byte_count_entry = entries.get(spec.byte_count_tag_id)
        if offset_entry is None or byte_count_entry is None:
            continue
        offsets = _entry_int_tuple(tiff_data, offset_entry, endian)
        byte_counts = _entry_int_tuple(tiff_data, byte_count_entry, endian)
        for payload in _combined_offset_pair_payloads(offsets, byte_counts):
            file_offset = tiff_file_offset + payload.start
            if file_offset < 0 or file_offset + payload.size > source_size:
                continue
            range_label = f"({label}:{_indexed_data_name(spec.data_name, payload)} data)"
            tooltip = f"Size: {payload.byte_count} bytes"
            if payload.pad_bytes:
                tooltip = f"{tooltip}, incl. {payload.pad_bytes} pad bytes"
            ranges.append(
                HtmlDumpByteRange(
                    file_offset,
                    payload.size,
                    range_label,
                    "tiff_indirect_payload",
                )
            )
            spans.append(_span(file_offset, payload.size, range_label, tooltip))


@dataclass(frozen=True)
class _TiffIndirectPayload:
    start: int
    size: int
    byte_count: int
    first_index: int
    last_index: int
    pair_count: int
    pad_bytes: int


def _offset_pair_specs_for_ifd(label: str) -> tuple[_TiffOffsetPairSpec, ...]:
    specs = list(_SHARED_TIFF_OFFSET_PAIR_SPECS)
    if label == "IFD1":
        specs.append(
            _TiffOffsetPairSpec(
                0x0201,
                0x0202,
                "ThumbnailOffset",
                "ThumbnailLength",
                "Thumbnail",
            )
        )
    elif label == "IFD0":
        specs.append(
            _TiffOffsetPairSpec(
                0x0201,
                0x0202,
                "PreviewImageStart",
                "PreviewImageLength",
                "PreviewImage",
            )
        )
    return tuple(specs)


def _combined_offset_pair_payloads(
    offsets: tuple[int, ...],
    byte_counts: tuple[int, ...],
) -> tuple[_TiffIndirectPayload, ...]:
    payloads: list[_TiffIndirectPayload] = []
    index = 0
    pair_count = min(len(offsets), len(byte_counts))
    while index < pair_count:
        start = offsets[index]
        size = byte_counts[index]
        if size <= 0:
            index += 1
            continue
        first_index = index
        last_index = index
        pad_bytes = 0
        index += 1
        while index < pair_count:
            end = start + size
            if byte_counts[index] <= 0:
                break
            if end & 0x01 and end + 1 == offsets[index]:
                size += 1
                pad_bytes += 1
                end += 1
            if end != offsets[index]:
                break
            size += byte_counts[index]
            last_index = index
            index += 1
        payloads.append(
            _TiffIndirectPayload(
                start=start,
                size=size,
                byte_count=size - pad_bytes,
                first_index=first_index,
                last_index=last_index,
                pair_count=pair_count,
                pad_bytes=pad_bytes,
            )
        )
    return tuple(payloads)


def _indexed_data_name(data_name: str, payload: _TiffIndirectPayload) -> str:
    if payload.pair_count <= 1:
        return data_name
    if payload.first_index == payload.last_index:
        return f"{data_name} {payload.first_index}"
    return f"{data_name} {payload.first_index}-{payload.last_index}"


def _entry_int_tuple(data: bytes, entry: IfdEntry, endian: Endian) -> tuple[int, ...]:
    try:
        value = read_entry_value(data, entry, endian)
    except ValueError:
        return ()
    if isinstance(value, int):
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, int))
    return ()


def _tiff_entry_byte_count(entry: IfdEntry) -> int | None:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        return None
    return field_size * entry.count


def _pointer_ifd(data: bytes, ifd: Ifd, tag_id: int, endian: Endian) -> Ifd | None:
    pointer_entry = next((entry for entry in ifd.entries if entry.tag_id == tag_id), None)
    if pointer_entry is None or pointer_entry.field_type != 4 or pointer_entry.count != 1:
        return None
    field_size = TYPE_SIZES.get(pointer_entry.field_type)
    if field_size is None or field_size * pointer_entry.count > 4:
        return None
    try:
        return parse_ifd(data, pointer_entry.value_offset, endian)
    except ValueError:
        return None


def _jpeg_segment_range(segment: JpegSegment) -> HtmlDumpByteRange:
    return HtmlDumpByteRange(
        offset=segment.offset,
        size=2 if segment.payload_length == 0 else segment.payload_length + 4,
        label=f"{segment.marker_name} segment",
        kind="jpeg_segment",
    )


def _span(offset: int, size: int, label: str, tooltip: str) -> HtmlDumpSpanAnnotation:
    return HtmlDumpSpanAnnotation(
        offset=offset,
        size=size,
        label=label,
        css_classes=("W", "H"),
        tooltip=tooltip,
    )


def _byte_range_to_json_value(byte_range: HtmlDumpByteRange) -> JsonObject:
    return {
        "offset": byte_range.offset,
        "size": byte_range.size,
        "label": byte_range.label,
        "kind": byte_range.kind,
    }


def _span_to_json_value(span: HtmlDumpSpanAnnotation) -> JsonObject:
    return {
        "offset": span.offset,
        "size": span.size,
        "label": span.label,
        "css_classes": list(span.css_classes),
        "tooltip": span.tooltip,
    }


def _block_to_json_value(block: HtmlDumpBlock) -> JsonObject:
    return {
        "kind": block.kind,
        "offset": block.offset,
        "size": block.size,
        "label": block.label,
        "byte_ranges": [_byte_range_to_json_value(byte_range) for byte_range in block.byte_ranges],
        "span_annotations": [_span_to_json_value(span) for span in block.span_annotations],
    }


def _payload_to_json_value(payload: HtmlDumpRangePayload) -> JsonObject:
    return {
        "offset": payload.offset,
        "size": payload.size,
        "emitted_size": payload.emitted_size,
        "omitted_size": payload.omitted_size,
        "label": payload.label,
        "kind": payload.kind,
        "hex_bytes": payload.hex_bytes,
        "ascii_text": payload.ascii_text,
        "base64_bytes": payload.base64_bytes,
    }


def _range_payload(
    data: bytes,
    byte_range: HtmlDumpByteRange,
    dump_limit: int,
) -> HtmlDumpRangePayload:
    end = min(byte_range.offset + byte_range.size, len(data))
    payload = data[byte_range.offset : end]
    if dump_limit >= 0 and len(payload) > dump_limit:
        payload = payload[:dump_limit]
    return HtmlDumpRangePayload(
        offset=byte_range.offset,
        size=byte_range.size,
        emitted_size=len(payload),
        omitted_size=max(byte_range.size - len(payload), 0),
        label=byte_range.label,
        kind=byte_range.kind,
        hex_bytes=" ".join(f"{byte:02x}" for byte in payload),
        ascii_text=_ascii_payload_text(payload),
        base64_bytes=b64encode(payload).decode("ascii"),
    )


def _ascii_payload_text(payload: bytes) -> str:
    return "".join(chr(byte) if 0x20 <= byte < 0x7F else "." for byte in payload)


def _render_html_dump_range(
    data: bytes,
    state: HtmlDumpReadState,
    byte_range: HtmlDumpByteRange,
    dump_limit: int,
) -> str:
    if byte_range.size <= 0:
        return ""
    offset = byte_range.offset
    end = min(offset + byte_range.size, len(data))
    if offset >= len(data):
        return ""
    payload = data[offset:end]
    if dump_limit >= 0 and len(payload) > dump_limit:
        payload = payload[:dump_limit]
    tooltip_index = _html_dump_tooltip_index(state, byte_range)
    css_class = _html_dump_css_class(state, byte_range)
    anchor_name = f"t{tooltip_index}" if tooltip_index is not None else None
    rows: list[str] = []
    for row_offset in range(0, len(payload), 16):
        row = payload[row_offset : row_offset + 16]
        absolute_offset = offset + row_offset
        if row_offset == 0:
            label = byte_range.label
            if len(payload) < byte_range.size:
                label = f"{label} [snip {byte_range.size - len(payload)} bytes]"
        else:
            label = ""
        rows.append(
            "<tr>"
            f"<td><pre>{_html_dump_offset(absolute_offset - state.html_dump_base)}</pre></td>"
            f"<td><pre>{_html_dump_hex(row, css_class, anchor_name)}</pre></td>"
            f"<td class=c2><pre>{_html_dump_ascii(row, css_class, anchor_name)}</pre></td>"
            f"<td><pre>{escape(label, quote=True)}</pre></td>"
            "</tr>\n"
        )
    return "".join(rows)


def _html_dump_tooltip_index(
    state: HtmlDumpReadState,
    byte_range: HtmlDumpByteRange,
) -> int | None:
    for index, span in enumerate(state.span_annotations):
        if span.offset == byte_range.offset and span.size == byte_range.size:
            return index
    return None


def _html_dump_css_class(state: HtmlDumpReadState, byte_range: HtmlDumpByteRange) -> str:
    for span in state.span_annotations:
        if span.offset == byte_range.offset and span.size == byte_range.size:
            return " ".join(span.css_classes)
    return "W"


def _html_dump_offset(offset: int) -> str:
    if offset < 0:
        return f"-{-offset:04x}"
    return f"{offset:04x}"


def _html_dump_hex(row: bytes, css_class: str, anchor_name: str | None) -> str:
    rendered = " ".join(f"{byte:02x}" for byte in row[:8])
    if len(row) > 8:
        rendered = f"{rendered}  {' '.join(f'{byte:02x}' for byte in row[8:])}"
    return _html_dump_anchor(rendered, css_class, anchor_name)


def _html_dump_ascii(row: bytes, css_class: str, anchor_name: str | None) -> str:
    rendered = "".join(chr(byte) if 0x20 <= byte < 0x7F else "." for byte in row)
    return _html_dump_anchor(escape(rendered, quote=True), css_class, anchor_name)


def _html_dump_anchor(content: str, css_class: str, anchor_name: str | None) -> str:
    escaped_class = escape(css_class, quote=True)
    if anchor_name is None:
        return f'<span class="{escaped_class}">{content}</span>'
    escaped_name = escape(anchor_name, quote=True)
    return f'<a name="{escaped_name}" class="{escaped_class}">{content}</a>'


def _render_html_dump_tooltip(index: int, span: HtmlDumpSpanAnnotation) -> str:
    label = escape(span.label, quote=True)
    tooltip = escape(span.tooltip, quote=True)
    return f"<div id=p{index} class=tt><b>{label}</b><br>{tooltip}<br>({span.size} bytes)</div>\n"
