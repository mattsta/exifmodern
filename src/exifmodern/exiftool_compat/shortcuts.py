"""Source-backed Shortcuts.pm compatibility planning.

This module models a small, non-mutating slice of ExifTool shortcut handling. It
expands selected built-in shortcut aliases, preserves source-defined group
prefixes, applies caller group prefixes only to unqualified targets, and blocks
unsupported mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type ShortcutPlanStatus = Literal["planned", "blocked"]
type ShortcutEvidenceId = str
type ShortcutResponsibilityKind = Literal[
    "expand_builtin_shortcut",
    "route_caller_group_prefix",
    "preserve_source_group_prefix",
    "block_unknown_shortcut",
    "block_rewrite",
    "gate_output_emission",
]
type ShortcutBlockerCode = Literal["unknown_shortcut"]
type ShortcutRewriteBlockerCode = Literal["shortcut_rewrite_not_ported"]
type ShortcutEmissionGateCode = Literal[
    "output_emission_requires_explicit_opt_in",
    "blocked_shortcut_expansion",
    "shortcut_rewrite_not_ported",
]

SHORTCUT_MAIN_SOURCE = "exiftool_compat.shortcuts.main"
SHORTCUT_USER_DEFINED_SOURCE = "exiftool_compat.shortcuts.user_defined"
SHORTCUT_GROUP_ROUTING_SOURCE = "exiftool_compat.shortcuts.group_routing"

SHORTCUT_COMPAT_SOURCES = (
    SHORTCUT_MAIN_SOURCE,
    SHORTCUT_USER_DEFINED_SOURCE,
    SHORTCUT_GROUP_ROUTING_SOURCE,
)

SELECTED_SHORTCUT_ALIASES: dict[str, tuple[str, ...]] = {
    "AllDates": (
        "DateTimeOriginal",
        "CreateDate",
        "ModifyDate",
    ),
    "Common": (
        "FileName",
        "FileSize",
        "Model",
        "DateTimeOriginal",
        "ImageSize",
        "Quality",
        "FocalLength",
        "ShutterSpeed",
        "Aperture",
        "ISO",
        "WhiteBalance",
        "Flash",
    ),
    "Unsafe": (
        "IFD0:YCbCrPositioning",
        "IFD0:YCbCrCoefficients",
        "IFD0:TransferFunction",
        "ExifIFD:ComponentsConfiguration",
        "ExifIFD:CompressedBitsPerPixel",
        "InteropIFD:InteropIndex",
        "InteropIFD:InteropVersion",
        "InteropIFD:RelatedImageWidth",
        "InteropIFD:RelatedImageHeight",
    ),
    "ColorSpaceTags": (
        "ExifIFD:ColorSpace",
        "ExifIFD:Gamma",
        "InteropIFD:InteropIndex",
        "ICC_Profile",
    ),
    "CommonIFD0": (
        "IFD0:ImageDescription",
        "IFD0:Make",
        "IFD0:Model",
        "IFD0:Software",
        "IFD0:ModifyDate",
        "IFD0:Artist",
        "IFD0:Copyright",
        "IFD0:Rating",
        "IFD0:RatingPercent",
        "IFD0:DNGLensInfo",
        "IFD0:PanasonicTitle",
        "IFD0:PanasonicTitle2",
        "IFD0:XPTitle",
        "IFD0:XPComment",
        "IFD0:XPAuthor",
        "IFD0:XPKeywords",
        "IFD0:XPSubject",
    ),
    "LargeTags": (
        "CanonVRD",
        "DLOData",
        "EXIF",
        "ICC_Profile",
        "IDCPreviewImage",
        "ImageData",
        "IPTC",
        "JpgFromRaw",
        "OriginalRawImage",
        "OtherImage",
        "PreviewImage",
        "ThumbnailImage",
        "TIFFPreview",
        "XML",
        "XMP",
        "ZoomedPreviewImage",
    ),
    "ls-l": (
        "FilePermissions",
        "FileHardLinks",
        "FileUserID",
        "FileGroupID",
        "FileSize#",
        "FileModifyDate",
        "FileName",
    ),
    "ImageDataMD5": ("ImageDataHash",),
}


@dataclass(frozen=True)
class ShortcutRequest:
    raw_name: str
    caller_group_prefix: str | None
    shortcut_name: str
    family_boundary_note: str


@dataclass(frozen=True)
class ShortcutExpandedTarget:
    shortcut_name: str
    target_name: str
    resolved_name: str
    source_group_prefix: str | None
    caller_group_prefix: str | None
    caller_group_applied: bool
    source_group_takes_precedence: bool


@dataclass(frozen=True)
class ShortcutExpansion:
    request: ShortcutRequest
    targets: tuple[ShortcutExpandedTarget, ...]
    evidence_ids: tuple[ShortcutEvidenceId, ...]


@dataclass(frozen=True)
class ShortcutBlocker:
    code: ShortcutBlockerCode
    shortcut_name: str
    reason: str
    evidence_ids: tuple[ShortcutEvidenceId, ...]


@dataclass(frozen=True)
class ShortcutRewriteRequest:
    requested_names: tuple[str, ...]
    reason: str = "Shortcut rewrite support is not part of this compatibility slice."


@dataclass(frozen=True)
class ShortcutRewriteBlocker:
    code: ShortcutRewriteBlockerCode
    reason: str
    evidence_ids: tuple[ShortcutEvidenceId, ...]


@dataclass(frozen=True)
class ShortcutEmissionGate:
    code: ShortcutEmissionGateCode
    reason: str
    evidence_ids: tuple[ShortcutEvidenceId, ...]


@dataclass(frozen=True)
class ShortcutResponsibility:
    kind: ShortcutResponsibilityKind
    detail: str
    evidence_ids: tuple[ShortcutEvidenceId, ...]


@dataclass(frozen=True)
class ShortcutsCompatibilityPlan:
    schema_version: int
    status: ShortcutPlanStatus
    expansions: tuple[ShortcutExpansion, ...]
    blockers: tuple[ShortcutBlocker, ...]
    rewrite_blockers: tuple[ShortcutRewriteBlocker, ...]
    output_emission_gates: tuple[ShortcutEmissionGate, ...]
    responsibilities: tuple[ShortcutResponsibility, ...]
    selected_aliases: tuple[str, ...]
    emitted_tag_names: tuple[str, ...] | None
    evidence_ids: tuple[ShortcutEvidenceId, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit_tag_names(self) -> tuple[str, ...]:
        if self.emitted_tag_names is None:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Shortcut output emission is gated: {gate_codes}")
        return self.emitted_tag_names


def build_shortcuts_compatibility_plan(
    shortcut_names: tuple[str, ...],
    *,
    rewrite_request: ShortcutRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> ShortcutsCompatibilityPlan:
    expansions: list[ShortcutExpansion] = []
    blockers: list[ShortcutBlocker] = []
    for raw_name in shortcut_names:
        request = shortcut_request(raw_name)
        target_names = SELECTED_SHORTCUT_ALIASES.get(request.shortcut_name)
        if target_names is None:
            blockers.append(unknown_shortcut_blocker(request.shortcut_name))
            continue
        expansions.append(
            ShortcutExpansion(
                request=request,
                targets=tuple(
                    expanded_target(request, target_name) for target_name in target_names
                ),
                evidence_ids=(SHORTCUT_MAIN_SOURCE, SHORTCUT_GROUP_ROUTING_SOURCE),
            )
        )

    rewrite_blockers = build_rewrite_blockers(rewrite_request)
    output_emission_gates = build_output_emission_gates(
        blockers,
        rewrite_blockers,
        allow_output_emission,
    )
    status: ShortcutPlanStatus = "blocked" if blockers or rewrite_blockers else "planned"
    emitted_tag_names = (
        tuple(target.resolved_name for expansion in expansions for target in expansion.targets)
        if status == "planned" and not output_emission_gates
        else None
    )
    return ShortcutsCompatibilityPlan(
        schema_version=1,
        status=status,
        expansions=tuple(expansions),
        blockers=tuple(blockers),
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=output_emission_gates,
        responsibilities=shortcut_responsibilities(),
        selected_aliases=tuple(SELECTED_SHORTCUT_ALIASES),
        emitted_tag_names=emitted_tag_names,
        evidence_ids=SHORTCUT_COMPAT_SOURCES,
    )


def shortcut_request(raw_name: str) -> ShortcutRequest:
    caller_group_prefix: str | None = None
    shortcut_name = raw_name
    if ":" in raw_name:
        caller_group_prefix, shortcut_name = raw_name.rsplit(":", 1)
    return ShortcutRequest(
        raw_name=raw_name,
        caller_group_prefix=caller_group_prefix,
        shortcut_name=shortcut_name,
        family_boundary_note=(
            "Family/group syntax is preserved as caller prefix text; this slice does "
            "not resolve ExifTool group-family numbers."
        ),
    )


def expanded_target(
    request: ShortcutRequest,
    target_name: str,
) -> ShortcutExpandedTarget:
    source_group_prefix = source_group_prefix_for(target_name)
    caller_group_applied = request.caller_group_prefix is not None and source_group_prefix is None
    resolved_name = (
        f"{request.caller_group_prefix}:{target_name}" if caller_group_applied else target_name
    )
    return ShortcutExpandedTarget(
        shortcut_name=request.shortcut_name,
        target_name=target_name,
        resolved_name=resolved_name,
        source_group_prefix=source_group_prefix,
        caller_group_prefix=request.caller_group_prefix,
        caller_group_applied=caller_group_applied,
        source_group_takes_precedence=(
            request.caller_group_prefix is not None and source_group_prefix is not None
        ),
    )


def source_group_prefix_for(target_name: str) -> str | None:
    if ":" not in target_name:
        return None
    return target_name.split(":", 1)[0]


def unknown_shortcut_blocker(shortcut_name: str) -> ShortcutBlocker:
    return ShortcutBlocker(
        code="unknown_shortcut",
        shortcut_name=shortcut_name,
        reason=(f"{shortcut_name!r} is not in the selected source-backed Shortcuts.pm table."),
        evidence_ids=(SHORTCUT_MAIN_SOURCE, SHORTCUT_USER_DEFINED_SOURCE),
    )


def build_rewrite_blockers(
    rewrite_request: ShortcutRewriteRequest | None,
) -> tuple[ShortcutRewriteBlocker, ...]:
    if rewrite_request is None or not rewrite_request.requested_names:
        return ()
    return (
        ShortcutRewriteBlocker(
            code="shortcut_rewrite_not_ported",
            reason=(
                "Shortcuts.pm defines command-line tag expansion, not a byte mutation "
                f"engine for {', '.join(rewrite_request.requested_names)}."
            ),
            evidence_ids=(SHORTCUT_MAIN_SOURCE,),
        ),
    )


def build_output_emission_gates(
    blockers: list[ShortcutBlocker],
    rewrite_blockers: tuple[ShortcutRewriteBlocker, ...],
    allow_output_emission: bool,
) -> tuple[ShortcutEmissionGate, ...]:
    gates: list[ShortcutEmissionGate] = []
    if blockers:
        gates.append(
            ShortcutEmissionGate(
                code="blocked_shortcut_expansion",
                reason="At least one requested shortcut could not be expanded.",
                evidence_ids=tuple(
                    source for blocker in blockers for source in blocker.evidence_ids
                ),
            )
        )
    for blocker in rewrite_blockers:
        gates.append(
            ShortcutEmissionGate(
                code="shortcut_rewrite_not_ported",
                reason=blocker.reason,
                evidence_ids=blocker.evidence_ids,
            )
        )
    if not allow_output_emission:
        gates.append(
            ShortcutEmissionGate(
                code="output_emission_requires_explicit_opt_in",
                reason="Shortcut compatibility plans are non-mutating by default.",
                evidence_ids=(SHORTCUT_MAIN_SOURCE,),
            )
        )
    return tuple(gates)


def shortcut_responsibilities() -> tuple[ShortcutResponsibility, ...]:
    return (
        ShortcutResponsibility(
            kind="expand_builtin_shortcut",
            detail="Expand selected built-in aliases from Shortcuts.pm into tag targets.",
            evidence_ids=(SHORTCUT_MAIN_SOURCE,),
        ),
        ShortcutResponsibility(
            kind="route_caller_group_prefix",
            detail="Apply a caller group prefix only to unqualified shortcut targets.",
            evidence_ids=(SHORTCUT_GROUP_ROUTING_SOURCE,),
        ),
        ShortcutResponsibility(
            kind="preserve_source_group_prefix",
            detail="Keep target group prefixes supplied by Shortcuts.pm ahead of caller groups.",
            evidence_ids=(SHORTCUT_GROUP_ROUTING_SOURCE,),
        ),
        ShortcutResponsibility(
            kind="block_unknown_shortcut",
            detail="Block shortcut names outside the selected source-backed alias set.",
            evidence_ids=(SHORTCUT_MAIN_SOURCE, SHORTCUT_USER_DEFINED_SOURCE),
        ),
        ShortcutResponsibility(
            kind="block_rewrite",
            detail="Block rewrite requests because this slice plans expansion only.",
            evidence_ids=(SHORTCUT_MAIN_SOURCE,),
        ),
        ShortcutResponsibility(
            kind="gate_output_emission",
            detail="Require explicit opt-in before returning expanded output names.",
            evidence_ids=(SHORTCUT_MAIN_SOURCE,),
        ),
    )


plan_shortcuts_compatibility = build_shortcuts_compatibility_plan
