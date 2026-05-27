"""Photoshop image resource readers and write-surface plans."""

from hashlib import md5
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO
from xml.etree import ElementTree

from exifmodern.formats.iptc.reader import parse_iptc_application_record
from exifmodern.formats.photoshop.image_resources import PhotoshopImageResourceBlock
from exifmodern.formats.photoshop.nested_metadata_plan import (
    PHOTOMECHANIC_TRAILER_SOURCE_ID,
    PHOTOSHOP_RESOURCE_ID_EXIF_INFO,
    PHOTOSHOP_RESOURCE_ID_ICC_PROFILE,
    PHOTOSHOP_RESOURCE_ID_IPTC_DATA,
    PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST,
    PHOTOSHOP_RESOURCE_ID_XMP,
)
from exifmodern.formats.photoshop.photomechanic import (
    PHOTOMECHANIC_SOFT_EDIT_SOURCE_ID,
    parse_photomechanic_trailer_tags,
)
from exifmodern.formats.photoshop.reader import (
    photoshop_print_scale_tags,
    photoshop_quality_tags,
    photoshop_resolution_tags,
    photoshop_resource_tags,
    photoshop_slice_tags,
    photoshop_version_tags,
)
from exifmodern.formats.photoshop.section_boundary_plan import (
    PSD_HEADER_LENGTH,
    PhotoshopPSDHeader,
    PhotoshopPSDSectionBoundaryError,
    PhotoshopPSDSectionBoundaryPlan,
    parse_photoshop_psd_header,
    plan_photoshop_psd_section_boundaries,
)
from exifmodern.formats.photoshop.write_plan import (
    PhotoshopPSDWriteClassification,
    PhotoshopPSDWriteSurfaceClassification,
    classify_photoshop_psd_golden_request_file,
    classify_photoshop_psd_write_args,
)
from exifmodern.formats.tiff.primitives import inspect_ifd0, parse_tiff_header
from exifmodern.formats.xmp.reader import decode_xmp_packet, parse_xmp_packet
from exifmodern.json_types import JsonArray, JsonObject, JsonValue, json_string_array_or_none
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = [
    "PhotoshopPSDWriteClassification",
    "PhotoshopPSDWriteSurfaceClassification",
    "build_photoshop_read_graph",
    "classify_photoshop_psd_golden_request_file",
    "classify_photoshop_psd_write_args",
    "invoke_photoshop",
]

_PHOTOSHOP_HEADER_TABLE = "Image::ExifTool::Photoshop::Header"
_PHOTOSHOP_MAIN_TABLE = "Image::ExifTool::Photoshop::Main"
_PHOTOSHOP_IMAGE_DATA_TABLE = "Image::ExifTool::Photoshop::ImageData"
_FILE_TABLE = "Image::ExifTool::File"
_IPTC_TABLE = "Image::ExifTool::IPTC::ApplicationRecord"
_ICC_HEADER_TABLE = "Image::ExifTool::ICC_Profile::Header"
_ICC_MAIN_TABLE = "Image::ExifTool::ICC_Profile::Main"
_EXIF_MAIN_TABLE = "Image::ExifTool::Exif::Main"
_EXIF_IFD_TABLE = "Image::ExifTool::Exif::ExifIFD"
_GPS_TABLE = "Image::ExifTool::GPS::Main"
_PHOTOMECHANIC_TABLE = "Image::ExifTool::PhotoMechanic::SoftEdit"
_PHOTOSHOP_COLOR_MODES = {
    0: "Bitmap",
    1: "Grayscale",
    2: "Indexed",
    3: "RGB",
    4: "CMYK",
    7: "Multichannel",
    8: "Duotone",
    9: "Lab",
}
PHOTOSHOP_FILE_TYPE_SOURCE_ID = "photoshop.reader.file_type"
_PHOTOSHOP_FILE_TYPE_SOURCE = PHOTOSHOP_FILE_TYPE_SOURCE_ID
_PHOTOMECHANIC_SOFT_EDIT_SOURCE = PHOTOMECHANIC_SOFT_EDIT_SOURCE_ID


