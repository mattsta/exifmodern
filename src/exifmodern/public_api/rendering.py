"""Package-local public read rendering helpers."""

from __future__ import annotations

import json
import re
from base64 import b64encode
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, TypeGuard

from exifmodern.formats.public_payload import read_public_document_payload
from exifmodern.json_types import JsonArray, JsonObject, JsonValue
from exifmodern.package_resources import charset_language_package_path
from exifmodern.read_graph import BinaryTagListValue, BinaryTagValue, TagValue
from exifmodern.renderer import JsonRecord

_EXIFTOOL_JSON_NUMBER_RE = re.compile(
    r"^-?(\d|[1-9]\d{1,14})(\.\d{1,16})?(e[-+]?\d{1,3})?$",
    re.IGNORECASE,
)
_EXIFTOOL_DEFAULT_TEXT_LABELS: dict[str, str] = {
    # Source: ../exiftool/lib/Image/ExifTool.pm GetDescription uses explicit
    # Description fields for default output before falling back to MakeDescription.
    "ExifToolVersion": "ExifTool Version Number",
    "FileAccessDate": "File Access Date/Time",
    "FileCreateDate": "File Creation Date/Time",
    "FileInodeChangeDate": "File Inode Change Date/Time",
    "FileModifyDate": "File Modification Date/Time",
    "FOV": "Field Of View",
    "FocalLength35efl": "Focal Length 35mm Equiv",
    "InteropIndex": "Interoperability Index",
    "InteropVersion": "Interoperability Version",
    "Model": "Camera Model Name",
    "Now": "Now",
    # Source: ../exiftool/lib/Image/ExifTool/Exif.pm Composite and EXIF tag
    # tables define these descriptions for public default text output.
    "DateTimeOriginal": "Date/Time Original",
    "ScaleFactor35efl": "Scale Factor To 35 mm Equivalent",
}
_ZERO_SUBSECOND_COMPOSITE_TAGS = frozenset(
    {
        "SubSecModifyDate",
        "SubSecCreateDate",
        "SubSecDateTimeOriginal",
    }
)


class _PhpBinaryString(str):
    """Internal marker for -php -b payloads that keep trailing NUL bytes."""


class _BinaryTagValueLike(Protocol):
    @property
    def byte_count(self) -> int: ...


@dataclass(frozen=True, slots=True)
class _TextRenderState:
    use_short_label: bool
    use_latin_label: bool
    use_translated_description_labels: bool
    use_missing_tag_description_labels: bool
    translate_descriptions: bool
    list_separator: str


if TYPE_CHECKING:
    from exifmodern.formats.xmp.reader import (
        XmpSourceStructElement,
        XmpSourceStructField,
        XmpSourceStructListItem,
    )
    from exifmodern.public_api.models import (
        MetadataReadRecord,
        MetadataReadRequest,
        OutputRenderRequest,
        XmlStructField,
        XmlStructListItem,
        XmlTagElement,
    )
    from exifmodern.services.charset_language_runtime import CharsetLanguageRuntimeService


def render_records_json(
    records: list[MetadataReadRecord],
    request: OutputRenderRequest,
) -> bytes:
    if len(records) == 1:
        return _render_exiftool_json_record(_json_output_record_for_render(records[0], request))
    lines = ["["]
    for index, record in enumerate(records):
        lines.append("{")
        body = _render_exiftool_json_record_body(_json_output_record_for_render(record, request))
        if body:
            lines.extend(body)
        if index < len(records) - 1:
            lines.append("},")
        else:
            lines.append("}")
    lines.append("]")
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_records_php(
    records: list[MetadataReadRecord],
    request: OutputRenderRequest,
) -> str:
    rendered_records = [
        _render_php_array(_php_output_record_for_render(record, request), indent="  ")
        for record in records
    ]
    if not rendered_records:
        return "Array();\n"
    return rendered_text_for_charset("Array(" + ",\n".join(rendered_records) + ");\n", request)


def render_records_html(
    records: list[MetadataReadRecord],
    request: OutputRenderRequest,
) -> str:
    parts: list[str] = []
    for record in records:
        source_file = escape(record.path.as_posix(), quote=True)
        element_metadata = _html_element_metadata_by_key(record, request)
        parts.append(f"<!-- {source_file} -->\n")
        parts.append("<table>\n")
        for key, value in _record_values_for_missing_group_family_render(
            _record_values_for_structured_scalar_render(record, request),
            request,
        ).items():
            if key == "SourceFile":
                continue
            group, name = _html_group_and_name(key)
            parts.append("<tr>")
            # Source: ../exiftool/exiftool lines 3010-3015 include the group
            # cell only when group output is active.
            if request.include_group_names:
                parts.append(f"<td>{escape(group, quote=True)}</td>")
            metadata = element_metadata.get(key) or element_metadata.get(name)
            if request.xml_tag_id_format != "none":
                tag_id = "" if metadata is None or metadata.et_id is None else metadata.et_id
                parts.append(f"<td>{escape(_formatted_tag_id(tag_id, request), quote=True)}</td>")
            parts.append(f"<td>{escape(name, quote=True)}</td>")
            rendered_value = html_text_value(value, list_separator=request.list_separator)
            parts.append(f"<td>{escape(rendered_value, quote=True)}</td>")
            parts.append("</tr>\n")
        parts.append("</table>\n")
    return rendered_text_for_charset("".join(parts), request)


