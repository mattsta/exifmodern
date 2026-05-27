"""Production-facing ExifModern command parser skeleton."""
# ruff: noqa: F401,I001

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO

from exifmodern.json_types import JsonObject, JsonValue
from exifmodern.package_resources import generated_index_package_path

PUBLIC_GEOLOCATION_PACKAGE: Path | None = None
_WRITE_SUBCOMMAND_OUTPUT_VALUE_OPTIONS = frozenset({"-o", "-out", "--output-file"})
_PUBLIC_SUBCOMMAND_HELP: tuple[tuple[str, str], ...] = (
    ("read", "read metadata from files"),
    ("inspect", "inspect file/container structure"),
    ("write", "plan metadata writes"),
    ("server", "run an explicit localhost JSON-lines server"),
    ("capabilities", "show public interface capabilities"),
    ("tag-lookup", "query the package-backed TagLookup catalog"),
    ("listgeo", "list the package-backed Geolocation database"),
    ("package-data", "inspect bundled production data resources"),
)
type SimpleTextScalar = str | int | float | bool | None
type SimpleTextValue = (
    SimpleTextScalar | Sequence[SimpleTextScalar] | BinaryTagListValue | BinaryTagValue
)
type PublicCliLazyValue = type | SimpleTextValue


@dataclass(frozen=True)
class _FastListgeoRequest:
    package_path: Path
    language_code: str = ""
    include_alternate_names: bool = False
    sort_by_city: bool = False
    min_population: float | None = None
    feature_option: str = ""
    include_header: bool = True
    include_title: bool = True
    json_output: bool = False
    subcommand_mode: bool = False


def _public_generated_index_package_path() -> Path:
    return generated_index_package_path()


def _public_geolocation_package_path() -> Path:
    return (
        PUBLIC_GEOLOCATION_PACKAGE
        if PUBLIC_GEOLOCATION_PACKAGE is not None
        else generated_index_package_path()
    )


if TYPE_CHECKING:
    from exifmodern.read_graph import BinaryTagListValue, BinaryTagValue, ReadGraph, ReadTag

    from exifmodern.exif_scalar_write_plan import build_exif_scalar_write_plan
    from exifmodern.formats.exif_sidecar.copy_from_file_plan import (
        source_backed_exif_tiff_payload,
    )
    from exifmodern.formats.geotag.public_workflow import PublicGeotagWorkflowRequest
    from exifmodern.formats.tiff.exif_scalar_rewriter import create_minimal_exif_scalar_tiff
    from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
    from exifmodern.formats.xmp.packet import empty_xmp_packet
    from exifmodern.formats.xmp.property_write import build_xmp_property_write_plan
    from exifmodern.json_types import JsonArray
    from exifmodern.public_api import (
        CapabilityQueryRequest,
        CapabilityQueryResult,
        FileInspectRequest,
        MetadataAssignment,
        MetadataReadRequest,
        MetadataWriteRequest,
        MetadataWriteResult,
        OutputFileRoutingRequest,
        OutputWriteFileRouting,
        PublicTagLookupRequest,
        capability_query_result_to_json_value,
        file_inspect_result_to_json_value,
        inspect_file,
        query_capabilities,
        query_tag_lookup,
        read_metadata,
        write_metadata,
    )
    from exifmodern.public_api.models import (
        PngChunkWriteRequest,
        PngTextChunkWriteRequest,
        PublicCharsetOption,
        RiffWavMetadataWriteRequest,
        RiffWebpMetadataWriteRequest,
        list_geolocation,
        public_geolocation_list_result_to_json_value,
        public_tag_lookup_result_to_json_value,
    )
    from exifmodern.services.geolocation_runtime import GeolocationListResult, GeolocationListRow
    from exifmodern.public_interface import write_request_parsing as _write_request_parsing
    from exifmodern.public_interface.batch_protocol import build_batch_execution_requests
    from exifmodern.public_interface.capability_text import (
        render_capability_query_text as _render_public_capability_query_text,
    )
    from exifmodern.public_interface.diagnostic_output import (
        exit_code_for_status,
        print_diagnostics,
    )
    from exifmodern.public_interface.echo_options import (
        prepare_top_level_echo_options,
        print_deferred_echo_options,
    )
    from exifmodern.public_interface.list_catalog import (
        is_top_level_list_request,
        public_geolocation_list_request_from_parts,
        render_top_level_list,
    )
    from exifmodern.public_interface.output_policy import public_write_output_is_stdout_request
    from exifmodern.public_interface.output_policy import PublicOutputSuppression
    from exifmodern.public_interface.read_options import (
        ExtensionFilterAction,
        OutputFileRoutingAction,
        PublicReadTagAction,
        parse_csv_delimiter,
        parse_exiftool_escaped_text,
        public_read_tag_exclusions_from_raw,
    )
    from exifmodern.public_interface.read_rendering import (
        api_read_options_not_connected_diagnostic as _api_read_options_not_connected_diagnostic,
        output_render_request_from_args as _output_render_request_from_args,
        output_render_request_with_api_effects as _output_render_request_with_api_effects,
        public_read_api_option_effects as _public_read_api_option_effects,
        read_result_with_public_cli_option_diagnostics,
        read_result_with_unknown_discovery_diagnostic,
    )
    from exifmodern.public_interface.read_result_output import (
        binary_stdout_multi_binary_diagnostic as _binary_stdout_multi_binary_diagnostic,
        emit_read_result as _emit_read_result,
        print_read_diagnostics as _print_read_diagnostics,
    )
    from exifmodern.public_interface.stay_open import (
        StayOpenArgfileStep as _StayOpenArgfileStep,
        is_public_subcommand_name as _is_public_subcommand_name,
        is_stay_open_continue_value as _is_stay_open_continue_value,
        is_stay_open_shutdown_value as _is_stay_open_shutdown_value,
        read_stay_open_argfile_text as _read_stay_open_argfile_text,
        run_bounded_stay_open_argfile as _run_bounded_stay_open_argfile,
        run_top_level_stay_open_driver as _run_top_level_stay_open_driver,
        run_top_level_stay_open_process_loop as _run_top_level_stay_open_process_loop,
        should_render_stay_open_ready_marker as _should_render_stay_open_ready_marker,
        stay_open_control_deferred_message as _stay_open_control_deferred_message,
        stay_open_missing_switch_argfile_message as _stay_open_missing_switch_argfile_message,
        top_level_stay_open_argfile as _top_level_stay_open_argfile,
        top_level_stay_open_request as _top_level_stay_open_request,
        top_level_stay_open_value_options as _top_level_stay_open_value_options,
    )
    from exifmodern.public_interface.top_level_options import (
        expand_top_level_argfiles,
        prepare_deferred_top_level_options,
    )
    from exifmodern.public_interface.top_level_read_options import (
        READ_SUBCOMMAND_DOUBLE_DASH_FLAG_OPTIONS as _READ_SUBCOMMAND_DOUBLE_DASH_FLAG_OPTIONS,
        READ_SUBCOMMAND_DOUBLE_DASH_VALUE_OPTIONS as _READ_SUBCOMMAND_DOUBLE_DASH_VALUE_OPTIONS,
        bounded_alternate_file_slot as _bounded_alternate_file_slot,
        bounded_public_option_suffix as _bounded_public_option_suffix,
        is_alternate_file_option as _is_alternate_file_option,
        is_file_order_option as _is_file_order_option,
        is_if_condition_option as _is_if_condition_option,
        is_top_level_print_format_option as _is_top_level_print_format_option,
        is_top_level_read_deferred_flag_option as _is_top_level_read_deferred_flag_option,
        is_top_level_read_deferred_optional_value_option,
        is_top_level_read_deferred_value_option as _is_top_level_read_deferred_value_option,
        load_public_print_format_template as _load_public_print_format_template,
        missing_top_level_option_value_message as _missing_top_level_option_value_message,
        parse_extract_embedded_option as _parse_extract_embedded_option,
        parse_required_top_level_option_value as _parse_required_top_level_option_value,
        parse_short_output_option as _parse_short_output_option,
        parse_top_level_read_api_option as _parse_top_level_read_api_option,
        parse_top_level_read_request as _parse_top_level_read_request,
        parse_verbose_option as _parse_verbose_option,
        prepare_read_subcommand_double_dash_exclusions,
        public_read_option_deferred_message as _public_read_option_deferred_message,
        read_subcommand_long_option_name as _read_subcommand_long_option_name,
        top_level_read_api_options as _top_level_read_api_options,
        top_level_read_requests_binary_suppression as _top_level_read_requests_binary_suppression,
    )
    from exifmodern.public_interface import top_level_read_options as _top_level_read_options
    from exifmodern.public_interface.traversal import expand_public_cli_read_paths
    from exifmodern.public_interface.unknown_options import (
        PublicUnknownTagAction,
        PublicUnknownTagOptions,
        public_unknown_tag_options_from_args,
        public_unknown_tag_options_from_namespace,
    )
    from exifmodern.public_interface.validation_output import (
        read_result_with_bounded_validate_output,
    )
    from exifmodern.public_interface.write_deferred_diagnostics import (
        is_execute_option as _is_execute_option,
    )
    from exifmodern.public_interface.write_request_parsing import (
        is_tags_from_file_option as _is_tags_from_file_option,
        parse_assignments as _parse_assignments,
        parse_deletes as _parse_deletes,
        tags_from_file_deferred_message as _tags_from_file_deferred_message,
    )
    from exifmodern.public_interface.png_write_reports import (
        metadata_write_result_to_json_value_with_cli_reports,
        png_textout_plan_reports_for_write_request as _png_textout_plan_reports_for_write_request,
    )

    _read_result_with_public_cli_option_diagnostics = read_result_with_public_cli_option_diagnostics
    _read_result_with_unknown_discovery_diagnostic = read_result_with_unknown_discovery_diagnostic
    _is_top_level_read_deferred_optional_value_option = (
        is_top_level_read_deferred_optional_value_option
    )
    _prepare_read_subcommand_double_dash_exclusions = prepare_read_subcommand_double_dash_exclusions
    _metadata_write_result_to_json_value_with_cli_reports = (
        metadata_write_result_to_json_value_with_cli_reports
    )

__all__ = [
    "_api_read_options_not_connected_diagnostic",
    "_output_render_request_from_args",
    "_output_render_request_with_api_effects",
    "_parse_assignments",
    "_parse_deletes",
    "_parse_top_level_read_request",
    "_public_read_api_option_effects",
    "_read_result_with_public_cli_option_diagnostics",
    "_read_result_with_unknown_discovery_diagnostic",
    "_read_stay_open_argfile_text",
    "_run_bounded_stay_open_argfile",
    "_run_top_level_stay_open_driver",
    "_stay_open_missing_switch_argfile_message",
    "_tags_from_file_deferred_message",
    "_top_level_read_api_options",
    "_top_level_read_requests_binary_suppression",
    "_top_level_stay_open_argfile",
    "_top_level_stay_open_request",
    "build_parser",
    "main",
]

_PUBLIC_CLI_RUNTIME_IMPORTED = False
_BROKEN_PIPE_STDOUT_SINK: TextIO | None = None
_SIMPLE_PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG: (
    Callable[[ReadTag], PublicOutputSuppression | None] | None
)
_SIMPLE_PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG = None
_LAZY_PUBLIC_CLI_NAMES = {
    "CapabilityQueryRequest",
    "CapabilityQueryResult",
    "ExtensionFilterAction",
    "FileInspectRequest",
    "MetadataAssignment",
    "MetadataReadRequest",
    "MetadataWriteRequest",
    "MetadataWriteResult",
    "OutputFileRoutingAction",
    "OutputFileRoutingRequest",
    "OutputWriteFileRouting",
    "PngChunkWriteRequest",
    "PngTextChunkWriteRequest",
    "PublicCharsetOption",
    "PublicReadTagAction",
    "PublicTagLookupRequest",
    "PublicUnknownTagAction",
    "PublicUnknownTagOptions",
    "RiffWavMetadataWriteRequest",
    "RiffWebpMetadataWriteRequest",
    "_READ_SUBCOMMAND_DOUBLE_DASH_FLAG_OPTIONS",
    "_READ_SUBCOMMAND_DOUBLE_DASH_VALUE_OPTIONS",
    "_StayOpenArgfileStep",
    "_api_read_options_not_connected_diagnostic",
    "_append_top_level_write_operation",
    "_binary_stdout_multi_binary_diagnostic",
    "_bounded_alternate_file_slot",
    "_bounded_public_option_suffix",
    "_copy_route_selector_group",
    "_emit_read_result",
    "_is_alternate_file_option",
    "_is_execute_option",
    "_is_exif_sidecar_copy_route_selector",
    "_is_file_order_option",
    "_is_if_condition_option",
    "_is_progress_option",
    "_is_public_subcommand_name",
    "_is_stay_open_continue_value",
    "_is_stay_open_shutdown_value",
    "_is_tags_from_file_option",
    "_is_top_level_print_format_option",
    "_is_top_level_read_deferred_flag_option",
    "_is_top_level_read_deferred_optional_value_option",
    "_is_top_level_read_deferred_value_option",
    "_is_xmp_sidecar_copy_route",
    "_load_public_print_format_template",
    "_metadata_write_result_to_json_value_with_cli_reports",
    "_missing_top_level_option_value_message",
    "_output_render_request_from_args",
    "_output_render_request_with_api_effects",
    "_parse_assignments",
    "_parse_deletes",
    "_parse_exif_sidecar_copy_route_or_defer",
    "_parse_extract_embedded_option",
    "_parse_required_top_level_option_value",
    "_parse_short_output_option",
    "_parse_tags_from_file_route_token",
    "_parse_tags_from_file_source",
    "_parse_top_level_read_api_option",
    "_parse_top_level_read_request",
    "_parse_verbose_option",
    "_parse_xmp_sidecar_copy_route_or_defer",
    "_png_readback_tag_summary",
    "_png_textout_plan_reports_for_write_request",
    "_png_textout_readback_report_for_write_result",
    "_png_textout_text_chunk_requests",
    "_png_textual_readback_summary",
    "_prepare_read_subcommand_double_dash_exclusions",
    "_print_read_diagnostics",
    "_public_copy_from_tags_from_file_parts",
    "_public_copy_route_from_direct_write_arg_or_none",
    "_public_copy_route_from_tags_from_file_route",
    "_public_copy_source_for_direct_routes",
    "_public_copy_source_kind_for_direct_routes",
    "_public_list_write_assignment_deferred_message",
    "_public_read_api_option_effects",
    "_public_read_option_deferred_message",
    "_public_write_geotag_deferred_message",
    "_public_write_option_deferred_message",
    "_public_write_original_maintenance_deferred_message",
    "_read_result_with_public_cli_option_diagnostics",
    "_read_result_with_unknown_discovery_diagnostic",
    "_read_stay_open_argfile_text",
    "_read_subcommand_long_option_name",
    "_run_bounded_stay_open_argfile",
    "_run_top_level_stay_open_driver",
    "_run_top_level_stay_open_process_loop",
    "_should_render_stay_open_ready_marker",
    "_stay_open_control_deferred_message",
    "_stay_open_missing_switch_argfile_message",
    "_tags_from_file_deferred_message",
    "_tags_from_file_route_list_deferred_reason",
    "_top_level_read_api_options",
    "_top_level_read_requests_binary_suppression",
    "_top_level_stay_open_argfile",
    "_top_level_stay_open_request",
    "_top_level_stay_open_value_options",
    "build_batch_execution_requests",
    "build_exif_scalar_write_plan",
    "build_xmp_property_write_plan",
    "capability_query_result_to_json_value",
    "create_minimal_exif_scalar_tiff",
    "empty_xmp_packet",
    "exit_code_for_status",
    "expand_public_cli_read_paths",
    "expand_top_level_argfiles",
    "file_inspect_result_to_json_value",
    "inspect_file",
    "is_top_level_list_request",
    "list_geolocation",
    "parse_csv_delimiter",
    "parse_exiftool_escaped_text",
    "prepare_deferred_top_level_options",
    "prepare_top_level_echo_options",
    "print_deferred_echo_options",
    "print_diagnostics",
    "public_geolocation_list_request_from_parts",
    "public_geolocation_list_result_to_json_value",
    "public_read_tag_exclusions_from_raw",
    "public_tag_lookup_result_to_json_value",
    "public_unknown_tag_options_from_args",
    "public_unknown_tag_options_from_namespace",
    "public_write_output_is_stdout_request",
    "query_capabilities",
    "query_tag_lookup",
    "read_metadata",
    "read_result_with_bounded_validate_output",
    "render_top_level_list",
    "source_backed_exif_tiff_payload",
    "write_metadata",
}


