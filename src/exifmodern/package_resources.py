"""Package-resource access for bundled production data."""

from __future__ import annotations

from contextlib import ExitStack
from functools import cache
from importlib.resources import as_file, files
from pathlib import Path
from typing import Literal

from exifmodern.runtime_data_shards import (
    CharsetLanguageShardKind,
    GeneratedIndexShard,
    MakerNoteShard,
)

type RuntimeDataPackage = Literal[
    "charset-language-package.json",
    "generated-index-package.json",
    "makernote-package.json",
]

_RESOURCE_STACK = ExitStack()


@cache
def runtime_data_package_path(name: RuntimeDataPackage) -> Path:
    """Return a filesystem path for a bundled runtime data package."""
    resource = files("exifmodern.data").joinpath(name)
    return _RESOURCE_STACK.enter_context(as_file(resource))


@cache
def runtime_data_resource_path(*parts: str) -> Path | None:
    """Return a filesystem path for an optional bundled runtime data resource."""
    if not parts:
        return None
    resource = files("exifmodern.data")
    for part in parts:
        resource = resource.joinpath(part)
    if not resource.is_file():
        return None
    return _RESOURCE_STACK.enter_context(as_file(resource))


def charset_language_package_path() -> Path:
    manifest_path = charset_language_manifest_path()
    return (
        manifest_path
        if manifest_path is not None
        else runtime_data_package_path("charset-language-package.json")
    )


def generated_index_package_path() -> Path:
    manifest_path = generated_index_manifest_path()
    return (
        manifest_path
        if manifest_path is not None
        else runtime_data_package_path("generated-index-package.json")
    )


def maker_note_package_path() -> Path:
    manifest_path = maker_note_manifest_path()
    return (
        manifest_path
        if manifest_path is not None
        else runtime_data_package_path("makernote-package.json")
    )


def generated_index_shard_path(kind: GeneratedIndexShard) -> Path | None:
    if kind == "geolocation":
        pickle_path = runtime_data_resource_path("generated-index", "geolocation.pickle")
        if pickle_path is not None:
            return pickle_path
        return runtime_data_resource_path("generated-index", "geolocation.json.gz")
    return runtime_data_resource_path(
        "generated-index",
        f"{kind}.json",
    ) or runtime_data_resource_path(
        "generated-index",
        f"{kind}.pickle",
    )


def generated_index_geolocation_repository_pickle_path() -> Path | None:
    return runtime_data_resource_path("generated-index", "geolocation.repository.pickle")


def maker_note_shard_path(kind: MakerNoteShard) -> Path | None:
    return runtime_data_resource_path("makernote", f"{kind}.json") or runtime_data_resource_path(
        "makernote",
        f"{kind}.pickle",
    )


def generated_index_manifest_path() -> Path | None:
    return runtime_data_resource_path("generated-index", "manifest.json")


def maker_note_manifest_path() -> Path | None:
    return runtime_data_resource_path("makernote", "manifest.json")


def charset_language_shard_path(kind: CharsetLanguageShardKind, name: str) -> Path | None:
    return runtime_data_resource_path(
        "charset-language",
        kind,
        f"{name}.json.gz",
    ) or runtime_data_resource_path("charset-language", kind, f"{name}.pickle")


def charset_language_manifest_path() -> Path | None:
    return runtime_data_resource_path("charset-language", "manifest.json")
