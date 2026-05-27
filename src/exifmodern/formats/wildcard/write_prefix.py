"""Typed expansion for ExifTool-style prefix wildcard write arguments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.xmp.property_write import (
    XMP_NAMESPACE_URIS,
    XmpGeneratedPropertyAssignment,
    generated_capabilities_by_property,
    simple_struct_assignment_target,
)

type WildcardWritePrefix = Literal["A"]
type WildcardXmpShape = Literal[
    "scalar_text",
    "scalar_boolean",
    "scalar_numeric",
    "list_text",
    "lang_alt",
]

A_PREFIX_EXIF_ARGS = (
    "Artist",
    "ApertureValue",
    "AmbientTemperature",
    "Acceleration",
)
A_PREFIX_IPTC_WIDTHS: dict[str, int | None] = {
    "ARMIdentifier": None,
    "ARMVersion": None,
    "ApplicationRecordVersion": None,
    "AudioSamplingRate": 6,
    "AudioSamplingResolution": 2,
    "AudioDuration": 6,
    "AudioOutcue": None,
}
A_PREFIX_SUPPORTED_XMP_SHAPES: set[WildcardXmpShape] = {
    "scalar_text",
    "scalar_boolean",
    "scalar_numeric",
    "list_text",
    "lang_alt",
}
A_PREFIX_SUPPORTED_XMP_STRATEGIES = {
    "current_property_spec",
    "generated_simple_property_spec",
    "generated_list_property_spec",
    "generated_lang_alt_property_spec",
}


@dataclass(frozen=True)
class WildcardWriteExpansion:
    exif_scalar_args: tuple[str, ...]
    iptc_args: tuple[str, ...]
    xmp_assignments: tuple[XmpGeneratedPropertyAssignment, ...]

    @property
    def assignment_count(self) -> int:
        return len(self.exif_scalar_args) + len(self.iptc_args) + len(self.xmp_assignments)


def wildcard_write_expansion_from_args(
    write_args: tuple[str, ...],
    capability_audit: Path,
) -> WildcardWriteExpansion:
    expansions = [
        expansion
        for arg in write_args
        if (expansion := wildcard_write_expansion_from_arg(arg, capability_audit)) is not None
    ]
    return WildcardWriteExpansion(
        exif_scalar_args=tuple(
            arg for expansion in expansions for arg in expansion.exif_scalar_args
        ),
        iptc_args=tuple(arg for expansion in expansions for arg in expansion.iptc_args),
        xmp_assignments=tuple(
            assignment for expansion in expansions for assignment in expansion.xmp_assignments
        ),
    )


def wildcard_write_expansion_from_arg(
    write_arg: str,
    capability_audit: Path,
) -> WildcardWriteExpansion | None:
    if not write_arg.startswith("-") or "=" not in write_arg:
        return None
    tag_token, value = write_arg[1:].split("=", 1)
    prefix = wildcard_prefix_or_none(tag_token)
    if prefix is None:
        return None
    return WildcardWriteExpansion(
        exif_scalar_args=prefix_exif_scalar_args(prefix, value),
        iptc_args=prefix_iptc_args(prefix, value),
        xmp_assignments=prefix_xmp_assignments(prefix, value, capability_audit),
    )


def wildcard_prefix_or_none(tag_token: str) -> WildcardWritePrefix | None:
    if tag_token == "A*":
        return "A"
    return None


def prefix_exif_scalar_args(prefix: WildcardWritePrefix, value: str) -> tuple[str, ...]:
    if prefix == "A":
        return tuple(f"-{tag_name}={value}" for tag_name in A_PREFIX_EXIF_ARGS)


def prefix_iptc_args(prefix: WildcardWritePrefix, value: str) -> tuple[str, ...]:
    if prefix != "A":
        return ()
    return tuple(
        f"-IPTC:{tag_name}={wildcard_iptc_value(value, width)}"
        for tag_name, width in A_PREFIX_IPTC_WIDTHS.items()
    )


def wildcard_iptc_value(value: str, width: int | None) -> str:
    if width is None:
        return value
    stripped = value.strip()
    if stripped.isdecimal():
        return stripped.zfill(width)
    return stripped


def prefix_xmp_assignments(
    prefix: WildcardWritePrefix,
    value: str,
    capability_audit: Path,
) -> tuple[XmpGeneratedPropertyAssignment, ...]:
    capabilities = generated_capabilities_by_property(capability_audit)
    assignments: list[XmpGeneratedPropertyAssignment] = []
    for capability in capabilities.values():
        if not capability.tag_name.startswith(prefix):
            continue
        if capability.modernization_strategy not in A_PREFIX_SUPPORTED_XMP_STRATEGIES:
            continue
        if capability.namespace_prefix not in XMP_NAMESPACE_URIS:
            continue
        if simple_struct_assignment_target(capability.property_name) is not None:
            continue
        assignment_value = wildcard_xmp_value(value, capability.shape)
        if assignment_value is None:
            continue
        assignments.append(
            XmpGeneratedPropertyAssignment(capability.property_name, assignment_value)
        )
    return tuple(assignments)


def wildcard_xmp_value(value: str, shape: str) -> str | None:
    if shape not in A_PREFIX_SUPPORTED_XMP_SHAPES:
        return None
    if shape == "scalar_boolean":
        return wildcard_boolean_value(value)
    return value


def wildcard_boolean_value(value: str) -> str:
    stripped = value.strip().lower()
    if stripped in {"", "0", "false", "no"}:
        return "false"
    return "true"
