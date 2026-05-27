"""CanonVRD generated-target setup materialization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from exifmodern.formats.canon_vrd.copy_from_file_writer import (
    CanonVrdCopyFromFileUnsupportedError,
    extract_canon_dr4_block,
    materialize_supported_canon_vrd_copy,
)
from exifmodern.formats.canon_vrd.reader import (
    CANON_VRD_FOOTER_SIZE,
    CANON_VRD_HEADER_SIZE,
    CANON_VRD_SIGNATURE,
)
from exifmodern.formats.canon_vrd.setup_write_plan import (
    CanonVrdSetupMaterializationPlan,
    CanonVrdSetupWriteStep,
)

CANON_DR4_BLOCK_TYPE = 0xFFFF00F7
CANON_VRD_BLANK_HEADER = CANON_VRD_SIGNATURE + b"\0\x01\0\0\0\0\0\0"
CANON_VRD_BLANK_FOOTER = CANON_VRD_SIGNATURE + (b"\0" * 42) + b"\xff\xd9"
CANON_RAW_DIR_START_POINTER = b"\0\0\0\0"


@dataclass(frozen=True)
class CanonVrdSetupMaterializationResult:
    data: bytes
    copied_bytes: int
    block_tag: str
    applied_step: str
    deferred: tuple[str, ...]


@dataclass(frozen=True)
class CanonVrdSetupMaterializationBatchResult:
    outputs: dict[str, bytes]
    applied_steps: tuple[str, ...]
    copied_bytes: int
    deferred: tuple[str, ...]


class CanonVrdSetupWriteUnsupportedError(ValueError):
    """Raised when a setup step needs DR4 value or container mutation."""


def materialize_supported_canon_vrd_setup_copy(
    source_data: bytes,
    step: CanonVrdSetupWriteStep,
    *,
    target_base_data: bytes | None = None,
) -> CanonVrdSetupMaterializationResult:
    if (
        step.action == "rewrite_embedded_generated_dr4_values"
        and step.output_container == "canon_raw_cr3"
    ):
        if not step.can_materialize_bytes:
            blockers = ", ".join(step.blocker_codes) or step.external_step.status
            raise CanonVrdSetupWriteUnsupportedError(
                f"CanonVRD setup step is not byte-materializable: {step.action} ({blockers})"
            )
        from exifmodern.formats.canon_vrd.cr3_atom_update import (
            CanonVrdCr3AtomUpdateUnsupportedError,
            materialize_bounded_uuid_canon2_write_last_update,
            plan_canon_vrd_cr3_embedded_value_update,
        )

        atom_plan = plan_canon_vrd_cr3_embedded_value_update(
            source_cr3_data=source_data,
            step=step,
        )
        try:
            cr3_result = materialize_bounded_uuid_canon2_write_last_update(
                source_data,
                atom_plan,
            )
        except CanonVrdCr3AtomUpdateUnsupportedError as error:
            raise CanonVrdSetupWriteUnsupportedError(str(error)) from error
        return CanonVrdSetupMaterializationResult(
            data=cr3_result.data,
            copied_bytes=len(cr3_result.data) - len(source_data),
            block_tag="CanonDR4",
            applied_step=step.action,
            deferred=(),
        )
    if (
        step.action == "copy_generated_dr4_block_to_canon_raw_trailer"
        and step.output_container == "canon_raw_cr3"
    ):
        if not step.can_materialize_bytes:
            blockers = ", ".join(step.blocker_codes) or step.external_step.status
            raise CanonVrdSetupWriteUnsupportedError(
                f"CanonVRD setup step is not byte-materializable: {step.action} ({blockers})"
            )
        if target_base_data is None:
            raise CanonVrdSetupWriteUnsupportedError(
                "CanonVRD CR3 setup step requires target base data"
            )
        from exifmodern.formats.canon_vrd.cr3_atom_update import (
            CanonVrdCr3AtomUpdateUnsupportedError,
            materialize_bounded_uuid_canon2_write_last_update,
            plan_canon_vrd_cr3_setup_atom_update,
        )

        atom_plan = plan_canon_vrd_cr3_setup_atom_update(
            target_cr3_data=target_base_data,
            source_dr4_data=source_data,
            step=step,
        )
        try:
            cr3_result = materialize_bounded_uuid_canon2_write_last_update(
                target_base_data,
                atom_plan,
            )
        except CanonVrdCr3AtomUpdateUnsupportedError as error:
            raise CanonVrdSetupWriteUnsupportedError(str(error)) from error
        return CanonVrdSetupMaterializationResult(
            data=cr3_result.data,
            copied_bytes=len(cr3_result.data) - len(target_base_data),
            block_tag="CanonDR4",
            applied_step=step.action,
            deferred=(),
        )
    if not step.can_materialize_bytes:
        blockers = ", ".join(step.blocker_codes) or step.external_step.status
        raise CanonVrdSetupWriteUnsupportedError(
            f"CanonVRD setup step is not byte-materializable: {step.action} ({blockers})"
        )
    if step.action == "copy_generated_dr4_block_to_canon_raw_trailer":
        if step.output_container not in {"canon_raw_cr2", "canon_raw_crw"}:
            raise CanonVrdSetupWriteUnsupportedError(
                f"CanonVRD setup step cannot materialize RAW container: {step.output_container}"
            )
        if target_base_data is None:
            raise CanonVrdSetupWriteUnsupportedError(
                "CanonVRD RAW trailer setup step requires target base data"
            )
        data = append_canon_dr4_raw_trailer(target_base_data, extract_canon_dr4_block(source_data))
        return CanonVrdSetupMaterializationResult(
            data=data,
            copied_bytes=len(data) - len(source_data),
            block_tag="CanonDR4",
            applied_step=step.action,
            deferred=(),
        )
    copy_step = replace(
        step.external_step,
        status="block_copy_supported",
        can_write_bytes=True,
        blocker_codes=(),
    )
    try:
        copy_result = materialize_supported_canon_vrd_copy(source_data, copy_step)
    except CanonVrdCopyFromFileUnsupportedError as error:
        raise CanonVrdSetupWriteUnsupportedError(str(error)) from error
    return CanonVrdSetupMaterializationResult(
        data=copy_result.data,
        copied_bytes=copy_result.copied_bytes,
        block_tag=copy_result.block_tag,
        applied_step=step.action,
        deferred=(),
    )


def materialize_canon_vrd_setup_data(
    source_data_by_name: Mapping[str, bytes],
    plan: CanonVrdSetupMaterializationPlan,
    *,
    include_main_write: bool = True,
) -> CanonVrdSetupMaterializationBatchResult:
    outputs = dict(source_data_by_name)
    applied_steps: list[str] = []
    deferred: list[str] = []
    copied_bytes = 0
    steps = plan.steps if include_main_write else plan.setup_steps
    for step in steps:
        if step.blocker_codes:
            deferred.append(deferred_message(step))
            continue
        if not step.can_materialize_bytes:
            deferred.append(f"CanonVRD setup step is not byte-materializable: {step.action}")
            continue
        if step.source_name is None:
            deferred.append(f"CanonVRD setup step has no source data name: {step.action}")
            continue
        source_data = outputs.get(step.source_name)
        if source_data is None:
            deferred.append(f"CanonVRD setup source is not materialized: {step.source_name}")
            continue
        target_base_data = None
        if step.action == "copy_generated_dr4_block_to_canon_raw_trailer":
            if step.external_step.fixture is None:
                deferred.append(f"CanonVRD setup step has no target fixture: {step.action}")
                continue
            target_base_data = outputs.get(step.external_step.fixture)
            if target_base_data is None:
                deferred.append(
                    "CanonVRD setup target fixture is not materialized: "
                    f"{step.external_step.fixture}"
                )
                continue
        result = materialize_supported_canon_vrd_setup_copy(
            source_data,
            step,
            target_base_data=target_base_data,
        )
        if step.output_name is not None:
            outputs[step.output_name] = result.data
        applied_steps.append(result.applied_step)
        copied_bytes += result.copied_bytes
    return CanonVrdSetupMaterializationBatchResult(
        outputs=outputs,
        applied_steps=tuple(applied_steps),
        copied_bytes=copied_bytes,
        deferred=tuple(deferred),
    )


def deferred_message(step: CanonVrdSetupWriteStep) -> str:
    blockers = ", ".join(step.blocker_codes)
    target = step.output_name or step.external_step.target_filename or step.external_step.fixture
    return f"CanonVRD setup step deferred for {target}: {step.action} ({blockers})"


def wrap_canon_dr4_as_vrd_trailer(dr4_data: bytes) -> bytes:
    """Wrap a protected CanonDR4 block in a CanonVRD trailer."""
    dr4_length = len(dr4_data)
    edit_record_length = dr4_length + 8
    vrd_data_length = dr4_length + 16
    trailer = bytearray(
        CANON_VRD_BLANK_HEADER
        + CANON_DR4_BLOCK_TYPE.to_bytes(4, "big")
        + edit_record_length.to_bytes(4, "big")
        + dr4_length.to_bytes(4, "big")
        + dr4_data
        + b"\0\0\0\0"
        + CANON_VRD_BLANK_FOOTER
    )
    expected_length = CANON_VRD_HEADER_SIZE + vrd_data_length + CANON_VRD_FOOTER_SIZE
    if len(trailer) != expected_length:
        raise CanonVrdSetupWriteUnsupportedError("CanonVRD wrapped DR4 length mismatch")
    trailer[0x18:0x1C] = vrd_data_length.to_bytes(4, "big")
    footer_length_offset = len(trailer) - 0x2C
    trailer[footer_length_offset : footer_length_offset + 4] = vrd_data_length.to_bytes(4, "big")
    return bytes(trailer)


def append_canon_dr4_raw_trailer(raw_data: bytes, dr4_data: bytes) -> bytes:
    """Append a CanonDR4 trailer using Canon RAW trailer ordering."""
    trailer = wrap_canon_dr4_as_vrd_trailer(dr4_data)
    pad = b" " if len(trailer) & 1 else b""
    return raw_data + pad + trailer[:-4] + CANON_RAW_DIR_START_POINTER
