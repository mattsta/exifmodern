"""Typed WriteExif directory/value-buffer coordinate seam.

This module owns the byte-level seam between a rebuilt TIFF directory and the
value buffer appended after it.  It is intentionally smaller than a complete
WriteExif port: callers provide source-backed payload decisions, and this seam
records/publishes the exact byte coordinates that final raw-format emitters
need to patch inline pointer fields and append value-buffer payloads.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.tiff.directory_transaction_plan import (
    TiffDirectoryRebuildPlan,
    TiffDirectoryTransactionPlan,
    TiffEntryLayoutPlan,
    TiffNextIfdPointerPlan,
    plan_entry_layouts,
    tag_id_hex,
)
from exifmodern.formats.tiff.mutation import RawTiffEntry
from exifmodern.formats.tiff.primitives import TIFF_TYPE_LONG, Endian
from exifmodern.json_types import JsonArray, JsonObject

type EvidenceId = str
type TiffWriteExifFixupBuffer = Literal["directory_bytes", "value_buffer"]
type TiffWriteExifPointerValueFormat = Literal["int32u"]
type TiffWriteExifDirectoryPointerTarget = Literal[
    "SubIFD",
    "ExifIFD",
    "GPS",
    "InteropIFD",
]
type TiffWriteExifPayloadSource = Literal[
    "directory_value_data",
    "new_composite_value",
    "copied_image_data",
    "preserved_existing_offset_value",
    "none",
    "format_specific_payload",
]
type TiffWriteExifCoordinateStatus = Literal[
    "emittable",
    "invalid_value_field_offset",
    "value_buffer_start_mismatch",
    "payload_length_mismatch",
]
type TiffWriteExifRebuiltPayloadStatus = Literal[
    "ready",
    "empty_transaction",
    "directory_coordinate_blocked",
    "directory_position_mismatch",
    "directory_pointer_fixups_required",
    "image_data_offset_fixups_required",
    "subdirectory_fixups_required",
    "unsupported_next_ifd_action",
]

DIRECTORY_POINTER_TAGS: tuple[int, ...] = (
    0x014A,  # SubIFD
    0x8769,  # ExifIFD
    0x8825,  # GPS
    0xA005,  # InteropIFD
)
DIRECTORY_POINTER_TARGETS: dict[int, TiffWriteExifDirectoryPointerTarget] = {
    0x014A: "SubIFD",
    0x8769: "ExifIFD",
    0x8825: "GPS",
    0xA005: "InteropIFD",
}
DIRECTORY_POINTER_TAG_NAMES: dict[int, str] = {
    0x014A: "SubIFD",
    0x8769: "ExifIFDPointer",
    0x8825: "GPSInfo",
    0xA005: "InteropOffset",
}
UINT32_MAX = 0xFFFFFFFF

WRITE_EXIF_VALUE_BUFFER_ASSEMBLY_SOURCE = "tiff.write_exif.value_buffer_assembly"
WRITE_EXIF_DIRECTORY_COORDINATE_SOURCE = "tiff.write_exif.directory_coordinate"
WRITE_EXIF_SUBDIRECTORY_FIXUP_SOURCE = "tiff.write_exif.subdirectory_fixup"
WRITE_EXIF_DIRECTORY_POINTER_FIXUP_SOURCE = "tiff.write_exif.directory_pointer_fixup"
WRITE_EXIF_NEWDATAPOS_FIXUP_SOURCE = "tiff.write_exif.newdatapos_fixup"
WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE = "tiff.write_exif.image_data_fixup"
WRITE_EXIF_INLINE_IMAGE_DATA_APPEND_SOURCE = "tiff.write_exif.inline_image_data_append"
WRITE_EXIF_ODD_VALUE_BUFFER_SOURCE = "tiff.write_exif.odd_value_buffer"


@dataclass(frozen=True)
class TiffWriteExifRebuiltDirectoryPayload:
    status: TiffWriteExifRebuiltPayloadStatus
    container_kind: str
    endian: Endian
    tiff_rewrite_base_offset: int
    directory_coordinates: tuple[TiffWriteExifValueBufferCoordinates, ...]
    rebuilt_tiff_payload: bytes | None
    last_ifd_offset: int | None
    blocked_directory_name: str | None
    reason: str
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_feed_container_emitter(self) -> bool:
        return self.status == "ready"

    @property
    def directory_count(self) -> int:
        return len(self.directory_coordinates)

    @property
    def rebuilt_tiff_payload_byte_count(self) -> int | None:
        if self.rebuilt_tiff_payload is None:
            return None
        return len(self.rebuilt_tiff_payload)

    def to_json(self) -> JsonObject:
        return {
            "blocked_directory_name": self.blocked_directory_name,
            "can_feed_container_emitter": self.can_feed_container_emitter,
            "container_kind": self.container_kind,
            "directory_coordinates": json_object_array(
                coordinates.to_json() for coordinates in self.directory_coordinates
            ),
            "directory_count": self.directory_count,
            "endian": self.endian,
            "last_ifd_offset": self.last_ifd_offset,
            "reason": self.reason,
            "rebuilt_tiff_payload_byte_count": self.rebuilt_tiff_payload_byte_count,
            "status": self.status,
            "tiff_rewrite_base_offset": self.tiff_rewrite_base_offset,
        }


@dataclass(frozen=True)
class TiffWriteExifFixupRecord:
    buffer_name: TiffWriteExifFixupBuffer
    offset: int
    target: str | None
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "buffer_name": self.buffer_name,
            "offset": self.offset,
            "target": self.target,
        }


@dataclass(frozen=True)
class TiffWriteExifImageDataPlacement:
    directory_name: str
    ifd_offset: int
    offset_tag_id: int
    byte_count_tag_id: int
    original_offset: int
    byte_count: int
    output_offset: int
    padding_byte_count: int
    evidence_ids: tuple[EvidenceId, ...]
    appended_payload: bytes | None = None

    @property
    def copied_end_offset(self) -> int:
        return self.output_offset + self.byte_count

    @property
    def padded_end_offset(self) -> int:
        return self.copied_end_offset + self.padding_byte_count

    @property
    def appends_to_rebuilt_tiff_payload(self) -> bool:
        return self.appended_payload is not None

    def to_json(self) -> JsonObject:
        return {
            "appended_payload_byte_count": (
                len(self.appended_payload) if self.appended_payload is not None else None
            ),
            "appends_to_rebuilt_tiff_payload": self.appends_to_rebuilt_tiff_payload,
            "byte_count": self.byte_count,
            "byte_count_tag_id": tag_id_hex(self.byte_count_tag_id),
            "copied_end_offset": self.copied_end_offset,
            "directory_name": self.directory_name,
            "ifd_offset": self.ifd_offset,
            "offset_tag_id": tag_id_hex(self.offset_tag_id),
            "original_offset": self.original_offset,
            "output_offset": self.output_offset,
            "padded_end_offset": self.padded_end_offset,
            "padding_byte_count": self.padding_byte_count,
        }


@dataclass(frozen=True)
class TiffWriteExifInlinePointerValueField:
    directory_name: str
    tag_id: int
    tag_name: str
    data_tag: str | None
    value_format: TiffWriteExifPointerValueFormat
    value_field_offset: int
    tiff_value_field_offset: int
    stored_offset_value: int
    encoded_value: bytes
    fixup_record: TiffWriteExifFixupRecord
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "data_tag": self.data_tag,
            "directory_name": self.directory_name,
            "encoded_value_hex": self.encoded_value.hex(),
            "fixup_record": self.fixup_record.to_json(),
            "offset_tag_id": tag_id_hex(self.tag_id),
            "offset_tag_name": self.tag_name,
            "stored_offset_value": self.stored_offset_value,
            "tiff_value_field_offset": self.tiff_value_field_offset,
            "value_field_offset": self.value_field_offset,
            "value_format": self.value_format,
        }


@dataclass(frozen=True)
class TiffWriteExifDirectoryPointerPatch:
    directory_name: str
    tag_id: int
    tag_name: str
    target_directory_name: TiffWriteExifDirectoryPointerTarget
    value_format: TiffWriteExifPointerValueFormat
    value_field_offset: int
    tiff_value_field_offset: int
    original_offset_value: int
    rebuilt_target_offset: int
    encoded_value: bytes
    fixup_record: TiffWriteExifFixupRecord
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "directory_name": self.directory_name,
            "encoded_value_hex": self.encoded_value.hex(),
            "fixup_record": self.fixup_record.to_json(),
            "offset_tag_id": tag_id_hex(self.tag_id),
            "offset_tag_name": self.tag_name,
            "original_offset_value": self.original_offset_value,
            "rebuilt_target_offset": self.rebuilt_target_offset,
            "target_directory_name": self.target_directory_name,
            "tiff_value_field_offset": self.tiff_value_field_offset,
            "value_field_offset": self.value_field_offset,
            "value_format": self.value_format,
        }


@dataclass(frozen=True)
class TiffWriteExifAppendedPayloadRange:
    payload_source: TiffWriteExifPayloadSource
    value_buffer_start_offset: int
    payload_start_offset: int
    payload_byte_count: int
    appends_payload: bool
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def payload_end_offset(self) -> int:
        return self.payload_start_offset + self.payload_byte_count

    def to_json(self) -> JsonObject:
        return {
            "appends_payload": self.appends_payload,
            "payload_byte_count": self.payload_byte_count,
            "payload_end_offset": self.payload_end_offset,
            "payload_source": self.payload_source,
            "payload_start_offset": self.payload_start_offset,
            "value_buffer_start_offset": self.value_buffer_start_offset,
        }


@dataclass(frozen=True)
class TiffWriteExifValueBufferCoordinates:
    status: TiffWriteExifCoordinateStatus
    directory_name: str
    directory_bytes: bytes
    value_buffer_start_offset: int
    value_buffer: bytes
    inline_pointer_value_fields: tuple[TiffWriteExifInlinePointerValueField, ...]
    directory_pointer_patches: tuple[TiffWriteExifDirectoryPointerPatch, ...]
    appended_payload_ranges: tuple[TiffWriteExifAppendedPayloadRange, ...]
    image_data_placements: tuple[TiffWriteExifImageDataPlacement, ...]
    fixup_records: tuple[TiffWriteExifFixupRecord, ...]
    reason: str
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def byte_output_enabled(self) -> bool:
        return self.status == "emittable"

    def to_json(self) -> JsonObject:
        return {
            "appended_payload_ranges": json_object_array(
                payload_range.to_json() for payload_range in self.appended_payload_ranges
            ),
            "byte_output_enabled": self.byte_output_enabled,
            "directory_byte_count": len(self.directory_bytes),
            "directory_name": self.directory_name,
            "directory_pointer_patches": json_object_array(
                pointer.to_json() for pointer in self.directory_pointer_patches
            ),
            "fixup_records": json_object_array(record.to_json() for record in self.fixup_records),
            "inline_pointer_value_fields": json_object_array(
                pointer.to_json() for pointer in self.inline_pointer_value_fields
            ),
            "image_data_placements": json_object_array(
                placement.to_json() for placement in self.image_data_placements
            ),
            "reason": self.reason,
            "status": self.status,
            "value_buffer_byte_count": len(self.value_buffer),
            "value_buffer_start_offset": self.value_buffer_start_offset,
        }


def build_tiff_write_exif_directory_value_buffer_coordinates(
    rebuild_plan: TiffDirectoryRebuildPlan,
    endian: Endian,
) -> TiffWriteExifValueBufferCoordinates:
    """Build directory bytes plus the initial WriteExif valBuff coordinates."""

    value_buffer = bytearray()
    encoded_entries: list[bytes] = []
    pointers: list[TiffWriteExifInlinePointerValueField] = []
    fixups: list[TiffWriteExifFixupRecord] = []
    payload_ranges: list[TiffWriteExifAppendedPayloadRange] = []

    for entry_layout in rebuild_plan.ordered_entries:
        entry = entry_layout.source_entry
        directory_value_field_offset = (
            entry_layout.value_field_offset - rebuild_plan.directory_start
        )
        if entry_layout.value_storage == "value_data_area":
            payload_start = rebuild_plan.value_data_area.start_offset + len(value_buffer)
            encoded_value = payload_start.to_bytes(4, endian)
            fixup = TiffWriteExifFixupRecord(
                buffer_name="directory_bytes",
                offset=directory_value_field_offset,
                target=None,
                evidence_ids=(WRITE_EXIF_VALUE_BUFFER_ASSEMBLY_SOURCE,),
            )
            pointer = TiffWriteExifInlinePointerValueField(
                directory_name=rebuild_plan.directory_name,
                tag_id=entry.tag_id,
                tag_name=tag_id_hex(entry.tag_id),
                data_tag=None,
                value_format="int32u",
                value_field_offset=directory_value_field_offset,
                tiff_value_field_offset=entry_layout.value_field_offset,
                stored_offset_value=payload_start,
                encoded_value=encoded_value,
                fixup_record=fixup,
                evidence_ids=(
                    WRITE_EXIF_VALUE_BUFFER_ASSEMBLY_SOURCE,
                    WRITE_EXIF_DIRECTORY_COORDINATE_SOURCE,
                ),
            )
            pointers.append(pointer)
            fixups.append(fixup)
            value_buffer.extend(entry.raw_value)
            payload_ranges.append(
                TiffWriteExifAppendedPayloadRange(
                    payload_source="directory_value_data",
                    value_buffer_start_offset=rebuild_plan.value_data_area.start_offset,
                    payload_start_offset=payload_start,
                    payload_byte_count=len(entry.raw_value),
                    appends_payload=True,
                    evidence_ids=(WRITE_EXIF_VALUE_BUFFER_ASSEMBLY_SOURCE,),
                )
            )
        else:
            encoded_value = inline_value_field(entry.raw_value)
        encoded_entries.append(encode_tiff_entry(entry, encoded_value, endian))

    directory_bytes = (
        len(encoded_entries).to_bytes(2, endian)
        + b"".join(encoded_entries)
        + rebuild_plan.next_ifd_pointer.planned_next_ifd_offset.to_bytes(4, endian)
    )
    return TiffWriteExifValueBufferCoordinates(
        status="emittable",
        directory_name=rebuild_plan.directory_name,
        directory_bytes=directory_bytes,
        value_buffer_start_offset=rebuild_plan.value_data_area.start_offset,
        value_buffer=bytes(value_buffer),
        inline_pointer_value_fields=tuple(pointers),
        directory_pointer_patches=(),
        appended_payload_ranges=tuple(payload_ranges),
        image_data_placements=(),
        fixup_records=tuple(fixups),
        reason="Built WriteExif-compatible directory bytes and initial valBuff coordinates.",
        evidence_ids=(
            WRITE_EXIF_VALUE_BUFFER_ASSEMBLY_SOURCE,
            WRITE_EXIF_DIRECTORY_COORDINATE_SOURCE,
            WRITE_EXIF_SUBDIRECTORY_FIXUP_SOURCE,
        ),
    )


def build_tiff_write_exif_rebuilt_directory_payload(
    transaction_plan: TiffDirectoryTransactionPlan,
    endian: Endian,
    tiff_rewrite_base_offset: int = 0,
    image_data_placements: tuple[TiffWriteExifImageDataPlacement, ...] = (),
) -> TiffWriteExifRebuiltDirectoryPayload:
    """Build a bounded WriteExif directory payload from a transaction plan.

    This emits only the subset already represented by this module: directory
    entries plus their immediate value buffer.  Pointer-bearing subdirectories
    stay blocked; inline Exif/GPS/Interop directory pointers and image-data
    offset pairs are patched only when exact rebuilt coordinates are available.
    """

    if not transaction_plan.directory_plans:
        return blocked_rebuilt_payload(
            "empty_transaction",
            transaction_plan,
            endian,
            tiff_rewrite_base_offset,
            (),
            None,
            "A rebuilt TIFF payload requires at least one staged directory.",
        )

    output = bytearray()
    coordinates: list[TiffWriteExifValueBufferCoordinates] = []
    last_ifd_offset: int | None = None
    exact_directory_offsets = exact_rebuilt_directory_offsets(
        transaction_plan,
        tiff_rewrite_base_offset,
        image_data_placements,
    )
    rebuilt_offsets_by_original_offset = rebuilt_directory_offsets_by_original_offset(
        transaction_plan,
        exact_directory_offsets,
    )

    for directory_plan in transaction_plan.directory_plans:
        current_absolute_offset = tiff_rewrite_base_offset + len(output)
        if current_absolute_offset > UINT32_MAX:
            return blocked_rebuilt_payload(
                "directory_position_mismatch",
                transaction_plan,
                endian,
                tiff_rewrite_base_offset,
                tuple(coordinates),
                directory_plan.directory_name,
                "The rebuilt directory offset exceeds the bounded int32u TIFF offset range.",
            )
        effective_directory_plan = rebase_tiff_directory_rebuild_plan(
            directory_plan,
            current_absolute_offset,
        )
        if directory_plan.subifd_schedules:
            return blocked_rebuilt_payload(
                "subdirectory_fixups_required",
                transaction_plan,
                endian,
                tiff_rewrite_base_offset,
                tuple(coordinates),
                directory_plan.directory_name,
                (
                    "SubIFD payloads require WriteExif placeholder patching before "
                    "the rebuilt TIFF payload can be emitted."
                ),
            )
        directory_image_data_placements = tuple(
            placement
            for placement in image_data_placements
            if placement.ifd_offset == directory_plan.directory_start
        )
        if effective_directory_plan.offset_pairs and not can_patch_directory_image_data_offsets(
            effective_directory_plan,
            directory_image_data_placements,
        ):
            return blocked_rebuilt_payload(
                "image_data_offset_fixups_required",
                transaction_plan,
                endian,
                tiff_rewrite_base_offset,
                tuple(coordinates),
                directory_plan.directory_name,
                (
                    "Image-data offset pairs require one tracked copied-data "
                    "placement per inline int32u offset before emit."
                ),
            )
        directory_coordinates = build_tiff_write_exif_directory_value_buffer_coordinates(
            effective_directory_plan,
            endian,
        )
        if not directory_coordinates.byte_output_enabled:
            return blocked_rebuilt_payload(
                "directory_coordinate_blocked",
                transaction_plan,
                endian,
                tiff_rewrite_base_offset,
                tuple((*coordinates, directory_coordinates)),
                directory_plan.directory_name,
                directory_coordinates.reason,
            )
        if directory_image_data_placements:
            directory_coordinates = apply_tiff_write_exif_image_data_offset_fixups(
                directory_coordinates,
                effective_directory_plan,
                directory_image_data_placements,
                endian,
            )
            if not directory_coordinates.byte_output_enabled:
                return blocked_rebuilt_payload(
                    "directory_coordinate_blocked",
                    transaction_plan,
                    endian,
                    tiff_rewrite_base_offset,
                    tuple((*coordinates, directory_coordinates)),
                    directory_plan.directory_name,
                    directory_coordinates.reason,
                )
        if directory_has_unpatchable_directory_pointer(
            effective_directory_plan,
            exact_directory_offsets,
        ):
            return blocked_rebuilt_payload(
                "directory_pointer_fixups_required",
                transaction_plan,
                endian,
                tiff_rewrite_base_offset,
                tuple((*coordinates, directory_coordinates)),
                directory_plan.directory_name,
                (
                    "Exif/GPS/Interop/SubIFD pointer entries require exact rebuilt "
                    "target coordinates and inline int32u pointer fields before emit."
                ),
            )
        directory_coordinates = apply_tiff_write_exif_directory_pointer_fixups(
            directory_coordinates,
            effective_directory_plan,
            exact_directory_offsets,
            endian,
        )
        if not directory_coordinates.byte_output_enabled:
            return blocked_rebuilt_payload(
                "directory_coordinate_blocked",
                transaction_plan,
                endian,
                tiff_rewrite_base_offset,
                tuple((*coordinates, directory_coordinates)),
                directory_plan.directory_name,
                directory_coordinates.reason,
            )

        if effective_directory_plan.next_ifd_pointer.action == "link_existing_next_ifd":
            rebuilt_next_ifd_offset = rebuilt_offsets_by_original_offset.get(
                effective_directory_plan.next_ifd_pointer.original_next_ifd_offset
            )
            if rebuilt_next_ifd_offset is None:
                return blocked_rebuilt_payload(
                    "unsupported_next_ifd_action",
                    transaction_plan,
                    endian,
                    tiff_rewrite_base_offset,
                    tuple((*coordinates, directory_coordinates)),
                    directory_plan.directory_name,
                    (
                        "The linked next-IFD target is not staged with an exact "
                        "rebuilt directory coordinate."
                    ),
                )
            directory_coordinates = apply_tiff_write_exif_next_ifd_pointer_fixup(
                directory_coordinates,
                effective_directory_plan,
                rebuilt_next_ifd_offset,
                endian,
            )
            if not directory_coordinates.byte_output_enabled:
                return blocked_rebuilt_payload(
                    "directory_coordinate_blocked",
                    transaction_plan,
                    endian,
                    tiff_rewrite_base_offset,
                    tuple((*coordinates, directory_coordinates)),
                    directory_plan.directory_name,
                    directory_coordinates.reason,
                )

        output.extend(directory_coordinates.directory_bytes)
        output.extend(directory_coordinates.value_buffer)
        coordinates.append(directory_coordinates)
        last_ifd_offset = effective_directory_plan.next_ifd_pointer.pointer_offset

        if (
            effective_directory_plan.next_ifd_pointer.action == "write_zero_pointer"
            or effective_directory_plan.next_ifd_pointer.action == "link_existing_next_ifd"
        ):
            continue
        else:
            return blocked_rebuilt_payload(
                "unsupported_next_ifd_action",
                transaction_plan,
                endian,
                tiff_rewrite_base_offset,
                tuple(coordinates),
                directory_plan.directory_name,
                "The bounded rebuilt payload supports only zero or linked next-IFD pointers.",
            )

    return TiffWriteExifRebuiltDirectoryPayload(
        status="ready",
        container_kind=transaction_plan.container_kind,
        endian=endian,
        tiff_rewrite_base_offset=tiff_rewrite_base_offset,
        directory_coordinates=tuple(coordinates),
        rebuilt_tiff_payload=bytes(output),
        last_ifd_offset=last_ifd_offset,
        blocked_directory_name=None,
        reason="Built a bounded WriteExif directory payload from staged directory bytes.",
        evidence_ids=unique_evidence_ids(
            (
                *transaction_plan.evidence_ids,
                WRITE_EXIF_DIRECTORY_COORDINATE_SOURCE,
                WRITE_EXIF_SUBDIRECTORY_FIXUP_SOURCE,
                WRITE_EXIF_DIRECTORY_POINTER_FIXUP_SOURCE,
                WRITE_EXIF_NEWDATAPOS_FIXUP_SOURCE,
                *(
                    evidence_id
                    for coordinate in coordinates
                    for evidence_id in coordinate.evidence_ids
                ),
            )
        ),
    )


def apply_tiff_write_exif_next_ifd_pointer_fixup(
    coordinates: TiffWriteExifValueBufferCoordinates,
    rebuild_plan: TiffDirectoryRebuildPlan,
    rebuilt_next_ifd_offset: int,
    endian: Endian,
) -> TiffWriteExifValueBufferCoordinates:
    if rebuilt_next_ifd_offset > UINT32_MAX:
        return blocked_coordinates(
            coordinates,
            "payload_length_mismatch",
            "The rebuilt next-IFD target exceeds the bounded int32u TIFF offset range.",
        )
    pointer_offset = rebuild_plan.next_ifd_pointer.pointer_offset - rebuild_plan.directory_start
    pointer_end = pointer_offset + 4
    if pointer_offset < 0 or pointer_end > len(coordinates.directory_bytes):
        return blocked_coordinates(
            coordinates,
            "invalid_value_field_offset",
            "The next-IFD pointer slot is outside the rebuilt directory bytes.",
        )
    rewritten_directory = bytearray(coordinates.directory_bytes)
    rewritten_directory[pointer_offset:pointer_end] = rebuilt_next_ifd_offset.to_bytes(4, endian)
    fixup = TiffWriteExifFixupRecord(
        buffer_name="directory_bytes",
        offset=pointer_offset,
        target="NextIFD",
        evidence_ids=(
            WRITE_EXIF_DIRECTORY_COORDINATE_SOURCE,
            WRITE_EXIF_NEWDATAPOS_FIXUP_SOURCE,
        ),
    )
    return TiffWriteExifValueBufferCoordinates(
        status="emittable",
        directory_name=coordinates.directory_name,
        directory_bytes=bytes(rewritten_directory),
        value_buffer_start_offset=coordinates.value_buffer_start_offset,
        value_buffer=coordinates.value_buffer,
        inline_pointer_value_fields=coordinates.inline_pointer_value_fields,
        directory_pointer_patches=coordinates.directory_pointer_patches,
        appended_payload_ranges=coordinates.appended_payload_ranges,
        image_data_placements=coordinates.image_data_placements,
        fixup_records=(*coordinates.fixup_records, fixup),
        reason="Patched WriteExif next-IFD pointer to the staged linked directory.",
        evidence_ids=unique_evidence_ids(
            (
                *coordinates.evidence_ids,
                WRITE_EXIF_DIRECTORY_COORDINATE_SOURCE,
                WRITE_EXIF_NEWDATAPOS_FIXUP_SOURCE,
            )
        ),
    )


def apply_tiff_write_exif_value_buffer_append(
    coordinates: TiffWriteExifValueBufferCoordinates,
    pointer: TiffWriteExifInlinePointerValueField,
    payload: bytes,
    payload_source: TiffWriteExifPayloadSource,
    expected_payload_start_offset: int,
) -> TiffWriteExifValueBufferCoordinates:
    """Patch one inline pointer field and append a payload to the value buffer."""

    value_field_end = pointer.value_field_offset + len(pointer.encoded_value)
    actual_payload_start_offset = coordinates.value_buffer_start_offset + len(
        coordinates.value_buffer
    )
    if pointer.value_field_offset < 0 or value_field_end > len(coordinates.directory_bytes):
        return blocked_coordinates(
            coordinates,
            "invalid_value_field_offset",
            "The pointer value field is outside the rebuilt directory bytes.",
        )
    if actual_payload_start_offset != expected_payload_start_offset:
        return blocked_coordinates(
            coordinates,
            "value_buffer_start_mismatch",
            "The supplied value buffer length does not match the planned valBuff start.",
        )
    if len(payload) == 0 and payload_source != "none":
        return blocked_coordinates(
            coordinates,
            "payload_length_mismatch",
            "A non-empty value-buffer payload is required for this append operation.",
        )

    rewritten_directory = (
        coordinates.directory_bytes[: pointer.value_field_offset]
        + pointer.encoded_value
        + coordinates.directory_bytes[value_field_end:]
    )
    append_range = TiffWriteExifAppendedPayloadRange(
        payload_source=payload_source,
        value_buffer_start_offset=coordinates.value_buffer_start_offset,
        payload_start_offset=actual_payload_start_offset,
        payload_byte_count=len(payload),
        appends_payload=payload_source != "none",
        evidence_ids=(WRITE_EXIF_ODD_VALUE_BUFFER_SOURCE, WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE),
    )
    return TiffWriteExifValueBufferCoordinates(
        status="emittable",
        directory_name=coordinates.directory_name,
        directory_bytes=rewritten_directory,
        value_buffer=coordinates.value_buffer + payload,
        value_buffer_start_offset=coordinates.value_buffer_start_offset,
        inline_pointer_value_fields=(*coordinates.inline_pointer_value_fields, pointer),
        directory_pointer_patches=coordinates.directory_pointer_patches,
        appended_payload_ranges=(*coordinates.appended_payload_ranges, append_range),
        image_data_placements=coordinates.image_data_placements,
        fixup_records=(*coordinates.fixup_records, pointer.fixup_record),
        reason="Patched inline pointer value field and appended payload to valBuff.",
        evidence_ids=unique_evidence_ids(
            (
                *coordinates.evidence_ids,
                WRITE_EXIF_ODD_VALUE_BUFFER_SOURCE,
                WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
            )
        ),
    )


def apply_tiff_write_exif_directory_pointer_fixups(
    coordinates: TiffWriteExifValueBufferCoordinates,
    rebuild_plan: TiffDirectoryRebuildPlan,
    exact_directory_offsets: dict[str, int],
    endian: Endian,
) -> TiffWriteExifValueBufferCoordinates:
    rewritten_directory = bytearray(coordinates.directory_bytes)
    patches: list[TiffWriteExifDirectoryPointerPatch] = []
    fixups: list[TiffWriteExifFixupRecord] = []

    for entry_layout in rebuild_plan.ordered_entries:
        target_directory_name = DIRECTORY_POINTER_TARGETS.get(entry_layout.tag_id)
        if target_directory_name is None:
            continue
        rebuilt_target_offset = exact_directory_offsets.get(target_directory_name)
        if rebuilt_target_offset is None:
            return blocked_coordinates(
                coordinates,
                "payload_length_mismatch",
                "Missing rebuilt target coordinate for a directory pointer tag.",
            )
        if not directory_pointer_entry_is_inline_int32u(entry_layout):
            return blocked_coordinates(
                coordinates,
                "payload_length_mismatch",
                "Only inline single int32u directory pointer fields are supported.",
            )
        value_field_offset = entry_layout.value_field_offset - rebuild_plan.directory_start
        original_offset_value = int.from_bytes(entry_layout.source_entry.raw_value, endian)
        patch = tiff_write_exif_directory_pointer_patch(
            directory_name=rebuild_plan.directory_name,
            tag_id=entry_layout.tag_id,
            tag_name=DIRECTORY_POINTER_TAG_NAMES[entry_layout.tag_id],
            target_directory_name=target_directory_name,
            value_field_offset=value_field_offset,
            tiff_value_field_offset=entry_layout.value_field_offset,
            original_offset_value=original_offset_value,
            rebuilt_target_offset=rebuilt_target_offset,
            endian=endian,
        )
        value_field_end = patch.value_field_offset + len(patch.encoded_value)
        if patch.value_field_offset < 0 or value_field_end > len(rewritten_directory):
            return blocked_coordinates(
                coordinates,
                "invalid_value_field_offset",
                "The directory pointer value field is outside the rebuilt directory bytes.",
            )
        rewritten_directory[patch.value_field_offset : value_field_end] = patch.encoded_value
        patches.append(patch)
        fixups.append(patch.fixup_record)

    if not patches:
        return coordinates
    return TiffWriteExifValueBufferCoordinates(
        status="emittable",
        directory_name=coordinates.directory_name,
        directory_bytes=bytes(rewritten_directory),
        value_buffer_start_offset=coordinates.value_buffer_start_offset,
        value_buffer=coordinates.value_buffer,
        inline_pointer_value_fields=coordinates.inline_pointer_value_fields,
        directory_pointer_patches=(*coordinates.directory_pointer_patches, *patches),
        appended_payload_ranges=coordinates.appended_payload_ranges,
        image_data_placements=coordinates.image_data_placements,
        fixup_records=(*coordinates.fixup_records, *fixups),
        reason="Patched WriteExif directory pointer fields to rebuilt directory positions.",
        evidence_ids=unique_evidence_ids(
            (
                *coordinates.evidence_ids,
                WRITE_EXIF_DIRECTORY_POINTER_FIXUP_SOURCE,
                WRITE_EXIF_NEWDATAPOS_FIXUP_SOURCE,
            )
        ),
    )


def apply_tiff_write_exif_image_data_offset_fixups(
    coordinates: TiffWriteExifValueBufferCoordinates,
    rebuild_plan: TiffDirectoryRebuildPlan,
    placements: tuple[TiffWriteExifImageDataPlacement, ...],
    endian: Endian,
) -> TiffWriteExifValueBufferCoordinates:
    rewritten_directory = bytearray(coordinates.directory_bytes)
    rewritten_value_buffer = bytearray(coordinates.value_buffer)
    pointers: list[TiffWriteExifInlinePointerValueField] = []
    fixups: list[TiffWriteExifFixupRecord] = []
    payload_ranges: list[TiffWriteExifAppendedPayloadRange] = []
    placement_by_tag = {placement.offset_tag_id: placement for placement in placements}

    for offset_pair in rebuild_plan.offset_pairs:
        placement = placement_by_tag.get(offset_pair.offset_tag_id)
        if placement is None:
            return blocked_coordinates(
                coordinates,
                "payload_length_mismatch",
                "Missing copied image-data placement for an offset-pair tag.",
            )
        entry_layout = entry_layout_by_tag_id(rebuild_plan, offset_pair.offset_tag_id)
        if (
            entry_layout is None
            or entry_layout.count != 1
            or len(entry_layout.source_entry.raw_value) != 4
        ):
            return blocked_coordinates(
                coordinates,
                "payload_length_mismatch",
                "Only inline single int32u image-data offset fields are supported.",
            )
        appended_payload = placement.appended_payload
        if appended_payload is not None:
            expected_payload_start = coordinates.value_buffer_start_offset + len(
                rewritten_value_buffer
            )
            if placement.output_offset != expected_payload_start:
                return blocked_coordinates(
                    coordinates,
                    "value_buffer_start_mismatch",
                    (
                        "The inline image-data payload start does not match the "
                        "rebuilt directory value-buffer boundary."
                    ),
                )
            if len(appended_payload) != placement.byte_count:
                return blocked_coordinates(
                    coordinates,
                    "payload_length_mismatch",
                    "The inline image-data payload length must match the byte-count tag.",
                )
        value_field_offset = entry_layout.value_field_offset - rebuild_plan.directory_start
        pointer = tiff_write_exif_inline_pointer_value_field(
            directory_name=rebuild_plan.directory_name,
            tag_id=offset_pair.offset_tag_id,
            tag_name=offset_pair.offset_tag_name,
            data_tag=offset_pair.data_tag,
            value_field_offset=value_field_offset,
            tiff_value_field_offset=entry_layout.value_field_offset,
            stored_offset_value=placement.output_offset,
            endian=endian,
            evidence_ids=(WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,),
        )
        value_field_end = pointer.value_field_offset + len(pointer.encoded_value)
        if pointer.value_field_offset < 0 or value_field_end > len(rewritten_directory):
            return blocked_coordinates(
                coordinates,
                "invalid_value_field_offset",
                "The image-data offset value field is outside the rebuilt directory bytes.",
            )
        rewritten_directory[pointer.value_field_offset : value_field_end] = pointer.encoded_value
        pointers.append(pointer)
        fixups.append(pointer.fixup_record)
        if appended_payload is not None:
            payload = appended_payload + (b"\x00" * placement.padding_byte_count)
            rewritten_value_buffer.extend(payload)
            payload_ranges.append(
                TiffWriteExifAppendedPayloadRange(
                    payload_source="copied_image_data",
                    value_buffer_start_offset=coordinates.value_buffer_start_offset,
                    payload_start_offset=placement.output_offset,
                    payload_byte_count=len(payload),
                    appends_payload=True,
                    evidence_ids=(
                        WRITE_EXIF_INLINE_IMAGE_DATA_APPEND_SOURCE,
                        WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
                    ),
                )
            )

    return TiffWriteExifValueBufferCoordinates(
        status="emittable",
        directory_name=coordinates.directory_name,
        directory_bytes=bytes(rewritten_directory),
        value_buffer_start_offset=coordinates.value_buffer_start_offset,
        value_buffer=bytes(rewritten_value_buffer),
        inline_pointer_value_fields=(*coordinates.inline_pointer_value_fields, *pointers),
        directory_pointer_patches=coordinates.directory_pointer_patches,
        appended_payload_ranges=(*coordinates.appended_payload_ranges, *payload_ranges),
        image_data_placements=(*coordinates.image_data_placements, *placements),
        fixup_records=(*coordinates.fixup_records, *fixups),
        reason="Patched WriteExif image-data offset fields to copied payload positions.",
        evidence_ids=unique_evidence_ids(
            (
                *coordinates.evidence_ids,
                WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
                *((WRITE_EXIF_INLINE_IMAGE_DATA_APPEND_SOURCE,) if payload_ranges else ()),
            )
        ),
    )


def can_patch_directory_image_data_offsets(
    rebuild_plan: TiffDirectoryRebuildPlan,
    placements: tuple[TiffWriteExifImageDataPlacement, ...],
) -> bool:
    if len(placements) != len(rebuild_plan.offset_pairs):
        return False
    placement_by_tag = {placement.offset_tag_id: placement for placement in placements}
    for offset_pair in rebuild_plan.offset_pairs:
        placement = placement_by_tag.get(offset_pair.offset_tag_id)
        entry_layout = entry_layout_by_tag_id(rebuild_plan, offset_pair.offset_tag_id)
        if placement is None or entry_layout is None:
            return False
        if offset_pair.offset_count != 1 or not offset_pair.counts_match:
            return False
        if entry_layout.count != 1 or len(entry_layout.source_entry.raw_value) != 4:
            return False
        if placement.byte_count_tag_id != offset_pair.byte_count_tag_id:
            return False
    return True


def exact_rebuilt_directory_offsets(
    transaction_plan: TiffDirectoryTransactionPlan,
    tiff_rewrite_base_offset: int,
    image_data_placements: tuple[TiffWriteExifImageDataPlacement, ...] = (),
) -> dict[str, int]:
    offsets: dict[str, int] = {}
    current_offset = tiff_rewrite_base_offset
    appended_payload_byte_counts = appended_payload_byte_counts_by_ifd_offset(image_data_placements)
    for directory_plan in transaction_plan.directory_plans:
        if directory_plan.directory_name not in offsets:
            offsets[directory_plan.directory_name] = current_offset
        current_offset += projected_tiff_directory_payload_byte_count(directory_plan)
        current_offset += appended_payload_byte_counts.get(directory_plan.directory_start, 0)
    return offsets


def rebuilt_directory_offsets_by_original_offset(
    transaction_plan: TiffDirectoryTransactionPlan,
    exact_directory_offsets: dict[str, int],
) -> dict[int, int]:
    offsets: dict[int, int] = {}
    for directory_plan in transaction_plan.directory_plans:
        rebuilt_offset = exact_directory_offsets.get(directory_plan.directory_name)
        if rebuilt_offset is not None and directory_plan.directory_start not in offsets:
            offsets[directory_plan.directory_start] = rebuilt_offset
    return offsets


def projected_tiff_directory_payload_byte_count(
    rebuild_plan: TiffDirectoryRebuildPlan,
) -> int:
    return (
        2
        + len(rebuild_plan.ordered_entries) * 12
        + 4
        + sum(
            len(entry_layout.source_entry.raw_value)
            for entry_layout in rebuild_plan.ordered_entries
            if len(entry_layout.source_entry.raw_value) > 4
        )
    )


def appended_payload_byte_counts_by_ifd_offset(
    placements: tuple[TiffWriteExifImageDataPlacement, ...],
) -> dict[int, int]:
    byte_counts: dict[int, int] = {}
    for placement in placements:
        if placement.appended_payload is None:
            continue
        byte_counts[placement.ifd_offset] = byte_counts.get(placement.ifd_offset, 0) + (
            len(placement.appended_payload) + placement.padding_byte_count
        )
    return byte_counts


def rebase_tiff_directory_rebuild_plan(
    rebuild_plan: TiffDirectoryRebuildPlan,
    directory_start: int,
) -> TiffDirectoryRebuildPlan:
    if rebuild_plan.directory_start == directory_start:
        return rebuild_plan
    ordered_entries, value_data_area = plan_entry_layouts(
        rebuild_plan.planned_directory.entries,
        directory_start,
    )
    return TiffDirectoryRebuildPlan(
        container_kind=rebuild_plan.container_kind,
        directory_name=rebuild_plan.directory_name,
        ifd_index=rebuild_plan.ifd_index,
        directory_start=directory_start,
        endian=rebuild_plan.endian,
        original_directory=rebuild_plan.original_directory,
        planned_directory=rebuild_plan.planned_directory,
        ordered_entries=ordered_entries,
        value_data_area=value_data_area,
        next_ifd_pointer=TiffNextIfdPointerPlan(
            action=rebuild_plan.next_ifd_pointer.action,
            pointer_offset=directory_start + 2 + len(rebuild_plan.planned_directory.entries) * 12,
            original_next_ifd_offset=rebuild_plan.next_ifd_pointer.original_next_ifd_offset,
            planned_next_ifd_offset=rebuild_plan.next_ifd_pointer.planned_next_ifd_offset,
            has_pointer_slot=rebuild_plan.next_ifd_pointer.has_pointer_slot,
            evidence_ids=rebuild_plan.next_ifd_pointer.evidence_ids,
        ),
        subifd_schedules=rebuild_plan.subifd_schedules,
        offset_pairs=rebuild_plan.offset_pairs,
        image_data_copy_gates=rebuild_plan.image_data_copy_gates,
        evidence_ids=rebuild_plan.evidence_ids,
    )


def entry_layout_by_tag_id(
    rebuild_plan: TiffDirectoryRebuildPlan,
    tag_id: int,
) -> TiffEntryLayoutPlan | None:
    for entry_layout in rebuild_plan.ordered_entries:
        if entry_layout.tag_id == tag_id:
            return entry_layout
    return None


def directory_has_unpatchable_directory_pointer(
    rebuild_plan: TiffDirectoryRebuildPlan,
    exact_directory_offsets: dict[str, int],
) -> bool:
    for entry_layout in rebuild_plan.ordered_entries:
        target_directory_name = DIRECTORY_POINTER_TARGETS.get(entry_layout.tag_id)
        if target_directory_name is None:
            continue
        target_offset = exact_directory_offsets.get(target_directory_name)
        if target_offset is None or target_offset > UINT32_MAX:
            return True
        if not directory_pointer_entry_is_inline_int32u(entry_layout):
            return True
    return False


def directory_pointer_entry_is_inline_int32u(entry_layout: TiffEntryLayoutPlan) -> bool:
    return (
        entry_layout.value_storage == "inline_value"
        and entry_layout.field_type == TIFF_TYPE_LONG
        and entry_layout.count == 1
        and len(entry_layout.source_entry.raw_value) == 4
    )


def tiff_write_exif_directory_pointer_patch(
    directory_name: str,
    tag_id: int,
    tag_name: str,
    target_directory_name: TiffWriteExifDirectoryPointerTarget,
    value_field_offset: int,
    tiff_value_field_offset: int,
    original_offset_value: int,
    rebuilt_target_offset: int,
    endian: Endian,
) -> TiffWriteExifDirectoryPointerPatch:
    if value_field_offset < 0:
        raise ValueError("TIFF directory pointer value field offset must be non-negative.")
    encoded_value = rebuilt_target_offset.to_bytes(4, endian)
    fixup = TiffWriteExifFixupRecord(
        buffer_name="directory_bytes",
        offset=value_field_offset,
        target=target_directory_name,
        evidence_ids=(
            WRITE_EXIF_DIRECTORY_POINTER_FIXUP_SOURCE,
            WRITE_EXIF_NEWDATAPOS_FIXUP_SOURCE,
        ),
    )
    return TiffWriteExifDirectoryPointerPatch(
        directory_name=directory_name,
        tag_id=tag_id,
        tag_name=tag_name,
        target_directory_name=target_directory_name,
        value_format="int32u",
        value_field_offset=value_field_offset,
        tiff_value_field_offset=tiff_value_field_offset,
        original_offset_value=original_offset_value,
        rebuilt_target_offset=rebuilt_target_offset,
        encoded_value=encoded_value,
        fixup_record=fixup,
        evidence_ids=(
            WRITE_EXIF_DIRECTORY_POINTER_FIXUP_SOURCE,
            WRITE_EXIF_NEWDATAPOS_FIXUP_SOURCE,
        ),
    )


def tiff_write_exif_inline_pointer_value_field(
    directory_name: str,
    tag_id: int,
    tag_name: str,
    data_tag: str,
    value_field_offset: int,
    tiff_value_field_offset: int | None,
    stored_offset_value: int,
    endian: Endian,
    evidence_ids: tuple[EvidenceId, ...],
) -> TiffWriteExifInlinePointerValueField:
    if value_field_offset < 0:
        raise ValueError("TIFF pointer value field offset must be non-negative.")
    encoded_value = stored_offset_value.to_bytes(4, endian)
    fixup = TiffWriteExifFixupRecord(
        buffer_name="directory_bytes",
        offset=value_field_offset,
        target=data_tag,
        evidence_ids=evidence_ids,
    )
    return TiffWriteExifInlinePointerValueField(
        directory_name=directory_name,
        tag_id=tag_id,
        tag_name=tag_name,
        data_tag=data_tag,
        value_format="int32u",
        value_field_offset=value_field_offset,
        tiff_value_field_offset=(
            value_field_offset if tiff_value_field_offset is None else tiff_value_field_offset
        ),
        stored_offset_value=stored_offset_value,
        encoded_value=encoded_value,
        fixup_record=fixup,
        evidence_ids=evidence_ids,
    )


def blocked_rebuilt_payload(
    status: TiffWriteExifRebuiltPayloadStatus,
    transaction_plan: TiffDirectoryTransactionPlan,
    endian: Endian,
    tiff_rewrite_base_offset: int,
    coordinates: tuple[TiffWriteExifValueBufferCoordinates, ...],
    blocked_directory_name: str | None,
    reason: str,
) -> TiffWriteExifRebuiltDirectoryPayload:
    return TiffWriteExifRebuiltDirectoryPayload(
        status=status,
        container_kind=transaction_plan.container_kind,
        endian=endian,
        tiff_rewrite_base_offset=tiff_rewrite_base_offset,
        directory_coordinates=coordinates,
        rebuilt_tiff_payload=None,
        last_ifd_offset=None,
        blocked_directory_name=blocked_directory_name,
        reason=reason,
        evidence_ids=unique_evidence_ids(
            (
                *transaction_plan.evidence_ids,
                WRITE_EXIF_DIRECTORY_COORDINATE_SOURCE,
                WRITE_EXIF_SUBDIRECTORY_FIXUP_SOURCE,
                *(
                    evidence_id
                    for coordinate in coordinates
                    for evidence_id in coordinate.evidence_ids
                ),
            )
        ),
    )


def blocked_coordinates(
    coordinates: TiffWriteExifValueBufferCoordinates,
    status: TiffWriteExifCoordinateStatus,
    reason: str,
) -> TiffWriteExifValueBufferCoordinates:
    return TiffWriteExifValueBufferCoordinates(
        status=status,
        directory_name=coordinates.directory_name,
        directory_bytes=coordinates.directory_bytes,
        value_buffer_start_offset=coordinates.value_buffer_start_offset,
        value_buffer=coordinates.value_buffer,
        inline_pointer_value_fields=coordinates.inline_pointer_value_fields,
        directory_pointer_patches=coordinates.directory_pointer_patches,
        appended_payload_ranges=coordinates.appended_payload_ranges,
        image_data_placements=coordinates.image_data_placements,
        fixup_records=coordinates.fixup_records,
        reason=reason,
        evidence_ids=coordinates.evidence_ids,
    )


def encode_tiff_entry(entry: RawTiffEntry, value_field: bytes, endian: Endian) -> bytes:
    return (
        entry.tag_id.to_bytes(2, endian)
        + entry.field_type.to_bytes(2, endian)
        + entry.count.to_bytes(4, endian)
        + value_field
    )


def inline_value_field(raw_value: bytes) -> bytes:
    return raw_value[:4].ljust(4, b"\x00")


def unique_evidence_ids(evidence_ids: tuple[EvidenceId, ...]) -> tuple[EvidenceId, ...]:
    seen: set[EvidenceId] = set()
    unique: list[EvidenceId] = []
    for evidence_id in evidence_ids:
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        unique.append(evidence_id)
    return tuple(unique)


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return [value for value in values]
