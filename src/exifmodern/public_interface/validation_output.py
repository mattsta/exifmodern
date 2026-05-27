"""Bounded ExifTool Validate pseudo-tag output for the public CLI."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from exifmodern.exiftool_compat.validate_plan import build_validate_plan
from exifmodern.public_api.models import MetadataReadRecord, MetadataReadRequest, MetadataReadResult
from exifmodern.public_api.rendering import render_record_output, render_records_json, text_value
from exifmodern.renderer import JsonRecord

_NO_EXIF_APP1_DIAGNOSTIC_PREFIX = "No JPEG EXIF APP1 segment found:"
_COUNT_SUFFIX_RE = re.compile(r" \[x([1-9][0-9]*)\]$")


def read_result_with_bounded_validate_output(
    read_result: MetadataReadResult,
    *,
    read_metadata_for_counts: Callable[[MetadataReadRequest], MetadataReadResult] | None = None,
) -> MetadataReadResult:
    """Emit bounded Validate output from existing source-backed pseudo-tags."""

    if not _validate_tag_requested(read_result.request.tags):
        return read_result
    if not read_result.records:
        return read_result
    pseudo_tag_records = read_result.records
    if read_metadata_for_counts is not None and not _warning_or_error_tag_requested(
        read_result.request.tags
    ):
        pseudo_tag_result = read_metadata_for_counts(_pseudo_tag_count_request(read_result.request))
        pseudo_tag_records = pseudo_tag_result.records
    if _records_have_warning_or_error(pseudo_tag_records):
        return _read_result_with_existing_pseudo_tag_validate(
            read_result,
            pseudo_tag_records,
        )
    if not _all_records_are_no_exif_jpegs(read_result):
        return read_result

    plan = build_validate_plan("JPEG", allow_output_emission=True)
    validate_value = (
        plan.summary.validate_value if read_result.request.render.numeric_output else "OK"
    )
    validate_key = (
        "ExifTool:Validate" if read_result.request.render.include_group_names else "Validate"
    )
    records = tuple(
        _record_with_validate_value(record, validate_key, validate_value, read_result)
        for record in read_result.records
    )
    diagnostics = tuple(
        diagnostic
        for diagnostic in read_result.diagnostics
        if diagnostic.code != "requested_tag_not_rendered"
        and not _is_no_exif_app1_read_graph_diagnostic(diagnostic.code, diagnostic.message)
        and not (
            diagnostic.code == "numeric_output_not_connected"
            and _only_validate_tag_requested(read_result.request.tags)
        )
    )
    rendered_text = _render_validate_records(records, read_result)
    return replace(
        read_result,
        status="ok",
        diagnostics=diagnostics,
        records=records,
        rendered_text=rendered_text,
    )


def _read_result_with_existing_pseudo_tag_validate(
    read_result: MetadataReadResult,
    pseudo_tag_records: tuple[MetadataReadRecord, ...],
) -> MetadataReadResult:
    validate_key = (
        "ExifTool:Validate" if read_result.request.render.include_group_names else "Validate"
    )
    counts_by_source = {
        record.path.as_posix(): _validate_counts_for_record(record) for record in pseudo_tag_records
    }
    records = tuple(
        _record_with_validate_value(
            record,
            validate_key,
            _render_validate_count(
                counts_by_source.get(record.path.as_posix(), (0, 0, 0)),
                numeric_output=read_result.request.render.numeric_output,
            ),
            read_result,
        )
        for record in read_result.records
    )
    diagnostics = tuple(
        diagnostic
        for diagnostic in read_result.diagnostics
        if diagnostic.code != "requested_tag_not_rendered"
        and not (
            diagnostic.code == "numeric_output_not_connected"
            and _only_validate_tag_requested(read_result.request.tags)
        )
    )
    rendered_text = _render_validate_records(records, read_result)
    return replace(
        read_result,
        status="ok" if not diagnostics else read_result.status,
        diagnostics=diagnostics,
        records=records,
        rendered_text=rendered_text,
    )


def _validate_tag_requested(tags: tuple[str, ...]) -> bool:
    return any(_tag_name_part(tag).lower() == "validate" for tag in tags)


def _warning_or_error_tag_requested(tags: tuple[str, ...]) -> bool:
    return any(_tag_base_name(_tag_name_part(tag)).lower() in {"warning", "error"} for tag in tags)


def _only_validate_tag_requested(tags: tuple[str, ...]) -> bool:
    return bool(tags) and all(_tag_name_part(tag).lower() == "validate" for tag in tags)


def _tag_name_part(tag: str) -> str:
    return tag.removeprefix("-").removesuffix("#").rsplit(":", 1)[-1]


def _tag_base_name(tag_name: str) -> str:
    return tag_name.split(" (", 1)[0]


def _pseudo_tag_count_request(request: MetadataReadRequest) -> MetadataReadRequest:
    tags = tuple(tag for tag in request.tags if _tag_name_part(tag).lower() != "validate")
    return replace(request, tags=(*tags, "Warning", "Error"))


def _records_have_warning_or_error(records: tuple[MetadataReadRecord, ...]) -> bool:
    return any(_record_has_warning_or_error(record) for record in records)


def _record_has_warning_or_error(record: MetadataReadRecord) -> bool:
    return any(_pseudo_tag_kind(key) is not None for key in record.values)


def _validate_counts_for_record(record: MetadataReadRecord) -> tuple[int, int, int]:
    error_count = 0
    warning_count = 0
    minor_warning_count = 0
    for key, value in record.values.items():
        tag_kind = _pseudo_tag_kind(key)
        if tag_kind is None:
            continue
        rendered = text_value(value)
        count = _pseudo_tag_occurrence_count(rendered)
        if tag_kind == "error":
            error_count += count
            continue
        warning_count += count
        if rendered.lower().startswith("[minor]"):
            minor_warning_count += count
    return error_count, warning_count, minor_warning_count


def _pseudo_tag_kind(key: str) -> str | None:
    name = _tag_base_name(_tag_name_part(key)).lower()
    if name in {"warning", "error"}:
        return name
    return None


def _pseudo_tag_occurrence_count(rendered: str) -> int:
    match = _COUNT_SUFFIX_RE.search(rendered)
    if match is None:
        return 1
    return int(match.group(1))


def _render_validate_count(
    counts: tuple[int, int, int],
    *,
    numeric_output: bool,
) -> str:
    if numeric_output:
        return f"{counts[0]} {counts[1]} {counts[2]}"
    if counts == (0, 0, 0):
        return "OK"
    parts: list[str] = []
    if counts[0]:
        parts.append(_plural_count(counts[0], "Error"))
    if counts[1]:
        warning = _plural_count(counts[1], "Warning")
        if counts[2]:
            if counts[1] == counts[2]:
                minor_text = "" if counts[1] == 1 else "all "
            else:
                minor_text = f"{counts[2]} "
            warning = f"{warning} ({minor_text}minor)"
        parts.append(warning)
    return " and ".join(parts)


def _plural_count(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


def _all_records_are_no_exif_jpegs(read_result: MetadataReadResult) -> bool:
    paths = {record.path.as_posix() for record in read_result.records}
    no_exif_paths = {
        diagnostic.message.split(_NO_EXIF_APP1_DIAGNOSTIC_PREFIX, 1)[1].strip()
        for diagnostic in read_result.diagnostics
        if diagnostic.code == "read_graph_diagnostic"
        and _NO_EXIF_APP1_DIAGNOSTIC_PREFIX in diagnostic.message
    }
    return paths <= no_exif_paths


def _is_no_exif_app1_read_graph_diagnostic(code: str, message: str) -> bool:
    return code == "read_graph_diagnostic" and _NO_EXIF_APP1_DIAGNOSTIC_PREFIX in message


def _record_with_validate_value(
    record: MetadataReadRecord,
    validate_key: str,
    validate_value: str,
    read_result: MetadataReadResult,
) -> MetadataReadRecord:
    values: JsonRecord = {"SourceFile": record.values["SourceFile"], validate_key: validate_value}
    return replace(
        record,
        values=values,
        rendered_text=render_record_output(values, read_result.request.render),
    )


def _render_validate_records(
    records: tuple[MetadataReadRecord, ...],
    read_result: MetadataReadResult,
) -> str:
    record_list = list(records)
    if read_result.request.render.format == "json":
        return render_records_json(record_list, read_result.request.render).decode("utf-8")
    return "".join(
        render_record_output(record.values, read_result.request.render) for record in record_list
    )
