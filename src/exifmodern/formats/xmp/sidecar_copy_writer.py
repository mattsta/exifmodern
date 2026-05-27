"""Package-local XMP sidecar tagsFromFile copy writer."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Literal

from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION_TEXT
from exifmodern.file_transaction import (
    BackupPolicy,
    FileWriteTransactionResult,
    write_bytes_in_place_transactionally,
    write_bytes_transactionally,
)
from exifmodern.formats.xmp.copy_from_file_plan import (
    XMP_TABLE_SOURCE,
    XMP_WRITER_SOURCE,
    XmpCopyFromFileDiagnostic,
    XmpCopyFromFilePlan,
    XmpDestinationAssignment,
    materialize_xmp_copy_from_file_plan,
    transform_xmp_packet_for_copy,
)
from exifmodern.formats.xmp.property_write import (
    XmpPropertySpec,
    XmpPropertyValueShape,
    XmpPropertyWritePlan,
    XmpRdfContainer,
    XmpTextListPropertyWrite,
    XmpTextPropertyWrite,
)

type XmpSidecarCopyValueShape = Literal["text", "seq", "alt"]

XMP_TOOLKIT_TEXT = f"Image::ExifTool {EXIFTOOL_COMPATIBILITY_VERSION_TEXT}"
XMP_TOOLKIT_BYTES = XMP_TOOLKIT_TEXT.encode("utf-8")

EMPTY_XMP_PACKET = (
    b"<?xpacket begin='\xef\xbb\xbf' id='W5M0MpCehiHzreSzNTczkc9d'?>\n"
    b"<x:xmpmeta xmlns:x='adobe:ns:meta/' x:xmptk='" + XMP_TOOLKIT_BYTES + b"'>\n"
    b"<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>\n"
    b" <rdf:Description rdf:about=''/>\n"
    b"</rdf:RDF>\n"
    b"</x:xmpmeta>\n"
    b"<?xpacket end='w'?>"
)


@dataclass(frozen=True)
class XmpSidecarCopyRewriteResult:
    data: bytes
    changed: bool
    copied_xmp_properties: int
    diagnostic_count: int
    diagnostics: tuple[XmpCopyFromFileDiagnostic, ...]
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class XmpSidecarCopyPropertySpec:
    property_name: str
    namespace_prefix: str
    namespace_uri: str
    element_name: str
    value_shape: XmpSidecarCopyValueShape = "text"


SIDECAR_COPY_PROPERTY_SPECS = (
    XmpSidecarCopyPropertySpec("XMP-tiff:Make", "tiff", "http://ns.adobe.com/tiff/1.0/", "Make"),
    XmpSidecarCopyPropertySpec(
        "XMP-tiff:Model",
        "tiff",
        "http://ns.adobe.com/tiff/1.0/",
        "Model",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-tiff:Orientation",
        "tiff",
        "http://ns.adobe.com/tiff/1.0/",
        "Orientation",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-tiff:XResolution",
        "tiff",
        "http://ns.adobe.com/tiff/1.0/",
        "XResolution",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-tiff:YResolution",
        "tiff",
        "http://ns.adobe.com/tiff/1.0/",
        "YResolution",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-tiff:ResolutionUnit",
        "tiff",
        "http://ns.adobe.com/tiff/1.0/",
        "ResolutionUnit",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-tiff:YCbCrPositioning",
        "tiff",
        "http://ns.adobe.com/tiff/1.0/",
        "YCbCrPositioning",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ExposureTime",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "ExposureTime",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:FNumber",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "FNumber",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ISO",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "ISOSpeedRatings",
        "seq",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ExifVersion",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "ExifVersion",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:DateTimeOriginal",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "DateTimeOriginal",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ComponentsConfiguration",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "ComponentsConfiguration",
        "seq",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:CompressedBitsPerPixel",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "CompressedBitsPerPixel",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ShutterSpeedValue",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "ShutterSpeedValue",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ApertureValue",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "ApertureValue",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ExposureCompensation",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "ExposureBiasValue",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:MaxApertureValue",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "MaxApertureValue",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:MeteringMode",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "MeteringMode",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:FocalLength",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "FocalLength",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSLatitude",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSLatitude",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSLongitude",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSLongitude",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSAltitudeRef",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSAltitudeRef",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSAltitude",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSAltitude",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSSatellites",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSSatellites",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSStatus",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSStatus",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSMeasureMode",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSMeasureMode",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSDOP",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSDOP",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSSpeedRef",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSSpeedRef",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSSpeed",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSSpeed",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSTrackRef",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSTrackRef",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSTrack",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSTrack",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSImgDirectionRef",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSImgDirectionRef",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSImgDirection",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSImgDirection",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSMapDatum",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSMapDatum",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSDestLatitude",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSDestLatitude",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSDestLongitude",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSDestLongitude",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSDestBearingRef",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSDestBearingRef",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSDestBearing",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSDestBearing",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSDestDistanceRef",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSDestDistanceRef",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSDestDistance",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSDestDistance",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSDifferential",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSDifferential",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:GPSHPositioningError",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "GPSHPositioningError",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:UserComment",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "UserComment",
        "alt",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:FlashpixVersion",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "FlashpixVersion",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ColorSpace",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "ColorSpace",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ExifImageWidth",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "PixelXDimension",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ExifImageHeight",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "PixelYDimension",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:FocalPlaneXResolution",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "FocalPlaneXResolution",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:FocalPlaneYResolution",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "FocalPlaneYResolution",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:FocalPlaneResolutionUnit",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "FocalPlaneResolutionUnit",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:SensingMethod",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "SensingMethod",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:FileSource",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "FileSource",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:CustomRendered",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "CustomRendered",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:ExposureMode",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "ExposureMode",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:WhiteBalance",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "WhiteBalance",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exif:SceneCaptureType",
        "exif",
        "http://ns.adobe.com/exif/1.0/",
        "SceneCaptureType",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-exifEX:InteropIndex",
        "exifEX",
        "http://cipa.jp/exif/1.0/",
        "InteroperabilityIndex",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-xmp:CreateDate",
        "xmp",
        "http://ns.adobe.com/xap/1.0/",
        "CreateDate",
    ),
    XmpSidecarCopyPropertySpec(
        "XMP-xmp:ModifyDate",
        "xmp",
        "http://ns.adobe.com/xap/1.0/",
        "ModifyDate",
    ),
)


def rewrite_xmp_sidecar_copy_from_file(
    source_path: Path,
    copy_plan: XmpCopyFromFilePlan,
    capability_audit: Path | None = None,
) -> XmpSidecarCopyRewriteResult:
    if copy_plan.strategy in {"copy_all_metadata_packet", "copy_xmp_writable_packet"}:
        data = transform_xmp_packet_for_copy(source_path.read_bytes(), copy_plan.packet_transform)
        return XmpSidecarCopyRewriteResult(
            data=data,
            changed=True,
            copied_xmp_properties=0,
            diagnostic_count=0,
            diagnostics=(),
        )
    materialized = materialize_xmp_copy_from_file_plan(copy_plan, source_path)
    diagnostics = materialized.diagnostics
    if diagnostics:
        return XmpSidecarCopyRewriteResult(
            data=EMPTY_XMP_PACKET,
            changed=False,
            copied_xmp_properties=0,
            diagnostic_count=len(diagnostics),
            diagnostics=diagnostics,
        )
    if not materialized.assignments:
        return XmpSidecarCopyRewriteResult(
            data=EMPTY_XMP_PACKET,
            changed=False,
            copied_xmp_properties=0,
            diagnostic_count=0,
            diagnostics=(),
        )
    packet = render_exif_to_xmp_sidecar_packet(materialized.assignments)
    return XmpSidecarCopyRewriteResult(
        data=packet,
        changed=packet != EMPTY_XMP_PACKET,
        copied_xmp_properties=len(unique_assignment_properties(materialized.assignments)),
        diagnostic_count=0,
        diagnostics=(),
    )


def rewrite_xmp_sidecar_copy_from_file_to_path(
    source_path: Path,
    output_path: Path,
    copy_plan: XmpCopyFromFilePlan,
    capability_audit: Path | None = None,
    backup_policy: BackupPolicy = "overwrite_original",
    backup_suffix: str = "_original",
) -> XmpSidecarCopyRewriteResult:
    result = rewrite_xmp_sidecar_copy_from_file(source_path, copy_plan, capability_audit)
    if backup_policy == "create_backup" and output_path.exists():
        transaction = write_bytes_in_place_transactionally(
            output_path,
            result.data,
            backup_policy,
            backup_suffix,
        )
    else:
        transaction = write_bytes_transactionally(output_path, result.data)
    return XmpSidecarCopyRewriteResult(
        data=result.data,
        changed=result.changed,
        copied_xmp_properties=result.copied_xmp_properties,
        diagnostic_count=result.diagnostic_count,
        diagnostics=result.diagnostics,
        transaction=transaction,
    )


def render_exif_to_xmp_sidecar_packet(assignments: tuple[XmpDestinationAssignment, ...]) -> bytes:
    values_by_property: dict[str, list[str]] = {}
    for assignment in assignments:
        values_by_property.setdefault(assignment.property_name, []).append(assignment.value)
    lines = [
        "<?xpacket begin='\ufeff' id='W5M0MpCehiHzreSzNTczkc9d'?>",
        f"<x:xmpmeta xmlns:x='adobe:ns:meta/' x:xmptk='{XMP_TOOLKIT_TEXT}'>",
        "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>",
        "",
    ]
    current_namespace_prefix = ""
    for spec in SIDECAR_COPY_PROPERTY_SPECS:
        values = values_by_property.get(spec.property_name)
        if not values:
            continue
        if spec.namespace_prefix != current_namespace_prefix:
            if current_namespace_prefix:
                lines.append(" </rdf:Description>")
                lines.append("")
            lines.append(" <rdf:Description rdf:about=''")
            lines.append(f"  xmlns:{spec.namespace_prefix}='{spec.namespace_uri}'>")
            current_namespace_prefix = spec.namespace_prefix
        lines.extend(render_property_lines(spec, tuple(values)))
    if current_namespace_prefix:
        lines.append(" </rdf:Description>")
        lines.append("")
    lines.extend(["</rdf:RDF>", "</x:xmpmeta>", "<?xpacket end='w'?>"])
    return ("\n".join(lines)).encode("utf-8")


def xmp_property_write_plan_from_copy_assignments(
    assignments: tuple[XmpDestinationAssignment, ...],
) -> XmpPropertyWritePlan:
    values_by_property = copy_assignment_values_by_property(assignments)
    steps: list[XmpTextPropertyWrite | XmpTextListPropertyWrite] = []
    generated_specs: list[XmpPropertySpec] = []
    for spec in SIDECAR_COPY_PROPERTY_SPECS:
        values = values_by_property.pop(spec.property_name, None)
        if values is None:
            continue
        generated_specs.append(xmp_property_spec_from_sidecar_copy_spec(spec))
        steps.append(xmp_property_write_step_from_sidecar_copy_spec(spec, tuple(values)))
    if values_by_property:
        unsupported_properties = ", ".join(sorted(values_by_property))
        raise ValueError(
            "No source-backed XMP property writer spec for exact copy assignments: "
            f"{unsupported_properties}"
        )
    return XmpPropertyWritePlan(
        tuple(steps),
        (XMP_TABLE_SOURCE, XMP_WRITER_SOURCE),
        (),
        tuple(generated_specs),
    )


def copy_assignment_values_by_property(
    assignments: tuple[XmpDestinationAssignment, ...],
) -> dict[str, list[str]]:
    values_by_property: dict[str, list[str]] = {}
    for assignment in assignments:
        values_by_property.setdefault(assignment.property_name, []).append(assignment.value)
    return values_by_property


def xmp_property_spec_from_sidecar_copy_spec(
    spec: XmpSidecarCopyPropertySpec,
) -> XmpPropertySpec:
    return XmpPropertySpec(
        spec.property_name,
        spec.namespace_prefix,
        spec.namespace_uri,
        spec.element_name,
        xmp_property_value_shape_from_sidecar_copy_shape(spec.value_shape),
        (XMP_TABLE_SOURCE,),
        xmp_rdf_container_from_sidecar_copy_shape(spec.value_shape),
    )


def xmp_property_value_shape_from_sidecar_copy_shape(
    shape: XmpSidecarCopyValueShape,
) -> XmpPropertyValueShape:
    if shape == "seq":
        return "seq_text"
    if shape == "alt":
        return "alt_text"
    return "simple_text"


def xmp_rdf_container_from_sidecar_copy_shape(
    shape: XmpSidecarCopyValueShape,
) -> XmpRdfContainer | None:
    if shape == "seq":
        return "Seq"
    if shape == "alt":
        return "Alt"
    return None


def xmp_property_write_step_from_sidecar_copy_spec(
    spec: XmpSidecarCopyPropertySpec,
    values: tuple[str, ...],
) -> XmpTextPropertyWrite | XmpTextListPropertyWrite:
    if spec.value_shape in {"seq", "alt"}:
        return XmpTextListPropertyWrite(spec.property_name, values)
    value = values[0] if values else ""
    return XmpTextPropertyWrite(spec.property_name, value)


def render_property_lines(
    spec: XmpSidecarCopyPropertySpec,
    values: tuple[str, ...],
) -> list[str]:
    qualified_name = f"{spec.namespace_prefix}:{spec.element_name}"
    if spec.value_shape == "seq":
        lines = [f"  <{qualified_name}>", "   <rdf:Seq>"]
        lines.extend(f"    <rdf:li>{escape(value)}</rdf:li>" for value in values)
        lines.extend(["   </rdf:Seq>", f"  </{qualified_name}>"])
        return lines
    if spec.value_shape == "alt":
        value = values[0] if values else ""
        return [
            f"  <{qualified_name}>",
            "   <rdf:Alt>",
            f"    <rdf:li xml:lang='x-default'>{escape(value)}</rdf:li>",
            "   </rdf:Alt>",
            f"  </{qualified_name}>",
        ]
    value = values[0] if values else ""
    return [f"  <{qualified_name}>{escape(value)}</{qualified_name}>"]


def unique_assignment_properties(
    assignments: tuple[XmpDestinationAssignment, ...],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(assignment.property_name for assignment in assignments))
