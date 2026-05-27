"""Public top-level geotag user-surface parsing."""

from __future__ import annotations

import argparse
import glob
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from exifmodern.formats.geotag.public_workflow import PublicGeotagWorkflowRequest
from exifmodern.formats.geotag.synchronization import (
    convert_geosync_values_resolving_file_references,
)
from exifmodern.public_interface.user_params import (
    PublicUserParam,
    parse_public_user_param_argument,
)

type PublicGeotagDestinationGroup = Literal[
    "default", "EXIF", "XMP", "QuickTime", "ItemList", "UserData", "Keys"
]

type PublicGeotagBackupPolicy = Literal["create_backup", "overwrite_original"]
type PublicGeotagOperation = Literal["apply", "delete"]

PUBLIC_GEOTAG_TIMEZONE_BLOCKER_SOURCE_REFERENCES: tuple[str, ...] = (
    "public.geotag.timezone-option-parse",
    "public.geotag.geotime-timezone-docs",
    "public.geotag.track-timezone-docs",
    "public.geotag.interpolation-timezone-docs",
    "public.geotag.local-timezone-formatting",
)


def is_top_level_geotag_request(args: Sequence[str]) -> bool:
    return any(
        arg.lower() == "-geotag"
        or arg.lower().startswith("-geotag=")
        or is_public_geotag_assignment(arg)
        for arg in args
    )


