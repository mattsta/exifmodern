"""Flash/SWF/FLV transaction planning helpers."""

import time
import zlib
from io import BufferedReader
from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.flash.media_transaction_plan import (
    FlashAmfRecordPlan,
    FlashEvidenceId,
    FlashMediaRewriteRequest,
    FlashMediaTransactionPlan,
    build_flash_media_transaction_plan,
    resolve_flash_evidence,
)
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.json_types import JsonValue
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

type FlashGraphScalar = str | int | float | bool | None
type FlashGraphValue = FlashGraphScalar | list[FlashGraphScalar]

FLASH_META_TAG_NAMES: dict[str, str] = {
    "audiocodecid": "AudioCodecID",
    "audiodatarate": "AudioBitrate",
    "audiodelay": "AudioDelay",
    "audiosamplerate": "AudioSampleRate",
    "audiosamplesize": "AudioSampleSize",
    "audiosize": "AudioSize",
    "canSeekToEnd": "CanSeekToEnd",
    "datasize": "DataSize",
    "duration": "Duration",
    "filesize": "FileSizeBytes",
    "framerate": "FrameRate",
    "hasAudio": "HasAudio",
    "hasCuePoints": "HasCuePoints",
    "hasKeyframes": "HasKeyFrames",
    "hasMetadata": "HasMetadata",
    "hasVideo": "HasVideo",
    "height": "ImageHeight",
    "keyframes.times": "KeyFramesTimes",
    "keyframes.filepositions": "KeyFramePositions",
    "lasttimestamp": "LastTimeStamp",
    "lastkeyframetimestamp": "LastKeyFrameTime",
    "metadatacreator": "MetadataCreator",
    "metadatadate": "MetadataDate",
    "stereo": "Stereo",
    "test": "Test",
    "videocodecid": "VideoCodecID",
    "videodatarate": "VideoBitrate",
    "videosize": "VideoSize",
    "width": "ImageWidth",
}

FLASH_CUE_POINT_NAMES: dict[str, str] = {
    "name": "Name",
    "time": "Time",
    "type": "Type",
}

__all__ = [
    "FlashMediaRewriteRequest",
    "FlashMediaTransactionPlan",
    "build_flash_media_transaction_plan",
    "build_flash_read_graph",
    "invoke_flash",
    "is_flash_prefix",
]


def is_flash_prefix(prefix: bytes) -> bool:
    if len(prefix) < 4:
        return False
    if prefix[:3] in {b"FWS", b"CWS", b"ZWS"}:
        return prefix[3] != 0
    return prefix.startswith(b"FLV\x01")


