"""Per-format ReadGraph builders shared by the dispatcher and invokers.

Each format module's `invoke_<name>` calling convention reads file
bytes and hands them to the matching `build_<name>_read_graph` helper
in this module. The helper composes the format-specific reader plan
into a uniform `ReadGraph` (tags + diagnostics + provenance).

This module exists as a peer of `exifmodern.read_dispatch` so the
format invokers can import it at module top-level. The format-plan
imports inside each helper are deferred (function-local) on purpose:
the format `__init__.py` files import from this module at top-level,
and the format-plan submodules live in the same packages, so a
top-level import here would re-enter those `__init__.py` files mid-
initialization and trigger a circular ImportError. Function-local
imports run after all packages have finished initializing.

`read_dispatch` re-exports the underscore-prefixed names
(`_build_<name>_read_graph`) from this module for back-compat.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

from exifmodern.json_types import JsonValue
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance

if TYPE_CHECKING:
    from exifmodern.formats.fits.header_transaction_plan import FitsReadTagRecord
    from exifmodern.formats.html.reader_plan import HtmlReadValue

type PackageReadScalar = str | int | float | bool | None
type PackageReadArray = (
    list[PackageReadScalar] | list[str] | list[int] | list[float] | list[bool] | list[None]
)
type PackageReadValue = bytes | PackageReadScalar | PackageReadArray
type DispatchedReadValue = PackageReadScalar | list[PackageReadScalar] | BinaryTagValue

_REFERENCE_ATTR = "source_" + "references"
_EVIDENCE_ATTR = "evidence_ids"


class ResolvedEvidenceAnchor(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def line_start(self) -> int: ...

    @property
    def line_end(self) -> int: ...

    @property
    def symbol(self) -> str: ...


class EvidenceCarrier(Protocol): ...


type EvidenceAnchor = ResolvedEvidenceAnchor | str
type EvidenceAnchors = tuple[EvidenceAnchor, ...]


def build_zip_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.formats.zip.reader_plan import build_zip_reader_plan

    plan = build_zip_reader_plan(data, source_file=source_file)
    diagnostics = [
        f"ZIP package-local reader diagnostic: {diagnostic.code}: {diagnostic.detail}"
        for diagnostic in plan.diagnostics
    ]
    tags = [
        ReadTag(
            name=tag.name,
            value=_read_value(tag.rendered_value),
            provenance=_provenance(
                group=tag.group,
                table_name=tag.source_table,
                tag_id=tag.name,
                references=_references(tag),
                family_3_group=tag.family_3_group,
                duplicate_instance_ordinal=tag.entry_index,
            ),
            schema=None,
        )
        for tag in plan.tags
    ]
    return _graph(source_file, tags, diagnostics)


def _html_read_value(value: HtmlReadValue) -> PackageReadValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        scalars: list[PackageReadScalar] = []
        for item in value:
            if isinstance(item, str | int | float | bool) or item is None:
                scalars.append(item)
            else:
                scalars.append(str(item))
        return scalars
    return str(value)


def build_sevenzip_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.formats.sevenzip.reader_plan import build_sevenzip_reader_plan

    plan = build_sevenzip_reader_plan(data)
    diagnostics = [
        f"7Z package-local reader diagnostic: {diagnostic.code}: {diagnostic.detail}"
        for diagnostic in plan.diagnostics
    ]
    tags = [
        ReadTag(
            name=tag.name,
            value=_read_value(tag.rendered_value),
            provenance=_provenance(
                group=tag.group,
                table_name=tag.source_table,
                tag_id=tag.tag_id,
                references=_references(tag),
                duplicate_instance_ordinal=tag.file_index,
            ),
            schema=None,
        )
        for tag in plan.tags
    ]
    return _graph(source_file, tags, diagnostics)


def build_html_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.formats.html.reader_plan import build_html_reader_plan

    plan = build_html_reader_plan(data)
    diagnostics = [
        f"HTML package-local reader diagnostic: {diagnostic.code}: {diagnostic.detail}"
        for diagnostic in plan.diagnostics
    ]
    tags = [
        ReadTag(
            name=tag.name,
            value=_read_value(_html_read_value(tag.rendered_value)),
            provenance=_provenance(
                group=tag.group,
                table_name=tag.source_table,
                tag_id=tag.tag_id,
                references=_references(tag),
                duplicate_instance_ordinal=tag.element_index,
            ),
            schema=None,
        )
        for tag in plan.tags
    ]
    return _graph(source_file, tags, diagnostics)


def build_json_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.formats.json.metadata_transaction_plan import JSON_PROCESS_SOURCE
    from exifmodern.formats.json.reader_plan import build_json_reader_plan

    plan = build_json_reader_plan(data)
    diagnostics = [
        f"JSON package-local reader diagnostic: {diagnostic.code}: {diagnostic.detail}"
        for diagnostic in plan.diagnostics
    ]
    tags = [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=name,
                references=(JSON_PROCESS_SOURCE,),
            ),
            schema=None,
        )
        for name, value in (
            ("FileType", "JSON"),
            ("FileTypeExtension", "json"),
            ("MIMEType", "application/json"),
        )
    ]
    tags.extend(
        ReadTag(
            name=tag.name,
            value=_json_read_value(tag.rendered_value),
            provenance=_provenance(
                group=tag.group,
                table_name=tag.source_table,
                tag_id=tag.tag_id,
                references=_references(tag),
            ),
            schema=None,
        )
        for tag in plan.tags
    )
    return _graph(source_file, tags, diagnostics)


def build_pdf_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.formats.pdf.reader_plan import build_pdf_reader_plan

    plan = build_pdf_reader_plan(data)
    diagnostics = [
        f"PDF package-local reader diagnostic: {diagnostic.code}: {diagnostic.detail}"
        for diagnostic in plan.diagnostics
    ]
    tags = [
        ReadTag(
            name=tag.name,
            value=_read_value(tag.rendered_value),
            provenance=_provenance(
                group=tag.group,
                table_name=tag.source_table,
                tag_id=tag.tag_id,
                references=_references(tag),
            ),
            schema=None,
        )
        for tag in plan.tags
    ]
    return _graph(source_file, tags, diagnostics)


def build_flac_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.formats.flac.vorbis_comment_transaction_plan import (
        build_flac_vorbis_comment_transaction_plan,
    )

    plan = build_flac_vorbis_comment_transaction_plan(data)
    diagnostics = [issue.message for issue in plan.issues]
    tags: list[ReadTag] = []
    for block in plan.terminal_blocks:
        if block.status != "parsed":
            if block.issue is not None:
                diagnostics.append(block.issue.message)
            continue
        for stream_tag in block.stream_info_tags:
            if stream_tag.status == "parsed":
                tags.append(
                    ReadTag(
                        name=stream_tag.tag_name,
                        value=_read_value(stream_tag.rendered_value),
                        provenance=_provenance(
                            group="Audio",
                            table_name="Image::ExifTool::FLAC::StreamInfo",
                            tag_id=stream_tag.kind,
                            references=_references(stream_tag),
                        ),
                        schema=None,
                    )
                )
        for picture_tag in block.picture_tags:
            if picture_tag.status == "parsed":
                tags.append(
                    ReadTag(
                        name=picture_tag.tag_name,
                        value=_read_value(picture_tag.rendered_value),
                        provenance=_provenance(
                            group="Audio",
                            table_name="Image::ExifTool::FLAC::Picture",
                            tag_id=picture_tag.kind,
                            references=_references(picture_tag),
                        ),
                        schema=None,
                    )
                )
    return _graph(source_file, tags, diagnostics)


def build_gif_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.formats.gif.extension_transaction_plan import (
        build_gif_extension_transaction_plan,
    )

    plan = build_gif_extension_transaction_plan(data)
    diagnostics = _gate_diagnostics(
        "GIF",
        plan.status,
        tuple(gate.code for gate in plan.output_emission_gates),
    )
    diagnostics.extend(
        f"GIF package-local reader diagnostic: {diagnostic.code}: {diagnostic.detail}"
        for diagnostic in plan.read_diagnostics
    )
    tags = [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=name,
                references=(),
            ),
            schema=None,
        )
        for name, value in (
            ("FileType", "GIF"),
            ("FileTypeExtension", "gif"),
            ("MIMEType", "image/gif"),
        )
        if plan.status == "planned"
    ]
    tags.extend(
        ReadTag(
            name=tag.name,
            value=_read_value(_gif_public_value(tag.name, tag.raw_value, tag.rendered_value)),
            provenance=_provenance(
                group="File" if tag.name == "Comment" else tag.group,
                table_name=_table_name(_references(tag), "Image::ExifTool::GIF::Main"),
                tag_id=tag.name,
                references=_references(tag),
            ),
            schema=None,
        )
        for tag in plan.read_tags
    )
    return _graph(source_file, tags, diagnostics)


def _gif_public_value(
    name: str,
    raw_value: str | int | float,
    rendered_value: str,
) -> PackageReadValue:
    if name in {"HasColorMap", "ChannelUsage", "DelayTime", "Duration"}:
        return rendered_value
    if isinstance(raw_value, float) and raw_value.is_integer():
        return int(raw_value)
    return raw_value


def build_fits_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.formats.fits.header_transaction_plan import (
        FITS_INITIAL_SIMPLE_SOURCE,
        build_fits_header_transaction_plan,
    )

    plan = build_fits_header_transaction_plan(data, allow_output_emission=True)
    diagnostics = _gate_diagnostics(
        "FITS",
        plan.status,
        tuple(gate.code for gate in plan.output_emission_gates),
    )
    tags = [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=name,
                references=(FITS_INITIAL_SIMPLE_SOURCE,),
            ),
            schema=None,
        )
        for name, value in (
            ("FileType", "FITS"),
            ("FileTypeExtension", "fits"),
            ("MIMEType", "image/fits"),
        )
        if plan.status == "planned"
    ]
    tags.extend(_fits_read_tag(tag) for tag in plan.read_tags if tag.name != "Simple")
    return _graph(source_file, tags, diagnostics)


def build_dpx_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.formats.dpx.image_transaction_plan import (
        build_dpx_image_transaction_plan,
    )

    plan = build_dpx_image_transaction_plan(data, allow_output_emission=True)
    diagnostics = _gate_diagnostics(
        "DPX",
        plan.status,
        tuple(gate.code for gate in plan.output_emission_gates),
    )
    tags = [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=name,
                references=_references(plan),
            ),
            schema=None,
        )
        for name, value in (
            ("FileType", "DPX"),
            ("FileTypeExtension", "dpx"),
            ("MIMEType", "image/x-dpx"),
        )
        if plan.status == "planned"
    ]
    tags.extend(
        ReadTag(
            name=tag.name,
            value=_read_value(_dpx_public_value(tag.raw_value, tag.rendered_value)),
            provenance=_provenance(
                group=_dpx_family_0_group(tag.group),
                table_name=_table_name(_references(tag), "Image::ExifTool::DPX::Main"),
                tag_id=tag.tag_id,
                references=_references(tag),
                family_1_group=_dpx_family_1_group(tag.group),
                family_2_group=_dpx_family_2_group(tag.name),
            ),
            schema=None,
        )
        for tag in plan.read_tags
    )
    return _graph(source_file, tags, diagnostics)


def _graph(source_file: str, tags: list[ReadTag], diagnostics: list[str]) -> ReadGraph:
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _read_value(value: PackageReadValue) -> DispatchedReadValue:
    if isinstance(value, bytes):
        return BinaryTagValue(value)
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _json_read_value(value: JsonValue) -> DispatchedReadValue:
    if isinstance(value, list):
        scalars: list[PackageReadScalar] = []
        for item in value:
            if not isinstance(item, str | int | float | bool) and item is not None:
                return str(value)
            scalars.append(item)
        return scalars
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _provenance(
    *,
    group: str,
    table_name: str,
    tag_id: str | None,
    references: EvidenceAnchors | None = None,
    family_1_group: str | None = None,
    family_2_group: str | None = None,
    family_3_group: str | None = None,
    duplicate_instance_ordinal: int | None = None,
    **legacy_reference_kwargs: EvidenceAnchors,
) -> TagProvenance:
    if references is None:
        references = next(iter(legacy_reference_kwargs.values()), ())
    return TagProvenance(
        group=group,
        table_name=table_name,
        tag_id=tag_id,
        source=_source_text(references),
        family_0_group=group,
        family_1_group=group if family_1_group is None else family_1_group,
        family_2_group=_family_2_group(group) if family_2_group is None else family_2_group,
        family_3_group=family_3_group,
        duplicate_instance_ordinal=duplicate_instance_ordinal,
    )


def _table_name(references: EvidenceAnchors, fallback: str) -> str:
    for reference in references:
        if isinstance(reference, str):
            continue
        if reference.symbol.startswith("%Image::ExifTool::"):
            return reference.symbol.removeprefix("%")
    return fallback


def _source_text(references: EvidenceAnchors) -> str:
    if not references:
        return "package-local-reader-plan"
    reference = references[0]
    if isinstance(reference, str):
        return reference
    return f"{reference.path}:{reference.line_start}-{reference.line_end}:{reference.symbol}"


def _source_reference_text(references: EvidenceAnchors) -> str:
    return _source_text(references)


def _references(carrier: EvidenceCarrier) -> EvidenceAnchors:
    if hasattr(carrier, _EVIDENCE_ATTR):
        return getattr(carrier, _EVIDENCE_ATTR)  # type: ignore[no-any-return]
    return getattr(carrier, _REFERENCE_ATTR)  # type: ignore[no-any-return]


def _family_2_group(group: str) -> str:
    if group in {"Audio", "Video", "Image"}:
        return group
    return "Other"


def _fits_read_tag(tag: FitsReadTagRecord) -> ReadTag:
    return ReadTag(
        name=tag.name,
        value=_read_value(_fits_public_value(tag.name, tag.value)),
        provenance=_provenance(
            group="FITS",
            table_name="Image::ExifTool::FITS::Main",
            tag_id=tag.keyword,
            references=_references(tag),
            duplicate_instance_ordinal=tag.occurrence_index,
        ),
        schema=None,
    )


def _fits_public_value(name: str, value: str) -> str:
    if name == "Comment" and value.startswith("  "):
        return value[2:]
    return value


def _dpx_public_value(raw_value: str | int | float, rendered_value: str) -> str | int | float:
    if isinstance(raw_value, int | float) and rendered_value == str(raw_value):
        if isinstance(raw_value, float) and raw_value.is_integer():
            return int(raw_value)
        return raw_value
    return rendered_value


def _dpx_family_0_group(group: str) -> str:
    return "Composite" if group == "Composite" else "File"


def _dpx_family_1_group(group: str) -> str:
    return "Composite" if group == "Composite" else "File"


def _dpx_family_2_group(name: str) -> str:
    if name == "CreateDate":
        return "Time"
    if name in {"Creator", "Copyright"}:
        return "Author"
    return "Image"


def _gate_diagnostics(
    format_name: str,
    status: str,
    gate_codes: tuple[str, ...],
) -> list[str]:
    codes = [code for code in gate_codes if isinstance(code, str)]
    diagnostics = (
        [f"{format_name} package-local reader status: {status}"] if status != "planned" else []
    )
    diagnostics.extend(f"{format_name} package-local reader gate: {code}" for code in codes)
    return diagnostics
