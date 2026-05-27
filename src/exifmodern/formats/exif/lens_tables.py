"""EXIF owner adapter for generated ExifTool lens identity tables."""

from __future__ import annotations

from pathlib import Path

from exifmodern.services.lens_identity import LensIdentityTable
from exifmodern.services.lens_identity_tables import (
    LensIdentityOwner,
    lens_identity_table_for_owner,
)


def exif_lens_identity_table(schema_path: Path, owner: LensIdentityOwner) -> LensIdentityTable:
    return lens_identity_table_for_owner(schema_path, owner)
