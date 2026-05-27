"""Matroska/EBML public read-graph adapter."""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from exifmodern.formats.matroska.ebml_transaction_plan import (
    CLUSTER_ID,
    STANDARD_SIMPLE_TAGS,
    MatroskaEbmlTransactionPlan,
    build_matroska_ebml_transaction_plan,
    decode_ebml_text,
    decode_scalar_value,
    generated_output_name,
    read_ebml_vint,
    render_scalar_value,
    standardized_output_name,
)
from exifmodern.json_types import JsonValue
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue
from exifmodern.services.system_metadata import read_system_tags

MATROSKA_SIGNATURE = b"\x1a\x45\xdf\xa3"
MATROSKA_INITIAL_READ_BYTES = 65_536
MATROSKA_TARGETED_TAGS_READ_BYTES = 2 * 1024 * 1024
MATROSKA_EXTENSION_FILE_TYPES = {
    ".mka": ("MKA", "mka", "audio/x-matroska"),
    ".mks": ("MKS", "mks", "application/x-matroska"),
    ".mkv": ("MKV", "mkv", "video/x-matroska"),
    ".webm": ("WEBM", "webm", "video/webm"),
}
MATROSKA_HEADER_TAGS = frozenset(
    {
        "EBMLVersion",
        "EBMLReadVersion",
        "EBMLMaxIDLength",
        "EBMLMaxSizeLength",
        "DocType",
        "DocTypeVersion",
        "DocTypeReadVersion",
    }
)
MATROSKA_TABLE = "Image::ExifTool::Matroska::Main"
MATROSKA_STD_TAG_TABLE = "Image::ExifTool::Matroska::StdTag"
EBML_HEADER_ID = 0x0A45DFA3
SEGMENT_ID = 0x08538067
INFO_ID = 0x0549A966
CHAPTER_TRANSLATE_ID = 0x2924
TRACKS_ID = 0x0654AE6B
TRACK_ENTRY_ID = 0x2E
TRACK_TYPE_ID = 0x03
TRACK_TRANSLATE_ID = 0x2624
VIDEO_ID = 0x60
AUDIO_ID = 0x61
SEEK_HEAD_ID = 0x014D9B74
SEEK_ID = 0x13AB
SEEK_POSITION_ID = 0x13AC
CUES_ID = 0x0C53BB6B
CUE_POINT_ID = 0x3B
CUE_TRACK_POSITIONS_ID = 0x37
CUE_REFERENCE_ID = 0x5B
ATTACHMENTS_ID = 0x0941A469
ATTACHED_FILE_ID = 0x21A7
CHAPTERS_ID = 0x43A770
EDITION_ENTRY_ID = 0x5B9
CHAPTER_ATOM_ID = 0x36
CHAPTER_TRACK_ID = 0x0F
CHAPTER_DISPLAY_ID = 0x00
CHAPTER_PROCESS_ID = 0x2944
CHAPTER_PROCESS_COMMAND_ID = 0x2911
CONTENT_ENCODINGS_ID = 0x2D80
CONTENT_ENCODING_ID = 0x2240
CONTENT_COMPRESSION_ID = 0x1034
CONTENT_ENCRYPTION_ID = 0x1035
PROJECTION_ID = 0x7670
TAGS_ID = 0x0254C367
TAG_ID = 0x3373
TARGETS_ID = 0x23C0
TAG_TRACK_UID_ID = 0x23C5
SIMPLE_TAG_ID = 0x27C8
TAG_NAME_ID = 0x05A3
TAG_LANGUAGE_ID = 0x047A
TAG_LANGUAGE_BCP47_ID = 0x047A
TAG_DEFAULT_ID = 0x0484
TAG_STRING_ID = 0x0487
TAG_BINARY_ID = 0x0485
METADATA_MASTER_IDS = frozenset(
    {
        EBML_HEADER_ID,
        SEGMENT_ID,
        INFO_ID,
        CHAPTER_TRANSLATE_ID,
        TRACKS_ID,
        TRACK_ENTRY_ID,
        TRACK_TRANSLATE_ID,
        VIDEO_ID,
        AUDIO_ID,
        SEEK_HEAD_ID,
        0x0DBB,
        CUES_ID,
        CUE_POINT_ID,
        CUE_TRACK_POSITIONS_ID,
        CUE_REFERENCE_ID,
        ATTACHMENTS_ID,
        ATTACHED_FILE_ID,
        CHAPTERS_ID,
        EDITION_ENTRY_ID,
        CHAPTER_ATOM_ID,
        CHAPTER_TRACK_ID,
        CHAPTER_DISPLAY_ID,
        CHAPTER_PROCESS_ID,
        CHAPTER_PROCESS_COMMAND_ID,
        CONTENT_ENCODINGS_ID,
        CONTENT_ENCODING_ID,
        CONTENT_COMPRESSION_ID,
        CONTENT_ENCRYPTION_ID,
        PROJECTION_ID,
        TAGS_ID,
        TAG_ID,
        TARGETS_ID,
        SIMPLE_TAG_ID,
    }
)
SEEK_TARGET_NAMES = {
    0x0549A966: "Info",
    0x0654AE6B: "Tracks",
    0x014D9B74: "SeekHead",
    0x0C53BB6B: "Cues",
    0x0941A469: "Attachments",
    0x43A770: "Chapters",
    0x0254C367: "Tags",
    0x0F43B675: "Cluster",
}
TRACK_TYPE_NAMES = {
    0x01: "Video",
    0x02: "Audio",
    0x03: "Complex",
    0x10: "Logo",
    0x11: "Subtitle",
    0x12: "Buttons",
    0x20: "Control",
}
VIDEO_TRACK_TYPE = 0x01
AUDIO_TRACK_TYPE = 0x02
NO_YES = {0: "No", 1: "Yes"}
VIDEO_SCAN_TYPES = {
    0: "Undetermined",
    1: "Interlaced",
    2: "Progressive",
}
STEREO_3D_MODES = {
    0: "Mono",
    1: "Right Eye",
    2: "Left Eye",
    3: "Both Eyes",
}
DISPLAY_UNITS = {
    0: "Pixels",
    1: "cm",
    2: "inches",
    3: "Display Aspect Ratio",
    4: "Unknown",
}
ASPECT_RATIO_TYPES = {
    0: "Free Resizing",
    1: "Keep Aspect Ratio",
    2: "Fixed",
}
CONTENT_ENCODING_TYPES = {
    0: "Compression",
    1: "Encryption",
}
CONTENT_COMPRESSION_ALGORITHMS = {
    0: "zlib",
    1: "bzlib",
    2: "lzo1x",
    3: "Header Stripping",
}
CONTENT_ENCRYPTION_ALGORITHMS = {
    0: "Not Encrypted",
    1: "DES",
    2: "3DES",
    3: "Twofish",
    4: "Blowfish",
    5: "AES",
}
CONTENT_SIGNATURE_ALGORITHMS = {
    0: "Not Signed",
    1: "RSA",
}
CONTENT_SIGNATURE_HASH_ALGORITHMS = {
    0: "Not Signed",
    1: "SHA1-160",
    2: "MD5",
}
TRANSLATE_CODECS = {
    0: "Matroska Script",
    1: "DVD Menu",
}
CHAPTER_PHYSICAL_EQUIVALENTS = {
    10: "Index",
    20: "Track",
    30: "Session",
    40: "Layer",
    50: "Side",
    60: "CD / DVD",
    70: "Set / Package",
}
CHAPTER_PROCESS_CODECS = {
    0: "Matroska",
    1: "DVD",
}
CHAPTER_PROCESS_TIMES = {
    0: "For Duration of Chapter",
    1: "Before Chapter",
    2: "After Chapter",
}
PROJECTION_TYPES = {
    0: "Rectangular",
    1: "Equirectangular",
    2: "Cubemap",
    3: "Mesh",
}
TARGET_TYPE_VALUES = {
    10: "Shot",
    20: "Scene/Subtrack",
    30: "Chapter/Track",
    40: "Session",
    50: "Movie/Album",
    60: "Season/Edition",
    70: "Collection",
}
INFO_SCALAR_FORMATS = {
    0x33A4: "uid",
    0x3384: "utf8",
    0x1CB923: "uid",
    0x1C83AB: "utf8",
    0x1EB923: "uid",
    0x1E83BB: "utf8",
    0x0AD7B1: "unsigned",
    0x0489: "float",
    0x0461: "date",
    0x03BA9: "utf8",
    0x0D80: "utf8",
    0x1741: "utf8",
}
INFO_SCALAR_NAMES = {
    0x33A4: "SegmentUID",
    0x3384: "SegmentFileName",
    0x1CB923: "PrevUID",
    0x1C83AB: "PrevFileName",
    0x1EB923: "NextUID",
    0x1E83BB: "NextFileName",
    0x0AD7B1: "TimecodeScale",
    0x0489: "Duration",
    0x0461: "DateTimeOriginal",
    0x03BA9: "Title",
    0x0D80: "MuxingApp",
    0x1741: "WritingApp",
}