def build_flash_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_flash_media_transaction_plan(data)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"Flash package-local reader status: {plan.status}")
    diagnostics.extend(
        f"Flash package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = []
    trailing_media_tags: list[ReadTag] = []
    trailing_composite_tags: list[ReadTag] = []

    def _add(
        name: str,
        value: FlashGraphValue,
        *,
        table: str,
        evidence_ids: tuple[FlashEvidenceId, ...],
        ordinal: int | None = None,
    ) -> None:
        if value is None:
            return
        rendered = value if isinstance(value, str | int | float | bool | list) else str(value)
        tags_out = (
            trailing_media_tags
            if table
            in {
                "Image::ExifTool::Flash::Audio",
                "Image::ExifTool::Flash::Video",
            }
            else tags
        )
        tags_out.append(
            ReadTag(
                name=name,
                value=_read_value(rendered),
                provenance=_provenance(
                    group="Flash",
                    table_name=table,
                    tag_id=name,
                    references=resolve_flash_evidence(evidence_ids),
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )

    def _add_file(
        name: str,
        value: FlashGraphValue,
        evidence_ids: tuple[FlashEvidenceId, ...],
    ) -> None:
        if value is None:
            return
        rendered = value if isinstance(value, str | int | float | bool | list) else str(value)
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(rendered),
                provenance=_provenance(
                    group="File",
                    table_name="Image::ExifTool::File",
                    tag_id=name,
                    references=resolve_flash_evidence(evidence_ids),
                ),
                schema=None,
            )
        )

    def _add_composite_image_size(
        width: float | None,
        height: float | None,
        evidence_ids: tuple[FlashEvidenceId, ...],
        *,
        target: list[ReadTag] | None = None,
    ) -> None:
        if width is None or height is None:
            return
        output_tags = tags if target is None else target
        image_size = f"{width:g}x{height:g}"
        megapixels = round((width * height) / 1_000_000, 3)
        for name, value in (
            ("ImageSize", image_size),
            ("Megapixels", megapixels),
        ):
            output_tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id=name,
                        references=resolve_flash_evidence(evidence_ids),
                    ),
                    schema=None,
                )
            )

    def _xmp_tags(
        payload: bytes,
        evidence_ids: tuple[FlashEvidenceId, ...],
    ) -> list[ReadTag]:
        try:
            values_by_group = parse_xmp_packet(payload)
        except ValueError:
            return []
        nested_tags: list[ReadTag] = []
        for group, values in values_by_group.items():
            for name, value in values.items():
                if group == "XMP-rdf" and name == "About":
                    continue
                tag_value = _json_flash_value(value)
                if tag_value is None:
                    continue
                nested_tags.append(
                    ReadTag(
                        name=name,
                        value=_read_value(tag_value),
                        provenance=_provenance(
                            group=group,
                            table_name=_xmp_table_name(group),
                            tag_id=name,
                            references=resolve_flash_evidence(evidence_ids),
                        ),
                        schema=None,
                    )
                )
        return nested_tags

    if plan.swf is not None and plan.swf.header is not None:
        header = plan.swf.header
        table = "Image::ExifTool::Flash::Main"
        _add_file("FileType", "SWF", header.evidence_ids)
        _add_file("FileTypeExtension", "swf", header.evidence_ids)
        _add_file("MIMEType", "application/x-shockwave-flash", header.evidence_ids)
        _add("FlashVersion", header.version, table=table, evidence_ids=header.evidence_ids)
        _add("Compressed", header.compressed, table=table, evidence_ids=header.evidence_ids)
        _add(
            "ImageWidth",
            _integral_float(header.image_width),
            table=table,
            evidence_ids=header.evidence_ids,
        )
        _add(
            "ImageHeight",
            _integral_float(header.image_height),
            table=table,
            evidence_ids=header.evidence_ids,
        )
        _add(
            "FrameRate",
            _integral_float(header.frame_rate),
            table=table,
            evidence_ids=header.evidence_ids,
        )
        _add("FrameCount", header.frame_count, table=table, evidence_ids=header.evidence_ids)
        _add(
            "Duration",
            _flash_duration(header.duration),
            table=table,
            evidence_ids=header.evidence_ids,
        )
        _add(
            "FlashAttributes",
            plan.swf.flash_attributes,
            table=table,
            evidence_ids=plan.swf.evidence_ids,
        )
        for swf_tag in plan.swf.tags:
            if swf_tag.route_kind == "xmp":
                tags.extend(_xmp_tags(swf_tag.payload, swf_tag.evidence_ids))
                continue
            _add(swf_tag.name, swf_tag.name, table=table, evidence_ids=swf_tag.evidence_ids)
        _add_composite_image_size(header.image_width, header.image_height, header.evidence_ids)
    if plan.flv is not None:
        if plan.flv.header is not None:
            _add_file("FileType", "FLV", plan.flv.header.evidence_ids)
            _add_file("FileTypeExtension", "flv", plan.flv.header.evidence_ids)
            _add_file("MIMEType", "video/x-flv", plan.flv.header.evidence_ids)
        for packet in plan.flv.packets:
            if packet.meta_packet is not None:
                meta = packet.meta_packet
                for tag_name, value, source_record in _flash_meta_graph_values(meta.fields):
                    _add(
                        tag_name,
                        value,
                        table="Image::ExifTool::Flash::Meta",
                        evidence_ids=source_record.evidence_ids,
                        ordinal=source_record.offset,
                    )
                width = _flash_meta_numeric_value(meta.fields, "width")
                height = _flash_meta_numeric_value(meta.fields, "height")
                if width is not None and height is not None:
                    _add_composite_image_size(
                        width,
                        height,
                        meta.evidence_ids,
                        target=trailing_composite_tags,
                    )
            if packet.audio_header is not None:
                audio = packet.audio_header
                table = "Image::ExifTool::Flash::Audio"
                _add(
                    "AudioEncoding",
                    audio.audio_encoding,
                    table=table,
                    evidence_ids=audio.evidence_ids,
                )
                _add(
                    "AudioSampleRate",
                    audio.audio_sample_rate,
                    table=table,
                    evidence_ids=audio.evidence_ids,
                )
                _add(
                    "AudioBitsPerSample",
                    audio.audio_bits_per_sample,
                    table=table,
                    evidence_ids=audio.evidence_ids,
                )
                _add(
                    "AudioChannels",
                    _flash_audio_channels(audio.audio_channels),
                    table=table,
                    evidence_ids=audio.evidence_ids,
                )
            if packet.video_header is not None:
                video = packet.video_header
                _add(
                    "VideoEncoding",
                    video.video_encoding,
                    table="Image::ExifTool::Flash::Video",
                    evidence_ids=video.evidence_ids,
                )
        tags.extend(trailing_media_tags)
        tags.extend(trailing_composite_tags)
    return _graph(source_file, tags, diagnostics)


