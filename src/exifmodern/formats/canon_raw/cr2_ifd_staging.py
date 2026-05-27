"""CR2 TIFF IFD mutation staging.

This module bridges Canon RAW CR2 planning to the shared TIFF directory
transaction planner.  It parses the CR2 TIFF IFD graph and stages safe
directory-layout work, but it does not emit CR2 bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan, build_exif_scalar_write_plan
from exifmodern.formats.canon_raw.cr2_mutation_plan import (
    CANON_RAW_CR2_SUFFIX_TEST_SOURCE,
    WRITE_EXIF_IMAGE_DATA_SOURCE,
    WRITE_EXIF_LAST_IFD_SOURCE,
    inspect_cr2_tiff_header,
    unique_sources,
)
from exifmodern.formats.canon_raw.write_plan import (
    CANON_FOCAL_PLANE_X_SIZE_SOURCE,
    CANON_OWNER_NAME_SOURCE,
    CR2_IPTC_DIRECTORY_SOURCE,
    EXIF_OWNER_NAME_SOURCE,
    IPTC_KEYWORDS_SOURCE,
    WRITE_CR2_SOURCE,
    CanonRawWriteRequestClassification,
    CanonRawWriteSurface,
    evidence_id_to_json,
)
from exifmodern.formats.iptc.dataset_writer import apply_iptc_application_write_plan
from exifmodern.formats.iptc.write_plan import build_iptc_application_write_plan
from exifmodern.formats.tiff.directory_transaction_plan import (
    TiffDirectoryInput,
    TiffDirectoryRebuildPlan,
    TiffDirectoryTransactionPlan,
    TiffEntryLayoutPlan,
    TiffEntryValueStorage,
    build_tiff_directory_rebuild_plan,
    build_tiff_directory_transaction_plan,
)
from exifmodern.formats.tiff.mutation import (
    RawTiffDirectory,
    RawTiffEntry,
    inline_u32,
    raw_directory,
)
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_LONG,
    TIFF_TYPE_SHORT,
    Endian,
    Ifd,
    parse_ifd,
    parse_tiff_header,
)
from exifmodern.json_types import JsonArray, JsonObject

type EvidenceId = str

type Cr2TiffIfdStageStatus = Literal[
    "ready",
    "unsupported_header",
    "tiff_parse_error",
    "missing_exif_ifd_for_scalar",
]
type Cr2TiffIfdDirectoryName = Literal["IFD0", "ExifIFD", "IFD1"]
type Cr2TiffIfdSurfaceStageCode = Literal[
    "staged_exif_scalar_directory_entry",
    "deferred_iptc_subdirectory_payload",
    "deferred_canon_makernote_codec",
]
type Cr2TiffIfdStageBlockerCode = Literal[
    "no_byte_mutation_from_ifd_stage",
    "requires_embedded_iptc_writer",
    "requires_canon_makernote_codec",
    "requires_image_data_copy_engine",
    "requires_cr2_header_last_ifd_fixup",
]
type Cr2IptcPayloadStageStatus = Literal[
    "ready",
    "unsupported_header",
    "tiff_parse_error",
    "no_keywords_requested",
    "invalid_iptc_value",
]
type Cr2IptcNaaRelayoutStatus = Literal[
    "ready",
    "unsupported_header",
    "tiff_parse_error",
    "no_keywords_requested",
    "invalid_iptc_value",
    "missing_staged_payload",
]
type Cr2CanonMakerNotePrerequisiteStatus = Literal[
    "ready",
    "unsupported_header",
    "tiff_parse_error",
    "no_makernote_tags_requested",
    "missing_exif_ifd",
    "missing_existing_makernote",
    "focal_plane_model_condition_unproven",
    "invalid_focal_plane_value",
]
type Cr2CanonMakerNotePrerequisiteCode = Literal[
    "locate_existing_makernote_ifd",
    "preserve_makernote_directory_identity",
    "owner_name_valueconv_padding",
    "focal_plane_model_condition",
    "focal_plane_valueconv_integer",
    "defer_binary_ifd_emission",
]
type Cr2CanonMakerNoteBinaryCodecStatus = Literal[
    "ready",
    "prerequisite_blocked",
    "unsupported_header",
    "tiff_parse_error",
    "no_makernote_tags_requested",
]
type Cr2CanonMakerNoteBinaryFieldCode = Literal[
    "owner_name_ifd_entry",
    "focal_plane_x_size_binary_element",
]

EXIF_IFD_POINTER_TAG = 0x8769
IPTC_NAA_TAG = 0x83BB
MAKER_NOTE_TAG = 0x927C

WRITE_EXIF_TAG_MERGE_SOURCE = "canon_raw.write_exif_tag_merge"
WRITE_EXIF_IFD_LOAD_SOURCE = "canon_raw.write_exif_ifd_load"
WRITE_IPTC_DATASET_ORDER_SOURCE = "canon_raw.write_iptc_dataset_order"
WRITE_EXIF_IPTC_NAA_RELAYOUT_SOURCE = "canon_raw.write_exif_iptc_naa_relayout"
WRITE_EXIF_DIRECTORY_VALUE_AREA_SOURCE = "canon_raw.write_exif_directory_value_area"
WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE = "canon_raw.write_exif_makernote_rewrite"
WRITE_EXIF_MAKERNOTE_SUBIFD_SOURCE = "canon_raw.write_exif_makernote_subifd"
WRITE_CANON_RAW_BUILD_MAKERNOTES_SOURCE = "canon_raw.write_canon_raw_build_makernotes"
WRITE_CANON_RAW_SAVE_MAKERNOTES_SOURCE = "canon_raw.write_canon_raw_save_makernotes"
CANON_FOCAL_LENGTH_BINARY_SOURCE = "canon_raw.canon_focal_length_binary"


@dataclass(frozen=True)
class Cr2TiffIfdDirectoryStage:
    name: Cr2TiffIfdDirectoryName
    original_offset: int
    entry_count: int
    next_ifd_offset: int
    tag_ids: tuple[int, ...]

    def to_json(self) -> JsonObject:
        return {
            "entry_count": self.entry_count,
            "name": self.name,
            "next_ifd_offset": self.next_ifd_offset,
            "original_offset": self.original_offset,
            "tag_ids": [tag_id_hex(tag_id) for tag_id in self.tag_ids],
        }


@dataclass(frozen=True)
class Cr2TiffIfdSurfaceStage:
    code: Cr2TiffIfdSurfaceStageCode
    surface: CanonRawWriteSurface
    requested_tags: tuple[str, ...]
    directory_name: Cr2TiffIfdDirectoryName | None
    source_tag_ids: tuple[int, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def ready_for_directory_layout(self) -> bool:
        return self.code == "staged_exif_scalar_directory_entry"

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "directory_name": self.directory_name,
            "ready_for_directory_layout": self.ready_for_directory_layout,
            "requested_tags": list(self.requested_tags),
            "source_tag_ids": [tag_id_hex(tag_id) for tag_id in self.source_tag_ids],
            "surface": self.surface,
        }


@dataclass(frozen=True)
class Cr2TiffIfdStageBlocker:
    code: Cr2TiffIfdStageBlockerCode
    surfaces: tuple[CanonRawWriteSurface, ...]
    reason: str
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def blocks_mutation(self) -> bool:
        return True

    def to_json(self) -> JsonObject:
        return {
            "blocks_mutation": self.blocks_mutation,
            "code": self.code,
            "reason": self.reason,
            "surfaces": list(self.surfaces),
        }


@dataclass(frozen=True)
class Cr2TiffIfdMutationStage:
    status: Cr2TiffIfdStageStatus
    requested_tags: tuple[str, ...]
    endian: Endian | None
    ifd0_offset: int | None
    directories: tuple[Cr2TiffIfdDirectoryStage, ...]
    surface_stages: tuple[Cr2TiffIfdSurfaceStage, ...]
    blockers: tuple[Cr2TiffIfdStageBlocker, ...]
    transaction_plan: TiffDirectoryTransactionPlan | None
    parse_error: str | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def blocked_gate_count(self) -> int:
        return sum(blocker.blocks_mutation for blocker in self.blockers)

    def to_json(self) -> JsonObject:
        return {
            "blocked_gate_count": self.blocked_gate_count,
            "blockers": [blocker.to_json() for blocker in self.blockers],
            "can_mutate_bytes": self.can_mutate_bytes,
            "directories": [directory.to_json() for directory in self.directories],
            "endian": self.endian,
            "ifd0_offset": self.ifd0_offset,
            "parse_error": self.parse_error,
            "requested_tags": list(self.requested_tags),
            "status": self.status,
            "surface_stages": [stage.to_json() for stage in self.surface_stages],
            "transaction_plan": (
                self.transaction_plan.to_json() if self.transaction_plan is not None else None
            ),
        }


@dataclass(frozen=True)
class Cr2IptcPayloadStage:
    status: Cr2IptcPayloadStageStatus
    requested_keywords: tuple[str, ...]
    original_payload: bytes
    staged_payload: bytes | None
    tiff_entry_tag_id: int
    tiff_entry_field_type: int
    tiff_entry_count: int | None
    tiff_entry_padding_byte_count: int
    parse_error: str | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_stage_directory_entry(self) -> bool:
        return self.status == "ready"

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    def to_json(self) -> JsonObject:
        return {
            "can_mutate_bytes": self.can_mutate_bytes,
            "can_stage_directory_entry": self.can_stage_directory_entry,
            "original_payload_byte_count": len(self.original_payload),
            "parse_error": self.parse_error,
            "requested_keywords": list(self.requested_keywords),
            "staged_payload_byte_count": (
                len(self.staged_payload) if self.staged_payload is not None else None
            ),
            "status": self.status,
            "tiff_entry_count": self.tiff_entry_count,
            "tiff_entry_field_type": self.tiff_entry_field_type,
            "tiff_entry_padding_byte_count": self.tiff_entry_padding_byte_count,
            "tiff_entry_tag_id": tag_id_hex(self.tiff_entry_tag_id),
        }


@dataclass(frozen=True)
class Cr2IptcNaaRelayoutPlan:
    status: Cr2IptcNaaRelayoutStatus
    payload_stage: Cr2IptcPayloadStage
    directory_name: Cr2TiffIfdDirectoryName | None
    original_entry_present: bool
    original_entry_count: int | None
    planned_entry_index: int | None
    planned_entry_field_type: int
    planned_entry_count: int | None
    staged_payload_byte_count: int | None
    padded_value_byte_count: int | None
    padding_byte_count: int
    value_storage: TiffEntryValueStorage | None
    value_field_offset: int | None
    planned_value_offset: int | None
    materialized_entry: Cr2IptcNaaMaterializedEntry | None
    directory_entry_count_before: int | None
    directory_entry_count_after: int | None
    directory_rebuild_plan: TiffDirectoryRebuildPlan | None
    parse_error: str | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_stage_directory_entry(self) -> bool:
        return self.status == "ready"

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    def to_json(self) -> JsonObject:
        return {
            "can_mutate_bytes": self.can_mutate_bytes,
            "can_stage_directory_entry": self.can_stage_directory_entry,
            "directory_entry_count_after": self.directory_entry_count_after,
            "directory_entry_count_before": self.directory_entry_count_before,
            "directory_name": self.directory_name,
            "directory_rebuild_plan": (
                self.directory_rebuild_plan.to_json()
                if self.directory_rebuild_plan is not None
                else None
            ),
            "original_entry_count": self.original_entry_count,
            "original_entry_present": self.original_entry_present,
            "padding_byte_count": self.padding_byte_count,
            "parse_error": self.parse_error,
            "padded_value_byte_count": self.padded_value_byte_count,
            "payload_stage": self.payload_stage.to_json(),
            "planned_entry_count": self.planned_entry_count,
            "planned_entry_field_type": self.planned_entry_field_type,
            "planned_entry_index": self.planned_entry_index,
            "planned_value_offset": self.planned_value_offset,
            "materialized_entry": (
                self.materialized_entry.to_json() if self.materialized_entry is not None else None
            ),
            "staged_payload_byte_count": self.staged_payload_byte_count,
            "status": self.status,
            "value_field_offset": self.value_field_offset,
            "value_storage": self.value_storage,
        }


@dataclass(frozen=True)
class Cr2IptcNaaMaterializedEntry:
    tag_id: int
    field_type: int
    count: int
    value_offset: int
    directory_entry_bytes: bytes
    value_data_bytes: bytes
    padding_byte_count: int
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_feed_directory_emitter(self) -> bool:
        return True

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    def to_json(self) -> JsonObject:
        return {
            "can_feed_directory_emitter": self.can_feed_directory_emitter,
            "can_mutate_bytes": self.can_mutate_bytes,
            "count": self.count,
            "directory_entry_hex": self.directory_entry_bytes.hex(),
            "field_type": self.field_type,
            "padding_byte_count": self.padding_byte_count,
            "tag_id": tag_id_hex(self.tag_id),
            "value_data_hex": self.value_data_bytes.hex(),
            "value_offset": self.value_offset,
        }


@dataclass(frozen=True)
class Cr2CanonMakerNotePrerequisite:
    code: Cr2CanonMakerNotePrerequisiteCode
    requested_tag: str | None
    planned_value: str | int | None
    requirement: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "planned_value": self.planned_value,
            "requested_tag": self.requested_tag,
            "requirement": self.requirement,
        }


@dataclass(frozen=True)
class Cr2CanonMakerNotePrerequisiteLedger:
    status: Cr2CanonMakerNotePrerequisiteStatus
    requested_tags: tuple[str, ...]
    maker_note_directory_name: Cr2TiffIfdDirectoryName | None
    maker_note_tag_id: int
    existing_makernote_present: bool
    prerequisites: tuple[Cr2CanonMakerNotePrerequisite, ...]
    blocked_prerequisite_codes: tuple[Cr2CanonMakerNotePrerequisiteCode, ...]
    parse_error: str | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def blocks_binary_codec(self) -> bool:
        return bool(self.blocked_prerequisite_codes)

    def to_json(self) -> JsonObject:
        return {
            "blocked_prerequisite_codes": list(self.blocked_prerequisite_codes),
            "blocks_binary_codec": self.blocks_binary_codec,
            "can_mutate_bytes": self.can_mutate_bytes,
            "existing_makernote_present": self.existing_makernote_present,
            "maker_note_directory_name": self.maker_note_directory_name,
            "maker_note_tag_id": tag_id_hex(self.maker_note_tag_id),
            "parse_error": self.parse_error,
            "prerequisites": [prerequisite.to_json() for prerequisite in self.prerequisites],
            "requested_tags": list(self.requested_tags),
            "status": self.status,
        }


@dataclass(frozen=True)
class Cr2CanonMakerNoteBinaryField:
    code: Cr2CanonMakerNoteBinaryFieldCode
    requested_tag: str
    canon_tag_id: int
    field_type: int
    count: int
    value_bytes: bytes
    directory_entry_bytes: bytes | None
    value_data_bytes: bytes
    value_offset: int | None
    fixup_offset: int | None
    binary_element_index: int | None
    binary_element_byte_offset: int | None
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "binary_element_byte_offset": self.binary_element_byte_offset,
            "binary_element_index": self.binary_element_index,
            "canon_tag_id": tag_id_hex(self.canon_tag_id),
            "code": self.code,
            "count": self.count,
            "directory_entry_hex": (
                self.directory_entry_bytes.hex() if self.directory_entry_bytes is not None else None
            ),
            "field_type": self.field_type,
            "fixup_offset": self.fixup_offset,
            "requested_tag": self.requested_tag,
            "value_bytes_hex": self.value_bytes.hex(),
            "value_data_hex": self.value_data_bytes.hex(),
            "value_offset": self.value_offset,
        }


@dataclass(frozen=True)
class Cr2CanonMakerNoteBinaryCodecPlan:
    status: Cr2CanonMakerNoteBinaryCodecStatus
    prerequisite_ledger: Cr2CanonMakerNotePrerequisiteLedger
    inferred_model: str | None
    materialized_fields: tuple[Cr2CanonMakerNoteBinaryField, ...]
    partial_makernote_bytes: bytes | None
    value_buffer_bytes: bytes | None
    fixup_offsets: tuple[int, ...]
    parse_error: str | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_feed_makernote_rewriter(self) -> bool:
        return self.status == "ready"

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    def to_json(self) -> JsonObject:
        return {
            "can_feed_makernote_rewriter": self.can_feed_makernote_rewriter,
            "can_mutate_bytes": self.can_mutate_bytes,
            "fields": [field.to_json() for field in self.materialized_fields],
            "fixup_offsets": list(self.fixup_offsets),
            "inferred_model": self.inferred_model,
            "parse_error": self.parse_error,
            "partial_makernote_hex": (
                self.partial_makernote_bytes.hex()
                if self.partial_makernote_bytes is not None
                else None
            ),
            "prerequisite_ledger": self.prerequisite_ledger.to_json(),
            "status": self.status,
            "value_buffer_hex": (
                self.value_buffer_bytes.hex() if self.value_buffer_bytes is not None else None
            ),
        }


@dataclass(frozen=True)
class Cr2ParsedIfdGraph:
    endian: Endian
    ifd0: Ifd
    ifd0_directory: RawTiffDirectory
    exif_ifd: Ifd | None
    exif_directory: RawTiffDirectory | None
    ifd1: Ifd | None
    ifd1_directory: RawTiffDirectory | None


def stage_cr2_tiff_ifd_mutation(
    data: bytes,
    classification: CanonRawWriteRequestClassification | None = None,
) -> Cr2TiffIfdMutationStage:
    inspection = inspect_cr2_tiff_header(data[:16])
    requested_tags = requested_tag_names(classification)
    if not inspection.recognized:
        return blocked_stage(
            "unsupported_header",
            requested_tags,
            None,
            inspection.ifd0_offset,
            (),
            (),
            "CR2 IFD staging requires the WriteCR2 signature gate.",
            None,
            (WRITE_CR2_SOURCE,),
        )
    try:
        graph = parse_cr2_ifd_graph(data)
    except ValueError as exc:
        return blocked_stage(
            "tiff_parse_error",
            requested_tags,
            tiff_endian_from_cr2_byte_order(inspection.byte_order),
            inspection.ifd0_offset,
            (),
            (),
            "CR2 IFD staging requires complete TIFF directory tables.",
            str(exc),
            (WRITE_CR2_SOURCE, WRITE_EXIF_IFD_LOAD_SOURCE),
        )

    exif_scalar_plan = build_cr2_exif_scalar_stage_plan(classification)
    if exif_scalar_plan is not None and graph.exif_directory is None:
        return blocked_stage(
            "missing_exif_ifd_for_scalar",
            requested_tags,
            graph.endian,
            graph.ifd0.offset,
            directory_stages_from_graph(graph),
            surface_stages_from_graph(graph, classification, exif_scalar_plan),
            "OwnerName staging requires the existing ExifIFD pointer before CR2 emit.",
            None,
            (WRITE_EXIF_TAG_MERGE_SOURCE, EXIF_OWNER_NAME_SOURCE),
        )

    directory_inputs = tiff_directory_inputs_from_graph(graph)
    transaction_plan = build_tiff_directory_transaction_plan(
        directory_inputs,
        endian=graph.endian,
        container_kind="cr2",
        scalar_write_plan=exif_scalar_plan,
    )
    return Cr2TiffIfdMutationStage(
        status="ready",
        requested_tags=requested_tags,
        endian=graph.endian,
        ifd0_offset=graph.ifd0.offset,
        directories=directory_stages_from_graph(graph),
        surface_stages=surface_stages_from_graph(graph, classification, exif_scalar_plan),
        blockers=CR2_TIFF_IFD_STAGE_BLOCKERS,
        transaction_plan=transaction_plan,
        parse_error=None,
        evidence_ids=unique_sources(
            (
                WRITE_CR2_SOURCE,
                WRITE_EXIF_IFD_LOAD_SOURCE,
                WRITE_EXIF_TAG_MERGE_SOURCE,
                EXIF_OWNER_NAME_SOURCE,
                CR2_IPTC_DIRECTORY_SOURCE,
                IPTC_KEYWORDS_SOURCE,
                CANON_OWNER_NAME_SOURCE,
                CANON_FOCAL_PLANE_X_SIZE_SOURCE,
                WRITE_EXIF_IMAGE_DATA_SOURCE,
                WRITE_EXIF_LAST_IFD_SOURCE,
                CANON_RAW_CR2_SUFFIX_TEST_SOURCE,
                *transaction_plan.evidence_ids,
            )
        ),
    )


def stage_cr2_iptc_naa_payload(
    data: bytes,
    classification: CanonRawWriteRequestClassification | None,
) -> Cr2IptcPayloadStage:
    requested_keywords = requested_values_for_tag(classification, "Keywords")
    if not requested_keywords:
        return cr2_iptc_payload_stage(
            "no_keywords_requested",
            (),
            b"",
            None,
            None,
            0,
            None,
            (CR2_IPTC_DIRECTORY_SOURCE, IPTC_KEYWORDS_SOURCE),
        )

    inspection = inspect_cr2_tiff_header(data[:16])
    if not inspection.recognized:
        return cr2_iptc_payload_stage(
            "unsupported_header",
            requested_keywords,
            b"",
            None,
            None,
            0,
            None,
            (WRITE_CR2_SOURCE, CR2_IPTC_DIRECTORY_SOURCE, IPTC_KEYWORDS_SOURCE),
        )

    try:
        graph = parse_cr2_ifd_graph(data)
    except ValueError as exc:
        return cr2_iptc_payload_stage(
            "tiff_parse_error",
            requested_keywords,
            b"",
            None,
            None,
            0,
            str(exc),
            (WRITE_CR2_SOURCE, WRITE_EXIF_IFD_LOAD_SOURCE, CR2_IPTC_DIRECTORY_SOURCE),
        )

    original_entry = raw_entry_by_tag_id(graph.ifd0_directory, IPTC_NAA_TAG)
    original_payload = b"" if original_entry is None else original_entry.raw_value
    try:
        plan = build_iptc_application_write_plan(keywords=requested_keywords)
        staged_payload = apply_iptc_application_write_plan(original_payload, plan)
    except ValueError as exc:
        return cr2_iptc_payload_stage(
            "invalid_iptc_value",
            requested_keywords,
            original_payload,
            None,
            None,
            0,
            str(exc),
            (IPTC_KEYWORDS_SOURCE, WRITE_IPTC_DATASET_ORDER_SOURCE),
        )

    padding_byte_count = padding_to_4_byte_boundary(len(staged_payload))
    return cr2_iptc_payload_stage(
        "ready",
        requested_keywords,
        original_payload,
        staged_payload,
        (len(staged_payload) + padding_byte_count) // 4,
        padding_byte_count,
        None,
        unique_sources(
            (
                WRITE_CR2_SOURCE,
                CR2_IPTC_DIRECTORY_SOURCE,
                IPTC_KEYWORDS_SOURCE,
                WRITE_IPTC_DATASET_ORDER_SOURCE,
                *(evidence_id for step in plan.steps for evidence_id in step.evidence_ids),
            )
        ),
    )


def plan_cr2_iptc_naa_relayout(
    data: bytes,
    classification: CanonRawWriteRequestClassification | None,
) -> Cr2IptcNaaRelayoutPlan:
    payload_stage = stage_cr2_iptc_naa_payload(data, classification)
    if not payload_stage.can_stage_directory_entry:
        return cr2_iptc_naa_relayout_plan(
            payload_stage.status,
            payload_stage,
            None,
            False,
            None,
            None,
            None,
            None,
            None,
            payload_stage.tiff_entry_padding_byte_count,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            payload_stage.parse_error,
            payload_stage.evidence_ids,
        )
    if payload_stage.staged_payload is None or payload_stage.tiff_entry_count is None:
        return cr2_iptc_naa_relayout_plan(
            "missing_staged_payload",
            payload_stage,
            None,
            False,
            None,
            None,
            None,
            None,
            None,
            payload_stage.tiff_entry_padding_byte_count,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "IPTC payload stage reported ready without payload bytes.",
            payload_stage.evidence_ids,
        )

    try:
        graph = parse_cr2_ifd_graph(data)
    except ValueError as exc:
        return cr2_iptc_naa_relayout_plan(
            "tiff_parse_error",
            payload_stage,
            None,
            False,
            None,
            None,
            None,
            None,
            None,
            payload_stage.tiff_entry_padding_byte_count,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            str(exc),
            (WRITE_CR2_SOURCE, WRITE_EXIF_IFD_LOAD_SOURCE, CR2_IPTC_DIRECTORY_SOURCE),
        )

    original_entry = raw_entry_by_tag_id(graph.ifd0_directory, IPTC_NAA_TAG)
    padded_payload = payload_stage.staged_payload + (
        b"\x00" * payload_stage.tiff_entry_padding_byte_count
    )
    planned_entry = RawTiffEntry(
        tag_id=IPTC_NAA_TAG,
        field_type=TIFF_TYPE_LONG,
        count=payload_stage.tiff_entry_count,
        raw_value=padded_payload,
    )
    planned_ifd0 = replace(
        graph.ifd0_directory,
        entries=upsert_raw_tiff_entry(graph.ifd0_directory.entries, planned_entry),
    )
    directory_rebuild_plan = build_tiff_directory_rebuild_plan(
        planned_ifd0,
        directory_name="IFD0",
        endian=graph.endian,
        container_kind="cr2",
        directory_start=graph.ifd0.offset,
    )
    layout = next(
        entry for entry in directory_rebuild_plan.ordered_entries if entry.tag_id == IPTC_NAA_TAG
    )
    materialized_entry = materialize_cr2_iptc_naa_entry(
        layout,
        padded_payload,
        graph.endian,
        payload_stage.tiff_entry_padding_byte_count,
    )
    return cr2_iptc_naa_relayout_plan(
        "ready",
        payload_stage,
        "IFD0",
        original_entry is not None,
        original_entry.count if original_entry is not None else None,
        layout.index,
        layout.count,
        len(payload_stage.staged_payload),
        len(padded_payload),
        payload_stage.tiff_entry_padding_byte_count,
        layout.value_storage,
        layout.value_field_offset,
        layout.planned_value_offset,
        materialized_entry,
        len(graph.ifd0_directory.entries),
        len(directory_rebuild_plan.planned_directory.entries),
        directory_rebuild_plan,
        None,
        unique_sources(
            (
                *payload_stage.evidence_ids,
                WRITE_EXIF_IPTC_NAA_RELAYOUT_SOURCE,
                WRITE_EXIF_DIRECTORY_VALUE_AREA_SOURCE,
                *materialized_entry.evidence_ids,
                *directory_rebuild_plan.evidence_ids,
            )
        ),
    )


def build_cr2_canon_makernote_prerequisite_ledger(
    data: bytes,
    classification: CanonRawWriteRequestClassification | None,
    *,
    model: str | None = None,
) -> Cr2CanonMakerNotePrerequisiteLedger:
    requested_tags = requested_makernote_tag_names(classification)
    if not requested_tags:
        return cr2_canon_makernote_prerequisite_ledger(
            "no_makernote_tags_requested",
            (),
            None,
            False,
            (),
            (),
            None,
            (CANON_OWNER_NAME_SOURCE, CANON_FOCAL_PLANE_X_SIZE_SOURCE),
        )

    inspection = inspect_cr2_tiff_header(data[:16])
    if not inspection.recognized:
        return cr2_canon_makernote_prerequisite_ledger(
            "unsupported_header",
            requested_tags,
            None,
            False,
            (),
            ("locate_existing_makernote_ifd",),
            None,
            (WRITE_CR2_SOURCE, WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE),
        )

    try:
        graph = parse_cr2_ifd_graph(data)
    except ValueError as exc:
        return cr2_canon_makernote_prerequisite_ledger(
            "tiff_parse_error",
            requested_tags,
            None,
            False,
            (),
            ("locate_existing_makernote_ifd",),
            str(exc),
            (WRITE_CR2_SOURCE, WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE),
        )

    if graph.exif_directory is None:
        return cr2_canon_makernote_prerequisite_ledger(
            "missing_exif_ifd",
            requested_tags,
            None,
            False,
            (),
            ("locate_existing_makernote_ifd",),
            None,
            (WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,),
        )

    maker_note_entry = raw_entry_by_tag_id(graph.exif_directory, MAKER_NOTE_TAG)
    if maker_note_entry is None:
        return cr2_canon_makernote_prerequisite_ledger(
            "missing_existing_makernote",
            requested_tags,
            "ExifIFD",
            False,
            (),
            ("locate_existing_makernote_ifd",),
            None,
            (WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,),
        )

    prerequisites: list[Cr2CanonMakerNotePrerequisite] = [
        Cr2CanonMakerNotePrerequisite(
            "locate_existing_makernote_ifd",
            None,
            None,
            "Reuse the existing ExifIFD MakerNotes tag 0x927c and LocateIFD path.",
            (WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,),
        ),
        Cr2CanonMakerNotePrerequisite(
            "preserve_makernote_directory_identity",
            None,
            None,
            "Keep nested MakerNote directories as MakerNotes and preserve Sub-IFD identity.",
            (WRITE_EXIF_MAKERNOTE_SUBIFD_SOURCE,),
        ),
    ]
    blocked: list[Cr2CanonMakerNotePrerequisiteCode] = ["defer_binary_ifd_emission"]
    status: Cr2CanonMakerNotePrerequisiteStatus = "ready"

    owner_name = requested_value_for_tag(classification, "OwnerName")
    if owner_name is not None:
        prerequisites.append(
            Cr2CanonMakerNotePrerequisite(
                "owner_name_valueconv_padding",
                "OwnerName",
                canon_makernote_owner_name_valueconv(owner_name),
                "Apply Canon OwnerName ValueConvInv padding before MakerNote entry encoding.",
                (CANON_OWNER_NAME_SOURCE,),
            )
        )

    focal_plane_x_size = requested_value_for_tag(classification, "FocalPlaneXSize")
    if focal_plane_x_size is not None:
        if model is None or not canon_focal_plane_x_size_model_allowed(model):
            prerequisites.append(
                Cr2CanonMakerNotePrerequisite(
                    "focal_plane_model_condition",
                    "FocalPlaneXSize",
                    model,
                    "Prove the Canon FocalPlaneXSize model condition before ValueConvInv.",
                    (CANON_FOCAL_PLANE_X_SIZE_SOURCE,),
                )
            )
            blocked.append("focal_plane_model_condition")
            status = "focal_plane_model_condition_unproven"
        else:
            try:
                raw_focal_plane = canon_focal_plane_x_size_valueconv_inv(focal_plane_x_size)
            except ValueError as exc:
                prerequisites.append(
                    Cr2CanonMakerNotePrerequisite(
                        "focal_plane_valueconv_integer",
                        "FocalPlaneXSize",
                        None,
                        str(exc),
                        (CANON_FOCAL_PLANE_X_SIZE_SOURCE,),
                    )
                )
                blocked.append("focal_plane_valueconv_integer")
                status = "invalid_focal_plane_value"
            else:
                prerequisites.extend(
                    (
                        Cr2CanonMakerNotePrerequisite(
                            "focal_plane_model_condition",
                            "FocalPlaneXSize",
                            model,
                            "The supplied Canon model passes the oracle condition.",
                            (CANON_FOCAL_PLANE_X_SIZE_SOURCE,),
                        ),
                        Cr2CanonMakerNotePrerequisite(
                            "focal_plane_valueconv_integer",
                            "FocalPlaneXSize",
                            raw_focal_plane,
                            "Apply Canon ValueConvInv: int(mm * 1000 / 25.4 + 0.5).",
                            (CANON_FOCAL_PLANE_X_SIZE_SOURCE,),
                        ),
                    )
                )

    prerequisites.append(
        Cr2CanonMakerNotePrerequisite(
            "defer_binary_ifd_emission",
            None,
            None,
            "Do not emit MakerNote bytes until the Canon binary IFD writer owns fixups.",
            (
                WRITE_CANON_RAW_BUILD_MAKERNOTES_SOURCE,
                WRITE_CANON_RAW_SAVE_MAKERNOTES_SOURCE,
                WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
            ),
        )
    )
    return cr2_canon_makernote_prerequisite_ledger(
        status,
        requested_tags,
        "ExifIFD",
        True,
        tuple(prerequisites),
        tuple(dict.fromkeys(blocked)),
        None,
        unique_sources(
            tuple(reference for item in prerequisites for reference in item.evidence_ids)
        ),
    )


def build_cr2_canon_makernote_binary_codec_plan(
    data: bytes,
    classification: CanonRawWriteRequestClassification | None,
    *,
    model: str | None = None,
) -> Cr2CanonMakerNoteBinaryCodecPlan:
    try:
        graph = parse_cr2_ifd_graph(data)
    except ValueError as exc:
        prerequisite_ledger = build_cr2_canon_makernote_prerequisite_ledger(
            data,
            classification,
            model=model,
        )
        return cr2_canon_makernote_binary_codec_plan(
            "tiff_parse_error",
            prerequisite_ledger,
            model,
            (),
            None,
            None,
            (),
            str(exc),
            prerequisite_ledger.evidence_ids,
        )

    inferred_model = model if model is not None else cr2_model_from_graph(graph)
    prerequisite_ledger = build_cr2_canon_makernote_prerequisite_ledger(
        data,
        classification,
        model=inferred_model,
    )
    if prerequisite_ledger.status == "no_makernote_tags_requested":
        return cr2_canon_makernote_binary_codec_plan(
            "no_makernote_tags_requested",
            prerequisite_ledger,
            inferred_model,
            (),
            None,
            None,
            (),
            None,
            prerequisite_ledger.evidence_ids,
        )
    blocking_codes = tuple(
        code
        for code in prerequisite_ledger.blocked_prerequisite_codes
        if code != "defer_binary_ifd_emission"
    )
    if blocking_codes:
        return cr2_canon_makernote_binary_codec_plan(
            "prerequisite_blocked",
            prerequisite_ledger,
            inferred_model,
            (),
            None,
            None,
            (),
            prerequisite_ledger.parse_error,
            prerequisite_ledger.evidence_ids,
        )

    byte_order: Literal["little", "big"] = "little" if graph.endian == "little" else "big"
    fields: list[Cr2CanonMakerNoteBinaryField] = []
    owner_name = requested_value_for_tag(classification, "OwnerName")
    if owner_name is not None:
        owner_value = canon_makernote_owner_name_valueconv(owner_name).encode("utf-8") + b"\0"
        fields.append(
            Cr2CanonMakerNoteBinaryField(
                code="owner_name_ifd_entry",
                requested_tag="OwnerName",
                canon_tag_id=0x0009,
                field_type=TIFF_TYPE_ASCII,
                count=len(owner_value),
                value_bytes=owner_value,
                directory_entry_bytes=None,
                value_data_bytes=b"",
                value_offset=None,
                fixup_offset=None,
                binary_element_index=None,
                binary_element_byte_offset=None,
                evidence_ids=(CANON_OWNER_NAME_SOURCE,),
            )
        )

    focal_plane_x_size = requested_value_for_tag(classification, "FocalPlaneXSize")
    if focal_plane_x_size is not None:
        raw_focal_plane = canon_focal_plane_x_size_valueconv_inv(focal_plane_x_size)
        fields.append(
            Cr2CanonMakerNoteBinaryField(
                code="focal_plane_x_size_binary_element",
                requested_tag="FocalPlaneXSize",
                canon_tag_id=0x0002,
                field_type=TIFF_TYPE_SHORT,
                count=1,
                value_bytes=raw_focal_plane.to_bytes(2, byte_order),
                directory_entry_bytes=None,
                value_data_bytes=b"",
                value_offset=None,
                fixup_offset=None,
                binary_element_index=2,
                binary_element_byte_offset=4,
                evidence_ids=(
                    CANON_FOCAL_PLANE_X_SIZE_SOURCE,
                    CANON_FOCAL_LENGTH_BINARY_SOURCE,
                ),
            )
        )

    maker_fields, value_buffer, partial_makernote, fixup_offsets = (
        materialize_canon_makernote_ifd_fields(tuple(fields), graph.endian)
    )
    return cr2_canon_makernote_binary_codec_plan(
        "ready",
        prerequisite_ledger,
        inferred_model,
        maker_fields,
        partial_makernote,
        value_buffer,
        fixup_offsets,
        None,
        unique_sources(
            (
                *prerequisite_ledger.evidence_ids,
                WRITE_CANON_RAW_BUILD_MAKERNOTES_SOURCE,
                WRITE_CANON_RAW_SAVE_MAKERNOTES_SOURCE,
                CANON_FOCAL_LENGTH_BINARY_SOURCE,
                *(reference for field in maker_fields for reference in field.evidence_ids),
            )
        ),
    )


def cr2_iptc_naa_relayout_plan(
    status: Cr2IptcNaaRelayoutStatus,
    payload_stage: Cr2IptcPayloadStage,
    directory_name: Cr2TiffIfdDirectoryName | None,
    original_entry_present: bool,
    original_entry_count: int | None,
    planned_entry_index: int | None,
    planned_entry_count: int | None,
    staged_payload_byte_count: int | None,
    padded_value_byte_count: int | None,
    padding_byte_count: int,
    value_storage: TiffEntryValueStorage | None,
    value_field_offset: int | None,
    planned_value_offset: int | None,
    materialized_entry: Cr2IptcNaaMaterializedEntry | None,
    directory_entry_count_before: int | None,
    directory_entry_count_after: int | None,
    directory_rebuild_plan: TiffDirectoryRebuildPlan | None,
    parse_error: str | None,
    evidence_ids: tuple[EvidenceId, ...],
) -> Cr2IptcNaaRelayoutPlan:
    return Cr2IptcNaaRelayoutPlan(
        status=status,
        payload_stage=payload_stage,
        directory_name=directory_name,
        original_entry_present=original_entry_present,
        original_entry_count=original_entry_count,
        planned_entry_index=planned_entry_index,
        planned_entry_field_type=TIFF_TYPE_LONG,
        planned_entry_count=planned_entry_count,
        staged_payload_byte_count=staged_payload_byte_count,
        padded_value_byte_count=padded_value_byte_count,
        padding_byte_count=padding_byte_count,
        value_storage=value_storage,
        value_field_offset=value_field_offset,
        planned_value_offset=planned_value_offset,
        materialized_entry=materialized_entry,
        directory_entry_count_before=directory_entry_count_before,
        directory_entry_count_after=directory_entry_count_after,
        directory_rebuild_plan=directory_rebuild_plan,
        parse_error=parse_error,
        evidence_ids=evidence_ids,
    )


def cr2_canon_makernote_binary_codec_plan(
    status: Cr2CanonMakerNoteBinaryCodecStatus,
    prerequisite_ledger: Cr2CanonMakerNotePrerequisiteLedger,
    inferred_model: str | None,
    materialized_fields: tuple[Cr2CanonMakerNoteBinaryField, ...],
    partial_makernote_bytes: bytes | None,
    value_buffer_bytes: bytes | None,
    fixup_offsets: tuple[int, ...],
    parse_error: str | None,
    evidence_ids: tuple[EvidenceId, ...],
) -> Cr2CanonMakerNoteBinaryCodecPlan:
    return Cr2CanonMakerNoteBinaryCodecPlan(
        status=status,
        prerequisite_ledger=prerequisite_ledger,
        inferred_model=inferred_model,
        materialized_fields=materialized_fields,
        partial_makernote_bytes=partial_makernote_bytes,
        value_buffer_bytes=value_buffer_bytes,
        fixup_offsets=fixup_offsets,
        parse_error=parse_error,
        evidence_ids=evidence_ids,
    )


def materialize_canon_makernote_ifd_fields(
    fields: tuple[Cr2CanonMakerNoteBinaryField, ...],
    endian: Endian,
) -> tuple[
    tuple[Cr2CanonMakerNoteBinaryField, ...],
    bytes,
    bytes,
    tuple[int, ...],
]:
    byte_order: Literal["little", "big"] = "little" if endian == "little" else "big"
    maker_ifd_fields = tuple(field for field in fields if field.code == "owner_name_ifd_entry")
    value_buffer = b"\0\0\0\0"
    materialized_by_tag: dict[int, Cr2CanonMakerNoteBinaryField] = {}
    for field in sorted(maker_ifd_fields, key=lambda item: item.canon_tag_id):
        value_size = len(field.value_bytes)
        if value_size > 4:
            value_offset = len(value_buffer)
            stored_value = value_offset.to_bytes(4, byte_order)
            value_data = field.value_bytes
            if value_size % 2:
                value_data += b"\0"
            value_buffer += value_data
        else:
            value_offset = None
            stored_value = field.value_bytes + (b"\0" * (4 - value_size))
            value_data = b""
        directory_entry = b"".join(
            (
                field.canon_tag_id.to_bytes(2, byte_order),
                field.field_type.to_bytes(2, byte_order),
                field.count.to_bytes(4, byte_order),
                stored_value,
            )
        )
        materialized_by_tag[field.canon_tag_id] = replace(
            field,
            directory_entry_bytes=directory_entry,
            value_data_bytes=value_data,
            value_offset=value_offset,
        )

    materialized_fields: list[Cr2CanonMakerNoteBinaryField] = []
    fixup_offsets: list[int] = []
    maker_notes = len(maker_ifd_fields).to_bytes(2, byte_order)
    for index, field in enumerate(sorted(maker_ifd_fields, key=lambda item: item.canon_tag_id)):
        materialized = materialized_by_tag[field.canon_tag_id]
        if materialized.directory_entry_bytes is None:
            raise ValueError("Canon MakerNote IFD field was not materialized.")
        directory_entry_bytes = materialized.directory_entry_bytes
        fixup_offset = None
        if materialized.value_offset is not None:
            fixup_offset = 2 + index * 12 + 8
            fixup_offsets.append(fixup_offset)
        materialized = replace(materialized, fixup_offset=fixup_offset)
        materialized_fields.append(materialized)
        maker_notes += directory_entry_bytes

    materialized_fields.extend(field for field in fields if field.code != "owner_name_ifd_entry")
    return (
        tuple(materialized_fields),
        value_buffer,
        maker_notes + value_buffer,
        tuple(fixup_offsets),
    )


def materialize_cr2_iptc_naa_entry(
    layout: TiffEntryLayoutPlan,
    value_data: bytes,
    endian: Endian,
    padding_byte_count: int,
) -> Cr2IptcNaaMaterializedEntry:
    planned_value_offset = layout.planned_value_offset
    if planned_value_offset is None:
        raise ValueError("IPTC-NAA payload must be stored in the TIFF value data area.")
    byte_order: Literal["little", "big"] = "little" if endian == "little" else "big"
    directory_entry_bytes = b"".join(
        (
            int(layout.tag_id).to_bytes(2, byte_order),
            int(layout.field_type).to_bytes(2, byte_order),
            int(layout.count).to_bytes(4, byte_order),
            planned_value_offset.to_bytes(4, byte_order),
        )
    )
    return Cr2IptcNaaMaterializedEntry(
        tag_id=int(layout.tag_id),
        field_type=int(layout.field_type),
        count=int(layout.count),
        value_offset=planned_value_offset,
        directory_entry_bytes=directory_entry_bytes,
        value_data_bytes=value_data,
        padding_byte_count=padding_byte_count,
        evidence_ids=(
            WRITE_EXIF_IPTC_NAA_RELAYOUT_SOURCE,
            WRITE_EXIF_DIRECTORY_VALUE_AREA_SOURCE,
        ),
    )


def cr2_iptc_payload_stage(
    status: Cr2IptcPayloadStageStatus,
    requested_keywords: tuple[str, ...],
    original_payload: bytes,
    staged_payload: bytes | None,
    tiff_entry_count: int | None,
    padding_byte_count: int,
    parse_error: str | None,
    evidence_ids: tuple[EvidenceId, ...],
) -> Cr2IptcPayloadStage:
    return Cr2IptcPayloadStage(
        status=status,
        requested_keywords=requested_keywords,
        original_payload=original_payload,
        staged_payload=staged_payload,
        tiff_entry_tag_id=IPTC_NAA_TAG,
        tiff_entry_field_type=TIFF_TYPE_LONG,
        tiff_entry_count=tiff_entry_count,
        tiff_entry_padding_byte_count=padding_byte_count,
        parse_error=parse_error,
        evidence_ids=evidence_ids,
    )


def cr2_canon_makernote_prerequisite_ledger(
    status: Cr2CanonMakerNotePrerequisiteStatus,
    requested_tags: tuple[str, ...],
    maker_note_directory_name: Cr2TiffIfdDirectoryName | None,
    existing_makernote_present: bool,
    prerequisites: tuple[Cr2CanonMakerNotePrerequisite, ...],
    blocked_prerequisite_codes: tuple[Cr2CanonMakerNotePrerequisiteCode, ...],
    parse_error: str | None,
    evidence_ids: tuple[EvidenceId, ...],
) -> Cr2CanonMakerNotePrerequisiteLedger:
    return Cr2CanonMakerNotePrerequisiteLedger(
        status=status,
        requested_tags=requested_tags,
        maker_note_directory_name=maker_note_directory_name,
        maker_note_tag_id=MAKER_NOTE_TAG,
        existing_makernote_present=existing_makernote_present,
        prerequisites=prerequisites,
        blocked_prerequisite_codes=blocked_prerequisite_codes,
        parse_error=parse_error,
        evidence_ids=evidence_ids,
    )


def parse_cr2_ifd_graph(data: bytes) -> Cr2ParsedIfdGraph:
    header = parse_tiff_header(data)
    ifd0 = parse_ifd(data, header.first_ifd_offset, header.endian)
    ifd0_directory = raw_directory(data, ifd0, header.endian)
    exif_offset = inline_u32(
        raw_entry_by_tag_id(ifd0_directory, EXIF_IFD_POINTER_TAG), header.endian
    )
    exif_ifd = None
    exif_directory = None
    if exif_offset is not None and exif_offset != 0:
        exif_ifd = parse_ifd(data, exif_offset, header.endian)
        exif_directory = raw_directory(data, exif_ifd, header.endian)

    ifd1 = None
    ifd1_directory = None
    if ifd0.next_ifd_offset:
        ifd1 = parse_ifd(data, ifd0.next_ifd_offset, header.endian)
        ifd1_directory = raw_directory(data, ifd1, header.endian)

    return Cr2ParsedIfdGraph(
        endian=header.endian,
        ifd0=ifd0,
        ifd0_directory=ifd0_directory,
        exif_ifd=exif_ifd,
        exif_directory=exif_directory,
        ifd1=ifd1,
        ifd1_directory=ifd1_directory,
    )


def cr2_model_from_graph(graph: Cr2ParsedIfdGraph) -> str | None:
    model_entry = raw_entry_by_tag_id(graph.ifd0_directory, 0x0110)
    if model_entry is None:
        return None
    return model_entry.raw_value.rstrip(b"\0").decode("utf-8", errors="replace")


def build_cr2_exif_scalar_stage_plan(
    classification: CanonRawWriteRequestClassification | None,
) -> ExifScalarWritePlan | None:
    owner_name = requested_value_for_tag(classification, "OwnerName")
    if owner_name is None:
        return None
    return build_exif_scalar_write_plan(
        image_description=None,
        orientation=None,
        date_time_original=None,
        owner_name=owner_name,
    )


def tiff_directory_inputs_from_graph(
    graph: Cr2ParsedIfdGraph,
) -> tuple[TiffDirectoryInput, ...]:
    inputs: list[TiffDirectoryInput] = [
        TiffDirectoryInput("IFD0", graph.ifd0_directory, directory_start=graph.ifd0.offset)
    ]
    if graph.exif_ifd is not None and graph.exif_directory is not None:
        inputs.append(
            TiffDirectoryInput(
                "ExifIFD",
                graph.exif_directory,
                directory_start=graph.exif_ifd.offset,
            )
        )
    if graph.ifd1 is not None and graph.ifd1_directory is not None:
        inputs.append(
            TiffDirectoryInput(
                "IFD1",
                graph.ifd1_directory,
                ifd_index=1,
                directory_start=graph.ifd1.offset,
            )
        )
    return tuple(inputs)


def directory_stages_from_graph(
    graph: Cr2ParsedIfdGraph,
) -> tuple[Cr2TiffIfdDirectoryStage, ...]:
    stages = [
        Cr2TiffIfdDirectoryStage(
            "IFD0",
            graph.ifd0.offset,
            len(graph.ifd0.entries),
            graph.ifd0.next_ifd_offset,
            tuple(entry.tag_id for entry in graph.ifd0.entries),
        )
    ]
    if graph.exif_ifd is not None:
        stages.append(
            Cr2TiffIfdDirectoryStage(
                "ExifIFD",
                graph.exif_ifd.offset,
                len(graph.exif_ifd.entries),
                graph.exif_ifd.next_ifd_offset,
                tuple(entry.tag_id for entry in graph.exif_ifd.entries),
            )
        )
    if graph.ifd1 is not None:
        stages.append(
            Cr2TiffIfdDirectoryStage(
                "IFD1",
                graph.ifd1.offset,
                len(graph.ifd1.entries),
                graph.ifd1.next_ifd_offset,
                tuple(entry.tag_id for entry in graph.ifd1.entries),
            )
        )
    return tuple(stages)


def surface_stages_from_graph(
    graph: Cr2ParsedIfdGraph,
    classification: CanonRawWriteRequestClassification | None,
    exif_scalar_plan: ExifScalarWritePlan | None,
) -> tuple[Cr2TiffIfdSurfaceStage, ...]:
    stages: list[Cr2TiffIfdSurfaceStage] = []
    requested_surfaces = requested_surfaces_by_name(classification)
    if exif_scalar_plan is not None:
        stages.append(
            Cr2TiffIfdSurfaceStage(
                "staged_exif_scalar_directory_entry",
                "cr2_tiff_exif",
                requested_surfaces.get("cr2_tiff_exif", ()),
                "ExifIFD",
                (EXIF_IFD_POINTER_TAG, 0xA430),
                (WRITE_EXIF_TAG_MERGE_SOURCE, EXIF_OWNER_NAME_SOURCE),
            )
        )
    if "cr2_tiff_iptc" in requested_surfaces or has_tag(graph.ifd0_directory, IPTC_NAA_TAG):
        stages.append(
            Cr2TiffIfdSurfaceStage(
                "deferred_iptc_subdirectory_payload",
                "cr2_tiff_iptc",
                requested_surfaces.get("cr2_tiff_iptc", ()),
                "IFD0",
                (IPTC_NAA_TAG,),
                (CR2_IPTC_DIRECTORY_SOURCE, IPTC_KEYWORDS_SOURCE),
            )
        )
    if "cr2_canon_makernote" in requested_surfaces or (
        graph.exif_directory is not None and has_tag(graph.exif_directory, MAKER_NOTE_TAG)
    ):
        stages.append(
            Cr2TiffIfdSurfaceStage(
                "deferred_canon_makernote_codec",
                "cr2_canon_makernote",
                requested_surfaces.get("cr2_canon_makernote", ()),
                "ExifIFD" if graph.exif_directory is not None else None,
                (MAKER_NOTE_TAG,),
                (CANON_OWNER_NAME_SOURCE, CANON_FOCAL_PLANE_X_SIZE_SOURCE),
            )
        )
    return tuple(stages)


def requested_tag_names(
    classification: CanonRawWriteRequestClassification | None,
) -> tuple[str, ...]:
    if classification is None:
        return ()
    if classification.container_kind != "cr2_tiff":
        raise ValueError(f"Expected cr2_tiff classification, got {classification.container_kind}")
    return tuple(tag.requested_tag for tag in classification.tags)


def requested_value_for_tag(
    classification: CanonRawWriteRequestClassification | None,
    requested_tag: str,
) -> str | None:
    if classification is None:
        return None
    if classification.container_kind != "cr2_tiff":
        raise ValueError(f"Expected cr2_tiff classification, got {classification.container_kind}")
    for tag in classification.tags:
        if tag.requested_tag == requested_tag:
            return tag.requested_value
    return None


def requested_values_for_tag(
    classification: CanonRawWriteRequestClassification | None,
    requested_tag: str,
) -> tuple[str, ...]:
    if classification is None:
        return ()
    if classification.container_kind != "cr2_tiff":
        raise ValueError(f"Expected cr2_tiff classification, got {classification.container_kind}")
    return tuple(
        tag.requested_value for tag in classification.tags if tag.requested_tag == requested_tag
    )


def requested_makernote_tag_names(
    classification: CanonRawWriteRequestClassification | None,
) -> tuple[str, ...]:
    requested_surfaces = requested_surfaces_by_name(classification)
    return requested_surfaces.get("cr2_canon_makernote", ())


def requested_surfaces_by_name(
    classification: CanonRawWriteRequestClassification | None,
) -> dict[CanonRawWriteSurface, tuple[str, ...]]:
    surfaces: dict[CanonRawWriteSurface, list[str]] = {}
    if classification is None:
        return {}
    if classification.container_kind != "cr2_tiff":
        raise ValueError(f"Expected cr2_tiff classification, got {classification.container_kind}")
    for tag in classification.tags:
        for surface in tag.target_surfaces:
            surfaces.setdefault(surface, []).append(tag.requested_tag)
    return {surface: tuple(tags) for surface, tags in surfaces.items()}


def raw_entry_by_tag_id(
    directory: RawTiffDirectory,
    tag_id: int,
) -> RawTiffEntry | None:
    for entry in directory.entries:
        if entry.tag_id == tag_id:
            return entry
    return None


def upsert_raw_tiff_entry(
    entries: tuple[RawTiffEntry, ...],
    updated_entry: RawTiffEntry,
) -> tuple[RawTiffEntry, ...]:
    retained = tuple(entry for entry in entries if entry.tag_id != updated_entry.tag_id)
    return (*retained, updated_entry)


def has_tag(directory: RawTiffDirectory, tag_id: int) -> bool:
    return raw_entry_by_tag_id(directory, tag_id) is not None


def tiff_endian_from_cr2_byte_order(byte_order: str) -> Endian | None:
    if byte_order == "little":
        return "little"
    if byte_order == "big":
        return "big"
    return None


def padding_to_4_byte_boundary(length: int) -> int:
    return (-length) % 4


def canon_makernote_owner_name_valueconv(owner_name: str) -> str:
    if len(owner_name) >= 31:
        return owner_name
    return owner_name + ("\0" * (31 - len(owner_name)))


def canon_focal_plane_x_size_valueconv_inv(value: str) -> int:
    cleaned = value.strip()
    if cleaned.lower().endswith("mm"):
        cleaned = cleaned[:-2].strip()
    try:
        millimeters = float(cleaned)
    except ValueError as exc:
        raise ValueError("FocalPlaneXSize must be a millimeter value.") from exc
    return int(millimeters * 1000 / 25.4 + 0.5)


def canon_focal_plane_x_size_model_allowed(model: str) -> bool:
    normalized = model.upper()
    if "EOS" not in normalized:
        return True
    allowed_fragments = (
        "1D",
        "1DS",
        "5D",
        "D30",
        "D60",
        "10D",
        "20D",
        "30D",
        "K236",
        "300D DIGITAL",
        "350D DIGITAL",
        "400D DIGITAL",
        "REBEL",
        "REBEL X",
        "REBEL XT",
        "REBEL XTI",
        "KISS DIGITAL",
        "KISS DIGITAL N",
        "KISS DIGITAL X",
    )
    return any(fragment in normalized for fragment in allowed_fragments)


def blocked_stage(
    status: Cr2TiffIfdStageStatus,
    requested_tags: tuple[str, ...],
    endian: Endian | None,
    ifd0_offset: int | None,
    directories: tuple[Cr2TiffIfdDirectoryStage, ...],
    surface_stages: tuple[Cr2TiffIfdSurfaceStage, ...],
    reason: str,
    parse_error: str | None,
    evidence_ids: tuple[EvidenceId, ...],
) -> Cr2TiffIfdMutationStage:
    return Cr2TiffIfdMutationStage(
        status=status,
        requested_tags=requested_tags,
        endian=endian,
        ifd0_offset=ifd0_offset,
        directories=directories,
        surface_stages=surface_stages,
        blockers=(
            Cr2TiffIfdStageBlocker(
                "no_byte_mutation_from_ifd_stage",
                ("cr2_tiff_exif", "cr2_tiff_iptc", "cr2_canon_makernote"),
                reason,
                evidence_ids,
            ),
        ),
        transaction_plan=None,
        parse_error=parse_error,
        evidence_ids=evidence_ids,
    )


def tag_id_hex(tag_id: int) -> str:
    return f"0x{tag_id:04X}"


def evidence_ids_to_json(references: tuple[EvidenceId, ...]) -> JsonArray:
    return [evidence_id_to_json(reference) for reference in references]


CR2_TIFF_IFD_STAGE_BLOCKERS: tuple[Cr2TiffIfdStageBlocker, ...] = (
    Cr2TiffIfdStageBlocker(
        "no_byte_mutation_from_ifd_stage",
        ("cr2_tiff_exif", "cr2_tiff_iptc", "cr2_canon_makernote"),
        "The CR2 IFD stage may build a transaction plan but must not emit RAW bytes.",
        (WRITE_CR2_SOURCE, WRITE_EXIF_TAG_MERGE_SOURCE),
    ),
    Cr2TiffIfdStageBlocker(
        "requires_embedded_iptc_writer",
        ("cr2_tiff_iptc",),
        "Keywords require a TIFF IPTC-NAA subdirectory payload writer before byte emit.",
        (CR2_IPTC_DIRECTORY_SOURCE, IPTC_KEYWORDS_SOURCE),
    ),
    Cr2TiffIfdStageBlocker(
        "requires_canon_makernote_codec",
        ("cr2_canon_makernote",),
        "Canon maker-note fields require Canon-specific binary codecs and model gates.",
        (CANON_OWNER_NAME_SOURCE, CANON_FOCAL_PLANE_X_SIZE_SOURCE),
    ),
    Cr2TiffIfdStageBlocker(
        "requires_image_data_copy_engine",
        ("cr2_tiff_exif", "cr2_tiff_iptc", "cr2_canon_makernote"),
        "Rebuilt CR2 IFD bytes must be followed by validated copied image data.",
        (WRITE_EXIF_IMAGE_DATA_SOURCE, CANON_RAW_CR2_SUFFIX_TEST_SOURCE),
    ),
    Cr2TiffIfdStageBlocker(
        "requires_cr2_header_last_ifd_fixup",
        ("cr2_tiff_exif", "cr2_tiff_iptc", "cr2_canon_makernote"),
        "WriteCR2 requires LastIFD to rebuild the 16-byte Canon RAW header.",
        (WRITE_CR2_SOURCE, WRITE_EXIF_LAST_IFD_SOURCE),
    ),
)
