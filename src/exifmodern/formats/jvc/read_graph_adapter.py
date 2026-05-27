"""JVC MakerNote adapters for the shared read graph contract."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.jvc.makernote_transaction_plan import (
    JvcByteOrder,
    JvcFieldPlan,
    JvcMakerNoteTransactionPlan,
    JvcNoteKind,
    JvcRawValue,
    build_jvc_makernote_transaction_plan,
)
from exifmodern.formats.public_payload import read_public_document_payload
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue


@dataclass(frozen=True)
class JvcMakerNoteSourceContext:
    source_file: str
    byte_order: JvcByteOrder = "little"
    exif_tag_id: int = 0x927C
    note_kind: JvcNoteKind = "auto"
    preserve_unknown_text_tags: bool = False
    maker_note_value_offset: int | None = None


def build_jvc_makernote_read_graph(
    maker_note_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
    *,
    note_kind: JvcNoteKind = "auto",
    byte_order: JvcByteOrder = "little",
    preserve_unknown_text_tags: bool = False,
    value_base_offset: int = 0,
) -> ReadGraph:
    directory_data = _maker_note_directory_data(maker_note_data)
    plan = build_jvc_makernote_transaction_plan(
        directory_data,
        note_kind=note_kind,
        byte_order=_resolved_byte_order(directory_data, byte_order),
        value_base_offset=_directory_value_base_offset(maker_note_data, value_base_offset),
        preserve_unknown_text_tags=preserve_unknown_text_tags,
        allow_output_emission=True,
    )
    return jvc_makernote_transaction_plan_to_read_graph(plan, source_file, generated_at_epoch)


def build_jvc_makernote_read_graph_from_file(
    path: Path,
    source_file: str | None = None,
    generated_at_epoch: int | None = None,
    *,
    note_kind: JvcNoteKind = "auto",
    byte_order: JvcByteOrder = "little",
    preserve_unknown_text_tags: bool = False,
    value_base_offset: int = 0,
) -> ReadGraph:
    maker_note_data = read_public_document_payload(path)
    if maker_note_data is None:
        display_source = path.as_posix() if source_file is None else source_file
        return ReadGraph(
            schema_version=1,
            generated_at_epoch=_epoch(generated_at_epoch),
            source_file=display_source,
            tags=[],
            diagnostics=["JVC MakerNote source exceeds public materialization limit."],
        )
    return build_jvc_makernote_read_graph(
        maker_note_data,
        path.as_posix() if source_file is None else source_file,
        generated_at_epoch,
        note_kind=note_kind,
        byte_order=byte_order,
        preserve_unknown_text_tags=preserve_unknown_text_tags,
        value_base_offset=value_base_offset,
    )


def build_jvc_makernote_read_graph_from_jpeg_file(
    path: Path,
    source_file: str | None = None,
    generated_at_epoch: int | None = None,
    *,
    preserve_unknown_text_tags: bool = False,
) -> ReadGraph:
    from exifmodern.formats.jpeg.container import inspect_jpeg_jvc_maker_note_bridge

    display_source = path.as_posix() if source_file is None else source_file
    bridge = inspect_jpeg_jvc_maker_note_bridge(path)
    if not bridge.ready or bridge.context is None:
        return ReadGraph(
            schema_version=1,
            generated_at_epoch=_epoch(generated_at_epoch),
            source_file=display_source,
            tags=[],
            diagnostics=[
                f"JVC JPEG MakerNote bridge {bridge.status}: {message}"
                for message in bridge.diagnostics
            ],
        )
    return build_jvc_makernote_read_graph_from_exif_tag(
        bridge.raw_maker_note,
        JvcMakerNoteSourceContext(
            display_source,
            byte_order=bridge.context.byte_order,
            note_kind=bridge.context.note_kind,
            preserve_unknown_text_tags=preserve_unknown_text_tags,
            maker_note_value_offset=bridge.context.maker_note_tiff_offset,
        ),
        generated_at_epoch,
    )


def build_jvc_makernote_read_graph_from_exif_tag(
    maker_note_data: bytes,
    source_context: JvcMakerNoteSourceContext,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    if source_context.exif_tag_id != 0x927C:
        plan = build_jvc_makernote_transaction_plan(
            b"",
            note_kind=source_context.note_kind,
            byte_order=source_context.byte_order,
            value_base_offset=_context_value_base_offset(source_context),
            preserve_unknown_text_tags=source_context.preserve_unknown_text_tags,
            allow_output_emission=True,
        )
        return ReadGraph(
            schema_version=1,
            generated_at_epoch=_epoch(generated_at_epoch),
            source_file=source_context.source_file,
            tags=[],
            diagnostics=[
                "JVC package-local reader gate: unsupported_exif_tag: "
                f"expected EXIF tag 0x927c, got 0x{source_context.exif_tag_id:04x}",
                *_diagnostics(plan),
            ],
        )
    return build_jvc_makernote_read_graph(
        maker_note_data,
        source_context.source_file,
        generated_at_epoch,
        note_kind=source_context.note_kind,
        byte_order=source_context.byte_order,
        preserve_unknown_text_tags=source_context.preserve_unknown_text_tags,
        value_base_offset=_context_value_base_offset(source_context),
    )


def jvc_makernote_transaction_plan_to_read_graph(
    plan: JvcMakerNoteTransactionPlan,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=_epoch(generated_at_epoch),
        source_file=source_file,
        tags=[_field_tag(field) for field in plan.fields],
        diagnostics=_diagnostics(plan),
    )


def _field_tag(field: JvcFieldPlan) -> ReadTag:
    tag_id = f"0x{field.tag_key:04x}" if isinstance(field.tag_key, int) else field.tag_key
    return ReadTag(
        name=field.tag_name,
        value=_render_value(field),
        provenance=TagProvenance(
            group="MakerNotes",
            table_name=field.table,
            tag_id=tag_id,
            source=_evidence_anchor_text(field.evidence_ids[0]),
            family_0_group="MakerNotes",
            family_1_group="JVC",
            family_2_group="Camera",
        ),
        schema=None,
    )


def _render_value(field: JvcFieldPlan) -> TagValue:
    value = field.interpreted_value
    if value is None:
        value = field.raw_value
    return _tag_value(value)


def _tag_value(value: JvcRawValue) -> TagValue:
    if isinstance(value, bytes):
        return BinaryTagValue(value)
    return value


def _diagnostics(plan: JvcMakerNoteTransactionPlan) -> list[str]:
    return [
        f"JVC package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if gate.code != "non_mutating_plan_requires_explicit_emission"
    ]


def _evidence_anchor_text(reference: str) -> str:
    return reference


def _epoch(generated_at_epoch: int | None) -> int:
    return generated_at_epoch if generated_at_epoch is not None else int(time.time())


def _maker_note_directory_data(maker_note_data: bytes) -> bytes:
    if maker_note_data.startswith(b"JVC "):
        return maker_note_data[4:]
    return maker_note_data


def _directory_value_base_offset(maker_note_data: bytes, value_base_offset: int) -> int:
    if maker_note_data.startswith(b"JVC ") and value_base_offset:
        return value_base_offset + 4
    return value_base_offset


def _context_value_base_offset(source_context: JvcMakerNoteSourceContext) -> int:
    if source_context.maker_note_value_offset is None:
        return 0
    return source_context.maker_note_value_offset


def _resolved_byte_order(
    directory_data: bytes,
    fallback_byte_order: JvcByteOrder,
) -> JvcByteOrder:
    if directory_data.startswith(b"VER:") or len(directory_data) < 2:
        return fallback_byte_order
    little_count = int.from_bytes(directory_data[:2], "little")
    big_count = int.from_bytes(directory_data[:2], "big")
    little_fits = _ifd_entry_region_fits(directory_data, little_count)
    big_fits = _ifd_entry_region_fits(directory_data, big_count)
    if big_fits and not little_fits:
        return "big"
    if little_fits and not big_fits:
        return "little"
    return fallback_byte_order


def _ifd_entry_region_fits(directory_data: bytes, entry_count: int) -> bool:
    return 2 + (entry_count * 12) + 4 <= len(directory_data)