def _flash_meta_graph_values(
    fields: tuple[FlashAmfRecordPlan, ...],
) -> tuple[tuple[str, FlashGraphValue, FlashAmfRecordPlan], ...]:
    values: list[tuple[str, FlashGraphValue, FlashAmfRecordPlan]] = []
    by_path = {
        field.field_path: field
        for field in fields
        if isinstance(field, FlashAmfRecordPlan) and field.field_path is not None
    }
    consumed: set[str] = set()
    for path, field in by_path.items():
        if path is None:
            continue
        array_value = _flash_array_value(field)
        if array_value is not None:
            if path in {"cuePoints", "keyframes"}:
                continue
            tag_name = FLASH_META_TAG_NAMES.get(path, _flash_dynamic_tag_name(path))
            values.append((tag_name, array_value, field))
            consumed.update(child.field_path or "" for child in field.children)
            continue
        if path in consumed or field.value_text is None:
            continue
        if path in {"audiosamplerate", "cuePoints", "keyframes"}:
            continue
        cue_name = _flash_cue_point_tag_name(path)
        if cue_name is not None:
            values.append((cue_name, _flash_meta_value(path, field.value_text), field))
            continue
        if "." in path:
            continue
        tag_name = FLASH_META_TAG_NAMES.get(path, _flash_dynamic_tag_name(path))
        values.append((tag_name, _flash_meta_value(path, field.value_text), field))
    return tuple(values)


def _flash_array_value(field: FlashAmfRecordPlan) -> list[FlashGraphScalar] | None:
    if field.amf_type_code != 0x0A:
        return None
    values: list[FlashGraphScalar] = []
    for child in field.children:
        if child.value_text is None:
            return None
        scalar_value = _flash_meta_value(field.field_path or "", child.value_text)
        if isinstance(scalar_value, list):
            return None
        values.append(scalar_value)
    return values


def _flash_cue_point_tag_name(path: str) -> str | None:
    parts = path.split(".")
    if len(parts) < 3 or parts[0] != "cuePoints" or not parts[1].isdecimal():
        return None
    suffix = FLASH_CUE_POINT_NAMES.get(parts[2])
    if suffix is not None:
        return f"CuePoint{parts[1]}{suffix}"
    if len(parts) == 4 and parts[2] == "parameters":
        return f"CuePoint{parts[1]}Parameter{_flash_dynamic_tag_name(parts[3])}"
    return None


def _flash_dynamic_tag_name(path: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in path.split(".") if part)