def build_photoshop_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph

    diagnostics: list[str] = []
    tags: list[ReadTag] = []
    try:
        header = _parse_photoshop_header(data)
    except PhotoshopPSDSectionBoundaryError as exc:
        diagnostics.append(f"Photoshop package-local reader error: {exc}")
        return _graph(source_file, tags, diagnostics)
    header_tags = _header_tags(header)
    tags.extend(header_tags)
    if header.version == 2:
        diagnostics.append("Photoshop package-local reader note: PSB section parsing deferred.")
        return _graph(source_file, tags, diagnostics)
    try:
        plan = plan_photoshop_psd_section_boundaries(data)
    except PhotoshopPSDSectionBoundaryError as exc:
        diagnostics.append(f"Photoshop package-local reader error: {exc}")
        return _graph(source_file, tags, diagnostics)
    tags[0:0] = _file_type_tags(header)
    compression_tag = _photoshop_tag(
        "Compression",
        "0",
        _photoshop_compression(plan.image_data_section.compression or 0),
        _PHOTOSHOP_IMAGE_DATA_TABLE,
        plan.source_reference_ids,
    )
    tags.append(compression_tag)
    _add_psd_image_resource_tags(tags, diagnostics, plan)
    _add_photomechanic_trailer_tags(tags, diagnostics, data, plan)
    _add_psd_derived_tags(tags, header, data, plan)
    tags[:] = _photoshop_exiftool_order(tags)
    return _graph(source_file, tags, diagnostics)


def _add_psd_derived_tags(
    tags: list[ReadTag],
    header: PhotoshopPSDHeader,
    data: bytes,
    plan: PhotoshopPSDSectionBoundaryPlan,
) -> None:
    layer_section = plan.layer_and_mask_info_section
    layer_count = _psd_layer_count(data[layer_section.data_start : layer_section.data_end])
    if layer_count is not None:
        tags.append(
            _photoshop_tag(
                "LayerCount",
                "LayerCount",
                layer_count,
                _PHOTOSHOP_MAIN_TABLE,
                plan.source_reference_ids,
            )
        )
    tags.append(
        _photoshop_tag(
            "ImageSize",
            "ImageSize",
            f"{header.width}x{header.height}",
            "Image::ExifTool::Composite",
            plan.source_reference_ids,
            group="Composite",
        )
    )
    tags.append(
        _photoshop_tag(
            "Megapixels",
            "Megapixels",
            _psd_megapixels(header.width, header.height),
            "Image::ExifTool::Composite",
            plan.source_reference_ids,
            group="Composite",
        )
    )


def _psd_layer_count(layer_and_mask_data: bytes) -> int | None:
    if len(layer_and_mask_data) < 4:
        return None
    layer_info_length = int.from_bytes(layer_and_mask_data[:4], "big")
    if layer_info_length == 0:
        return 0
    if len(layer_and_mask_data) < 6:
        return None
    count = int.from_bytes(layer_and_mask_data[4:6], "big", signed=True)
    return abs(count)


def _psd_megapixels(width: int, height: int) -> str:
    value = width * height / 1_000_000
    return f"{value:.3g}"


def _photoshop_exiftool_order(tags: list[ReadTag]) -> list[ReadTag]:
    return sorted(tags, key=_photoshop_exiftool_order_key)