def parse_public_geotag_workflow_request(
    args: Sequence[str],
) -> PublicGeotagWorkflowRequest:
    track_log_path: Path | None = None
    geotime: str | None = None
    geotime_copy_expression: str | None = None
    geosync_values: list[str] = []
    target_paths: list[Path] = []
    backup_policy: PublicGeotagBackupPolicy = "create_backup"
    preserve_file_times = False
    destination_group: PublicGeotagDestinationGroup = "default"
    operation: PublicGeotagOperation = "apply"
    geo_max_ext_seconds = 1800.0
    geo_max_int_seconds = 1800.0
    geo_max_hdop: float | None = None
    geo_max_pdop: float | None = None
    geolocate_geotag = False
    from exifmodern.package_resources import generated_index_package_path

    geolocation_package_path = generated_index_package_path()
    geoloc_max_distance_km: float | None = None
    geoloc_min_population: float | None = None
    geoloc_feature_codes: tuple[str, ...] = ()
    geoloc_excluded_feature_codes: tuple[str, ...] = ()
    geoloc_limit = 1
    geoloc_alt_names = True
    track_log_paths: list[Path] = []
    user_params: list[PublicUserParam] = []
    index = 0
    while index < len(args):
        arg = args[index]
        lower_arg = arg.lower()
        if lower_arg == "-api":
            value = _parse_required_option_value(arg, args, index)
            api_user_param = _public_api_user_param_argument(value)
            if api_user_param is not None:
                user_params.append(parse_public_user_param_argument(api_user_param))
                index += 2
                continue
            (
                geo_max_ext_seconds,
                geo_max_int_seconds,
                geo_max_hdop,
                geo_max_pdop,
                geolocate_geotag,
                geolocation_package_path,
                geoloc_max_distance_km,
                geoloc_min_population,
                geoloc_feature_codes,
                geoloc_excluded_feature_codes,
                geoloc_limit,
                geoloc_alt_names,
            ) = _apply_public_geotag_api_option(
                value,
                geo_max_ext_seconds,
                geo_max_int_seconds,
                geo_max_hdop,
                geo_max_pdop,
                geolocate_geotag,
                geolocation_package_path,
                geoloc_max_distance_km,
                geoloc_min_population,
                geoloc_feature_codes,
                geoloc_excluded_feature_codes,
                geoloc_limit,
                geoloc_alt_names,
            )
            index += 2
            continue
        if lower_arg == "-userparam":
            user_params.append(
                parse_public_user_param_argument(_parse_required_option_value(arg, args, index))
            )
            index += 2
            continue
        if lower_arg.startswith("-api="):
            (
                geo_max_ext_seconds,
                geo_max_int_seconds,
                geo_max_hdop,
                geo_max_pdop,
                geolocate_geotag,
                geolocation_package_path,
                geoloc_max_distance_km,
                geoloc_min_population,
                geoloc_feature_codes,
                geoloc_excluded_feature_codes,
                geoloc_limit,
                geoloc_alt_names,
            ) = _apply_public_geotag_api_option(
                arg.partition("=")[2],
                geo_max_ext_seconds,
                geo_max_int_seconds,
                geo_max_hdop,
                geo_max_pdop,
                geolocate_geotag,
                geolocation_package_path,
                geoloc_max_distance_km,
                geoloc_min_population,
                geoloc_feature_codes,
                geoloc_excluded_feature_codes,
                geoloc_limit,
                geoloc_alt_names,
            )
            index += 1
            continue
        if lower_arg == "-geotag=":
            operation = "delete"
            track_log_path = None
            track_log_paths = []
            index += 1
            continue
        if is_public_geotag_assignment(arg):
            tag_name, _separator, value = arg.removeprefix("-").partition("=")
            destination_group = public_geotag_destination_group(tag_name.lower())
            if value:
                track_log_path = Path(value)
                track_log_paths.append(track_log_path)
                operation = "apply"
            else:
                operation = "delete"
                track_log_path = None
                track_log_paths = []
            index += 1
            continue
        if lower_arg.startswith("-geotag="):
            track_log_path = Path(arg.partition("=")[2])
            track_log_paths.append(track_log_path)
            index += 1
            continue
        if lower_arg == "-geotag":
            track_log = _parse_required_option_value(arg, args, index)
            expanded_track_logs = _expand_public_geotag_track_log_option(track_log)
            track_log_paths.extend(expanded_track_logs)
            track_log_path = expanded_track_logs[-1]
            index += 2
            continue
        if lower_arg in {"-geosync", "-gps:geosync"}:
            geosync_values.append(
                _parse_required_option_value(arg, args, index, allow_dash_prefixed=True)
            )
            index += 2
            continue
        if is_public_geosync_assignment(arg):
            geosync_values.append(arg.partition("=")[2])
            index += 1
            continue
        if is_public_geolocate_geotag_assignment(arg):
            geolocate_geotag = True
            index += 1
            continue
        if lower_arg in {
            "-geotime",
            "-gps:geotime",
            "-exif:geotime",
            "-xmp:geotime",
            "-quicktime:geotime",
            "-itemlist:geotime",
            "-userdata:geotime",
            "-keys:geotime",
        }:
            destination_group = public_geotime_destination_group(lower_arg.removeprefix("-"))
            geotime = _parse_required_option_value(arg, args, index, allow_dash_prefixed=True)
            geotime_copy_expression = None
            index += 2
            continue
        if is_public_geotime_assignment(arg):
            destination_group = public_geotime_destination_group(
                arg.removeprefix("-").partition("=")[0].lower()
            )
            geotime_value = arg.partition("=")[2]
            if geotime_value:
                geotime = geotime_value
                geotime_copy_expression = None
            else:
                operation = "delete"
                geotime = None
                geotime_copy_expression = None
                track_log_path = None
                track_log_paths = []
            index += 1
            continue
        if is_public_geotime_copy_expression(arg):
            tag_name, _separator, expression = arg.removeprefix("-").partition("<")
            if not expression:
                raise argparse.ArgumentTypeError(f"Expecting source expression for {arg}")
            destination_group = public_geotime_destination_group(tag_name.lower())
            geotime = None
            geotime_copy_expression = expression
            index += 1
            continue
        if lower_arg in {"-overwrite_original", "-overwriteoriginal"}:
            backup_policy = "overwrite_original"
            index += 1
            continue
        if lower_arg == "-overwrite_original_in_place":
            raise argparse.ArgumentTypeError(
                "public -geotag does not implement -overwrite_original_in_place; use "
                "-overwrite_original for the executable overwrite policy or omit it to "
                "create the default _original backup"
            )
        if arg == "-P" or lower_arg == "-preserve":
            preserve_file_times = True
            index += 1
            continue
        if arg.startswith("-"):
            raise argparse.ArgumentTypeError(
                f"unsupported public -geotag planning option or mixed write: {arg}"
            )
        target_paths.append(Path(arg))
        index += 1
    if not track_log_paths and track_log_path is None and operation == "apply":
        raise argparse.ArgumentTypeError("Expecting file name for -geotag option")
    geosync = (
        convert_geosync_values_resolving_file_references(tuple(geosync_values))
        if geosync_values
        else None
    )
    if geosync is not None and geosync.status != "ok":
        raise argparse.ArgumentTypeError(
            geosync.warning or "Invalid Geosync value (please refer to geotag documentation)"
        )
    if geotime_copy_expression is not None:
        missing_copy_targets = [path for path in target_paths if not path.is_file()]
        if missing_copy_targets:
            raise argparse.ArgumentTypeError(
                "unsupported public -geotag planning option or mixed write: "
                f"-Geotime<{geotime_copy_expression}"
            )
    return PublicGeotagWorkflowRequest(
        track_log_path=track_log_path,
        geotime=geotime,
        geotime_copy_expression=geotime_copy_expression,
        target_paths=tuple(target_paths),
        track_log_paths=tuple(track_log_paths),
        geo_max_ext_seconds=geo_max_ext_seconds,
        geo_max_int_seconds=geo_max_int_seconds,
        geo_max_hdop=geo_max_hdop,
        geo_max_pdop=geo_max_pdop,
        geosync_offset_seconds=0.0 if geosync is None else geosync.offset_seconds or 0.0,
        geosync_points=() if geosync is None else geosync.points,
        geolocate_geotag=geolocate_geotag,
        geolocation_package_path=geolocation_package_path,
        geoloc_max_distance_km=geoloc_max_distance_km,
        geoloc_min_population=geoloc_min_population,
        geoloc_feature_codes=geoloc_feature_codes,
        geoloc_excluded_feature_codes=geoloc_excluded_feature_codes,
        geoloc_limit=geoloc_limit,
        geoloc_alt_names=geoloc_alt_names,
        backup_policy=backup_policy,
        preserve_file_times=preserve_file_times,
        destination_group=destination_group,
        operation=operation,
        user_params=tuple(user_params),
    )


