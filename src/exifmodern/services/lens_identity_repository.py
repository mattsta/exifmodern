"""Production lens identity repository models backed by packaged data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.services.lens_identity import (
    ExifLensIdentityRequest,
    LensIdentityResolution,
    LensIdentityTable,
    resolve_exif_lens_identity,
)

type SourceLensIdentityFamilyName = Literal[
    "canon_lens_types",
    "canon_rf_lens_type",
    "nikon_lens_ids",
    "pentax_lens_types",
    "sigma_lens_types",
    "minolta_a_mount",
    "sony_a_mount",
    "sony_e_mount",
    "minolta_teleconverters",
    "olympus_micro_four_thirds",
    "panasonic_leica",
]
type SourceLensIdentityLoadStatus = Literal["loaded", "missing_source", "unsupported"]
type SourceLensIdentityResolveStatus = Literal[
    "resolved",
    "missing_family",
    "missing_source",
    "unsupported",
]


@dataclass(frozen=True)
class SourceLensIdentityTableRecord:
    family: SourceLensIdentityFamilyName
    status: Literal["loaded"]
    owner: str
    source_module: str
    source_paths: tuple[str, ...]
    variable: str
    table: LensIdentityTable

    @property
    def entry_count(self) -> int:
        return len(self.table.entries)


@dataclass(frozen=True)
class SourceLensIdentityUnavailableFamily:
    family: SourceLensIdentityFamilyName
    status: Literal["missing_source", "unsupported"]
    owner: str
    source_module: str
    source_paths: tuple[str, ...]
    variable: str
    reason: str


type SourceLensIdentityFamily = SourceLensIdentityTableRecord | SourceLensIdentityUnavailableFamily


@dataclass(frozen=True)
class SourceLensIdentityResolvedFamily:
    family: SourceLensIdentityFamilyName
    status: Literal["resolved"]
    record: SourceLensIdentityTableRecord
    resolution: LensIdentityResolution


@dataclass(frozen=True)
class SourceLensIdentityUnavailableResolution:
    family: SourceLensIdentityFamilyName
    status: Literal["missing_source", "unsupported"]
    unavailable_family: SourceLensIdentityUnavailableFamily
    reason: str


@dataclass(frozen=True)
class SourceLensIdentityMissingFamilyResolution:
    family: SourceLensIdentityFamilyName
    status: Literal["missing_family"]
    reason: str


type SourceLensIdentityResolutionResult = (
    SourceLensIdentityResolvedFamily
    | SourceLensIdentityUnavailableResolution
    | SourceLensIdentityMissingFamilyResolution
)


@dataclass(frozen=True)
class SourceLensIdentityRepository:
    exiftool_root: Path
    families: tuple[SourceLensIdentityFamily, ...]

    @property
    def loaded_families(self) -> tuple[SourceLensIdentityTableRecord, ...]:
        return tuple(
            family for family in self.families if isinstance(family, SourceLensIdentityTableRecord)
        )

    @property
    def unavailable_families(self) -> tuple[SourceLensIdentityUnavailableFamily, ...]:
        return tuple(
            family
            for family in self.families
            if isinstance(family, SourceLensIdentityUnavailableFamily)
        )

    @property
    def loaded_family_count(self) -> int:
        return len(self.loaded_families)

    @property
    def unavailable_family_count(self) -> int:
        return len(self.unavailable_families)

    @property
    def total_entry_count(self) -> int:
        return sum(family.entry_count for family in self.loaded_families)

    def family(self, name: SourceLensIdentityFamilyName) -> SourceLensIdentityFamily | None:
        for family in self.families:
            if family.family == name:
                return family
        return None

    def table(self, name: SourceLensIdentityFamilyName) -> LensIdentityTable | None:
        family = self.family(name)
        if isinstance(family, SourceLensIdentityTableRecord):
            return family.table
        return None

    def resolve(
        self,
        name: SourceLensIdentityFamilyName,
        request: ExifLensIdentityRequest,
    ) -> SourceLensIdentityResolutionResult:
        family = self.family(name)
        if isinstance(family, SourceLensIdentityTableRecord):
            return SourceLensIdentityResolvedFamily(
                family=name,
                status="resolved",
                record=family,
                resolution=resolve_exif_lens_identity(request, family.table),
            )
        if isinstance(family, SourceLensIdentityUnavailableFamily):
            return SourceLensIdentityUnavailableResolution(
                family=name,
                status=family.status,
                unavailable_family=family,
                reason=family.reason,
            )
        return SourceLensIdentityMissingFamilyResolution(
            family=name,
            status="missing_family",
            reason=f"Source lens identity family is not registered: {name}.",
        )
