"""Nikon source payload materializers for restored Writer.jpg copy parity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.jpeg.container import inspect_jpeg_nikon_maker_note_bridge
from exifmodern.json_types import JsonObject

type EvidenceId = str

type NikonSourceMaterializationStatus = Literal[
    "ready",
    "blocked_nikon_makernote_bridge",
]
type NikonCopyProjectionBlockerCode = Literal[
    "requires_shared_jpeg_all_tag_copy_projection",
    "requires_nikon_makernote_relocation_into_jpeg_exif",
]

NIKON_TEST4_SOURCE_ID = "nikon.source_materialization.test_4"
NIKON_PROCESS_SOURCE_ID = "nikon.source_materialization.process_nikon"
NIKON_D70_LENS_SOURCE_ID = "nikon.source_materialization.d70_lensdata"
NIKON_SETNEWVALUES_SOURCE_ID = "nikon.source_materialization.set_new_values_from_file"


@dataclass(frozen=True)
class NikonCopyProjectionBlocker:
    code: NikonCopyProjectionBlockerCode
    reason: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class NikonSourceMaterialization:
    status: NikonSourceMaterializationStatus
    source_path: str
    raw_makernote_length: int | None
    raw_makernote_offset: int | None
    raw_main_ifd_length: int | None
    maker_note_byte_order: str | None
    diagnostics: tuple[str, ...]
    remaining_blockers: tuple[NikonCopyProjectionBlocker, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_json(self) -> JsonObject:
        return {
            "diagnostics": list(self.diagnostics),
            "maker_note_byte_order": self.maker_note_byte_order,
            "raw_main_ifd_length": self.raw_main_ifd_length,
            "raw_makernote_length": self.raw_makernote_length,
            "raw_makernote_offset": self.raw_makernote_offset,
            "remaining_blockers": [blocker.to_json() for blocker in self.remaining_blockers],
            "source_path": self.source_path,
            "status": self.status,
        }


def materialize_nikon_d70_jpeg_copy_source(path: Path) -> NikonSourceMaterialization:
    bridge = inspect_jpeg_nikon_maker_note_bridge(path)
    if not bridge.ready or bridge.context is None:
        return NikonSourceMaterialization(
            status="blocked_nikon_makernote_bridge",
            source_path=path.as_posix(),
            raw_makernote_length=None,
            raw_makernote_offset=None,
            raw_main_ifd_length=None,
            maker_note_byte_order=None,
            diagnostics=bridge.diagnostics,
            remaining_blockers=(),
            evidence_ids=(NIKON_TEST4_SOURCE_ID, NIKON_PROCESS_SOURCE_ID),
        )
    blocker = NikonCopyProjectionBlocker(
        code="requires_nikon_makernote_relocation_into_jpeg_exif",
        reason=(
            "NikonD70 MakerNote source bytes and ExifTool-style Type2/headerless "
            "context are materialized, but Nikon.t test 4 requires projecting all "
            "source tags into restored Writer.jpg and relocating MakerNote offsets "
            "inside a newly composed JPEG EXIF APP1 block."
        ),
        evidence_ids=(
            NIKON_TEST4_SOURCE_ID,
            NIKON_SETNEWVALUES_SOURCE_ID,
            NIKON_PROCESS_SOURCE_ID,
        ),
    )
    return NikonSourceMaterialization(
        status="ready",
        source_path=path.as_posix(),
        raw_makernote_length=len(bridge.raw_maker_note),
        raw_makernote_offset=bridge.context.maker_note_file_offset,
        raw_main_ifd_length=len(bridge.raw_main_ifd),
        maker_note_byte_order=bridge.context.byte_order,
        diagnostics=bridge.diagnostics,
        remaining_blockers=(blocker,),
        evidence_ids=(
            NIKON_TEST4_SOURCE_ID,
            NIKON_SETNEWVALUES_SOURCE_ID,
            NIKON_PROCESS_SOURCE_ID,
            NIKON_D70_LENS_SOURCE_ID,
        ),
    )
