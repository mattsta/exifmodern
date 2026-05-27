"""ID3 frame planning helpers."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.id3.frame_transaction_plan import (
    ID3V1_MARKER,
    ID3V1_TRAILER_SIZE,
    ID3V2_HEADER_SIZE,
    ID3V2_MARKER,
    Id3EmissionGate,
    Id3FrameDatabasePlan,
    Id3FrameDefinitionPlan,
    Id3FrameFlagPlan,
    Id3FramePlan,
    Id3FrameRoutingPlan,
    Id3FrameTransactionBlocked,
    Id3FrameTransactionPlan,
    Id3UnknownFrameBinaryPreservationPlan,
    Id3v1FieldPlan,
    Id3v1TrailerPlan,
    Id3v2HeaderPlan,
    build_id3_frame_database_plan,
    build_id3_frame_transaction_plan,
    decode_id3_syncsafe_size,
    plan_id3_frame_transaction,
    route_id3_frame,
    sanitize_unknown_id3_frame_id,
)
from exifmodern.formats.id3.read_graph_adapter import (
    build_id3_read_graph,
    id3_frame_transaction_plan_to_read_graph,
    id3_unknown_binary_preservation_to_graph_tag,
    render_id3_frame_transaction_plan_record,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "ID3V1_MARKER",
    "ID3V1_TRAILER_SIZE",
    "ID3V2_HEADER_SIZE",
    "ID3V2_MARKER",
    "Id3EmissionGate",
    "Id3FrameDatabasePlan",
    "Id3FrameDefinitionPlan",
    "Id3FrameFlagPlan",
    "Id3FramePlan",
    "Id3FrameRoutingPlan",
    "Id3FrameTransactionBlocked",
    "Id3FrameTransactionPlan",
    "Id3UnknownFrameBinaryPreservationPlan",
    "Id3v1FieldPlan",
    "Id3v1TrailerPlan",
    "Id3v2HeaderPlan",
    "build_id3_frame_database_plan",
    "build_id3_frame_transaction_plan",
    "build_id3_read_graph",
    "decode_id3_syncsafe_size",
    "id3_frame_transaction_plan_to_read_graph",
    "id3_unknown_binary_preservation_to_graph_tag",
    "invoke_id3",
    "plan_id3_frame_transaction",
    "render_id3_frame_transaction_plan_record",
    "route_id3_frame",
    "sanitize_unknown_id3_frame_id",
]


def invoke_id3(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_id3_read_graph(_read_id3_exiftool_spans(path), source_file=source_file)


def _read_id3_exiftool_spans(path: Path) -> bytes:
    """Read the leading ID3v2 block plus ExifTool's bounded ID3 trailer probes."""
    with path.open("rb") as file:
        header = file.read(ID3V2_HEADER_SIZE)
        data = bytearray(header)
        if len(header) == ID3V2_HEADER_SIZE and header.startswith(ID3V2_MARKER):
            payload_size = decode_id3_syncsafe_size(header[6:10])
            if payload_size is not None:
                data.extend(file.read(payload_size))
                if header[5] & 0x10:
                    data.extend(file.read(ID3V2_HEADER_SIZE))
        file.seek(0, 2)
        file_size = file.tell()
        trailer_window = ID3V1_TRAILER_SIZE + 227
        trailer_offset = max(0, file_size - trailer_window)
        file.seek(trailer_offset)
        trailer = file.read(trailer_window)
        if len(trailer) >= ID3V1_TRAILER_SIZE and trailer[-ID3V1_TRAILER_SIZE:].startswith(
            ID3V1_MARKER
        ):
            enhanced = trailer[:-ID3V1_TRAILER_SIZE]
            if enhanced.startswith(b"TAG+"):
                data.extend(enhanced[-227:])
            data.extend(trailer[-ID3V1_TRAILER_SIZE:])
        return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="id3v2",
        builder_ref="exifmodern.formats.id3:invoke_id3",
        patterns=(Pattern(0, b"ID3"),),
    ),
)
