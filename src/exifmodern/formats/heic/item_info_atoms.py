"""Typed HEIC ItemInformation atom edit primitives.

These helpers model the small ItemInfo/XMP write pieces used by ExifTool's
``WriteItemInfo`` path: ``iinf``/``infe``, ``iref``/``cdsc``, ``iloc`` item
entries, and scheduled ``mdat`` edits.  They intentionally stop short of global
QuickTime offset repair.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HEIC_ATOM_HEADER_SIZE = 8
HEIC_EXTENDED_ATOM_HEADER_SIZE = 16
XMP_MIME_TYPE = "application/rdf+xml"

type HeicItemType = str
type HeicMdatEditKind = Literal["insert", "replace", "delete"]
type HeicMdatSegmentKind = Literal["copy", "replacement"]
type HeicIlocOffsetPointerKind = Literal["iloc_extent_offset", "iloc_base_offset"]
type HeicIlocOffsetPointerTag = Literal["stco_iloc", "co64_iloc"]
type HeicItemInfoBoxKind = Literal["iinf", "iref", "iloc"]


@dataclass(frozen=True)
class HeicAtom:
    atom_type: str
    payload: bytes


@dataclass(frozen=True)
class HeicAtomSpan:
    atom_type: str
    offset: int
    size: int
    header_size: int
    payload: bytes


@dataclass(frozen=True)
class HeicFullBoxHeader:
    version: int
    flags: int


@dataclass(frozen=True)
class HeicInfeEntry:
    item_id: int
    item_type: HeicItemType
    item_name: str
    content_type: str | None
    content_encoding: str | None
    protection_index: int = 0


@dataclass(frozen=True)
class HeicIinfBox:
    version: int
    entries: tuple[HeicInfeEntry, ...]


@dataclass(frozen=True)
class HeicCdscReference:
    from_item_id: int
    to_item_ids: tuple[int, ...]


@dataclass(frozen=True)
class HeicIrefBox:
    version: int
    cdsc_references: tuple[HeicCdscReference, ...]


@dataclass(frozen=True)
class HeicIlocExtent:
    extent_index: int
    extent_offset: int
    extent_length: int


@dataclass(frozen=True)
class HeicIlocItemEntry:
    item_id: int
    construction_method: int
    data_reference_index: int
    base_offset: int
    extents: tuple[HeicIlocExtent, ...]


@dataclass(frozen=True)
class HeicIlocBox:
    version: int
    offset_size: int
    length_size: int
    base_offset_size: int
    index_size: int
    items: tuple[HeicIlocItemEntry, ...]


@dataclass(frozen=True)
class HeicMdatEdit:
    item_id: int
    mdat_index: int
    payload_offset: int
    replaced_length: int
    replacement: bytes
    kind: HeicMdatEditKind

    @property
    def length_delta(self) -> int:
        return len(self.replacement) - self.replaced_length


@dataclass(frozen=True)
class HeicScheduledMdatEdits:
    edits: tuple[HeicMdatEdit, ...]

    @property
    def length_delta(self) -> int:
        return sum(edit.length_delta for edit in self.edits)


@dataclass(frozen=True)
class HeicMdatBoxPlan:
    mdat_index: int
    atom_offset: int
    header_size: int
    payload_length: int
    size_field_width: int
    extends_to_eof: bool = False

    @property
    def payload_file_offset(self) -> int:
        return self.atom_offset + self.header_size

    @property
    def atom_size(self) -> int:
        return self.header_size + self.payload_length


@dataclass(frozen=True)
class HeicMdatPlannedSegment:
    mdat_index: int
    kind: HeicMdatSegmentKind
    old_payload_offset: int
    old_payload_end: int
    new_payload_relative_offset: int
    length: int
    item_id: int | None = None


@dataclass(frozen=True)
class HeicMdatBoxRewrite:
    mdat_index: int
    old_atom_offset: int
    old_payload_file_offset: int
    old_payload_length: int
    new_atom_offset: int
    new_payload_file_offset: int
    new_payload_length: int
    header_size: int
    size_field_width: int
    extends_to_eof: bool
    segments: tuple[HeicMdatPlannedSegment, ...]

    @property
    def length_delta(self) -> int:
        return self.new_payload_length - self.old_payload_length

    @property
    def requires_header_size_rewrite(self) -> bool:
        return self.length_delta != 0 and not self.extends_to_eof


@dataclass(frozen=True)
class HeicMdatRewritePlan:
    boxes: tuple[HeicMdatBoxRewrite, ...]

    @property
    def segments(self) -> tuple[HeicMdatPlannedSegment, ...]:
        return tuple(segment for box in self.boxes for segment in box.segments)

    @property
    def total_length_delta(self) -> int:
        return sum(box.length_delta for box in self.boxes)


@dataclass(frozen=True)
class HeicIlocOffsetPointerSite:
    item_id: int
    kind: HeicIlocOffsetPointerKind
    tag: HeicIlocOffsetPointerTag
    integer_size: int
    field_payload_offset: int
    field_box_offset: int
    field_file_offset: int
    stored_value: int
    media_data_base: int

    def shifted(self, byte_delta: int) -> HeicIlocOffsetPointerSite:
        return HeicIlocOffsetPointerSite(
            item_id=self.item_id,
            kind=self.kind,
            tag=self.tag,
            integer_size=self.integer_size,
            field_payload_offset=self.field_payload_offset,
            field_box_offset=self.field_box_offset,
            field_file_offset=self.field_file_offset + byte_delta,
            stored_value=self.stored_value,
            media_data_base=self.media_data_base,
        )


@dataclass(frozen=True)
class HeicItemInfoBoxDelta:
    atom_type: HeicItemInfoBoxKind
    old_size: int
    new_size: int

    @property
    def byte_delta(self) -> int:
        return self.new_size - self.old_size


@dataclass(frozen=True)
class HeicItemInfoCreationRebuildPlan:
    primary_item_id: int
    new_item_id: int
    iinf_payload: bytes
    iref_payload: bytes
    iloc_payload: bytes
    inserted_iref: bool
    box_deltas: tuple[HeicItemInfoBoxDelta, ...]
    bytes_inserted_before_iloc: int
    shifted_existing_iloc_offset_sites: tuple[HeicIlocOffsetPointerSite, ...]
    new_item_offset_site: HeicIlocOffsetPointerSite


@dataclass(frozen=True)
class HeicItemInfoExtentReplacementPlan:
    item_id: int
    iloc_payload: bytes
    scheduled_mdat_edits: HeicScheduledMdatEdits


@dataclass(frozen=True)
class HeicRecordedOffsetRewrite:
    site: HeicIlocOffsetPointerSite
    old_value: int
    new_value: int


@dataclass(frozen=True)
class HeicRecordedOffsetRewriteResult:
    data: bytes
    rewrites: tuple[HeicRecordedOffsetRewrite, ...]


def read_heic_atom_spans(
    data: bytes,
    start: int = 0,
    end: int | None = None,
) -> tuple[HeicAtomSpan, ...]:
    atom_end = len(data) if end is None else end
    atoms: list[HeicAtomSpan] = []
    offset = start
    while offset < atom_end:
        if offset + HEIC_ATOM_HEADER_SIZE > atom_end:
            raise ValueError("Truncated HEIC atom header.")
        size = int.from_bytes(data[offset : offset + 4], "big")
        atom_type = data[offset + 4 : offset + 8].decode("latin-1")
        header_size = HEIC_ATOM_HEADER_SIZE
        if size == 0:
            size = atom_end - offset
        elif size == 1:
            if offset + HEIC_EXTENDED_ATOM_HEADER_SIZE > atom_end:
                raise ValueError("Truncated HEIC extended atom header.")
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header_size = HEIC_EXTENDED_ATOM_HEADER_SIZE
        if size < header_size or offset + size > atom_end:
            raise ValueError(f"Invalid HEIC atom length for {atom_type!r}.")
        payload_start = offset + header_size
        atoms.append(
            HeicAtomSpan(
                atom_type=atom_type,
                offset=offset,
                size=size,
                header_size=header_size,
                payload=data[payload_start : offset + size],
            )
        )
        offset += size
    return tuple(atoms)


def encode_heic_atom(atom_type: str, payload: bytes) -> bytes:
    if len(atom_type) != 4:
        raise ValueError("HEIC atom types must be four characters.")
    atom_size = len(payload) + HEIC_ATOM_HEADER_SIZE
    if atom_size > 0xFFFFFFFF:
        raise ValueError("HEIC atoms larger than 4 GB are not supported.")
    return atom_size.to_bytes(4, "big") + atom_type.encode("latin-1") + payload


def encode_heic_atoms(atoms: tuple[HeicAtom, ...]) -> bytes:
    return b"".join(encode_heic_atom(atom.atom_type, atom.payload) for atom in atoms)


def mdat_box_plan_from_atom_span(
    atom: HeicAtomSpan,
    *,
    mdat_index: int,
    extends_to_eof: bool = False,
) -> HeicMdatBoxPlan:
    if atom.atom_type != "mdat":
        raise ValueError("Only mdat atom spans can be converted to mdat rewrite plans.")
    return HeicMdatBoxPlan(
        mdat_index=mdat_index,
        atom_offset=atom.offset,
        header_size=atom.header_size,
        payload_length=len(atom.payload),
        size_field_width=8 if atom.header_size == HEIC_EXTENDED_ATOM_HEADER_SIZE else 4,
        extends_to_eof=extends_to_eof,
    )


def plan_mdat_rewrite(
    mdat_boxes: tuple[HeicMdatBoxPlan, ...],
    schedule: HeicScheduledMdatEdits,
    *,
    rewritten_non_mdat_size: int,
) -> HeicMdatRewritePlan:
    """Split scheduled ItemInfo edits and compute rewritten ``mdat`` positions.

    This mirrors the ExifTool write phase without emitting bytes: edits are
    bounded to a single media-data box, each edited box is split into copy and
    replacement segments, 32-bit ``mdat`` headers are not promoted, and new
    media payload positions are assigned after the rewritten non-media buffer.
    """

    if rewritten_non_mdat_size < 0:
        raise ValueError("Rewritten non-mdat size must be non-negative.")
    known_mdat_indexes = {box.mdat_index for box in mdat_boxes}
    missing_indexes = tuple(
        dict.fromkeys(
            edit.mdat_index for edit in schedule.edits if edit.mdat_index not in known_mdat_indexes
        )
    )
    if missing_indexes:
        raise ValueError(f"Scheduled mdat edit targets missing mdat index {missing_indexes[0]}.")

    new_atom_offset = rewritten_non_mdat_size
    rewrites: list[HeicMdatBoxRewrite] = []
    for box in sorted(mdat_boxes, key=lambda candidate: candidate.mdat_index):
        box_edits = tuple(
            sorted(
                (edit for edit in schedule.edits if edit.mdat_index == box.mdat_index),
                key=lambda candidate: candidate.payload_offset,
            )
        )
        segments = split_mdat_payload_segments(box, box_edits)
        new_payload_length = sum(segment.length for segment in segments)
        new_atom_size = box.header_size + new_payload_length
        if box.size_field_width == 4 and not box.extends_to_eof and new_atom_size > 0xFFFFFFFF:
            raise ValueError("Cannot grow 32-bit mdat atom past uint32.")
        rewrite = HeicMdatBoxRewrite(
            mdat_index=box.mdat_index,
            old_atom_offset=box.atom_offset,
            old_payload_file_offset=box.payload_file_offset,
            old_payload_length=box.payload_length,
            new_atom_offset=new_atom_offset,
            new_payload_file_offset=new_atom_offset + box.header_size,
            new_payload_length=new_payload_length,
            header_size=box.header_size,
            size_field_width=box.size_field_width,
            extends_to_eof=box.extends_to_eof,
            segments=tuple(segments),
        )
        rewrites.append(rewrite)
        new_atom_offset += box.header_size + new_payload_length
    return HeicMdatRewritePlan(boxes=tuple(rewrites))


def discover_iloc_offset_pointer_sites(
    payload: bytes,
    *,
    iloc_box_file_offset: int = 0,
) -> tuple[HeicIlocOffsetPointerSite, ...]:
    """Locate ``iloc`` offset integer fields using ExifTool's write-time rule.

    ExifTool records either extent offsets or base offsets for later global
    media-offset repair.  For an item with both, it adjusts the larger component
    and stores the other component as the media-data base used during matching.
    """

    if iloc_box_file_offset < 0:
        raise ValueError("iloc box file offset must be non-negative.")
    if len(payload) < 8:
        raise ValueError("Truncated iloc size and count header.")

    version = payload[0]
    size_bits = int.from_bytes(payload[4:6], "big")
    offset_size = (size_bits >> 12) & 0x0F
    length_size = (size_bits >> 8) & 0x0F
    base_offset_size = (size_bits >> 4) & 0x0F
    index_size = size_bits & 0x0F
    validate_iloc_size(offset_size)
    validate_iloc_size(length_size)
    validate_iloc_size(base_offset_size)
    validate_iloc_size(index_size)
    if version < 2:
        item_count = read_uint(payload, 6, 2)
        pos = 8
    else:
        if len(payload) < 10:
            raise ValueError("Truncated iloc version 2 count.")
        item_count = read_uint(payload, 6, 4)
        pos = 10

    sites: list[HeicIlocOffsetPointerSite] = []
    for _index in range(item_count):
        item_id_size = 2 if version < 2 else 4
        item_id = read_uint(payload, pos, item_id_size)
        pos += item_id_size
        construction_method = 0
        if version in {1, 2}:
            construction_method = read_uint(payload, pos, 2) & 0x0F
            pos += 2
        data_reference_index = read_uint(payload, pos, 2)
        pos += 2
        offsets_are_constant = construction_method != 0 or data_reference_index != 0
        base_pointer_offset = pos
        base_offset = read_uint(payload, pos, base_offset_size)
        pos += base_offset_size
        extent_count = read_uint(payload, pos, 2)
        pos += 2
        base_sites: list[HeicIlocOffsetPointerSite] = []
        extent_sites: list[HeicIlocOffsetPointerSite] = []
        min_extent_offset: int | None = None
        if base_offset and not offsets_are_constant and base_offset_size:
            base_sites.append(
                iloc_offset_pointer_site(
                    item_id=item_id,
                    kind="iloc_base_offset",
                    integer_size=base_offset_size,
                    field_payload_offset=base_pointer_offset,
                    iloc_box_file_offset=iloc_box_file_offset,
                    stored_value=base_offset,
                    media_data_base=0,
                )
            )
        for _extent_index in range(extent_count):
            if version in {1, 2}:
                read_uint(payload, pos, index_size)
                pos += index_size
            extent_pointer_offset = pos
            extent_offset = read_uint(payload, pos, offset_size)
            pos += offset_size
            if not offsets_are_constant and offset_size:
                extent_sites.append(
                    iloc_offset_pointer_site(
                        item_id=item_id,
                        kind="iloc_extent_offset",
                        integer_size=offset_size,
                        field_payload_offset=extent_pointer_offset,
                        iloc_box_file_offset=iloc_box_file_offset,
                        stored_value=extent_offset,
                        media_data_base=base_offset,
                    )
                )
                if min_extent_offset is None or extent_offset < min_extent_offset:
                    min_extent_offset = extent_offset
            read_uint(payload, pos, length_size)
            pos += length_size
        if min_extent_offset is not None and min_extent_offset > base_offset:
            sites.extend(extent_sites)
        else:
            sites.extend(
                site_with_media_data_base(site, min_extent_offset or 0) for site in base_sites
            )
    return tuple(sites)


def shift_iloc_offset_pointer_sites(
    sites: tuple[HeicIlocOffsetPointerSite, ...],
    byte_delta: int,
) -> tuple[HeicIlocOffsetPointerSite, ...]:
    return tuple(site.shifted(byte_delta) for site in sites)


def plan_xmp_item_info_creation_rebuild(
    meta_children: tuple[HeicAtomSpan, ...],
    *,
    meta_payload_file_offset: int,
    primary_item_id: int,
    new_item_id: int,
    xmp_payload_length: int,
) -> HeicItemInfoCreationRebuildPlan:
    """Plan ExifTool-style ``iinf``/``iref``/``iloc`` growth for a new XMP item.

    The plan records existing ``iloc`` pointer sites before mutation, appends the
    new ItemInfo entries, and reports how far saved pointer locations move when
    earlier ItemInfo boxes grow before ``iloc``.
    """

    if meta_payload_file_offset < 0:
        raise ValueError("meta payload file offset must be non-negative.")
    if xmp_payload_length < 0:
        raise ValueError("XMP payload length must be non-negative.")
    iinf_atom = required_heic_atom(meta_children, "iinf")
    iloc_atom = required_heic_atom(meta_children, "iloc")
    iref_atom = find_heic_atom(meta_children, "iref")
    iloc_file_offset = meta_payload_file_offset + iloc_atom.offset
    old_iloc_sites = discover_iloc_offset_pointer_sites(
        iloc_atom.payload,
        iloc_box_file_offset=iloc_file_offset,
    )

    iloc = parse_iloc_payload(iloc_atom.payload)
    iinf_payload = append_iinf_entry(iinf_atom.payload, xmp_infe_entry(new_item_id))
    iloc_payload = append_iloc_item(
        iloc_atom.payload,
        mdat_iloc_item(new_item_id, xmp_payload_length, iloc, extent_offset=0),
    )
    cdsc = HeicCdscReference(from_item_id=new_item_id, to_item_ids=(primary_item_id,))
    inserted_iref = iref_atom is None
    if iref_atom is None:
        iref_version = 0 if max(primary_item_id, new_item_id) <= 0xFFFF else 1
        iref_payload = encode_iref_payload(
            HeicIrefBox(version=iref_version, cdsc_references=(cdsc,))
        )
        old_iref_size = 0
        iref_offset = iinf_atom.offset + iinf_atom.size
    else:
        iref_payload = append_iref_cdsc_reference(iref_atom.payload, cdsc)
        old_iref_size = iref_atom.size
        iref_offset = iref_atom.offset

    deltas = (
        HeicItemInfoBoxDelta(
            atom_type="iinf",
            old_size=iinf_atom.size,
            new_size=len(encode_heic_atom("iinf", iinf_payload)),
        ),
        HeicItemInfoBoxDelta(
            atom_type="iref",
            old_size=old_iref_size,
            new_size=len(encode_heic_atom("iref", iref_payload)),
        ),
        HeicItemInfoBoxDelta(
            atom_type="iloc",
            old_size=iloc_atom.size,
            new_size=len(encode_heic_atom("iloc", iloc_payload)),
        ),
    )
    bytes_before_iloc = sum(
        delta.byte_delta
        for delta, offset in (
            (deltas[0], iinf_atom.offset),
            (deltas[1], iref_offset),
        )
        if offset <= iloc_atom.offset
    )
    final_iloc_file_offset = iloc_file_offset + bytes_before_iloc
    new_item_site = find_new_item_iloc_offset_pointer_site(
        iloc_payload,
        item_id=new_item_id,
        iloc_box_file_offset=final_iloc_file_offset,
    )

    return HeicItemInfoCreationRebuildPlan(
        primary_item_id=primary_item_id,
        new_item_id=new_item_id,
        iinf_payload=iinf_payload,
        iref_payload=iref_payload,
        iloc_payload=iloc_payload,
        inserted_iref=inserted_iref,
        box_deltas=deltas,
        bytes_inserted_before_iloc=bytes_before_iloc,
        shifted_existing_iloc_offset_sites=shift_iloc_offset_pointer_sites(
            old_iloc_sites,
            bytes_before_iloc,
        ),
        new_item_offset_site=new_item_site,
    )


def encode_rebuilt_item_info_meta_payload(
    meta_full_header: bytes,
    meta_children: tuple[HeicAtomSpan, ...],
    rebuild_plan: HeicItemInfoCreationRebuildPlan,
) -> bytes:
    rewritten_children: list[HeicAtom] = []
    inserted_iref = False
    for child in meta_children:
        if child.atom_type == "iinf":
            rewritten_children.append(HeicAtom("iinf", rebuild_plan.iinf_payload))
            if rebuild_plan.inserted_iref:
                rewritten_children.append(HeicAtom("iref", rebuild_plan.iref_payload))
                inserted_iref = True
        elif child.atom_type == "iref":
            rewritten_children.append(HeicAtom("iref", rebuild_plan.iref_payload))
        elif child.atom_type == "iloc":
            rewritten_children.append(HeicAtom("iloc", rebuild_plan.iloc_payload))
        else:
            rewritten_children.append(HeicAtom(child.atom_type, child.payload))
    if rebuild_plan.inserted_iref and not inserted_iref:
        rewritten_children.append(HeicAtom("iref", rebuild_plan.iref_payload))
    return meta_full_header + encode_heic_atoms(tuple(rewritten_children))


def apply_heic_recorded_iloc_offset_rewrites(
    data: bytes,
    sites: tuple[HeicIlocOffsetPointerSite, ...],
    mdat_rewrite_plan: HeicMdatRewritePlan,
) -> HeicRecordedOffsetRewriteResult:
    """Apply recorded ``iloc`` pointer rewrites after media positions are known."""

    rewritten = bytearray(data)
    repairs: list[HeicRecordedOffsetRewrite] = []
    for site in sites:
        new_value = relocated_iloc_pointer_value(site, mdat_rewrite_plan)
        if site.integer_size == 4 and new_value > 0xFFFFFFFF:
            raise ValueError("Cannot promote iloc offset to 64 bits.")
        if site.field_file_offset + site.integer_size > len(rewritten):
            raise ValueError("Recorded iloc offset pointer is outside the output buffer.")
        old_value = int.from_bytes(
            rewritten[site.field_file_offset : site.field_file_offset + site.integer_size],
            "big",
        )
        rewritten[site.field_file_offset : site.field_file_offset + site.integer_size] = (
            new_value.to_bytes(site.integer_size, "big")
        )
        repairs.append(
            HeicRecordedOffsetRewrite(site=site, old_value=old_value, new_value=new_value)
        )
    return HeicRecordedOffsetRewriteResult(data=bytes(rewritten), rewrites=tuple(repairs))


def relocated_iloc_pointer_value(
    site: HeicIlocOffsetPointerSite,
    mdat_rewrite_plan: HeicMdatRewritePlan,
) -> int:
    edited_segment = first_replacement_segment_for_item(mdat_rewrite_plan, site.item_id)
    if edited_segment is not None:
        box = mdat_rewrite_box(mdat_rewrite_plan, edited_segment.mdat_index)
        return (
            box.new_payload_file_offset
            + edited_segment.new_payload_relative_offset
            - site.media_data_base
        )

    old_position = site.stored_value + site.media_data_base
    for box in mdat_rewrite_plan.boxes:
        for segment in box.segments:
            if segment.kind != "copy":
                continue
            if old_position < segment.old_payload_offset or old_position > segment.old_payload_end:
                continue
            if old_position == segment.old_payload_end and segment.old_payload_end != (
                box.old_payload_file_offset + box.old_payload_length
            ):
                continue
            return (
                box.new_payload_file_offset
                + segment.new_payload_relative_offset
                + old_position
                - segment.old_payload_offset
                - site.media_data_base
            )
    raise ValueError("Chunk offset in iloc atom is outside media data.")


def find_new_item_iloc_offset_pointer_site(
    payload: bytes,
    *,
    item_id: int,
    iloc_box_file_offset: int,
) -> HeicIlocOffsetPointerSite:
    if len(payload) < 8:
        raise ValueError("Truncated iloc size and count header.")
    version = payload[0]
    size_bits = int.from_bytes(payload[4:6], "big")
    offset_size = (size_bits >> 12) & 0x0F
    length_size = (size_bits >> 8) & 0x0F
    base_offset_size = (size_bits >> 4) & 0x0F
    index_size = size_bits & 0x0F
    validate_iloc_size(offset_size)
    validate_iloc_size(length_size)
    validate_iloc_size(base_offset_size)
    validate_iloc_size(index_size)
    if version < 2:
        item_count = read_uint(payload, 6, 2)
        pos = 8
    else:
        item_count = read_uint(payload, 6, 4)
        pos = 10

    for _index in range(item_count):
        current_item_id = read_uint(payload, pos, 2 if version < 2 else 4)
        pos += 2 if version < 2 else 4
        if version in {1, 2}:
            pos += 2
        pos += 2
        base_pointer_offset = pos
        pos += base_offset_size
        extent_count = read_uint(payload, pos, 2)
        pos += 2
        for _extent_index in range(extent_count):
            if version in {1, 2}:
                pos += index_size
            extent_pointer_offset = pos
            pos += offset_size
            pos += length_size
            if current_item_id != item_id:
                continue
            if offset_size in {4, 8}:
                return iloc_offset_pointer_site(
                    item_id=item_id,
                    kind="iloc_extent_offset",
                    integer_size=offset_size,
                    field_payload_offset=extent_pointer_offset,
                    iloc_box_file_offset=iloc_box_file_offset,
                    stored_value=0,
                    media_data_base=0,
                )
            if base_offset_size in {4, 8}:
                return iloc_offset_pointer_site(
                    item_id=item_id,
                    kind="iloc_base_offset",
                    integer_size=base_offset_size,
                    field_payload_offset=base_pointer_offset,
                    iloc_box_file_offset=iloc_box_file_offset,
                    stored_value=0,
                    media_data_base=0,
                )
            raise ValueError("New ItemInfo iloc entry has no writable offset pointer.")
    raise ValueError("New ItemInfo iloc entry must provide exactly one offset pointer.")


def first_replacement_segment_for_item(
    mdat_rewrite_plan: HeicMdatRewritePlan,
    item_id: int,
) -> HeicMdatPlannedSegment | None:
    for segment in mdat_rewrite_plan.segments:
        if segment.kind == "replacement" and segment.item_id == item_id:
            return segment
    return None


def mdat_rewrite_box(
    mdat_rewrite_plan: HeicMdatRewritePlan,
    mdat_index: int,
) -> HeicMdatBoxRewrite:
    for box in mdat_rewrite_plan.boxes:
        if box.mdat_index == mdat_index:
            return box
    raise ValueError(f"Missing rewritten mdat index {mdat_index}.")


def iloc_offset_pointer_site(
    *,
    item_id: int,
    kind: HeicIlocOffsetPointerKind,
    integer_size: int,
    field_payload_offset: int,
    iloc_box_file_offset: int,
    stored_value: int,
    media_data_base: int,
) -> HeicIlocOffsetPointerSite:
    tag = iloc_offset_pointer_tag(integer_size)
    field_box_offset = HEIC_ATOM_HEADER_SIZE + field_payload_offset
    return HeicIlocOffsetPointerSite(
        item_id=item_id,
        kind=kind,
        tag=tag,
        integer_size=integer_size,
        field_payload_offset=field_payload_offset,
        field_box_offset=field_box_offset,
        field_file_offset=iloc_box_file_offset + field_box_offset,
        stored_value=stored_value,
        media_data_base=media_data_base,
    )


def site_with_media_data_base(
    site: HeicIlocOffsetPointerSite,
    media_data_base: int,
) -> HeicIlocOffsetPointerSite:
    return HeicIlocOffsetPointerSite(
        item_id=site.item_id,
        kind=site.kind,
        tag=site.tag,
        integer_size=site.integer_size,
        field_payload_offset=site.field_payload_offset,
        field_box_offset=site.field_box_offset,
        field_file_offset=site.field_file_offset,
        stored_value=site.stored_value,
        media_data_base=media_data_base,
    )


def iloc_offset_pointer_tag(integer_size: int) -> HeicIlocOffsetPointerTag:
    if integer_size == 4:
        return "stco_iloc"
    if integer_size == 8:
        return "co64_iloc"
    raise ValueError("HEIC iloc offset pointer size must be 4 or 8 bytes.")


def split_mdat_payload_segments(
    box: HeicMdatBoxPlan,
    edits: tuple[HeicMdatEdit, ...],
) -> tuple[HeicMdatPlannedSegment, ...]:
    segments: list[HeicMdatPlannedSegment] = []
    cursor = 0
    new_cursor = 0
    for edit in edits:
        if edit.replaced_length < 0:
            raise ValueError("Scheduled mdat edit length must be non-negative.")
        if edit.payload_offset < cursor:
            raise ValueError("Scheduled mdat edits must not overlap.")
        edit_end = edit.payload_offset + edit.replaced_length
        if edit.payload_offset < 0 or edit_end > box.payload_length:
            raise ValueError("Scheduled mdat edit is outside the mdat payload.")
        if edit.payload_offset > cursor:
            copy_length = edit.payload_offset - cursor
            segments.append(
                HeicMdatPlannedSegment(
                    mdat_index=box.mdat_index,
                    kind="copy",
                    old_payload_offset=box.payload_file_offset + cursor,
                    old_payload_end=box.payload_file_offset + edit.payload_offset,
                    new_payload_relative_offset=new_cursor,
                    length=copy_length,
                )
            )
            new_cursor += copy_length
        if edit.replacement or edit.kind == "replace":
            replacement_length = len(edit.replacement)
            segments.append(
                HeicMdatPlannedSegment(
                    mdat_index=box.mdat_index,
                    kind="replacement",
                    old_payload_offset=box.payload_file_offset + edit.payload_offset,
                    old_payload_end=box.payload_file_offset + edit_end,
                    new_payload_relative_offset=new_cursor,
                    length=replacement_length,
                    item_id=edit.item_id,
                )
            )
            new_cursor += replacement_length
        cursor = edit_end
    if cursor < box.payload_length:
        copy_length = box.payload_length - cursor
        segments.append(
            HeicMdatPlannedSegment(
                mdat_index=box.mdat_index,
                kind="copy",
                old_payload_offset=box.payload_file_offset + cursor,
                old_payload_end=box.payload_file_offset + box.payload_length,
                new_payload_relative_offset=new_cursor,
                length=copy_length,
            )
        )
    return tuple(segments)


def parse_iinf_payload(payload: bytes) -> HeicIinfBox:
    header, body = parse_full_box_payload(payload)
    if header.version == 0:
        if len(body) < 2:
            raise ValueError("Truncated iinf item count.")
        count = int.from_bytes(body[:2], "big")
        child_start = 2
    else:
        if len(body) < 4:
            raise ValueError("Truncated iinf item count.")
        count = int.from_bytes(body[:4], "big")
        child_start = 4
    entries = tuple(
        parse_infe_payload(atom.payload)
        for atom in read_heic_atom_spans(body, child_start, len(body))
        if atom.atom_type == "infe"
    )
    if count != len(entries):
        raise ValueError("iinf item count does not match parsed infe entries.")
    return HeicIinfBox(version=header.version, entries=entries)


def encode_iinf_payload(iinf: HeicIinfBox) -> bytes:
    if iinf.version == 0:
        if len(iinf.entries) > 0xFFFF:
            raise ValueError("iinf version 0 item count overflow.")
        count = len(iinf.entries).to_bytes(2, "big")
    else:
        count = len(iinf.entries).to_bytes(4, "big")
    children = tuple(HeicAtom("infe", encode_infe_payload(entry)) for entry in iinf.entries)
    return encode_full_box_payload(iinf.version, 0, count + encode_heic_atoms(children))


def append_iinf_entry(payload: bytes, entry: HeicInfeEntry) -> bytes:
    iinf = parse_iinf_payload(payload)
    return encode_iinf_payload(HeicIinfBox(version=iinf.version, entries=(*iinf.entries, entry)))


def parse_infe_payload(payload: bytes) -> HeicInfeEntry:
    header, body = parse_full_box_payload(payload)
    pos = 0
    if header.version in {0, 1}:
        if len(body) < 4:
            raise ValueError("Truncated legacy infe header.")
        item_id = int.from_bytes(body[pos : pos + 2], "big")
        protection_index = int.from_bytes(body[pos + 2 : pos + 4], "big")
        pos += 4
        item_name, pos = read_null_string(body, pos)
        legacy_content_type, pos = read_null_string(body, pos)
        legacy_content_encoding, _pos = read_null_string(body, pos)
        return HeicInfeEntry(
            item_id=item_id,
            item_type="mime",
            item_name=item_name,
            content_type=legacy_content_type or None,
            content_encoding=legacy_content_encoding or None,
            protection_index=protection_index,
        )
    if header.version == 2:
        if len(body) < 8:
            raise ValueError("Truncated infe version 2 header.")
        item_id = int.from_bytes(body[pos : pos + 2], "big")
        pos += 2
    elif header.version == 3:
        if len(body) < 10:
            raise ValueError("Truncated infe version 3 header.")
        item_id = int.from_bytes(body[pos : pos + 4], "big")
        pos += 4
    else:
        raise ValueError(f"Unsupported infe version {header.version}.")
    protection_index = int.from_bytes(body[pos : pos + 2], "big")
    item_type = heic_item_type(body[pos + 2 : pos + 6].decode("latin-1"))
    pos += 6
    item_name, pos = read_null_string(body, pos)
    content_type: str | None = None
    content_encoding: str | None = None
    if item_type == "mime":
        content_type, pos = read_null_string(body, pos)
        content_encoding, _pos = read_null_string(body, pos)
    return HeicInfeEntry(
        item_id=item_id,
        item_type=item_type,
        item_name=item_name,
        content_type=content_type or None,
        content_encoding=content_encoding or None,
        protection_index=protection_index,
    )


def encode_infe_payload(entry: HeicInfeEntry) -> bytes:
    version = 2 if entry.item_id <= 0xFFFF else 3
    item_id = uint_bytes(entry.item_id, 2 if version == 2 else 4)
    item_type = entry.item_type.encode("latin-1")
    fields = item_id + uint_bytes(entry.protection_index, 2) + item_type
    fields += null_string(entry.item_name)
    if entry.item_type == "mime":
        fields += null_string(entry.content_type or "")
        fields += null_string(entry.content_encoding or "")
    elif entry.content_type is not None or entry.content_encoding is not None:
        raise ValueError("Only mime infe entries may carry content type or encoding strings.")
    return encode_full_box_payload(version, 0, fields)


def xmp_infe_entry(item_id: int, *, content_encoding: str | None = None) -> HeicInfeEntry:
    return HeicInfeEntry(
        item_id=item_id,
        item_type="mime",
        item_name="",
        content_type=XMP_MIME_TYPE,
        content_encoding=content_encoding,
        protection_index=0,
    )


def parse_iref_payload(payload: bytes) -> HeicIrefBox:
    header, body = parse_full_box_payload(payload)
    references = tuple(
        parse_cdsc_payload(atom.payload, header.version)
        for atom in read_heic_atom_spans(body, 0, len(body))
        if atom.atom_type == "cdsc"
    )
    return HeicIrefBox(version=header.version, cdsc_references=references)


def encode_iref_payload(iref: HeicIrefBox) -> bytes:
    children = tuple(
        HeicAtom("cdsc", encode_cdsc_payload(reference, iref.version))
        for reference in iref.cdsc_references
    )
    return encode_full_box_payload(iref.version, 0, encode_heic_atoms(children))


def append_iref_cdsc_reference(payload: bytes, reference: HeicCdscReference) -> bytes:
    iref = parse_iref_payload(payload)
    return encode_iref_payload(
        HeicIrefBox(
            version=iref.version,
            cdsc_references=(*iref.cdsc_references, reference),
        )
    )


def parse_cdsc_payload(payload: bytes, iref_version: int) -> HeicCdscReference:
    id_size = 2 if iref_version == 0 else 4
    header_size = id_size + 2
    if len(payload) < header_size:
        raise ValueError("Truncated cdsc payload.")
    from_item_id = int.from_bytes(payload[:id_size], "big")
    count = int.from_bytes(payload[id_size:header_size], "big")
    expected_size = header_size + count * id_size
    if len(payload) < expected_size:
        raise ValueError("Truncated cdsc reference list.")
    to_item_ids = tuple(
        int.from_bytes(payload[pos : pos + id_size], "big")
        for pos in range(header_size, expected_size, id_size)
    )
    return HeicCdscReference(from_item_id=from_item_id, to_item_ids=to_item_ids)


def encode_cdsc_payload(reference: HeicCdscReference, iref_version: int) -> bytes:
    id_size = 2 if iref_version == 0 else 4
    if len(reference.to_item_ids) > 0xFFFF:
        raise ValueError("cdsc reference count overflow.")
    return (
        uint_bytes(reference.from_item_id, id_size)
        + len(reference.to_item_ids).to_bytes(2, "big")
        + b"".join(uint_bytes(item_id, id_size) for item_id in reference.to_item_ids)
    )


def parse_iloc_payload(payload: bytes) -> HeicIlocBox:
    header, body = parse_full_box_payload(payload)
    if len(body) < 4:
        raise ValueError("Truncated iloc size and count header.")
    size_bits = int.from_bytes(body[:2], "big")
    offset_size = (size_bits >> 12) & 0x0F
    length_size = (size_bits >> 8) & 0x0F
    base_offset_size = (size_bits >> 4) & 0x0F
    index_size = size_bits & 0x0F
    validate_iloc_size(offset_size)
    validate_iloc_size(length_size)
    validate_iloc_size(base_offset_size)
    validate_iloc_size(index_size)
    if header.version < 2:
        count = int.from_bytes(body[2:4], "big")
        pos = 4
    else:
        if len(body) < 6:
            raise ValueError("Truncated iloc version 2 count.")
        count = int.from_bytes(body[2:6], "big")
        pos = 6
    items: list[HeicIlocItemEntry] = []
    for _index in range(count):
        item, pos = parse_iloc_item_entry(
            body,
            pos,
            header.version,
            offset_size,
            length_size,
            base_offset_size,
            index_size,
        )
        items.append(item)
    return HeicIlocBox(
        version=header.version,
        offset_size=offset_size,
        length_size=length_size,
        base_offset_size=base_offset_size,
        index_size=index_size,
        items=tuple(items),
    )


def encode_iloc_payload(iloc: HeicIlocBox) -> bytes:
    validate_iloc_box(iloc)
    size_bits = (
        (iloc.offset_size << 12)
        | (iloc.length_size << 8)
        | (iloc.base_offset_size << 4)
        | iloc.index_size
    )
    if iloc.version < 2:
        if len(iloc.items) > 0xFFFF:
            raise ValueError("iloc item count overflow.")
        count = len(iloc.items).to_bytes(2, "big")
    else:
        count = len(iloc.items).to_bytes(4, "big")
    entries = b"".join(encode_iloc_item_entry(item, iloc) for item in iloc.items)
    return encode_full_box_payload(iloc.version, 0, size_bits.to_bytes(2, "big") + count + entries)


def append_iloc_item(payload: bytes, item: HeicIlocItemEntry) -> bytes:
    iloc = parse_iloc_payload(payload)
    return encode_iloc_payload(
        HeicIlocBox(
            version=iloc.version,
            offset_size=iloc.offset_size,
            length_size=iloc.length_size,
            base_offset_size=iloc.base_offset_size,
            index_size=iloc.index_size,
            items=(*iloc.items, item),
        )
    )


def replace_iloc_item_extent_lengths(
    payload: bytes,
    *,
    item_id: int,
    replacement_length: int,
) -> bytes:
    """Rewrite an existing item's extent lengths after mdat replacement.

    ExifTool stores the whole rewritten metadata directory in the first extent
    and sets any remaining extents to zero length after scheduling them for
    deletion from media data.
    """

    if replacement_length < 0:
        raise ValueError("Replacement extent length must be non-negative.")
    iloc = parse_iloc_payload(payload)
    rewritten_items: list[HeicIlocItemEntry] = []
    found_item = False
    for item in iloc.items:
        if item.item_id != item_id:
            rewritten_items.append(item)
            continue
        if not item.extents:
            raise ValueError("Existing ItemInfo metadata item has no extents.")
        found_item = True
        rewritten_extents = tuple(
            HeicIlocExtent(
                extent_index=extent.extent_index,
                extent_offset=extent.extent_offset,
                extent_length=replacement_length if index == 0 else 0,
            )
            for index, extent in enumerate(item.extents)
        )
        rewritten_items.append(
            HeicIlocItemEntry(
                item_id=item.item_id,
                construction_method=item.construction_method,
                data_reference_index=item.data_reference_index,
                base_offset=item.base_offset,
                extents=rewritten_extents,
            )
        )
    if not found_item:
        raise ValueError(f"Missing iloc item {item_id}.")
    return encode_iloc_payload(
        HeicIlocBox(
            version=iloc.version,
            offset_size=iloc.offset_size,
            length_size=iloc.length_size,
            base_offset_size=iloc.base_offset_size,
            index_size=iloc.index_size,
            items=tuple(rewritten_items),
        )
    )


def plan_item_info_extent_replacement(
    iloc_payload: bytes,
    *,
    item: HeicIlocItemEntry,
    replacement: bytes,
    mdat_boxes: tuple[HeicMdatBoxPlan, ...],
) -> HeicItemInfoExtentReplacementPlan:
    """Plan replacement/deletion of an existing ItemInfo item's mdat extents."""

    if item.construction_method != 0:
        raise ValueError("Existing ItemInfo mdat replacement requires construction method 0.")
    if item.data_reference_index != 0:
        raise ValueError("Existing ItemInfo mdat replacement requires data in this file.")
    if not item.extents:
        raise ValueError("Existing ItemInfo metadata item has no extents.")

    edits: list[HeicMdatEdit] = []
    for index, extent in enumerate(item.extents):
        absolute_start = item.base_offset + extent.extent_offset
        absolute_end = absolute_start + extent.extent_length
        mdat_box = mdat_box_for_extent(mdat_boxes, absolute_start, absolute_end)
        edit_replacement = replacement if index == 0 else b""
        if extent.extent_length == 0 and not edit_replacement:
            continue
        edits.append(
            HeicMdatEdit(
                item_id=item.item_id,
                mdat_index=mdat_box.mdat_index,
                payload_offset=absolute_start - mdat_box.payload_file_offset,
                replaced_length=extent.extent_length,
                replacement=edit_replacement,
                kind="replace" if index == 0 else "delete",
            )
        )
    return HeicItemInfoExtentReplacementPlan(
        item_id=item.item_id,
        iloc_payload=replace_iloc_item_extent_lengths(
            iloc_payload,
            item_id=item.item_id,
            replacement_length=len(replacement),
        ),
        scheduled_mdat_edits=HeicScheduledMdatEdits(edits=tuple(edits)),
    )


