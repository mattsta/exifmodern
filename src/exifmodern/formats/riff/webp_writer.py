"""Source-grounded RIFF/WebP metadata chunk mutation boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan
from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.riff.webp_constants import (
    ALPH_CHUNK_ID,
    ANIM_CHUNK_ID,
    EXIF_CHUNK_ID,
    ICC_CHUNK_ID,
    INCORRECT_XMP_CHUNK_ID,
    VP8_CHUNK_ID,
    VP8L_CHUNK_ID,
    VP8X_CHUNK_ID,
    WEBP_FORM_TYPE,
    XMP_CHUNK_ID,
)
from exifmodern.formats.tiff.exif_scalar_rewriter import (
    create_minimal_exif_scalar_tiff,
    rewrite_exif_scalars_creating_if_needed,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan

__all__ = [
    "ALPH_CHUNK_ID",
    "ANIM_CHUNK_ID",
    "EXIF_CHUNK_ID",
    "ICC_CHUNK_ID",
    "INCORRECT_XMP_CHUNK_ID",
    "VP8L_CHUNK_ID",
    "VP8X_CHUNK_ID",
    "VP8_CHUNK_ID",
    "WEBP_FORM_TYPE",
    "XMP_CHUNK_ID",
    "RiffChunk",
    "WebpMetadataRewriteResult",
    "encode_riff_chunk",
    "encode_webp_chunks",
    "parse_webp_chunks",
    "rewrite_webp_file_metadata",
    "rewrite_webp_metadata",
]

WEBP_FLAG_ANIMATION = 0x02
WEBP_FLAG_XMP = 0x04
WEBP_FLAG_EXIF = 0x08
WEBP_FLAG_ALPHA = 0x10
WEBP_FLAG_ICC = 0x20
WEBP_METADATA_CHUNK_IDS = {EXIF_CHUNK_ID, XMP_CHUNK_ID, ICC_CHUNK_ID}
WEBP_DELETABLE_METADATA_CHUNK_IDS = WEBP_METADATA_CHUNK_IDS | {INCORRECT_XMP_CHUNK_ID}
VP8X_PAYLOAD_SIZE = 10


@dataclass(frozen=True)
class RiffChunk:
    chunk_id: bytes
    payload: bytes


@dataclass(frozen=True)
class WebpMetadataRewriteResult:
    data: bytes
    changed_exif_properties: int
    changed_xmp_properties: int
    deleted_metadata_chunks: int
    transaction: FileWriteTransactionResult | None = None


def rewrite_webp_file_metadata(
    input_path: Path,
    output_path: Path,
    exif_plan: ExifScalarWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    delete_all_metadata: bool,
) -> WebpMetadataRewriteResult:
    result = rewrite_webp_metadata(
        input_path.read_bytes(),
        exif_plan,
        xmp_plan,
        delete_all_metadata,
    )
    transaction = write_bytes_transactionally(output_path, result.data)
    return WebpMetadataRewriteResult(
        data=result.data,
        changed_exif_properties=result.changed_exif_properties,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_metadata_chunks=result.deleted_metadata_chunks,
        transaction=transaction,
    )


def rewrite_webp_metadata(
    webp_data: bytes,
    exif_plan: ExifScalarWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    delete_all_metadata: bool,
) -> WebpMetadataRewriteResult:
    chunks = parse_webp_chunks(webp_data)
    deleted_chunks = 0
    if delete_all_metadata:
        retained_chunks: list[RiffChunk] = []
        for chunk in chunks:
            if chunk.chunk_id in WEBP_DELETABLE_METADATA_CHUNK_IDS:
                deleted_chunks += 1
                continue
            retained_chunks.append(chunk)
        chunks = tuple(retained_chunks)
    changed_exif_properties = 0
    changed_xmp_properties = 0
    if exif_plan is not None and not delete_all_metadata:
        chunks = upsert_webp_chunk(chunks, EXIF_CHUNK_ID, rewritten_exif_chunk(chunks, exif_plan))
        changed_exif_properties = len(exif_plan.steps)
    if xmp_plan is not None and not delete_all_metadata:
        xmp_payload = existing_chunk_payload(chunks, XMP_CHUNK_ID) or empty_xmp_packet()
        xmp_result = apply_xmp_property_write_plan(xmp_payload, xmp_plan)
        chunks = upsert_webp_chunk(chunks, XMP_CHUNK_ID, xmp_result.packet)
        changed_xmp_properties = xmp_result.changed_properties
    chunks = update_vp8x_chunks(chunks)
    return WebpMetadataRewriteResult(
        data=encode_webp_chunks(chunks),
        changed_exif_properties=changed_exif_properties,
        changed_xmp_properties=changed_xmp_properties,
        deleted_metadata_chunks=deleted_chunks,
    )


def parse_webp_chunks(webp_data: bytes) -> tuple[RiffChunk, ...]:
    if len(webp_data) < 12 or webp_data[:4] != b"RIFF" or webp_data[8:12] != WEBP_FORM_TYPE:
        raise ValueError("Input is not a RIFF WebP file.")
    chunks: list[RiffChunk] = []
    offset = 12
    while offset + 8 <= len(webp_data):
        chunk_id = webp_data[offset : offset + 4]
        payload_length = int.from_bytes(webp_data[offset + 4 : offset + 8], "little")
        payload_start = offset + 8
        payload_end = payload_start + payload_length
        if payload_end > len(webp_data):
            raise ValueError(f"Truncated RIFF chunk {chunk_id!r}.")
        if payload_end + (payload_length & 1) > len(webp_data):
            raise ValueError(f"Missing RIFF padding for odd-sized chunk {chunk_id!r}.")
        chunks.append(RiffChunk(chunk_id, webp_data[payload_start:payload_end]))
        offset = payload_end + (payload_length & 1)
    if offset != len(webp_data):
        raise ValueError("Trailing bytes are not enough to form a RIFF chunk header.")
    return tuple(chunks)


def encode_webp_chunks(chunks: tuple[RiffChunk, ...]) -> bytes:
    encoded_chunks = b"".join(encode_riff_chunk(chunk) for chunk in chunks)
    riff_size = len(WEBP_FORM_TYPE) + len(encoded_chunks)
    return b"RIFF" + riff_size.to_bytes(4, "little") + WEBP_FORM_TYPE + encoded_chunks


def encode_riff_chunk(chunk: RiffChunk) -> bytes:
    padding = b"\x00" if len(chunk.payload) & 1 else b""
    return chunk.chunk_id + len(chunk.payload).to_bytes(4, "little") + chunk.payload + padding


def existing_chunk_payload(chunks: tuple[RiffChunk, ...], chunk_id: bytes) -> bytes | None:
    for chunk in chunks:
        if chunk.chunk_id == chunk_id:
            return chunk.payload
    return None


def rewritten_exif_chunk(
    chunks: tuple[RiffChunk, ...],
    plan: ExifScalarWritePlan,
) -> bytes:
    existing = existing_chunk_payload(chunks, EXIF_CHUNK_ID)
    if existing is None:
        return create_minimal_exif_scalar_tiff(plan)
    return rewrite_exif_scalars_creating_if_needed(existing, plan)


def upsert_webp_chunk(
    chunks: tuple[RiffChunk, ...],
    chunk_id: bytes,
    payload: bytes,
) -> tuple[RiffChunk, ...]:
    replacement = RiffChunk(chunk_id, payload)
    updated: list[RiffChunk] = []
    replaced = False
    for chunk in chunks:
        if chunk.chunk_id == chunk_id:
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(chunk)
    if replaced:
        return tuple(updated)
    if chunk_id == EXIF_CHUNK_ID:
        inserted: list[RiffChunk] = []
        for index, chunk in enumerate(updated):
            if chunk.chunk_id == XMP_CHUNK_ID:
                inserted.append(replacement)
                inserted.extend(updated[index:])
                return tuple(inserted)
            inserted.append(chunk)
    return (*updated, replacement)


def update_vp8x_chunks(chunks: tuple[RiffChunk, ...]) -> tuple[RiffChunk, ...]:
    has_vp8x = any(chunk.chunk_id == VP8X_CHUNK_ID for chunk in chunks)
    needs_vp8x = webp_chunks_need_vp8x(chunks)
    if has_vp8x and not needs_vp8x:
        return tuple(chunk for chunk in chunks if chunk.chunk_id != VP8X_CHUNK_ID)
    if needs_vp8x and not has_vp8x:
        dimensions = webp_image_dimensions(chunks)
        if dimensions is None:
            return chunks
        return (create_vp8x_chunk(chunks, dimensions), *chunks)
    return tuple(update_vp8x_chunk(chunk, chunks) for chunk in chunks)


def update_vp8x_chunk(chunk: RiffChunk, chunks: tuple[RiffChunk, ...]) -> RiffChunk:
    if chunk.chunk_id != VP8X_CHUNK_ID:
        return chunk
    if len(chunk.payload) < VP8X_PAYLOAD_SIZE:
        raise ValueError("Truncated VP8X chunk.")
    flags = int.from_bytes(chunk.payload[:4], "little")
    flags = set_vp8x_feature_flags(flags, chunks)
    return replace(chunk, payload=flags.to_bytes(4, "little") + chunk.payload[4:])


def create_vp8x_chunk(
    chunks: tuple[RiffChunk, ...],
    dimensions: tuple[int, int],
) -> RiffChunk:
    width, height = dimensions
    flags = set_vp8x_creation_flags(chunks)
    payload = flags.to_bytes(4, "little") + encode_uint24(width - 1) + encode_uint24(height - 1)
    return RiffChunk(VP8X_CHUNK_ID, payload)


def set_vp8x_feature_flags(flags: int, chunks: tuple[RiffChunk, ...]) -> int:
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    flags = set_or_clear_flag(flags, WEBP_FLAG_XMP, XMP_CHUNK_ID in chunk_ids)
    flags = set_or_clear_flag(flags, WEBP_FLAG_EXIF, EXIF_CHUNK_ID in chunk_ids)
    flags = set_or_clear_flag(flags, WEBP_FLAG_ICC, ICC_CHUNK_ID in chunk_ids)
    return flags


def set_vp8x_creation_flags(chunks: tuple[RiffChunk, ...]) -> int:
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    flags = set_vp8x_feature_flags(0, chunks)
    flags = set_or_clear_flag(flags, WEBP_FLAG_ANIMATION, ANIM_CHUNK_ID in chunk_ids)
    flags = set_or_clear_flag(
        flags,
        WEBP_FLAG_ALPHA,
        ALPH_CHUNK_ID in chunk_ids or any_vp8l_chunk_has_alpha(chunks),
    )
    return flags


def webp_chunks_need_vp8x(chunks: tuple[RiffChunk, ...]) -> bool:
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    return bool(
        chunk_ids
        & {
            ANIM_CHUNK_ID,
            XMP_CHUNK_ID,
            EXIF_CHUNK_ID,
            ALPH_CHUNK_ID,
            ICC_CHUNK_ID,
        }
    ) or any_vp8l_chunk_has_alpha(chunks)


def any_vp8l_chunk_has_alpha(chunks: tuple[RiffChunk, ...]) -> bool:
    return any(
        chunk.chunk_id == VP8L_CHUNK_ID and vp8l_payload_has_alpha(chunk.payload)
        for chunk in chunks
    )


def vp8l_payload_has_alpha(payload: bytes) -> bool:
    if len(payload) < 6 or payload[:1] != b"\x2f":
        return False
    return bool(int.from_bytes(payload[2:6], "little") & 0x100000)


def webp_image_dimensions(chunks: tuple[RiffChunk, ...]) -> tuple[int, int] | None:
    for chunk in chunks:
        if chunk.chunk_id == VP8X_CHUNK_ID and len(chunk.payload) >= VP8X_PAYLOAD_SIZE:
            return (
                int.from_bytes(chunk.payload[4:7], "little") + 1,
                int.from_bytes(chunk.payload[7:10], "little") + 1,
            )
        if chunk.chunk_id == VP8_CHUNK_ID and len(chunk.payload) >= 10:
            if chunk.payload[3:6] == b"\x9d\x01\x2a":
                return (
                    int.from_bytes(chunk.payload[6:8], "little") & 0x3FFF,
                    int.from_bytes(chunk.payload[8:10], "little") & 0x3FFF,
                )
        if chunk.chunk_id == VP8L_CHUNK_ID and len(chunk.payload) >= 6:
            if chunk.payload[:1] == b"\x2f":
                word = int.from_bytes(chunk.payload[2:6], "little")
                return (
                    (int.from_bytes(chunk.payload[1:3], "little") & 0x3FFF) + 1,
                    ((word >> 6) & 0x3FFF) + 1,
                )
    return None


def encode_uint24(value: int) -> bytes:
    return value.to_bytes(3, "little")


def set_or_clear_flag(flags: int, flag: int, enabled: bool) -> int:
    if enabled:
        return flags | flag
    return flags & ~flag
