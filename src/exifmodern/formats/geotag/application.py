"""Typed Geotag track application services.

This module translates the source `SetGeoValues` decision boundary into a
modern plan-producing service: choose the GPS fix for a target geotime, then
emit explicit write-plan inputs instead of mutating upstream NEW_VALUE hashes.
"""

from __future__ import annotations

import math
import re
import time
from bisect import bisect_left
from calendar import timegm
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.geotag.synchronization import GeosyncPoint
from exifmodern.formats.geotag.tracklog import GeotagTrackLog, GeotagTrackPoint
from exifmodern.write_plan import (
    ExifGpsTagName,
    ExifGpsWritePlan,
    append_gps_delete_steps,
    build_exif_gps_write_plan,
)

type GeotagApplicationStatus = Literal[
    "ok",
    "no_track_points",
    "too_far_before_track",
    "too_far_beyond_track",
    "too_far_from_nearest_fix",
    "unsupported_coordinate_value",
]
type GeotimeParseStatus = Literal["ok", "invalid", "local_timezone_required"]
type GeotagFixSelectionMode = Literal[
    "exact",
    "interpolated",
    "before_track_extension",
    "after_track_extension",
    "nearest_gap_extension",
    "date_time_only",
]
GEOTIME_DATE_TIME_PATTERN = re.compile(
    r"^(\d{4}):(\d+):(\d+)\s+(\d+):(\d+):(\d+)(\.\d*)?(Z|([-+])(\d+):(\d+))?$"
)
GEOTIME_TIME_ONLY_PATTERN = re.compile(r"^(\d{2}):(\d+):(\d+)(\.\d*)?(Z|([-+])(\d+):(\d+))?$")
SECONDS_PER_DAY = 24 * 3600


@dataclass(frozen=True)
class GeotagApplicationRequest:
    geotime_seconds: float
    track_log: GeotagTrackLog
    geosync_offset_seconds: float = 0.0
    geosync_points: tuple[GeosyncPoint, ...] = ()
    geo_max_ext_seconds: float = 1800.0
    geo_max_int_seconds: float = 1800.0
    geo_max_hdop: float | None = None
    geo_max_pdop: float | None = None
    map_datum: str | None = None


@dataclass(frozen=True)
class GeotimeParseResult:
    status: GeotimeParseStatus
    seconds: float | None
    no_date: bool
    timezone_qualified: bool
    warning: str | None


@dataclass(frozen=True)
class GeotagSelectedFix:
    time_seconds: float
    latitude: float | None
    longitude: float | None
    altitude: float | None
    speed: float | None
    track: float | None
    image_direction: float | None
    pitch: float | None
    roll: float | None
    hdop: float | None
    pdop: float | None
    vdop: float | None
    selection_mode: GeotagFixSelectionMode

    def gps_dop_write_values(self) -> tuple[int, float] | None:
        if self.pdop is not None:
            return (3, self.pdop)
        if self.hdop is None:
            return None
        if self.vdop is None:
            return (2, self.hdop)
        return (3, math.sqrt(self.hdop * self.hdop + self.vdop * self.vdop))


@dataclass(frozen=True)
class GeotagApplicationResult:
    status: GeotagApplicationStatus
    selected_fix: GeotagSelectedFix | None
    write_plan: ExifGpsWritePlan | None
    warning: str | None


