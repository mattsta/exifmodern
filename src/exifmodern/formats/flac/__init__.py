"""FLAC container planning helpers."""

from __future__ import annotations

from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _read_value
from exifmodern.formats.flac.vorbis_comment_transaction_plan import (
    FLAC_BLOCK_APPLICATION,
    FLAC_BLOCK_PADDING,
    FLAC_BLOCK_PICTURE,
    FLAC_BLOCK_STREAMINFO,
    FLAC_BLOCK_VORBIS_COMMENT,
    FLAC_STREAM_MARKER,
    FlacEmissionGate,
    FlacMetadataBlockPlan,
    FlacOutputMetadataBlockPlan,
    FlacPaddingActionPlan,
    FlacPaddingStrategyPlan,
    FlacPictureCommentPlan,
    FlacPictureTagPlan,
    FlacPlanIssue,
    FlacVorbisCommentEntryPlan,
    FlacVorbisCommentParsePlan,
    FlacVorbisCommentRoutePlan,
    FlacVorbisCommentTransactionBlocked,
    FlacVorbisCommentTransactionPlan,
    build_flac_vorbis_comment_transaction_plan,
    decode_exiftool_base64,
    encode_vorbis_comment_payload,
    parse_flac_picture_payload,
    parse_metadata_block_picture_comment,
    plan_flac_vorbis_comment_transaction,
    scan_flac_metadata_blocks,
)
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "FLAC_BLOCK_APPLICATION",
    "FLAC_BLOCK_PADDING",
    "FLAC_BLOCK_PICTURE",
    "FLAC_BLOCK_STREAMINFO",
    "FLAC_BLOCK_VORBIS_COMMENT",
    "FLAC_STREAM_MARKER",
    "FlacEmissionGate",
    "FlacMetadataBlockPlan",
    "FlacOutputMetadataBlockPlan",
    "FlacPaddingActionPlan",
    "FlacPaddingStrategyPlan",
    "FlacPictureCommentPlan",
    "FlacPictureTagPlan",
    "FlacPlanIssue",
    "FlacVorbisCommentEntryPlan",
    "FlacVorbisCommentParsePlan",
    "FlacVorbisCommentRoutePlan",
    "FlacVorbisCommentTransactionBlocked",
    "FlacVorbisCommentTransactionPlan",
    "build_flac_read_graph",
    "build_flac_vorbis_comment_transaction_plan",
    "decode_exiftool_base64",
    "encode_vorbis_comment_payload",
    "invoke_flac",
    "parse_flac_picture_payload",
    "parse_metadata_block_picture_comment",
    "plan_flac_vorbis_comment_transaction",
    "scan_flac_metadata_blocks",
]


type FlacCommentValue = str | float | bytes

FLAC_VORBIS_COMMENT_TAG_NAMES: dict[str, str] = {
    "TITLE": "Title",
    "VERSION": "Version",
    "ALBUM": "Album",
    "TRACKNUMBER": "TrackNumber",
    "ARTIST": "Artist",
    "PERFORMER": "Performer",
    "COPYRIGHT": "Copyright",
    "LICENSE": "License",
    "ORGANIZATION": "Organization",
    "DESCRIPTION": "Description",
    "GENRE": "Genre",
    "DATE": "Date",
    "LOCATION": "Location",
    "CONTACT": "Contact",
    "ISRC": "ISRCNumber",
    "COVERARTMIME": "CoverArtMIMEType",
    "COVERART": "CoverArt",
    "REPLAYGAIN_TRACK_PEAK": "ReplayGainTrackPeak",
    "REPLAYGAIN_TRACK_GAIN": "ReplayGainTrackGain",
    "REPLAYGAIN_ALBUM_PEAK": "ReplayGainAlbumPeak",
    "REPLAYGAIN_ALBUM_GAIN": "ReplayGainAlbumGain",
    "ENCODED_USING": "EncodedUsing",
    "ENCODED_BY": "EncodedBy",
    "COMMENT": "Comment",
    "ENCODER": "Encoder",
    "ENCODER_OPTIONS": "EncoderOptions",
}


def _provenance(
    *,
    group: str,
    table_name: str,
    tag_id: str | None,
    evidence_ids: tuple[str, ...] = (),
    family_1_group: str | None = None,
    family_2_group: str | None = None,
    family_3_group: str | None = None,
    duplicate_instance_ordinal: int | None = None,
) -> TagProvenance:
    return TagProvenance(
        group=group,
        table_name=table_name,
        tag_id=tag_id,
        source=evidence_ids[0] if evidence_ids else "package-local-reader-plan",
        family_0_group=group,
        family_1_group=group if family_1_group is None else family_1_group,
        family_2_group=_family_2_group(group) if family_2_group is None else family_2_group,
        family_3_group=family_3_group,
        duplicate_instance_ordinal=duplicate_instance_ordinal,
    )


def _family_2_group(group: str) -> str:
    if group in {"Audio", "Video", "Image"}:
        return group
    return "Other"


