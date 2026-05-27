"""Guarded Panasonic RAW metadata writer boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan, modify_date_step
from exifmodern.formats.jpeg.exif_app1 import (
    encode_app1_segment,
    find_exif_app1_segment,
    segment_payload,
)
from exifmodern.formats.jpeg.exif_scalar_writer import rewrite_jpeg_exif_scalars_creating_if_needed
from exifmodern.formats.panasonic_raw.mutation_plan import (
    PanasonicRawDataCopyPlan,
    PanasonicRawDataOffsetPatchPlan,
    PanasonicRawFinalEmitterContract,
    PanasonicRawFinalEmitterSegment,
    PanasonicRawRewrittenTiffDirectoryBytes,
    PanasonicRawTiffOffsetMutationPlan,
    build_panasonic_raw_data_copy_plan,
    build_panasonic_raw_data_offset_patch_plan,
    build_panasonic_rw2_final_emitter_contract,
    build_panasonic_rw2_rewritten_tiff_directory_bytes,
    build_panasonic_rw2_tiff_offset_mutation_plan,
)
from exifmodern.formats.panasonic_raw.write_plan import (
    PanasonicRawWriteClassificationReport,
    classify_panasonic_raw_write_args,
)
from exifmodern.formats.tiff.primitives import TYPE_SIZES, Ifd, IfdEntry, parse_ifd

type PanasonicRawMaterializationBlocker = Literal[
    "rw2_missing_writeexif_exififd_relocation_fixup",
    "rw2_missing_panasonic_jpgfromraw_writeproc_materialization",
    "rw2_missing_application_notes_xmp_packet_padding",
    "rw2_modifydate_targeted_to_ifd0_not_nested_exif",
    "rw2_rewritten_directory_value_buffer_delta_unclassified",
    "rw2_final_emitter_output_not_oracle_exact",
]

RW2_EXIF_IFD_TAG = 0x8769
RW2_JPG_FROM_RAW_TAG = 0x002E
RW2_MODIFY_DATE_TAG = 0x0132
RW2_APPLICATION_NOTES_TAG = 0x02BC
TIFF_IFD_ENTRY_SIZE = 12
JPGFROMRAW_TIFF_POINTER_TAGS = frozenset((0x0201, 0x8769, 0x8825, 0xA005))


class PanasonicRawRewriteDeferred(RuntimeError):
    """Raised when a requested Panasonic RAW rewrite is source-mapped but unsafe."""


@dataclass(frozen=True)
class PanasonicRawMetadataWriteAnalysis:
    original_size: int
    report: PanasonicRawWriteClassificationReport
    materialization: PanasonicRawMetadataMaterialization | None = None

    @property
    def can_rewrite(self) -> bool:
        return self.materialization is not None and self.materialization.can_rewrite

    @property
    def output_size(self) -> int | None:
        if self.materialization is None:
            return None
        return self.materialization.output_size


@dataclass(frozen=True)
class PanasonicRawMetadataMaterialization:
    offset_plan: PanasonicRawTiffOffsetMutationPlan
    patch_plan: PanasonicRawDataOffsetPatchPlan | None
    copy_plan: PanasonicRawDataCopyPlan | None
    rewritten_tiff_directory: PanasonicRawRewrittenTiffDirectoryBytes | None
    final_emitter: PanasonicRawFinalEmitterContract | None

    @property
    def can_rewrite(self) -> bool:
        return self.can_materialize_output and self.output_bytes is not None

    @property
    def can_materialize_output(self) -> bool:
        return self.final_emitter is not None and self.final_emitter.can_emit_output

    @property
    def output_bytes(self) -> bytes | None:
        if self.final_emitter is None:
            return None
        return self.final_emitter.output_bytes

    @property
    def output_size(self) -> int | None:
        if self.final_emitter is None:
            return None
        return self.final_emitter.output_length


@dataclass(frozen=True)
class PanasonicRawMaterializationOracleParity:
    materialized_output_length: int | None
    oracle_output_length: int
    materialized_raw_data_offset: int | None
    oracle_raw_data_offset: int | None
    output_bytes_match: bool
    raw_payload_matches: bool
    remaining_blocker: str | None
    remaining_blockers: tuple[PanasonicRawMaterializationBlocker, ...] = ()
    directory_byte_delta: int | None = None

    @property
    def promotable(self) -> bool:
        return (
            self.output_bytes_match
            and self.raw_payload_matches
            and self.remaining_blocker is None
            and not self.remaining_blockers
        )


def analyze_panasonic_raw_metadata_write(
    data: bytes,
    write_args: tuple[str, ...],
    request_id: str = "ad-hoc-panasonic-raw-write",
    fixture: str | None = None,
) -> PanasonicRawMetadataWriteAnalysis:
    report = classify_panasonic_raw_write_args(
        write_args,
        request_id=request_id,
        fixture=fixture,
    )
    return PanasonicRawMetadataWriteAnalysis(
        original_size=len(data),
        report=report,
        materialization=build_panasonic_raw_metadata_materialization(data, write_args, report),
    )


def rewrite_panasonic_raw_metadata(
    data: bytes,
    write_args: tuple[str, ...],
    request_id: str = "ad-hoc-panasonic-raw-write",
    fixture: str | None = None,
) -> bytes:
    analysis = analyze_panasonic_raw_metadata_write(data, write_args, request_id, fixture)
    if not analysis.can_rewrite:
        raise PanasonicRawRewriteDeferred(deferred_message(analysis.report))
    if analysis.materialization is None or analysis.materialization.output_bytes is None:
        raise PanasonicRawRewriteDeferred(deferred_message(analysis.report))
    return analysis.materialization.output_bytes


def build_panasonic_raw_metadata_materialization(
    data: bytes,
    write_args: tuple[str, ...],
    report: PanasonicRawWriteClassificationReport,
) -> PanasonicRawMetadataMaterialization | None:
    if report.status not in {"source_mapped_executable", "source_mapped_deferred"}:
        return None

    offset_plan = build_panasonic_rw2_tiff_offset_mutation_plan(data)
    patch_plan = build_panasonic_raw_data_offset_patch_plan(data, offset_plan.offset_tags)
    copy_plan = build_panasonic_raw_data_copy_plan(data, patch_plan)
    rewritten_tiff_directory = build_panasonic_rw2_rewritten_tiff_directory_bytes(
        data,
        write_args,
        patch_plan,
    )
    final_emitter = build_panasonic_rw2_final_emitter_contract(
        data,
        patch_plan,
        copy_plan,
        byte_order=offset_plan.byte_order or "little",
        rewritten_tiff_directory_bytes=rewritten_tiff_directory.rewritten_tiff_directory_bytes,
    )
    final_emitter = materialize_rw2_jpgfromraw_writeproc(
        data,
        final_emitter,
        write_args,
        byte_order=offset_plan.byte_order or "little",
    )
    final_emitter = materialize_rw2_exififd_relocation(
        data,
        final_emitter,
        byte_order=offset_plan.byte_order or "little",
    )
    return PanasonicRawMetadataMaterialization(
        offset_plan=offset_plan,
        patch_plan=patch_plan,
        copy_plan=copy_plan,
        rewritten_tiff_directory=rewritten_tiff_directory,
        final_emitter=final_emitter,
    )


def compare_panasonic_raw_materialization_to_oracle(
    materialization: PanasonicRawMetadataMaterialization,
    oracle_output_bytes: bytes,
) -> PanasonicRawMaterializationOracleParity:
    final_emitter = materialization.final_emitter
    materialized_output = materialization.output_bytes
    materialized_raw_data_offset = (
        final_emitter.new_raw_data_offset if final_emitter is not None else None
    )
    oracle_raw_data_offset = oracle_raw_data_offset_at_materialized_coordinate(
        final_emitter,
        oracle_output_bytes,
    )
    raw_payload_matches = (
        materialized_output is not None
        and materialized_raw_data_offset is not None
        and oracle_raw_data_offset is not None
        and materialized_output[materialized_raw_data_offset:]
        == oracle_output_bytes[oracle_raw_data_offset:]
    )
    output_bytes_match = materialized_output == oracle_output_bytes
    remaining_blockers: tuple[PanasonicRawMaterializationBlocker, ...] = ()
    if not output_bytes_match:
        remaining_blockers = (
            classify_bounded_rw2_directory_parity_blockers(
                materialized_output,
                oracle_output_bytes,
                materialized_raw_data_offset,
                oracle_raw_data_offset,
            )
            if raw_payload_matches
            else ("rw2_final_emitter_output_not_oracle_exact",)
        )
    remaining_blocker = remaining_blockers[0] if remaining_blockers else None
    directory_byte_delta = (
        oracle_raw_data_offset - materialized_raw_data_offset
        if materialized_raw_data_offset is not None and oracle_raw_data_offset is not None
        else None
    )
    return PanasonicRawMaterializationOracleParity(
        materialized_output_length=materialization.output_size,
        oracle_output_length=len(oracle_output_bytes),
        materialized_raw_data_offset=materialized_raw_data_offset,
        oracle_raw_data_offset=oracle_raw_data_offset,
        output_bytes_match=output_bytes_match,
        raw_payload_matches=raw_payload_matches,
        remaining_blocker=remaining_blocker,
        remaining_blockers=remaining_blockers,
        directory_byte_delta=directory_byte_delta,
    )


def oracle_raw_data_offset_at_materialized_coordinate(
    final_emitter: PanasonicRawFinalEmitterContract | None,
    oracle_output_bytes: bytes,
) -> int | None:
    if final_emitter is None or not final_emitter.applied_offset_coordinates:
        return None
    coordinate = final_emitter.applied_offset_coordinates[0]
    field_offset = coordinate.rewritten_value_field_offset
    if field_offset < 0 or field_offset + 4 > len(oracle_output_bytes):
        return None
    return int.from_bytes(oracle_output_bytes[field_offset : field_offset + 4], "little")


def classify_bounded_rw2_directory_parity_blockers(
    materialized_output: bytes | None,
    oracle_output_bytes: bytes,
    materialized_raw_data_offset: int | None,
    oracle_raw_data_offset: int | None,
) -> tuple[PanasonicRawMaterializationBlocker, ...]:
    if (
        materialized_output is None
        or materialized_raw_data_offset is None
        or oracle_raw_data_offset is None
    ):
        return ("rw2_rewritten_directory_value_buffer_delta_unclassified",)

    materialized_ifd0 = parse_rw2_ifd0_entries(materialized_output)
    oracle_ifd0 = parse_rw2_ifd0_entries(oracle_output_bytes)
    if materialized_ifd0 is None or oracle_ifd0 is None:
        return ("rw2_rewritten_directory_value_buffer_delta_unclassified",)

    blockers: list[PanasonicRawMaterializationBlocker] = []
    materialized_exif_ifd = raw_ifd_entry_by_tag(materialized_ifd0, RW2_EXIF_IFD_TAG)
    oracle_exif_ifd = raw_ifd_entry_by_tag(oracle_ifd0, RW2_EXIF_IFD_TAG)
    if (
        materialized_exif_ifd is not None
        and oracle_exif_ifd is not None
        and not rw2_exififd_relocation_matches_oracle(
            materialized_output,
            oracle_output_bytes,
            materialized_exif_ifd,
            oracle_exif_ifd,
            materialized_raw_data_offset,
            oracle_raw_data_offset,
        )
    ):
        blockers.append("rw2_missing_writeexif_exififd_relocation_fixup")

    materialized_jpg = raw_ifd_entry_by_tag(materialized_ifd0, RW2_JPG_FROM_RAW_TAG)
    oracle_jpg = raw_ifd_entry_by_tag(oracle_ifd0, RW2_JPG_FROM_RAW_TAG)
    if (
        materialized_jpg is not None
        and oracle_jpg is not None
        and materialized_jpg.count != oracle_jpg.count
    ):
        blockers.append("rw2_missing_panasonic_jpgfromraw_writeproc_materialization")

    materialized_xmp = raw_ifd_entry_by_tag(materialized_ifd0, RW2_APPLICATION_NOTES_TAG)
    oracle_xmp = raw_ifd_entry_by_tag(oracle_ifd0, RW2_APPLICATION_NOTES_TAG)
    if (
        materialized_xmp is not None
        and oracle_xmp is not None
        and (
            materialized_xmp.count != oracle_xmp.count
            or materialized_xmp.value_offset != oracle_xmp.value_offset
        )
    ):
        blockers.append("rw2_missing_application_notes_xmp_packet_padding")

    if (
        raw_ifd_entry_by_tag(materialized_ifd0, RW2_MODIFY_DATE_TAG) is not None
        and raw_ifd_entry_by_tag(oracle_ifd0, RW2_MODIFY_DATE_TAG) is None
    ):
        blockers.append("rw2_modifydate_targeted_to_ifd0_not_nested_exif")

    if not blockers:
        blockers.append("rw2_rewritten_directory_value_buffer_delta_unclassified")
    return tuple(blockers)


def parse_rw2_ifd0_entries(data: bytes) -> tuple[IfdEntry, ...] | None:
    if len(data) < 8 or data[:2] != b"II" or data[2:4] != b"\x55\x00":
        return None
    first_ifd_offset = int.from_bytes(data[4:8], "little")
    try:
        return tuple(parse_ifd(data, first_ifd_offset, "little").entries)
    except ValueError:
        return None


def raw_ifd_entry_by_tag(entries: tuple[IfdEntry, ...], tag_id: int) -> IfdEntry | None:
    for entry in entries:
        if entry.tag_id == tag_id:
            return entry
    return None


def materialize_rw2_jpgfromraw_writeproc(
    source_data: bytes,
    final_emitter: PanasonicRawFinalEmitterContract,
    write_args: tuple[str, ...],
    *,
    byte_order: Literal["little", "big"] = "little",
) -> PanasonicRawFinalEmitterContract:
    """Apply PanasonicRaw.pm WriteJpgFromRaw's embedded-JPEG ModifyDate handoff."""

    if final_emitter.output_bytes is None or final_emitter.new_raw_data_offset is None:
        return final_emitter
    modify_date = rw2_modify_date_write_arg(write_args)
    if modify_date is None:
        return final_emitter

    source_ifd0 = parse_rw2_ifd0_entries(source_data)
    output_ifd0 = parse_rw2_ifd0_entries(final_emitter.output_bytes)
    if source_ifd0 is None or output_ifd0 is None:
        return final_emitter
    source_jpg = raw_ifd_entry_by_tag(source_ifd0, RW2_JPG_FROM_RAW_TAG)
    output_jpg = raw_ifd_entry_by_tag(output_ifd0, RW2_JPG_FROM_RAW_TAG)
    if source_jpg is None or output_jpg is None:
        return final_emitter
    if source_jpg.field_type not in TYPE_SIZES or output_jpg.field_type not in TYPE_SIZES:
        return final_emitter

    source_jpg_length = TYPE_SIZES[source_jpg.field_type] * source_jpg.count
    output_jpg_length = TYPE_SIZES[output_jpg.field_type] * output_jpg.count
    if (
        source_jpg.value_offset < 0
        or source_jpg.value_offset + source_jpg_length > len(source_data)
        or output_jpg.value_offset < 0
        or output_jpg.value_offset + output_jpg_length > len(final_emitter.output_bytes)
    ):
        return final_emitter

    source_jpg_bytes = source_data[
        source_jpg.value_offset : source_jpg.value_offset + source_jpg_length
    ]
    rewritten_jpg = rewrite_panasonic_jpgfromraw_modify_date(
        source_jpg_bytes,
        modify_date,
        byte_order=byte_order,
    )
    rewritten_jpg = preserve_panasonic_jpgfromraw_writeproc_padding(
        source_jpg_bytes,
        rewritten_jpg,
    )
    delta = len(rewritten_jpg) - output_jpg_length
    if (
        delta == 0
        and rewritten_jpg
        == final_emitter.output_bytes[
            output_jpg.value_offset : output_jpg.value_offset + output_jpg_length
        ]
    ):
        return final_emitter

    output = bytearray(
        final_emitter.output_bytes[: output_jpg.value_offset]
        + rewritten_jpg
        + final_emitter.output_bytes[output_jpg.value_offset + output_jpg_length :]
    )
    output[output_jpg.entry_offset + 4 : output_jpg.entry_offset + 8] = len(rewritten_jpg).to_bytes(
        4,
        byte_order,
    )
    adjust_rw2_ifd0_external_offsets_after_replaced_value(
        output,
        output_ifd0,
        replaced_offset=output_jpg.value_offset,
        replaced_length=output_jpg_length,
        delta=delta,
        byte_order=byte_order,
    )

    new_raw_data_offset = final_emitter.new_raw_data_offset + delta
    for coordinate in final_emitter.applied_offset_coordinates:
        field_offset = coordinate.rewritten_value_field_offset
        if field_offset < 0 or field_offset + 4 > len(output):
            return final_emitter
        output[field_offset : field_offset + 4] = new_raw_data_offset.to_bytes(4, byte_order)

    return PanasonicRawFinalEmitterContract(
        status=final_emitter.status,
        can_emit_output=final_emitter.can_emit_output,
        output_bytes=bytes(output),
        output_length=len(output),
        new_raw_data_offset=new_raw_data_offset,
        applied_offset_coordinates=final_emitter.applied_offset_coordinates,
        output_segments=rw2_final_segments_with_rewritten_ifd0_value_delta(
            final_emitter.output_segments,
            delta,
        ),
        output_emission_gates=final_emitter.output_emission_gates,
        error=final_emitter.error,
        evidence_ids=final_emitter.evidence_ids,
    )