def _ensure_public_cli_runtime_imports() -> None:
    global _PUBLIC_CLI_RUNTIME_IMPORTED
    if _PUBLIC_CLI_RUNTIME_IMPORTED:
        return

    from exifmodern.exif_scalar_write_plan import build_exif_scalar_write_plan
    from exifmodern.formats.exif_sidecar.copy_from_file_plan import (
        source_backed_exif_tiff_payload,
    )
    from exifmodern.formats.tiff.exif_scalar_rewriter import create_minimal_exif_scalar_tiff
    from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
    from exifmodern.formats.xmp.packet import empty_xmp_packet
    from exifmodern.formats.xmp.property_write import build_xmp_property_write_plan
    from exifmodern.public_api import (
        CapabilityQueryRequest,
        CapabilityQueryResult,
        FileInspectRequest,
        MetadataAssignment,
        MetadataReadRequest,
        MetadataWriteRequest,
        MetadataWriteResult,
        OutputFileRoutingRequest,
        OutputWriteFileRouting,
        PublicTagLookupRequest,
        capability_query_result_to_json_value,
        file_inspect_result_to_json_value,
        inspect_file,
        query_capabilities,
        query_tag_lookup,
        read_metadata,
        write_metadata,
    )
    from exifmodern.public_api.models import (
        PngChunkWriteRequest,
        PngTextChunkWriteRequest,
        PublicCharsetOption,
        RiffWavMetadataWriteRequest,
        RiffWebpMetadataWriteRequest,
        list_geolocation,
        public_geolocation_list_result_to_json_value,
        public_tag_lookup_result_to_json_value,
    )
    from exifmodern.public_interface import png_write_reports as _png_write_reports
    from exifmodern.public_interface import read_rendering as _read_rendering
    from exifmodern.public_interface import read_result_output as _read_result_output
    from exifmodern.public_interface import stay_open as _stay_open
    from exifmodern.public_interface import top_level_read_options as _top_level_read_options
    from exifmodern.public_interface import (
        write_deferred_diagnostics as _write_deferred_diagnostics,
    )
    from exifmodern.public_interface import write_request_parsing as _write_request_parsing
    from exifmodern.public_interface.batch_protocol import build_batch_execution_requests
    from exifmodern.public_interface.capability_text import (
        render_capability_query_text as _render_public_capability_query_text,
    )
    from exifmodern.public_interface.diagnostic_output import (
        exit_code_for_status,
        print_diagnostics,
    )
    from exifmodern.public_interface.echo_options import (
        prepare_top_level_echo_options,
        print_deferred_echo_options,
    )
    from exifmodern.public_interface.list_catalog import (
        is_top_level_list_request,
        public_geolocation_list_request_from_parts,
        render_top_level_list,
    )
    from exifmodern.public_interface.output_policy import public_write_output_is_stdout_request
    from exifmodern.public_interface.read_options import (
        ExtensionFilterAction,
        OutputFileRoutingAction,
        PublicReadTagAction,
        parse_csv_delimiter,
        parse_exiftool_escaped_text,
        public_read_tag_exclusions_from_raw,
    )
    from exifmodern.public_interface.top_level_options import (
        expand_top_level_argfiles,
        prepare_deferred_top_level_options,
    )
    from exifmodern.public_interface.traversal import expand_public_cli_read_paths
    from exifmodern.public_interface.unknown_options import (
        PublicUnknownTagAction,
        PublicUnknownTagOptions,
        public_unknown_tag_options_from_args,
        public_unknown_tag_options_from_namespace,
    )
    from exifmodern.public_interface.validation_output import (
        read_result_with_bounded_validate_output,
    )

    globals().update(locals())
    globals().update(
        {
            "_api_read_options_not_connected_diagnostic": (
                _read_rendering.api_read_options_not_connected_diagnostic
            ),
            "_output_render_request_from_args": _read_rendering.output_render_request_from_args,
            "_output_render_request_with_api_effects": (
                _read_rendering.output_render_request_with_api_effects
            ),
            "_public_read_api_option_effects": _read_rendering.public_read_api_option_effects,
            "_read_result_with_public_cli_option_diagnostics": (
                _read_rendering.read_result_with_public_cli_option_diagnostics
            ),
            "_read_result_with_unknown_discovery_diagnostic": (
                _read_rendering.read_result_with_unknown_discovery_diagnostic
            ),
            "_emit_read_result": _read_result_output.emit_read_result,
            "_print_read_diagnostics": _read_result_output.print_read_diagnostics,
            "_binary_stdout_multi_binary_diagnostic": (
                _read_result_output.binary_stdout_multi_binary_diagnostic
            ),
            "_metadata_write_result_to_json_value_with_cli_reports": (
                _png_write_reports.metadata_write_result_to_json_value_with_cli_reports
            ),
            "_png_textout_plan_reports_for_write_request": (
                _png_write_reports.png_textout_plan_reports_for_write_request
            ),
            "_png_textout_text_chunk_requests": _png_write_reports.png_textout_text_chunk_requests,
            "_png_textout_readback_report_for_write_result": (
                _png_write_reports.png_textout_readback_report_for_write_result
            ),
            "_png_textual_readback_summary": _png_write_reports.png_textual_readback_summary,
            "_png_readback_tag_summary": _png_write_reports.png_readback_tag_summary,
            "_top_level_stay_open_request": _stay_open.top_level_stay_open_request,
            "_top_level_stay_open_argfile": _stay_open.top_level_stay_open_argfile,
            "_is_public_subcommand_name": _stay_open.is_public_subcommand_name,
            "_run_top_level_stay_open_driver": _stay_open.run_top_level_stay_open_driver,
            "_run_top_level_stay_open_process_loop": (
                _stay_open.run_top_level_stay_open_process_loop
            ),
            "_run_bounded_stay_open_argfile": _stay_open.run_bounded_stay_open_argfile,
            "_StayOpenArgfileStep": _stay_open.StayOpenArgfileStep,
            "_read_stay_open_argfile_text": _stay_open.read_stay_open_argfile_text,
            "_top_level_stay_open_value_options": _stay_open.top_level_stay_open_value_options,
            "_is_stay_open_shutdown_value": _stay_open.is_stay_open_shutdown_value,
            "_is_stay_open_continue_value": _stay_open.is_stay_open_continue_value,
            "_should_render_stay_open_ready_marker": (
                _stay_open.should_render_stay_open_ready_marker
            ),
            "_stay_open_control_deferred_message": _stay_open.stay_open_control_deferred_message,
            "_stay_open_missing_switch_argfile_message": (
                _stay_open.stay_open_missing_switch_argfile_message
            ),
            "_is_execute_option": _write_deferred_diagnostics.is_execute_option,
            "_is_progress_option": _write_deferred_diagnostics.is_progress_option,
            "_public_write_geotag_deferred_message": (
                _write_deferred_diagnostics.public_write_geotag_deferred_message
            ),
            "_public_write_option_deferred_message": (
                _write_deferred_diagnostics.public_write_option_deferred_message
            ),
            "_public_write_original_maintenance_deferred_message": (
                _write_deferred_diagnostics.public_write_original_maintenance_deferred_message
            ),
            "_READ_SUBCOMMAND_DOUBLE_DASH_VALUE_OPTIONS": (
                _top_level_read_options.READ_SUBCOMMAND_DOUBLE_DASH_VALUE_OPTIONS
            ),
            "_READ_SUBCOMMAND_DOUBLE_DASH_FLAG_OPTIONS": (
                _top_level_read_options.READ_SUBCOMMAND_DOUBLE_DASH_FLAG_OPTIONS
            ),
            "_parse_top_level_read_request": _top_level_read_options.parse_top_level_read_request,
            "_parse_short_output_option": _top_level_read_options.parse_short_output_option,
            "_parse_verbose_option": _top_level_read_options.parse_verbose_option,
            "_parse_extract_embedded_option": _top_level_read_options.parse_extract_embedded_option,
            "_is_top_level_print_format_option": (
                _top_level_read_options.is_top_level_print_format_option
            ),
            "_load_public_print_format_template": (
                _top_level_read_options.load_public_print_format_template
            ),
            "_top_level_read_requests_binary_suppression": (
                _top_level_read_options.top_level_read_requests_binary_suppression
            ),
            "_top_level_read_api_options": _top_level_read_options.top_level_read_api_options,
            "_parse_top_level_read_api_option": (
                _top_level_read_options.parse_top_level_read_api_option
            ),
            "_parse_required_top_level_option_value": (
                _top_level_read_options.parse_required_top_level_option_value
            ),
            "_missing_top_level_option_value_message": (
                _top_level_read_options.missing_top_level_option_value_message
            ),
            "_is_top_level_read_deferred_value_option": (
                _top_level_read_options.is_top_level_read_deferred_value_option
            ),
            "_is_top_level_read_deferred_optional_value_option": (
                _top_level_read_options.is_top_level_read_deferred_optional_value_option
            ),
            "_is_top_level_read_deferred_flag_option": (
                _top_level_read_options.is_top_level_read_deferred_flag_option
            ),
            "_public_read_option_deferred_message": (
                _top_level_read_options.public_read_option_deferred_message
            ),
            "_is_if_condition_option": _top_level_read_options.is_if_condition_option,
            "_is_file_order_option": _top_level_read_options.is_file_order_option,
            "_is_alternate_file_option": _top_level_read_options.is_alternate_file_option,
            "_bounded_public_option_suffix": _top_level_read_options.bounded_public_option_suffix,
            "_bounded_alternate_file_slot": _top_level_read_options.bounded_alternate_file_slot,
            "_prepare_read_subcommand_double_dash_exclusions": (
                _top_level_read_options.prepare_read_subcommand_double_dash_exclusions
            ),
            "_read_subcommand_long_option_name": (
                _top_level_read_options.read_subcommand_long_option_name
            ),
            "_public_write_assignments_without_order_indexes": (
                _write_request_parsing.public_write_assignments_without_order_indexes
            ),
            "_is_tags_from_file_option": _write_request_parsing.is_tags_from_file_option,
            "_parse_tags_from_file_source": _write_request_parsing.parse_tags_from_file_source,
            "_parse_tags_from_file_route_token": (
                _write_request_parsing.parse_tags_from_file_route_token
            ),
            "_public_copy_from_tags_from_file_parts": (
                _write_request_parsing.public_copy_from_tags_from_file_parts
            ),
            "_public_copy_route_from_tags_from_file_route": (
                _write_request_parsing.public_copy_route_from_tags_from_file_route
            ),
            "_public_copy_route_from_direct_write_arg_or_none": (
                _write_request_parsing.public_copy_route_from_direct_write_arg_or_none
            ),
            "_public_copy_source_for_direct_routes": (
                _write_request_parsing.public_copy_source_for_direct_routes
            ),
            "_public_copy_source_kind_for_direct_routes": (
                _write_request_parsing.public_copy_source_kind_for_direct_routes
            ),
            "_append_top_level_write_operation": (
                _write_request_parsing.append_top_level_write_operation
            ),
            "_public_list_write_assignment_deferred_message": (
                _write_request_parsing.public_list_write_assignment_deferred_message
            ),
            "_tags_from_file_route_list_deferred_reason": (
                _write_request_parsing.tags_from_file_route_list_deferred_reason
            ),
            "_is_exif_sidecar_copy_route_selector": (
                _write_request_parsing.is_exif_sidecar_copy_route_selector
            ),
            "_tags_from_file_deferred_message": (
                _write_request_parsing.tags_from_file_deferred_message
            ),
            "_is_xmp_sidecar_copy_route": _write_request_parsing.is_xmp_sidecar_copy_route,
            "_copy_route_selector_group": _write_request_parsing.copy_route_selector_group,
            "_parse_xmp_sidecar_copy_route_or_defer": (
                _write_request_parsing.parse_xmp_sidecar_copy_route_or_defer
            ),
            "_parse_exif_sidecar_copy_route_or_defer": (
                _write_request_parsing.parse_exif_sidecar_copy_route_or_defer
            ),
            "_parse_assignments": _write_request_parsing.parse_assignments,
            "_parse_deletes": _write_request_parsing.parse_deletes,
        }
    )
    _PUBLIC_CLI_RUNTIME_IMPORTED = True


