"""Typed JSON boundary helpers.

The stdlib JSON decoder is intentionally dynamic. Keep that dynamic boundary in
one module and expose recursive JSON value types everywhere else.
"""

from __future__ import annotations

import gzip
import json
import pickle
from pathlib import Path

type JsonScalar = str | int | float | bool | None
type JsonArray = list[JsonValue]
type JsonObject = dict[str, JsonValue]
type JsonValue = JsonScalar | JsonArray | JsonObject

SIDECAR_FRESHNESS_TOLERANCE_NS = 30_000_000_000


def load_json_value(path: Path) -> JsonValue:
    if path.suffix == ".pickle":
        direct_pickle_payload: JsonValue = pickle.loads(path.read_bytes())
        return direct_pickle_payload
    pickle_path = fresh_pickle_sidecar(path)
    if pickle_path is not None:
        payload: JsonValue = pickle.loads(pickle_path.read_bytes())
        return payload
    compressed_pickle_path = fresh_compressed_pickle_sidecar(path)
    if compressed_pickle_path is not None:
        compressed_payload: JsonValue = pickle.loads(
            gzip.decompress(compressed_pickle_path.read_bytes())
        )
        return compressed_payload
    if path.suffix == ".gz":
        gzip_payload: JsonValue = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        return gzip_payload
    text_payload: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    return text_payload


def fresh_pickle_sidecar(path: Path) -> Path | None:
    pickle_path = pickle_sidecar_path(path)
    if not pickle_path.is_file():
        return None
    if sidecar_is_stale(pickle_path, path):
        return None
    return pickle_path


def fresh_compressed_pickle_sidecar(path: Path) -> Path | None:
    compressed_pickle_path = compressed_pickle_sidecar_path(path)
    if not compressed_pickle_path.is_file():
        return None
    if sidecar_is_stale(compressed_pickle_path, path):
        return None
    return compressed_pickle_path


def sidecar_is_stale(sidecar_path: Path, source_path: Path) -> bool:
    source_newer_by_ns = source_path.stat().st_mtime_ns - sidecar_path.stat().st_mtime_ns
    return source_newer_by_ns > SIDECAR_FRESHNESS_TOLERANCE_NS


def pickle_sidecar_path(path: Path) -> Path:
    if path.suffix == ".gz" and path.name.endswith(".json.gz"):
        return path.with_name(path.name.removesuffix(".json.gz") + ".pickle")
    if path.suffix == ".json":
        return path.with_suffix(".pickle")
    return path.with_suffix(path.suffix + ".pickle")


def compressed_pickle_sidecar_path(path: Path) -> Path:
    return pickle_sidecar_path(path).with_suffix(".pickle.gz")


def load_json_object(path: Path) -> JsonObject:
    payload = load_json_value(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON mapping: {path}")
    return payload


def json_object_value(value: JsonValue, key: str) -> JsonValue | None:
    if not isinstance(value, dict):
        return None
    return value.get(key)


def json_array_value(value: JsonValue, key: str) -> JsonArray:
    item = json_object_value(value, key)
    return item if isinstance(item, list) else []


def json_string_array_value(value: JsonValue, key: str) -> list[str]:
    return [item for item in json_array_value(value, key) if isinstance(item, str)]


def json_string_array_or_none(value: JsonArray) -> list[str] | None:
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        items.append(item)
    return items


def json_object_items(value: JsonValue, key: str) -> JsonObject:
    item = json_object_value(value, key)
    return item if isinstance(item, dict) else {}


def json_object_or_empty(value: JsonValue | None) -> JsonObject:
    return value if isinstance(value, dict) else {}


def json_array_or_empty(value: JsonValue | None) -> JsonArray:
    return value if isinstance(value, list) else []


def json_string_value(value: JsonValue, key: str) -> str | None:
    item = json_object_value(value, key)
    return item if isinstance(item, str) else None


def json_int_value(value: JsonValue, key: str) -> int | None:
    item = json_object_value(value, key)
    return item if isinstance(item, int) and not isinstance(item, bool) else None


def json_bool_value(value: JsonValue, key: str) -> bool | None:
    item = json_object_value(value, key)
    return item if isinstance(item, bool) else None


def json_scalar_to_string(value: JsonValue | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, sort_keys=True)