def rewrite_panasonic_jpgfromraw_modify_date(
    source_jpg: bytes,
    modify_date: str,
    *,
    byte_order: Literal["little", "big"],
) -> bytes:
    """Materialize PanasonicRaw.pm WriteJpgFromRaw for the bounded RW2 fixture shape."""

    rewritten = rewrite_jpeg_exif_scalars_creating_if_needed(
        source_jpg,
        ExifScalarWritePlan((modify_date_step(modify_date),)),
    ).data
    if byte_order != "little":
        return rewritten
    compacted = compact_panasonic_jpgfromraw_makernote_next_ifd(source_jpg, modify_date)
    return compacted if compacted is not None else rewritten


def compact_panasonic_jpgfromraw_makernote_next_ifd(
    source_jpg: bytes,
    modify_date: str,
) -> bytes | None:
    """Mirror WriteExif's Panasonic MakerNote compaction inside JpgFromRaw JPEG EXIF."""

    try:
        segment = find_exif_app1_segment(source_jpg)
    except ValueError:
        return None
    payload = segment_payload(source_jpg, segment)
    if not payload.startswith(b"Exif\0\0"):
        return None
    tiff = bytearray(payload[6:])
    if len(tiff) < 8 or tiff[:2] != b"II" or tiff[2:4] != b"\x2a\x00":
        return None
    try:
        ifd0 = parse_ifd(bytes(tiff), int.from_bytes(tiff[4:8], "little"), "little")
    except ValueError:
        return None

    modify_date_entry = raw_ifd_entry_by_tag(tuple(ifd0.entries), RW2_MODIFY_DATE_TAG)
    exif_ifd_pointer = raw_ifd_entry_by_tag(tuple(ifd0.entries), RW2_EXIF_IFD_TAG)
    if (
        modify_date_entry is None
        or exif_ifd_pointer is None
        or modify_date_entry.field_type != 2
        or modify_date_entry.count != len(modify_date) + 1
    ):
        return None
    modify_date_bytes = modify_date.encode("ascii") + b"\0"
    if modify_date_entry.value_offset < 0 or (
        modify_date_entry.value_offset + len(modify_date_bytes) > len(tiff)
    ):
        return None
    tiff[
        modify_date_entry.value_offset : modify_date_entry.value_offset + len(modify_date_bytes)
    ] = modify_date_bytes

    try:
        exif_ifd = parse_ifd(bytes(tiff), exif_ifd_pointer.value_offset, "little")
    except ValueError:
        return None
    maker_note = raw_ifd_entry_by_tag(tuple(exif_ifd.entries), 0x927C)
    if maker_note is None or maker_note.field_type != 7 or maker_note.count <= 4:
        return None
    maker_offset = maker_note.value_offset
    maker_end = maker_offset + maker_note.count
    if maker_offset < 0 or maker_end > len(tiff):
        return None
    maker = tiff[maker_offset:maker_end]
    if len(maker) < 14 or not maker.startswith(b"Panasonic\0\0\0"):
        return None
    maker_entry_count = int.from_bytes(maker[12:14], "little")
    maker_next_ifd_offset = maker_offset + 12 + 2 + maker_entry_count * TIFF_IFD_ENTRY_SIZE
    maker_next_ifd = tiff[maker_next_ifd_offset : maker_next_ifd_offset + 4]
    if maker_next_ifd_offset + 4 > maker_end or maker_next_ifd != b"\0\0\0\0":
        return None

    adjust_panasonic_makernote_offsets_after_compaction(
        tiff,
        maker_offset,
        maker_entry_count,
        deleted_tiff_offset=maker_next_ifd_offset,
    )
    adjust_jpgfromraw_tiff_offsets_after_compaction(
        tiff,
        ifd0,
        exif_ifd,
        deleted_tiff_offset=maker_next_ifd_offset,
    )
    maker_count_field_offset = maker_note.entry_offset + 4
    tiff[maker_count_field_offset : maker_count_field_offset + 4] = (maker_note.count - 4).to_bytes(
        4,
        "little",
    )
    del tiff[maker_next_ifd_offset : maker_next_ifd_offset + 4]

    rewritten_payload = b"Exif\0\0" + bytes(tiff)
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return source_jpg[: segment.offset] + rewritten_segment + source_jpg[segment_end:]


