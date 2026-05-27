"""Source-backed ICC profile materialization helpers."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.icc.reader import validate_icc_profile
from exifmodern.formats.public_payload import read_public_document_payload


def materialize_source_icc_profile(source_path: Path) -> bytes:
    """Return exact standalone ICC_Profile bytes already present in a source.

    This is intentionally an exact-copy materializer, not an ICC writer. It
    covers standalone ICC/ICM files and JPEG APP2 ICC_PROFILE chunk reassembly.
    """

    with source_path.open("rb") as file:
        prefix = file.read(2)
    if prefix.startswith(b"\xff\xd8"):
        from exifmodern.formats.jpeg.app_segments.icc import read_icc_profile

        profile = read_icc_profile(source_path)
        invalid_reason = validate_icc_profile(profile, strict_declared_length=True)
        if invalid_reason is not None:
            raise ValueError(invalid_reason)
        return profile

    source_data = read_public_document_payload(source_path)
    if source_data is None:
        raise ValueError("standalone ICC profile exceeds public materialization limit")
    if validate_icc_profile(source_data, strict_declared_length=True) is None:
        return source_data

    raise ValueError("source does not contain a standalone ICC profile or JPEG APP2 ICC_Profile")
