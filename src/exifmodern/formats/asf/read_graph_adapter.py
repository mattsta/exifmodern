"""ASF adapters for the shared read graph contract."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from exifmodern.formats.asf.metadata_transaction_plan import (
    ASF_AUTHOR_GROUP_TAGS,
    ASF_HEADER_GUID,
    ASF_RECORD_HEADER_SIZE,
    ASF_TIME_GROUP_TAGS,
    AsfCodecEntryPlan,
    AsfMetadataEntryPlan,
    AsfMetadataTransactionPlan,
    AsfMetadataValue,
    AsfScalarEntryPlan,
    build_asf_metadata_transaction_plan,
    decode_asf_guid,
)
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue

ASF_MAX_HEADER_READ_BYTES = 64 * 1024 * 1024

ASF_FILE_TYPE_SOURCE = "asf.file_type"
ASF_COMPOSITE_SOURCE = "asf.composite"
ASF_DUPLICATE_OUTPUT_SOURCE = "asf.duplicate_output"


def is_asf_prefix(data: bytes) -> bool:
    """Return whether bytes satisfy ExifTool's first ASF Header GUID gate."""

    return len(data) >= 16 and decode_asf_guid(data[:16]) == ASF_HEADER_GUID


def asf_header_byte_count(data: bytes) -> int | None:
    """Return the bounded top-level Header object size needed by ASF.pm traversal."""

    if len(data) < ASF_RECORD_HEADER_SIZE or not is_asf_prefix(data):
        return None
    byte_count = int.from_bytes(data[16:24], "little")
    if byte_count < ASF_RECORD_HEADER_SIZE:
        return None
    return min(byte_count, ASF_MAX_HEADER_READ_BYTES)


def build_asf_read_graph_from_file(
    path: Path,
    *,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    prefix = _read_prefix(path, ASF_RECORD_HEADER_SIZE)
    byte_count = asf_header_byte_count(prefix)
    if byte_count is None:
        return _empty_graph(source_file, generated_at_epoch, "unsupported_header")
    with path.open("rb") as file:
        data = file.read(byte_count)
    graph = build_asf_read_graph(
        data,
        source_file=source_file,
        file_extension=path.suffix.lower().lstrip("."),
        generated_at_epoch=generated_at_epoch,
    )
    if path.stat().st_size > byte_count:
        graph.diagnostics.append(
            "ASF package-local reader diagnostic: media_payload_deferred: "
            f"read {byte_count} header bytes from {path.stat().st_size} total bytes; "
            "ASF.pm ProcessASF seeks across preserved top-level media objects."
        )
    return graph


def build_asf_read_graph(
    header_data: bytes,
    *,
    source_file: str,
    file_extension: str = "",
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    plan = build_asf_metadata_transaction_plan(header_data)
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=[
            *_file_type_tags(file_extension),
            *_asf_payload_tags(plan),
            *_composite_tags(plan.scalar_entries),
        ],
        diagnostics=_diagnostics(plan, len(header_data)),
    )


def _read_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


def _empty_graph(
    source_file: str,
    generated_at_epoch: int | None,
    status: str,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=[],
        diagnostics=[f"ASF package-local reader status: {status}"],
    )


def _file_type_tags(file_extension: str) -> tuple[ReadTag, ...]:
    file_type = _file_type_for_extension(file_extension)
    return (
        _file_tag("FileType", file_type, "FileType"),
        _file_tag("FileTypeExtension", file_type.lower(), "FileTypeExtension"),
        _file_tag("MIMEType", _mime_type(file_type), "MIMEType"),
    )


def _file_type_for_extension(file_extension: str) -> str:
    extension = file_extension.upper()
    if extension in {"ASF", "WMV", "WMA", "DIVX"}:
        return extension
    return "ASF"


def _mime_type(file_type: str) -> str:
    if file_type == "WMA":
        return "audio/x-ms-wma"
    if file_type == "WMV":
        return "video/x-ms-wmv"
    return "video/x-ms-asf"


def _file_tag(name: str, value: TagValue, tag_id: str) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::File",
            tag_id=tag_id,
            source=_evidence_id_text(ASF_FILE_TYPE_SOURCE),
            family_0_group="File",
            family_1_group="File",
            family_2_group="Other",
        ),
        schema=None,
    )