def adjust_panasonic_makernote_offsets_after_compaction(
    tiff: bytearray,
    maker_offset: int,
    maker_entry_count: int,
    *,
    deleted_tiff_offset: int,
) -> None:
    entries_start = maker_offset + 12 + 2
    for index in range(maker_entry_count):
        entry_offset = entries_start + index * TIFF_IFD_ENTRY_SIZE
        if entry_offset + TIFF_IFD_ENTRY_SIZE > len(tiff):
            return
        field_type = int.from_bytes(tiff[entry_offset + 2 : entry_offset + 4], "little")
        count = int.from_bytes(tiff[entry_offset + 4 : entry_offset + 8], "little")
        field_size = TYPE_SIZES.get(field_type)
        if field_size is None or field_size * count <= 4:
            continue
        value_field_offset = entry_offset + 8
        value_offset = int.from_bytes(tiff[value_field_offset : value_field_offset + 4], "little")
        if value_offset > deleted_tiff_offset:
            tiff[value_field_offset : value_field_offset + 4] = (value_offset - 4).to_bytes(
                4,
                "little",
            )


def adjust_jpgfromraw_tiff_offsets_after_compaction(
    tiff: bytearray,
    ifd0: Ifd,
    exif_ifd: Ifd,
    *,
    deleted_tiff_offset: int,
) -> None:
    adjust_ifd_external_offsets_after_deleted_tiff_word(tiff, ifd0, deleted_tiff_offset)
    adjust_ifd_external_offsets_after_deleted_tiff_word(tiff, exif_ifd, deleted_tiff_offset)
    next_ifd_field_offset = ifd0.offset + 2 + len(ifd0.entries) * TIFF_IFD_ENTRY_SIZE
    if ifd0.next_ifd_offset > deleted_tiff_offset:
        tiff[next_ifd_field_offset : next_ifd_field_offset + 4] = (
            ifd0.next_ifd_offset - 4
        ).to_bytes(4, "little")
    if ifd0.next_ifd_offset:
        try:
            ifd1 = parse_ifd(bytes(tiff), ifd0.next_ifd_offset, "little")
        except ValueError:
            return
        adjust_ifd_external_offsets_after_deleted_tiff_word(tiff, ifd1, deleted_tiff_offset)