def json_record_for_render(record: JsonRecord, request: OutputRenderRequest) -> JsonRecord:
    if not request.join_list_values:
        return record
    return {
        key: text_value(value, list_separator=request.list_separator)
        if isinstance(value, list)
        else value
        for key, value in record.items()
    }


def _json_output_record_for_render(
    record: MetadataReadRecord,
    request: OutputRenderRequest,
) -> JsonObject:
    if request.structured_output and record.xml_elements:
        return _structured_json_output_record_for_render(record, request)
    return {
        key: _json_value_for_tag_value(value, request)
        for key, value in json_record_for_render(
            _record_values_for_missing_group_family_render(record.values, request),
            request,
        ).items()
    }


def _structured_json_output_record_for_render(
    record: MetadataReadRecord,
    request: OutputRenderRequest,
) -> JsonObject:
    # Source: ../exiftool/exiftool lines 5960-5972 document that -struct
    # preserves XMP structures for JSON output instead of flattening all fields.
    output: JsonObject = {
        "SourceFile": _json_value_for_tag_value(record.values["SourceFile"], request)
    }
    for element in record.xml_elements:
        output[_json_element_key(element, request)] = _json_output_value_for_xml_element(
            element,
            request,
        )
    return output


def _json_output_value_for_xml_element(
    element: XmlTagElement,
    request: OutputRenderRequest,
) -> JsonValue:
    value = _json_value_for_xml_element(element, request)
    if request.xml_tag_id_format == "none" and not request.xml_include_table_metadata:
        return value
    wrapped: JsonObject = {"val": value}
    if request.xml_tag_id_format != "none" and element.et_id is not None:
        wrapped["id"] = _formatted_tag_id(element.et_id, request)
    if request.xml_include_table_metadata and element.et_table is not None:
        wrapped["table"] = element.et_table
    return wrapped


def _php_output_record_for_render(
    record: MetadataReadRecord,
    request: OutputRenderRequest,
) -> JsonObject:
    # Source: ../exiftool/exiftool lines 2945-2987 route JSON and PHP through
    # the same structured value formatter, with only delimiters differing.
    if request.structured_output and record.xml_elements:
        return _structured_json_output_record_for_render(record, request)
    return {
        key: _json_value_for_tag_value(value, request)
        for key, value in json_record_for_render(
            _record_values_for_missing_group_family_render(record.values, request),
            request,
        ).items()
    }


def _json_value_for_xml_element(
    element: XmlTagElement,
    request: OutputRenderRequest,
) -> JsonValue:
    if element.struct_list_items:
        return [
            _json_object_for_xml_struct_list_item(item, request)
            for item in element.struct_list_items
        ]
    if element.struct_fields:
        return _json_object_for_xml_struct_fields(element.struct_fields, request)
    return _json_value_for_tag_value(element.value, request)


def _json_object_for_xml_struct_list_item(
    item: XmlStructListItem,
    request: OutputRenderRequest,
) -> JsonObject:
    return _json_object_for_xml_struct_fields(item.fields, request)


def _json_object_for_xml_struct_fields(
    fields: tuple[XmlStructField, ...],
    request: OutputRenderRequest,
) -> JsonObject:
    output: JsonObject = {}
    for field in fields:
        key = _json_struct_field_key(field, request)
        if field.struct_fields:
            output[key] = _json_object_for_xml_struct_fields(field.struct_fields, request)
        else:
            output[key] = _json_value_for_tag_value(field.value, request)
    return output


def _json_element_key(element: XmlTagElement, request: OutputRenderRequest) -> str:
    if request.include_group_names:
        return f"{element.group}:{element.tag}"
    return element.tag


def _json_struct_field_key(field: XmlStructField, request: OutputRenderRequest) -> str:
    if request.include_group_names:
        return f"{field.group}:{field.tag}"
    return field.tag


def _json_value_for_tag_value(
    value: TagValue,
    request: OutputRenderRequest,
) -> JsonValue:
    if isinstance(value, BinaryTagListValue):
        if request.join_list_values:
            return text_value(value, list_separator=request.list_separator)
        return [_json_binary_value_for_tag_value(item, request) for item in value.items]
    if isinstance(value, BinaryTagValue):
        return _json_binary_value_for_tag_value(value, request)
    if isinstance(value, list):
        if request.join_list_values:
            return text_value(value, list_separator=request.list_separator)
        json_items: JsonArray = [_json_value_for_scalar_tag_value(item, request) for item in value]
        return json_items
    return _json_value_for_scalar_tag_value(value, request)


