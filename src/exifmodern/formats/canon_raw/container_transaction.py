"""Canon RAW container transaction planning.

This module composes the CR2 and CR3 source-backed staging work into one
container-engine primitive.  It deliberately stops before byte emission because
the remaining work crosses shared TIFF and QuickTime mutation seams.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.canon_raw.cr2_ifd_staging import (
    Cr2CanonMakerNoteBinaryCodecPlan,
    Cr2IptcNaaRelayoutPlan,
    Cr2IptcPayloadStage,
    Cr2TiffIfdMutationStage,
    build_cr2_canon_makernote_binary_codec_plan,
    plan_cr2_iptc_naa_relayout,
    stage_cr2_iptc_naa_payload,
    stage_cr2_tiff_ifd_mutation,
)
from exifmodern.formats.canon_raw.cr2_mutation_plan import (
    Cr2HeaderRebuildPlan,
    Cr2PayloadCopyLedger,
    build_cr2_payload_copy_ledger,
    inspect_cr2_tiff_header,
    plan_cr2_rebuilt_header,
)
from exifmodern.formats.canon_raw.cr2_transaction_ledger import (
    Cr2TiffRewriteTransactionLedger,
    build_cr2_tiff_rewrite_transaction_ledger,
)
from exifmodern.formats.canon_raw.cr3_mutation_plan import (
    Cr3BrandInspection,
    inspect_cr3_ftyp_brand,
    unique_sources,
)
from exifmodern.formats.canon_raw.cr3_transaction_ledger import (
    Cr3QuickTimeRewriteTransactionLedger,
    build_cr3_quicktime_rewrite_transaction_ledger,
)
from exifmodern.formats.canon_raw.write_plan import (
    CR3_CANON_UUID_SOURCE,
    CR3_CTBO_FIXUP_SOURCE,
    CR3_QUICKTIME_CANON2_SOURCE,
    CR3_QUICKTIME_MAP_SOURCE,
    WRITE_CR2_SOURCE,
    CanonRawWriteRequestClassification,
)
from exifmodern.json_types import JsonObject

type EvidenceId = str

type CanonRawContainerTransactionStatus = Literal[
    "cr2_transaction_blocked",
    "cr3_transaction_blocked",
    "unsupported_container",
]
type CanonRawContainerTransactionKind = Literal["cr2_tiff", "cr3_quicktime", "unknown"]
type CanonRawContainerEngineBlockerCode = Literal[
    "shared_tiff_directory_emitter_required",
    "cr2_embedded_iptc_entry_relayout_required",
    "canon_makernote_binary_codec_required",
    "cr2_image_data_and_suffix_copy_required",
    "cr2_header_last_ifd_fixup_required",
    "quicktime_atom_rewrite_engine_required",
    "cr3_xmp_uuid_packet_writer_required",
    "cr3_canon_uuid_tiff_writer_required",
    "cr3_ctbo_mdat_offset_repair_required",
    "cr3_write_last_emission_required",
    "recognized_container_required",
]
type Cr2EmissionReadinessStatus = Literal["blocked_on_shared_tiff_directory_emitter"]
type Cr2EmissionComponentCode = Literal[
    "cr2_header_fixup",
    "ifd_transaction_plan",
    "shared_tiff_directory_emitter_contract",
    "iptc_naa_materialized_entry",
    "canon_makernote_codec_plan",
    "image_data_suffix_copy_ledger",
    "writecr2_output_sequence",
]
type Cr2EmissionReadinessGateCode = Literal[
    "shared_tiff_directory_emitter_required",
    "cr2_header_fixup_ready",
    "ifd_transaction_plan_ready",
    "iptc_naa_entry_ready",
    "canon_makernote_codec_ready",
    "image_data_suffix_ledger_ready",
    "writecr2_output_sequence_ready",
]
type Cr2SharedTiffEmitterContractStatus = Literal["contract_ready_emitter_missing"]
type Cr2SharedTiffDirectoryAction = Literal[
    "write_entry_count_and_entries",
    "write_next_ifd_pointer",
    "append_value_data_area",
    "schedule_subifd_offsets",
    "track_image_data_offset_pairs",
    "apply_top_level_new_data_pos_fixup",
]

WRITE_CR2_OUTPUT_SOURCE = "canon_raw.write_cr2_output"
WRITE_EXIF_DIRECTORY_EMITTER_SOURCE = "canon_raw.write_exif_directory_emitter"
WRITE_EXIF_TOP_LEVEL_CR2_FIXUP_SOURCE = "canon_raw.write_exif_top_level_cr2_fixup"


@dataclass(frozen=True)
class CanonRawContainerEngineBlocker:
    code: CanonRawContainerEngineBlockerCode
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
        }


@dataclass(frozen=True)
class Cr2EmissionReadinessComponent:
    code: Cr2EmissionComponentCode
    status: str
    ready_for_emitter: bool
    artifact: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "artifact": self.artifact,
            "code": self.code,
            "ready_for_emitter": self.ready_for_emitter,
            "status": self.status,
        }


@dataclass(frozen=True)
class Cr2EmissionReadinessGate:
    code: Cr2EmissionReadinessGateCode
    passed: bool
    reason: str
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def blocks_mutation(self) -> bool:
        return not self.passed

    def to_json(self) -> JsonObject:
        return {
            "blocks_mutation": self.blocks_mutation,
            "code": self.code,
            "passed": self.passed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Cr2SharedTiffDirectoryEmitterPayload:
    directory_name: str
    original_offset: int
    planned_entry_count: int
    value_data_start_offset: int
    value_data_final_size: int
    next_ifd_action: str
    offset_pair_count: int
    subifd_schedule_count: int
    required_actions: tuple[Cr2SharedTiffDirectoryAction, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "directory_name": self.directory_name,
            "next_ifd_action": self.next_ifd_action,
            "offset_pair_count": self.offset_pair_count,
            "original_offset": self.original_offset,
            "planned_entry_count": self.planned_entry_count,
            "required_actions": list(self.required_actions),
            "subifd_schedule_count": self.subifd_schedule_count,
            "value_data_final_size": self.value_data_final_size,
            "value_data_start_offset": self.value_data_start_offset,
        }


@dataclass(frozen=True)
class Cr2SharedTiffDirectoryEmitterContract:
    status: Cr2SharedTiffEmitterContractStatus
    tiff_rewrite_base_offset: int
    endian: str
    directory_order: tuple[str, ...]
    directory_payloads: tuple[Cr2SharedTiffDirectoryEmitterPayload, ...]
    materialized_iptc_naa_entry_ready: bool
    materialized_iptc_naa_directory: str | None
    canon_makernote_field_count: int
    canon_makernote_fixup_offsets: tuple[int, ...]
    image_data_copy_required: bool
    header_fixup_required: bool
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_emit_tiff_directory_bytes(self) -> bool:
        return False

    @property
    def blocks_cr2_emission(self) -> bool:
        return True

    @property
    def directory_count(self) -> int:
        return len(self.directory_payloads)

    def to_json(self) -> JsonObject:
        return {
            "blocks_cr2_emission": self.blocks_cr2_emission,
            "can_emit_tiff_directory_bytes": self.can_emit_tiff_directory_bytes,
            "canon_makernote_field_count": self.canon_makernote_field_count,
            "canon_makernote_fixup_offsets": list(self.canon_makernote_fixup_offsets),
            "directory_count": self.directory_count,
            "directory_order": list(self.directory_order),
            "directory_payloads": [payload.to_json() for payload in self.directory_payloads],
            "endian": self.endian,
            "header_fixup_required": self.header_fixup_required,
            "image_data_copy_required": self.image_data_copy_required,
            "materialized_iptc_naa_directory": self.materialized_iptc_naa_directory,
            "materialized_iptc_naa_entry_ready": self.materialized_iptc_naa_entry_ready,
            "status": self.status,
            "tiff_rewrite_base_offset": self.tiff_rewrite_base_offset,
        }


@dataclass(frozen=True)
class Cr2EmissionReadinessPlan:
    status: Cr2EmissionReadinessStatus
    output_sequence: tuple[str, ...]
    components: tuple[Cr2EmissionReadinessComponent, ...]
    gates: tuple[Cr2EmissionReadinessGate, ...]
    remaining_blockers: tuple[CanonRawContainerEngineBlockerCode, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_emit_cr2_bytes(self) -> bool:
        return False

    @property
    def component_count(self) -> int:
        return len(self.components)

    @property
    def passed_gate_count(self) -> int:
        return sum(gate.passed for gate in self.gates)

    @property
    def blocked_gate_count(self) -> int:
        return sum(gate.blocks_mutation for gate in self.gates)

    def to_json(self) -> JsonObject:
        return {
            "blocked_gate_count": self.blocked_gate_count,
            "can_emit_cr2_bytes": self.can_emit_cr2_bytes,
            "component_count": self.component_count,
            "components": [component.to_json() for component in self.components],
            "gates": [gate.to_json() for gate in self.gates],
            "output_sequence": list(self.output_sequence),
            "passed_gate_count": self.passed_gate_count,
            "remaining_blockers": list(self.remaining_blockers),
            "status": self.status,
        }


@dataclass(frozen=True)
class CanonRawContainerTransactionPlan:
    status: CanonRawContainerTransactionStatus
    container_kind: CanonRawContainerTransactionKind
    requested_tags: tuple[str, ...]
    cr2_ifd_stage: Cr2TiffIfdMutationStage | None
    cr2_iptc_stage: Cr2IptcPayloadStage | None
    cr2_iptc_relayout_plan: Cr2IptcNaaRelayoutPlan | None
    cr2_header_fixup_plan: Cr2HeaderRebuildPlan | None
    cr2_payload_copy_ledger: Cr2PayloadCopyLedger | None
    cr2_makernote_codec_plan: Cr2CanonMakerNoteBinaryCodecPlan | None
    cr2_ledger: Cr2TiffRewriteTransactionLedger | None
    cr2_shared_tiff_emitter_contract: Cr2SharedTiffDirectoryEmitterContract | None
    cr2_emission_readiness_plan: Cr2EmissionReadinessPlan | None
    cr3_brand: Cr3BrandInspection | None
    cr3_ledger: Cr3QuickTimeRewriteTransactionLedger | None
    blockers: tuple[CanonRawContainerEngineBlocker, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def blocked_gate_count(self) -> int:
        return sum(blocker.blocks_mutation for blocker in self.blockers)

    def blocker_codes(self) -> tuple[str, ...]:
        return tuple(blocker.code for blocker in self.blockers)

    def to_json(self) -> JsonObject:
        return {
            "blocked_gate_count": self.blocked_gate_count,
            "blockers": [blocker.to_json() for blocker in self.blockers],
            "can_mutate_bytes": self.can_mutate_bytes,
            "container_kind": self.container_kind,
            "cr2_ifd_stage": (
                self.cr2_ifd_stage.to_json() if self.cr2_ifd_stage is not None else None
            ),
            "cr2_iptc_stage": (
                self.cr2_iptc_stage.to_json() if self.cr2_iptc_stage is not None else None
            ),
            "cr2_iptc_relayout_plan": (
                self.cr2_iptc_relayout_plan.to_json()
                if self.cr2_iptc_relayout_plan is not None
                else None
            ),
            "cr2_header_fixup_plan": (
                cr2_header_rebuild_plan_to_json(self.cr2_header_fixup_plan)
                if self.cr2_header_fixup_plan is not None
                else None
            ),
            "cr2_payload_copy_ledger": (
                self.cr2_payload_copy_ledger.to_json()
                if self.cr2_payload_copy_ledger is not None
                else None
            ),
            "cr2_makernote_codec_plan": (
                self.cr2_makernote_codec_plan.to_json()
                if self.cr2_makernote_codec_plan is not None
                else None
            ),
            "cr2_ledger": self.cr2_ledger.to_json() if self.cr2_ledger is not None else None,
            "cr2_shared_tiff_emitter_contract": (
                self.cr2_shared_tiff_emitter_contract.to_json()
                if self.cr2_shared_tiff_emitter_contract is not None
                else None
            ),
            "cr2_emission_readiness_plan": (
                self.cr2_emission_readiness_plan.to_json()
                if self.cr2_emission_readiness_plan is not None
                else None
            ),
            "cr3_brand": (
                {
                    "compatible_brands": list(self.cr3_brand.compatible_brands),
                    "ftyp_size": self.cr3_brand.ftyp_size,
                    "major_brand": self.cr3_brand.major_brand,
                    "recognized": self.cr3_brand.recognized,
                    "status": self.cr3_brand.status,
                }
                if self.cr3_brand is not None
                else None
            ),
            "cr3_ledger": self.cr3_ledger.to_json() if self.cr3_ledger is not None else None,
            "requested_tags": list(self.requested_tags),
            "status": self.status,
        }


def plan_canon_raw_container_transaction(
    data: bytes,
    classification: CanonRawWriteRequestClassification,
) -> CanonRawContainerTransactionPlan:
    if classification.container_kind == "cr2_tiff":
        return plan_cr2_container_transaction(data, classification)
    if classification.container_kind == "cr3_quicktime":
        return plan_cr3_container_transaction(data, classification)
    return CanonRawContainerTransactionPlan(
        status="unsupported_container",
        container_kind="unknown",
        requested_tags=tuple(tag.requested_tag for tag in classification.tags),
        cr2_ifd_stage=None,
        cr2_iptc_stage=None,
        cr2_iptc_relayout_plan=None,
        cr2_header_fixup_plan=None,
        cr2_payload_copy_ledger=None,
        cr2_makernote_codec_plan=None,
        cr2_ledger=None,
        cr2_shared_tiff_emitter_contract=None,
        cr2_emission_readiness_plan=None,
        cr3_brand=None,
        cr3_ledger=None,
        blockers=(
            CanonRawContainerEngineBlocker(
                "recognized_container_required",
                "Canon RAW writes require either the CR2 WriteCR2 path or CR3 QuickTime map.",
                (WRITE_CR2_SOURCE, CR3_QUICKTIME_MAP_SOURCE),
            ),
        ),
        evidence_ids=(WRITE_CR2_SOURCE, CR3_QUICKTIME_MAP_SOURCE),
    )


def plan_cr2_container_transaction(
    data: bytes,
    classification: CanonRawWriteRequestClassification,
) -> CanonRawContainerTransactionPlan:
    ifd_stage = stage_cr2_tiff_ifd_mutation(data, classification)
    iptc_stage = stage_cr2_iptc_naa_payload(data, classification)
    iptc_relayout_plan = plan_cr2_iptc_naa_relayout(data, classification)
    inspection = inspect_cr2_tiff_header(data[:16])
    header_fixup_plan = plan_cr2_rebuilt_header(data[:16], inspection.last_ifd_offset)
    payload_copy_ledger = build_cr2_payload_copy_ledger(data)
    makernote_codec_plan = build_cr2_canon_makernote_binary_codec_plan(
        data,
        classification,
    )
    ledger = build_cr2_tiff_rewrite_transaction_ledger(classification)
    shared_tiff_emitter_contract = build_cr2_shared_tiff_emitter_contract(
        ifd_stage,
        iptc_relayout_plan,
        header_fixup_plan,
        payload_copy_ledger,
        makernote_codec_plan,
    )
    readiness_plan = build_cr2_emission_readiness_plan(
        ifd_stage,
        iptc_relayout_plan,
        header_fixup_plan,
        payload_copy_ledger,
        makernote_codec_plan,
        ledger,
        shared_tiff_emitter_contract,
    )
    blockers = (
        CanonRawContainerEngineBlocker(
            "shared_tiff_directory_emitter_required",
            (
                "CR2 emission has a package-local shared TIFF emitter contract, "
                "but still needs the byte-level shared TIFF directory emitter."
            ),
            shared_tiff_emitter_contract.evidence_ids,
        ),
        *cr2_iptc_relayout_blockers(iptc_relayout_plan),
        *cr2_makernote_codec_blockers(makernote_codec_plan, ifd_stage),
        *cr2_payload_copy_blockers(payload_copy_ledger, ledger),
        *cr2_header_fixup_blockers(header_fixup_plan, ledger),
    )
    evidence_ids = unique_sources(
        (
            *ifd_stage.evidence_ids,
            *iptc_stage.evidence_ids,
            *iptc_relayout_plan.evidence_ids,
            *header_fixup_plan.evidence_ids,
            *payload_copy_ledger.evidence_ids,
            *makernote_codec_plan.evidence_ids,
            *ledger.evidence_ids,
            *shared_tiff_emitter_contract.evidence_ids,
            *readiness_plan.evidence_ids,
        )
    )
    return CanonRawContainerTransactionPlan(
        status="cr2_transaction_blocked",
        container_kind="cr2_tiff",
        requested_tags=ledger.requested_tags,
        cr2_ifd_stage=ifd_stage,
        cr2_iptc_stage=iptc_stage,
        cr2_iptc_relayout_plan=iptc_relayout_plan,
        cr2_header_fixup_plan=header_fixup_plan,
        cr2_payload_copy_ledger=payload_copy_ledger,
        cr2_makernote_codec_plan=makernote_codec_plan,
        cr2_ledger=ledger,
        cr2_shared_tiff_emitter_contract=shared_tiff_emitter_contract,
        cr2_emission_readiness_plan=readiness_plan,
        cr3_brand=None,
        cr3_ledger=None,
        blockers=blockers,
        evidence_ids=evidence_ids,
    )


def plan_cr3_container_transaction(
    data: bytes,
    classification: CanonRawWriteRequestClassification,
) -> CanonRawContainerTransactionPlan:
    brand = inspect_cr3_ftyp_brand(data[:32])
    ledger = build_cr3_quicktime_rewrite_transaction_ledger(classification)
    blockers = (
        CanonRawContainerEngineBlocker(
            "quicktime_atom_rewrite_engine_required",
            (
                "CR3 writes are QuickTime atom rewrites; output must traverse and "
                "rebuild atoms before UUID, mdat, and CTBO fixups can be emitted."
            ),
            (CR3_QUICKTIME_MAP_SOURCE, *ledger.output_emission_gates[1].evidence_ids),
        ),
        CanonRawContainerEngineBlocker(
            "cr3_xmp_uuid_packet_writer_required",
            (
                "Subject and XMP-exif ExposureCompensation require top-level CR3 "
                "XMP uuid payload replacement with oracle padding rules."
            ),
            tuple(
                reference
                for gate in ledger.output_emission_gates
                if gate.code == "xmp_uuid_prefix_and_padding_required"
                for reference in gate.evidence_ids
            ),
        ),
        CanonRawContainerEngineBlocker(
            "cr3_canon_uuid_tiff_writer_required",
            (
                "ExifIFD ExposureCompensation must be written through Canon UUID "
                "CMT TIFF payloads while preserving padding and MakerNote identity."
            ),
            (CR3_CANON_UUID_SOURCE,),
        ),
        CanonRawContainerEngineBlocker(
            "cr3_ctbo_mdat_offset_repair_required",
            (
                "Modified UUID offsets and mdat positions must be registered before "
                "CR3 CTBO item offsets and sizes are patched."
            ),
            tuple(
                reference
                for gate in ledger.output_emission_gates
                if gate.code
                in (
                    "modified_uuid_offsets_registered",
                    "mdat_required_for_ctbo_fixup",
                    "ctbo_entries_resolve_known_item_ids",
                )
                for reference in gate.evidence_ids
            ),
        ),
        CanonRawContainerEngineBlocker(
            "cr3_write_last_emission_required",
            "UUID-Canon2 atoms must be staged and emitted after mdat.",
            (CR3_QUICKTIME_CANON2_SOURCE,),
        ),
    )
    evidence_ids = unique_sources(
        (
            CR3_QUICKTIME_MAP_SOURCE,
            CR3_CANON_UUID_SOURCE,
            CR3_CTBO_FIXUP_SOURCE,
            CR3_QUICKTIME_CANON2_SOURCE,
            *ledger.evidence_ids,
        )
    )
    return CanonRawContainerTransactionPlan(
        status="cr3_transaction_blocked",
        container_kind="cr3_quicktime",
        requested_tags=ledger.requested_tags,
        cr2_ifd_stage=None,
        cr2_iptc_stage=None,
        cr2_iptc_relayout_plan=None,
        cr2_header_fixup_plan=None,
        cr2_payload_copy_ledger=None,
        cr2_makernote_codec_plan=None,
        cr2_ledger=None,
        cr2_shared_tiff_emitter_contract=None,
        cr2_emission_readiness_plan=None,
        cr3_brand=brand,
        cr3_ledger=ledger,
        blockers=blockers,
        evidence_ids=evidence_ids,
    )


def build_cr2_emission_readiness_plan(
    ifd_stage: Cr2TiffIfdMutationStage,
    iptc_relayout_plan: Cr2IptcNaaRelayoutPlan,
    header_fixup_plan: Cr2HeaderRebuildPlan,
    payload_copy_ledger: Cr2PayloadCopyLedger,
    makernote_codec_plan: Cr2CanonMakerNoteBinaryCodecPlan,
    ledger: Cr2TiffRewriteTransactionLedger,
    shared_tiff_emitter_contract: Cr2SharedTiffDirectoryEmitterContract,
) -> Cr2EmissionReadinessPlan:
    """Compose the CR2 emitter boundary without claiming byte emission.

    oracle's WriteCR2 boundary is header + WriteExif data + CopyImageData.
    Everything here is package-local and materialized enough to feed a future
    shared TIFF directory emitter; that emitter remains the only failing gate.
    """

    ifd_transaction_ready = ifd_stage.status == "ready" and ifd_stage.transaction_plan is not None
    components = (
        Cr2EmissionReadinessComponent(
            "cr2_header_fixup",
            header_fixup_plan.status,
            header_fixup_plan.can_emit_header,
            "rebuilt_16_byte_header",
            header_fixup_plan.evidence_ids,
        ),
        Cr2EmissionReadinessComponent(
            "ifd_transaction_plan",
            ifd_stage.status,
            ifd_transaction_ready,
            "staged_ifd_transaction_plan",
            ifd_stage.evidence_ids,
        ),
        Cr2EmissionReadinessComponent(
            "shared_tiff_directory_emitter_contract",
            shared_tiff_emitter_contract.status,
            not shared_tiff_emitter_contract.can_emit_tiff_directory_bytes
            and shared_tiff_emitter_contract.blocks_cr2_emission,
            "typed_shared_tiff_directory_emitter_contract",
            shared_tiff_emitter_contract.evidence_ids,
        ),
        Cr2EmissionReadinessComponent(
            "iptc_naa_materialized_entry",
            iptc_relayout_plan.status,
            iptc_relayout_plan.materialized_entry is not None
            and iptc_relayout_plan.materialized_entry.can_feed_directory_emitter,
            "materialized_iptc_naa_ifd0_entry",
            iptc_relayout_plan.evidence_ids,
        ),
        Cr2EmissionReadinessComponent(
            "canon_makernote_codec_plan",
            makernote_codec_plan.status,
            makernote_codec_plan.can_feed_makernote_rewriter,
            "canon_makernote_partial_ifd_and_fixups",
            makernote_codec_plan.evidence_ids,
        ),
        Cr2EmissionReadinessComponent(
            "image_data_suffix_copy_ledger",
            payload_copy_ledger.status,
            payload_copy_ledger.can_copy_payload_segments,
            "image_data_segments_and_non_tiff_suffix_range",
            payload_copy_ledger.evidence_ids,
        ),
        Cr2EmissionReadinessComponent(
            "writecr2_output_sequence",
            ledger.status,
            ledger.entry_count == 11,
            "header_then_tiff_data_then_image_data_copy_sequence",
            ledger.evidence_ids,
        ),
    )
    gate_sources = tuple(
        reference for gate in ledger.output_emission_gates for reference in gate.evidence_ids
    )
    gates = (
        Cr2EmissionReadinessGate(
            "cr2_header_fixup_ready",
            header_fixup_plan.can_emit_header,
            "The 16-byte CR2 header can be rebuilt with IFD0=16 and LastIFD.",
            header_fixup_plan.evidence_ids,
        ),
        Cr2EmissionReadinessGate(
            "ifd_transaction_plan_ready",
            ifd_transaction_ready,
            "The parsed CR2 IFD graph has a staged directory transaction plan.",
            ifd_stage.evidence_ids,
        ),
        Cr2EmissionReadinessGate(
            "iptc_naa_entry_ready",
            iptc_relayout_plan.materialized_entry is not None
            and iptc_relayout_plan.materialized_entry.can_feed_directory_emitter,
            "Keywords are materialized as an IFD0 IPTC-NAA entry and value-area payload.",
            iptc_relayout_plan.evidence_ids,
        ),
        Cr2EmissionReadinessGate(
            "canon_makernote_codec_ready",
            makernote_codec_plan.can_feed_makernote_rewriter,
            "Canon OwnerName and FocalPlaneXSize are converted to MakerNote codec fields.",
            makernote_codec_plan.evidence_ids,
        ),
        Cr2EmissionReadinessGate(
            "image_data_suffix_ledger_ready",
            payload_copy_ledger.can_copy_payload_segments,
            "Image-data copy ranges and the non-TIFF suffix range are ledgered.",
            payload_copy_ledger.evidence_ids,
        ),
        Cr2EmissionReadinessGate(
            "writecr2_output_sequence_ready",
            ledger.entry_count == 11,
            "The source-backed WriteCR2 output sequence is fully ordered.",
            ledger.evidence_ids,
        ),
        Cr2EmissionReadinessGate(
            "shared_tiff_directory_emitter_required",
            False,
            (
                "A shared TIFF directory byte emitter must consume the staged IFD "
                "transaction before CR2 bytes can be written."
            ),
            unique_sources(gate_sources),
        ),
    )
    return Cr2EmissionReadinessPlan(
        status="blocked_on_shared_tiff_directory_emitter",
        output_sequence=(
            "emit_rebuilt_cr2_header",
            "emit_shared_tiff_directory_payload",
            "copy_recorded_image_data_segments",
            "append_preserved_non_tiff_suffix",
        ),
        components=components,
        gates=gates,
        remaining_blockers=("shared_tiff_directory_emitter_required",),
        evidence_ids=unique_sources(
            (
                *header_fixup_plan.evidence_ids,
                *ifd_stage.evidence_ids,
                *iptc_relayout_plan.evidence_ids,
                *makernote_codec_plan.evidence_ids,
                *payload_copy_ledger.evidence_ids,
                *ledger.evidence_ids,
                *shared_tiff_emitter_contract.evidence_ids,
                *gate_sources,
            )
        ),
    )


def build_cr2_shared_tiff_emitter_contract(
    ifd_stage: Cr2TiffIfdMutationStage,
    iptc_relayout_plan: Cr2IptcNaaRelayoutPlan,
    header_fixup_plan: Cr2HeaderRebuildPlan,
    payload_copy_ledger: Cr2PayloadCopyLedger,
    makernote_codec_plan: Cr2CanonMakerNoteBinaryCodecPlan,
) -> Cr2SharedTiffDirectoryEmitterContract:
    """Adapt staged CR2 IFD planning into a future shared TIFF emitter contract."""

    transaction_plan = ifd_stage.transaction_plan
    directory_payloads: tuple[Cr2SharedTiffDirectoryEmitterPayload, ...] = ()
    directory_order: tuple[str, ...] = ()
    if transaction_plan is not None:
        directory_order = transaction_plan.directory_order
        directory_payloads = tuple(
            Cr2SharedTiffDirectoryEmitterPayload(
                directory_name=directory_plan.directory_name,
                original_offset=original_directory_offset(
                    ifd_stage,
                    directory_plan.directory_name,
                ),
                planned_entry_count=directory_plan.entry_count,
                value_data_start_offset=directory_plan.value_data_area.start_offset,
                value_data_final_size=directory_plan.value_data_area.final_size,
                next_ifd_action=directory_plan.next_ifd_pointer.action,
                offset_pair_count=len(directory_plan.offset_pairs),
                subifd_schedule_count=len(directory_plan.subifd_schedules),
                required_actions=directory_emitter_actions(
                    len(directory_plan.subifd_schedules),
                    len(directory_plan.offset_pairs),
                ),
                evidence_ids=unique_sources(
                    (
                        WRITE_EXIF_DIRECTORY_EMITTER_SOURCE,
                        *directory_plan.evidence_ids,
                    )
                ),
            )
            for directory_plan in transaction_plan.directory_plans
        )

    return Cr2SharedTiffDirectoryEmitterContract(
        status="contract_ready_emitter_missing",
        tiff_rewrite_base_offset=16,
        endian=ifd_stage.endian or "unknown",
        directory_order=directory_order,
        directory_payloads=directory_payloads,
        materialized_iptc_naa_entry_ready=iptc_relayout_plan.materialized_entry is not None
        and iptc_relayout_plan.materialized_entry.can_feed_directory_emitter,
        materialized_iptc_naa_directory=iptc_relayout_plan.directory_name,
        canon_makernote_field_count=len(makernote_codec_plan.materialized_fields),
        canon_makernote_fixup_offsets=makernote_codec_plan.fixup_offsets,
        image_data_copy_required=payload_copy_ledger.can_copy_payload_segments,
        header_fixup_required=header_fixup_plan.can_emit_header,
        evidence_ids=unique_sources(
            (
                WRITE_CR2_OUTPUT_SOURCE,
                WRITE_EXIF_DIRECTORY_EMITTER_SOURCE,
                WRITE_EXIF_TOP_LEVEL_CR2_FIXUP_SOURCE,
                *ifd_stage.evidence_ids,
                *iptc_relayout_plan.evidence_ids,
                *header_fixup_plan.evidence_ids,
                *payload_copy_ledger.evidence_ids,
                *makernote_codec_plan.evidence_ids,
            )
        ),
    )


def directory_emitter_actions(
    subifd_schedule_count: int,
    offset_pair_count: int,
) -> tuple[Cr2SharedTiffDirectoryAction, ...]:
    actions: list[Cr2SharedTiffDirectoryAction] = [
        "write_entry_count_and_entries",
        "write_next_ifd_pointer",
        "append_value_data_area",
    ]
    if subifd_schedule_count:
        actions.append("schedule_subifd_offsets")
    if offset_pair_count:
        actions.append("track_image_data_offset_pairs")
    actions.append("apply_top_level_new_data_pos_fixup")
    return tuple(actions)


def original_directory_offset(
    ifd_stage: Cr2TiffIfdMutationStage,
    directory_name: str,
) -> int:
    for directory in ifd_stage.directories:
        if directory.name == directory_name:
            return directory.original_offset
    return 0


def cr2_iptc_relayout_blockers(
    relayout_plan: Cr2IptcNaaRelayoutPlan,
) -> tuple[CanonRawContainerEngineBlocker, ...]:
    if relayout_plan.materialized_entry is not None:
        return ()
    return (
        CanonRawContainerEngineBlocker(
            "cr2_embedded_iptc_entry_relayout_required",
            (
                "The staged IPTC-NAA payload must be inserted as TIFF tag 0x83bb "
                "with count, padding, and offset relayout."
            ),
            relayout_plan.evidence_ids,
        ),
    )


def cr2_payload_copy_blockers(
    payload_copy_ledger: Cr2PayloadCopyLedger,
    ledger: Cr2TiffRewriteTransactionLedger,
) -> tuple[CanonRawContainerEngineBlocker, ...]:
    if payload_copy_ledger.can_copy_payload_segments:
        return ()
    return (
        CanonRawContainerEngineBlocker(
            "cr2_image_data_and_suffix_copy_required",
            (
                "oracle copies tracked CR2 image data after rewritten TIFF bytes "
                "and CanonRaw.t verifies the non-TIFF suffix survives."
            ),
            unique_sources(
                (
                    *payload_copy_ledger.evidence_ids,
                    *(
                        reference
                        for gate in ledger.output_emission_gates
                        if gate.code
                        in (
                            "image_data_copy_requires_tracked_offsets",
                            "non_tiff_suffix_requires_copy_contract",
                        )
                        for reference in gate.evidence_ids
                    ),
                )
            ),
        ),
    )


def cr2_makernote_codec_blockers(
    makernote_codec_plan: Cr2CanonMakerNoteBinaryCodecPlan,
    ifd_stage: Cr2TiffIfdMutationStage,
) -> tuple[CanonRawContainerEngineBlocker, ...]:
    if makernote_codec_plan.can_feed_makernote_rewriter:
        return ()
    return (
        CanonRawContainerEngineBlocker(
            "canon_makernote_binary_codec_required",
            (
                "Canon MakerNote OwnerName and FocalPlaneXSize writes require the "
                "Canon binary/IFD codec rather than scalar TIFF entry replacement."
            ),
            unique_sources(
                (
                    *makernote_codec_plan.evidence_ids,
                    *(
                        reference
                        for stage in ifd_stage.surface_stages
                        if stage.surface == "cr2_canon_makernote"
                        for reference in stage.evidence_ids
                    ),
                )
            ),
        ),
    )


def cr2_header_fixup_blockers(
    header_fixup_plan: Cr2HeaderRebuildPlan,
    ledger: Cr2TiffRewriteTransactionLedger,
) -> tuple[CanonRawContainerEngineBlocker, ...]:
    if header_fixup_plan.can_emit_header:
        return ()
    return (
        CanonRawContainerEngineBlocker(
            "cr2_header_last_ifd_fixup_required",
            (
                "The 16-byte CR2 header must be rebuilt with IFD0 at byte 16 and "
                "the WriteExif LastIFD pointer before output can be emitted."
            ),
            unique_sources(
                (
                    *header_fixup_plan.evidence_ids,
                    *(
                        reference
                        for gate in ledger.output_emission_gates
                        if gate.code
                        in ("ifd0_pointer_rebased_to_16", "last_ifd_required_before_emit")
                        for reference in gate.evidence_ids
                    ),
                )
            ),
        ),
    )


def cr2_header_rebuild_plan_to_json(plan: Cr2HeaderRebuildPlan) -> JsonObject:
    return {
        "can_emit_header": plan.can_emit_header,
        "original_ifd0_offset": plan.original_ifd0_offset,
        "original_last_ifd_offset": plan.original_last_ifd_offset,
        "rebuilt_header_hex": (
            plan.rebuilt_header.hex() if plan.rebuilt_header is not None else None
        ),
        "rebuilt_ifd0_offset": plan.rebuilt_ifd0_offset,
        "rebuilt_last_ifd_offset": plan.rebuilt_last_ifd_offset,
        "status": plan.status,
    }
