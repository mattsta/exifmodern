"""Typed runtime lookups backed by the generated maker-note package."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from exifmodern.formats.maker_notes.context import (
    EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
    MakerNoteRuntimeContext,
)
from exifmodern.package_resources import maker_note_package_path
from exifmodern.services.maker_note_tables import (
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
    load_maker_note_table_repository_for_modules,
)

type MakerNotePackagePrintLookupStatus = Literal[
    "condition_blocked",
    "condition_false",
    "converted",
    "missing_entry",
    "not_table_backed",
    "unknown_value",
]


@dataclass(frozen=True)
class MakerNotePackagePrintLookupRequest:
    module: str
    table: str
    tag_name: str
    raw_value: str
    tag_id: str = ""
    runtime_context: MakerNoteRuntimeContext = EMPTY_MAKER_NOTE_RUNTIME_CONTEXT


@dataclass(frozen=True)
class MakerNotePackagePrintLookupResult:
    request: MakerNotePackagePrintLookupRequest
    status: MakerNotePackagePrintLookupStatus
    printed_value: str | None
    source_path: str
    source_module: str
    source_table: str
    source_tag_id: str
    source_tag_name: str

    @property
    def converted(self) -> bool:
        return self.status == "converted"


@lru_cache(maxsize=1)
def default_maker_note_table_repository() -> MakerNoteTableRepository:
    return load_maker_note_table_repository(maker_note_package_path())


@lru_cache(maxsize=64)
def default_maker_note_module_table_repository(module: str) -> MakerNoteTableRepository:
    return load_maker_note_table_repository_for_modules(maker_note_package_path(), (module,))


def lookup_maker_note_package_print_conversion(
    repository: MakerNoteTableRepository,
    request: MakerNotePackagePrintLookupRequest,
) -> MakerNotePackagePrintLookupResult:
    locations = _lookup_locations(repository, request)
    if not locations:
        return _missing_result(request)

    return _lookup_maker_note_package_print_conversion_locations(request, locations)


def _lookup_locations(
    repository: MakerNoteTableRepository,
    request: MakerNotePackagePrintLookupRequest,
) -> tuple[MakerNoteTagLocation, ...]:
    return repository.tag_entry_locations_for(
        module=request.module,
        table=request.table,
        tag_name=request.tag_name,
        tag_id=request.tag_id,
    )


def _lookup_maker_note_package_print_conversion_locations(
    request: MakerNotePackagePrintLookupRequest,
    locations: tuple[MakerNoteTagLocation, ...],
) -> MakerNotePackagePrintLookupResult:
    condition_false_location: MakerNoteTagLocation | None = None
    not_table_backed_location: MakerNoteTagLocation | None = None
    unknown_value_location: MakerNoteTagLocation | None = None
    for location in locations:
        condition_status = _location_condition_status(request, location)
        if condition_status == "condition_blocked":
            return _location_result(
                request,
                location,
                status="condition_blocked",
                printed_value=None,
            )
        if condition_status == "condition_false":
            condition_false_location = condition_false_location or location
            continue
        if not location.entry.print_conv_pair_count:
            not_table_backed_location = not_table_backed_location or location
            continue
        printed = location.entry.print_conversion_for(request.raw_value)
        if printed is not None:
            return _location_result(
                request,
                location,
                status="converted",
                printed_value=printed,
            )
        if location.entry.has_condition:
            return _location_result(
                request,
                location,
                status="unknown_value",
                printed_value=None,
            )
        unknown_value_location = unknown_value_location or location

    if unknown_value_location is not None:
        return _location_result(
            request,
            unknown_value_location,
            status="unknown_value",
            printed_value=None,
        )
    if not_table_backed_location is not None:
        return _location_result(
            request,
            not_table_backed_location,
            status="not_table_backed",
            printed_value=None,
        )
    if condition_false_location is not None:
        return _location_result(
            request,
            condition_false_location,
            status="condition_false",
            printed_value=None,
        )

    return _missing_result(request)


def lookup_maker_note_package_print_conversions(
    repository: MakerNoteTableRepository,
    requests: tuple[MakerNotePackagePrintLookupRequest, ...],
) -> tuple[MakerNotePackagePrintLookupResult, ...]:
    return tuple(
        lookup_maker_note_package_print_conversion(repository, request) for request in requests
    )


def render_maker_note_package_print_value(
    *,
    module: str,
    table: str,
    tag_name: str,
    raw_value: str | int,
    tag_id: str | int = "",
    runtime_context: MakerNoteRuntimeContext = EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
) -> str | None:
    result = lookup_maker_note_package_print_conversion(
        default_maker_note_lookup_repository(module),
        MakerNotePackagePrintLookupRequest(
            module,
            table,
            tag_name,
            str(raw_value),
            str(tag_id) if tag_id != "" else "",
            runtime_context,
        ),
    )
    return result.printed_value if result.converted else None


def render_maker_note_package_runtime_print_value(
    *,
    module: str,
    table: str,
    tag_name: str,
    raw_value: str | int,
    tag_id: str | int = "",
    runtime_context: MakerNoteRuntimeContext = EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
) -> str | None:
    """Render generated package PrintConv, including domain adapter-backed entries."""
    from exifmodern.formats.maker_notes.print_conversion import (
        MakerNotePrintConversionRequest,
        render_maker_note_print_conversion,
    )

    result = render_maker_note_print_conversion(
        default_maker_note_lookup_repository(module),
        MakerNotePrintConversionRequest(
            raw_value=str(raw_value),
            module=module,
            table=table,
            tag_name=tag_name,
            tag_id=str(tag_id) if tag_id != "" else "",
            runtime_context=runtime_context,
        ),
    )
    for match in result.matches:
        if match.converted:
            return match.printed_value
    return None


def default_maker_note_lookup_repository(module: str) -> MakerNoteTableRepository:
    if module:
        return default_maker_note_module_table_repository(module)
    return default_maker_note_table_repository()


def _location_condition_status(
    request: MakerNotePackagePrintLookupRequest,
    location: MakerNoteTagLocation,
) -> Literal["condition_passed", "condition_false", "condition_blocked"]:
    entry = location.entry
    if entry.condition_kind != "scalar" or not entry.condition_text:
        return "condition_passed"
    from exifmodern.formats.maker_notes.condition_predicate import (
        MakerNoteConditionRequest,
        evaluate_maker_note_condition_match,
        maker_note_condition_inputs,
    )

    condition = evaluate_maker_note_condition_match(
        location,
        maker_note_condition_inputs(
            MakerNoteConditionRequest(
                raw_value=request.raw_value,
                runtime_context=request.runtime_context,
            )
        ),
    )
    if condition.status == "not_scalar_condition":
        return "condition_passed"
    if condition.status == "evaluated" and condition.matched is True:
        return "condition_passed"
    if condition.status == "evaluated":
        return "condition_false"
    return "condition_blocked"


def _location_result(
    request: MakerNotePackagePrintLookupRequest,
    location: MakerNoteTagLocation,
    *,
    status: MakerNotePackagePrintLookupStatus,
    printed_value: str | None,
) -> MakerNotePackagePrintLookupResult:
    return MakerNotePackagePrintLookupResult(
        request=request,
        status=status,
        printed_value=printed_value,
        source_path=location.module.source_path,
        source_module=location.module.module,
        source_table=location.table.name,
        source_tag_id=location.entry.tag_id,
        source_tag_name=location.entry.name,
    )


def _missing_result(
    request: MakerNotePackagePrintLookupRequest,
) -> MakerNotePackagePrintLookupResult:
    return MakerNotePackagePrintLookupResult(
        request=request,
        status="missing_entry",
        printed_value=None,
        source_path="",
        source_module=request.module,
        source_table=request.table,
        source_tag_id=request.tag_id,
        source_tag_name=request.tag_name,
    )
