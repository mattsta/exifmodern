"""Source-backed Portable FloatMap reader plan."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

type PfmReaderStatus = Literal["planned", "unsupported"]
type PfmDiagnosticCode = Literal["invalid_pfm_header"]

PFM_SOURCE = "pfm"
PFM_COMPOSITE_SOURCE = "pfm_composite"

_PFM_HEADER_RE = re.compile(rb"^(P[Ff])\x0a(\d+) (\d+)\x0a([-+0-9.]+)\x0a")


@dataclass(frozen=True)
class PfmDiagnostic:
    code: PfmDiagnosticCode
    detail: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PfmReadTag:
    name: str
    value: str | int | float
    group: str
    source_table: str
    tag_id: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PfmReaderPlan:
    status: PfmReaderStatus
    tags: tuple[PfmReadTag, ...]
    diagnostics: tuple[PfmDiagnostic, ...]
    evidence_ids: tuple[str, ...]


def build_pfm_reader_plan(data: bytes) -> PfmReaderPlan:
    match = _PFM_HEADER_RE.match(data[:256])
    if match is None:
        return PfmReaderPlan(
            status="unsupported",
            tags=(),
            diagnostics=(
                PfmDiagnostic(
                    code="invalid_pfm_header",
                    detail=(
                        "ProcessPFM2 requires PF/Pf, dimensions, and scale in the first 256 bytes."
                    ),
                    evidence_ids=(PFM_SOURCE,),
                ),
            ),
            evidence_ids=(PFM_SOURCE,),
        )
    marker = match.group(1).decode("ascii")
    width = int(match.group(2))
    height = int(match.group(3))
    scale = float(match.group(4).decode("ascii"))
    tags = (
        PfmReadTag(
            "FileType", "PFM", "File", "Image::ExifTool::Other::PFM", "FileType", (PFM_SOURCE,)
        ),
        PfmReadTag(
            "FileTypeExtension",
            "pfm",
            "File",
            "Image::ExifTool::Other::PFM",
            "FileTypeExtension",
            (PFM_SOURCE,),
        ),
        PfmReadTag(
            "MIMEType",
            "image/x-pfm",
            "File",
            "Image::ExifTool::Other::PFM",
            "MIMEType",
            (PFM_SOURCE,),
        ),
        PfmReadTag(
            "ColorSpace",
            "RGB" if marker == "PF" else "Monochrome",
            "File",
            "Image::ExifTool::Other::PFM",
            "ColorSpace",
            (PFM_SOURCE,),
        ),
        PfmReadTag(
            "ImageWidth", width, "File", "Image::ExifTool::Other::PFM", "ImageWidth", (PFM_SOURCE,)
        ),
        PfmReadTag(
            "ImageHeight",
            height,
            "File",
            "Image::ExifTool::Other::PFM",
            "ImageHeight",
            (PFM_SOURCE,),
        ),
        PfmReadTag(
            "ByteOrder",
            "Big-endian" if scale > 0 else "Little-endian",
            "File",
            "Image::ExifTool::Other::PFM",
            "ByteOrder",
            (PFM_SOURCE,),
        ),
        PfmReadTag(
            "ImageSize",
            f"{width}x{height}",
            "Composite",
            "Composite",
            "Exif-ImageSize",
            (PFM_COMPOSITE_SOURCE,),
        ),
        PfmReadTag(
            "Megapixels",
            float(f"{width * height / 1_000_000:.3g}"),
            "Composite",
            "Composite",
            "Exif-Megapixels",
            (PFM_COMPOSITE_SOURCE,),
        ),
    )
    return PfmReaderPlan(
        status="planned",
        tags=tags,
        diagnostics=(),
        evidence_ids=(PFM_SOURCE, PFM_COMPOSITE_SOURCE),
    )
