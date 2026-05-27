"""Typed handoff queue for safe-expression operations deferred to runtime services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import (
    JsonObject,
    json_array_value,
    json_object_or_empty,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type ServiceDeferralCategory = Literal[
    "file_backed_read_service",
    "file_backed_rebuild_service",
    "geotag_write_side_service",
    "lens_identity_table_service",
]
type ServiceDeferralLane = Literal["reader_runtime", "writer_runtime", "package_runtime"]


@dataclass(frozen=True)
class ServiceDeferralHandoff:
    operation_id: str
    category: ServiceDeferralCategory
    lane: ServiceDeferralLane
    service: str
    owner_module: str
    source: str
    required_capabilities: tuple[str, ...]
    implemented_primitives: tuple[str, ...]
    remaining_integration: tuple[str, ...]
    reason: str

    @property
    def primitive_boundary_exists(self) -> bool:
        return bool(self.implemented_primitives)


@dataclass(frozen=True)
class ServiceDeferralQueue:
    handoffs: tuple[ServiceDeferralHandoff, ...]

    @property
    def reader_runtime_count(self) -> int:
        return sum(1 for handoff in self.handoffs if handoff.lane == "reader_runtime")

    @property
    def writer_runtime_count(self) -> int:
        return sum(1 for handoff in self.handoffs if handoff.lane == "writer_runtime")

    @property
    def package_runtime_count(self) -> int:
        return sum(1 for handoff in self.handoffs if handoff.lane == "package_runtime")

    @property
    def all_have_primitive_boundaries(self) -> bool:
        return all(handoff.primitive_boundary_exists for handoff in self.handoffs)

    def for_lane(self, lane: ServiceDeferralLane) -> tuple[ServiceDeferralHandoff, ...]:
        return tuple(handoff for handoff in self.handoffs if handoff.lane == lane)


def load_service_deferral_queue(path: Path) -> ServiceDeferralQueue:
    payload = load_json_object(path)
    return ServiceDeferralQueue(
        handoffs=tuple(
            service_deferral_handoff(entry)
            for value in json_array_value(payload, "service_deferrals")
            for entry in [json_object_or_empty(value)]
            if entry
        )
    )


def service_deferral_handoff(entry: JsonObject) -> ServiceDeferralHandoff:
    category = service_deferral_category(required_string(entry, "category"))
    return ServiceDeferralHandoff(
        operation_id=required_string(entry, "operation_id"),
        category=category,
        lane=service_deferral_lane(category),
        service=required_string(entry, "service"),
        owner_module=required_string(entry, "owner_module"),
        source=required_string(entry, "source"),
        required_capabilities=tuple(json_string_array_value(entry, "required_capabilities")),
        implemented_primitives=tuple(json_string_array_value(entry, "implemented_primitives")),
        remaining_integration=tuple(json_string_array_value(entry, "remaining_integration")),
        reason=required_string(entry, "reason"),
    )


def service_deferral_lane(category: ServiceDeferralCategory) -> ServiceDeferralLane:
    if category == "file_backed_read_service":
        return "reader_runtime"
    if category == "file_backed_rebuild_service":
        return "reader_runtime"
    if category == "geotag_write_side_service":
        return "writer_runtime"
    if category == "lens_identity_table_service":
        return "package_runtime"
    raise ValueError(f"Unknown service deferral category: {category}")


def service_deferral_category(value: str) -> ServiceDeferralCategory:
    if value == "file_backed_read_service":
        return "file_backed_read_service"
    if value == "file_backed_rebuild_service":
        return "file_backed_rebuild_service"
    if value == "geotag_write_side_service":
        return "geotag_write_side_service"
    if value == "lens_identity_table_service":
        return "lens_identity_table_service"
    raise ValueError(f"Unknown service deferral category: {value}")


def required_string(entry: JsonObject, key: str) -> str:
    value = json_string_value(entry, key)
    if value is None:
        raise ValueError(f"Service deferral missing required string field: {key}")
    return value
