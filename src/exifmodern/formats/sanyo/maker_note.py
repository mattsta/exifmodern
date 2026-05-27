"""Source-grounded Sanyo maker-note scalar adapters."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.makernote.inline_ifd import (
    InlineMakerNoteIfdLocator,
    InlineMakerNoteScalarWritePlan,
    InlineMakerNoteScalarWriteStep,
)
from exifmodern.json_types import JsonObject, JsonValue

type SanyoEvidenceId = str
type SanyoScalar = int | float | str | bytes
type SanyoRawValue = SanyoScalar | tuple[int, ...] | tuple[int, int]
type SanyoRenderedValue = int | float | str | tuple[int, ...]
type SanyoValueFormat = Literal[
    "int16u",
    "int32u",
    "int32s",
    "rational64u",
    "rational64s",
    "string",
    "undef",
]
type SanyoVideoSurface = Literal["mov", "mp4"]
type SanyoVideoRole = Literal[
    "camera_identity",
    "exposure_value",
    "lens_value",
    "white_balance",
    "sensitivity",
    "software_boundary",
    "thumbnail_route",
]

SANYO_FLASH_MODE_TAG = 0x0225
SANYO_INLINE_IFD_LOCATOR = InlineMakerNoteIfdLocator(
    maker_note_header=b"SANYO\x00\x01\x00",
    ifd_offset_from_maker_note=8,
)
SANYO_FLASH_MODE_VALUES = {
    "auto": 0,
    "force": 1,
    "disabled": 2,
    "red eye": 3,
    "redeye": 3,
}
SANYO_FLASH_MODE_SOURCE = "sanyo.flash_mode"
SANYO_WRITE_TEST_SOURCE = "sanyo.write_test_3"
SANYO_OFF_ON_SOURCE = "sanyo.off_on"
SANYO_MAIN_SOURCE = "sanyo.main"
SANYO_MAIN_TEST_SOURCE = "sanyo.main_test_rendering"
SANYO_FACE_SOURCE = "sanyo.face_info"
SANYO_MOV_SOURCE = "sanyo.mov"
SANYO_MP4_SOURCE = "sanyo.mp4"
SANYO_THUMBNAIL_SOURCE = "sanyo.thumbnail"


@dataclass(frozen=True)
class SanyoMakerNoteTagSpec:
    tag_id: int
    tag_name: str
    value_format: SanyoValueFormat
    print_conv: dict[int, str] | None
    evidence_ids: tuple[SanyoEvidenceId, ...]


@dataclass(frozen=True)
class SanyoRenderedTag:
    tag_id: int
    tag_name: str
    raw_value: SanyoRawValue
    value: SanyoRenderedValue
    rendered_value: SanyoRenderedValue
    evidence_ids: tuple[SanyoEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "raw_value": json_value(self.raw_value),
            "rendered_value": json_value(self.rendered_value),
            "tag_id": self.tag_id,
            "tag_name": self.tag_name,
            "value": json_value(self.value),
        }


@dataclass(frozen=True)
class SanyoVideoFieldPlan:
    surface: SanyoVideoSurface
    offset: int
    tag_name: str
    value_format: SanyoValueFormat
    role: SanyoVideoRole
    raw_value: SanyoRawValue
    value: SanyoRenderedValue
    rendered_value: SanyoRenderedValue
    evidence_ids: tuple[SanyoEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "offset": self.offset,
            "raw_value": json_value(self.raw_value),
            "rendered_value": json_value(self.rendered_value),
            "role": self.role,
            "surface": self.surface,
            "tag_name": self.tag_name,
            "value": json_value(self.value),
            "value_format": self.value_format,
        }


@dataclass(frozen=True)
class SanyoVideoMetadataPlan:
    surface: SanyoVideoSurface
    fields: tuple[SanyoVideoFieldPlan, ...]
    thumbnail_routes: tuple[int, ...]
    evidence_ids: tuple[SanyoEvidenceId, ...]

    def field(self, tag_name: str) -> SanyoVideoFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def to_json(self) -> JsonObject:
        return {
            "fields": [field.to_json() for field in self.fields],
            "surface": self.surface,
            "thumbnail_routes": list(self.thumbnail_routes),
        }


OFF_ON_PRINT_CONV = {0: "Off", 1: "On"}
SANYO_QUALITY_PRINT_CONV = {
    0x0000: "Normal/Very Low",
    0x0001: "Normal/Low",
    0x0002: "Normal/Medium Low",
    0x0003: "Normal/Medium",
    0x0004: "Normal/Medium High",
    0x0005: "Normal/High",
    0x0006: "Normal/Very High",
    0x0007: "Normal/Super High",
    0x0100: "Fine/Very Low",
    0x0101: "Fine/Low",
    0x0102: "Fine/Medium Low",
    0x0103: "Fine/Medium",
    0x0104: "Fine/Medium High",
    0x0105: "Fine/High",
    0x0106: "Fine/Very High",
    0x0107: "Fine/Super High",
    0x0200: "Super Fine/Very Low",
    0x0201: "Super Fine/Low",
    0x0202: "Super Fine/Medium Low",
    0x0203: "Super Fine/Medium",
    0x0204: "Super Fine/Medium High",
    0x0205: "Super Fine/High",
    0x0206: "Super Fine/Very High",
    0x0207: "Super Fine/Super High",
}
SANYO_MAIN_TAG_SPECS: dict[int, SanyoMakerNoteTagSpec] = {
    0x00FF: SanyoMakerNoteTagSpec(0x00FF, "MakerNoteOffset", "int32u", None, (SANYO_MAIN_SOURCE,)),
    0x0200: SanyoMakerNoteTagSpec(0x0200, "SpecialMode", "int32u", None, (SANYO_MAIN_SOURCE,)),
    0x0201: SanyoMakerNoteTagSpec(
        0x0201,
        "SanyoQuality",
        "int16u",
        SANYO_QUALITY_PRINT_CONV,
        (SANYO_MAIN_SOURCE,),
    ),
    0x0202: SanyoMakerNoteTagSpec(
        0x0202,
        "Macro",
        "int16u",
        {0: "Normal", 1: "Macro", 2: "View", 3: "Manual"},
        (SANYO_MAIN_SOURCE,),
    ),
    0x0204: SanyoMakerNoteTagSpec(0x0204, "DigitalZoom", "rational64u", None, (SANYO_MAIN_SOURCE,)),
    0x020E: SanyoMakerNoteTagSpec(
        0x020E,
        "SequentialShot",
        "int16u",
        {0: "None", 1: "Standard", 2: "Best", 3: "Adjust Exposure"},
        (SANYO_MAIN_SOURCE,),
    ),
    0x020F: SanyoMakerNoteTagSpec(
        0x020F,
        "WideRange",
        "int16u",
        OFF_ON_PRINT_CONV,
        (SANYO_OFF_ON_SOURCE, SANYO_MAIN_SOURCE),
    ),
    0x0210: SanyoMakerNoteTagSpec(
        0x0210,
        "ColorAdjustmentMode",
        "int16u",
        OFF_ON_PRINT_CONV,
        (SANYO_OFF_ON_SOURCE, SANYO_MAIN_SOURCE),
    ),
    0x0213: SanyoMakerNoteTagSpec(
        0x0213,
        "QuickShot",
        "int16u",
        OFF_ON_PRINT_CONV,
        (SANYO_OFF_ON_SOURCE, SANYO_MAIN_SOURCE),
    ),
    0x0214: SanyoMakerNoteTagSpec(
        0x0214,
        "SelfTimer",
        "int16u",
        OFF_ON_PRINT_CONV,
        (SANYO_OFF_ON_SOURCE, SANYO_MAIN_SOURCE),
    ),
    0x0216: SanyoMakerNoteTagSpec(
        0x0216,
        "VoiceMemo",
        "int16u",
        OFF_ON_PRINT_CONV,
        (SANYO_OFF_ON_SOURCE, SANYO_MAIN_SOURCE),
    ),
    0x0217: SanyoMakerNoteTagSpec(
        0x0217,
        "RecordShutterRelease",
        "int16u",
        {0: "Record while down", 1: "Press start, press stop"},
        (SANYO_MAIN_SOURCE,),
    ),
    0x0218: SanyoMakerNoteTagSpec(
        0x0218,
        "FlickerReduce",
        "int16u",
        OFF_ON_PRINT_CONV,
        (SANYO_OFF_ON_SOURCE, SANYO_MAIN_SOURCE),
    ),
    0x0219: SanyoMakerNoteTagSpec(
        0x0219,
        "OpticalZoomOn",
        "int16u",
        OFF_ON_PRINT_CONV,
        (SANYO_OFF_ON_SOURCE, SANYO_MAIN_SOURCE),
    ),
    0x021B: SanyoMakerNoteTagSpec(
        0x021B,
        "DigitalZoomOn",
        "int16u",
        OFF_ON_PRINT_CONV,
        (SANYO_OFF_ON_SOURCE, SANYO_MAIN_SOURCE),
    ),
    0x021D: SanyoMakerNoteTagSpec(
        0x021D,
        "LightSourceSpecial",
        "int16u",
        OFF_ON_PRINT_CONV,
        (SANYO_OFF_ON_SOURCE, SANYO_MAIN_SOURCE),
    ),
    0x021E: SanyoMakerNoteTagSpec(
        0x021E, "Resaved", "int16u", {0: "No", 1: "Yes"}, (SANYO_MAIN_SOURCE,)
    ),
    0x021F: SanyoMakerNoteTagSpec(
        0x021F,
        "SceneSelect",
        "int16u",
        {
            0: "Off",
            1: "Sport",
            2: "TV",
            3: "Night",
            4: "User 1",
            5: "User 2",
            6: "Lamp",
        },
        (SANYO_MAIN_SOURCE,),
    ),
    0x0223: SanyoMakerNoteTagSpec(
        0x0223,
        "ManualFocusDistance",
        "rational64u",
        None,
        (SANYO_MAIN_SOURCE, SANYO_FACE_SOURCE),
    ),
    0x0224: SanyoMakerNoteTagSpec(
        0x0224,
        "SequenceShotInterval",
        "int16u",
        {0: "5 frames/s", 1: "10 frames/s", 2: "15 frames/s", 3: "20 frames/s"},
        (SANYO_MAIN_SOURCE,),
    ),
    0x0225: SanyoMakerNoteTagSpec(
        0x0225,
        "FlashMode",
        "int16u",
        {0: "Auto", 1: "Force", 2: "Disabled", 3: "Red eye"},
        (SANYO_FLASH_MODE_SOURCE,),
    ),
}


def build_sanyo_flash_mode_write_plan(value: str) -> InlineMakerNoteScalarWritePlan:
    return InlineMakerNoteScalarWritePlan((sanyo_flash_mode_write_step(value),))


def sanyo_flash_mode_write_step(value: str) -> InlineMakerNoteScalarWriteStep:
    return InlineMakerNoteScalarWriteStep(
        domain="Sanyo",
        tag_name="FlashMode",
        tag_id=SANYO_FLASH_MODE_TAG,
        field_type="SHORT",
        raw_value=normalize_sanyo_flash_mode(value),
        locator=SANYO_INLINE_IFD_LOCATOR,
        evidence_ids=(SANYO_FLASH_MODE_SOURCE, SANYO_WRITE_TEST_SOURCE),
    )


def normalize_sanyo_flash_mode(value: str) -> int:
    normalized = " ".join(value.strip().lower().replace("-", " ").split())
    mapped = SANYO_FLASH_MODE_VALUES.get(normalized)
    if mapped is not None:
        return mapped
    if normalized.isdecimal():
        return int(normalized)
    raise ValueError("Sanyo FlashMode must be Auto, Force, Disabled, Red eye, or an integer.")


def sanyo_main_tag_specs() -> tuple[SanyoMakerNoteTagSpec, ...]:
    return tuple(SANYO_MAIN_TAG_SPECS[tag_id] for tag_id in sorted(SANYO_MAIN_TAG_SPECS))


def render_sanyo_main_tag(
    tag_id: int,
    raw_value: SanyoRawValue,
) -> SanyoRenderedTag:
    spec = SANYO_MAIN_TAG_SPECS.get(tag_id)
    if spec is None:
        return SanyoRenderedTag(
            tag_id=tag_id,
            tag_name=f"Sanyo_0x{tag_id:04x}",
            raw_value=raw_value,
            value=render_default_value(raw_value),
            rendered_value=render_default_value(raw_value),
            evidence_ids=(SANYO_MAIN_SOURCE,),
        )
    value = convert_main_value(spec, raw_value)
    rendered = render_print_conv(spec, value)
    return SanyoRenderedTag(
        tag_id=tag_id,
        tag_name=spec.tag_name,
        raw_value=raw_value,
        value=value,
        rendered_value=rendered,
        evidence_ids=unique_evidence_ids((*spec.evidence_ids, SANYO_MAIN_TEST_SOURCE)),
    )


def build_sanyo_mov_metadata_plan(data: bytes) -> SanyoVideoMetadataPlan:
    fields = tuple(
        field
        for field in (
            read_video_string("mov", data, 0x00, "Make", 24, "camera_identity", SANYO_MOV_SOURCE),
            read_video_string("mov", data, 0x18, "Model", 8, "camera_identity", SANYO_MOV_SOURCE),
            read_mov_exposure_time(data),
            read_video_scaled_int32(
                "mov",
                data,
                0x2A,
                "FNumber",
                signed=False,
                scale=10,
                role="lens_value",
                render_kind="fnumber",
                source=SANYO_MOV_SOURCE,
            ),
            read_video_scaled_int32(
                "mov",
                data,
                0x32,
                "ExposureCompensation",
                signed=True,
                scale=10,
                role="exposure_value",
                render_kind="signed_decimal",
                source=SANYO_MOV_SOURCE,
            ),
            read_video_u16_map(
                "mov",
                data,
                0x44,
                "WhiteBalance",
                "white_balance",
                {
                    0: "Auto",
                    1: "Daylight",
                    2: "Shade",
                    3: "Fluorescent",
                    4: "Tungsten",
                    5: "Manual",
                },
                SANYO_MOV_SOURCE,
            ),
            read_video_scaled_int32(
                "mov",
                data,
                0x48,
                "FocalLength",
                signed=False,
                scale=10,
                role="lens_value",
                render_kind="millimeters",
                source=SANYO_MOV_SOURCE,
            ),
        )
        if field is not None
    )
    return SanyoVideoMetadataPlan(
        surface="mov",
        fields=fields,
        thumbnail_routes=(),
        evidence_ids=unique_evidence_ids(
            source for field in fields for source in field.evidence_ids
        ),
    )


def build_sanyo_mp4_metadata_plan(data: bytes) -> SanyoVideoMetadataPlan:
    software_d1 = read_mp4_software(data, 0xD1)
    software_d2 = read_mp4_software(data, 0xD2)
    thumbnail_routes: list[int] = []
    if software_d1 is not None:
        thumbnail_routes.append(0xF1)
    if software_d2 is not None:
        thumbnail_routes.append(0xF2)
    fields = tuple(
        field
        for field in (
            read_mp4_make(data),
            read_video_string("mp4", data, 0x18, "Model", 8, "camera_identity", SANYO_MP4_SOURCE),
            read_mp4_rational(data, 0x32, "FNumber", "rational64u", "lens_value", "fnumber"),
            read_mp4_rational(
                data,
                0x3A,
                "ExposureCompensation",
                "rational64s",
                "exposure_value",
                "signed_decimal_zero",
            ),
            read_mp4_iso(data),
            software_d1,
            software_d2,
        )
        if field is not None
    )
    sources = unique_evidence_ids(
        (
            *(source for field in fields for source in field.evidence_ids),
            *(SANYO_THUMBNAIL_SOURCE for _route in thumbnail_routes),
        )
    )
    return SanyoVideoMetadataPlan(
        surface="mp4",
        fields=fields,
        thumbnail_routes=tuple(thumbnail_routes),
        evidence_ids=sources,
    )


def convert_main_value(
    spec: SanyoMakerNoteTagSpec,
    raw_value: SanyoRawValue,
) -> SanyoRenderedValue:
    if spec.value_format in ("rational64u", "rational64s"):
        return rational_to_float(raw_value)
    return render_default_value(raw_value)


def render_print_conv(
    spec: SanyoMakerNoteTagSpec,
    value: SanyoRenderedValue,
) -> SanyoRenderedValue:
    if spec.print_conv is not None and isinstance(value, int):
        return spec.print_conv.get(value, value)
    return value


def render_default_value(value: SanyoRawValue) -> SanyoRenderedValue:
    if isinstance(value, bytes):
        return value.rstrip(b"\x00").decode("latin-1")
    if isinstance(value, tuple) and len(value) == 2:
        return rational_to_float(value)
    if isinstance(value, tuple):
        return " ".join(str(item) for item in value)
    return value


def rational_to_float(value: SanyoRawValue) -> SanyoRenderedValue:
    if not isinstance(value, tuple) or len(value) != 2:
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            return value
        return tuple(value) if isinstance(value, tuple) else 0
    numerator, denominator = value
    if denominator == 0:
        return 0
    converted = numerator / denominator
    return int(converted) if converted.is_integer() else converted


def read_video_string(
    surface: SanyoVideoSurface,
    data: bytes,
    offset: int,
    tag_name: str,
    length: int,
    role: SanyoVideoRole,
    source: SanyoEvidenceId,
) -> SanyoVideoFieldPlan | None:
    if offset + length > len(data):
        return None
    raw = data[offset : offset + length]
    value = raw.rstrip(b"\x00 ").decode("latin-1")
    return SanyoVideoFieldPlan(
        surface,
        offset,
        tag_name,
        "string",
        role,
        raw,
        value,
        value,
        (source,),
    )


def read_mov_exposure_time(data: bytes) -> SanyoVideoFieldPlan | None:
    if len(data) < 0x26 + 4:
        return None
    raw = int.from_bytes(data[0x26:0x2A], "little")
    value = 10 / raw if raw else 0
    rendered = print_exposure_time(value)
    return SanyoVideoFieldPlan(
        "mov",
        0x26,
        "ExposureTime",
        "int32u",
        "exposure_value",
        raw,
        value,
        rendered,
        (SANYO_MOV_SOURCE,),
    )


def read_video_scaled_int32(
    surface: SanyoVideoSurface,
    data: bytes,
    offset: int,
    tag_name: str,
    *,
    signed: bool,
    scale: int,
    role: SanyoVideoRole,
    render_kind: str,
    source: SanyoEvidenceId,
) -> SanyoVideoFieldPlan | None:
    if offset + 4 > len(data):
        return None
    raw = int.from_bytes(data[offset : offset + 4], "little", signed=signed)
    value = raw / scale
    rendered = render_numeric_value(value, render_kind)
    return SanyoVideoFieldPlan(
        surface,
        offset,
        tag_name,
        "int32s" if signed else "int32u",
        role,
        raw,
        value,
        rendered,
        (source,),
    )


def read_video_u16_map(
    surface: SanyoVideoSurface,
    data: bytes,
    offset: int,
    tag_name: str,
    role: SanyoVideoRole,
    print_conv: dict[int, str],
    source: SanyoEvidenceId,
) -> SanyoVideoFieldPlan | None:
    if offset + 2 > len(data):
        return None
    raw = int.from_bytes(data[offset : offset + 2], "little")
    rendered: SanyoRenderedValue = print_conv.get(raw, raw)
    return SanyoVideoFieldPlan(
        surface, offset, tag_name, "int16u", role, raw, raw, rendered, (source,)
    )


def read_mp4_make(data: bytes) -> SanyoVideoFieldPlan | None:
    field = read_video_string("mp4", data, 0x00, "Make", 5, "camera_identity", SANYO_MP4_SOURCE)
    if field is None or not isinstance(field.value, str):
        return field
    rendered = field.value.lower().capitalize()
    return SanyoVideoFieldPlan(
        field.surface,
        field.offset,
        field.tag_name,
        field.value_format,
        field.role,
        field.raw_value,
        field.value,
        rendered,
        field.evidence_ids,
    )


def read_mp4_rational(
    data: bytes,
    offset: int,
    tag_name: str,
    value_format: Literal["rational64u", "rational64s"],
    role: SanyoVideoRole,
    render_kind: str,
) -> SanyoVideoFieldPlan | None:
    if offset + 8 > len(data):
        return None
    signed = value_format == "rational64s"
    numerator = int.from_bytes(data[offset : offset + 4], "little", signed=signed)
    denominator = int.from_bytes(data[offset + 4 : offset + 8], "little", signed=signed)
    raw = (numerator, denominator)
    value = rational_to_float(raw)
    rendered = render_numeric_value(value, render_kind)
    return SanyoVideoFieldPlan(
        "mp4", offset, tag_name, value_format, role, raw, value, rendered, (SANYO_MP4_SOURCE,)
    )


def read_mp4_iso(data: bytes) -> SanyoVideoFieldPlan | None:
    if len(data) < 0x6A + 4:
        return None
    raw = int.from_bytes(data[0x6A:0x6E], "little")
    return SanyoVideoFieldPlan(
        "mp4", 0x6A, "ISO", "int32u", "sensitivity", raw, raw, raw, (SANYO_MP4_SOURCE,)
    )


def read_mp4_software(data: bytes, offset: int) -> SanyoVideoFieldPlan | None:
    if offset + 32 > len(data):
        return None
    raw = data[offset : offset + 32]
    if not raw.startswith(b"SANYO"):
        return None
    value = raw.replace(b"\x00", b"").decode("latin-1")
    return SanyoVideoFieldPlan(
        "mp4",
        offset,
        "Software",
        "undef",
        "software_boundary",
        raw,
        value,
        value,
        (SANYO_MP4_SOURCE, SANYO_THUMBNAIL_SOURCE),
    )


def render_numeric_value(
    value: SanyoRenderedValue,
    render_kind: str,
) -> SanyoRenderedValue:
    if not isinstance(value, (int, float)):
        return value
    if render_kind == "fnumber":
        return f"{value:.1f}"
    if render_kind == "millimeters":
        return f"{value:.1f} mm"
    if render_kind == "signed_decimal":
        return f"{value:+.1f}" if value else 0
    if render_kind == "signed_decimal_zero":
        return f"{value:+.1f}" if value else 0
    return value


def print_exposure_time(value: int | float) -> str | int:
    if value == 0:
        return 0
    if value < 1:
        denominator = round(1 / value)
        return f"1/{denominator}"
    return f"{value:g}"


def unique_evidence_ids(references: Iterable[SanyoEvidenceId]) -> tuple[SanyoEvidenceId, ...]:
    unique: list[SanyoEvidenceId] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def json_value(value: SanyoRawValue | SanyoRenderedValue) -> JsonValue:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, tuple):
        return list(value)
    return value