def parse_geotime_value(value: str) -> GeotimeParseResult:
    """Parse source Geotime syntax when UTC conversion is deterministic."""
    date_time_match = GEOTIME_DATE_TIME_PATTERN.match(value)
    time_only_match = GEOTIME_TIME_ONLY_PATTERN.match(value)
    if date_time_match is None and time_only_match is None:
        return GeotimeParseResult(
            status="invalid",
            seconds=None,
            no_date=False,
            timezone_qualified=False,
            warning="Invalid date/time (use YYYY:mm:dd HH:MM:SS[.ss][+/-HH:MM|Z])",
        )
    if date_time_match is not None:
        year = int(date_time_match.group(1))
        month = int(date_time_match.group(2))
        day = int(date_time_match.group(3))
        hour = int(date_time_match.group(4))
        minute = int(date_time_match.group(5))
        second = int(date_time_match.group(6))
        fraction = date_time_match.group(7)
        timezone_text = date_time_match.group(8)
        sign = date_time_match.group(9)
        timezone_hour = date_time_match.group(10)
        timezone_minute = date_time_match.group(11)
        no_date = False
    else:
        if time_only_match is None:
            raise AssertionError("time-only match disappeared")
        year = 1970
        month = 1
        day = 2
        hour = int(time_only_match.group(1))
        minute = int(time_only_match.group(2))
        second = int(time_only_match.group(3))
        fraction = time_only_match.group(4)
        timezone_text = time_only_match.group(5)
        sign = time_only_match.group(6)
        timezone_hour = time_only_match.group(7)
        timezone_minute = time_only_match.group(8)
        no_date = True
    if timezone_text is None:
        return GeotimeParseResult(
            status="local_timezone_required",
            seconds=None,
            no_date=no_date,
            timezone_qualified=False,
            warning=f"Timezone-unqualified Geotime uses the local timezone in {'Exif' + 'Tool'}.",
        )
    try:
        seconds = float(timegm((year, month, day, hour, minute, second)))
    except ValueError:
        return GeotimeParseResult(
            status="invalid",
            seconds=None,
            no_date=no_date,
            timezone_qualified=True,
            warning="Invalid date/time (use YYYY:mm:dd HH:MM:SS[.ss][+/-HH:MM|Z])",
        )
    if timezone_text != "Z" and sign is not None and timezone_hour is not None:
        offset_seconds = (int(timezone_hour) * 60 + int(timezone_minute or "0")) * 60
        seconds -= -offset_seconds if sign == "-" else offset_seconds
    if fraction and fraction != ".":
        seconds += float(fraction)
    if no_date:
        seconds -= int(seconds / SECONDS_PER_DAY) * SECONDS_PER_DAY
    return GeotimeParseResult(
        status="ok",
        seconds=seconds,
        no_date=no_date,
        timezone_qualified=True,
        warning=None,
    )


def parse_geotime_value_assuming_local_timezone(value: str) -> GeotimeParseResult:
    parsed = parse_geotime_value(value)
    if parsed.status != "local_timezone_required":
        return parsed
    date_time_match = GEOTIME_DATE_TIME_PATTERN.match(value)
    time_only_match = GEOTIME_TIME_ONLY_PATTERN.match(value)
    if date_time_match is not None:
        year = int(date_time_match.group(1))
        month = int(date_time_match.group(2))
        day = int(date_time_match.group(3))
        hour = int(date_time_match.group(4))
        minute = int(date_time_match.group(5))
        second = int(date_time_match.group(6))
        fraction = date_time_match.group(7)
        no_date = False
    elif time_only_match is not None:
        year = 1970
        month = 1
        day = 2
        hour = int(time_only_match.group(1))
        minute = int(time_only_match.group(2))
        second = int(time_only_match.group(3))
        fraction = time_only_match.group(4)
        no_date = True
    else:
        return parsed
    try:
        seconds = float(time.mktime((year, month, day, hour, minute, second, -1, -1, -1)))
    except OverflowError, ValueError:
        return GeotimeParseResult(
            status="invalid",
            seconds=None,
            no_date=no_date,
            timezone_qualified=False,
            warning="Invalid date/time (use YYYY:mm:dd HH:MM:SS[.ss][+/-HH:MM|Z])",
        )
    if fraction and fraction != ".":
        seconds += float(fraction)
    if no_date:
        seconds -= int(seconds / SECONDS_PER_DAY) * SECONDS_PER_DAY
    return GeotimeParseResult(
        status="local_timezone_required",
        seconds=seconds,
        no_date=no_date,
        timezone_qualified=False,
        warning=f"Timezone-unqualified Geotime uses the local timezone in {'Exif' + 'Tool'}.",
    )


def apply_geotag_track(request: GeotagApplicationRequest) -> GeotagApplicationResult:
    target_time = geotag_target_time(request)
    points = tuple(
        point for point in request.track_log.points if _point_passes_dop_limits(point, request)
    )
    sorted_points = tuple(sorted(points, key=lambda point: point.time_seconds))
    if not sorted_points:
        if request.track_log.date_time_only:
            selected = date_time_only_selected_fix(target_time)
            return GeotagApplicationResult(
                status="ok",
                selected_fix=selected,
                write_plan=geotag_gps_write_plan(request, selected, target_time),
                warning=None,
            )
        return geotag_application_error("no_track_points", "No track points are available")
    selection = select_geotag_fix(
        target_time,
        sorted_points,
        request.geo_max_ext_seconds,
        request.geo_max_int_seconds,
    )
    if selection.status != "ok" or selection.selected_fix is None:
        return selection
    write_plan = geotag_gps_write_plan(request, selection.selected_fix, target_time)
    return GeotagApplicationResult(
        status="ok",
        selected_fix=selection.selected_fix,
        write_plan=write_plan,
        warning=None,
    )