def __getattr__(name: str) -> PublicCliLazyValue:
    if name in _LAZY_PUBLIC_CLI_NAMES:
        _ensure_public_cli_runtime_imports()
        return globals()[name]  # type: ignore[no-any-return]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _is_top_level_geotag_request(args: Sequence[str]) -> bool:
    return any(
        arg.lower() == "-geotag"
        or arg.lower().startswith("-geotag=")
        or _is_public_geotag_assignment(arg)
        for arg in args
    )


def _parse_public_geotag_workflow_request(
    args: Sequence[str],
) -> PublicGeotagWorkflowRequest:
    from exifmodern.public_interface.geotag import parse_public_geotag_workflow_request

    return parse_public_geotag_workflow_request(args)


def _is_public_geotag_assignment(arg: str) -> bool:
    if not arg.startswith("-") or "=" not in arg:
        return False
    tag_name = arg.removeprefix("-").partition("=")[0].lower()
    return tag_name in {
        "geotag",
        "gps:geotag",
        "exif:geotag",
        "xmp:geotag",
        "quicktime:geotag",
        "itemlist:geotag",
        "userdata:geotag",
        "keys:geotag",
    }


def _is_public_geotime_assignment(arg: str) -> bool:
    from exifmodern.public_interface.geotag import is_public_geotime_assignment

    return is_public_geotime_assignment(arg)


def _public_geotime_destination_group(tag_name: str) -> str:
    from exifmodern.public_interface.geotag import public_geotime_destination_group

    return public_geotime_destination_group(tag_name)


_PUBLIC_PNG_TEXT_KEYWORDS_BY_TAG: dict[str, str] = {
    "aestheticscore": "aesthetic_score",
    "artist": "Artist",
    "author": "Author",
    "collection": "Collection",
    "comment": "Comment",
    "copyright": "Copyright",
    "createdate": "create-date",
    "creationtime": "Creation Time",
    "description": "Description",
    "disclaimer": "Disclaimer",
    "document": "Document",
    "label": "Label",
    "make": "Make",
    "model": "Model",
    "moddate": "modify-date",
    "parameters": "parameters",
    "pngwarning": "Warning",
    "software": "Software",
    "source": "Source",
    "timestamp": "TimeStamp",
    "title": "Title",
    "url": "URL",
    "warning": "Warning",
}
_PUBLIC_PNG_DELETE_GROUPS = frozenset({"png", "xmp", "exif", "ifd0", "icc", "icc_profile"})
_PUBLIC_PNG_DELETE_GROUP_DISPLAY_NAMES: dict[str, str] = {
    "exif": "EXIF",
    "icc": "ICC",
    "icc_profile": "ICC_Profile",
    "ifd0": "IFD0",
    "png": "PNG",
    "xmp": "XMP",
}
_PUBLIC_PNG_DELETE_ALL_TAGS = frozenset({"all", "*"})
_PUBLIC_PNG_ICC_COPY_ROUTES = frozenset({"icc_profile", "icc_profile:all", "icc_profile:*"})
_PUBLIC_PNG_XMP_COPY_ROUTES = frozenset({"xmp", "xmp:all", "xmp:*"})
_PUBLIC_PNG_EXIF_COPY_ROUTES = frozenset(
    {"exif", "exif:all", "exif:*", "ifd0", "ifd0:all", "ifd0:*"}
)


class _VerboseLevelAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        if option_string is None:
            setattr(namespace, self.dest, 1)
            return
        suffix = option_string.removeprefix("-v")
        level = int(suffix) if suffix.isdecimal() else 1
        setattr(namespace, self.dest, level)


class _DeferredReadOptionAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        del namespace, values
        if option_string is None:
            parser.error("internal deferred public read option parser error")
        parser.error(_public_read_option_deferred_message(option_string))


class _ReadCharsetAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        if option_string is None:
            parser.error("internal charset option parser error")
        if isinstance(values, str):
            raw_value = values
        else:
            parser.error(f"{option_string} requires [[TYPE=]CHARSET]")
        try:
            parsed = _top_level_read_options.parse_top_level_charset_option(
                option_string,
                (option_string, raw_value),
                0,
            )
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        if parsed.target is None:
            setattr(namespace, self.dest, parsed.charset)
            return
        current = list(getattr(namespace, "internal_charset_options", ()) or ())
        current.append(
            PublicCharsetOption(
                target=parsed.target,
                charset=parsed.charset,
                raw_option=parsed.raw_option,
            )
        )
        namespace.internal_charset_options = tuple(current)


class _ReadLanguageAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        if option_string is None:
            parser.error("internal language option parser error")
        if isinstance(values, str):
            setattr(namespace, self.dest, values.replace("-", "_").lower())
            return
        parser.error(f"{option_string} requires LANG")


_PUBLIC_PNG_UNSUPPORTED_NESTED_COPY_GROUPS = frozenset(
    {
        "iptc",
        "iptc:all",
        "iptc:*",
        "photoshop",
        "photoshop:all",
        "photoshop:*",
    }
)

type _PublicWritePolicy = Literal[
    "preserve_original",
    "overwrite_original",
    "overwrite_original_in_place",
]


def build_parser() -> argparse.ArgumentParser:
    _ensure_public_cli_runtime_imports()
    parser = _build_startup_parser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    read_parser = subparsers.add_parser(
        "read",
        help="read metadata from files",
        description="Parse a public metadata read request.",
    )
    _add_common_render_options(read_parser)
    read_parser.add_argument(
        "-tag",
        "--tag",
        action=PublicReadTagAction,
        default=[],
        help="select a tag by name; may be repeated",
    )
    read_parser.add_argument(
        "-x",
        "-exclude",
        dest="tag_exclusions",
        action="append",
        default=[],
        metavar="TAG",
        help="exclude a tag from read output; may be repeated",
    )
    read_parser.add_argument(
        "-r",
        "-recurse",
        "--recursive",
        action="store_true",
        help="request recursive directory traversal",
    )
    read_parser.add_argument(
        "-r.",
        "-recurse.",
        dest="recurse_dot_directories",
        action="store_true",
        help="recursively process subdirectories, including dot-prefixed directories",
    )
    read_parser.add_argument(
        "-i",
        "-ignore",
        dest="ignore_directories",
        action="append",
        default=[],
        metavar="DIR",
        help="ignore a directory name/path during directory scans; HIDDEN skips dot files",
    )
    for fast_level in range(0, 6):
        option_strings = ("-fast", "-fast1") if fast_level == 1 else (f"-fast{fast_level}",)
        read_parser.add_argument(
            *option_strings,
            dest="fast_scan_level",
            action="store_const",
            const=fast_level,
            default=None,
            help=argparse.SUPPRESS,
        )
    read_parser.add_argument(
        "-ext",
        "-extension",
        dest="extension_filters",
        action=ExtensionFilterAction,
        default=[],
        metavar="EXT",
        help="process only files with this extension during directory scans; may be repeated",
    )
    read_parser.add_argument(
        "--ext",
        "--extension",
        dest="extension_filters",
        action=ExtensionFilterAction,
        metavar="EXT",
        help="exclude files with this extension during directory scans; may be repeated",
    )
    read_parser.add_argument(
        "-ext+",
        "-extension+",
        dest="extension_filters",
        action=ExtensionFilterAction,
        metavar="EXT",
        help="add this extension to the normally scanned public read extensions",
    )
    read_parser.add_argument("paths", nargs="+", type=Path, help="file or directory paths")

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="inspect file/container structure",
        description="Parse a public file inspection request.",
    )
    inspect_parser.add_argument("paths", nargs="+", type=Path, help="file paths to inspect")

    write_parser = subparsers.add_parser(
        "write",
        help="plan metadata writes",
        description="Parse a public metadata write request.",
    )
    write_parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="TAG=VALUE",
        help="set a metadata tag value; may be repeated",
    )
    write_parser.add_argument(
        "--delete",
        action="append",
        default=[],
        metavar="TAG",
        help="delete a metadata tag or group; may be repeated",
    )
    write_parser.add_argument(
        "--overwrite-original",
        action="store_true",
        help="request in-place replacement instead of preserving the original file",
    )
    write_parser.add_argument(
        "--overwrite-original-in-place",
        action="store_true",
        help=(
            "request ExifTool overwrite_original_in_place semantics; execution reports "
            "a source-backed blocker until in-place attribute preservation is supported"
        ),
    )
    write_parser.add_argument(
        "-P",
        "-preserve",
        "--preserve",
        "--preserve-file-times",
        dest="preserve_file_times",
        action="store_true",
        help="preserve the filesystem modification time on supported write routes",
    )
    write_parser.add_argument(
        "-o",
        "-out",
        "--output-file",
        dest="write_output_file",
        type=Path,
        metavar="OUTFILE",
        help="write metadata to a new output file instead of modifying the source",
    )
    write_parser.add_argument(
        "-sep",
        "-separator",
        dest="list_separator",
        default=None,
        type=parse_exiftool_escaped_text,
        help="set list item separator for splitting supported list writes",
    )
    write_parser.add_argument(
        "--tag-lookup-package",
        "--tag-lookup-package-path",
        dest="tag_lookup_package_path",
        type=Path,
        metavar="PATH",
        help=(
            "generated-index package path used to add TagLookup writable-selection "
            "diagnostics to public write planning"
        ),
    )
    write_parser.add_argument("paths", nargs="+", type=Path, help="file paths to write")

    capabilities_parser = subparsers.add_parser(
        "capabilities",
        help="show public interface capabilities",
        description="Report the implemented and deferred public interface surface.",
    )
    capabilities_parser.add_argument(
        "--include-experimental",
        action="store_true",
        help="include experimental capabilities in the report",
    )
    capabilities_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="render capabilities as structured JSON or user-readable text",
    )
    capabilities_parser.add_argument(
        "--tag",
        "--tag-name",
        dest="tag_names",
        action="append",
        default=[],
        metavar="TAG",
        help=(
            "include package-backed capability detail for this tag name or wildcard; "
            "may be repeated"
        ),
    )
    capabilities_parser.add_argument(
        "--tag-lookup-package",
        "--tag-lookup-package-path",
        dest="tag_lookup_package_path",
        type=Path,
        metavar="PATH",
        help="generated-index package path used to resolve --tag capability detail",
    )
    capabilities_parser.add_argument(
        "--writable-tag",
        "--writable-tag-name",
        dest="writable_tag_names",
        action="append",
        default=[],
        metavar="TAG",
        help=(
            "include package-backed TagLookup writable selection diagnostics for this "
            "tag name; may be repeated"
        ),
    )

    tag_lookup_parser = subparsers.add_parser(
        "tag-lookup",
        help="query the package-backed TagLookup catalog",
        description=(
            "Resolve public TagLookup queries using a generated-index package copied "
            "from ExifTool's TagLookup source data."
        ),
    )
    tag_lookup_parser.add_argument(
        "--tag-lookup-package",
        "--tag-lookup-package-path",
        dest="tag_lookup_package_path",
        type=Path,
        metavar="PATH",
        help=(
            "generated-index package path used to resolve tag lookup queries; "
            "defaults to the bundled production package"
        ),
    )
    tag_lookup_parser.add_argument(
        "--tag",
        "--tag-name",
        dest="tag_names",
        action="append",
        default=[],
        metavar="TAG",
        help="resolve this tag name or wildcard through TagLookup; may be repeated",
    )
    tag_lookup_parser.add_argument(
        "--writable-tag",
        "--writable-tag-name",
        dest="writable_tag_names",
        action="append",
        default=[],
        metavar="TAG",
        help="resolve writable selection diagnostics for this tag; may be repeated",
    )

    listgeo_parser = subparsers.add_parser(
        "listgeo",
        help="list the package-backed Geolocation database",
        description=(
            "Emit ExifTool-compatible -listgeo CSV output using the generated "
            "geolocation package and runtime service."
        ),
    )
    listgeo_parser.add_argument(
        "--geolocation-package",
        "--geolocation-package-path",
        dest="geolocation_package_path",
        type=Path,
        metavar="PATH",
        help="generated-index package path containing geolocation data",
    )
    listgeo_parser.add_argument(
        "-sort",
        dest="sort_by_city",
        action="store_true",
        help="sort the geolocation database by city before listing",
    )
    listgeo_parser.add_argument(
        "-lang",
        dest="language_code",
        default="",
        metavar="CODE",
        help="apply source-backed geolocation language translations when packaged",
    )
    listgeo_parser.add_argument(
        "-api",
        dest="api_options",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=(
            "set a supported ExifTool API option: GeolocFeature, GeolocMinPop, or GeolocAltNames"
        ),
    )
    listgeo_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="emit structured public API JSON instead of ExifTool CSV text",
    )

    package_data_parser = subparsers.add_parser(
        "package-data",
        help="inspect bundled production data resources",
        description=(
            "Report the installed ExifModern runtime data resource paths, existence, "
            "and sizes without requiring inline Python snippets."
        ),
    )
    package_data_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="render package data diagnostics as structured JSON or text",
    )

    return parser


def _build_startup_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="exifmodern",
        description="Read, inspect, and write file metadata with ExifModern.",
    )


def _add_startup_subcommand_help(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="command", required=True)
    for subcommand, help_text in _PUBLIC_SUBCOMMAND_HELP:
        subparsers.add_parser(subcommand, help=help_text)


