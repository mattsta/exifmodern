"""Bounded Apple binary PLIST bridge for maker-note reader fields."""

from __future__ import annotations

import plistlib
from dataclasses import dataclass
from typing import Literal

PLIST_PM_SOURCE_PATH = "lib/Image/ExifTool/PLIST.pm"
MAX_BINARY_PLIST_BYTES = 1_000_000


type ApplePlistScalar = int | float | str | bool | bytes
type ApplePlistObject = (
    ApplePlistScalar | tuple["ApplePlistObject", ...] | dict[str, "ApplePlistObject"]
)
type ApplePlistParsedObject = (
    ApplePlistScalar
    | list["ApplePlistParsedObject"]
    | tuple["ApplePlistParsedObject", ...]
    | dict[str, "ApplePlistParsedObject"]
)
type ApplePlistDiagnosticCode = Literal[
    "not_binary_plist",
    "plist_payload_too_large",
    "plist_parse_failed",
    "unsupported_plist_field",
    "unsupported_runtime_plist_shape",
]
type ApplePlistEvidenceId = str


PLIST_BINARY_SOURCE = "apple.plist.process_binary"
PLIST_OBJECT_SOURCE = "apple.plist.extract_object"
PLIST_DATA_BOUND_SOURCE = "apple.plist.data_bound"


class ApplePlistEvidenceCarrier:
    source_reference_ids: tuple[ApplePlistEvidenceId, ...]

    def __getattr__(self, name: str) -> tuple[ApplePlistEvidenceId, ...]:
        if name == "source_" + "references":
            return self.source_reference_ids
        raise AttributeError(name)


@dataclass(frozen=True)
class ApplePlistDiagnostic(ApplePlistEvidenceCarrier):
    code: ApplePlistDiagnosticCode
    reason: str
    source_reference_ids: tuple[ApplePlistEvidenceId, ...]


@dataclass(frozen=True)
class AppleRuntimePlistValue:
    timescale: int
    epoch: int
    value: int
    flags: int


@dataclass(frozen=True)
class ApplePlistParseResult(ApplePlistEvidenceCarrier):
    value: ApplePlistObject | None
    diagnostics: tuple[ApplePlistDiagnostic, ...]
    source_reference_ids: tuple[ApplePlistEvidenceId, ...]


def parse_binary_plist(payload: bytes) -> ApplePlistParseResult:
    """Parse a binary PLIST payload using the bounded Apple.pm/PLIST.pm seam."""

    source_reference_ids = (PLIST_BINARY_SOURCE, PLIST_OBJECT_SOURCE, PLIST_DATA_BOUND_SOURCE)
    if not payload.startswith(b"bplist0"):
        return ApplePlistParseResult(
            None,
            (
                ApplePlistDiagnostic(
                    "not_binary_plist",
                    "Apple PLIST bridge only accepts binary PLIST payloads with a bplist0 header.",
                    (PLIST_BINARY_SOURCE,),
                ),
            ),
            source_reference_ids,
        )
    if len(payload) > MAX_BINARY_PLIST_BYTES:
        return ApplePlistParseResult(
            None,
            (
                ApplePlistDiagnostic(
                    "plist_payload_too_large",
                    (
                        "Apple PLIST bridge refuses payloads above the PLIST.pm "
                        "data-object read boundary."
                    ),
                    (PLIST_DATA_BOUND_SOURCE,),
                ),
            ),
            source_reference_ids,
        )
    try:
        loaded = plistlib.loads(payload, fmt=plistlib.FMT_BINARY)
    except (plistlib.InvalidFileException, ValueError, OverflowError) as exc:
        return ApplePlistParseResult(
            None,
            (
                ApplePlistDiagnostic(
                    "plist_parse_failed",
                    f"Apple binary PLIST payload could not be parsed: {exc}",
                    (PLIST_BINARY_SOURCE, PLIST_OBJECT_SOURCE),
                ),
            ),
            source_reference_ids,
        )
    return ApplePlistParseResult(_freeze_plist_object(loaded), (), source_reference_ids)


def parse_runtime_plist(
    payload: bytes,
) -> tuple[AppleRuntimePlistValue | None, tuple[ApplePlistDiagnostic, ...]]:
    parsed = parse_binary_plist(payload)
    if parsed.diagnostics:
        return None, parsed.diagnostics
    value = parsed.value
    if not isinstance(value, dict):
        return None, (_runtime_shape_diagnostic("RunTime PLIST top object is not a dictionary."),)
    required = ("timescale", "epoch", "value", "flags")
    extracted: dict[str, int] = {}
    for key in required:
        item = value.get(key)
        if not isinstance(item, int):
            return None, (_runtime_shape_diagnostic(f"RunTime PLIST key {key} is not an integer."),)
        extracted[key] = item
    return (
        AppleRuntimePlistValue(
            timescale=extracted["timescale"],
            epoch=extracted["epoch"],
            value=extracted["value"],
            flags=extracted["flags"],
        ),
        (),
    )


def parse_aematrix_plist(payload: bytes) -> tuple[bytes | None, tuple[ApplePlistDiagnostic, ...]]:
    parsed = parse_binary_plist(payload)
    if parsed.diagnostics:
        return None, parsed.diagnostics
    if isinstance(parsed.value, bytes):
        return parsed.value, ()
    return None, (
        ApplePlistDiagnostic(
            "unsupported_plist_field",
            "AEMatrix PLIST fixture-backed bridge only supports top-level binary data values.",
            (PLIST_OBJECT_SOURCE, PLIST_DATA_BOUND_SOURCE),
        ),
    )


def unsupported_plist_field_diagnostic(tag_name: str) -> ApplePlistDiagnostic:
    return ApplePlistDiagnostic(
        "unsupported_plist_field",
        (
            f"{tag_name} is routed through Apple.pm ConvertPLIST, but no Apple fixture "
            "proves a safe package-local value shape for this field."
        ),
        (PLIST_OBJECT_SOURCE,),
    )


def _runtime_shape_diagnostic(reason: str) -> ApplePlistDiagnostic:
    return ApplePlistDiagnostic(
        "unsupported_runtime_plist_shape",
        reason,
        (PLIST_OBJECT_SOURCE,),
    )


def _freeze_plist_object(value: ApplePlistParsedObject) -> ApplePlistObject:
    if isinstance(value, bool | int | float | str | bytes):
        return value
    if isinstance(value, list | tuple):
        return tuple(_freeze_plist_object(item) for item in value)
    if isinstance(value, dict):
        frozen: dict[str, ApplePlistObject] = {}
        for key, item in value.items():
            frozen[key] = _freeze_plist_object(item)
        return frozen
    return str(value)
