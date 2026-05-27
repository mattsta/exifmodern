"""Typed repositories for migrated ExifTool charset and language data."""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path

from exifmodern.json_types import (
    JsonObject,
    JsonValue,
    json_array_value,
    json_int_value,
    json_object_items,
    json_string_value,
    load_json_object,
)
from exifmodern.package_resources import charset_language_shard_path

type SourceCodepoints = tuple[int, ...]


@dataclass(frozen=True)
class CharsetMapping:
    source_codepoints: SourceCodepoints
    unicode_codepoint: int


@dataclass(frozen=True)
class CharsetTable:
    name: str
    source_path: str
    mappings: dict[SourceCodepoints, int]

    def unicode_for(self, source_codepoints: SourceCodepoints) -> int | None:
        return self.mappings.get(source_codepoints)


@dataclass(frozen=True)
class LanguageTable:
    name: str
    source_path: str
    translations: JsonObject

    def description_for(self, tag_name: str) -> str | None:
        return self.description_lookup(tag_name, "").description

    def description_lookup(
        self,
        tag_name: str,
        tag_language_code: str,
    ) -> LanguageDescriptionLookup:
        value = self.translations.get(tag_name)
        if isinstance(value, str):
            return LanguageDescriptionLookup(value, False)
        if isinstance(value, dict):
            description = json_string_value(value, "Description")
            return LanguageDescriptionLookup(description, False)
        if not tag_language_code:
            return LanguageDescriptionLookup(None, False)
        suffix = f"-{tag_language_code}"
        if not tag_name.endswith(suffix):
            return LanguageDescriptionLookup(None, False)
        value = self.translations.get(tag_name[: -len(suffix)])
        if isinstance(value, str):
            return LanguageDescriptionLookup(f"{value} ({tag_language_code})", True)
        if isinstance(value, dict):
            description = json_string_value(value, "Description")
            if description is not None:
                return LanguageDescriptionLookup(f"{description} ({tag_language_code})", True)
        return LanguageDescriptionLookup(None, False)

    def print_conversion_for(
        self,
        tag_name: str,
        printed_value: str,
        split_bitmask_value: bool = False,
    ) -> str | None:
        value = self.translations.get(tag_name)
        if not isinstance(value, dict):
            return None
        print_conv = json_object_items(value, "PrintConv")
        translated = print_conv.get(printed_value)
        if isinstance(translated, str):
            return translated
        if not split_bitmask_value:
            return None
        parts = printed_value.split(", ")
        mapped_parts: list[str] = []
        changed = False
        for part in parts:
            mapped = print_conv.get(part)
            if isinstance(mapped, str):
                mapped_parts.append(mapped)
                changed = True
            else:
                mapped_parts.append(part)
        return ", ".join(mapped_parts) if changed else None


@dataclass(frozen=True)
class LanguageDescriptionLookup:
    description: str | None
    used_lang_alt_base: bool


@dataclass(frozen=True)
class CharsetLanguageRepository:
    charsets: dict[str, CharsetTable]
    languages: dict[str, LanguageTable]
    use_shards: bool = False

    def charset(self, name: str) -> CharsetTable | None:
        table = self.charsets.get(name)
        if table is not None or not self.use_shards:
            return table
        return load_charset_table_shard(name)

    def language(self, name: str) -> LanguageTable | None:
        table = self.languages.get(name)
        if table is not None or not self.use_shards:
            return table
        return load_language_table_shard(name)


def load_charset_language_repository(package_path: Path) -> CharsetLanguageRepository:
    if package_path.name == "manifest.json" and package_path.parent.name == "charset-language":
        return CharsetLanguageRepository(charsets={}, languages={}, use_shards=True)
    package = load_json_object(package_path)
    charsets: dict[str, CharsetTable] = {}
    for value in json_array_value(package, "charsets"):
        charset_table = charset_table_from_json(value)
        if charset_table is not None:
            charsets[charset_table.name] = charset_table
    languages: dict[str, LanguageTable] = {}
    for value in json_array_value(package, "languages"):
        language_table = language_table_from_json(value)
        if language_table is not None:
            languages[language_table.name] = language_table
    return CharsetLanguageRepository(charsets=charsets, languages=languages)


def load_charset_table_shard(name: str) -> CharsetTable | None:
    shard_path = charset_language_shard_path("charsets", safe_charset_language_shard_name(name))
    if shard_path is None:
        return None
    return charset_table_from_json(load_gzip_json_object(shard_path))


def load_language_table_shard(name: str) -> LanguageTable | None:
    shard_path = charset_language_shard_path("languages", safe_charset_language_shard_name(name))
    if shard_path is None:
        return None
    return language_table_from_json(load_gzip_json_object(shard_path))


def load_gzip_json_object(path: Path) -> JsonObject:
    payload = gzip.decompress(path.read_bytes()).decode("utf-8")
    value: JsonValue = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON mapping: {path}")
    return value


def safe_charset_language_shard_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    if not normalized:
        raise ValueError(f"Empty charset/language shard name: {name!r}")
    return normalized


def charset_table_from_json(value: JsonValue) -> CharsetTable | None:
    if not isinstance(value, dict):
        return None
    name = json_string_value(value, "name")
    source_path = json_string_value(value, "source_path")
    if name is None or source_path is None:
        return None
    mappings: dict[SourceCodepoints, int] = {}
    for mapping_value in json_array_value(value, "mappings"):
        mapping = charset_mapping_from_json(mapping_value)
        if mapping is not None:
            mappings[mapping.source_codepoints] = mapping.unicode_codepoint
    return CharsetTable(name=name, source_path=source_path, mappings=mappings)


def charset_mapping_from_json(value: JsonValue) -> CharsetMapping | None:
    if not isinstance(value, dict):
        return None
    source_values = json_array_value(value, "source_codepoints")
    source_codepoints: list[int] = []
    for item in source_values:
        if isinstance(item, int) and not isinstance(item, bool):
            source_codepoints.append(item)
    unicode_codepoint = json_int_value(value, "unicode_codepoint")
    if not source_codepoints or unicode_codepoint is None:
        return None
    return CharsetMapping(
        source_codepoints=tuple(source_codepoints),
        unicode_codepoint=unicode_codepoint,
    )


def language_table_from_json(value: JsonValue) -> LanguageTable | None:
    if not isinstance(value, dict):
        return None
    name = json_string_value(value, "name")
    source_path = json_string_value(value, "source_path")
    translations_value = value.get("translations")
    if name is None or source_path is None or not isinstance(translations_value, dict):
        return None
    return LanguageTable(name=name, source_path=source_path, translations=translations_value)
