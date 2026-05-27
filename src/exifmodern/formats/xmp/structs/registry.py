"""Runtime registry for source-backed XMP simple struct/list adapters."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.acdsee_regions import (
    acdsee_regions_assignment_target,
    acdsee_regions_field_specs_for_parent,
    acdsee_regions_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.basic_image import (
    basic_image_assignment_target,
    basic_image_field_specs_for_parent,
    basic_image_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.camera_raw import (
    camera_raw_assignment_target,
    camera_raw_field_specs_for_parent,
    camera_raw_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.creator_atom import (
    creator_atom_assignment_target,
    creator_atom_field_specs_for_parent,
    creator_atom_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.dynamic_media import (
    dynamic_media_assignment_target,
    dynamic_media_field_specs_for_parent,
    dynamic_media_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.exif_extended import (
    exif_extended_assignment_target,
    exif_extended_field_specs_for_parent,
    exif_extended_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.exif_struct import (
    exif_struct_assignment_target,
    exif_struct_field_specs_for_parent,
    exif_struct_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.ics import (
    ics_assignment_target,
    ics_field_specs_for_parent,
    ics_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.iptc import (
    iptc_assignment_target,
    iptc_field_specs_for_parent,
    iptc_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.media_management import (
    media_management_assignment_target,
    media_management_field_specs_for_parent,
    media_management_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.paged_text import (
    paged_text_assignment_target,
    paged_text_field_specs_for_parent,
    paged_text_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.photoshop import (
    photoshop_assignment_target,
    photoshop_field_specs_for_parent,
    photoshop_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.prism import (
    prism_assignment_target,
    prism_field_specs_for_parent,
    prism_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
)


def xmp_struct_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    for parent_spec in (
        exif_struct_parent_spec_for_property(property_name),
        acdsee_regions_parent_spec_for_property(property_name),
        exif_extended_parent_spec_for_property(property_name),
        dynamic_media_parent_spec_for_property(property_name),
        media_management_parent_spec_for_property(property_name),
        basic_image_parent_spec_for_property(property_name),
        camera_raw_parent_spec_for_property(property_name),
        paged_text_parent_spec_for_property(property_name),
        iptc_parent_spec_for_property(property_name),
        ics_parent_spec_for_property(property_name),
        creator_atom_parent_spec_for_property(property_name),
        photoshop_parent_spec_for_property(property_name),
        prism_parent_spec_for_property(property_name),
    ):
        if parent_spec is not None:
            return parent_spec
    return None


def xmp_struct_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    for target in (
        exif_struct_assignment_target(property_name),
        acdsee_regions_assignment_target(property_name),
        exif_extended_assignment_target(property_name),
        dynamic_media_assignment_target(property_name),
        media_management_assignment_target(property_name),
        basic_image_assignment_target(property_name),
        camera_raw_assignment_target(property_name),
        paged_text_assignment_target(property_name),
        iptc_assignment_target(property_name),
        ics_assignment_target(property_name),
        creator_atom_assignment_target(property_name),
        photoshop_assignment_target(property_name),
        prism_assignment_target(property_name),
    ):
        if target is not None:
            return target
    return None


def xmp_struct_field_specs_for_parent(
    parent_spec: XmpSimpleStructParentSpec,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    if parent_spec.group == "XMP-xmpDM":
        return dynamic_media_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group in {"XMP-crd", "XMP-crs"}:
        return camera_raw_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group == "XMP-exif":
        return exif_struct_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group == "XMP-acdsee-rs":
        return acdsee_regions_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group == "XMP-exifEX":
        return exif_extended_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group == "XMP-xmpMM":
        return media_management_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group == "XMP-xmp":
        return basic_image_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group == "XMP-xmpTPg":
        return paged_text_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group in {"XMP-iptcCore", "XMP-iptcExt"}:
        return iptc_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group == "XMP-ics":
        return ics_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group == "XMP-creatorAtom":
        return creator_atom_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group == "XMP-photoshop":
        return photoshop_field_specs_for_parent(parent_spec.parent_name)
    if parent_spec.group == "XMP-prism":
        return prism_field_specs_for_parent(parent_spec.parent_name)
    return ()
