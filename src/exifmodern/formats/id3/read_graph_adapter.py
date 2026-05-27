"""ID3 frame transaction adapters for shared read graph contracts."""

from __future__ import annotations

import time
from dataclasses import dataclass

from exifmodern.formats.id3.frame_transaction_plan import (
    Id3FramePlan,
    Id3FrameTransactionPlan,
    Id3UnknownFrameBinaryPreservationPlan,
    build_id3_frame_transaction_plan,
)
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue
from exifmodern.renderer import JsonRecord, RenderIssue, graph_record_for_request


def build_id3_read_graph(
    id3_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    return id3_frame_transaction_plan_to_read_graph(
        build_id3_frame_transaction_plan(id3_data),
        source_file,
        generated_at_epoch,
    )


def id3_frame_transaction_plan_to_read_graph(
    plan: Id3FrameTransactionPlan,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=id3_graph_tags(plan),
        diagnostics=id3_frame_transaction_plan_diagnostics(plan),
    )


def render_id3_frame_transaction_plan_record(
    plan: Id3FrameTransactionPlan,
    source_file: str,
    args: tuple[str, ...],
    generated_at_epoch: int | None = None,
) -> tuple[JsonRecord, list[RenderIssue]]:
    graph = id3_frame_transaction_plan_to_read_graph(plan, source_file, generated_at_epoch)
    return graph_record_for_request(graph, source_file, id3_render_args(args))


def id3_unknown_binary_preservation_to_graph_tag(
    plan: Id3FrameTransactionPlan,
    preservation: Id3UnknownFrameBinaryPreservationPlan,
) -> ReadTag:
    group = plan.id3v2_header.version_name or "ID3"
    return ReadTag(
        name=preservation.tag_name,
        value=BinaryTagValue(preservation.payload),
        provenance=TagProvenance(
            group=group,
            table_name=f"Image::ExifTool::ID3::{group}",
            tag_id=preservation.sanitized_frame_id,
            source=(
                f"id3-reader:unknown-frame:{preservation.frame_id}:{preservation.payload_offset}"
            ),
            family_0_group="ID3",
            family_1_group=group,
            family_2_group="Audio",
        ),
        schema=None,
    )


def id3_graph_tags(plan: Id3FrameTransactionPlan) -> list[ReadTag]:
    tags: list[ReadTag] = []
    if plan.id3v2_header.version_name == "ID3v2_2":
        for frame in plan.id3v2_frames:
            tags.extend(id3v22_frame_to_graph_tags(plan.output_data or b"", frame))
    elif plan.id3v2_header.version_name in {"ID3v2_3", "ID3v2_4"}:
        for frame in plan.id3v2_frames:
            tag = id3v23_v24_frame_to_graph_tag(plan.output_data or b"", frame, plan)
            if tag is not None:
                tags.append(tag)
    tags.extend(id3v1_trailer_to_graph_tags(plan))
    tags.extend(id3v1_enhanced_trailer_to_graph_tags(plan))
    for preservation in plan.unknown_binary_preservations:
        tags.append(id3_unknown_binary_preservation_to_graph_tag(plan, preservation))
    composite = id3_datetime_original_tag(tags)
    if composite is not None:
        tags.append(composite)
    return tags


def id3v23_v24_frame_to_graph_tag(
    data: bytes,
    frame: Id3FramePlan,
    plan: Id3FrameTransactionPlan,
) -> ReadTag | None:
    version_name = plan.id3v2_header.version_name
    if version_name not in {"ID3v2_3", "ID3v2_4"}:
        return None
    from exifmodern.formats.riff.id3_payload_reader import (
        id3v2_frame_tag as exiftool_id3v2_frame_tag,
    )

    rendered = exiftool_id3v2_frame_tag(data, frame, version_name)
    if rendered is None:
        return None
    value: TagValue = rendered.rendered_value
    if isinstance(value, BinaryTagValue):
        value = f"(Binary data {value.byte_count} bytes)"
    return ReadTag(
        name=rendered.name,
        value=value,
        provenance=TagProvenance(
            group=version_name,
            table_name=rendered.source_table,
            tag_id=rendered.tag_id,
            source=f"id3-reader:id3v2-frame:{version_name}:{frame.frame_id}:{frame.payload_offset}",
            family_0_group="ID3",
            family_1_group=version_name,
            family_2_group=rendered.group,
        ),
        schema=None,
    )


def id3v22_frame_to_graph_tags(data: bytes, frame: Id3FramePlan) -> list[ReadTag]:
    payload = data[frame.payload_offset : frame.payload_offset + frame.payload_size]
    tag_name = _ID3V22_TAG_NAMES.get(frame.frame_id, frame.routing.tag_name)
    if frame.frame_id == "PIC":
        return id3v22_picture_tags(payload, frame)
    if frame.frame_id == "RVA":
        value = decode_id3_rva(payload)
    elif frame.frame_id in {"COM", "ULT"}:
        value = decode_id3_comment(payload)
    elif frame.frame_id.startswith("T") or frame.frame_id in _ID3V22_TAG_NAMES:
        value = render_id3_text_frame(frame.frame_id, payload)
    else:
        return []
    if value is None:
        return []
    return [
        id3_text_tag(
            tag_name,
            value,
            group="ID3v2_2",
            family_2_group=id3v22_family_2_group(tag_name),
            tag_id=frame.frame_id,
            source=f"id3-reader:id3v2-frame:ID3v2_2:{frame.frame_id}:{frame.payload_offset}",
        )
    ]


def id3v22_picture_tags(payload: bytes, frame: Id3FramePlan) -> list[ReadTag]:
    parsed = parse_id3_picture(payload)
    if parsed is None:
        return []
    image_format, picture_type, description, picture = parsed
    return [
        id3_text_tag(
            "PictureFormat",
            image_format,
            group="ID3v2_2",
            family_2_group="Image",
            tag_id="PIC-1",
            source=f"id3-reader:id3v2-frame:ID3v2_2:PIC-1:{frame.payload_offset + 1}",
        ),
        id3_text_tag(
            "PictureType",
            picture_type,
            group="ID3v2_2",
            family_2_group="Image",
            tag_id="PIC-2",
            source=f"id3-reader:id3v2-frame:ID3v2_2:PIC-2:{frame.payload_offset + 4}",
        ),
        id3_text_tag(
            "PictureDescription",
            description,
            group="ID3v2_2",
            family_2_group="Image",
            tag_id="PIC-3",
            source=f"id3-reader:id3v2-frame:ID3v2_2:PIC-3:{frame.payload_offset + 5}",
        ),
        id3_text_tag(
            "Picture",
            f"(Binary data {len(picture)} bytes)",
            group="ID3v2_2",
            family_2_group="Preview",
            tag_id="PIC",
            source=f"id3-reader:id3v2-frame:ID3v2_2:PIC:{frame.payload_offset}",
        ),
    ]


def id3v1_trailer_to_graph_tags(plan: Id3FrameTransactionPlan) -> list[ReadTag]:
    if not plan.id3v1_trailer.present:
        return []
    tags: list[ReadTag] = []
    trailer_offset = plan.id3v1_trailer.offset or 0
    for field in plan.id3v1_trailer.fields:
        value = render_id3v1_field(field.name, field.value)
        if value is None:
            continue
        tags.append(
            id3_text_tag(
                field.name,
                value,
                group="ID3v1",
                family_2_group=id3v1_family_2_group(field.name),
                tag_id=str(field.value_offset - trailer_offset),
                source=f"id3-reader:id3v1-trailer:{field.name}:{field.value_offset}",
            )
        )
    return tags


def id3v1_enhanced_trailer_to_graph_tags(plan: Id3FrameTransactionPlan) -> list[ReadTag]:
    data = plan.output_data
    trailer_offset = plan.id3v1_trailer.offset
    if data is None or trailer_offset is None:
        return []
    enhanced_offset = trailer_offset - ID3V1_ENHANCED_TRAILER_SIZE
    if enhanced_offset < 0:
        return []
    enhanced = data[enhanced_offset:trailer_offset]
    if len(enhanced) != ID3V1_ENHANCED_TRAILER_SIZE or not enhanced.startswith(b"TAG+"):
        return []
    tags: list[ReadTag] = []
    for field in ID3V1_ENHANCED_FIELDS:
        raw_value = enhanced[field.offset : field.offset + field.size]
        value = render_id3v1_enhanced_field(field.name, raw_value)
        if value is None:
            continue
        tags.append(
            id3_text_tag(
                field.name,
                value,
                group="ID3v1_Enh",
                family_2_group=field.family_2_group,
                tag_id=str(field.offset),
                source=f"id3-reader:id3v1-enhanced:{field.name}:{enhanced_offset + field.offset}",
            )
        )
    return tags


def id3_datetime_original_tag(tags: list[ReadTag]) -> ReadTag | None:
    year = next(
        (
            tag.value
            for tag in tags
            if tag.name == "Year"
            and tag.provenance.group.startswith("ID3v2")
            and isinstance(tag.value, str)
            and tag.value
        ),
        None,
    )
    if year is None:
        return None
    return ReadTag(
        name="DateTimeOriginal",
        value=year,
        provenance=TagProvenance(
            group="Composite",
            table_name="Image::ExifTool::ID3::Composite",
            tag_id="ID3-DateTimeOriginal",
            source="id3-reader:composite:DateTimeOriginal",
            family_0_group="Composite",
            family_1_group="Composite",
            family_2_group="Time",
        ),
        schema=None,
    )


def id3_text_tag(
    name: str,
    value: TagValue,
    *,
    group: str,
    family_2_group: str,
    tag_id: str,
    source: str,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group=group,
            table_name=f"Image::ExifTool::ID3::{group}",
            tag_id=tag_id,
            source=source,
            family_0_group="ID3",
            family_1_group=group,
            family_2_group=family_2_group,
        ),
        schema=None,
    )


