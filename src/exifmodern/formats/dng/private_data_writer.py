"""DNG protected private-data write classification.

The source-compatible DNG write path handles Canon OriginalDecisionData through
Canon maker-note OriginalDecisionDataOffset and generic TIFF offset-pair
handling, not as a DNGPrivateData block replacement.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan, build_exif_scalar_write_plan
from exifmodern.formats.canon.original_decision_data import (
    OriginalDecisionDataReadResult,
    OriginalDecisionDataStatus,
    read_original_decision_data,
)
from exifmodern.formats.dng import protected_blocks as _dng_protected_blocks
from exifmodern.formats.dng.report_serialization import (
    EvidenceId,
    json_object_array,
    unique_evidence_ids,
)
from exifmodern.formats.tiff.directory_transaction_plan import build_tiff_directory_rebuild_plan
from exifmodern.formats.tiff.exif_scalar_file_writer import (
    TiffExifScalarRewriteResult,
    rewrite_tiff_exif_scalars_creating_if_needed,
)
from exifmodern.formats.tiff.exif_scalar_rewriter import apply_exif_scalar_write_plan
from exifmodern.formats.tiff.mutation import (
    EXIF_IFD_POINTER,
    GPS_INFO_IFD_POINTER,
    THUMBNAIL_OFFSET,
    RawTiffDirectory,
    RawTiffEntry,
    TiffMutationModel,
    encode_tiff_mutation_model,
    parse_tiff_mutation_model,
    raw_entry_by_tag,
    upsert_raw_entry,
)
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_BYTE,
    TIFF_TYPE_LONG,
    TYPE_SIZES,
    Endian,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_u32,
)
from exifmodern.formats.tiff.write_exif_value_buffer import (
    TiffWriteExifPayloadSource,
    apply_tiff_write_exif_value_buffer_append,
    build_tiff_write_exif_directory_value_buffer_coordinates,
    tiff_write_exif_inline_pointer_value_field,
)
from exifmodern.json_types import JsonObject


def evidence_id(source_id: str, symbol: str) -> EvidenceId:
    return source_id


DNG_TEST3_SOURCE = evidence_id(
    "dng.original_decision_data.test_3",
    symbol="DNG write test 3",
)
DNG_ADOBE_PRIVATE_DATA_READ_SOURCE = evidence_id(
    "dng.original_decision_data.adobe_private_data_read",
    symbol="ProcessAdobeData",
)
DNG_ADOBE_PRIVATE_DATA_WRITE_SOURCE = evidence_id(
    "dng.original_decision_data.adobe_private_data_write",
    symbol="ProcessAdobeData outfile copy",
)
DNG_WRITE_ADOBE_STUFF_SOURCE = evidence_id(
    "dng.original_decision_data.write_adobe_stuff",
    symbol="WriteAdobeStuff",
)
DNG_ADOBE_MAKN_SOURCE = evidence_id(
    "dng.original_decision_data.adobe_makn",
    symbol="ProcessAdobeMakN",
)
DNG_PRIVATE_DATA_TAG_SOURCE = evidence_id(
    "dng.original_decision_data.private_data_tag",
    symbol="0xc634 DNGPrivateData",
)
DNG_OUTER_TIFF_PRIVATE_DATA_INSTALL_SOURCE = evidence_id(
    "dng.original_decision_data.outer_tiff_private_data_install",
    symbol="WriteExif large tag value install",
)
DNG_OUTER_TIFF_OFFSET_REPAIR_SOURCE = evidence_id(
    "dng.original_decision_data.outer_tiff_offset_repair",
    symbol="WriteExif image data offset repair",
)
DNG_OUTER_TIFF_SUBIFD_REPAIR_SOURCE = evidence_id(
    "dng.original_decision_data.outer_tiff_subifd_repair",
    symbol="WriteExif SubIFD offset repair",
)
CANON_ODD_OFFSET_SOURCE = evidence_id(
    "dng.original_decision_data.canon_odd_offset",
    symbol="0x83 OriginalDecisionDataOffset",
)
CANON_ODD_COMPOSITE_SOURCE = evidence_id(
    "dng.original_decision_data.canon_odd_composite",
    symbol="Composite OriginalDecisionData",
)
CANON_READ_ODD_SOURCE = evidence_id(
    "dng.original_decision_data.canon_read_odd",
    symbol="ReadODD",
)
WRITE_EXIF_ODD_SOURCE = evidence_id(
    "dng.original_decision_data.write_exif_odd",
    symbol="OriginalDecisionData OffsetPair write",
)
WRITER_PROTECTED_SOURCE = evidence_id(
    "dng.original_decision_data.writer_protected_gate",
    symbol="Protected write gate",
)


def original_decision_data_evidence_ids() -> tuple[EvidenceId, ...]:
    return (
        DNG_TEST3_SOURCE,
        DNG_ADOBE_PRIVATE_DATA_READ_SOURCE,
        DNG_ADOBE_PRIVATE_DATA_WRITE_SOURCE,
        DNG_WRITE_ADOBE_STUFF_SOURCE,
        DNG_PRIVATE_DATA_TAG_SOURCE,
        CANON_ODD_OFFSET_SOURCE,
        CANON_ODD_COMPOSITE_SOURCE,
        CANON_READ_ODD_SOURCE,
        WRITE_EXIF_ODD_SOURCE,
        WRITER_PROTECTED_SOURCE,
    )


adobe_makn_endian = _dng_protected_blocks.adobe_makn_endian
adobe_makn_header_length = _dng_protected_blocks.adobe_makn_header_length
find_adobe_private_data_record = _dng_protected_blocks.find_adobe_private_data_record
rewrap_adobe_private_data_record = _dng_protected_blocks.rewrap_adobe_private_data_record

type DngOriginalDecisionDataWriteStatus = Literal[
    "blocked",
    "protected_blocked",
    "invalid_value",
]
type DngProtectedPrivateDataBlockerCode = Literal[
    "requires_canon_original_decision_data_offset_pair_rebuild",
    "requires_outer_dng_private_data_container_install",
    "requires_protected_1",
    "invalid_original_decision_data_layout",
]
type DngOriginalDecisionDataByteSource = Literal[
    "new_composite_value",
    "preserved_existing_offset_value",
]
type DngOriginalDecisionDataOffsetBasis = Literal[
    "absolute_for_jpeg",
    "base_relative_for_dng",
]
type DngOriginalDecisionDataFileType = Literal["DNG", "JPEG"]
type DngOriginalDecisionDataOffsetStorageBasis = Literal[
    "stored_offset_is_file_absolute",
    "stored_offset_plus_tiff_base_is_file_absolute",
]
type DngOriginalDecisionDataOffsetPairPlanStatus = Literal[
    "plan_only_deferred",
    "protected_blocked",
    "invalid_new_value",
    "invalid_existing_offset",
    "invalid_existing_payload",
]
type DngOriginalDecisionDataOffsetPairGateCode = Literal[
    "protected_composite_write_permitted",
    "protected_offset_tag_rewrite_permitted",
    "new_payload_matches_read_odd_layout",
    "existing_offset_value_is_int32u",
    "existing_payload_range_is_inside_file",
    "new_offset_value_is_int32u",
    "writeexif_append_offset_pair_path_identified",
    "container_byte_emitter_not_enabled",
]
type DngOriginalDecisionDataOffsetPairAction = Literal[
    "append_new_payload_and_rewrite_offset",
    "preserve_existing_payload_and_rewrite_offset",
    "zero_offset_when_payload_unavailable",
]
type DngOriginalDecisionDataMutationGate = Literal[
    "protected_composite_write",
    "protected_offset_tag_rewrite",
    "validated_odd_layout",
    "offset_pair_rebuild",
    "no_direct_dng_private_data_mutation",
]
type DngOriginalDecisionDataTiffInstallStatus = Literal[
    "container_pending",
    "blocked_by_rebuild_plan",
]
type DngOriginalDecisionDataPointerValueFormat = Literal["int32u"]
type DngOriginalDecisionDataPayloadSource = Literal[
    "new_composite_value",
    "preserved_existing_offset_value",
    "none",
]
type DngOriginalDecisionDataTiffWriterOperation = Literal[
    "write_offset_tag_inline_int32u",
    "add_fixup_for_offset_tag_value_field",
    "append_odd_payload_to_value_buffer",
    "write_zero_offset_when_payload_unavailable",
]
type DngOriginalDecisionDataByteEmissionStatus = Literal[
    "emittable",
    "blocked_by_install_contract",
    "invalid_value_field_offset",
    "value_buffer_start_mismatch",
    "payload_length_mismatch",
    "invalid_payload_layout",
]
type DngOriginalDecisionDataPrivateDataRewriteStatus = Literal[
    "rewritten",
    "blocked_by_install_contract",
    "coordinates_not_discovered",
    "byte_emission_blocked",
    "invalid_adobe_private_data",
]
type DngPrivateDataOuterInstallStatus = Literal[
    "installed",
    "missing_dng_private_data",
    "invalid_dng_private_data",
    "private_data_rewrite_blocked",
    "offset_repair_required",
]
type DngOriginalDecisionDataCoordinateStatus = Literal[
    "discovered",
    "missing_dng_private_data",
    "missing_adobe_makn",
    "invalid_adobe_makn_header",
    "missing_original_decision_data_offset",
    "truncated_maker_notes",
]


@dataclass(frozen=True)
class DngProtectedPrivateDataBlocker:
    code: DngProtectedPrivateDataBlockerCode
    tag_name: str
    reason: str
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class DngOriginalDecisionDataOffsetTagContract:
    tag_id: int
    tag_name: str
    writable_format: str
    protected_level: int
    offset_pair_flag: bool
    has_length_pair: bool
    data_tag: str
    dng_offset_basis: DngOriginalDecisionDataOffsetBasis
    jpeg_offset_basis: DngOriginalDecisionDataOffsetBasis
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class DngOriginalDecisionDataCompositeContract:
    tag_name: str
    write_group: str
    require_tag: str
    raw_conv_reader: str
    protected_required: int
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class DngOriginalDecisionDataValueLayoutContract:
    signature: bytes
    supported_versions: tuple[int, ...]
    maximum_version3_chunk_length: int
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class DngOriginalDecisionDataRebuildContract:
    byte_sources: tuple[DngOriginalDecisionDataByteSource, ...]
    mutation_gates: tuple[DngOriginalDecisionDataMutationGate, ...]
    appends_data_to_value_buffer: bool
    rewrites_offset_tag: bool
    byte_output_enabled: bool
    reason_byte_output_disabled: str
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class DngOriginalDecisionDataWriteContract:
    offset_tag: DngOriginalDecisionDataOffsetTagContract
    composite: DngOriginalDecisionDataCompositeContract
    value_layout: DngOriginalDecisionDataValueLayoutContract
    rebuild: DngOriginalDecisionDataRebuildContract
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class DngOriginalDecisionDataWriteClassification:
    status: DngOriginalDecisionDataWriteStatus
    protected_requested: int
    protected_required: int
    contract: DngOriginalDecisionDataWriteContract
    value_status: OriginalDecisionDataStatus | None
    value_version: int | None
    reason: str
    blockers: tuple[DngProtectedPrivateDataBlocker, ...]
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class DngOwnerNameRewriteResult:
    data: bytes
    exif_scalar_plan: ExifScalarWritePlan
    rewrite_result: TiffExifScalarRewriteResult


@dataclass(frozen=True)
class DngOriginalDecisionDataPayloadRange:
    start_offset: int
    byte_count: int
    end_offset: int
    inside_file: bool
    status: OriginalDecisionDataStatus
    version: int | None
    warning: str | None

    def to_json(self) -> JsonObject:
        return {
            "byte_count": self.byte_count,
            "end_offset": self.end_offset,
            "inside_file": self.inside_file,
            "start_offset": self.start_offset,
            "status": self.status,
            "version": self.version,
            "warning": self.warning,
        }


@dataclass(frozen=True)
class DngOriginalDecisionDataOffsetPairRecord:
    offset_tag_id: int
    offset_tag_name: str
    data_tag: str
    has_length_pair: bool
    file_type: DngOriginalDecisionDataFileType
    old_stored_offset_value: int | None
    old_data_position_basis: DngOriginalDecisionDataOffsetStorageBasis
    old_payload_range: DngOriginalDecisionDataPayloadRange | None
    new_data_position_basis: DngOriginalDecisionDataOffsetStorageBasis
    new_payload_byte_count: int
    new_payload_absolute_offset: int
    new_stored_offset_value: int
    action: DngOriginalDecisionDataOffsetPairAction
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "data_tag": self.data_tag,
            "file_type": self.file_type,
            "has_length_pair": self.has_length_pair,
            "new_data_position_basis": self.new_data_position_basis,
            "new_payload_absolute_offset": self.new_payload_absolute_offset,
            "new_payload_byte_count": self.new_payload_byte_count,
            "new_stored_offset_value": self.new_stored_offset_value,
            "offset_tag_id": hex(self.offset_tag_id),
            "offset_tag_name": self.offset_tag_name,
            "old_data_position_basis": self.old_data_position_basis,
            "old_payload_range": (
                self.old_payload_range.to_json() if self.old_payload_range is not None else None
            ),
            "old_stored_offset_value": self.old_stored_offset_value,
        }


@dataclass(frozen=True)
class DngOriginalDecisionDataOffsetPairGate:
    code: DngOriginalDecisionDataOffsetPairGateCode
    passed: bool
    reason: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "passed": self.passed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DngOriginalDecisionDataOffsetPairRebuildPlan:
    status: DngOriginalDecisionDataOffsetPairPlanStatus
    byte_output_enabled: bool
    protected_requested: int
    protected_required: int
    offset_protected_required: int
    tiff_base_offset: int
    value_buffer_start_offset: int
    offset_pair_record: DngOriginalDecisionDataOffsetPairRecord
    gates: tuple[DngOriginalDecisionDataOffsetPairGate, ...]
    reason: str
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def source_backed_gates_satisfied(self) -> bool:
        return all(gate.passed for gate in self.gates)

    def to_json(self) -> JsonObject:
        return {
            "byte_output_enabled": self.byte_output_enabled,
            "gates": json_object_array(gate.to_json() for gate in self.gates),
            "offset_pair_record": self.offset_pair_record.to_json(),
            "offset_protected_required": self.offset_protected_required,
            "protected_requested": self.protected_requested,
            "protected_required": self.protected_required,
            "reason": self.reason,
            "source_backed_gates_satisfied": self.source_backed_gates_satisfied,
            "status": self.status,
            "tiff_base_offset": self.tiff_base_offset,
            "value_buffer_start_offset": self.value_buffer_start_offset,
        }


@dataclass(frozen=True)
class DngOriginalDecisionDataPointerValueRecord:
    directory_name: str
    offset_tag_id: int
    offset_tag_name: str
    data_tag: str
    value_format: DngOriginalDecisionDataPointerValueFormat
    value_field_offset: int
    stored_offset_value: int
    encoded_value: bytes
    fixup_target: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "data_tag": self.data_tag,
            "directory_name": self.directory_name,
            "encoded_value_hex": self.encoded_value.hex(),
            "fixup_target": self.fixup_target,
            "offset_tag_id": hex(self.offset_tag_id),
            "offset_tag_name": self.offset_tag_name,
            "stored_offset_value": self.stored_offset_value,
            "value_field_offset": self.value_field_offset,
            "value_format": self.value_format,
        }


@dataclass(frozen=True)
class DngOriginalDecisionDataValueBufferAppendRecord:
    payload_source: DngOriginalDecisionDataPayloadSource
    value_buffer_start_offset: int
    payload_absolute_offset: int
    payload_byte_count: int
    appends_payload: bool
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "appends_payload": self.appends_payload,
            "payload_absolute_offset": self.payload_absolute_offset,
            "payload_byte_count": self.payload_byte_count,
            "payload_source": self.payload_source,
            "value_buffer_start_offset": self.value_buffer_start_offset,
        }


@dataclass(frozen=True)
class DngOriginalDecisionDataTiffInstallContract:
    status: DngOriginalDecisionDataTiffInstallStatus
    byte_output_enabled: bool
    pointer_value_record: DngOriginalDecisionDataPointerValueRecord
    value_buffer_append_record: DngOriginalDecisionDataValueBufferAppendRecord
    required_tiff_writer_operations: tuple[DngOriginalDecisionDataTiffWriterOperation, ...]
    remaining_blocker: str
    rebuild_plan: DngOriginalDecisionDataOffsetPairRebuildPlan
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def source_backed_gates_satisfied_except_container_emitter(self) -> bool:
        return all(
            gate.passed or gate.code == "container_byte_emitter_not_enabled"
            for gate in self.rebuild_plan.gates
        )

    def to_json(self) -> JsonObject:
        return {
            "byte_output_enabled": self.byte_output_enabled,
            "pointer_value_record": self.pointer_value_record.to_json(),
            "rebuild_plan_status": self.rebuild_plan.status,
            "remaining_blocker": self.remaining_blocker,
            "required_tiff_writer_operations": list(self.required_tiff_writer_operations),
            "source_backed_gates_satisfied_except_container_emitter": (
                self.source_backed_gates_satisfied_except_container_emitter
            ),
            "status": self.status,
            "value_buffer_append_record": self.value_buffer_append_record.to_json(),
        }


@dataclass(frozen=True)
class DngOriginalDecisionDataByteEmissionPlan:
    status: DngOriginalDecisionDataByteEmissionStatus
    byte_output_enabled: bool
    directory_name: str
    directory_bytes: bytes
    value_buffer: bytes
    rewritten_value_field_offset: int | None
    appended_payload_start_offset: int | None
    appended_payload_byte_count: int
    payload_source: DngOriginalDecisionDataPayloadSource
    reason: str
    install_contract: DngOriginalDecisionDataTiffInstallContract
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "appended_payload_byte_count": self.appended_payload_byte_count,
            "appended_payload_start_offset": self.appended_payload_start_offset,
            "byte_output_enabled": self.byte_output_enabled,
            "directory_byte_count": len(self.directory_bytes),
            "directory_name": self.directory_name,
            "payload_source": self.payload_source,
            "reason": self.reason,
            "rewritten_value_field_offset": self.rewritten_value_field_offset,
            "status": self.status,
            "value_buffer_byte_count": len(self.value_buffer),
        }


@dataclass(frozen=True)
class DngOriginalDecisionDataFullFileCoordinates:
    status: DngOriginalDecisionDataCoordinateStatus
    reason: str
    endian: Endian | None
    dng_private_data_value_offset: int | None
    adobe_makn_record_offset: int | None
    adobe_makn_data_offset: int | None
    adobe_makn_data_size: int | None
    maker_notes_directory_offset: int | None
    tiff_base_offset: int | None
    original_decision_data_offset_value_field_offset: int | None
    original_decision_data_offset_value_field_directory_offset: int | None
    existing_offset_value: int | None
    rebuilt_value_buffer_start_offset: int | None
    rebuilt_value_buffer_prefix_byte_count: int | None
    rebuilt_odd_payload_start_offset: int | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def byte_output_coordinate_ready(self) -> bool:
        return self.status == "discovered"

    def to_json(self) -> JsonObject:
        return {
            "adobe_makn_data_offset": self.adobe_makn_data_offset,
            "adobe_makn_data_size": self.adobe_makn_data_size,
            "adobe_makn_record_offset": self.adobe_makn_record_offset,
            "byte_output_coordinate_ready": self.byte_output_coordinate_ready,
            "dng_private_data_value_offset": self.dng_private_data_value_offset,
            "endian": self.endian,
            "existing_offset_value": self.existing_offset_value,
            "maker_notes_directory_offset": self.maker_notes_directory_offset,
            "original_decision_data_offset_value_field_directory_offset": (
                self.original_decision_data_offset_value_field_directory_offset
            ),
            "original_decision_data_offset_value_field_offset": (
                self.original_decision_data_offset_value_field_offset
            ),
            "reason": self.reason,
            "rebuilt_odd_payload_start_offset": self.rebuilt_odd_payload_start_offset,
            "rebuilt_value_buffer_prefix_byte_count": (self.rebuilt_value_buffer_prefix_byte_count),
            "rebuilt_value_buffer_start_offset": self.rebuilt_value_buffer_start_offset,
            "status": self.status,
            "tiff_base_offset": self.tiff_base_offset,
        }


@dataclass(frozen=True)
class DngOriginalDecisionDataFullFileInstallContract:
    coordinates: DngOriginalDecisionDataFullFileCoordinates
    rebuild_plan: DngOriginalDecisionDataOffsetPairRebuildPlan | None
    install_contract: DngOriginalDecisionDataTiffInstallContract | None
    remaining_blocker: str | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def source_backed_coordinates_discovered(self) -> bool:
        return self.coordinates.byte_output_coordinate_ready

    @property
    def source_backed_gates_satisfied_except_container_emitter(self) -> bool:
        contract = self.install_contract
        return (
            contract is not None and contract.source_backed_gates_satisfied_except_container_emitter
        )

    def to_json(self) -> JsonObject:
        return {
            "coordinates": self.coordinates.to_json(),
            "install_contract": (
                self.install_contract.to_json() if self.install_contract is not None else None
            ),
            "rebuild_plan": self.rebuild_plan.to_json() if self.rebuild_plan is not None else None,
            "remaining_blocker": self.remaining_blocker,
            "source_backed_coordinates_discovered": self.source_backed_coordinates_discovered,
            "source_backed_gates_satisfied_except_container_emitter": (
                self.source_backed_gates_satisfied_except_container_emitter
            ),
        }


@dataclass(frozen=True)
class DngOriginalDecisionDataPrivateDataRewriteResult:
    status: DngOriginalDecisionDataPrivateDataRewriteStatus
    byte_output_enabled: bool
    original_private_data_byte_count: int | None
    rewritten_private_data_byte_count: int | None
    original_makn_byte_count: int | None
    rewritten_makn_byte_count: int | None
    rewritten_private_data: bytes | None
    remaining_blocker: str | None
    full_file_install_contract: DngOriginalDecisionDataFullFileInstallContract
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_output_enabled": self.byte_output_enabled,
            "full_file_install_contract": self.full_file_install_contract.to_json(),
            "original_makn_byte_count": self.original_makn_byte_count,
            "original_private_data_byte_count": self.original_private_data_byte_count,
            "remaining_blocker": self.remaining_blocker,
            "rewritten_makn_byte_count": self.rewritten_makn_byte_count,
            "rewritten_private_data_byte_count": self.rewritten_private_data_byte_count,
            "status": self.status,
        }


@dataclass(frozen=True)
class DngPrivateDataOuterInstallResult:
    status: DngPrivateDataOuterInstallStatus
    byte_output_enabled: bool
    data: bytes | None
    original_size: int
    rewritten_size: int | None
    original_private_data_byte_count: int | None
    replacement_private_data_byte_count: int | None
    owner_name: str | None
    offset_repair_blockers: tuple[str, ...]
    private_data_rewrite_result: DngOriginalDecisionDataPrivateDataRewriteResult | None
    reason: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_output_enabled": self.byte_output_enabled,
            "offset_repair_blockers": list(self.offset_repair_blockers),
            "original_private_data_byte_count": self.original_private_data_byte_count,
            "original_size": self.original_size,
            "owner_name": self.owner_name,
            "reason": self.reason,
            "replacement_private_data_byte_count": self.replacement_private_data_byte_count,
            "rewritten_size": self.rewritten_size,
            "status": self.status,
        }


def classify_original_decision_data_write(
    value: bytes,
    protected: int,
) -> DngOriginalDecisionDataWriteClassification:
    evidence_ids = original_decision_data_evidence_ids()
    contract = original_decision_data_write_contract()
    protected_required = 1
    if protected & protected_required == 0:
        blocker = DngProtectedPrivateDataBlocker(
            code="requires_protected_1",
            tag_name="OriginalDecisionData",
            reason="OriginalDecisionData is protected and requires Protected=1.",
            evidence_ids=(WRITER_PROTECTED_SOURCE, CANON_ODD_COMPOSITE_SOURCE),
        )
        return DngOriginalDecisionDataWriteClassification(
            status="protected_blocked",
            protected_requested=protected,
            protected_required=protected_required,
            contract=contract,
            value_status=None,
            value_version=None,
            reason=blocker.reason,
            blockers=(blocker,),
            evidence_ids=evidence_ids,
        )

    validation = read_original_decision_data(b"\x00" + value, offset=1)
    if validation.status != "ok":
        blocker = DngProtectedPrivateDataBlocker(
            code="invalid_original_decision_data_layout",
            tag_name="OriginalDecisionData",
            reason=validation.warning or "Invalid original decision data",
            evidence_ids=(CANON_READ_ODD_SOURCE,),
        )
        return DngOriginalDecisionDataWriteClassification(
            status="invalid_value",
            protected_requested=protected,
            protected_required=protected_required,
            contract=contract,
            value_status=validation.status,
            value_version=validation.version,
            reason=blocker.reason,
            blockers=(blocker,),
            evidence_ids=evidence_ids,
        )

    blocker = DngProtectedPrivateDataBlocker(
        code="requires_outer_dng_private_data_container_install",
        tag_name="OriginalDecisionData",
        reason=(
            "Blocked: safe OriginalDecisionData updates now have a source-backed Canon "
            "OriginalDecisionDataOffset WriteExif offset-pair rewrap for Adobe MakN, "
            "but full-file output still requires the outer DNG TIFF container to install "
            "the replacement DNGPrivateData value and repair affected offsets."
        ),
        evidence_ids=(
            DNG_ADOBE_PRIVATE_DATA_READ_SOURCE,
            DNG_ADOBE_PRIVATE_DATA_WRITE_SOURCE,
            DNG_WRITE_ADOBE_STUFF_SOURCE,
            CANON_ODD_OFFSET_SOURCE,
            CANON_ODD_COMPOSITE_SOURCE,
            CANON_READ_ODD_SOURCE,
            WRITE_EXIF_ODD_SOURCE,
        ),
    )
    return DngOriginalDecisionDataWriteClassification(
        status="blocked",
        protected_requested=protected,
        protected_required=protected_required,
        contract=contract,
        value_status=validation.status,
        value_version=validation.version,
        reason=blocker.reason,
        blockers=(blocker,),
        evidence_ids=evidence_ids,
    )


def build_original_decision_data_full_file_install_contract(
    file_data: bytes,
    new_value: bytes | None,
    protected: int,
) -> DngOriginalDecisionDataFullFileInstallContract:
    """Discover DNG Canon ODD coordinates and build the install contract."""

    coordinates, directory = discover_original_decision_data_full_file_coordinates(file_data)
    evidence_ids = unique_evidence_ids(
        (
            *coordinates.evidence_ids,
            CANON_ODD_OFFSET_SOURCE,
            WRITE_EXIF_ODD_SOURCE,
        )
    )
    if not coordinates.byte_output_coordinate_ready or directory is None:
        return DngOriginalDecisionDataFullFileInstallContract(
            coordinates=coordinates,
            rebuild_plan=None,
            install_contract=None,
            remaining_blocker=coordinates.reason,
            evidence_ids=evidence_ids,
        )
    if coordinates.tiff_base_offset is None:
        raise ValueError("Discovered ODD coordinates must include TIFF base offset.")
    if coordinates.existing_offset_value is None:
        raise ValueError("Discovered ODD coordinates must include existing offset value.")
    if coordinates.rebuilt_odd_payload_start_offset is None:
        raise ValueError("Discovered ODD coordinates must include rebuilt payload start.")
    if coordinates.original_decision_data_offset_value_field_directory_offset is None:
        raise ValueError("Discovered ODD coordinates must include directory value field offset.")
    if coordinates.endian is None:
        raise ValueError("Discovered ODD coordinates must include endian.")

    rebuild_plan = plan_original_decision_data_offset_pair_rebuild(
        file_data=file_data,
        new_value=new_value,
        protected=protected,
        existing_offset_value=coordinates.existing_offset_value,
        tiff_base_offset=coordinates.tiff_base_offset,
        value_buffer_start_offset=coordinates.rebuilt_odd_payload_start_offset,
        file_type="DNG",
    )
    install_contract = build_original_decision_data_tiff_install_contract(
        rebuild_plan,
        directory_name="MakerNotes",
        offset_tag_value_field_offset=(
            coordinates.original_decision_data_offset_value_field_directory_offset
        ),
        endian=coordinates.endian,
    )
    remaining_blocker = None
    if not install_contract.source_backed_gates_satisfied_except_container_emitter:
        remaining_blocker = install_contract.remaining_blocker
    return DngOriginalDecisionDataFullFileInstallContract(
        coordinates=coordinates,
        rebuild_plan=rebuild_plan,
        install_contract=install_contract,
        remaining_blocker=remaining_blocker,
        evidence_ids=evidence_ids,
    )


def discover_original_decision_data_full_file_coordinates(
    file_data: bytes,
) -> tuple[DngOriginalDecisionDataFullFileCoordinates, RawTiffDirectory | None]:
    """Locate DNG Adobe MakN/Canon ODD OffsetPair coordinates in full-file bytes."""

    evidence_ids = (
        DNG_PRIVATE_DATA_TAG_SOURCE,
        DNG_ADOBE_PRIVATE_DATA_READ_SOURCE,
        DNG_ADOBE_MAKN_SOURCE,
        CANON_ODD_OFFSET_SOURCE,
        WRITE_EXIF_ODD_SOURCE,
    )
    header = parse_tiff_header(file_data)
    ifd0 = parse_ifd(file_data, header.first_ifd_offset, header.endian)
    private_data_entry = first_ifd_entry(ifd0.entries, 0xC634)
    if private_data_entry is None:
        return (
            missing_original_decision_data_coordinates(
                "missing_dng_private_data",
                "DNGPrivateData tag 0xc634 was not found in IFD0.",
                header.endian,
                evidence_ids,
            ),
            None,
        )
    private_data_offset = private_data_entry.value_offset
    private_data_size = tiff_entry_byte_count(private_data_entry)
    private_data_end = private_data_offset + private_data_size
    if private_data_end > len(file_data) or not file_data[private_data_offset:].startswith(
        b"Adobe\x00"
    ):
        return (
            missing_original_decision_data_coordinates(
                "missing_adobe_makn",
                "DNGPrivateData does not contain an Adobe private-data envelope.",
                header.endian,
                evidence_ids,
                dng_private_data_value_offset=private_data_offset,
            ),
            None,
        )

    makn_record = find_adobe_private_data_record(
        file_data,
        private_data_offset,
        private_data_size,
        b"MakN",
    )
    if makn_record is None:
        return (
            missing_original_decision_data_coordinates(
                "missing_adobe_makn",
                "Adobe DNGPrivateData does not contain a MakN record.",
                header.endian,
                evidence_ids,
                dng_private_data_value_offset=private_data_offset,
            ),
            None,
        )
    makn_record_offset, makn_data_offset, makn_size = makn_record
    makn_end = makn_data_offset + makn_size
    if makn_size < 6 or makn_end > len(file_data):
        return (
            missing_original_decision_data_coordinates(
                "invalid_adobe_makn_header",
                "Adobe MakN record is too short for its byte-order/original-offset header.",
                header.endian,
                evidence_ids,
                dng_private_data_value_offset=private_data_offset,
                adobe_makn_record_offset=makn_record_offset,
                adobe_makn_data_offset=makn_data_offset,
                adobe_makn_data_size=makn_size,
            ),
            None,
        )
    maker_endian = adobe_makn_endian(file_data, makn_data_offset)
    if maker_endian is None:
        return (
            missing_original_decision_data_coordinates(
                "invalid_adobe_makn_header",
                "Adobe MakN record has an unsupported maker-note byte order marker.",
                header.endian,
                evidence_ids,
                dng_private_data_value_offset=private_data_offset,
                adobe_makn_record_offset=makn_record_offset,
                adobe_makn_data_offset=makn_data_offset,
                adobe_makn_data_size=makn_size,
            ),
            None,
        )
    tiff_base_offset = read_u32(file_data, makn_data_offset + 2, "big")
    makn_header_length = adobe_makn_header_length(file_data, makn_data_offset, makn_size)
    maker_notes_directory_offset = makn_data_offset + makn_header_length
    try:
        raw_directory = raw_adobe_makn_directory(
            file_data,
            maker_notes_directory_offset,
            makn_end,
            maker_endian,
        )
    except ValueError as error:
        return (
            missing_original_decision_data_coordinates(
                "truncated_maker_notes",
                str(error),
                maker_endian,
                evidence_ids,
                dng_private_data_value_offset=private_data_offset,
                adobe_makn_record_offset=makn_record_offset,
                adobe_makn_data_offset=makn_data_offset,
                adobe_makn_data_size=makn_size,
                maker_notes_directory_offset=maker_notes_directory_offset,
                tiff_base_offset=tiff_base_offset,
            ),
            None,
        )
    original_decision_data_entry = first_ifd_entry(
        parse_ifd(file_data, maker_notes_directory_offset, maker_endian).entries,
        0x0083,
    )
    if original_decision_data_entry is None:
        return (
            missing_original_decision_data_coordinates(
                "missing_original_decision_data_offset",
                "Canon OriginalDecisionDataOffset tag 0x0083 was not found in Adobe MakN.",
                maker_endian,
                evidence_ids,
                dng_private_data_value_offset=private_data_offset,
                adobe_makn_record_offset=makn_record_offset,
                adobe_makn_data_offset=makn_data_offset,
                adobe_makn_data_size=makn_size,
                maker_notes_directory_offset=maker_notes_directory_offset,
                tiff_base_offset=tiff_base_offset,
            ),
            raw_directory,
        )

    rebuild_plan = build_tiff_directory_rebuild_plan(
        raw_directory,
        directory_name="MakerNotes",
        endian=maker_endian,
        container_kind="dng",
    )
    value_coordinates = build_tiff_write_exif_directory_value_buffer_coordinates(
        rebuild_plan,
        maker_endian,
    )
    value_buffer_start = value_coordinates.value_buffer_start_offset
    payload_start = value_buffer_start + len(value_coordinates.value_buffer)
    value_field_offset = original_decision_data_entry.entry_offset + 8
    directory_value_field_offset = value_field_offset - maker_notes_directory_offset
    coordinates = DngOriginalDecisionDataFullFileCoordinates(
        status="discovered",
        reason=(
            "Discovered DNG Adobe MakN OriginalDecisionDataOffset value field, TIFF "
            "base offset, and rebuilt WriteExif valBuff payload start."
        ),
        endian=maker_endian,
        dng_private_data_value_offset=private_data_offset,
        adobe_makn_record_offset=makn_record_offset,
        adobe_makn_data_offset=makn_data_offset,
        adobe_makn_data_size=makn_size,
        maker_notes_directory_offset=maker_notes_directory_offset,
        tiff_base_offset=tiff_base_offset,
        original_decision_data_offset_value_field_offset=value_field_offset,
        original_decision_data_offset_value_field_directory_offset=directory_value_field_offset,
        existing_offset_value=original_decision_data_entry.value_offset,
        rebuilt_value_buffer_start_offset=value_buffer_start,
        rebuilt_value_buffer_prefix_byte_count=len(value_coordinates.value_buffer),
        rebuilt_odd_payload_start_offset=payload_start,
        evidence_ids=evidence_ids,
    )
    return coordinates, raw_directory


def plan_original_decision_data_offset_pair_rebuild(
    file_data: bytes,
    new_value: bytes | None,
    protected: int,
    existing_offset_value: int | None,
    tiff_base_offset: int,
    value_buffer_start_offset: int,
    file_type: DngOriginalDecisionDataFileType = "DNG",
) -> DngOriginalDecisionDataOffsetPairRebuildPlan:
    """Plan Canon ODD offset-pair rewrite without emitting bytes."""

    old_basis = original_decision_data_offset_storage_basis(file_type)
    old_absolute_offset = (
        None
        if existing_offset_value is None
        else absolute_original_decision_data_offset(
            existing_offset_value,
            tiff_base_offset,
            file_type,
        )
    )
    old_read_result = (
        None
        if old_absolute_offset is None
        else read_original_decision_data(file_data, old_absolute_offset)
    )
    old_payload_range = original_decision_data_payload_range(
        file_size=len(file_data),
        absolute_offset=old_absolute_offset,
        read_result=old_read_result,
    )

    chosen_payload = new_value
    action: DngOriginalDecisionDataOffsetPairAction = "append_new_payload_and_rewrite_offset"
    if chosen_payload is None and old_read_result is not None and old_read_result.data is not None:
        chosen_payload = old_read_result.data
        action = "preserve_existing_payload_and_rewrite_offset"
    elif chosen_payload is None:
        chosen_payload = b""
        action = "zero_offset_when_payload_unavailable"

    new_validation = (
        read_original_decision_data(b"\x00" + chosen_payload, offset=1) if chosen_payload else None
    )
    new_payload_valid = action == "zero_offset_when_payload_unavailable" or (
        new_validation is not None and new_validation.status == "ok"
    )
    new_stored_offset = 0
    if action != "zero_offset_when_payload_unavailable":
        new_stored_offset = stored_original_decision_data_offset(
            absolute_offset=tiff_base_offset + value_buffer_start_offset,
            tiff_base_offset=tiff_base_offset,
            file_type=file_type,
        )
    new_absolute_offset = absolute_original_decision_data_offset(
        new_stored_offset,
        tiff_base_offset,
        file_type,
    )

    record = DngOriginalDecisionDataOffsetPairRecord(
        offset_tag_id=0x83,
        offset_tag_name="OriginalDecisionDataOffset",
        data_tag="OriginalDecisionData",
        has_length_pair=False,
        file_type=file_type,
        old_stored_offset_value=existing_offset_value,
        old_data_position_basis=old_basis,
        old_payload_range=old_payload_range,
        new_data_position_basis=old_basis,
        new_payload_byte_count=len(chosen_payload),
        new_payload_absolute_offset=new_absolute_offset,
        new_stored_offset_value=new_stored_offset,
        action=action,
        evidence_ids=(CANON_ODD_OFFSET_SOURCE, WRITE_EXIF_ODD_SOURCE),
    )

    gates = original_decision_data_offset_pair_gates(
        protected=protected,
        existing_offset_value=existing_offset_value,
        old_payload_range=old_payload_range,
        new_payload_valid=new_payload_valid,
        new_stored_offset=new_stored_offset,
    )
    status = original_decision_data_offset_pair_status(gates, new_validation, old_payload_range)
    evidence_ids = (
        CANON_ODD_OFFSET_SOURCE,
        CANON_ODD_COMPOSITE_SOURCE,
        CANON_READ_ODD_SOURCE,
        WRITE_EXIF_ODD_SOURCE,
    )
    return DngOriginalDecisionDataOffsetPairRebuildPlan(
        status=status,
        byte_output_enabled=False,
        protected_requested=protected,
        protected_required=1,
        offset_protected_required=2,
        tiff_base_offset=tiff_base_offset,
        value_buffer_start_offset=value_buffer_start_offset,
        offset_pair_record=record,
        gates=gates,
        reason=original_decision_data_offset_pair_reason(status),
        evidence_ids=evidence_ids,
    )


def build_original_decision_data_tiff_install_contract(
    rebuild_plan: DngOriginalDecisionDataOffsetPairRebuildPlan,
    directory_name: str,
    offset_tag_value_field_offset: int,
    endian: Endian,
) -> DngOriginalDecisionDataTiffInstallContract:
    """Describe the final TIFF writer operations needed for the ODD plan.

    The contract deliberately remains non-emitting: the TIFF writer branch needs
    a final directory/value-buffer writer to consume these records.
    """

    if offset_tag_value_field_offset < 0:
        raise ValueError("OriginalDecisionDataOffset value field offset must be non-negative.")

    record = rebuild_plan.offset_pair_record
    encoded_value = record.new_stored_offset_value.to_bytes(4, endian)
    pointer_record = DngOriginalDecisionDataPointerValueRecord(
        directory_name=directory_name,
        offset_tag_id=record.offset_tag_id,
        offset_tag_name=record.offset_tag_name,
        data_tag=record.data_tag,
        value_format="int32u",
        value_field_offset=offset_tag_value_field_offset,
        stored_offset_value=record.new_stored_offset_value,
        encoded_value=encoded_value,
        fixup_target=record.data_tag,
        evidence_ids=(CANON_ODD_OFFSET_SOURCE, WRITE_EXIF_ODD_SOURCE),
    )
    append_record = DngOriginalDecisionDataValueBufferAppendRecord(
        payload_source=original_decision_data_payload_source(record.action),
        value_buffer_start_offset=rebuild_plan.value_buffer_start_offset,
        payload_absolute_offset=record.new_payload_absolute_offset,
        payload_byte_count=record.new_payload_byte_count,
        appends_payload=record.action != "zero_offset_when_payload_unavailable",
        evidence_ids=(CANON_READ_ODD_SOURCE, WRITE_EXIF_ODD_SOURCE),
    )
    status: DngOriginalDecisionDataTiffInstallStatus = "container_pending"
    if rebuild_plan.status != "plan_only_deferred":
        status = "blocked_by_rebuild_plan"
    operations = original_decision_data_required_tiff_writer_operations(record.action)
    return DngOriginalDecisionDataTiffInstallContract(
        status=status,
        byte_output_enabled=False,
        pointer_value_record=pointer_record,
        value_buffer_append_record=append_record,
        required_tiff_writer_operations=operations,
        remaining_blocker=original_decision_data_tiff_install_blocker(status),
        rebuild_plan=rebuild_plan,
        evidence_ids=(
            CANON_ODD_OFFSET_SOURCE,
            CANON_ODD_COMPOSITE_SOURCE,
            CANON_READ_ODD_SOURCE,
            WRITE_EXIF_ODD_SOURCE,
        ),
    )


def build_original_decision_data_byte_emission_plan(
    install_contract: DngOriginalDecisionDataTiffInstallContract,
    directory_bytes: bytes,
    value_buffer: bytes,
    payload: bytes,
) -> DngOriginalDecisionDataByteEmissionPlan:
    """Apply the final WriteExif-style ODD pointer and valBuff byte edits.

    This seam intentionally edits only the already-built TIFF directory/value
    buffers: it does not discover MakerNotes, rebuild IFD entries, or mutate
    Adobe DNGPrivateData.
    """

    pointer = install_contract.pointer_value_record
    append = install_contract.value_buffer_append_record
    if (
        install_contract.status != "container_pending"
        or not install_contract.source_backed_gates_satisfied_except_container_emitter
    ):
        return original_decision_data_blocked_byte_emission_plan(
            status="blocked_by_install_contract",
            reason=install_contract.remaining_blocker,
            install_contract=install_contract,
            directory_bytes=directory_bytes,
            value_buffer=value_buffer,
            payload=payload,
        )
    value_field_end = pointer.value_field_offset + len(pointer.encoded_value)
    if pointer.value_field_offset < 0 or value_field_end > len(directory_bytes):
        return original_decision_data_blocked_byte_emission_plan(
            status="invalid_value_field_offset",
            reason="OriginalDecisionDataOffset value field is outside the rebuilt directory bytes.",
            install_contract=install_contract,
            directory_bytes=directory_bytes,
            value_buffer=value_buffer,
            payload=payload,
        )
    if len(value_buffer) != append.value_buffer_start_offset:
        return original_decision_data_blocked_byte_emission_plan(
            status="value_buffer_start_mismatch",
            reason=(
                "The supplied TIFF value buffer length does not match the planned valBuff start."
            ),
            install_contract=install_contract,
            directory_bytes=directory_bytes,
            value_buffer=value_buffer,
            payload=payload,
        )
    if len(payload) != append.payload_byte_count:
        return original_decision_data_blocked_byte_emission_plan(
            status="payload_length_mismatch",
            reason="The supplied ODD payload length does not match the install contract.",
            install_contract=install_contract,
            directory_bytes=directory_bytes,
            value_buffer=value_buffer,
            payload=payload,
        )
    if append.appends_payload:
        validation = read_original_decision_data(b"\x00" + payload, offset=1)
        if validation.status != "ok":
            return original_decision_data_blocked_byte_emission_plan(
                status="invalid_payload_layout",
                reason=validation.warning or "Invalid original decision data",
                install_contract=install_contract,
                directory_bytes=directory_bytes,
                value_buffer=value_buffer,
                payload=payload,
            )
    elif payload:
        return original_decision_data_blocked_byte_emission_plan(
            status="payload_length_mismatch",
            reason="Zero-offset ODD emission must not append payload bytes.",
            install_contract=install_contract,
            directory_bytes=directory_bytes,
            value_buffer=value_buffer,
            payload=payload,
        )

    rewritten_directory = (
        directory_bytes[: pointer.value_field_offset]
        + pointer.encoded_value
        + directory_bytes[value_field_end:]
    )
    appended_start = len(value_buffer) if append.appends_payload else None
    rewritten_value_buffer = value_buffer + payload if append.appends_payload else value_buffer
    return DngOriginalDecisionDataByteEmissionPlan(
        status="emittable",
        byte_output_enabled=True,
        directory_name=pointer.directory_name,
        directory_bytes=rewritten_directory,
        value_buffer=rewritten_value_buffer,
        rewritten_value_field_offset=pointer.value_field_offset,
        appended_payload_start_offset=appended_start,
        appended_payload_byte_count=len(payload) if append.appends_payload else 0,
        payload_source=append.payload_source,
        reason=(
            "Rewrote inline OriginalDecisionDataOffset and appended ODD bytes to the "
            "TIFF value buffer using the source-backed WriteExif offset-pair contract."
        ),
        install_contract=install_contract,
        evidence_ids=(WRITE_EXIF_ODD_SOURCE, CANON_ODD_OFFSET_SOURCE, CANON_READ_ODD_SOURCE),
    )


def rewrite_dng_private_data_original_decision_data(
    file_data: bytes,
    new_value: bytes | None,
    protected: int,
) -> DngOriginalDecisionDataPrivateDataRewriteResult:
    """Rebuild Adobe DNGPrivateData bytes after applying the Canon ODD offset pair.

    The returned bytes are the replacement value for TIFF tag 0xc634 only. This
    deliberately does not rewrite the outer DNG TIFF directory or move following
    file bytes.
    """

    coordinates, directory = discover_original_decision_data_full_file_coordinates(file_data)
    full_contract = build_original_decision_data_full_file_install_contract(
        file_data=file_data,
        new_value=new_value,
        protected=protected,
    )
    evidence_ids = unique_evidence_ids(
        (
            *full_contract.evidence_ids,
            DNG_ADOBE_PRIVATE_DATA_WRITE_SOURCE,
            DNG_WRITE_ADOBE_STUFF_SOURCE,
            DNG_ADOBE_MAKN_SOURCE,
        )
    )
    if not coordinates.byte_output_coordinate_ready or directory is None:
        return blocked_private_data_rewrite_result(
            status="coordinates_not_discovered",
            blocker=coordinates.reason,
            full_contract=full_contract,
            evidence_ids=evidence_ids,
        )
    if full_contract.install_contract is None:
        return blocked_private_data_rewrite_result(
            status="blocked_by_install_contract",
            blocker=full_contract.remaining_blocker or "Missing ODD install contract.",
            full_contract=full_contract,
            evidence_ids=evidence_ids,
        )
    install_contract = full_contract.install_contract
    if not install_contract.source_backed_gates_satisfied_except_container_emitter:
        return blocked_private_data_rewrite_result(
            status="blocked_by_install_contract",
            blocker=install_contract.remaining_blocker,
            full_contract=full_contract,
            evidence_ids=evidence_ids,
        )
    if coordinates.endian is None:
        raise ValueError("Discovered ODD coordinates must include endian.")
    if coordinates.dng_private_data_value_offset is None:
        raise ValueError("Discovered ODD coordinates must include DNGPrivateData offset.")
    if coordinates.adobe_makn_data_offset is None:
        raise ValueError("Discovered ODD coordinates must include MakN data offset.")
    if coordinates.adobe_makn_data_size is None:
        raise ValueError("Discovered ODD coordinates must include MakN data size.")
    if coordinates.maker_notes_directory_offset is None:
        raise ValueError("Discovered ODD coordinates must include maker-note directory offset.")

    header = parse_tiff_header(file_data)
    private_data_entry = first_ifd_entry(
        parse_ifd(file_data, header.first_ifd_offset, header.endian).entries,
        0xC634,
    )
    if private_data_entry is None:
        return blocked_private_data_rewrite_result(
            status="coordinates_not_discovered",
            blocker="DNGPrivateData tag 0xc634 was not found in IFD0.",
            full_contract=full_contract,
            evidence_ids=evidence_ids,
        )
    private_data_size = tiff_entry_byte_count(private_data_entry)
    private_data_offset = coordinates.dng_private_data_value_offset
    original_private_data = file_data[private_data_offset : private_data_offset + private_data_size]
    makn_header_length = (
        coordinates.maker_notes_directory_offset - coordinates.adobe_makn_data_offset
    )
    makn_header = file_data[
        coordinates.adobe_makn_data_offset : coordinates.maker_notes_directory_offset
    ]
    if makn_header_length < 6 or len(makn_header) != makn_header_length:
        return blocked_private_data_rewrite_result(
            status="invalid_adobe_private_data",
            blocker="Adobe MakN header coordinates are not valid for private-data rewrap.",
            full_contract=full_contract,
            evidence_ids=evidence_ids,
        )

    rebuild_plan = build_tiff_directory_rebuild_plan(
        directory,
        directory_name="MakerNotes",
        endian=coordinates.endian,
        container_kind="dng",
    )
    value_coordinates = build_tiff_write_exif_directory_value_buffer_coordinates(
        rebuild_plan,
        coordinates.endian,
    )
    pointer_record = install_contract.pointer_value_record
    pointer = tiff_write_exif_inline_pointer_value_field(
        pointer_record.directory_name,
        pointer_record.offset_tag_id,
        pointer_record.offset_tag_name,
        pointer_record.data_tag,
        pointer_record.value_field_offset,
        pointer_record.value_field_offset,
        pointer_record.stored_offset_value,
        coordinates.endian,
        (),
    )
    payload = original_decision_data_rewrite_payload(
        file_data=file_data,
        new_value=new_value,
        install_contract=install_contract,
    )
    emitted = apply_tiff_write_exif_value_buffer_append(
        value_coordinates,
        pointer,
        payload=payload,
        payload_source=tiff_payload_source_from_dng(
            install_contract.value_buffer_append_record.payload_source
        ),
        expected_payload_start_offset=(
            install_contract.value_buffer_append_record.value_buffer_start_offset
        ),
    )
    if emitted.status != "emittable":
        return blocked_private_data_rewrite_result(
            status="byte_emission_blocked",
            blocker=emitted.reason,
            full_contract=full_contract,
            evidence_ids=evidence_ids,
            original_private_data_byte_count=len(original_private_data),
            original_makn_byte_count=coordinates.adobe_makn_data_size,
        )

    rewritten_makn = makn_header + emitted.directory_bytes + emitted.value_buffer
    rewritten_private_data = rewrap_adobe_private_data_record(
        original_private_data,
        record_tag=b"MakN",
        replacement_value=rewritten_makn,
    )
    if rewritten_private_data is None:
        return blocked_private_data_rewrite_result(
            status="invalid_adobe_private_data",
            blocker="Adobe DNGPrivateData record table is truncated or corrupt.",
            full_contract=full_contract,
            evidence_ids=evidence_ids,
            original_private_data_byte_count=len(original_private_data),
            original_makn_byte_count=coordinates.adobe_makn_data_size,
        )
    return DngOriginalDecisionDataPrivateDataRewriteResult(
        status="rewritten",
        byte_output_enabled=True,
        original_private_data_byte_count=len(original_private_data),
        rewritten_private_data_byte_count=len(rewritten_private_data),
        original_makn_byte_count=coordinates.adobe_makn_data_size,
        rewritten_makn_byte_count=len(rewritten_makn),
        rewritten_private_data=rewritten_private_data,
        remaining_blocker=(
            "Outer DNG TIFF container still must install the replacement 0xc634 "
            "DNGPrivateData value and update any affected offsets before full-file promotion."
        ),
        full_file_install_contract=full_contract,
        evidence_ids=evidence_ids,
    )


def install_dng_private_data_original_decision_data(
    file_data: bytes,
    owner_name: str | None,
    new_value: bytes | None,
    protected: int,
) -> DngPrivateDataOuterInstallResult:
    """Rebuild Canon ODD bytes, then attempt the outer 0xc634 TIFF install."""

    private_data_rewrite = rewrite_dng_private_data_original_decision_data(
        file_data=file_data,
        new_value=new_value,
        protected=protected,
    )
    evidence_ids = unique_evidence_ids(
        (
            *private_data_rewrite.evidence_ids,
            DNG_OUTER_TIFF_PRIVATE_DATA_INSTALL_SOURCE,
            DNG_OUTER_TIFF_OFFSET_REPAIR_SOURCE,
        )
    )
    if private_data_rewrite.rewritten_private_data is None:
        return DngPrivateDataOuterInstallResult(
            status="private_data_rewrite_blocked",
            byte_output_enabled=False,
            data=None,
            original_size=len(file_data),
            rewritten_size=None,
            original_private_data_byte_count=private_data_rewrite.original_private_data_byte_count,
            replacement_private_data_byte_count=None,
            owner_name=owner_name,
            offset_repair_blockers=(),
            private_data_rewrite_result=private_data_rewrite,
            reason=private_data_rewrite.remaining_blocker
            or "DNGPrivateData replacement bytes were not emitted.",
            evidence_ids=evidence_ids,
        )
    install_result = install_dng_private_data_outer_tiff_value(
        file_data=file_data,
        replacement_private_data=private_data_rewrite.rewritten_private_data,
        owner_name=owner_name,
        private_data_rewrite_result=private_data_rewrite,
    )
    return DngPrivateDataOuterInstallResult(
        status=install_result.status,
        byte_output_enabled=install_result.byte_output_enabled,
        data=install_result.data,
        original_size=install_result.original_size,
        rewritten_size=install_result.rewritten_size,
        original_private_data_byte_count=install_result.original_private_data_byte_count,
        replacement_private_data_byte_count=install_result.replacement_private_data_byte_count,
        owner_name=install_result.owner_name,
        offset_repair_blockers=install_result.offset_repair_blockers,
        private_data_rewrite_result=private_data_rewrite,
        reason=install_result.reason,
        evidence_ids=unique_evidence_ids((*evidence_ids, *install_result.evidence_ids)),
    )


def install_dng_private_data_outer_tiff_value(
    file_data: bytes,
    replacement_private_data: bytes,
    owner_name: str | None = None,
    private_data_rewrite_result: DngOriginalDecisionDataPrivateDataRewriteResult | None = None,
) -> DngPrivateDataOuterInstallResult:
    """Install replacement bytes for IFD0 tag 0xc634 in a bounded TIFF rewrite.

    This emits only when the rewrite does not require unsupported image-data or
    SubIFD offset repair.  It composes with OwnerName by applying the existing
    EXIF scalar plan to the same parsed TIFF mutation model before encoding.
    """

    parsed = parse_tiff_mutation_model(file_data)
    private_data_entry = raw_entry_by_tag(parsed.ifd0.entries, 0xC634)
    evidence_ids = (
        DNG_PRIVATE_DATA_TAG_SOURCE,
        DNG_OUTER_TIFF_PRIVATE_DATA_INSTALL_SOURCE,
        DNG_OUTER_TIFF_OFFSET_REPAIR_SOURCE,
        DNG_OUTER_TIFF_SUBIFD_REPAIR_SOURCE,
    )
    if private_data_entry is None:
        return DngPrivateDataOuterInstallResult(
            status="missing_dng_private_data",
            byte_output_enabled=False,
            data=None,
            original_size=len(file_data),
            rewritten_size=None,
            original_private_data_byte_count=None,
            replacement_private_data_byte_count=len(replacement_private_data),
            owner_name=owner_name,
            offset_repair_blockers=(),
            private_data_rewrite_result=private_data_rewrite_result,
            reason="DNGPrivateData tag 0xc634 was not found in IFD0.",
            evidence_ids=evidence_ids,
        )
    if private_data_entry.field_type != TIFF_TYPE_BYTE:
        return DngPrivateDataOuterInstallResult(
            status="invalid_dng_private_data",
            byte_output_enabled=False,
            data=None,
            original_size=len(file_data),
            rewritten_size=None,
            original_private_data_byte_count=len(private_data_entry.raw_value),
            replacement_private_data_byte_count=len(replacement_private_data),
            owner_name=owner_name,
            offset_repair_blockers=(),
            private_data_rewrite_result=private_data_rewrite_result,
            reason="DNGPrivateData tag 0xc634 must be encoded as writable int8u bytes.",
            evidence_ids=evidence_ids,
        )

    if len(replacement_private_data) != len(
        private_data_entry.raw_value
    ) and dng_changed_count_splice_required(parsed):
        splice_result = install_dng_private_data_changed_count_splice(
            file_data=file_data,
            replacement_private_data=replacement_private_data,
            owner_name=owner_name,
            private_data_rewrite_result=private_data_rewrite_result,
            evidence_ids=evidence_ids,
        )
        if splice_result is not None:
            return splice_result

    updated_private_entry = RawTiffEntry(
        tag_id=0xC634,
        field_type=TIFF_TYPE_BYTE,
        count=len(replacement_private_data),
        raw_value=replacement_private_data,
    )
    updated_ifd0 = RawTiffDirectory(
        entries=upsert_raw_entry(parsed.ifd0.entries, updated_private_entry),
        next_ifd_offset=parsed.ifd0.next_ifd_offset,
    )
    updated_exif_ifd = parsed.exif_ifd
    if owner_name is not None:
        owner_plan = build_exif_scalar_write_plan(
            image_description=None,
            orientation=None,
            date_time_original=None,
            owner_name=owner_name,
        )
        if updated_exif_ifd is None:
            return DngPrivateDataOuterInstallResult(
                status="offset_repair_required",
                byte_output_enabled=False,
                data=None,
                original_size=len(file_data),
                rewritten_size=None,
                original_private_data_byte_count=len(private_data_entry.raw_value),
                replacement_private_data_byte_count=len(replacement_private_data),
                owner_name=owner_name,
                offset_repair_blockers=("ExifIFD creation requires shared TIFF pointer fixup.",),
                private_data_rewrite_result=private_data_rewrite_result,
                reason=(
                    "OwnerName requires ExifIFD creation, which is not part of the bounded "
                    "outer DNGPrivateData install seam."
                ),
                evidence_ids=evidence_ids,
            )
        updated_exif_ifd = RawTiffDirectory(
            entries=apply_exif_scalar_write_plan(
                updated_exif_ifd.entries,
                owner_plan,
                "ExifIFD",
                parsed.endian,
            ),
            next_ifd_offset=updated_exif_ifd.next_ifd_offset,
        )

    candidate_data = encode_tiff_mutation_model(
        replace(
            parsed,
            ifd0=updated_ifd0,
            exif_ifd=updated_exif_ifd,
        )
    )
    blockers = dng_outer_install_offset_repair_blockers(
        parsed_ifd0_entries=parsed.ifd0.entries,
        original_size=len(file_data),
        rewritten_size=len(candidate_data),
        original_private_data_byte_count=len(private_data_entry.raw_value),
        replacement_private_data_byte_count=len(replacement_private_data),
        has_ifd1=parsed.ifd1 is not None,
        suffix_byte_count=len(parsed.suffix),
    )
    if blockers:
        return DngPrivateDataOuterInstallResult(
            status="offset_repair_required",
            byte_output_enabled=False,
            data=None,
            original_size=len(file_data),
            rewritten_size=len(candidate_data),
            original_private_data_byte_count=len(private_data_entry.raw_value),
            replacement_private_data_byte_count=len(replacement_private_data),
            owner_name=owner_name,
            offset_repair_blockers=blockers,
            private_data_rewrite_result=private_data_rewrite_result,
            reason=(
                "Installing replacement DNGPrivateData changes the outer TIFF layout, "
                "but offset-bearing DNG surfaces still need WriteExif-style repair."
            ),
            evidence_ids=evidence_ids,
        )
    return DngPrivateDataOuterInstallResult(
        status="installed",
        byte_output_enabled=True,
        data=candidate_data,
        original_size=len(file_data),
        rewritten_size=len(candidate_data),
        original_private_data_byte_count=len(private_data_entry.raw_value),
        replacement_private_data_byte_count=len(replacement_private_data),
        owner_name=owner_name,
        offset_repair_blockers=(),
        private_data_rewrite_result=private_data_rewrite_result,
        reason="Installed replacement IFD0 0xc634 DNGPrivateData bytes in the outer TIFF.",
        evidence_ids=evidence_ids,
    )


def original_decision_data_blocked_byte_emission_plan(
    status: DngOriginalDecisionDataByteEmissionStatus,
    reason: str,
    install_contract: DngOriginalDecisionDataTiffInstallContract,
    directory_bytes: bytes,
    value_buffer: bytes,
    payload: bytes,
) -> DngOriginalDecisionDataByteEmissionPlan:
    return DngOriginalDecisionDataByteEmissionPlan(
        status=status,
        byte_output_enabled=False,
        directory_name=install_contract.pointer_value_record.directory_name,
        directory_bytes=directory_bytes,
        value_buffer=value_buffer,
        rewritten_value_field_offset=None,
        appended_payload_start_offset=None,
        appended_payload_byte_count=len(payload),
        payload_source=install_contract.value_buffer_append_record.payload_source,
        reason=reason,
        install_contract=install_contract,
        evidence_ids=(WRITE_EXIF_ODD_SOURCE, CANON_ODD_OFFSET_SOURCE, CANON_READ_ODD_SOURCE),
    )


def dng_outer_install_offset_repair_blockers(
    parsed_ifd0_entries: tuple[RawTiffEntry, ...],
    original_size: int,
    rewritten_size: int,
    original_private_data_byte_count: int,
    replacement_private_data_byte_count: int,
    has_ifd1: bool,
    suffix_byte_count: int,
) -> tuple[str, ...]:
    layout_changed = (
        original_size != rewritten_size
        or original_private_data_byte_count != replacement_private_data_byte_count
    )
    if not layout_changed:
        return ()

    blockers: list[str] = []
    offset_tag_names = {
        EXIF_IFD_POINTER: "ExifIFDPointer",
        GPS_INFO_IFD_POINTER: "GPSInfoIFDPointer",
        THUMBNAIL_OFFSET: "ThumbnailOffset",
        0x0111: "StripOffsets",
        0x0117: "StripByteCounts",
        0x0118: "RawDataOffset",
        0x0144: "TileOffsets",
        0x0145: "TileByteCounts",
        0x014A: "SubIFD",
        0x0201: "ThumbnailOffset",
        0x0202: "ThumbnailLength",
        0xC61A: "DefaultCropOrigin",
        0xC61B: "DefaultCropSize",
    }
    for entry in parsed_ifd0_entries:
        tag_name = offset_tag_names.get(entry.tag_id)
        if tag_name is None:
            continue
        if entry.tag_id in (EXIF_IFD_POINTER, GPS_INFO_IFD_POINTER):
            continue
        blockers.append(f"IFD0:{tag_name} requires offset or byte-count repair.")
    if has_ifd1:
        blockers.append("IFD1 thumbnail or linked-directory offsets require repair.")
    if suffix_byte_count:
        blockers.append("Opaque TIFF suffix bytes would move and require offset repair.")
    return tuple(blockers)


def dng_changed_count_splice_required(parsed: TiffMutationModel) -> bool:
    offset_or_size_tags = {
        THUMBNAIL_OFFSET,
        0x0111,
        0x0117,
        0x0118,
        0x0144,
        0x0145,
        0x014A,
        0x0201,
        0x0202,
    }
    if parsed.ifd1 is not None:
        return True
    if parsed.suffix:
        return True
    return any(entry.tag_id in offset_or_size_tags for entry in parsed.ifd0.entries)


def install_dng_private_data_changed_count_splice(
    file_data: bytes,
    replacement_private_data: bytes,
    owner_name: str | None,
    private_data_rewrite_result: DngOriginalDecisionDataPrivateDataRewriteResult | None,
    evidence_ids: tuple[EvidenceId, ...],
) -> DngPrivateDataOuterInstallResult | None:
    """Install a changed-size 0xc634 value by shifting following bytes in place.

    This is deliberately narrower than the shared TIFF mutation encoder.  It is
    safe only for existing DNG layouts where every affected coordinate is an
    absolute uint32 offset in IFD0/ExifIFD/SubIFD directories and image-data
    offset tags.  New directory growth, such as adding OwnerName, remains a
    typed blocker because it needs the shared WriteExif directory rebuild path.
    """

    header = parse_tiff_header(file_data)
    ifd0 = parse_ifd(file_data, header.first_ifd_offset, header.endian)
    private_data_entry = first_ifd_entry(ifd0.entries, 0xC634)
    if private_data_entry is None:
        return None
    original_private_data_byte_count = tiff_entry_byte_count(private_data_entry)
    replacement_private_data_byte_count = len(replacement_private_data)
    delta = replacement_private_data_byte_count - original_private_data_byte_count
    if delta == 0:
        return None

    private_data_offset = private_data_entry.value_offset
    private_data_end = private_data_offset + original_private_data_byte_count
    rewritten_size = len(file_data) + delta
    if private_data_end > len(file_data):
        return DngPrivateDataOuterInstallResult(
            status="offset_repair_required",
            byte_output_enabled=False,
            data=None,
            original_size=len(file_data),
            rewritten_size=rewritten_size,
            original_private_data_byte_count=original_private_data_byte_count,
            replacement_private_data_byte_count=replacement_private_data_byte_count,
            owner_name=owner_name,
            offset_repair_blockers=(
                (
                    "DNGPrivateData 0xc634 original value range is outside the file: "
                    f"offset=0x{private_data_offset:x}, count={original_private_data_byte_count}."
                ),
            ),
            private_data_rewrite_result=private_data_rewrite_result,
            reason="Changed-size DNGPrivateData splice could not prove the original byte range.",
            evidence_ids=evidence_ids,
        )
    if owner_name is not None:
        owner_splice = install_dng_private_data_changed_count_owner_splice(
            file_data=file_data,
            replacement_private_data=replacement_private_data,
            owner_name=owner_name,
            private_data_rewrite_result=private_data_rewrite_result,
            evidence_ids=evidence_ids,
            header_endian=header.endian,
            ifd0=ifd0,
            private_data_entry=private_data_entry,
            private_data_offset=private_data_offset,
            private_data_end=private_data_end,
            original_private_data_byte_count=original_private_data_byte_count,
            replacement_private_data_byte_count=replacement_private_data_byte_count,
            private_data_delta=delta,
        )
        if owner_splice is not None:
            return owner_splice

    rewritten = bytearray(
        file_data[:private_data_offset] + replacement_private_data + file_data[private_data_end:]
    )
    blockers = patch_dng_changed_count_offsets(
        original=file_data,
        rewritten=rewritten,
        private_data_entry=private_data_entry,
        private_data_start=private_data_offset,
        private_data_end=private_data_end,
        replacement_private_data_byte_count=replacement_private_data_byte_count,
        delta=delta,
        endian=header.endian,
        ifd0=ifd0,
    )
    if blockers:
        return DngPrivateDataOuterInstallResult(
            status="offset_repair_required",
            byte_output_enabled=False,
            data=None,
            original_size=len(file_data),
            rewritten_size=rewritten_size,
            original_private_data_byte_count=original_private_data_byte_count,
            replacement_private_data_byte_count=replacement_private_data_byte_count,
            owner_name=owner_name,
            offset_repair_blockers=blockers,
            private_data_rewrite_result=private_data_rewrite_result,
            reason="Changed-size DNGPrivateData splice found unrepairable offset coordinates.",
            evidence_ids=evidence_ids,
        )
    return DngPrivateDataOuterInstallResult(
        status="installed",
        byte_output_enabled=True,
        data=bytes(rewritten),
        original_size=len(file_data),
        rewritten_size=rewritten_size,
        original_private_data_byte_count=original_private_data_byte_count,
        replacement_private_data_byte_count=replacement_private_data_byte_count,
        owner_name=owner_name,
        offset_repair_blockers=(),
        private_data_rewrite_result=private_data_rewrite_result,
        reason=(
            "Installed changed-size IFD0 0xc634 DNGPrivateData bytes and repaired "
            "existing IFD0/ExifIFD/SubIFD/image-data uint32 offsets."
        ),
        evidence_ids=evidence_ids,
    )


def patch_dng_changed_count_offsets(
    original: bytes,
    rewritten: bytearray,
    private_data_entry: IfdEntry,
    private_data_start: int,
    private_data_end: int,
    replacement_private_data_byte_count: int,
    delta: int,
    endian: Endian,
    ifd0: Ifd,
) -> tuple[str, ...]:
    return patch_dng_absolute_offsets_for_shift_points(
        original=original,
        rewritten=rewritten,
        shift_points=((private_data_end, delta),),
        replaced_ranges=((private_data_start, private_data_end, "DNGPrivateData bytes"),),
        endian=endian,
        ifd0=ifd0,
        private_data_entry=private_data_entry,
        replacement_private_data_byte_count=replacement_private_data_byte_count,
    )


def install_dng_private_data_changed_count_owner_splice(
    file_data: bytes,
    replacement_private_data: bytes,
    owner_name: str,
    private_data_rewrite_result: DngOriginalDecisionDataPrivateDataRewriteResult | None,
    evidence_ids: tuple[EvidenceId, ...],
    header_endian: Endian,
    ifd0: Ifd,
    private_data_entry: IfdEntry,
    private_data_offset: int,
    private_data_end: int,
    original_private_data_byte_count: int,
    replacement_private_data_byte_count: int,
    private_data_delta: int,
) -> DngPrivateDataOuterInstallResult | None:
    """Compose the DNGPrivateData splice with append-only OwnerName growth.

    This mirrors the WriteExif large-value append shape only for a source-safe
    ExifIFD layout: OwnerName is a new highest-sorted tag, and existing ExifIFD
    out-of-line values are already a contiguous value buffer after the directory.
    """

    exif_ifd_entry = first_ifd_entry(ifd0.entries, EXIF_IFD_POINTER)
    exif_ifd_offset = exif_ifd_entry.value_offset if exif_ifd_entry is not None else None
    if exif_ifd_entry is None or exif_ifd_offset is None or exif_ifd_offset == 0:
        return dng_owner_name_growth_blocked_result(
            file_data=file_data,
            rewritten_size=len(file_data) + private_data_delta,
            original_private_data_byte_count=original_private_data_byte_count,
            replacement_private_data_byte_count=replacement_private_data_byte_count,
            owner_name=owner_name,
            private_data_rewrite_result=private_data_rewrite_result,
            evidence_ids=evidence_ids,
            blocker="OwnerName growth requires an existing ExifIFD pointer in IFD0.",
            reason=(
                "DNG-local OwnerName composition can only mutate an existing ExifIFD; "
                "ExifIFD creation needs the shared TIFF directory rebuild/fixup path."
            ),
        )

    try:
        exif_ifd = parse_ifd(file_data, exif_ifd_offset, header_endian)
    except ValueError as exc:
        return dng_owner_name_growth_blocked_result(
            file_data=file_data,
            rewritten_size=len(file_data) + private_data_delta,
            original_private_data_byte_count=original_private_data_byte_count,
            replacement_private_data_byte_count=replacement_private_data_byte_count,
            owner_name=owner_name,
            private_data_rewrite_result=private_data_rewrite_result,
            evidence_ids=evidence_ids,
            blocker=f"ExifIFD is not readable at 0x{exif_ifd_offset:x}: {exc}.",
            reason="DNG-local OwnerName composition requires a readable existing ExifIFD.",
        )
    if exif_ifd.offset < private_data_end:
        return dng_owner_name_growth_blocked_result(
            file_data=file_data,
            rewritten_size=len(file_data) + private_data_delta,
            original_private_data_byte_count=original_private_data_byte_count,
            replacement_private_data_byte_count=replacement_private_data_byte_count,
            owner_name=owner_name,
            private_data_rewrite_result=private_data_rewrite_result,
            evidence_ids=evidence_ids,
            blocker=(
                "OwnerName ExifIFD is not after the replaced DNGPrivateData range: "
                f"exif_ifd_offset=0x{exif_ifd.offset:x}, private_data_end=0x{private_data_end:x}."
            ),
            reason=(
                "DNG-local OwnerName composition currently requires the ExifIFD to move "
                "after the DNGPrivateData splice."
            ),
        )

    owner_plan = build_exif_scalar_write_plan(
        image_description=None,
        orientation=None,
        date_time_original=None,
        owner_name=owner_name,
    )
    owner_entry = next(
        entry
        for entry in apply_exif_scalar_write_plan((), owner_plan, "ExifIFD", header_endian)
        if entry.tag_id == 0xA430
    )
    owner_blocker = dng_owner_name_growth_blocker(
        file_data=file_data,
        exif_ifd=exif_ifd,
        owner_entry=owner_entry,
    )
    exif_directory_end = exif_ifd.offset + 2 + len(exif_ifd.entries) * 12 + 4
    exif_entry_insert_offset = exif_directory_end - 4
    try:
        exif_data_end = parsed_dng_ifd_data_end(file_data, exif_ifd)
    except ValueError as exc:
        owner_blocker = str(exc)
    owner_value_byte_count = len(owner_entry.raw_value) if len(owner_entry.raw_value) > 4 else 0
    owner_growth = 12 + owner_value_byte_count
    rewritten_size = len(file_data) + private_data_delta + owner_growth
    if owner_blocker is not None:
        return dng_owner_name_growth_blocked_result(
            file_data=file_data,
            rewritten_size=rewritten_size,
            original_private_data_byte_count=original_private_data_byte_count,
            replacement_private_data_byte_count=replacement_private_data_byte_count,
            owner_name=owner_name,
            private_data_rewrite_result=private_data_rewrite_result,
            evidence_ids=evidence_ids,
            blocker=owner_blocker,
            reason=(
                "DNG-local OwnerName composition is limited to append-only ExifIFD "
                "directory growth with a contiguous value buffer."
            ),
        )

    shifts_before_owner_value = (
        (private_data_end, private_data_delta),
        (exif_entry_insert_offset, 12),
    )
    owner_value_offset = map_dng_original_offset(exif_data_end, shifts_before_owner_value)
    owner_value_field = (
        owner_value_offset.to_bytes(4, header_endian)
        if owner_value_byte_count
        else owner_entry.raw_value.ljust(4, b"\x00")
    )
    exif_replacement = (
        (len(exif_ifd.entries) + 1).to_bytes(2, header_endian)
        + b"".join(
            file_data[entry.entry_offset : entry.entry_offset + 12] for entry in exif_ifd.entries
        )
        + encode_dng_owner_name_entry(owner_entry, owner_value_field, header_endian)
        + exif_ifd.next_ifd_offset.to_bytes(4, header_endian)
        + file_data[exif_directory_end:exif_data_end]
        + (owner_entry.raw_value if owner_value_byte_count else b"")
    )
    shifted_exif_offset = shift_dng_absolute_offset(
        exif_ifd.offset,
        private_data_end,
        private_data_delta,
    )
    shifted_exif_data_end = shift_dng_absolute_offset(
        exif_data_end,
        private_data_end,
        private_data_delta,
    )
    rewritten = bytearray(
        file_data[:private_data_offset]
        + replacement_private_data
        + file_data[private_data_end : shifted_exif_offset - private_data_delta]
        + exif_replacement
        + file_data[exif_data_end:]
    )
    if len(rewritten) != rewritten_size:
        return dng_owner_name_growth_blocked_result(
            file_data=file_data,
            rewritten_size=rewritten_size,
            original_private_data_byte_count=original_private_data_byte_count,
            replacement_private_data_byte_count=replacement_private_data_byte_count,
            owner_name=owner_name,
            private_data_rewrite_result=private_data_rewrite_result,
            evidence_ids=evidence_ids,
            blocker=(
                "Composed DNGPrivateData/OwnerName splice produced an unexpected byte count: "
                f"expected={rewritten_size}, actual={len(rewritten)}, "
                f"shifted_exif_data_end=0x{shifted_exif_data_end:x}."
            ),
            reason="DNG-local OwnerName composition failed its byte-count invariant.",
        )

    blockers = patch_dng_absolute_offsets_for_shift_points(
        original=file_data,
        rewritten=rewritten,
        shift_points=(
            (private_data_end, private_data_delta),
            (exif_entry_insert_offset, 12),
            (exif_data_end, owner_value_byte_count),
        ),
        replaced_ranges=((private_data_offset, private_data_end, "DNGPrivateData bytes"),),
        endian=header_endian,
        ifd0=ifd0,
        private_data_entry=private_data_entry,
        replacement_private_data_byte_count=replacement_private_data_byte_count,
    )
    if blockers:
        return DngPrivateDataOuterInstallResult(
            status="offset_repair_required",
            byte_output_enabled=False,
            data=None,
            original_size=len(file_data),
            rewritten_size=rewritten_size,
            original_private_data_byte_count=original_private_data_byte_count,
            replacement_private_data_byte_count=replacement_private_data_byte_count,
            owner_name=owner_name,
            offset_repair_blockers=blockers,
            private_data_rewrite_result=private_data_rewrite_result,
            reason=(
                "Composed DNGPrivateData/OwnerName splice found unrepairable absolute "
                "offset coordinates."
            ),
            evidence_ids=evidence_ids,
        )
    return DngPrivateDataOuterInstallResult(
        status="installed",
        byte_output_enabled=True,
        data=bytes(rewritten),
        original_size=len(file_data),
        rewritten_size=rewritten_size,
        original_private_data_byte_count=original_private_data_byte_count,
        replacement_private_data_byte_count=replacement_private_data_byte_count,
        owner_name=owner_name,
        offset_repair_blockers=(),
        private_data_rewrite_result=private_data_rewrite_result,
        reason=(
            "Installed changed-size IFD0 0xc634 DNGPrivateData bytes, appended OwnerName "
            "to the existing ExifIFD value buffer, and repaired affected absolute offsets."
        ),
        evidence_ids=evidence_ids,
    )


def patch_dng_absolute_offsets_for_shift_points(
    original: bytes,
    rewritten: bytearray,
    shift_points: tuple[tuple[int, int], ...],
    replaced_ranges: tuple[tuple[int, int, str], ...],
    endian: Endian,
    ifd0: Ifd,
    private_data_entry: IfdEntry,
    replacement_private_data_byte_count: int,
) -> tuple[str, ...]:
    blockers: list[str] = []
    visited_directories: set[int] = set()
    offset_value_tag_names = {
        0x0111: "StripOffsets",
        0x0118: "RawDataOffset",
        0x0144: "TileOffsets",
        0x0201: "ThumbnailOffset",
    }
    directory_pointer_tag_names = {
        EXIF_IFD_POINTER: "ExifIFDPointer",
        GPS_INFO_IFD_POINTER: "GPSInfoIFDPointer",
    }

    def patch_u32(position: int, value: int, label: str) -> None:
        if position < 0 or position + 4 > len(rewritten):
            blockers.append(f"{label} value field is outside rewritten file at 0x{position:x}.")
            return
        if not 0 <= value <= 0xFFFFFFFF:
            blockers.append(f"{label} shifted value is not uint32: {value}.")
            return
        rewritten[position : position + 4] = value.to_bytes(4, endian)

    def shifted_position(original_position: int) -> int:
        return map_dng_original_offset(original_position, shift_points)

    def shifted_target(value: int, label: str) -> int | None:
        for start, end, description in replaced_ranges:
            if start < value < end:
                blockers.append(
                    f"{label} points inside replaced {description} at 0x{value:x}; "
                    f"replaced_range=0x{start:x}..0x{end:x}."
                )
                return None
        return map_dng_original_offset(value, shift_points)

    patch_u32(
        private_data_entry.entry_offset + 4,
        replacement_private_data_byte_count,
        "IFD0:DNGPrivateData count",
    )

    def patch_long_values(entry: IfdEntry, directory_name: str, tag_name: str) -> tuple[int, ...]:
        if entry.field_type != TIFF_TYPE_LONG:
            blockers.append(
                f"{directory_name}:{tag_name} has unsupported offset format "
                f"{entry.field_type} at entry_offset=0x{entry.entry_offset:x}."
            )
            return ()
        values: list[int] = []
        byte_count = tiff_entry_byte_count(entry)
        value_base = entry.entry_offset + 8 if byte_count <= 4 else entry.value_offset
        for index in range(entry.count):
            source_position = value_base + index * 4
            if source_position < 0 or source_position + 4 > len(original):
                blockers.append(
                    f"{directory_name}:{tag_name}[{index}] source slot is outside file "
                    f"at 0x{source_position:x}."
                )
                continue
            old_value = read_u32(original, source_position, endian)
            new_value = shifted_target(old_value, f"{directory_name}:{tag_name}[{index}]")
            if new_value is None:
                continue
            patch_u32(
                shifted_position(source_position),
                new_value,
                f"{directory_name}:{tag_name}[{index}]",
            )
            values.append(old_value)
        return tuple(values)

    def visit_directory(directory_name: str, directory_offset: int) -> None:
        if directory_offset == 0 or directory_offset in visited_directories:
            return
        visited_directories.add(directory_offset)
        try:
            directory = parse_ifd(original, directory_offset, endian)
        except ValueError as exc:
            blockers.append(
                f"{directory_name} is not a readable IFD at 0x{directory_offset:x}: {exc}."
            )
            return
        next_position = directory.offset + 2 + len(directory.entries) * 12
        if directory.next_ifd_offset:
            new_next = shifted_target(directory.next_ifd_offset, f"{directory_name}:NextIFD")
            if new_next is not None:
                patch_u32(
                    shifted_position(next_position),
                    new_next,
                    f"{directory_name}:NextIFD",
                )
                visit_directory(f"{directory_name}:NextIFD", directory.next_ifd_offset)
        for entry in directory.entries:
            byte_count = tiff_entry_byte_count(entry)
            if byte_count > 4 and entry.tag_id != 0xC634:
                new_value_offset = shifted_target(
                    entry.value_offset,
                    f"{directory_name}:0x{entry.tag_id:04x} value offset",
                )
                if new_value_offset is not None:
                    patch_u32(
                        shifted_position(entry.entry_offset + 8),
                        new_value_offset,
                        f"{directory_name}:0x{entry.tag_id:04x} value offset",
                    )
            if entry.tag_id in directory_pointer_tag_names:
                tag_name = directory_pointer_tag_names[entry.tag_id]
                offsets = patch_long_values(entry, directory_name, tag_name)
                for offset in offsets:
                    visit_directory(tag_name, offset)
            elif entry.tag_id == 0x014A:
                offsets = patch_long_values(entry, directory_name, "SubIFD")
                for index, offset in enumerate(offsets):
                    visit_directory(f"SubIFD{index}", offset)
            elif entry.tag_id in offset_value_tag_names:
                patch_long_values(entry, directory_name, offset_value_tag_names[entry.tag_id])

    visit_directory("IFD0", ifd0.offset)
    return tuple(blockers)


def dng_owner_name_growth_blocker(
    file_data: bytes,
    exif_ifd: Ifd,
    owner_entry: RawTiffEntry,
) -> str | None:
    if first_ifd_entry(exif_ifd.entries, 0xA430) is not None:
        return (
            "OwnerName already exists; changed-size DNGPrivateData composition only "
            "supports new OwnerName growth."
        )
    if exif_ifd.entries and owner_entry.tag_id <= max(entry.tag_id for entry in exif_ifd.entries):
        return (
            "OwnerName would not be appended at the end of the sorted ExifIFD entry list; "
            "shared TIFF directory rebuild coordinates are required."
        )
    if exif_ifd.next_ifd_offset:
        return "ExifIFD has a non-zero NextIFD pointer; OwnerName growth needs shared TIFF fixups."

    directory_end = exif_ifd.offset + 2 + len(exif_ifd.entries) * 12 + 4
    expected_value_offset = directory_end
    for entry in exif_ifd.entries:
        byte_count = tiff_entry_byte_count(entry)
        if byte_count <= 4:
            continue
        if entry.value_offset != expected_value_offset:
            return (
                "ExifIFD external value buffer is not contiguous in sorted tag order: "
                f"tag=0x{entry.tag_id:04x}, expected_offset=0x{expected_value_offset:x}, "
                f"actual_offset=0x{entry.value_offset:x}."
            )
        expected_value_offset += byte_count
    if expected_value_offset > len(file_data):
        return f"ExifIFD external value buffer extends past EOF at 0x{expected_value_offset:x}."
    if owner_entry.field_type != 2:
        return f"OwnerName must encode as ASCII field type 2, got {owner_entry.field_type}."
    if len(owner_entry.raw_value) > 4 and len(owner_entry.raw_value) & 1:
        return "OwnerName out-of-line value must already include even WriteExif padding."
    if len(owner_entry.raw_value) != owner_entry.count:
        return "OwnerName raw byte count does not match the planned TIFF count."
    try:
        owner_entry.raw_value.decode("ascii")
    except UnicodeDecodeError:
        return "OwnerName must be ASCII for the DNG-local scalar writer path."
    return None


def dng_owner_name_growth_blocked_result(
    file_data: bytes,
    rewritten_size: int,
    original_private_data_byte_count: int,
    replacement_private_data_byte_count: int,
    owner_name: str,
    private_data_rewrite_result: DngOriginalDecisionDataPrivateDataRewriteResult | None,
    evidence_ids: tuple[EvidenceId, ...],
    blocker: str,
    reason: str,
) -> DngPrivateDataOuterInstallResult:
    return DngPrivateDataOuterInstallResult(
        status="offset_repair_required",
        byte_output_enabled=False,
        data=None,
        original_size=len(file_data),
        rewritten_size=rewritten_size,
        original_private_data_byte_count=original_private_data_byte_count,
        replacement_private_data_byte_count=replacement_private_data_byte_count,
        owner_name=owner_name,
        offset_repair_blockers=(blocker,),
        private_data_rewrite_result=private_data_rewrite_result,
        reason=reason,
        evidence_ids=evidence_ids,
    )


def encode_dng_owner_name_entry(
    owner_entry: RawTiffEntry,
    value_field: bytes,
    endian: Endian,
) -> bytes:
    return (
        owner_entry.tag_id.to_bytes(2, endian)
        + owner_entry.field_type.to_bytes(2, endian)
        + owner_entry.count.to_bytes(4, endian)
        + value_field
    )


def parsed_dng_ifd_data_end(file_data: bytes, ifd: Ifd) -> int:
    data_end = ifd.offset + 2 + len(ifd.entries) * 12 + 4
    for entry in ifd.entries:
        byte_count = tiff_entry_byte_count(entry)
        if byte_count > 4:
            data_end = max(data_end, entry.value_offset + byte_count)
    if data_end > len(file_data):
        raise ValueError(f"IFD data extends past EOF at 0x{data_end:x}.")
    return data_end


def map_dng_original_offset(value: int, shift_points: tuple[tuple[int, int], ...]) -> int:
    shifted = value
    for point, delta in shift_points:
        if value >= point:
            shifted += delta
    return shifted


def shift_dng_absolute_offset(value: int, insertion_end: int, delta: int) -> int:
    if value >= insertion_end:
        return value + delta
    return value


def format_optional_offset(value: int | None) -> str:
    if value is None:
        return "missing"
    return f"0x{value:x}"


def blocked_private_data_rewrite_result(
    status: DngOriginalDecisionDataPrivateDataRewriteStatus,
    blocker: str,
    full_contract: DngOriginalDecisionDataFullFileInstallContract,
    evidence_ids: tuple[EvidenceId, ...],
    original_private_data_byte_count: int | None = None,
    original_makn_byte_count: int | None = None,
) -> DngOriginalDecisionDataPrivateDataRewriteResult:
    return DngOriginalDecisionDataPrivateDataRewriteResult(
        status=status,
        byte_output_enabled=False,
        original_private_data_byte_count=original_private_data_byte_count,
        rewritten_private_data_byte_count=None,
        original_makn_byte_count=original_makn_byte_count,
        rewritten_makn_byte_count=None,
        rewritten_private_data=None,
        remaining_blocker=blocker,
        full_file_install_contract=full_contract,
        evidence_ids=evidence_ids,
    )


def original_decision_data_rewrite_payload(
    file_data: bytes,
    new_value: bytes | None,
    install_contract: DngOriginalDecisionDataTiffInstallContract,
) -> bytes:
    payload_source = install_contract.value_buffer_append_record.payload_source
    if payload_source == "new_composite_value":
        if new_value is None:
            raise ValueError("New ODD payload source requires new_value bytes.")
        return new_value
    if payload_source == "preserved_existing_offset_value":
        old_payload = install_contract.rebuild_plan.offset_pair_record.old_payload_range
        if old_payload is None or old_payload.byte_count == 0:
            raise ValueError("Preserved ODD payload source requires an old payload range.")
        return file_data[old_payload.start_offset : old_payload.end_offset]
    return b""


def tiff_payload_source_from_dng(
    payload_source: DngOriginalDecisionDataPayloadSource,
) -> TiffWriteExifPayloadSource:
    if payload_source == "new_composite_value":
        return "new_composite_value"
    if payload_source == "preserved_existing_offset_value":
        return "preserved_existing_offset_value"
    return "none"


def original_decision_data_payload_source(
    action: DngOriginalDecisionDataOffsetPairAction,
) -> DngOriginalDecisionDataPayloadSource:
    if action == "append_new_payload_and_rewrite_offset":
        return "new_composite_value"
    if action == "preserve_existing_payload_and_rewrite_offset":
        return "preserved_existing_offset_value"
    return "none"


def original_decision_data_required_tiff_writer_operations(
    action: DngOriginalDecisionDataOffsetPairAction,
) -> tuple[DngOriginalDecisionDataTiffWriterOperation, ...]:
    base: tuple[DngOriginalDecisionDataTiffWriterOperation, ...] = (
        "write_offset_tag_inline_int32u",
        "add_fixup_for_offset_tag_value_field",
    )
    if action == "zero_offset_when_payload_unavailable":
        return (*base, "write_zero_offset_when_payload_unavailable")
    return (*base, "append_odd_payload_to_value_buffer")


def original_decision_data_tiff_install_blocker(
    status: DngOriginalDecisionDataTiffInstallStatus,
) -> str:
    if status == "blocked_by_rebuild_plan":
        return "The ODD rebuild plan has unsatisfied protected, payload, or offset gates."
    return (
        "The remaining blocker is the final TIFF/WriteExif byte emitter that can rewrite "
        "the inline OriginalDecisionDataOffset value, register its fixup, and append the "
        "ODD payload to valBuff in the rebuilt MakerNotes directory."
    )


def original_decision_data_offset_storage_basis(
    file_type: DngOriginalDecisionDataFileType,
) -> DngOriginalDecisionDataOffsetStorageBasis:
    if file_type == "JPEG":
        return "stored_offset_is_file_absolute"
    return "stored_offset_plus_tiff_base_is_file_absolute"


def absolute_original_decision_data_offset(
    stored_offset: int,
    tiff_base_offset: int,
    file_type: DngOriginalDecisionDataFileType,
) -> int:
    if stored_offset <= 0:
        return 0
    if file_type == "JPEG":
        return stored_offset
    return stored_offset + tiff_base_offset


def stored_original_decision_data_offset(
    absolute_offset: int,
    tiff_base_offset: int,
    file_type: DngOriginalDecisionDataFileType,
) -> int:
    if file_type == "JPEG":
        return absolute_offset
    return absolute_offset - tiff_base_offset


def original_decision_data_payload_range(
    file_size: int,
    absolute_offset: int | None,
    read_result: OriginalDecisionDataReadResult | None,
) -> DngOriginalDecisionDataPayloadRange | None:
    if absolute_offset is None or read_result is None:
        return None
    byte_count = len(read_result.data) if read_result.data is not None else 0
    end_offset = absolute_offset + byte_count
    return DngOriginalDecisionDataPayloadRange(
        start_offset=absolute_offset,
        byte_count=byte_count,
        end_offset=end_offset,
        inside_file=(
            read_result.status == "ok"
            and absolute_offset >= 0
            and byte_count > 0
            and end_offset <= file_size
        ),
        status=read_result.status,
        version=read_result.version,
        warning=read_result.warning,
    )


def original_decision_data_offset_pair_gates(
    protected: int,
    existing_offset_value: int | None,
    old_payload_range: DngOriginalDecisionDataPayloadRange | None,
    new_payload_valid: bool,
    new_stored_offset: int,
) -> tuple[DngOriginalDecisionDataOffsetPairGate, ...]:
    existing_offset_valid = (
        existing_offset_value is None or 0 <= existing_offset_value <= 0xFFFFFFFF
    )
    existing_payload_valid = (
        old_payload_range is None
        or old_payload_range.start_offset == 0
        or old_payload_range.inside_file
    )
    new_offset_valid = 0 <= new_stored_offset <= 0xFFFFFFFF
    return (
        DngOriginalDecisionDataOffsetPairGate(
            code="protected_composite_write_permitted",
            passed=protected & 1 != 0,
            reason=(
                "OriginalDecisionData composite is protected and DNG.t writes it with Protected=1."
            ),
            evidence_ids=(DNG_TEST3_SOURCE, CANON_ODD_COMPOSITE_SOURCE),
        ),
        DngOriginalDecisionDataOffsetPairGate(
            code="protected_offset_tag_rewrite_permitted",
            passed=protected & 1 != 0,
            reason=(
                "WriteExif rewrites the Protected=2 OriginalDecisionDataOffset internally "
                "when the Protected=1 OriginalDecisionData composite write is permitted."
            ),
            evidence_ids=(DNG_TEST3_SOURCE, CANON_ODD_COMPOSITE_SOURCE, WRITE_EXIF_ODD_SOURCE),
        ),
        DngOriginalDecisionDataOffsetPairGate(
            code="new_payload_matches_read_odd_layout",
            passed=new_payload_valid,
            reason="Payload must match Canon::ReadODD versioned layout before it can be appended.",
            evidence_ids=(CANON_READ_ODD_SOURCE,),
        ),
        DngOriginalDecisionDataOffsetPairGate(
            code="existing_offset_value_is_int32u",
            passed=existing_offset_valid,
            reason="OriginalDecisionDataOffset is writable as int32u.",
            evidence_ids=(CANON_ODD_OFFSET_SOURCE,),
        ),
        DngOriginalDecisionDataOffsetPairGate(
            code="existing_payload_range_is_inside_file",
            passed=existing_payload_valid,
            reason=(
                "Existing non-zero offsets must resolve to a readable ODD range "
                "inside the source file."
            ),
            evidence_ids=(CANON_READ_ODD_SOURCE, WRITE_EXIF_ODD_SOURCE),
        ),
        DngOriginalDecisionDataOffsetPairGate(
            code="new_offset_value_is_int32u",
            passed=new_offset_valid,
            reason="The replacement offset tag value must remain an int32u.",
            evidence_ids=(CANON_ODD_OFFSET_SOURCE, WRITE_EXIF_ODD_SOURCE),
        ),
        DngOriginalDecisionDataOffsetPairGate(
            code="writeexif_append_offset_pair_path_identified",
            passed=True,
            reason=(
                "WriteExif appends ODD bytes to valBuff and rewrites OriginalDecisionDataOffset."
            ),
            evidence_ids=(WRITE_EXIF_ODD_SOURCE,),
        ),
        DngOriginalDecisionDataOffsetPairGate(
            code="container_byte_emitter_not_enabled",
            passed=False,
            reason=(
                "This DNG component plans the offset-pair rebuild, but the container "
                "rewrite emitter is still deliberately disabled."
            ),
            evidence_ids=(WRITE_EXIF_ODD_SOURCE,),
        ),
    )


def original_decision_data_offset_pair_status(
    gates: tuple[DngOriginalDecisionDataOffsetPairGate, ...],
    new_validation: OriginalDecisionDataReadResult | None,
    old_payload_range: DngOriginalDecisionDataPayloadRange | None,
) -> DngOriginalDecisionDataOffsetPairPlanStatus:
    failed_codes = {gate.code for gate in gates if not gate.passed}
    if "protected_composite_write_permitted" in failed_codes:
        return "protected_blocked"
    if "protected_offset_tag_rewrite_permitted" in failed_codes:
        return "protected_blocked"
    if new_validation is not None and new_validation.status != "ok":
        return "invalid_new_value"
    if "existing_offset_value_is_int32u" in failed_codes:
        return "invalid_existing_offset"
    if old_payload_range is not None and old_payload_range.start_offset > 0:
        if not old_payload_range.inside_file:
            return "invalid_existing_payload"
    return "plan_only_deferred"


def original_decision_data_offset_pair_reason(
    status: DngOriginalDecisionDataOffsetPairPlanStatus,
) -> str:
    if status == "protected_blocked":
        return "OriginalDecisionData offset-pair planning is blocked by protected tag gates."
    if status == "invalid_new_value":
        return "New OriginalDecisionData bytes do not match Canon::ReadODD layout."
    if status == "invalid_existing_offset":
        return "Existing OriginalDecisionDataOffset is not representable as int32u."
    if status == "invalid_existing_payload":
        return (
            "Existing OriginalDecisionDataOffset does not resolve to a valid source payload range."
        )
    return (
        "OriginalDecisionDataOffset pair planning is source-backed, but byte output "
        "remains disabled until the DNG/TIFF container emitter applies the plan."
    )


def original_decision_data_write_contract() -> DngOriginalDecisionDataWriteContract:
    offset_tag = DngOriginalDecisionDataOffsetTagContract(
        tag_id=0x83,
        tag_name="OriginalDecisionDataOffset",
        writable_format="int32u",
        protected_level=2,
        offset_pair_flag=True,
        has_length_pair=False,
        data_tag="OriginalDecisionData",
        dng_offset_basis="base_relative_for_dng",
        jpeg_offset_basis="absolute_for_jpeg",
        evidence_ids=(CANON_ODD_OFFSET_SOURCE, WRITE_EXIF_ODD_SOURCE),
    )
    composite = DngOriginalDecisionDataCompositeContract(
        tag_name="OriginalDecisionData",
        write_group="MakerNotes",
        require_tag="OriginalDecisionDataOffset",
        raw_conv_reader="Image::ExifTool::Canon::ReadODD",
        protected_required=1,
        evidence_ids=(CANON_ODD_COMPOSITE_SOURCE, DNG_TEST3_SOURCE),
    )
    value_layout = DngOriginalDecisionDataValueLayoutContract(
        signature=b"\xff\xff\xff\xff",
        supported_versions=(1, 2, 3),
        maximum_version3_chunk_length=0x10000,
        evidence_ids=(CANON_READ_ODD_SOURCE,),
    )
    rebuild = DngOriginalDecisionDataRebuildContract(
        byte_sources=("new_composite_value", "preserved_existing_offset_value"),
        mutation_gates=(
            "protected_composite_write",
            "protected_offset_tag_rewrite",
            "validated_odd_layout",
            "offset_pair_rebuild",
            "no_direct_dng_private_data_mutation",
        ),
        appends_data_to_value_buffer=True,
        rewrites_offset_tag=True,
        byte_output_enabled=False,
        reason_byte_output_disabled=(
            "DNG OriginalDecisionData bytes stay gated until the Canon maker-note "
            "offset-pair rebuild path can preserve or append ODD data and rewrite "
            "OriginalDecisionDataOffset without treating Adobe DNGPrivateData as "
            "the mutation target."
        ),
        evidence_ids=(
            DNG_ADOBE_PRIVATE_DATA_READ_SOURCE,
            DNG_ADOBE_PRIVATE_DATA_WRITE_SOURCE,
            DNG_WRITE_ADOBE_STUFF_SOURCE,
            WRITE_EXIF_ODD_SOURCE,
        ),
    )
    return DngOriginalDecisionDataWriteContract(
        offset_tag=offset_tag,
        composite=composite,
        value_layout=value_layout,
        rebuild=rebuild,
        evidence_ids=(
            DNG_TEST3_SOURCE,
            DNG_ADOBE_PRIVATE_DATA_READ_SOURCE,
            DNG_ADOBE_PRIVATE_DATA_WRITE_SOURCE,
            DNG_WRITE_ADOBE_STUFF_SOURCE,
            CANON_ODD_OFFSET_SOURCE,
            CANON_ODD_COMPOSITE_SOURCE,
            CANON_READ_ODD_SOURCE,
            WRITE_EXIF_ODD_SOURCE,
        ),
    )


def first_ifd_entry(entries: Iterable[IfdEntry], tag_id: int) -> IfdEntry | None:
    for entry in entries:
        if entry.tag_id == tag_id:
            return entry
    return None


def tiff_entry_byte_count(entry: IfdEntry) -> int:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        raise ValueError(f"Unsupported TIFF field type: {entry.field_type}")
    return field_size * entry.count


def raw_adobe_makn_directory(
    file_data: bytes,
    directory_offset: int,
    directory_end: int,
    endian: Endian,
) -> RawTiffDirectory:
    parsed = parse_ifd(file_data, directory_offset, endian)
    external_cursor = parsed.offset + 2 + len(parsed.entries) * 12 + 4
    raw_entries: list[RawTiffEntry] = []
    for entry in parsed.entries:
        byte_count = tiff_entry_byte_count(entry)
        if byte_count <= 4:
            raw_value = entry.value_offset.to_bytes(4, endian)[:byte_count]
        else:
            value_end = external_cursor + byte_count
            if value_end > directory_end:
                raise ValueError("Adobe MakN maker-note value data is truncated.")
            raw_value = file_data[external_cursor:value_end]
            external_cursor = value_end
        raw_entries.append(
            RawTiffEntry(
                tag_id=entry.tag_id,
                field_type=entry.field_type,
                count=entry.count,
                raw_value=raw_value,
            )
        )
    return RawTiffDirectory(
        entries=tuple(raw_entries),
        next_ifd_offset=parsed.next_ifd_offset,
    )


def missing_original_decision_data_coordinates(
    status: DngOriginalDecisionDataCoordinateStatus,
    reason: str,
    endian: Endian | None,
    evidence_ids: tuple[EvidenceId, ...],
    dng_private_data_value_offset: int | None = None,
    adobe_makn_record_offset: int | None = None,
    adobe_makn_data_offset: int | None = None,
    adobe_makn_data_size: int | None = None,
    maker_notes_directory_offset: int | None = None,
    tiff_base_offset: int | None = None,
) -> DngOriginalDecisionDataFullFileCoordinates:
    return DngOriginalDecisionDataFullFileCoordinates(
        status=status,
        reason=reason,
        endian=endian,
        dng_private_data_value_offset=dng_private_data_value_offset,
        adobe_makn_record_offset=adobe_makn_record_offset,
        adobe_makn_data_offset=adobe_makn_data_offset,
        adobe_makn_data_size=adobe_makn_data_size,
        maker_notes_directory_offset=maker_notes_directory_offset,
        tiff_base_offset=tiff_base_offset,
        original_decision_data_offset_value_field_offset=None,
        original_decision_data_offset_value_field_directory_offset=None,
        existing_offset_value=None,
        rebuilt_value_buffer_start_offset=None,
        rebuilt_value_buffer_prefix_byte_count=None,
        rebuilt_odd_payload_start_offset=None,
        evidence_ids=evidence_ids,
    )


def rewrite_dng_owner_name(tiff_data: bytes, owner_name: str) -> DngOwnerNameRewriteResult:
    exif_plan = build_exif_scalar_write_plan(
        image_description=None,
        orientation=None,
        date_time_original=None,
        owner_name=owner_name,
    )
    rewrite_result = rewrite_tiff_exif_scalars_creating_if_needed(tiff_data, exif_plan)
    return DngOwnerNameRewriteResult(
        data=rewrite_result.data,
        exif_scalar_plan=exif_plan,
        rewrite_result=rewrite_result,
    )
