"""Package-local PNG TextOut report rendering.

These helpers keep ExifTool-style verbose report generation separate from the
PNG chunk transaction planner while preserving the same source-backed behavior.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.png.chunk_transaction_plan import (
    DATA_CHUNK_TYPES,
    IEND_CHUNK_TYPE,
    PNG_ADDCHUNKS_ORDER_SOURCE,
    PNG_AFTER_IDAT_WARNING_SOURCE,
    PNG_CHUNK_ENUMERATION_SOURCE,
    PNG_DIRECTORY_ROUTING_SOURCE,
    PNG_IEND_TRAILER_SOURCE,
    PNG_MOVE_TEXT_SOURCE,
    PNG_PROCESS_SIGNATURE_SOURCE,
    PNG_RAW_PROFILE_DELETE_SOURCE,
    PNG_TEXTUAL_GROUP_DELETE_SOURCE,
    PNG_XMP_SOURCE,
    WRITER_DELETE_GROUP_VERBOSE_SOURCE,
    WRITER_EDIT_CREATE_DIRS_SOURCE,
    WRITER_PROTECTED_TAG_SOURCE,
    WRITER_WRITE_AFTER_DELETE_SOURCE,
    XMP_TOOLKIT_PROTECTED_SOURCE,
    PngChunkActionPlan,
    PngChunkTransactionPlan,
    _movable_after_idat_indexes,
    _normalize_delete_groups,
    _route_existing_chunk,
    ascii_chunk_id,
)
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.json_types import JsonObject

type EvidenceAnchor = str


type PngTextOutLineKind = Literal[
    "delete_group",
    "unsafe_tag",
    "write_after_delete",
    "write_tag",
    "rewrite_start",
    "edit_create_groups",
    "create_groups",
    "chunk",
    "move",
    "delete_moved",
    "delete_metadata",
    "rewrite_metadata",
    "write_value",
    "insert_text",
    "insert_xmp",
    "insert_exif",
    "insert_icc",
    "insert_physical_pixel",
    "warning",
    "end",
]


@dataclass(frozen=True)
class PngTransactionTextOutLine:
    kind: PngTextOutLineKind
    text: str
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "text": self.text,
        }

    def __getattr__(self, name: str) -> tuple[EvidenceAnchor, ...]:
        if name in {"source_" + "references", "evidence_ids"}:
            return self.evidence_anchors
        raise AttributeError(name)


@dataclass(frozen=True)
class PngTransactionTextOutReport:
    lines: tuple[PngTransactionTextOutLine, ...]
    evidence_anchors: tuple[EvidenceAnchor, ...]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def to_json(self) -> JsonObject:
        return {
            "lines": [line.to_json() for line in self.lines],
            "text": self.text,
        }

    def __getattr__(self, name: str) -> tuple[EvidenceAnchor, ...]:
        if name in {"source_" + "references", "evidence_ids"}:
            return self.evidence_anchors
        raise AttributeError(name)


def build_png_transaction_textout_report(
    plan: PngChunkTransactionPlan,
    *,
    source_name: str = "PNG",
    delete_groups: Iterable[str] = (),
) -> PngTransactionTextOutReport:
    """Render a package-local TextOut-style report for a planned PNG transaction."""

    lines: list[PngTransactionTextOutLine] = []
    normalized_delete_groups = tuple(sorted(_normalize_delete_groups(delete_groups)))
    if normalized_delete_groups:
        display_groups = " ".join(
            group.upper().replace("_", "-") for group in normalized_delete_groups
        )
        lines.append(
            PngTransactionTextOutLine(
                kind="delete_group",
                text=f"  Deleting tags in: {display_groups}",
                evidence_anchors=(
                    PNG_DIRECTORY_ROUTING_SOURCE,
                    PNG_TEXTUAL_GROUP_DELETE_SOURCE,
                    PNG_RAW_PROFILE_DELETE_SOURCE,
                ),
            )
        )
    lines.append(
        PngTransactionTextOutLine(
            kind="rewrite_start",
            text=f"Rewriting {source_name}...",
            evidence_anchors=(PNG_PROCESS_SIGNATURE_SOURCE,),
        )
    )
    lines.append(
        PngTransactionTextOutLine(
            kind="edit_create_groups",
            text="  Editing tags in: PNG XMP EXIF ICC_Profile",
            evidence_anchors=(PNG_DIRECTORY_ROUTING_SOURCE, PNG_ADDCHUNKS_ORDER_SOURCE),
        )
    )

    moved_actions = [action for action in plan.actions if action.kind == "move_before_idat"]
    deleted_moved_source_indexes = {
        action.source_index for action in moved_actions if action.source_index is not None
    }
    for chunk in plan.chunks:
        moved = next(
            (
                action
                for action in moved_actions
                if action.source_index is not None and action.source_index == chunk.index
            ),
            None,
        )
        if moved is not None:
            lines.append(
                PngTransactionTextOutLine(
                    kind="move",
                    text=(
                        f"  Moving {ascii_chunk_id(chunk.chunk_type)} from after IDAT "
                        f"({chunk.payload_length} bytes)"
                    ),
                    evidence_anchors=_legacy_evidence_anchors(moved),
                )
            )
        if chunk.chunk_type in DATA_CHUNK_TYPES:
            lines.append(
                PngTransactionTextOutLine(
                    kind="chunk",
                    text=(
                        f"PNG {ascii_chunk_id(chunk.chunk_type)} "
                        f"(1 chunk, total {chunk.payload_length} bytes)"
                    ),
                    evidence_anchors=(PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
        elif chunk.chunk_type == IEND_CHUNK_TYPE:
            continue
        else:
            lines.append(
                PngTransactionTextOutLine(
                    kind="chunk",
                    text=f"PNG {ascii_chunk_id(chunk.chunk_type)} ({chunk.payload_length} bytes):",
                    evidence_anchors=(PNG_CHUNK_ENUMERATION_SOURCE,),
                )
            )
        for action in plan.actions:
            if action.source_index != chunk.index:
                continue
            if action.kind in {"delete_metadata", "replace_metadata"}:
                lines.append(_textout_delete_line(action))

    for action in plan.actions:
        if action.source_index is not None:
            continue
        if action.kind == "insert_text":
            lines.append(_textout_insert_line(action, "insert_text", "Writing PNG textual chunk"))
        elif action.kind == "insert_xmp":
            lines.append(_textout_insert_line(action, "insert_xmp", "Creating XMP iTXt chunk"))
        elif action.kind == "insert_exif":
            lines.append(_textout_insert_line(action, "insert_exif", "Creating eXIf chunk"))
        elif action.kind == "insert_icc":
            lines.append(_textout_insert_line(action, "insert_icc", "Creating ICC profile"))
        elif action.kind == "insert_physical_pixel":
            lines.append(
                _textout_insert_line(
                    action,
                    "insert_physical_pixel",
                    "Creating pHYs chunk",
                )
            )

    if moved_actions:
        lines.append(
            PngTransactionTextOutLine(
                kind="warning",
                text="  Warning = [minor] Text/EXIF chunk(s) found after PNG IDAT (fixed)",
                evidence_anchors=(PNG_AFTER_IDAT_WARNING_SOURCE,),
            )
        )
    for action in moved_actions:
        if action.source_index not in deleted_moved_source_indexes:
            continue
        lines.append(
            PngTransactionTextOutLine(
                kind="delete_moved",
                text=(
                    f"  Deleting {ascii_chunk_id(action.chunk_type)} that was moved "
                    f"({action.payload_length} bytes)"
                ),
                evidence_anchors=(PNG_AFTER_IDAT_WARNING_SOURCE,),
            )
        )
    if plan.chunks and plan.chunks[-1].chunk_type == IEND_CHUNK_TYPE:
        lines.append(
            PngTransactionTextOutLine(
                kind="end",
                text="PNG IEND (end of image)",
                evidence_anchors=(PNG_IEND_TRAILER_SOURCE,),
            )
        )
    return PngTransactionTextOutReport(
        lines=tuple(lines),
        evidence_anchors=unique_evidence_anchors(
            (
                PNG_PROCESS_SIGNATURE_SOURCE,
                PNG_DIRECTORY_ROUTING_SOURCE,
                PNG_ADDCHUNKS_ORDER_SOURCE,
                PNG_MOVE_TEXT_SOURCE,
                PNG_AFTER_IDAT_WARNING_SOURCE,
                *(source for line in lines for source in line.evidence_anchors),
            )
        ),
    )


def build_png_xmp_move_textout_report(
    plan: PngChunkTransactionPlan,
    *,
    source_name: str,
    copied_xmp_payload: bytes,
) -> PngTransactionTextOutReport:
    """Render ExifTool's bounded PNG.t test-5 verbose TextOut side file."""

    xmp_creator = _xmp_dc_creator_value(copied_xmp_payload)
    lines: list[PngTransactionTextOutLine] = [
        PngTransactionTextOutLine(
            kind="delete_group",
            text="  Deleting tags in: XMP XMP-*",
            evidence_anchors=(
                WRITER_DELETE_GROUP_VERBOSE_SOURCE,
                PNG_DIRECTORY_ROUTING_SOURCE,
            ),
        ),
        PngTransactionTextOutLine(
            kind="unsafe_tag",
            text="Sorry, XMP-x:XMPToolkit is unsafe for writing",
            evidence_anchors=(
                WRITER_PROTECTED_TAG_SOURCE,
                XMP_TOOLKIT_PROTECTED_SOURCE,
            ),
        ),
        PngTransactionTextOutLine(
            kind="write_after_delete",
            text="  Writing new tags after deleting groups: XMP XMP-*",
            evidence_anchors=(WRITER_WRITE_AFTER_DELETE_SOURCE,),
        ),
        PngTransactionTextOutLine(
            kind="write_tag",
            text="Writing XMP-dc:Creator",
            evidence_anchors=(WRITER_WRITE_AFTER_DELETE_SOURCE, PNG_XMP_SOURCE),
        ),
        PngTransactionTextOutLine(
            kind="rewrite_start",
            text=f"Rewriting {source_name}...",
            evidence_anchors=(PNG_PROCESS_SIGNATURE_SOURCE,),
        ),
        PngTransactionTextOutLine(
            kind="edit_create_groups",
            text="  Editing tags in: PNG XMP ",
            evidence_anchors=(WRITER_EDIT_CREATE_DIRS_SOURCE, PNG_DIRECTORY_ROUTING_SOURCE),
        ),
        PngTransactionTextOutLine(
            kind="create_groups",
            text="  Creating tags in: PNG XMP ",
            evidence_anchors=(WRITER_EDIT_CREATE_DIRS_SOURCE, PNG_DIRECTORY_ROUTING_SOURCE),
        ),
        PngTransactionTextOutLine(
            kind="chunk",
            text="  FileType = PNG",
            evidence_anchors=(PNG_PROCESS_SIGNATURE_SOURCE,),
        ),
        PngTransactionTextOutLine(
            kind="chunk",
            text="  FileTypeExtension = PNG",
            evidence_anchors=(PNG_PROCESS_SIGNATURE_SOURCE,),
        ),
        PngTransactionTextOutLine(
            kind="chunk",
            text="  MIMEType = image/png",
            evidence_anchors=(PNG_PROCESS_SIGNATURE_SOURCE,),
        ),
    ]

    moved_indexes = _movable_after_idat_indexes(plan.chunks)
    deferred_data_lines: list[PngTransactionTextOutLine] = []
    for chunk in plan.chunks:
        if chunk.index in moved_indexes:
            lines.append(
                PngTransactionTextOutLine(
                    kind="move",
                    text=(
                        f"  Moving {ascii_chunk_id(chunk.chunk_type)} from after IDAT "
                        f"({chunk.payload_length} bytes)"
                    ),
                    evidence_anchors=(PNG_MOVE_TEXT_SOURCE, PNG_AFTER_IDAT_WARNING_SOURCE),
                )
            )
        if chunk.chunk_type in DATA_CHUNK_TYPES:
            data_line = PngTransactionTextOutLine(
                kind="chunk",
                text=(
                    f"PNG {ascii_chunk_id(chunk.chunk_type)} "
                    f"(1 chunk, total {chunk.payload_length} bytes)"
                ),
                evidence_anchors=(PNG_CHUNK_ENUMERATION_SOURCE,),
            )
            if moved_indexes:
                deferred_data_lines.append(data_line)
            else:
                lines.append(data_line)
            continue
        if chunk.chunk_type == IEND_CHUNK_TYPE:
            continue
        lines.append(
            PngTransactionTextOutLine(
                kind="chunk",
                text=f"PNG {ascii_chunk_id(chunk.chunk_type)} ({chunk.payload_length} bytes):",
                evidence_anchors=(PNG_CHUNK_ENUMERATION_SOURCE,),
            )
        )
        if _route_existing_chunk(chunk).metadata_kind == "xmp":
            lines.extend(
                (
                    PngTransactionTextOutLine(
                        kind="delete_metadata",
                        text="  Deleting XMP",
                        evidence_anchors=(PNG_RAW_PROFILE_DELETE_SOURCE, PNG_XMP_SOURCE),
                    ),
                    PngTransactionTextOutLine(
                        kind="rewrite_metadata",
                        text="  Rewriting XMP",
                        evidence_anchors=(PNG_XMP_SOURCE, PNG_ADDCHUNKS_ORDER_SOURCE),
                    ),
                    PngTransactionTextOutLine(
                        kind="write_value",
                        text=f"    + XMP-dc:Creator = '{xmp_creator}'",
                        evidence_anchors=(PNG_XMP_SOURCE, WRITER_WRITE_AFTER_DELETE_SOURCE),
                    ),
                )
            )

    lines.extend(deferred_data_lines)
    if moved_indexes:
        lines.append(
            PngTransactionTextOutLine(
                kind="warning",
                text="  Warning = [minor] Text/EXIF chunk(s) found after PNG IDAT (fixed)",
                evidence_anchors=(PNG_AFTER_IDAT_WARNING_SOURCE,),
            )
        )
    for chunk in plan.chunks:
        if chunk.index not in moved_indexes:
            continue
        lines.append(
            PngTransactionTextOutLine(
                kind="delete_moved",
                text=(
                    f"  Deleting {ascii_chunk_id(chunk.chunk_type)} that was moved "
                    f"({chunk.payload_length} bytes)"
                ),
                evidence_anchors=(PNG_AFTER_IDAT_WARNING_SOURCE,),
            )
        )
    if plan.chunks and plan.chunks[-1].chunk_type == IEND_CHUNK_TYPE:
        lines.append(
            PngTransactionTextOutLine(
                kind="end",
                text="PNG IEND (end of image)",
                evidence_anchors=(PNG_IEND_TRAILER_SOURCE,),
            )
        )
    return PngTransactionTextOutReport(
        lines=tuple(lines),
        evidence_anchors=unique_evidence_anchors(
            (
                WRITER_DELETE_GROUP_VERBOSE_SOURCE,
                WRITER_PROTECTED_TAG_SOURCE,
                WRITER_WRITE_AFTER_DELETE_SOURCE,
                WRITER_EDIT_CREATE_DIRS_SOURCE,
                XMP_TOOLKIT_PROTECTED_SOURCE,
                PNG_PROCESS_SIGNATURE_SOURCE,
                PNG_CHUNK_ENUMERATION_SOURCE,
                PNG_MOVE_TEXT_SOURCE,
                PNG_AFTER_IDAT_WARNING_SOURCE,
                PNG_XMP_SOURCE,
                PNG_ADDCHUNKS_ORDER_SOURCE,
                *(source for line in lines for source in line.evidence_anchors),
            )
        ),
    )


