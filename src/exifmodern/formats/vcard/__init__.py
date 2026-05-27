"""vCard metadata transaction planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.vcard.metadata_transaction_plan import (
    VCardMetadataTransactionPlan,
    VCardParameterTagPlan,
    VCardRewriteRequest,
    build_vcard_metadata_transaction_plan,
)
from exifmodern.formats.vcard.subdocument_plan import (
    VCardSubdocumentPlan,
    build_vcard_subdocument_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = (
    "VCardMetadataTransactionPlan",
    "VCardRewriteRequest",
    "VCardSubdocumentPlan",
    "build_vcard_metadata_transaction_plan",
    "build_vcard_read_graph",
    "build_vcard_subdocument_plan",
    "invoke_vcard",
)


_VCARD_TABLE = "Image::ExifTool::VCard::Main"
_VCALENDAR_TABLE = "Image::ExifTool::VCard::VCalendar"
_VCARD_TEXT_SCAN_LIMIT = 8 * 1024 * 1024
type VCardReadValue = str | int | float | bool | list[float]


def build_vcard_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a vCard transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_vcard_metadata_transaction_plan(data)
    diagnostics = [
        f"vCard package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"vCard package-local reader status: {plan.status}")

    tags: list[ReadTag] = []
    tag_indexes: dict[tuple[str, str], int] = {}
    first_document_end = _first_document_end_line(plan)
    parameter_tags_by_line: dict[int, list[tuple[int, VCardParameterTagPlan]]] = {}
    for index, parameter_tag in enumerate(plan.parameter_tags):
        parameter_tags_by_line.setdefault(parameter_tag.property_line_index, []).append(
            (index, parameter_tag)
        )
    table_name = _VCALENDAR_TABLE if plan.signature.kind == "vcalendar" else _VCARD_TABLE
    if plan.signature.kind in {"vcard", "vcalendar"}:
        for name, file_value in _file_tags_for_container(plan.signature.kind):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(file_value),
                    provenance=_provenance(
                        group="File",
                        table_name="File",
                        tag_id=name,
                        references=(),
                    ),
                    schema=None,
                )
            )
    for index, prop in enumerate(plan.properties):
        property_value: str
        if prop.value.kind == "binary":
            property_value = _binary_suppression(prop.value.binary_value)
        elif prop.value.display_values:
            property_value = (
                "; ".join(prop.value.display_values)
                if len(prop.value.display_values) > 1
                else prop.value.display_values[0]
            )
        else:
            property_value = prop.value.raw_value
        group = _vcard_family1_group(plan.signature.kind, prop.family1_group)
        name = _vcard_display_name(prop.display_name, prop.language)
        rendered_value = _vcard_rendered_value(prop.routed_tag, name, property_value)
        _append_vcard_tag(
            tags,
            tag_indexes,
            ReadTag(
                name=name,
                value=_read_value(rendered_value),
                provenance=_provenance(
                    group=group,
                    table_name=table_name,
                    tag_id=prop.routed_tag,
                    references=(),
                    duplicate_instance_ordinal=index,
                ),
                schema=None,
            ),
            skip_duplicate=(
                group == "VCard"
                and first_document_end is not None
                and prop.line_index > first_document_end
            ),
        )
        parameter_tag_items = parameter_tags_by_line.get(prop.line_index, [])
        for parameter_index, parameter_tag in parameter_tag_items:
            if not parameter_tag.values:
                continue
            joined = _parameter_value(parameter_tag.parameter_name, parameter_tag.values)
            _append_vcard_tag(
                tags,
                tag_indexes,
                ReadTag(
                    name=parameter_tag.display_name,
                    value=_read_value(joined),
                    provenance=_provenance(
                        group=group,
                        table_name=table_name,
                        tag_id=parameter_tag.routed_tag,
                        references=(),
                        duplicate_instance_ordinal=parameter_index,
                    ),
                    schema=None,
                ),
                skip_duplicate=False,
            )
    return _graph(source_file, tags, diagnostics)


def _file_tags_for_container(kind: str) -> tuple[tuple[str, str], ...]:
    if kind == "vcalendar":
        return (
            ("FileType", "ICS"),
            ("FileTypeExtension", "ics"),
            ("MIMEType", "text/calendar"),
        )
    return (
        ("FileType", "VCard"),
        ("FileTypeExtension", "vcf"),
        ("MIMEType", "text/vcard"),
    )


def _vcard_family1_group(kind: str, family1_group: str | None) -> str:
    if family1_group is not None:
        return family1_group
    return "VCalendar" if kind == "vcalendar" else "VCard"


def _vcard_display_name(name: str, language: str | None) -> str:
    if language:
        return f"{name}-{language}"
    return name


def _binary_suppression(value: bytes | None) -> str:
    size = 0 if value is None else len(value)
    return f"(Binary data {size} bytes, use -b option to extract)"


def _vcard_rendered_value(tag_id: str, name: str, value: str) -> str | int | float | bool:
    if name == "ABLabel":
        return value.removeprefix("_$!<").removesuffix(">!$_")
    if name == "Birthday":
        return value.replace("-", ":")
    if name in {"VCardVersion", "VCalendarVersion"}:
        try:
            return float(value)
        except ValueError:
            return value
    if name.endswith("DefaultAlarm") or name.endswith("LocalDefaultAlarm"):
        return value == "TRUE"
    return value


def _parameter_value(name: str, values: tuple[str, ...]) -> str | list[float]:
    if name == "Geo":
        floats: list[float] = []
        for value in values:
            try:
                floats.append(float(value))
            except ValueError:
                return "; ".join(values)
        return floats
    return "; ".join(values)


def _first_document_end_line(plan: VCardMetadataTransactionPlan) -> int | None:
    for line in plan.logical_lines:
        if line.unfolded_text.upper() == "END:VCARD":
            return line.index
    return None


def _append_vcard_tag(
    tags: list[ReadTag],
    indexes: dict[tuple[str, str], int],
    tag: ReadTag,
    *,
    skip_duplicate: bool,
) -> None:
    key = (tag.provenance.group, tag.name)
    existing = indexes.get(key)
    if existing is None:
        indexes[key] = len(tags)
        tags.append(tag)
        return
    if skip_duplicate:
        return
    tags[existing] = tag


def invoke_vcard(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_vcard_read_graph(_read_bounded_prefix(path, _VCARD_TEXT_SCAN_LIMIT), source_file)


def _read_bounded_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="vcard",
        builder_ref="exifmodern.formats.vcard:invoke_vcard",
        patterns=(Pattern(0, b"BEGIN:V"),),
        notes=("case-insensitive in spec; trie matches uppercase only",),
    ),
)