def build_flac_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_flac_vorbis_comment_transaction_plan(data)
    diagnostics = [issue.message for issue in plan.issues]
    tags = _flac_file_type_tags()
    ordinal = len(tags)
    for block in plan.terminal_blocks:
        if block.status != "parsed":
            if block.issue is not None:
                diagnostics.append(block.issue.message)
            continue
        for stream_tag in block.stream_info_tags:
            if stream_tag.status == "parsed" and (
                stream_tag.kind != "duration" or stream_tag.rendered_value
            ):
                tags.append(
                    ReadTag(
                        name=stream_tag.tag_name,
                        value=_read_value(stream_tag.rendered_value),
                        provenance=_provenance(
                            group="FLAC",
                            table_name="Image::ExifTool::FLAC::StreamInfo",
                            tag_id=stream_tag.kind,
                            evidence_ids=stream_tag.evidence_ids,
                            duplicate_instance_ordinal=ordinal,
                        ),
                        schema=None,
                    )
                )
                ordinal += 1
        for picture_tag in block.picture_tags:
            if picture_tag.status == "parsed":
                tags.append(
                    ReadTag(
                        name=picture_tag.tag_name,
                        value=_read_value(picture_tag.rendered_value),
                        provenance=_provenance(
                            group="FLAC",
                            table_name="Image::ExifTool::FLAC::Picture",
                            tag_id=_flac_picture_tag_id(picture_tag.kind),
                            evidence_ids=picture_tag.evidence_ids,
                            duplicate_instance_ordinal=ordinal,
                        ),
                        schema=None,
                    )
                )
                ordinal += 1
    parse = plan.vorbis_route.original_parse
    if parse.issue is not None:
        diagnostics.append(parse.issue.message)
    if parse.vendor is not None:
        tags.append(
            ReadTag(
                name="Vendor",
                value=_read_value(parse.vendor),
                provenance=_provenance(
                    group="Vorbis",
                    table_name="Image::ExifTool::Vorbis::Comments",
                    tag_id="vendor",
                    evidence_ids=parse.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
        ordinal += 1
    for entry in parse.entries:
        if entry.routes_to_flac_picture:
            if entry.picture_comment is not None and entry.picture_comment.issue is not None:
                diagnostics.append(entry.picture_comment.issue.message)
            if entry.picture_comment is not None and entry.picture_comment.status == "decoded":
                for picture_tag in entry.picture_comment.picture_tags:
                    if picture_tag.status != "parsed":
                        continue
                    tags.append(
                        ReadTag(
                            name=picture_tag.tag_name,
                            value=_read_value(picture_tag.rendered_value),
                            provenance=_provenance(
                                group="FLAC",
                                table_name="Image::ExifTool::FLAC::Picture",
                                tag_id=_flac_picture_tag_id(picture_tag.kind),
                                evidence_ids=entry.picture_comment.evidence_ids,
                                duplicate_instance_ordinal=ordinal,
                            ),
                            schema=None,
                        )
                    )
                    ordinal += 1
            continue
        tags.append(
            ReadTag(
                name=_flac_vorbis_comment_tag_name(entry.tag),
                value=_read_value(_flac_vorbis_comment_value(entry.tag, entry.value)),
                provenance=_provenance(
                    group="Vorbis",
                    table_name="Image::ExifTool::Vorbis::Comments",
                    tag_id=entry.tag,
                    evidence_ids=entry.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
        ordinal += 1
    return _graph(source_file, tags, diagnostics)


def _flac_file_type_tags() -> list[ReadTag]:
    return [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=name,
                evidence_ids=(),
            ),
            schema=None,
        )
        for name, value in (
            ("FileType", "FLAC"),
            ("FileTypeExtension", "flac"),
            ("MIMEType", "audio/flac"),
        )
    ]


def _flac_picture_tag_id(kind: str) -> str:
    tag_ids = {
        "picture_type": "0",
        "picture_mime_type": "1",
        "picture_description": "2",
        "picture_width": "3",
        "picture_height": "4",
        "picture_bits_per_pixel": "5",
        "picture_indexed_colors": "6",
        "picture_length": "7",
        "picture": "8",
    }
    return tag_ids[kind]


def _flac_vorbis_comment_tag_name(tag: str) -> str:
    return FLAC_VORBIS_COMMENT_TAG_NAMES.get(tag, _dynamic_flac_vorbis_comment_name(tag))


def _dynamic_flac_vorbis_comment_name(tag: str) -> str:
    name_parts: list[str] = []
    capitalize_next = True
    for char in tag.lower():
        if char.isalnum() or char in {"_", "-"}:
            if char == "_":
                capitalize_next = True
                continue
            name_parts.append(char.upper() if capitalize_next else char)
            capitalize_next = False
            continue
        capitalize_next = True
    return "".join(name_parts)


def _flac_vorbis_comment_value(tag: str, value: str) -> FlacCommentValue:
    if tag == "COVERART":
        return decode_exiftool_base64(value) or value
    if tag in {"REPLAYGAIN_TRACK_PEAK", "REPLAYGAIN_ALBUM_PEAK"}:
        try:
            return float(value)
        except ValueError:
            return value
    if tag in {"REPLAYGAIN_TRACK_GAIN", "REPLAYGAIN_ALBUM_GAIN"}:
        if value.endswith(" dB"):
            return value
        return f"{value} dB"
    return value


def invoke_flac(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_flac_read_graph(_read_flac_metadata_prefix(path, prefix), source_file)


def _read_flac_metadata_prefix(path: Path, prefix: bytes) -> bytes:
    """Read only ExifTool's FLAC signature plus metadata-block chain."""

    data = bytearray(prefix[: len(FLAC_STREAM_MARKER)])
    if bytes(data) != FLAC_STREAM_MARKER:
        return bytes(data)
    with path.open("rb") as file:
        file.seek(len(FLAC_STREAM_MARKER))
        while True:
            header = file.read(4)
            if len(header) != 4:
                data.extend(header)
                return bytes(data)
            data.extend(header)
            size = int.from_bytes(header[1:4], "big")
            payload = file.read(size)
            data.extend(payload)
            if len(payload) != size or header[0] & 0x80:
                return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="flac",
        builder_ref="exifmodern.formats.flac:invoke_flac",
        patterns=(Pattern(0, b"fLaC"),),
    ),
)
