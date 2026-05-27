"""Non-mutating TIFF directory transaction planning primitives.

The objects in this module model the layout decisions made by ExifTool's
WriteExif directory rebuild path.  They intentionally stop before byte
mutation: callers get deterministic ordering, offset tracking, SubIFD
scheduling, and copy gates, but no encoded TIFF output.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal

from exifmodern.exif_scalar_write_plan import ExifScalarDirectoryName, ExifScalarWritePlan
from exifmodern.formats.tiff.exif_scalar_rewriter import apply_exif_scalar_write_plan
from exifmodern.formats.tiff.mutation import (
    RawTiffDirectory,
    RawTiffEntry,
    directory_size_from_count,
)
from exifmodern.formats.tiff.primitives import Endian, TiffFieldType
from exifmodern.json_types import JsonArray, JsonObject

type EvidenceId = str

type TiffDirectoryContainerKind = Literal[
    "tiff",
    "dng",
    "cr2",
    "mrw_ttw",
    "embedded_exif_sidecar",
]
type TiffEntryValueStorage = Literal["inline_value", "value_data_area"]
type TiffNextIfdAction = Literal[
    "write_zero_pointer",
    "link_existing_next_ifd",
    "create_ifd1",
    "maker_note_padding",
]
type TiffSubIfdPointerLocation = Literal["directory_entry", "value_data_area"]
type TiffImageDataGateCode = Literal[
    "no_byte_mutation_from_transaction_plan",
    "offset_pair_counts_must_match",
    "image_data_copy_requires_random_access_source",
    "strip_tile_conflict_requires_format_specific_handler",
    "subifd_image_data_requires_contained_fixup",
    "mrw_ttw_requires_four_byte_padding",
]

SUB_IFD_POINTER_TAG = 0x014A
STRIP_OFFSETS_TAG = 0x0111
STRIP_BYTE_COUNTS_TAG = 0x0117
RAW_DATA_OFFSET_TAG = 0x0118
TILE_OFFSETS_TAG = 0x0144
TILE_BYTE_COUNTS_TAG = 0x0145
THUMBNAIL_OFFSET_TAG = 0x0201
THUMBNAIL_LENGTH_TAG = 0x0202
JPG_FROM_RAW_START_TAG = 0x0201
JPG_FROM_RAW_LENGTH_TAG = 0x0202

WRITE_EXIF_SORT_IFD_SOURCE = "tiff.write_exif.sort_ifd"
WRITE_EXIF_IFD_ORDER_SOURCE = "tiff.write_exif.ifd_order"
WRITE_EXIF_DIRECTORY_ASSEMBLY_SOURCE = "tiff.write_exif.directory_assembly"
WRITE_EXIF_NEXT_IFD_SOURCE = "tiff.write_exif.next_ifd"
WRITE_EXIF_SUBIFD_CREATE_SOURCE = "tiff.write_exif.subifd_create"
WRITE_EXIF_SUBIFD_REWRITE_SOURCE = "tiff.write_exif.subifd_rewrite"
WRITE_EXIF_OFFSET_PAIR_SOURCE = "tiff.write_exif.offset_pair"
WRITE_EXIF_IMAGE_DATA_VALIDATE_SOURCE = "tiff.write_exif.image_data_validate"
WRITE_EXIF_IMAGE_DATA_COPY_SOURCE = "tiff.write_exif.image_data_copy"
WRITE_EXIF_MRW_TTW_SOURCE = "tiff.write_exif.mrw_ttw"
WRITE_EXIF_DNG_TIFF_LIKE_IFD_SOURCE = "tiff.write_exif.dng_tiff_like_ifd"


@dataclass(frozen=True)
class TiffDirectoryInput:
    name: str
    directory: RawTiffDirectory
    ifd_index: int = 0
    directory_start: int = 0
    allow_zero_tag_id: bool = False
    subifd_tag_ids: tuple[int, ...] = (SUB_IFD_POINTER_TAG,)


@dataclass(frozen=True)
class TiffEntryLayoutPlan:
    index: int
    tag_id: int
    field_type: TiffFieldType
    count: int
    raw_value_byte_count: int
    value_storage: TiffEntryValueStorage
    directory_entry_offset: int
    value_field_offset: int
    planned_value_offset: int | None
    source_entry: RawTiffEntry

    def to_json(self) -> JsonObject:
        return {
            "count": self.count,
            "directory_entry_offset": self.directory_entry_offset,
            "field_type": self.field_type,
            "index": self.index,
            "planned_value_offset": self.planned_value_offset,
            "raw_value_byte_count": self.raw_value_byte_count,
            "tag_id": tag_id_hex(self.tag_id),
            "value_field_offset": self.value_field_offset,
            "value_storage": self.value_storage,
        }


@dataclass(frozen=True)
class TiffValueDataReference:
    tag_id: int
    value_offset: int
    byte_count: int

    def to_json(self) -> JsonObject:
        return {
            "byte_count": self.byte_count,
            "tag_id": tag_id_hex(self.tag_id),
            "value_offset": self.value_offset,
        }


@dataclass(frozen=True)
class TiffValueDataAreaPlan:
    start_offset: int
    initial_size: int
    final_size: int
    references: tuple[TiffValueDataReference, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def growth_bytes(self) -> int:
        return self.final_size - self.initial_size

    def to_json(self) -> JsonObject:
        return {
            "final_size": self.final_size,
            "growth_bytes": self.growth_bytes,
            "initial_size": self.initial_size,
            "references": json_object_array(reference.to_json() for reference in self.references),
            "start_offset": self.start_offset,
        }


@dataclass(frozen=True)
class TiffNextIfdPointerPlan:
    action: TiffNextIfdAction
    pointer_offset: int
    original_next_ifd_offset: int
    planned_next_ifd_offset: int
    has_pointer_slot: bool
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "has_pointer_slot": self.has_pointer_slot,
            "original_next_ifd_offset": self.original_next_ifd_offset,
            "planned_next_ifd_offset": self.planned_next_ifd_offset,
            "pointer_offset": self.pointer_offset,
        }


@dataclass(frozen=True)
class TiffSubIfdSchedule:
    parent_directory_name: str
    parent_tag_id: int
    subdirectory_name: str
    subdirectory_index: int
    pointer_location: TiffSubIfdPointerLocation
    pointer_offset: int
    placeholder_value: int
    propagates_image_data: bool
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "parent_directory_name": self.parent_directory_name,
            "parent_tag_id": tag_id_hex(self.parent_tag_id),
            "placeholder_value": hex(self.placeholder_value),
            "pointer_location": self.pointer_location,
            "pointer_offset": self.pointer_offset,
            "propagates_image_data": self.propagates_image_data,
            "subdirectory_index": self.subdirectory_index,
            "subdirectory_name": self.subdirectory_name,
        }


@dataclass(frozen=True)
class TiffOffsetPairSpec:
    offset_tag_id: int
    byte_count_tag_id: int
    offset_tag_name: str
    byte_count_tag_name: str
    data_tag: str
    is_image_data: bool = True


@dataclass(frozen=True)
class TiffOffsetPairRecord:
    directory_name: str
    ifd_index: int
    offset_tag_id: int
    byte_count_tag_id: int
    offset_tag_name: str
    byte_count_tag_name: str
    data_tag: str
    offset_count: int
    byte_count_count: int
    counts_match: bool
    pointer_tracking_required: bool
    image_data_copy_deferred: bool
    gate_codes: tuple[TiffImageDataGateCode, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_count_count": self.byte_count_count,
            "byte_count_tag_id": tag_id_hex(self.byte_count_tag_id),
            "byte_count_tag_name": self.byte_count_tag_name,
            "counts_match": self.counts_match,
            "data_tag": self.data_tag,
            "directory_name": self.directory_name,
            "gate_codes": list(self.gate_codes),
            "ifd_index": self.ifd_index,
            "image_data_copy_deferred": self.image_data_copy_deferred,
            "offset_count": self.offset_count,
            "offset_tag_id": tag_id_hex(self.offset_tag_id),
            "offset_tag_name": self.offset_tag_name,
            "pointer_tracking_required": self.pointer_tracking_required,
        }


@dataclass(frozen=True)
class TiffImageDataCopyGate:
    code: TiffImageDataGateCode
    required_records: tuple[str, ...]
    invariant: str
    failure_response: str
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def blocks_mutation(self) -> bool:
        return True

    def to_json(self) -> JsonObject:
        return {
            "blocks_mutation": self.blocks_mutation,
            "code": self.code,
            "failure_response": self.failure_response,
            "invariant": self.invariant,
            "required_records": list(self.required_records),
        }


@dataclass(frozen=True)
class TiffDirectoryRebuildPlan:
    container_kind: TiffDirectoryContainerKind
    directory_name: str
    ifd_index: int
    directory_start: int
    endian: Endian
    original_directory: RawTiffDirectory
    planned_directory: RawTiffDirectory
    ordered_entries: tuple[TiffEntryLayoutPlan, ...]
    value_data_area: TiffValueDataAreaPlan
    next_ifd_pointer: TiffNextIfdPointerPlan
    subifd_schedules: tuple[TiffSubIfdSchedule, ...]
    offset_pairs: tuple[TiffOffsetPairRecord, ...]
    image_data_copy_gates: tuple[TiffImageDataCopyGate, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def entry_count(self) -> int:
        return len(self.ordered_entries)

    @property
    def value_data_growth_bytes(self) -> int:
        return self.value_data_area.growth_bytes

    def to_json(self) -> JsonObject:
        return {
            "can_mutate_bytes": self.can_mutate_bytes,
            "container_kind": self.container_kind,
            "directory_name": self.directory_name,
            "directory_start": self.directory_start,
            "entry_count": self.entry_count,
            "ifd_index": self.ifd_index,
            "image_data_copy_gates": json_object_array(
                gate.to_json() for gate in self.image_data_copy_gates
            ),
            "next_ifd_pointer": self.next_ifd_pointer.to_json(),
            "offset_pairs": json_object_array(record.to_json() for record in self.offset_pairs),
            "ordered_entries": json_object_array(entry.to_json() for entry in self.ordered_entries),
            "subifd_schedules": json_object_array(
                schedule.to_json() for schedule in self.subifd_schedules
            ),
            "value_data_area": self.value_data_area.to_json(),
            "value_data_growth_bytes": self.value_data_growth_bytes,
        }


@dataclass(frozen=True)
class TiffDirectoryTransactionPlan:
    status: Literal["plan_only_deferred"]
    container_kind: TiffDirectoryContainerKind
    directory_order: tuple[str, ...]
    directory_plans: tuple[TiffDirectoryRebuildPlan, ...]
    image_data_copy_gates: tuple[TiffImageDataCopyGate, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def directory_count(self) -> int:
        return len(self.directory_plans)

    @property
    def blocked_gate_count(self) -> int:
        return sum(gate.blocks_mutation for gate in self.image_data_copy_gates)

    def to_json(self) -> JsonObject:
        return {
            "blocked_gate_count": self.blocked_gate_count,
            "can_mutate_bytes": self.can_mutate_bytes,
            "container_kind": self.container_kind,
            "directory_count": self.directory_count,
            "directory_order": list(self.directory_order),
            "directory_plans": json_object_array(plan.to_json() for plan in self.directory_plans),
            "image_data_copy_gates": json_object_array(
                gate.to_json() for gate in self.image_data_copy_gates
            ),
            "status": self.status,
        }


DEFAULT_OFFSET_PAIR_SPECS: tuple[TiffOffsetPairSpec, ...] = (
    TiffOffsetPairSpec(
        STRIP_OFFSETS_TAG,
        STRIP_BYTE_COUNTS_TAG,
        "StripOffsets",
        "StripByteCounts",
        "ImageData",
    ),
    TiffOffsetPairSpec(
        TILE_OFFSETS_TAG,
        TILE_BYTE_COUNTS_TAG,
        "TileOffsets",
        "TileByteCounts",
        "ImageData",
    ),
    TiffOffsetPairSpec(
        THUMBNAIL_OFFSET_TAG,
        THUMBNAIL_LENGTH_TAG,
        "ThumbnailOffset",
        "ThumbnailLength",
        "ThumbnailImage",
    ),
    TiffOffsetPairSpec(
        RAW_DATA_OFFSET_TAG,
        STRIP_BYTE_COUNTS_TAG,
        "RawDataOffset",
        "StripByteCounts",
        "RawData",
    ),
)

BASE_IMAGE_DATA_COPY_GATES: tuple[TiffImageDataCopyGate, ...] = (
    TiffImageDataCopyGate(
        "no_byte_mutation_from_transaction_plan",
        (),
        "The shared TIFF directory transaction plan must never write or encode output bytes.",
        (
            "Keep the caller in plan-only mode until a byte-level transaction engine "
            "consumes this plan."
        ),
        (WRITE_EXIF_DIRECTORY_ASSEMBLY_SOURCE,),
    ),
    TiffImageDataCopyGate(
        "image_data_copy_requires_random_access_source",
        ("offset_pair_records",),
        "Image data ranges may be copied only from a validated random-access source.",
        "Do not copy strip, tile, thumbnail, or raw payload bytes from this plan alone.",
        (WRITE_EXIF_IMAGE_DATA_VALIDATE_SOURCE, WRITE_EXIF_IMAGE_DATA_COPY_SOURCE),
    ),
)


def build_tiff_directory_transaction_plan(
    directories: tuple[TiffDirectoryInput, ...],
    endian: Endian,
    container_kind: TiffDirectoryContainerKind = "tiff",
    scalar_write_plan: ExifScalarWritePlan | None = None,
    create_ifd1: bool = False,
) -> TiffDirectoryTransactionPlan:
    directory_plans = tuple(
        build_tiff_directory_rebuild_plan(
            directory_input.directory,
            directory_name=directory_input.name,
            endian=endian,
            container_kind=container_kind,
            ifd_index=directory_input.ifd_index,
            directory_start=directory_input.directory_start,
            allow_zero_tag_id=directory_input.allow_zero_tag_id,
            subifd_tag_ids=directory_input.subifd_tag_ids,
            scalar_write_plan=scalar_write_plan,
            create_ifd1=create_ifd1 and directory_input.name == "IFD0",
        )
        for directory_input in directories
    )
    gates = unique_gates(
        (
            *BASE_IMAGE_DATA_COPY_GATES,
            *(gate for plan in directory_plans for gate in plan.image_data_copy_gates),
        )
    )
    return TiffDirectoryTransactionPlan(
        status="plan_only_deferred",
        container_kind=container_kind,
        directory_order=write_exif_directory_order(container_kind),
        directory_plans=directory_plans,
        image_data_copy_gates=gates,
        evidence_ids=unique_evidence_ids(
            (
                WRITE_EXIF_IFD_ORDER_SOURCE,
                WRITE_EXIF_DIRECTORY_ASSEMBLY_SOURCE,
                *container_evidence_ids(container_kind),
                *(evidence_id for plan in directory_plans for evidence_id in plan.evidence_ids),
            )
        ),
    )


def build_tiff_directory_rebuild_plan(
    directory: RawTiffDirectory,
    directory_name: str,
    endian: Endian,
    container_kind: TiffDirectoryContainerKind = "tiff",
    ifd_index: int = 0,
    directory_start: int = 0,
    allow_zero_tag_id: bool = False,
    subifd_tag_ids: tuple[int, ...] = (SUB_IFD_POINTER_TAG,),
    scalar_write_plan: ExifScalarWritePlan | None = None,
    create_ifd1: bool = False,
) -> TiffDirectoryRebuildPlan:
    planned_directory = apply_scalar_plan_if_supported(
        directory,
        scalar_write_plan,
        directory_name,
        endian,
    )
    sorted_entries = sort_ifd_entries_for_write(
        planned_directory.entries,
        allow_zero_tag_id=allow_zero_tag_id,
    )
    planned_directory = replace(planned_directory, entries=sorted_entries)
    ordered_entries, value_data_area = plan_entry_layouts(sorted_entries, directory_start)
    subifd_schedules = plan_subifd_schedules(
        directory_name,
        ordered_entries,
        subifd_tag_ids=subifd_tag_ids,
    )
    offset_pairs = plan_offset_pair_records(
        directory_name,
        ifd_index,
        sorted_entries,
        container_kind=container_kind,
    )
    gates = plan_image_data_copy_gates(offset_pairs, subifd_schedules, container_kind)
    evidence_ids = unique_evidence_ids(
        (
            WRITE_EXIF_SORT_IFD_SOURCE,
            WRITE_EXIF_DIRECTORY_ASSEMBLY_SOURCE,
            WRITE_EXIF_NEXT_IFD_SOURCE,
            WRITE_EXIF_OFFSET_PAIR_SOURCE,
            WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
            *container_evidence_ids(container_kind),
            *(record.evidence_ids[0] for record in offset_pairs),
            *(schedule.evidence_ids[0] for schedule in subifd_schedules),
        )
    )
    return TiffDirectoryRebuildPlan(
        container_kind=container_kind,
        directory_name=directory_name,
        ifd_index=ifd_index,
        directory_start=directory_start,
        endian=endian,
        original_directory=directory,
        planned_directory=planned_directory,
        ordered_entries=ordered_entries,
        value_data_area=value_data_area,
        next_ifd_pointer=plan_next_ifd_pointer(
            planned_directory,
            directory_name,
            directory_start,
            create_ifd1=create_ifd1,
        ),
        subifd_schedules=subifd_schedules,
        offset_pairs=offset_pairs,
        image_data_copy_gates=gates,
        evidence_ids=evidence_ids,
    )


def apply_scalar_plan_if_supported(
    directory: RawTiffDirectory,
    scalar_write_plan: ExifScalarWritePlan | None,
    directory_name: str,
    endian: Endian,
) -> RawTiffDirectory:
    if scalar_write_plan is None:
        return directory
    if directory_name == "IFD0":
        scalar_directory_name: ExifScalarDirectoryName = "IFD0"
    elif directory_name == "ExifIFD":
        scalar_directory_name = "ExifIFD"
    else:
        return directory
    entries = apply_exif_scalar_write_plan(
        directory.entries,
        scalar_write_plan,
        scalar_directory_name,
        endian,
    )
    return replace(directory, entries=entries)


def sort_ifd_entries_for_write(
    entries: tuple[RawTiffEntry, ...],
    allow_zero_tag_id: bool = False,
) -> tuple[RawTiffEntry, ...]:
    indexed_entries = tuple(enumerate(entries))
    return tuple(
        entry
        for _, entry in sorted(
            indexed_entries,
            key=lambda indexed_entry: sort_key_for_ifd_entry(
                indexed_entry[1].tag_id,
                indexed_entry[0],
                allow_zero_tag_id,
            ),
        )
    )


def sort_key_for_ifd_entry(
    tag_id: int,
    index: int,
    allow_zero_tag_id: bool,
) -> tuple[int, int]:
    if tag_id == 0 and index != 0 and not allow_zero_tag_id:
        return (0x10000, index)
    return (tag_id, index)


def plan_entry_layouts(
    entries: tuple[RawTiffEntry, ...],
    directory_start: int = 0,
) -> tuple[tuple[TiffEntryLayoutPlan, ...], TiffValueDataAreaPlan]:
    value_data_offset = directory_start + directory_size_from_count(len(entries))
    next_value_data_offset = value_data_offset
    layouts: list[TiffEntryLayoutPlan] = []
    references: list[TiffValueDataReference] = []
    for index, entry in enumerate(entries):
        directory_entry_offset = directory_start + 2 + 12 * index
        value_field_offset = directory_entry_offset + 8
        byte_count = len(entry.raw_value)
        if byte_count > 4:
            planned_value_offset_value = next_value_data_offset
            planned_value_offset: int | None = planned_value_offset_value
            value_storage: TiffEntryValueStorage = "value_data_area"
            references.append(
                TiffValueDataReference(
                    tag_id=entry.tag_id,
                    value_offset=planned_value_offset_value,
                    byte_count=byte_count,
                )
            )
            next_value_data_offset += byte_count
        else:
            planned_value_offset = None
            value_storage = "inline_value"
        layouts.append(
            TiffEntryLayoutPlan(
                index=index,
                tag_id=entry.tag_id,
                field_type=entry.field_type,
                count=entry.count,
                raw_value_byte_count=byte_count,
                value_storage=value_storage,
                directory_entry_offset=directory_entry_offset,
                value_field_offset=value_field_offset,
                planned_value_offset=planned_value_offset,
                source_entry=entry,
            )
        )
    value_data_area = TiffValueDataAreaPlan(
        start_offset=value_data_offset,
        initial_size=0,
        final_size=next_value_data_offset - value_data_offset,
        references=tuple(references),
        evidence_ids=(WRITE_EXIF_DIRECTORY_ASSEMBLY_SOURCE,),
    )
    return tuple(layouts), value_data_area


def plan_next_ifd_pointer(
    directory: RawTiffDirectory,
    directory_name: str,
    directory_start: int,
    create_ifd1: bool = False,
) -> TiffNextIfdPointerPlan:
    pointer_offset = directory_start + 2 + len(directory.entries) * 12
    if directory_name == "MakerNotes":
        action: TiffNextIfdAction = "maker_note_padding"
        planned_next_ifd_offset = 0
    elif directory.next_ifd_offset:
        action = "link_existing_next_ifd"
        planned_next_ifd_offset = directory.next_ifd_offset
    elif create_ifd1:
        action = "create_ifd1"
        planned_next_ifd_offset = 0
    else:
        action = "write_zero_pointer"
        planned_next_ifd_offset = 0
    return TiffNextIfdPointerPlan(
        action=action,
        pointer_offset=pointer_offset,
        original_next_ifd_offset=directory.next_ifd_offset,
        planned_next_ifd_offset=planned_next_ifd_offset,
        has_pointer_slot=True,
        evidence_ids=(WRITE_EXIF_NEXT_IFD_SOURCE,),
    )


def plan_subifd_schedules(
    parent_directory_name: str,
    ordered_entries: tuple[TiffEntryLayoutPlan, ...],
    subifd_tag_ids: tuple[int, ...] = (SUB_IFD_POINTER_TAG,),
) -> tuple[TiffSubIfdSchedule, ...]:
    schedules: list[TiffSubIfdSchedule] = []
    for entry in ordered_entries:
        if entry.tag_id not in subifd_tag_ids:
            continue
        for subdirectory_index in range(max(entry.count, 1)):
            if entry.count > 1:
                pointer_location: TiffSubIfdPointerLocation = "value_data_area"
                pointer_offset = (entry.planned_value_offset or entry.value_field_offset) + (
                    subdirectory_index * 4
                )
            else:
                pointer_location = "directory_entry"
                pointer_offset = entry.value_field_offset
            schedules.append(
                TiffSubIfdSchedule(
                    parent_directory_name=parent_directory_name,
                    parent_tag_id=entry.tag_id,
                    subdirectory_name=subifd_name(parent_directory_name, subdirectory_index),
                    subdirectory_index=subdirectory_index,
                    pointer_location=pointer_location,
                    pointer_offset=pointer_offset,
                    placeholder_value=0xFEEDF00D,
                    propagates_image_data=parent_directory_name in {"IFD0", "SubIFD"},
                    evidence_ids=(
                        WRITE_EXIF_SUBIFD_CREATE_SOURCE,
                        WRITE_EXIF_SUBIFD_REWRITE_SOURCE,
                    ),
                )
            )
    return tuple(schedules)


def subifd_name(parent_directory_name: str, subdirectory_index: int) -> str:
    if parent_directory_name == "MakerNotes":
        return "MakerNotes"
    return "SubIFD" if subdirectory_index == 0 else f"SubIFD{subdirectory_index}"


def plan_offset_pair_records(
    directory_name: str,
    ifd_index: int,
    entries: tuple[RawTiffEntry, ...],
    container_kind: TiffDirectoryContainerKind = "tiff",
    specs: tuple[TiffOffsetPairSpec, ...] = DEFAULT_OFFSET_PAIR_SPECS,
) -> tuple[TiffOffsetPairRecord, ...]:
    entries_by_tag = {entry.tag_id: entry for entry in entries}
    records: list[TiffOffsetPairRecord] = []
    for spec in specs:
        offset_entry = entries_by_tag.get(spec.offset_tag_id)
        byte_count_entry = entries_by_tag.get(spec.byte_count_tag_id)
        if offset_entry is None or byte_count_entry is None:
            continue
        counts_match = offset_entry.count == byte_count_entry.count
        gate_codes: list[TiffImageDataGateCode] = ["image_data_copy_requires_random_access_source"]
        if not counts_match:
            gate_codes.append("offset_pair_counts_must_match")
        if container_kind == "mrw_ttw":
            gate_codes.append("mrw_ttw_requires_four_byte_padding")
        records.append(
            TiffOffsetPairRecord(
                directory_name=directory_name,
                ifd_index=ifd_index,
                offset_tag_id=spec.offset_tag_id,
                byte_count_tag_id=spec.byte_count_tag_id,
                offset_tag_name=spec.offset_tag_name,
                byte_count_tag_name=spec.byte_count_tag_name,
                data_tag=spec.data_tag,
                offset_count=offset_entry.count,
                byte_count_count=byte_count_entry.count,
                counts_match=counts_match,
                pointer_tracking_required=True,
                image_data_copy_deferred=spec.is_image_data,
                gate_codes=tuple(gate_codes),
                evidence_ids=(
                    WRITE_EXIF_OFFSET_PAIR_SOURCE,
                    WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,
                ),
            )
        )
    return tuple(records)


def plan_image_data_copy_gates(
    offset_pairs: tuple[TiffOffsetPairRecord, ...],
    subifd_schedules: tuple[TiffSubIfdSchedule, ...],
    container_kind: TiffDirectoryContainerKind,
) -> tuple[TiffImageDataCopyGate, ...]:
    gates: list[TiffImageDataCopyGate] = list(BASE_IMAGE_DATA_COPY_GATES)
    if any(not pair.counts_match for pair in offset_pairs):
        gates.append(
            TiffImageDataCopyGate(
                "offset_pair_counts_must_match",
                ("offset_pair_records",),
                "Every offset tag must have the same element count as its byte-count pair.",
                "Abort image-data copy planning when offset and byte-count arrays disagree.",
                (WRITE_EXIF_OFFSET_PAIR_SOURCE, WRITE_EXIF_IMAGE_DATA_COPY_SOURCE),
            )
        )
    if has_strip_tile_conflict(offset_pairs):
        gates.append(
            TiffImageDataCopyGate(
                "strip_tile_conflict_requires_format_specific_handler",
                ("StripOffsets", "TileOffsets"),
                (
                    "A directory must not carry both strip and tile image data without "
                    "a format exception."
                ),
                (
                    "Require an ARW/Panasonic-specific handler before copying "
                    "double-referenced image data."
                ),
                (WRITE_EXIF_IMAGE_DATA_COPY_SOURCE,),
            )
        )
    if any(schedule.propagates_image_data for schedule in subifd_schedules):
        gates.append(
            TiffImageDataCopyGate(
                "subifd_image_data_requires_contained_fixup",
                ("subifd_schedules",),
                "First-level SubIFD image-data offsets require contained fixup records.",
                "Do not copy SubIFD image data until the contained fixup shift is known.",
                (WRITE_EXIF_SUBIFD_REWRITE_SOURCE, WRITE_EXIF_IMAGE_DATA_COPY_SOURCE),
            )
        )
    if container_kind == "mrw_ttw":
        gates.append(
            TiffImageDataCopyGate(
                "mrw_ttw_requires_four_byte_padding",
                ("mrw_ttw_directory_data",),
                (
                    "MRW TTW directory data must be padded to a four-byte boundary "
                    "before following data."
                ),
                "Do not emit MRW TTW bytes until the TTW length and padding are fixed.",
                (WRITE_EXIF_MRW_TTW_SOURCE,),
            )
        )
    return unique_gates(tuple(gates))


def has_strip_tile_conflict(offset_pairs: tuple[TiffOffsetPairRecord, ...]) -> bool:
    offset_tag_ids = {record.offset_tag_id for record in offset_pairs}
    return STRIP_OFFSETS_TAG in offset_tag_ids and TILE_OFFSETS_TAG in offset_tag_ids


def write_exif_directory_order(
    container_kind: TiffDirectoryContainerKind,
) -> tuple[str, ...]:
    if container_kind == "dng":
        return (
            "IFD0",
            "SubIFD",
            "GlobalParameters",
            "ExifIFD",
            "GPS",
            "InteropIFD",
            "CameraProfileIFD",
            "IFD1+",
            "Thumbnail/ImageData",
        )
    if container_kind == "mrw_ttw":
        return (
            "MRW_TTW_IFD0",
            "SubIFD",
            "GlobalParameters",
            "ExifIFD",
            "GPS",
            "InteropIFD",
            "IFD1+",
            "TTWPadding",
            "ImageData",
        )
    return (
        "IFD0",
        "SubIFD",
        "GlobalParameters",
        "ExifIFD",
        "GPS",
        "InteropIFD",
        "IFD1+",
        "Thumbnail/ImageData",
    )


def container_evidence_ids(
    container_kind: TiffDirectoryContainerKind,
) -> tuple[EvidenceId, ...]:
    if container_kind == "dng":
        return (WRITE_EXIF_DNG_TIFF_LIKE_IFD_SOURCE,)
    if container_kind == "mrw_ttw":
        return (WRITE_EXIF_MRW_TTW_SOURCE,)
    return ()


def unique_evidence_ids(evidence_ids: tuple[EvidenceId, ...]) -> tuple[EvidenceId, ...]:
    seen: set[EvidenceId] = set()
    unique: list[EvidenceId] = []
    for evidence_id in evidence_ids:
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        unique.append(evidence_id)
    return tuple(unique)


def unique_sources(evidence_ids: tuple[EvidenceId, ...]) -> tuple[EvidenceId, ...]:
    """Compatibility alias for callers still using the old planner helper name."""

    return unique_evidence_ids(evidence_ids)


def unique_gates(gates: tuple[TiffImageDataCopyGate, ...]) -> tuple[TiffImageDataCopyGate, ...]:
    seen: set[TiffImageDataGateCode] = set()
    unique: list[TiffImageDataCopyGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return [value for value in values]


def tag_id_hex(tag_id: int) -> str:
    return f"0x{tag_id:04X}"