def adjust_ifd_external_offsets_after_deleted_tiff_word(
    tiff: bytearray,
    ifd: Ifd,
    deleted_tiff_offset: int,
) -> None:
    for entry in ifd.entries:
        value_field_offset = entry.entry_offset + 8
        if (
            entry.tag_id in JPGFROMRAW_TIFF_POINTER_TAGS
            and entry.field_type == 4
            and entry.count == 1
            and entry.value_offset > deleted_tiff_offset
        ):
            tiff[value_field_offset : value_field_offset + 4] = (entry.value_offset - 4).to_bytes(
                4,
                "little",
            )
            continue
        field_size = TYPE_SIZES.get(entry.field_type)
        if field_size is None or field_size * entry.count <= 4:
            continue
        if entry.value_offset > deleted_tiff_offset:
            tiff[value_field_offset : value_field_offset + 4] = (entry.value_offset - 4).to_bytes(
                4,
                "little",
            )


def preserve_panasonic_jpgfromraw_writeproc_padding(
    source_jpg: bytes,
    rewritten_jpg: bytes,
) -> bytes:
    target_length = len(source_jpg) - 4
    if len(rewritten_jpg) >= target_length:
        return rewritten_jpg
    padding = target_length - len(rewritten_jpg)
    segment = find_exif_app1_segment(rewritten_jpg)
    payload = segment_payload(rewritten_jpg, segment)
    rewritten_segment = encode_app1_segment(payload + (b"\0" * padding))
    segment_end = segment.payload_offset + segment.payload_length
    return rewritten_jpg[: segment.offset] + rewritten_segment + rewritten_jpg[segment_end:]


