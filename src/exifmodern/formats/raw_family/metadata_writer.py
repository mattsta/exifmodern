"""Non-mutating RAW-family metadata writer guard."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.raw_family.write_plan import (
    RawFamilyWriteRequestClassification,
    classify_raw_family_golden_request_payload,
)
from exifmodern.json_types import JsonObject


class RawFamilyRewriteDeferred(RuntimeError):
    """Raised when a RAW-family write request is source-mapped but not safely writable."""


@dataclass(frozen=True)
class RawFamilyMetadataWriteAnalysis:
    original_size: int
    classification: RawFamilyWriteRequestClassification

    @property
    def can_rewrite(self) -> bool:
        return self.classification.can_rewrite


def analyze_raw_family_metadata_write(
    data: bytes,
    payload: JsonObject,
) -> RawFamilyMetadataWriteAnalysis:
    return RawFamilyMetadataWriteAnalysis(
        original_size=len(data),
        classification=classify_raw_family_golden_request_payload(payload),
    )


def require_supported_raw_family_rewrite(
    classification: RawFamilyWriteRequestClassification,
) -> None:
    if classification.can_rewrite:
        return
    raise RawFamilyRewriteDeferred(deferred_message(classification))


def deferred_message(classification: RawFamilyWriteRequestClassification) -> str:
    blockers = "; ".join(classification.blockers)
    return (
        f"{classification.fixture} write is classified as {classification.status} "
        f"for {classification.container}. Blockers: {blockers}"
    )
