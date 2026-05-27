"""Query and diagnostics surfaces for migrated charset/language packages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.services.charset_language import (
    CharsetLanguageRepository,
    CharsetTable,
    LanguageTable,
    SourceCodepoints,
    load_charset_language_repository,
)


@dataclass(frozen=True)
class CharsetLookupRequest:
    charset: str
    source_codepoints: SourceCodepoints


@dataclass(frozen=True)
class CharsetLookupResult:
    request: CharsetLookupRequest
    charset_table: CharsetTable | None
    unicode_codepoint: int | None

    def to_json(self) -> JsonObject:
        return {
            "charset": self.request.charset,
            "source_codepoints": list(self.request.source_codepoints),
            "source_text": codepoints_to_text(self.request.source_codepoints),
            "unicode_codepoint": self.unicode_codepoint,
            "unicode_text": codepoint_to_text(self.unicode_codepoint),
            "found": self.unicode_codepoint is not None,
        }


@dataclass(frozen=True)
class LanguageLookupRequest:
    language: str
    tag_name: str
    printed_value: str = ""


@dataclass(frozen=True)
class LanguageLookupResult:
    request: LanguageLookupRequest
    language_table: LanguageTable | None
    description: str | None
    print_conversion: str | None

    def to_json(self) -> JsonObject:
        return {
            "language": self.request.language,
            "tag_name": self.request.tag_name,
            "printed_value": self.request.printed_value,
            "description": self.description,
            "print_conversion": self.print_conversion,
            "found": self.description is not None or self.print_conversion is not None,
        }


@dataclass(frozen=True)
class CharsetLanguageQueryResult:
    repository: CharsetLanguageRepository
    charset_results: tuple[CharsetLookupResult, ...]
    language_results: tuple[LanguageLookupResult, ...]

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "summary": charset_language_repository_summary(self.repository),
            "charset_results": charset_results_to_json(self.charset_results),
            "language_results": language_results_to_json(self.language_results),
        }


@dataclass(frozen=True)
class CharsetLanguageDiagnostics:
    repository: CharsetLanguageRepository

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "summary": charset_language_repository_summary(self.repository),
            "charsets": charset_tables_to_json(tuple(self.repository.charsets.values())),
            "languages": language_tables_to_json(tuple(self.repository.languages.values())),
        }


def run_charset_language_query(
    charset_language_package: Path,
    charset_requests: tuple[CharsetLookupRequest, ...],
    language_requests: tuple[LanguageLookupRequest, ...],
) -> CharsetLanguageQueryResult:
    repository = load_charset_language_repository(charset_language_package)
    return CharsetLanguageQueryResult(
        repository=repository,
        charset_results=tuple(
            run_charset_lookup(repository, request) for request in charset_requests
        ),
        language_results=tuple(
            run_language_lookup(repository, request) for request in language_requests
        ),
    )


def write_charset_language_query_result(
    charset_language_package: Path,
    charset_requests: tuple[CharsetLookupRequest, ...],
    language_requests: tuple[LanguageLookupRequest, ...],
    output: Path,
) -> CharsetLanguageQueryResult:
    result = run_charset_language_query(
        charset_language_package,
        charset_requests,
        language_requests,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def charset_language_query_summary(result: CharsetLanguageQueryResult) -> JsonObject:
    return {
        "charset_result_count": len(result.charset_results),
        "charset_found_count": sum(
            1 for result_item in result.charset_results if result_item.unicode_codepoint is not None
        ),
        "language_result_count": len(result.language_results),
        "language_found_count": sum(
            1
            for result_item in result.language_results
            if result_item.description is not None or result_item.print_conversion is not None
        ),
    }


def build_charset_language_diagnostics(
    charset_language_package: Path,
) -> CharsetLanguageDiagnostics:
    return CharsetLanguageDiagnostics(
        repository=load_charset_language_repository(charset_language_package),
    )


def write_charset_language_diagnostics(
    charset_language_package: Path,
    output: Path,
) -> CharsetLanguageDiagnostics:
    diagnostics = build_charset_language_diagnostics(charset_language_package)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(diagnostics.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return diagnostics


def charset_language_diagnostics_summary(
    diagnostics: CharsetLanguageDiagnostics,
) -> JsonObject:
    return charset_language_repository_summary(diagnostics.repository)


def run_charset_lookup(
    repository: CharsetLanguageRepository,
    request: CharsetLookupRequest,
) -> CharsetLookupResult:
    charset_table = repository.charset(request.charset)
    unicode_codepoint = (
        None if charset_table is None else charset_table.unicode_for(request.source_codepoints)
    )
    return CharsetLookupResult(
        request=request,
        charset_table=charset_table,
        unicode_codepoint=unicode_codepoint,
    )


def run_language_lookup(
    repository: CharsetLanguageRepository,
    request: LanguageLookupRequest,
) -> LanguageLookupResult:
    language_table = repository.language(request.language)
    description = (
        None if language_table is None else language_table.description_for(request.tag_name)
    )
    print_conversion = (
        None
        if language_table is None or not request.printed_value
        else language_table.print_conversion_for(request.tag_name, request.printed_value)
    )
    return LanguageLookupResult(
        request=request,
        language_table=language_table,
        description=description,
        print_conversion=print_conversion,
    )


def charset_language_repository_summary(
    repository: CharsetLanguageRepository,
) -> JsonObject:
    return {
        "charset_count": len(repository.charsets),
        "charset_mapping_count": sum(
            len(charset.mappings) for charset in repository.charsets.values()
        ),
        "language_count": len(repository.languages),
        "language_translation_count": sum(
            len(language.translations) for language in repository.languages.values()
        ),
    }


def parse_codepoint_sequence(value: str) -> SourceCodepoints:
    return tuple(parse_codepoint(part) for part in value.split(",") if part)


def parse_codepoint(value: str) -> int:
    normalized = value.strip().lower()
    if normalized.startswith("0x"):
        return int(normalized, 0)
    return int(normalized, 10)


def codepoints_to_text(codepoints: SourceCodepoints) -> str:
    return " ".join(f"0x{codepoint:02x}" for codepoint in codepoints)


def codepoint_to_text(codepoint: int | None) -> str:
    return "" if codepoint is None else f"U+{codepoint:04X}"


def charset_results_to_json(results: tuple[CharsetLookupResult, ...]) -> JsonArray:
    return [result.to_json() for result in results]


def language_results_to_json(results: tuple[LanguageLookupResult, ...]) -> JsonArray:
    return [result.to_json() for result in results]


def charset_tables_to_json(charsets: tuple[CharsetTable, ...]) -> JsonArray:
    return [
        {
            "name": charset.name,
            "source_path": charset.source_path,
            "mapping_count": len(charset.mappings),
        }
        for charset in sorted(charsets, key=lambda charset: charset.name.casefold())
    ]


def language_tables_to_json(languages: tuple[LanguageTable, ...]) -> JsonArray:
    return [
        {
            "name": language.name,
            "source_path": language.source_path,
            "translation_count": len(language.translations),
        }
        for language in sorted(languages, key=lambda language: language.name.casefold())
    ]