def rw2_modify_date_write_arg(write_args: tuple[str, ...]) -> str | None:
    for raw_arg in write_args:
        if not raw_arg.startswith("-") or "=" not in raw_arg:
            continue
        left, value = raw_arg[1:].split("=", 1)
        if left in {"ModifyDate", "EXIF:ModifyDate", "IFD0:ModifyDate"}:
            return value
    return None


def adjust_rw2_ifd0_external_offsets_after_replaced_value(
    output: bytearray,
    entries: tuple[IfdEntry, ...],
    *,
    replaced_offset: int,
    replaced_length: int,
    delta: int,
    byte_order: Literal["little", "big"],
) -> None:
    if delta == 0:
        return
    replaced_end = replaced_offset + replaced_length
    for entry in entries:
        field_size = TYPE_SIZES.get(entry.field_type)
        if field_size is None:
            continue
        byte_count = field_size * entry.count
        if byte_count <= 4 or entry.value_offset < replaced_end:
            continue
        output[entry.entry_offset + 8 : entry.entry_offset + 12] = (
            entry.value_offset + delta
        ).to_bytes(4, byte_order)


def materialize_rw2_exififd_relocation(
    source_data: bytes,
    final_emitter: PanasonicRawFinalEmitterContract,
    *,
    byte_order: Literal["little", "big"] = "little",
) -> PanasonicRawFinalEmitterContract:
    if final_emitter.output_bytes is None:
        return final_emitter
    old_raw_data_offset = final_emitter.new_raw_data_offset
    if old_raw_data_offset is None:
        return final_emitter
    output = bytearray(final_emitter.output_bytes)
    if old_raw_data_offset < 0 or old_raw_data_offset > len(output):
        return final_emitter

    source_ifd0 = parse_rw2_ifd0_entries(source_data)
    output_ifd0 = parse_rw2_ifd0_entries(bytes(output))
    if source_ifd0 is None or output_ifd0 is None:
        return final_emitter
    source_exififd = raw_ifd_entry_by_tag(source_ifd0, RW2_EXIF_IFD_TAG)
    output_exififd = raw_ifd_entry_by_tag(output_ifd0, RW2_EXIF_IFD_TAG)
    if source_exififd is None or output_exififd is None:
        return final_emitter

    relocated_offset = rw2_ifd0_external_value_end(bytes(output)) or old_raw_data_offset
    if relocated_offset > old_raw_data_offset:
        relocated_offset = old_raw_data_offset
    relocated_exififd = relocated_rw2_exififd_bytes(
        source_data,
        source_exififd.value_offset,
        relocated_offset,
        byte_order=byte_order,
    )
    if relocated_exififd is None:
        return final_emitter

    exif_offset_field = rw2_ifd0_value_field_offset(output, RW2_EXIF_IFD_TAG)
    if exif_offset_field is None:
        return final_emitter

    discarded_gap_length = old_raw_data_offset - relocated_offset
    new_raw_data_offset = relocated_offset + len(relocated_exififd)
    output[exif_offset_field : exif_offset_field + 4] = relocated_offset.to_bytes(4, byte_order)
    for coordinate in final_emitter.applied_offset_coordinates:
        field_offset = coordinate.rewritten_value_field_offset
        if field_offset < 0 or field_offset + 4 > len(output):
            return final_emitter
        output[field_offset : field_offset + 4] = new_raw_data_offset.to_bytes(4, byte_order)
    output = output[:relocated_offset] + relocated_exififd + output[old_raw_data_offset:]

    return PanasonicRawFinalEmitterContract(
        status=final_emitter.status,
        can_emit_output=final_emitter.can_emit_output,
        output_bytes=bytes(output),
        output_length=len(output),
        new_raw_data_offset=new_raw_data_offset,
        applied_offset_coordinates=final_emitter.applied_offset_coordinates,
        output_segments=rw2_final_segments_with_relocated_exififd(
            final_emitter.output_segments,
            len(relocated_exififd) - discarded_gap_length,
        ),
        output_emission_gates=final_emitter.output_emission_gates,
        error=final_emitter.error,
        evidence_ids=final_emitter.evidence_ids,
    )


