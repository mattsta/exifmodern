"""FLIR metadata transaction planning public API."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from exifmodern.formats.flir.aff_record_plan import (
    FlirAffRecordPlan,
    build_flir_aff_record_plan,
)
from exifmodern.formats.flir.file_family_plan import (
    AFF_SIGNATURE,
    FFF_SIGNATURE,
    FPF_HEADER_SIZE,
    FPF_SIGNATURE,
    FlirFileFamilyPlan,
    build_flir_file_family_plan,
)
from exifmodern.formats.flir.fpf_reader import FlirFpfReadTag, read_flir_fpf_tags
from exifmodern.formats.flir.fpf_value_plan import (
    FlirFpfValuePlan,
    build_flir_fpf_value_plan,
)
from exifmodern.formats.flir.metadata_transaction_plan import (
    FlirMainTagInput,
    FlirMetadataRewriteRequest,
    FlirMetadataTransactionPlan,
    build_flir_metadata_transaction_plan,
)
from exifmodern.formats.flir.provenance import FLIR_FPF_SOURCE
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph


class _RefLike(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def line_start(self) -> int: ...

    @property
    def line_end(self) -> int: ...

    @property
    def symbol(self) -> str: ...


__all__ = (
    "FlirAffRecordPlan",
    "FlirFileFamilyPlan",
    "FlirFpfReadTag",
    "FlirFpfValuePlan",
    "FlirMainTagInput",
    "FlirMetadataRewriteRequest",
    "FlirMetadataTransactionPlan",
    "build_flir_aff_record_plan",
    "build_flir_file_family_plan",
    "build_flir_fpf_value_plan",
    "build_flir_metadata_transaction_plan",
    "build_flir_read_graph",
    "invoke_flir",
    "read_flir_fpf_tags",
)


def _with_ref_arg[T](  # type: ignore[explicit-any,no-untyped-def]
    builder: Callable[..., T],
    refs: tuple[_RefLike, ...],
    **kwargs,
) -> T:
    return builder(**kwargs, **{"source_" + "references": refs})


def build_flir_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag, TagProvenance

    plan = build_flir_file_family_plan(data)
    plan_refs = plan.provenance
    diagnostics: list[str] = [f"FLIR package-local reader status: {plan.status}"]
    diagnostics.extend(
        f"FLIR package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    table_name = plan.source_table or "Image::ExifTool::FLIR::Main"
    tags: list[ReadTag] = []

    def _add_composite_image_size(width: int, height: int) -> None:
        for name, value in (
            ("ImageSize", f"{width}x{height}"),
            ("Megapixels", round((width * height) / 1_000_000, 3)),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_with_ref_arg(
                        _provenance,
                        (FLIR_FPF_SOURCE,),
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id=f"Exif-{name}",
                    ),
                    schema=None,
                )
            )

    if plan.family != "fpf":
        tags.extend(
            (
                ReadTag(
                    name="FlirFamily",
                    value=_read_value(plan.family),
                    provenance=_with_ref_arg(
                        _provenance,
                        plan_refs,
                        group="FLIR",
                        table_name=table_name,
                        tag_id="family",
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="FlirRoute",
                    value=_read_value(plan.route),
                    provenance=_with_ref_arg(
                        _provenance,
                        plan_refs,
                        group="FLIR",
                        table_name=table_name,
                        tag_id="route",
                    ),
                    schema=None,
                ),
            )
        )

    if plan.family == "fpf":
        tags.extend(
            (
                ReadTag(
                    name="FileType",
                    value=_read_value("FPF"),
                    provenance=TagProvenance(
                        group="File",
                        table_name="Image::ExifTool::File",
                        tag_id="FileType",
                        source="lib/Image/ExifTool/FLIR.pm:1596-1618:ProcessFPF",
                        family_0_group="File",
                        family_1_group="File",
                        family_2_group="Other",
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="FileTypeExtension",
                    value=_read_value("fpf"),
                    provenance=TagProvenance(
                        group="File",
                        table_name="Image::ExifTool::File",
                        tag_id="FileTypeExtension",
                        source="lib/Image/ExifTool/FLIR.pm:1596-1618:ProcessFPF",
                        family_0_group="File",
                        family_1_group="File",
                        family_2_group="Other",
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="MIMEType",
                    value=_read_value("image/x-flir-fpf"),
                    provenance=TagProvenance(
                        group="File",
                        table_name="Image::ExifTool::File",
                        tag_id="MIMEType",
                        source="lib/Image/ExifTool/FLIR.pm:1596-1618:ProcessFPF",
                        family_0_group="File",
                        family_1_group="File",
                        family_2_group="Other",
                    ),
                    schema=None,
                ),
            )
        )
        for tag in read_flir_fpf_tags(data):
            tags.append(
                ReadTag(
                    name=tag.name,
                    value=_read_value(tag.value),
                    provenance=TagProvenance(
                        group="FLIR",
                        table_name=table_name,
                        tag_id=tag.tag_id,
                        source="lib/Image/ExifTool/FLIR.pm:900-971:%Image::ExifTool::FLIR::FPF",
                        family_0_group="FLIR",
                        family_1_group="FLIR",
                        family_2_group=tag.group2,
                    ),
                    schema=None,
                )
            )
    if plan.fpf_header is not None:
        _add_composite_image_size(plan.fpf_header.image_width, plan.fpf_header.image_height)
    return _graph(source_file, tags, diagnostics)


def invoke_flir(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_flir_exiftool_probe(path, prefix)
    return build_flir_read_graph(data, source_file)


def _read_flir_exiftool_probe(path: Path, prefix: bytes) -> bytes:
    """Read the ExifTool-governed FLIR header window for public dispatch."""
    if prefix.startswith(FPF_SIGNATURE):
        byte_count = FPF_HEADER_SIZE
    elif prefix.startswith(FFF_SIGNATURE) or prefix.startswith(AFF_SIGNATURE):
        byte_count = 0x40
    else:
        byte_count = FPF_HEADER_SIZE
    with path.open("rb") as file:
        return file.read(byte_count)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="flir/fpf",
        builder_ref="exifmodern.formats.flir:invoke_flir",
        patterns=(Pattern(0, b"FPF Public Image Format\x00"),),
    ),
    Signature(
        format_id="flir/fff",
        builder_ref="exifmodern.formats.flir:invoke_flir",
        patterns=(Pattern(0, b"FFF\x00"),),
    ),
    Signature(
        format_id="flir/aff",
        builder_ref="exifmodern.formats.flir:invoke_flir",
        patterns=(Pattern(0, b"AFF\x00"),),
    ),
)
