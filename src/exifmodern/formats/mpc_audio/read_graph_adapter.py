"""Musepack/MPC adapters for the shared read graph contract."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from exifmodern.formats.ape.read_graph_adapter import _tag_diagnostics, _tag_item_tags
from exifmodern.formats.ape.tag_transaction_plan import build_ape_tag_transaction_plan
from exifmodern.formats.id3.frame_transaction_plan import build_id3_frame_transaction_plan
from exifmodern.formats.id3.read_graph_adapter import id3_graph_tags, parse_id3_picture
from exifmodern.formats.mpc_audio.transaction_plan import (
    APE_DESCRIPTOR_SIZE,
    APE_SIGNATURE,
    ID3V1_TRAILER_SIZE,
    ID3V2_HEADER_SIZE,
    MPC_HEADER_SIZE,
    MPC_ID3_PREFLIGHT_SOURCE,
    MPC_SIGNATURE,
    MPC_TAG_TABLE_SOURCE,
    MpcAudioTransactionPlan,
    build_mpc_audio_transaction_plan,
    leading_id3v2_end_offset,
)
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue

MPC_FILE_TYPE_SOURCE = "mpc_audio.file_type"
MPC_TRAILING_TAG_READ_LIMIT = 1024 * 1024


def is_mpc_prefix(data: bytes, path: Path | None = None) -> bool:
    """Return whether bytes satisfy ExifTool's MPC signature gate."""

    header_offset, reason = leading_id3v2_end_offset(data)
    if reason is not None:
        header_offset = 0
    if data[header_offset : header_offset + len(MPC_SIGNATURE)] == MPC_SIGNATURE:
        return True
    return path is not None and path.suffix.lower() == ".mpc"


def build_mpc_read_graph_from_file(
    path: Path,
    *,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    data = _read_mpc_invoker_bytes(path)
    return build_mpc_read_graph(
        data,
        source_file=source_file,
        generated_at_epoch=generated_at_epoch,
    )


def _read_mpc_invoker_bytes(path: Path) -> bytes:
    leading = _read_leading_id3v2(path)
    header_offset = len(leading)
    header = _read_at(path, header_offset, MPC_HEADER_SIZE)
    if len(header) < MPC_HEADER_SIZE:
        return leading + header
    return leading + header + _read_trailing_tags(path, header_offset + len(header))


def _read_leading_id3v2(path: Path) -> bytes:
    header = _read_at(path, 0, ID3V2_HEADER_SIZE)
    if not header.startswith(b"ID3") or len(header) < ID3V2_HEADER_SIZE:
        return b""
    size_bytes = header[6:10]
    if any(byte & 0x80 for byte in size_bytes):
        return b""
    payload_size = (
        (size_bytes[0] << 21) | (size_bytes[1] << 14) | (size_bytes[2] << 7) | size_bytes[3]
    )
    return _read_at(path, 0, ID3V2_HEADER_SIZE + payload_size)


def _read_trailing_tags(path: Path, minimum_offset: int) -> bytes:
    file_size = path.stat().st_size
    if file_size <= minimum_offset:
        return b""
    probe_size = min(file_size - minimum_offset, APE_DESCRIPTOR_SIZE + ID3V1_TRAILER_SIZE)
    probe = _read_tail(path, probe_size)
    search_end = file_size
    if len(probe) >= ID3V1_TRAILER_SIZE and probe[-ID3V1_TRAILER_SIZE:].startswith(b"TAG"):
        search_end -= ID3V1_TRAILER_SIZE
    footer = _read_at(path, search_end - APE_DESCRIPTOR_SIZE, APE_DESCRIPTOR_SIZE)
    ape_size = 0
    if len(footer) == APE_DESCRIPTOR_SIZE and footer.startswith(APE_SIGNATURE):
        declared_size = int.from_bytes(footer[12:16], "little")
        if APE_DESCRIPTOR_SIZE <= declared_size <= search_end - minimum_offset:
            ape_size = min(declared_size, MPC_TRAILING_TAG_READ_LIMIT)
    tail_start = max(minimum_offset, search_end - ape_size)
    if search_end < file_size:
        tail_start = min(tail_start, file_size - ID3V1_TRAILER_SIZE)
    return _read_at(path, tail_start, file_size - tail_start)


def _read_at(path: Path, offset: int, byte_count: int) -> bytes:
    if offset < 0 or byte_count <= 0:
        return b""
    with path.open("rb") as file:
        file.seek(offset)
        return file.read(byte_count)


def _read_tail(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        file.seek(-byte_count, 2)
        return file.read(byte_count)


def build_mpc_read_graph(
    data: bytes,
    *,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    plan = build_mpc_audio_transaction_plan(data, allow_output_emission=True)
    tags: list[ReadTag] = []
    diagnostics = [
        f"MPC package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status == "planned":
        tags.extend(_file_type_tags())
        id3_size = _id3_size(plan)
        if id3_size:
            tags.append(_file_tag("ID3Size", id3_size, "ID3Size", MPC_ID3_PREFLIGHT_SOURCE))
        tags.extend(_mpc_audio_tags(plan))
        tags.extend(_ape_trailer_tags(data, plan, diagnostics))
        tags.extend(_mpc_id3_tags(data))
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _file_type_tags() -> list[ReadTag]:
    return [
        _file_tag("FileType", "MPC", "FileType", MPC_FILE_TYPE_SOURCE),
        _file_tag("FileTypeExtension", "mpc", "FileTypeExtension", MPC_FILE_TYPE_SOURCE),
        _file_tag("MIMEType", "audio/x-musepack", "MIMEType", MPC_FILE_TYPE_SOURCE),
    ]


def _file_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    evidence_id: str,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::File",
            tag_id=tag_id,
            source=_evidence_id_text(evidence_id),
            family_0_group="File",
            family_1_group="File",
            family_2_group="Other",
        ),
        schema=None,
    )


def _mpc_audio_tags(plan: MpcAudioTransactionPlan) -> list[ReadTag]:
    audio = plan.version7_audio
    if not audio.available:
        return []
    values: tuple[tuple[str, TagValue, str], ...] = (
        ("TotalFrames", audio.total_frames, "Bit032-063"),
        ("SampleRate", audio.sample_rate, "Bit080-081"),
        ("Quality", audio.quality, "Bit084-087"),
        ("MaxBand", audio.max_band, "Bit088-093"),
        ("ReplayGainTrackPeak", audio.replay_gain_track_peak, "Bit096-111"),
        ("ReplayGainTrackGain", audio.replay_gain_track_gain, "Bit112-127"),
        ("ReplayGainAlbumPeak", audio.replay_gain_album_peak, "Bit128-143"),
        ("ReplayGainAlbumGain", audio.replay_gain_album_gain, "Bit144-159"),
        ("FastSeek", _yes_no(audio.fast_seek), "Bit179"),
        ("Gapless", _yes_no(audio.gapless), "Bit191"),
        ("EncoderVersion", audio.encoder_version, "Bit216-223"),
    )
    return [_mpc_tag(name, value, tag_id) for name, value, tag_id in values if value is not None]


def _mpc_tag(name: str, value: TagValue, tag_id: str) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="MPC",
            table_name="Image::ExifTool::MPC::Main",
            tag_id=tag_id,
            source=_evidence_id_text(MPC_TAG_TABLE_SOURCE),
            family_0_group="MPC",
            family_1_group="MPC",
            family_2_group="Audio",
        ),
        schema=None,
    )


