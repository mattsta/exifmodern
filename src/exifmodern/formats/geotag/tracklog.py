"""Typed Geotag track-log loader primitives translated from LoadTrackLog."""

from __future__ import annotations

import calendar
import csv
import io
import re
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.geotag.metadata import MetadataTrackLog, load_metadata_track_log_file
from exifmodern.media_source import FileMediaSource

type GeotagTrackLogStatus = Literal["ok", "invalid"]
type GeotagTrackLogInputKind = Literal["value", "file"]
type GeotagTrackLogFormat = Literal[
    "combined",
    "datetime_only",
    "metadata",
    "XML",
    "NMEA",
    "Winplus",
    "Bramor",
    "CSV",
    "JSON",
    "IGC",
]
type GeotagTrackValue = str | float
type CsvColumnKind = Literal[
    "ignore",
    "datetime",
    "date",
    "time",
    "runtime",
    "lat",
    "latref",
    "lon",
    "lonref",
    "alt",
    "speed",
    "track",
    "pitch",
    "roll",
    "dir",
]

TRACK_LOG_PROBE_SIZE = 4096
GARMIN_FIT_SIGNATURE_PREFIX_SIZE = 12
BINARY_METADATA_PREFIXES = (
    b"\xff\xd8",  # JPEG
    b"\x89PNG\r\n\x1a\n",
    b"II*\x00",
    b"MM\x00*",
    b"II+\x00",
    b"MM\x00+",
)

XML_TIME_PATTERN = re.compile(r"^(\d{4})-(\d+)-(\d+)T(\d+):(\d+):(\d+)(\.\d+)?(.*)")
TIMEZONE_PATTERN = re.compile(r"^([-+])(\d+):(\d{2})\b|^([-+])(\d{2})(\d{2})?\b")
PMGNTRK_PATTERN = re.compile(
    r"^\$PMGNTRK,(\d+)(\d{2}\.\d+),([NS]),(\d+)(\d{2}\.\d+),([EW]),"
    r"(-?\d+\.?\d*),([MF]),(\d{2})(\d{2})(\d+(\.\d*)?),A,(?:[^,]*,(\d{2})(\d{2})(\d+))?"
)
RMC_PATTERN = re.compile(
    r"^\$[A-Z]{2}RMC,(\d{2})(\d{2})(\d+(\.\d*)?),A?,"
    r"(\d*?)(\d{1,2}\.\d+),([NS]),(\d*?)(\d{1,2}\.\d+),([EW]),"
    r"(\d*\.?\d*),(\d*\.?\d*),(\d{2})(\d{2})(\d+)"
)
GGA_PATTERN = re.compile(
    r"^\$[A-Z]{2}GGA,(\d{2})(\d{2})(\d+(\.\d*)?),"
    r"(\d*?)(\d{1,2}\.\d+),([NS]),(\d*?)(\d{1,2}\.\d+),([EW]),"
    r"[1-6]?,(\d+)?,(\.\d+|\d+\.?\d*)?,(-?\d+\.?\d*)?,M?"
)
GLL_PATTERN = re.compile(
    r"^\$[A-Z]{2}GLL,(\d*?)(\d{1,2}\.\d+),([NS]),"
    r"(\d*?)(\d{1,2}\.\d+),([EW]),(\d{2})(\d{2})(\d+(\.\d*)?),A"
)
GSA_PATTERN = re.compile(
    r"^\$[A-Z]{2}GSA,[AM],([23]),((?:\d*,){11}(?:\d*)),"
    r"(\d+\.?\d*|\.\d+)?,(\d+\.?\d*|\.\d+)?,(\d+\.?\d*|\.\d+)?\*"
)
ZDA_PATTERN = re.compile(r"^\$[A-Z]{2}ZDA,(\d{2})(\d{2})(\d{2}(\.\d*)?),(\d+),(\d+),(\d+)")
PTNTHPR_PATTERN = re.compile(r"^\$PTNTHPR,(-?[\d.]+),[MNO],(-?[\d.]+),[MNO],(-?[\d.]+),[MNO]")
WINPLUS_PATTERN = re.compile(
    r"^TP,D,\s*([-+]?\d+\.\d*),\s*([-+]?\d+\.\d*),\s*"
    r"(\d+)/(\d+)/(\d{4}),\s*(\d+):(\d+):(\d+)"
)
BRAMOR_PATTERN = re.compile(
    r"^\s+\S+\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
    r"(\d{2})/(\d{2})/(\d{4})\s+(\d+):(\d+):(\d+(?:\.\d+)?)\s+"
    r"(\S+)\s+(\S+)\s+(\S+)\s+ypr\s*$"
)
IGC_DATE_PATTERN = re.compile(r"^HFDTE(?:DATE:)?(\d{2})(\d{2})(\d{2})")
IGC_FIX_PATTERN = re.compile(
    r"^B(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{3})([NS])"
    r"(\d{3})(\d{2})(\d{3})([EW])([AV])(\d{5})(\d{5})"
)
JSON_FIELD_PATTERN = re.compile(
    r'^\s*"(latitudeE7|longitudeE7|latE7|lngE7|timestamp|startTime|point|'
    r'durationMinutesOffsetFromStartTime|time)"\s*:\s*(?:"([^"]*)"|([^,\r\n]+)),?\s*$'
)
NMEA_TIMESTAMP_KINDS = frozenset(("RMC", "GGA", "GLL", "ZDA", "PMGNTRK"))
SECONDS_PER_DAY = 24 * 3600
NMEA_DATE_INHERITANCE_WINDOW_SECONDS = 10
NMEA_FIX_BOUNDARY_SECONDS = 10
DJI_FILENAME_TIME_PATTERN = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[^/\\]+(\d{2})-(\d{2})-(\d{2})[^/\\]*$"
)
CSV_SPEED_CONVERSION_TO_KNOTS = {
    "km/h": 1.852,
    "mph": 1.150779448,
    "m/s": 0.514444,
}


@dataclass(frozen=True)
class GeotagTrackPoint:
    time_seconds: float
    lat: GeotagTrackValue
    lon: GeotagTrackValue
    alt: GeotagTrackValue | None
    first: bool
    speed: GeotagTrackValue | None = None
    track: GeotagTrackValue | None = None
    direction: GeotagTrackValue | None = None
    pitch: GeotagTrackValue | None = None
    roll: GeotagTrackValue | None = None
    hdop: GeotagTrackValue | None = None
    pdop: GeotagTrackValue | None = None
    vdop: GeotagTrackValue | None = None


