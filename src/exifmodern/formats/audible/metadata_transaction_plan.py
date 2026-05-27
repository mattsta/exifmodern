"""Source-grounded, non-mutating Audible metadata transaction plans.

ExifTool's Audible module reads Audible AA files directly and exposes observed
Audible M4B sub-tables for QuickTime-driven traversal.  This planner mirrors
those read-side responsibilities without changing bytes: it validates AA
headers, walks the table of contents, routes metadata dictionary, chapter, and
cover-art sections, preserves unknown/audio/DRM payloads, and gates all output
emission behind explicit blockers.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

AUDIBLE_AA_HEADER_SIZE = 16
AUDIBLE_AA_TOC_ENTRY_SIZE = 12
AUDIBLE_AA_MAGIC = b"\x57\x90\x75\x36"
AUDIBLE_AA_MAX_TOC_BYTES = 0xC00
AUDIBLE_AA_MAX_CHUNK_BYTES = 100_000_000
AUDIBLE_AA_MAX_DICTIONARY_ENTRIES = 0x200

type AudibleContainerKind = Literal["aa", "unknown"]
type AudibleTableName = Literal[
    "aa_main",
    "quicktime_tags",
    "quicktime_meta",
    "quicktime_cvrx",
    "quicktime_tseg",
]
type AudibleSectionKind = Literal[
    "metadata_dictionary",
    "chapter_offset_table",
    "cover_art",
    "unknown_toc_section",
    "drm_audio_payload",
]
type AudibleSectionAction = Literal[
    "route_metadata_dictionary",
    "read_chapter_count",
    "delegate_cover_art",
    "preserve_unknown_section",
    "preserve_drm_audio_payload",
    "skip_empty_section",
    "block_too_large",
]
type AudibleMetadataRole = Literal[
    "title",
    "author",
    "narrator",
    "product",
    "runtime",
    "publish_date",
    "copyright",
    "drm",
    "generic",
]
type AudibleMetadataWriteAction = Literal[
    "upsert_metadata_dictionary",
    "delete_metadata_dictionary",
]
type AudibleEmissionGateCode = Literal[
    "truncated_audible_header",
    "unsupported_audible_signature",
    "declared_file_size_mismatch",
    "invalid_toc_size",
    "truncated_toc",
    "chunk_seek_error",
    "chunk_too_big",
    "chunk_read_error",
    "bad_dictionary",
    "bad_dictionary_count",
    "truncated_dictionary",
    "bad_dictionary_entry",
    "bad_cover_art",
    "metadata_rewrite_requires_full_audible_rebuild",
    "toc_rewrite_required",
    "file_size_rewrite_required",
    "planner_is_non_mutating",
    "full_audible_writer_not_implemented",
]
type AudibleResponsibilityConcern = Literal[
    "signature_header_validation",
    "aa_toc_section_enumeration",
    "metadata_dictionary_routing",
    "m4b_table_enumeration",
    "cover_art_delegation",
    "drm_audio_payload_preservation",
    "unknown_section_preservation",
    "size_truncation_blockers",
    "rewrite_blockers",
    "output_emission_gate",
]

AUDIBLE_PM_SOURCE_PATH = "lib/Image/ExifTool/Audible.pm"

AUDIBLE_MAIN_TABLE_SOURCE = "audible.main_table"
AUDIBLE_TAGS_TABLE_SOURCE = "audible.tags_table"
AUDIBLE_META_TABLE_SOURCE = "audible.meta_table"
AUDIBLE_CVRX_TABLE_SOURCE = "audible.cvrx_table"
AUDIBLE_TSEG_TABLE_SOURCE = "audible.tseg_table"
AUDIBLE_M4B_META_PROCESS_SOURCE = "audible.m4b_meta_process"
AUDIBLE_M4B_CVRX_PROCESS_SOURCE = "audible.m4b_cvrx_process"
AUDIBLE_AA_HEADER_SOURCE = "audible.aa_header"
AUDIBLE_AA_TOC_SOURCE = "audible.aa_toc"
AUDIBLE_AA_CHAPTER_SOURCE = "audible.aa_chapter"
AUDIBLE_AA_COVER_SOURCE = "audible.aa_cover"
AUDIBLE_AA_DICTIONARY_SOURCE = "audible.aa_dictionary"
AUDIBLE_READ_ONLY_SOURCE = "audible.read_only"


@dataclass(frozen=True)
class AudibleTableEntryPlan:
    table: AudibleTableName
    tag_id: str
    name: str
    role: AudibleMetadataRole | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "name": self.name,
            "role": self.role,
            "table": self.table,
            "tag_id": self.tag_id,
        }


@dataclass(frozen=True)
class AudibleHeaderValidation:
    container_kind: AudibleContainerKind
    is_valid: bool
    declared_file_size: int | None
    actual_file_size: int
    magic: str | None
    toc_entry_count: int | None
    toc_byte_count: int | None
    reason: AudibleEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "actual_file_size": self.actual_file_size,
            "container_kind": self.container_kind,
            "declared_file_size": self.declared_file_size,
            "is_valid": self.is_valid,
            "magic": self.magic,
            "reason": self.reason,
            "toc_byte_count": self.toc_byte_count,
            "toc_entry_count": self.toc_entry_count,
        }


@dataclass(frozen=True)
class AudibleSectionPlan:
    section_kind: AudibleSectionKind
    action: AudibleSectionAction
    toc_index: int | None
    chunk_type: int | None
    offset: int
    length: int
    end_offset: int | None
    evidence_ids: tuple[str, ...]

    @property
    def label(self) -> str:
        if self.chunk_type is None:
            return self.section_kind
        return f"toc[{self.toc_index}]/{self.chunk_type}:{self.section_kind}"

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "chunk_type": self.chunk_type,
            "end_offset": self.end_offset,
            "label": self.label,
            "length": self.length,
            "offset": self.offset,
            "section_kind": self.section_kind,
            "toc_index": self.toc_index,
        }


@dataclass(frozen=True)
class AudibleMetadataEntryPlan:
    tag_id: str
    name: str
    value: str
    role: AudibleMetadataRole
    section_label: str
    value_offset: int
    value_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "name": self.name,
            "role": self.role,
            "section_label": self.section_label,
            "tag_id": self.tag_id,
            "value": self.value,
            "value_offset": self.value_offset,
            "value_size": self.value_size,
        }


@dataclass(frozen=True)
class AudibleChapterPlan:
    section_label: str
    chapter_count: int
    value_offset: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "chapter_count": self.chapter_count,
            "section_label": self.section_label,
            "value_offset": self.value_offset,
        }


@dataclass(frozen=True)
class AudibleCoverArtPlan:
    section_label: str
    declared_cover_size: int
    declared_cover_offset: int
    payload_offset: int
    payload_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "declared_cover_offset": self.declared_cover_offset,
            "declared_cover_size": self.declared_cover_size,
            "payload_offset": self.payload_offset,
            "payload_size": self.payload_size,
            "section_label": self.section_label,
        }


@dataclass(frozen=True)
class AudibleMetadataWriteRequest:
    tag_id: str
    value: str | None


@dataclass(frozen=True)
class AudibleMetadataRoute:
    action: AudibleMetadataWriteAction
    tag_id: str
    name: str
    requested_value: str | None
    existing_value: str | None
    estimated_size_delta: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "estimated_size_delta": self.estimated_size_delta,
            "existing_value": self.existing_value,
            "name": self.name,
            "requested_value": self.requested_value,
            "tag_id": self.tag_id,
        }


@dataclass(frozen=True)
class AudibleResponsibility:
    order: int
    concern: AudibleResponsibilityConcern
    description: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "description": self.description,
            "order": self.order,
        }


@dataclass(frozen=True)
class AudibleEmissionGate:
    code: AudibleEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AudibleMetadataTransactionPlan:
    header_validation: AudibleHeaderValidation
    table_entries: tuple[AudibleTableEntryPlan, ...]
    sections: tuple[AudibleSectionPlan, ...]
    metadata_entries: tuple[AudibleMetadataEntryPlan, ...]
    chapter_counts: tuple[AudibleChapterPlan, ...]
    cover_art: tuple[AudibleCoverArtPlan, ...]
    routes: tuple[AudibleMetadataRoute, ...]
    responsibilities: tuple[AudibleResponsibility, ...]
    output_emission_gates: tuple[AudibleEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def section_labels(self) -> tuple[str, ...]:
        return tuple(section.label for section in self.sections)

    @property
    def preserved_unknown_section_count(self) -> int:
        return sum(1 for section in self.sections if section.action == "preserve_unknown_section")

    @property
    def preserved_drm_audio_payload_bytes(self) -> int:
        return sum(
            section.length
            for section in self.sections
            if section.action == "preserve_drm_audio_payload"
        )

    @property
    def estimated_size_delta(self) -> int:
        return sum(route.estimated_size_delta for route in self.routes)

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"Audible metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "chapter_counts": [chapter.to_json() for chapter in self.chapter_counts],
            "cover_art": [cover.to_json() for cover in self.cover_art],
            "estimated_size_delta": self.estimated_size_delta,
            "header_validation": self.header_validation.to_json(),
            "metadata_entries": [entry.to_json() for entry in self.metadata_entries],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "preserved_drm_audio_payload_bytes": self.preserved_drm_audio_payload_bytes,
            "preserved_unknown_section_count": self.preserved_unknown_section_count,
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "routes": [route.to_json() for route in self.routes],
            "section_labels": list(self.section_labels),
            "sections": [section.to_json() for section in self.sections],
            "table_entries": [entry.to_json() for entry in self.table_entries],
        }


def build_audible_metadata_transaction_plan(
    data: bytes,
    metadata_writes: tuple[AudibleMetadataWriteRequest, ...] = (),
    *,
    actual_file_size: int | None = None,
) -> AudibleMetadataTransactionPlan:
    """Build a non-mutating Audible metadata transaction plan."""

    header, sections, parse_gates = inspect_aa_sections(data, actual_file_size=actual_file_size)
    metadata_entries, chapter_counts, cover_art, metadata_gates = extract_section_payloads(
        sections, data
    )
    routes = route_metadata_writes(metadata_entries, metadata_writes)
    gates = [*parse_gates, *metadata_gates]
    if routes:
        gates.extend(rewrite_gates())
    gates.extend(non_mutating_gates())
    table_entries = audible_table_entries()
    responsibilities = default_responsibilities()
    sources = unique_evidence_ids(
        (
            *header.evidence_ids,
            *(source for entry in table_entries for source in entry.evidence_ids),
            *(source for section in sections for source in section.evidence_ids),
            *(source for entry in metadata_entries for source in entry.evidence_ids),
            *(source for chapter in chapter_counts for source in chapter.evidence_ids),
            *(source for cover in cover_art for source in cover.evidence_ids),
            *(source for route in routes for source in route.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
        )
    )
    return AudibleMetadataTransactionPlan(
        header_validation=header,
        table_entries=table_entries,
        sections=sections,
        metadata_entries=metadata_entries,
        chapter_counts=chapter_counts,
        cover_art=cover_art,
        routes=routes,
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
    )


def inspect_aa_sections(
    data: bytes,
    *,
    actual_file_size: int | None = None,
) -> tuple[
    AudibleHeaderValidation,
    tuple[AudibleSectionPlan, ...],
    tuple[AudibleEmissionGate, ...],
]:
    materialized_size = len(data)
    actual_size = actual_file_size if actual_file_size is not None else materialized_size
    if materialized_size < AUDIBLE_AA_HEADER_SIZE:
        return (
            AudibleHeaderValidation(
                container_kind="unknown",
                is_valid=False,
                declared_file_size=None,
                actual_file_size=actual_size,
                magic=data[4:8].hex() if materialized_size > 4 else None,
                toc_entry_count=None,
                toc_byte_count=None,
                reason="truncated_audible_header",
                evidence_ids=(AUDIBLE_AA_HEADER_SOURCE,),
            ),
            (),
            (
                AudibleEmissionGate(
                    "truncated_audible_header",
                    "ProcessAA reads 16 bytes before checking Audible magic and TOC size.",
                    True,
                    (AUDIBLE_AA_HEADER_SOURCE,),
                ),
            ),
        )
    declared_file_size = read_u32be(data, 0)
    magic = data[4:8]
    if magic != AUDIBLE_AA_MAGIC:
        return (
            AudibleHeaderValidation(
                container_kind="unknown",
                is_valid=False,
                declared_file_size=declared_file_size,
                actual_file_size=actual_size,
                magic=magic.hex(),
                toc_entry_count=None,
                toc_byte_count=None,
                reason="unsupported_audible_signature",
                evidence_ids=(AUDIBLE_AA_HEADER_SOURCE,),
            ),
            (),
            (
                AudibleEmissionGate(
                    "unsupported_audible_signature",
                    "AA files must contain Audible magic 0x57907536 at bytes 4..7.",
                    True,
                    (AUDIBLE_AA_HEADER_SOURCE,),
                ),
            ),
        )
    toc_entry_count = read_u32be(data, 8)
    toc_byte_count = AUDIBLE_AA_TOC_ENTRY_SIZE * toc_entry_count
    header = AudibleHeaderValidation(
        container_kind="aa",
        is_valid=declared_file_size == actual_size and toc_byte_count <= AUDIBLE_AA_MAX_TOC_BYTES,
        declared_file_size=declared_file_size,
        actual_file_size=actual_size,
        magic=magic.hex(),
        toc_entry_count=toc_entry_count,
        toc_byte_count=toc_byte_count,
        reason=header_reason(declared_file_size, actual_size, toc_byte_count),
        evidence_ids=(AUDIBLE_AA_HEADER_SOURCE,),
    )
    gates: list[AudibleEmissionGate] = []
    if declared_file_size != actual_size:
        gates.append(
            AudibleEmissionGate(
                "declared_file_size_mismatch",
                "ProcessAA expects the first uint32 to match the actual file size.",
                True,
                (AUDIBLE_AA_HEADER_SOURCE,),
            )
        )
    if toc_byte_count > AUDIBLE_AA_MAX_TOC_BYTES:
        gates.append(
            AudibleEmissionGate(
                "invalid_toc_size",
                "ProcessAA warns and stops when the TOC byte count exceeds 0x0c00.",
                True,
                (AUDIBLE_AA_HEADER_SOURCE,),
            )
        )
        return header, (), tuple(gates)
    toc_start = AUDIBLE_AA_HEADER_SIZE
    toc_end = toc_start + toc_byte_count
    if toc_end > materialized_size:
        gates.append(
            AudibleEmissionGate(
                "truncated_toc",
                "ProcessAA reads the declared TOC and warns when it is truncated.",
                True,
                (AUDIBLE_AA_HEADER_SOURCE,),
            )
        )
        return header, (), tuple(gates)
    sections: list[AudibleSectionPlan] = []
    for index in range(toc_entry_count):
        entry_offset = toc_start + index * AUDIBLE_AA_TOC_ENTRY_SIZE
        chunk_type = read_u32be(data, entry_offset)
        offset = read_u32be(data, entry_offset + 4)
        length = read_u32be(data, entry_offset + 8)
        section = inspect_toc_entry(index, chunk_type, offset, length, actual_size)
        sections.append(section)
        gates.extend(section_gates(section, actual_size))
    return header, tuple(sections), tuple(gates)


def inspect_toc_entry(
    index: int, chunk_type: int, offset: int, length: int, actual_size: int
) -> AudibleSectionPlan:
    sources: tuple[str, ...]
    if chunk_type == 2:
        kind: AudibleSectionKind = "metadata_dictionary"
        action: AudibleSectionAction = "route_metadata_dictionary"
        sources = (AUDIBLE_AA_TOC_SOURCE, AUDIBLE_AA_DICTIONARY_SOURCE)
    elif chunk_type == 6:
        kind = "chapter_offset_table"
        action = "read_chapter_count"
        sources = (AUDIBLE_AA_TOC_SOURCE, AUDIBLE_AA_CHAPTER_SOURCE)
    elif chunk_type == 11:
        kind = "cover_art"
        action = "delegate_cover_art"
        sources = (AUDIBLE_AA_TOC_SOURCE, AUDIBLE_AA_COVER_SOURCE)
    else:
        kind = "unknown_toc_section"
        action = "preserve_drm_audio_payload" if length > 0 else "skip_empty_section"
        sources = (AUDIBLE_AA_TOC_SOURCE,)
    if length == 0:
        action = "skip_empty_section"
    elif length > AUDIBLE_AA_MAX_CHUNK_BYTES:
        action = "block_too_large"
    end_offset = offset + length if offset + length <= actual_size else None
    if action == "preserve_drm_audio_payload":
        kind = "drm_audio_payload"
    return AudibleSectionPlan(
        section_kind=kind,
        action=action,
        toc_index=index,
        chunk_type=chunk_type,
        offset=offset,
        length=length,
        end_offset=end_offset,
        evidence_ids=sources,
    )


def section_gates(section: AudibleSectionPlan, actual_size: int) -> tuple[AudibleEmissionGate, ...]:
    if section.length == 0:
        return ()
    if section.offset >= actual_size:
        return (
            AudibleEmissionGate(
                "chunk_seek_error",
                f"TOC chunk {section.chunk_type} starts at {section.offset}, beyond EOF.",
                True,
                section.evidence_ids,
            ),
        )
    if section.length > AUDIBLE_AA_MAX_CHUNK_BYTES:
        return (
            AudibleEmissionGate(
                "chunk_too_big",
                f"TOC chunk {section.chunk_type} exceeds ExifTool's 100000000 byte read limit.",
                True,
                (AUDIBLE_AA_TOC_SOURCE,),
            ),
        )
    if section.end_offset is None:
        return (
            AudibleEmissionGate(
                "chunk_read_error",
                f"TOC chunk {section.chunk_type} declares bytes beyond EOF.",
                True,
                section.evidence_ids,
            ),
        )
    return ()


def extract_section_payloads(
    sections: tuple[AudibleSectionPlan, ...], data: bytes
) -> tuple[
    tuple[AudibleMetadataEntryPlan, ...],
    tuple[AudibleChapterPlan, ...],
    tuple[AudibleCoverArtPlan, ...],
    tuple[AudibleEmissionGate, ...],
]:
    metadata_entries: list[AudibleMetadataEntryPlan] = []
    chapter_counts: list[AudibleChapterPlan] = []
    cover_art: list[AudibleCoverArtPlan] = []
    gates: list[AudibleEmissionGate] = []
    for section in sections:
        if section.end_offset is None:
            continue
        payload = data[section.offset : section.end_offset]
        if section.action == "route_metadata_dictionary":
            parsed_entries, parsed_gates = parse_metadata_dictionary(section, payload)
            metadata_entries.extend(parsed_entries)
            gates.extend(parsed_gates)
        elif section.action == "read_chapter_count" and section.length >= 4:
            chapter_counts.append(
                AudibleChapterPlan(
                    section_label=section.label,
                    chapter_count=read_u32be(payload, 0),
                    value_offset=section.offset,
                    evidence_ids=(AUDIBLE_AA_CHAPTER_SOURCE,),
                )
            )
        elif section.action == "delegate_cover_art":
            parsed_cover, cover_gate = parse_cover_art(section, payload)
            if parsed_cover is not None:
                cover_art.append(parsed_cover)
            if cover_gate is not None:
                gates.append(cover_gate)
    return tuple(metadata_entries), tuple(chapter_counts), tuple(cover_art), tuple(gates)


def parse_metadata_dictionary(
    section: AudibleSectionPlan, payload: bytes
) -> tuple[tuple[AudibleMetadataEntryPlan, ...], tuple[AudibleEmissionGate, ...]]:
    if len(payload) < 4:
        return (
            (),
            (
                AudibleEmissionGate(
                    "bad_dictionary",
                    "ProcessAA requires at least four bytes for the dictionary count.",
                    True,
                    (AUDIBLE_AA_DICTIONARY_SOURCE,),
                ),
            ),
        )
    entry_count = read_u32be(payload, 0)
    if entry_count > AUDIBLE_AA_MAX_DICTIONARY_ENTRIES:
        return (
            (),
            (
                AudibleEmissionGate(
                    "bad_dictionary_count",
                    "ProcessAA skips dictionaries with more than 0x200 entries.",
                    True,
                    (AUDIBLE_AA_DICTIONARY_SOURCE,),
                ),
            ),
        )
    entries: list[AudibleMetadataEntryPlan] = []
    gates: list[AudibleEmissionGate] = []
    position = 4
    for index in range(entry_count):
        tag_position = position + 9
        if tag_position > len(payload):
            gates.append(
                AudibleEmissionGate(
                    "truncated_dictionary",
                    f"Dictionary entry {index} does not contain its fixed entry header.",
                    True,
                    (AUDIBLE_AA_DICTIONARY_SOURCE,),
                )
            )
            break
        tag_length = read_u32be(payload, position + 1)
        value_length = read_u32be(payload, position + 5)
        value_position = tag_position + tag_length
        next_position = value_position + value_length
        if next_position > len(payload):
            gates.append(
                AudibleEmissionGate(
                    "bad_dictionary_entry",
                    f"Dictionary entry {index} declares tag/value bytes beyond the chunk.",
                    True,
                    (AUDIBLE_AA_DICTIONARY_SOURCE,),
                )
            )
            break
        tag_id = payload[tag_position:value_position].decode("utf-8", errors="replace")
        raw_value = payload[value_position:next_position].decode("utf-8", errors="replace")
        value = unescape(raw_value)
        entries.append(
            AudibleMetadataEntryPlan(
                tag_id=tag_id,
                name=make_audible_tag_name(tag_id),
                value=value,
                role=metadata_role(tag_id),
                section_label=section.label,
                value_offset=section.offset + value_position,
                value_size=value_length,
                evidence_ids=(AUDIBLE_MAIN_TABLE_SOURCE, AUDIBLE_AA_DICTIONARY_SOURCE),
            )
        )
        position = next_position
    return tuple(entries), tuple(gates)


def parse_cover_art(
    section: AudibleSectionPlan, payload: bytes
) -> tuple[AudibleCoverArtPlan | None, AudibleEmissionGate | None]:
    if len(payload) < 8:
        return None, None
    cover_size = read_u32be(payload, 0)
    cover_offset = read_u32be(payload, 4)
    cover_end = cover_offset - section.offset + cover_size
    if cover_offset < section.offset + 8 or cover_end > len(payload):
        return (
            None,
            AudibleEmissionGate(
                "bad_cover_art",
                "AA cover-art chunk declares a payload outside the chunk bounds.",
                True,
                (AUDIBLE_AA_COVER_SOURCE,),
            ),
        )
    return (
        AudibleCoverArtPlan(
            section_label=section.label,
            declared_cover_size=cover_size,
            declared_cover_offset=cover_offset,
            payload_offset=cover_offset,
            payload_size=cover_size,
            evidence_ids=(AUDIBLE_AA_COVER_SOURCE,),
        ),
        None,
    )


def route_metadata_writes(
    existing_entries: tuple[AudibleMetadataEntryPlan, ...],
    metadata_writes: tuple[AudibleMetadataWriteRequest, ...],
) -> tuple[AudibleMetadataRoute, ...]:
    routes: list[AudibleMetadataRoute] = []
    for request in metadata_writes:
        existing = next(
            (entry for entry in existing_entries if entry.tag_id == request.tag_id),
            None,
        )
        existing_value = existing.value if existing is not None else None
        requested_size = len(request.value.encode("utf-8")) if request.value is not None else 0
        existing_size = len(existing_value.encode("utf-8")) if existing_value is not None else 0
        action: AudibleMetadataWriteAction = (
            "delete_metadata_dictionary" if request.value is None else "upsert_metadata_dictionary"
        )
        routes.append(
            AudibleMetadataRoute(
                action=action,
                tag_id=request.tag_id,
                name=make_audible_tag_name(request.tag_id),
                requested_value=request.value,
                existing_value=existing_value,
                estimated_size_delta=requested_size - existing_size,
                evidence_ids=(AUDIBLE_AA_DICTIONARY_SOURCE, AUDIBLE_READ_ONLY_SOURCE),
            )
        )
    return tuple(routes)


def rewrite_gates() -> tuple[AudibleEmissionGate, ...]:
    return (
        AudibleEmissionGate(
            "metadata_rewrite_requires_full_audible_rebuild",
            "Audible.pm only reads dictionaries; safe metadata edits require rebuilding AA chunks.",
            True,
            (AUDIBLE_AA_DICTIONARY_SOURCE, AUDIBLE_READ_ONLY_SOURCE),
        ),
        AudibleEmissionGate(
            "toc_rewrite_required",
            "Changing AA chunk sizes can require TOC offset and length repairs.",
            True,
            (AUDIBLE_AA_TOC_SOURCE,),
        ),
        AudibleEmissionGate(
            "file_size_rewrite_required",
            "AA byte 0..3 stores the file size, so rewritten output must repair it.",
            True,
            (AUDIBLE_AA_HEADER_SOURCE,),
        ),
    )


def non_mutating_gates() -> tuple[AudibleEmissionGate, ...]:
    return (
        AudibleEmissionGate(
            "planner_is_non_mutating",
            "Audible metadata transaction plans record decisions but do not mutate bytes.",
            True,
            (AUDIBLE_READ_ONLY_SOURCE,),
        ),
        AudibleEmissionGate(
            "full_audible_writer_not_implemented",
            "Safe emission requires a complete Audible AA writer and QuickTime delegation.",
            True,
            (AUDIBLE_READ_ONLY_SOURCE, AUDIBLE_AA_TOC_SOURCE),
        ),
    )


def audible_table_entries() -> tuple[AudibleTableEntryPlan, ...]:
    main = (AUDIBLE_MAIN_TABLE_SOURCE,)
    tags = (AUDIBLE_TAGS_TABLE_SOURCE,)
    meta = (AUDIBLE_META_TABLE_SOURCE,)
    cvrx = (AUDIBLE_CVRX_TABLE_SOURCE,)
    tseg = (AUDIBLE_TSEG_TABLE_SOURCE,)
    return (
        AudibleTableEntryPlan("aa_main", "pubdate", "PublishDate", "publish_date", main),
        AudibleTableEntryPlan(
            "aa_main",
            "pub_date_start",
            "PublishDateStart",
            "publish_date",
            main,
        ),
        AudibleTableEntryPlan("aa_main", "author", "Author", "author", main),
        AudibleTableEntryPlan("aa_main", "copyright", "Copyright", "copyright", main),
        AudibleTableEntryPlan("aa_main", "title", "Title", "title", main),
        AudibleTableEntryPlan("aa_main", "narrator", "Narrator", "narrator", main),
        AudibleTableEntryPlan("aa_main", "product_id", "ProductID", "product", main),
        AudibleTableEntryPlan("aa_main", "_chapter_count", "ChapterCount", None, main),
        AudibleTableEntryPlan("aa_main", "_cover_art", "CoverArt", None, main),
        AudibleTableEntryPlan("quicktime_tags", "meta", "Audible_meta", None, tags),
        AudibleTableEntryPlan("quicktime_tags", "cvrx", "Audible_cvrx", None, tags),
        AudibleTableEntryPlan("quicktime_tags", "tseg", "Audible_tseg", None, tags),
        AudibleTableEntryPlan("quicktime_meta", "Album", "Album", None, meta),
        AudibleTableEntryPlan("quicktime_meta", "ALBUMARTIST", "AlbumArtist", "author", meta),
        AudibleTableEntryPlan("quicktime_meta", "Artist", "Artist", "author", meta),
        AudibleTableEntryPlan("quicktime_meta", "Title", "Title", "title", meta),
        AudibleTableEntryPlan("quicktime_meta", "Year", "Year", None, meta),
        AudibleTableEntryPlan("quicktime_meta", "track", "ChapterName", None, meta),
        AudibleTableEntryPlan("quicktime_cvrx", "CoverArtType", "CoverArtType", None, cvrx),
        AudibleTableEntryPlan("quicktime_cvrx", "CoverArt", "CoverArt", None, cvrx),
        AudibleTableEntryPlan("quicktime_tseg", "tshd", "ChapterNumber", None, tseg),
        AudibleTableEntryPlan("quicktime_tseg", "meta", "Audible_meta2", None, tseg),
    )


def default_responsibilities() -> tuple[AudibleResponsibility, ...]:
    return (
        AudibleResponsibility(
            1,
            "signature_header_validation",
            "Validate AA magic, declared file size, and bounded TOC size.",
            (AUDIBLE_AA_HEADER_SOURCE,),
        ),
        AudibleResponsibility(
            2,
            "aa_toc_section_enumeration",
            "Walk 12-byte AA table-of-contents entries and route only ExifTool-modeled chunks.",
            (AUDIBLE_AA_TOC_SOURCE,),
        ),
        AudibleResponsibility(
            3,
            "metadata_dictionary_routing",
            "Extract known and unknown dictionary tags, including title, author, "
            "narrator, product, and runtime when present.",
            (AUDIBLE_MAIN_TABLE_SOURCE, AUDIBLE_AA_DICTIONARY_SOURCE),
        ),
        AudibleResponsibility(
            4,
            "m4b_table_enumeration",
            "Expose Audible QuickTime tags/meta/cvrx/tseg tables without adding a "
            "package-local QuickTime parser.",
            (
                AUDIBLE_TAGS_TABLE_SOURCE,
                AUDIBLE_META_TABLE_SOURCE,
                AUDIBLE_CVRX_TABLE_SOURCE,
                AUDIBLE_TSEG_TABLE_SOURCE,
                AUDIBLE_M4B_META_PROCESS_SOURCE,
                AUDIBLE_M4B_CVRX_PROCESS_SOURCE,
            ),
        ),
        AudibleResponsibility(
            5,
            "cover_art_delegation",
            "Bound embedded AA cover payloads and delegate them as binary artwork.",
            (AUDIBLE_AA_COVER_SOURCE,),
        ),
        AudibleResponsibility(
            6,
            "drm_audio_payload_preservation",
            "Preserve DRM metadata fields and TOC entries that ExifTool does not "
            "route as metadata, chapters, or cover art.",
            (AUDIBLE_MAIN_TABLE_SOURCE, AUDIBLE_AA_TOC_SOURCE),
        ),
        AudibleResponsibility(
            7,
            "unknown_section_preservation",
            "Preserve unknown TOC sections rather than rewriting or discarding them.",
            (AUDIBLE_AA_TOC_SOURCE,),
        ),
        AudibleResponsibility(
            8,
            "size_truncation_blockers",
            "Block invalid TOC size, truncated TOC/chunks, huge chunks, or "
            "malformed dictionaries/artwork.",
            (
                AUDIBLE_AA_HEADER_SOURCE,
                AUDIBLE_AA_TOC_SOURCE,
                AUDIBLE_AA_DICTIONARY_SOURCE,
                AUDIBLE_AA_COVER_SOURCE,
            ),
        ),
        AudibleResponsibility(
            9,
            "rewrite_blockers",
            "Gate requested writes because AA chunk, TOC, and file-size rebuilds "
            "are not implemented.",
            (AUDIBLE_AA_HEADER_SOURCE, AUDIBLE_AA_TOC_SOURCE, AUDIBLE_READ_ONLY_SOURCE),
        ),
        AudibleResponsibility(
            10,
            "output_emission_gate",
            "Keep byte emission disabled unless a future complete writer explicitly "
            "removes these gates.",
            (AUDIBLE_READ_ONLY_SOURCE,),
        ),
    )


def header_reason(
    declared_file_size: int, actual_file_size: int, toc_byte_count: int
) -> AudibleEmissionGateCode | None:
    if declared_file_size != actual_file_size:
        return "declared_file_size_mismatch"
    if toc_byte_count > AUDIBLE_AA_MAX_TOC_BYTES:
        return "invalid_toc_size"
    return None


def metadata_role(tag_id: str) -> AudibleMetadataRole:
    normalized = tag_id.casefold()
    if normalized in {"title", "short_title", "parent_title", "parent_short_title"}:
        return "title"
    if normalized == "author":
        return "author"
    if normalized == "narrator":
        return "narrator"
    if normalized in {"product_id", "parent_id", "title_id", "aggregation_id"}:
        return "product"
    if normalized in {"runtime", "duration", "running_time", "length"}:
        return "runtime"
    if normalized in {"pubdate", "pub_date_start"}:
        return "publish_date"
    if normalized == "copyright":
        return "copyright"
    if normalized in {
        "headerseed",
        "encryptedblocks",
        "headerkey",
        "license_list",
        "cputype",
        "license_count",
    }:
        return "drm"
    return "generic"


def make_audible_tag_name(tag_id: str) -> str:
    known_names: dict[str, str] = {
        "pubdate": "PublishDate",
        "pub_date_start": "PublishDateStart",
        "author": "Author",
        "copyright": "Copyright",
        "product_id": "ProductId",
    }
    if tag_id in known_names:
        return known_names[tag_id]
    if _is_lowercase_hex_tag_id(tag_id):
        return f"Tag{tag_id}"
    parts = tuple(part for part in tag_id.replace("-", "_").split("_") if part)
    if not parts:
        return "Unknown"
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _is_lowercase_hex_tag_id(tag_id: str) -> bool:
    return len(tag_id) > 0 and all(character in "0123456789abcdef" for character in tag_id)


def read_u32be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def unique_evidence_ids(references: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def unique_gates(gates: tuple[AudibleEmissionGate, ...]) -> tuple[AudibleEmissionGate, ...]:
    unique: list[AudibleEmissionGate] = []
    seen: set[AudibleEmissionGateCode] = set()
    for gate in gates:
        if gate.code not in seen:
            seen.add(gate.code)
            unique.append(gate)
    return tuple(unique)
