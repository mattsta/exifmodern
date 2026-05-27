"""Phase One IIQ rebuilt-block installation planning.

ExifTool's PhaseOne writer returns a rebuilt PhaseOne data block; the caller
owns installing that block into the surrounding file/container.  This module
models that installation boundary without emitting whole-container bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from exifmodern.formats.phaseone_raw.ifd_rebuild_plan import (
    PhaseOneIfdRebuildPlan,
    build_phaseone_ifd_rebuild_plan,
    rebuild_phaseone_ifd_bytes,
)
from exifmodern.formats.phaseone_raw.mutation_plan import (
    PHASEONE_IMAGE_DATA_HASH_SOURCE,
    PHASEONE_RAW_DATA_SOURCE,
    PHASEONE_WRITE_SOURCE,
    PhaseOneEvidenceId,
    PhaseOneRawByteRange,
    inspect_phaseone_ifd_header,
    unique_evidence_ids,
)
from exifmodern.json_types import JsonObject

type PhaseOneIiqInstallationStatus = Literal[
    "source_mapped_output_ready",
    "source_mapped_deferred",
    "unsupported",
]
type PhaseOneIiqOutputSegmentKind = Literal[
    "preserved_container_prefix",
    "rebuilt_phaseone_ifd_block",
]
type PhaseOneIiqRawDataCopyStatus = Literal["source_mapped", "unsupported"]
type PhaseOneIiqEmissionGateCode = Literal[
    "requires_drop_tag_delete_contract",
    "requires_source_container_suffix_contract",
    "requires_rebuilt_phaseone_ifd_bytes",
    "requires_materialized_phaseone_ifd_bytes",
]

PHASEONE_WRITE_RETURNS_BLOCK_SOURCE: PhaseOneEvidenceId = "phaseone_raw.write_return_block"
WRITE_EXIF_PUT_FIRST_HEADER_SOURCE: PhaseOneEvidenceId = "phaseone_raw.write_exif_put_first"
PHASEONE_WRITE_TEST_SOURCE: PhaseOneEvidenceId = "phaseone_raw.write_test_3"


@dataclass(frozen=True)
class PhaseOneIiqOutputSegment:
    kind: PhaseOneIiqOutputSegmentKind
    source_offset: int | None
    source_length: int | None
    output_offset: int
    output_length: int | None
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "output_length": self.output_length,
            "output_offset": self.output_offset,
            "source_length": self.source_length,
            "source_offset": self.source_offset,
        }


@dataclass(frozen=True)
class PhaseOneIiqPointerPatchContract:
    source_pointer_field: PhaseOneRawByteRange
    rebuilt_pointer_field: PhaseOneRawByteRange
    original_ifd_start: int
    planned_ifd_start: int
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "original_ifd_start": self.original_ifd_start,
            "planned_ifd_start": self.planned_ifd_start,
            "rebuilt_pointer_field": self.rebuilt_pointer_field.to_json(),
            "source_pointer_field": self.source_pointer_field.to_json(),
        }


@dataclass(frozen=True)
class PhaseOneIiqRawDataCopyRecord:
    status: PhaseOneIiqRawDataCopyStatus
    tag_name: str
    source_range: PhaseOneRawByteRange
    rebuilt_block_range: PhaseOneRawByteRange | None
    final_output_range: PhaseOneRawByteRange | None
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "final_output_range": (
                self.final_output_range.to_json() if self.final_output_range is not None else None
            ),
            "rebuilt_block_range": (
                self.rebuilt_block_range.to_json() if self.rebuilt_block_range is not None else None
            ),
            "source_range": self.source_range.to_json(),
            "status": self.status,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class PhaseOneIiqEmissionGate:
    code: PhaseOneIiqEmissionGateCode
    detail: str
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PhaseOneIiqMaterializedOutput:
    action: str
    output_bytes: bytes
    output_length: int
    output_sha256: str
    preserved_prefix_length: int
    rebuilt_block_output_offset: int
    rebuilt_block_length: int
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "output_length": self.output_length,
            "output_sha256": self.output_sha256,
            "preserved_prefix_length": self.preserved_prefix_length,
            "rebuilt_block_length": self.rebuilt_block_length,
            "rebuilt_block_output_offset": self.rebuilt_block_output_offset,
        }


@dataclass(frozen=True)
class PhaseOneIiqContainerInstallationPlan:
    status: PhaseOneIiqInstallationStatus
    can_emit_output: bool
    directory_offset: int | None
    original_phaseone_block_length: int | None
    rebuilt_phaseone_block_length: int | None
    output_segments: tuple[PhaseOneIiqOutputSegment, ...]
    pointer_patch_contract: PhaseOneIiqPointerPatchContract | None
    raw_data_copy_records: tuple[PhaseOneIiqRawDataCopyRecord, ...]
    materialized_output: PhaseOneIiqMaterializedOutput | None
    output_emission_gates: tuple[PhaseOneIiqEmissionGate, ...]
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "directory_offset": self.directory_offset,
            "materialized_output": (
                self.materialized_output.to_json() if self.materialized_output is not None else None
            ),
            "original_phaseone_block_length": self.original_phaseone_block_length,
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "output_segments": [segment.to_json() for segment in self.output_segments],
            "pointer_patch_contract": (
                self.pointer_patch_contract.to_json()
                if self.pointer_patch_contract is not None
                else None
            ),
            "raw_data_copy_records": [record.to_json() for record in self.raw_data_copy_records],
            "rebuilt_phaseone_block_length": self.rebuilt_phaseone_block_length,
            "status": self.status,
        }


PHASEONE_IIQ_NATIVE_ACTION: Literal["run_modern_phaseone_iiq_mutation_engine"] = (
    "run_modern_phaseone_iiq_mutation_engine"
)


class PhaseOneIiqMaterializationError(ValueError):
    """Raised when callers request Phase One IIQ bytes from a deferred plan."""


def build_phaseone_iiq_container_installation_plan(
    data: bytes,
    serial_number: str | None = None,
) -> PhaseOneIiqContainerInstallationPlan:
    """Plan how a rebuilt PhaseOne block would be installed into its container."""

    header = inspect_phaseone_ifd_header(data)
    rebuild_plan = build_phaseone_ifd_rebuild_plan(data, serial_number=serial_number)
    emission = rebuild_phaseone_ifd_bytes(data, serial_number=serial_number)
    evidence_ids = phaseone_iiq_installation_evidence_ids()
    if (
        header is None
        or rebuild_plan.status != "source_mapped_non_mutating"
        or rebuild_plan.directory_offset is None
        or rebuild_plan.pointer_patch is None
        or not emission.can_emit
    ):
        return PhaseOneIiqContainerInstallationPlan(
            status="unsupported",
            can_emit_output=False,
            directory_offset=None,
            original_phaseone_block_length=None,
            rebuilt_phaseone_block_length=None,
            output_segments=(),
            pointer_patch_contract=None,
            raw_data_copy_records=(),
            materialized_output=None,
            output_emission_gates=(
                PhaseOneIiqEmissionGate(
                    code="requires_rebuilt_phaseone_ifd_bytes",
                    detail="The PhaseOne IFD byte rebuilder did not produce an installable block.",
                    evidence_ids=(PHASEONE_WRITE_SOURCE,),
                ),
            ),
            evidence_ids=evidence_ids,
        )

    directory_offset = rebuild_plan.directory_offset
    rebuilt_length = emission.rebuilt_length
    original_block_length = len(data) - directory_offset
    output_segments = phaseone_iiq_output_segments(
        directory_offset=directory_offset,
        original_block_length=original_block_length,
        rebuilt_block_length=rebuilt_length,
    )
    pointer_patch_contract = phaseone_iiq_pointer_patch_contract(rebuild_plan)
    raw_data_copy_records = phaseone_iiq_raw_data_copy_records(rebuild_plan, directory_offset)
    materialized_output = build_phaseone_iiq_materialized_output(
        data=data,
        directory_offset=directory_offset,
        emission=emission.emit(),
    )
    gates = phaseone_iiq_output_emission_gates(materialized_output)
    return PhaseOneIiqContainerInstallationPlan(
        status=(
            "source_mapped_output_ready"
            if materialized_output is not None and not gates
            else "source_mapped_deferred"
        ),
        can_emit_output=materialized_output is not None and not gates,
        directory_offset=directory_offset,
        original_phaseone_block_length=original_block_length,
        rebuilt_phaseone_block_length=rebuilt_length,
        output_segments=output_segments,
        pointer_patch_contract=pointer_patch_contract,
        raw_data_copy_records=raw_data_copy_records,
        materialized_output=materialized_output,
        output_emission_gates=gates,
        evidence_ids=evidence_ids,
    )


def phaseone_iiq_output_segments(
    directory_offset: int,
    original_block_length: int,
    rebuilt_block_length: int,
) -> tuple[PhaseOneIiqOutputSegment, ...]:
    return (
        PhaseOneIiqOutputSegment(
            kind="preserved_container_prefix",
            source_offset=0,
            source_length=directory_offset,
            output_offset=0,
            output_length=directory_offset,
            evidence_ids=(PHASEONE_WRITE_RETURNS_BLOCK_SOURCE,),
        ),
        PhaseOneIiqOutputSegment(
            kind="rebuilt_phaseone_ifd_block",
            source_offset=directory_offset,
            source_length=original_block_length,
            output_offset=directory_offset,
            output_length=rebuilt_block_length,
            evidence_ids=(PHASEONE_WRITE_RETURNS_BLOCK_SOURCE,),
        ),
    )


def phaseone_iiq_pointer_patch_contract(
    rebuild_plan: PhaseOneIfdRebuildPlan,
) -> PhaseOneIiqPointerPatchContract | None:
    pointer_patch = rebuild_plan.pointer_patch
    if rebuild_plan.directory_offset is None or pointer_patch is None:
        return None
    rebuilt_pointer_start = (
        pointer_patch.pointer_field_range.start_offset - rebuild_plan.directory_offset
    )
    return PhaseOneIiqPointerPatchContract(
        source_pointer_field=PhaseOneRawByteRange(
            pointer_patch.pointer_field_range.start_offset,
            pointer_patch.pointer_field_range.end_offset,
        ),
        rebuilt_pointer_field=PhaseOneRawByteRange(
            rebuilt_pointer_start,
            rebuilt_pointer_start + pointer_patch.pointer_field_range.length,
        ),
        original_ifd_start=pointer_patch.original_ifd_start,
        planned_ifd_start=pointer_patch.planned_ifd_start,
        evidence_ids=(PHASEONE_WRITE_SOURCE, PHASEONE_WRITE_RETURNS_BLOCK_SOURCE),
    )


def phaseone_iiq_raw_data_copy_records(
    rebuild_plan: PhaseOneIfdRebuildPlan,
    directory_offset: int,
) -> tuple[PhaseOneIiqRawDataCopyRecord, ...]:
    records: list[PhaseOneIiqRawDataCopyRecord] = []
    for operation in rebuild_plan.operations:
        if operation.tag_name != "RawData":
            continue
        rebuilt_range = operation.planned_value_range
        records.append(
            PhaseOneIiqRawDataCopyRecord(
                status="source_mapped",
                tag_name=operation.tag_name,
                source_range=PhaseOneRawByteRange(
                    operation.original_value_range.start_offset,
                    operation.original_value_range.start_offset + operation.original_size,
                ),
                rebuilt_block_range=PhaseOneRawByteRange(
                    rebuilt_range.start_offset,
                    rebuilt_range.start_offset + operation.original_size,
                ),
                final_output_range=PhaseOneRawByteRange(
                    directory_offset + rebuilt_range.start_offset,
                    directory_offset + rebuilt_range.start_offset + operation.original_size,
                ),
                evidence_ids=unique_evidence_ids(
                    (
                        PHASEONE_RAW_DATA_SOURCE,
                        PHASEONE_IMAGE_DATA_HASH_SOURCE,
                        WRITE_EXIF_PUT_FIRST_HEADER_SOURCE,
                    )
                ),
            )
        )
    return tuple(records)


def build_phaseone_iiq_materialized_output(
    data: bytes,
    directory_offset: int,
    emission: bytes,
) -> PhaseOneIiqMaterializedOutput | None:
    if directory_offset < 0 or directory_offset > len(data) or not emission:
        return None
    output_bytes = data[:directory_offset] + emission
    return PhaseOneIiqMaterializedOutput(
        action=PHASEONE_IIQ_NATIVE_ACTION,
        output_bytes=output_bytes,
        output_length=len(output_bytes),
        output_sha256=sha256(output_bytes).hexdigest(),
        preserved_prefix_length=directory_offset,
        rebuilt_block_output_offset=directory_offset,
        rebuilt_block_length=len(emission),
        evidence_ids=(
            PHASEONE_WRITE_RETURNS_BLOCK_SOURCE,
            WRITE_EXIF_PUT_FIRST_HEADER_SOURCE,
            PHASEONE_RAW_DATA_SOURCE,
            PHASEONE_WRITE_TEST_SOURCE,
        ),
    )


def materialize_phaseone_iiq_container_output(
    plan: PhaseOneIiqContainerInstallationPlan,
) -> bytes:
    materialized_output = plan.materialized_output
    if not plan.can_emit_output or materialized_output is None:
        gate_codes = ", ".join(gate.code for gate in plan.output_emission_gates)
        raise PhaseOneIiqMaterializationError(
            f"Phase One IIQ output is not ready: {gate_codes or 'no materialized output'}"
        )
    return materialized_output.output_bytes


def phaseone_iiq_output_emission_gates(
    materialized_output: PhaseOneIiqMaterializedOutput | None,
) -> tuple[PhaseOneIiqEmissionGate, ...]:
    if materialized_output is not None:
        return ()
    return (
        PhaseOneIiqEmissionGate(
            code="requires_materialized_phaseone_ifd_bytes",
            detail=(
                "Whole-container output requires a rebuilt PhaseOne block and a source-mapped "
                "prefix replacement boundary."
            ),
            evidence_ids=(PHASEONE_WRITE_RETURNS_BLOCK_SOURCE,),
        ),
    )


def phaseone_iiq_installation_evidence_ids() -> tuple[PhaseOneEvidenceId, ...]:
    return unique_evidence_ids(
        (
            PHASEONE_RAW_DATA_SOURCE,
            PHASEONE_IMAGE_DATA_HASH_SOURCE,
            PHASEONE_WRITE_SOURCE,
            PHASEONE_WRITE_RETURNS_BLOCK_SOURCE,
            WRITE_EXIF_PUT_FIRST_HEADER_SOURCE,
            PHASEONE_WRITE_TEST_SOURCE,
        )
    )
