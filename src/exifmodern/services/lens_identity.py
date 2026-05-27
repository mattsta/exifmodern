"""Typed lens identity service primitives.

This module ports the deterministic, table-driven core of ExifTool's
`Exif::PrintLensID` into an explicit service boundary. It intentionally does
not embed vendor lens tables here; owner modules provide normalized
`LensIdentityTable` records.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

type LensTypeValue = str | int

LENS_OPTICS_RE = re.compile(
    r"(?P<sf>\d+(?:\.\d+)?)"
    r"(?:\s*-\s*(?P<lf>\d+(?:\.\d+)?))?"
    r"\s*mm\b.*?\bF/?"
    r"(?P<sa>\d+(?:\.\d+)?)"
    r"(?:\s*-\s*(?P<la>\d+(?:\.\d+)?))?",
    re.IGNORECASE,
)
LENS_FOCAL_RANGE_RE = re.compile(r"^(?P<sf>\d+)(?: (?:to )?(?P<lf>\d+))?$")


@dataclass(frozen=True)
class LensIdentityEntry:
    key: str
    name: str
    user_defined: bool = False


@dataclass(frozen=True)
class LensIdentityTable:
    entries: tuple[LensIdentityEntry, ...]

    def entry_for_key(self, key: str) -> LensIdentityEntry | None:
        for entry in self.entries:
            if entry.key == key:
                return entry
        return None

    def name_for_key(self, key: str) -> str | None:
        entry = self.entry_for_key(key)
        return None if entry is None else entry.name

    def candidates_for_key(self, key: str) -> tuple[LensIdentityEntry, ...]:
        candidates: list[LensIdentityEntry] = []
        base_entry = self.entry_for_key(key)
        if base_entry is None:
            return ()
        candidates.append(
            LensIdentityEntry(
                key=key,
                name=first_or_lens_name(base_entry.name),
                user_defined=base_entry.user_defined,
            )
        )
        variant_index = 1
        while True:
            variant_key = f"{key}.{variant_index}"
            variant_name = self.name_for_key(variant_key)
            if variant_name is None:
                return tuple(candidates)
            candidates.append(LensIdentityEntry(key=variant_key, name=variant_name))
            variant_index += 1


@dataclass(frozen=True)
class LensOptics:
    short_focal: float
    long_focal: float
    short_aperture: float
    long_aperture: float


@dataclass(frozen=True)
class ExifLensIdentityRequest:
    lens_type: LensTypeValue | None
    lens_type_print: str
    make: str = ""
    model: str = ""
    lens_spec_print: str | None = None
    focal_length: float | None = None
    max_aperture: float | None = None
    max_aperture_value: float | None = None
    short_focal: float | None = None
    long_focal: float | None = None
    lens_model: str | None = None
    lens_focal_range: str | None = None
    lens_spec: str | None = None


@dataclass(frozen=True)
class LensIdentityResolution:
    value: str | None
    candidates: tuple[str, ...]
    reason: str


def resolve_exif_lens_identity(
    request: ExifLensIdentityRequest,
    table: LensIdentityTable,
) -> LensIdentityResolution:
    if request.lens_type is None:
        return LensIdentityResolution(value=None, candidates=(), reason="missing_lens_type")
    if not table.entries:
        return print_value_only_resolution(request.lens_type_print)

    key = lens_type_key(request.lens_type)
    lens_name = table.name_for_key(key)
    if lens_name is None:
        return LensIdentityResolution(
            value=request.lens_model or request.lens_type_print,
            candidates=(),
            reason="unknown_lens_type",
        )

    candidate_entries = table.candidates_for_key(key)
    if len(candidate_entries) == 1:
        return LensIdentityResolution(
            value=lens_name,
            candidates=(lens_name,),
            reason="single_table_match",
        )

    candidates = tuple(entry.name for entry in candidate_entries)
    user_candidates = tuple(entry.name for entry in candidate_entries if entry.user_defined)
    if user_candidates:
        return LensIdentityResolution(
            value=" or ".join(user_candidates),
            candidates=user_candidates,
            reason="user_defined_match",
        )

    best_candidates = best_lens_candidates(request, candidates)
    if best_candidates:
        return LensIdentityResolution(
            value=" or ".join(best_candidates),
            candidates=best_candidates,
            reason="optics_filtered_match",
        )

    if request.lens_model and " or " in lens_name:
        return LensIdentityResolution(
            value=request.lens_model,
            candidates=candidates,
            reason="ambiguous_lens_model_fallback",
        )
    return LensIdentityResolution(
        value=lens_name,
        candidates=candidates,
        reason="unfiltered_ambiguous_match",
    )


def print_value_only_resolution(lens_type_print: str) -> LensIdentityResolution:
    if "mm" in lens_type_print:
        return LensIdentityResolution(
            value=lens_type_print,
            candidates=(lens_type_print,),
            reason="print_value_is_lens_name",
        )
    converted = re.sub(r"(\d)/F", r"\1mm F", lens_type_print)
    if converted != lens_type_print:
        return LensIdentityResolution(
            value=converted,
            candidates=(converted,),
            reason="print_value_slash_f_lens_name",
        )
    return LensIdentityResolution(value=None, candidates=(), reason="print_value_not_lens_name")


def best_lens_candidates(
    request: ExifLensIdentityRequest,
    candidates: tuple[str, ...],
) -> tuple[str, ...]:
    lens_spec_optics = parse_lens_optics(request.lens_spec_print) or request_lens_optics(request)
    focal_length = request.focal_length or single_focal_length(request)
    max_aperture = request.max_aperture or request.max_aperture_value

    matches: list[str] = []
    best: list[str] = []
    best_aperture_delta: float | None = None
    for candidate in candidates:
        optics = parse_lens_optics(candidate)
        if optics is None:
            continue
        if lens_spec_optics is not None:
            if not optics_match(optics, lens_spec_optics):
                continue
            if request.lens_spec_print and lens_spec_name_matches(
                candidate,
                request.lens_spec_print,
            ):
                return (candidate,)
            best.append(candidate)
            continue
        if focal_length is not None:
            if focal_length < optics.short_focal - 0.5:
                continue
            if focal_length > optics.long_focal + 0.5:
                continue
        if max_aperture is not None:
            if max_aperture < optics.short_aperture - 0.15:
                continue
            if max_aperture > optics.long_aperture + 0.15:
                continue
            aperture_delta = abs(max_aperture - approximate_max_aperture(optics, focal_length))
            if best_aperture_delta is None:
                best_aperture_delta = aperture_delta
            elif aperture_delta < best_aperture_delta - 0.15:
                best.clear()
                best_aperture_delta = aperture_delta
            elif aperture_delta > best_aperture_delta + 0.15:
                continue
            best.append(candidate)
        matches.append(candidate)
    if best:
        return tuple(best)
    return tuple(matches)


def request_lens_optics(request: ExifLensIdentityRequest) -> LensOptics | None:
    if request.short_focal is None or request.long_focal is None:
        return None
    short_aperture = request.max_aperture or request.max_aperture_value
    if short_aperture is None:
        return None
    long_aperture = request.max_aperture_value or short_aperture
    return LensOptics(
        short_focal=request.short_focal,
        long_focal=request.long_focal,
        short_aperture=short_aperture,
        long_aperture=long_aperture,
    )


def lens_spec_name_matches(candidate: str, lens_spec_print: str) -> bool:
    suffix_start = candidate.find(f" {lens_spec_print}")
    if suffix_start < 0:
        return False
    suffix = candidate[suffix_start + len(lens_spec_print) + 1 :]
    return suffix == "" or suffix.startswith(" (") or suffix == " GM"


def single_focal_length(request: ExifLensIdentityRequest) -> float | None:
    if request.short_focal is None:
        return None
    if request.long_focal is None or request.long_focal == request.short_focal:
        return request.short_focal
    return None


def parse_lens_optics(value: str | None) -> LensOptics | None:
    if value is None:
        return None
    match = LENS_OPTICS_RE.search(value)
    if match is None:
        return None
    short_focal = float(match.group("sf"))
    long_focal = float(match.group("lf") or short_focal)
    short_aperture = float(match.group("sa"))
    long_aperture = float(match.group("la") or short_aperture)
    return LensOptics(
        short_focal=short_focal,
        long_focal=long_focal,
        short_aperture=short_aperture,
        long_aperture=long_aperture,
    )


def optics_match(left: LensOptics, right: LensOptics) -> bool:
    return (
        abs(left.short_focal - right.short_focal) <= 0.5
        and abs(left.long_focal - right.long_focal) <= 0.5
        and abs(left.short_aperture - right.short_aperture) <= 0.15
        and abs(left.long_aperture - right.long_aperture) <= 0.15
    )


def approximate_max_aperture(optics: LensOptics, focal_length: float | None) -> float:
    if focal_length is None or optics.short_focal == optics.long_focal:
        return optics.short_aperture
    if optics.short_aperture == optics.long_aperture or focal_length <= optics.short_focal:
        return optics.short_aperture
    if focal_length >= optics.long_focal:
        return optics.long_aperture
    return math.exp(
        math.log(optics.short_aperture)
        + (math.log(optics.long_aperture) - math.log(optics.short_aperture))
        / (math.log(optics.long_focal) - math.log(optics.short_focal))
        * (math.log(focal_length) - math.log(optics.short_focal))
    )


def lens_type_key(value: LensTypeValue) -> str:
    return str(value)


def first_or_lens_name(value: str) -> str:
    return value.split(" or ", 1)[0]
