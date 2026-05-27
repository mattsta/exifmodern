"""JPEG COM segment mutation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.jpeg.container import JpegSegment, scan_jpeg_segments
from exifmodern.formats.jpeg.segment_writer import encode_jpeg_segment

JPEG_COM_MARKER = 0xFE
JPEG_MAX_SEGMENT_PAYLOAD_LENGTH = 0xFFFD


@dataclass(frozen=True)
class JpegCommentRewriteResult:
    data: bytes
    original_comment_segments: int
    rewritten_comment_segments: int


def rewrite_jpeg_comment(jpeg_data: bytes, comment: bytes | str | None) -> JpegCommentRewriteResult:
    """Replace all existing JPEG COM segments with one source-compatible value.

    ExifTool maps JPEG `Comment` to COM and rewrites at most one logical
    comment value, deleting duplicate COM segments as it goes.
    """

    payload = comment.encode("utf-8") if isinstance(comment, str) else comment
    segments = tuple(segment for segment in scan_jpeg_segments(jpeg_data) if segment.marker == 0xFE)
    without_comments = remove_comment_segments(jpeg_data, segments)
    if payload is None:
        return JpegCommentRewriteResult(
            data=without_comments,
            original_comment_segments=len(segments),
            rewritten_comment_segments=0,
        )

    rewritten_segments = encode_jpeg_comment_segments(payload)
    insertion_offset = jpeg_comment_insertion_offset(without_comments)
    return JpegCommentRewriteResult(
        data=(
            without_comments[:insertion_offset]
            + b"".join(rewritten_segments)
            + without_comments[insertion_offset:]
        ),
        original_comment_segments=len(segments),
        rewritten_comment_segments=len(rewritten_segments),
    )


def first_jpeg_comment(jpeg_data: bytes) -> bytes | None:
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker == JPEG_COM_MARKER:
            payload_end = segment.payload_offset + segment.payload_length
            return jpeg_data[segment.payload_offset : payload_end]
    return None


def encode_jpeg_comment_segments(comment: bytes) -> tuple[bytes, ...]:
    if not comment:
        return (encode_jpeg_segment(JPEG_COM_MARKER, b""),)
    return tuple(
        encode_jpeg_segment(
            JPEG_COM_MARKER,
            comment[offset : offset + JPEG_MAX_SEGMENT_PAYLOAD_LENGTH],
        )
        for offset in range(0, len(comment), JPEG_MAX_SEGMENT_PAYLOAD_LENGTH)
    )


def remove_comment_segments(
    jpeg_data: bytes,
    comment_segments: tuple[JpegSegment, ...],
) -> bytes:
    rewritten = jpeg_data
    for segment in reversed(comment_segments):
        segment_end = segment.payload_offset + segment.payload_length
        rewritten = rewritten[: segment.offset] + rewritten[segment_end:]
    return rewritten


def jpeg_comment_insertion_offset(jpeg_data: bytes) -> int:
    insertion_offset = 2
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker < 0xE0 or segment.marker > 0xEF:
            break
        insertion_offset = segment.payload_offset + segment.payload_length
    return insertion_offset