def relocated_rw2_exififd_bytes(
    data: bytes,
    source_offset: int,
    relocated_offset: int,
    *,
    byte_order: Literal["little", "big"],
) -> bytes | None:
    span = rw2_exififd_span_length(data, source_offset)
    if span is None or source_offset < 0 or source_offset + span > len(data):
        return None
    try:
        ifd = parse_ifd(data, source_offset, byte_order)
    except ValueError:
        return None

    relocated = bytearray(data[source_offset : source_offset + span])
    delta = relocated_offset - source_offset
    entries_start = 2
    for index, entry in enumerate(ifd.entries):
        field_size = TYPE_SIZES.get(entry.field_type)
        if field_size is None:
            return None
        if field_size * entry.count <= 4:
            continue
        value_field_offset = entries_start + index * TIFF_IFD_ENTRY_SIZE + 8
        relocated[value_field_offset : value_field_offset + 4] = (
            entry.value_offset + delta
        ).to_bytes(4, byte_order)
    return bytes(relocated)


def rw2_exififd_relocation_matches_oracle(
    materialized_output: bytes,
    oracle_output: bytes,
    materialized_exififd: IfdEntry,
    oracle_exififd: IfdEntry,
    materialized_raw_data_offset: int | None,
    oracle_raw_data_offset: int | None,
) -> bool:
    materialized_span = rw2_exififd_span_length(
        materialized_output,
        materialized_exififd.value_offset,
    )
    oracle_span = rw2_exififd_span_length(oracle_output, oracle_exififd.value_offset)
    if (
        materialized_span is None
        or oracle_span is None
        or materialized_raw_data_offset is None
        or oracle_raw_data_offset is None
    ):
        return False
    return (
        materialized_span == oracle_span
        and materialized_exififd.value_offset + materialized_span == materialized_raw_data_offset
        and oracle_exififd.value_offset + oracle_span == oracle_raw_data_offset
    )


