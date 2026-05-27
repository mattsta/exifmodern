"""Camera Bits PhotoMechanic trailer reader."""

from __future__ import annotations

from exifmodern.json_types import JsonObject, JsonValue

PHOTO_MECHANIC_FOOTER_SIGNATURE = b"cbipcbbl"

PHOTO_MECHANIC_SOFT_EDIT_TAGS = {
    216: "Rotation",
    217: "CropLeft",
    218: "CropTop",
    219: "CropRight",
    220: "CropBottom",
    221: "Tagged",
    222: "ColorClass",
}

PHOTO_MECHANIC_ROTATION = {
    0: 0,
    1: 90,
    2: 180,
    3: 270,
}

PHOTO_MECHANIC_COLOR_CLASS = {
    0: "0 (None)",
    1: "1 (Winner)",
    2: "2 (Winner alt)",
    3: "3 (Superior)",
    4: "4 (Superior alt)",
    5: "5 (Typical)",
    6: "6 (Typical alt)",
    7: "7 (Extras)",
    8: "8 (Trash)",
}


def parse_photo_mechanic_trailer_tags(payload: bytes) -> JsonObject:
    tags: JsonObject = {}
    position = 0
    while position + 5 <= len(payload):
        if payload[position] != 0x1C:
            position += 1
            continue
        record = payload[position + 1]
        dataset = payload[position + 2]
        size = int.from_bytes(payload[position + 3 : position + 5], "big")
        value_offset = position + 5
        next_position = value_offset + size
        if next_position > len(payload):
            break
        if record == 2 and dataset in PHOTO_MECHANIC_SOFT_EDIT_TAGS:
            tag_name = PHOTO_MECHANIC_SOFT_EDIT_TAGS[dataset]
            tags[tag_name] = photo_mechanic_value(tag_name, payload[value_offset:next_position])
        position = next_position
    return tags


def photo_mechanic_value(tag_name: str, value: bytes) -> JsonValue:
    if len(value) != 4:
        return value.hex()
    raw_value = int.from_bytes(value, "big", signed=True)
    if tag_name == "Rotation":
        return PHOTO_MECHANIC_ROTATION.get(raw_value, raw_value)
    if tag_name == "Tagged":
        return "Yes" if raw_value else "No"
    if tag_name == "ColorClass":
        return PHOTO_MECHANIC_COLOR_CLASS.get(raw_value, raw_value)
    return raw_value


def photo_mechanic_trailer_payload(data: bytes) -> bytes | None:
    position = data.find(PHOTO_MECHANIC_FOOTER_SIGNATURE)
    while position >= 0:
        size_offset = position - 4
        if size_offset >= 0:
            size = int.from_bytes(data[size_offset:position], "big")
            payload_offset = size_offset - size
            if payload_offset >= 0:
                return data[payload_offset:size_offset]
        position = data.find(PHOTO_MECHANIC_FOOTER_SIGNATURE, position + 1)
    return None
