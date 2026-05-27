"""Typed diagnostics for data-package and VM runtime consumption state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import (
    JsonObject,
    json_array_value,
    json_bool_value,
    json_int_value,
    json_object_items,
    json_object_or_empty,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type DataRuntimeFamily = Literal["charset_language", "generated_index", "maker_note_database"]
type DataRuntimeState = Literal[
    "runtime_consumed",
    "stale_ledger_reconciliation",
    "active_handoff",
]


@dataclass(frozen=True)
class DataRuntimeFamilyStatus:
    family: DataRuntimeFamily
    state: DataRuntimeState
    ledger_record_count: int
    evidence_packaged_count: int
    evidence_runtime_consumed_count: int
    ledger_package_pending_count: int
    ledger_runtime_pending_count: int
    stale_package_pending_count: int
    stale_runtime_pending_count: int
    unreconciled_package_pending_count: int
    unreconciled_runtime_pending_count: int
    source_anchors: tuple[str, ...]
    capability_note: str


@dataclass(frozen=True)
class MakerNoteFeatureRuntimeStatus:
    reader_ready_count: int
    tag_entry_count: int
    domain_adapter_required_count: int

    @property
    def runtime_terminal(self) -> bool:
        return (
            self.tag_entry_count > 0
            and self.reader_ready_count == self.tag_entry_count
            and self.domain_adapter_required_count == 0
        )


@dataclass(frozen=True)
class SafeExpressionRuntimeStatus:
    expression_count: int
    compilable_expression_count: int
    remaining_expression_count: int
    actionable_remaining_expression_count: int
    domain_adapter_expression_count: int
    service_deferred_expression_count: int
    waived_expression_count: int

    @property
    def generic_vm_backlog_closed(self) -> bool:
        return self.actionable_remaining_expression_count == 0


@dataclass(frozen=True)
class DataVmRuntimeStatus:
    families: tuple[DataRuntimeFamilyStatus, ...]
    maker_note_features: MakerNoteFeatureRuntimeStatus
    safe_expressions: SafeExpressionRuntimeStatus

    @property
    def active_data_runtime_handoff_count(self) -> int:
        return sum(
            family.unreconciled_package_pending_count + family.unreconciled_runtime_pending_count
            for family in self.families
        )

    @property
    def stale_ledger_debt_count(self) -> int:
        return sum(
            family.stale_package_pending_count + family.stale_runtime_pending_count
            for family in self.families
        )

    @property
    def implementation_terminal(self) -> bool:
        return (
            self.active_data_runtime_handoff_count == 0
            and self.maker_note_features.runtime_terminal
            and self.safe_expressions.generic_vm_backlog_closed
        )


def load_data_vm_runtime_status(project_root: Path) -> DataVmRuntimeStatus:
    source_progress = load_json_object(
        project_root / "artifacts" / "metrics" / "exifmodern-source-progress.json"
    )
    maker_note_surface = load_json_object(
        project_root / "artifacts" / "database" / "makernote-feature-surface.json"
    )
    safe_expression_plan = load_json_object(
        project_root / "artifacts" / "operations" / "exiftool-safe-expression-plan.json"
    )
    return DataVmRuntimeStatus(
        families=load_data_runtime_family_statuses(source_progress),
        maker_note_features=load_maker_note_feature_runtime_status(maker_note_surface),
        safe_expressions=load_safe_expression_runtime_status(safe_expression_plan),
    )


def load_data_runtime_family_statuses(
    source_progress: JsonObject,
) -> tuple[DataRuntimeFamilyStatus, ...]:
    reconciliation = json_object_items(source_progress, "source_table_ledger_reconciliation")
    return tuple(
        data_runtime_family_status(entry)
        for value in json_array_value(reconciliation, "family_summaries")
        for entry in [json_object_or_empty(value)]
        if entry
    )


def data_runtime_family_status(entry: JsonObject) -> DataRuntimeFamilyStatus:
    stale_package = required_int(entry, "stale_package_pending_count")
    stale_runtime = required_int(entry, "stale_runtime_pending_count")
    unreconciled_package = required_int(entry, "unreconciled_package_pending_count")
    unreconciled_runtime = required_int(entry, "unreconciled_runtime_pending_count")
    return DataRuntimeFamilyStatus(
        family=data_runtime_family(required_string(entry, "family")),
        state=data_runtime_state(
            stale_package + stale_runtime,
            unreconciled_package + unreconciled_runtime,
            required_bool(entry, "runtime_terminal"),
        ),
        ledger_record_count=required_int(entry, "ledger_record_count"),
        evidence_packaged_count=required_int(entry, "evidence_packaged_count"),
        evidence_runtime_consumed_count=required_int(entry, "evidence_runtime_consumed_count"),
        ledger_package_pending_count=required_int(entry, "ledger_package_pending_count"),
        ledger_runtime_pending_count=required_int(entry, "ledger_runtime_pending_count"),
        stale_package_pending_count=stale_package,
        stale_runtime_pending_count=stale_runtime,
        unreconciled_package_pending_count=unreconciled_package,
        unreconciled_runtime_pending_count=unreconciled_runtime,
        source_anchors=tuple(json_string_array_value(entry, "source_anchors")),
        capability_note=required_string(entry, "capability_note"),
    )


def load_maker_note_feature_runtime_status(
    maker_note_surface: JsonObject,
) -> MakerNoteFeatureRuntimeStatus:
    summary = json_object_items(maker_note_surface, "summary")
    return MakerNoteFeatureRuntimeStatus(
        reader_ready_count=required_int(summary, "reader_ready_count"),
        tag_entry_count=required_int(summary, "tag_entry_count"),
        domain_adapter_required_count=required_int(summary, "domain_adapter_required_count"),
    )


def load_safe_expression_runtime_status(
    safe_expression_plan: JsonObject,
) -> SafeExpressionRuntimeStatus:
    return SafeExpressionRuntimeStatus(
        expression_count=required_int(safe_expression_plan, "expression_count"),
        compilable_expression_count=required_int(
            safe_expression_plan, "compilable_expression_count"
        ),
        remaining_expression_count=required_int(safe_expression_plan, "remaining_expression_count"),
        actionable_remaining_expression_count=required_int(
            safe_expression_plan,
            "actionable_remaining_expression_count",
        ),
        domain_adapter_expression_count=required_int(
            safe_expression_plan,
            "domain_adapter_expression_count",
        ),
        service_deferred_expression_count=required_int(
            safe_expression_plan,
            "service_deferred_expression_count",
        ),
        waived_expression_count=required_int(safe_expression_plan, "waived_expression_count"),
    )


def data_runtime_state(
    stale_pending_count: int,
    unreconciled_pending_count: int,
    runtime_terminal: bool,
) -> DataRuntimeState:
    if unreconciled_pending_count > 0:
        return "active_handoff"
    if stale_pending_count > 0:
        return "stale_ledger_reconciliation"
    if runtime_terminal:
        return "runtime_consumed"
    return "active_handoff"


def data_runtime_family(value: str) -> DataRuntimeFamily:
    if value == "charset_language":
        return "charset_language"
    if value == "generated_index":
        return "generated_index"
    if value == "maker_note_database":
        return "maker_note_database"
    raise ValueError(f"Unknown data runtime family: {value}")


def required_string(entry: JsonObject, key: str) -> str:
    value = json_string_value(entry, key)
    if value is None:
        raise ValueError(f"Runtime status missing required string field: {key}")
    return value


def required_int(entry: JsonObject, key: str) -> int:
    value = json_int_value(entry, key)
    if value is None:
        raise ValueError(f"Runtime status missing required integer field: {key}")
    return value


def required_bool(entry: JsonObject, key: str) -> bool:
    value = json_bool_value(entry, key)
    if value is None:
        raise ValueError(f"Runtime status missing required boolean field: {key}")
    return value