def _scalar_tag(entry: AsfScalarEntryPlan) -> ReadTag:
    return ReadTag(
        name=entry.tag_name,
        value=entry.rendered_value,
        provenance=TagProvenance(
            group="ASF",
            table_name=entry.table_name,
            tag_id=entry.tag_name,
            source=_evidence_id_text(entry.evidence_ids[0]),
            family_0_group="ASF",
            family_1_group="ASF",
            family_2_group=_scalar_family_2_group(entry),
        ),
        schema=None,
    )


def _codec_tag(entry: AsfCodecEntryPlan) -> ReadTag:
    return ReadTag(
        name=entry.tag_name,
        value=entry.value,
        provenance=TagProvenance(
            group="ASF",
            table_name="Image::ExifTool::ASF::CodecList",
            tag_id=entry.tag_name,
            source=_evidence_id_text(entry.evidence_ids[1]),
            family_0_group="ASF",
            family_1_group="ASF",
            family_2_group="Other",
        ),
        schema=None,
    )


def _metadata_tag(entry: AsfMetadataEntryPlan) -> ReadTag:
    return ReadTag(
        name=entry.tag_name,
        value=_metadata_value(entry.value),
        provenance=TagProvenance(
            group="ASF",
            table_name=_metadata_table_name(entry.section),
            tag_id=entry.tag_name,
            source=_evidence_id_text(_semantic_evidence_id(entry.evidence_ids)),
            family_0_group="ASF",
            family_1_group="ASF",
            family_2_group=_metadata_family_2_group(entry.section, entry.tag_name),
        ),
        schema=None,
    )


def _metadata_value(value: AsfMetadataValue) -> TagValue:
    if isinstance(value, bytes):
        return BinaryTagValue(value)
    return value


def _asf_payload_tags(plan: AsfMetadataTransactionPlan) -> tuple[ReadTag, ...]:
    """Emit package-local ASF tags in the byte order used by ASF.pm traversal."""

    ordered: list[tuple[int, int, ReadTag]] = []
    for index, scalar_entry in enumerate(plan.scalar_entries):
        ordered.append((scalar_entry.value_offset, index, _scalar_tag(scalar_entry)))
    scalar_count = len(plan.scalar_entries)
    for index, codec_entry in enumerate(plan.codec_entries):
        ordered.append((codec_entry.value_offset, scalar_count + index, _codec_tag(codec_entry)))
    metadata_count_offset = scalar_count + len(plan.codec_entries)
    for index, metadata_entry in enumerate(plan.metadata_entries):
        ordered.append(
            (
                metadata_entry.value_offset,
                metadata_count_offset + index,
                _metadata_tag(metadata_entry),
            )
        )
    tags = tuple(tag for _, _, tag in sorted(ordered, key=lambda item: (item[0], item[1])))
    return _with_duplicate_instance_provenance(tags)


def _with_duplicate_instance_provenance(tags: tuple[ReadTag, ...]) -> tuple[ReadTag, ...]:
    totals: dict[str, int] = {}
    for tag in tags:
        totals[tag.name] = totals.get(tag.name, 0) + 1
    seen: dict[str, int] = {}
    updated: list[ReadTag] = []
    for tag in tags:
        if totals[tag.name] <= 1:
            updated.append(tag)
            continue
        ordinal = seen.get(tag.name, 0)
        seen[tag.name] = ordinal + 1
        updated.append(
            replace(
                tag,
                provenance=replace(
                    tag.provenance,
                    family_4_instance_group="" if ordinal == 0 else f"Copy{ordinal}",
                    duplicate_instance_ordinal=ordinal,
                ),
            )
        )
    return tuple(updated)


def _scalar_family_2_group(entry: AsfScalarEntryPlan) -> str:
    if entry.tag_name == "CreationDate":
        return "Time"
    return "Video"