@dataclass(frozen=True)
class AdapterEbmlElement:
    element_id: int
    offset: int
    payload_offset: int
    payload_size: int
    end_offset: int
    path: tuple[int, ...]


@dataclass(frozen=True)
class TargetedTagsWindow:
    data: bytes
    absolute_offset: int
    requested_size: int
    is_complete: bool


class MatroskaDecodedTag:
    def __init__(
        self,
        name: str,
        value: TagValue,
        tag_id: str,
        source: str,
        *,
        family_1_group: str = "Matroska",
        family_2_group: str = "Video",
        table_name: str = MATROSKA_TABLE,
        duplicate_instance_ordinal: int | None = None,
    ) -> None:
        self.name = name
        self.value = value
        self.tag_id = tag_id
        self.source = source
        self.family_1_group = family_1_group
        self.family_2_group = family_2_group
        self.table_name = table_name
        self.duplicate_instance_ordinal = duplicate_instance_ordinal


@dataclass(frozen=True)
class SimpleTagContext:
    tag_id: str
    output_name: str
    language: str | None
    country: str | None


def is_matroska_prefix(data: bytes) -> bool:
    return data.startswith(MATROSKA_SIGNATURE)


def build_matroska_read_graph_from_file(
    path: Path,
    *,
    source_file: str,
    prefix: bytes = b"",
    max_initial_bytes: int = MATROSKA_INITIAL_READ_BYTES,
    max_targeted_tags_bytes: int = MATROSKA_TARGETED_TAGS_READ_BYTES,
) -> ReadGraph:
    """Build a Matroska graph from a bounded leading byte range.

    ExifTool's Matroska reader advances in 64 KiB blocks and stops at the
    first Cluster by default. Public dispatch should preserve that large-media
    property instead of materializing multi-GB media payloads.
    """

    data = prefix[:max_initial_bytes]
    if len(data) < max_initial_bytes:
        with path.open("rb") as file:
            data = file.read(max_initial_bytes)
    targeted_tags_windows = _read_seek_directed_tags_windows(
        path,
        data,
        max_targeted_tags_bytes=max_targeted_tags_bytes,
    )
    return build_matroska_read_graph(
        data,
        path,
        source_file,
        targeted_tags_windows=targeted_tags_windows,
    )


def build_matroska_read_graph(
    data: bytes,
    path: Path,
    source_file: str,
    *,
    targeted_tags_windows: tuple[TargetedTagsWindow, ...] = (),
) -> ReadGraph:
    tags = _system_tags(path, source_file)
    diagnostics: list[str] = []
    file_type, extension, mime_type = MATROSKA_EXTENSION_FILE_TYPES.get(
        path.suffix.lower(),
        ("MKV", "mkv", "video/x-matroska"),
    )
    plan = build_matroska_ebml_transaction_plan(data)
    if plan.header.is_valid:
        for scalar in plan.scalars:
            if scalar.name == "DocType" and scalar.raw_value == "webm":
                file_type, extension, mime_type = "WEBM", "webm", "video/webm"
                break
        tags.extend(_file_type_tags(file_type, extension, mime_type, "matroska-ebml"))
        emitted_scalar_names: set[str] = set()
        timecode_scale = _timecode_scale(plan)
        for scalar in plan.scalars:
            emitted_scalar_names.add(scalar.name)
            if scalar.name in MATROSKA_HEADER_TAGS:
                source = "matroska-ebml-header"
            else:
                source = "matroska-segment-info"
            rendered_value = _render_top_level_scalar_value(
                scalar.name,
                scalar.raw_value,
                scalar.rendered_value,
                timecode_scale,
            )
            tags.append(
                _read_tag(
                    scalar.name,
                    _tag_value(rendered_value),
                    "Matroska",
                    MATROSKA_TABLE,
                    f"0x{scalar.element_id:x}",
                    source,
                    family_1_group="Info" if source == "matroska-segment-info" else "Matroska",
                    family_2_group="Time" if scalar.name == "DateTimeOriginal" else "Video",
                )
            )
        elements = _walk_metadata_elements(data, 0, len(data), ())
        external_tag_offsets = {window.absolute_offset for window in targeted_tags_windows}
        elements = _with_seek_directed_post_cluster_metadata(
            data,
            elements,
            diagnostics,
            external_tag_offsets=external_tag_offsets,
        )
        for decoded_tag in _segment_info_tags(data, elements, emitted_scalar_names):
            tags.append(_decoded_read_tag(decoded_tag))
        for decoded_tag in _track_tags(data, elements, diagnostics):
            tags.append(_decoded_read_tag(decoded_tag))
        for decoded_tag in _segment_metadata_tags(data, plan, elements, diagnostics):
            tags.append(_decoded_read_tag(decoded_tag))
        for decoded_tag in _targeted_tags_window_tags(
            targeted_tags_windows,
            data,
            elements,
            diagnostics,
        ):
            tags.append(_decoded_read_tag(decoded_tag))
        tags.extend(_matroska_composite_tags(tags))
    diagnostics.extend(
        gate.reason
        for gate in plan.output_emission_gates
        if gate.code
        not in {
            "planner_is_non_mutating",
            "full_ebml_writer_not_implemented",
        }
    )
    if not plan.header.is_valid:
        tags.extend(_file_type_tags(file_type, extension, mime_type, "matroska-ebml"))
    diagnostics.append(
        "Matroska traversal is bounded to source-defined EBML header, Segment Info, "
        "SeekHead, Cues, TrackEntry, Attachments, Chapters, and SimpleTag metadata "
        "in public dispatch; "
        "ExifTool ProcessMKV reads in 64 KiB blocks and skips large Cluster/media payloads."
    )
    return ReadGraph(1, int(time.time()), source_file, tags, diagnostics)


def _read_seek_directed_tags_windows(
    path: Path,
    initial_data: bytes,
    *,
    max_targeted_tags_bytes: int,
) -> tuple[TargetedTagsWindow, ...]:
    elements = _walk_metadata_elements(initial_data, 0, len(initial_data), ())
    target_offsets = _seek_target_offsets(initial_data, elements).get("Tags", ())
    if not target_offsets:
        return ()
    file_size = path.stat().st_size
    windows: list[TargetedTagsWindow] = []
    seen_offsets: set[int] = set()
    with path.open("rb") as file:
        for target_offset in target_offsets:
            if (
                target_offset in seen_offsets
                or target_offset < len(initial_data)
                or target_offset >= file_size
            ):
                continue
            seen_offsets.add(target_offset)
            window = _read_tags_window(
                file,
                target_offset,
                file_size,
                max_targeted_tags_bytes=max_targeted_tags_bytes,
            )
            if window is not None:
                windows.append(window)
    return tuple(windows)


def _read_tags_window(
    file: BinaryIO,
    target_offset: int,
    file_size: int,
    *,
    max_targeted_tags_bytes: int,
) -> TargetedTagsWindow | None:
    if max_targeted_tags_bytes <= 0:
        return None
    file.seek(target_offset)
    header_probe = file.read(16)
    try:
        element_id = read_ebml_vint(header_probe, 0)
        size = read_ebml_vint(header_probe, element_id.next_offset)
    except ValueError:
        return None
    if element_id.value != TAGS_ID or size.is_unknown_size:
        return None
    requested_size = min(size.next_offset + size.value, file_size - target_offset)
    read_size = min(requested_size, max_targeted_tags_bytes)
    file.seek(target_offset)
    data = file.read(read_size)
    return TargetedTagsWindow(
        data=data,
        absolute_offset=target_offset,
        requested_size=requested_size,
        is_complete=read_size >= requested_size,
    )