@dataclass(frozen=True)
class GeotagTrackLog:
    format_name: GeotagTrackLogFormat
    points: tuple[GeotagTrackPoint, ...]
    has: tuple[str, ...]
    is_date: bool
    no_date: bool
    date_time_only: bool


@dataclass(frozen=True)
class GeotagTrackLogLoadResult:
    status: GeotagTrackLogStatus
    track_log: GeotagTrackLog | None
    warning: str | None


@dataclass
class NmeaFix:
    lat: GeotagTrackValue | None = None
    lon: GeotagTrackValue | None = None
    alt: GeotagTrackValue | None = None
    speed: GeotagTrackValue | None = None
    track: GeotagTrackValue | None = None
    direction: GeotagTrackValue | None = None
    pitch: GeotagTrackValue | None = None
    roll: GeotagTrackValue | None = None
    hdop: GeotagTrackValue | None = None
    pdop: GeotagTrackValue | None = None
    vdop: GeotagTrackValue | None = None
    is_date: bool = False

    def merge_missing(self, other: NmeaFix) -> None:
        if self.lat is None:
            self.lat = other.lat
        if self.lon is None:
            self.lon = other.lon
        if self.alt is None:
            self.alt = other.alt
        if self.speed is None:
            self.speed = other.speed
        if self.track is None:
            self.track = other.track
        if self.direction is None:
            self.direction = other.direction
        if self.pitch is None:
            self.pitch = other.pitch
        if self.roll is None:
            self.roll = other.roll
        if self.hdop is None:
            self.hdop = other.hdop
        if self.pdop is None:
            self.pdop = other.pdop
        if self.vdop is None:
            self.vdop = other.vdop

    def has_position(self) -> bool:
        return self.lat is not None and self.lon is not None

    def to_track_point(self, time_seconds: float) -> GeotagTrackPoint:
        return GeotagTrackPoint(
            time_seconds=time_seconds,
            lat=self.lat if self.lat is not None else "",
            lon=self.lon if self.lon is not None else "",
            alt=self.alt,
            first=False,
            speed=self.speed,
            track=self.track,
            direction=self.direction,
            pitch=self.pitch,
            roll=self.roll,
            hdop=self.hdop,
            pdop=self.pdop,
            vdop=self.vdop,
        )


@dataclass(frozen=True)
class NmeaSentence:
    kind: str
    seconds: float | None
    date_seconds: int | None
    fix: NmeaFix


@dataclass(frozen=True)
class NmeaTrackParse:
    points: tuple[GeotagTrackPoint, ...]
    has: tuple[str, ...]
    is_date: bool
    no_date: bool


@dataclass(frozen=True)
class CsvColumn:
    kind: CsvColumnKind
    speed_scale: float | None = None


@dataclass
class CsvRowState:
    date_seconds: float | None = None
    seconds: float | None = None
    lat: float | None = None
    lon: float | None = None
    alt: str | None = None
    speed: GeotagTrackValue | None = None
    track: GeotagTrackValue | None = None
    pitch: GeotagTrackValue | None = None
    roll: GeotagTrackValue | None = None
    direction: GeotagTrackValue | None = None
    negative_lat: bool = False
    negative_lon: bool = False

    def apply_coordinate_refs(self) -> None:
        if self.negative_lat and self.lat is not None:
            self.lat = -abs(self.lat)
        if self.negative_lon and self.lon is not None:
            self.lon = -abs(self.lon)

    def to_track_point(self) -> GeotagTrackPoint | None:
        self.apply_coordinate_refs()
        if (
            self.date_seconds is None
            or self.seconds is None
            or self.lat is None
            or self.lon is None
        ):
            return None
        return GeotagTrackPoint(
            time_seconds=self.date_seconds + self.seconds,
            lat=self.lat,
            lon=self.lon,
            alt=self.alt,
            first=False,
            speed=self.speed,
            track=self.track,
            direction=self.direction,
            pitch=self.pitch,
            roll=self.roll,
        )


@dataclass
class JsonTrackState:
    lat: GeotagTrackValue | None = None
    lon: GeotagTrackValue | None = None
    start_time_seconds: float | None = None

    def consume_field(self, field_name: str, field_value: str) -> GeotagTrackPoint | None:
        if field_name in {"latitudeE7", "latE7"}:
            self.lat = float(field_value) * 1e-7
            return None
        if field_name in {"longitudeE7", "lngE7"}:
            self.lon = float(field_value) * 1e-7
            return None
        if field_name == "point":
            coordinates = tuple(re.findall(r"[-+]?\d+\.\d+", field_value))
            if len(coordinates) == 2:
                self.lat = coordinates[0]
                self.lon = coordinates[1]
            return None
        if field_name == "startTime":
            self.start_time_seconds = xml_time_seconds(field_value)
            return None
        if field_name in {"timestamp", "time"}:
            time_seconds = xml_time_seconds(field_value)
            if time_seconds is None:
                return None
            return self.emit_point(time_seconds)
        if (
            field_name == "durationMinutesOffsetFromStartTime"
            and self.start_time_seconds is not None
        ):
            return self.emit_point(self.start_time_seconds + float(field_value) * 60)
        return None

    def emit_point(self, time_seconds: float) -> GeotagTrackPoint | None:
        if self.lat is None or self.lon is None:
            return None
        point = GeotagTrackPoint(
            time_seconds=time_seconds,
            lat=self.lat,
            lon=self.lon,
            alt=None,
            first=False,
        )
        self.lat = None
        self.lon = None
        return point


def load_track_log_value(value: str) -> GeotagTrackLogLoadResult:
    return load_track_log_data(value, None)


def load_track_log_data(value: str, source_path: Path | None) -> GeotagTrackLogLoadResult:
    if value == "DATETIMEONLY":
        return ok_track_log(
            GeotagTrackLog(
                format_name="datetime_only",
                points=(),
                has=("pos",),
                is_date=True,
                no_date=False,
                date_time_only=True,
            )
        )
    if looks_like_xml_track_log(value):
        return load_xml_track_log(value)
    if looks_like_winplus_track_log(value):
        return load_winplus_track_log(value)
    if looks_like_bramor_track_log(value):
        return load_bramor_track_log(value)
    if looks_like_csv_track_log(value):
        return load_csv_track_log(value, source_path)
    if looks_like_json_track_log(value):
        return load_json_track_log(value)
    if looks_like_igc_track_log(value):
        return load_igc_track_log(value)
    if looks_like_nmea_track_log(value):
        return load_nmea_track_log(value)
    return invalid_track_log("No track points found in GPS data")