def _metadata_table_name(section: str) -> str:
    if section == "picture":
        return "Image::ExifTool::ASF::Picture"
    return "Image::ExifTool::ASF::ExtendedDescr"


def _metadata_family_2_group(section: str, tag_name: str) -> str:
    if section == "picture" and tag_name == "Picture":
        return "Preview"
    if section == "picture":
        return "Image"
    if tag_name in ASF_AUTHOR_GROUP_TAGS:
        return "Author"
    if tag_name in ASF_TIME_GROUP_TAGS:
        return "Time"
    if section == "content_description":
        if tag_name in {"Author", "Copyright"}:
            return "Author"
        return "Video"
    return "Video"


def _composite_tags(scalars: tuple[AsfScalarEntryPlan, ...]) -> tuple[ReadTag, ...]:
    width: int | None = None
    height: int | None = None
    for scalar in scalars:
        if scalar.tag_name == "ImageWidth" and isinstance(scalar.raw_value, int):
            width = scalar.raw_value
        elif scalar.tag_name == "ImageHeight" and isinstance(scalar.raw_value, int):
            height = scalar.raw_value
    if width is None or height is None:
        return ()
    megapixels = round(width * height / 1_000_000, 3)
    return (
        _composite_tag("ImageSize", f"{width}x{height}", "Exif-ImageSize"),
        _composite_tag("Megapixels", megapixels, "Exif-Megapixels"),
    )


def _composite_tag(name: str, value: TagValue, tag_id: str) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="Composite",
            table_name="Image::ExifTool::Composite",
            tag_id=tag_id,
            source=_evidence_id_text(ASF_COMPOSITE_SOURCE),
            family_0_group="Composite",
            family_1_group="Composite",
            family_2_group="Image",
        ),
        schema=None,
    )


def _diagnostics(plan: AsfMetadataTransactionPlan, header_byte_count: int) -> list[str]:
    diagnostics = [
        f"ASF package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if gate.code
        not in {
            "planner_is_non_mutating",
            "full_asf_writer_not_implemented",
        }
    ]
    diagnostics.append(
        "ASF package-local reader diagnostic: bounded_header_traversal: "
        f"read {header_byte_count} bytes from the ASF Header object; "
        "ProcessASF reads GUID/size object headers and seeks over preserved payload objects."
    )
    if any(isinstance(entry.value, bytes) for entry in plan.metadata_entries):
        diagnostics.append(
            "ASF package-local reader diagnostic: binary_metadata_payload_modeled: "
            "ReadASF preserves byte-array metadata values as raw bytes."
        )
    duplicate_names = sorted(name for name, count in _tag_name_counts(plan).items() if count > 1)
    if duplicate_names:
        diagnostics.append(
            "ASF package-local reader diagnostic: duplicate_instance_provenance_modeled: "
            f"{', '.join(duplicate_names)} carry family-4 CopyN/ordinal provenance from "
            "source-order ASF emissions "
            f"({_evidence_id_text(ASF_DUPLICATE_OUTPUT_SOURCE)})."
        )
    for record in plan.records:
        if record.action == "preserve_unknown":
            diagnostics.append(
                "ASF package-local reader diagnostic: unknown_object_preserved: "
                f"{record.full_path} ({record.guid}) is not defined in the ASF.pm table."
            )
    return diagnostics


def _tag_name_counts(plan: AsfMetadataTransactionPlan) -> dict[str, int]:
    counts: dict[str, int] = {}
    for scalar_entry in plan.scalar_entries:
        counts[scalar_entry.tag_name] = counts.get(scalar_entry.tag_name, 0) + 1
    for codec_entry in plan.codec_entries:
        counts[codec_entry.tag_name] = counts.get(codec_entry.tag_name, 0) + 1
    for metadata_entry in plan.metadata_entries:
        counts[metadata_entry.tag_name] = counts.get(metadata_entry.tag_name, 0) + 1
    return counts


def _evidence_id_text(evidence_id: str) -> str:
    return evidence_id


def _semantic_evidence_id(references: tuple[str, ...]) -> str:
    for reference in references:
        if "process" in reference:
            return reference
    return references[0]
