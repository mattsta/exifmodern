"""Media Jukebox APP9 reader."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.json_types import JsonObject

MEDIA_JUKEBOX_PREFIX = b"Media Jukebox\x00"
MEDIA_JUKEBOX_XML_HEADER_OFFSET = len(MEDIA_JUKEBOX_PREFIX) + 2
MEDIA_JUKEBOX_XML_FRAGMENT_OFFSET = 22


def read_media_jukebox_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xE9:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(MEDIA_JUKEBOX_PREFIX):
            continue
        return parse_media_jukebox_payload(payload)
    raise ValueError(f"No Media Jukebox APP9 segment found: {path}")


def parse_media_jukebox_payload(payload: bytes) -> JsonObject:
    root = media_jukebox_xml_root(payload)
    values: JsonObject = {}
    collect_media_jukebox_values(values, root, None)
    return values


def media_jukebox_xml_root(payload: bytes) -> ElementTree.Element[str]:
    for xml_text in media_jukebox_xml_candidates(payload):
        try:
            return ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            continue
    raise ValueError("Unreadable Media Jukebox APP9 XML")


def media_jukebox_xml_candidates(payload: bytes) -> tuple[str, str, str]:
    direct_xml_text = media_jukebox_text_from_offset(payload, len(MEDIA_JUKEBOX_PREFIX))
    header_xml_text = media_jukebox_text_from_offset(payload, MEDIA_JUKEBOX_XML_HEADER_OFFSET)
    fragment_text = media_jukebox_text_from_offset(payload, MEDIA_JUKEBOX_XML_FRAGMENT_OFFSET)
    return (
        direct_xml_text,
        header_xml_text,
        media_jukebox_wrapped_fragment(fragment_text),
    )


def media_jukebox_text_from_offset(payload: bytes, offset: int) -> str:
    return payload[offset:].rstrip(b"\x00").decode("utf-8", errors="replace")


def media_jukebox_wrapped_fragment(fragment_text: str) -> str:
    stripped_fragment = fragment_text.strip()
    stripped_fragment = stripped_fragment.removesuffix("</MJMD>")
    return f"<MJMD>{stripped_fragment}</MJMD>"


def collect_media_jukebox_values(
    values: JsonObject,
    element: ElementTree.Element[str],
    parent_name: str | None,
) -> None:
    tag_name = media_jukebox_tag_name(element.tag, parent_name)
    if tag_name is not None and len(list(element)) == 0 and element.text is not None:
        values[tag_name] = media_jukebox_value(tag_name, element.text)
    for child in element:
        collect_media_jukebox_values(values, child, element.tag)


def media_jukebox_tag_name(element_name: str, parent_name: str | None) -> str | None:
    if parent_name == "Tool" and element_name in {"Name", "Version"}:
        return f"Tool_{element_name}"
    if element_name in {"Tool_Name", "Tool_Version"}:
        return element_name
    if element_name in {"People", "Places", "Date", "Album", "Name", "Caption", "Keywords"}:
        return element_name
    return None


def media_jukebox_value(tag_name: str, text: str) -> str:
    if tag_name == "Date":
        return media_jukebox_date(text)
    return text


def media_jukebox_date(text: str) -> str:
    days = float(text)
    base = datetime(1899, 12, 30)
    value = base + timedelta(seconds=round(days * 24 * 60 * 60))
    return value.strftime("%Y:%m:%d %H:%M:%S")