def load_track_log_file(path: Path) -> GeotagTrackLogLoadResult:
    if not path.exists():
        return invalid_track_log(f"Error opening GPS file '{path.as_posix()}'")
    source = FileMediaSource(path)
    prefix = source.prefix(TRACK_LOG_PROBE_SIZE)
    if not prefix:
        return invalid_track_log(f"Empty track file '{path.as_posix()}'")
    if looks_like_garmin_fit_file_data(source.prefix(GARMIN_FIT_SIGNATURE_PREFIX_SIZE)):
        metadata_track_log = load_metadata_track_log_file(path)
        if metadata_track_log is not None:
            return ok_track_log(geotag_track_log_from_metadata(metadata_track_log))
        return invalid_track_log(f"Invalid track file '{path.as_posix()}'")
    if looks_like_binary_metadata_source(prefix):
        metadata_track_log = load_metadata_track_log_file(path)
        if metadata_track_log is not None:
            return ok_track_log(geotag_track_log_from_metadata(metadata_track_log))
        return invalid_track_log(f"Invalid track file '{path.as_posix()}'")
    raw_data = source.read_full()
    data = raw_data.decode("utf-8", errors="replace")
    result = load_track_log_data(data, path)
    if (
        result.status == "invalid"
        and not looks_like_xml_track_log(data)
        and not looks_like_winplus_track_log(data)
        and not looks_like_nmea_track_log(data)
        and not looks_like_bramor_track_log(data)
        and not looks_like_csv_track_log(data)
        and not looks_like_json_track_log(data)
        and not looks_like_igc_track_log(data)
    ):
        metadata_track_log = load_metadata_track_log_file(path)
        if metadata_track_log is not None:
            return ok_track_log(geotag_track_log_from_metadata(metadata_track_log))
        return invalid_track_log(f"Invalid track file '{path.as_posix()}'")
    return result


def looks_like_garmin_fit_file_data(data: bytes) -> bool:
    return len(data) >= 12 and data[8:12] == b".FIT"


def looks_like_binary_metadata_source(data: bytes) -> bool:
    return (
        any(data.startswith(prefix) for prefix in BINARY_METADATA_PREFIXES) or data[4:8] == b"ftyp"
    )


def geotag_track_log_from_metadata(metadata: MetadataTrackLog) -> GeotagTrackLog:
    return GeotagTrackLog(
        format_name="metadata",
        points=mark_first_track_point(
            tuple(
                GeotagTrackPoint(
                    time_seconds=point.time_seconds,
                    lat=point.lat,
                    lon=point.lon,
                    alt=point.alt,
                    speed=point.speed,
                    track=point.track,
                    first=False,
                )
                for point in metadata.points
            )
        ),
        has=metadata.has,
        is_date=True,
        no_date=False,
        date_time_only=False,
    )


def concatenate_track_logs(track_logs: tuple[GeotagTrackLog, ...]) -> GeotagTrackLog:
    if not track_logs:
        raise ValueError("at least one track log is required")
    if len(track_logs) == 1:
        return track_logs[0]
    points = tuple(
        sorted(
            (point for track_log in track_logs for point in track_log.points),
            key=lambda point: point.time_seconds,
        )
    )
    first_time = points[0].time_seconds if points else None
    ordered_has = tuple(
        key
        for key in ("pos", "track", "alt", "orient", "atemp", "err", "dop")
        if any(key in track_log.has for track_log in track_logs)
    )
    return GeotagTrackLog(
        format_name="combined",
        points=tuple(
            track_point_with_first(
                point,
                first_time is not None and point.time_seconds == first_time,
            )
            for point in points
        ),
        has=ordered_has or ("pos",),
        is_date=any(track_log.is_date for track_log in track_logs),
        no_date=any(track_log.no_date for track_log in track_logs),
        date_time_only=all(track_log.date_time_only for track_log in track_logs),
    )


def track_point_with_first(point: GeotagTrackPoint, first: bool) -> GeotagTrackPoint:
    return GeotagTrackPoint(
        time_seconds=point.time_seconds,
        lat=point.lat,
        lon=point.lon,
        alt=point.alt,
        first=first,
        speed=point.speed,
        track=point.track,
        direction=point.direction,
        pitch=point.pitch,
        roll=point.roll,
        hdop=point.hdop,
        pdop=point.pdop,
        vdop=point.vdop,
    )


def looks_like_xml_track_log(value: str) -> bool:
    return value.startswith("<?xml") or value.startswith("<gpx") or value.startswith("\ufeff<?xml")


def looks_like_nmea_track_log(value: str) -> bool:
    return any(
        marker in value
        for marker in (
            "$PMGNTRK,",
            "$GPRMC,",
            "$GNRMC,",
            "$GPGGA,",
            "$GNGGA,",
            "$GPGLL,",
            "$GNGLL,",
            "$GPGSA,",
            "$GNGSA,",
            "$GPZDA,",
            "$GNZDA,",
            "$PTNTHPR,",
        )
    )


def looks_like_winplus_track_log(value: str) -> bool:
    return value.startswith("TP,D,") or "\nTP,D," in value


def looks_like_bramor_track_log(value: str) -> bool:
    return " ypr" in value


def looks_like_csv_track_log(value: str) -> bool:
    first_line = first_non_empty_line(value)
    return "," in first_line and (
        (
            bool(re.search(r"\b(GPS)?Date", first_line, flags=re.IGNORECASE))
            and bool(re.search(r"\b(GPS)?(Date)?Time", first_line, flags=re.IGNORECASE))
        )
        or bool(re.search(r"\bTime\(seconds\)", first_line, flags=re.IGNORECASE))
    )


def looks_like_json_track_log(value: str) -> bool:
    return bool(
        re.search(
            r'"(timelineObjects|placeVisit|activitySegment|latitudeE7|'
            r'durationMinutesOffsetFromStartTime|startTime)"\s*:',
            value,
        )
    )


def first_non_empty_line(value: str) -> str:
    for line in value.splitlines():
        if line.strip():
            return line
    return ""


def looks_like_igc_track_log(value: str) -> bool:
    return "HFDTE" in value and "\nB" in value


