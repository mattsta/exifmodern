"""Bounded CSV/JSON import-write execution for public writes."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from exifmodern.exif_scalar_write_plan import build_exif_scalar_write_plan
from exifmodern.file_transaction import (
    BackupPolicy,
    copy_back_bytes_in_place_transactionally,
    write_bytes_in_place_transactionally,
)
from exifmodern.formats.iptc.write_plan import (
    IPTC_APPLICATION_TAG_SPECS,
    IptcApplicationWritePlan,
    text_step,
    upsert_text_step,
)
from exifmodern.formats.jpeg.app_segments.photoshop import read_iptc_tags
from exifmodern.formats.jpeg.app_segments.xmp import XMP_APP1_PREFIX
from exifmodern.formats.jpeg.container import read_jpeg_segment_probes
from exifmodern.formats.jpeg.exif_scalar_writer import rewrite_jpeg_file_exif_scalars_in_place
from exifmodern.formats.jpeg.iptc_app13_writer import (
    rewrite_jpeg_iptc_application_creating_if_needed,
)
from exifmodern.formats.jpeg.xmp_property_writer import (
    rewrite_jpeg_xmp_properties_creating_if_needed,
)
from exifmodern.formats.xmp.property_write import (
    XMP_PUBLIC_SIDECAR_PROPERTY_NAMES,
    XmpGeneratedPropertyAssignment,
    XmpJobRefFieldValue,
    XmpJobRefPropertyWrite,
    XmpPropertySpec,
    XmpPropertyWritePlan,
    XmpPropertyWriteStep,
    XmpPublicSidecarPropertyAssignment,
    XmpPublicSidecarPropertyDelete,
    XmpResourceRefFieldValue,
    XmpResourceRefPropertyWrite,
    build_generated_xmp_property_write_plan,
    build_public_xmp_sidecar_property_delete_plan,
    build_public_xmp_sidecar_property_write_plan,
    xmp_property_spec,
)
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.formats.xmp.sidecar_writer import rewrite_xmp_sidecar_file_properties_in_place
from exifmodern.formats.xmp.structs.job_ref import (
    job_ref_field_spec_for_field_name,
    job_ref_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.resource_event import (
    resource_event_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.resource_ref import (
    resource_ref_field_spec_for_field_name,
    resource_ref_parent_spec_for_property,
)
from exifmodern.json_types import JsonArray, JsonObject, JsonValue, load_json_value
from exifmodern.media_source import FileMediaSource
from exifmodern.public_api.models import (
    Diagnostic,
    MetadataAssignment,
    MetadataWriteRequest,
    MetadataWriteResult,
    PublicImportWriteRequest,
)

type MetadataWriteExecutor = Callable[[MetadataWriteRequest], MetadataWriteResult]

_EVIDENCE_JSON_KEY = "evidence_ids"
_EVIDENCE_IDS = (
    "public.import-write.cli-entry",
    "public.import-write.csv-read",
    "public.import-write.csv-delimiter",
    "public.import-write.json-read",
    "public.import-write.json-object-values",
    "public.import-write.csv-delimiter-option",
    "public.import-write.sourcefile-aliases",
    "public.import-write.replay-set-new-value",
    "public.import-write.csv-docs",
    "public.import-write.json-docs",
    "public.import-write.json-empty-and-add-docs",
    "public.import-write.iptc-list-tags",
    "public.import-write.xmp-public-properties",
    "public.import-write.xmp-unowned-list-tags",
    "public.import-write.xmp-writer",
    "public.import-write.writer-array-values",
    "public.import-write.xmp-struct-validation",
    "public.import-write.xmp-struct-format",
)
_SKIPPED_TAGS = frozenset({"sourcefile", "directory", "filename"})
_CSV_TAG_NAME_PATTERN = re.compile(r"^([-_0-9A-Z]+:)*[-_0-9A-Z]+#?$", re.IGNORECASE)
_MULTI_TARGET_JPEG_EXIF_SCALAR_TAGS = frozenset({"artist", "imagedescription"})
_XMP_SIDECAR_IMPORT_TAGS = {
    property_name.casefold(): property_name for property_name in XMP_PUBLIC_SIDECAR_PROPERTY_NAMES
}
_XMP_SIDECAR_IMPORT_LIST_TAGS = frozenset(
    property_name.casefold()
    for property_name in XMP_PUBLIC_SIDECAR_PROPERTY_NAMES
    if xmp_property_spec(property_name).rdf_container is not None
)
_JPEG_IPTC_IMPORT_TAGS = {
    normalized_tag: canonical_tag
    for canonical_tag in IPTC_APPLICATION_TAG_SPECS
    for normalized_tag in (canonical_tag.casefold(), f"iptc:{canonical_tag.casefold()}")
}
_JPEG_IPTC_IMPORT_LIST_TAGS = frozenset(
    normalized_tag
    for canonical_tag, spec in IPTC_APPLICATION_TAG_SPECS.items()
    if spec.is_list
    for normalized_tag in (canonical_tag.casefold(), f"iptc:{canonical_tag.casefold()}")
)
_JPEG_IPTC_IMPORT_LIST_ADD_TAGS = _JPEG_IPTC_IMPORT_LIST_TAGS
_OWNED_IMPORT_LIST_TAGS = _XMP_SIDECAR_IMPORT_LIST_TAGS | _JPEG_IPTC_IMPORT_LIST_TAGS
_XMP_CAPABILITY_AUDIT_PATH = Path("artifacts/schema/exiftool-xmp-write-capability-audit.json")
_SOURCE_BACKED_UNOWNED_IMPORT_LIST_TAGS = frozenset(
    {
        "xmp-xmp:advisory",
        "xmp-xmp:identifier",
        "xmp-exif:subjectarea",
        "xmp-iptccore:scene",
        "xmp-iptccore:subjectcode",
    }
)
_JPEG_SUFFIXES = frozenset({".jpg", ".jpeg", ".jpe"})


@dataclass(frozen=True)
class _ImportTagValue:
    tag: str
    value: JsonValue


@dataclass(frozen=True)
class _ImportRecord:
    source_file: str
    values: tuple[_ImportTagValue, ...]


@dataclass(frozen=True)
class _TargetImportReplay:
    target: Path
    assignments: tuple[MetadataAssignment, ...]
    deletes: tuple[str, ...] = ()
    array_replacement_tags: tuple[str, ...] = ()
    xmp_struct_steps: tuple[XmpPropertyWriteStep, ...] = ()
    xmp_struct_specs: tuple[XmpPropertySpec, ...] = ()


@dataclass(frozen=True)
class _ListValueReplay:
    assignments: tuple[MetadataAssignment, ...] = ()
    deletes: tuple[str, ...] = ()


def execute_import_write_request(
    request: MetadataWriteRequest,
    *,
    execute_metadata_write: MetadataWriteExecutor,
) -> MetadataWriteResult:
    import_request = request.import_write
    if import_request is None:
        return MetadataWriteResult(
            request=request,
            status="not_yet_implemented",
            diagnostics=(
                _import_write_diagnostic(
                    "unsupported_import_write_executor_shape",
                    "Import-write execution requires a typed public import request.",
                ),
            ),
        )
    blocker = _request_shape_blocker(request, import_request)
    if blocker is not None:
        return _blocked_import_write_result(request, blocker)
    records, parse_blocker = _load_import_records(import_request)
    if parse_blocker is not None:
        return _blocked_import_write_result(request, parse_blocker)
    replays, replay_blocker = _target_import_replays(request, records)
    if replay_blocker is not None:
        return _blocked_import_write_result(request, replay_blocker)
    route_blocker = _array_replacement_route_blocker(request, replays)
    if route_blocker is not None:
        return _blocked_import_write_result(request, route_blocker)
    route_blocker = _owned_route_blocker(request, replays)
    if route_blocker is not None:
        return _blocked_import_write_result(request, route_blocker)
    if len(replays) > 1:
        route_blocker = _multi_target_route_blocker(request, replays)
        if route_blocker is not None:
            return _blocked_import_write_result(request, route_blocker)

    changed_paths: list[Path] = []
    execution_diagnostics: list[Diagnostic] = []
    for replay in replays:
        if replay.xmp_struct_steps:
            struct_result = _execute_owned_xmp_struct_import_replay(request, replay)
            if struct_result.status != "ok":
                return struct_result
            changed_paths.extend(struct_result.changed_paths)
            execution_diagnostics.extend(struct_result.diagnostics)
            continue
        inner_request = replace(
            request,
            paths=(replay.target,),
            assignments=replay.assignments,
            deletes=replay.deletes,
            import_write=None,
        )
        inner_result = _execute_owned_import_replay_if_supported(inner_request)
        if inner_result is None:
            inner_result = execute_metadata_write(inner_request)
        if inner_result.status != "ok":
            return MetadataWriteResult(
                request=request,
                status=inner_result.status,
                changed_paths=tuple(changed_paths),
                diagnostics=(
                    *execution_diagnostics,
                    *inner_result.diagnostics,
                    _import_write_diagnostic(
                        "unsupported_import_write_route",
                        (
                            "Imported CSV/JSON values were not written because the lowered "
                            "write route is not fully owned by the public writer."
                        ),
                        {
                            "import_path": import_request.path.as_posix(),
                            "target_path": replay.target.as_posix(),
                            "import_format": import_request.import_format,
                            "add_list_items": import_request.add_list_items,
                            "imported_tags": [assignment.tag for assignment in replay.assignments],
                            "imported_deletes": list(replay.deletes),
                            _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
                        },
                    ),
                ),
            )
        changed_paths.extend(inner_result.changed_paths)
        execution_diagnostics.extend(inner_result.diagnostics)
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=tuple(dict.fromkeys(changed_paths)),
        diagnostics=(
            *execution_diagnostics,
            _import_write_diagnostic(
                "native_import_write_executed",
                (
                    "Public CSV/JSON import-write executed by lowering matching "
                    "SourceFile database values into an existing owned write request path."
                ),
                {
                    "import_path": import_request.path.as_posix(),
                    "target_paths": [replay.target.as_posix() for replay in replays],
                    "import_format": import_request.import_format,
                    "add_list_items": import_request.add_list_items,
                    "imported_tags": [
                        assignment.tag for replay in replays for assignment in replay.assignments
                    ],
                    "imported_struct_tags": [
                        step.property_name for replay in replays for step in replay.xmp_struct_steps
                    ],
                    "imported_deletes": [delete for replay in replays for delete in replay.deletes],
                    "changed_paths": [path.as_posix() for path in changed_paths],
                    _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
                },
            ),
        ),
    )


def _execute_owned_import_replay_if_supported(
    request: MetadataWriteRequest,
) -> MetadataWriteResult | None:
    if _is_owned_jpeg_iptc_import_replay(request):
        return _execute_owned_jpeg_iptc_import_replay(request)
    if _is_owned_jpeg_xmp_replay(request):
        return _execute_owned_jpeg_xmp_import_replay(request)
    if _is_owned_jpeg_exif_scalar_replay(request):
        return _execute_owned_jpeg_exif_scalar_import_replay(request)
    if _is_owned_xmp_sidecar_replay(request):
        return _execute_owned_xmp_sidecar_import_replay(request)
    return None


def _is_owned_jpeg_iptc_import_replay(request: MetadataWriteRequest) -> bool:
    return (
        len(request.paths) == 1
        and request.paths[0].suffix.casefold() in _JPEG_SUFFIXES
        and (bool(request.assignments) or bool(request.deletes))
        and all(
            _is_jpeg_iptc_import_route(request.paths[0], assignment.tag)
            for assignment in request.assignments
        )
        and all(delete.casefold() in _JPEG_IPTC_IMPORT_LIST_TAGS for delete in request.deletes)
    )


def _execute_owned_jpeg_iptc_import_replay(
    request: MetadataWriteRequest,
) -> MetadataWriteResult:
    target = request.paths[0]
    try:
        original = target.read_bytes()
        plan = _jpeg_iptc_import_replay_plan(target, request.assignments, request.deletes)
        rewritten = rewrite_jpeg_iptc_application_creating_if_needed(original, plan).data
        changed = rewritten != original
        if changed:
            _write_import_replay_bytes_transactionally(
                request,
                target,
                rewritten,
                _backup_policy(request),
            )
    except (OSError, ValueError) as exc:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(
                _import_write_diagnostic(
                    "native_write_failed",
                    f"Native import JPEG IPTC write failed for {target}: {exc}",
                    {"target_path": target.as_posix(), "error": str(exc)},
                ),
            ),
        )
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=(target,) if changed else (),
        diagnostics=(
            _import_write_diagnostic(
                "native_import_replay_route_executed",
                "Import replay executed through the owned JPEG IPTC APP13 writer route.",
                {
                    "target_path": target.as_posix(),
                    "imported_tags": [assignment.tag for assignment in request.assignments],
                    "imported_deletes": list(request.deletes),
                    "native_callable": (
                        "exifmodern.formats.jpeg.iptc_app13_writer."
                        "rewrite_jpeg_iptc_application_creating_if_needed"
                    ),
                    _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
                },
            ),
        ),
    )


def _jpeg_iptc_import_replay_plan(
    target: Path,
    assignments: tuple[MetadataAssignment, ...],
    deletes: tuple[str, ...],
) -> IptcApplicationWritePlan:
    steps = [
        text_step("delete", _JPEG_IPTC_IMPORT_TAGS[delete.casefold()], ()) for delete in deletes
    ]
    values_by_tag: dict[str, list[str]] = {}
    for assignment in assignments:
        canonical_tag = _JPEG_IPTC_IMPORT_TAGS[assignment.tag.casefold()]
        if assignment.operation == "add_list_value":
            values_by_tag.setdefault(
                canonical_tag,
                list(_existing_jpeg_iptc_tag_values(target, canonical_tag)),
            ).append(assignment.value)
            continue
        values_by_tag.setdefault(canonical_tag, []).append(assignment.value)
    steps.extend(upsert_text_step(tag, tuple(values)) for tag, values in values_by_tag.items())
    if not steps:
        raise ValueError("JPEG IPTC import replay requires at least one write step.")
    return IptcApplicationWritePlan(tuple(steps))


def _existing_jpeg_iptc_tag_values(target: Path, canonical_tag: str) -> tuple[str, ...]:
    try:
        value = read_iptc_tags(target).get(canonical_tag)
    except ValueError:
        return ()
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    if isinstance(value, str):
        return (value,)
    return ()


def _is_owned_jpeg_xmp_replay(request: MetadataWriteRequest) -> bool:
    return (
        len(request.paths) == 1
        and request.paths[0].suffix.casefold() in _JPEG_SUFFIXES
        and (bool(request.assignments) or bool(request.deletes))
        and all(_xmp_import_assignment_is_owned(assignment) for assignment in request.assignments)
        and all(delete.casefold() in _XMP_SIDECAR_IMPORT_LIST_TAGS for delete in request.deletes)
    )


def _execute_owned_jpeg_xmp_import_replay(
    request: MetadataWriteRequest,
) -> MetadataWriteResult:
    target = request.paths[0]
    try:
        if request.deletes:
            plan = build_public_xmp_sidecar_property_delete_plan(
                tuple(
                    XmpPublicSidecarPropertyDelete(_canonical_xmp_sidecar_import_tag(delete))
                    for delete in request.deletes
                )
            )
        else:
            assignments = _jpeg_xmp_replay_assignments(target, request.assignments)
            plan = build_public_xmp_sidecar_property_write_plan(
                tuple(
                    XmpPublicSidecarPropertyAssignment(assignment.tag, assignment.value)
                    for assignment in assignments
                )
            )
        original = target.read_bytes()
        result = rewrite_jpeg_xmp_properties_creating_if_needed(original, plan)
        if result.data != original:
            _write_import_replay_bytes_transactionally(
                request,
                target,
                result.data,
                _backup_policy(request),
            )
    except (OSError, ValueError) as exc:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(
                _import_write_diagnostic(
                    "native_write_failed",
                    f"Native import JPEG XMP property write failed for {target}: {exc}",
                    {"target_path": target.as_posix(), "error": str(exc)},
                ),
            ),
        )
    changed = result.changed_xmp_properties > 0 or result.deleted_xmp_properties > 0
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=(target,) if changed else (),
        diagnostics=(
            _import_write_diagnostic(
                "native_import_replay_route_executed",
                "Import replay executed through the owned JPEG XMP APP1 property writer route.",
                {
                    "target_path": target.as_posix(),
                    "imported_tags": [assignment.tag for assignment in request.assignments],
                    "imported_deletes": list(request.deletes),
                    "native_callable": (
                        "exifmodern.formats.jpeg.xmp_property_writer."
                        "rewrite_jpeg_xmp_properties_creating_if_needed"
                    ),
                    _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
                },
            ),
        ),
    )


def _jpeg_xmp_replay_assignments(
    target: Path,
    assignments: tuple[MetadataAssignment, ...],
) -> tuple[MetadataAssignment, ...]:
    replay_assignments: list[MetadataAssignment] = []
    add_tags = {
        _canonical_xmp_sidecar_import_tag(assignment.tag)
        for assignment in assignments
        if assignment.operation == "add_list_value"
    }
    existing = _existing_jpeg_xmp_groups(target) if add_tags else {}
    for tag in add_tags:
        replay_assignments.extend(
            MetadataAssignment(tag=tag, value=value)
            for value in _existing_xmp_list_values(existing, tag)
        )
    replay_assignments.extend(
        MetadataAssignment(
            tag=_canonical_xmp_sidecar_import_tag(assignment.tag),
            value=assignment.value,
        )
        for assignment in assignments
    )
    return tuple(replay_assignments)


def _existing_jpeg_xmp_groups(target: Path) -> dict[str, JsonObject]:
    source = FileMediaSource(target)
    for probe in read_jpeg_segment_probes(target):
        if probe.marker != 0xE1 or not probe.payload_prefix.startswith(XMP_APP1_PREFIX):
            continue
        payload = source.read_at(probe.payload_offset, probe.payload_length)
        return parse_xmp_packet(payload[len(XMP_APP1_PREFIX) :])
    return {}


def _write_import_replay_bytes_transactionally(
    request: MetadataWriteRequest,
    target: Path,
    data: bytes,
    backup_policy: BackupPolicy,
) -> None:
    if request.policy == "overwrite_original_in_place":
        copy_back_bytes_in_place_transactionally(
            target,
            data,
            preserve_file_times=request.preserve_file_times,
        )
        return
    write_bytes_in_place_transactionally(
        target,
        data,
        backup_policy,
        preserve_file_times=request.preserve_file_times,
    )


def _is_owned_jpeg_exif_scalar_replay(request: MetadataWriteRequest) -> bool:
    return (
        len(request.paths) == 1
        and not request.deletes
        and bool(request.assignments)
        and request.paths[0].suffix.casefold() in _JPEG_SUFFIXES
        and all(
            assignment.operation == "set"
            and assignment.tag.casefold() in _MULTI_TARGET_JPEG_EXIF_SCALAR_TAGS
            for assignment in request.assignments
        )
    )


def _execute_owned_jpeg_exif_scalar_import_replay(
    request: MetadataWriteRequest,
) -> MetadataWriteResult:
    target = request.paths[0]
    values = {assignment.tag.casefold(): assignment.value for assignment in request.assignments}
    try:
        plan = build_exif_scalar_write_plan(
            image_description=values.get("imagedescription"),
            orientation=None,
            date_time_original=None,
            artist=values.get("artist"),
        )
        result = rewrite_jpeg_file_exif_scalars_in_place(
            target,
            plan,
            backup_policy=_backup_policy(request),
            preserve_file_times=request.preserve_file_times,
        )
    except (OSError, ValueError) as exc:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(
                _import_write_diagnostic(
                    "native_write_failed",
                    f"Native import JPEG EXIF scalar write failed for {target}: {exc}",
                    {"target_path": target.as_posix(), "error": str(exc)},
                ),
            ),
        )
    changed_paths = (target,) if result.transaction is not None else ()
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=changed_paths,
        diagnostics=(
            _import_write_diagnostic(
                "native_import_replay_route_executed",
                "Import replay executed through the owned JPEG EXIF scalar writer route.",
                {
                    "target_path": target.as_posix(),
                    "imported_tags": [assignment.tag for assignment in request.assignments],
                    "native_callable": (
                        "exifmodern.formats.jpeg.exif_scalar_writer."
                        "rewrite_jpeg_file_exif_scalars_in_place"
                    ),
                    _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
                },
            ),
        ),
    )


def _is_owned_xmp_sidecar_replay(request: MetadataWriteRequest) -> bool:
    return (
        len(request.paths) == 1
        and request.paths[0].suffix.casefold() == ".xmp"
        and (bool(request.assignments) or bool(request.deletes))
        and all(
            _xmp_sidecar_import_assignment_is_owned(assignment)
            for assignment in request.assignments
        )
        and all(delete.casefold() in _XMP_SIDECAR_IMPORT_LIST_TAGS for delete in request.deletes)
    )


def _xmp_sidecar_import_assignment_is_owned(assignment: MetadataAssignment) -> bool:
    return _xmp_import_assignment_is_owned(assignment)


def _xmp_import_assignment_is_owned(assignment: MetadataAssignment) -> bool:
    normalized_tag = assignment.tag.casefold()
    if normalized_tag not in _XMP_SIDECAR_IMPORT_TAGS:
        return False
    if assignment.operation == "set":
        return True
    return (
        assignment.operation == "add_list_value" and normalized_tag in _XMP_SIDECAR_IMPORT_LIST_TAGS
    )


def _execute_owned_xmp_sidecar_import_replay(
    request: MetadataWriteRequest,
) -> MetadataWriteResult:
    target = request.paths[0]
    try:
        if request.deletes:
            plan = build_public_xmp_sidecar_property_delete_plan(
                tuple(
                    XmpPublicSidecarPropertyDelete(_canonical_xmp_sidecar_import_tag(delete))
                    for delete in request.deletes
                )
            )
        else:
            assignments = _xmp_sidecar_replay_assignments(target, request.assignments)
            plan = build_public_xmp_sidecar_property_write_plan(
                tuple(
                    XmpPublicSidecarPropertyAssignment(assignment.tag, assignment.value)
                    for assignment in assignments
                )
            )
        result = rewrite_xmp_sidecar_file_properties_in_place(
            target,
            plan,
            backup_policy=_backup_policy(request),
            preserve_file_times=request.preserve_file_times,
        )
    except (OSError, ValueError) as exc:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(
                _import_write_diagnostic(
                    "native_write_failed",
                    f"Native import XMP sidecar property write failed for {target}: {exc}",
                    {"target_path": target.as_posix(), "error": str(exc)},
                ),
            ),
        )
    changed = result.changed_xmp_properties > 0 or result.deleted_xmp_properties > 0
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=(target,) if changed else (),
        diagnostics=(
            _import_write_diagnostic(
                "native_import_replay_route_executed",
                "Import replay executed through the owned XMP sidecar property writer route.",
                {
                    "target_path": target.as_posix(),
                    "imported_tags": [assignment.tag for assignment in request.assignments],
                    "imported_deletes": list(request.deletes),
                    "native_callable": (
                        "exifmodern.formats.xmp.sidecar_writer."
                        "rewrite_xmp_sidecar_file_properties_in_place"
                    ),
                    _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
                },
            ),
        ),
    )


def _execute_owned_xmp_struct_import_replay(
    request: MetadataWriteRequest,
    replay: _TargetImportReplay,
) -> MetadataWriteResult:
    plan = XmpPropertyWritePlan(
        replay.xmp_struct_steps,
        (),
        generated_specs=replay.xmp_struct_specs,
    )
    target = replay.target
    try:
        if target.suffix.casefold() == ".xmp":
            result = rewrite_xmp_sidecar_file_properties_in_place(
                target,
                plan,
                backup_policy=_backup_policy(request),
                preserve_file_times=request.preserve_file_times,
            )
            changed = result.changed_xmp_properties > 0 or result.deleted_xmp_properties > 0
            native_callable = (
                "exifmodern.formats.xmp.sidecar_writer.rewrite_xmp_sidecar_file_properties_in_place"
            )
        else:
            original = target.read_bytes()
            jpeg_result = rewrite_jpeg_xmp_properties_creating_if_needed(original, plan)
            changed = (
                jpeg_result.changed_xmp_properties > 0 or jpeg_result.deleted_xmp_properties > 0
            )
            if jpeg_result.data != original:
                _write_import_replay_bytes_transactionally(
                    request,
                    target,
                    jpeg_result.data,
                    _backup_policy(request),
                )
            native_callable = (
                "exifmodern.formats.jpeg.xmp_property_writer."
                "rewrite_jpeg_xmp_properties_creating_if_needed"
            )
    except (OSError, ValueError) as exc:
        return MetadataWriteResult(
            request=request,
            status="unsupported",
            diagnostics=(
                _import_write_diagnostic(
                    "native_write_failed",
                    f"Native import XMP structured property write failed for {target}: {exc}",
                    {"target_path": target.as_posix(), "error": str(exc)},
                ),
            ),
        )
    return MetadataWriteResult(
        request=request,
        status="ok",
        changed_paths=(target,) if changed else (),
        diagnostics=(
            _import_write_diagnostic(
                "native_import_replay_route_executed",
                "Import replay executed through the owned XMP structured property writer route.",
                {
                    "target_path": target.as_posix(),
                    "imported_struct_tags": [
                        step.property_name for step in replay.xmp_struct_steps
                    ],
                    "native_callable": native_callable,
                    _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
                },
            ),
        ),
    )


def _xmp_sidecar_replay_assignments(
    target: Path,
    assignments: tuple[MetadataAssignment, ...],
) -> tuple[MetadataAssignment, ...]:
    replay_assignments: list[MetadataAssignment] = []
    add_tags = {
        _canonical_xmp_sidecar_import_tag(assignment.tag)
        for assignment in assignments
        if assignment.operation == "add_list_value"
    }
    existing = parse_xmp_packet(target.read_bytes()) if add_tags else {}
    for tag in add_tags:
        replay_assignments.extend(
            MetadataAssignment(tag=tag, value=value)
            for value in _existing_xmp_list_values(existing, tag)
        )
    replay_assignments.extend(
        MetadataAssignment(
            tag=_canonical_xmp_sidecar_import_tag(assignment.tag),
            value=assignment.value,
        )
        for assignment in assignments
    )
    return tuple(replay_assignments)


def _existing_xmp_list_values(
    groups: dict[str, JsonObject],
    tag: str,
) -> tuple[str, ...]:
    group, _separator, name = tag.partition(":")
    value = groups.get(group, {}).get(name)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    if isinstance(value, str):
        return (value,)
    return ()


def _canonical_xmp_sidecar_import_tag(tag: str) -> str:
    return _XMP_SIDECAR_IMPORT_TAGS.get(tag.casefold(), tag)


def _backup_policy(request: MetadataWriteRequest) -> BackupPolicy:
    if request.policy in {"overwrite_original", "overwrite_original_in_place"}:
        return "overwrite_original"
    return "create_backup"


def _request_shape_blocker(
    request: MetadataWriteRequest,
    import_request: PublicImportWriteRequest,
) -> Diagnostic | None:
    if not request.paths:
        return _import_write_diagnostic(
            "unsupported_import_write_missing_target",
            "Import-write execution requires at least one target path.",
            {
                "paths": [path.as_posix() for path in request.paths],
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    if request.assignments or request.deletes or request.public_copy_from_file is not None:
        return _import_write_diagnostic(
            "unsupported_import_write_mixed_operations",
            (
                "This bounded import-write slice does not mix imported database "
                "values with other writes."
            ),
            {_EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
        )
    return None


def _load_import_records(
    import_request: PublicImportWriteRequest,
) -> tuple[tuple[_ImportRecord, ...], Diagnostic | None]:
    if import_request.import_format == "csv":
        delimiter_blocker = _csv_delimiter_blocker(import_request)
        if delimiter_blocker is not None:
            return (), delimiter_blocker
        return _load_csv_import_records(import_request.path, delimiter=import_request.csv_delimiter)
    records, diagnostic = _load_json_import_records(import_request.path)
    if (
        diagnostic is not None
        and import_request.add_list_items
        and diagnostic.code == "unsupported_import_write_json_format"
    ):
        return records, _import_write_diagnostic(
            "unsupported_import_write_list_add",
            "JSON += import-write requires at least one import database record.",
            {
                "import_path": import_request.path.as_posix(),
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    return records, diagnostic


def _target_import_replays(
    request: MetadataWriteRequest,
    records: tuple[_ImportRecord, ...],
) -> tuple[tuple[_TargetImportReplay, ...], Diagnostic | None]:
    replays: list[_TargetImportReplay] = []
    import_request = request.import_write
    if import_request is None:
        return (), _import_write_diagnostic(
            "unsupported_import_write_executor_shape",
            "Import-write execution requires a typed public import request.",
        )
    for target in request.paths:
        target_records = _matching_records(records, target)
        if not target_records:
            return (), _import_write_diagnostic(
                "unsupported_import_write_source_file",
                "Import-write requires a SourceFile record matching each target or a '*' default.",
                {
                    "target_path": target.as_posix(),
                    "import_path": import_request.path.as_posix(),
                    "source_files": [imported_record.source_file for imported_record in records],
                    _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
                },
            )
        assignments, deletes, array_replacement_tags, assignment_blocker = (
            _write_operations_from_records(
                target_records,
                add_list_items=import_request.add_list_items,
            )
        )
        if assignment_blocker is not None:
            return (), assignment_blocker
        replays.append(
            _TargetImportReplay(
                target=target,
                assignments=assignments,
                deletes=deletes,
                array_replacement_tags=array_replacement_tags,
                xmp_struct_steps=tuple(
                    step
                    for record in target_records
                    for tag_value in record.values
                    for step in _xmp_struct_steps_for_import_value(tag_value.tag, tag_value.value)
                ),
                xmp_struct_specs=tuple(
                    spec
                    for record in target_records
                    for tag_value in record.values
                    for spec in _xmp_struct_specs_for_import_value(tag_value.tag, tag_value.value)
                ),
            )
        )
    return tuple(replays), None


def _array_replacement_route_blocker(
    request: MetadataWriteRequest,
    replays: tuple[_TargetImportReplay, ...],
) -> Diagnostic | None:
    import_request = request.import_write
    if import_request is None:
        return _import_write_diagnostic(
            "unsupported_import_write_executor_shape",
            "Import-write execution requires a typed public import request.",
        )
    unsupported_routes: JsonArray = []
    mixed_delete_routes: JsonArray = []
    for replay in replays:
        for tag in replay.array_replacement_tags:
            if not _array_replacement_route_is_owned(replay.target, tag):
                unsupported_routes.append({"target_path": replay.target.as_posix(), "tag": tag})
        if replay.array_replacement_tags and replay.deletes and replay.assignments:
            mixed_delete_routes.append(
                {
                    "target_path": replay.target.as_posix(),
                    "array_replacement_tags": list(replay.array_replacement_tags),
                    "assigned_tags": [assignment.tag for assignment in replay.assignments],
                    "deleted_tags": list(replay.deletes),
                }
            )
    if unsupported_routes:
        return _import_write_diagnostic(
            "unsupported_import_write_value",
            (
                "JSON array import values require an owned += list import route or "
                "an owned XMP/JPEG IPTC list replacement route; non-add replacement "
                "is currently owned for public XMP sidecar/JPEG APP1 list properties "
                "and JPEG IPTC list tags."
            ),
            {
                "import_path": import_request.path.as_posix(),
                "unsupported_routes": unsupported_routes,
                "supported_replacement_routes": [
                    "XMP sidecar public list property set",
                    "JPEG XMP APP1 public list property set",
                    "JPEG IPTC ApplicationRecord list property set",
                ],
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    if mixed_delete_routes:
        return _import_write_diagnostic(
            "unsupported_import_write_route",
            (
                "Empty JSON array replacement lowers to a list property delete, and "
                "this bounded import-write slice does not mix that delete with other "
                "lowered assignments in one replay."
            ),
            {
                "import_path": import_request.path.as_posix(),
                "unsupported_routes": mixed_delete_routes,
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    return None


def _multi_target_route_blocker(
    request: MetadataWriteRequest,
    replays: tuple[_TargetImportReplay, ...],
) -> Diagnostic | None:
    import_request = request.import_write
    if import_request is None:
        return _import_write_diagnostic(
            "unsupported_import_write_executor_shape",
            "Import-write execution requires a typed public import request.",
        )
    unsupported_routes: JsonArray = []
    for replay in replays:
        for assignment in replay.assignments:
            if not _multi_target_assignment_route_is_owned(replay.target, assignment):
                unsupported_routes.append(
                    {
                        "target_path": replay.target.as_posix(),
                        "tag": assignment.tag,
                        "operation": assignment.operation,
                    }
                )
        for delete in replay.deletes:
            if not _multi_target_delete_route_is_owned(replay.target, delete):
                unsupported_routes.append(
                    {
                        "target_path": replay.target.as_posix(),
                        "tag": delete,
                        "operation": "delete",
                    }
                )
    if not unsupported_routes:
        return None
    return _import_write_diagnostic(
        "unsupported_import_write_route",
        (
            "Multi-target import-write replay is limited to routes that can be "
            "preflighted as owned before mutating any target."
        ),
        {
            "import_path": import_request.path.as_posix(),
            "unsupported_routes": unsupported_routes,
            "supported_multi_target_routes": [
                "JPEG Artist/ImageDescription scalar set",
                "JPEG IPTC ApplicationRecord scalar/list property set",
                "JPEG IPTC ApplicationRecord list property delete",
                "JPEG IPTC ApplicationRecord list property add",
                "JPEG XMP APP1 public scalar/list property set",
                "JPEG XMP APP1 public list property delete",
                "JPEG XMP APP1 public list property add",
                "XMP sidecar public scalar/list property set",
                "XMP sidecar public list property delete",
                "XMP sidecar public list property add",
            ],
            _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
        },
    )


def _owned_route_blocker(
    request: MetadataWriteRequest,
    replays: tuple[_TargetImportReplay, ...],
) -> Diagnostic | None:
    import_request = request.import_write
    if import_request is None:
        return _import_write_diagnostic(
            "unsupported_import_write_executor_shape",
            "Import-write execution requires a typed public import request.",
        )
    unsupported_routes: JsonArray = []
    unsupported_scalar_add_routes: JsonArray = []
    unsupported_list_add_routes: JsonArray = []
    unsupported_value_routes: JsonArray = []
    unsupported_replay_routes: JsonArray = []
    for replay in replays:
        route_issue_count = (
            len(unsupported_routes)
            + len(unsupported_scalar_add_routes)
            + len(unsupported_list_add_routes)
            + len(unsupported_value_routes)
        )
        for assignment in replay.assignments:
            if not _import_assignment_route_is_owned(replay.target, assignment):
                route: JsonObject = {
                    "target_path": replay.target.as_posix(),
                    "tag": assignment.tag,
                    "operation": assignment.operation,
                }
                if _is_source_backed_scalar_add_blocker(replay.target, assignment):
                    unsupported_scalar_add_routes.append(route)
                elif _is_source_backed_unowned_list_add_blocker(assignment):
                    unsupported_list_add_routes.append(route)
                else:
                    unsupported_routes.append(route)
                continue
            value_blocker = _owned_import_assignment_value_blocker(replay.target, assignment)
            if value_blocker is not None:
                unsupported_value_routes.append(value_blocker)
        for delete in replay.deletes:
            if not _import_delete_route_is_owned(replay.target, delete):
                unsupported_routes.append(
                    {
                        "target_path": replay.target.as_posix(),
                        "tag": delete,
                        "operation": "delete",
                    }
                )
        if replay.xmp_struct_steps:
            if replay.assignments or replay.deletes:
                unsupported_replay_routes.append(
                    {
                        "target_path": replay.target.as_posix(),
                        "assigned_tags": [assignment.tag for assignment in replay.assignments],
                        "struct_tags": [step.property_name for step in replay.xmp_struct_steps],
                        "deleted_tags": list(replay.deletes),
                    }
                )
            elif not _xmp_struct_import_route_is_owned(replay.target):
                unsupported_routes.append(
                    {
                        "target_path": replay.target.as_posix(),
                        "tag": ",".join(step.property_name for step in replay.xmp_struct_steps),
                        "operation": "set_struct",
                    }
                )
        if len(unsupported_routes) + len(unsupported_scalar_add_routes) + len(
            unsupported_list_add_routes
        ) + len(
            unsupported_value_routes
        ) == route_issue_count and not _replay_route_is_owned_executable(replay):
            unsupported_replay_routes.append(
                {
                    "target_path": replay.target.as_posix(),
                    "assigned_tags": [assignment.tag for assignment in replay.assignments],
                    "deleted_tags": list(replay.deletes),
                }
            )
    if unsupported_scalar_add_routes:
        return _import_write_diagnostic(
            "unsupported_import_write_scalar_add",
            (
                "CSV/JSON += import-write is source-backed only for list-type tags; "
                "ExifTool documents that += affects only list-type tags for CSV/JSON "
                "imports, so scalar AddValue routes are blocked instead of being "
                "lowered as scalar assignments."
            ),
            {
                "import_path": import_request.path.as_posix(),
                "unsupported_routes": unsupported_scalar_add_routes,
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    if unsupported_list_add_routes:
        return _import_write_diagnostic(
            "unsupported_import_write_list_add",
            (
                "CSV/JSON += import-write recognized a source-backed list-type tag, "
                "but the target writer route is outside the owned public import "
                "replay routes."
            ),
            {
                "import_path": import_request.path.as_posix(),
                "unsupported_routes": unsupported_list_add_routes,
                "supported_list_add_routes": [
                    "JPEG IPTC ApplicationRecord list property add",
                    "JPEG XMP APP1 public list property add",
                    "XMP sidecar public list property add",
                ],
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    if unsupported_value_routes:
        return _import_write_diagnostic(
            "unsupported_import_write_value",
            "Imported CSV/JSON value is outside the owned writer bounds for this route.",
            {
                "import_path": import_request.path.as_posix(),
                "unsupported_routes": unsupported_value_routes,
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    if unsupported_replay_routes:
        return _import_write_diagnostic(
            "unsupported_import_write_route",
            (
                "Import-write replay is limited to a single owned native writer route "
                "per target before any target is mutated."
            ),
            {
                "import_path": import_request.path.as_posix(),
                "unsupported_routes": unsupported_replay_routes,
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    if not unsupported_routes:
        return None
    return _import_write_diagnostic(
        "unsupported_import_write_route",
        (
            "Import-write replay is limited to routes that can be preflighted "
            "as owned before mutating any target."
        ),
        {
            "import_path": import_request.path.as_posix(),
            "unsupported_routes": unsupported_routes,
            "supported_routes": [
                "JPEG Artist/ImageDescription scalar set",
                "JPEG IPTC ApplicationRecord scalar/list property set",
                "JPEG IPTC ApplicationRecord list property delete",
                "JPEG IPTC ApplicationRecord list property add",
                "JPEG XMP APP1 public scalar/list property set",
                "JPEG XMP APP1 public list property delete",
                "JPEG XMP APP1 public list property add",
                "XMP sidecar public scalar/list property set",
                "XMP sidecar public list property delete",
                "XMP sidecar public list property add",
            ],
            _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
        },
    )


def _replay_route_is_owned_executable(replay: _TargetImportReplay) -> bool:
    request = MetadataWriteRequest(
        paths=(replay.target,),
        assignments=replay.assignments,
        deletes=replay.deletes,
    )
    if replay.xmp_struct_steps:
        return (
            _xmp_struct_import_route_is_owned(replay.target)
            and not replay.assignments
            and not replay.deletes
        )
    return (
        _is_owned_jpeg_iptc_import_replay(request)
        or _is_owned_jpeg_xmp_replay(request)
        or _is_owned_jpeg_exif_scalar_replay(request)
        or _is_owned_xmp_sidecar_replay(request)
    )


def _is_source_backed_scalar_add_blocker(
    target: Path,
    assignment: MetadataAssignment,
) -> bool:
    if assignment.operation != "add_list_value":
        return False
    normalized_tag = assignment.tag.casefold()
    target_suffix = target.suffix.casefold()
    if target_suffix == ".xmp":
        return (
            normalized_tag in _XMP_SIDECAR_IMPORT_TAGS
            and normalized_tag not in _XMP_SIDECAR_IMPORT_LIST_TAGS
        )
    if target_suffix in _JPEG_SUFFIXES:
        return (
            (
                normalized_tag in _MULTI_TARGET_JPEG_EXIF_SCALAR_TAGS
                or normalized_tag in _JPEG_IPTC_IMPORT_TAGS
                or normalized_tag in _XMP_SIDECAR_IMPORT_TAGS
            )
            and normalized_tag not in _JPEG_IPTC_IMPORT_LIST_ADD_TAGS
            and normalized_tag not in _XMP_SIDECAR_IMPORT_LIST_TAGS
        )
    return False


def _is_source_backed_unowned_list_add_blocker(
    assignment: MetadataAssignment,
) -> bool:
    return assignment.operation == "add_list_value" and _source_backed_import_list_tag(
        assignment.tag
    )


def _owned_import_assignment_value_blocker(
    target: Path,
    assignment: MetadataAssignment,
) -> JsonObject | None:
    if not _is_jpeg_iptc_import_route(target, assignment.tag):
        return None
    canonical_tag = _JPEG_IPTC_IMPORT_TAGS[assignment.tag.casefold()]
    max_length = IPTC_APPLICATION_TAG_SPECS[canonical_tag].max_length
    if len(assignment.value) <= max_length:
        return None
    return {
        "target_path": target.as_posix(),
        "tag": assignment.tag,
        "operation": assignment.operation,
        "value_length": len(assignment.value),
        "max_length": max_length,
    }


def _is_jpeg_iptc_import_route(target: Path, tag: str) -> bool:
    return target.suffix.casefold() in _JPEG_SUFFIXES and tag.casefold() in _JPEG_IPTC_IMPORT_TAGS


def _array_replacement_route_is_owned(target: Path, tag: str) -> bool:
    normalized_tag = tag.casefold()
    target_suffix = target.suffix.casefold()
    return (
        (target_suffix == ".xmp" and normalized_tag in _XMP_SIDECAR_IMPORT_LIST_TAGS)
        or (target_suffix in _JPEG_SUFFIXES and normalized_tag in _JPEG_IPTC_IMPORT_LIST_TAGS)
        or (target_suffix in _JPEG_SUFFIXES and normalized_tag in _XMP_SIDECAR_IMPORT_LIST_TAGS)
    )


def _owned_list_import_tag(tag: str) -> bool:
    return tag.casefold() in _OWNED_IMPORT_LIST_TAGS


def _source_backed_import_list_tag(tag: str) -> bool:
    return (
        tag.casefold() in _OWNED_IMPORT_LIST_TAGS
        or tag.casefold() in _SOURCE_BACKED_UNOWNED_IMPORT_LIST_TAGS
    )


def _xmp_struct_import_route_is_owned(target: Path) -> bool:
    suffix = target.suffix.casefold()
    return suffix == ".xmp" or suffix in _JPEG_SUFFIXES


def _multi_target_assignment_route_is_owned(
    target: Path,
    assignment: MetadataAssignment,
) -> bool:
    return _import_assignment_route_is_owned(target, assignment)


def _import_assignment_route_is_owned(
    target: Path,
    assignment: MetadataAssignment,
) -> bool:
    normalized_tag = assignment.tag.casefold()
    target_suffix = target.suffix.casefold()
    if assignment.operation == "set":
        return (
            (
                target_suffix in _JPEG_SUFFIXES
                and normalized_tag in _MULTI_TARGET_JPEG_EXIF_SCALAR_TAGS
            )
            or (target_suffix in _JPEG_SUFFIXES and normalized_tag in _JPEG_IPTC_IMPORT_TAGS)
            or (target_suffix in _JPEG_SUFFIXES and normalized_tag in _XMP_SIDECAR_IMPORT_TAGS)
            or (target_suffix == ".xmp" and normalized_tag in _XMP_SIDECAR_IMPORT_TAGS)
        )
    if assignment.operation == "add_list_value":
        return (
            (target_suffix == ".xmp" and normalized_tag in _XMP_SIDECAR_IMPORT_LIST_TAGS)
            or (
                target_suffix in _JPEG_SUFFIXES
                and normalized_tag in _JPEG_IPTC_IMPORT_LIST_ADD_TAGS
            )
            or (target_suffix in _JPEG_SUFFIXES and normalized_tag in _XMP_SIDECAR_IMPORT_LIST_TAGS)
        )
    return False


def _multi_target_delete_route_is_owned(target: Path, tag: str) -> bool:
    return _import_delete_route_is_owned(target, tag)


def _import_delete_route_is_owned(target: Path, tag: str) -> bool:
    target_suffix = target.suffix.casefold()
    normalized_tag = tag.casefold()
    return (
        (target_suffix == ".xmp" and normalized_tag in _XMP_SIDECAR_IMPORT_LIST_TAGS)
        or (target_suffix in _JPEG_SUFFIXES and normalized_tag in _JPEG_IPTC_IMPORT_LIST_TAGS)
        or (target_suffix in _JPEG_SUFFIXES and normalized_tag in _XMP_SIDECAR_IMPORT_LIST_TAGS)
    )


def _csv_delimiter_blocker(import_request: PublicImportWriteRequest) -> Diagnostic | None:
    if import_request.csv_delimiter == "":
        return _import_write_diagnostic(
            "unsupported_import_write_csv_delimiter",
            "CSV import-write delimiter can not be empty.",
            {
                "import_path": import_request.path.as_posix(),
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    if '"' in import_request.csv_delimiter:
        return _import_write_diagnostic(
            "unsupported_import_write_csv_delimiter",
            "CSV import-write delimiter can not contain a double quote.",
            {
                "import_path": import_request.path.as_posix(),
                "csv_delimiter": import_request.csv_delimiter,
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    return None


def _load_csv_import_records(
    path: Path,
    *,
    delimiter: str,
) -> tuple[tuple[_ImportRecord, ...], Diagnostic | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return (), _import_write_diagnostic(
            "unsupported_import_write_open",
            f"Could not open CSV import file {path}: {exc}",
            {"import_path": path.as_posix(), _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
        )
    try:
        rows = tuple(_read_exiftool_csv_rows(text, delimiter=delimiter))
    except ValueError as exc:
        return (), _import_write_diagnostic(
            "unsupported_import_write_csv",
            f"Could not parse CSV import file {path}: {exc}",
            {
                "import_path": path.as_posix(),
                "csv_delimiter": delimiter,
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    if not rows:
        return (), _import_write_diagnostic(
            "unsupported_import_write_csv",
            "CSV import-write requires a non-empty header row.",
            {
                "import_path": path.as_posix(),
                "csv_delimiter": delimiter,
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    header, header_blocker = _csv_header(rows[0])
    if header_blocker is not None:
        return (), header_blocker
    records: list[_ImportRecord] = []
    for row in rows[1:]:
        record = _csv_record(header, row)
        if record is not None:
            records.append(record)
    if not records:
        return (), _import_write_diagnostic(
            "unsupported_import_write_csv",
            "CSV import-write requires at least one row with a SourceFile value.",
            {
                "import_path": path.as_posix(),
                "csv_delimiter": delimiter,
                _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
            },
        )
    return tuple(records), None


def _read_exiftool_csv_rows(text: str, *, delimiter: str) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    position = 0
    length = len(text)
    while position < length:
        row, position = _read_exiftool_csv_row(text, position, delimiter=delimiter)
        if row or position < length:
            rows.append(row)
    if text == "":
        return ()
    if text.endswith(("\n", "\r")):
        return tuple(rows)
    return tuple(rows)


def _read_exiftool_csv_row(
    text: str,
    position: int,
    *,
    delimiter: str,
) -> tuple[tuple[str, ...], int]:
    values: list[str] = []
    length = len(text)
    while True:
        value, position = _read_exiftool_csv_value(text, position, delimiter=delimiter)
        values.append(value)
        if position >= length:
            return tuple(values), position
        if text.startswith(delimiter, position):
            position += len(delimiter)
            continue
        if text.startswith("\r\n", position):
            return tuple(values), position + 2
        if text[position] in {"\r", "\n"}:
            return tuple(values), position + 1
        raise ValueError("CSV value was not followed by delimiter or newline")


def _read_exiftool_csv_value(
    text: str,
    position: int,
    *,
    delimiter: str,
) -> tuple[str, int]:
    length = len(text)
    while position < length and text[position] == " ":
        position += 1
    if position < length and text[position] == '"':
        position += 1
        chars: list[str] = []
        while position < length:
            char = text[position]
            if char == '"':
                if position + 1 < length and text[position + 1] == '"':
                    chars.append('"')
                    position += 2
                    continue
                position += 1
                while position < length and text[position] in {" ", "\t"}:
                    position += 1
                return "".join(chars), position
            chars.append(char)
            position += 1
        return "".join(chars), position
    value_start = position
    while position < length:
        if text.startswith(delimiter, position) or text.startswith("\r\n", position):
            break
        if text[position] in {"\r", "\n"}:
            break
        position += 1
    return text[value_start:position].rstrip(" \n\r"), position


def _csv_header(row: tuple[str, ...]) -> tuple[tuple[str, ...], Diagnostic | None]:
    header: list[str] = []
    for index, raw_name in enumerate(row):
        name = raw_name.removeprefix("\ufeff") if index == 0 else raw_name
        if name == "":
            break
        if _CSV_TAG_NAME_PATTERN.fullmatch(name) is None:
            return (), _import_write_diagnostic(
                "unsupported_import_write_csv",
                f"CSV import-write has invalid tag name {name!r}.",
                {"tag": name, _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
            )
        header.append("SourceFile" if index == 0 and name.lower() == "sourcefile" else name)
    if not header:
        return (), _import_write_diagnostic(
            "unsupported_import_write_csv",
            "CSV import-write requires at least one tag header.",
            {_EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
        )
    if header[0] != "SourceFile":
        return (), _import_write_diagnostic(
            "unsupported_import_write_csv",
            "CSV import-write requires SourceFile as the first column.",
            {_EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
        )
    return tuple(header), None


def _csv_record(header: tuple[str, ...], row: tuple[str, ...]) -> _ImportRecord | None:
    values: list[_ImportTagValue] = []
    source_file = ""
    for index, tag in enumerate(header):
        if index >= len(row):
            continue
        value = row[index]
        if value == "":
            continue
        if index == 0:
            source_file = value
        values.append(_ImportTagValue(tag=tag, value=value))
    if source_file == "":
        return None
    return _ImportRecord(source_file=source_file, values=tuple(values))


def _load_json_import_records(path: Path) -> tuple[tuple[_ImportRecord, ...], Diagnostic | None]:
    try:
        payload = load_json_value(path)
    except OSError as exc:
        return (), _import_write_diagnostic(
            "unsupported_import_write_open",
            f"Could not open JSON import file {path}: {exc}",
            {"import_path": path.as_posix(), _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
        )
    except ValueError as exc:
        return (), _import_write_diagnostic(
            "unsupported_import_write_json_format",
            f"Could not parse JSON import file {path}: {exc}",
            {"import_path": path.as_posix(), _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
        )
    json_records: tuple[JsonObject, ...]
    if isinstance(payload, dict):
        json_records = (payload,)
    elif isinstance(payload, list):
        json_records = tuple(item for item in payload if isinstance(item, dict))
    else:
        json_records = ()
    if not json_records:
        return (), _import_write_diagnostic(
            "unsupported_import_write_json_format",
            "JSON import-write requires at least one object record.",
            {"import_path": path.as_posix(), _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
        )
    import_records = tuple(_json_record(record) for record in json_records)
    return import_records, None


def _json_record(record: JsonObject) -> _ImportRecord:
    source_file = _record_source_file(record) or "*"
    return _ImportRecord(
        source_file=source_file,
        values=tuple(_ImportTagValue(tag=key, value=value) for key, value in record.items()),
    )


def _matching_records(
    records: tuple[_ImportRecord, ...],
    target: Path,
) -> tuple[_ImportRecord, ...]:
    target_names = _source_file_aliases(target.as_posix()) | _source_file_aliases(str(target))
    defaults = tuple(record for record in records if record.source_file == "*")
    matches = tuple(
        record
        for record in records
        if record.source_file != "*"
        and bool(_source_file_aliases(record.source_file) & target_names)
    )
    return (*defaults, *matches)


def _source_file_aliases(source_file: str) -> set[str]:
    slash_normalized = source_file.replace("\\", "/")
    aliases = {source_file, slash_normalized}
    with contextlib.suppress(OSError):
        aliases.add(Path(slash_normalized).resolve().as_posix())
    return aliases | {alias.casefold() for alias in aliases}


def _record_source_file(record: JsonObject) -> str | None:
    for key, value in record.items():
        if key.lower() == "sourcefile" and isinstance(value, str):
            return value
    return None


def _write_operations_from_records(
    records: tuple[_ImportRecord, ...],
    *,
    add_list_items: bool,
) -> tuple[tuple[MetadataAssignment, ...], tuple[str, ...], tuple[str, ...], Diagnostic | None]:
    assignments_by_tag: dict[str, tuple[MetadataAssignment, ...]] = {}
    deletes_by_tag: dict[str, str] = {}
    array_replacement_tags_by_tag: dict[str, str] = {}
    assignments: list[MetadataAssignment] = []
    xmp_struct_value_seen = False
    for record in records:
        for tag_value in record.values:
            key = tag_value.tag
            value = tag_value.value
            if key.lower() in _SKIPPED_TAGS:
                continue
            if _xmp_struct_steps_for_import_value(key, value):
                if add_list_items:
                    return (
                        (),
                        (),
                        (),
                        _import_write_diagnostic(
                            "unsupported_import_write_list_add",
                            (
                                "JSON += structured XMP import values are blocked until "
                                "the public XMP struct route owns source-backed AddValue "
                                "append semantics."
                            ),
                            {"tag": key, _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
                        ),
                    )
                xmp_struct_value_seen = True
                continue
            if add_list_items and _source_backed_xmp_struct_import_candidate(key, value):
                return (
                    (),
                    (),
                    (),
                    _import_write_diagnostic(
                        "unsupported_import_write_list_add",
                        (
                            "JSON += structured XMP import values are blocked until "
                            "the public XMP struct route owns source-backed AddValue "
                            "append semantics."
                        ),
                        {"tag": key, _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
                    ),
                )
            if isinstance(value, list):
                list_replay, list_blocker = _list_value_replay(
                    key,
                    value,
                    add_list_items=add_list_items,
                )
                if list_blocker is not None:
                    return (), (), (), list_blocker
                if add_list_items:
                    assignments.extend(list_replay.assignments)
                else:
                    normalized_key = key.casefold()
                    array_replacement_tags_by_tag[normalized_key] = key
                    if list_replay.deletes:
                        assignments_by_tag.pop(normalized_key, None)
                        deletes_by_tag[normalized_key] = list_replay.deletes[0]
                    else:
                        deletes_by_tag.pop(normalized_key, None)
                        assignments_by_tag[normalized_key] = list_replay.assignments
                continue
            if _unsupported_import_value(value):
                return (
                    (),
                    (),
                    (),
                    _import_write_diagnostic(
                        "unsupported_import_write_value",
                        (
                            "Structured JSON object import values are blocked because "
                            "ExifTool documents JSON objects exported by -D/-H/-l/-T as "
                            "not compatible with JSON import, and this slice has no owned "
                            "XMP struct adapter replay route."
                        ),
                        {
                            "tag": key,
                            "value_kind": "object" if isinstance(value, dict) else "null",
                            _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
                        },
                    ),
                )
            assignment = MetadataAssignment(
                tag=key,
                value=_import_scalar_text(value),
                operation="add_list_value" if add_list_items else "set",
            )
            if add_list_items:
                assignments.append(assignment)
                continue
            normalized_key = key.casefold()
            deletes_by_tag.pop(normalized_key, None)
            array_replacement_tags_by_tag.pop(normalized_key, None)
            assignments_by_tag[normalized_key] = (assignment,)
    if not add_list_items:
        assignments = [
            assignment
            for tag_assignments in assignments_by_tag.values()
            for assignment in tag_assignments
        ]
    deletes = tuple(deletes_by_tag.values()) if not add_list_items else ()
    array_replacement_tags = (
        tuple(array_replacement_tags_by_tag.values()) if not add_list_items else ()
    )
    if not assignments and not deletes and not xmp_struct_value_seen:
        return (
            (),
            (),
            (),
            _import_write_diagnostic(
                "unsupported_import_write_empty_record",
                "Import-write database did not contain writable tag values for this target.",
                {_EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
            ),
        )
    return tuple(assignments), deletes, array_replacement_tags, None


def _list_value_replay(
    tag: str,
    value: list[JsonValue],
    *,
    add_list_items: bool,
) -> tuple[_ListValueReplay, Diagnostic | None]:
    if not _owned_list_import_tag(tag):
        if add_list_items and _source_backed_import_list_tag(tag):
            return _ListValueReplay(), _import_write_diagnostic(
                "unsupported_import_write_list_add",
                (
                    "JSON += import-write recognized a source-backed list-type tag, "
                    "but the target writer route is outside the owned public import "
                    "replay routes."
                ),
                {
                    "tag": tag,
                    "supported_list_add_routes": [
                        "JPEG IPTC ApplicationRecord list property add",
                        "JPEG XMP APP1 public list property add",
                        "XMP sidecar public list property add",
                    ],
                    _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS),
                },
            )
        return _ListValueReplay(), _import_write_diagnostic(
            "unsupported_import_write_value",
            (
                "JSON array import values are supported only for owned list routes "
                "with target-aware replay adapters."
            ),
            {"tag": tag, _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
        )
    if not value:
        if add_list_items:
            return _ListValueReplay(), _import_write_diagnostic(
                "unsupported_import_write_empty_record",
                "JSON array import value did not contain writable list items.",
                {"tag": tag, _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
            )
        return _ListValueReplay(deletes=(tag,)), None
    assignments: list[MetadataAssignment] = []
    for item in value:
        if _unsupported_import_value(item):
            return _ListValueReplay(), _import_write_diagnostic(
                "unsupported_import_write_value",
                "JSON array import values must contain only scalar list items.",
                {"tag": tag, _EVIDENCE_JSON_KEY: list(_EVIDENCE_IDS)},
            )
        assignments.append(
            MetadataAssignment(
                tag=tag,
                value=_import_scalar_text(item),
                operation="add_list_value" if add_list_items else "set",
            )
        )
    return _ListValueReplay(assignments=tuple(assignments)), None


def _xmp_struct_steps_for_import_value(
    tag: str,
    value: JsonValue,
) -> tuple[XmpPropertyWriteStep, ...]:
    generated_plan = _generated_xmp_struct_plan_for_import_value(tag, value)
    if generated_plan is not None:
        return generated_plan.steps
    resource_ref_step = _xmp_resource_ref_step_for_import_value(tag, value)
    if resource_ref_step is not None:
        return (resource_ref_step,)
    job_ref_step = _xmp_job_ref_step_for_import_value(tag, value)
    if job_ref_step is not None:
        return (job_ref_step,)
    return ()


def _source_backed_xmp_struct_import_candidate(tag: str, value: JsonValue) -> bool:
    if not _xmp_struct_objects(value):
        return False
    return (
        resource_ref_parent_spec_for_property(tag) is not None
        or job_ref_parent_spec_for_property(tag) is not None
        or resource_event_parent_spec_for_property(tag) is not None
    )


def _xmp_struct_specs_for_import_value(
    tag: str,
    value: JsonValue,
) -> tuple[XmpPropertySpec, ...]:
    generated_plan = _generated_xmp_struct_plan_for_import_value(tag, value)
    if generated_plan is not None:
        return generated_plan.generated_specs
    if not _xmp_struct_steps_for_import_value(tag, value):
        return ()
    resource_ref_spec = resource_ref_parent_spec_for_property(tag)
    if resource_ref_spec is not None:
        return (
            XmpPropertySpec(
                resource_ref_spec.property_name,
                "xmpMM",
                "http://ns.adobe.com/xap/1.0/mm/",
                resource_ref_spec.element_name,
                "resource_ref",
                (),
                resource_ref_spec.list_kind,
            ),
        )
    job_ref_spec = job_ref_parent_spec_for_property(tag)
    if job_ref_spec is not None:
        return (
            XmpPropertySpec(
                job_ref_spec.property_name,
                "xmpBJ",
                "http://ns.adobe.com/xap/1.0/bj/",
                job_ref_spec.element_name,
                "job_ref",
                (),
                job_ref_spec.list_kind,
            ),
        )
    return ()


def _generated_xmp_struct_plan_for_import_value(
    tag: str,
    value: JsonValue,
) -> XmpPropertyWritePlan | None:
    struct_objects = _xmp_struct_objects(value)
    if not struct_objects:
        return None
    assignments = _generated_xmp_struct_assignments_for_import_value(tag, struct_objects)
    if not assignments:
        return None
    try:
        plan = build_generated_xmp_property_write_plan(_XMP_CAPABILITY_AUDIT_PATH, assignments)
    except OSError, ValueError:
        return None
    if plan.generated_diagnostics or not plan.steps:
        return None
    return plan


def _generated_xmp_struct_assignments_for_import_value(
    tag: str,
    struct_objects: tuple[JsonObject, ...],
) -> tuple[XmpGeneratedPropertyAssignment, ...]:
    group, separator, parent_name = tag.partition(":")
    if separator != ":" or not group.startswith("XMP-"):
        return ()
    assignments: list[XmpGeneratedPropertyAssignment] = []
    for struct_object in struct_objects:
        for field_name, item in struct_object.items():
            if not _json_import_scalar_is_writable(item):
                return ()
            assignments.append(
                XmpGeneratedPropertyAssignment(
                    f"{group}:{parent_name}{_generated_xmp_struct_field_suffix(field_name)}",
                    _import_scalar_text(item),
                )
            )
    return tuple(assignments)


def _generated_xmp_struct_field_suffix(field_name: str) -> str:
    if field_name == "":
        return field_name
    return field_name[:1].upper() + field_name[1:]


def _xmp_resource_ref_step_for_import_value(
    tag: str,
    value: JsonValue,
) -> XmpResourceRefPropertyWrite | None:
    parent_spec = resource_ref_parent_spec_for_property(tag)
    if parent_spec is None:
        return None
    struct_object = _single_xmp_struct_object(value)
    if struct_object is None:
        return None
    field_values: list[XmpResourceRefFieldValue] = []
    for key, item in struct_object.items():
        if not _json_import_scalar_is_writable(item):
            return None
        field_spec = resource_ref_field_spec_for_field_name(key)
        if field_spec is None:
            target = resource_ref_field_spec_for_field_name(key[:1].lower() + key[1:])
            field_spec = target
        if field_spec is None:
            continue
        field_values.append(
            XmpResourceRefFieldValue(field_spec.field_name, _import_scalar_text(item))
        )
    if not field_values:
        return None
    return XmpResourceRefPropertyWrite(parent_spec.property_name, tuple(field_values))


def _xmp_job_ref_step_for_import_value(
    tag: str,
    value: JsonValue,
) -> XmpJobRefPropertyWrite | None:
    parent_spec = job_ref_parent_spec_for_property(tag)
    if parent_spec is None:
        return None
    struct_object = _single_xmp_struct_object(value)
    if struct_object is None:
        return None
    field_values: list[XmpJobRefFieldValue] = []
    for key, item in struct_object.items():
        if not _json_import_scalar_is_writable(item):
            return None
        field_spec = job_ref_field_spec_for_field_name(key)
        if field_spec is None:
            field_spec = job_ref_field_spec_for_field_name(key[:1].lower() + key[1:])
        if field_spec is None:
            continue
        field_values.append(XmpJobRefFieldValue(field_spec.field_name, _import_scalar_text(item)))
    if not field_values:
        return None
    return XmpJobRefPropertyWrite(parent_spec.property_name, tuple(field_values))


def _single_xmp_struct_object(value: JsonValue) -> JsonObject | None:
    struct_objects = _xmp_struct_objects(value)
    if len(struct_objects) == 1:
        return struct_objects[0]
    return None


def _xmp_struct_objects(value: JsonValue) -> tuple[JsonObject, ...]:
    value = _json_structformat_value(value)
    if isinstance(value, dict):
        return (value,)
    if isinstance(value, list) and value:
        objects: list[JsonObject] = []
        for item in value:
            if not isinstance(item, dict):
                return ()
            objects.append(item)
        return tuple(objects)
    return ()


def _json_structformat_value(value: JsonValue) -> JsonValue:
    if not isinstance(value, dict) or "val" not in value:
        return value
    wrapper_keys = {key.casefold() for key in value}
    if not wrapper_keys <= {"val", "id", "table", "desc", "num"}:
        return value
    wrapped = value["val"]
    if isinstance(wrapped, dict):
        return wrapped
    if isinstance(wrapped, list) and all(isinstance(item, dict) for item in wrapped):
        return wrapped
    return None


def _json_import_scalar_is_writable(value: JsonValue) -> bool:
    return value is not None and not isinstance(value, (dict, list))


def _unsupported_import_value(value: JsonValue) -> bool:
    return value is None or isinstance(value, (dict, list))


def _import_scalar_text(value: JsonValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return ""


def _blocked_import_write_result(
    request: MetadataWriteRequest,
    diagnostic: Diagnostic,
) -> MetadataWriteResult:
    return MetadataWriteResult(
        request=request,
        status="not_yet_implemented",
        diagnostics=(diagnostic,),
    )


def _import_write_diagnostic(
    code: str,
    message: str,
    details: JsonObject | None = None,
) -> Diagnostic:
    return Diagnostic(code=code, message=message, details=details)