def mdat_box_for_extent(
    mdat_boxes: tuple[HeicMdatBoxPlan, ...],
    absolute_start: int,
    absolute_end: int,
) -> HeicMdatBoxPlan:
    if absolute_start < 0 or absolute_end < absolute_start:
        raise ValueError("Invalid ItemInfo extent range.")
    for box in mdat_boxes:
        payload_start = box.payload_file_offset
        payload_end = box.payload_file_offset + box.payload_length
        if absolute_start >= payload_start and absolute_end <= payload_end:
            return box
    raise ValueError("ItemInfo extent runs outside known mdat media data.")


def mdat_iloc_item(
    item_id: int,
    payload_length: int,
    iloc: HeicIlocBox,
    *,
    extent_offset: int,
) -> HeicIlocItemEntry:
    if payload_length < 0:
        raise ValueError("iloc extent length must be non-negative.")
    if iloc.offset_size == 0:
        if iloc.base_offset_size not in {4, 8}:
            raise ValueError("iloc offset_size 0 requires a 4- or 8-byte base_offset_size.")
        base_offset = extent_offset
        stored_extent_offset = 0
    else:
        base_offset = 0
        stored_extent_offset = extent_offset
    return HeicIlocItemEntry(
        item_id=item_id,
        construction_method=0,
        data_reference_index=0,
        base_offset=base_offset,
        extents=(
            HeicIlocExtent(
                extent_index=0,
                extent_offset=stored_extent_offset,
                extent_length=payload_length,
            ),
        ),
    )


