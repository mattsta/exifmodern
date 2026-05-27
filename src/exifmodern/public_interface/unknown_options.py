"""ExifTool-compatible public unknown-tag option handling."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PublicUnknownBinaryBlockBlocker:
    code: str
    message: str
    evidence_sources: tuple[str, ...]


@dataclass(frozen=True)
class PublicRequestAllDeepDiscoveryBlocker:
    code: str
    message: str
    evidence_sources: tuple[str, ...]


@dataclass(frozen=True)
class PublicUnknownTagOptions:
    exiftool_unknown_level: Literal[0, 1, 2] = 0

    def with_option(self, option: str) -> PublicUnknownTagOptions:
        return PublicUnknownTagOptions(
            exiftool_unknown_level=_effective_unknown_level(
                self.exiftool_unknown_level + _unknown_option_increment(option)
            )
        )

    @property
    def include_suppressed_unknown_tags(self) -> bool:
        return self.exiftool_unknown_level > 0

    @property
    def requests_binary_block_unknown_discovery(self) -> bool:
        return self.exiftool_unknown_level > 1

    @property
    def binary_block_discovery_blocker(self) -> PublicUnknownBinaryBlockBlocker | None:
        if not self.requests_binary_block_unknown_discovery:
            return None
        return PublicUnknownBinaryBlockBlocker(
            code="unknown_binary_block_discovery_not_exposed",
            message=(
                "ExifTool -U/-unknown2 requests unknown information from binary data "
                "blocks. The public read graph now exposes source-backed JPEG EXIF/TIFF "
                "dynamic unknown IFD tags and a bounded JPEG APP0 AVI1 ProcessBinaryData "
                "unknown-byte slice, but generic ProcessBinaryData synthetic "
                "binary-block unknown discovery across arbitrary source tables remains "
                "package-local coverage still to be implemented."
            ),
            evidence_sources=(
                "public.unknown.binary-block.option-increment",
                "public.unknown.binary-block.process-binarydata",
                "public.unknown.binary-block.gettaginfo",
            ),
        )


@dataclass(frozen=True)
class PublicUnknownApiOptionPlan:
    unknown_options: PublicUnknownTagOptions = PublicUnknownTagOptions()
    request_all_level: int | None = None
    unsupported_options: tuple[str, ...] = ()

    @property
    def include_suppressed_unknown_tags(self) -> bool:
        return self.unknown_options.include_suppressed_unknown_tags

    @property
    def requests_binary_block_unknown_discovery(self) -> bool:
        return self.unknown_options.requests_binary_block_unknown_discovery

    @property
    def requests_deep_request_all_discovery(self) -> bool:
        return self.request_all_level is not None and self.request_all_level > 2

    @property
    def request_all_deep_discovery_blocker(
        self,
    ) -> PublicRequestAllDeepDiscoveryBlocker | None:
        if not self.requests_deep_request_all_discovery:
            return None
        return PublicRequestAllDeepDiscoveryBlocker(
            code="request_all_deep_discovery_partially_modeled",
            message=(
                "ExifTool -api RequestAll=3 requests tags that are normally "
                "generated only when specifically requested. Public read execution "
                "now routes bounded JPEG RequestAll=3 JPEGImageLength state into graph "
                "construction, but broader hidden/generated tag fanout remains partial."
            ),
            evidence_sources=(
                "public.unknown.requestall.processjpeg-image-length",
                "public.unknown.requestall.jpegimagelength-generated",
                "public.unknown.requestall.option-table",
            ),
        )


class PublicUnknownTagAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        if values not in (None, ()) and option_string is None:
            parser.error("internal public unknown option parser error")
        if isinstance(values, list) and values:
            parser.error("internal public unknown option parser error")
        if option_string is None:
            parser.error("internal public unknown option parser error")
        options = public_unknown_tag_options_from_namespace(namespace, self.dest)
        setattr(namespace, self.dest, options.with_option(option_string))


def public_unknown_tag_options_from_namespace(
    namespace: argparse.Namespace,
    attribute: str,
) -> PublicUnknownTagOptions:
    value = getattr(namespace, attribute, None)
    if isinstance(value, PublicUnknownTagOptions):
        return value
    return PublicUnknownTagOptions()


def public_unknown_tag_options_with_option(
    options: PublicUnknownTagOptions,
    option: str,
) -> PublicUnknownTagOptions:
    return options.with_option(option)


def public_unknown_tag_options_from_level(level: int) -> PublicUnknownTagOptions:
    if level < 0:
        raise argparse.ArgumentTypeError("unknown tag option level must be non-negative")
    return PublicUnknownTagOptions(exiftool_unknown_level=_effective_unknown_level(level))


def public_unknown_tag_options_from_args(args: Sequence[str]) -> PublicUnknownTagOptions:
    options = PublicUnknownTagOptions()
    for arg in args:
        if public_is_unknown_tag_option(arg):
            options = options.with_option(arg)
    return options


def public_unknown_api_option_plan_from_options(
    api_options: Sequence[str],
) -> PublicUnknownApiOptionPlan:
    unknown_options = PublicUnknownTagOptions()
    request_all_level: int | None = None
    unsupported_options: list[str] = []
    for raw_option in api_options:
        name, value = _split_public_unknown_api_option(raw_option)
        normalized_name = name.lower()
        if normalized_name == "unknown":
            level = _parse_public_unknown_api_nonnegative_int(value)
            if level is None:
                unsupported_options.append(raw_option)
                continue
            unknown_options = public_unknown_tag_options_from_level(level)
            continue
        if normalized_name == "requestall":
            level = _parse_public_unknown_api_nonnegative_int(value)
            if level is None:
                unsupported_options.append(raw_option)
                continue
            request_all_level = level
            continue
    return PublicUnknownApiOptionPlan(
        unknown_options=unknown_options,
        request_all_level=request_all_level,
        unsupported_options=tuple(unsupported_options),
    )


def public_is_unknown_tag_option(arg: str) -> bool:
    if arg == "-U":
        return True
    normalized = arg.removeprefix("-").lower()
    return normalized in {"u", "unknown", "unknown2"}


def _unknown_option_increment(option: str) -> int:
    if option == "-U":
        return 2
    normalized = option.removeprefix("-").lower()
    if normalized in {"u", "unknown"}:
        return 1
    if normalized == "unknown2":
        return 2
    raise argparse.ArgumentTypeError(f"unsupported unknown tag option: {option}")


def _effective_unknown_level(level: int) -> Literal[0, 1, 2]:
    if level <= 0:
        return 0
    if level == 1:
        return 1
    return 2


def _split_public_unknown_api_option(raw_option: str) -> tuple[str, str | None]:
    name, separator, value = raw_option.partition("=")
    if separator != "=":
        return name.removesuffix("^"), "1"
    if name.endswith("^"):
        return name.removesuffix("^"), value
    if value == "":
        return name, None
    return name, value


def _parse_public_unknown_api_nonnegative_int(value: str | None) -> int | None:
    if value is None:
        return None
    if not value.isdecimal():
        return None
    return int(value)