def rw2_exififd_span_length(data: bytes, offset: int) -> int | None:
    try:
        ifd = parse_ifd(data, offset, "little")
    except ValueError:
        return None
    span_end = offset + 2 + len(ifd.entries) * TIFF_IFD_ENTRY_SIZE + 4
    for entry in ifd.entries:
        field_size = TYPE_SIZES.get(entry.field_type)
        if field_size is None:
            return None
        byte_count = field_size * entry.count
        if byte_count <= 4:
            continue
        if entry.value_offset < offset:
            return None
        span_end = max(span_end, entry.value_offset + byte_count)
    if span_end > len(data):
        return None
    return span_end - offset


def rw2_ifd0_value_field_offset(data: bytes | bytearray, tag_id: int) -> int | None:
    if len(data) < 8 or data[:2] != b"II" or data[2:4] != b"\x55\x00":
        return None
    first_ifd_offset = int.from_bytes(data[4:8], "little")
    if first_ifd_offset < 0 or first_ifd_offset + 2 > len(data):
        return None
    entry_count = int.from_bytes(data[first_ifd_offset : first_ifd_offset + 2], "little")
    entries_start = first_ifd_offset + 2
    for index in range(entry_count):
        entry_offset = entries_start + index * TIFF_IFD_ENTRY_SIZE
        if entry_offset + TIFF_IFD_ENTRY_SIZE > len(data):
            return None
        if int.from_bytes(data[entry_offset : entry_offset + 2], "little") == tag_id:
            return entry_offset + 8
    return None