def schedule_mdat_prepend(
    item_id: int,
    payload: bytes,
    *,
    mdat_index: int = 0,
) -> HeicScheduledMdatEdits:
    return HeicScheduledMdatEdits(
        edits=(
            HeicMdatEdit(
                item_id=item_id,
                mdat_index=mdat_index,
                payload_offset=0,
                replaced_length=0,
                replacement=payload,
                kind="insert",
            ),
        )
    )


def apply_scheduled_mdat_edits_to_payload(
    payload: bytes,
    schedule: HeicScheduledMdatEdits,
    *,
    mdat_index: int = 0,
) -> bytes:
    edits = tuple(edit for edit in schedule.edits if edit.mdat_index == mdat_index)
    rewritten = payload
    applied_delta = 0
    for edit in sorted(edits, key=lambda candidate: candidate.payload_offset):
        start = edit.payload_offset + applied_delta
        end = start + edit.replaced_length
        if start < 0 or end > len(rewritten):
            raise ValueError("Scheduled mdat edit is outside the payload.")
        rewritten = rewritten[:start] + edit.replacement + rewritten[end:]
        applied_delta += edit.length_delta
    return rewritten


def parse_full_box_payload(payload: bytes) -> tuple[HeicFullBoxHeader, bytes]:
    if len(payload) < 4:
        raise ValueError("Truncated HEIC full-box header.")
    return (
        HeicFullBoxHeader(version=payload[0], flags=int.from_bytes(payload[1:4], "big")),
        payload[4:],
    )


