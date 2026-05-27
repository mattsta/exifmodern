"""Typed repository for migrated ExifTool Geolocation database metadata."""

from __future__ import annotations

import pickle
import re
from dataclasses import dataclass
from math import atan2, cos, pi, radians, sin, sqrt
from pathlib import Path
from typing import Literal

from exifmodern.json_types import (
    JsonObject,
    JsonValue,
    json_array_value,
    json_bool_value,
    json_int_value,
    json_object_items,
    json_scalar_to_string,
    json_string_array_value,
    json_string_value,
    load_json_object,
)
from exifmodern.package_resources import (
    generated_index_geolocation_repository_pickle_path,
    generated_index_shard_path,
)

type GeolocationNameKey = tuple[str, str]
type GeolocationPlaceKey = tuple[str, str, str, str]
type GeolocationTranslationTable = dict[str, str]
type GeolocationFilterField = Literal[
    "city",
    "country_code",
    "country",
    "region",
    "subregion",
    "any",
]

EARTH_RADIUS_KM = 6371.0
GEOLOCATION_COORDINATE_SCALE = 0x100000


@dataclass(frozen=True)
class GeolocationEntry:
    entry_index: int
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
    feature_type: str | None
    alternate_names: tuple[str, ...]

    @property
    def latitude_degrees(self) -> float:
        return float(self.latitude)

    @property
    def longitude_degrees(self) -> float:
        return float(self.longitude)


@dataclass(frozen=True)
class GeolocationUserDefinedEntry:
    city: str
    region: str
    subregion: str
    country_code: str
    country: str
    timezone: str
    feature_code: str
    population: float
    latitude: float
    longitude: float
    alternate_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class GeolocationNearestMatch:
    entry: GeolocationEntry
    distance_km: str
    bearing_degrees: int


@dataclass(frozen=True)
class GeolocationRegexFilter:
    field: GeolocationFilterField
    pattern: str
    ignore_case: bool = True
    negate: bool = False