def load_xml_track_log(value: str) -> GeotagTrackLogLoadResult:
    try:
        root = ElementTree.fromstring(value.lstrip("\ufeff"))
    except ElementTree.ParseError:
        return invalid_track_log("No track points found in GPS data")
    parsed_points = tuple(xml_track_points(root))
    if not parsed_points:
        return invalid_track_log("No track points found in GPS data")
    first_time = parsed_points[0].time_seconds
    points = tuple(
        track_point_with_first(point, point.time_seconds == first_time) for point in parsed_points
    )
    has = ["pos"]
    if any(point.alt is not None for point in points) and not contains_gx_track(root):
        has.append("alt")
    if any(
        point.hdop is not None or point.pdop is not None or point.vdop is not None
        for point in points
    ):
        has.append("dop")
    return ok_track_log(
        GeotagTrackLog(
            format_name="XML",
            points=points,
            has=tuple(has),
            is_date=True,
            no_date=False,
            date_time_only=False,
        )
    )


def xml_track_points(root: ElementTree.Element) -> tuple[GeotagTrackPoint, ...]:
    gx_track_points = tuple(gx_track_xml_points(root))
    if gx_track_points:
        return gx_track_points
    points: list[GeotagTrackPoint] = []
    for element in root.iter():
        if local_name(element.tag).lower() not in {"trkpt", "wpt", "rtept", "trackpoint"}:
            continue
        point = xml_track_point(element)
        if point is not None:
            points.append(point)
    return tuple(points)


def gx_track_xml_points(root: ElementTree.Element) -> tuple[GeotagTrackPoint, ...]:
    points: list[GeotagTrackPoint] = []
    for element in root.iter():
        if local_name(element.tag).lower() != "track":
            continue
        times = tuple(
            child.text.strip()
            for child in element
            if local_name(child.tag).lower() == "when" and child.text
        )
        coordinates = tuple(
            child.text.strip()
            for child in element
            if local_name(child.tag).lower() == "coord" and child.text
        )
        for time_text, coordinate_text in zip(times, coordinates, strict=False):
            coordinate_parts = coordinate_text.split()
            if len(coordinate_parts) < 2:
                continue
            time_seconds = xml_time_seconds(time_text)
            if time_seconds is None:
                continue
            points.append(
                GeotagTrackPoint(
                    time_seconds=time_seconds,
                    lat=coordinate_parts[1],
                    lon=coordinate_parts[0],
                    alt=coordinate_parts[2] if len(coordinate_parts) >= 3 else None,
                    first=False,
                )
            )
    return tuple(points)


def contains_gx_track(root: ElementTree.Element) -> bool:
    return any(element.tag == "{http://www.google.com/kml/ext/2.2}Track" for element in root.iter())


def xml_track_point(element: ElementTree.Element) -> GeotagTrackPoint | None:
    lat = (
        element.attrib.get("lat")
        or child_text(element, "latitude")
        or child_text(element, "latitudedegrees")
    )
    lon = (
        element.attrib.get("lon")
        or child_text(element, "longitude")
        or child_text(element, "longitudedegrees")
    )
    time_text = child_text(element, "time")
    if lat is None or lon is None or time_text is None:
        return None
    time_seconds = xml_time_seconds(time_text)
    if time_seconds is None:
        return None
    return GeotagTrackPoint(
        time_seconds=time_seconds,
        lat=lat,
        lon=lon,
        alt=child_text(element, "ele")
        or child_text(element, "alt")
        or child_text(element, "altitude")
        or child_text(element, "altitudemeters"),
        hdop=child_text(element, "hdop"),
        pdop=child_text(element, "pdop"),
        vdop=child_text(element, "vdop"),
        first=False,
    )


def child_text(element: ElementTree.Element, name: str) -> str | None:
    for child in element.iter():
        if child is element:
            continue
        if local_name(child.tag).lower() == name and child.text is not None:
            return child.text.strip()
    return None


def local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def load_nmea_track_log(value: str) -> GeotagTrackLogLoadResult:
    parsed = nmea_track_parse(value)
    if not parsed.points:
        return invalid_track_log("No track points found in GPS data")
    first_time = parsed.points[0].time_seconds
    marked_points = tuple(
        track_point_with_first(point, point.time_seconds == first_time) for point in parsed.points
    )
    return ok_track_log(
        GeotagTrackLog(
            format_name="NMEA",
            points=marked_points,
            has=parsed.has,
            is_date=parsed.is_date,
            no_date=parsed.no_date,
            date_time_only=False,
        )
    )


def nmea_track_parse(value: str) -> NmeaTrackParse:
    points_by_time: dict[float, NmeaFix] = {}
    nmea_seen: set[str] = set()
    nmea_start: str | None = None
    current_fix: NmeaFix | None = None
    current_fix_seconds: float | None = None
    current_time: float | None = None
    last_date_seconds: int | None = None
    last_seconds: float | None = None
    is_date = False
    no_date = False
    current_no_date = False

    for line in value.splitlines():
        sentence = nmea_sentence(line.strip())
        if sentence is None:
            continue
        if nmea_start is None:
            if sentence.kind not in NMEA_TIMESTAMP_KINDS:
                continue
            nmea_start = sentence.kind
        sentence_date_seconds = nmea_sentence_date_seconds(
            sentence.seconds,
            sentence.date_seconds,
            last_seconds,
            last_date_seconds,
        )
        if sentence_date_seconds is not None and sentence.seconds is not None:
            last_date_seconds = sentence_date_seconds
            last_seconds = sentence.seconds
        starts_new_fix = nmea_sentence_starts_new_fix(
            sentence.kind,
            nmea_start,
            sentence.seconds,
            current_fix_seconds,
        )
        if starts_new_fix:
            if sentence.seconds is None:
                current_fix = sentence.fix
                current_fix_seconds = None
                current_time = None
                current_no_date = False
                nmea_seen.add(sentence.kind)
                continue
            current_fix = sentence.fix
            current_fix_seconds = sentence.seconds
            current_time = nmea_fix_time(sentence.seconds, sentence_date_seconds)
            current_no_date = sentence_date_seconds is None
            if sentence_date_seconds is None:
                no_date = True
            else:
                current_fix.is_date = True
                is_date = True
        elif current_fix is not None:
            current_fix.merge_missing(sentence.fix)
            if sentence_date_seconds is not None and not current_fix.is_date:
                was_current_no_date = current_no_date
                if current_time is not None:
                    points_by_time.pop(current_time, None)
                fix_seconds = current_fix_seconds
                if fix_seconds is None:
                    fix_seconds = sentence.seconds
                    current_fix_seconds = fix_seconds
                if fix_seconds is not None:
                    if sentence.seconds is not None and sentence.seconds < fix_seconds:
                        sentence_date_seconds -= SECONDS_PER_DAY
                    current_time = sentence_date_seconds + fix_seconds
                    current_fix.is_date = True
                    current_no_date = False
                    is_date = True
                    if was_current_no_date:
                        no_date = False
            elif (
                sentence.seconds is not None
                and current_fix_seconds is None
                and current_time is None
            ):
                current_fix_seconds = sentence.seconds
                current_time = nmea_fix_time(sentence.seconds, sentence_date_seconds)
                current_no_date = sentence_date_seconds is None
                no_date = no_date or current_no_date
                if sentence_date_seconds is not None:
                    current_fix.is_date = True
                    is_date = True
        else:
            continue
        if current_fix is not None and current_time is not None and current_fix.has_position():
            points_by_time[current_time] = current_fix
            if current_fix.is_date and current_no_date:
                no_date = False
                current_no_date = False
        nmea_seen.add(sentence.kind)

    has = nmea_capabilities(points_by_time, nmea_seen)
    return NmeaTrackParse(
        points=tuple(
            points_by_time[time_seconds].to_track_point(time_seconds)
            for time_seconds in sorted(points_by_time)
        ),
        has=has,
        is_date=is_date,
        no_date=no_date,
    )


