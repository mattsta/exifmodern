"""Typed write plans for common EXIF scalar tags."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from exifmodern.write_plan import SourceEvidenceId

type ExifScalarTagName = Literal[
    "ImageDescription",
    "Orientation",
    "XResolution",
    "YResolution",
    "ResolutionUnit",
    "ModifyDate",
    "Artist",
    "ISO",
    "DateTimeOriginal",
    "ApertureValue",
    "MaxApertureValue",
    "FocalLength",
    "UserComment",
    "OwnerName",
    "AmbientTemperature",
    "Acceleration",
    "SceneCaptureType",
    "CameraElevationAngle",
]
type ExifScalarDirectoryName = Literal["IFD0", "ExifIFD"]
type ExifScalarFieldType = Literal["ASCII", "SHORT", "RATIONAL", "UNDEFINED", "SRATIONAL"]
type ExifScalarWriteOperation = Literal["ensure", "upsert", "delete"]

EXIF_SCALAR_TAG_IDS: dict[ExifScalarTagName, str] = {
    "ImageDescription": "0x010E",
    "Orientation": "0x0112",
    "XResolution": "0x011A",
    "YResolution": "0x011B",
    "ResolutionUnit": "0x0128",
    "ModifyDate": "0x0132",
    "Artist": "0x013B",
    "ISO": "0x8827",
    "DateTimeOriginal": "0x9003",
    "ApertureValue": "0x9202",
    "MaxApertureValue": "0x9205",
    "FocalLength": "0x920A",
    "UserComment": "0x9286",
    "OwnerName": "0xA430",
    "AmbientTemperature": "0x9400",
    "Acceleration": "0x9404",
    "SceneCaptureType": "0xA406",
    "CameraElevationAngle": "0x9405",
}

EXIF_MAIN_SOURCE_ID: SourceEvidenceId = "exif.scalar.main_table"
IMAGE_DESCRIPTION_SOURCE_ID: SourceEvidenceId = "exif.scalar.image_description"
ORIENTATION_SOURCE_ID: SourceEvidenceId = "exif.scalar.orientation"
X_RESOLUTION_SOURCE_ID: SourceEvidenceId = "exif.scalar.x_resolution"
Y_RESOLUTION_SOURCE_ID: SourceEvidenceId = "exif.scalar.y_resolution"
RESOLUTION_UNIT_SOURCE_ID: SourceEvidenceId = "exif.scalar.resolution_unit"
MODIFY_DATE_SOURCE_ID: SourceEvidenceId = "exif.scalar.modify_date"
ARTIST_SOURCE_ID: SourceEvidenceId = "exif.scalar.artist"
ISO_SOURCE_ID: SourceEvidenceId = "exif.scalar.iso"
DATE_TIME_ORIGINAL_SOURCE_ID: SourceEvidenceId = "exif.scalar.date_time_original"
APERTURE_VALUE_SOURCE_ID: SourceEvidenceId = "exif.scalar.aperture_value"
MAX_APERTURE_VALUE_SOURCE_ID: SourceEvidenceId = "exif.scalar.max_aperture_value"
FOCAL_LENGTH_SOURCE_ID: SourceEvidenceId = "exif.scalar.focal_length"
USER_COMMENT_SOURCE_ID: SourceEvidenceId = "exif.scalar.user_comment"
OWNER_NAME_SOURCE_ID: SourceEvidenceId = "exif.scalar.owner_name"
SCENE_CAPTURE_TYPE_SOURCE_ID: SourceEvidenceId = "exif.scalar.scene_capture_type"
AMBIENT_TEMPERATURE_SOURCE_ID: SourceEvidenceId = "exif.scalar.ambient_temperature"
ACCELERATION_SOURCE_ID: SourceEvidenceId = "exif.scalar.acceleration"
CAMERA_ELEVATION_ANGLE_SOURCE_ID: SourceEvidenceId = "exif.scalar.camera_elevation_angle"
GEOTAG_CAMERA_ELEVATION_SOURCE_ID: SourceEvidenceId = "exif.scalar.geotag_camera_elevation"
EXIF_IFD_DEFAULT_SOURCE_ID: SourceEvidenceId = "exif.scalar.exif_ifd_defaults"
IFD0_DEFAULT_SOURCE_ID: SourceEvidenceId = "exif.scalar.ifd0_defaults"


ORIENTATION_TEXT_TO_VALUE = {
    "Horizontal (normal)": 1,
    "Mirror horizontal": 2,
    "Rotate 180": 3,
    "Mirror vertical": 4,
    "Mirror horizontal and rotate 270 CW": 5,
    "Rotate 90 CW": 6,
    "Mirror horizontal and rotate 90 CW": 7,
    "Rotate 270 CW": 8,
}
RESOLUTION_UNIT_TEXT_TO_VALUE = {
    "None": 1,
    "inches": 2,
    "inch": 2,
    "cm": 3,
    "centimeters": 3,
    "centimetres": 3,
}
SCENE_CAPTURE_TYPE_TEXT_TO_VALUE = {
    "standard": 0,
    "landscape": 1,
    "portrait": 2,
    "night": 3,
    "other": 4,
}


@dataclass(frozen=True)
class ExifScalarAsciiWriteValue:
    text: str
    nul_terminated: bool = True


@dataclass(frozen=True)
class ExifScalarShortWriteValue:
    value: int


@dataclass(frozen=True)
class ExifScalarRationalWriteValue:
    numerator: int
    denominator: int


@dataclass(frozen=True)
class ExifScalarUndefinedWriteValue:
    value: bytes


@dataclass(frozen=True)
class ExifScalarSignedRationalWriteValue:
    numerator: int
    denominator: int


@dataclass(frozen=True)
class ExifScalarDeleteWriteValue:
    pass


type ExifScalarWriteValue = (
    ExifScalarAsciiWriteValue
    | ExifScalarShortWriteValue
    | ExifScalarRationalWriteValue
    | ExifScalarUndefinedWriteValue
    | ExifScalarSignedRationalWriteValue
    | ExifScalarDeleteWriteValue
)


@dataclass(frozen=True)
class ExifScalarWriteStep:
    operation: ExifScalarWriteOperation
    directory_name: ExifScalarDirectoryName
    group: str
    table_name: str
    tag_name: ExifScalarTagName
    tag_id: str
    field_type: ExifScalarFieldType
    count: int
    value: ExifScalarWriteValue
    evidence_ids: tuple[SourceEvidenceId, ...]


@dataclass(frozen=True)
class ExifScalarWritePlan:
    steps: tuple[ExifScalarWriteStep, ...]

    @property
    def is_delete_only(self) -> bool:
        return all(step.operation == "delete" for step in self.steps)


def build_exif_scalar_write_plan(
    image_description: str | None,
    orientation: str | int | None,
    date_time_original: str | None,
    modify_date: str | None = None,
    owner_name: str | None = None,
    camera_elevation_angle: float | None = None,
    x_resolution: str | int | float | None = None,
    y_resolution: str | int | float | None = None,
    resolution_unit: str | int | None = None,
    artist: str | None = None,
    iso: str | int | None = None,
    aperture_value: str | int | float | None = None,
    max_aperture_value: str | int | float | None = None,
    focal_length: str | int | float | None = None,
    user_comment: str | None = None,
    ambient_temperature: str | int | float | None = None,
    acceleration: str | int | float | None = None,
    scene_capture_type: str | int | None = None,
    raw_date_time_original: bool = False,
) -> ExifScalarWritePlan:
    steps: list[ExifScalarWriteStep] = []
    if image_description is not None:
        steps.append(image_description_step(image_description))
    if orientation is not None:
        steps.append(orientation_step(orientation))
    if x_resolution is not None:
        steps.append(x_resolution_step(x_resolution))
    if y_resolution is not None:
        steps.append(y_resolution_step(y_resolution))
    if resolution_unit is not None:
        steps.append(resolution_unit_step(resolution_unit))
    if modify_date is not None:
        steps.append(modify_date_step(modify_date))
    if artist is not None:
        steps.append(artist_step(artist))
    if iso is not None:
        steps.append(iso_step(iso))
    if date_time_original is not None:
        steps.append(
            date_time_original_step(date_time_original, validate=not raw_date_time_original)
        )
    if aperture_value is not None:
        steps.append(aperture_value_step(aperture_value))
    if max_aperture_value is not None:
        steps.append(max_aperture_value_step(max_aperture_value))
    if focal_length is not None:
        steps.append(focal_length_step(focal_length))
    if user_comment is not None:
        steps.append(user_comment_step(user_comment))
    if owner_name is not None:
        steps.append(owner_name_step(owner_name))
    if ambient_temperature is not None:
        steps.append(ambient_temperature_step(ambient_temperature))
    if acceleration is not None:
        steps.append(acceleration_step(acceleration))
    if scene_capture_type is not None:
        steps.append(scene_capture_type_step(scene_capture_type))
    if camera_elevation_angle is not None:
        steps.append(camera_elevation_angle_step(camera_elevation_angle))
    if not steps:
        raise ValueError("EXIF scalar write plan requires at least one value.")
    return ExifScalarWritePlan(steps=tuple(steps))


def build_exif_scalar_delete_plan(
    delete_image_description: bool,
    delete_orientation: bool,
    delete_date_time_original: bool,
    delete_modify_date: bool = False,
    delete_owner_name: bool = False,
    delete_camera_elevation_angle: bool = False,
    delete_x_resolution: bool = False,
    delete_y_resolution: bool = False,
    delete_resolution_unit: bool = False,
    delete_artist: bool = False,
    delete_iso: bool = False,
    delete_aperture_value: bool = False,
    delete_max_aperture_value: bool = False,
    delete_focal_length: bool = False,
    delete_user_comment: bool = False,
    delete_ambient_temperature: bool = False,
    delete_acceleration: bool = False,
    delete_scene_capture_type: bool = False,
) -> ExifScalarWritePlan:
    steps: list[ExifScalarWriteStep] = []
    if delete_image_description:
        steps.append(delete_image_description_step())
    if delete_orientation:
        steps.append(delete_orientation_step())
    if delete_x_resolution:
        steps.append(delete_x_resolution_step())
    if delete_y_resolution:
        steps.append(delete_y_resolution_step())
    if delete_resolution_unit:
        steps.append(delete_resolution_unit_step())
    if delete_modify_date:
        steps.append(delete_modify_date_step())
    if delete_artist:
        steps.append(delete_artist_step())
    if delete_iso:
        steps.append(delete_iso_step())
    if delete_date_time_original:
        steps.append(delete_date_time_original_step())
    if delete_aperture_value:
        steps.append(delete_aperture_value_step())
    if delete_max_aperture_value:
        steps.append(delete_max_aperture_value_step())
    if delete_focal_length:
        steps.append(delete_focal_length_step())
    if delete_user_comment:
        steps.append(delete_user_comment_step())
    if delete_owner_name:
        steps.append(delete_owner_name_step())
    if delete_ambient_temperature:
        steps.append(delete_ambient_temperature_step())
    if delete_acceleration:
        steps.append(delete_acceleration_step())
    if delete_scene_capture_type:
        steps.append(delete_scene_capture_type_step())
    if delete_camera_elevation_angle:
        steps.append(delete_camera_elevation_angle_step())
    if not steps:
        raise ValueError("EXIF scalar delete plan requires at least one tag.")
    return ExifScalarWritePlan(steps=tuple(steps))


def image_description_step(value: str) -> ExifScalarWriteStep:
    if not value:
        raise ValueError("ImageDescription must not be empty.")
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="ImageDescription",
        tag_id=EXIF_SCALAR_TAG_IDS["ImageDescription"],
        field_type="ASCII",
        count=len(value) + 1,
        value=ExifScalarAsciiWriteValue(value),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, IMAGE_DESCRIPTION_SOURCE_ID),
    )


def delete_image_description_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="ImageDescription",
        tag_id=EXIF_SCALAR_TAG_IDS["ImageDescription"],
        field_type="ASCII",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, IMAGE_DESCRIPTION_SOURCE_ID),
    )


def orientation_step(value: str | int) -> ExifScalarWriteStep:
    orientation_value = normalize_orientation(value)
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="Orientation",
        tag_id=EXIF_SCALAR_TAG_IDS["Orientation"],
        field_type="SHORT",
        count=1,
        value=ExifScalarShortWriteValue(orientation_value),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, ORIENTATION_SOURCE_ID),
    )


def delete_orientation_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="Orientation",
        tag_id=EXIF_SCALAR_TAG_IDS["Orientation"],
        field_type="SHORT",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, ORIENTATION_SOURCE_ID),
    )


def x_resolution_step(value: str | int | float) -> ExifScalarWriteStep:
    rational = scalar_rational_write_value(value)
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="XResolution",
        tag_id=EXIF_SCALAR_TAG_IDS["XResolution"],
        field_type="RATIONAL",
        count=1,
        value=rational,
        evidence_ids=(EXIF_MAIN_SOURCE_ID, X_RESOLUTION_SOURCE_ID),
    )


def delete_x_resolution_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="XResolution",
        tag_id=EXIF_SCALAR_TAG_IDS["XResolution"],
        field_type="RATIONAL",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, X_RESOLUTION_SOURCE_ID),
    )


def y_resolution_step(value: str | int | float) -> ExifScalarWriteStep:
    rational = scalar_rational_write_value(value)
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="YResolution",
        tag_id=EXIF_SCALAR_TAG_IDS["YResolution"],
        field_type="RATIONAL",
        count=1,
        value=rational,
        evidence_ids=(EXIF_MAIN_SOURCE_ID, Y_RESOLUTION_SOURCE_ID),
    )


def delete_y_resolution_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="YResolution",
        tag_id=EXIF_SCALAR_TAG_IDS["YResolution"],
        field_type="RATIONAL",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, Y_RESOLUTION_SOURCE_ID),
    )


def resolution_unit_step(value: str | int) -> ExifScalarWriteStep:
    unit_value = normalize_resolution_unit(value)
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="ResolutionUnit",
        tag_id=EXIF_SCALAR_TAG_IDS["ResolutionUnit"],
        field_type="SHORT",
        count=1,
        value=ExifScalarShortWriteValue(unit_value),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, RESOLUTION_UNIT_SOURCE_ID),
    )


def delete_resolution_unit_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="ResolutionUnit",
        tag_id=EXIF_SCALAR_TAG_IDS["ResolutionUnit"],
        field_type="SHORT",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, RESOLUTION_UNIT_SOURCE_ID),
    )


def modify_date_step(value: str) -> ExifScalarWriteStep:
    validate_exif_datetime(value)
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="ModifyDate",
        tag_id=EXIF_SCALAR_TAG_IDS["ModifyDate"],
        field_type="ASCII",
        count=len(value) + 1,
        value=ExifScalarAsciiWriteValue(value),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, MODIFY_DATE_SOURCE_ID),
    )


def delete_modify_date_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="ModifyDate",
        tag_id=EXIF_SCALAR_TAG_IDS["ModifyDate"],
        field_type="ASCII",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, MODIFY_DATE_SOURCE_ID),
    )


def artist_step(value: str) -> ExifScalarWriteStep:
    if not value:
        raise ValueError("Artist must not be empty.")
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="Artist",
        tag_id=EXIF_SCALAR_TAG_IDS["Artist"],
        field_type="ASCII",
        count=len(value) + 1,
        value=ExifScalarAsciiWriteValue(value),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, ARTIST_SOURCE_ID),
    )


def delete_artist_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="IFD0",
        group="IFD0",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="Artist",
        tag_id=EXIF_SCALAR_TAG_IDS["Artist"],
        field_type="ASCII",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, ARTIST_SOURCE_ID),
    )


def iso_step(value: str | int) -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="ISO",
        tag_id=EXIF_SCALAR_TAG_IDS["ISO"],
        field_type="SHORT",
        count=1,
        value=ExifScalarShortWriteValue(normalize_iso(value)),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, ISO_SOURCE_ID),
    )


def delete_iso_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="ISO",
        tag_id=EXIF_SCALAR_TAG_IDS["ISO"],
        field_type="SHORT",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, ISO_SOURCE_ID),
    )


def date_time_original_step(value: str, *, validate: bool = True) -> ExifScalarWriteStep:
    if validate:
        validate_exif_datetime(value)
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="DateTimeOriginal",
        tag_id=EXIF_SCALAR_TAG_IDS["DateTimeOriginal"],
        field_type="ASCII",
        count=len(value) + 1,
        value=ExifScalarAsciiWriteValue(value),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, DATE_TIME_ORIGINAL_SOURCE_ID),
    )


def delete_date_time_original_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="DateTimeOriginal",
        tag_id=EXIF_SCALAR_TAG_IDS["DateTimeOriginal"],
        field_type="ASCII",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, DATE_TIME_ORIGINAL_SOURCE_ID),
    )


def max_aperture_value_step(value: str | int | float) -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="MaxApertureValue",
        tag_id=EXIF_SCALAR_TAG_IDS["MaxApertureValue"],
        field_type="RATIONAL",
        count=1,
        value=max_aperture_value_write_value(value),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, MAX_APERTURE_VALUE_SOURCE_ID),
    )


def aperture_value_step(value: str | int | float) -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="ApertureValue",
        tag_id=EXIF_SCALAR_TAG_IDS["ApertureValue"],
        field_type="RATIONAL",
        count=1,
        value=apex_aperture_write_value(value, tag_name="ApertureValue"),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, APERTURE_VALUE_SOURCE_ID),
    )


def delete_aperture_value_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="ApertureValue",
        tag_id=EXIF_SCALAR_TAG_IDS["ApertureValue"],
        field_type="RATIONAL",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, APERTURE_VALUE_SOURCE_ID),
    )


def delete_max_aperture_value_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="MaxApertureValue",
        tag_id=EXIF_SCALAR_TAG_IDS["MaxApertureValue"],
        field_type="RATIONAL",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, MAX_APERTURE_VALUE_SOURCE_ID),
    )


def focal_length_step(value: str | int | float) -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="FocalLength",
        tag_id=EXIF_SCALAR_TAG_IDS["FocalLength"],
        field_type="RATIONAL",
        count=1,
        value=measurement_rational_write_value(value, unit_suffix="mm"),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, FOCAL_LENGTH_SOURCE_ID),
    )


def delete_focal_length_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="FocalLength",
        tag_id=EXIF_SCALAR_TAG_IDS["FocalLength"],
        field_type="RATIONAL",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, FOCAL_LENGTH_SOURCE_ID),
    )


def user_comment_step(value: str) -> ExifScalarWriteStep:
    if not value:
        raise ValueError("UserComment must not be empty.")
    encoded = b"ASCII\x00\x00\x00" + value.encode("ascii")
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="UserComment",
        tag_id=EXIF_SCALAR_TAG_IDS["UserComment"],
        field_type="UNDEFINED",
        count=len(encoded),
        value=ExifScalarUndefinedWriteValue(encoded),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, USER_COMMENT_SOURCE_ID),
    )


def delete_user_comment_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="UserComment",
        tag_id=EXIF_SCALAR_TAG_IDS["UserComment"],
        field_type="UNDEFINED",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, USER_COMMENT_SOURCE_ID),
    )


def owner_name_step(value: str) -> ExifScalarWriteStep:
    if not value:
        raise ValueError("OwnerName must not be empty.")
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="OwnerName",
        tag_id=EXIF_SCALAR_TAG_IDS["OwnerName"],
        field_type="ASCII",
        count=len(value) + 1,
        value=ExifScalarAsciiWriteValue(value),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, OWNER_NAME_SOURCE_ID),
    )


def delete_owner_name_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="OwnerName",
        tag_id=EXIF_SCALAR_TAG_IDS["OwnerName"],
        field_type="ASCII",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, OWNER_NAME_SOURCE_ID),
    )


def ambient_temperature_step(value: str | int | float) -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="AmbientTemperature",
        tag_id=EXIF_SCALAR_TAG_IDS["AmbientTemperature"],
        field_type="SRATIONAL",
        count=1,
        value=measurement_signed_rational_write_value(value, unit_suffix="C"),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, AMBIENT_TEMPERATURE_SOURCE_ID),
    )


def delete_ambient_temperature_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="AmbientTemperature",
        tag_id=EXIF_SCALAR_TAG_IDS["AmbientTemperature"],
        field_type="SRATIONAL",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, AMBIENT_TEMPERATURE_SOURCE_ID),
    )


def acceleration_step(value: str | int | float) -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="Acceleration",
        tag_id=EXIF_SCALAR_TAG_IDS["Acceleration"],
        field_type="RATIONAL",
        count=1,
        value=scalar_rational_write_value(value),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, ACCELERATION_SOURCE_ID),
    )


def delete_acceleration_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="Acceleration",
        tag_id=EXIF_SCALAR_TAG_IDS["Acceleration"],
        field_type="RATIONAL",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, ACCELERATION_SOURCE_ID),
    )


def scene_capture_type_step(value: str | int) -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="SceneCaptureType",
        tag_id=EXIF_SCALAR_TAG_IDS["SceneCaptureType"],
        field_type="SHORT",
        count=1,
        value=ExifScalarShortWriteValue(normalize_scene_capture_type(value)),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, SCENE_CAPTURE_TYPE_SOURCE_ID),
    )


def delete_scene_capture_type_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="SceneCaptureType",
        tag_id=EXIF_SCALAR_TAG_IDS["SceneCaptureType"],
        field_type="SHORT",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(EXIF_MAIN_SOURCE_ID, SCENE_CAPTURE_TYPE_SOURCE_ID),
    )


def camera_elevation_angle_step(value: float) -> ExifScalarWriteStep:
    if not math.isfinite(value):
        raise ValueError("CameraElevationAngle must be finite.")
    rational = scalar_signed_rational_write_value(value)
    return ExifScalarWriteStep(
        operation="upsert",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="CameraElevationAngle",
        tag_id=EXIF_SCALAR_TAG_IDS["CameraElevationAngle"],
        field_type="SRATIONAL",
        count=1,
        value=rational,
        evidence_ids=(
            EXIF_MAIN_SOURCE_ID,
            CAMERA_ELEVATION_ANGLE_SOURCE_ID,
            GEOTAG_CAMERA_ELEVATION_SOURCE_ID,
        ),
    )


def delete_camera_elevation_angle_step() -> ExifScalarWriteStep:
    return ExifScalarWriteStep(
        operation="delete",
        directory_name="ExifIFD",
        group="ExifIFD",
        table_name="Image::ExifTool::Exif::Main",
        tag_name="CameraElevationAngle",
        tag_id=EXIF_SCALAR_TAG_IDS["CameraElevationAngle"],
        field_type="SRATIONAL",
        count=0,
        value=ExifScalarDeleteWriteValue(),
        evidence_ids=(
            EXIF_MAIN_SOURCE_ID,
            CAMERA_ELEVATION_ANGLE_SOURCE_ID,
            GEOTAG_CAMERA_ELEVATION_SOURCE_ID,
        ),
    )


def normalize_orientation(value: str | int) -> int:
    if isinstance(value, int):
        orientation: int | None = value
    else:
        orientation = ORIENTATION_TEXT_TO_VALUE.get(value)
        if orientation is None and value.isdecimal():
            orientation = int(value)
    if orientation is None or not 1 <= orientation <= 8:
        raise ValueError("Orientation must be 1-8 or a supported ExifTool orientation string.")
    return orientation


def normalize_resolution_unit(value: str | int) -> int:
    if isinstance(value, int):
        unit_value: int | None = value
    else:
        unit_value = RESOLUTION_UNIT_TEXT_TO_VALUE.get(value)
        if unit_value is None and value.isdecimal():
            unit_value = int(value)
    if unit_value is None or not 1 <= unit_value <= 3:
        raise ValueError("ResolutionUnit must be 1-3 or a supported ExifTool unit string.")
    return unit_value


def normalize_iso(value: str | int) -> int:
    if isinstance(value, int):
        iso_value: int | None = value
    else:
        normalized = value.replace(",", "").strip()
        iso_value = int(normalized) if normalized.isdecimal() else None
    if iso_value is None or not 1 <= iso_value <= 65535:
        raise ValueError("ISO must be an integer in the EXIF int16u range 1-65535.")
    return iso_value


def normalize_scene_capture_type(value: str | int) -> int:
    if isinstance(value, int):
        scene_value: int | None = value
    else:
        normalized = value.strip().lower()
        scene_value = SCENE_CAPTURE_TYPE_TEXT_TO_VALUE.get(normalized)
        if scene_value is None and normalized.isdecimal():
            scene_value = int(normalized)
    if scene_value is None or not 0 <= scene_value <= 4:
        raise ValueError(
            "SceneCaptureType must be 0-4 or Standard, Landscape, Portrait, Night, or Other."
        )
    return scene_value


def validate_exif_datetime(value: str) -> None:
    if len(value) != 19:
        raise ValueError("EXIF date/time must use YYYY:MM:DD HH:MM:SS.")
    digit_positions = {0, 1, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18}
    for index, character in enumerate(value):
        if index in digit_positions:
            if not character.isdecimal():
                raise ValueError("EXIF date/time must use YYYY:MM:DD HH:MM:SS.")
        elif (index, character) not in {
            (4, ":"),
            (7, ":"),
            (10, " "),
            (13, ":"),
            (16, ":"),
        }:
            raise ValueError("EXIF date/time must use YYYY:MM:DD HH:MM:SS.")


def scalar_signed_rational_write_value(value: float) -> ExifScalarSignedRationalWriteValue:
    fraction = Fraction(f"{value:.6f}").limit_denominator(1_000_000)
    return ExifScalarSignedRationalWriteValue(fraction.numerator, fraction.denominator)


def scalar_rational_write_value(value: str | int | float) -> ExifScalarRationalWriteValue:
    if isinstance(value, str):
        fraction = Fraction(value)
    else:
        fraction = Fraction(value).limit_denominator(1_000_000)
    if fraction <= 0:
        raise ValueError("EXIF rational scalar values must be positive.")
    return ExifScalarRationalWriteValue(fraction.numerator, fraction.denominator)


def measurement_rational_write_value(
    value: str | int | float,
    *,
    unit_suffix: str,
) -> ExifScalarRationalWriteValue:
    if isinstance(value, str):
        normalized = value.strip()
        suffix = unit_suffix.lower()
        if normalized.lower().endswith(suffix):
            normalized = normalized[: -len(unit_suffix)].strip()
        return scalar_rational_write_value(normalized)
    return scalar_rational_write_value(value)


def measurement_signed_rational_write_value(
    value: str | int | float,
    *,
    unit_suffix: str,
) -> ExifScalarSignedRationalWriteValue:
    if isinstance(value, str):
        normalized = value.strip()
        suffix = unit_suffix.lower()
        if normalized.lower().endswith(suffix):
            normalized = normalized[: -len(unit_suffix)].strip()
        return scalar_signed_rational_from_fraction_text(normalized)
    return scalar_signed_rational_write_value(float(value))


def max_aperture_value_write_value(
    value: str | int | float,
) -> ExifScalarRationalWriteValue:
    return apex_aperture_write_value(value, tag_name="MaxApertureValue")


def apex_aperture_write_value(
    value: str | int | float,
    *,
    tag_name: str,
) -> ExifScalarRationalWriteValue:
    f_number = float(Fraction(value.strip())) if isinstance(value, str) else float(value)
    if not math.isfinite(f_number) or f_number <= 0:
        raise ValueError(f"{tag_name} must be a positive finite F number.")
    apex_value = 2 * math.log(f_number) / math.log(2)
    return scalar_rational_write_value(apex_value)


def scalar_signed_rational_from_fraction_text(value: str) -> ExifScalarSignedRationalWriteValue:
    fraction = Fraction(value)
    return ExifScalarSignedRationalWriteValue(fraction.numerator, fraction.denominator)
