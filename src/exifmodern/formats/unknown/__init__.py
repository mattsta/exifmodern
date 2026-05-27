"""Unknown maker-note metadata transaction planning public API."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.unknown.metadata_transaction_plan import (
    UnknownJpegReadReport,
    UnknownMetadataRewriteRequest,
    UnknownMetadataTransactionPlan,
    build_unknown_jpeg_read_report,
    build_unknown_jpeg_read_report_from_parsed_tiff,
    build_unknown_metadata_transaction_plan,
    plan_unknown_metadata_transaction,
)
from exifmodern.json_types import JsonObject

if TYPE_CHECKING:
    from exifmodern.formats.unknown.write_plan import UnknownWritePlan

__all__ = (
    "UnknownJpegReadReport",
    "UnknownMetadataRewriteRequest",
    "UnknownMetadataTransactionPlan",
    "UnknownWritePlan",
    "build_unknown_jpeg_read_report",
    "build_unknown_jpeg_read_report_from_parsed_tiff",
    "build_unknown_metadata_transaction_plan",
    "classify_unknown_write_request_file",
    "classify_unknown_write_request_payload",
    "plan_unknown_metadata_transaction",
)

_WRITE_PLAN_EXPORTS = {
    "UnknownWritePlan",
    "classify_unknown_write_request_file",
    "classify_unknown_write_request_payload",
}

type UnknownWritePlanClass = type[UnknownWritePlan]
type UnknownWritePlanFileClassifier = Callable[[Path], UnknownWritePlan]
type UnknownWritePlanPayloadClassifier = Callable[[JsonObject], UnknownWritePlan]
type UnknownLazyExport = (
    UnknownWritePlanClass | UnknownWritePlanFileClassifier | UnknownWritePlanPayloadClassifier
)


def __getattr__(name: str) -> UnknownLazyExport:
    if name not in _WRITE_PLAN_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from exifmodern.formats.unknown import write_plan

    if name == "UnknownWritePlan":
        return write_plan.UnknownWritePlan
    if name == "classify_unknown_write_request_file":
        return write_plan.classify_unknown_write_request_file
    if name == "classify_unknown_write_request_payload":
        return write_plan.classify_unknown_write_request_payload
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
