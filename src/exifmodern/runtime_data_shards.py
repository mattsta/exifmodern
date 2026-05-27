"""Shared runtime-data shard keys and naming rules."""

from __future__ import annotations

import re
from typing import Literal

type GeneratedIndexShard = Literal[
    "file_type_catalog",
    "geolocation",
    "group_family_catalog",
    "lens_identity",
    "listx_catalog",
    "tag_lookup",
]
type GeneratedIndexPackageShard = Literal[
    "file_type_catalog",
    "geolocation",
    "group_family_catalog",
    "listx_catalog",
    "tag_lookup",
]
type CharsetLanguageShardKind = Literal["charsets", "languages"]
type MakerNoteShard = Literal[
    "canon",
    "canon_custom",
    "casio",
    "fujifilm",
    "garmin",
    "kodak",
    "minolta",
    "nikon",
    "nikon_custom",
    "nikon_settings",
    "olympus",
    "panasonic",
    "pentax",
    "sigma",
    "sony",
]

GENERATED_INDEX_PACKAGE_SHARDS: tuple[GeneratedIndexPackageShard, ...] = (
    "geolocation",
    "tag_lookup",
    "listx_catalog",
    "file_type_catalog",
    "group_family_catalog",
)
GENERATED_INDEX_SHARDS: tuple[GeneratedIndexShard, ...] = (
    "geolocation",
    "tag_lookup",
    "listx_catalog",
    "file_type_catalog",
    "group_family_catalog",
    "lens_identity",
)
MAKER_NOTE_MODULE_SHARDS: dict[str, MakerNoteShard] = {
    "Image::ExifTool::Canon": "canon",
    "Image::ExifTool::CanonCustom": "canon_custom",
    "Image::ExifTool::Casio": "casio",
    "Image::ExifTool::FujiFilm": "fujifilm",
    "Image::ExifTool::Garmin": "garmin",
    "Image::ExifTool::Kodak": "kodak",
    "Image::ExifTool::Minolta": "minolta",
    "Image::ExifTool::Nikon": "nikon",
    "Image::ExifTool::NikonCustom": "nikon_custom",
    "Image::ExifTool::NikonSettings": "nikon_settings",
    "Image::ExifTool::Olympus": "olympus",
    "Image::ExifTool::Panasonic": "panasonic",
    "Image::ExifTool::Pentax": "pentax",
    "Image::ExifTool::Sigma": "sigma",
    "Image::ExifTool::Sony": "sony",
}


def safe_runtime_data_shard_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    if not normalized:
        raise ValueError(f"empty runtime-data shard name after normalization: {name!r}")
    return normalized


def maker_note_shard_for_module(module: str) -> MakerNoteShard | None:
    return MAKER_NOTE_MODULE_SHARDS.get(module)


def maker_note_shard_key_for_module(module: str) -> str:
    return maker_note_shard_for_module(module) or safe_runtime_data_shard_name(module)
