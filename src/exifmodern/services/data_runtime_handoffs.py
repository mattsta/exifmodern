"""Package-backed classification for generated-data runtime handoffs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import (
    JsonObject,
    JsonValue,
    json_array_value,
    json_string_value,
    load_json_object,
)
from exifmodern.package_resources import generated_index_package_path, maker_note_package_path
from exifmodern.services.lens_identity_tables import (
    load_lens_identity_package_repository,
)

type DataRuntimeHandoffFamily = Literal[
    "canon",
    "casio",
    "geolocation",
    "minolta",
    "nikon",
    "olympus",
    "panasonic",
    "pentax",
    "sigma",
]
type DataRuntimeHandoffClassification = Literal[
    "consumed",
    "implemented-this-batch",
    "not-runtime-data",
    "blocked-with-source-anchor",
]

REQUESTED_HANDOFF_FAMILIES: tuple[DataRuntimeHandoffFamily, ...] = (
    "canon",
    "casio",
    "geolocation",
    "minolta",
    "nikon",
    "olympus",
    "panasonic",
    "pentax",
    "sigma",
)
LENS_PACKAGE_PATH = Path("artifacts/schema/exiftool-lens-identity-tables.json")
GENERATED_INDEX_PACKAGE_ARTIFACT = "artifacts/database/generated-index-package.json"
MAKER_NOTE_PACKAGE_ARTIFACT = "artifacts/database/makernote-package.json"

LENS_TABLE_VARIABLES_BY_FAMILY: dict[DataRuntimeHandoffFamily, tuple[str, ...]] = {
    "canon": ("canonLensTypes",),
    "minolta": ("sonyLensTypes",),
    "nikon": ("nikonLensIDs",),
    "panasonic": ("leicaLensTypes",),
    "pentax": ("pentaxLensTypes",),
    "sigma": ("sigmaLensTypes",),
}
MAKER_NOTE_MODULE_BY_FAMILY: dict[DataRuntimeHandoffFamily, str] = {
    "canon": "Image::ExifTool::Canon",
    "casio": "Image::ExifTool::Casio",
    "minolta": "Image::ExifTool::Minolta",
    "nikon": "Image::ExifTool::Nikon",
    "olympus": "Image::ExifTool::Olympus",
    "panasonic": "Image::ExifTool::Panasonic",
    "pentax": "Image::ExifTool::Pentax",
    "sigma": "Image::ExifTool::Sigma",
}
SOURCE_ANCHORS_BY_FAMILY: dict[DataRuntimeHandoffFamily, tuple[str, ...]] = {
    "canon": ("../exiftool/lib/Image/ExifTool/Canon.pm:%canonLensTypes",),
    "casio": (
        "../exiftool/lib/Image/ExifTool/Casio.pm:FocusMode",
        "../exiftool/lib/Image/ExifTool/Casio.pm:FirmwareDate",
    ),
    "geolocation": (
        "../exiftool/lib/Image/ExifTool/Geolocation.pm:ReadDatabase",
        "../exiftool/lib/Image/ExifTool/Geolocation.pm:Geolocate",
        "../exiftool/lib/Image/ExifTool/Geolocation.dat",
    ),
    "minolta": (
        "../exiftool/lib/Image/ExifTool/Minolta.pm:%minoltaLensTypes",
        "../exiftool/lib/Image/ExifTool/Sony.pm:%sonyLensTypes",
    ),
    "nikon": ("../exiftool/lib/Image/ExifTool/Nikon.pm:%nikonLensIDs",),
    "olympus": (
        "../exiftool/lib/Image/ExifTool/Olympus.pm:%olympusLensTypes",
        "../exiftool/lib/Image/ExifTool/PanasonicRaw.pm:LensTypeMake",
    ),
    "panasonic": ("../exiftool/lib/Image/ExifTool/Panasonic.pm:%leicaLensTypes",),
    "pentax": ("../exiftool/lib/Image/ExifTool/Pentax.pm:%pentaxLensTypes",),
    "sigma": ("../exiftool/lib/Image/ExifTool/Sigma.pm:%sigmaLensTypes",),
}


@dataclass(frozen=True)
class DataRuntimeHandoffStatus:
    family: DataRuntimeHandoffFamily
    classification: DataRuntimeHandoffClassification
    generated_artifact_paths: tuple[str, ...]
    source_anchors: tuple[str, ...]
    runtime_services: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class DataRuntimeHandoffReport:
    statuses: tuple[DataRuntimeHandoffStatus, ...]

    def by_family(self, family: DataRuntimeHandoffFamily) -> DataRuntimeHandoffStatus:
        for status in self.statuses:
            if status.family == family:
                return status
        raise ValueError(f"Unknown data runtime handoff family: {family}")

    def families_by_classification(
        self,
        classification: DataRuntimeHandoffClassification,
    ) -> tuple[DataRuntimeHandoffFamily, ...]:
        return tuple(
            status.family for status in self.statuses if status.classification == classification
        )


def classify_data_runtime_handoffs(project_root: Path) -> DataRuntimeHandoffReport:
    lens_variables = package_lens_variables(project_root / LENS_PACKAGE_PATH)
    maker_note_modules = package_maker_note_modules(
        project_data_package_path(
            project_root,
            MAKER_NOTE_PACKAGE_ARTIFACT,
            fallback=maker_note_package_path(),
        )
    )
    generated_index_kinds = package_generated_index_kinds(
        project_data_package_path(
            project_root,
            GENERATED_INDEX_PACKAGE_ARTIFACT,
            fallback=generated_index_package_path(),
        )
    )
    return DataRuntimeHandoffReport(
        statuses=tuple(
            classify_data_runtime_handoff(
                family,
                lens_variables,
                maker_note_modules,
                generated_index_kinds,
            )
            for family in REQUESTED_HANDOFF_FAMILIES
        )
    )


def classify_data_runtime_handoff(
    family: DataRuntimeHandoffFamily,
    lens_variables: frozenset[str],
    maker_note_modules: frozenset[str],
    generated_index_kinds: frozenset[str],
) -> DataRuntimeHandoffStatus:
    if family == "geolocation":
        return geolocation_handoff_status(generated_index_kinds)

    lens_variables_for_family = LENS_TABLE_VARIABLES_BY_FAMILY.get(family, ())
    lens_packaged = any(variable in lens_variables for variable in lens_variables_for_family)
    maker_note_module = MAKER_NOTE_MODULE_BY_FAMILY.get(family)
    maker_note_packaged = maker_note_module in maker_note_modules
    if family in {"pentax", "sigma"} and lens_packaged:
        return DataRuntimeHandoffStatus(
            family=family,
            classification="implemented-this-batch",
            generated_artifact_paths=(LENS_PACKAGE_PATH.as_posix(),),
            source_anchors=SOURCE_ANCHORS_BY_FAMILY[family],
            runtime_services=(
                "exifmodern.services.lens_identity_tables",
                "exifmodern.services.source_lens_identity_runtime",
            ),
            reason=(
                "Generated lens table is now exposed through the package-backed source "
                "lens identity runtime repository."
            ),
        )
    if lens_packaged or maker_note_packaged:
        artifact_paths = handoff_artifact_paths(lens_packaged, maker_note_packaged)
        return DataRuntimeHandoffStatus(
            family=family,
            classification="consumed",
            generated_artifact_paths=artifact_paths,
            source_anchors=SOURCE_ANCHORS_BY_FAMILY[family],
            runtime_services=runtime_services_for_family(
                family,
                lens_packaged,
                maker_note_packaged,
            ),
            reason=(
                "Canonical generated package data is already consumed by package-local "
                "runtime services."
            ),
        )
    return DataRuntimeHandoffStatus(
        family=family,
        classification="blocked-with-source-anchor",
        generated_artifact_paths=(),
        source_anchors=SOURCE_ANCHORS_BY_FAMILY[family],
        runtime_services=(),
        reason="No canonical generated package row was found for this handoff family.",
    )


def geolocation_handoff_status(
    generated_index_kinds: frozenset[str],
) -> DataRuntimeHandoffStatus:
    if "geolocation" in generated_index_kinds:
        return DataRuntimeHandoffStatus(
            family="geolocation",
            classification="consumed",
            generated_artifact_paths=(GENERATED_INDEX_PACKAGE_ARTIFACT,),
            source_anchors=SOURCE_ANCHORS_BY_FAMILY["geolocation"],
            runtime_services=(
                "exifmodern.services.geolocation_index",
                "exifmodern.services.geolocation_runtime",
            ),
            reason=(
                "Generated Geolocation.dat index is consumed by the geolocation runtime service."
            ),
        )
    return DataRuntimeHandoffStatus(
        family="geolocation",
        classification="blocked-with-source-anchor",
        generated_artifact_paths=(),
        source_anchors=SOURCE_ANCHORS_BY_FAMILY["geolocation"],
        runtime_services=(),
        reason="Generated index package does not contain the geolocation index.",
    )


def handoff_artifact_paths(
    lens_packaged: bool,
    maker_note_packaged: bool,
) -> tuple[str, ...]:
    paths: list[str] = []
    if lens_packaged:
        paths.append(LENS_PACKAGE_PATH.as_posix())
    if maker_note_packaged:
        paths.append(MAKER_NOTE_PACKAGE_ARTIFACT)
    return tuple(paths)


def project_data_package_path(project_root: Path, relative_path: str, *, fallback: Path) -> Path:
    artifact_path = project_root / relative_path
    if artifact_path.exists():
        return artifact_path
    return fallback


def runtime_services_for_family(
    family: DataRuntimeHandoffFamily,
    lens_packaged: bool,
    maker_note_packaged: bool,
) -> tuple[str, ...]:
    services: list[str] = []
    if lens_packaged:
        services.extend(
            (
                "exifmodern.services.lens_identity_tables",
                "exifmodern.services.source_lens_identity_runtime",
            )
        )
    if maker_note_packaged:
        services.append("exifmodern.services.maker_note_database")
    if family == "casio" and maker_note_packaged:
        services.append("exifmodern.services.maker_note_database.print_scalar")
    return tuple(services)


def package_lens_variables(package_path: Path) -> frozenset[str]:
    if not package_path.exists():
        return frozenset()
    repository = load_lens_identity_package_repository(package_path)
    return frozenset(table.variable for table in repository.tables)


def package_generated_index_kinds(package_path: Path) -> frozenset[str]:
    if not package_path.exists():
        return frozenset()
    package = load_json_object(package_path)
    return frozenset(
        kind
        for index_value in json_array_value(package, "indexes")
        for kind in [json_string_value(json_object(index_value), "kind")]
        if kind is not None
    )


def package_maker_note_modules(package_path: Path) -> frozenset[str]:
    if not package_path.exists():
        return frozenset()
    package = load_json_object(package_path)
    return frozenset(
        module
        for record_value in json_array_value(package, "records")
        for module in [json_string_value(json_object(record_value), "module")]
        if module is not None
    )


def json_object(value: JsonValue) -> JsonObject:
    return value if isinstance(value, dict) else {}
