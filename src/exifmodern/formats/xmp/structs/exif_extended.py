"""Source-grounded EXIF Extended XMP struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    simple_struct_parent_spec_for_property,
)

EXIF_EXTENDED_NAMESPACE = "http://cipa.jp/exif/1.0/"

XMP_EXIF_EXTENDED_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    XmpSimpleStructParentSpec(
        parent_name="CompositeImageExposureTimes",
        property_name="XMP-exifEX:CompositeImageExposureTimes",
        element_name="CompositeImageExposureTimes",
        group="XMP-exifEX",
        namespace_prefix="exifEX",
        struct_namespace_prefix="exifEX",
        struct_namespace_uri=EXIF_EXTENDED_NAMESPACE,
        shape="struct",
    ),
)

XMP_EXIF_EXTENDED_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = (
    XmpSimpleStructFieldSpec(
        "TotalExposurePeriod",
        "TotalExposurePeriod",
        "CompImageTotalExposurePeriod",
        "rational",
    ),
    XmpSimpleStructFieldSpec(
        "SumOfExposureTimesOfAll",
        "SumOfExposureTimesOfAll",
        "CompImageSumExposureAll",
        "rational",
    ),
    XmpSimpleStructFieldSpec(
        "SumOfExposureTimesOfUsed",
        "SumOfExposureTimesOfUsed",
        "CompImageSumExposureUsed",
        "rational",
    ),
    XmpSimpleStructFieldSpec(
        "MaxExposureTimesOfAll",
        "MaxExposureTimesOfAll",
        "CompImageMaxExposureAll",
        "rational",
    ),
    XmpSimpleStructFieldSpec(
        "MaxExposureTimesOfUsed",
        "MaxExposureTimesOfUsed",
        "CompImageMaxExposureUsed",
        "rational",
    ),
    XmpSimpleStructFieldSpec(
        "MinExposureTimesOfAll",
        "MinExposureTimesOfAll",
        "CompImageMinExposureAll",
        "rational",
    ),
    XmpSimpleStructFieldSpec(
        "MinExposureTimesOfUsed",
        "MinExposureTimesOfUsed",
        "CompImageMinExposureUsed",
        "rational",
    ),
    XmpSimpleStructFieldSpec(
        "NumberOfSequences",
        "NumberOfSequences",
        "CompImageNumSequences",
        "integer",
    ),
    XmpSimpleStructFieldSpec(
        "NumberOfImagesInSequences",
        "NumberOfImagesInSequences",
        "CompImageImagesPerSequence",
        "integer",
    ),
    XmpSimpleStructFieldSpec(
        "Values",
        "Values",
        "CompImageValues",
        "rational",
        field_list_kind="Seq",
    ),
)


def exif_extended_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(
        XMP_EXIF_EXTENDED_PARENT_SPECS,
        property_name,
    )


def exif_extended_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-exifEX" or separator != ":":
        return None
    parent_spec = XMP_EXIF_EXTENDED_PARENT_SPECS[0]
    for field_spec in XMP_EXIF_EXTENDED_FIELD_SPECS:
        if tag_name == field_spec.readback_suffix:
            return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def exif_extended_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    if parent_name == "CompositeImageExposureTimes":
        return XMP_EXIF_EXTENDED_FIELD_SPECS
    return ()


def exif_extended_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for field_spec in XMP_EXIF_EXTENDED_FIELD_SPECS:
        tag_ids[field_spec.readback_suffix] = "CompositeImageExposureTimes"
    return tag_ids
