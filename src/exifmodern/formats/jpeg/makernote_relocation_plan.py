"""JPEG MakerNote relocation planning for all-tag copy routes.

The shared JPEG composed writer may only emit MakerNotes after an exact
ExifTool-style EXIF rebuild has produced the same offset fixup graph.  This
module records the source-backed byte evidence for the restored fixture seam
without exposing a partial writer path.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from exifmodern.formats.canon_raw.source_materialization import (
    materialize_canon_cr2_copy_source,
)
from exifmodern.formats.nikon.source_materialization import (
    materialize_nikon_d70_jpeg_copy_source,
)
from exifmodern.json_types import JsonObject
from exifmodern.media_source import FileMediaSource

type JpegMakerNoteRelocationSourceKind = Literal["canon_cr2", "nikon_d70_jpeg"]
type JpegMakerNoteRelocationStatus = Literal["blocked_exact_fixup_graph_required"]
type JpegMakerNoteFixupPrimitiveCode = Literal[
    "source_extraction_makernote_fixup_extra",
    "rebuild_makernotes_locate_ifd_fixup_ledger",
    "maker_note_fixbase_footer_padding_decision",
    "parent_write_directory_value_fixup_records",
    "parent_exif_value_position_materialization_hook",
    "jpeg_app1_final_fixup_application",
]
type JpegMakerNoteRelocationBlockerCode = Literal[
    "requires_canon_makernote_relocation_into_jpeg_exif",
    "requires_nikon_makernote_relocation_into_jpeg_exif",
]

SETNEWVALUES_ALL_TAG_EVIDENCE_ID = "jpeg.makernote_relocation.set_new_values_all_tag"
WRITEEXIF_DIRECTORY_FIXUP_EVIDENCE_ID = "jpeg.makernote_relocation.directory_fixup"
EXIF_SOURCE_FIXUP_EXTRA_EVIDENCE_ID = "jpeg.makernote_relocation.source_fixup_extra"
WRITEEXIF_REBUILD_MAKERNOTES_EVIDENCE_ID = "jpeg.makernote_relocation.rebuild_makernotes"
WRITEEXIF_PARENT_MAKERNOTE_VALUE_EVIDENCE_ID = "jpeg.makernote_relocation.parent_value"
WRITEEXIF_FINAL_FIXUP_EVIDENCE_ID = "jpeg.makernote_relocation.final_fixup"
MAKERNOTE_ROUTE_EVIDENCE_ID = "jpeg.makernote_relocation.route"
MAKERNOTE_FIXBASE_EVIDENCE_ID = "jpeg.makernote_relocation.fixbase"
CANONRAW_TEST7_EVIDENCE_ID = "jpeg.makernote_relocation.canonraw_test7"
NIKON_TEST4_EVIDENCE_ID = "jpeg.makernote_relocation.nikon_test4"


@dataclass(frozen=True)
class JpegMakerNoteByteEvidence:
    source_path: str
    source_kind: JpegMakerNoteRelocationSourceKind
    raw_makernote_offset: int
    raw_makernote_length: int
    raw_makernote_sha256: str | None
    raw_main_ifd_length: int | None = None
    maker_note_byte_order: str | None = None

    @property
    def raw_makernote_end_offset(self) -> int:
        return self.raw_makernote_offset + self.raw_makernote_length

    def to_json(self) -> JsonObject:
        payload: JsonObject = {
            "raw_makernote_end_offset": self.raw_makernote_end_offset,
            "raw_makernote_length": self.raw_makernote_length,
            "raw_makernote_offset": self.raw_makernote_offset,
            "source_kind": self.source_kind,
            "source_path": self.source_path,
        }
        if self.raw_makernote_sha256 is not None:
            payload["raw_makernote_sha256"] = self.raw_makernote_sha256
        if self.raw_main_ifd_length is not None:
            payload["raw_main_ifd_length"] = self.raw_main_ifd_length
        if self.maker_note_byte_order is not None:
            payload["maker_note_byte_order"] = self.maker_note_byte_order
        return payload


@dataclass(frozen=True)
class JpegMakerNoteRelocationBlocker:
    code: JpegMakerNoteRelocationBlockerCode
    reason: str
    unsafe_partial_write_policy: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
            "unsafe_partial_write_policy": self.unsafe_partial_write_policy,
        }


@dataclass(frozen=True)
class JpegMakerNoteFixupGraphPrimitive:
    code: JpegMakerNoteFixupPrimitiveCode
    description: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "description": self.description,
        }


@dataclass(frozen=True)
class JpegMakerNoteRelocationPlan:
    status: JpegMakerNoteRelocationStatus
    byte_evidence: JpegMakerNoteByteEvidence
    blockers: tuple[JpegMakerNoteRelocationBlocker, ...]
    missing_fixup_primitives: tuple[JpegMakerNoteFixupGraphPrimitive, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_relocate(self) -> bool:
        return False

    @property
    def primary_blocker(self) -> JpegMakerNoteRelocationBlocker:
        return self.blockers[0]

    def to_json(self) -> JsonObject:
        return {
            "blockers": [blocker.to_json() for blocker in self.blockers],
            "byte_evidence": self.byte_evidence.to_json(),
            "can_relocate": self.can_relocate,
            "missing_fixup_primitives": [
                primitive.to_json() for primitive in self.missing_fixup_primitives
            ],
            "status": self.status,
        }


def build_canon_cr2_jpeg_makernote_relocation_plan(
    source_path: Path,
) -> JpegMakerNoteRelocationPlan:
    materialization = materialize_canon_cr2_copy_source(source_path)
    if materialization.raw_makernote_offset is None or materialization.raw_makernote_length is None:
        raise ValueError("Canon CR2 materializer did not expose MakerNote byte evidence.")
    byte_evidence = JpegMakerNoteByteEvidence(
        source_path=source_path.as_posix(),
        source_kind="canon_cr2",
        raw_makernote_offset=materialization.raw_makernote_offset,
        raw_makernote_length=materialization.raw_makernote_length,
        raw_makernote_sha256=None,
    )
    blocker = JpegMakerNoteRelocationBlocker(
        code="requires_canon_makernote_relocation_into_jpeg_exif",
        reason=(
            "Canon CR2 source bytes identify the MakerNote range, but ExifTool "
            "relocation depends on WriteExif rebuilding the EXIF tree and applying "
            "MakerNotes FixBase/footer/padding decisions from the new JPEG APP1 "
            "layout.  The current source materializer does not provide that fixup graph."
        ),
        unsafe_partial_write_policy=(
            "Do not copy the raw CR2 MakerNote block or RAW TIFF wrapper into JPEG APP1."
        ),
        evidence_ids=(
            CANONRAW_TEST7_EVIDENCE_ID,
            SETNEWVALUES_ALL_TAG_EVIDENCE_ID,
            EXIF_SOURCE_FIXUP_EXTRA_EVIDENCE_ID,
            WRITEEXIF_REBUILD_MAKERNOTES_EVIDENCE_ID,
            MAKERNOTE_ROUTE_EVIDENCE_ID,
            MAKERNOTE_FIXBASE_EVIDENCE_ID,
            WRITEEXIF_PARENT_MAKERNOTE_VALUE_EVIDENCE_ID,
            WRITEEXIF_DIRECTORY_FIXUP_EVIDENCE_ID,
            WRITEEXIF_FINAL_FIXUP_EVIDENCE_ID,
        ),
    )
    missing_primitives = (
        *_shared_missing_fixup_primitives(),
        JpegMakerNoteFixupGraphPrimitive(
            code="maker_note_fixbase_footer_padding_decision",
            description=(
                "Canon relocation needs the MakerNotes FixBase result, Canon footer "
                "old/new offset comparison, and make/model-specific MakerNotes "
                "padding decision from the destination JPEG layout."
            ),
            evidence_ids=(MAKERNOTE_FIXBASE_EVIDENCE_ID, WRITEEXIF_DIRECTORY_FIXUP_EVIDENCE_ID),
        ),
    )
    evidence_ids = blocker.evidence_ids + tuple(
        evidence_id for primitive in missing_primitives for evidence_id in primitive.evidence_ids
    )
    return JpegMakerNoteRelocationPlan(
        status="blocked_exact_fixup_graph_required",
        byte_evidence=byte_evidence,
        blockers=(blocker,),
        missing_fixup_primitives=missing_primitives,
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
    )


def build_nikon_d70_jpeg_makernote_relocation_plan(
    source_path: Path,
) -> JpegMakerNoteRelocationPlan:
    materialization = materialize_nikon_d70_jpeg_copy_source(source_path)
    if materialization.raw_makernote_offset is None or materialization.raw_makernote_length is None:
        raise ValueError("NikonD70 materializer did not expose MakerNote byte evidence.")
    byte_evidence = JpegMakerNoteByteEvidence(
        source_path=source_path.as_posix(),
        source_kind="nikon_d70_jpeg",
        raw_makernote_offset=materialization.raw_makernote_offset,
        raw_makernote_length=materialization.raw_makernote_length,
        raw_makernote_sha256=_source_slice_sha256(
            source_path,
            materialization.raw_makernote_offset,
            materialization.raw_makernote_length,
        ),
        raw_main_ifd_length=materialization.raw_main_ifd_length,
        maker_note_byte_order=materialization.maker_note_byte_order,
    )
    blocker = JpegMakerNoteRelocationBlocker(
        code="requires_nikon_makernote_relocation_into_jpeg_exif",
        reason=(
            "NikonD70 source bytes expose the Type2 MakerNote and raw Main IFD, "
            "but ExifTool writes the destination by extracting source tags, then "
            "rebuilding EXIF and applying nested directory/value fixups.  The current "
            "JPEG composed copy writer lacks those per-entry fixup records, including "
            "Nikon base-relative offsets."
        ),
        unsafe_partial_write_policy=(
            "Do not preserve the source EXIF APP1 MakerNote block when an implicit "
            "all-tag copy targets a new JPEG."
        ),
        evidence_ids=(
            NIKON_TEST4_EVIDENCE_ID,
            SETNEWVALUES_ALL_TAG_EVIDENCE_ID,
            EXIF_SOURCE_FIXUP_EXTRA_EVIDENCE_ID,
            WRITEEXIF_REBUILD_MAKERNOTES_EVIDENCE_ID,
            MAKERNOTE_ROUTE_EVIDENCE_ID,
            MAKERNOTE_FIXBASE_EVIDENCE_ID,
            WRITEEXIF_PARENT_MAKERNOTE_VALUE_EVIDENCE_ID,
            WRITEEXIF_DIRECTORY_FIXUP_EVIDENCE_ID,
            WRITEEXIF_FINAL_FIXUP_EVIDENCE_ID,
        ),
    )
    missing_primitives = (
        *_shared_missing_fixup_primitives(),
        JpegMakerNoteFixupGraphPrimitive(
            code="maker_note_fixbase_footer_padding_decision",
            description=(
                "Nikon Type2 relocation needs the destination-layout base shift for "
                "the Nikon header/subdirectory boundary and the non-relative "
                "MAKER_NOTE_FIXUP pointer records produced by WriteDirectory."
            ),
            evidence_ids=(
                MAKERNOTE_ROUTE_EVIDENCE_ID,
                WRITEEXIF_REBUILD_MAKERNOTES_EVIDENCE_ID,
                WRITEEXIF_PARENT_MAKERNOTE_VALUE_EVIDENCE_ID,
            ),
        ),
    )
    evidence_ids = blocker.evidence_ids + tuple(
        evidence_id for primitive in missing_primitives for evidence_id in primitive.evidence_ids
    )
    return JpegMakerNoteRelocationPlan(
        status="blocked_exact_fixup_graph_required",
        byte_evidence=byte_evidence,
        blockers=(blocker,),
        missing_fixup_primitives=missing_primitives,
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
    )


def _source_slice_sha256(path: Path, offset: int, length: int) -> str:
    return sha256(FileMediaSource(path).read_at(offset, length)).hexdigest()


def _shared_missing_fixup_primitives() -> tuple[JpegMakerNoteFixupGraphPrimitive, ...]:
    return (
        JpegMakerNoteFixupGraphPrimitive(
            code="source_extraction_makernote_fixup_extra",
            description=(
                "The source reader must expose the copied MakerNote value together "
                "with the TAG_EXTRA Fixup ledger that Exif.pm attaches after "
                "RebuildMakerNotes."
            ),
            evidence_ids=(
                EXIF_SOURCE_FIXUP_EXTRA_EVIDENCE_ID,
                WRITEEXIF_REBUILD_MAKERNOTES_EVIDENCE_ID,
            ),
        ),
        JpegMakerNoteFixupGraphPrimitive(
            code="rebuild_makernotes_locate_ifd_fixup_ledger",
            description=(
                "The MakerNote value must be rebuilt through LocateIFD and "
                "WriteDirectory so every nested offset pointer is recorded before "
                "the value is inserted into the parent EXIF tree."
            ),
            evidence_ids=(WRITEEXIF_REBUILD_MAKERNOTES_EVIDENCE_ID,),
        ),
        JpegMakerNoteFixupGraphPrimitive(
            code="parent_write_directory_value_fixup_records",
            description=(
                "The parent EXIF writer must carry MakerNote fixups through valBuff "
                "and valFixups, then merge them with directory/subdirectory fixups "
                "after final value positions are known."
            ),
            evidence_ids=(
                WRITEEXIF_PARENT_MAKERNOTE_VALUE_EVIDENCE_ID,
                WRITEEXIF_DIRECTORY_FIXUP_EVIDENCE_ID,
            ),
        ),
        JpegMakerNoteFixupGraphPrimitive(
            code="parent_exif_value_position_materialization_hook",
            description=(
                "The JPEG composed writer currently replaces whole APP1 payloads; it "
                "does not materialize the parent EXIF entry/value positions required "
                "to shift MakerNote pointers into the new Writer.jpg APP1 layout."
            ),
            evidence_ids=(WRITEEXIF_DIRECTORY_FIXUP_EVIDENCE_ID,),
        ),
        JpegMakerNoteFixupGraphPrimitive(
            code="jpeg_app1_final_fixup_application",
            description=(
                "Final JPEG APP1 and preview/data marker fixups are applied only "
                "after the complete EXIF payload length and insertion position are "
                "known."
            ),
            evidence_ids=(WRITEEXIF_FINAL_FIXUP_EVIDENCE_ID,),
        ),
    )
