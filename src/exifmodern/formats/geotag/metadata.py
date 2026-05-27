"""Metadata-file Geotag track-source adapter.

The upstream LoadTrackLog flow falls back to extracting GPS metadata from readable
files when no text track-log format matches.  This module keeps that source
adapter separate from text track parsers.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.garmin.metadata_transaction_plan import (
    GarminDataMessagePlan,
    GarminDecodedFieldPlan,
    build_garmin_metadata_transaction_plan,
)
from exifmodern.formats.garmin.read_graph_adapter import is_fit_prefix
from exifmodern.media_source import FileMediaSource
from exifmodern.read_graph import ReadGraph, TagValue, build_read_graph

type MetadataTrackValue = str | float

FIT_SIGNATURE_PREFIX_SIZE = 12

GPS_DATE_TIME_PATTERN = re.compile(
    r"^(\d{4}):(\d{2}):(\d{2})\s+(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)(?:Z)?$"
)
GPS_DMS_PATTERN = re.compile(
    r"""^\s*
    (?P<deg>[-+]?\d+(?:\.\d+)?)\s+deg(?:rees?)?\s+
    (?P<min>\d+(?:\.\d+)?)'
    (?:\s+(?P<sec>\d+(?:\.\d+)?)")?
    (?:\s+(?P<ref>[NSEW]))?
    \s*$""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class MetadataTrackPoint:
    time_seconds: float
    lat: MetadataTrackValue
    lon: MetadataTrackValue
    alt: MetadataTrackValue | None
    speed: MetadataTrackValue | None = None
    track: MetadataTrackValue | None = None


@dataclass(frozen=True)
class MetadataTrackLog:
    points: tuple[MetadataTrackPoint, ...]
    has: tuple[str, ...]


def load_metadata_track_log_file(path: Path) -> MetadataTrackLog | None:
    source = FileMediaSource(path)
    if is_fit_prefix(source.prefix(FIT_SIGNATURE_PREFIX_SIZE), path):
        return metadata_track_log_from_garmin_fit(source.read_full())
    try:
        graph = build_read_graph(path)
    except ValueError:
        return None
    return metadata_track_log_from_graph(graph)


def metadata_track_log_from_graph(graph: ReadGraph) -> MetadataTrackLog | None:
    time_seconds = metadata_time_seconds(graph)
    latitude = metadata_coordinate(graph, "GPSLatitude")
    longitude = metadata_coordinate(graph, "GPSLongitude")
    if time_seconds is None or latitude is None or longitude is None:
        return None
    altitude = metadata_altitude(graph)
    has = ["pos"]
    if altitude is not None:
        has.append("alt")
    return MetadataTrackLog(
        points=(MetadataTrackPoint(time_seconds, latitude, longitude, altitude),),
        has=tuple(has),
    )


def metadata_track_log_from_garmin_fit(data: bytes) -> MetadataTrackLog | None:
    plan = build_garmin_metadata_transaction_plan(data, extract_embedded=True)
    points = tuple(
        point
        for message in plan.data_messages
        for point in (metadata_track_point_from_garmin_message(message),)
        if point is not None
    )
    if not points:
        return None
    has = ["pos"]
    if any(point.alt is not None for point in points):
        has.append("alt")
    if any(point.speed is not None or point.track is not None for point in points):
        has.append("track")
    return MetadataTrackLog(points=points, has=tuple(has))


def metadata_track_point_from_garmin_message(
    message: GarminDataMessagePlan,
) -> MetadataTrackPoint | None:
    time_seconds = garmin_message_time_seconds(message)
    latitude = garmin_numeric_field(message.fields, "GPSLatitude")
    longitude = garmin_numeric_field(message.fields, "GPSLongitude")
    if time_seconds is None or latitude is None or longitude is None:
        return None
    speed = garmin_numeric_field(message.fields, "GPSSpeed")
    return MetadataTrackPoint(
        time_seconds=time_seconds,
        lat=latitude,
        lon=longitude,
        alt=garmin_metadata_value_field(message.fields, "GPSAltitude"),
        speed=speed / 1.852 if speed is not None else None,
        track=garmin_metadata_value_field(message.fields, "GPSTrack"),
    )


def garmin_message_time_seconds(message: GarminDataMessagePlan) -> float | None:
    gps_time = garmin_numeric_field(message.fields, "GPSDateTime")
    if gps_time is not None:
        return gps_time
    return garmin_numeric_field(message.fields, "TimeStamp")


def garmin_numeric_field(
    fields: tuple[GarminDecodedFieldPlan, ...],
    field_name: str,
) -> float | None:
    value = garmin_metadata_value_field(fields, field_name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def garmin_metadata_value_field(
    fields: tuple[GarminDecodedFieldPlan, ...],
    field_name: str,
) -> MetadataTrackValue | None:
    for field in fields:
        if field.field_name == field_name and isinstance(field.value, (str, int, float)):
            return field.value
    return None


def metadata_time_seconds(graph: ReadGraph) -> float | None:
    composite_date_time = tag_value(graph, "Composite", "GPSDateTime")
    if isinstance(composite_date_time, str):
        parsed = gps_date_time_seconds(composite_date_time)
        if parsed is not None:
            return parsed
    date_stamp = tag_value(graph, "GPS", "GPSDateStamp")
    time_stamp = tag_value(graph, "GPS", "GPSTimeStamp")
    if isinstance(date_stamp, str) and isinstance(time_stamp, str):
        return gps_date_time_seconds(f"{date_stamp} {time_stamp}Z")
    return None


def metadata_coordinate(
    graph: ReadGraph,
    coordinate_name: str,
) -> float | None:
    coordinate = tag_value(graph, "GPS", coordinate_name)
    if isinstance(coordinate, str):
        return gps_coordinate_degrees(coordinate, None)
    if isinstance(coordinate, (int, float)) and not isinstance(coordinate, bool):
        return float(coordinate)
    composite_value = tag_value(graph, "Composite", coordinate_name)
    if isinstance(composite_value, str):
        return gps_coordinate_degrees(composite_value, None)
    return None


def metadata_altitude(graph: ReadGraph) -> str | float | None:
    altitude = tag_value(graph, "GPS", "GPSAltitude")
    if isinstance(altitude, str):
        return altitude_value_text(altitude)
    if isinstance(altitude, (int, float)) and not isinstance(altitude, bool):
        return float(altitude)
    composite = tag_value(graph, "Composite", "GPSAltitude")
    if isinstance(composite, str):
        return altitude_value_text(composite)
    return None


def gps_date_time_seconds(value: str) -> float | None:
    match = GPS_DATE_TIME_PATTERN.match(value.strip())
    if match is None:
        return None
    return calendar.timegm(
        (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            0,
        )
    ) + float(match.group(6))


def gps_coordinate_degrees(value: str, reference: str | None) -> float | None:
    match = GPS_DMS_PATTERN.match(value)
    if match is not None:
        degrees = float(match.group("deg"))
        minutes = float(match.group("min"))
        seconds_text = match.group("sec")
        seconds = float(seconds_text) if seconds_text is not None else 0.0
        parsed = abs(degrees) + minutes / 60 + seconds / 3600
        suffix = match.group("ref") or gps_reference_suffix(reference)
        if suffix in {"S", "W"}:
            return -parsed
        return parsed if degrees >= 0 else -parsed
    try:
        parsed_float = float(value)
    except ValueError:
        return None
    suffix = gps_reference_suffix(reference)
    if suffix in {"S", "W"}:
        return -abs(parsed_float)
    return parsed_float


def gps_reference_suffix(reference: str | None) -> str | None:
    if reference is None:
        return None
    return {"North": "N", "South": "S", "East": "E", "West": "W"}.get(reference, reference)


def altitude_value_text(value: str) -> str | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    if match is None:
        return None
    if "Below" in value:
        return f"-{match.group(0).removeprefix('-')}"
    return match.group(0)


def tag_value(graph: ReadGraph, group: str, name: str) -> TagValue | None:
    for tag in graph.tags:
        if tag.provenance.group == group and tag.name == name:
            return tag.value
    return None
