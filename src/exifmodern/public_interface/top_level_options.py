"""ExifTool-style top-level public CLI option preparation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TopLevelOptionParseResult:
    args: list[str]
    quiet_count: int
    ignore_minor_errors: bool


def prepare_deferred_top_level_options(
    args: Sequence[str],
    *,
    quiet_count: int,
    ignore_minor_errors: bool,
) -> TopLevelOptionParseResult:
    if not is_top_level_exiftool_request(args):
        return TopLevelOptionParseResult(
            args=list(args),
            quiet_count=quiet_count,
            ignore_minor_errors=ignore_minor_errors,
        )
    prepared_args: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        lower_arg = arg.lower()
        if lower_arg in {"-q", "-quiet"}:
            quiet_count += 1
            index += 1
            continue
        if lower_arg in {"-m", "-ignoreminorerrors"}:
            ignore_minor_errors = True
            index += 1
            continue
        if lower_arg == "-config":
            index = _consume_top_level_config_option(
                args,
                index,
                has_prior_args=bool(prepared_args),
                quiet_count=quiet_count,
            )
            continue
        if lower_arg == "-stay_open":
            index = _consume_top_level_stay_open_option(args, index, quiet_count=quiet_count)
            continue
        if lower_arg == "-common_args":
            raise argparse.ArgumentTypeError(
                "public -common_args multi-command routing is not implemented yet; "
                "ExifTool constrains -common_args to top-level command lines after all other "
                "options, and disallows it inside -@ argfiles"
            )
        prepared_args.append(arg)
        index += 1
    return TopLevelOptionParseResult(
        args=prepared_args,
        quiet_count=quiet_count,
        ignore_minor_errors=ignore_minor_errors,
    )


def expand_top_level_argfiles(args: Sequence[str], *, depth: int = 0) -> list[str]:
    if not is_top_level_exiftool_request(args):
        return list(args)
    if depth > 20:
        raise argparse.ArgumentTypeError("too many nested -@ argfiles")

    expanded_args: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg != "-@":
            expanded_args.append(arg)
            index += 1
            continue

        argfile_index = index + 1
        if argfile_index >= len(args):
            raise argparse.ArgumentTypeError("Expecting filename for -@ option")
        argfile = args[argfile_index]
        expanded_args.extend(
            expand_top_level_argfiles(_read_argfile_args(argfile), depth=depth + 1)
        )
        index += 2
    return expanded_args


def is_top_level_exiftool_request(args: Sequence[str]) -> bool:
    return bool(args) and args[0] not in {
        "read",
        "inspect",
        "write",
        "capabilities",
        "-h",
        "--help",
    }


def _consume_top_level_config_option(
    args: Sequence[str],
    index: int,
    *,
    has_prior_args: bool,
    quiet_count: int,
) -> int:
    config_path_index = index + 1
    if config_path_index >= len(args):
        raise argparse.ArgumentTypeError("Expecting file name for -config option")
    config_path = args[config_path_index]
    if quiet_count >= 2:
        return config_path_index + 1
    if has_prior_args:
        print("Warning: Ignored -config option (not first on command line)", file=sys.stderr)
    else:
        print(
            "Warning: public -config file loading is deferred; "
            f"parsed and ignored config file {config_path!r}",
            file=sys.stderr,
        )
    return config_path_index + 1


def _consume_top_level_stay_open_option(
    args: Sequence[str],
    index: int,
    *,
    quiet_count: int,
) -> int:
    flag_index = index + 1
    if flag_index >= len(args):
        raise argparse.ArgumentTypeError("Expecting argument for -stay_open option")

    flag = args[flag_index].lower()
    if flag in {"0", "false"}:
        if quiet_count < 2:
            print("Warning: -stay_open wasn't active", file=sys.stderr)
        return flag_index + 1
    if flag not in {"1", "true"}:
        raise argparse.ArgumentTypeError("Invalid argument for -stay_open")

    argfile_detail = _stay_open_argfile_detail(args, flag_index + 1)
    raise argparse.ArgumentTypeError(
        "public -stay_open persistent protocol is not implemented yet; "
        f"recognized ExifTool-style '-stay_open {args[flag_index]}'{argfile_detail}; "
        "use one-shot -@ argfiles instead"
    )


def _stay_open_argfile_detail(args: Sequence[str], index: int) -> str:
    if index >= len(args):
        return " without required persistent -@ ARGFILE"
    if args[index] != "-@":
        return " without following persistent -@ ARGFILE"
    argfile_index = index + 1
    if argfile_index >= len(args):
        return " with missing persistent -@ ARGFILE"
    return f" with persistent argfile {args[argfile_index]!r}"


def _read_argfile_args(argfile: str) -> list[str]:
    if argfile == "-":
        lines = sys.stdin.read().lstrip("\ufeff").splitlines()
    else:
        path = Path(argfile)
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError as exc:
            raise argparse.ArgumentTypeError(f"Error opening arg file {argfile}") from exc

    parsed_args: list[str] = []
    for line in lines:
        parsed_arg = _parse_argfile_line(line)
        if parsed_arg is None:
            continue
        lower_arg = parsed_arg.lower()
        if lower_arg == "-config":
            raise argparse.ArgumentTypeError(
                "public -config inside -@ argfiles is not supported; "
                "ExifTool disallows -config in argfiles"
            )
        if lower_arg == "-common_args":
            raise argparse.ArgumentTypeError(
                "public -common_args inside -@ argfiles is not supported; "
                "ExifTool disallows -common_args in argfiles"
            )
        parsed_args.append(parsed_arg)
    return parsed_args


def _parse_argfile_line(line: str) -> str | None:
    if line.startswith("#[CSTR]"):
        return _parse_argfile_c_string(line.removeprefix("#[CSTR]"))
    if line.startswith("#"):
        return None
    arg = line.lstrip()
    if not arg:
        return None
    return _normalize_argfile_assignment_spacing(arg)


def _parse_argfile_c_string(value: str) -> str:
    value = _escape_argfile_c_string_literals(value)
    escapes = {
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        '"': '"',
        "\\": "\\",
    }
    parsed: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            parsed.append(escapes.get(escaped, f"\\{escaped}"))
            index += 2
            continue
        parsed.append(character)
        index += 1
    return "".join(parsed)


def _escape_argfile_c_string_literals(value: str) -> str:
    escaped: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            escaped.append("\\")
            escaped.append(value[index + 1])
            index += 2
            continue
        if character in {'"', "$", "@"} or (character == "\\" and index + 1 == len(value)):
            escaped.append("\\")
        escaped.append(character)
        index += 1
    return "".join(escaped)


def _normalize_argfile_assignment_spacing(arg: str) -> str:
    option_end = 0
    while option_end < len(arg):
        character = arg[option_end]
        if (
            character == "-"
            or character == "_"
            or character == ":"
            or character == "#"
            or character.isalnum()
        ):
            option_end += 1
            continue
        break
    option_name = arg[:option_end]
    if not option_name.startswith("-") or option_name == "-":
        return arg
    separator_start = option_end
    while separator_start < len(arg) and arg[separator_start].isspace():
        separator_start += 1
    for separator in ("+=", "-=", "<=", "="):
        if not arg.startswith(separator, separator_start):
            continue
        value_start = separator_start + len(separator)
        if value_start < len(arg) and arg[value_start] == " ":
            value_start += 1
        return f"{option_name}{separator}{arg[value_start:]}"
    return arg