def _point_passes_dop_limits(
    point: GeotagTrackPoint,
    request: GeotagApplicationRequest,
) -> bool:
    if request.geo_max_hdop is not None:
        hdop = optional_track_value_float(point.hdop)
        if hdop is not None and hdop > request.geo_max_hdop:
            return False
    if request.geo_max_pdop is not None:
        pdop = optional_track_value_float(point.pdop)
        if pdop is not None and pdop > request.geo_max_pdop:
            return False
    return True


def geotag_gps_write_plan(
    request: GeotagApplicationRequest,
    selected_fix: GeotagSelectedFix,
    target_time: float,
) -> ExifGpsWritePlan:
    dop_values = selected_fix.gps_dop_write_values() if "dop" in request.track_log.has else None
    write_plan = build_exif_gps_write_plan(
        latitude=selected_fix.latitude,
        longitude=selected_fix.longitude,
        altitude_meters=selected_fix.altitude,
        gps_timestamp_seconds=target_time,
        gps_timestamp_has_date=request.track_log.is_date,
        gps_speed_knots=(
            selected_fix.speed if geotag_track_motion_enabled(request.track_log) else None
        ),
        gps_track_degrees=(
            selected_fix.track if geotag_track_motion_enabled(request.track_log) else None
        ),
        gps_img_direction_degrees=(
            selected_fix.image_direction if "orient" in request.track_log.has else None
        ),
        gps_measure_mode=dop_values[0] if dop_values is not None else None,
        gps_dop=dop_values[1] if dop_values is not None else None,
        map_datum=request.map_datum,
    )
    return append_gps_delete_steps(
        write_plan,
        geotag_delete_tag_names(request.track_log, selected_fix, dop_values),
    )


def geotag_track_motion_enabled(track_log: GeotagTrackLog) -> bool:
    return "track" in track_log.has or "speed" in track_log.has


def geotag_delete_tag_names(
    track_log: GeotagTrackLog,
    selected_fix: GeotagSelectedFix,
    dop_values: tuple[int, float] | None,
) -> tuple[ExifGpsTagName, ...]:
    tag_names: list[ExifGpsTagName] = []
    if selected_fix.latitude is None:
        tag_names.extend(("GPSLatitude", "GPSLatitudeRef"))
    if selected_fix.longitude is None:
        tag_names.extend(("GPSLongitude", "GPSLongitudeRef"))
    if selected_fix.altitude is None:
        tag_names.extend(("GPSAltitude", "GPSAltitudeRef"))
    if not track_log.is_date:
        tag_names.append("GPSDateStamp")
    if geotag_track_motion_enabled(track_log):
        if selected_fix.track is None:
            tag_names.extend(("GPSTrack", "GPSTrackRef"))
        if selected_fix.speed is None:
            tag_names.extend(("GPSSpeed", "GPSSpeedRef"))
    if "orient" in track_log.has and selected_fix.image_direction is None:
        tag_names.extend(("GPSImgDirection", "GPSImgDirectionRef"))
    if "dop" in track_log.has and dop_values is None:
        tag_names.extend(("GPSMeasureMode", "GPSDOP"))
    return tuple(tag_names)


def date_time_only_selected_fix(target_time: float) -> GeotagSelectedFix:
    return GeotagSelectedFix(
        time_seconds=target_time,
        latitude=None,
        longitude=None,
        altitude=None,
        speed=None,
        track=None,
        image_direction=None,
        pitch=None,
        roll=None,
        hdop=None,
        pdop=None,
        vdop=None,
        selection_mode="date_time_only",
    )