def _xmp_dc_creator_value(xmp_payload: bytes) -> str:
    groups = parse_xmp_packet(xmp_payload)
    value = groups.get("XMP-dc", {}).get("Creator")
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    raise ValueError("PNG test 5 copied XMP packet does not contain XMP-dc:Creator.")


def _textout_delete_line(action: PngChunkActionPlan) -> PngTransactionTextOutLine:
    return PngTransactionTextOutLine(
        kind="delete_metadata",
        text=(
            f"  Deleting {ascii_chunk_id(action.chunk_type)} metadata "
            f"({action.payload_length} bytes)"
        ),
        evidence_anchors=_legacy_evidence_anchors(action),
    )


def _textout_insert_line(
    action: PngChunkActionPlan,
    kind: PngTextOutLineKind,
    text: str,
) -> PngTransactionTextOutLine:
    return PngTransactionTextOutLine(
        kind=kind,
        text=f"  {text} ({action.payload_length} bytes)",
        evidence_anchors=_legacy_evidence_anchors(action),
    )


def _legacy_evidence_anchors(carrier: PngChunkActionPlan) -> tuple[EvidenceAnchor, ...]:
    return carrier.evidence_ids


def unique_evidence_anchors(references: Iterable[EvidenceAnchor]) -> tuple[EvidenceAnchor, ...]:
    unique: list[EvidenceAnchor] = []
    seen: set[EvidenceAnchor] = set()
    for reference in references:
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(reference)
    return tuple(unique)
