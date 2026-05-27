"""Source-backed, non-mutating ASF metadata transaction plans.

The planner mirrors the ASF traversal and metadata routing decisions in
ExifTool's ``ASF.pm`` without changing bytes.  It validates the ASF header GUID,
walks top-level/header/header-extension records, routes ContentDescription,
CodecList, ExtendedContentDescription, Metadata, and MetadataLibrary payloads,
preserves large and unknown records, and keeps byte emission behind explicit gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from exifmodern.exiftool_compat.core import convert_bitrate, convert_duration
from exifmodern.json_types import JsonArray, JsonObject, JsonValue

ASF_RECORD_HEADER_SIZE = 24
ASF_HEADER_PAYLOAD_PREFIX_SIZE = 6
ASF_HEADER_EXTENSION_PREFIX_SIZE = 22
ASF_MAX_EXIFTOOL_RECORD_PAYLOAD_SIZE = 0x7FFFFFFF
ASF_FILETIME_UNIX_EPOCH_OFFSET_SECONDS = ((1970 - 1601) * 365 + 89) * 24 * 3600

ASF_HEADER_GUID = "75B22630-668E-11CF-A6D9-00AA0062CE6C"
ASF_DATA_GUID = "75B22636-668E-11CF-A6D9-00AA0062CE6C"
ASF_CONTENT_DESCRIPTION_GUID = "75B22633-668E-11CF-A6D9-00AA0062CE6C"
ASF_EXTENDED_CONTENT_DESCRIPTION_GUID = "D2D0A440-E307-11D2-97F0-00A0C95EA850"
ASF_HEADER_EXTENSION_GUID = "5FBF03B5-A92E-11CF-8EE3-00C00C205365"
ASF_CODEC_LIST_GUID = "86D15240-311D-11D0-A3A4-00A0C90348F6"
ASF_METADATA_GUID = "C5F8CBEA-5BAF-4877-8467-AA8C44FA4CCA"
ASF_METADATA_LIBRARY_GUID = "44231C94-9498-49D1-A141-1D134E457054"
ASF_PADDING_GUID = "1806D474-CADF-4509-A4BA-9AABCB96AAE8"

CONTENT_DESCRIPTION_TAGS: dict[int, str] = {
    0: "Title",
    1: "Author",
    2: "Copyright",
    3: "Description",
    4: "Rating",
}

type AsfTraversalTable = Literal["main", "header", "header_extension"]
type AsfMetadataSection = Literal[
    "content_description",
    "extended_content_description",
    "metadata",
    "metadata_library",
    "picture",
]
type AsfMetadataValue = str | int | bool | bytes
type AsfRecordAction = Literal[
    "descend_header",
    "descend_header_extension",
    "route_content_description",
    "route_extended_content_description",
    "route_codec_list",
    "route_metadata",
    "route_metadata_library",
    "preserve",
    "preserve_padding",
    "preserve_unknown",
    "preserve_large_record",
]
type AsfRouteAction = Literal[
    "upsert_content_description",
    "upsert_extended_content_description",
    "upsert_metadata",
    "upsert_metadata_library",
    "delete_content_description",
    "delete_extended_content_description",
    "delete_metadata",
    "delete_metadata_library",
]
type AsfEmissionGateCode = Literal[
    "truncated_asf_record_header",
    "unsupported_asf_header_guid",
    "invalid_asf_record_size",
    "truncated_asf_record_payload",
    "truncated_asf_header_prefix",
    "truncated_asf_header_extension_prefix",
    "malformed_content_description",
    "malformed_extended_content_description",
    "malformed_codec_list",
    "malformed_metadata",
    "malformed_picture",
    "unknown_asf_metadata_tag",
    "large_asf_record_preserved_without_rewrite",
    "size_growth_requires_padding_or_rebuild",
    "planner_is_non_mutating",
    "full_asf_writer_not_implemented",
]
type AsfTraversalConcern = Literal[
    "guid_header_validation",
    "top_level_and_header_traversal",
    "file_and_stream_scalar_routing",
    "metadata_directory_routing",
    "large_record_preservation",
    "padding_size_growth_blocker",
    "output_emission_gate",
]

ASF_GUID_SOURCE = "asf.guid"
ASF_MAIN_TABLE_SOURCE = "asf.main_table"
ASF_HEADER_TABLE_SOURCE = "asf.header_table"
ASF_HEADER_EXTENSION_TABLE_SOURCE = "asf.header_extension_table"
ASF_CONTENT_DESCRIPTION_SOURCE = "asf.content_description"
ASF_CONTENT_DESCRIPTION_PROCESS_SOURCE = "asf.content_description_process"
ASF_EXTENDED_DESCRIPTION_SOURCE = "asf.extended_description"
ASF_METADATA_SOURCE = "asf.metadata"
ASF_CODEC_LIST_SOURCE = "asf.codec_list"
ASF_CODEC_LIST_PROCESS_SOURCE = "asf.codec_list_process"
ASF_READ_VALUE_SOURCE = "asf.read_value"
ASF_PROCESS_TRAVERSAL_SOURCE = "asf.process_traversal"
ASF_LARGE_RECORD_SOURCE = "asf.large_record"
ASF_PADDING_SOURCE = "asf.padding"
ASF_STREAM_TYPE_SOURCE = "asf.stream_type"
ASF_ERROR_CORRECTION_SOURCE = "asf.error_correction"
ASF_FILE_PROPERTIES_SOURCE = "asf.file_properties"
ASF_STREAM_PROPERTIES_SOURCE = "asf.stream_properties"
ASF_EXTENDED_PRINTCONV_SOURCE = "asf.extended_printconv"
ASF_PICTURE_TABLE_SOURCE = "asf.picture_table"
ASF_PICTURE_PROCESS_SOURCE = "asf.picture_process"
ASF_EXTENDED_DESCRIPTOR_TAGS_SOURCE = "asf.extended_descriptor_tags"
RIFF_AUDIO_ENCODING_SOURCE = "riff.audio_encoding"

ASF_STREAM_TYPES: dict[str, str] = {
    "F8699E40-5B4D-11CF-A8FD-00805F5C442B": "Audio",
    "BC19EFC0-5B4D-11CF-A8FD-00805F5C442B": "Video",
    "59DACFC0-59E6-11D0-A3AC-00A0C90348F6": "Command",
    "B61BE100-5B4E-11CF-A8FD-00805F5C442B": "JFIF",
    "35907DE0-E415-11CF-A917-00805F5C442B": "Degradable JPEG",
    "91BD222C-F21C-497A-8B6D-5AA86BFC0185": "File Transfer",
    "3AFB65E2-47EF-40F2-AC2C-70A90D71D343": "Binary",
}
ASF_ERROR_CORRECTIONS: dict[str, str] = {
    "20FB5700-5B55-11CF-A8FD-00805F5C442B": "No Error Correction",
    "BFC3CD50-618F-11CF-8BB2-00AA00B4E220": "Audio Spread",
}
ASF_RIFF_AUDIO_ENCODINGS: dict[int, str] = {
    0x0001: "Microsoft PCM",
    0x0002: "Microsoft ADPCM",
    0x0003: "Microsoft IEEE float",
    0x0006: "Microsoft a-Law",
    0x0007: "Microsoft u-Law",
    0x000A: "WMA 9 Speech",
    0x000B: "Microsoft Windows Media RT Voice",
    0x0050: "Microsoft MPEG",
    0x0055: "MP3",
    0x00FF: "AAC",
    0x0160: "Microsoft Audio1",
    0x0161: "Windows Media Audio V2 V7 V8 V9 / DivX audio (WMA) / Alex AC3 Audio",
    0x0162: "Windows Media Audio Professional V9",
    0x0163: "Windows Media Audio Lossless V9",
    0x0164: "WMA Pro over S/PDIF",
}
ASF_PICTURE_TYPES: dict[int, str] = {
    0: "Other",
    1: "32x32 PNG Icon",
    2: "Other Icon",
    3: "Front Cover",
    4: "Back Cover",
    5: "Leaflet",
    6: "Media",
    7: "Lead Artist",
    8: "Artist",
    9: "Conductor",
    10: "Band",
    11: "Composer",
    12: "Lyricist",
    13: "Recording Studio or Location",
    14: "Recording Session",
    15: "Performance",
    16: "Capture from Movie or Video",
    17: "Bright(ly) Colored Fish",
    18: "Illustration",
    19: "Band Logo",
    20: "Publisher Logo",
}
ASF_BITRATE_TAGS = frozenset(("Bitrate", "CurrentBitrate", "OptimalBitrate", "PeakBitrate"))
ASF_GUID_VALUE_TAGS = frozenset(("MediaClassPrimaryID", "MediaClassSecondaryID"))
ASF_AUTHOR_GROUP_TAGS = frozenset(
    (
        "Author",
        "AuthorURL",
        "Copyright",
        "CopyrightURL",
        "Writer",
    )
)
ASF_TIME_GROUP_TAGS = frozenset(
    (
        "EncodingTime",
        "MediaOriginalBroadcastDateTime",
        "OriginalReleaseTime",
        "OriginalReleaseYear",
        "Year",
    )
)
ASF_EXTENDED_TAG_ALIASES: dict[str, str] = {
    "OriginalFilename": "OriginalFileName",
    "SubTitle": "Subtitle",
    "SubTitleDescription": "SubtitleDescription",
}
ASF_KNOWN_EXTENDED_TAGS = frozenset(
    (
        "ASFLeakyBucketPairs",
        "AlbumArtist",
        "AlbumCoverURL",
        "AlbumTitle",
        "ASFPacketCount",
        "ASFSecurityObjectsSize",
        "AspectRatioX",
        "AspectRatioY",
        "AudioFileURL",
        "AudioSourceURL",
        "Author",
        "AuthorURL",
        "AverageLevel",
        "BannerImageData",
        "BannerImageType",
        "BannerImageURL",
        "BeatsPerMinute",
        "Bitrate",
        "Broadcast",
        "BufferAverage",
        "Can_Skip_Backward",
        "Can_Skip_Forward",
        "Category",
        "Codec",
        "Composer",
        "Conductor",
        "ContainerFormat",
        "ContentDistributor",
        "ContentGroupDescription",
        "Copyright",
        "CopyrightURL",
        "CurrentBitrate",
        "Description",
        "Director",
        "DRM",
        "DRM_ContentID",
        "DRM_DRMHeader",
        "DRM_DRMHeader_ContentDistributor",
        "DRM_DRMHeader_ContentID",
        "DRM_DRMHeader_IndividualizedVersion",
        "DRM_DRMHeader_KeyID",
        "DRM_DRMHeader_LicenseAcqURL",
        "DRM_DRMHeader_SubscriptionContentID",
        "DRM_IndividualizedVersion",
        "DRM_KeyID",
        "DRM_LASignatureCert",
        "DRM_LASignatureLicSrvCert",
        "DRM_LASignaturePrivKey",
        "DRM_LASignatureRootCert",
        "DRM_LicenseAcqURL",
        "DRM_V1LicenseAcqURL",
        "Duration",
        "DVDID",
        "EncodedBy",
        "EncodingSettings",
        "EncodingTime",
        "FileSize",
        "Genre",
        "GenreID",
        "HasArbitraryDataStream",
        "HasAttachedImages",
        "HasAudio",
        "HasFileTransferStream",
        "HasImage",
        "HasScript",
        "HasVideo",
        "InitialKey",
        "Is_Protected",
        "Is_Trusted",
        "ISRC",
        "IsVBR",
        "Language",
        "Lyrics",
        "Lyrics_Synchronised",
        "MCDI",
        "MediaClassPrimaryID",
        "MediaClassSecondaryID",
        "MediaCredits",
        "MediaIsDelay",
        "MediaIsFinale",
        "MediaIsLive",
        "MediaIsPremiere",
        "MediaIsRepeat",
        "MediaIsSAP",
        "MediaIsStereo",
        "MediaIsSubtitled",
        "MediaIsTape",
        "MediaNetworkAffiliation",
        "MediaOriginalBroadcastDateTime",
        "MediaOriginalChannel",
        "MediaStationCallSign",
        "MediaStationName",
        "ModifiedBy",
        "Mood",
        "NSC_Address",
        "NSC_Description",
        "NSC_Email",
        "NSC_Name",
        "NSC_Phone",
        "NumberOfFrames",
        "OptimalBitrate",
        "OriginalAlbumTitle",
        "OriginalArtist",
        "OriginalFileName",
        "OriginalLyricist",
        "OriginalReleaseTime",
        "OriginalReleaseYear",
        "ParentalRating",
        "ParentalRatingReason",
        "PartOfSet",
        "PeakBitrate",
        "PeakValue",
        "Period",
        "Picture",
        "PlaylistDelay",
        "Producer",
        "PromotionURL",
        "ProtectionType",
        "Provider",
        "ProviderCopyright",
        "ProviderRating",
        "ProviderStyle",
        "Publisher",
        "RadioStationName",
        "RadioStationOwner",
        "Rating",
        "Seekable",
        "SharedUserRating",
        "Signature_Name",
        "Stridable",
        "StreamTypeInfo",
        "SubscriptionContentID",
        "Subtitle",
        "SubtitleDescription",
        "Text",
        "Title",
        "ToolName",
        "ToolVersion",
        "Track",
        "TrackNumber",
        "UniqueFileIdentifier",
        "UserWebURL",
        "VBRPeak",
        "VideoClosedCaptioning",
        "VideoFrameRate",
        "VideoHeight",
        "VideoWidth",
        "WMADRCAverageReference",
        "WMADRCAverageTarget",
        "WMADRCPeakReference",
        "WMADRCPeakTarget",
        "WMCollectionGroupID",
        "WMCollectionID",
        "WMContentID",
        "Writer",
        "Year",
    )
)


@dataclass(frozen=True)
class AsfGuidDefinition:
    name: str
    action: AsfRecordAction
    evidence_ids: tuple[str, ...]


MAIN_GUIDS: dict[str, AsfGuidDefinition] = {
    ASF_HEADER_GUID: AsfGuidDefinition(
        "Header",
        "descend_header",
        (ASF_MAIN_TABLE_SOURCE, ASF_PROCESS_TRAVERSAL_SOURCE),
    ),
    ASF_DATA_GUID: AsfGuidDefinition("Data", "preserve", (ASF_MAIN_TABLE_SOURCE,)),
    "33000890-E5B1-11CF-89F4-00A0C90349CB": AsfGuidDefinition(
        "SimpleIndex",
        "preserve",
        (ASF_MAIN_TABLE_SOURCE,),
    ),
}
HEADER_GUIDS: dict[str, AsfGuidDefinition] = {
    "8CABDCA1-A947-11CF-8EE4-00C00C205365": AsfGuidDefinition(
        "FileProperties",
        "preserve",
        (ASF_HEADER_TABLE_SOURCE, ASF_FILE_PROPERTIES_SOURCE),
    ),
    "B7DC0791-A9B7-11CF-8EE6-00C00C205365": AsfGuidDefinition(
        "StreamProperties",
        "preserve",
        (ASF_HEADER_TABLE_SOURCE, ASF_STREAM_PROPERTIES_SOURCE),
    ),
    ASF_HEADER_EXTENSION_GUID: AsfGuidDefinition(
        "HeaderExtension",
        "descend_header_extension",
        (ASF_HEADER_TABLE_SOURCE, ASF_HEADER_EXTENSION_TABLE_SOURCE),
    ),
    ASF_CONTENT_DESCRIPTION_GUID: AsfGuidDefinition(
        "ContentDescription",
        "route_content_description",
        (ASF_HEADER_TABLE_SOURCE, ASF_CONTENT_DESCRIPTION_SOURCE),
    ),
    ASF_CODEC_LIST_GUID: AsfGuidDefinition(
        "CodecList",
        "route_codec_list",
        (ASF_HEADER_TABLE_SOURCE, ASF_CODEC_LIST_SOURCE, ASF_CODEC_LIST_PROCESS_SOURCE),
    ),
    ASF_EXTENDED_CONTENT_DESCRIPTION_GUID: AsfGuidDefinition(
        "ExtendedContentDescr",
        "route_extended_content_description",
        (ASF_HEADER_TABLE_SOURCE, ASF_EXTENDED_DESCRIPTION_SOURCE),
    ),
    ASF_PADDING_GUID: AsfGuidDefinition(
        "Padding",
        "preserve_padding",
        (ASF_HEADER_TABLE_SOURCE, ASF_PADDING_SOURCE),
    ),
}
HEADER_EXTENSION_GUIDS: dict[str, AsfGuidDefinition] = {
    ASF_METADATA_GUID: AsfGuidDefinition(
        "Metadata",
        "route_metadata",
        (ASF_HEADER_EXTENSION_TABLE_SOURCE, ASF_METADATA_SOURCE),
    ),
    ASF_METADATA_LIBRARY_GUID: AsfGuidDefinition(
        "MetadataLibrary",
        "route_metadata_library",
        (ASF_HEADER_EXTENSION_TABLE_SOURCE, ASF_METADATA_SOURCE),
    ),
}


@dataclass(frozen=True)
class AsfRecordPlan:
    guid: str
    name: str
    table: AsfTraversalTable
    path: tuple[str, ...]
    offset: int
    total_size: int
    payload_offset: int
    payload_size: int
    end_offset: int | None
    header_prefix_size: int
    action: AsfRecordAction
    evidence_ids: tuple[str, ...]

    @property
    def full_path(self) -> str:
        return "/".join(self.path)

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "end_offset": self.end_offset,
            "full_path": self.full_path,
            "guid": self.guid,
            "header_prefix_size": self.header_prefix_size,
            "name": self.name,
            "offset": self.offset,
            "payload_offset": self.payload_offset,
            "payload_size": self.payload_size,
            "table": self.table,
            "total_size": self.total_size,
        }


@dataclass(frozen=True)
class AsfMetadataEntryPlan:
    section: AsfMetadataSection
    tag_name: str
    value: AsfMetadataValue
    value_type: int | None
    record_path: str
    value_offset: int
    value_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "record_path": self.record_path,
            "section": self.section,
            "tag_name": self.tag_name,
            "value": metadata_value_to_json(self.value),
            "value_offset": self.value_offset,
            "value_size": self.value_size,
            "value_type": self.value_type,
        }


@dataclass(frozen=True)
class AsfCodecEntryPlan:
    record_path: str
    codec_kind: str
    tag_name: str
    value: str
    value_offset: int
    value_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "codec_kind": self.codec_kind,
            "record_path": self.record_path,
            "tag_name": self.tag_name,
            "value": self.value,
            "value_offset": self.value_offset,
            "value_size": self.value_size,
        }


@dataclass(frozen=True)
class AsfScalarEntryPlan:
    record_path: str
    table_name: str
    tag_name: str
    raw_value: str | int
    rendered_value: str | int | float
    value_offset: int
    value_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "raw_value": self.raw_value,
            "record_path": self.record_path,
            "rendered_value": self.rendered_value,
            "table_name": self.table_name,
            "tag_name": self.tag_name,
            "value_offset": self.value_offset,
            "value_size": self.value_size,
        }


@dataclass(frozen=True)
class AsfMetadataWriteRequest:
    tag_name: str
    value: AsfMetadataValue | None
    section: AsfMetadataSection = "extended_content_description"
    value_type: int = 0


@dataclass(frozen=True)
class AsfMetadataRoute:
    action: AsfRouteAction
    section: AsfMetadataSection
    tag_name: str
    existing_value: AsfMetadataValue | None
    requested_value: AsfMetadataValue | None
    estimated_size_delta: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "estimated_size_delta": self.estimated_size_delta,
            "existing_value": metadata_value_to_json(self.existing_value),
            "requested_value": metadata_value_to_json(self.requested_value),
            "section": self.section,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class AsfTraversalResponsibility:
    order: int
    concern: AsfTraversalConcern
    description: str
    records: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "description": self.description,
            "order": self.order,
            "records": list(self.records),
        }


@dataclass(frozen=True)
class AsfEmissionGate:
    code: AsfEmissionGateCode
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
class AsfGuidHeaderValidation:
    is_valid: bool
    guid: str | None
    reason: AsfEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "guid": self.guid,
            "is_valid": self.is_valid,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AsfMetadataTransactionPlan:
    header_validation: AsfGuidHeaderValidation
    records: tuple[AsfRecordPlan, ...]
    scalar_entries: tuple[AsfScalarEntryPlan, ...]
    codec_entries: tuple[AsfCodecEntryPlan, ...]
    metadata_entries: tuple[AsfMetadataEntryPlan, ...]
    routes: tuple[AsfMetadataRoute, ...]
    responsibilities: tuple[AsfTraversalResponsibility, ...]
    output_emission_gates: tuple[AsfEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def full_paths(self) -> tuple[str, ...]:
        return tuple(record.full_path for record in self.records)

    @property
    def preserved_padding_bytes(self) -> int:
        return sum(
            record.payload_size for record in self.records if record.action == "preserve_padding"
        )

    @property
    def estimated_size_delta(self) -> int:
        return sum(route.estimated_size_delta for route in self.routes)

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"ASF metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "codec_entries": [entry.to_json() for entry in self.codec_entries],
            "estimated_size_delta": self.estimated_size_delta,
            "full_paths": list(self.full_paths),
            "header_validation": self.header_validation.to_json(),
            "metadata_entries": [entry.to_json() for entry in self.metadata_entries],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "preserved_padding_bytes": self.preserved_padding_bytes,
            "records": [record.to_json() for record in self.records],
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "routes": [route.to_json() for route in self.routes],
            "scalar_entries": [entry.to_json() for entry in self.scalar_entries],
        }


def build_asf_metadata_transaction_plan(
    data: bytes,
    metadata_writes: tuple[AsfMetadataWriteRequest, ...] = (),
    *,
    allow_size_growth: bool = False,
) -> AsfMetadataTransactionPlan:
    """Build a non-mutating ASF metadata transaction plan."""

    header_validation, records, parse_gates = inspect_asf_records(data)
    scalar_entries, scalar_gates = extract_scalar_entries(records, data)
    codec_entries, codec_gates = extract_codec_entries(records, data)
    metadata_entries, metadata_gates = extract_metadata_entries(records, data)
    routes = route_metadata_writes(metadata_entries, metadata_writes)
    gates = [*parse_gates, *scalar_gates, *codec_gates, *metadata_gates]

    estimated_growth = sum(max(0, route.estimated_size_delta) for route in routes)
    padding = sum(record.payload_size for record in records if record.action == "preserve_padding")
    if estimated_growth > padding and not allow_size_growth:
        gates.append(
            AsfEmissionGate(
                "size_growth_requires_padding_or_rebuild",
                (
                    f"Planned ASF edits need about {estimated_growth} bytes, but only "
                    f"{padding} Padding bytes are available for in-place growth."
                ),
                True,
                (ASF_PADDING_SOURCE, ASF_PROCESS_TRAVERSAL_SOURCE),
            )
        )

    gates.extend(
        (
            AsfEmissionGate(
                "planner_is_non_mutating",
                "ASF metadata transaction plans record decisions but do not mutate bytes.",
                True,
                (ASF_PROCESS_TRAVERSAL_SOURCE,),
            ),
            AsfEmissionGate(
                "full_asf_writer_not_implemented",
                "Safe emission requires a complete ASF writer with size and padding repair.",
                True,
                (ASF_PROCESS_TRAVERSAL_SOURCE,),
            ),
        )
    )
    responsibilities = default_responsibilities()
    sources = unique_evidence_ids(
        (
            *header_validation.evidence_ids,
            *(source for record in records for source in record.evidence_ids),
            *(source for entry in scalar_entries for source in entry.evidence_ids),
            *(source for entry in codec_entries for source in entry.evidence_ids),
            *(source for entry in metadata_entries for source in entry.evidence_ids),
            *(source for route in routes for source in route.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
        )
    )
    return AsfMetadataTransactionPlan(
        header_validation=header_validation,
        records=records,
        scalar_entries=scalar_entries,
        codec_entries=codec_entries,
        metadata_entries=metadata_entries,
        routes=routes,
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
    )


def inspect_asf_records(
    data: bytes,
) -> tuple[AsfGuidHeaderValidation, tuple[AsfRecordPlan, ...], tuple[AsfEmissionGate, ...]]:
    if len(data) < ASF_RECORD_HEADER_SIZE:
        return (
            AsfGuidHeaderValidation(
                False,
                None,
                "truncated_asf_record_header",
                (ASF_GUID_SOURCE, ASF_PROCESS_TRAVERSAL_SOURCE),
            ),
            (),
            (
                AsfEmissionGate(
                    "truncated_asf_record_header",
                    "Input ended before an ASF GUID plus 64-bit size header could be read.",
                    True,
                    (ASF_GUID_SOURCE, ASF_PROCESS_TRAVERSAL_SOURCE),
                ),
            ),
        )

    first_guid = decode_asf_guid(data[:16])
    if first_guid != ASF_HEADER_GUID:
        return (
            AsfGuidHeaderValidation(
                False,
                first_guid,
                "unsupported_asf_header_guid",
                (ASF_GUID_SOURCE, ASF_MAIN_TABLE_SOURCE),
            ),
            (),
            (
                AsfEmissionGate(
                    "unsupported_asf_header_guid",
                    "ExifTool ASF processing accepts only files beginning with the Header GUID.",
                    True,
                    (ASF_GUID_SOURCE, ASF_MAIN_TABLE_SOURCE, ASF_PROCESS_TRAVERSAL_SOURCE),
                ),
            ),
        )

    records, gates = parse_record_sequence(data, 0, len(data), "main", ())
    return (
        AsfGuidHeaderValidation(
            True,
            first_guid,
            None,
            (ASF_GUID_SOURCE, ASF_MAIN_TABLE_SOURCE, ASF_PROCESS_TRAVERSAL_SOURCE),
        ),
        tuple(records),
        tuple(gates),
    )


def parse_record_sequence(
    data: bytes,
    start: int,
    end: int,
    table: AsfTraversalTable,
    parent_path: tuple[str, ...],
) -> tuple[list[AsfRecordPlan], list[AsfEmissionGate]]:
    records: list[AsfRecordPlan] = []
    gates: list[AsfEmissionGate] = []
    offset = start
    while offset < end:
        if offset + ASF_RECORD_HEADER_SIZE > end or offset + ASF_RECORD_HEADER_SIZE > len(data):
            gates.append(
                AsfEmissionGate(
                    "truncated_asf_record_header",
                    f"Missing ASF record header at offset {offset}.",
                    True,
                    (ASF_PROCESS_TRAVERSAL_SOURCE,),
                )
            )
            break

        guid = decode_asf_guid(data[offset : offset + 16])
        total_size = int.from_bytes(data[offset + 16 : offset + 24], "little")
        if total_size < ASF_RECORD_HEADER_SIZE:
            gates.append(
                AsfEmissionGate(
                    "invalid_asf_record_size",
                    f"ASF record {guid} reports size {total_size}, less than its header.",
                    True,
                    (ASF_PROCESS_TRAVERSAL_SOURCE,),
                )
            )
            break

        payload_size = total_size - ASF_RECORD_HEADER_SIZE
        definition = guid_definition(table, guid)
        record_end = offset + total_size
        if payload_size > ASF_MAX_EXIFTOOL_RECORD_PAYLOAD_SIZE:
            large_end_offset = None if record_end > len(data) else record_end
            records.append(
                AsfRecordPlan(
                    guid=guid,
                    name=definition.name,
                    table=table,
                    path=(*parent_path, definition.name),
                    offset=offset,
                    total_size=total_size,
                    payload_offset=offset + ASF_RECORD_HEADER_SIZE,
                    payload_size=payload_size,
                    end_offset=large_end_offset,
                    header_prefix_size=0,
                    action="preserve_large_record",
                    evidence_ids=unique_evidence_ids(
                        (*definition.evidence_ids, ASF_LARGE_RECORD_SOURCE)
                    ),
                )
            )
            gates.append(
                AsfEmissionGate(
                    "large_asf_record_preserved_without_rewrite",
                    f"ASF record {guid} is too large for planned in-memory rewrite.",
                    True,
                    (ASF_LARGE_RECORD_SOURCE,),
                )
            )
            break

        if record_end > len(data) or record_end > end:
            gates.append(
                AsfEmissionGate(
                    "truncated_asf_record_payload",
                    f"ASF record {guid} extends beyond its parent range.",
                    True,
                    (ASF_PROCESS_TRAVERSAL_SOURCE,),
                )
            )
            break

        prefix_size = header_prefix_size_for_action(definition.action)
        record = AsfRecordPlan(
            guid=guid,
            name=definition.name,
            table=table,
            path=(*parent_path, definition.name),
            offset=offset,
            total_size=total_size,
            payload_offset=offset + ASF_RECORD_HEADER_SIZE,
            payload_size=payload_size,
            end_offset=record_end,
            header_prefix_size=prefix_size,
            action=definition.action,
            evidence_ids=unique_evidence_ids(
                (*definition.evidence_ids, ASF_GUID_SOURCE, ASF_PROCESS_TRAVERSAL_SOURCE)
            ),
        )
        records.append(record)
        child_start = record.payload_offset + prefix_size
        if definition.action == "descend_header":
            if payload_size < ASF_HEADER_PAYLOAD_PREFIX_SIZE:
                gates.append(
                    AsfEmissionGate(
                        "truncated_asf_header_prefix",
                        "ASF Header payload is shorter than ExifTool's six-byte subdirectory skip.",
                        True,
                        (ASF_MAIN_TABLE_SOURCE, ASF_PROCESS_TRAVERSAL_SOURCE),
                    )
                )
            else:
                children, child_gates = parse_record_sequence(
                    data,
                    child_start,
                    record_end,
                    "header",
                    record.path,
                )
                records.extend(children)
                gates.extend(child_gates)
        elif definition.action == "descend_header_extension":
            if payload_size < ASF_HEADER_EXTENSION_PREFIX_SIZE:
                gates.append(
                    AsfEmissionGate(
                        "truncated_asf_header_extension_prefix",
                        (
                            "ASF HeaderExtension payload is shorter than ExifTool's "
                            "22-byte subdirectory skip."
                        ),
                        True,
                        (ASF_HEADER_EXTENSION_TABLE_SOURCE, ASF_PROCESS_TRAVERSAL_SOURCE),
                    )
                )
            else:
                children, child_gates = parse_record_sequence(
                    data,
                    child_start,
                    record_end,
                    "header_extension",
                    record.path,
                )
                records.extend(children)
                gates.extend(child_gates)
        offset = record_end
    return records, gates


def extract_metadata_entries(
    records: tuple[AsfRecordPlan, ...],
    data: bytes,
) -> tuple[tuple[AsfMetadataEntryPlan, ...], tuple[AsfEmissionGate, ...]]:
    entries: list[AsfMetadataEntryPlan] = []
    gates: list[AsfEmissionGate] = []
    for record in records:
        payload = data[record.payload_offset : record.payload_offset + record.payload_size]
        if record.action == "route_content_description":
            record_entries, record_gates = parse_content_description(record, payload)
        elif record.action == "route_extended_content_description":
            record_entries, record_gates = parse_extended_content_description(record, payload)
        elif record.action == "route_metadata":
            record_entries, record_gates = parse_metadata(record, payload, "metadata")
        elif record.action == "route_metadata_library":
            record_entries, record_gates = parse_metadata(record, payload, "metadata_library")
        else:
            continue
        entries.extend(record_entries)
        gates.extend(record_gates)
    return tuple(entries), tuple(gates)


def extract_codec_entries(
    records: tuple[AsfRecordPlan, ...],
    data: bytes,
) -> tuple[tuple[AsfCodecEntryPlan, ...], tuple[AsfEmissionGate, ...]]:
    entries: list[AsfCodecEntryPlan] = []
    gates: list[AsfEmissionGate] = []
    for record in records:
        if record.action != "route_codec_list":
            continue
        payload = data[record.payload_offset : record.payload_offset + record.payload_size]
        record_entries, record_gates = parse_codec_list(record, payload)
        entries.extend(record_entries)
        gates.extend(record_gates)
    return tuple(entries), tuple(gates)


def extract_scalar_entries(
    records: tuple[AsfRecordPlan, ...],
    data: bytes,
) -> tuple[tuple[AsfScalarEntryPlan, ...], tuple[AsfEmissionGate, ...]]:
    entries: list[AsfScalarEntryPlan] = []
    gates: list[AsfEmissionGate] = []
    for record in records:
        payload = data[record.payload_offset : record.payload_offset + record.payload_size]
        if record.name == "FileProperties":
            record_entries, gate = parse_file_properties(record, payload)
        elif record.name == "StreamProperties":
            record_entries, gate = parse_stream_properties(record, payload)
        else:
            continue
        entries.extend(record_entries)
        if gate is not None:
            gates.append(gate)
    return tuple(entries), tuple(gates)


def parse_codec_list(
    record: AsfRecordPlan,
    payload: bytes,
) -> tuple[list[AsfCodecEntryPlan], list[AsfEmissionGate]]:
    if len(payload) < 20:
        return [], [
            AsfEmissionGate(
                "malformed_codec_list",
                "CodecList payload is shorter than ExifTool's 16-byte reserved GUID and count.",
                True,
                (ASF_CODEC_LIST_PROCESS_SOURCE,),
            )
        ]
    count = int.from_bytes(payload[16:20], "little")
    pos = 20
    entries: list[AsfCodecEntryPlan] = []
    gates: list[AsfEmissionGate] = []
    codec_kinds = {1: "Video", 2: "Audio"}
    for index in range(count):
        if pos + 8 > len(payload):
            gates.append(malformed_codec_list_gate(index))
            break
        codec_kind = codec_kinds.get(int.from_bytes(payload[pos : pos + 2], "little"), "Other")
        name_size = int.from_bytes(payload[pos + 2 : pos + 4], "little") * 2
        pos += 4
        if pos + name_size + 2 > len(payload):
            gates.append(malformed_codec_list_gate(index))
            break
        name_offset = record.payload_offset + pos
        name = decode_utf16le(payload[pos : pos + name_size])
        entries.append(
            AsfCodecEntryPlan(
                record.full_path,
                codec_kind,
                f"{codec_kind}CodecName",
                name,
                name_offset,
                name_size,
                (ASF_CODEC_LIST_SOURCE, ASF_CODEC_LIST_PROCESS_SOURCE),
            )
        )
        desc_size = int.from_bytes(payload[pos + name_size : pos + name_size + 2], "little") * 2
        pos += name_size + 2
        if pos + desc_size + 2 > len(payload):
            gates.append(malformed_codec_list_gate(index))
            break
        desc_offset = record.payload_offset + pos
        description = decode_utf16le(payload[pos : pos + desc_size])
        entries.append(
            AsfCodecEntryPlan(
                record.full_path,
                codec_kind,
                f"{codec_kind}CodecDescription",
                description,
                desc_offset,
                desc_size,
                (ASF_CODEC_LIST_SOURCE, ASF_CODEC_LIST_PROCESS_SOURCE),
            )
        )
        info_size = int.from_bytes(payload[pos + desc_size : pos + desc_size + 2], "little")
        pos += desc_size + 2 + info_size
    return entries, gates


def parse_file_properties(
    record: AsfRecordPlan,
    payload: bytes,
) -> tuple[tuple[AsfScalarEntryPlan, ...], AsfEmissionGate | None]:
    if len(payload) < 80:
        return (), AsfEmissionGate(
            "truncated_asf_record_payload",
            "FileProperties payload is shorter than the fixed ASF.pm binary table.",
            True,
            (ASF_FILE_PROPERTIES_SOURCE,),
        )
    entries: list[AsfScalarEntryPlan] = []
    file_id = decode_asf_guid(payload[0:16])
    entries.append(
        AsfScalarEntryPlan(
            record.full_path,
            "FileProperties",
            "FileID",
            file_id,
            file_id,
            record.payload_offset,
            16,
            (ASF_FILE_PROPERTIES_SOURCE, ASF_GUID_SOURCE),
        )
    )
    creation_date = int.from_bytes(payload[24:32], "little")
    entries.append(
        AsfScalarEntryPlan(
            record.full_path,
            "FileProperties",
            "CreationDate",
            creation_date,
            asf_filetime_iso_utc(creation_date),
            record.payload_offset + 24,
            8,
            (ASF_FILE_PROPERTIES_SOURCE,),
        )
    )
    specs: tuple[tuple[str, int, int], ...] = (
        ("FileLength", 16, 8),
        ("DataPackets", 32, 8),
        ("Duration", 40, 8),
        ("SendDuration", 48, 8),
        ("Preroll", 56, 8),
        ("Flags", 64, 4),
        ("MinPacketSize", 68, 4),
        ("MaxPacketSize", 72, 4),
        ("MaxBitrate", 76, 4),
    )
    for tag_name, offset, size in specs:
        raw = int.from_bytes(payload[offset : offset + size], "little")
        entries.append(
            AsfScalarEntryPlan(
                record.full_path,
                "FileProperties",
                tag_name,
                raw,
                render_asf_file_property(tag_name, raw),
                record.payload_offset + offset,
                size,
                (ASF_FILE_PROPERTIES_SOURCE,),
            )
        )
    return tuple(entries), None


def parse_stream_properties(
    record: AsfRecordPlan,
    payload: bytes,
) -> tuple[tuple[AsfScalarEntryPlan, ...], AsfEmissionGate | None]:
    if len(payload) < 54:
        return (), AsfEmissionGate(
            "truncated_asf_record_payload",
            "StreamProperties payload is shorter than the common ASF.pm binary fields.",
            True,
            (ASF_STREAM_PROPERTIES_SOURCE,),
        )
    stream_guid = decode_asf_guid(payload[0:16])
    correction_guid = decode_asf_guid(payload[16:32])
    stream_type = ASF_STREAM_TYPES.get(stream_guid, stream_guid)
    time_offset = int.from_bytes(payload[32:40], "little")
    stream_number = int.from_bytes(payload[48:50], "little")
    entries: list[AsfScalarEntryPlan] = [
        AsfScalarEntryPlan(
            record.full_path,
            "StreamProperties",
            "StreamType",
            stream_guid,
            stream_type,
            record.payload_offset,
            16,
            (ASF_STREAM_PROPERTIES_SOURCE, ASF_STREAM_TYPE_SOURCE, ASF_GUID_SOURCE),
        ),
        AsfScalarEntryPlan(
            record.full_path,
            "StreamProperties",
            "ErrorCorrectionType",
            correction_guid,
            ASF_ERROR_CORRECTIONS.get(correction_guid, correction_guid),
            record.payload_offset + 16,
            16,
            (ASF_STREAM_PROPERTIES_SOURCE, ASF_ERROR_CORRECTION_SOURCE, ASF_GUID_SOURCE),
        ),
        AsfScalarEntryPlan(
            record.full_path,
            "StreamProperties",
            "TimeOffset",
            time_offset,
            f"{time_offset / 10_000_000:g} s",
            record.payload_offset + 32,
            8,
            (ASF_STREAM_PROPERTIES_SOURCE,),
        ),
        AsfScalarEntryPlan(
            record.full_path,
            "StreamProperties",
            "StreamNumber",
            stream_number,
            render_asf_stream_number(stream_number),
            record.payload_offset + 48,
            2,
            (ASF_STREAM_PROPERTIES_SOURCE,),
        ),
    ]
    if stream_type == "Audio" and len(payload) >= 62:
        for tag_name, offset, size in (
            ("AudioCodecID", 54, 2),
            ("AudioChannels", 56, 2),
            ("AudioSampleRate", 58, 4),
        ):
            value = int.from_bytes(payload[offset : offset + size], "little")
            entries.append(
                AsfScalarEntryPlan(
                    record.full_path,
                    "StreamProperties",
                    tag_name,
                    value,
                    render_asf_stream_property(tag_name, value),
                    record.payload_offset + offset,
                    size,
                    stream_property_sources(tag_name),
                )
            )
    elif stream_type in {"Video", "JFIF", "Degradable JPEG"} and len(payload) >= 62:
        for tag_name, offset in (("ImageWidth", 54), ("ImageHeight", 58)):
            value = int.from_bytes(payload[offset : offset + 4], "little")
            entries.append(
                AsfScalarEntryPlan(
                    record.full_path,
                    "StreamProperties",
                    tag_name,
                    value,
                    value,
                    record.payload_offset + offset,
                    4,
                    (ASF_STREAM_PROPERTIES_SOURCE,),
                )
            )
    return tuple(entries), None


def parse_content_description(
    record: AsfRecordPlan,
    payload: bytes,
) -> tuple[list[AsfMetadataEntryPlan], list[AsfEmissionGate]]:
    if len(payload) < 10:
        return [], [
            AsfEmissionGate(
                "malformed_content_description",
                "ContentDescription payload is shorter than five 16-bit lengths.",
                True,
                (ASF_CONTENT_DESCRIPTION_PROCESS_SOURCE,),
            )
        ]
    lengths = [int.from_bytes(payload[index : index + 2], "little") for index in range(0, 10, 2)]
    pos = 10
    entries: list[AsfMetadataEntryPlan] = []
    gates: list[AsfEmissionGate] = []
    for slot, length in enumerate(lengths):
        if length == 0:
            continue
        if pos + length > len(payload):
            gates.append(
                AsfEmissionGate(
                    "malformed_content_description",
                    f"ContentDescription slot {slot} extends beyond the payload.",
                    True,
                    (ASF_CONTENT_DESCRIPTION_PROCESS_SOURCE,),
                )
            )
            break
        entries.append(
            AsfMetadataEntryPlan(
                section="content_description",
                tag_name=CONTENT_DESCRIPTION_TAGS[slot],
                value=decode_utf16le(payload[pos : pos + length]),
                value_type=0,
                record_path=record.full_path,
                value_offset=record.payload_offset + pos,
                value_size=length,
                evidence_ids=(
                    ASF_CONTENT_DESCRIPTION_SOURCE,
                    ASF_CONTENT_DESCRIPTION_PROCESS_SOURCE,
                ),
            )
        )
        pos += length
    return entries, gates


def parse_extended_content_description(
    record: AsfRecordPlan,
    payload: bytes,
) -> tuple[list[AsfMetadataEntryPlan], list[AsfEmissionGate]]:
    if len(payload) < 2:
        return [], [
            AsfEmissionGate(
                "malformed_extended_content_description",
                "ExtendedContentDescr payload is shorter than the descriptor count.",
                True,
                (ASF_EXTENDED_DESCRIPTION_SOURCE,),
            )
        ]
    count = int.from_bytes(payload[:2], "little")
    pos = 2
    entries: list[AsfMetadataEntryPlan] = []
    gates: list[AsfEmissionGate] = []
    for index in range(count):
        if pos + 6 > len(payload):
            gates.append(malformed_extended_gate(index))
            break
        name_len = int.from_bytes(payload[pos : pos + 2], "little")
        pos += 2
        if pos + name_len + 4 > len(payload):
            gates.append(malformed_extended_gate(index))
            break
        tag_name = normalized_asf_tag_name(decode_utf16le(payload[pos : pos + name_len]))
        pos += name_len
        value_type = int.from_bytes(payload[pos : pos + 2], "little")
        value_size = int.from_bytes(payload[pos + 2 : pos + 4], "little")
        pos += 4
        if pos + value_size > len(payload):
            gates.append(malformed_extended_gate(index))
            break
        raw_value = read_asf_value(payload, pos, value_type, value_size)
        known_tag_name = known_extended_tag_name(tag_name)
        if known_tag_name is None:
            gates.append(unknown_metadata_tag_gate(record.name, index))
        elif known_tag_name == "Picture" and isinstance(raw_value, bytes):
            picture_entries, picture_gates = parse_picture(
                raw_value,
                record.full_path,
                record.payload_offset + pos,
            )
            entries.extend(picture_entries)
            gates.extend(picture_gates)
        else:
            entries.append(
                AsfMetadataEntryPlan(
                    section="extended_content_description",
                    tag_name=known_tag_name,
                    value=render_asf_metadata_value(known_tag_name, raw_value),
                    value_type=value_type,
                    record_path=record.full_path,
                    value_offset=record.payload_offset + pos,
                    value_size=value_size,
                    evidence_ids=extended_metadata_sources(known_tag_name),
                )
            )
        pos += value_size
    return entries, gates


def parse_metadata(
    record: AsfRecordPlan,
    payload: bytes,
    section: Literal["metadata", "metadata_library"],
) -> tuple[list[AsfMetadataEntryPlan], list[AsfEmissionGate]]:
    if len(payload) < 2:
        return [], [
            AsfEmissionGate(
                "malformed_metadata",
                f"{record.name} payload is shorter than the descriptor count.",
                True,
                (ASF_METADATA_SOURCE,),
            )
        ]
    count = int.from_bytes(payload[:2], "little")
    pos = 2
    entries: list[AsfMetadataEntryPlan] = []
    gates: list[AsfEmissionGate] = []
    for index in range(count):
        if pos + 12 > len(payload):
            gates.append(malformed_metadata_gate(record.name, index))
            break
        name_len = int.from_bytes(payload[pos + 4 : pos + 6], "little")
        value_type = int.from_bytes(payload[pos + 6 : pos + 8], "little")
        value_size = int.from_bytes(payload[pos + 8 : pos + 12], "little")
        pos += 12
        if pos + name_len + value_size > len(payload):
            gates.append(malformed_metadata_gate(record.name, index))
            break
        tag_name = normalized_asf_tag_name(decode_utf16le(payload[pos : pos + name_len]))
        pos += name_len
        raw_value = read_asf_value(payload, pos, value_type, value_size)
        known_tag_name = known_extended_tag_name(tag_name)
        if known_tag_name is None:
            gates.append(unknown_metadata_tag_gate(record.name, index))
        else:
            entries.append(
                AsfMetadataEntryPlan(
                    section=section,
                    tag_name=known_tag_name,
                    value=render_asf_metadata_value(known_tag_name, raw_value),
                    value_type=value_type,
                    record_path=record.full_path,
                    value_offset=record.payload_offset + pos,
                    value_size=value_size,
                    evidence_ids=metadata_sources(known_tag_name),
                )
            )
        pos += value_size
    return entries, gates


def parse_picture(
    value: bytes,
    record_path: str,
    value_offset: int,
) -> tuple[list[AsfMetadataEntryPlan], list[AsfEmissionGate]]:
    if len(value) <= 9:
        return [], [malformed_picture_gate("WM/Picture payload is shorter than 10 bytes.")]
    picture_type = value[0]
    picture_size = int.from_bytes(value[1:5], "little")
    string_size = len(value) - 5 - picture_size
    if string_size < 4 or string_size % 2 != 0:
        return [], [malformed_picture_gate("WM/Picture string area has invalid length.")]
    picture_offset = 5 + string_size
    if picture_offset + picture_size > len(value):
        return [], [malformed_picture_gate("WM/Picture image payload extends beyond value.")]
    mime, description = parse_picture_strings(value[5:picture_offset])
    entries = [
        AsfMetadataEntryPlan(
            section="picture",
            tag_name="PictureType",
            value=ASF_PICTURE_TYPES.get(picture_type, str(picture_type)),
            value_type=None,
            record_path=record_path,
            value_offset=value_offset,
            value_size=1,
            evidence_ids=(ASF_PICTURE_TABLE_SOURCE, ASF_PICTURE_PROCESS_SOURCE),
        )
    ]
    if mime is not None:
        entries.append(
            AsfMetadataEntryPlan(
                section="picture",
                tag_name="PictureMIMEType",
                value=mime,
                value_type=None,
                record_path=record_path,
                value_offset=value_offset + 5,
                value_size=len(mime.encode("utf-16le")),
                evidence_ids=(ASF_PICTURE_TABLE_SOURCE, ASF_PICTURE_PROCESS_SOURCE),
            )
        )
    if description:
        entries.append(
            AsfMetadataEntryPlan(
                section="picture",
                tag_name="PictureDescription",
                value=description,
                value_type=None,
                record_path=record_path,
                value_offset=value_offset + 5 + len(mime.encode("utf-16le")) + 2
                if mime is not None
                else value_offset + 5,
                value_size=len(description.encode("utf-16le")),
                evidence_ids=(ASF_PICTURE_TABLE_SOURCE, ASF_PICTURE_PROCESS_SOURCE),
            )
        )
    entries.append(
        AsfMetadataEntryPlan(
            section="picture",
            tag_name="Picture",
            value=value[picture_offset : picture_offset + picture_size],
            value_type=None,
            record_path=record_path,
            value_offset=value_offset + picture_offset,
            value_size=picture_size,
            evidence_ids=(ASF_PICTURE_TABLE_SOURCE, ASF_PICTURE_PROCESS_SOURCE),
        )
    )
    return entries, []


def parse_picture_strings(value: bytes) -> tuple[str | None, str | None]:
    first_end = find_utf16le_terminator(value, 0)
    if first_end is None:
        return None, None
    second_start = first_end + 2
    second_end = find_utf16le_terminator(value, second_start)
    if second_end is None:
        return None, None
    return (
        decode_utf16le(value[:first_end]),
        decode_utf16le(value[second_start:second_end]),
    )


def find_utf16le_terminator(value: bytes, start: int) -> int | None:
    for offset in range(start, len(value) - 1, 2):
        if value[offset : offset + 2] == b"\x00\x00":
            return offset
    return None


def route_metadata_writes(
    existing_entries: tuple[AsfMetadataEntryPlan, ...],
    requests: tuple[AsfMetadataWriteRequest, ...],
) -> tuple[AsfMetadataRoute, ...]:
    routes: list[AsfMetadataRoute] = []
    existing_by_key = {(entry.section, entry.tag_name): entry for entry in existing_entries}
    for request in requests:
        tag_name = normalized_asf_tag_name(request.tag_name)
        existing = existing_by_key.get((request.section, tag_name))
        is_delete = request.value is None
        route_sources = route_sources_for_section(request.section)
        routes.append(
            AsfMetadataRoute(
                action=route_action(request.section, is_delete),
                section=request.section,
                tag_name=tag_name,
                existing_value=existing.value if existing else None,
                requested_value=request.value,
                estimated_size_delta=estimated_route_delta(existing, request),
                evidence_ids=route_sources,
            )
        )
    return tuple(routes)


def estimated_route_delta(
    existing: AsfMetadataEntryPlan | None,
    request: AsfMetadataWriteRequest,
) -> int:
    old_size = existing.value_size if existing else 0
    if request.value is None:
        return -old_size
    new_size = encoded_value_size(request.value, request.value_type)
    structural_overhead = 0 if existing else route_structural_overhead(request)
    return new_size - old_size + structural_overhead


def route_structural_overhead(request: AsfMetadataWriteRequest) -> int:
    name_size = len(normalized_asf_tag_name(request.tag_name).encode("utf-16le"))
    if request.section == "content_description":
        return 0
    if request.section == "extended_content_description":
        return 6 + name_size
    return 12 + name_size


def encoded_value_size(value: AsfMetadataValue, value_type: int) -> int:
    if isinstance(value, bytes):
        return len(value)
    if value_type == 5:
        return 2
    if value_type in {2, 3}:
        return 4
    if value_type == 4:
        return 8
    if isinstance(value, (int, bool)):
        return len(str(value).encode("utf-16le"))
    return len(value.encode("utf-16le"))


def read_asf_value(payload: bytes, pos: int, value_type: int, size: int) -> AsfMetadataValue:
    value = payload[pos : pos + size]
    if value_type == 0:
        return decode_utf16le(value)
    if value_type == 2:
        ints = read_ints(value, 4)
        if not ints:
            return False
        return single_or_joined_value(tuple(bool(number) for number in ints))
    if value_type == 3:
        return single_or_joined_value(read_ints(value, 4))
    if value_type == 4:
        return single_or_joined_value(read_ints(value, 8))
    if value_type == 5:
        return single_or_joined_value(read_ints(value, 2))
    return value


def single_or_joined_value(values: tuple[int | bool, ...]) -> int | bool | str:
    if len(values) == 1:
        return values[0]
    return " ".join(str(value) for value in values)


def read_ints(value: bytes, item_size: int) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(value[index : index + item_size], "little")
        for index in range(0, len(value) - (len(value) % item_size), item_size)
    )


def decode_asf_guid(value: bytes) -> str:
    if len(value) != 16:
        raise ValueError("ASF GUID data must be exactly 16 bytes.")
    return (
        f"{int.from_bytes(value[0:4], 'little'):08X}-"
        f"{int.from_bytes(value[4:6], 'little'):04X}-"
        f"{int.from_bytes(value[6:8], 'little'):04X}-"
        f"{value[8:10].hex().upper()}-"
        f"{value[10:16].hex().upper()}"
    )


def encode_asf_guid(guid: str) -> bytes:
    normalized = guid.upper()
    parts = normalized.split("-")
    if len(parts) != 5:
        raise ValueError(f"Invalid ASF GUID: {guid}")
    return (
        int(parts[0], 16).to_bytes(4, "little")
        + int(parts[1], 16).to_bytes(2, "little")
        + int(parts[2], 16).to_bytes(2, "little")
        + bytes.fromhex(parts[3])
        + bytes.fromhex(parts[4])
    )


def encode_asf_record(guid: str, payload: bytes) -> bytes:
    """Encode an ASF record for synthetic fixtures."""

    return (
        encode_asf_guid(guid)
        + (len(payload) + ASF_RECORD_HEADER_SIZE).to_bytes(8, "little")
        + payload
    )


def decode_utf16le(value: bytes) -> str:
    return value.decode("utf-16le", errors="replace").rstrip("\x00")


def asf_filetime_iso_utc(value: int) -> str:
    seconds = value / 10_000_000 - ASF_FILETIME_UNIX_EPOCH_OFFSET_SECONDS
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y:%m:%d %H:%M:%SZ")


def render_asf_file_property(tag_name: str, value: int) -> str | int:
    if tag_name in {"Duration", "SendDuration"}:
        rendered = convert_duration(value / 10_000_000)
        return str(rendered) if rendered is not None else ""
    if tag_name == "MaxBitrate":
        rendered = convert_bitrate(value)
        return str(rendered) if rendered is not None else ""
    return value


def render_asf_stream_property(tag_name: str, value: int) -> str | int:
    if tag_name == "AudioCodecID":
        return ASF_RIFF_AUDIO_ENCODINGS.get(value, value)
    return value


def render_asf_metadata_value(tag_name: str, value: AsfMetadataValue) -> AsfMetadataValue:
    if tag_name in ASF_GUID_VALUE_TAGS and isinstance(value, bytes) and len(value) == 16:
        return decode_asf_guid(value)
    if isinstance(value, bytes):
        return value
    if tag_name == "Duration" and isinstance(value, (int, str)):
        rendered = convert_duration(value)
        return str(rendered) if rendered is not None else ""
    if tag_name in ASF_BITRATE_TAGS and isinstance(value, (int, str)):
        rendered = convert_bitrate(value)
        return str(rendered) if rendered is not None else ""
    return value


def render_asf_stream_number(value: int) -> str | int:
    suffix = " (encrypted)" if value & 0x8000 else ""
    stream_number = value & 0x7F
    if suffix:
        return f"{stream_number}{suffix}"
    return stream_number


def normalized_asf_tag_name(tag_name: str) -> str:
    return tag_name.removeprefix("WM/").rstrip("\x00")


def known_extended_tag_name(tag_name: str) -> str | None:
    aliased = ASF_EXTENDED_TAG_ALIASES.get(tag_name, tag_name)
    if aliased in ASF_KNOWN_EXTENDED_TAGS:
        return aliased
    return None


def guid_definition(table: AsfTraversalTable, guid: str) -> AsfGuidDefinition:
    definitions = guid_definitions(table)
    found = definitions.get(guid)
    if found:
        return found
    return AsfGuidDefinition(f"Unknown_{guid}", "preserve_unknown", (table_source(table),))


def guid_definitions(table: AsfTraversalTable) -> dict[str, AsfGuidDefinition]:
    if table == "main":
        return MAIN_GUIDS
    if table == "header":
        return HEADER_GUIDS
    return HEADER_EXTENSION_GUIDS


def table_source(table: AsfTraversalTable) -> str:
    if table == "main":
        return ASF_MAIN_TABLE_SOURCE
    if table == "header":
        return ASF_HEADER_TABLE_SOURCE
    return ASF_HEADER_EXTENSION_TABLE_SOURCE


def header_prefix_size_for_action(action: AsfRecordAction) -> int:
    if action == "descend_header":
        return ASF_HEADER_PAYLOAD_PREFIX_SIZE
    if action == "descend_header_extension":
        return ASF_HEADER_EXTENSION_PREFIX_SIZE
    return 0


def route_action(section: AsfMetadataSection, is_delete: bool) -> AsfRouteAction:
    if section == "content_description":
        return "delete_content_description" if is_delete else "upsert_content_description"
    if section == "extended_content_description":
        return (
            "delete_extended_content_description"
            if is_delete
            else "upsert_extended_content_description"
        )
    if section == "metadata":
        return "delete_metadata" if is_delete else "upsert_metadata"
    return "delete_metadata_library" if is_delete else "upsert_metadata_library"


def route_sources_for_section(section: AsfMetadataSection) -> tuple[str, ...]:
    if section == "content_description":
        return (ASF_CONTENT_DESCRIPTION_SOURCE, ASF_CONTENT_DESCRIPTION_PROCESS_SOURCE)
    if section == "extended_content_description":
        return (ASF_EXTENDED_DESCRIPTION_SOURCE, ASF_READ_VALUE_SOURCE)
    if section == "picture":
        return (ASF_PICTURE_TABLE_SOURCE, ASF_PICTURE_PROCESS_SOURCE)
    return (ASF_HEADER_EXTENSION_TABLE_SOURCE, ASF_METADATA_SOURCE, ASF_READ_VALUE_SOURCE)


def stream_property_sources(tag_name: str) -> tuple[str, ...]:
    if tag_name == "AudioCodecID":
        return (ASF_STREAM_PROPERTIES_SOURCE, RIFF_AUDIO_ENCODING_SOURCE)
    return (ASF_STREAM_PROPERTIES_SOURCE,)


def extended_metadata_sources(tag_name: str) -> tuple[str, ...]:
    if tag_name in ASF_BITRATE_TAGS or tag_name == "Duration" or tag_name in ASF_GUID_VALUE_TAGS:
        return (
            ASF_EXTENDED_DESCRIPTION_SOURCE,
            ASF_READ_VALUE_SOURCE,
            ASF_EXTENDED_PRINTCONV_SOURCE,
            ASF_EXTENDED_DESCRIPTOR_TAGS_SOURCE,
        )
    return (
        ASF_EXTENDED_DESCRIPTION_SOURCE,
        ASF_READ_VALUE_SOURCE,
        ASF_EXTENDED_DESCRIPTOR_TAGS_SOURCE,
    )


def metadata_sources(tag_name: str) -> tuple[str, ...]:
    if tag_name in ASF_BITRATE_TAGS or tag_name == "Duration" or tag_name in ASF_GUID_VALUE_TAGS:
        return (
            ASF_METADATA_SOURCE,
            ASF_READ_VALUE_SOURCE,
            ASF_EXTENDED_PRINTCONV_SOURCE,
            ASF_EXTENDED_DESCRIPTOR_TAGS_SOURCE,
        )
    return (ASF_METADATA_SOURCE, ASF_READ_VALUE_SOURCE, ASF_EXTENDED_DESCRIPTOR_TAGS_SOURCE)


def malformed_extended_gate(index: int) -> AsfEmissionGate:
    return AsfEmissionGate(
        "malformed_extended_content_description",
        f"ExtendedContentDescr descriptor {index} extends beyond the payload.",
        True,
        (ASF_EXTENDED_DESCRIPTION_SOURCE,),
    )


def malformed_metadata_gate(record_name: str, index: int) -> AsfEmissionGate:
    return AsfEmissionGate(
        "malformed_metadata",
        f"{record_name} descriptor {index} extends beyond the payload.",
        True,
        (ASF_METADATA_SOURCE,),
    )


def malformed_codec_list_gate(index: int) -> AsfEmissionGate:
    return AsfEmissionGate(
        "malformed_codec_list",
        f"CodecList descriptor {index} extends beyond the payload.",
        True,
        (ASF_CODEC_LIST_PROCESS_SOURCE,),
    )


def malformed_picture_gate(reason: str) -> AsfEmissionGate:
    return AsfEmissionGate(
        "malformed_picture",
        reason,
        True,
        (ASF_PICTURE_PROCESS_SOURCE,),
    )


def unknown_metadata_tag_gate(record_name: str, index: int) -> AsfEmissionGate:
    return AsfEmissionGate(
        "unknown_asf_metadata_tag",
        f"{record_name} descriptor {index} is not defined in ASF.pm ExtendedDescr.",
        False,
        (ASF_EXTENDED_DESCRIPTOR_TAGS_SOURCE,),
    )


def default_responsibilities() -> tuple[AsfTraversalResponsibility, ...]:
    return (
        AsfTraversalResponsibility(
            1,
            "guid_header_validation",
            "Require the first GUID to be the ASF Header GUID and decode GUIDs as ASF.pm does.",
            ("header_validation.guid", "records[].guid"),
            (ASF_GUID_SOURCE, ASF_MAIN_TABLE_SOURCE),
        ),
        AsfTraversalResponsibility(
            2,
            "top_level_and_header_traversal",
            "Walk top-level records, Header children, and HeaderExtension children linearly.",
            ("records[].full_path", "records[].header_prefix_size"),
            (
                ASF_HEADER_TABLE_SOURCE,
                ASF_HEADER_EXTENSION_TABLE_SOURCE,
                ASF_PROCESS_TRAVERSAL_SOURCE,
            ),
        ),
        AsfTraversalResponsibility(
            3,
            "file_and_stream_scalar_routing",
            (
                "Expose fixed FileProperties and StreamProperties scalar fields "
                "from ASF.pm binary tables."
            ),
            ("scalar_entries",),
            (ASF_FILE_PROPERTIES_SOURCE, ASF_STREAM_PROPERTIES_SOURCE),
        ),
        AsfTraversalResponsibility(
            4,
            "metadata_directory_routing",
            (
                "Route ContentDescription, CodecList, ExtendedContentDescr, Metadata, "
                "and MetadataLibrary payloads."
            ),
            ("codec_entries", "metadata_entries", "routes"),
            (
                ASF_CONTENT_DESCRIPTION_PROCESS_SOURCE,
                ASF_CODEC_LIST_PROCESS_SOURCE,
                ASF_EXTENDED_DESCRIPTION_SOURCE,
                ASF_METADATA_SOURCE,
            ),
        ),
        AsfTraversalResponsibility(
            5,
            "large_record_preservation",
            "Preserve very large records instead of planning an in-memory rewrite.",
            ("preserve_large_record",),
            (ASF_LARGE_RECORD_SOURCE,),
        ),
        AsfTraversalResponsibility(
            6,
            "padding_size_growth_blocker",
            "Require available Padding bytes or a future rebuild before growing metadata.",
            ("preserved_padding_bytes", "estimated_size_delta"),
            (ASF_PADDING_SOURCE, ASF_PROCESS_TRAVERSAL_SOURCE),
        ),
        AsfTraversalResponsibility(
            7,
            "output_emission_gate",
            "Keep ASF byte emission disabled until a complete writer owns repair and output.",
            ("can_mutate_bytes", "output_emission_gates"),
            (ASF_PROCESS_TRAVERSAL_SOURCE,),
        ),
    )


def metadata_value_to_json(value: AsfMetadataValue | None) -> JsonValue:
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    return value


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def unique_evidence_ids(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for source in sources:
        if source not in unique:
            unique.append(source)
    return tuple(unique)


def unique_gates(gates: tuple[AsfEmissionGate, ...]) -> tuple[AsfEmissionGate, ...]:
    unique: list[AsfEmissionGate] = []
    seen_codes: set[AsfEmissionGateCode] = set()
    for gate in gates:
        if gate.code not in seen_codes:
            unique.append(gate)
            seen_codes.add(gate.code)
    return tuple(unique)