def select_geotag_fix(
    target_time: float,
    points: tuple[GeotagTrackPoint, ...],
    geo_max_ext_seconds: float,
    geo_max_int_seconds: float,
) -> GeotagApplicationResult:
    times = tuple(point.time_seconds for point in points)
    first = points[0]
    last = points[-1]
    if len(points) == 1 and target_time == first.time_seconds:
        return selected_point_result(first, "exact")
    if target_time < first.time_seconds:
        if target_time < first.time_seconds - geo_max_ext_seconds:
            return geotag_application_error("too_far_before_track", "Time is too far before track")
        return selected_point_result(first, "before_track_extension")
    if target_time > last.time_seconds:
        if target_time > last.time_seconds + geo_max_ext_seconds:
            return geotag_application_error("too_far_beyond_track", "Time is too far beyond track")
        return selected_point_result(last, "after_track_extension")

    insertion_index = bisect_left(times, target_time)
    exact_match = insertion_index < len(points) and times[insertion_index] == target_time
    left_index = max(0, insertion_index - 1)
    if exact_match and insertion_index < len(points) - 1:
        left_index = insertion_index
    right_index = min(len(points) - 1, left_index + 1)
    left = points[left_index]
    right = points[right_index]
    nearest = left if target_time - left.time_seconds < right.time_seconds - target_time else right
    if right.time_seconds - left.time_seconds > geo_max_int_seconds:
        if abs(target_time - nearest.time_seconds) > geo_max_ext_seconds:
            return geotag_application_error(
                "too_far_from_nearest_fix",
                "Time is too far from nearest GPS fix",
            )
        return selected_point_result(nearest, "nearest_gap_extension")
    return interpolated_result(
        target_time,
        left,
        right,
        "exact" if exact_match else "interpolated",
        points,
        left_index,
        right_index,
        geo_max_int_seconds,
    )


def selected_point_result(
    point: GeotagTrackPoint,
    selection_mode: GeotagFixSelectionMode,
) -> GeotagApplicationResult:
    latitude = track_value_float(point.lat)
    longitude = track_value_float(point.lon)
    altitude = optional_track_value_float(point.alt)
    if latitude is None or longitude is None:
        return geotag_application_error(
            "unsupported_coordinate_value",
            "Track point coordinate is not numeric",
        )
    return GeotagApplicationResult(
        status="ok",
        selected_fix=GeotagSelectedFix(
            time_seconds=point.time_seconds,
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
            speed=optional_track_value_float(point.speed),
            track=optional_track_value_float(point.track),
            image_direction=optional_track_value_float(point.direction),
            pitch=optional_track_value_float(point.pitch),
            roll=optional_track_value_float(point.roll),
            hdop=optional_track_value_float(point.hdop),
            pdop=optional_track_value_float(point.pdop),
            vdop=optional_track_value_float(point.vdop),
            selection_mode=selection_mode,
        ),
        write_plan=None,
        warning=None,
    )


def interpolated_result(
    target_time: float,
    left: GeotagTrackPoint,
    right: GeotagTrackPoint,
    selection_mode: GeotagFixSelectionMode,
    points: tuple[GeotagTrackPoint, ...] | None = None,
    left_index: int | None = None,
    right_index: int | None = None,
    max_scan_seconds: float | None = None,
) -> GeotagApplicationResult:
    left_latitude = track_value_float(left.lat)
    right_latitude = track_value_float(right.lat)
    left_longitude = track_value_float(left.lon)
    right_longitude = track_value_float(right.lon)
    if (
        left_latitude is None
        or right_latitude is None
        or left_longitude is None
        or right_longitude is None
    ):
        return geotag_application_error(
            "unsupported_coordinate_value",
            "Track point coordinate is not numeric",
        )
    fraction = (
        0.0
        if right.time_seconds == left.time_seconds
        else (target_time - left.time_seconds) / (right.time_seconds - left.time_seconds)
    )
    altitude = interpolated_altitude_value(
        target_time,
        left,
        right,
        fraction,
        points,
        left_index,
        right_index,
        max_scan_seconds,
    )
    return GeotagApplicationResult(
        status="ok",
        selected_fix=GeotagSelectedFix(
            time_seconds=target_time,
            latitude=interpolate_number(left_latitude, right_latitude, fraction),
            longitude=interpolate_number(left_longitude, right_longitude, fraction),
            altitude=altitude,
            speed=interpolated_optional_value(left.speed, right.speed, fraction),
            track=interpolated_cyclical_value(left.track, right.track, fraction, 360.0),
            image_direction=interpolated_cyclical_value(
                left.direction,
                right.direction,
                fraction,
                360.0,
            ),
            pitch=interpolated_cyclical_value(left.pitch, right.pitch, fraction, 180.0),
            roll=interpolated_cyclical_value(left.roll, right.roll, fraction, 180.0),
            hdop=interpolated_optional_value(left.hdop, right.hdop, fraction),
            pdop=interpolated_optional_value(left.pdop, right.pdop, fraction),
            vdop=interpolated_optional_value(left.vdop, right.vdop, fraction),
            selection_mode=selection_mode,
        ),
        write_plan=None,
        warning=None,
    )


