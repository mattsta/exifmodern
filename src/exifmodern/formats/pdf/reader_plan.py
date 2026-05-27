"""Bounded, source-backed PDF metadata reader plan."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.photoshop.reader import (
    PhotoshopResourceBlock,
    parse_photoshop_iptc_tags,
    parse_photoshop_print_scale_tags,
    parse_photoshop_resolution_tags,
    parse_photoshop_resources,
    parse_photoshop_slice_tags,
    parse_photoshop_tags,
    parse_photoshop_version_tags,
)
from exifmodern.formats.tiff.process_tiff import ProcessTiffTag, process_tiff_payload
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.json_types import JsonObject, JsonValue, json_string_array_or_none

type PdfReaderStatus = Literal["planned", "unsupported"]
type PdfReaderDiagnosticCode = Literal[
    "unsupported_pdf_signature",
    "malformed_pdf_object",
    "unsupported_pdf_indirect_value",
    "unsupported_pdf_stream_filter",
    "malformed_pdf_stream",
]
type PdfScalarValue = str | int | float | bool | None | list[str]

PDF_PM_SOURCE_PATH = "lib/Image/ExifTool/PDF.pm"

PDF_MAIN_SOURCE = "pdf.reader.main"
PDF_INFO_SOURCE = "pdf.reader.info"
PDF_ROOT_SOURCE = "pdf.reader.root"
PDF_PAGES_SOURCE = "pdf.reader.pages"
PDF_DATE_SOURCE = "pdf.reader.date"
PDF_FETCH_SOURCE = "pdf.reader.fetch"
PDF_EXTRACT_SOURCE = "pdf.reader.extract"
PDF_PROCESS_DICT_SOURCE = "pdf.reader.process_dict"
PDF_IMAGE_RESOURCES_SOURCE = "pdf.reader.image_resources"
PDF_METADATA_SOURCE = "pdf.reader.metadata"
PDF_STREAM_SOURCE = "pdf.reader.stream"
PHOTOSHOP_EXIFINFO_SOURCE = "pdf.reader.photoshop_exifinfo"
EXIF_SUBIFD_SOURCE = "pdf.reader.exif_subifd"
EXIF_IFD1_THUMBNAIL_SOURCE = "pdf.reader.exif_ifd1_thumbnail"

PDF_READER_SOURCES = (
    PDF_MAIN_SOURCE,
    PDF_INFO_SOURCE,
    PDF_ROOT_SOURCE,
    PDF_PAGES_SOURCE,
    PDF_DATE_SOURCE,
    PDF_FETCH_SOURCE,
    PDF_EXTRACT_SOURCE,
    PDF_PROCESS_DICT_SOURCE,
    PDF_IMAGE_RESOURCES_SOURCE,
    PDF_METADATA_SOURCE,
    PDF_STREAM_SOURCE,
    PHOTOSHOP_EXIFINFO_SOURCE,
    EXIF_SUBIFD_SOURCE,
    EXIF_IFD1_THUMBNAIL_SOURCE,
)

INFO_TAG_NAMES = {
    "Title": "Title",
    "Author": "Author",
    "Subject": "Subject",
    "Keywords": "Keywords",
    "Creator": "Creator",
    "Producer": "Producer",
    "CreationDate": "CreateDate",
    "ModDate": "ModifyDate",
    "SourceModified": "SourceModified",
    "Trapped": "Trapped",
    "AAPL:Keywords": "AppleKeywords",
}
ROOT_TAG_NAMES = {
    "Lang": "Language",
    "PageLayout": "PageLayout",
    "PageMode": "PageMode",
    "Version": "PDFVersion",
}
_IPTC_TAG_NAMES = {
    "ApplicationRecordVersion",
    "ObjectName",
    "Urgency",
    "Category",
    "SupplementalCategories",
    "Keywords",
    "SpecialInstructions",
    "DateCreated",
    "By-line",
    "By-lineTitle",
    "City",
    "Province-State",
    "Country-PrimaryLocationName",
    "OriginalTransmissionReference",
    "Headline",
    "Credit",
    "Source",
    "CopyrightNotice",
    "Caption-Abstract",
    "Writer-Editor",
}
_EXIF_TAG_IDS = {
    "ImageDescription": "0x010E",
    "Make": "0x010F",
    "Model": "0x0110",
    "Orientation": "0x0112",
    "XResolution": "0x011A",
    "YResolution": "0x011B",
    "ResolutionUnit": "0x0128",
    "Software": "0x0131",
    "ModifyDate": "0x0132",
    "Artist": "0x013B",
    "YCbCrPositioning": "0x0213",
    "Copyright": "0x8298",
    "FNumber": "0x829D",
    "ExposureProgram": "0x8822",
    "ISO": "0x8827",
    "ExifVersion": "0x9000",
    "DateTimeOriginal": "0x9003",
    "CreateDate": "0x9004",
    "ComponentsConfiguration": "0x9101",
    "CompressedBitsPerPixel": "0x9102",
    "ShutterSpeedValue": "0x9201",
    "ApertureValue": "0x9202",
    "BrightnessValue": "0x9203",
    "ExposureCompensation": "0x9204",
    "MaxApertureValue": "0x9205",
    "MeteringMode": "0x9207",
    "Flash": "0x9209",
    "Noise": "0x920D",
    "FlashpixVersion": "0xA000",
    "ColorSpace": "0xA001",
    "ExifImageWidth": "0xA002",
    "ExifImageHeight": "0xA003",
    "FocalPlaneXResolution": "0xA20E",
    "FocalPlaneYResolution": "0xA20F",
    "FocalPlaneResolutionUnit": "0xA210",
    "SensingMethod": "0xA217",
    "FileSource": "0xA300",
    "SceneType": "0xA301",
    "Compression": "0x0103",
    "ThumbnailOffset": "0x0201",
    "ThumbnailLength": "0x0202",
}


@dataclass(frozen=True)
class PdfReaderDiagnostic:
    code: PdfReaderDiagnosticCode
    detail: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PdfReadTag:
    name: str
    group: str
    source_table: str
    tag_id: str
    raw_value: PdfScalarValue
    rendered_value: PdfScalarValue
    object_reference: str | None
    byte_offset: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_offset": self.byte_offset,
            "group": self.group,
            "name": self.name,
            "object_reference": self.object_reference,
            "raw_value": _json_value(self.raw_value),
            "rendered_value": _json_value(self.rendered_value),
            "source_table": self.source_table,
            "tag_id": self.tag_id,
        }


@dataclass(frozen=True)
class PdfObjectBoundary:
    object_reference: str
    byte_offset: int
    byte_length: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_length": self.byte_length,
            "byte_offset": self.byte_offset,
            "object_reference": self.object_reference,
        }


@dataclass(frozen=True)
class PdfReaderPlan:
    status: PdfReaderStatus
    pdf_version: str | None
    object_boundaries: tuple[PdfObjectBoundary, ...]
    tags: tuple[PdfReadTag, ...]
    diagnostics: tuple[PdfReaderDiagnostic, ...]
    evidence_ids: tuple[str, ...]

    def tags_by_name(self) -> dict[str, tuple[PdfReadTag, ...]]:
        names = {tag.name for tag in self.tags}
        return {name: tuple(tag for tag in self.tags if tag.name == name) for name in names}

    def to_json(self) -> JsonObject:
        return {
            "diagnostics": [diagnostic.to_json() for diagnostic in self.diagnostics],
            "object_boundaries": [boundary.to_json() for boundary in self.object_boundaries],
            "pdf_version": self.pdf_version,
            "status": self.status,
            "tags": [tag.to_json() for tag in self.tags],
        }


@dataclass(frozen=True)
class _PdfObject:
    reference: str
    offset: int
    body: str
    length: int


def build_pdf_reader_plan(pdf_data: bytes) -> PdfReaderPlan:
    text = pdf_data.decode("latin-1", errors="replace")
    version_match = re.match(r"%PDF-(\d+\.\d+)", text)
    diagnostics: list[PdfReaderDiagnostic] = []
    if version_match is None:
        diagnostics.append(
            PdfReaderDiagnostic(
                "unsupported_pdf_signature",
                "PDF data must begin with a %PDF-version header.",
                (PDF_MAIN_SOURCE,),
            )
        )
        return PdfReaderPlan("unsupported", None, (), (), tuple(diagnostics), PDF_READER_SOURCES)

    objects = _objects(text)
    object_by_ref = {obj.reference: obj for obj in objects}
    boundaries = tuple(
        PdfObjectBoundary(obj.reference, obj.offset, obj.length, (PDF_FETCH_SOURCE,))
        for obj in objects
    )
    tags: list[PdfReadTag] = [
        PdfReadTag(
            name="PDFVersion",
            group="PDF",
            source_table="Image::ExifTool::PDF::Root",
            tag_id="Version",
            raw_value=version_match.group(1),
            rendered_value=version_match.group(1),
            object_reference=None,
            byte_offset=0,
            evidence_ids=(PDF_ROOT_SOURCE,),
        )
    ]
    tags.append(_linearized_tag(objects))

    trailer = _last_trailer(text)
    if not trailer:
        trailer = _last_xref_stream_dictionary(objects)
    info_ref = _ref_for_key(trailer, "Info")
    root_ref = _ref_for_key(trailer, "Root")
    if info_ref is not None and info_ref in object_by_ref:
        tags.extend(
            _dictionary_tags(object_by_ref[info_ref], INFO_TAG_NAMES, "Info", object_by_ref)
        )
    if root_ref is not None and root_ref in object_by_ref:
        root = object_by_ref[root_ref]
        tags.extend(_dictionary_tags(root, ROOT_TAG_NAMES, "Root", object_by_ref))
        pages_ref = _ref_for_key(root.body, "Pages")
        if pages_ref is not None and pages_ref in object_by_ref:
            count = _name_value(object_by_ref[pages_ref].body, "Count")
            if count is not None and count.isdecimal():
                tags.append(
                    PdfReadTag(
                        name="PageCount",
                        group="PDF",
                        source_table="Image::ExifTool::PDF::Pages",
                        tag_id="Count",
                        raw_value=int(count),
                        rendered_value=int(count),
                        object_reference=pages_ref,
                        byte_offset=object_by_ref[pages_ref].offset,
                        evidence_ids=(PDF_PAGES_SOURCE, PDF_PROCESS_DICT_SOURCE),
                    )
                )
    nested_tags, nested_diagnostics = _nested_stream_tags(objects)
    tags.extend(nested_tags)
    diagnostics.extend(nested_diagnostics)
    return PdfReaderPlan(
        "unsupported" if diagnostics else "planned",
        version_match.group(1),
        boundaries,
        tuple(tags),
        tuple(diagnostics),
        PDF_READER_SOURCES,
    )


def _nested_stream_tags(
    objects: tuple[_PdfObject, ...],
) -> tuple[tuple[PdfReadTag, ...], tuple[PdfReaderDiagnostic, ...]]:
    tags: list[PdfReadTag] = []
    diagnostics: list[PdfReaderDiagnostic] = []
    for obj in objects:
        payload, diagnostic = _object_stream_payload(obj)
        if diagnostic is not None:
            if _is_metadata_stream_object(obj):
                diagnostics.append(diagnostic)
            continue
        if payload is None:
            continue
        if _is_xmp_stream(obj, payload):
            tags.extend(_xmp_stream_tags(obj, payload))
        elif payload.startswith(b"8BIM") or payload.startswith(b"8B64"):
            stream_tags, stream_diagnostics = _photoshop_stream_tags(obj, payload)
            tags.extend(stream_tags)
            diagnostics.extend(stream_diagnostics)
    return tuple(tags), tuple(diagnostics)


def _is_metadata_stream_object(obj: _PdfObject) -> bool:
    return (
        "/Subtype /XML" in obj.body
        or "/ImageResources" in obj.body
        or "/AdobePhotoshop" in obj.body
    )


def _object_stream_payload(
    obj: _PdfObject,
) -> tuple[bytes | None, PdfReaderDiagnostic | None]:
    stream_match = re.search(
        r"\bstream(?:\r\n|\r|\n)(.*?)(?:\r\n|\r|\n)?endstream\b",
        obj.body,
        re.DOTALL,
    )
    if stream_match is None:
        return None, None
    payload = stream_match.group(1).encode("latin-1", errors="replace")
    filters = tuple(re.findall(r"/Filter\s+(/[A-Za-z0-9]+)", obj.body))
    if not filters:
        return payload, None
    if filters == ("/FlateDecode",):
        try:
            return zlib.decompress(payload), None
        except zlib.error as error:
            return None, PdfReaderDiagnostic(
                "malformed_pdf_stream",
                f"FlateDecode stream could not be inflated for object {obj.reference}: {error}",
                (PDF_STREAM_SOURCE,),
            )
    return None, PdfReaderDiagnostic(
        "unsupported_pdf_stream_filter",
        f"Object {obj.reference} uses unsupported stream filters: {', '.join(filters)}",
        (PDF_STREAM_SOURCE,),
    )


def _is_xmp_stream(obj: _PdfObject, payload: bytes) -> bool:
    if "/Subtype /XML" in obj.body:
        return True
    return b"<x:xapmeta" in payload or b"<rdf:RDF" in payload


def _xmp_stream_tags(obj: _PdfObject, payload: bytes) -> tuple[PdfReadTag, ...]:
    tags: list[PdfReadTag] = []
    for group, values in parse_xmp_packet(payload).items():
        for name, value in values.items():
            scalar = _json_scalar_or_string_list(value)
            if scalar is None:
                continue
            tags.append(
                _nested_tag(
                    name=name,
                    group=group,
                    source_table=_xmp_table_name(group),
                    tag_id=name,
                    value=scalar,
                    object_reference=obj.reference,
                    byte_offset=obj.offset,
                    evidence_ids=(PDF_METADATA_SOURCE, PDF_STREAM_SOURCE),
                )
            )
    return tuple(tags)


def _photoshop_stream_tags(
    obj: _PdfObject,
    payload: bytes,
) -> tuple[tuple[PdfReadTag, ...], tuple[PdfReaderDiagnostic, ...]]:
    diagnostics: list[PdfReaderDiagnostic] = []
    try:
        resources = parse_photoshop_resources(payload)
    except ValueError as error:
        return (), (
            PdfReaderDiagnostic(
                "malformed_pdf_stream",
                f"Photoshop ImageResources stream could not be parsed: {error}",
                (PDF_IMAGE_RESOURCES_SOURCE, PDF_STREAM_SOURCE),
            ),
        )
    tags: list[PdfReadTag] = []
    values = _photoshop_stream_values(payload)
    for name, value in values.items():
        scalar = _json_scalar_or_string_list(value)
        if scalar is None:
            continue
        group = "IPTC" if name in _IPTC_TAG_NAMES else "Photoshop"
        tags.append(
            _nested_tag(
                name=name,
                group=group,
                source_table=(
                    "Image::ExifTool::IPTC::ApplicationRecord"
                    if group == "IPTC"
                    else "Image::ExifTool::Photoshop::Main"
                ),
                tag_id=_photoshop_tag_id(name),
                value=scalar,
                object_reference=obj.reference,
                byte_offset=obj.offset,
                evidence_ids=(PDF_IMAGE_RESOURCES_SOURCE, PDF_STREAM_SOURCE),
            )
        )
    exif_tags, exif_diagnostics = _photoshop_exif_resource_tags(obj, resources)
    tags.extend(exif_tags)
    diagnostics.extend(exif_diagnostics)
    return tuple(tags), tuple(diagnostics)


def _photoshop_stream_values(payload: bytes) -> JsonObject:
    values: JsonObject = {}
    values.update(parse_photoshop_tags(payload))
    values.update(parse_photoshop_resolution_tags(payload))
    values.update(parse_photoshop_print_scale_tags(payload))
    values.update(parse_photoshop_slice_tags(payload))
    values.update(parse_photoshop_version_tags(payload))
    values.update(parse_photoshop_iptc_tags(payload))
    return values


def _photoshop_exif_resource_tags(
    obj: _PdfObject,
    resources: list[PhotoshopResourceBlock],
) -> tuple[tuple[PdfReadTag, ...], tuple[PdfReaderDiagnostic, ...]]:
    tags: list[PdfReadTag] = []
    diagnostics: list[PdfReaderDiagnostic] = []
    for resource in resources:
        if resource.resource_id != 0x0422:
            continue
        result = process_tiff_payload(
            resource.data,
            (PDF_IMAGE_RESOURCES_SOURCE, PDF_STREAM_SOURCE, PHOTOSHOP_EXIFINFO_SOURCE),
        )
        tags.extend(_embedded_tiff_tags(obj, result.tags))
        for diagnostic in result.diagnostics:
            diagnostics.append(
                PdfReaderDiagnostic(
                    "malformed_pdf_stream",
                    diagnostic.detail,
                    diagnostic.evidence_ids,
                )
            )
    return tuple(tags), tuple(diagnostics)


def _embedded_tiff_tags(
    obj: _PdfObject,
    tiff_tags: tuple[ProcessTiffTag, ...],
) -> tuple[PdfReadTag, ...]:
    tags: list[PdfReadTag] = []
    for tag in tiff_tags:
        tags.append(
            _nested_tag(
                name=tag.name,
                group=tag.group,
                source_table=tag.source_table,
                tag_id=_EXIF_TAG_IDS.get(tag.name, tag.tag_id),
                value=tag.value,
                object_reference=obj.reference,
                byte_offset=obj.offset,
                evidence_ids=tag.evidence_ids,
            )
        )
    return tuple(tags)


def _nested_tag(
    *,
    name: str,
    group: str,
    source_table: str,
    tag_id: str,
    value: PdfScalarValue,
    object_reference: str,
    byte_offset: int,
    evidence_ids: tuple[str, ...],
) -> PdfReadTag:
    return PdfReadTag(
        name=name,
        group=group,
        source_table=source_table,
        tag_id=tag_id,
        raw_value=value,
        rendered_value=value,
        object_reference=object_reference,
        byte_offset=byte_offset,
        evidence_ids=evidence_ids,
    )


def _objects(text: str) -> tuple[_PdfObject, ...]:
    matches = tuple(
        re.finditer(
            r"(?m)(?:^|[\r\n])(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj\b",
            text,
            re.DOTALL,
        )
    )
    return tuple(
        _PdfObject(
            reference=f"{match.group(1)} {match.group(2)} R",
            offset=match.start(1),
            body=match.group(3),
            length=match.end() - match.start(1),
        )
        for match in matches
    )


def _last_trailer(text: str) -> str:
    matches = tuple(re.finditer(r"\btrailer\b", text))
    for match in reversed(matches):
        body = _dictionary_body_at(text, match.end())
        if body is not None:
            return body
    return ""


def _last_xref_stream_dictionary(objects: tuple[_PdfObject, ...]) -> str:
    for obj in reversed(objects):
        if re.search(r"/Type(?:\s+|(?=/))/XRef\b", obj.body):
            body = _dictionary_body_at(obj.body, 0)
            if body is not None:
                return body
    return ""


def _dictionary_body_at(text: str, start: int) -> str | None:
    open_at = text.find("<<", start)
    if open_at < 0:
        return None
    depth = 1
    index = open_at + 2
    literal_depth = 0
    while index < len(text) - 1:
        char = text[index]
        if literal_depth:
            if char == "\\":
                index += 2
                continue
            if char == "(":
                literal_depth += 1
            elif char == ")":
                literal_depth -= 1
            index += 1
            continue
        if char == "(":
            literal_depth = 1
            index += 1
            continue
        if text.startswith("<<", index):
            depth += 1
            index += 2
            continue
        if text.startswith(">>", index):
            depth -= 1
            if depth == 0:
                return text[open_at + 2 : index]
            index += 2
            continue
        index += 1
    return None


def _ref_for_key(dictionary_text: str, key: str) -> str | None:
    match = re.search(
        rf"/{re.escape(key)}(?:\s+|(?=\d))(\d+)\s+(\d+)\s+R\b",
        dictionary_text,
    )
    if match is None:
        return None
    return f"{match.group(1)} {match.group(2)} R"


def _name_value(dictionary_text: str, key: str) -> str | None:
    match = re.search(
        rf"/{re.escape(key)}(?:\s+|(?=[(/\[<+-]|\d))"
        rf"(\((?:\\.|[^\\)])*\)|"
        rf"<[0-9A-Fa-f\s]+>|"
        rf"/[^\s<>\[\]()/%]+|"
        rf"\d+\s+\d+\s+R\b|"
        rf"[-+]?\d+(?:\.\d+)?|"
        rf"true|false|null)",
        dictionary_text,
        re.DOTALL,
    )
    if match is None:
        return None
    value = match.group(1)
    if value.startswith("(") and value.endswith(")"):
        return _pdf_string(value[1:-1])
    if value.startswith("<") and value.endswith(">"):
        return _pdf_hex_string(value[1:-1])
    if value.startswith("/"):
        return value[1:]
    return value


def _dictionary_tags(
    obj: _PdfObject,
    tag_names: dict[str, str],
    table: Literal["Info", "Root"],
    object_by_ref: dict[str, _PdfObject],
) -> tuple[PdfReadTag, ...]:
    tags: list[PdfReadTag] = []
    for tag_id, name in tag_names.items():
        value = _name_value(obj.body, tag_id)
        if value is None:
            continue
        tag_object_reference = obj.reference
        tag_byte_offset = obj.offset
        if _is_object_reference(value):
            value_obj = object_by_ref.get(value)
            if value_obj is None:
                continue
            indirect_value = _direct_object_value(value_obj.body)
            if indirect_value is None:
                continue
            value = indirect_value
            tag_object_reference = value_obj.reference
            tag_byte_offset = value_obj.offset
        source = PDF_INFO_SOURCE if table == "Info" else PDF_ROOT_SOURCE
        group = "PDF"
        evidence_ids: tuple[str, ...] = (source, PDF_PROCESS_DICT_SOURCE)
        if name.endswith("Date") and isinstance(value, str):
            value = _convert_pdf_date(value)
            evidence_ids = (source, PDF_DATE_SOURCE, PDF_PROCESS_DICT_SOURCE)
        tags.append(
            PdfReadTag(
                name=name,
                group=group,
                source_table=f"Image::ExifTool::PDF::{table}",
                tag_id=tag_id,
                raw_value=value,
                rendered_value=value,
                object_reference=tag_object_reference,
                byte_offset=tag_byte_offset,
                evidence_ids=evidence_ids,
            )
        )
    return tuple(tags)


def _linearized_tag(objects: tuple[_PdfObject, ...]) -> PdfReadTag:
    raw_value = "false"
    rendered_value = "No"
    if objects:
        value = _name_value(objects[0].body, "Linearized")
        if value is not None:
            raw_value = "true"
            rendered_value = "Yes"
    return PdfReadTag(
        name="Linearized",
        group="PDF",
        source_table="Image::ExifTool::PDF::Main",
        tag_id="_linearized",
        raw_value=raw_value,
        rendered_value=rendered_value,
        object_reference=objects[0].reference if objects else None,
        byte_offset=objects[0].offset if objects else 0,
        evidence_ids=(PDF_MAIN_SOURCE, PDF_PROCESS_DICT_SOURCE),
    )


def _pdf_string(value: str) -> str:
    return (
        value.replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\\", "\\")
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
    )


def _pdf_hex_string(value: str) -> str:
    hex_digits = re.sub(r"\s+", "", value)
    if len(hex_digits) % 2:
        hex_digits += "0"
    try:
        return bytes.fromhex(hex_digits).decode("latin-1")
    except ValueError:
        return value


def _is_object_reference(value: str) -> bool:
    return re.fullmatch(r"\d+\s+\d+\s+R", value) is not None


def _direct_object_value(object_body: str) -> str | None:
    body = re.sub(r"\bstream\b.*", "", object_body, flags=re.DOTALL).strip()
    if body.startswith("("):
        match = re.match(r"(\((?:\\.|[^\\)])*\))", body, flags=re.DOTALL)
        if match is None:
            return None
        return _pdf_string(match.group(1)[1:-1])
    if body.startswith("<") and not body.startswith("<<"):
        match = re.match(r"(<[0-9A-Fa-f\s]+>)", body, flags=re.DOTALL)
        if match is None:
            return None
        return _pdf_hex_string(match.group(1)[1:-1])
    if body.startswith("/"):
        match = re.match(r"/([^\s<>\[\]()/%]+)", body)
        if match is None:
            return None
        return match.group(1)
    match = re.match(r"([-+]?\d+(?:\.\d+)?|true|false|null)\b", body)
    if match is None:
        return None
    return match.group(1)


def _convert_pdf_date(value: str) -> str:
    date = value.removeprefix("D:")
    default = "00000101000000"
    if len(date) < len(default):
        date += default[len(date) :]
    match = re.match(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(.*)", date)
    if match is None:
        return date
    converted = (
        f"{match.group(1)}:{match.group(2)}:{match.group(3)} "
        f"{match.group(4)}:{match.group(5)}:{match.group(6)}"
    )
    timezone = match.group(7)
    if timezone:
        if re.match(r"\s*Z", timezone, flags=re.IGNORECASE):
            converted += "Z"
        else:
            timezone_match = re.match(r"\s*([-+])\s*(\d+)[': ]+(\d*)", timezone)
            if timezone_match is not None:
                converted += (
                    f"{timezone_match.group(1)}{timezone_match.group(2)}:"
                    f"{timezone_match.group(3) or '00'}"
                )
    return converted


def _json_value(value: PdfScalarValue) -> JsonValue:
    if isinstance(value, list):
        return [item for item in value]
    return value


def _json_scalar_or_string_list(value: JsonValue) -> PdfScalarValue | None:
    if isinstance(value, dict):
        return None
    if isinstance(value, list):
        return json_string_array_or_none(value)
    return value


def _xmp_table_name(group: str) -> str:
    if group.startswith("XMP-"):
        return f"Image::ExifTool::XMP::{group[4:]}"
    return "Image::ExifTool::XMP::Main"


def _photoshop_tag_id(name: str) -> str:
    return {
        "XResolution": "0",
        "DisplayedUnitsX": "2",
        "YResolution": "4",
        "DisplayedUnitsY": "6",
        "PrintStyle": "0",
        "PrintPosition": "2",
        "PrintScale": "10",
        "GlobalAngle": "0x040d",
        "GlobalAltitude": "0x0419",
        "CopyrightFlag": "0x040a",
        "URL": "0x040b",
        "URL_List": "0x041e",
        "SlicesGroupName": "20",
        "NumSlices": "24",
        "HasRealMergedData": "4",
        "WriterName": "5",
        "ReaderName": "9",
    }.get(name, name)


plan_pdf_reader = build_pdf_reader_plan


install_evidence_reference_compat(globals())
