"""Filesystem-backed System pseudo-tags."""

from __future__ import annotations

import grp
import pwd
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from exifmodern.json_types import JsonObject

type SystemDisplayPath = str


@dataclass(frozen=True)
class SystemPathParts:
    directory: str
    file_name: str


def read_system_tags(path: Path, display_path: SystemDisplayPath | None = None) -> JsonObject:
    path_stat = path.stat()
    display_parts = system_path_parts(display_path or path.as_posix())
    return {
        "FileName": display_parts.file_name,
        "Directory": display_parts.directory,
        "FileSize": exiftool_file_size(path_stat.st_size),
        "FileModifyDate": exiftool_datetime(path_stat.st_mtime),
        "FileAccessDate": exiftool_datetime(path_stat.st_atime),
        "FileInodeChangeDate": exiftool_datetime(path_stat.st_ctime),
        "FilePermissions": exiftool_permissions(path_stat.st_mode),
    }


def system_path_parts(display_path: SystemDisplayPath) -> SystemPathParts:
    pure_path = PurePosixPath(display_path)
    directory = pure_path.parent.as_posix()
    if directory == "":
        directory = "."
    return SystemPathParts(directory=directory, file_name=pure_path.name)


def exiftool_file_size(size_bytes: int) -> str:
    if size_bytes < 2000:
        return f"{size_bytes} bytes"
    if size_bytes < 10000:
        return f"{size_bytes / 1000:.1f} kB"
    if size_bytes < 2000000:
        return f"{size_bytes / 1000:.0f} kB"
    if size_bytes < 10000000:
        return f"{size_bytes / 1000000:.1f} MB"
    if size_bytes < 2000000000:
        return f"{size_bytes / 1000000:.0f} MB"
    if size_bytes < 10000000000:
        return f"{size_bytes / 1000000000:.1f} GB"
    return f"{size_bytes / 1000000000:.0f} GB"


def exiftool_datetime(timestamp: float) -> str:
    value = datetime.fromtimestamp(timestamp).astimezone()
    offset = value.strftime("%z")
    return f"{value:%Y:%m:%d %H:%M:%S}{offset[:3]}:{offset[3:]}"


def exiftool_permissions(mode: int) -> str:
    type_character = exiftool_file_type_character(mode)
    permission_bits = (
        (stat.S_IRUSR, "r"),
        (stat.S_IWUSR, "w"),
        (stat.S_IXUSR, "x"),
        (stat.S_IRGRP, "r"),
        (stat.S_IWGRP, "w"),
        (stat.S_IXGRP, "x"),
        (stat.S_IROTH, "r"),
        (stat.S_IWOTH, "w"),
        (stat.S_IXOTH, "x"),
    )
    return type_character + "".join(char if mode & bit else "-" for bit, char in permission_bits)


def exiftool_file_type_character(mode: int) -> str:
    file_type = stat.S_IFMT(mode)
    return {
        stat.S_IFIFO: "p",
        stat.S_IFCHR: "c",
        stat.S_IFDIR: "d",
        stat.S_IFBLK: "b",
        stat.S_IFLNK: "l",
        stat.S_IFSOCK: "s",
    }.get(file_type, "-")


def group_name_or_none(group_id: int) -> str | None:
    try:
        return grp.getgrgid(group_id).gr_name
    except KeyError:
        return None


def user_name_or_none(user_id: int) -> str | None:
    try:
        return pwd.getpwuid(user_id).pw_name
    except KeyError:
        return None