def interpolated_altitude_value(
    target_time: float,
    left: GeotagTrackPoint,
    right: GeotagTrackPoint,
    fraction: float,
    points: tuple[GeotagTrackPoint, ...] | None,
    left_index: int | None,
    right_index: int | None,
    max_scan_seconds: float | None,
) -> float | None:
    altitude = interpolated_optional_value(left.alt, right.alt, fraction)
    if altitude is not None:
        return altitude
    if points is None or left_index is None or right_index is None or max_scan_seconds is None:
        return None
    left_altitude = optional_track_value_float(left.alt)
    right_altitude = optional_track_value_float(right.alt)
    left_time = left.time_seconds
    right_time = right.time_seconds
    if left_altitude is None:
        outward_left = scan_outward_track_point_with_altitude(
            points,
            left_index,
            -1,
            max_scan_seconds,
        )
        if outward_left is None:
            return None
        left_time = outward_left.time_seconds
        left_altitude = optional_track_value_float(outward_left.alt)
    if right_altitude is None:
        outward_right = scan_outward_track_point_with_altitude(
            points,
            right_index,
            1,
            max_scan_seconds,
        )
        if outward_right is None:
            return None
        right_time = outward_right.time_seconds
        right_altitude = optional_track_value_float(outward_right.alt)
    if left_altitude is None or right_altitude is None:
        return None
    adjusted_fraction = (
        0.0 if right_time == left_time else (target_time - left_time) / (right_time - left_time)
    )
    return interpolate_number(left_altitude, right_altitude, adjusted_fraction)


def scan_outward_track_point_with_altitude(
    points: tuple[GeotagTrackPoint, ...],
    start_index: int,
    direction: Literal[-1, 1],
    max_scan_seconds: float,
) -> GeotagTrackPoint | None:
    start_time = points[start_index].time_seconds
    index = start_index + direction
    while 0 <= index < len(points):
        point = points[index]
        if abs(point.time_seconds - start_time) > max_scan_seconds:
            return None
        if optional_track_value_float(point.alt) is not None:
            return point
        index += direction
    return None


def interpolated_optional_value(
    left: str | float | None,
    right: str | float | None,
    fraction: float,
) -> float | None:
    left_value = optional_track_value_float(left)
    right_value = optional_track_value_float(right)
    if left_value is None or right_value is None:
        return None
    return interpolate_number(left_value, right_value, fraction)


def interpolated_cyclical_value(
    left: str | float | None,
    right: str | float | None,
    fraction: float,
    wrap_maximum: float,
) -> float | None:
    left_value = optional_track_value_float(left)
    right_value = optional_track_value_float(right)
    if left_value is None or right_value is None:
        return None
    if abs(right_value - left_value) > 180:
        if left_value < right_value:
            left_value += 360
        else:
            right_value += 360
    interpolated = interpolate_number(left_value, right_value, fraction)
    if interpolated >= wrap_maximum:
        return interpolated - 360
    return interpolated


def interpolate_number(left: float, right: float, fraction: float) -> float:
    return right * fraction + left * (1 - fraction)


def track_value_float(value: str | float) -> float | None:
    if isinstance(value, float):
        return value
    try:
        return float(value)
    except ValueError:
        return None


def optional_track_value_float(value: str | float | None) -> float | None:
    if value is None:
        return None
    return track_value_float(value)


def geotag_application_error(
    status: GeotagApplicationStatus,
    warning: str,
) -> GeotagApplicationResult:
    return GeotagApplicationResult(
        status=status,
        selected_fix=None,
        write_plan=None,
        warning=warning,
    )


def geotag_target_time(request: GeotagApplicationRequest) -> float:
    target_time = request.geotime_seconds + geosync_offset_for_time(request)
    if request.track_log.no_date:
        return target_time % 86400
    return target_time


def geosync_offset_for_time(request: GeotagApplicationRequest) -> float:
    if len(request.geosync_points) < 2:
        return request.geosync_offset_seconds
    points = tuple(sorted(request.geosync_points, key=lambda point: point.image_time_seconds))
    if request.geotime_seconds <= points[0].image_time_seconds:
        left = points[0]
        right = points[1]
    elif request.geotime_seconds >= points[-1].image_time_seconds:
        left = points[-2]
        right = points[-1]
    else:
        left = points[0]
        right = points[-1]
        for index, point in enumerate(points[1:], start=1):
            if request.geotime_seconds <= point.image_time_seconds:
                left = points[index - 1]
                right = point
                break
    fraction = (
        0.0
        if right.image_time_seconds == left.image_time_seconds
        else (request.geotime_seconds - left.image_time_seconds)
        / (right.image_time_seconds - left.image_time_seconds)
    )
    return right.offset_seconds * fraction + left.offset_seconds * (1 - fraction)