def _photoshop_exiftool_order_key(tag: ReadTag) -> tuple[int, int]:
    group = tag.provenance.group
    name = tag.name
    ordered_names = {
        "File": {
            "FileType": 0,
            "FileTypeExtension": 1,
            "MIMEType": 2,
            "CurrentIPTCDigest": 3,
            "ExifByteOrder": 4,
        },
        "Photoshop": {
            "NumChannels": 0,
            "ImageHeight": 1,
            "ImageWidth": 2,
            "BitDepth": 3,
            "ColorMode": 4,
            "IPTCDigest": 5,
            "LayerCount": 200,
            "Compression": 201,
        },
        "Composite": {"ImageSize": 0, "Megapixels": 1},
    }
    group_ranks = {
        "File": 0,
        "Photoshop": 1,
        "IPTC": 2,
        "XMP-x": 3,
        "XMP-rdf": 4,
        "XMP-photoshop": 5,
        "XMP-xmpBJ": 6,
        "XMP-xmpMM": 7,
        "XMP-xmpRights": 8,
        "XMP-dc": 9,
        "ICC-header": 10,
        "ICC_Profile": 11,
        "IFD0": 12,
        "ExifIFD": 13,
        "IFD1": 14,
        "PhotoMechanic": 15,
        "Composite": 16,
    }
    return group_ranks.get(group, 100), ordered_names.get(group, {}).get(name, 100)


def _parse_photoshop_header(data: bytes) -> PhotoshopPSDHeader:
    if len(data) < PSD_HEADER_LENGTH + 4:
        raise PhotoshopPSDSectionBoundaryError("Truncated Photoshop PSD header.")
    if data[:4] != b"8BPS":
        raise PhotoshopPSDSectionBoundaryError("Not a valid Photoshop PSD file.")
    version = int.from_bytes(data[4:6], "big")
    if version == 1:
        return parse_photoshop_psd_header(data)
    if version != 2:
        raise PhotoshopPSDSectionBoundaryError("Not a valid Photoshop PSD version.")
    return PhotoshopPSDHeader(
        signature=data[:4],
        version=version,
        channels=int.from_bytes(data[12:14], "big"),
        height=int.from_bytes(data[14:18], "big"),
        width=int.from_bytes(data[18:22], "big"),
        bit_depth=int.from_bytes(data[22:24], "big"),
        color_mode=int.from_bytes(data[24:26], "big"),
    )


def _header_tags(header: PhotoshopPSDHeader) -> list[ReadTag]:
    return [
        _photoshop_tag("NumChannels", "6", header.channels, _PHOTOSHOP_HEADER_TABLE, ()),
        _photoshop_tag("ImageHeight", "7", header.height, _PHOTOSHOP_HEADER_TABLE, ()),
        _photoshop_tag("ImageWidth", "9", header.width, _PHOTOSHOP_HEADER_TABLE, ()),
        _photoshop_tag("BitDepth", "11", header.bit_depth, _PHOTOSHOP_HEADER_TABLE, ()),
        _photoshop_tag(
            "ColorMode",
            "12",
            _PHOTOSHOP_COLOR_MODES.get(header.color_mode, header.color_mode),
            _PHOTOSHOP_HEADER_TABLE,
            (),
        ),
    ]


def _photoshop_tag(
    name: str,
    tag_id: str,
    value: str | int | float | bool | None | list[str],
    table_name: str,
    source_reference_ids: tuple[str, ...],
    *,
    group: str = "Photoshop",
) -> ReadTag:
    from exifmodern.dispatch_helpers import _family_2_group, _read_value
    from exifmodern.read_graph import ReadTag, TagProvenance

    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=TagProvenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            source=_photoshop_source_text(source_reference_ids),
            family_0_group=group,
            family_1_group=group,
            family_2_group=_family_2_group(group),
        ),
        schema=None,
    )


def _photoshop_source_text(source_reference_ids: tuple[str, ...]) -> str:
    if not source_reference_ids:
        return "package-local-reader-plan"
    source_id = source_reference_ids[0]
    return f"{source_id}:0-0:{source_id}"