def encode_full_box_payload(version: int, flags: int, body: bytes) -> bytes:
    if version < 0 or version > 0xFF:
        raise ValueError("Full-box version must fit in one byte.")
    if flags < 0 or flags > 0xFFFFFF:
        raise ValueError("Full-box flags must fit in three bytes.")
    return bytes((version,)) + flags.to_bytes(3, "big") + body


def parse_iloc_item_entry(
    payload: bytes,
    pos: int,
    version: int,
    offset_size: int,
    length_size: int,
    base_offset_size: int,
    index_size: int,
) -> tuple[HeicIlocItemEntry, int]:
    item_id_size = 2 if version < 2 else 4
    item_id = read_uint(payload, pos, item_id_size)
    pos += item_id_size
    construction_method = 0
    if version in {1, 2}:
        construction_method = read_uint(payload, pos, 2) & 0x0F
        pos += 2
    data_reference_index = read_uint(payload, pos, 2)
    pos += 2
    base_offset = read_uint(payload, pos, base_offset_size)
    pos += base_offset_size
    extent_count = read_uint(payload, pos, 2)
    pos += 2
    extents: list[HeicIlocExtent] = []
    for _index in range(extent_count):
        extent_index = 0
        if version in {1, 2}:
            extent_index = read_uint(payload, pos, index_size)
            pos += index_size
        extent_offset = read_uint(payload, pos, offset_size)
        pos += offset_size
        extent_length = read_uint(payload, pos, length_size)
        pos += length_size
        extents.append(
            HeicIlocExtent(
                extent_index=extent_index,
                extent_offset=extent_offset,
                extent_length=extent_length,
            )
        )
    return (
        HeicIlocItemEntry(
            item_id=item_id,
            construction_method=construction_method,
            data_reference_index=data_reference_index,
            base_offset=base_offset,
            extents=tuple(extents),
        ),
        pos,
    )


