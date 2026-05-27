"""BPG image transaction planning public API."""

from pathlib import Path
from typing import BinaryIO

from exifmodern.formats.bpg.image_transaction_plan import (
    BpgImageTransactionPlan,
    BpgRewriteRequest,
    build_bpg_image_transaction_plan,
)
from exifmodern.formats.bpg.nested_read import (
    BpgNestedPayloadExtraction,
    BpgNestedTag,
    extract_bpg_nested_payloads,
)
from exifmodern.formats.bpg.read_graph_adapter import (
    bpg_image_transaction_plan_to_read_graph,
    build_bpg_read_graph,
    is_bpg_prefix,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "BpgImageTransactionPlan",
    "BpgNestedPayloadExtraction",
    "BpgNestedTag",
    "BpgRewriteRequest",
    "bpg_image_transaction_plan_to_read_graph",
    "build_bpg_image_transaction_plan",
    "build_bpg_read_graph",
    "extract_bpg_nested_payloads",
    "invoke_bpg",
    "is_bpg_prefix",
)


def invoke_bpg(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_bpg_exiftool_ranges(path)
    return build_bpg_read_graph(data, source_file=source_file)


def _read_bpg_exiftool_ranges(path: Path) -> bytes:
    with path.open("rb") as file:
        header = bytearray(file.read(21))
        if len(header) < 21 or not header.startswith(b"BPG\xfb"):
            return bytes(header)
        if not header[5] & 0x08:
            return bytes(header)
        header_end = _bpg_header_end(bytes(header))
        if header_end is None:
            return bytes(header)
        file.seek(header_end)
        extension_length_bytes = _read_bpg_ue7_bytes(file, 5)
        extension_length = _bpg_ue7_value(extension_length_bytes)
        if extension_length is None or extension_length > 10_000_000:
            return bytes(header)
        return bytes(header[:header_end] + extension_length_bytes + file.read(extension_length))


def _bpg_header_end(data: bytes) -> int | None:
    offset = 6
    for _ in range(3):
        parsed = _bpg_ue7_value_and_end(data, offset)
        if parsed is None:
            return None
        _, offset = parsed
    return offset


def _read_bpg_ue7_bytes(file: BinaryIO, limit: int) -> bytes:
    data = bytearray()
    for _ in range(limit):
        byte = file.read(1)
        if not byte:
            break
        data.extend(byte)
        if byte[0] < 0x80:
            break
    return bytes(data)


def _bpg_ue7_value(data: bytes) -> int | None:
    parsed = _bpg_ue7_value_and_end(data, 0)
    return None if parsed is None else parsed[0]


def _bpg_ue7_value_and_end(data: bytes, offset: int) -> tuple[int, int] | None:
    value = 0
    for index in range(5):
        absolute = offset + index
        if absolute >= len(data):
            return None
        byte = data[absolute]
        value = (value << 7) | (byte & 0x7F)
        if byte < 0x80:
            return value, absolute + 1
    return None


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="bpg",
        builder_ref="exifmodern.formats.bpg:invoke_bpg",
        patterns=(Pattern(0, b"BPG\xfb"),),
    ),
)
