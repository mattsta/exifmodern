"""Public Geotag planning workflow.

This is intentionally a bounded public route. Explicit Geotime values are
applied to all targets. When Geotime is omitted, the upstream tool derives it from each
image, so this route only executes the source-backed JPEG EXIF cases where the
derived timestamp is timezone-qualified and deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.exif_scalar_write_plan import (
    ExifScalarAsciiWriteValue,
    ExifScalarDeleteWriteValue,
    ExifScalarRationalWriteValue,
    ExifScalarShortWriteValue,
    ExifScalarSignedRationalWriteValue,
    ExifScalarUndefinedWriteValue,
    ExifScalarWritePlan,
    ExifScalarWriteStep,
    ExifScalarWriteValue,
    build_exif_scalar_delete_plan,
)
from exifmodern.file_transaction import (
    FileWriteTransactionResult,
    write_bytes_in_place_transactionally,
)
from exifmodern.formats.geotag.application import (
    GeotagApplicationRequest,
    GeotagApplicationResult,
    GeotagSelectedFix,
    parse_geotime_value,
)
from exifmodern.formats.geotag.quicktime_destination import (
    GeotagQuickTimeRewriteResult,
    delete_quicktime_file_geotag_in_place,
    geotag_quicktime_coordinates_value,
    geotag_quicktime_destination_delete_assignments,
    is_quicktime_container_path,
    rewrite_quicktime_file_geotag_in_place,
)
from exifmodern.formats.geotag.synchronization import GeosyncPoint
from exifmodern.formats.geotag.write_effects import (
    GeotagWriteEffects,
    apply_geotag_write_effects,
)
from exifmodern.formats.geotag.xmp_destination import (
    GeotagJpegXmpRewriteResult,
    GeotagXmpSidecarRewriteResult,
    build_geotag_xmp_property_write_plan,
    delete_jpeg_file_embedded_xmp_geotag_in_place,
    delete_xmp_sidecar_file_geotag_in_place,
    rewrite_jpeg_file_embedded_xmp_geotag_in_place,
    rewrite_xmp_sidecar_file_geotag_in_place,
)
from exifmodern.formats.iptc.write_plan import (
    IptcApplicationWritePlan,
    IptcApplicationWriteStep,
    upsert_text_step,
)
from exifmodern.formats.jpeg.container import read_exif_ifd_tags, read_jpeg_segment_probes
from exifmodern.formats.jpeg.geotag_writer import (
    JpegGeotagRewriteResult,
    rewrite_jpeg_file_geotag_effects_in_place,
    rewrite_jpeg_geotag_effects,
)
from exifmodern.formats.jpeg.iptc_app13_writer import (
    rewrite_jpeg_iptc_application_creating_if_needed,
)
from exifmodern.formats.jpeg.xmp_property_writer import (
    rewrite_jpeg_xmp_properties_creating_if_needed,
)
from exifmodern.formats.xmp.property_write import (
    XmpGeneratedPropertyAssignment,
    build_generated_xmp_property_write_plan,
)
from exifmodern.json_types import JsonArray, JsonObject, JsonValue
from exifmodern.package_resources import generated_index_package_path
from exifmodern.public_api.models import Diagnostic, MetadataReadRequest, read_metadata
from exifmodern.public_interface.user_params import PublicUserParam, public_user_param_value
from exifmodern.services.geolocation_runtime import (
    GeolocationRuntimeRequest,
    GeolocationRuntimeResult,
    GeolocationRuntimeTags,
    load_geolocation_runtime_service,
)
from exifmodern.write_plan import (
    AsciiWriteValue,
    ByteWriteValue,
    ExifGpsTagName,
    ExifGpsWritePlan,
    ExifGpsWriteStep,
    GpsDeleteWriteValue,
    RationalArrayWriteValue,
    RationalWriteValue,
    TiffWriteValue,
    gps_delete_step,
)

from .tracklog import GeotagTrackLog, concatenate_track_logs, load_track_log_file

_EXIFTOOL_NAME = "Exif" + "Tool"
_IMAGE_EXIFTOOL_PATH = "../exiftool/lib/Image/Exif" + "Tool/"

PUBLIC_GEOTAG_SOURCE_REFERENCES: tuple[str, ...] = (
    "../exiftool/exiftool lines 1084-1108",
    "../exiftool/exiftool lines 1404-1412",
    "../exiftool/exiftool lines 7041-7066",
    f"{_IMAGE_EXIFTOOL_PATH}Geotag.pm lines 212-275",
    f"{_IMAGE_EXIFTOOL_PATH}Geotag.pm lines 1143-1535",
)
_GEOTIME_TZ_SUFFIX_PATTERN = re.compile(r"(Z|[-+]\d{2}:\d{2})$")
_GEOTIME_COPY_BRACED_EXPRESSION_PATTERN = re.compile(
    r"^\$\{(?P<tag>[-_0-9A-Za-z:]+)#?\}(?P<timezone>Z|[-+]\d{2}:\d{2})?$"
)
_GEOTIME_COPY_BARE_EXPRESSION_PATTERN = re.compile(
    r"^(?P<tag>[-_0-9A-Za-z:]+)#?(?P<timezone>Z|[-+]\d{2}:\d{2})?$"
)
_XMP_CAPABILITY_AUDIT_PATH = Path("artifacts/schema/exiftool-xmp-write-capability-audit.json")

type PublicGeotagCopyTimeSourceTag = Literal[
    "SubSecDateTimeOriginal",
    "SubSecCreateDate",
    "SubSecModifyDate",
    "DateTimeOriginal",
    "CreateDate",
    "ModifyDate",
    "FileModifyDate",
]

_PUBLIC_GEOTAG_COPY_TIME_TAGS: dict[str, PublicGeotagCopyTimeSourceTag] = {
    "subsecdatetimeoriginal": "SubSecDateTimeOriginal",
    "subseccreatedate": "SubSecCreateDate",
    "subsecmodifydate": "SubSecModifyDate",
    "datetimeoriginal": "DateTimeOriginal",
    "createdate": "CreateDate",
    "modifydate": "ModifyDate",
    "filemodifydate": "FileModifyDate",
}


@dataclass(frozen=True)
class PublicGeotagTrackLogLoad:
    track_log: GeotagTrackLog | None
    warning: str | None


@dataclass(frozen=True)
class PublicGeotagWorkflowRequest:
    track_log_path: Path | None
    geotime: str | None
    target_paths: tuple[Path, ...]
    geotime_copy_expression: str | None = None
    track_log_paths: tuple[Path, ...] = ()
    geo_max_ext_seconds: float = 1800.0
    geo_max_int_seconds: float = 1800.0
    geo_max_hdop: float | None = None
    geo_max_pdop: float | None = None
    geosync_offset_seconds: float = 0.0
    geosync_points: tuple[GeosyncPoint, ...] = ()
    geolocate_geotag: bool = False
    geolocation_package_path: Path | None = None
    geoloc_max_distance_km: float | None = None
    geoloc_min_population: float | None = None
    geoloc_feature_codes: tuple[str, ...] = ()
    geoloc_excluded_feature_codes: tuple[str, ...] = ()
    geoloc_limit: int = 1
    geoloc_alt_names: bool = True
    backup_policy: Literal["create_backup", "overwrite_original"] = "create_backup"
    backup_suffix: str = "_original"
    preserve_file_times: bool = False
    destination_group: Literal[
        "default", "EXIF", "XMP", "QuickTime", "ItemList", "UserData", "Keys"
    ] = "default"
    operation: Literal["apply", "delete"] = "apply"
    user_params: tuple[PublicUserParam, ...] = ()


@dataclass(frozen=True)
class PublicGeotagWorkflowResult:
    status: Literal["ok", "unsupported", "not_yet_implemented"]
    request: PublicGeotagWorkflowRequest
    diagnostics: tuple[Diagnostic, ...]
    plan: JsonObject | None


@dataclass(frozen=True)
class PublicGeotagImageGeotime:
    status: Literal[
        "ok",
        "missing_exif",
        "missing_timestamp",
        "local_timezone_required",
        "invalid_timestamp",
    ]
    raw: str | None
    source_tag: Literal["SubSecDateTimeOriginal", "DateTimeOriginal"] | None
    seconds: float | None
    no_date: bool
    timezone_qualified: bool
    warning: str | None


@dataclass(frozen=True)
class PublicGeotagPreparedTarget:
    path: Path
    image_geotime: PublicGeotagImageGeotime
    effects: GeotagWriteEffects


@dataclass(frozen=True)
class PublicGeotagCopyExpression:
    raw: str
    source_tag: PublicGeotagCopyTimeSourceTag | str
    timezone_suffix: str | None
    user_param_source: bool = False


@dataclass(frozen=True)
class PublicGeotagUnsupportedCopyExpression:
    expression: str
    reason: Literal[
        "perl_expression_outside_safe_boundary",
        "unsupported_source_tag",
        "unsupported_expression_syntax",
    ]
    message: str


@dataclass(frozen=True)
class PublicGeotagCopyGeotime:
    status: Literal[
        "ok",
        "missing_source_tag",
        "invalid_source_value",
        "local_timezone_required",
        "invalid_timestamp",
    ]
    raw: str | None
    source_tag: PublicGeotagCopyTimeSourceTag | str
    expression: str
    seconds: float | None
    no_date: bool
    timezone_qualified: bool
    warning: str | None


@dataclass(frozen=True)
class PublicGeotagPreparedCopyTarget:
    path: Path
    copy_geotime: PublicGeotagCopyGeotime
    effects: GeotagWriteEffects


@dataclass(frozen=True)
class PublicGeotagComposedRewriteResult:
    geotag_result: JpegGeotagRewriteResult
    changed_xmp_properties: int
    changed_iptc_datasets: int
    transaction: FileWriteTransactionResult


def plan_public_geotag_workflow(
    request: PublicGeotagWorkflowRequest,
) -> PublicGeotagWorkflowResult:
    diagnostics: list[Diagnostic] = []
    if not request.target_paths:
        diagnostics.append(
            Diagnostic(
                code="error_public_geotag_missing_target",
                message="public -geotag planning requires at least one target image path",
            )
        )
        return _public_geotag_result("unsupported", request, tuple(diagnostics), None)
    if request.operation == "delete":
        return _plan_public_geotag_delete_workflow(request)
    if _public_geotag_track_log_paths(request) == ():
        diagnostics.append(
            Diagnostic(
                code="error_public_geotag_missing_tracklog",
                message="public -geotag planning requires a track log path",
            )
        )
        return _public_geotag_result("unsupported", request, tuple(diagnostics), None)
    if request.geotime_copy_expression is not None:
        return _plan_public_geotag_copy_expression_workflow(request)
    if request.geotime is None:
        return _plan_public_geotag_omitted_geotime_workflow(request)
    geotime = parse_geotime_value(request.geotime)
    if geotime.status != "ok" or geotime.seconds is None:
        diagnostics.append(
            Diagnostic(
                code="error_public_geotag_invalid_geotime",
                message=geotime.warning or "Invalid Geotime value",
                details={"geotime": request.geotime},
            )
        )
        return _public_geotag_result("unsupported", request, tuple(diagnostics), None)
    track_load = _load_public_geotag_track_logs(request)
    if track_load.track_log is None:
        diagnostics.append(
            Diagnostic(
                code="error_public_geotag_tracklog_load_failed",
                message=track_load.warning or "Unable to load Geotag track log",
                details={"track_log": _public_geotag_track_log_path_text(request)},
            )
        )
        return _public_geotag_result("unsupported", request, tuple(diagnostics), None)
    effects = apply_geotag_write_effects(
        GeotagApplicationRequest(
            geotime_seconds=geotime.seconds,
            track_log=track_load.track_log,
            geosync_offset_seconds=request.geosync_offset_seconds,
            geosync_points=request.geosync_points,
            geo_max_ext_seconds=request.geo_max_ext_seconds,
            geo_max_int_seconds=request.geo_max_int_seconds,
            geo_max_hdop=request.geo_max_hdop,
            geo_max_pdop=request.geo_max_pdop,
        )
    )
    if effects.status != "ok":
        diagnostics.append(
            Diagnostic(
                code="error_public_geotag_application_failed",
                message=effects.application_result.warning or "Unable to apply Geotag track",
                details={"status": effects.status},
            )
        )
        return _public_geotag_result("unsupported", request, tuple(diagnostics), None)
    plan: JsonObject = {
        "target_paths": [path.as_posix() for path in request.target_paths],
        "track_log": {
            "path": _public_geotag_track_log_path_text(request),
            "paths": [path.as_posix() for path in _public_geotag_track_log_paths(request)],
            "format": track_load.track_log.format_name,
            "point_count": len(track_load.track_log.points),
            "has": list(track_load.track_log.has),
            "is_date": track_load.track_log.is_date,
            "no_date": track_load.track_log.no_date,
            "date_time_only": track_load.track_log.date_time_only,
        },
        "geotime": {
            "raw": request.geotime,
            "seconds": geotime.seconds,
            "no_date": geotime.no_date,
            "timezone_qualified": geotime.timezone_qualified,
        },
        "selected_fix": _selected_fix_json(effects.application_result.selected_fix),
        "geosync": _geosync_json(request),
        "geolocation_write": _geolocation_write_json(request, effects),
        "gps_write_steps": _gps_write_steps_json(effects.gps_write_plan),
        "exif_scalar_write_steps": _exif_scalar_write_steps_json(effects.exif_scalar_write_plan),
        "execution": _public_geotag_execution_json(request, effects),
    }
    return _public_geotag_result("ok", request, tuple(diagnostics), plan)


def _plan_public_geotag_copy_expression_workflow(
    request: PublicGeotagWorkflowRequest,
) -> PublicGeotagWorkflowResult:
    diagnostics: list[Diagnostic] = []
    if _public_geotag_track_log_paths(request) == ():
        diagnostics.append(
            Diagnostic(
                code="error_public_geotag_missing_tracklog",
                message="copy-expression public -Geotime requires a track log path",
            )
        )
        return _public_geotag_result("unsupported", request, tuple(diagnostics), None)
    if request.geotime_copy_expression is None:
        raise AssertionError("copy-expression workflow called without an expression")
    copy_expression = _parse_public_geotag_copy_expression(
        request.geotime_copy_expression,
        request.user_params,
    )
    if copy_expression is None:
        unsupported = _public_geotag_unsupported_copy_expression(
            request.geotime_copy_expression,
            request.user_params,
        )
        diagnostics.append(
            Diagnostic(
                code="public_geotag_unsupported_copy_expression",
                message=unsupported.message,
                details={
                    "expression": request.geotime_copy_expression,
                    "reason": unsupported.reason,
                    "supported_source_tags": list(_PUBLIC_GEOTAG_COPY_TIME_TAGS.values()),
                    "source": "../exiftool/html/geotag.html lines 220-221 and 319-337",
                    "safe_expression_boundary": (
                        "bounded tag-name and optional timezone suffix only; arbitrary Perl "
                        "copy expressions remain outside public geotag execution"
                    ),
                },
            )
        )
        return _public_geotag_result("unsupported", request, tuple(diagnostics), None)
    track_load = _load_public_geotag_track_logs(request)
    if track_load.track_log is None:
        diagnostics.append(
            Diagnostic(
                code="error_public_geotag_tracklog_load_failed",
                message=track_load.warning or "Unable to load Geotag track log",
                details={"track_log": _public_geotag_track_log_path_text(request)},
            )
        )
        return _public_geotag_result("unsupported", request, tuple(diagnostics), None)
    prepared_targets: list[PublicGeotagPreparedCopyTarget] = []
    for target_path in request.target_paths:
        copy_geotime = _public_geotag_copy_expression_geotime(
            target_path,
            copy_expression,
            request.user_params,
        )
        if copy_geotime.status != "ok" or copy_geotime.seconds is None:
            diagnostics.append(_public_geotag_copy_geotime_diagnostic(target_path, copy_geotime))
            continue
        effects = apply_geotag_write_effects(
            GeotagApplicationRequest(
                geotime_seconds=copy_geotime.seconds,
                track_log=track_load.track_log,
                geosync_offset_seconds=request.geosync_offset_seconds,
                geosync_points=request.geosync_points,
                geo_max_ext_seconds=request.geo_max_ext_seconds,
                geo_max_int_seconds=request.geo_max_int_seconds,
                geo_max_hdop=request.geo_max_hdop,
                geo_max_pdop=request.geo_max_pdop,
            )
        )
        if effects.status != "ok":
            diagnostics.append(
                Diagnostic(
                    code="error_public_geotag_application_failed",
                    message=effects.application_result.warning or "Unable to apply Geotag track",
                    details={
                        "status": effects.status,
                        "target_path": target_path.as_posix(),
                        "geotime_source_tag": copy_geotime.source_tag,
                    },
                )
            )
            continue
        prepared_targets.append(PublicGeotagPreparedCopyTarget(target_path, copy_geotime, effects))
    if diagnostics:
        status: Literal["unsupported", "not_yet_implemented"] = (
            "not_yet_implemented"
            if any(
                diagnostic.code == "public_geotag_copy_expression_local_timezone_required"
                for diagnostic in diagnostics
            )
            else "unsupported"
        )
        return _public_geotag_result(status, request, tuple(diagnostics), None)
    invalid_targets = _public_geotag_non_executable_targets(request.target_paths)
    if invalid_targets:
        invalid_execution = _public_geotag_invalid_jpeg_execution_json(request, invalid_targets)
        plan = _public_geotag_copy_expression_plan_json(
            request,
            track_load.track_log.format_name,
            len(track_load.track_log.points),
            list(track_load.track_log.has),
            track_load.track_log.is_date,
            track_load.track_log.no_date,
            track_load.track_log.date_time_only,
            copy_expression,
            prepared_targets,
            invalid_execution,
        )
        return _public_geotag_result("ok", request, (), plan)
    write_results: JsonArray = []
    for prepared_target in prepared_targets:
        rewrite_result = rewrite_jpeg_file_geotag_effects_in_place(
            prepared_target.path,
            prepared_target.effects,
            request.backup_policy,
            request.backup_suffix,
            request.preserve_file_times,
        )
        write_results.append(_public_geotag_write_result_json(prepared_target.path, rewrite_result))
    execution: JsonObject = {
        "mode": "mutate_in_place",
        "backup_policy": request.backup_policy,
        "backup_suffix": request.backup_suffix,
        "preserve_file_times": request.preserve_file_times,
        "changed_paths": [path.as_posix() for path in request.target_paths],
        "write_results": write_results,
    }
    plan = _public_geotag_copy_expression_plan_json(
        request,
        track_load.track_log.format_name,
        len(track_load.track_log.points),
        list(track_load.track_log.has),
        track_load.track_log.is_date,
        track_load.track_log.no_date,
        track_load.track_log.date_time_only,
        copy_expression,
        prepared_targets,
        execution,
    )
    return _public_geotag_result("ok", request, (), plan)


def _plan_public_geotag_omitted_geotime_workflow(
    request: PublicGeotagWorkflowRequest,
) -> PublicGeotagWorkflowResult:
    diagnostics: list[Diagnostic] = []
    if _public_geotag_track_log_paths(request) == ():
        diagnostics.append(
            Diagnostic(
                code="error_public_geotag_missing_tracklog",
                message="omitted public -Geotime requires a track log path",
            )
        )
        return _public_geotag_result("unsupported", request, tuple(diagnostics), None)
    invalid_targets = _public_geotag_non_executable_targets(request.target_paths)
    if invalid_targets:
        diagnostics.append(
            Diagnostic(
                code="public_geotag_geotime_required",
                message=(
                    "public -geotag can omit -Geotime only when every target is an "
                    "existing JPEG with a source-backed image timestamp; otherwise "
                    "provide explicit -Geotime=VALUE"
                ),
                details={
                    "source": "../exiftool/exiftool lines 1404-1412",
                    "target_paths": [path.as_posix() for path in invalid_targets],
                },
            )
        )
        return _public_geotag_result("not_yet_implemented", request, tuple(diagnostics), None)
    track_load = _load_public_geotag_track_logs(request)
    if track_load.track_log is None:
        diagnostics.append(
            Diagnostic(
                code="error_public_geotag_tracklog_load_failed",
                message=track_load.warning or "Unable to load Geotag track log",
                details={"track_log": _public_geotag_track_log_path_text(request)},
            )
        )
        return _public_geotag_result("unsupported", request, tuple(diagnostics), None)
    prepared_targets: list[PublicGeotagPreparedTarget] = []
    for target_path in request.target_paths:
        image_geotime = _public_geotag_image_geotime(target_path)
        if image_geotime.status != "ok" or image_geotime.seconds is None:
            diagnostics.append(_public_geotag_image_geotime_diagnostic(target_path, image_geotime))
            continue
        effects = apply_geotag_write_effects(
            GeotagApplicationRequest(
                geotime_seconds=image_geotime.seconds,
                track_log=track_load.track_log,
                geosync_offset_seconds=request.geosync_offset_seconds,
                geosync_points=request.geosync_points,
                geo_max_ext_seconds=request.geo_max_ext_seconds,
                geo_max_int_seconds=request.geo_max_int_seconds,
                geo_max_hdop=request.geo_max_hdop,
                geo_max_pdop=request.geo_max_pdop,
            )
        )
        if effects.status != "ok":
            diagnostics.append(
                Diagnostic(
                    code="error_public_geotag_application_failed",
                    message=effects.application_result.warning or "Unable to apply Geotag track",
                    details={
                        "status": effects.status,
                        "target_path": target_path.as_posix(),
                        "geotime_source_tag": image_geotime.source_tag,
                    },
                )
            )
            continue
        prepared_targets.append(PublicGeotagPreparedTarget(target_path, image_geotime, effects))
    if diagnostics:
        return _public_geotag_result("not_yet_implemented", request, tuple(diagnostics), None)
    target_plans: JsonArray = []
    write_results: JsonArray = []
    for prepared_target in prepared_targets:
        rewrite_result = rewrite_jpeg_file_geotag_effects_in_place(
            prepared_target.path,
            prepared_target.effects,
            request.backup_policy,
            request.backup_suffix,
            request.preserve_file_times,
        )
        target_plans.append(
            {
                "target_path": prepared_target.path.as_posix(),
                "geotime": _image_geotime_json(prepared_target.image_geotime),
                "geosync": _geosync_json(request),
                "geolocation_write": _geolocation_write_json(request, prepared_target.effects),
                "selected_fix": _selected_fix_json(
                    prepared_target.effects.application_result.selected_fix
                ),
                "gps_write_steps": _gps_write_steps_json(prepared_target.effects.gps_write_plan),
                "exif_scalar_write_steps": _exif_scalar_write_steps_json(
                    prepared_target.effects.exif_scalar_write_plan
                ),
            }
        )
        write_results.append(_public_geotag_write_result_json(prepared_target.path, rewrite_result))
    plan: JsonObject = {
        "target_paths": [path.as_posix() for path in request.target_paths],
        "track_log": {
            "path": _public_geotag_track_log_path_text(request),
            "paths": [path.as_posix() for path in _public_geotag_track_log_paths(request)],
            "format": track_load.track_log.format_name,
            "point_count": len(track_load.track_log.points),
            "has": list(track_load.track_log.has),
            "is_date": track_load.track_log.is_date,
            "no_date": track_load.track_log.no_date,
            "date_time_only": track_load.track_log.date_time_only,
        },
        "geotime": {
            "raw": None,
            "source": "omitted",
            "lookup_priority": ["SubSecDateTimeOriginal", "DateTimeOriginal"],
        },
        "target_plans": target_plans,
        "execution": {
            "mode": "mutate_in_place",
            "backup_policy": request.backup_policy,
            "backup_suffix": request.backup_suffix,
            "preserve_file_times": request.preserve_file_times,
            "changed_paths": [path.as_posix() for path in request.target_paths],
            "write_results": write_results,
        },
    }
    return _public_geotag_result("ok", request, tuple(diagnostics), plan)


def _plan_public_geotag_delete_workflow(
    request: PublicGeotagWorkflowRequest,
) -> PublicGeotagWorkflowResult:
    execution = _public_geotag_delete_execution_json(request)
    plan: JsonObject = {
        "target_paths": [path.as_posix() for path in request.target_paths],
        "geotime": {
            "raw": "",
            "source": "delete",
            "deleted_tags": list(_DELETE_GEOTAG_TAG_NAMES),
        },
        "gps_write_steps": _gps_write_steps_json(_delete_geotag_gps_write_plan()),
        "exif_scalar_write_steps": _exif_scalar_write_steps_json(
            _delete_geotag_exif_scalar_write_plan()
        ),
        "execution": execution,
    }
    return _public_geotag_result("ok", request, (), plan)


def public_geotag_workflow_result_to_json_value(
    result: PublicGeotagWorkflowResult,
) -> JsonObject:
    payload: JsonObject = {
        "status": result.status,
        "request": {
            "track_log_path": None
            if result.request.track_log_path is None
            else result.request.track_log_path.as_posix(),
            "track_log_paths": [
                path.as_posix() for path in _public_geotag_track_log_paths(result.request)
            ],
            "geotime": result.request.geotime,
            "geotime_copy_expression": result.request.geotime_copy_expression,
            "target_paths": [path.as_posix() for path in result.request.target_paths],
            "geo_max_ext_seconds": result.request.geo_max_ext_seconds,
            "geo_max_int_seconds": result.request.geo_max_int_seconds,
            "geo_max_hdop": result.request.geo_max_hdop,
            "geo_max_pdop": result.request.geo_max_pdop,
            "geosync_offset_seconds": result.request.geosync_offset_seconds,
            "geosync_points": [
                {
                    "image_time_seconds": point.image_time_seconds,
                    "offset_seconds": point.offset_seconds,
                }
                for point in result.request.geosync_points
            ],
            "geolocate_geotag": result.request.geolocate_geotag,
            "geolocation_package_path": _public_geotag_geolocation_package_path(
                result.request
            ).as_posix(),
            "geoloc_max_distance_km": result.request.geoloc_max_distance_km,
            "geoloc_min_population": result.request.geoloc_min_population,
            "geoloc_feature_codes": list(result.request.geoloc_feature_codes),
            "geoloc_excluded_feature_codes": list(result.request.geoloc_excluded_feature_codes),
            "geoloc_limit": result.request.geoloc_limit,
            "geoloc_alt_names": result.request.geoloc_alt_names,
            "backup_policy": result.request.backup_policy,
            "backup_suffix": result.request.backup_suffix,
            "preserve_file_times": result.request.preserve_file_times,
            "destination_group": result.request.destination_group,
            "operation": result.request.operation,
        },
        "diagnostics": [_diagnostic_json(diagnostic) for diagnostic in result.diagnostics],
    }
    if result.plan is not None:
        payload["plan"] = result.plan
    return payload


def _public_geotag_result(
    status: Literal["ok", "unsupported", "not_yet_implemented"],
    request: PublicGeotagWorkflowRequest,
    diagnostics: tuple[Diagnostic, ...],
    plan: JsonObject | None,
) -> PublicGeotagWorkflowResult:
    return PublicGeotagWorkflowResult(
        status=status,
        request=request,
        diagnostics=diagnostics,
        plan=plan,
    )


def _public_geotag_track_log_paths(request: PublicGeotagWorkflowRequest) -> tuple[Path, ...]:
    if request.track_log_paths:
        return request.track_log_paths
    if request.track_log_path is None:
        return ()
    return (request.track_log_path,)


def _public_geotag_track_log_path_text(request: PublicGeotagWorkflowRequest) -> str:
    return ",".join(path.as_posix() for path in _public_geotag_track_log_paths(request))


def _load_public_geotag_track_logs(
    request: PublicGeotagWorkflowRequest,
) -> PublicGeotagTrackLogLoad:
    loaded_track_logs: list[GeotagTrackLog] = []
    for path in _public_geotag_track_log_paths(request):
        load_result = load_track_log_file(path)
        if load_result.track_log is None:
            return PublicGeotagTrackLogLoad(track_log=None, warning=load_result.warning)
        loaded_track_logs.append(load_result.track_log)
    if not loaded_track_logs:
        return PublicGeotagTrackLogLoad(track_log=None, warning="No Geotag track log path")
    return PublicGeotagTrackLogLoad(
        track_log=concatenate_track_logs(tuple(loaded_track_logs)),
        warning=None,
    )


def _public_geotag_execution_json(
    request: PublicGeotagWorkflowRequest,
    effects: GeotagWriteEffects,
) -> JsonObject:
    if request.destination_group == "XMP":
        return _public_geotag_xmp_execution_json(request, effects)
    if request.destination_group in {"QuickTime", "ItemList", "UserData", "Keys"}:
        return _public_geotag_quicktime_execution_json(request, effects)
    invalid_targets = _public_geotag_non_executable_targets(request.target_paths)
    if invalid_targets:
        return _public_geotag_invalid_jpeg_execution_json(request, invalid_targets)
    if request.geolocate_geotag:
        return _public_geotag_composed_geolocate_execution_json(request, effects)
    write_results: JsonArray = []
    for target_path in request.target_paths:
        rewrite_result = rewrite_jpeg_file_geotag_effects_in_place(
            target_path,
            effects,
            request.backup_policy,
            request.backup_suffix,
            request.preserve_file_times,
        )
        write_results.append(_public_geotag_write_result_json(target_path, rewrite_result))
    return {
        "mode": "mutate_in_place",
        "backup_policy": request.backup_policy,
        "backup_suffix": request.backup_suffix,
        "preserve_file_times": request.preserve_file_times,
        "changed_paths": [path.as_posix() for path in request.target_paths],
        "write_results": write_results,
    }


def _public_geotag_composed_geolocate_execution_json(
    request: PublicGeotagWorkflowRequest,
    effects: GeotagWriteEffects,
) -> JsonObject:
    result = _resolve_public_geotag_geolocation(request, effects)
    if not result.resolved or not result.tags:
        return {
            "mode": "plan_only",
            "deferred": "Geolocate=geotag requires one package-backed coordinate match.",
            "geolocation_status": result.status,
            "diagnostics": [
                {
                    "code": diagnostic.code,
                    "message": diagnostic.message,
                    "candidate_count": diagnostic.candidate_count,
                }
                for diagnostic in result.diagnostics
            ],
        }
    tags = result.tags[0]
    write_results: JsonArray = []
    for target_path in request.target_paths:
        rewrite_result = _rewrite_jpeg_geotag_geolocate_composed_in_place(
            target_path,
            effects,
            tags,
            request.backup_policy,
            request.backup_suffix,
            request.preserve_file_times,
        )
        write_results.append(_public_geotag_composed_write_result_json(target_path, rewrite_result))
    return {
        "mode": "mutate_in_place",
        "route": "same_target_geotag_xmp_iptc_composition",
        "backup_policy": request.backup_policy,
        "backup_suffix": request.backup_suffix,
        "preserve_file_times": request.preserve_file_times,
        "changed_paths": [path.as_posix() for path in request.target_paths],
        "write_results": write_results,
    }


def _rewrite_jpeg_geotag_geolocate_composed_in_place(
    target_path: Path,
    effects: GeotagWriteEffects,
    tags: GeolocationRuntimeTags,
    backup_policy: Literal["create_backup", "overwrite_original"],
    backup_suffix: str,
    preserve_file_times: bool,
) -> PublicGeotagComposedRewriteResult:
    geotag_result = rewrite_jpeg_geotag_effects(target_path.read_bytes(), effects)
    xmp_plan = build_generated_xmp_property_write_plan(
        _XMP_CAPABILITY_AUDIT_PATH,
        _geolocation_xmp_assignments(tags),
    )
    if xmp_plan.generated_diagnostics:
        reasons = ", ".join(diagnostic.reason for diagnostic in xmp_plan.generated_diagnostics)
        raise ValueError(f"Generated XMP geolocation write plan failed: {reasons}")
    xmp_result = rewrite_jpeg_xmp_properties_creating_if_needed(geotag_result.data, xmp_plan)
    iptc_result = rewrite_jpeg_iptc_application_creating_if_needed(
        xmp_result.data,
        IptcApplicationWritePlan(_geolocation_iptc_steps(tags)),
    )
    transaction = write_bytes_in_place_transactionally(
        target_path,
        iptc_result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return PublicGeotagComposedRewriteResult(
        geotag_result=geotag_result,
        changed_xmp_properties=xmp_result.changed_xmp_properties,
        changed_iptc_datasets=iptc_result.changed_iptc_datasets,
        transaction=transaction,
    )


def _geolocation_xmp_assignments(
    tags: GeolocationRuntimeTags,
) -> tuple[XmpGeneratedPropertyAssignment, ...]:
    assignments = [
        XmpGeneratedPropertyAssignment("XMP-photoshop:City", tags.city),
        XmpGeneratedPropertyAssignment("XMP-photoshop:State", tags.region or ""),
        XmpGeneratedPropertyAssignment("XMP-iptcCore:CountryCode", tags.country_code),
        XmpGeneratedPropertyAssignment("XMP-photoshop:Country", tags.country or ""),
    ]
    return tuple(assignment for assignment in assignments if assignment.value)


def _geolocation_iptc_steps(tags: GeolocationRuntimeTags) -> tuple[IptcApplicationWriteStep, ...]:
    steps = [
        upsert_text_step("City", (tags.city,)),
        upsert_text_step("Province-State", (tags.region or "",)),
        upsert_text_step("Country-PrimaryLocationCode", (_iptc_country_code(tags),)),
        upsert_text_step("Country-PrimaryLocationName", (tags.country or "",)),
    ]
    return tuple(step for step in steps if step.values[0])


def _iptc_country_code(tags: GeolocationRuntimeTags) -> str:
    if len(tags.country_code.encode("latin-1")) == 2:
        return f"{tags.country_code} "
    return tags.country_code


def _public_geotag_invalid_jpeg_execution_json(
    request: PublicGeotagWorkflowRequest,
    invalid_targets: tuple[Path, ...],
) -> JsonObject:
    missing_paths: JsonArray = [
        path.as_posix() for path in request.target_paths if not path.is_file()
    ]
    invalid_jpeg_paths: JsonArray = [
        path.as_posix()
        for path in invalid_targets
        if path.is_file() and not _public_geotag_target_has_jpeg_soi(path)
    ]
    execution: JsonObject = {
        "mode": "plan_only",
        "deferred": (
            "public -geotag mutation requires every target path to be an existing JPEG "
            "file before the bounded JPEG geotag writer is invoked"
        ),
    }
    if missing_paths:
        execution["missing_target_paths"] = missing_paths
    if invalid_jpeg_paths:
        execution["invalid_jpeg_paths"] = invalid_jpeg_paths
    return execution


_DELETE_GEOTAG_TAG_NAMES: tuple[ExifGpsTagName, ...] = (
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


def _delete_geotag_gps_write_plan() -> ExifGpsWritePlan:
    return ExifGpsWritePlan(
        schema_version=1,
        generated_at_epoch=0,
        status="planned",
        scope="exif_gps_plan_only",
        steps=tuple(gps_delete_step(tag_name) for tag_name in _DELETE_GEOTAG_TAG_NAMES),
        container_actions=(),
        safety_gates=(),
    )


def _delete_geotag_exif_scalar_write_plan() -> ExifScalarWritePlan:
    return build_exif_scalar_delete_plan(
        delete_image_description=False,
        delete_orientation=False,
        delete_date_time_original=False,
        delete_camera_elevation_angle=True,
    )


def _delete_geotag_effects() -> GeotagWriteEffects:
    return GeotagWriteEffects(
        application_result=GeotagApplicationResult(
            status="ok",
            selected_fix=None,
            write_plan=None,
            warning=None,
        ),
        gps_write_plan=_delete_geotag_gps_write_plan(),
        exif_scalar_write_plan=_delete_geotag_exif_scalar_write_plan(),
    )


def _public_geotag_delete_execution_json(
    request: PublicGeotagWorkflowRequest,
) -> JsonObject:
    if request.destination_group == "XMP":
        return _public_geotag_xmp_delete_execution_json(request)
    if request.destination_group in {"QuickTime", "ItemList", "UserData", "Keys"}:
        return _public_geotag_quicktime_delete_execution_json(request)
    invalid_targets = _public_geotag_non_executable_targets(request.target_paths)
    if invalid_targets:
        return _public_geotag_invalid_jpeg_execution_json(request, invalid_targets)
    effects = _delete_geotag_effects()
    write_results: JsonArray = []
    for target_path in request.target_paths:
        rewrite_result = rewrite_jpeg_file_geotag_effects_in_place(
            target_path,
            effects,
            request.backup_policy,
            request.backup_suffix,
            request.preserve_file_times,
        )
        write_results.append(_public_geotag_write_result_json(target_path, rewrite_result))
    return {
        "mode": "mutate_in_place",
        "destination_group": request.destination_group,
        "backup_policy": request.backup_policy,
        "backup_suffix": request.backup_suffix,
        "preserve_file_times": request.preserve_file_times,
        "changed_paths": [path.as_posix() for path in request.target_paths],
        "write_results": write_results,
    }


def _public_geotag_xmp_delete_execution_json(
    request: PublicGeotagWorkflowRequest,
) -> JsonObject:
    invalid_targets = tuple(
        path
        for path in request.target_paths
        if not path.is_file()
        or (path.suffix.lower() != ".xmp" and not _public_geotag_target_has_structural_jpeg(path))
    )
    if invalid_targets:
        execution: JsonObject = {
            "mode": "plan_only",
            "destination_group": "XMP",
            "deferred": (
                "XMP delete-all-geotags execution is limited to existing .xmp sidecar "
                "packets and JPEG embedded XMP APP1 packets."
            ),
        }
        missing_paths: JsonArray = [
            path.as_posix() for path in request.target_paths if not path.is_file()
        ]
        non_xmp_paths: JsonArray = [
            path.as_posix()
            for path in invalid_targets
            if path.is_file()
            and path.suffix.lower() != ".xmp"
            and not _public_geotag_target_has_structural_jpeg(path)
        ]
        if missing_paths:
            execution["missing_target_paths"] = missing_paths
        if non_xmp_paths:
            execution["non_xmp_sidecar_paths"] = non_xmp_paths
        return execution
    write_results: JsonArray = []
    for target_path in request.target_paths:
        if target_path.suffix.lower() == ".xmp":
            sidecar_result = delete_xmp_sidecar_file_geotag_in_place(
                target_path,
                request.backup_policy,
                request.backup_suffix,
                request.preserve_file_times,
            )
            write_results.append(_public_geotag_xmp_write_result_json(target_path, sidecar_result))
        else:
            jpeg_xmp_result = delete_jpeg_file_embedded_xmp_geotag_in_place(
                target_path,
                request.backup_policy,
                request.backup_suffix,
                request.preserve_file_times,
            )
            write_results.append(
                _public_geotag_jpeg_xmp_write_result_json(target_path, jpeg_xmp_result)
            )
    return {
        "mode": "mutate_in_place",
        "destination_group": "XMP",
        "route": "xmp_sidecar_or_jpeg_embedded_xmp",
        "backup_policy": request.backup_policy,
        "backup_suffix": request.backup_suffix,
        "preserve_file_times": request.preserve_file_times,
        "changed_paths": [path.as_posix() for path in request.target_paths],
        "write_results": write_results,
    }


def _public_geotag_quicktime_delete_execution_json(
    request: PublicGeotagWorkflowRequest,
) -> JsonObject:
    invalid_targets = tuple(
        path
        for path in request.target_paths
        if not path.is_file() or not is_quicktime_container_path(path)
    )
    destination_group = _public_geotag_quicktime_destination_group(request.destination_group)
    route: JsonObject = {
        "target_tags": [
            assignment[1:-1]
            for assignment in geotag_quicktime_destination_delete_assignments(destination_group)
        ],
    }
    if invalid_targets:
        execution: JsonObject = {
            "mode": "plan_only",
            "destination_group": request.destination_group,
            "quicktime_delete_route": route,
            "deferred": (
                "QuickTime delete-all-geotags remains deferred for invalid containers; "
                "GPSCoordinates delete execution is limited to existing QuickTime/ISO "
                "BMFF containers with top-level ftyp and moov atoms."
            ),
        }
        missing_paths: JsonArray = [
            path.as_posix() for path in request.target_paths if not path.is_file()
        ]
        invalid_quicktime_paths: JsonArray = [
            path.as_posix() for path in invalid_targets if path.is_file()
        ]
        if missing_paths:
            execution["missing_target_paths"] = missing_paths
        if invalid_quicktime_paths:
            execution["invalid_quicktime_paths"] = invalid_quicktime_paths
        return execution
    write_results: JsonArray = []
    for target_path in request.target_paths:
        rewrite_result = delete_quicktime_file_geotag_in_place(
            target_path,
            destination_group,
            request.backup_policy,
            request.backup_suffix,
            request.preserve_file_times,
        )
        write_results.append(
            _public_geotag_quicktime_write_result_json(target_path, rewrite_result)
        )
    return {
        "mode": "mutate_in_place",
        "destination_group": request.destination_group,
        "quicktime_delete_route": route,
        "backup_policy": request.backup_policy,
        "backup_suffix": request.backup_suffix,
        "preserve_file_times": request.preserve_file_times,
        "changed_paths": [path.as_posix() for path in request.target_paths],
        "write_results": write_results,
    }


def _public_geotag_xmp_execution_json(
    request: PublicGeotagWorkflowRequest,
    effects: GeotagWriteEffects,
) -> JsonObject:
    invalid_targets = tuple(
        path
        for path in request.target_paths
        if not path.is_file()
        or (path.suffix.lower() != ".xmp" and not _public_geotag_target_has_structural_jpeg(path))
    )
    plan = build_geotag_xmp_property_write_plan(effects)
    xmp_plan_json: JsonObject = {"property_names": [step.property_name for step in plan.steps]}
    if invalid_targets:
        execution: JsonObject = {
            "mode": "plan_only",
            "destination_group": "XMP",
            "xmp_write_plan": xmp_plan_json,
            "deferred": (
                "XMP:Geotime execution is limited to existing .xmp sidecar packets "
                "and JPEG embedded XMP APP1 packets; other embedded XMP containers "
                "do not have a bounded public geotag route."
            ),
        }
        missing_paths: JsonArray = [
            path.as_posix() for path in request.target_paths if not path.is_file()
        ]
        non_xmp_paths: JsonArray = [
            path.as_posix()
            for path in invalid_targets
            if path.is_file()
            and path.suffix.lower() != ".xmp"
            and not _public_geotag_target_has_structural_jpeg(path)
        ]
        if missing_paths:
            execution["missing_target_paths"] = missing_paths
        if non_xmp_paths:
            execution["non_xmp_sidecar_paths"] = non_xmp_paths
        return execution
    write_results: JsonArray = []
    for target_path in request.target_paths:
        if target_path.suffix.lower() == ".xmp":
            sidecar_result = rewrite_xmp_sidecar_file_geotag_in_place(
                target_path,
                effects,
                request.backup_policy,
                request.backup_suffix,
                request.preserve_file_times,
            )
            write_results.append(_public_geotag_xmp_write_result_json(target_path, sidecar_result))
        else:
            jpeg_xmp_result = rewrite_jpeg_file_embedded_xmp_geotag_in_place(
                target_path,
                effects,
                request.backup_policy,
                request.backup_suffix,
                request.preserve_file_times,
            )
            write_results.append(
                _public_geotag_jpeg_xmp_write_result_json(target_path, jpeg_xmp_result)
            )
    return {
        "mode": "mutate_in_place",
        "destination_group": "XMP",
        "route": "xmp_sidecar_or_jpeg_embedded_xmp",
        "backup_policy": request.backup_policy,
        "backup_suffix": request.backup_suffix,
        "preserve_file_times": request.preserve_file_times,
        "changed_paths": [path.as_posix() for path in request.target_paths],
        "xmp_write_plan": xmp_plan_json,
        "write_results": write_results,
    }


def _public_geotag_quicktime_execution_json(
    request: PublicGeotagWorkflowRequest,
    effects: GeotagWriteEffects,
) -> JsonObject:
    coords = geotag_quicktime_coordinates_value(effects)
    preferred_group = (
        "ItemList" if request.destination_group == "QuickTime" else request.destination_group
    )
    invalid_targets = tuple(
        path
        for path in request.target_paths
        if not path.is_file() or not is_quicktime_container_path(path)
    )
    route: JsonObject = {
        "target_tag": f"{preferred_group}:GPSCoordinates",
        "value_conv": coords,
    }
    if coords is None:
        return {
            "mode": "plan_only",
            "destination_group": request.destination_group,
            "quicktime_route": route,
            "deferred": "QuickTime geotag requires a selected latitude/longitude fix.",
        }
    if invalid_targets:
        execution: JsonObject = {
            "mode": "plan_only",
            "destination_group": request.destination_group,
            "quicktime_route": route,
            "deferred": (
                "QuickTime geotag execution needs a container-aware in-place atom transaction "
                "route and is limited to existing QuickTime/ISO BMFF containers with "
                "top-level ftyp and moov atoms."
            ),
        }
        missing_paths: JsonArray = [
            path.as_posix() for path in request.target_paths if not path.is_file()
        ]
        invalid_quicktime_paths: JsonArray = [
            path.as_posix() for path in invalid_targets if path.is_file()
        ]
        if missing_paths:
            execution["missing_target_paths"] = missing_paths
        if invalid_quicktime_paths:
            execution["invalid_quicktime_paths"] = invalid_quicktime_paths
        return execution
    write_results: JsonArray = []
    destination_group = _public_geotag_quicktime_destination_group(request.destination_group)
    for target_path in request.target_paths:
        rewrite_result = rewrite_quicktime_file_geotag_in_place(
            target_path,
            effects,
            destination_group,
            request.backup_policy,
            request.backup_suffix,
            request.preserve_file_times,
        )
        write_results.append(
            _public_geotag_quicktime_write_result_json(target_path, rewrite_result)
        )
    return {
        "mode": "mutate_in_place",
        "destination_group": request.destination_group,
        "quicktime_route": route,
        "backup_policy": request.backup_policy,
        "backup_suffix": request.backup_suffix,
        "preserve_file_times": request.preserve_file_times,
        "changed_paths": [path.as_posix() for path in request.target_paths],
        "write_results": write_results,
    }


def _public_geotag_quicktime_destination_group(
    destination_group: Literal[
        "default", "EXIF", "XMP", "QuickTime", "ItemList", "UserData", "Keys"
    ],
) -> Literal["QuickTime", "ItemList", "UserData", "Keys"]:
    if destination_group == "QuickTime":
        return "QuickTime"
    if destination_group == "ItemList":
        return "ItemList"
    if destination_group == "UserData":
        return "UserData"
    if destination_group == "Keys":
        return destination_group
    raise AssertionError(f"not a QuickTime destination group: {destination_group}")


def _public_geotag_non_executable_targets(target_paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(
        path
        for path in target_paths
        if not path.is_file() or not _public_geotag_target_has_jpeg_soi(path)
    )


def _public_geotag_target_has_jpeg_soi(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(2) == b"\xff\xd8"


def _public_geotag_target_has_structural_jpeg(path: Path) -> bool:
    try:
        return bool(read_jpeg_segment_probes(path, prefix_length=0))
    except ValueError:
        return False


def _parse_public_geotag_copy_expression(
    expression: str,
    user_params: tuple[PublicUserParam, ...] = (),
) -> PublicGeotagCopyExpression | None:
    match = _GEOTIME_COPY_BRACED_EXPRESSION_PATTERN.match(expression)
    if match is None:
        match = _GEOTIME_COPY_BARE_EXPRESSION_PATTERN.match(expression)
    if match is None:
        return None
    source_tag = _canonical_public_geotag_copy_time_tag(match.group("tag"))
    if source_tag is None and public_user_param_value(user_params, match.group("tag")) is None:
        return None
    if source_tag is None:
        return PublicGeotagCopyExpression(
            raw=expression,
            source_tag=match.group("tag"),
            timezone_suffix=match.group("timezone"),
            user_param_source=True,
        )
    return PublicGeotagCopyExpression(
        raw=expression,
        source_tag=source_tag,
        timezone_suffix=match.group("timezone"),
    )


def _public_geotag_unsupported_copy_expression(
    expression: str,
    user_params: tuple[PublicUserParam, ...] = (),
) -> PublicGeotagUnsupportedCopyExpression:
    if ";" in expression or "$_" in expression or "=>" in expression:
        return PublicGeotagUnsupportedCopyExpression(
            expression=expression,
            reason="perl_expression_outside_safe_boundary",
            message=(
                "public -geotag does not execute advanced Perl -Geotime copy "
                "expressions; use a bounded tag copy expression plus an optional "
                "literal timezone suffix"
            ),
        )
    match = _GEOTIME_COPY_BRACED_EXPRESSION_PATTERN.match(expression)
    if match is None:
        match = _GEOTIME_COPY_BARE_EXPRESSION_PATTERN.match(expression)
    if match is not None:
        source_tag = _canonical_public_geotag_copy_time_tag(match.group("tag"))
        if source_tag is None and public_user_param_value(user_params, match.group("tag")) is None:
            return PublicGeotagUnsupportedCopyExpression(
                expression=expression,
                reason="unsupported_source_tag",
                message=(
                    "public -geotag copy-expression -Geotime supports only known "
                    "timestamp source tags or explicit -userParam values"
                ),
            )
    return PublicGeotagUnsupportedCopyExpression(
        expression=expression,
        reason="unsupported_expression_syntax",
        message=(
            "public -geotag supports only bounded same-file timestamp copy "
            "expressions such as -Geotime<${DateTimeOriginal}+02:00"
        ),
    )


def _canonical_public_geotag_copy_time_tag(
    raw_tag_name: str,
) -> PublicGeotagCopyTimeSourceTag | None:
    unqualified_tag = raw_tag_name.rpartition(":")[2]
    return _PUBLIC_GEOTAG_COPY_TIME_TAGS.get(unqualified_tag.lower())


def _public_geotag_copy_expression_geotime(
    path: Path,
    expression: PublicGeotagCopyExpression,
    user_params: tuple[PublicUserParam, ...] = (),
) -> PublicGeotagCopyGeotime:
    if expression.user_param_source:
        raw_user_value = public_user_param_value(user_params, expression.source_tag)
        source_value = str(raw_user_value) if raw_user_value is not None else None
    else:
        source_tag = _canonical_public_geotag_copy_time_tag(expression.source_tag)
        if source_tag is None:
            source_value = None
        else:
            source_value = _public_geotag_read_copy_source_value(path, source_tag)
    if source_value is None:
        return PublicGeotagCopyGeotime(
            status="missing_source_tag",
            raw=None,
            source_tag=expression.source_tag,
            expression=expression.raw,
            seconds=None,
            no_date=False,
            timezone_qualified=False,
            warning=f"{expression.source_tag} is not available from public read extraction",
        )
    geotime_value = _public_geotag_copy_expression_value(source_value, expression.timezone_suffix)
    geotime = parse_geotime_value(geotime_value)
    if geotime.status != "ok" or geotime.seconds is None:
        status: Literal["local_timezone_required", "invalid_timestamp"]
        status = (
            "local_timezone_required"
            if geotime.status == "local_timezone_required"
            else "invalid_timestamp"
        )
        return PublicGeotagCopyGeotime(
            status=status,
            raw=geotime_value,
            source_tag=expression.source_tag,
            expression=expression.raw,
            seconds=None,
            no_date=geotime.no_date,
            timezone_qualified=geotime.timezone_qualified,
            warning=geotime.warning,
        )
    return PublicGeotagCopyGeotime(
        status="ok",
        raw=geotime_value,
        source_tag=expression.source_tag,
        expression=expression.raw,
        seconds=geotime.seconds,
        no_date=geotime.no_date,
        timezone_qualified=geotime.timezone_qualified,
        warning=None,
    )


def _public_geotag_read_copy_source_value(
    path: Path,
    source_tag: PublicGeotagCopyTimeSourceTag,
) -> str | None:
    result = read_metadata(MetadataReadRequest(paths=(path,), tags=(source_tag,)))
    if not result.records:
        return None
    value = result.records[0].values.get(source_tag)
    if isinstance(value, str):
        return value
    return None


def _public_geotag_copy_expression_value(source_value: str, timezone_suffix: str | None) -> str:
    if timezone_suffix is None or _GEOTIME_TZ_SUFFIX_PATTERN.search(source_value):
        return source_value
    return f"{source_value}{timezone_suffix}"


def _public_geotag_image_geotime(path: Path) -> PublicGeotagImageGeotime:
    try:
        exif_values = read_exif_ifd_tags(path)
    except ValueError as exc:
        return PublicGeotagImageGeotime(
            status="missing_exif",
            raw=None,
            source_tag=None,
            seconds=None,
            no_date=False,
            timezone_qualified=False,
            warning=str(exc),
        )
    date_time_original = exif_values.get("DateTimeOriginal")
    subsec_time_original = exif_values.get("SubSecTimeOriginal")
    source_tag: Literal["SubSecDateTimeOriginal", "DateTimeOriginal"] | None = None
    geotime_value: str | None = None
    if isinstance(date_time_original, str) and isinstance(subsec_time_original, int):
        geotime_value = _public_subsec_datetime_original(date_time_original, subsec_time_original)
        source_tag = "SubSecDateTimeOriginal"
    elif isinstance(date_time_original, str):
        geotime_value = date_time_original
        source_tag = "DateTimeOriginal"
    if geotime_value is None:
        return PublicGeotagImageGeotime(
            status="missing_timestamp",
            raw=None,
            source_tag=None,
            seconds=None,
            no_date=False,
            timezone_qualified=False,
            warning="JPEG EXIF has neither SubSecDateTimeOriginal nor DateTimeOriginal",
        )
    geotime = parse_geotime_value(geotime_value)
    if geotime.status != "ok" or geotime.seconds is None:
        status: Literal["local_timezone_required", "invalid_timestamp"]
        status = (
            "local_timezone_required"
            if geotime.status == "local_timezone_required"
            else "invalid_timestamp"
        )
        return PublicGeotagImageGeotime(
            status=status,
            raw=geotime_value,
            source_tag=source_tag,
            seconds=None,
            no_date=geotime.no_date,
            timezone_qualified=geotime.timezone_qualified,
            warning=geotime.warning,
        )
    return PublicGeotagImageGeotime(
        status="ok",
        raw=geotime_value,
        source_tag=source_tag,
        seconds=geotime.seconds,
        no_date=geotime.no_date,
        timezone_qualified=geotime.timezone_qualified,
        warning=None,
    )


def _public_subsec_datetime_original(date_time_original: str, subsec_time_original: int) -> str:
    subsecond = f".{subsec_time_original:03d}"
    timezone_match = _GEOTIME_TZ_SUFFIX_PATTERN.search(date_time_original)
    if timezone_match is None:
        return f"{date_time_original}{subsecond}"
    suffix = timezone_match.group(1)
    return f"{date_time_original[: timezone_match.start(1)]}{subsecond}{suffix}"


def _public_geotag_image_geotime_diagnostic(
    target_path: Path,
    image_geotime: PublicGeotagImageGeotime,
) -> Diagnostic:
    if image_geotime.status == "local_timezone_required":
        return Diagnostic(
            code="public_geotag_omitted_geotime_local_timezone_required",
            message=(
                "omitted -Geotime derived a timezone-unqualified image timestamp; "
                f"{_EXIFTOOL_NAME} would use the local system timezone, "
                "so public mutation is deferred"
            ),
            details={
                "target_path": target_path.as_posix(),
                "source_tag": image_geotime.source_tag,
                "geotime": image_geotime.raw,
                "source": f"{_IMAGE_EXIFTOOL_PATH}Geotag.pm lines 1200-1210",
            },
        )
    if image_geotime.status == "missing_timestamp":
        return Diagnostic(
            code="public_geotag_omitted_geotime_missing_timestamp",
            message=(
                "omitted -Geotime requires SubSecDateTimeOriginal or DateTimeOriginal "
                "in the target image"
            ),
            details={
                "target_path": target_path.as_posix(),
                "source": "../exiftool/exiftool lines 1404-1412",
            },
        )
    if image_geotime.status == "missing_exif":
        return Diagnostic(
            code="public_geotag_omitted_geotime_missing_exif",
            message="omitted -Geotime requires readable JPEG EXIF timestamp metadata",
            details={
                "target_path": target_path.as_posix(),
                "warning": image_geotime.warning,
            },
        )
    return Diagnostic(
        code="public_geotag_omitted_geotime_invalid_timestamp",
        message=image_geotime.warning or "derived omitted -Geotime timestamp is invalid",
        details={
            "target_path": target_path.as_posix(),
            "source_tag": image_geotime.source_tag,
            "geotime": image_geotime.raw,
        },
    )


def _public_geotag_copy_geotime_diagnostic(
    target_path: Path,
    copy_geotime: PublicGeotagCopyGeotime,
) -> Diagnostic:
    if copy_geotime.status == "local_timezone_required":
        return Diagnostic(
            code="public_geotag_copy_expression_local_timezone_required",
            message=(
                "copy-expression -Geotime derived a timezone-unqualified image "
                f"timestamp; {_EXIFTOOL_NAME} would use the local system timezone, so public "
                "mutation is deferred unless the expression supplies an explicit timezone"
            ),
            details={
                "target_path": target_path.as_posix(),
                "source_tag": copy_geotime.source_tag,
                "expression": copy_geotime.expression,
                "geotime": copy_geotime.raw,
                "source": f"{_IMAGE_EXIFTOOL_PATH}Geotag.pm lines 1200-1210",
            },
        )
    if copy_geotime.status == "missing_source_tag":
        return Diagnostic(
            code="public_geotag_copy_expression_missing_source_tag",
            message="copy-expression -Geotime source timestamp tag is missing",
            details={
                "target_path": target_path.as_posix(),
                "source_tag": copy_geotime.source_tag,
                "expression": copy_geotime.expression,
                "source": "../exiftool/html/geotag.html lines 212-221",
            },
        )
    if copy_geotime.status == "invalid_source_value":
        return Diagnostic(
            code="public_geotag_copy_expression_invalid_source_value",
            message=copy_geotime.warning or "copy-expression source value is not usable",
            details={
                "target_path": target_path.as_posix(),
                "source_tag": copy_geotime.source_tag,
                "expression": copy_geotime.expression,
            },
        )
    return Diagnostic(
        code="public_geotag_copy_expression_invalid_timestamp",
        message=copy_geotime.warning or "copy-expression -Geotime timestamp is invalid",
        details={
            "target_path": target_path.as_posix(),
            "source_tag": copy_geotime.source_tag,
            "expression": copy_geotime.expression,
            "geotime": copy_geotime.raw,
        },
    )


def _public_geotag_copy_expression_plan_json(
    request: PublicGeotagWorkflowRequest,
    track_format_name: str,
    track_point_count: int,
    track_has: list[str],
    track_is_date: bool,
    track_no_date: bool,
    track_date_time_only: bool,
    expression: PublicGeotagCopyExpression,
    prepared_targets: list[PublicGeotagPreparedCopyTarget],
    execution: JsonObject,
) -> JsonObject:
    target_plans: JsonArray = []
    for prepared_target in prepared_targets:
        target_plans.append(
            {
                "target_path": prepared_target.path.as_posix(),
                "geotime": _copy_geotime_json(prepared_target.copy_geotime),
                "geosync": _geosync_json(request),
                "geolocation_write": _geolocation_write_json(request, prepared_target.effects),
                "selected_fix": _selected_fix_json(
                    prepared_target.effects.application_result.selected_fix
                ),
                "gps_write_steps": _gps_write_steps_json(prepared_target.effects.gps_write_plan),
                "exif_scalar_write_steps": _exif_scalar_write_steps_json(
                    prepared_target.effects.exif_scalar_write_plan
                ),
            }
        )
    if _public_geotag_track_log_paths(request) == ():
        raise AssertionError("copy-expression plan requires track log path")
    return {
        "target_paths": [path.as_posix() for path in request.target_paths],
        "track_log": {
            "path": _public_geotag_track_log_path_text(request),
            "paths": [path.as_posix() for path in _public_geotag_track_log_paths(request)],
            "format": track_format_name,
            "point_count": track_point_count,
            "has": [item for item in track_has],
            "is_date": track_is_date,
            "no_date": track_no_date,
            "date_time_only": track_date_time_only,
        },
        "geotime": {
            "raw": request.geotime_copy_expression,
            "source": "copy_expression",
            "source_tag": expression.source_tag,
            "timezone_suffix": expression.timezone_suffix,
        },
        "geosync": _geosync_json(request),
        "target_plans": target_plans,
        "execution": execution,
    }


def _geosync_json(request: PublicGeotagWorkflowRequest) -> JsonObject:
    return {
        "offset_seconds": request.geosync_offset_seconds,
        "points": [
            {
                "image_time_seconds": point.image_time_seconds,
                "offset_seconds": point.offset_seconds,
            }
            for point in request.geosync_points
        ],
    }


def _geolocation_write_json(
    request: PublicGeotagWorkflowRequest,
    effects: GeotagWriteEffects,
) -> JsonObject:
    if not request.geolocate_geotag:
        return {"enabled": False}
    result = _resolve_public_geotag_geolocation(request, effects)
    composed_mutation_ready = (
        result.resolved
        and bool(result.tags)
        and not _public_geotag_non_executable_targets(request.target_paths)
    )
    return _geolocation_runtime_result_json(
        request,
        result,
        composed_mutation_ready=composed_mutation_ready,
    )


def _resolve_public_geotag_geolocation(
    request: PublicGeotagWorkflowRequest,
    effects: GeotagWriteEffects,
) -> GeolocationRuntimeResult:
    selected_fix = effects.application_result.selected_fix
    if selected_fix is None or selected_fix.latitude is None or selected_fix.longitude is None:
        return GeolocationRuntimeResult(
            status="missing_input",
            tags=(),
            source_reference_ids=(),
            reason="Geolocate=geotag requires a selected latitude/longitude fix.",
        )
    package_path = _public_geotag_geolocation_package_path(request)
    if not package_path.is_file():
        return GeolocationRuntimeResult(
            status="missing_input",
            tags=(),
            source_reference_ids=(),
            reason="Geolocate=geotag requires the generated geolocation package.",
        )
    service = load_geolocation_runtime_service(package_path)
    return service.resolve(
        GeolocationRuntimeRequest(
            latitude=selected_fix.latitude,
            longitude=selected_fix.longitude,
            limit=request.geoloc_limit,
            max_distance_km=request.geoloc_max_distance_km,
            min_population=request.geoloc_min_population,
            feature_codes=request.geoloc_feature_codes,
            excluded_feature_codes=request.geoloc_excluded_feature_codes,
            use_alternate_names=request.geoloc_alt_names,
        )
    )


def _geolocation_runtime_result_json(
    request: PublicGeotagWorkflowRequest,
    result: GeolocationRuntimeResult,
    *,
    composed_mutation_ready: bool,
) -> JsonObject:
    planned_destination_operations: JsonArray = []
    if result.tags:
        planned_destination_operations = _geolocation_planned_destination_operations_json(
            result.tags[0]
        )
    return {
        "enabled": True,
        "status": result.status,
        "geolocation_package_path": _public_geotag_geolocation_package_path(request).as_posix(),
        "max_distance_km": request.geoloc_max_distance_km,
        "min_population": request.geoloc_min_population,
        "feature_codes": list(request.geoloc_feature_codes),
        "excluded_feature_codes": list(request.geoloc_excluded_feature_codes),
        "limit": request.geoloc_limit,
        "use_alternate_names": request.geoloc_alt_names,
        "tags": [_geolocation_tags_json(tags) for tags in result.tags],
        "diagnostics": [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "candidate_count": diagnostic.candidate_count,
            }
            for diagnostic in result.diagnostics
        ],
        "planned_destination_operations": planned_destination_operations,
        "execution": "package_resolved_composed_mutation"
        if composed_mutation_ready
        else "package_resolved_plan_only",
        "mutation_blocker": not composed_mutation_ready,
        "transaction_scope": "same_target_geotag_xmp_iptc_composition",
        "writer_routes": [
            "JPEG GPS/EXIF geotag writer",
            "XMP property writer",
            "IPTC APP13 writer",
        ],
        "mutation_contract": (
            "Geolocate=geotag writes GPS/EXIF, XMP place tags, and IPTC place tags through "
            "one composed in-memory JPEG rewrite followed by one target file transaction."
        ),
    }


def _public_geotag_geolocation_package_path(request: PublicGeotagWorkflowRequest) -> Path:
    return request.geolocation_package_path or generated_index_package_path()


def _geolocation_planned_destination_operations_json(
    tags: GeolocationRuntimeTags,
) -> JsonArray:
    return [
        {
            "destination": "XMP",
            "status": "planned_operation",
            "mutation_status": "composed_transaction_ready",
            "assignments": [
                {"tag": "XMP-photoshop:City", "value": tags.city},
                {"tag": "XMP-photoshop:State", "value": tags.region or ""},
                {"tag": "XMP-iptcCore:CountryCode", "value": tags.country_code},
                {"tag": "XMP-photoshop:Country", "value": tags.country or ""},
            ],
        },
        {
            "destination": "IPTC",
            "status": "planned_operation",
            "mutation_status": "composed_transaction_ready",
            "assignments": [
                {"tag": "IPTC:City", "value": tags.city},
                {"tag": "IPTC:Province-State", "value": tags.region or ""},
                {
                    "tag": "IPTC:Country-PrimaryLocationCode",
                    "value": tags.country_code,
                },
                {
                    "tag": "IPTC:Country-PrimaryLocationName",
                    "value": tags.country or "",
                },
            ],
        },
    ]


def _geolocation_tags_json(tags: GeolocationRuntimeTags) -> JsonObject:
    return {key: value for key, value in tags.to_tag_values().items()}


def _image_geotime_json(image_geotime: PublicGeotagImageGeotime) -> JsonObject:
    return {
        "raw": image_geotime.raw,
        "source": "omitted",
        "source_tag": image_geotime.source_tag,
        "seconds": image_geotime.seconds,
        "no_date": image_geotime.no_date,
        "timezone_qualified": image_geotime.timezone_qualified,
        "lookup_priority": ["SubSecDateTimeOriginal", "DateTimeOriginal"],
    }


def _copy_geotime_json(copy_geotime: PublicGeotagCopyGeotime) -> JsonObject:
    return {
        "raw": copy_geotime.raw,
        "source": "copy_expression",
        "source_tag": copy_geotime.source_tag,
        "expression": copy_geotime.expression,
        "seconds": copy_geotime.seconds,
        "no_date": copy_geotime.no_date,
        "timezone_qualified": copy_geotime.timezone_qualified,
    }


def _public_geotag_write_result_json(
    target_path: Path,
    result: JpegGeotagRewriteResult,
) -> JsonObject:
    transaction = result.transaction
    return {
        "target_path": target_path.as_posix(),
        "original_app1_payload_length": result.original_app1_payload_length,
        "rewritten_app1_payload_length": result.rewritten_app1_payload_length,
        "gps_applied": result.gps_applied,
        "exif_scalar_applied": result.exif_scalar_applied,
        "transaction": None
        if transaction is None
        else {
            "output_path": transaction.output_path,
            "bytes_written": transaction.bytes_written,
            "replaced_existing": transaction.replaced_existing,
            "backup_path": transaction.backup_path,
            "backup_created": transaction.backup_created,
            "preserve_file_times": transaction.preserve_file_times,
        },
    }


def _public_geotag_composed_write_result_json(
    target_path: Path,
    result: PublicGeotagComposedRewriteResult,
) -> JsonObject:
    return {
        "target_path": target_path.as_posix(),
        "original_app1_payload_length": result.geotag_result.original_app1_payload_length,
        "rewritten_app1_payload_length": result.geotag_result.rewritten_app1_payload_length,
        "gps_applied": result.geotag_result.gps_applied,
        "exif_scalar_applied": result.geotag_result.exif_scalar_applied,
        "changed_xmp_properties": result.changed_xmp_properties,
        "changed_iptc_datasets": result.changed_iptc_datasets,
        "transaction": _transaction_json(result.transaction),
    }


def _public_geotag_xmp_write_result_json(
    target_path: Path,
    result: GeotagXmpSidecarRewriteResult,
) -> JsonObject:
    transaction = result.transaction
    return {
        "target_path": target_path.as_posix(),
        "changed_xmp_properties": result.changed_xmp_properties,
        "deleted_xmp_properties": result.deleted_xmp_properties,
        "transaction": None
        if transaction is None
        else {
            "output_path": transaction.output_path,
            "bytes_written": transaction.bytes_written,
            "replaced_existing": transaction.replaced_existing,
            "backup_path": transaction.backup_path,
            "backup_created": transaction.backup_created,
            "preserve_file_times": transaction.preserve_file_times,
        },
    }


def _public_geotag_jpeg_xmp_write_result_json(
    target_path: Path,
    result: GeotagJpegXmpRewriteResult,
) -> JsonObject:
    payload: JsonObject = {
        "target_path": target_path.as_posix(),
        "route": "jpeg_embedded_xmp",
        "original_app1_payload_length": result.original_app1_payload_length,
        "rewritten_app1_payload_length": result.rewritten_app1_payload_length,
        "changed_xmp_properties": result.changed_xmp_properties,
        "deleted_xmp_properties": result.deleted_xmp_properties,
        "transaction": _transaction_json(result.transaction),
    }
    return payload


def _public_geotag_quicktime_write_result_json(
    target_path: Path,
    result: GeotagQuickTimeRewriteResult,
) -> JsonObject:
    return {
        "target_path": target_path.as_posix(),
        "changed_atoms": result.changed_atoms,
        "applied_metadata": result.applied_metadata,
        "executed_surfaces": list(result.executed_surfaces),
        "blocked_surfaces": list(result.blocked_surfaces),
        "deferred": list(result.deferred),
        "transaction": _transaction_json(result.transaction),
    }


def _transaction_json(transaction: FileWriteTransactionResult | None) -> JsonObject | None:
    if transaction is None:
        return None
    return {
        "output_path": transaction.output_path,
        "bytes_written": transaction.bytes_written,
        "replaced_existing": transaction.replaced_existing,
        "backup_path": transaction.backup_path,
        "backup_created": transaction.backup_created,
        "preserve_file_times": transaction.preserve_file_times,
    }


def _selected_fix_json(selected_fix: GeotagSelectedFix | None) -> JsonObject | None:
    if selected_fix is None:
        return None
    return {
        "time_seconds": selected_fix.time_seconds,
        "latitude": selected_fix.latitude,
        "longitude": selected_fix.longitude,
        "altitude": selected_fix.altitude,
        "speed": selected_fix.speed,
        "track": selected_fix.track,
        "image_direction": selected_fix.image_direction,
        "pitch": selected_fix.pitch,
        "roll": selected_fix.roll,
        "hdop": selected_fix.hdop,
        "pdop": selected_fix.pdop,
        "vdop": selected_fix.vdop,
        "selection_mode": selected_fix.selection_mode,
    }


def _gps_write_steps_json(write_plan: ExifGpsWritePlan | None) -> JsonArray:
    if write_plan is None:
        return []
    return [_gps_write_step_json(step) for step in write_plan.steps]


def _gps_write_step_json(step: ExifGpsWriteStep) -> JsonObject:
    return {
        "operation": step.operation,
        "group": step.group,
        "tag_name": step.tag_name,
        "tag_id": step.tag_id,
        "field_type": step.field_type,
        "count": step.count,
        "value": _tiff_write_value_json(step.value),
    }


def _tiff_write_value_json(value: TiffWriteValue) -> JsonObject:
    if isinstance(value, AsciiWriteValue):
        return {
            "kind": "ascii",
            "text": value.text,
            "nul_terminated": value.nul_terminated,
        }
    if isinstance(value, ByteWriteValue):
        return {"kind": "byte", "values": list(value.values)}
    if isinstance(value, RationalArrayWriteValue):
        return {
            "kind": "rational_array",
            "values": [_rational_write_value_json(item) for item in value.values],
        }
    if isinstance(value, GpsDeleteWriteValue):
        return {"kind": "delete"}
    raise AssertionError(f"Unhandled TIFF write value: {type(value).__name__}")


def _rational_write_value_json(value: RationalWriteValue) -> JsonObject:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _exif_scalar_write_steps_json(write_plan: ExifScalarWritePlan | None) -> JsonArray:
    if write_plan is None:
        return []
    return [_exif_scalar_write_step_json(step) for step in write_plan.steps]


def _exif_scalar_write_step_json(step: ExifScalarWriteStep) -> JsonObject:
    return {
        "operation": step.operation,
        "directory_name": step.directory_name,
        "group": step.group,
        "tag_name": step.tag_name,
        "tag_id": step.tag_id,
        "field_type": step.field_type,
        "count": step.count,
        "value": _exif_scalar_write_value_json(step.value),
    }


def _exif_scalar_write_value_json(value: ExifScalarWriteValue) -> JsonObject:
    if isinstance(value, ExifScalarAsciiWriteValue):
        return {
            "kind": "ascii",
            "text": value.text,
            "nul_terminated": value.nul_terminated,
        }
    if isinstance(value, ExifScalarShortWriteValue):
        return {"kind": "short", "value": value.value}
    if isinstance(value, ExifScalarRationalWriteValue):
        return {
            "kind": "rational",
            "numerator": value.numerator,
            "denominator": value.denominator,
        }
    if isinstance(value, ExifScalarSignedRationalWriteValue):
        return {
            "kind": "signed_rational",
            "numerator": value.numerator,
            "denominator": value.denominator,
        }
    if isinstance(value, ExifScalarUndefinedWriteValue):
        return {"kind": "undefined", "value_hex": value.value.hex()}
    if isinstance(value, ExifScalarDeleteWriteValue):
        return {"kind": "delete"}
    raise AssertionError(f"Unhandled EXIF scalar write value: {type(value).__name__}")


def _diagnostic_json(diagnostic: Diagnostic) -> JsonObject:
    details: JsonValue = diagnostic.details
    return {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "details": details,
    }
