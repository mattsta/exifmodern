"""Canon VRD v1 trailer reader."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.json_types import JsonObject, JsonValue
from exifmodern.services.binary import ieee754_float32

type IntRenderLookup = dict[int, int | str]

CANON_VRD_SIGNATURE = b"CANON OPTIONAL DATA\x00"
CANON_VRD_HEADER_SIZE = 0x1C
CANON_VRD_FOOTER_SIZE = 0x40
CANON_VRD_LENGTH_OVERHEAD = CANON_VRD_HEADER_SIZE + CANON_VRD_FOOTER_SIZE
CANON_VRD_EDIT_DATA_BLOCK = 0xFFFF00F4
CANON_VRD_V1_SIZE = 0x272

CANON_VRD_YES_NO: IntRenderLookup = {
    0: "No",
    1: "Yes",
}

WHITE_BALANCE_ADJ: IntRenderLookup = {
    0: "Auto",
    1: "Daylight",
    2: "Cloudy",
    3: "Tungsten",
    4: "Fluorescent",
    5: "Flash",
    8: "Shade",
    9: "Kelvin",
    30: "Manual (Click)",
    31: "Shot Settings",
}

RAW_COLOR_ADJ: IntRenderLookup = {
    0: "Shot Settings",
    1: "Faithful",
    2: "Custom",
}

TONE_CURVE_PROPERTY: IntRenderLookup = {
    0: "Shot Settings",
    1: "Linear",
    2: "Custom 1",
    3: "Custom 2",
    4: "Custom 3",
    5: "Custom 4",
    6: "Custom 5",
}

TONE_CURVE_MODE: IntRenderLookup = {
    0: "RGB",
    1: "Luminance",
}

TONE_CURVE_INTERPOLATION: IntRenderLookup = {
    0: "Curve",
    1: "Straight",
}

CROP_ASPECT_RATIO: IntRenderLookup = {
    0: "Free",
    1: "3:2",
    2: "2:3",
    3: "4:3",
    4: "3:4",
    5: "A-size Landscape",
    6: "A-size Portrait",
    7: "Letter-size Landscape",
    8: "Letter-size Portrait",
    9: "4:5",
    10: "5:4",
    11: "1:1",
    12: "Circle",
    65535: "Custom",
}

CHECK_MARK: IntRenderLookup = {
    0: "Clear",
    1: 1,
    2: 2,
    3: 3,
}

ROTATION: IntRenderLookup = {
    0: 0,
    1: 90,
    2: 180,
    3: 270,
}

WORK_COLOR_SPACE: IntRenderLookup = {
    0: "sRGB",
    1: "Adobe RGB",
    2: "Wide Gamut RGB",
    3: "Apple RGB",
    4: "ColorMatch RGB",
}


@dataclass(frozen=True)
class CanonVrdTrailer:
    start: int
    payload: bytes


@dataclass(frozen=True)
class CanonVrdField:
    name: str
    offset: int
    format_name: str
    count: int = 1


CANON_VRD_V1_FIELDS = (
    CanonVrdField("VRDVersion", 0x002, "u16"),
    CanonVrdField("WBAdjRGGBLevels", 0x006, "u16", 4),
    CanonVrdField("WhiteBalanceAdj", 0x018, "u16"),
    CanonVrdField("WBAdjColorTemp", 0x01A, "u16"),
    CanonVrdField("WBFineTuneActive", 0x024, "u16"),
    CanonVrdField("WBFineTuneSaturation", 0x028, "u16"),
    CanonVrdField("WBFineTuneTone", 0x02C, "u16"),
    CanonVrdField("RawColorAdj", 0x02E, "u16"),
    CanonVrdField("RawCustomSaturation", 0x030, "s32"),
    CanonVrdField("RawCustomTone", 0x034, "s32"),
    CanonVrdField("RawBrightnessAdj", 0x038, "s32"),
    CanonVrdField("ToneCurveProperty", 0x03C, "u16"),
    CanonVrdField("DynamicRangeMin", 0x07A, "u16"),
    CanonVrdField("DynamicRangeMax", 0x07C, "u16"),
    CanonVrdField("ToneCurveActive", 0x110, "u16"),
    CanonVrdField("ToneCurveMode", 0x113, "u8"),
    CanonVrdField("BrightnessAdj", 0x114, "s8"),
    CanonVrdField("ContrastAdj", 0x115, "s8"),
    CanonVrdField("SaturationAdj", 0x116, "s16"),
    CanonVrdField("ColorToneAdj", 0x11E, "s32"),
    CanonVrdField("LuminanceCurvePoints", 0x126, "u16", 21),
    CanonVrdField("LuminanceCurveLimits", 0x150, "u16", 4),
    CanonVrdField("ToneCurveInterpolation", 0x159, "u8"),
    CanonVrdField("RedCurvePoints", 0x160, "u16", 21),
    CanonVrdField("RedCurveLimits", 0x18A, "u16", 4),
    CanonVrdField("GreenCurvePoints", 0x19A, "u16", 21),
    CanonVrdField("GreenCurveLimits", 0x1C4, "u16", 4),
    CanonVrdField("BlueCurvePoints", 0x1D4, "u16", 21),
    CanonVrdField("BlueCurveLimits", 0x1FE, "u16", 4),
    CanonVrdField("RGBCurvePoints", 0x20E, "u16", 21),
    CanonVrdField("RGBCurveLimits", 0x238, "u16", 4),
    CanonVrdField("CropActive", 0x244, "u16"),
    CanonVrdField("CropLeft", 0x246, "u16"),
    CanonVrdField("CropTop", 0x248, "u16"),
    CanonVrdField("CropWidth", 0x24A, "u16"),
    CanonVrdField("CropHeight", 0x24C, "u16"),
    CanonVrdField("SharpnessAdj", 0x25A, "u16"),
    CanonVrdField("CropAspectRatio", 0x260, "u16"),
    CanonVrdField("ConstrainedCropWidth", 0x262, "float32"),
    CanonVrdField("ConstrainedCropHeight", 0x266, "float32"),
    CanonVrdField("CheckMark", 0x26A, "u16"),
    CanonVrdField("Rotation", 0x26E, "u16"),
    CanonVrdField("WorkColorSpace", 0x270, "u16"),
)


def parse_canon_vrd_tags(data: bytes) -> JsonObject:
    trailer = find_canon_vrd_trailer(data)
    if trailer is None:
        raise ValueError("No CanonVRD trailer found")
    tags: JsonObject = {}
    for block_type, block_payload in canon_vrd_blocks(trailer.payload):
        if block_type != CANON_VRD_EDIT_DATA_BLOCK:
            continue
        tags.update(parse_canon_vrd_edit_data(block_payload))
    if not tags:
        raise ValueError("No CanonVRD edit data found")
    return tags


def find_canon_vrd_trailer(data: bytes) -> CanonVrdTrailer | None:
    footer_position = data.rfind(CANON_VRD_SIGNATURE)
    while footer_position >= 0:
        trailer = canon_vrd_trailer_at_footer(data, footer_position)
        if trailer is not None:
            return trailer
        footer_position = data.rfind(CANON_VRD_SIGNATURE, 0, footer_position)
    return None


def canon_vrd_trailer_at_footer(data: bytes, footer_position: int) -> CanonVrdTrailer | None:
    footer_end = footer_position + CANON_VRD_FOOTER_SIZE
    if footer_end > len(data):
        return None
    data_length = read_u32(data, footer_position + 0x14)
    trailer_length = data_length + CANON_VRD_LENGTH_OVERHEAD
    trailer_start = footer_end - trailer_length
    if trailer_start < 0:
        return None
    if data[trailer_start : trailer_start + len(CANON_VRD_SIGNATURE)] != CANON_VRD_SIGNATURE:
        return None
    payload = data[trailer_start:footer_end]
    return CanonVrdTrailer(start=trailer_start, payload=payload)


def canon_vrd_blocks(trailer: bytes) -> list[tuple[int, bytes]]:
    footer_start = len(trailer) - CANON_VRD_FOOTER_SIZE
    position = CANON_VRD_HEADER_SIZE
    blocks: list[tuple[int, bytes]] = []
    while position + 8 <= footer_start:
        block_type = read_u32(trailer, position)
        block_length = read_u32(trailer, position + 4)
        position += 8
        block_end = position + block_length
        if block_end > footer_start:
            raise ValueError("Truncated CanonVRD block")
        blocks.append((block_type, trailer[position:block_end]))
        position = block_end
    return blocks


def parse_canon_vrd_edit_data(block: bytes) -> JsonObject:
    if len(block) < 4:
        raise ValueError("Truncated CanonVRD edit block")
    record_length = read_u32(block, 0)
    record_end = 4 + record_length
    if record_end > len(block):
        raise ValueError("Truncated CanonVRD edit record")
    vrd_v1 = block[4 : min(record_end, 4 + CANON_VRD_V1_SIZE)]
    if len(vrd_v1) < CANON_VRD_V1_SIZE:
        raise ValueError("Truncated CanonVRD v1 edit data")
    return parse_canon_vrd_v1(vrd_v1)


def parse_canon_vrd_v1(data: bytes) -> JsonObject:
    tags: JsonObject = {}
    for field in CANON_VRD_V1_FIELDS:
        raw_value = read_canon_vrd_field(data, field)
        tags[field.name] = render_canon_vrd_value(field.name, raw_value)
    return tags


def read_canon_vrd_field(data: bytes, field: CanonVrdField) -> int | float | list[int]:
    if field.count != 1:
        values: list[int] = []
        for index in range(field.count):
            values.append(read_numeric_field(data, field.offset + index * 2, field.format_name))
        return values
    if field.format_name == "float32":
        return ieee754_float32(read_bytes(data, field.offset, 4), "big")
    return read_numeric_field(data, field.offset, field.format_name)


def read_numeric_field(data: bytes, offset: int, format_name: str) -> int:
    if format_name == "u8":
        return read_bytes(data, offset, 1)[0]
    if format_name == "s8":
        return int.from_bytes(read_bytes(data, offset, 1), "big", signed=True)
    if format_name == "u16":
        return int.from_bytes(read_bytes(data, offset, 2), "big")
    if format_name == "s16":
        return int.from_bytes(read_bytes(data, offset, 2), "big", signed=True)
    if format_name == "s32":
        return int.from_bytes(read_bytes(data, offset, 4), "big", signed=True)
    raise ValueError(f"Unsupported CanonVRD field format: {format_name}")


def render_canon_vrd_value(name: str, value: int | float | list[int]) -> JsonValue:
    if name == "VRDVersion" and isinstance(value, int):
        return render_vrd_version(value)
    if name == "RawBrightnessAdj" and isinstance(value, int):
        return round(value / 6000, 2)
    if name in {
        "WBAdjRGGBLevels",
        "LuminanceCurveLimits",
        "RedCurveLimits",
        "GreenCurveLimits",
        "BlueCurveLimits",
        "RGBCurveLimits",
    }:
        return render_int_list(require_int_list(value))
    if name in {
        "LuminanceCurvePoints",
        "RedCurvePoints",
        "GreenCurvePoints",
        "BlueCurvePoints",
        "RGBCurvePoints",
    }:
        return render_tone_curve(require_int_list(value))
    if name in {"WBFineTuneActive", "ToneCurveActive", "CropActive"} and isinstance(value, int):
        return CANON_VRD_YES_NO.get(value, value)
    if name == "WhiteBalanceAdj" and isinstance(value, int):
        return WHITE_BALANCE_ADJ.get(value, value)
    if name == "RawColorAdj" and isinstance(value, int):
        return RAW_COLOR_ADJ.get(value, value)
    if name == "ToneCurveProperty" and isinstance(value, int):
        return TONE_CURVE_PROPERTY.get(value, value)
    if name == "ToneCurveMode" and isinstance(value, int):
        return TONE_CURVE_MODE.get(value, value)
    if name == "ToneCurveInterpolation" and isinstance(value, int):
        return TONE_CURVE_INTERPOLATION.get(value, value)
    if name == "CropAspectRatio" and isinstance(value, int):
        return CROP_ASPECT_RATIO.get(value, value)
    if name == "CheckMark" and isinstance(value, int):
        return CHECK_MARK.get(value, value)
    if name == "Rotation" and isinstance(value, int):
        return ROTATION.get(value, value)
    if name == "WorkColorSpace" and isinstance(value, int):
        return WORK_COLOR_SPACE.get(value, value)
    if name in {"ConstrainedCropWidth", "ConstrainedCropHeight"} and isinstance(value, float):
        return int(value) if value.is_integer() else value
    if isinstance(value, list):
        raise ValueError(f"Unhandled CanonVRD list field: {name}")
    return value


def render_vrd_version(value: int) -> str:
    text = str(value)
    if len(text) < 2:
        return text
    return f"{text[0]}.{text[1:-1]}.{text[-1]}"


def render_tone_curve(values: list[int]) -> str:
    point_count = values[0]
    if point_count < 2 or point_count > 10:
        return render_int_list(values)
    points: list[str] = []
    position = 1
    for _ in range(point_count):
        points.append(f"({values[position]},{values[position + 1]})")
        position += 2
    return " ".join(points)


def render_int_list(values: list[int]) -> str:
    return " ".join(str(value) for value in values)


def require_int_list(value: int | float | list[int]) -> list[int]:
    if isinstance(value, list):
        return value
    raise ValueError("Expected CanonVRD integer list")


def read_u32(data: bytes, offset: int) -> int:
    return int.from_bytes(read_bytes(data, offset, 4), "big")


def read_bytes(data: bytes, offset: int, size: int) -> bytes:
    if offset + size > len(data):
        raise ValueError(f"Truncated CanonVRD data at offset {offset}")
    return data[offset : offset + size]
