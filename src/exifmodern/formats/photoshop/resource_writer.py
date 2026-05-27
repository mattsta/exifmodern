"""Guarded Photoshop PSD image resource mutation planning.

The source-backed PSD behavior is classified in
:mod:`exifmodern.formats.photoshop.write_plan`.  Byte mutation is still gated
for real PSD fixtures until nested IPTC, XMP, and embedded EXIF writers are
integrated.  This module exposes executable IRB entry replacement, deletion,
insertion, and section-size repair primitives only for synthetic resource
sections.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.photoshop.image_resources import (
    PHOTOSHOP_WRITABLE_IRB_SIGNATURE,
    PhotoshopImageResourceBlock,
    PhotoshopImageResourceEntry,
    encode_image_resource_section,
    encoded_image_resource_entry_length,
    parse_image_resource_blocks,
    validate_resource_id,
)
from exifmodern.formats.photoshop.write_plan import WRITE_PHOTOSHOP_SOURCE_ID

type PhotoshopImageResourceReplacementAction = Literal["preserve", "replace"]
type PhotoshopImageResourceMutationAction = Literal["preserve", "replace", "delete", "insert"]
type PhotoshopImageResourceReplacementBlockerCode = Literal[
    "not_source_backed",
    "real_psd_fixture_resource_mutation_gated",
    "duplicate_replacement_request",
    "missing_target_resource",
    "duplicate_target_resource",
    "non_8bim_target_resource",
]
type PhotoshopImageResourceMutationBlockerCode = Literal[
    "not_source_backed",
    "real_psd_fixture_resource_mutation_gated",
    "duplicate_mutation_request",
    "missing_delete_target_resource",
    "missing_replace_target_resource",
    "duplicate_target_resource",
    "non_8bim_target_resource",
    "insert_target_resource_exists",
]


class PhotoshopPSDUnsupportedWriteError(RuntimeError):
    """Raised when a PSD resource write is source-backed but not safely writable."""


@dataclass(frozen=True)
class PhotoshopImageResourceReplacement:
    resource_id: int
    data: bytes
    name: bytes | None = None


@dataclass(frozen=True)
class PhotoshopImageResourceMutation:
    action: Literal["replace", "delete", "insert"]
    resource_id: int
    data: bytes = b""
    name: bytes | None = None


@dataclass(frozen=True)
class PhotoshopImageResourceReplacementStep:
    action: PhotoshopImageResourceReplacementAction
    resource_id: int
    signature: bytes
    source_entry_start: int
    source_entry_length: int
    source_data_offset: int
    source_data_size: int
    source_data_padding_size: int
    output_entry_start: int
    output_entry_length: int
    output_data_size: int
    output_data_padding_size: int


@dataclass(frozen=True)
class PhotoshopImageResourceMutationStep:
    action: PhotoshopImageResourceMutationAction
    resource_id: int
    signature: bytes
    source_entry_start: int | None
    source_entry_length: int
    source_data_offset: int | None
    source_data_size: int
    source_data_padding_size: int
    output_entry_start: int | None
    output_entry_length: int
    output_data_size: int
    output_data_padding_size: int


@dataclass(frozen=True)
class PhotoshopImageResourceReplacementPlan:
    source_length: int
    output_length: int
    source_backed: bool
    synthetic_resource_section: bool
    can_write_bytes: bool
    blocker_codes: tuple[PhotoshopImageResourceReplacementBlockerCode, ...]
    steps: tuple[PhotoshopImageResourceReplacementStep, ...]
    entries: tuple[PhotoshopImageResourceEntry, ...]
    source_reference_ids: tuple[str, ...]

    @property
    def replacement_count(self) -> int:
        return sum(1 for step in self.steps if step.action == "replace")


@dataclass(frozen=True)
class PhotoshopImageResourceMutationPlan:
    source_length: int
    output_length: int
    output_length_field: bytes
    source_backed: bool
    synthetic_resource_section: bool
    can_write_bytes: bool
    blocker_codes: tuple[PhotoshopImageResourceMutationBlockerCode, ...]
    steps: tuple[PhotoshopImageResourceMutationStep, ...]
    entries: tuple[PhotoshopImageResourceEntry, ...]
    source_reference_ids: tuple[str, ...]

    @property
    def replacement_count(self) -> int:
        return sum(1 for step in self.steps if step.action == "replace")

    @property
    def deletion_count(self) -> int:
        return sum(1 for step in self.steps if step.action == "delete")

    @property
    def insertion_count(self) -> int:
        return sum(1 for step in self.steps if step.action == "insert")


def plan_image_resource_entry_replacements(
    resource_section: bytes,
    replacements: Sequence[PhotoshopImageResourceReplacement],
    *,
    source_backed: bool,
    synthetic_resource_section: bool,
    real_psd_resource_mutation_enabled: bool = False,
) -> PhotoshopImageResourceReplacementPlan:
    replacement_lookup, duplicate_replacement_ids = replacement_map(replacements)
    blocks = parse_image_resource_blocks(resource_section)
    blocker_codes = image_resource_replacement_blockers(
        blocks=tuple((block.resource_id, block.signature) for block in blocks),
        replacement_ids=tuple(replacement_lookup),
        duplicate_replacement_ids=duplicate_replacement_ids,
        source_backed=source_backed,
        resource_mutation_enabled=synthetic_resource_section or real_psd_resource_mutation_enabled,
    )

    output_position = 0
    steps: list[PhotoshopImageResourceReplacementStep] = []
    planned_entries: list[PhotoshopImageResourceEntry] = []
    for block in blocks:
        replacement = replacement_lookup.get(block.resource_id)
        should_replace = (
            replacement is not None
            and block.signature == PHOTOSHOP_WRITABLE_IRB_SIGNATURE
            and count_resource_id(blocks, block.resource_id) == 1
            and block.resource_id not in duplicate_replacement_ids
        )
        if should_replace and replacement is not None:
            output_entry = PhotoshopImageResourceEntry(
                signature=block.signature,
                resource_id=block.resource_id,
                name=block.name if replacement.name is None else replacement.name,
                data=replacement.data,
            )
            action: PhotoshopImageResourceReplacementAction = "replace"
        else:
            output_entry = block.to_entry()
            action = "preserve"

        output_entry_length = encoded_image_resource_entry_length(output_entry)
        planned_entries.append(output_entry)
        steps.append(
            PhotoshopImageResourceReplacementStep(
                action=action,
                resource_id=block.resource_id,
                signature=block.signature,
                source_entry_start=block.entry_start,
                source_entry_length=block.entry_length,
                source_data_offset=block.data_offset,
                source_data_size=block.data_size,
                source_data_padding_size=block.data_padding_size,
                output_entry_start=output_position,
                output_entry_length=output_entry_length,
                output_data_size=len(output_entry.data),
                output_data_padding_size=len(output_entry.data) & 0x01,
            )
        )
        output_position += output_entry_length

    return PhotoshopImageResourceReplacementPlan(
        source_length=len(resource_section),
        output_length=output_position,
        source_backed=source_backed,
        synthetic_resource_section=synthetic_resource_section,
        can_write_bytes=not blocker_codes,
        blocker_codes=blocker_codes,
        steps=tuple(steps),
        entries=tuple(planned_entries),
        source_reference_ids=(WRITE_PHOTOSHOP_SOURCE_ID,),
    )


def apply_image_resource_entry_replacements(
    resource_section: bytes,
    replacements: Sequence[PhotoshopImageResourceReplacement],
    *,
    source_backed: bool,
    synthetic_resource_section: bool,
    real_psd_resource_mutation_enabled: bool = False,
) -> bytes:
    plan = plan_image_resource_entry_replacements(
        resource_section,
        replacements,
        source_backed=source_backed,
        synthetic_resource_section=synthetic_resource_section,
        real_psd_resource_mutation_enabled=real_psd_resource_mutation_enabled,
    )
    if not plan.can_write_bytes:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop image resource byte rewrite is limited to source-backed synthetic "
            "resource sections until nested PSD resource writers are integrated: "
            + ", ".join(plan.blocker_codes)
        )
    return encode_image_resource_section(plan.entries)


def replacement_map(
    replacements: Sequence[PhotoshopImageResourceReplacement],
) -> tuple[dict[int, PhotoshopImageResourceReplacement], tuple[int, ...]]:
    replacement_lookup: dict[int, PhotoshopImageResourceReplacement] = {}
    seen_resource_ids: set[int] = set()
    duplicate_resource_ids: list[int] = []
    for replacement in replacements:
        validate_resource_id(replacement.resource_id)
        if replacement.resource_id in seen_resource_ids:
            duplicate_resource_ids.append(replacement.resource_id)
            continue
        seen_resource_ids.add(replacement.resource_id)
        replacement_lookup[replacement.resource_id] = replacement
    return replacement_lookup, tuple(duplicate_resource_ids)


def plan_image_resource_entry_mutations(
    resource_section: bytes,
    mutations: Sequence[PhotoshopImageResourceMutation],
    *,
    source_backed: bool,
    synthetic_resource_section: bool,
    real_psd_resource_mutation_enabled: bool = False,
) -> PhotoshopImageResourceMutationPlan:
    mutation_lookup, duplicate_mutation_ids = mutation_map(mutations)
    blocks = parse_image_resource_blocks(resource_section)
    blocker_codes = image_resource_mutation_blockers(
        blocks=tuple((block.resource_id, block.signature) for block in blocks),
        mutations=tuple(mutation_lookup.values()),
        duplicate_mutation_ids=duplicate_mutation_ids,
        source_backed=source_backed,
        resource_mutation_enabled=synthetic_resource_section or real_psd_resource_mutation_enabled,
    )

    output_position = 0
    steps: list[PhotoshopImageResourceMutationStep] = []
    planned_entries: list[PhotoshopImageResourceEntry] = []
    for block in blocks:
        mutation = mutation_lookup.get(block.resource_id)
        can_mutate_existing = (
            mutation is not None
            and block.signature == PHOTOSHOP_WRITABLE_IRB_SIGNATURE
            and count_resource_id(blocks, block.resource_id) == 1
            and block.resource_id not in duplicate_mutation_ids
        )
        if can_mutate_existing and mutation is not None and mutation.action == "delete":
            steps.append(deleted_resource_step(block))
            continue
        if can_mutate_existing and mutation is not None and mutation.action == "replace":
            output_entry = PhotoshopImageResourceEntry(
                signature=block.signature,
                resource_id=block.resource_id,
                name=block.name if mutation.name is None else mutation.name,
                data=mutation.data,
            )
            action: PhotoshopImageResourceReplacementAction = "replace"
        else:
            output_entry = block.to_entry()
            action = "preserve"

        output_entry_length = encoded_image_resource_entry_length(output_entry)
        planned_entries.append(output_entry)
        steps.append(
            existing_resource_step(
                block,
                action=action,
                output_entry_start=output_position,
                output_entry_length=output_entry_length,
                output_data_size=len(output_entry.data),
            )
        )
        output_position += output_entry_length

    for insertion in sorted_insertions(mutation_lookup):
        insert_entry = inserted_resource_entry(insertion)
        insert_entry_length = encoded_image_resource_entry_length(insert_entry)
        planned_entries.append(insert_entry)
        steps.append(
            inserted_resource_step(
                insert_entry,
                output_entry_start=output_position,
                output_entry_length=insert_entry_length,
            )
        )
        output_position += insert_entry_length

    return PhotoshopImageResourceMutationPlan(
        source_length=len(resource_section),
        output_length=output_position,
        output_length_field=encode_image_resource_section_length(output_position),
        source_backed=source_backed,
        synthetic_resource_section=synthetic_resource_section,
        can_write_bytes=not blocker_codes,
        blocker_codes=blocker_codes,
        steps=tuple(steps),
        entries=tuple(planned_entries),
        source_reference_ids=(WRITE_PHOTOSHOP_SOURCE_ID,),
    )


def apply_image_resource_entry_mutations(
    resource_section: bytes,
    mutations: Sequence[PhotoshopImageResourceMutation],
    *,
    source_backed: bool,
    synthetic_resource_section: bool,
    real_psd_resource_mutation_enabled: bool = False,
) -> bytes:
    plan = plan_image_resource_entry_mutations(
        resource_section,
        mutations,
        source_backed=source_backed,
        synthetic_resource_section=synthetic_resource_section,
        real_psd_resource_mutation_enabled=real_psd_resource_mutation_enabled,
    )
    if not plan.can_write_bytes:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop image resource byte rewrite is limited to source-backed synthetic "
            "resource sections until nested PSD resource writers are integrated: "
            + ", ".join(plan.blocker_codes)
        )
    return encode_image_resource_section(plan.entries)


def encode_image_resource_section_length(resource_section_length: int) -> bytes:
    if resource_section_length < 0 or resource_section_length > 0xFFFFFFFF:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop PSD image resource section length must fit in uint32."
        )
    return resource_section_length.to_bytes(4, "big")


def mutation_map(
    mutations: Sequence[PhotoshopImageResourceMutation],
) -> tuple[dict[int, PhotoshopImageResourceMutation], tuple[int, ...]]:
    mutation_lookup: dict[int, PhotoshopImageResourceMutation] = {}
    seen_resource_ids: set[int] = set()
    duplicate_resource_ids: list[int] = []
    for mutation in mutations:
        validate_resource_id(mutation.resource_id)
        if mutation.resource_id in seen_resource_ids:
            duplicate_resource_ids.append(mutation.resource_id)
            continue
        seen_resource_ids.add(mutation.resource_id)
        mutation_lookup[mutation.resource_id] = mutation
    return mutation_lookup, tuple(duplicate_resource_ids)


def image_resource_replacement_blockers(
    *,
    blocks: tuple[tuple[int, bytes], ...],
    replacement_ids: tuple[int, ...],
    duplicate_replacement_ids: tuple[int, ...],
    source_backed: bool,
    resource_mutation_enabled: bool,
) -> tuple[PhotoshopImageResourceReplacementBlockerCode, ...]:
    blocker_codes: list[PhotoshopImageResourceReplacementBlockerCode] = []
    if not source_backed:
        blocker_codes.append("not_source_backed")
    if not resource_mutation_enabled:
        blocker_codes.append("real_psd_fixture_resource_mutation_gated")
    if duplicate_replacement_ids:
        blocker_codes.append("duplicate_replacement_request")

    for resource_id in replacement_ids:
        matching_signatures = tuple(
            signature for block_id, signature in blocks if block_id == resource_id
        )
        if not matching_signatures:
            blocker_codes.append("missing_target_resource")
            continue
        if len(matching_signatures) > 1:
            blocker_codes.append("duplicate_target_resource")
        if any(signature != PHOTOSHOP_WRITABLE_IRB_SIGNATURE for signature in matching_signatures):
            blocker_codes.append("non_8bim_target_resource")

    return tuple(dict.fromkeys(blocker_codes))


def image_resource_mutation_blockers(
    *,
    blocks: tuple[tuple[int, bytes], ...],
    mutations: tuple[PhotoshopImageResourceMutation, ...],
    duplicate_mutation_ids: tuple[int, ...],
    source_backed: bool,
    resource_mutation_enabled: bool,
) -> tuple[PhotoshopImageResourceMutationBlockerCode, ...]:
    blocker_codes: list[PhotoshopImageResourceMutationBlockerCode] = []
    if not source_backed:
        blocker_codes.append("not_source_backed")
    if not resource_mutation_enabled:
        blocker_codes.append("real_psd_fixture_resource_mutation_gated")
    if duplicate_mutation_ids:
        blocker_codes.append("duplicate_mutation_request")

    for mutation in mutations:
        matching_signatures = tuple(
            signature for block_id, signature in blocks if block_id == mutation.resource_id
        )
        if mutation.action == "insert":
            if matching_signatures:
                blocker_codes.append("insert_target_resource_exists")
            continue
        if not matching_signatures:
            if mutation.action == "delete":
                blocker_codes.append("missing_delete_target_resource")
            else:
                blocker_codes.append("missing_replace_target_resource")
            continue
        if len(matching_signatures) > 1:
            blocker_codes.append("duplicate_target_resource")
        if any(signature != PHOTOSHOP_WRITABLE_IRB_SIGNATURE for signature in matching_signatures):
            blocker_codes.append("non_8bim_target_resource")

    return tuple(dict.fromkeys(blocker_codes))


def existing_resource_step(
    block: PhotoshopImageResourceBlock,
    *,
    action: Literal["preserve", "replace"],
    output_entry_start: int,
    output_entry_length: int,
    output_data_size: int,
) -> PhotoshopImageResourceMutationStep:
    return PhotoshopImageResourceMutationStep(
        action=action,
        resource_id=block.resource_id,
        signature=block.signature,
        source_entry_start=block.entry_start,
        source_entry_length=block.entry_length,
        source_data_offset=block.data_offset,
        source_data_size=block.data_size,
        source_data_padding_size=block.data_padding_size,
        output_entry_start=output_entry_start,
        output_entry_length=output_entry_length,
        output_data_size=output_data_size,
        output_data_padding_size=output_data_size & 0x01,
    )


def deleted_resource_step(block: PhotoshopImageResourceBlock) -> PhotoshopImageResourceMutationStep:
    return PhotoshopImageResourceMutationStep(
        action="delete",
        resource_id=block.resource_id,
        signature=block.signature,
        source_entry_start=block.entry_start,
        source_entry_length=block.entry_length,
        source_data_offset=block.data_offset,
        source_data_size=block.data_size,
        source_data_padding_size=block.data_padding_size,
        output_entry_start=None,
        output_entry_length=0,
        output_data_size=0,
        output_data_padding_size=0,
    )


def inserted_resource_step(
    entry: PhotoshopImageResourceEntry,
    *,
    output_entry_start: int,
    output_entry_length: int,
) -> PhotoshopImageResourceMutationStep:
    return PhotoshopImageResourceMutationStep(
        action="insert",
        resource_id=entry.resource_id,
        signature=entry.signature,
        source_entry_start=None,
        source_entry_length=0,
        source_data_offset=None,
        source_data_size=0,
        source_data_padding_size=0,
        output_entry_start=output_entry_start,
        output_entry_length=output_entry_length,
        output_data_size=len(entry.data),
        output_data_padding_size=len(entry.data) & 0x01,
    )


def inserted_resource_entry(
    mutation: PhotoshopImageResourceMutation,
) -> PhotoshopImageResourceEntry:
    return PhotoshopImageResourceEntry(
        signature=PHOTOSHOP_WRITABLE_IRB_SIGNATURE,
        resource_id=mutation.resource_id,
        name=b"" if mutation.name is None else mutation.name,
        data=mutation.data,
    )


def sorted_insertions(
    mutation_lookup: dict[int, PhotoshopImageResourceMutation],
) -> tuple[PhotoshopImageResourceMutation, ...]:
    insertions = tuple(
        mutation for mutation in mutation_lookup.values() if mutation.action == "insert"
    )
    return tuple(sorted(insertions, key=lambda insertion: insertion.resource_id))


def count_resource_id(blocks: tuple[PhotoshopImageResourceBlock, ...], resource_id: int) -> int:
    return sum(1 for block in blocks if block.resource_id == resource_id)
