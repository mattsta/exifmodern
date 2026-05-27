"""XISF transaction planning public API."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree

from exifmodern.formats.xisf.metadata_transaction_plan import (
    XisfMetadataTransactionPlan,
    XisfRewriteRequest,
    build_xisf_metadata_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = (
    "XisfMetadataTransactionPlan",
    "XisfRewriteRequest",
    "build_xisf_metadata_transaction_plan",
    "build_xisf_read_graph",
    "invoke_xisf",
)


_XISF_IMAGE_TABLE = "Image::ExifTool::XISF::Image"
_XISF_PROPERTY_TABLE = "Image::ExifTool::XISF::Property"
_FILE_TABLE = "Image::ExifTool::File"
_XML_TABLE = "Image::ExifTool::XMP::XML"


def build_xisf_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate an XISF metadata transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_xisf_metadata_transaction_plan(data)
    diagnostics = [
        f"XISF package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"XISF package-local reader status: {plan.status}")

    tags: list[ReadTag] = []
    descriptor = plan.image_descriptor
    if plan.status == "planned":
        for name, value in (
            ("FileType", "XISF"),
            ("FileTypeExtension", "xisf"),
            ("MIMEType", "image/x-xisf"),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_provenance(
                        group="File",
                        table_name=_FILE_TABLE,
                        tag_id=name,
                        evidence_ids=plan.header_validation.evidence_ids,
                    ),
                    schema=None,
                )
            )
        if descriptor.image_width is not None and descriptor.image_height is not None:
            for name, image_value in (
                ("ImageWidth", int(descriptor.image_width)),
                ("ImageHeight", int(descriptor.image_height)),
                (
                    "NumPlanes",
                    None if descriptor.num_planes is None else int(descriptor.num_planes),
                ),
            ):
                if image_value is None:
                    continue
                tags.append(
                    ReadTag(
                        name=name,
                        value=_read_value(image_value),
                        provenance=_provenance(
                            group="File",
                            table_name=_XISF_IMAGE_TABLE,
                            tag_id=name,
                            evidence_ids=descriptor.evidence_ids,
                        ),
                        schema=None,
                    )
                )
        tags.append(
            ReadTag(
                name="XML",
                value=_read_value(
                    f"(Binary data {len(plan.xml_header.xml_bytes)} bytes, "
                    "use -b option to extract)"
                ),
                provenance=_provenance(
                    group="XML",
                    table_name=_XML_TABLE,
                    tag_id="XML",
                    evidence_ids=plan.xml_header.evidence_ids,
                ),
                schema=None,
            )
        )
    for index, attr in enumerate(descriptor.image_attributes):
        tags.append(
            ReadTag(
                name=attr.routed_tag,
                value=_read_value(_xisf_scalar(attr.routed_tag, attr.value)),
                provenance=_provenance(
                    group="XML",
                    table_name=_XISF_IMAGE_TABLE,
                    tag_id=attr.source_key,
                    evidence_ids=attr.evidence_ids,
                    duplicate_instance_ordinal=index,
                ),
                schema=None,
            )
        )
    tags.extend(_xisf_nested_xml_tags(plan.xml_header.xml_bytes, descriptor.evidence_ids))
    if descriptor.image_width is not None and descriptor.image_height is not None:
        width = int(descriptor.image_width)
        height = int(descriptor.image_height)
        tags.extend(
            (
                ReadTag(
                    name="ImageSize",
                    value=_read_value(f"{width}x{height}"),
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="ImageSize",
                        evidence_ids=descriptor.evidence_ids,
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="Megapixels",
                    value=_read_value(round(width * height / 1e6, 3)),
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="Megapixels",
                        evidence_ids=descriptor.evidence_ids,
                    ),
                    schema=None,
                ),
            )
        )
    return _graph(source_file, tags, diagnostics)


def _xisf_scalar(name: str, value: str) -> str | int | float:
    if name == "CreateDate":
        return value.replace("-", ":", 2).replace("T", " ")
    if name in {"CompressionLevel", "XResolution", "YResolution"}:
        return int(value)
    return value


def _xisf_nested_xml_tags(xml_bytes: bytes, evidence_ids: tuple[str, ...]) -> list[ReadTag]:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return []
    tags: list[ReadTag] = []
    image = _first_child_by_local_name(root, "Image")
    if image is None:
        return tags
    data = _first_child_by_local_name(image, "Data")
    if data is not None:
        if "compression" in data.attrib:
            tags.append(
                _xml_read_tag("ImageDataCompression", data.attrib["compression"], evidence_ids)
            )
        if "encoding" in data.attrib:
            tags.append(_xml_read_tag("ImageDataEncoding", data.attrib["encoding"], evidence_ids))
        payload_text = (data.text or "").strip()
        if payload_text:
            tags.append(
                _xml_read_tag(
                    "ImageData",
                    f"(Binary data {len(payload_text)} bytes, use -b option to extract)",
                    evidence_ids,
                )
            )
    resolution = _first_child_by_local_name(image, "Resolution")
    if resolution is not None:
        for attribute, name in (
            ("horizontal", "XResolution"),
            ("vertical", "YResolution"),
            ("unit", "ResolutionUnit"),
        ):
            value = resolution.attrib.get(attribute)
            if value is not None:
                tags.append(_xml_read_tag(name, _xisf_scalar(name, value), evidence_ids))
    metadata = _first_child_by_local_name(root, "Metadata")
    if metadata is not None:
        for child in metadata:
            if child.tag.rsplit("}", 1)[-1] != "Property":
                continue
            raw_id = child.attrib.get("id", "")
            name = raw_id.removeprefix("XISF:")
            name = "CreateDate" if name == "CreationTime" else name
            value = child.attrib.get("value", child.text or "")
            if name and value != "":
                tags.append(_xml_read_tag(name, _xisf_scalar(name, value), evidence_ids))
    return tags


def _first_child_by_local_name(
    element: ElementTree.Element, local_name: str
) -> ElementTree.Element | None:
    for child in element:
        if child.tag.rsplit("}", 1)[-1] == local_name:
            return child
    return None


def _xml_read_tag(name: str, value: str | int | float, evidence_ids: tuple[str, ...]) -> ReadTag:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group="XML",
            table_name=_XML_TABLE,
            tag_id=name,
            evidence_ids=evidence_ids,
        ),
        schema=None,
    )


def invoke_xisf(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_xisf_read_graph(_read_xisf_exiftool_xml_header(path), source_file)


def _read_xisf_exiftool_xml_header(path: Path) -> bytes:
    """Read XISF's 16-byte preamble and declared XML header only."""
    with path.open("rb") as file:
        preamble = file.read(16)
        if len(preamble) < 16:
            return preamble
        xml_length = int.from_bytes(preamble[8:12], "little")
        return preamble + file.read(xml_length)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="xisf",
        builder_ref="exifmodern.formats.xisf:invoke_xisf",
        patterns=(Pattern(0, b"XISF0100"),),
    ),
)
