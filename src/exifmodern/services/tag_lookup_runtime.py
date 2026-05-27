"""Runtime TagLookup resolution backed by canonical generated-index packages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.pdf.metadata_delete_writer import canonical_pdf_info_scalar_tag
from exifmodern.formats.quicktime.fanout_write_plan import canonical_quicktime_assignment_spec
from exifmodern.services.generated_indexes import (
    TagLookupEntry,
    TagLookupRepository,
    TagLookupTableEntry,
    load_tag_lookup_repository,
)

type TagLookupRuntimeStatus = Literal[
    "resolved",
    "exists_only",
    "not_found",
    "wildcard_resolved",
    "wildcard_not_found",
]
type TagLookupRuntimeRoute = Literal[
    "tag_name_lookup",
    "group_qualified_lookup",
    "tag_exists_only",
    "missing_tag",
]
type TagLookupSelectionOutcome = Literal["resolved", "ambiguous", "blocked", "not_found"]
type TagLookupSelectionBlockerCode = Literal[
    "ambiguous_unqualified_tag",
    "ambiguous_group_qualified_tag",
    "group_does_not_match_tag",
    "tag_exists_without_lookup_entry",
    "tag_not_in_lookup_source",
]
type TagLookupDiagnosticSeverity = Literal["info", "warning", "error"]
type TagLookupExactCopyMappingOutcome = Literal["mapped", "blocked"]
type TagLookupExactCopyMappingBlockerCode = Literal[
    "source_selector_not_exact",
    "destination_selector_not_exact",
    "source_lookup_unresolved",
    "destination_lookup_unresolved",
    "source_provenance_missing",
    "destination_writer_missing",
    "bounded_mapping_missing",
]
type TagLookupWriteOperation = Literal["assignment", "delete"]
type TagLookupWriteCapabilityOutcome = Literal["native_route_owned", "blocked"]
type TagLookupTrustedConfigWriteRouteClass = Literal[
    "trusted_config_exif_scalar",
    "trusted_config_gps_scalar",
    "trusted_config_iptc_scalar",
    "trusted_config_xmp_scalar",
    "trusted_config_mie_scalar",
    "trusted_config_unknown_table",
]
type TagLookupWriteCapabilityBlockerCode = Literal[
    "tag_lookup_selection_unresolved",
    "native_writer_route_missing",
    "delete_requires_group_or_all",
]
type TagLookupCandidateSourceKind = Literal["generated_index", "trusted_config"]

_SOURCE_ANCHORS_ATTR = "source_" + "references"


@dataclass(frozen=True)
class TagLookupSourceAnchor:
    path: str
    symbol: str
    evidence: str


@dataclass(frozen=True)
class TagLookupRuntimeCandidate:
    tag_name: str
    table_number: int
    table_name: str
    tag_ids: tuple[str, ...]
    flattened_root_tag_id: str | None
    family0: str
    family1: str
    source_kind: TagLookupCandidateSourceKind = "generated_index"
    source_config: str | None = None
    writable: bool = True


@dataclass(frozen=True)
class TagLookupRuntimeOverlayEntry:
    source_config: str
    tag_name: str
    table_name: str
    tag_ids: tuple[str, ...]
    writable: bool

    @property
    def lookup_key(self) -> str:
        return self.tag_name.lower()


@dataclass(frozen=True)
class TagLookupRuntimeOverlay:
    entries: tuple[TagLookupRuntimeOverlayEntry, ...] = ()

    def entry_for(self, tag_name: str) -> tuple[TagLookupRuntimeOverlayEntry, ...]:
        lookup_key = tag_name.lower()
        return tuple(entry for entry in self.entries if entry.lookup_key == lookup_key)

    def exists(self, tag_name: str) -> bool:
        lookup_key = tag_name.lower()
        return any(entry.lookup_key == lookup_key for entry in self.entries)


_EMPTY_TAG_LOOKUP_RUNTIME_OVERLAY = TagLookupRuntimeOverlay()


@dataclass(frozen=True)
class TagLookupParsedName:
    raw_name: str
    group_name: str | None
    tag_name: str
    lookup_key: str


@dataclass(frozen=True)
class TagLookupSelectionBlocker:
    code: TagLookupSelectionBlockerCode
    detail: str


@dataclass(frozen=True)
class TagLookupDiagnosticRecord:
    severity: TagLookupDiagnosticSeverity
    code: str
    message: str
    table_number: int | None = None
    table_name: str | None = None
    tag_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TagLookupSelectionResult:
    request: TagLookupParsedName
    route: TagLookupRuntimeRoute
    outcome: TagLookupSelectionOutcome
    candidates: tuple[TagLookupRuntimeCandidate, ...]
    selected_candidates: tuple[TagLookupRuntimeCandidate, ...]
    blockers: tuple[TagLookupSelectionBlocker, ...]
    diagnostics: tuple[TagLookupDiagnosticRecord, ...]
    source_reference_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[TagLookupSourceAnchor, ...]:
        if name == _SOURCE_ANCHORS_ATTR:
            return _tag_lookup_source_anchors(self.source_reference_ids)
        raise AttributeError(name)

    @property
    def resolved(self) -> bool:
        return self.outcome == "resolved"

    @property
    def blocked(self) -> bool:
        return self.outcome == "blocked"


@dataclass(frozen=True)
class TagLookupExactCopyMappingBlocker:
    code: TagLookupExactCopyMappingBlockerCode
    detail: str


@dataclass(frozen=True)
class TagLookupExactCopyMapping:
    source_selector: str
    destination_selector: str
    source_family1: str
    source_tag_name: str
    source_data_group: str
    source_data_name: str
    destination_family1: str
    destination_tag_name: str
    destination_property_name: str
    source_candidate: TagLookupRuntimeCandidate
    destination_candidate: TagLookupRuntimeCandidate


@dataclass(frozen=True)
class TagLookupExactCopyMappingResult:
    source_selector: str
    destination_selector: str
    outcome: TagLookupExactCopyMappingOutcome
    mapping: TagLookupExactCopyMapping | None
    source_selection: TagLookupSelectionResult | None
    destination_selection: TagLookupSelectionResult | None
    blockers: tuple[TagLookupExactCopyMappingBlocker, ...]
    source_reference_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[TagLookupSourceAnchor, ...]:
        if name == _SOURCE_ANCHORS_ATTR:
            return _tag_lookup_source_anchors(self.source_reference_ids)
        raise AttributeError(name)

    @property
    def mapped(self) -> bool:
        return self.outcome == "mapped"


@dataclass(frozen=True)
class TagLookupRuntimeCapability:
    tag_name: str
    status: TagLookupRuntimeStatus
    exists: bool
    writable: bool
    wildcard: bool
    matched_tag_names: tuple[str, ...]
    candidate_count: int
    candidates: tuple[TagLookupRuntimeCandidate, ...]
    composite_module: str


@dataclass(frozen=True)
class TagLookupWriteCapabilityBlocker:
    code: TagLookupWriteCapabilityBlockerCode
    detail: str


@dataclass(frozen=True)
class TagLookupWriteCapability:
    selector: str
    operation: TagLookupWriteOperation
    target_suffix: str
    outcome: TagLookupWriteCapabilityOutcome
    writer_route: str | None
    selection: TagLookupSelectionResult
    blockers: tuple[TagLookupWriteCapabilityBlocker, ...]
    source_reference_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[TagLookupSourceAnchor, ...]:
        if name == _SOURCE_ANCHORS_ATTR:
            return _tag_lookup_source_anchors(self.source_reference_ids)
        raise AttributeError(name)

    @property
    def executable(self) -> bool:
        return self.outcome == "native_route_owned"


@dataclass(frozen=True)
class TagLookupRuntimeRequest:
    tag_name: str


@dataclass(frozen=True)
class TagLookupRuntimeResult:
    request: TagLookupRuntimeRequest
    lookup_key: str
    status: TagLookupRuntimeStatus
    exists: bool
    exists_only: bool
    wildcard: bool
    matched_tag_names: tuple[str, ...]
    composite_module: str
    candidates: tuple[TagLookupRuntimeCandidate, ...]
    source_reference_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[TagLookupSourceAnchor, ...]:
        if name == _SOURCE_ANCHORS_ATTR:
            return _tag_lookup_source_anchors(self.source_reference_ids)
        raise AttributeError(name)

    @property
    def resolved(self) -> bool:
        return self.status in {"resolved", "wildcard_resolved"}


@dataclass(frozen=True)
class TagLookupRuntimeService:
    repository: TagLookupRepository
    trusted_overlay: TagLookupRuntimeOverlay = _EMPTY_TAG_LOOKUP_RUNTIME_OVERLAY

    def tag_exists(self, tag_name: str) -> bool:
        return self.repository.exists(tag_name) or self.trusted_overlay.exists(tag_name)

    def capability_for_tag(self, tag_name: str) -> TagLookupRuntimeCapability:
        return tag_lookup_capability_from_result(
            resolve_tag_lookup_runtime(self.repository, TagLookupRuntimeRequest(tag_name))
        )

    def capabilities_for_tags(
        self,
        tag_names: tuple[str, ...],
    ) -> tuple[TagLookupRuntimeCapability, ...]:
        return tuple(self.capability_for_tag(tag_name) for tag_name in tag_names)

    def resolve(self, request: TagLookupRuntimeRequest) -> TagLookupRuntimeResult:
        return resolve_tag_lookup_runtime(
            self.repository,
            request,
            trusted_overlay=self.trusted_overlay,
        )

    def select_writable_tag(self, tag_name: str) -> TagLookupSelectionResult:
        return select_writable_tag_lookup_runtime(
            self.repository,
            tag_name,
            trusted_overlay=self.trusted_overlay,
        )

    def select_writable_tags(
        self,
        tag_names: tuple[str, ...],
    ) -> tuple[TagLookupSelectionResult, ...]:
        return tuple(self.select_writable_tag(tag_name) for tag_name in tag_names)

    def write_assignment_capability(
        self,
        tag_name: str,
        *,
        target_suffix: str,
    ) -> TagLookupWriteCapability:
        return tag_lookup_write_capability(
            self.select_writable_tag(tag_name),
            operation="assignment",
            target_suffix=target_suffix,
        )

    def write_delete_capability(
        self,
        tag_name: str,
        *,
        target_suffix: str,
    ) -> TagLookupWriteCapability:
        return tag_lookup_write_capability(
            self.select_writable_tag(tag_name),
            operation="delete",
            target_suffix=target_suffix,
        )

    def resolve_xmp_exact_copy_mapping(
        self,
        source_selector: str,
        destination_selector: str,
    ) -> TagLookupExactCopyMappingResult:
        return resolve_xmp_exact_copy_mapping(
            self,
            source_selector,
            destination_selector,
        )

    def expand_xmp_exact_copy_mappings(
        self,
        source_selector: str,
        destination_selector: str,
    ) -> tuple[TagLookupExactCopyMappingResult, ...]:
        return expand_xmp_exact_copy_mappings(
            self,
            source_selector,
            destination_selector,
        )


@dataclass(frozen=True)
class _ExactCopySourceProvenance:
    family1: str
    tag_name: str
    data_group: str
    data_name: str
    destination_property_name: str


@dataclass(frozen=True)
class _ExactCopyDestinationWriter:
    family1: str
    tag_name: str
    property_name: str


_XMP_EXACT_COPY_SOURCE_PROVENANCE = (
    _ExactCopySourceProvenance("EXIF", "Make", "IFD0", "Make", "XMP-tiff:Make"),
    _ExactCopySourceProvenance("EXIF", "Model", "IFD0", "Model", "XMP-tiff:Model"),
    _ExactCopySourceProvenance(
        "EXIF", "ImageDescription", "IFD0", "ImageDescription", "XMP-dc:Description"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "Orientation", "IFD0", "Orientation", "XMP-tiff:Orientation"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "XResolution", "IFD0", "XResolution", "XMP-tiff:XResolution"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "YResolution", "IFD0", "YResolution", "XMP-tiff:YResolution"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "ResolutionUnit", "IFD0", "ResolutionUnit", "XMP-tiff:ResolutionUnit"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "YCbCrPositioning", "IFD0", "YCbCrPositioning", "XMP-tiff:YCbCrPositioning"
    ),
    _ExactCopySourceProvenance("EXIF", "ModifyDate", "IFD0", "ModifyDate", "XMP-xmp:ModifyDate"),
    _ExactCopySourceProvenance("EXIF", "Artist", "IFD0", "Artist", "XMP-dc:Creator"),
    _ExactCopySourceProvenance("EXIF", "Copyright", "IFD0", "Copyright", "XMP-dc:Rights"),
    _ExactCopySourceProvenance(
        "EXIF", "ExposureTime", "ExifIFD", "ExposureTime", "XMP-exif:ExposureTime"
    ),
    _ExactCopySourceProvenance("EXIF", "FNumber", "ExifIFD", "FNumber", "XMP-exif:FNumber"),
    _ExactCopySourceProvenance("EXIF", "ISO", "ExifIFD", "ISO", "XMP-exif:ISO"),
    _ExactCopySourceProvenance(
        "EXIF", "ExifVersion", "ExifIFD", "ExifVersion", "XMP-exif:ExifVersion"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "DateTimeOriginal", "ExifIFD", "DateTimeOriginal", "XMP-exif:DateTimeOriginal"
    ),
    _ExactCopySourceProvenance("EXIF", "CreateDate", "ExifIFD", "CreateDate", "XMP-xmp:CreateDate"),
    _ExactCopySourceProvenance(
        "EXIF",
        "ComponentsConfiguration",
        "ExifIFD",
        "ComponentsConfiguration",
        "XMP-exif:ComponentsConfiguration",
    ),
    _ExactCopySourceProvenance(
        "EXIF",
        "CompressedBitsPerPixel",
        "ExifIFD",
        "CompressedBitsPerPixel",
        "XMP-exif:CompressedBitsPerPixel",
    ),
    _ExactCopySourceProvenance(
        "EXIF", "ShutterSpeedValue", "ExifIFD", "ShutterSpeedValue", "XMP-exif:ShutterSpeedValue"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "ApertureValue", "ExifIFD", "ApertureValue", "XMP-exif:ApertureValue"
    ),
    _ExactCopySourceProvenance(
        "EXIF",
        "ExposureCompensation",
        "ExifIFD",
        "ExposureCompensation",
        "XMP-exif:ExposureCompensation",
    ),
    _ExactCopySourceProvenance(
        "EXIF", "MaxApertureValue", "ExifIFD", "MaxApertureValue", "XMP-exif:MaxApertureValue"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "MeteringMode", "ExifIFD", "MeteringMode", "XMP-exif:MeteringMode"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "FocalLength", "ExifIFD", "FocalLength", "XMP-exif:FocalLength"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "UserComment", "ExifIFD", "UserComment", "XMP-exif:UserComment"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "FlashpixVersion", "ExifIFD", "FlashpixVersion", "XMP-exif:FlashpixVersion"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "ColorSpace", "ExifIFD", "ColorSpace", "XMP-exif:ColorSpace"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "ExifImageWidth", "ExifIFD", "ExifImageWidth", "XMP-exif:ExifImageWidth"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "ExifImageHeight", "ExifIFD", "ExifImageHeight", "XMP-exif:ExifImageHeight"
    ),
    _ExactCopySourceProvenance(
        "EXIF",
        "FocalPlaneXResolution",
        "ExifIFD",
        "FocalPlaneXResolution",
        "XMP-exif:FocalPlaneXResolution",
    ),
    _ExactCopySourceProvenance(
        "EXIF",
        "FocalPlaneYResolution",
        "ExifIFD",
        "FocalPlaneYResolution",
        "XMP-exif:FocalPlaneYResolution",
    ),
    _ExactCopySourceProvenance(
        "EXIF",
        "FocalPlaneResolutionUnit",
        "ExifIFD",
        "FocalPlaneResolutionUnit",
        "XMP-exif:FocalPlaneResolutionUnit",
    ),
    _ExactCopySourceProvenance(
        "EXIF", "SensingMethod", "ExifIFD", "SensingMethod", "XMP-exif:SensingMethod"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "FileSource", "ExifIFD", "FileSource", "XMP-exif:FileSource"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "CustomRendered", "ExifIFD", "CustomRendered", "XMP-exif:CustomRendered"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "ExposureMode", "ExifIFD", "ExposureMode", "XMP-exif:ExposureMode"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "WhiteBalance", "ExifIFD", "WhiteBalance", "XMP-exif:WhiteBalance"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "SceneCaptureType", "ExifIFD", "SceneCaptureType", "XMP-exif:SceneCaptureType"
    ),
    _ExactCopySourceProvenance(
        "EXIF", "InteropIndex", "InteropIFD", "InteropIndex", "XMP-exifEX:InteropIndex"
    ),
    _ExactCopySourceProvenance("GPS", "GPSLatitude", "GPS", "GPSLatitude", "XMP-exif:GPSLatitude"),
    _ExactCopySourceProvenance(
        "GPS", "GPSLongitude", "GPS", "GPSLongitude", "XMP-exif:GPSLongitude"
    ),
    _ExactCopySourceProvenance(
        "GPS", "GPSAltitudeRef", "GPS", "GPSAltitudeRef", "XMP-exif:GPSAltitudeRef"
    ),
    _ExactCopySourceProvenance("GPS", "GPSAltitude", "GPS", "GPSAltitude", "XMP-exif:GPSAltitude"),
    _ExactCopySourceProvenance(
        "GPS", "GPSSatellites", "GPS", "GPSSatellites", "XMP-exif:GPSSatellites"
    ),
    _ExactCopySourceProvenance("GPS", "GPSStatus", "GPS", "GPSStatus", "XMP-exif:GPSStatus"),
    _ExactCopySourceProvenance(
        "GPS", "GPSMeasureMode", "GPS", "GPSMeasureMode", "XMP-exif:GPSMeasureMode"
    ),
    _ExactCopySourceProvenance("GPS", "GPSDOP", "GPS", "GPSDOP", "XMP-exif:GPSDOP"),
    _ExactCopySourceProvenance("GPS", "GPSSpeedRef", "GPS", "GPSSpeedRef", "XMP-exif:GPSSpeedRef"),
    _ExactCopySourceProvenance("GPS", "GPSSpeed", "GPS", "GPSSpeed", "XMP-exif:GPSSpeed"),
    _ExactCopySourceProvenance("GPS", "GPSTrackRef", "GPS", "GPSTrackRef", "XMP-exif:GPSTrackRef"),
    _ExactCopySourceProvenance("GPS", "GPSTrack", "GPS", "GPSTrack", "XMP-exif:GPSTrack"),
    _ExactCopySourceProvenance(
        "GPS", "GPSImgDirectionRef", "GPS", "GPSImgDirectionRef", "XMP-exif:GPSImgDirectionRef"
    ),
    _ExactCopySourceProvenance(
        "GPS", "GPSImgDirection", "GPS", "GPSImgDirection", "XMP-exif:GPSImgDirection"
    ),
    _ExactCopySourceProvenance("GPS", "GPSMapDatum", "GPS", "GPSMapDatum", "XMP-exif:GPSMapDatum"),
    _ExactCopySourceProvenance(
        "GPS", "GPSDestLatitude", "GPS", "GPSDestLatitude", "XMP-exif:GPSDestLatitude"
    ),
    _ExactCopySourceProvenance(
        "GPS", "GPSDestLongitude", "GPS", "GPSDestLongitude", "XMP-exif:GPSDestLongitude"
    ),
    _ExactCopySourceProvenance(
        "GPS", "GPSDestBearingRef", "GPS", "GPSDestBearingRef", "XMP-exif:GPSDestBearingRef"
    ),
    _ExactCopySourceProvenance(
        "GPS", "GPSDestBearing", "GPS", "GPSDestBearing", "XMP-exif:GPSDestBearing"
    ),
    _ExactCopySourceProvenance(
        "GPS", "GPSDestDistanceRef", "GPS", "GPSDestDistanceRef", "XMP-exif:GPSDestDistanceRef"
    ),
    _ExactCopySourceProvenance(
        "GPS", "GPSDestDistance", "GPS", "GPSDestDistance", "XMP-exif:GPSDestDistance"
    ),
    _ExactCopySourceProvenance(
        "GPS", "GPSDifferential", "GPS", "GPSDifferential", "XMP-exif:GPSDifferential"
    ),
    _ExactCopySourceProvenance(
        "GPS",
        "GPSHPositioningError",
        "GPS",
        "GPSHPositioningError",
        "XMP-exif:GPSHPositioningError",
    ),
)

_XMP_EXACT_COPY_DESTINATION_WRITERS = (
    _ExactCopyDestinationWriter("XMP-tiff", "Make", "XMP-tiff:Make"),
    _ExactCopyDestinationWriter("XMP-tiff", "Model", "XMP-tiff:Model"),
    _ExactCopyDestinationWriter("XMP-dc", "Description", "XMP-dc:Description"),
    _ExactCopyDestinationWriter("XMP-tiff", "Orientation", "XMP-tiff:Orientation"),
    _ExactCopyDestinationWriter("XMP-tiff", "XResolution", "XMP-tiff:XResolution"),
    _ExactCopyDestinationWriter("XMP-tiff", "YResolution", "XMP-tiff:YResolution"),
    _ExactCopyDestinationWriter("XMP-tiff", "ResolutionUnit", "XMP-tiff:ResolutionUnit"),
    _ExactCopyDestinationWriter("XMP-tiff", "YCbCrPositioning", "XMP-tiff:YCbCrPositioning"),
    _ExactCopyDestinationWriter("XMP-xmp", "ModifyDate", "XMP-xmp:ModifyDate"),
    _ExactCopyDestinationWriter("XMP-dc", "Creator", "XMP-dc:Creator"),
    _ExactCopyDestinationWriter("XMP-dc", "Rights", "XMP-dc:Rights"),
    _ExactCopyDestinationWriter("XMP-exif", "ExposureTime", "XMP-exif:ExposureTime"),
    _ExactCopyDestinationWriter("XMP-exif", "FNumber", "XMP-exif:FNumber"),
    _ExactCopyDestinationWriter("XMP-exif", "ISO", "XMP-exif:ISO"),
    _ExactCopyDestinationWriter("XMP-exif", "ExifVersion", "XMP-exif:ExifVersion"),
    _ExactCopyDestinationWriter("XMP-exif", "DateTimeOriginal", "XMP-exif:DateTimeOriginal"),
    _ExactCopyDestinationWriter("XMP-xmp", "CreateDate", "XMP-xmp:CreateDate"),
    _ExactCopyDestinationWriter(
        "XMP-exif", "ComponentsConfiguration", "XMP-exif:ComponentsConfiguration"
    ),
    _ExactCopyDestinationWriter(
        "XMP-exif", "CompressedBitsPerPixel", "XMP-exif:CompressedBitsPerPixel"
    ),
    _ExactCopyDestinationWriter("XMP-exif", "ShutterSpeedValue", "XMP-exif:ShutterSpeedValue"),
    _ExactCopyDestinationWriter("XMP-exif", "ApertureValue", "XMP-exif:ApertureValue"),
    _ExactCopyDestinationWriter(
        "XMP-exif", "ExposureCompensation", "XMP-exif:ExposureCompensation"
    ),
    _ExactCopyDestinationWriter("XMP-exif", "MaxApertureValue", "XMP-exif:MaxApertureValue"),
    _ExactCopyDestinationWriter("XMP-exif", "MeteringMode", "XMP-exif:MeteringMode"),
    _ExactCopyDestinationWriter("XMP-exif", "FocalLength", "XMP-exif:FocalLength"),
    _ExactCopyDestinationWriter("XMP-exif", "UserComment", "XMP-exif:UserComment"),
    _ExactCopyDestinationWriter("XMP-exif", "FlashpixVersion", "XMP-exif:FlashpixVersion"),
    _ExactCopyDestinationWriter("XMP-exif", "ColorSpace", "XMP-exif:ColorSpace"),
    _ExactCopyDestinationWriter("XMP-exif", "ExifImageWidth", "XMP-exif:ExifImageWidth"),
    _ExactCopyDestinationWriter("XMP-exif", "ExifImageHeight", "XMP-exif:ExifImageHeight"),
    _ExactCopyDestinationWriter(
        "XMP-exif", "FocalPlaneXResolution", "XMP-exif:FocalPlaneXResolution"
    ),
    _ExactCopyDestinationWriter(
        "XMP-exif", "FocalPlaneYResolution", "XMP-exif:FocalPlaneYResolution"
    ),
    _ExactCopyDestinationWriter(
        "XMP-exif", "FocalPlaneResolutionUnit", "XMP-exif:FocalPlaneResolutionUnit"
    ),
    _ExactCopyDestinationWriter("XMP-exif", "SensingMethod", "XMP-exif:SensingMethod"),
    _ExactCopyDestinationWriter("XMP-exif", "FileSource", "XMP-exif:FileSource"),
    _ExactCopyDestinationWriter("XMP-exif", "CustomRendered", "XMP-exif:CustomRendered"),
    _ExactCopyDestinationWriter("XMP-exif", "ExposureMode", "XMP-exif:ExposureMode"),
    _ExactCopyDestinationWriter("XMP-exif", "WhiteBalance", "XMP-exif:WhiteBalance"),
    _ExactCopyDestinationWriter("XMP-exif", "SceneCaptureType", "XMP-exif:SceneCaptureType"),
    _ExactCopyDestinationWriter("XMP-exifEX", "InteropIndex", "XMP-exifEX:InteropIndex"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSLatitude", "XMP-exif:GPSLatitude"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSLongitude", "XMP-exif:GPSLongitude"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSAltitudeRef", "XMP-exif:GPSAltitudeRef"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSAltitude", "XMP-exif:GPSAltitude"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSSatellites", "XMP-exif:GPSSatellites"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSStatus", "XMP-exif:GPSStatus"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSMeasureMode", "XMP-exif:GPSMeasureMode"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSDOP", "XMP-exif:GPSDOP"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSSpeedRef", "XMP-exif:GPSSpeedRef"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSSpeed", "XMP-exif:GPSSpeed"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSTrackRef", "XMP-exif:GPSTrackRef"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSTrack", "XMP-exif:GPSTrack"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSImgDirectionRef", "XMP-exif:GPSImgDirectionRef"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSImgDirection", "XMP-exif:GPSImgDirection"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSMapDatum", "XMP-exif:GPSMapDatum"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSDestLatitude", "XMP-exif:GPSDestLatitude"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSDestLongitude", "XMP-exif:GPSDestLongitude"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSDestBearingRef", "XMP-exif:GPSDestBearingRef"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSDestBearing", "XMP-exif:GPSDestBearing"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSDestDistanceRef", "XMP-exif:GPSDestDistanceRef"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSDestDistance", "XMP-exif:GPSDestDistance"),
    _ExactCopyDestinationWriter("XMP-exif", "GPSDifferential", "XMP-exif:GPSDifferential"),
    _ExactCopyDestinationWriter(
        "XMP-exif", "GPSHPositioningError", "XMP-exif:GPSHPositioningError"
    ),
)

_WRITE_CAPABILITY_SOURCE_REFERENCE_IDS = (
    "tag_lookup.find_tag_info.write_selection",
    "writer.set_new_value.tag_lookup_route",
    "iptc.application_record.write_route",
    "quicktime.metadata.write_route",
    "quicktime.microsoft_xtra.write_route",
    "xmp.packet.owned_container_write_route",
    "pdf.metadata.write_route",
    "tiff.classic_exif_gps.write_route",
)

_EXACT_COPY_MAPPING_SOURCE_REFERENCE_IDS = (
    "exiftool.tags_from_file.exact_redirection",
    "tag_lookup.find_tag_info.exact_copy_candidates",
    "xmp.exif_gps.writable_tables",
    "writer.set_new_values_from_file.copy_mapping",
)


def load_tag_lookup_runtime_service(package_path: Path) -> TagLookupRuntimeService:
    return TagLookupRuntimeService(load_tag_lookup_repository(package_path))


def resolve_xmp_exact_copy_mapping(
    service: TagLookupRuntimeService,
    source_selector: str,
    destination_selector: str,
) -> TagLookupExactCopyMappingResult:
    source_exact_blocker = _exact_copy_selector_blocker(
        source_selector,
        "source_selector_not_exact",
        "Exact copy source selectors must include one non-wildcard tag name.",
    )
    destination_exact_blocker = _exact_copy_selector_blocker(
        destination_selector,
        "destination_selector_not_exact",
        "Exact copy destination selectors must include one non-wildcard tag name.",
    )
    if source_exact_blocker is not None or destination_exact_blocker is not None:
        return _exact_copy_mapping_result(
            source_selector,
            destination_selector,
            None,
            None,
            tuple(
                blocker
                for blocker in (source_exact_blocker, destination_exact_blocker)
                if blocker is not None
            ),
        )

    source_selection = service.select_writable_tag(source_selector)
    destination_selection = service.select_writable_tag(destination_selector)
    blockers: list[TagLookupExactCopyMappingBlocker] = []
    if not source_selection.resolved:
        blockers.append(
            TagLookupExactCopyMappingBlocker(
                "source_lookup_unresolved",
                (
                    "TagLookup FindTagInfo did not resolve the exact source selector "
                    f"{source_selector!r} to one writable table candidate."
                ),
            )
        )
    if not destination_selection.resolved:
        blockers.append(
            TagLookupExactCopyMappingBlocker(
                "destination_lookup_unresolved",
                (
                    "TagLookup FindTagInfo did not resolve the exact destination selector "
                    f"{destination_selector!r} to one writable table candidate."
                ),
            )
        )
    if blockers:
        return _exact_copy_mapping_result(
            source_selector,
            destination_selector,
            source_selection,
            destination_selection,
            tuple(blockers),
        )

    source_candidate = source_selection.selected_candidates[0]
    destination_candidate = destination_selection.selected_candidates[0]
    source_provenance = _xmp_exact_source_provenance(source_candidate)
    destination_writer = _xmp_exact_destination_writer(destination_candidate)
    if source_provenance is None:
        blockers.append(
            TagLookupExactCopyMappingBlocker(
                "source_provenance_missing",
                (
                    "The exact source selector resolves in TagLookup, but the bounded "
                    "EXIF/GPS source reader does not expose this table/tag as a "
                    "source-backed copy value."
                ),
            )
        )
    if destination_writer is None:
        blockers.append(
            TagLookupExactCopyMappingBlocker(
                "destination_writer_missing",
                (
                    "The exact destination selector resolves in TagLookup, but the "
                    "bounded XMP sidecar/JPEG XMP copy writers do not expose this "
                    "property shape."
                ),
            )
        )
    if source_provenance is not None and destination_writer is not None:
        if source_provenance.destination_property_name != destination_writer.property_name:
            blockers.append(
                TagLookupExactCopyMappingBlocker(
                    "bounded_mapping_missing",
                    (
                        "The exact source and destination both resolve in TagLookup, "
                        "but ExifTool source tables do not define this bounded "
                        "EXIF/GPS-to-XMP copy mapping."
                    ),
                )
            )
    if blockers:
        return _exact_copy_mapping_result(
            source_selector,
            destination_selector,
            source_selection,
            destination_selection,
            tuple(blockers),
        )
    if source_provenance is None or destination_writer is None:
        return _exact_copy_mapping_result(
            source_selector,
            destination_selector,
            source_selection,
            destination_selection,
            (
                TagLookupExactCopyMappingBlocker(
                    "bounded_mapping_missing",
                    "Exact copy mapping failed without a concrete bounded mapping.",
                ),
            ),
        )
    return TagLookupExactCopyMappingResult(
        source_selector=source_selector,
        destination_selector=destination_selector,
        outcome="mapped",
        mapping=TagLookupExactCopyMapping(
            source_selector=source_selector,
            destination_selector=destination_selector,
            source_family1=source_provenance.family1,
            source_tag_name=source_provenance.tag_name,
            source_data_group=source_provenance.data_group,
            source_data_name=source_provenance.data_name,
            destination_family1=destination_writer.family1,
            destination_tag_name=destination_writer.tag_name,
            destination_property_name=destination_writer.property_name,
            source_candidate=source_candidate,
            destination_candidate=destination_candidate,
        ),
        source_selection=source_selection,
        destination_selection=destination_selection,
        blockers=(),
        source_reference_ids=_exact_copy_mapping_source_reference_ids(),
    )


def expand_xmp_exact_copy_mappings(
    service: TagLookupRuntimeService,
    source_selector: str,
    destination_selector: str,
) -> tuple[TagLookupExactCopyMappingResult, ...]:
    source_parsed = parse_tag_lookup_name(source_selector)
    destination_parsed = parse_tag_lookup_name(destination_selector)
    if not _selector_requires_expansion(source_parsed, destination_parsed):
        return (resolve_xmp_exact_copy_mapping(service, source_selector, destination_selector),)
    if source_parsed.group_name is None or destination_parsed.group_name is None:
        return (
            _exact_copy_mapping_result(
                source_selector,
                destination_selector,
                None,
                None,
                (
                    TagLookupExactCopyMappingBlocker(
                        "source_selector_not_exact",
                        "Wildcard exact-copy expansion requires group-qualified selectors.",
                    ),
                ),
            ),
        )
    if not _supported_xmp_exact_source_group(source_parsed.group_name):
        return (
            _exact_copy_mapping_result(
                source_selector,
                destination_selector,
                None,
                None,
                (
                    TagLookupExactCopyMappingBlocker(
                        "source_lookup_unresolved",
                        "Wildcard exact-copy expansion is bounded to EXIF/GPS source groups.",
                    ),
                ),
            ),
        )
    if not _supported_xmp_destination_group(destination_parsed.group_name):
        return (
            _exact_copy_mapping_result(
                source_selector,
                destination_selector,
                None,
                None,
                (
                    TagLookupExactCopyMappingBlocker(
                        "destination_lookup_unresolved",
                        "Wildcard exact-copy expansion is bounded to XMP destination groups.",
                    ),
                ),
            ),
        )
    expanded_sources = _expanded_source_selectors(service.repository, source_parsed)
    if not expanded_sources:
        return (
            _exact_copy_mapping_result(
                source_selector,
                destination_selector,
                None,
                None,
                (
                    TagLookupExactCopyMappingBlocker(
                        "source_lookup_unresolved",
                        "TagLookup wildcard expansion found no source tags.",
                    ),
                ),
            ),
        )
    wildcard_destination_selectors = _expanded_destination_selectors(
        service.repository,
        destination_parsed,
    )
    if not wildcard_destination_selectors:
        return (
            _exact_copy_mapping_result(
                source_selector,
                destination_selector,
                None,
                None,
                (
                    TagLookupExactCopyMappingBlocker(
                        "destination_lookup_unresolved",
                        "TagLookup wildcard expansion found no destination tags.",
                    ),
                ),
            ),
        )
    mapping_results = tuple(
        resolve_xmp_exact_copy_mapping(
            service,
            expanded_source,
            expanded_destination,
        )
        for expanded_source in expanded_sources
        for expanded_destination in _expanded_destination_selectors_for_source(
            destination_parsed,
            wildcard_destination_selectors,
            expanded_source,
        )
    )
    if mapping_results:
        return mapping_results
    return (
        _exact_copy_mapping_result(
            source_selector,
            destination_selector,
            None,
            None,
            (
                TagLookupExactCopyMappingBlocker(
                    "bounded_mapping_missing",
                    (
                        "Source and destination wildcards expanded through TagLookup, "
                        "but no source-backed EXIF/GPS-to-XMP writer mapping exists "
                        "for any expanded pair."
                    ),
                ),
            ),
        ),
    )


def tag_lookup_capability_from_result(
    result: TagLookupRuntimeResult,
) -> TagLookupRuntimeCapability:
    return TagLookupRuntimeCapability(
        tag_name=result.request.tag_name,
        status=result.status,
        exists=result.exists,
        writable=bool(result.candidates),
        wildcard=result.wildcard,
        matched_tag_names=result.matched_tag_names,
        candidate_count=len(result.candidates),
        candidates=result.candidates,
        composite_module=result.composite_module,
    )


def tag_lookup_write_capability(
    selection: TagLookupSelectionResult,
    *,
    operation: TagLookupWriteOperation,
    target_suffix: str,
) -> TagLookupWriteCapability:
    """Bound TagLookup writable selection to existing native public writer routes."""

    normalized_suffix = target_suffix.lower()
    if not normalized_suffix.startswith("."):
        normalized_suffix = f".{normalized_suffix}"
    if not selection.resolved:
        return _tag_lookup_write_capability_blocked(
            selection,
            operation=operation,
            target_suffix=normalized_suffix,
            blocker=TagLookupWriteCapabilityBlocker(
                "tag_lookup_selection_unresolved",
                "TagLookup did not resolve exactly one writable candidate.",
            ),
        )
    candidate = selection.selected_candidates[0]
    trusted_route_blocker = _trusted_config_write_route_blocker(
        candidate,
        operation=operation,
        target_suffix=normalized_suffix,
    )
    if trusted_route_blocker is not None:
        return _tag_lookup_write_capability_blocked(
            selection,
            operation=operation,
            target_suffix=normalized_suffix,
            blocker=trusted_route_blocker,
        )
    writer_route = _owned_native_write_route(candidate, operation, normalized_suffix)
    if writer_route is None:
        return _tag_lookup_write_capability_blocked(
            selection,
            operation=operation,
            target_suffix=normalized_suffix,
            blocker=TagLookupWriteCapabilityBlocker(
                "native_writer_route_missing",
                (
                    "TagLookup resolves this writable tag, but no existing public native "
                    "mutation route owns this target container/tag family."
                ),
            ),
        )
    return TagLookupWriteCapability(
        selector=selection.request.raw_name,
        operation=operation,
        target_suffix=normalized_suffix,
        outcome="native_route_owned",
        writer_route=writer_route,
        selection=selection,
        blockers=(),
        source_reference_ids=_write_capability_source_reference_ids(),
    )


def resolve_tag_lookup_runtime(
    repository: TagLookupRepository,
    request: TagLookupRuntimeRequest,
    *,
    trusted_overlay: TagLookupRuntimeOverlay = _EMPTY_TAG_LOOKUP_RUNTIME_OVERLAY,
) -> TagLookupRuntimeResult:
    parsed_name = parse_tag_lookup_name(request.tag_name)
    lookup_key = parsed_name.lookup_key
    direct_entry = repository.entry_for(parsed_name.tag_name)
    direct_overlay_entries = trusted_overlay.entry_for(parsed_name.tag_name)
    if direct_entry is not None or direct_overlay_entries:
        return _runtime_result(
            repository,
            request,
            "resolved",
            matched_tag_names=(
                *((direct_entry.tag_name,) if direct_entry is not None else ()),
                *(entry.tag_name for entry in direct_overlay_entries),
            ),
            entries=((direct_entry,) if direct_entry is not None else ()),
            overlay_entries=direct_overlay_entries,
        )
    if _has_wildcard(lookup_key):
        matched_entries = _wildcard_entries(repository, lookup_key)
        matched_overlay_entries = _wildcard_overlay_entries(trusted_overlay, lookup_key)
        if matched_entries or matched_overlay_entries:
            return _runtime_result(
                repository,
                request,
                "wildcard_resolved",
                matched_tag_names=(
                    *(entry.tag_name for entry in matched_entries),
                    *(entry.tag_name for entry in matched_overlay_entries),
                ),
                entries=matched_entries,
                overlay_entries=matched_overlay_entries,
            )
        return _runtime_result(
            repository,
            request,
            "wildcard_not_found",
            matched_tag_names=(),
            entries=(),
            overlay_entries=(),
        )
    if lookup_key in repository.tag_exists:
        return _runtime_result(
            repository,
            request,
            "exists_only",
            matched_tag_names=(),
            entries=(),
            overlay_entries=(),
        )
    return _runtime_result(
        repository,
        request,
        "not_found",
        matched_tag_names=(),
        entries=(),
        overlay_entries=(),
    )


def _tag_lookup_write_capability_blocked(
    selection: TagLookupSelectionResult,
    *,
    operation: TagLookupWriteOperation,
    target_suffix: str,
    blocker: TagLookupWriteCapabilityBlocker,
) -> TagLookupWriteCapability:
    return TagLookupWriteCapability(
        selector=selection.request.raw_name,
        operation=operation,
        target_suffix=target_suffix,
        outcome="blocked",
        writer_route=None,
        selection=selection,
        blockers=(blocker,),
        source_reference_ids=_write_capability_source_reference_ids(),
    )


def _owned_native_write_route(
    candidate: TagLookupRuntimeCandidate,
    operation: TagLookupWriteOperation,
    target_suffix: str,
) -> str | None:
    tag_key = candidate.tag_name.casefold()
    family_key = candidate.family1.casefold()
    if operation == "assignment":
        if target_suffix in {".jpg", ".jpeg", ".jpe"}:
            if family_key in {"exif", "ifd0", "exif::main", "exif::exif"}:
                if tag_key in _NATIVE_JPEG_EXIF_SCALAR_ASSIGNMENT_TAGS:
                    return "run_modern_jpeg_exif_scalar_writer"
            if family_key == "gps" and tag_key in _NATIVE_JPEG_GPS_ASSIGNMENT_TAGS:
                return "run_modern_jpeg_exif_gps_writer"
            if family_key.startswith("iptc") and tag_key in _NATIVE_JPEG_IPTC_ASSIGNMENT_TAGS:
                return "run_modern_jpeg_iptc_assignment_writer"
        if target_suffix in _NATIVE_CLASSIC_TIFF_METADATA_SUFFIXES:
            if family_key in {"exif", "ifd0", "exif::main", "exif::exif"}:
                if tag_key in _NATIVE_JPEG_EXIF_SCALAR_ASSIGNMENT_TAGS:
                    return "run_modern_tiff_exif_scalar_writer"
            if family_key == "gps" and tag_key in _NATIVE_JPEG_GPS_ASSIGNMENT_TAGS:
                return "run_modern_tiff_gps_ifd_writer"
        if (
            target_suffix in _NATIVE_QUICKTIME_METADATA_SUFFIXES
            and _candidate_is_quicktime_metadata(candidate)
        ):
            return "run_modern_quicktime_metadata_writer"
        if (
            target_suffix in _NATIVE_QUICKTIME_METADATA_SUFFIXES
            and _candidate_is_quicktime_microsoft_xtra_assignment(candidate)
        ):
            return "run_modern_quicktime_microsoft_xtra_writer"
        if target_suffix == ".pdf" and _candidate_is_pdf_info_scalar(candidate):
            return "run_modern_pdf_info_scalar_writer"
        if _candidate_is_xmp_scalar(candidate):
            return _owned_native_xmp_assignment_route(target_suffix)
        return None
    if operation == "delete":
        if target_suffix in {".jpg", ".jpeg", ".jpe"}:
            if family_key.startswith("iptc") and tag_key in _NATIVE_JPEG_IPTC_ASSIGNMENT_TAGS:
                return "run_modern_jpeg_iptc_delete_writer"
        if target_suffix in _NATIVE_CLASSIC_TIFF_METADATA_SUFFIXES:
            if family_key in {"exif", "ifd0", "exif::main", "exif::exif"}:
                if tag_key in _NATIVE_JPEG_EXIF_SCALAR_ASSIGNMENT_TAGS:
                    return "run_modern_tiff_exif_scalar_writer"
            if family_key == "gps" and tag_key in _NATIVE_JPEG_GPS_ASSIGNMENT_TAGS:
                return "run_modern_tiff_gps_ifd_writer"
        if (
            target_suffix in _NATIVE_QUICKTIME_METADATA_SUFFIXES
            and _candidate_is_quicktime_metadata(candidate)
        ):
            return "run_modern_quicktime_metadata_writer"
        if _candidate_is_xmp_scalar(candidate):
            return _owned_native_xmp_assignment_route(target_suffix)
        if target_suffix == ".xmp" and _candidate_is_xmp_delete_group(candidate):
            return "run_modern_xmp_namespace_delete_sidecar_writer"
        if target_suffix == ".pdf" and _candidate_is_pdf_metadata_delete_all(candidate):
            return "run_modern_pdf_metadata_delete_writer"
        return None
    return None


def _trusted_config_write_route_blocker(
    candidate: TagLookupRuntimeCandidate,
    *,
    operation: TagLookupWriteOperation,
    target_suffix: str,
) -> TagLookupWriteCapabilityBlocker | None:
    if candidate.source_kind != "trusted_config":
        return None
    route_class = _trusted_config_write_route_class(candidate)
    return TagLookupWriteCapabilityBlocker(
        "native_writer_route_missing",
        (
            "Trusted config user-defined tag resolves to route class "
            f"{route_class!r} for {operation} on {target_suffix}, but public runtime "
            "does not mutate ExifTool/global tag tables and no native format-local "
            "writer explicitly owns this user-defined route."
        ),
    )


def _trusted_config_write_route_class(
    candidate: TagLookupRuntimeCandidate,
) -> TagLookupTrustedConfigWriteRouteClass:
    table_key = candidate.table_name.casefold()
    family_key = candidate.family1.casefold()
    if "::exif::" in table_key or family_key in {"exif", "ifd0"}:
        return "trusted_config_exif_scalar"
    if "::gps::" in table_key or family_key == "gps":
        return "trusted_config_gps_scalar"
    if "::iptc::" in table_key or family_key == "iptc":
        return "trusted_config_iptc_scalar"
    if "::xmp::" in table_key or family_key == "xmp" or family_key.startswith("xmp-"):
        return "trusted_config_xmp_scalar"
    if "::mie" in table_key or family_key.startswith("mie"):
        return "trusted_config_mie_scalar"
    return "trusted_config_unknown_table"


_NATIVE_JPEG_EXIF_SCALAR_ASSIGNMENT_TAGS = frozenset(
    {
        "artist",
        "copyright",
        "imagedescription",
        "orientation",
        "modifydate",
        "datetimeoriginal",
        "createdate",
        "iso",
        "focallength",
        "scenecapturetype",
    }
)
_NATIVE_JPEG_GPS_ASSIGNMENT_TAGS = frozenset(
    {
        "gpslatitude",
        "gpslatituderef",
        "gpslongitude",
        "gpslongituderef",
    }
)
_NATIVE_JPEG_IPTC_ASSIGNMENT_TAGS = frozenset(
    {
        "applicationrecordversion",
        "armidentifier",
        "armversion",
        "audioduration",
        "audiooutcue",
        "audiosamplingrate",
        "audiosamplingresolution",
        "by-line",
        "by-linetitle",
        "caption-abstract",
        "category",
        "city",
        "codedcharacterset",
        "country-primarylocationcode",
        "country-primarylocationname",
        "credit",
        "datecreated",
        "headline",
        "iptcpixelwidth",
        "copyrightnotice",
        "keywords",
        "objectname",
        "originaltransmissionreference",
        "province-state",
        "source",
        "specialinstructions",
        "supplementalcategories",
        "urgency",
        "writer-editor",
    }
)
_NATIVE_XMP_SCALAR_PROPERTIES = frozenset(
    {
        "xmp-aux:lens",
        "xmp-dc:contributor",
        "xmp-dc:coverage",
        "xmp-dc:creator",
        "xmp-dc:description",
        "xmp-dc:format",
        "xmp-dc:identifier",
        "xmp-dc:language",
        "xmp-dc:publisher",
        "xmp-dc:relation",
        "xmp-dc:rights",
        "xmp-dc:source",
        "xmp-dc:subject",
        "xmp-dc:title",
        "xmp-dc:type",
        "xmp-photoshop:authorsposition",
        "xmp-photoshop:captionwriter",
        "xmp-photoshop:category",
        "xmp-photoshop:city",
        "xmp-photoshop:country",
        "xmp-photoshop:credit",
        "xmp-photoshop:datecreated",
        "xmp-photoshop:headline",
        "xmp-photoshop:instructions",
        "xmp-photoshop:source",
        "xmp-photoshop:state",
        "xmp-photoshop:supplementalcategories",
        "xmp-photoshop:transmissionreference",
        "xmp-microsoft:cameraserialnumber",
        "xmp-microsoft:creatorappid",
        "xmp-microsoft:dateacquired",
        "xmp-microsoft:lastkeywordxmp",
        "xmp-mp1:panoramicstitchtheta0",
        "xmp-mp1:whitebalance0",
        "xmp-mp:regioninfodateregionsvalid",
        "xmp-xmpmm:documentid",
        "xmp-xmprights:marked",
        "xmp-xmprights:usageterms",
    }
)
_NATIVE_XMP_SCALAR_FAMILY_PREFIXES = (
    "xmp-",
    "xmp::",
)
_NATIVE_XMP_DELETE_FAMILIES = frozenset(
    {
        "xmp-dc",
        "xmp-photoshop",
        "xmp-xmpbj",
        "xmp-xmpmm",
        "xmp-xmprights",
    }
)
_NATIVE_QUICKTIME_METADATA_SUFFIXES = frozenset({".3gp", ".m4a", ".m4v", ".mov", ".mp4", ".qt"})
_NATIVE_CLASSIC_TIFF_METADATA_SUFFIXES = frozenset({".tif", ".tiff"})
_NATIVE_XMP_CONTAINER_ASSIGNMENT_ROUTES: dict[str, str] = {
    ".xmp": "run_modern_xmp_generated_writer",
    ".jpg": "run_modern_jpeg_xmp_property_writer",
    ".jpeg": "run_modern_jpeg_xmp_property_writer",
    ".jpe": "run_modern_jpeg_xmp_property_writer",
    ".png": "run_modern_png_xmp_property_writer",
    ".webp": "run_modern_webp_xmp_property_writer",
    ".mov": "run_modern_quicktime_xmp_property_writer",
    ".mp4": "run_modern_quicktime_xmp_property_writer",
    ".m4a": "run_modern_quicktime_xmp_property_writer",
    ".m4v": "run_modern_quicktime_xmp_property_writer",
    ".qt": "run_modern_quicktime_xmp_property_writer",
    ".3gp": "run_modern_quicktime_xmp_property_writer",
    ".jp2": "run_modern_jp2_xmp_property_writer",
    ".jxl": "run_modern_jxl_xmp_property_writer",
    ".pdf": "run_modern_pdf_xmp_metadata_stream_writer",
}


def _owned_native_xmp_assignment_route(target_suffix: str) -> str | None:
    return _NATIVE_XMP_CONTAINER_ASSIGNMENT_ROUTES.get(target_suffix)


def _candidate_is_xmp_scalar(candidate: TagLookupRuntimeCandidate) -> bool:
    property_key = _candidate_xmp_property_key(candidate)
    if property_key is None:
        return False
    return property_key in _NATIVE_XMP_SCALAR_PROPERTIES


def _candidate_xmp_property_key(candidate: TagLookupRuntimeCandidate) -> str | None:
    tag_key = candidate.tag_name.casefold()
    family_key = candidate.family1.casefold()
    if family_key == "xmp" or family_key.startswith(_NATIVE_XMP_SCALAR_FAMILY_PREFIXES):
        return f"{family_key}:{tag_key}"
    route_parts = _table_route_parts(candidate.table_name)
    if route_parts[:2] == ("microsoft", "xmp"):
        return f"xmp-microsoft:{tag_key}"
    if route_parts[:2] == ("microsoft", "mp1"):
        return f"xmp-mp1:{tag_key}"
    if route_parts[:2] == ("microsoft", "mp"):
        return f"xmp-mp:{tag_key}"
    return None


def _candidate_is_xmp_delete_group(candidate: TagLookupRuntimeCandidate) -> bool:
    return candidate.tag_name.casefold() == "all" and candidate.family1.casefold() in (
        _NATIVE_XMP_DELETE_FAMILIES
    )


def _candidate_is_quicktime_metadata(candidate: TagLookupRuntimeCandidate) -> bool:
    group = _candidate_quicktime_metadata_group(candidate)
    if group is None:
        return False
    return canonical_quicktime_assignment_spec(f"{group}:{candidate.tag_name}") is not None


def _candidate_is_quicktime_microsoft_xtra_assignment(
    candidate: TagLookupRuntimeCandidate,
) -> bool:
    route_parts = _table_route_parts(candidate.table_name)
    return route_parts[:2] == ("microsoft", "xtra") and candidate.tag_name.casefold() in {
        "director",
        "shareduserrating",
    }


def _candidate_is_pdf_metadata_delete_all(candidate: TagLookupRuntimeCandidate) -> bool:
    route_parts = _table_route_parts(candidate.table_name)
    return candidate.tag_name.casefold() == "all" and route_parts[:1] == ("pdf",)


def _candidate_is_pdf_info_scalar(candidate: TagLookupRuntimeCandidate) -> bool:
    route_parts = _table_route_parts(candidate.table_name)
    return (
        route_parts[:2] == ("pdf", "info")
        and canonical_pdf_info_scalar_tag(candidate.tag_name) is not None
    )


def _candidate_quicktime_metadata_group(candidate: TagLookupRuntimeCandidate) -> str | None:
    route_parts = _table_route_parts(candidate.table_name)
    if not route_parts or route_parts[0] != "quicktime":
        return None
    if len(route_parts) == 1:
        return "QuickTime"
    match route_parts[1]:
        case "itemlist":
            return "ItemList"
        case "userdata":
            return "UserData"
        case "keys":
            return "Keys"
        case "audiokeys":
            return "AudioKeys"
        case "videokeys":
            return "VideoKeys"
    return None


def _write_capability_source_anchors() -> tuple[TagLookupSourceAnchor, ...]:
    return (
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/TagLookup.pm",
            symbol="FindTagInfo",
            evidence=(
                "FindTagInfo lower-cases write selectors, expands wildcards, sorts "
                "table matches, and returns all writable candidates in list context."
            ),
        ),
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/Writer.pl",
            symbol="SetNewValue",
            evidence=(
                "SetNewValue routes each requested writable tag through TagLookup "
                "before write execution, but container mutation still depends on a "
                "writer route that owns the destination format."
            ),
        ),
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/IPTC.pm and lib/Image/ExifTool/WriteIPTC.pl",
            symbol="IPTC ApplicationRecord writes",
            evidence=(
                "IPTC.pm defines writable EnvelopeRecord, ApplicationRecord, and "
                "NewsPhoto datasets; WriteIPTC rewrites IPTC records in numeric "
                "record/tag order."
            ),
        ),
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/QuickTime.pm and lib/Image/ExifTool/WriteQuickTime.pl",
            symbol="QuickTime metadata writes",
            evidence=(
                "QuickTime ItemList, UserData, Keys, AudioKeys, and VideoKeys tables "
                "are routed through WriteQuickTime; public execution only marks these "
                "owned when the existing QuickTime metadata writer accepts the tag."
            ),
        ),
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/QuickTime.pm and lib/Image/ExifTool/Microsoft.pm",
            symbol="QuickTime Microsoft Xtra writes",
            evidence=(
                "QuickTime UserData Xtra is the Microsoft Xtra atom route; "
                "Microsoft.pm defines writable WM/Director and WM/SharedUserRating "
                "Xtra entries, while public execution keeps non-owned Xtra formats "
                "and Xtra deletes blocked."
            ),
        ),
        TagLookupSourceAnchor(
            path=("lib/Image/ExifTool/XMP.pm, PNG.pm, RIFF.pm, WriteQuickTime.pl, and Jpeg2000.pm"),
            symbol="XMP packet writes in owned destination containers",
            evidence=(
                "XMP.pm defines writable packet properties, while PNG iTXt, WebP "
                "XMP chunks, MOV/MP4 XMP atoms, JP2 UUID-XMP boxes, and JXL xml "
                "boxes are existing native writer destinations for those properties."
            ),
        ),
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/PDF.pm and lib/Image/ExifTool/WritePDF.pl",
            symbol="PDF Info scalar, XMP Metadata stream, and all-metadata delete writes",
            evidence=(
                "PDF.pm defines writable Info dictionary tags including Title, "
                "Author, Subject, and Keywords; WritePDF appends changed Info "
                "objects, routes XMP writes through Root /Metadata streams, and "
                "also supports the unqualified all-metadata delete shape for "
                "classic, non-encrypted PDFs."
            ),
        ),
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/Writer.pl",
            symbol="classic TIFF EXIF/GPS writes",
            evidence=(
                "WriteInfo dispatches classic TIFF files through ProcessTIFF unless "
                "their TIFF type is in the no-write RAW list; public execution marks "
                "only the existing EXIF scalar and GPS IFD TIFF writer subset owned."
            ),
        ),
    )


def _write_capability_source_reference_ids() -> tuple[str, ...]:
    return _WRITE_CAPABILITY_SOURCE_REFERENCE_IDS


def select_writable_tag_lookup_runtime(
    repository: TagLookupRepository,
    raw_name: str,
    *,
    trusted_overlay: TagLookupRuntimeOverlay = _EMPTY_TAG_LOOKUP_RUNTIME_OVERLAY,
) -> TagLookupSelectionResult:
    parsed_name = parse_tag_lookup_name(raw_name)
    entry = repository.entry_for(parsed_name.tag_name)
    overlay_candidates = tuple(
        _overlay_candidate(overlay_entry)
        for overlay_entry in trusted_overlay.entry_for(parsed_name.tag_name)
        if overlay_entry.writable
    )
    if entry is None and not overlay_candidates:
        return _missing_or_exists_only_selection(repository, parsed_name, trusted_overlay)
    if entry is None:
        repository_candidates: tuple[TagLookupRuntimeCandidate, ...] = ()
    else:
        repository_candidates = tuple(
            candidate
            for table_entry in entry.tables
            if (candidate := _candidate(repository, entry.tag_name, table_entry)) is not None
        )
    candidates = (*repository_candidates, *overlay_candidates)
    if parsed_name.group_name is not None:
        return _group_qualified_selection(parsed_name, candidates)
    if len(candidates) == 1:
        return _selection_result(
            parsed_name,
            "tag_name_lookup",
            "resolved",
            candidates,
            candidates,
            (),
        )
    return _selection_result(
        parsed_name,
        "tag_name_lookup",
        "ambiguous",
        candidates,
        (),
        (
            TagLookupSelectionBlocker(
                code="ambiguous_unqualified_tag",
                detail=(
                    "TagLookup.pm returns writable candidates from every matching table; "
                    "a runtime write route must not choose between them silently."
                ),
            ),
        ),
    )


def parse_tag_lookup_name(raw_name: str) -> TagLookupParsedName:
    group_name, tag_name = _split_group_qualified_name(raw_name)
    return TagLookupParsedName(
        raw_name=raw_name,
        group_name=group_name,
        tag_name=tag_name,
        lookup_key=tag_name.lower(),
    )


def _runtime_result(
    repository: TagLookupRepository,
    request: TagLookupRuntimeRequest,
    status: TagLookupRuntimeStatus,
    matched_tag_names: tuple[str, ...],
    entries: tuple[TagLookupEntry, ...],
    overlay_entries: tuple[TagLookupRuntimeOverlayEntry, ...],
) -> TagLookupRuntimeResult:
    lookup_key = parse_tag_lookup_name(request.tag_name).lookup_key
    return TagLookupRuntimeResult(
        request=request,
        lookup_key=lookup_key,
        status=status,
        exists=repository.exists(lookup_key)
        or any(entry.lookup_key == lookup_key for entry in overlay_entries),
        exists_only=status == "exists_only",
        wildcard=_has_wildcard(lookup_key),
        matched_tag_names=matched_tag_names,
        composite_module=repository.composite_modules.get(lookup_key, ""),
        candidates=tuple(
            (
                *(
                    candidate
                    for entry in entries
                    for table_entry in entry.tables
                    if (candidate := _candidate(repository, entry.tag_name, table_entry))
                    is not None
                ),
                *(_overlay_candidate(entry) for entry in overlay_entries if entry.writable),
            )
        ),
        source_reference_ids=_source_reference_ids(status),
    )


def _candidate(
    repository: TagLookupRepository,
    tag_name: str,
    table_entry: TagLookupTableEntry,
) -> TagLookupRuntimeCandidate | None:
    table_name = repository.table_name(table_entry.table_number)
    if table_name is None:
        return None
    return TagLookupRuntimeCandidate(
        tag_name=tag_name,
        table_number=table_entry.table_number,
        table_name=table_name,
        tag_ids=table_entry.tag_ids,
        flattened_root_tag_id=table_entry.flattened_root_tag_id,
        family0=_candidate_family0(table_name),
        family1=_candidate_family1(table_name),
    )


def _overlay_candidate(entry: TagLookupRuntimeOverlayEntry) -> TagLookupRuntimeCandidate:
    return TagLookupRuntimeCandidate(
        tag_name=entry.tag_name,
        table_number=-1,
        table_name=entry.table_name,
        tag_ids=entry.tag_ids,
        flattened_root_tag_id=None,
        family0=_candidate_family0(entry.table_name),
        family1=_candidate_family1(entry.table_name),
        source_kind="trusted_config",
        source_config=entry.source_config,
        writable=entry.writable,
    )


def _missing_or_exists_only_selection(
    repository: TagLookupRepository,
    parsed_name: TagLookupParsedName,
    trusted_overlay: TagLookupRuntimeOverlay,
) -> TagLookupSelectionResult:
    if repository.exists(parsed_name.tag_name) or trusted_overlay.exists(parsed_name.tag_name):
        return _selection_result(
            parsed_name,
            "tag_exists_only",
            "blocked",
            (),
            (),
            (
                TagLookupSelectionBlocker(
                    code="tag_exists_without_lookup_entry",
                    detail=(
                        "TagLookup.pm recognizes this tag name, but FindTagInfo has no "
                        "writable lookup entry for it."
                    ),
                ),
            ),
        )
    return _selection_result(
        parsed_name,
        "missing_tag",
        "not_found",
        (),
        (),
        (
            TagLookupSelectionBlocker(
                code="tag_not_in_lookup_source",
                detail="The lowercased tag name is absent from the TagLookup repository.",
            ),
        ),
    )


def _group_qualified_selection(
    parsed_name: TagLookupParsedName,
    candidates: tuple[TagLookupRuntimeCandidate, ...],
) -> TagLookupSelectionResult:
    matching_candidates = tuple(
        candidate
        for candidate in candidates
        if _group_matches_table(parsed_name.group_name or "", candidate.table_name)
    )
    if len(matching_candidates) == 1:
        return _selection_result(
            parsed_name,
            "group_qualified_lookup",
            "resolved",
            candidates,
            matching_candidates,
            (),
        )
    if matching_candidates:
        return _selection_result(
            parsed_name,
            "group_qualified_lookup",
            "ambiguous",
            candidates,
            matching_candidates,
            (
                TagLookupSelectionBlocker(
                    code="ambiguous_group_qualified_tag",
                    detail=(
                        "The group qualifier narrows the tag lookup, but multiple "
                        "source tables still match."
                    ),
                ),
            ),
        )
    return _selection_result(
        parsed_name,
        "group_qualified_lookup",
        "blocked",
        candidates,
        (),
        (
            TagLookupSelectionBlocker(
                code="group_does_not_match_tag",
                detail="The requested group qualifier does not match any source table route.",
            ),
        ),
    )


def _selection_result(
    parsed_name: TagLookupParsedName,
    route: TagLookupRuntimeRoute,
    outcome: TagLookupSelectionOutcome,
    candidates: tuple[TagLookupRuntimeCandidate, ...],
    selected_candidates: tuple[TagLookupRuntimeCandidate, ...],
    blockers: tuple[TagLookupSelectionBlocker, ...],
) -> TagLookupSelectionResult:
    return TagLookupSelectionResult(
        request=parsed_name,
        route=route,
        outcome=outcome,
        candidates=candidates,
        selected_candidates=selected_candidates,
        blockers=blockers,
        diagnostics=_selection_diagnostics(outcome, candidates, selected_candidates, blockers),
        source_reference_ids=_selection_source_reference_ids(route, outcome),
    )


def _split_group_qualified_name(raw_name: str) -> tuple[str | None, str]:
    if ":" not in raw_name:
        return None, raw_name
    group_name, tag_name = raw_name.rsplit(":", 1)
    if not group_name or not tag_name:
        return None, raw_name
    return group_name, tag_name


def _group_matches_table(group_name: str, table_name: str) -> bool:
    group_parts = _normalized_group_parts(group_name)
    table_parts = _table_route_parts(table_name)
    if not group_parts:
        return False
    group_key = "::".join(group_parts)
    if group_key == _candidate_family0(table_name).casefold():
        return True
    if group_key == _candidate_family1(table_name).casefold():
        return True
    if group_parts == ("exif",) and table_parts[:1] == ("exif",):
        return True
    if group_parts == ("gps",) and table_parts[:1] == ("gps",):
        return True
    if group_parts == ("xmp",) and table_parts[:1] == ("xmp",):
        return True
    if table_parts[:1] == ("microsoft",):
        if group_parts == ("xmp", "microsoft") and table_parts[:2] == ("microsoft", "xmp"):
            return True
        if group_parts == ("xmp", "mp1") and table_parts[:2] == ("microsoft", "mp1"):
            return True
        if group_parts == ("xmp", "mp") and table_parts[:2] == ("microsoft", "mp"):
            return True
    if table_parts[:1] == ("quicktime",) and len(table_parts) > 1:
        if group_parts == table_parts[1:2]:
            return True
    return table_parts[: len(group_parts)] == group_parts


def _normalized_group_parts(group_name: str) -> tuple[str, ...]:
    normalized = group_name.replace("-", "::")
    return tuple(part.lower() for part in normalized.split("::") if part)


def _table_route_parts(table_name: str) -> tuple[str, ...]:
    prefix = "Image::ExifTool::"
    if table_name.startswith(prefix):
        table_name = table_name.removeprefix(prefix)
    return tuple(part.lower() for part in table_name.split("::") if part)


def _candidate_family0(table_name: str) -> str:
    route_parts = _table_route_parts(table_name)
    return route_parts[0].upper() if route_parts else ""


def _candidate_family1(table_name: str) -> str:
    route_parts = _table_route_parts(table_name)
    if not route_parts:
        return ""
    if route_parts[0] == "xmp" and len(route_parts) > 1:
        return f"XMP-{route_parts[1]}"
    if len(route_parts) > 1 and route_parts[-1] == "main":
        return route_parts[0].upper()
    return "::".join(part.upper() if index == 0 else part for index, part in enumerate(route_parts))


def _selection_diagnostics(
    outcome: TagLookupSelectionOutcome,
    candidates: tuple[TagLookupRuntimeCandidate, ...],
    selected_candidates: tuple[TagLookupRuntimeCandidate, ...],
    blockers: tuple[TagLookupSelectionBlocker, ...],
) -> tuple[TagLookupDiagnosticRecord, ...]:
    records: list[TagLookupDiagnosticRecord] = []
    for blocker in blockers:
        records.append(
            TagLookupDiagnosticRecord(
                severity="error" if outcome in {"blocked", "not_found"} else "warning",
                code=blocker.code,
                message=blocker.detail,
            )
        )
    selected_keys = frozenset(
        (candidate.table_number, candidate.table_name, candidate.tag_ids)
        for candidate in selected_candidates
    )
    for candidate in candidates:
        selected = (
            candidate.table_number,
            candidate.table_name,
            candidate.tag_ids,
        ) in selected_keys
        records.append(
            TagLookupDiagnosticRecord(
                severity="info",
                code="selected_writable_candidate" if selected else "available_writable_candidate",
                message=(
                    f"{candidate.family1 or candidate.family0} candidate from "
                    f"{candidate.table_name}"
                ),
                table_number=candidate.table_number,
                table_name=candidate.table_name,
                tag_ids=candidate.tag_ids,
            )
        )
    return tuple(records)


def _exact_copy_selector_blocker(
    selector: str,
    code: Literal["source_selector_not_exact", "destination_selector_not_exact"],
    detail: str,
) -> TagLookupExactCopyMappingBlocker | None:
    parsed = parse_tag_lookup_name(selector)
    if parsed.group_name is None:
        return TagLookupExactCopyMappingBlocker(code, detail)
    if parsed.tag_name.casefold() in {"*", "all"}:
        return TagLookupExactCopyMappingBlocker(code, detail)
    if _has_wildcard(parsed.tag_name):
        return TagLookupExactCopyMappingBlocker(code, detail)
    return None


def _selector_requires_expansion(
    source_parsed: TagLookupParsedName,
    destination_parsed: TagLookupParsedName,
) -> bool:
    if source_parsed.tag_name.casefold() in {"*", "all"}:
        return True
    if _has_wildcard(source_parsed.tag_name):
        return True
    if destination_parsed.tag_name.casefold() in {"*", "all"}:
        return True
    return _has_wildcard(destination_parsed.tag_name)


def _supported_xmp_exact_source_group(group_name: str) -> bool:
    return group_name.casefold() in {"exif", "gps"}


def _supported_xmp_destination_group(group_name: str) -> bool:
    normalized = group_name.casefold()
    return normalized == "xmp" or normalized.startswith("xmp-")


def _expanded_source_selectors(
    repository: TagLookupRepository,
    source_parsed: TagLookupParsedName,
) -> tuple[str, ...]:
    lookup_key = "*" if source_parsed.tag_name.casefold() == "all" else source_parsed.lookup_key
    entries = _wildcard_entries(repository, lookup_key) if _has_wildcard(lookup_key) else ()
    if not entries:
        return (source_parsed.raw_name,)
    selectors: list[str] = []
    group_name = source_parsed.group_name or ""
    for entry in entries:
        candidate = _single_group_candidate(repository, entry, group_name)
        if candidate is not None:
            selectors.append(f"{group_name}:{candidate.tag_name}")
    return tuple(dict.fromkeys(selectors))


def _single_group_candidate(
    repository: TagLookupRepository,
    entry: TagLookupEntry,
    group_name: str,
) -> TagLookupRuntimeCandidate | None:
    candidates = tuple(
        candidate
        for table_entry in entry.tables
        if (candidate := _candidate(repository, entry.tag_name, table_entry)) is not None
        and _group_matches_table(group_name, candidate.table_name)
    )
    if len(candidates) == 1:
        return candidates[0]
    return None


def _expanded_destination_selector(
    destination_parsed: TagLookupParsedName,
    expanded_source_selector: str,
) -> str:
    destination_group = destination_parsed.group_name or ""
    if destination_parsed.tag_name.casefold() in {"*", "all"}:
        source_tag_name = parse_tag_lookup_name(expanded_source_selector).tag_name
        return f"{destination_group}:{source_tag_name}"
    return destination_parsed.raw_name


def _expanded_destination_selectors(
    repository: TagLookupRepository,
    destination_parsed: TagLookupParsedName,
) -> tuple[str, ...]:
    if destination_parsed.tag_name.casefold() in {"*", "all"}:
        if (
            destination_parsed.group_name is not None
            and destination_parsed.group_name.casefold() != "xmp"
        ):
            entries = _wildcard_entries(repository, "*")
            group_selectors: list[str] = []
            group_name = destination_parsed.group_name
            for entry in entries:
                candidate = _single_group_candidate(repository, entry, group_name)
                if candidate is not None:
                    group_selectors.append(f"{group_name}:{candidate.tag_name}")
            if group_selectors:
                return tuple(dict.fromkeys(group_selectors))
        return (destination_parsed.raw_name,)
    if not _has_wildcard(destination_parsed.tag_name):
        return (destination_parsed.raw_name,)
    entries = _wildcard_entries(repository, destination_parsed.lookup_key)
    if not entries:
        return ()
    selectors: list[str] = []
    group_name = destination_parsed.group_name or ""
    for entry in entries:
        candidate = _single_group_candidate(repository, entry, group_name)
        if candidate is not None:
            selectors.append(f"{group_name}:{candidate.tag_name}")
    return tuple(dict.fromkeys(selectors))


def _expanded_destination_selectors_for_source(
    destination_parsed: TagLookupParsedName,
    wildcard_destination_selectors: tuple[str, ...],
    expanded_source_selector: str,
) -> tuple[str, ...]:
    provenance_selector = _expanded_destination_selector_from_source_provenance(
        destination_parsed,
        wildcard_destination_selectors,
        expanded_source_selector,
    )
    if provenance_selector is not None:
        return (provenance_selector,)
    if destination_parsed.tag_name.casefold() in {"*", "all"}:
        if wildcard_destination_selectors != (destination_parsed.raw_name,):
            return wildcard_destination_selectors
        return (_expanded_destination_selector(destination_parsed, expanded_source_selector),)
    return wildcard_destination_selectors


def _expanded_destination_selector_from_source_provenance(
    destination_parsed: TagLookupParsedName,
    wildcard_destination_selectors: tuple[str, ...],
    expanded_source_selector: str,
) -> str | None:
    source_parsed = parse_tag_lookup_name(expanded_source_selector)
    source_group = source_parsed.group_name
    if source_group is None:
        return None
    source_provenance = _xmp_exact_source_provenance_for_group_tag(
        source_group,
        source_parsed.tag_name,
    )
    if source_provenance is None:
        return None
    destination_group, _, destination_tag = source_provenance.destination_property_name.partition(
        ":"
    )
    requested_group = destination_parsed.group_name or ""
    if (
        requested_group.casefold() != "xmp"
        and requested_group.casefold() != destination_group.casefold()
    ):
        return None
    if destination_parsed.tag_name.casefold() in {"*", "all"}:
        return source_provenance.destination_property_name
    if not _has_wildcard(destination_parsed.tag_name):
        return None
    if not _wildcard_tag_pattern_matches(destination_parsed.tag_name, destination_tag):
        return None
    selector = f"{requested_group}:{destination_tag}"
    if selector.casefold() in {item.casefold() for item in wildcard_destination_selectors}:
        return selector
    return None


def _xmp_exact_source_provenance_for_group_tag(
    group_name: str,
    tag_name: str,
) -> _ExactCopySourceProvenance | None:
    for source_provenance in _XMP_EXACT_COPY_SOURCE_PROVENANCE:
        if (
            source_provenance.family1.casefold() == group_name.casefold()
            and source_provenance.tag_name.casefold() == tag_name.casefold()
        ):
            return source_provenance
    return None


def _wildcard_tag_pattern_matches(pattern: str, tag_name: str) -> bool:
    regex_pattern = re.escape(pattern.casefold())
    regex_pattern = regex_pattern.replace(r"\*", r"[-\w]*")
    regex_pattern = regex_pattern.replace(r"\?", r"[-\w]")
    return re.fullmatch(regex_pattern, tag_name.casefold()) is not None


def _exact_copy_mapping_result(
    source_selector: str,
    destination_selector: str,
    source_selection: TagLookupSelectionResult | None,
    destination_selection: TagLookupSelectionResult | None,
    blockers: tuple[TagLookupExactCopyMappingBlocker, ...],
) -> TagLookupExactCopyMappingResult:
    return TagLookupExactCopyMappingResult(
        source_selector=source_selector,
        destination_selector=destination_selector,
        outcome="blocked",
        mapping=None,
        source_selection=source_selection,
        destination_selection=destination_selection,
        blockers=blockers,
        source_reference_ids=_exact_copy_mapping_source_reference_ids(),
    )


def _xmp_exact_source_provenance(
    candidate: TagLookupRuntimeCandidate,
) -> _ExactCopySourceProvenance | None:
    for source_provenance in _XMP_EXACT_COPY_SOURCE_PROVENANCE:
        if (
            _source_candidate_matches_exact_provenance(candidate, source_provenance)
            and source_provenance.tag_name.casefold() == candidate.tag_name.casefold()
        ):
            return source_provenance
    return None


def _source_candidate_matches_exact_provenance(
    candidate: TagLookupRuntimeCandidate,
    source_provenance: _ExactCopySourceProvenance,
) -> bool:
    provenance_family = source_provenance.family1.casefold()
    candidate_family = candidate.family1.casefold()
    if provenance_family == candidate_family:
        return True
    if provenance_family == "exif" and candidate.family0.casefold() == "exif":
        return True
    return provenance_family == "gps" and candidate.family0.casefold() == "gps"


def _xmp_exact_destination_writer(
    candidate: TagLookupRuntimeCandidate,
) -> _ExactCopyDestinationWriter | None:
    for destination_writer in _XMP_EXACT_COPY_DESTINATION_WRITERS:
        if (
            destination_writer.family1.casefold() == candidate.family1.casefold()
            and destination_writer.tag_name.casefold() == candidate.tag_name.casefold()
        ):
            return destination_writer
    return None


def _exact_copy_mapping_source_anchors() -> tuple[TagLookupSourceAnchor, ...]:
    return (
        TagLookupSourceAnchor(
            path="exiftool",
            symbol="-tagsFromFile exact redirection docs",
            evidence=(
                "Lines 5522-5538 document exact SRCTAG>DSTTAG and DSTTAG<SRCTAG "
                "copy redirection, group-qualified source/destination tags, "
                "wildcards, and destination All/* preservation."
            ),
        ),
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/TagLookup.pm",
            symbol="FindTagInfo",
            evidence=(
                "Lines 13986-14063 lower-case writable tag names, sort table "
                "matches, expand flattened tags, and return all candidates in list "
                "context so exact copy routes can refuse ambiguity."
            ),
        ),
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/XMP.pm",
            symbol="XMP EXIF/GPS writable tables",
            evidence=(
                "Lines 1903-2362 define tiff/exif scalar aliases including "
                "Make, Model, Orientation, ResolutionUnit, YCbCrPositioning, "
                "ISO, ExifVersion, ComponentsConfiguration, ColorSpace, FNumber, "
                "FocalLength, DateTimeOriginal, ExifImageWidth, and XMP GPS "
                "latitude/longitude properties."
            ),
        ),
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/Writer.pl",
            symbol="SetNewValuesFromFile",
            evidence=(
                "Lines 1248-1664 parse source/destination copy tags, match source "
                "groups/tags, preserve explicit protected copies, and set matched "
                "values in original route order."
            ),
        ),
    )


def _exact_copy_mapping_source_reference_ids() -> tuple[str, ...]:
    return _EXACT_COPY_MAPPING_SOURCE_REFERENCE_IDS


def _wildcard_entries(
    repository: TagLookupRepository,
    lookup_key: str,
) -> tuple[TagLookupEntry, ...]:
    pattern = _wildcard_pattern(lookup_key)
    return tuple(
        repository.lookup[key]
        for key in sorted(repository.lookup)
        if re.fullmatch(pattern, key) is not None
    )


def _wildcard_overlay_entries(
    trusted_overlay: TagLookupRuntimeOverlay,
    lookup_key: str,
) -> tuple[TagLookupRuntimeOverlayEntry, ...]:
    pattern = _wildcard_pattern(lookup_key)
    return tuple(
        entry
        for entry in sorted(trusted_overlay.entries, key=lambda item: item.lookup_key)
        if re.fullmatch(pattern, entry.lookup_key) is not None
    )


def _wildcard_pattern(lookup_key: str) -> str:
    pieces: list[str] = []
    for character in lookup_key:
        if character == "*":
            pieces.append(r"[-\w]*")
        elif character == "?":
            pieces.append(r"[-\w]")
        else:
            pieces.append(re.escape(character))
    return "".join(pieces)


def _has_wildcard(lookup_key: str) -> bool:
    return "*" in lookup_key or "?" in lookup_key


def _source_anchors(
    status: TagLookupRuntimeStatus,
) -> tuple[TagLookupSourceAnchor, ...]:
    references = [
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/TagLookup.pm",
            symbol="TagExists",
            evidence=(
                "Lines 13974-13978 lower-case tag names and check %tagExists "
                "or %tagLookup for exact tag existence."
            ),
        ),
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/TagLookup.pm",
            symbol="FindTagInfo",
            evidence=(
                "Lines 13986-14006 lower-case lookup names, expand * and ? "
                "wildcards over %tagLookup, sort matches, and walk table "
                "numbers numerically."
            ),
        ),
    ]
    if status in {"resolved", "wildcard_resolved"}:
        references.append(
            TagLookupSourceAnchor(
                path="lib/Image/ExifTool/TagLookup.pm",
                symbol="FindTagInfo flattened/composite handling",
                evidence=(
                    "Lines 14009-14036 preserve flattened root tag IDs and "
                    "composite-module reload requirements for writable lookup candidates."
                ),
            )
        )
    return tuple(references)


def _source_reference_ids(status: TagLookupRuntimeStatus) -> tuple[str, ...]:
    reference_ids = (
        "tag_lookup.tag_exists",
        "tag_lookup.find_tag_info.lookup",
    )
    if status in {"resolved", "wildcard_resolved"}:
        return (
            *reference_ids,
            "tag_lookup.find_tag_info.flattened_composite",
        )
    return reference_ids


def _selection_source_anchors(
    route: TagLookupRuntimeRoute,
    outcome: TagLookupSelectionOutcome,
) -> tuple[TagLookupSourceAnchor, ...]:
    references = [
        TagLookupSourceAnchor(
            path="lib/Image/ExifTool/TagLookup.pm",
            symbol="FindTagInfo",
            evidence=(
                "Lines 13986-14063 lower-case lookup names, sort matching table "
                "numbers numerically, expand flattened tags, and return all tag "
                "info records to the caller in list context."
            ),
        ),
    ]
    if route == "tag_exists_only":
        references.append(
            TagLookupSourceAnchor(
                path="lib/Image/ExifTool/TagLookup.pm",
                symbol="TagExists",
                evidence=(
                    "Lines 13974-13978 check %tagExists and %tagLookup; names in "
                    "%tagExists only are recognized but have no writable lookup entry."
                ),
            )
        )
    if route == "group_qualified_lookup":
        references.append(
            TagLookupSourceAnchor(
                path="exiftool",
                symbol="group-qualified tag dispatch",
                evidence=(
                    "The ExifTool command layer parses optional group prefixes before "
                    "calling TagLookup; the runtime service exposes that caller-side "
                    "filtering as explicit selected candidates instead of mutating "
                    "the generated lookup data."
                ),
            )
        )
    if outcome == "ambiguous":
        references.append(
            TagLookupSourceAnchor(
                path="lib/Image/ExifTool/TagLookup.pm",
                symbol="FindTagInfo list context",
                evidence=(
                    "FindTagInfo may return multiple matching tag info hashes; "
                    "runtime callers must handle ambiguity explicitly."
                ),
            )
        )
    return tuple(references)


def _selection_source_reference_ids(
    route: TagLookupRuntimeRoute,
    outcome: TagLookupSelectionOutcome,
) -> tuple[str, ...]:
    reference_ids = ["tag_lookup.find_tag_info.selection"]
    if route == "tag_exists_only":
        reference_ids.append("tag_lookup.tag_exists.exists_only_selection")
    if route == "group_qualified_lookup":
        reference_ids.append("exiftool.group_qualified_tag_dispatch")
    if outcome == "ambiguous":
        reference_ids.append("tag_lookup.find_tag_info.ambiguous_list_context")
    return tuple(reference_ids)


_TAG_LOOKUP_SOURCE_REFERENCES_BY_ID = {
    **dict(
        zip(
            _WRITE_CAPABILITY_SOURCE_REFERENCE_IDS,
            _write_capability_source_anchors(),
            strict=True,
        )
    ),
    **dict(
        zip(
            _EXACT_COPY_MAPPING_SOURCE_REFERENCE_IDS,
            _exact_copy_mapping_source_anchors(),
            strict=True,
        )
    ),
    **dict(zip(_source_reference_ids("resolved"), _source_anchors("resolved"), strict=True)),
    **dict(
        zip(
            _selection_source_reference_ids("tag_exists_only", "blocked"),
            _selection_source_anchors("tag_exists_only", "blocked"),
            strict=True,
        )
    ),
    **dict(
        zip(
            _selection_source_reference_ids("group_qualified_lookup", "resolved"),
            _selection_source_anchors("group_qualified_lookup", "resolved"),
            strict=True,
        )
    ),
    **dict(
        zip(
            _selection_source_reference_ids("tag_name_lookup", "ambiguous"),
            _selection_source_anchors("tag_name_lookup", "ambiguous"),
            strict=True,
        )
    ),
}


def _tag_lookup_source_anchors(
    source_reference_ids: tuple[str, ...],
) -> tuple[TagLookupSourceAnchor, ...]:
    return tuple(_TAG_LOOKUP_SOURCE_REFERENCES_BY_ID[id_] for id_ in source_reference_ids)
