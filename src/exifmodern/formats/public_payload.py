"""Bounded payload reads for public format invokers."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

PUBLIC_DOCUMENT_PAYLOAD_LIMIT = 16 * 1024 * 1024


def read_public_document_payload(
    path: Path,
    *,
    byte_limit: int = PUBLIC_DOCUMENT_PAYLOAD_LIMIT,
) -> bytes | None:
    """Read a parser-owned document payload without using Path.read_bytes()."""

    with path.open("rb") as file:
        payload = file.read(byte_limit + 1)
    if len(payload) > byte_limit:
        return None
    return payload


def oversized_public_payload_graph(
    source_file: str,
    *,
    format_name: str,
    byte_limit: int = PUBLIC_DOCUMENT_PAYLOAD_LIMIT,
) -> ReadGraph:
    from exifmodern.read_graph import ReadGraph

    return ReadGraph(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_file=source_file,
        tags=[],
        diagnostics=[
            f"{format_name} public read deferred: source exceeds the default "
            f"{byte_limit} byte payload materialization limit."
        ],
    )