def _targeted_tags_window_tags(
    windows: tuple[TargetedTagsWindow, ...],
    primary_data: bytes,
    primary_elements: list[AdapterEbmlElement],
    diagnostics: list[str],
) -> list[MatroskaDecodedTag]:
    if not windows:
        return []
    track_uid_groups = _track_uid_groups(primary_data, primary_elements)
    tags: list[MatroskaDecodedTag] = []
    for window in windows:
        elements = _walk_metadata_elements(window.data, 0, len(window.data), (SEGMENT_ID,))
        if not elements:
            diagnostics.append(
                "Matroska SeekHead-directed bounded read found no complete Tags element "
                f"at offset {window.absolute_offset}."
            )
            continue
        tags.extend(_target_tags(window.data, elements, track_uid_groups))
        tags.extend(_simple_tag_tags(window.data, elements, diagnostics, track_uid_groups))
        if window.is_complete:
            diagnostics.append(
                "Matroska SeekHead-directed bounded read extracted post-Cluster Tags "
                f"at offset {window.absolute_offset} without scanning Cluster media payload."
            )
        else:
            diagnostics.append(
                "Matroska SeekHead-directed bounded read truncated a Tags element at offset "
                f"{window.absolute_offset}; requested {window.requested_size} bytes but read "
                f"{len(window.data)} bytes."
            )
    return tags


def _render_top_level_scalar_value(
    name: str,
    raw_value: JsonValue,
    rendered_value: JsonValue,
    timecode_scale: int,
) -> JsonValue:
    if name == "TimecodeScale" and isinstance(raw_value, int):
        return _milliseconds_text(raw_value / 1_000_000)
    if name == "TimecodeScale" and isinstance(rendered_value, int | float):
        return _milliseconds_text(float(rendered_value) * 1000)
    if name == "Duration" and isinstance(raw_value, int | float) and timecode_scale:
        return _duration_text(float(raw_value) * timecode_scale / 1_000_000_000)
    if name == "Duration" and isinstance(rendered_value, int | float):
        return _duration_text(float(rendered_value))
    return rendered_value


def _track_tags(
    data: bytes,
    elements: list[AdapterEbmlElement],
    diagnostics: list[str],
) -> list[MatroskaDecodedTag]:
    tags: list[MatroskaDecodedTag] = []
    track_entries = [element for element in elements if element.element_id == TRACK_ENTRY_ID]
    for track_index, track_entry in enumerate(track_entries):
        children = [
            element
            for element in elements
            if element.offset > track_entry.offset
            and element.end_offset <= track_entry.end_offset
            and element.payload_size is not None
        ]
        track_type = _track_type(children, data)
        for child in children:
            decoded = _track_child_tag(child, data, track_type, track_index, diagnostics)
            if decoded is not None:
                tags.append(decoded)
    return tags


def _segment_metadata_tags(
    data: bytes,
    plan: MatroskaEbmlTransactionPlan,
    elements: list[AdapterEbmlElement],
    diagnostics: list[str],
) -> list[MatroskaDecodedTag]:
    timecode_scale = _timecode_scale(plan)
    track_uid_groups = _track_uid_groups(data, elements)
    tags: list[MatroskaDecodedTag] = []
    tags.extend(_seek_tags(data, elements))
    tags.extend(_chapter_translate_tags(data, elements, diagnostics))
    tags.extend(_cue_tags(data, elements, timecode_scale))
    tags.extend(_attachment_tags(data, elements, diagnostics))
    tags.extend(_chapter_tags(data, elements))
    tags.extend(_target_tags(data, elements, track_uid_groups))
    tags.extend(_simple_tag_tags(data, elements, diagnostics, track_uid_groups))
    return tags


def _segment_info_tags(
    data: bytes,
    elements: list[AdapterEbmlElement],
    emitted_scalar_names: set[str],
) -> list[MatroskaDecodedTag]:
    tags: list[MatroskaDecodedTag] = []
    timecode_scale = 0
    info_elements = [element for element in elements if element.element_id == INFO_ID]
    for info in info_elements:
        for child in _direct_children(elements, info):
            name = INFO_SCALAR_NAMES.get(child.element_id)
            if name is None:
                continue
            payload = data[child.payload_offset : child.payload_offset + child.payload_size]
            format_name = INFO_SCALAR_FORMATS[child.element_id]
            raw_value: JsonValue = (
                payload.hex() if format_name == "uid" else decode_scalar_value(payload, format_name)
            )
            if child.element_id == 0x0AD7B1 and isinstance(raw_value, int):
                timecode_scale = raw_value
            if name in emitted_scalar_names:
                continue
            rendered_value = _render_info_scalar_value(
                child.element_id,
                raw_value,
                timecode_scale,
            )
            tags.append(
                MatroskaDecodedTag(
                    name,
                    _tag_value(rendered_value),
                    f"0x{child.element_id:x}",
                    "matroska-segment-info",
                    family_1_group="Info",
                    family_2_group="Time" if child.element_id == 0x0461 else "Video",
                )
            )
    return tags


def _render_info_scalar_value(
    element_id: int,
    raw_value: JsonValue,
    timecode_scale: int,
) -> JsonValue:
    if element_id == 0x0AD7B1 and isinstance(raw_value, int):
        return _milliseconds_text(raw_value / 1_000_000)
    if element_id == 0x0489 and isinstance(raw_value, int | float) and timecode_scale:
        return _duration_text(float(raw_value) * timecode_scale / 1_000_000_000)
    if element_id == 0x0461 and isinstance(raw_value, int):
        epoch = datetime(2001, 1, 1, tzinfo=UTC)
        date_time = epoch + timedelta(seconds=raw_value / 1_000_000_000)
        return date_time.strftime("%Y:%m:%d %H:%M:%SZ")
    return render_scalar_value(element_id, raw_value, timecode_scale)


def _seek_tags(data: bytes, elements: list[AdapterEbmlElement]) -> list[MatroskaDecodedTag]:
    tags: list[MatroskaDecodedTag] = []
    seek_head_by_path = {
        element.path: element for element in elements if element.element_id == SEEK_HEAD_ID
    }
    segment_by_path = {
        element.path: element for element in elements if element.element_id == SEGMENT_ID
    }
    for element in elements:
        payload = data[element.payload_offset : element.payload_offset + element.payload_size]
        if element.element_id == SEEK_ID:
            value = _seek_id_value(payload)
            if value is None:
                continue
            tags.append(MatroskaDecodedTag("SeekID", value, "0x13ab", "matroska-seek-head"))
        elif element.element_id == SEEK_POSITION_ID:
            seek_head = _nearest_parent(element, seek_head_by_path)
            base_offset = (
                _seek_position_base_offset(seek_head, segment_by_path)
                if seek_head is not None
                else 0
            )
            tags.append(
                MatroskaDecodedTag(
                    "SeekPosition",
                    _unsigned(payload) + base_offset,
                    "0x13ac",
                    "matroska-seek-head",
                )
            )
    return tags


def _chapter_translate_tags(
    data: bytes,
    elements: list[AdapterEbmlElement],
    diagnostics: list[str],
) -> list[MatroskaDecodedTag]:
    tags: list[MatroskaDecodedTag] = []
    chapter_translates = [
        element for element in elements if element.element_id == CHAPTER_TRANSLATE_ID
    ]
    for translate_index, chapter_translate in enumerate(chapter_translates):
        for child in _descendants(elements, chapter_translate):
            payload = data[child.payload_offset : child.payload_offset + child.payload_size]
            if child.element_id == 0x29FC:
                name = "ChapterTranslateEditionUID"
                value: TagValue = payload.hex()
            elif child.element_id == 0x29BF:
                name = "ChapterTranslateCodec"
                value = _mapped(_unsigned(payload), TRANSLATE_CODECS)
            elif child.element_id == 0x29A5:
                name = "ChapterTranslateID"
                value = BinaryTagValue(payload)
                diagnostics.append(
                    "Matroska ChapterTranslateID binary payload is source-defined but "
                    "emitted as BinaryTagValue; ExifTool reports it as binary data."
                )
            else:
                continue
            tags.append(
                MatroskaDecodedTag(
                    name,
                    value,
                    f"0x{child.element_id:x}",
                    "matroska-chapter-translate",
                    family_1_group="Info",
                    duplicate_instance_ordinal=translate_index if translate_index > 0 else None,
                )
            )
    return tags