def _ape_trailer_tags(
    data: bytes,
    plan: MpcAudioTransactionPlan,
    diagnostics: list[str],
) -> list[ReadTag]:
    boundary = next(
        (item for item in plan.tag_coexistence.boundaries if item.kind == "trailing_ape"),
        None,
    )
    if boundary is None:
        return []
    ape_data = data[boundary.offset : boundary.end_offset]
    ape_plan = build_ape_tag_transaction_plan(ape_data, allow_output_emission=True)
    diagnostics.extend(_tag_diagnostics(ape_plan))
    return _tag_item_tags(ape_plan)


def _mpc_id3_tags(data: bytes) -> list[ReadTag]:
    plan = build_id3_frame_transaction_plan(data)
    picture_payloads = [
        parsed[3]
        for frame in plan.id3v2_frames
        if frame.frame_id == "PIC"
        for parsed in [parse_id3_picture(data[frame.payload_offset : frame.end_offset])]
        if parsed is not None
    ]
    picture_index = 0
    tags: list[ReadTag] = []
    for tag in id3_graph_tags(plan):
        value = tag.value
        if tag.provenance.group in {"ID3v1", "ID3v2_2", "Composite"} and tag.name in {
            "DateTimeOriginal",
            "Year",
        }:
            value = _integer_string(value)
        if tag.provenance.group == "ID3v2_2" and tag.name == "Picture":
            if picture_index < len(picture_payloads):
                value = BinaryTagValue(picture_payloads[picture_index])
                picture_index += 1
        tags.append(replace(tag, value=value))
    return tags


def _id3_size(plan: MpcAudioTransactionPlan) -> int:
    size = plan.tag_coexistence.leading_id3v2_end_offset
    if plan.tag_coexistence.trailing_id3v1_present:
        size += ID3V1_TRAILER_SIZE
    return size


def _yes_no(value: bool | None) -> str | None:
    if value is None:
        return None
    return "Yes" if value else "No"


def _integer_string(value: TagValue) -> TagValue:
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return value


def _evidence_id_text(evidence_id: str) -> str:
    return evidence_id