def _json_binary_value_for_tag_value(
    value: BinaryTagValue,
    request: OutputRenderRequest,
) -> str:
    if not request.binary_output:
        return text_value(value, list_separator=request.list_separator)
    if request.format == "json":
        decoded = _json_binary_output_text(value.data)
        if decoded is not None:
            return decoded
        return "base64:" + b64encode(value.data).decode("ascii")
    if request.format == "php":
        return _PhpBinaryString(value.data.decode("latin-1"))
    return text_value(value, list_separator=request.list_separator)


def _json_binary_output_text(data: bytes) -> str | None:
    if any(byte < 0x20 and byte not in {0x09, 0x0A, 0x0D} for byte in data):
        return None
    if any(byte == 0x7F or byte > 0xF7 for byte in data):
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _json_value_for_scalar_tag_value(
    value: str | int | float | bool | None,
    request: OutputRenderRequest,
) -> JsonValue:
    if isinstance(value, str) and request.join_list_values:
        return text_value(value, list_separator=request.list_separator)
    return value


def _formatted_tag_id(tag_id: str, request: OutputRenderRequest) -> str:
    if request.xml_tag_id_format == "hex" and tag_id.isdecimal():
        return f"0x{int(tag_id):04x}"
    return tag_id


def render_records_csv(
    records: list[MetadataReadRecord],
    request: MetadataReadRequest,
) -> str:
    delimiter = request.render.csv_delimiter
    headers = csv_headers(records, request)
    lines = [
        delimiter.join(
            csv_cell(csv_header_label(header), delimiter) for header in ("SourceFile", *headers)
        ),
    ]
    for record in records:
        record_values = _record_values_for_missing_group_family_render(
            _record_values_for_structured_scalar_render(record, request.render),
            request.render,
        )
        values = [
            csv_cell(
                record_values.get("SourceFile"),
                delimiter,
                request.render.list_separator,
            )
        ]
        values.extend(
            csv_cell(
                record_values.get(header),
                delimiter,
                request.render.list_separator,
                binary_output=request.render.binary_output,
            )
            for header in headers
        )
        lines.append(delimiter.join(values))
    return rendered_text_for_charset("\n".join(lines) + "\n", request.render)


def csv_header_label(header: str) -> str:
    # ExifTool family-4 CSV output omits the empty primary duplicate group in
    # column labels, while JSON keeps the explicit ":Tag" key.
    return header.removeprefix(":")


def csv_headers(
    records: list[MetadataReadRecord],
    request: MetadataReadRequest,
) -> tuple[str, ...]:
    record_headers = tuple(
        tuple(
            key
            for key in _record_values_for_missing_group_family_render(
                _record_values_for_structured_scalar_render(record, request.render),
                request.render,
            )
            if key != "SourceFile"
        )
        for record in records
    )
    if not record_headers:
        return ()
    unique_headers = {header for headers in record_headers for header in headers}
    requested_headers = _csv_requested_header_order(request.tags, unique_headers)
    if requested_headers is not None:
        return requested_headers
    if len(request.tags) > 1:
        return _csv_sorted_headers(unique_headers)
    first_headers = record_headers[0]
    if all(headers == first_headers for headers in record_headers):
        return first_headers
    return _csv_sorted_headers(unique_headers)


def _csv_sorted_headers(unique_headers: set[str]) -> tuple[str, ...]:
    # Source: ../exiftool/exiftool lines 3907-3910 sort CSV headings by the
    # lower-case lookup keys used while accumulating %csvTags.
    return tuple(sorted(unique_headers, key=lambda header: (header.casefold(), header)))


def _csv_requested_header_order(
    requested_tags: tuple[str, ...],
    unique_headers: set[str],
) -> tuple[str, ...] | None:
    if not requested_tags:
        return None
    ordered_headers: list[str] = []
    for requested_tag in requested_tags:
        matched_headers = _csv_requested_header_matches(requested_tag, unique_headers)
        if not matched_headers:
            continue
        for matched_header in matched_headers:
            if matched_header not in ordered_headers:
                ordered_headers.append(matched_header)
    if len(ordered_headers) == len(unique_headers):
        return tuple(ordered_headers)
    return None


def _csv_requested_header_matches(requested_tag: str, unique_headers: set[str]) -> tuple[str, ...]:
    if requested_tag in unique_headers:
        return (requested_tag,)
    suffix = f":{requested_tag}"
    suffix_matches = tuple(header for header in unique_headers if header.endswith(suffix))
    if len(suffix_matches) == 1:
        return suffix_matches
    if suffix_matches and all(
        _is_csv_duplicate_instance_header(header, requested_tag) for header in suffix_matches
    ):
        # Source: ../exiftool/exiftool lines 2831-2852 accumulate CSV headings
        # from extracted tag order, while family-4 duplicate labels are CopyN
        # instance groups. If a single requested tag expands only to these
        # duplicate columns, preserve Copy0/Copy1/... order instead of falling
        # back to global heading sort.
        return tuple(sorted(suffix_matches, key=_csv_duplicate_instance_header_order))
    return ()


