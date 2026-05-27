"""Source-backed MIE selected-output materialization helpers."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.mie.reader import (
    MIE_GROUP_FORMATS,
    MIE_SIGNATURE_TAG,
    mie_endian,
    parse_mie_read_tags,
    read_mie_element,
)
from exifmodern.formats.public_payload import read_public_document_payload


def materialize_source_mie_file(source_path: Path) -> bytes:
    """Return exact standalone MIE bytes already present in a source.

    This is intentionally an exact-copy materializer, not a MIE writer. It only
    covers source files that the owned MIE reader can validate as standalone MIE.
    """

    source_data = read_public_document_payload(source_path)
    if source_data is None:
        raise ValueError("standalone MIE file exceeds public materialization limit")
    first_element = read_mie_element(source_data, 0, mie_endian(source_data))
    if (
        first_element is None
        or first_element.format_code not in MIE_GROUP_FORMATS
        or first_element.tag_name.encode("latin-1") != MIE_SIGNATURE_TAG
    ):
        raise ValueError("source is not a standalone MIE file")
    parse_mie_read_tags(source_data)
    return source_data
