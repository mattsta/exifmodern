"""JSON report helpers for DNG private-data writer plans."""

from __future__ import annotations

from collections.abc import Iterable

from exifmodern.json_types import JsonArray, JsonObject

type EvidenceId = str


def unique_evidence_ids(
    evidence_ids: tuple[EvidenceId, ...],
) -> tuple[EvidenceId, ...]:
    seen: set[EvidenceId] = set()
    unique_ids: list[EvidenceId] = []
    for evidence_id in evidence_ids:
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        unique_ids.append(evidence_id)
    return tuple(unique_ids)


def evidence_id_to_json(evidence_id: EvidenceId) -> JsonObject:
    return {"evidence_id": evidence_id}


def evidence_ids_to_json(references: tuple[EvidenceId, ...]) -> JsonArray:
    return [evidence_id_to_json(reference) for reference in references]


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return list(values)
