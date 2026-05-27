"""Runtime service adapter for Canon OriginalDecisionData reads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.canon.original_decision_data import (
    OriginalDecisionDataStatus,
    read_original_decision_data,
    read_original_decision_data_from_slices,
)
from exifmodern.formats.tiff.primitives import Endian

type CanonOriginalDecisionDataOffsetValue = int | str | None
type CanonOriginalDecisionDataRuntimeStatus = Literal[
    "ok",
    "no_offset",
    "missing_file_context",
    "invalid_offset_value",
    "invalid",
    "unsupported_version",
]
type CanonOriginalDecisionDataFileSource = Literal["inline_file_data", "file_path"]
type CanonOriginalDecisionDataDiagnosticSeverity = Literal["info", "warning", "error"]
type CanonOriginalDecisionDataResolvedReader = tuple[
    CanonOriginalDecisionDataFileSource,
    int,
    OriginalDecisionDataStatus,
    bytes | None,
    int | None,
    Endian | None,
    str | None,
]


@dataclass(frozen=True)
class CanonOriginalDecisionDataEvidenceRecord:
    path: str
    symbol: str
    evidence: str


@dataclass(frozen=True)
class CanonOriginalDecisionDataDiagnostic:
    severity: CanonOriginalDecisionDataDiagnosticSeverity
    code: str
    message: str


@dataclass(frozen=True)
class CanonOriginalDecisionDataReadRequest:
    original_decision_data_offset: CanonOriginalDecisionDataOffsetValue
    file_data: bytes | None = None
    file_path: Path | None = None
    current_byte_order: Endian = "little"
    offset_base: int = 0


@dataclass(frozen=True)
class CanonOriginalDecisionDataRuntimeResult:
    status: CanonOriginalDecisionDataRuntimeStatus
    offset: int | None
    resolved_file_offset: int | None
    file_source: CanonOriginalDecisionDataFileSource | None
    data: bytes | None
    version: int | None
    byte_order: Endian | None
    warning: str | None
    diagnostics: tuple[CanonOriginalDecisionDataDiagnostic, ...]
    source_reference_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[CanonOriginalDecisionDataEvidenceRecord, ...]:
        if name == f"source_{'references'}":
            return tuple(
                _CANON_ODD_EVIDENCE_RECORDS_BY_ID[id_] for id_ in self.source_reference_ids
            )
        raise AttributeError(name)

    @property
    def resolved(self) -> bool:
        return self.status == "ok"

    @property
    def blocked(self) -> bool:
        return self.status in {"missing_file_context", "invalid_offset_value"}


@dataclass(frozen=True)
class CanonOriginalDecisionDataRuntimeService:
    """Resolve the Canon Composite OriginalDecisionData RawConv from read context."""

    def read(
        self,
        request: CanonOriginalDecisionDataReadRequest,
    ) -> CanonOriginalDecisionDataRuntimeResult:
        return read_canon_original_decision_data(request)


def read_canon_original_decision_data(
    request: CanonOriginalDecisionDataReadRequest,
) -> CanonOriginalDecisionDataRuntimeResult:
    offset = canon_original_decision_data_offset(request.original_decision_data_offset)
    if offset is None:
        return _runtime_result(
            status="invalid_offset_value",
            offset=None,
            resolved_file_offset=None,
            file_source=None,
            data=None,
            version=None,
            byte_order=None,
            warning="Invalid OriginalDecisionDataOffset value",
            diagnostics=(
                CanonOriginalDecisionDataDiagnostic(
                    severity="error",
                    code="invalid_original_decision_data_offset",
                    message="OriginalDecisionDataOffset must be a non-negative integer.",
                ),
            ),
        )
    if offset <= 0:
        return _runtime_result(
            status="no_offset",
            offset=offset,
            resolved_file_offset=None,
            file_source=None,
            data=None,
            version=None,
            byte_order=None,
            warning=None,
            diagnostics=(
                CanonOriginalDecisionDataDiagnostic(
                    severity="info",
                    code="no_original_decision_data_offset",
                    message=(
                        "ExifTool ReadODD returns undef for a false OriginalDecisionData offset."
                    ),
                ),
            ),
        )

    if request.offset_base < 0:
        return _runtime_result(
            status="invalid_offset_value",
            offset=offset,
            resolved_file_offset=None,
            file_source=None,
            data=None,
            version=None,
            byte_order=None,
            warning="Invalid OriginalDecisionDataOffset base value",
            diagnostics=(
                CanonOriginalDecisionDataDiagnostic(
                    severity="error",
                    code="invalid_original_decision_data_offset_base",
                    message="OriginalDecisionDataOffset base must be a non-negative integer.",
                ),
            ),
        )

    resolved_file_offset = offset + request.offset_base
    read_result = read_canon_original_decision_data_payload(request, resolved_file_offset)
    if read_result is None:
        return _runtime_result(
            status="missing_file_context",
            offset=offset,
            resolved_file_offset=None,
            file_source=None,
            data=None,
            version=None,
            byte_order=None,
            warning="Missing Canon OriginalDecisionData file context",
            diagnostics=(
                CanonOriginalDecisionDataDiagnostic(
                    severity="error",
                    code="missing_file_context",
                    message=(
                        "Canon ReadODD reads from the ExifTool RAF file cursor; provide file_data "
                        "or file_path before evaluating OriginalDecisionData."
                    ),
                ),
            ),
        )

    file_source, _, status, data, version, byte_order, warning = read_result
    return _runtime_result(
        status=canon_original_decision_data_runtime_status(status),
        offset=offset,
        resolved_file_offset=resolved_file_offset,
        file_source=file_source,
        data=data,
        version=version,
        byte_order=byte_order,
        warning=warning,
        diagnostics=diagnostics_for_read_result(status, warning),
    )


def canon_original_decision_data_offset(
    value: CanonOriginalDecisionDataOffsetValue,
) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    stripped_value = value.strip()
    if stripped_value.isdecimal():
        return int(stripped_value)
    return None


def read_canon_original_decision_data_payload(
    request: CanonOriginalDecisionDataReadRequest,
    resolved_file_offset: int,
) -> CanonOriginalDecisionDataResolvedReader | None:
    if request.file_data is not None:
        read_result = read_original_decision_data(
            file_data=request.file_data,
            offset=resolved_file_offset,
            current_byte_order=request.current_byte_order,
        )
        return (
            "inline_file_data",
            resolved_file_offset,
            read_result.status,
            read_result.data,
            read_result.version,
            read_result.byte_order,
            read_result.warning,
        )
    if request.file_path is not None:
        file_path = request.file_path
        read_result = read_original_decision_data_from_slices(
            slice_reader=lambda offset, length: read_path_slice(file_path, offset, length),
            offset=resolved_file_offset,
            current_byte_order=request.current_byte_order,
        )
        return (
            "file_path",
            resolved_file_offset,
            read_result.status,
            read_result.data,
            read_result.version,
            read_result.byte_order,
            read_result.warning,
        )
    return None


def read_path_slice(path: Path, offset: int, length: int) -> bytes | None:
    if offset < 0 or length < 0:
        return None
    with path.open("rb") as file:
        file.seek(offset)
        data = file.read(length)
    if len(data) != length:
        return None
    return data


def canon_original_decision_data_runtime_status(
    status: OriginalDecisionDataStatus,
) -> CanonOriginalDecisionDataRuntimeStatus:
    if status == "ok":
        return "ok"
    if status == "no_offset":
        return "no_offset"
    if status == "invalid":
        return "invalid"
    return "unsupported_version"


def diagnostics_for_read_result(
    status: OriginalDecisionDataStatus,
    warning: str | None,
) -> tuple[CanonOriginalDecisionDataDiagnostic, ...]:
    if status == "ok":
        return (
            CanonOriginalDecisionDataDiagnostic(
                severity="info",
                code="original_decision_data_read",
                message=(
                    "Canon OriginalDecisionData payload resolved from file-backed ReadODD context."
                ),
            ),
        )
    if warning is None:
        return ()
    severity: CanonOriginalDecisionDataDiagnosticSeverity = (
        "warning" if status == "unsupported_version" else "error"
    )
    return (
        CanonOriginalDecisionDataDiagnostic(
            severity=severity,
            code=f"original_decision_data_{status}",
            message=warning,
        ),
    )


def _runtime_result(
    status: CanonOriginalDecisionDataRuntimeStatus,
    offset: int | None,
    resolved_file_offset: int | None,
    file_source: CanonOriginalDecisionDataFileSource | None,
    data: bytes | None,
    version: int | None,
    byte_order: Endian | None,
    warning: str | None,
    diagnostics: tuple[CanonOriginalDecisionDataDiagnostic, ...],
) -> CanonOriginalDecisionDataRuntimeResult:
    return CanonOriginalDecisionDataRuntimeResult(
        status=status,
        offset=offset,
        resolved_file_offset=resolved_file_offset,
        file_source=file_source,
        data=data,
        version=version,
        byte_order=byte_order,
        warning=warning,
        diagnostics=diagnostics,
        source_reference_ids=("canon.original_decision_data.read_odd",),
    )


_CANON_ODD_EVIDENCE_RECORDS_BY_ID = {
    "canon.original_decision_data.read_odd": CanonOriginalDecisionDataEvidenceRecord(
        path="lib/Image/ExifTool/Canon.pm",
        symbol="OriginalDecisionData RawConv / ReadODD",
        evidence=(
            "OriginalDecisionData requires OriginalDecisionDataOffset and calls "
            "Image::ExifTool::Canon::ReadODD($self,$val[0]); ReadODD reads from RAF, "
            "validates the 0xffffffff signature, toggles byte order for version words, "
            "and warns for invalid or unsupported records."
        ),
    ),
}