def _print_startup_help() -> None:
    parser = _build_startup_parser()
    _add_startup_subcommand_help(parser)
    parser.print_help()


def _parse_startup_help(args: Sequence[str]) -> bool:
    if len(args) != 1 or args[0] not in {"-h", "--help"}:
        return False
    parser = _build_startup_parser()
    _add_startup_subcommand_help(parser)
    parser.parse_args(args)
    return True


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _run_public_main(argv)
    except BrokenPipeError:
        _suppress_broken_pipe_shutdown_flush()
        return 0


def _suppress_broken_pipe_shutdown_flush() -> None:
    global _BROKEN_PIPE_STDOUT_SINK

    # Process-lifetime stdout replacement: a context manager would close the sink
    # before interpreter shutdown flushes `sys.stdout`.
    _BROKEN_PIPE_STDOUT_SINK = Path(os.devnull).open("w", encoding="utf-8")  # noqa: SIM115, RUF100
    sys.stdout = _BROKEN_PIPE_STDOUT_SINK


def _try_run_fast_listgeo(raw_args: Sequence[str]) -> int | None:
    if not raw_args or raw_args[0] not in {"listgeo", "-listgeo"}:
        return None
    subcommand_mode = raw_args[0] == "listgeo"
    parser = _build_fast_listgeo_parser(subcommand_mode=subcommand_mode)
    args = parser.parse_args(list(raw_args[1:]))
    package_path = args.geolocation_package_path or _public_geolocation_package_path()
    try:
        request = _fast_listgeo_request_from_args(
            package_path=package_path,
            api_options=tuple(args.api_options),
            sort_by_city=args.sort_by_city,
            language_code=args.language_code,
            include_title=True,
            json_output=args.json_output,
            subcommand_mode=subcommand_mode,
        )
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if not request.package_path.is_file():
        message = (
            f"public -listgeo requires the generated geolocation package at {request.package_path}"
        )
        if request.json_output:
            print(json.dumps(_fast_listgeo_missing_package_json(request, message), indent=2))
            print(f"geolocation_package_missing: {message}", file=sys.stderr)
            return 2
        parser.error(message)
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
    result = load_geolocation_runtime_service(request.package_path).list_public(runtime_request)
    rendered_text = "\n".join(result.csv_lines(runtime_request)) + "\n"
    if request.json_output:
        print(
            json.dumps(
                _fast_listgeo_result_json(request, result, rendered_text),
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(rendered_text, end="")
    return 0


def _build_fast_listgeo_parser(*, subcommand_mode: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exifmodern listgeo" if subcommand_mode else "exifmodern -listgeo",
        add_help=subcommand_mode,
    )
    parser.add_argument(
        "--geolocation-package",
        "--geolocation-package-path",
        dest="geolocation_package_path",
        type=Path,
        metavar="PATH",
    )
    parser.add_argument("-sort", dest="sort_by_city", action="store_true")
    parser.add_argument("-lang", dest="language_code", default="", metavar="CODE")
    parser.add_argument("-api", dest="api_options", action="append", default=[])
    parser.add_argument("--json", dest="json_output", action="store_true")
    return parser


def _fast_listgeo_request_from_args(
    *,
    package_path: Path,
    api_options: tuple[str, ...],
    sort_by_city: bool,
    language_code: str,
    include_title: bool,
    json_output: bool,
    subcommand_mode: bool,
) -> _FastListgeoRequest:
    feature_option = ""
    include_alternate_names = False
    min_population: float | None = None
    for api_option in api_options:
        option_name, option_value = _split_fast_api_option(api_option)
        normalized_name = option_name.lower()
        if normalized_name == "geolocfeature":
            feature_option = option_value
        elif normalized_name == "geolocminpop":
            min_population = _parse_fast_api_float(option_name, option_value)
        elif normalized_name == "geolocaltnames":
            include_alternate_names = _parse_fast_api_bool(option_name, option_value)
        else:
            raise argparse.ArgumentTypeError(
                "public -listgeo supports ExifTool API options GeolocFeature, "
                "GeolocMinPop, and GeolocAltNames only"
            )
    return _FastListgeoRequest(
        package_path=package_path,
        language_code=language_code,
        include_alternate_names=include_alternate_names,
        sort_by_city=sort_by_city,
        min_population=min_population,
        feature_option=feature_option,
        include_title=include_title,
        json_output=json_output,
        subcommand_mode=subcommand_mode,
    )


def _split_fast_api_option(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Expecting NAME=VALUE for -api option")
    option_name, option_value = value.split("=", 1)
    if not option_name:
        raise argparse.ArgumentTypeError("Expecting non-empty NAME in -api NAME=VALUE option")
    return option_name, option_value


def _parse_fast_api_float(option_name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid numeric value for -api {option_name}: {value!r}"
        ) from exc


def _parse_fast_api_bool(option_name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value for -api {option_name}: {value!r}")


def _fast_listgeo_missing_package_json(
    request: _FastListgeoRequest,
    message: str,
) -> JsonObject:
    value = _fast_listgeo_base_json(request, status="unsupported")
    value["diagnostics"] = [
        {
            "code": "geolocation_package_missing",
            "message": message,
            "details": {
                "geolocation_package_path": str(request.package_path),
            },
        }
    ]
    return value


def _fast_listgeo_result_json(
    request: _FastListgeoRequest,
    result: GeolocationListResult,
    rendered_text: str,
) -> JsonObject:
    value = _fast_listgeo_base_json(request, status="ok")
    alternate_names_column_available = result.alternate_names_column_available
    value["alternate_names_column_available"] = alternate_names_column_available
    value["rows"] = [
        _fast_listgeo_row_json(row, include_alternate_names=alternate_names_column_available)
        for row in result.rows
    ]
    value["rendered_text"] = rendered_text
    value["diagnostics"] = []
    return value


def _fast_listgeo_base_json(request: _FastListgeoRequest, *, status: str) -> JsonObject:
    return {
        "status": status,
        "operation": "listgeo",
        "package_path": str(request.package_path),
        "language_code": request.language_code,
        "include_alternate_names": request.include_alternate_names,
        "sort_by_city": request.sort_by_city,
        "sort_mode": "city" if request.sort_by_city else "database",
        "min_population": request.min_population,
        "feature_option": request.feature_option,
        "include_header": request.include_header,
        "include_title": request.include_title,
    }


def _fast_listgeo_row_json(
    row: GeolocationListRow,
    *,
    include_alternate_names: bool,
) -> JsonObject:
    value: JsonObject = {
        "city": row.city,
        "region": row.region,
        "subregion": row.subregion,
        "country_code": row.country_code,
        "country": row.country,
        "timezone": row.timezone,
        "feature_code": row.feature_code,
        "population": row.population,
        "latitude": row.latitude,
        "longitude": row.longitude,
    }
    if include_alternate_names:
        value["alternate_names"] = row.alternate_names
    return value


def _run_public_main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    simple_read_exit_code = _try_run_simple_top_level_read(raw_args)
    if simple_read_exit_code is not None:
        return simple_read_exit_code
    simple_read_exit_code = _try_run_simple_read_subcommand(raw_args)
    if simple_read_exit_code is not None:
        return simple_read_exit_code
    simple_read_exit_code = _try_run_simple_json_read_subcommand(raw_args)
    if simple_read_exit_code is not None:
        return simple_read_exit_code
    if _parse_startup_help(raw_args):
        return 0
    if not raw_args:
        _print_startup_help()
        return 0
    if _is_top_level_version_request(raw_args):
        print(_public_version_text())
        return 0
    if raw_args[0] == "server":
        from exifmodern.public_interface.server_mode import main as server_main

        return server_main(raw_args[1:])
    fast_listgeo_exit_code = _try_run_fast_listgeo(raw_args)
    if fast_listgeo_exit_code is not None:
        return fast_listgeo_exit_code

    _ensure_public_cli_runtime_imports()
    parser = build_parser()
    try:
        stay_open_request = _top_level_stay_open_request(raw_args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if stay_open_request is not None:
        return _run_top_level_stay_open_driver(
            stay_open_request.argfile,
            parser,
            command_runner=main,
            common_args=stay_open_request.common_args,
        )
    try:
        if _is_top_level_batch_execution_request(raw_args):
            raw_args = expand_top_level_argfiles(raw_args)
            return _run_top_level_batch_execution(raw_args, parser)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    quiet_count = 0
    ignore_minor_errors = False
    try:
        prepared = prepare_deferred_top_level_options(
            raw_args,
            quiet_count=quiet_count,
            ignore_minor_errors=ignore_minor_errors,
        )
        raw_args = prepared.args
        quiet_count = prepared.quiet_count
        ignore_minor_errors = prepared.ignore_minor_errors
        raw_args = expand_top_level_argfiles(raw_args)
        if _is_top_level_batch_execution_request(raw_args):
            return _run_top_level_batch_execution(raw_args, parser)
        prepared = prepare_deferred_top_level_options(
            raw_args,
            quiet_count=quiet_count,
            ignore_minor_errors=ignore_minor_errors,
        )
        raw_args = prepared.args
        quiet_count = prepared.quiet_count
        ignore_minor_errors = prepared.ignore_minor_errors
        echo_options = prepare_top_level_echo_options(raw_args)
        raw_args = echo_options.args
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if _is_top_level_version_request(raw_args):
        print(_public_version_text())
        print_deferred_echo_options(echo_options)
        return 0
    if not raw_args and echo_options.had_echo:
        print_deferred_echo_options(echo_options)
        return 0
    if _is_explicit_subcommand_help_request(raw_args):
        parser.parse_args(raw_args)
        return 0
    if is_top_level_list_request(raw_args):
        exit_code = _run_top_level_list(raw_args, parser, quiet_count=quiet_count)
        print_deferred_echo_options(echo_options)
        return exit_code
    if _is_top_level_geotag_request(raw_args):
        exit_code = _run_top_level_geotag(
            raw_args,
            parser,
            quiet_count=quiet_count,
            ignore_minor_errors=ignore_minor_errors,
        )
        print_deferred_echo_options(echo_options)
        return exit_code
    if _is_top_level_write_request(raw_args):
        exit_code = _run_top_level_write(
            raw_args,
            parser,
            quiet_count=quiet_count,
            ignore_minor_errors=ignore_minor_errors,
        )
        print_deferred_echo_options(echo_options)
        return exit_code
    if _is_top_level_read_request(raw_args):
        exit_code = _run_top_level_read(
            raw_args,
            parser,
            quiet_count=quiet_count,
            ignore_minor_errors=ignore_minor_errors,
        )
        print_deferred_echo_options(echo_options)
        return exit_code

    try:
        raw_args = _prepare_read_subcommand_double_dash_exclusions(raw_args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    raw_args = _normalize_write_subcommand_output_values(raw_args)
    args = parser.parse_args(raw_args)

    if args.command == "read":
        unknown_tag_options = public_unknown_tag_options_from_namespace(args, "unknown_tag_options")
        recursive = args.recursive or args.recurse_dot_directories
        ignore_directories = tuple(args.ignore_directories)
        extension_filters = tuple(args.extension_filters)
        read_request = MetadataReadRequest(
            paths=expand_public_cli_read_paths(
                tuple(args.paths),
                recursive=recursive,
                recurse_dot_directories=args.recurse_dot_directories,
                ignore_directories=ignore_directories,
                extension_filters=extension_filters,
            ),
            tags=tuple(args.tag),
            tag_exclusions=public_read_tag_exclusions_from_raw(args.tag_exclusions),
            recursive=recursive,
            recurse_dot_directories=args.recurse_dot_directories,
            ignore_directories=ignore_directories,
            fast_scan_level=args.fast_scan_level,
            extension_filters=extension_filters,
            render=_output_render_request_from_args(args),
        )
        read_result = read_metadata(read_request)
        read_result = _read_result_with_public_cli_option_diagnostics(
            read_result,
            unknown_tag_options,
            api_options=tuple(args.api_options),
            use_modules=tuple(args.use_modules),
        )
        read_result = read_result_with_bounded_validate_output(
            read_result,
            read_metadata_for_counts=read_metadata,
        )
        read_result = _emit_read_result(read_result)
        _print_read_diagnostics(read_result.diagnostics)
        return exit_code_for_status(read_result.status)

    if args.command == "inspect":
        inspect_result = inspect_file(FileInspectRequest(paths=tuple(args.paths)))
        print(
            json.dumps(
                file_inspect_result_to_json_value(inspect_result),
                indent=2,
                sort_keys=True,
            )
        )
        return exit_code_for_status(inspect_result.status)

    if args.command == "write":
        try:
            assignments, assignment_deletes = _parse_assignments(args.set)
            deletes = (*assignment_deletes, *_parse_deletes(args.delete))
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        if args.overwrite_original and args.overwrite_original_in_place:
            parser.error(
                "--overwrite-original and --overwrite-original-in-place are mutually exclusive"
            )
        policy: _PublicWritePolicy = "preserve_original"
        if args.overwrite_original:
            policy = "overwrite_original"
        if args.overwrite_original_in_place:
            policy = "overwrite_original_in_place"
        write_request = _metadata_write_request_from_public_write_parts(
            paths=tuple(args.paths),
            assignments=assignments,
            deletes=deletes,
            delete_order_indexes=(),
            policy=policy,
            preserve_file_times=args.preserve_file_times,
            write_output_file=(
                None
                if args.write_output_file is None
                else OutputWriteFileRouting(
                    output_path_template=args.write_output_file.as_posix(),
                    overwrite_policy=(
                        "overwrite_existing"
                        if policy == "overwrite_original"
                        else "error_if_exists"
                    ),
                    stdout=public_write_output_is_stdout_request(args.write_output_file.as_posix()),
                )
            ),
            list_separator=args.list_separator,
            tag_lookup_package_path=args.tag_lookup_package_path,
        )
        png_textout_plans = _png_textout_plan_reports_for_write_request(write_request)
        write_result = write_metadata(write_request)
        _emit_write_result(write_result, png_textout_plan_reports=png_textout_plans)
        print_diagnostics(write_result.diagnostics)
        return exit_code_for_status(write_result.status)

    if args.command == "capabilities":
        capability_tag_lookup_package_path = args.tag_lookup_package_path
        if capability_tag_lookup_package_path is None and (
            args.tag_names or args.writable_tag_names
        ):
            capability_tag_lookup_package_path = _public_generated_index_package_path()
        capability_result = query_capabilities(
            CapabilityQueryRequest(
                include_experimental=args.include_experimental,
                tag_names=tuple(args.tag_names),
                writable_tag_names=tuple(args.writable_tag_names),
                tag_lookup_package_path=capability_tag_lookup_package_path,
            )
        )
        if args.format == "text":
            print(_render_capability_query_text(capability_result), end="")
        else:
            print(
                json.dumps(
                    capability_query_result_to_json_value(capability_result),
                    indent=2,
                    sort_keys=True,
                )
            )
        return exit_code_for_status(capability_result.status)

    if args.command == "tag-lookup":
        tag_lookup_package_path = args.tag_lookup_package_path
        if tag_lookup_package_path is None:
            tag_lookup_package_path = _public_generated_index_package_path()
        tag_lookup_result = query_tag_lookup(
            PublicTagLookupRequest(
                package_path=tag_lookup_package_path,
                tag_names=tuple(args.tag_names),
                writable_tag_names=tuple(args.writable_tag_names),
            )
        )
        print(
            json.dumps(
                public_tag_lookup_result_to_json_value(tag_lookup_result),
                indent=2,
                sort_keys=True,
            )
        )
        print_diagnostics(tag_lookup_result.diagnostics)
        return exit_code_for_status(tag_lookup_result.status)

    if args.command == "listgeo":
        geolocation_package_path = args.geolocation_package_path
        if geolocation_package_path is None:
            geolocation_package_path = _public_geolocation_package_path()
        try:
            listgeo_request = public_geolocation_list_request_from_parts(
                package_path=geolocation_package_path,
                api_options=tuple(args.api_options),
                sort_by_city=args.sort_by_city,
                language_code=args.language_code,
                include_title=quiet_count == 0,
            )
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        listgeo_result = list_geolocation(listgeo_request)
        if args.json_output:
            print(
                json.dumps(
                    public_geolocation_list_result_to_json_value(listgeo_result),
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(listgeo_result.rendered_text, end="")
        print_diagnostics(listgeo_result.diagnostics)
        return exit_code_for_status(listgeo_result.status)

    if args.command == "package-data":
        package_data = _public_package_data_report()
        if args.format == "json":
            print(json.dumps(package_data, indent=2, sort_keys=True))
        else:
            print(_render_public_package_data_text(package_data), end="")
        return 0

    parser.error(f"unsupported command: {args.command}")


_SIMPLE_READ_TEXT_LABELS: dict[str, str] = {
    "CircleOfConfusion": "Circle Of Confusion",
    "DateTimeOriginal": "Date/Time Original",
    "ExifToolVersion": "ExifTool Version Number",
    "FileAccessDate": "File Access Date/Time",
    "FileCreateDate": "File Creation Date/Time",
    "FileInodeChangeDate": "File Inode Change Date/Time",
    "FileModifyDate": "File Modification Date/Time",
    "FOV": "Field Of View",
    "FocalLength35efl": "Focal Length 35mm Equiv",
    "HyperfocalDistance": "Hyperfocal Distance",
    "InteropIndex": "Interoperability Index",
    "InteropVersion": "Interoperability Version",
    "Model": "Camera Model Name",
    "Now": "Now",
    "ScaleFactor35efl": "Scale Factor To 35 mm Equivalent",
}
_SIMPLE_ZERO_SUBSECOND_COMPOSITE_TAGS = frozenset(
    {
        "SubSecModifyDate",
        "SubSecCreateDate",
        "SubSecDateTimeOriginal",
    }
)
_SIMPLE_READ_JPEG_SUFFIXES = frozenset({".jpg", ".jpeg", ".jpe"})
_SIMPLE_JSON_READ_SUFFIXES = frozenset(
    {
        ".jpe",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp4",
        ".pdf",
        ".png",
        ".rw2",
        ".webp",
    }
)
_SIMPLE_EXIFTOOL_JSON_NUMBER_RE = re.compile(
    r"^-?(\d|[1-9]\d{1,14})(\.\d{1,16})?(e[-+]?\d{1,3})?$",
    re.IGNORECASE,
)
_PUBLIC_SUBCOMMANDS = frozenset(subcommand for subcommand, _help_text in _PUBLIC_SUBCOMMAND_HELP)


def _try_run_simple_top_level_read(args: Sequence[str]) -> int | None:
    if not args or any(arg.startswith("-") or arg in _PUBLIC_SUBCOMMANDS for arg in args):
        return None
    paths = tuple(Path(arg) for arg in args)
    if not all(path.is_file() for path in paths):
        return None

    try:
        rendered_parts: list[str] = []
        diagnostics: list[str] = []
        for path in paths:
            rendered, path_diagnostics = _simple_top_level_read_file_text(path)
            rendered_parts.append(rendered)
            diagnostics.extend(f"{path}: {diagnostic}" for diagnostic in path_diagnostics)
    except OSError, ValueError:
        return None
    print("".join(rendered_parts), end="")
    for diagnostic in diagnostics:
        print(f"read_graph_diagnostic: {diagnostic}", file=sys.stderr)
    return 0


def _try_run_simple_read_subcommand(args: Sequence[str]) -> int | None:
    if len(args) < 2 or args[0] != "read":
        return None
    read_args = args[1:]
    if any(arg.startswith("-") for arg in read_args):
        return None
    paths = tuple(Path(arg) for arg in read_args)
    if not all(path.is_file() for path in paths):
        return None

    try:
        rendered_parts: list[str] = []
        diagnostics: list[str] = []
        for path in paths:
            rendered, path_diagnostics = _simple_read_subcommand_file_text(path)
            rendered_parts.append(rendered)
            diagnostics.extend(f"{path}: {diagnostic}" for diagnostic in path_diagnostics)
    except OSError, ValueError:
        return None
    print("".join(rendered_parts), end="")
    for diagnostic in diagnostics:
        print(f"read_graph_diagnostic: {diagnostic}", file=sys.stderr)
    return 0


def _try_run_simple_json_read_subcommand(args: Sequence[str]) -> int | None:
    if len(args) < 3 or args[0] != "read":
        return None
    read_args = args[1:]
    if read_args[:2] == ["--format", "json"]:
        path_args = read_args[2:]
    elif read_args and read_args[0] in {"-json", "-j"}:
        path_args = read_args[1:]
    else:
        return None
    if not path_args or any(arg.startswith("-") for arg in path_args):
        return None
    paths = tuple(Path(arg) for arg in path_args)
    if not all(path.is_file() for path in paths):
        return None
    if any(path.suffix.lower() not in _SIMPLE_JSON_READ_SUFFIXES for path in paths):
        return None

    try:
        rendered_parts: list[dict[str, JsonValue]] = []
        diagnostics: list[str] = []
        for path in paths:
            rendered, path_diagnostics = _simple_read_subcommand_file_json(path)
            rendered_parts.append(rendered)
            diagnostics.extend(f"{path}: {diagnostic}" for diagnostic in path_diagnostics)
    except OSError, ValueError:
        return None
    print(_simple_render_exiftool_json_records(rendered_parts), end="")
    for diagnostic in diagnostics:
        print(f"read_graph_diagnostic: {diagnostic}", file=sys.stderr)
    return 0


def _simple_top_level_read_file_text(path: Path) -> tuple[str, tuple[str, ...]]:
    from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION

    graph = _build_simple_read_graph(path)
    record = _simple_graph_record(graph, path.as_posix())
    record = {
        "ExifToolVersion": EXIFTOOL_COMPATIBILITY_VERSION,
        **{key: value for key, value in record.items() if key != "ExifToolVersion"},
    }
    return _simple_text_record(record), tuple(graph.diagnostics)


def _simple_read_subcommand_file_text(path: Path) -> tuple[str, tuple[str, ...]]:
    from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION

    graph = _build_simple_read_graph(path)
    record = _simple_graph_record(graph, path.as_posix())
    record = {
        "ExifToolVersion": EXIFTOOL_COMPATIBILITY_VERSION,
        **{key: value for key, value in record.items() if key != "ExifToolVersion"},
    }
    return _simple_text_record(record), tuple(graph.diagnostics)


def _simple_read_subcommand_file_json(path: Path) -> tuple[dict[str, JsonValue], tuple[str, ...]]:
    graph = _build_simple_read_graph(path)
    record = _simple_graph_record(graph, path.as_posix())
    return _simple_json_record(record), tuple(graph.diagnostics)


def _build_simple_read_graph(path: Path) -> ReadGraph:
    prefix = _simple_read_prefix(path)
    if path.suffix.lower() in _SIMPLE_READ_JPEG_SUFFIXES and prefix.startswith(b"\xff\xd8"):
        from exifmodern.read_graph import build_read_graph

        return build_read_graph(path, display_path=path.as_posix())

    from exifmodern.read_dispatch import build_dispatched_read_graph

    return build_dispatched_read_graph(path)


def _simple_read_prefix(path: Path) -> bytes:
    with path.open("rb") as file:
        return file.read(2)


def _simple_graph_record(graph: ReadGraph, source_file: str) -> dict[str, SimpleTextValue]:
    record: dict[str, SimpleTextValue] = {"SourceFile": source_file}
    seen_default_tag_names: set[str] = set()
    for tag in graph.tags:
        if _simple_skips_output_tag(tag, seen_default_tag_names):
            continue
        record[tag.name] = tag.value
    return record


def _simple_json_record(record: Mapping[str, SimpleTextValue]) -> dict[str, JsonValue]:
    return {key: _simple_json_value(value) for key, value in record.items()}


def _simple_json_value(value: SimpleTextValue) -> JsonValue:
    binary_list_text = _simple_binary_list_text(value)
    if binary_list_text is not None:
        return binary_list_text
    binary_text = _simple_binary_text(value)
    if binary_text is not None:
        return binary_text
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Sequence):
        return [_simple_json_scalar(item) for item in value]
    raise TypeError(f"Unsupported simple JSON value: {type(value).__name__}")


def _simple_json_scalar(value: SimpleTextScalar) -> JsonValue:
    return value


def _simple_render_exiftool_json_records(records: Sequence[Mapping[str, JsonValue]]) -> str:
    lines = ["["]
    for index, record in enumerate(records):
        lines.append("{")
        lines.extend(_simple_render_exiftool_json_record_body(record))
        lines.append("}," if index < len(records) - 1 else "}")
    lines.append("]")
    return "\n".join(lines) + "\n"


def _simple_render_exiftool_json_record_body(record: Mapping[str, JsonValue]) -> list[str]:
    lines: list[str] = []
    items = list(record.items())
    for index, (key, value) in enumerate(items):
        suffix = "," if index < len(items) - 1 else ""
        lines.append(
            f"  {json.dumps(key, ensure_ascii=False)}: "
            f"{_simple_render_exiftool_json_value(value)}{suffix}"
        )
    return lines


def _simple_render_exiftool_json_value(value: JsonValue) -> str:
    if isinstance(value, list):
        rendered_items = ",".join(_simple_render_exiftool_json_value(item) for item in value)
        return f"[{rendered_items}]"
    if isinstance(value, dict):
        rendered_items = ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{_simple_render_exiftool_json_value(item)}"
            for key, item in value.items()
        )
        return f"{{{rendered_items}}}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "null"
    if _simple_is_exiftool_json_unquoted_string(value):
        return value.lower() if value.lower() in {"true", "false"} else value
    return json.dumps(value, ensure_ascii=False)


def _simple_is_exiftool_json_unquoted_string(value: str) -> bool:
    return (
        value.lower() in {"true", "false"}
        or _SIMPLE_EXIFTOOL_JSON_NUMBER_RE.fullmatch(value) is not None
    )


def _simple_skips_output_tag(tag: ReadTag, seen_default_tag_names: set[str]) -> bool:
    if _simple_skips_unknown_tag(tag):
        return True
    if tag.name in seen_default_tag_names:
        return True
    seen_default_tag_names.add(tag.name)
    return False


def _simple_skips_unknown_tag(tag: ReadTag) -> bool:
    if not _simple_may_have_public_output_suppression(tag):
        return False
    return _simple_public_output_suppression_for_tag(tag) is not None


def _simple_public_output_suppression_for_tag(tag: ReadTag) -> PublicOutputSuppression | None:
    global _SIMPLE_PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG
    if _SIMPLE_PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG is None:
        from exifmodern.public_interface.output_policy import public_output_suppression_for_tag

        _SIMPLE_PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG = public_output_suppression_for_tag
    return _SIMPLE_PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG(tag)


def _simple_may_have_public_output_suppression(tag: ReadTag) -> bool:
    provenance = tag.provenance
    table_name = provenance.table_name
    if table_name in {
        "Image::ExifTool::Apple::Main",
        "Image::ExifTool::Matroska::Main",
        "Image::ExifTool::MacOS::Main",
        "Image::ExifTool::Unknown::Main",
    }:
        return True
    if table_name.startswith("Image::ExifTool::EXE::"):
        return True
    return provenance.source == "jpeg-app1-tiff-dynamic-unknown" and table_name in {
        "Image::ExifTool::Exif::Main",
        "Image::ExifTool::GPS::Main",
    }


def _simple_text_record(record: Mapping[str, SimpleTextValue]) -> str:
    lines: list[str] = []
    for key, value in record.items():
        if key == "SourceFile":
            continue
        if key in _SIMPLE_ZERO_SUBSECOND_COMPOSITE_TAGS and isinstance(value, str):
            continue
        lines.append(f"{_simple_text_label(key, record):<32}: {_simple_text_value(value)}\n")
    return "".join(lines)


def _simple_text_label(key: str, record: Mapping[str, SimpleTextValue]) -> str:
    if (
        key == "Model"
        and _simple_record_file_type(record) in {"MOV", "MP4", "M4V", "3GP"}
        and not _simple_record_has_embedded_exif_camera_model(record)
    ):
        return "Model"
    if key.endswith("-jpn-JP"):
        return f"{key.removesuffix('-jpn-JP')} (jpn-JP)"
    return _SIMPLE_READ_TEXT_LABELS.get(key, key)


def _simple_record_file_type(record: Mapping[str, SimpleTextValue]) -> str | None:
    value = record.get("FileType")
    return value.upper() if isinstance(value, str) else None


def _simple_record_has_embedded_exif_camera_model(record: Mapping[str, SimpleTextValue]) -> bool:
    return record.get("Make") == "Panasonic" and "ExifByteOrder" in record


def _simple_text_value(value: SimpleTextValue) -> str:
    binary_list_text = _simple_binary_list_text(value)
    if binary_list_text is not None:
        return binary_list_text
    binary_text = _simple_binary_text(value)
    if binary_text is not None:
        return binary_text
    if isinstance(value, list):
        return ", ".join(_simple_text_value(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _simple_binary_list_text(value: SimpleTextValue) -> str | None:
    items = getattr(value, "items", None)
    if not isinstance(items, tuple):
        return None
    item_text = tuple(_simple_binary_text(item) for item in items)
    if any(text is None for text in item_text):
        return None
    return ", ".join(text for text in item_text if text is not None)


def _simple_binary_text(value: SimpleTextValue) -> str | None:
    byte_count = getattr(value, "byte_count", None)
    if not isinstance(byte_count, int):
        return None
    return f"(Binary data {byte_count} bytes, use -b option to extract)"


def _render_capability_query_text(result: CapabilityQueryResult) -> str:
    """Render public CLI text sections including TagLookup query summary.

    The delegated renderer emits "TagLookup query summary:" and
    "TagLookup writable selections:" when package-backed TagLookup data is
    included in the public capability query.
    """
    return _render_public_capability_query_text(result)


def _public_package_data_report() -> JsonObject:
    from exifmodern.package_resources import (
        charset_language_manifest_path,
        charset_language_package_path,
        generated_index_geolocation_repository_pickle_path,
        generated_index_manifest_path,
        generated_index_package_path,
        generated_index_shard_path,
        maker_note_manifest_path,
        maker_note_package_path,
        runtime_data_resource_path,
    )

    resources = {
        "runtime_manifest_json": runtime_data_resource_path("runtime-data-manifest.json"),
        "runtime_manifest_pickle": runtime_data_resource_path("runtime-data-manifest.pickle"),
        "generated_index_package": generated_index_package_path(),
        "generated_index_manifest": generated_index_manifest_path(),
        "generated_index_tag_lookup": generated_index_shard_path("tag_lookup"),
        "generated_index_geolocation": generated_index_shard_path("geolocation"),
        "generated_index_geolocation_repository": (
            generated_index_geolocation_repository_pickle_path()
        ),
        "maker_note_package": maker_note_package_path(),
        "maker_note_manifest": maker_note_manifest_path(),
        "charset_language_package": charset_language_package_path(),
        "charset_language_manifest": charset_language_manifest_path(),
    }
    payload: JsonObject = {
        "operation": "package-data",
        "resources": [
            _public_package_data_resource_record(name, path)
            for name, path in sorted(resources.items())
        ],
    }
    return payload


def _public_package_data_resource_record(
    name: str,
    path: Path | None,
) -> JsonObject:
    exists = path is not None and path.exists()
    return {
        "name": name,
        "path": "" if path is None else path.as_posix(),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists and path is not None else 0,
    }


def _render_public_package_data_text(report: Mapping[str, JsonValue]) -> str:
    resources = report.get("resources")
    if not isinstance(resources, list):
        return ""
    lines = ["ExifModern package data resources:"]
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        name = resource.get("name", "")
        exists = resource.get("exists", False)
        size_bytes = resource.get("size_bytes", 0)
        path = resource.get("path", "")
        lines.append(f"  {name}: exists={exists} size={size_bytes} path={path}")
    return "\n".join(lines) + "\n"


def _is_top_level_version_request(args: Sequence[str]) -> bool:
    return len(args) == 1 and args[0].lower() in {"-ver", "--ver"}


def _is_explicit_subcommand_help_request(args: Sequence[str]) -> bool:
    if len(args) < 2:
        return False
    if args[0] not in {
        "read",
        "inspect",
        "write",
        "capabilities",
        "tag-lookup",
        "listgeo",
        "package-data",
    }:
        return False
    return any(arg in {"-h", "--help"} for arg in args[1:])


def _is_top_level_batch_execution_request(args: Sequence[str]) -> bool:
    if not args or args[0] in {
        "read",
        "inspect",
        "write",
        "capabilities",
        "tag-lookup",
        "listgeo",
        "package-data",
        "-h",
        "--help",
    }:
        return False
    end_of_options = False
    for arg in args:
        if arg == "--":
            end_of_options = True
            continue
        if end_of_options:
            continue
        if _is_execute_option(arg) or arg.lower() == "-common_args":
            return True
    return False


def _run_top_level_batch_execution(
    args: Sequence[str],
    parser: argparse.ArgumentParser,
) -> int:
    try:
        requests = build_batch_execution_requests(args)
    except ValueError as exc:
        parser.error(str(exc))

    exit_code = 0
    for request in requests:
        if not request.args:
            continue
        try:
            frame_exit_code = main(list(request.args))
        except SystemExit as exc:
            frame_exit_code = _system_exit_code(exc)
        exit_code = _aggregate_batch_exit_code(exit_code, frame_exit_code)
    return exit_code


def _system_exit_code(exc: SystemExit) -> int:
    if isinstance(exc.code, int):
        return exc.code
    if exc.code is None:
        return 0
    return 2


def _aggregate_batch_exit_code(current: int, frame_exit_code: int) -> int:
    if current == 1 or frame_exit_code == 1:
        return 1
    if current != 0:
        return current
    return frame_exit_code


def _public_version_text() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("exifmodern")
    except PackageNotFoundError:
        return "0.1.0"


def _is_top_level_read_request(args: Sequence[str]) -> bool:
    if not args:
        return False
    if args[0] == "-h" and len(args) > 1:
        return True
    return args[0] not in {
        "read",
        "inspect",
        "write",
        "capabilities",
        "tag-lookup",
        "listgeo",
        "package-data",
        "-h",
        "--help",
    }


def _is_top_level_write_request(args: Sequence[str]) -> bool:
    if not args or args[0] in {
        "read",
        "inspect",
        "write",
        "capabilities",
        "tag-lookup",
        "listgeo",
        "package-data",
        "-h",
        "--help",
    }:
        return False
    return any(_is_top_level_write_token(arg) for arg in args)


def _is_top_level_write_token(arg: str) -> bool:
    lower_arg = arg.lower()
    if lower_arg in {
        "-overwrite_original",
        "-overwriteoriginal",
        "-overwrite_original_in_place",
        "-delete_original",
        "-delete_original!",
        "-restore_original",
        "-geotag",
    }:
        return True
    if _is_tags_from_file_option(arg):
        return True
    if not arg.startswith("-") or arg.startswith("--"):
        return False
    tag_argument = arg.removeprefix("-")
    return "=" in tag_argument or "<" in tag_argument or ">" in tag_argument


def _run_top_level_geotag(
    args: Sequence[str],
    parser: argparse.ArgumentParser,
    *,
    quiet_count: int,
    ignore_minor_errors: bool,
) -> int:
    from exifmodern.formats.geotag.public_workflow import (
        plan_public_geotag_workflow,
        public_geotag_workflow_result_to_json_value,
    )
    from exifmodern.public_interface.diagnostic_output import print_diagnostics

    try:
        request = _parse_public_geotag_workflow_request(args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    result = plan_public_geotag_workflow(request)
    print(
        json.dumps(
            public_geotag_workflow_result_to_json_value(result),
            indent=2,
            sort_keys=True,
        )
    )
    print_diagnostics(
        result.diagnostics,
        quiet_count=quiet_count,
        ignore_minor_errors=ignore_minor_errors,
    )
    return exit_code_for_status(result.status)


def _run_top_level_list(
    args: Sequence[str],
    parser: argparse.ArgumentParser,
    *,
    quiet_count: int,
) -> int:
    from exifmodern.public_interface.list_catalog_data import public_list_catalog

    try:
        rendered = render_top_level_list(
            args,
            catalog=public_list_catalog(),
            quiet_count=quiet_count,
            geolocation_package=_public_geolocation_package_path(),
        )
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    print(rendered, end="")
    return 0


def _run_top_level_write(
    args: Sequence[str],
    parser: argparse.ArgumentParser,
    *,
    quiet_count: int,
    ignore_minor_errors: bool,
) -> int:
    try:
        write_request = _parse_top_level_write_request(args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    png_textout_plans = _png_textout_plan_reports_for_write_request(write_request)
    write_result = write_metadata(write_request)
    _emit_write_result(write_result, png_textout_plan_reports=png_textout_plans)
    print_diagnostics(
        write_result.diagnostics,
        quiet_count=quiet_count,
        ignore_minor_errors=ignore_minor_errors,
    )
    return exit_code_for_status(write_result.status)


def _emit_write_result(
    write_result: MetadataWriteResult,
    *,
    png_textout_plan_reports: JsonArray,
) -> None:
    if write_result.stdout_binary:
        sys.stdout.buffer.write(write_result.stdout_binary)
        return
    print(
        json.dumps(
            _metadata_write_result_to_json_value_with_cli_reports(
                write_result,
                png_textout_plan_reports=png_textout_plan_reports,
            ),
            indent=2,
            sort_keys=True,
        )
    )


def _normalize_write_subcommand_output_values(args: Sequence[str]) -> list[str]:
    if not args or args[0] != "write":
        return list(args)
    normalized = [args[0]]
    index = 1
    while index < len(args):
        arg = args[index]
        if arg in _WRITE_SUBCOMMAND_OUTPUT_VALUE_OPTIONS and index + 1 < len(args):
            normalized.append(f"{arg}={args[index + 1]}")
            index += 2
            continue
        normalized.append(arg)
        index += 1
    return normalized


def _run_top_level_read(
    args: Sequence[str],
    parser: argparse.ArgumentParser,
    *,
    quiet_count: int,
    ignore_minor_errors: bool,
) -> int:
    try:
        read_request = _parse_top_level_read_request(args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if ignore_minor_errors:
        from dataclasses import replace

        read_request = replace(
            read_request,
            render=replace(read_request.render, ignore_minor_errors=True),
        )
    read_result = read_metadata(read_request)
    read_result = _read_result_with_public_cli_option_diagnostics(
        read_result,
        public_unknown_tag_options_from_args(args),
        api_options=_top_level_read_api_options(args),
    )
    read_result = read_result_with_bounded_validate_output(
        read_result,
        read_metadata_for_counts=read_metadata,
    )
    read_result = _emit_read_result(read_result)
    _print_read_diagnostics(
        read_result.diagnostics,
        quiet_count=quiet_count,
        ignore_minor_errors=ignore_minor_errors,
    )
    return exit_code_for_status(read_result.status)


def _parse_top_level_write_request(args: Sequence[str]) -> MetadataWriteRequest:
    _ensure_public_cli_runtime_imports()
    return _write_request_parsing.parse_top_level_write_request(
        args,
        metadata_write_request_from_public_parts=_metadata_write_request_from_public_write_parts,
        png_copy_from_file_request_or_none=_parse_png_copy_from_file_request_or_none,
    )


def _parse_top_level_tags_from_file_write_request(
    args: Sequence[str],
    *,
    source_file: str,
    route_start_index: int,
    paths_before: tuple[Path, ...],
    policy: _PublicWritePolicy,
    preserve_file_times: bool = False,
    tag_lookup_package_path: Path | None = None,
    write_output_file: OutputWriteFileRouting | None = None,
) -> MetadataWriteRequest:
    _ensure_public_cli_runtime_imports()
    return _write_request_parsing.parse_top_level_tags_from_file_write_request(
        args,
        source_file=source_file,
        route_start_index=route_start_index,
        paths_before=paths_before,
        policy=policy,
        preserve_file_times=preserve_file_times,
        tag_lookup_package_path=tag_lookup_package_path,
        png_copy_from_file_request_or_none=_parse_png_copy_from_file_request_or_none,
    )


def _metadata_write_request_from_public_write_parts(
    *,
    paths: tuple[Path, ...],
    assignments: tuple[MetadataAssignment, ...],
    deletes: tuple[str, ...],
    delete_order_indexes: tuple[int, ...],
    policy: _PublicWritePolicy,
    preserve_file_times: bool = False,
    write_output_file: OutputWriteFileRouting | None = None,
    list_separator: str | None = None,
    tag_lookup_package_path: Path | None = None,
) -> MetadataWriteRequest:
    riff_webp_metadata_write = _riff_webp_metadata_write_request_from_public_parts(
        paths=paths,
        assignments=assignments,
        deletes=deletes,
    )
    if riff_webp_metadata_write is not None:
        return MetadataWriteRequest(
            paths=paths,
            riff_webp_metadata_write=riff_webp_metadata_write,
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
            list_separator=list_separator,
            tag_lookup_package_path=tag_lookup_package_path,
        )
    riff_wav_metadata_write = _riff_wav_metadata_write_request_from_public_parts(
        paths=paths,
        assignments=assignments,
        deletes=deletes,
    )
    if riff_wav_metadata_write is not None:
        return MetadataWriteRequest(
            paths=paths,
            riff_wav_metadata_write=riff_wav_metadata_write,
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
            list_separator=list_separator,
            tag_lookup_package_path=tag_lookup_package_path,
        )
    png_chunk_write = _png_chunk_write_request_from_public_parts(
        paths=paths,
        assignments=assignments,
        deletes=deletes,
    )
    if png_chunk_write is not None:
        return MetadataWriteRequest(
            paths=paths,
            png_chunk_write=png_chunk_write,
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
            list_separator=list_separator,
            tag_lookup_package_path=tag_lookup_package_path,
        )
    return MetadataWriteRequest(
        paths=paths,
        assignments=assignments,
        deletes=deletes,
        delete_order_indexes=delete_order_indexes,
        policy=policy,
        preserve_file_times=preserve_file_times,
        write_output_file=write_output_file,
        list_separator=list_separator,
        tag_lookup_package_path=tag_lookup_package_path,
    )


def _riff_wav_metadata_write_request_from_public_parts(
    *,
    paths: tuple[Path, ...],
    assignments: tuple[MetadataAssignment, ...],
    deletes: tuple[str, ...],
) -> RiffWavMetadataWriteRequest | None:
    if not paths or not all(path.suffix.lower() in {".wav", ".avi"} for path in paths):
        return None
    if assignments:
        return None
    if len(deletes) == 1 and _is_public_delete_all_target(deletes[0]):
        return RiffWavMetadataWriteRequest(delete_all_modeled_metadata=True)
    return None


def _riff_webp_metadata_write_request_from_public_parts(
    *,
    paths: tuple[Path, ...],
    assignments: tuple[MetadataAssignment, ...],
    deletes: tuple[str, ...],
) -> RiffWebpMetadataWriteRequest | None:
    if not paths or not all(path.suffix.lower() == ".webp" for path in paths):
        return None
    if assignments:
        return None
    if len(deletes) == 1 and _is_public_delete_all_target(deletes[0]):
        return RiffWebpMetadataWriteRequest(delete_all_metadata=True)
    return None


def _is_public_delete_all_target(delete: str) -> bool:
    normalized = delete.lower().replace("all", "*")
    return normalized in {"*", "*:*"}


def _png_chunk_write_request_from_public_parts(
    *,
    paths: tuple[Path, ...],
    assignments: tuple[MetadataAssignment, ...],
    deletes: tuple[str, ...],
) -> PngChunkWriteRequest | None:
    if not paths or not all(path.suffix.lower() == ".png" for path in paths):
        return None

    text_chunks: list[PngTextChunkWriteRequest] = []
    xmp_payload: bytes | None = None
    xmp_assignments: list[MetadataAssignment] = []
    exif_assignments: list[MetadataAssignment] = []
    delete_groups: list[str] = []
    delete_all_metadata = False

    for assignment in assignments:
        text_request = _png_text_chunk_write_request_from_assignment(assignment)
        if text_request is not None:
            text_chunks.append(text_request)
            continue
        if _is_png_xmp_payload_assignment(assignment.tag):
            xmp_payload = assignment.value.encode("utf-8")
            continue
        if _is_png_xmp_scalar_assignment(assignment.tag):
            xmp_assignments.append(assignment)
            continue
        if _is_png_exif_scalar_assignment(assignment.tag):
            exif_assignments.append(assignment)
            continue
        return None

    for delete in deletes:
        delete_target = _png_delete_target(delete)
        if delete_target is None:
            return None
        if delete_target == "all":
            delete_all_metadata = True
            continue
        delete_groups.append(delete_target)

    xmp_payload = _png_xmp_payload_from_assignments(
        tuple(xmp_assignments),
        existing_payload=xmp_payload,
    )
    if xmp_assignments and xmp_payload is None:
        return None
    if not text_chunks and xmp_payload is None and not delete_groups and not delete_all_metadata:
        if not exif_assignments:
            return None
    exif_payload = _png_exif_scalar_payload_from_assignments(tuple(exif_assignments))
    if exif_assignments and exif_payload is None:
        return None
    return PngChunkWriteRequest(
        text_chunks=tuple(text_chunks),
        xmp_payload=xmp_payload,
        exif_payload=exif_payload,
        delete_metadata_groups=tuple(delete_groups),
        delete_all_metadata=delete_all_metadata,
    )


def _png_text_chunk_write_request_from_assignment(
    assignment: MetadataAssignment,
) -> PngTextChunkWriteRequest | None:
    group, tag_name = _split_public_write_tag(assignment.tag)
    if group != "png":
        return None
    keyword, language_code = _png_text_keyword_and_language(tag_name)
    if keyword is None:
        return None
    return PngTextChunkWriteRequest(
        keyword=keyword,
        value=assignment.value.encode("utf-8"),
        language_code=language_code,
    )


def _is_png_xmp_payload_assignment(tag: str) -> bool:
    group, tag_name = _split_public_write_tag(tag)
    return group == "png" and tag_name.lower() in {"xmp", "xml:com.adobe.xmp"}


def _is_png_xmp_scalar_assignment(tag: str) -> bool:
    group, tag_name = _split_public_write_tag(tag)
    canonical_group = group.replace("_", "-")
    canonical_tag = tag_name.lower()
    return (
        canonical_group in {"xmp", "xmp-photoshop"} and canonical_tag in {"city", "datecreated"}
    ) or (canonical_group == "xmp-xmpmm" and canonical_tag == "documentid")


def _png_xmp_payload_from_assignments(
    assignments: tuple[MetadataAssignment, ...],
    *,
    existing_payload: bytes | None = None,
) -> bytes | None:
    if not assignments:
        return existing_payload
    city: str | None = None
    date_created: str | None = None
    document_id: str | None = None
    for assignment in assignments:
        group, tag_name = _split_public_write_tag(assignment.tag)
        canonical_group = group.replace("_", "-")
        match (canonical_group, tag_name.lower()):
            case ("xmp", "city") | ("xmp-photoshop", "city"):
                city = assignment.value
            case ("xmp", "datecreated") | ("xmp-photoshop", "datecreated"):
                date_created = assignment.value
            case ("xmp-xmpmm", "documentid"):
                document_id = assignment.value
            case _:
                return None
    plan = build_xmp_property_write_plan(
        photoshop_city=city,
        photoshop_date_created=date_created,
        xmpmm_document_id=document_id,
    )
    source_packet = existing_payload if existing_payload is not None else empty_xmp_packet()
    return apply_xmp_property_write_plan(source_packet, plan).packet


def _is_png_exif_scalar_assignment(tag: str) -> bool:
    group, tag_name = _split_public_write_tag(tag)
    return group in {"exif", "ifd0", "exififd"} and tag_name.lower() in {
        "artist",
        "description",
        "imagedescription",
        "orientation",
        "modifydate",
        "datetimeoriginal",
        "iso",
        "focallength",
        "scenecapturetype",
    }


def _png_exif_scalar_payload_from_assignments(
    assignments: tuple[MetadataAssignment, ...],
) -> bytes | None:
    if not assignments:
        return None
    image_description: str | None = None
    orientation: str | None = None
    modify_date: str | None = None
    artist: str | None = None
    iso: str | None = None
    date_time_original: str | None = None
    focal_length: str | None = None
    scene_capture_type: str | None = None

    for assignment in assignments:
        _group, tag_name = _split_public_write_tag(assignment.tag)
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
        plan = build_exif_scalar_write_plan(
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
    return create_minimal_exif_scalar_tiff(plan)


def _png_text_keyword_and_language(tag_name: str) -> tuple[str | None, str]:
    base_name = tag_name
    language_code = ""
    if "-" in tag_name:
        candidate_base, candidate_language = tag_name.rsplit("-", 1)
        if candidate_base and _is_rfc3066_like_language_code(candidate_language):
            base_name = candidate_base
            language_code = candidate_language
    keyword = _PUBLIC_PNG_TEXT_KEYWORDS_BY_TAG.get(base_name.lower().replace(" ", ""))
    return keyword, language_code


def _is_rfc3066_like_language_code(value: str) -> bool:
    if not value:
        return False
    return all(part.isalpha() and 1 <= len(part) <= 8 for part in value.split("-"))


def _png_delete_target(tag: str) -> str | None:
    group, tag_name = _split_public_write_tag(tag)
    if not group and tag_name.lower() in _PUBLIC_PNG_DELETE_ALL_TAGS:
        return "all"
    if group in _PUBLIC_PNG_DELETE_ALL_TAGS and tag_name.lower() in _PUBLIC_PNG_DELETE_ALL_TAGS:
        return "all"
    if group in _PUBLIC_PNG_DELETE_GROUPS and tag_name.lower() in _PUBLIC_PNG_DELETE_ALL_TAGS:
        return _PUBLIC_PNG_DELETE_GROUP_DISPLAY_NAMES[group]
    return None


def _split_public_write_tag(tag: str) -> tuple[str, str]:
    group, separator, tag_name = tag.partition(":")
    if separator != ":":
        return "", tag
    return group.lower().replace("-", "_"), tag_name


def _parse_png_copy_from_file_request_or_none(
    *,
    source_file: str,
    routes: tuple[str, ...],
    assignments: tuple[MetadataAssignment, ...],
    deletes: tuple[str, ...],
    paths: tuple[Path, ...],
    policy: _PublicWritePolicy,
) -> MetadataWriteRequest | None:
    if not routes:
        return None
    normalized_routes = tuple(_normalize_png_copy_route(route) for route in routes)
    if not any(path.suffix.lower() == ".png" for path in paths):
        return None
    if any(route in _PUBLIC_PNG_UNSUPPORTED_NESTED_COPY_GROUPS for route in normalized_routes):
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason=(
                    "PNG nested raw-profile/IPTC/Photoshop copy materialization is not "
                    "implemented; ExifTool stores these as non-standard Raw profile "
                    "TextualData profiles requiring Photoshop/IPTC profile construction"
                ),
            )
        )
    if all(_is_png_icc_copy_route(route) for route in routes):
        return _parse_png_icc_copy_from_file_request(
            source_file=source_file,
            routes=routes,
            assignments=assignments,
            deletes=deletes,
            paths=paths,
            policy=policy,
        )
    if all(_is_png_exif_copy_route(route) for route in routes):
        return _parse_png_exif_copy_from_file_request(
            source_file=source_file,
            routes=routes,
            assignments=assignments,
            deletes=deletes,
            paths=paths,
            policy=policy,
        )
    if all(_is_png_xmp_copy_route(route) for route in routes):
        return _parse_png_xmp_copy_from_file_request(
            source_file=source_file,
            routes=routes,
            assignments=assignments,
            deletes=deletes,
            paths=paths,
            policy=policy,
        )
    return None


def _parse_png_icc_copy_from_file_request(
    *,
    source_file: str,
    routes: tuple[str, ...],
    assignments: tuple[MetadataAssignment, ...],
    deletes: tuple[str, ...],
    paths: tuple[Path, ...],
    policy: _PublicWritePolicy,
) -> MetadataWriteRequest:
    if not paths:
        raise argparse.ArgumentTypeError("at least one file or directory path is required")
    if source_file == "@":
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason="PNG ICC_Profile copy requires an explicit ICC source file",
            )
        )
    if deletes:
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason="PNG ICC_Profile copy does not support delete operations in this slice",
            )
        )
    profile_name = _png_icc_profile_name_assignment_or_defer(
        source_file=source_file,
        routes=routes,
        assignments=assignments,
    )
    unsupported_paths = tuple(path for path in paths if path.suffix.lower() != ".png")
    if unsupported_paths:
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason="PNG ICC_Profile copy is supported only for .png targets",
            )
        )
    try:
        icc_payload = Path(source_file).read_bytes()
    except OSError as exc:
        raise argparse.ArgumentTypeError(
            f"could not read ICC_Profile source for public PNG copy: {source_file}: {exc}"
        ) from exc
    return MetadataWriteRequest(
        paths=paths,
        png_chunk_write=PngChunkWriteRequest(
            icc_payload=icc_payload,
            icc_profile_name=profile_name,
        ),
        policy=policy,
    )


def _parse_png_exif_copy_from_file_request(
    *,
    source_file: str,
    routes: tuple[str, ...],
    assignments: tuple[MetadataAssignment, ...],
    deletes: tuple[str, ...],
    paths: tuple[Path, ...],
    policy: _PublicWritePolicy,
) -> MetadataWriteRequest:
    if source_file == "@":
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason="PNG EXIF copy requires an explicit source file",
            )
        )
    if assignments or deletes:
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason=(
                    "PNG EXIF copy is bounded to direct source-backed eXIf materialization "
                    "without mixed assignments or deletes"
                ),
            )
        )
    _raise_if_png_copy_targets_are_not_png(source_file=source_file, routes=routes, paths=paths)
    try:
        exif_payload, _materialization = source_backed_exif_tiff_payload(Path(source_file))
    except (OSError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            f"could not materialize EXIF source for public PNG copy: {source_file}: {exc}"
        ) from exc
    return MetadataWriteRequest(
        paths=paths,
        png_chunk_write=PngChunkWriteRequest(exif_payload=exif_payload),
        policy=policy,
    )