def _is_csv_duplicate_instance_header(header: str, requested_tag: str) -> bool:
    group, separator, tag = header.rpartition(":")
    if separator == "" or tag.casefold() != requested_tag.casefold():
        return False
    if group == "":
        return True
    if group.casefold() == "copy0":
        return True
    if not group.casefold().startswith("copy"):
        return False
    return group[4:].isdecimal()


def _csv_duplicate_instance_header_order(header: str) -> tuple[int, str]:
    group, _, _ = header.rpartition(":")
    if group == "" or group.casefold() == "copy0":
        return (0, header)
    return (int(group[4:]), header)


def csv_cell(
    value: TagValue,
    delimiter: str,
    list_separator: str = ", ",
    *,
    binary_output: bool = False,
) -> str:
    rendered = _csv_text_value(
        value,
        list_separator=list_separator,
        binary_output=binary_output,
    )
    if (
        '"' in rendered
        or delimiter in rendered
        or "\n" in rendered
        or "\r" in rendered
        or rendered != rendered.strip()
    ):
        escaped = rendered.replace('"', '""')
        return f'"{escaped}"'
    return rendered


def _csv_text_value(
    value: TagValue,
    *,
    list_separator: str,
    binary_output: bool,
) -> str:
    if isinstance(value, BinaryTagListValue):
        return list_separator.join(
            _csv_text_value(item, list_separator=list_separator, binary_output=binary_output)
            for item in value.items
        )
    if isinstance(value, BinaryTagValue):
        if binary_output:
            return _csv_binary_output_text(value.data)
        return text_value(value, list_separator=list_separator)
    if isinstance(value, list):
        return list_separator.join(
            _csv_text_value(
                item,
                list_separator=list_separator,
                binary_output=binary_output,
            )
            for item in value
        )
    if value is None:
        return ""
    return str(value)


def _csv_binary_output_text(data: bytes) -> str:
    # Source: ../exiftool/exiftool lines 1542-1556 and 3881-3895 keep -csv -b
    # in CSV text output and base64-encode values when CSV charset checks find
    # bytes outside tab/LF/CR/space-through-0xff.
    if any(byte not in {0x09, 0x0A, 0x0D} and not 0x20 <= byte <= 0xFF for byte in data):
        return "base64:" + b64encode(data).decode("ascii")
    return data.decode("latin-1")


def render_record_output(record: JsonRecord, request: OutputRenderRequest) -> str:
    record = _record_values_for_missing_group_family_render(record, request)
    if request.format == "tab":
        return rendered_text_for_charset(_render_record_tab(record, request), request)
    if request.format in ("csv", "xml", "html", "php", "html_dump"):
        return ""
    return rendered_text_for_charset(_render_record_text(record, request), request)


def _record_values_for_missing_group_family_render(
    record: JsonRecord,
    request: OutputRenderRequest,
) -> JsonRecord:
    if request.missing_tag_value is None or 4 not in request.group_name_families:
        return record

    rendered: JsonRecord = {}
    for key, value in record.items():
        rendered[_key_for_missing_group_family_render(key, value, request)] = value
    return rendered


def _record_values_for_structured_scalar_render(
    record: MetadataReadRecord,
    request: OutputRenderRequest,
) -> JsonRecord:
    if not request.structured_output:
        return record.values
    if request.format not in {"csv", "html"}:
        return record.values
    xml_elements = record.xml_elements or _source_xmp_xml_elements_for_structured_scalar_render(
        record
    )
    if not xml_elements:
        return record.values

    flattened_struct_keys = _flattened_struct_keys_for_elements(xml_elements)
    output: JsonRecord = {}
    for key, value in record.values.items():
        if key in flattened_struct_keys:
            continue
        output[key] = value
    for element in xml_elements:
        if not element.struct_fields and not element.struct_list_items:
            continue
        output[_json_element_key(element, request)] = _serialized_struct_xml_element(element)
    return output


def _source_xmp_xml_elements_for_structured_scalar_render(
    record: MetadataReadRecord,
) -> tuple[XmlTagElement, ...]:
    packets = _source_xmp_packets_for_structured_scalar_render(record.path)
    if not packets:
        return ()
    elements: list[XmlTagElement] = []
    seen: set[tuple[str, str]] = set()
    for packet in packets:
        for source_element in _source_xmp_struct_elements_from_packet(packet):
            key = (source_element.group, source_element.tag)
            if key in seen:
                continue
            elements.append(_xml_tag_element_from_source_struct_element(source_element))
            seen.add(key)
    return tuple(elements)


def _source_xmp_packets_for_structured_scalar_render(path: Path) -> tuple[bytes, ...]:
    if path.suffix.lower() == ".xmp":
        try:
            data = read_public_document_payload(path)
        except OSError:
            return ()
        if data is None:
            return ()
        return (data,)
    if path.suffix.lower() == ".png":
        return _source_png_textual_xmp_packets_for_structured_scalar_render(path)
    if path.suffix.lower() not in {".jpe", ".jpeg", ".jpg"}:
        return ()
    try:
        from exifmodern.formats.jpeg.app_segments.xmp import jpeg_xmp_packets_from_app1_file
    except ImportError:
        return ()
    try:
        return tuple(packet.packet for packet in jpeg_xmp_packets_from_app1_file(path))
    except OSError, ValueError:
        return ()


