"""Apple PLIST metadata transaction planning public API."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from exifmodern.dispatch_helpers import _graph, _provenance
from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.plist.transaction_plan import (
    PLIST_MAIN_SOURCE,
    PlistDatabaseEntryPlan,
    PlistTransactionPlan,
    PlistValuePlan,
    build_plist_transaction_plan,
)
from exifmodern.json_types import JsonValue
from exifmodern.read_graph import (
    BinaryTagListValue,
    BinaryTagValue,
    ReadGraph,
    ReadTag,
    ScalarTagValue,
    TagValue,
)
from exifmodern.signature_trie.signature import Pattern, PreprocessKind, Signature

_PLIST_PUBLIC_READ_LIMIT = 64 * 1024 * 1024

__all__ = (
    "PlistTransactionPlan",
    "build_plist_read_graph",
    "build_plist_transaction_plan",
    "invoke_plist",
)


def build_plist_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_plist_transaction_plan(data)
    group = _plist_group(plan)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"PLIST package-local reader status: {plan.status}")
    diagnostics.extend(
        f"PLIST package-local reader gate: {gate.code}" for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = _plist_file_tags(source_file, plan)
    deferred_nested_tags: list[ReadTag] = []
    for ordinal, item in enumerate(_coalesced_display_entries(plan.database_entries, group=group)):
        entry = item.entry
        if entry.tag_id == "adjustmentData":
            deferred_nested_tags.extend(_nested_adjustment_data_tags(entry, source_file))
            continue
        tags.append(
            ReadTag(
                name=_plist_tag_name(entry),
                value=item.value,
                provenance=_provenance(
                    group=group,
                    table_name="Image::ExifTool::PLIST::Main",
                    tag_id=entry.tag_id,
                    evidence_ids=entry.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    tags.extend(deferred_nested_tags)
    return _graph(source_file, tags, diagnostics)


@dataclass(frozen=True)
class _PlistCoalescedDisplayEntry:
    entry: PlistDatabaseEntryPlan
    value: TagValue


_LOCAL_TZ = ZoneInfo("America/New_York")

_PLIST_KNOWN_NAMES: dict[str, str] = {
    "adjustmentBaseVersion": "AdjustmentBaseVersion",
    "adjustmentData": "AdjustmentData",
    "adjustmentEditorBundleID": "AdjustmentEditorBundleID",
    "adjustmentFormatIdentifier": "AdjustmentFormatIdentifier",
    "adjustmentFormatVersion": "AdjustmentFormatVersion",
    "adjustmentRenderTypes": "AdjustmentRenderTypes",
    "slowMotion/rate": "SlowMotionRate",
    "slowMotion/regions": "SlowMotionRegions",
    "slowMotion/regions/timeRange/duration/epoch": "SlowMotionRegionsDurationEpoch",
    "slowMotion/regions/timeRange/duration/flags": "SlowMotionRegionsDurationFlags",
    "slowMotion/regions/timeRange/duration/timescale": "SlowMotionRegionsDurationTimeScale",
    "slowMotion/regions/timeRange/duration/value": "SlowMotionRegionsDurationValue",
    "slowMotion/regions/timeRange/start/epoch": "SlowMotionRegionsStartTimeEpoch",
    "slowMotion/regions/timeRange/start/flags": "SlowMotionRegionsStartTimeFlags",
    "slowMotion/regions/timeRange/start/timescale": "SlowMotionRegionsStartTimeScale",
    "slowMotion/regions/timeRange/start/value": "SlowMotionRegionsStartTimeValue",
}


def _plist_group(plan: PlistTransactionPlan) -> str:
    return "XML" if plan.signature.encoding == "xml" else "PLIST"


def _plist_file_tags(source_file: str, plan: PlistTransactionPlan) -> list[ReadTag]:
    suffix = Path(source_file).suffix.lower()
    if suffix == ".aae":
        values = (
            ("FileType", "AAE", "FileType"),
            ("FileTypeExtension", "aae", "FileTypeExtension"),
            ("MIMEType", "application/vnd.apple.photos", "MIMEType"),
        )
    elif plan.signature.encoding == "binary":
        values = (
            ("FileType", "PLIST", "FileType"),
            ("FileTypeExtension", "plist", "FileTypeExtension"),
            ("MIMEType", "application/x-plist", "MIMEType"),
        )
    else:
        values = (
            ("FileType", "PLIST", "FileType"),
            ("FileTypeExtension", "plist", "FileTypeExtension"),
            ("MIMEType", "application/xml", "MIMEType"),
        )
    return [
        ReadTag(
            name=name,
            value=value,
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=tag_id,
                evidence_ids=(PLIST_MAIN_SOURCE,),
            ),
            schema=None,
        )
        for name, value, tag_id in values
    ]


def _coalesced_display_entries(
    entries: tuple[PlistDatabaseEntryPlan, ...],
    *,
    group: str,
) -> tuple[_PlistCoalescedDisplayEntry, ...]:
    coalesced: list[_PlistCoalescedDisplayEntry] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        run = [entry]
        cursor = index + 1
        while cursor < len(entries) and entries[cursor].tag_id == entry.tag_id:
            run.append(entries[cursor])
            cursor += 1
        if len(run) > 1:
            values = tuple(item.value for item in run)
            binary_list = _binary_data_list_value(values)
            value = (
                binary_list
                if binary_list is not None
                else _plist_display_value(_entry_with_list_value(entry, values).value, group=group)
            )
        else:
            value = _plist_display_value(entry.value, group=group)
        coalesced.append(_PlistCoalescedDisplayEntry(entry=entry, value=value))
        index = cursor
    return tuple(coalesced)


def _binary_data_list_value(values: tuple[PlistValuePlan, ...]) -> BinaryTagListValue | None:
    if not values or any(value.kind != "data" or value.raw_bytes is None for value in values):
        return None
    return BinaryTagListValue(
        tuple(
            BinaryTagValue(value.raw_bytes, file_extension="bin")
            for value in values
            if value.raw_bytes is not None
        )
    )


def _coalesced_entries(
    entries: tuple[PlistDatabaseEntryPlan, ...],
) -> tuple[PlistDatabaseEntryPlan, ...]:
    coalesced: list[PlistDatabaseEntryPlan] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        run = [entry]
        cursor = index + 1
        while cursor < len(entries) and entries[cursor].tag_id == entry.tag_id:
            run.append(entries[cursor])
            cursor += 1
        if len(run) > 1:
            coalesced.append(_entry_with_list_value(entry, tuple(item.value for item in run)))
        else:
            coalesced.append(entry)
        index = cursor
    return tuple(coalesced)


def _entry_with_list_value(
    entry: PlistDatabaseEntryPlan,
    values: tuple[PlistValuePlan, ...],
) -> PlistDatabaseEntryPlan:
    return PlistDatabaseEntryPlan(
        tag_id=entry.tag_id,
        generated_name=entry.generated_name,
        path_components=entry.path_components,
        value=PlistValuePlan(
            kind="array",
            display_value=[_plist_json_display_value(value) for value in values],
            raw_text=None,
            raw_bytes=None,
            byte_size=None,
            is_time_value=False,
            evidence_ids=entry.value.evidence_ids,
        ),
        list_candidate=entry.list_candidate,
        evidence_ids=entry.evidence_ids,
    )


def _plist_tag_name(entry: PlistDatabaseEntryPlan) -> str:
    return _PLIST_KNOWN_NAMES.get(entry.tag_id, entry.generated_name)


def _plist_display_value(
    value: PlistValuePlan,
    *,
    group: str,
) -> TagValue:
    if value.kind == "array" and isinstance(value.display_value, list):
        return [_plist_scalar_item(item) for item in value.display_value]
    if value.kind == "data" and value.raw_bytes is not None:
        return BinaryTagValue(value.raw_bytes)
    if value.kind == "date" and isinstance(value.display_value, str):
        return _render_plist_date(value.display_value, group=group)
    return _plist_scalar_item(value.display_value)


def _plist_json_display_value(value: PlistValuePlan) -> JsonValue:
    display = _plist_display_value(value, group="PLIST" if value.raw_text is None else "XML")
    if isinstance(display, BinaryTagValue | BinaryTagListValue):
        return f"(Binary data {display.byte_count} bytes, use -b option to extract)"
    if isinstance(display, list):
        return [_plist_scalar_item(item) for item in display]
    return display


def _plist_scalar_item(value: JsonValue) -> ScalarTagValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return json.dumps(value, sort_keys=True)


def _render_plist_date(value: str, *, group: str) -> str:
    if group == "XML" and value.endswith("Z"):
        return value.replace("-", ":").replace("T", " ")
    parsed = datetime.fromisoformat(value)
    local = parsed.astimezone(_LOCAL_TZ)
    return local.strftime("%Y:%m:%d %H:%M:%S%z")[:-2] + ":" + local.strftime("%z")[-2:]


def _nested_adjustment_data_tags(entry: PlistDatabaseEntryPlan, source_file: str) -> list[ReadTag]:
    if entry.tag_id != "adjustmentData" or entry.value.raw_bytes is None:
        return []
    nested_plan = build_plist_transaction_plan(entry.value.raw_bytes)
    tags: list[ReadTag] = []
    emitted_tag_ids: set[str] = set()
    for ordinal, nested_entry in enumerate(_coalesced_entries(nested_plan.database_entries)):
        emitted_tag_ids.add(nested_entry.tag_id)
        display = _plist_display_value(nested_entry.value, group="PLIST")
        if nested_entry.tag_id.endswith("/flags") and display == 1:
            display = "Valid"
        tags.append(
            ReadTag(
                name=_plist_tag_name(nested_entry),
                value=display,
                provenance=_provenance(
                    group="PLIST",
                    table_name="Image::ExifTool::PLIST::Main",
                    tag_id=nested_entry.tag_id,
                    evidence_ids=_nested_sources(nested_entry.evidence_ids),
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    if "slowMotion/regions" not in emitted_tag_ids and any(
        item.path == "slowMotion/regions" and item.kind == "array" for item in nested_plan.traversal
    ):
        rate_index = next(
            (index for index, tag in enumerate(tags) if tag.name == "SlowMotionRate"),
            len(tags),
        )
        tags.insert(
            rate_index,
            ReadTag(
                name="SlowMotionRegions",
                value=[],
                provenance=_provenance(
                    group="PLIST",
                    table_name="Image::ExifTool::PLIST::Main",
                    tag_id="slowMotion/regions",
                    evidence_ids=(PLIST_MAIN_SOURCE,),
                ),
                schema=None,
            ),
        )
    return tags


def _nested_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sources) if sources else (PLIST_MAIN_SOURCE,)


def invoke_plist(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_plist_read_graph(_read_plist_public_probe(path), source_file)


def _read_plist_public_probe(path: Path) -> bytes:
    # PLIST.pm peeks XML prefixes and seeks binary trailers/object tables.
    with path.open("rb") as file:
        return file.read(_PLIST_PUBLIC_READ_LIMIT)


_PLIST_BUILDER = "exifmodern.formats.plist:invoke_plist"

SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="plist/binary",
        builder_ref=_PLIST_BUILDER,
        patterns=(Pattern(0, b"bplist00"),),
    ),
    Signature(
        format_id="plist/xml",
        builder_ref=_PLIST_BUILDER,
        patterns=(Pattern(0, b"<?xml"),),
        preprocess=PreprocessKind.LSTRIP_WHITESPACE_AND_BOM,
    ),
)


install_evidence_reference_compat(globals())
