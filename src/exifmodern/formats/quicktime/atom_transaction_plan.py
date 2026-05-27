"""Shared non-mutating QuickTime atom transaction planning.

ExifTool's QuickTime writer is a single atom-transaction engine used by MOV/MP4
metadata, track rotation, HEIC ItemInfo edits, and Canon CR3 UUID/CTBO repairs.
This module factors those shared responsibilities into typed, source-backed
planning records.  It deliberately does not mutate bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.quicktime.atoms import (
    QT_ATOM_HEADER_SIZE,
    QT_EXTENDED_ATOM_HEADER_SIZE,
)
from exifmodern.formats.quicktime.fanout_write_plan import QuickTimeFanoutWritePlan
from exifmodern.formats.quicktime.metadata_atoms import (
    QuickTimeMetadataDeleteGroup,
    QuickTimeMetadataGroup,
    QuickTimeMetadataValue,
    QuickTimeMetadataWritePlan,
)
from exifmodern.formats.quicktime.rotation_writer import QuickTimeRotationWritePlan
from exifmodern.json_types import JsonObject

type QuickTimeAtomTransactionStatus = Literal["plan_only_deferred"]
type QuickTimeAtomTransactionConcern = Literal[
    "atom_traversal",
    "full_atom_path_routing",
    "metadata_atom_replacement",
    "matrix_tkhd_mutation",
    "atom_size_recalculation",
    "mdat_preservation",
    "offset_sensitive_blocker",
    "write_last_ordering",
    "output_emission_gate",
]
type QuickTimeAtomTransactionPhase = Literal[
    "input_scan",
    "route",
    "payload_plan",
    "size_plan",
    "media_plan",
    "offset_plan",
    "emit_gate",
]
type QuickTimeAtomTransactionEntryCode = Literal[
    "walk_atom_tree_and_record_full_paths",
    "route_writes_to_full_atom_paths",
    "plan_metadata_atom_replacements",
    "plan_tkhd_matrix_mutations",
    "recalculate_modified_atom_sizes",
    "preserve_or_schedule_mdat_chunks",
    "collect_offset_sensitive_atoms",
    "stage_write_last_atoms",
    "gate_output_emission",
]
type QuickTimeMutationAction = Literal[
    "upsert_metadata_atom",
    "delete_metadata_atom",
    "delete_metadata_group",
    "replace_microsoft_xtra_atom",
    "replace_three_gp_userdata_atom",
    "rewrite_tkhd_matrix",
]
type QuickTimeRouteSurface = (
    QuickTimeMetadataGroup
    | Literal[
        "Microsoft",
        "UserData-3GP",
        "Rotation",
        "HEIC-ItemInfo",
        "CR3-UUID-CTBO",
        "XMP-UUID",
    ]
)
type QuickTimeRouteRole = Literal[
    "metadata_atom_replacement",
    "matrix_tkhd_mutation",
    "heic_item_info_mdat_repair",
    "cr3_uuid_ctbo_repair",
    "xmp_uuid_replacement",
]
type QuickTimeOffsetBlockerCode = Literal[
    "requires_sample_chunk_offset_repair",
    "requires_item_location_offset_repair",
    "unsupported_movie_fragment_offset_model",
    "unsupported_segment_index_offset_model",
    "unsupported_sample_aux_offset_model",
    "requires_gps_offset_repair",
    "requires_cr3_ctbo_offset_repair",
    "requires_uuid_offset_registration",
]
type QuickTimeOutputEmissionGateCode = Literal[
    "planner_is_non_mutating",
    "full_atom_paths_must_be_resolved",
    "offset_sensitive_atoms_must_be_absent_or_repaired",
    "modified_atom_sizes_must_be_recalculated",
    "mdat_must_be_preserved_before_write_last",
    "metadata_replacements_must_delegate_to_atom_writer",
    "tkhd_matrix_must_delegate_to_rotation_writer",
    "write_last_atoms_must_follow_mdat",
    "heic_item_info_offsets_must_be_repaired",
    "cr3_ctbo_offsets_must_be_repaired",
]

CONTAINER_ATOMS = frozenset(
    {
        "moov",
        "trak",
        "mdia",
        "minf",
        "stbl",
        "edts",
        "dinf",
        "udta",
        "meta",
        "ilst",
        "moof",
        "traf",
        "mfra",
        "iprp",
        "ipco",
    }
)
FULL_ATOM_CONTAINERS = frozenset({"meta"})
OFFSET_BLOCKER_BY_ATOM: dict[str, QuickTimeOffsetBlockerCode] = {
    "stco": "requires_sample_chunk_offset_repair",
    "co64": "requires_sample_chunk_offset_repair",
    "iloc": "requires_item_location_offset_repair",
    "mfra": "unsupported_movie_fragment_offset_model",
    "moof": "unsupported_movie_fragment_offset_model",
    "sidx": "unsupported_segment_index_offset_model",
    "saio": "unsupported_sample_aux_offset_model",
    "gps ": "requires_gps_offset_repair",
    "CTBO": "requires_cr3_ctbo_offset_repair",
    "uuid": "requires_uuid_offset_registration",
}
CANON2_WRITE_LAST_UUID = bytes.fromhex("210f1687914911e4811100242131fce4")

WRITE_QUICKTIME_MAIN_SOURCE = "quicktime.write_transaction_setup"
WRITE_QUICKTIME_ROUTING_SOURCE = "quicktime.atom_routing"
WRITE_QUICKTIME_FULL_PATH_SOURCE = "quicktime.full_atom_path_routing"
WRITE_QUICKTIME_DELETE_SOURCE = "quicktime.delete_group_selection"
WRITE_QUICKTIME_OFFSET_SOURCE = "quicktime.offset_sensitive_atoms"
WRITE_QUICKTIME_SIZE_SOURCE = "quicktime.modified_atom_size_staging"
WRITE_QUICKTIME_CREATE_SOURCE = "quicktime.metadata_atom_creation"
WRITE_QUICKTIME_HEIC_SOURCE = "quicktime.heic_item_info_dispatch"
WRITE_QUICKTIME_MDAT_SOURCE = "quicktime.mdat_position_planning"
WRITE_QUICKTIME_OFFSET_FIXUP_SOURCE = "quicktime.recorded_offset_fixups"
WRITE_QUICKTIME_FINAL_EMIT_SOURCE = "quicktime.final_mdat_write_last_emission"
QUICKTIME_METADATA_TABLE_SOURCE = "quicktime.metadata_tables"
QUICKTIME_ROTATION_SOURCE = "quicktime.rotation_write_also"
QUICKTIME_TKHD_SOURCE = "quicktime.track_header_matrix"
QUICKTIME_WRITE_LAST_SOURCE = "quicktime.uuid_canon2_write_last"


@dataclass(frozen=True)
class QuickTimeAtomNode:
    atom_type: str
    path: tuple[str, ...]
    offset: int
    header_size: int
    size: int
    payload_offset: int
    payload_size: int
    is_container: bool
    is_top_level: bool
    write_last_semantics: str | None = None

    @property
    def full_path(self) -> str:
        return "/".join(self.path)


@dataclass(frozen=True)
class QuickTimeMdatChunk:
    path: str
    offset: int
    header_size: int
    data_offset: int
    data_size: int | None
    extends_to_eof: bool


@dataclass(frozen=True)
class QuickTimeOffsetSensitiveAtom:
    atom_type: str
    full_path: str
    offset: int
    payload_size: int
    blocker_code: QuickTimeOffsetBlockerCode
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class QuickTimeAtomTraversal:
    atom_nodes: tuple[QuickTimeAtomNode, ...]
    mdat_chunks: tuple[QuickTimeMdatChunk, ...]
    offset_sensitive_atoms: tuple[QuickTimeOffsetSensitiveAtom, ...]

    @property
    def full_paths(self) -> tuple[str, ...]:
        return tuple(node.full_path for node in self.atom_nodes)

    @property
    def has_mdat(self) -> bool:
        return bool(self.mdat_chunks)

    @property
    def write_last_paths(self) -> tuple[str, ...]:
        return tuple(
            node.full_path for node in self.atom_nodes if node.write_last_semantics is not None
        )


@dataclass(frozen=True)
class QuickTimeAtomRoute:
    surface: QuickTimeRouteSurface
    full_atom_path: str
    role: QuickTimeRouteRole
    handler_type: str | None
    delegate: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "delegate": self.delegate,
            "full_atom_path": self.full_atom_path,
            "handler_type": self.handler_type,
            "role": self.role,
            "surface": self.surface,
        }


@dataclass(frozen=True)
class QuickTimeMutationResponsibility:
    action: QuickTimeMutationAction
    surface: QuickTimeRouteSurface
    full_atom_path: str
    tag_name: str | None
    value: str | None
    delegate: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "delegate": self.delegate,
            "full_atom_path": self.full_atom_path,
            "surface": self.surface,
            "tag_name": self.tag_name,
            "value": self.value,
        }


@dataclass(frozen=True)
class QuickTimeAtomTransactionEntry:
    order: int
    code: QuickTimeAtomTransactionEntryCode
    concern: QuickTimeAtomTransactionConcern
    phase: QuickTimeAtomTransactionPhase
    description: str
    depends_on: tuple[QuickTimeAtomTransactionEntryCode, ...]
    records: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "concern": self.concern,
            "depends_on": list(self.depends_on),
            "description": self.description,
            "order": self.order,
            "phase": self.phase,
            "records": list(self.records),
        }


@dataclass(frozen=True)
class QuickTimeOutputEmissionGate:
    code: QuickTimeOutputEmissionGateCode
    required_entries: tuple[QuickTimeAtomTransactionEntryCode, ...]
    invariant: str
    failure_response: str
    satisfied: bool
    evidence_ids: tuple[str, ...]

    @property
    def blocks_mutation(self) -> bool:
        return not self.satisfied

    def to_json(self) -> JsonObject:
        return {
            "blocks_mutation": self.blocks_mutation,
            "code": self.code,
            "failure_response": self.failure_response,
            "invariant": self.invariant,
            "required_entries": list(self.required_entries),
            "satisfied": self.satisfied,
        }


@dataclass(frozen=True)
class QuickTimeAtomTransactionPlan:
    status: QuickTimeAtomTransactionStatus
    routes: tuple[QuickTimeAtomRoute, ...]
    mutation_responsibilities: tuple[QuickTimeMutationResponsibility, ...]
    entries: tuple[QuickTimeAtomTransactionEntry, ...]
    output_emission_gates: tuple[QuickTimeOutputEmissionGate, ...]
    traversal: QuickTimeAtomTraversal | None
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def blocked_gate_count(self) -> int:
        return sum(gate.blocks_mutation for gate in self.output_emission_gates)

    @property
    def offset_blocker_codes(self) -> tuple[QuickTimeOffsetBlockerCode, ...]:
        if self.traversal is None:
            return ()
        return tuple(atom.blocker_code for atom in self.traversal.offset_sensitive_atoms)

    def entries_for_concern(
        self, concern: QuickTimeAtomTransactionConcern
    ) -> tuple[QuickTimeAtomTransactionEntry, ...]:
        return tuple(entry for entry in self.entries if entry.concern == concern)

    def to_json(self) -> JsonObject:
        return {
            "blocked_gate_count": self.blocked_gate_count,
            "can_mutate_bytes": self.can_mutate_bytes,
            "entries": [entry.to_json() for entry in self.entries],
            "offset_blocker_codes": list(self.offset_blocker_codes),
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "routes": [route.to_json() for route in self.routes],
            "mutation_responsibilities": [
                responsibility.to_json() for responsibility in self.mutation_responsibilities
            ],
            "status": self.status,
            "traversal": traversal_to_json(self.traversal),
        }


def inspect_quicktime_atom_transaction(data: bytes) -> QuickTimeAtomTraversal:
    """Walk a QuickTime/ISO BMFF atom tree without rewriting bytes."""

    nodes, mdats, offset_atoms = read_atom_nodes(data, 0, len(data), ())
    return QuickTimeAtomTraversal(
        atom_nodes=tuple(nodes),
        mdat_chunks=tuple(mdats),
        offset_sensitive_atoms=tuple(offset_atoms),
    )


def build_quicktime_atom_transaction_plan(
    *,
    data: bytes | None = None,
    metadata_plan: QuickTimeMetadataWritePlan | None = None,
    fanout_plan: QuickTimeFanoutWritePlan | None = None,
    rotation_plan: QuickTimeRotationWritePlan | None = None,
    include_heic_item_info: bool = False,
    include_cr3_uuid_ctbo: bool = False,
) -> QuickTimeAtomTransactionPlan:
    traversal = inspect_quicktime_atom_transaction(data) if data is not None else None
    routes = requested_routes(
        metadata_plan=metadata_plan,
        fanout_plan=fanout_plan,
        rotation_plan=rotation_plan,
        include_heic_item_info=include_heic_item_info,
        include_cr3_uuid_ctbo=include_cr3_uuid_ctbo,
    )
    mutation_responsibilities = requested_mutation_responsibilities(
        metadata_plan=metadata_plan,
        fanout_plan=fanout_plan,
        rotation_plan=rotation_plan,
    )
    evidence_ids = unique_evidence_ids(
        (
            WRITE_QUICKTIME_MAIN_SOURCE,
            WRITE_QUICKTIME_ROUTING_SOURCE,
            WRITE_QUICKTIME_FULL_PATH_SOURCE,
            WRITE_QUICKTIME_OFFSET_SOURCE,
            WRITE_QUICKTIME_SIZE_SOURCE,
            WRITE_QUICKTIME_MDAT_SOURCE,
            WRITE_QUICKTIME_OFFSET_FIXUP_SOURCE,
            WRITE_QUICKTIME_FINAL_EMIT_SOURCE,
            *tuple(source for route in routes for source in route.evidence_ids),
            *tuple(
                source
                for responsibility in mutation_responsibilities
                for source in responsibility.evidence_ids
            ),
        )
    )
    return QuickTimeAtomTransactionPlan(
        status="plan_only_deferred",
        routes=routes,
        mutation_responsibilities=mutation_responsibilities,
        entries=QUICKTIME_TRANSACTION_ENTRIES,
        output_emission_gates=output_emission_gates(
            traversal=traversal,
            routes=routes,
            mutation_responsibilities=mutation_responsibilities,
            include_heic_item_info=include_heic_item_info,
            include_cr3_uuid_ctbo=include_cr3_uuid_ctbo,
        ),
        traversal=traversal,
        evidence_ids=evidence_ids,
    )


def read_atom_nodes(
    data: bytes,
    start: int,
    end: int,
    parent_path: tuple[str, ...],
) -> tuple[
    list[QuickTimeAtomNode],
    list[QuickTimeMdatChunk],
    list[QuickTimeOffsetSensitiveAtom],
]:
    nodes: list[QuickTimeAtomNode] = []
    mdats: list[QuickTimeMdatChunk] = []
    offset_atoms: list[QuickTimeOffsetSensitiveAtom] = []
    cursor = start
    while cursor < end:
        parsed = parse_atom_header(data, cursor, end)
        atom_type, size, header_size, payload_offset, payload_size, extends_to_eof = parsed
        path = (*parent_path, atom_type)
        is_container = atom_is_container(atom_type, parent_path)
        node = QuickTimeAtomNode(
            atom_type=atom_type,
            path=path,
            offset=cursor,
            header_size=header_size,
            size=size,
            payload_offset=payload_offset,
            payload_size=payload_size,
            is_container=is_container,
            is_top_level=not parent_path,
            write_last_semantics=write_last_semantics(
                data[payload_offset : payload_offset + payload_size]
            ),
        )
        nodes.append(node)
        blocker_code = OFFSET_BLOCKER_BY_ATOM.get(atom_type)
        if blocker_code is not None:
            offset_atoms.append(
                QuickTimeOffsetSensitiveAtom(
                    atom_type=atom_type,
                    full_path=node.full_path,
                    offset=cursor,
                    payload_size=payload_size,
                    blocker_code=blocker_code,
                    evidence_ids=(WRITE_QUICKTIME_OFFSET_SOURCE,),
                )
            )
        if atom_type == "mdat" and not parent_path:
            mdats.append(
                QuickTimeMdatChunk(
                    path=node.full_path,
                    offset=cursor,
                    header_size=header_size,
                    data_offset=payload_offset,
                    data_size=None if extends_to_eof else payload_size,
                    extends_to_eof=extends_to_eof,
                )
            )
        if is_container and atom_type != "mdat":
            child_start = child_payload_start(atom_type, payload_offset, payload_size)
            if child_start < payload_offset + payload_size:
                child_nodes, child_mdats, child_offsets = read_atom_nodes(
                    data,
                    child_start,
                    payload_offset + payload_size,
                    path,
                )
                nodes.extend(child_nodes)
                mdats.extend(child_mdats)
                offset_atoms.extend(child_offsets)
        cursor += size
    return nodes, mdats, offset_atoms


def parse_atom_header(
    data: bytes,
    offset: int,
    end: int,
) -> tuple[str, int, int, int, int, bool]:
    if offset + QT_ATOM_HEADER_SIZE > end:
        raise ValueError("Truncated QuickTime atom header.")
    atom_size = int.from_bytes(data[offset : offset + 4], "big")
    atom_type = data[offset + 4 : offset + 8].decode("latin-1")
    extends_to_eof = False
    if atom_size == 0:
        atom_end = len(data)
        atom_size = atom_end - offset
        header_size = QT_ATOM_HEADER_SIZE
        extends_to_eof = True
    elif atom_size == 1:
        if offset + QT_EXTENDED_ATOM_HEADER_SIZE > end:
            raise ValueError("Truncated QuickTime extended atom header.")
        atom_size = int.from_bytes(data[offset + 8 : offset + 16], "big")
        atom_end = offset + atom_size
        header_size = QT_EXTENDED_ATOM_HEADER_SIZE
    else:
        atom_end = offset + atom_size
        header_size = QT_ATOM_HEADER_SIZE
    payload_offset = offset + header_size
    if atom_end < payload_offset or atom_end > end:
        raise ValueError(f"Invalid QuickTime atom length for {atom_type!r}.")
    return (
        atom_type,
        atom_size,
        header_size,
        payload_offset,
        atom_end - payload_offset,
        extends_to_eof,
    )


def atom_is_container(atom_type: str, parent_path: tuple[str, ...]) -> bool:
    if parent_path and parent_path[-1] == "ilst":
        return True
    return atom_type in CONTAINER_ATOMS


def child_payload_start(atom_type: str, payload_offset: int, payload_size: int) -> int:
    if atom_type in FULL_ATOM_CONTAINERS and payload_size >= 4:
        return payload_offset + 4
    return payload_offset


def write_last_semantics(payload: bytes) -> str | None:
    if payload.startswith(CANON2_WRITE_LAST_UUID):
        return "UUID-Canon2 WriteLast"
    return None


def requested_routes(
    *,
    metadata_plan: QuickTimeMetadataWritePlan | None,
    fanout_plan: QuickTimeFanoutWritePlan | None,
    rotation_plan: QuickTimeRotationWritePlan | None,
    include_heic_item_info: bool,
    include_cr3_uuid_ctbo: bool,
) -> tuple[QuickTimeAtomRoute, ...]:
    surfaces: list[QuickTimeRouteSurface] = []
    if metadata_plan is not None:
        for value in metadata_plan.values:
            surfaces.append(value.group)
        for delete_group in metadata_plan.delete_groups:
            surfaces.append(delete_group.group)
    if fanout_plan is not None:
        for value in fanout_plan.metadata_plan.values:
            surfaces.append(value.group)
        for delete_group in fanout_plan.metadata_plan.delete_groups:
            surfaces.append(delete_group.group)
        if fanout_plan.microsoft_assignments:
            surfaces.append("Microsoft")
        if fanout_plan.three_gp_assignments:
            surfaces.append("UserData-3GP")
    if rotation_plan is not None:
        surfaces.append("Rotation")
    if include_heic_item_info:
        surfaces.append("HEIC-ItemInfo")
    if include_cr3_uuid_ctbo:
        surfaces.append("CR3-UUID-CTBO")
        surfaces.append("XMP-UUID")
    return tuple(route_for_surface(surface) for surface in dedupe(surfaces))


def route_for_surface(surface: QuickTimeRouteSurface) -> QuickTimeAtomRoute:
    routes: dict[QuickTimeRouteSurface, QuickTimeAtomRoute] = {
        "ItemList": QuickTimeAtomRoute(
            "ItemList",
            "moov/udta/meta/ilst",
            "metadata_atom_replacement",
            None,
            "exifmodern.formats.quicktime.metadata_writer",
            (WRITE_QUICKTIME_FULL_PATH_SOURCE, QUICKTIME_METADATA_TABLE_SOURCE),
        ),
        "UserData": QuickTimeAtomRoute(
            "UserData",
            "moov/udta",
            "metadata_atom_replacement",
            None,
            "exifmodern.formats.quicktime.metadata_writer",
            (WRITE_QUICKTIME_ROUTING_SOURCE, QUICKTIME_METADATA_TABLE_SOURCE),
        ),
        "Keys": QuickTimeAtomRoute(
            "Keys",
            "moov/meta/keys + moov/meta/ilst",
            "metadata_atom_replacement",
            "mdta",
            "exifmodern.formats.quicktime.metadata_writer",
            (WRITE_QUICKTIME_FULL_PATH_SOURCE, QUICKTIME_METADATA_TABLE_SOURCE),
        ),
        "AudioKeys": QuickTimeAtomRoute(
            "AudioKeys",
            "moov/trak[handler=soun]/meta/keys + moov/trak[handler=soun]/meta/ilst",
            "metadata_atom_replacement",
            "soun",
            "exifmodern.formats.quicktime.metadata_writer",
            (WRITE_QUICKTIME_FULL_PATH_SOURCE, QUICKTIME_METADATA_TABLE_SOURCE),
        ),
        "VideoKeys": QuickTimeAtomRoute(
            "VideoKeys",
            "moov/trak[handler=vide]/meta/keys + moov/trak[handler=vide]/meta/ilst",
            "metadata_atom_replacement",
            "vide",
            "exifmodern.formats.quicktime.metadata_writer",
            (WRITE_QUICKTIME_FULL_PATH_SOURCE, QUICKTIME_METADATA_TABLE_SOURCE),
        ),
        "Microsoft": QuickTimeAtomRoute(
            "Microsoft",
            "moov/udta/Xtra",
            "metadata_atom_replacement",
            None,
            "pending Microsoft Xtra atom writer",
            (WRITE_QUICKTIME_ROUTING_SOURCE,),
        ),
        "UserData-3GP": QuickTimeAtomRoute(
            "UserData-3GP",
            "moov/udta/loci|rtng",
            "metadata_atom_replacement",
            None,
            "pending 3GP UserData atom writer",
            (WRITE_QUICKTIME_ROUTING_SOURCE,),
        ),
        "Rotation": QuickTimeAtomRoute(
            "Rotation",
            "moov/trak[handler=vide]/tkhd",
            "matrix_tkhd_mutation",
            "vide",
            "exifmodern.formats.quicktime.rotation_writer",
            (QUICKTIME_ROTATION_SOURCE, QUICKTIME_TKHD_SOURCE),
        ),
        "HEIC-ItemInfo": QuickTimeAtomRoute(
            "HEIC-ItemInfo",
            "meta/iinf + meta/iref + meta/iloc + mdat",
            "heic_item_info_mdat_repair",
            None,
            "exifmodern.formats.heic.item_info_write_plan + offset_repair_plan",
            (WRITE_QUICKTIME_HEIC_SOURCE, WRITE_QUICKTIME_MDAT_SOURCE),
        ),
        "CR3-UUID-CTBO": QuickTimeAtomRoute(
            "CR3-UUID-CTBO",
            "uuid + CTBO + mdat",
            "cr3_uuid_ctbo_repair",
            None,
            "exifmodern.formats.canon_raw.cr3_transaction_ledger",
            (WRITE_QUICKTIME_OFFSET_FIXUP_SOURCE, WRITE_QUICKTIME_FINAL_EMIT_SOURCE),
        ),
        "XMP-UUID": QuickTimeAtomRoute(
            "XMP-UUID",
            "uuid[prefix=be7acfcb97a942e89c71999491e3afac]",
            "xmp_uuid_replacement",
            None,
            "XMP uuid atom writer",
            (WRITE_QUICKTIME_CREATE_SOURCE,),
        ),
    }
    return routes[surface]


def requested_mutation_responsibilities(
    *,
    metadata_plan: QuickTimeMetadataWritePlan | None,
    fanout_plan: QuickTimeFanoutWritePlan | None,
    rotation_plan: QuickTimeRotationWritePlan | None,
) -> tuple[QuickTimeMutationResponsibility, ...]:
    responsibilities: list[QuickTimeMutationResponsibility] = []
    if metadata_plan is not None:
        responsibilities.extend(metadata_responsibilities(metadata_plan))
    if fanout_plan is not None:
        responsibilities.extend(metadata_responsibilities(fanout_plan.metadata_plan))
        responsibilities.extend(
            QuickTimeMutationResponsibility(
                "replace_microsoft_xtra_atom",
                "Microsoft",
                "moov/udta/Xtra",
                assignment.name,
                ",".join(assignment.values),
                "pending Microsoft Xtra atom writer",
                (WRITE_QUICKTIME_ROUTING_SOURCE,),
            )
            for assignment in fanout_plan.microsoft_assignments
        )
        responsibilities.extend(
            QuickTimeMutationResponsibility(
                "replace_three_gp_userdata_atom",
                "UserData-3GP",
                f"moov/udta/{assignment.atom_id}",
                assignment.name,
                assignment.value,
                "pending 3GP UserData atom writer",
                (WRITE_QUICKTIME_ROUTING_SOURCE,),
            )
            for assignment in fanout_plan.three_gp_assignments
        )
    if rotation_plan is not None:
        responsibilities.append(
            QuickTimeMutationResponsibility(
                "rewrite_tkhd_matrix",
                "Rotation",
                "moov/trak[handler=vide]/tkhd",
                "Rotation",
                str(rotation_plan.rotation_degrees),
                "exifmodern.formats.quicktime.rotation_writer",
                (QUICKTIME_ROTATION_SOURCE, QUICKTIME_TKHD_SOURCE),
            )
        )
    return tuple(responsibilities)


def metadata_responsibilities(
    plan: QuickTimeMetadataWritePlan,
) -> tuple[QuickTimeMutationResponsibility, ...]:
    responsibilities: list[QuickTimeMutationResponsibility] = []
    for delete_group in plan.delete_groups:
        responsibilities.append(metadata_delete_group_responsibility(delete_group))
    for value in plan.values:
        responsibilities.append(metadata_value_responsibility(value))
    return tuple(responsibilities)


def metadata_delete_group_responsibility(
    delete_group: QuickTimeMetadataDeleteGroup,
) -> QuickTimeMutationResponsibility:
    return QuickTimeMutationResponsibility(
        "delete_metadata_group",
        delete_group.group,
        route_for_surface(delete_group.group).full_atom_path,
        "all",
        None,
        "exifmodern.formats.quicktime.metadata_writer",
        (WRITE_QUICKTIME_DELETE_SOURCE, QUICKTIME_METADATA_TABLE_SOURCE),
    )


def metadata_value_responsibility(
    value: QuickTimeMetadataValue,
) -> QuickTimeMutationResponsibility:
    return QuickTimeMutationResponsibility(
        "delete_metadata_atom" if value.value is None else "upsert_metadata_atom",
        value.group,
        route_for_surface(value.group).full_atom_path,
        value.name,
        value.value,
        "exifmodern.formats.quicktime.metadata_writer",
        (WRITE_QUICKTIME_CREATE_SOURCE, QUICKTIME_METADATA_TABLE_SOURCE),
    )


def output_emission_gates(
    *,
    traversal: QuickTimeAtomTraversal | None,
    routes: tuple[QuickTimeAtomRoute, ...],
    mutation_responsibilities: tuple[QuickTimeMutationResponsibility, ...],
    include_heic_item_info: bool,
    include_cr3_uuid_ctbo: bool,
) -> tuple[QuickTimeOutputEmissionGate, ...]:
    has_metadata = any(route.role == "metadata_atom_replacement" for route in routes)
    has_rotation = any(route.surface == "Rotation" for route in routes)
    has_mdat = traversal is not None and traversal.has_mdat
    has_offset_blockers = traversal is None or bool(traversal.offset_sensitive_atoms)
    has_write_last = traversal is not None and bool(traversal.write_last_paths)
    return (
        QuickTimeOutputEmissionGate(
            "planner_is_non_mutating",
            ("gate_output_emission",),
            "This shared transaction plan may describe output but must not write bytes.",
            "Delegate to an implemented writer or keep the request in plan-only state.",
            False,
            (WRITE_QUICKTIME_FINAL_EMIT_SOURCE,),
        ),
        QuickTimeOutputEmissionGate(
            "full_atom_paths_must_be_resolved",
            ("walk_atom_tree_and_record_full_paths", "route_writes_to_full_atom_paths"),
            "Every requested mutation must route to a full atom path before output.",
            "Abort instead of creating or editing an ambiguous QuickTime directory.",
            traversal is not None or not routes,
            (WRITE_QUICKTIME_FULL_PATH_SOURCE,),
        ),
        QuickTimeOutputEmissionGate(
            "offset_sensitive_atoms_must_be_absent_or_repaired",
            ("collect_offset_sensitive_atoms",),
            "Offset-bearing atoms must be repaired or proven absent before emitting bytes.",
            "Abort before output so media and uuid offsets do not become stale.",
            not has_offset_blockers,
            (WRITE_QUICKTIME_OFFSET_SOURCE, WRITE_QUICKTIME_OFFSET_FIXUP_SOURCE),
        ),
        QuickTimeOutputEmissionGate(
            "modified_atom_sizes_must_be_recalculated",
            ("recalculate_modified_atom_sizes",),
            "All modified atom headers must reflect rewritten payload lengths.",
            "Abort before output if size growth and uuid size registration are not modeled.",
            not mutation_responsibilities,
            (WRITE_QUICKTIME_SIZE_SOURCE,),
        ),
        QuickTimeOutputEmissionGate(
            "mdat_must_be_preserved_before_write_last",
            ("preserve_or_schedule_mdat_chunks", "stage_write_last_atoms"),
            "Top-level mdat chunks are copied or edited after metadata and before WriteLast atoms.",
            "Abort if media data ordering cannot be preserved.",
            has_mdat and not has_write_last,
            (WRITE_QUICKTIME_MDAT_SOURCE, WRITE_QUICKTIME_FINAL_EMIT_SOURCE),
        ),
        QuickTimeOutputEmissionGate(
            "metadata_replacements_must_delegate_to_atom_writer",
            ("plan_metadata_atom_replacements",),
            "Metadata value/delete operations must be delegated to a byte writer.",
            "Keep metadata mutations descriptive in this shared plan.",
            not has_metadata,
            (QUICKTIME_METADATA_TABLE_SOURCE, WRITE_QUICKTIME_CREATE_SOURCE),
        ),
        QuickTimeOutputEmissionGate(
            "tkhd_matrix_must_delegate_to_rotation_writer",
            ("plan_tkhd_matrix_mutations",),
            "Rotation requires video-track tkhd matrix mutation.",
            "Delegate tkhd mutation to the rotation writer before output.",
            not has_rotation,
            (QUICKTIME_ROTATION_SOURCE, QUICKTIME_TKHD_SOURCE),
        ),
        QuickTimeOutputEmissionGate(
            "write_last_atoms_must_follow_mdat",
            ("stage_write_last_atoms", "preserve_or_schedule_mdat_chunks"),
            "Atoms marked WriteLast must be staged and emitted after media data.",
            "Abort rather than inline a WriteLast atom ahead of mdat.",
            not has_write_last,
            (QUICKTIME_WRITE_LAST_SOURCE, WRITE_QUICKTIME_FINAL_EMIT_SOURCE),
        ),
        QuickTimeOutputEmissionGate(
            "heic_item_info_offsets_must_be_repaired",
            ("preserve_or_schedule_mdat_chunks", "collect_offset_sensitive_atoms"),
            "HEIC ItemInfo edits require iinf/iref/iloc rebuild and global offset repair.",
            "Use the HEIC ItemInfo offset repair plan before emitting bytes.",
            not include_heic_item_info,
            (WRITE_QUICKTIME_HEIC_SOURCE, WRITE_QUICKTIME_MDAT_SOURCE),
        ),
        QuickTimeOutputEmissionGate(
            "cr3_ctbo_offsets_must_be_repaired",
            ("collect_offset_sensitive_atoms", "stage_write_last_atoms"),
            "CR3 UUID and CTBO entries must be repaired from final uuid and mdat positions.",
            "Use the CR3 transaction ledger before emitting bytes.",
            not include_cr3_uuid_ctbo,
            (WRITE_QUICKTIME_OFFSET_FIXUP_SOURCE, QUICKTIME_WRITE_LAST_SOURCE),
        ),
    )


QUICKTIME_TRANSACTION_ENTRIES: tuple[QuickTimeAtomTransactionEntry, ...] = (
    QuickTimeAtomTransactionEntry(
        1,
        "walk_atom_tree_and_record_full_paths",
        "atom_traversal",
        "input_scan",
        "Walk QuickTime atoms recursively and record stable full atom paths with offsets.",
        (),
        ("atom_nodes", "full_atom_paths", "write_last_candidates"),
        (WRITE_QUICKTIME_MAIN_SOURCE, WRITE_QUICKTIME_FULL_PATH_SOURCE),
    ),
    QuickTimeAtomTransactionEntry(
        2,
        "route_writes_to_full_atom_paths",
        "full_atom_path_routing",
        "route",
        "Route metadata, rotation, HEIC, and CR3 requests to their complete atom paths.",
        ("walk_atom_tree_and_record_full_paths",),
        ("atom_routes",),
        (WRITE_QUICKTIME_ROUTING_SOURCE, WRITE_QUICKTIME_FULL_PATH_SOURCE),
    ),
    QuickTimeAtomTransactionEntry(
        3,
        "plan_metadata_atom_replacements",
        "metadata_atom_replacement",
        "payload_plan",
        "Plan ItemList/UserData/Keys atom upserts, deletes, and pending fanout atoms.",
        ("route_writes_to_full_atom_paths",),
        ("metadata_replacement_responsibilities",),
        (QUICKTIME_METADATA_TABLE_SOURCE, WRITE_QUICKTIME_CREATE_SOURCE),
    ),
    QuickTimeAtomTransactionEntry(
        4,
        "plan_tkhd_matrix_mutations",
        "matrix_tkhd_mutation",
        "payload_plan",
        "Plan video-track tkhd MatrixStructure mutation for QuickTime Rotation.",
        ("route_writes_to_full_atom_paths",),
        ("tkhd_matrix_responsibilities",),
        (QUICKTIME_ROTATION_SOURCE, QUICKTIME_TKHD_SOURCE),
    ),
    QuickTimeAtomTransactionEntry(
        5,
        "recalculate_modified_atom_sizes",
        "atom_size_recalculation",
        "size_plan",
        "Recalculate modified atom lengths and register modified uuid sizes for CTBO repair.",
        ("plan_metadata_atom_replacements", "plan_tkhd_matrix_mutations"),
        ("modified_atom_size_records",),
        (WRITE_QUICKTIME_SIZE_SOURCE,),
    ),
    QuickTimeAtomTransactionEntry(
        6,
        "preserve_or_schedule_mdat_chunks",
        "mdat_preservation",
        "media_plan",
        "Preserve top-level mdat chunks or schedule HEIC ItemInfo mdat edits.",
        ("walk_atom_tree_and_record_full_paths",),
        ("mdat_chunks", "mdat_edit_schedule"),
        (WRITE_QUICKTIME_MDAT_SOURCE,),
    ),
    QuickTimeAtomTransactionEntry(
        7,
        "collect_offset_sensitive_atoms",
        "offset_sensitive_blocker",
        "offset_plan",
        "Collect offset-bearing atoms and unsupported fragment/index boxes before output.",
        ("walk_atom_tree_and_record_full_paths", "preserve_or_schedule_mdat_chunks"),
        ("offset_sensitive_atoms", "offset_repair_blockers"),
        (WRITE_QUICKTIME_OFFSET_SOURCE, WRITE_QUICKTIME_OFFSET_FIXUP_SOURCE),
    ),
    QuickTimeAtomTransactionEntry(
        8,
        "stage_write_last_atoms",
        "write_last_ordering",
        "media_plan",
        "Stage atoms marked WriteLast so final output emits them after mdat.",
        ("recalculate_modified_atom_sizes", "preserve_or_schedule_mdat_chunks"),
        ("write_last_atoms",),
        (WRITE_QUICKTIME_SIZE_SOURCE, QUICKTIME_WRITE_LAST_SOURCE),
    ),
    QuickTimeAtomTransactionEntry(
        9,
        "gate_output_emission",
        "output_emission_gate",
        "emit_gate",
        "Expose the gates a mutating QuickTime transaction engine must satisfy before output.",
        (
            "collect_offset_sensitive_atoms",
            "stage_write_last_atoms",
            "recalculate_modified_atom_sizes",
        ),
        ("output_emission_gates",),
        (WRITE_QUICKTIME_FINAL_EMIT_SOURCE,),
    ),
)


def traversal_to_json(traversal: QuickTimeAtomTraversal | None) -> JsonObject | None:
    if traversal is None:
        return None
    return {
        "atom_nodes": [
            {
                "atom_type": node.atom_type,
                "full_path": node.full_path,
                "header_size": node.header_size,
                "is_container": node.is_container,
                "is_top_level": node.is_top_level,
                "offset": node.offset,
                "payload_offset": node.payload_offset,
                "payload_size": node.payload_size,
                "size": node.size,
                "write_last_semantics": node.write_last_semantics,
            }
            for node in traversal.atom_nodes
        ],
        "full_paths": list(traversal.full_paths),
        "mdat_chunks": [
            {
                "data_offset": chunk.data_offset,
                "data_size": chunk.data_size,
                "extends_to_eof": chunk.extends_to_eof,
                "header_size": chunk.header_size,
                "offset": chunk.offset,
                "path": chunk.path,
            }
            for chunk in traversal.mdat_chunks
        ],
        "offset_sensitive_atoms": [
            {
                "atom_type": atom.atom_type,
                "blocker_code": atom.blocker_code,
                "full_path": atom.full_path,
                "offset": atom.offset,
                "payload_size": atom.payload_size,
            }
            for atom in traversal.offset_sensitive_atoms
        ],
        "write_last_paths": list(traversal.write_last_paths),
    }


def dedupe[T](items: list[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(items))


def unique_evidence_ids(evidence_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(evidence_ids))
