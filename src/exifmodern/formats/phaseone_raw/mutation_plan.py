"""Source-backed Phase One IIQ mutation planning.

Phase One MakerNotes use custom IFD-like directories.  ExifTool rewrites those
directories by validating the header, rebuilding entries, buffering value data,
applying value-offset fixups, and patching the PhaseOneIFD pointer.  This module
only produces that typed plan and read-only header summaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.raw_family.write_plan import (
    RawFamilyBlockerCode,
    RawFamilyWriteRequestClassification,
    RawFamilyWriteSurface,
    classify_raw_family_golden_request_file,
)
from exifmodern.json_types import JsonObject

type PhaseOneByteOrder = Literal["little", "big"]
type PhaseOneEvidenceId = str
type PhaseOneIfdKind = Literal["phaseone_main_ifd", "sensor_calibration_ifd"]
type PhaseOneRawMutationPlanStatus = Literal["source_mapped_deferred", "unsupported"]
type PhaseOneRawMutationStepKind = Literal[
    "validate_phaseone_ifd_header",
    "read_phaseone_entry_table",
    "rewrite_main_serial_number_value",
    "rewrite_sensor_calibration_subifd",
    "pad_value_data_to_four_bytes",
    "apply_phaseone_value_offset_fixups",
    "patch_phaseone_ifd_pointer",
    "plan_phaseone_raw_data_copy_ranges",
    "return_rebuilt_phaseone_block",
]
type PhaseOneRawPrerequisite = Literal[
    "phaseone_ifd_header",
    "phaseone_entry_size",
    "requested_phaseone_raw_family_route",
    "serial_number_tag_definition",
    "sensor_calibration_tag_table",
    "phaseone_value_fixup_table",
    "phaseone_raw_data_tag_definition",
    "phaseone_image_data_hash_copy_loop",
]
type PhaseOneRawSafetyGate = Literal[
    "defer_without_phaseone_ifd_rebuilder",
    "defer_without_entry_size_validation",
    "defer_without_serial_value_encoder",
    "defer_without_sensor_calibration_rewriter",
    "defer_without_value_padding",
    "defer_without_value_offset_fixups",
    "defer_without_phaseone_ifd_pointer_patch",
    "defer_without_phaseone_raw_data_copy",
]

PHASEONE_MAIN_ENTRY_SIZE = 16
PHASEONE_SENSOR_CALIBRATION_ENTRY_SIZE = 12
PHASEONE_SERIAL_NUMBER_TAG = 0x0102
PHASEONE_SENSOR_CALIBRATION_TAG = 0x0110
PHASEONE_RAW_DATA_TAG = 0x010F
PHASEONE_IMAGE_DATA_HASH_CHUNK_SIZE = 65536

PHASEONE_MAIN_SOURCE: PhaseOneEvidenceId = "phaseone_raw.main"
PHASEONE_SERIAL_SOURCE: PhaseOneEvidenceId = "phaseone_raw.serial_number"
PHASEONE_SENSOR_CALIBRATION_SOURCE: PhaseOneEvidenceId = "phaseone_raw.sensor_calibration"
PHASEONE_WRITE_SOURCE: PhaseOneEvidenceId = "phaseone_raw.write_phaseone"
PHASEONE_RAW_DATA_SOURCE: PhaseOneEvidenceId = "phaseone_raw.raw_data"
PHASEONE_IMAGE_DATA_HASH_SOURCE: PhaseOneEvidenceId = "phaseone_raw.image_data_hash"


@dataclass(frozen=True)
class PhaseOneIfdEntrySummary:
    tag_id: int
    format_size: int | None
    value_size: int
    value_or_offset: int
    is_serial_number: bool
    is_sensor_calibration: bool

    def to_json(self) -> JsonObject:
        return {
            "format_size": self.format_size,
            "is_sensor_calibration": self.is_sensor_calibration,
            "is_serial_number": self.is_serial_number,
            "tag_id": f"0x{self.tag_id:04x}",
            "value_or_offset": self.value_or_offset,
            "value_size": self.value_size,
        }


@dataclass(frozen=True)
class PhaseOneIfdHeaderSummary:
    directory_offset: int
    byte_order: PhaseOneByteOrder
    ifd_kind: PhaseOneIfdKind
    entry_size: int
    ifd_start: int
    entry_count: int | None
    entries: tuple[PhaseOneIfdEntrySummary, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_order": self.byte_order,
            "directory_offset": self.directory_offset,
            "entries": [entry.to_json() for entry in self.entries],
            "entry_count": self.entry_count,
            "entry_size": self.entry_size,
            "ifd_kind": self.ifd_kind,
            "ifd_start": self.ifd_start,
        }


@dataclass(frozen=True)
class PhaseOneRawByteRange:
    start_offset: int
    end_offset: int

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset

    def to_json(self) -> JsonObject:
        return {
            "end_offset": self.end_offset,
            "length": self.length,
            "start_offset": self.start_offset,
        }


@dataclass(frozen=True)
class PhaseOneRawDataCopyRange:
    entry_index: int
    tag_id: int
    tag_name: str
    source_range: PhaseOneRawByteRange
    original_size: int
    put_first_in_rebuild: bool
    writable: bool
    hash_chunk_size: int
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "entry_index": self.entry_index,
            "hash_chunk_size": self.hash_chunk_size,
            "original_size": self.original_size,
            "put_first_in_rebuild": self.put_first_in_rebuild,
            "source_range": self.source_range.to_json(),
            "tag_id": f"0x{self.tag_id:04x}",
            "tag_name": self.tag_name,
            "writable": self.writable,
        }


@dataclass(frozen=True)
class PhaseOneRawDataPreservationPlan:
    status: PhaseOneRawMutationPlanStatus
    can_preserve_raw_data: bool
    copy_ranges: tuple[PhaseOneRawDataCopyRange, ...]
    blockers: tuple[PhaseOneRawSafetyGate, ...]
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "can_preserve_raw_data": self.can_preserve_raw_data,
            "copy_ranges": [copy_range.to_json() for copy_range in self.copy_ranges],
            "status": self.status,
        }


@dataclass(frozen=True)
class PhaseOneRawRequestedMutation:
    requested_tag: str
    requested_value: str
    generic_surfaces: tuple[RawFamilyWriteSurface, ...]
    generic_blockers: tuple[RawFamilyBlockerCode, ...]

    def to_json(self) -> JsonObject:
        return {
            "generic_blockers": list(self.generic_blockers),
            "generic_surfaces": list(self.generic_surfaces),
            "requested_tag": self.requested_tag,
            "requested_value": self.requested_value,
        }


@dataclass(frozen=True)
class PhaseOneRawMutationStep:
    kind: PhaseOneRawMutationStepKind
    description: str
    prerequisites: tuple[PhaseOneRawPrerequisite, ...]
    safety_gates: tuple[PhaseOneRawSafetyGate, ...]
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "description": self.description,
            "kind": self.kind,
            "prerequisites": list(self.prerequisites),
            "safety_gates": list(self.safety_gates),
        }


@dataclass(frozen=True)
class PhaseOneRawMutationPlan:
    status: PhaseOneRawMutationPlanStatus
    can_mutate: bool
    raw_family_request_id: str | None
    header: PhaseOneIfdHeaderSummary | None
    raw_data_preservation: PhaseOneRawDataPreservationPlan | None
    requested_mutations: tuple[PhaseOneRawRequestedMutation, ...]
    steps: tuple[PhaseOneRawMutationStep, ...]
    safety_gates: tuple[PhaseOneRawSafetyGate, ...]
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_mutate": self.can_mutate,
            "header": self.header.to_json() if self.header is not None else None,
            "raw_data_preservation": (
                self.raw_data_preservation.to_json()
                if self.raw_data_preservation is not None
                else None
            ),
            "raw_family_request_id": self.raw_family_request_id,
            "requested_mutations": [
                requested_mutation.to_json() for requested_mutation in self.requested_mutations
            ],
            "safety_gates": list(self.safety_gates),
            "status": self.status,
            "steps": [step.to_json() for step in self.steps],
        }


def load_phaseone_iiq_golden_mutation_plan(
    request_path: Path,
    data: bytes,
) -> PhaseOneRawMutationPlan:
    return build_phaseone_iiq_mutation_plan(
        data,
        classify_raw_family_golden_request_file(request_path),
    )


def build_phaseone_iiq_mutation_plan(
    data: bytes,
    raw_family_classification: RawFamilyWriteRequestClassification | None = None,
) -> PhaseOneRawMutationPlan:
    header = inspect_phaseone_ifd_header(data)
    requested_mutations = requested_mutations_from_raw_family(raw_family_classification)
    raw_data_preservation = build_phaseone_raw_data_preservation_plan(data, header)
    steps = phaseone_iiq_mutation_steps() if header is not None else ()
    status: PhaseOneRawMutationPlanStatus = (
        "source_mapped_deferred"
        if header is not None and raw_family_classification_is_phaseone(raw_family_classification)
        else "unsupported"
    )
    return PhaseOneRawMutationPlan(
        status=status,
        can_mutate=False,
        raw_family_request_id=(
            raw_family_classification.request_id if raw_family_classification is not None else None
        ),
        header=header,
        raw_data_preservation=raw_data_preservation,
        requested_mutations=requested_mutations,
        steps=steps,
        safety_gates=unique_safety_gates(steps),
        evidence_ids=plan_evidence_ids(raw_family_classification),
    )


def inspect_phaseone_ifd_header(data: bytes) -> PhaseOneIfdHeaderSummary | None:
    if len(data) < 20:
        return None
    directory_offset = find_phaseone_directory_offset(data)
    if directory_offset is None:
        return None
    byte_order = phaseone_byte_order(data, directory_offset)
    if byte_order is None:
        return None
    entry_size = phaseone_entry_size(data, directory_offset)
    if entry_size is None:
        return None
    ifd_kind: PhaseOneIfdKind = (
        "phaseone_main_ifd" if entry_size == PHASEONE_MAIN_ENTRY_SIZE else "sensor_calibration_ifd"
    )
    ifd_start = read_uint(data, directory_offset + 8, byte_order)
    if directory_offset + ifd_start + 8 > len(data):
        return None
    entry_count = read_uint(data, directory_offset + ifd_start, byte_order)
    if entry_count < 2 or entry_count > 300:
        return None
    return PhaseOneIfdHeaderSummary(
        directory_offset=directory_offset,
        byte_order=byte_order,
        ifd_kind=ifd_kind,
        entry_size=entry_size,
        ifd_start=ifd_start,
        entry_count=entry_count,
        entries=parse_phaseone_entries(
            data,
            directory_offset,
            ifd_start,
            entry_count,
            entry_size,
            byte_order,
        ),
    )


def find_phaseone_directory_offset(data: bytes) -> int | None:
    scan_limit = min(len(data) - 20, 4096)
    for offset in range(max(scan_limit, 0) + 1):
        byte_order = phaseone_byte_order(data, offset)
        entry_size = phaseone_entry_size(data, offset)
        if byte_order is None or entry_size is None:
            continue
        ifd_start = read_uint(data, offset + 8, byte_order)
        if offset + ifd_start + 8 > len(data):
            continue
        entry_count = read_uint(data, offset + ifd_start, byte_order)
        if 2 <= entry_count <= 300:
            return offset
    return None


def phaseone_byte_order(data: bytes, offset: int) -> PhaseOneByteOrder | None:
    if data[offset : offset + 2] == b"II":
        return "little"
    if data[offset : offset + 2] == b"MM":
        return "big"
    return None


def phaseone_entry_size(data: bytes, offset: int) -> int | None:
    header = data[offset : offset + 8]
    if (header[:4] == b"IIII" and header[5:8] == b"waR") or (
        header[:4] == b"MMMM" and header[4:7] == b"Raw"
    ):
        return PHASEONE_MAIN_ENTRY_SIZE
    if header in (b"IIII\x01\0\0\0", b"MMMM\0\0\0\x01"):
        return PHASEONE_SENSOR_CALIBRATION_ENTRY_SIZE
    return None


def parse_phaseone_entries(
    data: bytes,
    directory_offset: int,
    ifd_start: int,
    entry_count: int,
    entry_size: int,
    byte_order: PhaseOneByteOrder,
) -> tuple[PhaseOneIfdEntrySummary, ...]:
    entries: list[PhaseOneIfdEntrySummary] = []
    entries_start = directory_offset + ifd_start + 8
    for index in range(entry_count):
        entry_offset = entries_start + index * entry_size
        if entry_offset + entry_size > len(data):
            break
        tag_id = read_uint(data, entry_offset, byte_order)
        format_size = (
            read_uint(data, entry_offset + 4, byte_order)
            if entry_size == PHASEONE_MAIN_ENTRY_SIZE
            else None
        )
        value_size = read_uint(data, entry_offset + entry_size - 8, byte_order)
        value_or_offset = read_uint(data, entry_offset + entry_size - 4, byte_order)
        entries.append(
            PhaseOneIfdEntrySummary(
                tag_id=tag_id,
                format_size=format_size,
                value_size=value_size,
                value_or_offset=value_or_offset,
                is_serial_number=tag_id in (PHASEONE_SERIAL_NUMBER_TAG, 0x0407),
                is_sensor_calibration=tag_id == PHASEONE_SENSOR_CALIBRATION_TAG,
            )
        )
    return tuple(entries)


def build_phaseone_raw_data_preservation_plan(
    data: bytes,
    header: PhaseOneIfdHeaderSummary | None,
) -> PhaseOneRawDataPreservationPlan | None:
    if header is None or header.ifd_kind != "phaseone_main_ifd" or header.entry_count is None:
        return None

    ranges: list[PhaseOneRawDataCopyRange] = []
    dir_len = len(data) - header.directory_offset
    entries_start = header.directory_offset + header.ifd_start + 8
    for index in range(header.entry_count):
        entry_offset = entries_start + index * header.entry_size
        if entry_offset + header.entry_size > len(data):
            return None
        tag_id = read_uint(data, entry_offset, header.byte_order)
        if tag_id != PHASEONE_RAW_DATA_TAG:
            continue
        value_size = read_uint(data, entry_offset + header.entry_size - 8, header.byte_order)
        value_or_offset = read_uint(data, entry_offset + header.entry_size - 4, header.byte_order)
        source_range = phaseone_entry_value_range(
            directory_offset=header.directory_offset,
            dir_len=dir_len,
            entry_offset=entry_offset,
            entry_size=header.entry_size,
            value_size=value_size,
            value_or_offset=value_or_offset,
        )
        if source_range is None:
            return PhaseOneRawDataPreservationPlan(
                status="unsupported",
                can_preserve_raw_data=False,
                copy_ranges=(),
                blockers=("defer_without_phaseone_raw_data_copy",),
                evidence_ids=phaseone_raw_data_preservation_evidence_ids(),
            )
        ranges.append(
            PhaseOneRawDataCopyRange(
                entry_index=index,
                tag_id=tag_id,
                tag_name="RawData",
                source_range=source_range,
                original_size=value_size,
                put_first_in_rebuild=True,
                writable=False,
                hash_chunk_size=PHASEONE_IMAGE_DATA_HASH_CHUNK_SIZE,
                evidence_ids=phaseone_raw_data_preservation_evidence_ids(),
            )
        )

    if not ranges:
        return None
    return PhaseOneRawDataPreservationPlan(
        status="source_mapped_deferred",
        can_preserve_raw_data=False,
        copy_ranges=tuple(ranges),
        blockers=("defer_without_phaseone_raw_data_copy",),
        evidence_ids=phaseone_raw_data_preservation_evidence_ids(),
    )


def phaseone_entry_value_range(
    directory_offset: int,
    dir_len: int,
    entry_offset: int,
    entry_size: int,
    value_size: int,
    value_or_offset: int,
) -> PhaseOneRawByteRange | None:
    if value_size > 4:
        if value_or_offset + value_size > dir_len:
            return None
        start_offset = directory_offset + value_or_offset
        return PhaseOneRawByteRange(start_offset, start_offset + value_size)
    value_field_offset = entry_offset + entry_size - 4
    return PhaseOneRawByteRange(value_field_offset, value_field_offset + value_size)


def requested_mutations_from_raw_family(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> tuple[PhaseOneRawRequestedMutation, ...]:
    if raw_family_classification is None:
        return ()
    return tuple(
        PhaseOneRawRequestedMutation(
            requested_tag=argument.requested_tag,
            requested_value=argument.requested_value,
            generic_surfaces=argument.target_surfaces,
            generic_blockers=argument.blocker_codes,
        )
        for argument in raw_family_classification.arguments
    )


def raw_family_classification_is_phaseone(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> bool:
    if raw_family_classification is None:
        return True
    return (
        raw_family_classification.container == "iiq_phaseone"
        and raw_family_classification.status == "source_mapped_deferred"
        and all(
            "iiq_phaseone_main_ifd" in argument.target_surfaces
            or "iiq_phaseone_sensor_calibration_ifd" in argument.target_surfaces
            for argument in raw_family_classification.arguments
        )
    )


def phaseone_iiq_mutation_steps() -> tuple[PhaseOneRawMutationStep, ...]:
    return (
        PhaseOneRawMutationStep(
            kind="validate_phaseone_ifd_header",
            description="Validate PhaseOne or SensorCalibration directory header and byte order.",
            prerequisites=("phaseone_ifd_header", "requested_phaseone_raw_family_route"),
            safety_gates=("defer_without_phaseone_ifd_rebuilder",),
            evidence_ids=(PHASEONE_MAIN_SOURCE, PHASEONE_WRITE_SOURCE),
        ),
        PhaseOneRawMutationStep(
            kind="read_phaseone_entry_table",
            description="Read the fixed-size PhaseOne entry table before value reconstruction.",
            prerequisites=("phaseone_entry_size",),
            safety_gates=("defer_without_entry_size_validation",),
            evidence_ids=(PHASEONE_MAIN_SOURCE, PHASEONE_SENSOR_CALIBRATION_SOURCE),
        ),
        PhaseOneRawMutationStep(
            kind="rewrite_main_serial_number_value",
            description="Encode the requested SerialNumber string in the main PhaseOne IFD.",
            prerequisites=("serial_number_tag_definition",),
            safety_gates=("defer_without_serial_value_encoder",),
            evidence_ids=(PHASEONE_SERIAL_SOURCE, PHASEONE_WRITE_SOURCE),
        ),
        PhaseOneRawMutationStep(
            kind="rewrite_sensor_calibration_subifd",
            description="Recurse into SensorCalibration when SerialNumber lands in that sub-IFD.",
            prerequisites=("sensor_calibration_tag_table",),
            safety_gates=("defer_without_sensor_calibration_rewriter",),
            evidence_ids=(PHASEONE_SENSOR_CALIBRATION_SOURCE, PHASEONE_WRITE_SOURCE),
        ),
        PhaseOneRawMutationStep(
            kind="pad_value_data_to_four_bytes",
            description="Pad rewritten values to 4-byte alignment before offset fixups.",
            prerequisites=("phaseone_value_fixup_table",),
            safety_gates=("defer_without_value_padding",),
            evidence_ids=(PHASEONE_WRITE_SOURCE,),
        ),
        PhaseOneRawMutationStep(
            kind="apply_phaseone_value_offset_fixups",
            description="Shift deferred value offsets by the rebuilt header buffer length.",
            prerequisites=("phaseone_value_fixup_table",),
            safety_gates=("defer_without_value_offset_fixups",),
            evidence_ids=(PHASEONE_WRITE_SOURCE,),
        ),
        PhaseOneRawMutationStep(
            kind="patch_phaseone_ifd_pointer",
            description="Patch the PhaseOneIFD pointer in the rebuilt header.",
            prerequisites=("phaseone_value_fixup_table",),
            safety_gates=("defer_without_phaseone_ifd_pointer_patch",),
            evidence_ids=(PHASEONE_WRITE_SOURCE,),
        ),
        PhaseOneRawMutationStep(
            kind="plan_phaseone_raw_data_copy_ranges",
            description=(
                "Preserve PhaseOne RawData image bytes as copied ranges before any byte emission."
            ),
            prerequisites=(
                "phaseone_raw_data_tag_definition",
                "phaseone_image_data_hash_copy_loop",
            ),
            safety_gates=("defer_without_phaseone_raw_data_copy",),
            evidence_ids=(PHASEONE_RAW_DATA_SOURCE, PHASEONE_IMAGE_DATA_HASH_SOURCE),
        ),
        PhaseOneRawMutationStep(
            kind="return_rebuilt_phaseone_block",
            description="Return a rebuilt PhaseOne block for the outer writer to install.",
            prerequisites=("phaseone_ifd_header",),
            safety_gates=("defer_without_phaseone_ifd_rebuilder",),
            evidence_ids=(PHASEONE_WRITE_SOURCE,),
        ),
    )


def plan_evidence_ids(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> tuple[PhaseOneEvidenceId, ...]:
    evidence_ids: list[PhaseOneEvidenceId] = [
        PHASEONE_MAIN_SOURCE,
        PHASEONE_SERIAL_SOURCE,
        PHASEONE_SENSOR_CALIBRATION_SOURCE,
        PHASEONE_WRITE_SOURCE,
        PHASEONE_RAW_DATA_SOURCE,
        PHASEONE_IMAGE_DATA_HASH_SOURCE,
    ]
    if raw_family_classification is not None:
        evidence_ids.append(f"raw_family.{raw_family_classification.container}")
    return unique_evidence_ids(tuple(evidence_ids))


def read_uint(data: bytes, offset: int, byte_order: PhaseOneByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order)


def unique_safety_gates(
    steps: tuple[PhaseOneRawMutationStep, ...],
) -> tuple[PhaseOneRawSafetyGate, ...]:
    safety_gates: list[PhaseOneRawSafetyGate] = []
    for step in steps:
        for safety_gate in step.safety_gates:
            if safety_gate not in safety_gates:
                safety_gates.append(safety_gate)
    return tuple(safety_gates)


def unique_evidence_ids(
    evidence_ids: tuple[PhaseOneEvidenceId, ...],
) -> tuple[PhaseOneEvidenceId, ...]:
    unique: list[PhaseOneEvidenceId] = []
    for evidence_id in evidence_ids:
        if evidence_id not in unique:
            unique.append(evidence_id)
    return tuple(unique)


def phaseone_raw_data_preservation_evidence_ids() -> tuple[PhaseOneEvidenceId, ...]:
    return (PHASEONE_RAW_DATA_SOURCE, PHASEONE_IMAGE_DATA_HASH_SOURCE, PHASEONE_WRITE_SOURCE)
