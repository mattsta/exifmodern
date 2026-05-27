"""Source-backed HTML metadata reader plan."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.html.metadata_transaction_plan import (
    HTML_SIGNATURE_SOURCE,
    HTML_TITLE_SOURCE,
    HTML_TRANSACTION_SOURCES,
    HTML_XML_SOURCE,
    HtmlMetadataTransactionPlan,
    build_html_metadata_transaction_plan,
)
from exifmodern.json_types import JsonArray, JsonObject

type HtmlReaderStatus = Literal["planned", "unsupported"]
type HtmlReaderDiagnosticCode = Literal["malformed_html_header", "unsupported_html_document"]
type HtmlReadScalar = str | int | float
type HtmlReadArray = JsonArray
type HtmlReadValue = HtmlReadScalar | HtmlReadArray


@dataclass(frozen=True)
class HtmlReaderDiagnostic:
    code: HtmlReaderDiagnosticCode
    detail: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class HtmlReadTag:
    name: str
    group: str
    source_table: str
    tag_id: str
    raw_value: HtmlReadValue
    rendered_value: HtmlReadValue
    element_index: int
    byte_offset: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_offset": self.byte_offset,
            "element_index": self.element_index,
            "group": self.group,
            "name": self.name,
            "raw_value": self.raw_value,
            "rendered_value": self.rendered_value,
            "source_table": self.source_table,
            "tag_id": self.tag_id,
        }


@dataclass(frozen=True)
class HtmlReaderPlan:
    status: HtmlReaderStatus
    metadata: HtmlMetadataTransactionPlan
    tags: tuple[HtmlReadTag, ...]
    diagnostics: tuple[HtmlReaderDiagnostic, ...]
    evidence_ids: tuple[str, ...]

    def tags_by_name(self) -> dict[str, tuple[HtmlReadTag, ...]]:
        names = {tag.name for tag in self.tags}
        return {name: tuple(tag for tag in self.tags if tag.name == name) for name in names}

    def to_json(self) -> JsonObject:
        return {
            "diagnostics": [diagnostic.to_json() for diagnostic in self.diagnostics],
            "status": self.status,
            "tags": [tag.to_json() for tag in self.tags],
        }


def build_html_reader_plan(data: bytes) -> HtmlReaderPlan:
    metadata = build_html_metadata_transaction_plan(data, allow_output_emission=True)
    diagnostics = tuple(
        HtmlReaderDiagnostic(
            code=(
                "malformed_html_header"
                if gate.code.startswith("truncated") or gate.code == "unclosed_non_meta_element"
                else "unsupported_html_document"
            ),
            detail=gate.code,
            evidence_ids=gate.evidence_ids,
        )
        for gate in metadata.output_emission_gates
        if gate.code != "missing_head"
    )
    tags: list[HtmlReadTag] = []
    if metadata.signature.accepted:
        for name, file_value in (
            ("FileType", "HTML"),
            ("FileTypeExtension", "html"),
            ("MIMEType", "text/html"),
        ):
            tags.append(
                HtmlReadTag(
                    name=name,
                    group="File",
                    source_table="Image::ExifTool::File",
                    tag_id=name,
                    raw_value=file_value,
                    rendered_value=file_value,
                    element_index=-1,
                    byte_offset=0,
                    evidence_ids=(HTML_SIGNATURE_SOURCE,),
                )
            )
    for meta in metadata.meta_tags:
        name, group, table, rendered_value = _meta_tag_output(
            meta.group, meta.normalized_tag, meta.value
        )
        tags.append(
            HtmlReadTag(
                name=name,
                group=group,
                source_table=table,
                tag_id=meta.tag_name,
                raw_value=meta.raw_content,
                rendered_value=rendered_value,
                element_index=meta.element_index,
                byte_offset=_element_offset(metadata, meta.element_index),
                evidence_ids=meta.evidence_ids,
            )
        )
    for child in metadata.xml_children:
        name, group, table, rendered_value = _xml_child_output(child.group, child.tag, child.value)
        tags.append(
            HtmlReadTag(
                name=name,
                group=group,
                source_table=table,
                tag_id=child.tag,
                raw_value=child.raw_value,
                rendered_value=rendered_value,
                element_index=child.element_index,
                byte_offset=_element_offset(metadata, child.element_index),
                evidence_ids=(HTML_XML_SOURCE,),
            )
        )
    if metadata.title is not None:
        tags.append(
            HtmlReadTag(
                name="Title",
                group="HTML",
                source_table="Image::ExifTool::HTML::Main",
                tag_id="title",
                raw_value=metadata.title.raw_value,
                rendered_value=metadata.title.value,
                element_index=metadata.title.element_index,
                byte_offset=_element_offset(metadata, metadata.title.element_index),
                evidence_ids=(HTML_TITLE_SOURCE,),
            )
        )
    return HtmlReaderPlan(
        status="unsupported" if diagnostics or metadata.status == "blocked" else "planned",
        metadata=metadata,
        tags=tuple(_collapse_html_list_tags(_source_ordered_tags(tags))),
        diagnostics=diagnostics,
        evidence_ids=HTML_TRANSACTION_SOURCES,
    )


_HTML_TABLES: dict[str, tuple[str, str, str]] = {
    "http-equiv": ("HTTP-equiv", "Image::ExifTool::HTML::equiv", "ContentType"),
    "dc": ("HTML-dc", "Image::ExifTool::HTML::dc", ""),
    "ncc": ("HTML-ncc", "Image::ExifTool::HTML::ncc", ""),
    "prod": ("HTML-prod", "Image::ExifTool::HTML::prod", ""),
    "o": ("HTML-office", "Image::ExifTool::HTML::Office", ""),
}

_HTML_DC_NAMES = {
    "contributor": "Contributor",
    "coverage": "Coverage",
    "creator": "Creator",
    "date": "Date",
    "description": "Description",
    "format": "Format",
    "identifier": "Identifier",
    "language": "Language",
    "publisher": "Publisher",
    "relation": "Relation",
    "rights": "Rights",
    "source": "Source",
    "subject": "Subject",
    "title": "Title",
    "type": "Type",
}

_HTML_NCC_NAMES = {
    "charset": "CharacterSet",
    "depth": "Depth",
    "files": "Files",
    "footnotes": "Footnotes",
    "generator": "Generator",
    "kbytesize": "KByteSize",
    "maxpagenormal": "MaxPageNormal",
    "multimediatype": "MultimediaType",
    "narrator": "Narrator",
    "pagefront": "PageFront",
    "pagenormal": "PageNormal",
    "pagespecial": "PageSpecial",
    "prodnotes": "ProdNotes",
    "setinfo": "SetInfo",
    "sidebars": "Sidebars",
    "sourcedate": "SourceDate",
    "sourceedition": "SourceEdition",
    "sourcepublisher": "SourcePublisher",
    "tocitems": "TOCItems",
    "totaltime": "Duration",
}

_HTML_PROD_NAMES = {
    "reclocation": "RecLocation",
    "recengineer": "RecEngineer",
}

_HTML_OFFICE_NAMES = {
    "Author": "Author",
    "Category": "Category",
    "Characters": "Characters",
    "CharactersWithSpaces": "CharactersWithSpaces",
    "Company": "Company",
    "Created": "CreateDate",
    "Description": "Description",
    "Keywords": "Keywords",
    "LastAuthor": "LastAuthor",
    "LastSaved": "ModifyDate",
    "Lines": "Lines",
    "Manager": "Manager",
    "Pages": "Pages",
    "Paragraphs": "Paragraphs",
    "Revision": "RevisionNumber",
    "Subject": "Subject",
    "Template": "Template",
    "TotalTime": "TotalEditTime",
    "Version": "RevisionNumber",
    "Words": "Words",
}

_HTML_INT_TAGS = {
    "Characters",
    "CharactersWithSpaces",
    "Depth",
    "Files",
    "Footnotes",
    "KByteSize",
    "Lines",
    "MaxPageNormal",
    "PageFront",
    "PageNormal",
    "Pages",
    "PageSpecial",
    "Paragraphs",
    "ProdNotes",
    "Sidebars",
    "SourceDate",
    "SourceEdition",
    "TOCItems",
    "Words",
}


def _meta_tag_output(
    group: str | None,
    tag: str,
    value: str,
) -> tuple[str, str, str, HtmlReadScalar]:
    if group == "http-equiv":
        name = "ContentType" if tag == "content-type" else _title_identifier(tag)
        return name, "HTTP-equiv", "Image::ExifTool::HTML::equiv", value
    if group == "dc":
        name = _HTML_DC_NAMES.get(tag, _title_identifier(tag))
        return name, "HTML-dc", "Image::ExifTool::HTML::dc", value
    if group == "ncc":
        name = _HTML_NCC_NAMES.get(tag, _title_identifier(tag))
        return name, "HTML-ncc", "Image::ExifTool::HTML::ncc", _typed_html_value(name, value)
    if group == "prod":
        name = _HTML_PROD_NAMES.get(tag, _title_identifier(tag))
        return name, "HTML-prod", "Image::ExifTool::HTML::prod", value
    if group == "o":
        name = _HTML_OFFICE_NAMES.get(tag, _title_identifier(tag))
        return name, "HTML-office", "Image::ExifTool::HTML::Office", _typed_html_value(name, value)
    return _title_identifier(tag), "HTML", "Image::ExifTool::HTML::Main", value


def _xml_child_output(group: str, tag: str, value: str) -> tuple[str, str, str, HtmlReadScalar]:
    normalized_tag = _office_xml_tag_name(tag) if group == "o" else tag
    return _meta_tag_output(group, normalized_tag, value)


def _office_xml_tag_name(tag: str) -> str:
    name = tag
    name = re.sub(r"_x([0-9a-fA-F]{4})_", lambda match: chr(int(match.group(1), 16)), name)
    name = re.sub(r"\s(.)", lambda match: match.group(1).upper(), name)
    name = re.sub(r"[^-_\w\d]", "", name)
    return name[:1].upper() + name[1:] if name[:1].islower() else name


def _title_identifier(value: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", value)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _typed_html_value(name: str, value: str) -> HtmlReadScalar:
    if name == "TotalEditTime":
        try:
            minutes = int(value)
        except ValueError:
            return value
        return "1 minute" if minutes == 1 else f"{minutes} minutes"
    if name in _HTML_INT_TAGS:
        try:
            return int(value)
        except ValueError:
            return value
    if name == "RevisionNumber":
        try:
            return float(value)
        except ValueError:
            return value
    if name in {"CreateDate", "ModifyDate"}:
        return value.replace("-", ":", 2).replace("T", " ", 1)
    return value


def _source_ordered_tags(tags: list[HtmlReadTag]) -> list[HtmlReadTag]:
    file_tags = [tag for tag in tags if tag.group == "File"]
    content_tags = [tag for tag in tags if tag.group != "File"]
    return [*file_tags, *sorted(content_tags, key=lambda tag: (tag.byte_offset, tag.element_index))]


def _collapse_html_list_tags(tags: list[HtmlReadTag]) -> list[HtmlReadTag]:
    list_keys = {("HTML-dc", "Creator")}
    collapsed: list[HtmlReadTag] = []
    indexes: dict[tuple[str, str], int] = {}
    for tag in tags:
        key = (tag.group, tag.name)
        if key not in list_keys:
            existing_index = indexes.get(key)
            if existing_index is not None:
                collapsed.pop(existing_index)
                indexes = {
                    existing_key: (index if index < existing_index else index - 1)
                    for existing_key, index in indexes.items()
                    if existing_key != key
                }
                indexes[key] = len(collapsed)
                collapsed.append(tag)
                continue
            indexes[key] = len(collapsed)
            collapsed.append(tag)
            continue
        existing_index = indexes.get(key)
        if existing_index is None:
            indexes[key] = len(collapsed)
            collapsed.append(tag)
            continue
        existing = collapsed[existing_index]
        existing_values: HtmlReadArray = (
            existing.rendered_value
            if isinstance(existing.rendered_value, list)
            else [existing.rendered_value]
        )
        collapsed[existing_index] = replace(
            existing,
            rendered_value=[*existing_values, tag.rendered_value],
            raw_value=[*existing_values, tag.rendered_value],
        )
    return collapsed


def _element_offset(metadata: HtmlMetadataTransactionPlan, element_index: int) -> int:
    for element in metadata.elements:
        if element.index == element_index:
            return element.offset
    return 0


plan_html_reader = build_html_reader_plan


install_evidence_reference_compat(globals())