def _cue_tags(
    data: bytes,
    elements: list[AdapterEbmlElement],
    timecode_scale: int,
) -> list[MatroskaDecodedTag]:
    tags: list[MatroskaDecodedTag] = []
    cue_points = [element for element in elements if element.element_id == CUE_POINT_ID]
    for cue_index, cue_point in enumerate(cue_points):
        children = _descendants(elements, cue_point)
        for child in children:
            payload = data[child.payload_offset : child.payload_offset + child.payload_size]
            name = _cue_tag_name(child.element_id)
            if name is None:
                continue
            value: TagValue
            if child.element_id in {0x33, 0x16}:
                value = _scaled_timecode(_unsigned(payload), timecode_scale)
            else:
                value = _unsigned(payload)
            tags.append(
                MatroskaDecodedTag(
                    name,
                    value,
                    f"0x{child.element_id:x}",
                    "matroska-cues",
                    family_1_group="Cues",
                    duplicate_instance_ordinal=cue_index if cue_index > 0 else None,
                )
            )
    return tags


def _attachment_tags(
    data: bytes,
    elements: list[AdapterEbmlElement],
    diagnostics: list[str],
) -> list[MatroskaDecodedTag]:
    tags: list[MatroskaDecodedTag] = []
    attached_files = [element for element in elements if element.element_id == ATTACHED_FILE_ID]
    for file_index, attached_file in enumerate(attached_files):
        children = _descendants(elements, attached_file)
        for child in children:
            payload = data[child.payload_offset : child.payload_offset + child.payload_size]
            name = _attachment_tag_name(child.element_id)
            if child.element_id in {0x65C, 0x675}:
                diagnostics.append(
                    f"Matroska {child.element_id:#x} binary attachment payload is source-defined "
                    "and emitted as BinaryTagValue; ExifTool reports it as binary data."
                )
            if name is None:
                continue
            value: TagValue = (
                BinaryTagValue(payload)
                if child.element_id in {0x65C, 0x675}
                else payload.hex()
                if child.element_id == 0x6AE
                else decode_ebml_text(payload)
            )
            tags.append(
                MatroskaDecodedTag(
                    name,
                    value,
                    f"0x{child.element_id:x}",
                    "matroska-attachments",
                    family_1_group=f"AttachedFile{file_index + 1}",
                    duplicate_instance_ordinal=file_index if file_index > 0 else None,
                )
            )
    return tags


def _chapter_tags(data: bytes, elements: list[AdapterEbmlElement]) -> list[MatroskaDecodedTag]:
    tags: list[MatroskaDecodedTag] = []
    tags.extend(_edition_tags(data, elements))
    chapter_atoms = [element for element in elements if element.element_id == CHAPTER_ATOM_ID]
    for chapter_index, chapter_atom in enumerate(chapter_atoms):
        children = _descendants(elements, chapter_atom)
        for child in children:
            payload = data[child.payload_offset : child.payload_offset + child.payload_size]
            name = _chapter_tag_name(child.element_id)
            if name is None:
                continue
            value = _chapter_tag_value(child.element_id, payload)
            tags.append(
                MatroskaDecodedTag(
                    name,
                    value,
                    f"0x{child.element_id:x}",
                    "matroska-chapters",
                    family_1_group=f"Chapter{chapter_index + 1}",
                    family_2_group="Time" if child.element_id in {0x11, 0x12} else "Video",
                    duplicate_instance_ordinal=chapter_index if chapter_index > 0 else None,
                )
            )
    return tags


def _edition_tags(data: bytes, elements: list[AdapterEbmlElement]) -> list[MatroskaDecodedTag]:
    tags: list[MatroskaDecodedTag] = []
    edition_entries = [element for element in elements if element.element_id == EDITION_ENTRY_ID]
    names = {
        0x5BC: "EditionUID",
        0x5BD: "EditionFlagHidden",
        0x5DB: "EditionFlagDefault",
        0x5DD: "EditionFlagOrdered",
    }
    for edition_index, edition_entry in enumerate(edition_entries):
        for child in _direct_children(elements, edition_entry):
            name = names.get(child.element_id)
            if name is None:
                continue
            payload = data[child.payload_offset : child.payload_offset + child.payload_size]
            value: TagValue = payload.hex() if child.element_id == 0x5BC else _unsigned(payload)
            tags.append(
                MatroskaDecodedTag(
                    name,
                    value,
                    f"0x{child.element_id:x}",
                    "matroska-chapters",
                    family_1_group=f"Edition{edition_index + 1}",
                    duplicate_instance_ordinal=edition_index if edition_index > 0 else None,
                )
            )
    return tags


def _target_tags(
    data: bytes,
    elements: list[AdapterEbmlElement],
    track_uid_groups: dict[str, str],
) -> list[MatroskaDecodedTag]:
    tags: list[MatroskaDecodedTag] = []
    targets_elements = [element for element in elements if element.element_id == TARGETS_ID]
    for target_index, targets in enumerate(targets_elements):
        group = _targets_family_1_group(data, elements, targets, track_uid_groups)
        for child in _direct_children(elements, targets):
            payload = data[child.payload_offset : child.payload_offset + child.payload_size]
            name = _target_tag_name(child.element_id)
            if name is None:
                continue
            value = _target_tag_value(child.element_id, payload)
            tags.append(
                MatroskaDecodedTag(
                    name,
                    value,
                    f"0x{child.element_id:x}",
                    "matroska-targets",
                    family_1_group=group,
                    duplicate_instance_ordinal=target_index if target_index > 0 else None,
                )
            )
    return tags


