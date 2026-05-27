"""Source-backed DNG protected write planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.exif_scalar_write_plan import (
    ExifScalarWritePlan,
    build_exif_scalar_write_plan,
)
from exifmodern.formats.dng.private_data_writer import (
    DngOriginalDecisionDataFullFileInstallContract,
    DngOriginalDecisionDataWriteClassification,
    build_original_decision_data_full_file_install_contract,
    classify_original_decision_data_write,
)
from exifmodern.formats.dng.report_serialization import EvidenceId

type DngProtectedTagName = Literal["OwnerName", "OriginalDecisionData"]
type DngProtectedSurfaceStatus = Literal["implemented", "blocked"]


@dataclass(frozen=True)
class DngProtectedWriteSurface:
    tag_name: DngProtectedTagName
    status: DngProtectedSurfaceStatus
    write_group: str
    reason: str
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class DngProtectedWritePlan:
    surfaces: tuple[DngProtectedWriteSurface, ...]
    owner_name_exif_scalar_plan: ExifScalarWritePlan | None
    original_decision_data_classification: DngOriginalDecisionDataWriteClassification | None
    original_decision_data_full_file_contract: DngOriginalDecisionDataFullFileInstallContract | None
    safety_gates: tuple[str, ...]

    @property
    def implemented_surfaces(self) -> tuple[DngProtectedWriteSurface, ...]:
        return tuple(surface for surface in self.surfaces if surface.status == "implemented")

    @property
    def deferred_surfaces(self) -> tuple[DngProtectedWriteSurface, ...]:
        return tuple(surface for surface in self.surfaces if surface.status == "blocked")


def build_dng_protected_write_plan(
    owner_name: str | None,
    original_decision_data: bytes | None,
    protected: int,
    file_data: bytes | None = None,
) -> DngProtectedWritePlan:
    surfaces: list[DngProtectedWriteSurface] = []
    owner_name_plan = None
    if owner_name is not None:
        owner_name_plan = build_exif_scalar_write_plan(
            image_description=None,
            orientation=None,
            date_time_original=None,
            owner_name=owner_name,
        )
        surfaces.append(
            DngProtectedWriteSurface(
                tag_name="OwnerName",
                status="implemented",
                write_group="ExifIFD",
                reason="OwnerName is an EXIF scalar and is delegated to the TIFF EXIF writer.",
                evidence_ids=("exif.scalar.main", "exif.scalar.owner_name"),
            )
        )

    original_decision_data_classification = None
    original_decision_data_full_file_contract = None
    if original_decision_data is not None:
        original_decision_data_classification = classify_original_decision_data_write(
            original_decision_data,
            protected,
        )
        surface_status: DngProtectedSurfaceStatus = "blocked"
        surface_reason = original_decision_data_classification.reason
        surface_sources = original_decision_data_classification.evidence_ids
        if (
            file_data is not None
            and original_decision_data_classification.status == "blocked"
            and original_decision_data_classification.value_status == "ok"
        ):
            original_decision_data_full_file_contract = (
                build_original_decision_data_full_file_install_contract(
                    file_data=file_data,
                    new_value=original_decision_data,
                    protected=protected,
                )
            )
            surface_sources = original_decision_data_full_file_contract.evidence_ids
            if (
                original_decision_data_full_file_contract.source_backed_coordinates_discovered
                and original_decision_data_full_file_contract.remaining_blocker is None
            ):
                surface_status = "implemented"
                surface_reason = (
                    "OriginalDecisionData can be installed through the source-backed "
                    "Adobe DNGPrivateData MakN offset-pair runtime."
                )
            else:
                surface_reason = (
                    original_decision_data_full_file_contract.remaining_blocker
                    or original_decision_data_classification.reason
                )
        surfaces.append(
            DngProtectedWriteSurface(
                tag_name="OriginalDecisionData",
                status=surface_status,
                write_group="MakerNotes",
                reason=surface_reason,
                evidence_ids=surface_sources,
            )
        )

    if not surfaces:
        raise ValueError("DNG protected write plan requires at least one requested tag.")

    return DngProtectedWritePlan(
        surfaces=tuple(surfaces),
        owner_name_exif_scalar_plan=owner_name_plan,
        original_decision_data_classification=original_decision_data_classification,
        original_decision_data_full_file_contract=original_decision_data_full_file_contract,
        safety_gates=(
            "do_not_install_dng_private_data_without_outer_tiff_container_rewrite",
            "owner_name_uses_existing_tiff_exif_scalar_writer",
            "original_decision_data_requires_protected_1",
            "original_decision_data_value_must_match_canon_read_odd_layout",
            "original_decision_data_private_data_rewrap_consumes_offset_pair_contract",
            "original_decision_data_full_file_runtime_requires_source_backed_coordinates",
        ),
    )
