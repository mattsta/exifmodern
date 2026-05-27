"""XMP owner adapter for generated lens identity tables."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from exifmodern.services.lens_identity import LensIdentityTable
from exifmodern.services.lens_identity_tables import (
    LensIdentityOwner,
    lens_identity_table_for_owner,
)

type XmpLensMake = Literal[
    "Canon",
    "Nikon",
    "Pentax",
    "Ricoh",
    "Sony",
    "Sigma",
    "Samsung",
    "Leica",
]


def xmp_lens_identity_table(schema_path: Path, make: XmpLensMake) -> LensIdentityTable:
    return lens_identity_table_for_owner(schema_path, xmp_lens_identity_owner(make))


def xmp_lens_identity_owner(make: XmpLensMake) -> LensIdentityOwner:
    if make == "Canon":
        return "canon"
    if make == "Nikon":
        return "nikon"
    if make in {"Pentax", "Ricoh"}:
        return "pentax"
    if make == "Sony":
        return "sony"
    if make == "Sigma":
        return "sigma"
    if make == "Samsung":
        return "samsung"
    return "leica"
