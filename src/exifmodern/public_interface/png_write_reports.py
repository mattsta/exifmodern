"""Public CLI PNG write textout and readback report helpers."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.png.chunk_transaction_plan import (
    PngTextChunkRequest,
    build_png_chunk_transaction_plan,
)
from exifmodern.formats.png.textout_report import build_png_transaction_textout_report
from exifmodern.formats.png.textual_read_graph import build_png_textual_read_graph
from exifmodern.json_types import JsonArray, JsonObject, JsonValue
from exifmodern.public_api import (
    MetadataWriteRequest,
    MetadataWriteResult,
    metadata_write_result_to_json_value,
)
from exifmodern.public_api.models import PngTextChunkWriteRequest
from exifmodern.read_graph import BinaryTagListValue, BinaryTagValue, ReadTag


def metadata_write_result_to_json_value_with_cli_reports(
    write_result: MetadataWriteResult,
    *,
    png_textout_plan_reports: JsonArray,
) -> JsonObject:
    result = metadata_write_result_to_json_value(write_result)
    png_report = png_textout_readback_report_for_write_result(
        write_result,
        png_textout_plan_reports=png_textout_plan_reports,
    )
    if png_report is not None:
        result["png_textout_readback_report"] = png_report
    return result


def png_textout_plan_reports_for_write_request(request: MetadataWriteRequest) -> JsonArray:
    png_request = request.png_chunk_write
    if png_request is None:
        return []
    reports: JsonArray = []
    for path in request.paths:
        try:
            input_data = path.read_bytes()
            transaction_plan = build_png_chunk_transaction_plan(
                input_data,
                icc_payload=png_request.icc_payload,
                icc_profile_name=png_request.icc_profile_name,
                exif_payload=png_request.exif_payload,
                xmp_payload=png_request.xmp_payload,
                text_chunks=png_textout_text_chunk_requests(png_request.text_chunks),
                delete_metadata_groups=png_request.delete_metadata_groups,
                delete_all_metadata=png_request.delete_all_metadata,
                allow_output_emission=True,
            )
            textout_report = build_png_transaction_textout_report(
                transaction_plan,
                source_name=path.as_posix(),
                delete_groups=png_request.delete_metadata_groups,
            )
            reports.append(
                {
                    "can_emit_output": transaction_plan.can_emit_output,
                    "path": path.as_posix(),
                    "plan_status": transaction_plan.status,
                    "textout": textout_report.to_json(),
                    "transaction_gates": [
                        gate.to_json() for gate in transaction_plan.output_emission_gates
                    ],
                }
            )
        except OSError as exc:
            reports.append(
                {
                    "can_emit_output": False,
                    "path": path.as_posix(),
                    "plan_status": "unavailable",
                    "read_error": str(exc),
                    "textout": None,
                    "transaction_gates": [],
                }
            )
    return reports


def png_textout_text_chunk_requests(
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


def png_textout_readback_report_for_write_result(
    result: MetadataWriteResult,
    *,
    png_textout_plan_reports: JsonArray,
) -> JsonObject | None:
    if not png_textout_plan_reports:
        return None
    request = result.request
    if request.png_chunk_write is None:
        return None
    readbacks: JsonArray = []
    for path in request.paths:
        readbacks.append(png_textual_readback_summary(path))
    return {
        "native_readback_callable": (
            "exifmodern.formats.png.textual_read_graph.build_png_textual_read_graph"
        ),
        "package_local_textout_callable": (
            "exifmodern.formats.png.chunk_transaction_plan.build_png_transaction_textout_report"
        ),
        "plan_reports": png_textout_plan_reports,
        "readback_reports": readbacks,
        "status": "ready" if result.status == "ok" else "planned",
    }


def png_textual_readback_summary(path: Path) -> JsonObject:
    try:
        graph = build_png_textual_read_graph(path.read_bytes(), source_file=path.as_posix())
    except OSError as exc:
        return {
            "diagnostics": [],
            "native_readback_ready": False,
            "path": path.as_posix(),
            "read_error": str(exc),
            "tag_count": 0,
            "tags": [],
        }
    return {
        "diagnostics": list(graph.diagnostics),
        "native_readback_ready": True,
        "path": path.as_posix(),
        "tag_count": len(graph.tags),
        "tags": [png_readback_tag_summary(tag) for tag in graph.tags],
    }


def png_readback_tag_summary(tag: ReadTag) -> JsonObject:
    value = tag.value
    json_value: JsonValue
    if isinstance(value, BinaryTagValue):
        json_value = {
            "byte_count": value.byte_count,
            "type": "binary",
        }
    elif isinstance(value, BinaryTagListValue):
        json_value = {
            "byte_count": value.byte_count,
            "item_count": value.item_count,
            "type": "binary_list",
        }
    elif isinstance(value, list):
        json_value = [str(item) for item in value]
    else:
        json_value = value
    return {
        "group": tag.provenance.group,
        "name": tag.name,
        "source": tag.provenance.source,
        "table_name": tag.provenance.table_name,
        "value": json_value,
    }
