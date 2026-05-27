"""Ogg page and comment transaction planning helpers."""

from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _read_value
from exifmodern.formats.flac import build_flac_read_graph
from exifmodern.formats.flac.vorbis_comment_transaction_plan import decode_exiftool_base64
from exifmodern.formats.ogg.page_comment_transaction_plan import (
    OGG_CAPTURE_PATTERN,
    OGG_MAIN_SOURCE,
    OGG_PAGE_COMMENT_TRANSACTION_SOURCES,
    OggFlacHandoffPlan,
    OggPacketRoutePlan,
    OggPageCommentTransactionBlocked,
    OggPageCommentTransactionPlan,
    OggPagePlan,
    OggVorbisCommentEntryPlan,
    build_ogg_flac_handoff,
    build_ogg_page_comment_transaction_plan,
    encode_vorbis_comment_payload,
    packet_route_payload,
    plan_ogg_page_comment_transaction,
    scan_ogg_pages,
)
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance
from exifmodern.signature_trie.signature import Pattern, Signature

OGG_EXIFTOOL_MAX_PACKETS_PER_STREAM = 2
OGG_FIXED_HEADER_SIZE = 27

__all__ = [
    "OGG_CAPTURE_PATTERN",
    "OGG_PAGE_COMMENT_TRANSACTION_SOURCES",
    "OggFlacHandoffPlan",
    "OggPageCommentTransactionBlocked",
    "OggPageCommentTransactionPlan",
    "build_ogg_flac_handoff",
    "build_ogg_page_comment_transaction_plan",
    "build_ogg_read_graph",
    "encode_vorbis_comment_payload",
    "invoke_ogg",
    "plan_ogg_page_comment_transaction",
    "scan_ogg_pages",
]


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


def build_ogg_read_graph(data: bytes, source_file: str, input_size: int | None = None) -> ReadGraph:
    plan = build_ogg_page_comment_transaction_plan(data)
    diagnostics: list[str] = [
        f"OGG package-local reader issue: {issue.code}: {issue.message}"
        for issue in plan.issues
        if _diagnostic_issue_is_read_blocker(issue.code, plan)
    ]
    diagnostics.extend(
        f"OGG package-local reader gate: {gate.code}"
        for gate in plan.emission_gates
        if not gate.passed and _diagnostic_gate_is_read_blocker(gate.code, plan)
    )
    tags: list[ReadTag] = _file_type_tags(plan)
    if (
        plan.flac_handoff.status == "assembled"
        and plan.flac_handoff.synthetic_flac_stream is not None
    ):
        flac_graph = build_flac_read_graph(plan.flac_handoff.synthetic_flac_stream, source_file)
        tags.extend(tag for tag in flac_graph.tags if tag.provenance.family_0_group != "File")
        diagnostics.extend(
            diagnostic
            for diagnostic in flac_graph.diagnostics
            if not diagnostic.startswith(
                "No complete metadata block with the last-metadata-block flag"
            )
        )
    elif plan.flac_handoff.issue is not None:
        diagnostics.append(
            "OGG package-local reader issue: "
            f"{plan.flac_handoff.issue.code}: {plan.flac_handoff.issue.message}"
        )
    ordinal = 0
    for route in plan.packet_routes:
        packet_payload = _route_payload(data, plan.pages, route)
        for name, value, tag_id in _codec_header_tags(route, packet_payload):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_provenance(
                        group="Opus" if route.codec == "opus" else "Vorbis",
                        table_name=(
                            "Image::ExifTool::Opus::Header"
                            if route.codec == "opus"
                            else "Image::ExifTool::Vorbis::Header"
                        ),
                        tag_id=tag_id,
                        evidence_ids=route.evidence_ids,
                        duplicate_instance_ordinal=ordinal,
                    ),
                    schema=None,
                )
            )
            ordinal += 1
    for route in plan.comment_routes:
        comment_parse = route.comment_parse
        if comment_parse.vendor is not None:
            tags.append(
                ReadTag(
                    name="Vendor",
                    value=_read_value(comment_parse.vendor),
                    provenance=_provenance(
                        group="Vorbis",
                        table_name="Image::ExifTool::Vorbis::Comments",
                        tag_id="Vendor",
                        evidence_ids=comment_parse.evidence_ids,
                        duplicate_instance_ordinal=ordinal,
                    ),
                    schema=None,
                )
            )
            ordinal += 1
        for entry in comment_parse.entries:
            if entry.routes_to_flac_picture:
                if entry.picture_comment is not None and entry.picture_comment.issue is not None:
                    diagnostics.append(
                        "OGG package-local reader issue: "
                        f"{entry.picture_comment.issue.code}: {entry.picture_comment.issue.message}"
                    )
                if entry.picture_comment is not None and entry.picture_comment.status == "decoded":
                    for picture_tag in _picture_comment_read_tags(entry, ordinal):
                        tags.append(picture_tag)
                        ordinal += 1
                continue
            tags.append(
                ReadTag(
                    name=_vorbis_comment_tag_name(entry.tag),
                    value=_read_value(_vorbis_comment_value(entry.tag, entry.value)),
                    provenance=_provenance(
                        group=_vorbis_comment_group(entry.tag),
                        table_name="Image::ExifTool::Vorbis::Comments",
                        tag_id=entry.tag,
                        evidence_ids=entry.evidence_ids,
                        duplicate_instance_ordinal=ordinal,
                    ),
                    schema=None,
                )
            )
            ordinal += 1
    tags.extend(_vorbis_composite_tags(input_size if input_size is not None else len(data), tags))
    return _graph(source_file, tags, diagnostics)


