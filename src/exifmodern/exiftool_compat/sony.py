"""Sony exact-helper compatibility adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass

from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolScalar,
    perl_truthy,
    string_value,
)


@dataclass(frozen=True)
class SonyLensFeature:
    bits_to_name: tuple[tuple[int, str], ...]


SONY_LENS_FEATURES: tuple[SonyLensFeature, ...] = (
    SonyLensFeature(((0x4000, "PZ"),)),
    SonyLensFeature(((0x0100, "DT"), (0x0200, "FE"), (0x0300, "E"))),
    SonyLensFeature(((0x0020, "STF"), (0x0040, "Reflex"), (0x0060, "Macro"), (0x0080, "Fisheye"))),
    SonyLensFeature(((0x0004, "ZA"), (0x0008, "G"))),
    SonyLensFeature(((0x0001, "SSM"), (0x0002, "SAM"))),
    SonyLensFeature(((0x8000, "OSS"),)),
    SonyLensFeature(((0x2000, "LE"),)),
    SonyLensFeature(((0x0800, "II"),)),
)
UNKNOWN_LENS_SPEC_RE = re.compile(r"Unknown \((.*)\)", re.IGNORECASE)


def print_inv_lens_spec(values: list[ExifToolScalar]) -> ExifToolScalar:
    if not 1 <= len(values) <= 3:
        raise ExifToolCompatibilityError(
            f"PrintInvLensSpec expected 1 to 3 arguments, got {len(values)}."
        )
    text = string_value(values[0])
    unknown_match = UNKNOWN_LENS_SPEC_RE.search(text)
    if unknown_match is not None:
        return unknown_match.group(1)
    has_feature_only_output = len(values) >= 3 and perl_truthy(values[2])
    if not has_feature_only_output:
        raise ExifToolCompatibilityError(
            "PrintInvLensSpec full lens-spec inverse requires typed lens-info parsing."
        )
    flags = sony_lens_feature_flags(text)
    return f"{flags >> 8:02x} {flags & 0xFF:02x}"


def sony_lens_feature_flags(text: str) -> int:
    flags = 0
    for feature in SONY_LENS_FEATURES:
        for bits, name in feature.bits_to_name:
            if sony_lens_feature_matches(text, name):
                flags |= bits
    return flags


def sony_lens_feature_matches(text: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) is not None
