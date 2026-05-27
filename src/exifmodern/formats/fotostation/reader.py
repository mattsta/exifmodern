"""FotoWare FotoStation trailer reader."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.json_types import JsonObject, JsonValue

FOTOSTATION_SIGNATURE = b"\xa1\xb2\xc3\xd4"
FOTOSTATION_FOOTER_SIZE = 10
FOTOSTATION_SOFT_EDIT_TAG = 0x02

FOTOSTATION_SOFT_EDIT_TAGS = {
    0: "OriginalImageWidth",
    1: "OriginalImageHeight",
    2: "ColorPlanes",
    3: "XYResolution",
    4: "Rotation",
    6: "CropLeft",
    7: "CropTop",
    8: "CropRight",
    9: "CropBottom",
    11: "CropRotation",
}

FOTOSTATION_CROP_TAGS = {
    "CropLeft",
    "CropTop",
    "CropRight",
    "CropBottom",
}


@dataclass(frozen=True)
class FotoStationRecord:
    tag_id: int
    payload: bytes


def parse_fotostation_tags(data: bytes) -> JsonObject:
    tags: JsonObject = {}
    for record in fotostation_records(data):
        if record.tag_id == FOTOSTATION_SOFT_EDIT_TAG:
            tags.update(parse_fotostation_soft_edit(record.payload))
    return tags


def fotostation_records(data: bytes) -> list[FotoStationRecord]:
    records: list[FotoStationRecord] = []
    signature_offset = data.find(FOTOSTATION_SIGNATURE)
    while signature_offset >= 0:
        record = fotostation_record_at(data, signature_offset)
        if record is not None:
            records.append(record)
        signature_offset = data.find(FOTOSTATION_SIGNATURE, signature_offset + 1)
    return records


def fotostation_record_at(data: bytes, signature_offset: int) -> FotoStationRecord | None:
    footer_offset = signature_offset - 6
    if footer_offset < 0:
        return None
    tag_id = int.from_bytes(data[footer_offset : footer_offset + 2], "big")
    record_size = int.from_bytes(data[footer_offset + 2 : footer_offset + 6], "big")
    if record_size < FOTOSTATION_FOOTER_SIZE:
        return None
    payload_size = record_size - FOTOSTATION_FOOTER_SIZE
    payload_offset = footer_offset - payload_size
    if payload_offset < 0:
        return None
    return FotoStationRecord(
        tag_id=tag_id,
        payload=data[payload_offset:footer_offset],
    )


def parse_fotostation_soft_edit(payload: bytes) -> JsonObject:
    tags: JsonObject = {}
    entry_count = len(payload) // 4
    for index in range(entry_count):
        tag_name = FOTOSTATION_SOFT_EDIT_TAGS.get(index)
        if tag_name is None:
            continue
        raw_value = int.from_bytes(payload[index * 4 : index * 4 + 4], "big", signed=True)
        tags[tag_name] = fotostation_soft_edit_value(tag_name, raw_value)
    return tags


def fotostation_soft_edit_value(tag_name: str, raw_value: int) -> JsonValue:
    if tag_name == "XYResolution":
        return integral_float(raw_value / 1000)
    if tag_name == "Rotation":
        return integral_float(360 - raw_value / 100) if raw_value else 0
    if tag_name in FOTOSTATION_CROP_TAGS:
        return f"{integral_float(raw_value / 1000)}%"
    if tag_name == "CropRotation":
        return integral_float(-raw_value / 100)
    return raw_value


def integral_float(value: float) -> int | float:
    return int(value) if value.is_integer() else value
