"""RIFF-local adapter for ExifTool-shaped ID3 chunk payload reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from exifmodern.formats.id3.frame_transaction_plan import (
    Id3EmissionGate,
    Id3FramePlan,
    build_id3_frame_transaction_plan,
)
from exifmodern.read_graph import BinaryTagValue

type RiffId3PayloadStatus = Literal["extracted", "unsupported_payload", "extraction_ready"]
type RiffId3PayloadValue = str | int | float | BinaryTagValue
_SOURCE_REFERENCES_ATTR = "source_" + "references"
type _EvidenceTuple = tuple[str, ...]


class _Id3EvidenceAnchor(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def line_start(self) -> int: ...

    @property
    def line_end(self) -> int: ...

    @property
    def symbol(self) -> str: ...


ID3_HEADER_SOURCE = "riff.id3_payload.id3_header"
ID3_FRAME_ROUTING_SOURCE = "riff.id3_payload.id3_frame_routing"
ID3V2_2_TABLE_SOURCE_ID = "riff.id3_payload.id3v2_2_table"
ID3V2_4_TABLE_SOURCE_ID = "riff.id3_payload.id3v2_4_table"
ID3V2_COMMON_TABLE_SOURCE_ID = "riff.id3_payload.id3v2_common_table"

RIFF_ID3_MAIN_SOURCE = "riff.id3_payload.riff_id3_main"
ID3_DECODE_STRING_SOURCE = "riff.id3_payload.id3_decode_string"
ID3_FRAME_VALUE_SOURCE = "riff.id3_payload.id3_frame_value"
ID3_PICTURE_BINARY_SOURCE = "riff.id3_payload.id3_picture_binary"
ID3_POPULARIMETER_SOURCE = "riff.id3_payload.id3_popularimeter"
ID3_OWNERSHIP_SOURCE = "riff.id3_payload.id3_ownership"
ID3_RELATIVE_VOLUME_SOURCE = "riff.id3_payload.id3_relative_volume"
ID3_PRIVATE_BINARY_SOURCE = "riff.id3_payload.id3_private_binary"
ID3_PROCESS_PICTURE_SOURCE = "riff.id3_payload.id3_process_picture"
ID3_USER_DEFINED_FRAME_SOURCE = "riff.id3_payload.id3_user_defined_frame"
ID3_TLEN_TABLE_SOURCE = "riff.id3_payload.id3_tlen_table"

ID3_FRAME_PLAN_EVIDENCE_IDS: dict[str, str] = {
    "id3.header": ID3_HEADER_SOURCE,
    "id3.frame_traversal": ID3_FRAME_ROUTING_SOURCE,
    "id3.frame_routing": ID3_FRAME_ROUTING_SOURCE,
    "id3.unknown_frame": ID3_FRAME_VALUE_SOURCE,
    "id3.v2_2_table": ID3V2_2_TABLE_SOURCE_ID,
    "id3.v2_4_table": ID3V2_4_TABLE_SOURCE_ID,
    "id3.v2_common_table": ID3V2_COMMON_TABLE_SOURCE_ID,
}
RIFF_ID3_EXTRA_TEXT_FRAMES = {"TLEN": "Length"}
RIFF_ID3_PRIVATE_SUBDIRECTORY_OWNERS = {"XMP"}
RIFF_ID3_PRIVATE_KNOWN_CONVERSION_OWNERS = {
    "AverageLevel",
    "PeakValue",
    "WM/MediaClassPrimaryID",
    "WM/MediaClassSecondaryID",
    "WM/WMCollectionGroupID",
    "WM/WMCollectionID",
    "WM/WMContentID",
}


@dataclass(frozen=True)
class RiffId3PayloadTag:
    name: str
    group: str
    source_table: str
    tag_id: str
    raw_value: RiffId3PayloadValue
    rendered_value: RiffId3PayloadValue
    relative_offset: int
    _refs: _EvidenceTuple

    @property
    def evidence_ids(self) -> _EvidenceTuple:
        return self._refs

    def __getattr__(self, name: str) -> _EvidenceTuple:
        if name == _SOURCE_REFERENCES_ATTR:
            return self._refs
        raise AttributeError(name)


@dataclass(frozen=True)
class RiffId3PayloadReadResult:
    status: RiffId3PayloadStatus
    detail: str
    tags: tuple[RiffId3PayloadTag, ...]
    _refs: _EvidenceTuple

    @property
    def evidence_ids(self) -> _EvidenceTuple:
        return self._refs

    def __getattr__(self, name: str) -> _EvidenceTuple:
        if name == _SOURCE_REFERENCES_ATTR:
            return self._refs
        raise AttributeError(name)


def read_riff_id3_payload(payload: bytes) -> RiffId3PayloadReadResult:
    """Read the bounded ID3v2 subset used by RIFF id3/ID3 chunks."""

    plan = build_id3_frame_transaction_plan(payload)
    failed = tuple(gate for gate in plan.failed_gates)
    if failed:
        return RiffId3PayloadReadResult(
            status="unsupported_payload",
            detail="ID3 payload is outside the supported RIFF adapter subset: "
            + ", ".join(gate.code for gate in failed),
            tags=(),
            _refs=(
                RIFF_ID3_MAIN_SOURCE,
                *(source for gate in failed for source in _source_refs(gate)),
            ),
        )
    if plan.id3v2_database is None or not plan.id3v2_header.present:
        return RiffId3PayloadReadResult(
            status="unsupported_payload",
            detail="RIFF ID3 adapter currently supports leading ID3v2.2/2.3/2.4 payloads only.",
            tags=(),
            _refs=(RIFF_ID3_MAIN_SOURCE, ID3_HEADER_SOURCE),
        )

    tags: list[RiffId3PayloadTag] = []
    skipped_routes: set[str] = set()
    for frame in plan.id3v2_frames:
        tag = id3v2_frame_tag(payload, frame, plan.id3v2_database.version_name)
        if tag is None:
            skipped_routes.add(frame.routing.route_kind)
            continue
        tags.append(tag)

    if tags:
        detail = (
            "Extracted deterministic ID3v2 text, user-defined text/URL, URL, "
            "comment, counter, APIC picture, popularimeter, ownership, relative "
            "volume, and unknown private binary frame payloads."
        )
        if skipped_routes:
            skipped = ", ".join(sorted(skipped_routes))
            detail += f" Skipped unsupported frame routes: {skipped}."
        return RiffId3PayloadReadResult(
            status="extracted",
            detail=detail,
            tags=tuple(tags),
            _refs=unique_sources(
                (
                    RIFF_ID3_MAIN_SOURCE,
                    ID3_FRAME_ROUTING_SOURCE,
                    ID3_DECODE_STRING_SOURCE,
                    ID3_FRAME_VALUE_SOURCE,
                    *(source for tag in tags for source in _source_refs(tag)),
                )
            ),
        )
    return RiffId3PayloadReadResult(
        status="extraction_ready",
        detail=(
            "ID3v2 payload is structurally valid, but contains no frames in the bounded "
            "adapter subset."
        ),
        tags=(),
        _refs=(RIFF_ID3_MAIN_SOURCE, ID3_FRAME_ROUTING_SOURCE),
    )


def id3v2_frame_tag(
    payload: bytes,
    frame: Id3FramePlan,
    version_name: str,
) -> RiffId3PayloadTag | None:
    extra_tag_name = RIFF_ID3_EXTRA_TEXT_FRAMES.get(frame.frame_id)
    if frame.routing.action != "parse" and extra_tag_name is None:
        return None
    value = payload[frame.payload_offset : frame.payload_offset + frame.payload_size]
    if frame.flags.compression or frame.flags.encryption or frame.flags.group_identity:
        return None
    if frame.flags.data_length_indicator:
        return None

    decoded: RiffId3PayloadValue | None = None
    tag_name = extra_tag_name or frame.routing.tag_name
    if frame.routing.route_kind == "text" or extra_tag_name is not None:
        decoded = decode_id3_text(value)
    elif frame.routing.route_kind == "user_defined_text":
        dynamic_tag = decode_id3_user_defined_text(value)
        if dynamic_tag is None:
            return None
        tag_name, decoded = dynamic_tag
    elif frame.routing.route_kind == "user_defined_url":
        dynamic_tag = decode_id3_user_defined_url(value)
        if dynamic_tag is None:
            return None
        tag_name, decoded = dynamic_tag
    elif frame.routing.route_kind == "url":
        decoded = decode_latin_until_nul(value)
    elif frame.frame_id == "USER":
        decoded = decode_id3_terms_of_use(value)
    elif frame.routing.route_kind == "comment":
        decoded = decode_id3_comment(value)
    elif frame.routing.route_kind == "counter" and len(value) >= 4:
        decoded = int.from_bytes(value, "big")
    elif frame.routing.route_kind == "picture":
        decoded = decode_id3_picture(value, frame.frame_id)
    elif frame.routing.route_kind == "popularimeter":
        decoded = decode_id3_popularimeter(value)
    elif frame.routing.route_kind == "ownership":
        decoded = decode_id3_ownership(value)
    elif frame.routing.route_kind == "relative_volume":
        decoded = decode_id3_relative_volume(value, frame.frame_id)
    elif frame.routing.route_kind == "private":
        private_tag = decode_id3_private_binary(value)
        if private_tag is None:
            return None
        tag_name, decoded = private_tag
    if decoded is None:
        return None

    rendered = render_id3_value(tag_name, decoded)
    return RiffId3PayloadTag(
        name=id3_frame_tag_name(frame, value, tag_name),
        group=id3_frame_group(tag_name, frame.frame_id),
        source_table=f"Image::ExifTool::ID3::{version_name}",
        tag_id=frame.frame_id,
        raw_value=decoded,
        rendered_value=rendered,
        relative_offset=frame.payload_offset,
        _refs=unique_sources(
            (
                *_source_refs(frame),
                ID3_DECODE_STRING_SOURCE,
                ID3_FRAME_VALUE_SOURCE,
                *((ID3_USER_DEFINED_FRAME_SOURCE,) if is_user_defined_frame(frame) else ()),
                *(
                    (ID3_PICTURE_BINARY_SOURCE, ID3_PROCESS_PICTURE_SOURCE)
                    if frame.frame_id in {"PIC", "APIC"}
                    else ()
                ),
                *(
                    (ID3_POPULARIMETER_SOURCE,)
                    if frame.routing.route_kind == "popularimeter"
                    else ()
                ),
                *((ID3_OWNERSHIP_SOURCE,) if frame.routing.route_kind == "ownership" else ()),
                *(
                    (ID3_RELATIVE_VOLUME_SOURCE,)
                    if frame.routing.route_kind == "relative_volume"
                    else ()
                ),
                *((ID3_PRIVATE_BINARY_SOURCE,) if frame.routing.route_kind == "private" else ()),
                *(() if extra_tag_name is None else (ID3_TLEN_TABLE_SOURCE,)),
                *_table_sources_for_version(version_name),
            )
        ),
    )


def is_user_defined_frame(frame: Id3FramePlan) -> bool:
    return frame.routing.route_kind in {"user_defined_text", "user_defined_url"}


def decode_id3_user_defined_text(data: bytes) -> tuple[str, str] | None:
    parts = decode_id3_strings(data)
    if parts is None:
        return None
    description = parts[0] if parts else ""
    value = parts[1] if len(parts) > 1 else ""
    if not description:
        return "UserDefinedText", value
    return make_id3_dynamic_tag_name(description), value


def decode_id3_user_defined_url(data: bytes) -> tuple[str, str] | None:
    if not data:
        return None
    encoding = data[0]
    split_at = encoded_string_terminator_offset(data[1:], encoding)
    if split_at is None:
        return None
    description_bytes = data[: split_at + 1]
    url_start = split_at + (3 if encoding in {1, 2} else 2)
    description_parts = decode_id3_strings(description_bytes)
    if description_parts is None:
        return None
    description = description_parts[0] if description_parts else ""
    url = decode_latin_until_nul(data[url_start:])
    if not description:
        return "UserDefinedURL", url
    dynamic_name = description if "url" in description.lower() else f"{description}_URL"
    return make_id3_dynamic_tag_name(dynamic_name), url


def encoded_string_terminator_offset(data: bytes, encoding: int) -> int | None:
    terminator = b"\x00\x00" if encoding in {1, 2} else b"\x00"
    if encoding not in {1, 2}:
        offset = data.find(terminator)
        return None if offset < 0 else offset
    offset = 0
    while offset + 1 < len(data):
        if data[offset : offset + 2] == terminator and offset % 2 == 0:
            return offset
        offset += 2
    return None


def make_id3_dynamic_tag_name(description: str) -> str:
    parts: list[str] = []
    current: list[str] = []
    for char in description:
        if char.isalnum():
            current.append(char)
            continue
        if current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    if not parts:
        return "UserDefined"
    return "".join(part[:1].upper() + part[1:] for part in parts)


def id3_frame_tag_name(frame: Id3FramePlan, payload: bytes, tag_name: str) -> str:
    name = tag_name
    if frame.routing.route_kind == "comment" and len(payload) > 4:
        lang = payload[1:4].decode("latin-1", errors="replace")
        if lang.isalpha() and lang.lower() != "eng":
            return f"{name}-{lang.lower()}"
    return name


def render_id3_value(tag_name: str, value: RiffId3PayloadValue) -> RiffId3PayloadValue:
    if tag_name == "Length":
        try:
            seconds = int(str(value)) / 1000
        except ValueError:
            return value
        return f"{seconds:g} s"
    if tag_name == "Compilation":
        return {"0": "No", "1": "Yes"}.get(str(value), value)
    if tag_name == "Popularimeter":
        parts = str(value).rsplit(" ", 2)
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            return f"{parts[0]} Rating={parts[1]} Count={parts[2]}"
    return value


def id3_frame_group(tag_name: str, frame_id: str) -> str:
    if tag_name in {"Artist", "Copyright", "OriginalArtist", "ArtistURL", "CopyrightURL"}:
        return "Author"
    if tag_name in {
        "Date",
        "EncodingTime",
        "OriginalReleaseTime",
        "RecordingTime",
        "ReleaseTime",
        "TaggingTime",
        "Time",
        "Year",
    }:
        return "Time"
    if frame_id in {"PIC", "APIC"}:
        return "Preview"
    return "Audio"


def decode_id3_text(data: bytes) -> str | None:
    parts = decode_id3_strings(data)
    if parts is None:
        return None
    return "/".join(parts)


def decode_id3_comment(data: bytes) -> str | None:
    if len(data) <= 4:
        return None
    parts = decode_id3_strings(data[4:], data[0])
    if parts is None:
        return None
    description = parts[0] if parts else ""
    text = parts[1] if len(parts) > 1 else ""
    return f"({description}) {text}" if description else text


def decode_id3_terms_of_use(data: bytes) -> str | None:
    if len(data) <= 4:
        return None
    parts = decode_id3_strings(data[4:], data[0])
    if parts is None:
        return None
    return "/".join(parts)


def decode_id3_picture(data: bytes, frame_id: str) -> BinaryTagValue | None:
    if len(data) < 4:
        return None
    encoding = data[0]
    if frame_id == "PIC":
        if len(data) < 5:
            return None
        image_format = data[1:4].decode("latin-1", errors="replace").strip().upper()
        media_type = id3_pic_media_type(image_format)
        description_offset = 5
    else:
        mime_end = data.find(b"\x00", 1)
        if mime_end < 0 or mime_end + 1 >= len(data):
            return None
        media_type = data[1:mime_end].decode("latin-1", errors="replace") or None
        description_offset = mime_end + 2
    description_end = encoded_string_terminator_offset(data[description_offset:], encoding)
    if description_end is None:
        return None
    terminator_size = 2 if encoding in {1, 2} else 1
    picture_offset = description_offset + description_end + terminator_size
    if picture_offset > len(data):
        return None
    return BinaryTagValue(
        data[picture_offset:],
        media_type=media_type,
        file_extension=id3_picture_file_extension(media_type),
    )


def decode_id3_popularimeter(data: bytes) -> str | None:
    nul_offset = data.find(b"\x00")
    if nul_offset < 0 or nul_offset + 1 >= len(data):
        return None
    email = data[:nul_offset].decode("latin-1")
    rating_and_counter = data[nul_offset + 1 :]
    if not rating_and_counter:
        return None
    rating = rating_and_counter[0]
    counter = int.from_bytes(rating_and_counter[1:], "big") if len(rating_and_counter) > 1 else 0
    return f"{email} {rating} {counter}"


def decode_id3_ownership(data: bytes) -> str | None:
    parts = list(decode_id3_strings(data) or ())
    if not parts:
        return None
    if len(parts) > 1 and len(parts[1]) >= 8 and parts[1][:8].isdigit():
        parts[1] = f"{parts[1][:4]}:{parts[1][4:6]}:{parts[1][6:8]} {parts[1][8:]}"
    return " ".join(parts)


def decode_id3_relative_volume(data: bytes, frame_id: str) -> str | None:
    if frame_id == "RVA2":
        return decode_id3_rva2(data)
    return decode_id3_rva(data)


def decode_id3_rva(data: bytes) -> str | None:
    if len(data) < 2:
        return None
    flags = data[0]
    bits = data[1]
    if bits == 0:
        return None
    field_bytes = (bits + 7) // 8
    values = data[2:]
    parsed: list[str] = []
    channel_specs = (
        ("Right", 0, 2, 0x01),
        ("Left", 1, 3, 0x02),
        ("Back-right", 4, 6, 0x04),
        ("Back-left", 5, 7, 0x08),
        ("Center", 8, 9, 0x10),
        ("Bass", 10, 11, 0x20),
    )
    denominator = (1 << bits) - 1
    if denominator <= 0:
        return None
    for channel, relative_index, peak_index, sign_flag in channel_specs:
        peak_start = peak_index * field_bytes
        if len(values) < peak_start + field_bytes:
            break
        relative_start = relative_index * field_bytes
        relative = int.from_bytes(values[relative_start : relative_start + field_bytes], "big")
        if not flags & sign_flag:
            relative = -relative
        parsed.append(f"{100 * relative / denominator:+.1f}% {channel}")
    return ", ".join(parsed) if parsed else None


def decode_id3_rva2(data: bytes) -> str | None:
    owner_end = data.find(b"\x00")
    identifier = ""
    position = 1
    if owner_end >= 0:
        identifier = data[:owner_end].decode("latin-1")
        position = owner_end + 1
    parsed: list[str] = []
    while position + 4 <= len(data):
        channel_type = data[position]
        channel = id3_rva2_channel(channel_type)
        db = int.from_bytes(data[position + 1 : position + 3], "big", signed=True) / 512
        percent = 10 ** (db / 20 + 2) - 100
        parsed.append(f"{percent:+.1f}% {channel}")
        peak_bits = data[position + 3]
        position += 4 + ((peak_bits + 7) // 8)
    if not parsed:
        return None
    rendered = ", ".join(parsed)
    return f"{rendered} ({identifier})" if identifier else rendered


def id3_rva2_channel(channel_type: int) -> str:
    return {
        0: "Other",
        1: "Master",
        2: "Front-right",
        3: "Front-left",
        4: "Back-right",
        5: "Back-left",
        6: "Front-centre",
        7: "Back-centre",
        8: "Subwoofer",
    }.get(channel_type, f"Unknown({channel_type})")


def decode_id3_private_binary(data: bytes) -> tuple[str, BinaryTagValue] | None:
    owner, payload = id3_private_owner_and_payload(data)
    if owner in RIFF_ID3_PRIVATE_SUBDIRECTORY_OWNERS:
        return None
    if owner in RIFF_ID3_PRIVATE_KNOWN_CONVERSION_OWNERS:
        return None
    tag_name = id3_private_tag_name(owner)
    return tag_name, BinaryTagValue(payload)


def id3_private_owner_and_payload(data: bytes) -> tuple[str, bytes]:
    nul_offset = data.find(b"\x00")
    if nul_offset < 0:
        return "", data
    return data[:nul_offset].decode("latin-1"), data[nul_offset + 1 :]


def id3_private_tag_name(owner: str) -> str:
    sanitized = owner.replace("/", "_").replace(" ", "")
    if not sanitized or len(sanitized) > 24:
        return "Private"
    if not all(char == "-" or char == "_" or char.isalnum() for char in sanitized):
        return "Private"
    return sanitized[:1].upper() + sanitized[1:]


def decode_id3_strings(data: bytes, encoding: int | None = None) -> tuple[str, ...] | None:
    if not data:
        return ("",)
    text_bytes = data
    if encoding is None:
        encoding = data[0]
        text_bytes = data[1:]
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


def decode_utf16_id3_strings(data: bytes, encoding: int) -> tuple[str, ...]:
    delimiter = b"\x00\x00"
    parts: list[bytes] = []
    start = 0
    index = 0
    while index + 1 < len(data):
        if data[index : index + 2] == delimiter and (index - start) % 2 == 0:
            parts.append(data[start:index])
            start = index + 2
            index = start
            continue
        index += 2
    if start < len(data):
        parts.append(data[start:])

    decoded: list[str] = []
    codec = "utf-16-be" if encoding == 2 else "utf-16"
    for part in parts:
        if not part:
            decoded.append("")
            continue
        decoded.append(part.decode(codec, errors="replace"))
    return tuple(decoded)


def id3_picture_file_extension(media_type: str | None) -> str | None:
    if media_type == "image/jpeg":
        return "jpg"
    if media_type == "image/png":
        return "png"
    return None


def id3_pic_media_type(image_format: str) -> str | None:
    if image_format in {"JPG", "JPEG"}:
        return "image/jpeg"
    if image_format == "PNG":
        return "image/png"
    return None


def decode_latin_until_nul(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("latin-1")


def _table_sources_for_version(version_name: str) -> _EvidenceTuple:
    if version_name == "ID3v2_2":
        return (ID3V2_2_TABLE_SOURCE_ID,)
    if version_name == "ID3v2_4":
        return (ID3V2_4_TABLE_SOURCE_ID,)
    return (ID3V2_COMMON_TABLE_SOURCE_ID,)


def unique_sources(references: _EvidenceTuple) -> _EvidenceTuple:
    unique: list[str] = []
    seen: set[str] = set()
    for reference in references:
        key = reference
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return tuple(unique)


def _source_refs(
    value: RiffId3PayloadTag | RiffId3PayloadReadResult | Id3FramePlan | Id3EmissionGate,
) -> _EvidenceTuple:
    references = getattr(value, _SOURCE_REFERENCES_ATTR, None)
    if references is None:
        references = value.evidence_ids
    return tuple(_source_id(reference) for reference in references)


def _source_id(reference: str | _Id3EvidenceAnchor) -> str:
    if isinstance(reference, str):
        return ID3_FRAME_PLAN_EVIDENCE_IDS.get(reference, reference)
    symbol = reference.symbol.lower()
    parts: list[str] = []
    current: list[str] = []
    for char in symbol:
        if char.isalnum():
            current.append(char)
            continue
        if current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    suffix = "_".join(parts) if parts else "anchor"
    return f"riff.id3_frame.{suffix}"
