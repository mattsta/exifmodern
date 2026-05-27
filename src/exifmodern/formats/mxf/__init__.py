"""MXF KLV metadata transaction planning helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.mxf.klv_transaction_plan import (
    MXF_CLOSED_COMPLETE_HEADER_UL,
    MXF_CLOSED_HEADER_UL,
    MXF_ESSENCE_ELEMENT_UL,
    MXF_INDEX_TABLE_SEGMENT_UL,
    MXF_KEY_SIZE,
    MXF_MAX_EXIFTOOL_IN_MEMORY_VALUE_SIZE,
    MXF_OPEN_COMPLETE_HEADER_UL,
    MXF_OPEN_HEADER_UL,
    MXF_PREFACE_UL,
    MXF_PRIMER_UL,
    MXF_RANDOM_INDEX_METADATA_UL,
    MxfBerLengthPlan,
    MxfEmissionGate,
    MxfHeaderPartitionValidationPlan,
    MxfKlvMetadataTransactionPlan,
    MxfKlvPacketPlan,
    MxfMetadataSetRoutePlan,
    MxfPrimerMappingPlan,
    MxfResponsibilityPlan,
    build_mxf_klv_metadata_transaction_plan,
    classify_klv,
    encode_ber_length,
    encode_local_set_item,
    encode_mxf_klv,
    encode_primer_pack,
    key_from_ul,
    ul_from_key,
)
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "MXF_CLOSED_COMPLETE_HEADER_UL",
    "MXF_CLOSED_HEADER_UL",
    "MXF_ESSENCE_ELEMENT_UL",
    "MXF_INDEX_TABLE_SEGMENT_UL",
    "MXF_OPEN_COMPLETE_HEADER_UL",
    "MXF_OPEN_HEADER_UL",
    "MXF_PREFACE_UL",
    "MXF_PRIMER_UL",
    "MXF_RANDOM_INDEX_METADATA_UL",
    "MxfBerLengthPlan",
    "MxfEmissionGate",
    "MxfHeaderPartitionValidationPlan",
    "MxfKlvMetadataTransactionPlan",
    "MxfKlvPacketPlan",
    "MxfMetadataSetRoutePlan",
    "MxfPrimerMappingPlan",
    "MxfResponsibilityPlan",
    "build_mxf_klv_metadata_transaction_plan",
    "build_mxf_read_graph",
    "encode_ber_length",
    "encode_local_set_item",
    "encode_mxf_klv",
    "encode_primer_pack",
    "invoke_mxf",
    "key_from_ul",
    "ul_from_key",
]

_MXF_MAIN_TABLE = "Image::ExifTool::MXF::Main"
_MXF_HEADER_TABLE = "Image::ExifTool::MXF::Header"
_MXF_HEADER_OUTPUT_SOURCE = "_mxf_header_output"
_MXF_COMPONENT_DATA_DEFINITION_PRINT_CONV: dict[str, str] = {
    "060e2b34.0401.0101.01030201.01000000": "SMPTE 12M Timecode Track",
    "060e2b34.0401.0101.01030201.02000000": ("SMPTE 12M Timecode Track with active user bits"),
    "060e2b34.0401.0101.01030201.03000000": "SMPTE 309M Timecode Track",
    "060e2b34.0401.0101.01030201.10000000": "Descriptive Metadata Track",
    "060e2b34.0401.0101.01030202.01000000": "Picture Essence Track",
    "060e2b34.0401.0101.01030202.02000000": "Sound Essence Track",
    "060e2b34.0401.0101.01030202.03000000": "Data Essence Track",
}
_MXF_DURATION_TAGS = {"Duration", "Origin", "StartTimecode", "EssenceLength"}


@dataclass
class _MxfObject:
    uid: str
    set_name: str
    routes: list[MxfMetadataSetRoutePlan] = field(default_factory=list)
    strong_refs: list[str] = field(default_factory=list)
    track_id: int | None = None
    edit_rate: str | None = None


@dataclass(frozen=True)
class _MxfEmittedRoute:
    route: MxfMetadataSetRoutePlan
    group: str
    uid: str | None
    ordinal: int


def build_mxf_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_mxf_klv_metadata_transaction_plan(data)
    diagnostics: list[str] = [
        f"MXF package-local reader gate: {gate.code}"
        for gate in plan.output_emission_gates
        if gate.code != "planner_is_non_mutating"
    ]
    tags: list[ReadTag] = [
        ReadTag(
            name="FileType",
            value="MXF",
            provenance=_provenance(
                group="File",
                table_name=_MXF_MAIN_TABLE,
                tag_id="FileType",
                evidence_ids=plan.header_partition_validation.evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="FileTypeExtension",
            value="mxf",
            provenance=_provenance(
                group="File",
                table_name=_MXF_MAIN_TABLE,
                tag_id="FileTypeExtension",
                evidence_ids=plan.header_partition_validation.evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="MIMEType",
            value="application/mxf",
            provenance=_provenance(
                group="File",
                table_name=_MXF_MAIN_TABLE,
                tag_id="MIMEType",
                evidence_ids=plan.header_partition_validation.evidence_ids,
            ),
            schema=None,
        ),
    ]
    version = _mxf_header_version(data, plan)
    if version is not None:
        tags.append(
            ReadTag(
                name="MXFVersion",
                value=version,
                provenance=_provenance(
                    group="MXF",
                    table_name=_MXF_HEADER_TABLE,
                    tag_id="0",
                    evidence_ids=(_MXF_HEADER_OUTPUT_SOURCE,),
                ),
                schema=None,
            )
        )
    finalized_routes = _finalize_mxf_object_routes(plan.metadata_routes)
    for finalized in finalized_routes:
        route = finalized.route
        if route.tag_name == "InstanceUID" or route.tag_name.startswith("LocalTag_"):
            continue
        rendered = _render_mxf_route_value(route)
        if route.tag_name in _MXF_DURATION_TAGS and rendered in {0, -1}:
            rendered = "0 s"
        tags.append(
            ReadTag(
                name=route.tag_name,
                value=_read_value(rendered),
                provenance=_provenance(
                    group=finalized.group,
                    table_name=f"Image::ExifTool::MXF::{route.set_name}",
                    tag_id=route.global_ul or f"0x{route.local_tag:04x}",
                    evidence_ids=route.evidence_ids,
                    duplicate_instance_ordinal=finalized.ordinal,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _finalize_mxf_object_routes(
    routes: tuple[MxfMetadataSetRoutePlan, ...],
) -> tuple[_MxfEmittedRoute, ...]:
    objects_by_uid, object_order, route_objects = _collect_mxf_objects(routes)
    group1_by_track_id = _mxf_track_group_lookup(object_order)
    route_groups: dict[tuple[int, int], str] = {}
    edit_rate_by_group: dict[str, str] = {}
    best_duration_uid: str | None = None
    preface_uids = [obj.uid for obj in object_order if obj.set_name == "Preface"]
    for uid in preface_uids:
        best_duration_uid = _assign_mxf_groups(
            uid,
            objects_by_uid,
            group1_by_track_id,
            route_groups,
            edit_rate_by_group,
            None,
            False,
            best_duration_uid,
            set(),
        )

    emitted: list[_MxfEmittedRoute] = []
    best_duration_value: str | int | float | bool | None = None
    for ordinal, route in enumerate(routes):
        obj = route_objects.get((route.packet_offset, route.item_offset))
        route_uid = obj.uid if obj is not None else None
        group = route_groups.get((route.packet_offset, route.item_offset), "MXF")
        emitted.append(_MxfEmittedRoute(route, group, route_uid, ordinal))
        if route_uid == best_duration_uid and route.tag_name == "Duration":
            best_duration_value = _render_mxf_route_value(route)

    deduped = _dedupe_mxf_routes(emitted)
    if best_duration_value is not None:
        duration_route = next(
            (
                item.route
                for item in reversed(emitted)
                if item.uid == best_duration_uid and item.route.tag_name == "Duration"
            ),
            None,
        )
        if duration_route is not None:
            deduped.append(_MxfEmittedRoute(duration_route, "MXF", None, len(routes)))
    return tuple(deduped)


def _collect_mxf_objects(
    routes: tuple[MxfMetadataSetRoutePlan, ...],
) -> tuple[dict[str, _MxfObject], list[_MxfObject], dict[tuple[int, int], _MxfObject]]:
    by_packet: dict[int, list[MxfMetadataSetRoutePlan]] = {}
    for route in routes:
        by_packet.setdefault(route.packet_offset, []).append(route)

    objects_by_uid: dict[str, _MxfObject] = {}
    object_order: list[_MxfObject] = []
    route_objects: dict[tuple[int, int], _MxfObject] = {}
    for packet_routes in by_packet.values():
        uid = _packet_instance_uid(packet_routes)
        if uid is None:
            continue
        obj = objects_by_uid.get(uid)
        if obj is None:
            obj = _MxfObject(uid=uid, set_name=packet_routes[0].set_name)
            objects_by_uid[uid] = obj
            object_order.append(obj)
        else:
            obj.set_name = packet_routes[0].set_name
        obj.routes.extend(packet_routes)
        obj.strong_refs.extend(_packet_strong_refs(packet_routes))
        for route in packet_routes:
            route_objects[(route.packet_offset, route.item_offset)] = obj
            if route.tag_name.endswith("TrackID") and isinstance(route.decoded_value, int):
                obj.track_id = route.decoded_value
            elif route.tag_name == "EditRate" and isinstance(route.decoded_value, str):
                obj.edit_rate = route.decoded_value
    return objects_by_uid, object_order, route_objects


def _packet_instance_uid(routes: list[MxfMetadataSetRoutePlan]) -> str | None:
    for route in routes:
        if route.tag_name == "InstanceUID" and isinstance(route.decoded_value, str):
            return route.decoded_value
    return None


def _packet_strong_refs(routes: list[MxfMetadataSetRoutePlan]) -> list[str]:
    refs: list[str] = []
    for route in routes:
        if route.format_name == "StrongReference" and isinstance(route.decoded_value, str):
            refs.append(route.decoded_value)
        elif route.format_name in {"StrongReferenceArray", "StrongReferenceBatch"} and isinstance(
            route.decoded_value, list
        ):
            refs.extend(item for item in route.decoded_value if isinstance(item, str))
    return refs


def _mxf_track_group_lookup(objects: list[_MxfObject]) -> dict[int, str]:
    group_by_track_id: dict[int, str] = {}
    for obj in objects:
        if obj.track_id is None or obj.track_id in group_by_track_id:
            continue
        group_by_track_id[obj.track_id] = f"Track{len(group_by_track_id) + 1}"
    return group_by_track_id


def _assign_mxf_groups(
    uid: str,
    objects_by_uid: dict[str, _MxfObject],
    group1_by_track_id: dict[int, str],
    route_groups: dict[tuple[int, int], str],
    edit_rate_by_group: dict[str, str],
    inherited_track_id: int | None,
    in_source_package: bool,
    best_duration_uid: str | None,
    active: set[str],
) -> str | None:
    obj = objects_by_uid.get(uid)
    if obj is None or uid in active:
        return best_duration_uid
    active.add(uid)
    track_id = obj.track_id if obj.track_id is not None else inherited_track_id
    group = group1_by_track_id.get(track_id) if track_id is not None else None
    if group is not None:
        if obj.edit_rate is not None:
            edit_rate_by_group[group] = obj.edit_rate
        if obj.set_name == "TimecodeComponent":
            if in_source_package or best_duration_uid is None:
                best_duration_uid = obj.uid
    for route in obj.routes:
        if group is not None:
            route_groups[(route.packet_offset, route.item_offset)] = group
    child_in_source = in_source_package or obj.set_name == "SourcePackage"
    for child_uid in obj.strong_refs:
        best_duration_uid = _assign_mxf_groups(
            child_uid,
            objects_by_uid,
            group1_by_track_id,
            route_groups,
            edit_rate_by_group,
            track_id,
            child_in_source,
            best_duration_uid,
            active,
        )
    active.remove(uid)
    return best_duration_uid


def _dedupe_mxf_routes(routes: list[_MxfEmittedRoute]) -> list[_MxfEmittedRoute]:
    keep_indexes: set[int] = set()
    seen: set[tuple[str, str]] = set()
    for index in range(len(routes) - 1, -1, -1):
        item = routes[index]
        if item.uid is None or item.route.tag_name.startswith("LocalTag_"):
            keep_indexes.add(index)
            continue
        key = (item.route.tag_name, item.uid)
        if key in seen:
            continue
        seen.add(key)
        keep_indexes.add(index)
    return [item for index, item in enumerate(routes) if index in keep_indexes]


def _render_mxf_route_value(route: MxfMetadataSetRoutePlan) -> str | int | float | bool | None:
    value = route.decoded_value
    if route.tag_name == "ComponentDataDefinition" and isinstance(value, str):
        return _MXF_COMPONENT_DATA_DEFINITION_PRINT_CONV.get(value, value)
    if route.format_name == "Boolean" and isinstance(value, str):
        return value != "False"
    if route.format_name == "rational64s" and isinstance(value, str):
        return _render_rational64s(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _render_rational64s(value: str) -> str | int | float:
    numerator_text, separator, denominator_text = value.partition("/")
    if not separator:
        return value
    try:
        numerator = int(numerator_text)
        denominator = int(denominator_text)
    except ValueError:
        return value
    if denominator == 0:
        return value
    if numerator % denominator == 0:
        return numerator // denominator
    return numerator / denominator


def _mxf_header_version(data: bytes, plan: MxfKlvMetadataTransactionPlan) -> str | None:
    if not plan.header_partition_validation.is_valid:
        return None
    for packet in plan.klv_packets:
        if packet.action == "process_header_partition" and packet.value_length >= 4:
            value_offset = packet.value_offset
            if value_offset + 4 <= len(data):
                major = int.from_bytes(data[value_offset : value_offset + 2], "big")
                minor = int.from_bytes(data[value_offset + 2 : value_offset + 4], "big")
                return f"{major}.{minor}"
    return None


def invoke_mxf(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_mxf_read_graph(_read_mxf_exiftool_klv_metadata(path, prefix), source_file)


def _read_mxf_exiftool_klv_metadata(path: Path, prefix: bytes) -> bytes:
    # MXF.pm probes up to 65547 bytes for run-in, then reads full known KLV
    # values below 10 MB and seeks over large/opaque essence or partition data.
    probe = bytearray(prefix)
    with path.open("rb") as file:
        if len(probe) < 65_547:
            file.seek(len(probe))
            probe.extend(file.read(65_547 - len(probe)))
        marker = b"\x06\x0e\x2b\x34\x02\x05\x01\x01\x0d\x01\x02"
        start = bytes(probe).find(marker)
        if start < 0:
            return bytes(probe)
        file.seek(start)
        data = bytearray()
        while True:
            key = file.read(MXF_KEY_SIZE)
            if not key:
                break
            if len(key) != MXF_KEY_SIZE:
                data.extend(key)
                break
            first = file.read(1)
            if len(first) != 1:
                data.extend(key)
                break
            length_bytes = bytearray(first)
            if first[0] >= 0x80:
                length_count = first[0] & 0x7F
                more = file.read(length_count)
                length_bytes.extend(more)
                if len(more) != length_count:
                    data.extend(key + bytes(length_bytes))
                    break
                value_length = int.from_bytes(more, "big")
            else:
                value_length = first[0]
            ul = ul_from_key(key)
            _, action, _ = classify_klv(ul, value_length)
            should_read = (
                action
                in {
                    "process_header_partition",
                    "process_primer_pack",
                    "process_local_set",
                    "preserve_random_index_pack",
                    "preserve_index_table_segment",
                }
                and value_length < MXF_MAX_EXIFTOOL_IN_MEMORY_VALUE_SIZE
            )
            if not should_read:
                file.seek(value_length, 1)
                continue
            value = file.read(value_length)
            data.extend(key + bytes(length_bytes) + value)
            if len(value) != value_length:
                break
    return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="mxf",
        builder_ref="exifmodern.formats.mxf:invoke_mxf",
        patterns=(Pattern(0, b"\x06\x0e\x2b\x34\x02\x05\x01\x01\x0d\x01\x02"),),
        weak=True,
    ),
)
