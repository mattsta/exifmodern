"""XMP group deletion plan primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type XmpGroupDeleteTarget = Literal["XMP"]
type XmpNamespaceDeleteTarget = Literal[
    "XMP-dc",
    "XMP-photoshop",
    "XMP-xmpBJ",
    "XMP-xmpMM",
    "XMP-xmpRights",
]

XMP_GROUP_DELETE_SOURCE_ID = "xmp.group_delete.jpeg_xmp_segments"
XMP_SEGMENT_DISCOVERY_SOURCE_ID = "xmp.group_delete.jpeg_app1_discovery"
XMP_NAMESPACE_GROUP_DELETE_SOURCE_ID = "xmp.group_delete.family1_namespace"


@dataclass(frozen=True)
class XmpGroupDeletePlan:
    target: XmpGroupDeleteTarget
    source_reference_ids: tuple[str, ...]


@dataclass(frozen=True)
class XmpNamespaceDeletePlan:
    target: XmpNamespaceDeleteTarget
    namespace_uri: str
    source_reference_ids: tuple[str, ...]


def build_xmp_group_delete_plan() -> XmpGroupDeletePlan:
    return XmpGroupDeletePlan(
        target="XMP",
        source_reference_ids=(XMP_GROUP_DELETE_SOURCE_ID, XMP_SEGMENT_DISCOVERY_SOURCE_ID),
    )


def build_xmp_namespace_delete_plan(target: XmpNamespaceDeleteTarget) -> XmpNamespaceDeletePlan:
    return XmpNamespaceDeletePlan(
        target=target,
        namespace_uri=xmp_namespace_delete_uri(target),
        source_reference_ids=(XMP_NAMESPACE_GROUP_DELETE_SOURCE_ID,),
    )


def xmp_namespace_delete_target(value: str) -> XmpNamespaceDeleteTarget:
    if value == "XMP-dc":
        return "XMP-dc"
    if value == "XMP-photoshop":
        return "XMP-photoshop"
    if value == "XMP-xmpBJ":
        return "XMP-xmpBJ"
    if value == "XMP-xmpMM":
        return "XMP-xmpMM"
    if value == "XMP-xmpRights":
        return "XMP-xmpRights"
    raise ValueError(
        "XMP namespace delete target must be XMP-dc, XMP-photoshop, "
        "XMP-xmpBJ, XMP-xmpMM, or XMP-xmpRights."
    )


def xmp_namespace_delete_uri(target: XmpNamespaceDeleteTarget) -> str:
    if target == "XMP-dc":
        return "http://purl.org/dc/elements/1.1/"
    if target == "XMP-photoshop":
        return "http://ns.adobe.com/photoshop/1.0/"
    if target == "XMP-xmpBJ":
        return "http://ns.adobe.com/xap/1.0/bj/"
    if target == "XMP-xmpMM":
        return "http://ns.adobe.com/xap/1.0/mm/"
    return "http://ns.adobe.com/xap/1.0/rights/"
