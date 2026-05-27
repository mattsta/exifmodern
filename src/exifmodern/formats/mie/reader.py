"""Bounded, source-backed MIE scalar reader."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonObject, JsonValue

type MieEndian = Literal["big", "little"]
type MieScalarValue = bytes | str | int | float | list[str]

MIE_SYNC_BYTE = 0x7E
MIE_GROUP_FORMATS = {0x10, 0x18}
MIE_UTF8_FORMAT = 0x28
MIE_SIGNATURE_TAG = b"0MIE"
MIE_TRAILER_SIGNATURE_TAG = "zmie"

MIE_PM_SOURCE_PATH = "lib/Image/ExifTool/MIE.pm"

MIE_FORMAT_SOURCE = "mie_format"
MIE_MAIN_SOURCE = "mie_main"
MIE_META_SOURCE = "mie_meta"
MIE_DOC_SOURCE = "mie_doc"
MIE_GEO_SOURCE = "mie_geo"
MIE_IMAGE_SOURCE = "mie_image"
MIE_THUMBNAIL_SOURCE = "mie_thumbnail"
MIE_CAMERA_SOURCE = "mie_camera"
MIE_ORIENT_SOURCE = "mie_orient"
MIE_LENS_SOURCE = "mie_lens"
MIE_FLASH_SOURCE = "mie_flash"
MIE_PROCESS_SOURCE = "mie_process"
MIE_HEADER_SOURCE = "mie_header"

MIE_READER_SOURCES = (
    MIE_FORMAT_SOURCE,
    MIE_MAIN_SOURCE,
    MIE_META_SOURCE,
    MIE_DOC_SOURCE,
    MIE_GEO_SOURCE,
    MIE_IMAGE_SOURCE,
    MIE_THUMBNAIL_SOURCE,
    MIE_CAMERA_SOURCE,
    MIE_ORIENT_SOURCE,
    MIE_LENS_SOURCE,
    MIE_FLASH_SOURCE,
    MIE_PROCESS_SOURCE,
    MIE_HEADER_SOURCE,
)


@dataclass(frozen=True)
class MieElement:
    format_code: int
    tag_name: str
    data: bytes
    next_offset: int
    data_offset: int


@dataclass(frozen=True)
class MieTagDefinition:
    name: str
    family_2_group: str
    evidence_id: str


@dataclass(frozen=True)
class MieGroupDefinition:
    table_name: str
    family_1_group: str
    family_2_group: str
    evidence_id: str


@dataclass(frozen=True)
class MieGroupContext:
    table_key: str
    table_name: str
    family_1_group: str
    family_2_group: str
    evidence_id: str


@dataclass(frozen=True)
class MieReadTag:
    name: str
    group: str
    source_table: str
    tag_id: str
    raw_value: MieScalarValue
    rendered_value: MieScalarValue
    byte_offset: int
    evidence_ids: tuple[str, ...]


ROOT_CONTEXT = MieGroupContext(
    table_key="Main",
    table_name="Image::ExifTool::MIE::Main",
    family_1_group="MIE-Main",
    family_2_group="Other",
    evidence_id=MIE_MAIN_SOURCE,
)

GROUP_DEFINITIONS: dict[tuple[str, str], MieGroupDefinition] = {
    ("Main", "Meta"): MieGroupDefinition(
        "Image::ExifTool::MIE::Meta", "MIE-Meta", "Image", MIE_META_SOURCE
    ),
    ("Meta", "Document"): MieGroupDefinition(
        "Image::ExifTool::MIE::Doc", "MIE-Doc", "Document", MIE_DOC_SOURCE
    ),
    ("Meta", "Geo"): MieGroupDefinition(
        "Image::ExifTool::MIE::Geo", "MIE-Geo", "Location", MIE_GEO_SOURCE
    ),
    ("Meta", "Image"): MieGroupDefinition(
        "Image::ExifTool::MIE::Image", "MIE-Image", "Image", MIE_IMAGE_SOURCE
    ),
    ("Meta", "Thumbnail"): MieGroupDefinition(
        "Image::ExifTool::MIE::Thumbnail", "MIE-Thumbnail", "Image", MIE_THUMBNAIL_SOURCE
    ),
    ("Meta", "Camera"): MieGroupDefinition(
        "Image::ExifTool::MIE::Camera", "MIE-Camera", "Camera", MIE_CAMERA_SOURCE
    ),
    ("Camera", "Flash"): MieGroupDefinition(
        "Image::ExifTool::MIE::Flash", "MIE-Flash", "Camera", MIE_FLASH_SOURCE
    ),
    ("Camera", "Lens"): MieGroupDefinition(
        "Image::ExifTool::MIE::Lens", "MIE-Lens", "Camera", MIE_LENS_SOURCE
    ),
    ("Camera", "Orientation"): MieGroupDefinition(
        "Image::ExifTool::MIE::Orient", "MIE-Orient", "Camera", MIE_ORIENT_SOURCE
    ),
}

TAG_DEFINITIONS: dict[tuple[str, str], MieTagDefinition] = {
    ("Main", "0Type"): MieTagDefinition("SubfileType", "Other", MIE_MAIN_SOURCE),
    ("Main", "0Vers"): MieTagDefinition("MIEVersion", "Other", MIE_MAIN_SOURCE),
    ("Main", "1Name"): MieTagDefinition("SubfileName", "Other", MIE_MAIN_SOURCE),
    ("Main", "2MIME"): MieTagDefinition("SubfileMIMEType", "Other", MIE_MAIN_SOURCE),
    ("Main", "data"): MieTagDefinition("SubfileData", "Other", MIE_MAIN_SOURCE),
    ("Main", MIE_TRAILER_SIGNATURE_TAG): MieTagDefinition(
        "TrailerSignature", "Other", MIE_MAIN_SOURCE
    ),
    ("Doc", "Comment"): MieTagDefinition("Comment", "Document", MIE_DOC_SOURCE),
    ("Doc", "Copyright"): MieTagDefinition("Copyright", "Author", MIE_DOC_SOURCE),
    ("Doc", "CreateDate"): MieTagDefinition("CreateDate", "Time", MIE_DOC_SOURCE),
    ("Doc", "Keywords"): MieTagDefinition("Keywords", "Document", MIE_DOC_SOURCE),
    ("Doc", "ModifyDate"): MieTagDefinition("ModifyDate", "Time", MIE_DOC_SOURCE),
    ("Doc", "OriginalDate"): MieTagDefinition("DateTimeOriginal", "Time", MIE_DOC_SOURCE),
    ("Doc", "References"): MieTagDefinition("References", "Document", MIE_DOC_SOURCE),
    ("Doc", "Software"): MieTagDefinition("Software", "Document", MIE_DOC_SOURCE),
    ("Doc", "Title"): MieTagDefinition("Title", "Document", MIE_DOC_SOURCE),
    ("Doc", "URL"): MieTagDefinition("URL", "Document", MIE_DOC_SOURCE),
    ("Geo", "City"): MieTagDefinition("City", "Location", MIE_GEO_SOURCE),
    ("Geo", "Country"): MieTagDefinition("Country", "Location", MIE_GEO_SOURCE),
    ("Geo", "State"): MieTagDefinition("State", "Location", MIE_GEO_SOURCE),
    ("Image", "ColorSpace"): MieTagDefinition("ColorSpace", "Image", MIE_IMAGE_SOURCE),
    ("Image", "Components"): MieTagDefinition("ComponentsConfiguration", "Image", MIE_IMAGE_SOURCE),
    ("Image", "ImageSize"): MieTagDefinition("ImageSize", "Image", MIE_IMAGE_SOURCE),
    ("Image", "Resolution"): MieTagDefinition("Resolution", "Image", MIE_IMAGE_SOURCE),
    ("Thumbnail", "ImageSize"): MieTagDefinition(
        "ThumbnailImageSize", "Image", MIE_THUMBNAIL_SOURCE
    ),
    ("Thumbnail", "data"): MieTagDefinition("ThumbnailImage", "Preview", MIE_THUMBNAIL_SOURCE),
    ("Camera", "ColorTemperature"): MieTagDefinition(
        "ColorTemperature", "Camera", MIE_CAMERA_SOURCE
    ),
    ("Camera", "Contrast"): MieTagDefinition("Contrast", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "ExposureComp"): MieTagDefinition(
        "ExposureCompensation", "Camera", MIE_CAMERA_SOURCE
    ),
    ("Camera", "ExposureMode"): MieTagDefinition("ExposureMode", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "ExposureTime"): MieTagDefinition("ExposureTime", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "FocusMode"): MieTagDefinition("FocusMode", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "ISO"): MieTagDefinition("ISO", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "Make"): MieTagDefinition("Make", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "Model"): MieTagDefinition("Model", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "OwnerName"): MieTagDefinition("OwnerName", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "Saturation"): MieTagDefinition("Saturation", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "SerialNumber"): MieTagDefinition("SerialNumber", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "Sharpness"): MieTagDefinition("Sharpness", "Camera", MIE_CAMERA_SOURCE),
    ("Camera", "ShootingMode"): MieTagDefinition("ShootingMode", "Camera", MIE_CAMERA_SOURCE),
    ("Flash", "ExposureComp"): MieTagDefinition("FlashExposureComp", "Camera", MIE_FLASH_SOURCE),
    ("Flash", "GuideNumber"): MieTagDefinition("FlashGuideNumber", "Camera", MIE_FLASH_SOURCE),
    ("Lens", "FNumber"): MieTagDefinition("FNumber", "Camera", MIE_LENS_SOURCE),
    ("Lens", "MaxAperture"): MieTagDefinition("MaxAperture", "Camera", MIE_LENS_SOURCE),
    ("Lens", "MinAperture"): MieTagDefinition("MinAperture", "Camera", MIE_LENS_SOURCE),
    ("Orient", "Rotation"): MieTagDefinition("Rotation", "Camera", MIE_ORIENT_SOURCE),
}


def parse_mie_trailer_tags(data: bytes) -> JsonObject:
    offset = mie_trailer_offset(data)
    if offset is None:
        raise ValueError("No MIE trailer found")
    return parse_mie_tags(data[offset:])


def parse_mie_tags(payload: bytes) -> JsonObject:
    return {tag.name: _json_value(tag.rendered_value) for tag in parse_mie_read_tags(payload)}


def parse_mie_read_tags(payload: bytes) -> tuple[MieReadTag, ...]:
    tags: list[MieReadTag] = []
    _parse_mie_group(payload, 0, len(payload), ROOT_CONTEXT, mie_endian(payload), tags)
    return tuple(tags)


def _parse_mie_group(
    payload: bytes,
    start_offset: int,
    end_offset: int,
    context: MieGroupContext,
    endian: MieEndian,
    tags: list[MieReadTag],
) -> int:
    offset = start_offset
    while offset + 4 <= end_offset:
        if payload[offset] != MIE_SYNC_BYTE:
            break
        if payload[offset : offset + 4] == b"~\x00\x00\x00":
            return offset + 4
        element = read_mie_element(payload, offset, endian)
        if element is None:
            break
        if element.format_code in MIE_GROUP_FORMATS:
            child_endian: MieEndian = "little" if element.format_code & 0x08 else "big"
            child_context = (
                ROOT_CONTEXT
                if context.table_key == "Main" and element.tag_name == "0MIE"
                else _child_context(context, element.tag_name)
            )
            if element.data:
                _parse_mie_group(
                    element.data,
                    0,
                    len(element.data),
                    child_context,
                    child_endian,
                    tags,
                )
            else:
                offset = _parse_mie_group(
                    payload,
                    element.next_offset,
                    end_offset,
                    child_context,
                    child_endian,
                    tags,
                )
                continue
        else:
            tag = _read_tag_for_element(context, element, endian)
            if tag is not None:
                tags.append(tag)
        offset = element.next_offset
    return offset


def _legacy_parse_mie_tags(payload: bytes) -> JsonObject:
    tags: JsonObject = {}
    group_stack: list[str] = []
    offset = 0
    endian = mie_endian(payload)
    while offset + 4 <= len(payload):
        if payload[offset] != MIE_SYNC_BYTE:
            break
        if payload[offset : offset + 4] == b"~\x00\x00\x00":
            if group_stack:
                group_stack.pop()
            offset += 4
            continue
        element = read_mie_element(payload, offset, endian)
        if element is None:
            break
        if element.format_code in MIE_GROUP_FORMATS:
            group_stack.append(element.tag_name)
        elif element.tag_name == "Copyright" and group_stack[-2:] == ["Meta", "Document"]:
            tags["Copyright"] = element.data.decode("utf-8", errors="replace")
        elif element.tag_name == MIE_TRAILER_SIGNATURE_TAG:
            tags["TrailerSignature"] = element.data.decode("latin-1", errors="replace")
        offset = element.next_offset
    return tags


def mie_trailer_offset(data: bytes) -> int | None:
    for format_code in MIE_GROUP_FORMATS:
        signature = bytes((MIE_SYNC_BYTE, format_code, len(MIE_SIGNATURE_TAG)))
        position = data.find(signature)
        while position >= 0:
            tag_offset = position + 4
            tag_end = tag_offset + len(MIE_SIGNATURE_TAG)
            if tag_end <= len(data) and data[tag_offset:tag_end] == MIE_SIGNATURE_TAG:
                return position
            position = data.find(signature, position + 1)
    return None


def mie_endian(payload: bytes) -> MieEndian:
    return "little" if len(payload) > 1 and payload[1] == 0x18 else "big"


def read_mie_element(payload: bytes, offset: int, endian: MieEndian) -> MieElement | None:
    if offset + 4 > len(payload) or payload[offset] != MIE_SYNC_BYTE:
        return None
    format_code = payload[offset + 1]
    tag_length = payload[offset + 2]
    data_length_code = payload[offset + 3]
    tag_offset = offset + 4
    tag_end = tag_offset + tag_length
    if tag_end > len(payload):
        return None
    tag_name = payload[tag_offset:tag_end].decode("latin-1", errors="replace")
    data_length, data_offset = mie_data_length(payload, tag_end, data_length_code, endian)
    data_end = data_offset + data_length
    if data_end > len(payload):
        return None
    return MieElement(
        format_code=format_code,
        tag_name=tag_name,
        data=payload[data_offset:data_end],
        next_offset=data_end,
        data_offset=data_offset,
    )


def mie_data_length(
    payload: bytes,
    offset: int,
    data_length_code: int,
    endian: MieEndian,
) -> tuple[int, int]:
    if data_length_code < 253:
        return data_length_code, offset
    if data_length_code == 254 and offset + 4 <= len(payload):
        return int.from_bytes(payload[offset : offset + 4], endian), offset + 4
    if data_length_code == 255 and offset + 2 <= len(payload):
        return int.from_bytes(payload[offset : offset + 2], endian), offset + 2
    if data_length_code == 253 and offset + 8 <= len(payload):
        return int.from_bytes(payload[offset : offset + 8], endian), offset + 8
    return 0, len(payload)


def _child_context(context: MieGroupContext, tag_name: str) -> MieGroupContext:
    definition = GROUP_DEFINITIONS.get((context.table_key, tag_name))
    if definition is None:
        return MieGroupContext(
            table_key=tag_name,
            table_name="Image::ExifTool::MIE::Unknown",
            family_1_group="MIE-Unknown",
            family_2_group=context.family_2_group,
            evidence_id=MIE_PROCESS_SOURCE,
        )
    return MieGroupContext(
        table_key=definition.table_name.rsplit("::", 1)[1],
        table_name=definition.table_name,
        family_1_group=definition.family_1_group,
        family_2_group=definition.family_2_group,
        evidence_id=definition.evidence_id,
    )


def _read_tag_for_element(
    context: MieGroupContext,
    element: MieElement,
    endian: MieEndian,
) -> MieReadTag | None:
    tag_id, units = _split_units(element.tag_name)
    definition = _tag_definition(context, tag_id)
    if definition is None:
        return None
    if definition.name == "TrailerSignature" and not element.data:
        trailer_value: MieScalarValue = ""
        trailer_rendered: MieScalarValue = ""
        return MieReadTag(
            name=definition.name,
            group=context.family_1_group,
            source_table=context.table_name,
            tag_id=tag_id,
            raw_value=trailer_value,
            rendered_value=trailer_rendered,
            byte_offset=element.data_offset,
            evidence_ids=(definition.evidence_id, MIE_FORMAT_SOURCE, MIE_PROCESS_SOURCE),
        )
    if definition.name in {"SubfileData", "ThumbnailImage"} and (element.format_code & 0xFB) == 0:
        return MieReadTag(
            name=definition.name,
            group=context.family_1_group,
            source_table=context.table_name,
            tag_id=tag_id,
            raw_value=element.data,
            rendered_value=element.data,
            byte_offset=element.data_offset,
            evidence_ids=(definition.evidence_id, MIE_FORMAT_SOURCE, MIE_PROCESS_SOURCE),
        )
    value = _mie_value(element.data, element.format_code, endian)
    if value is None:
        return None
    rendered = _render_value(definition.name, value, units)
    return MieReadTag(
        name=definition.name,
        group=context.family_1_group,
        source_table=context.table_name,
        tag_id=tag_id,
        raw_value=value,
        rendered_value=rendered,
        byte_offset=element.data_offset,
        evidence_ids=(definition.evidence_id, MIE_FORMAT_SOURCE, MIE_PROCESS_SOURCE),
    )


def _tag_definition(context: MieGroupContext, tag_id: str) -> MieTagDefinition | None:
    definition = TAG_DEFINITIONS.get((context.table_key, tag_id))
    if definition is not None:
        return definition
    localized = _localized_tag_base(tag_id)
    if localized is None:
        return None
    base_tag, language = localized
    base_definition = TAG_DEFINITIONS.get((context.table_key, base_tag))
    if base_definition is None:
        return None
    return MieTagDefinition(
        name=f"{base_definition.name}-{language}",
        family_2_group=base_definition.family_2_group,
        evidence_id=base_definition.evidence_id,
    )


def _localized_tag_base(tag_id: str) -> tuple[str, str] | None:
    if len(tag_id) < 7 or tag_id[-6] != "-":
        return None
    language = tag_id[-5:]
    if language[2] != "_":
        return None
    if not language[:2].islower() or not language[3:].isupper():
        return None
    return tag_id[:-6], language


def _split_units(tag_name: str) -> tuple[str, str | None]:
    if not tag_name.endswith(")") or "(" not in tag_name:
        return tag_name, None
    tag_id, units = tag_name.rsplit("(", 1)
    return tag_id, units[:-1]


def _mie_value(data: bytes, format_code: int, endian: MieEndian) -> MieScalarValue | None:
    base_format = format_code & 0xFB
    if base_format == 0x00:
        return None
    if base_format == 0x20:
        return data.decode("latin-1", errors="replace")
    if base_format == 0x28:
        return data.decode("utf-8", errors="replace")
    if base_format == 0x29:
        return data.decode(_utf16_codec(endian), errors="replace")
    if base_format == 0x2A:
        return data.decode(_utf32_codec(endian), errors="replace")
    if base_format == 0x30:
        return list(data.decode("latin-1", errors="replace").split("\0"))
    if base_format == 0x38:
        return list(data.decode("utf-8", errors="replace").split("\0"))
    if base_format == 0x39:
        return list(data.decode(_utf16_codec(endian), errors="replace").split("\0"))
    if base_format == 0x3A:
        return list(data.decode(_utf32_codec(endian), errors="replace").split("\0"))
    if base_format in {0x40, 0x41, 0x42, 0x43}:
        return _integer_values(data, base_format, signed=False, endian=endian)
    if base_format in {0x48, 0x49, 0x4A, 0x4B}:
        return _integer_values(data, base_format, signed=True, endian=endian)
    if base_format in {0x52, 0x53, 0x5A, 0x5B}:
        return _rational_values(data, base_format, endian)
    return None


def _integer_values(
    data: bytes,
    format_code: int,
    *,
    signed: bool,
    endian: MieEndian,
) -> int | str | None:
    width = 1 << (format_code & 0x03)
    if len(data) < width or len(data) % width:
        return None
    values = [
        int.from_bytes(data[offset : offset + width], endian, signed=signed)
        for offset in range(0, len(data), width)
    ]
    if len(values) == 1:
        return values[0]
    return " ".join(str(value) for value in values)


def _rational_values(data: bytes, format_code: int, endian: MieEndian) -> float | str | None:
    signed = format_code in {0x5A, 0x5B}
    component_width = 2 if format_code in {0x52, 0x5A} else 4
    rational_width = component_width * 2
    if len(data) < rational_width or len(data) % rational_width:
        return None
    values: list[float | int] = []
    for offset in range(0, len(data), rational_width):
        numerator = int.from_bytes(data[offset : offset + component_width], endian, signed=signed)
        denominator = int.from_bytes(
            data[offset + component_width : offset + rational_width],
            endian,
            signed=signed,
        )
        if denominator == 0:
            values.append(0)
        else:
            quotient = numerator / denominator
            values.append(int(quotient) if quotient.is_integer() else quotient)
    if len(values) == 1:
        return values[0]
    return " ".join(_number_text(value) for value in values)


def _render_value(
    tag_name: str,
    value: MieScalarValue,
    units: str | None,
) -> MieScalarValue:
    if isinstance(value, (bytes, list)):
        return value
    if (
        isinstance(value, int | float)
        and units is None
        and tag_name
        not in {
            "ImageSize",
            "ThumbnailImageSize",
            "Resolution",
        }
    ):
        return value
    rendered = _number_text(value)
    if tag_name in {"ImageSize", "ThumbnailImageSize", "Resolution"}:
        rendered = rendered.replace(" ", "x")
    if units is not None:
        rendered = f"{rendered}({units})"
    return rendered


def _number_text(value: str | int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _utf16_codec(endian: MieEndian) -> str:
    return "utf-16-le" if endian == "little" else "utf-16-be"


def _utf32_codec(endian: MieEndian) -> str:
    return "utf-32-le" if endian == "little" else "utf-32-be"


def _json_value(value: MieScalarValue) -> JsonValue:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list):
        return [item for item in value]
    return value
