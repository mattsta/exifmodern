"""CanonVRD generated-target setup materialization planning.

This package-local planner covers CanonVRD golden requests whose main write
depends on generated DR4/CR2/CR3 setup targets. It builds on the source-grounded
external write classification and only marks exact protected-block copies as
byte-materializable. DR4 value rewrites and container mutations stay as explicit
blockers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.canon_vrd.external_write_plan import (
    CanonVrdEvidenceCarrier,
    CanonVrdEvidenceId,
    CanonVrdExternalAction,
    CanonVrdExternalBlockerCode,
    CanonVrdExternalContainerKind,
    CanonVrdExternalStatus,
    CanonVrdExternalWriteStep,
    classify_write_step,
)
from exifmodern.json_types import (
    JsonObject,
    JsonValue,
    json_array_value,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type CanonVrdSetupAction = Literal[
    "copy_canon_vrd_block_to_generated_vrd",
    "copy_canon_dr4_block_to_generated_dr4",
    "copy_generated_dr4_block_to_vrd_trailer",
    "copy_generated_dr4_block_to_canon_raw_trailer",
    "rewrite_generated_dr4_values",
    "rewrite_embedded_generated_dr4_values",
    "unsupported",
]
type CanonVrdSetupStatus = Literal[
    "setup_materialization_supported",
    "setup_materialization_planned_with_blockers",
    "unsupported",
]
type CanonVrdSetupSourceKind = Literal["fixture", "generated_target", "unknown"]
type CanonVrdSetupBlockerCode = CanonVrdExternalBlockerCode
type CanonVrdCr3AtomPlacement = Literal["quicktime_mov_uuid_canon2_write_last"]
type CanonVrdCr3PayloadBoundary = Literal[
    "uuid_atom_header",
    "uuid_identifier",
    "canon_vrd_trailer_payload",
    "canon_vrd_edit4_record",
    "canon_dr4_payload",
]
type CanonVrdCr3LengthFixup = Literal[
    "quicktime_uuid_atom_size",
    "quicktime_uuid_chunk_offset_record",
    "canon_vrd_edit4_record_length",
    "canon_vrd_header_data_length",
    "canon_vrd_footer_data_length",
    "embedded_dr4_value_bytes",
]

CR3_CANON2_UUID_HEX = "210f1687914911e4811100242131fce4"

SETUP_HANDLED_BLOCKER: CanonVrdExternalBlockerCode = "requires_setup_materialization"
SUPPORTED_EXACT_COPY_ACTIONS: tuple[CanonVrdExternalAction, ...] = (
    "copy_canon_vrd_block_to_vrd_file",
    "copy_canon_dr4_block_to_dr4_file",
)
SUPPORTED_SETUP_BYTE_ACTIONS: tuple[CanonVrdExternalAction, ...] = (
    *SUPPORTED_EXACT_COPY_ACTIONS,
    "copy_canon_dr4_block_to_canon_raw_trailer",
    "rewrite_standalone_dr4_values",
    "rewrite_embedded_dr4_values",
)


CR3_CANON_VRD_MAP_SOURCE = "canon_vrd.setup.cr3_directory_map"
CR3_CANON2_UUID_SOURCE = "canon_vrd.setup.cr3_canon2_uuid"
CR3_UUID_SIZE_UPDATE_SOURCE = "canon_vrd.setup.cr3_uuid_size_update"
CR3_UUID_ADD_OFFSET_SOURCE = "canon_vrd.setup.cr3_uuid_add_offset"
CR3_CTBO_FIXUP_SOURCE = "canon_vrd.setup.cr3_ctbo_fixup"


@dataclass(frozen=True)
class CanonVrdCr3SetupAtomBoundary(CanonVrdEvidenceCarrier):
    placement: CanonVrdCr3AtomPlacement
    uuid_hex: str
    payload_boundaries: tuple[CanonVrdCr3PayloadBoundary, ...]
    length_fixups: tuple[CanonVrdCr3LengthFixup, ...]
    blocker_codes: tuple[CanonVrdSetupBlockerCode, ...]
    source_reference_ids: tuple[CanonVrdEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocker_codes": list(self.blocker_codes),
            "length_fixups": list(self.length_fixups),
            "payload_boundaries": list(self.payload_boundaries),
            "placement": self.placement,
            "uuid_hex": self.uuid_hex,
        }


@dataclass(frozen=True)
class CanonVrdSetupWriteStep(CanonVrdEvidenceCarrier):
    external_step: CanonVrdExternalWriteStep
    action: CanonVrdSetupAction
    status: CanonVrdSetupStatus
    source_name: str | None
    source_kind: CanonVrdSetupSourceKind
    output_name: str | None
    output_container: CanonVrdExternalContainerKind
    blocker_codes: tuple[CanonVrdSetupBlockerCode, ...]
    cr3_atom_boundary: CanonVrdCr3SetupAtomBoundary | None
    source_reference_ids: tuple[CanonVrdEvidenceId, ...]

    @property
    def can_materialize_bytes(self) -> bool:
        return (
            self.external_step.action in SUPPORTED_SETUP_BYTE_ACTIONS
            and self.external_step.status != "unsupported"
            and not self.blocker_codes
        )

    @property
    def is_generated_output(self) -> bool:
        return self.external_step.scope == "setup_step" and self.output_name is not None

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "blocker_codes": list(self.blocker_codes),
            "can_materialize_bytes": self.can_materialize_bytes,
            "cr3_atom_boundary": (
                self.cr3_atom_boundary.to_json() if self.cr3_atom_boundary else None
            ),
            "external_action": self.external_step.action,
            "external_status": self.external_step.status,
            "is_generated_output": self.is_generated_output,
            "output_container": self.output_container,
            "output_name": self.output_name,
            "source_kind": self.source_kind,
            "source_name": self.source_name,
            "status": self.status,
        }


@dataclass(frozen=True)
class CanonVrdSetupMaterializationPlan:
    request_id: str
    fixture: str
    target_filename: str | None
    generated_targets: tuple[str, ...]
    status: CanonVrdSetupStatus
    setup_steps: tuple[CanonVrdSetupWriteStep, ...]
    main_step: CanonVrdSetupWriteStep

    @property
    def steps(self) -> tuple[CanonVrdSetupWriteStep, ...]:
        return (*self.setup_steps, self.main_step)

    @property
    def can_materialize_all_bytes(self) -> bool:
        return all(step.can_materialize_bytes for step in self.steps)

    @property
    def materializable_steps(self) -> tuple[CanonVrdSetupWriteStep, ...]:
        return tuple(step for step in self.steps if step.can_materialize_bytes)

    @property
    def blocked_steps(self) -> tuple[CanonVrdSetupWriteStep, ...]:
        return tuple(step for step in self.steps if step.blocker_codes)

    @property
    def final_target_is_generated_setup_target(self) -> bool:
        return self.target_filename in self.generated_targets

    def to_json(self) -> JsonObject:
        return {
            "blocked_steps": len(self.blocked_steps),
            "can_materialize_all_bytes": self.can_materialize_all_bytes,
            "final_target_is_generated_setup_target": self.final_target_is_generated_setup_target,
            "fixture": self.fixture,
            "generated_targets": list(self.generated_targets),
            "main_step": self.main_step.to_json(),
            "materializable_steps": len(self.materializable_steps),
            "request_id": self.request_id,
            "setup_steps": [step.to_json() for step in self.setup_steps],
            "status": self.status,
            "target_filename": self.target_filename,
        }


def classify_canon_vrd_setup_request_file(path: Path) -> CanonVrdSetupMaterializationPlan:
    return classify_canon_vrd_setup_request_payload(load_json_object(path))


def classify_canon_vrd_setup_request_payload(
    payload: JsonObject,
) -> CanonVrdSetupMaterializationPlan:
    request_id = required_string(payload, "request_id")
    fixture = required_string(payload, "fixture")
    target_filename = json_string_value(payload, "target_filename")
    raw_setup_steps = tuple(json_array_value(payload, "setup_steps"))
    generated_targets = tuple(
        target
        for target in (setup_target_filename(value) for value in raw_setup_steps)
        if target is not None
    )
    setup_steps = tuple(
        classify_setup_materialization_step(value, index, generated_targets)
        for index, value in enumerate(raw_setup_steps, start=1)
    )
    main_external_step = classify_write_step(
        scope="main_write",
        step_index=None,
        fixture=fixture,
        target_filename=target_filename,
        write_args=tuple(json_string_array_value(payload, "write_args")),
    )
    main_step = build_setup_step(main_external_step, generated_targets)
    return CanonVrdSetupMaterializationPlan(
        request_id=request_id,
        fixture=fixture,
        target_filename=target_filename,
        generated_targets=generated_targets,
        status=overall_status((*setup_steps, main_step)),
        setup_steps=setup_steps,
        main_step=main_step,
    )


def classify_setup_materialization_step(
    value: JsonValue,
    index: int,
    generated_targets: tuple[str, ...],
) -> CanonVrdSetupWriteStep:
    if not isinstance(value, dict):
        external_step = classify_write_step(
            scope="setup_step",
            step_index=index,
            fixture=None,
            target_filename=None,
            write_args=(),
        )
        return build_setup_step(external_step, generated_targets)
    external_step = classify_write_step(
        scope="setup_step",
        step_index=index,
        fixture=json_string_value(value, "fixture"),
        target_filename=json_string_value(value, "target_filename"),
        write_args=tuple(json_string_array_value(value, "write_args")),
    )
    return build_setup_step(external_step, generated_targets)


def build_setup_step(
    external_step: CanonVrdExternalWriteStep,
    generated_targets: tuple[str, ...],
) -> CanonVrdSetupWriteStep:
    source_name = setup_source_name(external_step, generated_targets)
    blocker_codes = setup_blocker_codes(external_step)
    return CanonVrdSetupWriteStep(
        external_step=external_step,
        action=setup_action_for_external_action(external_step.action),
        status=step_status(external_step.status, blocker_codes),
        source_name=source_name,
        source_kind=source_kind(source_name, generated_targets),
        output_name=external_step.target_filename,
        output_container=external_step.target_container,
        blocker_codes=blocker_codes,
        cr3_atom_boundary=cr3_atom_boundary_for_step(external_step, blocker_codes),
        source_reference_ids=external_step.source_reference_ids,
    )


def setup_action_for_external_action(action: CanonVrdExternalAction) -> CanonVrdSetupAction:
    if action == "copy_canon_vrd_block_to_vrd_file":
        return "copy_canon_vrd_block_to_generated_vrd"
    if action == "copy_canon_dr4_block_to_dr4_file":
        return "copy_canon_dr4_block_to_generated_dr4"
    if action == "copy_canon_dr4_block_to_vrd_trailer":
        return "copy_generated_dr4_block_to_vrd_trailer"
    if action == "copy_canon_dr4_block_to_canon_raw_trailer":
        return "copy_generated_dr4_block_to_canon_raw_trailer"
    if action == "rewrite_standalone_dr4_values":
        return "rewrite_generated_dr4_values"
    if action == "rewrite_embedded_dr4_values":
        return "rewrite_embedded_generated_dr4_values"
    return "unsupported"


def setup_blocker_codes(
    external_step: CanonVrdExternalWriteStep,
) -> tuple[CanonVrdSetupBlockerCode, ...]:
    handled = {SETUP_HANDLED_BLOCKER}
    if (
        external_step.action == "copy_canon_dr4_block_to_canon_raw_trailer"
        and external_step.scope == "setup_step"
        and external_step.target_container in {"canon_raw_cr2", "canon_raw_crw"}
    ):
        handled.add("requires_canon_raw_trailer_rewrite")
    if external_step.target_container == "canon_raw_cr3":
        handled.add("requires_cr3_quicktime_atom_rebuild")
        if (
            external_step.action == "copy_canon_dr4_block_to_canon_raw_trailer"
            and external_step.scope == "setup_step"
        ):
            handled.add("requires_canon_raw_trailer_rewrite")
        if supports_bounded_cr3_embedded_dr4_value_update(external_step):
            handled.add("requires_dr4_directory_value_writer")
            handled.add("requires_vrd_header_footer_length_updates")
    return tuple(code for code in external_step.blocker_codes if code not in handled)


def setup_source_name(
    external_step: CanonVrdExternalWriteStep,
    generated_targets: tuple[str, ...],
) -> str | None:
    if external_step.tags_from_file is not None:
        return external_step.tags_from_file
    if (
        external_step.scope == "main_write"
        and external_step.action == "rewrite_embedded_dr4_values"
        and external_step.target_filename in generated_targets
    ):
        return external_step.target_filename
    return external_step.fixture


def supports_bounded_cr3_embedded_dr4_value_update(
    external_step: CanonVrdExternalWriteStep,
) -> bool:
    return (
        external_step.scope == "main_write"
        and external_step.action == "rewrite_embedded_dr4_values"
        and external_step.target_container == "canon_raw_cr3"
        and external_step.requested_tags == ("CanonVRD:GammaBlackPoint",)
    )


def cr3_atom_boundary_for_step(
    external_step: CanonVrdExternalWriteStep,
    blocker_codes: tuple[CanonVrdSetupBlockerCode, ...],
) -> CanonVrdCr3SetupAtomBoundary | None:
    if external_step.target_container != "canon_raw_cr3":
        return None
    if external_step.action == "copy_canon_dr4_block_to_canon_raw_trailer":
        return CanonVrdCr3SetupAtomBoundary(
            placement="quicktime_mov_uuid_canon2_write_last",
            uuid_hex=CR3_CANON2_UUID_HEX,
            payload_boundaries=(
                "uuid_atom_header",
                "uuid_identifier",
                "canon_vrd_trailer_payload",
                "canon_vrd_edit4_record",
                "canon_dr4_payload",
            ),
            length_fixups=(
                "quicktime_uuid_atom_size",
                "quicktime_uuid_chunk_offset_record",
                "canon_vrd_edit4_record_length",
                "canon_vrd_header_data_length",
                "canon_vrd_footer_data_length",
            ),
            blocker_codes=blocker_codes,
            source_reference_ids=(
                CR3_CANON_VRD_MAP_SOURCE,
                CR3_CANON2_UUID_SOURCE,
                CR3_UUID_ADD_OFFSET_SOURCE,
                CR3_CTBO_FIXUP_SOURCE,
            ),
        )
    if external_step.action == "rewrite_embedded_dr4_values":
        return CanonVrdCr3SetupAtomBoundary(
            placement="quicktime_mov_uuid_canon2_write_last",
            uuid_hex=CR3_CANON2_UUID_HEX,
            payload_boundaries=(
                "uuid_atom_header",
                "uuid_identifier",
                "canon_vrd_trailer_payload",
                "canon_vrd_edit4_record",
                "canon_dr4_payload",
            ),
            length_fixups=(
                "embedded_dr4_value_bytes",
                "quicktime_uuid_atom_size",
                "quicktime_uuid_chunk_offset_record",
                "canon_vrd_edit4_record_length",
                "canon_vrd_header_data_length",
                "canon_vrd_footer_data_length",
            ),
            blocker_codes=blocker_codes,
            source_reference_ids=(
                CR3_CANON_VRD_MAP_SOURCE,
                CR3_CANON2_UUID_SOURCE,
                CR3_UUID_SIZE_UPDATE_SOURCE,
                CR3_CTBO_FIXUP_SOURCE,
            ),
        )
    return None


def step_status(
    external_status: CanonVrdExternalStatus,
    blocker_codes: tuple[CanonVrdSetupBlockerCode, ...],
) -> CanonVrdSetupStatus:
    if external_status == "unsupported":
        return "unsupported"
    if blocker_codes:
        return "setup_materialization_planned_with_blockers"
    return "setup_materialization_supported"


def overall_status(steps: tuple[CanonVrdSetupWriteStep, ...]) -> CanonVrdSetupStatus:
    if any(step.status == "unsupported" for step in steps):
        return "unsupported"
    if any(step.status == "setup_materialization_planned_with_blockers" for step in steps):
        return "setup_materialization_planned_with_blockers"
    return "setup_materialization_supported"


def source_kind(
    source_name: str | None,
    generated_targets: tuple[str, ...],
) -> CanonVrdSetupSourceKind:
    if source_name is None:
        return "unknown"
    if source_name in generated_targets:
        return "generated_target"
    return "fixture"


def setup_target_filename(value: JsonValue) -> str | None:
    if not isinstance(value, dict):
        return None
    return json_string_value(value, "target_filename")


def required_string(payload: JsonObject, key: str) -> str:
    value = json_string_value(payload, key)
    if value is None:
        raise ValueError(f"Expected string JSON field: {key}")
    return value
