"""Photoshop ResolutionInfo resource rewrite primitives.

Photoshop ``ResolutionInfo`` is binary data with big-endian integer fields.
The X/Y resolution fields are writable ``int32u`` values stored as 16.16 fixed
point numbers, using ``int($val * 0x10000 + 0.5)`` when writing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from exifmodern.formats.photoshop.image_resources import (
    PHOTOSHOP_WRITABLE_IRB_SIGNATURE,
    PhotoshopImageResourceBlock,
)
from exifmodern.formats.photoshop.nested_metadata_plan import (
    PHOTOSHOP_RESOURCE_ID_RESOLUTION_INFO,
)
from exifmodern.formats.photoshop.resource_writer import (
    PhotoshopImageResourceMutation,
    PhotoshopPSDUnsupportedWriteError,
)
from exifmodern.formats.photoshop.section_boundary_plan import (
    plan_photoshop_psd_section_boundaries,
    rewrite_synthetic_photoshop_psd_image_resources,
)
from exifmodern.formats.photoshop.write_plan import (
    PHOTOSHOP_RESOLUTION_SOURCE_ID,
    WRITE_PHOTOSHOP_SOURCE_ID,
)

type PhotoshopResolutionWriteValue = str | int | Decimal
type PhotoshopResolutionFieldName = Literal["XResolution", "YResolution"]
type PhotoshopResolutionInfoBlockerCode = Literal[
    "not_source_backed",
    "resolution_info_payload_too_short",
    "resolution_value_not_numeric",
    "resolution_value_out_of_uint32_range",
    "missing_resolution_info_resource",
    "duplicate_resolution_info_resource",
    "non_8bim_resolution_info_resource",
]

FIXED_POINT_SCALE = 0x10000
UINT32_MAX = 0xFFFFFFFF
RESOLUTION_INFO_MINIMUM_LENGTH = 14
X_RESOLUTION_OFFSET = 0
DISPLAYED_UNITS_X_OFFSET = 4
Y_RESOLUTION_OFFSET = 8
DISPLAYED_UNITS_Y_OFFSET = 12

PHOTOSHOP_RESOLUTION_WRITE_BINARY_SOURCE_ID = "photoshop.resolution_info.write_binary_data"


@dataclass(frozen=True)
class PhotoshopResolutionInfo:
    x_resolution_raw: int
    displayed_units_x: int
    y_resolution_raw: int
    displayed_units_y: int
    payload_suffix: bytes

    @property
    def x_resolution(self) -> Decimal:
        return fixed_point_to_decimal(self.x_resolution_raw)

    @property
    def y_resolution(self) -> Decimal:
        return fixed_point_to_decimal(self.y_resolution_raw)


@dataclass(frozen=True)
class PhotoshopResolutionInfoRewriteStep:
    field_name: PhotoshopResolutionFieldName
    source_raw_value: int
    output_raw_value: int
    source_value: Decimal
    output_value: Decimal
    changed: bool


@dataclass(frozen=True)
class PhotoshopResolutionInfoRewritePlan:
    source_length: int
    output_length: int
    source_backed: bool
    can_write_bytes: bool
    blocker_codes: tuple[PhotoshopResolutionInfoBlockerCode, ...]
    source_info: PhotoshopResolutionInfo | None
    output_data: bytes | None
    steps: tuple[PhotoshopResolutionInfoRewriteStep, ...]
    source_reference_ids: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return any(step.changed for step in self.steps)


def parse_resolution_info_payload(payload: bytes) -> PhotoshopResolutionInfo:
    if len(payload) < RESOLUTION_INFO_MINIMUM_LENGTH:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop ResolutionInfo payload is too short for binary fields."
        )
    return PhotoshopResolutionInfo(
        x_resolution_raw=read_u32(payload, X_RESOLUTION_OFFSET),
        displayed_units_x=read_u16(payload, DISPLAYED_UNITS_X_OFFSET),
        y_resolution_raw=read_u32(payload, Y_RESOLUTION_OFFSET),
        displayed_units_y=read_u16(payload, DISPLAYED_UNITS_Y_OFFSET),
        payload_suffix=payload[RESOLUTION_INFO_MINIMUM_LENGTH:],
    )


def plan_resolution_info_rewrite(
    payload: bytes,
    *,
    x_resolution: PhotoshopResolutionWriteValue | None = None,
    y_resolution: PhotoshopResolutionWriteValue | None = None,
    source_backed: bool = True,
) -> PhotoshopResolutionInfoRewritePlan:
    blockers: list[PhotoshopResolutionInfoBlockerCode] = []
    if not source_backed:
        blockers.append("not_source_backed")
    if len(payload) < RESOLUTION_INFO_MINIMUM_LENGTH:
        blockers.append("resolution_info_payload_too_short")

    parsed_x = parse_fixed_point_write_value(x_resolution)
    parsed_y = parse_fixed_point_write_value(y_resolution)
    if parsed_x.blocker_code is not None:
        blockers.append(parsed_x.blocker_code)
    if parsed_y.blocker_code is not None:
        blockers.append(parsed_y.blocker_code)

    if blockers:
        return PhotoshopResolutionInfoRewritePlan(
            source_length=len(payload),
            output_length=len(payload),
            source_backed=source_backed,
            can_write_bytes=False,
            blocker_codes=tuple(dict.fromkeys(blockers)),
            source_info=None,
            output_data=None,
            steps=(),
            source_reference_ids=resolution_info_source_reference_ids(),
        )

    source_info = parse_resolution_info_payload(payload)
    output_x_raw = (
        source_info.x_resolution_raw if parsed_x.raw_value is None else parsed_x.raw_value
    )
    output_y_raw = (
        source_info.y_resolution_raw if parsed_y.raw_value is None else parsed_y.raw_value
    )
    output = bytearray(payload)
    output[X_RESOLUTION_OFFSET : X_RESOLUTION_OFFSET + 4] = output_x_raw.to_bytes(4, "big")
    output[Y_RESOLUTION_OFFSET : Y_RESOLUTION_OFFSET + 4] = output_y_raw.to_bytes(4, "big")

    steps = (
        resolution_rewrite_step(
            field_name="XResolution",
            source_raw_value=source_info.x_resolution_raw,
            output_raw_value=output_x_raw,
        ),
        resolution_rewrite_step(
            field_name="YResolution",
            source_raw_value=source_info.y_resolution_raw,
            output_raw_value=output_y_raw,
        ),
    )
    return PhotoshopResolutionInfoRewritePlan(
        source_length=len(payload),
        output_length=len(output),
        source_backed=source_backed,
        can_write_bytes=True,
        blocker_codes=(),
        source_info=source_info,
        output_data=bytes(output),
        steps=steps,
        source_reference_ids=resolution_info_source_reference_ids(),
    )


def resolution_info_mutation(
    payload: bytes,
    *,
    x_resolution: PhotoshopResolutionWriteValue | None = None,
    y_resolution: PhotoshopResolutionWriteValue | None = None,
    resource_name: bytes | None = None,
    source_backed: bool = True,
) -> PhotoshopImageResourceMutation:
    plan = plan_resolution_info_rewrite(
        payload,
        x_resolution=x_resolution,
        y_resolution=y_resolution,
        source_backed=source_backed,
    )
    if not plan.can_write_bytes or plan.output_data is None:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop ResolutionInfo rewrite is blocked: " + ", ".join(plan.blocker_codes)
        )
    return PhotoshopImageResourceMutation(
        "replace",
        PHOTOSHOP_RESOURCE_ID_RESOLUTION_INFO,
        plan.output_data,
        resource_name,
    )


def rewrite_synthetic_photoshop_psd_resolution_info(
    psd_data: bytes,
    *,
    x_resolution: PhotoshopResolutionWriteValue | None = None,
    y_resolution: PhotoshopResolutionWriteValue | None = None,
    source_backed: bool = True,
) -> bytes:
    section_plan = plan_photoshop_psd_section_boundaries(
        psd_data,
        source_backed=source_backed,
        synthetic_psd=True,
    )
    matching_blocks = tuple(
        block
        for block in section_plan.image_resource_blocks
        if block.resource_id == PHOTOSHOP_RESOURCE_ID_RESOLUTION_INFO
    )
    blocker_codes = resolution_resource_blockers(matching_blocks, source_backed=source_backed)
    if blocker_codes:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop synthetic PSD ResolutionInfo rewrite is blocked: " + ", ".join(blocker_codes)
        )

    block = matching_blocks[0]
    mutation = resolution_info_mutation(
        block.data,
        x_resolution=x_resolution,
        y_resolution=y_resolution,
        resource_name=block.name,
        source_backed=source_backed,
    )
    return rewrite_synthetic_photoshop_psd_image_resources(
        psd_data,
        (mutation,),
        source_backed=source_backed,
    )


@dataclass(frozen=True)
class ParsedFixedPointWriteValue:
    raw_value: int | None
    blocker_code: PhotoshopResolutionInfoBlockerCode | None


def parse_fixed_point_write_value(
    value: PhotoshopResolutionWriteValue | None,
) -> ParsedFixedPointWriteValue:
    if value is None:
        return ParsedFixedPointWriteValue(raw_value=None, blocker_code=None)
    try:
        decimal_value = Decimal(value)
    except InvalidOperation, ValueError:
        return ParsedFixedPointWriteValue(
            raw_value=None,
            blocker_code="resolution_value_not_numeric",
        )
    raw_value = int(decimal_value * FIXED_POINT_SCALE + Decimal("0.5"))
    if raw_value < 0 or raw_value > UINT32_MAX:
        return ParsedFixedPointWriteValue(
            raw_value=None,
            blocker_code="resolution_value_out_of_uint32_range",
        )
    return ParsedFixedPointWriteValue(raw_value=raw_value, blocker_code=None)


def resolution_resource_blockers(
    matching_blocks: tuple[PhotoshopImageResourceBlock, ...],
    *,
    source_backed: bool,
) -> tuple[PhotoshopResolutionInfoBlockerCode, ...]:
    blockers: list[PhotoshopResolutionInfoBlockerCode] = []
    if not source_backed:
        blockers.append("not_source_backed")
    if not matching_blocks:
        blockers.append("missing_resolution_info_resource")
    if len(matching_blocks) > 1:
        blockers.append("duplicate_resolution_info_resource")
    if any(block.signature != PHOTOSHOP_WRITABLE_IRB_SIGNATURE for block in matching_blocks):
        blockers.append("non_8bim_resolution_info_resource")
    return tuple(dict.fromkeys(blockers))


def resolution_rewrite_step(
    *,
    field_name: PhotoshopResolutionFieldName,
    source_raw_value: int,
    output_raw_value: int,
) -> PhotoshopResolutionInfoRewriteStep:
    return PhotoshopResolutionInfoRewriteStep(
        field_name=field_name,
        source_raw_value=source_raw_value,
        output_raw_value=output_raw_value,
        source_value=fixed_point_to_decimal(source_raw_value),
        output_value=fixed_point_to_decimal(output_raw_value),
        changed=source_raw_value != output_raw_value,
    )


def fixed_point_to_decimal(raw_value: int) -> Decimal:
    return Decimal(raw_value) / Decimal(FIXED_POINT_SCALE)


def read_u32(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset : offset + 4], "big")


def read_u16(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset : offset + 2], "big")


def resolution_info_source_reference_ids() -> tuple[str, ...]:
    return (
        PHOTOSHOP_RESOLUTION_SOURCE_ID,
        PHOTOSHOP_RESOLUTION_WRITE_BINARY_SOURCE_ID,
        WRITE_PHOTOSHOP_SOURCE_ID,
    )