def _flash_meta_value(path: str, value: str) -> FlashGraphValue:
    if value in {"Yes", "No"}:
        return value
    number = _flash_number(value)
    if number is None:
        return value
    if path == "audiodatarate":
        return f"{number * 1000 / 1000:.1f} kbps"
    if path == "videodatarate":
        return f"{number * 1000 / 1000:.0f} kbps"
    if path == "duration":
        return f"{number:.2f} s"
    if path == "metadatadate":
        return _flash_unix_date(number)
    if path == "framerate":
        rounded = int(number * 1000 + 0.5) / 1000
        return int(rounded) if float(rounded).is_integer() else rounded
    if float(number).is_integer():
        return int(number)
    return number


def _flash_meta_numeric_value(fields: tuple[FlashAmfRecordPlan, ...], path: str) -> float | None:
    for field in fields:
        if field.field_path != path or field.value_text is None:
            continue
        return _flash_number(field.value_text)
    return None


def _flash_number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _flash_scalar_text(value: FlashGraphValue) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _flash_audio_channels(value: int) -> str | int:
    return {1: "1 (mono)", 2: "2 (stereo)"}.get(value, value)


def _flash_unix_date(seconds: float) -> str:
    whole_seconds = int(seconds)
    fractional = seconds - whole_seconds
    local_time = time.localtime(whole_seconds)
    utc_time = time.gmtime(whole_seconds)
    zone_offset = -time.timezone
    if local_time.tm_isdst > 0 and time.daylight:
        zone_offset = -time.altzone
    sign = "+" if zone_offset >= 0 else "-"
    zone_offset = abs(zone_offset)
    return (
        time.strftime("%Y:%m:%d %H:%M:%S", utc_time)
        + f"{fractional:.6f}"[1:]
        + f"{sign}{zone_offset // 3600:02d}:{(zone_offset % 3600) // 60:02d}"
    )


def _json_flash_value(value: JsonValue) -> FlashGraphValue:
    if isinstance(value, list):
        values: list[FlashGraphScalar] = []
        for item in value:
            if not isinstance(item, str | int | float | bool):
                return str(value)
            values.append(item)
        return values
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _xmp_table_name(group: str) -> str:
    suffix = group.removeprefix("XMP-")
    if suffix == group:
        return "Image::ExifTool::XMP::Main"
    return f"Image::ExifTool::XMP::{suffix}"