def nmea_sentence_date_seconds(
    seconds: float | None,
    date_seconds: int | None,
    last_seconds: float | None,
    last_date_seconds: int | None,
) -> int | None:
    if date_seconds is not None:
        if seconds is not None and last_seconds is not None and seconds < last_seconds - 2:
            return date_seconds + SECONDS_PER_DAY
        return date_seconds
    if seconds is None or last_seconds is None or last_date_seconds is None:
        return None
    inherited_date = last_date_seconds
    adjusted_last_seconds = last_seconds
    if seconds < adjusted_last_seconds - 2:
        adjusted_last_seconds -= SECONDS_PER_DAY
        inherited_date += SECONDS_PER_DAY
    if seconds - adjusted_last_seconds < NMEA_DATE_INHERITANCE_WINDOW_SECONDS:
        return inherited_date
    return None


def nmea_sentence_starts_new_fix(
    kind: str,
    nmea_start: str,
    seconds: float | None,
    current_fix_seconds: float | None,
) -> bool:
    if kind == nmea_start:
        return True
    if seconds is None:
        return False
    if current_fix_seconds is None:
        return True
    if seconds >= current_fix_seconds:
        return seconds - current_fix_seconds >= NMEA_FIX_BOUNDARY_SECONDS
    return seconds + SECONDS_PER_DAY - current_fix_seconds >= NMEA_FIX_BOUNDARY_SECONDS


def nmea_fix_time(seconds: float, date_seconds: int | None) -> float:
    return seconds if date_seconds is None else date_seconds + seconds


def nmea_capabilities(points_by_time: dict[float, NmeaFix], nmea_seen: set[str]) -> tuple[str, ...]:
    has = {"pos"}
    if (
        "GGA" in nmea_seen
        or "PMGNTRK" in nmea_seen
        or any(fix.alt is not None for fix in points_by_time.values())
    ):
        has.add("alt")
    if "RMC" in nmea_seen or any(
        fix.track is not None or fix.speed is not None for fix in points_by_time.values()
    ):
        has.add("track")
    if "PTNTHPR" in nmea_seen or any(
        fix.direction is not None or fix.pitch is not None or fix.roll is not None
        for fix in points_by_time.values()
    ):
        has.add("orient")
    return tuple(sorted(has))


def nmea_sentence(line: str) -> NmeaSentence | None:
    if "$" in line and not line.startswith("$"):
        line = line[line.index("$") :]
    kind = nmea_sentence_kind(line)
    if kind == "RMC":
        return rmc_sentence(line)
    if kind == "GGA":
        return gga_sentence(line)
    if kind == "GLL":
        return gll_sentence(line)
    if kind == "GSA":
        return gsa_sentence(line)
    if kind == "ZDA":
        return zda_sentence(line)
    if kind == "PMGNTRK":
        return pmgntrk_sentence(line)
    if kind == "PTNTHPR":
        return ptnthpr_sentence(line)
    return None


def nmea_sentence_kind(line: str) -> str | None:
    if line.startswith("$PMGNTRK,"):
        return "PMGNTRK"
    if line.startswith("$PTNTHPR,"):
        return "PTNTHPR"
    if len(line) >= 7 and line.startswith("$"):
        suffix = line[3:6]
        if suffix in {"RMC", "GGA", "GLL", "GSA", "ZDA"}:
            return suffix
    return None


def rmc_sentence(line: str) -> NmeaSentence | None:
    match = RMC_PATTERN.match(line)
    if match is None:
        return None
    day = int(match.group(13))
    month = int(match.group(14))
    year = int(match.group(15))
    if day > 31 or month > 12 or year > 99:
        return None
    full_year = year + (1900 if year >= 70 else 2000)
    return NmeaSentence(
        kind="RMC",
        seconds=nmea_seconds(match.group(1), match.group(2), match.group(3)),
        date_seconds=calendar.timegm((full_year, month, day, 0, 0, 0)),
        fix=NmeaFix(
            lat=nmea_coordinate(match.group(5), match.group(6), match.group(7), "N"),
            lon=nmea_coordinate(match.group(8), match.group(9), match.group(10), "E"),
            speed=match.group(11) or None,
            track=match.group(12) or None,
        ),
    )


def gga_sentence(line: str) -> NmeaSentence | None:
    match = GGA_PATTERN.match(line)
    if match is None:
        return None
    return NmeaSentence(
        kind="GGA",
        seconds=nmea_seconds(match.group(1), match.group(2), match.group(3)),
        date_seconds=None,
        fix=NmeaFix(
            lat=nmea_coordinate(match.group(5), match.group(6), match.group(7), "N"),
            lon=nmea_coordinate(match.group(8), match.group(9), match.group(10), "E"),
            alt=match.group(13),
            hdop=match.group(12),
        ),
    )