def _parse_png_xmp_copy_from_file_request(
    *,
    source_file: str,
    routes: tuple[str, ...],
    assignments: tuple[MetadataAssignment, ...],
    deletes: tuple[str, ...],
    paths: tuple[Path, ...],
    policy: _PublicWritePolicy,
) -> MetadataWriteRequest:
    if source_file == "@":
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason="PNG XMP copy requires an explicit source XMP packet file",
            )
        )
    if deletes:
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason="PNG XMP copy does not support delete operations in this slice",
            )
        )
    _raise_if_png_copy_targets_are_not_png(source_file=source_file, routes=routes, paths=paths)
    unsupported_assignments = tuple(
        assignment
        for assignment in assignments
        if not _is_png_xmp_scalar_assignment(assignment.tag)
    )
    if unsupported_assignments:
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason=(
                    "PNG XMP copy can be combined only with bounded XMP scalar "
                    "assignments in this public route"
                ),
            )
        )
    try:
        xmp_payload = Path(source_file).read_bytes()
    except OSError as exc:
        raise argparse.ArgumentTypeError(
            f"could not read XMP source for public PNG copy: {source_file}: {exc}"
        ) from exc
    materialized_xmp_payload = _png_xmp_payload_from_assignments(
        tuple(assignments),
        existing_payload=xmp_payload,
    )
    if materialized_xmp_payload is None:
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason="PNG XMP copy could not materialize the requested XMP packet",
            )
        )
    return MetadataWriteRequest(
        paths=paths,
        png_chunk_write=PngChunkWriteRequest(xmp_payload=materialized_xmp_payload),
        policy=policy,
    )


