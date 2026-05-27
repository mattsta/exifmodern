"""Implementation requirements for ExifTool-compatible read selectors.

This module is intentionally a planning/reporting seam, not selector expansion.
The current public selector parser can model ExifTool group-family, chained
group, all-instance, and CopyN intent, but ReadGraph provenance does not yet
carry the full group families required to execute those selectors correctly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, TypedDict

from exifmodern.public_api.models import PublicReadTagSelector

type JsonPrimitive = str | int | bool | None
type SelectorCapability = Literal[
    "family_group_matching",
    "chained_group_matching",
    "all_instance_group_matching",
    "duplicate_instance_matching",
    "group_family_rendering",
]
type SelectorImplementationStatus = Literal[
    "modeled_waiting_for_provenance",
    "requires_read_graph_extension",
    "requires_renderer_extension",
]
type SelectorImplementationPhaseName = Literal[
    "provenance_capture",
    "selector_matching",
    "duplicate_policy",
    "public_rendering",
    "parity_validation",
]
type SelectorRuntimeSurface = Literal[
    "read_graph_tag_provenance",
    "public_selector_parser",
    "public_selector_expansion",
    "public_cli_group_rendering",
    "public_api_read_result_rendering",
]
type SelectorValidationTarget = Literal[
    "family_0_1_2_selector_matching",
    "colon_chained_group_matching",
    "all_instance_duplicate_expansion",
    "copy_n_instance_matching",
    "group_family_cli_rendering",
    "oracle_selector_parity_cases",
]
type RequiredProvenanceField = Literal[
    "family_0_group",
    "family_1_group",
    "family_2_group",
    "family_4_instance_group",
    "all_family_group_names",
    "duplicate_instance_ordinal",
    "group_render_family_chain",
]


class ExifToolSourceAnchorJson(TypedDict):
    path: str
    start_line: int
    end_line: int
    behavior: str


class SelectorImplementationPhaseJson(TypedDict):
    name: SelectorImplementationPhaseName
    summary: str
    done_when: str


class SelectorProvenanceRequirementJson(TypedDict):
    capability: SelectorCapability
    status: SelectorImplementationStatus
    required_fields: list[RequiredProvenanceField]
    owned_runtime_surfaces: list[SelectorRuntimeSurface]
    validation_targets: list[SelectorValidationTarget]
    implementation_phases: list[SelectorImplementationPhaseJson]
    source_anchors: list[ExifToolSourceAnchorJson]
    implementation_task: str
    blocker: str


class SelectorProvenancePlanReportJson(TypedDict):
    status: str
    requirements: list[SelectorProvenanceRequirementJson]
    blocked_fields: list[RequiredProvenanceField]


@dataclass(frozen=True)
class ExifToolSourceAnchor:
    path: str
    start_line: int
    end_line: int
    behavior: str

    def to_json_dict(self) -> ExifToolSourceAnchorJson:
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "behavior": self.behavior,
        }


@dataclass(frozen=True)
class SelectorImplementationPhase:
    name: SelectorImplementationPhaseName
    summary: str
    done_when: str

    def to_json_dict(self) -> SelectorImplementationPhaseJson:
        return {
            "name": self.name,
            "summary": self.summary,
            "done_when": self.done_when,
        }


@dataclass(frozen=True)
class SelectorProvenanceRequirement:
    capability: SelectorCapability
    status: SelectorImplementationStatus
    required_fields: tuple[RequiredProvenanceField, ...]
    owned_runtime_surfaces: tuple[SelectorRuntimeSurface, ...]
    validation_targets: tuple[SelectorValidationTarget, ...]
    implementation_phases: tuple[SelectorImplementationPhase, ...]
    source_anchors: tuple[ExifToolSourceAnchor, ...]
    implementation_task: str
    blocker: str

    def to_json_dict(self) -> SelectorProvenanceRequirementJson:
        return {
            "capability": self.capability,
            "status": self.status,
            "required_fields": list(self.required_fields),
            "owned_runtime_surfaces": list(self.owned_runtime_surfaces),
            "validation_targets": list(self.validation_targets),
            "implementation_phases": [phase.to_json_dict() for phase in self.implementation_phases],
            "source_anchors": [anchor.to_json_dict() for anchor in self.source_anchors],
            "implementation_task": self.implementation_task,
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class SelectorProvenancePlanReport:
    requirements: tuple[SelectorProvenanceRequirement, ...]

    @property
    def blocked_fields(self) -> tuple[RequiredProvenanceField, ...]:
        fields: list[RequiredProvenanceField] = []
        for requirement in self.requirements:
            for field in requirement.required_fields:
                if field not in fields:
                    fields.append(field)
        return tuple(fields)

    def to_json_dict(self) -> SelectorProvenancePlanReportJson:
        return {
            "status": "actionable_plan_waiting_for_runtime_provenance",
            "requirements": [requirement.to_json_dict() for requirement in self.requirements],
            "blocked_fields": list(self.blocked_fields),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2, sort_keys=True)


TAG_SPEC_ANCHOR = ExifToolSourceAnchor(
    path="../exiftool/lib/Image/ExifTool.pod",
    start_line=250,
    end_line=260,
    behavior=(
        "Tag specs accept colon-separated groups, optional leading family "
        "numbers, tag-name wildcards, literal GROUP:* selection, special "
        "* group all-instance selection, and multiple group selectors."
    ),
)
GROUP_MATCHES_ANCHOR = ExifToolSourceAnchor(
    path="../exiftool/lib/Image/ExifTool.pm",
    start_line=5208,
    end_line=5250,
    behavior=(
        "GroupMatches splits chained group specs, records optional family "
        "numbers, normalizes Copy0 to the primary instance, retrieves all "
        "groups with GetGroup(tag, -1), and matches each requested group."
    ),
)
GROUP_FAMILY_ANCHOR = ExifToolSourceAnchor(
    path="../exiftool/lib/Image/ExifTool.pod",
    start_line=2322,
    end_line=2366,
    behavior=(
        "Group families 0, 1, 2, and 4 define information type, specific "
        "location, category, and duplicate instance names such as Copy1."
    ),
)
GROUP_RENDER_ANCHOR = ExifToolSourceAnchor(
    path="../exiftool/exiftool",
    start_line=5917,
    end_line=5929,
    behavior=(
        "-G/-g output accepts family numbers, multiple family chains, and "
        "simplifies rendered group chains unless the family list starts with "
        "a colon."
    ),
)

CAPTURE_FAMILY_PROVENANCE_PHASE = SelectorImplementationPhase(
    name="provenance_capture",
    summary=(
        "Capture ExifTool family 0, 1, and 2 group names beside each native "
        "ReadTag without changing current rendered names."
    ),
    done_when=(
        "ReadGraph records can distinguish information type, concrete storage "
        "location, and category groups for selector matching."
    ),
)
MATCH_FAMILY_SELECTOR_PHASE = SelectorImplementationPhase(
    name="selector_matching",
    summary=(
        "Route leading selector family numbers through captured family fields "
        "instead of the current single group label."
    ),
    done_when=(
        "Selectors such as 0EXIF:*, 1IFD0:*, and 2Image:* match only tags "
        "whose corresponding ExifTool family field matches."
    ),
)
CAPTURE_ALL_GROUPS_PHASE = SelectorImplementationPhase(
    name="provenance_capture",
    summary=(
        "Preserve the complete GetGroup(tag, -1) group list needed for "
        "colon-chained selector matching."
    ),
    done_when=(
        "Each ReadTag exposes the full ordered group list used by ExifTool "
        "GroupMatches for chained group specs."
    ),
)
MATCH_CHAINED_SELECTOR_PHASE = SelectorImplementationPhase(
    name="selector_matching",
    summary=(
        "Match each colon-separated group selector component against explicit "
        "family fields or against the full group list when unqualified."
    ),
    done_when=(
        "Selectors such as EXIF:Time:* reject tags missing any requested group "
        "component and accept tags matching all requested components."
    ),
)
CAPTURE_DUPLICATE_PHASE = SelectorImplementationPhase(
    name="duplicate_policy",
    summary=(
        "Record primary Copy0 and additional CopyN instance identity before "
        "duplicate collapse removes ExifTool-visible instance provenance."
    ),
    done_when=(
        "Read results retain deterministic duplicate ordinals and family-4 "
        "instance names for primary and repeated tags."
    ),
)
MATCH_DUPLICATE_PHASE = SelectorImplementationPhase(
    name="selector_matching",
    summary=(
        "Use Copy0/CopyN identity for family-4 selector matching and use the "
        "all-instance group wildcard to opt into duplicate expansion."
    ),
    done_when=(
        "Selectors such as Copy2:WhiteBalance and *:WhiteBalance use captured "
        "duplicate identity instead of current diagnostic-only handling."
    ),
)
RENDER_GROUP_FAMILY_PHASE = SelectorImplementationPhase(
    name="public_rendering",
    summary=(
        "Render requested -G/-g family chains from captured provenance while "
        "preserving ExifTool chain simplification semantics."
    ),
    done_when=(
        "Public CLI/API can render selected group families without relying on "
        "the current single provenance.group fallback."
    ),
)
SELECTOR_PARITY_PHASE = SelectorImplementationPhase(
    name="parity_validation",
    summary=(
        "Add oracle-backed selector parity cases after provenance capture and "
        "matching surfaces are implemented."
    ),
    done_when=(
        "Focused parity tests cover family selectors, chained selectors, "
        "all-instance wildcard selectors, CopyN selectors, and -G/-g output."
    ),
)


def build_selector_provenance_plan_report() -> SelectorProvenancePlanReport:
    return SelectorProvenancePlanReport(
        requirements=(
            SelectorProvenanceRequirement(
                capability="family_group_matching",
                status="requires_read_graph_extension",
                required_fields=("family_0_group", "family_1_group", "family_2_group"),
                owned_runtime_surfaces=(
                    "read_graph_tag_provenance",
                    "public_selector_expansion",
                ),
                validation_targets=(
                    "family_0_1_2_selector_matching",
                    "oracle_selector_parity_cases",
                ),
                implementation_phases=(
                    CAPTURE_FAMILY_PROVENANCE_PHASE,
                    MATCH_FAMILY_SELECTOR_PHASE,
                    SELECTOR_PARITY_PHASE,
                ),
                source_anchors=(TAG_SPEC_ANCHOR, GROUP_MATCHES_ANCHOR, GROUP_FAMILY_ANCHOR),
                implementation_task=(
                    "Extend TagProvenance or an adjacent immutable provenance record "
                    "so each ReadTag carries ExifTool family 0, 1, and 2 groups "
                    "separately, then route selector family prefixes through those "
                    "fields instead of the current single provenance.group string."
                ),
                blocker=(
                    "Current ReadGraph tags expose only TagProvenance.group, which "
                    "is effectively one family-1-like label in existing adapters."
                ),
            ),
            SelectorProvenanceRequirement(
                capability="chained_group_matching",
                status="requires_read_graph_extension",
                required_fields=("all_family_group_names",),
                owned_runtime_surfaces=(
                    "read_graph_tag_provenance",
                    "public_selector_expansion",
                ),
                validation_targets=(
                    "colon_chained_group_matching",
                    "oracle_selector_parity_cases",
                ),
                implementation_phases=(
                    CAPTURE_ALL_GROUPS_PHASE,
                    MATCH_CHAINED_SELECTOR_PHASE,
                    SELECTOR_PARITY_PHASE,
                ),
                source_anchors=(TAG_SPEC_ANCHOR, GROUP_MATCHES_ANCHOR),
                implementation_task=(
                    "Represent the complete GetGroup(tag, -1) family list for each "
                    "ReadTag and match each colon-separated selector component "
                    "against either the requested explicit family or any available "
                    "family when no family number is supplied."
                ),
                blocker=(
                    "Current provenance has no all-family list, so an unqualified "
                    "chain such as EXIF:Time:* cannot be matched against all groups."
                ),
            ),
            SelectorProvenanceRequirement(
                capability="all_instance_group_matching",
                status="requires_read_graph_extension",
                required_fields=("family_4_instance_group", "duplicate_instance_ordinal"),
                owned_runtime_surfaces=(
                    "read_graph_tag_provenance",
                    "public_selector_expansion",
                ),
                validation_targets=(
                    "all_instance_duplicate_expansion",
                    "oracle_selector_parity_cases",
                ),
                implementation_phases=(
                    CAPTURE_DUPLICATE_PHASE,
                    MATCH_DUPLICATE_PHASE,
                    SELECTOR_PARITY_PHASE,
                ),
                source_anchors=(TAG_SPEC_ANCHOR, GROUP_MATCHES_ANCHOR, GROUP_FAMILY_ANCHOR),
                implementation_task=(
                    "Carry duplicate instance identity for collapsed duplicate "
                    "ReadTags so *:Tag can bypass the normal duplicate suppression "
                    "behavior while preserving deterministic output names."
                ),
                blocker=(
                    "Current wildcard expansion intentionally collapses duplicate "
                    "read-graph keys and reports a diagnostic instead of preserving "
                    "ExifTool duplicate instances."
                ),
            ),
            SelectorProvenanceRequirement(
                capability="duplicate_instance_matching",
                status="requires_read_graph_extension",
                required_fields=("family_4_instance_group", "duplicate_instance_ordinal"),
                owned_runtime_surfaces=(
                    "read_graph_tag_provenance",
                    "public_selector_expansion",
                ),
                validation_targets=(
                    "copy_n_instance_matching",
                    "oracle_selector_parity_cases",
                ),
                implementation_phases=(
                    CAPTURE_DUPLICATE_PHASE,
                    MATCH_DUPLICATE_PHASE,
                    SELECTOR_PARITY_PHASE,
                ),
                source_anchors=(GROUP_MATCHES_ANCHOR, GROUP_FAMILY_ANCHOR),
                implementation_task=(
                    "Model the primary instance as Copy0 for selector matching and "
                    "additional instances as Copy1, Copy2, and so on, matching "
                    "ExifTool family-4 semantics."
                ),
                blocker=(
                    "ReadGraph currently has no family-4 provenance for primary or "
                    "additional instances."
                ),
            ),
            SelectorProvenanceRequirement(
                capability="group_family_rendering",
                status="requires_renderer_extension",
                required_fields=("group_render_family_chain",),
                owned_runtime_surfaces=(
                    "public_cli_group_rendering",
                    "public_api_read_result_rendering",
                ),
                validation_targets=(
                    "group_family_cli_rendering",
                    "oracle_selector_parity_cases",
                ),
                implementation_phases=(
                    RENDER_GROUP_FAMILY_PHASE,
                    SELECTOR_PARITY_PHASE,
                ),
                source_anchors=(GROUP_RENDER_ANCHOR, GROUP_FAMILY_ANCHOR),
                implementation_task=(
                    "Teach public rendering to request explicit family chains, "
                    "preserve or simplify group-chain rendering according to "
                    "ExifTool -G/-g family syntax, and use the same provenance "
                    "fields as selector expansion."
                ),
                blocker=(
                    "Public rendering can only render the existing provenance.group "
                    "label for currently representable family-1 output."
                ),
            ),
        )
    )


def required_fields_for_selector(
    selector: PublicReadTagSelector,
) -> tuple[RequiredProvenanceField, ...]:
    report = build_selector_provenance_plan_report()
    fields: list[RequiredProvenanceField] = []
    capabilities: list[SelectorCapability] = []
    if selector.has_family_selector:
        capabilities.append("family_group_matching")
    if selector.has_group_chain:
        capabilities.append("chained_group_matching")
    if selector.has_all_instances_group:
        capabilities.append("all_instance_group_matching")
    if selector.has_duplicate_instance_selector:
        capabilities.append("duplicate_instance_matching")
    for requirement in report.requirements:
        if requirement.capability not in capabilities:
            continue
        for field in requirement.required_fields:
            if field not in fields:
                fields.append(field)
    return tuple(fields)
