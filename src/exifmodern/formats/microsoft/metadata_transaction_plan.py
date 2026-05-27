"""Source-grounded, non-mutating Microsoft metadata transaction planning."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

MICROSOFT_SOURCE_PATH = "lib/Image/ExifTool/Microsoft.pm"

type MicrosoftSurfaceKind = Literal["xmp_packet", "quicktime_xtra_atom", "exif_stitch_binary"]
type MicrosoftNamespace = Literal["MicrosoftPhoto", "MP1", "MP", "MPRI", "MPReg"]
type MicrosoftTableKind = Literal["Stitch", "XMP", "MP1", "MP", "Xtra"]
type MicrosoftGroup0 = Literal["XMP", "QuickTime", "MakerNotes"]
type MicrosoftGroup1 = Literal["XMP-microsoft", "XMP-MP1", "XMP-MP", "Microsoft"]
type MicrosoftGroup2 = Literal["Image", "Video", "Time", "Author"]
type MicrosoftValueKind = Literal[
    "string",
    "real",
    "date",
    "unicode",
    "int64u",
    "guid",
    "variant",
    "unknown",
    "binary",
]
type MicrosoftRole = Literal[
    "photo_schema",
    "panoramic_stitch",
    "region_metadata",
    "region_time_metadata",
    "xtra_video_metadata",
    "xtra_author_metadata",
    "xtra_time_metadata",
    "unknown_payload",
]
type MicrosoftRouteAction = Literal[
    "route_microsoft_xmp_property",
    "route_microsoft_xtra_entry",
    "route_microsoft_stitch_binary",
    "preserve_unknown_microsoft_property",
    "preserve_unknown_xtra_entry",
    "preserve_raw_payload",
    "block_requested_rewrite",
    "route_source_backed_rewrite",
    "no_metadata_mutation",
]
type MicrosoftBlockerCode = Literal[
    "malformed_xmp_packet",
    "truncated_xmp_packet",
    "malformed_xtra_entry",
    "truncated_xtra_entry",
    "malformed_xtra_value",
    "truncated_stitch_binary",
]
type MicrosoftEmissionGateCode = Literal[
    "malformed_xmp_packet",
    "truncated_xmp_packet",
    "malformed_xtra_entry",
    "truncated_xtra_entry",
    "malformed_xtra_value",
    "truncated_stitch_binary",
    "unsupported_microsoft_rewrite",
    "source_backed_rewrite_requires_downstream_writer",
    "raw_payload_preservation_required",
    "planner_is_non_mutating",
    "microsoft_writer_not_implemented",
]
type MicrosoftRewriteOperation = Literal["replace_property", "delete_property", "insert_property"]
type MicrosoftMetadataValue = str | int | float | bytes | tuple[str | int | bytes, ...] | None

MICROSOFT_STITCH_SOURCE = "microsoft.stitch"
MICROSOFT_XMP_SOURCE = "microsoft.xmp"
MICROSOFT_MP1_SOURCE = "microsoft.mp1"
MICROSOFT_MP_SOURCE = "microsoft.mp"
MICROSOFT_XTRA_TABLE_SOURCE = "microsoft.xtra.table"
MICROSOFT_XTRA_GUID_SOURCE = "microsoft.xtra.guid"
MICROSOFT_READ_XTRA_SOURCE = "microsoft.read.xtra"
MICROSOFT_WRITE_XTRA_SOURCE = "microsoft.write.xtra"
MICROSOFT_PROCESS_XTRA_SOURCE = "microsoft.process.xtra"


@dataclass(frozen=True)
class MicrosoftPropertySpec:
    table: MicrosoftTableKind
    namespace: MicrosoftNamespace | None
    property_id: str
    tag_name: str
    group0: MicrosoftGroup0
    group1: MicrosoftGroup1
    group2: MicrosoftGroup2
    value_kind: MicrosoftValueKind
    role: MicrosoftRole
    writable: bool
    avoid: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MicrosoftTablePlan:
    table: MicrosoftTableKind
    group0: MicrosoftGroup0
    group1: MicrosoftGroup1
    group2: MicrosoftGroup2
    route: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "group0": self.group0,
            "group1": self.group1,
            "group2": self.group2,
            "route": self.route,
            "table": self.table,
        }


@dataclass(frozen=True)
class MicrosoftMetadataFieldPlan:
    table: MicrosoftTableKind
    namespace: MicrosoftNamespace | None
    property_id: str
    tag_name: str
    group0: MicrosoftGroup0
    group1: MicrosoftGroup1
    group2: MicrosoftGroup2
    role: MicrosoftRole
    value_kind: MicrosoftValueKind
    value: MicrosoftMetadataValue
    known: bool
    writable: bool
    avoid: bool
    byte_range: tuple[int, int] | None
    raw_payload: bytes
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "avoid": self.avoid,
            "byte_range": list(self.byte_range) if self.byte_range is not None else None,
            "group0": self.group0,
            "group1": self.group1,
            "group2": self.group2,
            "known": self.known,
            "namespace": self.namespace,
            "property_id": self.property_id,
            "raw_payload_hex": self.raw_payload.hex(),
            "role": self.role,
            "table": self.table,
            "tag_name": self.tag_name,
            "value": metadata_value_to_json(self.value),
            "value_kind": self.value_kind,
            "writable": self.writable,
        }


@dataclass(frozen=True)
class MicrosoftPayloadPreservationPlan:
    table: MicrosoftTableKind
    label: str
    byte_range: tuple[int, int]
    raw_payload: bytes
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": list(self.byte_range),
            "label": self.label,
            "raw_payload_hex": self.raw_payload.hex(),
            "reason": self.reason,
            "table": self.table,
        }


@dataclass(frozen=True)
class MicrosoftActionPlan:
    action: MicrosoftRouteAction
    target: str | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class MicrosoftTransactionBlocker:
    code: MicrosoftBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MicrosoftEmissionGate:
    code: MicrosoftEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MicrosoftRewriteRequest:
    operation: MicrosoftRewriteOperation
    table: MicrosoftTableKind
    property_id: str
    value: MicrosoftMetadataValue = None


@dataclass(frozen=True)
class MicrosoftMetadataTransactionPlan:
    surface_kind: MicrosoftSurfaceKind
    source_data: bytes
    tables: tuple[MicrosoftTablePlan, ...]
    fields: tuple[MicrosoftMetadataFieldPlan, ...]
    payload_preservations: tuple[MicrosoftPayloadPreservationPlan, ...]
    actions: tuple[MicrosoftActionPlan, ...]
    blockers: tuple[MicrosoftTransactionBlocker, ...]
    output_emission_gates: tuple[MicrosoftEmissionGate, ...]
    rewrite_requests: tuple[MicrosoftRewriteRequest, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def unknown_fields(self) -> tuple[MicrosoftMetadataFieldPlan, ...]:
        return tuple(field for field in self.fields if not field.known)

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"Microsoft metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "actions": [action.to_json() for action in self.actions],
            "blockers": [blocker.to_json() for blocker in self.blockers],
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "fields": [field.to_json() for field in self.fields],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "payload_preservations": [payload.to_json() for payload in self.payload_preservations],
            "rewrite_requests": [
                {
                    "operation": request.operation,
                    "property_id": request.property_id,
                    "table": request.table,
                    "value": metadata_value_to_json(request.value),
                }
                for request in self.rewrite_requests
            ],
            "source_data_hex": self.source_data.hex(),
            "surface_kind": self.surface_kind,
            "tables": [table.to_json() for table in self.tables],
        }


def build_microsoft_metadata_transaction_plan(
    data: bytes,
    *,
    surface_kind: MicrosoftSurfaceKind = "xmp_packet",
    rewrite_requests: tuple[MicrosoftRewriteRequest, ...] = (),
) -> MicrosoftMetadataTransactionPlan:
    """Build a Microsoft metadata plan without mutating input bytes."""

    fields: tuple[MicrosoftMetadataFieldPlan, ...]
    parse_actions: tuple[MicrosoftActionPlan, ...]
    blockers: tuple[MicrosoftTransactionBlocker, ...]
    payloads: tuple[MicrosoftPayloadPreservationPlan, ...]
    if surface_kind == "quicktime_xtra_atom":
        fields, payloads, parse_actions, blockers = parse_xtra_entries(data)
    elif surface_kind == "exif_stitch_binary":
        fields, payloads, parse_actions, blockers = parse_stitch_binary(data)
    else:
        fields, parse_actions, blockers = parse_xmp_properties(data)
        payloads = ()

    actions = (
        *parse_actions,
        *actions_for_rewrites(rewrite_requests),
        MicrosoftActionPlan(
            "no_metadata_mutation",
            None,
            "Planner records Microsoft.pm routing and preservation only.",
            (MICROSOFT_PROCESS_XTRA_SOURCE, MICROSOFT_MP_SOURCE),
        ),
    )
    gates = (
        *gates_for_blockers(blockers),
        *gates_for_rewrites(rewrite_requests),
        *default_output_gates(),
    )
    tables = table_plans()
    sources = unique_sources(
        (
            *(source for table in tables for source in table.evidence_ids),
            *(source for field in fields for source in field.evidence_ids),
            *(source for payload in payloads for source in payload.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for blocker in blockers for source in blocker.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return MicrosoftMetadataTransactionPlan(
        surface_kind=surface_kind,
        source_data=data,
        tables=tables,
        fields=fields,
        payload_preservations=payloads,
        actions=actions,
        blockers=blockers,
        output_emission_gates=unique_gates(gates),
        rewrite_requests=rewrite_requests,
        evidence_ids=sources,
    )


def parse_xmp_properties(
    data: bytes,
) -> tuple[
    tuple[MicrosoftMetadataFieldPlan, ...],
    tuple[MicrosoftActionPlan, ...],
    tuple[MicrosoftTransactionBlocker, ...],
]:
    if not data.strip():
        return (), (), ()
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        code: MicrosoftBlockerCode = (
            "truncated_xmp_packet" if looks_truncated_xml(data) else "malformed_xmp_packet"
        )
        return (
            (),
            (),
            (
                MicrosoftTransactionBlocker(
                    code,
                    f"Microsoft XMP/RDF XML could not be parsed: {error}.",
                    (MICROSOFT_XMP_SOURCE, MICROSOFT_MP1_SOURCE, MICROSOFT_MP_SOURCE),
                ),
            ),
        )

    fields: list[MicrosoftMetadataFieldPlan] = []
    actions: list[MicrosoftActionPlan] = []
    collect_xmp_properties(root, fields, actions)
    return tuple(fields), tuple(actions), ()


def collect_xmp_properties(
    element: ET.Element[str],
    fields: list[MicrosoftMetadataFieldPlan],
    actions: list[MicrosoftActionPlan],
) -> None:
    element_name = expanded_name(element.tag)
    for attr_name, attr_value in element.attrib.items():
        add_xmp_property(expanded_name(attr_name), attr_value, fields, actions)
    text = element.text.strip() if element.text is not None else ""
    if text:
        add_xmp_property(element_name, text, fields, actions)
    for child in list(element):
        collect_xmp_properties(child, fields, actions)


def add_xmp_property(
    name: ExpandedName,
    text: str,
    fields: list[MicrosoftMetadataFieldPlan],
    actions: list[MicrosoftActionPlan],
) -> None:
    namespace = namespace_for_uri(name.namespace_uri)
    if namespace is None:
        return
    table = table_for_namespace(namespace)
    spec = property_spec_for(table, name.local_name)
    if spec is None:
        source = source_for_table(table)
        fields.append(
            MicrosoftMetadataFieldPlan(
                table,
                namespace,
                name.local_name,
                f"{namespace}{name.local_name}",
                "XMP",
                group1_for_table(table),
                "Image",
                "unknown_payload",
                "string",
                text,
                False,
                False,
                False,
                None,
                b"",
                (source,),
            )
        )
        actions.append(
            MicrosoftActionPlan(
                "preserve_unknown_microsoft_property",
                name.local_name,
                (
                    "Microsoft namespace property is not declared in Microsoft.pm "
                    "and is preserved only."
                ),
                (source,),
            )
        )
        return
    fields.append(field_from_spec(spec, convert_text_value(text, spec.value_kind), None, b""))
    actions.append(
        MicrosoftActionPlan(
            "route_microsoft_xmp_property",
            spec.property_id,
            f"Route {spec.table}:{spec.property_id} through its Microsoft.pm XMP table.",
            spec.evidence_ids,
        )
    )


def parse_xtra_entries(
    data: bytes,
) -> tuple[
    tuple[MicrosoftMetadataFieldPlan, ...],
    tuple[MicrosoftPayloadPreservationPlan, ...],
    tuple[MicrosoftActionPlan, ...],
    tuple[MicrosoftTransactionBlocker, ...],
]:
    pos = 0
    fields: list[MicrosoftMetadataFieldPlan] = []
    payloads: list[MicrosoftPayloadPreservationPlan] = []
    actions: list[MicrosoftActionPlan] = []
    blockers: list[MicrosoftTransactionBlocker] = []
    while pos < len(data):
        if pos + 4 > len(data):
            blockers.append(
                MicrosoftTransactionBlocker(
                    "truncated_xtra_entry",
                    "Xtra entry ended before its 32-bit size field.",
                    (MICROSOFT_PROCESS_XTRA_SOURCE,),
                )
            )
            break
        size = int.from_bytes(data[pos : pos + 4], "big")
        if size < 8:
            blockers.append(
                MicrosoftTransactionBlocker(
                    "malformed_xtra_entry",
                    "Xtra entry size is smaller than the size and tag-length fields.",
                    (MICROSOFT_PROCESS_XTRA_SOURCE,),
                )
            )
            break
        if pos + size > len(data):
            blockers.append(
                MicrosoftTransactionBlocker(
                    "truncated_xtra_entry",
                    "Xtra entry size extends beyond available atom bytes.",
                    (MICROSOFT_PROCESS_XTRA_SOURCE,),
                )
            )
            break
        tag_len = int.from_bytes(data[pos + 4 : pos + 8], "big")
        if tag_len + 18 > size:
            blockers.append(
                MicrosoftTransactionBlocker(
                    "malformed_xtra_entry",
                    "Xtra tag length leaves no complete value header.",
                    (MICROSOFT_PROCESS_XTRA_SOURCE,),
                )
            )
            break
        tag_bytes = data[pos + 8 : pos + 8 + tag_len]
        value_start = pos + 8 + tag_len
        value_end = pos + size
        tag = tag_bytes.decode("utf-8", errors="replace")
        values, value_kind, value_blocker = read_xtra_values(data[value_start:value_end])
        if value_blocker is not None:
            blockers.append(value_blocker)
        spec = property_spec_for("Xtra", tag)
        if spec is None:
            generated_tag = generated_xtra_unknown_name(tag)
            fields.append(
                MicrosoftMetadataFieldPlan(
                    "Xtra",
                    None,
                    tag,
                    generated_tag,
                    "QuickTime",
                    "Microsoft",
                    "Video",
                    "unknown_payload",
                    value_kind,
                    values,
                    False,
                    False,
                    False,
                    (value_start, value_end),
                    data[value_start:value_end],
                    (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_PROCESS_XTRA_SOURCE),
                )
            )
            actions.append(
                MicrosoftActionPlan(
                    "preserve_unknown_xtra_entry",
                    tag,
                    "Xtra entry is not declared in Microsoft.pm and is preserved as raw payload.",
                    (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_PROCESS_XTRA_SOURCE),
                )
            )
        else:
            fields.append(
                field_from_spec(spec, values, (value_start, value_end), data[value_start:value_end])
            )
            actions.append(
                MicrosoftActionPlan(
                    "route_microsoft_xtra_entry",
                    spec.property_id,
                    f"Route Xtra tag {spec.property_id} through Microsoft.pm ProcessXtra.",
                    spec.evidence_ids,
                )
            )
        payloads.append(
            MicrosoftPayloadPreservationPlan(
                "Xtra",
                tag,
                (pos, pos + size),
                data[pos : pos + size],
                "The non-mutating slice keeps each Xtra entry byte-for-byte.",
                (MICROSOFT_PROCESS_XTRA_SOURCE,),
            )
        )
        actions.append(
            MicrosoftActionPlan(
                "preserve_raw_payload",
                tag,
                "Xtra entry raw bytes are preserved for downstream atom rewriting.",
                (MICROSOFT_PROCESS_XTRA_SOURCE,),
            )
        )
        pos += size
    return tuple(fields), tuple(payloads), tuple(actions), tuple(blockers)


def parse_stitch_binary(
    data: bytes,
) -> tuple[
    tuple[MicrosoftMetadataFieldPlan, ...],
    tuple[MicrosoftPayloadPreservationPlan, ...],
    tuple[MicrosoftActionPlan, ...],
    tuple[MicrosoftTransactionBlocker, ...],
]:
    blockers: tuple[MicrosoftTransactionBlocker, ...] = ()
    if data and len(data) < 12:
        blockers = (
            MicrosoftTransactionBlocker(
                "truncated_stitch_binary",
                "HDView stitch data is shorter than the first three int32 fields.",
                (MICROSOFT_STITCH_SOURCE,),
            ),
        )
    fields: list[MicrosoftMetadataFieldPlan] = []
    for offset, tag_name in (
        (0, "PanoramicStitchVersion"),
        (4, "PanoramicStitchCameraMotion"),
        (8, "PanoramicStitchMapType"),
    ):
        if len(data) >= offset + 4:
            value = int.from_bytes(data[offset : offset + 4], "little")
            spec = property_spec_for("Stitch", tag_name)
            if spec is not None:
                fields.append(
                    field_from_spec(spec, value, (offset, offset + 4), data[offset : offset + 4])
                )
    payloads = (
        (
            MicrosoftPayloadPreservationPlan(
                "Stitch",
                "HDViewStitchData",
                (0, len(data)),
                data,
                "Stitch binary payload is preserved because this slice does not emit BinaryData.",
                (MICROSOFT_STITCH_SOURCE,),
            ),
        )
        if data
        else ()
    )
    actions = (
        MicrosoftActionPlan(
            "route_microsoft_stitch_binary",
            "0x4748",
            "Route custom EXIF HDView stitch data through the Microsoft.pm Stitch table.",
            (MICROSOFT_STITCH_SOURCE,),
        ),
        MicrosoftActionPlan(
            "preserve_raw_payload",
            "HDViewStitchData",
            "Stitch raw bytes are preserved for downstream BinaryData rewriting.",
            (MICROSOFT_STITCH_SOURCE,),
        ),
    )
    return tuple(fields), payloads, actions, blockers


def read_xtra_values(
    data: bytes,
) -> tuple[MicrosoftMetadataValue, MicrosoftValueKind, MicrosoftTransactionBlocker | None]:
    if len(data) < 10:
        return (
            data,
            "binary",
            MicrosoftTransactionBlocker(
                "malformed_xtra_value",
                "Xtra value block is shorter than count, value length, and value type.",
                (MICROSOFT_READ_XTRA_SOURCE,),
            ),
        )
    count = int.from_bytes(data[0:4], "big")
    pos = 10
    values: list[str | int | bytes] = []
    value_kind: MicrosoftValueKind = "unknown"
    for _index in range(count):
        if pos > len(data):
            break
        value_len = int.from_bytes(data[pos - 6 : pos - 2], "big") - 6
        value_type = int.from_bytes(data[pos - 2 : pos], "big")
        if value_len < 0 or pos + value_len > len(data):
            return (
                tuple(values),
                value_kind,
                MicrosoftTransactionBlocker(
                    "malformed_xtra_value",
                    "Xtra value length extends beyond its entry payload.",
                    (MICROSOFT_READ_XTRA_SOURCE,),
                ),
            )
        raw_value = data[pos : pos + value_len]
        value, value_kind = decode_xtra_value(raw_value, value_type)
        values.append(value)
        pos += value_len + 6
    if len(values) == 1:
        return values[0], value_kind, None
    return tuple(values), value_kind, None


def decode_xtra_value(
    raw_value: bytes, value_type: int
) -> tuple[str | int | bytes, MicrosoftValueKind]:
    if value_type == 8:
        return raw_value.decode("utf-16-le", errors="replace").rstrip("\x00"), "unicode"
    if value_type == 19 and len(raw_value) == 8:
        return int.from_bytes(raw_value, "little"), "int64u"
    if value_type == 21 and len(raw_value) == 8:
        return int.from_bytes(raw_value, "little"), "date"
    if value_type == 72 and len(raw_value) == 16:
        packed = raw_value[3::-1] + raw_value[5:3:-1] + raw_value[7:5:-1] + raw_value[8:]
        hex_text = packed.hex().upper()
        return (
            f"{hex_text[0:8]}-{hex_text[8:12]}-{hex_text[12:16]}-{hex_text[16:20]}-{hex_text[20:32]}",
            "guid",
        )
    if value_type == 65 and len(raw_value) > 4:
        return raw_value, "variant"
    return raw_value, "unknown"


@dataclass(frozen=True)
class ExpandedName:
    namespace_uri: str | None
    local_name: str


def expanded_name(value: str) -> ExpandedName:
    if value.startswith("{"):
        namespace_uri, _, local_name = value[1:].partition("}")
        return ExpandedName(namespace_uri, local_name)
    if ":" in value:
        namespace_uri, _, local_name = value.partition(":")
        return ExpandedName(namespace_uri, local_name)
    return ExpandedName(None, value)


def namespace_for_uri(namespace_uri: str | None) -> MicrosoftNamespace | None:
    if namespace_uri in MICROSOFT_NAMESPACES:
        return MICROSOFT_NAMESPACES[namespace_uri]
    return None


def table_for_namespace(namespace: MicrosoftNamespace) -> MicrosoftTableKind:
    if namespace == "MicrosoftPhoto":
        return "XMP"
    if namespace == "MP1":
        return "MP1"
    return "MP"


def group1_for_table(table: MicrosoftTableKind) -> MicrosoftGroup1:
    if table == "XMP":
        return "XMP-microsoft"
    if table == "MP1":
        return "XMP-MP1"
    if table == "MP":
        return "XMP-MP"
    return "Microsoft"


def convert_text_value(text: str, value_kind: MicrosoftValueKind) -> MicrosoftMetadataValue:
    if value_kind == "real":
        try:
            return float(text)
        except ValueError:
            return text
    return text


def field_from_spec(
    spec: MicrosoftPropertySpec,
    value: MicrosoftMetadataValue,
    byte_range: tuple[int, int] | None,
    raw_payload: bytes,
) -> MicrosoftMetadataFieldPlan:
    return MicrosoftMetadataFieldPlan(
        spec.table,
        spec.namespace,
        spec.property_id,
        spec.tag_name,
        spec.group0,
        spec.group1,
        spec.group2,
        spec.role,
        spec.value_kind,
        value,
        True,
        spec.writable,
        spec.avoid,
        byte_range,
        raw_payload,
        spec.evidence_ids,
    )


def actions_for_rewrites(
    rewrite_requests: tuple[MicrosoftRewriteRequest, ...],
) -> tuple[MicrosoftActionPlan, ...]:
    actions: list[MicrosoftActionPlan] = []
    for request in rewrite_requests:
        spec = property_spec_for(request.table, request.property_id)
        if spec is not None and spec.writable:
            actions.append(
                MicrosoftActionPlan(
                    "route_source_backed_rewrite",
                    request.property_id,
                    (
                        "Rewrite target is declared writable by Microsoft.pm, but "
                        "no writer is emitted."
                    ),
                    spec.evidence_ids,
                )
            )
        else:
            source = spec.evidence_ids if spec is not None else (source_for_table(request.table),)
            actions.append(
                MicrosoftActionPlan(
                    "block_requested_rewrite",
                    request.property_id,
                    "Rewrite target is not a Microsoft.pm-backed writable field.",
                    source,
                )
            )
    return tuple(actions)


def gates_for_rewrites(
    rewrite_requests: tuple[MicrosoftRewriteRequest, ...],
) -> tuple[MicrosoftEmissionGate, ...]:
    gates: list[MicrosoftEmissionGate] = []
    for request in rewrite_requests:
        spec = property_spec_for(request.table, request.property_id)
        if spec is not None and spec.writable:
            gates.append(
                MicrosoftEmissionGate(
                    "source_backed_rewrite_requires_downstream_writer",
                    (
                        f"{request.table}:{request.property_id} is source-backed, "
                        "but this slice does not emit bytes."
                    ),
                    True,
                    spec.evidence_ids,
                )
            )
        else:
            source = spec.evidence_ids if spec is not None else (source_for_table(request.table),)
            gates.append(
                MicrosoftEmissionGate(
                    "unsupported_microsoft_rewrite",
                    (
                        f"{request.table}:{request.property_id} is not a supported "
                        "Microsoft.pm rewrite."
                    ),
                    True,
                    source,
                )
            )
    return tuple(gates)


def gates_for_blockers(
    blockers: tuple[MicrosoftTransactionBlocker, ...],
) -> tuple[MicrosoftEmissionGate, ...]:
    return tuple(
        MicrosoftEmissionGate(
            blocker.code,
            blocker.reason,
            True,
            blocker.evidence_ids,
        )
        for blocker in blockers
    )


def default_output_gates() -> tuple[MicrosoftEmissionGate, ...]:
    return (
        MicrosoftEmissionGate(
            "raw_payload_preservation_required",
            (
                "Microsoft XMP, Xtra, and stitch payloads must be preserved "
                "byte-for-byte by this slice."
            ),
            True,
            (MICROSOFT_PROCESS_XTRA_SOURCE, MICROSOFT_STITCH_SOURCE, MICROSOFT_MP_SOURCE),
        ),
        MicrosoftEmissionGate(
            "planner_is_non_mutating",
            "This transaction plan is intentionally non-mutating by default.",
            True,
            (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_MP_SOURCE),
        ),
        MicrosoftEmissionGate(
            "microsoft_writer_not_implemented",
            "No Microsoft.pm-backed output writer is implemented in this slice.",
            True,
            (MICROSOFT_WRITE_XTRA_SOURCE, MICROSOFT_XMP_SOURCE, MICROSOFT_STITCH_SOURCE),
        ),
    )


def table_plans() -> tuple[MicrosoftTablePlan, ...]:
    return (
        MicrosoftTablePlan(
            "Stitch",
            "MakerNotes",
            "Microsoft",
            "Image",
            "exif_tag_0x4748",
            (MICROSOFT_STITCH_SOURCE,),
        ),
        MicrosoftTablePlan(
            "XMP",
            "XMP",
            "XMP-microsoft",
            "Image",
            "xmp_microsoft_photo_1_0",
            (MICROSOFT_XMP_SOURCE,),
        ),
        MicrosoftTablePlan(
            "MP1", "XMP", "XMP-MP1", "Image", "xmp_microsoft_photo_1_1", (MICROSOFT_MP1_SOURCE,)
        ),
        MicrosoftTablePlan(
            "MP",
            "XMP",
            "XMP-MP",
            "Image",
            "xmp_microsoft_photo_1_2_regions",
            (MICROSOFT_MP_SOURCE,),
        ),
        MicrosoftTablePlan(
            "Xtra",
            "QuickTime",
            "Microsoft",
            "Video",
            "quicktime_xtra_atom",
            (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_PROCESS_XTRA_SOURCE),
        ),
    )


def property_spec_for(table: MicrosoftTableKind, property_id: str) -> MicrosoftPropertySpec | None:
    return MICROSOFT_PROPERTY_SPECS.get((table, property_id))


def source_for_table(table: MicrosoftTableKind) -> str:
    if table == "Stitch":
        return MICROSOFT_STITCH_SOURCE
    if table == "XMP":
        return MICROSOFT_XMP_SOURCE
    if table == "MP1":
        return MICROSOFT_MP1_SOURCE
    if table == "MP":
        return MICROSOFT_MP_SOURCE
    return MICROSOFT_XTRA_TABLE_SOURCE


def generated_xtra_unknown_name(tag: str) -> str:
    name = tag.removeprefix("WM/")
    if re.fullmatch(r"[-\w]+", name):
        return name[:1].upper() + name[1:]
    return tag


def looks_truncated_xml(data: bytes) -> bool:
    stripped = data.rstrip()
    return stripped.startswith(b"<") and not stripped.endswith(b">")


def metadata_value_to_json(value: MicrosoftMetadataValue) -> JsonValue:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, tuple):
        return [metadata_value_to_json(item) for item in value]
    return value


def evidence_ids_to_json(sources: tuple[str, ...]) -> JsonArray:
    return list(sources)


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        key = source
        if key not in seen:
            unique.append(source)
            seen.add(key)
    return tuple(unique)


def unique_gates(gates: tuple[MicrosoftEmissionGate, ...]) -> tuple[MicrosoftEmissionGate, ...]:
    unique: list[MicrosoftEmissionGate] = []
    seen: set[tuple[MicrosoftEmissionGateCode, str]] = set()
    for gate in gates:
        key = (gate.code, gate.reason)
        if key not in seen:
            unique.append(gate)
            seen.add(key)
    return tuple(unique)


MICROSOFT_NAMESPACES: dict[str, MicrosoftNamespace] = {
    "MicrosoftPhoto": "MicrosoftPhoto",
    "http://ns.microsoft.com/photo/1.0/": "MicrosoftPhoto",
    "MP1": "MP1",
    "http://ns.microsoft.com/photo/1.1/": "MP1",
    "MP": "MP",
    "http://ns.microsoft.com/photo/1.2/": "MP",
    "MPRI": "MPRI",
    "MPReg": "MPReg",
}

MICROSOFT_PROPERTY_SPECS: dict[tuple[MicrosoftTableKind, str], MicrosoftPropertySpec] = {
    ("Stitch", "PanoramicStitchVersion"): MicrosoftPropertySpec(
        "Stitch",
        None,
        "PanoramicStitchVersion",
        "PanoramicStitchVersion",
        "MakerNotes",
        "Microsoft",
        "Image",
        "binary",
        "panoramic_stitch",
        True,
        False,
        (MICROSOFT_STITCH_SOURCE,),
    ),
    ("Stitch", "PanoramicStitchCameraMotion"): MicrosoftPropertySpec(
        "Stitch",
        None,
        "PanoramicStitchCameraMotion",
        "PanoramicStitchCameraMotion",
        "MakerNotes",
        "Microsoft",
        "Image",
        "binary",
        "panoramic_stitch",
        True,
        False,
        (MICROSOFT_STITCH_SOURCE,),
    ),
    ("Stitch", "PanoramicStitchMapType"): MicrosoftPropertySpec(
        "Stitch",
        None,
        "PanoramicStitchMapType",
        "PanoramicStitchMapType",
        "MakerNotes",
        "Microsoft",
        "Image",
        "binary",
        "panoramic_stitch",
        True,
        False,
        (MICROSOFT_STITCH_SOURCE,),
    ),
    ("XMP", "CameraSerialNumber"): MicrosoftPropertySpec(
        "XMP",
        "MicrosoftPhoto",
        "CameraSerialNumber",
        "CameraSerialNumber",
        "XMP",
        "XMP-microsoft",
        "Image",
        "string",
        "photo_schema",
        True,
        False,
        (MICROSOFT_XMP_SOURCE,),
    ),
    ("XMP", "DateAcquired"): MicrosoftPropertySpec(
        "XMP",
        "MicrosoftPhoto",
        "DateAcquired",
        "DateAcquired",
        "XMP",
        "XMP-microsoft",
        "Time",
        "date",
        "photo_schema",
        True,
        False,
        (MICROSOFT_XMP_SOURCE,),
    ),
    ("XMP", "LensModel"): MicrosoftPropertySpec(
        "XMP",
        "MicrosoftPhoto",
        "LensModel",
        "LensModel",
        "XMP",
        "XMP-microsoft",
        "Image",
        "string",
        "photo_schema",
        True,
        True,
        (MICROSOFT_XMP_SOURCE,),
    ),
    ("XMP", "Rating"): MicrosoftPropertySpec(
        "XMP",
        "MicrosoftPhoto",
        "Rating",
        "RatingPercent",
        "XMP",
        "XMP-microsoft",
        "Image",
        "string",
        "photo_schema",
        True,
        False,
        (MICROSOFT_XMP_SOURCE,),
    ),
    ("XMP", "CreatorAppId"): MicrosoftPropertySpec(
        "XMP",
        "MicrosoftPhoto",
        "CreatorAppId",
        "CreatorAppID",
        "XMP",
        "XMP-microsoft",
        "Image",
        "string",
        "photo_schema",
        True,
        False,
        (MICROSOFT_XMP_SOURCE,),
    ),
    ("MP1", "PanoramicStitchCameraMotion"): MicrosoftPropertySpec(
        "MP1",
        "MP1",
        "PanoramicStitchCameraMotion",
        "PanoramicStitchCameraMotion",
        "XMP",
        "XMP-MP1",
        "Image",
        "string",
        "panoramic_stitch",
        True,
        False,
        (MICROSOFT_MP1_SOURCE,),
    ),
    ("MP1", "PanoramicStitchTheta0"): MicrosoftPropertySpec(
        "MP1",
        "MP1",
        "PanoramicStitchTheta0",
        "PanoramicStitchTheta0",
        "XMP",
        "XMP-MP1",
        "Image",
        "real",
        "panoramic_stitch",
        True,
        False,
        (MICROSOFT_MP1_SOURCE,),
    ),
    ("MP1", "WhiteBalance0"): MicrosoftPropertySpec(
        "MP1",
        "MP1",
        "WhiteBalance0",
        "WhiteBalance0",
        "XMP",
        "XMP-MP1",
        "Image",
        "real",
        "photo_schema",
        True,
        False,
        (MICROSOFT_MP1_SOURCE,),
    ),
    ("MP1", "Brightness"): MicrosoftPropertySpec(
        "MP1",
        "MP1",
        "Brightness",
        "Brightness",
        "XMP",
        "XMP-MP1",
        "Image",
        "string",
        "photo_schema",
        True,
        True,
        (MICROSOFT_MP1_SOURCE,),
    ),
    ("MP", "RegionInfo"): MicrosoftPropertySpec(
        "MP",
        "MP",
        "RegionInfo",
        "RegionInfoMP",
        "XMP",
        "XMP-MP",
        "Image",
        "string",
        "region_metadata",
        True,
        False,
        (MICROSOFT_MP_SOURCE,),
    ),
    ("MP", "RegionInfoDateRegionsValid"): MicrosoftPropertySpec(
        "MP",
        "MP",
        "RegionInfoDateRegionsValid",
        "RegionInfoDateRegionsValid",
        "XMP",
        "XMP-MP",
        "Time",
        "date",
        "region_time_metadata",
        True,
        False,
        (MICROSOFT_MP_SOURCE,),
    ),
    ("MP", "RegionInfoRegionsPersonDisplayName"): MicrosoftPropertySpec(
        "MP",
        "MP",
        "RegionInfoRegionsPersonDisplayName",
        "RegionPersonDisplayName",
        "XMP",
        "XMP-MP",
        "Image",
        "string",
        "region_metadata",
        True,
        False,
        (MICROSOFT_MP_SOURCE,),
    ),
    ("Xtra", "Author"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "Author",
        "Author",
        "QuickTime",
        "Microsoft",
        "Author",
        "unknown",
        "xtra_author_metadata",
        False,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE,),
    ),
    ("Xtra", "Copyright"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "Copyright",
        "Copyright",
        "QuickTime",
        "Microsoft",
        "Author",
        "unknown",
        "xtra_author_metadata",
        False,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE,),
    ),
    ("Xtra", "Description"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "Description",
        "Description",
        "QuickTime",
        "Microsoft",
        "Video",
        "unicode",
        "xtra_video_metadata",
        True,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_WRITE_XTRA_SOURCE),
    ),
    ("Xtra", "RecordingTime"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "RecordingTime",
        "RecordingTime",
        "QuickTime",
        "Microsoft",
        "Time",
        "unknown",
        "xtra_time_metadata",
        False,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE,),
    ),
    ("Xtra", "WM/AlbumTitle"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "WM/AlbumTitle",
        "AlbumTitle",
        "QuickTime",
        "Microsoft",
        "Video",
        "unicode",
        "xtra_video_metadata",
        True,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_WRITE_XTRA_SOURCE),
    ),
    ("Xtra", "WM/Category"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "WM/Category",
        "Category",
        "QuickTime",
        "Microsoft",
        "Video",
        "unicode",
        "xtra_video_metadata",
        True,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_WRITE_XTRA_SOURCE),
    ),
    ("Xtra", "WM/EncodingTime"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "WM/EncodingTime",
        "EncodingTime",
        "QuickTime",
        "Microsoft",
        "Time",
        "date",
        "xtra_time_metadata",
        True,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_WRITE_XTRA_SOURCE),
    ),
    ("Xtra", "WM/MediaClassPrimaryID"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "WM/MediaClassPrimaryID",
        "MediaClassPrimaryID",
        "QuickTime",
        "Microsoft",
        "Video",
        "guid",
        "xtra_video_metadata",
        True,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_WRITE_XTRA_SOURCE),
    ),
    ("Xtra", "WM/SharedUserRating"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "WM/SharedUserRating",
        "SharedUserRating",
        "QuickTime",
        "Microsoft",
        "Video",
        "int64u",
        "xtra_video_metadata",
        True,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_WRITE_XTRA_SOURCE),
    ),
    ("Xtra", "WM/Writer"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "WM/Writer",
        "Writer",
        "QuickTime",
        "Microsoft",
        "Author",
        "unicode",
        "xtra_author_metadata",
        True,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_WRITE_XTRA_SOURCE),
    ),
    ("Xtra", "{2CBAA8F5-D81F-47CA-B17A-F8D822300131} 100"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "{2CBAA8F5-D81F-47CA-B17A-F8D822300131} 100",
        "DateAcquired",
        "QuickTime",
        "Microsoft",
        "Time",
        "variant",
        "xtra_time_metadata",
        True,
        True,
        (MICROSOFT_XTRA_TABLE_SOURCE, MICROSOFT_XTRA_GUID_SOURCE, MICROSOFT_WRITE_XTRA_SOURCE),
    ),
    ("Xtra", "{F29F85E0-4FF9-1068-AB91-08002B27B3D9} 4"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "{F29F85E0-4FF9-1068-AB91-08002B27B3D9} 4",
        "Author",
        "QuickTime",
        "Microsoft",
        "Author",
        "unknown",
        "xtra_author_metadata",
        False,
        True,
        (MICROSOFT_XTRA_GUID_SOURCE,),
    ),
    ("Xtra", "{14B81DA1-0135-4D31-96D9-6CBFC9671A99} 36867"): MicrosoftPropertySpec(
        "Xtra",
        None,
        "{14B81DA1-0135-4D31-96D9-6CBFC9671A99} 36867",
        "DatePictureTaken",
        "QuickTime",
        "Microsoft",
        "Time",
        "unknown",
        "xtra_time_metadata",
        False,
        True,
        (MICROSOFT_XTRA_GUID_SOURCE,),
    ),
}