def _track_child_tag(
    element: AdapterEbmlElement,
    data: bytes,
    track_type: int | None,
    track_index: int,
    diagnostics: list[str],
) -> MatroskaDecodedTag | None:
    payload = data[element.payload_offset : element.payload_offset + (element.payload_size or 0)]
    family_2_group = "Audio" if _is_audio_track_element(element, track_type) else "Video"
    duplicate = track_index if track_index > 0 else None
    common_kwargs = {
        "family_1_group": f"Track{track_index + 1}",
        "family_2_group": family_2_group,
        "duplicate_instance_ordinal": duplicate,
    }
    if element.element_id == 0x57:
        return _track_tag(
            "TrackNumber", _unsigned(payload), "0x57", "matroska-track-entry", common_kwargs
        )
    if element.element_id == 0x33C5:
        return _track_tag(
            "TrackUID", payload.hex(), "0x33c5", "matroska-track-entry", common_kwargs
        )
    if element.element_id == TRACK_TYPE_ID:
        raw_value = _unsigned(payload)
        track_type_value = TRACK_TYPE_NAMES.get(raw_value, f"Unknown ({raw_value})")
        return _track_tag(
            "TrackType", track_type_value, "0x3", "matroska-track-entry", common_kwargs
        )
    if element.element_id == 0x136E:
        return _track_tag(
            "TrackName", decode_ebml_text(payload), "0x136e", "matroska-track-entry", common_kwargs
        )
    if element.element_id == 0x2B59C:
        return _track_tag(
            "TrackLanguage",
            decode_ebml_text(payload),
            "0x2b59c",
            "matroska-track-entry",
            common_kwargs,
        )
    if element.element_id == 0x2B59D:
        return _track_tag(
            "TrackLanguageIETF",
            decode_ebml_text(payload),
            "0x2b59d",
            "matroska-track-entry",
            common_kwargs,
        )
    if element.element_id in {0x39, 0x08, 0x15AA, 0x1C, 0x2A}:
        names = {
            0x39: "TrackUsed",
            0x08: "TrackDefault",
            0x15AA: "TrackForced",
            0x1C: "TrackLacing",
            0x2A: "CodecDecodeAll",
        }
        return _track_tag(
            names[element.element_id],
            _no_yes(_unsigned(payload)),
            f"0x{element.element_id:x}",
            "matroska-track-entry",
            common_kwargs,
        )
    if element.element_id in {0x2DE7, 0x2DF8, 0x15EE, 0x3446, 0x2FAB}:
        names = {
            0x2DE7: "MinCache",
            0x2DF8: "MaxCache",
            0x15EE: "MaxBlockAdditionID",
            0x3446: "TrackAttachmentUID",
            0x2FAB: "TrackOverlay",
        }
        track_uid_value: TagValue = (
            payload.hex() if element.element_id == 0x3446 else _unsigned(payload)
        )
        return _track_tag(
            names[element.element_id],
            track_uid_value,
            f"0x{element.element_id:x}",
            "matroska-track-entry",
            common_kwargs,
        )
    if element.element_id == 0x137F:
        return _track_tag(
            "TrackOffset",
            _signed(payload),
            "0x137f",
            "matroska-track-entry",
            common_kwargs,
        )
    if element.element_id in {0x26FC, 0x26BF}:
        if element.element_id == 0x26FC:
            name = "TrackTranslateEditionUID"
            track_translate_value: TagValue = payload.hex()
        else:
            name = "TrackTranslateCodec"
            track_translate_value = _mapped(_unsigned(payload), TRANSLATE_CODECS)
        return _track_tag(
            name,
            track_translate_value,
            f"0x{element.element_id:x}",
            "matroska-track-translate",
            common_kwargs,
        )
    if element.element_id == 0x3314F:
        return _track_tag(
            "TrackTimecodeScale",
            _integer_if_whole(_float(payload)),
            "0x3314f",
            "matroska-track-entry",
            common_kwargs,
        )
    if element.element_id in {0x1A9697, 0x1B4040, 0x6B240}:
        names = {
            0x1A9697: "CodecSettings",
            0x1B4040: "CodecInfoURL",
            0x6B240: "CodecDownloadURL",
        }
        return _track_tag(
            names[element.element_id],
            decode_ebml_text(payload),
            f"0x{element.element_id:x}",
            "matroska-track-entry",
            common_kwargs,
        )
    if element.element_id in {0x23A2, 0x26A5, 0xEB524, 0x3D7B, 0x255, 0x7E2, 0x7E3, 0x7E4}:
        names = {
            0x23A2: "CodecPrivate",
            0x26A5: "TrackTranslateTrackID",
            0xEB524: "ColorSpace",
            0x3D7B: "ChannelPositions",
            0x255: "ContentCompressionSettings",
            0x7E2: "ContentEncryptionKeyID",
            0x7E3: "ContentSignature",
            0x7E4: "ContentSignatureKeyID",
        }
        source = (
            "matroska-content-encoding"
            if element.element_id in {0x255, 0x7E2, 0x7E3, 0x7E4}
            else "matroska-track-translate"
            if element.element_id == 0x26A5
            else "matroska-track-entry"
        )
        diagnostics.append(
            f"Matroska {element.element_id:#x} binary track payload is source-defined "
            "and emitted as BinaryTagValue; ExifTool reports it as binary data."
        )
        return _track_tag(
            names[element.element_id],
            BinaryTagValue(payload),
            f"0x{element.element_id:x}",
            source,
            common_kwargs,
        )
    if element.element_id == 0x06:
        name = _track_type_tag_name(track_type, "VideoCodecID", "AudioCodecID", "CodecID")
        return _track_tag(
            name, decode_ebml_text(payload), "0x6", "matroska-track-entry", common_kwargs
        )
    if element.element_id == 0x58688:
        name = _track_type_tag_name(track_type, "VideoCodecName", "AudioCodecName", "CodecName")
        return _track_tag(
            name, decode_ebml_text(payload), "0x58688", "matroska-track-entry", common_kwargs
        )
    if element.element_id == 0x3E383:
        default_duration_ns = _unsigned(payload)
        name = "VideoFrameRate" if track_type == VIDEO_TRACK_TYPE else "DefaultDuration"
        rendered: TagValue = (
            _integer_if_whole(round(1_000_000_000 / default_duration_ns, 3))
            if track_type == VIDEO_TRACK_TYPE and default_duration_ns
            else _milliseconds_text(default_duration_ns / 1_000_000)
        )
        return _track_tag(name, rendered, "0x3e383", "matroska-track-entry", common_kwargs)
    if element.element_id in {
        0x1A,
        0x13B8,
        0x30,
        0x3A,
        0x14AA,
        0x14BB,
        0x14CC,
        0x14DD,
        0x14B0,
        0x14BA,
        0x14B2,
        0x14B3,
        0xFB523,
        0x383E3,
    }:
        names = {
            0x1A: "VideoScanType",
            0x13B8: "Stereo3DMode",
            0x30: "ImageWidth",
            0x3A: "ImageHeight",
            0x14AA: "CropBottom",
            0x14BB: "CropTop",
            0x14CC: "CropLeft",
            0x14DD: "CropRight",
            0x14B0: "DisplayWidth",
            0x14BA: "DisplayHeight",
            0x14B2: "DisplayUnit",
            0x14B3: "AspectRatioType",
            0xFB523: "Gamma",
            0x383E3: "FrameRate",
        }
        raw_video_value = (
            _float(payload) if element.element_id in {0xFB523, 0x383E3} else _unsigned(payload)
        )
        video_value: TagValue
        if element.element_id == 0x1A and isinstance(raw_video_value, int):
            video_value = _mapped(raw_video_value, VIDEO_SCAN_TYPES)
        elif element.element_id == 0x13B8 and isinstance(raw_video_value, int):
            video_value = _mapped(raw_video_value, STEREO_3D_MODES)
        elif element.element_id == 0x14B2 and isinstance(raw_video_value, int):
            video_value = _mapped(raw_video_value, DISPLAY_UNITS)
        elif element.element_id == 0x14B3 and isinstance(raw_video_value, int):
            video_value = _mapped(raw_video_value, ASPECT_RATIO_TYPES)
        else:
            video_value = raw_video_value
        return _track_tag(
            names[element.element_id],
            video_value,
            f"0x{element.element_id:x}",
            "matroska-track-video",
            common_kwargs,
        )
    if element.element_id in {0x35, 0x38B5, 0x1F, 0x2264}:
        names = {
            0x35: "AudioSampleRate",
            0x38B5: "OutputAudioSampleRate",
            0x1F: "AudioChannels",
            0x2264: "AudioBitsPerSample",
        }
        audio_value: TagValue = (
            _float(payload) if element.element_id in {0x35, 0x38B5} else _unsigned(payload)
        )
        if element.element_id in {0x35, 0x38B5}:
            audio_value = _integer_if_whole(audio_value)
        return _track_tag(
            names[element.element_id],
            audio_value,
            f"0x{element.element_id:x}",
            "matroska-track-audio",
            common_kwargs,
        )
    if element.element_id in {0x1031, 0x1032, 0x1033, 0x254, 0x7E1, 0x7E5, 0x7E6}:
        names = {
            0x1031: "ContentEncodingOrder",
            0x1032: "ContentEncodingScope",
            0x1033: "ContentEncodingType",
            0x254: "ContentCompressionAlgorithm",
            0x7E1: "ContentEncryptionAlgorithm",
            0x7E5: "ContentSignatureAlgorithm",
            0x7E6: "ContentSignatureHashAlgorithm",
        }
        raw_encoding_value = _unsigned(payload)
        encoding_maps = {
            0x1033: CONTENT_ENCODING_TYPES,
            0x254: CONTENT_COMPRESSION_ALGORITHMS,
            0x7E1: CONTENT_ENCRYPTION_ALGORITHMS,
            0x7E5: CONTENT_SIGNATURE_ALGORITHMS,
            0x7E6: CONTENT_SIGNATURE_HASH_ALGORITHMS,
        }
        encoding_value: TagValue = (
            _mapped(raw_encoding_value, encoding_maps[element.element_id])
            if element.element_id in encoding_maps
            else raw_encoding_value
        )
        return _track_tag(
            names[element.element_id],
            encoding_value,
            f"0x{element.element_id:x}",
            "matroska-content-encoding",
            common_kwargs,
        )
    if element.element_id in {0x7671, 0x7672, 0x7673, 0x7674, 0x7675}:
        if element.element_id == 0x7672:
            diagnostics.append(
                "Matroska ProjectionPrivate is source-defined but omitted from public read output; "
                "ExifTool delegates equirectangular/cubemap binary payloads to QuickTime "
                "projection tables."
            )
            return None
        names = {
            0x7671: "ProjectionType",
            0x7673: "ProjectionPoseYaw",
            0x7674: "ProjectionPosePitch",
            0x7675: "ProjectionPoseRoll",
        }
        projection_value: TagValue = (
            _mapped(_unsigned(payload), PROJECTION_TYPES)
            if element.element_id == 0x7671
            else _float(payload)
        )
        return _track_tag(
            names[element.element_id],
            projection_value,
            f"0x{element.element_id:x}",
            "matroska-projection",
            common_kwargs,
        )
    if element.element_id == CLUSTER_ID:
        return None
    return None


