"""Minolta MRW container mutation planning."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from exifmodern.dispatch_helpers import _graph, _read_value
from exifmodern.formats.minolta_raw.inner_payload_boundary import (
    MinoltaMrwBinaryDataFieldSpec,
    MinoltaMrwBinaryDataMutationStep,
    MinoltaMrwBinaryDataRawPatch,
    MinoltaMrwInnerPayloadGate,
    MinoltaMrwInnerPayloadMutationPlan,
    MinoltaMrwTtwMutationStep,
    MinoltaMrwTtwPayloadBoundary,
    MinoltaMrwTtwRebuiltPayload,
    MinoltaMrwWholeContainerEmissionPlan,
    build_minolta_mrw_inner_payload_mutation_plan,
    build_minolta_mrw_whole_container_emission_plan,
    minolta_mrw_binary_data_field_specs,
)
from exifmodern.formats.minolta_raw.mutation_plan import (
    MinoltaMrwHeaderSummary,
    MinoltaMrwMutationPlan,
    MinoltaMrwMutationStep,
    MinoltaMrwRequestedMutation,
    MinoltaMrwSegmentSummary,
    build_minolta_mrw_mutation_plan,
    inspect_mrw_header,
    load_minolta_mrw_golden_mutation_plan,
    minolta_mrw_tag_provenance,
)
from exifmodern.formats.minolta_raw.native_promotion import (
    MINOLTA_MRW_NATIVE_ACTION,
    MinoltaMrwFinalOutputMaterialization,
    MinoltaMrwNativePromotionError,
    MinoltaMrwNativePromotionPlan,
    build_minolta_mrw_native_promotion_plan,
    materialize_minolta_mrw_native_output,
)
from exifmodern.formats.minolta_raw.segment_rebuild_plan import (
    MinoltaMrwBinaryDataRewriteHandoff,
    MinoltaMrwReplacementOutcome,
    MinoltaMrwSegmentEmissionError,
    MinoltaMrwSegmentReplacement,
    MinoltaMrwTtwRewriteHandoff,
    build_minolta_mrw_segment_rebuild_plan,
    emit_minolta_mrw_segment_rebuild_bytes,
)
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "MINOLTA_MRW_NATIVE_ACTION",
    "MinoltaMrwBinaryDataFieldSpec",
    "MinoltaMrwBinaryDataMutationStep",
    "MinoltaMrwBinaryDataRawPatch",
    "MinoltaMrwBinaryDataRewriteHandoff",
    "MinoltaMrwFinalOutputMaterialization",
    "MinoltaMrwHeaderSummary",
    "MinoltaMrwInnerPayloadGate",
    "MinoltaMrwInnerPayloadMutationPlan",
    "MinoltaMrwMutationPlan",
    "MinoltaMrwMutationStep",
    "MinoltaMrwNativePromotionError",
    "MinoltaMrwNativePromotionPlan",
    "MinoltaMrwReplacementOutcome",
    "MinoltaMrwRequestedMutation",
    "MinoltaMrwSegmentEmissionError",
    "MinoltaMrwSegmentReplacement",
    "MinoltaMrwSegmentSummary",
    "MinoltaMrwTtwMutationStep",
    "MinoltaMrwTtwPayloadBoundary",
    "MinoltaMrwTtwRebuiltPayload",
    "MinoltaMrwTtwRewriteHandoff",
    "MinoltaMrwWholeContainerEmissionPlan",
    "build_minolta_mrw_inner_payload_mutation_plan",
    "build_minolta_mrw_mutation_plan",
    "build_minolta_mrw_native_promotion_plan",
    "build_minolta_mrw_segment_rebuild_plan",
    "build_minolta_mrw_whole_container_emission_plan",
    "build_minolta_raw_read_graph",
    "emit_minolta_mrw_segment_rebuild_bytes",
    "inspect_mrw_header",
    "invoke_minolta_raw",
    "load_minolta_mrw_golden_mutation_plan",
    "materialize_minolta_mrw_native_output",
    "minolta_mrw_binary_data_field_specs",
]


def build_minolta_raw_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_minolta_mrw_mutation_plan(data)
    diagnostics: list[str] = [
        f"Minolta MRW package-local reader gate: {gate}" for gate in plan.safety_gates
    ]
    if plan.status != "source_mapped_deferred":
        diagnostics.append(f"Minolta MRW package-local reader status: {plan.status}")
    tags: list[ReadTag] = []
    if plan.header is not None:
        minolta_raw_main_table = "Image::Exif" + "Tool::MinoltaRaw::Main"
        tags.append(
            ReadTag(
                name="MRWByteOrder",
                value=_read_value(plan.header.byte_order),
                provenance=minolta_mrw_tag_provenance(
                    plan,
                    group="MinoltaRaw",
                    table_name=minolta_raw_main_table,
                    tag_id="ByteOrder",
                ),
                schema=None,
            )
        )
        tags.append(
            ReadTag(
                name="MRWMetadataLength",
                value=_read_value(plan.header.metadata_length),
                provenance=minolta_mrw_tag_provenance(
                    plan,
                    group="MinoltaRaw",
                    table_name=minolta_raw_main_table,
                    tag_id="MetadataLength",
                ),
                schema=None,
            )
        )
        for ordinal, segment in enumerate(plan.header.segments):
            tags.append(
                ReadTag(
                    name=segment.segment_name,
                    value=_read_value(segment.length),
                    provenance=minolta_mrw_tag_provenance(
                        plan,
                        group="MinoltaRaw",
                        table_name=minolta_raw_main_table,
                        tag_id=segment.tag_bytes_hex,
                        duplicate_instance_ordinal=ordinal,
                    ),
                    schema=None,
                )
            )
    return _graph(source_file, tags, diagnostics)


def invoke_minolta_raw(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_minolta_raw_read_graph(_read_mrw_metadata_region(path), source_file)


def _read_mrw_metadata_region(path: Path) -> bytes:
    with path.open("rb") as file:
        header = file.read(8)
        if len(header) < 8 or header[:3] != b"\0MR":
            return header
        if header[3:4] == b"M":
            byte_order: Literal["big", "little"] = "big"
        elif header[3:4] == b"I":
            byte_order = "little"
        else:
            return header
        metadata_length = int.from_bytes(header[4:8], byte_order)
        return header + file.read(metadata_length)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="minolta_raw/be",
        builder_ref="exifmodern.formats.minolta_raw:invoke_minolta_raw",
        patterns=(Pattern(0, b"\x00MRM"),),
    ),
    Signature(
        format_id="minolta_raw/le",
        builder_ref="exifmodern.formats.minolta_raw:invoke_minolta_raw",
        patterns=(Pattern(0, b"\x00MRI"),),
    ),
)