type VorbisCommentValue = str | int | bytes

VORBIS_COMMENT_TAG_NAMES: dict[str, str] = {
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
    "DIRECTOR": "Director",
    "PRODUCER": "Producer",
    "COMPOSER": "Composer",
    "ACTOR": "Actor",
    "ENCODER": "Encoder",
    "ENCODER_OPTIONS": "EncoderOptions",
}

VORBIS_COMMENT_AUTHOR_TAGS = {
    "ARTIST",
    "PERFORMER",
    "COPYRIGHT",
    "LICENSE",
    "ORGANIZATION",
    "CONTACT",
}


def _vorbis_comment_tag_name(tag: str) -> str:
    return VORBIS_COMMENT_TAG_NAMES.get(tag, _dynamic_vorbis_comment_name(tag))


def _dynamic_vorbis_comment_name(tag: str) -> str:
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


def _vorbis_comment_group(tag: str) -> str:
    if tag == "COVERART":
        return "Vorbis"
    if tag in VORBIS_COMMENT_AUTHOR_TAGS:
        return "Vorbis"
    if tag == "DATE":
        return "Vorbis"
    return "Vorbis"


def _vorbis_comment_value(tag: str, value: str) -> VorbisCommentValue:
    if tag == "COVERART":
        return decode_exiftool_base64(value) or value
    if tag in {"REPLAYGAIN_TRACK_GAIN", "REPLAYGAIN_ALBUM_GAIN"}:
        if value.endswith(" dB"):
            return value
        return f"{value} dB"
    if tag in {"DATE", "TRACKNUMBER"} or tag.replace(":", "_").endswith("DATE"):
        try:
            return str(int(value)) if tag == "MEDIAJUKEBOX_DATE" else int(value)
        except ValueError:
            return value
    return value


def _vorbis_composite_tags(data_size: int, tags: list[ReadTag]) -> tuple[ReadTag, ...]:
    nominal_bitrate: int | None = None
    sources: tuple[str, ...] = (OGG_MAIN_SOURCE,)
    for tag in tags:
        if tag.name != "NominalBitrate":
            continue
        if isinstance(tag.value, int | float):
            nominal_bitrate = int(tag.value) * 1000 if tag.value < 1000 else int(tag.value)
            sources = ()
            break
        if isinstance(tag.value, str) and tag.value.endswith(" kbps"):
            try:
                nominal_bitrate = int(float(tag.value.removesuffix(" kbps"))) * 1000
                sources = ()
                break
            except ValueError:
                pass
    if nominal_bitrate is None or nominal_bitrate <= 0:
        return ()
    duration = data_size * 8 / nominal_bitrate
    return (
        ReadTag(
            name="Duration",
            value=_read_value(f"{duration:.2f} s (approx)"),
            provenance=_provenance(
                group="Composite",
                table_name="Image::ExifTool::Vorbis::Composite",
                tag_id="Duration",
                evidence_ids=sources,
            ),
            schema=None,
        ),
    )


def _picture_comment_read_tags(
    entry: OggVorbisCommentEntryPlan, ordinal_start: int
) -> tuple[ReadTag, ...]:
    if entry.picture_comment is None:
        return ()
    tags: list[ReadTag] = []
    ordinal = ordinal_start
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
    return tuple(tags)


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


def _file_type_tags(plan: OggPageCommentTransactionPlan) -> list[ReadTag]:
    has_opus = any(route.codec == "opus" for route in plan.packet_routes)
    if has_opus:
        values = (
            ("FileType", "OPUS", "FileType"),
            ("FileTypeExtension", "opus", "FileTypeExtension"),
            ("MIMEType", "audio/ogg", "MIMEType"),
        )
    else:
        values = (
            ("FileType", "OGG", "FileType"),
            ("FileTypeExtension", "ogg", "FileTypeExtension"),
            ("MIMEType", "audio/ogg", "MIMEType"),
        )
    return [
        ReadTag(
            name=name,
            value=value,
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=tag_id,
                evidence_ids=(OGG_MAIN_SOURCE,),
            ),
            schema=None,
        )
        for name, value, tag_id in values
    ]


