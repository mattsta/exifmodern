"""GIMP XCF transaction planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree

from exifmodern.formats.gimp.image_transaction_plan import (
    GIMP_EVIDENCE_ANCHORS,
    GIMP_PARASITE_PROCESS_SOURCE,
    GIMP_PARASITE_TABLE_SOURCE,
    GimpEvidenceAnchor,
    GimpImageTransactionPlan,
    GimpParasitePlan,
    GimpRewriteRequest,
    build_gimp_image_transaction_plan,
    resolve_gimp_evidence,
)
from exifmodern.formats.icc.reader import parse_icc_header_tags, parse_icc_profile_tags
from exifmodern.formats.tiff.process_tiff import ProcessTiffTag, process_tiff_payload
from exifmodern.formats.xmp.reader import decode_xmp_packet, parse_xmp_packet
from exifmodern.json_types import JsonArray, JsonObject, JsonValue
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = (
    "GimpImageTransactionPlan",
    "GimpRewriteRequest",
    "build_gimp_image_transaction_plan",
    "build_gimp_read_graph",
    "invoke_gimp",
)

type GimpNestedTagValue = str | int | float | bool | None | list[str]

GIMP_EXIF_PROCESS_TIFF_ANCHOR = GimpEvidenceAnchor(
    "gimp.parasite_table",
    "lib/Image/ExifTool/GIMP.pm",
    112,
    121,
    "GIMP.pm exif-data ProcessTIFF parasite route",
    "EXIF parasite payloads route to ProcessTIFF after the six-byte Exif header.",
)
GIMP_XMP_PROCESS_ANCHOR = GimpEvidenceAnchor(
    "gimp.parasite_table",
    "lib/Image/ExifTool/GIMP.pm",
    139,
    149,
    "GIMP.pm XMP parasite routes",
    "GIMP metadata parasites route to XMP/XML processing.",
)
GIMP_ICC_PROCESS_ANCHOR = GimpEvidenceAnchor(
    "gimp.parasite_table",
    "lib/Image/ExifTool/GIMP.pm",
    129,
    135,
    "GIMP.pm ICC parasite routes",
    "The GIMP parasite table routes ICC profile payloads to ICC_Profile::Main.",
)


def build_gimp_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_gimp_image_transaction_plan(data)
    diagnostics: list[str] = [f"GIMP package-local reader status: {plan.status}"]
    diagnostics.extend(
        f"GIMP package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = []
    if plan.status == "planned":
        for name, value in (
            ("FileType", "XCF"),
            ("FileTypeExtension", "xcf"),
            ("MIMEType", "image/x-xcf"),
            ("ExifByteOrder", "Big-endian (Motorola, MM)"),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_provenance(
                        group="File",
                        table_name="Image::ExifTool::GIMP::Header",
                        tag_id=name,
                        references=resolve_gimp_evidence(plan.header_validation.evidence_ids),
                    ),
                    schema=None,
                )
            )
    if plan.header_validation.version_number is not None:
        tags.append(
            ReadTag(
                name="XCFVersion",
                value=_read_value(plan.header_validation.version_number),
                provenance=_provenance(
                    group="GIMP",
                    table_name="Image::ExifTool::GIMP::Header",
                    tag_id="9",
                    references=resolve_gimp_evidence(plan.header_validation.evidence_ids),
                ),
                schema=None,
            )
        )
    geometry = plan.image_geometry
    geometry_specs: tuple[tuple[str, str, str | int | None], ...] = (
        ("ImageWidth", "14", geometry.image_width),
        ("ImageHeight", "18", geometry.image_height),
        ("ColorMode", "22", geometry.base_type_name),
    )
    for name, tag_id, geometry_value in geometry_specs:
        if geometry_value is None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(geometry_value),
                provenance=_provenance(
                    group="GIMP",
                    table_name="Image::ExifTool::GIMP::Header",
                    tag_id=tag_id,
                    references=resolve_gimp_evidence(geometry.evidence_ids),
                ),
                schema=None,
            )
        )
    for prop in plan.image_properties:
        if prop.name == "Parasites":
            continue
        if prop.name == "Resolution" and prop.float_values is not None:
            for name, tag_id, resolution_value in (
                ("XResolution", "0", prop.float_values[0]),
                ("YResolution", "1", prop.float_values[1]),
            ):
                rendered_resolution: int | float = (
                    int(resolution_value) if resolution_value.is_integer() else resolution_value
                )
                tags.append(
                    ReadTag(
                        name=name,
                        value=_read_value(rendered_resolution),
                        provenance=_provenance(
                            group="GIMP",
                            table_name="Image::ExifTool::GIMP::Resolution",
                            tag_id=tag_id,
                            references=resolve_gimp_evidence(prop.evidence_ids),
                            duplicate_instance_ordinal=prop.index,
                        ),
                        schema=None,
                    )
                )
            continue
        rendered_value = (
            prop.print_value
            if prop.print_value is not None
            else (prop.numeric_value if prop.numeric_value is not None else "")
        )
        tags.append(
            ReadTag(
                name=prop.name,
                value=_read_value(rendered_value),
                provenance=_provenance(
                    group="GIMP",
                    table_name="Image::ExifTool::GIMP::Property",
                    tag_id=str(prop.tag),
                    references=resolve_gimp_evidence(prop.evidence_ids),
                    duplicate_instance_ordinal=prop.index,
                ),
                schema=None,
            )
        )
    for parasite in plan.parasites:
        tags.extend(_nested_parasite_tags(parasite, data))
    tags.extend(_gimp_composite_tags(tags, resolve_gimp_evidence(geometry.evidence_ids)))
    return _graph(source_file, tags, diagnostics)


def _gimp_composite_tags(
    tags: list[ReadTag],
    evidence_anchors: tuple[GimpEvidenceAnchor, ...],
) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    width = _gimp_numeric_tag_value(tags, "ImageWidth")
    height = _gimp_numeric_tag_value(tags, "ImageHeight")
    if width is None or height is None:
        return []
    pixels = width * height / 1_000_000
    return [
        ReadTag(
            name="ImageSize",
            value=_read_value(f"{int(width)}x{int(height)}"),
            provenance=_provenance(
                group="Composite",
                table_name="Image::ExifTool::Exif::Composite",
                tag_id="Exif-ImageSize",
                references=evidence_anchors,
            ),
            schema=None,
        ),
        ReadTag(
            name="Megapixels",
            value=_read_value(round(pixels, 1 if pixels >= 1 else 6)),
            provenance=_provenance(
                group="Composite",
                table_name="Image::ExifTool::Exif::Composite",
                tag_id="Exif-Megapixels",
                references=evidence_anchors,
            ),
            schema=None,
        ),
    ]


def _gimp_numeric_tag_value(tags: list[ReadTag], name: str) -> float | None:
    for tag in tags:
        if tag.name != name:
            continue
        value = tag.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)
    return None


def _nested_parasite_tags(parasite: GimpParasitePlan, data: bytes) -> list[ReadTag]:
    if parasite.data_range is None:
        return []
    start, end = parasite.data_range
    payload = data[start:end]
    if parasite.route in {"route_exif", "route_jpeg_exif"}:
        return _nested_tiff_tags(parasite, payload[parasite.processor_start_offset :])
    if parasite.route == "route_icc_profile":
        return _nested_icc_tags(parasite, payload)
    if parasite.route in {"route_xmp", "route_xml"}:
        return _nested_xmp_tags(parasite, payload[parasite.processor_start_offset :])
    return []


def _nested_tiff_tags(parasite: GimpParasitePlan, payload: bytes) -> list[ReadTag]:
    result = process_tiff_payload(
        payload,
        tuple(
            reference.symbol
            for reference in _nested_evidence_anchors(parasite, (GIMP_EXIF_PROCESS_TIFF_ANCHOR,))
        ),
    )
    return _nested_tiff_read_tags(parasite, result.tags)


def _nested_tiff_read_tags(
    parasite: GimpParasitePlan,
    tiff_tags: tuple[ProcessTiffTag, ...],
) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    tags: list[ReadTag] = []
    for tag in tiff_tags:
        tags.append(
            ReadTag(
                name=tag.name,
                value=_read_value(tag.value),
                provenance=_provenance(
                    group=tag.group,
                    table_name=tag.source_table,
                    tag_id=tag.tag_id,
                    references=tag.evidence_ids,
                    duplicate_instance_ordinal=parasite.index,
                ),
                schema=None,
            )
        )
    return tags


def _nested_icc_tags(parasite: GimpParasitePlan, payload: bytes) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    try:
        values = {**parse_icc_header_tags(payload), **parse_icc_profile_tags(payload)}
    except ValueError:
        return []
    tags: list[ReadTag] = []
    for name, value in values.items():
        tag_value = _nested_json_value(value)
        if tag_value is None and value is not None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(tag_value),
                provenance=_provenance(
                    group=_icc_group_name(name),
                    table_name=_icc_table_name(name),
                    tag_id=name,
                    references=_nested_evidence_anchors(parasite, (GIMP_ICC_PROCESS_ANCHOR,)),
                    duplicate_instance_ordinal=parasite.index,
                ),
                schema=None,
            )
        )
    return tags


def _nested_xmp_tags(parasite: GimpParasitePlan, payload: bytes) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    try:
        values_by_group = parse_xmp_packet(payload)
    except ValueError, SyntaxError:
        return []
    _merge_gimp_xmp_resource_attributes(values_by_group, payload)
    tags: list[ReadTag] = []
    for group, values in values_by_group.items():
        for name, value in values.items():
            if group == "XMP-rdf" and name == "About":
                continue
            tag_value = _nested_json_value(value)
            if tag_value is None and value is not None:
                continue
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(tag_value),
                    provenance=_provenance(
                        group=group,
                        table_name=_xmp_table_name(group),
                        tag_id=name,
                        references=_nested_evidence_anchors(parasite, (GIMP_XMP_PROCESS_ANCHOR,)),
                        duplicate_instance_ordinal=parasite.index,
                    ),
                    schema=None,
                )
            )
    return tags


def _merge_gimp_xmp_resource_attributes(
    values_by_group: dict[str, JsonObject],
    payload: bytes,
) -> None:
    """Promote source-backed XMP resource attributes not surfaced as text nodes."""

    try:
        root = ElementTree.fromstring(decode_xmp_packet(payload))
    except ElementTree.ParseError:
        return
    rights_group = values_by_group.setdefault("XMP-xmpRights", {})
    for element in root.iter():
        if element.tag != "{http://ns.adobe.com/xap/1.0/rights/}WebStatement":
            continue
        resource = element.attrib.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource")
        if resource is None:
            resource = element.attrib.get("resource")
        if resource is not None:
            rights_group.setdefault("WebStatement", resource)


def _nested_json_value(value: JsonValue) -> GimpNestedTagValue | None:
    if isinstance(value, dict):
        return None
    if isinstance(value, list):
        return _json_string_array_or_none(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return None


def _json_string_array_or_none(value: JsonArray) -> list[str] | None:
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        strings.append(item)
    return strings


def _nested_evidence_anchors(
    parasite: GimpParasitePlan,
    extra_anchors: tuple[GimpEvidenceAnchor, ...],
) -> tuple[GimpEvidenceAnchor, ...]:
    return _unique_evidence_anchors(
        (
            *resolve_gimp_evidence(parasite.evidence_ids),
            GIMP_EVIDENCE_ANCHORS[GIMP_PARASITE_TABLE_SOURCE],
            GIMP_EVIDENCE_ANCHORS[GIMP_PARASITE_PROCESS_SOURCE],
            *extra_anchors,
        )
    )


def _icc_table_name(name: str) -> str:
    if name in {
        "ProfileCopyright",
        "ProfileDescription",
        "MediaWhitePoint",
        "MediaBlackPoint",
        "RedTRC",
        "GreenTRC",
        "BlueTRC",
        "RedMatrixColumn",
        "GreenMatrixColumn",
        "BlueMatrixColumn",
    }:
        return "Image::ExifTool::ICC_Profile::Main"
    return "Image::ExifTool::ICC_Profile::Header"


def _icc_group_name(name: str) -> str:
    if _icc_table_name(name) == "Image::ExifTool::ICC_Profile::Header":
        return "ICC-header"
    return "ICC_Profile"


def _xmp_table_name(group: str) -> str:
    if group.startswith("XMP-"):
        return f"Image::ExifTool::XMP::{group[4:]}"
    return "Image::ExifTool::XMP::Main"


def _unique_evidence_anchors(
    evidence_anchors: tuple[GimpEvidenceAnchor, ...],
) -> tuple[GimpEvidenceAnchor, ...]:
    unique: list[GimpEvidenceAnchor] = []
    seen: set[tuple[str, int, int, str]] = set()
    for anchor in evidence_anchors:
        key = (anchor.path, anchor.line_start, anchor.line_end, anchor.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(anchor)
    return tuple(unique)


def invoke_gimp(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_gimp_exiftool_properties(path)
    return build_gimp_read_graph(data, source_file)


def _read_gimp_exiftool_properties(path: Path) -> bytes:
    with path.open("rb") as file:
        data = bytearray(file.read(26))
        if len(data) < 26:
            return bytes(data)
        for _ in range(4096):
            prop_header = file.read(8)
            if len(prop_header) != 8:
                break
            data.extend(prop_header)
            prop_type = int.from_bytes(prop_header[:4], "big")
            prop_size = int.from_bytes(prop_header[4:8], "big")
            if prop_type == 0:
                break
            if prop_size > 16 * 1024 * 1024:
                break
            data.extend(file.read(prop_size))
        return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="gimp",
        builder_ref="exifmodern.formats.gimp:invoke_gimp",
        patterns=(Pattern(0, b"gimp xcf "),),
    ),
)
