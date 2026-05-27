"""ZISRAW/CZI adapter for the shared read graph contract."""

from __future__ import annotations

import time
from pathlib import Path
from xml.etree import ElementTree

from exifmodern.formats.zisraw.metadata_transaction_plan import (
    ZISRAW_MAIN_TABLE_SOURCE,
    ZISRAW_XML_PROCESS_SOURCE,
    ZisrawMetadataTransactionPlan,
    ZisrawXmlTagPlan,
    build_zisraw_metadata_transaction_plan,
)
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance, TagValue

_ZISRAW_MAX_SPARSE_MATERIALIZATION = 16 * 1024 * 1024


def build_zisraw_read_graph_from_file(path: Path, *, source_file: str) -> ReadGraph:
    return build_zisraw_read_graph(_read_zisraw_metadata_bytes(path), source_file=source_file)


def _read_zisraw_metadata_bytes(path: Path) -> bytes:
    from exifmodern.formats.zisraw.metadata_transaction_plan import (
        ZISRAW_HEADER_SIZE,
        ZISRAW_METADATA_HEADER_SIZE,
        ZISRAW_METADATA_OFFSET_OFFSET,
        ZISRAW_METADATA_XML_LENGTH_OFFSET,
    )

    chunks: list[tuple[int, bytes]] = []
    with path.open("rb") as file:
        header = file.read(ZISRAW_HEADER_SIZE)
        chunks.append((0, header))
        if len(header) < ZISRAW_HEADER_SIZE:
            return _join_sparse_chunks(chunks)
        metadata_offset = int.from_bytes(
            header[ZISRAW_METADATA_OFFSET_OFFSET : ZISRAW_METADATA_OFFSET_OFFSET + 8],
            "little",
        )
        if metadata_offset == 0:
            return _join_sparse_chunks(chunks)
        file.seek(metadata_offset)
        metadata_header = file.read(ZISRAW_METADATA_HEADER_SIZE)
        chunks.append((metadata_offset, metadata_header))
        if len(metadata_header) < ZISRAW_METADATA_HEADER_SIZE:
            return _join_sparse_chunks(chunks)
        xml_length = int.from_bytes(
            metadata_header[
                ZISRAW_METADATA_XML_LENGTH_OFFSET : ZISRAW_METADATA_XML_LENGTH_OFFSET + 4
            ],
            "little",
        )
        xml_offset = metadata_offset + ZISRAW_METADATA_HEADER_SIZE
        file.seek(xml_offset)
        chunks.append((xml_offset, file.read(xml_length)))
    return _join_sparse_chunks(chunks)


def _join_sparse_chunks(chunks: list[tuple[int, bytes]]) -> bytes:
    size = max((offset + len(chunk) for offset, chunk in chunks), default=0)
    if size > _ZISRAW_MAX_SPARSE_MATERIALIZATION:
        return chunks[0][1] if chunks else b""
    result = bytearray(b"\0" * size)
    for offset, chunk in chunks:
        result[offset : offset + len(chunk)] = chunk
    return bytes(result)