def encode_iloc_item_entry(item: HeicIlocItemEntry, iloc: HeicIlocBox) -> bytes:
    item_id_size = 2 if iloc.version < 2 else 4
    encoded = uint_bytes(item.item_id, item_id_size)
    if iloc.version in {1, 2}:
        encoded += uint_bytes(item.construction_method, 2)
    encoded += uint_bytes(item.data_reference_index, 2)
    encoded += uint_bytes(item.base_offset, iloc.base_offset_size)
    if len(item.extents) > 0xFFFF:
        raise ValueError("iloc extent count overflow.")
    encoded += len(item.extents).to_bytes(2, "big")
    for extent in item.extents:
        if iloc.version in {1, 2}:
            encoded += uint_bytes(extent.extent_index, iloc.index_size)
        encoded += uint_bytes(extent.extent_offset, iloc.offset_size)
        encoded += uint_bytes(extent.extent_length, iloc.length_size)
    return encoded


def read_uint(payload: bytes, pos: int, size: int) -> int:
    if size == 0:
        return 0
    if pos + size > len(payload):
        raise ValueError("Truncated HEIC integer field.")
    return int.from_bytes(payload[pos : pos + size], "big")


def uint_bytes(value: int, size: int) -> bytes:
    if size == 0:
        if value:
            raise ValueError("Non-zero value cannot be stored in a zero-width field.")
        return b""
    max_value = (1 << (size * 8)) - 1
    if value < 0 or value > max_value:
        raise ValueError(f"Value {value} does not fit in {size} bytes.")
    return value.to_bytes(size, "big")


