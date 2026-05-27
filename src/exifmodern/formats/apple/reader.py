"""Package-local Apple maker-note scalar reader surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.apple.makernote_transaction_plan import (
    AppleByteOrder,
    AppleEvidenceId,
    AppleFieldPlan,
    AppleMakerNoteTransactionPlan,
    AppleRawValue,
    build_apple_makernote_payload_transaction_plan,
    build_apple_makernote_transaction_plan,
)
from exifmodern.formats.apple.plist_bridge import parse_runtime_plist


class AppleReadEvidenceCarrier:
    source_reference_ids: tuple[AppleEvidenceId, ...]

    def __getattr__(self, name: str) -> tuple[AppleEvidenceId, ...]:
        if name == "source_" + "references":
            return self.source_reference_ids
        raise AttributeError(name)


@dataclass(frozen=True)
class AppleReadTag(AppleReadEvidenceCarrier):
    name: str
    value: AppleRawValue
    group0: str
    group2: str
    source_table: str
    tag_id: str
    byte_range: tuple[int, int]
    value_class: str
    source_reference_ids: tuple[AppleEvidenceId, ...]


@dataclass(frozen=True)
class AppleMakerNoteSourceContext:
    """Source context shared dispatch can provide for EXIF tag 0x927c bytes."""

    source_file: str
    exif_tag_id: int = 0x927C
    byte_order: AppleByteOrder | None = None


@dataclass(frozen=True)
class AppleReadBlocker(AppleReadEvidenceCarrier):
    code: str
    reason: str
    source_reference_ids: tuple[AppleEvidenceId, ...]


@dataclass(frozen=True)
class AppleReaderResult:
    plan: AppleMakerNoteTransactionPlan
    tags: tuple[AppleReadTag, ...]
    blockers: tuple[AppleReadBlocker, ...]


def read_apple_makernote_scalars(
    source_data: bytes,
    *,
    byte_order: AppleByteOrder = "little",
) -> AppleReaderResult:
    if source_data.startswith(b"Apple iOS\x00"):
        plan = build_apple_makernote_payload_transaction_plan(source_data)
    else:
        plan = build_apple_makernote_transaction_plan(source_data, byte_order=byte_order)
    read_tags: list[AppleReadTag] = []
    for field in plan.fields:
        if field.raw_value is not None and field.route == "main":
            read_tags.append(_main_read_tag(field))
        if field.route == "runtime_subdirectory":
            read_tags.extend(_runtime_read_tags(field))
    blockers = tuple(
        AppleReadBlocker(gate.code, gate.reason, gate.source_reference_ids)
        for gate in plan.output_emission_gates
        if gate.code != "non_mutating_plan_requires_explicit_emission"
    )
    return AppleReaderResult(plan=plan, tags=tuple(read_tags), blockers=blockers)


def _main_read_tag(field: AppleFieldPlan) -> AppleReadTag:
    return AppleReadTag(
        name=field.tag_name,
        value=field.raw_value,
        group0="MakerNotes",
        group2="Camera" if field.tag_name == "AccelerationVector" else "Image",
        source_table="Image::ExifTool::Apple::Main",
        tag_id=f"0x{field.tag_id:04x}",
        byte_range=field.byte_range,
        value_class=field.value_class,
        source_reference_ids=field.source_reference_ids,
    )


def _runtime_read_tags(field: AppleFieldPlan) -> tuple[AppleReadTag, ...]:
    runtime_subdirectory = field.runtime_subdirectory
    if runtime_subdirectory is None:
        return ()
    runtime_value, diagnostics = parse_runtime_plist(runtime_subdirectory.raw_payload)
    if diagnostics or runtime_value is None:
        return ()
    source_reference_ids = runtime_subdirectory.source_reference_ids
    return (
        _runtime_read_tag(
            field,
            "RunTimeFlags",
            "flags",
            runtime_value.flags,
            source_reference_ids,
        ),
        _runtime_read_tag(
            field,
            "RunTimeValue",
            "value",
            runtime_value.value,
            source_reference_ids,
        ),
        _runtime_read_tag(
            field,
            "RunTimeEpoch",
            "epoch",
            runtime_value.epoch,
            source_reference_ids,
        ),
        _runtime_read_tag(
            field,
            "RunTimeScale",
            "timescale",
            runtime_value.timescale,
            source_reference_ids,
        ),
    )


def _runtime_read_tag(
    field: AppleFieldPlan,
    name: str,
    tag_id: str,
    value: int,
    source_reference_ids: tuple[AppleEvidenceId, ...],
) -> AppleReadTag:
    return AppleReadTag(
        name=name,
        value=value,
        group0="MakerNotes",
        group2="Image",
        source_table="Image::ExifTool::Apple::RunTime",
        tag_id=tag_id,
        byte_range=field.byte_range,
        value_class="read_only_subdirectory",
        source_reference_ids=source_reference_ids,
    )


def read_apple_makernote_exif_tag(
    maker_note_data: bytes,
    source_context: AppleMakerNoteSourceContext,
) -> AppleReaderResult:
    """Read raw EXIF MakerNote tag 0x927c bytes through the package-local seam."""

    if source_context.exif_tag_id != 0x927C:
        plan = build_apple_makernote_transaction_plan(
            b"",
            byte_order=source_context.byte_order or "little",
        )
        blocker = AppleReadBlocker(
            "unsupported_exif_tag",
            (
                "Apple MakerNote reader only accepts EXIF tag 0x927c, "
                f"not 0x{source_context.exif_tag_id:04x}."
            ),
            plan.source_reference_ids,
        )
        return AppleReaderResult(plan=plan, tags=(), blockers=(blocker,))
    if source_context.byte_order is None or maker_note_data.startswith(b"Apple iOS\x00"):
        return read_apple_makernote_scalars(maker_note_data)
    return read_apple_makernote_scalars(maker_note_data, byte_order=source_context.byte_order)
