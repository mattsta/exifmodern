"""Bounded native write execution for the public API."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Iterable
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

from exifmodern.exif_scalar_write_plan import (
    ExifScalarTagName,
    ExifScalarWritePlan,
    ExifScalarWriteStep,
    build_exif_scalar_delete_plan,
    build_exif_scalar_write_plan,
)
from exifmodern.file_transaction import (
    BackupPolicy,
    copy_back_bytes_in_place_transactionally,
    write_bytes_in_place_transactionally,
    write_bytes_transactionally,
)
from exifmodern.formats.bigtiff.transaction_plan import materialize_bigtiff_exif_gps_source
from exifmodern.formats.casio.maker_note import (
    CasioMakerNoteFamily,
    CasioMakerNoteWritePlan,
    build_casio_maker_note_write_plan,
)
from exifmodern.formats.exif_sidecar.copy_from_file_plan import (
    ExifSidecarCopyFromFilePlan,
    exif_sidecar_public_execution_boundary_report,
    parse_exif_sidecar_copy_from_file_args,
)
from exifmodern.formats.exif_sidecar.sidecar_writer import (
    ExifSidecarCopyFromFileExecutionRequest,
    execute_exif_sidecar_copy_from_file_request,
)
from exifmodern.formats.gps.transaction_plan import gps_coordinate_to_degrees
from exifmodern.formats.icc.materializer import materialize_source_icc_profile
from exifmodern.formats.iptc.reader import parse_iptc_application_record
from exifmodern.formats.iptc.write_plan import (
    IPTC_APPLICATION_TAG_SPECS,
    IptcApplicationWritePlan,
    IptcApplicationWriteStep,
    iptc_application_tag_spec,
    text_step,
    upsert_binary_step,
    upsert_text_step,
)
from exifmodern.formats.jpeg.app_segment_delete import (
    JpegAppSegmentDeletePlan,
    build_jpeg_app_segment_delete_plan,
    delete_jpeg_app_segments,
    jpeg_app_segment_delete_target,
)
from exifmodern.formats.jpeg.app_segments.xmp import XMP_APP1_PREFIX
from exifmodern.formats.jpeg.binary_makernote_writer import (
    rewrite_jpeg_maker_note_binary_data,
)
from exifmodern.formats.jpeg.casio_makernote_writer import rewrite_jpeg_casio_maker_notes
from exifmodern.formats.jpeg.container import (
    read_exif_ifd_tags,
    read_gps_ifd_tags,
    read_ifd0_tags,
    read_jpeg_segment_probes,
    scan_jpeg_segments,
)
from exifmodern.formats.jpeg.exif_app1 import (
    EXIF_APP1_PREFIX,
    encode_app1_segment,
    exif_app1_insertion_offset,
    find_exif_app1_segment_or_none,
    segment_payload,
)
from exifmodern.formats.jpeg.exif_gps_writer import (
    rewrite_jpeg_exif_gps_creating_if_needed,
    rewrite_jpeg_file_exif_gps_in_place,
)
from exifmodern.formats.jpeg.exif_scalar_writer import (
    rewrite_jpeg_exif_scalars_creating_if_needed,
    rewrite_jpeg_file_exif_scalars_in_place,
)
from exifmodern.formats.jpeg.inline_makernote_writer import (
    rewrite_jpeg_inline_maker_note_scalars,
)
from exifmodern.formats.jpeg.iptc_app13_writer import (
    existing_iptc_resource_data,
    first_photoshop_app13_segment,
    rewrite_jpeg_iptc_application_creating_if_needed,
)
from exifmodern.formats.jpeg.xmp_app1 import (
    encode_xmp_app1_segment,
    first_standard_xmp_app1_segment,
    xmp_app1_insertion_offset,
)
from exifmodern.formats.jpeg.xmp_property_writer import (
    rewrite_jpeg_xmp_copy_assignments_creating_if_needed,
    rewrite_jpeg_xmp_properties_creating_if_needed,
)
from exifmodern.formats.jpeg2000.metadata_writer import (
    rewrite_jp2_metadata,
)
from exifmodern.formats.jxl.metadata_writer import rewrite_jxl_metadata
from exifmodern.formats.makernote.binary_data import MakerNoteBinaryDataWritePlan
from exifmodern.formats.makernote.inline_ifd import InlineMakerNoteScalarWritePlan
from exifmodern.formats.minolta.maker_note import build_minolta_date_write_plan
from exifmodern.formats.pdf.metadata_delete_writer import (
    PDF_INFO_SCALAR_TAGS,
    PdfInfoScalarAssignment,
    _pdf_info_write_evidence_ids,
    canonical_pdf_info_scalar_tag,
    rewrite_pdf_info_scalar_metadata,
    rewrite_pdf_metadata_delete,
)
from exifmodern.formats.pdf.xmp_metadata_stream_writer import rewrite_pdf_xmp_metadata_stream
from exifmodern.formats.photoshop.reader import parse_photoshop_resources
from exifmodern.formats.png.metadata_writer import (
    rewrite_png_metadata,
    standard_xmp_payload_from_png,
)
from exifmodern.formats.quicktime.fanout_writer import (
    rewrite_microsoft_xtra,
    rewrite_quicktime_xmp_properties,
)
from exifmodern.formats.quicktime.metadata_atoms import (
    QuickTimeMetadataWritePlan,
    parse_quicktime_metadata_write_args,
)
from exifmodern.formats.quicktime.metadata_writer import rewrite_quicktime_metadata
from exifmodern.formats.quicktime.microsoft_metadata import (
    MicrosoftXtraAssignment,
    MicrosoftXtraBlocker,
    classify_microsoft_xtra_assignment,
    microsoft_xtra_tag_spec,
)
from exifmodern.formats.riff.webp_writer import (
    EXIF_CHUNK_ID,
    ICC_CHUNK_ID,
    XMP_CHUNK_ID,
    encode_webp_chunks,
    existing_chunk_payload,
    parse_webp_chunks,
    rewrite_webp_metadata,
    update_vp8x_chunks,
    upsert_webp_chunk,
)
from exifmodern.formats.sanyo.maker_note import build_sanyo_flash_mode_write_plan
from exifmodern.formats.tiff.exif_scalar_file_writer import (
    rewrite_tiff_exif_scalars_creating_if_needed,
)
from exifmodern.formats.tiff.gps_rewriter import rewrite_gps_ifd_creating_if_needed
from exifmodern.formats.tiff.primitives import (
    read_exif_ifd_values,
    read_gps_ifd_values,
    read_ifd0_values,
)
from exifmodern.formats.xmp.copy_from_file_plan import (
    EXIF_TIFF_EXACT_COPY_SOURCE_SUFFIXES,
    SUPPORTED_EXACT_COPY_SOURCE_SUFFIXES,
    TIFF_RAW_EXACT_COPY_SOURCE_SUFFIXES,
    ExifSourceTag,
    XmpCopyFromFilePlan,
    XmpDestinationAssignment,
    XmpMaterializedCopyFromFilePlan,
    mappings_for_copy_plan,
    materialize_xmp_copy_from_file_plan,
    parse_xmp_copy_from_file_args,
    source_path_has_bigtiff_header,
    source_path_has_exif_tiff_header,
    xmp_assignment_values_for_source_tag,
)
from exifmodern.formats.xmp.family2_delete import (
    XmpFamily2DeletePlan,
    XmpFamily2DeleteTarget,
    build_xmp_family2_delete_plan,
    xmp_family2_delete_target,
)
from exifmodern.formats.xmp.group_delete import (
    XmpNamespaceDeletePlan,
    XmpNamespaceDeleteTarget,
    build_xmp_namespace_delete_plan,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan, delete_xmp_namespace
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import (
    XMP_PUBLIC_SIDECAR_PROPERTY_NAMES,
    XmpPropertyWritePlan,
    XmpPublicSidecarPropertyAssignment,
    XmpPublicSidecarPropertyDelete,
    build_public_xmp_sidecar_property_delete_plan,
    build_public_xmp_sidecar_property_write_plan,
    split_xmp_public_list_value,
)
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.formats.xmp.sidecar_copy_writer import (
    rewrite_xmp_sidecar_copy_from_file,
    rewrite_xmp_sidecar_copy_from_file_to_path,
    xmp_property_write_plan_from_copy_assignments,
)
from exifmodern.formats.xmp.sidecar_writer import (
    delete_xmp_sidecar_family2_groups,
    delete_xmp_sidecar_file_family2_groups_in_place,
    rewrite_xmp_sidecar_file_properties_in_place,
    rewrite_xmp_sidecar_properties,
)
from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.media_source import FileMediaSource
from exifmodern.public_api.import_write_executor import execute_import_write_request
from exifmodern.public_api.models import (
    Diagnostic,
    ExifSidecarCopyFromFileRequest,
    ExifSidecarCopyRouteRequest,
    MetadataAssignment,
    MetadataWriteRequest,
    MetadataWriteResult,
    PublicCopyFromFileAlternateFile,
    PublicCopyFromFileRequest,
    PublicCopyFromFileRouteRequest,
    PublicOperationStatus,
    XmpSidecarCopyFromFileRequest,
    XmpSidecarCopyRouteRequest,
    plan_metadata_write,
)
from exifmodern.public_interface.alternate_files import (
    PublicInsertTagValue,
    alternate_file_format_support,
    public_insert_tag_interpolation_issues,
    public_insert_tag_value_tokens,
    resolve_alternate_file_path,
)
from exifmodern.services.tag_lookup_runtime import (
    TagLookupExactCopyMapping,
    TagLookupExactCopyMappingResult,
    TagLookupRuntimeCandidate,
    TagLookupSelectionResult,
    load_tag_lookup_runtime_service,
)
from exifmodern.write_plan import (
    ExifGpsTagName,
    ExifGpsWritePlan,
    append_gps_delete_steps,
    build_exif_gps_write_plan,
)

type _SupportedXmpScalarTag = Literal[
    "XMP-aux:Lens",
    "XMP-dc:Creator",
    "XMP-dc:Description",
    "XMP-dc:Rights",
    "XMP-dc:Subject",
    "XMP-dc:Title",
    "XMP-photoshop:City",
    "XMP-photoshop:DateCreated",
    "XMP-photoshop:State",
    "XMP-xmpMM:DocumentID",
    "XMP-xmpRights:Marked",
    "XMP-xmpRights:UsageTerms",
]

_SUPPORTED_XMP_SCALAR_TAGS = frozenset(
    property_name.lower() for property_name in XMP_PUBLIC_SIDECAR_PROPERTY_NAMES
)
_SUPPORTED_XMP_FAMILY2_DELETE_GROUPS = frozenset({"camera", "image"})
_SUPPORTED_XMP_FAMILY2_DELETE_SELECTORS = frozenset({"*", "all"})
_SUPPORTED_XMP_NAMESPACE_DELETE_GROUPS: dict[str, XmpNamespaceDeleteTarget] = {
    "xmp-dc": "XMP-dc",
    "xmp-photoshop": "XMP-photoshop",
    "xmp-xmpbj": "XMP-xmpBJ",
    "xmp-xmpmm": "XMP-xmpMM",
    "xmp-xmprights": "XMP-xmpRights",
}
_SUPPORTED_XMP_NAMESPACE_DELETE_SELECTORS = frozenset({"*", "all"})
_SUPPORTED_XMP_LIST_MUTATION_TAGS = frozenset({"xmp-dc:subject"})
_SUPPORTED_IPTC_KEYWORDS_LIST_MUTATION_TAGS = frozenset({"iptc:keywords", "keywords"})
_SUPPORTED_IPTC_ASSIGNMENT_TAGS = {
    normalized_tag: canonical_tag
    for canonical_tag in IPTC_APPLICATION_TAG_SPECS
    for normalized_tag in (canonical_tag.casefold(), f"iptc:{canonical_tag.casefold()}")
}
_SUPPORTED_IPTC_LIST_ASSIGNMENT_TAGS = frozenset(
    normalized_tag
    for canonical_tag, spec in IPTC_APPLICATION_TAG_SPECS.items()
    if spec.is_list
    for normalized_tag in (canonical_tag.casefold(), f"iptc:{canonical_tag.casefold()}")
)

type _PublicGpsCoreTag = Literal[
    "GPSLatitude",
    "GPSLatitudeRef",
    "GPSLongitude",
    "GPSLongitudeRef",
]
type _JpegGpsRefTag = Literal["GPSLatitudeRef", "GPSLongitudeRef"]
type _JpegGpsCoordinateTag = Literal["GPSLatitude", "GPSLongitude"]
type _JpegGpsKind = Literal["lat", "lon"]
type _PublicExifScalarTag = Literal[
    "Artist",
    "ImageDescription",
    "Orientation",
    "ModifyDate",
    "DateTimeOriginal",
    "ISO",
    "FocalLength",
    "SceneCaptureType",
]
type _PublicExifScalarValue = str | int | float
type _PublicGpsValue = str
type _PublicWriteFamily = Literal["gps", "scalar", "xmp", "unsupported"]
type _VendorJpegComposedKind = Literal["casio", "minolta", "sanyo"]
type _PublicExactCopySourceClass = Literal[
    "missing_source",
    "jpeg_exif_app1",
    "standalone_exif_tiff",
    "bigtiff",
    "classic_tiff_raw_wrapper",
    "nonstandard_tiff_raw_wrapper",
    "non_tiff_raw_wrapper",
    "media_container",
    "chunked_image_container",
    "unsupported_suffix",
]
type _PublicExactCopyDestinationClass = Literal[
    "exif_tiff_sidecar_or_image",
    "bigtiff",
    "classic_tiff_raw_wrapper",
    "nonstandard_tiff_raw_wrapper",
    "non_tiff_raw_wrapper",
    "media_container",
    "chunked_image_container",
    "unsupported_suffix",
]

_JPEG_SUFFIXES = frozenset({".jpg", ".jpeg", ".jpe"})
_TIFF_SUFFIXES = frozenset({".tif", ".tiff"})
_NONSTANDARD_TIFF_RAW_SUFFIXES = frozenset({".orf", ".raw", ".rw2", ".rwl"})
_NON_TIFF_RAW_SUFFIXES = frozenset({".crw", ".iiq", ".mrw", ".raf", ".x3f"})
_MEDIA_CONTAINER_EXACT_COPY_SUFFIXES = frozenset(
    {".3gp", ".avif", ".heic", ".heif", ".m4a", ".m4v", ".mov", ".mp4", ".qt"}
)
_QUICKTIME_METADATA_WRITE_SUFFIXES = frozenset({".3gp", ".m4a", ".m4v", ".mov", ".mp4", ".qt"})
_JPEG2000_CODESTREAM_SUFFIXES = frozenset({".j2c", ".j2k", ".jpc"})
_CHUNKED_IMAGE_EXACT_COPY_SUFFIXES = _JPEG2000_CODESTREAM_SUFFIXES | frozenset(
    {".jp2", ".jxl", ".png", ".webp"}
)
_SUPPORTED_XMP_ASSIGNMENT_SUFFIXES = (
    _JPEG_SUFFIXES
    | _QUICKTIME_METADATA_WRITE_SUFFIXES
    | frozenset({".xmp", ".png", ".webp", ".jp2", ".jxl", ".pdf"})
)
_SUPPORTED_SCALAR_GROUP_PREFIXES = frozenset({"", "exif", "ifd0", "exififd"})
_SCALAR_TAG_BY_KEY: dict[str, _PublicExifScalarTag] = {
    "artist": "Artist",
    "imagedescription": "ImageDescription",
    "orientation": "Orientation",
    "modifydate": "ModifyDate",
    "datetimeoriginal": "DateTimeOriginal",
    "iso": "ISO",
    "focallength": "FocalLength",
    "scenecapturetype": "SceneCaptureType",
}
_IFD0_SCALAR_TAGS: frozenset[_PublicExifScalarTag] = frozenset(
    {
        "Artist",
        "ImageDescription",
        "ModifyDate",
        "Orientation",
    }
)
_EXIFIFD_SCALAR_TAGS: frozenset[_PublicExifScalarTag] = frozenset(
    {
        "DateTimeOriginal",
        "FocalLength",
        "ISO",
        "SceneCaptureType",
    }
)
_SUPPORTED_GPS_CORE_TAGS = frozenset(
    {
        "gpslatitude",
        "gpslatituderef",
        "gpslongitude",
        "gpslongituderef",
    }
)
_GPS_CORE_TAG_BY_KEY: dict[str, _PublicGpsCoreTag] = {
    "gpslatitude": "GPSLatitude",
    "gpslatituderef": "GPSLatitudeRef",
    "gpslongitude": "GPSLongitude",
    "gpslongituderef": "GPSLongitudeRef",
}
_SUPPORTED_GPS_GROUP_PREFIXES = frozenset({"", "composite", "exif", "gps"})


@dataclass(frozen=True)
class _PreparedXmpSidecarWrite:
    paths: tuple[Path, ...]
    plan: XmpPropertyWritePlan
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedXmpSubjectListMutation:
    paths: tuple[Path, ...]
    assignments: tuple[MetadataAssignment, ...]
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedJpegIptcKeywordsListMutation:
    paths: tuple[Path, ...]
    assignments: tuple[MetadataAssignment, ...]
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedJpegIptcAssignmentWrite:
    paths: tuple[Path, ...]
    plan: IptcApplicationWritePlan
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedJpegIptcDeleteWrite:
    paths: tuple[Path, ...]
    plan: IptcApplicationWritePlan
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedJpegAppSegmentDeleteWrite:
    paths: tuple[Path, ...]
    plan: JpegAppSegmentDeletePlan
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedXmpSidecarFamily2Delete:
    paths: tuple[Path, ...]
    plan: XmpFamily2DeletePlan
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedXmpSidecarNamespaceDelete:
    paths: tuple[Path, ...]
    plans: tuple[XmpNamespaceDeletePlan, ...]
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedXmpSidecarCopyFromFile:
    paths: tuple[Path, ...]
    source_path: Path
    plan: XmpCopyFromFilePlan
    backup_policy: BackupPolicy
    route_tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedExifSidecarCopyFromFile:
    paths: tuple[Path, ...]
    source_path: Path
    plan: ExifSidecarCopyFromFilePlan
    backup_policy: BackupPolicy
    route_tags: tuple[str, ...]


@dataclass(frozen=True)
class _PublicExactCopySourceSupport:
    supported: bool
    source_class: _PublicExactCopySourceClass
    blocker_code: str | None
    detail: str


@dataclass(frozen=True)
class _PublicExactCopyDestinationBlocker:
    path: Path
    suffix: str
    destination_class: _PublicExactCopyDestinationClass
    blocker_code: str
    detail: str


@dataclass(frozen=True)
class _PreparedPublicXmpExactCopyRewrite:
    path: Path
    data: bytes
    changed: bool
    copied_properties: int
    surface: str


@dataclass(frozen=True)
class _PreparedJpegGpsWrite:
    paths: tuple[Path, ...]
    plan: ExifGpsWritePlan
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedJpegExifScalarWrite:
    paths: tuple[Path, ...]
    plan: ExifScalarWritePlan
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PublicOrderedScalarEffect:
    order_index: int
    sequence_index: int
    operation: Literal["upsert", "delete"]
    tag: _PublicExifScalarTag
    value: _PublicExifScalarValue | None
    route: str


@dataclass(frozen=True)
class _PublicOrderedGpsEffect:
    order_index: int
    sequence_index: int
    operation: Literal["upsert", "delete"]
    tag: _PublicGpsCoreTag
    value: _PublicGpsValue | None
    route: str


type _PublicOrderedExifEffect = _PublicOrderedScalarEffect | _PublicOrderedGpsEffect


@dataclass(frozen=True)
class _PublicOrderedExifSourceValues:
    source_path: Path
    scalar_group_values: dict[str, dict[_PublicExifScalarTag, _PublicExifScalarValue]]
    gps_values: dict[_PublicGpsCoreTag, _PublicGpsValue]


@dataclass(frozen=True)
class _PublicOrderedExifTargetPlan:
    path: Path
    scalar_plan: ExifScalarWritePlan | None
    gps_plan: ExifGpsWritePlan | None
    ordered_effects: tuple[_PublicOrderedExifEffect, ...]


@dataclass(frozen=True)
class _PreparedPublicOrderedExifRewrite:
    path: Path
    data: bytes
    changed: bool
    surface: str


@dataclass(frozen=True)
class _PreparedVendorJpegComposedWrite:
    paths: tuple[Path, ...]
    kind: _VendorJpegComposedKind
    backup_policy: BackupPolicy
    tags: tuple[str, ...]
    exif_plan: ExifScalarWritePlan | None = None
    casio_plan: CasioMakerNoteWritePlan | None = None
    binary_maker_note_plan: MakerNoteBinaryDataWritePlan | None = None
    inline_maker_note_plan: InlineMakerNoteScalarWritePlan | None = None
    iptc_plan: IptcApplicationWritePlan | None = None


@dataclass(frozen=True)
class _PreparedQuickTimeMetadataWrite:
    paths: tuple[Path, ...]
    plan: QuickTimeMetadataWritePlan
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedQuickTimeMicrosoftXtraWrite:
    paths: tuple[Path, ...]
    assignments: tuple[MicrosoftXtraAssignment, ...]
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedPdfMetadataDeleteWrite:
    paths: tuple[Path, ...]
    backup_policy: BackupPolicy
    tags: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedPdfInfoScalarWrite:
    paths: tuple[Path, ...]
    backup_policy: BackupPolicy
    assignments: tuple[PdfInfoScalarAssignment, ...]
    tags: tuple[str, ...]


def execute_metadata_write(request: MetadataWriteRequest) -> MetadataWriteResult:
    if request.import_write is not None:
        return execute_import_write_request(
            request,
            execute_metadata_write=execute_metadata_write,
        )
    plan = plan_metadata_write(request)
    policy_diagnostics = _blocking_write_policy_diagnostics(request)
    if policy_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=plan.diagnostics,
        )
    list_copy_diagnostics = _unsupported_mixed_public_list_mutation_copy_diagnostics(request)
    if list_copy_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan.diagnostics, *list_copy_diagnostics),
        )
    public_copy_result = _execute_public_copy_from_file_if_supported(request, plan.diagnostics)
    if public_copy_result is not None:
        return public_copy_result
    public_copy_diagnostics = _public_copy_from_file_diagnostics(request.public_copy_from_file)
    if public_copy_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan.diagnostics, *public_copy_diagnostics),
        )

    webp_icc_delete_result = _execute_webp_icc_delete_if_supported(request, plan.diagnostics)
    if webp_icc_delete_result is not None:
        return webp_icc_delete_result

    prepared_pdf_delete, pdf_delete_diagnostics = _prepare_pdf_metadata_delete_write(request)
    if prepared_pdf_delete is not None:
        return _execute_pdf_metadata_delete_write(request, prepared_pdf_delete, plan.diagnostics)

    prepared_pdf_info, pdf_info_diagnostics = _prepare_pdf_info_scalar_write(request)
    if prepared_pdf_info is not None:
        return _execute_pdf_info_scalar_write(request, prepared_pdf_info, plan.diagnostics)

    prepared_exif_copy, exif_copy_diagnostics = _prepare_exif_sidecar_copy_from_file(request)
    if prepared_exif_copy is not None:
        return _execute_exif_sidecar_copy_from_file(
            request,
            prepared_exif_copy,
            plan.diagnostics,
        )
    if _has_blocking_exif_sidecar_copy_diagnostics(exif_copy_diagnostics):
        return MetadataWriteResult(
            request=request,
            status=_status_for_deferred_diagnostics(exif_copy_diagnostics),
            diagnostics=(*plan.diagnostics, *exif_copy_diagnostics),
        )

    prepared_xmp_copy, xmp_copy_diagnostics = _prepare_xmp_sidecar_copy_from_file(request)
    if prepared_xmp_copy is not None:
        return _execute_xmp_sidecar_copy_from_file(
            request,
            prepared_xmp_copy,
            plan.diagnostics,
        )
    if _has_blocking_xmp_sidecar_copy_diagnostics(xmp_copy_diagnostics):
        return MetadataWriteResult(
            request=request,
            status=_status_for_deferred_diagnostics(xmp_copy_diagnostics),
            diagnostics=(*plan.diagnostics, *xmp_copy_diagnostics),
        )

    prepared_xmp_property_delete, xmp_property_delete_diagnostics = (
        _prepare_xmp_property_delete_write(request)
    )
    if prepared_xmp_property_delete is not None:
        return _execute_xmp_sidecar_scalar_write(
            request,
            prepared_xmp_property_delete,
            plan.diagnostics,
        )

    prepared_xmp_namespace_delete, xmp_namespace_delete_diagnostics = (
        _prepare_xmp_sidecar_namespace_delete(request)
    )
    if prepared_xmp_namespace_delete is not None:
        return _execute_xmp_sidecar_namespace_delete(
            request,
            prepared_xmp_namespace_delete,
            plan.diagnostics,
        )

    prepared_xmp_delete, xmp_delete_diagnostics = _prepare_xmp_sidecar_family2_delete(request)
    if prepared_xmp_delete is not None:
        return _execute_xmp_sidecar_family2_delete(request, prepared_xmp_delete, plan.diagnostics)

    prepared_app_segment_delete, app_segment_delete_diagnostics = (
        _prepare_jpeg_app_segment_delete_write(request)
    )
    if prepared_app_segment_delete is not None:
        return _execute_jpeg_app_segment_delete_write(
            request,
            prepared_app_segment_delete,
            plan.diagnostics,
        )
    if _has_jpeg_app_segment_delete_tags(request):
        return MetadataWriteResult(
            request=request,
            status=_status_for_deferred_diagnostics(app_segment_delete_diagnostics),
            diagnostics=(*plan.diagnostics, *app_segment_delete_diagnostics),
        )

    prepared_iptc_delete, iptc_delete_diagnostics = _prepare_jpeg_iptc_delete_write(request)
    if prepared_iptc_delete is not None:
        return _execute_jpeg_iptc_delete_write(
            request,
            prepared_iptc_delete,
            plan.diagnostics,
        )
    if _has_jpeg_iptc_delete_tags(request):
        return MetadataWriteResult(
            request=request,
            status=_status_for_deferred_diagnostics(iptc_delete_diagnostics),
            diagnostics=(*plan.diagnostics, *iptc_delete_diagnostics),
        )

    prepared_iptc_assignment, iptc_assignment_diagnostics = _prepare_jpeg_iptc_assignment_write(
        request
    )
    if prepared_iptc_assignment is not None:
        return _execute_jpeg_iptc_assignment_write(
            request,
            prepared_iptc_assignment,
            plan.diagnostics,
        )
    if _has_jpeg_iptc_assignment_tags(request):
        return MetadataWriteResult(
            request=request,
            status=_status_for_deferred_diagnostics(iptc_assignment_diagnostics),
            diagnostics=(*plan.diagnostics, *iptc_assignment_diagnostics),
        )

    prepared_vendor_jpeg, vendor_jpeg_diagnostics = _prepare_vendor_jpeg_composed_write(request)
    if prepared_vendor_jpeg is not None:
        return _execute_vendor_jpeg_composed_write(
            request,
            prepared_vendor_jpeg,
            plan.diagnostics,
        )
    if _has_vendor_jpeg_composed_write_tags(request):
        return MetadataWriteResult(
            request=request,
            status=_status_for_deferred_diagnostics(vendor_jpeg_diagnostics),
            diagnostics=(*plan.diagnostics, *vendor_jpeg_diagnostics),
        )

    if _has_public_list_mutation_assignment(request):
        prepared_iptc_list, iptc_list_diagnostics = _prepare_jpeg_iptc_keywords_list_mutation(
            request
        )
        if prepared_iptc_list is not None:
            return _execute_jpeg_iptc_keywords_list_mutation(
                request,
                prepared_iptc_list,
                plan.diagnostics,
            )
        if _has_jpeg_iptc_keywords_list_mutation_request(request):
            return MetadataWriteResult(
                request=request,
                status=_status_for_deferred_diagnostics(iptc_list_diagnostics),
                diagnostics=(*plan.diagnostics, *iptc_list_diagnostics),
            )

        prepared_xmp_list, xmp_list_diagnostics = _prepare_xmp_subject_list_mutation(request)
        if prepared_xmp_list is not None:
            return _execute_xmp_subject_list_mutation(
                request,
                prepared_xmp_list,
                plan.diagnostics,
            )
        return MetadataWriteResult(
            request=request,
            status=_status_for_deferred_diagnostics(xmp_list_diagnostics),
            diagnostics=(*plan.diagnostics, *xmp_list_diagnostics),
        )

    ordered_assign_delete_result = _execute_public_ordered_exif_assign_delete_if_supported(
        request,
        plan.diagnostics,
    )
    if ordered_assign_delete_result is not None:
        return ordered_assign_delete_result

    prepared_microsoft_xtra, microsoft_xtra_diagnostics = _prepare_quicktime_microsoft_xtra_write(
        request
    )
    if prepared_microsoft_xtra is not None:
        return _execute_quicktime_microsoft_xtra_write(
            request,
            prepared_microsoft_xtra,
            plan.diagnostics,
        )
    if _has_quicktime_microsoft_xtra_write_tags(request):
        return MetadataWriteResult(
            request=request,
            status=_status_for_deferred_diagnostics(microsoft_xtra_diagnostics),
            diagnostics=(*plan.diagnostics, *microsoft_xtra_diagnostics),
        )

    prepared_quicktime, quicktime_diagnostics = _prepare_quicktime_metadata_write(request)
    if prepared_quicktime is not None:
        return _execute_quicktime_metadata_write(request, prepared_quicktime, plan.diagnostics)
    if _has_quicktime_metadata_write_tags(request):
        return MetadataWriteResult(
            request=request,
            status=_status_for_deferred_diagnostics(quicktime_diagnostics),
            diagnostics=(*plan.diagnostics, *quicktime_diagnostics),
        )

    prepared_xmp, xmp_diagnostics = _prepare_xmp_sidecar_scalar_write(request)
    if prepared_xmp is not None:
        return _execute_xmp_sidecar_scalar_write(request, prepared_xmp, plan.diagnostics)

    prepared_jpeg_scalar, jpeg_scalar_diagnostics = _prepare_jpeg_exif_scalar_write(request)
    if prepared_jpeg_scalar is not None:
        return _execute_jpeg_exif_scalar_write(request, prepared_jpeg_scalar, plan.diagnostics)

    prepared_jpeg_gps, jpeg_gps_diagnostics = _prepare_jpeg_gps_write(request)
    if prepared_jpeg_gps is not None:
        return _execute_jpeg_gps_write(request, prepared_jpeg_gps, plan.diagnostics)

    diagnostics = _preferred_prepare_diagnostics(
        exif_copy_diagnostics,
        xmp_copy_diagnostics,
        pdf_delete_diagnostics,
        pdf_info_diagnostics,
        xmp_property_delete_diagnostics,
        xmp_namespace_delete_diagnostics,
        xmp_delete_diagnostics,
        app_segment_delete_diagnostics,
        vendor_jpeg_diagnostics,
        microsoft_xtra_diagnostics,
        quicktime_diagnostics,
        iptc_assignment_diagnostics,
        xmp_diagnostics,
        jpeg_scalar_diagnostics,
        jpeg_gps_diagnostics,
    )
    return MetadataWriteResult(
        request=request,
        status=_status_for_deferred_diagnostics(diagnostics),
        diagnostics=(*plan.diagnostics, *diagnostics),
    )


def _execute_public_copy_from_file_if_supported(
    request: MetadataWriteRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult | None:
    copy_request = request.public_copy_from_file
    if copy_request is None:
        return None
    xmp_exact_result = _execute_public_xmp_exact_copy_if_supported(
        request,
        copy_request,
        plan_diagnostics,
    )
    if xmp_exact_result is not None:
        return xmp_exact_result
    ordered_scalar_result = _execute_public_ordered_scalar_copy_write_if_supported(
        request,
        copy_request,
        plan_diagnostics,
    )
    if ordered_scalar_result is not None:
        return ordered_scalar_result
    if request.assignments or request.deletes:
        return None
    if request.xmp_sidecar_copy_from_file is not None or request.exif_sidecar_copy_from_file:
        return None
    datfile_result = _execute_public_datfile_payload_if_supported(
        request,
        copy_request,
        plan_diagnostics,
    )
    if datfile_result is not None:
        return datfile_result
    xmp_sidecar_redirect_result = _execute_public_xmp_sidecar_redirect_copy_if_supported(
        request,
        copy_request,
        plan_diagnostics,
    )
    if xmp_sidecar_redirect_result is not None:
        return xmp_sidecar_redirect_result
    scalar_result = _execute_public_scalar_copy_if_supported(
        request,
        copy_request,
        plan_diagnostics,
    )
    if scalar_result is not None:
        return scalar_result
    copied_groups = _public_copy_groups(copy_request)
    if not copied_groups:
        return None
    if copy_request.source_kind != "explicit_source":
        return None
    source_path = Path(copy_request.source)
    if not source_path.is_file():
        return None
    if not request.paths:
        return None

    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    copied_groups_by_path: JsonArray = []
    for path in request.paths:
        try:
            original_data = path.read_bytes() if path.exists() else b""
            rewritten_data = _rewrite_public_copy_target(
                original_data,
                target_path=path,
                source_path=source_path,
                copied_groups=copied_groups,
            )
            if rewritten_data != original_data:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    rewritten_data,
                    _backup_policy(request),
                )
                changed_paths.append(path)
            copied_groups_by_path.append(
                {
                    "path": path.as_posix(),
                    "groups": _json_string_array(sorted(copied_groups)),
                    "changed": rewritten_data != original_data,
                }
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="unsupported_public_copy_from_file_execution",
                    message=f"Public copy-from-file execution failed for {path}: {exc}",
                    details={
                        "path": path.as_posix(),
                        "source": source_path.as_posix(),
                        "groups": _json_string_array(sorted(copied_groups)),
                        "error": str(exc),
                        "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                    },
                )
            )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public generic copy-from-file route executed through bounded "
                    "EXIF/XMP container copy support."
                ),
                details={
                    "action": "run_modern_public_copy_from_file_executor",
                    "changed_paths": _json_string_array(path.as_posix() for path in changed_paths),
                    "source_path": source_path.as_posix(),
                    "routes": _json_string_array(route.raw for route in copy_request.routes),
                    "groups": _json_string_array(sorted(copied_groups)),
                    "copied_groups_by_path": copied_groups_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_public_scalar_copy_if_supported(
    request: MetadataWriteRequest,
    copy_request: PublicCopyFromFileRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult | None:
    if request.assignments or request.deletes:
        return None
    if copy_request.source_kind != "explicit_source" or not request.paths:
        return None
    source_path = Path(copy_request.source)
    if source_path.suffix.lower() not in _JPEG_SUFFIXES or not source_path.is_file():
        return None
    unsupported_targets = [
        path for path in request.paths if path.suffix.lower() not in _JPEG_SUFFIXES
    ]
    if unsupported_targets:
        return None

    route_copies: list[
        tuple[PublicCopyFromFileRouteRequest, _PublicExifScalarTag, _PublicExifScalarTag]
    ] = []
    for route in sorted(copy_request.routes, key=lambda item: item.order_index):
        route_expansion = _public_scalar_copy_route_expansion(route)
        if route_expansion is None:
            return None
        route_copies.extend(route_expansion)

    if not route_copies:
        return None

    try:
        source_group_values = _read_public_jpeg_exif_scalar_group_values(source_path)
        route_copies = _existing_public_scalar_route_copies(source_group_values, route_copies)
        if not route_copies:
            return None
        source_values = _public_scalar_values_for_selector(source_group_values, "EXIF:*")
        values = _scalar_copy_values_from_routes(source_values, route_copies)
        scalar_plan = _build_public_exif_scalar_plan_from_values(values)
    except (OSError, ValueError) as exc:
        return _unsupported_public_scalar_copy_result(
            request,
            plan_diagnostics,
            source_path,
            route_copies,
            exc,
        )

    prepared = _PreparedJpegExifScalarWrite(
        paths=request.paths,
        plan=scalar_plan,
        backup_policy=_backup_policy(request),
        tags=tuple(destination_tag for _, _, destination_tag in route_copies),
    )
    result = _execute_jpeg_exif_scalar_write(request, prepared, plan_diagnostics)
    return replace(
        result,
        diagnostics=(
            *result.diagnostics[:-1],
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public redirected scalar copy-from-file route executed through the "
                    "package-local JPEG EXIF scalar writer."
                ),
                details={
                    "action": "run_modern_public_scalar_copy_from_file_executor",
                    "native_callable": (
                        "exifmodern.formats.jpeg.exif_scalar_writer."
                        "rewrite_jpeg_file_exif_scalars_in_place"
                    ),
                    "changed_paths": [path.as_posix() for path in result.changed_paths],
                    "source_path": source_path.as_posix(),
                    "routes": _json_string_array(_route_copies_raw_routes(route_copies)),
                    "copied_tags": [
                        {
                            "source_selector": source_tag,
                            "destination_selector": destination_tag,
                        }
                        for _, source_tag, destination_tag in route_copies
                    ],
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                },
            ),
        ),
    )


def _execute_public_ordered_scalar_copy_write_if_supported(
    request: MetadataWriteRequest,
    copy_request: PublicCopyFromFileRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult | None:
    if (
        not request.assignments
        and not request.deletes
        and not _public_copy_routes_need_ordered_exif_executor(copy_request)
    ):
        return None
    if request.xmp_sidecar_copy_from_file is not None or request.exif_sidecar_copy_from_file:
        return None
    if not request.paths:
        return None
    target_diagnostic = _public_ordered_exif_target_diagnostic(request.paths)
    if target_diagnostic is not None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, target_diagnostic),
        )
    if any(not _public_ordered_exif_path_is_supported_target(path) for path in request.paths):
        return None
    order_diagnostic = _public_ordered_scalar_request_order_diagnostic(request)
    if order_diagnostic is not None:
        return None
    if (request.assignments or request.deletes) and any(
        route.kind == "implicit_all" for route in copy_request.routes
    ):
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                *plan_diagnostics,
                _unsupported_ordered_scalar_copy_write_diagnostic(
                    "unsupported_public_ordered_scalar_copy_route",
                    (
                        "Public ordered EXIF copy/write keeps mixed implicit All routes "
                        "deferred; pure implicit All copy is bounded to the safe "
                        "JPEG EXIF scalar/GPS allowlist."
                    ),
                    "<implicit All copy route>",
                ),
            ),
        )

    return _execute_public_ordered_exif_copy_write(
        request=request,
        copy_request=copy_request,
        plan_diagnostics=plan_diagnostics,
    )


def _public_copy_routes_need_ordered_exif_executor(
    copy_request: PublicCopyFromFileRequest,
) -> bool:
    if copy_request.source_kind == "current_target" or copy_request.alternate_files:
        return any(route.kind != "datfile_payload" for route in copy_request.routes)
    if copy_request.source_kind == "explicit_source":
        source_format_support = alternate_file_format_support(copy_request.source)
        if source_format_support.filename_percent_codes or source_format_support.tag_interpolation:
            return any(route.kind != "datfile_payload" for route in copy_request.routes)
    return any(
        route.kind == "implicit_all" or _public_gps_copy_route_kind(route) != "unsupported"
        for route in copy_request.routes
    )


def _public_ordered_exif_no_effect_result(
    request: MetadataWriteRequest,
    copy_request: PublicCopyFromFileRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public ordered EXIF copy/write request matched no supported source tags."
                ),
                details={
                    "action": "run_modern_public_ordered_exif_copy_write_executor",
                    "changed_paths": [],
                    "source": copy_request.source,
                    "source_kind": copy_request.source_kind,
                    "alternate_files": _public_copy_alternate_files_json(
                        copy_request.alternate_files
                    ),
                    "routes": _json_string_array(route.raw for route in copy_request.routes),
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                },
            ),
        ),
    )


def _execute_public_ordered_exif_copy_write(
    *,
    request: MetadataWriteRequest,
    copy_request: PublicCopyFromFileRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    prepared_targets: list[_PublicOrderedExifTargetPlan] = []
    for path in request.paths:
        effects_result = _public_ordered_exif_effects(
            request,
            copy_request,
            target_path=path,
        )
        if isinstance(effects_result, Diagnostic):
            return MetadataWriteResult(
                request=request,
                status="not_yet_implemented",
                diagnostics=(*plan_diagnostics, effects_result),
            )
        ordered_effects = tuple(
            sorted(
                effects_result,
                key=lambda effect: (effect.order_index, effect.sequence_index),
            )
        )
        try:
            scalar_plan, gps_plan = _public_ordered_exif_plans_from_effects(ordered_effects)
        except ValueError as exc:
            return MetadataWriteResult(
                request=request,
                status="not_yet_implemented",
                diagnostics=(
                    *plan_diagnostics,
                    Diagnostic(
                        code="unsupported_public_ordered_exif_copy_write_value",
                        message=f"Public ordered EXIF copy/write request was rejected: {exc}",
                        details={
                            "path": path.as_posix(),
                            "error": str(exc),
                            "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                        },
                    ),
                ),
            )
        prepared_targets.append(
            _PublicOrderedExifTargetPlan(
                path=path,
                scalar_plan=scalar_plan,
                gps_plan=gps_plan,
                ordered_effects=ordered_effects,
            )
        )
    if not any(
        target.scalar_plan is not None or target.gps_plan is not None for target in prepared_targets
    ):
        return _public_ordered_exif_no_effect_result(request, copy_request, plan_diagnostics)

    prepared_rewrites: list[_PreparedPublicOrderedExifRewrite] = []
    execution_diagnostics: list[Diagnostic] = []
    for target in prepared_targets:
        path = target.path
        try:
            original_data = path.read_bytes()
            rewritten_data = original_data
            if target.scalar_plan is not None:
                if path.suffix.lower() in _TIFF_SUFFIXES:
                    rewritten_data = rewrite_tiff_exif_scalars_creating_if_needed(
                        rewritten_data,
                        target.scalar_plan,
                    ).data
                else:
                    rewritten_data = rewrite_jpeg_exif_scalars_creating_if_needed(
                        rewritten_data,
                        target.scalar_plan,
                    ).data
            if target.gps_plan is not None:
                if path.suffix.lower() in _TIFF_SUFFIXES:
                    rewritten_data = rewrite_gps_ifd_creating_if_needed(
                        rewritten_data,
                        target.gps_plan,
                    )
                else:
                    rewritten_data = rewrite_jpeg_exif_gps_creating_if_needed(
                        rewritten_data,
                        target.gps_plan,
                    ).data
            prepared_rewrites.append(
                _PreparedPublicOrderedExifRewrite(
                    path=path,
                    data=rewritten_data,
                    changed=rewritten_data != original_data,
                    surface=(
                        "tiff_ifd_rewrite"
                        if path.suffix.lower() in _TIFF_SUFFIXES
                        else "jpeg_exif_app1_rewrite"
                    ),
                )
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native ordered public EXIF copy/write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=(),
        )

    changed_paths: list[Path] = []
    for prepared_rewrite in prepared_rewrites:
        if prepared_rewrite.changed:
            _write_rewritten_bytes_transactionally(
                request,
                prepared_rewrite.path,
                prepared_rewrite.data,
                _backup_policy(request),
            )
            changed_paths.append(prepared_rewrite.path)

    scalar_only = all(target.gps_plan is None for target in prepared_targets)
    if not copy_request.routes:
        action = (
            "run_modern_public_ordered_scalar_assign_delete_executor"
            if scalar_only
            else "run_modern_public_ordered_exif_assign_delete_executor"
        )
    else:
        action = (
            "run_modern_public_ordered_scalar_copy_write_executor"
            if scalar_only
            else "run_modern_public_ordered_exif_copy_write_executor"
        )
    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            *_public_ordered_exif_subset_diagnostics(copy_request),
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public ordered assignment/delete/copy-from-file request executed through "
                    "bounded package-local JPEG EXIF scalar and GPS writers."
                ),
                details={
                    "action": action,
                    "native_callables": [
                        "exifmodern.formats.jpeg.exif_scalar_writer."
                        "rewrite_jpeg_exif_scalars_creating_if_needed",
                        "exifmodern.formats.jpeg.exif_gps_writer."
                        "rewrite_jpeg_exif_gps_creating_if_needed",
                        "exifmodern.formats.tiff.exif_scalar_file_writer."
                        "rewrite_tiff_exif_scalars_creating_if_needed",
                        "exifmodern.formats.tiff.gps_rewriter.rewrite_gps_ifd_creating_if_needed",
                    ],
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "source": copy_request.source,
                    "source_kind": copy_request.source_kind,
                    "destination_surfaces_by_path": [
                        {
                            "path": prepared_rewrite.path.as_posix(),
                            "surface": prepared_rewrite.surface,
                            "changed": prepared_rewrite.changed,
                        }
                        for prepared_rewrite in prepared_rewrites
                    ],
                    "ordered_operations": [
                        {
                            "order_index": effect.order_index,
                            "operation": effect.operation,
                            "tag": effect.tag,
                            "route": effect.route,
                        }
                        for target in prepared_targets
                        for effect in target.ordered_effects
                    ],
                    "alternate_files": _public_copy_alternate_files_json(
                        copy_request.alternate_files
                    ),
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_tiff_ordered_write_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_public_ordered_exif_assign_delete_if_supported(
    request: MetadataWriteRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult | None:
    if not request.assignments and not request.deletes:
        return None
    if request.public_copy_from_file is not None:
        return None
    if request.xmp_sidecar_copy_from_file is not None or request.exif_sidecar_copy_from_file:
        return None
    if not request.paths:
        return None
    target_diagnostic = _public_ordered_exif_target_diagnostic(request.paths)
    if target_diagnostic is not None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, target_diagnostic),
        )
    if any(not _public_ordered_exif_path_is_supported_target(path) for path in request.paths):
        return None
    if not request.deletes and all(path.suffix.lower() in _JPEG_SUFFIXES for path in request.paths):
        return None
    execution_request = _public_ordered_exif_request_with_default_assignment_order(request)
    order_diagnostic = _public_ordered_scalar_request_order_diagnostic(request)
    if order_diagnostic is not None and execution_request is not request:
        order_diagnostic = _public_ordered_scalar_request_order_diagnostic(execution_request)
    if order_diagnostic is not None:
        return None
    return _execute_public_ordered_exif_copy_write(
        request=execution_request,
        copy_request=PublicCopyFromFileRequest(
            source="@",
            source_kind="current_target",
            routes=(),
        ),
        plan_diagnostics=plan_diagnostics,
    )


def _public_ordered_exif_path_is_supported_target(path: Path) -> bool:
    return path.suffix.lower() in (_JPEG_SUFFIXES | _TIFF_SUFFIXES)


def _public_ordered_exif_request_with_default_assignment_order(
    request: MetadataWriteRequest,
) -> MetadataWriteRequest:
    if request.deletes or not request.assignments:
        return request
    if all(assignment.order_index is not None for assignment in request.assignments):
        return request
    return replace(
        request,
        assignments=tuple(
            replace(assignment, order_index=index)
            for index, assignment in enumerate(request.assignments)
        ),
    )


def _public_ordered_exif_target_diagnostic(paths: tuple[Path, ...]) -> Diagnostic | None:
    blockers: JsonArray = []
    for path in paths:
        suffix = path.suffix.lower()
        if suffix in _TIFF_SUFFIXES and _path_is_bigtiff(path):
            blockers.append(
                {
                    "path": path.as_posix(),
                    "suffix": suffix,
                    "destination_class": "bigtiff",
                    "blocker_code": "bigtiff_destination_write_rejected_by_exiftool",
                    "detail": (
                        "ExifTool reads BigTIFF IFD metadata but rejects BigTIFF writes; "
                        "this public ordered EXIF executor owns only classic TIFF."
                    ),
                }
            )
    if not blockers:
        return None
    return Diagnostic(
        code="unsupported_public_ordered_exif_destination_writer",
        message=(
            "Public ordered EXIF assignment/delete/copy cannot write one or more "
            "TIFF-family targets with the selected destination writer."
        ),
        details={
            "destination_blockers": blockers,
            "supported_destination_suffixes": _json_string_array(
                sorted(_JPEG_SUFFIXES | _TIFF_SUFFIXES)
            ),
            "evidence_ids": _public_tiff_ordered_write_evidence_ids_json(),
        },
    )


def _public_ordered_exif_subset_diagnostics(
    copy_request: PublicCopyFromFileRequest,
) -> tuple[Diagnostic, ...]:
    if not any(route.kind == "implicit_all" for route in copy_request.routes):
        return ()
    return (
        Diagnostic(
            code="bounded_public_implicit_all_copy_exclusions",
            message=(
                "Public implicit All copy executed only the source-backed JPEG EXIF "
                "scalar/GPS allowlist; other groups remain excluded."
            ),
            details={
                "copied_subset": [
                    "EXIF:Artist",
                    "EXIF:ImageDescription",
                    "EXIF:Orientation",
                    "EXIF:ModifyDate",
                    "EXIF:DateTimeOriginal",
                    "EXIF:ISO",
                    "EXIF:FocalLength",
                    "EXIF:SceneCaptureType",
                    "GPS:GPSLatitude",
                    "GPS:GPSLatitudeRef",
                    "GPS:GPSLongitude",
                    "GPS:GPSLongitudeRef",
                ],
                "excluded_groups": [
                    "XMP",
                    "IPTC",
                    "MakerNotes",
                    "binary/protected tags",
                    "list tags",
                    "non-scalar structures",
                ],
                "evidence_ids": _public_copy_from_file_evidence_ids_json(),
            },
        ),
    )


def _public_ordered_scalar_request_order_diagnostic(
    request: MetadataWriteRequest,
) -> Diagnostic | None:
    unordered_assignments: JsonArray = [
        assignment.tag for assignment in request.assignments if assignment.order_index is None
    ]
    delete_order_count = len(request.delete_order_indexes)
    if unordered_assignments or (request.deletes and delete_order_count != len(request.deletes)):
        return Diagnostic(
            code="unsupported_public_ordered_scalar_copy_write_ordering",
            message=(
                "Public mixed scalar assignment/delete/copy execution requires explicit "
                "order indexes for every assignment and delete so ExifTool command order is "
                "not guessed."
            ),
            details={
                "unordered_assignments": unordered_assignments,
                "delete_count": len(request.deletes),
                "delete_order_index_count": delete_order_count,
                "evidence_ids": _public_copy_from_file_evidence_ids_json(),
            },
        )
    return None


def _public_ordered_exif_effects(
    request: MetadataWriteRequest,
    copy_request: PublicCopyFromFileRequest,
    *,
    target_path: Path,
) -> tuple[_PublicOrderedExifEffect, ...] | Diagnostic:
    effects: list[_PublicOrderedExifEffect] = []
    sequence_index = 0
    copy_effects = _public_ordered_exif_copy_effects(
        copy_request,
        sequence_index,
        target_path=target_path,
    )
    if isinstance(copy_effects, Diagnostic):
        return copy_effects
    effects.extend(copy_effects)
    sequence_index += len(copy_effects)

    for assignment in request.assignments:
        if assignment.order_index is None:
            continue
        if assignment.operation != "set":
            return _unsupported_ordered_scalar_copy_write_diagnostic(
                "unsupported_public_ordered_exif_assignment_operation",
                (
                    "Public ordered EXIF copy/write keeps list add/delete operations "
                    "deferred; this bounded executor handles scalar set/delete only."
                ),
                assignment.tag,
            )
        scalar_tag = _public_datfile_destination_scalar_tag_or_none(assignment.tag)
        gps_tag = _public_gps_tag_or_none(assignment.tag)
        if scalar_tag is None and gps_tag is None:
            return _unsupported_ordered_scalar_copy_write_diagnostic(
                "unsupported_public_ordered_exif_assignment_tag",
                (
                    "Public ordered EXIF copy/write supports only bounded JPEG EXIF "
                    "scalar and GPS coordinate assignments."
                ),
                assignment.tag,
            )
        if scalar_tag is not None:
            effects.append(
                _PublicOrderedScalarEffect(
                    order_index=assignment.order_index,
                    sequence_index=sequence_index,
                    operation="upsert",
                    tag=scalar_tag,
                    value=assignment.value,
                    route=f"{assignment.tag}=",
                )
            )
        elif gps_tag is not None:
            effects.append(
                _PublicOrderedGpsEffect(
                    order_index=assignment.order_index,
                    sequence_index=sequence_index,
                    operation="upsert",
                    tag=gps_tag,
                    value=str(assignment.value),
                    route=f"{assignment.tag}=",
                )
            )
        sequence_index += 1

    for delete_index, delete in zip(request.delete_order_indexes, request.deletes, strict=True):
        scalar_tag = _public_datfile_destination_scalar_tag_or_none(delete)
        gps_tag = _public_gps_tag_or_none(delete)
        if scalar_tag is None and gps_tag is None:
            return _unsupported_ordered_scalar_copy_write_diagnostic(
                "unsupported_public_ordered_exif_delete_tag",
                (
                    "Public ordered EXIF copy/write supports only bounded JPEG EXIF "
                    "scalar/GPS deletes."
                ),
                delete,
            )
        if scalar_tag is not None:
            effects.append(
                _PublicOrderedScalarEffect(
                    order_index=delete_index,
                    sequence_index=sequence_index,
                    operation="delete",
                    tag=scalar_tag,
                    value=None,
                    route=f"{delete}=",
                )
            )
        elif gps_tag is not None:
            effects.append(
                _PublicOrderedGpsEffect(
                    order_index=delete_index,
                    sequence_index=sequence_index,
                    operation="delete",
                    tag=gps_tag,
                    value=None,
                    route=f"{delete}=",
                )
            )
        sequence_index += 1
    return tuple(effects)


def _public_ordered_exif_plans_from_effects(
    ordered_effects: tuple[_PublicOrderedExifEffect, ...],
) -> tuple[ExifScalarWritePlan | None, ExifGpsWritePlan | None]:
    values: dict[_PublicExifScalarTag, _PublicExifScalarValue] = {}
    deleted_tags: set[_PublicExifScalarTag] = set()
    gps_values: dict[_PublicGpsCoreTag, _PublicGpsValue] = {}
    deleted_gps_tags: set[_PublicGpsCoreTag] = set()
    for effect in ordered_effects:
        if isinstance(effect, _PublicOrderedScalarEffect):
            if effect.operation == "delete":
                values.pop(effect.tag, None)
                deleted_tags.add(effect.tag)
                continue
            if effect.value is None:
                raise ValueError(f"ordered scalar effect for {effect.tag} has no value")
            values[effect.tag] = effect.value
            deleted_tags.discard(effect.tag)
            continue
        if effect.operation == "delete":
            gps_values.pop(effect.tag, None)
            deleted_gps_tags.add(effect.tag)
            continue
        if effect.value is None:
            raise ValueError(f"ordered GPS effect for {effect.tag} has no value")
        gps_values[effect.tag] = effect.value
        deleted_gps_tags.discard(effect.tag)

    scalar_plan = (
        _public_exif_scalar_plan_from_values_and_deletes(values, deleted_tags)
        if values or deleted_tags
        else None
    )
    gps_plan = (
        _public_gps_plan_from_values_and_deletes(gps_values, deleted_gps_tags)
        if gps_values or deleted_gps_tags
        else None
    )
    return scalar_plan, gps_plan


def _public_ordered_exif_copy_effects(
    copy_request: PublicCopyFromFileRequest,
    initial_sequence_index: int,
    *,
    target_path: Path,
) -> tuple[_PublicOrderedExifEffect, ...] | Diagnostic:
    effects: list[_PublicOrderedExifEffect] = []
    source_cache: dict[Path, _PublicOrderedExifSourceValues] = {}

    sequence_index = initial_sequence_index
    for route in sorted(copy_request.routes, key=lambda item: item.order_index):
        if route.kind == "datfile_payload":
            datfile_effect = _public_ordered_scalar_datfile_effect(route, sequence_index)
            if isinstance(datfile_effect, Diagnostic):
                return datfile_effect
            effects.append(datfile_effect)
            sequence_index += 1
            continue
        source_result = _public_ordered_exif_source_values_for_route(
            copy_request=copy_request,
            route=route,
            target_path=target_path,
            source_cache=source_cache,
        )
        if isinstance(source_result, Diagnostic):
            return source_result
        source_route, source_values = source_result
        gps_effects = _public_ordered_gps_copy_effects(
            source_route,
            source_values.gps_values,
            sequence_index,
        )
        if isinstance(gps_effects, Diagnostic):
            return gps_effects
        if gps_effects or route.kind == "implicit_all":
            effects.extend(gps_effects)
            sequence_index += len(gps_effects)
            if route.kind == "implicit_all":
                scalar_effects = _public_ordered_implicit_all_scalar_copy_effects(
                    source_route,
                    source_values.scalar_group_values,
                    sequence_index,
                )
                effects.extend(scalar_effects)
                sequence_index += len(scalar_effects)
            continue
        route_expansion = _public_scalar_copy_route_expansion(source_route)
        if route_expansion is None:
            return _unsupported_ordered_scalar_copy_write_diagnostic(
                "unsupported_public_ordered_scalar_copy_route",
                "Public ordered EXIF copy/write supports only bounded JPEG EXIF scalar/GPS routes.",
                route.raw,
            )
        for _route, source_tag, destination_tag in route_expansion:
            route_source_values = _public_scalar_values_for_selector(
                source_values.scalar_group_values,
                source_route.source_selector,
            )
            value = route_source_values.get(source_tag)
            if value is None:
                if _public_scalar_source_selector_is_pattern(source_route.source_selector):
                    continue
                return _unsupported_ordered_scalar_copy_write_diagnostic(
                    "unsupported_public_ordered_scalar_copy_missing_source_tag",
                    "Public ordered scalar copy/write source tag is missing.",
                    route.raw,
                )
            effects.append(
                _PublicOrderedScalarEffect(
                    order_index=route.order_index,
                    sequence_index=sequence_index,
                    operation="upsert",
                    tag=destination_tag,
                    value=value,
                    route=route.raw,
                )
            )
            sequence_index += 1
    return tuple(effects)


def _public_ordered_exif_source_values_for_route(
    *,
    copy_request: PublicCopyFromFileRequest,
    route: PublicCopyFromFileRouteRequest,
    target_path: Path,
    source_cache: dict[Path, _PublicOrderedExifSourceValues],
) -> tuple[PublicCopyFromFileRouteRequest, _PublicOrderedExifSourceValues] | Diagnostic:
    route_result = _public_route_with_resolved_alternate_source_selector(
        copy_request,
        route,
    )
    if isinstance(route_result, Diagnostic):
        return route_result
    source_route, alternate = route_result
    source_path_result = _public_ordered_exif_source_path(
        copy_request=copy_request,
        route=source_route,
        alternate=alternate,
        target_path=target_path,
    )
    if isinstance(source_path_result, Diagnostic):
        return source_path_result
    source_path = source_path_result
    cached = source_cache.get(source_path)
    if cached is not None:
        return source_route, cached
    if (
        source_path.suffix.lower() not in (_JPEG_SUFFIXES | _TIFF_SUFFIXES)
        or not source_path.is_file()
    ):
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_exif_copy_source",
            "Public ordered EXIF copy/write requires an existing JPEG or classic TIFF copy source.",
            source_path.as_posix(),
        )
    if source_path.suffix.lower() in _TIFF_SUFFIXES and _path_is_bigtiff(source_path):
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_exif_copy_source",
            (
                "Public ordered EXIF copy/write keeps BigTIFF writes blocked; BigTIFF "
                "is not accepted as an ordered copy source in this TIFF destination slice."
            ),
            source_path.as_posix(),
        )
    try:
        source_values = _PublicOrderedExifSourceValues(
            source_path=source_path,
            scalar_group_values=_read_public_exif_scalar_group_values(source_path),
            gps_values=_read_public_gps_core_values(source_path),
        )
    except (OSError, ValueError) as exc:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_exif_copy_source",
            f"Public ordered EXIF copy/write could not read the copy source: {exc}",
            source_path.as_posix(),
        )
    source_cache[source_path] = source_values
    return source_route, source_values


def _public_route_with_resolved_alternate_source_selector(
    copy_request: PublicCopyFromFileRequest,
    route: PublicCopyFromFileRouteRequest,
) -> tuple[PublicCopyFromFileRouteRequest, PublicCopyFromFileAlternateFile | None] | Diagnostic:
    destination_alternate = _public_alternate_selector_part(route.destination_selector)
    if destination_alternate is not None:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_exif_alternate_destination",
            "Public ordered EXIF copy/write cannot write destination tags into FileNUM groups.",
            route.raw,
        )
    source_alternate = _public_alternate_selector_part(route.source_selector)
    if source_alternate is None:
        return route, None
    slot, stripped_selector = source_alternate
    alternate = _public_copy_alternate_file_for_slot(copy_request, slot)
    if alternate is None:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_exif_alternate_source",
            (
                "Public ordered EXIF copy/write FileNUM source selectors require "
                "a matching -fileNUM path."
            ),
            route.raw,
        )
    return replace(route, source_selector=stripped_selector), alternate


def _public_ordered_exif_source_path(
    *,
    copy_request: PublicCopyFromFileRequest,
    route: PublicCopyFromFileRouteRequest,
    alternate: PublicCopyFromFileAlternateFile | None,
    target_path: Path,
) -> Path | Diagnostic:
    if alternate is not None:
        format_support = alternate_file_format_support(alternate.path.as_posix())
        if format_support.tag_interpolation:
            return _public_ordered_exif_interpolated_source_path(
                raw_path=alternate.path,
                target_path=target_path,
                diagnostic_code="unsupported_public_ordered_exif_alternate_source_format",
            )
        if format_support.source_alias:
            return target_path
        if format_support.filename_percent_codes:
            formatted_path = resolve_alternate_file_path(alternate.path, target_path)
            if not formatted_path.is_file():
                return _unsupported_ordered_scalar_copy_write_diagnostic(
                    "unsupported_public_ordered_exif_alternate_source_format",
                    (
                        "Public ordered EXIF copy/write resolved the ExifTool filename "
                        "percent formatted alternate-file source, but the resolved JPEG "
                        "source does not exist."
                    ),
                    alternate.path.as_posix(),
                )
            return formatted_path
        return alternate.path
    if route.kind == "implicit_all" or route.kind in {"selector", "redirect_selector"}:
        if copy_request.source_kind == "explicit_source":
            format_support = alternate_file_format_support(copy_request.source)
            if format_support.tag_interpolation:
                return _public_ordered_exif_interpolated_source_path(
                    raw_path=Path(copy_request.source),
                    target_path=target_path,
                    diagnostic_code="unsupported_public_ordered_exif_copy_source_format",
                )
            if format_support.filename_percent_codes:
                return resolve_alternate_file_path(Path(copy_request.source), target_path)
            return Path(copy_request.source)
        if copy_request.source_kind == "current_target":
            return target_path
    return _unsupported_ordered_scalar_copy_write_diagnostic(
        "unsupported_public_ordered_exif_copy_source",
        (
            "Public ordered EXIF copy/write supports explicit JPEG sources, @ current "
            "target sources, DATFILE payload routes, and bounded FileNUM alternate sources."
        ),
        copy_request.source,
    )


def _public_ordered_exif_interpolated_source_path(
    *,
    raw_path: Path,
    target_path: Path,
    diagnostic_code: str,
) -> Path | Diagnostic:
    try:
        tag_values = _public_insert_tag_values_for_target(target_path)
    except (OSError, ValueError) as exc:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            diagnostic_code,
            (
                "Public ordered EXIF copy/write could not read target tags for source "
                f"path interpolation: {exc}"
            ),
            raw_path.as_posix(),
        )
    issues = public_insert_tag_interpolation_issues(raw_path.as_posix(), tag_values=tag_values)
    if issues:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            diagnostic_code,
            (
                "Public ordered EXIF copy/write supports source path $tag interpolation "
                "only for existing scalar EXIF target values; arbitrary Perl expressions, "
                "missing tags, and non-scalar values remain terminal public-runtime seams."
            ),
            raw_path.as_posix(),
        )
    unsafe_tokens = _public_unsafe_interpolated_path_tokens(raw_path, tag_values)
    if unsafe_tokens:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            diagnostic_code,
            (
                "Public ordered EXIF copy/write rejected source path $tag interpolation "
                "because a substituted scalar value would introduce a path separator or "
                "relative traversal segment."
            ),
            raw_path.as_posix(),
        )
    resolved_path = resolve_alternate_file_path(raw_path, target_path, tag_values=tag_values)
    if not resolved_path.is_file():
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            diagnostic_code,
            (
                "Public ordered EXIF copy/write resolved the ExifTool $tag-interpolated "
                "source path, but the resolved source does not exist."
            ),
            raw_path.as_posix(),
        )
    return resolved_path


def _public_insert_tag_values_for_target(
    target_path: Path,
) -> tuple[PublicInsertTagValue, ...]:
    scalar_groups = _read_public_exif_scalar_group_values(target_path)
    values: dict[str, _PublicExifScalarValue] = {}
    for group in ("ifd0", "exififd", "exif"):
        for tag, value in scalar_groups.get(group, {}).items():
            values[tag] = value
    return tuple(PublicInsertTagValue(tag, value) for tag, value in values.items())


def _public_unsafe_interpolated_path_tokens(
    raw_path: Path,
    tag_values: tuple[PublicInsertTagValue, ...],
) -> tuple[str, ...]:
    unsafe_tokens: list[str] = []
    for token in public_insert_tag_value_tokens(raw_path.as_posix()):
        value = _public_insert_tag_text_for_token(token, tag_values)
        if value is not None and _public_insert_tag_path_value_is_unsafe(value):
            unsafe_tokens.append(token)
    return tuple(unsafe_tokens)


def _public_insert_tag_text_for_token(
    token: str,
    tag_values: tuple[PublicInsertTagValue, ...],
) -> str | None:
    normalized = token.removesuffix("#").casefold()
    for tag_value in tag_values:
        if tag_value.token.removesuffix("#").casefold() == normalized:
            return str(tag_value.value)
    return None


def _public_insert_tag_path_value_is_unsafe(value: str) -> bool:
    if "/" in value or "\\" in value:
        return True
    return value in {"", ".", ".."}


def _public_alternate_selector_part(selector: str | None) -> tuple[int, str] | None:
    if selector is None:
        return None
    parts = selector.strip().split(":")
    if len(parts) < 2:
        return None
    slot = _public_alternate_slot_for_group(parts[0])
    if slot is None:
        return None
    stripped_selector = ":".join(parts[1:]).strip()
    if not stripped_selector:
        return None
    return slot, stripped_selector


def _public_alternate_slot_for_group(group: str) -> int | None:
    normalized = group.lower()
    if not normalized.startswith("file"):
        return None
    slot_text = normalized.removeprefix("file")
    if slot_text in {"1", "2", "3", "4", "5"}:
        return int(slot_text)
    return None


def _public_copy_alternate_file_for_slot(
    copy_request: PublicCopyFromFileRequest,
    slot: int,
) -> PublicCopyFromFileAlternateFile | None:
    for alternate in copy_request.alternate_files:
        if alternate.slot == slot:
            return alternate
    return None


def _public_ordered_scalar_datfile_effect(
    route: PublicCopyFromFileRouteRequest,
    sequence_index: int,
) -> _PublicOrderedExifEffect | Diagnostic:
    if route.destination_selector is None or route.datfile_path is None:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_scalar_datfile_route",
            "Public ordered scalar copy/write DATFILE routes require a destination and path.",
            route.raw,
        )
    scalar_tag = _public_datfile_destination_scalar_tag_or_none(route.destination_selector)
    gps_tag = _public_datfile_destination_gps_tag_or_none(route.destination_selector)
    if scalar_tag is None and gps_tag is None:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_scalar_datfile_route",
            (
                "Public ordered scalar copy/write DATFILE routes support only JPEG EXIF "
                "scalars and bounded GPS coordinate/ref tags."
            ),
            route.raw,
        )
    try:
        value = route.datfile_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_scalar_datfile_encoding",
            "Public ordered scalar copy/write DATFILE payloads are bounded to UTF-8 text.",
            route.datfile_path.as_posix(),
        )
    except OSError as exc:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_scalar_datfile_source",
            f"Public ordered scalar copy/write DATFILE payload could not be read: {exc}",
            route.datfile_path.as_posix(),
        )
    if gps_tag is not None:
        return _PublicOrderedGpsEffect(
            order_index=route.order_index,
            sequence_index=sequence_index,
            operation="upsert",
            tag=gps_tag,
            value=value,
            route=route.raw,
        )
    if scalar_tag is None:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_scalar_datfile_route",
            "Public ordered scalar copy/write DATFILE route did not resolve to a scalar tag.",
            route.raw,
        )
    return _PublicOrderedScalarEffect(
        order_index=route.order_index,
        sequence_index=sequence_index,
        operation="upsert",
        tag=scalar_tag,
        value=value,
        route=route.raw,
    )


def _public_ordered_implicit_all_scalar_copy_effects(
    route: PublicCopyFromFileRouteRequest,
    source_group_values: dict[str, dict[_PublicExifScalarTag, _PublicExifScalarValue]],
    initial_sequence_index: int,
) -> tuple[_PublicOrderedScalarEffect, ...]:
    source_values = _public_scalar_values_for_selector(source_group_values, "EXIF:*")
    effects: list[_PublicOrderedScalarEffect] = []
    sequence_index = initial_sequence_index
    for tag, value in sorted(source_values.items()):
        effects.append(
            _PublicOrderedScalarEffect(
                order_index=route.order_index,
                sequence_index=sequence_index,
                operation="upsert",
                tag=tag,
                value=value,
                route=route.raw,
            )
        )
        sequence_index += 1
    return tuple(effects)


def _public_ordered_gps_copy_effects(
    route: PublicCopyFromFileRouteRequest,
    source_values: dict[_PublicGpsCoreTag, _PublicGpsValue],
    initial_sequence_index: int,
) -> tuple[_PublicOrderedGpsEffect, ...] | Diagnostic:
    if route.kind == "implicit_all":
        return _public_gps_wildcard_copy_effects(route, source_values, initial_sequence_index)
    route_kind = _public_gps_copy_route_kind(route)
    if route_kind == "unsupported":
        return ()
    if route.kind == "selector" and route.source_selector is not None:
        return _public_gps_selector_copy_effects(
            route=route,
            source_selector=route.source_selector,
            destination_selector=None,
            source_values=source_values,
            initial_sequence_index=initial_sequence_index,
        )
    if (
        route.kind == "redirect_selector"
        and route.source_selector is not None
        and route.destination_selector is not None
    ):
        return _public_gps_selector_copy_effects(
            route=route,
            source_selector=route.source_selector,
            destination_selector=route.destination_selector,
            source_values=source_values,
            initial_sequence_index=initial_sequence_index,
        )
    return _unsupported_ordered_scalar_copy_write_diagnostic(
        "unsupported_public_ordered_gps_copy_route",
        "Public ordered GPS copy routes require source and destination selectors.",
        route.raw,
    )


def _public_gps_selector_copy_effects(
    *,
    route: PublicCopyFromFileRouteRequest,
    source_selector: str,
    destination_selector: str | None,
    source_values: dict[_PublicGpsCoreTag, _PublicGpsValue],
    initial_sequence_index: int,
) -> tuple[_PublicOrderedGpsEffect, ...] | Diagnostic:
    source_tag = _public_gps_tag_or_none(source_selector)
    if source_tag is not None:
        destination_tag = source_tag
        if destination_selector is not None:
            parsed_destination_tag = _public_gps_tag_or_none(destination_selector)
            if parsed_destination_tag is None:
                return _unsupported_ordered_scalar_copy_write_diagnostic(
                    "unsupported_public_ordered_gps_redirect",
                    "Public ordered GPS copy redirects require GPS destination tags.",
                    route.raw,
                )
            destination_tag = parsed_destination_tag
        return _public_gps_exact_copy_effects(
            route=route,
            source_tag=source_tag,
            destination_tag=destination_tag,
            source_values=source_values,
            initial_sequence_index=initial_sequence_index,
        )

    source_tags = _public_gps_supported_selector_tags(source_selector)
    if not source_tags:
        return ()
    if destination_selector is not None and not _public_gps_destination_preserves_source_tag(
        destination_selector
    ):
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_gps_redirect",
            "Public ordered GPS wildcard redirects require a GPS wildcard destination.",
            route.raw,
        )
    return _public_gps_wildcard_copy_effects(
        route,
        source_values,
        initial_sequence_index,
        selected_tags=source_tags,
    )


def _public_gps_exact_copy_effects(
    *,
    route: PublicCopyFromFileRouteRequest,
    source_tag: _PublicGpsCoreTag,
    destination_tag: _PublicGpsCoreTag,
    source_values: dict[_PublicGpsCoreTag, _PublicGpsValue],
    initial_sequence_index: int,
) -> tuple[_PublicOrderedGpsEffect, ...] | Diagnostic:
    source_coordinate_tag = _gps_coordinate_tag_or_none(source_tag)
    destination_coordinate_tag = _gps_coordinate_tag_or_none(destination_tag)
    if source_coordinate_tag is not None and destination_coordinate_tag is not None:
        return _public_gps_coordinate_pair_copy_effects(
            route=route,
            source_coordinate_tag=source_coordinate_tag,
            destination_coordinate_tag=destination_coordinate_tag,
            source_values=source_values,
            initial_sequence_index=initial_sequence_index,
        )
    value = source_values.get(source_tag)
    if value is None:
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_gps_copy_missing_source_tag",
            "Public ordered GPS copy source tag is missing.",
            route.raw,
        )
    return (
        _PublicOrderedGpsEffect(
            order_index=route.order_index,
            sequence_index=initial_sequence_index,
            operation="upsert",
            tag=destination_tag,
            value=value,
            route=route.raw,
        ),
    )


def _public_gps_wildcard_copy_effects(
    route: PublicCopyFromFileRouteRequest,
    source_values: dict[_PublicGpsCoreTag, _PublicGpsValue],
    initial_sequence_index: int,
    selected_tags: tuple[_PublicGpsCoreTag, ...] | None = None,
) -> tuple[_PublicOrderedGpsEffect, ...] | Diagnostic:
    requested_tags = frozenset(selected_tags or tuple(_GPS_CORE_TAG_BY_KEY.values()))
    effects: list[_PublicOrderedGpsEffect] = []
    sequence_index = initial_sequence_index
    for coordinate_tag in ("GPSLatitude", "GPSLongitude"):
        if (
            coordinate_tag not in requested_tags
            and _gps_ref_tag_for_coordinate(coordinate_tag) not in requested_tags
        ):
            continue
        pair_effects = _public_gps_coordinate_pair_copy_effects(
            route=route,
            source_coordinate_tag=coordinate_tag,
            destination_coordinate_tag=coordinate_tag,
            source_values=source_values,
            initial_sequence_index=sequence_index,
            missing_is_empty=True,
        )
        if isinstance(pair_effects, Diagnostic):
            return pair_effects
        effects.extend(pair_effects)
        sequence_index += len(pair_effects)
    return tuple(effects)


def _public_gps_coordinate_pair_copy_effects(
    *,
    route: PublicCopyFromFileRouteRequest,
    source_coordinate_tag: _JpegGpsCoordinateTag,
    destination_coordinate_tag: _JpegGpsCoordinateTag,
    source_values: dict[_PublicGpsCoreTag, _PublicGpsValue],
    initial_sequence_index: int,
    missing_is_empty: bool = False,
) -> tuple[_PublicOrderedGpsEffect, ...] | Diagnostic:
    source_ref_tag = _gps_ref_tag_for_coordinate(source_coordinate_tag)
    destination_ref_tag = _gps_ref_tag_for_coordinate(destination_coordinate_tag)
    coordinate_value = source_values.get(source_coordinate_tag)
    reference_value = source_values.get(source_ref_tag)
    if coordinate_value is None or reference_value is None:
        if missing_is_empty:
            return ()
        return _unsupported_ordered_scalar_copy_write_diagnostic(
            "unsupported_public_ordered_gps_copy_missing_source_tag",
            "Public ordered GPS coordinate copy requires both coordinate and reference tags.",
            route.raw,
        )
    source_kind = _gps_kind_for_coordinate(source_coordinate_tag)
    signed = _signed_coordinate_from_assignment(
        coordinate_value,
        reference_value,
        source_coordinate_tag,
        source_ref_tag,
        source_kind,
    )
    if isinstance(signed, Diagnostic):
        return signed
    destination_value = f"{abs(signed):.12g}"
    destination_ref = _gps_reference_text_for_signed_coordinate(
        signed,
        destination_coordinate_tag,
    )
    return (
        _PublicOrderedGpsEffect(
            order_index=route.order_index,
            sequence_index=initial_sequence_index,
            operation="upsert",
            tag=destination_coordinate_tag,
            value=destination_value,
            route=route.raw,
        ),
        _PublicOrderedGpsEffect(
            order_index=route.order_index,
            sequence_index=initial_sequence_index + 1,
            operation="upsert",
            tag=destination_ref_tag,
            value=destination_ref,
            route=route.raw,
        ),
    )


def _unsupported_ordered_scalar_copy_write_diagnostic(
    code: str,
    message: str,
    unsupported_value: str,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        details={
            "unsupported_value": unsupported_value,
            "supported_tags": _json_string_array(
                (
                    *sorted(_SCALAR_TAG_BY_KEY.values()),
                    "GPSLatitude",
                    "GPSLatitudeRef",
                    "GPSLongitude",
                    "GPSLongitudeRef",
                )
            ),
            "evidence_ids": _public_copy_from_file_evidence_ids_json(),
        },
    )


def _public_exif_scalar_plan_from_values_and_deletes(
    values: dict[_PublicExifScalarTag, _PublicExifScalarValue],
    deleted_tags: set[_PublicExifScalarTag],
) -> ExifScalarWritePlan:
    steps: list[ExifScalarWriteStep] = []
    if values:
        steps.extend(_build_public_exif_scalar_plan_from_values(values).steps)
    if deleted_tags:
        steps.extend(_build_public_exif_scalar_delete_plan(deleted_tags).steps)
    if not steps:
        raise ValueError("ordered scalar copy/write requires at least one final effect")
    return ExifScalarWritePlan(steps=tuple(steps))


def _public_gps_plan_from_values_and_deletes(
    values: dict[_PublicGpsCoreTag, _PublicGpsValue],
    deleted_tags: set[_PublicGpsCoreTag],
) -> ExifGpsWritePlan:
    latitude = _public_signed_gps_coordinate_or_none(
        values,
        "GPSLatitude",
        "GPSLatitudeRef",
        "lat",
    )
    longitude = _public_signed_gps_coordinate_or_none(
        values,
        "GPSLongitude",
        "GPSLongitudeRef",
        "lon",
    )
    if isinstance(latitude, Diagnostic) or isinstance(longitude, Diagnostic):
        if isinstance(latitude, Diagnostic):
            raise ValueError(latitude.message)
        if isinstance(longitude, Diagnostic):
            raise ValueError(longitude.message)
    if latitude is None and longitude is None:
        raise ValueError(
            "GPS delete-only ordered copy/write is deferred until a delete-only GPS plan "
            "can be emitted without fabricating coordinate values."
        )
    plan = build_exif_gps_write_plan(
        latitude=latitude,
        longitude=longitude,
        map_datum=None,
    )
    if deleted_tags:
        plan = append_gps_delete_steps(
            plan,
            tuple(_gps_exif_tag_name(tag) for tag in sorted(deleted_tags)),
        )
    return plan


def _public_signed_gps_coordinate_or_none(
    values: dict[_PublicGpsCoreTag, _PublicGpsValue],
    coordinate_tag: _JpegGpsCoordinateTag,
    ref_tag: _JpegGpsRefTag,
    kind: _JpegGpsKind,
) -> float | Diagnostic | None:
    coordinate_value = values.get(coordinate_tag)
    ref_value = values.get(ref_tag)
    if coordinate_value is None and ref_value is None:
        return None
    if coordinate_value is None or ref_value is None:
        return Diagnostic(
            code="unsupported_gps_value_format",
            message=(
                "Public ordered GPS copy/write requires coordinate and reference "
                "values to be present as a pair."
            ),
            details={"coordinate_tag": coordinate_tag, "reference_tag": ref_tag},
        )
    return _signed_coordinate_from_assignment(
        coordinate_value,
        ref_value,
        coordinate_tag,
        ref_tag,
        kind,
    )


def _gps_exif_tag_name(tag: _PublicGpsCoreTag) -> ExifGpsTagName:
    tag_names: dict[_PublicGpsCoreTag, ExifGpsTagName] = {
        "GPSLatitude": "GPSLatitude",
        "GPSLatitudeRef": "GPSLatitudeRef",
        "GPSLongitude": "GPSLongitude",
        "GPSLongitudeRef": "GPSLongitudeRef",
    }
    return tag_names[tag]


def _build_public_exif_scalar_delete_plan(
    deleted_tags: set[_PublicExifScalarTag],
) -> ExifScalarWritePlan:
    return build_exif_scalar_delete_plan(
        delete_image_description="ImageDescription" in deleted_tags,
        delete_orientation="Orientation" in deleted_tags,
        delete_date_time_original="DateTimeOriginal" in deleted_tags,
        delete_modify_date="ModifyDate" in deleted_tags,
        delete_artist="Artist" in deleted_tags,
        delete_iso="ISO" in deleted_tags,
        delete_focal_length="FocalLength" in deleted_tags,
        delete_scene_capture_type="SceneCaptureType" in deleted_tags,
    )


def _public_scalar_copy_route_expansion(
    route: PublicCopyFromFileRouteRequest,
) -> (
    tuple[tuple[PublicCopyFromFileRouteRequest, _PublicExifScalarTag, _PublicExifScalarTag], ...]
    | None
):
    if route.kind == "selector":
        if route.source_selector is None:
            return None
        source_tag = _public_datfile_destination_scalar_tag_or_none(route.source_selector)
        if source_tag is not None:
            return ((route, source_tag, source_tag),)
        expanded_source_tags = _public_scalar_supported_selector_tags(route.source_selector)
        if not expanded_source_tags:
            return None
        return tuple((route, tag, tag) for tag in expanded_source_tags)
    if route.kind != "redirect_selector":
        return None
    if route.source_selector is None or route.destination_selector is None:
        return None
    source_tag = _public_datfile_destination_scalar_tag_or_none(route.source_selector)
    destination_tag = _public_datfile_destination_scalar_tag_or_none(route.destination_selector)
    if source_tag is not None and destination_tag is not None:
        return ((route, source_tag, destination_tag),)
    if not _public_scalar_destination_selector_preserves_source_tag(route.destination_selector):
        return None
    expanded_source_tags = _public_scalar_supported_selector_tags(route.source_selector)
    if not expanded_source_tags:
        return None
    return tuple((route, tag, tag) for tag in expanded_source_tags)


def _existing_public_scalar_route_copies(
    source_group_values: dict[str, dict[_PublicExifScalarTag, _PublicExifScalarValue]],
    route_copies: list[
        tuple[PublicCopyFromFileRouteRequest, _PublicExifScalarTag, _PublicExifScalarTag]
    ],
) -> list[tuple[PublicCopyFromFileRouteRequest, _PublicExifScalarTag, _PublicExifScalarTag]]:
    existing_copies: list[
        tuple[PublicCopyFromFileRouteRequest, _PublicExifScalarTag, _PublicExifScalarTag]
    ] = []
    for route, source_tag, destination_tag in route_copies:
        if not _public_scalar_source_selector_is_pattern(route.source_selector):
            existing_copies.append((route, source_tag, destination_tag))
            continue
        route_source_values = _public_scalar_values_for_selector(
            source_group_values,
            route.source_selector,
        )
        if source_tag in route_source_values:
            existing_copies.append((route, source_tag, destination_tag))
    return existing_copies


def _public_scalar_source_selector_is_pattern(selector: str | None) -> bool:
    if selector is None:
        return False
    _, local_name = _normalized_tag_parts(selector)
    return local_name in {"*", "all"} or "*" in local_name or "?" in local_name


def _public_scalar_supported_selector_tags(selector: str) -> tuple[_PublicExifScalarTag, ...]:
    group, local_name = _normalized_tag_parts(selector)
    if group not in _SUPPORTED_SCALAR_GROUP_PREFIXES:
        return ()
    if "*" not in local_name and "?" not in local_name and local_name != "all":
        return ()
    source_tags = _public_scalar_supported_tags_for_group(group)
    if local_name in {"*", "all"}:
        return tuple(sorted(source_tags))
    return tuple(sorted(tag for tag in source_tags if fnmatchcase(tag.lower(), local_name)))


def _public_scalar_supported_tags_for_group(group: str) -> frozenset[_PublicExifScalarTag]:
    if group in {"", "exif"}:
        return frozenset(_SCALAR_TAG_BY_KEY.values())
    if group == "ifd0":
        return _IFD0_SCALAR_TAGS
    if group == "exififd":
        return _EXIFIFD_SCALAR_TAGS
    return frozenset()


def _public_scalar_destination_selector_preserves_source_tag(selector: str) -> bool:
    group, local_name = _normalized_tag_parts(selector)
    return group in _SUPPORTED_SCALAR_GROUP_PREFIXES and local_name in {"*", "all"}


def _public_gps_copy_route_kind(
    route: PublicCopyFromFileRouteRequest,
) -> Literal["gps", "unsupported"]:
    if route.kind == "implicit_all":
        return "gps"
    if route.kind == "selector" and route.source_selector is not None:
        return "gps" if _public_gps_selector_is_supported(route.source_selector) else "unsupported"
    if (
        route.kind == "redirect_selector"
        and route.source_selector is not None
        and route.destination_selector is not None
    ):
        if _public_gps_selector_is_supported(route.source_selector) or (
            _public_gps_selector_is_supported(route.destination_selector)
        ):
            return "gps"
    return "unsupported"


def _public_gps_selector_is_supported(selector: str) -> bool:
    return _public_gps_tag_or_none(selector) is not None or bool(
        _public_gps_supported_selector_tags(selector)
    )


def _public_gps_tag_or_none(selector: str) -> _PublicGpsCoreTag | None:
    group, local_name = _normalized_tag_parts(selector)
    if group not in _SUPPORTED_GPS_GROUP_PREFIXES:
        return None
    return _GPS_CORE_TAG_BY_KEY.get(local_name)


def _public_gps_supported_selector_tags(selector: str) -> tuple[_PublicGpsCoreTag, ...]:
    group, local_name = _normalized_tag_parts(selector)
    if group not in _SUPPORTED_GPS_GROUP_PREFIXES:
        return ()
    source_tags: tuple[_PublicGpsCoreTag, ...] = (
        "GPSLatitude",
        "GPSLatitudeRef",
        "GPSLongitude",
        "GPSLongitudeRef",
    )
    if local_name in {"*", "all"}:
        return source_tags
    if "*" not in local_name and "?" not in local_name:
        return ()
    return tuple(tag for tag in source_tags if fnmatchcase(tag.lower(), local_name))


def _public_gps_destination_preserves_source_tag(selector: str) -> bool:
    group, local_name = _normalized_tag_parts(selector)
    return group in _SUPPORTED_GPS_GROUP_PREFIXES and local_name in {"*", "all"}


def _unsupported_public_scalar_copy_result(
    request: MetadataWriteRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
    source_path: Path,
    route_copies: list[
        tuple[PublicCopyFromFileRouteRequest, _PublicExifScalarTag, _PublicExifScalarTag]
    ],
    exc: OSError | ValueError,
) -> MetadataWriteResult:
    return MetadataWriteResult(
        request=request,
        status="not_yet_implemented",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="unsupported_public_scalar_copy_from_file_execution",
                message=f"Public scalar copy-from-file route could not be executed: {exc}",
                details={
                    "source_path": source_path.as_posix(),
                    "routes": _json_string_array(_route_copies_raw_routes(route_copies)),
                    "supported_tags": _json_string_array(sorted(_SCALAR_TAG_BY_KEY.values())),
                    "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                },
            ),
        ),
    )


def _route_copies_raw_routes(
    route_copies: list[
        tuple[PublicCopyFromFileRouteRequest, _PublicExifScalarTag, _PublicExifScalarTag]
    ],
) -> tuple[str, ...]:
    raw_routes: list[str] = []
    for route, _, _ in route_copies:
        if route.raw not in raw_routes:
            raw_routes.append(route.raw)
    return tuple(raw_routes)


def _read_public_jpeg_exif_scalar_values(
    source_path: Path,
) -> dict[_PublicExifScalarTag, _PublicExifScalarValue]:
    return _public_scalar_values_for_selector(
        _read_public_exif_scalar_group_values(source_path),
        "EXIF:*",
    )


def _read_public_exif_scalar_group_values(
    source_path: Path,
) -> dict[str, dict[_PublicExifScalarTag, _PublicExifScalarValue]]:
    if source_path.suffix.lower() in _TIFF_SUFFIXES:
        return _read_public_tiff_exif_scalar_group_values(source_path)
    return _read_public_jpeg_exif_scalar_group_values(source_path)


def _read_public_jpeg_exif_scalar_group_values(
    source_path: Path,
) -> dict[str, dict[_PublicExifScalarTag, _PublicExifScalarValue]]:
    values: dict[_PublicExifScalarTag, _PublicExifScalarValue] = {}
    ifd0_values = _public_scalar_values_from_json_tags(read_ifd0_tags(source_path))
    values.update(ifd0_values)
    exif_ifd_values: dict[_PublicExifScalarTag, _PublicExifScalarValue] = {}
    try:
        exif_ifd_values = _public_scalar_values_from_json_tags(read_exif_ifd_tags(source_path))
        values.update(exif_ifd_values)
    except ValueError:
        pass
    return {
        "": values,
        "exif": values,
        "ifd0": ifd0_values,
        "exififd": exif_ifd_values,
    }


def _read_public_tiff_exif_scalar_group_values(
    source_path: Path,
) -> dict[str, dict[_PublicExifScalarTag, _PublicExifScalarValue]]:
    data = source_path.read_bytes()
    values: dict[_PublicExifScalarTag, _PublicExifScalarValue] = {}
    ifd0_values = _public_scalar_values_from_json_tags(dict(read_ifd0_values(data)))
    values.update(ifd0_values)
    exif_ifd_values: dict[_PublicExifScalarTag, _PublicExifScalarValue] = {}
    try:
        exif_ifd_values = _public_scalar_values_from_json_tags(dict(read_exif_ifd_values(data)))
        values.update(exif_ifd_values)
    except ValueError:
        pass
    return {
        "": values,
        "exif": values,
        "ifd0": ifd0_values,
        "exififd": exif_ifd_values,
    }


def _read_public_gps_core_values(
    source_path: Path,
) -> dict[_PublicGpsCoreTag, _PublicGpsValue]:
    if source_path.suffix.lower() in _TIFF_SUFFIXES:
        return _read_public_tiff_gps_core_values(source_path)
    return _read_public_jpeg_gps_core_values(source_path)


def _read_public_jpeg_gps_core_values(
    source_path: Path,
) -> dict[_PublicGpsCoreTag, _PublicGpsValue]:
    try:
        tags = read_gps_ifd_tags(source_path)
    except ValueError:
        return {}
    values: dict[_PublicGpsCoreTag, _PublicGpsValue] = {}
    for gps_tag in _GPS_CORE_TAG_BY_KEY.values():
        value = tags.get(gps_tag)
        if isinstance(value, str):
            values[gps_tag] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            values[gps_tag] = str(value)
    return values


def _read_public_tiff_gps_core_values(
    source_path: Path,
) -> dict[_PublicGpsCoreTag, _PublicGpsValue]:
    try:
        tags = read_gps_ifd_values(source_path.read_bytes())
    except ValueError:
        return {}
    return _public_gps_core_values_from_json_tags(dict(tags))


def _public_gps_core_values_from_json_tags(
    tags: JsonObject,
) -> dict[_PublicGpsCoreTag, _PublicGpsValue]:
    values: dict[_PublicGpsCoreTag, _PublicGpsValue] = {}
    for gps_tag in _GPS_CORE_TAG_BY_KEY.values():
        value = tags.get(gps_tag)
        if isinstance(value, str):
            values[gps_tag] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            values[gps_tag] = str(value)
    return values


def _public_scalar_values_for_selector(
    group_values: dict[str, dict[_PublicExifScalarTag, _PublicExifScalarValue]],
    selector: str | None,
) -> dict[_PublicExifScalarTag, _PublicExifScalarValue]:
    if selector is None:
        return {}
    group, local_name = _normalized_tag_parts(selector)
    source_values = group_values.get(group, {})
    if local_name in {"*", "all"}:
        return dict(source_values)
    if "*" in local_name or "?" in local_name:
        return {
            tag: value
            for tag, value in source_values.items()
            if fnmatchcase(tag.lower(), local_name)
        }
    scalar_tag = _SCALAR_TAG_BY_KEY.get(local_name)
    if scalar_tag is None:
        return {}
    value = source_values.get(scalar_tag)
    if value is None:
        return {}
    return {scalar_tag: value}


def _public_scalar_values_from_json_tags(
    tags: JsonObject,
) -> dict[_PublicExifScalarTag, _PublicExifScalarValue]:
    values: dict[_PublicExifScalarTag, _PublicExifScalarValue] = {}
    for scalar_tag in _SCALAR_TAG_BY_KEY.values():
        value = tags.get(scalar_tag)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (str, int, float)):
            values[scalar_tag] = value
    return values


def _scalar_copy_values_from_routes(
    source_values: dict[_PublicExifScalarTag, _PublicExifScalarValue],
    route_copies: list[
        tuple[PublicCopyFromFileRouteRequest, _PublicExifScalarTag, _PublicExifScalarTag]
    ],
) -> dict[_PublicExifScalarTag, _PublicExifScalarValue]:
    values: dict[_PublicExifScalarTag, _PublicExifScalarValue] = {}
    for route, source_tag, destination_tag in route_copies:
        value = source_values.get(source_tag)
        if value is None:
            raise ValueError(f"Source tag is missing for route {route.raw}: {source_tag}")
        values[destination_tag] = value
    return values


def _build_public_exif_scalar_plan_from_values(
    values: dict[_PublicExifScalarTag, _PublicExifScalarValue],
) -> ExifScalarWritePlan:
    return build_exif_scalar_write_plan(
        image_description=_scalar_text_value(values.get("ImageDescription")),
        orientation=_scalar_short_value(values.get("Orientation")),
        date_time_original=_scalar_text_value(values.get("DateTimeOriginal")),
        modify_date=_scalar_text_value(values.get("ModifyDate")),
        artist=_scalar_text_value(values.get("Artist")),
        iso=_scalar_short_value(values.get("ISO")),
        focal_length=_scalar_rational_value(values.get("FocalLength")),
        scene_capture_type=_scalar_short_value(values.get("SceneCaptureType")),
    )


def _scalar_text_value(value: _PublicExifScalarValue | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _scalar_short_value(value: _PublicExifScalarValue | None) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, float):
        return str(value)
    return value


def _scalar_rational_value(value: _PublicExifScalarValue | None) -> str | int | float | None:
    return value


def _gps_coordinate_tag_or_none(tag: _PublicGpsCoreTag) -> _JpegGpsCoordinateTag | None:
    if tag == "GPSLatitude":
        return "GPSLatitude"
    if tag == "GPSLongitude":
        return "GPSLongitude"
    return None


def _gps_ref_tag_for_coordinate(tag: _JpegGpsCoordinateTag) -> _JpegGpsRefTag:
    if tag == "GPSLatitude":
        return "GPSLatitudeRef"
    return "GPSLongitudeRef"


def _gps_kind_for_coordinate(tag: _JpegGpsCoordinateTag) -> _JpegGpsKind:
    if tag == "GPSLatitude":
        return "lat"
    return "lon"


def _gps_reference_text_for_signed_coordinate(
    coordinate: float,
    destination_tag: _JpegGpsCoordinateTag,
) -> _PublicGpsValue:
    if destination_tag == "GPSLatitude":
        return "South" if coordinate < 0 else "North"
    return "West" if coordinate < 0 else "East"


def _execute_public_datfile_payload_if_supported(
    request: MetadataWriteRequest,
    copy_request: PublicCopyFromFileRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult | None:
    datfile_routes = tuple(
        sorted(
            (route for route in copy_request.routes if route.kind == "datfile_payload"),
            key=lambda route: route.order_index,
        )
    )
    if len(datfile_routes) != len(copy_request.routes):
        return None
    if not datfile_routes or not request.paths:
        return None
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() not in _JPEG_SUFFIXES
    ]
    if unsupported_paths:
        return None

    scalar_values: dict[_PublicExifScalarTag, str] = {}
    gps_values: dict[_PublicGpsCoreTag, str] = {}
    route_tags: list[str] = []
    source_paths: list[str] = []
    for route in datfile_routes:
        if route.destination_selector is None or route.datfile_path is None:
            return None
        scalar_tag = _public_datfile_destination_scalar_tag_or_none(route.destination_selector)
        gps_tag = _public_datfile_destination_gps_tag_or_none(route.destination_selector)
        if scalar_tag is None and gps_tag is None:
            return None
        try:
            value = route.datfile_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return MetadataWriteResult(
                request=request,
                status="not_yet_implemented",
                diagnostics=(
                    *plan_diagnostics,
                    Diagnostic(
                        code="unsupported_public_datfile_payload_encoding",
                        message=(
                            "Public DATFILE payload execution is bounded to UTF-8 text values "
                            "for supported JPEG EXIF scalar tags."
                        ),
                        details={
                            "datfile_path": route.datfile_path.as_posix(),
                            "route": route.raw,
                            "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                        },
                    ),
                ),
            )
        except OSError as exc:
            return MetadataWriteResult(
                request=request,
                status="not_yet_implemented",
                diagnostics=(
                    *plan_diagnostics,
                    Diagnostic(
                        code="unsupported_public_datfile_payload_source",
                        message=f"Public DATFILE payload source could not be read: {exc}",
                        details={
                            "datfile_path": route.datfile_path.as_posix(),
                            "route": route.raw,
                            "error": str(exc),
                            "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                        },
                    ),
                ),
            )
        if gps_tag is not None:
            gps_values[gps_tag] = value
            route_tags.append(gps_tag)
        elif scalar_tag is not None:
            scalar_values[scalar_tag] = value
            route_tags.append(scalar_tag)
        source_paths.append(route.datfile_path.as_posix())

    gps_component_diagnostic = _public_datfile_gps_component_diagnostic(gps_values)
    if gps_component_diagnostic is not None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, gps_component_diagnostic),
        )

    scalar_plan: ExifScalarWritePlan | None = None
    try:
        if scalar_values:
            scalar_plan = build_exif_scalar_write_plan(
                image_description=scalar_values.get("ImageDescription"),
                orientation=scalar_values.get("Orientation"),
                date_time_original=scalar_values.get("DateTimeOriginal"),
                modify_date=scalar_values.get("ModifyDate"),
                artist=scalar_values.get("Artist"),
                iso=scalar_values.get("ISO"),
                focal_length=scalar_values.get("FocalLength"),
                scene_capture_type=scalar_values.get("SceneCaptureType"),
            )
    except ValueError as exc:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                *plan_diagnostics,
                Diagnostic(
                    code="unsupported_public_datfile_payload_value",
                    message=f"Public DATFILE payload value was rejected: {exc}",
                    details={
                        "error": str(exc),
                        "routes": _json_string_array(route.raw for route in datfile_routes),
                        "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                    },
                ),
            ),
        )

    gps_plan: ExifGpsWritePlan | None = None
    if gps_values:
        try:
            gps_plan = _public_gps_plan_from_values_and_deletes(gps_values, set())
        except ValueError as exc:
            return MetadataWriteResult(
                request=request,
                status="not_yet_implemented",
                diagnostics=(
                    *plan_diagnostics,
                    Diagnostic(
                        code="unsupported_public_datfile_payload_gps_value",
                        message=f"Public GPS DATFILE payload value was rejected: {exc}",
                        details={
                            "error": str(exc),
                            "routes": _json_string_array(route.raw for route in datfile_routes),
                            "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                        },
                    ),
                ),
            )

    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    for path in request.paths:
        try:
            original_data = path.read_bytes()
            rewritten_data = original_data
            if scalar_plan is not None:
                rewritten_data = rewrite_jpeg_exif_scalars_creating_if_needed(
                    rewritten_data,
                    scalar_plan,
                ).data
            if gps_plan is not None:
                rewritten_data = rewrite_jpeg_exif_gps_creating_if_needed(
                    rewritten_data,
                    gps_plan,
                ).data
            if rewritten_data != original_data:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    rewritten_data,
                    _backup_policy(request),
                )
                changed_paths.append(path)
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native public DATFILE payload write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public DATFILE payload copy executed through package-local JPEG "
                    "EXIF scalar/GPS writers."
                ),
                details={
                    "action": "run_modern_public_datfile_payload_executor",
                    "native_callables": [
                        "exifmodern.formats.jpeg.exif_scalar_writer."
                        "rewrite_jpeg_exif_scalars_creating_if_needed",
                        "exifmodern.formats.jpeg.exif_gps_writer."
                        "rewrite_jpeg_exif_gps_creating_if_needed",
                    ],
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "routes": _json_string_array(route.raw for route in datfile_routes),
                    "tags": _json_string_array(route_tags),
                    "datfile_paths": _json_string_array(source_paths),
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_public_xmp_exact_copy_if_supported(
    request: MetadataWriteRequest,
    copy_request: PublicCopyFromFileRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult | None:
    if request.assignments or request.deletes:
        return None
    if request.tag_lookup_package_path is None:
        return None
    if copy_request.source_kind != "explicit_source" or not request.paths:
        return None
    if not _public_copy_routes_are_xmp_exact_redirects(copy_request.routes):
        return None

    package_path = request.tag_lookup_package_path
    if not package_path.exists():
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                *plan_diagnostics,
                Diagnostic(
                    code="unsupported_public_exact_copy_mapping_tag_lookup_package",
                    message=(
                        "Public exact copy mapping requires an existing generated "
                        "TagLookup package."
                    ),
                    details={
                        "tag_lookup_package_path": package_path.as_posix(),
                        "routes": _json_string_array(route.raw for route in copy_request.routes),
                        "evidence_ids": _public_exact_copy_mapping_evidence_ids_json(),
                    },
                ),
            ),
        )

    source_path = Path(copy_request.source)
    source_support = _public_exact_copy_source_support(source_path)
    if not source_support.supported:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                *plan_diagnostics,
                Diagnostic(
                    code="unsupported_public_exact_copy_source",
                    message=(
                        "Public exact EXIF/GPS-to-XMP copy mapping is bounded to "
                        "existing JPEG EXIF APP1, EXIF/TIFF, and BigTIFF sources."
                    ),
                    details={
                        "source_path": source_path.as_posix(),
                        "source_class": source_support.source_class,
                        "blocker_code": source_support.blocker_code or "",
                        "blocker_detail": source_support.detail,
                        "supported_suffixes": _json_string_array(
                            sorted(_legacy_public_exact_copy_source_suffixes())
                        ),
                        "supported_source_suffixes": _json_string_array(
                            sorted(_public_supported_exact_copy_source_suffixes())
                        ),
                        "supported_raw_wrapper_suffixes": _json_string_array(
                            sorted(TIFF_RAW_EXACT_COPY_SOURCE_SUFFIXES)
                        ),
                        "routes": _json_string_array(route.raw for route in copy_request.routes),
                        "evidence_ids": _public_exact_copy_mapping_evidence_ids_json(),
                    },
                ),
            ),
        )

    destination_blockers = _public_exact_copy_destination_blockers(request.paths)
    if destination_blockers:
        return _unsupported_public_exact_copy_destination_result(
            request,
            plan_diagnostics,
            copy_request,
            "unsupported_target_route",
            destination_blockers,
        )

    try:
        service = load_tag_lookup_runtime_service(package_path)
    except (OSError, ValueError) as exc:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                *plan_diagnostics,
                Diagnostic(
                    code="unsupported_public_exact_copy_mapping_tag_lookup_package",
                    message=f"Public exact copy mapping could not load TagLookup: {exc}",
                    details={
                        "tag_lookup_package_path": package_path.as_posix(),
                        "error": str(exc),
                        "evidence_ids": _public_exact_copy_mapping_evidence_ids_json(),
                    },
                ),
            ),
        )

    mapping_results = tuple(
        mapping_result
        for route in copy_request.routes
        for mapping_result in service.expand_xmp_exact_copy_mappings(
            route.source_selector or "",
            route.destination_selector or "",
        )
    )
    blockers = tuple(
        blocker for mapping_result in mapping_results for blocker in mapping_result.blockers
    )
    if blockers:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                *plan_diagnostics,
                Diagnostic(
                    code="unsupported_public_exact_copy_mapping",
                    message=(
                        "Public exact copy mapping resolved through TagLookup but "
                        "one or more routes are outside the bounded EXIF/GPS-to-XMP "
                        "writer slice."
                    ),
                    details={
                        "tag_lookup_package_path": package_path.as_posix(),
                        "routes": _json_string_array(route.raw for route in copy_request.routes),
                        "mapping_results": _public_exact_copy_mapping_results_json(mapping_results),
                        "blocker_codes": _json_string_array(
                            dict.fromkeys(blocker.code for blocker in blockers)
                        ),
                        "evidence_ids": _public_exact_copy_mapping_evidence_ids_json(),
                    },
                ),
            ),
        )

    mapping_items: list[TagLookupExactCopyMapping] = []
    for mapping_result in mapping_results:
        if mapping_result.mapping is not None:
            mapping_items.append(mapping_result.mapping)
    mappings = tuple(mapping_items)
    if not mappings:
        return None
    try:
        plan = parse_xmp_copy_from_file_args(
            (
                "-tagsFromFile",
                source_path.as_posix(),
                *(f"-{route.raw}" for route in copy_request.routes),
            )
        )
    except ValueError as exc:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                *plan_diagnostics,
                Diagnostic(
                    code="unsupported_public_exact_copy_mapping",
                    message=f"Public exact copy route could not be planned: {exc}",
                    details={
                        "routes": _json_string_array(route.raw for route in copy_request.routes),
                        "error": str(exc),
                        "evidence_ids": _public_exact_copy_mapping_evidence_ids_json(),
                    },
                ),
            ),
        )

    exact_plan = replace(plan, exact_mappings=mappings)
    try:
        materialized = _materialize_public_xmp_exact_copy_plan(exact_plan, source_path)
    except (OSError, ValueError) as exc:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                *plan_diagnostics,
                Diagnostic(
                    code="unsupported_public_exact_copy_source",
                    message=(
                        "Public exact EXIF/GPS-to-XMP copy mapping could not "
                        "materialize source EXIF/GPS tags."
                    ),
                    details={
                        "source_path": source_path.as_posix(),
                        "error": str(exc),
                        "supported_suffixes": _json_string_array(
                            sorted(_legacy_public_exact_copy_source_suffixes())
                        ),
                        "supported_source_suffixes": _json_string_array(
                            sorted(_public_supported_exact_copy_source_suffixes())
                        ),
                        "supported_raw_wrapper_suffixes": _json_string_array(
                            sorted(TIFF_RAW_EXACT_COPY_SOURCE_SUFFIXES)
                        ),
                        "routes": _json_string_array(route.raw for route in copy_request.routes),
                        "evidence_ids": _public_exact_copy_mapping_evidence_ids_json(),
                    },
                ),
            ),
        )
    if materialized.diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                *plan_diagnostics,
                *tuple(
                    Diagnostic(
                        code="xmp_exact_copy_from_file_diagnostic",
                        message=diagnostic.detail,
                        details={
                            "token": diagnostic.token,
                            "reason": diagnostic.reason,
                            "evidence_ids": _public_exact_copy_mapping_evidence_ids_json(),
                        },
                    )
                    for diagnostic in materialized.diagnostics
                ),
            ),
        )
    execution_diagnostics: list[Diagnostic] = []
    copied_xmp_properties = _copied_xmp_property_count(materialized.assignments)
    prepared_rewrites: list[_PreparedPublicXmpExactCopyRewrite] = []
    for path in request.paths:
        try:
            if path.suffix.lower() == ".xmp":
                if _public_exact_copy_assignments_are_public_xmp(materialized.assignments):
                    sidecar_plan = _public_exact_copy_generated_xmp_plan(materialized.assignments)
                elif _source_path_is_bigtiff(source_path):
                    sidecar_plan = xmp_property_write_plan_from_copy_assignments(
                        materialized.assignments
                    )
                else:
                    result = rewrite_xmp_sidecar_copy_from_file(source_path, exact_plan)
                    changed = result.changed
                    rewritten_data = result.data
                    copied_properties = result.copied_xmp_properties
                    sidecar_plan = None
                if sidecar_plan is not None:
                    original_data = path.read_bytes() if path.exists() else empty_xmp_packet()
                    sidecar_result = rewrite_xmp_sidecar_properties(original_data, sidecar_plan)
                    changed = (
                        sidecar_result.changed_xmp_properties > 0
                        or sidecar_result.deleted_xmp_properties > 0
                    )
                    rewritten_data = sidecar_result.data
                    copied_properties = copied_xmp_properties
                prepared_rewrites.append(
                    _PreparedPublicXmpExactCopyRewrite(
                        path=path,
                        data=rewritten_data,
                        changed=changed,
                        copied_properties=copied_properties,
                        surface="xmp_sidecar_replace",
                    )
                )
            elif path.suffix.lower() in _JPEG_SUFFIXES:
                original_data = path.read_bytes()
                existing_standard_xmp = first_standard_xmp_app1_segment(original_data) is not None
                rewritten_data = original_data
                if materialized.assignments:
                    if _public_exact_copy_assignments_are_public_xmp(materialized.assignments):
                        jpeg_result = rewrite_jpeg_xmp_properties_creating_if_needed(
                            original_data,
                            _public_exact_copy_generated_xmp_plan(materialized.assignments),
                        )
                    else:
                        jpeg_result = rewrite_jpeg_xmp_copy_assignments_creating_if_needed(
                            original_data,
                            materialized.assignments,
                        )
                    rewritten_data = jpeg_result.data
                copied_properties = copied_xmp_properties
                prepared_rewrites.append(
                    _PreparedPublicXmpExactCopyRewrite(
                        path=path,
                        data=rewritten_data,
                        changed=rewritten_data != original_data,
                        copied_properties=copied_properties,
                        surface=(
                            "jpeg_xmp_app1_merge"
                            if existing_standard_xmp
                            else "jpeg_xmp_app1_create"
                        ),
                    )
                )
            elif path.suffix.lower() == ".png":
                original_data = path.read_bytes()
                xmp_plan = xmp_property_write_plan_from_copy_assignments(materialized.assignments)
                try:
                    existing_xmp = standard_xmp_payload_from_png(original_data)
                except ValueError:
                    existing_xmp = empty_xmp_packet()
                xmp_result = apply_xmp_property_write_plan(existing_xmp, xmp_plan)
                png_result = rewrite_png_metadata(
                    original_data,
                    xmp_payload=xmp_result.packet,
                    delete_metadata_groups=("XMP",),
                )
                rewritten_data = png_result.data
                copied_properties = copied_xmp_properties
                prepared_rewrites.append(
                    _PreparedPublicXmpExactCopyRewrite(
                        path=path,
                        data=rewritten_data,
                        changed=rewritten_data != original_data,
                        copied_properties=copied_properties,
                        surface="png_xmp_itxt_merge",
                    )
                )
            elif path.suffix.lower() == ".webp":
                original_data = path.read_bytes()
                xmp_plan = xmp_property_write_plan_from_copy_assignments(materialized.assignments)
                webp_result = rewrite_webp_metadata(
                    original_data,
                    exif_plan=None,
                    xmp_plan=xmp_plan,
                    delete_all_metadata=False,
                )
                rewritten_data = webp_result.data
                copied_properties = copied_xmp_properties
                prepared_rewrites.append(
                    _PreparedPublicXmpExactCopyRewrite(
                        path=path,
                        data=rewritten_data,
                        changed=rewritten_data != original_data,
                        copied_properties=copied_properties,
                        surface="webp_xmp_chunk_merge",
                    )
                )
            elif path.suffix.lower() in _QUICKTIME_METADATA_WRITE_SUFFIXES:
                original_data = path.read_bytes()
                xmp_plan = xmp_property_write_plan_from_copy_assignments(materialized.assignments)
                quicktime_result = rewrite_quicktime_xmp_properties(original_data, xmp_plan)
                rewritten_data = quicktime_result.data
                copied_properties = copied_xmp_properties
                prepared_rewrites.append(
                    _PreparedPublicXmpExactCopyRewrite(
                        path=path,
                        data=rewritten_data,
                        changed=rewritten_data != original_data,
                        copied_properties=copied_properties,
                        surface="quicktime_xmp_atom_merge",
                    )
                )
            elif path.suffix.lower() == ".jp2":
                original_data = path.read_bytes()
                xmp_plan = xmp_property_write_plan_from_copy_assignments(materialized.assignments)
                jp2_result = rewrite_jp2_metadata(original_data, None, None, xmp_plan, None, None)
                rewritten_data = jp2_result.data
                copied_properties = copied_xmp_properties
                prepared_rewrites.append(
                    _PreparedPublicXmpExactCopyRewrite(
                        path=path,
                        data=rewritten_data,
                        changed=rewritten_data != original_data,
                        copied_properties=copied_properties,
                        surface="jp2_uuid_xmp_box_merge",
                    )
                )
            elif path.suffix.lower() == ".jxl":
                original_data = path.read_bytes()
                xmp_plan = xmp_property_write_plan_from_copy_assignments(materialized.assignments)
                jxl_result = rewrite_jxl_metadata(original_data, None, xmp_plan)
                rewritten_data = jxl_result.data
                copied_properties = copied_xmp_properties
                prepared_rewrites.append(
                    _PreparedPublicXmpExactCopyRewrite(
                        path=path,
                        data=rewritten_data,
                        changed=rewritten_data != original_data,
                        copied_properties=copied_properties,
                        surface="jxl_xml_xmp_box_merge",
                    )
                )
            else:
                raise ValueError(
                    "Public exact copy destination passed unsupported blocker gate: "
                    f"{path.suffix.lower()}."
                )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native public exact EXIF/GPS-to-XMP copy failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=(),
        )

    changed_paths: list[Path] = []
    copied_properties_by_path: JsonArray = []
    destination_surfaces_by_path: JsonArray = []
    for prepared_rewrite in prepared_rewrites:
        if prepared_rewrite.changed:
            if prepared_rewrite.path.suffix.lower() == ".xmp":
                _write_public_exact_xmp_sidecar_result(
                    request,
                    prepared_rewrite.path,
                    prepared_rewrite.data,
                    _backup_policy(request),
                )
            else:
                _write_rewritten_bytes_transactionally(
                    request,
                    prepared_rewrite.path,
                    prepared_rewrite.data,
                    _backup_policy(request),
                )
            changed_paths.append(prepared_rewrite.path)
        copied_properties_by_path.append(
            {
                "path": prepared_rewrite.path.as_posix(),
                "copied_xmp_properties": prepared_rewrite.copied_properties,
            }
        )
        destination_surfaces_by_path.append(
            {
                "path": prepared_rewrite.path.as_posix(),
                "surface": prepared_rewrite.surface,
                "changed": prepared_rewrite.changed,
            }
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public exact EXIF/GPS-to-XMP copy-from-file routes executed through "
                    "TagLookup-backed bounded mapping and package-local XMP writers."
                ),
                details={
                    "action": "run_modern_public_xmp_exact_copy_from_file_executor",
                    "native_callables": [
                        "exifmodern.formats.xmp.sidecar_copy_writer."
                        "rewrite_xmp_sidecar_copy_from_file",
                        "exifmodern.formats.xmp.sidecar_writer.rewrite_xmp_sidecar_properties",
                        "exifmodern.formats.jpeg.xmp_property_writer."
                        "rewrite_jpeg_xmp_copy_assignments_creating_if_needed",
                        "exifmodern.formats.jpeg.xmp_property_writer."
                        "rewrite_jpeg_xmp_properties_creating_if_needed",
                        "exifmodern.formats.png.metadata_writer.rewrite_png_metadata",
                        "exifmodern.formats.riff.webp_writer.rewrite_webp_metadata",
                        "exifmodern.formats.quicktime.fanout_writer."
                        "rewrite_quicktime_xmp_properties",
                        "exifmodern.formats.jpeg2000.metadata_writer.rewrite_jp2_metadata",
                        "exifmodern.formats.jxl.metadata_writer.rewrite_jxl_metadata",
                        "exifmodern.formats.bigtiff.transaction_plan."
                        "materialize_bigtiff_exif_gps_source",
                    ],
                    "planner": (
                        "exifmodern.formats.xmp.copy_from_file_plan.parse_xmp_copy_from_file_args"
                    ),
                    "tag_lookup_package_path": package_path.as_posix(),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "source_path": source_path.as_posix(),
                    "routes": _json_string_array(route.raw for route in copy_request.routes),
                    "mapped_properties": _json_string_array(
                        mapping.destination_property_name for mapping in mappings
                    ),
                    "mapping_results": _public_exact_copy_mapping_results_json(mapping_results),
                    "strategy": exact_plan.strategy,
                    "copied_properties_by_path": copied_properties_by_path,
                    "destination_surfaces_by_path": destination_surfaces_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_exact_copy_mapping_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _public_copy_routes_are_xmp_exact_redirects(
    routes: tuple[PublicCopyFromFileRouteRequest, ...],
) -> bool:
    if not routes:
        return False
    return all(_public_copy_route_is_xmp_exact_redirect(route) for route in routes)


def _public_copy_route_is_xmp_exact_redirect(route: PublicCopyFromFileRouteRequest) -> bool:
    if route.kind != "redirect_selector":
        return False
    if route.source_selector is None or route.destination_selector is None:
        return False
    source_group, source_tag = _normalized_tag_parts(route.source_selector)
    destination_group, destination_tag = _normalized_tag_parts(route.destination_selector)
    if source_group not in {"exif", "gps"}:
        return False
    if destination_group != "xmp" and not destination_group.startswith("xmp-"):
        return False
    return bool(source_tag and destination_tag)


def _public_exact_selector_is_pattern(tag_name: str) -> bool:
    return tag_name in {"*", "all"} or "*" in tag_name or "?" in tag_name


def _public_exact_copy_source_is_supported(source_path: Path) -> bool:
    return _public_exact_copy_source_support(source_path).supported


def _legacy_public_exact_copy_source_suffixes() -> frozenset[str]:
    return EXIF_TIFF_EXACT_COPY_SOURCE_SUFFIXES | _JPEG_SUFFIXES


def _public_supported_exact_copy_source_suffixes() -> frozenset[str]:
    return SUPPORTED_EXACT_COPY_SOURCE_SUFFIXES | frozenset({".btf"})


def _public_exact_copy_source_support(source_path: Path) -> _PublicExactCopySourceSupport:
    if not source_path.is_file():
        return _PublicExactCopySourceSupport(
            supported=False,
            source_class="missing_source",
            blocker_code="source_file_missing",
            detail="The explicit -tagsFromFile source path does not exist as a file.",
        )
    suffix = source_path.suffix.lower()
    if suffix in _JPEG_SUFFIXES:
        return _PublicExactCopySourceSupport(
            supported=True,
            source_class="jpeg_exif_app1",
            blocker_code=None,
            detail="JPEG source EXIF APP1 is materialized through the existing APP1 TIFF reader.",
        )
    if suffix == ".btf":
        return _public_bigtiff_source_support(source_path)
    if suffix in EXIF_TIFF_EXACT_COPY_SOURCE_SUFFIXES:
        if _source_path_is_bigtiff(source_path):
            return _public_bigtiff_source_support(source_path)
        return _public_tiff_header_source_support(source_path, "standalone_exif_tiff")
    if suffix in TIFF_RAW_EXACT_COPY_SOURCE_SUFFIXES:
        if _source_path_is_bigtiff(source_path):
            return _public_bigtiff_source_support(source_path)
        return _public_tiff_header_source_support(source_path, "classic_tiff_raw_wrapper")
    if suffix in _NONSTANDARD_TIFF_RAW_SUFFIXES:
        return _PublicExactCopySourceSupport(
            supported=False,
            source_class="nonstandard_tiff_raw_wrapper",
            blocker_code="nonstandard_tiff_raw_magic_not_materialized",
            detail=(
                "ExifTool routes this RAW family through TIFF-family processing with "
                "format-specific header rules, but the bounded exact-copy source "
                "materializer currently accepts only classic TIFF magic 0x2a or "
                "the precise BigTIFF blocker."
            ),
        )
    if suffix in _NON_TIFF_RAW_SUFFIXES:
        return _PublicExactCopySourceSupport(
            supported=False,
            source_class="non_tiff_raw_wrapper",
            blocker_code="raw_wrapper_embedded_exif_source_not_materialized",
            detail=(
                "ExifTool uses a format-specific RAW module for this source class; "
                "ExifModern does not yet expose its embedded EXIF/GPS/XMP source "
                "tags to exact-copy materialization."
            ),
        )
    if suffix in _MEDIA_CONTAINER_EXACT_COPY_SUFFIXES:
        return _PublicExactCopySourceSupport(
            supported=False,
            source_class="media_container",
            blocker_code="media_container_metadata_source_not_materialized",
            detail=(
                "ExifTool can extract metadata from media/container atom trees, but "
                "this exact-copy path has no source-backed EXIF/GPS/XMP atom/item "
                "materializer for the container."
            ),
        )
    if suffix in _CHUNKED_IMAGE_EXACT_COPY_SUFFIXES:
        return _PublicExactCopySourceSupport(
            supported=False,
            source_class="chunked_image_container",
            blocker_code="chunked_image_metadata_source_not_materialized",
            detail=(
                "ExifTool reads metadata from chunked image containers with "
                "format-specific chunk/box modules; this exact-copy path has no "
                "source-backed chunk XMP/EXIF materializer."
            ),
        )
    return _PublicExactCopySourceSupport(
        supported=False,
        source_class="unsupported_suffix",
        blocker_code="unsupported_source_suffix",
        detail="The source suffix is outside the currently bounded exact-copy source classes.",
    )


def _public_tiff_header_source_support(
    source_path: Path,
    source_class: Literal["standalone_exif_tiff", "classic_tiff_raw_wrapper"],
) -> _PublicExactCopySourceSupport:
    if source_path_has_exif_tiff_header(source_path):
        return _PublicExactCopySourceSupport(
            supported=True,
            source_class=source_class,
            blocker_code=None,
            detail=(
                "The source starts with an EXIF/TIFF or BigTIFF byte-order header; "
                "classic TIFF data is materialized natively, while BigTIFF reaches "
                "the precise materializer blocker."
            ),
        )
    return _PublicExactCopySourceSupport(
        supported=False,
        source_class=source_class,
        blocker_code="classic_tiff_header_missing",
        detail=(
            "The suffix is a TIFF-family exact-copy source, but the bytes do not "
            "start with a classic EXIF/TIFF or BigTIFF header."
        ),
    )


def _public_bigtiff_source_support(source_path: Path) -> _PublicExactCopySourceSupport:
    if _source_path_is_bigtiff(source_path):
        return _PublicExactCopySourceSupport(
            supported=True,
            source_class="bigtiff",
            blocker_code=None,
            detail=(
                "BigTIFF source EXIF/GPS tags are materialized through the typed "
                "BigTIFF IFD reader; destination BigTIFF writes remain blocked."
            ),
        )
    return _PublicExactCopySourceSupport(
        supported=False,
        source_class="bigtiff",
        blocker_code="bigtiff_header_missing",
        detail=(
            "The source suffix is BigTIFF, but the bytes do not start with the "
            "BigTIFF byte-order and 0x2b header."
        ),
    )


def _source_path_is_bigtiff(source_path: Path) -> bool:
    return source_path_has_bigtiff_header(source_path)


def _materialize_public_xmp_exact_copy_plan(
    exact_plan: XmpCopyFromFilePlan,
    source_path: Path,
) -> XmpMaterializedCopyFromFilePlan:
    if _source_path_is_bigtiff(source_path):
        return _materialize_public_bigtiff_xmp_exact_copy_plan(exact_plan, source_path)
    return materialize_xmp_copy_from_file_plan(exact_plan, source_path)


def _materialize_public_bigtiff_xmp_exact_copy_plan(
    exact_plan: XmpCopyFromFilePlan,
    source_path: Path,
) -> XmpMaterializedCopyFromFilePlan:
    materialized_source = materialize_bigtiff_exif_gps_source(source_path.read_bytes())
    if materialized_source.status != "materialized":
        details = "; ".join(diagnostic.detail for diagnostic in materialized_source.diagnostics)
        if not details:
            details = "BigTIFF source EXIF/GPS materialization did not complete."
        raise ValueError(details)
    mappings = mappings_for_copy_plan(exact_plan)
    source_tags = {
        (tag.group, tag.name): ExifSourceTag(
            group=tag.group,
            name=tag.name,
            value=tag.value,
            field_type=tag.field_type,
        )
        for tag in materialized_source.tags
    }
    assignments: list[XmpDestinationAssignment] = []
    for mapping in mappings:
        source_tag = source_tags.get((mapping.source_group, mapping.source_name))
        if source_tag is None:
            continue
        assignments.extend(
            XmpDestinationAssignment(mapping.property_name, value)
            for value in xmp_assignment_values_for_source_tag(source_tag, mapping)
        )
    return XmpMaterializedCopyFromFilePlan(
        copy_plan=exact_plan,
        assignments=tuple(assignments),
        diagnostics=(),
    )


def _copied_xmp_property_count(assignments: tuple[XmpDestinationAssignment, ...]) -> int:
    return len({assignment.property_name for assignment in assignments})


def _public_exact_copy_assignments_are_public_xmp(
    assignments: tuple[XmpDestinationAssignment, ...],
) -> bool:
    if not assignments:
        return False
    return all(
        assignment.property_name in XMP_PUBLIC_SIDECAR_PROPERTY_NAMES for assignment in assignments
    )


def _public_exact_copy_generated_xmp_plan(
    assignments: tuple[XmpDestinationAssignment, ...],
) -> XmpPropertyWritePlan:
    return build_public_xmp_sidecar_property_write_plan(
        tuple(
            XmpPublicSidecarPropertyAssignment(assignment.property_name, assignment.value)
            for assignment in assignments
        )
    )


def _unsupported_public_exact_copy_destination_result(
    request: MetadataWriteRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
    copy_request: PublicCopyFromFileRequest,
    reason: str,
    blockers: tuple[_PublicExactCopyDestinationBlocker, ...],
) -> MetadataWriteResult:
    return MetadataWriteResult(
        request=request,
        status="not_yet_implemented",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="unsupported_public_exact_copy_destination_writer",
                message=(
                    "Public exact EXIF/GPS-to-XMP copy mapping cannot write one or "
                    "more targets with the currently bounded destination writers."
                ),
                details={
                    "reason": reason,
                    "paths": _json_string_array(blocker.path.as_posix() for blocker in blockers),
                    "destination_blockers": _public_exact_copy_destination_blockers_json(blockers),
                    "routes": _json_string_array(route.raw for route in copy_request.routes),
                    "supported_destination_surfaces": [
                        "xmp_sidecar_replace",
                        "jpeg_xmp_app1_create",
                        "jpeg_xmp_app1_merge",
                        "png_xmp_itxt_merge",
                        "webp_xmp_chunk_merge",
                        "quicktime_xmp_atom_merge",
                        "jp2_uuid_xmp_box_merge",
                        "jxl_xml_xmp_box_merge",
                    ],
                    "evidence_ids": _public_exact_copy_mapping_evidence_ids_json(),
                },
            ),
        ),
    )


def _public_exact_copy_destination_blockers(
    paths: tuple[Path, ...],
) -> tuple[_PublicExactCopyDestinationBlocker, ...]:
    return tuple(
        blocker
        for path in paths
        if (blocker := _public_exact_copy_destination_blocker(path)) is not None
    )


def _public_exact_copy_destination_blocker(
    path: Path,
) -> _PublicExactCopyDestinationBlocker | None:
    suffix = path.suffix.lower()
    if (
        suffix == ".xmp"
        or suffix in _JPEG_SUFFIXES
        or suffix in {".png", ".webp", ".jp2", ".jxl"}
        or suffix in _QUICKTIME_METADATA_WRITE_SUFFIXES
    ):
        return None
    if suffix == ".btf" or (
        suffix in EXIF_TIFF_EXACT_COPY_SOURCE_SUFFIXES and _path_is_bigtiff(path)
    ):
        return _exact_copy_destination_blocker(
            path,
            "bigtiff",
            "bigtiff_destination_write_rejected_by_exiftool",
            (
                "ExifTool reads BigTIFF IFD metadata but explicitly rejects BigTIFF "
                "writes; this executor may use BigTIFF as a source only."
            ),
        )
    if suffix in EXIF_TIFF_EXACT_COPY_SOURCE_SUFFIXES:
        return _exact_copy_destination_blocker(
            path,
            "exif_tiff_sidecar_or_image",
            "exif_tiff_destination_ifd_rewrite_missing",
            (
                "ExifTool can route copied values into EXIF/TIFF directories, but "
                "this public exact-copy executor currently owns only XMP sidecar "
                "and JPEG/PNG/WebP XMP destination writers."
            ),
        )
    if suffix in TIFF_RAW_EXACT_COPY_SOURCE_SUFFIXES:
        return _exact_copy_destination_blocker(
            path,
            "classic_tiff_raw_wrapper",
            "tiff_raw_destination_ifd_rewrite_missing",
            (
                "The source materializer may read classic TIFF RAW wrappers, but "
                "mutating RAW-wrapper IFDs requires a format-specific writer route."
            ),
        )
    if suffix in _NONSTANDARD_TIFF_RAW_SUFFIXES:
        return _exact_copy_destination_blocker(
            path,
            "nonstandard_tiff_raw_wrapper",
            "nonstandard_tiff_raw_destination_rewrite_missing",
            (
                "ExifTool handles this RAW class with TIFF-family format-specific "
                "write rules; no exact-copy destination writer owns those offsets."
            ),
        )
    if suffix in _NON_TIFF_RAW_SUFFIXES:
        return _exact_copy_destination_blocker(
            path,
            "non_tiff_raw_wrapper",
            "raw_wrapper_destination_rewrite_missing",
            (
                "ExifTool uses a dedicated RAW module for this destination class; "
                "ExifModern has no exact-copy mutation engine for it in this lane."
            ),
        )
    if suffix in _MEDIA_CONTAINER_EXACT_COPY_SUFFIXES:
        return _exact_copy_destination_blocker(
            path,
            "media_container",
            "media_container_destination_metadata_writer_missing",
            (
                "Container destinations require atom/item/box-specific EXIF/XMP "
                "writers and offset repair, not the bounded XMP sidecar/JPEG APP1 "
                "writer used by this exact-copy executor."
            ),
        )
    if suffix in _JPEG2000_CODESTREAM_SUFFIXES:
        return _exact_copy_destination_blocker(
            path,
            "chunked_image_container",
            "jpeg2000_codestream_write_rejected_by_exiftool",
            (
                "ExifTool reads raw J2C/J2K/JPC codestreams but rejects writing "
                "them directly; exact-copy metadata writes require a boxed JP2 "
                "destination, not a synthesized container conversion."
            ),
        )
    if suffix in _CHUNKED_IMAGE_EXACT_COPY_SUFFIXES:
        return _exact_copy_destination_blocker(
            path,
            "chunked_image_container",
            "chunked_image_destination_metadata_writer_missing",
            (
                "Chunked image destinations require PNG/WebP/JP2/JXL chunk or box "
                "writers for exact-copy routes; this executor does not own them."
            ),
        )
    return _exact_copy_destination_blocker(
        path,
        "unsupported_suffix",
        "unsupported_destination_suffix",
        "The destination suffix is outside the currently bounded exact-copy writers.",
    )


def _path_is_bigtiff(path: Path) -> bool:
    return path.is_file() and _source_path_is_bigtiff(path)


def _exact_copy_destination_blocker(
    path: Path,
    destination_class: _PublicExactCopyDestinationClass,
    blocker_code: str,
    detail: str,
) -> _PublicExactCopyDestinationBlocker:
    return _PublicExactCopyDestinationBlocker(
        path=path,
        suffix=path.suffix.lower(),
        destination_class=destination_class,
        blocker_code=blocker_code,
        detail=detail,
    )


def _public_exact_copy_destination_blockers_json(
    blockers: tuple[_PublicExactCopyDestinationBlocker, ...],
) -> JsonArray:
    return [
        {
            "path": blocker.path.as_posix(),
            "suffix": blocker.suffix,
            "destination_class": blocker.destination_class,
            "blocker_code": blocker.blocker_code,
            "detail": blocker.detail,
        }
        for blocker in blockers
    ]


def _write_public_exact_xmp_sidecar_result(
    request: MetadataWriteRequest,
    path: Path,
    data: bytes,
    backup_policy: BackupPolicy,
) -> None:
    if path.exists():
        _write_rewritten_bytes_transactionally(request, path, data, backup_policy)
        return
    write_bytes_transactionally(path, data)


def _public_exact_copy_mapping_results_json(
    mapping_results: tuple[TagLookupExactCopyMappingResult, ...],
) -> JsonArray:
    items: JsonArray = []
    for mapping_result in mapping_results:
        item: JsonObject = {
            "source_selector": mapping_result.source_selector,
            "destination_selector": mapping_result.destination_selector,
            "outcome": mapping_result.outcome,
            "blockers": [
                {"code": blocker.code, "detail": blocker.detail}
                for blocker in mapping_result.blockers
            ],
        }
        if mapping_result.mapping is not None:
            item["mapping"] = _public_exact_copy_mapping_json(mapping_result.mapping)
        if mapping_result.source_selection is not None:
            item["source_selection"] = _tag_lookup_selection_summary_json(
                mapping_result.source_selection
            )
        if mapping_result.destination_selection is not None:
            item["destination_selection"] = _tag_lookup_selection_summary_json(
                mapping_result.destination_selection
            )
        items.append(item)
    return items


def _public_exact_copy_mapping_json(mapping: TagLookupExactCopyMapping) -> JsonObject:
    return {
        "source_selector": mapping.source_selector,
        "destination_selector": mapping.destination_selector,
        "source_family1": mapping.source_family1,
        "source_tag_name": mapping.source_tag_name,
        "source_data_group": mapping.source_data_group,
        "source_data_name": mapping.source_data_name,
        "destination_family1": mapping.destination_family1,
        "destination_tag_name": mapping.destination_tag_name,
        "destination_property_name": mapping.destination_property_name,
        "source_candidate": _tag_lookup_candidate_summary_json(mapping.source_candidate),
        "destination_candidate": _tag_lookup_candidate_summary_json(mapping.destination_candidate),
    }


def _tag_lookup_selection_summary_json(selection: TagLookupSelectionResult) -> JsonObject:
    return {
        "request": selection.request.raw_name,
        "route": selection.route,
        "outcome": selection.outcome,
        "selected_candidates": [
            _tag_lookup_candidate_summary_json(candidate)
            for candidate in selection.selected_candidates
        ],
        "blocker_codes": _json_string_array(blocker.code for blocker in selection.blockers),
    }


def _tag_lookup_candidate_summary_json(candidate: TagLookupRuntimeCandidate) -> JsonObject:
    return {
        "tag_name": candidate.tag_name,
        "table_number": candidate.table_number,
        "table_name": candidate.table_name,
        "tag_ids": _json_string_array(candidate.tag_ids),
        "family0": candidate.family0,
        "family1": candidate.family1,
    }


def _public_exact_copy_mapping_evidence_ids() -> tuple[str, ...]:
    return (
        "public.write.exact-copy.cli-docs",
        "public.write.exact-copy.tag-lookup",
        "public.write.exact-copy.writer-routing",
        "public.write.copy-from-file.writer-routing",
        "public.write.xmp.assignment",
        "public.write.webp.icc-profile",
        "public.write.tiff.ordered-writer",
    )


def _public_exact_copy_mapping_evidence_ids_json() -> JsonArray:
    return _json_string_array(_public_exact_copy_mapping_evidence_ids())


def _public_tiff_ordered_write_evidence_ids() -> tuple[str, ...]:
    return (
        "public.write.tiff.ordered-writer",
        "public.write.tiff.write-exif",
        "public.write.copy-from-file.gps-conversion",
    )


def _public_tiff_ordered_write_evidence_ids_json() -> JsonArray:
    return _json_string_array(_public_tiff_ordered_write_evidence_ids())


def _execute_public_xmp_sidecar_redirect_copy_if_supported(
    request: MetadataWriteRequest,
    copy_request: PublicCopyFromFileRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult | None:
    if request.assignments or request.deletes:
        return None
    if copy_request.source_kind != "explicit_source" or not request.paths:
        return None
    source_path = Path(copy_request.source)
    if not source_path.is_file():
        return None
    unsupported_targets = [path for path in request.paths if path.suffix.lower() != ".xmp"]
    if unsupported_targets:
        return None
    if len(copy_request.routes) != 1:
        return None
    route = _public_copy_route_as_xmp_sidecar_route_or_none(copy_request.routes[0])
    if route is None:
        return None
    copy_from_file = XmpSidecarCopyFromFileRequest(
        source_path=source_path,
        routes=(route,),
    )
    try:
        plan = parse_xmp_copy_from_file_args(_xmp_sidecar_copy_write_args(copy_from_file))
    except ValueError:
        return None
    prepared = _PreparedXmpSidecarCopyFromFile(
        paths=request.paths,
        source_path=source_path,
        plan=plan,
        backup_policy=_backup_policy(request),
        route_tags=(_xmp_sidecar_copy_route_tag(route),),
    )
    result = _execute_xmp_sidecar_copy_from_file(
        request,
        prepared,
        plan_diagnostics,
    )
    if result.status != "ok":
        return result
    return replace(
        result,
        diagnostics=(
            *result.diagnostics[:-1],
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public redirected EXIF-to-XMP copy-from-file route executed through "
                    "the package-local XMP sidecar copy writer."
                ),
                details={
                    "action": "run_modern_public_xmp_sidecar_redirect_copy_executor",
                    "native_callable": (
                        "exifmodern.formats.xmp.sidecar_copy_writer."
                        "rewrite_xmp_sidecar_copy_from_file_to_path"
                    ),
                    "planner": (
                        "exifmodern.formats.xmp.copy_from_file_plan.parse_xmp_copy_from_file_args"
                    ),
                    "changed_paths": [path.as_posix() for path in result.changed_paths],
                    "source_path": source_path.as_posix(),
                    "routes": _json_string_array(route.raw for route in copy_request.routes),
                    "lowered_routes": [_xmp_sidecar_copy_route_tag(route)],
                    "strategy": plan.strategy,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_copy_from_file_evidence_ids_json(),
                },
            ),
        ),
    )


def _public_copy_route_as_xmp_sidecar_route_or_none(
    route: PublicCopyFromFileRouteRequest,
) -> XmpSidecarCopyRouteRequest | None:
    if route.kind != "redirect_selector":
        return None
    if route.source_selector is None or route.destination_selector is None:
        return None
    source_group, source_tag = _normalized_tag_parts(route.source_selector)
    destination_group, destination_tag = _normalized_tag_parts(route.destination_selector)
    if source_group == "exif" and source_tag in {"*", "all"}:
        if destination_group == "xmp" and destination_tag in {"*", "all"}:
            return XmpSidecarCopyRouteRequest(source_group="EXIF", destination_group="XMP")
    return None


def _public_datfile_destination_scalar_tag_or_none(
    destination_selector: str,
) -> _PublicExifScalarTag | None:
    group, local_name = _normalized_tag_parts(destination_selector)
    if group not in _SUPPORTED_SCALAR_GROUP_PREFIXES:
        return None
    return _SCALAR_TAG_BY_KEY.get(local_name)


def _public_datfile_destination_gps_tag_or_none(
    destination_selector: str,
) -> _PublicGpsCoreTag | None:
    return _public_gps_tag_or_none(destination_selector)


def _public_datfile_gps_component_diagnostic(
    gps_values: dict[_PublicGpsCoreTag, str],
) -> Diagnostic | None:
    missing_tags: list[_PublicGpsCoreTag] = []
    for coordinate_tag in ("GPSLatitude", "GPSLongitude"):
        ref_tag = _gps_ref_tag_for_coordinate(coordinate_tag)
        has_coordinate = coordinate_tag in gps_values
        has_ref = ref_tag in gps_values
        if has_coordinate and not has_ref:
            missing_tags.append(ref_tag)
        if has_ref and not has_coordinate:
            missing_tags.append(coordinate_tag)
    if not missing_tags:
        return None
    return Diagnostic(
        code="unsupported_public_datfile_payload_gps_components",
        message=(
            "Public GPS DATFILE payload execution requires coordinate/ref pairs for each "
            "bounded GPS coordinate written."
        ),
        details={
            "missing_tags": _json_string_array(missing_tags),
            "provided_tags": _json_string_array(gps_values.keys()),
            "supported_tags": _json_string_array(
                (
                    "GPSLatitude",
                    "GPSLatitudeRef",
                    "GPSLongitude",
                    "GPSLongitudeRef",
                )
            ),
            "evidence_ids": _public_copy_from_file_evidence_ids_json(),
        },
    )


def _public_copy_groups(copy_request: PublicCopyFromFileRequest) -> frozenset[str]:
    groups: set[str] = set()
    for route in copy_request.routes:
        if route.kind == "implicit_all":
            groups.update(("EXIF", "XMP"))
            continue
        if route.kind != "selector" or route.source_selector is None:
            return frozenset()
        group = route.source_selector.strip().partition(":")[0].lower()
        if group == "all":
            groups.update(("EXIF", "XMP"))
        elif group == "exif":
            groups.add("EXIF")
        elif group == "xmp":
            groups.add("XMP")
        elif group in {"icc_profile", "icc"}:
            groups.add("ICC_Profile")
        else:
            return frozenset()
    return frozenset(groups)


def _rewrite_public_copy_target(
    target_data: bytes,
    *,
    target_path: Path,
    source_path: Path,
    copied_groups: frozenset[str],
) -> bytes:
    suffix = target_path.suffix.lower()
    rewritten = target_data
    if suffix == ".exif":
        if copied_groups != frozenset({"EXIF"}):
            raise ValueError("EXIF sidecar targets support only EXIF copy routes.")
        return _public_copy_source_exif_tiff_payload(source_path)
    if suffix == ".xmp":
        if copied_groups != frozenset({"XMP"}):
            raise ValueError("XMP sidecar targets support only XMP copy routes.")
        return _public_copy_source_xmp_packet(source_path)
    if suffix in _JPEG_SUFFIXES:
        if "ICC_Profile" in copied_groups:
            raise ValueError("JPEG targets do not support ICC_Profile copy in this route.")
        if "EXIF" in copied_groups:
            rewritten = _rewrite_jpeg_exif_payload(
                rewritten,
                EXIF_APP1_PREFIX + _public_copy_source_exif_tiff_payload(source_path),
            )
        if "XMP" in copied_groups:
            rewritten = _rewrite_jpeg_xmp_payload(
                rewritten,
                XMP_APP1_PREFIX + _public_copy_source_xmp_packet(source_path),
            )
        return rewritten
    if suffix == ".webp":
        chunks = parse_webp_chunks(rewritten)
        if "EXIF" in copied_groups:
            chunks = upsert_webp_chunk(
                chunks,
                EXIF_CHUNK_ID,
                _public_copy_source_exif_tiff_payload(source_path),
            )
        if "XMP" in copied_groups:
            chunks = upsert_webp_chunk(
                chunks,
                XMP_CHUNK_ID,
                _public_copy_source_xmp_packet(source_path),
            )
        if "ICC_Profile" in copied_groups:
            chunks = upsert_webp_chunk(
                chunks,
                ICC_CHUNK_ID,
                _public_copy_source_icc_profile(source_path),
            )
        return encode_webp_chunks(update_vp8x_chunks(chunks))
    raise ValueError(
        "public copy-from-file execution supports .exif, .xmp, JPEG, and WebP targets only."
    )


def _public_copy_source_exif_tiff_payload(source_path: Path) -> bytes:
    suffix = source_path.suffix.lower()
    if suffix == ".exif":
        source_data = source_path.read_bytes()
        if not source_data:
            raise ValueError("EXIF source sidecar is empty.")
        return source_data
    if suffix in _JPEG_SUFFIXES:
        source = FileMediaSource(source_path)
        for probe in read_jpeg_segment_probes(source_path):
            if probe.marker != 0xE1 or not probe.payload_prefix.startswith(EXIF_APP1_PREFIX):
                continue
            payload = source.read_at(probe.payload_offset, probe.payload_length)
            return payload[len(EXIF_APP1_PREFIX) :]
        raise ValueError("JPEG source does not contain an EXIF APP1 segment.")
    if suffix == ".webp":
        source_data = source_path.read_bytes()
        chunk_payload = existing_chunk_payload(parse_webp_chunks(source_data), EXIF_CHUNK_ID)
        if chunk_payload is None:
            raise ValueError("WebP source does not contain an EXIF chunk.")
        return chunk_payload
    raise ValueError("EXIF copy source must be .exif, JPEG, or WebP.")


def _public_copy_source_xmp_packet(source_path: Path) -> bytes:
    suffix = source_path.suffix.lower()
    if suffix == ".xmp":
        source_data = source_path.read_bytes()
        if not source_data:
            raise ValueError("XMP source sidecar is empty.")
        return source_data
    if suffix in _JPEG_SUFFIXES:
        source = FileMediaSource(source_path)
        for probe in read_jpeg_segment_probes(source_path):
            if probe.marker != 0xE1 or not probe.payload_prefix.startswith(XMP_APP1_PREFIX):
                continue
            payload = source.read_at(probe.payload_offset, probe.payload_length)
            return payload[len(XMP_APP1_PREFIX) :]
        raise ValueError("JPEG source does not contain a standard XMP APP1 segment.")
    if suffix == ".webp":
        source_data = source_path.read_bytes()
        chunk_payload = existing_chunk_payload(parse_webp_chunks(source_data), XMP_CHUNK_ID)
        if chunk_payload is None:
            raise ValueError("WebP source does not contain an XMP chunk.")
        return chunk_payload
    raise ValueError("XMP copy source must be .xmp, JPEG, or WebP.")


def _public_copy_source_icc_profile(source_path: Path) -> bytes:
    if source_path.suffix.lower() == ".webp":
        source_data = source_path.read_bytes()
        chunk_payload = existing_chunk_payload(parse_webp_chunks(source_data), ICC_CHUNK_ID)
        if chunk_payload is None:
            raise ValueError("WebP source does not contain an ICCP chunk.")
        return chunk_payload
    return materialize_source_icc_profile(source_path)


def _execute_webp_icc_delete_if_supported(
    request: MetadataWriteRequest,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult | None:
    if not _is_webp_icc_delete_request(request):
        return None

    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    deleted_chunks_by_path: JsonArray = []
    for path in request.paths:
        try:
            original_data = path.read_bytes()
            chunks = parse_webp_chunks(original_data)
            retained_chunks = tuple(chunk for chunk in chunks if chunk.chunk_id != ICC_CHUNK_ID)
            rewritten_data = encode_webp_chunks(update_vp8x_chunks(retained_chunks))
            deleted_count = len(chunks) - len(retained_chunks)
            if rewritten_data != original_data:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    rewritten_data,
                    _backup_policy(request),
                )
                changed_paths.append(path)
            deleted_chunks_by_path.append(
                {
                    "path": path.as_posix(),
                    "deleted_iccp_chunks": deleted_count,
                    "changed": rewritten_data != original_data,
                }
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="unsupported_webp_icc_profile_delete",
                    message=f"Public WebP ICC_Profile delete failed for {path}: {exc}",
                    details={
                        "path": path.as_posix(),
                        "error": str(exc),
                        "evidence_ids": _public_webp_icc_profile_evidence_ids_json(),
                    },
                )
            )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public WebP ICC_Profile delete executed through the package-local "
                    "RIFF/WebP chunk writer primitives."
                ),
                details={
                    "action": "run_modern_webp_icc_profile_delete_writer",
                    "native_callable": (
                        "exifmodern.formats.riff.webp_writer.parse_webp_chunks/"
                        "update_vp8x_chunks/encode_webp_chunks"
                    ),
                    "changed_paths": _json_string_array(path.as_posix() for path in changed_paths),
                    "deletes": _json_string_array(request.deletes),
                    "deleted_chunks_by_path": deleted_chunks_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_webp_icc_profile_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _is_webp_icc_delete_request(request: MetadataWriteRequest) -> bool:
    if not request.paths or not all(path.suffix.lower() == ".webp" for path in request.paths):
        return False
    if request.assignments or len(request.deletes) != 1:
        return False
    if (
        request.xmp_sidecar_copy_from_file is not None
        or request.exif_sidecar_copy_from_file is not None
        or request.public_copy_from_file is not None
        or request.png_chunk_write is not None
        or request.riff_wav_metadata_write is not None
        or request.riff_webp_metadata_write is not None
    ):
        return False
    return _normalized_webp_icc_delete_target(request.deletes[0]) in {
        "icc_profile",
        "icc_profile:all",
        "icc_profile:*",
        "icc",
        "icc:all",
        "icc:*",
    }


def _normalized_webp_icc_delete_target(delete: str) -> str:
    return delete.strip().lower().replace("-", "_")


def _public_webp_icc_profile_evidence_ids() -> tuple[str, ...]:
    return ("public.write.webp.icc-profile",)


def _public_webp_icc_profile_evidence_ids_json() -> JsonArray:
    return _json_string_array(_public_webp_icc_profile_evidence_ids())


def _rewrite_jpeg_exif_payload(jpeg_data: bytes, exif_app1_payload: bytes) -> bytes:
    segment = find_exif_app1_segment_or_none(jpeg_data)
    rewritten_segment = encode_app1_segment(exif_app1_payload)
    if segment is None:
        insertion_offset = exif_app1_insertion_offset(jpeg_data)
        return jpeg_data[:insertion_offset] + rewritten_segment + jpeg_data[insertion_offset:]
    segment_end = segment.payload_offset + segment.payload_length
    return jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:]


def _rewrite_jpeg_xmp_payload(jpeg_data: bytes, xmp_app1_payload: bytes) -> bytes:
    segment = first_standard_xmp_app1_segment(jpeg_data)
    rewritten_segment = encode_xmp_app1_segment(xmp_app1_payload)
    if segment is None:
        insertion_offset = xmp_app1_insertion_offset(jpeg_data)
        return jpeg_data[:insertion_offset] + rewritten_segment + jpeg_data[insertion_offset:]
    segment_end = segment.payload_offset + segment.payload_length
    return jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:]


def _public_copy_from_file_evidence_ids() -> tuple[str, ...]:
    return (
        "public.write.copy-from-file.writer-routing",
        "public.write.copy-from-file.gps-conversion",
        "public.write.copy-from-file.writer-tests",
        "public.write.output.filename-format",
        "public.write.webp.icc-profile",
    )


def _public_copy_from_file_evidence_ids_json() -> JsonArray:
    return _json_string_array(_public_copy_from_file_evidence_ids())


def _json_string_array(values: Iterable[str]) -> JsonArray:
    items: JsonArray = []
    for value in values:
        items.append(value)
    return items


def _json_assignment_value(value: str | bytes) -> str | JsonObject:
    if isinstance(value, str):
        return value
    return {
        "encoding": "base64",
        "byte_count": len(value),
        "value": b64encode(value).decode("ascii"),
    }


def _public_copy_alternate_files_json(
    alternate_files: tuple[PublicCopyFromFileAlternateFile, ...],
) -> JsonArray:
    items: JsonArray = []
    for alternate in alternate_files:
        items.append(
            {
                "raw_option": alternate.raw_option,
                "path": alternate.path.as_posix(),
                "slot": alternate.slot,
            }
        )
    return items


def _public_copy_from_file_diagnostics(
    request: PublicCopyFromFileRequest | None,
) -> tuple[Diagnostic, ...]:
    if request is None:
        return ()
    return (
        Diagnostic(
            code="not_yet_implemented_public_copy_from_file_route",
            message=(
                "Public generic copy-from-file routing is parsed into a typed request, "
                "but this shape is not executed until the selected format writer exposes "
                "a source-backed tag-copy operation."
            ),
            details={
                "source": request.source,
                "source_kind": request.source_kind,
                "alternate_files": _public_copy_alternate_files_json(request.alternate_files),
                "routes": [
                    {
                        "raw": route.raw,
                        "kind": route.kind,
                        "order_index": route.order_index,
                        "source_selector": route.source_selector,
                        "destination_selector": route.destination_selector,
                        "datfile_path": (
                            None if route.datfile_path is None else route.datfile_path.as_posix()
                        ),
                    }
                    for route in request.routes
                ],
                "unsupported_shape": "public_copy_from_file",
                "evidence_ids": _public_copy_from_file_evidence_ids_json(),
            },
        ),
    )


def _has_blocking_exif_sidecar_copy_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> bool:
    return any(
        diagnostic.code
        in {
            "unsupported_mixed_exif_sidecar_copy_from_file_shape",
            "unsupported_exif_sidecar_copy_path",
            "unsupported_exif_sidecar_copy_route",
            "unsupported_exif_sidecar_copy_source_path",
            "unsupported_public_preserve_file_times_route",
        }
        for diagnostic in diagnostics
    )


def _has_blocking_xmp_sidecar_copy_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> bool:
    return any(
        diagnostic.code
        in {
            "not_yet_implemented_xmp_sidecar_copy_backup_policy",
            "unsupported_mixed_xmp_sidecar_copy_from_file_shape",
            "unsupported_xmp_sidecar_copy_path",
            "unsupported_xmp_sidecar_copy_route",
            "unsupported_xmp_sidecar_copy_route_combination",
            "unsupported_xmp_sidecar_copy_source_path",
            "unsupported_public_preserve_file_times_route",
        }
        for diagnostic in diagnostics
    )


def _execute_exif_sidecar_copy_from_file(
    request: MetadataWriteRequest,
    prepared: _PreparedExifSidecarCopyFromFile,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    copied_exif_bytes_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            result = execute_exif_sidecar_copy_from_file_request(
                ExifSidecarCopyFromFileExecutionRequest(
                    source_path=prepared.source_path,
                    output_path=path,
                    copy_plan=prepared.plan,
                    backup_policy=prepared.backup_policy,
                )
            )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native EXIF sidecar copy-from-file failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue
        if result.diagnostics:
            execution_diagnostics.extend(
                Diagnostic(
                    code="exif_sidecar_copy_from_file_diagnostic",
                    message=diagnostic.detail,
                    details={
                        "path": path.as_posix(),
                        "token": diagnostic.token,
                        "reason": diagnostic.reason,
                    },
                )
                for diagnostic in result.diagnostics
            )
            continue
        if result.changed:
            changed_paths.append(path)
        copied_exif_bytes_by_path.append(
            {
                "path": path.as_posix(),
                "copied_exif_bytes": result.copied_exif_bytes,
            }
        )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public write executed through the package-local EXIF sidecar "
                    "copy-from-file writer."
                ),
                details={
                    "action": "run_modern_exif_sidecar_copy_from_file_writer",
                    "native_callable": (
                        "exifmodern.formats.exif_sidecar.sidecar_writer."
                        "execute_exif_sidecar_copy_from_file_request"
                    ),
                    "path_writer": (
                        "exifmodern.formats.exif_sidecar.sidecar_writer."
                        "rewrite_exif_sidecar_copy_from_file_to_path"
                    ),
                    "planner": (
                        "exifmodern.formats.exif_sidecar.copy_from_file_plan."
                        "parse_exif_sidecar_copy_from_file_args"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "source_path": prepared.source_path.as_posix(),
                    "routes": list(prepared.route_tags),
                    "strategy": prepared.plan.strategy,
                    "copied_exif_bytes_by_path": copied_exif_bytes_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": [
                        "public.write.copy-from-file.writer-routing",
                        "public.write.tiff.ordered-writer",
                        "public.write.sidecar.exif-copy",
                    ],
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_xmp_sidecar_copy_from_file(
    request: MetadataWriteRequest,
    prepared: _PreparedXmpSidecarCopyFromFile,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    copied_properties_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            if request.policy == "overwrite_original_in_place":
                result = rewrite_xmp_sidecar_copy_from_file(prepared.source_path, prepared.plan)
                if result.changed:
                    _write_rewritten_bytes_transactionally(
                        request,
                        path,
                        result.data,
                        prepared.backup_policy,
                    )
            else:
                result = rewrite_xmp_sidecar_copy_from_file_to_path(
                    prepared.source_path,
                    path,
                    prepared.plan,
                    backup_policy=prepared.backup_policy,
                )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native XMP sidecar copy-from-file failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue
        if result.diagnostics:
            execution_diagnostics.extend(
                Diagnostic(
                    code="xmp_sidecar_copy_from_file_diagnostic",
                    message=diagnostic.detail,
                    details={
                        "path": path.as_posix(),
                        "token": diagnostic.token,
                        "reason": diagnostic.reason,
                    },
                )
                for diagnostic in result.diagnostics
            )
            continue
        if result.changed:
            changed_paths.append(path)
        copied_properties_by_path.append(
            {
                "path": path.as_posix(),
                "copied_xmp_properties": result.copied_xmp_properties,
            }
        )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public write executed through the package-local XMP sidecar "
                    "copy-from-file writer."
                ),
                details={
                    "action": "run_modern_xmp_sidecar_copy_from_file_writer",
                    "native_callable": (
                        "exifmodern.formats.xmp.sidecar_copy_writer."
                        "rewrite_xmp_sidecar_copy_from_file_to_path"
                    ),
                    "planner": (
                        "exifmodern.formats.xmp.copy_from_file_plan.parse_xmp_copy_from_file_args"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "source_path": prepared.source_path.as_posix(),
                    "routes": list(prepared.route_tags),
                    "strategy": prepared.plan.strategy,
                    "copied_properties_by_path": copied_properties_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": [
                        "public.write.copy-from-file.writer-routing",
                        "public.write.xmp.assignment",
                        "public.write.sidecar.xmp-copy",
                    ],
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_pdf_metadata_delete_write(
    request: MetadataWriteRequest,
    prepared: _PreparedPdfMetadataDeleteWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    delete_plans_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            result = rewrite_pdf_metadata_delete(path.read_bytes())
            if result.changed:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    result.data,
                    prepared.backup_policy,
                )
                changed_paths.append(path)
            delete_plans_by_path.append(
                {
                    "path": path.as_posix(),
                    "status": result.plan.status,
                    "reason": result.plan.reason,
                    "operations": [operation.to_json() for operation in result.plan.operations],
                    "changed": result.changed,
                }
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native PDF metadata delete failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public write executed through the package-local PDF metadata delete writer."
                ),
                details={
                    "action": "run_modern_pdf_metadata_delete_writer",
                    "native_callable": (
                        "exifmodern.formats.pdf.metadata_delete_writer.rewrite_pdf_metadata_delete"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "delete_plans_by_path": delete_plans_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": ["public.write.pdf.info"],
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_pdf_info_scalar_write(
    request: MetadataWriteRequest,
    prepared: _PreparedPdfInfoScalarWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    write_plans_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            result = rewrite_pdf_info_scalar_metadata(path.read_bytes(), prepared.assignments)
            if result.changed:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    result.data,
                    prepared.backup_policy,
                )
                changed_paths.append(path)
            write_plans_by_path.append(
                {
                    "path": path.as_posix(),
                    "status": result.plan.status,
                    "reason": result.plan.reason,
                    "operations": [operation.to_json() for operation in result.plan.operations],
                    "changed": result.changed,
                    "assignments": [
                        {"tag": assignment.tag, "value": assignment.value}
                        for assignment in result.plan.assignments
                    ],
                }
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native PDF Info scalar write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message="Public write executed through the package-local PDF Info writer.",
                details={
                    "action": "run_modern_pdf_info_scalar_writer",
                    "native_callable": (
                        "exifmodern.formats.pdf.metadata_delete_writer."
                        "rewrite_pdf_info_scalar_metadata"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "write_plans_by_path": write_plans_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": list(_pdf_info_write_evidence_ids()),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_xmp_sidecar_namespace_delete(
    request: MetadataWriteRequest,
    prepared: _PreparedXmpSidecarNamespaceDelete,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    deleted_properties_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            packet = path.read_bytes()
            deleted_properties = 0
            for namespace_plan in prepared.plans:
                mutation_result = delete_xmp_namespace(packet, namespace_plan)
                packet = mutation_result.packet
                deleted_properties += mutation_result.deleted_properties
            if deleted_properties > 0:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    packet,
                    prepared.backup_policy,
                )
                changed_paths.append(path)
            deleted_properties_by_path.append(
                {
                    "path": path.as_posix(),
                    "deleted_properties": deleted_properties,
                }
            )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native XMP sidecar namespace delete failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public write executed through the package-local XMP namespace "
                    "delete mutator for sidecar packets."
                ),
                details={
                    "action": "run_modern_xmp_namespace_delete_sidecar_writer",
                    "native_callable": "exifmodern.formats.xmp.mutation.delete_xmp_namespace",
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "targets": [namespace_plan.target for namespace_plan in prepared.plans],
                    "deleted_properties_by_path": deleted_properties_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_xmp_assignment_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_xmp_sidecar_family2_delete(
    request: MetadataWriteRequest,
    prepared: _PreparedXmpSidecarFamily2Delete,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    for path in prepared.paths:
        try:
            if request.policy == "overwrite_original_in_place":
                result = delete_xmp_sidecar_family2_groups(path.read_bytes(), prepared.plan)
                if result.deleted_xmp_properties > 0:
                    _write_rewritten_bytes_transactionally(
                        request,
                        path,
                        result.data,
                        prepared.backup_policy,
                    )
            else:
                result = delete_xmp_sidecar_file_family2_groups_in_place(
                    path,
                    prepared.plan,
                    backup_policy=prepared.backup_policy,
                    preserve_file_times=request.preserve_file_times,
                )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native XMP sidecar family-2 delete failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue
        if result.deleted_xmp_properties > 0:
            changed_paths.append(path)

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public write executed through the package-local XMP sidecar "
                    "family-2 delete writer."
                ),
                details={
                    "action": "run_modern_xmp_family2_delete_sidecar_writer",
                    "native_callable": (
                        "exifmodern.formats.xmp.sidecar_writer."
                        "delete_xmp_sidecar_file_family2_groups_in_place"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "targets": list(prepared.plan.targets),
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_xmp_assignment_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_jpeg_app_segment_delete_write(
    request: MetadataWriteRequest,
    prepared: _PreparedJpegAppSegmentDeleteWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    deleted_segments_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            original_data = path.read_bytes()
            result = delete_jpeg_app_segments(original_data, prepared.plan)
            if result.deleted_segments > 0:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    result.data,
                    prepared.backup_policy,
                )
                changed_paths.append(path)
            deleted_segments_by_path.append(
                {
                    "path": path.as_posix(),
                    "deleted_segments": result.deleted_segments,
                    "deleted_bytes": result.deleted_bytes,
                }
            )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native JPEG APP segment delete failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message="Public write executed through the package-local JPEG APP6 delete writer.",
                details={
                    "action": "run_modern_jpeg_app_segment_delete_writer",
                    "native_callable": (
                        "exifmodern.formats.jpeg.app_segment_delete.delete_jpeg_app_segments"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "target": prepared.plan.target,
                    "deleted_segments_by_path": deleted_segments_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _jpeg_app_segment_delete_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_xmp_sidecar_scalar_write(
    request: MetadataWriteRequest,
    prepared: _PreparedXmpSidecarWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    destination_surfaces_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            suffix = path.suffix.lower()
            if suffix == ".xmp" and request.policy == "overwrite_original_in_place":
                result = rewrite_xmp_sidecar_properties(path.read_bytes(), prepared.plan)
                if result.changed_xmp_properties > 0 or result.deleted_xmp_properties > 0:
                    _write_rewritten_bytes_transactionally(
                        request,
                        path,
                        result.data,
                        prepared.backup_policy,
                    )
                changed = result.changed_xmp_properties > 0 or result.deleted_xmp_properties > 0
                surface = "xmp_sidecar_replace"
            elif suffix == ".xmp":
                result = rewrite_xmp_sidecar_file_properties_in_place(
                    path,
                    prepared.plan,
                    backup_policy=prepared.backup_policy,
                    preserve_file_times=request.preserve_file_times,
                )
                changed = result.changed_xmp_properties > 0 or result.deleted_xmp_properties > 0
                surface = "xmp_sidecar_replace"
            else:
                original_data = path.read_bytes()
                rewritten_data, changed, surface = _rewrite_xmp_assignment_container(
                    original_data,
                    suffix,
                    prepared.plan,
                )
                if changed:
                    _write_rewritten_bytes_transactionally(
                        request,
                        path,
                        rewritten_data,
                        prepared.backup_policy,
                    )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native XMP property write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue
        if changed:
            changed_paths.append(path)
        destination_surfaces_by_path.append(
            {
                "path": path.as_posix(),
                "surface": surface,
                "changed": changed,
            }
        )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=("Public write executed through package-local XMP property writers."),
                details={
                    "action": _xmp_assignment_action_for_paths(prepared.paths),
                    "native_callables": _xmp_assignment_native_callables(prepared.paths),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "destination_surfaces_by_path": destination_surfaces_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_xmp_assignment_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _rewrite_xmp_assignment_container(
    original_data: bytes,
    suffix: str,
    xmp_plan: XmpPropertyWritePlan,
) -> tuple[bytes, bool, str]:
    if suffix in _JPEG_SUFFIXES:
        existing_standard_xmp = first_standard_xmp_app1_segment(original_data) is not None
        jpeg_result = rewrite_jpeg_xmp_properties_creating_if_needed(original_data, xmp_plan)
        return (
            jpeg_result.data,
            jpeg_result.data != original_data,
            "jpeg_xmp_app1_merge" if existing_standard_xmp else "jpeg_xmp_app1_create",
        )
    if suffix == ".png":
        try:
            existing_xmp = standard_xmp_payload_from_png(original_data)
        except ValueError:
            existing_xmp = empty_xmp_packet()
        xmp_result = apply_xmp_property_write_plan(existing_xmp, xmp_plan)
        png_result = rewrite_png_metadata(
            original_data,
            xmp_payload=xmp_result.packet,
            delete_metadata_groups=("XMP",),
        )
        return png_result.data, png_result.data != original_data, "png_xmp_itxt_merge"
    if suffix == ".webp":
        webp_result = rewrite_webp_metadata(
            original_data,
            exif_plan=None,
            xmp_plan=xmp_plan,
            delete_all_metadata=False,
        )
        return webp_result.data, webp_result.data != original_data, "webp_xmp_chunk_merge"
    if suffix in _QUICKTIME_METADATA_WRITE_SUFFIXES:
        quicktime_result = rewrite_quicktime_xmp_properties(original_data, xmp_plan)
        return (
            quicktime_result.data,
            quicktime_result.data != original_data,
            "quicktime_xmp_atom_merge",
        )
    if suffix == ".jp2":
        jp2_result = rewrite_jp2_metadata(original_data, None, None, xmp_plan, None, None)
        return jp2_result.data, jp2_result.data != original_data, "jp2_uuid_xmp_box_merge"
    if suffix == ".jxl":
        jxl_result = rewrite_jxl_metadata(original_data, None, xmp_plan)
        return jxl_result.data, jxl_result.data != original_data, "jxl_xml_xmp_box_merge"
    if suffix == ".pdf":
        pdf_result = rewrite_pdf_xmp_metadata_stream(original_data, xmp_plan)
        return pdf_result.data, pdf_result.changed, "pdf_xmp_metadata_stream_append"
    raise ValueError(f"Unsupported XMP assignment destination suffix: {suffix}.")


def _xmp_assignment_action_for_paths(paths: tuple[Path, ...]) -> str:
    suffixes = {path.suffix.lower() for path in paths}
    if suffixes == {".xmp"}:
        return "run_modern_xmp_generated_writer"
    return "run_modern_xmp_container_property_writer"


def _xmp_assignment_native_callables(paths: tuple[Path, ...]) -> JsonArray:
    suffixes = {path.suffix.lower() for path in paths}
    callables: list[str] = []
    if ".xmp" in suffixes:
        callables.append(
            "exifmodern.formats.xmp.sidecar_writer.rewrite_xmp_sidecar_file_properties_in_place"
        )
    if suffixes & _JPEG_SUFFIXES:
        callables.append(
            "exifmodern.formats.jpeg.xmp_property_writer."
            "rewrite_jpeg_xmp_properties_creating_if_needed"
        )
    if ".png" in suffixes:
        callables.append("exifmodern.formats.png.metadata_writer.rewrite_png_metadata")
    if ".webp" in suffixes:
        callables.append("exifmodern.formats.riff.webp_writer.rewrite_webp_metadata")
    if suffixes & _QUICKTIME_METADATA_WRITE_SUFFIXES:
        callables.append(
            "exifmodern.formats.quicktime.fanout_writer.rewrite_quicktime_xmp_properties"
        )
    if ".jp2" in suffixes:
        callables.append("exifmodern.formats.jpeg2000.metadata_writer.rewrite_jp2_metadata")
    if ".jxl" in suffixes:
        callables.append("exifmodern.formats.jxl.metadata_writer.rewrite_jxl_metadata")
    if ".pdf" in suffixes:
        callables.append(
            "exifmodern.formats.pdf.xmp_metadata_stream_writer.rewrite_pdf_xmp_metadata_stream"
        )
    return _json_string_array(callables)


def _execute_xmp_subject_list_mutation(
    request: MetadataWriteRequest,
    prepared: _PreparedXmpSubjectListMutation,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    mutations_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            original_data = path.read_bytes()
            existing_values = _xmp_dc_subject_values_from_public_target(path, original_data)
            final_values = _xmp_subject_values_after_public_list_mutations(
                existing_values,
                prepared.assignments,
                request.list_separator,
            )
            changed = final_values != existing_values
            if changed:
                plan = _xmp_subject_replacement_plan(final_values)
                if path.suffix.lower() == ".xmp":
                    if request.policy == "overwrite_original_in_place":
                        sidecar_rewrite_result = rewrite_xmp_sidecar_properties(
                            original_data,
                            plan,
                        )
                        if (
                            sidecar_rewrite_result.changed_xmp_properties > 0
                            or sidecar_rewrite_result.deleted_xmp_properties > 0
                        ):
                            _write_rewritten_bytes_transactionally(
                                request,
                                path,
                                sidecar_rewrite_result.data,
                                prepared.backup_policy,
                            )
                    else:
                        sidecar_rewrite_result = rewrite_xmp_sidecar_file_properties_in_place(
                            path,
                            plan,
                            backup_policy=prepared.backup_policy,
                            preserve_file_times=request.preserve_file_times,
                        )
                    if (
                        sidecar_rewrite_result.changed_xmp_properties > 0
                        or sidecar_rewrite_result.deleted_xmp_properties > 0
                    ):
                        changed_paths.append(path)
                else:
                    jpeg_rewrite_result = rewrite_jpeg_xmp_properties_creating_if_needed(
                        original_data, plan
                    )
                    if jpeg_rewrite_result.data != original_data:
                        _write_rewritten_bytes_transactionally(
                            request,
                            path,
                            jpeg_rewrite_result.data,
                            prepared.backup_policy,
                        )
                        changed_paths.append(path)
            mutations_by_path.append(
                {
                    "path": path.as_posix(),
                    "container": (
                        "xmp_sidecar" if path.suffix.lower() == ".xmp" else "jpeg_xmp_app1"
                    ),
                    "existing_values": list(existing_values),
                    "final_values": list(final_values),
                    "changed": changed,
                }
            )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native XMP sidecar list mutation failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    has_jpeg_target = any(path.suffix.lower() != ".xmp" for path in prepared.paths)
    action = (
        "run_modern_xmp_subject_list_mutation_writer"
        if has_jpeg_target
        else "run_modern_xmp_sidecar_list_mutation_writer"
    )
    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public list add/delete write syntax executed for the bounded "
                    "XMP-dc:Subject sidecar/JPEG APP1 subset."
                ),
                details={
                    "action": action,
                    "native_callables": [
                        "exifmodern.formats.xmp.sidecar_writer."
                        "rewrite_xmp_sidecar_file_properties_in_place",
                        "exifmodern.formats.jpeg.xmp_property_writer."
                        "rewrite_jpeg_xmp_properties_creating_if_needed",
                    ],
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "operations": [
                        {
                            "tag": assignment.tag,
                            "operation": assignment.operation,
                            "value": assignment.value,
                        }
                        for assignment in prepared.assignments
                    ],
                    "list_separator": request.list_separator,
                    "mutations_by_path": mutations_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_list_mutation_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_jpeg_iptc_keywords_list_mutation(
    request: MetadataWriteRequest,
    prepared: _PreparedJpegIptcKeywordsListMutation,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    mutations_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            original_data = path.read_bytes()
            existing_values = _jpeg_iptc_keywords_values(original_data)
            final_values = _iptc_keywords_values_after_public_list_mutations(
                existing_values,
                prepared.assignments,
                request.list_separator,
            )
            changed = final_values != existing_values
            if changed:
                rewritten = rewrite_jpeg_iptc_application_creating_if_needed(
                    original_data,
                    _iptc_keywords_replacement_plan(final_values),
                ).data
                if rewritten != original_data:
                    _write_rewritten_bytes_transactionally(
                        request,
                        path,
                        rewritten,
                        prepared.backup_policy,
                    )
                    changed_paths.append(path)
            mutations_by_path.append(
                {
                    "path": path.as_posix(),
                    "existing_values": list(existing_values),
                    "final_values": list(final_values),
                    "changed": changed,
                }
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native JPEG IPTC Keywords list mutation failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public list add/delete write syntax executed for JPEG "
                    "IPTC:Keywords APP13 list values."
                ),
                details={
                    "action": "run_modern_jpeg_iptc_keywords_list_mutation_writer",
                    "native_callable": (
                        "exifmodern.formats.jpeg.iptc_app13_writer."
                        "rewrite_jpeg_iptc_application_creating_if_needed"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "operations": [
                        {
                            "tag": assignment.tag,
                            "operation": assignment.operation,
                            "value": assignment.value,
                        }
                        for assignment in prepared.assignments
                    ],
                    "list_separator": request.list_separator,
                    "mutations_by_path": mutations_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_list_mutation_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_jpeg_iptc_assignment_write(
    request: MetadataWriteRequest,
    prepared: _PreparedJpegIptcAssignmentWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    mutations_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            original_data = path.read_bytes()
            rewritten = rewrite_jpeg_iptc_application_creating_if_needed(
                original_data,
                prepared.plan,
            ).data
            changed = rewritten != original_data
            if changed:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    rewritten,
                    prepared.backup_policy,
                )
                changed_paths.append(path)
            mutations_by_path.append(
                {
                    "path": path.as_posix(),
                    "changed": changed,
                }
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native JPEG IPTC assignment write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public JPEG IPTC string/list replacement assignments executed through "
                    "the package-local APP13 IPTC writer."
                ),
                details={
                    "action": "run_modern_jpeg_iptc_assignment_writer",
                    "native_callable": (
                        "exifmodern.formats.jpeg.iptc_app13_writer."
                        "rewrite_jpeg_iptc_application_creating_if_needed"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "operations": [
                        {
                            "tag": assignment.tag,
                            "operation": assignment.operation,
                            "value": _json_assignment_value(assignment.value),
                        }
                        for assignment in request.assignments
                    ],
                    "list_separator": request.list_separator,
                    "mutations_by_path": mutations_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_iptc_assignment_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_jpeg_iptc_delete_write(
    request: MetadataWriteRequest,
    prepared: _PreparedJpegIptcDeleteWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    mutations_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            original_data = path.read_bytes()
            rewritten = rewrite_jpeg_iptc_application_creating_if_needed(
                original_data,
                prepared.plan,
            ).data
            changed = rewritten != original_data
            if changed:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    rewritten,
                    prepared.backup_policy,
                )
                changed_paths.append(path)
            mutations_by_path.append({"path": path.as_posix(), "changed": changed})
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native JPEG IPTC delete write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public JPEG IPTC dataset deletes executed through the "
                    "package-local APP13 IPTC writer."
                ),
                details={
                    "action": "run_modern_jpeg_iptc_delete_writer",
                    "native_callable": (
                        "exifmodern.formats.jpeg.iptc_app13_writer."
                        "rewrite_jpeg_iptc_application_creating_if_needed"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "mutations_by_path": mutations_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_iptc_assignment_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_jpeg_gps_write(
    request: MetadataWriteRequest,
    prepared: _PreparedJpegGpsWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    for path in prepared.paths:
        try:
            result = rewrite_jpeg_file_exif_gps_in_place(
                path,
                prepared.plan,
                backup_policy=prepared.backup_policy,
                preserve_file_times=request.preserve_file_times,
            )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native JPEG EXIF GPS write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue
        if result.transaction is not None:
            changed_paths.append(path)

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=("Public write executed through the package-local JPEG EXIF GPS writer."),
                details={
                    "action": "run_modern_jpeg_exif_gps_writer",
                    "native_callable": (
                        "exifmodern.formats.jpeg.exif_gps_writer."
                        "rewrite_jpeg_file_exif_gps_in_place"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": ["public.write.exif.gps"],
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _execute_jpeg_exif_scalar_write(
    request: MetadataWriteRequest,
    prepared: _PreparedJpegExifScalarWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    for path in prepared.paths:
        try:
            result = rewrite_jpeg_file_exif_scalars_in_place(
                path,
                prepared.plan,
                backup_policy=prepared.backup_policy,
                preserve_file_times=request.preserve_file_times,
            )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native JPEG EXIF scalar write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
            continue
        if result.transaction is not None:
            changed_paths.append(path)

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public write executed through the package-local JPEG EXIF scalar writer."
                ),
                details={
                    "action": "run_modern_jpeg_exif_scalar_writer",
                    "native_callable": (
                        "exifmodern.formats.jpeg.exif_scalar_writer."
                        "rewrite_jpeg_file_exif_scalars_in_place"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "tags": list(prepared.tags),
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": ["public.write.exif.scalar-table"],
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def writer_t_only_if_missing_exif_scalar_rewrite(
    jpeg_data: bytes,
    plan: ExifScalarWritePlan,
) -> bytes:
    """Apply Writer.t Replace=0-style EXIF scalar writes only to absent tags."""
    missing_plan = writer_t_only_if_missing_exif_scalar_plan(jpeg_data, plan)
    if not missing_plan.steps:
        return jpeg_data
    return rewrite_jpeg_exif_scalars_creating_if_needed(jpeg_data, missing_plan).data


def writer_t_only_if_missing_exif_scalar_plan(
    jpeg_data: bytes,
    plan: ExifScalarWritePlan,
) -> ExifScalarWritePlan:
    existing_tags = _existing_writer_t_exif_scalar_tags(jpeg_data)
    return ExifScalarWritePlan(
        tuple(
            step
            for step in plan.steps
            if step.operation != "upsert" or step.tag_name not in existing_tags
        )
    )


def writer_t_ifd0_resolution_from_jfif_rewrite(
    target_jpeg_data: bytes,
    source_jpeg_data: bytes,
) -> bytes:
    jfif_resolution = _jfif_resolution_values(source_jpeg_data)
    plan = build_exif_scalar_write_plan(
        image_description=None,
        orientation=None,
        date_time_original=None,
        x_resolution=jfif_resolution["XResolution"],
        y_resolution=jfif_resolution["YResolution"],
        resolution_unit=jfif_resolution["ResolutionUnit"],
    )
    return rewrite_jpeg_exif_scalars_creating_if_needed(target_jpeg_data, plan).data


def _existing_writer_t_exif_scalar_tags(jpeg_data: bytes) -> frozenset[ExifScalarTagName]:
    segment = find_exif_app1_segment_or_none(jpeg_data)
    if segment is None:
        return frozenset()
    payload = segment_payload(jpeg_data, segment)
    tiff_data = payload[len(EXIF_APP1_PREFIX) :]
    values = {
        **read_ifd0_values(tiff_data),
        **read_exif_ifd_values(tiff_data),
    }
    return frozenset(tag_name for tag_name in _SCALAR_TAG_BY_KEY.values() if tag_name in values)


def _jfif_resolution_values(jpeg_data: bytes) -> dict[ExifScalarTagName, int | str]:
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker != 0xE0:
            continue
        payload_end = segment.payload_offset + segment.payload_length
        payload = jpeg_data[segment.payload_offset : payload_end]
        if not payload.startswith(b"JFIF\x00") or len(payload) < 12:
            continue
        unit = payload[7]
        resolution_unit = "None"
        if unit == 1:
            resolution_unit = "inches"
        elif unit == 2:
            resolution_unit = "cm"
        return {
            "XResolution": int.from_bytes(payload[8:10], "big"),
            "YResolution": int.from_bytes(payload[10:12], "big"),
            "ResolutionUnit": resolution_unit,
        }
    raise ValueError("No JPEG JFIF APP0 resolution segment found.")


def _execute_vendor_jpeg_composed_write(
    request: MetadataWriteRequest,
    prepared: _PreparedVendorJpegComposedWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    planned_actions_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            original_data = path.read_bytes()
            rewritten_data = _apply_vendor_jpeg_composed_writes(original_data, prepared)
            if rewritten_data != original_data:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    rewritten_data,
                    prepared.backup_policy,
                )
                changed_paths.append(path)
            planned_actions_by_path.append(
                {
                    "path": path.as_posix(),
                    "kind": prepared.kind,
                    "tags": list(prepared.tags),
                    "changed": rewritten_data != original_data,
                }
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_vendor_jpeg_composed_write_failed",
                    message=(f"Public vendor JPEG composed write failed for {path}: {exc}"),
                    details={
                        "path": path.as_posix(),
                        "kind": prepared.kind,
                        "tags": list(prepared.tags),
                        "error": str(exc),
                        "evidence_ids": _vendor_jpeg_composed_evidence_ids(prepared.kind),
                    },
                )
            )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public write executed through the package-local vendor JPEG composed writer."
                ),
                details={
                    "action": "run_modern_vendor_jpeg_composed_writer",
                    "native_callable": "exifmodern.public_api.write_executor",
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "kind": prepared.kind,
                    "tags": list(prepared.tags),
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "planned_actions_by_path": planned_actions_by_path,
                    "evidence_ids": _vendor_jpeg_composed_evidence_ids(prepared.kind),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _apply_vendor_jpeg_composed_writes(
    jpeg_data: bytes,
    prepared: _PreparedVendorJpegComposedWrite,
) -> bytes:
    rewritten = jpeg_data
    if prepared.exif_plan is not None:
        rewritten = rewrite_jpeg_exif_scalars_creating_if_needed(
            rewritten,
            prepared.exif_plan,
        ).data
    if prepared.casio_plan is not None:
        rewritten = rewrite_jpeg_casio_maker_notes(rewritten, prepared.casio_plan).data
    if prepared.binary_maker_note_plan is not None:
        rewritten = rewrite_jpeg_maker_note_binary_data(
            rewritten,
            prepared.binary_maker_note_plan,
        ).data
    if prepared.inline_maker_note_plan is not None:
        rewritten = rewrite_jpeg_inline_maker_note_scalars(
            rewritten,
            prepared.inline_maker_note_plan,
        ).data
    if prepared.iptc_plan is not None:
        rewritten = rewrite_jpeg_iptc_application_creating_if_needed(
            rewritten,
            prepared.iptc_plan,
        ).data
    return rewritten


def _prepare_exif_sidecar_copy_from_file(
    request: MetadataWriteRequest,
) -> tuple[_PreparedExifSidecarCopyFromFile | None, tuple[Diagnostic, ...]]:
    copy_request = request.exif_sidecar_copy_from_file
    if copy_request is None:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public EXIF sidecar copy-from-file execution requires a typed request.",
                details={"reason": "missing_exif_sidecar_copy_from_file"},
            ),
        )
    if not request.paths:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    if (
        request.assignments
        or request.deletes
        or request.xmp_sidecar_copy_from_file is not None
        or request.public_copy_from_file is not None
    ):
        return None, (
            Diagnostic(
                code="unsupported_mixed_exif_sidecar_copy_from_file_shape",
                message=(
                    "Public EXIF sidecar copy-from-file execution must not be mixed "
                    "with scalar assignments, deletes, or XMP sidecar copy requests."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                    "has_xmp_sidecar_copy_from_file": request.xmp_sidecar_copy_from_file
                    is not None,
                    "has_public_copy_from_file": request.public_copy_from_file is not None,
                },
            ),
        )
    if request.preserve_file_times:
        return None, (
            _unsupported_preserve_file_times_diagnostic(
                "exif_sidecar_copy_from_file",
                "EXIF sidecar copy-from-file writer",
            ),
        )
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() != ".exif"
    ]
    if unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_exif_sidecar_copy_path",
                message=(
                    "Public EXIF sidecar copy-from-file execution is limited to .exif "
                    "sidecar targets."
                ),
                details={"unsupported_paths": unsupported_paths},
            ),
        )
    if not copy_request.source_path.is_file():
        return None, (
            Diagnostic(
                code="unsupported_exif_sidecar_copy_source_path",
                message="Public EXIF sidecar copy-from-file source path must be a file.",
                details={"source_path": copy_request.source_path.as_posix()},
            ),
        )
    if not copy_request.routes:
        return None, (
            Diagnostic(
                code="unsupported_exif_sidecar_copy_route",
                message="Public EXIF sidecar copy-from-file execution requires a copy route.",
                details={"reason": "missing_routes"},
            ),
        )

    route_tags = tuple(_exif_sidecar_copy_route_tag(route) for route in copy_request.routes)
    try:
        plan = parse_exif_sidecar_copy_from_file_args(_exif_sidecar_copy_write_args(copy_request))
    except ValueError as exc:
        return None, (
            Diagnostic(
                code="unsupported_exif_sidecar_copy_route",
                message=(
                    "Public EXIF sidecar copy-from-file execution supports only "
                    "source-backed EXIF, EXIF:all, and EXIF:* routes."
                ),
                details={
                    "error": str(exc),
                    "routes": list(route_tags),
                    "supported_routes": ["EXIF", "EXIF:all", "EXIF:*"],
                    "evidence_ids": [
                        "public.write.copy-from-file.writer-routing",
                        "public.write.sidecar.exif-copy",
                    ],
                },
            ),
        )

    return (
        _PreparedExifSidecarCopyFromFile(
            paths=request.paths,
            source_path=copy_request.source_path,
            plan=plan,
            backup_policy=_backup_policy(request),
            route_tags=route_tags,
        ),
        (),
    )


def _exif_sidecar_copy_write_args(request: ExifSidecarCopyFromFileRequest) -> tuple[str, ...]:
    args = ["-tagsFromFile", request.source_path.as_posix()]
    args.extend(f"-{_exif_sidecar_copy_route_tag(route)}" for route in request.routes)
    return tuple(args)


def _exif_sidecar_copy_route_tag(route: ExifSidecarCopyRouteRequest) -> str:
    if route.tag_pattern:
        return f"{route.source_group}:{route.tag_pattern}"
    return route.source_group


def _prepare_xmp_sidecar_copy_from_file(
    request: MetadataWriteRequest,
) -> tuple[_PreparedXmpSidecarCopyFromFile | None, tuple[Diagnostic, ...]]:
    copy_request = request.xmp_sidecar_copy_from_file
    if copy_request is None:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public XMP sidecar copy-from-file execution requires a typed request.",
                details={"reason": "missing_xmp_sidecar_copy_from_file"},
            ),
        )
    if not request.paths:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    if (
        request.assignments
        or request.deletes
        or request.exif_sidecar_copy_from_file is not None
        or request.public_copy_from_file is not None
    ):
        return None, (
            Diagnostic(
                code="unsupported_mixed_xmp_sidecar_copy_from_file_shape",
                message=(
                    "Public XMP sidecar copy-from-file execution must not be mixed "
                    "with scalar assignments, deletes, or EXIF sidecar copy requests."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                    "has_exif_sidecar_copy_from_file": request.exif_sidecar_copy_from_file
                    is not None,
                    "has_public_copy_from_file": request.public_copy_from_file is not None,
                },
            ),
        )
    if request.preserve_file_times:
        return None, (
            _unsupported_preserve_file_times_diagnostic(
                "xmp_sidecar_copy_from_file",
                "XMP sidecar copy-from-file writer",
            ),
        )
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() != ".xmp"
    ]
    if unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_xmp_sidecar_copy_path",
                message=(
                    "Public XMP sidecar copy-from-file execution is limited to .xmp "
                    "sidecar targets."
                ),
                details={"unsupported_paths": unsupported_paths},
            ),
        )
    if not copy_request.source_path.is_file():
        return None, (
            Diagnostic(
                code="unsupported_xmp_sidecar_copy_source_path",
                message="Public XMP sidecar copy-from-file source path must be a file.",
                details={"source_path": copy_request.source_path.as_posix()},
            ),
        )
    if not copy_request.routes:
        return None, (
            Diagnostic(
                code="unsupported_xmp_sidecar_copy_route",
                message="Public XMP sidecar copy-from-file execution requires a copy route.",
                details={"reason": "missing_routes"},
            ),
        )
    route_combination_diagnostic = _unsupported_xmp_sidecar_copy_route_combination_diagnostic(
        copy_request
    )
    if route_combination_diagnostic is not None:
        return None, (route_combination_diagnostic,)

    try:
        plan = parse_xmp_copy_from_file_args(_xmp_sidecar_copy_write_args(copy_request))
    except ValueError as exc:
        return None, (
            Diagnostic(
                code="unsupported_xmp_sidecar_copy_route",
                message=(
                    "Public XMP sidecar copy-from-file execution supports only the "
                    "source-backed route subset implemented by XmpCopyFromFilePlan."
                ),
                details={
                    "error": str(exc),
                    "routes": [_xmp_sidecar_copy_route_tag(route) for route in copy_request.routes],
                    "supported_routes": [
                        "ALL:* > ALL:*",
                        "EXIF:* > XMP:*",
                        "XMP:* > XMP:*",
                    ],
                    "evidence_ids": [
                        "public.write.copy-from-file.writer-routing",
                        "public.write.sidecar.xmp-copy",
                    ],
                },
            ),
        )

    return (
        _PreparedXmpSidecarCopyFromFile(
            paths=request.paths,
            source_path=copy_request.source_path,
            plan=plan,
            backup_policy=_backup_policy(request),
            route_tags=tuple(_xmp_sidecar_copy_route_tag(route) for route in copy_request.routes),
        ),
        (),
    )


def _unsupported_xmp_sidecar_copy_route_combination_diagnostic(
    copy_request: XmpSidecarCopyFromFileRequest,
) -> Diagnostic | None:
    unsupported_routes: JsonArray = [
        _xmp_sidecar_copy_route_tag(route)
        for route in copy_request.routes
        if not _is_supported_xmp_sidecar_copy_route_combination(route)
    ]
    if not unsupported_routes:
        return None
    return Diagnostic(
        code="unsupported_xmp_sidecar_copy_route_combination",
        message=(
            "Public XMP sidecar copy-from-file execution supports only the "
            "source-backed ALL:* > ALL:*, EXIF:* > XMP:*, and XMP:* > XMP:* "
            "route combinations."
        ),
        details={
            "routes": unsupported_routes,
            "supported_routes": _supported_xmp_sidecar_copy_route_tags(),
            "unsupported_route_reason": (
                "source/destination group pairing is outside the native XMP sidecar copy subset"
            ),
            "evidence_ids": [
                "public.write.copy-from-file.writer-routing",
                "public.write.sidecar.xmp-copy",
            ],
        },
    )


def _is_supported_xmp_sidecar_copy_route_combination(
    route: XmpSidecarCopyRouteRequest,
) -> bool:
    return (
        (route.source_group == "ALL" and route.destination_group == "ALL")
        or (route.source_group == "EXIF" and route.destination_group == "XMP")
        or (route.source_group == "XMP" and route.destination_group == "XMP")
    )


def _supported_xmp_sidecar_copy_route_tags() -> JsonArray:
    return ["ALL:* > ALL:*", "EXIF:* > XMP:*", "XMP:* > XMP:*"]


def _xmp_sidecar_copy_write_args(request: XmpSidecarCopyFromFileRequest) -> tuple[str, ...]:
    args = ["-tagsFromFile", request.source_path.as_posix()]
    args.extend(f"-{_xmp_sidecar_copy_route_tag(route)}" for route in request.routes)
    return tuple(args)


def _xmp_sidecar_copy_route_tag(route: XmpSidecarCopyRouteRequest) -> str:
    return (
        f"{route.source_group}:{route.tag_pattern} > {route.destination_group}:{route.tag_pattern}"
    )


def _prepare_xmp_sidecar_namespace_delete(
    request: MetadataWriteRequest,
) -> tuple[_PreparedXmpSidecarNamespaceDelete | None, tuple[Diagnostic, ...]]:
    if not request.paths:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    if request.assignments and request.deletes:
        return None, (
            Diagnostic(
                code="not_yet_implemented_public_write_shape",
                message=(
                    "Public XMP sidecar native write execution does not yet support mixed "
                    "assignment and delete requests."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                },
            ),
        )
    if not request.deletes:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public XMP sidecar namespace delete execution requires delete tags.",
                details={"reason": "missing_deletes"},
            ),
        )

    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() != ".xmp"
    ]
    if unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_xmp_sidecar_delete_path",
                message=(
                    "Public XMP sidecar namespace delete execution is limited to .xmp "
                    "sidecar files."
                ),
                details={"unsupported_paths": unsupported_paths},
            ),
        )

    targets, tag_diagnostics = _xmp_namespace_delete_targets(request.deletes)
    if tag_diagnostics:
        return None, tag_diagnostics

    return (
        _PreparedXmpSidecarNamespaceDelete(
            paths=request.paths,
            plans=tuple(build_xmp_namespace_delete_plan(target) for target in targets),
            backup_policy=_backup_policy(request),
            tags=request.deletes,
        ),
        (),
    )


def _prepare_xmp_sidecar_family2_delete(
    request: MetadataWriteRequest,
) -> tuple[_PreparedXmpSidecarFamily2Delete | None, tuple[Diagnostic, ...]]:
    if not request.paths:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    if request.assignments and request.deletes:
        return None, (
            Diagnostic(
                code="not_yet_implemented_public_write_shape",
                message=(
                    "Public XMP sidecar native write execution does not yet support mixed "
                    "assignment and delete requests."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                },
            ),
        )
    if not request.deletes:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public XMP sidecar family-2 delete execution requires delete tags.",
                details={"reason": "missing_deletes"},
            ),
        )

    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() != ".xmp"
    ]
    if unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_xmp_sidecar_delete_path",
                message=(
                    "Public XMP sidecar family-2 delete execution is limited to .xmp sidecar files."
                ),
                details={"unsupported_paths": unsupported_paths},
            ),
        )

    targets, tag_diagnostics = _xmp_family2_delete_targets(request.deletes)
    if tag_diagnostics:
        return None, tag_diagnostics

    return (
        _PreparedXmpSidecarFamily2Delete(
            paths=request.paths,
            plan=build_xmp_family2_delete_plan(targets),
            backup_policy=_backup_policy(request),
            tags=request.deletes,
        ),
        (),
    )


def _prepare_jpeg_iptc_keywords_list_mutation(
    request: MetadataWriteRequest,
) -> tuple[_PreparedJpegIptcKeywordsListMutation | None, tuple[Diagnostic, ...]]:
    if not _is_iptc_keywords_only_list_mutation_request(request):
        return None, (
            Diagnostic(
                code="unsupported_jpeg_iptc_keywords_list_mutation_tag",
                message=(
                    "Public JPEG IPTC list mutation execution supports only "
                    "IPTC:Keywords in this slice."
                ),
                details={
                    "tags": [assignment.tag for assignment in request.assignments],
                    "supported_tags": ["IPTC:Keywords", "Keywords"],
                    "evidence_ids": _public_list_mutation_evidence_ids_json(),
                },
            ),
        )
    if not request.paths:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    mixed_diagnostic = _unsupported_mixed_jpeg_iptc_keywords_list_mutation_diagnostic(request)
    if mixed_diagnostic is not None:
        return None, (mixed_diagnostic,)

    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() not in _JPEG_SUFFIXES
    ]
    if unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_jpeg_iptc_keywords_list_mutation_path",
                message=(
                    "Public IPTC:Keywords +=/-= list mutation execution is limited "
                    "to JPEG/JPG/JPE targets with Photoshop APP13 IPTC data."
                ),
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": [suffix for suffix in sorted(_JPEG_SUFFIXES)],
                    "evidence_ids": _public_list_mutation_evidence_ids_json(),
                },
            ),
        )

    return (
        _PreparedJpegIptcKeywordsListMutation(
            paths=request.paths,
            assignments=request.assignments,
            backup_policy=_backup_policy(request),
            tags=tuple(assignment.tag for assignment in request.assignments),
        ),
        (),
    )


def _unsupported_mixed_jpeg_iptc_keywords_list_mutation_diagnostic(
    request: MetadataWriteRequest,
) -> Diagnostic | None:
    mixed_surfaces: JsonArray = []
    if request.deletes:
        mixed_surfaces.append("deletes")
    if request.xmp_sidecar_copy_from_file is not None:
        mixed_surfaces.append("xmp_sidecar_copy_from_file")
    if request.exif_sidecar_copy_from_file is not None:
        mixed_surfaces.append("exif_sidecar_copy_from_file")
    if request.public_copy_from_file is not None:
        mixed_surfaces.append("public_copy_from_file")
    if request.png_chunk_write is not None:
        mixed_surfaces.append("png_chunk_write")
    if request.riff_wav_metadata_write is not None:
        mixed_surfaces.append("riff_wav_metadata_write")
    if request.riff_webp_metadata_write is not None:
        mixed_surfaces.append("riff_webp_metadata_write")
    if not mixed_surfaces:
        return None
    return Diagnostic(
        code="unsupported_mixed_jpeg_iptc_keywords_list_mutation_shape",
        message=(
            "Public JPEG IPTC:Keywords +=/-= list mutation execution does not mix "
            "with copy routes, container typed writes, or public delete requests."
        ),
        details={
            "mixed_surfaces": mixed_surfaces,
            "assignments": [
                {
                    "tag": assignment.tag,
                    "operation": assignment.operation,
                    "value": _json_assignment_value(assignment.value),
                }
                for assignment in request.assignments
            ],
            "deletes": list(request.deletes),
            "evidence_ids": _public_list_mutation_evidence_ids_json(),
        },
    )


def _has_jpeg_iptc_keywords_list_mutation_request(request: MetadataWriteRequest) -> bool:
    return _is_iptc_keywords_only_list_mutation_request(request) and any(
        path.suffix.lower() != ".xmp" for path in request.paths
    )


def _is_iptc_keywords_only_list_mutation_request(request: MetadataWriteRequest) -> bool:
    if not _has_public_list_mutation_assignment(request):
        return False
    return all(
        _normalized_tag(assignment.tag) in _SUPPORTED_IPTC_KEYWORDS_LIST_MUTATION_TAGS
        for assignment in request.assignments
    )


def _prepare_jpeg_iptc_assignment_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedJpegIptcAssignmentWrite | None, tuple[Diagnostic, ...]]:
    if not request.assignments:
        return None, ()
    if not _is_jpeg_iptc_assignment_family_request(request):
        return None, ()
    if not _has_jpeg_iptc_assignment_tags(request):
        return None, (
            Diagnostic(
                code="unsupported_jpeg_iptc_assignment_tag",
                message=(
                    "Public JPEG IPTC assignment execution supports only a bounded "
                    "source-backed IPTC string/list replacement tag set."
                ),
                details={
                    "tags": _json_string_array(
                        assignment.tag for assignment in request.assignments
                    ),
                    "supported_tags": _json_string_array(sorted(_SUPPORTED_IPTC_ASSIGNMENT_TAGS)),
                    "evidence_ids": _public_iptc_assignment_evidence_ids_json(),
                },
            ),
        )
    mixed_diagnostic = _unsupported_mixed_jpeg_iptc_assignment_diagnostic(request)
    if mixed_diagnostic is not None:
        return None, (mixed_diagnostic,)
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() not in _JPEG_SUFFIXES
    ]
    if not request.paths or unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_jpeg_iptc_assignment_path",
                message="Public JPEG IPTC assignment execution is limited to JPEG/JPG/JPE targets.",
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": [suffix for suffix in sorted(_JPEG_SUFFIXES)],
                    "evidence_ids": _public_iptc_assignment_evidence_ids_json(),
                },
            ),
        )

    try:
        plan = _jpeg_iptc_assignment_plan(request.assignments, request.list_separator)
    except ValueError as exc:
        return None, (
            Diagnostic(
                code="unsupported_jpeg_iptc_assignment_value",
                message=f"Public JPEG IPTC assignment value was rejected: {exc}",
                details={
                    "error": str(exc),
                    "evidence_ids": _public_iptc_assignment_evidence_ids_json(),
                },
            ),
        )
    return (
        _PreparedJpegIptcAssignmentWrite(
            paths=request.paths,
            plan=plan,
            backup_policy=_backup_policy(request),
            tags=tuple(assignment.tag for assignment in request.assignments),
        ),
        (),
    )


def _has_jpeg_iptc_assignment_tags(request: MetadataWriteRequest) -> bool:
    return bool(request.assignments) and all(
        assignment.operation == "set"
        and _normalized_tag(assignment.tag) in _SUPPORTED_IPTC_ASSIGNMENT_TAGS
        for assignment in request.assignments
    )


def _is_jpeg_iptc_assignment_family_request(request: MetadataWriteRequest) -> bool:
    if not request.assignments:
        return False
    for assignment in request.assignments:
        if assignment.operation != "set":
            return False
        group, local_name = _normalized_tag_parts(assignment.tag)
        if group != "iptc" and local_name not in _SUPPORTED_IPTC_ASSIGNMENT_TAGS:
            return False
    return True


def _unsupported_mixed_jpeg_iptc_assignment_diagnostic(
    request: MetadataWriteRequest,
) -> Diagnostic | None:
    mixed_surfaces: JsonArray = []
    if request.deletes:
        mixed_surfaces.append("deletes")
    if any(assignment.operation != "set" for assignment in request.assignments):
        mixed_surfaces.append("list_mutation_assignments")
    if request.public_copy_from_file is not None:
        mixed_surfaces.append("public_copy_from_file")
    if request.xmp_sidecar_copy_from_file is not None:
        mixed_surfaces.append("xmp_sidecar_copy_from_file")
    if request.exif_sidecar_copy_from_file is not None:
        mixed_surfaces.append("exif_sidecar_copy_from_file")
    if request.png_chunk_write is not None:
        mixed_surfaces.append("png_chunk_write")
    if request.riff_wav_metadata_write is not None:
        mixed_surfaces.append("riff_wav_metadata_write")
    if request.riff_webp_metadata_write is not None:
        mixed_surfaces.append("riff_webp_metadata_write")
    if not mixed_surfaces:
        return None
    return Diagnostic(
        code="unsupported_mixed_jpeg_iptc_assignment_shape",
        message=(
            "Public JPEG IPTC assignment execution is bounded to set operations and "
            "does not mix with copy routes, deletes, list mutations, or container typed writes."
        ),
        details={
            "mixed_surfaces": mixed_surfaces,
            "assignments": [
                {
                    "tag": assignment.tag,
                    "operation": assignment.operation,
                    "value": _json_assignment_value(assignment.value),
                }
                for assignment in request.assignments
            ],
            "deletes": list(request.deletes),
            "evidence_ids": _public_iptc_assignment_evidence_ids_json(),
        },
    )


def _jpeg_iptc_assignment_plan(
    assignments: tuple[MetadataAssignment, ...],
    list_separator: str | None,
) -> IptcApplicationWritePlan:
    steps = tuple(
        _jpeg_iptc_assignment_step(assignment, list_separator) for assignment in assignments
    )
    return IptcApplicationWritePlan(steps)


def _jpeg_iptc_assignment_step(
    assignment: MetadataAssignment,
    list_separator: str | None,
) -> IptcApplicationWriteStep:
    normalized_tag = _normalized_tag(assignment.tag)
    tag_name = _SUPPORTED_IPTC_ASSIGNMENT_TAGS[normalized_tag]
    spec = iptc_application_tag_spec(tag_name)
    if spec is None:
        raise ValueError(f"Unsupported IPTC ApplicationRecord tag: {tag_name}")
    raw_value: str | bytes = assignment.value
    if spec.value_kind == "binary":
        if not isinstance(raw_value, bytes):
            if tag_name == "RasterizedCaption":
                raise ValueError(
                    "IPTC RasterizedCaption public assignment requires caller-supplied "
                    "7360-byte raw raster bytes; ExifTool IPTC.pm defines only "
                    "undef[7360] storage and no text-to-raster generation semantics."
                )
            raise ValueError(
                f"IPTC {tag_name} public assignment requires caller-supplied raw bytes; "
                "text command-line values are not coerced into binary payloads."
            )
        return upsert_binary_step(tag_name, (raw_value,))
    if not isinstance(raw_value, str):
        raise ValueError(f"IPTC {tag_name} public assignment requires text.")
    values: tuple[str, ...] = (
        _public_list_assignment_values(raw_value, list_separator)
        if normalized_tag in _SUPPORTED_IPTC_LIST_ASSIGNMENT_TAGS
        else (raw_value,)
    )
    return upsert_text_step(tag_name, values)


def _prepare_jpeg_iptc_delete_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedJpegIptcDeleteWrite | None, tuple[Diagnostic, ...]]:
    if not request.deletes:
        return None, ()
    if not _is_jpeg_iptc_delete_family_request(request):
        return None, ()
    if not _has_jpeg_iptc_delete_tags(request):
        return None, (
            Diagnostic(
                code="unsupported_jpeg_iptc_delete_tag",
                message=(
                    "Public JPEG IPTC delete execution supports only source-backed "
                    "IPTC ApplicationRecord/NewsPhoto datasets owned by the APP13 writer."
                ),
                details={
                    "tags": _json_string_array(request.deletes),
                    "supported_tags": _json_string_array(sorted(_SUPPORTED_IPTC_ASSIGNMENT_TAGS)),
                    "evidence_ids": _public_iptc_assignment_evidence_ids_json(),
                },
            ),
        )
    mixed_diagnostic = _unsupported_mixed_jpeg_iptc_delete_diagnostic(request)
    if mixed_diagnostic is not None:
        return None, (mixed_diagnostic,)
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() not in _JPEG_SUFFIXES
    ]
    if not request.paths or unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_jpeg_iptc_delete_path",
                message="Public JPEG IPTC delete execution is limited to JPEG/JPG/JPE targets.",
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": [suffix for suffix in sorted(_JPEG_SUFFIXES)],
                    "evidence_ids": _public_iptc_assignment_evidence_ids_json(),
                },
            ),
        )
    return (
        _PreparedJpegIptcDeleteWrite(
            paths=request.paths,
            plan=_jpeg_iptc_delete_plan(request.deletes),
            backup_policy=_backup_policy(request),
            tags=request.deletes,
        ),
        (),
    )


def _prepare_jpeg_app_segment_delete_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedJpegAppSegmentDeleteWrite | None, tuple[Diagnostic, ...]]:
    if not request.deletes:
        return None, ()
    if not _has_jpeg_app_segment_delete_family_request(request):
        return None, ()
    mixed_diagnostic = _unsupported_mixed_jpeg_app_segment_delete_diagnostic(request)
    if mixed_diagnostic is not None:
        return None, (mixed_diagnostic,)
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() not in _JPEG_SUFFIXES
    ]
    if not request.paths or unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_jpeg_app_segment_delete_path",
                message=(
                    "Public JPEG APP segment delete execution is limited to JPEG/JPG/JPE targets."
                ),
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": [suffix for suffix in sorted(_JPEG_SUFFIXES)],
                    "evidence_ids": _jpeg_app_segment_delete_evidence_ids_json(),
                },
            ),
        )

    plans: list[JpegAppSegmentDeletePlan] = []
    unsupported_tags: JsonArray = []
    for delete in request.deletes:
        group, selector = _normalized_delete_tag_parts(delete)
        if selector not in {"*", "all"}:
            unsupported_tags.append(delete)
            continue
        try:
            plans.append(
                build_jpeg_app_segment_delete_plan(jpeg_app_segment_delete_target(group.upper()))
            )
        except ValueError:
            unsupported_tags.append(delete)

    if unsupported_tags:
        return None, (
            Diagnostic(
                code="unsupported_jpeg_app_segment_delete_tag",
                message=(
                    "Public JPEG APP segment delete execution is bounded to source-backed "
                    "APP6:* deletes."
                ),
                details={
                    "unsupported_tags": unsupported_tags,
                    "supported_tags": ["APP6:*", "APP6:All"],
                    "evidence_ids": _jpeg_app_segment_delete_evidence_ids_json(),
                },
            ),
        )
    if len(plans) != 1:
        return None, (
            Diagnostic(
                code="unsupported_jpeg_app_segment_delete_tag",
                message="Public JPEG APP segment delete execution supports one APP6 delete target.",
                details={
                    "tags": list(request.deletes),
                    "evidence_ids": _jpeg_app_segment_delete_evidence_ids_json(),
                },
            ),
        )
    return (
        _PreparedJpegAppSegmentDeleteWrite(
            paths=request.paths,
            plan=plans[0],
            backup_policy=_backup_policy(request),
            tags=request.deletes,
        ),
        (),
    )


def _has_jpeg_app_segment_delete_tags(request: MetadataWriteRequest) -> bool:
    return bool(request.deletes) and _has_jpeg_app_segment_delete_family_request(request)


def _has_jpeg_app_segment_delete_family_request(request: MetadataWriteRequest) -> bool:
    return bool(request.deletes) and all(
        _normalized_delete_tag_parts(delete)[0].startswith("app") for delete in request.deletes
    )


def _unsupported_mixed_jpeg_app_segment_delete_diagnostic(
    request: MetadataWriteRequest,
) -> Diagnostic | None:
    mixed_surfaces: JsonArray = []
    if request.assignments:
        mixed_surfaces.append("assignments")
    if request.public_copy_from_file is not None:
        mixed_surfaces.append("public_copy_from_file")
    if request.xmp_sidecar_copy_from_file is not None:
        mixed_surfaces.append("xmp_sidecar_copy_from_file")
    if request.exif_sidecar_copy_from_file is not None:
        mixed_surfaces.append("exif_sidecar_copy_from_file")
    if not mixed_surfaces:
        return None
    return Diagnostic(
        code="unsupported_mixed_jpeg_app_segment_delete_shape",
        message=(
            "Public JPEG APP segment delete execution is bounded to delete-only "
            "requests and does not mix with assignments or copy routes."
        ),
        details={
            "mixed_surfaces": mixed_surfaces,
            "deletes": list(request.deletes),
            "evidence_ids": _jpeg_app_segment_delete_evidence_ids_json(),
        },
    )


def _jpeg_app_segment_delete_evidence_ids_json() -> JsonArray:
    return ["public.write.jpeg.app-segment-delete"]


def _has_jpeg_iptc_delete_tags(request: MetadataWriteRequest) -> bool:
    return bool(request.deletes) and all(
        _normalized_tag(delete) in _SUPPORTED_IPTC_ASSIGNMENT_TAGS for delete in request.deletes
    )


def _is_jpeg_iptc_delete_family_request(request: MetadataWriteRequest) -> bool:
    if not request.deletes:
        return False
    for delete in request.deletes:
        group, local_name = _normalized_tag_parts(delete)
        if group != "iptc" and local_name not in _SUPPORTED_IPTC_ASSIGNMENT_TAGS:
            return False
    return True


def _unsupported_mixed_jpeg_iptc_delete_diagnostic(
    request: MetadataWriteRequest,
) -> Diagnostic | None:
    mixed_surfaces: JsonArray = []
    if request.assignments:
        mixed_surfaces.append("assignments")
    if request.public_copy_from_file is not None:
        mixed_surfaces.append("public_copy_from_file")
    if request.xmp_sidecar_copy_from_file is not None:
        mixed_surfaces.append("xmp_sidecar_copy_from_file")
    if request.exif_sidecar_copy_from_file is not None:
        mixed_surfaces.append("exif_sidecar_copy_from_file")
    if request.png_chunk_write is not None:
        mixed_surfaces.append("png_chunk_write")
    if request.riff_wav_metadata_write is not None:
        mixed_surfaces.append("riff_wav_metadata_write")
    if request.riff_webp_metadata_write is not None:
        mixed_surfaces.append("riff_webp_metadata_write")
    if not mixed_surfaces:
        return None
    return Diagnostic(
        code="unsupported_mixed_jpeg_iptc_delete_shape",
        message=(
            "Public JPEG IPTC delete execution is bounded to delete-only requests "
            "and does not mix with assignments, copy routes, or container typed writes."
        ),
        details={
            "mixed_surfaces": mixed_surfaces,
            "deletes": list(request.deletes),
            "assignments": [assignment.tag for assignment in request.assignments],
            "evidence_ids": _public_iptc_assignment_evidence_ids_json(),
        },
    )


def _jpeg_iptc_delete_plan(deletes: tuple[str, ...]) -> IptcApplicationWritePlan:
    return IptcApplicationWritePlan(
        tuple(
            text_step("delete", _SUPPORTED_IPTC_ASSIGNMENT_TAGS[_normalized_tag(delete)], ())
            for delete in deletes
        )
    )


def _prepare_xmp_subject_list_mutation(
    request: MetadataWriteRequest,
) -> tuple[_PreparedXmpSubjectListMutation | None, tuple[Diagnostic, ...]]:
    if not request.paths:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    mixed_diagnostic = _unsupported_mixed_xmp_sidecar_list_mutation_diagnostic(request)
    if mixed_diagnostic is not None:
        return None, (mixed_diagnostic,)

    unsupported_paths: JsonArray = [
        path.as_posix()
        for path in request.paths
        if path.suffix.lower() != ".xmp" and path.suffix.lower() not in _JPEG_SUFFIXES
    ]
    if unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_xmp_sidecar_list_mutation_path",
                message=(
                    "Public XMP-dc:Subject list add/delete write execution is limited to "
                    "XMP sidecar files and JPEG/JPG/JPE targets with standard XMP APP1 packets."
                ),
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": [".xmp", *sorted(_JPEG_SUFFIXES)],
                    "evidence_ids": _public_list_mutation_evidence_ids_json(),
                },
            ),
        )

    xmp_packet_diagnostic = _unsupported_jpeg_xmp_subject_list_mutation_packet_diagnostic(request)
    if xmp_packet_diagnostic is not None:
        return None, (xmp_packet_diagnostic,)

    unsupported_assignments: JsonArray = [
        assignment.tag
        for assignment in request.assignments
        if _normalized_tag(assignment.tag) not in _SUPPORTED_XMP_LIST_MUTATION_TAGS
    ]
    if unsupported_assignments:
        return None, (
            Diagnostic(
                code="unsupported_xmp_sidecar_list_mutation_tag",
                message=(
                    "Public +=/-= list mutation is supported only for source-backed "
                    "XMP-dc:Subject sidecar Bag lists in this slice."
                ),
                details={
                    "unsupported_tags": unsupported_assignments,
                    "supported_tags": ["XMP-dc:Subject"],
                    "unsupported_surfaces": [
                        "IPTC:Keywords",
                        "binary/protected tags",
                        "structured XMP lists",
                        "non-sidecar list containers",
                    ],
                    "evidence_ids": _public_list_mutation_evidence_ids_json(),
                },
            ),
        )

    return (
        _PreparedXmpSubjectListMutation(
            paths=request.paths,
            assignments=request.assignments,
            backup_policy=_backup_policy(request),
            tags=tuple(assignment.tag for assignment in request.assignments),
        ),
        (),
    )


def _unsupported_mixed_xmp_sidecar_list_mutation_diagnostic(
    request: MetadataWriteRequest,
) -> Diagnostic | None:
    mixed_surfaces: JsonArray = []
    if request.deletes:
        mixed_surfaces.append("deletes")
    has_set_assignment = any(assignment.operation == "set" for assignment in request.assignments)
    has_list_assignment = any(assignment.operation != "set" for assignment in request.assignments)
    if has_set_assignment and has_list_assignment:
        if any(
            _normalized_tag(assignment.tag) not in _SUPPORTED_XMP_LIST_MUTATION_TAGS
            for assignment in request.assignments
        ):
            mixed_surfaces.append("scalar_assignments")
    if request.xmp_sidecar_copy_from_file is not None:
        mixed_surfaces.append("xmp_sidecar_copy_from_file")
    if request.exif_sidecar_copy_from_file is not None:
        mixed_surfaces.append("exif_sidecar_copy_from_file")
    if request.public_copy_from_file is not None:
        mixed_surfaces.append("public_copy_from_file")
    if request.png_chunk_write is not None:
        mixed_surfaces.append("png_chunk_write")
    if request.riff_wav_metadata_write is not None:
        mixed_surfaces.append("riff_wav_metadata_write")
    if request.riff_webp_metadata_write is not None:
        mixed_surfaces.append("riff_webp_metadata_write")
    if not mixed_surfaces:
        return None
    return Diagnostic(
        code="unsupported_mixed_xmp_sidecar_list_mutation_shape",
        message=(
            "Public +=/-= list mutation execution is bounded to ordered "
            "XMP-dc:Subject sidecar operations and does not mix with copy routes, "
            "container typed writes, or public delete requests."
        ),
        details={
            "mixed_surfaces": mixed_surfaces,
            "assignments": [
                {
                    "tag": assignment.tag,
                    "operation": assignment.operation,
                    "value": assignment.value,
                }
                for assignment in request.assignments
            ],
            "deletes": list(request.deletes),
            "evidence_ids": _public_list_mutation_evidence_ids_json(),
        },
    )


def _prepare_quicktime_metadata_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedQuickTimeMetadataWrite | None, tuple[Diagnostic, ...]]:
    if not _has_quicktime_metadata_write_tags(request):
        return None, ()
    if not request.paths:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public QuickTime metadata execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    mixed_diagnostic = _unsupported_mixed_quicktime_metadata_write_diagnostic(request)
    if mixed_diagnostic is not None:
        return None, (mixed_diagnostic,)
    unsupported_paths: JsonArray = [
        path.as_posix()
        for path in request.paths
        if path.suffix.lower() not in _QUICKTIME_METADATA_WRITE_SUFFIXES
    ]
    if unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_quicktime_metadata_write_path",
                message=(
                    "Public QuickTime metadata assignment/delete execution is limited "
                    "to MOV/MP4/M4A/M4V/3GP/QT targets."
                ),
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": _json_string_array(
                        sorted(_QUICKTIME_METADATA_WRITE_SUFFIXES)
                    ),
                    "evidence_ids": _public_quicktime_metadata_write_evidence_ids_json(),
                },
            ),
        )
    write_args = _quicktime_metadata_write_args(request)
    parsed = parse_quicktime_metadata_write_args(write_args)
    if parsed.unsupported:
        return None, (
            Diagnostic(
                code="unsupported_quicktime_metadata_write_tag",
                message=(
                    "Public QuickTime metadata execution supports only owned "
                    "ItemList/UserData/Keys/AudioKeys/VideoKeys assignment and delete tags."
                ),
                details={
                    "unsupported": _json_string_array(parsed.unsupported),
                    "write_args": _json_string_array(write_args),
                    "evidence_ids": _public_quicktime_metadata_write_evidence_ids_json(),
                },
            ),
        )
    return (
        _PreparedQuickTimeMetadataWrite(
            paths=request.paths,
            plan=parsed.plan,
            backup_policy=_backup_policy(request),
            tags=tuple(
                [
                    *(assignment.tag for assignment in request.assignments),
                    *request.deletes,
                ]
            ),
        ),
        (),
    )


def _prepare_quicktime_microsoft_xtra_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedQuickTimeMicrosoftXtraWrite | None, tuple[Diagnostic, ...]]:
    if not _has_quicktime_microsoft_xtra_write_tags(request):
        return None, ()
    if not request.paths:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public Microsoft Xtra execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    mixed_diagnostic = _unsupported_mixed_quicktime_microsoft_xtra_write_diagnostic(request)
    if mixed_diagnostic is not None:
        return None, (mixed_diagnostic,)
    unsupported_paths: JsonArray = [
        path.as_posix()
        for path in request.paths
        if path.suffix.lower() not in _QUICKTIME_METADATA_WRITE_SUFFIXES
    ]
    if unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_quicktime_microsoft_xtra_write_path",
                message=(
                    "Public Microsoft Xtra assignment execution is limited to "
                    "QuickTime-family MOV/MP4/M4A/M4V/3GP/QT targets."
                ),
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": _json_string_array(
                        sorted(_QUICKTIME_METADATA_WRITE_SUFFIXES)
                    ),
                    "evidence_ids": _public_quicktime_microsoft_xtra_evidence_ids_json(),
                },
            ),
        )
    assignments: list[MicrosoftXtraAssignment] = []
    unsupported_tags: JsonArray = []
    invalid_values: JsonArray = []
    for assignment in request.assignments:
        group, local_name = _normalized_tag_parts(assignment.tag)
        if group != "microsoft" or microsoft_xtra_tag_spec(local_name) is None:
            unsupported_tags.append(assignment.tag)
            continue
        classified = classify_microsoft_xtra_assignment(local_name, assignment.value)
        if isinstance(classified, MicrosoftXtraBlocker):
            invalid_values.append(
                {
                    "tag": assignment.tag,
                    "value": assignment.value,
                    "reason": classified.message,
                    "source": classified.source,
                }
            )
            continue
        assignments.append(classified)
    if unsupported_tags:
        return None, (
            Diagnostic(
                code="unsupported_quicktime_microsoft_xtra_write_tag",
                message=(
                    "Public Microsoft Xtra assignment execution supports only "
                    "Microsoft:Director and Microsoft:SharedUserRating."
                ),
                details={
                    "unsupported_tags": unsupported_tags,
                    "supported_tags": ["Microsoft:Director", "Microsoft:SharedUserRating"],
                    "evidence_ids": _public_quicktime_microsoft_xtra_evidence_ids_json(),
                },
            ),
        )
    if invalid_values:
        return None, (
            Diagnostic(
                code="unsupported_quicktime_microsoft_xtra_write_value",
                message="Public Microsoft Xtra assignment value failed source-backed validation.",
                details={
                    "invalid_values": invalid_values,
                    "evidence_ids": _public_quicktime_microsoft_xtra_evidence_ids_json(),
                },
            ),
        )
    return (
        _PreparedQuickTimeMicrosoftXtraWrite(
            paths=request.paths,
            assignments=tuple(assignments),
            backup_policy=_backup_policy(request),
            tags=tuple(assignment.tag for assignment in request.assignments),
        ),
        (),
    )


def _execute_quicktime_microsoft_xtra_write(
    request: MetadataWriteRequest,
    prepared: _PreparedQuickTimeMicrosoftXtraWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    preflight: list[tuple[Path, bytes, bytes, int]] = []
    execution_diagnostics: list[Diagnostic] = []
    for path in prepared.paths:
        try:
            original_data = path.read_bytes()
            rewrite_result = rewrite_microsoft_xtra(original_data, prepared.assignments)
            if rewrite_result.deferred:
                execution_diagnostics.append(
                    Diagnostic(
                        code="unsupported_quicktime_microsoft_xtra_write_surface",
                        message=(
                            "Microsoft Xtra writer deferred this target before any "
                            "public writes were committed."
                        ),
                        details={
                            "path": path.as_posix(),
                            "deferred": _json_string_array(rewrite_result.deferred),
                            "evidence_ids": (_public_quicktime_microsoft_xtra_evidence_ids_json()),
                        },
                    )
                )
                continue
            preflight.append(
                (path, original_data, rewrite_result.data, rewrite_result.changed_atoms)
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native Microsoft Xtra write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=(),
        )

    changed_paths: list[Path] = []
    changed_atoms_by_path: JsonArray = []
    for path, original_data, rewritten_data, changed_atoms in preflight:
        if rewritten_data != original_data:
            _write_rewritten_bytes_transactionally(
                request,
                path,
                rewritten_data,
                prepared.backup_policy,
            )
            changed_paths.append(path)
        changed_atoms_by_path.append(
            {
                "path": path.as_posix(),
                "changed_atoms": changed_atoms,
                "changed": rewritten_data != original_data,
            }
        )
    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public QuickTime Microsoft Xtra assignment executed through the "
                    "package-local QuickTime Xtra atom writer after all-target preflight."
                ),
                details={
                    "action": "run_modern_quicktime_microsoft_xtra_writer",
                    "native_callable": (
                        "exifmodern.formats.quicktime.fanout_writer.rewrite_microsoft_xtra"
                    ),
                    "changed_paths": _json_string_array(path.as_posix() for path in changed_paths),
                    "tags": _json_string_array(prepared.tags),
                    "changed_atoms_by_path": changed_atoms_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_quicktime_microsoft_xtra_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _has_quicktime_microsoft_xtra_write_tags(request: MetadataWriteRequest) -> bool:
    return any(
        _quicktime_microsoft_xtra_tag_has_owned_group(tag)
        for tag in (
            *(assignment.tag for assignment in request.assignments),
            *request.deletes,
        )
    )


def _quicktime_microsoft_xtra_tag_has_owned_group(tag: str) -> bool:
    group, _local_name = _normalized_tag_parts(tag)
    return group == "microsoft"


def _unsupported_mixed_quicktime_microsoft_xtra_write_diagnostic(
    request: MetadataWriteRequest,
) -> Diagnostic | None:
    mixed_surfaces: JsonArray = []
    if request.deletes:
        mixed_surfaces.append("deletes")
    if any(assignment.operation != "set" for assignment in request.assignments):
        mixed_surfaces.append("list_mutation_assignments")
    for assignment in request.assignments:
        group, _local_name = _normalized_tag_parts(assignment.tag)
        if group != "microsoft":
            mixed_surfaces.append("non_microsoft_assignment")
            break
    if request.public_copy_from_file is not None:
        mixed_surfaces.append("public_copy_from_file")
    if request.xmp_sidecar_copy_from_file is not None:
        mixed_surfaces.append("xmp_sidecar_copy_from_file")
    if request.exif_sidecar_copy_from_file is not None:
        mixed_surfaces.append("exif_sidecar_copy_from_file")
    if request.png_chunk_write is not None:
        mixed_surfaces.append("png_chunk_write")
    if request.riff_wav_metadata_write is not None:
        mixed_surfaces.append("riff_wav_metadata_write")
    if request.riff_webp_metadata_write is not None:
        mixed_surfaces.append("riff_webp_metadata_write")
    if not mixed_surfaces:
        return None
    return Diagnostic(
        code="unsupported_mixed_quicktime_microsoft_xtra_write_shape",
        message=(
            "Public QuickTime Microsoft Xtra execution is bounded to assignment-only "
            "direct set operations and does not mix with deletes, copy routes, list "
            "mutations, or non-Microsoft assignment tags."
        ),
        details={
            "mixed_surfaces": mixed_surfaces,
            "assignments": [assignment.tag for assignment in request.assignments],
            "deletes": list(request.deletes),
            "delete_blocker": (
                "ExifTool Microsoft.pm WriteXtra supports Microsoft group deletion, "
                "but ExifModern's package-local Xtra writer currently owns assignment "
                "upsert only, so public Xtra deletes remain blocked."
            ),
            "evidence_ids": _public_quicktime_microsoft_xtra_evidence_ids_json(),
        },
    )


def _execute_quicktime_metadata_write(
    request: MetadataWriteRequest,
    prepared: _PreparedQuickTimeMetadataWrite,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    changed_atoms_by_path: JsonArray = []
    for path in prepared.paths:
        try:
            original_data = path.read_bytes()
            rewrite_result = rewrite_quicktime_metadata(original_data, prepared.plan)
            if rewrite_result.deferred:
                execution_diagnostics.append(
                    Diagnostic(
                        code="unsupported_quicktime_metadata_write_surface",
                        message=(
                            "QuickTime metadata writer deferred one or more requested surfaces."
                        ),
                        details={
                            "path": path.as_posix(),
                            "deferred": _json_string_array(rewrite_result.deferred),
                            "evidence_ids": (_public_quicktime_metadata_write_evidence_ids_json()),
                        },
                    )
                )
                continue
            if rewrite_result.data != original_data:
                _write_rewritten_bytes_transactionally(
                    request,
                    path,
                    rewrite_result.data,
                    prepared.backup_policy,
                )
                changed_paths.append(path)
            changed_atoms_by_path.append(
                {
                    "path": path.as_posix(),
                    "changed_atoms": rewrite_result.changed_atoms,
                    "changed": rewrite_result.data != original_data,
                }
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native QuickTime metadata write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )
    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )
    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan_diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public QuickTime ItemList/UserData/Keys metadata assignment/delete "
                    "executed through the package-local QuickTime atom writer."
                ),
                details={
                    "action": "run_modern_quicktime_metadata_writer",
                    "native_callable": (
                        "exifmodern.formats.quicktime.metadata_writer.rewrite_quicktime_metadata"
                    ),
                    "changed_paths": _json_string_array(path.as_posix() for path in changed_paths),
                    "tags": _json_string_array(prepared.tags),
                    "changed_atoms_by_path": changed_atoms_by_path,
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _public_quicktime_metadata_write_evidence_ids_json(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _has_quicktime_metadata_write_tags(request: MetadataWriteRequest) -> bool:
    return any(
        _quicktime_metadata_tag_has_owned_group(tag)
        for tag in (
            *(assignment.tag for assignment in request.assignments),
            *request.deletes,
        )
    )


def _quicktime_metadata_tag_has_owned_group(tag: str) -> bool:
    group, _local_name = _normalized_tag_parts(tag)
    return group in {"quicktime", "itemlist", "userdata", "keys", "audiokeys", "videokeys"}


def _unsupported_mixed_quicktime_metadata_write_diagnostic(
    request: MetadataWriteRequest,
) -> Diagnostic | None:
    mixed_surfaces: JsonArray = []
    if any(assignment.operation != "set" for assignment in request.assignments):
        mixed_surfaces.append("list_mutation_assignments")
    if request.public_copy_from_file is not None:
        mixed_surfaces.append("public_copy_from_file")
    if request.xmp_sidecar_copy_from_file is not None:
        mixed_surfaces.append("xmp_sidecar_copy_from_file")
    if request.exif_sidecar_copy_from_file is not None:
        mixed_surfaces.append("exif_sidecar_copy_from_file")
    if request.png_chunk_write is not None:
        mixed_surfaces.append("png_chunk_write")
    if request.riff_wav_metadata_write is not None:
        mixed_surfaces.append("riff_wav_metadata_write")
    if request.riff_webp_metadata_write is not None:
        mixed_surfaces.append("riff_webp_metadata_write")
    if not mixed_surfaces:
        return None
    return Diagnostic(
        code="unsupported_mixed_quicktime_metadata_write_shape",
        message=(
            "Public QuickTime metadata execution is bounded to direct set/delete "
            "operations and does not mix with copy routes, list mutations, or typed "
            "container write requests."
        ),
        details={
            "mixed_surfaces": mixed_surfaces,
            "assignments": [assignment.tag for assignment in request.assignments],
            "deletes": list(request.deletes),
            "evidence_ids": _public_quicktime_metadata_write_evidence_ids_json(),
        },
    )


def _quicktime_metadata_write_args(request: MetadataWriteRequest) -> tuple[str, ...]:
    operations: list[tuple[int, str]] = []
    fallback_order = 0
    for assignment in request.assignments:
        order_index = assignment.order_index
        if order_index is None:
            order_index = fallback_order
            fallback_order += 1
        operations.append((order_index, f"-{assignment.tag}={assignment.value}"))
    for index, delete in enumerate(request.deletes):
        order_index = (
            request.delete_order_indexes[index]
            if index < len(request.delete_order_indexes)
            else fallback_order
        )
        if index >= len(request.delete_order_indexes):
            fallback_order += 1
        operations.append((order_index, f"-{delete}="))
    return tuple(arg for _order_index, arg in sorted(operations, key=lambda item: item[0]))


def _prepare_pdf_metadata_delete_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedPdfMetadataDeleteWrite | None, tuple[Diagnostic, ...]]:
    if not request.deletes:
        return None, ()
    if not any(path.suffix.lower() == ".pdf" for path in request.paths):
        return None, ()
    if request.assignments:
        return None, (
            Diagnostic(
                code="unsupported_mixed_pdf_metadata_delete_shape",
                message=(
                    "Public PDF metadata delete execution is bounded to delete-only "
                    "unqualified All requests."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                },
            ),
        )
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() != ".pdf"
    ]
    if not request.paths or unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_pdf_metadata_delete_path",
                message="Public PDF metadata delete execution is limited to PDF targets.",
                details={"unsupported_paths": unsupported_paths, "supported_suffixes": [".pdf"]},
            ),
        )
    unsupported_deletes: JsonArray = [
        delete for delete in request.deletes if _normalized_tag(delete) != "all"
    ]
    if unsupported_deletes:
        return None, (
            Diagnostic(
                code="unsupported_pdf_metadata_delete_tag",
                message=(
                    "Public PDF metadata delete execution supports only the source-backed "
                    "unqualified All delete route."
                ),
                details={
                    "unsupported_tags": unsupported_deletes,
                    "supported_tags": ["All"],
                    "evidence_ids": ["public.write.pdf.info"],
                },
            ),
        )
    return (
        _PreparedPdfMetadataDeleteWrite(
            paths=request.paths,
            backup_policy=_backup_policy(request),
            tags=request.deletes,
        ),
        (),
    )


def _prepare_pdf_info_scalar_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedPdfInfoScalarWrite | None, tuple[Diagnostic, ...]]:
    if not request.assignments:
        return None, ()
    if not any(path.suffix.lower() == ".pdf" for path in request.paths):
        return None, ()
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() != ".pdf"
    ]
    if not request.paths or unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_pdf_info_scalar_path",
                message="Public PDF Info scalar writes are limited to PDF targets.",
                details={"unsupported_paths": unsupported_paths, "supported_suffixes": [".pdf"]},
            ),
        )
    if request.deletes:
        return None, (
            Diagnostic(
                code="unsupported_mixed_pdf_info_scalar_shape",
                message=(
                    "Public PDF Info scalar execution is bounded to assignment-only "
                    "Title, Author, Subject, and Keywords writes."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                },
            ),
        )
    list_assignments: JsonArray = [
        assignment.tag for assignment in request.assignments if assignment.operation != "set"
    ]
    if list_assignments:
        return None, (
            Diagnostic(
                code="unsupported_pdf_info_scalar_list_mutation",
                message="Public PDF Info scalar writes do not execute +=/-= list mutations.",
                details={
                    "list_mutation_tags": list_assignments,
                    "supported_tags": _json_string_array(sorted(PDF_INFO_SCALAR_TAGS)),
                },
            ),
        )
    unsupported_tags = [
        assignment.tag
        for assignment in request.assignments
        if canonical_pdf_info_scalar_tag(assignment.tag) is None
    ]
    if unsupported_tags:
        if all(_normalized_tag(tag) in _SUPPORTED_XMP_SCALAR_TAGS for tag in unsupported_tags):
            return None, ()
        return None, (
            Diagnostic(
                code="unsupported_pdf_info_scalar_tag",
                message=(
                    "Public PDF Info scalar writes are source-backed only for Title, "
                    "Author, Subject, and Keywords. Non-XMP PDF assignments remain "
                    "outside this bounded writer."
                ),
                details={
                    "unsupported_tags": _json_string_array(unsupported_tags),
                    "supported_tags": _json_string_array(sorted(PDF_INFO_SCALAR_TAGS)),
                    "evidence_ids": list(_pdf_info_write_evidence_ids()),
                },
            ),
        )
    assignments = tuple(
        PdfInfoScalarAssignment(
            canonical_pdf_info_scalar_tag(assignment.tag) or assignment.tag,
            assignment.value,
        )
        for assignment in request.assignments
    )
    return (
        _PreparedPdfInfoScalarWrite(
            paths=request.paths,
            backup_policy=_backup_policy(request),
            assignments=assignments,
            tags=tuple(assignment.tag for assignment in request.assignments),
        ),
        (),
    )


def _prepare_xmp_property_delete_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedXmpSidecarWrite | None, tuple[Diagnostic, ...]]:
    if not request.deletes:
        return None, ()
    if not all(_normalized_tag(delete) in _SUPPORTED_XMP_SCALAR_TAGS for delete in request.deletes):
        return None, ()
    if request.assignments:
        return None, (
            Diagnostic(
                code="unsupported_mixed_xmp_property_delete_shape",
                message=(
                    "Public XMP property delete execution is bounded to delete-only "
                    "scalar-property requests."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                },
            ),
        )
    unsupported_paths: JsonArray = [
        path.as_posix()
        for path in request.paths
        if path.suffix.lower() not in _SUPPORTED_XMP_ASSIGNMENT_SUFFIXES
    ]
    if not request.paths or unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_xmp_property_delete_path",
                message=(
                    "Public XMP property delete execution is bounded to existing XMP "
                    "sidecar, JPEG APP1, PNG iTXt, WebP XMP, QuickTime XMP, JP2 UUID "
                    "XMP, JXL XML XMP, and PDF /Metadata stream writer routes."
                ),
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": _json_string_array(
                        sorted(_SUPPORTED_XMP_ASSIGNMENT_SUFFIXES)
                    ),
                    "evidence_ids": _public_xmp_assignment_evidence_ids_json(),
                },
            ),
        )
    plan = build_public_xmp_sidecar_property_delete_plan(
        tuple(
            XmpPublicSidecarPropertyDelete(_canonical_xmp_public_sidecar_property_name(delete))
            for delete in request.deletes
        )
    )
    if plan.generated_diagnostics:
        return None, (
            Diagnostic(
                code="unsupported_xmp_property_delete_tag",
                message=(
                    "Public XMP property delete execution could not build a bounded "
                    "source-backed delete plan."
                ),
                details={
                    "diagnostics": [
                        {
                            "property_name": diagnostic.property_name,
                            "reason": diagnostic.reason,
                            "detail": diagnostic.detail,
                        }
                        for diagnostic in plan.generated_diagnostics
                    ],
                    "supported_tags": _json_string_array(sorted(_SUPPORTED_XMP_SCALAR_TAGS)),
                },
            ),
        )
    return (
        _PreparedXmpSidecarWrite(
            paths=request.paths,
            plan=plan,
            backup_policy=_backup_policy(request),
            tags=request.deletes,
        ),
        (),
    )


def _prepare_xmp_sidecar_scalar_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedXmpSidecarWrite | None, tuple[Diagnostic, ...]]:
    if not request.paths:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    if request.deletes:
        return None, (
            Diagnostic(
                code="not_yet_implemented_public_write_shape",
                message="Public native write execution does not support deletes yet.",
                details={"deletes": list(request.deletes)},
            ),
        )
    if not request.assignments:
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one assignment.",
                details={"reason": "missing_assignments"},
            ),
        )
    list_assignments: JsonArray = [
        assignment.tag for assignment in request.assignments if assignment.operation != "set"
    ]
    if list_assignments:
        return None, (
            Diagnostic(
                code="unsupported_xmp_sidecar_property_write",
                message=(
                    "Public XMP scalar sidecar writes do not execute +=/-= list mutations; "
                    "only the bounded XMP-dc:Subject list mutation route may handle them."
                ),
                details={
                    "list_mutation_tags": list_assignments,
                    "supported_list_mutation_tags": _json_string_array(("XMP-dc:Subject",)),
                    "evidence_ids": _public_list_mutation_evidence_ids_json(),
                },
            ),
        )

    exif_sidecar_copy_diagnostics = _exif_sidecar_copy_from_file_shape_diagnostics(request)
    if exif_sidecar_copy_diagnostics:
        return None, exif_sidecar_copy_diagnostics

    unsupported_paths: JsonArray = [
        path.as_posix()
        for path in request.paths
        if path.suffix.lower() not in _SUPPORTED_XMP_ASSIGNMENT_SUFFIXES
    ]
    if unsupported_paths:
        return None, (
            Diagnostic(
                code="not_yet_implemented_public_write_shape",
                message=(
                    "Public native XMP assignment execution is bounded to existing "
                    "XMP sidecar, JPEG APP1, PNG iTXt, WebP XMP, QuickTime XMP, "
                    "JP2 UUID XMP, JXL XML XMP, and PDF /Metadata stream writer routes."
                ),
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": _json_string_array(
                        sorted(_SUPPORTED_XMP_ASSIGNMENT_SUFFIXES)
                    ),
                    "evidence_ids": _public_xmp_assignment_evidence_ids_json(),
                },
            ),
        )

    copy_from_file_diagnostics = _xmp_sidecar_copy_from_file_shape_diagnostics(request.assignments)
    if copy_from_file_diagnostics:
        return None, copy_from_file_diagnostics

    unsupported_tags: JsonArray = [
        assignment.tag
        for assignment in request.assignments
        if _normalized_tag(assignment.tag) not in _SUPPORTED_XMP_SCALAR_TAGS
    ]
    supported_tags: JsonArray = [tag for tag in sorted(_SUPPORTED_XMP_SCALAR_TAGS)]
    if unsupported_tags:
        return None, (
            Diagnostic(
                code="not_yet_implemented_public_write_shape",
                message=(
                    "Public native write execution supports only a bounded XMP "
                    "sidecar scalar-property allowlist."
                ),
                details={
                    "unsupported_tags": unsupported_tags,
                    "supported_tags": supported_tags,
                },
            ),
        )

    xmp_plan = _xmp_scalar_plan(request.assignments, request.list_separator)
    if xmp_plan.generated_diagnostics:
        return None, (
            Diagnostic(
                code="unsupported_xmp_sidecar_property_write",
                message=(
                    "Public XMP sidecar property write could not build a bounded "
                    "source-backed write plan."
                ),
                details={
                    "diagnostics": [
                        {
                            "property_name": diagnostic.property_name,
                            "reason": diagnostic.reason,
                            "detail": diagnostic.detail,
                        }
                        for diagnostic in xmp_plan.generated_diagnostics
                    ],
                    "supported_tags": supported_tags,
                },
            ),
        )

    return (
        _PreparedXmpSidecarWrite(
            paths=request.paths,
            plan=xmp_plan,
            backup_policy=_backup_policy(request),
            tags=tuple(assignment.tag for assignment in request.assignments),
        ),
        (),
    )


def _xmp_scalar_plan(
    assignments: tuple[MetadataAssignment, ...],
    list_separator: str | None,
) -> XmpPropertyWritePlan:
    return build_public_xmp_sidecar_property_write_plan(
        tuple(
            XmpPublicSidecarPropertyAssignment(
                _canonical_xmp_public_sidecar_property_name(assignment.tag),
                assignment.value,
            )
            for assignment in assignments
        ),
        list_separator,
    )


def _has_public_list_mutation_assignment(request: MetadataWriteRequest) -> bool:
    return any(assignment.operation != "set" for assignment in request.assignments)


def _unsupported_mixed_public_list_mutation_copy_diagnostics(
    request: MetadataWriteRequest,
) -> tuple[Diagnostic, ...]:
    if not _has_public_list_mutation_assignment(request):
        return ()
    if (
        request.public_copy_from_file is None
        and request.xmp_sidecar_copy_from_file is None
        and request.exif_sidecar_copy_from_file is None
    ):
        return ()
    return (
        Diagnostic(
            code="unsupported_mixed_public_list_mutation_copy_shape",
            message=(
                "Public +=/-= list mutation syntax is parsed, but mixed copy/list "
                "operations are not executed by the bounded public writer."
            ),
            details={
                "list_mutations": [
                    {
                        "tag": assignment.tag,
                        "operation": assignment.operation,
                        "value": assignment.value,
                        "order_index": assignment.order_index,
                    }
                    for assignment in request.assignments
                    if assignment.operation != "set"
                ],
                "has_public_copy_from_file": request.public_copy_from_file is not None,
                "has_xmp_sidecar_copy_from_file": request.xmp_sidecar_copy_from_file is not None,
                "has_exif_sidecar_copy_from_file": request.exif_sidecar_copy_from_file is not None,
                "evidence_ids": _public_list_mutation_evidence_ids_json(),
            },
        ),
    )


def _unsupported_jpeg_xmp_subject_list_mutation_packet_diagnostic(
    request: MetadataWriteRequest,
) -> Diagnostic | None:
    unsupported_paths: JsonArray = []
    for path in request.paths:
        if path.suffix.lower() not in _JPEG_SUFFIXES:
            continue
        try:
            has_standard_xmp = _jpeg_path_has_standard_xmp_app1(path)
        except OSError:
            has_standard_xmp = False
        if not has_standard_xmp:
            unsupported_paths.append(path.as_posix())
    if not unsupported_paths:
        return None
    return Diagnostic(
        code="unsupported_xmp_sidecar_list_mutation_path",
        message=(
            "Public JPEG XMP-dc:Subject +=/-= list mutation is bounded to targets "
            "with an existing standard XMP APP1 packet; creating embedded XMP APP1 "
            "from public list mutation syntax remains deferred."
        ),
        details={
            "unsupported_paths": unsupported_paths,
            "supported_suffixes": [".xmp", *sorted(_JPEG_SUFFIXES)],
            "unsupported_surface": "missing_standard_xmp_app1",
            "evidence_ids": _public_list_mutation_evidence_ids_json(),
        },
    )


def _jpeg_path_has_standard_xmp_app1(path: Path) -> bool:
    return any(
        probe.marker == 0xE1 and probe.payload_prefix.startswith(XMP_APP1_PREFIX)
        for probe in read_jpeg_segment_probes(path, prefix_length=len(XMP_APP1_PREFIX))
    )


def _xmp_dc_subject_values_from_public_target(path: Path, data: bytes) -> tuple[str, ...]:
    if path.suffix.lower() == ".xmp":
        return _xmp_dc_subject_values(data)
    return _jpeg_xmp_dc_subject_values(data)


def _jpeg_xmp_dc_subject_values(jpeg_data: bytes) -> tuple[str, ...]:
    segment = first_standard_xmp_app1_segment(jpeg_data)
    if segment is None:
        return ()
    payload = segment_payload(jpeg_data, segment)
    return _xmp_dc_subject_values(payload[len(XMP_APP1_PREFIX) :])


def _xmp_dc_subject_values(packet: bytes) -> tuple[str, ...]:
    subject = parse_xmp_packet(packet).get("XMP-dc", {}).get("Subject")
    if subject is None:
        return ()
    if isinstance(subject, str):
        return (subject,)
    if isinstance(subject, list):
        return tuple(item for item in subject if isinstance(item, str))
    return (str(subject),)


def _xmp_subject_values_after_public_list_mutations(
    existing_values: tuple[str, ...],
    assignments: tuple[MetadataAssignment, ...],
    list_separator: str | None,
) -> tuple[str, ...]:
    values = list(existing_values)
    for assignment in assignments:
        assignment_values = _public_list_assignment_values(assignment.value, list_separator)
        if assignment.operation == "set":
            values = list(assignment_values)
            continue
        if assignment.operation == "add_list_value":
            values.extend(assignment_values)
            continue
        values = [
            existing_value
            for existing_value in values
            if existing_value not in frozenset(assignment_values)
        ]
    return tuple(values)


def _jpeg_iptc_keywords_values(jpeg_data: bytes) -> tuple[str, ...]:
    segment = first_photoshop_app13_segment(jpeg_data)
    if segment is None:
        return ()
    payload = segment_payload(jpeg_data, segment)
    keywords = parse_iptc_application_record(
        existing_iptc_resource_data(parse_photoshop_resources(payload))
    ).get("Keywords")
    if keywords is None:
        return ()
    if isinstance(keywords, str):
        return (keywords,)
    if isinstance(keywords, list):
        return tuple(keyword for keyword in keywords if isinstance(keyword, str))
    return (str(keywords),)


def _iptc_keywords_values_after_public_list_mutations(
    existing_values: tuple[str, ...],
    assignments: tuple[MetadataAssignment, ...],
    list_separator: str | None,
) -> tuple[str, ...]:
    values = list(existing_values)
    for assignment in assignments:
        assignment_values = _public_list_assignment_values(assignment.value, list_separator)
        if assignment.operation == "set":
            values = list(assignment_values)
            continue
        if assignment.operation == "add_list_value":
            values.extend(assignment_values)
            continue
        values = [
            existing_value
            for existing_value in values
            if existing_value not in frozenset(assignment_values)
        ]
    return tuple(values)


def _public_list_assignment_values(value: str, list_separator: str | None) -> tuple[str, ...]:
    if list_separator is None:
        return (value,)
    return split_xmp_public_list_value(value, list_separator)


def _xmp_subject_replacement_plan(values: tuple[str, ...]) -> XmpPropertyWritePlan:
    if not values:
        return build_public_xmp_sidecar_property_delete_plan(
            (XmpPublicSidecarPropertyDelete("XMP-dc:Subject"),)
        )
    return build_public_xmp_sidecar_property_write_plan(
        tuple(XmpPublicSidecarPropertyAssignment("XMP-dc:Subject", value) for value in values)
    )


def _iptc_keywords_replacement_plan(values: tuple[str, ...]) -> IptcApplicationWritePlan:
    if not values:
        return IptcApplicationWritePlan((text_step("delete", "Keywords", ()),))
    return IptcApplicationWritePlan((upsert_text_step("Keywords", values),))


def _public_list_mutation_evidence_ids() -> tuple[str, ...]:
    return (
        "public.write.list-mutation.writer",
        "public.write.list-mutation.tables",
        "public.write.iptc.assignment",
        "public.write.iptc.rewrite",
    )


def _public_list_mutation_evidence_ids_json() -> JsonArray:
    return _json_string_array(_public_list_mutation_evidence_ids())


def _public_iptc_assignment_evidence_ids() -> tuple[str, ...]:
    return (
        "public.write.iptc.assignment",
        "public.write.iptc.rewrite",
    )


def _public_iptc_assignment_evidence_ids_json() -> JsonArray:
    return _json_string_array(_public_iptc_assignment_evidence_ids())


def _public_quicktime_metadata_write_evidence_ids() -> tuple[str, ...]:
    return ("public.write.quicktime.metadata",)


def _public_quicktime_metadata_write_evidence_ids_json() -> JsonArray:
    return _json_string_array(_public_quicktime_metadata_write_evidence_ids())


def _public_quicktime_microsoft_xtra_evidence_ids() -> tuple[str, ...]:
    return ("public.write.quicktime.microsoft-xtra",)


def _public_quicktime_microsoft_xtra_evidence_ids_json() -> JsonArray:
    return _json_string_array(_public_quicktime_microsoft_xtra_evidence_ids())


def _public_xmp_assignment_evidence_ids() -> tuple[str, ...]:
    return (
        "public.write.exact-copy.tag-lookup",
        "public.write.exact-copy.writer-routing",
        "public.write.xmp.assignment",
        "public.write.webp.icc-profile",
        "public.write.quicktime.metadata",
        "public.write.pdf.info",
    )


def _public_xmp_assignment_evidence_ids_json() -> JsonArray:
    return _json_string_array(_public_xmp_assignment_evidence_ids())


def _canonical_xmp_public_sidecar_property_name(tag: str) -> str:
    normalized = _normalized_tag(tag)
    for property_name in XMP_PUBLIC_SIDECAR_PROPERTY_NAMES:
        if property_name.lower() == normalized:
            return property_name
    return tag


def _xmp_sidecar_copy_from_file_shape_diagnostics(
    assignments: tuple[MetadataAssignment, ...],
) -> tuple[Diagnostic, ...]:
    copy_route_assignments = [
        assignment
        for assignment in assignments
        if _assignment_looks_like_xmp_sidecar_copy_from_file_route(assignment)
    ]
    if not copy_route_assignments:
        return ()
    return (
        Diagnostic(
            code="not_yet_implemented_public_copy_from_file_shape",
            message=(
                "Public XMP sidecar copy-from-file execution is deferred because "
                "MetadataWriteRequest does not yet model a tagsFromFile source path "
                "and copy route separately from scalar assignments."
            ),
            details={
                "unsupported_shape": "xmp_sidecar_copy_from_file",
                "requested_tags": [assignment.tag for assignment in copy_route_assignments],
                "requested_values": [assignment.value for assignment in copy_route_assignments],
                "existing_callable": (
                    "exifmodern.formats.xmp.sidecar_copy_writer."
                    "rewrite_xmp_sidecar_copy_from_file_to_path"
                ),
                "existing_planner": (
                    "exifmodern.formats.xmp.copy_from_file_plan.parse_xmp_copy_from_file_args"
                ),
                "next_integration_seam": (
                    "Add typed public request fields for tagsFromFile source_path "
                    "and copy routes, then translate them into XmpCopyFromFilePlan "
                    "before calling the package-local sidecar copy writer."
                ),
                "evidence_ids": [
                    "public.write.copy-from-file.writer-routing",
                    "public.write.xmp.assignment",
                    "public.write.sidecar.xmp-copy",
                ],
            },
        ),
    )


def _assignment_looks_like_xmp_sidecar_copy_from_file_route(
    assignment: MetadataAssignment,
) -> bool:
    tag = assignment.tag.strip()
    normalized_tag = _normalized_tag(tag)
    if normalized_tag in {"tagsfromfile", "-tagsfromfile"}:
        return True
    if ">" in tag:
        return True
    if normalized_tag in {"all", "all:all", "xmp:all", "exif:* > xmp:*"}:
        return _value_looks_like_public_copy_source_path(assignment.value)
    return False


def _exif_sidecar_copy_from_file_shape_diagnostics(
    request: MetadataWriteRequest,
) -> tuple[Diagnostic, ...]:
    if not _request_targets_only_exif_sidecars(request):
        return ()
    copy_route_assignments = [
        assignment
        for assignment in request.assignments
        if _assignment_looks_like_exif_sidecar_copy_from_file_route(assignment)
    ]
    if not copy_route_assignments:
        return ()
    report = exif_sidecar_public_execution_boundary_report()
    details = report.to_json_object()
    details["requested_tags"] = [assignment.tag for assignment in copy_route_assignments]
    details["requested_values"] = [assignment.value for assignment in copy_route_assignments]
    details["target_paths"] = [path.as_posix() for path in request.paths]
    return (
        Diagnostic(
            code="not_yet_implemented_public_exif_sidecar_copy_from_file_shape",
            message=(
                "Public EXIF sidecar copy-from-file execution is deferred because "
                "MetadataWriteRequest does not yet expose a typed EXIF tagsFromFile "
                "source route or public backup-policy-safe EXIF sidecar writer call."
            ),
            details=details,
        ),
    )


def _request_targets_only_exif_sidecars(request: MetadataWriteRequest) -> bool:
    return bool(request.paths) and all(path.suffix.lower() == ".exif" for path in request.paths)


def _assignment_looks_like_exif_sidecar_copy_from_file_route(
    assignment: MetadataAssignment,
) -> bool:
    tag = assignment.tag.strip()
    normalized_tag = _normalized_tag(tag)
    if normalized_tag in {"tagsfromfile", "-tagsfromfile", "exif", "exif:all", "exif:*"}:
        return _value_looks_like_exif_sidecar_copy_source_path(assignment.value)
    return False


def _value_looks_like_exif_sidecar_copy_source_path(value: str) -> bool:
    suffix = Path(value.strip()).suffix.lower()
    return suffix in {".jpg", ".jpeg", ".jpe", ".exif"}


def _value_looks_like_public_copy_source_path(value: str) -> bool:
    source = value.strip()
    suffix = Path(source).suffix.lower()
    return (
        "/" in source
        or "\\" in source
        or suffix in {".jpg", ".jpeg", ".jpe", ".xmp", ".tif", ".tiff"}
    )


def _prepare_jpeg_exif_scalar_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedJpegExifScalarWrite | None, tuple[Diagnostic, ...]]:
    shape_diagnostics = _basic_exif_scalar_write_shape_diagnostics(request)
    if shape_diagnostics:
        return None, shape_diagnostics

    missing_paths: JsonArray = [path.as_posix() for path in request.paths if not path.exists()]
    if missing_paths:
        return None, (
            Diagnostic(
                code="not_yet_implemented_public_write_shape",
                message=(
                    "Public JPEG EXIF scalar native write execution requires existing "
                    "target files; missing-path writes stay in the planned/deferred "
                    "public write surface."
                ),
                details={
                    "missing_paths": missing_paths,
                    "evidence_ids": _public_exif_scalar_delete_evidence_ids(),
                },
            ),
        )

    mixed_family_diagnostics = _mixed_assignment_family_diagnostics(request.assignments)
    if mixed_family_diagnostics:
        return None, mixed_family_diagnostics

    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() not in _JPEG_SUFFIXES
    ]
    if unsupported_paths:
        supported_suffixes: JsonArray = [suffix for suffix in sorted(_JPEG_SUFFIXES)]
        return None, (
            Diagnostic(
                code="unsupported_mixed_path_types",
                message=(
                    "Public JPEG EXIF scalar native write execution requires JPEG/JPG/JPE "
                    "targets only."
                ),
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": supported_suffixes,
                },
            ),
        )

    normalized_delete_tags, delete_diagnostics = _normalized_exif_scalar_delete_tags(
        request.deletes
    )
    if delete_diagnostics:
        return None, delete_diagnostics
    if normalized_delete_tags:
        scalar_plan = _build_public_exif_scalar_delete_plan(set(normalized_delete_tags))
        return (
            _PreparedJpegExifScalarWrite(
                paths=request.paths,
                plan=scalar_plan,
                backup_policy=_backup_policy(request),
                tags=request.deletes,
            ),
            (),
        )

    normalized_tags, tag_diagnostics = _normalized_exif_scalar_assignment_tags(request.assignments)
    if tag_diagnostics:
        return None, tag_diagnostics

    values = {
        normalized_tag: assignment.value
        for normalized_tag, assignment in zip(normalized_tags, request.assignments, strict=True)
    }
    try:
        scalar_plan = build_exif_scalar_write_plan(
            image_description=values.get("ImageDescription"),
            orientation=values.get("Orientation"),
            date_time_original=values.get("DateTimeOriginal"),
            modify_date=values.get("ModifyDate"),
            artist=values.get("Artist"),
            iso=values.get("ISO"),
            focal_length=values.get("FocalLength"),
            scene_capture_type=values.get("SceneCaptureType"),
        )
    except ValueError as exc:
        return None, (
            Diagnostic(
                code="unsupported_exif_scalar_value_format",
                message=f"Public JPEG EXIF scalar native write execution rejected a value: {exc}",
                details={"error": str(exc)},
            ),
        )

    return (
        _PreparedJpegExifScalarWrite(
            paths=request.paths,
            plan=scalar_plan,
            backup_policy=_backup_policy(request),
            tags=tuple(assignment.tag for assignment in request.assignments),
        ),
        (),
    )


def _basic_exif_scalar_write_shape_diagnostics(
    request: MetadataWriteRequest,
) -> tuple[Diagnostic, ...]:
    if not request.paths:
        return (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    if request.assignments and request.deletes:
        return (
            Diagnostic(
                code="not_yet_implemented_public_write_shape",
                message=(
                    "Public JPEG EXIF scalar assignment/delete execution supports "
                    "assignment-only or delete-only requests; mixed unordered requests "
                    "remain deferred until command-order effects are preserved."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                    "evidence_ids": _public_exif_scalar_delete_evidence_ids(),
                },
            ),
        )
    if not request.assignments and not request.deletes:
        return (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one assignment or delete.",
                details={"reason": "missing_write_operations"},
            ),
        )
    return ()


def _prepare_vendor_jpeg_composed_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedVendorJpegComposedWrite | None, tuple[Diagnostic, ...]]:
    shape_diagnostics = _basic_write_shape_diagnostics(request)
    if shape_diagnostics:
        return None, shape_diagnostics
    if not _has_vendor_jpeg_composed_write_tags(request):
        return None, (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public vendor JPEG composed write execution requires vendor tags.",
                details={"reason": "missing_vendor_jpeg_composed_tags"},
            ),
        )

    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() not in _JPEG_SUFFIXES
    ]
    if unsupported_paths:
        return None, (
            Diagnostic(
                code="unsupported_mixed_path_types",
                message=(
                    "Public vendor JPEG composed write execution requires JPEG/JPG/JPE "
                    "targets only."
                ),
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": [suffix for suffix in sorted(_JPEG_SUFFIXES)],
                },
            ),
        )

    values = _assignment_values_by_local_tag(request.assignments)
    kind = _vendor_jpeg_composed_kind(request, values)
    if kind == "sanyo":
        return _prepare_sanyo_jpeg_composed_write(request, values)
    if kind == "minolta":
        return _prepare_minolta_jpeg_composed_write(request, values)
    if kind == "casio":
        return _prepare_casio_jpeg_composed_write(request, values)
    return None, (
        Diagnostic(
            code="unsupported_vendor_jpeg_composed_tag",
            message=(
                "Public vendor JPEG composed write execution supports only the "
                "source-backed Sanyo, Minolta, and Casio seed shapes in this slice."
            ),
            details={
                "tags": [assignment.tag for assignment in request.assignments],
                "supported_shapes": [
                    "Sanyo SceneCaptureType + MakerNotes:FlashMode",
                    "Minolta Caption-Abstract + MinoltaDate",
                    "Casio MaxApertureValue + FocusMode",
                    "Casio XResolution + YResolution + ObjectDistance",
                    "Casio FirmwareDate on a known Casio family fixture",
                ],
            },
        ),
    )


def _prepare_sanyo_jpeg_composed_write(
    request: MetadataWriteRequest,
    values: dict[str, str],
) -> tuple[_PreparedVendorJpegComposedWrite | None, tuple[Diagnostic, ...]]:
    unsupported_tags = _unsupported_vendor_tags(
        request.assignments,
        {"FlashMode", "SceneCaptureType"},
    )
    if unsupported_tags:
        return _unsupported_vendor_jpeg_tags("sanyo", unsupported_tags)
    flash_mode = values.get("FlashMode")
    scene_capture_type = values.get("SceneCaptureType")
    if flash_mode is None or scene_capture_type is None:
        return _missing_vendor_jpeg_tags(
            "sanyo",
            ("SceneCaptureType", "FlashMode"),
            values,
        )
    try:
        exif_plan = build_exif_scalar_write_plan(
            image_description=None,
            orientation=None,
            date_time_original=None,
            scene_capture_type=scene_capture_type,
        )
        inline_plan = build_sanyo_flash_mode_write_plan(flash_mode)
    except ValueError as exc:
        return _invalid_vendor_jpeg_value("sanyo", exc)
    return (
        _PreparedVendorJpegComposedWrite(
            paths=request.paths,
            kind="sanyo",
            backup_policy=_backup_policy(request),
            tags=tuple(assignment.tag for assignment in request.assignments),
            exif_plan=exif_plan,
            inline_maker_note_plan=inline_plan,
        ),
        (),
    )


def _prepare_minolta_jpeg_composed_write(
    request: MetadataWriteRequest,
    values: dict[str, str],
) -> tuple[_PreparedVendorJpegComposedWrite | None, tuple[Diagnostic, ...]]:
    unsupported_tags = _unsupported_vendor_tags(
        request.assignments,
        {"Caption-Abstract", "MinoltaDate"},
    )
    if unsupported_tags:
        return _unsupported_vendor_jpeg_tags("minolta", unsupported_tags)
    caption = values.get("Caption-Abstract")
    minolta_date = values.get("MinoltaDate")
    if caption is None or minolta_date is None:
        return _missing_vendor_jpeg_tags(
            "minolta",
            ("Caption-Abstract", "MinoltaDate"),
            values,
        )
    try:
        iptc_plan = IptcApplicationWritePlan((upsert_text_step("Caption-Abstract", (caption,)),))
        binary_plan = build_minolta_date_write_plan(minolta_date)
    except ValueError as exc:
        return _invalid_vendor_jpeg_value("minolta", exc)
    return (
        _PreparedVendorJpegComposedWrite(
            paths=request.paths,
            kind="minolta",
            backup_policy=_backup_policy(request),
            tags=tuple(assignment.tag for assignment in request.assignments),
            binary_maker_note_plan=binary_plan,
            iptc_plan=iptc_plan,
        ),
        (),
    )


def _prepare_casio_jpeg_composed_write(
    request: MetadataWriteRequest,
    values: dict[str, str],
) -> tuple[_PreparedVendorJpegComposedWrite | None, tuple[Diagnostic, ...]]:
    supported_tags = {
        "FirmwareDate",
        "FocusMode",
        "MaxApertureValue",
        "ObjectDistance",
        "XResolution",
        "YResolution",
    }
    unsupported_tags = _unsupported_vendor_tags(request.assignments, supported_tags)
    if unsupported_tags:
        return _unsupported_vendor_jpeg_tags("casio", unsupported_tags)
    focus_mode = values.get("FocusMode")
    object_distance = values.get("ObjectDistance")
    firmware_date = values.get("FirmwareDate")
    firmware_date_family = _casio_firmware_date_family_for_request(
        request,
        focus_mode,
        object_distance,
        firmware_date,
    )
    if firmware_date is not None and firmware_date_family is None:
        return None, (
            Diagnostic(
                code="unsupported_vendor_jpeg_composed_shape",
                message=(
                    "Casio FirmwareDate writes require a known Casio maker-note family; "
                    "the public executor does not infer a family for non-Casio fixture names."
                ),
                details={
                    "tags": [assignment.tag for assignment in request.assignments],
                    "evidence_ids": _vendor_jpeg_composed_evidence_ids("casio"),
                },
            ),
        )
    try:
        exif_plan = _casio_exif_scalar_plan(values)
        casio_plan = build_casio_maker_note_write_plan(
            focus_mode,
            object_distance,
            firmware_date,
            firmware_date_family,
        )
    except ValueError as exc:
        return _invalid_vendor_jpeg_value("casio", exc)
    return (
        _PreparedVendorJpegComposedWrite(
            paths=request.paths,
            kind="casio",
            backup_policy=_backup_policy(request),
            tags=tuple(assignment.tag for assignment in request.assignments),
            exif_plan=exif_plan,
            casio_plan=casio_plan,
        ),
        (),
    )


def _casio_exif_scalar_plan(values: dict[str, str]) -> ExifScalarWritePlan | None:
    has_exif_scalar = any(
        tag_name in values for tag_name in ("MaxApertureValue", "XResolution", "YResolution")
    )
    if not has_exif_scalar:
        return None
    return build_exif_scalar_write_plan(
        image_description=None,
        orientation=None,
        date_time_original=None,
        x_resolution=values.get("XResolution"),
        y_resolution=values.get("YResolution"),
        max_aperture_value=values.get("MaxApertureValue"),
    )


def _assignment_values_by_local_tag(
    assignments: tuple[MetadataAssignment, ...],
) -> dict[str, str]:
    return {
        _public_assignment_local_tag(assignment.tag): assignment.value for assignment in assignments
    }


def _public_assignment_local_tag(tag: str) -> str:
    return tag.strip().removeprefix("-").removesuffix("#").rsplit(":", 1)[-1]


def _vendor_jpeg_composed_kind(
    request: MetadataWriteRequest,
    values: dict[str, str],
) -> _VendorJpegComposedKind | None:
    lower_path_names = tuple(path.name.lower() for path in request.paths)
    assignment_groups = tuple(
        _normalized_tag_parts(assignment.tag)[0] for assignment in request.assignments
    )
    if "FlashMode" in values and (
        any(group in {"sanyo", "makernotes"} for group in assignment_groups)
        or all("sanyo" in name for name in lower_path_names)
    ):
        return "sanyo"
    if "MinoltaDate" in values and (
        any(group == "minolta" for group in assignment_groups)
        or all("minolta" in name for name in lower_path_names)
    ):
        return "minolta"
    if {"FocusMode", "ObjectDistance", "FirmwareDate"} & values.keys() and (
        any(group == "casio" for group in assignment_groups)
        or all("casio" in name for name in lower_path_names)
    ):
        return "casio"
    return None


def _casio_firmware_date_family_for_request(
    request: MetadataWriteRequest,
    focus_mode: str | None,
    object_distance: str | None,
    firmware_date: str | None,
) -> CasioMakerNoteFamily | None:
    if firmware_date is None:
        return None
    if object_distance is not None:
        return "type2"
    if focus_mode is not None:
        return "type1"
    if all(path.name.lower().startswith("casio2") for path in request.paths):
        return "type2"
    if all(path.name.lower().startswith("casio") for path in request.paths):
        return "type1"
    return None


def _unsupported_vendor_tags(
    assignments: tuple[MetadataAssignment, ...],
    supported_tags: set[str],
) -> JsonArray:
    return [
        assignment.tag
        for assignment in assignments
        if _public_assignment_local_tag(assignment.tag) not in supported_tags
    ]


def _unsupported_vendor_jpeg_tags(
    kind: _VendorJpegComposedKind,
    unsupported_tags: JsonArray,
) -> tuple[_PreparedVendorJpegComposedWrite | None, tuple[Diagnostic, ...]]:
    return None, (
        Diagnostic(
            code="unsupported_vendor_jpeg_composed_tag",
            message=f"Public {kind} JPEG composed write has unsupported tag requests.",
            details={
                "kind": kind,
                "unsupported_tags": unsupported_tags,
                "evidence_ids": _vendor_jpeg_composed_evidence_ids(kind),
            },
        ),
    )


def _missing_vendor_jpeg_tags(
    kind: _VendorJpegComposedKind,
    required_tags: tuple[str, ...],
    values: dict[str, str],
) -> tuple[_PreparedVendorJpegComposedWrite | None, tuple[Diagnostic, ...]]:
    missing_tags: JsonArray = [tag for tag in required_tags if tag not in values]
    return None, (
        Diagnostic(
            code="unsupported_vendor_jpeg_composed_shape",
            message=f"Public {kind} JPEG composed write is missing required seed tags.",
            details={
                "kind": kind,
                "missing_tags": missing_tags,
                "required_tags": list(required_tags),
                "evidence_ids": _vendor_jpeg_composed_evidence_ids(kind),
            },
        ),
    )


def _invalid_vendor_jpeg_value(
    kind: _VendorJpegComposedKind,
    exc: ValueError,
) -> tuple[_PreparedVendorJpegComposedWrite | None, tuple[Diagnostic, ...]]:
    return None, (
        Diagnostic(
            code="unsupported_vendor_jpeg_composed_value",
            message=f"Public {kind} JPEG composed write rejected a value: {exc}",
            details={
                "kind": kind,
                "error": str(exc),
                "evidence_ids": _vendor_jpeg_composed_evidence_ids(kind),
            },
        ),
    )


def _has_vendor_jpeg_composed_write_tags(request: MetadataWriteRequest) -> bool:
    local_tags = {
        _public_assignment_local_tag(assignment.tag) for assignment in request.assignments
    }
    return bool(
        local_tags
        & {
            "Caption-Abstract",
            "FirmwareDate",
            "FlashMode",
            "FocusMode",
            "MinoltaDate",
            "ObjectDistance",
        }
    )


def _vendor_jpeg_composed_evidence_ids(kind: _VendorJpegComposedKind) -> JsonArray:
    if kind == "sanyo":
        return ["public.write.vendor-composed.sanyo"]
    if kind == "minolta":
        return ["public.write.vendor-composed.minolta"]
    return ["public.write.vendor-composed.casio"]


def _prepare_jpeg_gps_write(
    request: MetadataWriteRequest,
) -> tuple[_PreparedJpegGpsWrite | None, tuple[Diagnostic, ...]]:
    shape_diagnostics = _basic_write_shape_diagnostics(request)
    if shape_diagnostics:
        return None, shape_diagnostics

    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() not in _JPEG_SUFFIXES
    ]
    if unsupported_paths:
        supported_suffixes: JsonArray = [suffix for suffix in sorted(_JPEG_SUFFIXES)]
        return None, (
            Diagnostic(
                code="unsupported_mixed_path_types",
                message=(
                    "Public JPEG GPS native write execution requires JPEG/JPG/JPE targets only."
                ),
                details={
                    "unsupported_paths": unsupported_paths,
                    "supported_suffixes": supported_suffixes,
                },
            ),
        )

    normalized_tags, tag_diagnostics = _normalized_gps_core_assignment_tags(request.assignments)
    if tag_diagnostics:
        return None, tag_diagnostics

    values = {
        normalized_tag: assignment.value
        for normalized_tag, assignment in zip(normalized_tags, request.assignments, strict=True)
    }
    missing_tags: JsonArray = [
        tag
        for tag in (
            "GPSLatitude",
            "GPSLatitudeRef",
            "GPSLongitude",
            "GPSLongitudeRef",
        )
        if tag not in values
    ]
    if missing_tags:
        return None, (
            Diagnostic(
                code="missing_gps_coordinate_components",
                message=(
                    "Public JPEG GPS native write execution requires latitude, latitude ref, "
                    "longitude, and longitude ref assignments in one request."
                ),
                details={"missing_tags": missing_tags},
            ),
        )

    latitude = _signed_coordinate_from_assignment(
        values["GPSLatitude"],
        values["GPSLatitudeRef"],
        "GPSLatitude",
        "GPSLatitudeRef",
        "lat",
    )
    longitude = _signed_coordinate_from_assignment(
        values["GPSLongitude"],
        values["GPSLongitudeRef"],
        "GPSLongitude",
        "GPSLongitudeRef",
        "lon",
    )
    coordinate_diagnostics: list[Diagnostic] = []
    if isinstance(latitude, Diagnostic):
        coordinate_diagnostics.append(latitude)
    if isinstance(longitude, Diagnostic):
        coordinate_diagnostics.append(longitude)
    if coordinate_diagnostics:
        return None, tuple(coordinate_diagnostics)
    if not isinstance(latitude, float) or not isinstance(longitude, float):
        return None, (
            Diagnostic(
                code="unsupported_gps_value_format",
                message="Public JPEG GPS native write execution could not parse GPS coordinates.",
                details={},
            ),
        )

    try:
        gps_plan = build_exif_gps_write_plan(
            latitude=latitude,
            longitude=longitude,
            map_datum=None,
        )
    except ValueError as exc:
        return None, (
            Diagnostic(
                code="unsupported_gps_value_format",
                message=f"Public JPEG GPS native write execution rejected GPS values: {exc}",
                details={"error": str(exc)},
            ),
        )

    return (
        _PreparedJpegGpsWrite(
            paths=request.paths,
            plan=gps_plan,
            backup_policy=_backup_policy(request),
            tags=tuple(assignment.tag for assignment in request.assignments),
        ),
        (),
    )


def _basic_write_shape_diagnostics(
    request: MetadataWriteRequest,
) -> tuple[Diagnostic, ...]:
    if not request.paths:
        return (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    if request.deletes:
        return (
            Diagnostic(
                code="not_yet_implemented_public_write_shape",
                message="Public native write execution does not support deletes yet.",
                details={"deletes": list(request.deletes)},
            ),
        )
    if not request.assignments:
        return (
            Diagnostic(
                code="unsupported_public_write_shape",
                message="Public native write execution requires at least one assignment.",
                details={"reason": "missing_assignments"},
            ),
        )
    return ()


def _public_exif_scalar_delete_evidence_ids() -> JsonArray:
    return ["public.write.exif-scalar-delete"]


def _normalized_exif_scalar_assignment_tags(
    assignments: tuple[MetadataAssignment, ...],
) -> tuple[tuple[_PublicExifScalarTag, ...], tuple[Diagnostic, ...]]:
    normalized_tags: list[_PublicExifScalarTag] = []
    unsupported_tags: JsonArray = []
    unsupported_prefixes: JsonArray = []
    for assignment in assignments:
        group, local_name = _normalized_tag_parts(assignment.tag)
        if group not in _SUPPORTED_SCALAR_GROUP_PREFIXES:
            unsupported_prefixes.append(assignment.tag)
            continue
        scalar_tag = _SCALAR_TAG_BY_KEY.get(local_name)
        if scalar_tag is None:
            unsupported_tags.append(assignment.tag)
            continue
        normalized_tags.append(scalar_tag)

    diagnostics: list[Diagnostic] = []
    if unsupported_prefixes:
        diagnostics.append(
            Diagnostic(
                code="unsupported_exif_scalar_tag",
                message=(
                    "Public JPEG EXIF scalar native write execution supports only ungrouped, "
                    "EXIF, IFD0, or ExifIFD scalar tags."
                ),
                details={"unsupported_tags": unsupported_prefixes},
            )
        )
    if unsupported_tags:
        supported_tags: JsonArray = [tag for tag in sorted(_SCALAR_TAG_BY_KEY.values())]
        diagnostics.append(
            Diagnostic(
                code="unsupported_exif_scalar_tag",
                message=(
                    "Public JPEG EXIF scalar native write execution supports only a bounded "
                    "source-backed scalar tag allowlist."
                ),
                details={
                    "unsupported_tags": unsupported_tags,
                    "supported_tags": supported_tags,
                },
            )
        )
    if diagnostics:
        return (), tuple(diagnostics)
    return tuple(normalized_tags), ()


def _normalized_exif_scalar_delete_tags(
    deletes: tuple[str, ...],
) -> tuple[tuple[_PublicExifScalarTag, ...], tuple[Diagnostic, ...]]:
    normalized_tags: list[_PublicExifScalarTag] = []
    unsupported_tags: JsonArray = []
    unsupported_prefixes: JsonArray = []
    for delete in deletes:
        group, local_name = _normalized_exif_scalar_delete_tag_parts(delete)
        if group not in _SUPPORTED_SCALAR_GROUP_PREFIXES:
            unsupported_prefixes.append(delete)
            continue
        scalar_tag = _SCALAR_TAG_BY_KEY.get(local_name)
        if scalar_tag is None:
            unsupported_tags.append(delete)
            continue
        normalized_tags.append(scalar_tag)

    diagnostics: list[Diagnostic] = []
    if unsupported_prefixes:
        diagnostics.append(
            Diagnostic(
                code="unsupported_exif_scalar_tag",
                message=(
                    "Public JPEG EXIF scalar native delete execution supports only "
                    "ungrouped, EXIF, IFD0, or ExifIFD scalar tags."
                ),
                details={
                    "unsupported_tags": unsupported_prefixes,
                    "evidence_ids": _public_exif_scalar_delete_evidence_ids(),
                },
            )
        )
    if unsupported_tags:
        supported_tags: JsonArray = [tag for tag in sorted(_SCALAR_TAG_BY_KEY.values())]
        diagnostics.append(
            Diagnostic(
                code="unsupported_exif_scalar_tag",
                message=(
                    "Public JPEG EXIF scalar native delete execution supports only a "
                    "bounded source-backed scalar tag allowlist."
                ),
                details={
                    "unsupported_tags": unsupported_tags,
                    "supported_tags": supported_tags,
                    "evidence_ids": _public_exif_scalar_delete_evidence_ids(),
                },
            )
        )
    if diagnostics:
        return (), tuple(diagnostics)
    return tuple(normalized_tags), ()


def _normalized_exif_scalar_delete_tag_parts(tag: str) -> tuple[str, str]:
    normalized = _normalized_tag(tag).removesuffix("=")
    if ":" not in normalized:
        return "", normalized
    group, local_name = normalized.rsplit(":", 1)
    return group, local_name


def _normalized_gps_core_assignment_tags(
    assignments: tuple[MetadataAssignment, ...],
) -> tuple[tuple[_PublicGpsCoreTag, ...], tuple[Diagnostic, ...]]:
    normalized_tags: list[_PublicGpsCoreTag] = []
    unsupported_tags: JsonArray = []
    unsupported_prefixes: JsonArray = []
    for assignment in assignments:
        group, local_name = _normalized_tag_parts(assignment.tag)
        if group not in _SUPPORTED_GPS_GROUP_PREFIXES:
            unsupported_prefixes.append(assignment.tag)
            continue
        gps_tag = _GPS_CORE_TAG_BY_KEY.get(local_name)
        if gps_tag is None:
            unsupported_tags.append(assignment.tag)
            continue
        normalized_tags.append(gps_tag)

    diagnostics: list[Diagnostic] = []
    if unsupported_prefixes:
        diagnostics.append(
            Diagnostic(
                code="unsupported_gps_tag",
                message=(
                    "Public JPEG GPS native write execution supports only ungrouped, "
                    "GPS, EXIF, or Composite GPS coordinate tags."
                ),
                details={"unsupported_tags": unsupported_prefixes},
            )
        )
    if unsupported_tags:
        supported_tags: JsonArray = [tag for tag in sorted(_SUPPORTED_GPS_CORE_TAGS)]
        diagnostics.append(
            Diagnostic(
                code="unsupported_gps_tag",
                message=(
                    "Public JPEG GPS native write execution supports only GPSLatitude, "
                    "GPSLatitudeRef, GPSLongitude, and GPSLongitudeRef."
                ),
                details={
                    "unsupported_tags": unsupported_tags,
                    "supported_tags": supported_tags,
                },
            )
        )
    if diagnostics:
        return (), tuple(diagnostics)
    return tuple(normalized_tags), ()


def _signed_coordinate_from_assignment(
    coordinate_text: str,
    reference_text: str,
    coordinate_tag: _JpegGpsCoordinateTag,
    reference_tag: _JpegGpsRefTag,
    kind: _JpegGpsKind,
) -> float | Diagnostic:
    coordinate = gps_coordinate_to_degrees(coordinate_text, True, kind)
    if coordinate is None:
        return Diagnostic(
            code="unsupported_gps_value_format",
            message=(
                "Public JPEG GPS native write execution supports ExifTool-style "
                "GPS coordinate strings containing one to three decimal numbers."
            ),
            details={"tag": coordinate_tag, "value": coordinate_text},
        )
    reference = _gps_reference_sign(reference_text, reference_tag)
    if reference is None:
        return Diagnostic(
            code="unsupported_gps_value_format",
            message=(
                "Public JPEG GPS native write execution supports N/North/S/South "
                "latitude refs and E/East/W/West longitude refs."
            ),
            details={"tag": reference_tag, "value": reference_text},
        )
    if coordinate < 0 and reference > 0:
        return _inconsistent_gps_coordinate_diagnostic(coordinate_tag, reference_tag)
    return abs(coordinate) * reference


def _gps_reference_sign(reference_text: str, tag: _JpegGpsRefTag) -> float | None:
    value = reference_text.strip().lower()
    if tag == "GPSLatitudeRef":
        if value in {"n", "north"}:
            return 1.0
        if value in {"s", "south"}:
            return -1.0
    if tag == "GPSLongitudeRef":
        if value in {"e", "east"}:
            return 1.0
        if value in {"w", "west"}:
            return -1.0
    if value.startswith("-"):
        return -1.0
    if value.startswith("+") or value[:1].isdigit():
        return 1.0
    return None


def _inconsistent_gps_coordinate_diagnostic(
    coordinate_tag: _JpegGpsCoordinateTag,
    reference_tag: _JpegGpsRefTag,
) -> Diagnostic:
    return Diagnostic(
        code="unsupported_gps_value_format",
        message="Public JPEG GPS coordinate value and reference value are inconsistent.",
        details={"coordinate_tag": coordinate_tag, "reference_tag": reference_tag},
    )


def _mixed_assignment_family_diagnostics(
    assignments: tuple[MetadataAssignment, ...],
) -> tuple[Diagnostic, ...]:
    families = tuple(_assignment_family(assignment) for assignment in assignments)
    present = frozenset(family for family in families if family != "unsupported")
    if len(present) <= 1:
        return ()
    return (
        Diagnostic(
            code="unsupported_mixed_write_families",
            message=(
                "Public native write execution does not yet dispatch mixed GPS, EXIF scalar, "
                "and XMP assignment families in one request."
            ),
            details={
                "families": [family for family in sorted(present)],
                "tags": [assignment.tag for assignment in assignments],
            },
        ),
    )


def _assignment_family(assignment: MetadataAssignment) -> _PublicWriteFamily:
    group, local_name = _normalized_tag_parts(assignment.tag)
    if group.startswith("xmp-") or group == "xmp":
        return "xmp"
    if group in _SUPPORTED_GPS_GROUP_PREFIXES and local_name in _SUPPORTED_GPS_CORE_TAGS:
        return "gps"
    if group in _SUPPORTED_SCALAR_GROUP_PREFIXES and local_name in _SCALAR_TAG_BY_KEY:
        return "scalar"
    return "unsupported"


def _preferred_prepare_diagnostics(
    exif_copy_diagnostics: tuple[Diagnostic, ...],
    xmp_copy_diagnostics: tuple[Diagnostic, ...],
    pdf_delete_diagnostics: tuple[Diagnostic, ...],
    pdf_info_diagnostics: tuple[Diagnostic, ...],
    xmp_property_delete_diagnostics: tuple[Diagnostic, ...],
    xmp_namespace_delete_diagnostics: tuple[Diagnostic, ...],
    xmp_delete_diagnostics: tuple[Diagnostic, ...],
    app_segment_delete_diagnostics: tuple[Diagnostic, ...],
    vendor_jpeg_diagnostics: tuple[Diagnostic, ...],
    microsoft_xtra_diagnostics: tuple[Diagnostic, ...],
    quicktime_diagnostics: tuple[Diagnostic, ...],
    iptc_assignment_diagnostics: tuple[Diagnostic, ...],
    xmp_diagnostics: tuple[Diagnostic, ...],
    jpeg_scalar_diagnostics: tuple[Diagnostic, ...],
    jpeg_gps_diagnostics: tuple[Diagnostic, ...],
) -> tuple[Diagnostic, ...]:
    if any(
        diagnostic.code
        in {
            "unsupported_mixed_exif_sidecar_copy_from_file_shape",
            "unsupported_exif_sidecar_copy_path",
            "unsupported_exif_sidecar_copy_route",
            "unsupported_exif_sidecar_copy_source_path",
            "unsupported_public_preserve_file_times_route",
        }
        for diagnostic in exif_copy_diagnostics
    ):
        return exif_copy_diagnostics
    if any(
        diagnostic.code
        in {
            "not_yet_implemented_xmp_sidecar_copy_backup_policy",
            "unsupported_mixed_xmp_sidecar_copy_from_file_shape",
            "unsupported_xmp_sidecar_copy_path",
            "unsupported_xmp_sidecar_copy_route",
            "unsupported_xmp_sidecar_copy_route_combination",
            "unsupported_xmp_sidecar_copy_source_path",
            "unsupported_public_preserve_file_times_route",
        }
        for diagnostic in xmp_copy_diagnostics
    ):
        return xmp_copy_diagnostics
    if any(
        diagnostic.code.startswith("unsupported_pdf_metadata_delete")
        or diagnostic.code == "unsupported_mixed_pdf_metadata_delete_shape"
        for diagnostic in pdf_delete_diagnostics
    ):
        return pdf_delete_diagnostics
    if any(
        diagnostic.code.startswith("unsupported_pdf_info_scalar")
        or diagnostic.code == "unsupported_mixed_pdf_info_scalar_shape"
        for diagnostic in pdf_info_diagnostics
    ):
        return pdf_info_diagnostics
    if any(
        diagnostic.code.startswith("unsupported_xmp_property_delete")
        or diagnostic.code == "unsupported_mixed_xmp_property_delete_shape"
        for diagnostic in xmp_property_delete_diagnostics
    ):
        return xmp_property_delete_diagnostics
    if any(
        diagnostic.code
        in {
            "unsupported_mixed_xmp_sidecar_write_shape",
            "unsupported_xmp_namespace_delete_tag",
            "unsupported_xmp_sidecar_delete_path",
        }
        for diagnostic in xmp_namespace_delete_diagnostics
    ):
        return xmp_namespace_delete_diagnostics
    if any(
        diagnostic.code
        in {
            "unsupported_mixed_xmp_sidecar_write_shape",
            "unsupported_xmp_family2_delete_tag",
            "unsupported_xmp_sidecar_delete_path",
        }
        for diagnostic in xmp_delete_diagnostics
    ):
        return xmp_delete_diagnostics
    if any(
        diagnostic.code.startswith("unsupported_jpeg_app_segment_delete")
        or diagnostic.code == "unsupported_mixed_jpeg_app_segment_delete_shape"
        for diagnostic in app_segment_delete_diagnostics
    ):
        return app_segment_delete_diagnostics
    if any(
        diagnostic.code.startswith("unsupported_vendor_jpeg_composed")
        or diagnostic.code == "unsupported_mixed_path_types"
        for diagnostic in vendor_jpeg_diagnostics
    ):
        return vendor_jpeg_diagnostics
    if any(
        diagnostic.code.startswith("unsupported_quicktime_microsoft_xtra_write")
        or diagnostic.code == "unsupported_mixed_quicktime_microsoft_xtra_write_shape"
        for diagnostic in microsoft_xtra_diagnostics
    ):
        return microsoft_xtra_diagnostics
    if any(
        diagnostic.code.startswith("unsupported_quicktime_metadata_write")
        or diagnostic.code == "unsupported_mixed_quicktime_metadata_write_shape"
        for diagnostic in quicktime_diagnostics
    ):
        return quicktime_diagnostics
    if any(
        diagnostic.code.startswith("unsupported_jpeg_iptc_assignment")
        or diagnostic.code == "unsupported_mixed_jpeg_iptc_assignment_shape"
        for diagnostic in iptc_assignment_diagnostics
    ):
        return iptc_assignment_diagnostics
    if any(
        diagnostic.code == "unsupported_mixed_write_families"
        for diagnostic in jpeg_scalar_diagnostics
    ):
        return jpeg_scalar_diagnostics
    if any(
        diagnostic.code == "not_yet_implemented_public_copy_from_file_shape"
        for diagnostic in xmp_diagnostics
    ):
        return xmp_diagnostics
    if any(
        diagnostic.code == "not_yet_implemented_public_exif_sidecar_copy_from_file_shape"
        for diagnostic in xmp_diagnostics
    ):
        return xmp_diagnostics
    if any(
        diagnostic.code == "unsupported_xmp_sidecar_property_write"
        for diagnostic in xmp_diagnostics
    ):
        return xmp_diagnostics
    if any(
        diagnostic.code == "unsupported_exif_scalar_value_format"
        for diagnostic in jpeg_scalar_diagnostics
    ):
        return jpeg_scalar_diagnostics
    if any(
        diagnostic.code.startswith("unsupported_exif_scalar")
        and _diagnostic_has_exif_scalar_family_requested_tag(diagnostic)
        for diagnostic in jpeg_scalar_diagnostics
    ):
        return jpeg_scalar_diagnostics
    if any(
        diagnostic.code == "unsupported_gps_value_format" for diagnostic in jpeg_gps_diagnostics
    ):
        return jpeg_gps_diagnostics
    if any(
        diagnostic.code.startswith("unsupported_gps")
        and _diagnostic_has_gps_requested_tag(diagnostic)
        for diagnostic in jpeg_gps_diagnostics
    ):
        return jpeg_gps_diagnostics
    if any(
        diagnostic.code in {"missing_gps_coordinate_components", "unsupported_mixed_path_types"}
        for diagnostic in jpeg_gps_diagnostics
    ):
        return jpeg_gps_diagnostics
    return xmp_diagnostics


def _xmp_namespace_delete_targets(
    deletes: tuple[str, ...],
) -> tuple[tuple[XmpNamespaceDeleteTarget, ...], tuple[Diagnostic, ...]]:
    targets: list[XmpNamespaceDeleteTarget] = []
    unsupported_tags: JsonArray = []
    for delete in deletes:
        group, selector = _normalized_delete_tag_parts(delete)
        target = _SUPPORTED_XMP_NAMESPACE_DELETE_GROUPS.get(group)
        if target is None or selector not in _SUPPORTED_XMP_NAMESPACE_DELETE_SELECTORS:
            unsupported_tags.append(delete)
            continue
        targets.append(target)

    if unsupported_tags:
        return (), (
            Diagnostic(
                code="unsupported_xmp_namespace_delete_tag",
                message=(
                    "Public XMP sidecar native namespace delete execution supports only "
                    "source-backed XMP family-1 namespace All/* deletes in this slice."
                ),
                details={
                    "unsupported_tags": unsupported_tags,
                    "supported_tags": _supported_xmp_namespace_delete_tags(),
                    "evidence_ids": _public_xmp_assignment_evidence_ids_json(),
                },
            ),
        )
    return tuple(dict.fromkeys(targets)), ()


def _supported_xmp_namespace_delete_tags() -> JsonArray:
    supported_tags: JsonArray = []
    for target in sorted(_SUPPORTED_XMP_NAMESPACE_DELETE_GROUPS.values()):
        supported_tags.append(f"{target}:*")
        supported_tags.append(f"{target}:All")
    return supported_tags


def _xmp_family2_delete_targets(
    deletes: tuple[str, ...],
) -> tuple[tuple[XmpFamily2DeleteTarget, ...], tuple[Diagnostic, ...]]:
    targets: list[XmpFamily2DeleteTarget] = []
    unsupported_tags: JsonArray = []
    for delete in deletes:
        group, selector = _normalized_delete_tag_parts(delete)
        if (
            group not in _SUPPORTED_XMP_FAMILY2_DELETE_GROUPS
            or selector not in _SUPPORTED_XMP_FAMILY2_DELETE_SELECTORS
        ):
            unsupported_tags.append(delete)
            continue
        targets.append(xmp_family2_delete_target(group.title()))

    if unsupported_tags:
        return (), (
            Diagnostic(
                code="unsupported_xmp_family2_delete_tag",
                message=(
                    "Public XMP sidecar native delete execution supports only bounded "
                    "family-2 Image and Camera group deletes in this slice."
                ),
                details={
                    "unsupported_tags": unsupported_tags,
                    "supported_tags": ["Camera:*", "Camera:All", "Image:*", "Image:All"],
                },
            ),
        )
    return tuple(targets), ()


def _diagnostic_has_exif_scalar_family_requested_tag(diagnostic: Diagnostic) -> bool:
    details = diagnostic.details
    if details is None:
        return False
    unsupported_tags = details.get("unsupported_tags")
    if not isinstance(unsupported_tags, list):
        return False
    return any(
        isinstance(tag, str)
        and _normalized_tag_parts(tag)[0] in _SUPPORTED_SCALAR_GROUP_PREFIXES
        and _normalized_tag_parts(tag)[1] not in _SUPPORTED_GPS_CORE_TAGS
        for tag in unsupported_tags
    )


def _diagnostic_has_gps_requested_tag(diagnostic: Diagnostic) -> bool:
    details = diagnostic.details
    if details is None:
        return False
    unsupported_tags = details.get("unsupported_tags")
    if not isinstance(unsupported_tags, list):
        return False
    return any(
        isinstance(tag, str) and _normalized_tag_parts(tag)[1].startswith("gps")
        for tag in unsupported_tags
    )


def _backup_policy(request: MetadataWriteRequest) -> BackupPolicy:
    if request.policy in {"overwrite_original", "overwrite_original_in_place"}:
        return "overwrite_original"
    return "create_backup"


def _write_rewritten_bytes_transactionally(
    request: MetadataWriteRequest,
    path: Path,
    data: bytes,
    backup_policy: BackupPolicy,
) -> None:
    if request.policy == "overwrite_original_in_place":
        copy_back_bytes_in_place_transactionally(
            path,
            data,
            preserve_file_times=request.preserve_file_times,
        )
        return
    write_bytes_in_place_transactionally(
        path,
        data,
        backup_policy,
        preserve_file_times=request.preserve_file_times,
    )


def _unsupported_preserve_file_times_diagnostic(
    route: str,
    writer_name: str,
) -> Diagnostic:
    return Diagnostic(
        code="unsupported_public_preserve_file_times_route",
        message=(
            f"Public {route} execution cannot honor preserve_file_times until the "
            f"{writer_name} exposes timestamp-preserving transaction policy."
        ),
        details={
            "route": route,
            "writer": writer_name,
            "evidence_ids": [
                "public.write.policy.overwrite-preserve-docs",
                "public.write.policy.overwrite-semantics",
                "public.write.policy.writer-preserve-time",
            ],
        },
    )


def _blocking_write_policy_diagnostics(request: MetadataWriteRequest) -> tuple[Diagnostic, ...]:
    _ = request
    return ()


def _normalized_tag(tag: str) -> str:
    return tag.strip().removeprefix("-").lower()


def _normalized_tag_parts(tag: str) -> tuple[str, str]:
    normalized = _normalized_tag(tag)
    if ":" not in normalized:
        return "", normalized
    group, local_name = normalized.rsplit(":", 1)
    return group, local_name


def _normalized_delete_tag_parts(tag: str) -> tuple[str, str]:
    normalized = _normalized_tag(tag).removesuffix("=")
    if ":" not in normalized:
        return normalized, "all"
    group, selector = normalized.rsplit(":", 1)
    return group, selector


def _status_for_deferred_diagnostics(
    diagnostics: tuple[Diagnostic, ...],
) -> PublicOperationStatus:
    if any(diagnostic.code == "unsupported_public_write_shape" for diagnostic in diagnostics):
        return "unsupported"
    return "not_yet_implemented"
