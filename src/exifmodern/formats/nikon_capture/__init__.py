"""Nikon Capture metadata transaction planning."""

from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.nikon_capture.transaction_plan import (
    NIKON_CAPTURE_FIXED_HEADER_SIZE,
    NIKON_CAPTURE_HEADER_SIZE,
    NIKON_CAPTURE_MAGIC,
    NikonCaptureDirectoryPlan,
    NikonCaptureEditVersionPlan,
    NikonCaptureEditVersionsPlan,
    NikonCaptureEmissionGate,
    NikonCaptureEntryPlan,
    NikonCaptureRewriteRequest,
    NikonCaptureRewriteTagRequest,
    NikonCaptureTransactionPlan,
    build_nikon_capture_transaction_plan,
    plan_nikon_capture_transaction,
)
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "NikonCaptureDirectoryPlan",
    "NikonCaptureEditVersionPlan",
    "NikonCaptureEditVersionsPlan",
    "NikonCaptureEmissionGate",
    "NikonCaptureEntryPlan",
    "NikonCaptureRewriteRequest",
    "NikonCaptureRewriteTagRequest",
    "NikonCaptureTransactionPlan",
    "build_nikon_capture_read_graph",
    "build_nikon_capture_transaction_plan",
    "invoke_nikon_capture",
    "plan_nikon_capture_transaction",
]


def _emit_directory(
    directory: NikonCaptureDirectoryPlan | None,
    tags: list[ReadTag],
    ordinal_start: int,
) -> int:
    if directory is None:
        return ordinal_start
    ordinal = ordinal_start
    for entry in directory.entries:
        name = entry.tag_name or entry.tag_id_hex
        rendered: str | int = entry.payload_size or entry.tag_id_hex
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(rendered),
                provenance=_provenance(
                    group="NikonCapture",
                    table_name="Image::ExifTool::NikonCapture::Main",
                    tag_id=entry.tag_id_hex,
                    evidence_ids=entry.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
        ordinal += 1
    return ordinal


def build_nikon_capture_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_nikon_capture_transaction_plan(data)
    diagnostics: list[str] = [
        f"Nikon Capture package-local reader gate: {gate.code}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.append(f"Nikon Capture package-local reader status: {plan.status}")
    tags: list[ReadTag] = []
    ordinal = _emit_directory(plan.directory_plan, tags, 0)
    if plan.edit_versions_plan is not None:
        for version in plan.edit_versions_plan.versions:
            ordinal = _emit_directory(version.directory_plan, tags, ordinal)
    return _graph(source_file, tags, diagnostics)


def invoke_nikon_capture(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_nikon_capture_read_graph(_read_nikon_capture_payload(path, prefix), source_file)


def _read_nikon_capture_payload(path: Path, prefix: bytes) -> bytes:
    # NikonCapture.pm receives an in-memory Nikon Capture data block from Nikon
    # MakerNotes. Public dispatch can only see standalone blocks, so bound the
    # read by the little-endian directory size word when the magic is present.
    data = bytearray(prefix)
    with path.open("rb") as file:
        if len(data) < NIKON_CAPTURE_HEADER_SIZE:
            file.seek(len(data))
            data.extend(file.read(NIKON_CAPTURE_HEADER_SIZE - len(data)))
        if len(data) < NIKON_CAPTURE_HEADER_SIZE:
            return bytes(data)
        magic = int.from_bytes(data[:4], "little")
        if magic != NIKON_CAPTURE_MAGIC:
            size = path.stat().st_size
            file.seek(len(data))
            data.extend(file.read(size - len(data)))
            return bytes(data)
        declared_size = int.from_bytes(
            data[NIKON_CAPTURE_FIXED_HEADER_SIZE : NIKON_CAPTURE_FIXED_HEADER_SIZE + 4],
            "little",
        )
        target_size = NIKON_CAPTURE_FIXED_HEADER_SIZE + declared_size
        if len(data) >= target_size:
            return bytes(data[:target_size])
        file.seek(len(data))
        data.extend(file.read(target_size - len(data)))
    return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="nikon_capture",
        builder_ref="exifmodern.formats.nikon_capture:invoke_nikon_capture",
        patterns=(Pattern(0, b"\x40\xa9\x86\x7a"),),
        notes=("magic is NIKON_CAPTURE_MAGIC=0x7A86A940 read little-endian at offset 0",),
    ),
)
