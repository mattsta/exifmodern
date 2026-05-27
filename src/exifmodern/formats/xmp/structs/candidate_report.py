"""Reusable reports for remaining generated XMP struct-adapter candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.xmp.structs.acdsee_regions import XMP_ACDSEE_REGION_PARENT_SPECS
from exifmodern.formats.xmp.structs.basic_image import XMP_BASIC_IMAGE_PARENT_SPECS
from exifmodern.formats.xmp.structs.camera_raw import XMP_CAMERA_RAW_PARENT_SPECS
from exifmodern.formats.xmp.structs.creator_atom import XMP_CREATOR_ATOM_PARENT_SPECS
from exifmodern.formats.xmp.structs.dynamic_media import XMP_DYNAMIC_MEDIA_PARENT_SPECS
from exifmodern.formats.xmp.structs.exif_extended import XMP_EXIF_EXTENDED_PARENT_SPECS
from exifmodern.formats.xmp.structs.exif_struct import XMP_EXIF_STRUCT_PARENT_SPECS
from exifmodern.formats.xmp.structs.ics import XMP_ICS_PARENT_SPECS
from exifmodern.formats.xmp.structs.iptc import XMP_IPTC_PARENT_SPECS
from exifmodern.formats.xmp.structs.job_ref import XMP_JOB_REF_PARENT_SPECS
from exifmodern.formats.xmp.structs.manifest_item import XMP_MANIFEST_ITEM_PARENT_SPECS
from exifmodern.formats.xmp.structs.media_management import (
    XMP_MEDIA_MANAGEMENT_PARENT_SPECS,
)
from exifmodern.formats.xmp.structs.paged_text import XMP_PAGED_TEXT_PARENT_SPECS
from exifmodern.formats.xmp.structs.pantry_item import XMP_PANTRY_ITEM_PARENT_SPECS
from exifmodern.formats.xmp.structs.photoshop import XMP_PHOTOSHOP_PARENT_SPECS
from exifmodern.formats.xmp.structs.prism import XMP_PRISM_PARENT_SPECS
from exifmodern.formats.xmp.structs.resource_event import XMP_RESOURCE_EVENT_PARENT_SPECS
from exifmodern.formats.xmp.structs.resource_ref import XMP_RESOURCE_REF_PARENT_SPECS
from exifmodern.json_types import (
    JsonArray,
    JsonObject,
    json_array_value,
    json_string_value,
    load_json_object,
)

type XmpStructCandidateGroupKey = tuple[str, str, str]


@dataclass(frozen=True)
class XmpStructCandidate:
    property_name: str
    namespace: str
    tag_id: str
    tag_name: str
    shape: str
    list_kind: str | None
    effective_writable: str
    supported_now: bool

    def group_key(self) -> XmpStructCandidateGroupKey:
        return (self.namespace, self.shape, self.list_kind or "none")

    def to_json_object(self) -> JsonObject:
        return {
            "effective_writable": self.effective_writable,
            "list_kind": self.list_kind,
            "namespace": self.namespace,
            "property_name": self.property_name,
            "shape": self.shape,
            "supported_now": self.supported_now,
            "tag_id": self.tag_id,
            "tag_name": self.tag_name,
        }


def xmp_struct_candidate_report(capability_audit_path: Path) -> JsonObject:
    candidates = xmp_struct_candidates(capability_audit_path)
    unsupported_candidates = tuple(
        candidate for candidate in candidates if not candidate.supported_now
    )
    supported_candidates = tuple(candidate for candidate in candidates if candidate.supported_now)
    unsupported_groups = candidate_groups(unsupported_candidates)
    return {
        "candidate_count": len(candidates),
        "candidates": candidate_items(candidates),
        "group_count": len(unsupported_groups),
        "groups": candidate_group_items(unsupported_groups, "namespace"),
        "ranked_groups": candidate_group_items(unsupported_groups, "priority"),
        "supported_candidate_count": len(supported_candidates),
        "supported_parent_properties": supported_parent_property_items(),
        "unsupported_candidate_count": len(unsupported_candidates),
    }


def write_xmp_struct_candidate_report(
    capability_audit_path: Path,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            xmp_struct_candidate_report(capability_audit_path),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def xmp_struct_candidates(capability_audit_path: Path) -> tuple[XmpStructCandidate, ...]:
    payload = load_json_object(capability_audit_path)
    candidates: list[XmpStructCandidate] = []
    supported_properties = supported_struct_parent_properties()
    for item in json_array_value(payload, "capabilities"):
        if not isinstance(item, dict):
            continue
        candidate = xmp_struct_candidate_from_json(item, supported_properties)
        if candidate is not None:
            candidates.append(candidate)
    return tuple(sorted(candidates, key=lambda candidate: candidate.property_name))


def xmp_struct_candidate_from_json(
    item: JsonObject,
    supported_properties: frozenset[str],
) -> XmpStructCandidate | None:
    if json_string_value(item, "modernization_strategy") != "generated_struct_adapter":
        return None
    property_name = json_string_value(item, "property_name")
    namespace = json_string_value(item, "namespace")
    tag_id = json_string_value(item, "tag_id")
    tag_name = json_string_value(item, "tag_name")
    shape = json_string_value(item, "shape")
    effective_writable = json_string_value(item, "effective_writable")
    if (
        property_name is None
        or namespace is None
        or tag_id is None
        or tag_name is None
        or shape is None
        or effective_writable is None
    ):
        return None
    return XmpStructCandidate(
        property_name=property_name,
        namespace=namespace,
        tag_id=tag_id,
        tag_name=tag_name,
        shape=shape,
        list_kind=json_string_value(item, "list_kind"),
        effective_writable=effective_writable,
        supported_now=property_name in supported_properties,
    )


def supported_struct_parent_properties() -> frozenset[str]:
    properties: set[str] = set()
    for resource_ref_parent_spec in XMP_RESOURCE_REF_PARENT_SPECS:
        properties.add(resource_ref_parent_spec.property_name)
    for acdsee_region_parent_spec in XMP_ACDSEE_REGION_PARENT_SPECS:
        properties.add(acdsee_region_parent_spec.property_name)
    for dynamic_media_parent_spec in XMP_DYNAMIC_MEDIA_PARENT_SPECS:
        properties.add(dynamic_media_parent_spec.property_name)
    for camera_raw_parent_spec in XMP_CAMERA_RAW_PARENT_SPECS:
        properties.add(camera_raw_parent_spec.property_name)
    for creator_atom_parent_spec in XMP_CREATOR_ATOM_PARENT_SPECS:
        properties.add(creator_atom_parent_spec.property_name)
    for exif_extended_parent_spec in XMP_EXIF_EXTENDED_PARENT_SPECS:
        properties.add(exif_extended_parent_spec.property_name)
    for exif_parent_spec in XMP_EXIF_STRUCT_PARENT_SPECS:
        properties.add(exif_parent_spec.property_name)
    for ics_parent_spec in XMP_ICS_PARENT_SPECS:
        properties.add(ics_parent_spec.property_name)
    for resource_event_parent_spec in XMP_RESOURCE_EVENT_PARENT_SPECS:
        properties.add(resource_event_parent_spec.property_name)
    for job_ref_parent_spec in XMP_JOB_REF_PARENT_SPECS:
        properties.add(job_ref_parent_spec.property_name)
    for manifest_item_parent_spec in XMP_MANIFEST_ITEM_PARENT_SPECS:
        properties.add(manifest_item_parent_spec.property_name)
    for pantry_item_parent_spec in XMP_PANTRY_ITEM_PARENT_SPECS:
        properties.add(pantry_item_parent_spec.property_name)
    for paged_text_parent_spec in XMP_PAGED_TEXT_PARENT_SPECS:
        properties.add(paged_text_parent_spec.property_name)
    for media_management_parent_spec in XMP_MEDIA_MANAGEMENT_PARENT_SPECS:
        properties.add(media_management_parent_spec.property_name)
    for basic_image_parent_spec in XMP_BASIC_IMAGE_PARENT_SPECS:
        properties.add(basic_image_parent_spec.property_name)
    for iptc_parent_spec in XMP_IPTC_PARENT_SPECS:
        properties.add(iptc_parent_spec.property_name)
    for prism_parent_spec in XMP_PRISM_PARENT_SPECS:
        properties.add(prism_parent_spec.property_name)
    for photoshop_parent_spec in XMP_PHOTOSHOP_PARENT_SPECS:
        properties.add(photoshop_parent_spec.property_name)
    return frozenset(properties)


def supported_parent_property_items() -> JsonArray:
    items: JsonArray = []
    for property_name in sorted(supported_struct_parent_properties()):
        items.append(property_name)
    return items


def candidate_items(candidates: tuple[XmpStructCandidate, ...]) -> JsonArray:
    items: JsonArray = []
    for candidate in candidates:
        items.append(candidate.to_json_object())
    return items


def candidate_groups(
    candidates: tuple[XmpStructCandidate, ...],
) -> dict[XmpStructCandidateGroupKey, tuple[XmpStructCandidate, ...]]:
    grouped_candidates: dict[XmpStructCandidateGroupKey, list[XmpStructCandidate]] = {}
    for candidate in candidates:
        grouped_candidates.setdefault(candidate.group_key(), []).append(candidate)
    return {
        group_key: tuple(sorted(items, key=lambda item: item.property_name))
        for group_key, items in grouped_candidates.items()
    }


type XmpStructCandidateGroupOrder = Literal["namespace", "priority"]


def candidate_group_items(
    groups: dict[XmpStructCandidateGroupKey, tuple[XmpStructCandidate, ...]],
    order: XmpStructCandidateGroupOrder,
) -> JsonArray:
    items: JsonArray = []
    for (namespace, shape, list_kind), grouped_candidates in ordered_candidate_groups(
        groups,
        order,
    ):
        items.append(
            {
                "candidate_count": len(grouped_candidates),
                "candidates": candidate_items(grouped_candidates),
                "list_kind": None if list_kind == "none" else list_kind,
                "namespace": namespace,
                "shape": shape,
            }
        )
    return items


def ordered_candidate_groups(
    groups: dict[XmpStructCandidateGroupKey, tuple[XmpStructCandidate, ...]],
    order: XmpStructCandidateGroupOrder,
) -> tuple[tuple[XmpStructCandidateGroupKey, tuple[XmpStructCandidate, ...]], ...]:
    if order == "namespace":
        return tuple(sorted(groups.items()))
    return tuple(
        sorted(
            groups.items(),
            key=lambda item: (
                -len(item[1]),
                struct_list_priority(item[0][1]),
                item[0][0],
                item[0][2],
            ),
        )
    )


def struct_list_priority(shape: str) -> int:
    return 0 if shape == "struct_list" else 1