def _walk_metadata_elements(
    data: bytes,
    start: int,
    end: int,
    parent_path: tuple[int, ...],
) -> list[AdapterEbmlElement]:
    elements: list[AdapterEbmlElement] = []
    offset = start
    while offset < end:
        try:
            element_id = read_ebml_vint(data, offset)
            size = read_ebml_vint(data, element_id.next_offset)
        except ValueError:
            break
        if size.is_unknown_size:
            break
        payload_offset = size.next_offset
        payload_end = payload_offset + size.value
        if payload_end > end or payload_end > len(data):
            if element_id.value != SEGMENT_ID:
                break
            payload_end = min(end, len(data))
        path = (*parent_path, element_id.value)
        element = AdapterEbmlElement(
            element_id=element_id.value,
            offset=offset,
            payload_offset=payload_offset,
            payload_size=size.value,
            end_offset=payload_end,
            path=path,
        )
        elements.append(element)
        if element_id.value in METADATA_MASTER_IDS and element_id.value != CLUSTER_ID:
            elements.extend(_walk_metadata_elements(data, payload_offset, payload_end, path))
        if element_id.value == CLUSTER_ID:
            break
        offset = payload_end
    return elements


def _with_seek_directed_post_cluster_metadata(
    data: bytes,
    elements: list[AdapterEbmlElement],
    diagnostics: list[str],
    *,
    external_tag_offsets: set[int] | None = None,
) -> list[AdapterEbmlElement]:
    external_tag_offsets = external_tag_offsets or set()
    cluster_payload_offset = next(
        (element.payload_offset for element in elements if element.element_id == CLUSTER_ID),
        None,
    )
    if cluster_payload_offset is None:
        cluster_payload_offset = _first_cluster_payload_offset(data)
    if cluster_payload_offset is None:
        return elements

    existing_offsets = {element.offset for element in elements}
    extended = list(elements)
    for target_offset in _seek_target_offsets(data, elements).get("Tags", ()):
        if target_offset in external_tag_offsets:
            continue
        if target_offset <= cluster_payload_offset or target_offset in existing_offsets:
            continue
        if target_offset >= len(data):
            diagnostics.append(
                "Matroska SeekHead points to post-Cluster Tags at offset "
                f"{target_offset}, but the provided byte window ends at {len(data)}; "
                "bounded traversal will not scan Cluster media payloads to reach it."
            )
            continue
        try:
            target_id = read_ebml_vint(data, target_offset)
        except ValueError:
            diagnostics.append(
                "Matroska SeekHead points to post-Cluster Tags at offset "
                f"{target_offset}, but the target EBML ID is truncated or invalid."
            )
            continue
        if target_id.value != TAGS_ID:
            diagnostics.append(
                "Matroska SeekHead post-Cluster Tags target at offset "
                f"{target_offset} resolves to 0x{target_id.value:x}; bounded traversal "
                "requires a source-defined Tags element at the seek target."
            )
            continue
        jumped = _walk_metadata_elements(data, target_offset, len(data), (SEGMENT_ID,))
        if not jumped:
            diagnostics.append(
                "Matroska SeekHead post-Cluster Tags target at offset "
                f"{target_offset} could not be parsed as a complete Tags element."
            )
            continue
        extended.extend(element for element in jumped if element.offset not in existing_offsets)
        existing_offsets.update(element.offset for element in jumped)
        diagnostics.append(
            "Matroska SeekHead-directed traversal jumped over Cluster media payload "
            f"to post-Cluster Tags at offset {target_offset}."
        )
    return extended


def _first_cluster_payload_offset(data: bytes) -> int | None:
    segment = _first_top_level_element(data, SEGMENT_ID)
    if segment is None:
        return None
    offset = segment.payload_offset
    end = min(segment.end_offset, len(data))
    while offset < end:
        try:
            element_id = read_ebml_vint(data, offset)
            size = read_ebml_vint(data, element_id.next_offset)
        except ValueError:
            return None
        if element_id.value == CLUSTER_ID:
            return size.next_offset
        if size.is_unknown_size:
            return None
        payload_end = size.next_offset + size.value
        if payload_end > end:
            return size.next_offset if element_id.value == CLUSTER_ID else None
        offset = payload_end
    return None


def _first_top_level_element(data: bytes, target_id: int) -> AdapterEbmlElement | None:
    offset = 0
    while offset < len(data):
        try:
            element_id = read_ebml_vint(data, offset)
            size = read_ebml_vint(data, element_id.next_offset)
        except ValueError:
            return None
        if size.is_unknown_size:
            return None
        payload_offset = size.next_offset
        payload_end = payload_offset + size.value
        if payload_end > len(data):
            return None
        if element_id.value == target_id:
            return AdapterEbmlElement(
                element_id=element_id.value,
                offset=offset,
                payload_offset=payload_offset,
                payload_size=size.value,
                end_offset=payload_end,
                path=(element_id.value,),
            )
        offset = payload_end
    return None


def _seek_target_offsets(
    data: bytes,
    elements: list[AdapterEbmlElement],
) -> dict[str, tuple[int, ...]]:
    targets: dict[str, list[int]] = {}
    seek_heads = {
        element.path: element for element in elements if element.element_id == SEEK_HEAD_ID
    }
    segments = {element.path: element for element in elements if element.element_id == SEGMENT_ID}
    seek_elements = [element for element in elements if element.element_id == 0x0DBB]
    for seek_element in seek_elements:
        target_name: str | None = None
        target_position: int | None = None
        for child in _direct_children(elements, seek_element):
            payload = data[child.payload_offset : child.payload_offset + child.payload_size]
            if child.element_id == SEEK_ID:
                try:
                    target_id = read_ebml_vint(payload, 0).value
                except ValueError:
                    continue
                target_name = SEEK_TARGET_NAMES.get(target_id)
            elif child.element_id == SEEK_POSITION_ID:
                seek_head = _nearest_parent(child, seek_heads)
                base_offset = (
                    _seek_position_base_offset(seek_head, segments) if seek_head is not None else 0
                )
                target_position = _unsigned(payload) + base_offset
        if target_name is not None and target_position is not None:
            targets.setdefault(target_name, []).append(target_position)
    return {name: tuple(offsets) for name, offsets in targets.items()}


def _descendants(
    elements: list[AdapterEbmlElement],
    parent: AdapterEbmlElement,
) -> list[AdapterEbmlElement]:
    return [
        element
        for element in elements
        if element.offset > parent.offset and element.end_offset <= parent.end_offset
    ]


def _nearest_parent(
    element: AdapterEbmlElement,
    parents_by_path: dict[tuple[int, ...], AdapterEbmlElement],
) -> AdapterEbmlElement | None:
    for length in range(len(element.path) - 1, 0, -1):
        parent = parents_by_path.get(element.path[:length])
        if parent is not None:
            return parent
    return None


def _timecode_scale(plan: MatroskaEbmlTransactionPlan) -> int:
    for scalar in plan.scalars:
        if scalar.name != "TimecodeScale":
            continue
        if isinstance(scalar.raw_value, int):
            return scalar.raw_value
    return 0


def _seek_id_value(payload: bytes) -> str | None:
    try:
        value = read_ebml_vint(payload, 0).value
    except ValueError:
        return None
    suffix = SEEK_TARGET_NAMES.get(value)
    rendered = f"0x{value:x}"
    return f"{rendered} ({suffix})" if suffix is not None else rendered


def _seek_position_base_offset(
    seek_head: AdapterEbmlElement,
    segments_by_path: dict[tuple[int, ...], AdapterEbmlElement],
) -> int:
    # Matroska SeekPosition is relative to the Segment payload.  In front-loaded
    # mkvmerge files this is also the SeekHead element start; using the post-ID
    # offset lands on the following element's size VInt instead of its ID.
    for length in range(len(seek_head.path) - 1, 0, -1):
        segment = segments_by_path.get(seek_head.path[:length])
        if segment is not None:
            return segment.payload_offset
    return seek_head.offset


def _scaled_timecode(value: int, timecode_scale: int) -> int | float:
    return value * timecode_scale / 1_000_000_000 if timecode_scale else value


def _integer_if_whole(value: TagValue) -> TagValue:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _milliseconds_text(milliseconds: float) -> str:
    value = _integer_if_whole(milliseconds)
    return f"{value} ms"


def _duration_text(seconds: float) -> str:
    rounded = int(seconds + 0.5)
    hours = rounded // 3600
    minutes = (rounded % 3600) // 60
    remaining_seconds = rounded % 60
    return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"


