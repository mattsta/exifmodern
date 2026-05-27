"""Narrow executable RIFF/WAV and RIFF/AVI metadata deletion."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.riff.wav_metadata_transaction_plan import (
    RiffMetadataDeleteRequest,
    RiffWavMetadataTransactionPlan,
    build_wav_metadata_transaction_plan,
)


@dataclass(frozen=True)
class RiffWavMetadataRewriteResult:
    data: bytes
    deleted_metadata_chunks: int
    plan: RiffWavMetadataTransactionPlan


def delete_all_modeled_wav_metadata(riff_data: bytes) -> RiffWavMetadataRewriteResult:
    """Delete only complete top-level RIFF metadata chunks modeled by RIFF.pm."""

    plan = build_wav_metadata_transaction_plan(
        riff_data,
        delete_requests=(RiffMetadataDeleteRequest("all_metadata"),),
        allow_output_emission=True,
    )
    data = plan.emit()
    deleted_chunks = sum(
        1
        for chunk in plan.chunks
        if chunk.metadata_family in {"info", "riff_exif", "xmp", "id3", "c2pa"}
    )
    return RiffWavMetadataRewriteResult(
        data=data,
        deleted_metadata_chunks=deleted_chunks,
        plan=plan,
    )