@dataclass(frozen=True)
class GeolocationIndexRepository:
    version: str
    declared_city_count: int
    city_count: int
    country_count: int
    region_count: int
    subregion_count: int
    timezone_count: int
    feature_code_count: int
    alternate_names_source_present: bool
    language_translation_source_present: bool
    alternate_names_count_matches_city_count: bool
    alternate_name_entry_count: int
    alternate_name_count: int
    language_code_count: int
    language_translation_count: int
    language_translation_error_count: int
    language_translation_errors: tuple[str, ...]
    sample_cities: tuple[str, ...]
    entries: tuple[GeolocationEntry, ...]
    entries_by_city: dict[GeolocationNameKey, tuple[GeolocationEntry, ...]]
    entries_by_alternate_city: dict[GeolocationNameKey, tuple[GeolocationEntry, ...]]
    entries_by_place: dict[GeolocationPlaceKey, tuple[GeolocationEntry, ...]]
    language_translations: dict[str, GeolocationTranslationTable]

    @property
    def city_count_matches_header(self) -> bool:
        return self.declared_city_count == self.city_count

    @property
    def supports_packaged_alternate_names(self) -> bool:
        return (
            self.alternate_names_source_present
            and self.alternate_names_count_matches_city_count
            and self.alternate_name_count > 0
        )

    @property
    def supports_packaged_language_translations(self) -> bool:
        return self.language_translation_source_present and self.language_translation_count > 0

    def find_city(
        self,
        city: str,
        use_alternate_names: bool = False,
    ) -> tuple[GeolocationEntry, ...]:
        return self.city_candidates(city, use_alternate_names)

    def find_location(
        self,
        city: str,
        country_code: str = "",
        region: str = "",
        subregion: str = "",
        use_alternate_names: bool = True,
    ) -> tuple[GeolocationEntry, ...]:
        key = normalized_place_key(city, country_code, region, subregion)
        if country_code and region and subregion and key in self.entries_by_place:
            return self.entries_by_place[key]
        return self.search(
            city=city,
            country_code=country_code,
            region=region,
            subregion=subregion,
            use_alternate_names=use_alternate_names,
        )

    def search(
        self,
        city: str = "",
        country_code: str = "",
        region: str = "",
        subregion: str = "",
        exact_place_names: tuple[str, ...] = (),
        limit: int | None = None,
        min_population: float | None = None,
        feature_codes: tuple[str, ...] = (),
        excluded_feature_codes: tuple[str, ...] = (),
        regex_filters: tuple[GeolocationRegexFilter, ...] = (),
        use_alternate_names: bool = True,
    ) -> tuple[GeolocationEntry, ...]:
        entries = self.city_candidates(city, use_alternate_names) if city else self.entries
        feature_filter = frozenset(code.casefold() for code in feature_codes)
        excluded_feature_filter = frozenset(code.casefold() for code in excluded_feature_codes)
        matches = tuple(
            entry
            for entry in entries
            if location_filter_matches(entry, country_code, region, subregion)
            and exact_place_names_match(entry, exact_place_names)
            and population_matches(entry, min_population)
            and feature_matches(entry, feature_filter, excluded_feature_filter)
            and regex_filters_match(entry, regex_filters)
        )
        sorted_matches = tuple(
            sorted(matches, key=lambda entry: (-entry.population, entry.city.casefold()))
        )
        if limit is not None and limit > 0:
            return sorted_matches[:limit]
        return sorted_matches

    def with_user_defined_entries(
        self,
        user_entries: tuple[GeolocationUserDefinedEntry, ...],
    ) -> GeolocationIndexRepository:
        if not user_entries:
            return self
        appended = list(self.entries)
        for user_entry in user_entries:
            appended.append(
                user_defined_entry_to_geolocation_entry(self, user_entry, len(appended))
            )
        entries = tuple(appended)
        user_alternate_name_count = sum(len(entry.alternate_names) for entry in user_entries)
        return GeolocationIndexRepository(
            version=self.version,
            declared_city_count=self.declared_city_count + len(user_entries),
            city_count=self.city_count + len(user_entries),
            country_count=self.country_count,
            region_count=self.region_count,
            subregion_count=self.subregion_count,
            timezone_count=self.timezone_count,
            feature_code_count=self.feature_code_count,
            alternate_names_source_present=(
                self.alternate_names_source_present or user_alternate_name_count > 0
            ),
            language_translation_source_present=self.language_translation_source_present,
            alternate_names_count_matches_city_count=(
                self.alternate_names_count_matches_city_count or user_alternate_name_count > 0
            ),
            alternate_name_entry_count=self.alternate_name_entry_count
            + sum(1 for entry in user_entries if entry.alternate_names),
            alternate_name_count=self.alternate_name_count + user_alternate_name_count,
            language_code_count=self.language_code_count,
            language_translation_count=self.language_translation_count,
            language_translation_error_count=self.language_translation_error_count,
            language_translation_errors=self.language_translation_errors,
            sample_cities=self.sample_cities,
            entries=entries,
            entries_by_city=entries_by_city(entries),
            entries_by_alternate_city=entries_by_alternate_city(entries),
            entries_by_place=entries_by_place(entries),
            language_translations=self.language_translations,
        )

    def city_candidates(
        self,
        city: str,
        use_alternate_names: bool,
    ) -> tuple[GeolocationEntry, ...]:
        direct = self.entries_by_city.get(normalized_name_key(city), ())
        if not use_alternate_names or not self.supports_packaged_alternate_names:
            return direct
        alternate = self.entries_by_alternate_city.get(normalized_name_key(city), ())
        if not direct:
            return alternate
        if not alternate:
            return direct
        by_index = {entry.entry_index: entry for entry in direct}
        for entry in alternate:
            by_index.setdefault(entry.entry_index, entry)
        return tuple(sorted(by_index.values(), key=lambda entry: entry.entry_index))

    def nearest(
        self,
        latitude: float,
        longitude: float,
        limit: int = 1,
        max_distance_km: float | None = None,
        min_population: float | None = None,
        feature_codes: tuple[str, ...] = (),
        excluded_feature_codes: tuple[str, ...] = (),
        regex_filters: tuple[GeolocationRegexFilter, ...] = (),
    ) -> tuple[GeolocationNearestMatch, ...]:
        if limit < 1:
            return ()
        feature_filter = frozenset(code.casefold() for code in feature_codes)
        excluded_feature_filter = frozenset(code.casefold() for code in excluded_feature_codes)
        matches: list[GeolocationNearestMatch] = []
        for entry in self.entries:
            if not population_matches(entry, min_population):
                continue
            if not feature_matches(entry, feature_filter, excluded_feature_filter):
                continue
            if not regex_filters_match(entry, regex_filters):
                continue
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
            sorted(
                matches,
                key=lambda match: (float(match.distance_km), -match.entry.population),
            )[:limit]
        )

    def nearby_for_entry(
        self,
        entry: GeolocationEntry,
        limit: int,
        max_distance_km: float | None = None,
        min_population: float | None = None,
        feature_codes: tuple[str, ...] = (),
        excluded_feature_codes: tuple[str, ...] = (),
    ) -> tuple[GeolocationNearestMatch, ...]:
        return self.nearest(
            entry.latitude_degrees,
            entry.longitude_degrees,
            limit=limit,
            max_distance_km=max_distance_km,
            min_population=min_population,
            feature_codes=feature_codes,
            excluded_feature_codes=excluded_feature_codes,
        )

    def translated_entry(
        self,
        entry: GeolocationEntry,
        language_code: str,
    ) -> GeolocationEntry:
        if not language_code or language_code == "en":
            return entry
        table = self.language_translations.get(language_code)
        if table is None:
            return entry
        city = translated_city(entry, table)
        subregion = translated_subregion(entry, table)
        region = translated_region(entry, table)
        country = translated_country(entry, table)
        feature_type = table.get(entry.feature_code, entry.feature_type or "")
        return GeolocationEntry(
            entry_index=entry.entry_index,
            city=city,
            region=region,
            subregion=subregion,
            country_code=entry.country_code,
            country=country,
            timezone=entry.timezone,
            feature_code=entry.feature_code,
            population=entry.population,
            latitude=entry.latitude,
            longitude=entry.longitude,
            feature_type=feature_type or None,
            alternate_names=entry.alternate_names,
        )

    def translated_entries(
        self,
        entries: tuple[GeolocationEntry, ...],
        language_code: str,
    ) -> tuple[GeolocationEntry, ...]:
        return tuple(self.translated_entry(entry, language_code) for entry in entries)

    def translated_nearest_matches(
        self,
        matches: tuple[GeolocationNearestMatch, ...],
        language_code: str,
    ) -> tuple[GeolocationNearestMatch, ...]:
        return tuple(
            GeolocationNearestMatch(
                entry=self.translated_entry(match.entry, language_code),
                distance_km=match.distance_km,
                bearing_degrees=match.bearing_degrees,
            )
            for match in matches
        )


