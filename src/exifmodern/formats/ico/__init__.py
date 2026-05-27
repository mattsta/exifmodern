"""Windows ICO/CUR planning surfaces."""

from pathlib import Path

from exifmodern.formats.ico.directory_transaction_plan import (
    IcoDirectoryImageTransactionPlan,
    IcoMetadataDelegationRequest,
    build_ico_directory_image_transaction_plan,
)
from exifmodern.formats.ico.read_graph_adapter import (
    build_ico_read_graph,
    ico_directory_byte_count,
    is_ico_prefix,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "IcoDirectoryImageTransactionPlan",
    "IcoMetadataDelegationRequest",
    "build_ico_directory_image_transaction_plan",
    "build_ico_read_graph",
    "ico_directory_byte_count",
    "invoke_ico",
    "is_ico_prefix",
]


def invoke_ico(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    byte_count = ico_directory_byte_count(prefix)
    if byte_count is None:
        directory_data = prefix[:0]
    elif len(prefix) >= byte_count:
        directory_data = prefix[:byte_count]
    else:
        with path.open("rb") as file:
            directory_data = file.read(byte_count)
    return build_ico_read_graph(directory_data, source_file=source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="ico",
        builder_ref="exifmodern.formats.ico:invoke_ico",
        patterns=(Pattern(0, b"\x00\x00\x01\x00"),),
        structural_check="exifmodern.formats.ico.read_graph_adapter:is_ico_prefix",
    ),
    Signature(
        format_id="cur",
        builder_ref="exifmodern.formats.ico:invoke_ico",
        patterns=(Pattern(0, b"\x00\x00\x02\x00"),),
        structural_check="exifmodern.formats.ico.read_graph_adapter:is_ico_prefix",
    ),
    Signature(
        format_id="ico/v0",
        builder_ref="exifmodern.formats.ico:invoke_ico",
        patterns=(Pattern(0, b"\x00\x00\x01\x000\x00"),),
    ),
    Signature(
        format_id="ico/v1",
        builder_ref="exifmodern.formats.ico:invoke_ico",
        patterns=(Pattern(0, b"\x00\x00\x01\x00^\x00"),),
    ),
    Signature(
        format_id="ico/v2",
        builder_ref="exifmodern.formats.ico:invoke_ico",
        patterns=(Pattern(0, b"\x00\x00\x02\x000\x00"),),
    ),
    Signature(
        format_id="ico/v3",
        builder_ref="exifmodern.formats.ico:invoke_ico",
        patterns=(Pattern(0, b"\x00\x00\x02\x00^\x00"),),
    ),
)