def build_zisraw_read_graph(data: bytes, *, source_file: str) -> ReadGraph:
    plan = build_zisraw_metadata_transaction_plan(data, allow_output_emission=True)
    diagnostics = [
        f"CZI package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    tags: list[ReadTag] = []
    if plan.status == "planned":
        tags.extend(_file_type_tags())
        tags.extend(_header_tags(plan))
        tags.append(
            _tag(
                "XML",
                (
                    f"(Binary data {len(plan.metadata_segment.xml_bytes)} bytes, "
                    "use -b option to extract)"
                ),
                "XML",
                "XML",
                "Image::ExifTool::XMP::XML",
                (ZISRAW_XML_PROCESS_SOURCE,),
            )
        )
        tags.extend(_zisraw_structured_xml_tags(plan))
        tags.extend(_xml_tags(plan))
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _file_type_tags() -> list[ReadTag]:
    return [
        _tag("FileType", "CZI", "FileType", "File", "Image::ExifTool::File", ()),
        _tag(
            "FileTypeExtension",
            "czi",
            "FileTypeExtension",
            "File",
            "Image::ExifTool::File",
            (),
        ),
        _tag(
            "MIMEType",
            "image/x-zeiss-czi",
            "MIMEType",
            "File",
            "Image::ExifTool::File",
            (),
        ),
    ]


def _header_tags(plan: ZisrawMetadataTransactionPlan) -> list[ReadTag]:
    values: tuple[tuple[str, TagValue], ...] = (
        (
            "ZISRAWVersion",
            None
            if plan.header_fields.version_print is None
            else float(plan.header_fields.version_print),
        ),
        ("PrimaryFileGUID", plan.header_fields.primary_file_guid_hex),
        ("FileGUID", plan.header_fields.file_guid_hex),
    )
    return [
        _tag(
            name,
            value,
            name,
            "File",
            "Image::ExifTool::ZISRAW::Main",
            (ZISRAW_MAIN_TABLE_SOURCE, ZISRAW_XML_PROCESS_SOURCE),
        )
        for name, value in values
        if value is not None
    ]


def _xml_tags(plan: ZisrawMetadataTransactionPlan) -> list[ReadTag]:
    return [
        _xml_tag(tag, ordinal)
        for ordinal, tag in enumerate(plan.xml_tags)
        if tag.shortened_name
        and tag.text is not None
        and tag.shortened_name
        not in {
            "MicroscopeStandSpecification",
            "EyePieceMag",
            "EyePieceTotalMag",
            "EyePieceDepthOfField",
            "EyePieceFieldOfView",
            "EyePieceTotalFieldOfView",
        }
    ]


def _zisraw_structured_xml_tags(plan: ZisrawMetadataTransactionPlan) -> list[ReadTag]:
    try:
        root = ElementTree.fromstring(plan.metadata_segment.xml_bytes)
    except ElementTree.ParseError:
        return []
    tags: list[ReadTag] = []
    hardware = _first_descendant(root, "HardwareSetting")
    if hardware is None:
        return tags
    microscope = _first_descendant(hardware, "Microscope")
    if microscope is not None:
        tags.extend(_element_attribute_tags("Microscope", microscope, plan))
        stand = _first_descendant(microscope, "StandSpecification")
        if stand is not None and stand.text is not None:
            tags.append(_xml_value_tag("MicroscopeStandSpecification", stand.text, plan))
        device_ref = _first_descendant(microscope, "DeviceRef")
        if device_ref is not None and "Id" in device_ref.attrib:
            tags.append(_xml_value_tag("MicroscopeDeviceRefId", device_ref.attrib["Id"], plan))
    eyepiece = _first_descendant(hardware, "EyePiece")
    if eyepiece is not None:
        tags.extend(_element_attribute_tags("EyePiece", eyepiece, plan))
        for child_name, tag_name in (
            ("Magnification", "EyePieceMag"),
            ("TotalMagnification", "EyePieceTotalMag"),
            ("DepthOfField", "EyePieceDepthOfField"),
            ("FieldOfView", "EyePieceFieldOfView"),
            ("TotalFieldOfView", "EyePieceTotalFieldOfView"),
        ):
            child = _first_descendant(eyepiece, child_name)
            if child is not None and child.text is not None:
                tags.append(_xml_value_tag(tag_name, _zisraw_xml_value(tag_name, child.text), plan))
    return tags


def _element_attribute_tags(
    prefix: str, element: ElementTree.Element, plan: ZisrawMetadataTransactionPlan
) -> list[ReadTag]:
    return [
        _xml_value_tag(
            prefix + attribute_name, _zisraw_xml_value(prefix + attribute_name, value), plan
        )
        for attribute_name, value in element.attrib.items()
    ]


def _first_descendant(element: ElementTree.Element, local_name: str) -> ElementTree.Element | None:
    for descendant in element.iter():
        if descendant.tag.rsplit("}", 1)[-1] == local_name:
            return descendant
    return None


def _xml_value_tag(name: str, value: TagValue, plan: ZisrawMetadataTransactionPlan) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="XML",
            table_name="Image::ExifTool::ZISRAW::XML",
            tag_id=name,
            source=_evidence_id_text((ZISRAW_XML_PROCESS_SOURCE,)),
            family_0_group="XML",
            family_1_group="XML",
            family_2_group="Image",
        ),
        schema=None,
    )


def _xml_tag(tag: ZisrawXmlTagPlan, ordinal: int) -> ReadTag:
    name = tag.shortened_name
    return ReadTag(
        name=name,
        value=_zisraw_xml_value(name, tag.text),
        provenance=TagProvenance(
            group="XML",
            table_name="Image::ExifTool::ZISRAW::XML",
            tag_id=tag.exiftool_input_name,
            source=_evidence_id_text(tag.evidence_ids),
            family_0_group="XML",
            family_1_group="XML",
            family_2_group="Image",
            duplicate_instance_ordinal=ordinal,
        ),
        schema=None,
    )


def _zisraw_xml_value(name: str, value: str | None) -> TagValue:
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if name.endswith("Mag") or name.endswith("FieldOfView"):
        try:
            return int(value)
        except ValueError:
            return float(value)
    if name.endswith("DepthOfField") or name.endswith("TotalFieldOfView"):
        return float(value)
    return value


def _tag(
    name: str,
    value: TagValue,
    tag_id: str,
    group: str,
    table_name: str,
    evidence_ids: tuple[str, ...],
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            source=_evidence_id_text(evidence_ids),
            family_0_group=group,
            family_1_group=group,
            family_2_group="Image" if group == "XML" else "Other",
        ),
        schema=None,
    )


def _evidence_id_text(evidence_ids: tuple[str, ...]) -> str:
    return (evidence_ids or (ZISRAW_XML_PROCESS_SOURCE,))[0]
