"""Bounded FLIR FPF public-header scalar reader."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.flir.file_family_plan import (
    FPF_HEADER_SIZE,
    build_flir_file_family_plan,
)
from exifmodern.formats.flir.fpf_value_plan import build_flir_fpf_value_plan

type FlirFpfFieldFormat = Literal[
    "uint16",
    "uint32",
    "float",
    "float1",
    "float2",
    "kelvin",
    "distance",
    "humidity",
    "string32",
    "datetime",
    "image_type",
    "pixel_format",
]
type FlirFpfReadValue = str | int | float


@dataclass(frozen=True)
class FlirFpfReadTag:
    name: str
    value: FlirFpfReadValue
    group2: str
    tag_id: str


@dataclass(frozen=True)
class FlirFpfFieldDefinition:
    offset: int
    name: str
    field_format: FlirFpfFieldFormat
    group2: str


FPF_FIELD_DEFINITIONS: tuple[FlirFpfFieldDefinition, ...] = (
    FlirFpfFieldDefinition(0x20, "FPFVersion", "uint32", "Image"),
    FlirFpfFieldDefinition(0x24, "ImageDataOffset", "uint32", "Image"),
    FlirFpfFieldDefinition(0x28, "ImageType", "image_type", "Image"),
    FlirFpfFieldDefinition(0x2A, "ImagePixelFormat", "pixel_format", "Image"),
    FlirFpfFieldDefinition(0x2C, "ImageWidth", "uint16", "Image"),
    FlirFpfFieldDefinition(0x2E, "ImageHeight", "uint16", "Image"),
    FlirFpfFieldDefinition(0x30, "ExternalTriggerCount", "uint32", "Image"),
    FlirFpfFieldDefinition(0x34, "SequenceFrameNumber", "uint32", "Image"),
    FlirFpfFieldDefinition(0x78, "CameraModel", "string32", "Camera"),
    FlirFpfFieldDefinition(0x98, "CameraPartNumber", "string32", "Camera"),
    FlirFpfFieldDefinition(0xB8, "CameraSerialNumber", "string32", "Camera"),
    FlirFpfFieldDefinition(0xD8, "CameraTemperatureRangeMin", "kelvin", "Camera"),
    FlirFpfFieldDefinition(0xDC, "CameraTemperatureRangeMax", "kelvin", "Camera"),
    FlirFpfFieldDefinition(0xE0, "LensModel", "string32", "Camera"),
    FlirFpfFieldDefinition(0x100, "LensPartNumber", "string32", "Camera"),
    FlirFpfFieldDefinition(0x120, "LensSerialNumber", "string32", "Camera"),
    FlirFpfFieldDefinition(0x140, "FilterModel", "string32", "Camera"),
    FlirFpfFieldDefinition(0x150, "FilterPartNumber", "string32", "Camera"),
    FlirFpfFieldDefinition(0x180, "FilterSerialNumber", "string32", "Camera"),
    FlirFpfFieldDefinition(0x1E0, "Emissivity", "float2", "Image"),
    FlirFpfFieldDefinition(0x1E4, "ObjectDistance", "distance", "Image"),
    FlirFpfFieldDefinition(0x1E8, "ReflectedApparentTemperature", "kelvin", "Image"),
    FlirFpfFieldDefinition(0x1EC, "AtmosphericTemperature", "kelvin", "Image"),
    FlirFpfFieldDefinition(0x1F0, "RelativeHumidity", "humidity", "Image"),
    FlirFpfFieldDefinition(0x1F4, "ComputedAtmosphericTrans", "float2", "Image"),
    FlirFpfFieldDefinition(0x1F8, "EstimatedAtmosphericTrans", "float2", "Image"),
    FlirFpfFieldDefinition(0x1FC, "ReferenceTemperature", "kelvin", "Image"),
    FlirFpfFieldDefinition(0x200, "IRWindowTemperature", "kelvin", "Camera"),
    FlirFpfFieldDefinition(0x204, "IRWindowTransmission", "float2", "Camera"),
    FlirFpfFieldDefinition(0x248, "DateTimeOriginal", "datetime", "Time"),
    FlirFpfFieldDefinition(0x2A4, "CameraScaleMin", "float1", "Image"),
    FlirFpfFieldDefinition(0x2A8, "CameraScaleMax", "float1", "Image"),
    FlirFpfFieldDefinition(0x2AC, "CalculatedScaleMin", "float1", "Image"),
    FlirFpfFieldDefinition(0x2B0, "CalculatedScaleMax", "float1", "Image"),
    FlirFpfFieldDefinition(0x2B4, "ActualScaleMin", "float1", "Image"),
    FlirFpfFieldDefinition(0x2B8, "ActualScaleMax", "float1", "Image"),
)


def read_flir_fpf_tags(data: bytes) -> tuple[FlirFpfReadTag, ...]:
    """Read only the source-defined FPF header; image data is never loaded."""

    plan = build_flir_file_family_plan(data[:FPF_HEADER_SIZE])
    if plan.family != "fpf" or plan.fpf_header is None:
        return ()
    byte_order = plan.fpf_header.byte_order
    if byte_order not in {"little", "big"}:
        return ()
    byte_order_name: Literal["little", "big"] = "little" if byte_order == "little" else "big"
    tags: list[FlirFpfReadTag] = []
    for definition in FPF_FIELD_DEFINITIONS:
        value = _read_field(data, definition, byte_order_name)
        if value is None:
            continue
        tags.append(
            FlirFpfReadTag(
                name=definition.name,
                value=value,
                group2=definition.group2,
                tag_id=str(definition.offset),
            )
        )
    return tuple(tags)


def _read_field(
    data: bytes,
    definition: FlirFpfFieldDefinition,
    byte_order: Literal["little", "big"],
) -> FlirFpfReadValue | None:
    if definition.field_format == "uint16":
        return _read_uint(data, definition.offset, 2, byte_order)
    if definition.field_format == "uint32":
        return _read_uint(data, definition.offset, 4, byte_order)
    if definition.field_format == "image_type":
        value = _read_uint(data, definition.offset, 2, byte_order)
        if value is None:
            return None
        display = build_flir_fpf_value_plan("image_type", value).display_name
        return display if display is not None else value
    if definition.field_format == "pixel_format":
        value = _read_uint(data, definition.offset, 2, byte_order)
        if value is None:
            return None
        display = build_flir_fpf_value_plan("pixel_format", value).display_name
        return display if display is not None else value
    if definition.field_format == "string32":
        if len(data) < definition.offset + 32:
            return None
        text = (
            data[definition.offset : definition.offset + 32]
            .split(b"\0", 1)[0]
            .decode(
                "latin-1",
                errors="replace",
            )
        )
        if definition.name == "CameraSerialNumber" and text.isdecimal():
            return int(text)
        return text
    if definition.field_format == "datetime":
        maybe_values = tuple(
            _read_uint(data, definition.offset + index * 4, 4, byte_order) for index in range(7)
        )
        if any(value is None for value in maybe_values):
            return None
        values = tuple(value for value in maybe_values if value is not None)
        if len(values) != 7:
            return None
        year, month, day, hour, minute, second, millisecond = values
        return (
            f"{year:04d}:{month:02d}:{day:02d} "
            f"{hour:02d}:{minute:02d}:{second:02d}.{millisecond:03d}"
        )
    float_value = _read_float(data, definition.offset, byte_order)
    if float_value is None:
        return None
    if definition.field_format == "float":
        return float_value
    if definition.field_format == "float1":
        return f"{float_value:.1f}"
    if definition.field_format == "float2":
        return f"{float_value:.2f}"
    if definition.field_format == "kelvin":
        return f"{float_value - 273.15:.1f} C"
    if definition.field_format == "distance":
        return f"{float_value:.2f} m"
    if definition.field_format == "humidity":
        return f"{float_value * 100:.1f} %"
    return None


def _read_uint(
    data: bytes,
    offset: int,
    size: Literal[2, 4],
    byte_order: Literal["little", "big"],
) -> int | None:
    if len(data) < offset + size:
        return None
    return int.from_bytes(data[offset : offset + size], byte_order)


def _read_float(data: bytes, offset: int, byte_order: Literal["little", "big"]) -> float | None:
    if len(data) < offset + 4:
        return None
    prefix = "<" if byte_order == "little" else ">"
    return float(struct.unpack(prefix + "f", data[offset : offset + 4])[0])
