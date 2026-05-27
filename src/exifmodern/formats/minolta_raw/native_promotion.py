"""Minolta MRW native final-output promotion seam.

This module does not perform tag-level MRW mutation.  It promotes the
package-local whole-container emission result into a final native output only
after the TTW/BinaryData handoffs have already produced source-backed bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from exifmodern.formats.minolta_raw.inner_payload_boundary import (
    MINOLTA_RAW_WRITE_TEST_EVIDENCE_ID,
    MinoltaMrwBinaryDataRawPatch,
    MinoltaMrwInnerPayloadGate,
    MinoltaMrwTtwCameraSettingsRewrite,
    MinoltaMrwTtwRebuiltPayload,
    MinoltaMrwWholeContainerEmissionPlan,
    build_minolta_mrw_ttw_camera_settings_rewrite,
    build_minolta_mrw_whole_container_emission_plan,
    unique_gates,
)
from exifmodern.formats.minolta_raw.mutation_plan import (
    MINOLTA_RAW_WRITE_EVIDENCE_ID,
    WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
    inspect_mrw_header,
    unique_evidence_ids,
)
from exifmodern.formats.raw_family.write_plan import RawFamilyWriteRequestClassification
from exifmodern.json_types import JsonObject

type MinoltaMrwNativePromotionStatus = Literal[
    "native_output_ready",
    "native_output_deferred",
    "unsupported",
]
type MinoltaMrwRequestedPromotionStatus = Literal[
    "request_native_output_ready",
    "request_native_output_deferred",
    "unsupported",
]

MINOLTA_MRW_NATIVE_ACTION: Literal["run_modern_minolta_mrw_native_writer"] = (
    "run_modern_minolta_mrw_native_writer"
)


@dataclass(frozen=True)
class MinoltaMrwFinalOutputMaterialization:
    action: str
    output_bytes: bytes
    output_length: int
    output_sha256: str
    metadata_length: int
    raw_tail_source_offset: int
    raw_tail_output_offset: int
    raw_tail_length: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "metadata_length": self.metadata_length,
            "output_length": self.output_length,
            "output_sha256": self.output_sha256,
            "raw_tail_length": self.raw_tail_length,
            "raw_tail_output_offset": self.raw_tail_output_offset,
            "raw_tail_source_offset": self.raw_tail_source_offset,
        }


@dataclass(frozen=True)
class MinoltaMrwNativePromotionPlan:
    status: MinoltaMrwNativePromotionStatus
    can_promote_native: bool
    materialized_output: MinoltaMrwFinalOutputMaterialization | None
    whole_container_plan: MinoltaMrwWholeContainerEmissionPlan
    gates: tuple[MinoltaMrwInnerPayloadGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_promote_native": self.can_promote_native,
            "gates": [gate.to_json() for gate in self.gates],
            "materialized_output": (
                self.materialized_output.to_json() if self.materialized_output is not None else None
            ),
            "output_available": self.materialized_output is not None,
            "status": self.status,
            "whole_container_plan": self.whole_container_plan.to_json(),
        }


@dataclass(frozen=True)
class MinoltaMrwRequestedPromotionPlan:
    status: MinoltaMrwRequestedPromotionStatus
    can_promote_request: bool
    request_id: str | None
    requested_ttw_tags: tuple[str, ...]
    requested_binary_tags: tuple[str, ...]
    native_promotion_plan: MinoltaMrwNativePromotionPlan
    remaining_blockers: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_promote_request": self.can_promote_request,
            "native_promotion_plan": self.native_promotion_plan.to_json(),
            "remaining_blockers": list(self.remaining_blockers),
            "request_id": self.request_id,
            "requested_binary_tags": list(self.requested_binary_tags),
            "requested_ttw_tags": list(self.requested_ttw_tags),
            "status": self.status,
        }


class MinoltaMrwNativePromotionError(ValueError):
    """Raised when callers request native MRW bytes from a deferred plan."""


def build_minolta_mrw_native_promotion_plan(
    data: bytes,
    raw_patches: tuple[MinoltaMrwBinaryDataRawPatch, ...] = (),
    ttw_rebuilt_payloads: tuple[MinoltaMrwTtwRebuiltPayload, ...] = (),
) -> MinoltaMrwNativePromotionPlan:
    whole_container_plan = build_minolta_mrw_whole_container_emission_plan(
        data,
        raw_patches,
        ttw_rebuilt_payloads,
    )
    materialized_output = build_final_output_materialization(data, whole_container_plan)
    if materialized_output is not None:
        gates: tuple[MinoltaMrwInnerPayloadGate, ...] = ()
        return native_promotion_plan(
            status="native_output_ready",
            materialized_output=materialized_output,
            whole_container_plan=whole_container_plan,
            gates=gates,
        )

    return native_promotion_plan(
        status=(
            "unsupported"
            if whole_container_plan.status == "unsupported"
            else "native_output_deferred"
        ),
        materialized_output=None,
        whole_container_plan=whole_container_plan,
        gates=whole_container_plan.gates,
    )


def build_minolta_mrw_requested_native_promotion_plan(
    data: bytes,
    raw_family_classification: RawFamilyWriteRequestClassification | None,
    raw_patches: tuple[MinoltaMrwBinaryDataRawPatch, ...] = (),
    ttw_rebuilt_payloads: tuple[MinoltaMrwTtwRebuiltPayload, ...] = (),
) -> MinoltaMrwRequestedPromotionPlan:
    """Assess whether a classified MRW write request can promote to final bytes.

    The request-level gate is intentionally broader than raw segment emission:
    Minolta.t test 4 writes FocusMode and LastFileNumber through the embedded
    TTW/TIFF MakerNote path, so the whole container may only promote after that
    handoff supplies verified rebuilt TTW bytes.
    """

    requested_ttw_tags = requested_tags_for_surface(
        raw_family_classification,
        "mrw_minolta_ttw_tiff",
    )
    requested_binary_tags = requested_tags_for_surface(
        raw_family_classification,
        "mrw_minolta_makernote_binary",
    )
    camera_settings_rewrite = build_requested_camera_settings_rewrite(
        data,
        raw_family_classification,
        ttw_rebuilt_payloads,
    )
    effective_ttw_rebuilt_payloads = (
        camera_settings_rewrite.ttw_rebuilt_payloads
        if camera_settings_rewrite is not None
        else ttw_rebuilt_payloads
    )
    native_plan = build_minolta_mrw_native_promotion_plan(
        data,
        raw_patches,
        effective_ttw_rebuilt_payloads,
    )
    blockers: list[str] = [gate.code for gate in native_plan.gates]
    if camera_settings_rewrite is not None:
        blockers.extend(gate.code for gate in camera_settings_rewrite.gates)
    if requested_ttw_tags and not effective_ttw_rebuilt_payloads:
        append_unique_blocker(blockers, "requires_mrw_embedded_tiff_rewrite")
        append_unique_blocker(blockers, "requires_minolta_makernote_ttw_update")
    if requested_binary_tags and not effective_ttw_rebuilt_payloads and not raw_patches:
        append_unique_blocker(blockers, "requires_minolta_makernote_binary_update")

    can_promote = native_plan.can_promote_native and not blockers
    return MinoltaMrwRequestedPromotionPlan(
        status=(
            "request_native_output_ready"
            if can_promote
            else "unsupported"
            if native_plan.status == "unsupported"
            else "request_native_output_deferred"
        ),
        can_promote_request=can_promote,
        request_id=(
            raw_family_classification.request_id if raw_family_classification is not None else None
        ),
        requested_ttw_tags=requested_ttw_tags,
        requested_binary_tags=requested_binary_tags,
        native_promotion_plan=native_plan,
        remaining_blockers=tuple(blockers),
        evidence_ids=unique_evidence_ids(
            (
                MINOLTA_RAW_WRITE_EVIDENCE_ID,
                WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
                MINOLTA_RAW_WRITE_TEST_EVIDENCE_ID,
                *native_plan.evidence_ids,
                *(
                    camera_settings_rewrite.evidence_ids
                    if camera_settings_rewrite is not None
                    else ()
                ),
            )
        ),
    )


def build_requested_camera_settings_rewrite(
    data: bytes,
    raw_family_classification: RawFamilyWriteRequestClassification | None,
    ttw_rebuilt_payloads: tuple[MinoltaMrwTtwRebuiltPayload, ...],
) -> MinoltaMrwTtwCameraSettingsRewrite | None:
    if ttw_rebuilt_payloads or raw_family_classification is None:
        return None
    requested_values = tuple(
        (argument.requested_tag, argument.requested_value)
        for argument in raw_family_classification.arguments
        if "mrw_minolta_ttw_tiff" in argument.target_surfaces
    )
    if not requested_values:
        return None
    return build_minolta_mrw_ttw_camera_settings_rewrite(data, requested_values)


def materialize_minolta_mrw_native_output(plan: MinoltaMrwNativePromotionPlan) -> bytes:
    materialized_output = plan.materialized_output
    if not plan.can_promote_native or materialized_output is None:
        gate_codes = ", ".join(gate.code for gate in plan.gates) or "no output bytes"
        raise MinoltaMrwNativePromotionError(
            f"Minolta MRW native output is not ready: {gate_codes}"
        )
    return materialized_output.output_bytes


def build_final_output_materialization(
    original_data: bytes,
    whole_container_plan: MinoltaMrwWholeContainerEmissionPlan,
) -> MinoltaMrwFinalOutputMaterialization | None:
    output_bytes = whole_container_plan.output_bytes
    raw_copy = whole_container_plan.segment_rebuild_plan.raw_image_data_copy
    if whole_container_plan.status != "emitted" or output_bytes is None or raw_copy is None:
        return None

    output_header = inspect_mrw_header(output_bytes)
    if output_header is None:
        return None
    raw_tail = original_data[raw_copy.source_range.start_offset : raw_copy.source_range.end_offset]
    output_tail = output_bytes[raw_copy.planned_output_offset :]
    if raw_tail != output_tail:
        return None

    return MinoltaMrwFinalOutputMaterialization(
        action=MINOLTA_MRW_NATIVE_ACTION,
        output_bytes=output_bytes,
        output_length=len(output_bytes),
        output_sha256=sha256(output_bytes).hexdigest(),
        metadata_length=output_header.metadata_length,
        raw_tail_source_offset=raw_copy.source_range.start_offset,
        raw_tail_output_offset=raw_copy.planned_output_offset,
        raw_tail_length=raw_copy.source_range.length,
        evidence_ids=(
            MINOLTA_RAW_WRITE_EVIDENCE_ID,
            WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
            MINOLTA_RAW_WRITE_TEST_EVIDENCE_ID,
        ),
    )


def native_promotion_plan(
    status: MinoltaMrwNativePromotionStatus,
    materialized_output: MinoltaMrwFinalOutputMaterialization | None,
    whole_container_plan: MinoltaMrwWholeContainerEmissionPlan,
    gates: tuple[MinoltaMrwInnerPayloadGate, ...],
) -> MinoltaMrwNativePromotionPlan:
    unique_gate_tuple = unique_gates(gates)
    return MinoltaMrwNativePromotionPlan(
        status=status,
        can_promote_native=materialized_output is not None,
        materialized_output=materialized_output,
        whole_container_plan=whole_container_plan,
        gates=unique_gate_tuple,
        evidence_ids=native_promotion_evidence_ids(
            materialized_output,
            whole_container_plan,
            unique_gate_tuple,
        ),
    )


def native_promotion_evidence_ids(
    materialized_output: MinoltaMrwFinalOutputMaterialization | None,
    whole_container_plan: MinoltaMrwWholeContainerEmissionPlan,
    gates: tuple[MinoltaMrwInnerPayloadGate, ...],
) -> tuple[str, ...]:
    return unique_evidence_ids(
        (
            MINOLTA_RAW_WRITE_EVIDENCE_ID,
            WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
            MINOLTA_RAW_WRITE_TEST_EVIDENCE_ID,
            *whole_container_plan.evidence_ids,
            *(materialized_output.evidence_ids if materialized_output is not None else ()),
            *(evidence_id for gate in gates for evidence_id in gate.evidence_ids),
        )
    )


def requested_tags_for_surface(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
    surface: str,
) -> tuple[str, ...]:
    if raw_family_classification is None:
        return ()
    return tuple(
        argument.requested_tag
        for argument in raw_family_classification.arguments
        if surface in argument.target_surfaces
    )


def append_unique_blocker(blockers: list[str], blocker: str) -> None:
    if blocker not in blockers:
        blockers.append(blocker)