def _source_png_textual_xmp_packets_for_structured_scalar_render(path: Path) -> tuple[bytes, ...]:
    try:
        data = read_public_document_payload(path)
    except OSError:
        return ()
    if data is None:
        return ()
    try:
        from exifmodern.formats.png.textual_runtime import png_textual_xmp_packets

        return png_textual_xmp_packets(data)
    except ValueError:
        return ()


def _source_xmp_struct_elements_from_packet(
    packet: bytes,
) -> tuple[XmpSourceStructElement, ...]:
    try:
        from xml.etree import ElementTree

        from exifmodern.formats.xmp.reader import source_struct_elements_from_xmp_packet

        return source_struct_elements_from_xmp_packet(packet)
    except ElementTree.ParseError, ValueError:
        return ()


def _xml_tag_element_from_source_struct_element(
    element: XmpSourceStructElement,
) -> XmlTagElement:
    from exifmodern.public_api.models import XmlTagElement

    return XmlTagElement(
        group=element.group,
        tag=element.tag,
        value=element.value,
        uri_path=element.uri_path,
        list_container=_xml_list_container(element.list_container),
        struct_list_items=tuple(
            _xml_struct_list_item_from_source_struct_item(item)
            for item in element.struct_list_items
        ),
    )


def _xml_list_container(
    value: str | None,
) -> Literal["Bag", "Seq", "Alt"]:
    if value == "Bag":
        return "Bag"
    if value == "Seq":
        return "Seq"
    if value == "Alt":
        return "Alt"
    return "Bag"


def _xml_struct_list_item_from_source_struct_item(
    item: XmpSourceStructListItem,
) -> XmlStructListItem:
    from exifmodern.public_api.models import XmlStructListItem, XmlStructListItemBoundary

    return XmlStructListItem(
        fields=tuple(_xml_struct_field_from_source_struct_field(field) for field in item.fields),
        boundary=XmlStructListItemBoundary(
            source_index=item.source_index,
            source_path=item.source_path,
        ),
    )


def _xml_struct_field_from_source_struct_field(
    field: XmpSourceStructField,
) -> XmlStructField:
    from exifmodern.public_api.models import XmlStructField

    return XmlStructField(
        group=field.group,
        tag=field.tag,
        value=field.value,
        uri_path=field.uri_path,
        struct_fields=tuple(
            _xml_struct_field_from_source_struct_field(nested_field)
            for nested_field in field.struct_fields
        ),
    )


def _flattened_struct_keys_for_elements(
    elements: tuple[XmlTagElement, ...],
) -> set[str]:
    keys: set[str] = set()
    for element in elements:
        for field in element.struct_fields:
            _add_flattened_struct_field_keys(keys, element.tag, field)
        for item in element.struct_list_items:
            for field in item.fields:
                _add_flattened_struct_field_keys(keys, element.tag, field)
    return keys


def _add_flattened_struct_field_keys(
    keys: set[str],
    parent_tag: str,
    field: XmlStructField,
) -> None:
    keys.add(f"{parent_tag}{field.tag}")
    keys.add(f"{field.group}:{parent_tag}{field.tag}")
    keys.add(field.tag)
    keys.add(f"{field.group}:{field.tag}")
    for nested_field in field.struct_fields:
        _add_flattened_struct_field_keys(keys, f"{parent_tag}{field.tag}", nested_field)


def _serialized_struct_xml_element(element: XmlTagElement) -> str:
    # Source: ../exiftool/exiftool lines 2709-2711 call XMP SerializeStruct for
    # -struct values outside XML/JSON, and
    # ../exiftool/lib/Image/ExifTool/XMPStruct.pl lines 34-68 define the
    # default compact "{field=value}" / "[...]" scalar escaping.
    if element.struct_list_items:
        return _serialize_struct_list_items(element.struct_list_items, closing_bracket=None)
    return _serialize_struct_fields(element.struct_fields, closing_bracket=None)


def _serialize_struct_list_items(
    items: tuple[XmlStructListItem, ...],
    *,
    closing_bracket: str | None,
) -> str:
    _ = closing_bracket
    rendered_items = (_serialize_struct_fields(item.fields, closing_bracket="]") for item in items)
    return "[" + ",".join(rendered_items) + "]"


def _serialize_struct_fields(
    fields: tuple[XmlStructField, ...],
    *,
    closing_bracket: str | None,
) -> str:
    _ = closing_bracket
    return "{" + ",".join(_serialize_struct_field(field) for field in fields) + "}"


def _serialize_struct_field(field: XmlStructField) -> str:
    if field.struct_fields:
        return f"{field.tag}={_serialize_struct_fields(field.struct_fields, closing_bracket='}')}"
    return f"{field.tag}={_serialize_struct_tag_value(field.value, closing_bracket='}')}"


