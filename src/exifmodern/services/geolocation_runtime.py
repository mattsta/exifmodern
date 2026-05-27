"""Runtime Geolocation tag generation backed by the canonical package API."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from exifmodern.services.geolocation_index import (
    GeolocationEntry,
    GeolocationFilterField,
    GeolocationIndexRepository,
    GeolocationNearestMatch,
    GeolocationRegexFilter,
    load_geolocation_index_repository,
    source_distance_and_bearing,
)

type GeolocationRuntimeStatus = Literal[
    "resolved",
    "ambiguous_place",
    "missing_input",
    "not_found",
]
type GeolocationRuntimeDiagnosticCode = Literal[
    "resolved",
    "search_matched_multiple_cities",
    "multiple_geolocation_cities_possible",
    "missing_geolocation_input",
    "no_such_city",
    "no_suitable_location",
]
type GeolocationSourceInputStatus = Literal["coordinates", "city", "default", "missing"]
type GeolocationListStatus = Literal["listed", "empty"]
type GeolocationFeatureOptionMode = Literal["none", "include", "exclude"]
type GeolocationListSortMode = Literal["database", "city", "country"]

GEOLOCATION_DONE_EXTRACT_SOURCE_ID = "geolocation.done_extract"
GEOLOCATION_LOOKUP_SOURCE_ID = "geolocation.geolocate.lookup"
GEOLOCATION_ENTRY_SOURCE_ID = "geolocation.get_entry"
GEOLOCATION_LISTGEO_SOURCE_ID = "geolocation.listgeo"
GEOLOCATION_SORT_SOURCE_ID = "geolocation.sort_database"
GEOLOCATION_QUERY_PARSE_SOURCE_ID = "geolocation.query_parser"
GEOLOCATION_SOURCE_INPUT_SOURCE_ID = "geolocation.done_extract.input"

GEOLOCATION_DEFAULT_INPUT_TAGS: tuple[str, ...] = (
    "GPSLatitude",
    "GPSLongitude",
    "GPSLatitudeRef",
    "GPSLongitudeRef",
    "GPSCoordinates",
    "LocationShownGPSLatitude",
    "LocationShownGPSLongitude",
    "XMP:City",
    "State",
    "CountryCode",
    "Country",
    "IPTC:City",
    "Province-State",
    "Country-PrimaryLocationCode",
    "Country-PrimaryLocationName",
    "LocationShownCity",
    "LocationShownProvinceState",
    "LocationShownCountryCode",
    "LocationShownCountryName",
)


@dataclass(frozen=True)
class GeolocationRuntimeRequest:
    city: str = ""
    country_code: str = ""
    region: str = ""
    subregion: str = ""
    exact_place_names: tuple[str, ...] = ()
    latitude: float | None = None
    longitude: float | None = None
    language_code: str = ""
    limit: int = 1
    max_distance_km: float | None = None
    min_population: float | None = None
    feature_codes: tuple[str, ...] = ()
    excluded_feature_codes: tuple[str, ...] = ()
    regex_filters: tuple[GeolocationRegexFilter, ...] = ()
    use_alternate_names: bool = True
    allow_multiple_places: bool = False

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def has_place(self) -> bool:
        return bool(self.city)


@dataclass(frozen=True)
class GeolocationRuntimeTags:
    city: str
    country_code: str
    feature_code: str
    population: float
    position: str
    region: str | None = None
    subregion: str | None = None
    country: str | None = None
    timezone: str | None = None
    feature_type: str | None = None
    distance_km: str | None = None
    bearing_degrees: int | None = None

    def to_tag_values(self) -> dict[str, str | float | int]:
        values: dict[str, str | float | int] = {
            "GeolocationCity": self.city,
            "GeolocationCountryCode": self.country_code,
            "GeolocationFeatureCode": self.feature_code,
            "GeolocationPopulation": self.population,
            "GeolocationPosition": self.position,
        }
        optional_values: tuple[tuple[str, str | int | None], ...] = (
            ("GeolocationRegion", self.region),
            ("GeolocationSubregion", self.subregion),
            ("GeolocationCountry", self.country),
            ("GeolocationTimeZone", self.timezone),
            ("GeolocationFeatureType", self.feature_type),
            ("GeolocationDistance", self.distance_km),
            ("GeolocationBearing", self.bearing_degrees),
        )
        for tag, value in optional_values:
            if value is not None and value != "":
                values[tag] = value
        return values


@dataclass(frozen=True)
class GeolocationRuntimeDiagnostic:
    code: GeolocationRuntimeDiagnosticCode
    message: str
    candidate_count: int = 0


@dataclass(frozen=True)
class GeolocationRuntimeResult:
    status: GeolocationRuntimeStatus
    tags: tuple[GeolocationRuntimeTags, ...]
    source_reference_ids: tuple[str, ...]
    reason: str = ""
    candidate_count: int = 0
    diagnostics: tuple[GeolocationRuntimeDiagnostic, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"


@dataclass(frozen=True)
class GeolocationListRequest:
    language_code: str = ""
    include_alternate_names: bool = False
    sort_by_city: bool = False
    sort_mode: GeolocationListSortMode = "database"
    min_population: float | None = None
    feature_codes: tuple[str, ...] = ()
    excluded_feature_codes: tuple[str, ...] = ()
    include_header: bool = True
    include_title: bool = True


@dataclass(frozen=True)
class GeolocationFeatureOption:
    mode: GeolocationFeatureOptionMode
    feature_codes: tuple[str, ...]
    excluded_feature_codes: tuple[str, ...]
    source_reference_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeolocationParsedQuery:
    request: GeolocationRuntimeRequest
    source_reference_ids: tuple[str, ...]
    use_city_and_coordinates: bool = False


@dataclass(frozen=True)
class GeolocationSourceInput:
    status: GeolocationSourceInputStatus
    request: GeolocationRuntimeRequest
    query: str = ""
    tags_used: tuple[str, ...] = ()
    default_values: tuple[str, ...] = ()
    use_city_and_coordinates: bool = False
    source_reference_ids: tuple[str, ...] = (
        GEOLOCATION_SOURCE_INPUT_SOURCE_ID,
        GEOLOCATION_QUERY_PARSE_SOURCE_ID,
        GEOLOCATION_LOOKUP_SOURCE_ID,
    )


@dataclass(frozen=True)
class GeolocationListRow:
    city: str
    region: str
    subregion: str
    country_code: str
    country: str
    timezone: str
    feature_code: str
    population: float
    latitude: str
    longitude: str
    alternate_names: str | None = None

    def values(self) -> tuple[str, ...]:
        values = (
            self.city,
            self.region,
            self.subregion,
            self.country_code,
            self.country,
            self.timezone,
            self.feature_code,
            source_listgeo_population(self.population),
            self.latitude,
            self.longitude,
        )
        if self.alternate_names is None:
            return values
        return (*values, self.alternate_names)

    def to_csv_line(self) -> str:
        return ",".join(self.values())


@dataclass(frozen=True)
class GeolocationListResult:
    status: GeolocationListStatus
    rows: tuple[GeolocationListRow, ...]
    source_reference_ids: tuple[str, ...]
    alternate_names_column_available: bool
    title: str = "Geolocation database:"

    @property
    def csv_header(self) -> str:
        header = (
            "City",
            "Region",
            "Subregion",
            "CountryCode",
            "Country",
            "TimeZone",
            "FeatureCode",
            "Population",
            "Latitude",
            "Longitude",
        )
        if self.alternate_names_column_available:
            return ",".join((*header, "AltNames"))
        return ",".join(header)

    def csv_lines(self, request: GeolocationListRequest | None = None) -> tuple[str, ...]:
        active_request = request or GeolocationListRequest(
            include_alternate_names=self.alternate_names_column_available
        )
        lines: list[str] = []
        if active_request.include_title:
            lines.append(self.title)
        if active_request.include_header:
            lines.append(self.csv_header)
        lines.extend(row.to_csv_line() for row in self.rows)
        return tuple(lines)

    @property
    def csv_text(self) -> str:
        return "\n".join(self.csv_lines()) + "\n"


@dataclass(frozen=True)
class GeolocationRuntimeService:
    repository: GeolocationIndexRepository

    def resolve(self, request: GeolocationRuntimeRequest) -> GeolocationRuntimeResult:
        return resolve_geolocation_runtime(self.repository, request)

    def list_public(self, request: GeolocationListRequest) -> GeolocationListResult:
        return list_geolocation_public_runtime(self.repository, request)


@cache
def load_geolocation_runtime_service(package_path: Path) -> GeolocationRuntimeService:
    return GeolocationRuntimeService(load_geolocation_index_repository(package_path))


def geolocation_list_request_from_source_options(
    *,
    language_code: str = "",
    include_alternate_names: bool = False,
    sort_by_city: bool = False,
    min_population: float | None = None,
    feature_option: str = "",
    include_header: bool = True,
    include_title: bool = True,
) -> GeolocationListRequest:
    parsed_feature_option = parse_geolocation_feature_option(feature_option)
    return GeolocationListRequest(
        language_code=language_code,
        include_alternate_names=include_alternate_names,
        sort_by_city=sort_by_city,
        sort_mode="city" if sort_by_city else "database",
        min_population=min_population,
        feature_codes=parsed_feature_option.feature_codes,
        excluded_feature_codes=parsed_feature_option.excluded_feature_codes,
        include_header=include_header,
        include_title=include_title,
    )


def geolocation_runtime_request_from_source_query(
    value: str,
    *,
    language_code: str = "",
    limit: int = 1,
    max_distance_km: float | None = None,
    min_population: float | None = None,
    feature_option: str = "",
    use_alternate_names: bool = True,
    allow_multiple_places: bool = False,
) -> GeolocationParsedQuery:
    parsed_feature_option = parse_geolocation_feature_option(feature_option)
    parsed = parse_geolocation_source_query(value)
    request_limit = parsed.limit if parsed.limit is not None else limit
    request = GeolocationRuntimeRequest(
        city=parsed.city,
        country_code=parsed.country_code,
        region=parsed.region,
        subregion=parsed.subregion,
        exact_place_names=parsed.exact_place_names,
        latitude=parsed.latitude,
        longitude=parsed.longitude,
        language_code=language_code,
        limit=request_limit,
        max_distance_km=max_distance_km,
        min_population=min_population,
        feature_codes=parsed_feature_option.feature_codes,
        excluded_feature_codes=parsed_feature_option.excluded_feature_codes,
        regex_filters=parsed.regex_filters,
        use_alternate_names=use_alternate_names,
        allow_multiple_places=allow_multiple_places or parsed.allow_multiple_places,
    )
    return GeolocationParsedQuery(
        request=request,
        use_city_and_coordinates=parsed.use_city_and_coordinates,
        source_reference_ids=(GEOLOCATION_QUERY_PARSE_SOURCE_ID, GEOLOCATION_LOOKUP_SOURCE_ID),
    )


def geolocation_runtime_request_from_source_input(
    geolocation_option: str,
    tag_values: Mapping[str, str | int | float],
    *,
    language_code: str = "",
    limit: int = 1,
    max_distance_km: float | None = None,
    min_population: float | None = None,
    feature_option: str = "",
    use_alternate_names: bool = True,
    allow_multiple_places: bool = False,
) -> GeolocationSourceInput:
    option = parse_geolocation_source_input_option(geolocation_option)
    source_input = source_input_query_from_tags(
        option.tags,
        option.defaults,
        option.both,
        tag_values,
    )
    if source_input.query:
        parsed = geolocation_runtime_request_from_source_query(
            source_input.query,
            language_code=language_code,
            limit=limit,
            max_distance_km=max_distance_km,
            min_population=min_population,
            feature_option=feature_option,
            use_alternate_names=use_alternate_names,
            allow_multiple_places=allow_multiple_places,
        )
        return GeolocationSourceInput(
            status=source_input.status,
            request=parsed.request,
            query=source_input.query,
            tags_used=source_input.tags_used,
            default_values=option.defaults,
            use_city_and_coordinates=parsed.use_city_and_coordinates,
        )
    parsed_feature_option = parse_geolocation_feature_option(feature_option)
    return GeolocationSourceInput(
        status="missing",
        request=GeolocationRuntimeRequest(
            language_code=language_code,
            limit=limit,
            max_distance_km=max_distance_km,
            min_population=min_population,
            feature_codes=parsed_feature_option.feature_codes,
            excluded_feature_codes=parsed_feature_option.excluded_feature_codes,
            use_alternate_names=use_alternate_names,
            allow_multiple_places=allow_multiple_places,
        ),
        default_values=option.defaults,
    )


@dataclass(frozen=True)
class GeolocationSourceInputOption:
    tags: tuple[str, ...]
    defaults: tuple[str, ...]
    both: bool = False


@dataclass(frozen=True)
class GeolocationSourceInputQuery:
    status: GeolocationSourceInputStatus
    query: str = ""
    tags_used: tuple[str, ...] = ()


def parse_geolocation_source_input_option(value: str) -> GeolocationSourceInputOption:
    defaults: list[str] = []
    tags: list[str] = []
    both = False
    for raw_piece in value.strip().split(","):
        piece = raw_piece.strip()
        if not piece:
            continue
        if piece.casefold() == "both":
            both = True
            continue
        if piece.startswith("$"):
            tag = piece[1:]
            if tag:
                tags.append(tag)
            continue
        defaults.append(piece)
    return GeolocationSourceInputOption(
        tags=tuple(tags) if tags else GEOLOCATION_DEFAULT_INPUT_TAGS,
        defaults=tuple(defaults),
        both=both,
    )


def source_input_query_from_tags(
    tags: tuple[str, ...],
    defaults: tuple[str, ...],
    both: bool,
    tag_values: Mapping[str, str | int | float],
) -> GeolocationSourceInputQuery:
    coordinates: list[str] = []
    coordinate_tags: list[str] = []
    refs: list[str] = ["", ""]
    city_values: list[str] = []
    city_tags: list[str] = []
    done_city = False
    for tag in tags:
        value = source_input_tag_value(tag_values, tag)
        if value is None:
            continue
        text = str(value)
        if "Coordinates" in tag:
            if len(coordinates) < 2:
                coordinates = text.split(" ")[:2]
                coordinate_tags = [*coordinate_tags, tag][:1]
            continue
        coordinate_index = source_input_coordinate_index(tag)
        if coordinate_index is not None:
            if tag.endswith("Ref"):
                if not refs[coordinate_index]:
                    refs[coordinate_index] = text
            elif len(coordinates) <= coordinate_index:
                while len(coordinates) < coordinate_index:
                    coordinates.append("")
                coordinates.append(text)
                coordinate_tags.append(tag)
            continue
        if "City" in tag:
            if city_values:
                done_city = True
                continue
            city_values.append(text)
            city_tags.append(tag)
        elif city_values:
            if not done_city:
                city_values.append(text)
                city_tags.append(tag)
            if done_city:
                continue
    if len(coordinates) >= 2 and coordinates[0] and coordinates[1]:
        coordinates[0] = source_input_signed_coordinate(coordinates[0], refs[0], "S")
        coordinates[1] = source_input_signed_coordinate(coordinates[1], refs[1], "W")
        query = ",".join((coordinates[0], coordinates[1]))
        if both:
            query = f"{query},both"
        return GeolocationSourceInputQuery(
            status="coordinates",
            query=query,
            tags_used=tuple(coordinate_tags),
        )
    if city_values:
        query = ",".join(city_values)
        if both:
            query = f"{query},both"
        return GeolocationSourceInputQuery(
            status="city",
            query=query,
            tags_used=tuple(city_tags),
        )
    query = ",".join(defaults)
    if query == "1":
        return GeolocationSourceInputQuery(status="missing")
    if query:
        return GeolocationSourceInputQuery(status="default", query=f"{query},both")
    return GeolocationSourceInputQuery(status="missing")


def source_input_tag_value(
    tag_values: Mapping[str, str | int | float],
    tag: str,
) -> str | int | float | None:
    value = tag_values.get(tag)
    if value is not None:
        return value
    normalized_tag = tag.casefold()
    for key, candidate in tag_values.items():
        if key.casefold() == normalized_tag:
            return candidate
    return None


def source_input_coordinate_index(tag: str) -> int | None:
    if "Latitude" in tag:
        return 0
    if "Longitude" in tag:
        return 1
    return None


def source_input_signed_coordinate(value: str, ref: str, negative_ref: str) -> str:
    coordinate = _source_query_float(value)
    if coordinate is None:
        return value
    if ref == negative_ref and coordinate > 0:
        return str(-coordinate)
    return value


@dataclass(frozen=True)
class ParsedGeolocationSourceQuery:
    city: str = ""
    country_code: str = ""
    region: str = ""
    subregion: str = ""
    exact_place_names: tuple[str, ...] = ()
    latitude: float | None = None
    longitude: float | None = None
    regex_filters: tuple[GeolocationRegexFilter, ...] = ()
    limit: int | None = None
    allow_multiple_places: bool = False
    use_city_and_coordinates: bool = False


def parse_geolocation_source_query(value: str) -> ParsedGeolocationSourceQuery:
    city = ""
    country_code = ""
    region = ""
    subregion = ""
    exact_place_names: list[str] = []
    coordinates: list[float] = []
    regex_filters: list[GeolocationRegexFilter] = []
    limit: int | None = None
    use_city_and_coordinates = False
    for raw_piece in value.strip().split(","):
        piece = raw_piece.strip()
        if not piece:
            continue
        phrase_coordinates = _source_query_lat_lon_phrase(piece)
        if phrase_coordinates is not None and not coordinates:
            coordinates.extend(phrase_coordinates)
            continue
        if piece.casefold() == "both":
            use_city_and_coordinates = True
            continue
        if piece.casefold().startswith("num="):
            limit = _source_query_limit(piece)
            continue
        regex_filter = _source_query_regex_filter(piece)
        if regex_filter is not None:
            regex_filters.append(regex_filter)
            continue
        coordinate = _source_query_float(piece)
        if coordinate is not None:
            if len(coordinates) < 2:
                coordinates.append(coordinate)
            continue
        if not city:
            city = piece
            continue
        if _looks_like_country_code(piece) and not country_code:
            country_code = piece
        exact_place_names.append(piece)
    latitude = coordinates[0] if len(coordinates) == 2 else None
    longitude = coordinates[1] if len(coordinates) == 2 else None
    return ParsedGeolocationSourceQuery(
        city=city,
        country_code=country_code,
        region=region,
        subregion=subregion,
        exact_place_names=tuple(exact_place_names),
        latitude=latitude,
        longitude=longitude,
        regex_filters=tuple(regex_filters),
        limit=limit,
        allow_multiple_places=limit is not None and limit > 1 and latitude is None,
        use_city_and_coordinates=use_city_and_coordinates,
    )


def parse_geolocation_feature_option(value: str) -> GeolocationFeatureOption:
    stripped_value = value.strip()
    if not stripped_value:
        return GeolocationFeatureOption(
            mode="none",
            feature_codes=(),
            excluded_feature_codes=(),
            source_reference_ids=(GEOLOCATION_LISTGEO_SOURCE_ID, GEOLOCATION_LOOKUP_SOURCE_ID),
        )
    exclude_mode = stripped_value.startswith("-")
    if exclude_mode:
        stripped_value = stripped_value[1:]
    feature_codes = tuple(
        feature_code
        for piece in stripped_value.split(",")
        if (feature_code := piece.strip().lstrip("-"))
    )
    return GeolocationFeatureOption(
        mode="exclude" if exclude_mode else "include",
        feature_codes=() if exclude_mode else feature_codes,
        excluded_feature_codes=feature_codes if exclude_mode else (),
        source_reference_ids=(GEOLOCATION_LISTGEO_SOURCE_ID, GEOLOCATION_LOOKUP_SOURCE_ID),
    )


def resolve_geolocation_runtime(
    repository: GeolocationIndexRepository,
    request: GeolocationRuntimeRequest,
) -> GeolocationRuntimeResult:
    if not request.has_coordinates and not request.has_place:
        return geolocation_runtime_result(
            "missing_input",
            (),
            "Geolocation runtime requires either coordinates or a city.",
        )
    if request.has_coordinates and request.has_place:
        return resolve_combined_geolocation_runtime(repository, request)
    if request.has_coordinates:
        return resolve_coordinate_geolocation_runtime(repository, request)
    return resolve_place_geolocation_runtime(repository, request)


def list_geolocation_public_runtime(
    repository: GeolocationIndexRepository,
    request: GeolocationListRequest,
) -> GeolocationListResult:
    entries = listgeo_sorted_entries(repository.entries, request)
    translated = repository.translated_entries(entries, request.language_code)
    include_alternate_names = (
        request.include_alternate_names and repository.supports_packaged_alternate_names
    )
    rows = tuple(
        row
        for entry in translated
        if listgeo_entry_matches(entry, request)
        if (row := listgeo_row_from_entry(entry, include_alternate_names)) is not None
    )
    return GeolocationListResult(
        status="listed" if rows else "empty",
        rows=rows,
        alternate_names_column_available=include_alternate_names,
        source_reference_ids=(
            GEOLOCATION_LISTGEO_SOURCE_ID,
            GEOLOCATION_ENTRY_SOURCE_ID,
            GEOLOCATION_SORT_SOURCE_ID,
        ),
    )


def listgeo_sorted_entries(
    entries: tuple[GeolocationEntry, ...],
    request: GeolocationListRequest,
) -> tuple[GeolocationEntry, ...]:
    sort_mode = "city" if request.sort_by_city else request.sort_mode
    if sort_mode == "city":
        return tuple(sorted(entries, key=lambda entry: entry.city))
    if sort_mode == "country":
        return tuple(sorted(entries, key=lambda entry: (entry.country, entry.city)))
    return entries


def listgeo_entry_matches(
    entry: GeolocationEntry,
    request: GeolocationListRequest,
) -> bool:
    if request.min_population is not None and entry.population < request.min_population:
        return False
    feature_code = entry.feature_code.casefold()
    feature_filter = frozenset(code.casefold() for code in request.feature_codes)
    excluded_feature_filter = frozenset(code.casefold() for code in request.excluded_feature_codes)
    if feature_filter and feature_code not in feature_filter:
        return False
    return feature_code not in excluded_feature_filter


def listgeo_row_from_entry(
    entry: GeolocationEntry,
    include_alternate_names: bool,
) -> GeolocationListRow:
    alternate_names: str | None = None
    if include_alternate_names and entry.alternate_names:
        alternate_names = ",".join(entry.alternate_names)
    return GeolocationListRow(
        city=entry.city,
        region=entry.region,
        subregion=entry.subregion,
        country_code=entry.country_code,
        country=entry.country,
        timezone=entry.timezone,
        feature_code=entry.feature_code,
        population=entry.population,
        latitude=entry.latitude,
        longitude=entry.longitude,
        alternate_names=alternate_names,
    )


def source_listgeo_population(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def resolve_coordinate_geolocation_runtime(
    repository: GeolocationIndexRepository,
    request: GeolocationRuntimeRequest,
) -> GeolocationRuntimeResult:
    if request.latitude is None or request.longitude is None:
        return geolocation_runtime_result(
            "missing_input",
            (),
            "Both latitude and longitude are required for coordinate geolocation.",
        )
    matches = repository.nearest(
        request.latitude,
        request.longitude,
        limit=request.limit,
        max_distance_km=request.max_distance_km,
        min_population=request.min_population,
        feature_codes=request.feature_codes,
        excluded_feature_codes=request.excluded_feature_codes,
        regex_filters=request.regex_filters,
    )
    if not matches:
        return geolocation_runtime_result(
            "not_found",
            (),
            "No suitable location in Geolocation database.",
        )
    translated = repository.translated_nearest_matches(matches, request.language_code)
    return geolocation_runtime_result(
        "resolved",
        tuple(runtime_tags_from_nearest_match(match) for match in translated),
        candidate_count=len(translated),
    )


def resolve_combined_geolocation_runtime(
    repository: GeolocationIndexRepository,
    request: GeolocationRuntimeRequest,
) -> GeolocationRuntimeResult:
    if request.latitude is None or request.longitude is None:
        return geolocation_runtime_result(
            "missing_input",
            (),
            "Both latitude and longitude are required for combined geolocation.",
        )
    place_matches = repository.search(
        city=request.city,
        country_code=request.country_code,
        region=request.region,
        subregion=request.subregion,
        exact_place_names=request.exact_place_names,
        min_population=request.min_population,
        feature_codes=request.feature_codes,
        excluded_feature_codes=request.excluded_feature_codes,
        regex_filters=request.regex_filters,
        use_alternate_names=request.use_alternate_names,
    )
    if not place_matches:
        return geolocation_runtime_result(
            "not_found",
            (),
            "No such city in Geolocation database.",
        )
    nearest_matches = nearest_geolocation_entries(
        place_matches,
        request.latitude,
        request.longitude,
        limit=request.limit,
        max_distance_km=request.max_distance_km,
    )
    if not nearest_matches:
        return geolocation_runtime_result(
            "not_found",
            (),
            "No suitable matching city in Geolocation database.",
            candidate_count=len(place_matches),
        )
    translated = repository.translated_nearest_matches(nearest_matches, request.language_code)
    return geolocation_runtime_result(
        "resolved",
        tuple(runtime_tags_from_nearest_match(match) for match in translated),
        candidate_count=len(place_matches),
    )


def resolve_place_geolocation_runtime(
    repository: GeolocationIndexRepository,
    request: GeolocationRuntimeRequest,
) -> GeolocationRuntimeResult:
    matches = repository.search(
        city=request.city,
        country_code=request.country_code,
        region=request.region,
        subregion=request.subregion,
        exact_place_names=request.exact_place_names,
        limit=None if request.allow_multiple_places else 2,
        min_population=request.min_population,
        feature_codes=request.feature_codes,
        excluded_feature_codes=request.excluded_feature_codes,
        regex_filters=request.regex_filters,
        use_alternate_names=request.use_alternate_names,
    )
    if not matches:
        return geolocation_runtime_result(
            "not_found",
            (),
            "No such city in Geolocation database.",
        )
    if len(matches) > 1 and not request.allow_multiple_places:
        return geolocation_runtime_result(
            "ambiguous_place",
            (),
            "Multiple Geolocation cities are possible.",
            candidate_count=len(matches),
        )
    if len(matches) == 1 and request.limit > 1:
        nearby_matches = repository.nearby_for_entry(
            matches[0],
            limit=request.limit,
            max_distance_km=request.max_distance_km,
            min_population=request.min_population,
            feature_codes=request.feature_codes,
            excluded_feature_codes=request.excluded_feature_codes,
        )
        if not nearby_matches:
            return geolocation_runtime_result(
                "not_found",
                (),
                "No suitable nearby location in Geolocation database.",
                candidate_count=len(matches),
            )
        translated_nearby = repository.translated_nearest_matches(
            nearby_matches,
            request.language_code,
        )
        return geolocation_runtime_result(
            "resolved",
            tuple(runtime_tags_from_nearest_match(match) for match in translated_nearby),
            candidate_count=len(translated_nearby),
        )
    limited = matches[: request.limit] if request.limit > 0 else ()
    translated = repository.translated_entries(limited, request.language_code)
    return geolocation_runtime_result(
        "resolved",
        tuple(runtime_tags_from_entry(entry) for entry in translated),
        candidate_count=len(matches),
    )


def nearest_geolocation_entries(
    entries: tuple[GeolocationEntry, ...],
    latitude: float,
    longitude: float,
    limit: int,
    max_distance_km: float | None = None,
) -> tuple[GeolocationNearestMatch, ...]:
    if limit < 1:
        return ()
    matches: list[GeolocationNearestMatch] = []
    for entry in entries:
        distance, bearing = source_distance_and_bearing(
            latitude,
            longitude,
            entry.latitude_degrees,
            entry.longitude_degrees,
        )
        if max_distance_km is not None and distance > max_distance_km:
            continue
        matches.append(
            GeolocationNearestMatch(
                entry=entry,
                distance_km=f"{distance:.2f}",
                bearing_degrees=bearing,
            )
        )
    return tuple(
        sorted(matches, key=lambda match: (float(match.distance_km), -match.entry.population))[
            :limit
        ]
    )


def _source_query_limit(value: str) -> int | None:
    try:
        parsed = int(value.split("=", 1)[1])
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _source_query_regex_filter(value: str) -> GeolocationRegexFilter | None:
    negate = False
    text = value
    if text.startswith("-"):
        negate = True
        text = text[1:]
    prefix = ""
    if len(text) > 2 and text[2] == "/":
        prefix = text[:2].casefold()
        text = text[2:]
    if not text.startswith("/"):
        return None
    last_slash = text.rfind("/")
    if last_slash <= 0:
        return None
    pattern = text[1:last_slash]
    flags = text[last_slash + 1 :]
    field = _source_query_regex_field(prefix)
    if field is None:
        return None
    return GeolocationRegexFilter(
        field=field,
        pattern=pattern,
        ignore_case="i" in flags.casefold(),
        negate=negate,
    )


def _source_query_regex_field(value: str) -> GeolocationFilterField | None:
    if value == "ci":
        return "city"
    if value == "cc":
        return "country_code"
    if value == "co":
        return "country"
    if value == "re":
        return "region"
    if value == "sr":
        return "subregion"
    if value == "":
        return "any"
    return None


def _source_query_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _source_query_lat_lon_phrase(value: str) -> tuple[float, float] | None:
    match = re.match(
        r"^([-+]?\d+(?:\.\d+)?)\s*(([NS])[A-Z]*)?\s+"
        r"([-+]?\d+(?:\.\d+)?)\s*(([EW])[A-Z]*)?",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    latitude = _source_query_float(match.group(1))
    longitude = _source_query_float(match.group(4))
    if latitude is None or longitude is None:
        return None
    latitude_direction = match.group(3)
    longitude_direction = match.group(6)
    if latitude_direction is not None and latitude_direction.casefold() == "s":
        latitude = -abs(latitude)
    if longitude_direction is not None and longitude_direction.casefold() == "w":
        longitude = -abs(longitude)
    return latitude, longitude


def _looks_like_country_code(value: str) -> bool:
    return len(value) == 2 and value.isalpha()


def runtime_tags_from_nearest_match(match: GeolocationNearestMatch) -> GeolocationRuntimeTags:
    return runtime_tags_from_entry(
        match.entry,
        distance_km=match.distance_km,
        bearing_degrees=match.bearing_degrees,
    )


def runtime_tags_from_entry(
    entry: GeolocationEntry,
    distance_km: str | None = None,
    bearing_degrees: int | None = None,
) -> GeolocationRuntimeTags:
    return GeolocationRuntimeTags(
        city=entry.city,
        region=entry.region or None,
        subregion=entry.subregion or None,
        country_code=entry.country_code,
        country=entry.country or None,
        timezone=entry.timezone or None,
        feature_code=entry.feature_code,
        feature_type=entry.feature_type,
        population=entry.population,
        position=f"{entry.latitude}, {entry.longitude}",
        distance_km=distance_km,
        bearing_degrees=bearing_degrees,
    )


def geolocation_runtime_result(
    status: GeolocationRuntimeStatus,
    tags: tuple[GeolocationRuntimeTags, ...],
    reason: str = "",
    candidate_count: int = 0,
) -> GeolocationRuntimeResult:
    return GeolocationRuntimeResult(
        status=status,
        tags=tags,
        reason=reason,
        candidate_count=candidate_count,
        diagnostics=geolocation_runtime_diagnostics(status, reason, candidate_count, tags),
        source_reference_ids=(
            GEOLOCATION_DONE_EXTRACT_SOURCE_ID,
            GEOLOCATION_LOOKUP_SOURCE_ID,
            GEOLOCATION_ENTRY_SOURCE_ID,
        ),
    )


def geolocation_runtime_diagnostics(
    status: GeolocationRuntimeStatus,
    reason: str,
    candidate_count: int,
    tags: tuple[GeolocationRuntimeTags, ...],
) -> tuple[GeolocationRuntimeDiagnostic, ...]:
    if status == "resolved" and len(tags) > 1:
        count = candidate_count or len(tags)
        return (
            GeolocationRuntimeDiagnostic(
                code="search_matched_multiple_cities",
                message=f"Search matched {count} cities",
                candidate_count=count,
            ),
        )
    if status == "resolved":
        return (
            GeolocationRuntimeDiagnostic(
                code="resolved",
                message="Geolocation search resolved.",
                candidate_count=candidate_count or len(tags),
            ),
        )
    if status == "ambiguous_place":
        return (
            GeolocationRuntimeDiagnostic(
                code="multiple_geolocation_cities_possible",
                message=reason or "Multiple Geolocation cities are possible.",
                candidate_count=candidate_count,
            ),
        )
    if status == "missing_input":
        return (
            GeolocationRuntimeDiagnostic(
                code="missing_geolocation_input",
                message=reason or "Insufficient information to determine geolocation.",
                candidate_count=candidate_count,
            ),
        )
    code: GeolocationRuntimeDiagnosticCode = (
        "no_such_city" if reason.casefold().startswith("no such city") else "no_suitable_location"
    )
    return (
        GeolocationRuntimeDiagnostic(
            code=code,
            message=reason or "No suitable location in Geolocation database.",
            candidate_count=candidate_count,
        ),
    )
