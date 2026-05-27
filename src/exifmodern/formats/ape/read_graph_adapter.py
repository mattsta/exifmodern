"""APE/MAC adapters for the shared read graph contract."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from exifmodern.exiftool_compat.core import convert_duration
from exifmodern.formats.ape.tag_transaction_plan import (
    APE_DESCRIPTOR_SIZE,
    APE_SIGNATURE,
    ID3V1_MARKER,
    ID3V1_TRAILER_SIZE,
    ID3V2_MARKER,
    ApeItemPlan,
    ApeTagTransactionPlan,
    build_ape_tag_transaction_plan,
)
from exifmodern.formats.id3.frame_transaction_plan import build_id3_frame_transaction_plan
from exifmodern.formats.id3.read_graph_adapter import id3_graph_tags
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue

MAC_SIGNATURE = b"MAC "
APE_MAX_TAG_PAYLOAD_BYTES = 16 * 1024 * 1024

APE_FILE_TYPE_SOURCE = "ape.file_type"
APE_FOOTER_SOURCE = "ape.footer"
APE_OLD_HEADER_SOURCE = "ape.old_header"
APE_NEW_HEADER_SOURCE = "ape.new_header"
APE_COMPOSITE_SOURCE = "ape.composite"


@dataclass(frozen=True)
class ApeReadBytes:
    data: bytes
    diagnostics: tuple[str, ...]


def is_ape_prefix(data: bytes) -> bool:
    """Return whether bytes satisfy ExifTool's APE.pm primary signature gate."""

    return data.startswith((MAC_SIGNATURE, APE_SIGNATURE))


