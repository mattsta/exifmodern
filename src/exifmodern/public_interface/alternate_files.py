"""Oracle-compatible bounded alternate-file path formatting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.public_interface.output_policy import (
    PublicFilenameSprintfTagContext,
    public_filename_sprintf,
)
from exifmodern.public_interface.user_params import (
    PublicUserParam,
    original_file_user_params,
    public_user_param_value,
)

type PublicInsertTagValueScalar = str | int | float | bool
type PublicInsertTagValueRaw = PublicInsertTagValueScalar | bytes | tuple[str, ...] | None
type PublicInsertTagInterpolationIssueReason = Literal[
    "missing",
    "non_scalar",
    "advanced_expression",
]

_FILENAME_SPRINTF_TOKEN_RE = re.compile(r"%[-+]?\d*[.:]?\d*[lu]?[dDfFeEtgso]")
_INSERT_TAG_VALUES_TOKEN_RE = re.compile(r"\$(\{\s*)?((?:[-\w]*\w:)*[-\w]*\w#?|\$|/)(?:\s*\})?")
_INSERT_TAG_VALUES_ADVANCED_RE = re.compile(r"\$\{\s*(?:[-\w]*\w:)*[-\w]*\w#?\s*;")


@dataclass(frozen=True)
class AlternateFileFormatSupport:
    source_alias: bool
    filename_percent_codes: bool
    tag_interpolation: bool


@dataclass(frozen=True)
class PublicInsertTagValue:
    token: str
    value: PublicInsertTagValueRaw


@dataclass(frozen=True)
class PublicInsertTagInterpolationIssue:
    token: str
    reason: PublicInsertTagInterpolationIssueReason


def alternate_file_format_support(raw_path: str) -> AlternateFileFormatSupport:
    return AlternateFileFormatSupport(
        source_alias=raw_path == "@",
        filename_percent_codes=_FILENAME_SPRINTF_TOKEN_RE.search(raw_path) is not None,
        tag_interpolation=_has_insert_tag_values_tag_interpolation(raw_path),
    )


def alternate_file_has_unsupported_tag_interpolation(
    raw_path: str,
    user_params: tuple[PublicUserParam, ...] = (),
    tag_values: tuple[PublicInsertTagValue, ...] = (),
) -> bool:
    return bool(public_insert_tag_interpolation_issues(raw_path, user_params, tag_values))


def alternate_file_has_advanced_tag_interpolation(raw_path: str) -> bool:
    return _INSERT_TAG_VALUES_ADVANCED_RE.search(raw_path) is not None


def public_insert_tag_value_tokens(raw_path: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in _INSERT_TAG_VALUES_TOKEN_RE.finditer(raw_path):
        token = match.group(2)
        if token not in {"$", "/"}:
            tokens.append(token)
    return tuple(tokens)


def public_unresolved_insert_tag_value_tokens(
    raw_path: str,
    user_params: tuple[PublicUserParam, ...] = (),
    tag_values: tuple[PublicInsertTagValue, ...] = (),
) -> tuple[str, ...]:
    return tuple(
        issue.token
        for issue in public_insert_tag_interpolation_issues(
            raw_path,
            user_params,
            tag_values,
        )
    )


def public_insert_tag_interpolation_issues(
    raw_path: str,
    user_params: tuple[PublicUserParam, ...] = (),
    tag_values: tuple[PublicInsertTagValue, ...] = (),
) -> tuple[PublicInsertTagInterpolationIssue, ...]:
    if _INSERT_TAG_VALUES_ADVANCED_RE.search(raw_path):
        return tuple(
            PublicInsertTagInterpolationIssue(token, "advanced_expression")
            for token in public_insert_tag_value_tokens(raw_path)
        )
    issues: list[PublicInsertTagInterpolationIssue] = []
    for token in public_insert_tag_value_tokens(raw_path):
        if public_user_param_value(user_params, token) is not None:
            continue
        tag_value = _public_insert_tag_value(tag_values, token)
        if tag_value is None:
            issues.append(PublicInsertTagInterpolationIssue(token, "missing"))
            continue
        if _public_insert_tag_value_scalar_text(tag_value) is None:
            issues.append(PublicInsertTagInterpolationIssue(token, "non_scalar"))
    return tuple(issues)


def resolve_alternate_file_path(
    raw_path: Path,
    source_path: Path,
    user_params: tuple[PublicUserParam, ...] = (),
    tag_values: tuple[PublicInsertTagValue, ...] = (),
) -> Path:
    effective_user_params = (*original_file_user_params(source_path), *user_params)
    raw_text = raw_path.as_posix()
    if raw_text == "@":
        return source_path
    raw_text = _resolve_safe_insert_tag_values_literals(
        raw_text,
        effective_user_params,
        tag_values,
    )
    if _FILENAME_SPRINTF_TOKEN_RE.search(raw_text) is None:
        return Path(raw_text)
    return Path(filename_sprintf(raw_text, source_path.as_posix()))


def _has_insert_tag_values_tag_interpolation(raw_path: str) -> bool:
    if _INSERT_TAG_VALUES_ADVANCED_RE.search(raw_path):
        return True
    for match in _INSERT_TAG_VALUES_TOKEN_RE.finditer(raw_path):
        if match.group(2) not in {"$", "/"}:
            return True
    return False


def _resolve_safe_insert_tag_values_literals(
    raw_path: str,
    user_params: tuple[PublicUserParam, ...],
    tag_values: tuple[PublicInsertTagValue, ...] = (),
) -> str:
    def replacement(match: re.Match[str]) -> str:
        token = match.group(2)
        if token == "$":
            return "$"
        if token == "/":
            return "\n"
        value = public_user_param_value(user_params, token)
        if value is not None:
            return str(value)
        tag_value = _public_insert_tag_value(tag_values, token)
        tag_text = _public_insert_tag_value_scalar_text(tag_value)
        if tag_text is not None:
            return tag_text
        return match.group(0)

    return _INSERT_TAG_VALUES_TOKEN_RE.sub(replacement, raw_path)


def _public_insert_tag_value(
    tag_values: tuple[PublicInsertTagValue, ...],
    token: str,
) -> PublicInsertTagValueRaw:
    normalized = token.removesuffix("#").casefold()
    for tag_value in tag_values:
        if tag_value.token.removesuffix("#").casefold() == normalized:
            return tag_value.value
    return None


def _public_insert_tag_value_scalar_text(value: PublicInsertTagValueRaw) -> str | None:
    if value is None or isinstance(value, bytes | tuple):
        return None
    return str(value)


def filename_sprintf(
    format_text: str,
    source_file: str,
    tag_context: PublicFilenameSprintfTagContext | None = None,
) -> str:
    return public_filename_sprintf(
        format_template=format_text,
        source_path=Path(source_file),
        tag_context=tag_context,
    )
