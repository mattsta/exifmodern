"""Machine-readable reports for XMP structure adapter coverage."""

from __future__ import annotations

import json
from pathlib import Path

from exifmodern.formats.xmp.structs.acdsee_regions import (
    XMP_ACDSEE_REGION_FIELD_SPECS,
    XMP_ACDSEE_REGION_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.basic_image import (
    XMP_BASIC_IMAGE_FIELD_SPECS,
    XMP_BASIC_IMAGE_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.camera_raw import (
    XMP_CAMERA_RAW_FIELD_SPECS,
    XMP_CAMERA_RAW_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.creator_atom import (
    XMP_CREATOR_ATOM_FIELD_SPECS,
    XMP_CREATOR_ATOM_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.dynamic_media import (
    XMP_DYNAMIC_MEDIA_FIELD_SPECS,
    XMP_DYNAMIC_MEDIA_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.exif_extended import (
    XMP_EXIF_EXTENDED_FIELD_SPECS,
    XMP_EXIF_EXTENDED_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.exif_struct import (
    XMP_EXIF_STRUCT_FIELD_SPECS,
    XMP_EXIF_STRUCT_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.ics import (
    XMP_ICS_FIELD_SPECS,
    XMP_ICS_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.iptc import (
    XMP_IPTC_FIELD_SPECS,
    XMP_IPTC_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.job_ref import (
    XMP_JOB_REF_FIELD_SPECS,
    XMP_JOB_REF_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.manifest_item import (
    XMP_MANIFEST_ITEM_PARENT_SPECS,
    XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS,
    manifest_item_readback_tag_ids,
)
from exifmodern.formats.xmp.structs.media_management import (
    XMP_MEDIA_MANAGEMENT_FIELD_SPECS,
    XMP_MEDIA_MANAGEMENT_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.paged_text import (
    XMP_PAGED_TEXT_FIELD_SPECS,
    XMP_PAGED_TEXT_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.pantry_item import (
    XMP_PANTRY_ITEM_FIELD_SPECS,
    XMP_PANTRY_ITEM_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.photoshop import (
    XMP_PHOTOSHOP_FIELD_SPECS,
    XMP_PHOTOSHOP_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.prism import (
    XMP_PRISM_FIELD_SPECS,
    XMP_PRISM_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.resource_event import (
    XMP_RESOURCE_EVENT_FIELD_SPECS,
    XMP_RESOURCE_EVENT_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.resource_ref import (
    XMP_RESOURCE_REF_FIELD_SPECS,
    XMP_RESOURCE_REF_PARENT_SPECS,
)
from exifmodern.json_types import JsonArray, JsonObject


def xmp_struct_adapter_report() -> JsonObject:
    parent_items: JsonArray = []
    for resource_ref_parent_spec in XMP_RESOURCE_REF_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "ResourceRef",
                "element_name": resource_ref_parent_spec.element_name,
                "list_kind": resource_ref_parent_spec.list_kind,
                "namespace": "xmpMM",
                "parent_name": resource_ref_parent_spec.parent_name,
                "property_name": resource_ref_parent_spec.property_name,
                "shape": resource_ref_parent_spec.shape,
            }
        )
    for acdsee_region_parent_spec in XMP_ACDSEE_REGION_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "AcdseeRegionSimpleStruct",
                "element_name": acdsee_region_parent_spec.element_name,
                "list_kind": acdsee_region_parent_spec.list_kind,
                "namespace": acdsee_region_parent_spec.namespace_prefix,
                "parent_name": acdsee_region_parent_spec.parent_name,
                "property_name": acdsee_region_parent_spec.property_name,
                "shape": acdsee_region_parent_spec.shape,
                "struct_namespace_prefix": (acdsee_region_parent_spec.struct_namespace_prefix),
            }
        )
    for resource_event_parent_spec in XMP_RESOURCE_EVENT_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "ResourceEvent",
                "element_name": resource_event_parent_spec.element_name,
                "list_kind": resource_event_parent_spec.list_kind,
                "namespace": "xmpMM",
                "parent_name": resource_event_parent_spec.parent_name,
                "property_name": resource_event_parent_spec.property_name,
                "shape": resource_event_parent_spec.shape,
            }
        )
    for job_ref_parent_spec in XMP_JOB_REF_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "JobRef",
                "element_name": job_ref_parent_spec.element_name,
                "list_kind": job_ref_parent_spec.list_kind,
                "namespace": "xmpBJ",
                "parent_name": job_ref_parent_spec.parent_name,
                "property_name": job_ref_parent_spec.property_name,
                "shape": job_ref_parent_spec.shape,
            }
        )
    for manifest_item_parent_spec in XMP_MANIFEST_ITEM_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "ManifestItem",
                "element_name": manifest_item_parent_spec.element_name,
                "list_kind": manifest_item_parent_spec.list_kind,
                "namespace": "xmpMM",
                "parent_name": manifest_item_parent_spec.parent_name,
                "property_name": manifest_item_parent_spec.property_name,
                "shape": manifest_item_parent_spec.shape,
            }
        )
    for pantry_item_parent_spec in XMP_PANTRY_ITEM_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "PantryItem",
                "element_name": pantry_item_parent_spec.element_name,
                "list_kind": pantry_item_parent_spec.list_kind,
                "namespace": "xmpMM",
                "parent_name": pantry_item_parent_spec.parent_name,
                "property_name": pantry_item_parent_spec.property_name,
                "shape": pantry_item_parent_spec.shape,
            }
        )
    for paged_text_parent_spec in XMP_PAGED_TEXT_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "PagedTextSimpleStruct",
                "element_name": paged_text_parent_spec.element_name,
                "list_kind": paged_text_parent_spec.list_kind,
                "namespace": paged_text_parent_spec.namespace_prefix,
                "parent_name": paged_text_parent_spec.parent_name,
                "property_name": paged_text_parent_spec.property_name,
                "shape": paged_text_parent_spec.shape,
                "struct_namespace_prefix": paged_text_parent_spec.struct_namespace_prefix,
            }
        )
    for dynamic_media_parent_spec in XMP_DYNAMIC_MEDIA_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "DynamicMediaSimpleStruct",
                "element_name": dynamic_media_parent_spec.element_name,
                "list_kind": dynamic_media_parent_spec.list_kind,
                "namespace": dynamic_media_parent_spec.namespace_prefix,
                "parent_name": dynamic_media_parent_spec.parent_name,
                "property_name": dynamic_media_parent_spec.property_name,
                "shape": dynamic_media_parent_spec.shape,
                "struct_namespace_prefix": dynamic_media_parent_spec.struct_namespace_prefix,
            }
        )
    for camera_raw_parent_spec in XMP_CAMERA_RAW_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "CameraRawSimpleStruct",
                "element_name": camera_raw_parent_spec.element_name,
                "list_kind": camera_raw_parent_spec.list_kind,
                "namespace": camera_raw_parent_spec.namespace_prefix,
                "parent_name": camera_raw_parent_spec.parent_name,
                "property_name": camera_raw_parent_spec.property_name,
                "shape": camera_raw_parent_spec.shape,
                "struct_namespace_prefix": camera_raw_parent_spec.struct_namespace_prefix,
            }
        )
    for creator_atom_parent_spec in XMP_CREATOR_ATOM_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "CreatorAtomSimpleStruct",
                "element_name": creator_atom_parent_spec.element_name,
                "list_kind": creator_atom_parent_spec.list_kind,
                "namespace": creator_atom_parent_spec.namespace_prefix,
                "parent_name": creator_atom_parent_spec.parent_name,
                "property_name": creator_atom_parent_spec.property_name,
                "shape": creator_atom_parent_spec.shape,
                "struct_namespace_prefix": creator_atom_parent_spec.struct_namespace_prefix,
            }
        )
    for exif_extended_parent_spec in XMP_EXIF_EXTENDED_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "ExifExtendedSimpleStruct",
                "element_name": exif_extended_parent_spec.element_name,
                "list_kind": exif_extended_parent_spec.list_kind,
                "namespace": exif_extended_parent_spec.namespace_prefix,
                "parent_name": exif_extended_parent_spec.parent_name,
                "property_name": exif_extended_parent_spec.property_name,
                "shape": exif_extended_parent_spec.shape,
                "struct_namespace_prefix": exif_extended_parent_spec.struct_namespace_prefix,
            }
        )
    for exif_parent_spec in XMP_EXIF_STRUCT_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "ExifSimpleStruct",
                "element_name": exif_parent_spec.element_name,
                "list_kind": exif_parent_spec.list_kind,
                "namespace": exif_parent_spec.namespace_prefix,
                "parent_name": exif_parent_spec.parent_name,
                "property_name": exif_parent_spec.property_name,
                "shape": exif_parent_spec.shape,
                "struct_namespace_prefix": exif_parent_spec.struct_namespace_prefix,
            }
        )
    for ics_parent_spec in XMP_ICS_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "IcsSimpleStruct",
                "element_name": ics_parent_spec.element_name,
                "list_kind": ics_parent_spec.list_kind,
                "namespace": ics_parent_spec.namespace_prefix,
                "parent_name": ics_parent_spec.parent_name,
                "property_name": ics_parent_spec.property_name,
                "shape": ics_parent_spec.shape,
                "struct_namespace_prefix": ics_parent_spec.struct_namespace_prefix,
            }
        )
    for media_management_parent_spec in XMP_MEDIA_MANAGEMENT_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "MediaManagementVersion",
                "element_name": media_management_parent_spec.element_name,
                "list_kind": media_management_parent_spec.list_kind,
                "namespace": media_management_parent_spec.namespace_prefix,
                "parent_name": media_management_parent_spec.parent_name,
                "property_name": media_management_parent_spec.property_name,
                "shape": media_management_parent_spec.shape,
                "struct_namespace_prefix": media_management_parent_spec.struct_namespace_prefix,
            }
        )
    for basic_image_parent_spec in XMP_BASIC_IMAGE_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "BasicImageStruct",
                "element_name": basic_image_parent_spec.element_name,
                "list_kind": basic_image_parent_spec.list_kind,
                "namespace": basic_image_parent_spec.namespace_prefix,
                "parent_name": basic_image_parent_spec.parent_name,
                "property_name": basic_image_parent_spec.property_name,
                "shape": basic_image_parent_spec.shape,
                "struct_namespace_prefix": basic_image_parent_spec.struct_namespace_prefix,
            }
        )
    for iptc_parent_spec in XMP_IPTC_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "IptcSimpleStruct",
                "element_name": iptc_parent_spec.element_name,
                "list_kind": iptc_parent_spec.list_kind,
                "namespace": iptc_parent_spec.namespace_prefix,
                "parent_name": iptc_parent_spec.parent_name,
                "property_name": iptc_parent_spec.property_name,
                "shape": iptc_parent_spec.shape,
                "struct_namespace_prefix": iptc_parent_spec.struct_namespace_prefix,
            }
        )
    for prism_parent_spec in XMP_PRISM_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "PrismSimpleStruct",
                "element_name": prism_parent_spec.element_name,
                "list_kind": prism_parent_spec.list_kind,
                "namespace": prism_parent_spec.namespace_prefix,
                "parent_name": prism_parent_spec.parent_name,
                "property_name": prism_parent_spec.property_name,
                "shape": prism_parent_spec.shape,
                "struct_namespace_prefix": prism_parent_spec.struct_namespace_prefix,
            }
        )
    for photoshop_parent_spec in XMP_PHOTOSHOP_PARENT_SPECS:
        parent_items.append(
            {
                "adapter": "PhotoshopSimpleStruct",
                "element_name": photoshop_parent_spec.element_name,
                "list_kind": photoshop_parent_spec.list_kind,
                "namespace": photoshop_parent_spec.namespace_prefix,
                "parent_name": photoshop_parent_spec.parent_name,
                "property_name": photoshop_parent_spec.property_name,
                "shape": photoshop_parent_spec.shape,
                "struct_namespace_prefix": photoshop_parent_spec.struct_namespace_prefix,
            }
        )

    field_items: JsonArray = []
    for resource_ref_field_spec in XMP_RESOURCE_REF_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "ResourceRef",
                "date_value": resource_ref_field_spec.date_value,
                "field_name": resource_ref_field_spec.field_name,
                "readback_suffix": resource_ref_field_spec.readback_suffix,
                "suffix": resource_ref_field_spec.suffix,
            }
        )
    for acdsee_region_field_spec in XMP_ACDSEE_REGION_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "AcdseeRegionSimpleStruct",
                "date_value": False,
                "field_name": acdsee_region_field_spec.field_name,
                "nested_field_name": acdsee_region_field_spec.nested_field_name,
                "nested_list_kind": acdsee_region_field_spec.nested_list_kind,
                "readback_suffix": acdsee_region_field_spec.readback_suffix,
                "suffix": acdsee_region_field_spec.suffix,
                "value_kind": acdsee_region_field_spec.value_kind,
            }
        )
    for resource_event_field_spec in XMP_RESOURCE_EVENT_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "ResourceEvent",
                "date_value": resource_event_field_spec.date_value,
                "field_name": resource_event_field_spec.field_name,
                "readback_suffix": resource_event_field_spec.readback_suffix,
                "suffix": resource_event_field_spec.suffix,
            }
        )
    for job_ref_field_spec in XMP_JOB_REF_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "JobRef",
                "date_value": False,
                "field_name": job_ref_field_spec.field_name,
                "readback_suffix": job_ref_field_spec.readback_suffix,
                "suffix": job_ref_field_spec.suffix,
            }
        )
    for manifest_item_field_spec in XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "ManifestItem",
                "date_value": False,
                "field_name": manifest_item_field_spec.field_name,
                "field_kind": "simple",
                "readback_suffix": manifest_item_field_spec.readback_suffix,
                "suffix": manifest_item_field_spec.suffix,
            }
        )
    for manifest_item_reference_name in sorted(manifest_item_readback_tag_ids()):
        if not manifest_item_reference_name.startswith("ManifestReference"):
            continue
        field_items.append(
            {
                "adapter": "ManifestItem",
                "date_value": manifest_item_reference_name == "ManifestReferenceLastModifyDate",
                "field_name": manifest_item_reference_name.removeprefix("ManifestReference"),
                "field_kind": "reference",
                "readback_suffix": manifest_item_reference_name.removeprefix("Manifest"),
                "suffix": manifest_item_reference_name.removeprefix("Manifest"),
            }
        )
    for pantry_item_field_spec in XMP_PANTRY_ITEM_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "PantryItem",
                "date_value": False,
                "field_name": pantry_item_field_spec.field_name,
                "readback_suffix": pantry_item_field_spec.readback_suffix,
                "suffix": pantry_item_field_spec.suffix,
            }
        )
    for paged_text_field_spec in XMP_PAGED_TEXT_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "PagedTextSimpleStruct",
                "date_value": False,
                "field_name": paged_text_field_spec.field_name,
                "readback_suffix": paged_text_field_spec.readback_suffix,
                "suffix": paged_text_field_spec.suffix,
                "value_kind": paged_text_field_spec.value_kind,
            }
        )
    for dynamic_media_field_spec in XMP_DYNAMIC_MEDIA_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "DynamicMediaSimpleStruct",
                "date_value": False,
                "field_name": dynamic_media_field_spec.field_name,
                "readback_suffix": dynamic_media_field_spec.readback_suffix,
                "suffix": dynamic_media_field_spec.suffix,
                "value_kind": dynamic_media_field_spec.value_kind,
            }
        )
    for camera_raw_field_spec in XMP_CAMERA_RAW_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "CameraRawSimpleStruct",
                "date_value": False,
                "field_list_kind": camera_raw_field_spec.field_list_kind,
                "field_name": camera_raw_field_spec.field_name,
                "nested_field_name": camera_raw_field_spec.nested_field_name,
                "nested_list_kind": camera_raw_field_spec.nested_list_kind,
                "readback_suffix": camera_raw_field_spec.readback_suffix,
                "suffix": camera_raw_field_spec.suffix,
                "value_kind": camera_raw_field_spec.value_kind,
            }
        )
    for creator_atom_field_spec in XMP_CREATOR_ATOM_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "CreatorAtomSimpleStruct",
                "date_value": False,
                "field_name": creator_atom_field_spec.field_name,
                "readback_suffix": creator_atom_field_spec.readback_suffix,
                "suffix": creator_atom_field_spec.suffix,
                "value_kind": creator_atom_field_spec.value_kind,
            }
        )
    for exif_extended_field_spec in XMP_EXIF_EXTENDED_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "ExifExtendedSimpleStruct",
                "date_value": False,
                "field_list_kind": exif_extended_field_spec.field_list_kind,
                "field_name": exif_extended_field_spec.field_name,
                "readback_suffix": exif_extended_field_spec.readback_suffix,
                "suffix": exif_extended_field_spec.suffix,
                "value_kind": exif_extended_field_spec.value_kind,
            }
        )
    for exif_field_spec in XMP_EXIF_STRUCT_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "ExifSimpleStruct",
                "date_value": False,
                "field_list_kind": exif_field_spec.field_list_kind,
                "field_name": exif_field_spec.field_name,
                "readback_suffix": exif_field_spec.readback_suffix,
                "suffix": exif_field_spec.suffix,
                "value_kind": exif_field_spec.value_kind,
            }
        )
    for ics_field_spec in XMP_ICS_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "IcsSimpleStruct",
                "date_value": False,
                "field_name": ics_field_spec.field_name,
                "nested_field_name": ics_field_spec.nested_field_name,
                "nested_list_kind": ics_field_spec.nested_list_kind,
                "readback_suffix": ics_field_spec.readback_suffix,
                "suffix": ics_field_spec.suffix,
                "value_kind": ics_field_spec.value_kind,
            }
        )
    for media_management_field_spec in XMP_MEDIA_MANAGEMENT_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "MediaManagementVersion",
                "date_value": media_management_field_spec.value_kind == "date",
                "field_name": media_management_field_spec.field_name,
                "readback_suffix": media_management_field_spec.readback_suffix,
                "suffix": media_management_field_spec.suffix,
                "value_kind": media_management_field_spec.value_kind,
            }
        )
    for basic_image_field_spec in XMP_BASIC_IMAGE_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "BasicImageStruct",
                "date_value": False,
                "field_name": basic_image_field_spec.field_name,
                "readback_suffix": basic_image_field_spec.readback_suffix,
                "suffix": basic_image_field_spec.suffix,
                "value_kind": basic_image_field_spec.value_kind,
            }
        )
    for iptc_field_spec in XMP_IPTC_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "IptcSimpleStruct",
                "date_value": iptc_field_spec.value_kind == "date",
                "field_list_kind": iptc_field_spec.field_list_kind,
                "field_name": iptc_field_spec.field_name,
                "readback_suffix": iptc_field_spec.readback_suffix,
                "suffix": iptc_field_spec.suffix,
                "value_kind": iptc_field_spec.value_kind,
            }
        )
    for prism_field_spec in XMP_PRISM_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "PrismSimpleStruct",
                "date_value": prism_field_spec.value_kind == "date",
                "field_name": prism_field_spec.field_name,
                "readback_suffix": prism_field_spec.readback_suffix,
                "suffix": prism_field_spec.suffix,
                "value_kind": prism_field_spec.value_kind,
            }
        )
    for photoshop_field_spec in XMP_PHOTOSHOP_FIELD_SPECS:
        field_items.append(
            {
                "adapter": "PhotoshopSimpleStruct",
                "date_value": False,
                "field_name": photoshop_field_spec.field_name,
                "nested_field_name": photoshop_field_spec.nested_field_name,
                "readback_suffix": photoshop_field_spec.readback_suffix,
                "suffix": photoshop_field_spec.suffix,
                "value_kind": photoshop_field_spec.value_kind,
            }
        )

    return {
        "adapter_count": 18,
        "adapters": [
            {
                "adapter": "AcdseeRegionSimpleStruct",
                "field_count": len(XMP_ACDSEE_REGION_FIELD_SPECS),
                "parent_count": len(XMP_ACDSEE_REGION_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::ACDSeeRegions",
                "struct_name": "ACDSeeRegionInfo/ACDSeeRegion",
                "supported_shapes": ["struct"],
            },
            {
                "adapter": "BasicImageStruct",
                "field_count": len(XMP_BASIC_IMAGE_FIELD_SPECS),
                "parent_count": len(XMP_BASIC_IMAGE_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::xmp",
                "struct_name": "PageInfo/Thumbnail",
                "supported_shapes": ["struct_list"],
            },
            {
                "adapter": "DynamicMediaSimpleStruct",
                "field_count": len(XMP_DYNAMIC_MEDIA_FIELD_SPECS),
                "parent_count": len(XMP_DYNAMIC_MEDIA_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::xmpDM",
                "struct_name": "Time/Timecode/Media/ProjectLink/DynamicMedia structures",
                "supported_shapes": ["struct", "struct_list"],
            },
            {
                "adapter": "CameraRawSimpleStruct",
                "field_count": len(XMP_CAMERA_RAW_FIELD_SPECS),
                "parent_count": len(XMP_CAMERA_RAW_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::crd/crs",
                "struct_name": "Adobe Camera Raw correction, mask, look, and lens structures",
                "supported_shapes": ["struct", "struct_list"],
            },
            {
                "adapter": "CreatorAtomSimpleStruct",
                "field_count": len(XMP_CREATOR_ATOM_FIELD_SPECS),
                "parent_count": len(XMP_CREATOR_ATOM_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::creatorAtom",
                "struct_name": "AEProjectLink/MacAtom/WindowsAtom",
                "supported_shapes": ["struct"],
            },
            {
                "adapter": "ExifExtendedSimpleStruct",
                "field_count": len(XMP_EXIF_EXTENDED_FIELD_SPECS),
                "parent_count": len(XMP_EXIF_EXTENDED_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::exifEX",
                "struct_name": "CompositeImageExposureTimes",
                "supported_shapes": ["struct"],
            },
            {
                "adapter": "ExifSimpleStruct",
                "field_count": len(XMP_EXIF_STRUCT_FIELD_SPECS),
                "parent_count": len(XMP_EXIF_STRUCT_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::exif",
                "struct_name": "OECF/Flash/CFAPattern/DeviceSettings",
                "supported_shapes": ["struct"],
            },
            {
                "adapter": "IcsSimpleStruct",
                "field_count": len(XMP_ICS_FIELD_SPECS),
                "parent_count": len(XMP_ICS_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::ics",
                "struct_name": "SubVersion/TagStructure",
                "supported_shapes": ["struct_list"],
            },
            {
                "adapter": "JobRef",
                "field_count": len(XMP_JOB_REF_FIELD_SPECS),
                "parent_count": len(XMP_JOB_REF_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::xmpBJ",
                "struct_name": "JobRef",
                "supported_shapes": ["struct_list"],
            },
            {
                "adapter": "IptcSimpleStruct",
                "field_count": len(XMP_IPTC_FIELD_SPECS),
                "parent_count": len(XMP_IPTC_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::iptcCore/iptcExt",
                "struct_name": "IPTC Core contact and IPTC Extension reusable structs",
                "supported_shapes": ["struct", "struct_list"],
            },
            {
                "adapter": "PrismSimpleStruct",
                "field_count": len(XMP_PRISM_FIELD_SPECS),
                "parent_count": len(XMP_PRISM_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::prism",
                "struct_name": "PRISM alternate title/channel/date/platform structures",
                "supported_shapes": ["struct", "struct_list"],
            },
            {
                "adapter": "PhotoshopSimpleStruct",
                "field_count": len(XMP_PHOTOSHOP_FIELD_SPECS),
                "parent_count": len(XMP_PHOTOSHOP_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::photoshop",
                "struct_name": "CameraProfiles/TextLayers",
                "supported_shapes": ["struct_list"],
            },
            {
                "adapter": "ManifestItem",
                "field_count": len(XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS)
                + len(manifest_item_readback_tag_ids())
                - len(XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS),
                "parent_count": len(XMP_MANIFEST_ITEM_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::xmpMM",
                "struct_name": "ManifestItem",
                "supported_shapes": ["struct_list"],
            },
            {
                "adapter": "MediaManagementVersion",
                "field_count": len(XMP_MEDIA_MANAGEMENT_FIELD_SPECS),
                "parent_count": len(XMP_MEDIA_MANAGEMENT_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::xmpMM",
                "struct_name": "Version",
                "supported_shapes": ["struct_list"],
            },
            {
                "adapter": "PantryItem",
                "field_count": len(XMP_PANTRY_ITEM_FIELD_SPECS),
                "parent_count": len(XMP_PANTRY_ITEM_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::xmpMM",
                "struct_name": "PantryItem",
                "supported_shapes": ["struct_list"],
            },
            {
                "adapter": "PagedTextSimpleStruct",
                "field_count": len(XMP_PAGED_TEXT_FIELD_SPECS),
                "parent_count": len(XMP_PAGED_TEXT_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::xmpTPg",
                "struct_name": "Dimensions/Font/Colorant",
                "supported_shapes": ["struct", "struct_list"],
            },
            {
                "adapter": "ResourceRef",
                "field_count": len(XMP_RESOURCE_REF_FIELD_SPECS),
                "parent_count": len(XMP_RESOURCE_REF_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::xmpMM",
                "struct_name": "ResourceRef",
                "supported_shapes": ["struct", "struct_list"],
            },
            {
                "adapter": "ResourceEvent",
                "field_count": len(XMP_RESOURCE_EVENT_FIELD_SPECS),
                "parent_count": len(XMP_RESOURCE_EVENT_PARENT_SPECS),
                "source_table": "Image::ExifTool::XMP::xmpMM",
                "struct_name": "ResourceEvent",
                "supported_shapes": ["struct_list"],
            },
        ],
        "field_count": (
            len(XMP_ACDSEE_REGION_FIELD_SPECS)
            + len(XMP_JOB_REF_FIELD_SPECS)
            + len(XMP_BASIC_IMAGE_FIELD_SPECS)
            + len(XMP_CAMERA_RAW_FIELD_SPECS)
            + len(XMP_CREATOR_ATOM_FIELD_SPECS)
            + len(XMP_DYNAMIC_MEDIA_FIELD_SPECS)
            + len(XMP_EXIF_EXTENDED_FIELD_SPECS)
            + len(XMP_EXIF_STRUCT_FIELD_SPECS)
            + len(XMP_ICS_FIELD_SPECS)
            + len(XMP_IPTC_FIELD_SPECS)
            + len(manifest_item_readback_tag_ids())
            + len(XMP_MEDIA_MANAGEMENT_FIELD_SPECS)
            + len(XMP_PANTRY_ITEM_FIELD_SPECS)
            + len(XMP_PAGED_TEXT_FIELD_SPECS)
            + len(XMP_PHOTOSHOP_FIELD_SPECS)
            + len(XMP_PRISM_FIELD_SPECS)
            + len(XMP_RESOURCE_REF_FIELD_SPECS)
            + len(XMP_RESOURCE_EVENT_FIELD_SPECS)
        ),
        "fields": field_items,
        "parent_count": (
            len(XMP_ACDSEE_REGION_PARENT_SPECS)
            + len(XMP_JOB_REF_PARENT_SPECS)
            + len(XMP_BASIC_IMAGE_PARENT_SPECS)
            + len(XMP_CAMERA_RAW_PARENT_SPECS)
            + len(XMP_CREATOR_ATOM_PARENT_SPECS)
            + len(XMP_DYNAMIC_MEDIA_PARENT_SPECS)
            + len(XMP_EXIF_EXTENDED_PARENT_SPECS)
            + len(XMP_EXIF_STRUCT_PARENT_SPECS)
            + len(XMP_ICS_PARENT_SPECS)
            + len(XMP_IPTC_PARENT_SPECS)
            + len(XMP_MANIFEST_ITEM_PARENT_SPECS)
            + len(XMP_MEDIA_MANAGEMENT_PARENT_SPECS)
            + len(XMP_PANTRY_ITEM_PARENT_SPECS)
            + len(XMP_PAGED_TEXT_PARENT_SPECS)
            + len(XMP_PHOTOSHOP_PARENT_SPECS)
            + len(XMP_PRISM_PARENT_SPECS)
            + len(XMP_RESOURCE_REF_PARENT_SPECS)
            + len(XMP_RESOURCE_EVENT_PARENT_SPECS)
        ),
        "parents": parent_items,
    }


def write_xmp_struct_adapter_report(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(xmp_struct_adapter_report(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