def build_ape_read_graph_from_file(
    path: Path,
    *,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    prefix = _read_prefix(path, max(32, APE_DESCRIPTOR_SIZE))
    read_bytes = _read_ape_tag_bytes(path, prefix)
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    tags = _file_type_tags()
    diagnostics = list(read_bytes.diagnostics)

    if prefix.startswith(MAC_SIGNATURE):
        header_tags, header_diagnostics = _mac_header_tags(path, prefix)
        tags.extend(header_tags)
        diagnostics.extend(header_diagnostics)
    if read_bytes.data:
        plan = build_ape_tag_transaction_plan(read_bytes.data, allow_output_emission=True)
        tags.extend(_tag_item_tags(plan))
        diagnostics.extend(_tag_diagnostics(plan))
    else:
        diagnostics.append(
            "APE package-local reader diagnostic: ape_tag_payload_absent: "
            "no bounded APETAGEX header/footer payload was available for tag extraction."
        )

    tags.extend(_id3_tags_from_file(path))
    scalar_values = _scalar_values(tags)
    duration = _duration_value(scalar_values)
    if duration is not None:
        tags.append(
            _composite_tag(
                "Duration",
                f"{duration:.2f} s",
                "APE-Duration",
                APE_COMPOSITE_SOURCE,
            )
        )

    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def build_ape_read_graph(
    data: bytes,
    *,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    plan = build_ape_tag_transaction_plan(data, allow_output_emission=True)
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=[*_file_type_tags(), *_tag_item_tags(plan), *_id3_tags(data)],
        diagnostics=_tag_diagnostics(plan),
    )


def _read_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


def _read_ape_tag_bytes(path: Path, prefix: bytes) -> ApeReadBytes:
    if len(prefix) >= APE_DESCRIPTOR_SIZE and prefix.startswith(APE_SIGNATURE):
        declared_size = int.from_bytes(prefix[12:16], "little")
        if declared_size < APE_DESCRIPTOR_SIZE or declared_size > APE_MAX_TAG_PAYLOAD_BYTES:
            return ApeReadBytes(b"", ("APE package-local reader status: invalid_header_size",))
        with path.open("rb") as file:
            return ApeReadBytes(
                file.read(declared_size),
                (
                    "APE package-local reader diagnostic: header_tag_payload: "
                    f"read {declared_size} APETAGEX header bytes.",
                ),
            )

    file_size = path.stat().st_size
    footer_end = _footer_search_end(path, file_size)
    footer_offset = footer_end - APE_DESCRIPTOR_SIZE
    if footer_offset < 0:
        return ApeReadBytes(b"", ())
    with path.open("rb") as file:
        file.seek(footer_offset)
        footer = file.read(APE_DESCRIPTOR_SIZE)
    if not footer.startswith(APE_SIGNATURE):
        return ApeReadBytes(b"", ())
    declared_size = int.from_bytes(footer[12:16], "little")
    payload_size = declared_size - APE_DESCRIPTOR_SIZE
    if payload_size < 0 or payload_size > APE_MAX_TAG_PAYLOAD_BYTES:
        return ApeReadBytes(b"", ("APE package-local reader status: invalid_footer_size",))
    payload_offset = footer_offset - payload_size
    if payload_offset < 0:
        return ApeReadBytes(b"", ("APE package-local reader status: footer_payload_out_of_bounds",))
    with path.open("rb") as file:
        file.seek(payload_offset)
        tag_data = file.read(payload_size + APE_DESCRIPTOR_SIZE)
    return ApeReadBytes(
        tag_data,
        (
            "APE package-local reader diagnostic: footer_tag_payload: "
            f"read {payload_size} payload bytes plus APETAGEX footer from offset {payload_offset}.",
        ),
    )


def _footer_search_end(path: Path, file_size: int) -> int:
    if file_size < ID3V1_TRAILER_SIZE:
        return file_size
    with path.open("rb") as file:
        file.seek(file_size - ID3V1_TRAILER_SIZE)
        trailer = file.read(3)
    if trailer == b"TAG":
        return file_size - ID3V1_TRAILER_SIZE
    return file_size


def _mac_header_tags(path: Path, prefix: bytes) -> tuple[list[ReadTag], list[str]]:
    if len(prefix) < 32:
        return [], ["APE package-local reader status: truncated_mac_header"]
    version_raw = int.from_bytes(prefix[4:6], "little")
    if version_raw <= 3970:
        return _old_mac_header_tags(prefix), []
    descriptor_offset = int.from_bytes(prefix[8:12], "little")
    descriptor_size = int.from_bytes(prefix[12:16], "little")
    if descriptor_size > 4096:
        return [], [
            "APE package-local reader diagnostic: mac_descriptor_deferred: "
            f"declared descriptor size {descriptor_size} exceeds bounded header model."
        ]
    with path.open("rb") as file:
        file.seek(descriptor_offset)
        descriptor = file.read(descriptor_size)
    return _new_mac_header_tags(descriptor), []


def _old_mac_header_tags(data: bytes) -> list[ReadTag]:
    values = [
        _mac_header_tag(
            "APEVersion",
            int.from_bytes(data[4:6], "little") / 1000,
            "0",
            APE_OLD_HEADER_SOURCE,
        ),
        _mac_header_tag(
            "CompressionLevel",
            int.from_bytes(data[6:8], "little"),
            "1",
            APE_OLD_HEADER_SOURCE,
        ),
        _mac_header_tag(
            "Channels", int.from_bytes(data[10:12], "little"), "3", APE_OLD_HEADER_SOURCE
        ),
        _mac_header_tag(
            "SampleRate", int.from_bytes(data[12:16], "little"), "4", APE_OLD_HEADER_SOURCE
        ),
        _mac_header_tag(
            "TotalFrames", int.from_bytes(data[24:28], "little"), "10", APE_OLD_HEADER_SOURCE
        ),
        _mac_header_tag(
            "FinalFrameBlocks",
            int.from_bytes(data[28:32], "little"),
            "12",
            APE_OLD_HEADER_SOURCE,
        ),
    ]
    return values


def _new_mac_header_tags(data: bytes) -> list[ReadTag]:
    if len(data) < 24:
        return []
    return [
        _mac_header_tag(
            "CompressionLevel",
            int.from_bytes(data[0:2], "little"),
            "0",
            APE_NEW_HEADER_SOURCE,
        ),
        _mac_header_tag(
            "BlocksPerFrame",
            int.from_bytes(data[4:8], "little"),
            "2",
            APE_NEW_HEADER_SOURCE,
        ),
        _mac_header_tag(
            "FinalFrameBlocks",
            int.from_bytes(data[8:12], "little"),
            "4",
            APE_NEW_HEADER_SOURCE,
        ),
        _mac_header_tag(
            "TotalFrames", int.from_bytes(data[12:16], "little"), "6", APE_NEW_HEADER_SOURCE
        ),
        _mac_header_tag(
            "BitsPerSample",
            int.from_bytes(data[16:18], "little"),
            "8",
            APE_NEW_HEADER_SOURCE,
        ),
        _mac_header_tag(
            "Channels", int.from_bytes(data[18:20], "little"), "9", APE_NEW_HEADER_SOURCE
        ),
        _mac_header_tag(
            "SampleRate", int.from_bytes(data[20:24], "little"), "10", APE_NEW_HEADER_SOURCE
        ),
    ]


def _file_type_tags() -> list[ReadTag]:
    return [
        _file_tag("FileType", "APE", "FileType"),
        _file_tag("FileTypeExtension", "ape", "FileTypeExtension"),
        _file_tag("MIMEType", "audio/x-monkeys-audio", "MIMEType"),
    ]


def _file_tag(name: str, value: TagValue, tag_id: str) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::File",
            tag_id=tag_id,
            source=_evidence_id_text(APE_FILE_TYPE_SOURCE),
            family_0_group="File",
            family_1_group="File",
            family_2_group="Other",
        ),
        schema=None,
    )


