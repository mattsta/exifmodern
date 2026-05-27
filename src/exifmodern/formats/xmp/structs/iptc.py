"""Source-grounded IPTC Core/Extension XMP struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructListKind,
    XmpSimpleStructParentSpec,
    XmpSimpleStructPathStep,
    XmpSimpleStructShape,
    XmpSimpleStructValueKind,
    simple_struct_parent_spec_for_property,
)

IPTC_CORE_NAMESPACE = "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/"
IPTC_EXT_NAMESPACE = "http://iptc.org/std/Iptc4xmpExt/2008-02-29/"
XMP_NAMESPACE = "http://ns.adobe.com/xap/1.0/"
EXIF_NAMESPACE = "http://ns.adobe.com/exif/1.0/"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
ST_AREA_NAMESPACE = "http://ns.adobe.com/xmp/sType/Area#"
XMP_DM_NAMESPACE = "http://ns.adobe.com/xmp/1.0/DynamicMedia/"


def iptc_core_parent(parent_name: str) -> XmpSimpleStructParentSpec:
    return XmpSimpleStructParentSpec(
        parent_name=parent_name,
        property_name=f"XMP-iptcCore:{parent_name}",
        element_name=parent_name,
        group="XMP-iptcCore",
        namespace_prefix="iptcCore",
        struct_namespace_prefix="Iptc4xmpCore",
        struct_namespace_uri=IPTC_CORE_NAMESPACE,
        shape="struct",
    )


def iptc_ext_parent(
    parent_name: str,
    *,
    element_name: str | None = None,
    shape: XmpSimpleStructShape = "struct",
) -> XmpSimpleStructParentSpec:
    return XmpSimpleStructParentSpec(
        parent_name=parent_name,
        property_name=f"XMP-iptcExt:{parent_name}",
        element_name=element_name or parent_name,
        group="XMP-iptcExt",
        namespace_prefix="iptcExt",
        struct_namespace_prefix="Iptc4xmpExt",
        struct_namespace_uri=IPTC_EXT_NAMESPACE,
        shape=shape,
        list_kind="Bag" if shape == "struct_list" else None,
    )


XMP_IPTC_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    iptc_core_parent("CreatorContactInfo"),
    iptc_ext_parent("AboutCvTerm", shape="struct_list"),
    iptc_ext_parent("ArtworkOrObject", shape="struct_list"),
    iptc_ext_parent("ContainerFormat"),
    iptc_ext_parent("Contributor", shape="struct_list"),
    iptc_ext_parent("Creator", shape="struct_list"),
    iptc_ext_parent("DataOnScreen", shape="struct_list"),
    iptc_ext_parent("DopesheetLink", shape="struct_list"),
    iptc_ext_parent("EmbdEncRightsExpr", shape="struct_list"),
    iptc_ext_parent("Episode"),
    iptc_ext_parent("Genre", shape="struct_list"),
    iptc_ext_parent("ImageRegion", shape="struct_list"),
    iptc_ext_parent("LinkedEncRightsExpr", shape="struct_list"),
    iptc_ext_parent("LocationCreated", shape="struct_list"),
    iptc_ext_parent("LocationShown", shape="struct_list"),
    iptc_ext_parent("MetadataAuthority", element_name="metadataAuthority"),
    iptc_ext_parent("MetadataLastEditor", element_name="metadataLastEditor"),
    iptc_ext_parent("PersonHeard", shape="struct_list"),
    iptc_ext_parent("PersonInImageWDetails", shape="struct_list"),
    iptc_ext_parent("PlanningRef", shape="struct_list"),
    iptc_ext_parent("ProductInImage", shape="struct_list"),
    iptc_ext_parent("PublicationEvent", shape="struct_list"),
    iptc_ext_parent("Rating", shape="struct_list"),
    iptc_ext_parent("RecDevice"),
    iptc_ext_parent("RegistryID", element_name="RegistryId", shape="struct_list"),
    iptc_ext_parent("Season"),
    iptc_ext_parent("Series"),
    iptc_ext_parent("ShownEvent", element_name="EventExt", shape="struct_list"),
    iptc_ext_parent("Snapshot", element_name="SnapshotLink", shape="struct_list"),
    iptc_ext_parent("SupplyChainSource", shape="struct_list"),
    iptc_ext_parent("TemporalCoverage"),
    iptc_ext_parent("TranscriptLink", shape="struct_list"),
    iptc_ext_parent("VideoShotType", shape="struct_list"),
    iptc_ext_parent("WorkflowTag"),
)


def field(
    suffix: str,
    field_name: str,
    readback_suffix: str,
    value_kind: XmpSimpleStructValueKind = "text",
    *,
    namespace_uri: str | None = None,
    field_list_kind: XmpSimpleStructListKind | None = None,
    nested_path: tuple[XmpSimpleStructPathStep, ...] = (),
) -> XmpSimpleStructFieldSpec:
    return XmpSimpleStructFieldSpec(
        suffix=suffix,
        field_name=field_name,
        readback_suffix=readback_suffix,
        value_kind=value_kind,
        namespace_uri=namespace_uri,
        field_list_kind=field_list_kind,
        nested_path=nested_path,
    )


def parent_fields(
    parent_name: str,
    specs: tuple[XmpSimpleStructFieldSpec, ...],
) -> tuple[str, tuple[XmpSimpleStructFieldSpec, ...]]:
    return (parent_name, specs)


def prefixed_field(
    parent_name: str,
    suffix: str,
    field_name: str | None = None,
    value_kind: XmpSimpleStructValueKind = "text",
    *,
    namespace_uri: str | None = None,
    field_list_kind: XmpSimpleStructListKind | None = None,
    nested_path: tuple[XmpSimpleStructPathStep, ...] = (),
) -> XmpSimpleStructFieldSpec:
    return field(
        suffix=f"{parent_name}{suffix}",
        field_name=field_name or suffix,
        readback_suffix=f"{parent_name}{suffix}",
        value_kind=value_kind,
        namespace_uri=namespace_uri,
        field_list_kind=field_list_kind,
        nested_path=nested_path,
    )


def iptc_path_step(
    field_name: str,
    list_kind: XmpSimpleStructListKind | None = None,
) -> XmpSimpleStructPathStep:
    return XmpSimpleStructPathStep(
        field_name,
        namespace_uri=IPTC_EXT_NAMESPACE,
        list_kind=list_kind,
    )


def nested_field(
    suffix: str,
    field_name: str,
    readback_suffix: str,
    nested_path: tuple[XmpSimpleStructPathStep, ...],
    value_kind: XmpSimpleStructValueKind = "text",
    *,
    namespace_uri: str | None = None,
    field_list_kind: XmpSimpleStructListKind | None = None,
) -> XmpSimpleStructFieldSpec:
    return field(
        suffix,
        field_name,
        readback_suffix,
        value_kind,
        namespace_uri=namespace_uri,
        field_list_kind=field_list_kind,
        nested_path=nested_path,
    )


def entity_fields(parent_name: str) -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field(
            parent_name, "Identifier", namespace_uri=XMP_NAMESPACE, field_list_kind="Bag"
        ),
        prefixed_field(parent_name, "Name", value_kind="lang_alt"),
    )


def entity_with_role_fields(parent_name: str) -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        *entity_fields(parent_name),
        prefixed_field(parent_name, "Role", field_list_kind="Bag"),
    )


def cv_term_fields(parent_name: str) -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field(parent_name, "CvId", "CvId"),
        prefixed_field(parent_name, "Id", "CvTermId"),
        prefixed_field(parent_name, "Name", "CvTermName", "lang_alt"),
        prefixed_field(parent_name, "RefinedAbout", "CvTermRefinedAbout"),
    )


def location_fields(parent_name: str) -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field(
            parent_name, "Identifier", namespace_uri=XMP_NAMESPACE, field_list_kind="Bag"
        ),
        prefixed_field(parent_name, "City"),
        prefixed_field(parent_name, "CountryCode"),
        prefixed_field(parent_name, "CountryName"),
        prefixed_field(parent_name, "ProvinceState"),
        prefixed_field(parent_name, "Sublocation"),
        prefixed_field(parent_name, "WorldRegion"),
        prefixed_field(parent_name, "LocationId", field_list_kind="Bag"),
        prefixed_field(parent_name, "LocationName", value_kind="lang_alt"),
        prefixed_field(parent_name, "GPSLatitude", namespace_uri=EXIF_NAMESPACE),
        prefixed_field(parent_name, "GPSLongitude", namespace_uri=EXIF_NAMESPACE),
        prefixed_field(
            parent_name,
            "GPSAltitude",
            namespace_uri=EXIF_NAMESPACE,
            value_kind="rational",
        ),
        prefixed_field(
            parent_name,
            "GPSAltitudeRef",
            namespace_uri=EXIF_NAMESPACE,
            value_kind="integer",
        ),
    )


XMP_IPTC_FIELD_SPECS_BY_PARENT: tuple[
    tuple[str, tuple[XmpSimpleStructFieldSpec, ...]],
    ...,
] = (
    parent_fields(
        "CreatorContactInfo",
        (
            field("CreatorCity", "CiAdrCity", "CreatorCity"),
            field("CreatorCountry", "CiAdrCtry", "CreatorCountry"),
            field("CreatorAddress", "CiAdrExtadr", "CreatorAddress"),
            field("CreatorPostalCode", "CiAdrPcode", "CreatorPostalCode"),
            field("CreatorRegion", "CiAdrRegion", "CreatorRegion"),
            field("CreatorWorkEmail", "CiEmailWork", "CreatorWorkEmail"),
            field("CreatorWorkTelephone", "CiTelWork", "CreatorWorkTelephone"),
            field("CreatorWorkURL", "CiUrlWork", "CreatorWorkURL"),
        ),
    ),
    parent_fields("AboutCvTerm", cv_term_fields("AboutCvTerm")),
    parent_fields(
        "ArtworkOrObject",
        (
            field("ArtworkCopyrightNotice", "AOCopyrightNotice", "ArtworkCopyrightNotice"),
            field(
                "ArtworkCreator",
                "AOCreator",
                "ArtworkCreator",
                field_list_kind="Seq",
            ),
            field("ArtworkDateCreated", "AODateCreated", "ArtworkDateCreated", "date"),
            field("ArtworkSource", "AOSource", "ArtworkSource"),
            field("ArtworkSourceInventoryNo", "AOSourceInvNo", "ArtworkSourceInventoryNo"),
            field("ArtworkTitle", "AOTitle", "ArtworkTitle", "lang_alt"),
            field(
                "ArtworkCopyrightOwnerName",
                "AOCurrentCopyrightOwnerName",
                "ArtworkCopyrightOwnerName",
            ),
            field(
                "ArtworkCopyrightOwnerID",
                "AOCurrentCopyrightOwnerId",
                "ArtworkCopyrightOwnerID",
            ),
            field("ArtworkLicensorName", "AOCurrentLicensorName", "ArtworkLicensorName"),
            field("ArtworkLicensorID", "AOCurrentLicensorId", "ArtworkLicensorID"),
            field(
                "ArtworkCreatorID",
                "AOCreatorId",
                "ArtworkCreatorID",
                field_list_kind="Seq",
            ),
            field("ArtworkCircaDateCreated", "AOCircaDateCreated", "ArtworkCircaDateCreated"),
            field(
                "ArtworkStylePeriod",
                "AOStylePeriod",
                "ArtworkStylePeriod",
                field_list_kind="Bag",
            ),
            field("ArtworkSourceInvURL", "AOSourceInvURL", "ArtworkSourceInvURL"),
            field(
                "ArtworkContentDescription",
                "AOContentDescription",
                "ArtworkContentDescription",
                "lang_alt",
            ),
            field(
                "ArtworkContributionDescription",
                "AOContributionDescription",
                "ArtworkContributionDescription",
                "lang_alt",
            ),
            field(
                "ArtworkPhysicalDescription",
                "AOPhysicalDescription",
                "ArtworkPhysicalDescription",
                "lang_alt",
            ),
        ),
    ),
    parent_fields("ContainerFormat", entity_fields("ContainerFormat")),
    parent_fields("Contributor", entity_with_role_fields("Contributor")),
    parent_fields("Creator", entity_with_role_fields("Creator")),
    parent_fields(
        "DataOnScreen",
        (
            prefixed_field("DataOnScreen", "RegionText", "RegionText"),
            nested_field(
                "DataOnScreenRegionX",
                "x",
                "DataOnScreenRegionX",
                (iptc_path_step("Region"),),
                "real",
                namespace_uri=ST_AREA_NAMESPACE,
            ),
            nested_field(
                "DataOnScreenRegionY",
                "y",
                "DataOnScreenRegionY",
                (iptc_path_step("Region"),),
                "real",
                namespace_uri=ST_AREA_NAMESPACE,
            ),
            nested_field(
                "DataOnScreenRegionW",
                "w",
                "DataOnScreenRegionW",
                (iptc_path_step("Region"),),
                "real",
                namespace_uri=ST_AREA_NAMESPACE,
            ),
            nested_field(
                "DataOnScreenRegionH",
                "h",
                "DataOnScreenRegionH",
                (iptc_path_step("Region"),),
                "real",
                namespace_uri=ST_AREA_NAMESPACE,
            ),
            nested_field(
                "DataOnScreenRegionD",
                "d",
                "DataOnScreenRegionD",
                (iptc_path_step("Region"),),
                "real",
                namespace_uri=ST_AREA_NAMESPACE,
            ),
            nested_field(
                "DataOnScreenRegionUnit",
                "unit",
                "DataOnScreenRegionUnit",
                (iptc_path_step("Region"),),
                namespace_uri=ST_AREA_NAMESPACE,
            ),
        ),
    ),
    parent_fields(
        "DopesheetLink",
        (
            prefixed_field("DopesheetLink", "Link"),
            prefixed_field("DopesheetLink", "LinkQualifier"),
        ),
    ),
    parent_fields(
        "EmbdEncRightsExpr",
        (
            field("EmbeddedEncodedRightsExpr", "EncRightsExpr", "EmbeddedEncodedRightsExpr"),
            field(
                "EmbeddedEncodedRightsExprType",
                "RightsExprEncType",
                "EmbeddedEncodedRightsExprType",
            ),
            field(
                "EmbeddedEncodedRightsExprLangID",
                "RightsExprLangId",
                "EmbeddedEncodedRightsExprLangID",
            ),
        ),
    ),
    parent_fields(
        "Episode",
        (
            prefixed_field("Episode", "Name"),
            prefixed_field("Episode", "Number"),
            prefixed_field("Episode", "Identifier"),
        ),
    ),
    parent_fields("Genre", cv_term_fields("Genre")),
    parent_fields(
        "LinkedEncRightsExpr",
        (
            field("LinkedEncodedRightsExpr", "LinkedRightsExpr", "LinkedEncodedRightsExpr"),
            field(
                "LinkedEncodedRightsExprType",
                "RightsExprEncType",
                "LinkedEncodedRightsExprType",
            ),
            field(
                "LinkedEncodedRightsExprLangID",
                "RightsExprLangId",
                "LinkedEncodedRightsExprLangID",
            ),
        ),
    ),
    parent_fields("LocationCreated", location_fields("LocationCreated")),
    parent_fields("LocationShown", location_fields("LocationShown")),
    parent_fields("MetadataAuthority", entity_fields("MetadataAuthority")),
    parent_fields("MetadataLastEditor", entity_fields("MetadataLastEditor")),
    parent_fields("PersonHeard", entity_fields("PersonHeard")),
    parent_fields(
        "ImageRegion",
        (
            field("ImageRegionID", "rId", "ImageRegionID"),
            field("ImageRegionName", "Name", "ImageRegionName", "lang_alt"),
            nested_field(
                "ImageRegionBoundaryShape",
                "rbShape",
                "ImageRegionBoundaryShape",
                (iptc_path_step("RegionBoundary"),),
            ),
            nested_field(
                "ImageRegionBoundaryUnit",
                "rbUnit",
                "ImageRegionBoundaryUnit",
                (iptc_path_step("RegionBoundary"),),
            ),
            nested_field(
                "ImageRegionBoundaryX",
                "rbX",
                "ImageRegionBoundaryX",
                (iptc_path_step("RegionBoundary"),),
                "real",
            ),
            nested_field(
                "ImageRegionBoundaryY",
                "rbY",
                "ImageRegionBoundaryY",
                (iptc_path_step("RegionBoundary"),),
                "real",
            ),
            nested_field(
                "ImageRegionBoundaryW",
                "rbW",
                "ImageRegionBoundaryW",
                (iptc_path_step("RegionBoundary"),),
                "real",
            ),
            nested_field(
                "ImageRegionBoundaryH",
                "rbH",
                "ImageRegionBoundaryH",
                (iptc_path_step("RegionBoundary"),),
                "real",
            ),
            nested_field(
                "ImageRegionBoundaryRx",
                "rbRx",
                "ImageRegionBoundaryRx",
                (iptc_path_step("RegionBoundary"),),
                "real",
            ),
            nested_field(
                "ImageRegionBoundaryVerticesX",
                "rbX",
                "ImageRegionBoundaryVerticesX",
                (
                    iptc_path_step("RegionBoundary"),
                    iptc_path_step("rbVertices", "Seq"),
                ),
                "real",
            ),
            nested_field(
                "ImageRegionBoundaryVerticesY",
                "rbY",
                "ImageRegionBoundaryVerticesY",
                (
                    iptc_path_step("RegionBoundary"),
                    iptc_path_step("rbVertices", "Seq"),
                ),
                "real",
            ),
            nested_field(
                "ImageRegionCtypeIdentifier",
                "Identifier",
                "ImageRegionCtypeIdentifier",
                (iptc_path_step("rCtype", "Bag"),),
                namespace_uri=XMP_NAMESPACE,
                field_list_kind="Bag",
            ),
            nested_field(
                "ImageRegionCtypeName",
                "Name",
                "ImageRegionCtypeName",
                (iptc_path_step("rCtype", "Bag"),),
                "lang_alt",
            ),
            nested_field(
                "ImageRegionRoleIdentifier",
                "Identifier",
                "ImageRegionRoleIdentifier",
                (iptc_path_step("rRole", "Bag"),),
                namespace_uri=XMP_NAMESPACE,
                field_list_kind="Bag",
            ),
            nested_field(
                "ImageRegionRoleName",
                "Name",
                "ImageRegionRoleName",
                (iptc_path_step("rRole", "Bag"),),
                "lang_alt",
            ),
        ),
    ),
    parent_fields(
        "PersonInImageWDetails",
        (
            field(
                "PersonInImageId",
                "PersonId",
                "PersonInImageId",
                field_list_kind="Bag",
            ),
            field("PersonInImageName", "PersonName", "PersonInImageName", "lang_alt"),
            nested_field(
                "PersonInImageWDetailsPersonCharacteristicCvId",
                "CvId",
                "PersonInImageCvTermCvId",
                (iptc_path_step("PersonCharacteristic", "Bag"),),
            ),
            nested_field(
                "PersonInImageWDetailsPersonCharacteristicCvTermId",
                "CvTermId",
                "PersonInImageCvTermId",
                (iptc_path_step("PersonCharacteristic", "Bag"),),
            ),
            nested_field(
                "PersonInImageWDetailsPersonCharacteristicCvTermName",
                "CvTermName",
                "PersonInImageCvTermName",
                (iptc_path_step("PersonCharacteristic", "Bag"),),
                "lang_alt",
            ),
            nested_field(
                "PersonInImageWDetailsPersonCharacteristicCvTermRefinedAbout",
                "CvTermRefinedAbout",
                "PersonInImageCvTermRefinedAbout",
                (iptc_path_step("PersonCharacteristic", "Bag"),),
            ),
            field(
                "PersonInImageDescription",
                "PersonDescription",
                "PersonInImageDescription",
                "lang_alt",
            ),
        ),
    ),
    parent_fields("PlanningRef", entity_with_role_fields("PlanningRef")),
    parent_fields(
        "ProductInImage",
        (
            prefixed_field("ProductInImage", "Name", "ProductName", "lang_alt"),
            prefixed_field("ProductInImage", "GTIN", "ProductGTIN"),
            prefixed_field("ProductInImage", "Description", "ProductDescription", "lang_alt"),
            prefixed_field("ProductInImage", "Id", "ProductId"),
        ),
    ),
    parent_fields(
        "PublicationEvent",
        (
            prefixed_field("PublicationEvent", "Date", value_kind="date"),
            prefixed_field("PublicationEvent", "Name"),
            prefixed_field("PublicationEvent", "Identifier"),
        ),
    ),
    parent_fields(
        "Rating",
        (
            prefixed_field("Rating", "Value", "RatingValue"),
            prefixed_field("Rating", "SourceLink", "RatingSourceLink"),
            prefixed_field("Rating", "ScaleMinValue", "RatingScaleMinValue"),
            prefixed_field("Rating", "ScaleMaxValue", "RatingScaleMaxValue"),
            prefixed_field("Rating", "ValueLogoLink", "RatingValueLogoLink"),
            *(
                XmpSimpleStructFieldSpec(
                    suffix=f"RatingRegion{field_spec.suffix.removeprefix('RatingRegion')}",
                    field_name=field_spec.field_name,
                    readback_suffix=field_spec.readback_suffix,
                    value_kind=field_spec.value_kind,
                    namespace_uri=field_spec.namespace_uri,
                    field_list_kind=field_spec.field_list_kind,
                    nested_path=(iptc_path_step("RatingRegion", "Bag"),),
                )
                for field_spec in location_fields("RatingRegion")
            ),
        ),
    ),
    parent_fields(
        "RecDevice",
        (
            prefixed_field("RecDevice", "Manufacturer"),
            prefixed_field("RecDevice", "ModelName"),
            prefixed_field("RecDevice", "SerialNumber"),
            prefixed_field("RecDevice", "AttLensDescription"),
            prefixed_field("RecDevice", "OwnersDeviceId"),
        ),
    ),
    parent_fields(
        "RegistryID",
        (
            field("RegistryItemID", "RegItemId", "RegistryItemID"),
            field("RegistryOrganisationID", "RegOrgId", "RegistryOrganisationID"),
            field("RegistryEntryRole", "RegEntryRole", "RegistryEntryRole"),
        ),
    ),
    parent_fields(
        "Season",
        (
            prefixed_field("Season", "Name"),
            prefixed_field("Season", "Number"),
            prefixed_field("Season", "Identifier"),
        ),
    ),
    parent_fields(
        "Series",
        (
            prefixed_field("Series", "Name"),
            prefixed_field("Series", "Identifier"),
        ),
    ),
    parent_fields("ShownEvent", entity_fields("ShownEvent")),
    parent_fields(
        "Snapshot",
        (
            field("SnapshotLink", "Link", "SnapshotLink"),
            field(
                "SnapshotLinkQualifier",
                "LinkQualifier",
                "SnapshotLinkQualifier",
                field_list_kind="Bag",
            ),
            field("SnapshotImageRole", "ImageRole", "SnapshotImageRole"),
            field("SnapshotFormat", "format", "SnapshotFormat", namespace_uri=DC_NAMESPACE),
            field("SnapshotWidthPixels", "WidthPixels", "SnapshotWidthPixels", "integer"),
            field("SnapshotHeightPixels", "HeightPixels", "SnapshotHeightPixels", "integer"),
            nested_field(
                "SnapshotUsedVideoFrameTimeFormat",
                "timeFormat",
                "SnapshotUsedVideoFrameTimeFormat",
                (iptc_path_step("UsedVideoFrame"),),
                namespace_uri=XMP_DM_NAMESPACE,
            ),
            nested_field(
                "SnapshotUsedVideoFrameTimeValue",
                "timeValue",
                "SnapshotUsedVideoFrameTimeValue",
                (iptc_path_step("UsedVideoFrame"),),
                namespace_uri=XMP_DM_NAMESPACE,
            ),
            nested_field(
                "SnapshotUsedVideoFrameValue",
                "value",
                "SnapshotUsedVideoFrameValue",
                (iptc_path_step("UsedVideoFrame"),),
                "integer",
                namespace_uri=XMP_DM_NAMESPACE,
            ),
        ),
    ),
    parent_fields("SupplyChainSource", entity_fields("SupplyChainSource")),
    parent_fields(
        "TemporalCoverage",
        (
            field("TemporalCoverageFrom", "tempCoverageFrom", "TemporalCoverageFrom", "date"),
            field("TemporalCoverageTo", "tempCoverageTo", "TemporalCoverageTo", "date"),
        ),
    ),
    parent_fields(
        "TranscriptLink",
        (
            prefixed_field("TranscriptLink", "Link"),
            prefixed_field("TranscriptLink", "LinkQualifier"),
        ),
    ),
    parent_fields("VideoShotType", entity_fields("VideoShotType")),
    parent_fields("WorkflowTag", cv_term_fields("WorkflowTag")),
)

XMP_IPTC_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = tuple(
    field_spec for _, field_specs in XMP_IPTC_FIELD_SPECS_BY_PARENT for field_spec in field_specs
)


def iptc_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(XMP_IPTC_PARENT_SPECS, property_name)


def iptc_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group not in {"XMP-iptcCore", "XMP-iptcExt"} or separator != ":":
        return None
    for parent_spec in XMP_IPTC_PARENT_SPECS:
        if group != parent_spec.group:
            continue
        for field_spec in iptc_field_specs_for_parent(parent_spec.parent_name):
            if tag_name == field_spec.readback_suffix:
                return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def iptc_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    for candidate_parent_name, field_specs in XMP_IPTC_FIELD_SPECS_BY_PARENT:
        if candidate_parent_name == parent_name:
            return field_specs
    return ()


def iptc_readback_tag_ids() -> dict[str, str]:
    return {
        **iptc_core_readback_tag_ids(),
        **iptc_ext_readback_tag_ids(),
    }


def iptc_core_readback_tag_ids() -> dict[str, str]:
    return iptc_readback_tag_ids_for_group("XMP-iptcCore")


def iptc_ext_readback_tag_ids() -> dict[str, str]:
    return iptc_readback_tag_ids_for_group("XMP-iptcExt")


def iptc_readback_tag_ids_for_group(group: str) -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_IPTC_PARENT_SPECS:
        if parent_spec.group != group:
            continue
        for field_spec in iptc_field_specs_for_parent(parent_spec.parent_name):
            tag_ids[field_spec.readback_suffix] = parent_spec.element_name
    return tag_ids
