"""Source-backed MWG metadata coordination transaction plans.

ExifTool's MWG.pm defines composite coordination over EXIF, IPTC, XMP,
Photoshop digest state, and MWG XMP namespaces. This module does not model MWG
as a file container; it plans family/group responsibility, synchronization
boundaries, strict-location read handling, and rewrite gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonValue

MWG_SOURCE_PATH = "lib/Image/ExifTool/MWG.pm"

type MwgMetadataValue = str | int | tuple[str, ...]
type MwgRouteAction = Literal[
    "coordinate_mwg_composite",
    "route_source_family",
    "route_mwg_xmp_namespace",
    "preserve_existing",
    "block",
]
type MwgRouteBlockerCode = Literal[
    "unknown_mwg_composite",
    "unknown_mwg_xmp_namespace_tag",
    "unsupported_group",
]
type MwgSourceRole = Literal["desire", "write_also", "require", "digest"]
type MwgWritePolicy = Literal[
    "write_value",
    "write_existing_iptc_only",
    "write_composite_subsecond",
    "update_iptc_digest",
    "read_only_digest",
]
type MwgPlanConcern = Literal[
    "composite_coordination",
    "source_family_routing",
    "iptc_digest_synchronization",
    "strict_mwg_read_locations",
    "exif_utf8_string_default",
    "creator_string_list_bridge",
    "mwg_xmp_namespace_tables",
    "unsupported_rewrite_gates",
]
type MwgConflictGateCode = Literal[
    "iptc_digest_mismatch_requires_reconcile",
    "non_standard_location_ignored_in_strict_mode",
]
type MwgRewriteBlockerCode = Literal[
    "mwg_has_no_container_writer",
    "associated_family_writer_required",
    "raw_container_rewrite_not_in_scope",
]
type MwgEmissionGateCode = Literal[
    "unsupported_mwg_rewrite",
    "blocked_route",
    "conflict_gate_requires_resolution",
    "planner_is_non_mutating",
]
type MwgXmpNamespaceResponsibility = Literal[
    "region_info",
    "hierarchical_keywords",
    "collections",
]

MWG_COMPOSITE_SOURCE = "mwg.composite"
MWG_KEYWORDS_SOURCE = "mwg.keywords"
MWG_DESCRIPTION_SOURCE = "mwg.description"
MWG_DATE_TIME_SOURCE = "mwg.date.time"
MWG_MODIFY_RATING_ORIENTATION_SOURCE = "mwg.modify.rating.orientation"
MWG_AUTHOR_SOURCE = "mwg.author"
MWG_LOCATION_SOURCE = "mwg.location"
MWG_XMP_NAMESPACE_SOURCE = "mwg.xmp.namespace"
MWG_LOAD_SOURCE = "mwg.load"
MWG_STRING_LIST_SOURCE = "mwg.string.list"
MWG_RECONCILE_SOURCE = "mwg.reconcile"
MWG_TRUNCATED_IPTC_SOURCE = "mwg.truncated.iptc"
MWG_TRANSACTION_SOURCES = (
    MWG_COMPOSITE_SOURCE,
    MWG_KEYWORDS_SOURCE,
    MWG_DESCRIPTION_SOURCE,
    MWG_DATE_TIME_SOURCE,
    MWG_MODIFY_RATING_ORIENTATION_SOURCE,
    MWG_AUTHOR_SOURCE,
    MWG_LOCATION_SOURCE,
    MWG_XMP_NAMESPACE_SOURCE,
    MWG_LOAD_SOURCE,
    MWG_STRING_LIST_SOURCE,
    MWG_RECONCILE_SOURCE,
    MWG_TRUNCATED_IPTC_SOURCE,
)


@dataclass(frozen=True)
class MwgAssociatedTag:
    group_name: str
    tag_name: str
    role: MwgSourceRole
    write_policy: MwgWritePolicy
    iptc_character_limit: int | None

    @property
    def qualified_name(self) -> str:
        return f"{self.group_name}:{self.tag_name}"

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "group_name": self.group_name,
            "iptc_character_limit": self.iptc_character_limit,
            "qualified_name": self.qualified_name,
            "role": self.role,
            "tag_name": self.tag_name,
            "write_policy": self.write_policy,
        }


@dataclass(frozen=True)
class MwgCompositeDefinition:
    tag_name: str
    family2_group: str
    writable: bool
    list_value: bool
    direct_composite_write: bool
    require_tag: MwgAssociatedTag | None
    desire_tags: tuple[MwgAssociatedTag, ...]
    write_also_tags: tuple[MwgAssociatedTag, ...]
    uses_iptc_digest: bool
    read_priority: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "desire_tags": [tag.to_json() for tag in self.desire_tags],
            "direct_composite_write": self.direct_composite_write,
            "family2_group": self.family2_group,
            "list_value": self.list_value,
            "read_priority": list(self.read_priority),
            "require_tag": self.require_tag.to_json() if self.require_tag else None,
            "tag_name": self.tag_name,
            "uses_iptc_digest": self.uses_iptc_digest,
            "writable": self.writable,
            "write_also_tags": [tag.to_json() for tag in self.write_also_tags],
        }


@dataclass(frozen=True)
class MwgWriteRequest:
    group_name: str
    tag_name: str
    value: MwgMetadataValue


@dataclass(frozen=True)
class MwgExistingField:
    group_name: str
    tag_name: str
    value: MwgMetadataValue
    standard_location: bool = True


@dataclass(frozen=True)
class MwgExistingFieldPlan:
    group_name: str
    tag_name: str
    value: MwgMetadataValue
    standard_location: bool
    route_action: MwgRouteAction
    strict_mode_warning: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "group_name": self.group_name,
            "route_action": self.route_action,
            "standard_location": self.standard_location,
            "strict_mode_warning": self.strict_mode_warning,
            "tag_name": self.tag_name,
            "value": metadata_value_to_json(self.value),
        }


@dataclass(frozen=True)
class MwgRoutePlan:
    action: MwgRouteAction
    group_name: str
    tag_name: str
    requested_value: MwgMetadataValue | None
    composite_tag_name: str | None
    blocker_code: MwgRouteBlockerCode | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "action": self.action,
            "blocker_code": self.blocker_code,
            "composite_tag_name": self.composite_tag_name,
            "group_name": self.group_name,
            "reason": self.reason,
            "requested_value": metadata_value_to_json(self.requested_value),
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class MwgSynchronizationBoundary:
    tag_name: str
    source_groups: tuple[str, ...]
    digest_protected: bool
    iptc_edit_group_required: bool
    read_conflict_policy: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "digest_protected": self.digest_protected,
            "iptc_edit_group_required": self.iptc_edit_group_required,
            "read_conflict_policy": self.read_conflict_policy,
            "source_groups": list(self.source_groups),
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class MwgXmpNamespacePlan:
    group_name: str
    namespace: str
    responsibility: MwgXmpNamespaceResponsibility
    independent_of_composite_load: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "group_name": self.group_name,
            "independent_of_composite_load": self.independent_of_composite_load,
            "namespace": self.namespace,
            "responsibility": self.responsibility,
        }


@dataclass(frozen=True)
class MwgConflictGate:
    code: MwgConflictGateCode
    tag_name: str | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "reason": self.reason,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class MwgRewriteBlocker:
    code: MwgRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MwgEmissionGate:
    code: MwgEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MwgResponsibilityPlan:
    concern: MwgPlanConcern
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "concern": self.concern,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MwgMetadataTransactionPlan:
    composite_group: str
    strict_mode_default: bool
    exif_string_encoding_default: str
    composite_definitions: tuple[MwgCompositeDefinition, ...]
    xmp_namespace_plans: tuple[MwgXmpNamespacePlan, ...]
    existing_fields: tuple[MwgExistingFieldPlan, ...]
    routes: tuple[MwgRoutePlan, ...]
    synchronization_boundaries: tuple[MwgSynchronizationBoundary, ...]
    conflict_gates: tuple[MwgConflictGate, ...]
    rewrite_blockers: tuple[MwgRewriteBlocker, ...]
    output_emission_gates: tuple[MwgEmissionGate, ...]
    responsibilities: tuple[MwgResponsibilityPlan, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return False

    def emit(self) -> bytes:
        raise ValueError("MWG metadata transaction output is gated")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "composite_definitions": [
                definition.to_json() for definition in self.composite_definitions
            ],
            "composite_group": self.composite_group,
            "conflict_gates": [gate.to_json() for gate in self.conflict_gates],
            "existing_fields": [field.to_json() for field in self.existing_fields],
            "exif_string_encoding_default": self.exif_string_encoding_default,
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "rewrite_blockers": [blocker.to_json() for blocker in self.rewrite_blockers],
            "routes": [route.to_json() for route in self.routes],
            "strict_mode_default": self.strict_mode_default,
            "synchronization_boundaries": [
                boundary.to_json() for boundary in self.synchronization_boundaries
            ],
            "xmp_namespace_plans": [plan.to_json() for plan in self.xmp_namespace_plans],
        }


def build_mwg_metadata_transaction_plan(
    existing_fields: tuple[MwgExistingField, ...] = (),
    write_requests: tuple[MwgWriteRequest, ...] = (),
) -> MwgMetadataTransactionPlan:
    routes = tuple(route_write_request(request) for request in write_requests)
    planned_existing_fields = tuple(plan_existing_field(field) for field in existing_fields)
    conflict_gates = build_conflict_gates(existing_fields)
    output_emission_gates = build_output_emission_gates(routes, conflict_gates)

    return MwgMetadataTransactionPlan(
        composite_group="MWG",
        strict_mode_default=True,
        exif_string_encoding_default="UTF8",
        composite_definitions=COMPOSITE_DEFINITIONS,
        xmp_namespace_plans=XMP_NAMESPACE_PLANS,
        existing_fields=planned_existing_fields,
        routes=routes,
        synchronization_boundaries=SYNCHRONIZATION_BOUNDARIES,
        conflict_gates=conflict_gates,
        rewrite_blockers=REWRITE_BLOCKERS,
        output_emission_gates=output_emission_gates,
        responsibilities=RESPONSIBILITIES,
        evidence_ids=MWG_TRANSACTION_SOURCES,
    )


def route_write_request(request: MwgWriteRequest) -> MwgRoutePlan:
    if request.group_name == "MWG":
        definition = COMPOSITE_LOOKUP.get(request.tag_name)
        if definition:
            return MwgRoutePlan(
                action="coordinate_mwg_composite",
                group_name=request.group_name,
                tag_name=request.tag_name,
                requested_value=request.value,
                composite_tag_name=definition.tag_name,
                blocker_code=None,
                reason="MWG Composite requests coordinate associated source-family writes.",
                evidence_ids=definition.evidence_ids,
            )
        return block_route(
            request,
            "unknown_mwg_composite",
            "MWG.pm declares a fixed Composite tag table; this tag is not present.",
            (MWG_COMPOSITE_SOURCE,),
        )

    namespace_plan = XMP_NAMESPACE_LOOKUP.get(request.group_name)
    if namespace_plan:
        return MwgRoutePlan(
            action="route_mwg_xmp_namespace",
            group_name=request.group_name,
            tag_name=request.tag_name,
            requested_value=request.value,
            composite_tag_name=None,
            blocker_code=None,
            reason="MWG XMP namespace tables are handled as XMP tags, not Composite tags.",
            evidence_ids=namespace_plan.evidence_ids,
        )

    composite_tag_name = SOURCE_TAG_LOOKUP.get(qualified_name(request.group_name, request.tag_name))
    if composite_tag_name:
        return MwgRoutePlan(
            action="route_source_family",
            group_name=request.group_name,
            tag_name=request.tag_name,
            requested_value=request.value,
            composite_tag_name=composite_tag_name,
            blocker_code=None,
            reason="The request targets an associated tag listed by an MWG Composite.",
            evidence_ids=COMPOSITE_LOOKUP[composite_tag_name].evidence_ids,
        )

    if request.group_name.startswith("XMP-mwg-"):
        return block_route(
            request,
            "unknown_mwg_xmp_namespace_tag",
            "Only the MWG XMP namespaces declared by MWG.pm are routed here.",
            (MWG_XMP_NAMESPACE_SOURCE,),
        )

    return block_route(
        request,
        "unsupported_group",
        "MWG coordination only covers MWG composites and declared associated source groups.",
        (MWG_COMPOSITE_SOURCE,),
    )


def block_route(
    request: MwgWriteRequest,
    blocker_code: MwgRouteBlockerCode,
    reason: str,
    sources: tuple[str, ...],
) -> MwgRoutePlan:
    return MwgRoutePlan(
        action="block",
        group_name=request.group_name,
        tag_name=request.tag_name,
        requested_value=request.value,
        composite_tag_name=None,
        blocker_code=blocker_code,
        reason=reason,
        evidence_ids=sources,
    )


def plan_existing_field(field: MwgExistingField) -> MwgExistingFieldPlan:
    if not field.standard_location and field.group_name in {"EXIF", "IPTC", "XMP"}:
        return MwgExistingFieldPlan(
            group_name=field.group_name,
            tag_name=field.tag_name,
            value=field.value,
            standard_location=field.standard_location,
            route_action="preserve_existing",
            strict_mode_warning=True,
            evidence_ids=(MWG_COMPOSITE_SOURCE, MWG_LOAD_SOURCE),
        )

    request = MwgWriteRequest(field.group_name, field.tag_name, field.value)
    route = route_write_request(request)
    return MwgExistingFieldPlan(
        group_name=field.group_name,
        tag_name=field.tag_name,
        value=field.value,
        standard_location=field.standard_location,
        route_action=route.action if route.action != "block" else "preserve_existing",
        strict_mode_warning=False,
        evidence_ids=route.evidence_ids,
    )


def build_conflict_gates(
    existing_fields: tuple[MwgExistingField, ...],
) -> tuple[MwgConflictGate, ...]:
    gates: list[MwgConflictGate] = []
    current_digest = first_value(existing_fields, "CurrentIPTCDigest")
    stored_digest = first_value(existing_fields, "IPTCDigest")
    digest_mismatch = (
        isinstance(current_digest, str)
        and isinstance(stored_digest, str)
        and current_digest != stored_digest
    )

    if digest_mismatch:
        for definition in COMPOSITE_DEFINITIONS:
            if definition.uses_iptc_digest and has_multiple_source_values(
                existing_fields,
                definition,
            ):
                gates.append(
                    MwgConflictGate(
                        code="iptc_digest_mismatch_requires_reconcile",
                        tag_name=definition.tag_name,
                        reason=(
                            "The associated IPTC and XMP/EXIF values coexist while "
                            "CurrentIPTCDigest differs from IPTCDigest."
                        ),
                        evidence_ids=(definition.evidence_ids[0], MWG_RECONCILE_SOURCE),
                    )
                )

    for field in existing_fields:
        if not field.standard_location and field.group_name in {"EXIF", "IPTC", "XMP"}:
            gates.append(
                MwgConflictGate(
                    code="non_standard_location_ignored_in_strict_mode",
                    tag_name=None,
                    reason=(
                        "Strict MWG mode ignores EXIF, IPTC, and XMP in non-standard "
                        "locations during reads and reports a warning."
                    ),
                    evidence_ids=(MWG_COMPOSITE_SOURCE, MWG_LOAD_SOURCE),
                )
            )
    return tuple(gates)


def first_value(
    existing_fields: tuple[MwgExistingField, ...],
    tag_name: str,
) -> MwgMetadataValue | None:
    for field in existing_fields:
        if field.tag_name == tag_name:
            return field.value
    return None


def has_multiple_source_values(
    existing_fields: tuple[MwgExistingField, ...],
    definition: MwgCompositeDefinition,
) -> bool:
    seen_values: set[str] = set()
    source_names = {
        tag.qualified_name
        for tag in definition.desire_tags
        if tag.role != "digest" and not tag.group_name.startswith("Composite")
    }
    for field in existing_fields:
        if qualified_name(field.group_name, field.tag_name) not in source_names:
            continue
        value = metadata_value_key(field.value)
        if value:
            seen_values.add(value)
    return len(seen_values) > 1


def build_output_emission_gates(
    routes: tuple[MwgRoutePlan, ...],
    conflict_gates: tuple[MwgConflictGate, ...],
) -> tuple[MwgEmissionGate, ...]:
    gates: list[MwgEmissionGate] = [
        MwgEmissionGate(
            code="unsupported_mwg_rewrite",
            reason="This slice plans MWG coordination but does not rewrite associated families.",
            evidence_ids=(MWG_COMPOSITE_SOURCE,),
        )
    ]
    if any(route.action == "block" for route in routes):
        gates.append(
            MwgEmissionGate(
                code="blocked_route",
                reason="At least one write request does not map to an MWG source-backed route.",
                evidence_ids=(MWG_COMPOSITE_SOURCE, MWG_XMP_NAMESPACE_SOURCE),
            )
        )
    if conflict_gates:
        gates.append(
            MwgEmissionGate(
                code="conflict_gate_requires_resolution",
                reason="Synchronization or strict-location gates must be resolved before mutation.",
                evidence_ids=(MWG_COMPOSITE_SOURCE, MWG_RECONCILE_SOURCE),
            )
        )
    gates.append(
        MwgEmissionGate(
            code="planner_is_non_mutating",
            reason=(
                "MWG is a coordination layer here; byte mutation is delegated to family writers."
            ),
            evidence_ids=(MWG_COMPOSITE_SOURCE,),
        )
    )
    return tuple(gates)


def associated(
    group_name: str,
    tag_name: str,
    role: MwgSourceRole,
    write_policy: MwgWritePolicy,
    iptc_character_limit: int | None = None,
) -> MwgAssociatedTag:
    return MwgAssociatedTag(
        group_name=group_name,
        tag_name=tag_name,
        role=role,
        write_policy=write_policy,
        iptc_character_limit=iptc_character_limit,
    )


def digest_tags(count: int) -> tuple[MwgAssociatedTag, ...]:
    if count == 2:
        return (
            associated("Photoshop", "CurrentIPTCDigest", "digest", "read_only_digest"),
            associated("Photoshop", "IPTCDigest", "digest", "update_iptc_digest"),
        )
    return (
        associated("Photoshop", "CurrentIPTCDigest", "digest", "read_only_digest"),
        associated("Photoshop", "IPTCDigest", "digest", "update_iptc_digest"),
    )


COMPOSITE_DEFINITIONS = (
    MwgCompositeDefinition(
        tag_name="Keywords",
        family2_group="Image",
        writable=True,
        list_value=True,
        direct_composite_write=True,
        require_tag=None,
        desire_tags=(
            associated("IPTC", "Keywords", "desire", "write_existing_iptc_only", 64),
            associated("XMP-dc", "Subject", "desire", "write_value"),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated("IPTC", "Keywords", "write_also", "write_existing_iptc_only", 64),
            associated("XMP-dc", "Subject", "write_also", "write_value"),
        ),
        uses_iptc_digest=True,
        read_priority=("XMP-dc:Subject when IPTC digest is synchronized", "IPTC:Keywords"),
        evidence_ids=(MWG_KEYWORDS_SOURCE, MWG_RECONCILE_SOURCE, MWG_TRUNCATED_IPTC_SOURCE),
    ),
    MwgCompositeDefinition(
        tag_name="Description",
        family2_group="Image",
        writable=True,
        list_value=False,
        direct_composite_write=True,
        require_tag=None,
        desire_tags=(
            associated("EXIF", "ImageDescription", "desire", "write_value"),
            associated("IPTC", "Caption-Abstract", "desire", "write_existing_iptc_only", 2000),
            associated("XMP-dc", "Description", "desire", "write_value"),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated("EXIF", "ImageDescription", "write_also", "write_value"),
            associated("IPTC", "Caption-Abstract", "write_also", "write_existing_iptc_only", 2000),
            associated("XMP-dc", "Description", "write_also", "write_value"),
        ),
        uses_iptc_digest=True,
        read_priority=("EXIF:ImageDescription", "XMP-dc:Description", "IPTC:Caption-Abstract"),
        evidence_ids=(MWG_DESCRIPTION_SOURCE, MWG_RECONCILE_SOURCE, MWG_TRUNCATED_IPTC_SOURCE),
    ),
    MwgCompositeDefinition(
        tag_name="DateTimeOriginal",
        family2_group="Time",
        writable=True,
        list_value=False,
        direct_composite_write=True,
        require_tag=None,
        desire_tags=(
            associated(
                "Composite",
                "SubSecDateTimeOriginal",
                "desire",
                "write_composite_subsecond",
            ),
            associated("EXIF", "DateTimeOriginal", "desire", "write_value"),
            associated("IPTC", "DateCreated", "desire", "write_existing_iptc_only"),
            associated("IPTC", "TimeCreated", "desire", "write_existing_iptc_only"),
            associated("XMP-photoshop", "DateCreated", "desire", "write_value"),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated(
                "Composite",
                "SubSecDateTimeOriginal",
                "write_also",
                "write_composite_subsecond",
            ),
            associated("IPTC", "DateCreated", "write_also", "write_existing_iptc_only"),
            associated("IPTC", "TimeCreated", "write_also", "write_existing_iptc_only"),
            associated("XMP-photoshop", "DateCreated", "write_also", "write_value"),
        ),
        uses_iptc_digest=True,
        read_priority=(
            "Composite:SubSecDateTimeOriginal",
            "EXIF:DateTimeOriginal",
            "XMP-photoshop:DateCreated",
            "IPTC date/time pair",
        ),
        evidence_ids=(MWG_DATE_TIME_SOURCE, MWG_RECONCILE_SOURCE),
    ),
    MwgCompositeDefinition(
        tag_name="CreateDate",
        family2_group="Time",
        writable=True,
        list_value=False,
        direct_composite_write=True,
        require_tag=None,
        desire_tags=(
            associated("Composite", "SubSecCreateDate", "desire", "write_composite_subsecond"),
            associated("EXIF", "CreateDate", "desire", "write_value"),
            associated("IPTC", "DigitalCreationDate", "desire", "write_existing_iptc_only"),
            associated("IPTC", "DigitalCreationTime", "desire", "write_existing_iptc_only"),
            associated("XMP-xmp", "CreateDate", "desire", "write_value"),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated("Composite", "SubSecCreateDate", "write_also", "write_composite_subsecond"),
            associated("IPTC", "DigitalCreationDate", "write_also", "write_existing_iptc_only"),
            associated("IPTC", "DigitalCreationTime", "write_also", "write_existing_iptc_only"),
            associated("XMP-xmp", "CreateDate", "write_also", "write_value"),
        ),
        uses_iptc_digest=True,
        read_priority=(
            "Composite:SubSecCreateDate",
            "EXIF:CreateDate",
            "XMP-xmp:CreateDate",
            "IPTC digital creation pair",
        ),
        evidence_ids=(MWG_DATE_TIME_SOURCE, MWG_RECONCILE_SOURCE),
    ),
    MwgCompositeDefinition(
        tag_name="ModifyDate",
        family2_group="Time",
        writable=True,
        list_value=False,
        direct_composite_write=False,
        require_tag=None,
        desire_tags=(
            associated("Composite", "SubSecModifyDate", "desire", "write_composite_subsecond"),
            associated("EXIF", "ModifyDate", "desire", "write_value"),
            associated("XMP-xmp", "ModifyDate", "desire", "write_value"),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated("Composite", "SubSecModifyDate", "write_also", "write_composite_subsecond"),
            associated("XMP-xmp", "ModifyDate", "write_also", "write_value"),
        ),
        uses_iptc_digest=False,
        read_priority=("Composite:SubSecModifyDate", "EXIF:ModifyDate", "XMP-xmp:ModifyDate"),
        evidence_ids=(MWG_MODIFY_RATING_ORIENTATION_SOURCE,),
    ),
    MwgCompositeDefinition(
        tag_name="Orientation",
        family2_group="Image",
        writable=True,
        list_value=False,
        direct_composite_write=False,
        require_tag=associated("EXIF", "Orientation", "require", "write_value"),
        desire_tags=(),
        write_also_tags=(associated("EXIF", "Orientation", "write_also", "write_value"),),
        uses_iptc_digest=False,
        read_priority=("EXIF:Orientation",),
        evidence_ids=(MWG_MODIFY_RATING_ORIENTATION_SOURCE,),
    ),
    MwgCompositeDefinition(
        tag_name="Rating",
        family2_group="Image",
        writable=True,
        list_value=False,
        direct_composite_write=False,
        require_tag=associated("XMP-xmp", "Rating", "require", "write_value"),
        desire_tags=(),
        write_also_tags=(associated("XMP-xmp", "Rating", "write_also", "write_value"),),
        uses_iptc_digest=False,
        read_priority=("XMP-xmp:Rating",),
        evidence_ids=(MWG_MODIFY_RATING_ORIENTATION_SOURCE,),
    ),
    MwgCompositeDefinition(
        tag_name="Copyright",
        family2_group="Author",
        writable=True,
        list_value=False,
        direct_composite_write=True,
        require_tag=None,
        desire_tags=(
            associated("EXIF", "Copyright", "desire", "write_value"),
            associated("IPTC", "CopyrightNotice", "desire", "write_existing_iptc_only", 128),
            associated("XMP-dc", "Rights", "desire", "write_value"),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated("EXIF", "Copyright", "write_also", "write_value"),
            associated("IPTC", "CopyrightNotice", "write_also", "write_existing_iptc_only", 128),
            associated("XMP-dc", "Rights", "write_also", "write_value"),
        ),
        uses_iptc_digest=True,
        read_priority=("EXIF:Copyright", "XMP-dc:Rights", "IPTC:CopyrightNotice"),
        evidence_ids=(MWG_AUTHOR_SOURCE, MWG_RECONCILE_SOURCE, MWG_TRUNCATED_IPTC_SOURCE),
    ),
    MwgCompositeDefinition(
        tag_name="Creator",
        family2_group="Author",
        writable=True,
        list_value=True,
        direct_composite_write=True,
        require_tag=None,
        desire_tags=(
            associated("EXIF", "Artist", "desire", "write_value"),
            associated("IPTC", "By-line", "desire", "write_existing_iptc_only", 32),
            associated("XMP-dc", "Creator", "desire", "write_value"),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated("EXIF", "Artist", "write_also", "write_value"),
            associated("IPTC", "By-line", "write_also", "write_existing_iptc_only", 32),
            associated("XMP-dc", "Creator", "write_also", "write_value"),
        ),
        uses_iptc_digest=True,
        read_priority=("EXIF:Artist", "XMP-dc:Creator", "IPTC:By-line"),
        evidence_ids=(
            MWG_AUTHOR_SOURCE,
            MWG_STRING_LIST_SOURCE,
            MWG_RECONCILE_SOURCE,
            MWG_TRUNCATED_IPTC_SOURCE,
        ),
    ),
    MwgCompositeDefinition(
        tag_name="Country",
        family2_group="Location",
        writable=True,
        list_value=False,
        direct_composite_write=True,
        require_tag=None,
        desire_tags=(
            associated(
                "IPTC",
                "Country-PrimaryLocationName",
                "desire",
                "write_existing_iptc_only",
                64,
            ),
            associated("XMP-photoshop", "Country", "desire", "write_value"),
            associated(
                "XMP-iptcExt",
                "LocationShownCountryName",
                "desire",
                "write_value",
            ),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated(
                "IPTC",
                "Country-PrimaryLocationName",
                "write_also",
                "write_existing_iptc_only",
                64,
            ),
            associated("XMP-photoshop", "Country", "write_also", "write_value"),
            associated(
                "XMP-iptcExt",
                "LocationShownCountryName",
                "write_also",
                "write_value",
            ),
        ),
        uses_iptc_digest=True,
        read_priority=("XMP-iptcExt:LocationShownCountryName", "XMP-photoshop:Country", "IPTC"),
        evidence_ids=(MWG_LOCATION_SOURCE, MWG_RECONCILE_SOURCE, MWG_TRUNCATED_IPTC_SOURCE),
    ),
    MwgCompositeDefinition(
        tag_name="State",
        family2_group="Location",
        writable=True,
        list_value=False,
        direct_composite_write=True,
        require_tag=None,
        desire_tags=(
            associated("IPTC", "Province-State", "desire", "write_existing_iptc_only", 32),
            associated("XMP-photoshop", "State", "desire", "write_value"),
            associated("XMP-iptcExt", "LocationShownProvinceState", "desire", "write_value"),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated("IPTC", "Province-State", "write_also", "write_existing_iptc_only", 32),
            associated("XMP-photoshop", "State", "write_also", "write_value"),
            associated("XMP-iptcExt", "LocationShownProvinceState", "write_also", "write_value"),
        ),
        uses_iptc_digest=True,
        read_priority=("XMP-iptcExt:LocationShownProvinceState", "XMP-photoshop:State", "IPTC"),
        evidence_ids=(MWG_LOCATION_SOURCE, MWG_RECONCILE_SOURCE, MWG_TRUNCATED_IPTC_SOURCE),
    ),
    MwgCompositeDefinition(
        tag_name="City",
        family2_group="Location",
        writable=True,
        list_value=False,
        direct_composite_write=True,
        require_tag=None,
        desire_tags=(
            associated("IPTC", "City", "desire", "write_existing_iptc_only", 32),
            associated("XMP-photoshop", "City", "desire", "write_value"),
            associated("XMP-iptcExt", "LocationShownCity", "desire", "write_value"),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated("IPTC", "City", "write_also", "write_existing_iptc_only", 32),
            associated("XMP-photoshop", "City", "write_also", "write_value"),
            associated("XMP-iptcExt", "LocationShownCity", "write_also", "write_value"),
        ),
        uses_iptc_digest=True,
        read_priority=("XMP-iptcExt:LocationShownCity", "XMP-photoshop:City", "IPTC"),
        evidence_ids=(MWG_LOCATION_SOURCE, MWG_RECONCILE_SOURCE, MWG_TRUNCATED_IPTC_SOURCE),
    ),
    MwgCompositeDefinition(
        tag_name="Location",
        family2_group="Location",
        writable=True,
        list_value=False,
        direct_composite_write=True,
        require_tag=None,
        desire_tags=(
            associated("IPTC", "Sub-location", "desire", "write_existing_iptc_only", 32),
            associated("XMP-iptcCore", "Location", "desire", "write_value"),
            associated("XMP-iptcExt", "LocationShownSublocation", "desire", "write_value"),
            *digest_tags(2),
        ),
        write_also_tags=(
            associated("IPTC", "Sub-location", "write_also", "write_existing_iptc_only", 32),
            associated("XMP-iptcCore", "Location", "write_also", "write_value"),
            associated("XMP-iptcExt", "LocationShownSublocation", "write_also", "write_value"),
        ),
        uses_iptc_digest=True,
        read_priority=("XMP-iptcExt:LocationShownSublocation", "XMP-iptcCore:Location", "IPTC"),
        evidence_ids=(MWG_LOCATION_SOURCE, MWG_RECONCILE_SOURCE, MWG_TRUNCATED_IPTC_SOURCE),
    ),
)

COMPOSITE_LOOKUP: dict[str, MwgCompositeDefinition] = {
    definition.tag_name: definition for definition in COMPOSITE_DEFINITIONS
}
SOURCE_TAG_LOOKUP: dict[str, str] = {
    tag.qualified_name: definition.tag_name
    for definition in COMPOSITE_DEFINITIONS
    for tag in (*definition.desire_tags, *definition.write_also_tags)
    if tag.role != "digest"
}

XMP_NAMESPACE_PLANS = (
    MwgXmpNamespacePlan("XMP-mwg-rs", "mwg-rs", "region_info", True, (MWG_XMP_NAMESPACE_SOURCE,)),
    MwgXmpNamespacePlan(
        "XMP-mwg-kw",
        "mwg-kw",
        "hierarchical_keywords",
        True,
        (MWG_XMP_NAMESPACE_SOURCE,),
    ),
    MwgXmpNamespacePlan(
        "XMP-mwg-coll",
        "mwg-coll",
        "collections",
        True,
        (MWG_XMP_NAMESPACE_SOURCE,),
    ),
)
XMP_NAMESPACE_LOOKUP: dict[str, MwgXmpNamespacePlan] = {
    plan.group_name: plan for plan in XMP_NAMESPACE_PLANS
}

SYNCHRONIZATION_BOUNDARIES = tuple(
    MwgSynchronizationBoundary(
        tag_name=definition.tag_name,
        source_groups=tuple(
            dict.fromkeys(
                tag.group_name
                for tag in (*definition.desire_tags, *definition.write_also_tags)
                if tag.role != "digest"
            )
        ),
        digest_protected=definition.uses_iptc_digest,
        iptc_edit_group_required=any(
            tag.write_policy == "write_existing_iptc_only" for tag in definition.write_also_tags
        ),
        read_conflict_policy="prefer declared RawConv/ValueConv order and recover truncated IPTC",
        evidence_ids=definition.evidence_ids,
    )
    for definition in COMPOSITE_DEFINITIONS
)

RESPONSIBILITIES = (
    MwgResponsibilityPlan(
        "composite_coordination",
        "MWG Composite tags are derived from and written through associated source tags.",
        (MWG_COMPOSITE_SOURCE,),
    ),
    MwgResponsibilityPlan(
        "source_family_routing",
        "EXIF, IPTC, XMP, Composite, and Photoshop digest groups define responsibility.",
        (MWG_COMPOSITE_SOURCE,),
    ),
    MwgResponsibilityPlan(
        "iptc_digest_synchronization",
        "IPTC writes reconcile Photoshop:IPTCDigest when allowed by original digest state.",
        (MWG_RECONCILE_SOURCE,),
    ),
    MwgResponsibilityPlan(
        "strict_mwg_read_locations",
        "Strict mode ignores non-standard EXIF/IPTC/XMP locations during reads.",
        (MWG_COMPOSITE_SOURCE, MWG_LOAD_SOURCE),
    ),
    MwgResponsibilityPlan(
        "exif_utf8_string_default",
        "The exiftool application defaults internal EXIF strings to UTF8 when MWG is loaded.",
        (MWG_COMPOSITE_SOURCE,),
    ),
    MwgResponsibilityPlan(
        "creator_string_list_bridge",
        "EXIF:Artist is changed to list behavior with MWG semicolon-space string rules.",
        (MWG_COMPOSITE_SOURCE, MWG_LOAD_SOURCE, MWG_STRING_LIST_SOURCE),
    ),
    MwgResponsibilityPlan(
        "mwg_xmp_namespace_tables",
        "Region, hierarchical keyword, and collection namespace tables are XMP surfaces.",
        (MWG_XMP_NAMESPACE_SOURCE,),
    ),
    MwgResponsibilityPlan(
        "unsupported_rewrite_gates",
        "This package-local surface is non-mutating and blocks byte output.",
        (MWG_COMPOSITE_SOURCE,),
    ),
)

REWRITE_BLOCKERS = (
    MwgRewriteBlocker(
        "mwg_has_no_container_writer",
        "MWG.pm declares Composite coordination and XMP namespace tables, not a container writer.",
        (MWG_COMPOSITE_SOURCE, MWG_XMP_NAMESPACE_SOURCE),
    ),
    MwgRewriteBlocker(
        "associated_family_writer_required",
        "Writes must be performed by the associated EXIF/IPTC/XMP/Composite family writers.",
        (MWG_COMPOSITE_SOURCE,),
    ),
    MwgRewriteBlocker(
        "raw_container_rewrite_not_in_scope",
        "This slice does not rewrite file container bytes or embedded metadata packets.",
        (MWG_COMPOSITE_SOURCE,),
    ),
)


def qualified_name(group_name: str, tag_name: str) -> str:
    return f"{group_name}:{tag_name}"


def metadata_value_key(value: MwgMetadataValue) -> str:
    if isinstance(value, tuple):
        return "\x1f".join(value)
    return str(value)


def metadata_value_to_json(value: MwgMetadataValue | None) -> JsonValue:
    if isinstance(value, tuple):
        return list(value)
    return value


def evidence_ids_to_json(references: tuple[str, ...]) -> list[JsonValue]:
    return list(references)
