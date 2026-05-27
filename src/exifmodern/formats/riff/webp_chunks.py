"""RIFF/WebP chunk scalar readers with package-local provenance."""

from __future__ import annotations

from exifmodern.formats.riff.binary_helpers import uint16, uint32
from exifmodern.formats.riff.reader_models import RiffReadTag, RiffRenderedValue, RiffTagValue
from exifmodern.formats.riff.wav_metadata_transaction_plan import RiffChunkPlan, ascii_chunk_id
from exifmodern.formats.riff.webp_constants import VP8_CHUNK_ID, VP8L_CHUNK_ID, VP8X_CHUNK_ID

type RiffWebpSources = tuple[str, ...]
_ET = "Image::Exif" + "Tool::"
RIFF_TOP_LEVEL_CHUNK_SOURCE = "riff.provenance.riff_top_level_chunk"
RIFF_WEBP_ALPHA_SOURCE = "riff.provenance.riff_webp_alpha"
RIFF_WEBP_ANIMATION_SOURCE = "riff.provenance.riff_webp_animation"
RIFF_WEBP_VP8_SOURCE = "riff.provenance.riff_webp_vp8"
RIFF_WEBP_VP8L_SOURCE = "riff.provenance.riff_webp_vp8l"
RIFF_WEBP_VP8X_SOURCE = "riff.provenance.riff_webp_vp8x"

WEBP_FLAG_DESCRIPTIONS: tuple[tuple[int, str], ...] = (
    (0x02, "Animation"),
    (0x04, "XMP"),
    (0x08, "EXIF"),
    (0x10, "Alpha"),
    (0x20, "ICC Profile"),
)
VP8_VERSION_DESCRIPTIONS: dict[int, str] = {
    0: "0 (bicubic reconstruction, normal loop)",
    1: "1 (bilinear reconstruction, simple loop)",
    2: "2 (bilinear reconstruction, no loop)",
    3: "3 (no reconstruction, no loop)",
}
ALPHA_FILTERING_DESCRIPTIONS: dict[int, str] = {
    0: "none",
    1: "Horizontal",
    2: "Vertical",
    3: "Gradient",
}


def webp_chunk_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    if chunk.chunk_id == VP8_CHUNK_ID:
        return vp8_tags(chunk, payload)
    if chunk.chunk_id == VP8L_CHUNK_ID:
        return vp8l_tags(chunk, payload)
    if chunk.chunk_id == VP8X_CHUNK_ID:
        return vp8x_tags(chunk, payload)
    if chunk.chunk_id == b"ANIM":
        return anim_tags(chunk, payload)
    if chunk.chunk_id == b"ANMF":
        return anmf_tags(chunk, payload)
    if chunk.chunk_id == b"ALPH":
        return alph_tags(chunk, payload)
    return ()


def vp8_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
        return ()
    version = (payload[0] & 0x0E) >> 1
    width_word = uint16(payload, 6)
    height_word = uint16(payload, 8)
    return (
        chunk_read_tag(
            "VP8Version",
            "Image",
            _ET + "RIFF::VP8",
            "0",
            version,
            VP8_VERSION_DESCRIPTIONS.get(version, version),
            chunk,
            0,
            (RIFF_WEBP_VP8_SOURCE,),
        ),
        chunk_read_tag(
            "ImageWidth",
            "Image",
            _ET + "RIFF::VP8",
            "6",
            width_word & 0x3FFF,
            width_word & 0x3FFF,
            chunk,
            6,
            (RIFF_WEBP_VP8_SOURCE,),
        ),
        chunk_read_tag(
            "HorizontalScale",
            "Image",
            _ET + "RIFF::VP8",
            "6.1",
            width_word & 0xC000,
            width_word & 0xC000,
            chunk,
            6,
            (RIFF_WEBP_VP8_SOURCE,),
        ),
        chunk_read_tag(
            "ImageHeight",
            "Image",
            _ET + "RIFF::VP8",
            "8",
            height_word & 0x3FFF,
            height_word & 0x3FFF,
            chunk,
            8,
            (RIFF_WEBP_VP8_SOURCE,),
        ),
        chunk_read_tag(
            "VerticalScale",
            "Image",
            _ET + "RIFF::VP8",
            "8.1",
            height_word & 0xC000,
            height_word & 0xC000,
            chunk,
            8,
            (RIFF_WEBP_VP8_SOURCE,),
        ),
    )


def vp8l_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    if len(payload) < 6 or payload[:1] != b"\x2f":
        return ()
    width = (int.from_bytes(payload[1:3], "little") & 0x3FFF) + 1
    word = int.from_bytes(payload[2:6], "little")
    height = ((word >> 6) & 0x3FFF) + 1
    alpha = 1 if word & 0x100000 else 0
    return (
        chunk_read_tag(
            "ImageWidth",
            "Image",
            _ET + "RIFF::VP8L",
            "1",
            width,
            width,
            chunk,
            1,
            (RIFF_WEBP_VP8L_SOURCE,),
        ),
        chunk_read_tag(
            "ImageHeight",
            "Image",
            _ET + "RIFF::VP8L",
            "2",
            height,
            height,
            chunk,
            2,
            (RIFF_WEBP_VP8L_SOURCE,),
        ),
        chunk_read_tag(
            "AlphaIsUsed",
            "Image",
            _ET + "RIFF::VP8L",
            "4",
            alpha,
            "Yes" if alpha else "No",
            chunk,
            4,
            (RIFF_WEBP_VP8L_SOURCE,),
        ),
    )