def _serialize_struct_tag_value(value: TagValue, *, closing_bracket: str | None) -> str:
    if isinstance(value, list):
        return (
            "["
            + ",".join(_serialize_struct_tag_value(item, closing_bracket="]") for item in value)
            + "]"
        )
    if value is None:
        return ""
    return _escape_serialized_struct_scalar(text_value(value), closing_bracket=closing_bracket)


def _escape_serialized_struct_scalar(
    value: str,
    *,
    closing_bracket: str | None,
) -> str:
    escaped: list[str] = []
    for character in value:
        if character in {",", "|"} or (
            closing_bracket is not None and character == closing_bracket
        ):
            escaped.append("|")
        escaped.append(character)
    rendered = "".join(escaped)
    if rendered[:1] in {" ", "\t", "\n", "\r", "[", "{"}:
        return "|" + rendered
    return rendered


def _key_for_missing_group_family_render(
    key: str,
    value: TagValue,
    request: OutputRenderRequest,
) -> str:
    if key == "SourceFile" or not key.startswith("Unknown:") or value != request.missing_tag_value:
        return key
    tag_name = key.split(":", 1)[1]
    # Source: ../exiftool/exiftool lines 2732-2749 force missing values, then
    # use Copy0 only for JSON/PHP family-4 group output. CSV remains ungrouped;
    # text/tab/HTML keep the empty family-4 group when group output is active.
    if request.format in {"json", "php"}:
        return f"Copy0:{tag_name}"
    if request.format in {"csv", "tab", "text", "html"}:
        return f":{tag_name}"
    return key


def _html_group_and_name(key: str) -> tuple[str, str]:
    if ":" not in key:
        return "", key
    group, name = key.rsplit(":", 1)
    return group, name


def _html_element_metadata_by_key(
    record: MetadataReadRecord,
    request: OutputRenderRequest,
) -> dict[str, XmlTagElement]:
    metadata: dict[str, XmlTagElement] = {}
    for element in record.xml_elements:
        metadata[element.tag] = element
        metadata[f"{element.group}:{element.tag}"] = element
        output_key = _json_element_key(element, request)
        metadata[output_key] = element
    return metadata


def _render_record_text(record: JsonRecord, request: OutputRenderRequest) -> str:
    lines: list[str] = []
    state = _text_render_state(request)
    for key, value in record.items():
        if key == "SourceFile":
            continue
        if _skip_default_text_tag(key, value, request, state):
            continue
        if request.short_output_level >= 3:
            lines.append(f"{text_value(value, list_separator=state.list_separator)}\n")
            continue
        label = _text_label_for_key(key, request, record, state)
        rendered_value = text_value(value, list_separator=state.list_separator)
        lines.append(f"{label}: {rendered_value}\n")
    return "".join(lines)


def _text_render_state(request: OutputRenderRequest) -> _TextRenderState:
    normalized_language = normalized_public_language_code(request.language_code)
    use_short_label = (
        request.short_output_level >= 1 or request.short_tag_names or request.very_short_output
    )
    return _TextRenderState(
        use_short_label=use_short_label,
        use_latin_label=request.output_charset == "Latin" and normalized_language == "en",
        use_translated_description_labels=normalized_language != "en",
        use_missing_tag_description_labels=request.missing_tag_value is not None,
        translate_descriptions=normalized_language not in {"", "en"},
        list_separator=request.list_separator,
    )


def _skip_default_text_tag(
    key: str,
    value: TagValue,
    request: OutputRenderRequest,
    state: _TextRenderState | None = None,
) -> bool:
    state = state or _text_render_state(request)
    if state.use_short_label or request.include_group_names:
        return False
    tag_name = key.rsplit(":", 1)[-1]
    # Source: ExifTool default text output suppresses zero-only subsecond
    # composite dates even though `-j` exposes them. Keep structured/API output
    # unchanged and apply the suppression only to default text rendering.
    return tag_name in _ZERO_SUBSECOND_COMPOSITE_TAGS and isinstance(value, str)


def _render_record_tab(record: JsonRecord, request: OutputRenderRequest) -> str:
    output_values = [(key, value) for key, value in record.items() if key != "SourceFile"]
    if request.short_output_level >= 2 or request.very_short_output:
        return (
            "\t".join(
                text_value(value, list_separator=request.list_separator)
                for _, value in output_values
            )
            + "\n"
        )
    lines: list[str] = []
    for key, value in output_values:
        rendered_value = text_value(value, list_separator=request.list_separator)
        lines.append(f"{_tab_label_for_key(key, request)}\t{rendered_value}\n")
    return "".join(lines)


def _tab_label_for_key(key: str, request: OutputRenderRequest) -> str:
    if request.include_group_names and ":" in key:
        group, name = key.rsplit(":", 1)
        return f"[{group}] {name}"
    return key


