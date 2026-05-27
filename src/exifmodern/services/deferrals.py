"""Typed contracts for safe-expression surfaces deferred to platform services."""

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


@dataclass(frozen=True)
class ServiceDeferralContract:
    operation_id: str
    category: ServiceDeferralCategory
    service: str
    owner_module: str
    source: str
    required_capabilities: tuple[str, ...]
    implemented_primitives: tuple[str, ...]
    remaining_integration: tuple[str, ...]
    reason: str


def load_service_deferral_contracts(path: Path) -> tuple[ServiceDeferralContract, ...]:
    payload = load_json_object(path)
    return tuple(
        service_deferral_contract(entry)
        for entry_value in json_array_value(payload, "service_deferrals")
        for entry in [json_object_or_empty(entry_value)]
        if entry
    )


def service_deferral_contract(entry: JsonObject) -> ServiceDeferralContract:
    return ServiceDeferralContract(
        operation_id=required_string(entry, "operation_id"),
        category=service_deferral_category(required_string(entry, "category")),
        service=required_string(entry, "service"),
        owner_module=required_string(entry, "owner_module"),
        source=required_string(entry, "source"),
        required_capabilities=tuple(json_string_array_value(entry, "required_capabilities")),
        implemented_primitives=tuple(json_string_array_value(entry, "implemented_primitives")),
        remaining_integration=tuple(json_string_array_value(entry, "remaining_integration")),
        reason=required_string(entry, "reason"),
    )


def required_string(entry: JsonObject, key: str) -> str:
    value = json_string_value(entry, key)
    if value is None:
        raise ValueError(f"Service deferral entry missing required string field: {key}")
    return value


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


def contracts_by_category(
    contracts: tuple[ServiceDeferralContract, ...],
) -> dict[ServiceDeferralCategory, tuple[ServiceDeferralContract, ...]]:
    return {
        category: tuple(contract for contract in contracts if contract.category == category)
        for category in service_deferral_categories(contracts)
    }


def service_deferral_categories(
    contracts: tuple[ServiceDeferralContract, ...],
) -> tuple[ServiceDeferralCategory, ...]:
    seen: set[ServiceDeferralCategory] = set()
    categories: list[ServiceDeferralCategory] = []
    for contract in contracts:
        if contract.category in seen:
            continue
        seen.add(contract.category)
        categories.append(contract.category)
    return tuple(categories)
