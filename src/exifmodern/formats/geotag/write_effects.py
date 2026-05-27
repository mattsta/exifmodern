"""Multi-owner Geotag write effects.

The upstream SetGeoValues flow writes across tag owners: GPS IFD tags for position and
motion, plus ExifIFD CameraElevationAngle for pitch. This module keeps that
application-level composition explicit without merging the owner-specific
writers.
"""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.exif_scalar_write_plan import (
    ExifScalarWritePlan,
    build_exif_scalar_delete_plan,
    build_exif_scalar_write_plan,
)
from exifmodern.formats.geotag.application import (
    GeotagApplicationRequest,
    GeotagApplicationResult,
    GeotagApplicationStatus,
    apply_geotag_track,
)
from exifmodern.write_plan import ExifGpsTagName, ExifGpsWritePlan, gps_delete_step

DELETE_GEOTAG_TAG_NAMES: tuple[ExifGpsTagName, ...] = (
    "GPSVersionID",
    "GPSLatitude",
    "GPSLatitudeRef",
    "GPSLongitude",
    "GPSLongitudeRef",
    "GPSAltitude",
    "GPSAltitudeRef",
    "GPSDateStamp",
    "GPSTimeStamp",
    "GPSTrack",
    "GPSTrackRef",
    "GPSSpeed",
    "GPSSpeedRef",
    "GPSImgDirection",
    "GPSImgDirectionRef",
    "GPSMeasureMode",
    "GPSDOP",
)


@dataclass(frozen=True)
class GeotagWriteEffects:
    application_result: GeotagApplicationResult
    gps_write_plan: ExifGpsWritePlan | None
    exif_scalar_write_plan: ExifScalarWritePlan | None

    @property
    def status(self) -> GeotagApplicationStatus:
        return self.application_result.status


def apply_geotag_write_effects(request: GeotagApplicationRequest) -> GeotagWriteEffects:
    application_result = apply_geotag_track(request)
    if application_result.status != "ok" or application_result.selected_fix is None:
        return GeotagWriteEffects(
            application_result=application_result,
            gps_write_plan=None,
            exif_scalar_write_plan=None,
        )
    return GeotagWriteEffects(
        application_result=application_result,
        gps_write_plan=application_result.write_plan,
        exif_scalar_write_plan=geotag_exif_scalar_plan(request, application_result),
    )


def delete_geotag_write_effects() -> GeotagWriteEffects:
    return GeotagWriteEffects(
        application_result=GeotagApplicationResult(
            status="ok",
            selected_fix=None,
            write_plan=None,
            warning=None,
        ),
        gps_write_plan=ExifGpsWritePlan(
            schema_version=1,
            generated_at_epoch=0,
            status="planned",
            scope="exif_gps_plan_only",
            steps=tuple(gps_delete_step(tag_name) for tag_name in DELETE_GEOTAG_TAG_NAMES),
            container_actions=(),
            safety_gates=(),
        ),
        exif_scalar_write_plan=build_exif_scalar_delete_plan(
            delete_image_description=False,
            delete_orientation=False,
            delete_date_time_original=False,
            delete_camera_elevation_angle=True,
        ),
    )


def geotag_exif_scalar_plan(
    request: GeotagApplicationRequest,
    application_result: GeotagApplicationResult,
) -> ExifScalarWritePlan | None:
    if application_result.selected_fix is None:
        return None
    if application_result.selected_fix.pitch is not None:
        return build_exif_scalar_write_plan(
            image_description=None,
            orientation=None,
            date_time_original=None,
            camera_elevation_angle=application_result.selected_fix.pitch,
        )
    if "orient" in request.track_log.has:
        return build_exif_scalar_delete_plan(
            delete_image_description=False,
            delete_orientation=False,
            delete_date_time_original=False,
            delete_camera_elevation_angle=True,
        )
    return None
