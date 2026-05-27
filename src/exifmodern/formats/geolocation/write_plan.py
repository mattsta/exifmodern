"""Source-backed Geolocate write expansion.

ExifTool's write-only Geolocate tag expands a location lookup into concrete
GPS, XMP, or IPTC writes according to Writer.pl GetGeolocateTags. This module
keeps that source behavior as a domain adapter instead of spreading
Geolocation-specific routing through JPEG, IPTC, XMP, or GPS mutation code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.iptc.write_plan import (
    IptcApplicationWritePlan,
    IptcApplicationWriteStep,
    coalesce_iptc_application_steps,
    upsert_text_step,
)
from exifmodern.formats.xmp.property_write import (
    XMP_PROPERTY_TABLE_SOURCE,
    XMP_PROPERTY_WRITE_SOURCE,
    XmpGeneratedPlanDiagnostic,
    XmpGeneratedPropertyAssignment,
    XmpPropertyWritePlan,
    build_generated_xmp_property_write_plan,
)
from exifmodern.json_types import JsonObject
from exifmodern.package_resources import generated_index_package_path
from exifmodern.services.geolocation_index import (
    GeolocationEntry,
    GeolocationIndexRepository,
    GeolocationNearestMatch,
    load_geolocation_index_repository,
)
from exifmodern.write_plan import EvidenceAnchor, ExifGpsWritePlan, build_exif_gps_write_plan

type GeolocateWriteTargetGroup = Literal["default", "iptc"]
type GeolocateLookupKind = Literal["coordinates", "place"]
type GeolocateWriteDiagnosticReason = Literal[
    "unsupported_tag",
    "unsupported_option",
    "invalid_value",
    "lookup_not_found",
    "lookup_ambiguous",
    "unsupported_group",
]

DEFAULT_GELOCATION_PACKAGE = generated_index_package_path()
GEOLOCATE_TAG_ANCHOR = EvidenceAnchor(
    path="lib/Image/ExifTool.pm",
    line_start=2043,
    line_end=2092,
    symbol="Geolocate",
    evidence=(
        "The write-only Geolocate tag calls Geolocation::Geolocate/GetEntry and "
        "sets concrete GPS, XMP, or IPTC tags from the resolved row."
    ),
)
GEOLOCATE_TAG_ROUTING_ANCHOR = EvidenceAnchor(
    path="lib/Image/ExifTool/Writer.pl",
    line_start=3781,
    line_end=3828,
    symbol="GetGeolocateTags",
    evidence=(
        "GetGeolocateTags maps requested groups to XMP, IPTC, and GPS target tags "
        "and chooses place tags for coordinate lookups or GPS tags for place lookups."
    ),
)


@dataclass(frozen=True)
class GeolocateWriteDiagnostic:
    tag: str
    reason: GeolocateWriteDiagnosticReason
    detail: str
    evidence_anchors: tuple[EvidenceAnchor, ...] = (
        GEOLOCATE_TAG_ANCHOR,
        GEOLOCATE_TAG_ROUTING_ANCHOR,
    )

    def to_json(self) -> JsonObject:
        return {
            "detail": self.detail,
            "reason": self.reason,
            "tag": self.tag,
        }


@dataclass(frozen=True)
class GeolocateWriteRequest:
    tag: str
    value: str
    target_group: GeolocateWriteTargetGroup


@dataclass(frozen=True)
class GeolocateApiOptions:
    min_population: float | None = None
    composite_disabled: bool = False


@dataclass(frozen=True)
class ResolvedGeolocateEntry:
    entry: GeolocationEntry
    lookup_kind: GeolocateLookupKind
    distance: GeolocationNearestMatch | None

    @property
    def writes_place_tags(self) -> bool:
        return self.lookup_kind == "coordinates"


@dataclass(frozen=True)
class GeolocateJpegWritePlan:
    xmp_plan: XmpPropertyWritePlan | None
    iptc_plan: IptcApplicationWritePlan | None
    gps_plan: ExifGpsWritePlan | None
    resolved_entry_count: int
    evidence_ids: tuple[str, ...]

    @property
    def step_count(self) -> int:
        xmp_count = 0 if self.xmp_plan is None else len(self.xmp_plan.steps)
        iptc_count = 0 if self.iptc_plan is None else len(self.iptc_plan.steps)
        gps_count = 0 if self.gps_plan is None else len(self.gps_plan.steps)
        return xmp_count + iptc_count + gps_count


@dataclass(frozen=True)
class GeolocateJpegWritePlanResult:
    plan: GeolocateJpegWritePlan | None
    diagnostics: tuple[GeolocateWriteDiagnostic, ...]
    xmp_diagnostics: tuple[XmpGeneratedPlanDiagnostic, ...] = ()


def evidence_anchor_to_json(source: EvidenceAnchor) -> JsonObject:
    return {
        "evidence": source.evidence,
        "line_end": source.line_end,
        "line_start": source.line_start,
        "path": source.path,
        "symbol": source.symbol,
    }


def build_geolocate_jpeg_write_plan_from_args(
    write_args: tuple[str, ...],
    xmp_capability_audit: Path,
    generated_index_package: Path = DEFAULT_GELOCATION_PACKAGE,
) -> GeolocateJpegWritePlanResult:
    parsed = parse_geolocate_write_args(write_args)
    if parsed.diagnostics:
        return GeolocateJpegWritePlanResult(None, parsed.diagnostics)
    if not parsed.requests:
        return GeolocateJpegWritePlanResult(None, ())
    repository = load_geolocation_index_repository(generated_index_package)
    xmp_assignments: list[XmpGeneratedPropertyAssignment] = []
    iptc_steps: list[IptcApplicationWriteStep] = []
    gps_plan: ExifGpsWritePlan | None = None
    diagnostics: list[GeolocateWriteDiagnostic] = []
    resolved_count = 0
    for request in parsed.requests:
        resolved = resolve_geolocate_entry(request, parsed.options, repository)
        if isinstance(resolved, GeolocateWriteDiagnostic):
            diagnostics.append(resolved)
            continue
        resolved_count += 1
        if request.target_group == "default":
            if resolved.writes_place_tags:
                xmp_assignments.extend(xmp_place_assignments(resolved.entry))
            else:
                gps_plan = build_exif_gps_write_plan(
                    latitude=resolved.entry.latitude_degrees,
                    longitude=resolved.entry.longitude_degrees,
                    map_datum=None,
                )
        elif request.target_group == "iptc":
            if resolved.writes_place_tags:
                iptc_steps.extend(iptc_place_steps(resolved.entry))
            else:
                diagnostics.append(
                    GeolocateWriteDiagnostic(
                        request.tag,
                        "unsupported_group",
                        "IPTC Geolocate place-to-GPS expansion has no IPTC GPS target tags.",
                    )
                )
        else:
            diagnostics.append(
                GeolocateWriteDiagnostic(
                    request.tag,
                    "unsupported_group",
                    f"Unsupported Geolocate target group: {request.target_group}",
                )
            )
    if diagnostics:
        return GeolocateJpegWritePlanResult(None, tuple(diagnostics))
    xmp_plan = (
        build_generated_xmp_property_write_plan(xmp_capability_audit, tuple(xmp_assignments))
        if xmp_assignments
        else None
    )
    xmp_diagnostics = () if xmp_plan is None else xmp_plan.generated_diagnostics
    if xmp_diagnostics:
        return GeolocateJpegWritePlanResult(None, (), xmp_diagnostics)
    iptc_plan = (
        IptcApplicationWritePlan(coalesce_iptc_application_steps(tuple(iptc_steps)))
        if iptc_steps
        else None
    )
    if xmp_plan is None and iptc_plan is None and gps_plan is None:
        return GeolocateJpegWritePlanResult(None, ())
    return GeolocateJpegWritePlanResult(
        GeolocateJpegWritePlan(
            xmp_plan=xmp_plan,
            iptc_plan=iptc_plan,
            gps_plan=gps_plan,
            resolved_entry_count=resolved_count,
            evidence_ids=(
                "geolocation.write.geolocate_tag",
                "geolocation.write.geolocate_routing",
                XMP_PROPERTY_TABLE_SOURCE,
                XMP_PROPERTY_WRITE_SOURCE,
            ),
        ),
        (),
    )


@dataclass(frozen=True)
class ParsedGeolocateWriteArgs:
    requests: tuple[GeolocateWriteRequest, ...]
    options: GeolocateApiOptions
    diagnostics: tuple[GeolocateWriteDiagnostic, ...]


def parse_geolocate_write_args(write_args: tuple[str, ...]) -> ParsedGeolocateWriteArgs:
    requests: list[GeolocateWriteRequest] = []
    diagnostics: list[GeolocateWriteDiagnostic] = []
    min_population: float | None = None
    composite_disabled = False
    previous_was_api = False
    for arg in write_args:
        if previous_was_api:
            previous_was_api = False
            if arg.startswith("GeolocMinPop="):
                try:
                    min_population = float(arg.split("=", 1)[1])
                except ValueError:
                    diagnostics.append(
                        GeolocateWriteDiagnostic(
                            "GeolocMinPop",
                            "invalid_value",
                            "GeolocMinPop must be numeric.",
                        )
                    )
                continue
            if arg == "Composite=0":
                composite_disabled = True
                continue
            diagnostics.append(
                GeolocateWriteDiagnostic(
                    arg,
                    "unsupported_option",
                    "Geolocate JPEG write planning supports GeolocMinPop and Composite=0.",
                )
            )
            continue
        if arg == "-api":
            previous_was_api = True
            continue
        if not arg.startswith("-") or "=" not in arg:
            continue
        tag_token, value = arg[1:].split("=", 1)
        tag = tag_token.removesuffix("-").removesuffix("#")
        group, separator, leaf = tag.partition(":")
        if separator:
            if leaf != "Geolocate":
                diagnostics.append(unsupported_tag_diagnostic(tag))
            elif group.lower() == "iptc":
                requests.append(GeolocateWriteRequest(tag, value, "iptc"))
            else:
                diagnostics.append(
                    GeolocateWriteDiagnostic(
                        tag,
                        "unsupported_group",
                        "Current source-backed Geolocate writes support default and IPTC groups.",
                    )
                )
        elif tag == "Geolocate":
            requests.append(GeolocateWriteRequest(tag, value, "default"))
        else:
            diagnostics.append(unsupported_tag_diagnostic(tag))
    return ParsedGeolocateWriteArgs(
        requests=tuple(requests),
        options=GeolocateApiOptions(
            min_population=min_population,
            composite_disabled=composite_disabled,
        ),
        diagnostics=tuple(diagnostics),
    )


def unsupported_tag_diagnostic(tag: str) -> GeolocateWriteDiagnostic:
    return GeolocateWriteDiagnostic(
        tag,
        "unsupported_tag",
        "Geolocate adapter accepts Geolocate and IPTC:Geolocate assignments only.",
    )


def resolve_geolocate_entry(
    request: GeolocateWriteRequest,
    options: GeolocateApiOptions,
    repository: GeolocationIndexRepository,
) -> ResolvedGeolocateEntry | GeolocateWriteDiagnostic:
    coordinate = parse_coordinate_pair(request.value)
    if coordinate is not None:
        latitude, longitude = coordinate
        nearest_matches = repository.nearest(
            latitude,
            longitude,
            limit=1,
            min_population=options.min_population,
        )
        if not nearest_matches:
            return GeolocateWriteDiagnostic(
                request.tag,
                "lookup_not_found",
                f"No Geolocation row matched coordinates {request.value}.",
            )
        return ResolvedGeolocateEntry(
            nearest_matches[0].entry,
            "coordinates",
            nearest_matches[0],
        )
    place = parse_place_query(request.value)
    if place is None:
        return GeolocateWriteDiagnostic(
            request.tag,
            "invalid_value",
            "Geolocate value must be latitude/longitude or city[,region[,country-code]].",
        )
    city, region, country_code = place
    place_matches = repository.search(
        city=city,
        country_code=country_code,
        region=region,
        min_population=options.min_population,
    )
    if not place_matches:
        return GeolocateWriteDiagnostic(
            request.tag,
            "lookup_not_found",
            f"No Geolocation row matched place {request.value}.",
        )
    if len(place_matches) > 1:
        return GeolocateWriteDiagnostic(
            request.tag,
            "lookup_ambiguous",
            f"Geolocation place lookup matched {len(place_matches)} rows for {request.value}.",
        )
    return ResolvedGeolocateEntry(place_matches[0], "place", None)


def parse_coordinate_pair(value: str) -> tuple[float, float] | None:
    parts = split_geolocate_value(value)
    if len(parts) < 2:
        return None
    try:
        latitude = float(parts[0])
        longitude = float(parts[1])
    except ValueError:
        return None
    return latitude, longitude


def parse_place_query(value: str) -> tuple[str, str, str] | None:
    parts = split_geolocate_value(value)
    if not parts or not parts[0]:
        return None
    city = parts[0]
    region = parts[1] if len(parts) > 1 else ""
    country_code = parts[2] if len(parts) > 2 else ""
    return city, region, country_code


def split_geolocate_value(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def xmp_place_assignments(entry: GeolocationEntry) -> tuple[XmpGeneratedPropertyAssignment, ...]:
    assignments = [
        XmpGeneratedPropertyAssignment("XMP-photoshop:City", entry.city),
        XmpGeneratedPropertyAssignment("XMP-photoshop:State", entry.region),
        XmpGeneratedPropertyAssignment("XMP-iptcCore:CountryCode", entry.country_code),
        XmpGeneratedPropertyAssignment("XMP-photoshop:Country", entry.country),
    ]
    return tuple(assignment for assignment in assignments if assignment.value)


def iptc_place_steps(entry: GeolocationEntry) -> tuple[IptcApplicationWriteStep, ...]:
    steps = [
        upsert_text_step("City", (entry.city,)),
        upsert_text_step("Province-State", (entry.region,)),
        upsert_text_step("Country-PrimaryLocationCode", (iptc_country_code(entry),)),
        upsert_text_step("Country-PrimaryLocationName", (entry.country,)),
    ]
    return tuple(step for step in steps if step.values[0])


def iptc_country_code(entry: GeolocationEntry) -> str:
    if len(entry.country_code.encode("latin-1")) == 2:
        return f"{entry.country_code} "
    return entry.country_code
