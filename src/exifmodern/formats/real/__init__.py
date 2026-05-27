"""RealMedia planning helpers."""

from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from exifmodern.formats.real.media_transaction_plan import (
    REAL_HEADER_SIZE,
    REAL_MEDIA_PROPS_TABLE_SOURCE,
    REAL_PROCESS_SOURCE,
    RealMediaTransactionPlan,
    RealNameValuePropertyPlan,
    RealRewriteRequest,
    RealStreamPlan,
    build_real_media_transaction_plan,
)
from exifmodern.read_graph import ReadTag, TagProvenance
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = [
    "RealMediaTransactionPlan",
    "RealRewriteRequest",
    "build_real_media_transaction_plan",
    "build_real_read_graph",
    "invoke_real",
]


_REAL_CONTENT_TABLE = "Image::ExifTool::Real::ContentDescr"
_REAL_PROPERTIES_TABLE = "Image::ExifTool::Real::Properties"
_REAL_METADATA_TABLE = "Image::ExifTool::Real::Metadata"
_REAL_AUDIO_TABLE = "Image::ExifTool::Real::Audio"
_REAL_MEDIA_PROPS_TABLE = "Image::ExifTool::Real::MediaProps"
_ID3_V1_TABLE = "Image::ExifTool::ID3::v1"
_REAL_FILE_TYPES: dict[str, tuple[str, str, str]] = {
    "RM": ("RM", "rm", "audio/x-pn-realaudio"),
    "RA": ("RA", "ra", "audio/x-pn-realaudio"),
    "RAM": ("RAM", "ram", "audio/x-pn-realaudio"),
    "RPM": ("RPM", "rpm", "audio/x-pn-realaudio-plugin"),
}
_FILE_SOURCE = (REAL_PROCESS_SOURCE,)
_ID3_SOURCE = (REAL_PROCESS_SOURCE,)
_GENRES = {78: "Rock & Roll"}


