"""Source-backed EXIF lens Composite derivations.

The formulas mirror Image::ExifTool::Exif Composite definitions for
ScaleFactor35efl, CircleOfConfusion, FOV, FocalLength35efl,
HyperfocalDistance, and DOF.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from exifmodern.formats.jpeg.container import read_exif_app1
from exifmodern.formats.tiff.primitives import (
    Endian,
    Ifd,
    find_entry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)

type LensCompositeTagMap = dict[str, str]

EXIF_LENS_COMPOSITE_SOURCE = (
    "../exiftool/lib/Image/ExifTool/Exif.pm:4804-4946 "
    "FocalLength35efl/ScaleFactor35efl/CircleOfConfusion/HyperfocalDistance/DOF/FOV"
)
EXIF_SCALE_FACTOR_SOURCE = "../exiftool/lib/Image/ExifTool/Exif.pm:5451-5524 CalcScaleFactor35efl"


@dataclass(frozen=True)
class ExifLensCompositeInputs:
    focal_length_mm: float
    aperture: float
    focal_length_35mm: float | None
    subject_distance_m: float | None
    focal_plane_resolution_unit: int | str | None
    focal_plane_x_resolution: float | None
    focal_plane_y_resolution: float | None
    exif_image_width: float | None
    exif_image_height: float | None


def exif_lens_composite_overrides(path: Path) -> LensCompositeTagMap:
    """Return raw-value EXIF lens composite values for tags already in the graph."""
    inputs = _read_exif_lens_inputs(path)
    if inputs is None:
        return {}
    scale_factor = _calc_scale_factor_35efl(inputs)
    if scale_factor is None:
        return {"FocalLength35efl": f"{inputs.focal_length_mm:.1f} mm"}
    circle_of_confusion = math.hypot(36, 24) / (scale_factor * 1440)
    focal_length_35mm = inputs.focal_length_mm * scale_factor
    values: LensCompositeTagMap = {
        "ScaleFactor35efl": f"{scale_factor:.1f}",
        "CircleOfConfusion": f"{circle_of_confusion:.3f} mm",
        "FOV": _print_fov(inputs.focal_length_mm, scale_factor, inputs.subject_distance_m),
        "FocalLength35efl": (
            f"{inputs.focal_length_mm:.1f} mm (35 mm equivalent: {focal_length_35mm:.1f} mm)"
        ),
        "HyperfocalDistance": _print_hyperfocal_distance(
            inputs.focal_length_mm,
            inputs.aperture,
            circle_of_confusion,
        ),
    }
    dof = _print_dof(inputs, circle_of_confusion)
    if dof is not None:
        values["DOF"] = dof
    return values


def _read_exif_lens_inputs(path: Path) -> ExifLensCompositeInputs | None:
    try:
        app1 = read_exif_app1(path)
        header = parse_tiff_header(app1.tiff_data)
        ifd0 = parse_ifd(app1.tiff_data, header.first_ifd_offset, header.endian)
        exif_pointer = _raw_entry_float(app1.tiff_data, ifd0, header.endian, 0x8769)
        if exif_pointer is None:
            return None
        exif_ifd = parse_ifd(app1.tiff_data, int(exif_pointer), header.endian)
        focal_length = _raw_entry_float(app1.tiff_data, exif_ifd, header.endian, 0x920A)
        f_number = _raw_entry_float(app1.tiff_data, exif_ifd, header.endian, 0x829D)
        aperture_value = _raw_entry_float(app1.tiff_data, exif_ifd, header.endian, 0x9202)
        focal_length_35mm = _raw_entry_float(app1.tiff_data, exif_ifd, header.endian, 0xA405)
        subject_distance = _raw_entry_float(app1.tiff_data, exif_ifd, header.endian, 0x9206)
    except ValueError:
        return None
    aperture = f_number if f_number is not None else None
    if aperture is None and aperture_value is not None:
        aperture = math.pow(2, aperture_value / 2)
    if focal_length is None or aperture is None:
        return None
    focal_plane_resolution_unit = _raw_entry_scalar(
        app1.tiff_data,
        exif_ifd,
        header.endian,
        0xA210,
    )
    focal_plane_x_resolution = _raw_entry_float(app1.tiff_data, exif_ifd, header.endian, 0xA20E)
    focal_plane_y_resolution = _raw_entry_float(app1.tiff_data, exif_ifd, header.endian, 0xA20F)
    exif_image_width = _raw_entry_float(app1.tiff_data, exif_ifd, header.endian, 0xA002)
    exif_image_height = _raw_entry_float(app1.tiff_data, exif_ifd, header.endian, 0xA003)
    return ExifLensCompositeInputs(
        focal_length_mm=focal_length,
        aperture=aperture,
        focal_length_35mm=focal_length_35mm,
        subject_distance_m=subject_distance,
        focal_plane_resolution_unit=focal_plane_resolution_unit,
        focal_plane_x_resolution=focal_plane_x_resolution,
        focal_plane_y_resolution=focal_plane_y_resolution,
        exif_image_width=exif_image_width,
        exif_image_height=exif_image_height,
    )


def _raw_entry_float(data: bytes, ifd: Ifd, endian: Endian, tag_id: int) -> float | None:
    entry = find_entry(ifd, tag_id)
    if entry is None:
        return None
    value = read_entry_value(data, entry, endian)
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, int):
        return float(value)
    return None


def _raw_entry_scalar(data: bytes, ifd: Ifd, endian: Endian, tag_id: int) -> int | str | None:
    entry = find_entry(ifd, tag_id)
    if entry is None:
        return None
    value = read_entry_value(data, entry, endian)
    if isinstance(value, int | str):
        return value
    return None


def _calc_scale_factor_35efl(inputs: ExifLensCompositeInputs) -> float | None:
    if inputs.focal_length_mm and inputs.focal_length_35mm:
        return inputs.focal_length_35mm / inputs.focal_length_mm
    units_by_raw_value: dict[int | str, float] = {
        3: 10,
        4: 1,
        5: 0.001,
        "cm": 10,
        "mm": 1,
        "um": 0.001,
    }
    units = units_by_raw_value.get(inputs.focal_plane_resolution_unit or "", 25.4)
    x_resolution = inputs.focal_plane_x_resolution
    y_resolution = inputs.focal_plane_y_resolution or x_resolution
    width = inputs.exif_image_width
    height = inputs.exif_image_height
    if (
        not x_resolution
        or not y_resolution
        or not width
        or not height
        or x_resolution == 0
        or y_resolution == 0
    ):
        return None
    aspect = width / height
    if aspect <= 0.5 or aspect >= 2:
        return None
    focal_plane_width = width * units / x_resolution
    focal_plane_height = height * units / y_resolution
    diagonal = math.hypot(focal_plane_width, focal_plane_height)
    if diagonal <= 1 or diagonal >= 100:
        return None
    return math.hypot(36, 24) / diagonal


def _print_hyperfocal_distance(
    focal_length_mm: float,
    aperture: float,
    circle_of_confusion: float,
) -> str:
    if not aperture or not circle_of_confusion:
        return "inf"
    hyperfocal_m = focal_length_mm * focal_length_mm / (aperture * circle_of_confusion * 1000)
    return f"{hyperfocal_m:.2f} m"


def _print_fov(
    focal_length_mm: float,
    scale_factor: float,
    focus_distance_m: float | None,
) -> str:
    if not focal_length_mm or not scale_factor:
        return ""
    correction = 1.0
    if focus_distance_m:
        focus_distance_mm_minus_focal = 1000 * focus_distance_m - focal_length_mm
        if focus_distance_mm_minus_focal > 0:
            correction += focal_length_mm / focus_distance_mm_minus_focal
    half_angle = math.atan2(36, 2 * focal_length_mm * scale_factor * correction)
    field_of_view = half_angle * 360 / 3.14159
    rendered = f"{field_of_view:.1f} deg"
    if focus_distance_m and 0 < focus_distance_m < 10000:
        width_m = 2 * focus_distance_m * math.sin(half_angle) / math.cos(half_angle)
        rendered += f" ({width_m:.2f} m)"
    return rendered


def _print_dof(inputs: ExifLensCompositeInputs, circle_of_confusion: float) -> str | None:
    if not inputs.subject_distance_m:
        return None
    if not inputs.focal_length_mm or not circle_of_confusion:
        return "0.00 m (0.00 - 0.00 m)"
    distance_m = inputs.subject_distance_m or 1e10
    focal_length_mm = inputs.focal_length_mm
    t_value = (
        inputs.aperture
        * circle_of_confusion
        * (distance_m * 1000 - focal_length_mm)
        / (focal_length_mm * focal_length_mm)
    )
    near = distance_m / (1 + t_value)
    far = distance_m / (1 - t_value)
    if far < 0:
        far = 0
    if not far:
        return f"inf ({near:.2f} m - inf)"
    depth = far - near
    precision = 3 if 0 < depth < 0.02 else 2
    return f"{depth:.{precision}f} m ({near:.{precision}f} - {far:.{precision}f} m)"
