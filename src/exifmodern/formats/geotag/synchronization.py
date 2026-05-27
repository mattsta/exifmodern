"""Geotag synchronization primitives translated from upstream ConvertGeosync."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.exiftool_compat.core import get_unix_time
from exifmodern.formats.jpeg.container import read_exif_ifd_tags, read_gps_ifd_tags
from exifmodern.json_types import JsonValue

type GeosyncOffsetStatus = Literal["ok", "invalid", "requires_context"]
type GeosyncConversionMode = Literal["constant_offset", "time_vector", "time_vector_sequence"]

GEOSYNC_NUMBER_PATTERN = re.compile(r"(?=\d|\.\d)\d*(?:\.\d*)?")
DATED_TIMESTAMP_PATTERN = re.compile(r"^(\d+:\d+:\d+)\s+\d+")
SECONDS_PER_DAY = 24 * 3600


@dataclass(frozen=True)
class GeosyncPoint:
    image_time_seconds: float
    offset_seconds: float


@dataclass(frozen=True)
class GeosyncConversionResult:
    status: GeosyncOffsetStatus
    mode: GeosyncConversionMode | None
    offset_seconds: float | None
    points: tuple[GeosyncPoint, ...]
    times: tuple[float, ...]
    warning: str | None


@dataclass(frozen=True)
class GeosyncFileReferenceTimes:
    gps_time: str
    image_time: str
    image_time_tag: str


type ConstantGeosyncOffsetResult = GeosyncConversionResult


def convert_geosync_value(value: str) -> GeosyncConversionResult:
    return convert_geosync_value_with_state(value, empty_geosync_state(), False)


def convert_geosync_values(values: tuple[str, ...]) -> GeosyncConversionResult:
    state = empty_geosync_state()
    result: GeosyncConversionResult | None = None
    for value in values:
        result = convert_geosync_value_with_state(value, state, True)
        if result.status != "ok":
            return result
        state = GeosyncState(
            offset_seconds=result.offset_seconds,
            points=result.points,
            times=result.times,
        )
    if result is None:
        return invalid_geosync_time_vector("Invalid value (please refer to geotag documentation)")
    return result


def convert_geosync_values_resolving_file_references(
    values: tuple[str, ...],
) -> GeosyncConversionResult:
    """Convert Geosync values, resolving source-backed file-reference vectors.

    The upstream ConvertGeosync flow treats ``GPS_TIME@FILE`` and bare ``FILE`` as
    synchronization vectors when FILE exists.  This public route resolves only
    existing JPEG/EXIF files through the native readers already used by the
    geotag workflow; unsupported files remain precise invalid vectors.
    """

    state = empty_geosync_state()
    result: GeosyncConversionResult | None = None
    for value in values:
        result = convert_geosync_value_with_state(
            value,
            state,
            True,
            resolve_file_references=True,
        )
        if result.status != "ok":
            return result
        state = GeosyncState(
            offset_seconds=result.offset_seconds,
            points=result.points,
            times=result.times,
        )
    if result is None:
        return invalid_geosync_time_vector("Invalid value (please refer to geotag documentation)")
    return result


@dataclass(frozen=True)
class GeosyncState:
    offset_seconds: float | None
    points: tuple[GeosyncPoint, ...]
    times: tuple[float, ...]


def empty_geosync_state() -> GeosyncState:
    return GeosyncState(offset_seconds=None, points=(), times=())


def convert_geosync_value_with_state(
    value: str,
    state: GeosyncState,
    sequence_mode: bool,
    *,
    resolve_file_references: bool = False,
) -> GeosyncConversionResult:
    if "@" in value:
        gps_time, image_time = split_geosync_time_vector(value)
        if (
            resolve_file_references
            and gps_time is not None
            and image_time is not None
            and looks_like_context_file_reference(image_time)
            and Path(image_time).is_file()
        ):
            return convert_geosync_file_reference_vector(
                Path(image_time),
                state,
                sequence_mode,
                gps_time=gps_time,
            )
        return convert_geosync_time_vector(value, state, sequence_mode)
    if resolve_file_references and looks_like_standalone_geosync_file_reference(value):
        sync_file = Path(value)
        if sync_file.is_file():
            return convert_geosync_file_reference_vector(
                sync_file,
                state,
                sequence_mode,
                gps_time=None,
            )
    return convert_constant_geosync_offset(value)


def convert_constant_geosync_offset(value: str) -> ConstantGeosyncOffsetResult:
    """Convert upstream simple Geosync time-difference syntax to seconds.

    This intentionally covers only the source branch documented as
    `"[+-]DD MM:HH:SS.ss"`. Values that require an image file, GPS timestamp,
    or existing upstream `Geosync` NEW_VALUE state remain service-level work.
    """

    if geosync_value_requires_context(value):
        return GeosyncConversionResult(
            status="requires_context",
            mode=None,
            offset_seconds=None,
            points=(),
            times=(),
            warning=None,
        )
    components = tuple(float(match) for match in GEOSYNC_NUMBER_PATTERN.findall(value) if match)
    if not components:
        return GeosyncConversionResult(
            status="invalid",
            mode="constant_offset",
            offset_seconds=None,
            points=(),
            times=(),
            warning="Invalid value (please refer to geotag documentation)",
        )
    seconds = weighted_seconds_from_geosync_components(components)
    if value.lstrip().startswith("-"):
        seconds = -seconds
    return GeosyncConversionResult(
        status="ok",
        mode="constant_offset",
        offset_seconds=seconds,
        points=(),
        times=(),
        warning=None,
    )


def geosync_value_requires_context(value: str) -> bool:
    return "@" in value


def weighted_seconds_from_geosync_components(components: tuple[float, ...]) -> float:
    total = 0.0
    remaining = list(components)
    for multiplier in (1.0, 60.0, 3600.0, 86400.0):
        if not remaining:
            break
        total += multiplier * remaining.pop()
    return total


def convert_geosync_time_vector(
    value: str,
    state: GeosyncState | None = None,
    sequence_mode: bool = False,
) -> GeosyncConversionResult:
    active_state = empty_geosync_state() if state is None else state
    gps_time, image_time = split_geosync_time_vector(value)
    if gps_time is None or image_time is None:
        return invalid_geosync_time_vector("Invalid value (please refer to geotag documentation)")
    if looks_like_context_file_reference(image_time):
        return GeosyncConversionResult(
            status="requires_context",
            mode=None,
            offset_seconds=None,
            points=(),
            times=(),
            warning=None,
        )
    normalized = normalize_geosync_time_pair(gps_time, image_time)
    no_date = normalized is None
    gps_date_time, image_date_time = (
        (f"1970:01:01 {gps_time}", f"1970:01:01 {image_time}") if normalized is None else normalized
    )
    image_seconds = unix_time_seconds(image_date_time)
    if image_seconds is None:
        return invalid_geosync_time_vector(f"Invalid image time '{image_time}'")
    gps_seconds = unix_time_seconds(gps_date_time)
    if gps_seconds is None:
        return invalid_geosync_time_vector(f"Invalid GPS time '{gps_time}'")
    gps_seconds, image_seconds = adjust_date_less_geosync_pair(
        gps_time,
        gps_date_time,
        gps_seconds,
        image_time,
        image_date_time,
        image_seconds,
    )
    offset_seconds = gps_seconds - image_seconds
    point = GeosyncPoint(image_time_seconds=image_seconds, offset_seconds=offset_seconds)
    points = (
        active_state.points if no_date else sorted_geosync_points((*active_state.points, point))
    )
    times = tuple(point.image_time_seconds for point in points) if len(points) > 1 else ()
    return GeosyncConversionResult(
        status="ok",
        mode="time_vector_sequence" if sequence_mode else "time_vector",
        offset_seconds=offset_seconds,
        points=points,
        times=times,
        warning=None,
    )


def sorted_geosync_points(points: tuple[GeosyncPoint, ...]) -> tuple[GeosyncPoint, ...]:
    point_by_time = {point.image_time_seconds: point for point in points}
    return tuple(point_by_time[time] for time in sorted(point_by_time))


def split_geosync_time_vector(value: str) -> tuple[str | None, str | None]:
    gps_time, separator, image_time = value.partition("@")
    if not separator:
        return None, None
    gps_time = gps_time.strip()
    image_time = image_time.strip()
    if not gps_time or not image_time:
        return None, None
    return gps_time, image_time


def looks_like_context_file_reference(value: str) -> bool:
    return not timestamp_has_time_separator(value)


def looks_like_standalone_geosync_file_reference(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped) and (not stripped[0].isdigit() or ":" not in stripped)


def timestamp_has_time_separator(value: str) -> bool:
    return ":" in value


def normalize_geosync_time_pair(gps_time: str, image_time: str) -> tuple[str, str] | None:
    image_date = leading_exif_date(image_time)
    gps_date = leading_exif_date(gps_time)
    if image_date is not None:
        image_date_time = image_time
        gps_date_time = gps_time if gps_date is not None else f"{image_date} {gps_time}"
    elif gps_date is not None:
        image_date_time = f"{gps_date} {image_time}"
        gps_date_time = gps_time
    else:
        return None
    return gps_date_time, image_date_time


def leading_exif_date(value: str) -> str | None:
    match = DATED_TIMESTAMP_PATTERN.match(value)
    return None if match is None else match.group(1)


def unix_time_seconds(value: str) -> float | None:
    timestamp = get_unix_time([value, 1])
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        return float(timestamp)
    return None


def convert_geosync_file_reference_vector(
    sync_file: Path,
    state: GeosyncState | None = None,
    sequence_mode: bool = False,
    *,
    gps_time: str | None,
) -> GeosyncConversionResult:
    active_state = empty_geosync_state() if state is None else state
    times = geosync_file_reference_times(sync_file, gps_time=gps_time)
    if isinstance(times, GeosyncConversionResult):
        return times
    return convert_geosync_time_vector(
        f"{times.gps_time}@{times.image_time}",
        active_state,
        sequence_mode,
    )


def geosync_file_reference_times(
    sync_file: Path,
    *,
    gps_time: str | None,
) -> GeosyncFileReferenceTimes | GeosyncConversionResult:
    try:
        exif_tags = read_exif_ifd_tags(sync_file)
        gps_tags = read_gps_ifd_tags(sync_file)
    except ValueError as exc:
        return invalid_geosync_time_vector(f"Error reading Geosync file '{sync_file}': {exc}")

    resolved_gps_time = gps_time or geosync_file_gps_time(gps_tags)
    if resolved_gps_time is None:
        return invalid_geosync_time_vector(f"No GPSTimeStamp in '{sync_file}'")
    image_time = geosync_file_image_time(exif_tags)
    if image_time is None:
        return invalid_geosync_time_vector(f"No image timestamp in '{sync_file}'")
    return GeosyncFileReferenceTimes(
        gps_time=resolved_gps_time,
        image_time=image_time[1],
        image_time_tag=image_time[0],
    )


def geosync_file_gps_time(gps_tags: Mapping[str, JsonValue]) -> str | None:
    gps_date_time = gps_tags.get("GPSDateTime")
    if isinstance(gps_date_time, str):
        return gps_date_time
    gps_time = gps_tags.get("GPSTimeStamp")
    if not isinstance(gps_time, str):
        return None
    gps_date = gps_tags.get("GPSDateStamp")
    if isinstance(gps_date, str):
        return f"{gps_date} {gps_time}"
    return f"{gps_time}Z"


def geosync_file_image_time(exif_tags: Mapping[str, JsonValue]) -> tuple[str, str] | None:
    for tag in (
        "SubSecDateTimeOriginal",
        "SubSecCreateDate",
        "SubSecModifyDate",
        "DateTimeOriginal",
        "CreateDate",
        "ModifyDate",
    ):
        value = exif_tags.get(tag)
        if isinstance(value, str):
            return tag, value
    return None


def adjust_date_less_geosync_pair(
    gps_time: str,
    gps_date_time: str,
    gps_seconds: float,
    image_time: str,
    image_date_time: str,
    image_seconds: float,
) -> tuple[float, float]:
    if gps_date_time == gps_time and image_date_time == image_time:
        return gps_seconds, image_seconds
    difference = (image_seconds - gps_seconds) % SECONDS_PER_DAY
    if difference > 12 * 3600:
        difference -= SECONDS_PER_DAY
    if difference < -12 * 3600:
        difference += SECONDS_PER_DAY
    if gps_date_time != gps_time:
        return image_seconds - difference, image_seconds
    return gps_seconds, gps_seconds + difference


def invalid_geosync_time_vector(warning: str) -> GeosyncConversionResult:
    return GeosyncConversionResult(
        status="invalid",
        mode="time_vector",
        offset_seconds=None,
        points=(),
        times=(),
        warning=warning,
    )