def _file_type_tags(header: PhotoshopPSDHeader) -> list[ReadTag]:
    if header.version == 2:
        values = {
            "FileType": "PSB",
            "FileTypeExtension": "psb",
            "MIMEType": "application/vnd.adobe.photoshop",
        }
    else:
        values = {
            "FileType": "PSD",
            "FileTypeExtension": "psd",
            "MIMEType": "application/vnd.adobe.photoshop",
        }
    return [
        _photoshop_tag(
            name,
            name,
            value,
            _FILE_TABLE,
            (_PHOTOSHOP_FILE_TYPE_SOURCE,),
            group="File",
        )
        for name, value in values.items()
    ]


def _add_psd_image_resource_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    plan: PhotoshopPSDSectionBoundaryPlan,
) -> None:
    from exifmodern.formats.icc.reader import parse_icc_header_tags, parse_icc_profile_tags

    for resource in plan.image_resource_blocks:
        if resource.resource_id == PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST:
            tags.append(
                _photoshop_tag(
                    "IPTCDigest",
                    "0x0425",
                    resource.data.hex(),
                    _PHOTOSHOP_MAIN_TABLE,
                    plan.source_reference_ids,
                )
            )
        if resource.resource_id == PHOTOSHOP_RESOURCE_ID_IPTC_DATA:
            tags.append(
                _photoshop_tag(
                    "CurrentIPTCDigest",
                    "CurrentIPTCDigest",
                    md5(resource.data, usedforsecurity=False).hexdigest(),
                    _PHOTOSHOP_MAIN_TABLE,
                    plan.source_reference_ids,
                    group="File",
                )
            )
            _add_json_values(
                tags,
                parse_iptc_application_record(resource.data),
                group="IPTC",
                table_name=_IPTC_TABLE,
                source="IPTC",
                source_reference_ids=plan.source_reference_ids,
            )
        elif resource.resource_id == PHOTOSHOP_RESOURCE_ID_XMP:
            try:
                xmp_groups = parse_xmp_packet(resource.data)
            except (SyntaxError, ValueError) as exc:
                diagnostics.append(f"Photoshop nested XMP diagnostic: {exc}")
                continue
            xmp_groups["XMP-x"].update(_xmp_packet_wrapper_tags(resource.data))
            for group, values in xmp_groups.items():
                for name, value in values.items():
                    tag_value = _json_scalar_or_string_list(value)
                    if tag_value is None:
                        continue
                    tags.append(
                        _photoshop_tag(
                            name,
                            name,
                            tag_value,
                            _xmp_table_name(group),
                            plan.source_reference_ids,
                            group=group,
                        )
                    )
        elif resource.resource_id == PHOTOSHOP_RESOURCE_ID_ICC_PROFILE:
            try:
                icc_values = {
                    **parse_icc_header_tags(resource.data),
                    **parse_icc_profile_tags(resource.data),
                }
            except ValueError as exc:
                diagnostics.append(f"Photoshop nested ICC_Profile diagnostic: {exc}")
                continue
            for name, value in icc_values.items():
                tag_value = _json_scalar_or_string_list(value)
                if tag_value is None:
                    continue
                tags.append(
                    _photoshop_tag(
                        name,
                        name,
                        tag_value,
                        _icc_table_name(name),
                        plan.source_reference_ids,
                        group=_icc_group_name(name),
                    )
                )
        elif resource.resource_id == PHOTOSHOP_RESOURCE_ID_EXIF_INFO:
            try:
                header = parse_tiff_header(resource.data)
                inspection = inspect_ifd0(resource.data)
            except ValueError as exc:
                diagnostics.append(f"Photoshop nested EXIFInfo diagnostic: {exc}")
                continue
            tags.append(
                _photoshop_tag(
                    "ExifByteOrder",
                    "ExifByteOrder",
                    header.byte_order,
                    _EXIF_MAIN_TABLE,
                    plan.source_reference_ids,
                    group="File",
                )
            )
            _add_embedded_tiff_values(tags, inspection, plan.source_reference_ids)
        else:
            _add_photoshop_resource_specific_tags(tags, resource, plan.source_reference_ids)


