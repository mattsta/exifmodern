"""RAW source payload materializers for restored Writer.jpg copy parity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.jpeg.container import inspect_tiff_canon_maker_note_bridge
from exifmodern.formats.public_payload import read_public_document_payload
from exifmodern.json_types import JsonObject

type EvidenceId = str

type CanonRawSourceMaterializationStatus = Literal[
    "ready",
    "missing",
    "blocked_invalid_crw_header",
    "blocked_truncated_ciff_directory",
    "blocked_truncated_ciff_value",
    "blocked_ciff_recursion",
    "blocked_canon_makernote_bridge",
]
type CanonRawCopyProjectionBlockerCode = Literal[
    "requires_shared_jpeg_all_tag_copy_projection",
    "requires_canon_makernote_relocation_into_jpeg_exif",
    "requires_ciff_makernote_projection_into_jpeg_exif",
]

CANON_RAW_JPGFROMRAW_SOURCE = "canon_raw.canon_raw_jpgfromraw"
CANON_RAW_CIFF_PROCESS_SOURCE = "canon_raw.canon_raw_ciff_process"
CANON_RAW_WRITER_TEST_SOURCE = "canon_raw.canon_raw_writer_test"
CANON_RAW_CR2_COPY_TEST_SOURCE = "canon_raw.canon_raw_cr2_copy_test"
CANON_RAW_SETNEWVALUES_SOURCE = "canon_raw.canon_raw_setnewvalues"
CANON_RAW_MAKERNOTE_BRIDGE_SOURCE = "canon_raw.canon_raw_makernote_bridge"


@dataclass(frozen=True)
class CanonRawCiffPayload:
    tag_id: int
    tag_name: str
    offset: int
    length: int
    data: bytes
    directory_path: tuple[str, ...]

    @property
    def sha256(self) -> str:
        from hashlib import sha256

        return sha256(self.data).hexdigest()

    def to_json(self) -> JsonObject:
        return {
            "directory_path": list(self.directory_path),
            "length": self.length,
            "offset": self.offset,
            "sha256": self.sha256,
            "tag_id": f"0x{self.tag_id:04x}",
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class CanonRawCopyProjectionBlocker:
    code: CanonRawCopyProjectionBlockerCode
    reason: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CanonRawSourceMaterialization:
    status: CanonRawSourceMaterializationStatus
    source_path: str
    materialized_payloads: tuple[CanonRawCiffPayload, ...]
    raw_makernote_length: int | None
    raw_makernote_offset: int | None
    diagnostics: tuple[str, ...]
    remaining_blockers: tuple[CanonRawCopyProjectionBlocker, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_json(self) -> JsonObject:
        return {
            "diagnostics": list(self.diagnostics),
            "materialized_payloads": [payload.to_json() for payload in self.materialized_payloads],
            "raw_makernote_length": self.raw_makernote_length,
            "raw_makernote_offset": self.raw_makernote_offset,
            "remaining_blockers": [blocker.to_json() for blocker in self.remaining_blockers],
            "source_path": self.source_path,
            "status": self.status,
        }


def materialize_canon_crw_jpgfromraw_source(path: Path) -> CanonRawSourceMaterialization:
    data = read_public_document_payload(path)
    if data is None:
        return _blocked_canon_raw_materialization(
            "blocked_invalid_crw_header",
            path,
            "CRW source exceeds public materialization limit.",
            (CANON_RAW_CIFF_PROCESS_SOURCE,),
        )
    endian = _crw_endian(data[:2])
    if endian is None or len(data) < 14 or data[6:14] not in {b"HEAPCCDR", b"HEAPJPGM"}:
        return _blocked_canon_raw_materialization(
            "blocked_invalid_crw_header",
            path,
            "CRW header does not match oracle ProcessCRW byte order and HEAP signature gates.",
            (CANON_RAW_CIFF_PROCESS_SOURCE,),
        )
    header_len = int.from_bytes(data[2:6], endian)
    if header_len < 14 or header_len >= len(data):
        return _blocked_canon_raw_materialization(
            "blocked_invalid_crw_header",
            path,
            "CRW heap header length is outside the file.",
            (CANON_RAW_CIFF_PROCESS_SOURCE,),
        )
    result = _find_crw_ciff_payload(
        data,
        block_start=header_len,
        block_len=len(data) - header_len,
        endian=endian,
        wanted_tag_id=0x2007,
        directory_path=("CIFF",),
        visited=(),
    )
    if isinstance(result, str):
        return _blocked_canon_raw_materialization(
            result,
            path,
            f"CRW JpgFromRaw source materialization failed at {result}.",
            (CANON_RAW_CIFF_PROCESS_SOURCE, CANON_RAW_JPGFROMRAW_SOURCE),
        )
    if result is None:
        return CanonRawSourceMaterialization(
            status="missing",
            source_path=path.as_posix(),
            materialized_payloads=(),
            raw_makernote_length=None,
            raw_makernote_offset=None,
            diagnostics=(
                "CRW CIFF traversal completed but JpgFromRaw tag 0x2007 was not present.",
            ),
            remaining_blockers=(),
            evidence_ids=(CANON_RAW_CIFF_PROCESS_SOURCE, CANON_RAW_JPGFROMRAW_SOURCE),
        )
    blocker = CanonRawCopyProjectionBlocker(
        code="requires_ciff_makernote_projection_into_jpeg_exif",
        reason=(
            "RAW-side CIFF JpgFromRaw extraction is materialized, but Writer.t test 13 "
            "requires the shared JPEG all-tag copy writer to project CIFF/MakerNotes "
            "into a destination JPEG without guessing binary relocation."
        ),
        evidence_ids=(CANON_RAW_WRITER_TEST_SOURCE, CANON_RAW_SETNEWVALUES_SOURCE),
    )
    return CanonRawSourceMaterialization(
        status="ready",
        source_path=path.as_posix(),
        materialized_payloads=(result,),
        raw_makernote_length=None,
        raw_makernote_offset=None,
        diagnostics=("CRW CIFF JpgFromRaw payload was materialized from source bytes.",),
        remaining_blockers=(blocker,),
        evidence_ids=(
            CANON_RAW_CIFF_PROCESS_SOURCE,
            CANON_RAW_JPGFROMRAW_SOURCE,
            CANON_RAW_WRITER_TEST_SOURCE,
            CANON_RAW_SETNEWVALUES_SOURCE,
        ),
    )


def materialize_canon_cr2_copy_source(path: Path) -> CanonRawSourceMaterialization:
    data = read_public_document_payload(path)
    if data is None:
        return _blocked_canon_raw_materialization(
            "blocked_canon_makernote_bridge",
            path,
            "CR2 source exceeds public materialization limit.",
            (CANON_RAW_CR2_COPY_TEST_SOURCE, CANON_RAW_MAKERNOTE_BRIDGE_SOURCE),
        )
    bridge = inspect_tiff_canon_maker_note_bridge(data)
    if not bridge.ready or bridge.context is None:
        return _blocked_canon_raw_materialization(
            "blocked_canon_makernote_bridge",
            path,
            "; ".join(bridge.diagnostics),
            (CANON_RAW_CR2_COPY_TEST_SOURCE, CANON_RAW_MAKERNOTE_BRIDGE_SOURCE),
        )
    blocker = CanonRawCopyProjectionBlocker(
        code="requires_canon_makernote_relocation_into_jpeg_exif",
        reason=(
            "CR2 Canon MakerNote source bytes and offsets are available, but "
            "CanonRaw.t test 7 requires relocating that RAW MakerNote payload into "
            "a newly composed JPEG EXIF APP1 block, which is the shared JPEG writer seam."
        ),
        evidence_ids=(CANON_RAW_CR2_COPY_TEST_SOURCE, CANON_RAW_SETNEWVALUES_SOURCE),
    )
    return CanonRawSourceMaterialization(
        status="ready",
        source_path=path.as_posix(),
        materialized_payloads=(),
        raw_makernote_length=len(bridge.raw_maker_note),
        raw_makernote_offset=bridge.context.maker_note_file_offset,
        diagnostics=bridge.diagnostics,
        remaining_blockers=(blocker,),
        evidence_ids=(
            CANON_RAW_CR2_COPY_TEST_SOURCE,
            CANON_RAW_SETNEWVALUES_SOURCE,
            CANON_RAW_MAKERNOTE_BRIDGE_SOURCE,
        ),
    )


def _find_crw_ciff_payload(
    data: bytes,
    *,
    block_start: int,
    block_len: int,
    endian: Literal["little", "big"],
    wanted_tag_id: int,
    directory_path: tuple[str, ...],
    visited: tuple[int, ...],
) -> CanonRawCiffPayload | CanonRawSourceMaterializationStatus | None:
    if block_start in visited:
        return "blocked_ciff_recursion"
    if block_start < 0 or block_len < 4 or block_start + block_len > len(data):
        return "blocked_truncated_ciff_directory"
    dir_offset = int.from_bytes(data[block_start + block_len - 4 : block_start + block_len], endian)
    directory_start = block_start + dir_offset
    if directory_start < block_start or directory_start + 2 > block_start + block_len:
        return "blocked_truncated_ciff_directory"
    entries = int.from_bytes(data[directory_start : directory_start + 2], endian)
    entries_start = directory_start + 2
    entries_end = entries_start + entries * 10
    if entries_end > block_start + block_len or entries_end > len(data):
        return "blocked_truncated_ciff_directory"
    for index in range(entries):
        entry_offset = entries_start + index * 10
        tag = int.from_bytes(data[entry_offset : entry_offset + 2], endian)
        size = int.from_bytes(data[entry_offset + 2 : entry_offset + 6], endian)
        value_pointer = int.from_bytes(data[entry_offset + 6 : entry_offset + 10], endian)
        if tag & 0x8000:
            return "blocked_truncated_ciff_directory"
        tag_id = tag & 0x3FFF
        tag_type = (tag >> 8) & 0x38
        value_in_dir = bool(tag & 0x4000)
        if tag_id == wanted_tag_id:
            if value_in_dir:
                payload_offset = entry_offset + 4
                payload_size = 8
            else:
                payload_offset = block_start + value_pointer
                payload_size = size
            if (
                payload_offset < block_start
                or payload_size < 0
                or payload_offset + payload_size > len(data)
            ):
                return "blocked_truncated_ciff_value"
            return CanonRawCiffPayload(
                tag_id=tag_id,
                tag_name="JpgFromRaw",
                offset=payload_offset,
                length=payload_size,
                data=data[payload_offset : payload_offset + payload_size],
                directory_path=directory_path,
            )
        if tag_type in {0x28, 0x30} and not value_in_dir:
            child_start = block_start + value_pointer
            child_path = (*directory_path, f"CIFF_0x{tag_id:04x}")
            child = _find_crw_ciff_payload(
                data,
                block_start=child_start,
                block_len=size,
                endian=endian,
                wanted_tag_id=wanted_tag_id,
                directory_path=child_path,
                visited=(*visited, block_start),
            )
            if child is not None:
                return child
    return None


def _blocked_canon_raw_materialization(
    status: CanonRawSourceMaterializationStatus,
    path: Path,
    diagnostic: str,
    evidence_ids: tuple[EvidenceId, ...],
) -> CanonRawSourceMaterialization:
    return CanonRawSourceMaterialization(
        status=status,
        source_path=path.as_posix(),
        materialized_payloads=(),
        raw_makernote_length=None,
        raw_makernote_offset=None,
        diagnostics=(diagnostic,),
        remaining_blockers=(),
        evidence_ids=evidence_ids,
    )


def _crw_endian(prefix: bytes) -> Literal["little", "big"] | None:
    if prefix == b"II":
        return "little"
    if prefix == b"MM":
        return "big"
    return None


def evidence_id_to_json(reference: EvidenceId) -> JsonObject:
    return {"id": reference}
