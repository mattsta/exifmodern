"""Bounded public condition/file-order/source-file compatibility helpers."""

from __future__ import annotations

import re

type PublicBoundedAlternateFileSlot = int

_ALTERNATE_FILE_OPTION_RE = re.compile(r"^-file(?P<slot>\d+)$", re.IGNORECASE)
_FILENAME_SPRINTF_EXTRA_TOKEN_RE = re.compile(
    r"%[-+]?\d*[.:]?\d*[lu]?(?P<code>[tgso])(?P<group_index>\d?)"
)

CONDITION_FILE_ORDER_SOURCE_EVIDENCE = (
    "public.conditionals.file-slot-options",
    "public.conditionals.if-options",
    "public.conditionals.srcfile-resolution",
    "public.conditionals.filename-sprintf",
    "public.conditionals.alternate-file-interpolation",
    "public.conditionals.filenum-tag-routing",
)


def is_public_alternate_file_option(option: str) -> bool:
    return _ALTERNATE_FILE_OPTION_RE.fullmatch(option) is not None


def public_bounded_alternate_file_slot(
    option: str,
) -> PublicBoundedAlternateFileSlot | None:
    match = _ALTERNATE_FILE_OPTION_RE.fullmatch(option)
    if match is None:
        return None
    slot = int(match.group("slot"))
    return slot


def public_alternate_file_slot_deferred_message(option: str) -> str:
    return (
        f"public alternate-file read routing for {option} requires a numeric "
        "ExifTool -fileNUM slot. Public support is limited to the semantic "
        "alternate-file routing contract until full FileNUM tag selector state "
        "is represented."
    )


def public_filename_sprintf_extra_tokens(format_text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in _FILENAME_SPRINTF_EXTRA_TOKEN_RE.finditer(format_text):
        tokens.append(match.group(0))
    return tuple(tokens)


def public_filename_sprintf_extra_tokens_deferred_message(
    option: str,
    format_text: str,
    tokens: tuple[str, ...],
) -> str:
    token_list = ", ".join(tokens)
    return (
        f"public {option} filename formatting for {format_text!r} uses "
        f"FilenameSPrintf extra-output token(s) {token_list}. ExifTool resolves "
        "these tokens from optional tag-output context; public -srcfile/-fileNUM "
        "execution resolves them through the shared source-backed formatter with "
        "empty tag context and still defers $tag interpolation."
    )
