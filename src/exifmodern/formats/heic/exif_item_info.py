"""HEIC ItemInfo EXIF payload handoff planning.

ExifTool's HEIC ItemInfo writer does not mutate EXIF bytes directly in the
QuickTime layer.  It peels off the HEIC EXIF item header, delegates the TIFF
directory to ``WriteTIFF``, then schedules the returned payload as an ``mdat``
replacement.  This module models that byte boundary without inventing TIFF
rewrite output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HEIC_EXIF_ITEM_TYPE = "Exif"
HEIC_EXIF_EMPTY_HEADER = b"\0\0\0\x06Exif\0\0"
TIFF_BIG_ENDIAN_HEADER = b"MM\0\x2a"
TIFF_LITTLE_ENDIAN_HEADER = b"II\x2a\0"

type HeicExifItemOperation = Literal[
    "create_exif_item",
    "rewrite_existing_exif_item",
    "delete_existing_exif_item",
]
type HeicExifTiffHandoffStatus = Literal[
    "ready_for_tiff_handoff",
    "empty_exif_create",
    "missing_exif_header_tiff_at_start",
    "invalid_exif_header",
]
type HeicExifTiffHandoffBlockerCode = Literal[
    "invalid_exif_header",
    "tiff_rewrite_not_implemented",
]

HEIC_EXIF_TIFF_HANDOFF_EVIDENCE_ID = "heic.exif_item_info.tiff_handoff"
HEIC_EXIF_TIFF_RESULT_EVIDENCE_ID = "heic.exif_item_info.tiff_result"


@dataclass(frozen=True)
class HeicExifTiffHandoffPlan:
    operation: HeicExifItemOperation
    status: HeicExifTiffHandoffStatus
    input_length: int
    header: bytes
    tiff_payload: bytes
    dir_start: int
    dir_length: int
    warning: str | None
    blocker_codes: tuple[HeicExifTiffHandoffBlockerCode, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_handoff_to_tiff(self) -> bool:
        return self.status != "invalid_exif_header"

    @property
    def needs_tiff_rewrite(self) -> bool:
        return "tiff_rewrite_not_implemented" in self.blocker_codes


def plan_heic_exif_tiff_handoff(
    exif_payload: bytes,
    *,
    operation: HeicExifItemOperation,
) -> HeicExifTiffHandoffPlan:
    """Parse the HEIC EXIF item envelope before a future WriteTIFF-equivalent call."""

    if not exif_payload:
        return HeicExifTiffHandoffPlan(
            operation=operation,
            status="empty_exif_create",
            input_length=0,
            header=HEIC_EXIF_EMPTY_HEADER,
            tiff_payload=b"",
            dir_start=0,
            dir_length=0,
            warning=None,
            blocker_codes=("tiff_rewrite_not_implemented",),
            evidence_ids=(HEIC_EXIF_TIFF_HANDOFF_EVIDENCE_ID,),
        )
    if exif_payload.startswith(TIFF_BIG_ENDIAN_HEADER) or exif_payload.startswith(
        TIFF_LITTLE_ENDIAN_HEADER
    ):
        return HeicExifTiffHandoffPlan(
            operation=operation,
            status="missing_exif_header_tiff_at_start",
            input_length=len(exif_payload),
            header=b"",
            tiff_payload=exif_payload,
            dir_start=0,
            dir_length=len(exif_payload),
            warning="Missing Exif header",
            blocker_codes=("tiff_rewrite_not_implemented",),
            evidence_ids=(HEIC_EXIF_TIFF_HANDOFF_EVIDENCE_ID,),
        )
    if len(exif_payload) >= 4:
        header_length = 4 + int.from_bytes(exif_payload[:4], "big")
        if len(exif_payload) >= header_length:
            return HeicExifTiffHandoffPlan(
                operation=operation,
                status="ready_for_tiff_handoff",
                input_length=len(exif_payload),
                header=exif_payload[:header_length],
                tiff_payload=exif_payload[header_length:],
                dir_start=header_length,
                dir_length=len(exif_payload) - header_length,
                warning=None,
                blocker_codes=("tiff_rewrite_not_implemented",),
                evidence_ids=(HEIC_EXIF_TIFF_HANDOFF_EVIDENCE_ID,),
            )
    return HeicExifTiffHandoffPlan(
        operation=operation,
        status="invalid_exif_header",
        input_length=len(exif_payload),
        header=b"",
        tiff_payload=b"",
        dir_start=0,
        dir_length=0,
        warning="Invalid Exif header",
        blocker_codes=("invalid_exif_header",),
        evidence_ids=(HEIC_EXIF_TIFF_HANDOFF_EVIDENCE_ID,),
    )
