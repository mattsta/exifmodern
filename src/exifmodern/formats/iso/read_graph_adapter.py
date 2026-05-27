"""ISO 9660 read graph adapter backed by ExifTool ISO.pm tables."""

from __future__ import annotations

import time
from pathlib import Path

from exifmodern.formats.iso.transaction_plan import (
    ISO_DESCRIPTOR_OFFSET,
    ISO_DESCRIPTOR_SIZE,
    ISO_EVIDENCE_ANCHORS,
    IsoReaderPlan,
    build_iso_reader_plan,
)
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance
from exifmodern.services.system_metadata import read_system_tags

ISO_DESCRIPTOR_READ_LIMIT = 16


def build_iso_read_graph_from_path(
    path: Path,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    descriptors = read_iso_descriptors(path)
    plan = build_iso_reader_plan(descriptors)
    return iso_reader_plan_to_read_graph(plan, path, source_file, generated_at_epoch)


def read_iso_descriptors(path: Path) -> tuple[bytes, ...]:
    descriptors: list[bytes] = []
    with path.open("rb") as file:
        file.seek(ISO_DESCRIPTOR_OFFSET)
        for _ in range(ISO_DESCRIPTOR_READ_LIMIT):
            descriptor = file.read(ISO_DESCRIPTOR_SIZE)
            if len(descriptor) != ISO_DESCRIPTOR_SIZE:
                if descriptor:
                    descriptors.append(descriptor)
                break
            descriptors.append(descriptor)
            if descriptor.startswith(b"\xffCD001"):
                break
            if descriptor[1:6] != b"CD001":
                break
    return tuple(descriptors)


def iso_reader_plan_to_read_graph(
    plan: IsoReaderPlan,
    path: Path,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    tags = [*_system_tags(path, source_file), *_file_identity_tags(), *_iso_tags(plan)]
    diagnostics = [
        f"ISO package-local reader status: {plan.status}",
        (
            "ISO package-local reader diagnostic: bounded_descriptor_read: "
            f"read {len(plan.descriptors)} descriptor sectors starting at byte 32768"
        ),
        *plan.diagnostics,
    ]
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _system_tags(path: Path, source_file: str) -> list[ReadTag]:
    values = read_system_tags(path, source_file)
    tags: list[ReadTag] = []
    for name, value in values.items():
        if not isinstance(value, str):
            continue
        tags.append(
            ReadTag(
                name=name,
                value=value,
                provenance=TagProvenance(
                    group="System",
                    table_name="Image::ExifTool::Extra",
                    tag_id=name,
                    source="filesystem",
                    family_0_group="File",
                    family_1_group="System",
                    family_2_group=_system_family_2(name),
                ),
                schema=None,
            )
        )
    return tags


def _file_identity_tags() -> list[ReadTag]:
    provenance = TagProvenance(
        group="File",
        table_name="Image::ExifTool::File",
        tag_id=None,
        source="iso9660-volume-descriptor",
        family_0_group="File",
        family_1_group="File",
        family_2_group="Other",
    )
    return [
        ReadTag("FileType", "ISO", provenance, None),
        ReadTag("FileTypeExtension", "iso", provenance, None),
        ReadTag("MIMEType", "application/x-iso9660-image", provenance, None),
    ]


def _iso_tags(plan: IsoReaderPlan) -> list[ReadTag]:
    return [
        ReadTag(
            name=tag.name,
            value=tag.value,
            provenance=TagProvenance(
                group=tag.group,
                table_name=tag.table_name,
                tag_id=tag.tag_id,
                source=_source_text(tag.evidence_ids),
                family_0_group=tag.group,
                family_1_group=tag.group,
                family_2_group="Time" if tag.name.endswith("Date") else "Other",
            ),
            schema=None,
        )
        for tag in plan.read_tags
    ]


def _system_family_2(tag_name: str) -> str:
    if tag_name in {"FileModifyDate", "FileAccessDate", "FileInodeChangeDate"}:
        return "Time"
    return "Other"


def _source_text(evidence_ids: tuple[str, ...]) -> str:
    if not evidence_ids:
        return "package-local-iso-reader"
    anchor = ISO_EVIDENCE_ANCHORS[evidence_ids[0]]
    return f"{anchor.path}:{anchor.line_start}-{anchor.line_end}:{anchor.symbol}"
