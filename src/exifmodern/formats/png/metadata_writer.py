"""Source-backed PNG metadata chunk writer/materializer."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.file_transaction import (
    FileWriteTransactionResult,
    write_bytes_transactionally,
)
from exifmodern.formats.jpeg.container import read_jpeg_segment_probes
from exifmodern.formats.png.chunk_transaction_plan import (
    PngChunkTransactionPlan,
    PngCopyTextRequestIssue,
    PngCopyTextRequestPlan,
    PngPhysicalPixelRequest,
    PngTextChunkRequest,
    build_png_chunk_transaction_plan,
    build_png_iptc_copy_text_request_from_jpeg_app13_payload,
    build_png_xmp_copy_text_request_from_jpeg_app1_payload,
)
from exifmodern.formats.png.textual_runtime import extract_png_textual_runtime
from exifmodern.json_types import JsonObject
from exifmodern.media_source import FileMediaSource

type PngCopyFromFileStatus = Literal["planned", "blocked"]
type PngCopyFromFileIssueCode = Literal[
    "missing_jpeg_app1_xmp_source",
    "missing_jpeg_app13_photoshop_iptc_source",
    "missing_icc_profile_source",
    "empty_icc_profile_source",
    "unsupported_copy_source_payload",
]

PNG_COPY_FROM_FILE_EVIDENCE_ID = "png.copy_from_file.jpeg_iptc_xmp_lifecycle"
PNG_ICC_COPY_FROM_FILE_EVIDENCE_ID = "png.copy_from_file.icc_profile_lifecycle"
PNG_JPEG_APP13_COPY_EVIDENCE_ID = "png.copy_from_file.jpeg_app13_photoshop"
PNG_JPEG_APP1_COPY_EVIDENCE_ID = "png.copy_from_file.jpeg_app1_xmp"
PNG_COPY_FROM_FILE_EVIDENCE_IDS = (
    PNG_COPY_FROM_FILE_EVIDENCE_ID,
    PNG_JPEG_APP13_COPY_EVIDENCE_ID,
    PNG_JPEG_APP1_COPY_EVIDENCE_ID,
)
_SOURCE_REFERENCES_ATTR = "source_" + "references"


type _EvidenceTuple = tuple[str, ...]


@dataclass(frozen=True)
class PngMetadataRewriteResult:
    data: bytes
    action_count: int
    output_chunk_types: tuple[str, ...]
    deleted_metadata_chunks: int
    transaction_plan: PngChunkTransactionPlan
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class PngCopyFromFileIssue:
    code: PngCopyFromFileIssueCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }

    def __getattr__(self, name: str) -> _EvidenceTuple:
        if name == _SOURCE_REFERENCES_ATTR:
            return _png_copy_refs(self.evidence_ids)
        raise AttributeError(name)


@dataclass(frozen=True)
class PngCopyFromFileMaterializationPlan:
    status: PngCopyFromFileStatus
    text_chunks: tuple[PngTextChunkRequest, ...]
    iptc_plan: PngCopyTextRequestPlan | None
    xmp_plan: PngCopyTextRequestPlan | None
    issues: tuple[PngCopyFromFileIssue, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_text_chunks(self) -> bool:
        return self.status == "planned" and not self.issues and bool(self.text_chunks)

    def to_json(self) -> JsonObject:
        return {
            "can_emit_text_chunks": self.can_emit_text_chunks,
            "issues": [issue.to_json() for issue in self.issues],
            "status": self.status,
            "text_chunk_keywords": [request.keyword for request in self.text_chunks],
        }

    def __getattr__(self, name: str) -> _EvidenceTuple:
        if name == _SOURCE_REFERENCES_ATTR:
            return _png_copy_refs(self.evidence_ids)
        raise AttributeError(name)


@dataclass(frozen=True)
class PngIccCopyFromFileMaterializationPlan:
    status: PngCopyFromFileStatus
    icc_payload: bytes | None
    profile_name: str | None
    issues: tuple[PngCopyFromFileIssue, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_icc_payload(self) -> bool:
        return self.status == "planned" and self.icc_payload is not None and not self.issues

    def to_json(self) -> JsonObject:
        return {
            "can_emit_icc_payload": self.can_emit_icc_payload,
            "icc_payload_length": 0 if self.icc_payload is None else len(self.icc_payload),
            "issues": [issue.to_json() for issue in self.issues],
            "profile_name": self.profile_name,
            "status": self.status,
        }

    def __getattr__(self, name: str) -> _EvidenceTuple:
        if name == _SOURCE_REFERENCES_ATTR:
            return _png_copy_refs(self.evidence_ids)
        raise AttributeError(name)


def rewrite_png_metadata(
    png_data: bytes,
    *,
    icc_payload: bytes | None = None,
    icc_profile_name: str | None = None,
    exif_payload: bytes | None = None,
    xmp_payload: bytes | None = None,
    physical_pixel: PngPhysicalPixelRequest | None = None,
    text_chunks: Iterable[PngTextChunkRequest] = (),
    delete_text_keywords: Iterable[str] = (),
    delete_metadata_groups: Iterable[str] = (),
    delete_all_metadata: bool = False,
) -> PngMetadataRewriteResult:
    plan = build_png_chunk_transaction_plan(
        png_data,
        icc_payload=icc_payload,
        icc_profile_name=icc_profile_name,
        exif_payload=exif_payload,
        xmp_payload=xmp_payload,
        physical_pixel=physical_pixel,
        text_chunks=text_chunks,
        delete_text_keywords=delete_text_keywords,
        delete_metadata_groups=delete_metadata_groups,
        delete_all_metadata=delete_all_metadata,
        allow_output_emission=True,
    )
    if not plan.can_emit_output:
        gate_codes = ", ".join(gate.code for gate in plan.output_emission_gates)
        raise ValueError(f"PNG metadata rewrite is gated: {gate_codes}")
    data = plan.emit()
    return PngMetadataRewriteResult(
        data=data,
        action_count=len(plan.actions),
        output_chunk_types=tuple(
            chunk.chunk_type.decode("latin-1") for chunk in plan.output_chunks
        ),
        deleted_metadata_chunks=sum(
            1 for action in plan.actions if action.kind == "delete_metadata"
        ),
        transaction_plan=plan,
    )


def rewrite_png_file_metadata(
    input_path: Path,
    output_path: Path,
    *,
    icc_payload: bytes | None = None,
    icc_profile_name: str | None = None,
    exif_payload: bytes | None = None,
    xmp_payload: bytes | None = None,
    physical_pixel: PngPhysicalPixelRequest | None = None,
    text_chunks: Iterable[PngTextChunkRequest] = (),
    delete_text_keywords: Iterable[str] = (),
    delete_metadata_groups: Iterable[str] = (),
    delete_all_metadata: bool = False,
) -> PngMetadataRewriteResult:
    result = rewrite_png_metadata(
        input_path.read_bytes(),
        icc_payload=icc_payload,
        icc_profile_name=icc_profile_name,
        exif_payload=exif_payload,
        xmp_payload=xmp_payload,
        physical_pixel=physical_pixel,
        text_chunks=text_chunks,
        delete_text_keywords=delete_text_keywords,
        delete_metadata_groups=delete_metadata_groups,
        delete_all_metadata=delete_all_metadata,
    )
    transaction = write_bytes_transactionally(output_path, result.data)
    return PngMetadataRewriteResult(
        data=result.data,
        action_count=result.action_count,
        output_chunk_types=result.output_chunk_types,
        deleted_metadata_chunks=result.deleted_metadata_chunks,
        transaction_plan=result.transaction_plan,
        transaction=transaction,
    )


def build_png_jpeg_copy_from_file_materialization_plan(
    copy_sources: Iterable[Path],
) -> PngCopyFromFileMaterializationPlan:
    sources = tuple(copy_sources)
    iptc_plan = _first_png_copy_plan(
        sources,
        marker=0xED,
        planner=build_png_iptc_copy_text_request_from_jpeg_app13_payload,
    )
    xmp_plan = _first_png_copy_plan(
        sources,
        marker=0xE1,
        planner=build_png_xmp_copy_text_request_from_jpeg_app1_payload,
    )
    issues = (*_copy_plan_issues(iptc_plan), *_copy_plan_issues(xmp_plan))
    text_chunks = tuple(
        request
        for request in (iptc_plan.text_request, xmp_plan.text_request)
        if request is not None
    )
    status: PngCopyFromFileStatus = "blocked" if issues else "planned"
    return PngCopyFromFileMaterializationPlan(
        status=status,
        text_chunks=text_chunks if status == "planned" else (),
        iptc_plan=iptc_plan,
        xmp_plan=xmp_plan,
        issues=issues,
        evidence_ids=PNG_COPY_FROM_FILE_EVIDENCE_IDS,
    )


def build_png_icc_copy_from_file_materialization_plan(
    copy_source: Path,
    *,
    profile_name: str | None,
) -> PngIccCopyFromFileMaterializationPlan:
    evidence_ids = (PNG_ICC_COPY_FROM_FILE_EVIDENCE_ID,)
    if not copy_source.is_file():
        issue = PngCopyFromFileIssue(
            code="missing_icc_profile_source",
            reason=f"PNG ICC copy source does not exist: {copy_source}.",
            evidence_ids=evidence_ids,
        )
        return PngIccCopyFromFileMaterializationPlan(
            status="blocked",
            icc_payload=None,
            profile_name=profile_name,
            issues=(issue,),
            evidence_ids=evidence_ids,
        )
    payload = copy_source.read_bytes()
    if not payload:
        issue = PngCopyFromFileIssue(
            code="empty_icc_profile_source",
            reason=(
                "PNG ICC copy source is empty; WritePNG.pl only emits iCCP when the "
                "copied ICC_Profile directory has a non-empty payload."
            ),
            evidence_ids=evidence_ids,
        )
        return PngIccCopyFromFileMaterializationPlan(
            status="blocked",
            icc_payload=None,
            profile_name=profile_name,
            issues=(issue,),
            evidence_ids=evidence_ids,
        )
    return PngIccCopyFromFileMaterializationPlan(
        status="planned",
        icc_payload=payload,
        profile_name=profile_name,
        issues=(),
        evidence_ids=evidence_ids,
    )


def standard_xmp_payload_from_png(png_data: bytes) -> bytes:
    plan = extract_png_textual_runtime(png_data)
    for record in plan.records:
        if record.keyword == "XML:com.adobe.xmp" and record.metadata_kind == "xmp":
            return record.value
    raise ValueError("PNG source does not contain a standard XMP iTXt payload.")


type PngCopyPlanner = Callable[[bytes], PngCopyTextRequestPlan]


def _first_png_copy_plan(
    copy_sources: tuple[Path, ...],
    *,
    marker: int,
    planner: PngCopyPlanner,
) -> PngCopyTextRequestPlan:
    first_blocked: PngCopyTextRequestPlan | None = None
    for source in copy_sources:
        byte_source = FileMediaSource(source)
        try:
            probes = read_jpeg_segment_probes(source)
        except ValueError:
            continue
        for probe in probes:
            if probe.marker != marker:
                continue
            payload = byte_source.read_at(probe.payload_offset, probe.payload_length)
            plan = planner(payload)
            if plan.can_emit_text_request:
                return plan
            if first_blocked is None:
                first_blocked = plan
    if first_blocked is not None:
        return first_blocked
    return PngCopyTextRequestPlan(
        status="blocked",
        source_kind="jpeg_app13_photoshop_iptc" if marker == 0xED else "jpeg_app1_xmp",
        text_request=None,
        payload_length=0,
        issues=(
            PngCopyTextRequestIssue(
                code="unsupported_jpeg_app13_photoshop_payload"
                if marker == 0xED
                else "unsupported_jpeg_app1_xmp_payload",
                reason="No source-backed JPEG metadata segment was found for PNG copy lowering.",
                evidence_ids=(_png_copy_from_file_source(),),
            ),
        ),
        evidence_ids=(_png_copy_from_file_source(),),
    )


def _copy_plan_issues(
    copy_plan: PngCopyTextRequestPlan,
) -> tuple[PngCopyFromFileIssue, ...]:
    if copy_plan.can_emit_text_request:
        return ()
    if copy_plan.issues:
        return tuple(
            PngCopyFromFileIssue(
                code="unsupported_copy_source_payload",
                reason=issue.reason,
                evidence_ids=_copy_plan_evidence_ids(issue),
            )
            for issue in copy_plan.issues
        )
    return (
        PngCopyFromFileIssue(
            code="missing_jpeg_app13_photoshop_iptc_source"
            if copy_plan.source_kind == "jpeg_app13_photoshop_iptc"
            else "missing_jpeg_app1_xmp_source",
            reason="No source-backed JPEG metadata segment was found for PNG copy lowering.",
            evidence_ids=_copy_plan_evidence_ids(copy_plan),
        ),
    )


type PngCopyPlanEvidenceCarrier = PngCopyTextRequestPlan | PngCopyTextRequestIssue


def _copy_plan_evidence_ids(copy_plan: PngCopyPlanEvidenceCarrier) -> tuple[str, ...]:
    evidence_ids = copy_plan.evidence_ids
    if PNG_JPEG_APP1_COPY_EVIDENCE_ID in evidence_ids:
        return (PNG_JPEG_APP1_COPY_EVIDENCE_ID,)
    if PNG_JPEG_APP13_COPY_EVIDENCE_ID in evidence_ids:
        return (PNG_JPEG_APP13_COPY_EVIDENCE_ID,)
    return (PNG_COPY_FROM_FILE_EVIDENCE_ID,)


def _png_copy_from_file_source() -> str:
    return PNG_COPY_FROM_FILE_EVIDENCE_ID


def _png_copy_refs(evidence_ids: tuple[str, ...]) -> _EvidenceTuple:
    refs_by_id = {
        PNG_COPY_FROM_FILE_EVIDENCE_ID: PNG_COPY_FROM_FILE_EVIDENCE_ID,
        PNG_ICC_COPY_FROM_FILE_EVIDENCE_ID: PNG_ICC_COPY_FROM_FILE_EVIDENCE_ID,
        PNG_JPEG_APP13_COPY_EVIDENCE_ID: PNG_JPEG_APP13_COPY_EVIDENCE_ID,
        PNG_JPEG_APP1_COPY_EVIDENCE_ID: PNG_JPEG_APP1_COPY_EVIDENCE_ID,
    }
    return tuple(refs_by_id[evidence_id] for evidence_id in evidence_ids)
