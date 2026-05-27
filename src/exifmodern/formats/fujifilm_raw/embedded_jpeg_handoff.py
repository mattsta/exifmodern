"""RAF-local handoff from FujiFilm embedded JPEG bytes to JPEG metadata writers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.exif_scalar_write_plan import (
    ExifScalarWritePlan,
    ExifScalarWriteStep,
    user_comment_step,
)
from exifmodern.formats.jpeg.exif_scalar_writer import rewrite_jpeg_exif_scalars_creating_if_needed

type FujiFilmRafJpegHandoffDiagnosticReason = Literal[
    "embedded_jpeg_range_unavailable",
    "invalid_embedded_jpeg",
    "invalid_value",
    "unsupported_write_arg",
]

FUJIFILM_RAF_JPEG_HANDOFF_EVIDENCE_ID = "fujifilm_raw.raf.jpeg_handoff"
FUJIFILM_RAF_WRITE_JPEG_EVIDENCE_ID = "fujifilm_raw.raf.write_jpeg"
FUJIFILM_RAF_USER_COMMENT_TEST_EVIDENCE_ID = "fujifilm_raw.raf.user_comment_test"


@dataclass(frozen=True)
class FujiFilmRafJpegHandoffDiagnostic:
    reason: FujiFilmRafJpegHandoffDiagnosticReason
    detail: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FujiFilmRafEmbeddedJpegMetadataRewriteResult:
    output_bytes: bytes | None
    diagnostics: tuple[FujiFilmRafJpegHandoffDiagnostic, ...]
    evidence_ids: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.output_bytes is not None and not self.diagnostics


def rewrite_raf_embedded_jpeg_metadata_from_write_args(
    raf_data: bytes,
    jpeg_offset: int,
    jpeg_length: int,
    write_args: tuple[str, ...],
) -> FujiFilmRafEmbeddedJpegMetadataRewriteResult:
    """Rewrite the embedded RAF JPEG for the source-backed FujiFilm.t test-5 shape."""

    diagnostics: list[FujiFilmRafJpegHandoffDiagnostic] = []
    if jpeg_offset < 0 or jpeg_length <= 0 or jpeg_offset + jpeg_length > len(raf_data):
        return FujiFilmRafEmbeddedJpegMetadataRewriteResult(
            output_bytes=None,
            diagnostics=(
                FujiFilmRafJpegHandoffDiagnostic(
                    reason="embedded_jpeg_range_unavailable",
                    detail="WriteRAF must read the complete embedded JPEG before WriteJPEG.",
                    evidence_ids=(FUJIFILM_RAF_JPEG_HANDOFF_EVIDENCE_ID,),
                ),
            ),
            evidence_ids=(
                FUJIFILM_RAF_JPEG_HANDOFF_EVIDENCE_ID,
                FUJIFILM_RAF_WRITE_JPEG_EVIDENCE_ID,
            ),
        )

    embedded_jpeg = raf_data[jpeg_offset : jpeg_offset + jpeg_length]
    if not embedded_jpeg.startswith(b"\xff\xd8"):
        return FujiFilmRafEmbeddedJpegMetadataRewriteResult(
            output_bytes=None,
            diagnostics=(
                FujiFilmRafJpegHandoffDiagnostic(
                    reason="invalid_embedded_jpeg",
                    detail="WriteJPEG requires the embedded RAF metadata payload to be a JPEG.",
                    evidence_ids=(
                        FUJIFILM_RAF_JPEG_HANDOFF_EVIDENCE_ID,
                        FUJIFILM_RAF_WRITE_JPEG_EVIDENCE_ID,
                    ),
                ),
            ),
            evidence_ids=(
                FUJIFILM_RAF_JPEG_HANDOFF_EVIDENCE_ID,
                FUJIFILM_RAF_WRITE_JPEG_EVIDENCE_ID,
            ),
        )

    plan_steps: list[ExifScalarWriteStep] = []
    for write_arg in write_args:
        if not write_arg.startswith("-") or "=" not in write_arg:
            continue
        tag_token, value = write_arg[1:].split("=", 1)
        if tag_token in {"UserComment", "EXIF:UserComment"}:
            try:
                plan_steps.append(user_comment_step(value))
            except ValueError as error:
                diagnostics.append(
                    FujiFilmRafJpegHandoffDiagnostic(
                        reason="invalid_value",
                        detail=str(error),
                        evidence_ids=(FUJIFILM_RAF_USER_COMMENT_TEST_EVIDENCE_ID,),
                    )
                )
            continue
        diagnostics.append(
            FujiFilmRafJpegHandoffDiagnostic(
                reason="unsupported_write_arg",
                detail=(
                    "RAF embedded JPEG handoff currently supports the source-backed "
                    "FujiFilm.t UserComment write shape only."
                ),
                evidence_ids=(FUJIFILM_RAF_USER_COMMENT_TEST_EVIDENCE_ID,),
            )
        )

    if diagnostics or not plan_steps:
        return FujiFilmRafEmbeddedJpegMetadataRewriteResult(
            output_bytes=None,
            diagnostics=tuple(diagnostics)
            or (
                FujiFilmRafJpegHandoffDiagnostic(
                    reason="unsupported_write_arg",
                    detail="No source-backed RAF embedded JPEG write arguments were provided.",
                    evidence_ids=(FUJIFILM_RAF_USER_COMMENT_TEST_EVIDENCE_ID,),
                ),
            ),
            evidence_ids=(
                FUJIFILM_RAF_JPEG_HANDOFF_EVIDENCE_ID,
                FUJIFILM_RAF_WRITE_JPEG_EVIDENCE_ID,
                FUJIFILM_RAF_USER_COMMENT_TEST_EVIDENCE_ID,
            ),
        )

    rewritten = rewrite_jpeg_exif_scalars_creating_if_needed(
        embedded_jpeg,
        ExifScalarWritePlan(tuple(plan_steps)),
    ).data
    return FujiFilmRafEmbeddedJpegMetadataRewriteResult(
        output_bytes=rewritten,
        diagnostics=(),
        evidence_ids=(
            FUJIFILM_RAF_JPEG_HANDOFF_EVIDENCE_ID,
            FUJIFILM_RAF_WRITE_JPEG_EVIDENCE_ID,
            FUJIFILM_RAF_USER_COMMENT_TEST_EVIDENCE_ID,
        ),
    )
