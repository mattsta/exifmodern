"""Photoshop Image Resource Block reader for proven APP13 parity slices."""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import md5
from typing import Protocol

from exifmodern.formats.iptc.reader import parse_iptc_application_record
from exifmodern.json_types import JsonArray, JsonObject, JsonValue

type PhotoshopResourceId = int
type PhotoshopResourceName = str
type PhotoshopResourceParser = Callable[[bytes], JsonObject]

PHOTOSHOP_APP13_PREFIX = b"Photoshop 3.0\x00"
PHOTOSHOP_RESOURCE_SIGNATURES = {b"8BIM", b"8B64"}


@dataclass(frozen=True)
class PhotoshopResourceBlock:
    resource_id: PhotoshopResourceId
    name: PhotoshopResourceName
    data: bytes


@dataclass(frozen=True)
class PhotoshopRenderedTag:
    group: str
    name: str
    value: JsonValue


class PhotoshopResourceLike(Protocol):
    @property
    def resource_id(self) -> PhotoshopResourceId:
        """Photoshop IRB resource identifier."""
        ...

    @property
    def data(self) -> bytes:
        """Photoshop IRB resource payload."""
        ...


def parse_photoshop_iptc_tags(payload: bytes) -> JsonObject:
    for resource in parse_photoshop_resources(payload):
        if resource.resource_id == 0x0404:
            return parse_iptc_application_record(resource.data)
    return {}


def parse_current_iptc_digest_tags(payload: bytes) -> JsonObject:
    for resource in parse_photoshop_resources(payload):
        if resource.resource_id == 0x0404:
            return {"CurrentIPTCDigest": md5(resource.data, usedforsecurity=False).hexdigest()}
    return {}


def parse_photoshop_app13_rendered_tag_sequence(payload: bytes) -> tuple[PhotoshopRenderedTag, ...]:
    """Return tags in single-pass APP13 IRB dispatch order."""

    tags: list[PhotoshopRenderedTag] = []
    for resource in parse_photoshop_resources(payload):
        if resource.resource_id == 0x0404:
            tags.append(
                PhotoshopRenderedTag(
                    group="File",
                    name="CurrentIPTCDigest",
                    value=md5(resource.data, usedforsecurity=False).hexdigest(),
                )
            )
            tags.extend(
                PhotoshopRenderedTag(group="IPTC", name=name, value=value)
                for name, value in parse_iptc_application_record(resource.data).items()
            )
            continue
        group_tags = photoshop_resource_rendered_tags(resource)
        tags.extend(
            PhotoshopRenderedTag(group="Photoshop", name=name, value=value)
            for name, value in group_tags.items()
        )
    return tuple(tags)


def parse_photoshop_tags(payload: bytes) -> JsonObject:
    values: JsonObject = {}
    for resource in parse_photoshop_resources(payload):
        values.update(photoshop_resource_rendered_tags(resource))
    return values


def parse_photoshop_resolution_tags(payload: bytes) -> JsonObject:
    return photoshop_resource_by_id_tags(payload, 0x03ED, photoshop_resolution_tags)


def parse_photoshop_print_scale_tags(payload: bytes) -> JsonObject:
    return photoshop_resource_by_id_tags(payload, 0x0426, photoshop_print_scale_tags)


def parse_photoshop_slice_tags(payload: bytes) -> JsonObject:
    return photoshop_resource_by_id_tags(payload, 0x041A, photoshop_slice_tags)


def parse_photoshop_version_tags(payload: bytes) -> JsonObject:
    return photoshop_resource_by_id_tags(payload, 0x0421, photoshop_version_tags)


def parse_photoshop_pixel_tags(payload: bytes) -> JsonObject:
    return photoshop_resource_by_id_tags(payload, 0x0428, photoshop_pixel_tags)


def parse_photoshop_quality_tags(payload: bytes) -> JsonObject:
    return photoshop_resource_by_id_tags(payload, 0x0406, photoshop_quality_tags)