def load_geolocation_index_repository(package_path: Path) -> GeolocationIndexRepository:
    shard_path = (
        generated_index_shard_path("geolocation")
        if _is_generated_index_manifest_path(package_path)
        else None
    )
    if shard_path is not None:
        repository_pickle_path = generated_index_geolocation_repository_pickle_path()
        if repository_pickle_path is not None:
            return load_geolocation_index_repository_pickle(repository_pickle_path)
        return geolocation_index_repository_from_json(load_json_object(shard_path))
    package = load_json_object(package_path)
    if json_string_value(package, "format") == "geolocation_database_v1":
        return geolocation_index_repository_from_json(package)
    for index_value in json_array_value(package, "indexes"):
        if not isinstance(index_value, dict):
            continue
        if json_string_value(index_value, "kind") != "geolocation":
            continue
        data = json_object_items(index_value, "data")
        return geolocation_index_repository_from_json(data)
    return empty_geolocation_index_repository()


def load_geolocation_index_repository_pickle(path: Path) -> GeolocationIndexRepository:
    payload = pickle.loads(path.read_bytes())
    if not isinstance(payload, GeolocationIndexRepository):
        raise ValueError(f"Expected geolocation repository pickle: {path}")
    return payload


def _is_generated_index_manifest_path(path: Path) -> bool:
    return path.name == "manifest.json" and path.parent.name == "generated-index"


