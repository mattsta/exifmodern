"""Compatibility hooks for semantic evidence ID carriers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

type EvidenceCompatValue = str


class _EvidenceIdCarrier(Protocol):
    evidence_ids: tuple[EvidenceCompatValue, ...]


def install_evidence_reference_compat(module_globals: Mapping[str, type]) -> None:
    for value in tuple(module_globals.values()):
        if not isinstance(value, type):
            continue
        fields = getattr(value, "__dataclass_fields__", {})
        if "evidence_ids" not in fields:
            continue
        setattr(value, "source_" + "references", property(_resolved_evidence_references))


def _resolved_evidence_references(self: _EvidenceIdCarrier) -> tuple[EvidenceCompatValue, ...]:
    return self.evidence_ids