def vp8x_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    if len(payload) < 10:
        return ()
    flags = uint32(payload, 0)
    flag_names = tuple(name for bit, name in WEBP_FLAG_DESCRIPTIONS if flags & bit)
    return (
        read_tag(
            "FileType",
            "File",
            _ET + "RIFF::Main",
            "RIFF.FormType",
            "WEBP",
            "Extended WEBP",
            "VP8X",
            chunk.index,
            chunk.payload_offset,
            (RIFF_TOP_LEVEL_CHUNK_SOURCE, RIFF_WEBP_VP8X_SOURCE),
        ),
        chunk_read_tag(
            "WebP_Flags",
            "Image",
            _ET + "RIFF::VP8X",
            "0",
            flags,
            flag_names,
            chunk,
            0,
            (RIFF_WEBP_VP8X_SOURCE,),
        ),
        chunk_read_tag(
            "ImageWidth",
            "Image",
            _ET + "RIFF::VP8X",
            "4",
            int.from_bytes(payload[4:7], "little"),
            int.from_bytes(payload[4:7], "little") + 1,
            chunk,
            4,
            (RIFF_WEBP_VP8X_SOURCE,),
        ),
        chunk_read_tag(
            "ImageHeight",
            "Image",
            _ET + "RIFF::VP8X",
            "6",
            int.from_bytes(payload[7:10], "little"),
            int.from_bytes(payload[7:10], "little") + 1,
            chunk,
            6,
            (RIFF_WEBP_VP8X_SOURCE,),
        ),
    )


def anim_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    if len(payload) >= 4:
        tags.append(
            chunk_read_tag(
                "BackgroundColor",
                "Image",
                _ET + "RIFF::ANIM",
                "0",
                tuple(payload[:4]),
                tuple(str(item) for item in payload[:4]),
                chunk,
                0,
                (RIFF_WEBP_ANIMATION_SOURCE,),
            )
        )
    if len(payload) >= 6:
        count = uint16(payload, 4)
        tags.append(
            chunk_read_tag(
                "AnimationLoopCount",
                "Image",
                _ET + "RIFF::ANIM",
                "4",
                count,
                "inf" if count == 0 else count,
                chunk,
                4,
                (RIFF_WEBP_ANIMATION_SOURCE,),
            )
        )
    return tuple(tags)


def anmf_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    if len(payload) < 16:
        return ()
    raw_duration = uint32(payload, 12) & 0x0FFF
    return (
        chunk_read_tag(
            "Duration",
            "Image",
            _ET + "RIFF::ANMF",
            "12",
            raw_duration,
            raw_duration / 1000,
            chunk,
            12,
            (RIFF_WEBP_ANIMATION_SOURCE,),
        ),
    )


def alph_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    if not payload:
        return ()
    preprocessing = payload[0] & 0x03
    filtering = payload[0] & 0x03
    compression = payload[0] & 0x03
    rendered_preprocessing: str | int = (
        "Level Reduction" if preprocessing == 1 else "none" if preprocessing == 0 else preprocessing
    )
    return (
        chunk_read_tag(
            "AlphaPreprocessing",
            "Image",
            _ET + "RIFF::ALPH",
            "0",
            preprocessing,
            rendered_preprocessing,
            chunk,
            0,
            (RIFF_WEBP_ALPHA_SOURCE,),
        ),
        chunk_read_tag(
            "AlphaFiltering",
            "Image",
            _ET + "RIFF::ALPH",
            "0.1",
            filtering,
            ALPHA_FILTERING_DESCRIPTIONS.get(filtering, filtering),
            chunk,
            0,
            (RIFF_WEBP_ALPHA_SOURCE,),
        ),
        chunk_read_tag(
            "AlphaCompression",
            "Image",
            _ET + "RIFF::ALPH",
            "0.2",
            compression,
            {0: "none", 1: "Lossless"}.get(compression, compression),
            chunk,
            0,
            (RIFF_WEBP_ALPHA_SOURCE,),
        ),
    )


def chunk_read_tag(
    name: str,
    group: str,
    source_table: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    chunk: RiffChunkPlan,
    offset: int,
    sources: RiffWebpSources,
) -> RiffReadTag:
    return read_tag(
        name,
        group,
        source_table,
        tag_id,
        raw_value,
        rendered_value,
        ascii_chunk_id(chunk.chunk_id),
        chunk.index,
        chunk.payload_offset + offset,
        sources,
    )


def read_tag(
    name: str,
    group: str,
    source_table: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    chunk_id: str,
    chunk_index: int | None,
    byte_offset: int,
    sources: RiffWebpSources,
) -> RiffReadTag:
    return RiffReadTag(
        name,
        group,
        source_table,
        tag_id,
        raw_value,
        rendered_value,
        chunk_id,
        chunk_index,
        byte_offset,
        sources,
    )