def geolocation_index_repository_from_json(value: JsonObject) -> GeolocationIndexRepository:
    entries = tuple(
        entry
        for item in json_array_value(value, "entries")
        if (entry := geolocation_entry_from_json(item)) is not None
    )
    return GeolocationIndexRepository(
        version=json_string_value(value, "version") or "",
        declared_city_count=json_int_value(value, "declared_city_count") or 0,
        city_count=json_int_value(value, "city_count") or 0,
        country_count=json_int_value(value, "country_count") or 0,
        region_count=json_int_value(value, "region_count") or 0,
        subregion_count=json_int_value(value, "subregion_count") or 0,
        timezone_count=json_int_value(value, "timezone_count") or 0,
        feature_code_count=json_int_value(value, "feature_code_count") or 0,
        alternate_names_source_present=(
            json_bool_value(value, "alternate_names_source_present") or False
        ),
        language_translation_source_present=(
            json_bool_value(value, "language_translation_source_present") or False
        ),
        alternate_names_count_matches_city_count=(
            json_bool_value(value, "alternate_names_count_matches_city_count") or False
        ),
        alternate_name_entry_count=json_int_value(value, "alternate_name_entry_count") or 0,
        alternate_name_count=json_int_value(value, "alternate_name_count") or 0,
        language_code_count=json_int_value(value, "language_code_count") or 0,
        language_translation_count=json_int_value(value, "language_translation_count") or 0,
        language_translation_error_count=(
            json_int_value(value, "language_translation_error_count") or 0
        ),
        language_translation_errors=tuple(
            json_string_array_value(value, "language_translation_errors")
        ),
        sample_cities=tuple(json_string_array_value(value, "sample_cities")),
        entries=entries,
        entries_by_city=entries_by_city(entries),
        entries_by_alternate_city=entries_by_alternate_city(entries),
        entries_by_place=entries_by_place(entries),
        language_translations=geolocation_language_translations_from_json(value),
    )


def geolocation_entry_from_json(value: JsonValue) -> GeolocationEntry | None:
    if not isinstance(value, dict):
        return None
    city = json_string_value(value, "city")
    region = json_string_value(value, "region")
    subregion = json_string_value(value, "subregion")
    country_code = json_string_value(value, "country_code")
    country = json_string_value(value, "country")
    timezone = json_string_value(value, "timezone")
    feature_code = json_string_value(value, "feature_code")
    population = json_float_from_value(value.get("population"))
    latitude = json_string_value(value, "latitude")
    longitude = json_string_value(value, "longitude")
    entry_index = json_int_value(value, "entry_index")
    if (
        entry_index is None
        or city is None
        or region is None
        or subregion is None
        or country_code is None
        or country is None
        or timezone is None
        or feature_code is None
        or population is None
        or latitude is None
        or longitude is None
    ):
        return None
    return GeolocationEntry(
        entry_index=entry_index,
        city=city,
        region=region,
        subregion=subregion,
        country_code=country_code,
        country=country,
        timezone=timezone,
        feature_code=feature_code,
        population=population,
        latitude=latitude,
        longitude=longitude,
        feature_type=json_string_value(value, "feature_type"),
        alternate_names=tuple(json_string_array_value(value, "alternate_names")),
    )


def empty_geolocation_index_repository() -> GeolocationIndexRepository:
    entries: tuple[GeolocationEntry, ...] = ()
    return GeolocationIndexRepository(
        version="",
        declared_city_count=0,
        city_count=0,
        country_count=0,
        region_count=0,
        subregion_count=0,
        timezone_count=0,
        feature_code_count=0,
        alternate_names_source_present=False,
        language_translation_source_present=False,
        alternate_names_count_matches_city_count=False,
        alternate_name_entry_count=0,
        alternate_name_count=0,
        language_code_count=0,
        language_translation_count=0,
        language_translation_error_count=0,
        language_translation_errors=(),
        sample_cities=(),
        entries=entries,
        entries_by_city={},
        entries_by_alternate_city={},
        entries_by_place={},
        language_translations={},
    )