def _diagnostic_issue_is_read_blocker(code: str, plan: OggPageCommentTransactionPlan) -> bool:
    if code in {"truncated_segment_table", "truncated_page_payload", "truncated_page_header"}:
        return not plan.comment_routes
    return True


def _diagnostic_gate_is_read_blocker(code: str, plan: OggPageCommentTransactionPlan) -> bool:
    if code in {"ogg_crc_lacing_rewrite", "non_mutating_planner"}:
        return False
    return not (code == "page_header_lacing_traversal" and plan.comment_routes)


def _route_payload(data: bytes, pages: tuple[OggPagePlan, ...], route: OggPacketRoutePlan) -> bytes:
    return packet_route_payload(data, pages, route)


def _codec_header_tags(
    route: OggPacketRoutePlan, payload: bytes
) -> tuple[tuple[str, int | float | str, str], ...]:
    if (
        route.codec == "opus"
        and route.route_kind == "codec_header"
        and payload.startswith(b"OpusHead")
    ):
        if len(payload) < 19:
            return ()
        output_gain_raw = int.from_bytes(payload[16:18], "little", signed=True)
        return (
            ("OpusVersion", payload[8], "0"),
            ("AudioChannels", payload[9], "1"),
            ("SampleRate", int.from_bytes(payload[12:16], "little"), "4"),
            ("OutputGain", 10 ** (output_gain_raw / 5120), "8"),
        )
    if (
        route.codec == "vorbis"
        and route.route_kind == "codec_header"
        and payload[0:7] == b"\x01vorbis"
    ):
        if len(payload) < 30:
            return ()
        nominal_bitrate = int.from_bytes(payload[20:24], "little", signed=True)
        tags: list[tuple[str, int | float | str, str]] = [
            ("VorbisVersion", int.from_bytes(payload[7:11], "little"), "0"),
            ("AudioChannels", payload[11], "4"),
            ("SampleRate", int.from_bytes(payload[12:16], "little"), "5"),
        ]
        if nominal_bitrate:
            tags.append(("NominalBitrate", f"{round(nominal_bitrate / 1000)} kbps", "13"))
        return tuple(tags)
    return ()


def invoke_ogg(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_ogg_read_graph(
        _read_ogg_exiftool_header_pages(path, prefix),
        source_file,
        input_size=path.stat().st_size,
    )


def _read_ogg_exiftool_header_pages(path: Path, prefix: bytes) -> bytes:
    """Read Ogg pages through ExifTool's leading packet scan window."""

    if not prefix.startswith(OGG_CAPTURE_PATTERN):
        return prefix[: len(OGG_CAPTURE_PATTERN)]
    data = bytearray()
    packets = 0
    streams = 0
    buffered_streams: set[int] = set()
    num_flac: int | None = None
    with path.open("rb") as file:
        while True:
            header28 = file.read(28)
            if len(header28) != 28:
                if header28:
                    data.extend(header28)
                return bytes(data)
            if not header28.startswith(OGG_CAPTURE_PATTERN):
                data.extend(header28)
                return bytes(data)

            flag = header28[5]
            stream = int.from_bytes(header28[14:18], "little")
            if flag & 0x02:
                streams += 1
            if not flag & 0x01:
                packets += 1

            segment_count = header28[26]
            segment_lengths = [header28[27]]
            extra_segment_table = b""
            if segment_count:
                extra_segment_table = file.read(segment_count - 1)
                if len(extra_segment_table) != segment_count - 1:
                    data.extend(header28)
                    data.extend(extra_segment_table)
                    return bytes(data)
                segment_lengths.extend(extra_segment_table)
            else:
                segment_lengths = []
            payload_length = sum(segment_lengths)
            payload = file.read(payload_length)
            data.extend(header28)
            data.extend(extra_segment_table)
            data.extend(payload)
            if len(payload) != payload_length:
                return bytes(data)

            if payload.startswith(b"\x7fFLAC") and len(payload) >= 9:
                num_flac = int.from_bytes(payload[7:9], "big")
                buffered_streams.add(stream)
            elif _is_ogg_exiftool_packet_start(payload):
                buffered_streams.add(stream)

            if num_flac is not None:
                num_flac -= 1
                if num_flac <= 0:
                    return bytes(data)
            elif stream in buffered_streams and flag & 0x04:
                buffered_streams.remove(stream)

            if num_flac is None and streams > 0:
                if packets > OGG_EXIFTOOL_MAX_PACKETS_PER_STREAM * streams and not buffered_streams:
                    return bytes(data)


def _is_ogg_exiftool_packet_start(payload: bytes) -> bool:
    return (
        (len(payload) >= 7 and payload[1:7] in {b"vorbis", b"theora"})
        or payload.startswith(b"OpusHead")
        or payload.startswith(b"OpusTags")
    )


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="ogg",
        builder_ref="exifmodern.formats.ogg:invoke_ogg",
        patterns=(Pattern(0, b"OggS"),),
    ),
)