def validate_iloc_box(iloc: HeicIlocBox) -> None:
    if iloc.version not in {0, 1, 2}:
        raise ValueError(f"Unsupported iloc version {iloc.version}.")
    validate_iloc_size(iloc.offset_size)
    validate_iloc_size(iloc.length_size)
    validate_iloc_size(iloc.base_offset_size)
    validate_iloc_size(iloc.index_size)


def validate_iloc_size(size: int) -> None:
    if size not in {0, 4, 8}:
        raise ValueError("HEIC iloc variable integer sizes must be 0, 4, or 8 bytes.")


def read_null_string(payload: bytes, pos: int) -> tuple[str, int]:
    end = payload.find(b"\x00", pos)
    if end < 0:
        return payload[pos:].decode("latin-1"), len(payload)
    return payload[pos:end].decode("latin-1"), end + 1


def null_string(value: str) -> bytes:
    return value.encode("latin-1") + b"\x00"


def heic_item_type(value: str) -> HeicItemType:
    if len(value) != 4:
        raise ValueError(f"Unsupported HEIC item type {value!r}.")
    return value


def find_heic_atom(atoms: tuple[HeicAtomSpan, ...], atom_type: str) -> HeicAtomSpan | None:
    for atom in atoms:
        if atom.atom_type == atom_type:
            return atom
    return None


def required_heic_atom(atoms: tuple[HeicAtomSpan, ...], atom_type: str) -> HeicAtomSpan:
    atom = find_heic_atom(atoms, atom_type)
    if atom is None:
        raise ValueError(f"Missing required HEIC atom {atom_type}.")
    return atom