def _tag_item_tags(plan: ApeTagTransactionPlan) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for item in plan.items:
        if item.value.route_kind == "cover_art_binary_with_description":
            if item.value.cover_art_description is not None:
                tags.append(
                    _ape_tag(
                        f"{item.tag_name}Desc",
                        item.value.cover_art_description,
                        f"{item.key} Desc",
                        item.evidence_ids[0],
                        item.duplicate_occurrence,
                    )
                )
            tags.append(
                _ape_tag(
                    item.tag_name,
                    BinaryTagValue(item.value.raw_value[item.value.binary_payload_offset :]),
                    item.key,
                    item.evidence_ids[0],
                    item.duplicate_occurrence,
                    family_2_group="Preview",
                )
            )
        else:
            tags.append(_item_tag(item))
    return tags


def _item_tag(item: ApeItemPlan) -> ReadTag:
    value: TagValue
    if item.value_kind == "binary":
        value = BinaryTagValue(item.value.raw_value)
    elif item.value.utf8_value is not None:
        value = _ape_text_value(item.tag_name, item.value.utf8_value)
    else:
        value = BinaryTagValue(item.value.raw_value)
    return _ape_tag(
        item.tag_name,
        value,
        item.key,
        item.evidence_ids[0],
        item.duplicate_occurrence,
    )


def _id3_tags(data: bytes) -> list[ReadTag]:
    if not _has_id3_metadata(data):
        return []
    return id3_graph_tags(build_id3_frame_transaction_plan(data))


def _id3_tags_from_file(path: Path) -> list[ReadTag]:
    file_size = path.stat().st_size
    id3_data = _leading_id3v2_bytes(path)
    trailing_id3v1 = _trailing_id3v1_bytes(path, file_size)
    if trailing_id3v1:
        id3_data += trailing_id3v1
    if not id3_data:
        return []
    return id3_graph_tags(build_id3_frame_transaction_plan(id3_data))


def _leading_id3v2_bytes(path: Path) -> bytes:
    with path.open("rb") as file:
        header = file.read(10)
        if len(header) < 10 or not header.startswith(ID3V2_MARKER):
            return b""
        size_bytes = header[6:10]
        if any(byte & 0x80 for byte in size_bytes):
            return b""
        payload_size = (
            (size_bytes[0] << 21) | (size_bytes[1] << 14) | (size_bytes[2] << 7) | size_bytes[3]
        )
        if payload_size > APE_MAX_TAG_PAYLOAD_BYTES:
            return b""
        payload = file.read(payload_size)
    if len(payload) != payload_size:
        return b""
    return header + payload