def build_real_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a RealMedia transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _read_value

    extension = Path(source_file).suffix.removeprefix(".")
    plan = build_real_media_transaction_plan(data, file_extension=extension)
    diagnostics = [
        f"Real package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"Real package-local reader status: {plan.status}")

    tags: list[ReadTag] = []
    for name, file_value in _file_tags(plan):
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(file_value),
                provenance=_real_provenance(
                    group="File",
                    table_name="Image::ExifTool::File",
                    tag_id=name,
                    family_1_group="File",
                    evidence_ids=_FILE_SOURCE,
                ),
                schema=None,
            )
        )
    for prop in plan.prop_fields:
        property_value = _render_prop_value(prop.name, prop.value)
        if property_value is None:
            continue
        tags.append(
            ReadTag(
                name=prop.name,
                value=_read_value(property_value),
                provenance=_real_provenance(
                    group="Other",
                    table_name=_REAL_PROPERTIES_TABLE,
                    tag_id=prop.name,
                    family_1_group="Real-PROP",
                    evidence_ids=prop.evidence_ids,
                ),
                schema=None,
            )
        )
    for stream_index, stream in enumerate(plan.streams, start=1):
        family_1_group = "Real-MDPR" if stream_index == 1 else f"Real-MDPR{stream_index}"
        for name, stream_value in _stream_tags(stream):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(stream_value),
                    provenance=_real_provenance(
                        group="Other",
                        table_name=_REAL_MEDIA_PROPS_TABLE,
                        tag_id=name,
                        family_1_group=family_1_group,
                        evidence_ids=stream.evidence_ids,
                    ),
                    schema=None,
                )
            )
        for prop_name, prop_value in _logical_file_info_tags(stream.file_info_properties):
            tags.append(
                ReadTag(
                    name=prop_name,
                    value=_read_value(prop_value),
                    provenance=_real_provenance(
                        group="Other",
                        table_name=_REAL_MEDIA_PROPS_TABLE,
                        tag_id=prop_name,
                        family_1_group=family_1_group,
                        evidence_ids=(REAL_MEDIA_PROPS_TABLE_SOURCE,),
                    ),
                    schema=None,
                )
            )
    id3_tags = _id3v1_tags(data)
    for cdesc in plan.content_descriptions:
        for name, content_value in (
            ("Title", cdesc.title),
            ("Author", cdesc.author),
            ("Copyright", cdesc.copyright),
            ("Comment", cdesc.comment),
        ):
            if content_value is None:
                continue
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(content_value),
                    provenance=_real_provenance(
                        group="Other",
                        table_name=_REAL_CONTENT_TABLE,
                        tag_id=name,
                        family_1_group="Real-CONT",
                        evidence_ids=cdesc.evidence_ids,
                    ),
                    schema=None,
                )
            )
    for surface in plan.metadata_surfaces:
        for metadata_entry in surface.values:
            metadata_value: int | str | None
            if metadata_entry.text_value is not None:
                metadata_value = metadata_entry.text_value
            elif metadata_entry.int_value is not None:
                metadata_value = metadata_entry.int_value
            else:
                continue
            tags.append(
                ReadTag(
                    name=_real_metadata_name(metadata_entry.tag_path),
                    value=_read_value(metadata_value),
                    provenance=_real_provenance(
                        group="Other",
                        table_name=_REAL_METADATA_TABLE,
                        tag_id=_real_metadata_name(metadata_entry.tag_path),
                        family_1_group="Real-RJMD",
                        evidence_ids=metadata_entry.evidence_ids,
                    ),
                    schema=None,
                )
            )
    if plan.audio is not None:
        for scalar in plan.audio.scalars:
            scalar_value = scalar.value
            if scalar_value is None or scalar_value == "":
                continue
            rendered_scalar = (
                str(scalar_value) if isinstance(scalar_value, list | tuple | dict) else scalar_value
            )
            tags.append(
                ReadTag(
                    name=scalar.tag_name,
                    value=_read_value(rendered_scalar),
                    provenance=_real_provenance(
                        group="Audio",
                        table_name=scalar.table_name or _REAL_AUDIO_TABLE,
                        tag_id=scalar.tag_name,
                        family_1_group=f"Real-RA{plan.audio.version}",
                        evidence_ids=scalar.evidence_ids,
                    ),
                    schema=None,
                )
            )
    for metafile_entry in plan.metafile_entries:
        tags.append(
            ReadTag(
                name="URL" if metafile_entry.tag == "url" else "Text",
                value=_read_value(metafile_entry.text),
                provenance=_real_provenance(
                    group="Other",
                    table_name="Image::ExifTool::Real::Metafile",
                    tag_id=metafile_entry.tag,
                    family_1_group="Real",
                    evidence_ids=metafile_entry.evidence_ids,
                    duplicate_instance_ordinal=metafile_entry.index,
                ),
                schema=None,
            )
        )
    tags.extend(id3_tags)
    if id3_tags:
        year_tag = next((tag for tag in id3_tags if tag.name == "Year"), None)
        if year_tag is not None:
            tags.append(
                ReadTag(
                    name="DateTimeOriginal",
                    value=year_tag.value,
                    provenance=_real_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="DateTimeOriginal",
                        family_1_group="Composite",
                        evidence_ids=_ID3_SOURCE,
                    ),
                    schema=None,
                )
            )
    return _graph(source_file, tags, diagnostics)


def _file_tags(plan: RealMediaTransactionPlan) -> tuple[tuple[str, str], ...]:
    if plan.file_kind is None:
        return ()
    values = _REAL_FILE_TYPES[plan.file_kind]
    return (
        ("FileType", values[0]),
        ("FileTypeExtension", values[1]),
        ("MIMEType", plan.stream_mime_types[0] if len(plan.stream_mime_types) == 1 else values[2]),
    )


def _render_prop_value(name: str, value: int) -> int | str | None:
    if name in {"IndexOffset", "DataOffset"}:
        return None
    if name in {"MaxBitrate", "AvgBitrate"}:
        return _render_bitrate(value)
    if name in {"Duration", "Preroll"}:
        return _render_duration(value)
    if name == "Flags":
        names = []
        for bit, label in (
            (0, "Allow Recording"),
            (1, "Perfect Play"),
            (2, "Live"),
            (3, "Allow Download"),
        ):
            if value & (1 << bit):
                names.append(label)
        return ", ".join(names) if names else 0
    return value