def _text_label_for_key(
    key: str,
    request: OutputRenderRequest,
    record: JsonRecord | None = None,
    state: _TextRenderState | None = None,
) -> str:
    state = state or _text_render_state(request)
    if state.use_short_label:
        if request.include_group_names and ":" in key:
            group, name = key.rsplit(":", 1)
            return f"[{group}] {name}"
        return key
    if state.use_latin_label:
        if request.include_group_names and ":" in key:
            group, name = key.rsplit(":", 1)
            prefix = f"[{group}]"
            return f"{prefix:<15} {name:<32}"
        return f"{key:<32}"
    if _text_label_should_use_description(key, request, state):
        if request.include_group_names and ":" in key:
            group, name = key.rsplit(":", 1)
            prefix = f"[{group}]"
            return (
                f"{prefix:<15} {_default_text_label_for_tag_name(name, request, record, state):<32}"
            )
        return f"{_default_text_label_for_tag_name(key, request, record, state):<32}"
    if request.include_group_names and ":" in key:
        group, name = key.rsplit(":", 1)
        prefix = f"[{group}]"
        return f"{prefix:<15} {name:<32}"
    return f"{key:<32}"


def _text_label_should_use_description(
    key: str,
    request: OutputRenderRequest,
    state: _TextRenderState | None = None,
) -> bool:
    state = state or _text_render_state(request)
    if state.use_translated_description_labels:
        return True
    if state.use_missing_tag_description_labels and key.startswith(":"):
        return True
    tag_name = key.rsplit(":", 1)[-1]
    return tag_name in {"ExifToolVersion", "FileModifyDate"}


def _default_text_label_for_tag_name(
    tag_name: str,
    request: OutputRenderRequest,
    record: JsonRecord | None = None,
    state: _TextRenderState | None = None,
) -> str:
    state = state or _text_render_state(request)
    if state.translate_descriptions:
        translated = _translated_text_label_for_tag_name(tag_name, request.language_code)
        if translated is not None:
            return translated
    if (
        tag_name == "Model"
        and _record_file_type(record) in {"MOV", "MP4", "M4V", "3GP"}
        and not _record_has_embedded_exif_camera_model(record)
    ):
        return "Model"
    return _EXIFTOOL_DEFAULT_TEXT_LABELS.get(tag_name, _make_exiftool_description(tag_name))


def _record_file_type(record: JsonRecord | None) -> str | None:
    if record is None:
        return None
    value = record.get("FileType")
    return value.upper() if isinstance(value, str) else None


def _record_has_embedded_exif_camera_model(record: JsonRecord | None) -> bool:
    if record is None:
        return False
    return record.get("Make") == "Panasonic" and "ExifByteOrder" in record


def _make_exiftool_description(tag_name: str) -> str:
    # Source: ../exiftool/lib/Image/ExifTool.pm MakeDescription.
    desc = tag_name[:1].upper() + tag_name[1:]
    desc = desc.replace("_", " ")
    tag_id_match = re.search(r" (0x[\da-f]+)$", desc, flags=re.IGNORECASE)
    tag_id = None
    if tag_id_match is not None:
        tag_id = tag_id_match.group(1)
        desc = desc[: tag_id_match.start()]
    desc = re.sub(r"([a-z])([A-Z\d])", r"\1 \2", desc)
    desc = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", desc)
    desc = re.sub(r"(\d)([A-Z]\S)", r"\1 \2", desc)
    if tag_id is not None:
        desc = f"{desc} {tag_id}"
    return desc


def _translated_text_label_for_tag_name(tag_name: str, language_code: str) -> str | None:
    normalized_language = normalized_public_language_code(language_code)
    if normalized_language in {"", "en"}:
        return None
    service = _charset_language_runtime_service()
    if service is None:
        return None
    from exifmodern.services.charset_language_runtime import LanguageRuntimeRequest

    result = service.translate(
        LanguageRuntimeRequest(language=normalized_language, tag_name=tag_name)
    )
    return result.description if result.resolved else None


def normalized_public_language_code(language_code: str) -> str:
    return language_code.strip().replace("-", "_").lower()


@lru_cache(maxsize=1)
def _charset_language_runtime_service() -> CharsetLanguageRuntimeService | None:
    package_path = charset_language_package_path()
    if not package_path.is_file():
        return None
    from exifmodern.services.charset_language_runtime import (
        load_charset_language_runtime_service,
    )

    return load_charset_language_runtime_service(package_path)


def rendered_text_for_charset(text: str, request: OutputRenderRequest) -> str:
    normalized_charset = request.output_charset.strip().lower()
    if normalized_charset in {"", "utf8", "utf-8"}:
        return text
    if normalized_charset in {"latin", "latin1", "cp1252"}:
        # ExifTool -L is cp1252 output. In the public string API we preserve
        # text semantics while safely replacing codepoints cp1252 cannot emit.
        return text.encode("cp1252", errors="replace").decode("cp1252")
    return text


def text_value(value: TagValue, *, list_separator: str = ", ") -> str:
    if isinstance(value, BinaryTagListValue):
        return list_separator.join(
            f"(Binary data {item.byte_count} bytes, use -b option to extract)"
            for item in value.items
        )
    if isinstance(value, BinaryTagValue):
        return f"(Binary data {value.byte_count} bytes, use -b option to extract)"
    if isinstance(value, list):
        return list_separator.join(
            text_value(item, list_separator=list_separator) for item in value
        )
    if value is None:
        return ""
    return str(value)