def is_public_geotime_assignment(arg: str) -> bool:
    if not arg.startswith("-") or "=" not in arg:
        return False
    tag_name = arg.removeprefix("-").partition("=")[0].lower()
    return tag_name in {
        "geotime",
        "gps:geotime",
        "exif:geotime",
        "xmp:geotime",
        "quicktime:geotime",
        "itemlist:geotime",
        "userdata:geotime",
        "keys:geotime",
    }


def is_public_geotag_assignment(arg: str) -> bool:
    if not arg.startswith("-") or "=" not in arg:
        return False
    tag_name = arg.removeprefix("-").partition("=")[0].lower()
    return tag_name in {
        "geotag",
        "gps:geotag",
        "exif:geotag",
        "xmp:geotag",
        "quicktime:geotag",
        "itemlist:geotag",
        "userdata:geotag",
        "keys:geotag",
    }


def is_public_geosync_assignment(arg: str) -> bool:
    if not arg.startswith("-") or "=" not in arg:
        return False
    tag_name = arg.removeprefix("-").partition("=")[0].lower()
    return tag_name in {"geosync", "gps:geosync"}


def is_public_geolocate_geotag_assignment(arg: str) -> bool:
    if not arg.startswith("-") or "=" not in arg:
        return False
    tag_name, _separator, value = arg.removeprefix("-").partition("=")
    geolocate_tags = {"geolocate", "iptc:geolocate", "xmp:geolocate", "iptc:xmp:geolocate"}
    return tag_name.lower() in geolocate_tags and (
        "geotag" in value.lower().split(",")
        or value.lower() == "geotag"
        or "geotag" in value.lower().split()
    )


def is_public_geotime_copy_expression(arg: str) -> bool:
    if not arg.startswith("-") or "<" not in arg:
        return False
    tag_name = arg.removeprefix("-").partition("<")[0].lower()
    return tag_name in {
        "geotime",
        "gps:geotime",
        "exif:geotime",
        "xmp:geotime",
        "quicktime:geotime",
        "itemlist:geotime",
        "userdata:geotime",
        "keys:geotime",
    }


def _public_api_user_param_argument(value: str) -> str | None:
    name, separator, assigned_value = value.partition("=")
    if name.lower() != "userparam" or separator != "=":
        return None
    return assigned_value


def public_geotime_destination_group(tag_name: str) -> PublicGeotagDestinationGroup:
    if tag_name == "geotime":
        return "default"
    return public_geotag_destination_group(tag_name.replace(":geotime", ":geotag"))


