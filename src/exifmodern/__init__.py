# mypy: disable-error-code=no-untyped-def
"""Python-native ExifModern metadata API."""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "ExifModernBytes",
    "ExifModernEdit",
    "ExifModernFile",
    "MetadataDeleteTags",
    "MetadataPath",
    "MetadataPendingOperation",
    "MetadataPendingOperations",
    "MetadataTagAssignments",
    "MetadataTagNames",
    "MetadataValues",
    "__version__",
    "delete_tags",
    "from_bytes",
    "open_file",
    "read_args",
    "read_bytes",
    "read_file",
    "read_files",
    "remove_gps",
    "set_tags",
    "write_file",
]


def __getattr__(name: str):
    if name not in __all__ or name == "__version__":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from exifmodern import api

    value = getattr(api, name)
    globals()[name] = value
    return value
