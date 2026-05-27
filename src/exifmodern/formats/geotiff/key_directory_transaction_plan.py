"""GeoTIFF key-directory transaction planning.

This module mirrors the read-time GeoKey handling in ExifTool's GeoTiff.pm and
keeps mutation behind explicit gates.  It parses the GeoKeyDirectory header,
routes entry storage locations, decodes values from the GeoDoubleParams and
GeoAsciiParams blocks, and records why a rewrite is preserve-only or blocked.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

GEOTIFF_INLINE_LOCATION = 0
GEOTIFF_DIRECTORY_LOCATION = 0x87AF
GEOTIFF_DOUBLE_PARAMS_LOCATION = 0x87B0
GEOTIFF_ASCII_PARAMS_LOCATION = 0x87B1
GEOTIFF_ENTRY_SIZE = 8
GEOTIFF_HEADER_SIZE = 8
GEOTIFF_USER_DEFINED = 32767

type GeoTiffEndian = Literal["little", "big"]
type GeoTiffPlanStatus = Literal["planned", "blocked"]
type GeoTiffEntryFormatRoute = Literal[
    "inline_short",
    "geo_key_directory_short",
    "geo_double_params",
    "geo_ascii_params",
    "unknown_location",
    "unknown_key_preserved",
]
type GeoTiffValueDomain = Literal[
    "generated_version",
    "gt_model_type",
    "gt_raster_type",
    "epsg_geographic_type",
    "epsg_projected_type",
    "epsg_units",
    "free_text",
    "numeric_parameter",
    "unknown",
]
type GeoTiffCodeStatus = Literal[
    "source_table_known",
    "user_defined",
    "source_table_unmapped",
    "not_code_table_backed",
]
type GeoTiffActionKind = Literal[
    "parse_key_directory_header",
    "generate_geotiff_version_tag",
    "parse_key_entry",
    "route_inline_short",
    "route_directory_short",
    "route_double_params",
    "route_ascii_params",
    "preserve_unknown_key",
    "trim_ascii_terminator",
]
type GeoTiffBlockerCode = Literal[
    "bad_geotiff_directory",
    "truncated_key_directory_header",
    "truncated_key_directory_entries",
    "unexpected_geotiff_key_directory_version",
    "unknown_geotiff_location",
    "missing_geo_key_directory_short_data",
    "missing_geo_double_params",
    "truncated_geo_double_params",
    "missing_geo_ascii_params",
    "truncated_geo_ascii_params",
]
type GeoTiffRewriteGateCode = Literal[
    "non_mutating_plan_requires_explicit_rewrite_request",
    "preserve_only_rewrite_requires_explicit_gate",
]
type GeoTiffRewriteBlockerCode = Literal[
    "geotiff_key_mutation_not_implemented",
    "malformed_key_directory_blocks_rewrite",
    "unknown_keys_are_preserve_only",
]
type GeoTiffRewriteOperation = Literal["set", "delete"]
type GeoTiffValue = int | float | str | tuple[int, ...] | tuple[float, ...]


GEOTIFF_FORMAT_SOURCE = "geotiff.format"
GEOTIFF_MAIN_TABLE_SOURCE = "geotiff.main.table"
GEOTIFF_PROCESS_HEADER_SOURCE = "geotiff.process.header"
GEOTIFF_PROCESS_ENTRY_SOURCE = "geotiff.process.entry"
GEOTIFF_BLOCK_PRESERVE_SOURCE = "geotiff.block.preserve"

GEOTIFF_TRANSACTION_SOURCES = (
    GEOTIFF_FORMAT_SOURCE,
    GEOTIFF_MAIN_TABLE_SOURCE,
    GEOTIFF_PROCESS_HEADER_SOURCE,
    GEOTIFF_PROCESS_ENTRY_SOURCE,
    GEOTIFF_BLOCK_PRESERVE_SOURCE,
)


@dataclass(frozen=True)
class GeoTiffTagDefinition:
    tag_id: int
    name: str
    value_domain: GeoTiffValueDomain
    print_values: dict[int, str]


EPSG_UNITS: dict[int, str] = {
    9001: "Linear Meter",
    9002: "Linear Foot",
    9003: "Linear Foot US Survey",
    9004: "Linear Foot Modified American",
    9005: "Linear Foot Clarke",
    9006: "Linear Foot Indian",
    9007: "Linear Link",
    9008: "Linear Link Benoit",
    9009: "Linear Link Sears",
    9010: "Linear Chain Benoit",
    9011: "Linear Chain Sears",
    9012: "Linear Yard Sears",
    9013: "Linear Yard Indian",
    9014: "Linear Fathom",
    9015: "Linear Mile International Nautical",
    9101: "Angular Radian",
    9102: "Angular Degree",
    9103: "Angular Arc Minute",
    9104: "Angular Arc Second",
    9105: "Angular Grad",
    9106: "Angular Gon",
    9107: "Angular DMS",
    9108: "Angular DMS Hemisphere",
    GEOTIFF_USER_DEFINED: "User Defined",
}

GT_MODEL_TYPE_VALUES: dict[int, str] = {
    1: "Projected",
    2: "Geographic",
    3: "Geocentric",
    GEOTIFF_USER_DEFINED: "User Defined",
}
GT_RASTER_TYPE_VALUES: dict[int, str] = {
    1: "Pixel Is Area",
    2: "Pixel Is Point",
    GEOTIFF_USER_DEFINED: "User Defined",
}
GEOGRAPHIC_TYPE_VALUES: dict[int, str] = {
    4001: "Airy 1830",
    4002: "Airy Modified 1849",
    4003: "Australian National Spheroid",
    4004: "Bessel 1841",
    4005: "Bessel Modified",
    4006: "Bessel Namibia",
    4007: "Clarke 1858",
    4008: "Clarke 1866",
    4030: "WGS84",
    4267: "NAD27",
    4269: "NAD83",
    4326: "WGS 84",
    GEOTIFF_USER_DEFINED: "User Defined",
}
PROJECTED_CS_TYPE_VALUES: dict[int, str] = {
    26918: "NAD83 UTM zone 18N",
    GEOTIFF_USER_DEFINED: "User Defined",
}

KNOWN_TAGS: dict[int, GeoTiffTagDefinition] = {
    1024: GeoTiffTagDefinition(1024, "GTModelType", "gt_model_type", GT_MODEL_TYPE_VALUES),
    1025: GeoTiffTagDefinition(1025, "GTRasterType", "gt_raster_type", GT_RASTER_TYPE_VALUES),
    1026: GeoTiffTagDefinition(1026, "GTCitation", "free_text", {}),
    2048: GeoTiffTagDefinition(
        2048, "GeographicType", "epsg_geographic_type", GEOGRAPHIC_TYPE_VALUES
    ),
    2049: GeoTiffTagDefinition(2049, "GeogCitation", "free_text", {}),
    2052: GeoTiffTagDefinition(2052, "GeogLinearUnits", "epsg_units", EPSG_UNITS),
    2053: GeoTiffTagDefinition(2053, "GeogLinearUnitSize", "numeric_parameter", {}),
    2054: GeoTiffTagDefinition(2054, "GeogAngularUnits", "epsg_units", EPSG_UNITS),
    2055: GeoTiffTagDefinition(2055, "GeogAngularUnitSize", "numeric_parameter", {}),
    2057: GeoTiffTagDefinition(2057, "GeogSemiMajorAxis", "numeric_parameter", {}),
    2058: GeoTiffTagDefinition(2058, "GeogSemiMinorAxis", "numeric_parameter", {}),
    2059: GeoTiffTagDefinition(2059, "GeogInvFlattening", "numeric_parameter", {}),
    2060: GeoTiffTagDefinition(2060, "GeogAzimuthUnits", "epsg_units", EPSG_UNITS),
    2061: GeoTiffTagDefinition(2061, "GeogPrimeMeridianLong", "numeric_parameter", {}),
    2062: GeoTiffTagDefinition(2062, "GeogToWGS84", "numeric_parameter", {}),
    3072: GeoTiffTagDefinition(
        3072, "ProjectedCSType", "epsg_projected_type", PROJECTED_CS_TYPE_VALUES
    ),
    3076: GeoTiffTagDefinition(3076, "ProjLinearUnits", "epsg_units", EPSG_UNITS),
    3077: GeoTiffTagDefinition(3077, "ProjLinearUnitSize", "numeric_parameter", {}),
    4099: GeoTiffTagDefinition(4099, "VerticalUnits", "epsg_units", EPSG_UNITS),
}


@dataclass(frozen=True)
class GeoTiffRewriteUpdate:
    operation: GeoTiffRewriteOperation
    tag_id: int
    value: GeoTiffValue | None


@dataclass(frozen=True)
class GeoTiffKeyDirectoryRewriteRequest:
    preserve_only: bool = True
    updates: tuple[GeoTiffRewriteUpdate, ...] = ()


@dataclass(frozen=True)
class GeoTiffVersionPlan:
    version: int
    revision: int
    minor_revision: int
    value: str
    tag_name: str
    value_domain: GeoTiffValueDomain
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeoTiffAction:
    kind: GeoTiffActionKind
    target: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeoTiffBlocker:
    code: GeoTiffBlockerCode
    detail: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeoTiffRewriteGate:
    code: GeoTiffRewriteGateCode
    detail: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeoTiffRewriteBlocker:
    code: GeoTiffRewriteBlockerCode
    detail: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeoTiffKeyEntryPlan:
    index: int
    entry_offset: int
    key_id: int
    tag_name: str | None
    location: int
    count: int
    value_offset: int
    format_route: GeoTiffEntryFormatRoute
    value_domain: GeoTiffValueDomain
    value: GeoTiffValue | None
    printable_value: str | None
    code_status: GeoTiffCodeStatus
    value_byte_range: tuple[int, int] | None
    emits_metadata: bool
    blockers: tuple[GeoTiffBlocker, ...]
    evidence_ids: tuple[str, ...]

    @property
    def key_id_hex(self) -> str:
        return f"0x{self.key_id:04x}"


@dataclass(frozen=True)
class GeoTiffKeyDirectoryTransactionPlan:
    status: GeoTiffPlanStatus
    endian: GeoTiffEndian
    key_directory_size: int
    double_params_size: int | None
    ascii_params_size: int | None
    entry_count: int | None
    version: GeoTiffVersionPlan | None
    entries: tuple[GeoTiffKeyEntryPlan, ...]
    actions: tuple[GeoTiffAction, ...]
    blockers: tuple[GeoTiffBlocker, ...]
    rewrite_gates: tuple[GeoTiffRewriteGate, ...]
    rewrite_blockers: tuple[GeoTiffRewriteBlocker, ...]
    can_rewrite_preserved_blocks: bool
    evidence_ids: tuple[str, ...]


def build_geotiff_key_directory_transaction_plan(
    key_directory: bytes,
    *,
    geo_double_params: bytes | None = None,
    geo_ascii_params: bytes | None = None,
    endian: GeoTiffEndian = "little",
    rewrite_request: GeoTiffKeyDirectoryRewriteRequest | None = None,
    allow_preserve_only_rewrite: bool = False,
) -> GeoTiffKeyDirectoryTransactionPlan:
    actions = [
        GeoTiffAction(
            "parse_key_directory_header",
            "GeoTiffDirectory",
            (GEOTIFF_PROCESS_HEADER_SOURCE,),
        )
    ]
    blockers: list[GeoTiffBlocker] = []
    entries: list[GeoTiffKeyEntryPlan] = []

    if len(key_directory) < GEOTIFF_HEADER_SIZE:
        blockers.append(
            GeoTiffBlocker(
                "truncated_key_directory_header",
                "GeoTiffDirectory is shorter than the 8-byte GeoKeyDirectory header.",
                (GEOTIFF_PROCESS_HEADER_SOURCE,),
            )
        )
        return _build_plan(
            endian=endian,
            key_directory=key_directory,
            geo_double_params=geo_double_params,
            geo_ascii_params=geo_ascii_params,
            entry_count=None,
            version=None,
            entries=(),
            actions=tuple(actions),
            blockers=tuple(blockers),
            rewrite_request=rewrite_request,
            allow_preserve_only_rewrite=allow_preserve_only_rewrite,
        )

    version_number = read_u16(key_directory, 0, endian)
    revision = read_u16(key_directory, 2, endian)
    minor_revision = read_u16(key_directory, 4, endian)
    entry_count = read_u16(key_directory, 6, endian)
    version = GeoTiffVersionPlan(
        version_number,
        revision,
        minor_revision,
        f"{version_number}.{revision}.{minor_revision}",
        "GeoTiffVersion",
        "generated_version",
        (GEOTIFF_MAIN_TABLE_SOURCE, GEOTIFF_PROCESS_HEADER_SOURCE),
    )
    actions.append(
        GeoTiffAction(
            "generate_geotiff_version_tag",
            "GeoTiffVersion",
            (GEOTIFF_MAIN_TABLE_SOURCE, GEOTIFF_PROCESS_HEADER_SOURCE),
        )
    )
    if version_number != 1:
        blockers.append(
            GeoTiffBlocker(
                "unexpected_geotiff_key_directory_version",
                f"GeoKeyDirectory version {version_number} is not the expected major version 1.",
                (GEOTIFF_PROCESS_HEADER_SOURCE,),
            )
        )

    required_size = GEOTIFF_HEADER_SIZE + (entry_count * GEOTIFF_ENTRY_SIZE)
    if len(key_directory) < required_size:
        blockers.append(
            GeoTiffBlocker(
                "truncated_key_directory_entries",
                (f"GeoTiffDirectory does not contain the advertised {entry_count} GeoKey entries."),
                (GEOTIFF_PROCESS_HEADER_SOURCE,),
            )
        )
        return _build_plan(
            endian=endian,
            key_directory=key_directory,
            geo_double_params=geo_double_params,
            geo_ascii_params=geo_ascii_params,
            entry_count=entry_count,
            version=version,
            entries=(),
            actions=tuple(actions),
            blockers=tuple(blockers),
            rewrite_request=rewrite_request,
            allow_preserve_only_rewrite=allow_preserve_only_rewrite,
        )

    for index in range(entry_count):
        entry_offset = GEOTIFF_HEADER_SIZE + (index * GEOTIFF_ENTRY_SIZE)
        entry = _parse_entry(
            index=index,
            entry_offset=entry_offset,
            key_directory=key_directory,
            geo_double_params=geo_double_params,
            geo_ascii_params=geo_ascii_params,
            endian=endian,
        )
        entries.append(entry)
        actions.extend(_actions_for_entry(entry))
        blockers.extend(entry.blockers)

    return _build_plan(
        endian=endian,
        key_directory=key_directory,
        geo_double_params=geo_double_params,
        geo_ascii_params=geo_ascii_params,
        entry_count=entry_count,
        version=version,
        entries=tuple(entries),
        actions=tuple(actions),
        blockers=tuple(blockers),
        rewrite_request=rewrite_request,
        allow_preserve_only_rewrite=allow_preserve_only_rewrite,
    )


def _build_plan(
    *,
    endian: GeoTiffEndian,
    key_directory: bytes,
    geo_double_params: bytes | None,
    geo_ascii_params: bytes | None,
    entry_count: int | None,
    version: GeoTiffVersionPlan | None,
    entries: tuple[GeoTiffKeyEntryPlan, ...],
    actions: tuple[GeoTiffAction, ...],
    blockers: tuple[GeoTiffBlocker, ...],
    rewrite_request: GeoTiffKeyDirectoryRewriteRequest | None,
    allow_preserve_only_rewrite: bool,
) -> GeoTiffKeyDirectoryTransactionPlan:
    rewrite_gates = rewrite_gates_for_request(
        rewrite_request,
        allow_preserve_only_rewrite=allow_preserve_only_rewrite,
    )
    rewrite_blockers = rewrite_blockers_for_request(
        rewrite_request,
        entries=entries,
        blockers=blockers,
    )
    can_rewrite = (
        rewrite_request is not None
        and rewrite_request.preserve_only
        and len(rewrite_request.updates) == 0
        and allow_preserve_only_rewrite
        and len(blockers) == 0
        and len(rewrite_blockers) == 0
    )
    status: GeoTiffPlanStatus = "blocked" if blockers else "planned"
    return GeoTiffKeyDirectoryTransactionPlan(
        status=status,
        endian=endian,
        key_directory_size=len(key_directory),
        double_params_size=None if geo_double_params is None else len(geo_double_params),
        ascii_params_size=None if geo_ascii_params is None else len(geo_ascii_params),
        entry_count=entry_count,
        version=version,
        entries=entries,
        actions=actions,
        blockers=blockers,
        rewrite_gates=rewrite_gates,
        rewrite_blockers=rewrite_blockers,
        can_rewrite_preserved_blocks=can_rewrite,
        evidence_ids=GEOTIFF_TRANSACTION_SOURCES,
    )


def _parse_entry(
    *,
    index: int,
    entry_offset: int,
    key_directory: bytes,
    geo_double_params: bytes | None,
    geo_ascii_params: bytes | None,
    endian: GeoTiffEndian,
) -> GeoTiffKeyEntryPlan:
    key_id = read_u16(key_directory, entry_offset, endian)
    location = read_u16(key_directory, entry_offset + 2, endian)
    count = read_u16(key_directory, entry_offset + 4, endian)
    value_offset = read_u16(key_directory, entry_offset + 6, endian)
    tag_definition = KNOWN_TAGS.get(key_id)
    if tag_definition is None:
        return GeoTiffKeyEntryPlan(
            index=index,
            entry_offset=entry_offset,
            key_id=key_id,
            tag_name=None,
            location=location,
            count=count,
            value_offset=value_offset,
            format_route="unknown_key_preserved",
            value_domain="unknown",
            value=None,
            printable_value=None,
            code_status="not_code_table_backed",
            value_byte_range=None,
            emits_metadata=False,
            blockers=(),
            evidence_ids=(GEOTIFF_MAIN_TABLE_SOURCE, GEOTIFF_PROCESS_ENTRY_SOURCE),
        )

    value, byte_range, route, blockers = _read_entry_value(
        tag_name=tag_definition.name,
        location=location,
        count=count,
        value_offset=value_offset,
        entry_offset=entry_offset,
        key_directory=key_directory,
        geo_double_params=geo_double_params,
        geo_ascii_params=geo_ascii_params,
        endian=endian,
    )
    printable, code_status = printable_value_and_status(tag_definition, value)
    return GeoTiffKeyEntryPlan(
        index=index,
        entry_offset=entry_offset,
        key_id=key_id,
        tag_name=tag_definition.name,
        location=location,
        count=count,
        value_offset=value_offset,
        format_route=route,
        value_domain=tag_definition.value_domain,
        value=value,
        printable_value=printable,
        code_status=code_status,
        value_byte_range=byte_range,
        emits_metadata=len(blockers) == 0 and route != "unknown_location",
        blockers=blockers,
        evidence_ids=(GEOTIFF_MAIN_TABLE_SOURCE, GEOTIFF_FORMAT_SOURCE),
    )


def _read_entry_value(
    *,
    tag_name: str,
    location: int,
    count: int,
    value_offset: int,
    entry_offset: int,
    key_directory: bytes,
    geo_double_params: bytes | None,
    geo_ascii_params: bytes | None,
    endian: GeoTiffEndian,
) -> tuple[
    GeoTiffValue | None,
    tuple[int, int] | None,
    GeoTiffEntryFormatRoute,
    tuple[GeoTiffBlocker, ...],
]:
    if location == GEOTIFF_INLINE_LOCATION:
        value_start = entry_offset + 6
        return (
            read_u16(key_directory, value_start, endian),
            (value_start, value_start + 2),
            "inline_short",
            (),
        )
    if location == GEOTIFF_DIRECTORY_LOCATION:
        start = value_offset * 2
        size = count * 2
        if len(key_directory) < start + size:
            return (
                None,
                None,
                "geo_key_directory_short",
                (
                    GeoTiffBlocker(
                        "missing_geo_key_directory_short_data",
                        f"Missing int16u data for {tag_name}.",
                        (GEOTIFF_PROCESS_ENTRY_SOURCE,),
                    ),
                ),
            )
        short_values = tuple(
            read_u16(key_directory, start + (item_index * 2), endian) for item_index in range(count)
        )
        return collapse_ints(short_values), (start, start + size), "geo_key_directory_short", ()
    if location == GEOTIFF_DOUBLE_PARAMS_LOCATION:
        if geo_double_params is None:
            return (
                None,
                None,
                "geo_double_params",
                (
                    GeoTiffBlocker(
                        "missing_geo_double_params",
                        f"Missing double data for {tag_name}.",
                        (GEOTIFF_PROCESS_ENTRY_SOURCE,),
                    ),
                ),
            )
        start = value_offset * 8
        size = count * 8
        if len(geo_double_params) < start + size:
            return (
                None,
                None,
                "geo_double_params",
                (
                    GeoTiffBlocker(
                        "truncated_geo_double_params",
                        f"GeoTiffDoubleParams is too short for {tag_name}.",
                        (GEOTIFF_PROCESS_ENTRY_SOURCE,),
                    ),
                ),
            )
        float_values = tuple(
            read_float64(geo_double_params, start + (item_index * 8), endian)
            for item_index in range(count)
        )
        return collapse_floats(float_values), (start, start + size), "geo_double_params", ()
    if location == GEOTIFF_ASCII_PARAMS_LOCATION:
        if geo_ascii_params is None:
            return (
                None,
                None,
                "geo_ascii_params",
                (
                    GeoTiffBlocker(
                        "missing_geo_ascii_params",
                        f"Missing string data for {tag_name}.",
                        (GEOTIFF_PROCESS_ENTRY_SOURCE,),
                    ),
                ),
            )
        start = value_offset
        if len(geo_ascii_params) < start + count:
            return (
                None,
                None,
                "geo_ascii_params",
                (
                    GeoTiffBlocker(
                        "truncated_geo_ascii_params",
                        f"GeoTiffAsciiParams is too short for {tag_name}.",
                        (GEOTIFF_PROCESS_ENTRY_SOURCE,),
                    ),
                ),
            )
        raw_value = geo_ascii_params[start : start + count].decode("latin-1")
        if raw_value.endswith(("\0", "|")):
            raw_value = raw_value[:-1]
        return raw_value, (start, start + count), "geo_ascii_params", ()
    return (
        None,
        None,
        "unknown_location",
        (
            GeoTiffBlocker(
                "unknown_geotiff_location",
                f"Unknown GeoTiff location {location} for {tag_name}.",
                (GEOTIFF_FORMAT_SOURCE, GEOTIFF_PROCESS_ENTRY_SOURCE),
            ),
        ),
    )


def _actions_for_entry(entry: GeoTiffKeyEntryPlan) -> tuple[GeoTiffAction, ...]:
    actions = [
        GeoTiffAction(
            "parse_key_entry",
            entry.key_id_hex,
            (GEOTIFF_PROCESS_ENTRY_SOURCE,),
        )
    ]
    if entry.format_route == "inline_short":
        actions.append(
            GeoTiffAction("route_inline_short", entry.key_id_hex, (GEOTIFF_FORMAT_SOURCE,))
        )
    elif entry.format_route == "geo_key_directory_short":
        actions.append(
            GeoTiffAction("route_directory_short", entry.key_id_hex, (GEOTIFF_FORMAT_SOURCE,))
        )
    elif entry.format_route == "geo_double_params":
        actions.append(
            GeoTiffAction("route_double_params", entry.key_id_hex, (GEOTIFF_FORMAT_SOURCE,))
        )
    elif entry.format_route == "geo_ascii_params":
        actions.append(
            GeoTiffAction("route_ascii_params", entry.key_id_hex, (GEOTIFF_FORMAT_SOURCE,))
        )
        actions.append(
            GeoTiffAction(
                "trim_ascii_terminator",
                entry.key_id_hex,
                (GEOTIFF_PROCESS_ENTRY_SOURCE,),
            )
        )
    elif entry.format_route == "unknown_key_preserved":
        actions.append(
            GeoTiffAction("preserve_unknown_key", entry.key_id_hex, (GEOTIFF_MAIN_TABLE_SOURCE,))
        )
    return tuple(actions)


def rewrite_gates_for_request(
    rewrite_request: GeoTiffKeyDirectoryRewriteRequest | None,
    *,
    allow_preserve_only_rewrite: bool,
) -> tuple[GeoTiffRewriteGate, ...]:
    if rewrite_request is None:
        return (
            GeoTiffRewriteGate(
                "non_mutating_plan_requires_explicit_rewrite_request",
                "GeoTIFF planning is non-mutating unless a rewrite request is provided.",
                (GEOTIFF_BLOCK_PRESERVE_SOURCE,),
            ),
        )
    if rewrite_request.preserve_only and not allow_preserve_only_rewrite:
        return (
            GeoTiffRewriteGate(
                "preserve_only_rewrite_requires_explicit_gate",
                "Preserving GeoTIFF blocks through a rewrite requires an explicit gate.",
                (GEOTIFF_BLOCK_PRESERVE_SOURCE,),
            ),
        )
    return ()


def rewrite_blockers_for_request(
    rewrite_request: GeoTiffKeyDirectoryRewriteRequest | None,
    *,
    entries: tuple[GeoTiffKeyEntryPlan, ...],
    blockers: tuple[GeoTiffBlocker, ...],
) -> tuple[GeoTiffRewriteBlocker, ...]:
    rewrite_blockers: list[GeoTiffRewriteBlocker] = []
    if rewrite_request is not None and (
        not rewrite_request.preserve_only or rewrite_request.updates
    ):
        rewrite_blockers.append(
            GeoTiffRewriteBlocker(
                "geotiff_key_mutation_not_implemented",
                "This slice plans GeoTIFF key handling but does not mutate key entries.",
                (GEOTIFF_PROCESS_ENTRY_SOURCE,),
            )
        )
    if blockers:
        rewrite_blockers.append(
            GeoTiffRewriteBlocker(
                "malformed_key_directory_blocks_rewrite",
                "Malformed GeoTIFF key-directory or parameter data blocks rewrite.",
                (GEOTIFF_PROCESS_ENTRY_SOURCE,),
            )
        )
    if any(not entry.emits_metadata for entry in entries):
        rewrite_blockers.append(
            GeoTiffRewriteBlocker(
                "unknown_keys_are_preserve_only",
                "Unknown GeoTIFF keys are retained only as preserve-only records.",
                (GEOTIFF_MAIN_TABLE_SOURCE,),
            )
        )
    return tuple(rewrite_blockers)


def printable_value_and_status(
    tag_definition: GeoTiffTagDefinition,
    value: GeoTiffValue | None,
) -> tuple[str | None, GeoTiffCodeStatus]:
    if not isinstance(value, int):
        return (str(value) if value is not None else None), "not_code_table_backed"
    if not tag_definition.print_values:
        return str(value), "not_code_table_backed"
    printable = tag_definition.print_values.get(value)
    if printable is None:
        return None, "source_table_unmapped"
    if value == GEOTIFF_USER_DEFINED and printable == "User Defined":
        return printable, "user_defined"
    return printable, "source_table_known"


def collapse_ints(values: tuple[int, ...]) -> int | tuple[int, ...]:
    if len(values) == 1:
        return values[0]
    return values


def collapse_floats(values: tuple[float, ...]) -> float | tuple[float, ...]:
    if len(values) == 1:
        return values[0]
    return values


def read_u16(data: bytes, offset: int, endian: GeoTiffEndian) -> int:
    return int.from_bytes(data[offset : offset + 2], byteorder=endian)


def read_float64(data: bytes, offset: int, endian: GeoTiffEndian) -> float:
    format_code = "<d" if endian == "little" else ">d"
    value = struct.unpack(format_code, data[offset : offset + 8])[0]
    if not isinstance(value, float):
        raise TypeError("Expected float64 value")
    return value