def _matroska_composite_tags(tags: list[ReadTag]) -> list[ReadTag]:
    width = _first_integer_tag_value(tags, "ImageWidth")
    height = _first_integer_tag_value(tags, "ImageHeight")
    if width is None or height is None:
        return []
    megapixels = round(width * height / 1_000_000, 3)
    return [
        _read_tag(
            "ImageSize",
            f"{width}x{height}",
            "Composite",
            "Image::ExifTool::Composite",
            "ImageSize",
            "matroska-derived-image",
            family_1_group="Composite",
            family_2_group="Image",
        ),
        _read_tag(
            "Megapixels",
            megapixels,
            "Composite",
            "Image::ExifTool::Composite",
            "Megapixels",
            "matroska-derived-image",
            family_1_group="Composite",
            family_2_group="Image",
        ),
    ]


def _first_integer_tag_value(tags: list[ReadTag], name: str) -> int | None:
    for tag in tags:
        if tag.name == name and isinstance(tag.value, int):
            return tag.value
    return None


def _cue_tag_name(element_id: int) -> str | None:
    names = {
        0x33: "CueTime",
        0x77: "CueTrack",
        0x71: "CueClusterPosition",
        0x1378: "CueBlockNumber",
        0x6A: "CueCodecState",
        0x16: "CueRefTime",
        0x17: "CueRefCluster",
        0x135F: "CueRefNumber",
        0x6B: "CueRefCodecState",
    }
    return names.get(element_id)


def _attachment_tag_name(element_id: int) -> str | None:
    names = {
        0x67E: "AttachedFileDescription",
        0x66E: "AttachedFileName",
        0x660: "AttachedFileMIMEType",
        0x65C: "AttachedFileData",
        0x6AE: "AttachedFileUID",
        0x675: "AttachedFileReferral",
    }
    return names.get(element_id)


def _chapter_tag_name(element_id: int) -> str | None:
    names = {
        0x33C4: "ChapterUID",
        0x11: "ChapterTimeStart",
        0x12: "ChapterTimeEnd",
        0x18: "ChapterFlagHidden",
        0x598: "ChapterFlagEnabled",
        0x2E67: "ChapterSegmentUID",
        0x2EBC: "ChapterSegmentEditionUID",
        0x23C3: "ChapterPhysicalEquivalent",
        0x09: "ChapterTrackNumber",
        0x05: "ChapterString",
        0x37C: "ChapterLanguage",
        0x37E: "ChapterCountry",
        0x2955: "ChapterProcessCodecID",
        0x50D: "ChapterProcessPrivate",
        0x2922: "ChapterProcessTime",
        0x2933: "ChapterProcessData",
    }
    return names.get(element_id)


def _chapter_tag_value(element_id: int, payload: bytes) -> TagValue:
    if element_id in {0x50D, 0x2933}:
        return BinaryTagValue(payload)
    if element_id in {0x33C4, 0x2E67, 0x2EBC}:
        return payload.hex()
    if element_id in {0x05, 0x37C, 0x37E}:
        return decode_ebml_text(payload)
    raw = _unsigned(payload)
    if element_id in {0x11, 0x12}:
        return raw / 1_000_000_000
    if element_id == 0x23C3:
        return _mapped(raw, CHAPTER_PHYSICAL_EQUIVALENTS)
    if element_id == 0x2955:
        return _mapped(raw, CHAPTER_PROCESS_CODECS)
    if element_id == 0x2922:
        return _mapped(raw, CHAPTER_PROCESS_TIMES)
    return raw


def _simple_tag_tags(
    data: bytes,
    elements: list[AdapterEbmlElement],
    diagnostics: list[str],
    track_uid_groups: dict[str, str],
) -> list[MatroskaDecodedTag]:
    tags: list[MatroskaDecodedTag] = []
    tag_family_groups = _tag_family_1_groups(data, elements, track_uid_groups)
    simple_tags = [element for element in elements if element.element_id == SIMPLE_TAG_ID]
    for simple_tag in simple_tags:
        parent_context = _simple_tag_parent_context(data, elements, simple_tag)
        direct_children = _direct_children(elements, simple_tag)
        tag_name = _simple_tag_text_child(data, direct_children, TAG_NAME_ID)
        if tag_name is None:
            continue
        normalized = tag_name.upper()
        local_name = _simple_tag_output_name(normalized)
        parent_output_name = None if parent_context is None else parent_context.output_name
        parent_tag_id = None if parent_context is None else parent_context.tag_id
        if parent_tag_id == "COUNTRY":
            parent_output_name = None
            parent_tag_id = None
        output_base_name = (
            f"{parent_output_name}/{local_name}" if parent_output_name else local_name
        )
        tag_id_base = f"{parent_tag_id}/{normalized}" if parent_tag_id else normalized
        language = _simple_tag_text_child(data, direct_children, TAG_LANGUAGE_BCP47_ID)
        country = None if parent_context is None else parent_context.country
        if language is None and parent_context is not None:
            language = parent_context.language
        language_code = _simple_tag_language_code(language, country)
        output_name = _simple_tag_localized_name(output_base_name, language_code)
        tag_id = _simple_tag_localized_name(tag_id_base, language_code)
        if _simple_tag_unsigned_child(data, direct_children, TAG_DEFAULT_ID) is not None:
            diagnostics.append(
                f"Matroska SimpleTag {tag_id_base} carries TagDefault; ExifTool "
                "HandleStruct records it in the SimpleTag structure but does not apply it "
                "when rendering public tags."
            )
        tag_string = _simple_tag_text_child(data, direct_children, TAG_STRING_ID)
        binary_child = next(
            (child for child in direct_children if child.element_id == TAG_BINARY_ID),
            None,
        )
        if binary_child is not None and tag_string is not None:
            diagnostics.append(
                f"Matroska SimpleTag {tag_id} carries TagBinary and TagString; ExifTool "
                "HandleStruct prefers TagString, so public read output preserves the string value."
            )
        if tag_string is None:
            if binary_child is None:
                continue
            payload_start = binary_child.payload_offset
            payload_end = payload_start + binary_child.payload_size
            payload = data[payload_start:payload_end]
            tags.append(
                MatroskaDecodedTag(
                    output_name,
                    BinaryTagValue(payload),
                    tag_id,
                    "matroska-simple-tag-binary",
                    table_name=MATROSKA_STD_TAG_TABLE,
                    family_1_group=_simple_tag_family_1_group(simple_tag, tag_family_groups),
                    family_2_group="Video",
                )
            )
            continue
        tags.append(
            MatroskaDecodedTag(
                output_name,
                tag_string,
                tag_id,
                "matroska-simple-tag",
                table_name=MATROSKA_STD_TAG_TABLE,
                family_1_group=_simple_tag_family_1_group(simple_tag, tag_family_groups),
                family_2_group="Video",
            )
        )
    return tags


def _simple_tag_parent_context(
    data: bytes,
    elements: list[AdapterEbmlElement],
    simple_tag: AdapterEbmlElement,
) -> SimpleTagContext | None:
    parent_simple_tags = [
        element
        for element in elements
        if element.element_id == SIMPLE_TAG_ID
        and element.offset < simple_tag.offset
        and element.end_offset >= simple_tag.end_offset
    ]
    if not parent_simple_tags:
        return None
    nearest = max(parent_simple_tags, key=lambda element: element.offset)
    parent = _simple_tag_parent_context(data, elements, nearest)
    direct_children = _direct_children(elements, nearest)
    tag_name = _simple_tag_text_child(data, direct_children, TAG_NAME_ID)
    if tag_name is None:
        return parent
    normalized = tag_name.upper()
    local_name = _simple_tag_output_name(normalized)
    if parent is not None and parent.tag_id == "COUNTRY":
        output_name = local_name
        tag_id = normalized
    else:
        output_name = f"{parent.output_name}/{local_name}" if parent is not None else local_name
        tag_id = f"{parent.tag_id}/{normalized}" if parent is not None else normalized
    language = _simple_tag_text_child(data, direct_children, TAG_LANGUAGE_BCP47_ID)
    if language is None and parent is not None:
        language = parent.language
    tag_string = _simple_tag_text_child(data, direct_children, TAG_STRING_ID)
    country = None if parent is None else parent.country
    if normalized == "COUNTRY" and tag_string is not None:
        country = tag_string
        output_name = "" if parent is None else parent.output_name
        tag_id = "" if parent is None else parent.tag_id
    return SimpleTagContext(tag_id, output_name, language, country)


def _direct_children(
    elements: list[AdapterEbmlElement],
    parent: AdapterEbmlElement,
) -> list[AdapterEbmlElement]:
    return [
        element
        for element in elements
        if element.offset > parent.offset
        and element.end_offset <= parent.end_offset
        and element.path[:-1] == parent.path
    ]


