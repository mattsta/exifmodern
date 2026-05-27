"""EXIF sidecar tagsFromFile copy planning.

This module models the safe subset needed for creating an ``.exif`` sidecar
from source-backed EXIF bytes. It deliberately does not synthesize TIFF output.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.jpeg.container import read_exif_app1
from exifmodern.formats.tiff.primitives import parse_tiff_header
from exifmodern.json_types import JsonArray, JsonObject, json_string_array_value, json_string_value

type ExifSidecarCopySourceGroup = Literal["EXIF"]
type ExifSidecarCopyDestinationGroup = Literal["EXIF_SIDECAR"]
type ExifSidecarCopyTagPattern = Literal["*"]
type ExifSidecarCopyStrategy = Literal["copy_source_exif_tiff_payload"]
type ExifSidecarCopyMaterialization = Literal[
    "jpeg_app1_tiff_payload",
    "exif_tiff_file_payload",
]


TAGS_FROM_FILE_SOURCE = "format.exif_sidecar.tags_from_file"
EXIF_BLOCK_WRITE_SOURCE = "format.exif_sidecar.block_write_guard"
EXIF_SIDECAR_CREATE_SOURCE = "format.exif_sidecar.create_flow"
WRITE_EXIF_SOURCE = "format.exif_sidecar.write_exif"
EXIF_READ_SOURCE = "format.exif_sidecar.exif_read"
WRITER_EXIF_SIDECAR_TEST_SOURCE = "format.exif_sidecar.writer_test"


@dataclass(frozen=True)
class ExifSidecarCopySourceSelector:
    group: ExifSidecarCopySourceGroup
    tag_pattern: ExifSidecarCopyTagPattern
    raw_token: str


@dataclass(frozen=True)
class ExifSidecarCopyDestinationSelector:
    group: ExifSidecarCopyDestinationGroup
    tag_pattern: ExifSidecarCopyTagPattern
    raw_token: str


@dataclass(frozen=True)
class ExifSidecarCopyRoute:
    source: ExifSidecarCopySourceSelector
    destination: ExifSidecarCopyDestinationSelector
    raw_argument: str


@dataclass(frozen=True)
class ExifSidecarCopyFromFilePlan:
    source_filename: str
    routes: tuple[ExifSidecarCopyRoute, ...]
    strategy: ExifSidecarCopyStrategy
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExifSidecarCopyDiagnostic:
    token: str
    reason: str
    detail: str


@dataclass(frozen=True)
class ExifSidecarPublicExecutionBoundaryReport:
    unsupported_shape: str
    existing_callable: str
    existing_planner: str
    supported_runtime_routes: tuple[str, ...]
    blockers: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json_object(self) -> JsonObject:
        blockers: JsonArray = list(self.blockers)
        supported_runtime_routes: JsonArray = list(self.supported_runtime_routes)
        evidence_ids: JsonArray = list(self.evidence_ids)
        return {
            "unsupported_shape": self.unsupported_shape,
            "existing_callable": self.existing_callable,
            "existing_planner": self.existing_planner,
            "supported_runtime_routes": supported_runtime_routes,
            "blockers": blockers,
            "evidence_ids": evidence_ids,
        }


@dataclass(frozen=True)
class MaterializedExifSidecarCopyFromFilePlan:
    copy_plan: ExifSidecarCopyFromFilePlan
    data: bytes
    materialization: ExifSidecarCopyMaterialization
    diagnostics: tuple[ExifSidecarCopyDiagnostic, ...]


def exif_sidecar_copy_plan_from_request_payload(
    payload: JsonObject,
) -> ExifSidecarCopyFromFilePlan:
    write_args = tuple(json_string_array_value(payload, "write_args"))
    return parse_exif_sidecar_copy_from_file_args(write_args)


def exif_sidecar_copy_request_id(payload: JsonObject) -> str | None:
    return json_string_value(payload, "request_id")


def exif_sidecar_public_execution_boundary_report() -> ExifSidecarPublicExecutionBoundaryReport:
    return ExifSidecarPublicExecutionBoundaryReport(
        unsupported_shape="exif_sidecar_copy_from_file",
        existing_callable=(
            "exifmodern.formats.exif_sidecar.sidecar_writer."
            "rewrite_exif_sidecar_copy_from_file_to_path"
        ),
        existing_planner=(
            "exifmodern.formats.exif_sidecar.copy_from_file_plan."
            "parse_exif_sidecar_copy_from_file_args"
        ),
        supported_runtime_routes=("EXIF", "EXIF:all", "EXIF:*"),
        blockers=(
            "Legacy scalar assignment requests such as MetadataAssignment(tag='EXIF', "
            "value='source.jpg') are intentionally not executed as tagsFromFile copy "
            "routes; callers must use MetadataWriteRequest.exif_sidecar_copy_from_file.",
            "Typed EXIF sidecar copy execution maps backup policy preserve_original "
            "to create_backup and overwrite_original to overwrite_original before calling the "
            "package-local execution request.",
            "Executing scalar assignment values as filenames would overload assignment "
            "semantics and could fake tagsFromFile copy behavior.",
        ),
        evidence_ids=(
            TAGS_FROM_FILE_SOURCE,
            EXIF_SIDECAR_CREATE_SOURCE,
            EXIF_BLOCK_WRITE_SOURCE,
            WRITER_EXIF_SIDECAR_TEST_SOURCE,
        ),
    )


def parse_exif_sidecar_copy_from_file_args(
    write_args: tuple[str, ...],
) -> ExifSidecarCopyFromFilePlan:
    source_filename: str | None = None
    routes: list[ExifSidecarCopyRoute] = []
    index = 0
    while index < len(write_args):
        arg = write_args[index]
        if arg == "-tagsFromFile":
            if index + 1 >= len(write_args):
                raise ValueError("Missing tagsFromFile source filename")
            source_filename = write_args[index + 1]
            index += 2
            continue
        if source_filename is not None and arg.startswith("-"):
            routes.append(parse_exif_sidecar_copy_route(arg[1:]))
        index += 1
    if source_filename is None:
        raise ValueError("Request does not contain -tagsFromFile")
    if not routes:
        raise ValueError("Request does not contain supported tagsFromFile copy routes")
    copy_routes = tuple(routes)
    strategy = exif_sidecar_copy_strategy(copy_routes)
    return ExifSidecarCopyFromFilePlan(
        source_filename=source_filename,
        routes=copy_routes,
        strategy=strategy,
        evidence_ids=(
            TAGS_FROM_FILE_SOURCE,
            EXIF_BLOCK_WRITE_SOURCE,
            EXIF_SIDECAR_CREATE_SOURCE,
            WRITE_EXIF_SOURCE,
            EXIF_READ_SOURCE,
            WRITER_EXIF_SIDECAR_TEST_SOURCE,
        ),
    )


def parse_exif_sidecar_copy_route(token: str) -> ExifSidecarCopyRoute:
    source = parse_exif_sidecar_copy_source_selector(token.strip())
    destination = ExifSidecarCopyDestinationSelector(
        group="EXIF_SIDECAR",
        tag_pattern="*",
        raw_token=".exif",
    )
    return ExifSidecarCopyRoute(source=source, destination=destination, raw_argument=token)


def parse_exif_sidecar_copy_source_selector(token: str) -> ExifSidecarCopySourceSelector:
    group, tag_pattern = parse_exif_sidecar_selector(token)
    if group != "exif":
        raise ValueError(f"Unsupported tagsFromFile EXIF sidecar source selector: {token}")
    return ExifSidecarCopySourceSelector(group="EXIF", tag_pattern=tag_pattern, raw_token=token)


def parse_exif_sidecar_selector(token: str) -> tuple[str, ExifSidecarCopyTagPattern]:
    group, separator, tag = token.lower().partition(":")
    if group != "exif":
        raise ValueError(f"Unsupported tagsFromFile EXIF sidecar selector: {token}")
    if separator == "":
        return group, "*"
    if tag in {"all", "*"}:
        return group, "*"
    raise ValueError(f"Unsupported tagsFromFile EXIF sidecar selector: {token}")


def exif_sidecar_copy_strategy(
    routes: tuple[ExifSidecarCopyRoute, ...],
) -> ExifSidecarCopyStrategy:
    if routes and all(
        route.source.group == "EXIF" and route.destination.group == "EXIF_SIDECAR"
        for route in routes
    ):
        return "copy_source_exif_tiff_payload"
    route_names = ", ".join(route.raw_argument for route in routes)
    raise ValueError(f"Unsupported EXIF sidecar copy route: {route_names}")


def materialize_exif_sidecar_copy_from_file_plan(
    copy_plan: ExifSidecarCopyFromFilePlan,
    source_path: Path,
) -> MaterializedExifSidecarCopyFromFilePlan:
    if copy_plan.strategy != "copy_source_exif_tiff_payload":
        return MaterializedExifSidecarCopyFromFilePlan(
            copy_plan=copy_plan,
            data=b"",
            materialization="exif_tiff_file_payload",
            diagnostics=(
                ExifSidecarCopyDiagnostic(
                    copy_plan.strategy,
                    "unsupported_strategy",
                    "EXIF sidecar copy supports only source EXIF TIFF payload copies.",
                ),
            ),
        )
    try:
        data, materialization = source_backed_exif_tiff_payload(source_path)
    except ValueError as error:
        return MaterializedExifSidecarCopyFromFilePlan(
            copy_plan=copy_plan,
            data=b"",
            materialization="exif_tiff_file_payload",
            diagnostics=(
                ExifSidecarCopyDiagnostic(
                    source_path.as_posix(),
                    "missing_source_exif",
                    str(error),
                ),
            ),
        )
    return MaterializedExifSidecarCopyFromFilePlan(
        copy_plan=copy_plan,
        data=data,
        materialization=materialization,
        diagnostics=(),
    )


def source_backed_exif_tiff_payload(
    source_path: Path,
) -> tuple[bytes, ExifSidecarCopyMaterialization]:
    if source_path.suffix.lower() == ".exif":
        data = source_path.read_bytes()
        validate_exif_tiff_payload(data, source_path)
        return data, "exif_tiff_file_payload"
    data = read_exif_app1(source_path).tiff_data
    validate_exif_tiff_payload(data, source_path)
    return data, "jpeg_app1_tiff_payload"


def validate_exif_tiff_payload(data: bytes, source_path: Path) -> None:
    if not data:
        raise ValueError(f"No source-backed EXIF TIFF payload found: {source_path}")
    parse_tiff_header(data)
