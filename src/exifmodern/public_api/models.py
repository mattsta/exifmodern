"""Stable request and result models for production-facing ExifModern APIs.

These types intentionally describe the public contract before routing to full
read/write services is complete. Skeleton operations return explicit statuses
instead of silently claiming ExifTool-compatible behavior.
"""

from __future__ import annotations

import os
import re
import tempfile
from base64 import b64encode
from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from fnmatch import fnmatchcase
from functools import cmp_to_key
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from xml.etree import ElementTree

from exifmodern.formats.public_payload import read_public_document_payload
from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.public_api.rendering import (
    csv_headers as _csv_headers,
)
from exifmodern.public_api.rendering import (
    json_record_for_render as _json_record_for_render,
)
from exifmodern.public_api.rendering import (
    render_record_output as _render_record_output,
)
from exifmodern.public_api.rendering import (
    render_records_csv as _render_records_csv,
)
from exifmodern.public_api.rendering import (
    render_records_html as _render_records_html,
)
from exifmodern.public_api.rendering import (
    render_records_json as _render_records_json,
)
from exifmodern.public_api.rendering import (
    render_records_php as _render_records_php,
)
from exifmodern.public_api.rendering import (
    rendered_text_for_charset as _rendered_text_for_charset,
)
from exifmodern.public_api.rendering import (
    text_value as _text_value,
)
from exifmodern.public_interface import alternate_files as _public_alternate_files
from exifmodern.public_interface import embedded as _public_embedded
from exifmodern.public_interface.alternate_files import PublicInsertTagValue
from exifmodern.public_interface.missing_tags import (
    forced_missing_group_name as _forced_missing_group_name,
)
from exifmodern.public_interface.missing_tags import (
    forced_missing_record_key as _forced_missing_record_key,
)
from exifmodern.public_interface.output_policy import (
    PublicFilenameSprintfTagContext,
)
from exifmodern.public_interface.output_policy import (
    classify_public_write_output_route as _classify_public_write_output_route,
)
from exifmodern.public_interface.output_policy import (
    public_filename_sprintf as _public_filename_sprintf,
)
from exifmodern.public_interface.output_policy import (
    public_output_visible_graph as _public_output_visible_graph,
)
from exifmodern.public_interface.output_policy import (
    public_write_output_effective_path as _public_write_output_effective_path,
)
from exifmodern.public_interface.output_policy import (
    public_write_output_effective_paths as _public_write_output_effective_paths,
)
from exifmodern.public_interface.output_policy import (
    public_write_output_evidence_ids as _public_write_output_evidence_ids,
)
from exifmodern.public_interface.output_policy import (
    public_write_output_stdout_extension as _public_write_output_stdout_extension,
)
from exifmodern.public_interface.user_params import (
    PublicUserParam,
    original_file_user_params,
    public_user_param_value,
)
from exifmodern.read_dispatch import RIFF_SIGNATURES, build_dispatched_read_graph
from exifmodern.read_graph import (
    BinaryTagListValue,
    BinaryTagValue,
    ReadGraph,
    ReadGraphRuntimeOptions,
    ReadGraphUnknownTagLevel,
    ReadTag,
    ScalarTagArray,
    ScalarTagValue,
    TagProvenance,
    TagValue,
    build_read_graph,
)
from exifmodern.renderer import (
    JsonRecord,
    RenderIssue,
    RenderOptions,
    RequestedTag,
    find_graph_tags,
    format_render_issues,
    format_requested_tag,
    graph_record_for_request,
    render_exiftool_json,
    requested_tag_from_arg,
)

if TYPE_CHECKING:
    from exifmodern.exif_scalar_write_plan import (
        ExifScalarWritePlan,
        artist_step,
        build_exif_scalar_write_plan,
    )
    from exifmodern.file_transaction import (
        BackupPolicy,
        copy_back_bytes_in_place_transactionally,
        write_bytes_in_place_transactionally,
        write_bytes_transactionally,
    )
    from exifmodern.formats.canon_vrd.copy_from_file_writer import (
        extract_canon_dr4_block,
        extract_canon_vrd_block,
    )
    from exifmodern.formats.exv.writer import (
        ExvSourceMetadataGroup,
        materialize_exv_from_comment_value,
        materialize_exv_from_exif_tiff_payload,
        materialize_exv_from_generated_xmp_plan,
        materialize_exv_from_source_ducky_assignments,
        materialize_exv_from_source_exif,
        materialize_exv_from_source_exif_with_scalar_plan,
        materialize_exv_from_source_iptc_application_plan,
        materialize_exv_from_source_metadata,
        materialize_exv_from_source_metadata_groups,
        materialize_exv_from_source_photoshop_app13_plan,
    )
    from exifmodern.formats.icc.materializer import materialize_source_icc_profile
    from exifmodern.formats.iptc.write_plan import (
        IptcApplicationWritePlan,
        coalesce_iptc_application_steps,
        iptc_application_tag_spec,
        upsert_text_step,
    )
    from exifmodern.formats.mie.materializer import materialize_source_mie_file
    from exifmodern.formats.photoshop.app13_resource_writer import (
        PhotoshopApp13ResourceWritePlan,
        build_photoshop_app13_resource_write_plan,
    )
    from exifmodern.formats.png.chunk_transaction_plan import (
        PngPhysicalPixelRequest,
        PngTextChunkRequest,
        build_png_chunk_transaction_plan,
    )
    from exifmodern.formats.png.textual_runtime import (
        PngXmpAlternateLanguageWriteRequest,
        build_png_xmp_itxt_alternate_language_write_plan,
    )
    from exifmodern.formats.riff.wav_metadata_transaction_plan import (
        RiffMetadataDeleteRequest,
        build_wav_metadata_transaction_plan,
    )
    from exifmodern.formats.riff.webp_chunk_transaction_plan import (
        build_webp_chunk_transaction_plan,
    )
    from exifmodern.formats.tiff.exif_scalar_rewriter import create_minimal_exif_scalar_tiff
    from exifmodern.formats.xmp.packet import empty_xmp_packet
    from exifmodern.formats.xmp.property_write import (
        XMP_PUBLIC_SIDECAR_PROPERTY_NAMES,
        XmpPropertyWritePlan,
        XmpPublicSidecarPropertyAssignment,
        build_public_xmp_sidecar_property_write_plan,
    )
    from exifmodern.formats.xmp.property_write import (
        simple_struct_assignment_target as xmp_simple_struct_assignment_target,
    )
    from exifmodern.formats.xmp.reader import (
        RDF_NAMESPACE,
        decode_xmp_packet,
        expanded_name_parts,
        namespace_spec_for_uri,
    )
    from exifmodern.formats.xmp.sidecar_writer import rewrite_xmp_sidecar_properties
    from exifmodern.formats.xmp.structs.job_ref import (
        XMP_JOB_REF_FIELD_SPECS,
        job_ref_assignment_target,
    )
    from exifmodern.formats.xmp.structs.manifest_item import (
        XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS,
        manifest_item_assignment_target,
    )
    from exifmodern.formats.xmp.structs.pantry_item import (
        XMP_PANTRY_ITEM_FIELD_SPECS,
        pantry_item_assignment_target,
    )
    from exifmodern.formats.xmp.structs.resource_event import (
        XMP_RESOURCE_EVENT_FIELD_SPECS,
        resource_event_assignment_target,
    )
    from exifmodern.formats.xmp.structs.resource_ref import (
        XMP_RESOURCE_REF_FIELD_SPECS,
        resource_ref_assignment_target,
    )
    from exifmodern.formats.xmp.structs.simple_struct import simple_struct_nested_path_steps
    from exifmodern.public_interface.plot_svg import PlotSvgDiagnostic, PlotSvgSettings
    from exifmodern.safe_expression.bytecode import SafeExpressionProgram, VmScalar, VmValue
    from exifmodern.services.geolocation_runtime import (
        GeolocationListRow,
        GeolocationListSortMode,
    )
    from exifmodern.services.tag_lookup_runtime import (
        TagLookupRuntimeCandidate,
        TagLookupRuntimeCapability,
        TagLookupRuntimeResult,
        TagLookupSelectionResult,
        load_tag_lookup_runtime_service,
    )
    from exifmodern.write_action_dispatch import (
        GoldenWriteModernPlanRecord,
        WriteActionCapabilityStatus,
        classify_write_action,
        load_modern_runnable_write_action_records,
        native_callable_to_json,
        status_counts_to_json,
    )
_PUBLIC_WRITE_RUNTIME_IMPORTED = False


def _default_plot_svg_settings() -> PlotSvgSettings:
    from exifmodern.public_interface.plot_svg import PlotSvgSettings

    return PlotSvgSettings()


def _ensure_public_write_runtime_imports() -> None:
    global _PUBLIC_WRITE_RUNTIME_IMPORTED
    if _PUBLIC_WRITE_RUNTIME_IMPORTED:
        return

    from exifmodern.exif_scalar_write_plan import (
        ExifScalarWritePlan,
        artist_step,
        build_exif_scalar_write_plan,
    )
    from exifmodern.file_transaction import (
        BackupPolicy,
        copy_back_bytes_in_place_transactionally,
        write_bytes_in_place_transactionally,
        write_bytes_transactionally,
    )
    from exifmodern.formats.canon_vrd.copy_from_file_writer import (
        extract_canon_dr4_block,
        extract_canon_vrd_block,
    )
    from exifmodern.formats.exv.writer import (
        ExvSourceMetadataGroup,
        materialize_exv_from_comment_value,
        materialize_exv_from_exif_tiff_payload,
        materialize_exv_from_generated_xmp_plan,
        materialize_exv_from_source_ducky_assignments,
        materialize_exv_from_source_exif,
        materialize_exv_from_source_exif_with_scalar_plan,
        materialize_exv_from_source_iptc_application_plan,
        materialize_exv_from_source_metadata,
        materialize_exv_from_source_metadata_groups,
        materialize_exv_from_source_photoshop_app13_plan,
    )
    from exifmodern.formats.icc.materializer import materialize_source_icc_profile
    from exifmodern.formats.iptc.write_plan import (
        IptcApplicationWritePlan,
        coalesce_iptc_application_steps,
        iptc_application_tag_spec,
        upsert_text_step,
    )
    from exifmodern.formats.mie.materializer import materialize_source_mie_file
    from exifmodern.formats.photoshop.app13_resource_writer import (
        build_photoshop_app13_resource_write_plan,
    )
    from exifmodern.formats.png.chunk_transaction_plan import (
        PngPhysicalPixelRequest,
        PngTextChunkRequest,
        build_png_chunk_transaction_plan,
    )
    from exifmodern.formats.png.textual_runtime import (
        PngXmpAlternateLanguageWriteRequest,
        build_png_xmp_itxt_alternate_language_write_plan,
    )
    from exifmodern.formats.riff.wav_metadata_transaction_plan import (
        RiffMetadataDeleteRequest,
        build_wav_metadata_transaction_plan,
    )
    from exifmodern.formats.riff.webp_chunk_transaction_plan import (
        build_webp_chunk_transaction_plan,
    )
    from exifmodern.formats.tiff.exif_scalar_rewriter import (
        create_minimal_exif_scalar_tiff,
    )
    from exifmodern.formats.xmp.packet import empty_xmp_packet
    from exifmodern.formats.xmp.property_write import (
        XMP_PUBLIC_SIDECAR_PROPERTY_NAMES,
        XmpPublicSidecarPropertyAssignment,
        build_public_xmp_sidecar_property_write_plan,
    )
    from exifmodern.formats.xmp.sidecar_writer import rewrite_xmp_sidecar_properties
    from exifmodern.services.tag_lookup_runtime import load_tag_lookup_runtime_service
    from exifmodern.write_action_dispatch import (
        WriteActionCapabilityStatus,
        classify_write_action,
        load_modern_runnable_write_action_records,
        native_callable_to_json,
        status_counts_to_json,
    )

    globals().update(
        {
            "artist_step": artist_step,
            "ExifScalarWritePlan": ExifScalarWritePlan,
            "build_exif_scalar_write_plan": build_exif_scalar_write_plan,
            "BackupPolicy": BackupPolicy,
            "copy_back_bytes_in_place_transactionally": (copy_back_bytes_in_place_transactionally),
            "write_bytes_in_place_transactionally": write_bytes_in_place_transactionally,
            "write_bytes_transactionally": write_bytes_transactionally,
            "extract_canon_dr4_block": extract_canon_dr4_block,
            "extract_canon_vrd_block": extract_canon_vrd_block,
            "ExvSourceMetadataGroup": ExvSourceMetadataGroup,
            "materialize_exv_from_comment_value": materialize_exv_from_comment_value,
            "materialize_exv_from_exif_tiff_payload": materialize_exv_from_exif_tiff_payload,
            "materialize_exv_from_generated_xmp_plan": materialize_exv_from_generated_xmp_plan,
            "materialize_exv_from_source_ducky_assignments": (
                materialize_exv_from_source_ducky_assignments
            ),
            "materialize_exv_from_source_exif": materialize_exv_from_source_exif,
            "materialize_exv_from_source_exif_with_scalar_plan": (
                materialize_exv_from_source_exif_with_scalar_plan
            ),
            "materialize_exv_from_source_iptc_application_plan": (
                materialize_exv_from_source_iptc_application_plan
            ),
            "materialize_exv_from_source_metadata": materialize_exv_from_source_metadata,
            "materialize_exv_from_source_metadata_groups": (
                materialize_exv_from_source_metadata_groups
            ),
            "materialize_exv_from_source_photoshop_app13_plan": (
                materialize_exv_from_source_photoshop_app13_plan
            ),
            "materialize_source_icc_profile": materialize_source_icc_profile,
            "IptcApplicationWritePlan": IptcApplicationWritePlan,
            "coalesce_iptc_application_steps": coalesce_iptc_application_steps,
            "iptc_application_tag_spec": iptc_application_tag_spec,
            "upsert_text_step": upsert_text_step,
            "materialize_source_mie_file": materialize_source_mie_file,
            "build_photoshop_app13_resource_write_plan": (
                build_photoshop_app13_resource_write_plan
            ),
            "PngPhysicalPixelRequest": PngPhysicalPixelRequest,
            "PngTextChunkRequest": PngTextChunkRequest,
            "build_png_chunk_transaction_plan": build_png_chunk_transaction_plan,
            "PngXmpAlternateLanguageWriteRequest": PngXmpAlternateLanguageWriteRequest,
            "build_png_xmp_itxt_alternate_language_write_plan": (
                build_png_xmp_itxt_alternate_language_write_plan
            ),
            "RiffMetadataDeleteRequest": RiffMetadataDeleteRequest,
            "build_wav_metadata_transaction_plan": build_wav_metadata_transaction_plan,
            "build_webp_chunk_transaction_plan": build_webp_chunk_transaction_plan,
            "create_minimal_exif_scalar_tiff": create_minimal_exif_scalar_tiff,
            "empty_xmp_packet": empty_xmp_packet,
            "XMP_PUBLIC_SIDECAR_PROPERTY_NAMES": XMP_PUBLIC_SIDECAR_PROPERTY_NAMES,
            "XmpPublicSidecarPropertyAssignment": XmpPublicSidecarPropertyAssignment,
            "build_public_xmp_sidecar_property_write_plan": (
                build_public_xmp_sidecar_property_write_plan
            ),
            "rewrite_xmp_sidecar_properties": rewrite_xmp_sidecar_properties,
            "load_tag_lookup_runtime_service": load_tag_lookup_runtime_service,
            "WriteActionCapabilityStatus": WriteActionCapabilityStatus,
            "classify_write_action": classify_write_action,
            "load_modern_runnable_write_action_records": (
                load_modern_runnable_write_action_records
            ),
            "native_callable_to_json": native_callable_to_json,
            "status_counts_to_json": status_counts_to_json,
        }
    )
    _PUBLIC_WRITE_RUNTIME_IMPORTED = True


def _ensure_public_xmp_structured_runtime_imports() -> None:
    from exifmodern.formats.jpeg.app_segments.xmp import jpeg_xmp_packets_from_app1_segments
    from exifmodern.formats.xmp.property_write import (
        simple_struct_assignment_target as xmp_simple_struct_assignment_target,
    )
    from exifmodern.formats.xmp.reader import (
        RDF_NAMESPACE,
        decode_xmp_packet,
        expanded_name_parts,
        namespace_spec_for_uri,
    )
    from exifmodern.formats.xmp.structs.job_ref import (
        XMP_JOB_REF_FIELD_SPECS,
        job_ref_assignment_target,
    )
    from exifmodern.formats.xmp.structs.manifest_item import (
        XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS,
        manifest_item_assignment_target,
    )
    from exifmodern.formats.xmp.structs.pantry_item import (
        XMP_PANTRY_ITEM_FIELD_SPECS,
        pantry_item_assignment_target,
    )
    from exifmodern.formats.xmp.structs.resource_event import (
        XMP_RESOURCE_EVENT_FIELD_SPECS,
        resource_event_assignment_target,
    )
    from exifmodern.formats.xmp.structs.resource_ref import (
        XMP_RESOURCE_REF_FIELD_SPECS,
        resource_ref_assignment_target,
    )
    from exifmodern.formats.xmp.structs.simple_struct import simple_struct_nested_path_steps

    globals().update(
        {
            "jpeg_xmp_packets_from_app1_segments": jpeg_xmp_packets_from_app1_segments,
            "xmp_simple_struct_assignment_target": xmp_simple_struct_assignment_target,
            "RDF_NAMESPACE": RDF_NAMESPACE,
            "decode_xmp_packet": decode_xmp_packet,
            "expanded_name_parts": expanded_name_parts,
            "namespace_spec_for_uri": namespace_spec_for_uri,
            "XMP_JOB_REF_FIELD_SPECS": XMP_JOB_REF_FIELD_SPECS,
            "job_ref_assignment_target": job_ref_assignment_target,
            "XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS": XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS,
            "manifest_item_assignment_target": manifest_item_assignment_target,
            "XMP_PANTRY_ITEM_FIELD_SPECS": XMP_PANTRY_ITEM_FIELD_SPECS,
            "pantry_item_assignment_target": pantry_item_assignment_target,
            "XMP_RESOURCE_EVENT_FIELD_SPECS": XMP_RESOURCE_EVENT_FIELD_SPECS,
            "resource_event_assignment_target": resource_event_assignment_target,
            "XMP_RESOURCE_REF_FIELD_SPECS": XMP_RESOURCE_REF_FIELD_SPECS,
            "resource_ref_assignment_target": resource_ref_assignment_target,
            "simple_struct_nested_path_steps": simple_struct_nested_path_steps,
        }
    )


type PublicOperationStatus = Literal[
    "ok",
    "unsupported",
    "not_yet_implemented",
    "condition_failed",
]
type UnsupportedReason = Literal[
    "native_read_service_not_connected",
    "native_write_service_not_connected",
    "native_inspect_service_not_connected",
    "renderer_not_connected",
]
type RenderFormat = Literal["text", "json", "xml", "csv", "tab", "html", "php", "html_dump", "plot"]
type WritePolicy = Literal[
    "preserve_original",
    "overwrite_original",
    "overwrite_original_in_place",
]
type PublicImportWriteFormat = Literal["csv", "json"]
type ExtensionFilterMode = Literal["include", "exclude", "include_extra"]
type XmpSidecarCopyGroup = Literal["ALL", "EXIF", "XMP"]
type XmpSidecarCopyDestinationGroup = Literal["ALL", "XMP"]
type XmpSidecarCopyTagPattern = Literal["*"]
type ExifSidecarCopyGroup = Literal["EXIF"]
type ExifSidecarCopyTagPattern = Literal["", "all", "*"]
type PublicCopyFromFileSourceKind = Literal["explicit_source", "current_target", "datfile"]
type PublicCopyFromFileRouteKind = Literal[
    "implicit_all",
    "selector",
    "redirect_selector",
    "datfile_payload",
]
type PublicWriteOperation = Literal["assignment", "delete", "copy_from_file"]
type MetadataAssignmentOperation = Literal["set", "add_list_value", "delete_list_value"]
type PublicWriteTargetKind = Literal["tag", "group", "all"]
type PublicWriteSideEffectKind = Literal[
    "filesystem_timestamp",
    "filesystem_rename_or_move",
    "filesystem_link",
    "filesystem_dry_run_name",
    "filesystem_original_backup_delete",
    "filesystem_original_backup_restore",
]
type PublicReadGroupFamily = Literal[0, 1, 2, 4]
type PublicReadAlternateFileSlot = int
type PublicReadGroupWildcardMode = Literal["literal", "all_instances"]
type PublicReadDuplicateInstanceMode = Literal["default", "primary", "copy"]
type PublicReadConditionPass = int
type _PublicInsertTagUnresolvedReason = Literal["missing", "non_scalar"]
type RemainingSelectedWriteOutputType = Literal["exv", "mie", "icc", "vrd", "dr4"]
type _ExvDuckyPublicAssignment = tuple[Literal["Quality", "Comment", "Copyright"], str]
type PublicReadConditionOperator = Literal[
    "exists",
    "not_exists",
    "vm",
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
]
type XmlTagIdFormat = Literal["none", "decimal", "hex"]
type XmlListContainerKind = Literal["Bag", "Seq", "Alt"]
type XmpStructuredShape = Literal["struct", "struct_list"]
type PngPixelUnits = Literal[0, 1]
type OutputFileOverwritePolicy = Literal[
    "error_if_exists",
    "overwrite_existing",
    "append_existing",
    "overwrite_new_then_append",
]
type OutputTagFileExtensionFilterMode = Literal["include", "exclude"]
type UnsafeBinaryOutputPolicy = Literal[
    "explicit_tags_only",
    "suppress_binary_tags",
    "request_all_allows_unsafe",
]
type PublicPrintFormatSourceKind = Literal["inline", "file"]
type PublicPrintFormatSectionKind = Literal["HEAD", "SECT", "IF", "BODY", "ENDS", "TAIL"]
type PublicCharsetTarget = Literal[
    "EXIF",
    "FileName",
    "ID3",
    "IPTC",
    "Photoshop",
    "QuickTime",
    "RIFF",
    "XMP",
]

PUBLIC_DIRECTORY_READ_EXTENSIONS = frozenset(
    {
        ".avi",
        ".bmp",
        ".jpe",
        ".jpeg",
        ".jpg",
        ".mka",
        ".mks",
        ".mkv",
        ".mp3",
        ".png",
        ".wav",
        ".webm",
        ".webp",
    }
)
PUBLIC_RIFF_FILE_TYPES = frozenset({"AVI", "WAV", "WEBP"})
MAX_PUBLIC_BINARY_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_PUBLIC_WILDCARD_EXPANSION_TAGS = 512
_PUBLIC_UNSAFE_BINARY_TAG_NAMES = frozenset(
    {
        "ImageData",
        "ImageDataHash",
        "RawImage",
        "RawThermalImage",
        "SphericalVideoXML",
        "Trailer",
    }
)
_PUBLIC_SAFE_BINARY_TAG_NAMES = frozenset(
    {
        "EmbeddedVideo",
        "ICC_Profile",
        "JpgFromRaw",
        "OtherImage",
        "PreviewImage",
        "ThumbnailImage",
    }
)
_PUBLIC_INSPECT_PREFIX_BYTES = 12
_PUBLIC_INSPECT_FULL_READ_LIMIT_BYTES = 64 * 1024 * 1024
_PUBLIC_MEDIA_READ_FULL_READ_LIMIT_BYTES = 64 * 1024 * 1024
_PRINT_FORMAT_DEFAULT_FILENAME_SANITIZER = "__exiftool_default_filename_sanitizer__"
_PUBLIC_READ_CONDITION_TAG_RE = r"(?:[-_0-9A-Za-z]+:)*[-_0-9A-Za-z]+#?"
_PUBLIC_READ_CONDITION_EXISTS_RE = re.compile(
    rf"^\s*(?P<negated>not\s+)?\$(?:\{{(?P<braced_tag>{_PUBLIC_READ_CONDITION_TAG_RE})\}}|(?P<tag>{_PUBLIC_READ_CONDITION_TAG_RE}))\s*$",
    re.IGNORECASE,
)
_PUBLIC_READ_CONDITION_COMPARISON_RE = re.compile(
    rf"^\s*\$(?:\{{(?P<braced_tag>{_PUBLIC_READ_CONDITION_TAG_RE})\}}|(?P<tag>{_PUBLIC_READ_CONDITION_TAG_RE}))\s*"
    r"(?P<operator>==|!=|<=|>=|<|>|eq|ne|lt|le|gt|ge)\s*"
    r"(?P<literal>-?(?:0|[1-9]\d*)(?:\.\d+)?|\"[^\"]*\"|'[^']*')\s*$",
    re.IGNORECASE,
)
_PUBLIC_READ_CONDITION_TAG_REFERENCE_RE = re.compile(
    rf"\$(?:\{{(?P<braced_tag>{_PUBLIC_READ_CONDITION_TAG_RE})\}}|(?P<tag>{_PUBLIC_READ_CONDITION_TAG_RE}))"
)
_PUBLIC_EXIF_SIDECAR_SCALAR_TAG_KEYS = frozenset(
    {
        "description",
        "imagedescription",
        "orientation",
        "modifydate",
        "artist",
        "iso",
        "datetimeoriginal",
        "focallength",
        "scenecapturetype",
    }
)
BOUNDED_EXIF_FAMILY_1_GROUPS = frozenset(
    {
        "ExifIFD",
        "GPS",
        "IFD0",
        "IFD1",
        "InteropIFD",
        "MakerNotes",
        "SubIFD",
    }
)
_EXIF_ORIENTATION_VALUE_CONV_BY_PRINT_CONV: dict[str, int] = {
    # Source: ../exiftool/lib/Image/ExifTool/Exif.pm lines 291-300.
    "Horizontal (normal)": 1,
    "Mirror horizontal": 2,
    "Rotate 180": 3,
    "Mirror vertical": 4,
    "Mirror horizontal and rotate 270 CW": 5,
    "Rotate 90 CW": 6,
    "Mirror horizontal and rotate 90 CW": 7,
    "Rotate 270 CW": 8,
}


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    details: JsonObject | None = None


@dataclass(frozen=True)
class OutputTagFileExtensionFilter:
    extension: str
    mode: OutputTagFileExtensionFilterMode = "include"


@dataclass(frozen=True)
class OutputPerSourceFileRouting:
    format_template: str
    overwrite_policy: OutputFileOverwritePolicy = "error_if_exists"


@dataclass(frozen=True)
class OutputPerTagFileRouting:
    format_template: str
    overwrite_policy: OutputFileOverwritePolicy = "error_if_exists"
    extension_filters: tuple[OutputTagFileExtensionFilter, ...] = ()


@dataclass(frozen=True)
class OutputWriteFileRouting:
    output_path_template: str
    overwrite_policy: OutputFileOverwritePolicy = "error_if_exists"
    stdout: bool = False


@dataclass(frozen=True)
class OutputFileRoutingRequest:
    stdout_binary: bool = False
    unsafe_binary_policy: UnsafeBinaryOutputPolicy = "explicit_tags_only"
    per_source_file: OutputPerSourceFileRouting | None = None
    per_tag_file: OutputPerTagFileRouting | None = None
    write_output_file: OutputWriteFileRouting | None = None


@dataclass(frozen=True)
class PublicPrintFormatTemplate:
    source_kind: PublicPrintFormatSourceKind
    raw_argument: str
    lines: tuple[str, ...]
    append_inline_newline: bool = True


@dataclass(frozen=True)
class PublicCharsetOption:
    target: PublicCharsetTarget
    charset: str
    raw_option: str


@dataclass(frozen=True)
class OutputRenderRequest:
    format: RenderFormat = "text"
    include_group_names: bool = False
    include_unknown_tags: bool = False
    unknown_tag_level: ReadGraphUnknownTagLevel = 0
    allow_duplicate_tags: bool = False
    group_name_families: tuple[PublicReadGroupFamily, ...] = ()
    short_output_level: int = 0
    short_tag_names: bool = False
    very_short_output: bool = False
    sort_output: bool = False
    numeric_output: bool = False
    csv_delimiter: str = ","
    list_separator: str = ", "
    join_list_values: bool = False
    binary_output: bool = False
    suppress_binary_tags: bool = False
    output_file_routing: OutputFileRoutingRequest = OutputFileRoutingRequest()
    xml_tag_id_format: XmlTagIdFormat = "none"
    xml_include_table_metadata: bool = False
    structured_output: bool = False
    list_item_index: int | None = None
    missing_tag_value: str | None = None
    ignore_minor_errors: bool = False
    print_format_templates: tuple[PublicPrintFormatTemplate, ...] = ()
    verbose_level: int = 0
    html_dump_base: int = 0
    extract_embedded_level: int = 0
    request_all_level: int = 0
    scan_for_xmp: bool = False
    output_filter: str | None = None
    output_charset: str = "UTF8"
    language_code: str = "en"
    internal_charset_options: tuple[PublicCharsetOption, ...] = ()
    plot_svg_settings: PlotSvgSettings = dataclass_field(default_factory=_default_plot_svg_settings)


@dataclass(frozen=True)
class PublicReadGroupSelector:
    raw: str
    name: str
    family: PublicReadGroupFamily | None = None
    wildcard_mode: PublicReadGroupWildcardMode = "literal"
    duplicate_instance_mode: PublicReadDuplicateInstanceMode = "default"
    duplicate_instance_number: int | None = None


@dataclass(frozen=True)
class PublicReadTagSelector:
    raw: str
    tag_name: str
    group_chain: tuple[PublicReadGroupSelector, ...] = ()
    tag_wildcard: bool = False
    all_tag: bool = False
    value_conversion_disabled: bool = False

    @property
    def has_group_chain(self) -> bool:
        return len(self.group_chain) > 1

    @property
    def has_family_selector(self) -> bool:
        return any(group.family is not None for group in self.group_chain)

    @property
    def has_all_instances_group(self) -> bool:
        return any(group.wildcard_mode == "all_instances" for group in self.group_chain)

    @property
    def has_duplicate_instance_selector(self) -> bool:
        return any(group.duplicate_instance_mode != "default" for group in self.group_chain)


@dataclass(frozen=True)
class PublicReadTagExclusion:
    raw: str


@dataclass(frozen=True)
class PublicReadCondition:
    raw_option: str
    expression: str
    pass_number: PublicReadConditionPass = 0


@dataclass(frozen=True)
class PublicReadConditionPlan:
    condition: PublicReadCondition
    tag: str
    operator: PublicReadConditionOperator
    comparison_value: str | float | None = None
    vm_program: SafeExpressionProgram | None = None
    vm_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicReadFileOrder:
    raw_option: str
    tag: str
    fast_pass: PublicReadConditionPass = 0


@dataclass(frozen=True)
class PublicReadAlternateFile:
    raw_option: str
    path: Path
    slot: PublicReadAlternateFileSlot


@dataclass(frozen=True)
class PublicReadSourceFile:
    raw_option: str
    path: Path


@dataclass(frozen=True)
class _PublicInsertTagUnresolvedToken:
    token: str
    reason: _PublicInsertTagUnresolvedReason


@dataclass(frozen=True)
class OutputRenderResult:
    request: OutputRenderRequest
    status: PublicOperationStatus
    diagnostics: tuple[Diagnostic, ...] = ()
    rendered_text: str = ""


@dataclass(frozen=True)
class MetadataReadRequest:
    paths: tuple[Path, ...]
    tags: tuple[str, ...] = ()
    tag_exclusions: tuple[PublicReadTagExclusion, ...] = ()
    recursive: bool = False
    recurse_dot_directories: bool = False
    ignore_directories: tuple[str, ...] = ()
    fast_scan_level: int | None = None
    extension_filters: tuple[ExtensionFilter, ...] = ()
    conditions: tuple[PublicReadCondition, ...] = ()
    file_order: tuple[PublicReadFileOrder, ...] = ()
    alternate_files: tuple[PublicReadAlternateFile, ...] = ()
    source_files: tuple[PublicReadSourceFile, ...] = ()
    user_params: tuple[PublicUserParam, ...] = ()
    render: OutputRenderRequest = OutputRenderRequest()


_PUBLIC_READ_GRAPH_REQUEST: ContextVar[MetadataReadRequest | None] = ContextVar(
    "_PUBLIC_READ_GRAPH_REQUEST",
    default=None,
)


@dataclass(frozen=True)
class PublicBatchFrameRequest:
    args: tuple[str, ...]
    execute_id: str | None
    index: int
    ready_marker: str | None = None


@dataclass(frozen=True)
class PublicBatchRequest:
    frames: tuple[PublicBatchFrameRequest, ...]
    common_args: tuple[str, ...] = ()
    persistent_process_management: bool = False
    process_management_contract: str = (
        "Public batch protocol requests model one-shot -execute frames and bounded "
        "-stay_open argfile replay. Long-lived ExifTool-compatible polling process "
        "management is an explicit release-scope deferral."
    )


@dataclass(frozen=True)
class ExtensionFilter:
    extension: str
    mode: ExtensionFilterMode = "include"


@dataclass(frozen=True)
class MetadataReadRecord:
    path: Path
    values: JsonRecord
    rendered_text: str
    rendered_binary: bytes = b""
    xml_namespaces: tuple[XmlNamespaceBinding, ...] = ()
    xml_elements: tuple[XmlTagElement, ...] = ()
    output_tags: tuple[OutputRenderedTag, ...] = ()


@dataclass(frozen=True)
class XmlNamespaceBinding:
    prefix: str
    uri_path: str


@dataclass(frozen=True)
class XmlStructField:
    group: str
    tag: str
    value: TagValue
    uri_path: str | None = None
    struct_fields: tuple[XmlStructField, ...] = ()


@dataclass(frozen=True)
class XmlStructListItemBoundary:
    source_index: int
    source_path: str


@dataclass(frozen=True)
class XmlStructListItem:
    fields: tuple[XmlStructField, ...]
    boundary: XmlStructListItemBoundary | None = None


@dataclass(frozen=True)
class XmlTagElement:
    group: str
    tag: str
    value: TagValue
    uri_path: str
    et_id: str | None = None
    et_table: str | None = None
    list_container: XmlListContainerKind = "Bag"
    struct_fields: tuple[XmlStructField, ...] = ()
    struct_list_items: tuple[XmlStructListItem, ...] = ()


@dataclass
class _PendingXmlResourceRefParent:
    group: str
    parent_name: str
    uri_path: str
    fields: dict[str, XmlStructField]
    first_index: int


@dataclass
class _PendingXmlManifestParent:
    group: str
    parent_name: str
    uri_path: str
    simple_fields: dict[str, XmlStructField]
    reference_fields: dict[str, XmlStructField]
    first_index: int


@dataclass(frozen=True)
class _XmlStructuredFieldTarget:
    parent_group: str
    parent_name: str
    parent_element_name: str
    parent_uri_path: str
    parent_shape: XmpStructuredShape
    parent_list_kind: XmlListContainerKind
    field_group: str
    field_name: str
    source_field_name: str
    field_uri_path: str | None
    field_order: int
    nested_path: tuple[_XmlStructuredPathStep, ...] = ()


@dataclass(frozen=True)
class _XmlStructuredPathStep:
    group: str
    field_name: str
    uri_path: str | None
    list_kind: XmlListContainerKind | None = None


@dataclass
class _PendingXmlStructuredParent:
    target: _XmlStructuredFieldTarget
    fields: dict[str, XmlStructField]
    first_index: int


@dataclass(frozen=True)
class OutputRenderedTag:
    label: str
    tag_name: str
    group_name: str
    group_names: tuple[str, ...]
    value: TagValue
    suggested_extension: str = "txt"
    original_file_name: str = ""


@dataclass(frozen=True)
class OutputFileWriteResult:
    source_path: Path
    output_path: Path
    bytes_written: int
    replaced_existing: bool
    routing_kind: Literal["per_source_file", "per_tag_file"]


@dataclass(frozen=True)
class MetadataReadResult:
    request: MetadataReadRequest
    status: PublicOperationStatus
    diagnostics: tuple[Diagnostic, ...]
    records: tuple[MetadataReadRecord, ...] = ()
    rendered_text: str = ""
    rendered_binary: bytes = b""
    output_files: tuple[OutputFileWriteResult, ...] = ()
    condition_failed_count: int = 0


@dataclass(frozen=True)
class MetadataAssignment:
    tag: str
    value: str
    order_index: int | None = None
    operation: MetadataAssignmentOperation = "set"


@dataclass(frozen=True)
class MetadataWriteTagReference:
    raw: str
    tag_name: str
    group_chain: tuple[str, ...] = ()
    target_kind: PublicWriteTargetKind = "tag"


@dataclass(frozen=True)
class MetadataWriteOperationSummary:
    operation: PublicWriteOperation
    target: MetadataWriteTagReference
    value: str | None = None


@dataclass(frozen=True)
class PublicWriteSideEffectBlocker:
    tag: str
    effect_kind: PublicWriteSideEffectKind
    requested_operation: PublicWriteOperation
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class XmpSidecarCopyRouteRequest:
    source_group: XmpSidecarCopyGroup
    destination_group: XmpSidecarCopyDestinationGroup
    tag_pattern: XmpSidecarCopyTagPattern = "*"


@dataclass(frozen=True)
class XmpSidecarCopyFromFileRequest:
    source_path: Path
    routes: tuple[XmpSidecarCopyRouteRequest, ...]


@dataclass(frozen=True)
class ExifSidecarCopyRouteRequest:
    source_group: ExifSidecarCopyGroup
    tag_pattern: ExifSidecarCopyTagPattern = ""


@dataclass(frozen=True)
class ExifSidecarCopyFromFileRequest:
    source_path: Path
    routes: tuple[ExifSidecarCopyRouteRequest, ...]


@dataclass(frozen=True)
class PublicCopyFromFileRouteRequest:
    raw: str
    kind: PublicCopyFromFileRouteKind
    order_index: int
    source_selector: str | None = None
    destination_selector: str | None = None
    datfile_path: Path | None = None


@dataclass(frozen=True)
class PublicCopyFromFileAlternateFile:
    raw_option: str
    path: Path
    slot: PublicReadAlternateFileSlot


@dataclass(frozen=True)
class PublicCopyFromFileRequest:
    source: str
    source_kind: PublicCopyFromFileSourceKind
    routes: tuple[PublicCopyFromFileRouteRequest, ...]
    alternate_files: tuple[PublicCopyFromFileAlternateFile, ...] = ()


@dataclass(frozen=True)
class PngTextChunkWriteRequest:
    keyword: str
    value: bytes
    language_code: str = ""
    force_itxt: bool = False
    compress: bool = False


@dataclass(frozen=True)
class PngChunkWriteRequest:
    text_chunks: tuple[PngTextChunkWriteRequest, ...] = ()
    xmp_payload: bytes | None = None
    exif_payload: bytes | None = None
    icc_payload: bytes | None = None
    icc_profile_name: str | None = None
    pixels_per_unit_x: int | None = None
    pixels_per_unit_y: int | None = None
    pixel_units: PngPixelUnits | None = None
    delete_metadata_groups: tuple[str, ...] = ()
    delete_all_metadata: bool = False


@dataclass(frozen=True)
class RiffWavMetadataWriteRequest:
    delete_all_modeled_metadata: bool = False


@dataclass(frozen=True)
class RiffWebpMetadataWriteRequest:
    delete_all_metadata: bool = False


@dataclass(frozen=True)
class PublicImportWriteRequest:
    import_format: PublicImportWriteFormat
    path: Path
    add_list_items: bool = False
    csv_delimiter: str = ","


@dataclass(frozen=True)
class MetadataWriteRequest:
    paths: tuple[Path, ...]
    assignments: tuple[MetadataAssignment, ...] = ()
    deletes: tuple[str, ...] = ()
    delete_order_indexes: tuple[int, ...] = ()
    xmp_sidecar_copy_from_file: XmpSidecarCopyFromFileRequest | None = None
    exif_sidecar_copy_from_file: ExifSidecarCopyFromFileRequest | None = None
    public_copy_from_file: PublicCopyFromFileRequest | None = None
    png_chunk_write: PngChunkWriteRequest | None = None
    riff_wav_metadata_write: RiffWavMetadataWriteRequest | None = None
    riff_webp_metadata_write: RiffWebpMetadataWriteRequest | None = None
    import_write: PublicImportWriteRequest | None = None
    policy: WritePolicy = "preserve_original"
    preserve_file_times: bool = False
    write_output_file: OutputWriteFileRouting | None = None
    list_separator: str | None = None
    tag_lookup_package_path: Path | None = None


@dataclass(frozen=True)
class MetadataWritePlan:
    request: MetadataWriteRequest
    status: PublicOperationStatus
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class PublicWriteDispatchCandidate:
    operation: PublicWriteOperation
    tag: str
    action: str
    status: str
    reason: str
    request_id: str
    request_path: str
    container_family: str | None
    write_tags: tuple[str, ...]
    native_callables: tuple[JsonObject, ...]


@dataclass(frozen=True)
class PublicWriteDispatchClassification:
    operation: PublicWriteOperation
    tag: str
    actionability: str
    candidates: tuple[PublicWriteDispatchCandidate, ...]


@dataclass(frozen=True)
class MetadataWriteResult:
    request: MetadataWriteRequest
    status: PublicOperationStatus
    diagnostics: tuple[Diagnostic, ...]
    changed_paths: tuple[Path, ...] = ()
    stdout_binary: bytes = b""


@dataclass(frozen=True)
class _SourceBackedWriteOutputBytes:
    inner_result: MetadataWriteResult
    output_bytes: bytes
    source_access_time_ns: int
    source_modified_time_ns: int


@dataclass(frozen=True)
class _XmpSidecarWriteOutputBytes:
    output_bytes: bytes
    changed_xmp_properties: int
    deleted_xmp_properties: int
    unsupported_diagnostic: Diagnostic | None = None


@dataclass(frozen=True)
class _ExifSidecarWriteOutputBytes:
    output_bytes: bytes
    changed_exif_tags: tuple[str, ...]
    unsupported_diagnostic: Diagnostic | None = None


@dataclass(frozen=True)
class _RemainingSelectedWriteOutputBytes:
    output_bytes: bytes
    selected_output_type: RemainingSelectedWriteOutputType
    block_tag: str
    changed_exif_tags: tuple[str, ...] = ()
    unsupported_diagnostic: Diagnostic | None = None


@dataclass(frozen=True)
class _PlannedSourceBackedWriteOutput:
    source_path: Path
    output_path: Path
    source_backed_output: _SourceBackedWriteOutputBytes


_REMAINING_SELECTED_OUTPUT_SUFFIX_TO_TYPE: dict[str, RemainingSelectedWriteOutputType] = {
    ".dr4": "dr4",
    ".exv": "exv",
    ".icc": "icc",
    ".icm": "icc",
    ".mie": "mie",
    ".vrd": "vrd",
}


@dataclass(frozen=True)
class CapabilityQueryRequest:
    include_experimental: bool = False
    tag_names: tuple[str, ...] = ()
    writable_tag_names: tuple[str, ...] = ()
    tag_lookup_package_path: Path | None = None


@dataclass(frozen=True)
class TagLookupCapabilitySummary:
    package_path: Path
    package_loaded: bool
    table_count: int
    lookup_tag_count: int
    tag_exists_count: int
    composite_module_count: int
    queried_tag_count: int
    wildcard_query_count: int
    resolved_tag_count: int
    exists_only_tag_count: int
    missing_tag_count: int
    writable_candidate_count: int
    writable_selection_count: int
    writable_resolved_count: int
    writable_ambiguous_count: int
    writable_blocked_count: int
    writable_not_found_count: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PublicGeolocationListRequest:
    package_path: Path
    language_code: str = ""
    include_alternate_names: bool = False
    sort_by_city: bool = False
    sort_mode: GeolocationListSortMode = "database"
    min_population: float | None = None
    feature_option: str = ""
    include_header: bool = True
    include_title: bool = True


@dataclass(frozen=True)
class PublicGeolocationListResult:
    request: PublicGeolocationListRequest
    status: PublicOperationStatus
    diagnostics: tuple[Diagnostic, ...] = ()
    rows: tuple[GeolocationListRow, ...] = ()
    alternate_names_column_available: bool = False
    rendered_text: str = ""


@dataclass(frozen=True)
class PublicTagLookupRequest:
    package_path: Path
    tag_names: tuple[str, ...] = ()
    writable_tag_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicTagLookupResult:
    request: PublicTagLookupRequest
    status: PublicOperationStatus
    diagnostics: tuple[Diagnostic, ...] = ()
    tag_results: tuple[TagLookupRuntimeResult, ...] = ()
    writable_selections: tuple[TagLookupSelectionResult, ...] = ()
    summary: TagLookupCapabilitySummary | None = None


@dataclass(frozen=True)
class CapabilitySurfaceDescriptor:
    name: str
    status: PublicOperationStatus
    summary: str


@dataclass(frozen=True)
class CapabilityDescriptor:
    name: str
    status: PublicOperationStatus
    summary: str
    surfaces: tuple[CapabilitySurfaceDescriptor, ...] = ()


@dataclass(frozen=True)
class CapabilityQueryResult:
    request: CapabilityQueryRequest
    status: PublicOperationStatus
    capabilities: tuple[CapabilityDescriptor, ...]
    diagnostics: tuple[Diagnostic, ...] = ()
    tag_lookup_summary: TagLookupCapabilitySummary | None = None
    tag_lookup_capabilities: tuple[TagLookupRuntimeCapability, ...] = ()
    tag_lookup_writable_selections: tuple[TagLookupSelectionResult, ...] = ()


@dataclass(frozen=True)
class FileInspectRequest:
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class FileInspectRecord:
    path: Path
    file_type: str
    values: JsonRecord
    structure: JsonObject


@dataclass(frozen=True)
class FileInspectResult:
    request: FileInspectRequest
    status: PublicOperationStatus
    diagnostics: tuple[Diagnostic, ...]
    records: tuple[FileInspectRecord, ...] = ()


def read_metadata(request: MetadataReadRequest) -> MetadataReadResult:
    condition_plans = tuple(
        plan
        for condition in request.conditions
        if (plan := _public_read_condition_plan(condition)) is not None
    )
    execution_control_diagnostic = public_read_execution_controls_not_connected_diagnostic(
        request,
        condition_plans,
    )
    if execution_control_diagnostic is not None:
        return MetadataReadResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(execution_control_diagnostic,),
        )

    output_file_routing_diagnostic = output_file_routing_not_connected_diagnostic(request.render)
    if output_file_routing_diagnostic is not None:
        return MetadataReadResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(output_file_routing_diagnostic,),
        )

    if request.render.binary_output and not _binary_output_uses_record_renderer(request.render):
        return _read_metadata_binary(request, condition_plans)

    if request.render.format == "html_dump":
        return _read_metadata_html_dump(request, condition_plans)

    if request.render.format == "plot":
        return _read_metadata_plot(request, condition_plans)

    if request.render.format not in ("text", "json", "xml", "csv", "tab", "html", "php"):
        return MetadataReadResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                _operation_deferred(
                    "renderer_not_connected",
                    "Public read execution is connected for text, JSON, XML, CSV, tab, "
                    "HTML, and PHP output only.",
                ),
            ),
        )

    records: list[MetadataReadRecord] = []
    diagnostics: list[Diagnostic] = []
    condition_failed_count = 0
    extract_embedded_byte_range_exposed = False
    extract_embedded_recursive_traversal_required = False
    for original_path in _expanded_read_paths(request):
        path, source_file_diagnostics = _public_read_source_file_path(original_path, request)
        diagnostics.extend(source_file_diagnostics)
        if source_file_diagnostics:
            continue
        bound_diagnostic = _public_media_read_bound_diagnostic(path)
        if bound_diagnostic is not None:
            diagnostics.append(bound_diagnostic)
            continue
        try:
            graph = _build_public_read_graph_for_request(path, request)
        except FileNotFoundError:
            diagnostics.append(_file_not_found_diagnostic(path))
            continue
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    code="file_read_failed",
                    message=f"Unable to read metadata from {path}: {exc}",
                )
            )
            continue
        embedded_byte_range_tags = _public_extract_embedded_byte_range_tag_names(graph)
        embedded_timed_record_tags = _public_extract_embedded_bounded_timed_record_tag_names(graph)
        if embedded_byte_range_tags:
            extract_embedded_byte_range_exposed = True
        if embedded_timed_record_tags:
            extract_embedded_byte_range_exposed = True
            if request.render.extract_embedded_level > 1:
                extract_embedded_recursive_traversal_required = True
        if any(
            _public_embedded.public_embedded_tag_requires_recursive_traversal(tag_name)
            for tag_name in embedded_byte_range_tags
        ):
            extract_embedded_recursive_traversal_required = True
        graph = _graph_with_public_user_params(graph, request, original_path)
        graph, alternate_file_diagnostics = _graph_with_public_alternate_file_reads(
            graph,
            request,
            condition_plans,
            format_base_path=original_path,
        )
        diagnostics.extend(alternate_file_diagnostics)
        if not _public_read_conditions_match(graph, condition_plans):
            condition_failed_count += 1
            continue
        output_group_family_diagnostic = _unsupported_public_output_group_families_diagnostic(
            path,
            request.render,
        )
        if output_group_family_diagnostic is not None:
            diagnostics.append(output_group_family_diagnostic)
        render_tags, wildcard_diagnostics = _expand_public_read_wildcards(
            graph,
            request.tags,
            path,
            request.render,
        )
        diagnostics.extend(wildcard_diagnostics)
        excluded_graph = _graph_with_public_read_exclusions(graph, request.tag_exclusions)
        render_tags = _render_tags_with_public_read_exclusions(
            graph,
            excluded_graph,
            render_tags,
            request.tag_exclusions,
            request.render,
        )
        render_tags = _render_tags_with_public_duplicate_instances(
            excluded_graph,
            render_tags,
            request.render,
            request.tags,
        )
        public_output_graph = _public_output_visible_graph(
            excluded_graph,
            include_unknown_tags=request.render.include_unknown_tags,
        )
        public_output_graph = _graph_with_public_binary_suppression(
            public_output_graph,
            request.render,
        )
        render_tags = _render_tags_with_public_output_suppression(
            excluded_graph,
            public_output_graph,
            render_tags,
            request.render,
        )
        if request.tags and not render_tags:
            record: JsonRecord = {"SourceFile": path.as_posix()}
            records.append(
                MetadataReadRecord(
                    path=path,
                    values=record,
                    rendered_text=_render_record_output(record, request.render),
                )
            )
            continue
        render_graph = _graph_with_public_duplicate_instance_projection(
            public_output_graph, render_tags
        )
        render_graph = _graph_with_public_output_group_projection(render_graph, request.render)
        record, issues = graph_record_for_request(
            render_graph,
            path.as_posix(),
            _renderer_args_for_read_request(request, tags=render_tags),
        )
        forced_missing_issues = tuple(issues)
        record, output_group_provenance_diagnostic = _record_with_output_group_family(
            render_graph,
            record,
            request.render,
            path,
        )
        record = _record_with_value_conversion_disabled_tags(
            record,
            request.tags,
            request.render,
        )
        record = _record_with_list_item_projection(record, request.render)
        if output_group_provenance_diagnostic is not None:
            diagnostics.append(output_group_provenance_diagnostic)
        if issues:
            record, remaining_issues = _record_with_forced_missing_tags(
                record,
                tuple(issues),
                request.render,
            )
            issues = list(remaining_issues)
        if issues:
            diagnostics.append(
                Diagnostic(
                    code="requested_tag_not_rendered",
                    message=f"{path}: {format_render_issues(issues)}",
                    details={
                        "path": path.as_posix(),
                        "requested_tags": [_render_issue_requested_tag(issue) for issue in issues],
                    },
                )
            )
        for graph_diagnostic in _public_read_graph_diagnostics(graph):
            diagnostics.append(
                Diagnostic(
                    code="read_graph_diagnostic",
                    message=f"{path}: {graph_diagnostic}",
                )
            )
        xml_elements = _xml_elements_for_record(render_graph, render_tags, request.render)
        xml_elements = _xml_elements_with_forced_missing_tags(
            xml_elements,
            forced_missing_issues,
            request.render,
        )
        xml_elements = _xml_elements_with_list_item_projection(xml_elements, request.render)
        xml_elements = _xml_elements_with_source_xmp_struct_list_boundaries(
            path,
            xml_elements,
            request.render,
        )
        diagnostics.extend(
            _structured_xmp_renderer_blocker_diagnostics(
                path,
                xml_elements,
                request.render,
            )
        )
        xml_elements = _xml_elements_with_structured_xmp_parents(xml_elements, request.render)
        xml_elements = _sorted_xml_elements(xml_elements, request.render)
        xml_namespaces = _xml_namespaces_for_elements(xml_elements)
        if not xml_namespaces:
            xml_namespaces = _xml_namespaces_for_record(render_graph, record)
        record = _sorted_record(record, request.render)
        filter_diagnostic = _public_output_filter_diagnostic(path, request.render)
        if filter_diagnostic is not None:
            diagnostics.append(filter_diagnostic)
        record = _record_with_public_output_filter(record, request.render)
        xml_elements = _xml_elements_with_public_output_filter(xml_elements, request.render)
        records.append(
            MetadataReadRecord(
                path=path,
                values=record,
                rendered_text=_render_record_output(record, request.render),
                xml_namespaces=xml_namespaces,
                xml_elements=xml_elements,
                output_tags=_output_rendered_tags_for_record(
                    render_graph,
                    record,
                    include_binary=request.render.binary_output,
                ),
            )
        )

    output_files, output_file_diagnostics = _execute_read_output_file_routing(
        records,
        request.render,
    )
    diagnostics.extend(output_file_diagnostics)

    if request.render.numeric_output:
        diagnostics.append(numeric_output_not_connected_diagnostic(request))
    diagnostics.extend(_diagnostics_for_charset_read_options(request))
    diagnostics.extend(
        _diagnostics_for_deferred_inspection_read_options(
            request,
            extract_embedded_byte_range_exposed=extract_embedded_byte_range_exposed,
            extract_embedded_recursive_traversal_required=(
                extract_embedded_recursive_traversal_required
            ),
        )
    )

    diagnostics = _csv_compatible_read_diagnostics(records, request, diagnostics)

    if condition_failed_count and not any(
        _read_diagnostic_is_blocking(diagnostic) for diagnostic in diagnostics
    ):
        diagnostics.append(_files_failed_condition_diagnostic(condition_failed_count, request))

    if condition_failed_count and not records:
        rendered_text = ""
    else:
        rendered_text, render_diagnostics = _render_read_result_text_with_diagnostics(
            records,
            request,
        )
        diagnostics.extend(render_diagnostics)

    return MetadataReadResult(
        request=request,
        status=_metadata_read_status(
            tuple(records),
            diagnostics,
            condition_failed_count=condition_failed_count,
        ),
        diagnostics=tuple(diagnostics),
        records=tuple(records),
        rendered_text=rendered_text,
        output_files=output_files,
        condition_failed_count=condition_failed_count,
    )


def _read_metadata_html_dump(
    request: MetadataReadRequest,
    condition_plans: tuple[PublicReadConditionPlan, ...],
) -> MetadataReadResult:
    from exifmodern.formats.jpeg.html_dump_state import (
        render_html_dump_document as _render_html_dump_document,
    )

    records: list[MetadataReadRecord] = []
    diagnostics: list[Diagnostic] = []
    condition_failed_count = 0
    extract_embedded_byte_range_exposed = False
    extract_embedded_recursive_traversal_required = False
    for original_path in _expanded_read_paths(request):
        path, source_file_diagnostics = _public_read_source_file_path(original_path, request)
        diagnostics.extend(source_file_diagnostics)
        if source_file_diagnostics:
            continue
        bound_diagnostic = _public_media_read_bound_diagnostic(path)
        if bound_diagnostic is not None:
            diagnostics.append(bound_diagnostic)
            continue
        try:
            graph = _build_public_read_graph_for_request(path, request)
        except FileNotFoundError:
            diagnostics.append(_file_not_found_diagnostic(path))
            continue
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    code="file_read_failed",
                    message=f"Unable to read metadata from {path}: {exc}",
                )
            )
            continue
        embedded_byte_range_tags = _public_extract_embedded_byte_range_tag_names(graph)
        embedded_timed_record_tags = _public_extract_embedded_bounded_timed_record_tag_names(graph)
        if embedded_byte_range_tags:
            extract_embedded_byte_range_exposed = True
        if embedded_timed_record_tags:
            extract_embedded_byte_range_exposed = True
            if request.render.extract_embedded_level > 1:
                extract_embedded_recursive_traversal_required = True
        if any(
            _public_embedded.public_embedded_tag_requires_recursive_traversal(tag_name)
            for tag_name in embedded_byte_range_tags
        ):
            extract_embedded_recursive_traversal_required = True
        graph = _graph_with_public_user_params(graph, request, original_path)
        graph, alternate_file_diagnostics = _graph_with_public_alternate_file_reads(
            graph,
            request,
            condition_plans,
            format_base_path=original_path,
        )
        diagnostics.extend(alternate_file_diagnostics)
        if not _public_read_conditions_match(graph, condition_plans):
            condition_failed_count += 1
            continue
        for graph_diagnostic in _public_read_graph_diagnostics(graph):
            diagnostics.append(
                Diagnostic(
                    code="read_graph_diagnostic",
                    message=f"{path}: {graph_diagnostic}",
                )
            )
        html_dump_state = graph.html_dump_state
        if html_dump_state is None or not html_dump_state.byte_ranges:
            diagnostics.append(_html_dump_byte_range_state_unavailable_diagnostic(path, graph))
            continue
        if html_dump_state.html_dump_base != request.render.html_dump_base:
            html_dump_state = replace(
                html_dump_state,
                html_dump_base=request.render.html_dump_base,
            )
        try:
            source_data = read_public_document_payload(
                path,
                byte_limit=_PUBLIC_MEDIA_READ_FULL_READ_LIMIT_BYTES,
            )
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    code="file_read_failed",
                    message=f"Unable to read htmlDump bytes from {path}: {exc}",
                )
            )
            continue
        if source_data is None:
            diagnostics.append(
                Diagnostic(
                    code="html_dump_source_deferred",
                    message=(
                        f"{path}: htmlDump source exceeds "
                        f"{_PUBLIC_MEDIA_READ_FULL_READ_LIMIT_BYTES} bytes; "
                        "range-backed htmlDump rendering is not yet available."
                    ),
                    details={
                        "limit_bytes": _PUBLIC_MEDIA_READ_FULL_READ_LIMIT_BYTES,
                        "blocking": True,
                    },
                )
            )
            continue
        rendered_text = _render_html_dump_document(
            source_data,
            html_dump_state,
            dump_limit=_html_dump_limit_for_request(request),
        )
        record: JsonRecord = {"SourceFile": path.as_posix()}
        records.append(
            MetadataReadRecord(
                path=path,
                values=record,
                rendered_text=rendered_text,
                output_tags=(),
            )
        )

    diagnostics.extend(_diagnostics_for_charset_read_options(request))
    diagnostics.extend(
        _diagnostics_for_deferred_inspection_read_options(
            request,
            extract_embedded_byte_range_exposed=extract_embedded_byte_range_exposed,
            extract_embedded_recursive_traversal_required=(
                extract_embedded_recursive_traversal_required
            ),
        )
    )

    if condition_failed_count and not any(
        _read_diagnostic_is_blocking(diagnostic) for diagnostic in diagnostics
    ):
        diagnostics.append(_files_failed_condition_diagnostic(condition_failed_count, request))

    if condition_failed_count and not records:
        rendered_text = ""
    else:
        rendered_text = "".join(record.rendered_text for record in records)

    return MetadataReadResult(
        request=request,
        status=_metadata_read_status(
            tuple(records),
            diagnostics,
            condition_failed_count=condition_failed_count,
        ),
        diagnostics=tuple(diagnostics),
        records=tuple(records),
        rendered_text=rendered_text,
        condition_failed_count=condition_failed_count,
    )


def _read_metadata_plot(
    request: MetadataReadRequest,
    condition_plans: tuple[PublicReadConditionPlan, ...],
) -> MetadataReadResult:
    records: list[MetadataReadRecord] = []
    diagnostics: list[Diagnostic] = []
    plot_graphs: list[ReadGraph] = []
    condition_failed_count = 0
    for original_path in _expanded_read_paths(request):
        path, source_file_diagnostics = _public_read_source_file_path(original_path, request)
        diagnostics.extend(source_file_diagnostics)
        if source_file_diagnostics:
            continue
        bound_diagnostic = _public_media_read_bound_diagnostic(path)
        if bound_diagnostic is not None:
            diagnostics.append(bound_diagnostic)
            continue
        try:
            graph = _build_public_read_graph_for_request(path, request)
        except FileNotFoundError:
            diagnostics.append(_file_not_found_diagnostic(path))
            continue
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    code="file_read_failed",
                    message=f"Unable to read metadata from {path}: {exc}",
                )
            )
            continue
        graph = _graph_with_public_user_params(graph, request, original_path)
        graph, alternate_file_diagnostics = _graph_with_public_alternate_file_reads(
            graph,
            request,
            condition_plans,
            format_base_path=original_path,
        )
        diagnostics.extend(alternate_file_diagnostics)
        if not _public_read_conditions_match(graph, condition_plans):
            condition_failed_count += 1
            continue
        for graph_diagnostic in _public_read_graph_diagnostics(graph):
            diagnostics.append(
                Diagnostic(
                    code="read_graph_diagnostic",
                    message=f"{path}: {graph_diagnostic}",
                )
            )
        plot_graph, plot_graph_diagnostics = _plot_public_output_graph_for_request(
            graph,
            request,
            path,
        )
        diagnostics.extend(plot_graph_diagnostics)
        plot_graphs.append(plot_graph)
        records.append(
            MetadataReadRecord(
                path=path,
                values={"SourceFile": path.as_posix()},
                rendered_text="",
                output_tags=(),
            )
        )

    if condition_failed_count and not any(
        _read_diagnostic_is_blocking(diagnostic) for diagnostic in diagnostics
    ):
        diagnostics.append(_files_failed_condition_diagnostic(condition_failed_count, request))

    if condition_failed_count and not plot_graphs:
        return MetadataReadResult(
            request=request,
            status=_metadata_read_status(
                tuple(records),
                diagnostics,
                condition_failed_count=condition_failed_count,
            ),
            diagnostics=tuple(diagnostics),
            records=tuple(records),
            rendered_text="",
            condition_failed_count=condition_failed_count,
        )

    if not plot_graphs and any(
        _read_diagnostic_is_blocking(diagnostic) for diagnostic in diagnostics
    ):
        return MetadataReadResult(
            request=request,
            status=_metadata_read_status(
                tuple(records),
                diagnostics,
                condition_failed_count=condition_failed_count,
            ),
            diagnostics=tuple(diagnostics),
            records=tuple(records),
            rendered_text="",
            condition_failed_count=condition_failed_count,
        )

    from exifmodern.public_interface.plot_svg import (
        render_svg_plot_for_graphs as _render_svg_plot_for_graphs,
    )

    plot_result = _render_svg_plot_for_graphs(
        tuple(plot_graphs),
        extract_embedded_level=request.render.extract_embedded_level,
        settings=request.render.plot_svg_settings,
    )
    diagnostics.extend(
        _plot_svg_diagnostic_to_public(diagnostic) for diagnostic in plot_result.diagnostics
    )
    if plot_result.svg:
        diagnostics.extend(_diagnostics_for_charset_read_options(request))
        diagnostics.extend(
            _diagnostics_for_deferred_inspection_read_options(
                request,
                extract_embedded_byte_range_exposed=plot_result.point_state.tag_extra_state.family_3_available,
                extract_embedded_recursive_traversal_required=False,
            )
        )
    rendered_text = plot_result.svg
    status = _metadata_read_status(
        tuple(records),
        diagnostics,
        condition_failed_count=condition_failed_count,
    )
    return MetadataReadResult(
        request=request,
        status=status,
        diagnostics=tuple(diagnostics),
        records=tuple(records),
        rendered_text=rendered_text,
        condition_failed_count=condition_failed_count,
    )


def _plot_public_output_graph_for_request(
    graph: ReadGraph,
    request: MetadataReadRequest,
    path: Path,
) -> tuple[ReadGraph, tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    output_group_family_diagnostic = _unsupported_public_output_group_families_diagnostic(
        path,
        request.render,
    )
    if output_group_family_diagnostic is not None:
        diagnostics.append(output_group_family_diagnostic)
    render_tags, wildcard_diagnostics = _expand_public_read_wildcards(
        graph,
        request.tags,
        path,
        request.render,
    )
    diagnostics.extend(wildcard_diagnostics)
    excluded_graph = _graph_with_public_read_exclusions(graph, request.tag_exclusions)
    render_tags = _render_tags_with_public_read_exclusions(
        graph,
        excluded_graph,
        render_tags,
        request.tag_exclusions,
        request.render,
    )
    render_tags = _render_tags_with_public_duplicate_instances(
        excluded_graph,
        render_tags,
        request.render,
        request.tags,
    )
    public_output_graph = _public_output_visible_graph(
        excluded_graph,
        include_unknown_tags=request.render.include_unknown_tags,
    )
    public_output_graph = _graph_with_public_binary_suppression(
        public_output_graph,
        request.render,
    )
    render_tags = _render_tags_with_public_output_suppression(
        excluded_graph,
        public_output_graph,
        render_tags,
        request.render,
    )
    render_graph = _graph_with_public_duplicate_instance_projection(
        public_output_graph,
        render_tags,
    )
    render_graph = _graph_with_public_output_group_projection(render_graph, request.render)
    selected_tags = _plot_selected_graph_tags(render_graph, render_tags, request.render)
    return replace(render_graph, tags=list(selected_tags)), tuple(diagnostics)


def _plot_selected_graph_tags(
    graph: ReadGraph,
    render_tags: tuple[str, ...],
    render: OutputRenderRequest,
) -> tuple[ReadTag, ...]:
    if not render_tags:
        return tuple(graph.tags)

    selected: list[ReadTag] = []
    options = RenderOptions(
        group_names=render.include_group_names,
        duplicate_tags=_public_render_extracts_duplicate_tags(render),
        include_unknown_tags=True,
    )
    for render_tag in render_tags:
        requested_tag = requested_tag_from_arg(_renderer_tag_arg(render_tag))
        if requested_tag is None:
            continue
        selected.extend(find_graph_tags(graph, requested_tag, options))
    return tuple(selected)


def _plot_svg_diagnostic_to_public(diagnostic: PlotSvgDiagnostic) -> Diagnostic:
    if diagnostic.severity == "warning":
        return Diagnostic(
            code="read_graph_diagnostic",
            message=diagnostic.message,
            details=diagnostic.details,
        )
    return Diagnostic(
        code=diagnostic.code,
        message=diagnostic.message,
        details=diagnostic.details,
    )


def _build_public_read_graph_for_request(
    path: Path,
    request: MetadataReadRequest,
) -> ReadGraph:
    token = _PUBLIC_READ_GRAPH_REQUEST.set(request)
    try:
        return _build_public_read_graph(path)
    finally:
        _PUBLIC_READ_GRAPH_REQUEST.reset(token)


def _build_public_read_graph(
    path: Path,
    request: MetadataReadRequest | None = None,
) -> ReadGraph:
    if request is None:
        request = _PUBLIC_READ_GRAPH_REQUEST.get()
    runtime_options = _read_graph_runtime_options_for_request(request)
    if _read_graph_runtime_options_need_jpeg_runtime(runtime_options) and _path_has_jpeg_soi(path):
        return build_read_graph(
            path,
            display_path=path.as_posix(),
            runtime_options=runtime_options,
        )
    return build_dispatched_read_graph(
        path,
        display_path=path.as_posix(),
        runtime_options=runtime_options,
    )


def _read_graph_runtime_options_for_request(
    request: MetadataReadRequest | None,
) -> ReadGraphRuntimeOptions:
    if request is None:
        return ReadGraphRuntimeOptions()
    request_all_level = request.render.request_all_level
    if request.render.output_file_routing.unsafe_binary_policy == "request_all_allows_unsafe":
        request_all_level = max(request_all_level, 3)
    unknown_tag_level = request.render.unknown_tag_level
    if not request.render.include_unknown_tags:
        unknown_tag_level = 0
    return ReadGraphRuntimeOptions(
        unknown_tag_level=unknown_tag_level,
        request_all_level=request_all_level,
        extract_embedded_level=request.render.extract_embedded_level,
        include_html_dump_state=request.render.format == "html_dump",
        include_dynamic_unknown_ifd_tags=request.render.include_unknown_tags,
    )


def _read_graph_runtime_options_need_jpeg_runtime(
    runtime_options: ReadGraphRuntimeOptions,
) -> bool:
    return (
        runtime_options.requests_process_binarydata_unknowns
        or runtime_options.requests_request_all_hidden_tags
        or runtime_options.extract_embedded_level > 0
    )


def _path_has_jpeg_soi(path: Path) -> bool:
    with path.open("rb") as file:
        return file.read(2) == b"\xff\xd8"


def _record_with_public_binary_output_policy(
    record: JsonRecord,
    graph: ReadGraph,
    request: MetadataReadRequest,
    path: Path,
) -> tuple[JsonRecord, tuple[Diagnostic, ...]]:
    if request.render.output_file_routing.unsafe_binary_policy == "request_all_allows_unsafe":
        return record, ()

    filtered: JsonRecord = {}
    diagnostics: list[Diagnostic] = []
    for key, value in record.items():
        if key == "SourceFile" or not isinstance(value, BinaryTagValue | BinaryTagListValue):
            filtered[key] = value
            continue
        tag = _read_tag_for_record_label(graph, key)
        reason = _public_binary_output_block_reason(tag, request)
        if reason is None:
            filtered[key] = value
            continue
        diagnostics.append(
            _unsafe_binary_output_blocked_diagnostic(
                path,
                key,
                tag,
                reason=reason,
            )
        )
    return filtered, tuple(diagnostics)


def _read_tag_for_record_label(graph: ReadGraph, label: str) -> ReadTag | None:
    tag_name = label.rsplit(":", 1)[-1]
    return next((tag for tag in graph.tags if tag.name == tag_name), None)


def _public_binary_output_block_reason(
    tag: ReadTag | None,
    request: MetadataReadRequest,
) -> str | None:
    if request.render.output_file_routing.unsafe_binary_policy == "suppress_binary_tags":
        return "binary_output_suppressed"
    if tag is not None and _is_public_unsafe_binary_output_tag(tag):
        return "unsafe_binary_payload"
    if tag is None or not _public_binary_tag_was_explicitly_selected(tag, request.tags):
        return "implicit_binary_fanout"
    return None


def _is_public_unsafe_binary_output_tag(tag: ReadTag) -> bool:
    if tag.name in _PUBLIC_SAFE_BINARY_TAG_NAMES:
        return False
    if tag.name in _PUBLIC_UNSAFE_BINARY_TAG_NAMES:
        return True
    lowered_name = tag.name.lower()
    if "hash" in lowered_name:
        return True
    if lowered_name.endswith("trailer"):
        return True
    if lowered_name.endswith("imagedata"):
        return True
    return bool(tag.provenance.group == "Trailer" or tag.provenance.family_0_group == "Trailer")


def _public_binary_tag_was_explicitly_selected(
    tag: ReadTag,
    requested_tags: tuple[str, ...],
) -> bool:
    for requested_tag in requested_tags:
        if "*" in requested_tag:
            continue
        selected_parts = requested_tag.removesuffix("#").split(":")
        if not selected_parts or selected_parts[-1].lower() != tag.name.lower():
            continue
        selected_groups = tuple(part.lower() for part in selected_parts[:-1] if part)
        if not selected_groups:
            return True
        tag_groups = {
            group.lower()
            for group in (
                tag.provenance.group,
                tag.provenance.family_0_group,
                tag.provenance.family_1_group,
                tag.provenance.family_2_group,
            )
            if group is not None
        }
        if all(group in tag_groups for group in selected_groups):
            return True
    return False


def _unsafe_binary_output_blocked_diagnostic(
    path: Path,
    label: str,
    tag: ReadTag | None,
    *,
    reason: str,
) -> Diagnostic:
    details: JsonObject = {
        "path": path.as_posix(),
        "label": label,
        "reason": reason,
        "unsafe_binary_policy": "explicit_tags_only",
        "evidence_ids": ["public.read.unsafe-binary-tags"],
    }
    if tag is not None:
        details["tag_name"] = tag.name
        details["group_name"] = tag.provenance.group
        details["table_name"] = tag.provenance.table_name
    return Diagnostic(
        code="unsafe_binary_output_blocked",
        message=(
            f"{path}: blocked binary output for {label} because the public binary "
            f"policy classified it as {reason}."
        ),
        details=details,
    )


def _unsupported_binary_list_item_fanout_diagnostic(
    path: Path,
    record: JsonRecord,
    routing: OutputPerTagFileRouting | None,
) -> Diagnostic | None:
    if routing is None:
        return None
    list_labels: JsonArray = [
        label
        for label, value in record.items()
        if label != "SourceFile" and isinstance(value, list)
    ]
    if not list_labels:
        return None
    return Diagnostic(
        code="unsupported_public_binary_list_item_fanout",
        message=(
            f"{path}: public -b -W output selected list values, but the read graph "
            "does not expose source-backed binary item payload records with per-item "
            "boundaries."
        ),
        details={
            "source_path": path.as_posix(),
            "format_template": routing.format_template,
            "overwrite_policy": routing.overwrite_policy,
            "list_labels": list_labels,
            "route_blocker": "read_graph_binary_list_item_boundaries",
            "evidence_ids": [
                "public.read.binary-list-retention",
                "public.output.binary-list-routing",
                "public.output.binary-list-docs",
            ],
        },
    )


def _graph_with_public_user_params(
    graph: ReadGraph,
    request: MetadataReadRequest,
    original_path: Path,
) -> ReadGraph:
    params = _public_user_params_for_path(request, original_path)
    available_params = tuple(param for param in params if param.value is not None)
    if not available_params:
        return graph
    user_param_tags = [
        ReadTag(
            name=_public_user_param_tag_name(param),
            value=param.value,
            provenance=TagProvenance(
                group="UserParam",
                table_name="Image::ExifTool::UserParam",
                tag_id=param.name,
                source=graph.source_file,
                family_0_group="UserParam",
                family_1_group="UserParam",
                family_2_group="Other",
            ),
            schema=None,
        )
        for param in available_params
    ]
    return replace(graph, tags=[*graph.tags, *user_param_tags])


def _public_user_params_for_path(
    request: MetadataReadRequest,
    original_path: Path,
) -> tuple[PublicUserParam, ...]:
    if not request.source_files:
        return request.user_params
    return (*request.user_params, *original_file_user_params(original_path))


def _public_user_param_tag_name(param: PublicUserParam) -> str:
    return param.name.removesuffix("#")


def _graph_with_public_alternate_file_reads(
    graph: ReadGraph,
    request: MetadataReadRequest,
    condition_plans: tuple[PublicReadConditionPlan, ...] = (),
    *,
    format_base_path: Path | None = None,
) -> tuple[ReadGraph, tuple[Diagnostic, ...]]:
    requested_slots = _public_requested_alternate_file_slots(
        _public_read_execution_control_tags(request, condition_plans)
    )
    if not requested_slots:
        return graph, ()
    alternate_files = {
        alternate.slot: alternate
        for alternate in request.alternate_files
        if alternate.slot in requested_slots
    }
    alternate_tags: list[ReadTag] = []
    diagnostics: list[Diagnostic] = []
    base_path = format_base_path if format_base_path is not None else Path(graph.source_file)
    for slot in sorted(requested_slots):
        alternate = alternate_files[slot]
        tag_values = _public_insert_tag_values_for_graph(alternate.path.as_posix(), graph)
        unresolved_tokens = _public_insert_tag_unresolved_tokens_for_graph(
            alternate.path.as_posix(),
            _public_user_params_for_path(request, base_path),
            graph,
        )
        if unresolved_tokens:
            diagnostics.append(
                _public_alternate_file_tag_interpolation_diagnostic(slot, unresolved_tokens)
            )
            continue
        if _public_alternate_files.alternate_file_format_support(
            alternate.path.as_posix()
        ).tag_interpolation and not _public_source_file_tag_format_is_bounded(
            alternate.path.as_posix()
        ):
            diagnostics.append(
                _public_alternate_file_tag_interpolation_unbounded_diagnostic(
                    slot,
                    alternate.path,
                )
            )
            continue
        alternate_path = _public_alternate_files.resolve_alternate_file_path(
            alternate.path,
            base_path,
            _public_user_params_for_path(request, base_path),
            tag_values,
        )
        if tag_values:
            path_bound_diagnostic = _public_alternate_file_tag_path_bound_diagnostic(
                slot,
                alternate.path,
                alternate_path,
                base_path,
            )
            if path_bound_diagnostic is not None:
                diagnostics.append(path_bound_diagnostic)
                continue
        bound_diagnostic = _public_media_read_bound_diagnostic(alternate_path)
        if bound_diagnostic is not None:
            diagnostics.append(bound_diagnostic)
            continue
        try:
            alternate_graph = _build_public_read_graph_for_request(
                alternate_path,
                request,
            )
        except FileNotFoundError:
            diagnostics.append(_file_not_found_diagnostic(alternate_path))
            continue
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    code="file_read_failed",
                    message=f"Unable to read metadata from {alternate_path}: {exc}",
                )
            )
            continue
        alternate_tags.extend(
            _public_alternate_file_projected_tags(
                alternate_graph,
                slot,
            )
        )
        for graph_diagnostic in _public_read_graph_diagnostics(alternate_graph):
            diagnostics.append(
                Diagnostic(
                    code="read_graph_diagnostic",
                    message=f"{alternate_path}: {graph_diagnostic}",
                )
            )
    if not alternate_tags:
        return graph, tuple(diagnostics)
    return replace(graph, tags=[*graph.tags, *alternate_tags]), tuple(diagnostics)


def _public_alternate_file_projected_tags(
    alternate_graph: ReadGraph,
    slot: PublicReadAlternateFileSlot,
) -> tuple[ReadTag, ...]:
    group = f"File{slot}"
    return tuple(
        replace(
            tag,
            provenance=replace(
                tag.provenance,
                group=group,
                family_0_group=group,
                family_1_group=group,
                family_2_group=group,
                source=alternate_graph.source_file,
            ),
        )
        for tag in alternate_graph.tags
    )


def _public_insert_tag_values_for_graph(
    raw_path: str,
    graph: ReadGraph,
) -> tuple[PublicInsertTagValue, ...]:
    values: list[PublicInsertTagValue] = []
    for token in _public_alternate_files.public_insert_tag_value_tokens(raw_path):
        value = _public_read_condition_tag_value(graph, token)
        text = _public_insert_tag_scalar_text(value)
        if text is not None:
            values.append(PublicInsertTagValue(token=token, value=text))
    return tuple(values)


def _public_insert_tag_scalar_text(value: TagValue) -> str | None:
    if value is None or isinstance(value, BinaryTagValue | BinaryTagListValue | list):
        return None
    return str(value)


def _public_insert_tag_unresolved_tokens_for_graph(
    raw_path: str,
    user_params: tuple[PublicUserParam, ...],
    graph: ReadGraph,
) -> tuple[_PublicInsertTagUnresolvedToken, ...]:
    unresolved: list[_PublicInsertTagUnresolvedToken] = []
    for token in _public_alternate_files.public_insert_tag_value_tokens(raw_path):
        if public_user_param_value(user_params, token) is not None:
            continue
        value = _public_read_condition_tag_value(graph, token)
        if value is None:
            unresolved.append(_PublicInsertTagUnresolvedToken(token, "missing"))
            continue
        if _public_insert_tag_scalar_text(value) is None:
            unresolved.append(_PublicInsertTagUnresolvedToken(token, "non_scalar"))
    return tuple(unresolved)


def _public_alternate_file_tag_interpolation_diagnostic(
    slot: PublicReadAlternateFileSlot,
    tokens: tuple[_PublicInsertTagUnresolvedToken, ...],
) -> Diagnostic:
    token_values: JsonArray = []
    reason_values: JsonObject = {}
    for token in tokens:
        token_values.append(token.token)
        reason_values[token.token] = token.reason
    return Diagnostic(
        code="public_alternate_file_read_deferred",
        message=(
            "ExifTool -fileNUM alternate-file path interpolation is recognized, "
            "but this request uses tag values that are not available as bounded "
            f"scalar public read-graph values for File{slot}."
        ),
        details={
            "unsupported_semantics": "alternate_file_tag_interpolation_unresolved",
            "slot": slot,
            "tokens": token_values,
            "token_reasons": reason_values,
            "supported_scope": (
                "bounded public -fileNUM $TAG interpolation executes when the "
                "referenced main-file tag is available as a scalar public read-graph "
                "value before alternate-file extraction"
            ),
            "evidence_ids": [
                "public.read.alternate-file.setup",
                "public.read.altfile-interpolation",
            ],
        },
    )


def _public_alternate_file_tag_interpolation_unbounded_diagnostic(
    slot: PublicReadAlternateFileSlot,
    raw_path: Path,
) -> Diagnostic:
    return Diagnostic(
        code="public_alternate_file_read_deferred",
        message=(
            "ExifTool -fileNUM alternate-file path interpolation is recognized, "
            "but this tag-interpolated format is outside the bounded local public "
            "execution slice."
        ),
        details={
            "unsupported_semantics": "alternate_file_tag_interpolation_unanchored",
            "slot": slot,
            "format": raw_path.as_posix(),
            "supported_scope": (
                "bounded public -fileNUM $TAG interpolation executes only for "
                "formats anchored to the original file directory with %d or "
                "$Directory and resolved from scalar main-file public read-graph "
                "values"
            ),
            "evidence_ids": ["public.read.altfile-interpolation"],
        },
    )


def _public_alternate_file_tag_path_bound_diagnostic(
    slot: PublicReadAlternateFileSlot,
    raw_path: Path,
    resolved_path: Path,
    original_path: Path,
) -> Diagnostic | None:
    if _public_source_file_tag_path_is_bounded(resolved_path, original_path):
        return None
    return Diagnostic(
        code="public_alternate_file_read_deferred",
        message=(
            "ExifTool -fileNUM alternate-file path interpolation resolved outside "
            "the bounded local public execution scope."
        ),
        details={
            "unsupported_semantics": "alternate_file_tag_interpolation_unsafe_path",
            "slot": slot,
            "format": raw_path.as_posix(),
            "resolved_path": resolved_path.as_posix(),
            "original_path": original_path.as_posix(),
            "supported_scope": (
                "scalar $TAG interpolation for -fileNUM may resolve only to local "
                "paths under the original file directory and must not include parent "
                "directory traversal"
            ),
            "evidence_ids": ["public.read.altfile-interpolation"],
        },
    )


def _public_media_read_bound_diagnostic(path: Path) -> Diagnostic | None:
    try:
        file_size = path.stat().st_size
    except OSError:
        return None
    if file_size <= _PUBLIC_MEDIA_READ_FULL_READ_LIMIT_BYTES:
        return None
    try:
        prefix = _read_public_file_prefix(path, _PUBLIC_INSPECT_PREFIX_BYTES)
    except OSError:
        return None
    if prefix.startswith(RIFF_SIGNATURES):
        family = "RIFF/WebP"
        evidence = ["public.read.media-riff-bound"]
    elif prefix.startswith(b"\x1a\x45\xdf\xa3"):
        family = "Matroska/EBML"
        evidence = ["public.read.media-matroska-bound"]
    else:
        return None
    return Diagnostic(
        code="large_media_public_read_deferred",
        message=(
            f"{path}: public {family} metadata reads are bounded to files up to "
            f"{_PUBLIC_MEDIA_READ_FULL_READ_LIMIT_BYTES} bytes until streaming "
            "metadata-only traversal is connected."
        ),
        details={
            "path": path.as_posix(),
            "file_size": file_size,
            "limit_bytes": _PUBLIC_MEDIA_READ_FULL_READ_LIMIT_BYTES,
            "family": family,
            "evidence_ids": list(evidence),
        },
    )


_PUBLIC_TRANSLITERATION_FILTER_RE = re.compile(r"\Atr/(?P<from>[^/]*)/(?P<to>[^/]*)/\Z")


def _public_output_filter_diagnostic(path: Path, render: OutputRenderRequest) -> Diagnostic | None:
    if render.output_filter is None:
        return None
    from exifmodern.safe_expression.facade import compile_safe_filter_expression

    if compile_safe_filter_expression(render.output_filter) is not None:
        return None
    return Diagnostic(
        code="public_output_filter_not_connected",
        message=(
            f"{path}: public output Filter must compile to the safe-expression VM; "
            "host Perl execution remains deferred."
        ),
        details={
            "filter": render.output_filter,
            "evidence_ids": [
                (
                    "../exiftool/lib/Image/ExifTool.pm lines 1139-1140 define Filter "
                    "as an output filter."
                ),
                (
                    "../exiftool/lib/Image/ExifTool.pm lines 6497-6523 apply the "
                    "filter to scalar, array, and hash values."
                ),
                "../exiftool/t/ExifTool.t lines 313-320 tests Filter with tr/ /_/;tr/0-9/#/.",
            ],
        },
    )


def _record_with_public_output_filter(
    record: JsonRecord,
    render: OutputRenderRequest,
) -> JsonRecord:
    if render.output_filter is None:
        return record
    from exifmodern.safe_expression.facade import compile_safe_filter_expression

    program = compile_safe_filter_expression(render.output_filter)
    if program is None:
        return record
    return {
        key: (
            value if key == "SourceFile" else _json_value_with_public_output_filter(value, program)
        )
        for key, value in record.items()
    }


def _xml_elements_with_public_output_filter(
    elements: tuple[XmlTagElement, ...],
    render: OutputRenderRequest,
) -> tuple[XmlTagElement, ...]:
    if render.output_filter is None:
        return elements
    from exifmodern.safe_expression.facade import compile_safe_filter_expression

    program = compile_safe_filter_expression(render.output_filter)
    if program is None:
        return elements
    return tuple(_xml_element_with_public_output_filter(element, program) for element in elements)


def _xml_element_with_public_output_filter(
    element: XmlTagElement,
    program: SafeExpressionProgram,
) -> XmlTagElement:
    return replace(
        element,
        value=_tag_value_with_public_output_filter(element.value, program),
        struct_fields=tuple(
            replace(field, value=_tag_value_with_public_output_filter(field.value, program))
            for field in element.struct_fields
        ),
    )


def _tag_value_with_public_output_filter(
    value: TagValue,
    program: SafeExpressionProgram,
) -> TagValue:
    if isinstance(value, str):
        return _string_with_public_output_filter(value, program)
    if isinstance(value, bool):
        return _string_with_public_output_filter(str(value), program)
    if isinstance(value, int | float):
        return _string_with_public_output_filter(str(value), program)
    if isinstance(value, list):
        filtered: list[str | int | float | bool | None] = [
            _string_with_public_output_filter(str(item), program) if item is not None else None
            for item in value
        ]
        return filtered
    return value


def _json_value_with_public_output_filter(
    value: TagValue,
    program: SafeExpressionProgram,
) -> TagValue:
    if isinstance(value, str):
        return _string_with_public_output_filter(value, program)
    if isinstance(value, bool):
        return _string_with_public_output_filter(str(value), program)
    if isinstance(value, int | float):
        return _string_with_public_output_filter(str(value), program)
    if isinstance(value, list):
        filtered: list[str | int | float | bool | None] = [
            _string_with_public_output_filter(str(item), program) if item is not None else None
            for item in value
        ]
        return filtered
    return value


def _string_with_public_output_filter(value: str, program: SafeExpressionProgram) -> str:
    from exifmodern.safe_expression.vm import evaluate_program

    result = evaluate_program(program, {"$val": value})
    return "" if result is None else str(result)


def _public_output_filter_operations(
    filter_expression: str | None,
) -> tuple[tuple[str, str], ...] | None:
    if filter_expression is None:
        return ()
    operations: list[tuple[str, str]] = []
    for raw_operation in filter_expression.split(";"):
        operation = raw_operation.strip()
        if not operation:
            continue
        match = _PUBLIC_TRANSLITERATION_FILTER_RE.fullmatch(operation)
        if match is None:
            return None
        source_chars = _expanded_public_filter_chars(match.group("from"))
        replacement_chars = _expanded_public_filter_chars(match.group("to"))
        if not source_chars or not replacement_chars:
            return None
        operations.append((source_chars, replacement_chars))
    return tuple(operations)


def _expanded_public_filter_chars(value: str) -> str:
    expanded: list[str] = []
    index = 0
    while index < len(value):
        if index + 2 < len(value) and value[index + 1] == "-":
            start = ord(value[index])
            end = ord(value[index + 2])
            if start <= end:
                expanded.extend(chr(codepoint) for codepoint in range(start, end + 1))
                index += 3
                continue
        expanded.append(value[index])
        index += 1
    return "".join(expanded)


def _public_translation_table(source_chars: str, replacement_chars: str) -> dict[int, str]:
    table: dict[int, str] = {}
    last_replacement = replacement_chars[-1]
    for index, source_char in enumerate(source_chars):
        replacement = (
            replacement_chars[index] if index < len(replacement_chars) else last_replacement
        )
        table[ord(source_char)] = replacement
    return table


def _public_read_graph_diagnostics(graph: ReadGraph) -> tuple[str, ...]:
    return tuple(
        diagnostic
        for diagnostic in graph.diagnostics
        if not _is_public_matroska_informational_diagnostic(diagnostic)
    )


def _public_extract_embedded_byte_range_tag_names(graph: ReadGraph) -> tuple[str, ...]:
    tag_names: list[str] = []
    for tag in graph.tags:
        if not _public_embedded.public_embedded_byte_range_source_is_safe(
            tag.name,
            tag.provenance.source,
        ):
            continue
        if isinstance(tag.value, BinaryTagValue):
            tag_names.append(tag.name)
    return tuple(tag_names)


def _public_extract_embedded_bounded_timed_record_tag_names(
    graph: ReadGraph,
) -> tuple[str, ...]:
    return tuple(
        tag.name
        for tag in graph.tags
        if _public_embedded.public_embedded_bounded_timed_record_source_is_safe(
            tag.provenance.source
        )
    )


def _graph_has_public_extract_embedded_byte_range(graph: ReadGraph) -> bool:
    return bool(_public_extract_embedded_byte_range_tag_names(graph))


def _is_public_matroska_informational_diagnostic(diagnostic: str) -> bool:
    return diagnostic.startswith(
        (
            "Matroska traversal is bounded to source-defined EBML header",
            "Matroska 0x23a2 binary track payload is source-defined",
            "Element 0x8538067 extends beyond its parent payload.",
            "A writable Matroska metadata transaction requires a Segment element.",
        )
    )


def _read_metadata_binary(
    request: MetadataReadRequest,
    condition_plans: tuple[PublicReadConditionPlan, ...],
) -> MetadataReadResult:
    records: list[MetadataReadRecord] = []
    diagnostics: list[Diagnostic] = []
    rendered_parts: list[bytes] = []
    condition_failed_count = 0
    for path in _expanded_read_paths(request):
        bound_diagnostic = _public_media_read_bound_diagnostic(path)
        if bound_diagnostic is not None:
            diagnostics.append(bound_diagnostic)
            continue
        try:
            graph = _build_public_read_graph_for_request(path, request)
        except FileNotFoundError:
            diagnostics.append(_file_not_found_diagnostic(path))
            continue
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    code="file_read_failed",
                    message=f"Unable to read metadata from {path}: {exc}",
                )
            )
            continue
        if not _public_read_conditions_match(graph, condition_plans):
            condition_failed_count += 1
            continue
        render_tags, wildcard_diagnostics = _expand_public_read_wildcards(
            graph,
            request.tags,
            path,
            request.render,
        )
        diagnostics.extend(wildcard_diagnostics)
        excluded_graph = _graph_with_public_read_exclusions(graph, request.tag_exclusions)
        render_tags = _render_tags_with_public_read_exclusions(
            graph,
            excluded_graph,
            render_tags,
            request.tag_exclusions,
            request.render,
        )
        render_tags = _render_tags_with_public_duplicate_instances(
            excluded_graph,
            render_tags,
            request.render,
        )
        public_output_graph = _public_output_visible_graph(
            excluded_graph,
            include_unknown_tags=request.render.include_unknown_tags,
        )
        render_tags = _render_tags_with_public_output_suppression(
            excluded_graph,
            public_output_graph,
            render_tags,
            request.render,
        )
        if request.tags and not render_tags:
            continue
        render_graph = _graph_with_public_duplicate_instance_projection(
            public_output_graph, render_tags
        )
        render_graph = _graph_with_public_output_group_projection(render_graph, request.render)
        record, issues = graph_record_for_request(
            render_graph,
            path.as_posix(),
            _renderer_args_for_read_request(request, tags=render_tags),
        )
        if issues:
            diagnostics.append(
                Diagnostic(
                    code="requested_tag_not_rendered",
                    message=f"{path}: {format_render_issues(issues)}",
                )
            )
        for graph_diagnostic in _public_read_graph_diagnostics(graph):
            diagnostics.append(
                Diagnostic(
                    code="read_graph_diagnostic",
                    message=f"{path}: {graph_diagnostic}",
                )
            )
        record, binary_policy_diagnostics = _record_with_public_binary_output_policy(
            record,
            render_graph,
            request,
            path,
        )
        diagnostics.extend(binary_policy_diagnostics)
        binary_values = [
            value.data
            for key, value in record.items()
            if key != "SourceFile" and isinstance(value, BinaryTagValue)
        ]
        for key, value in record.items():
            if key == "SourceFile" or not isinstance(value, BinaryTagListValue):
                continue
            binary_values.extend(item.data for item in value.items)
        if not binary_values and _output_file_routing_is_executable_per_tag_binary_read(
            request.render
        ):
            binary_list_item_diagnostic = _unsupported_binary_list_item_fanout_diagnostic(
                path,
                record,
                request.render.output_file_routing.per_tag_file,
            )
            if binary_list_item_diagnostic is not None:
                diagnostics.append(binary_list_item_diagnostic)
        if not binary_values:
            continue
        rendered_binary = b"".join(binary_values)
        if len(rendered_binary) > MAX_PUBLIC_BINARY_OUTPUT_BYTES:
            diagnostics.append(
                Diagnostic(
                    code="binary_output_exceeds_public_bound",
                    message=(
                        f"{path}: binary output is {len(rendered_binary)} bytes, "
                        f"above the public API bound of {MAX_PUBLIC_BINARY_OUTPUT_BYTES} bytes."
                    ),
                    details={
                        "byte_count": len(rendered_binary),
                        "max_public_binary_output_bytes": MAX_PUBLIC_BINARY_OUTPUT_BYTES,
                    },
                )
            )
            continue
        records.append(
            MetadataReadRecord(
                path=path,
                values=record,
                rendered_text="",
                rendered_binary=rendered_binary,
                output_tags=_output_rendered_tags_for_record(
                    render_graph,
                    record,
                    include_binary=True,
                ),
            )
        )
        rendered_parts.append(rendered_binary)
    if condition_failed_count and not any(
        _read_diagnostic_is_blocking(diagnostic) for diagnostic in diagnostics
    ):
        diagnostics.append(_files_failed_condition_diagnostic(condition_failed_count, request))

    if not records:
        if condition_failed_count:
            return MetadataReadResult(
                request=request,
                status=_metadata_read_status(
                    tuple(records),
                    diagnostics,
                    condition_failed_count=condition_failed_count,
                ),
                diagnostics=tuple(diagnostics),
                condition_failed_count=condition_failed_count,
            )
        diagnostics.insert(0, binary_output_not_connected_diagnostic(request))
        return MetadataReadResult(
            request=request,
            status="unsupported",
            diagnostics=tuple(diagnostics),
            condition_failed_count=condition_failed_count,
        )
    output_files, output_file_diagnostics = _execute_read_output_file_routing(
        records,
        request.render,
    )
    diagnostics.extend(output_file_diagnostics)
    routed_binary_to_files = _output_file_routing_is_executable_per_tag_binary_read(request.render)
    return MetadataReadResult(
        request=request,
        status=_metadata_read_status(
            tuple(records),
            diagnostics,
            condition_failed_count=condition_failed_count,
        ),
        diagnostics=tuple(diagnostics),
        records=tuple(records),
        rendered_binary=b"" if routed_binary_to_files else b"".join(rendered_parts),
        output_files=output_files,
        condition_failed_count=condition_failed_count,
    )


def _binary_output_uses_record_renderer(render: OutputRenderRequest) -> bool:
    # Source: ../exiftool/exiftool lines 1542-1556, 1643-1661 and 5677-5690
    # keep -b inside CSV/XML/JSON/PHP renderers instead of switching to pure
    # binary stdout.
    return render.format in {"csv", "json", "php", "xml"}


def _metadata_read_status(
    records: tuple[MetadataReadRecord, ...],
    diagnostics: Sequence[Diagnostic],
    *,
    condition_failed_count: int = 0,
) -> PublicOperationStatus:
    if any(_read_diagnostic_is_blocking(diagnostic) for diagnostic in diagnostics):
        return "unsupported"
    if records:
        return "ok"
    if condition_failed_count:
        return "condition_failed"
    return "unsupported" if diagnostics else "ok"


def _diagnostics_for_deferred_inspection_read_options(
    request: MetadataReadRequest,
    *,
    extract_embedded_byte_range_exposed: bool,
    extract_embedded_recursive_traversal_required: bool,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    if request.render.verbose_level and request.render.format != "html_dump":
        diagnostics.append(
            Diagnostic(
                code="verbose_diagnostic_dump_not_connected",
                message=(
                    "ExifTool-style -v verbose structure dumps are recognized, but "
                    "public read execution does not expose low-level verbose dumps yet."
                ),
                details={
                    "verbose_level": request.render.verbose_level,
                    "evidence_ids": ["public.read.verbose-output"],
                },
            )
        )
    if (
        request.render.extract_embedded_level
        and not extract_embedded_byte_range_exposed
        and not _public_embedded.public_extract_embedded_requires_recursive_traversal(
            request.render.extract_embedded_level
        )
    ):
        diagnostics.append(
            Diagnostic(
                code="extract_embedded_not_connected",
                message=(
                    "ExifTool-style -ee embedded extraction is recognized, but public "
                    "read execution has no source-backed embedded byte range for this "
                    "input yet."
                ),
                details={
                    "extract_embedded_level": request.render.extract_embedded_level,
                    "bounded_public_byte_range_tags": list(
                        _public_embedded.PUBLIC_EXTRACT_EMBEDDED_BYTE_RANGE_TAGS
                    ),
                    "evidence_ids": ["public.read.embedded-extraction"],
                },
            )
        )
    if _public_embedded.public_extract_embedded_requires_recursive_traversal(
        request.render.extract_embedded_level
    ) and (
        not extract_embedded_byte_range_exposed or extract_embedded_recursive_traversal_required
    ):
        diagnostics.append(
            Diagnostic(
                code="embedded_document_recursive_traversal_deferred",
                message=(
                    "ExifTool-style numeric -ee levels above 1 require recursive "
                    "embedded document or video stream traversal. Public read output "
                    "currently exposes only source-backed read-graph byte ranges."
                ),
                details={
                    "extract_embedded_level": request.render.extract_embedded_level,
                    "bounded_public_byte_range_tags": list(
                        _public_embedded.PUBLIC_EXTRACT_EMBEDDED_BYTE_RANGE_TAGS
                    ),
                    "evidence_ids": list(
                        _public_embedded.PUBLIC_EXTRACT_EMBEDDED_RECURSIVE_EVIDENCE_IDS
                    ),
                },
            )
        )
    if request.render.scan_for_xmp:
        diagnostics.append(
            Diagnostic(
                code="scan_for_xmp_not_connected",
                message=(
                    "ExifTool-style -scanForXMP is recognized, but public read execution "
                    "does not brute-force scan file bodies for XMP packets."
                ),
                details={
                    "evidence_ids": ["public.read.scan-for-xmp"],
                },
            )
        )
    return tuple(diagnostics)


def _diagnostics_for_charset_read_options(
    request: MetadataReadRequest,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for option in request.render.internal_charset_options:
        diagnostics.append(
            Diagnostic(
                code="internal_charset_option_recognized",
                message=(
                    f"ExifTool -charset {option.target}={option.charset} was recognized; "
                    "the current public read graph applies output charset effects only."
                ),
                details={
                    "target": option.target,
                    "charset": option.charset,
                    "raw_option": option.raw_option,
                    "blocking": False,
                    "evidence_ids": ["public.read.charset-options"],
                },
            )
        )
    return tuple(diagnostics)


def _html_dump_limit_for_request(request: MetadataReadRequest) -> int:
    # Source: ../exiftool/lib/Image/ExifTool/HtmlDump.pm lines 327-334 cap
    # dumped bytes by HtmlDump verbose level.
    if request.render.verbose_level <= 1:
        return 1024
    if request.render.verbose_level <= 2:
        return 16_384
    return 256 * 1024 * 1024


def _html_dump_byte_range_state_unavailable_diagnostic(
    path: Path,
    graph: ReadGraph,
) -> Diagnostic:
    byte_range_count = 0
    dump_block_count = 0
    span_annotation_count = 0
    if graph.html_dump_state is not None:
        byte_range_count = len(graph.html_dump_state.byte_ranges)
        dump_block_count = len(graph.html_dump_state.dump_blocks)
        span_annotation_count = len(graph.html_dump_state.span_annotations)
    return Diagnostic(
        code="html_dump_byte_range_state_unavailable",
        message=(
            f"{path}: ExifTool -htmlDump requires low-level HTML_DUMP byte ranges; "
            "this read graph does not expose renderable byte-range state."
        ),
        details={
            "path": path.as_posix(),
            "source_file": graph.source_file,
            "tag_count": len(graph.tags),
            "graph_diagnostics": list(graph.diagnostics),
            "html_dump_state_available": graph.html_dump_state is not None,
            "html_dump_byte_range_count": byte_range_count,
            "html_dump_dump_block_count": dump_block_count,
            "html_dump_span_annotation_count": span_annotation_count,
            "evidence_ids": [
                (
                    "../exiftool/exiftool lines 1118-1122 parse -htmlDump, "
                    "increase verbose output, and set HtmlDumpBase."
                ),
                (
                    "../exiftool/lib/Image/ExifTool.pm lines 4367-4369 creates "
                    "Image::ExifTool::HtmlDump state during extraction."
                ),
                (
                    "../exiftool/lib/Image/ExifTool.pm lines 6948-6972 route "
                    "HTML_DUMP byte ranges through HDump/Add."
                ),
                (
                    "../exiftool/lib/Image/ExifTool/HtmlDump.pm lines 306-315 "
                    "render from collected byte-range blocks into an HTML document."
                ),
            ],
        },
    )


def _plot_renderer_state_unavailable_diagnostic(request: MetadataReadRequest) -> Diagnostic:
    from exifmodern.provenance.public_interface import PLOT_SOURCES as _PLOT_SOURCES
    from exifmodern.public_interface.plot_svg import (
        plot_renderer_contract_to_json_value as _plot_renderer_contract_to_json_value,
    )

    return Diagnostic(
        code="plot_renderer_state_unavailable",
        message=(
            "ExifTool -plot requires TAG_EXTRA family-3 document metadata and "
            "Image::ExifTool::Plot accumulated point state; the public read graph "
            "currently exposes tag values and family 0/1/2/4 provenance, but not "
            "the source-backed family-3 document numbers required for exact SVG output."
        ),
        details={
            "paths": [path.as_posix() for path in request.paths],
            "requested_tags": list(request.tags),
            "evidence_ids": list(_PLOT_SOURCES),
            "current_graph_diagnostics": _plot_current_graph_diagnostics(request),
            "renderer_contract": _plot_renderer_contract_to_json_value(),
        },
    )


def _plot_current_graph_diagnostics(request: MetadataReadRequest) -> JsonArray:
    diagnostics: JsonArray = []
    for original_path in _expanded_read_paths(request):
        path, source_file_diagnostics = _public_read_source_file_path(original_path, request)
        if source_file_diagnostics:
            diagnostics.append(
                {
                    "path": path.as_posix(),
                    "status": "source_file_deferred",
                    "diagnostics": [diagnostic.code for diagnostic in source_file_diagnostics],
                }
            )
            continue
        try:
            graph = _build_public_read_graph_for_request(path, request)
        except FileNotFoundError:
            diagnostics.append(
                {
                    "path": path.as_posix(),
                    "status": "file_not_found",
                }
            )
            continue
        except OSError as exc:
            diagnostics.append(
                {
                    "path": path.as_posix(),
                    "status": "file_read_failed",
                    "message": str(exc),
                }
            )
            continue
        numeric_candidates: JsonArray = []
        for tag in graph.tags:
            point_count = _plot_numeric_point_count(tag.value)
            if point_count <= 0:
                continue
            if request.tags and not _plot_requested_tag_matches(tag.name, request.tags):
                continue
            numeric_candidates.append(
                {
                    "name": tag.name,
                    "group": tag.provenance.group,
                    "point_count": point_count,
                }
            )
        diagnostics.append(
            {
                "path": path.as_posix(),
                "status": "read_graph_available",
                "tag_count": len(graph.tags),
                "numeric_candidate_tags": numeric_candidates[:20],
                "numeric_candidate_tag_count": len(numeric_candidates),
                "provenance_fields_available": [
                    "group",
                    "source_table",
                    "table_name",
                    "tag_id",
                    "family_0_group",
                    "family_1_group",
                    "family_2_group",
                    "family_4_instance_group",
                    "duplicate_instance_ordinal",
                ],
                "tag_extra_family_3_available": False,
                "missing_provenance_fields": ["family_3_group"],
                "graph_diagnostics": list(graph.diagnostics),
            }
        )
    return diagnostics


def _plot_requested_tag_matches(tag_name: str, requested_tags: tuple[str, ...]) -> bool:
    for requested_tag in requested_tags:
        normalized = requested_tag.removeprefix("-")
        requested_name = normalized.rsplit(":", 1)[-1].removesuffix("#")
        if requested_name.lower() == tag_name.lower():
            return True
    return False


def _plot_numeric_point_count(value: TagValue) -> int:
    if isinstance(value, BinaryTagValue):
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return 1
    if isinstance(value, list):
        return sum(1 for item in value if _plot_scalar_is_numeric(item))
    if isinstance(value, str):
        return 1 if _plot_scalar_text_is_numeric(value) else 0
    return 0


def _plot_scalar_is_numeric(value: ScalarTagValue) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    if isinstance(value, str):
        return _plot_scalar_text_is_numeric(value)
    return False


def _plot_scalar_text_is_numeric(value: str) -> bool:
    return (
        re.fullmatch(r"[+-]?(?=\.?\d)\d*\.?\d*(?:e[+-]?\d+)?", value.strip(), re.IGNORECASE)
        is not None
    )


def _html_dump_renderer_deferred_diagnostic(request: MetadataReadRequest) -> Diagnostic:
    graph_diagnostics = _html_dump_current_graph_diagnostics(request)
    currently_available_state: JsonArray = [
        "public read graph tags",
        "tag provenance labels",
        "normalized tag values",
    ]
    if _html_dump_graph_state_available(graph_diagnostics):
        currently_available_state.extend(
            [
                "HtmlDumpBase byte offset",
                "per-segment byte ranges",
                "low-level EXIF/TIFF/JPEG dump blocks",
                "HTML_DUMP span/class tooltip annotations",
            ]
        )
    required_state: JsonArray = [
        "HtmlDumpBase byte offset",
        "per-segment byte ranges",
        "low-level EXIF/TIFF/JPEG dump blocks",
        "HTML_DUMP span/class tooltip annotations",
    ]
    renderer_contract: JsonObject = {
        "required_state": required_state,
        "currently_available_state": currently_available_state,
        "missing_state": [
            state for state in required_state if state not in currently_available_state
        ],
    }
    return Diagnostic(
        code="html_dump_renderer_deferred",
        message=(
            "ExifTool -htmlDump read-graph byte-range state is available for bounded "
            "JPEG/EXIF inputs, but final HtmlDump.pm HTML document rendering is not "
            "connected yet."
        ),
        details={
            "paths": [path.as_posix() for path in request.paths],
            "evidence_ids": [
                (
                    "../exiftool/exiftool lines 1118-1122 parse -htmlDump, "
                    "increase verbose output, and set HtmlDumpBase."
                ),
                (
                    "../exiftool/exiftool documentation lines 5948-5958 describes "
                    "-htmlDump as a dynamic hex dump currently backed by EXIF/TIFF "
                    "and JPEG internals."
                ),
                (
                    "../exiftool/lib/Image/ExifTool.pm lines 4367-4369 creates "
                    "Image::ExifTool::HtmlDump state during extraction."
                ),
            ],
            "current_graph_diagnostics": graph_diagnostics,
            "renderer_contract": renderer_contract,
            "missing_renderer_state": renderer_contract["missing_state"],
        },
    )


def _html_dump_current_graph_diagnostics(request: MetadataReadRequest) -> JsonArray:
    diagnostics: JsonArray = []
    for original_path in _expanded_read_paths(request):
        path, source_file_diagnostics = _public_read_source_file_path(original_path, request)
        if source_file_diagnostics:
            diagnostics.append(
                {
                    "path": path.as_posix(),
                    "status": "source_file_deferred",
                    "diagnostics": [diagnostic.code for diagnostic in source_file_diagnostics],
                }
            )
            continue
        try:
            graph = _build_public_read_graph_for_request(path, request)
        except FileNotFoundError:
            diagnostics.append(
                {
                    "path": path.as_posix(),
                    "status": "file_not_found",
                }
            )
            continue
        except OSError as exc:
            diagnostics.append(
                {
                    "path": path.as_posix(),
                    "status": "file_read_failed",
                    "message": str(exc),
                }
            )
            continue
        html_dump_state = graph.html_dump_state
        byte_range_fields_available: JsonArray = []
        dump_block_kinds: JsonArray = []
        span_annotation_fields_available: JsonArray = []
        html_dump_base: int | None = None
        if html_dump_state is not None:
            html_dump_base = html_dump_state.html_dump_base
            if html_dump_state.byte_ranges:
                byte_range_fields_available = ["offset", "size", "label", "kind"]
            dump_block_kinds = [
                kind for kind in sorted({block.kind for block in html_dump_state.dump_blocks})
            ]
            if html_dump_state.span_annotations:
                span_annotation_fields_available = [
                    "offset",
                    "size",
                    "label",
                    "css_classes",
                    "tooltip",
                ]
        diagnostics.append(
            {
                "path": path.as_posix(),
                "status": "read_graph_available",
                "tag_count": len(graph.tags),
                "graph_diagnostics": list(graph.diagnostics),
                "provenance_fields_available": [
                    "group",
                    "source_table",
                    "table_name",
                    "tag_id",
                    "family_4_instance_group",
                    "duplicate_instance_ordinal",
                ],
                "html_dump_state_available": html_dump_state is not None,
                "html_dump_base": html_dump_base,
                "requested_html_dump_base": request.render.html_dump_base,
                "byte_range_fields_available": byte_range_fields_available,
                "dump_block_kinds_available": dump_block_kinds,
                "span_annotation_fields_available": span_annotation_fields_available,
            }
        )
    return diagnostics


def _html_dump_graph_state_available(graph_diagnostics: JsonArray) -> bool:
    for item in graph_diagnostics:
        if not isinstance(item, dict):
            continue
        available = item.get("html_dump_state_available")
        if available is True:
            return True
    return False


def _read_diagnostic_is_blocking(diagnostic: Diagnostic) -> bool:
    return diagnostic.code not in {
        "read_graph_diagnostic",
        "files_failed_condition",
        "print_format_tag_not_rendered",
        "structured_xmp_list_item_boundaries_unavailable",
        "internal_charset_option_recognized",
        "unsafe_binary_output_blocked",
    }


def _files_failed_condition_diagnostic(
    condition_failed_count: int,
    request: MetadataReadRequest,
) -> Diagnostic:
    return Diagnostic(
        code="files_failed_condition",
        message=f"{condition_failed_count:5d} files failed condition",
        details={
            "condition_failed_count": condition_failed_count,
            "conditions": [
                {
                    "raw_option": condition.raw_option,
                    "expression": condition.expression,
                    "pass_number": condition.pass_number,
                }
                for condition in request.conditions
            ],
            "evidence_ids": [
                (
                    "../exiftool/exiftool lines 2193-2242 evaluate -if conditions "
                    "per file, call EFile(file, 2), increment countFailed, and skip "
                    "normal processing when the result is false."
                ),
                (
                    "../exiftool/exiftool lines 2061-2069 print the files-failed "
                    "condition summary during public command rendering."
                ),
                (
                    "../exiftool/exiftool lines 2086-2091 set exit status 2 when "
                    "all files failed the -if condition and no files were processed."
                ),
                (
                    "../exiftool/exiftool EXIT STATUS documentation lines 8128-8134 "
                    "documents status 2 when all files failed the -if condition."
                ),
            ],
        },
    )


def _render_issue_requested_tag(issue: RenderIssue) -> str:
    requested_tag = issue.requested_tag
    if requested_tag.group is None:
        return requested_tag.name
    return f"{requested_tag.group}:{requested_tag.name}"


def _record_with_forced_missing_tags(
    record: JsonRecord,
    issues: tuple[RenderIssue, ...],
    render: OutputRenderRequest,
) -> tuple[JsonRecord, tuple[RenderIssue, ...]]:
    if render.missing_tag_value is None:
        return record, issues

    forced_record = dict(record)
    forced_render_format: Literal["text", "json", "xml", "csv", "tab"]
    if render.format == "json":
        forced_render_format = "json"
    elif render.format == "xml":
        forced_render_format = "xml"
    elif render.format == "csv":
        forced_render_format = "csv"
    elif render.format == "tab":
        forced_render_format = "tab"
    else:
        forced_render_format = "text"
    for issue in issues:
        forced_record[
            _forced_missing_record_key(
                issue,
                include_group_names=render.include_group_names,
                render_format=forced_render_format,
            )
        ] = render.missing_tag_value
    return forced_record, ()


def _record_with_value_conversion_disabled_tags(
    record: JsonRecord,
    requested_tags: tuple[str, ...],
    render: OutputRenderRequest,
) -> JsonRecord:
    if not requested_tags:
        return record

    converted = dict(record)
    for requested_tag in requested_tags:
        selector = parse_public_read_tag_selector(requested_tag)
        if not selector.value_conversion_disabled:
            continue
        record_key = _value_conversion_disabled_record_key(selector, render)
        value = converted.get(record_key)
        converted_value = _source_backed_value_conversion_disabled_value(
            selector.tag_name,
            value,
        )
        if converted_value is not None:
            converted[record_key] = converted_value
    return converted


def _value_conversion_disabled_record_key(
    selector: PublicReadTagSelector,
    render: OutputRenderRequest,
) -> str:
    if render.include_group_names and selector.group_chain:
        return f"{selector.group_chain[-1].name}:{selector.tag_name}"
    return selector.tag_name


def _source_backed_value_conversion_disabled_value(
    tag_name: str,
    value: TagValue,
) -> TagValue:
    if tag_name.lower() == "orientation" and isinstance(value, str):
        return _EXIF_ORIENTATION_VALUE_CONV_BY_PRINT_CONV.get(value)
    return None


def _csv_compatible_read_diagnostics(
    records: list[MetadataReadRecord],
    request: MetadataReadRequest,
    diagnostics: list[Diagnostic],
) -> list[Diagnostic]:
    if request.render.format != "csv" or not request.tags:
        return diagnostics
    rendered_headers = set(_csv_headers(records, request))
    filtered: list[Diagnostic] = []
    for diagnostic in diagnostics:
        if not _is_csv_blank_cell_requested_tag_diagnostic(diagnostic, rendered_headers):
            filtered.append(diagnostic)
    return filtered


def _is_csv_blank_cell_requested_tag_diagnostic(
    diagnostic: Diagnostic,
    rendered_headers: set[str],
) -> bool:
    if diagnostic.code != "requested_tag_not_rendered" or diagnostic.details is None:
        return False
    requested_tags = diagnostic.details.get("requested_tags")
    if not isinstance(requested_tags, list):
        return False
    return bool(requested_tags) and all(
        isinstance(tag, str) and tag in rendered_headers for tag in requested_tags
    )


def _file_not_found_diagnostic(path: Path) -> Diagnostic:
    return Diagnostic(
        code="error_file_not_found",
        message=f"Error: File not found - {path}",
        details={
            "path": str(path),
            "evidence_ids": (
                "../exiftool/exiftool ProcessFiles read path checks Exists(file) "
                "before extraction and warns 'Error: File not found - $file'."
            ),
        },
    )


def public_read_execution_controls_not_connected_diagnostic(
    request: MetadataReadRequest,
    condition_plans: tuple[PublicReadConditionPlan, ...] = (),
) -> Diagnostic | None:
    unsupported_conditions = tuple(
        condition
        for condition in request.conditions
        if all(plan.condition != condition for plan in condition_plans)
    )
    alternate_file_diagnostic = _unsupported_public_alternate_file_read_diagnostic(
        request,
        condition_plans,
    )
    source_file_diagnostic = _unsupported_public_source_file_read_diagnostic(request)
    if (
        not unsupported_conditions
        and alternate_file_diagnostic is None
        and source_file_diagnostic is None
    ):
        return None
    evidence_ids: JsonArray = [
        "public.read.condition.parse",
        "public.read.file-order",
        "public.read.alternate-file.setup",
        "public.read.alternate-file.docs",
        "public.read.altfile-interpolation",
        "public.read.altfile-group-routing",
    ]
    return Diagnostic(
        code="public_read_execution_controls_deferred",
        message=(
            "ExifTool read execution controls are modeled in the public API, but this "
            "request uses conditional filtering, alternate-file extraction, or "
            "source-file routing outside the bounded native read subset."
        ),
        details={
            "conditions": [
                {
                    "raw_option": condition.raw_option,
                    "expression": condition.expression,
                    "pass_number": condition.pass_number,
                }
                for condition in unsupported_conditions
            ],
            "unsupported_condition_details": _unsupported_public_read_condition_details(
                unsupported_conditions
            ),
            "executed_conditions": [
                {
                    "raw_option": plan.condition.raw_option,
                    "expression": plan.condition.expression,
                    "pass_number": plan.condition.pass_number,
                    "tag": plan.tag,
                    "operator": plan.operator,
                    "comparison_value": plan.comparison_value,
                    "vm_tags": list(plan.vm_tags),
                }
                for plan in condition_plans
            ],
            "file_order": [
                {
                    "raw_option": order.raw_option,
                    "tag": order.tag,
                    "fast_pass": order.fast_pass,
                }
                for order in request.file_order
            ],
            "alternate_files": [
                {
                    "raw_option": alternate.raw_option,
                    "path": alternate.path.as_posix(),
                    "slot": alternate.slot,
                }
                for alternate in request.alternate_files
            ],
            "alternate_file_blocker": None
            if alternate_file_diagnostic is None
            else alternate_file_diagnostic.details,
            "source_file_blocker": None
            if source_file_diagnostic is None
            else source_file_diagnostic.details,
            "evidence_ids": evidence_ids,
        },
    )


def _unsupported_public_read_condition_details(
    unsupported_conditions: tuple[PublicReadCondition, ...],
) -> JsonArray:
    details: JsonArray = []
    for condition in unsupported_conditions:
        _rewritten, tags = _public_read_condition_vm_expression(condition.expression)
        unsupported_semantics = (
            "condition_not_public_tag_predicate"
            if not tags
            else "condition_uses_unsupported_perl_expression"
        )
        details.append(
            {
                "raw_option": condition.raw_option,
                "expression": condition.expression,
                "pass_number": condition.pass_number,
                "unsupported_semantics": unsupported_semantics,
                "supported_scope": (
                    "bounded public read -if execution supports deterministic predicates "
                    "whose values come from extracted public read tags and compile through "
                    "the safe-expression VM or the simple exists/comparison parser"
                ),
                "referenced_tags": list(tags),
                "evidence_ids": [
                    "public.read.condition.parse",
                    "public.read.condition.evaluate",
                ],
            }
        )
    return details


def _unsupported_public_alternate_file_read_diagnostic(
    request: MetadataReadRequest,
    condition_plans: tuple[PublicReadConditionPlan, ...] = (),
) -> Diagnostic | None:
    return _unsupported_public_alternate_file_read_diagnostic_for_tags(
        request,
        _public_read_execution_control_tags(request, condition_plans),
        condition_plans,
    )


def _unsupported_public_source_file_read_diagnostic(
    request: MetadataReadRequest,
) -> Diagnostic | None:
    unbounded_formats: JsonArray = [
        source_file.path.as_posix()
        for source_file in request.source_files
        if _public_alternate_files.alternate_file_format_support(
            source_file.path.as_posix()
        ).tag_interpolation
        and not _public_source_file_tag_format_is_bounded(source_file.path.as_posix())
    ]
    if unbounded_formats:
        return Diagnostic(
            code="public_source_file_read_deferred",
            message=(
                "ExifTool -srcfile source-file routing is recognized, but this "
                "tag-interpolated source file format is outside the bounded local "
                "public execution slice."
            ),
            details={
                "unsupported_semantics": "srcfile_tag_interpolation",
                "formats": unbounded_formats,
                "supported_scope": (
                    "bounded public -srcfile $TAG interpolation executes only for "
                    "formats anchored to the original file directory with %d or "
                    "$Directory and resolved from scalar main-file public read-graph "
                    "values"
                ),
                "evidence_ids": ["public.read.srcfile.docs"],
            },
        )
    advanced_formats: JsonArray = [
        source_file.path.as_posix()
        for source_file in request.source_files
        if _public_alternate_files.alternate_file_has_advanced_tag_interpolation(
            source_file.path.as_posix()
        )
    ]
    if not advanced_formats:
        return None
    return Diagnostic(
        code="public_source_file_read_deferred",
        message=(
            "ExifTool -srcfile source-file routing is recognized, but this source "
            "file format string uses arbitrary InsertTagValues expression semantics "
            "outside the bounded public execution slice."
        ),
        details={
            "unsupported_semantics": "srcfile_advanced_tag_interpolation",
            "formats": advanced_formats,
            "supported_scope": (
                "bounded public -srcfile execution supports @ current-file aliases "
                "and ExifTool FilenameSPrintf percent codes resolved from the "
                "original command-line file; scalar $TAG interpolation executes "
                "only when the tag is already available from the main-file public "
                "read graph and resolves to a bounded local source path"
            ),
            "evidence_ids": [
                "public.read.srcfile.parse",
                "public.read.srcfile.select",
                "public.read.srcfile.docs",
            ],
        },
    )


def _public_source_file_tag_format_is_bounded(raw_path: str) -> bool:
    return (
        "%d" in raw_path
        or "$Directory/" in raw_path
        or "${Directory}/" in raw_path
        or "${Directory }/" in raw_path
    )


def _unsupported_public_alternate_file_read_diagnostic_for_tags(
    request: MetadataReadRequest,
    requested_tags: tuple[str, ...],
    condition_plans: tuple[PublicReadConditionPlan, ...] = (),
) -> Diagnostic | None:
    if not request.alternate_files:
        return None
    if request.conditions and not _public_requested_alternate_file_slots(
        _public_read_condition_tags(condition_plans)
    ):
        return _public_alternate_file_deferred_diagnostic(
            "alternate_file_with_condition",
            "conditional expressions combined with alternate-file output selectors "
            "remain deferred unless the safe condition itself references bounded "
            "FileNUM:TAG state",
        )
    if request.render.binary_output:
        return _public_alternate_file_deferred_diagnostic(
            "alternate_file_with_binary_output",
            "binary alternate-file extraction is deferred; this slice executes scalar "
            "alternate FileNUM:TAG output selectors only",
        )
    requested_slots = _public_requested_alternate_file_slots(requested_tags)
    if not requested_slots:
        return _public_alternate_file_deferred_diagnostic(
            "alternate_file_without_file_group_selector",
            "bounded public execution only loads alternate files when a FileNUM:TAG "
            "selector requests values from that alternate source in output tags, "
            "conditions, or file ordering controls",
        )
    configured_slots = frozenset(alternate.slot for alternate in request.alternate_files)
    missing_slots = sorted(slot for slot in requested_slots if slot not in configured_slots)
    if missing_slots:
        return _public_alternate_file_deferred_diagnostic(
            "alternate_file_selector_without_configured_file",
            "FileNUM selectors require a matching -fileNUM alternate file option",
            missing_slots=missing_slots,
        )
    advanced_interpolated_slots = [
        alternate.slot
        for alternate in request.alternate_files
        if alternate.slot in requested_slots
        and _public_alternate_files.alternate_file_has_advanced_tag_interpolation(
            alternate.path.as_posix()
        )
    ]
    if advanced_interpolated_slots:
        return _public_alternate_file_deferred_diagnostic(
            "alternate_file_advanced_tag_interpolation",
            "ALTFILE % filename formatting codes, @ source-file aliases, literal "
            "dollar escapes, trusted UserParam values, and scalar main-file $TAG "
            "interpolation execute in this bounded slice; arbitrary InsertTagValues "
            "Perl expressions remain deferred",
            formatted_slots=advanced_interpolated_slots,
        )
    return None


def _public_read_execution_control_tags(
    request: MetadataReadRequest,
    condition_plans: tuple[PublicReadConditionPlan, ...],
) -> tuple[str, ...]:
    tags: list[str] = []
    tags.extend(request.tags)
    tags.extend(_public_read_condition_tags(condition_plans))
    tags.extend(order.tag.removeprefix("-") for order in request.file_order)
    return tuple(tags)


def _public_read_condition_tags(
    condition_plans: tuple[PublicReadConditionPlan, ...],
) -> tuple[str, ...]:
    tags: list[str] = []
    for plan in condition_plans:
        if plan.vm_tags:
            tags.extend(plan.vm_tags)
        elif plan.tag:
            tags.append(plan.tag)
    return tuple(tags)


def _public_requested_alternate_file_slots(
    requested_tags: tuple[str, ...],
) -> frozenset[PublicReadAlternateFileSlot]:
    slots: set[PublicReadAlternateFileSlot] = set()
    for requested_tag in requested_tags:
        selector = parse_public_read_tag_selector(requested_tag)
        for group in selector.group_chain:
            slot = _public_read_alternate_file_slot_for_group(group.name)
            if slot is not None:
                slots.add(slot)
    return frozenset(slots)


def _public_read_alternate_file_slot_for_group(
    group_name: str,
) -> PublicReadAlternateFileSlot | None:
    normalized = group_name.lower()
    if not normalized.startswith("file"):
        return None
    suffix = normalized.removeprefix("file")
    return int(suffix) if suffix.isdecimal() else None


def _public_alternate_file_deferred_diagnostic(
    unsupported_semantics: str,
    supported_scope: str,
    missing_slots: list[PublicReadAlternateFileSlot] | None = None,
    formatted_slots: list[PublicReadAlternateFileSlot] | None = None,
) -> Diagnostic:
    details: JsonObject = {
        "unsupported_semantics": unsupported_semantics,
        "supported_scope": supported_scope,
        "evidence_ids": [
            "public.read.alternate-file.docs",
            "public.read.alternate-file.setup",
            "public.read.filename-sprintf",
            "public.read.altfile-interpolation",
            "public.read.altfile-group-routing",
        ],
    }
    if missing_slots:
        missing_slot_values: JsonArray = []
        missing_slot_values.extend(missing_slots)
        details["missing_slots"] = missing_slot_values
    if formatted_slots:
        formatted_slot_values: JsonArray = []
        formatted_slot_values.extend(formatted_slots)
        details["formatted_slots"] = formatted_slot_values
    return Diagnostic(
        code="public_alternate_file_read_deferred",
        message=(
            "ExifTool -fileNUM alternate-file reads are recognized, but this "
            f"request is outside the bounded public execution slice: {unsupported_semantics}."
        ),
        details=details,
    )


def _public_read_condition_plan(condition: PublicReadCondition) -> PublicReadConditionPlan | None:
    vm_plan = _public_read_vm_condition_plan(condition)
    if vm_plan is not None:
        return vm_plan
    exists_match = _PUBLIC_READ_CONDITION_EXISTS_RE.fullmatch(condition.expression)
    if exists_match is not None:
        operator: PublicReadConditionOperator = (
            "not_exists" if exists_match.group("negated") else "exists"
        )
        return PublicReadConditionPlan(
            condition=condition,
            tag=_public_read_condition_match_tag(exists_match).removesuffix("#"),
            operator=operator,
        )
    comparison_match = _PUBLIC_READ_CONDITION_COMPARISON_RE.fullmatch(condition.expression)
    if comparison_match is None:
        return None
    literal = comparison_match.group("literal")
    return PublicReadConditionPlan(
        condition=condition,
        tag=_public_read_condition_match_tag(comparison_match).removesuffix("#"),
        operator=_public_read_condition_operator(comparison_match.group("operator")),
        comparison_value=_public_read_condition_literal(literal),
    )


def _public_read_condition_match_tag(match: re.Match[str]) -> str:
    return match.group("braced_tag") or match.group("tag")


def _public_read_vm_condition_plan(
    condition: PublicReadCondition,
) -> PublicReadConditionPlan | None:
    rewritten, tags = _public_read_condition_vm_expression(condition.expression)
    if not tags:
        return None
    from exifmodern.safe_expression.facade import compile_safe_expression

    program = compile_safe_expression(rewritten)
    if program is None:
        return None
    return PublicReadConditionPlan(
        condition=condition,
        tag=tags[0],
        operator="vm",
        vm_program=program,
        vm_tags=tags,
    )


def _public_read_condition_vm_expression(expression: str) -> tuple[str, tuple[str, ...]]:
    tags: list[str] = []
    tag_indexes: dict[str, int] = {}

    def replacement(match: re.Match[str]) -> str:
        tag = _public_read_condition_match_tag(match).removesuffix("#")
        index = tag_indexes.get(tag)
        if index is None:
            index = len(tags)
            tags.append(tag)
            tag_indexes[tag] = index
        return f"$val[{index}]"

    rewritten = _PUBLIC_READ_CONDITION_TAG_REFERENCE_RE.sub(replacement, expression)
    return rewritten, tuple(tags)


def _public_read_condition_operator(operator: str) -> PublicReadConditionOperator:
    normalized = operator.lower()
    if normalized == "eq":
        return "eq"
    if normalized == "ne":
        return "ne"
    if normalized == "lt":
        return "lt"
    if normalized == "le":
        return "le"
    if normalized == "gt":
        return "gt"
    if normalized == "ge":
        return "ge"
    if operator == "==":
        return "=="
    if operator == "!=":
        return "!="
    if operator == "<":
        return "<"
    if operator == "<=":
        return "<="
    if operator == ">":
        return ">"
    return ">="


def _public_read_condition_literal(literal: str) -> str | float:
    if (literal.startswith("'") and literal.endswith("'")) or (
        literal.startswith('"') and literal.endswith('"')
    ):
        return literal[1:-1]
    return float(literal)


def _public_read_conditions_match(
    graph: ReadGraph,
    condition_plans: tuple[PublicReadConditionPlan, ...],
) -> bool:
    return all(_public_read_condition_matches(graph, plan) for plan in condition_plans)


def _public_read_condition_matches(graph: ReadGraph, plan: PublicReadConditionPlan) -> bool:
    if plan.vm_program is not None:
        return _public_read_vm_condition_matches(graph, plan)
    user_param_value = _public_read_graph_user_param_value(graph, plan.tag)
    if user_param_value is not None:
        if plan.operator == "exists":
            return _public_read_condition_truthy(user_param_value)
        if plan.operator == "not_exists":
            return not _public_read_condition_truthy(user_param_value)
        comparison_value = plan.comparison_value
        if comparison_value is None:
            return False
        return _public_read_condition_compare(user_param_value, plan.operator, comparison_value)
    requested_tag = requested_tag_from_arg(f"-{plan.tag}")
    if requested_tag is None:
        return plan.operator == "not_exists"
    tags = find_graph_tags(
        graph,
        requested_tag,
        RenderOptions(group_names=False, duplicate_tags=False, group_family=1),
    )
    if not tags:
        return plan.operator == "not_exists"
    if plan.operator == "exists":
        return _public_read_condition_truthy(tags[0].value)
    if plan.operator == "not_exists":
        return not _public_read_condition_truthy(tags[0].value)
    comparison_value = plan.comparison_value
    if comparison_value is None:
        return False
    return _public_read_condition_compare(tags[0].value, plan.operator, comparison_value)


def _public_read_vm_condition_matches(graph: ReadGraph, plan: PublicReadConditionPlan) -> bool:
    if plan.vm_program is None:
        return False
    from exifmodern.safe_expression.vm import evaluate_program, perl_truthy

    values: list[VmScalar] = [
        _public_read_condition_vm_value(_public_read_condition_tag_value(graph, tag))
        for tag in plan.vm_tags
    ]
    try:
        result = evaluate_program(plan.vm_program, {"$val": values})
    except TypeError, ValueError:
        return False
    return perl_truthy(result)


def _public_read_condition_vm_value(value: TagValue) -> str | int | float | bool | None:
    if value is None or isinstance(value, BinaryTagValue | BinaryTagListValue):
        return None
    if isinstance(value, str | int | float | bool):
        return value
    return " ".join(str(item) for item in value if item is not None)


def _public_read_condition_tag_value(graph: ReadGraph, tag: str) -> TagValue:
    user_param_value = _public_read_graph_user_param_value(graph, tag)
    if user_param_value is not None:
        return user_param_value
    requested_tag = requested_tag_from_arg(f"-{tag}")
    if requested_tag is None:
        return None
    tags = find_graph_tags(
        graph,
        requested_tag,
        RenderOptions(group_names=False, duplicate_tags=False, group_family=1),
    )
    if not tags:
        return None
    return tags[0].value


def _public_read_graph_user_param_value(graph: ReadGraph, tag: str) -> TagValue:
    normalized = tag.rpartition(":")[2]
    for read_tag in graph.tags:
        if read_tag.provenance.family_0_group != "UserParam":
            continue
        if read_tag.name.lower() == normalized.removesuffix("#").lower():
            return read_tag.value
    return None


def _public_read_condition_truthy(value: TagValue) -> bool:
    if value is None or isinstance(value, BinaryTagValue | BinaryTagListValue):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, list):
        return bool(value)
    return value not in ("", "0")


def _public_read_condition_compare(
    value: TagValue,
    operator: PublicReadConditionOperator,
    comparison_value: str | float,
) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, BinaryTagValue | BinaryTagListValue):
        return False
    if isinstance(value, list):
        return False
    if not isinstance(value, str | int | float):
        return False
    if operator in ("==", "!=", "<", "<=", ">", ">="):
        left_number = _public_read_condition_number(value)
        if left_number is None or not isinstance(comparison_value, float):
            return False
        return _public_read_condition_numeric_compare(left_number, operator, comparison_value)
    left_text = str(value)
    right_text = str(comparison_value)
    return _public_read_condition_text_compare(left_text, operator, right_text)


def _public_read_condition_number(value: str | int | float) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(value)
    except ValueError:
        return None


def _public_read_condition_numeric_compare(
    left: float,
    operator: PublicReadConditionOperator,
    right: float,
) -> bool:
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    return left >= right


def _public_read_condition_text_compare(
    left: str,
    operator: PublicReadConditionOperator,
    right: str,
) -> bool:
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "lt":
        return left < right
    if operator == "le":
        return left <= right
    if operator == "gt":
        return left > right
    return left >= right


def binary_output_not_connected_diagnostic(request: MetadataReadRequest) -> Diagnostic:
    return Diagnostic(
        code="binary_output_not_connected",
        message=(
            "ExifTool binary output mode is recognized, but no requested native read "
            "record currently exposes a bounded bytes payload."
        ),
        details={
            "requested_tags": list(request.tags),
            "current_tag_value_model": (
                "str | int | float | bool | None | list[str] | BinaryTagValue"
            ),
            "evidence_ids": [
                "public.read.binary-output.options",
                "public.read.binary-output.convert",
                "public.read.binary-output.docs",
            ],
        },
    )


def output_file_routing_not_connected_diagnostic(
    request: OutputRenderRequest,
) -> Diagnostic | None:
    routing = request.output_file_routing
    if _output_file_routing_is_default(routing):
        return None
    if _output_file_routing_is_executable_per_source_text_read(request):
        return None
    if _output_file_routing_is_executable_per_tag_scalar_read(request):
        return None
    if _output_file_routing_is_executable_per_tag_binary_read(request):
        return None
    return Diagnostic(
        code="output_file_routing_execution_deferred",
        message=(
            "ExifTool external output routing is modeled in the public API, but public "
            "read/write execution is not wired for this routing shape yet."
        ),
        details={
            "output_file_routing": output_file_routing_request_to_json_value(routing),
            "executable_subset": (
                "Public read execution currently supports only per-source -w output "
                "for rendered text/JSON records, per-tag -W output for rendered "
                "scalar text/JSON tags, and per-tag -b -W output for native "
                "byte-bearing tags with error-if-exists or overwrite policy."
            ),
            "evidence_ids": [
                "public.output.read-routing.parse",
                "public.output.read-routing.per-source-docs",
                "public.output.read-routing.per-tag-docs",
                "public.write.output.file-routing",
            ],
        },
    )


def _output_file_routing_is_default(request: OutputFileRoutingRequest) -> bool:
    return (
        not request.stdout_binary
        and request.unsafe_binary_policy in {"explicit_tags_only", "request_all_allows_unsafe"}
        and request.per_source_file is None
        and request.per_tag_file is None
        and request.write_output_file is None
    )


def _output_file_routing_is_executable_per_source_text_read(
    request: OutputRenderRequest,
) -> bool:
    routing = request.output_file_routing
    per_source = routing.per_source_file
    return (
        per_source is not None
        and not request.binary_output
        and request.format in {"text", "json"}
        and not routing.stdout_binary
        and routing.unsafe_binary_policy == "explicit_tags_only"
        and routing.per_tag_file is None
        and routing.write_output_file is None
        and per_source.overwrite_policy
        in {"error_if_exists", "overwrite_existing", "append_existing", "overwrite_new_then_append"}
    )


def _output_file_routing_is_executable_per_tag_scalar_read(
    request: OutputRenderRequest,
) -> bool:
    routing = request.output_file_routing
    per_tag = routing.per_tag_file
    return (
        per_tag is not None
        and per_tag.format_template != ""
        and not request.binary_output
        and request.format in {"text", "json"}
        and not routing.stdout_binary
        and routing.unsafe_binary_policy == "explicit_tags_only"
        and routing.per_source_file is None
        and routing.write_output_file is None
        and per_tag.overwrite_policy
        in {"error_if_exists", "overwrite_existing", "append_existing", "overwrite_new_then_append"}
    )


def _output_file_routing_is_executable_per_tag_binary_read(
    request: OutputRenderRequest,
) -> bool:
    routing = request.output_file_routing
    per_tag = routing.per_tag_file
    return (
        per_tag is not None
        and per_tag.format_template != ""
        and request.binary_output
        and request.format in {"text", "json"}
        and not routing.stdout_binary
        and routing.unsafe_binary_policy == "explicit_tags_only"
        and routing.per_source_file is None
        and routing.write_output_file is None
        and per_tag.overwrite_policy
        in {"error_if_exists", "overwrite_existing", "append_existing", "overwrite_new_then_append"}
    )


def _execute_read_output_file_routing(
    records: list[MetadataReadRecord],
    request: OutputRenderRequest,
) -> tuple[tuple[OutputFileWriteResult, ...], tuple[Diagnostic, ...]]:
    if _output_file_routing_is_executable_per_tag_scalar_read(
        request
    ) or _output_file_routing_is_executable_per_tag_binary_read(request):
        _ensure_public_write_runtime_imports()
        return _execute_read_per_tag_output_file_routing(records, request)
    if not _output_file_routing_is_executable_per_source_text_read(request):
        return (), ()
    per_source = request.output_file_routing.per_source_file
    if per_source is None:
        return (), ()
    _ensure_public_write_runtime_imports()

    output_files: list[OutputFileWriteResult] = []
    diagnostics: list[Diagnostic] = []
    for record in records:
        output_path, path_diagnostic = _per_source_output_path(
            record.path,
            per_source.format_template,
            per_source.overwrite_policy,
        )
        if path_diagnostic is not None:
            diagnostics.append(path_diagnostic)
            continue
        payload = _payload_for_output_write(
            output_path,
            _render_per_source_output_payload(record, request),
            per_source.overwrite_policy,
        )
        if per_source.overwrite_policy == "error_if_exists" and output_path.exists():
            diagnostics.append(_output_file_exists_diagnostic(record.path, output_path))
            continue
        try:
            write_result = write_bytes_transactionally(output_path, payload)
        except OSError as exc:
            diagnostics.append(_output_file_write_failed_diagnostic(record.path, output_path, exc))
            continue
        output_files.append(
            OutputFileWriteResult(
                source_path=record.path,
                output_path=output_path,
                bytes_written=write_result.bytes_written,
                replaced_existing=write_result.replaced_existing,
                routing_kind="per_source_file",
            )
        )
    return tuple(output_files), tuple(diagnostics)


def _execute_read_per_tag_output_file_routing(
    records: list[MetadataReadRecord],
    request: OutputRenderRequest,
) -> tuple[tuple[OutputFileWriteResult, ...], tuple[Diagnostic, ...]]:
    per_tag = request.output_file_routing.per_tag_file
    if per_tag is None:
        return (), ()
    diagnostics = list(_per_tag_output_unexposed_value_diagnostics(records, per_tag))
    binary_list_route_diagnostic = _binary_list_item_output_route_diagnostic(
        records,
        request,
        per_tag,
    )
    if binary_list_route_diagnostic is not None:
        return (), (*tuple(diagnostics), binary_list_route_diagnostic)
    if _per_tag_output_routing_appends_to_one_file(per_tag):
        appended_output_files, append_diagnostics = (
            _execute_read_per_tag_single_output_append_routing(
                records,
                request,
                per_tag,
            )
        )
        return appended_output_files, (*tuple(diagnostics), *append_diagnostics)

    output_files: list[OutputFileWriteResult] = []
    for record in records:
        for output_tag in record.output_tags:
            if not _per_tag_output_extension_is_selected(output_tag, per_tag):
                continue
            output_path, path_diagnostic = _per_tag_output_path(
                record.path,
                output_tag,
                per_tag.format_template,
                per_tag.overwrite_policy,
            )
            if path_diagnostic is not None:
                diagnostics.append(path_diagnostic)
                continue
            payload = _payload_for_output_write(
                output_path,
                _render_per_tag_output_payload(record, output_tag, request),
                per_tag.overwrite_policy,
            )
            if per_tag.overwrite_policy == "error_if_exists" and output_path.exists():
                diagnostics.append(_output_file_exists_diagnostic(record.path, output_path))
                continue
            try:
                write_result = write_bytes_transactionally(output_path, payload)
            except OSError as exc:
                diagnostics.append(
                    _output_file_write_failed_diagnostic(record.path, output_path, exc)
                )
                continue
            output_files.append(
                OutputFileWriteResult(
                    source_path=record.path,
                    output_path=output_path,
                    bytes_written=write_result.bytes_written,
                    replaced_existing=write_result.replaced_existing,
                    routing_kind="per_tag_file",
                )
            )
    return tuple(output_files), tuple(diagnostics)


def _per_tag_output_unexposed_value_diagnostics(
    records: list[MetadataReadRecord],
    routing: OutputPerTagFileRouting,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for record in records:
        if record.output_tags:
            continue
        unexposed_labels: JsonArray = [label for label in record.values if label != "SourceFile"]
        if not unexposed_labels:
            continue
        diagnostics.append(
            Diagnostic(
                code="unsupported_public_per_tag_output_unexposed_values",
                message=(
                    f"{record.path}: public -W per-tag output has rendered values that "
                    "are not exposed as tag-output records, so no external output bytes "
                    "were emitted for those values."
                ),
                details={
                    "source_path": record.path.as_posix(),
                    "format_template": routing.format_template,
                    "overwrite_policy": routing.overwrite_policy,
                    "unexposed_labels": unexposed_labels,
                    "route_blocker": "per_tag_output_requires_output_rendered_tags",
                    "evidence_ids": [
                        "public.output.read-routing.parse",
                        "public.output.read-routing.open",
                    ],
                },
            )
        )
    return tuple(diagnostics)


def _binary_list_item_output_route_diagnostic(
    records: list[MetadataReadRecord],
    request: OutputRenderRequest,
    routing: OutputPerTagFileRouting,
) -> Diagnostic | None:
    if not request.binary_output:
        return None
    list_labels: JsonArray = []
    for record in records:
        for label, value in record.values.items():
            if (
                label != "SourceFile"
                and isinstance(value, BinaryTagListValue)
                and value.item_count > 1
                and any(
                    output_tag.label == label
                    and _per_tag_output_extension_is_selected(output_tag, routing)
                    for output_tag in record.output_tags
                )
            ):
                list_labels.append(label)
    if not list_labels:
        return None
    if _per_tag_output_template_has_copy_counter(routing.format_template) and (
        routing.overwrite_policy != "overwrite_existing"
    ):
        return None
    return Diagnostic(
        code="unsupported_public_binary_list_item_output_route",
        message=(
            "public -b -W output selected multi-item binary list payloads, but "
            "the output route does not provide deterministic per-item filenames."
        ),
        details={
            "format_template": routing.format_template,
            "overwrite_policy": routing.overwrite_policy,
            "list_labels": list_labels,
            "route_blocker": "binary_list_item_output_requires_copy_counter",
            "evidence_ids": [
                "public.output.binary-list-routing",
                "public.output.binary-list-docs",
            ],
        },
    )


def _execute_read_per_tag_single_output_append_routing(
    records: list[MetadataReadRecord],
    request: OutputRenderRequest,
    per_tag: OutputPerTagFileRouting,
) -> tuple[tuple[OutputFileWriteResult, ...], tuple[Diagnostic, ...]]:
    pending_payloads: dict[Path, tuple[Path, bytes]] = {}
    diagnostics: list[Diagnostic] = []
    for record in records:
        selected_tags = tuple(
            output_tag
            for output_tag in record.output_tags
            if _per_tag_output_extension_is_selected(output_tag, per_tag)
        )
        if not selected_tags:
            continue
        output_path, path_diagnostic = _per_tag_output_path(
            record.path,
            selected_tags[0],
            per_tag.format_template,
            per_tag.overwrite_policy,
        )
        if path_diagnostic is not None:
            diagnostics.append(path_diagnostic)
            continue
        record_payload = b"".join(
            _render_per_tag_output_payload(record, output_tag, request)
            for output_tag in selected_tags
        )
        existing_source_path, existing_payload = pending_payloads.get(
            output_path,
            (record.path, b""),
        )
        pending_payloads[output_path] = (
            existing_source_path,
            existing_payload + record_payload,
        )

    output_files: list[OutputFileWriteResult] = []
    for output_path, (source_path, payload) in pending_payloads.items():
        write_payload = _payload_for_single_output_append_write(
            output_path,
            payload,
            per_tag.overwrite_policy,
        )
        try:
            write_result = write_bytes_transactionally(output_path, write_payload)
        except OSError as exc:
            diagnostics.append(_output_file_write_failed_diagnostic(source_path, output_path, exc))
            continue
        output_files.append(
            OutputFileWriteResult(
                source_path=source_path,
                output_path=output_path,
                bytes_written=write_result.bytes_written,
                replaced_existing=write_result.replaced_existing,
                routing_kind="per_tag_file",
            )
        )
    return tuple(output_files), tuple(diagnostics)


def _per_tag_output_routing_appends_to_one_file(routing: OutputPerTagFileRouting) -> bool:
    return (
        routing.overwrite_policy in {"append_existing", "overwrite_new_then_append"}
        and re.search(r"%[-+]?\d*[.:]?\d*[lu]?[tgso]", routing.format_template) is None
    )


def _payload_for_single_output_append_write(
    output_path: Path,
    payload: bytes,
    overwrite_policy: OutputFileOverwritePolicy,
) -> bytes:
    if overwrite_policy == "append_existing" and output_path.exists():
        return output_path.read_bytes() + payload
    return payload


def _payload_for_output_write(
    output_path: Path,
    payload: bytes,
    overwrite_policy: OutputFileOverwritePolicy,
) -> bytes:
    if overwrite_policy not in {"append_existing", "overwrite_new_then_append"}:
        return payload
    if not output_path.exists():
        return payload
    return output_path.read_bytes() + payload


def _render_per_source_output_payload(
    record: MetadataReadRecord,
    request: OutputRenderRequest,
) -> bytes:
    if request.format == "json":
        return _render_records_json([record], request)
    return record.rendered_text.encode("utf-8")


def _render_per_tag_output_payload(
    record: MetadataReadRecord,
    output_tag: OutputRenderedTag,
    request: OutputRenderRequest,
) -> bytes:
    if request.binary_output and isinstance(output_tag.value, BinaryTagValue):
        return output_tag.value.data
    if request.format == "json":
        return render_exiftool_json(
            _json_record_for_render(
                {
                    "SourceFile": record.path.as_posix(),
                    output_tag.label: output_tag.value,
                },
                request,
            )
        )
    return (_text_value(output_tag.value, list_separator=request.list_separator) + "\n").encode(
        "utf-8"
    )


def _per_tag_output_extension_is_selected(
    output_tag: OutputRenderedTag,
    routing: OutputPerTagFileRouting,
) -> bool:
    if not routing.extension_filters:
        return True
    extension = output_tag.suggested_extension.lower().removeprefix(".")
    includes = {
        extension_filter.extension.lower().removeprefix(".")
        for extension_filter in routing.extension_filters
        if extension_filter.mode == "include"
    }
    excludes = {
        extension_filter.extension.lower().removeprefix(".")
        for extension_filter in routing.extension_filters
        if extension_filter.mode == "exclude"
    }
    if includes and extension not in includes:
        return False
    return extension not in excludes


def _per_source_output_path(
    source_path: Path,
    format_template: str,
    overwrite_policy: OutputFileOverwritePolicy = "error_if_exists",
) -> tuple[Path, Diagnostic | None]:
    if _output_template_has_format_code(format_template):
        unsupported_code = _unsupported_output_format_code(format_template)
        if unsupported_code is not None:
            return source_path, _unsupported_output_format_code_diagnostic(
                source_path,
                format_template,
                unsupported_code,
            )
        return _next_unused_output_path(
            source_path,
            format_template,
            overwrite_policy=overwrite_policy,
            output_tag=None,
        )
    extension = format_template if format_template.startswith(".") else f".{format_template}"
    return source_path.with_suffix(extension), None


def _per_tag_output_path(
    source_path: Path,
    output_tag: OutputRenderedTag,
    format_template: str,
    overwrite_policy: OutputFileOverwritePolicy = "error_if_exists",
) -> tuple[Path, Diagnostic | None]:
    unsupported_code = _unsupported_per_tag_output_format_code(format_template)
    if unsupported_code is not None:
        return source_path, _unsupported_output_format_code_diagnostic(
            source_path,
            format_template,
            unsupported_code,
        )
    return _next_unused_output_path(
        source_path,
        format_template,
        overwrite_policy=overwrite_policy,
        output_tag=output_tag,
    )


def _output_template_has_format_code(format_template: str) -> bool:
    return "%" in format_template


def _unsupported_output_format_code(format_template: str) -> str | None:
    allowed_codes = frozenset({"c", "C", "d", "D", "e", "E", "f", "F"})
    index = 0
    while index < len(format_template):
        if format_template[index] != "%":
            index += 1
            continue
        if index + 1 < len(format_template) and format_template[index + 1] == "%":
            index += 2
            continue
        format_code = _next_output_format_code(format_template[index:])
        if format_code is None:
            return "%"
        if format_code.code not in allowed_codes:
            return f"%{format_code.code}"
        index += format_code.token_length
    return None


def _unsupported_per_tag_output_format_code(format_template: str) -> str | None:
    allowed_codes = frozenset({"c", "C", "d", "D", "e", "E", "f", "F", "g", "o", "s", "t"})
    index = 0
    while index < len(format_template):
        if format_template[index] != "%":
            index += 1
            continue
        if index + 1 < len(format_template) and format_template[index + 1] == "%":
            index += 2
            continue
        format_code = _next_output_format_code(format_template[index:])
        if format_code is None:
            return "%"
        if format_code.code not in allowed_codes:
            return f"%{format_code.code}"
        index += format_code.token_length
    return None


@dataclass(frozen=True)
class _OutputFormatCode:
    code: str
    token_length: int


def _next_output_format_code(template_tail: str) -> _OutputFormatCode | None:
    match = re.match(r"%[-+]?\d*[.:]?\d*[lun]?[cC]", template_tail)
    if match is not None:
        return _OutputFormatCode(code=template_tail[match.end() - 1], token_length=match.end())
    match = re.match(r"%[-+]?\d*[.:]?\d*[lu]?[dDfFeEtgso]", template_tail)
    if match is None:
        return None
    token_length = match.end()
    code = template_tail[token_length - 1]
    if code == "g" and token_length < len(template_tail) and template_tail[token_length].isdigit():
        token_length += 1
    return _OutputFormatCode(code=code, token_length=token_length)


def _expand_per_source_output_template(source_path: Path, format_template: str) -> str:
    return _expand_per_source_output_template_with_copy(source_path, format_template, copy_number=0)


def _expand_per_source_output_template_with_copy(
    source_path: Path,
    format_template: str,
    *,
    copy_number: int,
) -> str:
    rendered = _public_filename_sprintf(
        format_template=format_template,
        source_path=source_path,
    )
    return _expand_output_copy_tokens(rendered, copy_number=copy_number).replace("%%", "%")


def _expand_per_tag_output_template(
    source_path: Path,
    output_tag: OutputRenderedTag,
    format_template: str,
    *,
    copy_number: int = 0,
) -> str:
    rendered = _public_filename_sprintf(
        format_template=format_template,
        source_path=source_path,
        tag_context=PublicFilenameSprintfTagContext(
            tag_name=output_tag.tag_name,
            group_names=output_tag.group_names,
            suggested_extension=output_tag.suggested_extension,
            original_file_name=output_tag.original_file_name,
        ),
    )
    return _expand_output_copy_tokens(rendered, copy_number=copy_number).replace("%%", "%")


def _expand_output_copy_tokens(format_template: str, *, copy_number: int) -> str:
    return re.sub(
        r"%([-+]?)(\d*)([.:]?)(\d*)([lun]?)([cC])",
        lambda match: _expanded_output_copy_token(match, copy_number=copy_number),
        format_template,
    )


def _expanded_output_copy_token(match: re.Match[str], *, copy_number: int) -> str:
    sign = match.group(1)
    width_text = match.group(2)
    decimal = match.group(3)
    width_2_text = match.group(4)
    modifier = match.group(5)
    token = match.group(6)
    width = int(width_text or "0")
    width_2 = int(width_2_text or "0")
    if token == "c" and not decimal and not copy_number:
        return ""
    if token == "c" and width < width_2:
        width = width_2
    number = copy_number + (1 if modifier else 0)
    value = f"{number:0{width}d}" if width else str(number)
    if modifier and modifier != "n":
        value = _copy_counter_alpha(copy_number, uppercase=modifier == "u")
        value = value.rjust(width, "a" if modifier == "l" else "A")
    if token == "c" and sign:
        return ("-" if sign == "-" else "_") + value
    return value


def _copy_counter_alpha(copy_number: int, *, uppercase: bool) -> str:
    alphabet_start = ord("A" if uppercase else "a")
    value = chr(alphabet_start + (copy_number % 26))
    while copy_number >= 26:
        copy_number = copy_number // 26 - 1
        value = chr(alphabet_start + (copy_number % 26)) + value
    return value


def _per_tag_output_template_has_copy_counter(format_template: str) -> bool:
    return re.search(r"%[-+]?\d*[.:]?\d*[lun]?[cC]", format_template) is not None


def _next_unused_output_path(
    source_path: Path,
    format_template: str,
    *,
    overwrite_policy: OutputFileOverwritePolicy,
    output_tag: OutputRenderedTag | None,
) -> tuple[Path, Diagnostic | None]:
    if not _per_tag_output_template_has_copy_counter(format_template):
        if output_tag is None:
            return Path(_expand_per_source_output_template(source_path, format_template)), None
        return Path(_expand_per_tag_output_template(source_path, output_tag, format_template)), None
    if overwrite_policy == "overwrite_existing":
        copy_number = 0
        if output_tag is None:
            return (
                Path(
                    _expand_per_source_output_template_with_copy(
                        source_path,
                        format_template,
                        copy_number=copy_number,
                    )
                ),
                None,
            )
        return (
            Path(
                _expand_per_tag_output_template(
                    source_path,
                    output_tag,
                    format_template,
                    copy_number=copy_number,
                )
            ),
            None,
        )
    for copy_number in range(MAX_PUBLIC_WILDCARD_EXPANSION_TAGS):
        if output_tag is None:
            candidate = Path(
                _expand_per_source_output_template_with_copy(
                    source_path,
                    format_template,
                    copy_number=copy_number,
                )
            )
        else:
            candidate = Path(
                _expand_per_tag_output_template(
                    source_path,
                    output_tag,
                    format_template,
                    copy_number=copy_number,
                )
            )
        if not candidate.exists():
            return candidate, None
    return source_path, _unsupported_output_format_code_diagnostic(
        source_path,
        format_template,
        "%c",
    )


def _unsupported_output_format_code_diagnostic(
    source_path: Path,
    format_template: str,
    unsupported_code: str,
) -> Diagnostic:
    return Diagnostic(
        code="output_file_format_code_deferred",
        message=(
            f"{source_path}: output template {format_template!r} uses {unsupported_code}, "
            "which requires ExifTool format-code semantics not yet wired."
        ),
        details={
            "source_path": source_path.as_posix(),
            "format_template": format_template,
            "unsupported_code": unsupported_code,
            "evidence_ids": [
                "public.output.read-routing.per-source-docs",
                "public.output.read-routing.per-tag-docs",
            ],
        },
    )


def _output_file_exists_diagnostic(source_path: Path, output_path: Path) -> Diagnostic:
    return Diagnostic(
        code="output_file_exists",
        message=(
            f"{source_path}: output file already exists and overwrite was not requested: "
            f"{output_path}"
        ),
        details={
            "source_path": source_path.as_posix(),
            "output_path": output_path.as_posix(),
            "evidence_ids": ["public.output.read-routing.per-source-docs"],
        },
    )


def _output_file_write_failed_diagnostic(
    source_path: Path,
    output_path: Path,
    exc: OSError,
) -> Diagnostic:
    return Diagnostic(
        code="output_file_write_failed",
        message=f"{source_path}: unable to write routed output file {output_path}: {exc}",
        details={
            "source_path": source_path.as_posix(),
            "output_path": output_path.as_posix(),
        },
    )


def numeric_output_not_connected_diagnostic(request: MetadataReadRequest) -> Diagnostic:
    return Diagnostic(
        code="numeric_output_not_connected",
        message=(
            "ExifTool -n numeric output is recognized, but the public read graph does not "
            "yet preserve separate raw and print-converted values for all tags."
        ),
        details={
            "requested_tags": list(request.tags),
            "next_integration_seam": (
                "Extend ReadTag/TagValue with raw_value plus print-converted display_value, "
                "then route OutputRenderRequest.numeric_output through render selection."
            ),
            "evidence_ids": ["public.read.numeric-output"],
        },
    )


def _expanded_read_paths(request: MetadataReadRequest) -> tuple[Path, ...]:
    from exifmodern.public_interface.traversal import expand_public_cli_read_paths

    paths = expand_public_cli_read_paths(
        request.paths,
        recursive=request.recursive,
        recurse_dot_directories=request.recurse_dot_directories,
        ignore_directories=request.ignore_directories,
        extension_filters=request.extension_filters,
    )
    return _paths_with_public_file_order(paths, request)


def _public_read_source_file_path(
    path: Path,
    request: MetadataReadRequest,
) -> tuple[Path, tuple[Diagnostic, ...]]:
    if not request.source_files:
        return path, ()
    tag_graph: ReadGraph | None = None
    first_formatted: Path | None = None
    for source_file in request.source_files:
        tag_values: tuple[PublicInsertTagValue, ...] = ()
        if _public_alternate_files.alternate_file_format_support(
            source_file.path.as_posix()
        ).tag_interpolation:
            if tag_graph is None:
                try:
                    tag_graph = _build_public_read_graph_for_request(path, request)
                except FileNotFoundError:
                    return path, (_file_not_found_diagnostic(path),)
                except OSError as exc:
                    return path, (
                        Diagnostic(
                            code="file_read_failed",
                            message=f"Unable to read metadata from {path}: {exc}",
                        ),
                    )
            tag_values = _public_insert_tag_values_for_graph(
                source_file.path.as_posix(),
                tag_graph,
            )
            unresolved_tokens = _public_insert_tag_unresolved_tokens_for_graph(
                source_file.path.as_posix(),
                _public_user_params_for_path(request, path),
                tag_graph,
            )
            if unresolved_tokens:
                return path, (
                    _public_source_file_tag_interpolation_diagnostic(
                        source_file.path,
                        unresolved_tokens,
                    ),
                )
        formatted = _public_alternate_files.resolve_alternate_file_path(
            source_file.path,
            path,
            _public_user_params_for_path(request, path),
            tag_values,
        )
        if tag_values:
            source_bound_diagnostic = _public_source_file_tag_path_bound_diagnostic(
                source_file.path,
                formatted,
                path,
            )
            if source_bound_diagnostic is not None:
                return path, (source_bound_diagnostic,)
        if first_formatted is None:
            first_formatted = formatted
        if formatted.exists():
            return formatted, ()
    return first_formatted if first_formatted is not None else path, ()


def _public_source_file_tag_interpolation_diagnostic(
    raw_path: Path,
    tokens: tuple[_PublicInsertTagUnresolvedToken, ...],
) -> Diagnostic:
    token_values: JsonArray = []
    reason_values: JsonObject = {}
    for token in tokens:
        token_values.append(token.token)
        reason_values[token.token] = token.reason
    return Diagnostic(
        code="public_source_file_read_deferred",
        message=(
            "ExifTool -srcfile source-file path interpolation is recognized, but "
            "this request references tag values that are missing or not available "
            "as bounded scalar public read-graph values from the main file."
        ),
        details={
            "unsupported_semantics": "srcfile_tag_interpolation_unresolved",
            "format": raw_path.as_posix(),
            "tokens": token_values,
            "token_reasons": reason_values,
            "supported_scope": (
                "bounded public -srcfile $TAG interpolation executes only when "
                "each referenced tag is already present as a scalar public read-graph "
                "value before source-file routing"
            ),
            "evidence_ids": [
                "public.read.condition.parse",
                "public.read.srcfile.docs",
            ],
        },
    )


def _public_source_file_tag_path_bound_diagnostic(
    raw_path: Path,
    resolved_path: Path,
    original_path: Path,
) -> Diagnostic | None:
    if _public_source_file_tag_path_is_bounded(resolved_path, original_path):
        return None
    return Diagnostic(
        code="public_source_file_read_deferred",
        message=(
            "ExifTool -srcfile source-file path interpolation resolved outside the "
            "bounded local public execution scope."
        ),
        details={
            "unsupported_semantics": "srcfile_tag_interpolation_unsafe_path",
            "format": raw_path.as_posix(),
            "resolved_path": resolved_path.as_posix(),
            "original_path": original_path.as_posix(),
            "supported_scope": (
                "scalar $TAG interpolation for -srcfile may resolve only to local "
                "paths under the original file directory and must not include parent "
                "directory traversal"
            ),
            "evidence_ids": ["public.read.srcfile.docs"],
        },
    )


def _public_source_file_tag_path_is_bounded(
    resolved_path: Path,
    original_path: Path,
) -> bool:
    if ".." in resolved_path.parts:
        return False
    original_directory = original_path.parent.resolve(strict=False)
    resolved_absolute = (
        resolved_path if resolved_path.is_absolute() else original_directory / resolved_path
    ).resolve(strict=False)
    try:
        return (
            os.path.commonpath((original_directory.as_posix(), resolved_absolute.as_posix()))
            == original_directory.as_posix()
        )
    except ValueError:
        return False


def _paths_with_public_file_order(
    paths: tuple[Path, ...],
    request: MetadataReadRequest,
) -> tuple[Path, ...]:
    ordered_paths = list(paths)
    if request.file_order:

        def compare_paths(left: Path, right: Path) -> int:
            return _compare_file_order_paths(left, right, request)

        ordered_paths.sort(key=cmp_to_key(compare_paths))
    return tuple(ordered_paths)


def _public_file_order_is_safe_path_order(order: PublicReadFileOrder) -> bool:
    return _normalized_public_file_order_tag(order.tag) in {"filename", "sourcefile"}


def _normalized_public_file_order_tag(tag: str) -> str:
    return tag.removeprefix("-").rsplit(":", 1)[-1].lower()


def _public_file_order_path_key(path: Path, order: PublicReadFileOrder) -> str:
    normalized_tag = _normalized_public_file_order_tag(order.tag)
    if normalized_tag == "sourcefile":
        return path.as_posix().casefold()
    return path.name.casefold()


def _compare_file_order_paths(
    left: Path,
    right: Path,
    request: MetadataReadRequest,
) -> int:
    for order in request.file_order:
        comparison = _compare_file_order_values(
            _public_file_order_value(left, order, request),
            _public_file_order_value(right, order, request),
        )
        if comparison:
            return -comparison if order.tag.startswith("-") else comparison
    return (left.as_posix() > right.as_posix()) - (left.as_posix() < right.as_posix())


def _public_file_order_value(
    path: Path,
    order: PublicReadFileOrder,
    request: MetadataReadRequest,
) -> TagValue:
    source_path, source_diagnostics = _public_read_source_file_path(path, request)
    if source_diagnostics:
        return None
    if _public_file_order_is_safe_path_order(order):
        return _public_file_order_path_key(source_path, order)
    if not source_path.exists():
        return None
    requested_tag = requested_tag_from_arg(f"-{order.tag.removeprefix('-')}")
    if requested_tag is None:
        return None
    try:
        graph = _build_public_read_graph_for_request(source_path, request)
    except OSError:
        return None
    graph = _graph_with_public_user_params(graph, request, path)
    graph, _diagnostics = _graph_with_public_alternate_file_reads(
        graph,
        request,
        format_base_path=path,
    )
    tags = find_graph_tags(
        graph,
        requested_tag,
        RenderOptions(group_names=False, duplicate_tags=False, group_family=1),
    )
    if not tags:
        return None
    return tags[0].value


def _compare_file_order_values(left: TagValue, right: TagValue) -> int:
    left_sort = _file_order_sort_value(left)
    right_sort = _file_order_sort_value(right)
    if left_sort.missing and right_sort.missing:
        return 0
    if left_sort.missing:
        return 1
    if right_sort.missing:
        return -1
    if left_sort.numeric and right_sort.numeric:
        left_number = float(left_sort.value)
        right_number = float(right_sort.value)
        return (left_number > right_number) - (left_number < right_number)
    if left_sort.numeric:
        return -1
    if right_sort.numeric:
        return 1
    left_text = str(left_sort.value)
    right_text = str(right_sort.value)
    return (left_text > right_text) - (left_text < right_text)


@dataclass(frozen=True)
class _FileOrderSortValue:
    value: str | float
    numeric: bool
    missing: bool = False


def _file_order_sort_value(value: TagValue) -> _FileOrderSortValue:
    if value is None or isinstance(value, BinaryTagValue):
        return _FileOrderSortValue("~", False, missing=True)
    if isinstance(value, bool):
        return _FileOrderSortValue(str(value), False)
    if isinstance(value, int | float):
        return _FileOrderSortValue(float(value), True)
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    text = str(value)
    try:
        return _FileOrderSortValue(float(text), True)
    except ValueError:
        return _FileOrderSortValue(text.casefold(), False)


def _scan_read_directory(
    root: Path,
    recursive: bool,
    recurse_dot_directories: bool,
    ignore_directories: tuple[str, ...],
    extension_filters: tuple[ExtensionFilter, ...],
) -> tuple[Path, ...]:
    if _directory_is_ignored(root, ignore_directories):
        return ()
    paths: list[Path] = []
    for candidate in root.iterdir():
        if candidate.is_dir():
            if (
                recursive
                and (recurse_dot_directories or not candidate.name.startswith("."))
                and not _directory_is_ignored(candidate, ignore_directories)
            ):
                paths.extend(
                    _scan_read_directory(
                        candidate,
                        recursive=True,
                        recurse_dot_directories=recurse_dot_directories,
                        ignore_directories=ignore_directories,
                        extension_filters=extension_filters,
                    )
                )
            continue
        if (
            candidate.is_file()
            and not _file_is_ignored(candidate, ignore_directories)
            and _is_public_directory_read_file(candidate, extension_filters)
        ):
            paths.append(candidate)
    return tuple(paths)


def _directory_is_ignored(path: Path, ignore_directories: tuple[str, ...]) -> bool:
    if path.is_symlink() and "SYMLINKS" in ignore_directories:
        return True
    path_values = _directory_ignore_path_values(path)
    for ignored in ignore_directories:
        if ignored in {"HIDDEN", "SYMLINKS"}:
            continue
        if ignored == path.name or ignored in path_values:
            return True
    return False


def _directory_ignore_path_values(path: Path) -> frozenset[str]:
    return frozenset(
        {
            str(path),
            path.as_posix(),
            str(path.resolve(strict=False)),
            path.resolve(strict=False).as_posix(),
        }
    )


def _file_is_ignored(path: Path, ignore_directories: tuple[str, ...]) -> bool:
    return "HIDDEN" in ignore_directories and path.name.startswith(".")


def _is_public_directory_read_file(
    path: Path,
    extension_filters: tuple[ExtensionFilter, ...],
) -> bool:
    if not extension_filters:
        return path.suffix.lower() in PUBLIC_DIRECTORY_READ_EXTENSIONS

    accepted = _extension_filter_acceptance(path, extension_filters)
    if accepted == "rejected":
        return False
    if accepted == "specific":
        return True
    return path.suffix.lower() in PUBLIC_DIRECTORY_READ_EXTENSIONS


def _extension_filter_acceptance(
    path: Path,
    extension_filters: tuple[ExtensionFilter, ...],
) -> Literal["specific", "default", "rejected"]:
    lookup: dict[str, bool] = {}
    has_include_only_filter = False
    for extension_filter in extension_filters:
        normalized = _normalized_extension_filter_value(extension_filter.extension)
        if extension_filter.mode == "exclude":
            lookup[normalized] = False
            continue
        lookup[normalized] = True
        if extension_filter.mode == "include":
            has_include_only_filter = True

    extension = _path_extension_filter_value(path)
    if extension in lookup:
        return "specific" if lookup[extension] else "rejected"
    if "*" in lookup:
        return "specific" if lookup["*"] else "rejected"
    if has_include_only_filter:
        return "rejected"
    return "default"


def _path_extension_filter_value(path: Path) -> str:
    suffix = path.suffix
    return suffix[1:].upper() if suffix.startswith(".") else suffix.upper()


def _normalized_extension_filter_value(extension: str) -> str:
    return extension.removeprefix(".").upper()


def _expand_public_read_wildcards(
    graph: ReadGraph,
    requested_tags: tuple[str, ...],
    path: Path,
    render: OutputRenderRequest,
) -> tuple[tuple[str, ...], tuple[Diagnostic, ...]]:
    if not requested_tags:
        return requested_tags, ()

    expanded_tags: list[str] = []
    diagnostics: list[Diagnostic] = []
    for requested_tag in requested_tags:
        expansion, diagnostic = _expand_public_read_wildcard(
            graph,
            requested_tag,
            path,
            render,
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        expanded_tags.extend(expansion)
    return tuple(expanded_tags), tuple(diagnostics)


def _graph_with_public_read_exclusions(
    graph: ReadGraph,
    exclusions: tuple[PublicReadTagExclusion, ...],
) -> ReadGraph:
    if not exclusions:
        return graph

    tags = [tag for tag in graph.tags if not _public_read_tag_is_excluded(tag, exclusions)]
    if len(tags) == len(graph.tags):
        return graph
    return replace(graph, tags=tags)


def _render_tags_with_public_read_exclusions(
    graph: ReadGraph,
    excluded_graph: ReadGraph,
    render_tags: tuple[str, ...],
    exclusions: tuple[PublicReadTagExclusion, ...],
    render: OutputRenderRequest,
) -> tuple[str, ...]:
    if not exclusions or not render_tags:
        return render_tags

    options = RenderOptions(
        group_names=render.include_group_names or render.format == "xml",
        duplicate_tags=_public_render_extracts_duplicate_tags(render),
        include_unknown_tags=True,
    )
    kept: list[str] = []
    for render_tag in render_tags:
        requested_tag = requested_tag_from_arg(_renderer_tag_arg(render_tag))
        if requested_tag is None:
            kept.append(render_tag)
            continue
        original_matches = find_graph_tags(graph, requested_tag, options)
        remaining_matches = find_graph_tags(excluded_graph, requested_tag, options)
        if original_matches and not remaining_matches:
            continue
        kept.append(render_tag)
    return tuple(kept)


def _render_tags_with_public_output_suppression(
    graph: ReadGraph,
    visible_graph: ReadGraph,
    render_tags: tuple[str, ...],
    render: OutputRenderRequest,
) -> tuple[str, ...]:
    if not render_tags or len(graph.tags) == len(visible_graph.tags):
        return render_tags

    options = RenderOptions(
        group_names=render.include_group_names or render.format == "xml",
        duplicate_tags=_public_render_extracts_duplicate_tags(render),
        include_unknown_tags=True,
    )
    kept: list[str] = []
    for render_tag in render_tags:
        requested_tag = requested_tag_from_arg(_renderer_tag_arg(render_tag))
        if requested_tag is None:
            kept.append(render_tag)
            continue
        original_matches = find_graph_tags(graph, requested_tag, options)
        visible_matches = find_graph_tags(visible_graph, requested_tag, options)
        if original_matches and not visible_matches:
            continue
        kept.append(render_tag)
    return tuple(kept)


def _graph_with_public_binary_suppression(
    graph: ReadGraph,
    render: OutputRenderRequest,
) -> ReadGraph:
    if not render.suppress_binary_tags:
        return graph

    tags = [tag for tag in graph.tags if not _public_tag_value_contains_binary(tag.value)]
    if len(tags) == len(graph.tags):
        return graph
    return replace(graph, tags=tags)


def _public_tag_value_contains_binary(value: TagValue) -> bool:
    if isinstance(value, BinaryTagValue):
        return True
    if isinstance(value, list):
        return any(_public_tag_value_contains_binary(item) for item in value)
    return False


def _render_tags_with_public_duplicate_instances(
    graph: ReadGraph,
    render_tags: tuple[str, ...],
    render: OutputRenderRequest,
    source_tags: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if (
        not render_tags
        or render.format == "xml"
        or not _public_render_extracts_duplicate_tags(render)
    ):
        return render_tags

    expanded: list[str] = []
    for render_tag in render_tags:
        requested_instance_tag = _public_duplicate_instance_render_tag_for_source_selector(
            render_tag,
            source_tags,
        )
        if requested_instance_tag is not None:
            expanded.append(requested_instance_tag)
            continue
        requested_tag = requested_tag_from_arg(_renderer_tag_arg(render_tag))
        if requested_tag is None:
            expanded.append(render_tag)
            continue
        if _render_tag_can_use_exiftool_family4_output_labels(requested_tag, render):
            expanded.append(render_tag)
            continue
        if requested_tag.group is not None and _is_public_duplicate_instance_group_name(
            requested_tag.group
        ):
            expanded.append(render_tag)
            continue
        instance_tags = _public_duplicate_instance_render_tags(graph, requested_tag)
        if instance_tags:
            expanded.extend(instance_tags)
            continue
        expanded.append(render_tag)
    return tuple(dict.fromkeys(expanded))


def _public_duplicate_instance_render_tag_for_source_selector(
    render_tag: str,
    source_tags: tuple[str, ...],
) -> str | None:
    requested_tag = requested_tag_from_arg(_renderer_tag_arg(render_tag))
    if requested_tag is None:
        return None
    for source_tag in source_tags:
        selector = parse_public_read_tag_selector(source_tag)
        if selector.tag_wildcard or selector.all_tag:
            continue
        if selector.tag_name.casefold() != requested_tag.name.casefold():
            continue
        instance_number = _public_duplicate_group_selector_for_selector(selector)
        if instance_number is None:
            continue
        return f"{_public_duplicate_instance_key_for_ordinal(instance_number)}:{selector.tag_name}"
    return None


def _public_duplicate_group_selector_for_selector(
    selector: PublicReadTagSelector,
) -> int | None:
    for group in selector.group_chain:
        if group.duplicate_instance_number is not None:
            return group.duplicate_instance_number
    return None


def _render_tag_can_use_exiftool_family4_output_labels(
    requested_tag: RequestedTag,
    render: OutputRenderRequest,
) -> bool:
    if not render.include_group_names or render.group_name_families != (4,):
        return False
    selector = parse_public_read_tag_selector(format_requested_tag(requested_tag))
    if selector.tag_wildcard or selector.all_tag:
        return False
    return requested_tag.group is None or not _is_public_duplicate_instance_group_name(
        requested_tag.group
    )


def _public_duplicate_instance_render_tags(
    graph: ReadGraph,
    requested_tag: RequestedTag,
) -> tuple[str, ...]:
    options = RenderOptions(group_names=True, duplicate_tags=True)
    matches = find_graph_tags(graph, requested_tag, options)
    expanded: list[str] = []
    for tag in matches:
        instance_key = _public_duplicate_instance_key(tag)
        if instance_key is None:
            continue
        expanded.append(f"{instance_key}:{tag.name}")
    if len(expanded) <= 1:
        return ()
    return tuple(expanded)


def _public_read_tag_is_excluded(
    tag: ReadTag,
    exclusions: tuple[PublicReadTagExclusion, ...],
) -> bool:
    return any(
        _public_read_exclusion_matches_tag(parse_public_read_tag_selector(exclusion.raw), tag)
        for exclusion in exclusions
    )


def _public_read_exclusion_matches_tag(
    selector: PublicReadTagSelector,
    tag: ReadTag,
) -> bool:
    if not _public_read_exclusion_tag_name_matches(selector, tag.name):
        return False
    if not selector.group_chain:
        return True
    group = selector.group_chain[0]
    if group.wildcard_mode == "all_instances":
        return True
    if group.family is not None:
        family_group = _tag_provenance_family_group(tag.provenance, group.family)
        return family_group is not None and family_group.lower() == group.name.lower()
    return group.name.lower() in {
        candidate.lower()
        for candidate in (
            tag.provenance.group,
            tag.provenance.family_0_group,
            tag.provenance.family_1_group,
            tag.provenance.family_2_group,
            tag.provenance.family_4_instance_group,
        )
        if candidate is not None
    }


def _public_read_exclusion_tag_name_matches(
    selector: PublicReadTagSelector,
    tag_name: str,
) -> bool:
    if selector.all_tag:
        return True
    return _public_wildcard_matches(selector.tag_name, tag_name)


def _expand_public_read_wildcard(
    graph: ReadGraph,
    requested_tag: str,
    path: Path,
    render: OutputRenderRequest,
) -> tuple[tuple[str, ...], Diagnostic | None]:
    selector = parse_public_read_tag_selector(requested_tag)
    if selector.has_group_chain:
        return _expand_public_read_group_chain_selector(graph, requested_tag, path, selector)
    if selector.has_duplicate_instance_selector:
        return _expand_public_read_duplicate_instance_selector(graph, requested_tag, path, selector)
    if selector.has_all_instances_group:
        return _expand_public_read_all_instance_selector(graph, requested_tag, path, selector)
    if selector.has_family_selector:
        return _expand_public_read_family_selector(graph, requested_tag, path, selector, render)
    if not selector.tag_wildcard:
        return (requested_tag,), None

    matched_tags: list[str] = []
    seen: set[str] = set()
    duplicate_matches: list[ReadTag] = []
    has_group_selector = bool(selector.group_chain)
    group_key = selector.group_chain[0].name.lower() if selector.group_chain else None
    pattern = "*" if selector.all_tag else selector.tag_name
    for graph_tag in graph.tags:
        if group_key is not None and graph_tag.provenance.group.lower() != group_key:
            continue
        if not _public_wildcard_matches(pattern, graph_tag.name):
            continue
        expanded = (
            f"{graph_tag.provenance.group}:{graph_tag.name}"
            if has_group_selector
            else graph_tag.name
        )
        if expanded in seen:
            if len(duplicate_matches) < 8:
                duplicate_matches.append(graph_tag)
            continue
        seen.add(expanded)
        matched_tags.append(expanded)
        if len(matched_tags) >= MAX_PUBLIC_WILDCARD_EXPANSION_TAGS:
            return tuple(matched_tags), _bounded_public_wildcard_diagnostic(path, requested_tag)
    if not matched_tags:
        return (requested_tag,), None
    if duplicate_matches and _public_render_extracts_duplicate_tags(render):
        duplicate_expansion, duplicate_diagnostic = (
            _expand_public_read_duplicate_matches_from_wildcard(
                graph,
                requested_tag,
                path,
                selector,
            )
        )
        if duplicate_expansion:
            return duplicate_expansion, duplicate_diagnostic
        return (
            tuple(matched_tags),
            _public_wildcard_duplicate_matches_collapsed_diagnostic(
                path,
                requested_tag,
                duplicate_matches,
            ),
        )
    return tuple(matched_tags), None


def _expand_public_read_duplicate_instance_selector(
    graph: ReadGraph,
    requested_tag: str,
    path: Path,
    selector: PublicReadTagSelector,
) -> tuple[tuple[str, ...], Diagnostic | None]:
    if len(selector.group_chain) != 1:
        return (), _unsupported_public_group_family_wildcard_diagnostic(
            path,
            requested_tag,
            selector,
        )
    group = selector.group_chain[0]
    if group.family is not None:
        return (), _unsupported_public_duplicate_instance_wildcard_diagnostic(
            path,
            requested_tag,
            selector,
        )
    if group.duplicate_instance_number is None:
        return (requested_tag,), None

    pattern = "*" if selector.all_tag else selector.tag_name
    matched_tags: list[str] = []
    missing_provenance_tags: list[str] = []
    for graph_tag in graph.tags:
        if not _public_wildcard_matches(pattern, graph_tag.name):
            continue
        instance_key = _public_duplicate_instance_key(graph_tag)
        if instance_key is None:
            if len(missing_provenance_tags) < 8:
                missing_provenance_tags.append(f"{graph_tag.provenance.group}:{graph_tag.name}")
            continue
        if instance_key != _public_duplicate_instance_key_for_ordinal(
            group.duplicate_instance_number
        ):
            continue
        matched_tags.append(f"{instance_key}:{graph_tag.name}")
        if len(matched_tags) >= MAX_PUBLIC_WILDCARD_EXPANSION_TAGS:
            return tuple(matched_tags), _bounded_public_wildcard_diagnostic(path, requested_tag)

    if missing_provenance_tags:
        return (), _unsupported_public_duplicate_instance_wildcard_diagnostic(
            path,
            requested_tag,
            selector,
        )
    if not matched_tags:
        return (requested_tag,), None
    return tuple(matched_tags), None


def _expand_public_read_all_instance_selector(
    graph: ReadGraph,
    requested_tag: str,
    path: Path,
    selector: PublicReadTagSelector,
) -> tuple[tuple[str, ...], Diagnostic | None]:
    if len(selector.group_chain) != 1:
        return (), _unsupported_public_group_family_wildcard_diagnostic(
            path,
            requested_tag,
            selector,
        )

    pattern = "*" if selector.all_tag else selector.tag_name
    matched_tags: list[str] = []
    missing_provenance_tags: list[str] = []
    for graph_tag in graph.tags:
        if not _public_wildcard_matches(pattern, graph_tag.name):
            continue
        instance_key = _public_duplicate_instance_key(graph_tag)
        if instance_key is None:
            if len(missing_provenance_tags) < 8:
                missing_provenance_tags.append(f"{graph_tag.provenance.group}:{graph_tag.name}")
            continue
        matched_tags.append(f"{instance_key}:{graph_tag.name}")
        if len(matched_tags) >= MAX_PUBLIC_WILDCARD_EXPANSION_TAGS:
            return tuple(matched_tags), _bounded_public_wildcard_diagnostic(path, requested_tag)

    if missing_provenance_tags:
        return (), _unsupported_public_group_wildcard_diagnostic(
            path,
            requested_tag,
            selector,
        )
    if not matched_tags:
        return (requested_tag,), None
    return tuple(matched_tags), None


def _expand_public_read_duplicate_matches_from_wildcard(
    graph: ReadGraph,
    requested_tag: str,
    path: Path,
    selector: PublicReadTagSelector,
) -> tuple[tuple[str, ...], Diagnostic | None]:
    pattern = "*" if selector.all_tag else selector.tag_name
    matched_tags: list[str] = []
    missing_provenance_tags: list[str] = []
    for graph_tag in graph.tags:
        if selector.group_chain:
            group = selector.group_chain[0]
            if graph_tag.provenance.group.lower() != group.name.lower():
                continue
        if not _public_wildcard_matches(pattern, graph_tag.name):
            continue
        instance_key = _public_duplicate_instance_key(graph_tag)
        if instance_key is None:
            if len(missing_provenance_tags) < 8:
                missing_provenance_tags.append(f"{graph_tag.provenance.group}:{graph_tag.name}")
            continue
        matched_tags.append(f"{instance_key}:{graph_tag.name}")
        if len(matched_tags) >= MAX_PUBLIC_WILDCARD_EXPANSION_TAGS:
            return tuple(matched_tags), _bounded_public_wildcard_diagnostic(path, requested_tag)

    if missing_provenance_tags:
        return (), _missing_public_duplicate_instance_provenance_diagnostic(
            path,
            requested_tag,
            selector,
            missing_provenance_tags,
        )
    return tuple(matched_tags), None


def _expand_public_read_group_chain_selector(
    graph: ReadGraph,
    requested_tag: str,
    path: Path,
    selector: PublicReadTagSelector,
) -> tuple[tuple[str, ...], Diagnostic | None]:
    pattern = "*" if selector.all_tag else selector.tag_name
    matched_tags: list[str] = []
    seen: set[str] = set()
    missing_provenance_tags: list[str] = []
    missing_family: PublicReadGroupFamily | None = None
    missing_duplicate_provenance = False

    for graph_tag in graph.tags:
        if not _public_wildcard_matches(pattern, graph_tag.name):
            continue
        match_result = _public_read_group_chain_match_result(selector, graph_tag)
        if match_result.missing_duplicate_provenance:
            missing_duplicate_provenance = True
            if len(missing_provenance_tags) < 8:
                missing_provenance_tags.append(f"{graph_tag.provenance.group}:{graph_tag.name}")
            continue
        if match_result.missing_family is not None:
            missing_family = match_result.missing_family
            if len(missing_provenance_tags) < 8:
                missing_provenance_tags.append(f"{graph_tag.provenance.group}:{graph_tag.name}")
            continue
        if not match_result.matches:
            continue
        expanded = f"{graph_tag.provenance.group}:{graph_tag.name}"
        if expanded in seen:
            continue
        seen.add(expanded)
        matched_tags.append(expanded)
        if len(matched_tags) >= MAX_PUBLIC_WILDCARD_EXPANSION_TAGS:
            return tuple(matched_tags), _bounded_public_wildcard_diagnostic(path, requested_tag)

    if missing_family is not None:
        return (), _missing_public_group_family_provenance_diagnostic(
            path,
            requested_tag,
            selector,
            missing_family,
            missing_provenance_tags,
        )
    if missing_duplicate_provenance:
        return (), _missing_public_duplicate_instance_provenance_diagnostic(
            path,
            requested_tag,
            selector,
            missing_provenance_tags,
        )
    if not matched_tags:
        return (requested_tag,), None
    return tuple(matched_tags), None


@dataclass(frozen=True)
class _PublicReadGroupChainMatchResult:
    matches: bool
    missing_family: PublicReadGroupFamily | None = None
    missing_duplicate_provenance: bool = False


def _public_read_group_chain_match_result(
    selector: PublicReadTagSelector,
    tag: ReadTag,
) -> _PublicReadGroupChainMatchResult:
    for group in selector.group_chain:
        group_result = _public_read_group_selector_match_result(group, tag)
        if group_result.missing_duplicate_provenance:
            return group_result
        if group_result.missing_family is not None:
            return group_result
        if not group_result.matches:
            return group_result
    return _PublicReadGroupChainMatchResult(matches=True)


def _public_read_group_selector_match_result(
    group: PublicReadGroupSelector,
    tag: ReadTag,
) -> _PublicReadGroupChainMatchResult:
    if group.wildcard_mode == "all_instances":
        return _PublicReadGroupChainMatchResult(matches=True)
    if group.duplicate_instance_number is not None:
        duplicate_key = _public_duplicate_instance_key(tag)
        if duplicate_key is None:
            return _PublicReadGroupChainMatchResult(
                matches=False,
                missing_duplicate_provenance=True,
            )
        requested_key = _public_duplicate_instance_key_for_ordinal(group.duplicate_instance_number)
        return _PublicReadGroupChainMatchResult(
            matches=duplicate_key.lower() == requested_key.lower()
        )
    if group.family is not None:
        family_group = _tag_provenance_family_group(tag.provenance, group.family)
        if family_group is None:
            if _public_read_group_selector_matches_any_populated_group(group, tag):
                return _PublicReadGroupChainMatchResult(
                    matches=False,
                    missing_family=group.family,
                )
            return _PublicReadGroupChainMatchResult(matches=False)
        return _PublicReadGroupChainMatchResult(matches=family_group.lower() == group.name.lower())
    return _PublicReadGroupChainMatchResult(
        matches=_public_read_group_selector_matches_any_populated_group(group, tag)
    )


def _public_read_group_selector_matches_any_populated_group(
    group: PublicReadGroupSelector,
    tag: ReadTag,
) -> bool:
    normalized_group = group.name.lower()
    return normalized_group in {
        candidate.lower() for candidate in _public_read_populated_group_names(tag.provenance)
    }


def _public_read_populated_group_names(provenance: TagProvenance) -> tuple[str, ...]:
    groups: list[str] = []
    groups.extend(
        group
        for group in (
            provenance.group,
            provenance.family_0_group,
            provenance.family_1_group,
            provenance.family_2_group,
            _public_duplicate_instance_key_for_provenance(provenance),
        )
        if group is not None
    )
    return tuple(groups)


def _public_duplicate_instance_key(tag: ReadTag) -> str | None:
    return _public_duplicate_instance_key_for_provenance(tag.provenance)


def _public_duplicate_instance_key_for_provenance(
    provenance: TagProvenance,
) -> str | None:
    if provenance.family_4_instance_group is None or provenance.duplicate_instance_ordinal is None:
        return None
    expected = _public_duplicate_instance_key_for_ordinal(provenance.duplicate_instance_ordinal)
    if (
        _normalized_public_duplicate_instance_group(provenance.family_4_instance_group)
        != expected.lower()
    ):
        return None
    return expected


def _public_duplicate_instance_key_for_ordinal(ordinal: int) -> str:
    if ordinal <= 0:
        return "Copy0"
    return f"Copy{ordinal}"


def _public_render_extracts_duplicate_tags(render: OutputRenderRequest) -> bool:
    if (
        render.allow_duplicate_tags
        or render.extract_embedded_level > 0
        or render.format in {"xml", "php"}
    ):
        return True
    return render.format == "json" and 4 in render.group_name_families


def _normalized_public_duplicate_instance_group(group: str) -> str:
    return "copy0" if group == "" else group.lower()


def _graph_with_public_duplicate_instance_projection(
    graph: ReadGraph,
    render_tags: tuple[str, ...],
) -> ReadGraph:
    requested_instance_keys = {
        group.lower()
        for tag in render_tags
        if ":" in tag
        for group, _ in (tag.split(":", 1),)
        if _is_public_duplicate_instance_group_name(group)
    }
    if not requested_instance_keys:
        return graph

    projected_tags: list[ReadTag] = []
    for tag in graph.tags:
        instance_key = _public_duplicate_instance_key(tag)
        if instance_key is None or instance_key.lower() not in requested_instance_keys:
            continue
        projected_tags.append(
            replace(
                tag,
                provenance=replace(
                    tag.provenance,
                    group=instance_key,
                    family_1_group=instance_key,
                    family_4_instance_group=instance_key,
                ),
            )
        )
    if not projected_tags:
        return graph
    return replace(graph, tags=[*graph.tags, *projected_tags])


def _graph_with_public_output_group_projection(
    graph: ReadGraph,
    render: OutputRenderRequest,
) -> ReadGraph:
    if not render.include_group_names or not render.group_name_families:
        return graph

    colliding_keys = _public_output_projection_colliding_keys(graph)
    if not colliding_keys:
        return graph

    projected_tags: list[ReadTag] = []
    changed = False
    for tag in graph.tags:
        if (tag.provenance.group, tag.name) not in colliding_keys:
            projected_tags.append(tag)
            continue
        group = _output_group_label_for_tag_provenance(tag.provenance, render.group_name_families)
        if group is None or group == tag.provenance.group:
            projected_tags.append(tag)
            continue
        projected_tags.append(
            replace(
                tag,
                provenance=replace(
                    tag.provenance,
                    group=group,
                    family_0_group=tag.provenance.family_0_group or tag.provenance.group,
                    family_1_group=tag.provenance.family_1_group or tag.provenance.group,
                    family_2_group=tag.provenance.family_2_group or tag.provenance.group,
                ),
            )
        )
        changed = True
    if not changed:
        return graph
    return replace(graph, tags=projected_tags)


def _public_output_projection_colliding_keys(graph: ReadGraph) -> frozenset[tuple[str, str]]:
    counts: dict[tuple[str, str], int] = {}
    for tag in graph.tags:
        key = (tag.provenance.group, tag.name)
        counts[key] = counts.get(key, 0) + 1
    return frozenset(key for key, count in counts.items() if count > 1)


def _is_public_duplicate_instance_group_name(group: str) -> bool:
    normalized = group.lower()
    return normalized == "copy0" or (normalized.startswith("copy") and normalized[4:].isdecimal())


def _expand_public_read_family_selector(
    graph: ReadGraph,
    requested_tag: str,
    path: Path,
    selector: PublicReadTagSelector,
    render: OutputRenderRequest,
) -> tuple[tuple[str, ...], Diagnostic | None]:
    if len(selector.group_chain) != 1:
        return (), _unsupported_public_group_family_wildcard_diagnostic(
            path,
            requested_tag,
            selector,
        )
    group = selector.group_chain[0]
    if group.family is None:
        return (requested_tag,), None

    pattern = "*" if selector.all_tag else selector.tag_name
    matched_tags: list[str] = []
    seen: set[str] = set()
    duplicate_matches: list[ReadTag] = []
    missing_provenance_tags: list[str] = []
    for graph_tag in graph.tags:
        if not _public_wildcard_matches(pattern, graph_tag.name):
            continue
        family_group = _tag_provenance_family_group(graph_tag.provenance, group.family)
        if family_group is None:
            if graph_tag.provenance.group.lower() == group.name.lower():
                missing_provenance_tags.append(f"{graph_tag.provenance.group}:{graph_tag.name}")
            continue
        if family_group.lower() != group.name.lower():
            continue
        expanded = f"{graph_tag.provenance.group}:{graph_tag.name}"
        if expanded in seen:
            if len(duplicate_matches) < 8:
                duplicate_matches.append(graph_tag)
            continue
        seen.add(expanded)
        matched_tags.append(expanded)
        if len(matched_tags) >= MAX_PUBLIC_WILDCARD_EXPANSION_TAGS:
            return tuple(matched_tags), _bounded_public_wildcard_diagnostic(path, requested_tag)

    if missing_provenance_tags:
        return (), _missing_public_group_family_provenance_diagnostic(
            path,
            requested_tag,
            selector,
            group.family,
            missing_provenance_tags,
        )
    if not matched_tags:
        return (requested_tag,), None
    if duplicate_matches and _public_render_extracts_duplicate_tags(render):
        return (
            tuple(matched_tags),
            _public_wildcard_duplicate_matches_collapsed_diagnostic(
                path,
                requested_tag,
                duplicate_matches,
            ),
        )
    return tuple(matched_tags), None


def _tag_provenance_family_group(
    provenance: TagProvenance,
    family: PublicReadGroupFamily,
) -> str | None:
    match family:
        case 0:
            if (
                provenance.family_0_group is None
                and provenance.group in BOUNDED_EXIF_FAMILY_1_GROUPS
            ):
                return "EXIF"
            return provenance.family_0_group
        case 1:
            return provenance.family_1_group
        case 2:
            return provenance.family_2_group
        case 4:
            return _public_duplicate_instance_key_for_provenance(provenance)
    return None


def parse_public_read_tag_selector(requested_tag: str) -> PublicReadTagSelector:
    raw = requested_tag.removeprefix("-")
    tag_spec = raw.removesuffix("#")
    parts = tag_spec.split(":")
    tag_name = parts[-1]
    return PublicReadTagSelector(
        raw=raw,
        tag_name=tag_name,
        group_chain=tuple(_parse_public_read_group_selector(part) for part in parts[:-1] if part),
        tag_wildcard=_is_public_tag_wildcard(tag_name),
        all_tag=tag_name.lower() in {"all", "*"},
        value_conversion_disabled=raw.endswith("#"),
    )


def _parse_public_read_group_selector(group: str) -> PublicReadGroupSelector:
    family: PublicReadGroupFamily | None = None
    name = group
    if name and name[0].isdigit():
        family = _public_read_group_family_from_prefix(name[0])
        name = name[1:]
    normalized = name.lower()
    duplicate_mode: PublicReadDuplicateInstanceMode = "default"
    duplicate_instance_number: int | None = None
    if normalized == "copy0":
        duplicate_mode = "primary"
        duplicate_instance_number = 0
    elif normalized.startswith("copy") and normalized[4:].isdecimal():
        duplicate_mode = "copy"
        duplicate_instance_number = int(normalized[4:])
    return PublicReadGroupSelector(
        raw=group,
        name=name,
        family=family,
        wildcard_mode="all_instances" if normalized in {"all", "*"} else "literal",
        duplicate_instance_mode=duplicate_mode,
        duplicate_instance_number=duplicate_instance_number,
    )


def _public_read_group_family_from_prefix(
    prefix: str,
) -> PublicReadGroupFamily | None:
    match prefix:
        case "0":
            return 0
        case "1":
            return 1
        case "2":
            return 2
        case "4":
            return 4
    return None


def _is_public_tag_wildcard(tag_name: str) -> bool:
    return tag_name.lower() in {"all", "*"} or any(marker in tag_name for marker in ("*", "?"))


def _public_wildcard_matches(pattern: str, tag_name: str) -> bool:
    return fnmatchcase(tag_name.lower(), pattern.lower())


def _unsupported_public_group_wildcard_diagnostic(
    path: Path,
    requested_tag: str,
    selector: PublicReadTagSelector,
) -> Diagnostic:
    return Diagnostic(
        code="unsupported_group_wildcard_tag",
        message=(
            f"{path}: grouped wildcard tag selection is not supported by the "
            f"bounded public read graph expansion: {requested_tag}."
        ),
        details={
            "requested_tag": requested_tag,
            "selector": _public_read_tag_selector_to_json_value(selector),
            "unsupported_semantics": "all_group_instances",
            "supported_scope": (
                "literal groups plus All, *, ?, or * in tag names matched only "
                "against the current decoded read graph"
            ),
            "evidence_ids": [
                (
                    "../exiftool/exiftool documents All as a special tag name "
                    "and documents ? and * wildcards in tag names."
                ),
                (
                    "../exiftool/exiftool documents * or All group names as a "
                    "special all-instances mode; ExifModern does not implement "
                    "that grouped wildcard mode in this bounded read graph slice."
                ),
            ],
        },
    )


def _unsupported_public_group_family_wildcard_diagnostic(
    path: Path,
    requested_tag: str,
    selector: PublicReadTagSelector,
) -> Diagnostic:
    return Diagnostic(
        code="unsupported_group_family_wildcard_tag",
        message=(
            f"{path}: group-family or chained group wildcard tag selection is not "
            f"supported by the bounded public read graph expansion: {requested_tag}."
        ),
        details={
            "requested_tag": requested_tag,
            "group_selector": ":".join(group.raw for group in selector.group_chain),
            "selector": _public_read_tag_selector_to_json_value(selector),
            "unsupported_semantics": (
                "family_number_or_multiple_group_selectors_without_family_provenance"
            ),
            "supported_scope": (
                "one literal decoded read-graph group plus All, *, ?, or * in the tag name"
            ),
            "evidence_ids": [
                (
                    "../exiftool/lib/Image/ExifTool.pod documents optional "
                    "colon-separated group names and leading family numbers."
                ),
                (
                    "../exiftool/lib/Image/ExifTool.pm GroupMatches splits "
                    "group specs on colons and handles leading family numbers."
                ),
            ],
        },
    )


def _missing_public_group_family_provenance_diagnostic(
    path: Path,
    requested_tag: str,
    selector: PublicReadTagSelector,
    family: PublicReadGroupFamily,
    missing_provenance_tags: list[str],
) -> Diagnostic:
    missing_examples: JsonArray = []
    missing_examples.extend(missing_provenance_tags[:8])
    return Diagnostic(
        code="missing_group_family_provenance",
        message=(
            f"{path}: group-family selector {requested_tag} matched decoded tags "
            f"whose family-{family} provenance is not populated."
        ),
        details={
            "requested_tag": requested_tag,
            "selector": _public_read_tag_selector_to_json_value(selector),
            "family": family,
            "missing_provenance_examples": missing_examples,
            "unsupported_semantics": "family_selector_without_populated_provenance",
            "supported_scope": (
                "single explicit family 0, 1, or 2 group selectors are expanded only "
                "for decoded tags that already carry the requested family provenance"
            ),
            "evidence_ids": [
                (
                    "../exiftool/lib/Image/ExifTool.pm GetGroup guarantees "
                    "families 0-2 after group construction."
                ),
                (
                    "../exiftool/lib/Image/ExifTool.pm GroupMatches uses "
                    "GetGroup(tag, -1) and checks a leading family number "
                    "against that family slot."
                ),
            ],
        },
    )


def _unsupported_public_duplicate_instance_wildcard_diagnostic(
    path: Path,
    requested_tag: str,
    selector: PublicReadTagSelector,
) -> Diagnostic:
    return Diagnostic(
        code="unsupported_duplicate_instance_wildcard_tag",
        message=(
            f"{path}: duplicate instance group selection is not supported by the "
            f"bounded public read graph expansion: {requested_tag}."
        ),
        details={
            "requested_tag": requested_tag,
            "selector": _public_read_tag_selector_to_json_value(selector),
            "unsupported_semantics": "family_4_duplicate_instance_selector",
            "supported_scope": (
                "public runtime selector expansion is still deferred until native "
                "readers consistently populate family-4 CopyN instance provenance"
            ),
            "required_provenance_fields": [
                "family_4_instance_group",
                "duplicate_instance_ordinal",
            ],
            "current_graph_provenance": (
                "TagProvenance.family_4_instance_group and "
                "duplicate_instance_ordinal are serialized when populated"
            ),
            "evidence_ids": [
                (
                    "../exiftool/lib/Image/ExifTool.pm GetGroup derives family 4 "
                    "from duplicate tag keys like 'Tag (1)' and returns CopyN "
                    "for non-primary duplicate instances."
                ),
                (
                    "../exiftool/lib/Image/ExifTool.pm GroupMatches accepts "
                    "Copy0 as the primary tag and matches group chains against "
                    "GetGroup(tag, -1) extended groups."
                ),
            ],
        },
    )


def _missing_public_duplicate_instance_provenance_diagnostic(
    path: Path,
    requested_tag: str,
    selector: PublicReadTagSelector,
    missing_provenance_tags: list[str],
) -> Diagnostic:
    missing_examples: JsonArray = []
    missing_examples.extend(missing_provenance_tags)
    return Diagnostic(
        code="missing_duplicate_instance_provenance",
        message=(
            f"{path}: duplicate instance selector {requested_tag} matched decoded tags "
            "whose family-4 CopyN provenance is not populated."
        ),
        details={
            "requested_tag": requested_tag,
            "selector": _public_read_tag_selector_to_json_value(selector),
            "missing_provenance_examples": missing_examples,
            "unsupported_semantics": "duplicate_selector_without_populated_provenance",
            "supported_scope": (
                "single Copy0/CopyN selectors and single * or All all-instance "
                "selectors are expanded only for decoded tags that already carry "
                "family_4_instance_group and duplicate_instance_ordinal"
            ),
            "required_provenance_fields": [
                "family_4_instance_group",
                "duplicate_instance_ordinal",
            ],
            "current_graph_provenance": (
                "TagProvenance.family_4_instance_group and "
                "duplicate_instance_ordinal are serialized when populated"
            ),
            "evidence_ids": [
                (
                    "../exiftool/lib/Image/ExifTool.pm GetGroup derives family 4 "
                    "as an empty primary instance or CopyN for non-primary duplicates."
                ),
                (
                    "../exiftool/lib/Image/ExifTool.pm GroupMatches normalizes "
                    "Copy0 to the primary instance and compares requested groups "
                    "against GetGroup(tag, -1)."
                ),
                (
                    "../exiftool/lib/Image/ExifTool.pm CombineInfo keeps first "
                    "entries unless Duplicates is enabled, making all-instance "
                    "selection opt-in behavior."
                ),
            ],
        },
    )


def _bounded_public_wildcard_diagnostic(path: Path, requested_tag: str) -> Diagnostic:
    return Diagnostic(
        code="public_wildcard_expansion_truncated",
        message=(
            f"{path}: wildcard tag selection for {requested_tag} reached the "
            f"public expansion bound of {MAX_PUBLIC_WILDCARD_EXPANSION_TAGS} tags."
        ),
        details={
            "requested_tag": requested_tag,
            "max_public_wildcard_expansion_tags": MAX_PUBLIC_WILDCARD_EXPANSION_TAGS,
        },
    )


def _public_wildcard_duplicate_matches_collapsed_diagnostic(
    path: Path,
    requested_tag: str,
    duplicate_matches: list[ReadTag],
) -> Diagnostic:
    duplicate_match_examples: JsonArray = [
        f"{tag.provenance.group}:{tag.name}" for tag in duplicate_matches
    ]
    duplicate_provenance_examples = _duplicate_match_provenance_examples(duplicate_matches)
    evidence_ids: JsonArray = [
        (
            "../exiftool/lib/Image/ExifTool.pm wildcard GetInfo matching "
            "extends patterns for duplicate keys when Duplicates, Exclude, "
            "group options, or all-group mode are active."
        ),
        (
            "../exiftool/lib/Image/ExifTool.pm GetGroup derives family 4 "
            "CopyN names from duplicate tag keys such as 'Tag (1)'."
        ),
    ]
    return Diagnostic(
        code="public_wildcard_duplicate_matches_collapsed",
        message=(
            f"{path}: wildcard tag selection for {requested_tag} matched duplicate "
            "decoded tags, but public wildcard expansion currently emits one "
            "selection key per group/name."
        ),
        details={
            "requested_tag": requested_tag,
            "duplicate_match_examples": duplicate_match_examples,
            "duplicate_handling": (
                "bounded public read graphs do not expose ExifTool instance-numbered "
                "duplicate keys such as 'Tag (1)' for wildcard expansion"
            ),
            "duplicate_provenance_examples": duplicate_provenance_examples,
            "evidence_ids": evidence_ids,
        },
    )


def _duplicate_match_provenance_examples(duplicate_matches: list[ReadTag]) -> JsonArray:
    examples: JsonArray = []
    for tag in duplicate_matches:
        provenance = tag.provenance
        if (
            provenance.family_4_instance_group is None
            and provenance.duplicate_instance_ordinal is None
        ):
            continue
        example: JsonObject = {
            "tag": f"{provenance.group}:{tag.name}",
            "family_4_instance_group": provenance.family_4_instance_group,
            "duplicate_instance_ordinal": provenance.duplicate_instance_ordinal,
        }
        examples.append(example)
    return examples


def _public_read_tag_selector_to_json_value(selector: PublicReadTagSelector) -> JsonObject:
    return {
        "raw": selector.raw,
        "tag_name": selector.tag_name,
        "tag_wildcard": selector.tag_wildcard,
        "all_tag": selector.all_tag,
        "value_conversion_disabled": selector.value_conversion_disabled,
        "group_chain": [
            {
                "raw": group.raw,
                "name": group.name,
                "family": group.family,
                "wildcard_mode": group.wildcard_mode,
                "duplicate_instance_mode": group.duplicate_instance_mode,
                "duplicate_instance_number": group.duplicate_instance_number,
            }
            for group in selector.group_chain
        ],
    }


def _unsupported_public_output_group_families_diagnostic(
    path: Path,
    render: OutputRenderRequest,
) -> Diagnostic | None:
    if len(render.group_name_families) <= 1:
        return None
    if render.format != "xml":
        return None
    return Diagnostic(
        code="unsupported_output_group_family",
        message=(
            f"{path}: chained output group family selection "
            f"{list(render.group_name_families)} is modeled, but not supported by "
            "the bounded public XML output renderer."
        ),
        details={
            "requested_group_name_families": list(render.group_name_families),
            "supported_group_name_families": [0, 1, 2, 4],
            "unsupported_semantics": "chained_xml_output_group_families",
            "current_graph_provenance": (
                "TagProvenance.family_0_group, family_1_group, family_2_group"
            ),
            "supported_scope": (
                "chained -G family labels are rendered for text, JSON, CSV, "
                "and tab output; XML output needs namespace-safe group modeling "
                "before colon-chained labels can be emitted"
            ),
            "evidence_ids": [
                (
                    "../exiftool/exiftool documents -G[NUM][:NUM...] as selecting "
                    "output group family numbers and allowing multiple colon-separated "
                    "families."
                ),
                (
                    "../exiftool/lib/Image/ExifTool.pm GetGroup simplifies multiple "
                    "family strings and removes adjacent identical group names."
                ),
            ],
        },
    )


def _record_with_output_group_family(
    graph: ReadGraph,
    record: JsonRecord,
    render: OutputRenderRequest,
    path: Path,
) -> tuple[JsonRecord, Diagnostic | None]:
    if not render.include_group_names or not render.group_name_families:
        return record, None
    if render.format == "xml" and len(render.group_name_families) > 1:
        return record, None

    relabeled: JsonRecord = {}
    missing_provenance: list[str] = []
    for key, value in record.items():
        if key == "SourceFile":
            relabeled[key] = value
            continue
        tag = _graph_tag_for_record_key(graph, key)
        if tag is None:
            relabeled[key] = value
            continue
        group = _output_group_label_for_tag_provenance(tag.provenance, render.group_name_families)
        if group is None:
            if len(missing_provenance) < 8:
                missing_provenance.append(f"{tag.provenance.group}:{tag.name}")
            relabeled[key] = value
            continue
        relabeled[f"{group}:{tag.name}"] = value

    if missing_provenance:
        return relabeled, _missing_public_output_group_family_provenance_diagnostic(
            path,
            render.group_name_families[0],
            missing_provenance,
        )
    return relabeled, None


def _single_output_group_family(render: OutputRenderRequest) -> PublicReadGroupFamily | None:
    if not render.include_group_names or len(render.group_name_families) != 1:
        return None
    return render.group_name_families[0]


def _output_group_label_for_tag_provenance(
    provenance: TagProvenance,
    families: tuple[PublicReadGroupFamily, ...],
) -> str | None:
    groups: list[str] = []
    for family in families:
        group = _output_group_for_tag_provenance(provenance, family)
        if group is None:
            return None
        if groups and groups[-1] == group:
            continue
        groups.append(group)
    return ":".join(groups)


def _graph_tag_for_record_key(graph: ReadGraph, key: str) -> ReadTag | None:
    if ":" in key:
        group, name = key.rsplit(":", 1)
        for tag in graph.tags:
            if tag.name != name:
                continue
            if group in _output_group_labels_for_graph_tag(tag):
                return tag
        return None
    for tag in graph.tags:
        if tag.name == key:
            return tag
    return None


def _output_group_labels_for_graph_tag(tag: ReadTag) -> frozenset[str]:
    labels: set[str] = {tag.provenance.group}
    families: tuple[PublicReadGroupFamily, ...] = (0, 1, 2, 4)
    for family in families:
        group = _output_group_for_tag_provenance(tag.provenance, family)
        if group is not None:
            labels.add(group)
    for first in families:
        for second in families:
            label = _output_group_label_for_tag_provenance(tag.provenance, (first, second))
            if label is not None:
                labels.add(label)
    return frozenset(labels)


def _output_group_for_tag_provenance(
    provenance: TagProvenance,
    family: PublicReadGroupFamily,
) -> str | None:
    if family == 1 and provenance.family_1_group is None:
        return provenance.group
    return _tag_provenance_family_group(provenance, family)


def _missing_public_output_group_family_provenance_diagnostic(
    path: Path,
    family: PublicReadGroupFamily,
    missing_provenance_tags: list[str],
) -> Diagnostic:
    missing_examples: JsonArray = []
    missing_examples.extend(missing_provenance_tags)
    return Diagnostic(
        code="missing_output_group_family_provenance",
        message=(
            f"{path}: output group family {family} was requested, but some rendered "
            "tags do not carry populated family provenance."
        ),
        details={
            "family": family,
            "missing_provenance_examples": missing_examples,
            "unsupported_semantics": "output_family_without_populated_provenance",
            "supported_scope": (
                "single explicit -G0, -G1, -G2, or -G4 output labels are rendered "
                "only from populated TagProvenance family fields; family 1 may "
                "fall back to the current renderer group"
            ),
            "evidence_ids": [
                (
                    "../exiftool/lib/Image/ExifTool.pm GetGroup returns the "
                    "requested single group family; family 4 derives duplicate "
                    "instance labels such as Copy0 and CopyN."
                ),
                (
                    "../exiftool/exiftool documents -G[NUM] as printing group "
                    "names for each tag, with -G0 assumed when NUM is omitted."
                ),
            ],
        },
    )


def _renderer_args_for_read_request(
    request: MetadataReadRequest,
    tags: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    args: list[str] = []
    if request.render.format == "json":
        args.append("-json")
    if request.render.format == "xml":
        args.append("-G1")
        args.append("-a")
    elif request.render.include_group_names and request.render.group_name_families == (4,):
        args.append("-G4")
    elif request.render.include_group_names:
        args.append("-G1")
    if _public_render_extracts_duplicate_tags(request.render) and "-a" not in args:
        args.append("-a")
    if request.render.include_unknown_tags:
        args.append("-u")
    if request.render.short_tag_names:
        args.append("-s")
    args.extend(_renderer_tag_arg(tag) for tag in (request.tags if tags is None else tags))
    return tuple(args)


def _renderer_tag_arg(tag: str) -> str:
    tag_without_value_suffix = tag.removesuffix("#")
    return (
        tag_without_value_suffix
        if tag_without_value_suffix.startswith("-")
        else f"-{tag_without_value_suffix}"
    )


def _render_read_result_text(
    records: list[MetadataReadRecord],
    request: MetadataReadRequest,
) -> str:
    rendered_text, _ = _render_read_result_text_with_diagnostics(records, request)
    return rendered_text


def _render_read_result_text_with_diagnostics(
    records: list[MetadataReadRecord],
    request: MetadataReadRequest,
) -> tuple[str, tuple[Diagnostic, ...]]:
    if request.render.print_format_templates:
        return _render_print_format_templates(records, request.render)
    render = request.render
    if render.format == "json":
        return _render_records_json(records, render).decode("utf-8"), ()
    if render.format == "xml":
        return _rendered_text_for_charset(_render_records_xml(records, render), render), ()
    if render.format == "csv":
        return _render_records_csv(records, request), ()
    if render.format == "html":
        return _render_records_html(records, render), ()
    if render.format == "php":
        return _render_records_php(records, render), ()
    rendered_text = "".join(record.rendered_text for record in records)
    return _rendered_text_for_charset(rendered_text, render), ()


def _render_print_format_templates(
    records: list[MetadataReadRecord],
    render: OutputRenderRequest,
) -> tuple[str, tuple[Diagnostic, ...]]:
    sections, section_diagnostics = _public_print_format_sections(render.print_format_templates)
    rendered_parts: list[str] = []
    diagnostics = list(section_diagnostics)
    first_record = records[0] if records else None
    rendered_parts.extend(
        _render_print_format_section_lines(sections["HEAD"], first_record, render, diagnostics)
    )
    section_header: str | None = None
    section_trailer = ""
    for record in records:
        section_lines = _render_print_format_section_lines(
            sections["SECT"], record, render, diagnostics
        )
        if section_lines:
            next_section_header = "".join(section_lines)
            if section_header is not None and section_header != next_section_header:
                rendered_parts.append(section_trailer)
                section_trailer = ""
                section_header = None
            if section_header is None:
                section_header = next_section_header
                rendered_parts.append(section_header)
        should_render_body = _print_format_if_sections_match(
            sections["IF"], record, render, diagnostics
        )
        if should_render_body:
            rendered_parts.extend(
                _render_print_format_section_lines(sections["BODY"], record, render, diagnostics)
            )
        if section_header is not None:
            section_trailer += "".join(
                _render_print_format_section_lines(sections["ENDS"], record, render, diagnostics)
            )
    if section_trailer:
        rendered_parts.append(section_trailer)
    rendered_parts.extend(
        _render_print_format_section_lines(sections["TAIL"], first_record, render, diagnostics)
    )
    return "".join(rendered_parts), tuple(diagnostics)


def _public_print_format_sections(
    templates: tuple[PublicPrintFormatTemplate, ...],
) -> tuple[dict[PublicPrintFormatSectionKind, list[str]], tuple[Diagnostic, ...]]:
    sections: dict[PublicPrintFormatSectionKind, list[str]] = {
        "HEAD": [],
        "SECT": [],
        "IF": [],
        "BODY": [],
        "ENDS": [],
        "TAIL": [],
    }
    diagnostics: list[Diagnostic] = []
    for template in templates:
        for line in template.lines:
            if not line.startswith("#"):
                sections["BODY"].append(line)
                continue
            marker_end = line.find("]")
            if marker_end < 0 or not line.startswith("#["):
                continue
            marker = line[2:marker_end]
            content = line[marker_end + 1 :]
            if marker == "HEAD":
                sections["HEAD"].append(content)
                continue
            if marker == "IF":
                sections["IF"].append(content)
                continue
            if marker == "BODY":
                sections["BODY"].append(content)
                continue
            if marker == "TAIL":
                sections["TAIL"].append(content)
                continue
            if marker == "SECT":
                sections["SECT"].append(content)
                continue
            if marker == "ENDS":
                sections["ENDS"].append(content)
    return sections, tuple(diagnostics)


def _print_format_if_sections_match(
    lines: list[str],
    record: MetadataReadRecord,
    render: OutputRenderRequest,
    diagnostics: list[Diagnostic],
) -> bool:
    for line in lines:
        line_match, line_diagnostics = _print_format_if_line_matches(line, record, render)
        diagnostics.extend(line_diagnostics)
        if not line_match:
            return False
    return True


def _print_format_if_line_matches(
    line: str,
    record: MetadataReadRecord,
    render: OutputRenderRequest,
) -> tuple[bool, tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    for tag_expression in _print_format_tag_expressions(line):
        tag_value, tag_diagnostics = _print_format_tag_value(
            tag_expression,
            record,
            render,
            ignore_minor_missing=False,
        )
        diagnostics.extend(
            diagnostic
            for diagnostic in tag_diagnostics
            if diagnostic.code == "print_format_advanced_expression_deferred"
        )
        if tag_value is None:
            return False, tuple(diagnostics)
    return True, tuple(diagnostics)


def _print_format_tag_expressions(line: str) -> tuple[str, ...]:
    expressions: list[str] = []
    index = 0
    while index < len(line):
        if line[index] != "$" or index + 1 >= len(line):
            index += 1
            continue
        next_character = line[index + 1]
        if next_character in {"$", "/"}:
            index += 2
            continue
        if next_character == "{":
            end_index = line.find("}", index + 2)
            if end_index < 0:
                index += 1
                continue
            expressions.append(line[index + 2 : end_index])
            index = end_index + 1
            continue
        tag_end = index + 1
        while tag_end < len(line) and _print_format_tag_character(line[tag_end]):
            tag_end += 1
        if tag_end > index + 1:
            expressions.append(line[index + 1 : tag_end])
            index = tag_end
            continue
        index += 1
    return tuple(expressions)


def _render_print_format_section_lines(
    lines: list[str],
    record: MetadataReadRecord | None,
    render: OutputRenderRequest,
    diagnostics: list[Diagnostic],
) -> list[str]:
    rendered_lines: list[str] = []
    for line in lines:
        rendered, line_diagnostics = _render_print_format_line(line, record, render)
        diagnostics.extend(line_diagnostics)
        if rendered is not None:
            rendered_lines.append(rendered)
    return rendered_lines


def _render_print_format_line(
    line: str,
    record: MetadataReadRecord | None,
    render: OutputRenderRequest,
) -> tuple[str | None, tuple[Diagnostic, ...]]:
    if record is None:
        return "", ()
    rendered: list[str] = []
    diagnostics: list[Diagnostic] = []
    index = 0
    while index < len(line):
        character = line[index]
        if character != "$":
            rendered.append(character)
            index += 1
            continue
        if index + 1 >= len(line):
            rendered.append("$")
            index += 1
            continue
        next_character = line[index + 1]
        if next_character == "$":
            rendered.append("$")
            index += 2
            continue
        if next_character == "/":
            rendered.append("\n")
            index += 2
            continue
        if next_character == "{":
            end_index = line.find("}", index + 2)
            if end_index < 0:
                rendered.append("$")
                index += 1
                continue
            tag_expression = line[index + 2 : end_index]
            tag_value, tag_diagnostics = _print_format_tag_value(
                tag_expression,
                record,
                render,
                ignore_minor_missing=render.ignore_minor_errors,
            )
            diagnostics.extend(tag_diagnostics)
            if tag_value is None:
                return None, tuple(diagnostics)
            rendered.append(tag_value)
            index = end_index + 1
            continue
        tag_end = index + 1
        while tag_end < len(line) and _print_format_tag_character(line[tag_end]):
            tag_end += 1
        if tag_end == index + 1:
            rendered.append("$")
            index += 1
            continue
        tag_value, tag_diagnostics = _print_format_tag_value(
            line[index + 1 : tag_end],
            record,
            render,
            ignore_minor_missing=render.ignore_minor_errors,
        )
        diagnostics.extend(tag_diagnostics)
        if tag_value is None:
            return None, tuple(diagnostics)
        rendered.append(tag_value)
        index = tag_end
    return "".join(rendered), tuple(diagnostics)


def _print_format_tag_character(character: str) -> bool:
    return character.isalnum() or character in {"-", "_", ":", "#", "?", "*"}


def _print_format_tag_value(
    tag_expression: str,
    record: MetadataReadRecord,
    render: OutputRenderRequest,
    *,
    ignore_minor_missing: bool,
) -> tuple[str | None, tuple[Diagnostic, ...]]:
    tag_name, filter_expression, list_item_filter = _print_format_tag_filter_expression(
        tag_expression
    )
    value = _print_format_record_value(record.values, tag_name)
    if value is None:
        if render.missing_tag_value is not None:
            return render.missing_tag_value, ()
        if ignore_minor_missing:
            return "", ()
        return None, (_print_format_missing_tag_diagnostic(record.path, tag_name),)
    if filter_expression is not None:
        rendered_value = _print_format_filtered_tag_value(
            value,
            filter_expression,
            list_item_filter=list_item_filter,
            render=render,
        )
        if rendered_value is None:
            return None, (_print_format_advanced_expression_deferred_diagnostic(tag_expression),)
        return rendered_value, ()
    return _text_value(value, list_separator=render.list_separator), ()


def _print_format_tag_filter_expression(tag_expression: str) -> tuple[str, str | None, bool]:
    tag_name, separator, filter_expression = tag_expression.partition(";")
    list_item_filter = tag_name.endswith("@")
    if list_item_filter:
        tag_name = tag_name.removesuffix("@")
    tag_name = tag_name.removesuffix("#")
    if not separator:
        return tag_name, None, list_item_filter
    if filter_expression == "":
        # Source: ../exiftool/exiftool documentation lines 7411-7414 defines
        # an empty advanced expression as removing Windows filename-illegal chars.
        filter_expression = _PRINT_FORMAT_DEFAULT_FILENAME_SANITIZER
    return tag_name, filter_expression, list_item_filter


def _print_format_filtered_tag_value(
    value: TagValue,
    filter_expression: str,
    *,
    list_item_filter: bool,
    render: OutputRenderRequest,
) -> str | None:
    if isinstance(value, BinaryTagValue | BinaryTagListValue):
        return None
    if filter_expression == _PRINT_FORMAT_DEFAULT_FILENAME_SANITIZER:
        return _print_format_sanitized_filename_value(
            value,
            list_item_filter=list_item_filter,
            render=render,
        )
    from exifmodern.safe_expression.facade import compile_safe_filter_expression

    program = compile_safe_filter_expression(filter_expression)
    if program is None:
        return None
    if list_item_filter and isinstance(value, list):
        rendered_items: list[str] = []
        for item in value:
            filtered_item = _print_format_evaluate_filter_program(program, item)
            if filtered_item is None:
                continue
            rendered_items.append(_print_format_vm_value_to_text(filtered_item))
        return render.list_separator.join(rendered_items)
    filtered = _print_format_evaluate_filter_program(program, value)
    if filtered is None:
        return None
    return _print_format_vm_value_to_text(filtered)


def _print_format_sanitized_filename_value(
    value: ScalarTagValue | ScalarTagArray,
    *,
    list_item_filter: bool,
    render: OutputRenderRequest,
) -> str:
    if isinstance(value, list):
        items = (_print_format_default_filename_sanitize(item) for item in value)
        separator = render.list_separator if list_item_filter else " "
        return separator.join(items)
    return _print_format_default_filename_sanitize(value)


def _print_format_default_filename_sanitize(value: ScalarTagValue) -> str:
    return "".join(character for character in str(value) if character not in "/\\?*:|<>\0")


def _print_format_evaluate_filter_program(
    program: SafeExpressionProgram,
    value: ScalarTagValue | ScalarTagArray,
) -> VmValue | None:
    from exifmodern.safe_expression.vm import SafeExpressionVmError, evaluate_program

    if isinstance(value, list):
        input_value: VmValue = list(value)
    else:
        input_value = value
    try:
        return evaluate_program(program, {"$val": input_value})
    except SafeExpressionVmError:
        return None


def _print_format_vm_value_to_text(value: VmValue) -> str:
    from exifmodern.safe_expression.bytecode import (
        ArrayReferenceValue,
        HashReferenceValue,
        ScalarReferenceValue,
    )

    if isinstance(value, ScalarReferenceValue):
        return _print_format_vm_value_to_text(value.value)
    if isinstance(value, ArrayReferenceValue):
        return " ".join(_print_format_vm_value_to_text(item) for item in value.values)
    if isinstance(value, HashReferenceValue):
        return ""
    if isinstance(value, list):
        return " ".join(_print_format_vm_value_to_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _print_format_record_value(record: JsonRecord, tag_name: str) -> TagValue | None:
    lookup = {key.lower(): value for key, value in record.items()}
    normalized_tag = tag_name.lower()
    if normalized_tag in lookup:
        return lookup[normalized_tag]
    if ":" in normalized_tag:
        _, short_name = normalized_tag.rsplit(":", 1)
        return lookup.get(short_name)
    for key, value in record.items():
        if key.lower().rsplit(":", 1)[-1] == normalized_tag:
            return value
    return None


def _print_format_missing_tag_diagnostic(path: Path, tag_name: str) -> Diagnostic:
    return Diagnostic(
        code="print_format_tag_not_rendered",
        message=(
            f"[minor] {path}: print-format tag {tag_name} was not available; skipped template line"
        ),
        details={
            "path": path.as_posix(),
            "tag": tag_name,
            "evidence_ids": (
                "../exiftool/exiftool documentation lines 6184-6195 says missing "
                "-p tags issue a minor warning and skip the line unless -f or -m changes "
                "missing-tag behavior."
            ),
        },
    )


def _print_format_advanced_expression_deferred_diagnostic(tag_expression: str) -> Diagnostic:
    return Diagnostic(
        code="print_format_advanced_expression_deferred",
        message=(
            "ExifTool advanced -p tag expressions are recognized but not evaluated by "
            "the safe public template subset."
        ),
        details={
            "tag_expression": tag_expression,
            "evidence_ids": (
                "../exiftool/exiftool documentation lines 7398-7477 allows Perl "
                "statements inside ${TAG;EXPR}; ExifModern must not guess these effects."
            ),
        },
    )


def _print_format_section_deferred_diagnostic(
    template: PublicPrintFormatTemplate,
    marker: str,
) -> Diagnostic:
    return Diagnostic(
        code="print_format_section_deferred",
        message=(
            f"ExifTool -p section marker #[{marker}] is recognized but outside the "
            "safe public template subset."
        ),
        details={
            "marker": marker,
            "source_kind": template.source_kind,
            "raw_argument": template.raw_argument,
            "evidence_ids": (
                "../exiftool/exiftool documentation lines 6138-6154 defines HEAD, "
                "SECT, IF, BODY, ENDS, and TAIL markers; this lane implements only "
                "literal marker sections and safe tag interpolation."
            ),
        },
    )


def _record_with_list_item_projection(
    record: JsonRecord,
    request: OutputRenderRequest,
) -> JsonRecord:
    if request.list_item_index is None:
        return record
    projected: JsonRecord = {}
    for key, value in record.items():
        if key == "SourceFile" or not isinstance(value, list):
            projected[key] = value
            continue
        selected = _list_item_value(value, request.list_item_index)
        if selected is not None:
            projected[key] = selected
    return projected


def _sorted_record(record: JsonRecord, request: OutputRenderRequest) -> JsonRecord:
    if not request.sort_output:
        return record
    source_file = record.get("SourceFile")
    sorted_items = sorted(
        ((key, value) for key, value in record.items() if key != "SourceFile"),
        key=lambda item: _sort_output_key(item[0], request),
    )
    sorted_record: JsonRecord = {}
    if source_file is not None:
        sorted_record["SourceFile"] = source_file
    sorted_record.update(sorted_items)
    return sorted_record


def _sort_output_key(key: str, request: OutputRenderRequest) -> str:
    if request.short_tag_names and ":" in key:
        _, tag = key.split(":", 1)
        return tag.lower()
    return key.lower()


def _xml_elements_with_list_item_projection(
    elements: tuple[XmlTagElement, ...],
    request: OutputRenderRequest,
) -> tuple[XmlTagElement, ...]:
    if request.list_item_index is None:
        return elements
    projected: list[XmlTagElement] = []
    for element in elements:
        if not isinstance(element.value, list):
            projected.append(element)
            continue
        selected = _list_item_value(element.value, request.list_item_index)
        if selected is not None:
            projected.append(replace(element, value=selected))
    return tuple(projected)


def _xml_elements_with_source_xmp_struct_list_boundaries(
    path: Path,
    elements: tuple[XmlTagElement, ...],
    request: OutputRenderRequest,
) -> tuple[XmlTagElement, ...]:
    if not _render_uses_xml_elements_for_structured_output(request):
        return elements
    _ensure_public_xmp_structured_runtime_imports()

    pending = _source_xmp_struct_list_pending_targets(elements)
    if not pending:
        return elements
    packets = _source_xmp_packets_for_structured_render(path)
    if not packets:
        return elements
    source_parents: dict[tuple[str, str], XmlTagElement] = {}
    for packet in packets:
        packet_parents = _source_xmp_struct_list_parent_elements(packet, pending, request)
        for parent_key, packet_parent in packet_parents.items():
            source_parents.setdefault(parent_key, packet_parent)
    if not source_parents:
        return elements

    ordered_parents: dict[int, XmlTagElement] = {}
    flat_struct_field_indices: set[int] = set()
    for parent_key, source_parent in source_parents.items():
        parent_indices = pending[parent_key][1]
        ordered_parents[min(parent_indices)] = source_parent
        flat_struct_field_indices.update(parent_indices)

    structured_elements: list[XmlTagElement] = []
    for index, element in enumerate(elements):
        parent: XmlTagElement | None = ordered_parents.get(index)
        if parent is not None:
            structured_elements.append(parent)
        if index in flat_struct_field_indices:
            continue
        structured_elements.append(element)
    return tuple(structured_elements)


def _source_xmp_struct_list_pending_targets(
    elements: tuple[XmlTagElement, ...],
) -> dict[tuple[str, str], tuple[tuple[_XmlStructuredFieldTarget, ...], set[int]]]:
    pending_targets: dict[tuple[str, str], list[_XmlStructuredFieldTarget]] = {}
    pending_indices: dict[tuple[str, str], set[int]] = {}
    seen_fields: set[tuple[str, str, str]] = set()
    for index, element in enumerate(elements):
        target = _xmp_struct_list_field_target(element)
        if target is None:
            continue
        parent_key = (target.parent_group, target.parent_name)
        field_key = (target.parent_group, target.parent_name, target.field_name)
        if field_key not in seen_fields:
            targets = pending_targets.setdefault(parent_key, [])
            targets.append(target)
            seen_fields.add(field_key)
        indices = pending_indices.setdefault(parent_key, set())
        indices.add(index)
    return {
        parent_key: (
            tuple(sorted(targets, key=lambda target: (target.field_order, target.field_name))),
            pending_indices[parent_key],
        )
        for parent_key, targets in pending_targets.items()
    }


def _xmp_struct_list_field_target(element: XmlTagElement) -> _XmlStructuredFieldTarget | None:
    _ensure_public_xmp_structured_runtime_imports()
    generic_target = _generic_xmp_structured_field_target(element)
    if generic_target is not None and generic_target.parent_shape == "struct_list":
        return generic_target

    resource_ref_target = resource_ref_assignment_target(f"{element.group}:{element.tag}")
    if resource_ref_target is not None and resource_ref_target.parent_spec.shape == "struct_list":
        return _XmlStructuredFieldTarget(
            parent_group=element.group,
            parent_name=resource_ref_target.parent_spec.parent_name,
            parent_element_name=resource_ref_target.parent_spec.element_name,
            parent_uri_path="XMP/XMP-xmpMM",
            parent_shape=resource_ref_target.parent_spec.shape,
            parent_list_kind=resource_ref_target.parent_spec.list_kind or "Bag",
            field_group=element.group,
            field_name=resource_ref_target.field_spec.readback_suffix,
            source_field_name=resource_ref_target.field_spec.field_name,
            field_uri_path="XMP/XMP-xmpMM",
            field_order=_resource_ref_field_order(resource_ref_target.field_spec.readback_suffix),
        )

    manifest_target = manifest_item_assignment_target(f"{element.group}:{element.tag}")
    if manifest_target is None:
        return None
    if manifest_target.field_kind == "simple" and manifest_target.simple_field_spec is not None:
        simple_spec = manifest_target.simple_field_spec
        return _XmlStructuredFieldTarget(
            parent_group=element.group,
            parent_name=manifest_target.parent_spec.parent_name,
            parent_element_name=manifest_target.parent_spec.element_name,
            parent_uri_path="XMP/XMP-xmpMM",
            parent_shape=manifest_target.parent_spec.shape,
            parent_list_kind=manifest_target.parent_spec.list_kind,
            field_group=simple_spec.namespace_prefix,
            field_name=simple_spec.field_name,
            source_field_name=simple_spec.field_name,
            field_uri_path=_xmp_struct_namespace_uri_path(simple_spec.namespace_prefix),
            field_order=_manifest_simple_field_order(simple_spec.readback_suffix),
        )
    if (
        manifest_target.field_kind == "reference"
        and manifest_target.reference_field_spec is not None
    ):
        reference_spec = manifest_target.reference_field_spec
        return _XmlStructuredFieldTarget(
            parent_group=element.group,
            parent_name=manifest_target.parent_spec.parent_name,
            parent_element_name=manifest_target.parent_spec.element_name,
            parent_uri_path="XMP/XMP-xmpMM",
            parent_shape=manifest_target.parent_spec.shape,
            parent_list_kind=manifest_target.parent_spec.list_kind,
            field_group="stRef",
            field_name=reference_spec.field_name,
            source_field_name=reference_spec.field_name,
            field_uri_path=_xmp_struct_namespace_uri_path("stRef"),
            field_order=len(XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS)
            + _resource_ref_field_order(reference_spec.readback_suffix),
            nested_path=(
                _XmlStructuredPathStep(
                    group="stMfs",
                    field_name="reference",
                    uri_path=_xmp_struct_namespace_uri_path("stMfs"),
                ),
            ),
        )
    return None


def _source_xmp_packets_for_structured_render(path: Path) -> tuple[bytes, ...]:
    if path.suffix.lower() != ".xmp":
        return _source_jpeg_xmp_packets_for_structured_render(path)
    try:
        data = read_public_document_payload(path)
    except OSError:
        return ()
    if data is None:
        return ()
    return (data,)


def _source_jpeg_xmp_packets_for_structured_render(path: Path) -> tuple[bytes, ...]:
    if path.suffix.lower() not in {".jpe", ".jpeg", ".jpg"}:
        return ()
    _ensure_public_xmp_structured_runtime_imports()
    from exifmodern.formats.jpeg.app_segments.xmp import jpeg_xmp_packets_from_app1_file

    try:
        return tuple(packet.packet for packet in jpeg_xmp_packets_from_app1_file(path))
    except OSError, ValueError:
        return ()


def _source_xmp_struct_list_parent_elements(
    packet: bytes,
    pending: dict[tuple[str, str], tuple[tuple[_XmlStructuredFieldTarget, ...], set[int]]],
    request: OutputRenderRequest,
) -> dict[tuple[str, str], XmlTagElement]:
    try:
        root = ElementTree.fromstring(decode_xmp_packet(packet))
    except ElementTree.ParseError:
        return {}

    parent_elements: dict[tuple[str, str], XmlTagElement] = {}
    for property_element in root.iter():
        parent_key = _source_xmp_struct_list_parent_key(property_element, pending)
        if parent_key is None:
            continue
        targets = pending[parent_key][0]
        items = _source_xmp_struct_list_items(property_element, targets, request)
        if not items:
            continue
        first_target = targets[0]
        parent_elements[parent_key] = XmlTagElement(
            group=first_target.parent_group,
            tag=first_target.parent_name,
            value=None,
            uri_path=first_target.parent_uri_path,
            list_container=first_target.parent_list_kind,
            struct_list_items=items,
        )
    return parent_elements


def _source_xmp_struct_list_parent_key(
    element: ElementTree.Element[str],
    pending: dict[tuple[str, str], tuple[tuple[_XmlStructuredFieldTarget, ...], set[int]]],
) -> tuple[str, str] | None:
    namespace, local_name = expanded_name_parts(element.tag)
    if namespace is None:
        return None
    spec = namespace_spec_for_uri(namespace)
    if spec is None:
        return None
    for parent_key, (targets, _) in pending.items():
        first_target = targets[0]
        if (
            spec.group == first_target.parent_group
            and local_name == first_target.parent_element_name
        ):
            return parent_key
    return None


def _source_xmp_struct_list_items(
    element: ElementTree.Element[str],
    targets: tuple[_XmlStructuredFieldTarget, ...],
    request: OutputRenderRequest,
) -> tuple[XmlStructListItem, ...]:
    container = _source_xmp_rdf_container(element)
    if container is None:
        return ()
    indexed_source_items = tuple(
        (index, item)
        for index, item in enumerate(tuple(container))
        if expanded_name_parts(item.tag) == (RDF_NAMESPACE, "li")
    )
    if request.list_item_index is not None:
        try:
            indexed_source_items = (indexed_source_items[request.list_item_index],)
        except IndexError:
            indexed_source_items = ()

    rendered_items: list[XmlStructListItem] = []
    for source_index, source_item in indexed_source_items:
        fields: list[XmlStructField] = []
        for target in targets:
            value = _source_xmp_struct_field_value(source_item, target)
            if value is None:
                continue
            fields.append(_xml_struct_field_for_target(target, value))
        if fields:
            parent = targets[0]
            rendered_items.append(
                XmlStructListItem(
                    fields=tuple(fields),
                    boundary=XmlStructListItemBoundary(
                        source_index=source_index,
                        source_path=(
                            f"{parent.parent_group}:{parent.parent_name}/rdf:li[{source_index}]"
                        ),
                    ),
                )
            )
    return tuple(rendered_items)


def _source_xmp_rdf_container(
    element: ElementTree.Element[str],
) -> ElementTree.Element[str] | None:
    for child in tuple(element):
        namespace, local_name = expanded_name_parts(child.tag)
        if namespace == RDF_NAMESPACE and local_name in {"Bag", "Seq", "Alt"}:
            return child
    return None


def _source_xmp_struct_field_value(
    source_item: ElementTree.Element[str],
    target: _XmlStructuredFieldTarget,
) -> TagValue:
    payload_elements: tuple[ElementTree.Element[str], ...] = (source_item,)
    for step in target.nested_path:
        nested_payloads: list[ElementTree.Element[str]] = []
        for payload_element in payload_elements:
            nested_element = _source_xmp_direct_child_by_local_name(
                payload_element,
                step.field_name,
            )
            if nested_element is not None:
                nested_payloads.append(nested_element)
        if not nested_payloads:
            return None
        payload_elements = tuple(nested_payloads)

    for payload_element in payload_elements:
        field_element = _source_xmp_direct_child_by_local_name(
            payload_element,
            target.source_field_name,
        )
        if field_element is not None:
            return _source_xmp_element_value(field_element)
        attribute_value = _source_xmp_attribute_by_local_name(
            payload_element,
            target.source_field_name,
        )
        if attribute_value is not None:
            return attribute_value
    return None


def _source_xmp_element_value(element: ElementTree.Element[str]) -> TagValue:
    container = _source_xmp_rdf_container(element)
    if container is not None:
        values: list[ScalarTagValue] = []
        for item in tuple(container):
            if expanded_name_parts(item.tag) != (RDF_NAMESPACE, "li"):
                continue
            text = _source_xmp_text(item)
            if text is not None:
                values.append(text)
            elif not tuple(item):
                values.append("")
        return values
    text = _source_xmp_text(element)
    if text is not None:
        return text
    resource = element.attrib.get(f"{{{RDF_NAMESPACE}}}resource")
    if resource is not None:
        return resource
    return None


def _source_xmp_direct_child_by_local_name(
    element: ElementTree.Element[str],
    local_name: str,
) -> ElementTree.Element[str] | None:
    for child in tuple(element):
        _, child_name = expanded_name_parts(child.tag)
        if child_name == local_name:
            return child
    return None


def _source_xmp_attribute_by_local_name(
    element: ElementTree.Element[str],
    local_name: str,
) -> str | None:
    for attribute_name, value in element.attrib.items():
        _, attribute_local_name = expanded_name_parts(attribute_name)
        if attribute_local_name == local_name:
            return value
    return None


def _source_xmp_text(element: ElementTree.Element[str]) -> str | None:
    if element.text is None:
        return None
    text = element.text.strip()
    return text or None


def _xml_elements_with_structured_xmp_parents(
    elements: tuple[XmlTagElement, ...],
    request: OutputRenderRequest,
) -> tuple[XmlTagElement, ...]:
    if not _render_uses_xml_elements_for_structured_output(request):
        return elements
    _ensure_public_xmp_structured_runtime_imports()
    elements = _xml_elements_with_generic_xmp_structured_parents(elements, request)
    elements = _xml_elements_with_xmp_resource_ref_parents(elements, request)
    return _xml_elements_with_xmp_manifest_parents(elements)


def _xml_elements_with_generic_xmp_structured_parents(
    elements: tuple[XmlTagElement, ...],
    request: OutputRenderRequest,
) -> tuple[XmlTagElement, ...]:
    pending_by_parent: dict[tuple[str, str], _PendingXmlStructuredParent] = {}
    flat_struct_field_indices: set[int] = set()
    flat_struct_field_indices_by_parent: dict[tuple[str, str], set[int]] = {}
    for index, element in enumerate(elements):
        target = _generic_xmp_structured_field_target(element)
        if target is None:
            continue
        field = _xml_struct_field_for_target(target, element.value)
        parent_key = (target.parent_group, target.parent_name)
        pending = pending_by_parent.get(parent_key)
        if pending is None:
            pending = _PendingXmlStructuredParent(
                target=target,
                fields={},
                first_index=index,
            )
            pending_by_parent[parent_key] = pending
        pending.fields[f"{target.field_order}:{target.field_name}"] = field
        flat_struct_field_indices.add(index)
        parent_indices = flat_struct_field_indices_by_parent.setdefault(parent_key, set())
        parent_indices.add(index)
    if not pending_by_parent:
        return elements

    ordered_parents: dict[int, XmlTagElement] = {}
    for pending in pending_by_parent.values():
        parent = _xml_generic_structured_parent_element(pending, request)
        if parent is not None:
            ordered_parents[pending.first_index] = parent
        else:
            parent_key = (pending.target.parent_group, pending.target.parent_name)
            flat_struct_field_indices.difference_update(
                flat_struct_field_indices_by_parent.get(parent_key, set())
            )

    structured_elements: list[XmlTagElement] = []
    for index, element in enumerate(elements):
        parent = ordered_parents.get(index)
        if parent is not None:
            structured_elements.append(parent)
        if index in flat_struct_field_indices:
            continue
        structured_elements.append(element)
    return tuple(structured_elements)


def _generic_xmp_structured_field_target(
    element: XmlTagElement,
) -> _XmlStructuredFieldTarget | None:
    _ensure_public_xmp_structured_runtime_imports()
    property_name = f"{element.group}:{element.tag}"
    simple_target = xmp_simple_struct_assignment_target(property_name)
    if simple_target is not None:
        nested_steps = tuple(
            _xml_structured_path_step(
                parent_group=simple_target.parent_spec.group,
                namespace_prefix=simple_target.parent_spec.struct_namespace_prefix,
                namespace_uri=step.namespace_uri,
                field_name=step.field_name,
                list_kind=step.list_kind,
            )
            for step in simple_struct_nested_path_steps(simple_target.field_spec)
        )
        return _XmlStructuredFieldTarget(
            parent_group=simple_target.parent_spec.group,
            parent_name=simple_target.parent_spec.parent_name,
            parent_element_name=simple_target.parent_spec.element_name,
            parent_uri_path=_xmp_struct_namespace_uri_path(simple_target.parent_spec.group),
            parent_shape=simple_target.parent_spec.shape,
            parent_list_kind=simple_target.parent_spec.list_kind or "Bag",
            field_group=simple_target.parent_spec.group,
            field_name=simple_target.field_spec.field_name,
            source_field_name=simple_target.field_spec.field_name,
            field_uri_path=_xmp_struct_namespace_uri_path(simple_target.parent_spec.group),
            field_order=_simple_struct_field_order(property_name),
            nested_path=nested_steps,
        )

    job_ref_target = job_ref_assignment_target(property_name)
    if job_ref_target is not None:
        return _XmlStructuredFieldTarget(
            parent_group="XMP-xmpBJ",
            parent_name=job_ref_target.parent_spec.parent_name,
            parent_element_name=job_ref_target.parent_spec.element_name,
            parent_uri_path="XMP/XMP-xmpBJ",
            parent_shape=job_ref_target.parent_spec.shape,
            parent_list_kind=job_ref_target.parent_spec.list_kind,
            field_group="stJob",
            field_name=job_ref_target.field_spec.field_name,
            source_field_name=job_ref_target.field_spec.field_name,
            field_uri_path="XMP/stJob",
            field_order=_job_ref_field_order(job_ref_target.field_spec.readback_suffix),
        )

    pantry_target = pantry_item_assignment_target(property_name)
    if pantry_target is not None:
        return _XmlStructuredFieldTarget(
            parent_group="XMP-xmpMM",
            parent_name=pantry_target.parent_spec.parent_name,
            parent_element_name=pantry_target.parent_spec.element_name,
            parent_uri_path="XMP/XMP-xmpMM",
            parent_shape=pantry_target.parent_spec.shape,
            parent_list_kind=pantry_target.parent_spec.list_kind,
            field_group="xmpMM",
            field_name=pantry_target.field_spec.field_name,
            source_field_name=pantry_target.field_spec.field_name,
            field_uri_path="XMP/XMP-xmpMM",
            field_order=_pantry_item_field_order(pantry_target.field_spec.readback_suffix),
        )

    resource_event_target = resource_event_assignment_target(property_name)
    if resource_event_target is not None:
        return _XmlStructuredFieldTarget(
            parent_group="XMP-xmpMM",
            parent_name=resource_event_target.parent_spec.parent_name,
            parent_element_name=resource_event_target.parent_spec.element_name,
            parent_uri_path="XMP/XMP-xmpMM",
            parent_shape=resource_event_target.parent_spec.shape,
            parent_list_kind=resource_event_target.parent_spec.list_kind,
            field_group="stEvt",
            field_name=resource_event_target.field_spec.field_name,
            source_field_name=resource_event_target.field_spec.field_name,
            field_uri_path="XMP/stEvt",
            field_order=_resource_event_field_order(
                resource_event_target.field_spec.readback_suffix
            ),
        )

    return None


def _structured_xmp_renderer_blocker_diagnostics(
    path: Path,
    elements: tuple[XmlTagElement, ...],
    request: OutputRenderRequest,
) -> tuple[Diagnostic, ...]:
    if not _render_uses_xml_elements_for_structured_output(request):
        return ()
    _ensure_public_xmp_structured_runtime_imports()
    blocked_parent_names: list[str] = []
    for element in elements:
        target = _xmp_struct_list_field_target(element)
        if target is None:
            continue
        parent_name = f"{target.parent_group}:{target.parent_name}"
        if parent_name not in blocked_parent_names:
            blocked_parent_names.append(parent_name)
    if not blocked_parent_names:
        return ()
    blocked_parents: JsonArray = []
    for parent_name in blocked_parent_names:
        blocked_parents.append(parent_name)
    return (
        Diagnostic(
            code="structured_xmp_list_item_boundaries_unavailable",
            message=(
                f"{path}: structured XMP list rendering kept flattened fields because "
                "list item boundary indexes are not available in public render elements."
            ),
            details={
                "path": path.as_posix(),
                "blocked_parents": blocked_parents,
                "evidence_ids": [
                    (
                        "../exiftool/lib/Image/ExifTool/XMP.pm lines 3986-3999 add "
                        "indexed rdf:li properties so ExifTool can restore struct-list "
                        "item grouping."
                    ),
                    (
                        "../exiftool/t/XMP_31.out line 13 shows LocationCreated as "
                        "multiple struct items; flattened readback lacks item indexes."
                    ),
                ],
            },
        ),
    )


def _xml_structured_path_step(
    *,
    parent_group: str,
    namespace_prefix: str,
    namespace_uri: str | None,
    field_name: str,
    list_kind: XmlListContainerKind | None,
) -> _XmlStructuredPathStep:
    if namespace_uri is None:
        return _XmlStructuredPathStep(
            group=parent_group,
            field_name=field_name,
            uri_path=_xmp_struct_namespace_uri_path(parent_group),
            list_kind=list_kind,
        )
    return _XmlStructuredPathStep(
        group=namespace_prefix,
        field_name=field_name,
        uri_path=_xmp_struct_namespace_uri_path(namespace_prefix),
        list_kind=list_kind,
    )


def _xml_struct_field_for_target(
    target: _XmlStructuredFieldTarget,
    value: TagValue,
) -> XmlStructField:
    field = XmlStructField(
        group=target.field_group,
        tag=target.field_name,
        value=value,
        uri_path=target.field_uri_path,
    )
    for step in reversed(target.nested_path):
        field = XmlStructField(
            group=step.group,
            tag=step.field_name,
            value=None,
            uri_path=step.uri_path,
            struct_fields=(field,),
        )
    return field


def _xml_generic_structured_parent_element(
    pending: _PendingXmlStructuredParent,
    request: OutputRenderRequest,
) -> XmlTagElement | None:
    ordered_fields = tuple(
        field
        for _, field in sorted(
            pending.fields.items(),
            key=lambda item: (int(item[0].partition(":")[0]), item[0]),
        )
    )
    target = pending.target
    if target.parent_shape == "struct":
        return XmlTagElement(
            group=target.parent_group,
            tag=target.parent_name,
            value=None,
            uri_path=target.parent_uri_path,
            struct_fields=ordered_fields,
        )
    if not _xml_struct_list_can_render_as_single_item(ordered_fields, request):
        return None
    return XmlTagElement(
        group=target.parent_group,
        tag=target.parent_name,
        value=None,
        uri_path=target.parent_uri_path,
        list_container=target.parent_list_kind,
        struct_list_items=(XmlStructListItem(fields=ordered_fields),),
    )


def _xml_struct_list_can_render_as_single_item(
    fields: tuple[XmlStructField, ...],
    request: OutputRenderRequest,
) -> bool:
    _ = fields
    _ = request
    return False


def _simple_struct_field_order(property_name: str) -> int:
    return 0


def _job_ref_field_order(readback_suffix: str) -> int:
    for index, field_spec in enumerate(XMP_JOB_REF_FIELD_SPECS):
        if field_spec.readback_suffix == readback_suffix:
            return index
    return 0


def _pantry_item_field_order(readback_suffix: str) -> int:
    for index, field_spec in enumerate(XMP_PANTRY_ITEM_FIELD_SPECS):
        if field_spec.readback_suffix == readback_suffix:
            return index
    return 0


def _resource_event_field_order(readback_suffix: str) -> int:
    for index, field_spec in enumerate(XMP_RESOURCE_EVENT_FIELD_SPECS):
        if field_spec.readback_suffix == readback_suffix:
            return index
    return 0


def _resource_ref_field_order(readback_suffix: str) -> int:
    for index, field_spec in enumerate(XMP_RESOURCE_REF_FIELD_SPECS):
        if field_spec.readback_suffix == readback_suffix:
            return index
    return 0


def _manifest_simple_field_order(readback_suffix: str) -> int:
    for index, field_spec in enumerate(XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS):
        if field_spec.readback_suffix == readback_suffix:
            return index
    return 0


def _xml_elements_with_xmp_resource_ref_parents(
    elements: tuple[XmlTagElement, ...],
    request: OutputRenderRequest,
) -> tuple[XmlTagElement, ...]:
    pending_by_parent: dict[tuple[str, str], _PendingXmlResourceRefParent] = {}
    flat_struct_field_indices: set[int] = set()
    flat_struct_field_indices_by_parent: dict[tuple[str, str], set[int]] = {}
    for index, element in enumerate(elements):
        target = resource_ref_assignment_target(f"{element.group}:{element.tag}")
        if target is None:
            continue
        parent_key = (element.group, target.parent_spec.parent_name)
        pending = pending_by_parent.get(parent_key)
        if pending is None:
            pending = _PendingXmlResourceRefParent(
                group=element.group,
                parent_name=target.parent_spec.parent_name,
                uri_path="XMP/XMP-xmpMM",
                fields={},
                first_index=index,
            )
            pending_by_parent[parent_key] = pending
        pending.fields[target.field_spec.readback_suffix] = XmlStructField(
            group=element.group,
            tag=target.field_spec.readback_suffix,
            value=element.value,
        )
        flat_struct_field_indices.add(index)
        parent_indices = flat_struct_field_indices_by_parent.setdefault(parent_key, set())
        parent_indices.add(index)
    if not pending_by_parent:
        return elements

    ordered_parents: dict[int, XmlTagElement] = {}
    for pending in pending_by_parent.values():
        parent = _xml_resource_ref_parent_element(pending, request)
        if parent is not None:
            ordered_parents[pending.first_index] = parent
        else:
            blocked_parent_key = (pending.group, pending.parent_name)
            flat_struct_field_indices.difference_update(
                flat_struct_field_indices_by_parent.get(blocked_parent_key, set())
            )
    structured_elements: list[XmlTagElement] = []
    for index, element in enumerate(elements):
        parent = ordered_parents.get(index)
        if parent is not None:
            structured_elements.append(parent)
        if index in flat_struct_field_indices:
            continue
        structured_elements.append(element)
    return tuple(structured_elements)


def _xml_resource_ref_parent_element(
    pending: _PendingXmlResourceRefParent,
    request: OutputRenderRequest,
) -> XmlTagElement | None:
    ordered_fields: list[XmlStructField] = []
    for field_spec in XMP_RESOURCE_REF_FIELD_SPECS:
        field = pending.fields.get(field_spec.readback_suffix)
        if field is not None:
            ordered_fields.append(field)
    parent_spec = resource_ref_assignment_target(
        f"{pending.group}:{pending.parent_name}{ordered_fields[0].tag}"
    )
    if parent_spec is None or parent_spec.parent_spec.shape == "struct":
        return XmlTagElement(
            group=pending.group,
            tag=pending.parent_name,
            value=None,
            uri_path=pending.uri_path,
            struct_fields=tuple(ordered_fields),
        )
    if not _xml_struct_list_can_render_as_single_item(tuple(ordered_fields), request):
        return None
    return XmlTagElement(
        group=pending.group,
        tag=pending.parent_name,
        value=None,
        uri_path=pending.uri_path,
        list_container=parent_spec.parent_spec.list_kind or "Bag",
        struct_list_items=(XmlStructListItem(fields=tuple(ordered_fields)),),
    )


def _xml_elements_with_xmp_manifest_parents(
    elements: tuple[XmlTagElement, ...],
) -> tuple[XmlTagElement, ...]:
    pending_by_parent: dict[tuple[str, str], _PendingXmlManifestParent] = {}
    flat_struct_field_indices: set[int] = set()
    for index, element in enumerate(elements):
        target = manifest_item_assignment_target(f"{element.group}:{element.tag}")
        if target is None:
            continue
        parent_key = (element.group, target.parent_spec.parent_name)
        pending = pending_by_parent.get(parent_key)
        if pending is None:
            pending = _PendingXmlManifestParent(
                group=element.group,
                parent_name=target.parent_spec.parent_name,
                uri_path="XMP/XMP-xmpMM",
                simple_fields={},
                reference_fields={},
                first_index=index,
            )
            pending_by_parent[parent_key] = pending
        if target.field_kind == "simple" and target.simple_field_spec is not None:
            pending.simple_fields[target.simple_field_spec.readback_suffix] = XmlStructField(
                group=target.simple_field_spec.namespace_prefix,
                tag=target.simple_field_spec.field_name,
                value=element.value,
                uri_path=_xmp_struct_namespace_uri_path(target.simple_field_spec.namespace_prefix),
            )
            flat_struct_field_indices.add(index)
            continue
        if target.field_kind == "reference" and target.reference_field_spec is not None:
            pending.reference_fields[target.reference_field_spec.readback_suffix] = XmlStructField(
                group="stRef",
                tag=target.reference_field_spec.field_name,
                value=element.value,
                uri_path=_xmp_struct_namespace_uri_path("stRef"),
            )
            flat_struct_field_indices.add(index)
    if not pending_by_parent:
        return elements

    ordered_parents = {
        pending.first_index: _xml_manifest_parent_element(pending)
        for pending in pending_by_parent.values()
    }
    structured_elements: list[XmlTagElement] = []
    for index, element in enumerate(elements):
        parent = ordered_parents.get(index)
        if parent is not None:
            structured_elements.append(parent)
        if index in flat_struct_field_indices:
            continue
        structured_elements.append(element)
    return tuple(structured_elements)


def _xml_manifest_parent_element(
    pending: _PendingXmlManifestParent,
) -> XmlTagElement:
    item_fields: list[XmlStructField] = []
    for field_spec in XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS:
        field = pending.simple_fields.get(field_spec.readback_suffix)
        if field is not None:
            item_fields.append(field)
    reference_fields = _xml_manifest_reference_fields(pending)
    if reference_fields:
        item_fields.append(
            XmlStructField(
                group="stMfs",
                tag="reference",
                value=None,
                uri_path=_xmp_struct_namespace_uri_path("stMfs"),
                struct_fields=reference_fields,
            )
        )
    return XmlTagElement(
        group=pending.group,
        tag=pending.parent_name,
        value=None,
        uri_path=pending.uri_path,
        list_container="Bag",
        struct_list_items=(XmlStructListItem(fields=tuple(item_fields)),),
    )


def _xml_manifest_reference_fields(
    pending: _PendingXmlManifestParent,
) -> tuple[XmlStructField, ...]:
    ordered_fields: list[XmlStructField] = []
    for field_spec in XMP_RESOURCE_REF_FIELD_SPECS:
        field = pending.reference_fields.get(field_spec.readback_suffix)
        if field is not None:
            ordered_fields.append(field)
    return tuple(ordered_fields)


def _xmp_struct_namespace_uri_path(prefix: str) -> str:
    if prefix == "xmpMM":
        return "XMP/XMP-xmpMM"
    return f"XMP/{prefix}"


def _xml_elements_with_forced_missing_tags(
    elements: tuple[XmlTagElement, ...],
    issues: tuple[RenderIssue, ...],
    render: OutputRenderRequest,
) -> tuple[XmlTagElement, ...]:
    if render.format != "xml" or render.missing_tag_value is None or not issues:
        return elements

    forced_elements = list(elements)
    for issue in issues:
        requested_tag = issue.requested_tag
        group = _forced_missing_group_name(issue)
        forced_elements.append(
            XmlTagElement(
                group=group,
                tag=requested_tag.name,
                value=render.missing_tag_value,
                uri_path=group,
            )
        )
    return tuple(forced_elements)


def _sorted_xml_elements(
    elements: tuple[XmlTagElement, ...],
    request: OutputRenderRequest,
) -> tuple[XmlTagElement, ...]:
    if not request.sort_output:
        return elements
    return tuple(
        sorted(
            elements,
            key=lambda element: _sort_output_key(f"{element.group}:{element.tag}", request),
        )
    )


def _list_item_value(values: Sequence[TagValue], index: int) -> TagValue | None:
    try:
        return values[index]
    except IndexError:
        return None


def _render_records_xml(
    records: list[MetadataReadRecord],
    request: OutputRenderRequest,
) -> str:
    xml_encoding = "windows-1252" if _public_output_charset_is_latin(request) else "UTF-8"
    lines = [
        f"<?xml version='1.0' encoding='{xml_encoding}'?>",
        "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>",
    ]
    for record in records:
        lines.extend(_render_record_xml_lines(record, request))
    lines.append("</rdf:RDF>")
    return "\n".join(lines) + "\n"


def _public_output_charset_is_latin(request: OutputRenderRequest) -> bool:
    return request.output_charset.strip().lower() in {"latin", "latin1", "cp1252"}


def _render_record_xml_lines(
    record: MetadataReadRecord,
    request: OutputRenderRequest,
) -> list[str]:
    source_file = _xml_escape(_text_value(record.values.get("SourceFile")))
    lines = [
        "",
        f"<rdf:Description rdf:about='{source_file}'",
        "  xmlns:et='http://ns.exiftool.org/1.0/' et:toolkit='Image::ExifTool ExifModern'",
    ]
    for namespace in _xml_record_namespaces(record):
        lines.append(
            f"  xmlns:{namespace.prefix}='http://ns.exiftool.org/{namespace.uri_path}/1.0/'"
        )
    if request.short_tag_names:
        return _render_short_record_xml_lines(record, request, lines)
    lines[-1] = f"{lines[-1]}>"
    if record.xml_elements:
        for element in record.xml_elements:
            lines.extend(_render_xml_tag_lines(element, request))
    else:
        for key, value in record.values.items():
            if key == "SourceFile":
                continue
            group, tag = _xml_group_and_tag(key)
            lines.extend(
                _render_xml_tag_lines(
                    XmlTagElement(group=group, tag=tag, value=value, uri_path=group),
                    request,
                )
            )
    lines.append("</rdf:Description>")
    return lines


def _render_short_record_xml_lines(
    record: MetadataReadRecord,
    request: OutputRenderRequest,
    description_lines: list[str],
) -> list[str]:
    lines = list(description_lines)
    attribute_values = _short_xml_attribute_values(record)
    if not attribute_values:
        lines[-1] = f"{lines[-1]}/>"
        return lines
    for token, value in attribute_values:
        rendered_value = _text_value(value, list_separator=request.list_separator)
        lines.append(f"  {token}='{_xml_escape(rendered_value)}'")
    lines[-1] = f"{lines[-1]}/>"
    return lines


def _short_xml_attribute_values(record: MetadataReadRecord) -> tuple[tuple[str, TagValue], ...]:
    values: list[tuple[str, TagValue]] = []
    seen_tokens: set[str] = set()
    if record.xml_elements:
        for element in record.xml_elements:
            token = f"{element.group}:{element.tag}"
            if token in seen_tokens:
                continue
            values.append((token, element.value))
            seen_tokens.add(token)
        return tuple(values)
    for key, value in record.values.items():
        if key == "SourceFile":
            continue
        group, tag = _xml_group_and_tag(key)
        token = f"{group}:{tag}"
        if token in seen_tokens:
            continue
        values.append((token, value))
        seen_tokens.add(token)
    return tuple(values)


def _xml_record_groups(record: MetadataReadRecord) -> tuple[str, ...]:
    groups: list[str] = []
    for key in record.values:
        if key == "SourceFile":
            continue
        group, _ = _xml_group_and_tag(key)
        if group not in groups:
            groups.append(group)
    return tuple(groups)


def _xml_record_namespaces(record: MetadataReadRecord) -> tuple[XmlNamespaceBinding, ...]:
    if record.xml_namespaces:
        return record.xml_namespaces
    return tuple(
        XmlNamespaceBinding(prefix=group, uri_path=group) for group in _xml_record_groups(record)
    )


def _xml_elements_for_record(
    graph: ReadGraph,
    render_tags: tuple[str, ...],
    render: OutputRenderRequest,
) -> tuple[XmlTagElement, ...]:
    if not _render_tracks_xml_elements(render):
        return ()

    tags = _xml_selected_graph_tags(graph, render_tags)
    elements: list[XmlTagElement] = []
    for tag in tags:
        group = _xml_output_group_for_tag(tag, render)
        elements.append(
            XmlTagElement(
                group=group,
                tag=tag.name,
                value=tag.value,
                uri_path=_xml_namespace_uri_path_for_prefix(group, tag),
                et_id=_xml_tag_id_attribute(tag, render),
                et_table=tag.provenance.table_name if render.xml_include_table_metadata else None,
            )
        )
    return tuple(elements)


def _render_tracks_xml_elements(render: OutputRenderRequest) -> bool:
    return render.format == "xml" or _render_uses_xml_elements_for_structured_output(render)


def _render_uses_xml_elements_for_structured_output(render: OutputRenderRequest) -> bool:
    # Source: ../exiftool/exiftool lines 2945-2987 route JSON/PHP through the
    # same structured value formatter used after tag extraction; XML element
    # records are ExifModern's shared safe representation for those structures.
    return (
        render.format in {"json", "php", "xml"}
        and render.structured_output
        and not render.short_tag_names
    )


def _xml_selected_graph_tags(graph: ReadGraph, render_tags: tuple[str, ...]) -> tuple[ReadTag, ...]:
    if not render_tags:
        return tuple(graph.tags)

    selected: list[ReadTag] = []
    options = RenderOptions(group_names=True, duplicate_tags=True)
    for render_tag in render_tags:
        requested_tag = requested_tag_from_arg(_renderer_tag_arg(render_tag))
        if requested_tag is None:
            continue
        selected.extend(find_graph_tags(graph, requested_tag, options))
    return tuple(selected)


def _xml_output_group_for_tag(tag: ReadTag, render: OutputRenderRequest) -> str:
    family = _single_output_group_family(render)
    if family is None:
        return tag.provenance.group
    return _output_group_for_tag_provenance(tag.provenance, family) or tag.provenance.group


def _xml_tag_id_attribute(tag: ReadTag, render: OutputRenderRequest) -> str | None:
    if render.xml_tag_id_format == "none" or tag.provenance.tag_id is None:
        return None
    tag_id = tag.provenance.tag_id
    if render.xml_tag_id_format == "hex" and tag_id.isdecimal():
        return f"0x{int(tag_id):04x}"
    return tag_id


def _xml_namespaces_for_elements(
    elements: tuple[XmlTagElement, ...],
) -> tuple[XmlNamespaceBinding, ...]:
    namespaces: list[XmlNamespaceBinding] = []
    seen: set[str] = set()
    for element in elements:
        if element.group not in seen:
            namespaces.append(XmlNamespaceBinding(prefix=element.group, uri_path=element.uri_path))
            seen.add(element.group)
        for field in element.struct_fields:
            _append_xml_struct_field_namespaces(field, namespaces, seen)
        for item in element.struct_list_items:
            for field in item.fields:
                _append_xml_struct_field_namespaces(field, namespaces, seen)
    return tuple(namespaces)


def _append_xml_struct_field_namespaces(
    field: XmlStructField,
    namespaces: list[XmlNamespaceBinding],
    seen: set[str],
) -> None:
    if field.group not in seen:
        namespaces.append(
            XmlNamespaceBinding(prefix=field.group, uri_path=field.uri_path or field.group)
        )
        seen.add(field.group)
    for nested_field in field.struct_fields:
        _append_xml_struct_field_namespaces(nested_field, namespaces, seen)


def _xml_namespaces_for_record(
    graph: ReadGraph,
    record: JsonRecord,
) -> tuple[XmlNamespaceBinding, ...]:
    namespaces: list[XmlNamespaceBinding] = []
    seen: set[str] = set()
    for key in record:
        if key == "SourceFile":
            continue
        prefix, _ = _xml_group_and_tag(key)
        if prefix in seen:
            continue
        tag = _graph_tag_for_record_key(graph, key)
        namespaces.append(
            XmlNamespaceBinding(
                prefix=prefix,
                uri_path=_xml_namespace_uri_path_for_prefix(prefix, tag),
            )
        )
        seen.add(prefix)
    return tuple(namespaces)


def _xml_namespace_uri_path_for_prefix(prefix: str, tag: ReadTag | None) -> str:
    if tag is None:
        return prefix
    family_0 = _tag_provenance_family_group(tag.provenance, 0)
    family_1 = _tag_provenance_family_group(tag.provenance, 1) or tag.provenance.group
    if family_0 == family_1 and family_1.startswith("XMP-"):
        return f"XMP/{family_1}"
    if prefix != family_1 or family_0 is None:
        return prefix
    if family_0 == family_1 and family_1 in {"ExifTool", "File", "Composite", "Unknown"}:
        return family_1
    return f"{family_0}/{family_1}"


def _xml_group_and_tag(key: str) -> tuple[str, str]:
    if ":" not in key:
        return "Unknown", key
    group, tag = key.split(":", 1)
    return group, tag


def _render_xml_tag_lines(
    element: XmlTagElement,
    request: OutputRenderRequest,
) -> list[str]:
    token = f"{element.group}:{element.tag}"
    attributes = _xml_element_attributes(element)
    if element.struct_list_items:
        lines = [f" <{token}{attributes}>", f"  <rdf:{element.list_container}>"]
        for struct_item in element.struct_list_items:
            lines.append("   <rdf:li rdf:parseType='Resource'>")
            for field in struct_item.fields:
                lines.extend(_render_xml_struct_field_lines(field, "    ", request))
            lines.append("   </rdf:li>")
        lines.append(f"  </rdf:{element.list_container}>")
        lines.append(f" </{token}>")
        return lines
    if element.struct_fields:
        lines = [f" <{token}{attributes} rdf:parseType='Resource'>"]
        for field in element.struct_fields:
            lines.extend(_render_xml_struct_field_lines(field, "  ", request))
        lines.append(f" </{token}>")
        return lines
    if isinstance(element.value, list):
        lines = [f" <{token}{attributes}>", f"  <rdf:{element.list_container}>"]
        for item in element.value:
            value_text, value_attributes = _xml_value_text_and_attributes(item, request)
            lines.append(f"   <rdf:li{value_attributes}>{_xml_escape(value_text)}</rdf:li>")
        lines.append(f"  </rdf:{element.list_container}>")
        lines.append(f" </{token}>")
        return lines
    value_text, value_attributes = _xml_value_text_and_attributes(element.value, request)
    return [f" <{token}{attributes}{value_attributes}>{_xml_escape(value_text)}</{token}>"]


def _render_xml_struct_field_lines(
    field: XmlStructField,
    indent: str,
    request: OutputRenderRequest,
) -> list[str]:
    token = f"{field.group}:{field.tag}"
    if field.struct_fields:
        lines = [f"{indent}<{token} rdf:parseType='Resource'>"]
        for nested_field in field.struct_fields:
            lines.extend(_render_xml_struct_field_lines(nested_field, f"{indent} ", request))
        lines.append(f"{indent}</{token}>")
        return lines
    if isinstance(field.value, list):
        lines = [f"{indent}<{token}>", f"{indent} <rdf:Bag>"]
        for item in field.value:
            value_text, value_attributes = _xml_value_text_and_attributes(item, request)
            lines.append(f"{indent}  <rdf:li{value_attributes}>{_xml_escape(value_text)}</rdf:li>")
        lines.append(f"{indent} </rdf:Bag>")
        lines.append(f"{indent}</{token}>")
        return lines
    value_text, value_attributes = _xml_value_text_and_attributes(field.value, request)
    return [f"{indent}<{token}{value_attributes}>{_xml_escape(value_text)}</{token}>"]


def _xml_value_text_and_attributes(
    value: TagValue,
    request: OutputRenderRequest,
) -> tuple[str, str]:
    if isinstance(value, BinaryTagValue) and request.binary_output:
        if _xml_binary_output_requires_base64(value.data):
            return (
                b64encode(value.data).decode("ascii"),
                " rdf:datatype='http://www.w3.org/2001/XMLSchema#base64Binary'",
            )
        return value.data.decode("utf-8"), ""
    return _text_value(value, list_separator=request.list_separator), ""


def _xml_binary_output_requires_base64(data: bytes) -> bool:
    # Source: ../exiftool/exiftool lines 3729-3738 and 3787-3790 encode XML
    # binary values as xsd:base64Binary when they contain XML-invalid controls
    # or are not valid UTF-8.
    if any(byte < 0x20 and byte not in {0x09, 0x0A, 0x0D} for byte in data):
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _xml_element_attributes(element: XmlTagElement) -> str:
    attributes: list[str] = []
    if element.et_id is not None:
        attributes.append(f"et:id='{_xml_escape(element.et_id)}'")
    if element.et_table is not None:
        attributes.append(f"et:table='{_xml_escape(element.et_table)}'")
    return "" if not attributes else " " + " ".join(attributes)


def _xml_escape(value: str) -> str:
    cleaned = "".join(
        "." if _is_invalid_xml_character(character) else character for character in value
    )
    return (
        cleaned.replace("&", "&amp;")
        .replace("'", "&apos;")
        .replace('"', "&quot;")
        .replace(">", "&gt;")
        .replace("<", "&lt;")
    )


def _is_invalid_xml_character(character: str) -> bool:
    codepoint = ord(character)
    return codepoint < 32 and character not in "\t\n\r"


def _output_rendered_tags_for_record(
    graph: ReadGraph,
    record: JsonRecord,
    *,
    include_binary: bool = False,
) -> tuple[OutputRenderedTag, ...]:
    output_tags: list[OutputRenderedTag] = []
    original_file_name = _output_original_file_name(record)
    graph_tags_by_name = _first_graph_tags_by_name(graph)
    for label, value in record.items():
        if label == "SourceFile":
            continue
        if isinstance(value, BinaryTagValue) and not include_binary:
            continue
        tag_name = label.rsplit(":", 1)[-1]
        matching_tag = graph_tags_by_name.get(tag_name)
        if isinstance(value, list) and not _output_rendered_list_has_provenance(matching_tag):
            continue
        group_name = _output_rendered_tag_group_name(label, matching_tag)
        if isinstance(value, BinaryTagListValue):
            if not include_binary:
                continue
            for item in value.items:
                output_tags.append(
                    OutputRenderedTag(
                        label=label,
                        tag_name=tag_name,
                        group_name=group_name,
                        group_names=_output_rendered_tag_group_names(matching_tag, group_name),
                        value=item,
                        suggested_extension=_output_rendered_tag_suggested_extension(
                            item,
                            tag_name,
                        ),
                        original_file_name=original_file_name,
                    )
                )
            continue
        output_tags.append(
            OutputRenderedTag(
                label=label,
                tag_name=tag_name,
                group_name=group_name,
                group_names=_output_rendered_tag_group_names(matching_tag, group_name),
                value=value,
                suggested_extension=_output_rendered_tag_suggested_extension(value, tag_name),
                original_file_name=original_file_name,
            )
        )
    return tuple(output_tags)


def _first_graph_tags_by_name(graph: ReadGraph) -> dict[str, ReadTag]:
    tags_by_name: dict[str, ReadTag] = {}
    for tag in graph.tags:
        tags_by_name.setdefault(tag.name, tag)
    return tags_by_name


def _output_rendered_list_has_provenance(tag: ReadTag | None) -> bool:
    if tag is None:
        return False
    provenance = tag.provenance
    return provenance.source != "" and (
        provenance.group != "" or provenance.family_0_group is not None
    )


def _output_rendered_tag_suggested_extension(value: TagValue, tag_name: str) -> str:
    if isinstance(value, BinaryTagValue) and value.file_extension:
        return value.file_extension.removeprefix(".")
    if isinstance(value, BinaryTagValue):
        if tag_name.lower() in {"exif_profile", "exifprofile"}:
            return "exif"
        return "bin"
    return "txt"


def _output_rendered_tag_group_name(label: str, tag: ReadTag | None) -> str:
    if ":" in label:
        return label.rsplit(":", 1)[0]
    if tag is None:
        return ""
    return tag.provenance.family_0_group or tag.provenance.group


def _output_original_file_name(record: JsonRecord) -> str:
    raw_original = record.get("OriginalRawFileName")
    if isinstance(raw_original, str):
        return raw_original
    original = record.get("OriginalFileName")
    if isinstance(original, str):
        return original
    return ""


def _output_rendered_tag_group_names(tag: ReadTag | None, fallback_group: str) -> tuple[str, ...]:
    if tag is None:
        return (fallback_group, "", "", "", "")
    provenance = tag.provenance
    return (
        provenance.family_0_group or provenance.group,
        provenance.family_1_group or "",
        provenance.family_2_group or "",
        "",
        _public_duplicate_instance_key_for_provenance(provenance) or "",
    )


def read_metadata_deferred(request: MetadataReadRequest) -> MetadataReadResult:
    return MetadataReadResult(
        request=request,
        status="not_yet_implemented",
        diagnostics=(
            _operation_deferred(
                "native_read_service_not_connected",
                "Public metadata read parsing is available, but native read execution "
                "is not connected yet.",
            ),
        ),
    )


def plan_metadata_write(request: MetadataWriteRequest) -> MetadataWritePlan:
    _ensure_public_write_runtime_imports()
    diagnostics = (*_write_dispatch_diagnostics(request), *_write_policy_diagnostics(request))
    return MetadataWritePlan(
        request=request,
        status="not_yet_implemented",
        diagnostics=diagnostics,
    )


def write_metadata(request: MetadataWriteRequest) -> MetadataWriteResult:
    _ensure_public_write_runtime_imports()
    if request.write_output_file is not None:
        return _write_metadata_to_output_file(request)
    policy_diagnostics = _blocking_write_policy_diagnostics(request)
    if policy_diagnostics:
        plan = plan_metadata_write(request)
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=plan.diagnostics,
        )
    side_effect_diagnostics = _write_side_effect_blocker_diagnostics(request)
    if side_effect_diagnostics:
        plan = plan_metadata_write(request)
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=plan.diagnostics,
        )
    if request.riff_webp_metadata_write is not None:
        return _write_riff_webp_metadata(request)
    if request.riff_wav_metadata_write is not None:
        return _write_riff_wav_metadata(request)
    if request.png_chunk_write is not None:
        return _write_png_chunk_metadata(request)
    lowered_png_request = _lower_exiftool_style_png_write_request(request)
    if lowered_png_request is not None:
        return _write_png_chunk_metadata(lowered_png_request)
    png_diagnostic = _unsupported_untyped_png_write_diagnostic(request)
    if png_diagnostic is not None:
        plan = plan_metadata_write(request)
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan.diagnostics, png_diagnostic),
        )

    from exifmodern.public_api.write_executor import execute_metadata_write

    return execute_metadata_write(request)


def _write_metadata_to_output_file(request: MetadataWriteRequest) -> MetadataWriteResult:
    plan = plan_metadata_write(request)
    routing = request.write_output_file
    if routing is None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=plan.diagnostics,
        )
    output_diagnostic = _write_output_file_route_diagnostic(request, routing)
    if output_diagnostic is not None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan.diagnostics, output_diagnostic),
        )
    if routing.stdout:
        if _write_output_route_targets_xmp_sidecar(request, routing):
            return _write_xmp_sidecar_to_output_stdout(
                request,
                routing,
                plan_diagnostics=plan.diagnostics,
            )
        if _write_output_route_targets_exif_sidecar(request, routing):
            return _write_exif_sidecar_to_output_stdout(
                request,
                routing,
                plan_diagnostics=plan.diagnostics,
            )
        selected_output_type = _remaining_selected_write_output_type(request, routing)
        if selected_output_type is not None:
            return _write_remaining_selected_output_to_stdout(
                request,
                routing,
                selected_output_type,
                plan_diagnostics=plan.diagnostics,
            )
        return _write_metadata_to_output_stdout(
            request,
            routing,
            plan_diagnostics=plan.diagnostics,
        )
    if _write_output_route_targets_xmp_sidecar(request, routing):
        return _write_xmp_sidecar_to_output_paths(
            request,
            routing,
            plan_diagnostics=plan.diagnostics,
        )
    if _write_output_route_targets_exif_sidecar(request, routing):
        return _write_exif_sidecar_to_output_paths(
            request,
            routing,
            plan_diagnostics=plan.diagnostics,
        )
    selected_output_type = _remaining_selected_write_output_type(request, routing)
    if selected_output_type is not None:
        return _write_remaining_selected_output_to_paths(
            request,
            routing,
            selected_output_type,
            plan_diagnostics=plan.diagnostics,
        )
    return _write_metadata_to_output_paths(
        request,
        routing,
        plan_diagnostics=plan.diagnostics,
    )


def _write_output_route_targets_xmp_sidecar(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
) -> bool:
    if routing.stdout:
        return _public_write_output_stdout_extension(routing.output_path_template) == ".xmp"
    output_paths = _public_write_output_effective_paths(
        source_paths=request.paths,
        output_path_template=routing.output_path_template,
    )
    return bool(output_paths) and all(path.suffix.lower() == ".xmp" for path in output_paths)


def _write_output_route_targets_exif_sidecar(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
) -> bool:
    if routing.stdout:
        return _public_write_output_stdout_extension(routing.output_path_template) == ".exif"
    output_paths = _public_write_output_effective_paths(
        source_paths=request.paths,
        output_path_template=routing.output_path_template,
    )
    return bool(output_paths) and all(path.suffix.lower() == ".exif" for path in output_paths)


def _write_xmp_sidecar_to_output_stdout(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
    *,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    xmp_output = _xmp_sidecar_write_output_bytes(request)
    if xmp_output.unsupported_diagnostic is not None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, xmp_output.unsupported_diagnostic),
        )
    source_erase_diagnostics: list[Diagnostic] = []
    for source_path in request.paths:
        source_erase_diagnostic = _write_output_erase_source_if_requested(request, source_path)
        if source_erase_diagnostic is not None:
            source_erase_diagnostics.append(source_erase_diagnostic)
    stdout_binary = xmp_output.output_bytes * len(request.paths)
    details: JsonObject = {
        "action": "run_modern_public_write_output_xmp_stdout_executor",
        "source_paths": [path.as_posix() for path in request.paths],
        "output_path_template": routing.output_path_template,
        "overwrite_policy": routing.overwrite_policy,
        "byte_count": len(stdout_binary),
        "byte_counts": [len(xmp_output.output_bytes)] * len(request.paths),
        "source_count": len(request.paths),
        "changed_xmp_properties": xmp_output.changed_xmp_properties,
        "deleted_xmp_properties": xmp_output.deleted_xmp_properties,
        "source_removed": request.policy == "overwrite_original" and not source_erase_diagnostics,
        "evidence_ids": _write_output_file_evidence_ids(),
    }
    if len(request.paths) == 1:
        details["source_path"] = request.paths[0].as_posix()
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=(),
        stdout_binary=stdout_binary,
        diagnostics=(
            *tuple(source_erase_diagnostics),
            Diagnostic(
                code="native_write_output_xmp_stdout_executed",
                message=(
                    "Public write-output -o -.xmp routing created XMP sidecar bytes "
                    "through the bounded XMP sidecar property writer and returned them "
                    "for stdout in source order."
                ),
                details=details,
            ),
        ),
    )


def _write_xmp_sidecar_to_output_paths(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
    *,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    xmp_output = _xmp_sidecar_write_output_bytes(request)
    if xmp_output.unsupported_diagnostic is not None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, xmp_output.unsupported_diagnostic),
        )

    output_paths = _public_write_output_effective_paths(
        source_paths=request.paths,
        output_path_template=routing.output_path_template,
    )
    changed_paths: list[Path] = []
    output_file_details: JsonArray = []
    for source_path, output_path in zip(request.paths, output_paths, strict=True):
        try:
            write_result = write_bytes_transactionally(output_path, xmp_output.output_bytes)
        except OSError as exc:
            return _unsupported_write_output_file_execution_result(
                request,
                plan_diagnostics,
                source_path=source_path,
                output_path=output_path,
                error=str(exc),
                changed_paths=tuple(changed_paths),
            )
        changed_paths.append(output_path)
        output_file_details.append(
            {
                "source_path": source_path.as_posix(),
                "output_path": output_path.as_posix(),
                "bytes_written": write_result.bytes_written,
                "replaced_existing": write_result.replaced_existing,
            }
        )

    source_erase_diagnostics: list[Diagnostic] = []
    for source_path in request.paths:
        source_erase_diagnostic = _write_output_erase_source_if_requested(request, source_path)
        if source_erase_diagnostic is not None:
            source_erase_diagnostics.append(source_erase_diagnostic)

    changed_path_values: JsonArray = [path.as_posix() for path in changed_paths]
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=tuple(changed_paths),
        diagnostics=(
            *tuple(source_erase_diagnostics),
            Diagnostic(
                code="native_write_output_xmp_file_executed",
                message=(
                    "Public write-output -o .xmp routing created XMP sidecar files "
                    "through the bounded XMP sidecar property writer."
                ),
                details={
                    "action": "run_modern_public_write_output_xmp_file_executor",
                    "source_paths": [path.as_posix() for path in request.paths],
                    "output_paths": changed_path_values,
                    "output_path_template": routing.output_path_template,
                    "overwrite_policy": routing.overwrite_policy,
                    "source_count": len(request.paths),
                    "changed_paths": changed_path_values,
                    "output_files": output_file_details,
                    "changed_xmp_properties": xmp_output.changed_xmp_properties,
                    "deleted_xmp_properties": xmp_output.deleted_xmp_properties,
                    "source_removed": request.policy == "overwrite_original"
                    and not source_erase_diagnostics,
                    "evidence_ids": _write_output_file_evidence_ids(),
                },
            ),
        ),
    )


def _xmp_sidecar_write_output_bytes(request: MetadataWriteRequest) -> _XmpSidecarWriteOutputBytes:
    unsupported_diagnostic = _xmp_sidecar_write_output_diagnostic(request)
    if unsupported_diagnostic is not None:
        return _XmpSidecarWriteOutputBytes(
            output_bytes=b"",
            changed_xmp_properties=0,
            deleted_xmp_properties=0,
            unsupported_diagnostic=unsupported_diagnostic,
        )
    plan = build_public_xmp_sidecar_property_write_plan(
        tuple(
            XmpPublicSidecarPropertyAssignment(
                _canonical_xmp_public_sidecar_property_name(assignment.tag),
                assignment.value,
            )
            for assignment in request.assignments
        ),
        request.list_separator,
    )
    if plan.generated_diagnostics:
        return _XmpSidecarWriteOutputBytes(
            output_bytes=b"",
            changed_xmp_properties=0,
            deleted_xmp_properties=0,
            unsupported_diagnostic=_unsupported_xmp_sidecar_write_output_plan_diagnostic(plan),
        )
    result = rewrite_xmp_sidecar_properties(empty_xmp_packet(), plan)
    return _XmpSidecarWriteOutputBytes(
        output_bytes=result.data,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_xmp_properties=result.deleted_xmp_properties,
    )


def _xmp_sidecar_write_output_diagnostic(request: MetadataWriteRequest) -> Diagnostic | None:
    if not request.assignments:
        return _unsupported_xmp_sidecar_write_output_shape_diagnostic(
            reason="missing_assignments",
            message=(
                "Public write-output XMP sidecar creation requires at least one bounded "
                "XMP assignment."
            ),
        )
    unsupported_operations: JsonArray = [
        assignment.tag for assignment in request.assignments if assignment.operation != "set"
    ]
    if unsupported_operations:
        return _unsupported_xmp_sidecar_write_output_shape_diagnostic(
            reason="unsupported_assignment_operation",
            message=(
                "Public write-output XMP sidecar creation supports scalar/list replacement "
                "assignments only, not += or -= mutations."
            ),
            values=unsupported_operations,
        )
    unsupported_tags: JsonArray = [
        assignment.tag
        for assignment in request.assignments
        if _normalized_public_write_tag(assignment.tag) not in _supported_xmp_sidecar_tag_keys()
    ]
    if unsupported_tags:
        return _unsupported_xmp_sidecar_write_output_shape_diagnostic(
            reason="unsupported_xmp_tags",
            message=(
                "Public write-output XMP sidecar creation is bounded to the existing "
                "public XMP sidecar property allowlist."
            ),
            values=unsupported_tags,
        )
    return None


def _unsupported_xmp_sidecar_write_output_shape_diagnostic(
    *,
    reason: str,
    message: str,
    values: JsonArray | None = None,
) -> Diagnostic:
    details: JsonObject = {
        "route_blocker": "write_output_file_type_conversion",
        "reason": reason,
        "supported_tags": [tag for tag in sorted(XMP_PUBLIC_SIDECAR_PROPERTY_NAMES)],
        "evidence_ids": _write_output_file_evidence_ids(),
    }
    if values is not None:
        details["values"] = values
    return Diagnostic(
        code="unsupported_public_write_output_xmp_sidecar_creation",
        message=message,
        details=details,
    )


def _unsupported_xmp_sidecar_write_output_plan_diagnostic(
    plan: XmpPropertyWritePlan,
) -> Diagnostic:
    return Diagnostic(
        code="unsupported_public_write_output_xmp_sidecar_creation",
        message=(
            "Public write-output XMP sidecar creation could not build a bounded "
            "source-backed XMP write plan."
        ),
        details={
            "route_blocker": "write_output_file_type_conversion",
            "diagnostics": [
                {
                    "property_name": diagnostic.property_name,
                    "reason": diagnostic.reason,
                    "detail": diagnostic.detail,
                }
                for diagnostic in plan.generated_diagnostics
            ],
            "evidence_ids": _write_output_file_evidence_ids(),
        },
    )


def _canonical_xmp_public_sidecar_property_name(tag: str) -> str:
    normalized = _normalized_public_write_tag(tag)
    for property_name in XMP_PUBLIC_SIDECAR_PROPERTY_NAMES:
        if property_name.lower() == normalized:
            return property_name
    return tag


def _supported_xmp_sidecar_tag_keys() -> frozenset[str]:
    return frozenset(property_name.lower() for property_name in XMP_PUBLIC_SIDECAR_PROPERTY_NAMES)


def _normalized_public_write_tag(tag: str) -> str:
    return tag.strip().removeprefix("-").lower()


def _write_exif_sidecar_to_output_stdout(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
    *,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    exif_output = _exif_sidecar_write_output_bytes(request)
    if exif_output.unsupported_diagnostic is not None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, exif_output.unsupported_diagnostic),
        )
    source_erase_diagnostics: list[Diagnostic] = []
    for source_path in request.paths:
        source_erase_diagnostic = _write_output_erase_source_if_requested(request, source_path)
        if source_erase_diagnostic is not None:
            source_erase_diagnostics.append(source_erase_diagnostic)
    stdout_binary = exif_output.output_bytes * len(request.paths)
    details: JsonObject = {
        "action": "run_modern_public_write_output_exif_stdout_executor",
        "source_paths": [path.as_posix() for path in request.paths],
        "output_path_template": routing.output_path_template,
        "overwrite_policy": routing.overwrite_policy,
        "byte_count": len(stdout_binary),
        "byte_counts": [len(exif_output.output_bytes)] * len(request.paths),
        "source_count": len(request.paths),
        "changed_exif_tags": list(exif_output.changed_exif_tags),
        "source_removed": request.policy == "overwrite_original" and not source_erase_diagnostics,
        "evidence_ids": _write_output_file_evidence_ids(),
    }
    if len(request.paths) == 1:
        details["source_path"] = request.paths[0].as_posix()
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=(),
        stdout_binary=stdout_binary,
        diagnostics=(
            *tuple(source_erase_diagnostics),
            Diagnostic(
                code="native_write_output_exif_stdout_executed",
                message=(
                    "Public write-output -o -.exif routing created EXIF sidecar bytes "
                    "through the bounded EXIF scalar TIFF materializer and returned them "
                    "for stdout in source order."
                ),
                details=details,
            ),
        ),
    )


def _write_exif_sidecar_to_output_paths(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
    *,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    exif_output = _exif_sidecar_write_output_bytes(request)
    if exif_output.unsupported_diagnostic is not None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan_diagnostics, exif_output.unsupported_diagnostic),
        )

    output_paths = _public_write_output_effective_paths(
        source_paths=request.paths,
        output_path_template=routing.output_path_template,
    )
    changed_paths: list[Path] = []
    output_file_details: JsonArray = []
    for source_path, output_path in zip(request.paths, output_paths, strict=True):
        try:
            write_result = write_bytes_transactionally(output_path, exif_output.output_bytes)
        except OSError as exc:
            return _unsupported_write_output_file_execution_result(
                request,
                plan_diagnostics,
                source_path=source_path,
                output_path=output_path,
                error=str(exc),
                changed_paths=tuple(changed_paths),
            )
        changed_paths.append(output_path)
        output_file_details.append(
            {
                "source_path": source_path.as_posix(),
                "output_path": output_path.as_posix(),
                "bytes_written": write_result.bytes_written,
                "replaced_existing": write_result.replaced_existing,
            }
        )

    source_erase_diagnostics: list[Diagnostic] = []
    for source_path in request.paths:
        source_erase_diagnostic = _write_output_erase_source_if_requested(request, source_path)
        if source_erase_diagnostic is not None:
            source_erase_diagnostics.append(source_erase_diagnostic)

    changed_path_values: JsonArray = [path.as_posix() for path in changed_paths]
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=tuple(changed_paths),
        diagnostics=(
            *tuple(source_erase_diagnostics),
            Diagnostic(
                code="native_write_output_exif_file_executed",
                message=(
                    "Public write-output -o .exif routing created EXIF sidecar files "
                    "through the bounded EXIF scalar TIFF materializer."
                ),
                details={
                    "action": "run_modern_public_write_output_exif_file_executor",
                    "source_paths": [path.as_posix() for path in request.paths],
                    "output_paths": changed_path_values,
                    "output_path_template": routing.output_path_template,
                    "overwrite_policy": routing.overwrite_policy,
                    "source_count": len(request.paths),
                    "changed_paths": changed_path_values,
                    "output_files": output_file_details,
                    "changed_exif_tags": list(exif_output.changed_exif_tags),
                    "source_removed": request.policy == "overwrite_original"
                    and not source_erase_diagnostics,
                    "evidence_ids": _write_output_file_evidence_ids(),
                },
            ),
        ),
    )


def _exif_sidecar_write_output_bytes(request: MetadataWriteRequest) -> _ExifSidecarWriteOutputBytes:
    unsupported_diagnostic = _exif_sidecar_write_output_diagnostic(request)
    if unsupported_diagnostic is not None:
        return _ExifSidecarWriteOutputBytes(
            output_bytes=b"",
            changed_exif_tags=(),
            unsupported_diagnostic=unsupported_diagnostic,
        )
    plan = _exif_sidecar_scalar_write_plan(request.assignments)
    if plan is None:
        return _ExifSidecarWriteOutputBytes(
            output_bytes=b"",
            changed_exif_tags=(),
            unsupported_diagnostic=_unsupported_exif_sidecar_write_output_shape_diagnostic(
                reason="unsupported_exif_values",
                message=(
                    "Public write-output EXIF sidecar creation could not normalize the "
                    "bounded EXIF scalar assignment values."
                ),
                values=[assignment.tag for assignment in request.assignments],
            ),
        )
    return _ExifSidecarWriteOutputBytes(
        output_bytes=create_minimal_exif_scalar_tiff(plan),
        changed_exif_tags=tuple(step.tag_name for step in plan.steps),
    )


def _exif_sidecar_write_output_diagnostic(request: MetadataWriteRequest) -> Diagnostic | None:
    if (
        request.deletes
        or request.delete_order_indexes
        or request.xmp_sidecar_copy_from_file is not None
        or request.exif_sidecar_copy_from_file is not None
        or request.public_copy_from_file is not None
        or request.png_chunk_write is not None
        or request.riff_wav_metadata_write is not None
        or request.riff_webp_metadata_write is not None
    ):
        return _unsupported_exif_sidecar_write_output_shape_diagnostic(
            reason="unsupported_write_shape",
            message=(
                "Public write-output EXIF sidecar creation is bounded to direct EXIF "
                "scalar assignments, not deletes, copy routes, or container-specific "
                "write requests."
            ),
        )
    if not request.assignments:
        return _unsupported_exif_sidecar_write_output_shape_diagnostic(
            reason="missing_assignments",
            message=(
                "Public write-output EXIF sidecar creation requires at least one bounded "
                "EXIF scalar assignment."
            ),
        )
    unsupported_operations: JsonArray = [
        assignment.tag for assignment in request.assignments if assignment.operation != "set"
    ]
    if unsupported_operations:
        return _unsupported_exif_sidecar_write_output_shape_diagnostic(
            reason="unsupported_assignment_operation",
            message=(
                "Public write-output EXIF sidecar creation supports scalar replacement "
                "assignments only, not += or -= mutations."
            ),
            values=unsupported_operations,
        )
    unsupported_tags: JsonArray = [
        assignment.tag
        for assignment in request.assignments
        if not _is_supported_exif_sidecar_scalar_assignment(assignment.tag)
    ]
    if unsupported_tags:
        return _unsupported_exif_sidecar_write_output_shape_diagnostic(
            reason="unsupported_exif_tags",
            message=(
                "Public write-output EXIF sidecar creation is bounded to existing "
                "EXIF scalar TIFF materializer tags."
            ),
            values=unsupported_tags,
        )
    return None


def _exif_sidecar_scalar_write_plan(
    assignments: tuple[MetadataAssignment, ...],
) -> ExifScalarWritePlan | None:
    image_description: str | None = None
    orientation: str | None = None
    modify_date: str | None = None
    artist: str | None = None
    iso: str | None = None
    date_time_original: str | None = None
    focal_length: str | None = None
    scene_capture_type: str | None = None

    for assignment in assignments:
        _group, tag_name = _public_write_tag_parts(assignment.tag)
        match tag_name.lower():
            case "description" | "imagedescription":
                image_description = assignment.value
            case "orientation":
                orientation = assignment.value
            case "modifydate":
                modify_date = assignment.value
            case "artist":
                artist = assignment.value
            case "iso":
                iso = assignment.value
            case "datetimeoriginal":
                date_time_original = assignment.value
            case "focallength":
                focal_length = assignment.value
            case "scenecapturetype":
                scene_capture_type = assignment.value
            case _:
                return None
    try:
        return build_exif_scalar_write_plan(
            image_description=image_description,
            orientation=orientation,
            date_time_original=date_time_original,
            modify_date=modify_date,
            artist=artist,
            iso=iso,
            focal_length=focal_length,
            scene_capture_type=scene_capture_type,
        )
    except ValueError:
        return None


def _is_supported_exif_sidecar_scalar_assignment(tag: str) -> bool:
    group, tag_name = _public_write_tag_parts(tag)
    return group in {"exif", "ifd0", "exififd"} and (
        tag_name.lower() in _PUBLIC_EXIF_SIDECAR_SCALAR_TAG_KEYS
    )


def _public_write_tag_parts(tag: str) -> tuple[str, str]:
    group, separator, tag_name = tag.strip().removeprefix("-").partition(":")
    if separator != ":":
        return "", tag.strip().removeprefix("-")
    return group.lower().replace("-", "_"), tag_name


def _unsupported_exif_sidecar_write_output_shape_diagnostic(
    *,
    reason: str,
    message: str,
    values: JsonArray | None = None,
) -> Diagnostic:
    supported_tags: JsonArray = [
        tag
        for tag in sorted(
            f"EXIF:{tag}" for tag in _PUBLIC_EXIF_SIDECAR_SCALAR_TAG_KEYS if tag != "description"
        )
    ]
    details: JsonObject = {
        "route_blocker": "write_output_file_type_conversion",
        "reason": reason,
        "supported_tags": supported_tags,
        "evidence_ids": _write_output_file_evidence_ids(),
    }
    if values is not None:
        details["values"] = values
    return Diagnostic(
        code="unsupported_public_write_output_exif_sidecar_creation",
        message=message,
        details=details,
    )


def _remaining_selected_write_output_type(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
) -> RemainingSelectedWriteOutputType | None:
    if routing.stdout:
        extension = _public_write_output_stdout_extension(routing.output_path_template)
        if extension is None:
            return None
        return _REMAINING_SELECTED_OUTPUT_SUFFIX_TO_TYPE.get(extension.lower())
    output_paths = _public_write_output_effective_paths(
        source_paths=request.paths,
        output_path_template=routing.output_path_template,
    )
    selected_types = frozenset(
        selected_type
        for output_path in output_paths
        if (
            selected_type := _REMAINING_SELECTED_OUTPUT_SUFFIX_TO_TYPE.get(
                output_path.suffix.lower()
            )
        )
        is not None
    )
    if len(selected_types) != 1 or len(selected_types) != len(
        frozenset(output_path.suffix.lower() for output_path in output_paths)
    ):
        return None
    return next(iter(selected_types))


def _write_remaining_selected_output_to_stdout(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
    selected_output_type: RemainingSelectedWriteOutputType,
    *,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    selected_outputs: list[tuple[Path, _RemainingSelectedWriteOutputBytes]] = []
    for source_path in request.paths:
        selected_output = _remaining_selected_write_output_bytes(
            request,
            source_path,
            selected_output_type,
        )
        if selected_output.unsupported_diagnostic is not None:
            return MetadataWriteResult(
                request=request,
                status="not_yet_implemented",
                diagnostics=(*plan_diagnostics, selected_output.unsupported_diagnostic),
            )
        selected_outputs.append((source_path, selected_output))

    source_erase_diagnostics: list[Diagnostic] = []
    for source_path, _selected_output in selected_outputs:
        source_erase_diagnostic = _write_output_erase_source_if_requested(request, source_path)
        if source_erase_diagnostic is not None:
            source_erase_diagnostics.append(source_erase_diagnostic)
    stdout_binary = b"".join(
        selected_output.output_bytes for _source_path, selected_output in selected_outputs
    )
    byte_counts: JsonArray = [
        len(selected_output.output_bytes) for _source_path, selected_output in selected_outputs
    ]
    details: JsonObject = {
        "action": _remaining_selected_output_stdout_action(selected_output_type),
        "source_paths": [
            source_path.as_posix() for source_path, _selected_output in selected_outputs
        ],
        "output_path_template": routing.output_path_template,
        "selected_output_type": selected_output_type,
        "block_tag": selected_outputs[0][1].block_tag,
        "byte_count": len(stdout_binary),
        "byte_counts": byte_counts,
        "source_count": len(selected_outputs),
        "source_removed": request.policy == "overwrite_original" and not source_erase_diagnostics,
        "evidence_ids": _remaining_selected_output_evidence_ids(selected_output_type),
    }
    changed_exif_tags = tuple(
        dict.fromkeys(
            tag
            for _source_path, selected_output in selected_outputs
            for tag in selected_output.changed_exif_tags
        )
    )
    if changed_exif_tags:
        details["changed_exif_tags"] = list(changed_exif_tags)
    if len(selected_outputs) == 1:
        details["source_path"] = selected_outputs[0][0].as_posix()
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=(),
        stdout_binary=stdout_binary,
        diagnostics=(
            *tuple(source_erase_diagnostics),
            Diagnostic(
                code=_native_remaining_selected_output_code(
                    selected_output_type,
                    stdout=True,
                ),
                message=(
                    _remaining_selected_output_success_message(
                        selected_output_type,
                        route="stdout",
                        block_tag=selected_outputs[0][1].block_tag,
                    )
                ),
                details=details,
            ),
        ),
    )


def _write_remaining_selected_output_to_paths(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
    selected_output_type: RemainingSelectedWriteOutputType,
    *,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    output_paths = _public_write_output_effective_paths(
        source_paths=request.paths,
        output_path_template=routing.output_path_template,
    )
    planned_outputs: list[tuple[Path, Path, _RemainingSelectedWriteOutputBytes]] = []
    for source_path, output_path in zip(request.paths, output_paths, strict=True):
        selected_output = _remaining_selected_write_output_bytes(
            request,
            source_path,
            selected_output_type,
        )
        if selected_output.unsupported_diagnostic is not None:
            return MetadataWriteResult(
                request=request,
                status="not_yet_implemented",
                diagnostics=(*plan_diagnostics, selected_output.unsupported_diagnostic),
            )
        planned_outputs.append((source_path, output_path, selected_output))

    changed_paths: list[Path] = []
    output_file_details: JsonArray = []
    for source_path, output_path, selected_output in planned_outputs:
        try:
            write_result = write_bytes_transactionally(output_path, selected_output.output_bytes)
        except OSError as exc:
            return _unsupported_write_output_file_execution_result(
                request,
                plan_diagnostics,
                source_path=source_path,
                output_path=output_path,
                error=str(exc),
                changed_paths=tuple(changed_paths),
            )
        changed_paths.append(output_path)
        output_file_details.append(
            {
                "source_path": source_path.as_posix(),
                "output_path": output_path.as_posix(),
                "bytes_written": write_result.bytes_written,
                "replaced_existing": write_result.replaced_existing,
                "block_tag": selected_output.block_tag,
                "changed_exif_tags": list(selected_output.changed_exif_tags),
            }
        )

    source_erase_diagnostics: list[Diagnostic] = []
    for source_path, _output_path, _selected_output in planned_outputs:
        source_erase_diagnostic = _write_output_erase_source_if_requested(request, source_path)
        if source_erase_diagnostic is not None:
            source_erase_diagnostics.append(source_erase_diagnostic)

    changed_path_values: JsonArray = [path.as_posix() for path in changed_paths]
    changed_exif_tags = tuple(
        dict.fromkeys(
            tag
            for _source_path, _output_path, selected_output in planned_outputs
            for tag in selected_output.changed_exif_tags
        )
    )
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=tuple(changed_paths),
        diagnostics=(
            *tuple(source_erase_diagnostics),
            Diagnostic(
                code=_native_remaining_selected_output_code(
                    selected_output_type,
                    stdout=False,
                ),
                message=(
                    _remaining_selected_output_success_message(
                        selected_output_type,
                        route="file",
                        block_tag=planned_outputs[0][2].block_tag,
                    )
                ),
                details={
                    "action": _remaining_selected_output_file_action(selected_output_type),
                    "source_paths": [source_path.as_posix() for source_path in request.paths],
                    "output_paths": changed_path_values,
                    "output_path_template": routing.output_path_template,
                    "selected_output_type": selected_output_type,
                    "block_tag": planned_outputs[0][2].block_tag,
                    "source_count": len(planned_outputs),
                    "changed_paths": changed_path_values,
                    "output_files": output_file_details,
                    "changed_exif_tags": list(changed_exif_tags),
                    "source_removed": request.policy == "overwrite_original"
                    and not source_erase_diagnostics,
                    "evidence_ids": _remaining_selected_output_evidence_ids(selected_output_type),
                },
            ),
        ),
    )


def _remaining_selected_write_output_bytes(
    request: MetadataWriteRequest,
    source_path: Path,
    selected_output_type: RemainingSelectedWriteOutputType,
) -> _RemainingSelectedWriteOutputBytes:
    if selected_output_type == "exv":
        return _exv_selected_write_output_bytes(request, source_path)
    unsupported_diagnostic = _remaining_selected_write_output_diagnostic(
        request,
        source_path,
        selected_output_type,
    )
    if unsupported_diagnostic is not None:
        return _RemainingSelectedWriteOutputBytes(
            output_bytes=b"",
            selected_output_type=selected_output_type,
            block_tag=_remaining_selected_output_block_tag(selected_output_type),
            unsupported_diagnostic=unsupported_diagnostic,
        )
    try:
        if selected_output_type == "vrd":
            source_data = source_path.read_bytes()
            output_bytes = extract_canon_vrd_block(source_data)
        elif selected_output_type == "dr4":
            source_data = source_path.read_bytes()
            output_bytes = extract_canon_dr4_block(source_data)
        elif selected_output_type == "icc":
            output_bytes = materialize_source_icc_profile(source_path)
        elif selected_output_type == "mie":
            output_bytes = materialize_source_mie_file(source_path)
        else:
            output_bytes = b""
    except ValueError as exc:
        selected_label = _remaining_selected_output_materializer_label(selected_output_type)
        return _RemainingSelectedWriteOutputBytes(
            output_bytes=b"",
            selected_output_type=selected_output_type,
            block_tag=_remaining_selected_output_block_tag(selected_output_type),
            unsupported_diagnostic=_unsupported_remaining_selected_write_output_diagnostic(
                selected_output_type,
                source_path=source_path,
                reason=(_remaining_selected_output_missing_reason(selected_output_type)),
                message=(
                    f"Public write-output selected {selected_label} output creation "
                    f"could not copy {_remaining_selected_output_block_tag(selected_output_type)} "
                    f"because the source does not contain a valid block: {exc}"
                ),
            ),
        )
    return _RemainingSelectedWriteOutputBytes(
        output_bytes=output_bytes,
        selected_output_type=selected_output_type,
        block_tag=_remaining_selected_output_block_tag(selected_output_type),
    )


def _exv_selected_write_output_bytes(
    request: MetadataWriteRequest,
    source_path: Path,
) -> _RemainingSelectedWriteOutputBytes:
    unsupported_diagnostic = _exv_selected_write_output_diagnostic(request, source_path)
    if unsupported_diagnostic is not None:
        return _RemainingSelectedWriteOutputBytes(
            output_bytes=b"",
            selected_output_type="exv",
            block_tag=_remaining_selected_output_block_tag("exv"),
            unsupported_diagnostic=unsupported_diagnostic,
        )
    try:
        if request.public_copy_from_file is not None:
            copy_source_path = Path(request.public_copy_from_file.source)
            requested_groups = _exv_selected_tags_from_file_groups(request.public_copy_from_file)
            if isinstance(requested_groups, Diagnostic):
                return _RemainingSelectedWriteOutputBytes(
                    output_bytes=b"",
                    selected_output_type="exv",
                    block_tag=_remaining_selected_output_block_tag("exv"),
                    unsupported_diagnostic=requested_groups,
                )
            return _RemainingSelectedWriteOutputBytes(
                output_bytes=materialize_exv_from_source_metadata_groups(
                    copy_source_path,
                    requested_groups,
                ),
                selected_output_type="exv",
                block_tag="EXV",
            )
        if request.assignments:
            comment_value = _exv_comment_assignment_value(request)
            if comment_value is not None:
                return _RemainingSelectedWriteOutputBytes(
                    output_bytes=materialize_exv_from_comment_value(comment_value),
                    selected_output_type="exv",
                    block_tag="Comment",
                    changed_exif_tags=("Comment",),
                )
            ducky_assignments = _exv_ducky_assignments_or_diagnostic(request, source_path)
            if isinstance(ducky_assignments, Diagnostic):
                return _RemainingSelectedWriteOutputBytes(
                    output_bytes=b"",
                    selected_output_type="exv",
                    block_tag=_remaining_selected_output_block_tag("exv"),
                    unsupported_diagnostic=ducky_assignments,
                )
            if ducky_assignments is not None:
                return _RemainingSelectedWriteOutputBytes(
                    output_bytes=materialize_exv_from_source_ducky_assignments(
                        source_path,
                        ducky_assignments,
                    ),
                    selected_output_type="exv",
                    block_tag="Ducky",
                )
            iptc_plan = _exv_iptc_application_write_plan(request)
            if iptc_plan is not None:
                return _RemainingSelectedWriteOutputBytes(
                    output_bytes=materialize_exv_from_source_iptc_application_plan(
                        source_path,
                        iptc_plan,
                    ),
                    selected_output_type="exv",
                    block_tag="Photoshop",
                )
            photoshop_plan = _exv_photoshop_app13_resource_write_plan(request)
            if photoshop_plan is not None:
                return _RemainingSelectedWriteOutputBytes(
                    output_bytes=materialize_exv_from_source_photoshop_app13_plan(
                        source_path,
                        photoshop_plan,
                    ),
                    selected_output_type="exv",
                    block_tag="Photoshop",
                )
            xmp_plan = _exv_xmp_property_write_plan(request)
            if xmp_plan is not None:
                return _RemainingSelectedWriteOutputBytes(
                    output_bytes=materialize_exv_from_generated_xmp_plan(xmp_plan),
                    selected_output_type="exv",
                    block_tag="XMP",
                )
            if _source_has_exif_tiff_payload(source_path):
                plan = _exif_sidecar_scalar_write_plan(request.assignments)
                if plan is None:
                    exif_output = _exif_sidecar_write_output_bytes(request)
                    return _RemainingSelectedWriteOutputBytes(
                        output_bytes=b"",
                        selected_output_type="exv",
                        block_tag=_remaining_selected_output_block_tag("exv"),
                        unsupported_diagnostic=_exv_selected_write_output_from_exif_diagnostic(
                            source_path,
                            exif_output.unsupported_diagnostic,
                        )
                        if exif_output.unsupported_diagnostic is not None
                        else _unsupported_remaining_selected_write_output_diagnostic(
                            "exv",
                            source_path=source_path,
                            reason="unsupported_exif_values",
                            message=(
                                "Public write-output EXV creation could not normalize the "
                                "bounded EXIF scalar assignment values for source EXIF merge."
                            ),
                            values=[assignment.tag for assignment in request.assignments],
                        ),
                    )
                return _RemainingSelectedWriteOutputBytes(
                    output_bytes=materialize_exv_from_source_exif_with_scalar_plan(
                        source_path,
                        plan,
                    ),
                    selected_output_type="exv",
                    block_tag=_remaining_selected_output_block_tag("exv"),
                    changed_exif_tags=tuple(step.tag_name for step in plan.steps),
                )
            exif_output = _exif_sidecar_write_output_bytes(request)
            if exif_output.unsupported_diagnostic is not None:
                return _RemainingSelectedWriteOutputBytes(
                    output_bytes=b"",
                    selected_output_type="exv",
                    block_tag=_remaining_selected_output_block_tag("exv"),
                    unsupported_diagnostic=_exv_selected_write_output_from_exif_diagnostic(
                        source_path,
                        exif_output.unsupported_diagnostic,
                    ),
                )
            return _RemainingSelectedWriteOutputBytes(
                output_bytes=materialize_exv_from_exif_tiff_payload(exif_output.output_bytes),
                selected_output_type="exv",
                block_tag=_remaining_selected_output_block_tag("exv"),
                changed_exif_tags=exif_output.changed_exif_tags,
            )
        return _RemainingSelectedWriteOutputBytes(
            output_bytes=materialize_exv_from_source_metadata(source_path),
            selected_output_type="exv",
            block_tag=_remaining_selected_output_block_tag("exv"),
        )
    except (OSError, ValueError) as exc:
        return _RemainingSelectedWriteOutputBytes(
            output_bytes=b"",
            selected_output_type="exv",
            block_tag=_remaining_selected_output_block_tag("exv"),
            unsupported_diagnostic=_unsupported_remaining_selected_write_output_diagnostic(
                "exv",
                source_path=source_path,
                reason="missing_source_exif_tiff_payload",
                message=(
                    "Public write-output EXV creation can materialize only already-owned "
                    "EXIF/APP13/XMP/ICC/COM payload bytes; no source-backed EXV metadata "
                    f"payload was available: {exc}"
                ),
            ),
        )


def _remaining_selected_write_output_diagnostic(
    request: MetadataWriteRequest,
    source_path: Path,
    selected_output_type: RemainingSelectedWriteOutputType,
) -> Diagnostic | None:
    if (
        request.assignments
        or request.deletes
        or request.delete_order_indexes
        or request.xmp_sidecar_copy_from_file is not None
        or request.exif_sidecar_copy_from_file is not None
        or request.public_copy_from_file is not None
        or request.png_chunk_write is not None
        or request.riff_wav_metadata_write is not None
        or request.riff_webp_metadata_write is not None
    ):
        if selected_output_type in {"icc", "mie"}:
            return _unsupported_remaining_selected_write_output_diagnostic(
                selected_output_type,
                source_path=source_path,
                reason="missing_native_materializer",
                message=_remaining_selected_output_blocker_message(selected_output_type),
                values=[assignment.tag for assignment in request.assignments],
            )
        return _unsupported_remaining_selected_write_output_diagnostic(
            selected_output_type,
            source_path=source_path,
            reason="unsupported_write_shape",
            message=(
                "Public write-output VRD/DR4/ICC creation is bounded to exact source "
                "CanonVRD/CanonDR4/ICC_Profile block copy. Individual selected-output tag "
                "creation or mutation requires a native writer, so no synthetic "
                "selected-output bytes are emitted."
            ),
            values=[assignment.tag for assignment in request.assignments],
        )
    return None


def _exv_selected_write_output_diagnostic(
    request: MetadataWriteRequest,
    source_path: Path,
) -> Diagnostic | None:
    if (
        request.deletes
        or request.delete_order_indexes
        or request.xmp_sidecar_copy_from_file is not None
        or request.exif_sidecar_copy_from_file is not None
        or request.png_chunk_write is not None
        or request.riff_wav_metadata_write is not None
        or request.riff_webp_metadata_write is not None
    ):
        return _unsupported_remaining_selected_write_output_diagnostic(
            "exv",
            source_path=source_path,
            reason="unsupported_write_shape",
            message=(
                "Public write-output EXV creation is bounded to source-backed EXIF TIFF "
                "payload wrapping or direct EXIF scalar assignment materialization; mixed "
                "copy/delete/container requests remain deferred."
            ),
            values=[assignment.tag for assignment in request.assignments],
        )
    if request.public_copy_from_file is not None:
        requested_groups = _exv_selected_tags_from_file_groups(request.public_copy_from_file)
        if isinstance(requested_groups, Diagnostic):
            return requested_groups
    if request.assignments:
        if _exv_comment_assignment_value(request) is not None:
            return None
        ducky_assignments = _exv_ducky_assignments_or_diagnostic(request, source_path)
        if isinstance(ducky_assignments, Diagnostic):
            return ducky_assignments
        if ducky_assignments is not None:
            return None
        if _exv_iptc_application_write_plan(request) is not None:
            return None
        if _exv_photoshop_app13_resource_write_plan(request) is not None:
            return None
        if _exv_xmp_property_write_plan(request) is not None:
            return None
        exif_diagnostic = _exif_sidecar_write_output_diagnostic(request)
        if exif_diagnostic is not None:
            return _exv_selected_write_output_from_exif_diagnostic(
                source_path,
                exif_diagnostic,
            )
    return None


def _exv_selected_tags_from_file_groups(
    copy_request: PublicCopyFromFileRequest,
) -> tuple[ExvSourceMetadataGroup, ...] | Diagnostic:
    if copy_request.source_kind != "explicit_source":
        return _unsupported_exv_selected_tags_from_file_diagnostic(
            copy_request,
            reason="unsupported_tags_from_file_source",
            message=(
                "Public selected-output EXV tagsFromFile projection currently requires an "
                "explicit source file; current-target @ and dynamic source filenames need "
                "per-target ExifTool copy evaluation."
            ),
        )
    if copy_request.alternate_files:
        return _unsupported_exv_selected_tags_from_file_diagnostic(
            copy_request,
            reason="unsupported_alternate_source_file",
            message=(
                "Public selected-output EXV tagsFromFile projection does not yet evaluate "
                "-fileNUM alternate source selectors."
            ),
        )
    source_path = Path(copy_request.source)
    if not source_path.is_file():
        return _unsupported_exv_selected_tags_from_file_diagnostic(
            copy_request,
            reason="missing_tags_from_file_source",
            message="The explicit -tagsFromFile source path does not exist as a file.",
        )

    groups: list[ExvSourceMetadataGroup] = []
    for route in sorted(copy_request.routes, key=lambda item: item.order_index):
        group_result = _exv_selected_tags_from_file_route_group(route)
        if isinstance(group_result, Diagnostic):
            return group_result
        if group_result not in groups:
            groups.append(group_result)
    if not groups:
        return _unsupported_exv_selected_tags_from_file_diagnostic(
            copy_request,
            reason="unsupported_tags_from_file_route",
            message=(
                "Public selected-output EXV tagsFromFile projection found no owned "
                "JPEG-family metadata directory route to copy."
            ),
        )
    return tuple(groups)


def _exv_selected_tags_from_file_route_group(
    route: PublicCopyFromFileRouteRequest,
) -> ExvSourceMetadataGroup | Diagnostic:
    if route.kind == "implicit_all":
        return _unsupported_exv_selected_tags_from_file_route_diagnostic(
            route,
            reason="unsupported_implicit_all_route",
            message=(
                "Implicit -tagsFromFile all-tag projection is still value-level copy "
                "semantics; selected EXV output only owns explicit, group-preserving "
                "JPEG-family directory routes."
            ),
        )
    if route.kind == "datfile_payload":
        return _unsupported_exv_selected_tags_from_file_route_diagnostic(
            route,
            reason="unsupported_datfile_payload_route",
            message=(
                "DATFILE '<=' routes provide raw tag values, not source-backed JPEG "
                "metadata directory bytes for selected EXV output."
            ),
        )
    if route.source_selector is None:
        return _unsupported_exv_selected_tags_from_file_route_diagnostic(
            route,
            reason="missing_source_selector",
            message="The selected EXV copy route is missing a source selector.",
        )
    if route.kind == "redirect_selector":
        if route.destination_selector is None:
            return _unsupported_exv_selected_tags_from_file_route_diagnostic(
                route,
                reason="missing_destination_selector",
                message="The selected EXV redirected copy route is missing a destination selector.",
            )
        source_group = _exv_selected_exact_source_group(route.source_selector)
        destination_group = _exv_selected_exact_source_group(route.destination_selector)
        if source_group is not None and source_group == destination_group:
            return source_group
        return _unsupported_exv_selected_tags_from_file_route_diagnostic(
            route,
            reason="unsupported_redirect_projection",
            message=(
                "Selected EXV tagsFromFile projection owns only exact group-preserving "
                "directory copies such as XMP:all>XMP:all or Photoshop:all>Photoshop:all; "
                "cross-group or scalar redirects require value-level writers."
            ),
        )
    if route.kind == "selector":
        group = _exv_selected_exact_source_group(route.source_selector)
        if group is not None:
            return group
        if _exv_selected_selector_group(route.source_selector) == "all":
            return _unsupported_exv_selected_tags_from_file_route_diagnostic(
                route,
                reason="unsupported_write_shape",
                message=(
                    "Selected EXV tagsFromFile all:all projection remains a value-level "
                    "copy route; exact source-backed directory projection requires explicit "
                    "groups such as EXIF:all, XMP:all, JFIF:all, FlashPix:all, Ducky:all, "
                    "or Adobe:all."
                ),
            )
    return _unsupported_exv_selected_tags_from_file_route_diagnostic(
        route,
        reason="unsupported_tags_from_file_route",
        message=(
            "Selected EXV tagsFromFile projection owns exact source-backed EXIF, "
            "Photoshop, XMP, ICC_Profile, Comment, JFIF, JFXX, CIFF, FlashPix, MPF, "
            "Meta, RMETA, SEAL, AROT, JUMBF, Ducky, and Adobe directory routes only."
        ),
    )


def _exv_selected_exact_source_group(selector: str) -> ExvSourceMetadataGroup | None:
    group_text, separator, tag_text = selector.strip().partition(":")
    group = group_text.strip().lower().replace("-", "_")
    tag = tag_text.strip().lower()
    if separator and tag not in {"all", "*"}:
        return None
    if group == "exif":
        return "EXIF"
    if group == "photoshop":
        return "Photoshop"
    if group == "xmp":
        return "XMP"
    if group in {"icc", "icc_profile"}:
        return "ICC_Profile"
    if group in {"comment", "com"}:
        return "Comment"
    if group == "jfif":
        return "JFIF"
    if group == "jfxx":
        return "JFXX"
    if group == "ciff":
        return "CIFF"
    if group == "flashpix":
        return "FlashPix"
    if group == "mpf":
        return "MPF"
    if group == "meta":
        return "Meta"
    if group == "rmeta":
        return "RMETA"
    if group == "seal":
        return "SEAL"
    if group == "arot":
        return "AROT"
    if group == "jumbf":
        return "JUMBF"
    if group == "ducky":
        return "Ducky"
    if group == "adobe":
        return "Adobe"
    return None


def _exv_selected_selector_group(selector: str) -> str:
    return selector.strip().partition(":")[0].strip().lower().replace("-", "_")


def _unsupported_exv_selected_tags_from_file_diagnostic(
    copy_request: PublicCopyFromFileRequest,
    *,
    reason: str,
    message: str,
) -> Diagnostic:
    return Diagnostic(
        code="unsupported_public_write_output_exv_creation",
        message=message,
        details={
            "route_blocker": "write_output_exv_creation",
            "selected_output_type": "exv",
            "reason": reason,
            "source_path": copy_request.source,
            "routes": [route.raw for route in copy_request.routes],
            "evidence_ids": _remaining_selected_output_evidence_ids("exv"),
        },
    )


def _unsupported_exv_selected_tags_from_file_route_diagnostic(
    route: PublicCopyFromFileRouteRequest,
    *,
    reason: str,
    message: str,
) -> Diagnostic:
    return Diagnostic(
        code="unsupported_public_write_output_exv_creation",
        message=message,
        details={
            "route_blocker": "write_output_exv_creation",
            "selected_output_type": "exv",
            "reason": reason,
            "route": route.raw,
            "source_selector": route.source_selector,
            "destination_selector": route.destination_selector,
            "evidence_ids": _remaining_selected_output_evidence_ids("exv"),
        },
    )


def _exv_comment_assignment_value(request: MetadataWriteRequest) -> str | None:
    if len(request.assignments) != 1:
        return None
    assignment = request.assignments[0]
    group, tag = _public_write_tag_parts(assignment.tag)
    if assignment.operation != "set":
        return None
    if tag.lower() != "comment":
        return None
    if group and group.lower() not in {"file", "comment", "com"}:
        return None
    return assignment.value


def _exv_ducky_assignments_or_diagnostic(
    request: MetadataWriteRequest,
    source_path: Path,
) -> tuple[_ExvDuckyPublicAssignment, ...] | Diagnostic | None:
    if not request.assignments:
        return None
    has_ducky_assignment = any(
        _public_write_tag_parts(assignment.tag)[0] == "ducky" for assignment in request.assignments
    )
    if not has_ducky_assignment:
        return None
    parsed_assignments: list[_ExvDuckyPublicAssignment] = []
    for assignment in request.assignments:
        group, tag_name = _public_write_tag_parts(assignment.tag)
        if group != "ducky":
            return _unsupported_remaining_selected_write_output_diagnostic(
                "exv",
                source_path=source_path,
                reason="unsupported_mixed_ducky_assignment",
                message=(
                    "Selected EXV Ducky APP12 materialization owns Ducky-only "
                    "assignment batches; mixed EXV directory creation order needs "
                    "broader JPEG/EXV WriteDirectory orchestration."
                ),
                values=[item.tag for item in request.assignments],
            )
        if assignment.operation != "set":
            return _unsupported_remaining_selected_write_output_diagnostic(
                "exv",
                source_path=source_path,
                reason="unsupported_ducky_operation",
                message=(
                    "APP12.pm WriteDucky supports replacement, creation, and deletion, "
                    "but selected EXV public routing currently owns set/upsert assignments "
                    "only."
                ),
                values=[assignment.tag],
            )
        ducky_tag = _exv_ducky_public_tag_name(tag_name)
        if ducky_tag is None:
            return _unsupported_remaining_selected_write_output_diagnostic(
                "exv",
                source_path=source_path,
                reason="unsupported_ducky_tag",
                message=(
                    "APP12.pm Ducky defines writable Quality, Comment, and Copyright blocks only."
                ),
                values=[assignment.tag],
            )
        if ducky_tag == "Quality":
            quality_match = re.search(r"\d+", assignment.value)
            if quality_match is None or int(quality_match.group(0)) > 0xFFFFFFFF:
                return _unsupported_remaining_selected_write_output_diagnostic(
                    "exv",
                    source_path=source_path,
                    reason="invalid_ducky_quality_value",
                    message=(
                        "APP12.pm Ducky Quality uses PrintConvInv to extract an unsigned "
                        "integer and stores it as int32u."
                    ),
                    values=[assignment.value],
                )
        parsed_assignments.append((ducky_tag, assignment.value))
    parsed_tuple = tuple(parsed_assignments)
    try:
        materialize_exv_from_source_ducky_assignments(source_path, parsed_tuple)
    except (OSError, ValueError) as exc:
        return _unsupported_remaining_selected_write_output_diagnostic(
            "exv",
            source_path=source_path,
            reason=str(exc),
            message=(
                "Selected EXV Ducky APP12 materialization could not safely emit bytes "
                f"through the source-backed WriteDucky planner: {exc}"
            ),
            values=[item.tag for item in request.assignments],
        )
    return parsed_tuple


def _exv_ducky_public_tag_name(
    tag_name: str,
) -> Literal["Quality", "Comment", "Copyright"] | None:
    normalized = tag_name.lower().replace("-", "")
    if normalized == "quality":
        return "Quality"
    if normalized == "comment":
        return "Comment"
    if normalized == "copyright":
        return "Copyright"
    return None


def _exv_iptc_application_write_plan(
    request: MetadataWriteRequest,
) -> IptcApplicationWritePlan | None:
    if not request.assignments:
        return None
    steps = []
    for assignment in request.assignments:
        group, tag_name = _public_write_tag_parts(assignment.tag)
        if group != "iptc" or assignment.operation != "set":
            return None
        if iptc_application_tag_spec(tag_name) is None:
            return None
        values = _exv_iptc_assignment_values(assignment.value, request.list_separator)
        try:
            steps.append(upsert_text_step(tag_name, values))
        except ValueError:
            return None
    if not steps:
        return None
    return IptcApplicationWritePlan(coalesce_iptc_application_steps(tuple(steps)))


def _exv_photoshop_app13_resource_write_plan(
    request: MetadataWriteRequest,
) -> PhotoshopApp13ResourceWritePlan | None:
    if not request.assignments:
        return None
    if any(assignment.operation != "set" for assignment in request.assignments):
        return None
    return build_photoshop_app13_resource_write_plan(
        tuple((assignment.tag, assignment.value) for assignment in request.assignments)
    )


def _exv_xmp_property_write_plan(
    request: MetadataWriteRequest,
) -> XmpPropertyWritePlan | None:
    if not request.assignments:
        return None
    if any(assignment.operation != "set" for assignment in request.assignments):
        return None
    if any(
        _normalized_public_write_tag(assignment.tag) not in _supported_xmp_sidecar_tag_keys()
        for assignment in request.assignments
    ):
        return None
    plan = build_public_xmp_sidecar_property_write_plan(
        tuple(
            XmpPublicSidecarPropertyAssignment(
                _canonical_xmp_public_sidecar_property_name(assignment.tag),
                assignment.value,
            )
            for assignment in request.assignments
        ),
        request.list_separator,
    )
    if plan.generated_diagnostics:
        return None
    return plan


def _exv_iptc_assignment_values(value: str, list_separator: str | None) -> tuple[str, ...]:
    if list_separator is None:
        return (value,)
    return tuple(value.split(list_separator))


def _source_has_exif_tiff_payload(source_path: Path) -> bool:
    try:
        materialize_exv_from_source_exif(source_path)
    except OSError, ValueError:
        return False
    return True


def _exv_selected_write_output_from_exif_diagnostic(
    source_path: Path,
    exif_diagnostic: Diagnostic,
) -> Diagnostic:
    details = exif_diagnostic.details or {}
    reason = str(details.get("reason", "unsupported_exif_tiff_payload"))
    values = details.get("values")
    value_array = values if isinstance(values, list) else None
    return _unsupported_remaining_selected_write_output_diagnostic(
        "exv",
        source_path=source_path,
        reason=reason,
        message=(
            "Public write-output EXV creation can wrap only the owned EXIF scalar TIFF "
            f"materializer output for assignment routes: {exif_diagnostic.message}"
        ),
        values=value_array,
    )


def _unsupported_remaining_selected_write_output_diagnostic(
    selected_output_type: RemainingSelectedWriteOutputType,
    *,
    source_path: Path,
    reason: str,
    message: str,
    values: JsonArray | None = None,
) -> Diagnostic:
    details: JsonObject = {
        "route_blocker": f"write_output_{selected_output_type}_creation",
        "selected_output_type": selected_output_type,
        "reason": reason,
        "source_path": source_path.as_posix(),
        "evidence_ids": _remaining_selected_output_evidence_ids(selected_output_type),
    }
    if values is not None:
        details["values"] = values
    return Diagnostic(
        code=_unsupported_remaining_selected_output_code(selected_output_type),
        message=message,
        details=details,
    )


def _unsupported_remaining_selected_output_code(
    selected_output_type: RemainingSelectedWriteOutputType,
) -> str:
    if selected_output_type == "vrd":
        return "unsupported_public_write_output_canon_vrd_creation"
    if selected_output_type == "dr4":
        return "unsupported_public_write_output_canon_dr4_creation"
    return f"unsupported_public_write_output_{selected_output_type}_creation"


def _native_remaining_selected_output_code(
    selected_output_type: RemainingSelectedWriteOutputType,
    *,
    stdout: bool,
) -> str:
    route = "stdout" if stdout else "file"
    if selected_output_type in {"exv", "icc", "mie"}:
        return f"native_write_output_{selected_output_type}_{route}_executed"
    return f"native_write_output_canon_{selected_output_type}_{route}_executed"


def _remaining_selected_output_stdout_action(
    selected_output_type: RemainingSelectedWriteOutputType,
) -> str:
    if selected_output_type == "exv":
        return "run_modern_public_write_output_selected_exv_stdout_executor"
    if selected_output_type == "icc":
        return "run_modern_public_write_output_selected_icc_stdout_executor"
    if selected_output_type == "mie":
        return "run_modern_public_write_output_selected_mie_stdout_executor"
    return "run_modern_public_write_output_selected_canon_block_stdout_executor"


def _remaining_selected_output_file_action(
    selected_output_type: RemainingSelectedWriteOutputType,
) -> str:
    if selected_output_type == "exv":
        return "run_modern_public_write_output_selected_exv_file_executor"
    if selected_output_type == "icc":
        return "run_modern_public_write_output_selected_icc_file_executor"
    if selected_output_type == "mie":
        return "run_modern_public_write_output_selected_mie_file_executor"
    return "run_modern_public_write_output_selected_canon_block_file_executor"


def _remaining_selected_output_materializer_label(
    selected_output_type: RemainingSelectedWriteOutputType,
) -> str:
    if selected_output_type == "icc":
        return "ICC/ICM"
    if selected_output_type == "mie":
        return "MIE"
    if selected_output_type in {"vrd", "dr4"}:
        return "Canon"
    return selected_output_type.upper()


def _remaining_selected_output_block_tag(
    selected_output_type: RemainingSelectedWriteOutputType,
) -> str:
    if selected_output_type == "exv":
        return "EXIF"
    if selected_output_type == "vrd":
        return "CanonVRD"
    if selected_output_type == "dr4":
        return "CanonDR4"
    if selected_output_type == "icc":
        return "ICC_Profile"
    return selected_output_type.upper()


def _remaining_selected_output_missing_reason(
    selected_output_type: RemainingSelectedWriteOutputType,
) -> str:
    if selected_output_type == "mie":
        return "missing_standalone_mie_file"
    return f"missing_{_remaining_selected_output_block_tag(selected_output_type).lower()}_block"


def _remaining_selected_output_blocker_message(
    selected_output_type: RemainingSelectedWriteOutputType,
) -> str:
    if selected_output_type == "exv":
        return (
            "Public write-output EXV creation is bounded to already-owned EXIF TIFF "
            "payload materialization; broader JPEG/EXV WriteDirectory segment fanout "
            "remains deferred."
        )
    if selected_output_type == "mie":
        return (
            "Public write-output MIE mutation is blocked because ExifTool creates MIE "
            "through the MIE writer, but this public route only owns exact source-backed "
            "standalone MIE copying."
        )
    return (
        "Public write-output ICC/ICM mutation is blocked because ExifTool creates "
        "standalone ICC profiles through ICC_Profile::WriteICC, but this public "
        "route only owns exact source-backed ICC_Profile copying."
    )


def _remaining_selected_output_success_message(
    selected_output_type: RemainingSelectedWriteOutputType,
    *,
    route: Literal["stdout", "file"],
    block_tag: str,
) -> str:
    if selected_output_type == "exv":
        if route == "stdout":
            return (
                "Public write-output selected EXV routing materialized EXV bytes from "
                "owned EXIF/APP13/XMP/ICC/COM/JPEG-family payloads and returned "
                "concatenated bytes for stdout."
            )
        return (
            "Public write-output selected EXV routing materialized EXV bytes from "
            "owned EXIF/APP13/XMP/ICC/COM/JPEG-family payloads and wrote them to "
            "output files."
        )
    if route == "stdout":
        return (
            f"Public write-output selected "
            f"{_remaining_selected_output_materializer_label(selected_output_type)} output "
            f"routing copied an exact {block_tag} block from each source and returned "
            "concatenated bytes for stdout."
        )
    return (
        f"Public write-output selected "
        f"{_remaining_selected_output_materializer_label(selected_output_type)} output "
        f"routing copied exact {block_tag} source blocks to output files."
    )


def _remaining_selected_output_evidence_ids(
    selected_output_type: RemainingSelectedWriteOutputType,
) -> JsonArray:
    evidence = _write_output_file_evidence_ids()
    if selected_output_type == "exv":
        evidence.extend(
            [
                "public.write.output.selected-exv-writer",
                "public.write.output.selected-xmp-writer",
            ]
        )
    elif selected_output_type == "mie":
        evidence.append("public.write.output.selected-mie-writer")
    elif selected_output_type == "icc":
        evidence.append("public.write.output.selected-icc-writer")
    elif selected_output_type == "vrd":
        evidence.append("public.write.output.selected-vrd")
    else:
        evidence.append("public.write.output.selected-dr4")
    return evidence


def _write_metadata_to_output_stdout(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
    *,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    source_backed_outputs: list[_SourceBackedWriteOutputBytes] = []
    inner_diagnostics: list[Diagnostic] = []
    for source_path in request.paths:
        try:
            source_backed_output = _source_backed_write_output_bytes(request, source_path)
        except OSError as exc:
            return _unsupported_write_output_file_execution_result(
                request,
                (*plan_diagnostics, *tuple(inner_diagnostics)),
                source_path=source_path,
                output_path=None,
                error=str(exc),
            )
        if source_backed_output.inner_result.status != "ok":
            return _source_backed_output_failed_result(
                request,
                source_path,
                source_backed_output,
                diagnostics=tuple(inner_diagnostics),
            )
        inner_diagnostics.extend(source_backed_output.inner_result.diagnostics)
        source_backed_outputs.append(source_backed_output)

    source_erase_diagnostics: list[Diagnostic] = []
    for source_path in request.paths:
        source_erase_diagnostic = _write_output_erase_source_if_requested(request, source_path)
        if source_erase_diagnostic is not None:
            source_erase_diagnostics.append(source_erase_diagnostic)
    stdout_binary = b"".join(output.output_bytes for output in source_backed_outputs)
    source_paths: JsonArray = [path.as_posix() for path in request.paths]
    byte_counts: JsonArray = [len(output.output_bytes) for output in source_backed_outputs]
    details: JsonObject = {
        "action": "run_modern_public_write_output_stdout_executor",
        "source_paths": source_paths,
        "output_path_template": routing.output_path_template,
        "overwrite_policy": routing.overwrite_policy,
        "inner_status": "ok",
        "byte_count": len(stdout_binary),
        "byte_counts": byte_counts,
        "source_count": len(source_backed_outputs),
        "source_removed": request.policy == "overwrite_original" and not source_erase_diagnostics,
        "preserve_file_times": request.preserve_file_times,
        "evidence_ids": _write_output_file_evidence_ids(),
    }
    if len(request.paths) == 1:
        details["source_path"] = request.paths[0].as_posix()
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=(),
        stdout_binary=stdout_binary,
        diagnostics=(
            *tuple(inner_diagnostics),
            *tuple(source_erase_diagnostics),
            Diagnostic(
                code="native_write_output_stdout_executed",
                message=(
                    "Public write-output -o stdout routing executed source-backed "
                    "native writes and returned rewritten file bytes for stdout."
                ),
                details=details,
            ),
        ),
    )


def _write_metadata_to_output_paths(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
    *,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    if _write_output_route_is_literal_multi_source(request, routing):
        return _write_metadata_to_literal_multi_source_output_path(
            request,
            routing,
            plan_diagnostics=plan_diagnostics,
        )
    output_paths = _public_write_output_effective_paths(
        source_paths=request.paths,
        output_path_template=routing.output_path_template,
    )
    planned_outputs: list[_PlannedSourceBackedWriteOutput] = []
    inner_diagnostics: list[Diagnostic] = []
    for source_path, output_path in zip(request.paths, output_paths, strict=True):
        try:
            source_backed_output = _source_backed_write_output_bytes(request, source_path)
        except OSError as exc:
            return _unsupported_write_output_file_execution_result(
                request,
                (*plan_diagnostics, *tuple(inner_diagnostics)),
                source_path=source_path,
                output_path=output_path,
                error=str(exc),
            )
        if source_backed_output.inner_result.status != "ok":
            return _source_backed_output_failed_result(
                request,
                source_path,
                source_backed_output,
                diagnostics=tuple(inner_diagnostics),
            )
        inner_diagnostics.extend(source_backed_output.inner_result.diagnostics)
        planned_outputs.append(
            _PlannedSourceBackedWriteOutput(
                source_path=source_path,
                output_path=output_path,
                source_backed_output=source_backed_output,
            )
        )

    changed_paths: list[Path] = []
    output_file_details: JsonArray = []
    bytes_written_by_output: list[int] = []
    replaced_existing_by_output: list[bool] = []
    for planned_output in planned_outputs:
        source_backed_output = planned_output.source_backed_output
        output_path = planned_output.output_path
        source_path = planned_output.source_path
        try:
            write_result = write_bytes_transactionally(
                output_path,
                source_backed_output.output_bytes,
            )
            if request.preserve_file_times:
                os.utime(
                    output_path,
                    ns=(
                        source_backed_output.source_access_time_ns,
                        source_backed_output.source_modified_time_ns,
                    ),
                )
        except OSError as exc:
            return _unsupported_write_output_file_execution_result(
                request,
                tuple(inner_diagnostics),
                source_path=source_path,
                output_path=output_path,
                error=str(exc),
                changed_paths=tuple(changed_paths),
            )
        changed_paths.append(output_path)
        bytes_written_by_output.append(write_result.bytes_written)
        replaced_existing_by_output.append(write_result.replaced_existing)
        output_file_details.append(
            {
                "source_path": source_path.as_posix(),
                "output_path": output_path.as_posix(),
                "bytes_written": write_result.bytes_written,
                "replaced_existing": write_result.replaced_existing,
            }
        )

    source_erase_diagnostics: list[Diagnostic] = []
    for planned_output in planned_outputs:
        source_erase_diagnostic = _write_output_erase_source_if_requested(
            request,
            planned_output.source_path,
        )
        if source_erase_diagnostic is not None:
            source_erase_diagnostics.append(source_erase_diagnostic)

    source_path_values: JsonArray = [path.as_posix() for path in request.paths]
    changed_path_values: JsonArray = [path.as_posix() for path in changed_paths]
    source_removed_paths: JsonArray = [
        planned_output.source_path.as_posix()
        for planned_output in planned_outputs
        if request.policy == "overwrite_original" and not planned_output.source_path.exists()
    ]
    details: JsonObject = {
        "action": "run_modern_public_write_output_file_executor",
        "source_paths": source_path_values,
        "output_paths": changed_path_values,
        "output_path_template": routing.output_path_template,
        "overwrite_policy": routing.overwrite_policy,
        "source_count": len(planned_outputs),
        "inner_status": "ok",
        "changed_paths": changed_path_values,
        "output_files": output_file_details,
        "source_removed": request.policy == "overwrite_original" and not source_erase_diagnostics,
        "source_removed_paths": source_removed_paths,
        "preserve_file_times": request.preserve_file_times,
        "evidence_ids": _write_output_file_evidence_ids(),
    }
    if len(planned_outputs) == 1:
        details["source_path"] = planned_outputs[0].source_path.as_posix()
        details["output_path"] = changed_paths[0].as_posix()
        details["bytes_written"] = bytes_written_by_output[0]
        details["replaced_existing"] = replaced_existing_by_output[0]

    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=tuple(changed_paths),
        diagnostics=(
            *tuple(inner_diagnostics),
            *tuple(source_erase_diagnostics),
            Diagnostic(
                code="native_write_output_file_executed",
                message=(
                    "Public write-output -o routing executed source-backed native "
                    "writes and emitted the rewritten bytes to output file routes."
                ),
                details=details,
            ),
        ),
    )


def _write_metadata_to_literal_multi_source_output_path(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
    *,
    plan_diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    output_path = _public_write_output_effective_path(
        source_path=request.paths[0],
        output_path_template=routing.output_path_template,
    )
    changed_paths: list[Path] = []
    output_file_details: JsonArray = []
    bytes_written_by_output: list[int] = []
    replaced_existing_by_output: list[bool] = []
    inner_diagnostics: list[Diagnostic] = []
    source_erase_diagnostics: list[Diagnostic] = []
    for source_path in request.paths:
        if output_path.exists():
            return _write_output_literal_multi_source_existing_target_result(
                request,
                (*plan_diagnostics, *tuple(inner_diagnostics), *tuple(source_erase_diagnostics)),
                source_path=source_path,
                output_path=output_path,
                changed_paths=tuple(changed_paths),
                output_file_details=output_file_details,
            )
        try:
            source_backed_output = _source_backed_write_output_bytes(request, source_path)
        except OSError as exc:
            return _unsupported_write_output_file_execution_result(
                request,
                (*plan_diagnostics, *tuple(inner_diagnostics), *tuple(source_erase_diagnostics)),
                source_path=source_path,
                output_path=output_path,
                error=str(exc),
                changed_paths=tuple(changed_paths),
            )
        if source_backed_output.inner_result.status != "ok":
            return _source_backed_output_failed_result(
                request,
                source_path,
                source_backed_output,
                diagnostics=(
                    *plan_diagnostics,
                    *tuple(inner_diagnostics),
                    *tuple(source_erase_diagnostics),
                ),
            )
        inner_diagnostics.extend(source_backed_output.inner_result.diagnostics)
        try:
            write_result = write_bytes_transactionally(
                output_path,
                source_backed_output.output_bytes,
            )
            if request.preserve_file_times:
                os.utime(
                    output_path,
                    ns=(
                        source_backed_output.source_access_time_ns,
                        source_backed_output.source_modified_time_ns,
                    ),
                )
        except OSError as exc:
            return _unsupported_write_output_file_execution_result(
                request,
                (*plan_diagnostics, *tuple(inner_diagnostics), *tuple(source_erase_diagnostics)),
                source_path=source_path,
                output_path=output_path,
                error=str(exc),
                changed_paths=tuple(changed_paths),
            )
        changed_paths.append(output_path)
        bytes_written_by_output.append(write_result.bytes_written)
        replaced_existing_by_output.append(write_result.replaced_existing)
        output_file_details.append(
            {
                "source_path": source_path.as_posix(),
                "output_path": output_path.as_posix(),
                "bytes_written": write_result.bytes_written,
                "replaced_existing": write_result.replaced_existing,
            }
        )
        source_erase_diagnostic = _write_output_erase_source_if_requested(request, source_path)
        if source_erase_diagnostic is not None:
            source_erase_diagnostics.append(source_erase_diagnostic)

    changed_path_values: JsonArray = [path.as_posix() for path in changed_paths]
    source_removed_paths: JsonArray = [
        source_path.as_posix()
        for source_path in request.paths
        if request.policy == "overwrite_original" and not source_path.exists()
    ]
    return MetadataWriteResult(
        request,
        status="ok",
        changed_paths=tuple(changed_paths),
        diagnostics=(
            *tuple(inner_diagnostics),
            *tuple(source_erase_diagnostics),
            Diagnostic(
                code="native_write_output_file_executed",
                message=(
                    "Public write-output -o literal multi-source routing executed "
                    "source-backed native writes in ExifTool source order."
                ),
                details={
                    "action": "run_modern_public_write_output_literal_multi_source_executor",
                    "source_paths": [path.as_posix() for path in request.paths],
                    "output_paths": changed_path_values,
                    "output_path_template": routing.output_path_template,
                    "overwrite_policy": routing.overwrite_policy,
                    "source_count": len(changed_paths),
                    "inner_status": "ok",
                    "changed_paths": changed_path_values,
                    "output_files": output_file_details,
                    "source_removed": request.policy == "overwrite_original"
                    and not source_erase_diagnostics,
                    "source_removed_paths": source_removed_paths,
                    "preserve_file_times": request.preserve_file_times,
                    "evidence_ids": _write_output_file_evidence_ids(),
                    "bytes_written": bytes_written_by_output[-1],
                    "replaced_existing": replaced_existing_by_output[-1],
                },
            ),
        ),
    )


def _write_output_route_is_literal_multi_source(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
) -> bool:
    if routing.stdout or len(request.paths) <= 1:
        return False
    output_path = Path(routing.output_path_template)
    if output_path.is_dir() or routing.output_path_template.endswith(("/", "\\")):
        return False
    return re.search(r"%[-+]?\d*[.:]?\d*[lun]?[dDfFeEtgsocC]", routing.output_path_template) is None


def _write_output_literal_multi_source_existing_target_result(
    request: MetadataWriteRequest,
    diagnostics: tuple[Diagnostic, ...],
    *,
    source_path: Path,
    output_path: Path,
    changed_paths: tuple[Path, ...],
    output_file_details: JsonArray,
) -> MetadataWriteResult:
    return MetadataWriteResult(
        request=request,
        status="not_yet_implemented",
        changed_paths=changed_paths,
        diagnostics=(
            *diagnostics,
            Diagnostic(
                code="unsupported_public_write_output_file_exists",
                message=(
                    "ExifTool -o literal multi-source routing writes sources in order; "
                    f"{output_path} already exists before processing {source_path}, so "
                    "no later source bytes are emitted."
                ),
                details={
                    "source_path": source_path.as_posix(),
                    "output_path": output_path.as_posix(),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "output_files": output_file_details,
                    "route_blocker": "existing_write_output_file_without_overwrite",
                    "evidence_ids": _write_output_file_evidence_ids(),
                },
            ),
        ),
    )


def _source_backed_output_failed_result(
    request: MetadataWriteRequest,
    source_path: Path,
    source_backed_output: _SourceBackedWriteOutputBytes,
    *,
    diagnostics: tuple[Diagnostic, ...],
) -> MetadataWriteResult:
    return MetadataWriteResult(
        request=request,
        status=source_backed_output.inner_result.status,
        diagnostics=(
            *diagnostics,
            *source_backed_output.inner_result.diagnostics,
            Diagnostic(
                code="unsupported_public_write_output_file_execution",
                message=(
                    "Public write-output routing did not emit bytes because the "
                    "source-backed native write did not complete successfully."
                ),
                details={
                    "source_path": source_path.as_posix(),
                    "inner_status": source_backed_output.inner_result.status,
                    "evidence_ids": _write_output_file_evidence_ids(),
                },
            ),
        ),
    )


def _source_backed_write_output_bytes(
    request: MetadataWriteRequest,
    source_path: Path,
) -> _SourceBackedWriteOutputBytes:
    source_stat = source_path.stat()
    source_data = source_path.read_bytes()
    with tempfile.TemporaryDirectory(prefix="exifmodern-write-output-") as temp_directory:
        temp_path = Path(temp_directory) / f"source{source_path.suffix}"
        write_bytes_transactionally(temp_path, source_data)
        inner_request = replace(
            request,
            paths=(temp_path,),
            policy="overwrite_original",
            write_output_file=None,
        )
        inner_result = write_metadata(inner_request)
        output_bytes = temp_path.read_bytes() if inner_result.status == "ok" else b""
    return _SourceBackedWriteOutputBytes(
        inner_result=inner_result,
        output_bytes=output_bytes,
        source_access_time_ns=source_stat.st_atime_ns,
        source_modified_time_ns=source_stat.st_mtime_ns,
    )


def _write_output_erase_source_if_requested(
    request: MetadataWriteRequest,
    source_path: Path,
) -> Diagnostic | None:
    if request.policy != "overwrite_original":
        return None
    try:
        source_path.unlink()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return Diagnostic(
            code="public_write_output_source_erase_failed",
            message=f"Public write-output -overwrite_original could not erase {source_path}: {exc}",
            details={
                "source_path": source_path.as_posix(),
                "error": str(exc),
                "evidence_ids": _write_output_file_evidence_ids(),
            },
        )
    return None


def _unsupported_write_output_file_execution_result(
    request: MetadataWriteRequest,
    diagnostics: tuple[Diagnostic, ...],
    *,
    source_path: Path,
    output_path: Path | None,
    error: str,
    changed_paths: tuple[Path, ...] = (),
) -> MetadataWriteResult:
    details: JsonObject = {
        "source_path": source_path.as_posix(),
        "error": error,
        "changed_paths": [path.as_posix() for path in changed_paths],
        "evidence_ids": _write_output_file_evidence_ids(),
    }
    if output_path is not None:
        details["output_path"] = output_path.as_posix()
    return MetadataWriteResult(
        request=request,
        status="not_yet_implemented",
        changed_paths=changed_paths,
        diagnostics=(
            *diagnostics,
            Diagnostic(
                code="unsupported_public_write_output_file_execution",
                message=f"Public write-output file routing failed: {error}",
                details=details,
            ),
        ),
    )


def _write_output_file_route_diagnostic(
    request: MetadataWriteRequest,
    routing: OutputWriteFileRouting,
) -> Diagnostic | None:
    decision = _classify_public_write_output_route(
        source_paths=request.paths,
        output_path_template=routing.output_path_template,
        stdout=routing.stdout,
        overwrite_policy=routing.overwrite_policy,
        write_policy=request.policy,
    )
    if decision.blocker == "existing_write_output_file_without_overwrite":
        source_path = decision.source_path if decision.source_path is not None else request.paths[0]
        output_path = (
            decision.output_path
            if decision.output_path is not None
            else _public_write_output_effective_path(
                source_path=source_path,
                output_path_template=routing.output_path_template,
            )
        )
        return Diagnostic(
            code="unsupported_public_write_output_file_exists",
            message=decision.message,
            details={
                "source_path": source_path.as_posix(),
                "output_path": output_path.as_posix(),
                "overwrite_policy": routing.overwrite_policy,
                "route_blocker": decision.blocker,
                "evidence_ids": list(decision.evidence_ids),
            },
        )
    if decision.blocker is not None and decision.unsupported_value is not None:
        return _unsupported_write_output_file_diagnostic(
            decision.unsupported_value,
            routing,
            message=decision.message,
            route_blocker=decision.blocker,
            evidence_ids=decision.evidence_ids,
            source_path=decision.source_path,
            output_path=decision.output_path,
        )
    return None


def _unsupported_write_output_file_diagnostic(
    unsupported_value: str,
    routing: OutputWriteFileRouting,
    *,
    message: str | None = None,
    route_blocker: str | None = None,
    evidence_ids: tuple[str, ...] | None = None,
    source_path: Path | None = None,
    output_path: Path | None = None,
) -> Diagnostic:
    details: JsonObject = {
        "unsupported_value": unsupported_value,
        "route_blocker": route_blocker,
        "write_output_file": {
            "output_path_template": routing.output_path_template,
            "overwrite_policy": routing.overwrite_policy,
            "stdout": routing.stdout,
        },
        "evidence_ids": list(evidence_ids or _write_output_file_evidence_ids()),
    }
    if source_path is not None:
        details["source_path"] = source_path.as_posix()
    if output_path is not None:
        details["output_path"] = output_path.as_posix()
    return Diagnostic(
        code="unsupported_public_write_output_file_route",
        message=message
        or (
            "Public write-output -o execution is bounded to one literal output file "
            "for one source-backed write request."
        ),
        details=details,
    )


def _write_output_file_evidence_ids() -> JsonArray:
    return list(_public_write_output_evidence_ids())


def _write_riff_webp_metadata(request: MetadataWriteRequest) -> MetadataWriteResult:
    plan = plan_metadata_write(request)
    webp_request = request.riff_webp_metadata_write
    if webp_request is None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=plan.diagnostics,
        )
    shape_diagnostics = _riff_webp_metadata_write_shape_diagnostics(request, webp_request)
    if shape_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan.diagnostics, *shape_diagnostics),
        )

    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    planned_actions_by_path: JsonArray = []
    for path in request.paths:
        try:
            input_data = path.read_bytes()
            transaction_plan = build_webp_chunk_transaction_plan(
                input_data,
                delete_all_metadata=webp_request.delete_all_metadata,
                allow_output_emission=True,
            )
            if not transaction_plan.can_emit_output:
                execution_diagnostics.append(
                    Diagnostic(
                        code="unsupported_riff_webp_metadata_transaction_plan",
                        message=(
                            "Public RIFF WebP metadata write could not emit a bounded "
                            f"transaction for {path}."
                        ),
                        details={
                            "path": path.as_posix(),
                            "gates": [
                                gate.to_json() for gate in transaction_plan.output_emission_gates
                            ],
                            "evidence_ids": _riff_webp_public_writer_evidence_ids(),
                        },
                    )
                )
                continue
            output = transaction_plan.emit()
            if output != input_data:
                _write_public_rewritten_bytes_transactionally(
                    request,
                    path,
                    output,
                    _public_backup_policy(request),
                )
                changed_paths.append(path)
            planned_actions_by_path.append(
                {
                    "path": path.as_posix(),
                    "deleted_metadata_chunks": transaction_plan.deleted_metadata_chunks,
                    "actions": [action.to_json() for action in transaction_plan.actions],
                    "output_chunk_ids": [
                        chunk.chunk_id.decode("latin-1") for chunk in transaction_plan.output_chunks
                    ],
                }
            )
        except (OSError, ValueError) as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native RIFF WebP metadata write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan.diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan.diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public write executed through the package-local RIFF WebP "
                    "chunk transaction planner."
                ),
                details={
                    "action": "run_modern_riff_webp_metadata_delete_all_writer",
                    "native_callable": (
                        "exifmodern.formats.riff.webp_chunk_transaction_plan."
                        "build_webp_chunk_transaction_plan"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "planned_actions_by_path": planned_actions_by_path,
                    "evidence_ids": _riff_webp_public_writer_evidence_ids(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _riff_webp_metadata_write_shape_diagnostics(
    request: MetadataWriteRequest,
    webp_request: RiffWebpMetadataWriteRequest,
) -> tuple[Diagnostic, ...]:
    if not request.paths:
        return (
            Diagnostic(
                code="unsupported_riff_webp_public_write_shape",
                message="Public RIFF WebP metadata write execution requires a target path.",
                details={"reason": "missing_paths"},
            ),
        )
    if (
        request.assignments
        or request.deletes
        or request.xmp_sidecar_copy_from_file is not None
        or request.exif_sidecar_copy_from_file is not None
        or request.public_copy_from_file is not None
        or request.png_chunk_write is not None
        or request.riff_wav_metadata_write is not None
    ):
        return (
            Diagnostic(
                code="unsupported_mixed_riff_webp_public_write_shape",
                message=(
                    "Public RIFF WebP metadata write execution uses the typed "
                    "riff_webp_metadata_write request and does not mix with scalar "
                    "assignments, public deletes, PNG writes, RIFF WAV/AVI writes, "
                    "or sidecar copy requests."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                    "has_png_chunk_write": request.png_chunk_write is not None,
                    "has_riff_wav_metadata_write": request.riff_wav_metadata_write is not None,
                    "has_xmp_sidecar_copy_from_file": request.xmp_sidecar_copy_from_file
                    is not None,
                    "has_exif_sidecar_copy_from_file": request.exif_sidecar_copy_from_file
                    is not None,
                    "has_public_copy_from_file": request.public_copy_from_file is not None,
                },
            ),
        )
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() != ".webp"
    ]
    if unsupported_paths:
        return (
            Diagnostic(
                code="unsupported_riff_webp_public_write_path",
                message=(
                    "Public RIFF WebP metadata delete-all execution is limited to WebP targets."
                ),
                details={"unsupported_paths": unsupported_paths},
            ),
        )
    if not webp_request.delete_all_metadata:
        return (
            Diagnostic(
                code="unsupported_riff_webp_public_write_shape",
                message=(
                    "Public RIFF WebP metadata execution currently supports only "
                    "delete_all_metadata."
                ),
                details={
                    "reason": "missing_delete_all_metadata",
                    "evidence_ids": _riff_webp_public_writer_evidence_ids(),
                },
            ),
        )
    return ()


def _write_riff_wav_metadata(request: MetadataWriteRequest) -> MetadataWriteResult:
    plan = plan_metadata_write(request)
    riff_request = request.riff_wav_metadata_write
    if riff_request is None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=plan.diagnostics,
        )
    shape_diagnostics = _riff_wav_metadata_write_shape_diagnostics(request, riff_request)
    if shape_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan.diagnostics, *shape_diagnostics),
        )

    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    planned_actions_by_path: JsonArray = []
    for path in request.paths:
        try:
            input_data = path.read_bytes()
            transaction_plan = build_wav_metadata_transaction_plan(
                input_data,
                delete_requests=(RiffMetadataDeleteRequest("all_metadata"),),
                allow_output_emission=True,
            )
            if not transaction_plan.can_emit_output:
                execution_diagnostics.append(
                    Diagnostic(
                        code="unsupported_riff_wav_metadata_transaction_plan",
                        message=(
                            "Public RIFF WAV/AVI delete-all metadata write could not emit "
                            f"a bounded transaction for {path}."
                        ),
                        details={
                            "path": path.as_posix(),
                            "gates": [
                                gate.to_json() for gate in transaction_plan.output_emission_gates
                            ],
                            "evidence_ids": _riff_wav_public_writer_evidence_ids(),
                        },
                    )
                )
                continue
            output = transaction_plan.emit()
            if output != input_data:
                _write_public_rewritten_bytes_transactionally(
                    request,
                    path,
                    output,
                    _public_backup_policy(request),
                )
                changed_paths.append(path)
            planned_actions_by_path.append(
                {
                    "path": path.as_posix(),
                    "deleted_metadata_chunks": sum(
                        1
                        for chunk in transaction_plan.chunks
                        if chunk.metadata_family in {"info", "riff_exif", "xmp", "id3", "c2pa"}
                    ),
                    "deletions": [deletion.to_json() for deletion in transaction_plan.deletions],
                    "full_paths": list(transaction_plan.full_paths),
                }
            )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native RIFF WAV/AVI metadata write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan.diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan.diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public write executed through the package-local RIFF WAV/AVI "
                    "metadata transaction planner."
                ),
                details={
                    "action": "run_modern_riff_wav_metadata_delete_all_writer",
                    "native_callable": (
                        "exifmodern.formats.riff.wav_metadata_transaction_plan."
                        "build_wav_metadata_transaction_plan"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "planned_actions_by_path": planned_actions_by_path,
                    "evidence_ids": _riff_wav_public_writer_evidence_ids(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _riff_wav_metadata_write_shape_diagnostics(
    request: MetadataWriteRequest,
    riff_request: RiffWavMetadataWriteRequest,
) -> tuple[Diagnostic, ...]:
    if not request.paths:
        return (
            Diagnostic(
                code="unsupported_riff_wav_public_write_shape",
                message="Public RIFF WAV/AVI metadata write execution requires a target path.",
                details={"reason": "missing_paths"},
            ),
        )
    if (
        request.assignments
        or request.deletes
        or request.xmp_sidecar_copy_from_file is not None
        or request.exif_sidecar_copy_from_file is not None
        or request.public_copy_from_file is not None
        or request.png_chunk_write is not None
        or request.riff_webp_metadata_write is not None
    ):
        return (
            Diagnostic(
                code="unsupported_mixed_riff_wav_public_write_shape",
                message=(
                    "Public RIFF WAV/AVI metadata write execution uses the typed "
                    "riff_wav_metadata_write request and does not mix with scalar "
                    "assignments, public deletes, PNG writes, RIFF WebP writes, "
                    "or sidecar copy requests."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                    "has_png_chunk_write": request.png_chunk_write is not None,
                    "has_riff_webp_metadata_write": request.riff_webp_metadata_write is not None,
                    "has_xmp_sidecar_copy_from_file": request.xmp_sidecar_copy_from_file
                    is not None,
                    "has_exif_sidecar_copy_from_file": request.exif_sidecar_copy_from_file
                    is not None,
                    "has_public_copy_from_file": request.public_copy_from_file is not None,
                },
            ),
        )
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() not in {".wav", ".avi"}
    ]
    if unsupported_paths:
        return (
            Diagnostic(
                code="unsupported_riff_wav_public_write_path",
                message=(
                    "Public RIFF WAV/AVI metadata delete-all execution is limited to "
                    "WAV/AVI targets."
                ),
                details={"unsupported_paths": unsupported_paths},
            ),
        )
    if not riff_request.delete_all_modeled_metadata:
        return (
            Diagnostic(
                code="unsupported_riff_wav_public_write_shape",
                message=(
                    "Public RIFF WAV/AVI metadata execution currently supports only "
                    "delete_all_modeled_metadata."
                ),
                details={
                    "reason": "missing_delete_all_modeled_metadata",
                    "evidence_ids": _riff_wav_public_writer_evidence_ids(),
                },
            ),
        )
    return ()


def _write_png_chunk_metadata(request: MetadataWriteRequest) -> MetadataWriteResult:
    plan = plan_metadata_write(request)
    png_request = request.png_chunk_write
    if png_request is None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=plan.diagnostics,
        )
    shape_diagnostics = _png_chunk_write_shape_diagnostics(request, png_request)
    if shape_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(*plan.diagnostics, *shape_diagnostics),
        )

    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    planned_actions_by_path: JsonArray = []
    for path in request.paths:
        try:
            input_data = path.read_bytes()
            transaction_plan = build_png_chunk_transaction_plan(
                input_data,
                icc_payload=png_request.icc_payload,
                icc_profile_name=png_request.icc_profile_name,
                exif_payload=png_request.exif_payload,
                xmp_payload=png_request.xmp_payload,
                text_chunks=_png_text_chunk_requests(png_request.text_chunks),
                delete_metadata_groups=png_request.delete_metadata_groups,
                delete_all_metadata=png_request.delete_all_metadata,
                physical_pixel=_png_physical_pixel_request(png_request),
                allow_output_emission=True,
            )
            if not transaction_plan.can_emit_output:
                execution_diagnostics.append(
                    Diagnostic(
                        code="unsupported_png_chunk_transaction_plan",
                        message=(
                            f"Public PNG write could not emit a chunk transaction for {path}."
                        ),
                        details={
                            "path": path.as_posix(),
                            "gates": [
                                gate.to_json() for gate in transaction_plan.output_emission_gates
                            ],
                        },
                    )
                )
                continue
            output = transaction_plan.emit()
            if output != input_data:
                _write_public_rewritten_bytes_transactionally(
                    request,
                    path,
                    output,
                    _public_backup_policy(request),
                )
                changed_paths.append(path)
            planned_actions_by_path.append(
                {
                    "path": path.as_posix(),
                    "actions": [action.to_json() for action in transaction_plan.actions],
                    "output_chunk_types": [
                        chunk.chunk_type.decode("latin-1")
                        for chunk in transaction_plan.output_chunks
                    ],
                }
            )
        except OSError as exc:
            execution_diagnostics.append(
                Diagnostic(
                    code="native_write_failed",
                    message=f"Native PNG chunk write failed for {path}: {exc}",
                    details={"path": path.as_posix(), "error": str(exc)},
                )
            )

    if execution_diagnostics:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(*plan.diagnostics, *execution_diagnostics),
            changed_paths=tuple(changed_paths),
        )

    return MetadataWriteResult(
        request=request,
        status="ok",
        diagnostics=(
            *plan.diagnostics,
            Diagnostic(
                code="native_write_executed",
                message=(
                    "Public write executed through the package-local PNG chunk transaction planner."
                ),
                details={
                    "action": "run_modern_png_chunk_transaction_writer",
                    "native_callable": (
                        "exifmodern.formats.png.chunk_transaction_plan."
                        "build_png_chunk_transaction_plan"
                    ),
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    "policy": request.policy,
                    "preserve_file_times": request.preserve_file_times,
                    "planned_actions_by_path": planned_actions_by_path,
                    "evidence_ids": _png_public_writer_evidence_ids(),
                },
            ),
        ),
        changed_paths=tuple(changed_paths),
    )


def _png_chunk_write_shape_diagnostics(
    request: MetadataWriteRequest,
    png_request: PngChunkWriteRequest,
) -> tuple[Diagnostic, ...]:
    if not request.paths:
        return (
            Diagnostic(
                code="unsupported_png_public_write_shape",
                message="Public PNG chunk write execution requires at least one target path.",
                details={"reason": "missing_paths"},
            ),
        )
    if (
        request.assignments
        or request.deletes
        or request.xmp_sidecar_copy_from_file is not None
        or request.exif_sidecar_copy_from_file is not None
        or request.public_copy_from_file is not None
        or request.riff_webp_metadata_write is not None
    ):
        return (
            Diagnostic(
                code="unsupported_mixed_png_public_write_shape",
                message=(
                    "Public PNG chunk write execution uses the typed png_chunk_write "
                    "request and does not mix with scalar assignments, public deletes, "
                    "RIFF WebP writes, or sidecar copy requests."
                ),
                details={
                    "assignments": [assignment.tag for assignment in request.assignments],
                    "deletes": list(request.deletes),
                    "has_riff_webp_metadata_write": request.riff_webp_metadata_write is not None,
                    "has_xmp_sidecar_copy_from_file": request.xmp_sidecar_copy_from_file
                    is not None,
                    "has_exif_sidecar_copy_from_file": request.exif_sidecar_copy_from_file
                    is not None,
                    "has_public_copy_from_file": request.public_copy_from_file is not None,
                },
            ),
        )
    unsupported_paths: JsonArray = [
        path.as_posix() for path in request.paths if path.suffix.lower() != ".png"
    ]
    if unsupported_paths:
        return (
            Diagnostic(
                code="unsupported_png_public_write_path",
                message="Public PNG chunk write execution is limited to .png targets.",
                details={"unsupported_paths": unsupported_paths},
            ),
        )
    if not _png_request_has_operation(png_request):
        return (
            Diagnostic(
                code="unsupported_png_public_write_shape",
                message="Public PNG chunk write execution requires an explicit operation.",
                details={
                    "reason": "missing_png_chunk_write_operation",
                    "supported_operations": [
                        "text_chunks",
                        "xmp_payload",
                        "exif_payload",
                        "icc_payload",
                        "delete_metadata_groups",
                        "delete_all_metadata",
                    ],
                },
            ),
        )
    if png_request.icc_profile_name is not None and png_request.icc_payload is None:
        return (
            Diagnostic(
                code="unsupported_png_public_write_shape",
                message=(
                    "Public PNG ProfileName writes are supported only with an explicit "
                    "ICC payload; arbitrary ICC directory construction is not exposed."
                ),
                details={
                    "reason": "icc_profile_name_without_icc_payload",
                    "evidence_ids": _png_public_writer_evidence_ids(),
                },
            ),
        )
    return ()


def _lower_exiftool_style_png_write_request(
    request: MetadataWriteRequest,
) -> MetadataWriteRequest | None:
    if not request.paths or not all(path.suffix.lower() == ".png" for path in request.paths):
        return None
    if (
        request.png_chunk_write is not None
        or request.riff_wav_metadata_write is not None
        or request.xmp_sidecar_copy_from_file is not None
        or request.exif_sidecar_copy_from_file is not None
        or request.public_copy_from_file is not None
    ):
        return None
    lowered = _png_chunk_write_request_from_assignments(request.assignments, request.deletes)
    if lowered is None:
        return None
    return replace(
        request,
        assignments=(),
        deletes=(),
        png_chunk_write=lowered,
    )


def _png_chunk_write_request_from_assignments(
    assignments: tuple[MetadataAssignment, ...],
    deletes: tuple[str, ...],
) -> PngChunkWriteRequest | None:
    text_chunks: list[PngTextChunkWriteRequest] = []
    xmp_payload: bytes | None = None
    exif_payload: bytes | None = None
    pixels_per_unit_x: int | None = None
    pixels_per_unit_y: int | None = None
    pixel_units: PngPixelUnits | None = None
    delete_groups: list[str] = []

    for delete in deletes:
        lowered_delete = _png_delete_group_from_public_tag(delete)
        if lowered_delete is None:
            return None
        delete_groups.append(lowered_delete)

    for assignment in assignments:
        tag = assignment.tag.strip()
        if tag.lower() == "exif:artist":
            if assignment.value is None:
                return None
            exif_payload = create_minimal_exif_scalar_tiff(
                ExifScalarWritePlan((artist_step(assignment.value),))
            )
            continue
        if tag.lower() in {"png:pixelsperunitx", "pixelsperunitx"}:
            pixels_per_unit_x = _png_int32u_assignment_value(assignment.value)
            if pixels_per_unit_x is None:
                return None
            continue
        if tag.lower() in {"png:pixelsperunity", "pixelsperunity"}:
            pixels_per_unit_y = _png_int32u_assignment_value(assignment.value)
            if pixels_per_unit_y is None:
                return None
            continue
        if tag.lower() in {"png:pixelunits", "pixelunits"}:
            pixel_units = _png_pixel_units_assignment_value(assignment.value)
            if pixel_units is None:
                return None
            continue
        xmp_text_request = _png_xmp_text_request_from_public_assignment(assignment)
        if xmp_text_request is not None:
            xmp_payload = xmp_text_request.value
            continue
        text_chunk = _png_text_chunk_from_public_assignment(assignment)
        if text_chunk is not None:
            text_chunks.append(text_chunk)
            continue
        return None

    if (
        not text_chunks
        and xmp_payload is None
        and exif_payload is None
        and pixels_per_unit_x is None
        and pixels_per_unit_y is None
        and pixel_units is None
        and not delete_groups
    ):
        return None
    return PngChunkWriteRequest(
        text_chunks=tuple(text_chunks),
        xmp_payload=xmp_payload,
        exif_payload=exif_payload,
        pixels_per_unit_x=pixels_per_unit_x,
        pixels_per_unit_y=pixels_per_unit_y,
        pixel_units=pixel_units,
        delete_metadata_groups=tuple(delete_groups),
    )


def _png_delete_group_from_public_tag(tag: str) -> str | None:
    normalized = tag.strip().lower()
    if normalized in {"png:*", "png:all", "png"}:
        return "PNG"
    if normalized in {"xmp:*", "xmp:all", "xmp"}:
        return "XMP"
    if normalized in {"exif:*", "exif:all", "exif"}:
        return "EXIF"
    if normalized in {"icc_profile:*", "icc_profile:all", "icc_profile"}:
        return "ICC_Profile"
    return None


def _png_text_chunk_from_public_assignment(
    assignment: MetadataAssignment,
) -> PngTextChunkWriteRequest | None:
    tag = assignment.tag.strip()
    group, separator, name = tag.partition(":")
    if separator != ":" or group.lower() != "png" or assignment.value is None:
        return None
    if name.lower() in {"pixelsperunitx", "pixelsperunity", "pixelunits", "profilename"}:
        return None
    keyword, language_code = _png_keyword_and_language_code(name)
    try:
        value = assignment.value.encode("ascii")
    except UnicodeEncodeError:
        return PngTextChunkWriteRequest(
            keyword=keyword,
            value=assignment.value.encode("utf-8"),
            language_code=language_code,
            force_itxt=True,
        )
    if language_code:
        value = assignment.value.encode("utf-8")
    return PngTextChunkWriteRequest(
        keyword=keyword,
        value=value,
        language_code=language_code,
    )


def _png_xmp_text_request_from_public_assignment(
    assignment: MetadataAssignment,
) -> PngTextChunkRequest | None:
    if assignment.value is None:
        return None
    if not assignment.tag.lower().startswith("xmp:description-"):
        return None
    plan = build_png_xmp_itxt_alternate_language_write_plan(
        (
            PngXmpAlternateLanguageWriteRequest(
                tag_name=assignment.tag,
                value=assignment.value.encode("latin-1"),
                charset="Latin",
            ),
        )
    )
    if not plan.can_emit_text_request:
        return None
    return plan.text_request


def _png_keyword_and_language_code(tag_name: str) -> tuple[str, str]:
    keyword, separator, language_code = tag_name.partition("-")
    if separator and language_code:
        return keyword, language_code
    return tag_name, ""


def _png_int32u_assignment_value(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        integer = int(value, 10)
    except ValueError:
        return None
    if integer < 0 or integer > 0xFFFFFFFF:
        return None
    return integer


def _png_pixel_units_assignment_value(value: str | None) -> PngPixelUnits | None:
    integer = _png_int32u_assignment_value(value)
    if integer == 0:
        return 0
    if integer == 1:
        return 1
    return None


def _png_physical_pixel_request(
    request: PngChunkWriteRequest,
) -> PngPhysicalPixelRequest | None:
    if (
        request.pixels_per_unit_x is None
        and request.pixels_per_unit_y is None
        and request.pixel_units is None
    ):
        return None
    return PngPhysicalPixelRequest(
        pixels_per_unit_x=request.pixels_per_unit_x,
        pixels_per_unit_y=request.pixels_per_unit_y,
        pixel_units=request.pixel_units,
    )


def _unsupported_untyped_png_write_diagnostic(request: MetadataWriteRequest) -> Diagnostic | None:
    if not request.paths or not all(path.suffix.lower() == ".png" for path in request.paths):
        return None
    if not (
        request.assignments
        or request.deletes
        or request.xmp_sidecar_copy_from_file is not None
        or request.exif_sidecar_copy_from_file is not None
    ):
        return None
    return Diagnostic(
        code="unsupported_png_public_write_shape",
        message=(
            "Public PNG writes require MetadataWriteRequest.png_chunk_write so the "
            "supported text/XMP/EXIF/ICC chunk operations are explicit and bounded."
        ),
        details={
            "assignments": [assignment.tag for assignment in request.assignments],
            "deletes": list(request.deletes),
            "unsupported_png_profile_surfaces": _unsupported_png_profile_surfaces(request),
            "supported_typed_request": "MetadataWriteRequest.png_chunk_write",
            "evidence_ids": _png_public_writer_evidence_ids(),
        },
    )


def _unsupported_png_profile_surfaces(request: MetadataWriteRequest) -> JsonArray:
    surfaces: JsonArray = []
    for assignment in request.assignments:
        group, separator, tag_name = assignment.tag.partition(":")
        normalized_group = group.lower().replace("-", "_")
        normalized_tag = tag_name.lower().replace(" ", "").replace("_", "")
        if normalized_group in {"iptc", "photoshop"}:
            surfaces.append(assignment.tag)
            continue
        if separator == ":" and "rawprofile" in normalized_tag:
            surfaces.append(assignment.tag)
    for delete in request.deletes:
        group, separator, tag_name = delete.partition(":")
        normalized_group = group.lower().replace("-", "_")
        normalized_tag = tag_name.lower().replace(" ", "").replace("_", "")
        if normalized_group in {"iptc", "photoshop"}:
            surfaces.append(delete)
            continue
        if separator == ":" and "rawprofile" in normalized_tag:
            surfaces.append(delete)
    return surfaces


def _png_request_has_operation(request: PngChunkWriteRequest) -> bool:
    return (
        bool(request.text_chunks)
        or request.xmp_payload is not None
        or request.exif_payload is not None
        or request.icc_payload is not None
        or request.pixels_per_unit_x is not None
        or request.pixels_per_unit_y is not None
        or request.pixel_units is not None
        or bool(request.delete_metadata_groups)
        or request.delete_all_metadata
    )


def _png_text_chunk_requests(
    requests: tuple[PngTextChunkWriteRequest, ...],
) -> tuple[PngTextChunkRequest, ...]:
    return tuple(
        PngTextChunkRequest(
            keyword=request.keyword,
            value=request.value,
            language_code=request.language_code,
            force_itxt=request.force_itxt,
            compress=request.compress,
        )
        for request in requests
    )


def _public_backup_policy(request: MetadataWriteRequest) -> BackupPolicy:
    if request.policy in {"overwrite_original", "overwrite_original_in_place"}:
        return "overwrite_original"
    return "create_backup"


def _write_public_rewritten_bytes_transactionally(
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


def _write_policy_diagnostics(request: MetadataWriteRequest) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    if request.preserve_file_times:
        diagnostics.append(
            Diagnostic(
                code="public_write_preserve_file_times_requested",
                message=(
                    "Public write requested ExifTool -P style filesystem modification "
                    "time preservation for routes whose native transaction supports it."
                ),
                details={
                    "policy": request.policy,
                    "preserve_file_times": True,
                    "evidence_ids": [
                        "public.write.policy.overwrite-preserve-docs",
                        "public.write.policy.overwrite-semantics",
                        "public.write.policy.writer-preserve-time",
                    ],
                },
            )
        )
    if request.policy == "overwrite_original_in_place":
        diagnostics.append(
            Diagnostic(
                code="public_overwrite_original_in_place_requested",
                message=(
                    "Public write requested ExifTool overwrite_original_in_place "
                    "copy-back semantics for native routes that can emit rewritten bytes."
                ),
                details={
                    "policy": request.policy,
                    "preserve_file_times_supported": request.preserve_file_times,
                    "evidence_ids": [
                        "public.write.policy.in-place-option",
                        "public.write.policy.overwrite-semantics",
                        "public.write.policy.in-place-writer",
                    ],
                },
            )
        )
    diagnostics.extend(_blocking_write_policy_diagnostics(request))
    return tuple(diagnostics)


def _blocking_write_policy_diagnostics(request: MetadataWriteRequest) -> tuple[Diagnostic, ...]:
    _ = request
    return ()


_PUBLIC_WRITE_SIDE_EFFECT_TAGS: dict[
    str, tuple[PublicWriteSideEffectKind, str, tuple[str, ...]]
] = {
    "directory": (
        "filesystem_rename_or_move",
        (
            "ExifTool Directory is a writable pseudo System tag that moves files "
            "and creates directories."
        ),
        ("public.write.filesystem.directory", "public.write.filesystem.cli-side-effects"),
    ),
    "filename": (
        "filesystem_rename_or_move",
        "ExifTool FileName is a writable pseudo System tag that renames or moves files.",
        ("public.write.filesystem.filename", "public.write.filesystem.cli-side-effects"),
    ),
    "filemodifydate": (
        "filesystem_timestamp",
        "ExifTool FileModifyDate is a writable pseudo System tag that sets filesystem mtime.",
        ("public.write.filesystem.filemodifydate", "public.write.filesystem.cli-side-effects"),
    ),
    "hardlink": (
        "filesystem_link",
        "ExifTool HardLink is a write-only pseudo System tag that creates a hard link.",
        ("public.write.filesystem.links", "public.write.filesystem.cli-side-effects"),
    ),
    "symlink": (
        "filesystem_link",
        "ExifTool SymLink is a write-only pseudo System tag that creates a symbolic link.",
        ("public.write.filesystem.links", "public.write.filesystem.cli-side-effects"),
    ),
    "testname": (
        "filesystem_dry_run_name",
        "ExifTool TestName is a write-only pseudo tag for dry-run filename side effects.",
        ("public.write.filesystem.testname", "public.write.filesystem.cli-side-effects"),
    ),
}


def _write_side_effect_blocker_diagnostics(
    request: MetadataWriteRequest,
) -> tuple[Diagnostic, ...]:
    blockers = _write_side_effect_blockers(request)
    return tuple(_write_side_effect_blocker_diagnostic(blocker) for blocker in blockers)


def _write_side_effect_blockers(
    request: MetadataWriteRequest,
) -> tuple[PublicWriteSideEffectBlocker, ...]:
    blockers: list[PublicWriteSideEffectBlocker] = []
    for assignment in request.assignments:
        blocker = _write_side_effect_blocker_for_tag(
            assignment.tag,
            requested_operation="assignment",
        )
        if blocker is not None:
            blockers.append(blocker)
    for delete in request.deletes:
        blocker = _write_side_effect_blocker_for_tag(delete, requested_operation="delete")
        if blocker is not None:
            blockers.append(blocker)
    return tuple(blockers)


def _write_side_effect_blocker_for_tag(
    tag: str,
    *,
    requested_operation: PublicWriteOperation,
) -> PublicWriteSideEffectBlocker | None:
    local_name = _normalized_write_side_effect_tag_name(tag)
    side_effect = _PUBLIC_WRITE_SIDE_EFFECT_TAGS.get(local_name)
    if side_effect is None:
        return None
    effect_kind, reason, evidence_ids = side_effect
    return PublicWriteSideEffectBlocker(
        tag=tag,
        effect_kind=effect_kind,
        requested_operation=requested_operation,
        reason=reason,
        evidence_ids=evidence_ids,
    )


def _normalized_write_side_effect_tag_name(tag: str) -> str:
    local_name = tag.strip().removeprefix("-").removesuffix("=").rsplit(":", 1)[-1]
    return "".join(character for character in local_name.lower() if character.isalnum())


def _write_side_effect_blocker_diagnostic(
    blocker: PublicWriteSideEffectBlocker,
) -> Diagnostic:
    return Diagnostic(
        code="public_write_side_effect_blocked",
        message=(
            f"{blocker.requested_operation} for {blocker.tag} requires ExifTool "
            f"{blocker.effect_kind} side effects; public write execution does not "
            "fake filesystem side effects."
        ),
        details={
            "tag": blocker.tag,
            "requested_operation": blocker.requested_operation,
            "effect_kind": blocker.effect_kind,
            "reason": blocker.reason,
            "supported_public_state": (
                "MetadataWriteRequest models metadata assignments/deletes plus typed "
                "container writes; pseudo filesystem write side effects need a "
                "separate public operation model before execution."
            ),
            "evidence_ids": list(blocker.evidence_ids),
        },
    )


def _png_public_writer_evidence_ids() -> JsonArray:
    return ["public.write.png.writer"]


def _riff_wav_public_writer_evidence_ids() -> JsonArray:
    return ["public.write.riff.reader", "public.write.riff.webp-writer"]


def _riff_webp_public_writer_evidence_ids() -> JsonArray:
    return ["public.write.riff.webp-writer"]


def _write_dispatch_diagnostics(request: MetadataWriteRequest) -> tuple[Diagnostic, ...]:
    _ensure_public_write_runtime_imports()
    classifications = _classify_public_write_request(request)
    summary = _write_dispatch_summary_for_classifications(classifications)
    tag_lookup_diagnostics = _tag_lookup_write_selection_diagnostics(request, classifications)
    side_effect_diagnostics = _write_side_effect_blocker_diagnostics(request)
    return (
        Diagnostic(
            code="write_dispatch_capability_summary",
            message=(
                "Public write planning is connected to the typed write-action dispatch "
                "classification registry; native execution remains deferred."
            ),
            details=summary,
        ),
        *(
            _write_dispatch_classification_diagnostic(classification)
            for classification in classifications
        ),
        *tag_lookup_diagnostics,
        *side_effect_diagnostics,
        Diagnostic(
            code="native_write_execution_deferred",
            message=(
                "No public native write execution service is connected yet, so this "
                "request is planned and classified but not executed."
            ),
            details={
                "execution_connected": False,
                "changed_paths": [],
            },
        ),
    )


def _tag_lookup_write_selection_diagnostics(
    request: MetadataWriteRequest,
    classifications: tuple[PublicWriteDispatchClassification, ...],
) -> tuple[Diagnostic, ...]:
    package_path = request.tag_lookup_package_path
    if package_path is None:
        return ()
    tag_names = _tag_lookup_selection_tag_names(classifications)
    if not tag_names:
        return ()
    if not package_path.exists():
        return (
            Diagnostic(
                code="tag_lookup_writable_selection_package_missing",
                message=f"Generated-index package does not exist: {package_path}",
                details={
                    "tag_lookup_package_path": str(package_path),
                    "writable_tag_names": list(tag_names),
                },
            ),
        )
    selections = load_tag_lookup_runtime_service(package_path).select_writable_tags(tag_names)
    return (
        Diagnostic(
            code="tag_lookup_writable_selection_summary",
            message=(
                "Public write planning used the generated TagLookup package to classify "
                "requested writable tags without changing write execution routes."
            ),
            details={
                "tag_lookup_package_path": str(package_path),
                "selection_count": len(selections),
                "outcome_counts": _tag_lookup_selection_outcome_counts(selections),
                "evidence_ids": _tag_lookup_write_selection_evidence_ids(),
            },
        ),
        *(
            _tag_lookup_write_selection_diagnostic(classification, selection)
            for classification, selection in zip(classifications, selections, strict=True)
        ),
    )


def _tag_lookup_selection_tag_names(
    classifications: tuple[PublicWriteDispatchClassification, ...],
) -> tuple[str, ...]:
    return tuple(classification.tag for classification in classifications)


def _tag_lookup_selection_outcome_counts(
    selections: tuple[TagLookupSelectionResult, ...],
) -> JsonObject:
    counts: JsonObject = {
        "resolved": 0,
        "ambiguous": 0,
        "blocked": 0,
        "not_found": 0,
    }
    for selection in selections:
        value = counts[selection.outcome]
        counts[selection.outcome] = value + 1 if isinstance(value, int) else 1
    return counts


def _tag_lookup_write_selection_diagnostic(
    classification: PublicWriteDispatchClassification,
    selection: TagLookupSelectionResult,
) -> Diagnostic:
    return Diagnostic(
        code=f"tag_lookup_writable_selection_{selection.outcome}",
        message=(
            f"TagLookup writable selection for {classification.operation} "
            f"{classification.tag} is {selection.outcome}."
        ),
        details={
            "operation": classification.operation,
            "tag": classification.tag,
            "dispatch_actionability": classification.actionability,
            "selection": tag_lookup_selection_result_to_json_value(selection),
        },
    )


def _tag_lookup_write_selection_evidence_ids() -> JsonArray:
    return ["public.tag-lookup.capability"]


def _classify_public_write_request(
    request: MetadataWriteRequest,
) -> tuple[PublicWriteDispatchClassification, ...]:
    records = load_modern_runnable_write_action_records()
    container_families = _path_container_families(request.paths)
    operations: list[tuple[PublicWriteOperation, str]] = []
    operations.extend(("assignment", assignment.tag) for assignment in request.assignments)
    operations.extend(("delete", tag) for tag in request.deletes)
    if request.xmp_sidecar_copy_from_file is not None:
        operations.extend(
            ("copy_from_file", _xmp_sidecar_copy_route_tag(route))
            for route in request.xmp_sidecar_copy_from_file.routes
        )
    if request.exif_sidecar_copy_from_file is not None:
        operations.extend(
            ("copy_from_file", _exif_sidecar_copy_route_tag(route))
            for route in request.exif_sidecar_copy_from_file.routes
        )
    if request.public_copy_from_file is not None:
        operations.extend(
            ("copy_from_file", route.raw) for route in request.public_copy_from_file.routes
        )
    return tuple(
        _classify_public_write_operation(operation, tag, records, container_families)
        for operation, tag in operations
    )


def _classify_public_write_operation(
    operation: PublicWriteOperation,
    tag: str,
    records: tuple[GoldenWriteModernPlanRecord, ...],
    container_families: frozenset[str],
) -> PublicWriteDispatchClassification:
    candidates = tuple(
        candidate
        for record in records
        if _record_matches_public_write_tag(record, tag, container_families)
        for candidate in (_public_dispatch_candidate(operation, tag, record),)
    )
    return PublicWriteDispatchClassification(
        operation=operation,
        tag=tag,
        actionability=_write_actionability(candidates),
        candidates=candidates,
    )


def _record_matches_public_write_tag(
    record: GoldenWriteModernPlanRecord,
    tag: str,
    container_families: frozenset[str],
) -> bool:
    if (
        container_families
        and record.container_family is not None
        and record.container_family not in container_families
    ):
        return False
    return any(_write_tag_matches_public_request(write_tag, tag) for write_tag in record.write_tags)


def _write_tag_matches_public_request(write_tag: str, requested_tag: str) -> bool:
    write_tag_key = _normalized_write_tag_key(write_tag)
    requested_key = _normalized_write_tag_key(requested_tag)
    if write_tag_key == requested_key:
        return True
    if write_tag_key == "exif" and requested_key in {"exif:*", "exif:all"}:
        return True
    if requested_key.endswith(":all"):
        return write_tag_key.startswith(f"{requested_key.removesuffix(':all')}:")
    if write_tag_key.endswith(":*"):
        return requested_key.startswith(f"{write_tag_key.removesuffix(':*')}:")
    if ":" not in requested_key:
        return _write_tag_local_name(write_tag_key) == requested_key
    return False


def _normalized_write_tag_key(tag: str) -> str:
    return tag.strip().removeprefix("-").lower()


def _write_tag_local_name(tag: str) -> str:
    return tag.rsplit(":", 1)[-1]


def _path_container_families(paths: tuple[Path, ...]) -> frozenset[str]:
    families: set[str] = set()
    for path in paths:
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg", ".jpe"}:
            families.add("jpeg")
        elif suffix in {".tif", ".tiff"}:
            families.add("tiff")
        elif suffix == ".xmp":
            families.add("xmp_sidecar")
        elif suffix == ".exif":
            families.add("exif_sidecar")
        elif suffix == ".webp":
            families.add("riff_webp")
        elif suffix == ".png":
            families.add("png")
        elif suffix == ".heic":
            families.add("heic")
        elif suffix == ".jp2":
            families.add("jpeg2000")
        elif suffix == ".jxl":
            families.add("jxl")
    return frozenset(families)


def _public_dispatch_candidate(
    operation: PublicWriteOperation,
    tag: str,
    record: GoldenWriteModernPlanRecord,
) -> PublicWriteDispatchCandidate:
    capability = classify_write_action(record.action)
    return PublicWriteDispatchCandidate(
        operation=operation,
        tag=tag,
        action=record.action,
        status=capability.status.value,
        reason=capability.reason,
        request_id=record.request_id,
        request_path=record.request_path,
        container_family=record.container_family,
        write_tags=record.write_tags,
        native_callables=tuple(
            native_callable_to_json(entry) for entry in capability.native_callables
        ),
    )


def _xmp_sidecar_copy_route_tag(route: XmpSidecarCopyRouteRequest) -> str:
    return f"{route.source_group}:* > {route.destination_group}:*"


def _exif_sidecar_copy_route_tag(route: ExifSidecarCopyRouteRequest) -> str:
    if route.tag_pattern:
        return f"{route.source_group}:{route.tag_pattern}"
    return route.source_group


def _write_actionability(candidates: tuple[PublicWriteDispatchCandidate, ...]) -> str:
    statuses = {candidate.status for candidate in candidates}
    if WriteActionCapabilityStatus.NATIVE_CALLABLE_AVAILABLE.value in statuses:
        return WriteActionCapabilityStatus.NATIVE_CALLABLE_AVAILABLE.value
    if WriteActionCapabilityStatus.GENERATED_PLAN_AVAILABLE.value in statuses:
        return WriteActionCapabilityStatus.GENERATED_PLAN_AVAILABLE.value
    if WriteActionCapabilityStatus.UNSUPPORTED.value in statuses:
        return WriteActionCapabilityStatus.UNSUPPORTED.value
    return WriteActionCapabilityStatus.UNKNOWN.value


def _write_dispatch_summary_for_classifications(
    classifications: tuple[PublicWriteDispatchClassification, ...],
) -> JsonObject:
    status_counts = _empty_write_actionability_counts()
    candidate_count = 0
    native_callable_count = 0
    generated_plan_count = 0
    for classification in classifications:
        status_counts[WriteActionCapabilityStatus(classification.actionability)] += 1
        candidate_count += len(classification.candidates)
        for candidate in classification.candidates:
            if candidate.status == WriteActionCapabilityStatus.NATIVE_CALLABLE_AVAILABLE.value:
                native_callable_count += 1
            elif candidate.status == WriteActionCapabilityStatus.GENERATED_PLAN_AVAILABLE.value:
                generated_plan_count += 1

    return {
        "planning_connected": True,
        "execution_connected": False,
        "registry": "exifmodern.write_action_dispatch",
        "requested_operation_count": len(classifications),
        "candidate_count": candidate_count,
        "native_callable_candidate_count": native_callable_count,
        "generated_plan_candidate_count": generated_plan_count,
        "operation_counts_by_actionability": status_counts_to_json(status_counts),
        "execution_blocker": "native_write_execution_deferred",
        "evidence_ids": ["public.write.exact-copy.writer-routing"],
    }


def _empty_write_actionability_counts() -> dict[WriteActionCapabilityStatus, int]:
    return {status: 0 for status in WriteActionCapabilityStatus}


def _write_dispatch_classification_diagnostic(
    classification: PublicWriteDispatchClassification,
) -> Diagnostic:
    if classification.candidates:
        message = (
            f"{classification.operation} for {classification.tag} has "
            f"{len(classification.candidates)} source-backed dispatch candidate(s); "
            f"best actionability is {classification.actionability}."
        )
    else:
        message = (
            f"{classification.operation} for {classification.tag} has no matching "
            "source-backed dispatch candidate in the current registry/artifact slice."
        )
    return Diagnostic(
        code=classification.actionability,
        message=message,
        details={
            "operation": classification.operation,
            "tag": classification.tag,
            "actionability": classification.actionability,
            "candidates": [
                _public_dispatch_candidate_to_json(candidate)
                for candidate in classification.candidates
            ],
        },
    )


def _public_dispatch_candidate_to_json(candidate: PublicWriteDispatchCandidate) -> JsonObject:
    return {
        "operation": candidate.operation,
        "tag": candidate.tag,
        "action": candidate.action,
        "status": candidate.status,
        "reason": candidate.reason,
        "request_id": candidate.request_id,
        "request_path": candidate.request_path,
        "container_family": candidate.container_family,
        "write_tags": list(candidate.write_tags),
        "native_callables": list(candidate.native_callables),
    }


def render_output(request: OutputRenderRequest) -> OutputRenderResult:
    diagnostics = [
        _operation_deferred(
            "renderer_not_connected",
            "Public output rendering is not connected to metadata results yet.",
        )
    ]
    output_file_routing_diagnostic = output_file_routing_not_connected_diagnostic(request)
    if output_file_routing_diagnostic is not None:
        diagnostics.append(output_file_routing_diagnostic)
    return OutputRenderResult(
        request=request,
        status="not_yet_implemented",
        diagnostics=tuple(diagnostics),
    )


def inspect_file(request: FileInspectRequest) -> FileInspectResult:
    records: list[FileInspectRecord] = []
    diagnostics: list[Diagnostic] = []
    for path in request.paths:
        try:
            record = _inspect_public_file(path, diagnostics)
            if record is not None:
                records.append(record)
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    code="file_inspect_failed",
                    message=f"Unable to inspect {path}: {exc}",
                )
            )
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(
                    code="unsupported_file_format",
                    message=f"{path}: {exc}",
                )
            )

    return FileInspectResult(
        request=request,
        status="ok" if records and not diagnostics else "unsupported",
        diagnostics=tuple(diagnostics),
        records=tuple(records),
    )


def _inspect_public_file(
    path: Path,
    diagnostics: list[Diagnostic],
) -> FileInspectRecord | None:
    prefix = _read_public_file_prefix(path, _PUBLIC_INSPECT_PREFIX_BYTES)
    if prefix.startswith(b"\xff\xd8\xff"):
        from exifmodern.formats.jpeg.container import build_jpeg_inspection

        graph = build_dispatched_read_graph(path, display_path=path.as_posix())
        values, _ = graph_record_for_request(graph, path.as_posix(), ("-G1", "-a"))
        for graph_diagnostic in graph.diagnostics:
            diagnostics.append(
                Diagnostic(
                    code="inspect_graph_diagnostic",
                    message=f"{path}: {graph_diagnostic}",
                )
            )
        return FileInspectRecord(
            path=path,
            file_type="JPEG",
            values=values,
            structure=build_jpeg_inspection(path),
        )
    if prefix.startswith(RIFF_SIGNATURES):
        from exifmodern.formats.riff.read_graph_adapter import riff_reader_plan_to_read_graph
        from exifmodern.formats.riff.reader_plan import build_riff_reader_plan

        file_size = path.stat().st_size
        if file_size > _PUBLIC_INSPECT_FULL_READ_LIMIT_BYTES:
            diagnostics.append(_large_public_riff_inspect_deferred_diagnostic(path, file_size))
            return None
        data = read_public_document_payload(
            path,
            byte_limit=_PUBLIC_INSPECT_FULL_READ_LIMIT_BYTES,
        )
        if data is None:
            diagnostics.append(_large_public_riff_inspect_deferred_diagnostic(path, file_size))
            return None
        plan = build_riff_reader_plan(data)
        file_type = plan.file_type or "unknown"
        if file_type not in PUBLIC_RIFF_FILE_TYPES:
            raise ValueError(f"RIFF form type is not in the public inspect surface: {file_type}")
        graph = riff_reader_plan_to_read_graph(
            plan,
            path.as_posix(),
            filesystem_path=path,
        )
        values, _ = graph_record_for_request(graph, path.as_posix(), ("-G1", "-a"))
        for graph_diagnostic in graph.diagnostics:
            diagnostics.append(
                Diagnostic(
                    code="inspect_graph_diagnostic",
                    message=f"{path}: {graph_diagnostic}",
                )
            )
        return FileInspectRecord(
            path=path,
            file_type=file_type,
            values=values,
            structure=plan.to_json(),
        )
    raise ValueError("unsupported public inspect signature")


def _read_public_file_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


def _large_public_riff_inspect_deferred_diagnostic(path: Path, file_size: int) -> Diagnostic:
    return Diagnostic(
        code="large_riff_inspect_full_read_deferred",
        message=(
            f"{path}: public RIFF inspect is bounded to files up to "
            f"{_PUBLIC_INSPECT_FULL_READ_LIMIT_BYTES} bytes until structure planning "
            "can stream large chunks."
        ),
        details={
            "path": path.as_posix(),
            "file_size": file_size,
            "limit_bytes": _PUBLIC_INSPECT_FULL_READ_LIMIT_BYTES,
            "evidence_ids": ["public.read.inspect.large-riff"],
        },
    )


def query_capabilities(request: CapabilityQueryRequest) -> CapabilityQueryResult:
    tag_lookup_capabilities, capability_diagnostics = _query_tag_lookup_capabilities(request)
    writable_selections, selection_diagnostics = _query_tag_lookup_writable_selections(request)
    tag_lookup_summary, summary_diagnostics = _query_tag_lookup_summary(
        request,
        tag_lookup_capabilities,
        writable_selections,
    )
    return CapabilityQueryResult(
        request=request,
        status="ok",
        capabilities=(
            CapabilityDescriptor(
                name="capabilities",
                status="ok",
                summary="Reports the public interface surface and explicit implementation status.",
            ),
            CapabilityDescriptor(
                name="read",
                status="ok",
                summary=(
                    "Reads the native public subset through package-local read graphs "
                    "with text, JSON, XML, CSV, and tab rendering."
                ),
                surfaces=(
                    CapabilitySurfaceDescriptor(
                        name="native-jpeg-basic-read",
                        status="ok",
                        summary=(
                            "Reads bounded JPEG file, image, IFD0, EXIF, and GPS "
                            "metadata exposed by the native read graph."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="native-riff-read",
                        status="ok",
                        summary=(
                            "Reads bounded RIFF/WAV/AVI/WebP metadata exposed by the "
                            "native RIFF read graph."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="native-png-textual-read",
                        status="ok",
                        summary=(
                            "Reads bounded PNG textual metadata exposed by the native "
                            "PNG textual read graph."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="native-bmp-read",
                        status="ok",
                        summary=(
                            "Reads bounded BMP/DIB header metadata exposed by the native "
                            "BMP read graph."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="native-mp3-read",
                        status="ok",
                        summary=(
                            "Reads bounded MP3 audio header and ID3 metadata exposed by "
                            "the native MPEG/ID3 read graph."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="native-matroska-read",
                        status="ok",
                        summary=(
                            "Reads bounded Matroska/EBML metadata exposed by the native "
                            "Matroska read graph."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="binary-external-output-routing-model",
                        status="ok",
                        summary=(
                            "Models stdout binary extraction, per-source output files, "
                            "per-tag output files, overwrite/append policy, -Wext filters, "
                            "and unsafe binary gating; executes the safe per-source -w "
                            "text/JSON read-output subset."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="safe-path-file-order",
                        status="ok",
                        summary=(
                            "Executes the path-backed -fileOrder FileName/SourceFile subset; "
                            "metadata-driven ordering remains explicitly deferred."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="bounded-output-filter",
                        status="ok",
                        summary=(
                            "Applies the source-backed ExifTool.t transliteration-only "
                            "output Filter subset during public read rendering."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="full-exiftool-read-surface",
                        status="not_yet_implemented",
                        summary=(
                            "Formats and tags outside the native public read subset "
                            "remain deferred."
                        ),
                    ),
                ),
            ),
            CapabilityDescriptor(
                name="inspect",
                status="ok",
                summary=("Inspects the native public subset with graph-backed metadata records."),
                surfaces=(
                    CapabilitySurfaceDescriptor(
                        name="native-jpeg-inspect",
                        status="ok",
                        summary="Inspects bounded JPEG/basic container structure.",
                    ),
                    CapabilitySurfaceDescriptor(
                        name="native-riff-inspect",
                        status="ok",
                        summary="Inspects bounded RIFF/WAV/AVI/WebP container structure.",
                    ),
                    CapabilitySurfaceDescriptor(
                        name="full-exiftool-inspect-surface",
                        status="not_yet_implemented",
                        summary=(
                            "Container inspection outside the native public inspect "
                            "subset remains deferred."
                        ),
                    ),
                ),
            ),
            CapabilityDescriptor(
                name="api-configuration",
                status="ok",
                summary=(
                    "Recognizes reviewed ExifTool API/configuration entry points without "
                    "loading arbitrary Perl plug-in modules."
                ),
                surfaces=(
                    CapabilitySurfaceDescriptor(
                        name="reviewed-read-api-option-allow-list",
                        status="ok",
                        summary=(
                            "Applies bounded -api Duplicates, PrintConv, Unknown, RequestAll, "
                            "Charset, Lang, MissingTagValue, ListJoin/ListSep, ListItem, and "
                            "transliteration-only Filter read effects; other API options remain "
                            "diagnostics."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="config-file-deferred",
                        status="not_yet_implemented",
                        summary=(
                            "Recognizes ExifTool -config placement rules but does not load "
                            "legacy Perl configuration files."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="perl-plugin-loading-blocked",
                        status="not_yet_implemented",
                        summary=(
                            "Recognizes -use as ExifTool plug-in loading and blocks it "
                            "instead of treating module names as public tags."
                        ),
                    ),
                ),
            ),
            CapabilityDescriptor(
                name="geolocation",
                status="ok",
                summary=(
                    "Lists package-backed Geolocation database rows through the "
                    "runtime geolocation service."
                ),
                surfaces=(
                    CapabilitySurfaceDescriptor(
                        name="public-listgeo-runtime",
                        status="ok",
                        summary=(
                            "Supports ExifTool-style -listgeo CSV output for the "
                            "generated geolocation package, including -sort, -lang, "
                            "and API options GeolocFeature, GeolocMinPop, and "
                            "GeolocAltNames."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="full-geolocation-query-cli",
                        status="not_yet_implemented",
                        summary=(
                            "General geolocation lookup/write CLI behavior outside "
                            "listgeo remains deferred to the runtime service boundary."
                        ),
                    ),
                ),
            ),
            CapabilityDescriptor(
                name="write",
                status="ok",
                summary=(
                    "Executes the proven bounded public write families; unsupported "
                    "write shapes remain explicitly deferred."
                ),
                surfaces=(
                    CapabilitySurfaceDescriptor(
                        name="xmp-sidecar-scalar-write",
                        status="ok",
                        summary="Executes bounded scalar writes to XMP sidecar files.",
                    ),
                    CapabilitySurfaceDescriptor(
                        name="jpeg-gps-coordinate-write",
                        status="ok",
                        summary="Executes bounded JPEG EXIF GPS coordinate writes.",
                    ),
                    CapabilitySurfaceDescriptor(
                        name="jpeg-exif-scalar-write",
                        status="ok",
                        summary="Executes bounded JPEG IFD0/ExifIFD scalar writes.",
                    ),
                    CapabilitySurfaceDescriptor(
                        name="xmp-sidecar-family2-delete",
                        status="ok",
                        summary=(
                            "Executes bounded XMP sidecar family-2 Image and Camera group deletes."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="xmp-sidecar-namespace-delete",
                        status="ok",
                        summary=(
                            "Executes bounded XMP sidecar namespace deletes for source-backed "
                            "XMP family-1 groups."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="xmp-sidecar-copy-from-file",
                        status="ok",
                        summary=(
                            "Executes bounded typed XMP sidecar tagsFromFile copy routes "
                            "through the package-local copy planner and writer."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="exif-sidecar-copy-from-file",
                        status="ok",
                        summary=(
                            "Executes bounded typed EXIF sidecar tagsFromFile copy routes "
                            "through the package-local EXIF sidecar copy planner and writer."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="png-chunk-transaction-write",
                        status="ok",
                        summary=(
                            "Executes typed bounded PNG text, XMP, EXIF, ICC, and metadata "
                            "delete chunk transactions through the package-local PNG planner."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="riff-wav-avi-delete-all-modeled-metadata",
                        status="ok",
                        summary=(
                            "Executes typed bounded WAV/AVI delete-all-modeled metadata "
                            "transactions through the package-local RIFF planner."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="riff-webp-delete-all-metadata",
                        status="ok",
                        summary=(
                            "Executes typed bounded WebP delete-all metadata transactions "
                            "through the package-local RIFF/WebP chunk planner."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="typed-sidecar-copy-route-contract",
                        status="ok",
                        summary=(
                            "Typed copy-from-file execution accepts XMP routes "
                            "ALL:* > ALL:*, EXIF:* > XMP:*, and XMP:* > XMP:*, "
                            "plus EXIF sidecar routes EXIF, EXIF:all, and EXIF:*."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="preserve-file-times-write-policy",
                        status="ok",
                        summary=(
                            "MetadataWriteRequest.preserve_file_times executes ExifTool "
                            "-P style FileModifyDate preservation for bounded public "
                            "routes whose native transactions expose timestamp policy."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="overwrite-original-in-place-policy",
                        status="not_yet_implemented",
                        summary=(
                            "overwrite_original_in_place is modeled separately and "
                            "diagnosed because ExifTool preserves broader original file "
                            "attributes through an in-place update step."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="unsupported-mixed-public-copy-write-shapes",
                        status="not_yet_implemented",
                        summary=(
                            "Public copy-from-file execution rejects requests mixed "
                            "with scalar assignments, deletes, or another typed sidecar "
                            "copy request instead of attempting partial ExifTool copy behavior."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="public-delete-and-copy-write-shapes",
                        status="not_yet_implemented",
                        summary=(
                            "List add/delete, untyped copy-from-file, broader group deletes, "
                            "unsupported copy route pairings, and CLI/top-level typed sidecar "
                            "copy construction remain deferred."
                        ),
                    ),
                    CapabilitySurfaceDescriptor(
                        name="full-exiftool-write-surface",
                        status="not_yet_implemented",
                        summary=(
                            "Write families outside XMP sidecar scalars/deletes/copy routes, "
                            "EXIF sidecar copy routes, JPEG GPS, and JPEG EXIF scalars remain "
                            "deferred."
                        ),
                    ),
                ),
            ),
        ),
        diagnostics=(*capability_diagnostics, *selection_diagnostics, *summary_diagnostics),
        tag_lookup_summary=tag_lookup_summary,
        tag_lookup_capabilities=tag_lookup_capabilities,
        tag_lookup_writable_selections=writable_selections,
    )


def list_geolocation(request: PublicGeolocationListRequest) -> PublicGeolocationListResult:
    if not request.package_path.is_file():
        return PublicGeolocationListResult(
            request=request,
            status="unsupported",
            diagnostics=(
                Diagnostic(
                    code="geolocation_package_missing",
                    message=(
                        "public -listgeo requires the generated geolocation package at "
                        f"{request.package_path}"
                    ),
                    details={
                        "geolocation_package_path": str(request.package_path),
                        "evidence_ids": ["public.geolocation.listgeo"],
                    },
                ),
            ),
        )
    from exifmodern.services.geolocation_runtime import (
        geolocation_list_request_from_source_options,
        load_geolocation_runtime_service,
    )

    runtime_request = geolocation_list_request_from_source_options(
        language_code=request.language_code,
        include_alternate_names=request.include_alternate_names,
        sort_by_city=request.sort_by_city,
        min_population=request.min_population,
        feature_option=request.feature_option,
        include_header=request.include_header,
        include_title=request.include_title,
    )
    if request.sort_mode != "database" and not request.sort_by_city:
        runtime_request = replace(runtime_request, sort_mode=request.sort_mode)
    service = load_geolocation_runtime_service(request.package_path)
    runtime_result = service.list_public(runtime_request)
    return PublicGeolocationListResult(
        request=request,
        status="ok",
        rows=runtime_result.rows,
        alternate_names_column_available=runtime_result.alternate_names_column_available,
        rendered_text="\n".join(runtime_result.csv_lines(runtime_request)) + "\n",
    )


def query_tag_lookup(request: PublicTagLookupRequest) -> PublicTagLookupResult:
    if not request.package_path.exists():
        return PublicTagLookupResult(
            request=request,
            status="unsupported",
            diagnostics=(
                Diagnostic(
                    code="tag_lookup_package_missing",
                    message=f"Generated-index package does not exist: {request.package_path}",
                    details={
                        "tag_lookup_package_path": str(request.package_path),
                        "tag_names": list(request.tag_names),
                        "writable_tag_names": list(request.writable_tag_names),
                        "evidence_ids": list(_tag_lookup_capability_evidence_ids()),
                    },
                ),
            ),
        )

    from exifmodern.services.tag_lookup_runtime import (
        TagLookupRuntimeRequest,
        load_tag_lookup_runtime_service,
        tag_lookup_capability_from_result,
    )

    service = load_tag_lookup_runtime_service(request.package_path)
    tag_results = tuple(
        service.resolve(TagLookupRuntimeRequest(tag_name)) for tag_name in request.tag_names
    )
    writable_selections = service.select_writable_tags(request.writable_tag_names)
    capabilities = tuple(tag_lookup_capability_from_result(result) for result in tag_results)
    summary, diagnostics = _query_tag_lookup_summary(
        CapabilityQueryRequest(
            tag_names=request.tag_names,
            writable_tag_names=request.writable_tag_names,
            tag_lookup_package_path=request.package_path,
        ),
        capabilities,
        writable_selections,
    )
    return PublicTagLookupResult(
        request=request,
        status="unsupported" if diagnostics else "ok",
        diagnostics=diagnostics,
        tag_results=tag_results,
        writable_selections=writable_selections,
        summary=summary,
    )


def _query_tag_lookup_capabilities(
    request: CapabilityQueryRequest,
) -> tuple[tuple[TagLookupRuntimeCapability, ...], tuple[Diagnostic, ...]]:
    if not request.tag_names:
        return (), ()
    package_path = request.tag_lookup_package_path
    if package_path is None:
        return (
            (),
            (
                Diagnostic(
                    code="tag_lookup_package_required",
                    message=(
                        "Tag capability detail requires a generated-index package path; "
                        "the default capability report does not load package data."
                    ),
                    details={"tag_names": list(request.tag_names)},
                ),
            ),
        )
    if not package_path.exists():
        return (
            (),
            (
                Diagnostic(
                    code="tag_lookup_package_missing",
                    message=f"Generated-index package does not exist: {package_path}",
                    details={
                        "tag_lookup_package_path": str(package_path),
                        "tag_names": list(request.tag_names),
                    },
                ),
            ),
        )
    from exifmodern.services.tag_lookup_runtime import load_tag_lookup_runtime_service

    service = load_tag_lookup_runtime_service(package_path)
    return service.capabilities_for_tags(request.tag_names), ()


def _query_tag_lookup_writable_selections(
    request: CapabilityQueryRequest,
) -> tuple[tuple[TagLookupSelectionResult, ...], tuple[Diagnostic, ...]]:
    if not request.writable_tag_names:
        return (), ()
    package_path = request.tag_lookup_package_path
    if package_path is None:
        return (
            (),
            (
                Diagnostic(
                    code="tag_lookup_writable_selection_package_required",
                    message=(
                        "Writable tag selection diagnostics require a generated-index "
                        "package path; the default capability report does not load "
                        "package data."
                    ),
                    details={"writable_tag_names": list(request.writable_tag_names)},
                ),
            ),
        )
    if not package_path.exists():
        return (
            (),
            (
                Diagnostic(
                    code="tag_lookup_writable_selection_package_missing",
                    message=f"Generated-index package does not exist: {package_path}",
                    details={
                        "tag_lookup_package_path": str(package_path),
                        "writable_tag_names": list(request.writable_tag_names),
                    },
                ),
            ),
        )
    from exifmodern.services.tag_lookup_runtime import load_tag_lookup_runtime_service

    service = load_tag_lookup_runtime_service(package_path)
    return service.select_writable_tags(request.writable_tag_names), ()


def _query_tag_lookup_summary(
    request: CapabilityQueryRequest,
    capabilities: tuple[TagLookupRuntimeCapability, ...],
    writable_selections: tuple[TagLookupSelectionResult, ...],
) -> tuple[TagLookupCapabilitySummary | None, tuple[Diagnostic, ...]]:
    package_path = request.tag_lookup_package_path
    if package_path is None:
        return None, ()
    if not package_path.exists():
        return None, ()
    from exifmodern.services.tag_lookup_runtime import load_tag_lookup_runtime_service

    service = load_tag_lookup_runtime_service(package_path)
    repository = service.repository
    if not repository.has_data:
        return (
            TagLookupCapabilitySummary(
                package_path=package_path,
                package_loaded=False,
                table_count=0,
                lookup_tag_count=0,
                tag_exists_count=0,
                composite_module_count=0,
                queried_tag_count=len(request.tag_names),
                wildcard_query_count=_tag_lookup_wildcard_query_count(request.tag_names),
                resolved_tag_count=0,
                exists_only_tag_count=0,
                missing_tag_count=0,
                writable_candidate_count=0,
                writable_selection_count=len(request.writable_tag_names),
                writable_resolved_count=0,
                writable_ambiguous_count=0,
                writable_blocked_count=0,
                writable_not_found_count=0,
                evidence_ids=_tag_lookup_capability_evidence_ids(),
            ),
            (
                Diagnostic(
                    code="tag_lookup_package_has_no_tag_lookup_index",
                    message=(
                        "Generated-index package loaded, but it does not contain a "
                        "tag_lookup index."
                    ),
                    details={"tag_lookup_package_path": str(package_path)},
                ),
            ),
        )
    return (
        TagLookupCapabilitySummary(
            package_path=package_path,
            package_loaded=True,
            table_count=len(repository.table_list),
            lookup_tag_count=len(repository.lookup),
            tag_exists_count=len(repository.tag_exists),
            composite_module_count=len(repository.composite_modules),
            queried_tag_count=len(request.tag_names),
            wildcard_query_count=_tag_lookup_wildcard_query_count(request.tag_names),
            resolved_tag_count=sum(
                1
                for capability in capabilities
                if capability.status in {"resolved", "wildcard_resolved"}
            ),
            exists_only_tag_count=sum(
                1 for capability in capabilities if capability.status == "exists_only"
            ),
            missing_tag_count=sum(
                1
                for capability in capabilities
                if capability.status in {"not_found", "wildcard_not_found"}
            ),
            writable_candidate_count=sum(capability.candidate_count for capability in capabilities),
            writable_selection_count=len(request.writable_tag_names),
            writable_resolved_count=sum(
                1 for selection in writable_selections if selection.outcome == "resolved"
            ),
            writable_ambiguous_count=sum(
                1 for selection in writable_selections if selection.outcome == "ambiguous"
            ),
            writable_blocked_count=sum(
                1 for selection in writable_selections if selection.outcome == "blocked"
            ),
            writable_not_found_count=sum(
                1 for selection in writable_selections if selection.outcome == "not_found"
            ),
            evidence_ids=_tag_lookup_capability_evidence_ids(),
        ),
        (),
    )


def _tag_lookup_wildcard_query_count(tag_names: tuple[str, ...]) -> int:
    return sum(1 for tag_name in tag_names if "*" in tag_name or "?" in tag_name)


def _tag_lookup_capability_evidence_ids() -> tuple[str, ...]:
    return ("public.tag-lookup.capability",)


def _operation_deferred(reason: UnsupportedReason, message: str) -> Diagnostic:
    return Diagnostic(code=reason, message=message)


def capability_query_result_to_json_value(
    result: CapabilityQueryResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    from exifmodern.public_api.serialization import capability_query_result_to_json_value

    return capability_query_result_to_json_value(
        result,
        include_evidence_ids=include_evidence_ids,
    )


def diagnostic_to_json_value(
    diagnostic: Diagnostic,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    from exifmodern.public_api.serialization import diagnostic_to_json_value

    return diagnostic_to_json_value(
        diagnostic,
        include_evidence_ids=include_evidence_ids,
    )


def file_inspect_result_to_json_value(
    result: FileInspectResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    from exifmodern.public_api.serialization import file_inspect_result_to_json_value

    return file_inspect_result_to_json_value(
        result,
        include_evidence_ids=include_evidence_ids,
    )


def metadata_read_result_to_json_value(
    result: MetadataReadResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    from exifmodern.public_api.serialization import metadata_read_result_to_json_value

    return metadata_read_result_to_json_value(
        result,
        include_evidence_ids=include_evidence_ids,
    )


def metadata_write_plan_to_json_value(
    plan: MetadataWritePlan,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    from exifmodern.public_api.serialization import metadata_write_plan_to_json_value

    return metadata_write_plan_to_json_value(
        plan,
        include_evidence_ids=include_evidence_ids,
    )


def metadata_write_result_to_json_value(
    result: MetadataWriteResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    from exifmodern.public_api.serialization import metadata_write_result_to_json_value

    return metadata_write_result_to_json_value(
        result,
        include_evidence_ids=include_evidence_ids,
    )


def output_file_routing_request_to_json_value(request: OutputFileRoutingRequest) -> JsonObject:
    from exifmodern.public_api.serialization import output_file_routing_request_to_json_value

    return output_file_routing_request_to_json_value(request)


def output_render_request_to_json_value(request: OutputRenderRequest) -> JsonObject:
    from exifmodern.public_api.serialization import output_render_request_to_json_value

    return output_render_request_to_json_value(request)


def public_geolocation_list_result_to_json_value(
    result: PublicGeolocationListResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    from exifmodern.public_api.serialization import public_geolocation_list_result_to_json_value

    return public_geolocation_list_result_to_json_value(
        result,
        include_evidence_ids=include_evidence_ids,
    )


def public_tag_lookup_result_to_json_value(
    result: PublicTagLookupResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    from exifmodern.public_api.serialization import public_tag_lookup_result_to_json_value

    return public_tag_lookup_result_to_json_value(
        result,
        include_evidence_ids=include_evidence_ids,
    )


def tag_lookup_capability_summary_to_json_value(
    summary: TagLookupCapabilitySummary,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    from exifmodern.public_api.serialization import tag_lookup_capability_summary_to_json_value

    value = tag_lookup_capability_summary_to_json_value(
        summary,
        include_evidence_ids=include_evidence_ids,
    )
    if value is None:
        raise ValueError("TagLookup capability summary serialization unexpectedly returned None")
    return value


def tag_lookup_runtime_candidate_to_json_value(candidate: TagLookupRuntimeCandidate) -> JsonObject:
    from exifmodern.public_api.serialization import tag_lookup_runtime_candidate_to_json_value

    return tag_lookup_runtime_candidate_to_json_value(candidate)


def tag_lookup_runtime_capability_to_json_value(
    capability: TagLookupRuntimeCapability,
) -> JsonObject:
    from exifmodern.public_api.serialization import tag_lookup_runtime_capability_to_json_value

    return tag_lookup_runtime_capability_to_json_value(capability)


def tag_lookup_selection_result_to_json_value(selection: TagLookupSelectionResult) -> JsonObject:
    from exifmodern.public_api.serialization import tag_lookup_selection_result_to_json_value

    return tag_lookup_selection_result_to_json_value(selection)