def _integral_float(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value.is_integer() else value


def _flash_duration(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f} s"


def invoke_flash(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_flash_read_graph(_read_flash_exiftool_spans(path, prefix), source_file)


def _read_flash_exiftool_spans(path: Path, prefix: bytes) -> bytes:
    if prefix.startswith(b"FLV\x01"):
        return _read_flv_exiftool_packets(path)
    return _read_swf_exiftool_tags(path)


def _read_flv_exiftool_packets(path: Path) -> bytes:
    with path.open("rb") as file:
        header = file.read(9)
        data = bytearray(header)
        if len(header) < 9 or not header.startswith(b"FLV\x01"):
            return bytes(data)
        flags = header[4] & 0x05
        data_offset = int.from_bytes(header[5:9], "big")
        if data_offset > 9:
            data.extend(file.read(data_offset - 9))
        remaining_flags = flags
        found = 0
        for _ in range(8192):
            packet_header = file.read(15)
            if len(packet_header) != 15:
                break
            data.extend(packet_header)
            packet_type = packet_header[4]
            payload_length = int.from_bytes(packet_header[5:8], "big")
            if packet_type in {0x08, 0x09}:
                mask = 0x04 if packet_type == 0x08 else 0x01
                if not found & mask:
                    found |= mask
                    remaining_flags &= ~mask
                    if payload_length:
                        data.extend(file.read(1))
                        file.seek(payload_length - 1, 1)
                    if not remaining_flags:
                        break
                    continue
            elif packet_type == 0x12:
                data.extend(file.read(payload_length))
                if not remaining_flags:
                    break
                continue
            file.seek(payload_length, 1)
        return bytes(data)


def _read_swf_exiftool_tags(path: Path) -> bytes:
    with path.open("rb") as file:
        header = file.read(8)
        if len(header) < 8 or not header.startswith((b"FWS", b"CWS")):
            return header
        if header.startswith(b"FWS"):
            return header + _read_uncompressed_swf_info(file)
        return header + _read_compressed_swf_info(file)


def _read_compressed_swf_info(file: BufferedReader) -> bytes:
    compressed = bytearray()
    body = bytearray()
    inflater = zlib.decompressobj()
    for _ in range(16384):
        chunk = file.read(64)
        if not chunk:
            break
        compressed.extend(chunk)
        try:
            body.extend(inflater.decompress(chunk))
        except zlib.error:
            break
        if _swf_info_scan_complete(bytes(body)) or inflater.eof:
            break
    return bytes(compressed)


def _read_uncompressed_swf_info(file: BufferedReader) -> bytes:
    data = bytearray(file.read(64))
    if not data:
        return bytes(data)
    rect_bits = data[0] >> 3
    frame_header_size = (5 + rect_bits * 4 + 7) // 8 + 4
    offset = frame_header_size
    has_metadata = False
    for _ in range(8192):
        while len(data) < offset + 2:
            chunk = file.read(offset + 2 - len(data))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        code = int.from_bytes(data[offset : offset + 2], "little")
        tag_id = code >> 6
        size = code & 0x3F
        payload_offset = offset + 2
        if tag_id not in {69, 77} and not has_metadata:
            break
        if size == 0x3F:
            while len(data) < payload_offset + 4:
                chunk = file.read(payload_offset + 4 - len(data))
                if not chunk:
                    return bytes(data)
                data.extend(chunk)
            size = int.from_bytes(data[payload_offset : payload_offset + 4], "little")
            payload_offset += 4
            if size > 1_000_000:
                break
        while len(data) < payload_offset + size + 2:
            chunk = file.read(payload_offset + size + 2 - len(data))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        if tag_id == 69:
            if size and data[payload_offset] & 0x10:
                has_metadata = True
            else:
                break
        elif tag_id == 77:
            break
        offset = payload_offset + size
    return bytes(data)


def _swf_info_scan_complete(body: bytes) -> bool:
    if not body:
        return False
    rect_bits = body[0] >> 3
    offset = (5 + rect_bits * 4 + 7) // 8 + 4
    has_metadata = False
    for _ in range(8192):
        if len(body) < offset + 2:
            return False
        code = int.from_bytes(body[offset : offset + 2], "little")
        tag_id = code >> 6
        size = code & 0x3F
        payload_offset = offset + 2
        if tag_id not in {69, 77} and not has_metadata:
            return True
        if size == 0x3F:
            if len(body) < payload_offset + 4:
                return False
            size = int.from_bytes(body[payload_offset : payload_offset + 4], "little")
            payload_offset += 4
            if size > 1_000_000:
                return True
        if len(body) < payload_offset + size + 2:
            return False
        if tag_id == 69:
            if size and body[payload_offset] & 0x10:
                has_metadata = True
            else:
                return True
        elif tag_id == 77:
            return True
        offset = payload_offset + size
    return True


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="flash/swf-fws",
        builder_ref="exifmodern.formats.flash:invoke_flash",
        patterns=(Pattern(0, b"FWS"),),
        structural_check="exifmodern.formats.flash:is_flash_prefix",
    ),
    Signature(
        format_id="flash/swf-cws",
        builder_ref="exifmodern.formats.flash:invoke_flash",
        patterns=(Pattern(0, b"CWS"),),
        structural_check="exifmodern.formats.flash:is_flash_prefix",
    ),
    Signature(
        format_id="flash/swf-zws",
        builder_ref="exifmodern.formats.flash:invoke_flash",
        patterns=(Pattern(0, b"ZWS"),),
        structural_check="exifmodern.formats.flash:is_flash_prefix",
        notes=(
            "routes to explicit unsupported diagnostic; Flash.pm ProcessSWF accepts only FWS/CWS",
        ),
    ),
    Signature(
        format_id="flash/flv",
        builder_ref="exifmodern.formats.flash:invoke_flash",
        patterns=(Pattern(0, b"FLV\x01"),),
        structural_check="exifmodern.formats.flash:is_flash_prefix",
    ),
)
