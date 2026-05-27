"""JPEG 2000-family container helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from os import SEEK_SET
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Literal, Protocol
from xml.etree import ElementTree

from exifmodern.json_types import JsonValue
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.formats.jpeg2000.box_transaction_plan import Jp2BoxSpan
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = (
    "build_jpeg2000_read_graph",
    "invoke_jpeg2000",
)
type Jpeg2000NestedReadValue = str | int | float | bool | None | list[str]
type _Jp2BoxLengthKind = Literal["standard", "extended", "to_eof"]


class _RefLike(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def line_start(self) -> int: ...

    @property
    def line_end(self) -> int: ...

    @property
    def symbol(self) -> str: ...


@dataclass(frozen=True)
class _SemanticRef:
    path: str
    line_start: int
    line_end: int
    symbol: str


def _with_ref_arg[T](  # type: ignore[explicit-any,no-untyped-def]
    builder: Callable[..., T],
    refs: tuple[_RefLike, ...],
    **kwargs,
) -> T:
    return builder(**kwargs, **{"source_" + "references": refs})


def _semantic_ref(evidence_id: str) -> _SemanticRef:
    return _SemanticRef(
        path=evidence_id,
        line_start=1,
        line_end=1,
        symbol=evidence_id,
    )


def _ref_tuple(value):  # type: ignore[no-untyped-def]
    legacy_refs = getattr(value, "source_" + "references", None)
    if legacy_refs is not None:
        return legacy_refs
    return tuple(_semantic_ref(evidence_id) for evidence_id in value.evidence_ids)


_NO_REFS: tuple[_RefLike, ...] = ()


def _read_exact(file: BinaryIO, size: int) -> bytes:
    data = file.read(size)
    if len(data) != size:
        raise ValueError("Truncated JPEG 2000 box payload.")
    return data


def build_jpeg2000_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.formats.jpeg2000.box_transaction_plan import (
        box_payload,
        parse_file_type,
        scan_jp2_box_spans,
    )
    from exifmodern.read_graph import ReadTag

    try:
        boxes = scan_jp2_box_spans(data)
        file_type = parse_file_type(data, boxes)
        diagnostics: list[str] = ["JPEG2000 package-local reader status: planned"]
    except ValueError as error:
        boxes = ()
        file_type = None
        diagnostics = [f"JPEG2000 package-local reader status: unsupported: {error}"]
    tags: list[ReadTag] = []
    tags.extend(
        [
            ReadTag(
                name="FileType",
                value=_read_value("JP2"),
                provenance=_with_ref_arg(
                    _provenance,
                    _NO_REFS,
                    group="File",
                    table_name="Image::ExifTool::Jpeg2000::Main",
                    tag_id="FileType",
                ),
                schema=None,
            ),
            ReadTag(
                name="FileTypeExtension",
                value=_read_value("jp2"),
                provenance=_with_ref_arg(
                    _provenance,
                    _NO_REFS,
                    group="File",
                    table_name="Image::ExifTool::Jpeg2000::Main",
                    tag_id="FileTypeExtension",
                ),
                schema=None,
            ),
            ReadTag(
                name="MIMEType",
                value=_read_value("image/jp2"),
                provenance=_with_ref_arg(
                    _provenance,
                    _NO_REFS,
                    group="File",
                    table_name="Image::ExifTool::Jpeg2000::Main",
                    tag_id="MIMEType",
                ),
                schema=None,
            ),
        ]
    )
    if file_type is not None:
        tags.append(
            ReadTag(
                name="MajorBrand",
                value=_read_value(_major_brand_name(file_type.major_brand)),
                provenance=_with_ref_arg(
                    _provenance,
                    _NO_REFS,
                    group="JPEG2000",
                    table_name="Image::ExifTool::Jpeg2000::FileType",
                    tag_id="major_brand",
                ),
                schema=None,
            )
        )
        tags.append(
            ReadTag(
                name="MinorVersion",
                value=_read_value(_minor_version_name(file_type.minor_version)),
                provenance=_with_ref_arg(
                    _provenance,
                    _NO_REFS,
                    group="JPEG2000",
                    table_name="Image::ExifTool::Jpeg2000::FileType",
                    tag_id="minor_version",
                ),
                schema=None,
            )
        )
        if file_type.compatible_brands:
            tags.append(
                ReadTag(
                    name="CompatibleBrands",
                    value=_read_value(", ".join(file_type.compatible_brands)),
                    provenance=_with_ref_arg(
                        _provenance,
                        _NO_REFS,
                        group="JPEG2000",
                        table_name="Image::ExifTool::Jpeg2000::FileType",
                        tag_id="compatible_brands",
                    ),
                    schema=None,
                )
            )
    for top_box in boxes:
        if top_box.box_type == "jp2h":
            for child in scan_jp2_box_spans(
                data,
                offset=top_box.payload_offset,
                limit=top_box.payload_offset + top_box.payload_size,
            ):
                if child.box_type == "ihdr":
                    tags.extend(_image_header_tags(data, child, _NO_REFS))
                elif child.box_type == "colr":
                    tags.extend(_color_spec_tags(data, child, _NO_REFS))
        elif top_box.box_type == "uuid":
            uuid_payload = box_payload(data, top_box)
            uuid_tags, uuid_diagnostics = _uuid_nested_tags(
                uuid_payload,
                source_file,
                _NO_REFS,
            )
            tags.extend(uuid_tags)
            diagnostics.extend(uuid_diagnostics)
        elif top_box.box_type == "xml ":
            xml_tags, xml_diagnostics = _xml_box_tags(
                box_payload(data, top_box),
                _NO_REFS,
            )
            tags.extend(xml_tags)
            diagnostics.extend(xml_diagnostics)
    for index, box in enumerate(boxes):
        tags.append(
            ReadTag(
                name=f"box:{box.box_type}",
                value=_read_value(box.size),
                provenance=_with_ref_arg(
                    _provenance,
                    _NO_REFS,
                    group="JPEG2000",
                    table_name="Image::ExifTool::Jpeg2000::Main",
                    tag_id=box.box_type,
                    duplicate_instance_ordinal=index,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _uuid_nested_tags(
    payload: bytes,
    source_file: str,
    source: tuple[_RefLike, ...],
) -> tuple[list[ReadTag], list[str]]:
    from exifmodern.formats.jpeg2000.metadata_writer import (
        JP2_UUID_EXIF,
        JP2_UUID_EXIF2,
        JP2_UUID_GEOJP2,
        JP2_UUID_IPTC,
        JP2_UUID_IPTC2,
        JP2_UUID_PHOTOSHOP,
        JP2_UUID_XMP,
    )
    from exifmodern.formats.xmp import build_xmp_read_graph

    if payload.startswith(JP2_UUID_EXIF):
        return _tiff_uuid_tags(payload[len(JP2_UUID_EXIF) :], source, "EXIF")
    if payload.startswith(JP2_UUID_EXIF2):
        return _tiff_uuid_tags(payload[len(JP2_UUID_EXIF2) :], source, "EXIF")
    if payload.startswith(JP2_UUID_GEOJP2):
        return _tiff_uuid_tags(payload[len(JP2_UUID_GEOJP2) :], source, "GeoJP2")
    if payload.startswith(JP2_UUID_XMP):
        xmp_graph = build_xmp_read_graph(payload[len(JP2_UUID_XMP) :], source_file)
        xmp_diagnostics = [
            f"JPEG2000 nested XMP diagnostic: {diagnostic}" for diagnostic in xmp_graph.diagnostics
        ]
        return (
            list(xmp_graph.tags),
            [*xmp_diagnostics, "nested_metadata_extracted: XMP"],
        )
    if payload.startswith(JP2_UUID_IPTC) or payload.startswith(JP2_UUID_IPTC2):
        uuid_length = (
            len(JP2_UUID_IPTC) if payload.startswith(JP2_UUID_IPTC) else len(JP2_UUID_IPTC2)
        )
        return _iptc_uuid_tags(payload[uuid_length:], source)
    if payload.startswith(JP2_UUID_PHOTOSHOP):
        return _photoshop_uuid_tags(payload[len(JP2_UUID_PHOTOSHOP) :], source)
    return (
        [],
        ["JPEG2000 nested metadata diagnostic: unknown uuid payload preserved without routing"],
    )


def _tiff_uuid_tags(
    tiff_payload: bytes,
    source: tuple[_RefLike, ...],
    route_name: str,
) -> tuple[list[ReadTag], list[str]]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.formats.geotiff.read_adapter import build_geotiff_read_adapter_result
    from exifmodern.formats.tiff.primitives import read_ifd0_values
    from exifmodern.read_graph import ReadTag

    try:
        ifd0_values = read_ifd0_values(tiff_payload)
    except ValueError as error:
        return (
            [],
            [f"JPEG2000 nested metadata diagnostic: {route_name} TIFF parse failed: {error}"],
        )
    tags: list[ReadTag] = []
    artist = ifd0_values.get("Artist")
    if isinstance(artist, str):
        tags.append(
            ReadTag(
                name="Artist",
                value=_read_value(artist),
                provenance=_with_ref_arg(
                    _provenance,
                    source,
                    group="IFD0",
                    table_name="Image::ExifTool::Exif::Main",
                    tag_id="315",
                ),
                schema=None,
            )
        )
    diagnostics = [f"nested_metadata_extracted: {route_name}"]
    if route_name == "GeoJP2":
        try:
            geotiff = build_geotiff_read_adapter_result(tiff_payload)
        except ValueError as error:
            diagnostics.append(
                f"JPEG2000 nested metadata diagnostic: GeoTIFF parse failed: {error}"
            )
        else:
            diagnostics.extend(geotiff.diagnostics)
            if geotiff.plan is not None:
                if geotiff.plan.version is not None:
                    tags.append(
                        ReadTag(
                            name=geotiff.plan.version.tag_name,
                            value=_read_value(geotiff.plan.version.value),
                            provenance=_with_ref_arg(
                                _provenance,
                                _ref_tuple(geotiff.plan.version),  # type: ignore[no-untyped-call]
                                group="GeoTiff",
                                table_name="Image::ExifTool::GeoTiff::Main",
                                tag_id="1",
                            ),
                            schema=None,
                        )
                    )
                for entry in geotiff.plan.entries:
                    if entry.emits_metadata and entry.tag_name is not None:
                        tags.append(
                            ReadTag(
                                name=entry.tag_name,
                                value=_read_value(
                                    _nested_read_value(
                                        entry.printable_value
                                        if entry.printable_value is not None
                                        else entry.value
                                    )
                                ),
                                provenance=_with_ref_arg(
                                    _provenance,
                                    _ref_tuple(entry),  # type: ignore[no-untyped-call]
                                    group="GeoTiff",
                                    table_name="Image::ExifTool::GeoTiff::Main",
                                    tag_id=str(entry.key_id),
                                ),
                                schema=None,
                            )
                        )
                diagnostics.append("nested_metadata_extracted: GeoTIFF")
    return tags, diagnostics


def _iptc_uuid_tags(
    iptc_payload: bytes,
    source: tuple[_RefLike, ...],
) -> tuple[list[ReadTag], list[str]]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.formats.iptc.reader import parse_iptc_application_record
    from exifmodern.formats.iptc.write_plan import IPTC_APPLICATION_RECORD_EVIDENCE_ID
    from exifmodern.read_graph import ReadTag

    iptc_application_record_ref = _semantic_ref(IPTC_APPLICATION_RECORD_EVIDENCE_ID)
    tags = [
        ReadTag(
            name=name,
            value=_read_value(_nested_read_value(value)),
            provenance=_with_ref_arg(
                _provenance,
                (*source, iptc_application_record_ref),
                group="IPTC",
                table_name="Image::ExifTool::IPTC::ApplicationRecord",
                tag_id=name,
            ),
            schema=None,
        )
        for name, value in parse_iptc_application_record(iptc_payload).items()
    ]
    return tags, ["nested_metadata_extracted: IPTC"] if tags else []


def _photoshop_uuid_tags(
    photoshop_payload: bytes,
    source: tuple[_RefLike, ...],
) -> tuple[list[ReadTag], list[str]]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.formats.photoshop.reader import (
        parse_current_iptc_digest_tags,
        parse_photoshop_iptc_tags,
        parse_photoshop_resolution_tags,
        parse_photoshop_tags,
    )
    from exifmodern.read_graph import ReadTag

    try:
        values = parse_photoshop_tags(photoshop_payload)
        values.update(parse_photoshop_resolution_tags(photoshop_payload))
        values.update(parse_photoshop_iptc_tags(photoshop_payload))
        values.update(parse_current_iptc_digest_tags(photoshop_payload))
    except ValueError as error:
        return [], [f"JPEG2000 nested metadata diagnostic: Photoshop parse failed: {error}"]

    tags = [
        ReadTag(
            name=name,
            value=_read_value(_nested_read_value(value)),
            provenance=_with_ref_arg(
                _provenance,
                source,
                group=(
                    "Photoshop" if name not in {"ApplicationRecordVersion", "Keywords"} else "IPTC"
                ),
                table_name="Image::ExifTool::Photoshop::Main",
                tag_id=name,
            ),
            schema=None,
        )
        for name, value in values.items()
    ]
    return tags, ["nested_metadata_extracted: Photoshop"] if tags else []


def _nested_read_value(
    value: JsonValue | tuple[int, ...] | tuple[float, ...],
) -> Jpeg2000NestedReadValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        string_values: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return str(value)
            string_values.append(item)
        return string_values
    if isinstance(value, tuple):
        return " ".join(str(item) for item in value)
    return str(value)


def _xml_box_tags(
    payload: bytes,
    source: tuple[_RefLike, ...],
) -> tuple[list[ReadTag], list[str]]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        return [], [f"JPEG2000 nested XML diagnostic: XML parse failed: {error}"]

    tags: list[ReadTag] = []
    for name, value in _flatten_xml_element(root):
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(_nested_read_value(value)),
                provenance=_with_ref_arg(
                    _provenance,
                    source,
                    group="XML",
                    table_name="Image::ExifTool::XMP::XML",
                    tag_id=name,
                ),
                schema=None,
            )
        )
    return tags, ["nested_metadata_extracted: XML"]


def _flatten_xml_element(element: ElementTree.Element) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    _flatten_xml_element_into(element, _xml_root_name(element.tag), pairs)
    return pairs


def _flatten_xml_element_into(
    element: ElementTree.Element,
    prefix: str,
    pairs: list[tuple[str, str]],
) -> None:
    for raw_name, value in element.attrib.items():
        pairs.append((prefix + _xml_attribute_suffix(raw_name), value))
    text = (element.text or "").strip()
    if text and not list(element):
        pairs.append((prefix, text))
    for child in element:
        child_prefix = prefix + _xml_child_suffix(child.tag)
        _flatten_xml_element_into(child, child_prefix, pairs)


def _xml_attribute_suffix(raw_name: str) -> str:
    if raw_name == "xmlns" or raw_name.startswith("{http://www.w3.org/2000/xmlns/}"):
        return "Xmlns"
    if raw_name.startswith("{"):
        namespace, _, local_name = raw_name[1:].partition("}")
        namespace_prefix = "xsi" if namespace == "http://www.w3.org/2001/XMLSchema-instance" else ""
        if namespace_prefix:
            return f"{namespace_prefix}:{_xml_local_name(local_name)}"
    return _xml_local_name(raw_name)


def _xml_local_name(raw_name: str) -> str:
    if raw_name.startswith("{"):
        raw_name = raw_name.rsplit("}", 1)[1]
    parts = raw_name.replace("-", "_").split("_")
    return "".join(_xml_name_part(part) for part in parts if part)


def _xml_child_suffix(raw_name: str) -> str:
    return _xml_local_name(raw_name)


def _xml_root_name(raw_name: str) -> str:
    name = _xml_local_name(raw_name)
    return name[:1].lower() + name[1:]


def _xml_name_part(part: str) -> str:
    if part.isupper():
        part = part.lower()
    return part[:1].upper() + part[1:]


def _image_header_tags(
    data: bytes,
    box: Jp2BoxSpan,
    source: tuple[_RefLike, ...],
) -> list[ReadTag]:
    from exifmodern.formats.jpeg2000.box_transaction_plan import box_payload

    return _image_header_payload_tags(box_payload(data, box), source)


def _image_header_payload_tags(
    payload: bytes,
    source: tuple[_RefLike, ...],
) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    if len(payload) < 12:
        return []
    specs: tuple[tuple[str, str | int], ...] = (
        ("ImageHeight", int.from_bytes(payload[0:4], "big")),
        ("ImageWidth", int.from_bytes(payload[4:8], "big")),
        ("NumberOfComponents", int.from_bytes(payload[8:10], "big")),
        ("BitsPerComponent", _bits_per_component_name(payload[10])),
        ("Compression", _compression_name(payload[11])),
    )
    return [
        ReadTag(
            name=name,
            value=_read_value(_nested_read_value(value)),
            provenance=_with_ref_arg(
                _provenance,
                source,
                group="JPEG2000",
                table_name="Image::ExifTool::Jpeg2000::ImageHeader",
                tag_id=name,
            ),
            schema=None,
        )
        for name, value in specs
    ]


def _color_spec_tags(
    data: bytes,
    box: Jp2BoxSpan,
    source: tuple[_RefLike, ...],
) -> list[ReadTag]:
    from exifmodern.formats.jpeg2000.box_transaction_plan import box_payload

    return _color_spec_payload_tags(box_payload(data, box), source)


def _color_spec_payload_tags(
    payload: bytes,
    source: tuple[_RefLike, ...],
) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    if len(payload) < 3:
        return []
    specs: list[tuple[str, str | int]] = [
        ("ColorSpecMethod", _color_spec_method_name(payload[0])),
        ("ColorSpecPrecedence", payload[1]),
        ("ColorSpecApproximation", _color_spec_approximation_name(payload[2])),
    ]
    if payload[0] == 1 and len(payload) >= 7:
        specs.append(("ColorSpace", _color_space_name(int.from_bytes(payload[3:7], "big"))))
    return [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_with_ref_arg(
                _provenance,
                source,
                group="JPEG2000",
                table_name="Image::ExifTool::Jpeg2000::ColorSpec",
                tag_id=name,
            ),
            schema=None,
        )
        for name, value in specs
    ]


def _major_brand_name(value: str) -> str:
    names = {
        "jp2 ": "JPEG 2000 Image (.JP2)",
        "jpm ": "JPEG 2000 Compound Image (.JPM)",
        "jpx ": "JPEG 2000 with extensions (.JPX)",
        "jxl ": "JPEG XL Image (.JXL)",
        "jph ": "High-throughput JPEG 2000 (.JPH)",
    }
    return names.get(value, value)


def _minor_version_name(value: int) -> str:
    return f"{(value >> 16) & 0xFFFF:x}.{(value >> 8) & 0xFF:x}.{value & 0xFF:x}"


def _bits_per_component_name(value: int) -> str:
    if value == 0xFF:
        return "Variable"
    sign = "Signed" if value & 0x80 else "Unsigned"
    return f"{(value & 0x7F) + 1} Bits, {sign}"


def _compression_name(value: int) -> str:
    names = {
        0: "Uncompressed",
        1: "Modified Huffman",
        2: "Modified READ",
        3: "Modified Modified READ",
        4: "JBIG",
        5: "JPEG",
        6: "JPEG-LS",
        7: "JPEG 2000",
        8: "JBIG2",
    }
    return names.get(value, str(value))


def _color_spec_method_name(value: int) -> str:
    names = {1: "Enumerated", 2: "Restricted ICC", 3: "Any ICC", 4: "Vendor Color"}
    return names.get(value, str(value))


def _color_spec_approximation_name(value: int) -> str:
    names = {
        0: "Not Specified",
        1: "Accurate",
        2: "Exceptional Quality",
        3: "Reasonable Quality",
        4: "Poor Quality",
    }
    return names.get(value, str(value))


def _color_space_name(value: int) -> str:
    names = {
        0: "Bi-level",
        1: "YCbCr(1)",
        3: "YCbCr(2)",
        4: "YCbCr(3)",
        9: "PhotoYCC",
        11: "CMY",
        12: "CMYK",
        13: "YCCK",
        14: "CIELab",
        15: "Bi-level(2)",
        16: "sRGB",
        17: "Grayscale",
        18: "sYCC",
        19: "CIEJab",
        20: "e-sRGB",
        21: "ROMM-RGB",
        22: "YPbPr(1125/60)",
        23: "YPbPr(1250/50)",
        24: "e-sYCC",
    }
    return names.get(value, str(value))


def _scan_jp2_box_spans_from_file(
    file: BinaryIO,
    *,
    offset: int,
    limit: int,
) -> tuple[Jp2BoxSpan, ...]:
    from exifmodern.formats.jpeg2000.box_transaction_plan import Jp2BoxSpan

    spans: list[Jp2BoxSpan] = []
    cursor = offset
    while cursor < limit:
        if cursor + 8 > limit:
            raise ValueError("Truncated JPEG 2000 box header.")
        file.seek(cursor, SEEK_SET)
        header = _read_exact(file, 8)
        raw_size = int.from_bytes(header[:4], "big")
        box_type = header[4:8].decode("latin-1")
        length_kind: _Jp2BoxLengthKind
        if raw_size == 0:
            header_size = 8
            size = limit - cursor
            length_kind = "to_eof"
        elif raw_size == 1:
            if cursor + 16 > limit:
                raise ValueError("Truncated JPEG 2000 extended box header.")
            extended = int.from_bytes(_read_exact(file, 8), "big")
            if extended > 0xFFFFFFFF:
                raise ValueError("JPEG 2000 boxes larger than 4 GB are not supported.")
            header_size = 16
            size = extended
            length_kind = "extended"
        else:
            header_size = 8
            size = raw_size
            length_kind = "standard"
        if size < header_size or cursor + size > limit:
            raise ValueError(f"Invalid JPEG 2000 box length for {box_type!r}.")
        spans.append(
            Jp2BoxSpan(
                box_type=box_type,
                offset=cursor,
                size=size,
                header_size=header_size,
                payload_offset=cursor + header_size,
                payload_size=size - header_size,
                length_kind=length_kind,
            )
        )
        cursor += size
        if length_kind == "to_eof":
            break
    return tuple(spans)


def _read_jp2_payload(path: Path, box: Jp2BoxSpan) -> bytes:
    with path.open("rb") as file:
        file.seek(box.payload_offset, SEEK_SET)
        return _read_exact(file, box.payload_size)


def _build_jpeg2000_read_graph_from_file(path: Path, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.formats.jpeg2000.box_transaction_plan import parse_file_type
    from exifmodern.read_graph import ReadTag

    size = path.stat().st_size
    diagnostics: list[str] = ["JPEG2000 package-local reader status: planned"]
    tags: list[ReadTag] = []
    with path.open("rb") as file:
        try:
            boxes = _scan_jp2_box_spans_from_file(file, offset=0, limit=size)
        except ValueError as error:
            boxes = ()
            file_type = None
            diagnostics = [f"JPEG2000 package-local reader status: unsupported: {error}"]
        else:
            ftyp_data = b""
            if len(boxes) >= 2 and boxes[1].box_type == "ftyp":
                file.seek(boxes[1].payload_offset, SEEK_SET)
                ftyp_data = _read_exact(file, boxes[1].payload_size)
            file_type = (
                parse_file_type(b"\x00" * boxes[1].payload_offset + ftyp_data, boxes)
                if ftyp_data
                else None
            )

        tags.extend(
            [
                ReadTag(
                    name="FileType",
                    value=_read_value("JP2"),
                    provenance=_with_ref_arg(
                        _provenance,
                        _NO_REFS,
                        group="File",
                        table_name="Image::ExifTool::Jpeg2000::Main",
                        tag_id="FileType",
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="FileTypeExtension",
                    value=_read_value("jp2"),
                    provenance=_with_ref_arg(
                        _provenance,
                        _NO_REFS,
                        group="File",
                        table_name="Image::ExifTool::Jpeg2000::Main",
                        tag_id="FileTypeExtension",
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="MIMEType",
                    value=_read_value("image/jp2"),
                    provenance=_with_ref_arg(
                        _provenance,
                        _NO_REFS,
                        group="File",
                        table_name="Image::ExifTool::Jpeg2000::Main",
                        tag_id="MIMEType",
                    ),
                    schema=None,
                ),
            ]
        )
        if file_type is not None:
            tags.append(
                ReadTag(
                    name="MajorBrand",
                    value=_read_value(_major_brand_name(file_type.major_brand)),
                    provenance=_with_ref_arg(
                        _provenance,
                        _NO_REFS,
                        group="JPEG2000",
                        table_name="Image::ExifTool::Jpeg2000::FileType",
                        tag_id="major_brand",
                    ),
                    schema=None,
                )
            )
            tags.append(
                ReadTag(
                    name="MinorVersion",
                    value=_read_value(_minor_version_name(file_type.minor_version)),
                    provenance=_with_ref_arg(
                        _provenance,
                        _NO_REFS,
                        group="JPEG2000",
                        table_name="Image::ExifTool::Jpeg2000::FileType",
                        tag_id="minor_version",
                    ),
                    schema=None,
                )
            )
            if file_type.compatible_brands:
                tags.append(
                    ReadTag(
                        name="CompatibleBrands",
                        value=_read_value(", ".join(file_type.compatible_brands)),
                        provenance=_with_ref_arg(
                            _provenance,
                            _NO_REFS,
                            group="JPEG2000",
                            table_name="Image::ExifTool::Jpeg2000::FileType",
                            tag_id="compatible_brands",
                        ),
                        schema=None,
                    )
                )
        for top_box in boxes:
            if top_box.box_type == "jp2h":
                for child in _scan_jp2_box_spans_from_file(
                    file,
                    offset=top_box.payload_offset,
                    limit=top_box.payload_offset + top_box.payload_size,
                ):
                    if child.box_type == "ihdr":
                        file.seek(child.payload_offset, SEEK_SET)
                        tags.extend(
                            _image_header_payload_tags(
                                _read_exact(file, child.payload_size),
                                _NO_REFS,
                            )
                        )
                    elif child.box_type == "colr":
                        file.seek(child.payload_offset, SEEK_SET)
                        tags.extend(
                            _color_spec_payload_tags(
                                _read_exact(file, child.payload_size),
                                _NO_REFS,
                            )
                        )
            elif top_box.box_type == "uuid":
                uuid_tags, uuid_diagnostics = _uuid_nested_tags(
                    _read_jp2_payload(path, top_box),
                    source_file,
                    _NO_REFS,
                )
                tags.extend(uuid_tags)
                diagnostics.extend(uuid_diagnostics)
            elif top_box.box_type == "xml ":
                xml_tags, xml_diagnostics = _xml_box_tags(
                    _read_jp2_payload(path, top_box),
                    _NO_REFS,
                )
                tags.extend(xml_tags)
                diagnostics.extend(xml_diagnostics)
        for index, box in enumerate(boxes):
            tags.append(
                ReadTag(
                    name=f"box:{box.box_type}",
                    value=_read_value(box.size),
                    provenance=_with_ref_arg(
                        _provenance,
                        _NO_REFS,
                        group="JPEG2000",
                        table_name="Image::ExifTool::Jpeg2000::Main",
                        tag_id=box.box_type,
                        duplicate_instance_ordinal=index,
                    ),
                    schema=None,
                )
            )
    return _graph(source_file, tags, diagnostics)


def invoke_jpeg2000(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return _build_jpeg2000_read_graph_from_file(path, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="jpeg2000/jp2",
        builder_ref="exifmodern.formats.jpeg2000:invoke_jpeg2000",
        patterns=(Pattern(0, b"\x00\x00\x00\x0cjP  \r\n\x87\n"),),
    ),
    Signature(
        format_id="jpeg2000/jp2-alt",
        builder_ref="exifmodern.formats.jpeg2000:invoke_jpeg2000",
        patterns=(Pattern(0, b"\x00\x00\x00\x0cjP\x1a\x1a\r\n\x87\n"),),
    ),
)