def _trailing_id3v1_bytes(path: Path, file_size: int) -> bytes:
    if file_size < ID3V1_TRAILER_SIZE:
        return b""
    with path.open("rb") as file:
        file.seek(file_size - ID3V1_TRAILER_SIZE)
        trailer = file.read(ID3V1_TRAILER_SIZE)
    if trailer.startswith(ID3V1_MARKER):
        return trailer
    return b""


def _has_id3_metadata(data: bytes) -> bool:
    return data.startswith(ID3V2_MARKER) or (
        len(data) >= ID3V1_TRAILER_SIZE and data[-ID3V1_TRAILER_SIZE:].startswith(ID3V1_MARKER)
    )


def _ape_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    evidence_id: str,
    duplicate_ordinal: int | None = None,
    *,
    family_1_group: str = "APE",
    family_2_group: str = "Audio",
    table_name: str = "Image::ExifTool::APE::Main",
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="APE",
            table_name=table_name,
            tag_id=tag_id,
            source=_evidence_id_text(evidence_id),
            family_0_group="APE",
            family_1_group=family_1_group,
            family_2_group=family_2_group,
            duplicate_instance_ordinal=duplicate_ordinal,
        ),
        schema=None,
    )


def _mac_header_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    evidence_id: str,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="MAC",
            table_name=(
                "Image::ExifTool::APE::OldHeader"
                if evidence_id == APE_OLD_HEADER_SOURCE
                else "Image::ExifTool::APE::NewHeader"
            ),
            tag_id=tag_id,
            source=_evidence_id_text(evidence_id),
            family_0_group="APE",
            family_1_group="MAC",
            family_2_group="Audio",
        ),
        schema=None,
    )


def _composite_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    evidence_id: str,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="Composite",
            table_name="Image::ExifTool::APE::Composite",
            tag_id=tag_id,
            source=_evidence_id_text(evidence_id),
            family_0_group="Composite",
            family_1_group="Composite",
            family_2_group="Audio",
        ),
        schema=None,
    )


def _tag_diagnostics(plan: ApeTagTransactionPlan) -> list[str]:
    diagnostics = [
        f"APE package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if gate.code != "ape_planner_is_non_mutating"
    ]
    if any(item.value_kind in {"binary", "external_locator", "reserved"} for item in plan.items):
        diagnostics.append(
            "APE package-local reader diagnostic: binary_or_locator_values_preserved: "
            "APE.pm routes binary values by (flags & 0x06) and preserves other non-text payloads."
        )
    return diagnostics


def _scalar_values(tags: list[ReadTag]) -> dict[str, int | float]:
    values: dict[str, int | float] = {}
    for tag in tags:
        if isinstance(tag.value, int | float):
            values[tag.name] = tag.value
    return values


def _duration_value(values: dict[str, int | float]) -> float | None:
    sample_rate = values.get("SampleRate")
    total_frames = values.get("TotalFrames")
    blocks_per_frame = values.get("BlocksPerFrame", 73728)
    final_frame_blocks = values.get("FinalFrameBlocks")
    if (
        isinstance(sample_rate, int)
        and isinstance(total_frames, int)
        and isinstance(blocks_per_frame, int)
        and isinstance(final_frame_blocks, int)
        and sample_rate > 0
        and total_frames > 0
    ):
        return ((total_frames - 1) * blocks_per_frame + final_frame_blocks) / sample_rate
    return None


def _ape_text_value(tag_name: str, value: str) -> TagValue:
    if tag_name == "Duration":
        duration = _ape_duration_value(value)
        if duration is not None:
            return duration
    if tag_name in {"Track", "Year", "MediaJukeboxDate"}:
        try:
            return int(value)
        except ValueError:
            return value
    return value


def _ape_duration_value(value: str) -> str | None:
    try:
        raw_duration = int(value)
    except ValueError:
        return None
    if raw_duration < 0 and raw_duration >= -2147483648:
        raw_duration += 4294967296
    converted = convert_duration(raw_duration * 1e-7)
    return converted if isinstance(converted, str) else None


def _evidence_id_text(evidence_id: str) -> str:
    return evidence_id