def html_text_value(value: TagValue, *, list_separator: str = ", ") -> str:
    if isinstance(value, BinaryTagListValue):
        return list_separator.join(f"(Binary data {item.byte_count} bytes)" for item in value.items)
    if isinstance(value, BinaryTagValue):
        # Source: ../exiftool/exiftool lines 3979-3986 omit the "-b" hint for
        # HTML output because binary extraction is not valid for that renderer.
        return f"(Binary data {value.byte_count} bytes)"
    if isinstance(value, list):
        return list_separator.join(
            html_text_value(item, list_separator=list_separator) for item in value
        )
    if value is None:
        return ""
    return str(value)


def _render_exiftool_json_record(record: JsonObject) -> bytes:
    lines = ["[{"]
    lines.extend(_render_exiftool_json_record_body(record))
    lines.append("}]")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_exiftool_json_record_body(record: JsonObject) -> list[str]:
    lines: list[str] = []
    items = list(record.items())
    for index, (key, value) in enumerate(items):
        suffix = "," if index < len(items) - 1 else ""
        lines.append(
            f"  {json.dumps(key, ensure_ascii=False)}: {_render_exiftool_json_value(value)}{suffix}"
        )
    return lines


def _render_exiftool_json_value(value: JsonValue | TagValue) -> str:
    if isinstance(value, BinaryTagListValue | BinaryTagValue):
        return json.dumps(text_value(value), ensure_ascii=False)
    if _is_binary_tag_value_like(value):
        return json.dumps(
            f"(Binary data {value.byte_count} bytes, use -b option to extract)",
            ensure_ascii=False,
        )
    if isinstance(value, list):
        rendered_items = ",".join(_render_exiftool_json_value(item) for item in value)
        return f"[{rendered_items}]"
    if isinstance(value, dict):
        rendered_items = ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{_render_exiftool_json_value(item)}"
            for key, item in value.items()
        )
        return f"{{{rendered_items}}}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "null"
    if _is_exiftool_json_unquoted_string(value):
        return value.lower() if value.lower() in {"true", "false"} else value
    return json.dumps(value, ensure_ascii=False)


def _render_php_array(record: JsonObject, *, indent: str) -> str:
    if not record:
        return "Array()"
    lines = ["Array("]
    items = list(record.items())
    next_indent = indent + "  "
    for index, (key, value) in enumerate(items):
        suffix = "," if index < len(items) - 1 else ""
        lines.append(
            f"{next_indent}{_render_php_string(key, binary=False, force_quote=True)} => "
            f"{_render_php_value(value, indent=next_indent)}{suffix}"
        )
    lines.append(f"{indent})")
    return "\n".join(lines)


def _render_php_value(value: JsonValue, *, indent: str) -> str:
    if isinstance(value, list):
        if not value:
            return "Array()"
        next_indent = indent + "  "
        lines = ["Array("]
        for index, item in enumerate(value):
            suffix = "," if index < len(value) - 1 else ""
            lines.append(f"{next_indent}{_render_php_value(item, indent=next_indent)}{suffix}")
        lines.append(f"{indent})")
        return "\n".join(lines)
    if isinstance(value, dict):
        return _render_php_array(value, indent=indent)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "NULL"
    return _render_php_string(
        value,
        binary=isinstance(value, _PhpBinaryString),
        force_quote=False,
    )


def _render_php_string(value: str, *, binary: bool, force_quote: bool) -> str:
    # Source: ../exiftool/exiftool lines 3796-3827 use EscapeJSON for PHP too:
    # numbers remain unquoted, "$" is escaped, controls use \xNN, and non-binary
    # strings lose trailing NULs.
    if not force_quote and _EXIFTOOL_JSON_NUMBER_RE.fullmatch(value) is not None:
        return value
    escaped = _escape_php_json_basics(value)
    if not binary:
        escaped = escaped.rstrip("\0")
    escaped = escaped.replace("$", "\\$")
    escaped = "".join(_php_control_escape(character) for character in escaped)
    return f'"{escaped}"'


def _escape_php_json_basics(value: str) -> str:
    output: list[str] = []
    for character in value:
        if character == '"':
            output.append('\\"')
        elif character == "\\":
            output.append("\\\\")
        elif character == "\t":
            output.append("\\t")
        elif character == "\n":
            output.append("\\n")
        elif character == "\r":
            output.append("\\r")
        else:
            output.append(character)
    return "".join(output)


def _php_control_escape(character: str) -> str:
    ordinal = ord(character)
    if ordinal < 0x20 or ordinal == 0x7F:
        return f"\\x{ordinal:02X}"
    return character


def _is_exiftool_json_unquoted_string(value: str) -> bool:
    return (
        value.lower() in {"true", "false"} or _EXIFTOOL_JSON_NUMBER_RE.fullmatch(value) is not None
    )


def _is_binary_tag_value_like(value: JsonValue | TagValue) -> TypeGuard[_BinaryTagValueLike]:
    return value.__class__.__name__ == "BinaryTagValue" and hasattr(value, "byte_count")
