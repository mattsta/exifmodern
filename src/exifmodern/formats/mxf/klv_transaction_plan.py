"""Source-backed, non-mutating MXF KLV metadata transaction plans.

The planner mirrors the MXF traversal decisions in ExifTool's ``MXF.pm``
without changing bytes.  It validates header-partition KLV keys, decodes BER
lengths, records primer/local-set routing, preserves unknown KLV packets and
large essence payloads, and keeps all byte emission behind explicit gates.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

MXF_KEY_SIZE = 16
MXF_LOCAL_SET_ITEM_HEADER_SIZE = 4
MXF_MAX_EXIFTOOL_IN_MEMORY_VALUE_SIZE = 10_000_000
MXF_MAX_EXIFTOOL_UNKNOWN_READ_SIZE = 65_536

MXF_OPEN_HEADER_UL = "060e2b34.0205.0101.0d010201.01020100"
MXF_CLOSED_HEADER_UL = "060e2b34.0205.0101.0d010201.01020200"
MXF_OPEN_COMPLETE_HEADER_UL = "060e2b34.0205.0101.0d010201.01020300"
MXF_CLOSED_COMPLETE_HEADER_UL = "060e2b34.0205.0101.0d010201.01020400"
MXF_PRIMER_UL = "060e2b34.0205.0101.0d010201.01050100"
MXF_RANDOM_INDEX_METADATA_UL = "060e2b34.0205.0101.0d010201.01110100"
MXF_INDEX_TABLE_SEGMENT_UL = "060e2b34.0253.0101.0d010201.01100100"
MXF_PREFACE_UL = "060e2b34.0253.0101.0d010101.01012f00"
MXF_ESSENCE_ELEMENT_UL = "060e2b34.0102.0101.0d010301.15010800"

type MxfKlvAction = Literal[
    "process_header_partition",
    "process_primer_pack",
    "process_local_set",
    "preserve_unknown_klv",
    "preserve_partition_or_footer_pack",
    "preserve_random_index_pack",
    "preserve_index_table_segment",
    "preserve_large_essence_payload",
]
type MxfBerLengthForm = Literal["short", "long"]
type MxfMetadataRouteAction = Literal[
    "route_known_metadata_tag",
    "preserve_unknown_local_tag",
    "route_unresolved_local_tag",
]
type MxfResponsibilityConcern = Literal[
    "header_partition_key_validation",
    "ber_length_decoding",
    "primer_pack_mapping",
    "local_set_routing",
    "metadata_set_database_routing",
    "rip_and_index_preservation",
    "unknown_klv_preservation",
    "large_essence_preservation",
    "partition_offset_rewrite_blocker",
    "output_emission_gate",
]
type MxfEmissionGateCode = Literal[
    "truncated_klv_key",
    "unsupported_header_partition_key",
    "invalid_ber_length",
    "truncated_ber_length",
    "truncated_klv_value",
    "malformed_primer_pack",
    "malformed_local_set",
    "large_essence_payload_preserved_without_rewrite",
    "partition_or_offset_rewrite_required",
    "planner_is_non_mutating",
    "full_mxf_writer_not_implemented",
]

MXF_MAIN_TABLE_SOURCE = "mxf_main_table"
MXF_HEADER_TABLE_SOURCE = "mxf_header_table"
MXF_BER_LENGTH_SOURCE = "mxf_ber_length"
MXF_PROCESS_SOURCE = "mxf_process"
MXF_PRIMER_SOURCE = "mxf_primer"
MXF_LOCAL_SET_SOURCE = "mxf_local_set"
MXF_OBJECT_GRAPH_SOURCE = "mxf_object_graph"
MXF_DURATION_SOURCE = "mxf_duration"
MXF_UNKNOWN_SOURCE = "mxf_unknown"
MXF_FINAL_FIXUP_SOURCE = "mxf_final_fixup"

MXF_HEADER_PARTITION_ULS = {
    MXF_OPEN_HEADER_UL,
    MXF_CLOSED_HEADER_UL,
    MXF_OPEN_COMPLETE_HEADER_UL,
    MXF_CLOSED_COMPLETE_HEADER_UL,
}

MXF_KNOWN_KLVS: dict[str, tuple[str, MxfKlvAction, tuple[str, ...]]] = {
    MXF_OPEN_HEADER_UL: ("OpenHeader", "process_header_partition", (MXF_MAIN_TABLE_SOURCE,)),
    MXF_CLOSED_HEADER_UL: ("ClosedHeader", "process_header_partition", (MXF_MAIN_TABLE_SOURCE,)),
    MXF_OPEN_COMPLETE_HEADER_UL: (
        "OpenCompleteHeader",
        "process_header_partition",
        (MXF_MAIN_TABLE_SOURCE,),
    ),
    MXF_CLOSED_COMPLETE_HEADER_UL: (
        "ClosedCompleteHeader",
        "process_header_partition",
        (MXF_MAIN_TABLE_SOURCE,),
    ),
    "060e2b34.0205.0101.0d010201.01030100": (
        "OpenBodyPartition",
        "preserve_partition_or_footer_pack",
        (MXF_MAIN_TABLE_SOURCE,),
    ),
    "060e2b34.0205.0101.0d010201.01040200": (
        "Footer",
        "preserve_partition_or_footer_pack",
        (MXF_MAIN_TABLE_SOURCE,),
    ),
    MXF_PRIMER_UL: ("Primer", "process_primer_pack", (MXF_MAIN_TABLE_SOURCE, MXF_PRIMER_SOURCE)),
    "060e2b34.0205.0101.0d010201.01110000": (
        "RandomIndexMetadataV10",
        "preserve_random_index_pack",
        (MXF_MAIN_TABLE_SOURCE,),
    ),
    MXF_RANDOM_INDEX_METADATA_UL: (
        "RandomIndexMetadata",
        "preserve_random_index_pack",
        (MXF_MAIN_TABLE_SOURCE,),
    ),
    "060e2b34.0206.0101.0d010200.00000000": (
        "PartitionMetadata",
        "preserve_partition_or_footer_pack",
        (MXF_MAIN_TABLE_SOURCE,),
    ),
    MXF_INDEX_TABLE_SEGMENT_UL: (
        "IndexTableSegment",
        "preserve_index_table_segment",
        (MXF_MAIN_TABLE_SOURCE,),
    ),
    MXF_PREFACE_UL: ("Preface", "process_local_set", (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE)),
    "060e2b34.0253.0101.0d010101.01013000": (
        "Identification",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01010200": (
        "StructuralComponent",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01010f00": (
        "SequenceSet",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01011400": (
        "TimecodeComponent",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01011800": (
        "ContentStorageSet",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01012300": (
        "EssenceContainerDataSet",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01012500": (
        "FileDescriptor",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01012700": (
        "GenericPictureEssenceDescriptor",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01012800": (
        "CDCIEssenceDescriptor",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01012900": (
        "RGBAEssenceDescriptor",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01013400": (
        "GenericPackage",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01013600": (
        "MaterialPackage",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01013700": (
        "SourcePackage",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01013800": (
        "GenericTrack",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01013900": (
        "EventTrack",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01013a00": (
        "StaticTrack",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01013b00": (
        "Track",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01014200": (
        "GenericSoundEssenceDescriptor",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01014700": (
        "AES3PCMDescriptor",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
    "060e2b34.0253.0101.0d010101.01014800": (
        "WaveAudioDescriptor",
        "process_local_set",
        (MXF_MAIN_TABLE_SOURCE, MXF_LOCAL_SET_SOURCE),
    ),
}

MXF_METADATA_TAGS: dict[str, str] = {
    "060e2b34.0101.0101.01011502.00000000": "InstanceUID",
    "060e2b34.0101.0101.01030302.01000000": "PackageName",
    "060e2b34.0101.0102.01040103.00000000": "TrackNumber",
    "060e2b34.0101.0102.01070101.00000000": "TrackID",
    "060e2b34.0101.0102.01070102.01000000": "TrackName",
    "060e2b34.0101.0102.03010201.05000000": "SDKVersion",
    "060e2b34.0101.0102.05300405.00000000": "EditRate",
    "060e2b34.0101.0105.05300406.00000000": "EditRate",
    "060e2b34.0101.0102.05200701.0a000000": "ToolkitVersion",
    "060e2b34.0101.0102.07020110.01030000": "CreateDate",
    "060e2b34.0101.0102.07020110.02030000": "ModifyDate",
    "060e2b34.0101.0102.07020110.02040000": "ContainerLastModifyDate",
    "060e2b34.0101.0102.07020110.02050000": "PackageLastModifyDate",
    "060e2b34.0101.0102.07020201.01030000": "Duration",
    "060e2b34.0101.0102.07020103.01030000": "Origin",
    "060e2b34.0101.0102.07020103.01050000": "StartTimecode",
    "060e2b34.0101.0102.04070100.00000000": "ComponentDataDefinition",
    "060e2b34.0101.0102.04040101.02060000": "RoundedTimecodeTimebase",
    "060e2b34.0101.0101.04040101.05000000": "DropFrame",
    "060e2b34.0101.0102.05200701.02010000": "ApplicationSupplierName",
    "060e2b34.0101.0102.05200701.03010000": "ApplicationName",
    "060e2b34.0101.0102.05200701.05010000": "ApplicationVersionString",
    "060e2b34.0101.0102.05200701.06010000": "ApplicationPlatform",
    "060e2b34.0101.0101.04060101.00000000": "SampleRate",
    "060e2b34.0101.0101.04060102.00000000": "EssenceLength",
    "060e2b34.0101.0104.01030404.00000000": "EssenceStreamID",
    "060e2b34.0101.0104.04020301.04000000": "LockedIndicator",
    "060e2b34.0101.0104.04020303.04000000": "BitsPerAudioSample",
    "060e2b34.0101.0103.01030302.01000000": "PackageName",
    "060e2b34.0101.0105.04020101.04000000": "ChannelCount",
    "060e2b34.0101.0105.04020301.01010000": "AudioSampleRate",
    "060e2b34.0101.0105.04020302.01000000": "BlockAlign",
    "060e2b34.0101.0105.04020303.05000000": "AverageBytesPerSecond",
    "060e2b34.0101.0105.06010103.05000000": "LinkedTrackID",
}
MXF_METADATA_FORMATS: dict[str, str] = {
    "060e2b34.0101.0101.01011502.00000000": "GUID",
    "060e2b34.0101.0101.01030302.01000000": "UTF-16",
    "060e2b34.0101.0102.01040103.00000000": "int32u",
    "060e2b34.0101.0102.01070101.00000000": "int32u",
    "060e2b34.0101.0102.01070102.01000000": "UTF-16",
    "060e2b34.0101.0102.03010201.05000000": "VersionType",
    "060e2b34.0101.0102.05300405.00000000": "rational64s",
    "060e2b34.0101.0102.05200701.0a000000": "ProductVersion",
    "060e2b34.0101.0102.07020110.01030000": "Timestamp",
    "060e2b34.0101.0102.07020110.02030000": "Timestamp",
    "060e2b34.0101.0102.07020110.02040000": "Timestamp",
    "060e2b34.0101.0102.07020110.02050000": "Timestamp",
    "060e2b34.0101.0102.07020201.01030000": "length",
    "060e2b34.0101.0102.07020103.01030000": "int64s",
    "060e2b34.0101.0102.07020103.01050000": "int64s",
    "060e2b34.0101.0102.04070100.00000000": "WeakReference",
    "060e2b34.0101.0102.04040101.02060000": "int16u",
    "060e2b34.0101.0101.04040101.05000000": "Boolean",
    "060e2b34.0101.0102.05200701.02010000": "UTF-16",
    "060e2b34.0101.0102.05200701.03010000": "UTF-16",
    "060e2b34.0101.0102.05200701.05010000": "UTF-16",
    "060e2b34.0101.0102.05200701.06010000": "UTF-16",
    "060e2b34.0101.0105.05300406.00000000": "rational64s",
    "060e2b34.0101.0101.04060101.00000000": "rational64s",
    "060e2b34.0101.0101.04060102.00000000": "length",
    "060e2b34.0101.0104.01030404.00000000": "int32u",
    "060e2b34.0101.0104.04020301.04000000": "Boolean",
    "060e2b34.0101.0104.04020303.04000000": "int32u",
    "060e2b34.0101.0103.01030302.01000000": "UTF-16",
    "060e2b34.0101.0105.04020101.04000000": "int32u",
    "060e2b34.0101.0105.04020301.01010000": "rational64s",
    "060e2b34.0101.0105.04020302.01000000": "int16u",
    "060e2b34.0101.0105.04020303.05000000": "int32u",
    "060e2b34.0101.0105.06010103.05000000": "int32u",
    "060e2b34.0101.0102.06010104.02010000": "StrongReference",
    "060e2b34.0101.0104.06010104.01080000": "StrongReference",
    "060e2b34.0101.0102.06010104.02030000": "StrongReference",
    "060e2b34.0101.0102.06010104.02040000": "StrongReference",
    "060e2b34.0101.0102.06010104.05010000": "StrongReferenceBatch",
    "060e2b34.0101.0102.06010104.05020000": "StrongReferenceBatch",
    "060e2b34.0101.0102.06010104.06040000": "StrongReferenceBatch",
    "060e2b34.0101.0102.06010104.06050000": "StrongReferenceBatch",
    "060e2b34.0101.0102.06010104.06090000": "StrongReferenceBatch",
}


@dataclass(frozen=True)
class MxfBerLengthPlan:
    form: MxfBerLengthForm
    first_byte: int
    encoded_size: int
    value_length: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "encoded_size": self.encoded_size,
            "first_byte": self.first_byte,
            "form": self.form,
            "value_length": self.value_length,
        }


@dataclass(frozen=True)
class MxfPrimerMappingPlan:
    local_tag: int
    global_ul: str
    entry_offset: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "entry_offset": self.entry_offset,
            "global_ul": self.global_ul,
            "local_tag": f"0x{self.local_tag:04x}",
        }


@dataclass(frozen=True)
class MxfMetadataSetRoutePlan:
    packet_offset: int
    set_name: str
    local_tag: int
    global_ul: str | None
    tag_name: str
    action: MxfMetadataRouteAction
    item_offset: int
    value_offset: int
    value_size: int
    format_name: str | None
    decoded_value: JsonValue
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "global_ul": self.global_ul,
            "item_offset": self.item_offset,
            "local_tag": f"0x{self.local_tag:04x}",
            "packet_offset": self.packet_offset,
            "set_name": self.set_name,
            "tag_name": self.tag_name,
            "value_offset": self.value_offset,
            "value_size": self.value_size,
            "format_name": self.format_name,
            "decoded_value": self.decoded_value,
        }


@dataclass(frozen=True)
class MxfKlvPacketPlan:
    ul: str
    name: str
    action: MxfKlvAction
    offset: int
    value_offset: int
    value_length: int
    end_offset: int | None
    ber_length: MxfBerLengthPlan
    preserved_prefix_size: int
    evidence_ids: tuple[str, ...]

    @property
    def total_size(self) -> int | None:
        if self.end_offset is None:
            return None
        return self.end_offset - self.offset

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "ber_length": self.ber_length.to_json(),
            "end_offset": self.end_offset,
            "name": self.name,
            "offset": self.offset,
            "preserved_prefix_size": self.preserved_prefix_size,
            "total_size": self.total_size,
            "ul": self.ul,
            "value_length": self.value_length,
            "value_offset": self.value_offset,
        }


@dataclass(frozen=True)
class MxfResponsibilityPlan:
    order: int
    concern: MxfResponsibilityConcern
    description: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "description": self.description,
            "order": self.order,
        }


@dataclass(frozen=True)
class MxfEmissionGate:
    code: MxfEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MxfHeaderPartitionValidationPlan:
    is_valid: bool
    ul: str | None
    run_in_size: int | None
    reason: MxfEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "is_valid": self.is_valid,
            "reason": self.reason,
            "run_in_size": self.run_in_size,
            "ul": self.ul,
        }


@dataclass(frozen=True)
class MxfKlvMetadataTransactionPlan:
    header_partition_validation: MxfHeaderPartitionValidationPlan
    klv_packets: tuple[MxfKlvPacketPlan, ...]
    primer_mappings: tuple[MxfPrimerMappingPlan, ...]
    metadata_routes: tuple[MxfMetadataSetRoutePlan, ...]
    responsibilities: tuple[MxfResponsibilityPlan, ...]
    output_emission_gates: tuple[MxfEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def packet_names(self) -> tuple[str, ...]:
        return tuple(packet.name for packet in self.klv_packets)

    @property
    def preserved_unknown_count(self) -> int:
        return sum(1 for packet in self.klv_packets if packet.action == "preserve_unknown_klv")

    @property
    def preserved_large_essence_bytes(self) -> int:
        return sum(
            packet.value_length
            for packet in self.klv_packets
            if packet.action == "preserve_large_essence_payload"
        )

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"MXF KLV metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "header_partition_validation": self.header_partition_validation.to_json(),
            "klv_packets": [packet.to_json() for packet in self.klv_packets],
            "metadata_routes": [route.to_json() for route in self.metadata_routes],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "packet_names": list(self.packet_names),
            "preserved_large_essence_bytes": self.preserved_large_essence_bytes,
            "preserved_unknown_count": self.preserved_unknown_count,
            "primer_mappings": [mapping.to_json() for mapping in self.primer_mappings],
            "responsibilities": [item.to_json() for item in self.responsibilities],
        }


def build_mxf_klv_metadata_transaction_plan(data: bytes) -> MxfKlvMetadataTransactionPlan:
    """Build a non-mutating MXF KLV metadata transaction plan."""

    header_validation, start, validation_gates = validate_header_partition(data)
    klv_packets, packet_gates = parse_klv_packets(data, start)
    primer_mappings, primer_gates = parse_primer_mappings(data, klv_packets)
    primer_lookup = {mapping.local_tag: mapping.global_ul for mapping in primer_mappings}
    metadata_routes, route_gates = parse_metadata_routes(data, klv_packets, primer_lookup)
    gates = [*validation_gates, *packet_gates, *primer_gates, *route_gates]

    if any(packet.action == "preserve_large_essence_payload" for packet in klv_packets):
        gates.append(
            MxfEmissionGate(
                "large_essence_payload_preserved_without_rewrite",
                "Large essence KLV payloads are preserved as opaque bytes and are not rewritten.",
                True,
                (MXF_UNKNOWN_SOURCE,),
            )
        )

    if header_validation.is_valid:
        gates.append(
            MxfEmissionGate(
                "partition_or_offset_rewrite_required",
                (
                    "MXF KLV emission requires partition pack, HeaderSize, FooterPosition, "
                    "RIP, and index offset repair rather than local byte replacement."
                ),
                True,
                (MXF_HEADER_TABLE_SOURCE, MXF_PROCESS_SOURCE, MXF_FINAL_FIXUP_SOURCE),
            )
        )

    gates.extend(
        (
            MxfEmissionGate(
                "planner_is_non_mutating",
                "MXF KLV transaction plans record decisions but do not mutate bytes.",
                True,
                (MXF_PROCESS_SOURCE,),
            ),
            MxfEmissionGate(
                "full_mxf_writer_not_implemented",
                "Safe emission requires a complete MXF writer with partition and offset repair.",
                True,
                (MXF_HEADER_TABLE_SOURCE, MXF_PROCESS_SOURCE),
            ),
        )
    )
    responsibilities = default_responsibilities()
    sources = unique_sources(
        (
            *header_validation.evidence_ids,
            *(source for packet in klv_packets for source in packet.evidence_ids),
            *(source for mapping in primer_mappings for source in mapping.evidence_ids),
            *(source for route in metadata_routes for source in route.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
        )
    )
    return MxfKlvMetadataTransactionPlan(
        header_partition_validation=header_validation,
        klv_packets=klv_packets,
        primer_mappings=primer_mappings,
        metadata_routes=metadata_routes,
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
    )


def validate_header_partition(
    data: bytes,
) -> tuple[MxfHeaderPartitionValidationPlan, int, tuple[MxfEmissionGate, ...]]:
    if len(data) < MXF_KEY_SIZE:
        return (
            MxfHeaderPartitionValidationPlan(
                False,
                None,
                None,
                "truncated_klv_key",
                (MXF_PROCESS_SOURCE,),
            ),
            0,
            (
                MxfEmissionGate(
                    "truncated_klv_key",
                    "Input ended before an MXF 16-byte KLV key could be read.",
                    True,
                    (MXF_PROCESS_SOURCE,),
                ),
            ),
        )

    start = find_header_partition_start(data)
    if start is None:
        first_ul = ul_from_key(data[:MXF_KEY_SIZE])
        return (
            MxfHeaderPartitionValidationPlan(
                False,
                first_ul,
                None,
                "unsupported_header_partition_key",
                (MXF_MAIN_TABLE_SOURCE, MXF_PROCESS_SOURCE),
            ),
            0,
            (
                MxfEmissionGate(
                    "unsupported_header_partition_key",
                    (
                        "ExifTool MXF processing searches for an SMPTE header partition "
                        "key before walking KLV packets."
                    ),
                    True,
                    (MXF_MAIN_TABLE_SOURCE, MXF_PROCESS_SOURCE),
                ),
            ),
        )

    ul = ul_from_key(data[start : start + MXF_KEY_SIZE])
    return (
        MxfHeaderPartitionValidationPlan(
            True,
            ul,
            start,
            None,
            (MXF_MAIN_TABLE_SOURCE, MXF_PROCESS_SOURCE),
        ),
        start,
        (),
    )


def parse_klv_packets(
    data: bytes,
    start: int,
) -> tuple[tuple[MxfKlvPacketPlan, ...], tuple[MxfEmissionGate, ...]]:
    packets: list[MxfKlvPacketPlan] = []
    gates: list[MxfEmissionGate] = []
    offset = start
    while offset < len(data):
        if offset + MXF_KEY_SIZE > len(data):
            gates.append(
                MxfEmissionGate(
                    "truncated_klv_key",
                    f"Missing MXF KLV key at offset {offset}.",
                    True,
                    (MXF_PROCESS_SOURCE,),
                )
            )
            break

        ul = ul_from_key(data[offset : offset + MXF_KEY_SIZE])
        length_offset = offset + MXF_KEY_SIZE
        ber_length, next_offset, ber_gate = decode_ber_length(data, length_offset)
        if ber_gate:
            gates.append(ber_gate)
            break

        value_offset = next_offset
        value_end = value_offset + ber_length.value_length
        name, action, sources = classify_klv(ul, ber_length.value_length)
        end_offset = value_end if value_end <= len(data) else None
        preserved_prefix_size = preserved_value_prefix_size(action, ber_length.value_length)
        packets.append(
            MxfKlvPacketPlan(
                ul=ul,
                name=name,
                action=action,
                offset=offset,
                value_offset=value_offset,
                value_length=ber_length.value_length,
                end_offset=end_offset,
                ber_length=ber_length,
                preserved_prefix_size=preserved_prefix_size,
                evidence_ids=unique_sources((*sources, MXF_BER_LENGTH_SOURCE, MXF_PROCESS_SOURCE)),
            )
        )
        if value_end > len(data):
            gates.append(
                MxfEmissionGate(
                    "truncated_klv_value",
                    f"MXF KLV {ul} extends beyond available input bytes.",
                    True,
                    (MXF_PROCESS_SOURCE,),
                )
            )
            break
        offset = value_end
    return tuple(packets), tuple(gates)


def decode_ber_length(
    data: bytes,
    offset: int,
) -> tuple[MxfBerLengthPlan, int, MxfEmissionGate | None]:
    if offset >= len(data):
        empty = MxfBerLengthPlan("short", 0, 0, 0, (MXF_BER_LENGTH_SOURCE,))
        return (
            empty,
            offset,
            MxfEmissionGate(
                "truncated_ber_length",
                f"Missing BER length byte at offset {offset}.",
                True,
                (MXF_BER_LENGTH_SOURCE,),
            ),
        )
    first = data[offset]
    if first < 0x80:
        return (
            MxfBerLengthPlan("short", first, 1, first, (MXF_BER_LENGTH_SOURCE,)),
            offset + 1,
            None,
        )

    count = first & 0x7F
    if count == 0 or count > 8:
        return (
            MxfBerLengthPlan("long", first, 1, 0, (MXF_BER_LENGTH_SOURCE,)),
            offset + 1,
            MxfEmissionGate(
                "invalid_ber_length",
                "MXF KLV planning requires definite BER lengths of one to eight bytes.",
                True,
                (MXF_BER_LENGTH_SOURCE,),
            ),
        )
    end = offset + 1 + count
    if end > len(data):
        return (
            MxfBerLengthPlan("long", first, 1 + count, 0, (MXF_BER_LENGTH_SOURCE,)),
            len(data),
            MxfEmissionGate(
                "truncated_ber_length",
                f"BER long-form length at offset {offset} needs {count} bytes.",
                True,
                (MXF_BER_LENGTH_SOURCE,),
            ),
        )
    length = 0
    for item in data[offset + 1 : end]:
        length = length * 256 + item
    return (
        MxfBerLengthPlan("long", first, 1 + count, length, (MXF_BER_LENGTH_SOURCE,)),
        end,
        None,
    )


def parse_primer_mappings(
    data: bytes,
    packets: tuple[MxfKlvPacketPlan, ...],
) -> tuple[tuple[MxfPrimerMappingPlan, ...], tuple[MxfEmissionGate, ...]]:
    mappings: list[MxfPrimerMappingPlan] = []
    gates: list[MxfEmissionGate] = []
    for packet in packets:
        if packet.action != "process_primer_pack":
            continue
        payload = data[packet.value_offset : packet.value_offset + packet.value_length]
        if len(payload) <= 8:
            gates.append(
                MxfEmissionGate(
                    "malformed_primer_pack",
                    "Primer pack is too short for ExifTool's count and item-size fields.",
                    True,
                    (MXF_PRIMER_SOURCE,),
                )
            )
            continue
        count = int.from_bytes(payload[0:4], "big")
        item_size = int.from_bytes(payload[4:8], "big")
        if item_size < 18:
            gates.append(
                MxfEmissionGate(
                    "malformed_primer_pack",
                    "Primer pack item size is smaller than ExifTool's 18-byte minimum.",
                    True,
                    (MXF_PRIMER_SOURCE,),
                )
            )
            continue
        pos = 8
        for _index in range(count):
            if pos + item_size > len(payload):
                gates.append(
                    MxfEmissionGate(
                        "malformed_primer_pack",
                        "Primer pack ended before all declared mapping entries were present.",
                        True,
                        (MXF_PRIMER_SOURCE,),
                    )
                )
                break
            local_tag = int.from_bytes(payload[pos : pos + 2], "big")
            mappings.append(
                MxfPrimerMappingPlan(
                    local_tag=local_tag,
                    global_ul=ul_from_key(payload[pos + 2 : pos + 18]),
                    entry_offset=packet.value_offset + pos,
                    evidence_ids=(MXF_PRIMER_SOURCE,),
                )
            )
            pos += item_size
    return tuple(mappings), tuple(gates)


def parse_metadata_routes(
    data: bytes,
    packets: tuple[MxfKlvPacketPlan, ...],
    primer_lookup: dict[int, str],
) -> tuple[tuple[MxfMetadataSetRoutePlan, ...], tuple[MxfEmissionGate, ...]]:
    routes: list[MxfMetadataSetRoutePlan] = []
    gates: list[MxfEmissionGate] = []
    for packet in packets:
        if packet.action != "process_local_set" or packet.end_offset is None:
            continue
        pos = packet.value_offset
        end = packet.end_offset
        while pos + MXF_LOCAL_SET_ITEM_HEADER_SIZE <= end:
            local_tag = int.from_bytes(data[pos : pos + 2], "big")
            value_size = int.from_bytes(data[pos + 2 : pos + 4], "big")
            value_offset = pos + MXF_LOCAL_SET_ITEM_HEADER_SIZE
            if value_offset + value_size > end:
                gates.append(
                    MxfEmissionGate(
                        "malformed_local_set",
                        f"Local set item 0x{local_tag:04x} extends beyond {packet.name}.",
                        True,
                        (MXF_LOCAL_SET_SOURCE,),
                    )
                )
                break
            global_ul = primer_lookup.get(local_tag)
            tag_name = MXF_METADATA_TAGS.get(global_ul or "", f"LocalTag_0x{local_tag:04x}")
            format_name = MXF_METADATA_FORMATS.get(global_ul or "")
            decoded_value = decode_mxf_metadata_value(
                data[value_offset : value_offset + value_size], format_name
            )
            sources: tuple[str, ...]
            if global_ul is None:
                action: MxfMetadataRouteAction = "route_unresolved_local_tag"
                sources = (MXF_LOCAL_SET_SOURCE, MXF_OBJECT_GRAPH_SOURCE)
            elif global_ul in MXF_METADATA_TAGS:
                action = "route_known_metadata_tag"
                sources = (MXF_LOCAL_SET_SOURCE, MXF_OBJECT_GRAPH_SOURCE, MXF_DURATION_SOURCE)
            else:
                action = "preserve_unknown_local_tag"
                sources = (MXF_LOCAL_SET_SOURCE, MXF_UNKNOWN_SOURCE)
            routes.append(
                MxfMetadataSetRoutePlan(
                    set_name=packet.name,
                    packet_offset=packet.offset,
                    local_tag=local_tag,
                    global_ul=global_ul,
                    tag_name=tag_name,
                    action=action,
                    item_offset=pos,
                    value_offset=value_offset,
                    value_size=value_size,
                    format_name=format_name,
                    decoded_value=decoded_value,
                    evidence_ids=sources,
                )
            )
            pos = value_offset + value_size
        if pos != end and pos + MXF_LOCAL_SET_ITEM_HEADER_SIZE > end:
            gates.append(
                MxfEmissionGate(
                    "malformed_local_set",
                    f"Local set {packet.name} ended with a partial item header.",
                    True,
                    (MXF_LOCAL_SET_SOURCE,),
                )
            )
    return tuple(routes), tuple(gates)


def default_responsibilities() -> tuple[MxfResponsibilityPlan, ...]:
    return (
        MxfResponsibilityPlan(
            1,
            "header_partition_key_validation",
            "Locate and validate the SMPTE header partition key before KLV traversal.",
            (MXF_MAIN_TABLE_SOURCE, MXF_PROCESS_SOURCE),
        ),
        MxfResponsibilityPlan(
            2,
            "ber_length_decoding",
            "Decode KLV BER lengths exactly enough to find value and next-packet boundaries.",
            (MXF_BER_LENGTH_SOURCE,),
        ),
        MxfResponsibilityPlan(
            3,
            "primer_pack_mapping",
            "Build the local-tag to global-UL database from Primer entries.",
            (MXF_PRIMER_SOURCE,),
        ),
        MxfResponsibilityPlan(
            4,
            "local_set_routing",
            "Route local-set items through the primer and preserve unresolved local tags.",
            (MXF_LOCAL_SET_SOURCE,),
        ),
        MxfResponsibilityPlan(
            5,
            "metadata_set_database_routing",
            (
                "Collect metadata-set identity, reference, track, edit-rate, language, "
                "duration, and duplicate-resolution responsibilities for later planners."
            ),
            (MXF_OBJECT_GRAPH_SOURCE, MXF_DURATION_SOURCE, MXF_FINAL_FIXUP_SOURCE),
        ),
        MxfResponsibilityPlan(
            6,
            "rip_and_index_preservation",
            (
                "Preserve RIP and index table KLV packets because ExifTool does not "
                "decode metadata there."
            ),
            (MXF_MAIN_TABLE_SOURCE,),
        ),
        MxfResponsibilityPlan(
            7,
            "unknown_klv_preservation",
            "Preserve unknown KLV packets and only expose bounded prefixes for inspection.",
            (MXF_UNKNOWN_SOURCE,),
        ),
        MxfResponsibilityPlan(
            8,
            "large_essence_preservation",
            "Preserve large essence payloads without attempting in-memory metadata rewrite.",
            (MXF_UNKNOWN_SOURCE,),
        ),
        MxfResponsibilityPlan(
            9,
            "partition_offset_rewrite_blocker",
            "Block emission until partition pack, footer, RIP, and index offsets can be repaired.",
            (MXF_HEADER_TABLE_SOURCE, MXF_PROCESS_SOURCE),
        ),
        MxfResponsibilityPlan(
            10,
            "output_emission_gate",
            "Keep transaction planning non-mutating until a complete MXF writer exists.",
            (MXF_PROCESS_SOURCE,),
        ),
    )


def classify_klv(
    ul: str,
    value_length: int,
) -> tuple[str, MxfKlvAction, tuple[str, ...]]:
    known = MXF_KNOWN_KLVS.get(ul)
    if known:
        return known
    if is_essence_ul(ul) and value_length >= MXF_MAX_EXIFTOOL_IN_MEMORY_VALUE_SIZE:
        return ("EssenceElement", "preserve_large_essence_payload", (MXF_UNKNOWN_SOURCE,))
    return (f"MXF_{ul.replace('.', '')}", "preserve_unknown_klv", (MXF_UNKNOWN_SOURCE,))


def is_essence_ul(ul: str) -> bool:
    return ul.startswith("060e2b34.0102.0101.") or ".0d010301." in ul


def preserved_value_prefix_size(action: MxfKlvAction, value_length: int) -> int:
    if action in {"preserve_unknown_klv", "preserve_large_essence_payload"}:
        return min(value_length, MXF_MAX_EXIFTOOL_UNKNOWN_READ_SIZE)
    return value_length


def decode_mxf_metadata_value(value: bytes, format_name: str | None) -> JsonValue:
    if format_name == "GUID" and len(value) == 16:
        return value.hex()
    if format_name == "UTF-16":
        return value.decode("utf-16be", errors="replace").rstrip("\x00")
    if format_name == "string":
        return value.split(b"\x00", 1)[0].decode("latin-1", errors="replace")
    if format_name == "int16u" and len(value) >= 2:
        return int.from_bytes(value[:2], "big")
    if format_name == "int32u" and len(value) >= 4:
        return int.from_bytes(value[:4], "big")
    if format_name == "int64s" and len(value) >= 8:
        return int.from_bytes(value[:8], "big", signed=True)
    if format_name == "rational64s" and len(value) >= 8:
        numerator = int.from_bytes(value[:4], "big", signed=True)
        denominator = int.from_bytes(value[4:8], "big", signed=True)
        return f"{numerator}/{denominator}"
    if format_name == "VersionType":
        return ".".join(str(item) for item in value)
    if format_name == "ProductVersion":
        values = [
            int.from_bytes(value[index : index + 2], "big") for index in range(0, len(value), 2)
        ]
        while len(values) < 5:
            values.append(0)
        release = {
            0: "unknown",
            1: "released",
            2: "debug",
            3: "patched",
            4: "beta",
            5: "private build",
        }.get(values[4], f"unknown {values[4]}")
        return f"{values[0]}.{values[1]}.{values[2]}.{values[3]} {release}"
    if format_name == "Timestamp" and len(value) >= 8:
        year = int.from_bytes(value[0:2], "big")
        month = value[2]
        day = value[3]
        hour = value[4]
        minute = value[5]
        second = value[6]
        millisecond = value[7] * 4
        if (
            year > 3000
            or month > 12
            or day > 31
            or hour > 24
            or minute > 59
            or second > 59
            or value[7] > 249
        ):
            return f"Invalid (0x{value.hex()})"
        return (
            f"{year:04d}:{month:02d}:{day:02d} "
            f"{hour:02d}:{minute:02d}:{second:02d}.{millisecond:03d}"
        )
    if format_name == "Boolean" and value:
        return "False" if value[:1] == b"\0" else "True"
    if format_name == "length" and len(value) >= 8:
        return int.from_bytes(value[:8], "big", signed=True)
    if format_name == "WeakReference" and len(value) == 16:
        return _decode_mxf_weak_reference(value)
    if format_name == "StrongReference" and len(value) == 16:
        return value.hex()
    if format_name in {"StrongReferenceArray", "StrongReferenceBatch"} and len(value) > 16:
        return _decode_mxf_reference_array(value)
    return value.hex()


def _decode_mxf_weak_reference(value: bytes) -> str:
    if value[0] & 0x80:
        value = value[8:] + value[:8]
    return ul_from_key(value)


def _decode_mxf_reference_array(value: bytes) -> JsonArray:
    count = int.from_bytes(value[:4], "big")
    item_size = int.from_bytes(value[4:8], "big")
    references: JsonArray = []
    if item_size < 16:
        return references
    for index in range(count):
        pos = 8 + index * item_size
        if pos + item_size > len(value):
            break
        references.append(value[pos : pos + 16].hex())
    return references


def find_header_partition_start(data: bytes) -> int | None:
    limit = min(len(data), 65_547)
    for offset in range(0, max(0, limit - MXF_KEY_SIZE + 1)):
        ul = ul_from_key(data[offset : offset + MXF_KEY_SIZE])
        if ul in MXF_HEADER_PARTITION_ULS:
            return offset
    return None


def ul_from_key(value: bytes) -> str:
    if len(value) != MXF_KEY_SIZE:
        raise ValueError("MXF UL data must be exactly 16 bytes.")
    parts = (
        value[0:4].hex(),
        value[4:6].hex(),
        value[6:8].hex(),
        value[8:12].hex(),
        value[12:16].hex(),
    )
    return ".".join(parts)


def key_from_ul(ul: str) -> bytes:
    parts = ul.split(".")
    if len(parts) != 5:
        raise ValueError(f"Invalid MXF UL: {ul}")
    return bytes.fromhex("".join(parts))


def encode_ber_length(length: int) -> bytes:
    """Encode a KLV BER length for synthetic fixtures."""

    if length < 0:
        raise ValueError("MXF BER length must be non-negative.")
    if length < 0x80:
        return bytes((length,))
    size = max(1, (length.bit_length() + 7) // 8)
    return bytes((0x80 | size,)) + length.to_bytes(size, "big")


def encode_mxf_klv(ul: str, payload: bytes) -> bytes:
    """Encode an MXF KLV packet for synthetic fixtures."""

    return key_from_ul(ul) + encode_ber_length(len(payload)) + payload


def encode_primer_pack(entries: tuple[tuple[int, str], ...]) -> bytes:
    payload = len(entries).to_bytes(4, "big") + (18).to_bytes(4, "big")
    for local_tag, global_ul in entries:
        payload += local_tag.to_bytes(2, "big") + key_from_ul(global_ul)
    return payload


def encode_local_set_item(local_tag: int, value: bytes) -> bytes:
    return local_tag.to_bytes(2, "big") + len(value).to_bytes(2, "big") + value


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in references:
        if source in seen:
            continue
        seen.add(source)
        unique.append(source)
    return tuple(unique)


def unique_gates(gates: tuple[MxfEmissionGate, ...]) -> tuple[MxfEmissionGate, ...]:
    unique: list[MxfEmissionGate] = []
    seen: set[MxfEmissionGateCode] = set()
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