def photoshop_resource_by_id_tags(
    payload: bytes,
    resource_id: PhotoshopResourceId,
    read_resource: PhotoshopResourceParser,
) -> JsonObject:
    for resource in parse_photoshop_resources(payload):
        if resource.resource_id == resource_id:
            result: JsonObject = read_resource(resource.data)
            return result
    return {}


def parse_photoshop_resources(payload: bytes) -> list[PhotoshopResourceBlock]:
    if payload.startswith(PHOTOSHOP_APP13_PREFIX):
        position = len(PHOTOSHOP_APP13_PREFIX)
    elif payload[:4] in PHOTOSHOP_RESOURCE_SIGNATURES:
        position = 0
    else:
        raise ValueError("Unrecognized Photoshop resource data")
    resources: list[PhotoshopResourceBlock] = []
    while position + 12 <= len(payload):
        signature = payload[position : position + 4]
        if signature not in PHOTOSHOP_RESOURCE_SIGNATURES:
            break
        resource_id = int.from_bytes(payload[position + 4 : position + 6], "big")
        name, after_name = read_pascal_name(payload, position + 6)
        if after_name + 4 > len(payload):
            break
        data_size = int.from_bytes(payload[after_name : after_name + 4], "big")
        data_offset = after_name + 4
        data_end = data_offset + data_size
        if data_end > len(payload):
            break
        resources.append(
            PhotoshopResourceBlock(
                resource_id=resource_id,
                name=name,
                data=payload[data_offset:data_end],
            )
        )
        position = data_end + data_size % 2
    return resources


def read_pascal_name(payload: bytes, offset: int) -> tuple[str, int]:
    if offset >= len(payload):
        return "", len(payload)
    length = payload[offset]
    value_offset = offset + 1
    value_end = min(value_offset + length, len(payload))
    padded_end = value_offset + length + (1 if (1 + length) % 2 else 0)
    return payload[value_offset:value_end].decode("latin-1", errors="replace"), padded_end


def photoshop_resource_rendered_tags(resource: PhotoshopResourceLike) -> JsonObject:
    if resource.resource_id == 0x0425:
        return {"IPTCDigest": resource.data.hex()}
    if resource.resource_id == 0x03ED:
        return photoshop_resolution_tags(resource.data)
    if resource.resource_id == 0x0426:
        return photoshop_print_scale_tags(resource.data)
    if resource.resource_id == 0x041A:
        return photoshop_slice_tags(resource.data)
    if resource.resource_id == 0x0421:
        return photoshop_version_tags(resource.data)
    if resource.resource_id == 0x0428:
        return photoshop_pixel_tags(resource.data)
    if resource.resource_id == 0x0406:
        return photoshop_quality_tags(resource.data)
    if resource.resource_id == 0x040D and len(resource.data) >= 4:
        return {"GlobalAngle": int.from_bytes(resource.data[0:4], "big")}
    if resource.resource_id == 0x0419 and len(resource.data) >= 4:
        return {"GlobalAltitude": int.from_bytes(resource.data[0:4], "big")}
    if resource.resource_id == 0x040A and resource.data:
        return {"CopyrightFlag": resource.data[0] != 0}
    if resource.resource_id == 0x040B:
        return {"URL": resource.data.decode("latin-1", errors="replace")}
    if resource.resource_id == 0x041E:
        return {"URL_List": photoshop_url_list(resource.data)}
    return {}


def photoshop_resource_tags(resource: PhotoshopResourceLike) -> JsonObject:
    return photoshop_resource_rendered_tags(resource)


def photoshop_resolution_tags(data: bytes) -> JsonObject:
    if len(data) < 14:
        return {}
    return {
        "XResolution": compact_float_value(round(int.from_bytes(data[0:4], "big") / 65536, 2)),
        "DisplayedUnitsX": photoshop_resolution_unit(int.from_bytes(data[4:6], "big")),
        "YResolution": compact_float_value(round(int.from_bytes(data[8:12], "big") / 65536, 2)),
        "DisplayedUnitsY": photoshop_resolution_unit(int.from_bytes(data[12:14], "big")),
    }