def _stream_tags(stream: RealStreamPlan) -> tuple[tuple[str, int | str], ...]:
    payload = stream.preserved_payload
    values: list[tuple[str, int | str]] = []
    for name, offset, size, renderer in (
        ("StreamNumber", 0, 2, "int"),
        ("StreamMaxBitrate", 2, 4, "bitrate"),
        ("StreamAvgBitrate", 6, 4, "bitrate"),
        ("StreamMaxPacketSize", 10, 4, "int"),
        ("StreamAvgPacketSize", 14, 4, "int"),
        ("StreamStartTime", 18, 4, "int"),
        ("StreamPreroll", 22, 4, "duration"),
        ("StreamDuration", 26, 4, "duration"),
    ):
        if offset + size > len(payload):
            continue
        raw_value = int.from_bytes(payload[offset : offset + size], "big")
        if renderer == "bitrate":
            values.append((name, _render_bitrate(raw_value)))
        elif renderer == "duration":
            values.append((name, _render_duration(raw_value)))
        else:
            values.append((name, raw_value))
    if stream.stream_name:
        values.append(("StreamName", stream.stream_name))
    if stream.mime_type is not None:
        values.append(("StreamMimeType", stream.mime_type))
    if stream.mime_type == "logical-fileinfo":
        values.append(("FileInfoVersion", 0))
    return tuple(values)


def _logical_file_info_tags(
    properties: tuple[RealNameValuePropertyPlan, ...],
) -> tuple[tuple[str, int | str], ...]:
    values: list[tuple[str, int | str]] = []
    for prop in properties:
        tag_name = _logical_property_name(prop.tag)
        tag_value: int | str | None
        if prop.text_value is not None:
            tag_value = _logical_property_value(tag_name, prop.text_value)
        elif prop.int_values:
            tag_value = _logical_property_value(tag_name, prop.int_values[0])
        else:
            tag_value = None
        if tag_value is not None:
            values.append((tag_name, tag_value))
    return tuple(values)


def _logical_property_name(name: str) -> str:
    return {
        "Content Rating": "ContentRating",
        "audioMode": "AudioMode",
        "Creation Date": "CreateDate",
        "Generated By": "Software",
        "Modification Date": "ModifyDate",
        "videoMode": "VideoMode",
    }.get(name, name.replace(" ", ""))


def _logical_property_value(name: str, value: int | str) -> int | str:
    if name == "ContentRating" and value == 1:
        return "All Ages"
    if name in {"CreateDate", "ModifyDate"} and isinstance(value, str):
        parts = value.split(" ", 1)
        if len(parts) == 2:
            date_parts = parts[0].split("/")
            time_parts = parts[1].split(":")
            if len(date_parts) == 3:
                rendered_time = (
                    f"{int(time_parts[0]):02d}:{int(time_parts[1]):02d}:{int(time_parts[2]):02d}"
                    if len(time_parts) == 3
                    else parts[1]
                )
                rendered_date = f"{date_parts[2]}:{int(date_parts[1]):02d}:{int(date_parts[0]):02d}"
                return f"{rendered_date} {rendered_time}"
    return value


def _real_metadata_name(tag_path: str) -> str:
    mapped = {
        "Album/Name": "AlbumName",
        "Track/Category": "TrackCategory",
        "Track/Comments": "TrackComments",
        "Track/Lyrics": "TrackLyrics",
    }.get(tag_path, tag_path)
    return "".join(character for character in mapped if character.isalnum())


def _id3v1_tags(data: bytes) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _read_value

    if len(data) < 128:
        return []
    footer = data[-128:]
    if not footer.startswith(b"TAG"):
        return []
    raw_values: tuple[tuple[str, bytes], ...] = (
        ("Title", footer[3:33]),
        ("Artist", footer[33:63]),
        ("Album", footer[63:93]),
        ("Year", footer[93:97]),
        ("Comment", footer[97:127]),
    )
    tags = [
        ReadTag(
            name=name,
            value=_read_value(_decode_id3_text(value)),
            provenance=_real_provenance(
                group="Audio",
                table_name=_ID3_V1_TABLE,
                tag_id=name,
                family_1_group="ID3v1",
                evidence_ids=_ID3_SOURCE,
            ),
            schema=None,
        )
        for name, value in raw_values
        if _decode_id3_text(value)
    ]
    genre = _GENRES.get(footer[127], footer[127])
    tags.append(
        ReadTag(
            name="Genre",
            value=_read_value(genre),
            provenance=_real_provenance(
                group="Audio",
                table_name=_ID3_V1_TABLE,
                tag_id="Genre",
                family_1_group="ID3v1",
                evidence_ids=_ID3_SOURCE,
            ),
            schema=None,
        )
    )
    return tags


def _decode_id3_text(value: bytes) -> str:
    return value.rstrip(b"\x00 ").decode("latin-1", errors="replace")


def _render_bitrate(value: int) -> str:
    if value < 1000:
        return f"{value} bps"
    return f"{int(value / 1000 + 0.5)} kbps"