def gll_sentence(line: str) -> NmeaSentence | None:
    match = GLL_PATTERN.match(line)
    if match is None:
        return None
    return NmeaSentence(
        kind="GLL",
        seconds=nmea_seconds(match.group(7), match.group(8), match.group(9)),
        date_seconds=None,
        fix=NmeaFix(
            lat=nmea_coordinate(match.group(1), match.group(2), match.group(3), "N"),
            lon=nmea_coordinate(match.group(4), match.group(5), match.group(6), "E"),
        ),
    )


def gsa_sentence(line: str) -> NmeaSentence | None:
    match = GSA_PATTERN.match(line)
    if match is None:
        return None
    return NmeaSentence(
        kind="GSA",
        seconds=None,
        date_seconds=None,
        fix=NmeaFix(pdop=match.group(3), hdop=match.group(4), vdop=match.group(5)),
    )


def zda_sentence(line: str) -> NmeaSentence | None:
    match = ZDA_PATTERN.match(line)
    if match is None:
        return None
    return NmeaSentence(
        kind="ZDA",
        seconds=nmea_seconds(match.group(1), match.group(2), match.group(3)),
        date_seconds=calendar.timegm(
            (int(match.group(7)), int(match.group(6)), int(match.group(5)), 0, 0, 0)
        ),
        fix=NmeaFix(),
    )


def pmgntrk_sentence(line: str) -> NmeaSentence | None:
    match = PMGNTRK_PATTERN.match(line)
    if match is None:
        return None
    altitude: GeotagTrackValue = match.group(7)
    if match.group(8) == "F":
        altitude = float(match.group(7)) * 12 * 0.0254
    date_seconds: int | None = None
    day_text = match.group(13)
    month_text = match.group(14)
    year_text = match.group(15)
    if day_text is not None and month_text is not None and year_text is not None:
        day = int(day_text)
        month = int(month_text)
        year = int(year_text)
        if day > 31 or month > 12 or year > 99:
            return None
        full_year = year + (1900 if year >= 70 else 2000)
        date_seconds = calendar.timegm((full_year, month, day, 0, 0, 0))
    return NmeaSentence(
        kind="PMGNTRK",
        seconds=nmea_seconds(match.group(9), match.group(10), match.group(11)),
        date_seconds=date_seconds,
        fix=NmeaFix(
            lat=pmgntrk_coordinate(match.group(1), match.group(2), match.group(3), "N"),
            lon=pmgntrk_coordinate(match.group(4), match.group(5), match.group(6), "E"),
            alt=altitude,
        ),
    )


def ptnthpr_sentence(line: str) -> NmeaSentence | None:
    match = PTNTHPR_PATTERN.match(line)
    if match is None:
        return None
    return NmeaSentence(
        kind="PTNTHPR",
        seconds=None,
        date_seconds=None,
        fix=NmeaFix(direction=match.group(1), pitch=match.group(2), roll=match.group(3)),
    )


def nmea_seconds(hours_text: str, minutes_text: str, seconds_text: str) -> float:
    return (int(hours_text) * 60 + int(minutes_text)) * 60 + float(seconds_text)


def nmea_coordinate(
    degrees_text: str,
    minutes_text: str,
    direction: str,
    positive_direction: str,
) -> float:
    degrees = int(degrees_text) if degrees_text else 0
    value = degrees + float(minutes_text) / 60
    return value if direction == positive_direction else -value


def pmgntrk_coordinate(
    degrees_text: str,
    minutes_text: str,
    direction: str,
    positive_direction: str,
) -> float:
    value = int(degrees_text) + float(minutes_text) / 60
    return value if direction == positive_direction else -value


def load_winplus_track_log(value: str) -> GeotagTrackLogLoadResult:
    points = tuple(winplus_track_points(value))
    if not points:
        return invalid_track_log("No track points found in GPS data")
    return ok_track_log(
        GeotagTrackLog(
            format_name="Winplus",
            points=mark_first_track_point(points),
            has=("pos",),
            is_date=True,
            no_date=False,
            date_time_only=False,
        )
    )


def winplus_track_points(value: str) -> tuple[GeotagTrackPoint, ...]:
    points: list[GeotagTrackPoint] = []
    for line in value.splitlines():
        match = WINPLUS_PATTERN.match(line)
        if match is None:
            continue
        points.append(
            GeotagTrackPoint(
                time_seconds=calendar.timegm(
                    (
                        int(match.group(5)),
                        int(match.group(3)),
                        int(match.group(4)),
                        int(match.group(6)),
                        int(match.group(7)),
                        int(match.group(8)),
                    )
                ),
                lat=match.group(1),
                lon=match.group(2),
                alt=None,
                first=False,
            )
        )
    return tuple(points)


def load_csv_track_log(value: str, source_path: Path | None) -> GeotagTrackLogLoadResult:
    rows = tuple(csv_rows(value))
    if not rows:
        return invalid_track_log("No track points found in GPS data")
    columns = tuple(csv_column(header, rows[0][0] == "INDEX") for header in rows[0])
    dji_start_time = csv_dji_start_time(columns, source_path)
    if any(column.kind == "runtime" for column in columns) and dji_start_time is None:
        return invalid_track_log("Error getting start time from file name for DJI CSV track file")
    points: list[GeotagTrackPoint] = []
    has = {"pos"}
    for row in rows[1:]:
        row_state = csv_row_state(columns, row, dji_start_time)
        point = row_state.to_track_point()
        if point is None:
            continue
        points.append(point)
        if row_state.alt is not None:
            has.add("alt")
        if row_state.speed is not None:
            has.add("speed")
        if row_state.track is not None:
            has.add("track")
        if row_state.direction is not None:
            has.add("dir")
        if row_state.pitch is not None:
            has.add("pitch")
            has.add("orient")
        if row_state.roll is not None:
            has.add("roll")
    if not points:
        return invalid_track_log("No track points found in GPS data")
    return ok_track_log(
        GeotagTrackLog(
            format_name="CSV",
            points=mark_first_track_point(tuple(points)),
            has=tuple(sorted(has)),
            is_date=True,
            no_date=False,
            date_time_only=False,
        )
    )


def csv_rows(value: str) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    reader = csv.reader(io.StringIO(value), delimiter=",")
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        rows.append(tuple(cell.strip() for cell in row))
    return tuple(rows)