def user_defined_entry_to_geolocation_entry(
    repository: GeolocationIndexRepository,
    entry: GeolocationUserDefinedEntry,
    entry_index: int,
) -> GeolocationEntry:
    feature_code, feature_type = user_defined_feature(entry.feature_code)
    return GeolocationEntry(
        entry_index=entry_index,
        city=entry.city,
        region=canonical_region(repository, entry.region),
        subregion=canonical_subregion(repository, entry.subregion),
        country_code=entry.country_code.upper(),
        country=entry.country or canonical_country(repository, entry.country_code),
        timezone=canonical_timezone(repository, entry.timezone),
        feature_code=feature_code,
        population=user_defined_population(entry.population),
        latitude=user_defined_latitude(entry.latitude),
        longitude=user_defined_longitude(entry.longitude),
        feature_type=feature_type or feature_type_for_code(repository, feature_code),
        alternate_names=entry.alternate_names,
    )


def user_defined_feature(value: str) -> tuple[str, str | None]:
    feature_code, separator, feature_type = value.partition(" ")
    if not feature_code:
        return "Other", None
    return feature_code.upper(), feature_type if separator else None


def feature_type_for_code(repository: GeolocationIndexRepository, feature_code: str) -> str | None:
    if feature_code == "Other":
        return None
    normalized = feature_code.casefold()
    for entry in repository.entries:
        if entry.feature_code.casefold() == normalized and entry.feature_type:
            return entry.feature_type
    return None


def canonical_country(repository: GeolocationIndexRepository, country_code: str) -> str:
    normalized = country_code.casefold()
    for entry in repository.entries:
        if entry.country_code.casefold() == normalized:
            return entry.country
    return ""


def canonical_region(repository: GeolocationIndexRepository, region: str) -> str:
    normalized = region.casefold()
    for entry in repository.entries:
        if entry.region.casefold() == normalized:
            return entry.region
    return region


def canonical_subregion(repository: GeolocationIndexRepository, subregion: str) -> str:
    normalized = subregion.casefold()
    for entry in repository.entries:
        if entry.subregion.casefold() == normalized:
            return entry.subregion
    return subregion


def canonical_timezone(repository: GeolocationIndexRepository, timezone: str) -> str:
    normalized = timezone.casefold()
    for entry in repository.entries:
        if entry.timezone.casefold() == normalized:
            return entry.timezone
    return timezone


def user_defined_population(value: float) -> float:
    return float(f"{value:.1e}")


def user_defined_latitude(value: float) -> str:
    packed = int((value + 90) / 180 * 0x100000 + 0.5) & 0xFFFFF
    return f"{packed * 180 / 0x100000 - 90:.4f}"


def user_defined_longitude(value: float) -> str:
    packed = int((value + 180) / 360 * 0x100000 + 0.5) & 0xFFFFF
    return f"{packed * 360 / 0x100000 - 180:.4f}"


def entries_by_city(
    entries: tuple[GeolocationEntry, ...],
) -> dict[GeolocationNameKey, tuple[GeolocationEntry, ...]]:
    grouped: dict[GeolocationNameKey, list[GeolocationEntry]] = {}
    for entry in entries:
        grouped.setdefault(normalized_name_key(entry.city), []).append(entry)
    return {key: tuple(values) for key, values in grouped.items()}


def entries_by_alternate_city(
    entries: tuple[GeolocationEntry, ...],
) -> dict[GeolocationNameKey, tuple[GeolocationEntry, ...]]:
    grouped: dict[GeolocationNameKey, list[GeolocationEntry]] = {}
    for entry in entries:
        for name in entry.alternate_names:
            grouped.setdefault(normalized_name_key(name), []).append(entry)
    return {key: tuple(values) for key, values in grouped.items()}


