"""Oracle-style public CLI path traversal helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from exifmodern.public_api.models import ExtensionFilter
from exifmodern.public_interface.directory_traversal import public_directory_read_extensions

type PublicTraversalAcceptance = Literal["specific", "default", "rejected"]


def expand_public_cli_read_paths(
    paths: tuple[Path, ...],
    *,
    recursive: bool,
    recurse_dot_directories: bool,
    ignore_directories: tuple[str, ...],
    extension_filters: tuple[ExtensionFilter, ...],
    trusted_supported_extensions: frozenset[str] = frozenset(),
) -> tuple[Path, ...]:
    """Expand CLI directory inputs and apply oracle -ext filters to explicit files."""

    expanded: list[Path] = []
    for path in paths:
        if path.is_dir():
            expanded.extend(
                scan_public_cli_read_directory(
                    path,
                    recursive=recursive or recurse_dot_directories,
                    recurse_dot_directories=recurse_dot_directories,
                    ignore_directories=ignore_directories,
                    extension_filters=extension_filters,
                    trusted_supported_extensions=trusted_supported_extensions,
                )
            )
            continue
        if _explicit_public_cli_file_is_accepted(path, extension_filters):
            expanded.append(path)
    return tuple(expanded)


def scan_public_cli_read_directory(
    root: Path,
    *,
    recursive: bool,
    recurse_dot_directories: bool,
    ignore_directories: tuple[str, ...],
    extension_filters: tuple[ExtensionFilter, ...],
    trusted_supported_extensions: frozenset[str] = frozenset(),
) -> tuple[Path, ...]:
    if public_cli_directory_is_ignored(root, ignore_directories):
        return ()
    paths: list[Path] = []
    for candidate in root.iterdir():
        if candidate.is_dir():
            if (
                recursive
                and (recurse_dot_directories or not candidate.name.startswith("."))
                and not public_cli_directory_is_ignored(candidate, ignore_directories)
            ):
                paths.extend(
                    scan_public_cli_read_directory(
                        candidate,
                        recursive=True,
                        recurse_dot_directories=recurse_dot_directories,
                        ignore_directories=ignore_directories,
                        extension_filters=extension_filters,
                        trusted_supported_extensions=trusted_supported_extensions,
                    )
                )
            continue
        if (
            candidate.is_file()
            and not public_cli_file_is_ignored(candidate, ignore_directories)
            and public_cli_directory_file_is_accepted(
                candidate,
                extension_filters,
                trusted_supported_extensions=trusted_supported_extensions,
            )
        ):
            paths.append(candidate)
    return tuple(paths)


def public_cli_directory_is_ignored(
    path: Path,
    ignore_directories: tuple[str, ...],
) -> bool:
    if path.is_symlink() and "SYMLINKS" in ignore_directories:
        return True
    path_values = _directory_ignore_path_values(path)
    for ignored in ignore_directories:
        if ignored in {"HIDDEN", "SYMLINKS"}:
            continue
        if ignored == path.name or ignored in path_values:
            return True
    return False


def public_cli_file_is_ignored(path: Path, ignore_directories: tuple[str, ...]) -> bool:
    return "HIDDEN" in ignore_directories and path.name.startswith(".")


def public_cli_directory_file_is_accepted(
    path: Path,
    extension_filters: tuple[ExtensionFilter, ...],
    *,
    trusted_supported_extensions: frozenset[str] = frozenset(),
) -> bool:
    directory_read_extensions = public_directory_read_extensions() | trusted_supported_extensions
    if not extension_filters:
        return path.suffix.lower() in directory_read_extensions

    acceptance = public_cli_extension_filter_acceptance(path, extension_filters)
    if acceptance == "rejected":
        return False
    if acceptance == "specific":
        return True
    return path.suffix.lower() in directory_read_extensions


def public_cli_extension_filter_acceptance(
    path: Path,
    extension_filters: tuple[ExtensionFilter, ...],
) -> PublicTraversalAcceptance:
    lookup: dict[str, bool] = {}
    has_include_only_filter = False
    for extension_filter in extension_filters:
        normalized = _normalized_extension_filter_value(extension_filter.extension)
        if extension_filter.mode == "exclude":
            lookup[normalized] = False
            continue
        lookup[normalized] = True
        if extension_filter.mode == "include":
            has_include_only_filter = True

    extension = _path_extension_filter_value(path)
    if extension in lookup:
        return "specific" if lookup[extension] else "rejected"
    if "*" in lookup:
        return "specific" if lookup["*"] else "rejected"
    if has_include_only_filter:
        return "rejected"
    return "default"


def _explicit_public_cli_file_is_accepted(
    path: Path,
    extension_filters: tuple[ExtensionFilter, ...],
) -> bool:
    if not extension_filters or not path.exists():
        return True
    return public_cli_extension_filter_acceptance(path, extension_filters) != "rejected"


def _directory_ignore_path_values(path: Path) -> frozenset[str]:
    return frozenset(
        {
            str(path),
            path.as_posix(),
            str(path.resolve(strict=False)),
            path.resolve(strict=False).as_posix(),
        }
    )


def _path_extension_filter_value(path: Path) -> str:
    name = path.name
    dot_index = name.rfind(".")
    if dot_index < 0 or dot_index == len(name) - 1:
        return ""
    return name[dot_index + 1 :].upper()


def _normalized_extension_filter_value(extension: str) -> str:
    return extension.removeprefix(".").upper()
