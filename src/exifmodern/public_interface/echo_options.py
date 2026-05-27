"""Oracle-style top-level echo option handling for the public CLI."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedTopLevelEchoOptions:
    args: list[str]
    stdout_after: tuple[str, ...] = ()
    stderr_after: tuple[str, ...] = ()
    had_echo: bool = False


def prepare_top_level_echo_options(args: Sequence[str]) -> PreparedTopLevelEchoOptions:
    prepared_args: list[str] = []
    stdout_after: list[str] = []
    stderr_after: list[str] = []
    had_echo = False
    index = 0
    while index < len(args):
        arg = args[index]
        echo_number = top_level_echo_option_number(arg)
        if echo_number is None:
            prepared_args.append(arg)
            index += 1
            continue
        had_echo = True
        text_index = index + 1
        if text_index >= len(args):
            index += 1
            continue
        text = args[text_index]
        if echo_number == 1:
            print(text)
        elif echo_number == 2:
            print(text, file=sys.stderr)
        elif echo_number == 3:
            stdout_after.append(text)
        else:
            stderr_after.append(text)
        index += 2
    return PreparedTopLevelEchoOptions(
        args=prepared_args,
        stdout_after=tuple(stdout_after),
        stderr_after=tuple(stderr_after),
        had_echo=had_echo,
    )


def top_level_echo_option_number(arg: str) -> int | None:
    if not arg.startswith("-"):
        return None
    option = arg.removeprefix("-").lower()
    if option == "echo":
        return 1
    if option.startswith("echo") and option.removeprefix("echo").isdecimal():
        number = int(option.removeprefix("echo"))
        if 1 <= number <= 4:
            return number
    return None


def print_deferred_echo_options(options: PreparedTopLevelEchoOptions) -> None:
    for text in options.stdout_after:
        print(text)
    for text in options.stderr_after:
        print(text, file=sys.stderr)
