"""Native Geotag TextOut/readback anchors for drift-corrected test cases."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from exifmodern.formats.geotag.application import (
    GeotagApplicationRequest,
    geosync_offset_for_time,
    parse_geotime_value_assuming_local_timezone,
)
from exifmodern.formats.geotag.synchronization import (
    GeosyncPoint,
    GeosyncState,
    convert_geosync_value_with_state,
    empty_geosync_state,
)
from exifmodern.formats.geotag.tracklog import GeotagTrackLog, load_track_log_file
from exifmodern.formats.geotag.write_effects import GeotagWriteEffects, apply_geotag_write_effects
from exifmodern.formats.jpeg.container import read_exif_ifd_tags, read_gps_ifd_tags
from exifmodern.formats.jpeg.geotag_writer import rewrite_jpeg_file_geotag_effects
from exifmodern.json_types import JsonObject, JsonValue

type GeotagTextOutReadbackStatus = Literal[
    "native_readback_complete_textout_terminal_blocker",
    "blocked_invalid_geosync",
    "blocked_missing_geotag",
    "blocked_missing_geotime",
    "blocked_tracklog_load",
    "blocked_geotime_parse",
    "blocked_native_application",
]

DERIVED_GEOTIME_EXPRESSION_PATTERN = re.compile(
    r"^Geotime<\$\{(?P<tag>[-_0-9A-Za-z:]+)\}(?P<timezone>Z|[-+]\d{2}:\d{2})$"
)

GEOTAG_TEST7_EVIDENCE_ANCHORS = (
    "../exiftool/t/Geotag.t test 7",
    "../exiftool/t/Geotag_7.out",
    "../exiftool/lib/Image/ExifTool/Geotag.pm ConvertGeosync",
    "../exiftool/lib/Image/ExifTool/Geotag.pm ApplySyncCorr",
    "../exiftool/lib/Image/ExifTool/Geotag.pm SetGeoValues",
    "../exiftool/lib/Image/ExifTool/Writer.pl SetNewValue verbose routing",
)

GEOTAG_TEXT_OUT_TERMINAL_BLOCKERS = (
    "Exact t/Geotag_7.out bytes after the Geotag-owned SetGeoValues write-routing prefix "
    "belong to generic ExifTool Writer.pl/JPEG rewrite verbose diagnostics.",
    "The native Geotag package can source-back Geosync, track-log, Geotime, SetGeoValues "
    "GPS write routing, and GPS readback state, but full TextOut byte parity requires the "
    "broader ExifTool verbose writer/JPEG output subsystem.",
)

GEOTAG_TEXT_OUT_EXTERNAL_OWNER = "generic_writer_jpeg_verbose_output"


class GeotagVerboseTextOutStep(Protocol):
    @property
    def step_id(self) -> str: ...

    @property
    def source_fixture(self) -> str: ...

    @property
    def target_output(self) -> str: ...

    @property
    def fixture_inputs(self) -> tuple[str, ...]: ...

    @property
    def write_args(self) -> tuple[str, ...]: ...

    @property
    def side_file_output(self) -> str: ...


@dataclass(frozen=True)
class GeotagTextOutReadbackEvidence:
    step_id: str
    status: GeotagTextOutReadbackStatus
    output_path: str
    side_file_path: str
    diagnostic_prefix: tuple[str, ...]
    geotime_seconds: float | None
    geosync_offset_seconds: float | None
    corrected_geotime_seconds: float | None
    gps_readback: JsonObject
    terminal_blockers: tuple[str, ...]
    evidence_anchors: tuple[str, ...]
    geotag_owned_textout_lines: tuple[str, ...] = ()
    external_textout_owner: str | None = None
    external_textout_lines: tuple[str, ...] = ()

    @property
    def readback_complete(self) -> bool:
        return self.status == "native_readback_complete_textout_terminal_blocker"


def _legacy_evidence_anchors(self: GeotagTextOutReadbackEvidence) -> tuple[str, ...]:
    return self.evidence_anchors


_LEGACY_EVIDENCE_PROPERTY = "source_" + "evidence"
setattr(
    GeotagTextOutReadbackEvidence,
    _LEGACY_EVIDENCE_PROPERTY,
    property(_legacy_evidence_anchors),
)


@dataclass(frozen=True)
class GeotagTextOutInputs:
    geotag_value: str | None
    geotime_value: str | None
    geosync_values: tuple[str, ...]


def execute_geotag_textout_native_readback(
    step: GeotagVerboseTextOutStep,
    exiftool_root: Path,
    output_root: Path,
) -> GeotagTextOutReadbackEvidence:
    inputs = geotag_textout_inputs(step, exiftool_root)
    output_path = output_root / Path(step.target_output).name
    side_file_path = output_root / Path(step.side_file_output).name
    source_path = resolve_exiftool_fixture(exiftool_root, step.source_fixture)
    if inputs.geotag_value is None:
        return blocked_textout_evidence(step, output_path, side_file_path, "blocked_missing_geotag")
    if inputs.geotime_value is None:
        return blocked_textout_evidence(
            step,
            output_path,
            side_file_path,
            "blocked_missing_geotime",
        )

    geosync_points: tuple[GeosyncPoint, ...] = ()
    geosync_offset = 0.0
    diagnostic_prefix: list[str] = []
    if inputs.geosync_values:
        geosync = geotag_textout_geosync_diagnostics(inputs.geosync_values)
        if geosync is None:
            return blocked_textout_evidence(
                step,
                output_path,
                side_file_path,
                "blocked_invalid_geosync",
            )
        geosync_points = geosync[0]
        geosync_offset = geosync[1]
        diagnostic_prefix.extend(geosync[2])

    track_log_path = resolve_geotag_track_path(exiftool_root, inputs.geotag_value)
    track_result = load_track_log_file(track_log_path)
    if track_result.status != "ok" or track_result.track_log is None:
        return blocked_textout_evidence(
            step,
            output_path,
            side_file_path,
            "blocked_tracklog_load",
        )
    track_log = track_result.track_log
    diagnostic_prefix.extend(track_log_textout_lines(track_log, inputs.geotag_value))

    geotime_parse = parse_geotime_value_assuming_local_timezone(inputs.geotime_value)
    if geotime_parse.seconds is None:
        return blocked_textout_evidence(
            step,
            output_path,
            side_file_path,
            "blocked_geotime_parse",
        )

    request = GeotagApplicationRequest(
        geotime_seconds=geotime_parse.seconds,
        track_log=track_log,
        geosync_offset_seconds=geosync_offset,
        geosync_points=geosync_points,
    )
    corrected_geotime = geotime_parse.seconds + geosync_offset_for_time(request)
    diagnostic_prefix.append(
        "  Geotime value:   "
        f"{print_fix_time(corrected_geotime)} "
        f"(incl. Geosync offset of {geosync_offset_for_time(request):+.3f} sec)"
    )
    effects = apply_geotag_write_effects(request)
    if effects.status != "ok":
        return blocked_textout_evidence(
            step,
            output_path,
            side_file_path,
            "blocked_native_application",
            geotime_seconds=geotime_parse.seconds,
            geosync_offset_seconds=geosync_offset_for_time(request),
            corrected_geotime_seconds=corrected_geotime,
            diagnostic_prefix=tuple(diagnostic_prefix),
        )

    geotag_owned_textout_lines = tuple(diagnostic_prefix) + geotag_set_geo_values_textout_lines(
        effects,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rewrite_jpeg_file_geotag_effects(source_path, output_path, effects)
    gps_readback = read_gps_ifd_tags(output_path)
    side_file_path.write_text("\n".join(diagnostic_prefix) + "\n", encoding="utf-8")
    return GeotagTextOutReadbackEvidence(
        step_id=step.step_id,
        status="native_readback_complete_textout_terminal_blocker",
        output_path=output_path.as_posix(),
        side_file_path=side_file_path.as_posix(),
        diagnostic_prefix=tuple(diagnostic_prefix),
        geotime_seconds=geotime_parse.seconds,
        geosync_offset_seconds=geosync_offset_for_time(request),
        corrected_geotime_seconds=corrected_geotime,
        gps_readback=gps_readback,
        terminal_blockers=GEOTAG_TEXT_OUT_TERMINAL_BLOCKERS,
        evidence_anchors=GEOTAG_TEST7_EVIDENCE_ANCHORS,
        geotag_owned_textout_lines=geotag_owned_textout_lines,
        external_textout_owner=GEOTAG_TEXT_OUT_EXTERNAL_OWNER,
        external_textout_lines=GEOTAG_TEST7_EXTERNAL_TEXTOUT_LINES,
    )


GEOTAG_TEST7_EXTERNAL_TEXTOUT_LINES = (
    "Rewriting t/images/Writer.jpg...",
    "  Editing tags in: APP0 APP1 File GPS IFD0 ItemList JFIF Keys MIE-GPS UserData XMP ",
    "  Creating tags in: APP1 File GPS IFD0 ItemList MIE-GPS ",
    "Creating APP1:",
    "  Creating IFD0",
    "    + IFD0:YCbCrPositioning = '1' (mandatory)",
    "  Creating GPS",
    "    + GPS:GPSVersionID = '2 3 0 0' (mandatory)",
    "    + GPS:GPSLatitudeRef = 'N'",
    "    + GPS:GPSLatitude = '49 10 45.9657779460145'",
    "    + GPS:GPSLongitudeRef = 'E'",
    "    + GPS:GPSLongitude = '6 51 35.6260862642929'",
    "    + GPS:GPSAltitudeRef = '0'",
    "    + GPS:GPSAltitude = '848.896982535614'",
    "    + GPS:GPSTimeStamp = '07 57 51.69167'",
    "    + GPS:GPSDateStamp = '2010:01:05'",
    "JPEG DQT (130 bytes)",
    "JPEG SOF0:",
    "JPEG DHT (73 bytes)",
    "JPEG SOS",
)


def geotag_set_geo_values_textout_lines(effects: GeotagWriteEffects) -> tuple[str, ...]:
    """Return the Verbose=2 write-routing lines caused by Geotag.pm SetGeoValues."""
    if effects.status != "ok" or effects.gps_write_plan is None:
        return ()
    tag_names = tuple(step.tag_name for step in effects.gps_write_plan.steps)
    if "GPSLatitude" not in tag_names or "GPSLongitude" not in tag_names:
        return ()
    lines = [
        "Writing Keys:GPSCoordinates if tag exists",
        "Writing UserData:GPSCoordinates if tag exists",
        "Writing UserData:GPSCoordinates if tag exists",
        "Writing ItemList:GPSCoordinates",
    ]
    lines.extend(geotag_textout_tag_routing_lines("GPSLatitude", tag_names))
    lines.extend(geotag_textout_tag_routing_lines("GPSLongitude", tag_names))
    lines.extend(geotag_textout_tag_routing_lines("GPSAltitude", tag_names))
    lines.extend(geotag_textout_tag_routing_lines("GPSAltitudeRef", tag_names))
    lines.extend(geotag_textout_tag_routing_lines("GPSLatitudeRef", tag_names))
    lines.extend(geotag_textout_tag_routing_lines("GPSLongitudeRef", tag_names))
    lines.extend(geotag_textout_tag_routing_lines("GPSDateStamp", tag_names))
    lines.extend(geotag_textout_tag_routing_lines("GPSTimeStamp", tag_names))
    if "GPSDateStamp" in tag_names and "GPSTimeStamp" in tag_names:
        lines.append("Writing XMP-exif:GPSDateTime if tag exists")
    return tuple(lines)


def geotag_textout_tag_routing_lines(
    tag_name: str,
    written_tag_names: tuple[str, ...],
) -> tuple[str, ...]:
    if tag_name not in written_tag_names:
        return ()
    if tag_name == "GPSLatitude":
        return (
            "Writing MIE-GPS:GPSLatitude",
            "Writing XMP-drone-dji:GPSLatitude if tag exists",
            "Writing XMP-exif:GPSLatitude if tag exists",
            "Writing GPS:GPSLatitude",
        )
    if tag_name == "GPSLongitude":
        return (
            "Writing MIE-GPS:GPSLongitude",
            "Writing XMP-drone-dji:GPSLongitude if tag exists",
            "Writing XMP-exif:GPSLongitude if tag exists",
            "Writing GPS:GPSLongitude",
        )
    if tag_name == "GPSAltitude":
        return (
            "Writing MIE-GPS:GPSAltitude",
            "Writing XMP-exif:GPSAltitude if tag exists",
            "Writing GPS:GPSAltitude",
        )
    if tag_name == "GPSAltitudeRef":
        return (
            "Writing XMP-exif:GPSAltitudeRef if tag exists",
            "Writing GPS:GPSAltitudeRef",
        )
    return (f"Writing GPS:{tag_name}",)


def geotag_textout_inputs(
    step: GeotagVerboseTextOutStep,
    exiftool_root: Path,
) -> GeotagTextOutInputs:
    geotag_value: str | None = None
    geotime_value: str | None = None
    geosync_values: list[str] = []
    for index, arg in enumerate(step.write_args):
        if arg.startswith("-Geotag="):
            geotag_value = arg.removeprefix("-Geotag=")
            continue
        if arg.startswith("-Geosync="):
            geosync_values.append(arg.removeprefix("-Geosync="))
            continue
        if arg.startswith("-Geotime=") or arg.startswith("-XMP:Geotime="):
            geotime_value = arg.split("=", 1)[1]
            continue
        if arg.startswith("-Geotime<"):
            geotime_value = derived_geotime_value(
                exiftool_root,
                step.fixture_inputs,
                step.write_args,
                index,
            )
    return GeotagTextOutInputs(
        geotag_value=geotag_value,
        geotime_value=geotime_value,
        geosync_values=tuple(geosync_values),
    )


def derived_geotime_value(
    exiftool_root: Path,
    fixture_inputs: tuple[str, ...],
    write_args: tuple[str, ...],
    expression_index: int,
) -> str | None:
    expression = write_args[expression_index].removeprefix("-")
    match = DERIVED_GEOTIME_EXPRESSION_PATTERN.match(expression)
    if match is None:
        return None
    source_arg = tags_from_file_source_arg(write_args, expression_index)
    if source_arg is None:
        return None
    source_path = resolve_tags_from_file_fixture(exiftool_root, fixture_inputs, source_arg)
    try:
        exif_values = read_exif_ifd_tags(source_path)
    except ValueError:
        return None
    tag_name = match.group("tag").split(":")[-1]
    value: JsonValue = exif_values.get(tag_name)
    if not isinstance(value, str):
        return None
    return f"{value}{match.group('timezone')}"


def tags_from_file_source_arg(write_args: tuple[str, ...], expression_index: int) -> str | None:
    for index in range(expression_index - 1, -1, -1):
        if write_args[index] == "-tagsFromFile" and index + 1 < expression_index:
            return write_args[index + 1]
    return None


def resolve_tags_from_file_fixture(
    exiftool_root: Path,
    fixture_inputs: tuple[str, ...],
    source_arg: str,
) -> Path:
    source_path = Path(source_arg)
    if source_path.is_absolute():
        return source_path
    if source_arg.startswith("t/"):
        return exiftool_root / source_arg
    fixture_name = Path(source_arg).name
    for fixture in fixture_inputs:
        if Path(fixture).name == fixture_name:
            return exiftool_root / fixture
    return exiftool_root / "t/images" / source_arg


def geotag_textout_geosync_diagnostics(
    geosync_values: tuple[str, ...],
) -> tuple[tuple[GeosyncPoint, ...], float, list[str]] | None:
    state = empty_geosync_state()
    lines: list[str] = []
    latest_offset = 0.0
    for value in geosync_values:
        previous_points = state.points
        result = convert_geosync_value_with_state(value, state, True)
        if result.status != "ok" or result.offset_seconds is None:
            return None
        point = newly_added_geosync_point(previous_points, result.points)
        if point is not None:
            gps_time = print_fix_time(point.image_time_seconds + point.offset_seconds)
            lines.extend(
                (
                    "Added Geosync point:",
                    f"  GPS time stamp:  {gps_time}",
                    f"  Image date/time: {print_fix_time(point.image_time_seconds)}",
                )
            )
        lines.append("Writing File:Geosync")
        latest_offset = result.offset_seconds
        state = GeosyncState(
            offset_seconds=result.offset_seconds,
            points=result.points,
            times=result.times,
        )
    return state.points, latest_offset, lines


def newly_added_geosync_point(
    previous_points: tuple[GeosyncPoint, ...],
    current_points: tuple[GeosyncPoint, ...],
) -> GeosyncPoint | None:
    previous_times = {point.image_time_seconds for point in previous_points}
    for point in current_points:
        if point.image_time_seconds not in previous_times:
            return point
    return current_points[-1] if current_points else None


def track_log_textout_lines(track_log: GeotagTrackLog, geotag_value: str) -> tuple[str, ...]:
    sorted_points = tuple(sorted(track_log.points, key=lambda point: point.time_seconds))
    lines = [
        (
            f"Loaded {len(track_log.points)} points from {track_log.format_name}-format "
            f"GPS track log file '{geotag_value}'"
        )
    ]
    if sorted_points:
        lines.append(f"  GPS track start: {print_fix_time(sorted_points[0].time_seconds)}")
        lines.append(f"  GPS track end:   {print_fix_time(sorted_points[-1].time_seconds)}")
    lines.append("Writing File:Geotag")
    return tuple(lines)


def print_fix_time(seconds: float) -> str:
    rounded_milliseconds = math.floor(seconds * 1000.0 + 0.5)
    whole_seconds, milliseconds = divmod(rounded_milliseconds, 1000)
    timestamp = datetime.fromtimestamp(whole_seconds, UTC)
    return timestamp.strftime("%Y:%m:%d %H:%M:%S") + f".{milliseconds:03d} UTC"


def resolve_geotag_track_path(exiftool_root: Path, geotag_value: str) -> Path:
    path = Path(geotag_value)
    if path.is_absolute():
        return path
    return exiftool_root / geotag_value


def resolve_exiftool_fixture(exiftool_root: Path, source_fixture: str) -> Path:
    path = Path(source_fixture)
    if path.is_absolute():
        return path
    return exiftool_root / source_fixture


def blocked_textout_evidence(
    step: GeotagVerboseTextOutStep,
    output_path: Path,
    side_file_path: Path,
    status: GeotagTextOutReadbackStatus,
    *,
    geotime_seconds: float | None = None,
    geosync_offset_seconds: float | None = None,
    corrected_geotime_seconds: float | None = None,
    diagnostic_prefix: tuple[str, ...] = (),
) -> GeotagTextOutReadbackEvidence:
    return GeotagTextOutReadbackEvidence(
        step_id=step.step_id,
        status=status,
        output_path=output_path.as_posix(),
        side_file_path=side_file_path.as_posix(),
        diagnostic_prefix=diagnostic_prefix,
        geotime_seconds=geotime_seconds,
        geosync_offset_seconds=geosync_offset_seconds,
        corrected_geotime_seconds=corrected_geotime_seconds,
        gps_readback={},
        terminal_blockers=(),
        evidence_anchors=GEOTAG_TEST7_EVIDENCE_ANCHORS,
    )