def entries_by_place(
    entries: tuple[GeolocationEntry, ...],
) -> dict[GeolocationPlaceKey, tuple[GeolocationEntry, ...]]:
    grouped: dict[GeolocationPlaceKey, list[GeolocationEntry]] = {}
    for entry in entries:
        grouped.setdefault(
            normalized_place_key(
                entry.city,
                entry.country_code,
                entry.region,
                entry.subregion,
            ),
            [],
        ).append(entry)
    return {key: tuple(values) for key, values in grouped.items()}


def normalized_name_key(value: str) -> GeolocationNameKey:
    return (value.casefold(), normalize_spaces(value).casefold())


def normalized_place_key(
    city: str,
    country_code: str,
    region: str,
    subregion: str,
) -> GeolocationPlaceKey:
    return (
        normalize_spaces(city).casefold(),
        normalize_spaces(country_code).casefold(),
        normalize_spaces(region).casefold(),
        normalize_spaces(subregion).casefold(),
    )


def normalize_spaces(value: str) -> str:
    return " ".join(value.split())


def location_filter_matches(
    entry: GeolocationEntry,
    country_code: str,
    region: str,
    subregion: str,
) -> bool:
    return (
        optional_name_matches(entry.country_code, country_code)
        and optional_name_matches(entry.region, region)
        and optional_name_matches(entry.subregion, subregion)
    )


def exact_place_names_match(entry: GeolocationEntry, requested_values: tuple[str, ...]) -> bool:
    if not requested_values:
        return True
    normalized_entry_values = frozenset(
        normalize_spaces(value).casefold()
        for value in (
            entry.country_code,
            entry.country,
            entry.region,
            entry.subregion,
        )
        if value
    )
    return all(
        normalize_spaces(value).casefold() in normalized_entry_values for value in requested_values
    )


def population_matches(entry: GeolocationEntry, min_population: float | None) -> bool:
    return min_population is None or entry.population >= min_population


def feature_matches(
    entry: GeolocationEntry,
    feature_filter: frozenset[str],
    excluded_feature_filter: frozenset[str],
) -> bool:
    feature_code = entry.feature_code.casefold()
    if feature_filter and feature_code not in feature_filter:
        return False
    return feature_code not in excluded_feature_filter


def optional_name_matches(entry_value: str, requested_value: str) -> bool:
    if not requested_value:
        return True
    return normalize_spaces(entry_value).casefold() == normalize_spaces(requested_value).casefold()


def regex_filters_match(
    entry: GeolocationEntry,
    filters: tuple[GeolocationRegexFilter, ...],
) -> bool:
    return all(regex_filter_matches(entry, item) for item in filters)


def regex_filter_matches(entry: GeolocationEntry, item: GeolocationRegexFilter) -> bool:
    flags = re.IGNORECASE if item.ignore_case else 0
    matched = (
        re.search(item.pattern, geolocation_filter_value(entry, item.field), flags) is not None
    )
    return not matched if item.negate else matched


def geolocation_filter_value(entry: GeolocationEntry, field: GeolocationFilterField) -> str:
    if field == "city":
        return entry.city
    if field == "country_code":
        return entry.country_code
    if field == "country":
        return entry.country
    if field == "region":
        return entry.region
    if field == "subregion":
        return entry.subregion
    return "\n".join(
        (
            entry.city,
            entry.country_code,
            entry.country,
            entry.region,
            entry.subregion,
        )
    )


def geolocation_language_translations_from_json(
    value: JsonObject,
) -> dict[str, GeolocationTranslationTable]:
    tables: dict[str, GeolocationTranslationTable] = {}
    for item in json_array_value(value, "language_translations"):
        if not isinstance(item, dict):
            continue
        language_code = json_string_value(item, "name")
        translations = item.get("translations")
        if language_code is None or not isinstance(translations, dict):
            continue
        table: GeolocationTranslationTable = {}
        for key, translated_value in translations.items():
            if not isinstance(key, str):
                continue
            text = json_scalar_to_string(translated_value)
            if text is not None:
                table[key] = text
        tables[language_code] = table
    return tables