def public_geotag_destination_group(tag_name: str) -> PublicGeotagDestinationGroup:
    group = tag_name.partition(":")[0]
    if group in {"geotag", "gps"}:
        return "default"
    if group == "exif":
        return "EXIF"
    if group == "xmp":
        return "XMP"
    if group == "quicktime":
        return "QuickTime"
    if group == "itemlist":
        return "ItemList"
    if group == "userdata":
        return "UserData"
    if group == "keys":
        return "Keys"
    raise argparse.ArgumentTypeError(f"unsupported public -geotag group: {group}")


def _apply_public_geotag_api_option(
    value: str,
    geo_max_ext_seconds: float,
    geo_max_int_seconds: float,
    geo_max_hdop: float | None,
    geo_max_pdop: float | None,
    geolocate_geotag: bool,
    geolocation_package_path: Path,
    geoloc_max_distance_km: float | None,
    geoloc_min_population: float | None,
    geoloc_feature_codes: tuple[str, ...],
    geoloc_excluded_feature_codes: tuple[str, ...],
    geoloc_limit: int,
    geoloc_alt_names: bool,
) -> tuple[
    float,
    float,
    float | None,
    float | None,
    bool,
    Path,
    float | None,
    float | None,
    tuple[str, ...],
    tuple[str, ...],
    int,
    bool,
]:
    name, separator, raw_option_value = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError(f"Expecting NAME=VALUE for -api {value}")
    normalized = name.lower()
    if normalized == "geomaxextsecs":
        return (
            _parse_public_geotag_float_option("GeoMaxExtSecs", raw_option_value),
            geo_max_int_seconds,
            geo_max_hdop,
            geo_max_pdop,
            geolocate_geotag,
            geolocation_package_path,
            geoloc_max_distance_km,
            geoloc_min_population,
            geoloc_feature_codes,
            geoloc_excluded_feature_codes,
            geoloc_limit,
            geoloc_alt_names,
        )
    if normalized == "geomaxintsecs":
        return (
            geo_max_ext_seconds,
            _parse_public_geotag_float_option("GeoMaxIntSecs", raw_option_value),
            geo_max_hdop,
            geo_max_pdop,
            geolocate_geotag,
            geolocation_package_path,
            geoloc_max_distance_km,
            geoloc_min_population,
            geoloc_feature_codes,
            geoloc_excluded_feature_codes,
            geoloc_limit,
            geoloc_alt_names,
        )
    if normalized == "geolocation":
        return (
            geo_max_ext_seconds,
            geo_max_int_seconds,
            geo_max_hdop,
            geo_max_pdop,
            geolocate_geotag or raw_option_value.lower() == "geotag",
            geolocation_package_path,
            geoloc_max_distance_km,
            geoloc_min_population,
            geoloc_feature_codes,
            geoloc_excluded_feature_codes,
            geoloc_limit,
            geoloc_alt_names,
        )
    if normalized == "geolocationpackage":
        return (
            geo_max_ext_seconds,
            geo_max_int_seconds,
            geo_max_hdop,
            geo_max_pdop,
            geolocate_geotag,
            Path(raw_option_value),
            geoloc_max_distance_km,
            geoloc_min_population,
            geoloc_feature_codes,
            geoloc_excluded_feature_codes,
            geoloc_limit,
            geoloc_alt_names,
        )
    if normalized == "geolocmaxdist":
        return (
            geo_max_ext_seconds,
            geo_max_int_seconds,
            geo_max_hdop,
            geo_max_pdop,
            geolocate_geotag,
            geolocation_package_path,
            _parse_public_geotag_float_option("GeolocMaxDist", raw_option_value),
            geoloc_min_population,
            geoloc_feature_codes,
            geoloc_excluded_feature_codes,
            geoloc_limit,
            geoloc_alt_names,
        )
    if normalized == "geolocminpop":
        return (
            geo_max_ext_seconds,
            geo_max_int_seconds,
            geo_max_hdop,
            geo_max_pdop,
            geolocate_geotag,
            geolocation_package_path,
            geoloc_max_distance_km,
            _parse_public_geotag_float_option("GeolocMinPop", raw_option_value),
            geoloc_feature_codes,
            geoloc_excluded_feature_codes,
            geoloc_limit,
            geoloc_alt_names,
        )
    if normalized == "geolocfeature":
        feature_codes, excluded_feature_codes = _parse_public_geoloc_feature_option(
            raw_option_value
        )
        return (
            geo_max_ext_seconds,
            geo_max_int_seconds,
            geo_max_hdop,
            geo_max_pdop,
            geolocate_geotag,
            geolocation_package_path,
            geoloc_max_distance_km,
            geoloc_min_population,
            feature_codes,
            excluded_feature_codes,
            geoloc_limit,
            geoloc_alt_names,
        )
    if normalized == "geolocmulti":
        return (
            geo_max_ext_seconds,
            geo_max_int_seconds,
            geo_max_hdop,
            geo_max_pdop,
            geolocate_geotag,
            geolocation_package_path,
            geoloc_max_distance_km,
            geoloc_min_population,
            geoloc_feature_codes,
            geoloc_excluded_feature_codes,
            _parse_public_geotag_int_option("GeolocMulti", raw_option_value),
            geoloc_alt_names,
        )
    if normalized == "geolocaltnames":
        return (
            geo_max_ext_seconds,
            geo_max_int_seconds,
            geo_max_hdop,
            geo_max_pdop,
            geolocate_geotag,
            geolocation_package_path,
            geoloc_max_distance_km,
            geoloc_min_population,
            geoloc_feature_codes,
            geoloc_excluded_feature_codes,
            geoloc_limit,
            raw_option_value not in {"0", "false", "False"},
        )
    if normalized == "geomaxhdop":
        return (
            geo_max_ext_seconds,
            geo_max_int_seconds,
            _parse_public_geotag_float_option("GeoMaxHDOP", raw_option_value),
            geo_max_pdop,
            geolocate_geotag,
            geolocation_package_path,
            geoloc_max_distance_km,
            geoloc_min_population,
            geoloc_feature_codes,
            geoloc_excluded_feature_codes,
            geoloc_limit,
            geoloc_alt_names,
        )
    if normalized == "geomaxpdop":
        return (
            geo_max_ext_seconds,
            geo_max_int_seconds,
            geo_max_hdop,
            _parse_public_geotag_float_option("GeoMaxPDOP", raw_option_value),
            geolocate_geotag,
            geolocation_package_path,
            geoloc_max_distance_km,
            geoloc_min_population,
            geoloc_feature_codes,
            geoloc_excluded_feature_codes,
            geoloc_limit,
            geoloc_alt_names,
        )
    if normalized in {"geominsats", "geohposerr", "geospeedref", "geousertag"}:
        raise argparse.ArgumentTypeError(
            f"unsupported public -geotag API option: {name}; "
            "the current public geotag track-point model does not expose the "
            "required source field without adding arbitrary Perl Geotime/config behavior"
        )
    raise argparse.ArgumentTypeError(f"unsupported public -geotag API option: {name}")


