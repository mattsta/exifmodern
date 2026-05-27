"""MRW inner TTW/BinaryData mutation boundaries.

This module intentionally stops below user-facing tag conversion.  It models
the source-backed payload contract that MRW segment emission needs: TTW is an
embedded TIFF writer handoff, while PRD/WBG/RIF are fixed-offset BinaryData
payloads that may be replaced only with exact-size raw bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.minolta_raw.mutation_plan import (
    MINOLTA_RAW_BINARY_EVIDENCE_ID,
    MINOLTA_RAW_RIF_EVIDENCE_ID,
    MINOLTA_RAW_WBG_EVIDENCE_ID,
    MINOLTA_RAW_WRITE_EVIDENCE_ID,
    WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
    MinoltaMrwSegmentName,
    unique_evidence_ids,
)
from exifmodern.formats.minolta_raw.segment_rebuild_plan import (
    MinoltaMrwBinaryDataTableName,
    MinoltaMrwSegmentEmissionError,
    MinoltaMrwSegmentRebuildPlan,
    MinoltaMrwSegmentReplacement,
    MinoltaMrwTtwRewriteHandoff,
    build_minolta_mrw_segment_rebuild_plan,
    emit_minolta_mrw_segment_rebuild_bytes,
    mrw_four_byte_padding_length,
)
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_UNDEFINED,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
)
from exifmodern.json_types import JsonObject

type MinoltaMrwInnerPayloadPlanStatus = Literal["source_mapped_partial", "unsupported"]
type MinoltaMrwBinaryDataFormat = Literal[
    "string[8]",
    "int8u",
    "int8s",
    "int8u[4]",
    "int16u",
    "int16u[2]",
    "int16u[4]",
    "int32u",
]
type MinoltaMrwInnerPayloadGateCode = Literal[
    "ttw_tiff_writer_required",
    "missing_ttw_rebuilt_payload",
    "ttw_rebuilt_payload_boundary_mismatch",
    "ttw_rebuilt_payload_empty",
    "ttw_fixup_not_confirmed",
    "ttw_camera_settings_layout_unsupported",
    "ttw_camera_settings_value_unsupported",
    "unsupported_binary_tag",
    "missing_binary_segment",
    "binary_payload_size_mismatch",
    "binary_payload_range_out_of_bounds",
    "whole_mrw_output_still_gated",
    "whole_mrw_segment_emission_failed",
]
type MinoltaMrwWholeContainerEmissionStatus = Literal["emitted", "gated", "unsupported"]

MINOLTA_RAW_WRITE_TEST_SOURCE_ID = "minolta_raw.inner_payload.write_test"
MINOLTA_RAW_MRW_OUTPUT_SOURCE_ID = "minolta_raw.inner_payload.writer_output"
MINOLTA_MAKERNOTE_MAIN_SOURCE_ID = "minolta_raw.inner_payload.makernote_main"
MINOLTA_CAMERA_SETTINGS_SOURCE_ID = "minolta_raw.inner_payload.camera_settings"

MINOLTA_RAW_WRITE_TEST_EVIDENCE_ID = MINOLTA_RAW_WRITE_TEST_SOURCE_ID
MINOLTA_RAW_MRW_OUTPUT_EVIDENCE_ID = MINOLTA_RAW_MRW_OUTPUT_SOURCE_ID
MINOLTA_MAKERNOTE_MAIN_EVIDENCE_ID = MINOLTA_MAKERNOTE_MAIN_SOURCE_ID
MINOLTA_CAMERA_SETTINGS_EVIDENCE_ID = MINOLTA_CAMERA_SETTINGS_SOURCE_ID

TTW_EXIF_IFD_POINTER_TAG = 0x8769
TTW_MAKER_NOTE_TAG = 0x927C
MINOLTA_CAMERA_SETTINGS_OLD_TAG = 0x0001
MINOLTA_CAMERA_SETTINGS_TAG = 0x0003
MINOLTA_CAMERA_SETTINGS_ENTRY_SIZE = 4
MINOLTA_LAST_FILE_NUMBER_INDEX = 27
MINOLTA_FOCUS_MODE_INDEX = 48


@dataclass(frozen=True)
class MinoltaMrwBinaryDataRawPatch:
    tag_name: str
    raw_payload: bytes


@dataclass(frozen=True)
class MinoltaMrwTtwRebuiltPayload:
    segment_index: int
    input_offset: int
    input_length: int
    rebuilt_tiff_payload: bytes
    fixup_applied: bool
    ttw_length_verified: bool


@dataclass(frozen=True)
class MinoltaMrwBinaryDataFieldSpec:
    tag_name: str
    segment_name: MinoltaMrwSegmentName
    tag_table: MinoltaMrwBinaryDataTableName
    offset: int
    format_name: MinoltaMrwBinaryDataFormat
    byte_count: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_count": self.byte_count,
            "format_name": self.format_name,
            "offset": self.offset,
            "segment_name": self.segment_name,
            "tag_name": self.tag_name,
            "tag_table": self.tag_table,
        }


@dataclass(frozen=True)
class MinoltaMrwInnerPayloadGate:
    code: MinoltaMrwInnerPayloadGateCode
    message: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class MinoltaMrwTtwPayloadBoundary:
    segment_index: int
    input_offset: int
    input_length: int
    output_offset: int
    writer: str
    required_fixup: str
    gate: MinoltaMrwInnerPayloadGate | None

    def to_json(self) -> JsonObject:
        return {
            "gate": self.gate.to_json() if self.gate is not None else None,
            "input_length": self.input_length,
            "input_offset": self.input_offset,
            "output_offset": self.output_offset,
            "required_fixup": self.required_fixup,
            "segment_index": self.segment_index,
            "writer": self.writer,
        }


@dataclass(frozen=True)
class MinoltaMrwTtwMutationStep:
    segment_index: int
    input_range: tuple[int, int]
    rebuilt_payload_length: int
    padding_length: int
    output_payload_length: int
    required_fixups: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "input_range": [self.input_range[0], self.input_range[1]],
            "output_payload_length": self.output_payload_length,
            "padding_length": self.padding_length,
            "rebuilt_payload_length": self.rebuilt_payload_length,
            "required_fixups": list(self.required_fixups),
            "segment_index": self.segment_index,
        }


@dataclass(frozen=True)
class MinoltaMrwTtwCameraSettingsPatch:
    tag_name: str
    requested_value: str
    raw_value: int
    byte_range: tuple[int, int]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": [self.byte_range[0], self.byte_range[1]],
            "raw_value": self.raw_value,
            "requested_value": self.requested_value,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class MinoltaMrwTtwCameraSettingsRewrite:
    status: MinoltaMrwInnerPayloadPlanStatus
    ttw_rebuilt_payloads: tuple[MinoltaMrwTtwRebuiltPayload, ...]
    patches: tuple[MinoltaMrwTtwCameraSettingsPatch, ...]
    gates: tuple[MinoltaMrwInnerPayloadGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "gates": [gate.to_json() for gate in self.gates],
            "patches": [patch.to_json() for patch in self.patches],
            "status": self.status,
            "ttw_rebuilt_payload_count": len(self.ttw_rebuilt_payloads),
        }


@dataclass(frozen=True)
class MinoltaMrwBinaryDataMutationStep:
    segment_index: int
    tag_name: str
    byte_range: tuple[int, int]
    raw_payload: bytes
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": [self.byte_range[0], self.byte_range[1]],
            "raw_payload_hex": self.raw_payload.hex(),
            "segment_index": self.segment_index,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class MinoltaMrwInnerPayloadMutationPlan:
    status: MinoltaMrwInnerPayloadPlanStatus
    can_build_segment_replacements: bool
    whole_mrw_output_gated: bool
    ttw_boundaries: tuple[MinoltaMrwTtwPayloadBoundary, ...]
    ttw_steps: tuple[MinoltaMrwTtwMutationStep, ...]
    binary_data_fields: tuple[MinoltaMrwBinaryDataFieldSpec, ...]
    binary_data_steps: tuple[MinoltaMrwBinaryDataMutationStep, ...]
    segment_replacements: tuple[MinoltaMrwSegmentReplacement, ...]
    gates: tuple[MinoltaMrwInnerPayloadGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "binary_data_fields": [field.to_json() for field in self.binary_data_fields],
            "binary_data_steps": [step.to_json() for step in self.binary_data_steps],
            "can_build_segment_replacements": self.can_build_segment_replacements,
            "gates": [gate.to_json() for gate in self.gates],
            "segment_replacements": [
                {
                    "outcome": replacement.outcome,
                    "payload_hex": replacement.payload.hex(),
                    "segment_index": replacement.segment_index,
                    "writer": replacement.writer,
                }
                for replacement in self.segment_replacements
            ],
            "status": self.status,
            "ttw_boundaries": [boundary.to_json() for boundary in self.ttw_boundaries],
            "ttw_steps": [step.to_json() for step in self.ttw_steps],
            "whole_mrw_output_gated": self.whole_mrw_output_gated,
        }


@dataclass(frozen=True)
class MinoltaMrwWholeContainerEmissionPlan:
    status: MinoltaMrwWholeContainerEmissionStatus
    can_emit: bool
    output_bytes: bytes | None
    inner_payload_plan: MinoltaMrwInnerPayloadMutationPlan
    segment_rebuild_plan: MinoltaMrwSegmentRebuildPlan
    gates: tuple[MinoltaMrwInnerPayloadGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_emit": self.can_emit,
            "gates": [gate.to_json() for gate in self.gates],
            "inner_payload_plan": self.inner_payload_plan.to_json(),
            "output_available": self.output_bytes is not None,
            "output_length": len(self.output_bytes) if self.output_bytes is not None else None,
            "segment_rebuild_plan": self.segment_rebuild_plan.to_json(),
            "status": self.status,
        }


def build_minolta_mrw_inner_payload_mutation_plan(
    data: bytes,
    raw_patches: tuple[MinoltaMrwBinaryDataRawPatch, ...] = (),
    ttw_rebuilt_payloads: tuple[MinoltaMrwTtwRebuiltPayload, ...] = (),
) -> MinoltaMrwInnerPayloadMutationPlan:
    segment_plan = build_minolta_mrw_segment_rebuild_plan(data)
    binary_fields = minolta_mrw_binary_data_field_specs()
    ttw_steps, ttw_gates = build_ttw_mutation_steps(ttw_rebuilt_payloads, segment_plan)
    gates = [
        *ttw_gates,
        *ttw_boundary_gates(segment_plan.ttw_handoffs, ttw_steps),
    ]
    steps: list[MinoltaMrwBinaryDataMutationStep] = []

    if segment_plan.status != "source_mapped_non_mutating":
        return MinoltaMrwInnerPayloadMutationPlan(
            status="unsupported",
            can_build_segment_replacements=False,
            whole_mrw_output_gated=True,
            ttw_boundaries=ttw_boundaries(segment_plan, ttw_steps),
            ttw_steps=ttw_steps,
            binary_data_fields=binary_fields,
            binary_data_steps=(),
            segment_replacements=(),
            gates=unique_gates(tuple(gates)),
            evidence_ids=inner_payload_evidence_ids(binary_fields, tuple(gates), ttw_steps, ()),
        )

    for patch in raw_patches:
        step, gate = build_binary_data_mutation_step(data, patch, binary_fields, segment_plan)
        if step is not None:
            steps.append(step)
        if gate is not None:
            gates.append(gate)

    unsupported = any(gate.code in blocker_codes() for gate in gates)
    whole_mrw_output_gated = unsupported or len(ttw_steps) != len(segment_plan.ttw_handoffs)
    if whole_mrw_output_gated:
        gates.append(
            MinoltaMrwInnerPayloadGate(
                code="whole_mrw_output_still_gated",
                message=(
                    "Inner payload planning emits segment replacement payloads only; callers must "
                    "keep whole MRW output gated until the selected writer path has "
                    "explicit approval."
                ),
                evidence_ids=(MINOLTA_RAW_WRITE_TEST_EVIDENCE_ID,),
            )
        )
    replacements = (
        *build_ttw_segment_replacements(ttw_rebuilt_payloads, ttw_steps),
        *build_binary_data_segment_replacements(data, tuple(steps), segment_plan),
    )
    return MinoltaMrwInnerPayloadMutationPlan(
        status="unsupported" if unsupported else "source_mapped_partial",
        can_build_segment_replacements=bool(ttw_steps or steps) and not unsupported,
        whole_mrw_output_gated=whole_mrw_output_gated,
        ttw_boundaries=ttw_boundaries(segment_plan, ttw_steps),
        ttw_steps=ttw_steps,
        binary_data_fields=binary_fields,
        binary_data_steps=tuple(steps),
        segment_replacements=() if unsupported else replacements,
        gates=unique_gates(tuple(gates)),
        evidence_ids=inner_payload_evidence_ids(
            binary_fields, tuple(gates), ttw_steps, tuple(steps)
        ),
    )


def build_minolta_mrw_whole_container_emission_plan(
    data: bytes,
    raw_patches: tuple[MinoltaMrwBinaryDataRawPatch, ...] = (),
    ttw_rebuilt_payloads: tuple[MinoltaMrwTtwRebuiltPayload, ...] = (),
) -> MinoltaMrwWholeContainerEmissionPlan:
    inner_payload_plan = build_minolta_mrw_inner_payload_mutation_plan(
        data,
        raw_patches,
        ttw_rebuilt_payloads,
    )
    segment_rebuild_plan = build_minolta_mrw_segment_rebuild_plan(
        data,
        inner_payload_plan.segment_replacements,
    )
    gates = list(inner_payload_plan.gates)
    if inner_payload_plan.status == "unsupported":
        return whole_container_emission_plan(
            status="unsupported",
            output_bytes=None,
            inner_payload_plan=inner_payload_plan,
            segment_rebuild_plan=segment_rebuild_plan,
            gates=tuple(gates),
        )
    if inner_payload_plan.whole_mrw_output_gated:
        return whole_container_emission_plan(
            status="gated",
            output_bytes=None,
            inner_payload_plan=inner_payload_plan,
            segment_rebuild_plan=segment_rebuild_plan,
            gates=tuple(gates),
        )
    try:
        output_bytes = emit_minolta_mrw_segment_rebuild_bytes(
            data,
            inner_payload_plan.segment_replacements,
        )
    except MinoltaMrwSegmentEmissionError as exc:
        gates.append(
            MinoltaMrwInnerPayloadGate(
                code="whole_mrw_segment_emission_failed",
                message=f"MRW segment emission failed after handoff validation: {exc}.",
                evidence_ids=(MINOLTA_RAW_WRITE_EVIDENCE_ID, WRITE_EXIF_MRW_TTW_EVIDENCE_ID),
            )
        )
        return whole_container_emission_plan(
            status="gated",
            output_bytes=None,
            inner_payload_plan=inner_payload_plan,
            segment_rebuild_plan=segment_rebuild_plan,
            gates=tuple(gates),
        )
    return whole_container_emission_plan(
        status="emitted",
        output_bytes=output_bytes,
        inner_payload_plan=inner_payload_plan,
        segment_rebuild_plan=segment_rebuild_plan,
        gates=(),
    )


def build_minolta_mrw_ttw_camera_settings_rewrite(
    data: bytes,
    requested_values: tuple[tuple[str, str], ...],
) -> MinoltaMrwTtwCameraSettingsRewrite:
    """Build a TTW payload from source-backed Minolta CameraSettings writes.

    This is intentionally bounded to the Minolta MRW write-test shape: FocusMode
    and LastFileNumber inside the existing Minolta CameraSettings BinaryData
    block.  The caller still routes the emitted payload through the MRW segment
    and TTW fixup gates before whole-container output is allowed.
    """

    segment_plan = build_minolta_mrw_segment_rebuild_plan(data)
    if len(segment_plan.ttw_handoffs) != 1:
        return ttw_camera_settings_rewrite_unsupported(
            "Expected exactly one MinoltaTTW segment for CameraSettings rewrite.",
            "ttw_camera_settings_layout_unsupported",
        )
    handoff = segment_plan.ttw_handoffs[0]
    payload = bytearray(
        data[handoff.input_payload_range.start_offset : handoff.input_payload_range.end_offset]
    )
    try:
        camera_settings = locate_minolta_ttw_camera_settings(bytes(payload))
    except ValueError as exc:
        return ttw_camera_settings_rewrite_unsupported(
            str(exc),
            "ttw_camera_settings_layout_unsupported",
        )

    patches: list[MinoltaMrwTtwCameraSettingsPatch] = []
    for tag_name, requested_value in requested_values:
        patch = build_minolta_camera_settings_patch(
            payload=payload,
            camera_settings_entry=camera_settings,
            tag_name=tag_name,
            requested_value=requested_value,
        )
        if patch is None:
            return ttw_camera_settings_rewrite_unsupported(
                f"Unsupported Minolta CameraSettings value for {tag_name}.",
                "ttw_camera_settings_value_unsupported",
            )
        payload[patch.byte_range[0] : patch.byte_range[1]] = patch.raw_value.to_bytes(4, "big")
        patches.append(patch)

    return MinoltaMrwTtwCameraSettingsRewrite(
        status="source_mapped_partial",
        ttw_rebuilt_payloads=(
            MinoltaMrwTtwRebuiltPayload(
                segment_index=handoff.segment_index,
                input_offset=handoff.input_payload_range.start_offset,
                input_length=handoff.input_payload_range.length,
                rebuilt_tiff_payload=bytes(payload),
                fixup_applied=True,
                ttw_length_verified=True,
            ),
        ),
        patches=tuple(patches),
        gates=(),
        evidence_ids=unique_evidence_ids(
            (
                MINOLTA_RAW_WRITE_EVIDENCE_ID,
                WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
                MINOLTA_MAKERNOTE_MAIN_EVIDENCE_ID,
                MINOLTA_CAMERA_SETTINGS_EVIDENCE_ID,
                MINOLTA_RAW_WRITE_TEST_EVIDENCE_ID,
            )
        ),
    )


def locate_minolta_ttw_camera_settings(ttw_payload: bytes) -> IfdEntry:
    header = parse_tiff_header(ttw_payload)
    ifd0 = parse_ifd(ttw_payload, header.first_ifd_offset, header.endian)
    exif_ifd_entry = required_ttw_ifd_entry(ifd0, TTW_EXIF_IFD_POINTER_TAG, "ExifIFD pointer")
    exif_ifd = parse_ifd(ttw_payload, exif_ifd_entry.value_offset, header.endian)
    maker_note_entry = required_ttw_ifd_entry(exif_ifd, TTW_MAKER_NOTE_TAG, "MakerNote")
    if maker_note_entry.field_type != TIFF_TYPE_UNDEFINED:
        raise ValueError("TTW MakerNote is not undefined data.")
    maker_note_ifd = parse_ifd(ttw_payload, maker_note_entry.value_offset, header.endian)
    for tag_id in (MINOLTA_CAMERA_SETTINGS_TAG, MINOLTA_CAMERA_SETTINGS_OLD_TAG):
        entry = optional_ttw_ifd_entry(maker_note_ifd, tag_id)
        if entry is not None:
            return entry
    raise ValueError("TTW MakerNote lacks a Minolta CameraSettings subdirectory.")


def build_minolta_camera_settings_patch(
    payload: bytearray,
    camera_settings_entry: IfdEntry,
    tag_name: str,
    requested_value: str,
) -> MinoltaMrwTtwCameraSettingsPatch | None:
    raw_value = minolta_camera_settings_raw_value(tag_name, requested_value)
    if raw_value is None:
        return None
    tag_index = minolta_camera_settings_tag_index(tag_name)
    if tag_index is None:
        return None
    start = camera_settings_entry.value_offset + tag_index * MINOLTA_CAMERA_SETTINGS_ENTRY_SIZE
    end = start + MINOLTA_CAMERA_SETTINGS_ENTRY_SIZE
    if (
        end > len(payload)
        or tag_index * MINOLTA_CAMERA_SETTINGS_ENTRY_SIZE >= camera_settings_entry.count
    ):
        return None
    return MinoltaMrwTtwCameraSettingsPatch(
        tag_name=tag_name,
        requested_value=requested_value,
        raw_value=raw_value,
        byte_range=(start, end),
        evidence_ids=(MINOLTA_MAKERNOTE_MAIN_EVIDENCE_ID, MINOLTA_CAMERA_SETTINGS_EVIDENCE_ID),
    )


def minolta_camera_settings_tag_index(tag_name: str) -> int | None:
    if tag_name == "FocusMode":
        return MINOLTA_FOCUS_MODE_INDEX
    if tag_name == "LastFileNumber":
        return MINOLTA_LAST_FILE_NUMBER_INDEX
    return None


def minolta_camera_settings_raw_value(tag_name: str, requested_value: str) -> int | None:
    if tag_name == "FocusMode":
        if requested_value == "AF":
            return 0
        if requested_value == "MF":
            return 1
        return None
    if tag_name == "LastFileNumber":
        try:
            value = int(requested_value)
        except ValueError:
            return None
        if value < 0 or value > 0xFFFFFFFF:
            return None
        return value
    return None


def required_ttw_ifd_entry(ifd: Ifd, tag_id: int, label: str) -> IfdEntry:
    entry = optional_ttw_ifd_entry(ifd, tag_id)
    if entry is None:
        raise ValueError(f"TTW missing {label} tag 0x{tag_id:04x}.")
    return entry


def optional_ttw_ifd_entry(ifd: Ifd, tag_id: int) -> IfdEntry | None:
    return next((entry for entry in ifd.entries if entry.tag_id == tag_id), None)


def ttw_camera_settings_rewrite_unsupported(
    message: str,
    code: MinoltaMrwInnerPayloadGateCode,
) -> MinoltaMrwTtwCameraSettingsRewrite:
    gate = MinoltaMrwInnerPayloadGate(
        code=code,
        message=message,
        evidence_ids=(
            MINOLTA_MAKERNOTE_MAIN_EVIDENCE_ID,
            MINOLTA_CAMERA_SETTINGS_EVIDENCE_ID,
            WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
        ),
    )
    return MinoltaMrwTtwCameraSettingsRewrite(
        status="unsupported",
        ttw_rebuilt_payloads=(),
        patches=(),
        gates=(gate,),
        evidence_ids=gate.evidence_ids,
    )


def minolta_mrw_binary_data_field_specs() -> tuple[MinoltaMrwBinaryDataFieldSpec, ...]:
    return (
        field("FirmwareID", "MinoltaPRD", "Image::ExifTool::MinoltaRaw::PRD", 0, "string[8]", 8),
        field("SensorHeight", "MinoltaPRD", "Image::ExifTool::MinoltaRaw::PRD", 8, "int16u", 2),
        field("SensorWidth", "MinoltaPRD", "Image::ExifTool::MinoltaRaw::PRD", 10, "int16u", 2),
        field("ImageHeight", "MinoltaPRD", "Image::ExifTool::MinoltaRaw::PRD", 12, "int16u", 2),
        field("ImageWidth", "MinoltaPRD", "Image::ExifTool::MinoltaRaw::PRD", 14, "int16u", 2),
        field("RawDepth", "MinoltaPRD", "Image::ExifTool::MinoltaRaw::PRD", 16, "int8u", 1),
        field("BitDepth", "MinoltaPRD", "Image::ExifTool::MinoltaRaw::PRD", 17, "int8u", 1),
        field("StorageMethod", "MinoltaPRD", "Image::ExifTool::MinoltaRaw::PRD", 18, "int8u", 1),
        field("BayerPattern", "MinoltaPRD", "Image::ExifTool::MinoltaRaw::PRD", 23, "int8u", 1),
        field("WBScale", "MinoltaWBG", "Image::ExifTool::MinoltaRaw::WBG", 0, "int8u[4]", 4),
        field("WB_RGGBLevels", "MinoltaWBG", "Image::ExifTool::MinoltaRaw::WBG", 4, "int16u[4]", 8),
        field("Saturation", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 1, "int8s", 1),
        field("Contrast", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 2, "int8s", 1),
        field("Sharpness", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 3, "int8s", 1),
        field("WBMode", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 4, "int8u", 1),
        field("ProgramMode", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 5, "int8u", 1),
        field("ISOSetting", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 6, "int8u", 1),
        field("ColorMode", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 7, "int8u", 1),
        field("ColorFilter", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 56, "int8s", 1),
        field("BWFilter", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 57, "int8u", 1),
        field("ZoneMatching", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 58, "int8u", 1),
        field("Hue", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 59, "int8s", 1),
        field("ColorTemperature", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 60, "int8u", 1),
        field("RawDataLength", "MinoltaRIF", "Image::ExifTool::MinoltaRaw::RIF", 80, "int32u", 4),
    )


def field(
    tag_name: str,
    segment_name: MinoltaMrwSegmentName,
    tag_table: MinoltaMrwBinaryDataTableName,
    offset: int,
    format_name: MinoltaMrwBinaryDataFormat,
    byte_count: int,
) -> MinoltaMrwBinaryDataFieldSpec:
    return MinoltaMrwBinaryDataFieldSpec(
        tag_name=tag_name,
        segment_name=segment_name,
        tag_table=tag_table,
        offset=offset,
        format_name=format_name,
        byte_count=byte_count,
        evidence_ids=field_evidence_ids(segment_name),
    )


def field_evidence_ids(segment_name: MinoltaMrwSegmentName) -> tuple[str, ...]:
    if segment_name == "MinoltaPRD":
        return (MINOLTA_RAW_BINARY_EVIDENCE_ID, MINOLTA_RAW_MRW_OUTPUT_EVIDENCE_ID)
    if segment_name == "MinoltaWBG":
        return (MINOLTA_RAW_WBG_EVIDENCE_ID, MINOLTA_RAW_MRW_OUTPUT_EVIDENCE_ID)
    return (MINOLTA_RAW_RIF_EVIDENCE_ID, MINOLTA_RAW_MRW_OUTPUT_EVIDENCE_ID)


def ttw_boundary_gates(
    handoffs: tuple[MinoltaMrwTtwRewriteHandoff, ...],
    steps: tuple[MinoltaMrwTtwMutationStep, ...],
) -> tuple[MinoltaMrwInnerPayloadGate, ...]:
    fulfilled_indexes = frozenset(step.segment_index for step in steps)
    return tuple(
        MinoltaMrwInnerPayloadGate(
            code="ttw_tiff_writer_required",
            message="MinoltaTTW mutation must be delegated to WriteTIFF with MRW TTW fixups.",
            evidence_ids=(*handoff.evidence_ids, WRITE_EXIF_MRW_TTW_EVIDENCE_ID),
        )
        for handoff in handoffs
        if handoff.segment_index not in fulfilled_indexes
    )


def ttw_boundaries(
    segment_plan: MinoltaMrwSegmentRebuildPlan,
    steps: tuple[MinoltaMrwTtwMutationStep, ...],
) -> tuple[MinoltaMrwTtwPayloadBoundary, ...]:
    gates_by_index = {
        gate_handoff.segment_index: gate
        for gate_handoff, gate in zip(
            (
                handoff
                for handoff in segment_plan.ttw_handoffs
                if handoff.segment_index not in {step.segment_index for step in steps}
            ),
            ttw_boundary_gates(segment_plan.ttw_handoffs, steps),
            strict=True,
        )
    }
    return tuple(
        MinoltaMrwTtwPayloadBoundary(
            segment_index=handoff.segment_index,
            input_offset=handoff.input_payload_range.start_offset,
            input_length=handoff.input_payload_range.length,
            output_offset=segment_plan.segments[
                handoff.segment_index
            ].planned_output_range.start_offset,
            writer=handoff.write_proc,
            required_fixup="WriteExif MRW TTW length verification",
            gate=gates_by_index.get(handoff.segment_index),
        )
        for handoff in segment_plan.ttw_handoffs
    )


def build_ttw_mutation_steps(
    rebuilt_payloads: tuple[MinoltaMrwTtwRebuiltPayload, ...],
    segment_plan: MinoltaMrwSegmentRebuildPlan,
) -> tuple[tuple[MinoltaMrwTtwMutationStep, ...], tuple[MinoltaMrwInnerPayloadGate, ...]]:
    steps: list[MinoltaMrwTtwMutationStep] = []
    gates: list[MinoltaMrwInnerPayloadGate] = []
    handoffs_by_index: dict[int, MinoltaMrwTtwRewriteHandoff] = {
        handoff.segment_index: handoff for handoff in segment_plan.ttw_handoffs
    }
    payload_indexes = frozenset(payload.segment_index for payload in rebuilt_payloads)
    for handoff in segment_plan.ttw_handoffs:
        if handoff.segment_index not in payload_indexes:
            gates.append(
                MinoltaMrwInnerPayloadGate(
                    code="missing_ttw_rebuilt_payload",
                    message=(
                        "MinoltaTTW has no already-rebuilt TIFF payload for segment "
                        f"{handoff.segment_index}."
                    ),
                    evidence_ids=(*handoff.evidence_ids, WRITE_EXIF_MRW_TTW_EVIDENCE_ID),
                )
            )
    for rebuilt_payload in rebuilt_payloads:
        matched_handoff = handoffs_by_index.get(rebuilt_payload.segment_index)
        if matched_handoff is None:
            gates.append(
                MinoltaMrwInnerPayloadGate(
                    code="ttw_rebuilt_payload_boundary_mismatch",
                    message=(
                        "TTW rebuilt payload references a segment index that is not a "
                        f"MinoltaTTW handoff: {rebuilt_payload.segment_index}."
                    ),
                    evidence_ids=(WRITE_EXIF_MRW_TTW_EVIDENCE_ID,),
                )
            )
            continue
        if (
            rebuilt_payload.input_offset != matched_handoff.input_payload_range.start_offset
            or rebuilt_payload.input_length != matched_handoff.input_payload_range.length
        ):
            gates.append(
                MinoltaMrwInnerPayloadGate(
                    code="ttw_rebuilt_payload_boundary_mismatch",
                    message=(
                        "TTW rebuilt payload must match the source MinoltaTTW input "
                        "offset and length."
                    ),
                    evidence_ids=(
                        *matched_handoff.evidence_ids,
                        WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
                    ),
                )
            )
            continue
        if not rebuilt_payload.rebuilt_tiff_payload:
            gates.append(
                MinoltaMrwInnerPayloadGate(
                    code="ttw_rebuilt_payload_empty",
                    message="TTW rebuilt TIFF payload must be non-empty.",
                    evidence_ids=(
                        *matched_handoff.evidence_ids,
                        WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
                    ),
                )
            )
            continue
        if not rebuilt_payload.fixup_applied or not rebuilt_payload.ttw_length_verified:
            gates.append(
                MinoltaMrwInnerPayloadGate(
                    code="ttw_fixup_not_confirmed",
                    message=(
                        "TTW rebuilt payload must confirm WriteExif offset fixups and "
                        "MRW TTW length verification."
                    ),
                    evidence_ids=(
                        *matched_handoff.evidence_ids,
                        WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
                    ),
                )
            )
            continue
        rebuilt_length = len(rebuilt_payload.rebuilt_tiff_payload)
        padding_length = mrw_four_byte_padding_length(rebuilt_length)
        steps.append(
            MinoltaMrwTtwMutationStep(
                segment_index=matched_handoff.segment_index,
                input_range=(
                    matched_handoff.input_payload_range.start_offset,
                    matched_handoff.input_payload_range.end_offset,
                ),
                rebuilt_payload_length=rebuilt_length,
                padding_length=padding_length,
                output_payload_length=rebuilt_length + padding_length,
                required_fixups=(
                    "WriteExif MRW TTW data padding",
                    "WriteExif MRW TTW length verification",
                    "WriteExif offset-pointer fixups",
                ),
                evidence_ids=(
                    *matched_handoff.evidence_ids,
                    WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
                ),
            )
        )
    return tuple(steps), tuple(gates)


def build_binary_data_mutation_step(
    data: bytes,
    patch: MinoltaMrwBinaryDataRawPatch,
    fields: tuple[MinoltaMrwBinaryDataFieldSpec, ...],
    segment_plan: MinoltaMrwSegmentRebuildPlan,
) -> tuple[MinoltaMrwBinaryDataMutationStep | None, MinoltaMrwInnerPayloadGate | None]:
    spec = next(
        (field_spec for field_spec in fields if field_spec.tag_name == patch.tag_name), None
    )
    if spec is None:
        return None, MinoltaMrwInnerPayloadGate(
            code="unsupported_binary_tag",
            message=(
                "Minolta MRW BinaryData tag is not in the source-backed raw patch "
                f"surface: {patch.tag_name}."
            ),
            evidence_ids=(
                MINOLTA_RAW_BINARY_EVIDENCE_ID,
                MINOLTA_RAW_WBG_EVIDENCE_ID,
                MINOLTA_RAW_RIF_EVIDENCE_ID,
            ),
        )
    handoff = next(
        (
            binary_handoff
            for binary_handoff in segment_plan.binary_data_handoffs
            if binary_handoff.segment_name == spec.segment_name
        ),
        None,
    )
    if handoff is None:
        return None, MinoltaMrwInnerPayloadGate(
            code="missing_binary_segment",
            message=(
                f"MRW file does not contain the {spec.segment_name} segment required "
                f"for {patch.tag_name}."
            ),
            evidence_ids=spec.evidence_ids,
        )
    if len(patch.raw_payload) != spec.byte_count:
        return None, MinoltaMrwInnerPayloadGate(
            code="binary_payload_size_mismatch",
            message=f"{patch.tag_name} raw payload must be exactly {spec.byte_count} bytes.",
            evidence_ids=spec.evidence_ids,
        )
    start = handoff.input_payload_range.start_offset + spec.offset
    end = start + spec.byte_count
    if end > handoff.input_payload_range.end_offset or end > len(data):
        return None, MinoltaMrwInnerPayloadGate(
            code="binary_payload_range_out_of_bounds",
            message=(
                f"{patch.tag_name} fixed BinaryData range extends beyond the MRW segment payload."
            ),
            evidence_ids=spec.evidence_ids,
        )
    return (
        MinoltaMrwBinaryDataMutationStep(
            segment_index=handoff.segment_index,
            tag_name=patch.tag_name,
            byte_range=(start, end),
            raw_payload=patch.raw_payload,
            evidence_ids=(*spec.evidence_ids, MINOLTA_RAW_WRITE_TEST_EVIDENCE_ID),
        ),
        None,
    )


def build_binary_data_segment_replacements(
    data: bytes,
    steps: tuple[MinoltaMrwBinaryDataMutationStep, ...],
    segment_plan: MinoltaMrwSegmentRebuildPlan,
) -> tuple[MinoltaMrwSegmentReplacement, ...]:
    replacements: list[MinoltaMrwSegmentReplacement] = []
    for handoff in segment_plan.binary_data_handoffs:
        segment_steps = tuple(step for step in steps if step.segment_index == handoff.segment_index)
        if not segment_steps:
            continue
        payload = bytearray(
            data[handoff.input_payload_range.start_offset : handoff.input_payload_range.end_offset]
        )
        for step in segment_steps:
            start = step.byte_range[0] - handoff.input_payload_range.start_offset
            end = step.byte_range[1] - handoff.input_payload_range.start_offset
            payload[start:end] = step.raw_payload
        replacements.append(
            MinoltaMrwSegmentReplacement(
                segment_index=handoff.segment_index,
                writer="binary_data_writer",
                payload=bytes(payload),
            )
        )
    return tuple(replacements)


def build_ttw_segment_replacements(
    rebuilt_payloads: tuple[MinoltaMrwTtwRebuiltPayload, ...],
    steps: tuple[MinoltaMrwTtwMutationStep, ...],
) -> tuple[MinoltaMrwSegmentReplacement, ...]:
    payload_by_index = {
        rebuilt_payload.segment_index: rebuilt_payload for rebuilt_payload in rebuilt_payloads
    }
    replacements: list[MinoltaMrwSegmentReplacement] = []
    for step in steps:
        rebuilt_payload = payload_by_index[step.segment_index]
        replacements.append(
            MinoltaMrwSegmentReplacement(
                segment_index=step.segment_index,
                writer="tiff_writer",
                payload=rebuilt_payload.rebuilt_tiff_payload,
            )
        )
    return tuple(replacements)


def binary_data_blocker_codes() -> tuple[MinoltaMrwInnerPayloadGateCode, ...]:
    return (
        "unsupported_binary_tag",
        "missing_binary_segment",
        "binary_payload_size_mismatch",
        "binary_payload_range_out_of_bounds",
    )


def ttw_blocker_codes() -> tuple[MinoltaMrwInnerPayloadGateCode, ...]:
    return (
        "ttw_rebuilt_payload_boundary_mismatch",
        "ttw_rebuilt_payload_empty",
        "ttw_fixup_not_confirmed",
    )


def blocker_codes() -> tuple[MinoltaMrwInnerPayloadGateCode, ...]:
    return (*binary_data_blocker_codes(), *ttw_blocker_codes())


def unique_gates(
    gates: tuple[MinoltaMrwInnerPayloadGate, ...],
) -> tuple[MinoltaMrwInnerPayloadGate, ...]:
    unique: list[MinoltaMrwInnerPayloadGate] = []
    for gate in gates:
        if gate not in unique:
            unique.append(gate)
    return tuple(unique)


def inner_payload_evidence_ids(
    fields: tuple[MinoltaMrwBinaryDataFieldSpec, ...],
    gates: tuple[MinoltaMrwInnerPayloadGate, ...],
    ttw_steps: tuple[MinoltaMrwTtwMutationStep, ...],
    steps: tuple[MinoltaMrwBinaryDataMutationStep, ...],
) -> tuple[str, ...]:
    return unique_evidence_ids(
        (
            MINOLTA_RAW_WRITE_TEST_EVIDENCE_ID,
            MINOLTA_RAW_MRW_OUTPUT_EVIDENCE_ID,
            *(evidence_id for field_spec in fields for evidence_id in field_spec.evidence_ids),
            *(evidence_id for gate in gates for evidence_id in gate.evidence_ids),
            *(evidence_id for step in ttw_steps for evidence_id in step.evidence_ids),
            *(evidence_id for step in steps for evidence_id in step.evidence_ids),
        )
    )


def whole_container_emission_plan(
    status: MinoltaMrwWholeContainerEmissionStatus,
    output_bytes: bytes | None,
    inner_payload_plan: MinoltaMrwInnerPayloadMutationPlan,
    segment_rebuild_plan: MinoltaMrwSegmentRebuildPlan,
    gates: tuple[MinoltaMrwInnerPayloadGate, ...],
) -> MinoltaMrwWholeContainerEmissionPlan:
    unique_gate_tuple = unique_gates(gates)
    return MinoltaMrwWholeContainerEmissionPlan(
        status=status,
        can_emit=output_bytes is not None,
        output_bytes=output_bytes,
        inner_payload_plan=inner_payload_plan,
        segment_rebuild_plan=segment_rebuild_plan,
        gates=unique_gate_tuple,
        evidence_ids=whole_container_emission_evidence_ids(
            inner_payload_plan,
            segment_rebuild_plan,
            unique_gate_tuple,
        ),
    )


def whole_container_emission_evidence_ids(
    inner_payload_plan: MinoltaMrwInnerPayloadMutationPlan,
    segment_rebuild_plan: MinoltaMrwSegmentRebuildPlan,
    gates: tuple[MinoltaMrwInnerPayloadGate, ...],
) -> tuple[str, ...]:
    return unique_evidence_ids(
        (
            MINOLTA_RAW_WRITE_EVIDENCE_ID,
            WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
            MINOLTA_RAW_WRITE_TEST_EVIDENCE_ID,
            *inner_payload_plan.evidence_ids,
            *segment_rebuild_plan.evidence_ids,
            *(evidence_id for gate in gates for evidence_id in gate.evidence_ids),
        )
    )