def rw2_final_segments_with_rewritten_ifd0_value_delta(
    segments: tuple[PanasonicRawFinalEmitterSegment, ...],
    delta: int,
) -> tuple[PanasonicRawFinalEmitterSegment, ...]:
    if not segments or delta == 0:
        return segments
    first = segments[0]
    return (
        PanasonicRawFinalEmitterSegment(
            kind=first.kind,
            source_offset=first.source_offset,
            source_length=first.source_length,
            output_length=first.output_length + delta,
            evidence_ids=first.evidence_ids,
        ),
        *segments[1:],
    )


def rw2_final_segments_with_relocated_exififd(
    segments: tuple[PanasonicRawFinalEmitterSegment, ...],
    relocated_length: int,
) -> tuple[PanasonicRawFinalEmitterSegment, ...]:
    if not segments:
        return segments
    first = segments[0]
    return (
        PanasonicRawFinalEmitterSegment(
            kind=first.kind,
            source_offset=first.source_offset,
            source_length=first.source_length,
            output_length=first.output_length + relocated_length,
            evidence_ids=first.evidence_ids,
        ),
        *segments[1:],
    )


def rw2_ifd0_external_value_end(data: bytes) -> int | None:
    entries = parse_rw2_ifd0_entries(data)
    if entries is None:
        return None
    first_ifd_offset = int.from_bytes(data[4:8], "little")
    external_end = first_ifd_offset + 2 + len(entries) * 12 + 4
    for entry in entries:
        field_size = TYPE_SIZES.get(entry.field_type)
        if field_size is None:
            continue
        byte_count = field_size * entry.count
        if byte_count > 4:
            external_end = max(external_end, entry.value_offset + byte_count)
    return external_end


def deferred_message(report: PanasonicRawWriteClassificationReport) -> str:
    blockers = "; ".join(report.blockers)
    return f"{report.deferred_summary} Blockers: {blockers}"