def csv_column(header: str, is_columbus: bool) -> CsvColumn:
    normalized = re.sub(r"^GPS ?", "", header, flags=re.IGNORECASE)
    if re.match(r"^Time ?\(seconds\)$", normalized, flags=re.IGNORECASE):
        return CsvColumn("runtime")
    if re.match(r"^Date ?Time", normalized, flags=re.IGNORECASE):
        return CsvColumn("datetime")
    if re.match(r"^Date", normalized, flags=re.IGNORECASE):
        return CsvColumn("date")
    if re.match(r"^Time(?! ?\(text\))", normalized, flags=re.IGNORECASE):
        return CsvColumn("time")
    if re.match(r"^(Pos)?Lat", normalized, flags=re.IGNORECASE):
        return CsvColumn("latref" if re.search(r"ref$", normalized, flags=re.IGNORECASE) else "lat")
    if re.match(r"^(Pos)?Lon", normalized, flags=re.IGNORECASE):
        return CsvColumn("lonref" if re.search(r"ref$", normalized, flags=re.IGNORECASE) else "lon")
    if re.match(r"^(Pos)?(Alt|Height)", normalized, flags=re.IGNORECASE):
        return CsvColumn("alt")
    if re.match(r"^Speed", normalized, flags=re.IGNORECASE):
        unit_match = re.search(r"\((mph|km/h|m/s)\)", normalized)
        if unit_match is not None:
            return CsvColumn("speed", CSV_SPEED_CONVERSION_TO_KNOTS[unit_match.group(1)])
        if is_columbus:
            return CsvColumn("speed", CSV_SPEED_CONVERSION_TO_KNOTS["km/h"])
        return CsvColumn("speed")
    if re.match(r"^(Angle)?(Heading|Track|Bearing)", normalized, flags=re.IGNORECASE):
        return CsvColumn("track")
    if re.match(r"^(Angle)?Pitch", normalized, flags=re.IGNORECASE) or re.match(
        r"^Camera ?Elevation ?Angle", normalized, flags=re.IGNORECASE
    ):
        return CsvColumn("pitch")
    if re.match(r"^(Angle)?Roll", normalized, flags=re.IGNORECASE):
        return CsvColumn("roll")
    if re.match(r"^Img ?Dir", normalized, flags=re.IGNORECASE):
        return CsvColumn("dir")
    return CsvColumn("ignore")


def csv_dji_start_time(columns: tuple[CsvColumn, ...], source_path: Path | None) -> float | None:
    if not any(column.kind == "runtime" for column in columns):
        return None
    if source_path is None:
        return None
    match = DJI_FILENAME_TIME_PATTERN.search(source_path.name)
    if match is None:
        return None
    return time.mktime(
        (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6)),
            0,
            0,
            -1,
        )
    )


def csv_row_state(
    columns: tuple[CsvColumn, ...],
    row: tuple[str, ...],
    dji_start_time: float | None,
) -> CsvRowState:
    row_state = CsvRowState()
    for index, column in enumerate(columns):
        if index >= len(row):
            break
        value = row[index]
        if not value:
            break
        apply_csv_value(row_state, column, value, dji_start_time)
    return row_state


def apply_csv_value(
    row_state: CsvRowState,
    column: CsvColumn,
    value: str,
    dji_start_time: float | None,
) -> None:
    if column.kind == "datetime":
        date_time_seconds = csv_datetime_seconds(value)
        if date_time_seconds is not None:
            row_state.date_seconds = date_time_seconds
            row_state.seconds = 0
    elif column.kind == "date":
        row_state.date_seconds = csv_date_seconds(value)
    elif column.kind == "time":
        row_state.seconds = csv_time_seconds(value)
    elif column.kind == "runtime":
        if dji_start_time is not None:
            row_state.date_seconds = dji_start_time
            row_state.seconds = float(value)
    elif column.kind == "lat":
        row_state.lat = float(value)
    elif column.kind == "latref":
        row_state.negative_lat = value.upper().startswith("S")
    elif column.kind == "lon":
        row_state.lon = float(value)
    elif column.kind == "lonref":
        row_state.negative_lon = value.upper().startswith("W")
    elif column.kind == "alt":
        row_state.alt = value
    elif column.kind == "speed":
        row_state.speed = float(value) / column.speed_scale if column.speed_scale else value
    elif column.kind == "track":
        row_state.track = value
    elif column.kind == "pitch":
        row_state.pitch = value
    elif column.kind == "roll":
        row_state.roll = value
    elif column.kind == "dir":
        row_state.direction = value


def csv_datetime_seconds(value: str) -> float | None:
    normalized = re.sub(r"^(\d{2})[^\d](\d{2})[^\d](\d{4}) ", r"\3:\2:\1 ", value)
    match = re.match(
        r"^(\d{4})[^\d](\d{2})[^\d](\d{2})\s+(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)",
        normalized,
    )
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


def csv_date_seconds(value: str) -> float | None:
    slash_match = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", value)
    if slash_match is not None:
        return float(
            calendar.timegm(
                (
                    int(slash_match.group(3)),
                    int(slash_match.group(2)),
                    int(slash_match.group(1)),
                    0,
                    0,
                    0,
                )
            )
        )
    iso_match = re.search(r"(\d{4}).*?(\d{2}).*?(\d{2})", value)
    if iso_match is not None:
        return float(
            calendar.timegm(
                (
                    int(iso_match.group(1)),
                    int(iso_match.group(2)),
                    int(iso_match.group(3)),
                    0,
                    0,
                    0,
                )
            )
        )
    compact_match = re.match(r"^(\d{2})(\d{2})(\d{2})$", value)
    if compact_match is not None:
        return float(
            calendar.timegm(
                (
                    int(compact_match.group(1)) + 2000,
                    int(compact_match.group(2)),
                    int(compact_match.group(3)),
                    0,
                    0,
                    0,
                )
            )
        )
    return None


def csv_time_seconds(value: str) -> float | None:
    time_match = re.match(
        r"^(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?).*?(([-+])(\d{1,2}):?(\d{2}))?",
        value,
    )
    if time_match is not None:
        seconds = (int(time_match.group(1)) * 60 + int(time_match.group(2))) * 60 + float(
            time_match.group(3)
        )
        if time_match.group(4):
            timezone_seconds = (int(time_match.group(6)) * 60 + int(time_match.group(7))) * 60
            seconds += timezone_seconds if time_match.group(5) == "-" else -timezone_seconds
        return seconds
    compact_match = re.match(r"^(\d{2})(\d{2})(\d{2})$", value)
    if compact_match is not None:
        return float(
            (int(compact_match.group(1)) * 60 + int(compact_match.group(2))) * 60
            + int(compact_match.group(3))
        )
    return None


