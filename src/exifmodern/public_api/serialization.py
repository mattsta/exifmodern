"""Package-local JSON serialization helpers for public API models."""

from __future__ import annotations

from base64 import b64encode
from dataclasses import replace
from pathlib import Path

from exifmodern.json_types import JsonArray, JsonObject, JsonValue
from exifmodern.public_api.models import (
    CapabilityQueryResult,
    Diagnostic,
    ExifSidecarCopyFromFileRequest,
    FileInspectResult,
    MetadataReadResult,
    MetadataWriteOperationSummary,
    MetadataWritePlan,
    MetadataWriteRequest,
    MetadataWriteResult,
    MetadataWriteTagReference,
    OutputFileRoutingRequest,
    OutputPerSourceFileRouting,
    OutputPerTagFileRouting,
    OutputRenderRequest,
    OutputWriteFileRouting,
    PngChunkWriteRequest,
    PublicCopyFromFileRequest,
    PublicGeolocationListResult,
    PublicImportWriteRequest,
    PublicReadAlternateFile,
    PublicReadCondition,
    PublicReadFileOrder,
    PublicReadTagExclusion,
    PublicTagLookupResult,
    PublicWriteTargetKind,
    RiffWavMetadataWriteRequest,
    RiffWebpMetadataWriteRequest,
    TagLookupCapabilitySummary,
    XmlNamespaceBinding,
    XmlStructField,
    XmlStructListItem,
    XmlTagElement,
    XmpSidecarCopyFromFileRequest,
    _exif_sidecar_copy_route_tag,
    _public_read_tag_selector_to_json_value,
    _xmp_sidecar_copy_route_tag,
    parse_public_read_tag_selector,
)
from exifmodern.public_interface.user_params import PublicUserParam
from exifmodern.read_graph import BinaryTagListValue, BinaryTagValue, TagValue
from exifmodern.renderer import JsonRecord
from exifmodern.services.tag_lookup_runtime import (
    TagLookupRuntimeCandidate,
    TagLookupRuntimeCapability,
    TagLookupRuntimeResult,
    TagLookupSelectionResult,
)


