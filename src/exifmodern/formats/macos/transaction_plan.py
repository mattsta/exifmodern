"""Source-grounded, non-mutating MacOS metadata transaction planning.

The planner mirrors the MacOS.pm surfaces that affect write routing: AppleDouble
sidecar records, ATTR extended attributes, MDItem pseudo-tags, Finder-mediated
pseudo-tags, and delete-only xattr pseudo-tags. It records preservation and
blockers, but it does not run macOS tools or rewrite bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MACOS_PM_SOURCE_PATH = "lib/Image/ExifTool/MacOS.pm"
APPLEDOUBLE_MAGIC = b"\x00\x05\x16\x07\x00"
APPLEDOUBLE_SIGNATURE_SUFFIX = b"\x00\x00Mac OS X        "
MACOS_SUPPORTED_APPLEDOUBLE_VERSION = 2
MACOS_SIDECAR_HEADER_LENGTH = 26
MACOS_SIDECAR_RECORD_LENGTH = 12
MACOS_MAX_RECORD_LENGTH = 100_000_000
ATTR_MIN_HEADER_LENGTH = 58
ATTR_ENTRY_COUNT_OFFSET = 66
ATTR_FIRST_ENTRY_OFFSET = 70

type MacOSRouteKind = Literal[
    "resource_fork",
    "attr_table",
    "xattr",
    "finder_info",
    "finder_pseudo",
    "mditem",
    "unknown_payload",
    "block",
]
type MacOSInputKind = Literal["sidecar_record", "attr_entry", "xattr", "mditem", "rewrite"]
type MacOSPlanStatus = Literal["planned", "blocked", "unsupported"]
type MacOSGroup2 = Literal[
    "Audio",
    "Author",
    "Camera",
    "Document",
    "Image",
    "Location",
    "Other",
    "Time",
    "Video",
]
type MacOSOperation = Literal["set", "delete", "conditional_replace", "shift"]
type MacOSMetadataValue = str | int | float | bytes | tuple[str, ...]
type MacOSMalformedCode = Literal[
    "invalid_macos_header",
    "unsupported_macos_version",
    "truncated_header",
    "record_size_too_large",
    "truncated_record",
    "invalid_attr_header",
    "truncated_attr_header",
    "truncated_attr_entry",
    "truncated_attr_name",
    "invalid_attr_offset",
    "truncated_attr_value",
]
type MacOSRewriteGateCode = Literal[
    "malformed_input_blocks_rewrite",
    "resource_fork_rewrite_not_implemented",
    "attr_table_rewrite_not_implemented",
    "xattr_set_rewrite_not_implemented",
    "xattr_delete_rewrite_not_implemented",
    "finder_osascript_rewrite_not_implemented",
    "setfile_rewrite_not_implemented",
    "tag_utility_rewrite_not_implemented",
    "conditional_replacement_not_supported",
    "time_shift_not_supported",
    "unknown_macos_tag",
    "planner_is_non_mutating",
    "macos_writer_not_implemented",
]

MACOS_MAIN_TABLE_SOURCE = "format.macos.main_table"
MACOS_MDITEM_TABLE_SOURCE = "format.macos.mditem_table"
MACOS_XATTR_TABLE_SOURCE = "format.macos.xattr_table"
MACOS_SET_TAGS_SOURCE = "format.macos.set_tags"
MACOS_DYNAMIC_MDITEM_SOURCE = "format.macos.dynamic_mditem"
MACOS_XATTR_READ_SOURCE = "format.macos.xattr_read_value"
MACOS_ATTR_SOURCE = "format.macos.attr_parser"
MACOS_SIDECAR_SOURCE = "format.macos.sidecar_parser"

MACOS_TRANSACTION_SOURCES = (
    MACOS_MAIN_TABLE_SOURCE,
    MACOS_MDITEM_TABLE_SOURCE,
    MACOS_XATTR_TABLE_SOURCE,
    MACOS_SET_TAGS_SOURCE,
    MACOS_DYNAMIC_MDITEM_SOURCE,
    MACOS_XATTR_READ_SOURCE,
    MACOS_ATTR_SOURCE,
    MACOS_SIDECAR_SOURCE,
)


@dataclass(frozen=True)
class MacOSKnownTag:
    tag_id: str
    tag_name: str
    route_kind: MacOSRouteKind
    group2: MacOSGroup2
    writable: bool = False
    delete_only: bool = False
    list_value: bool = False
    binary: bool = False
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MacOSXAttrPayload:
    attribute_name: str
    payload: bytes


@dataclass(frozen=True)
class MacOSMDItemValue:
    tag_name: str
    value: MacOSMetadataValue


@dataclass(frozen=True)
class MacOSRewriteRequest:
    tag_name: str
    operation: MacOSOperation
    value: MacOSMetadataValue | None = None


@dataclass(frozen=True)
class MacOSMalformedBlocker:
    code: MacOSMalformedCode
    reason: str
    byte_range: tuple[int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MacOSRewriteGate:
    code: MacOSRewriteGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MacOSRouteClassification:
    input_kind: MacOSInputKind
    route_kind: MacOSRouteKind
    tag_id: str
    tag_name: str
    group1: str
    group2: MacOSGroup2
    payload_range: tuple[int, int] | None = None
    payload: bytes = b""
    payload_preserved: bool = True
    writable: bool = False
    delete_only: bool = False
    binary: bool = False
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MacOSSidecarHeaderPlan:
    version: int | None
    entry_count: int
    valid: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MacOSMetadataTransactionPlan:
    status: MacOSPlanStatus
    evidence_ids: tuple[str, ...]
    known_tags: tuple[MacOSKnownTag, ...]
    sidecar_header: MacOSSidecarHeaderPlan | None
    routes: tuple[MacOSRouteClassification, ...]
    malformed_blockers: tuple[MacOSMalformedBlocker, ...]
    rewrite_gates: tuple[MacOSRewriteGate, ...]
    can_mutate_bytes: bool
    can_emit_output: bool
    preserved_payload_bytes: int
    original_bytes: bytes

    def emit(self) -> bytes:
        if not self.can_emit_output:
            codes = ", ".join(gate.code for gate in self.rewrite_gates)
            raise ValueError(f"MacOS metadata transaction output is gated: {codes}")
        return self.original_bytes


def mditem_known(tag_name: str, group2: MacOSGroup2) -> MacOSKnownTag:
    return MacOSKnownTag(
        tag_name,
        tag_name,
        "mditem",
        group2,
        evidence_ids=(MACOS_MDITEM_TABLE_SOURCE,),
    )


def xattr_known(attribute_name: str, tag_name: str, group2: MacOSGroup2) -> MacOSKnownTag:
    return MacOSKnownTag(
        attribute_name,
        tag_name,
        "xattr",
        group2,
        evidence_ids=(MACOS_XATTR_TABLE_SOURCE, MACOS_XATTR_READ_SOURCE),
    )


KNOWN_MDITEM_TAGS: dict[str, MacOSKnownTag] = {
    "MDItemFinderComment": MacOSKnownTag(
        "MDItemFinderComment",
        "MDItemFinderComment",
        "finder_pseudo",
        "Other",
        writable=True,
        evidence_ids=(MACOS_MDITEM_TABLE_SOURCE, MACOS_SET_TAGS_SOURCE),
    ),
    "MDItemFSLabel": MacOSKnownTag(
        "MDItemFSLabel",
        "MDItemFSLabel",
        "finder_pseudo",
        "Other",
        writable=True,
        evidence_ids=(MACOS_MDITEM_TABLE_SOURCE, MACOS_SET_TAGS_SOURCE),
    ),
    "MDItemFSCreationDate": MacOSKnownTag(
        "MDItemFSCreationDate",
        "MDItemFSCreationDate",
        "mditem",
        "Time",
        writable=True,
        evidence_ids=(MACOS_MDITEM_TABLE_SOURCE, MACOS_SET_TAGS_SOURCE),
    ),
    "MDItemUserTags": MacOSKnownTag(
        "MDItemUserTags",
        "MDItemUserTags",
        "mditem",
        "Other",
        writable=True,
        list_value=True,
        evidence_ids=(MACOS_MDITEM_TABLE_SOURCE, MACOS_SET_TAGS_SOURCE),
    ),
    "MDItemAuthors": mditem_known("MDItemAuthors", "Author"),
    "MDItemAcquisitionMake": mditem_known("MDItemAcquisitionMake", "Camera"),
    "MDItemAudioBitRate": mditem_known("MDItemAudioBitRate", "Audio"),
    "MDItemCity": mditem_known("MDItemCity", "Location"),
    "MDItemContentCreationDate": mditem_known("MDItemContentCreationDate", "Time"),
    "MDItemCreator": mditem_known("MDItemCreator", "Document"),
    "MDItemPixelWidth": mditem_known("MDItemPixelWidth", "Image"),
    "MDItemVideoBitRate": mditem_known("MDItemVideoBitRate", "Video"),
}

KNOWN_XATTR_TAGS: dict[str, MacOSKnownTag] = {
    "com.apple.FinderInfo": MacOSKnownTag(
        "com.apple.FinderInfo",
        "XAttrFinderInfo",
        "finder_info",
        "Other",
        binary=True,
        evidence_ids=(MACOS_XATTR_TABLE_SOURCE, MACOS_XATTR_READ_SOURCE),
    ),
    "com.apple.quarantine": MacOSKnownTag(
        "com.apple.quarantine",
        "XAttrQuarantine",
        "xattr",
        "Other",
        writable=True,
        delete_only=True,
        evidence_ids=(MACOS_XATTR_TABLE_SOURCE, MACOS_SET_TAGS_SOURCE),
    ),
    "com.apple.metadata:kMDItemWhereFroms": MacOSKnownTag(
        "com.apple.metadata:kMDItemWhereFroms",
        "XAttrMDItemWhereFroms",
        "xattr",
        "Other",
        writable=True,
        delete_only=True,
        evidence_ids=(MACOS_XATTR_TABLE_SOURCE, MACOS_SET_TAGS_SOURCE),
    ),
    "com.apple.metadata:kMDItemFinderComment": xattr_known(
        "com.apple.metadata:kMDItemFinderComment", "XAttrMDItemFinderComment", "Other"
    ),
    "com.apple.metadata:kMDItemDownloadedDate": xattr_known(
        "com.apple.metadata:kMDItemDownloadedDate", "XAttrMDItemDownloadedDate", "Time"
    ),
    "com.apple.metadata:com_apple_mail_dateReceived": xattr_known(
        "com.apple.metadata:com_apple_mail_dateReceived",
        "XAttrAppleMailDateReceived",
        "Time",
    ),
    "com.apple.metadata:com_apple_mail_dateSent": xattr_known(
        "com.apple.metadata:com_apple_mail_dateSent", "XAttrAppleMailDateSent", "Time"
    ),
    "com.apple.metadata:kMDLabel": MacOSKnownTag(
        "com.apple.metadata:kMDLabel",
        "XAttrMDLabel",
        "xattr",
        "Other",
        binary=True,
        evidence_ids=(MACOS_XATTR_TABLE_SOURCE, MACOS_XATTR_READ_SOURCE),
    ),
    "com.apple.ResourceFork": MacOSKnownTag(
        "com.apple.ResourceFork",
        "XAttrResourceFork",
        "resource_fork",
        "Other",
        binary=True,
        evidence_ids=(MACOS_XATTR_TABLE_SOURCE,),
    ),
    "com.apple.lastuseddate#PS": xattr_known(
        "com.apple.lastuseddate#PS", "XAttrLastUsedDate", "Time"
    ),
}


def build_macos_metadata_transaction_plan(
    source: bytes = b"",
    *,
    xattr_values: tuple[MacOSXAttrPayload, ...] = (),
    mditem_values: tuple[MacOSMDItemValue, ...] = (),
    rewrite_requests: tuple[MacOSRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> MacOSMetadataTransactionPlan:
    routes: list[MacOSRouteClassification] = []
    malformed_blockers: list[MacOSMalformedBlocker] = []
    sidecar_header = parse_sidecar(source, routes, malformed_blockers) if source else None

    for payload in xattr_values:
        routes.append(classify_xattr("xattr", payload.attribute_name, payload.payload, None))
    for mditem in mditem_values:
        routes.append(classify_mditem(mditem))

    rewrite_gates = rewrite_blockers(rewrite_requests, malformed_blockers)
    status = plan_status(malformed_blockers, rewrite_gates)
    if not allow_output_emission:
        rewrite_gates = (
            *rewrite_gates,
            MacOSRewriteGate(
                "planner_is_non_mutating",
                "Planner defaults to preserving MacOS metadata bytes until an emitter is explicit.",
                True,
                (MACOS_SET_TAGS_SOURCE,),
            ),
            MacOSRewriteGate(
                "macos_writer_not_implemented",
                "MacOS.pm invokes platform tools; this planner records routes only.",
                True,
                (MACOS_SET_TAGS_SOURCE,),
            ),
        )
    can_emit_output = status == "planned" and not any(
        gate.blocks_emission for gate in rewrite_gates
    )
    preserved_payload_bytes = sum(len(route.payload) for route in routes if route.payload_preserved)
    return MacOSMetadataTransactionPlan(
        status=status,
        evidence_ids=MACOS_TRANSACTION_SOURCES,
        known_tags=known_tags(),
        sidecar_header=sidecar_header,
        routes=tuple(routes),
        malformed_blockers=tuple(malformed_blockers),
        rewrite_gates=rewrite_gates,
        can_mutate_bytes=False,
        can_emit_output=can_emit_output,
        preserved_payload_bytes=preserved_payload_bytes,
        original_bytes=source,
    )


def parse_sidecar(
    source: bytes,
    routes: list[MacOSRouteClassification],
    malformed_blockers: list[MacOSMalformedBlocker],
) -> MacOSSidecarHeaderPlan:
    if not is_valid_sidecar_signature(source):
        malformed_blockers.append(
            malformed(
                "invalid_macos_header",
                "AppleDouble MacOS sidecar signature is invalid.",
                0,
                len(source),
            )
        )
        return MacOSSidecarHeaderPlan(None, 0, False, (MACOS_SIDECAR_SOURCE,))
    version = source[5]
    entry_count = int.from_bytes(source[24:26], "big")
    if version != MACOS_SUPPORTED_APPLEDOUBLE_VERSION:
        malformed_blockers.append(
            malformed(
                "unsupported_macos_version",
                f"AppleDouble version {version} is not supported by MacOS.pm.",
                5,
                6,
            )
        )
        return MacOSSidecarHeaderPlan(version, entry_count, False, (MACOS_SIDECAR_SOURCE,))
    header_end = MACOS_SIDECAR_HEADER_LENGTH + entry_count * MACOS_SIDECAR_RECORD_LENGTH
    if len(source) < header_end:
        malformed_blockers.append(
            malformed("truncated_header", "AppleDouble record table is truncated.", 26, len(source))
        )
        return MacOSSidecarHeaderPlan(version, entry_count, False, (MACOS_SIDECAR_SOURCE,))
    for index in range(entry_count):
        entry_offset = MACOS_SIDECAR_HEADER_LENGTH + index * MACOS_SIDECAR_RECORD_LENGTH
        tag_id = int.from_bytes(source[entry_offset : entry_offset + 4], "big")
        payload_offset = int.from_bytes(source[entry_offset + 4 : entry_offset + 8], "big")
        payload_length = int.from_bytes(source[entry_offset + 8 : entry_offset + 12], "big")
        if payload_length > MACOS_MAX_RECORD_LENGTH:
            malformed_blockers.append(
                malformed(
                    "record_size_too_large",
                    "AppleDouble record length exceeds the MacOS.pm safety cap.",
                    entry_offset + 8,
                    entry_offset + 12,
                )
            )
            break
        payload_end = payload_offset + payload_length
        if payload_end > len(source):
            malformed_blockers.append(
                malformed(
                    "truncated_record",
                    "AppleDouble record payload extends past the sidecar bytes.",
                    payload_offset,
                    min(payload_end, len(source)),
                )
            )
            break
        payload = source[payload_offset:payload_end]
        routes.append(classify_sidecar_record(tag_id, payload, payload_offset, payload_end))
        if tag_id == 9:
            parse_attr(payload, payload_offset, routes, malformed_blockers)
    return MacOSSidecarHeaderPlan(
        version, entry_count, not malformed_blockers, (MACOS_SIDECAR_SOURCE,)
    )


def parse_attr(
    data: bytes,
    data_pos: int,
    routes: list[MacOSRouteClassification],
    malformed_blockers: list[MacOSMalformedBlocker],
) -> None:
    if len(data) < ATTR_MIN_HEADER_LENGTH or data[34:38] != b"ATTR":
        malformed_blockers.append(
            malformed(
                "invalid_attr_header",
                "ATTR payload does not contain the MacOS.pm ATTR marker.",
                data_pos,
                data_pos + len(data),
            )
        )
        return
    if len(data) < ATTR_FIRST_ENTRY_OFFSET:
        malformed_blockers.append(
            malformed(
                "truncated_attr_header",
                "ATTR header is too short for the entry count used by MacOS.pm.",
                data_pos,
                data_pos + len(data),
            )
        )
        return
    entry_count = int.from_bytes(data[ATTR_ENTRY_COUNT_OFFSET:ATTR_FIRST_ENTRY_OFFSET], "big")
    pos = ATTR_FIRST_ENTRY_OFFSET
    for _ in range(entry_count):
        if pos + 12 > len(data):
            malformed_blockers.append(
                malformed(
                    "truncated_attr_entry",
                    "ATTR entry header is truncated.",
                    data_pos + pos,
                    data_pos + len(data),
                )
            )
            break
        value_offset = int.from_bytes(data[pos : pos + 4], "big") - data_pos
        value_length = int.from_bytes(data[pos + 4 : pos + 8], "big")
        name_length = data[pos + 10]
        if pos + 11 + name_length > len(data):
            malformed_blockers.append(
                malformed(
                    "truncated_attr_name",
                    "ATTR attribute name is truncated.",
                    data_pos + pos,
                    data_pos + len(data),
                )
            )
            break
        if value_offset < 0 or value_offset > len(data):
            malformed_blockers.append(
                malformed(
                    "invalid_attr_offset",
                    "ATTR value offset is outside the ATTR payload.",
                    data_pos + pos,
                    data_pos + pos + 4,
                )
            )
            break
        value_end = value_offset + value_length
        if value_end > len(data):
            malformed_blockers.append(
                malformed(
                    "truncated_attr_value",
                    "ATTR value extends past the ATTR payload.",
                    data_pos + value_offset,
                    data_pos + len(data),
                )
            )
            break
        attribute_name = data[pos + 11 : pos + 11 + name_length].rstrip(b"\x00").decode("utf-8")
        attribute_name = normalize_kmdlabel(attribute_name)
        routes.append(
            classify_xattr(
                "attr_entry",
                attribute_name,
                data[value_offset:value_end],
                (data_pos + value_offset, data_pos + value_end),
            )
        )
        pos += (11 + name_length + 3) & -4


def classify_sidecar_record(
    tag_id: int,
    payload: bytes,
    payload_start: int,
    payload_end: int,
) -> MacOSRouteClassification:
    if tag_id == 2:
        return MacOSRouteClassification(
            "sidecar_record",
            "resource_fork",
            "2",
            "RSRC",
            "MacOS",
            "Other",
            (payload_start, payload_end),
            payload,
            evidence_ids=(MACOS_MAIN_TABLE_SOURCE, MACOS_SIDECAR_SOURCE),
        )
    if tag_id == 9:
        return MacOSRouteClassification(
            "sidecar_record",
            "attr_table",
            "9",
            "ATTR",
            "MacOS",
            "Other",
            (payload_start, payload_end),
            payload,
            evidence_ids=(MACOS_MAIN_TABLE_SOURCE, MACOS_ATTR_SOURCE),
        )
    return MacOSRouteClassification(
        "sidecar_record",
        "unknown_payload",
        str(tag_id),
        f"MacOSRecord{tag_id}",
        "MacOS",
        "Other",
        (payload_start, payload_end),
        payload,
        evidence_ids=(MACOS_SIDECAR_SOURCE,),
    )


def classify_xattr(
    input_kind: Literal["attr_entry", "xattr"],
    attribute_name: str,
    payload: bytes,
    payload_range: tuple[int, int] | None,
) -> MacOSRouteClassification:
    normalized_name = normalize_kmdlabel(attribute_name)
    known = KNOWN_XATTR_TAGS.get(normalized_name)
    if known is None:
        tag_name = dynamic_xattr_tag_name(normalized_name)
        group2: MacOSGroup2 = "Time" if normalized_name.endswith("Date") else "Other"
        known = MacOSKnownTag(
            normalized_name,
            tag_name,
            "xattr",
            group2,
            binary=contains_binary_payload(normalized_name, payload),
            evidence_ids=(MACOS_XATTR_READ_SOURCE,),
        )
    return MacOSRouteClassification(
        input_kind,
        known.route_kind,
        known.tag_id,
        known.tag_name,
        "MacOS",
        known.group2,
        payload_range,
        payload,
        writable=known.writable,
        delete_only=known.delete_only,
        binary=known.binary or contains_binary_payload(normalized_name, payload),
        evidence_ids=known.evidence_ids,
    )


def classify_mditem(mditem: MacOSMDItemValue) -> MacOSRouteClassification:
    known = KNOWN_MDITEM_TAGS.get(mditem.tag_name)
    if known is None:
        group2 = dynamic_mditem_group(mditem.tag_name, mditem.value)
        known = MacOSKnownTag(
            mditem.tag_name,
            dynamic_mditem_tag_name(mditem.tag_name),
            "mditem",
            group2,
            evidence_ids=(MACOS_DYNAMIC_MDITEM_SOURCE,),
        )
    return MacOSRouteClassification(
        "mditem",
        known.route_kind,
        known.tag_id,
        known.tag_name,
        "MacOS",
        known.group2,
        writable=known.writable,
        delete_only=known.delete_only,
        evidence_ids=known.evidence_ids,
    )


def rewrite_blockers(
    rewrite_requests: tuple[MacOSRewriteRequest, ...],
    malformed_blockers: list[MacOSMalformedBlocker],
) -> tuple[MacOSRewriteGate, ...]:
    gates: list[MacOSRewriteGate] = []
    if malformed_blockers:
        gates.append(
            MacOSRewriteGate(
                "malformed_input_blocks_rewrite",
                "Malformed MacOS metadata must be preserved until the source can be read safely.",
                True,
                (MACOS_ATTR_SOURCE, MACOS_SIDECAR_SOURCE),
            )
        )
    for request in rewrite_requests:
        known = KNOWN_MDITEM_TAGS.get(request.tag_name)
        if known is None:
            known = next(
                (tag for tag in KNOWN_XATTR_TAGS.values() if tag.tag_name == request.tag_name),
                None,
            )
        if request.operation == "conditional_replace":
            gates.append(
                MacOSRewriteGate(
                    "conditional_replacement_not_supported",
                    "MacOS.pm warns that conditional replacement is not yet supported.",
                    True,
                    (MACOS_SET_TAGS_SOURCE,),
                )
            )
        if request.operation == "shift":
            gates.append(
                MacOSRewriteGate(
                    "time_shift_not_supported",
                    "MacOS.pm marks creation date shifting as not supported yet.",
                    True,
                    (MACOS_MDITEM_TABLE_SOURCE, MACOS_SET_TAGS_SOURCE),
                )
            )
        if known is None:
            gates.append(
                MacOSRewriteGate(
                    "unknown_macos_tag",
                    f"{request.tag_name} is not a known MacOS.pm writable tag in this slice.",
                    True,
                    (MACOS_MDITEM_TABLE_SOURCE, MACOS_XATTR_TABLE_SOURCE),
                )
            )
            continue
        gates.append(rewrite_gate_for_known_tag(known, request))
    return tuple(gates)


def rewrite_gate_for_known_tag(
    known: MacOSKnownTag, request: MacOSRewriteRequest
) -> MacOSRewriteGate:
    if known.route_kind == "resource_fork":
        return MacOSRewriteGate(
            "resource_fork_rewrite_not_implemented",
            "Resource fork byte rewrites are delegated to RSRC planning and are not emitted here.",
            True,
            known.evidence_ids,
        )
    if known.route_kind == "attr_table":
        return MacOSRewriteGate(
            "attr_table_rewrite_not_implemented",
            "ATTR table rebuilds require AppleDouble record layout rewrites.",
            True,
            known.evidence_ids,
        )
    if known.route_kind == "finder_pseudo":
        return MacOSRewriteGate(
            "finder_osascript_rewrite_not_implemented",
            "Finder comment and label writes route through osascript in MacOS.pm.",
            True,
            known.evidence_ids,
        )
    if known.tag_name == "MDItemFSCreationDate":
        return MacOSRewriteGate(
            "setfile_rewrite_not_implemented",
            "File creation date writes route through setfile in MacOS.pm.",
            True,
            known.evidence_ids,
        )
    if known.tag_name == "MDItemUserTags":
        return MacOSRewriteGate(
            "tag_utility_rewrite_not_implemented",
            "User tag writes route through the external tag utility in MacOS.pm.",
            True,
            known.evidence_ids,
        )
    if known.delete_only and request.operation == "delete":
        return MacOSRewriteGate(
            "xattr_delete_rewrite_not_implemented",
            "Delete-only xattr pseudo-tags route through xattr -d in MacOS.pm.",
            True,
            known.evidence_ids,
        )
    return MacOSRewriteGate(
        "xattr_set_rewrite_not_implemented",
        "Direct MacOS xattr setting is outside this non-mutating planner.",
        True,
        known.evidence_ids,
    )


def plan_status(
    malformed_blockers: list[MacOSMalformedBlocker],
    rewrite_gates: tuple[MacOSRewriteGate, ...],
) -> MacOSPlanStatus:
    if malformed_blockers:
        return "blocked"
    if any(gate.blocks_emission for gate in rewrite_gates):
        return "unsupported"
    return "planned"


def is_valid_sidecar_signature(source: bytes) -> bool:
    return (
        len(source) >= MACOS_SIDECAR_HEADER_LENGTH
        and source[:5] == APPLEDOUBLE_MAGIC
        and source[6:24] == APPLEDOUBLE_SIGNATURE_SUFFIX
    )


def malformed(
    code: MacOSMalformedCode,
    reason: str,
    start: int,
    end: int,
) -> MacOSMalformedBlocker:
    return MacOSMalformedBlocker(
        code, reason, (start, end), (MACOS_ATTR_SOURCE, MACOS_SIDECAR_SOURCE)
    )


def normalize_kmdlabel(attribute_name: str) -> str:
    return re.sub(
        r"^com\.apple\.metadata:kMDLabel_.*",
        "com.apple.metadata:kMDLabel",
        attribute_name,
    )


def dynamic_xattr_tag_name(attribute_name: str) -> str:
    name = attribute_name
    prefix = "com.apple."
    if name.startswith(prefix):
        name = name[len(prefix) :]
        name = re.sub(r"^metadata:_?k", "", name)
        name = re.sub(r"^metadata:(com_)?", "", name)
    name = re.sub(r"[.:_]([A-Za-z0-9])", lambda match: match.group(1).upper(), name)
    if not name:
        name = "Attribute"
    return "XAttr" + name[:1].upper() + name[1:]


def dynamic_mditem_tag_name(tag_name: str) -> str:
    name = re.sub(r"^com_", "", tag_name)
    name = re.sub(r"_([a-z])", lambda match: match.group(1).upper(), name)
    return name[:1].upper() + name[1:]


def dynamic_mditem_group(tag_name: str, value: MacOSMetadataValue) -> MacOSGroup2:
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value):
        return "Time"
    if "Audio" in tag_name:
        return "Audio"
    if "Copyright" in tag_name or "Author" in tag_name:
        return "Author"
    return "Other"


def contains_binary_payload(attribute_name: str, payload: bytes) -> bool:
    return (
        attribute_name == "com.apple.metadata:kMDLabel" or b"\x00" in payload or len(payload) > 200
    )


def known_tags() -> tuple[MacOSKnownTag, ...]:
    return (
        *KNOWN_MDITEM_TAGS.values(),
        *KNOWN_XATTR_TAGS.values(),
        MacOSKnownTag(
            "2",
            "RSRC",
            "resource_fork",
            "Other",
            evidence_ids=(MACOS_MAIN_TABLE_SOURCE,),
        ),
        MacOSKnownTag(
            "9",
            "ATTR",
            "attr_table",
            "Other",
            evidence_ids=(MACOS_MAIN_TABLE_SOURCE,),
        ),
    )