def _add_photomechanic_trailer_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    data: bytes,
    plan: PhotoshopPSDSectionBoundaryPlan,
) -> None:
    trailer = plan.trailer_section
    if trailer is None:
        return
    try:
        values = parse_photomechanic_trailer_tags(data[trailer.data_start : trailer.data_end])
    except ValueError as exc:
        diagnostics.append(f"Photoshop PhotoMechanic trailer diagnostic: {exc}")
        return
    rendered_values: JsonObject = dict(values)
    _add_json_values(
        tags,
        rendered_values,
        group="PhotoMechanic",
        table_name=_PHOTOMECHANIC_TABLE,
        source="PhotoMechanic",
        source_reference_ids=(
            PHOTOMECHANIC_TRAILER_SOURCE_ID,
            _PHOTOMECHANIC_SOFT_EDIT_SOURCE,
            *plan.source_reference_ids,
        ),
    )


def _xmp_packet_wrapper_tags(packet: bytes) -> JsonObject:
    try:
        root = ElementTree.fromstring(decode_xmp_packet(packet))
    except ElementTree.ParseError:
        return {}
    for attribute_name, toolkit in root.attrib.items():
        local_name = attribute_name.rsplit("}", 1)[-1]
        if local_name in {"xmptk", "xaptk"}:
            return {"XMPToolkit": toolkit}
    return {}


def _add_photoshop_resource_specific_tags(
    tags: list[ReadTag],
    resource: PhotoshopImageResourceBlock,
    source_reference_ids: tuple[str, ...],
) -> None:
    values: JsonObject = {}
    values.update(photoshop_resource_tags(resource))
    if resource.resource_id == 0x03ED:
        values.update(photoshop_resolution_tags(resource.data))
    elif resource.resource_id == 0x0406:
        values.update(photoshop_quality_tags(resource.data))
    elif resource.resource_id == 0x041A:
        values.update(photoshop_slice_tags(resource.data))
    elif resource.resource_id == 0x0421:
        values.update(photoshop_version_tags(resource.data))
    elif resource.resource_id == 0x0426:
        values.update(photoshop_print_scale_tags(resource.data))
    _add_json_values(
        tags,
        values,
        group="Photoshop",
        table_name=_PHOTOSHOP_MAIN_TABLE,
        source="Photoshop",
        source_reference_ids=source_reference_ids,
    )


def _add_embedded_tiff_values(
    tags: list[ReadTag],
    inspection: JsonObject,
    source_reference_ids: tuple[str, ...],
) -> None:
    for group, key, table_name in (
        ("IFD0", "ifd0_values", _EXIF_MAIN_TABLE),
        ("ExifIFD", "exif_ifd_values", _EXIF_IFD_TABLE),
        ("GPS", "gps_ifd_values", _GPS_TABLE),
        ("IFD1", "ifd1_values", _EXIF_MAIN_TABLE),
    ):
        values = inspection.get(key)
        if not isinstance(values, dict):
            continue
        _add_json_values(
            tags,
            values,
            group=group,
            table_name=table_name,
            source="EXIFInfo",
            source_reference_ids=source_reference_ids,
        )


def _add_json_values(
    tags: list[ReadTag],
    values: JsonObject,
    *,
    group: str,
    table_name: str,
    source: str,
    source_reference_ids: tuple[str, ...],
) -> None:
    for name, value in values.items():
        if name.endswith("IFDPointer"):
            continue
        tag_value = _json_scalar_or_string_list(value)
        if tag_value is None:
            continue
        tags.append(
            _photoshop_tag(
                name,
                name if source != "Photoshop" else _photoshop_tag_id(name),
                tag_value,
                table_name,
                source_reference_ids,
                group=group,
            )
        )


def _json_scalar_or_string_list(value: JsonValue) -> str | int | float | bool | None | list[str]:
    if isinstance(value, dict):
        return None
    if isinstance(value, list):
        return _json_string_array_or_none(value)
    return value


