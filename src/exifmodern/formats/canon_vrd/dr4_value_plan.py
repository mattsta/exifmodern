"""CanonVRD DR4 value rewrite planning.

Standalone same-size DR4 value writes can be handed to the package-local value
writer; embedded CanonVRD and RAW containers remain deferred because they add
trailer length and container rewrite requirements.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.canon_vrd.external_write_plan import (
    CANON_DR4_BLOCK_EXTRACT_SOURCE,
    CANON_DR4_BLOCK_WRITE_SOURCE,
    CANON_DR4_TEST_14_SOURCE,
    CANON_DR4_TEST_15_21_SOURCE,
    CANON_DR4_TEST_23_SOURCE,
    CANON_DR4_TEST_24_SOURCE,
    CANON_DR4_VALUE_WRITE_SOURCE,
    CANON_DR4_WRAP_SOURCE,
    CANON_RAW_MAIN_SOURCE,
    CANON_RAW_WRITE_TRAILER_SOURCE,
    CANON_VRD_SUBDIRECTORY_REWRITE_SOURCE,
    WRITER_ADD_TRAILERS_SOURCE,
    CanonVrdEvidenceCarrier,
    CanonVrdEvidenceId,
    CanonVrdExternalAction,
    CanonVrdExternalBlockerCode,
)
from exifmodern.formats.canon_vrd.setup_write_plan import (
    CanonVrdSetupWriteStep,
    classify_canon_vrd_setup_request_payload,
)
from exifmodern.json_types import (
    JsonObject,
    json_array_value,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type CanonVrdDr4PlanStatus = Literal[
    "byte_write_supported",
    "source_mapped_deferred",
    "exact_copy_only",
    "unsupported",
]
type CanonVrdDr4StepKind = Literal[
    "exact_canon_dr4_block_copy",
    "dr4_value_rewrite",
    "unsupported",
]
type CanonVrdDr4ValueScope = Literal[
    "standalone_dr4_file",
    "embedded_canon_vrd_trailer",
    "not_value_rewrite",
]
type CanonVrdDr4ValueLocation = Literal[
    "directory_value",
    "directory_entry_flag",
    "nested_subdirectory_value",
    "unknown",
]
type CanonVrdDr4PhaseKind = Literal[
    "extract_canon_dr4_block",
    "copy_canon_dr4_block",
    "wrap_canon_dr4_in_vrd_trailer",
    "parse_dr4_header",
    "walk_dr4_directory_entries",
    "resolve_requested_dr4_tags",
    "plan_same_size_value_or_flag_writes",
    "rewrite_nested_dr4_subdirectories",
    "update_canon_vrd_header_footer_lengths",
    "rewrite_canon_raw_trailer",
    "rebuild_cr3_quicktime_atoms",
]
type CanonVrdDr4Prerequisite = Literal[
    "source_canon_dr4_block_available",
    "valid_dr4_magic_and_byte_order",
    "dr4_header_is_32_bytes",
    "dr4_entry_count_in_header_word_7",
    "dr4_entries_fit_directory_bounds",
    "requested_dr4_entry_exists",
    "nested_subdirectory_exists",
    "canon_vrd_header_footer_present",
    "canon_vrd_edit4_block_present",
    "canon_raw_write_pipeline_available",
    "cr3_quicktime_atom_map_available",
]
type CanonVrdDr4SafetyGate = Literal[
    "requires_existing_dr4_directory_entry",
    "requires_known_dr4_value_format",
    "requires_same_size_value_encoding",
    "requires_subdirectory_same_length_rewrite",
    "requires_vrd_header_footer_length_updates",
    "requires_canon_raw_trailer_rewrite",
    "requires_cr3_quicktime_atom_rebuild",
    "requires_no_unsafe_byte_mutation",
]
type CanonVrdDr4LengthFieldKind = Literal[
    "dr4_entry_count_header_word",
    "canon_vrd_edit4_record_length",
    "canon_vrd_header_data_length",
    "canon_vrd_footer_data_length",
]
type CanonVrdDr4LengthPolicy = Literal[
    "validate_only",
    "preserve_existing_length",
    "defer_update_until_container_rewrite",
]


CANON_DR4_TABLE_SOURCE = "canon_vrd.dr4.table"
CANON_DR4_HEADER_TABLE_SOURCE = "canon_vrd.dr4.header_table"
CANON_DR4_HEADER_PROCESS_SOURCE = "canon_vrd.dr4.header_validation"
CANON_DR4_ENTRY_WALK_SOURCE = "canon_vrd.dr4.entry_rewrite_loop"
CANON_VRD_LENGTH_FIELDS_SOURCE = "canon_vrd.dr4.vrd_length_fields"
CANON_VRD_DIRECTORY_PHASE_SOURCE = "canon_vrd.dr4.vrd_directory_rewrite_phases"
CANON_DR4_TAG_LAYOUT_SOURCE = "canon_vrd.dr4.writable_tag_layout"


@dataclass(frozen=True)
class CanonVrdDr4RequestedValue:
    argument: str
    group: str | None
    tag_name: str
    raw_value: str
    location: CanonVrdDr4ValueLocation
    dr4_entry_tag_id: str | None
    flag_index: int | None
    subdirectory: str | None
    subdirectory_tag_id: str | None
    value_format: str | None

    def to_json(self) -> JsonObject:
        return {
            "argument": self.argument,
            "dr4_entry_tag_id": self.dr4_entry_tag_id,
            "flag_index": self.flag_index,
            "group": self.group,
            "location": self.location,
            "raw_value": self.raw_value,
            "subdirectory": self.subdirectory,
            "subdirectory_tag_id": self.subdirectory_tag_id,
            "tag_name": self.tag_name,
            "value_format": self.value_format,
        }


@dataclass(frozen=True)
class CanonVrdDr4LengthRequirement(CanonVrdEvidenceCarrier):
    kind: CanonVrdDr4LengthFieldKind
    byte_offset: int | None
    location: str
    policy: CanonVrdDr4LengthPolicy
    source_reference_ids: tuple[CanonVrdEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_offset": self.byte_offset,
            "kind": self.kind,
            "location": self.location,
            "policy": self.policy,
        }


@dataclass(frozen=True)
class CanonVrdDr4RewritePhase(CanonVrdEvidenceCarrier):
    kind: CanonVrdDr4PhaseKind
    description: str
    source_reference_ids: tuple[CanonVrdEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "description": self.description,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class CanonVrdDr4RewriteStepPlan(CanonVrdEvidenceCarrier):
    action: CanonVrdExternalAction
    step_kind: CanonVrdDr4StepKind
    value_scope: CanonVrdDr4ValueScope
    source_name: str | None
    output_name: str | None
    target_container: str
    requested_values: tuple[CanonVrdDr4RequestedValue, ...]
    prerequisites: tuple[CanonVrdDr4Prerequisite, ...]
    safety_gates: tuple[CanonVrdDr4SafetyGate, ...]
    length_requirements: tuple[CanonVrdDr4LengthRequirement, ...]
    phases: tuple[CanonVrdDr4RewritePhase, ...]
    blocker_codes: tuple[CanonVrdExternalBlockerCode, ...]
    source_reference_ids: tuple[CanonVrdEvidenceId, ...]

    @property
    def can_materialize_exact_copy(self) -> bool:
        return self.step_kind == "exact_canon_dr4_block_copy" and not self.blocker_codes

    @property
    def can_rewrite_values(self) -> bool:
        return self.step_kind == "dr4_value_rewrite" and not self.blocker_codes

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "blocker_codes": list(self.blocker_codes),
            "can_materialize_exact_copy": self.can_materialize_exact_copy,
            "can_rewrite_values": self.can_rewrite_values,
            "length_requirements": [
                requirement.to_json() for requirement in self.length_requirements
            ],
            "output_name": self.output_name,
            "phases": [phase.to_json() for phase in self.phases],
            "prerequisites": list(self.prerequisites),
            "requested_values": [value.to_json() for value in self.requested_values],
            "safety_gates": list(self.safety_gates),
            "source_name": self.source_name,
            "step_kind": self.step_kind,
            "target_container": self.target_container,
            "value_scope": self.value_scope,
        }


@dataclass(frozen=True)
class CanonVrdDr4ValueRewritePlan(CanonVrdEvidenceCarrier):
    request_id: str
    fixture: str
    target_filename: str | None
    status: CanonVrdDr4PlanStatus
    steps: tuple[CanonVrdDr4RewriteStepPlan, ...]
    source_reference_ids: tuple[CanonVrdEvidenceId, ...]

    @property
    def value_rewrite_steps(self) -> tuple[CanonVrdDr4RewriteStepPlan, ...]:
        return tuple(step for step in self.steps if step.step_kind == "dr4_value_rewrite")

    @property
    def exact_copy_steps(self) -> tuple[CanonVrdDr4RewriteStepPlan, ...]:
        return tuple(step for step in self.steps if step.step_kind == "exact_canon_dr4_block_copy")

    @property
    def can_rewrite_any_values(self) -> bool:
        return any(step.can_rewrite_values for step in self.value_rewrite_steps)

    def to_json(self) -> JsonObject:
        return {
            "can_rewrite_any_values": self.can_rewrite_any_values,
            "exact_copy_steps": len(self.exact_copy_steps),
            "fixture": self.fixture,
            "request_id": self.request_id,
            "status": self.status,
            "steps": [step.to_json() for step in self.steps],
            "target_filename": self.target_filename,
            "value_rewrite_steps": len(self.value_rewrite_steps),
        }


def classify_canon_vrd_dr4_value_request_file(path: Path) -> CanonVrdDr4ValueRewritePlan:
    return classify_canon_vrd_dr4_value_request_payload(load_json_object(path))


def classify_canon_vrd_dr4_value_request_payload(
    payload: JsonObject,
) -> CanonVrdDr4ValueRewritePlan:
    setup_plan = classify_canon_vrd_setup_request_payload(payload)
    raw_steps = (*setup_raw_steps(payload), main_raw_step(payload))
    steps = tuple(
        step_plan
        for setup_step, raw_step in zip(setup_plan.steps, raw_steps, strict=True)
        if (step_plan := build_dr4_step_plan(setup_step, raw_step)) is not None
    )
    return CanonVrdDr4ValueRewritePlan(
        request_id=required_string(payload, "request_id"),
        fixture=required_string(payload, "fixture"),
        target_filename=json_string_value(payload, "target_filename"),
        status=plan_status(steps),
        steps=steps,
        source_reference_ids=unique_source_reference_ids(
            reference for step in steps for reference in step.source_reference_ids
        ),
    )


def build_dr4_step_plan(
    setup_step: CanonVrdSetupWriteStep,
    raw_step: JsonObject,
) -> CanonVrdDr4RewriteStepPlan | None:
    action = setup_step.external_step.action
    write_args = tuple(json_string_array_value(raw_step, "write_args"))
    requested_values = tuple(
        requested_value
        for assignment in write_assignments(write_args)
        if (requested_value := requested_value_from_assignment(assignment)) is not None
    )

    if action in {"rewrite_standalone_dr4_values", "rewrite_embedded_dr4_values"}:
        return build_value_rewrite_step(setup_step, requested_values)
    if action in {
        "copy_canon_dr4_block_to_dr4_file",
        "copy_canon_dr4_block_to_vrd_trailer",
        "copy_canon_dr4_block_to_canon_raw_trailer",
    }:
        return build_exact_copy_step(setup_step)
    if requested_values:
        return build_unsupported_step(setup_step, requested_values)
    return None


def build_value_rewrite_step(
    setup_step: CanonVrdSetupWriteStep,
    requested_values: tuple[CanonVrdDr4RequestedValue, ...],
) -> CanonVrdDr4RewriteStepPlan:
    action = setup_step.external_step.action
    embedded = action == "rewrite_embedded_dr4_values"
    target_container = setup_step.output_container
    blockers = setup_step.blocker_codes
    return CanonVrdDr4RewriteStepPlan(
        action=action,
        step_kind="dr4_value_rewrite",
        value_scope="embedded_canon_vrd_trailer" if embedded else "standalone_dr4_file",
        source_name=setup_step.source_name,
        output_name=setup_step.output_name,
        target_container=target_container,
        requested_values=requested_values,
        prerequisites=prerequisites_for_value_rewrite(embedded, target_container),
        safety_gates=safety_gates_for_value_rewrite(blockers, requested_values),
        length_requirements=length_requirements_for_value_rewrite(embedded),
        phases=phases_for_value_rewrite(embedded, target_container),
        blocker_codes=blockers,
        source_reference_ids=source_reference_ids_for_value_rewrite(embedded, target_container),
    )


def build_exact_copy_step(setup_step: CanonVrdSetupWriteStep) -> CanonVrdDr4RewriteStepPlan:
    action = setup_step.external_step.action
    target_container = setup_step.output_container
    return CanonVrdDr4RewriteStepPlan(
        action=action,
        step_kind="exact_canon_dr4_block_copy",
        value_scope="not_value_rewrite",
        source_name=setup_step.source_name,
        output_name=setup_step.output_name,
        target_container=target_container,
        requested_values=(),
        prerequisites=prerequisites_for_exact_copy(target_container),
        safety_gates=safety_gates_for_exact_copy(setup_step.blocker_codes),
        length_requirements=length_requirements_for_exact_copy(target_container),
        phases=phases_for_exact_copy(target_container),
        blocker_codes=setup_step.blocker_codes,
        source_reference_ids=source_reference_ids_for_exact_copy(action, target_container),
    )


def build_unsupported_step(
    setup_step: CanonVrdSetupWriteStep,
    requested_values: tuple[CanonVrdDr4RequestedValue, ...],
) -> CanonVrdDr4RewriteStepPlan:
    return CanonVrdDr4RewriteStepPlan(
        action=setup_step.external_step.action,
        step_kind="unsupported",
        value_scope="not_value_rewrite",
        source_name=setup_step.source_name,
        output_name=setup_step.output_name,
        target_container=setup_step.output_container,
        requested_values=requested_values,
        prerequisites=(),
        safety_gates=("requires_no_unsafe_byte_mutation",),
        length_requirements=(),
        phases=(),
        blocker_codes=setup_step.blocker_codes,
        source_reference_ids=setup_step.source_reference_ids,
    )


def prerequisites_for_value_rewrite(
    embedded: bool,
    target_container: str,
) -> tuple[CanonVrdDr4Prerequisite, ...]:
    prerequisites: list[CanonVrdDr4Prerequisite] = [
        "source_canon_dr4_block_available",
        "valid_dr4_magic_and_byte_order",
        "dr4_header_is_32_bytes",
        "dr4_entry_count_in_header_word_7",
        "dr4_entries_fit_directory_bounds",
        "requested_dr4_entry_exists",
    ]
    if embedded:
        prerequisites.extend(("canon_vrd_header_footer_present", "canon_vrd_edit4_block_present"))
    if target_container in {"canon_raw_cr2", "canon_raw_cr3", "canon_raw_crw"}:
        prerequisites.append("canon_raw_write_pipeline_available")
    if target_container == "canon_raw_cr3":
        prerequisites.append("cr3_quicktime_atom_map_available")
    return tuple(prerequisites)


def safety_gates_for_value_rewrite(
    blockers: tuple[CanonVrdExternalBlockerCode, ...],
    requested_values: tuple[CanonVrdDr4RequestedValue, ...],
) -> tuple[CanonVrdDr4SafetyGate, ...]:
    gates: list[CanonVrdDr4SafetyGate] = [
        "requires_existing_dr4_directory_entry",
        "requires_known_dr4_value_format",
        "requires_same_size_value_encoding",
        "requires_no_unsafe_byte_mutation",
    ]
    if any(value.location == "nested_subdirectory_value" for value in requested_values):
        gates.append("requires_subdirectory_same_length_rewrite")
    gates.extend(safety_gates_from_blockers(blockers))
    return unique_values(gates)


def length_requirements_for_value_rewrite(
    embedded: bool,
) -> tuple[CanonVrdDr4LengthRequirement, ...]:
    requirements: list[CanonVrdDr4LengthRequirement] = [
        CanonVrdDr4LengthRequirement(
            kind="dr4_entry_count_header_word",
            byte_offset=28,
            location="DR4 header word 7",
            policy="validate_only",
            source_reference_ids=(
                CANON_DR4_HEADER_TABLE_SOURCE,
                CANON_DR4_HEADER_PROCESS_SOURCE,
            ),
        )
    ]
    if embedded:
        requirements.extend(canon_vrd_length_requirements())
    return tuple(requirements)


def phases_for_value_rewrite(
    embedded: bool,
    target_container: str,
) -> tuple[CanonVrdDr4RewritePhase, ...]:
    phases = [
        CanonVrdDr4RewritePhase(
            kind="parse_dr4_header",
            description=(
                "Validate DR4 magic/byte order, 32-byte header, entry count, and "
                "entry table bounds before considering any value writes."
            ),
            source_reference_ids=(
                CANON_DR4_HEADER_TABLE_SOURCE,
                CANON_DR4_HEADER_PROCESS_SOURCE,
            ),
        ),
        CanonVrdDr4RewritePhase(
            kind="walk_dr4_directory_entries",
            description=(
                "Walk existing 28-byte DR4 entries and resolve each entry value "
                "offset, length, format, and associated flag words."
            ),
            source_reference_ids=(CANON_DR4_ENTRY_WALK_SOURCE,),
        ),
        CanonVrdDr4RewritePhase(
            kind="resolve_requested_dr4_tags",
            description=(
                "Resolve requested DR4 tags to an existing entry value, entry flag, "
                "or nested binary-data subdirectory member."
            ),
            source_reference_ids=(CANON_DR4_TAG_LAYOUT_SOURCE,),
        ),
        CanonVrdDr4RewritePhase(
            kind="plan_same_size_value_or_flag_writes",
            description=(
                "Only plan writes whose encoded value fits the existing scalar or "
                "flag field; this planner does not emit mutation bytes."
            ),
            source_reference_ids=(CANON_DR4_VALUE_WRITE_SOURCE, CANON_DR4_ENTRY_WALK_SOURCE),
        ),
    ]
    if embedded:
        phases.append(
            CanonVrdDr4RewritePhase(
                kind="rewrite_nested_dr4_subdirectories",
                description=(
                    "Let the CanonVRD edit block own nested DR4 directory rewrites "
                    "and reject subdirectory output whose length changes."
                ),
                source_reference_ids=(
                    CANON_DR4_ENTRY_WALK_SOURCE,
                    CANON_VRD_DIRECTORY_PHASE_SOURCE,
                ),
            )
        )
        phases.append(
            CanonVrdDr4RewritePhase(
                kind="update_canon_vrd_header_footer_lengths",
                description=(
                    "If the embedded CanonVRD block length changes, update the "
                    "header and footer contained-data length words together."
                ),
                source_reference_ids=(
                    CANON_VRD_LENGTH_FIELDS_SOURCE,
                    CANON_VRD_SUBDIRECTORY_REWRITE_SOURCE,
                    CANON_VRD_DIRECTORY_PHASE_SOURCE,
                ),
            )
        )
    if target_container in {"canon_raw_cr2", "canon_raw_crw"}:
        phases.append(canon_raw_trailer_phase())
    if target_container == "canon_raw_cr3":
        phases.append(
            CanonVrdDr4RewritePhase(
                kind="rebuild_cr3_quicktime_atoms",
                description=(
                    "CR3 embeds CanonVRD data inside a QuickTime-family container; "
                    "atom rebuilding is outside this DR4 value planner."
                ),
                source_reference_ids=(CANON_RAW_MAIN_SOURCE,),
            )
        )
    return tuple(phases)


def prerequisites_for_exact_copy(target_container: str) -> tuple[CanonVrdDr4Prerequisite, ...]:
    prerequisites: list[CanonVrdDr4Prerequisite] = ["source_canon_dr4_block_available"]
    if target_container in {
        "vrd_file",
        "jpeg_with_vrd_trailer",
        "canon_raw_cr2",
        "canon_raw_cr3",
        "canon_raw_crw",
    }:
        prerequisites.extend(("canon_vrd_header_footer_present", "canon_vrd_edit4_block_present"))
    if target_container in {"canon_raw_cr2", "canon_raw_cr3", "canon_raw_crw"}:
        prerequisites.append("canon_raw_write_pipeline_available")
    if target_container == "canon_raw_cr3":
        prerequisites.append("cr3_quicktime_atom_map_available")
    return tuple(prerequisites)


def safety_gates_for_exact_copy(
    blockers: tuple[CanonVrdExternalBlockerCode, ...],
) -> tuple[CanonVrdDr4SafetyGate, ...]:
    return safety_gates_from_blockers(blockers)


def length_requirements_for_exact_copy(
    target_container: str,
) -> tuple[CanonVrdDr4LengthRequirement, ...]:
    if target_container == "dr4_file":
        return ()
    if target_container in {
        "vrd_file",
        "jpeg_with_vrd_trailer",
        "canon_raw_cr2",
        "canon_raw_cr3",
        "canon_raw_crw",
    }:
        return canon_vrd_length_requirements()
    return ()


def phases_for_exact_copy(target_container: str) -> tuple[CanonVrdDr4RewritePhase, ...]:
    phases = [
        CanonVrdDr4RewritePhase(
            kind="extract_canon_dr4_block",
            description="Extract the complete CanonDR4 protected block without value edits.",
            source_reference_ids=(CANON_DR4_BLOCK_EXTRACT_SOURCE,),
        ),
        CanonVrdDr4RewritePhase(
            kind="copy_canon_dr4_block",
            description="Write the CanonDR4 protected block unchanged when the target is DR4.",
            source_reference_ids=(CANON_DR4_BLOCK_WRITE_SOURCE,),
        ),
    ]
    if target_container != "dr4_file":
        phases.append(
            CanonVrdDr4RewritePhase(
                kind="wrap_canon_dr4_in_vrd_trailer",
                description=(
                    "Wrap the DR4 record with a CanonVRD header, Edit4 record, "
                    "and footer before adding it to a trailer-bearing target."
                ),
                source_reference_ids=(CANON_DR4_WRAP_SOURCE, WRITER_ADD_TRAILERS_SOURCE),
            )
        )
    if target_container in {"canon_raw_cr2", "canon_raw_crw"}:
        phases.append(canon_raw_trailer_phase())
    if target_container == "canon_raw_cr3":
        phases.append(canon_raw_trailer_phase())
        phases.append(
            CanonVrdDr4RewritePhase(
                kind="rebuild_cr3_quicktime_atoms",
                description=(
                    "CR3 trailer insertion requires QuickTime-family container work "
                    "outside exact DR4 block copying."
                ),
                source_reference_ids=(CANON_RAW_MAIN_SOURCE,),
            )
        )
    return tuple(phases)


def source_reference_ids_for_value_rewrite(
    embedded: bool,
    target_container: str,
) -> tuple[CanonVrdEvidenceId, ...]:
    references: list[CanonVrdEvidenceId] = [
        CANON_DR4_TEST_24_SOURCE if embedded else CANON_DR4_TEST_14_SOURCE,
        CANON_DR4_TABLE_SOURCE,
        CANON_DR4_HEADER_TABLE_SOURCE,
        CANON_DR4_HEADER_PROCESS_SOURCE,
        CANON_DR4_ENTRY_WALK_SOURCE,
        CANON_DR4_VALUE_WRITE_SOURCE,
        CANON_DR4_TAG_LAYOUT_SOURCE,
    ]
    if embedded:
        references.extend(
            (
                CANON_VRD_LENGTH_FIELDS_SOURCE,
                CANON_VRD_SUBDIRECTORY_REWRITE_SOURCE,
                CANON_VRD_DIRECTORY_PHASE_SOURCE,
            )
        )
    if target_container in {"canon_raw_cr2", "canon_raw_cr3", "canon_raw_crw"}:
        references.extend((CANON_RAW_MAIN_SOURCE, CANON_RAW_WRITE_TRAILER_SOURCE))
    return unique_source_reference_ids(references)


def source_reference_ids_for_exact_copy(
    action: CanonVrdExternalAction,
    target_container: str,
) -> tuple[CanonVrdEvidenceId, ...]:
    references: list[CanonVrdEvidenceId] = [
        CANON_DR4_TEST_23_SOURCE
        if action == "copy_canon_dr4_block_to_dr4_file"
        else CANON_DR4_TEST_15_21_SOURCE,
        CANON_DR4_BLOCK_EXTRACT_SOURCE,
        CANON_DR4_BLOCK_WRITE_SOURCE,
    ]
    if target_container != "dr4_file":
        references.extend(
            (
                CANON_DR4_WRAP_SOURCE,
                WRITER_ADD_TRAILERS_SOURCE,
                CANON_VRD_LENGTH_FIELDS_SOURCE,
            )
        )
    if target_container in {"canon_raw_cr2", "canon_raw_cr3", "canon_raw_crw"}:
        references.extend((CANON_RAW_MAIN_SOURCE, CANON_RAW_WRITE_TRAILER_SOURCE))
    return unique_source_reference_ids(references)


def canon_vrd_length_requirements() -> tuple[CanonVrdDr4LengthRequirement, ...]:
    return (
        CanonVrdDr4LengthRequirement(
            kind="canon_vrd_edit4_record_length",
            byte_offset=None,
            location="Edit4 block length word immediately before the DR4 payload",
            policy="defer_update_until_container_rewrite",
            source_reference_ids=(CANON_DR4_WRAP_SOURCE, CANON_VRD_DIRECTORY_PHASE_SOURCE),
        ),
        CanonVrdDr4LengthRequirement(
            kind="canon_vrd_header_data_length",
            byte_offset=0x18,
            location="CanonVRD 0x1c-byte header",
            policy="defer_update_until_container_rewrite",
            source_reference_ids=(CANON_DR4_WRAP_SOURCE, CANON_VRD_LENGTH_FIELDS_SOURCE),
        ),
        CanonVrdDr4LengthRequirement(
            kind="canon_vrd_footer_data_length",
            byte_offset=0x14,
            location="CanonVRD 0x40-byte footer",
            policy="defer_update_until_container_rewrite",
            source_reference_ids=(CANON_DR4_WRAP_SOURCE, CANON_VRD_LENGTH_FIELDS_SOURCE),
        ),
    )


def canon_raw_trailer_phase() -> CanonVrdDr4RewritePhase:
    return CanonVrdDr4RewritePhase(
        kind="rewrite_canon_raw_trailer",
        description=(
            "Canon RAW writes append or rewrite CanonVRD trailers through the RAW "
            "writer and patch the trailing DirStart pointer."
        ),
        source_reference_ids=(CANON_RAW_MAIN_SOURCE, CANON_RAW_WRITE_TRAILER_SOURCE),
    )


def write_assignments(write_args: tuple[str, ...]) -> tuple[tuple[str, str, str | None], ...]:
    assignments: list[tuple[str, str, str | None]] = []
    skip_next = False
    for arg in write_args:
        if skip_next:
            skip_next = False
            continue
        if arg in {"-api", "-tagsFromFile"}:
            skip_next = True
            continue
        if arg == "-overwrite_original" or not arg.startswith("-") or "=" not in arg:
            continue
        tag, _separator, value = arg[1:].partition("=")
        assignments.append((arg, tag, value))
    return tuple(assignments)


def requested_value_from_assignment(
    assignment: tuple[str, str, str | None],
) -> CanonVrdDr4RequestedValue | None:
    argument, raw_tag, raw_value = assignment
    group, tag_name = split_grouped_tag(raw_tag)
    if tag_name not in REQUESTED_TAG_LAYOUT:
        return None
    layout = REQUESTED_TAG_LAYOUT[tag_name]
    return CanonVrdDr4RequestedValue(
        argument=argument,
        group=group,
        tag_name=tag_name,
        raw_value=raw_value or "",
        location=layout.location,
        dr4_entry_tag_id=layout.dr4_entry_tag_id,
        flag_index=layout.flag_index,
        subdirectory=layout.subdirectory,
        subdirectory_tag_id=layout.subdirectory_tag_id,
        value_format=layout.value_format,
    )


@dataclass(frozen=True)
class RequestedDr4TagLayout:
    location: CanonVrdDr4ValueLocation
    dr4_entry_tag_id: str
    flag_index: int | None
    subdirectory: str | None
    subdirectory_tag_id: str | None
    value_format: str


REQUESTED_TAG_LAYOUT: dict[str, RequestedDr4TagLayout] = {
    "CropX": RequestedDr4TagLayout(
        location="nested_subdirectory_value",
        dr4_entry_tag_id="0x0f0100",
        flag_index=None,
        subdirectory="CropInfo",
        subdirectory_tag_id="0x03",
        value_format="int32s",
    ),
    "SharpnessAdjOn": RequestedDr4TagLayout(
        location="directory_entry_flag",
        dr4_entry_tag_id="0x020310",
        flag_index=0,
        subdirectory=None,
        subdirectory_tag_id=None,
        value_format="int32u",
    ),
    "RedHSL": RequestedDr4TagLayout(
        location="directory_value",
        dr4_entry_tag_id="0x020910",
        flag_index=None,
        subdirectory=None,
        subdirectory_tag_id=None,
        value_format="entry_format",
    ),
    "GammaBlackPoint": RequestedDr4TagLayout(
        location="nested_subdirectory_value",
        dr4_entry_tag_id="0x020a00",
        flag_index=None,
        subdirectory="GammaInfo",
        subdirectory_tag_id="0x0c",
        value_format="double",
    ),
}


def split_grouped_tag(raw_tag: str) -> tuple[str | None, str]:
    if ":" not in raw_tag:
        return None, raw_tag
    group, _separator, tag_name = raw_tag.rpartition(":")
    return group or None, tag_name


def safety_gates_from_blockers(
    blockers: tuple[CanonVrdExternalBlockerCode, ...],
) -> tuple[CanonVrdDr4SafetyGate, ...]:
    gates: list[CanonVrdDr4SafetyGate] = []
    if "requires_vrd_header_footer_length_updates" in blockers:
        gates.append("requires_vrd_header_footer_length_updates")
    if "requires_canon_raw_trailer_rewrite" in blockers:
        gates.append("requires_canon_raw_trailer_rewrite")
    if "requires_cr3_quicktime_atom_rebuild" in blockers:
        gates.append("requires_cr3_quicktime_atom_rebuild")
    return tuple(gates)


def setup_raw_steps(payload: JsonObject) -> tuple[JsonObject, ...]:
    return tuple(
        value if isinstance(value, dict) else {}
        for value in json_array_value(payload, "setup_steps")
    )


def main_raw_step(payload: JsonObject) -> JsonObject:
    return {
        "fixture": json_string_value(payload, "fixture"),
        "target_filename": json_string_value(payload, "target_filename"),
        "write_args": json_array_value(payload, "write_args"),
    }


def plan_status(
    steps: tuple[CanonVrdDr4RewriteStepPlan, ...],
) -> CanonVrdDr4PlanStatus:
    if any(step.step_kind == "unsupported" for step in steps):
        return "unsupported"
    if any(step.blocker_codes for step in steps):
        return "source_mapped_deferred"
    if any(step.step_kind == "dr4_value_rewrite" for step in steps):
        return "byte_write_supported"
    return "exact_copy_only"


def required_string(payload: JsonObject, key: str) -> str:
    value = json_string_value(payload, key)
    if value is None:
        raise ValueError(f"Expected string JSON field: {key}")
    return value


def unique_values[T](values: list[T]) -> tuple[T, ...]:
    unique: list[T] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return tuple(unique)


def unique_source_reference_ids(
    references: Iterable[CanonVrdEvidenceId],
) -> tuple[CanonVrdEvidenceId, ...]:
    unique: list[CanonVrdEvidenceId] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)