def _simple_tag_text_child(
    data: bytes,
    children: list[AdapterEbmlElement],
    element_id: int,
) -> str | None:
    for child in children:
        if child.element_id != element_id:
            continue
        payload = data[child.payload_offset : child.payload_offset + child.payload_size]
        return decode_ebml_text(payload)
    return None


def _simple_tag_unsigned_child(
    data: bytes,
    children: list[AdapterEbmlElement],
    element_id: int,
) -> int | None:
    for child in children:
        if child.element_id != element_id:
            continue
        payload = data[child.payload_offset : child.payload_offset + child.payload_size]
        return _unsigned(payload)
    return None


def _simple_tag_language_code(language: str | None, country: str | None) -> str | None:
    if country is not None:
        if language:
            return f"{language}-{country}"
        return f"eng-{country}"
    return language


def _simple_tag_localized_name(name: str, language_code: str | None) -> str:
    if language_code:
        return f"{name}-{language_code}"
    return name


def _simple_tag_output_name(tag_name: str) -> str:
    return (
        standardized_output_name(tag_name)
        if tag_name in STANDARD_SIMPLE_TAGS
        else generated_output_name(tag_name)
    )


def _track_uid_groups(
    data: bytes,
    elements: list[AdapterEbmlElement],
) -> dict[str, str]:
    groups: dict[str, str] = {}
    track_entries = [element for element in elements if element.element_id == TRACK_ENTRY_ID]
    for track_index, track_entry in enumerate(track_entries):
        direct_children = _direct_children(elements, track_entry)
        track_number = _track_number(data, direct_children) or track_index + 1
        track_uid = _track_uid(data, direct_children)
        if track_uid is not None:
            groups[track_uid] = f"Track{track_number}"
    return groups


def _track_number(data: bytes, children: list[AdapterEbmlElement]) -> int | None:
    for child in children:
        if child.element_id != 0x57:
            continue
        payload = data[child.payload_offset : child.payload_offset + child.payload_size]
        return _unsigned(payload)
    return None


def _track_uid(data: bytes, children: list[AdapterEbmlElement]) -> str | None:
    for child in children:
        if child.element_id != 0x33C5:
            continue
        payload = data[child.payload_offset : child.payload_offset + child.payload_size]
        return payload.hex()
    return None


def _tag_family_1_groups(
    data: bytes,
    elements: list[AdapterEbmlElement],
    track_uid_groups: dict[str, str],
) -> dict[tuple[int, ...], str]:
    groups: dict[tuple[int, ...], str] = {}
    tag_elements = [element for element in elements if element.element_id == TAG_ID]
    for tag_element in tag_elements:
        targets = next(
            (
                child
                for child in _direct_children(elements, tag_element)
                if child.element_id == TARGETS_ID
            ),
            None,
        )
        if targets is None:
            continue
        groups[tag_element.path] = _targets_family_1_group(
            data,
            elements,
            targets,
            track_uid_groups,
        )
    return groups


def _targets_family_1_group(
    data: bytes,
    elements: list[AdapterEbmlElement],
    targets: AdapterEbmlElement,
    track_uid_groups: dict[str, str],
) -> str:
    for child in _direct_children(elements, targets):
        if child.element_id != TAG_TRACK_UID_ID:
            continue
        payload = data[child.payload_offset : child.payload_offset + child.payload_size]
        group = track_uid_groups.get(payload.hex())
        if group is not None:
            return group
    return "Matroska"


def _simple_tag_family_1_group(
    simple_tag: AdapterEbmlElement,
    tag_family_groups: dict[tuple[int, ...], str],
) -> str:
    for length in range(len(simple_tag.path) - 1, 0, -1):
        group = tag_family_groups.get(simple_tag.path[:length])
        if group is not None:
            return group
    return "Matroska"


def _target_tag_name(element_id: int) -> str | None:
    names = {
        0x28CA: "TargetTypeValue",
        0x23CA: "TargetType",
        TAG_TRACK_UID_ID: "TagTrackUID",
        0x23C9: "TagEditionUID",
        0x23C4: "TagChapterUID",
        0x23C6: "TagAttachmentUID",
    }
    return names.get(element_id)


def _target_tag_value(element_id: int, payload: bytes) -> TagValue:
    if element_id == 0x28CA:
        raw = _unsigned(payload)
        return TARGET_TYPE_VALUES.get(raw, raw)
    if element_id == 0x23CA:
        return decode_ebml_text(payload)
    return payload.hex()


def _track_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    source: str,
    common_kwargs: dict[str, str | int | None],
) -> MatroskaDecodedTag:
    family_1_group = common_kwargs["family_1_group"]
    family_2_group = common_kwargs["family_2_group"]
    duplicate_instance_ordinal = common_kwargs["duplicate_instance_ordinal"]
    return MatroskaDecodedTag(
        name,
        value,
        tag_id,
        source,
        family_1_group=family_1_group if isinstance(family_1_group, str) else "Matroska",
        family_2_group=family_2_group if isinstance(family_2_group, str) else "Video",
        duplicate_instance_ordinal=(
            duplicate_instance_ordinal if isinstance(duplicate_instance_ordinal, int) else None
        ),
    )


def _track_type_tag_name(
    track_type: int | None,
    video_name: str,
    audio_name: str,
    fallback_name: str,
) -> str:
    if track_type == VIDEO_TRACK_TYPE:
        return video_name
    if track_type == AUDIO_TRACK_TYPE:
        return audio_name
    return fallback_name


def _track_type(elements: list[AdapterEbmlElement], data: bytes) -> int | None:
    for element in elements:
        if element.element_id != TRACK_TYPE_ID or element.payload_size is None:
            continue
        payload = data[element.payload_offset : element.payload_offset + element.payload_size]
        return _unsigned(payload)
    return None


def _is_audio_track_element(element: AdapterEbmlElement, track_type: int | None) -> bool:
    if track_type == AUDIO_TRACK_TYPE:
        return True
    return element.element_id in {0x35, 0x38B5, 0x1F, 0x2264}


def _unsigned(payload: bytes) -> int:
    return int.from_bytes(payload, "big")


def _signed(payload: bytes) -> int:
    return int.from_bytes(payload, "big", signed=True)


def _mapped(value: int, values: dict[int, str]) -> str:
    return values.get(value, f"Unknown ({value})")


def _no_yes(value: int) -> str:
    return _mapped(value, NO_YES)


def _float(payload: bytes) -> float | str:
    if len(payload) == 4:
        return float(struct.unpack(">f", payload)[0])
    if len(payload) == 8:
        return float(struct.unpack(">d", payload)[0])
    return payload.hex()


def _system_tags(path: Path, source_file: str) -> list[ReadTag]:
    return [
        _read_tag(
            name,
            _tag_value(value),
            "System",
            "Image::ExifTool::Extra",
            name,
            "filesystem",
            family_1_group="System",
            family_2_group="Time" if name.endswith("Date") else "Other",
        )
        for name, value in read_system_tags(path, source_file).items()
    ]


def _tag_value(value: JsonValue) -> TagValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return str(value)
            strings.append(item)
        return strings
    return str(value)


def _file_type_tags(
    file_type: str,
    extension: str,
    mime_type: str,
    source: str,
) -> list[ReadTag]:
    return [
        _read_tag("FileType", file_type, "File", "Image::ExifTool::File", None, source),
        _read_tag(
            "FileTypeExtension",
            extension,
            "File",
            "Image::ExifTool::File",
            None,
            source,
        ),
        _read_tag("MIMEType", mime_type, "File", "Image::ExifTool::File", None, source),
    ]


def _read_tag(
    name: str,
    value: TagValue,
    group: str,
    table_name: str,
    tag_id: str | None,
    source: str,
    *,
    family_1_group: str | None = None,
    family_2_group: str = "Other",
    duplicate_instance_ordinal: int | None = None,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group,
            table_name,
            tag_id,
            source,
            family_0_group="File" if group in {"File", "System"} else group,
            family_1_group=family_1_group or group,
            family_2_group=family_2_group,
            duplicate_instance_ordinal=duplicate_instance_ordinal,
        ),
        schema=None,
    )


def _decoded_read_tag(tag: MatroskaDecodedTag) -> ReadTag:
    return _read_tag(
        tag.name,
        tag.value,
        "Matroska",
        tag.table_name,
        tag.tag_id,
        tag.source,
        family_1_group=tag.family_1_group,
        family_2_group=tag.family_2_group,
        duplicate_instance_ordinal=tag.duplicate_instance_ordinal,
    )