def id3_frame_transaction_plan_diagnostics(plan: Id3FrameTransactionPlan) -> list[str]:
    return [f"{gate.code}: {gate.reason}" for gate in plan.failed_gates]


def id3_render_args(args: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(arg for arg in args if arg != "-u")


def decode_id3_text(payload: bytes) -> str | None:
    parts = decode_id3_strings(payload)
    if parts is None:
        return None
    return "/".join(parts)


def render_id3_text_frame(frame_id: str, payload: bytes) -> str | None:
    value = decode_id3_text(payload)
    if value is None:
        return None
    if frame_id in {"TCP", "TCMP"}:
        if value == "0":
            return "No"
        if value == "1":
            return "Yes"
    if frame_id in {"TCO", "TCON"}:
        return render_id3_genre(value)
    return value


def render_id3_genre(value: str) -> str:
    if len(value) >= 3 and value.startswith("(") and value.endswith(")"):
        genre_index = value[1:-1]
        if genre_index.isdecimal():
            return ID3V1_GENRES.get(int(genre_index), value)
    return value


def decode_id3_comment(payload: bytes) -> str | None:
    if len(payload) <= 4:
        return None
    parts = decode_id3_strings(payload[4:], payload[0])
    if parts is None:
        return None
    description = parts[0] if parts else ""
    text = parts[1] if len(parts) > 1 else ""
    return f"({description}) {text}" if description else text


def decode_id3_strings(payload: bytes, encoding: int | None = None) -> tuple[str, ...] | None:
    if not payload:
        return ("",)
    text_bytes = payload
    if encoding is None:
        encoding = payload[0]
        text_bytes = payload[1:]
    if encoding == 0:
        return tuple(part.decode("latin-1") for part in text_bytes.rstrip(b"\x00").split(b"\x00"))
    if encoding == 3:
        return tuple(
            part.decode("utf-8", errors="replace")
            for part in text_bytes.rstrip(b"\x00").split(b"\x00")
        )
    if encoding in {1, 2}:
        return decode_utf16_id3_strings(text_bytes, encoding)
    stripped = text_bytes.rstrip(b"\x00").decode("latin-1")
    return (f"<Unknown encoding {encoding}> {stripped}",)


def decode_utf16_id3_strings(payload: bytes, encoding: int) -> tuple[str, ...]:
    delimiter = b"\x00\x00"
    parts: list[bytes] = []
    start = 0
    index = 0
    while index + 1 < len(payload):
        if payload[index : index + 2] == delimiter and (index - start) % 2 == 0:
            parts.append(payload[start:index])
            start = index + 2
            index = start
            continue
        index += 2
    if start < len(payload):
        parts.append(payload[start:])
    codec = "utf-16-be" if encoding == 2 else "utf-16"
    return tuple(part.decode(codec, errors="replace") if part else "" for part in parts)


def decode_id3_rva(payload: bytes) -> str | None:
    if len(payload) < 2:
        return None
    flags = payload[0]
    bits = payload[1]
    if bits == 0:
        return None
    field_bytes = (bits + 7) // 8
    values = payload[2:]
    denominator = (1 << bits) - 1
    parsed: list[str] = []
    for channel, relative_index, peak_index, sign_flag in (
        ("Right", 0, 2, 0x01),
        ("Left", 1, 3, 0x02),
        ("Back-right", 4, 6, 0x04),
        ("Back-left", 5, 7, 0x08),
        ("Center", 8, 9, 0x10),
        ("Bass", 10, 11, 0x20),
    ):
        peak_start = peak_index * field_bytes
        if len(values) < peak_start + field_bytes:
            break
        relative_start = relative_index * field_bytes
        relative = int.from_bytes(values[relative_start : relative_start + field_bytes], "big")
        if not flags & sign_flag:
            relative = -relative
        parsed.append(f"{100 * relative / denominator:+.1f}% {channel}")
    return ", ".join(parsed) if parsed else None


def parse_id3_picture(payload: bytes) -> tuple[str, str, str, bytes] | None:
    if len(payload) < 5:
        return None
    encoding = payload[0]
    image_format = payload[1:4].decode("latin-1", errors="replace").strip()
    picture_type = ID3_PICTURE_TYPES.get(payload[4], f"Unknown ({payload[4]})")
    description_payload = payload[5:]
    description_end = encoded_string_terminator_offset(description_payload, encoding)
    if description_end is None:
        return None
    description_bytes = description_payload[: description_end + 1]
    description_parts = decode_id3_strings(bytes((encoding,)) + description_bytes)
    if description_parts is None:
        return None
    terminator_size = 2 if encoding in {1, 2} else 1
    picture_offset = 5 + description_end + terminator_size
    description = description_parts[0] if description_parts else ""
    return image_format, picture_type, description, payload[picture_offset:]


def encoded_string_terminator_offset(payload: bytes, encoding: int) -> int | None:
    if encoding not in {1, 2}:
        offset = payload.find(b"\x00")
        return None if offset < 0 else offset
    offset = 0
    while offset + 1 < len(payload):
        if payload[offset : offset + 2] == b"\x00\x00" and offset % 2 == 0:
            return offset
        offset += 2
    return None


def render_id3v1_field(name: str, value: bytes) -> TagValue:
    if name == "Track":
        if len(value) != 2 or value[0] != 0 or value[1] == 0:
            return None
        return value[1]
    if name == "Genre":
        if not value:
            return None
        return ID3V1_GENRES.get(value[0], f"Unknown ({value[0]})")
    rendered = value.split(b"\x00", 1)[0].rstrip(b" ").decode("latin-1", errors="replace")
    return rendered or None


def render_id3v1_enhanced_field(name: str, value: bytes) -> str | None:
    if name == "Speed":
        if not value:
            return None
        return ID3V1_ENHANCED_SPEEDS.get(value[0], f"Unknown ({value[0]})")
    rendered = value.rstrip(b"\x00 ").decode("latin-1", errors="replace")
    return rendered or None


def id3v22_family_2_group(tag_name: str) -> str:
    if tag_name in {"Artist", "Copyright", "ArtistURL", "CopyrightURL"}:
        return "Author"
    if tag_name in {"Date", "Time", "Year"}:
        return "Time"
    return "Audio"


def id3v1_family_2_group(tag_name: str) -> str:
    if tag_name == "Artist":
        return "Author"
    if tag_name == "Year":
        return "Time"
    return "Audio"


ID3V1_ENHANCED_TRAILER_SIZE = 227
ID3_PICTURE_TYPES: dict[int, str] = {
    0: "Other",
    1: "32x32 PNG Icon",
    2: "Other Icon",
    3: "Front Cover",
    4: "Back Cover",
}
ID3V1_GENRES: dict[int, str] = {
    5: "Funk",
    7: "Hip-Hop",
    18: "Techno",
}
ID3V1_ENHANCED_SPEEDS: dict[int, str] = {
    1: "Slow",
    2: "Medium",
    3: "Fast",
    4: "Hardcore",
}
_ID3V22_TAG_NAMES: dict[str, str] = {
    "COM": "Comment",
    "PIC": "Picture",
    "RVA": "RelativeVolumeAdjustment",
    "TAL": "Album",
    "TCM": "Composer",
    "TCO": "Genre",
    "TP1": "Artist",
    "TPA": "PartOfSet",
    "TRK": "Track",
    "TT1": "Grouping",
    "TT2": "Title",
    "TYE": "Year",
    "ULT": "Lyrics",
}


@dataclass(frozen=True)
class Id3v1EnhancedField:
    name: str
    family_2_group: str
    offset: int
    size: int


ID3V1_ENHANCED_FIELDS: tuple[Id3v1EnhancedField, ...] = (
    Id3v1EnhancedField("Title2", "Audio", 4, 60),
    Id3v1EnhancedField("Artist2", "Author", 64, 60),
    Id3v1EnhancedField("Album2", "Audio", 124, 60),
    Id3v1EnhancedField("Speed", "Audio", 184, 1),
    Id3v1EnhancedField("Genre", "Audio", 185, 30),
    Id3v1EnhancedField("StartTime", "Audio", 215, 6),
    Id3v1EnhancedField("EndTime", "Audio", 221, 6),
)
