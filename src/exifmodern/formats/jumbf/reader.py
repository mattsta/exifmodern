"""JUMBF reader for currently proven C2PA/CAI parity slices."""

from __future__ import annotations

import json
from dataclasses import dataclass

from exifmodern.json_types import JsonObject, JsonValue

type BoxType = str

APP11_JUMBF_PREFIX = b"JP"
APP11_JUMBF_HEADER_SIZE = 8
BOX_HEADER_SIZE = 8
JUMD_TYPE_SIZE = 16


@dataclass(frozen=True)
class JumbfBox:
    box_type: BoxType
    data: bytes


def parse_jumbf_tags(payload: bytes) -> JsonObject:
    groups = parse_jumbf_groups(payload)
    return groups["JUMBF"]


def parse_jumbf_json_tags(payload: bytes) -> JsonObject:
    groups = parse_jumbf_groups(payload)
    return groups["JSON"]


def parse_jumbf_groups(payload: bytes) -> dict[str, JsonObject]:
    if not payload.startswith(APP11_JUMBF_PREFIX) or len(payload) < APP11_JUMBF_HEADER_SIZE:
        raise ValueError("Invalid JPEG APP11 JUMBF payload")
    jumbf_tags: JsonObject = {}
    json_tags: JsonObject = {}
    for box in read_boxes(payload[APP11_JUMBF_HEADER_SIZE:]):
        collect_jumbf_box_tags(box, jumbf_tags, json_tags, record_jumd=True)
    if not jumbf_tags and not json_tags:
        raise ValueError("No JUMBF tags found in APP11 payload")
    return {"JUMBF": jumbf_tags, "JSON": json_tags}


def collect_jumbf_box_tags(
    box: JumbfBox,
    jumbf_tags: JsonObject,
    json_tags: JsonObject,
    record_jumd: bool,
) -> None:
    if box.box_type == "jumd":
        tags = parse_jumd_tags(box.data)
        if record_jumd and tags and not jumbf_tags:
            jumbf_tags.update(tags)
        return
    if box.box_type == "json":
        json_tags.update(parse_json_box_tags(box.data))
        return
    if box.box_type == "jumb":
        first_child = True
        for child in read_boxes(box.data):
            collect_jumbf_box_tags(
                child,
                jumbf_tags,
                json_tags,
                record_jumd=record_jumd and first_child,
            )
            first_child = False


def read_boxes(data: bytes) -> list[JumbfBox]:
    boxes: list[JumbfBox] = []
    offset = 0
    while offset + BOX_HEADER_SIZE <= len(data):
        box_size = int.from_bytes(data[offset : offset + 4], "big")
        if box_size < BOX_HEADER_SIZE or offset + box_size > len(data):
            break
        box_type = data[offset + 4 : offset + 8].decode("latin-1", errors="replace")
        boxes.append(
            JumbfBox(
                box_type=box_type,
                data=data[offset + BOX_HEADER_SIZE : offset + box_size],
            )
        )
        offset += box_size
    return boxes


def parse_jumd_tags(data: bytes) -> JsonObject:
    if len(data) < JUMD_TYPE_SIZE + 1:
        return {}
    tags: JsonObject = {
        "JUMDType": format_jumd_type(data[:JUMD_TYPE_SIZE]),
    }
    toggles = data[JUMD_TYPE_SIZE]
    if toggles & 0x02:
        label = data[JUMD_TYPE_SIZE + 1 :].split(b"\x00", 1)[0]
        tags["JUMDLabel"] = label.decode("utf-8", errors="replace")
    return tags


def format_jumd_type(data: bytes) -> str:
    value = data.hex()
    first = value[0:8]
    try:
        ascii_prefix = bytes.fromhex(first).decode("ascii")
    except ValueError:
        ascii_prefix = ""
    if ascii_prefix.isalnum() and len(ascii_prefix) == 4:
        first = f"({ascii_prefix})"
    return "-".join((first, value[8:12], value[12:16], value[16:]))


def parse_json_box_tags(data: bytes) -> JsonObject:
    try:
        value: JsonValue = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError, json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    tags: JsonObject = {}
    title = value.get("title")
    location = value.get("location")
    copyright_value = value.get("copyright")
    if isinstance(title, str):
        tags["Title"] = title
    if isinstance(location, str):
        tags["Location"] = location
    if isinstance(copyright_value, str):
        tags["Copyright"] = copyright_value
    return tags