def metadata_read_result_to_json_value(
    result: MetadataReadResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    return {
        "status": result.status,
        "operation": "read",
        "paths": _path_values(result.request.paths),
        "tags": list(result.request.tags),
        "tag_exclusions": [
            _public_read_tag_exclusion_to_json_value(exclusion)
            for exclusion in result.request.tag_exclusions
        ],
        "recursive": result.request.recursive,
        "recurse_dot_directories": result.request.recurse_dot_directories,
        "ignore_directories": list(result.request.ignore_directories),
        "fast_scan_level": result.request.fast_scan_level,
        "extension_filters": [
            {"extension": extension_filter.extension, "mode": extension_filter.mode}
            for extension_filter in result.request.extension_filters
        ],
        "conditions": [
            _public_read_condition_to_json_value(condition)
            for condition in result.request.conditions
        ],
        "file_order": [
            _public_read_file_order_to_json_value(order) for order in result.request.file_order
        ],
        "alternate_files": [
            _public_read_alternate_file_to_json_value(alternate)
            for alternate in result.request.alternate_files
        ],
        "user_params": [
            _public_user_param_to_json_value(user_param)
            for user_param in result.request.user_params
        ],
        "render": output_render_request_to_json_value(result.request.render),
        "records": [
            {
                "path": str(record.path),
                "values": _json_record_value(record.values),
                "rendered_text": record.rendered_text,
                "rendered_binary": _binary_output_json_value(record.rendered_binary),
                "xml_namespaces": [
                    _xml_namespace_binding_to_json_value(namespace)
                    for namespace in record.xml_namespaces
                ],
                "xml_elements": [
                    _xml_tag_element_to_json_value(element) for element in record.xml_elements
                ],
            }
            for record in result.records
        ],
        "rendered_text": result.rendered_text,
        "rendered_binary": _binary_output_json_value(result.rendered_binary),
        "condition_failed_count": result.condition_failed_count,
        "output_files": [
            {
                "source_path": output_file.source_path.as_posix(),
                "output_path": output_file.output_path.as_posix(),
                "bytes_written": output_file.bytes_written,
                "replaced_existing": output_file.replaced_existing,
                "routing_kind": output_file.routing_kind,
            }
            for output_file in result.output_files
        ],
        "diagnostics": _diagnostic_values(
            result.diagnostics,
            include_evidence_ids=include_evidence_ids,
        ),
    }


def _public_read_tag_exclusion_to_json_value(exclusion: PublicReadTagExclusion) -> JsonObject:
    selector = parse_public_read_tag_selector(exclusion.raw)
    return {
        "raw": exclusion.raw,
        "selector": _public_read_tag_selector_to_json_value(selector),
    }


def _public_read_condition_to_json_value(condition: PublicReadCondition) -> JsonObject:
    return {
        "raw_option": condition.raw_option,
        "expression": condition.expression,
        "pass_number": condition.pass_number,
    }


def _public_read_file_order_to_json_value(order: PublicReadFileOrder) -> JsonObject:
    return {
        "raw_option": order.raw_option,
        "tag": order.tag,
        "fast_pass": order.fast_pass,
    }


def _public_user_param_to_json_value(user_param: PublicUserParam) -> JsonObject:
    return {
        "raw_argument": user_param.raw_argument,
        "name": user_param.name,
        "value": user_param.value,
        "extracted": user_param.extracted,
    }


def _public_read_alternate_file_to_json_value(alternate: PublicReadAlternateFile) -> JsonObject:
    return {
        "raw_option": alternate.raw_option,
        "path": alternate.path.as_posix(),
        "slot": alternate.slot,
    }


def metadata_write_plan_to_json_value(
    plan: MetadataWritePlan,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    return {
        "status": plan.status,
        "operation": "write-plan",
        "paths": _path_values(plan.request.paths),
        "parsed_operations": _metadata_write_operation_summary_values(plan.request),
        "assignments": [
            {"tag": assignment.tag, "value": assignment.value}
            for assignment in plan.request.assignments
        ],
        "deletes": list(plan.request.deletes),
        "xmp_sidecar_copy_from_file": _xmp_sidecar_copy_from_file_request_to_json_value(
            plan.request.xmp_sidecar_copy_from_file
        ),
        "exif_sidecar_copy_from_file": _exif_sidecar_copy_from_file_request_to_json_value(
            plan.request.exif_sidecar_copy_from_file
        ),
        "public_copy_from_file": _public_copy_from_file_request_to_json_value(
            plan.request.public_copy_from_file
        ),
        "png_chunk_write": _png_chunk_write_request_to_json_value(plan.request.png_chunk_write),
        "riff_wav_metadata_write": _riff_wav_metadata_write_request_to_json_value(
            plan.request.riff_wav_metadata_write
        ),
        "riff_webp_metadata_write": _riff_webp_metadata_write_request_to_json_value(
            plan.request.riff_webp_metadata_write
        ),
        "import_write": _public_import_write_request_to_json_value(plan.request.import_write),
        "policy": plan.request.policy,
        "preserve_file_times": plan.request.preserve_file_times,
        "write_output_file": _output_write_file_routing_to_json_value(
            plan.request.write_output_file
        ),
        "list_separator": plan.request.list_separator,
        "tag_lookup_package_path": (
            None
            if plan.request.tag_lookup_package_path is None
            else str(plan.request.tag_lookup_package_path)
        ),
        "diagnostics": _diagnostic_values(
            plan.diagnostics,
            include_evidence_ids=include_evidence_ids,
        ),
    }


def metadata_write_result_to_json_value(
    result: MetadataWriteResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    return {
        "status": result.status,
        "operation": "write",
        "paths": _path_values(result.request.paths),
        "parsed_operations": _metadata_write_operation_summary_values(result.request),
        "assignments": [
            {"tag": assignment.tag, "value": assignment.value}
            for assignment in result.request.assignments
        ],
        "deletes": list(result.request.deletes),
        "xmp_sidecar_copy_from_file": _xmp_sidecar_copy_from_file_request_to_json_value(
            result.request.xmp_sidecar_copy_from_file
        ),
        "exif_sidecar_copy_from_file": _exif_sidecar_copy_from_file_request_to_json_value(
            result.request.exif_sidecar_copy_from_file
        ),
        "public_copy_from_file": _public_copy_from_file_request_to_json_value(
            result.request.public_copy_from_file
        ),
        "png_chunk_write": _png_chunk_write_request_to_json_value(result.request.png_chunk_write),
        "riff_wav_metadata_write": _riff_wav_metadata_write_request_to_json_value(
            result.request.riff_wav_metadata_write
        ),
        "riff_webp_metadata_write": _riff_webp_metadata_write_request_to_json_value(
            result.request.riff_webp_metadata_write
        ),
        "import_write": _public_import_write_request_to_json_value(result.request.import_write),
        "policy": result.request.policy,
        "preserve_file_times": result.request.preserve_file_times,
        "write_output_file": _output_write_file_routing_to_json_value(
            result.request.write_output_file
        ),
        "list_separator": result.request.list_separator,
        "tag_lookup_package_path": (
            None
            if result.request.tag_lookup_package_path is None
            else str(result.request.tag_lookup_package_path)
        ),
        "changed_paths": _path_values(result.changed_paths),
        "diagnostics": _diagnostic_values(
            result.diagnostics,
            include_evidence_ids=include_evidence_ids,
        ),
    }


def _metadata_write_operation_summary_values(request: MetadataWriteRequest) -> JsonArray:
    values: JsonArray = []
    for assignment in request.assignments:
        values.append(
            _metadata_write_operation_summary_to_json_value(
                MetadataWriteOperationSummary(
                    operation="assignment",
                    target=_metadata_write_tag_reference(assignment.tag),
                    value=assignment.value,
                )
            )
        )
    for delete in request.deletes:
        values.append(
            _metadata_write_operation_summary_to_json_value(
                MetadataWriteOperationSummary(
                    operation="delete",
                    target=_metadata_write_delete_reference(delete),
                )
            )
        )
    if request.xmp_sidecar_copy_from_file is not None:
        for xmp_route in request.xmp_sidecar_copy_from_file.routes:
            values.append(
                _metadata_write_operation_summary_to_json_value(
                    MetadataWriteOperationSummary(
                        operation="copy_from_file",
                        target=_metadata_write_tag_reference(
                            _xmp_sidecar_copy_route_tag(xmp_route)
                        ),
                        value=request.xmp_sidecar_copy_from_file.source_path.as_posix(),
                    )
                )
            )
    if request.exif_sidecar_copy_from_file is not None:
        for exif_route in request.exif_sidecar_copy_from_file.routes:
            values.append(
                _metadata_write_operation_summary_to_json_value(
                    MetadataWriteOperationSummary(
                        operation="copy_from_file",
                        target=_metadata_write_tag_reference(
                            _exif_sidecar_copy_route_tag(exif_route)
                        ),
                        value=request.exif_sidecar_copy_from_file.source_path.as_posix(),
                    )
                )
            )
    if request.public_copy_from_file is not None:
        for route in request.public_copy_from_file.routes:
            values.append(
                _metadata_write_operation_summary_to_json_value(
                    MetadataWriteOperationSummary(
                        operation="copy_from_file",
                        target=_metadata_write_tag_reference(route.raw),
                        value=request.public_copy_from_file.source,
                    )
                )
            )
    if request.import_write is not None:
        values.append(
            {
                "operation": "import_write",
                "target": {
                    "raw": request.import_write.path.as_posix(),
                    "tag_name": request.import_write.import_format,
                    "group_chain": [],
                    "target_kind": "tag",
                },
                "value": "+=" if request.import_write.add_list_items else "=",
            }
        )
    return values


def _metadata_write_operation_summary_to_json_value(
    operation: MetadataWriteOperationSummary,
) -> JsonObject:
    return {
        "operation": operation.operation,
        "target": _metadata_write_tag_reference_to_json_value(operation.target),
        "value": operation.value,
    }


def _metadata_write_tag_reference_to_json_value(reference: MetadataWriteTagReference) -> JsonObject:
    return {
        "raw": reference.raw,
        "group_chain": list(reference.group_chain),
        "tag_name": reference.tag_name,
        "target_kind": reference.target_kind,
        "group_qualified": bool(reference.group_chain),
    }


def _metadata_write_tag_reference(raw: str) -> MetadataWriteTagReference:
    parts = tuple(part for part in raw.split(":") if part)
    if not parts:
        return MetadataWriteTagReference(raw=raw, tag_name="", target_kind="all")
    tag_name = parts[-1]
    target_kind: PublicWriteTargetKind = "all" if tag_name.lower() in {"*", "all"} else "tag"
    return MetadataWriteTagReference(
        raw=raw,
        group_chain=parts[:-1],
        tag_name=tag_name,
        target_kind=target_kind,
    )


def _metadata_write_delete_reference(raw: str) -> MetadataWriteTagReference:
    reference = _metadata_write_tag_reference(raw.removesuffix("="))
    if reference.group_chain and reference.target_kind == "all":
        return replace(reference, target_kind="group")
    if reference.target_kind != "tag":
        return reference
    if reference.group_chain:
        return reference
    return replace(reference, target_kind="tag")


def _png_chunk_write_request_to_json_value(
    request: PngChunkWriteRequest | None,
) -> JsonObject | None:
    if request is None:
        return None
    return {
        "text_chunks": [
            {
                "keyword": text_chunk.keyword,
                "value": _binary_output_json_value(text_chunk.value),
                "language_code": text_chunk.language_code,
                "force_itxt": text_chunk.force_itxt,
                "compress": text_chunk.compress,
            }
            for text_chunk in request.text_chunks
        ],
        "xmp_payload": _optional_binary_output_json_value(request.xmp_payload),
        "exif_payload": _optional_binary_output_json_value(request.exif_payload),
        "icc_payload": _optional_binary_output_json_value(request.icc_payload),
        "icc_profile_name": request.icc_profile_name,
        "pixels_per_unit_x": request.pixels_per_unit_x,
        "pixels_per_unit_y": request.pixels_per_unit_y,
        "pixel_units": request.pixel_units,
        "delete_metadata_groups": list(request.delete_metadata_groups),
        "delete_all_metadata": request.delete_all_metadata,
    }


def _riff_wav_metadata_write_request_to_json_value(
    request: RiffWavMetadataWriteRequest | None,
) -> JsonObject | None:
    if request is None:
        return None
    return {
        "delete_all_modeled_metadata": request.delete_all_modeled_metadata,
    }


def _riff_webp_metadata_write_request_to_json_value(
    request: RiffWebpMetadataWriteRequest | None,
) -> JsonObject | None:
    if request is None:
        return None
    return {
        "delete_all_metadata": request.delete_all_metadata,
    }


def _public_import_write_request_to_json_value(
    request: PublicImportWriteRequest | None,
) -> JsonObject | None:
    if request is None:
        return None
    return {
        "import_format": request.import_format,
        "path": request.path.as_posix(),
        "add_list_items": request.add_list_items,
    }


def _optional_binary_output_json_value(value: bytes | None) -> JsonObject | None:
    if value is None:
        return None
    return _binary_output_json_value(value)


def _xmp_sidecar_copy_from_file_request_to_json_value(
    request: XmpSidecarCopyFromFileRequest | None,
) -> JsonObject | None:
    if request is None:
        return None
    return {
        "source_path": str(request.source_path),
        "routes": [
            {
                "source_group": route.source_group,
                "destination_group": route.destination_group,
                "tag_pattern": route.tag_pattern,
            }
            for route in request.routes
        ],
    }


def _exif_sidecar_copy_from_file_request_to_json_value(
    request: ExifSidecarCopyFromFileRequest | None,
) -> JsonObject | None:
    if request is None:
        return None
    return {
        "source_path": str(request.source_path),
        "routes": [
            {
                "source_group": route.source_group,
                "tag_pattern": route.tag_pattern,
            }
            for route in request.routes
        ],
    }


def _public_copy_from_file_request_to_json_value(
    request: PublicCopyFromFileRequest | None,
) -> JsonObject | None:
    if request is None:
        return None
    return {
        "source": request.source,
        "source_kind": request.source_kind,
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
    }


def output_render_request_to_json_value(request: OutputRenderRequest) -> JsonObject:
    value: JsonObject = {
        "format": request.format,
        "include_group_names": request.include_group_names,
        "include_unknown_tags": request.include_unknown_tags,
        "allow_duplicate_tags": request.allow_duplicate_tags,
        "group_name_families": list(request.group_name_families),
        "short_tag_names": request.short_tag_names,
        "very_short_output": request.very_short_output,
        "sort_output": request.sort_output,
        "numeric_output": request.numeric_output,
        "csv_delimiter": request.csv_delimiter,
        "list_separator": request.list_separator,
        "join_list_values": request.join_list_values,
        "binary_output": request.binary_output,
        "output_file_routing": output_file_routing_request_to_json_value(
            request.output_file_routing
        ),
        "xml_tag_id_format": request.xml_tag_id_format,
        "xml_include_table_metadata": request.xml_include_table_metadata,
        "structured_output": request.structured_output,
        "list_item_index": request.list_item_index,
        "missing_tag_value": request.missing_tag_value,
        "verbose_level": request.verbose_level,
        "extract_embedded_level": request.extract_embedded_level,
        "scan_for_xmp": request.scan_for_xmp,
        "output_filter": request.output_filter,
        "output_charset": request.output_charset,
        "language_code": request.language_code,
        "print_format_templates": [
            {
                "source_kind": template.source_kind,
                "raw_argument": template.raw_argument,
                "line_count": len(template.lines),
                "append_inline_newline": template.append_inline_newline,
            }
            for template in request.print_format_templates
        ],
    }
    if request.suppress_binary_tags:
        value["suppress_binary_tags"] = True
    return value


def output_file_routing_request_to_json_value(request: OutputFileRoutingRequest) -> JsonObject:
    return {
        "stdout_binary": request.stdout_binary,
        "unsafe_binary_policy": request.unsafe_binary_policy,
        "per_source_file": _output_per_source_file_routing_to_json_value(request.per_source_file),
        "per_tag_file": _output_per_tag_file_routing_to_json_value(request.per_tag_file),
        "write_output_file": _output_write_file_routing_to_json_value(request.write_output_file),
    }


def _output_per_source_file_routing_to_json_value(
    request: OutputPerSourceFileRouting | None,
) -> JsonObject | None:
    if request is None:
        return None
    return {
        "format_template": request.format_template,
        "overwrite_policy": request.overwrite_policy,
    }


def _output_per_tag_file_routing_to_json_value(
    request: OutputPerTagFileRouting | None,
) -> JsonObject | None:
    if request is None:
        return None
    return {
        "format_template": request.format_template,
        "overwrite_policy": request.overwrite_policy,
        "extension_filters": [
            {"extension": extension_filter.extension, "mode": extension_filter.mode}
            for extension_filter in request.extension_filters
        ],
    }


def _output_write_file_routing_to_json_value(
    request: OutputWriteFileRouting | None,
) -> JsonObject | None:
    if request is None:
        return None
    return {
        "output_path_template": request.output_path_template,
        "overwrite_policy": request.overwrite_policy,
        "stdout": request.stdout,
    }


def file_inspect_result_to_json_value(
    result: FileInspectResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    return {
        "status": result.status,
        "operation": "inspect",
        "paths": _path_values(result.request.paths),
        "records": [
            {
                "path": str(record.path),
                "file_type": record.file_type,
                "values": _json_record_value(record.values),
                "structure": record.structure,
            }
            for record in result.records
        ],
        "diagnostics": _diagnostic_values(
            result.diagnostics,
            include_evidence_ids=include_evidence_ids,
        ),
    }


def capability_query_result_to_json_value(
    result: CapabilityQueryResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    return {
        "status": result.status,
        "operation": "capabilities",
        "include_experimental": result.request.include_experimental,
        "tag_lookup_request": {
            "package_path": (
                None
                if result.request.tag_lookup_package_path is None
                else str(result.request.tag_lookup_package_path)
            ),
            "tag_names": list(result.request.tag_names),
            "writable_tag_names": list(result.request.writable_tag_names),
        },
        "tag_lookup_summary": tag_lookup_capability_summary_to_json_value(
            result.tag_lookup_summary,
            include_evidence_ids=include_evidence_ids,
        ),
        "tag_lookup_capabilities": [
            tag_lookup_runtime_capability_to_json_value(capability)
            for capability in result.tag_lookup_capabilities
        ],
        "tag_lookup_writable_selections": [
            tag_lookup_selection_result_to_json_value(selection)
            for selection in result.tag_lookup_writable_selections
        ],
        "capabilities": [
            {
                "name": capability.name,
                "status": capability.status,
                "summary": capability.summary,
                "surfaces": [
                    {
                        "name": surface.name,
                        "status": surface.status,
                        "summary": surface.summary,
                    }
                    for surface in capability.surfaces
                ],
            }
            for capability in result.capabilities
        ],
        "diagnostics": _diagnostic_values(
            result.diagnostics,
            include_evidence_ids=include_evidence_ids,
        ),
    }


def tag_lookup_capability_summary_to_json_value(
    summary: TagLookupCapabilitySummary | None,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject | None:
    if summary is None:
        return None
    value: JsonObject = {
        "package_path": str(summary.package_path),
        "package_loaded": summary.package_loaded,
        "table_count": summary.table_count,
        "lookup_tag_count": summary.lookup_tag_count,
        "tag_exists_count": summary.tag_exists_count,
        "composite_module_count": summary.composite_module_count,
        "queried_tag_count": summary.queried_tag_count,
        "wildcard_query_count": summary.wildcard_query_count,
        "resolved_tag_count": summary.resolved_tag_count,
        "exists_only_tag_count": summary.exists_only_tag_count,
        "missing_tag_count": summary.missing_tag_count,
        "writable_candidate_count": summary.writable_candidate_count,
        "writable_selection_count": summary.writable_selection_count,
        "writable_resolved_count": summary.writable_resolved_count,
        "writable_ambiguous_count": summary.writable_ambiguous_count,
        "writable_blocked_count": summary.writable_blocked_count,
        "writable_not_found_count": summary.writable_not_found_count,
    }
    if include_evidence_ids:
        value["evidence_ids"] = list(summary.evidence_ids)
    return value


def public_geolocation_list_result_to_json_value(
    result: PublicGeolocationListResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    return {
        "status": result.status,
        "operation": "listgeo",
        "package_path": str(result.request.package_path),
        "language_code": result.request.language_code,
        "include_alternate_names": result.request.include_alternate_names,
        "sort_by_city": result.request.sort_by_city,
        "sort_mode": result.request.sort_mode,
        "min_population": result.request.min_population,
        "feature_option": result.request.feature_option,
        "include_header": result.request.include_header,
        "include_title": result.request.include_title,
        "alternate_names_column_available": result.alternate_names_column_available,
        "rows": [
            {
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
                "alternate_names": row.alternate_names,
            }
            for row in result.rows
        ],
        "rendered_text": result.rendered_text,
        "diagnostics": _diagnostic_values(
            result.diagnostics,
            include_evidence_ids=include_evidence_ids,
        ),
    }


def public_tag_lookup_result_to_json_value(
    result: PublicTagLookupResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    return {
        "status": result.status,
        "operation": "tag-lookup",
        "package_path": str(result.request.package_path),
        "tag_names": list(result.request.tag_names),
        "writable_tag_names": list(result.request.writable_tag_names),
        "tag_lookup_summary": tag_lookup_capability_summary_to_json_value(
            result.summary,
            include_evidence_ids=include_evidence_ids,
        ),
        "tag_lookup_results": [
            tag_lookup_runtime_result_to_json_value(
                tag_result,
                include_evidence_ids=include_evidence_ids,
            )
            for tag_result in result.tag_results
        ],
        "tag_lookup_writable_selections": [
            tag_lookup_selection_result_to_json_value(
                selection,
                include_evidence_ids=include_evidence_ids,
            )
            for selection in result.writable_selections
        ],
        "diagnostics": _diagnostic_values(
            result.diagnostics,
            include_evidence_ids=include_evidence_ids,
        ),
    }


def tag_lookup_runtime_result_to_json_value(
    result: TagLookupRuntimeResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    value: JsonObject = {
        "tag_name": result.request.tag_name,
        "lookup_key": result.lookup_key,
        "status": result.status,
        "resolved": result.resolved,
        "exists": result.exists,
        "exists_only": result.exists_only,
        "wildcard": result.wildcard,
        "matched_tag_names": list(result.matched_tag_names),
        "composite_module": result.composite_module,
        "candidates": [
            tag_lookup_runtime_candidate_to_json_value(candidate) for candidate in result.candidates
        ],
    }
    if include_evidence_ids:
        value["evidence_ids"] = list(result.source_reference_ids)
    return value


def tag_lookup_runtime_capability_to_json_value(
    capability: TagLookupRuntimeCapability,
) -> JsonObject:
    return {
        "tag_name": capability.tag_name,
        "status": capability.status,
        "exists": capability.exists,
        "writable": capability.writable,
        "wildcard": capability.wildcard,
        "matched_tag_names": list(capability.matched_tag_names),
        "candidate_count": capability.candidate_count,
        "composite_module": capability.composite_module,
        "candidates": [
            {
                "tag_name": candidate.tag_name,
                "table_number": candidate.table_number,
                "table_name": candidate.table_name,
                "tag_ids": list(candidate.tag_ids),
                "flattened_root_tag_id": candidate.flattened_root_tag_id,
            }
            for candidate in capability.candidates
        ],
    }


def tag_lookup_selection_result_to_json_value(
    selection: TagLookupSelectionResult,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    value: JsonObject = {
        "request": {
            "raw_name": selection.request.raw_name,
            "group_name": selection.request.group_name,
            "tag_name": selection.request.tag_name,
            "lookup_key": selection.request.lookup_key,
        },
        "route": selection.route,
        "outcome": selection.outcome,
        "resolved": selection.resolved,
        "blocked": selection.blocked,
        "candidates": [
            tag_lookup_runtime_candidate_to_json_value(candidate)
            for candidate in selection.candidates
        ],
        "selected_candidates": [
            tag_lookup_runtime_candidate_to_json_value(candidate)
            for candidate in selection.selected_candidates
        ],
        "blockers": [
            {
                "code": blocker.code,
                "detail": blocker.detail,
            }
            for blocker in selection.blockers
        ],
    }
    if include_evidence_ids:
        value["evidence_ids"] = list(selection.source_reference_ids)
    return value


def tag_lookup_runtime_candidate_to_json_value(
    candidate: TagLookupRuntimeCandidate,
) -> JsonObject:
    return {
        "tag_name": candidate.tag_name,
        "table_number": candidate.table_number,
        "table_name": candidate.table_name,
        "tag_ids": list(candidate.tag_ids),
        "flattened_root_tag_id": candidate.flattened_root_tag_id,
    }


def _path_values(paths: tuple[Path, ...]) -> JsonArray:
    return [str(path) for path in paths]


def _diagnostic_values(
    diagnostics: tuple[Diagnostic, ...],
    *,
    include_evidence_ids: bool = False,
) -> JsonArray:
    return [
        diagnostic_to_json_value(
            diagnostic,
            include_evidence_ids=include_evidence_ids,
        )
        for diagnostic in diagnostics
    ]


def _json_record_value(record: JsonRecord) -> JsonObject:
    return {key: _json_tag_value(value) for key, value in record.items()}


def _xml_namespace_binding_to_json_value(namespace: XmlNamespaceBinding) -> JsonObject:
    return {
        "prefix": namespace.prefix,
        "uri_path": namespace.uri_path,
    }


def _xml_tag_element_to_json_value(element: XmlTagElement) -> JsonObject:
    value: JsonObject = {
        "group": element.group,
        "tag": element.tag,
        "value": _json_tag_value(element.value),
        "uri_path": element.uri_path,
        "et_id": element.et_id,
        "et_table": element.et_table,
        "list_container": element.list_container,
        "struct_fields": [
            _xml_struct_field_to_json_value(field) for field in element.struct_fields
        ],
    }
    if element.struct_list_items:
        value["struct_list_items"] = [
            _xml_struct_list_item_to_json_value(item) for item in element.struct_list_items
        ]
    return value


def _xml_struct_field_to_json_value(field: XmlStructField) -> JsonObject:
    value: JsonObject = {
        "group": field.group,
        "tag": field.tag,
        "value": _json_tag_value(field.value),
    }
    if field.uri_path is not None:
        value["uri_path"] = field.uri_path
    if field.struct_fields:
        value["struct_fields"] = [
            _xml_struct_field_to_json_value(nested_field) for nested_field in field.struct_fields
        ]
    return value


def _xml_struct_list_item_to_json_value(item: XmlStructListItem) -> JsonObject:
    return {
        "fields": [_xml_struct_field_to_json_value(field) for field in item.fields],
    }


def _json_tag_value(value: TagValue) -> JsonValue:
    if isinstance(value, BinaryTagListValue):
        return {
            "type": "binary_list",
            "byte_count": value.byte_count,
            "item_count": value.item_count,
            "items": [_binary_tag_value_json_value(item) for item in value.items],
        }
    if isinstance(value, BinaryTagValue):
        return _binary_tag_value_json_value(value)
    if isinstance(value, list):
        return [_json_tag_value(item) for item in value]
    return value


def _binary_tag_value_json_value(value: BinaryTagValue) -> JsonObject:
    return {
        "type": "binary",
        "byte_count": value.byte_count,
        "base64": b64encode(value.data).decode("ascii"),
        "media_type": value.media_type,
        "file_extension": value.file_extension,
    }


def _binary_output_json_value(value: bytes) -> JsonObject | None:
    if not value:
        return None
    return {
        "type": "binary",
        "byte_count": len(value),
        "base64": b64encode(value).decode("ascii"),
    }


def diagnostic_to_json_value(
    diagnostic: Diagnostic,
    *,
    include_evidence_ids: bool = False,
) -> JsonObject:
    value: JsonObject = {
        "code": diagnostic.code,
        "message": diagnostic.message,
    }
    if diagnostic.details is not None:
        value["details"] = (
            _json_value_with_evidence_ids(diagnostic.details)
            if include_evidence_ids
            else _json_value_without_evidence_ids(diagnostic.details)
        )
    return value


def _json_value_with_evidence_ids(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: _json_value_with_evidence_ids(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value_with_evidence_ids(item) for item in value]
    return value


def _json_value_without_evidence_ids(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _json_value_without_evidence_ids(item)
            for key, item in value.items()
            if key != "evidence_ids"
        }
    if isinstance(value, list):
        return [_json_value_without_evidence_ids(item) for item in value]
    return value
