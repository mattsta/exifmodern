"""Typed public UserParam subset for trusted oracle-compatible reads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PublicUserParam:
    raw_argument: str
    name: str
    value: str | int | None
    extracted: bool = False


def parse_public_user_param_argument(argument: str) -> PublicUserParam:
    if "^=" in argument:
        name, value = argument.split("^=", 1)
        return _public_user_param(argument, name, value, force_empty=True)
    if "=" in argument:
        name, value = argument.split("=", 1)
        if value == "":
            return _public_user_param(argument, name, None, force_empty=False)
        return _public_user_param(argument, name, value, force_empty=False)
    return _public_user_param(argument, argument, 1, force_empty=False)


def original_file_user_params(path: Path) -> tuple[PublicUserParam, PublicUserParam]:
    return (
        PublicUserParam(
            raw_argument="OriginalDirectory#",
            name="originaldirectory#",
            value=_original_directory(path),
            extracted=True,
        ),
        PublicUserParam(
            raw_argument="OriginalFileName#",
            name="originalfilename#",
            value=path.name,
            extracted=True,
        ),
    )


def public_user_param_value(
    params: tuple[PublicUserParam, ...],
    tag: str,
) -> str | int | None:
    normalized = clean_public_user_param_name(tag)
    for candidate in (normalized, f"{normalized}#"):
        for param in reversed(params):
            if param.name == candidate:
                return param.value
    return None


def clean_public_user_param_name(name: str) -> str:
    return "".join(
        character.lower() for character in name if character.isalnum() or character in "-_#"
    )


def _public_user_param(
    raw_argument: str,
    name: str,
    value: str | int | None,
    *,
    force_empty: bool,
) -> PublicUserParam:
    clean_name = clean_public_user_param_name(name)
    extracted = clean_name.endswith("#")
    return PublicUserParam(
        raw_argument=raw_argument,
        name=clean_name,
        value="" if force_empty else value,
        extracted=extracted,
    )


def _original_directory(path: Path) -> str:
    parent = path.parent.as_posix()
    if parent == ".":
        return ""
    return f"{parent}/"
