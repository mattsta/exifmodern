"""Source-grounded XMP Dynamic Media struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    simple_struct_field_spec_for_field_name,
    simple_struct_field_spec_for_suffix,
    simple_struct_parent_spec_for_property,
    simple_struct_readback_tag_ids,
)

XMPDM_NAMESPACE = "http://ns.adobe.com/xmp/1.0/DynamicMedia/"
ST_DIM_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/Dimensions#"
XMPG_NAMESPACE = "http://ns.adobe.com/xap/1.0/g/"

XMP_DYNAMIC_MEDIA_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    XmpSimpleStructParentSpec(
        parent_name="AltTimecode",
        property_name="XMP-xmpDM:AltTimecode",
        element_name="AltTimecode",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="BeatSpliceParams",
        property_name="XMP-xmpDM:BeatSpliceParams",
        element_name="BeatSpliceParams",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="ContributedMedia",
        property_name="XMP-xmpDM:ContributedMedia",
        element_name="ContributedMedia",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct_list",
        list_kind="Bag",
    ),
    XmpSimpleStructParentSpec(
        parent_name="Duration",
        property_name="XMP-xmpDM:Duration",
        element_name="Duration",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="IntroTime",
        property_name="XMP-xmpDM:IntroTime",
        element_name="IntroTime",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="Markers",
        property_name="XMP-xmpDM:Markers",
        element_name="Markers",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct_list",
        list_kind="Seq",
    ),
    XmpSimpleStructParentSpec(
        parent_name="OutCue",
        property_name="XMP-xmpDM:OutCue",
        element_name="OutCue",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="ProjectRef",
        property_name="XMP-xmpDM:ProjectRef",
        element_name="ProjectRef",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="RelativeTimestamp",
        property_name="XMP-xmpDM:RelativeTimestamp",
        element_name="RelativeTimestamp",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="ResampleParams",
        property_name="XMP-xmpDM:ResampleParams",
        element_name="ResampleParams",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="StartTimecode",
        property_name="XMP-xmpDM:StartTimecode",
        element_name="StartTimecode",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="TimeScaleParams",
        property_name="XMP-xmpDM:TimeScaleParams",
        element_name="TimeScaleParams",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="Tracks",
        property_name="XMP-xmpDM:Tracks",
        element_name="Tracks",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpDM",
        struct_namespace_uri=XMPDM_NAMESPACE,
        shape="struct_list",
        list_kind="Bag",
    ),
    XmpSimpleStructParentSpec(
        parent_name="VideoAlphaPremultipleColor",
        property_name="XMP-xmpDM:VideoAlphaPremultipleColor",
        element_name="VideoAlphaPremultipleColor",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="xmpG",
        struct_namespace_uri=XMPG_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="VideoFrameSize",
        property_name="XMP-xmpDM:VideoFrameSize",
        element_name="VideoFrameSize",
        group="XMP-xmpDM",
        namespace_prefix="xmpDM",
        struct_namespace_prefix="stDim",
        struct_namespace_uri=ST_DIM_NAMESPACE,
        shape="struct",
    ),
)

XMP_DYNAMIC_MEDIA_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = (
    XmpSimpleStructFieldSpec("TimeFormat", "timeFormat", "TimeFormat", "text"),
    XmpSimpleStructFieldSpec("TimeValue", "timeValue", "TimeValue", "text"),
    XmpSimpleStructFieldSpec("Scale", "scale", "Scale", "rational"),
    XmpSimpleStructFieldSpec("Value", "value", "Value", "integer"),
    XmpSimpleStructFieldSpec("RiseInDecibel", "riseInDecibel", "RiseInDecibel", "real"),
    XmpSimpleStructFieldSpec(
        "RiseInTimeDurationScale",
        "scale",
        "RiseInTimeDurationScale",
        "rational",
        nested_field_name="riseInTimeDuration",
    ),
    XmpSimpleStructFieldSpec(
        "RiseInTimeDurationValue",
        "value",
        "RiseInTimeDurationValue",
        "integer",
        nested_field_name="riseInTimeDuration",
    ),
    XmpSimpleStructFieldSpec(
        "UseFileBeatsMarker",
        "useFileBeatsMarker",
        "UseFileBeatsMarker",
        "boolean",
    ),
    XmpSimpleStructFieldSpec(
        "DurationScale",
        "scale",
        "DurationScale",
        "rational",
        nested_field_name="duration",
    ),
    XmpSimpleStructFieldSpec(
        "DurationValue",
        "value",
        "DurationValue",
        "integer",
        nested_field_name="duration",
    ),
    XmpSimpleStructFieldSpec("Managed", "managed", "Managed", "boolean"),
    XmpSimpleStructFieldSpec("Path", "path", "Path", "text"),
    XmpSimpleStructFieldSpec(
        "StartTimeScale",
        "scale",
        "StartTimeScale",
        "rational",
        nested_field_name="startTime",
    ),
    XmpSimpleStructFieldSpec(
        "StartTimeValue",
        "value",
        "StartTimeValue",
        "integer",
        nested_field_name="startTime",
    ),
    XmpSimpleStructFieldSpec("Track", "track", "Track", "text"),
    XmpSimpleStructFieldSpec("WebStatement", "webStatement", "WebStatement", "text"),
    XmpSimpleStructFieldSpec("ProjectPath", "path", "Path", "text"),
    XmpSimpleStructFieldSpec("ProjectType", "type", "Type", "text"),
    XmpSimpleStructFieldSpec("Quality", "quality", "Quality", "text"),
    XmpSimpleStructFieldSpec(
        "FrameOverlappingPercentage",
        "frameOverlappingPercentage",
        "FrameOverlappingPercentage",
        "real",
    ),
    XmpSimpleStructFieldSpec("FrameSize", "frameSize", "FrameSize", "real"),
    XmpSimpleStructFieldSpec("ColorantSwatchName", "swatchName", "SwatchName", "text"),
    XmpSimpleStructFieldSpec("ColorantMode", "mode", "Mode", "text"),
    XmpSimpleStructFieldSpec("ColorantType", "type", "Type", "text"),
    XmpSimpleStructFieldSpec("ColorantCyan", "cyan", "Cyan", "real"),
    XmpSimpleStructFieldSpec("ColorantMagenta", "magenta", "Magenta", "real"),
    XmpSimpleStructFieldSpec("ColorantYellow", "yellow", "Yellow", "real"),
    XmpSimpleStructFieldSpec("ColorantBlack", "black", "Black", "real"),
    XmpSimpleStructFieldSpec("ColorantRed", "red", "Red", "integer"),
    XmpSimpleStructFieldSpec("ColorantGreen", "green", "Green", "integer"),
    XmpSimpleStructFieldSpec("ColorantBlue", "blue", "Blue", "integer"),
    XmpSimpleStructFieldSpec("ColorantGray", "gray", "Gray", "integer"),
    XmpSimpleStructFieldSpec("ColorantL", "L", "L", "real"),
    XmpSimpleStructFieldSpec("ColorantA", "A", "A", "integer"),
    XmpSimpleStructFieldSpec("ColorantB", "B", "B", "integer"),
    XmpSimpleStructFieldSpec("ColorantTint", "tint", "Tint", "integer"),
    XmpSimpleStructFieldSpec("W", "w", "W", "real"),
    XmpSimpleStructFieldSpec("H", "h", "H", "real"),
    XmpSimpleStructFieldSpec("Unit", "unit", "Unit", "text"),
    XmpSimpleStructFieldSpec("Comment", "comment", "Comment", "text"),
    XmpSimpleStructFieldSpec("Duration", "duration", "Duration", "text"),
    XmpSimpleStructFieldSpec("Location", "location", "Location", "text"),
    XmpSimpleStructFieldSpec("Name", "name", "Name", "text"),
    XmpSimpleStructFieldSpec("StartTime", "startTime", "StartTime", "text"),
    XmpSimpleStructFieldSpec("Target", "target", "Target", "text"),
    XmpSimpleStructFieldSpec("Type", "type", "Type", "text"),
    XmpSimpleStructFieldSpec("CuePointType", "cuePointType", "CuePointType", "text"),
    XmpSimpleStructFieldSpec("Probability", "probability", "Probability", "real"),
    XmpSimpleStructFieldSpec("Speaker", "speaker", "Speaker", "text"),
    XmpSimpleStructFieldSpec(
        "CuePointParamsKey",
        "key",
        "CuePointParamsKey",
        "text",
        nested_field_name="cuePointParams",
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "CuePointParamsValue",
        "value",
        "CuePointParamsValue",
        "text",
        nested_field_name="cuePointParams",
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec("FrameRate", "frameRate", "FrameRate", "text"),
    XmpSimpleStructFieldSpec("TrackName", "trackName", "TrackName", "text"),
    XmpSimpleStructFieldSpec("TrackType", "trackType", "TrackType", "text"),
    XmpSimpleStructFieldSpec(
        "MarkersName",
        "name",
        "MarkersName",
        "text",
        nested_field_name="markers",
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "MarkersStartTime",
        "startTime",
        "MarkersStartTime",
        "text",
        nested_field_name="markers",
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "MarkersType",
        "type",
        "MarkersType",
        "text",
        nested_field_name="markers",
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "MarkersProbability",
        "probability",
        "MarkersProbability",
        "real",
        nested_field_name="markers",
        nested_list_kind="Seq",
    ),
)


def dynamic_media_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(XMP_DYNAMIC_MEDIA_PARENT_SPECS, property_name)


def dynamic_media_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-xmpDM" or separator != ":":
        return None
    for parent_spec in sorted(
        XMP_DYNAMIC_MEDIA_PARENT_SPECS,
        key=lambda item: len(item.parent_name),
        reverse=True,
    ):
        if not tag_name.startswith(parent_spec.parent_name):
            continue
        field_suffix = tag_name.removeprefix(parent_spec.parent_name)
        field_spec = dynamic_media_field_spec_for_parent_and_suffix(
            parent_spec.parent_name,
            field_suffix,
        )
        if field_spec is None:
            continue
        return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def dynamic_media_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    if parent_name in {"AltTimecode", "StartTimecode"}:
        return dynamic_media_field_specs_for_suffixes(
            ("TimeFormat", "TimeValue", "Value"),
        )
    if parent_name in {"Duration", "IntroTime", "OutCue", "RelativeTimestamp"}:
        return dynamic_media_field_specs_for_suffixes(("Scale", "Value"))
    if parent_name == "Markers":
        return dynamic_media_field_specs_for_suffixes(
            (
                "Comment",
                "Duration",
                "Location",
                "Name",
                "StartTime",
                "Target",
                "Type",
                "CuePointType",
                "Probability",
                "Speaker",
                "CuePointParamsKey",
                "CuePointParamsValue",
            ),
        )
    if parent_name == "BeatSpliceParams":
        return dynamic_media_field_specs_for_suffixes(
            (
                "RiseInDecibel",
                "RiseInTimeDurationScale",
                "RiseInTimeDurationValue",
                "UseFileBeatsMarker",
            ),
        )
    if parent_name == "ContributedMedia":
        return dynamic_media_field_specs_for_suffixes(
            (
                "DurationScale",
                "DurationValue",
                "Managed",
                "Path",
                "StartTimeScale",
                "StartTimeValue",
                "Track",
                "WebStatement",
            ),
        )
    if parent_name == "ProjectRef":
        return dynamic_media_field_specs_for_suffixes(("ProjectPath", "ProjectType"))
    if parent_name == "ResampleParams":
        return dynamic_media_field_specs_for_suffixes(("Quality",))
    if parent_name == "TimeScaleParams":
        return dynamic_media_field_specs_for_suffixes(
            ("FrameOverlappingPercentage", "FrameSize", "Quality"),
        )
    if parent_name == "Tracks":
        return dynamic_media_field_specs_for_suffixes(
            (
                "FrameRate",
                "TrackName",
                "TrackType",
                "MarkersName",
                "MarkersStartTime",
                "MarkersType",
                "MarkersProbability",
            ),
        )
    if parent_name == "VideoAlphaPremultipleColor":
        return dynamic_media_field_specs_for_suffixes(
            (
                "ColorantSwatchName",
                "ColorantMode",
                "ColorantType",
                "ColorantCyan",
                "ColorantMagenta",
                "ColorantYellow",
                "ColorantBlack",
                "ColorantRed",
                "ColorantGreen",
                "ColorantBlue",
                "ColorantGray",
                "ColorantL",
                "ColorantA",
                "ColorantB",
                "ColorantTint",
            ),
        )
    if parent_name == "VideoFrameSize":
        return dynamic_media_field_specs_for_suffixes(("W", "H", "Unit"))
    return ()


def dynamic_media_field_specs_for_suffixes(
    suffixes: tuple[str, ...],
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    specs: list[XmpSimpleStructFieldSpec] = []
    for suffix in suffixes:
        field_spec = dynamic_media_field_spec_for_suffix(suffix)
        if field_spec is not None:
            specs.append(field_spec)
    return tuple(specs)


def dynamic_media_field_spec_for_parent_and_suffix(
    parent_name: str,
    suffix: str,
) -> XmpSimpleStructFieldSpec | None:
    for field_spec in dynamic_media_field_specs_for_parent(parent_name):
        if field_spec.suffix == suffix:
            return field_spec
    return None


def dynamic_media_field_spec_for_suffix(suffix: str) -> XmpSimpleStructFieldSpec | None:
    return simple_struct_field_spec_for_suffix(XMP_DYNAMIC_MEDIA_FIELD_SPECS, suffix)


def dynamic_media_field_spec_for_field_name(field_name: str) -> XmpSimpleStructFieldSpec | None:
    return simple_struct_field_spec_for_field_name(XMP_DYNAMIC_MEDIA_FIELD_SPECS, field_name)


def dynamic_media_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_DYNAMIC_MEDIA_PARENT_SPECS:
        field_specs = dynamic_media_field_specs_for_parent(parent_spec.parent_name)
        tag_ids.update(simple_struct_readback_tag_ids((parent_spec,), field_specs))
    return tag_ids