def photoshop_resolution_unit(value: int) -> str | int:
    return {
        1: "inches",
        2: "cm",
    }.get(value, value)


def photoshop_print_scale_tags(data: bytes) -> JsonObject:
    if len(data) < 14:
        return {}
    x_position = unpack_float32(data[2:6])
    y_position = unpack_float32(data[6:10])
    return {
        "PrintStyle": photoshop_print_style(int.from_bytes(data[0:2], "big")),
        "PrintPosition": f"{compact_number(x_position)} {compact_number(y_position)}",
        "PrintScale": compact_float_value(unpack_float32(data[10:14])),
    }


def photoshop_print_style(value: int) -> str | int:
    return {
        0: "Centered",
        1: "Size to Fit",
        2: "User Defined",
    }.get(value, value)


def photoshop_slice_tags(data: bytes) -> JsonObject:
    if len(data) < 28:
        return {}
    name, after_name = read_utf16be_counted_string(data, 20)
    if after_name + 4 > len(data):
        return {"SlicesGroupName": name}
    return {
        "SlicesGroupName": name,
        "NumSlices": int.from_bytes(data[after_name : after_name + 4], "big"),
    }


def photoshop_version_tags(data: bytes) -> JsonObject:
    if len(data) < 5:
        return {}
    writer, after_writer = read_utf16be_counted_string(data, 5)
    reader, _ = read_utf16be_counted_string(data, after_writer)
    return {
        "HasRealMergedData": "Yes" if data[4] else "No",
        "WriterName": writer,
        "ReaderName": reader,
    }


def photoshop_pixel_tags(data: bytes) -> JsonObject:
    if len(data) < 12:
        return {}
    return {"PixelAspectRatio": compact_float_value(struct.unpack(">d", data[4:12])[0])}


def photoshop_quality_tags(data: bytes) -> JsonObject:
    if len(data) < 6:
        return {}
    raw_quality = int.from_bytes(data[0:2], "big", signed=True)
    raw_format = int.from_bytes(data[2:4], "big")
    tags: JsonObject = {
        "PhotoshopQuality": raw_quality + 4,
        "PhotoshopFormat": photoshop_format(raw_format),
    }
    if raw_format == 0x0101:
        tags["ProgressiveScans"] = photoshop_progressive_scans(int.from_bytes(data[4:6], "big"))
    return tags


def photoshop_format(value: int) -> str | int:
    return {
        0x0000: "Standard",
        0x0001: "Optimized",
        0x0101: "Progressive",
    }.get(value, value)


def photoshop_progressive_scans(value: int) -> str | int:
    return {
        1: "3 Scans",
        2: "4 Scans",
        3: "5 Scans",
    }.get(value, value)


def photoshop_url_list(data: bytes) -> JsonValue:
    if len(data) < 4:
        return []
    count = int.from_bytes(data[0:4], "big")
    position = 4
    values: JsonArray = []
    for _ in range(count):
        position += 8
        if position + 4 > len(data):
            break
        value, position = read_utf16be_counted_string(data, position)
        values.append(value)
    return values


def read_utf16be_counted_string(data: bytes, offset: int) -> tuple[str, int]:
    if offset + 4 > len(data):
        return "", len(data)
    character_count = int.from_bytes(data[offset : offset + 4], "big")
    text_offset = offset + 4
    text_end = min(text_offset + character_count * 2, len(data))
    return data[text_offset:text_end].decode("utf-16-be", errors="replace"), text_end


def unpack_float32(data: bytes) -> float:
    value: float = struct.unpack(">f", data)[0]
    return value


def compact_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def compact_float_value(value: float) -> int | float:
    return int(value) if value.is_integer() else value