def mark_first_track_point(points: tuple[GeotagTrackPoint, ...]) -> tuple[GeotagTrackPoint, ...]:
    if not points:
        return ()
    first_time = points[0].time_seconds
    return tuple(
        track_point_with_first(point, point.time_seconds == first_time) for point in points
    )


def load_json_track_log(value: str) -> GeotagTrackLogLoadResult:
    points = json_track_points(value)
    if not points:
        return invalid_track_log("No track points found in GPS data")
    return ok_track_log(
        GeotagTrackLog(
            format_name="JSON",
            points=mark_first_track_point(points),
            has=("pos",),
            is_date=True,
            no_date=False,
            date_time_only=False,
        )
    )


def json_track_points(value: str) -> tuple[GeotagTrackPoint, ...]:
    state = JsonTrackState()
    points: list[GeotagTrackPoint] = []
    for line in value.splitlines():
        field = json_track_field(line)
        if field is None:
            continue
        field_name, field_value = field
        point = state.consume_field(field_name, field_value)
        if point is not None:
            points.append(point)
    return tuple(points)


def json_track_field(line: str) -> tuple[str, str] | None:
    match = JSON_FIELD_PATTERN.match(line)
    if match is None:
        return None
    return match.group(1), (
        match.group(2) if match.group(2) is not None else match.group(3)
    ).strip()


def load_bramor_track_log(value: str) -> GeotagTrackLogLoadResult:
    points = tuple(bramor_track_points(value))
    if not points:
        return invalid_track_log("No track points found in GPS data")
    first_time = points[0].time_seconds
    marked_points = tuple(
        track_point_with_first(point, point.time_seconds == first_time) for point in points
    )
    return ok_track_log(
        GeotagTrackLog(
            format_name="Bramor",
            points=marked_points,
            has=("alt", "orient", "pos", "track"),
            is_date=True,
            no_date=False,
            date_time_only=False,
        )
    )


def bramor_track_points(value: str) -> tuple[GeotagTrackPoint, ...]:
    points: list[GeotagTrackPoint] = []
    for line in value.splitlines():
        match = BRAMOR_PATTERN.match(line)
        if match is None:
            continue
        points.append(
            GeotagTrackPoint(
                time_seconds=calendar.timegm(
                    (
                        int(match.group(7)),
                        int(match.group(6)),
                        int(match.group(5)),
                        int(match.group(8)),
                        int(match.group(9)),
                        0,
                    )
                )
                + float(match.group(10)),
                lat=match.group(1),
                lon=match.group(2),
                alt=match.group(3),
                first=False,
                track=match.group(4),
                direction=match.group(11),
                pitch=match.group(12),
                roll=match.group(13),
            )
        )
    return tuple(points)


def load_igc_track_log(value: str) -> GeotagTrackLogLoadResult:
    points = tuple(igc_track_points(value))
    if not points:
        return invalid_track_log("No track points found in GPS data")
    first_time = points[0].time_seconds
    marked_points = tuple(
        track_point_with_first(point, point.time_seconds == first_time) for point in points
    )
    return ok_track_log(
        GeotagTrackLog(
            format_name="IGC",
            points=marked_points,
            has=("alt", "pos"),
            is_date=True,
            no_date=False,
            date_time_only=False,
        )
    )


def igc_track_points(value: str) -> tuple[GeotagTrackPoint, ...]:
    points: list[GeotagTrackPoint] = []
    date_seconds: int | None = None
    previous_seconds = 0.0
    for line in value.splitlines():
        date_match = IGC_DATE_PATTERN.match(line)
        if date_match is not None:
            year = int(date_match.group(3))
            full_year = year + (1900 if year >= 70 else 2000)
            date_seconds = calendar.timegm(
                (full_year, int(date_match.group(2)), int(date_match.group(1)), 0, 0, 0)
            )
            continue
        fix_match = IGC_FIX_PATTERN.match(line)
        if fix_match is None or date_seconds is None:
            continue
        seconds = (int(fix_match.group(1)) * 60 + int(fix_match.group(2))) * 60 + int(
            fix_match.group(3)
        )
        if seconds < previous_seconds - 2:
            date_seconds += 24 * 3600
        previous_seconds = seconds
        points.append(
            GeotagTrackPoint(
                time_seconds=date_seconds + seconds,
                lat=igc_coordinate(
                    fix_match.group(4),
                    fix_match.group(5),
                    fix_match.group(6),
                    fix_match.group(7),
                    "N",
                ),
                lon=igc_coordinate(
                    fix_match.group(8),
                    fix_match.group(9),
                    fix_match.group(10),
                    fix_match.group(11),
                    "E",
                ),
                alt=fix_match.group(14) if fix_match.group(12) == "A" else None,
                first=False,
            )
        )
    return tuple(points)


def igc_coordinate(
    degrees_text: str,
    minutes_text: str,
    minute_fraction_text: str,
    direction: str,
    positive_direction: str,
) -> float:
    value = int(degrees_text) + (int(minutes_text) + int(minute_fraction_text) / 1000) / 60
    return value if direction == positive_direction else -value


def xml_time_seconds(value: str) -> float | None:
    match = XML_TIME_PATTERN.match(value)
    if match is None:
        return None
    try:
        timestamp = calendar.timegm(
            (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
                int(match.group(5)),
                int(match.group(6)),
            )
        )
    except ValueError:
        return None
    result = float(timestamp)
    if match.group(7):
        result += float(match.group(7))
    timezone_text = match.group(8)
    timezone_match = TIMEZONE_PATTERN.match(timezone_text)
    if timezone_match is not None:
        result += timezone_adjustment_seconds(timezone_match)
    return result


def timezone_adjustment_seconds(match: re.Match[str]) -> int:
    sign = match.group(1) or match.group(4)
    hours = int(match.group(2) or match.group(5))
    minutes = int(match.group(3) or match.group(6) or "0")
    seconds = (hours * 60 + minutes) * 60
    return -seconds if sign == "+" else seconds


def ok_track_log(track_log: GeotagTrackLog) -> GeotagTrackLogLoadResult:
    return GeotagTrackLogLoadResult(status="ok", track_log=track_log, warning=None)


def invalid_track_log(warning: str) -> GeotagTrackLogLoadResult:
    return GeotagTrackLogLoadResult(status="invalid", track_log=None, warning=warning)
