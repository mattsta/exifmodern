"""Composed JPEG legacy APP metadata writer.

The contained plans stay table-local in Canon CIFF and Kodak Meta modules; this
boundary only coordinates their separate APP segment mutations for one JPEG.
"""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.canon.ciff_write_plan import CiffWritePlan
from exifmodern.formats.jpeg.ciff_writer import rewrite_jpeg_ciff
from exifmodern.formats.jpeg.kodak_meta_writer import rewrite_jpeg_kodak_meta
from exifmodern.formats.kodak.meta_write_plan import KodakMetaWritePlan


@dataclass(frozen=True)
class LegacyAppMetadataWritePlan:
    ciff_plan: CiffWritePlan | None
    kodak_meta_plan: KodakMetaWritePlan | None

    @property
    def step_count(self) -> int:
        ciff_count = 0 if self.ciff_plan is None else len(self.ciff_plan.steps)
        kodak_meta_count = 0 if self.kodak_meta_plan is None else len(self.kodak_meta_plan.steps)
        return ciff_count + kodak_meta_count


@dataclass(frozen=True)
class JpegLegacyAppMetadataRewriteResult:
    data: bytes
    changed_tags: int


def rewrite_jpeg_legacy_app_metadata(
    jpeg_data: bytes,
    plan: LegacyAppMetadataWritePlan,
) -> JpegLegacyAppMetadataRewriteResult:
    rewritten = jpeg_data
    changed_tags = 0
    if plan.kodak_meta_plan is not None:
        kodak_result = rewrite_jpeg_kodak_meta(rewritten, plan.kodak_meta_plan)
        rewritten = kodak_result.data
        changed_tags += kodak_result.changed_tags
    if plan.ciff_plan is not None:
        ciff_result = rewrite_jpeg_ciff(rewritten, plan.ciff_plan)
        rewritten = ciff_result.data
        changed_tags += ciff_result.changed_tags
    return JpegLegacyAppMetadataRewriteResult(rewritten, changed_tags)