def _raise_if_png_copy_targets_are_not_png(
    *,
    source_file: str,
    routes: tuple[str, ...],
    paths: tuple[Path, ...],
) -> None:
    unsupported_paths = tuple(path for path in paths if path.suffix.lower() != ".png")
    if unsupported_paths:
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason="PNG copy materialization is supported only for .png targets",
            )
        )


def _normalize_png_copy_route(route: str) -> str:
    return route.lower().replace("-", "_")


def _is_png_icc_copy_route(route: str) -> bool:
    return _normalize_png_copy_route(route) in _PUBLIC_PNG_ICC_COPY_ROUTES


def _is_png_exif_copy_route(route: str) -> bool:
    return _normalize_png_copy_route(route) in _PUBLIC_PNG_EXIF_COPY_ROUTES


def _is_png_xmp_copy_route(route: str) -> bool:
    return _normalize_png_copy_route(route) in _PUBLIC_PNG_XMP_COPY_ROUTES


def _png_icc_profile_name_assignment_or_defer(
    *,
    source_file: str,
    routes: tuple[str, ...],
    assignments: tuple[MetadataAssignment, ...],
) -> str | None:
    profile_name: str | None = None
    for assignment in assignments:
        group, tag_name = _split_public_write_tag(assignment.tag)
        if group == "png" and tag_name.lower() == "profilename":
            profile_name = assignment.value
            continue
        raise argparse.ArgumentTypeError(
            _tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason=(
                    "PNG ICC_Profile copy can be combined only with PNG:ProfileName "
                    "in this bounded public route"
                ),
            )
        )
    return profile_name


class _ExtractEmbeddedLevelAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        if option_string is None:
            parser.error("internal extractEmbedded-level parser error")
        parsed_level = _parse_extract_embedded_option(option_string)
        if parsed_level is None:
            parser.error(f"unsupported extractEmbedded option: {option_string}")
        setattr(namespace, self.dest, parsed_level)


def _add_common_render_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("text", "json", "xml", "csv", "tab", "html", "php", "html_dump"),
        default="text",
        help="requested output format",
    )
    parser.add_argument(
        "-json",
        "-j",
        dest="format",
        action="store_const",
        const="json",
        help="use ExifTool-compatible JSON output format",
    )
    parser.add_argument(
        "-X",
        "-xmlFormat",
        "-xmlformat",
        dest="format",
        action="store_const",
        const="xml",
        help="use ExifTool-compatible RDF/XML output format",
    )
    parser.add_argument(
        "-csv",
        dest="format",
        action="store_const",
        const="csv",
        help="use ExifTool-compatible CSV output format",
    )
    parser.add_argument(
        "-htmlFormat",
        "-htmlformat",
        dest="format",
        action="store_const",
        const="html",
        help="use bounded ExifTool-compatible HTML table output",
    )
    parser.add_argument(
        "-php",
        dest="format",
        action="store_const",
        const="php",
        help="use bounded ExifTool-compatible PHP Array output",
    )
    parser.add_argument(
        "-htmlDump",
        "-htmldump",
        dest="format",
        action="store_const",
        const="html_dump",
        help="recognize ExifTool htmlDump output and report a typed blocker",
    )
    parser.add_argument(
        "-t",
        "-tab",
        dest="tab_format",
        action="store_true",
        help="use ExifTool tab-delimited list output format",
    )
    parser.add_argument(
        "-T",
        "-table",
        dest="table_format",
        action="store_true",
        help="use ExifTool tabular output format without tag labels",
    )
    parser.add_argument(
        "-G",
        "-groupNames",
        "-groupnames",
        "--group-names",
        action="store_true",
        help="include group names in output projection",
    )
    parser.add_argument(
        "-G0",
        dest="group_name_families",
        action="append_const",
        const=0,
        default=[],
        help="include family 0 group names in output projection",
    )
    parser.add_argument(
        "-G1",
        dest="group_name_families",
        action="append_const",
        const=1,
        help="include family 1 group names in output projection",
    )
    parser.add_argument(
        "-G2",
        dest="group_name_families",
        action="append_const",
        const=2,
        help="include family 2 group names in output projection",
    )
    parser.add_argument(
        "-G4",
        dest="group_name_families",
        action="append_const",
        const=4,
        help="include family 4 duplicate-instance group names in output projection",
    )
    parser.add_argument(
        "-G0:1",
        dest="group_name_family_chains",
        action="append_const",
        const=(0, 1),
        default=[],
        help="include chained family 0 and 1 group names in output projection",
    )
    parser.add_argument(
        "-G0:2",
        dest="group_name_family_chains",
        action="append_const",
        const=(0, 2),
        help="include chained family 0 and 2 group names in output projection",
    )
    parser.add_argument(
        "-G1:2",
        dest="group_name_family_chains",
        action="append_const",
        const=(1, 2),
        help="include chained family 1 and 2 group names in output projection",
    )
    parser.add_argument(
        "-a",
        "-duplicates",
        "--allow-duplicates",
        action="store_true",
        help="allow duplicate tag names in output projection",
    )
    parser.add_argument(
        "--a",
        "--duplicates",
        dest="allow_duplicates",
        action="store_false",
        help="disable duplicate tag names in output projection",
    )
    parser.add_argument(
        "-s",
        "-s1",
        "-short",
        "-short1",
        "--short-names",
        dest="short_output_levels",
        action="append_const",
        const=1,
        default=[],
        help="use ExifTool short output with tag names instead of descriptions",
    )
    parser.add_argument(
        "-s2",
        "-short2",
        dest="short_output_levels",
        action="append_const",
        const=2,
        help="use ExifTool short output without alignment padding",
    )
    parser.add_argument(
        "-s3",
        "-short3",
        dest="short_output_levels",
        action="append_const",
        const=3,
        help="use ExifTool short output with values only",
    )
    parser.add_argument(
        "-S",
        "-veryShort",
        "-veryshort",
        "--very-short",
        "--veryShort",
        "--veryshort",
        action="store_true",
        help="use ExifTool very-short text output with no alignment padding",
    )
    parser.add_argument(
        "-sort",
        dest="sort_output",
        action="store_true",
        help="sort rendered tag output by current public output label",
    )
    parser.add_argument(
        "-n",
        "--printConv",
        "--printconv",
        dest="numeric_output",
        action="store_true",
        help="request ExifTool numeric/raw values; currently reports an explicit read-graph seam",
    )
    parser.add_argument(
        "-printConv",
        "-printconv",
        dest="numeric_output",
        action="store_false",
        help="request ExifTool print-converted values after a previous numeric-output request",
    )
    parser.add_argument(
        "-b",
        "-binary",
        dest="binary_output",
        action="store_true",
        help=(
            "request ExifTool-style binary output; currently returns an explicit "
            "unsupported diagnostic until native binary payloads are exposed"
        ),
    )
    parser.add_argument(
        "--b",
        "--binary",
        dest="suppress_binary_tags",
        action="store_true",
        help=(
            "suppress binary tag values in rendered metadata output, distinct from "
            "-b binary extraction"
        ),
    )
    parser.add_argument(
        "-u",
        "-unknown",
        "-Unknown",
        "-UNKNOWN",
        "-U",
        "-unknown2",
        "-Unknown2",
        "-UNKNOWN2",
        dest="unknown_tag_options",
        action=PublicUnknownTagAction,
        nargs=0,
        default=PublicUnknownTagOptions(),
        help="include ExifTool-compatible unknown tags that are suppressed by default",
    )
    parser.add_argument(
        "-api",
        "-API",
        dest="api_options",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=(
            "recognize ExifTool API read options; reports an explicit public read "
            "diagnostic for generic API effects that are not connected"
        ),
    )
    parser.add_argument(
        "-charset",
        dest="output_charset",
        action=_ReadCharsetAction,
        metavar="[[TYPE=]CHARSET]",
        default="UTF8",
        help="apply reviewed ExifTool output charset routing for public read rendering",
    )
    parser.add_argument(
        "-L",
        "-latin",
        dest="output_charset",
        action="store_const",
        const="Latin",
        help="use Windows Latin1/cp1252 output rendering like ExifTool -L",
    )
    parser.add_argument(
        "-lang",
        dest="read_language_code",
        action=_ReadLanguageAction,
        metavar="LANG",
        default="en",
        help="apply packaged ExifTool language translations to safe public read labels",
    )
    parser.add_argument(
        "-config",
        dest="deferred_read_options",
        action=_DeferredReadOptionAction,
        metavar="CFGFILE",
        help=(
            "recognize ExifTool Perl configuration files and report an explicit "
            "public blocker instead of loading code"
        ),
    )
    parser.add_argument(
        "-userParam",
        "-userparam",
        dest="deferred_read_options",
        action=_DeferredReadOptionAction,
        metavar="PARAM[[^]=[VAL]]",
        help=(
            "recognize ExifTool user parameters and report an explicit public interpolation blocker"
        ),
    )
    parser.add_argument(
        "-use",
        dest="use_modules",
        action="append",
        default=[],
        metavar="MODULE",
        help=(
            "recognize ExifTool Perl plug-in loading and report an explicit public "
            "blocker instead of loading arbitrary modules"
        ),
    )
    parser.add_argument(
        "-f",
        "-forcePrint",
        "-forceprint",
        dest="force_print",
        action="store_true",
        help="force printing of requested tags that are missing, using '-' by default",
    )
    parser.add_argument(
        "-m",
        "-ignoreMinorErrors",
        "-ignoreminorerrors",
        dest="ignore_minor_errors",
        action="store_true",
        help="ignore minor read/rendering errors where ExifTool would leave values empty",
    )
    parser.add_argument(
        "-v",
        "-verbose",
        dest="verbose_level",
        action="store_const",
        const=1,
        default=0,
        help="recognize ExifTool verbose diagnostic output and report a typed deferral",
    )
    parser.add_argument(
        "-v2",
        "-v3",
        "-v4",
        "-v5",
        dest="verbose_level",
        action=_VerboseLevelAction,
        nargs=0,
        help="recognize ExifTool numeric verbose diagnostic levels",
    )
    parser.add_argument(
        "-ee",
        "-extractEmbedded",
        "-extractembedded",
        dest="extract_embedded_level",
        action="store_const",
        const=1,
        default=0,
        help="recognize ExifTool embedded extraction and report a typed deferral",
    )
    parser.add_argument(
        "-ee2",
        "-ee3",
        dest="extract_embedded_level",
        action=_ExtractEmbeddedLevelAction,
        nargs=0,
        help="recognize ExifTool numeric embedded extraction levels",
    )
    parser.add_argument(
        "-scanForXMP",
        "-scanforxmp",
        dest="scan_for_xmp",
        action="store_true",
        help="recognize ExifTool brute-force XMP scanning and report a typed deferral",
    )
    parser.add_argument(
        "-w",
        "-w!",
        "-w+",
        "-w+!",
        "-w!+",
        "-textOut",
        "-textout",
        "-textOut!",
        "-textout!",
        "-textOut+",
        "-textout+",
        "-textOut+!",
        "-textout+!",
        "-textOut!+",
        "-textout!+",
        dest="output_file_routing",
        action=OutputFileRoutingAction,
        default=OutputFileRoutingRequest(),
        metavar="EXT_OR_FMT",
        help=(
            "parse ExifTool per-source output routing intent; external file creation "
            "is reported as deferred"
        ),
    )
    parser.add_argument(
        "-W",
        "-W!",
        "-W+",
        "-W+!",
        "-W!+",
        "-tagOut",
        "-tagout",
        "-tagOut!",
        "-tagout!",
        "-tagOut+",
        "-tagout+",
        "-tagOut+!",
        "-tagout+!",
        "-tagOut!+",
        "-tagout!+",
        dest="output_file_routing",
        action=OutputFileRoutingAction,
        metavar="FMT",
        help=(
            "parse ExifTool per-tag output routing intent; external file creation "
            "is reported as deferred"
        ),
    )
    parser.add_argument(
        "-Wext",
        "--Wext",
        "-tagOutExt",
        "-tagoutext",
        "--tagOutExt",
        "--tagoutext",
        dest="output_file_routing",
        action=OutputFileRoutingAction,
        metavar="EXT",
        help="parse ExifTool per-tag output extension filters for deferred routing",
    )
    parser.add_argument(
        "-o",
        "-out",
        dest="output_file_routing",
        action=OutputFileRoutingAction,
        metavar="OUTFILE",
        help="parse ExifTool write-output routing intent; execution remains deferred",
    )
    parser.add_argument(
        "-D",
        "-decimal",
        dest="xml_tag_id_format",
        action="store_const",
        const="decimal",
        default="none",
        help="include decimal tag IDs in XML output when tag provenance is populated",
    )
    parser.add_argument(
        "-H",
        "-hex",
        dest="xml_tag_id_format",
        action="store_const",
        const="hex",
        help="include hexadecimal tag IDs in XML output when tag provenance is populated",
    )
    parser.add_argument(
        "--xml-table-metadata",
        dest="xml_include_table_metadata",
        action="store_true",
        help="include tag table metadata in XML output when tag provenance is populated",
    )
    parser.add_argument(
        "-struct",
        "-structFormat",
        "-structformat",
        dest="structured_output",
        action="store_true",
        help="preserve source-backed structured XMP values in XML output",
    )
    parser.add_argument(
        "-csvDelim",
        "-csvdelim",
        "--csv-delim",
        default=",",
        type=parse_csv_delimiter,
        help="set delimiter for CSV output; rejects double quotes like ExifTool",
    )
    parser.add_argument(
        "-sep",
        "-separator",
        dest="list_separator",
        default=None,
        type=parse_exiftool_escaped_text,
        help="set list item separator for joined list values",
    )
    parser.add_argument(
        "-listItem",
        "-listitem",
        dest="list_item_index",
        default=None,
        type=int,
        help="extract a specific item from list values",
    )


if __name__ == "__main__":
    raise SystemExit(main())