def _json_string_array_or_none(value: JsonArray) -> list[str] | None:
    return json_string_array_or_none(value)


def _icc_table_name(name: str) -> str:
    from exifmodern.formats.icc.reader import icc_table_name_for_tag

    return icc_table_name_for_tag(name)


def _icc_group_name(name: str) -> str:
    from exifmodern.formats.icc.reader import icc_group_name_for_tag

    return icc_group_name_for_tag(name)


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
        "PhotoshopQuality": "0",
        "PhotoshopFormat": "2",
    }.get(name, name)


def _photoshop_compression(value: int) -> str | int:
    return {
        0: "Uncompressed",
        1: "RLE",
        2: "ZIP without prediction",
        3: "ZIP with prediction",
    }.get(value, value)


def _read_exact(file: BinaryIO, size: int) -> bytes:
    data = file.read(size)
    if len(data) != size:
        raise PhotoshopPSDSectionBoundaryError("Truncated Photoshop PSD section.")
    return data


def _materialize_photoshop_public_read_metadata(path: Path) -> bytes:
    from exifmodern.formats.photoshop.section_boundary_plan import (
        PHOTOMECHANIC_TRAILER_FOOTER_LENGTH,
        PHOTOMECHANIC_TRAILER_FOOTER_SIGNATURE,
    )

    size = path.stat().st_size
    with path.open("rb") as file:
        header_and_color_length = _read_exact(file, PSD_HEADER_LENGTH + 4)
        if header_and_color_length[:4] != b"8BPS":
            return header_and_color_length
        version = int.from_bytes(header_and_color_length[4:6], "big")
        if version == 2:
            return header_and_color_length
        color_length = int.from_bytes(header_and_color_length[PSD_HEADER_LENGTH:30], "big")
        color_payload = _read_exact(file, color_length)
        resource_length = int.from_bytes(_read_exact(file, 4), "big")
        resource_payload = _read_exact(file, resource_length)
        layer_length = int.from_bytes(_read_exact(file, 4), "big")
        layer_payload = _read_exact(file, layer_length)
        image_compression = _read_exact(file, 2)
        trailer = b""
        if size >= PHOTOMECHANIC_TRAILER_FOOTER_LENGTH:
            file.seek(size - PHOTOMECHANIC_TRAILER_FOOTER_LENGTH)
            footer = _read_exact(file, PHOTOMECHANIC_TRAILER_FOOTER_LENGTH)
            if footer[4:] == PHOTOMECHANIC_TRAILER_FOOTER_SIGNATURE:
                payload_length = int.from_bytes(footer[:4], "big")
                trailer_start = size - PHOTOMECHANIC_TRAILER_FOOTER_LENGTH - payload_length
                minimum_trailer_start = (
                    len(header_and_color_length)
                    + color_length
                    + 4
                    + resource_length
                    + 4
                    + layer_length
                    + 2
                )
                if payload_length < 0x80000000 and trailer_start >= minimum_trailer_start:
                    file.seek(trailer_start)
                    trailer = _read_exact(file, payload_length) + footer
    return b"".join(
        (
            header_and_color_length,
            color_payload,
            resource_length.to_bytes(4, "big"),
            resource_payload,
            layer_length.to_bytes(4, "big"),
            layer_payload,
            image_compression,
            trailer,
        )
    )


def invoke_photoshop(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_photoshop_read_graph(
        _materialize_photoshop_public_read_metadata(path),
        source_file,
    )


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="photoshop/psd",
        builder_ref="exifmodern.formats.photoshop:invoke_photoshop",
        patterns=(Pattern(0, b"8BPS\x00\x01"),),
    ),
    Signature(
        format_id="photoshop/psb",
        builder_ref="exifmodern.formats.photoshop:invoke_photoshop",
        patterns=(Pattern(0, b"8BPS\x00\x02"),),
    ),
)