def _render_duration(milliseconds: int) -> str:
    if milliseconds == 0:
        return "0 s"
    return f"{milliseconds / 1000:.2f} s"


def _real_provenance(
    *,
    group: str,
    table_name: str,
    tag_id: str | None,
    family_1_group: str,
    evidence_ids: tuple[str, ...],
    duplicate_instance_ordinal: int | None = None,
) -> TagProvenance:
    source = "; ".join(evidence_ids) or "package-local-reader-plan"
    family_2_group = "Author" if tag_id in {"Author", "Artist", "Copyright"} else "Other"
    if family_1_group == "File":
        family_2_group = "Other"
    if family_1_group in {"Real-RA4", "ID3v1"}:
        family_2_group = "Audio"
    if tag_id in {"CreateDate", "ModifyDate", "Year", "DateTimeOriginal"}:
        family_2_group = "Time"
    return TagProvenance(
        group=group,
        table_name=table_name,
        tag_id=tag_id,
        source=source,
        family_0_group=group,
        family_1_group=family_1_group,
        family_2_group=family_2_group,
        duplicate_instance_ordinal=duplicate_instance_ordinal,
    )


def invoke_real(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_real_read_graph(_read_real_exiftool_spans(path, prefix), source_file)


def _read_real_exiftool_spans(path: Path, prefix: bytes) -> bytes:
    with path.open("rb") as file:
        if prefix.startswith(b".ra\xfd"):
            file.seek(0)
            return file.read(REAL_HEADER_SIZE + 512)
        if prefix.startswith((b"pnm://", b"rtsp://", b"http://")):
            return _read_real_metafile_lines(file)
        return _read_realmedia_chunks_and_footer(file)


def _read_real_metafile_lines(file: BinaryIO) -> bytes:
    data = bytearray()
    for _ in range(8192):
        line = file.readline(258)
        if not line:
            break
        data.extend(line)
        if len(line) > 256:
            break
    return bytes(data)


def _read_realmedia_chunks_and_footer(file: BinaryIO) -> bytes:
    file.seek(0)
    header = file.read(REAL_HEADER_SIZE)
    data = bytearray(header)
    if len(header) < REAL_HEADER_SIZE or not header.startswith(b".RMF"):
        return bytes(data)
    header_size = int.from_bytes(header[4:8], "big")
    if header_size < REAL_HEADER_SIZE:
        return bytes(data)
    data.extend(file.read(header_size - REAL_HEADER_SIZE))
    for _ in range(8192):
        chunk_header = file.read(10)
        if len(chunk_header) != 10:
            break
        tag = chunk_header[:4]
        size = int.from_bytes(chunk_header[4:8], "big")
        if tag in {b"\0\0\0\0", b"DATA"}:
            break
        data.extend(chunk_header)
        if size < 10 or size & 0x80000000:
            break
        payload_size = size - 10
        if tag in {b"PROP", b"MDPR", b"CONT", b"RJMD"}:
            data.extend(file.read(payload_size))
        else:
            file.seek(payload_size, 1)
    data.extend(_read_real_footer_probe(file))
    return bytes(data)


def _read_real_footer_probe(file: BinaryIO) -> bytes:
    file.seek(0, 2)
    file_size = file.tell()
    if file_size < 140:
        return b""
    file.seek(file_size - 140)
    probe = file.read(12)
    if not probe.startswith(b"RMJE"):
        return b""
    meta_size = int.from_bytes(probe[8:12], "big")
    footer_start = file_size - 140 - meta_size
    if footer_start < 0:
        return probe
    file.seek(footer_start)
    return file.read(file_size - footer_start)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="real/rm",
        builder_ref="exifmodern.formats.real:invoke_real",
        patterns=(Pattern(0, b".RMF"),),
    ),
    Signature(
        format_id="real/ra",
        builder_ref="exifmodern.formats.real:invoke_real",
        patterns=(Pattern(0, b".ra\xfd"),),
    ),
    Signature(
        format_id="real/ram-pnm",
        builder_ref="exifmodern.formats.real:invoke_real",
        patterns=(Pattern(0, b"pnm://"),),
    ),
    Signature(
        format_id="real/ram-rtsp",
        builder_ref="exifmodern.formats.real:invoke_real",
        patterns=(Pattern(0, b"rtsp://"),),
    ),
    Signature(
        format_id="real/ram-http",
        builder_ref="exifmodern.formats.real:invoke_real",
        patterns=(Pattern(0, b"http://"),),
    ),
)
