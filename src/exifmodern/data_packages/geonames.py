"""Native GeoNames ingestion for ExifModern geolocation runtime data."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

GEONAMES_DOWNLOAD_BASE_URL = "https://download.geonames.org/export/dump"
GEONAMES_DATASET_FILES: tuple[str, ...] = (
    "allCountries.txt",
    "countryInfo.txt",
    "admin1CodesASCII.txt",
    "admin2Codes.txt",
    "featureCodes_en.txt",
)
GEONAMES_ARCHIVE_FILES: dict[str, str] = {
    "allCountries.txt": "allCountries.zip",
    "alternateNamesV2.txt": "alternateNamesV2.zip",
}
GEONAMES_DEFAULT_ALWAYS_INCLUDE_CODES = frozenset(("PPLA", "PPLA2"))
GEONAMES_DEFAULT_POPULATION_CODES = frozenset(
    (
        "PPL",
        "PPLA",
        "PPLA2",
        "PPLA3",
        "PPLA4",
        "PPLA5",
        "PPLC",
        "PPLCH",
        "PPLF",
        "PPLG",
        "PPLH",
        "PPLL",
        "PPLQ",
        "PPLR",
        "PPLS",
        "PPLW",
        "PPLX",
        "STLMT",
    )
)
GEONAMES_LANGUAGE_CODES = frozenset(
    (
        "cs",
        "de",
        "en",
        "en-ca",
        "en-gb",
        "es",
        "fi",
        "fr",
        "it",
        "ja",
        "ko",
        "nl",
        "pl",
        "ru",
        "sk",
        "sv",
        "tr",
        "zh",
        "zh-cn",
        "zh-tw",
    )
)


@dataclass(frozen=True)
class GeonamesFetchRecord:
    name: str
    url: str
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class GeonamesRemoteMetadata:
    url: str
    http_status: int
    last_modified: str | None
    etag: str | None
    content_length: int | None
    checked_at: str


@dataclass(frozen=True)
class GeonamesAdminRecord:
    code: str
    name: str
    geonameid: str


@dataclass(frozen=True)
class GeonamesCityRecord:
    geonameid: str
    name: str
    latitude: str
    longitude: str
    feature_code: str
    country_code: str
    admin1_code: str
    admin2_code: str
    population: int
    timezone: str


@dataclass(frozen=True)
class GeonamesAlternateRecord:
    language_code: str
    name: str
    preferred: bool


def fetch_geonames_cache(
    cache_dir: Path,
    *,
    base_url: str = GEONAMES_DOWNLOAD_BASE_URL,
    include_alternate_names: bool = True,
    force: bool = False,
) -> JsonObject:
    cache_dir.mkdir(parents=True, exist_ok=True)
    previous_manifest = load_previous_geonames_manifest(cache_dir / "manifest.json")
    requested_files = list(GEONAMES_DATASET_FILES)
    if include_alternate_names:
        requested_files.append("alternateNamesV2.txt")
    records: JsonArray = []
    for file_name in requested_files:
        records.append(
            fetch_geonames_file(
                cache_dir,
                base_url,
                file_name,
                previous_manifest=previous_manifest,
                force=force,
            )
        )
    manifest: JsonObject = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "geonames",
        "base_url": base_url,
        "files": records,
    }
    (cache_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def fetch_geonames_file(
    cache_dir: Path,
    base_url: str,
    file_name: str,
    *,
    previous_manifest: JsonObject | None = None,
    force: bool = False,
) -> JsonObject:
    archive_name = GEONAMES_ARCHIVE_FILES.get(file_name)
    if archive_name is None:
        url = f"{base_url.rstrip('/')}/{file_name}"
        target = cache_dir / file_name
        previous_record = previous_geonames_record(previous_manifest, file_name)
        remote = fetch_conditional_remote_metadata(url, previous_record)
        fetched = should_fetch_geonames_file(previous_record, remote, target, force=force)
        if fetched:
            download_file(url, target)
    else:
        url = f"{base_url.rstrip('/')}/{archive_name}"
        archive_path = cache_dir / archive_name
        target = cache_dir / file_name
        previous_record = previous_geonames_record(previous_manifest, file_name)
        remote = fetch_conditional_remote_metadata(url, previous_record)
        fetched = should_fetch_geonames_file(previous_record, remote, target, force=force)
        if fetched:
            download_file(url, archive_path)
            extract_single_zip_member(archive_path, file_name, target)
        target = cache_dir / file_name
    payload = target.read_bytes()
    return {
        "name": file_name,
        "url": url,
        "path": target.name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "remote_http_status": remote.http_status,
        "remote_last_modified": remote.last_modified,
        "remote_etag": remote.etag,
        "remote_content_length": remote.content_length,
        "checked_at": remote.checked_at,
        "fetched_at": (
            datetime.now(UTC).isoformat() if fetched else previous_fetched_at(previous_record)
        ),
        "fetch_status": "fetched" if fetched else "reused",
    }


def load_previous_geonames_manifest(path: Path) -> JsonObject | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def previous_geonames_record(manifest: JsonObject | None, file_name: str) -> JsonObject | None:
    if manifest is None:
        return None
    files = manifest.get("files")
    if not isinstance(files, list):
        return None
    for item in files:
        if isinstance(item, dict) and item.get("name") == file_name:
            return item
    return None


def previous_fetched_at(previous_record: JsonObject | None) -> str | None:
    if previous_record is None:
        return None
    value = previous_record.get("fetched_at")
    return value if isinstance(value, str) else None


def should_fetch_geonames_file(
    previous_record: JsonObject | None,
    remote: GeonamesRemoteMetadata,
    target: Path,
    *,
    force: bool = False,
) -> bool:
    if force or previous_record is None or not target.is_file():
        return True
    return not remote_metadata_matches_previous(previous_record, remote)


def remote_metadata_matches_previous(
    previous_record: Mapping[str, JsonValue],
    remote: GeonamesRemoteMetadata,
) -> bool:
    if remote.etag is not None and previous_record.get("remote_etag") != remote.etag:
        return False
    if (
        remote.last_modified is not None
        and previous_record.get("remote_last_modified") != remote.last_modified
    ):
        return False
    if (
        remote.content_length is not None
        and previous_record.get("remote_content_length") != remote.content_length
    ):
        return False
    return any(
        value is not None for value in (remote.etag, remote.last_modified, remote.content_length)
    )


def fetch_remote_metadata(url: str) -> GeonamesRemoteMetadata:
    request = Request(url, method="HEAD")
    with urlopen(request, timeout=60) as response:
        headers = response.headers
        return GeonamesRemoteMetadata(
            url=url,
            http_status=response.status,
            last_modified=headers.get("Last-Modified"),
            etag=headers.get("ETag"),
            content_length=header_int(headers.get("Content-Length")),
            checked_at=datetime.now(UTC).isoformat(),
        )


def fetch_conditional_remote_metadata(
    url: str,
    previous_record: JsonObject | None,
) -> GeonamesRemoteMetadata:
    headers: dict[str, str] = {}
    if previous_record is not None:
        etag = previous_record.get("remote_etag")
        last_modified = previous_record.get("remote_last_modified")
        if isinstance(etag, str):
            headers["If-None-Match"] = etag
        if isinstance(last_modified, str):
            headers["If-Modified-Since"] = last_modified
    request = Request(url, headers=headers, method="HEAD")
    try:
        with urlopen(request, timeout=60) as response:
            response_headers = response.headers
            return GeonamesRemoteMetadata(
                url=url,
                http_status=response.status,
                last_modified=response_headers.get("Last-Modified"),
                etag=response_headers.get("ETag"),
                content_length=header_int(response_headers.get("Content-Length")),
                checked_at=datetime.now(UTC).isoformat(),
            )
    except HTTPError as error:
        if error.code != 304:
            raise
        return GeonamesRemoteMetadata(
            url=url,
            http_status=304,
            last_modified=string_or_none(previous_record, "remote_last_modified"),
            etag=string_or_none(previous_record, "remote_etag"),
            content_length=int_or_none(previous_record, "remote_content_length"),
            checked_at=datetime.now(UTC).isoformat(),
        )


def string_or_none(value: JsonObject | None, key: str) -> str | None:
    if value is None:
        return None
    item = value.get(key)
    return item if isinstance(item, str) else None


def int_or_none(value: JsonObject | None, key: str) -> int | None:
    if value is None:
        return None
    item = value.get(key)
    return item if isinstance(item, int) and not isinstance(item, bool) else None


def header_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def download_file(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    with urlopen(url, timeout=120) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output)
    temporary.replace(target)


def extract_single_zip_member(archive_path: Path, member_name: str, target: Path) -> None:
    with (
        zipfile.ZipFile(archive_path) as archive,
        archive.open(member_name) as source,
        target.open("wb") as output,
    ):
        shutil.copyfileobj(source, output)


def parse_geonames_cache(cache_dir: Path, *, min_population: int = 2000) -> JsonObject:
    countries = parse_country_info(cache_dir / "countryInfo.txt")
    admin1 = parse_admin_codes(cache_dir / "admin1CodesASCII.txt")
    admin2 = parse_admin_codes(cache_dir / "admin2Codes.txt")
    feature_types = parse_feature_codes(cache_dir / "featureCodes_en.txt")
    selected_entries = selected_geonames_city_records(
        cache_dir / "allCountries.txt",
        min_population=min_population,
    )
    alternate_names, language_translations = parse_alternate_names(
        cache_dir / "alternateNamesV2.txt",
        selected_entries,
        countries,
        admin1,
        admin2,
    )
    entries: JsonArray = []
    for entry_index, record in enumerate(selected_entries):
        country = countries.get(record.country_code, record.country_code)
        region_key = f"{record.country_code}.{record.admin1_code}"
        subregion_key = f"{record.country_code}.{record.admin1_code}.{record.admin2_code}"
        region = admin1.get(
            region_key,
            GeonamesAdminRecord(region_key, record.admin1_code, ""),
        ).name
        subregion = admin2.get(
            subregion_key,
            GeonamesAdminRecord(subregion_key, record.admin2_code, ""),
        ).name
        entries.append(
            {
                "entry_index": entry_index,
                "city": record.name,
                "region": region,
                "subregion": subregion,
                "country_code": record.country_code,
                "country": country,
                "timezone": record.timezone,
                "feature_code": record.feature_code,
                "feature_type": feature_types.get(record.feature_code),
                "population": float(record.population),
                "latitude": normalized_coordinate(record.latitude),
                "longitude": normalized_coordinate(record.longitude),
                "alternate_names": list(alternate_names.get(record.geonameid, ())),
            }
        )
    return {
        "format": "geolocation_database_v1",
        "source_contract": "GeoNames dump direct",
        "version": "geonames-direct-v1",
        "declared_city_count": len(entries),
        "comment": (
            f"GeoNames direct import with population {min_population} or greater "
            "and ExifTool-compatible populated-place feature defaults"
        ),
        "alternate_names_source_present": (cache_dir / "alternateNamesV2.txt").is_file(),
        "language_translation_source_present": bool(language_translations),
        "alternate_names_count_matches_city_count": bool(alternate_names),
        "alternate_name_entry_count": sum(1 for names in alternate_names.values() if names),
        "alternate_name_count": sum(len(names) for names in alternate_names.values()),
        "language_code_count": len(language_translations),
        "language_translation_count": language_translation_count(language_translations),
        "language_translation_error_count": 0,
        "language_translation_errors": [],
        "city_count": len(entries),
        "country_count": len(countries),
        "region_count": len(admin1),
        "subregion_count": len(admin2),
        "timezone_count": len({record.timezone for record in selected_entries}),
        "feature_code_count": len(feature_types),
        "sample_cities": [record.name for record in selected_entries[:5]],
        "language_translations": language_translations,
        "entries": entries,
    }


def parse_country_info(path: Path) -> dict[str, str]:
    countries: dict[str, str] = {}
    for row in tab_rows(path):
        if len(row) < 5:
            continue
        countries[row[0]] = row[4]
    return countries


def parse_admin_codes(path: Path) -> dict[str, GeonamesAdminRecord]:
    records: dict[str, GeonamesAdminRecord] = {}
    for row in tab_rows(path):
        if len(row) < 4:
            continue
        records[row[0]] = GeonamesAdminRecord(code=row[0], name=row[1], geonameid=row[3])
    return records


def parse_feature_codes(path: Path) -> dict[str, str]:
    features: dict[str, str] = {}
    for row in tab_rows(path):
        if len(row) < 2:
            continue
        feature_code = row[0].split(".")[-1]
        features[feature_code] = row[1]
    return features


def selected_geonames_city_records(
    path: Path,
    *,
    min_population: int,
) -> tuple[GeonamesCityRecord, ...]:
    records: list[GeonamesCityRecord] = []
    for row in tab_rows(path):
        if len(row) < 18:
            continue
        feature_class = row[6]
        feature_code = row[7]
        population = int_or_zero(row[14])
        if feature_class != "P":
            continue
        if not keep_geonames_city(feature_code, population, min_population):
            continue
        records.append(
            GeonamesCityRecord(
                geonameid=row[0],
                name=row[1],
                latitude=row[4],
                longitude=row[5],
                feature_code=feature_code,
                country_code=row[8],
                admin1_code=row[10],
                admin2_code=row[11],
                population=population,
                timezone=row[17],
            )
        )
    return tuple(sorted(records, key=geonames_city_sort_key))


def keep_geonames_city(feature_code: str, population: int, min_population: int) -> bool:
    if feature_code in GEONAMES_DEFAULT_ALWAYS_INCLUDE_CODES:
        return True
    return population >= min_population and feature_code in GEONAMES_DEFAULT_POPULATION_CODES


def geonames_city_sort_key(record: GeonamesCityRecord) -> tuple[str, str, str, str]:
    return (record.name.casefold(), record.country_code, record.admin1_code, record.admin2_code)


def parse_alternate_names(
    path: Path,
    selected_entries: tuple[GeonamesCityRecord, ...],
    countries: dict[str, str],
    admin1: dict[str, GeonamesAdminRecord],
    admin2: dict[str, GeonamesAdminRecord],
) -> tuple[dict[str, tuple[str, ...]], JsonArray]:
    if not path.is_file():
        return {}, []
    selected_by_id = {record.geonameid: record for record in selected_entries}
    alias_values: dict[str, list[str]] = {record.geonameid: [] for record in selected_entries}
    translations_by_language: dict[str, dict[str, str]] = {}
    for row in tab_rows(path):
        if len(row) < 4:
            continue
        geonameid = row[1]
        record = selected_by_id.get(geonameid)
        if record is None:
            continue
        language_code = row[2].casefold()
        name = row[3]
        if not name or name == record.name:
            continue
        if language_code in {"", "abbr", "link", "post"}:
            append_unique(alias_values[geonameid], name)
            continue
        if language_code in GEONAMES_LANGUAGE_CODES:
            table = translations_by_language.setdefault(language_code.replace("-", "_"), {})
            add_city_translation(table, record, name)
    add_country_region_translations(translations_by_language, countries, admin1, admin2)
    language_records: JsonArray = []
    for language, translations in sorted(translations_by_language.items()):
        translation_payload: JsonObject = dict(translations)
        language_record: JsonObject = {
            "name": language,
            "translations": translation_payload,
            "translation_count": len(translations),
            "source_path": "alternateNamesV2.txt",
        }
        language_records.append(language_record)
    return {key: tuple(values) for key, values in alias_values.items()}, language_records


def add_city_translation(table: dict[str, str], record: GeonamesCityRecord, name: str) -> None:
    table.setdefault(
        f"{record.country_code}{record.admin1_code},{record.admin2_code},{record.name}",
        name,
    )
    table.setdefault(f"{record.country_code}{record.admin1_code},{record.name}", name)
    table.setdefault(f"{record.country_code},{record.name}", name)
    table.setdefault(record.name, name)


def add_country_region_translations(
    translations_by_language: dict[str, dict[str, str]],
    countries: dict[str, str],
    admin1: dict[str, GeonamesAdminRecord],
    admin2: dict[str, GeonamesAdminRecord],
) -> None:
    for table in translations_by_language.values():
        for country_code, country_name in countries.items():
            table.setdefault(f"{country_code},", country_name)
        for record in admin1.values():
            table.setdefault(f"{record.code.replace('.', '')},", record.name)
        for record in admin2.values():
            parts = record.code.split(".")
            if len(parts) >= 3:
                table.setdefault(f"{parts[0]}{parts[1]},{parts[2]},", record.name)


def append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def language_translation_count(records: JsonArray) -> int:
    count = 0
    for item in records:
        if not isinstance(item, dict):
            continue
        translations = item.get("translations")
        if isinstance(translations, dict):
            count += len(translations)
    return count


def normalized_coordinate(value: str) -> str:
    try:
        return f"{float(value):.4f}"
    except ValueError:
        return "0.0000"


def tab_rows(path: Path) -> tuple[list[str], ...]:
    rows: list[list[str]] = []
    if not path.is_file():
        return ()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.rstrip("\n\r")
            if not stripped or stripped.startswith("#"):
                continue
            rows.append(stripped.split("\t"))
    return tuple(rows)


def int_or_zero(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0
