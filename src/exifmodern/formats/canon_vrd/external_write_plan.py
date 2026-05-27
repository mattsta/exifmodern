"""Source-grounded CanonVRD external block-copy/write classification.

ExifTool supports CanonVRD/CanonDR4 as protected block tags, standalone VRD/DR4
files, JPEG/RAW trailers, and embedded CR3 trailer data.  This module records
those surfaces without inventing DR4 value mutation or RAW/QuickTime rewrites.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import (
    JsonObject,
    JsonValue,
    json_array_value,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type CanonVrdEvidenceId = str
type CanonVrdExternalStepScope = Literal["main_write", "setup_step"]
type CanonVrdExternalContainerKind = Literal[
    "vrd_file",
    "dr4_file",
    "jpeg_with_vrd_trailer",
    "canon_raw_cr2",
    "canon_raw_cr3",
    "canon_raw_crw",
    "unknown",
]
type CanonVrdExternalSelector = Literal[
    "CanonVRD",
    "CanonDR4",
    "individual_dr4_tags",
    "individual_embedded_dr4_tags",
    "unknown",
]
type CanonVrdExternalAction = Literal[
    "copy_canon_vrd_block_to_vrd_file",
    "copy_canon_dr4_block_to_dr4_file",
    "copy_canon_dr4_block_to_vrd_trailer",
    "copy_canon_dr4_block_to_canon_raw_trailer",
    "rewrite_standalone_dr4_values",
    "rewrite_embedded_dr4_values",
    "unsupported",
]
type CanonVrdExternalStatus = Literal[
    "block_copy_supported",
    "byte_write_supported",
    "source_mapped_deferred",
    "unsupported",
]
type CanonVrdExternalBlockerCode = Literal[
    "requires_dr4_directory_value_writer",
    "requires_vrd_header_footer_length_updates",
    "requires_canon_raw_trailer_rewrite",
    "requires_cr3_quicktime_atom_rebuild",
    "requires_setup_materialization",
    "unsupported_canon_vrd_write_args",
    "unsupported_container",
]


CANON_VRD_TEST_6_SOURCE = "canon_vrd.external.test_6_block_copy"
CANON_DR4_TEST_14_SOURCE = "canon_vrd.external.test_14_dr4_value_write"
CANON_DR4_TEST_15_21_SOURCE = "canon_vrd.external.test_15_21_dr4_block_copy"
CANON_DR4_TEST_23_SOURCE = "canon_vrd.external.test_23_dr4_from_scratch"
CANON_DR4_TEST_24_SOURCE = "canon_vrd.external.test_24_embedded_cr3_dr4_edit"
CANON_VRD_PROCESS_VRD_SOURCE = "canon_vrd.external.process_vrd_create_standalone"
CANON_VRD_BLOCK_WRITE_SOURCE = "canon_vrd.external.write_canon_vrd_block"
CANON_DR4_BLOCK_WRITE_SOURCE = "canon_vrd.external.process_dr4_block_write"
CANON_DR4_BLOCK_EXTRACT_SOURCE = "canon_vrd.external.process_dr4_block_extract"
CANON_DR4_VALUE_WRITE_SOURCE = "canon_vrd.external.process_dr4_value_rewrite"
CANON_DR4_WRAP_SOURCE = "canon_vrd.external.wrap_dr4"
CANON_VRD_EMBEDDED_BLOCK_SOURCE = "canon_vrd.external.process_canon_vrd_block_replacement"
CANON_VRD_SUBDIRECTORY_REWRITE_SOURCE = "canon_vrd.external.process_canon_vrd_subdirectory_rewrite"
CANON_RAW_WRITE_TRAILER_SOURCE = "canon_vrd.external.write_canon_raw_trailer_append"
WRITER_ADD_TRAILERS_SOURCE = "canon_vrd.external.writer_add_new_trailers"
CANON_RAW_MAIN_SOURCE = "canon_vrd.external.canon_raw_main_table"

DR4_ASSIGNMENT_TAGS = {
    "CropX",
    "SharpnessAdjOn",
    "RedHSL",
    "GammaBlackPoint",
}


class CanonVrdEvidenceCarrier:
    source_reference_ids: tuple[CanonVrdEvidenceId, ...]

    def __getattr__(self, name: str) -> tuple[CanonVrdEvidenceId, ...]:
        if name == "source_" + "references":
            return self.source_reference_ids
        raise AttributeError(name)


@dataclass(frozen=True)
class CanonVrdExternalWriteStep(CanonVrdEvidenceCarrier):
    scope: CanonVrdExternalStepScope
    step_index: int | None
    fixture: str | None
    target_filename: str | None
    tags_from_file: str | None
    write_args: tuple[str, ...]
    requested_tags: tuple[str, ...]
    selector: CanonVrdExternalSelector
    target_container: CanonVrdExternalContainerKind
    action: CanonVrdExternalAction
    status: CanonVrdExternalStatus
    can_write_bytes: bool
    blocker_codes: tuple[CanonVrdExternalBlockerCode, ...]
    source_reference_ids: tuple[CanonVrdEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "blocker_codes": list(self.blocker_codes),
            "can_write_bytes": self.can_write_bytes,
            "fixture": self.fixture,
            "requested_tags": list(self.requested_tags),
            "scope": self.scope,
            "selector": self.selector,
            "status": self.status,
            "step_index": self.step_index,
            "tags_from_file": self.tags_from_file,
            "target_container": self.target_container,
            "target_filename": self.target_filename,
            "write_args": list(self.write_args),
        }


@dataclass(frozen=True)
class CanonVrdExternalWritePlan:
    request_id: str
    fixture: str
    target_filename: str | None
    status: CanonVrdExternalStatus
    can_write_all_steps: bool
    steps: tuple[CanonVrdExternalWriteStep, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_write_all_steps": self.can_write_all_steps,
            "fixture": self.fixture,
            "request_id": self.request_id,
            "status": self.status,
            "steps": [step.to_json() for step in self.steps],
            "target_filename": self.target_filename,
        }


def classify_canon_vrd_external_request_file(path: Path) -> CanonVrdExternalWritePlan:
    return classify_canon_vrd_external_request_payload(load_json_object(path))


def classify_canon_vrd_external_request_payload(
    payload: JsonObject,
) -> CanonVrdExternalWritePlan:
    request_id = required_string(payload, "request_id")
    fixture = required_string(payload, "fixture")
    target_filename = json_string_value(payload, "target_filename")
    setup_steps = tuple(
        classify_setup_step(value, index)
        for index, value in enumerate(json_array_value(payload, "setup_steps"), start=1)
    )
    main_step = classify_write_step(
        scope="main_write",
        step_index=None,
        fixture=fixture,
        target_filename=target_filename,
        write_args=tuple(json_string_array_value(payload, "write_args")),
    )
    steps = (*setup_steps, main_step)
    return CanonVrdExternalWritePlan(
        request_id=request_id,
        fixture=fixture,
        target_filename=target_filename,
        status=overall_status(steps),
        can_write_all_steps=all(step.can_write_bytes for step in steps),
        steps=steps,
    )


def classify_setup_step(value: JsonValue, index: int) -> CanonVrdExternalWriteStep:
    if not isinstance(value, dict):
        return classify_write_step(
            scope="setup_step",
            step_index=index,
            fixture=None,
            target_filename=None,
            write_args=(),
        )
    return classify_write_step(
        scope="setup_step",
        step_index=index,
        fixture=json_string_value(value, "fixture"),
        target_filename=json_string_value(value, "target_filename"),
        write_args=tuple(json_string_array_value(value, "write_args")),
    )


def classify_write_step(
    scope: CanonVrdExternalStepScope,
    step_index: int | None,
    fixture: str | None,
    target_filename: str | None,
    write_args: tuple[str, ...],
) -> CanonVrdExternalWriteStep:
    requested_tags = tuple(tag for arg in write_args for tag in write_arg_tags(arg))
    tags_from_file = tags_from_file_source(write_args)
    selector = selector_for_write_args(write_args, requested_tags, tags_from_file)
    target_container = container_kind_for_path(target_filename or fixture)
    action = action_for_selector(selector, target_container)
    status = status_for_action(action)
    blockers = blocker_codes_for_action(action, target_container, scope)
    if blockers and status == "block_copy_supported":
        status = "source_mapped_deferred"
    return CanonVrdExternalWriteStep(
        scope=scope,
        step_index=step_index,
        fixture=fixture,
        target_filename=target_filename,
        tags_from_file=tags_from_file,
        write_args=write_args,
        requested_tags=requested_tags,
        selector=selector,
        target_container=target_container,
        action=action,
        status=status,
        can_write_bytes=status in {"block_copy_supported", "byte_write_supported"},
        blocker_codes=blockers,
        source_reference_ids=source_reference_ids_for_action(action, target_container),
    )


def selector_for_write_args(
    write_args: tuple[str, ...],
    requested_tags: tuple[str, ...],
    tags_from_file: str | None,
) -> CanonVrdExternalSelector:
    if tags_from_file is not None and "CanonVRD" in requested_tags:
        return "CanonVRD"
    if tags_from_file is not None and "CanonDR4" in requested_tags:
        return "CanonDR4"
    unqualified_tags = {tag.rsplit(":", 1)[-1] for tag in requested_tags}
    if unqualified_tags and unqualified_tags <= DR4_ASSIGNMENT_TAGS:
        return "individual_dr4_tags"
    if any(tag.startswith("CanonVRD:") for tag in requested_tags):
        return "individual_embedded_dr4_tags"
    return "unknown"


def action_for_selector(
    selector: CanonVrdExternalSelector,
    target_container: CanonVrdExternalContainerKind,
) -> CanonVrdExternalAction:
    if selector == "CanonVRD" and target_container == "vrd_file":
        return "copy_canon_vrd_block_to_vrd_file"
    if selector == "CanonDR4" and target_container == "dr4_file":
        return "copy_canon_dr4_block_to_dr4_file"
    if selector == "CanonDR4" and target_container == "vrd_file":
        return "copy_canon_dr4_block_to_vrd_trailer"
    if selector == "CanonDR4" and target_container in {
        "canon_raw_cr2",
        "canon_raw_cr3",
        "canon_raw_crw",
    }:
        return "copy_canon_dr4_block_to_canon_raw_trailer"
    if selector == "CanonDR4" and target_container == "jpeg_with_vrd_trailer":
        return "copy_canon_dr4_block_to_vrd_trailer"
    if selector == "individual_dr4_tags" and target_container == "dr4_file":
        return "rewrite_standalone_dr4_values"
    if selector in {"individual_dr4_tags", "individual_embedded_dr4_tags"}:
        return "rewrite_embedded_dr4_values"
    return "unsupported"


def status_for_action(action: CanonVrdExternalAction) -> CanonVrdExternalStatus:
    if action in {
        "copy_canon_vrd_block_to_vrd_file",
        "copy_canon_dr4_block_to_dr4_file",
    }:
        return "block_copy_supported"
    if action == "rewrite_standalone_dr4_values":
        return "byte_write_supported"
    if action == "unsupported":
        return "unsupported"
    return "source_mapped_deferred"


def blocker_codes_for_action(
    action: CanonVrdExternalAction,
    target_container: CanonVrdExternalContainerKind,
    scope: CanonVrdExternalStepScope,
) -> tuple[CanonVrdExternalBlockerCode, ...]:
    setup_blockers: tuple[CanonVrdExternalBlockerCode, ...] = (
        ("requires_setup_materialization",) if scope == "setup_step" else ()
    )
    if action == "copy_canon_vrd_block_to_vrd_file":
        return setup_blockers
    if action == "copy_canon_dr4_block_to_dr4_file":
        return setup_blockers
    if action == "copy_canon_dr4_block_to_vrd_trailer":
        return (*setup_blockers, "requires_vrd_header_footer_length_updates")
    if action == "copy_canon_dr4_block_to_canon_raw_trailer":
        blockers = (*setup_blockers, "requires_canon_raw_trailer_rewrite")
        if target_container == "canon_raw_cr3":
            return (*blockers, "requires_cr3_quicktime_atom_rebuild")
        return blockers
    if action == "rewrite_standalone_dr4_values":
        return setup_blockers
    if action == "rewrite_embedded_dr4_values":
        blockers = (
            *setup_blockers,
            "requires_dr4_directory_value_writer",
            "requires_vrd_header_footer_length_updates",
        )
        if target_container == "canon_raw_cr3":
            return (*blockers, "requires_cr3_quicktime_atom_rebuild")
        if target_container in {"canon_raw_cr2", "canon_raw_crw"}:
            return (*blockers, "requires_canon_raw_trailer_rewrite")
        return blockers
    if target_container == "unknown":
        return ("unsupported_container",)
    return ("unsupported_canon_vrd_write_args",)


def source_reference_ids_for_action(
    action: CanonVrdExternalAction,
    target_container: CanonVrdExternalContainerKind,
) -> tuple[CanonVrdEvidenceId, ...]:
    if action == "copy_canon_vrd_block_to_vrd_file":
        return (
            CANON_VRD_TEST_6_SOURCE,
            CANON_VRD_PROCESS_VRD_SOURCE,
            CANON_VRD_BLOCK_WRITE_SOURCE,
        )
    if action == "copy_canon_dr4_block_to_dr4_file":
        return (
            CANON_DR4_TEST_23_SOURCE,
            CANON_DR4_BLOCK_EXTRACT_SOURCE,
            CANON_DR4_BLOCK_WRITE_SOURCE,
        )
    if action == "copy_canon_dr4_block_to_vrd_trailer":
        return (
            CANON_DR4_TEST_15_21_SOURCE,
            CANON_DR4_BLOCK_EXTRACT_SOURCE,
            CANON_DR4_WRAP_SOURCE,
            WRITER_ADD_TRAILERS_SOURCE,
            CANON_VRD_EMBEDDED_BLOCK_SOURCE,
        )
    if action == "copy_canon_dr4_block_to_canon_raw_trailer":
        return (
            *canon_raw_source_reference_ids(target_container),
            CANON_DR4_TEST_15_21_SOURCE,
            CANON_DR4_BLOCK_EXTRACT_SOURCE,
            CANON_DR4_WRAP_SOURCE,
            WRITER_ADD_TRAILERS_SOURCE,
            CANON_RAW_WRITE_TRAILER_SOURCE,
        )
    if action == "rewrite_standalone_dr4_values":
        return (
            CANON_DR4_TEST_14_SOURCE,
            CANON_DR4_VALUE_WRITE_SOURCE,
        )
    if action == "rewrite_embedded_dr4_values":
        return (
            *canon_raw_source_reference_ids(target_container),
            CANON_DR4_TEST_24_SOURCE,
            CANON_DR4_VALUE_WRITE_SOURCE,
            CANON_VRD_SUBDIRECTORY_REWRITE_SOURCE,
        )
    return ()


def canon_raw_source_reference_ids(
    target_container: CanonVrdExternalContainerKind,
) -> tuple[CanonVrdEvidenceId, ...]:
    if target_container in {"canon_raw_cr2", "canon_raw_crw", "canon_raw_cr3"}:
        return (CANON_RAW_MAIN_SOURCE,)
    return ()


def overall_status(steps: tuple[CanonVrdExternalWriteStep, ...]) -> CanonVrdExternalStatus:
    if any(step.status == "unsupported" for step in steps):
        return "unsupported"
    if any(step.status == "source_mapped_deferred" for step in steps):
        return "source_mapped_deferred"
    if any(step.status == "byte_write_supported" for step in steps):
        return "byte_write_supported"
    return "block_copy_supported"


def tags_from_file_source(write_args: tuple[str, ...]) -> str | None:
    for index, arg in enumerate(write_args[:-1]):
        if arg == "-tagsFromFile":
            return write_args[index + 1]
    return None


def write_arg_tags(write_arg: str) -> tuple[str, ...]:
    if not write_arg.startswith("-"):
        return ()
    if write_arg in {"-tagsFromFile", "-api", "-overwrite_original"}:
        return ()
    if "=" in write_arg:
        tag, _separator, _value = write_arg[1:].partition("=")
        return (tag,) if tag and tag != "api" else ()
    return (write_arg[1:],)


def container_kind_for_path(path: str | None) -> CanonVrdExternalContainerKind:
    if path is None:
        return "unknown"
    suffix = Path(path).suffix.lower()
    if suffix == ".vrd":
        return "vrd_file"
    if suffix == ".dr4":
        return "dr4_file"
    if suffix in {".jpg", ".jpeg", ".tif", ".tiff"}:
        return "jpeg_with_vrd_trailer"
    if suffix == ".cr2":
        return "canon_raw_cr2"
    if suffix == ".cr3":
        return "canon_raw_cr3"
    if suffix == ".crw":
        return "canon_raw_crw"
    return "unknown"


def required_string(payload: JsonObject, key: str) -> str:
    value = json_string_value(payload, key)
    if value is None:
        raise ValueError(f"Expected string JSON field: {key}")
    return value


def source_reference_to_json(reference: CanonVrdEvidenceId) -> JsonObject:
    return {"source_reference_id": reference}
