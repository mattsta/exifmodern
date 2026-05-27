"""MRC metadata transaction planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.mrc.metadata_transaction_plan import (
    MRC_HEADER_SIZE,
    MrcMetadataTransactionPlan,
    MrcRewriteRequest,
    build_mrc_metadata_transaction_plan,
)
from exifmodern.media_source import FileMediaSource
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = (
    "MrcMetadataTransactionPlan",
    "MrcRewriteRequest",
    "build_mrc_metadata_transaction_plan",
    "build_mrc_read_graph",
    "invoke_mrc",
    "is_mrc_prefix",
)


def is_mrc_prefix(prefix: bytes) -> bool:
    plan = build_mrc_metadata_transaction_plan(prefix)
    return plan.header_validation.is_exiftool_accepted


def build_mrc_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph

    plan = build_mrc_metadata_transaction_plan(data)
    diagnostics = [
        f"MRC package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    tags: list[ReadTag] = [
        _mrc_tag(
            "Warning",
            "Warning",
            "[minor] Use the ExtractEmbedded option to read metadata for all frames",
            plan.header_validation.evidence_ids,
            group="ExifTool",
            table_name="Image::ExifTool",
        ),
        _mrc_tag("FileType", "FileType", "MRC", plan.header_validation.evidence_ids, group="File"),
        _mrc_tag(
            "FileTypeExtension",
            "FileTypeExtension",
            "mrc",
            plan.header_validation.evidence_ids,
            group="File",
        ),
        _mrc_tag(
            "MIMEType",
            "MIMEType",
            "image/x-mrc",
            plan.header_validation.evidence_ids,
            group="File",
        ),
    ]
    dimensions = plan.dimensions
    if dimensions is not None:
        for name, tag_id, dimension_value in (
            ("ImageWidth", "0", dimensions.image_width),
            ("ImageHeight", "1", dimensions.image_height),
            ("ImageDepth", "2", dimensions.image_depth),
        ):
            tags.append(_mrc_tag(name, tag_id, dimension_value, dimensions.evidence_ids))
    if plan.mode is not None:
        tags.append(
            _mrc_tag(
                "ImageMode",
                "3",
                plan.mode.description or plan.mode.mode_code,
                plan.mode.evidence_ids,
            )
        )
    if dimensions is not None:
        for name, tag_id, vector_value in (
            ("StartPoint", "4", _join_ints(dimensions.start_point)),
            ("GridSize", "7", _join_ints(dimensions.grid_size)),
        ):
            tags.append(_mrc_tag(name, tag_id, vector_value, dimensions.evidence_ids))
    if plan.cell is not None:
        for name, tag_id, cell_value in (
            ("CellWidth", "10", _mrc_render_value(plan.cell.cell_size_angstroms[0])),
            ("CellHeight", "11", _mrc_render_value(plan.cell.cell_size_angstroms[1])),
            ("CellDepth", "12", _mrc_render_value(plan.cell.cell_size_angstroms[2])),
            ("CellAlpha", "13", _mrc_render_value(plan.cell.cell_angles_degrees[0])),
            ("CellBeta", "14", _mrc_render_value(plan.cell.cell_angles_degrees[1])),
            ("CellGamma", "15", _mrc_render_value(plan.cell.cell_angles_degrees[2])),
        ):
            tags.append(_mrc_tag(name, tag_id, cell_value, plan.cell.evidence_ids))
    if plan.axes is not None:
        for name, tag_id, axis_value in (
            ("ImageWidthAxis", "16", plan.axes.width_axis_label),
            ("ImageHeightAxis", "17", plan.axes.height_axis_label),
            ("ImageDepthAxis", "18", plan.axes.depth_axis_label),
        ):
            tags.append(_mrc_tag(name, tag_id, axis_value, plan.axes.evidence_ids))
    if plan.statistics is not None:
        statistic_tags: tuple[tuple[str, str, str | int | float], ...] = (
            ("DensityMin", "19", _mrc_render_value(plan.statistics.density_min)),
            ("DensityMax", "20", _mrc_render_value(plan.statistics.density_max)),
            ("DensityMean", "21", _mrc_render_value(plan.statistics.density_mean)),
            ("SpaceGroupNumber", "22", plan.statistics.space_group_number),
        )
        for name, tag_id, statistics_value in statistic_tags:
            tags.append(_mrc_tag(name, tag_id, statistics_value, plan.statistics.evidence_ids))
    if plan.extended_header is not None:
        for name, tag_id, extended_header_value in (
            ("ExtendedHeaderSize", "23", plan.extended_header.declared_size),
            ("ExtendedHeaderType", "26", plan.extended_header.header_type),
        ):
            tags.append(
                _mrc_tag(
                    name,
                    tag_id,
                    extended_header_value,
                    plan.extended_header.evidence_ids,
                )
            )
    if plan.header_validation.mrc_version is not None:
        tags.append(
            _mrc_tag(
                "MRCVersion",
                "27",
                plan.header_validation.mrc_version,
                plan.header_validation.evidence_ids,
            )
        )
    if plan.cell is not None:
        tags.append(
            _mrc_tag(
                "Origin",
                "49",
                _join_floats(plan.cell.origin),
                plan.cell.evidence_ids,
            )
        )
    tags.append(
        _mrc_tag(
            "MachineStamp",
            "53",
            _machine_stamp_value(plan.header_validation.machine_stamp),
            plan.header_validation.evidence_ids,
        )
    )
    if plan.statistics is not None:
        tags.append(
            _mrc_tag(
                "RMSDeviation",
                "54",
                _mrc_render_value(plan.statistics.rms_deviation),
                plan.statistics.evidence_ids,
            )
        )
    if plan.labels is not None:
        tags.append(
            _mrc_tag(
                "NumberOfLabels",
                "55",
                plan.labels.number_of_labels,
                plan.labels.evidence_ids,
            )
        )
        for index, label in enumerate(plan.labels.labels):
            if label:
                tags.append(
                    _mrc_tag(
                        f"Label{index + 1}",
                        str(56 + index * 20),
                        label,
                        plan.labels.evidence_ids,
                    )
                )
    for tag in plan.fei_tags:
        tags.append(
            _mrc_tag(
                tag.name,
                str(tag.tag_id),
                _mrc_render_value(tag.value),
                tag.evidence_ids,
                group="File",
                table_name="Image::ExifTool::MRC::FEI12",
            )
        )
    tags.extend(_mrc_composite_tags(plan))
    return _graph(source_file, tags, diagnostics)


def _mrc_tag(
    name: str,
    tag_id: str,
    value: str | int | float,
    evidence_ids: tuple[str, ...],
    *,
    group: str = "File",
    table_name: str = "Image::ExifTool::MRC::Main",
) -> ReadTag:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            evidence_ids=evidence_ids,
        ),
        schema=None,
    )


def _join_ints(values: tuple[int, int, int]) -> str:
    return " ".join(str(value) for value in values)


def _join_floats(values: tuple[float, float, float]) -> str:
    return " ".join(str(_mrc_render_value(value)) for value in values)


def _machine_stamp_value(value: bytes) -> str:
    return " ".join(f"0x{byte:02x}" for byte in value)


def _mrc_render_value(value: str | int | float) -> str | int | float:
    if isinstance(value, int) and abs(value) >= 10**15:
        return float(f"{value:.15g}")
    if not isinstance(value, float):
        return value
    if abs(value) >= 10**15:
        return float(f"{value:.15g}")
    if value.is_integer():
        return int(value)
    return f"{value:.15g}"


def _mrc_composite_tags(plan: MrcMetadataTransactionPlan) -> list[ReadTag]:
    if plan.dimensions is None:
        return []
    width = plan.dimensions.image_width
    height = plan.dimensions.image_height
    return [
        _mrc_tag(
            "ImageSize",
            "ImageSize",
            f"{width}x{height}",
            plan.dimensions.evidence_ids,
            group="Composite",
            table_name="Image::ExifTool::Composite",
        ),
        _mrc_tag(
            "Megapixels",
            "Megapixels",
            round(width * height / 1_000_000, 1),
            plan.dimensions.evidence_ids,
            group="Composite",
            table_name="Image::ExifTool::Composite",
        ),
    ]


def invoke_mrc(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_mrc_read_graph(_mrc_reader_prefix(path, prefix), source_file)


def _mrc_reader_prefix(path: Path, prefix: bytes) -> bytes:
    source = FileMediaSource(path)
    data = (
        prefix[:MRC_HEADER_SIZE]
        if len(prefix) >= MRC_HEADER_SIZE
        else source.prefix(MRC_HEADER_SIZE)
    )
    if len(data) < MRC_HEADER_SIZE:
        return data
    declared_extended_size = int.from_bytes(data[92:96], "little")
    extended_type = data[104:108].decode("latin-1", errors="replace").rstrip("\x00 ")
    if declared_extended_size == 0 or not extended_type.startswith(("FEI1", "FEI2")):
        return data
    metadata_size_probe = MRC_HEADER_SIZE + 4
    if len(prefix) >= metadata_size_probe:
        probe = prefix[:metadata_size_probe]
    else:
        probe = source.prefix(metadata_size_probe)
    if len(probe) < metadata_size_probe:
        return probe
    metadata_size = int.from_bytes(probe[MRC_HEADER_SIZE:metadata_size_probe], "little")
    if metadata_size <= 0 or metadata_size > declared_extended_size:
        return probe
    desired_size = MRC_HEADER_SIZE + metadata_size
    if len(prefix) >= desired_size:
        return prefix[:desired_size]
    return source.prefix(desired_size)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="mrc",
        builder_ref="exifmodern.formats.mrc:invoke_mrc",
        patterns=(Pattern(208, b"MAP"),),
        structural_check="exifmodern.formats.mrc:is_mrc_prefix",
        weak=True,
    ),
)