def _parse_public_geotag_float_option(option_name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{option_name} must be numeric") from exc


def _parse_public_geotag_int_option(option_name: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{option_name} must be an integer") from exc
    return max(1, parsed)


def _parse_public_geoloc_feature_option(value: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    pieces = tuple(piece.strip() for piece in value.split(",") if piece.strip())
    if pieces and all(piece.startswith("-") for piece in pieces):
        return (), tuple(piece.removeprefix("-") for piece in pieces)
    return tuple(piece.removeprefix("-") for piece in pieces), ()


def _expand_public_geotag_track_log_option(value: str) -> tuple[Path, ...]:
    if glob.has_magic(value):
        pattern = Path(value)
        root = Path(pattern.anchor) if pattern.is_absolute() else Path()
        relative_pattern = pattern.relative_to(root) if pattern.is_absolute() else pattern
        matches = tuple(root.glob(relative_pattern.as_posix()))
        if not matches:
            raise argparse.ArgumentTypeError("No matching file found for -geotag option")
        return matches
    return (Path(value),)


def _parse_required_option_value(
    option: str,
    args: Sequence[str],
    option_index: int,
    *,
    allow_dash_prefixed: bool = False,
) -> str:
    value_index = option_index + 1
    if value_index >= len(args) or (args[value_index].startswith("-") and not allow_dash_prefixed):
        raise argparse.ArgumentTypeError(_missing_required_option_value_message(option))
    return args[value_index]


def _missing_required_option_value_message(option: str) -> str:
    if option.lstrip("-").lower() == "geotag":
        return "Expecting file name for -geotag option"
    return f"Expecting argument for {option} option"