def translated_city(entry: GeolocationEntry, table: GeolocationTranslationTable) -> str:
    return (
        table.get(f"{entry.country_code}{entry.region},{entry.subregion},{entry.city}")
        or table.get(f"{entry.country_code}{entry.region},{entry.city}")
        or table.get(f"{entry.country_code},{entry.city}")
        or table.get(f",{entry.city}")
        or table.get(entry.city)
        or entry.city
    )


def translated_subregion(entry: GeolocationEntry, table: GeolocationTranslationTable) -> str:
    return (
        table.get(f"{entry.country_code}{entry.region},{entry.subregion},")
        or table.get(entry.subregion)
        or entry.subregion
    )


def translated_region(entry: GeolocationEntry, table: GeolocationTranslationTable) -> str:
    return (
        table.get(f"{entry.country_code}{entry.region},") or table.get(entry.region) or entry.region
    )


def translated_country(entry: GeolocationEntry, table: GeolocationTranslationTable) -> str:
    return table.get(f"{entry.country_code},") or table.get(entry.country) or entry.country


def json_float_from_value(value: JsonValue | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = json_scalar_to_string(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def haversine_distance_km(
    latitude: float,
    longitude: float,
    entry_latitude: float,
    entry_longitude: float,
) -> float:
    lat0 = radians(latitude)
    lon0 = radians(longitude)
    lat1 = radians(entry_latitude)
    lon1 = radians(entry_longitude)
    sin_lat = sin((lat1 - lat0) / 2)
    sin_lon = sin((lon1 - lon0) / 2)
    a_value = sin_lat * sin_lat + cos(lat0) * cos(lat1) * sin_lon * sin_lon
    return 2 * EARTH_RADIUS_KM * atan2(sqrt(a_value), sqrt(1 - a_value))


def bearing_degrees(
    latitude: float,
    longitude: float,
    entry_latitude: float,
    entry_longitude: float,
) -> int:
    lat0 = radians(latitude)
    lon0 = radians(longitude)
    lat1 = radians(entry_latitude)
    lon1 = radians(entry_longitude)
    y_value = sin(lon1 - lon0) * cos(lat1)
    x_value = cos(lat0) * sin(lat1) - sin(lat0) * cos(lat1) * cos(lon1 - lon0)
    return int(atan2(y_value, x_value) * 180 / 3.141592653589793 + 360.5) % 360


def source_distance_and_bearing(
    latitude: float,
    longitude: float,
    entry_latitude: float,
    entry_longitude: float,
) -> tuple[float, int]:
    lat0_units = source_latitude_units(latitude, adjust_zero=True)
    lon0_units = source_longitude_units(longitude)
    lat1_units = source_latitude_units(entry_latitude)
    lon1_units = source_longitude_units(entry_longitude)
    p0 = lat0_units * pi / GEOLOCATION_COORDINATE_SCALE - pi / 2
    t0 = lon0_units * pi / (GEOLOCATION_COORDINATE_SCALE // 2) - pi
    p1 = lat1_units * pi / GEOLOCATION_COORDINATE_SCALE - pi / 2
    t1 = lon1_units * pi / (GEOLOCATION_COORDINATE_SCALE // 2) - pi
    cp0 = cos(p0)
    sp = sin((p1 - p0) / 2)
    st = sin((t1 - t0) / 2)
    a_value = sp * sp + cp0 * cos(p1) * st * st
    unit_distance = atan2(sqrt(a_value), sqrt(1 - a_value))
    bearing = atan2(
        sin(t1 - t0) * cos(p1 - p0),
        cp0 * sin(p1) - sin(p0) * cos(p1) * cos(t1 - t0),
    )
    return (
        2 * EARTH_RADIUS_KM * unit_distance,
        int(bearing * 180 / pi + 360.5) % 360,
    )


def source_latitude_units(value: float, adjust_zero: bool = False) -> int:
    units = int((value + 90) / 180 * GEOLOCATION_COORDINATE_SCALE + 0.5) & 0xFFFFF
    if adjust_zero and units == 0:
        return 1 if value < 0 else 0xFFFFF
    return units


def source_longitude_units(value: float) -> int:
    return int((value + 180) / 360 * GEOLOCATION_COORDINATE_SCALE + 0.5) & 0xFFFFF
