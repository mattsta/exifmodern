"""Source-grounded HEIC ItemInfo/XMP write-surface classification.

ExifTool writes HEIC/HEIF XMP through the top-level QuickTime ``meta`` box's
ItemInformation path, not through MOV/MP4 ``moov`` metadata atoms.  This module
models that behavior and its blockers without pretending that partial atom
mutation is safe.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.heic.exif_item_info import (
    HEIC_EXIF_ITEM_TYPE,
    HEIC_EXIF_TIFF_HANDOFF_EVIDENCE_ID,
    HEIC_EXIF_TIFF_RESULT_EVIDENCE_ID,
)
from exifmodern.json_types import (
    JsonObject,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type HeicContainerKind = Literal["heic_item_info", "cr3_quicktime", "unsupported"]
type HeicItemInfoWriteStatus = Literal["runnable_item_info_rewrite", "deferred_item_info_rewrite"]
type HeicItemInfoOperation = Literal[
    "create_exif_item",
    "create_xmp_item",
    "rewrite_existing_exif_item",
    "rewrite_existing_xmp_item",
    "delete_existing_exif_item",
    "delete_existing_xmp_item",
    "unsupported_request",
]
type HeicItemInfoSurface = Literal[
    "heic_top_level_meta_item_information_exif",
    "heic_top_level_meta_item_information_xmp",
    "heic_iinf_infe_type_exif",
    "heic_iinf_infe_mime_xmp",
    "heic_iref_cdsc_primary_reference",
    "heic_iloc_mdat_chunk",
    "heic_existing_exif_item_rewrite",
    "heic_existing_xmp_item_rewrite",
    "heic_exif_header_tiff_payload",
    "cr3_top_level_xmp_uuid",
]
type HeicItemInfoBlockerCode = Literal[
    "requires_heic_item_info_atom_rebuild",
    "requires_iinf_iref_iloc_count_and_offset_fixups",
    "requires_mdat_chunk_insertion_and_offset_rewrite",
    "requires_existing_mdat_extent_replacement",
    "requires_exif_tiff_handoff",
    "compressed_metadata_requires_deflate_round_trip",
    "cannot_change_compression_when_rewriting_heic_metadata",
    "protected_metadata_not_decodable",
    "construction_method_not_supported_for_heic_write",
    "metadata_not_in_this_file",
    "missing_iinf_or_iloc_box",
    "unsupported_container_family",
    "unsupported_requested_tag",
]
type HeicItemInfoStorage = Literal[
    "no_existing_exif_item",
    "no_existing_xmp_item",
    "existing_exif_item",
    "existing_xmp_item",
    "existing_deflate_exif_item",
    "existing_deflate_xmp_item",
    "existing_protected_exif_item",
    "existing_protected_xmp_item",
    "existing_external_exif_item",
    "existing_external_xmp_item",
    "existing_unsupported_construction_method_exif_item",
    "existing_unsupported_construction_method_xmp_item",
    "missing_required_boxes",
    "unknown",
]

HEIC_ITEM_INFO_MAP_EVIDENCE_ID = "heic.item_info.map"
CR3_QUICKTIME_MAP_EVIDENCE_ID = "heic.item_info.cr3_map"
PARSE_ITEM_LOCATION_EVIDENCE_ID = "heic.item_info.parse_item_location"
PARSE_ITEM_INFO_EVIDENCE_ID = "heic.item_info.parse_item_info"
READ_ITEM_INFO_CONSTRAINT_EVIDENCE_ID = "heic.item_info.read_constraints"
WRITE_ITEM_INFO_SELECTION_EVIDENCE_ID = "heic.item_info.write_selection"
WRITE_ITEM_INFO_REWRITE_EVIDENCE_ID = "heic.item_info.write_rewrite"
WRITE_ITEM_INFO_CREATE_EVIDENCE_ID = "heic.item_info.write_create"
WRITE_ITEM_INFO_BOX_INSERT_EVIDENCE_ID = "heic.item_info.box_insert"
WRITE_MDAT_EDIT_EVIDENCE_ID = "heic.item_info.mdat_edit"
WRITE_OFFSET_FIXUP_EVIDENCE_ID = "heic.item_info.offset_fixup"
XMP_DC_TITLE_EVIDENCE_ID = "heic.item_info.xmp_dc_title"


@dataclass(frozen=True)
class HeicBoxSpan:
    atom_type: str
    offset: int
    size: int
    header_size: int
    payload: bytes


@dataclass(frozen=True)
class HeicIlocExtent:
    extent_offset: int
    extent_length: int
    offset_size: int
    length_size: int
    base_offset_size: int
    index_size: int


@dataclass(frozen=True)
class HeicItemInfoItem:
    item_id: int
    item_type: str
    content_type: str | None
    content_encoding: str | None
    protection_index: int
    construction_method: int
    data_reference_index: int
    base_offset: int
    extents: tuple[HeicIlocExtent, ...]
    refers_to_primary: bool

    @property
    def is_xmp(self) -> bool:
        return self.content_type == "application/rdf+xml"

    @property
    def is_exif(self) -> bool:
        return (self.content_type or self.item_type) == HEIC_EXIF_ITEM_TYPE


@dataclass(frozen=True)
class HeicItemInfoState:
    container_kind: HeicContainerKind
    major_brand: str | None
    compatible_brands: tuple[str, ...]
    has_top_level_meta: bool
    has_iinf: bool
    has_iloc: bool
    has_iref: bool
    has_mdat: bool
    has_idat: bool
    primary_item_id: int | None
    items: tuple[HeicItemInfoItem, ...]

    @property
    def primary_xmp_items(self) -> tuple[HeicItemInfoItem, ...]:
        return tuple(item for item in self.items if item.is_xmp and item.refers_to_primary)

    @property
    def primary_exif_items(self) -> tuple[HeicItemInfoItem, ...]:
        return tuple(item for item in self.items if item.is_exif and item.refers_to_primary)

    @property
    def next_item_id(self) -> int | None:
        if not self.items:
            return None
        return max(item.item_id for item in self.items) + 1


@dataclass(frozen=True)
class HeicItemInfoWriteTagClassification:
    requested_tag: str
    requested_value: str
    operation: HeicItemInfoOperation
    storage: HeicItemInfoStorage
    target_surfaces: tuple[HeicItemInfoSurface, ...]
    blocker_codes: tuple[HeicItemInfoBlockerCode, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocker_codes": list(self.blocker_codes),
            "operation": self.operation,
            "requested_tag": self.requested_tag,
            "requested_value": self.requested_value,
            "storage": self.storage,
            "target_surfaces": list(self.target_surfaces),
        }


@dataclass(frozen=True)
class HeicItemInfoWriteClassification:
    request_id: str
    fixture: str
    container_kind: HeicContainerKind
    status: HeicItemInfoWriteStatus
    supported_by_exiftool: bool
    supported_for_modern_mutation: bool
    state: HeicItemInfoState | None
    tags: tuple[HeicItemInfoWriteTagClassification, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        payload: JsonObject = {
            "container_kind": self.container_kind,
            "fixture": self.fixture,
            "request_id": self.request_id,
            "status": self.status,
            "supported_by_exiftool": self.supported_by_exiftool,
            "supported_for_modern_mutation": self.supported_for_modern_mutation,
            "tags": [tag.to_json() for tag in self.tags],
        }
        if self.state is not None:
            payload["state"] = heic_item_info_state_to_json(self.state)
        return payload


@dataclass(frozen=True)
class HeicItemInfoWriteRequestReport:
    requests: tuple[HeicItemInfoWriteClassification, ...]

    @property
    def request_count(self) -> int:
        return len(self.requests)

    @property
    def deferred_count(self) -> int:
        return sum(1 for request in self.requests if not request.supported_for_modern_mutation)

    def to_json(self) -> JsonObject:
        return {
            "deferred_count": self.deferred_count,
            "request_count": self.request_count,
            "requests": [request.to_json() for request in self.requests],
            "status": "deferred_item_info_rewrite",
        }


def classify_heic_item_info_golden_request_file(
    request_path: Path,
    *,
    exiftool_root: Path | None = None,
) -> HeicItemInfoWriteClassification:
    payload = load_json_object(request_path)
    fixture_data = None
    if exiftool_root is not None:
        fixture = required_string(payload, "fixture")
        fixture_path = exiftool_root / fixture
        if fixture_path.exists():
            fixture_data = fixture_path.read_bytes()
    return classify_heic_item_info_golden_request_payload(payload, fixture_data=fixture_data)


def classify_heic_item_info_golden_request_payload(
    payload: JsonObject,
    *,
    fixture_data: bytes | None = None,
) -> HeicItemInfoWriteClassification:
    fixture = required_string(payload, "fixture")
    request_id = required_string(payload, "request_id")
    state = parse_heic_item_info_state(fixture_data) if fixture_data is not None else None
    container_kind = (
        state.container_kind if state is not None else container_kind_for_fixture(fixture)
    )
    tags = tuple(
        classify_write_arg(write_arg, container_kind, state)
        for write_arg in json_string_array_value(payload, "write_args")
        if is_metadata_assignment_arg(write_arg)
    )
    supported_for_modern_mutation = is_supported_modern_item_info_creation(
        container_kind,
        state,
        tags,
    )
    if supported_for_modern_mutation:
        tags = tuple(
            tag_with_blockers(tag, ())
            if tag.operation == "create_xmp_item" and tag.storage == "no_existing_xmp_item"
            else tag
            for tag in tags
        )
    return HeicItemInfoWriteClassification(
        request_id=request_id,
        fixture=fixture,
        container_kind=container_kind,
        status=(
            "runnable_item_info_rewrite"
            if supported_for_modern_mutation
            else "deferred_item_info_rewrite"
        ),
        supported_by_exiftool=all(tag.operation != "unsupported_request" for tag in tags),
        supported_for_modern_mutation=supported_for_modern_mutation,
        state=state,
        tags=tags,
        evidence_ids=container_evidence_ids(container_kind),
    )


def is_supported_modern_item_info_creation(
    container_kind: HeicContainerKind,
    state: HeicItemInfoState | None,
    tags: tuple[HeicItemInfoWriteTagClassification, ...],
) -> bool:
    """Return true for the source-backed new-XMP ItemInfo shape the emitter handles."""

    if container_kind != "heic_item_info" or state is None or not tags:
        return False
    if not (
        state.has_top_level_meta
        and state.has_iinf
        and state.has_iloc
        and state.has_mdat
        and state.primary_item_id is not None
    ):
        return False
    return all(
        tag.operation == "create_xmp_item"
        and tag.storage == "no_existing_xmp_item"
        and tag.requested_value != ""
        and tag.requested_tag.lower().startswith("xmp")
        for tag in tags
    )


def tag_with_blockers(
    tag: HeicItemInfoWriteTagClassification,
    blockers: tuple[HeicItemInfoBlockerCode, ...],
) -> HeicItemInfoWriteTagClassification:
    return HeicItemInfoWriteTagClassification(
        requested_tag=tag.requested_tag,
        requested_value=tag.requested_value,
        operation=tag.operation,
        storage=tag.storage,
        target_surfaces=tag.target_surfaces,
        blocker_codes=blockers,
        evidence_ids=tag.evidence_ids,
    )


def build_heic_item_info_write_request_report(
    request_paths: tuple[Path, ...],
    *,
    exiftool_root: Path | None = None,
) -> HeicItemInfoWriteRequestReport:
    return HeicItemInfoWriteRequestReport(
        requests=tuple(
            classify_heic_item_info_golden_request_file(path, exiftool_root=exiftool_root)
            for path in request_paths
        )
    )


def write_heic_item_info_write_request_report(
    request_paths: tuple[Path, ...],
    output_path: Path,
    *,
    exiftool_root: Path | None = None,
) -> HeicItemInfoWriteRequestReport:
    report = build_heic_item_info_write_request_report(
        request_paths,
        exiftool_root=exiftool_root,
    )
    output_path.write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def classify_write_arg(
    write_arg: str,
    container_kind: HeicContainerKind,
    state: HeicItemInfoState | None = None,
) -> HeicItemInfoWriteTagClassification:
    requested_tag, requested_value = split_assignment_arg(write_arg)
    if container_kind == "cr3_quicktime":
        return HeicItemInfoWriteTagClassification(
            requested_tag=requested_tag,
            requested_value=requested_value,
            operation="unsupported_request",
            storage="unknown",
            target_surfaces=("cr3_top_level_xmp_uuid",),
            blocker_codes=("unsupported_container_family",),
            evidence_ids=(CR3_QUICKTIME_MAP_EVIDENCE_ID, WRITE_OFFSET_FIXUP_EVIDENCE_ID),
        )
    requested_tag_lower = requested_tag.lower()
    requested_group: Literal["exif", "xmp", "unsupported"]
    if requested_tag_lower.startswith("exif"):
        requested_group = "exif"
    elif requested_tag_lower.startswith("xmp"):
        requested_group = "xmp"
    else:
        requested_group = "unsupported"
    if requested_group == "unsupported":
        return HeicItemInfoWriteTagClassification(
            requested_tag=requested_tag,
            requested_value=requested_value,
            operation="unsupported_request",
            storage="unknown",
            target_surfaces=(),
            blocker_codes=("unsupported_requested_tag",),
            evidence_ids=container_evidence_ids(container_kind),
        )
    if container_kind != "heic_item_info":
        return HeicItemInfoWriteTagClassification(
            requested_tag=requested_tag,
            requested_value=requested_value,
            operation="unsupported_request",
            storage="unknown",
            target_surfaces=(),
            blocker_codes=("unsupported_container_family",),
            evidence_ids=container_evidence_ids(container_kind),
        )
    operation: HeicItemInfoOperation
    storage: HeicItemInfoStorage = "unknown"
    if requested_group == "exif":
        operation = "delete_existing_exif_item" if requested_value == "" else "create_exif_item"
        if state is not None:
            storage = storage_for_state(state, metadata_kind="exif")
            if state.primary_exif_items and requested_value != "":
                operation = "rewrite_existing_exif_item"
    else:
        operation = "delete_existing_xmp_item" if requested_value == "" else "create_xmp_item"
        if state is not None:
            storage = storage_for_state(state, metadata_kind="xmp")
            if state.primary_xmp_items and requested_value != "":
                operation = "rewrite_existing_xmp_item"
    surfaces = surfaces_for_operation(operation)
    blockers = blocker_codes_for_operation(operation, storage)
    evidence_ids = evidence_ids_for_operation(operation, requested_tag, storage)
    return HeicItemInfoWriteTagClassification(
        requested_tag=requested_tag,
        requested_value=requested_value,
        operation=operation,
        storage=storage,
        target_surfaces=surfaces,
        blocker_codes=blockers,
        evidence_ids=evidence_ids,
    )


def parse_heic_item_info_state(data: bytes) -> HeicItemInfoState:
    top_boxes = read_box_spans(data, 0, len(data))
    ftyp = first_box(top_boxes, "ftyp")
    major_brand, compatible_brands = parse_ftyp(ftyp.payload if ftyp is not None else b"")
    container_kind = container_kind_for_brands(major_brand, compatible_brands)
    meta = first_box(top_boxes, "meta")
    mdat_boxes = tuple(box for box in top_boxes if box.atom_type == "mdat")
    if meta is None:
        return HeicItemInfoState(
            container_kind=container_kind,
            major_brand=major_brand,
            compatible_brands=compatible_brands,
            has_top_level_meta=False,
            has_iinf=False,
            has_iloc=False,
            has_iref=False,
            has_mdat=bool(mdat_boxes),
            has_idat=False,
            primary_item_id=None,
            items=(),
        )
    meta_children = read_box_spans(meta.payload, 4, len(meta.payload))
    pitm = first_box(meta_children, "pitm")
    iinf = first_box(meta_children, "iinf")
    iloc = first_box(meta_children, "iloc")
    iref = first_box(meta_children, "iref")
    idat = first_box(meta_children, "idat")
    primary_item_id = parse_pitm(pitm.payload) if pitm is not None else None
    item_map = parse_iinf_items(iinf.payload if iinf is not None else b"")
    location_map = parse_iloc_items(iloc.payload if iloc is not None else b"")
    ref_map = parse_iref_cdsc(iref.payload if iref is not None else b"")
    items: list[HeicItemInfoItem] = []
    for item_id in sorted(item_map):
        info = item_map[item_id]
        location = location_map.get(item_id)
        refers_to_primary = primary_item_id is not None and primary_item_id in ref_map.get(
            item_id, ()
        )
        if primary_item_id is not None and item_id == primary_item_id:
            refers_to_primary = True
        items.append(
            HeicItemInfoItem(
                item_id=item_id,
                item_type=info.item_type,
                content_type=info.content_type,
                content_encoding=info.content_encoding,
                protection_index=info.protection_index,
                construction_method=location.construction_method if location is not None else 0,
                data_reference_index=location.data_reference_index if location is not None else 0,
                base_offset=location.base_offset if location is not None else 0,
                extents=location.extents if location is not None else (),
                refers_to_primary=refers_to_primary,
            )
        )
    return HeicItemInfoState(
        container_kind=container_kind,
        major_brand=major_brand,
        compatible_brands=compatible_brands,
        has_top_level_meta=True,
        has_iinf=iinf is not None,
        has_iloc=iloc is not None,
        has_iref=iref is not None,
        has_mdat=bool(mdat_boxes),
        has_idat=idat is not None,
        primary_item_id=primary_item_id,
        items=tuple(items),
    )


@dataclass(frozen=True)
class ParsedInfeItem:
    item_type: str
    content_type: str | None
    content_encoding: str | None
    protection_index: int


@dataclass(frozen=True)
class ParsedIlocItem:
    construction_method: int
    data_reference_index: int
    base_offset: int
    extents: tuple[HeicIlocExtent, ...]


def read_box_spans(data: bytes, start: int, end: int) -> tuple[HeicBoxSpan, ...]:
    boxes: list[HeicBoxSpan] = []
    offset = start
    while offset + 8 <= end:
        size = int.from_bytes(data[offset : offset + 4], "big")
        atom_type = data[offset + 4 : offset + 8].decode("latin-1")
        header_size = 8
        if size == 1:
            if offset + 16 > end:
                break
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header_size = 16
        elif size == 0:
            size = end - offset
        if size < header_size or offset + size > end:
            break
        payload_start = offset + header_size
        boxes.append(
            HeicBoxSpan(
                atom_type=atom_type,
                offset=offset,
                size=size,
                header_size=header_size,
                payload=data[payload_start : offset + size],
            )
        )
        offset += size
    return tuple(boxes)


def parse_ftyp(payload: bytes) -> tuple[str | None, tuple[str, ...]]:
    if len(payload) < 8:
        return None, ()
    major_brand = payload[:4].decode("latin-1")
    brands = [major_brand]
    pos = 8
    while pos + 4 <= len(payload):
        brands.append(payload[pos : pos + 4].decode("latin-1"))
        pos += 4
    return major_brand, tuple(brands)


def parse_pitm(payload: bytes) -> int | None:
    if len(payload) < 6:
        return None
    version = payload[0]
    if version == 0:
        return int.from_bytes(payload[4:6], "big")
    if len(payload) < 8:
        return None
    return int.from_bytes(payload[4:8], "big")


def parse_iinf_items(payload: bytes) -> dict[int, ParsedInfeItem]:
    if len(payload) < 6:
        return {}
    version = payload[0]
    pos = 6 if version == 0 else 8
    if pos > len(payload):
        return {}
    items: dict[int, ParsedInfeItem] = {}
    for box in read_box_spans(payload, pos, len(payload)):
        if box.atom_type != "infe":
            continue
        parsed = parse_infe(box.payload)
        if parsed is not None:
            item_id, item = parsed
            items[item_id] = item
    return items


def parse_infe(payload: bytes) -> tuple[int, ParsedInfeItem] | None:
    if len(payload) < 8:
        return None
    version = payload[0]
    pos = 4
    if version in {0, 1}:
        if pos + 4 > len(payload):
            return None
        item_id = int.from_bytes(payload[pos : pos + 2], "big")
        protection_index = int.from_bytes(payload[pos + 2 : pos + 4], "big")
        pos += 4
        name, pos = read_null_string(payload, pos)
        legacy_content_type, pos = read_null_string(payload, pos)
        legacy_content_encoding, pos = read_null_string(payload, pos)
        return item_id, ParsedInfeItem(
            item_type=name,
            content_type=legacy_content_type or None,
            content_encoding=legacy_content_encoding or None,
            protection_index=protection_index,
        )
    if version == 2:
        if pos + 8 > len(payload):
            return None
        item_id = int.from_bytes(payload[pos : pos + 2], "big")
        pos += 2
    elif version == 3:
        if pos + 10 > len(payload):
            return None
        item_id = int.from_bytes(payload[pos : pos + 4], "big")
        pos += 4
    else:
        return None
    protection_index = int.from_bytes(payload[pos : pos + 2], "big")
    item_type = payload[pos + 2 : pos + 6].decode("latin-1")
    pos += 6
    _name, pos = read_null_string(payload, pos)
    content_type: str | None = None
    content_encoding: str | None = None
    if item_type == "mime":
        content_type, pos = read_null_string(payload, pos)
        content_encoding, pos = read_null_string(payload, pos)
    return item_id, ParsedInfeItem(
        item_type=item_type,
        content_type=content_type or None,
        content_encoding=content_encoding or None,
        protection_index=protection_index,
    )


def parse_iloc_items(payload: bytes) -> dict[int, ParsedIlocItem]:
    if len(payload) < 8:
        return {}
    version = payload[0]
    size_bits = int.from_bytes(payload[4:6], "big")
    offset_size = (size_bits >> 12) & 0x0F
    length_size = (size_bits >> 8) & 0x0F
    base_offset_size = (size_bits >> 4) & 0x0F
    index_size = size_bits & 0x0F
    if version < 2:
        count = int.from_bytes(payload[6:8], "big")
        pos = 8
    else:
        if len(payload) < 10:
            return {}
        count = int.from_bytes(payload[6:10], "big")
        pos = 10
    items: dict[int, ParsedIlocItem] = {}
    for _index in range(count):
        item_id, pos = read_item_id(payload, pos, version)
        if item_id is None or pos + 2 > len(payload):
            return items
        construction_method = 0
        if version in {1, 2}:
            construction_method = int.from_bytes(payload[pos : pos + 2], "big") & 0x0F
            pos += 2
            if pos + 2 > len(payload):
                return items
        data_reference_index = int.from_bytes(payload[pos : pos + 2], "big")
        pos += 2
        base_offset, pos = read_var_int(payload, pos, base_offset_size)
        if base_offset is None or pos + 2 > len(payload):
            return items
        extent_count = int.from_bytes(payload[pos : pos + 2], "big")
        pos += 2
        extents: list[HeicIlocExtent] = []
        for _extent_index in range(extent_count):
            if version in {1, 2}:
                _ignored_index, pos = read_var_int(payload, pos, index_size)
            extent_offset, pos = read_var_int(payload, pos, offset_size)
            extent_length, pos = read_var_int(payload, pos, length_size)
            if extent_offset is None or extent_length is None:
                return items
            extents.append(
                HeicIlocExtent(
                    extent_offset=extent_offset,
                    extent_length=extent_length,
                    offset_size=offset_size,
                    length_size=length_size,
                    base_offset_size=base_offset_size,
                    index_size=index_size,
                )
            )
        items[item_id] = ParsedIlocItem(
            construction_method=construction_method,
            data_reference_index=data_reference_index,
            base_offset=base_offset,
            extents=tuple(extents),
        )
    return items


def parse_iref_cdsc(payload: bytes) -> dict[int, tuple[int, ...]]:
    if len(payload) < 4:
        return {}
    version = payload[0]
    refs: dict[int, tuple[int, ...]] = {}
    for box in read_box_spans(payload, 4, len(payload)):
        if box.atom_type != "cdsc":
            continue
        if version == 0:
            if len(box.payload) < 6:
                continue
            from_item = int.from_bytes(box.payload[0:2], "big")
            count = int.from_bytes(box.payload[2:4], "big")
            pos = 4
            id_size = 2
        else:
            if len(box.payload) < 10:
                continue
            from_item = int.from_bytes(box.payload[0:4], "big")
            count = int.from_bytes(box.payload[4:6], "big")
            pos = 6
            id_size = 4
        to_items: list[int] = []
        for _index in range(count):
            if pos + id_size > len(box.payload):
                break
            to_items.append(int.from_bytes(box.payload[pos : pos + id_size], "big"))
            pos += id_size
        refs[from_item] = tuple(to_items)
    return refs


def read_item_id(payload: bytes, pos: int, version: int) -> tuple[int | None, int]:
    item_id_size = 2 if version < 2 else 4
    if pos + item_id_size > len(payload):
        return None, pos
    return int.from_bytes(payload[pos : pos + item_id_size], "big"), pos + item_id_size


def read_var_int(payload: bytes, pos: int, size: int) -> tuple[int | None, int]:
    if size == 0:
        return 0, pos
    if size not in {4, 8} or pos + size > len(payload):
        return None, pos
    return int.from_bytes(payload[pos : pos + size], "big"), pos + size


def read_null_string(payload: bytes, pos: int) -> tuple[str, int]:
    end = payload.find(b"\x00", pos)
    if end < 0:
        return payload[pos:].decode("latin-1"), len(payload)
    return payload[pos:end].decode("latin-1"), end + 1


def first_box(boxes: tuple[HeicBoxSpan, ...], atom_type: str) -> HeicBoxSpan | None:
    for box in boxes:
        if box.atom_type == atom_type:
            return box
    return None


def container_kind_for_fixture(fixture: str) -> HeicContainerKind:
    suffix = Path(fixture).suffix.lower()
    if suffix in {".heic", ".heif", ".hif", ".avif"}:
        return "heic_item_info"
    if suffix == ".cr3":
        return "cr3_quicktime"
    return "unsupported"


def container_kind_for_brands(
    major_brand: str | None,
    compatible_brands: tuple[str, ...],
) -> HeicContainerKind:
    brands = set(compatible_brands)
    if "crx " in brands or major_brand == "crx ":
        return "cr3_quicktime"
    if brands & {"heic", "mif1", "avif"}:
        return "heic_item_info"
    return "unsupported"


def storage_for_state(
    state: HeicItemInfoState,
    *,
    metadata_kind: Literal["exif", "xmp"],
) -> HeicItemInfoStorage:
    if not state.has_iinf or not state.has_iloc:
        return "missing_required_boxes"
    metadata_items = (
        state.primary_exif_items if metadata_kind == "exif" else state.primary_xmp_items
    )
    if not metadata_items:
        return "no_existing_exif_item" if metadata_kind == "exif" else "no_existing_xmp_item"
    item = metadata_items[0]
    if item.protection_index:
        return (
            "existing_protected_exif_item"
            if metadata_kind == "exif"
            else "existing_protected_xmp_item"
        )
    if item.data_reference_index:
        return (
            "existing_external_exif_item"
            if metadata_kind == "exif"
            else "existing_external_xmp_item"
        )
    if item.construction_method:
        return (
            "existing_unsupported_construction_method_exif_item"
            if metadata_kind == "exif"
            else "existing_unsupported_construction_method_xmp_item"
        )
    if item.content_encoding == "deflate":
        return (
            "existing_deflate_exif_item" if metadata_kind == "exif" else "existing_deflate_xmp_item"
        )
    return "existing_exif_item" if metadata_kind == "exif" else "existing_xmp_item"


def surfaces_for_operation(
    operation: HeicItemInfoOperation,
) -> tuple[HeicItemInfoSurface, ...]:
    if operation == "create_xmp_item":
        return (
            "heic_top_level_meta_item_information_xmp",
            "heic_iinf_infe_mime_xmp",
            "heic_iref_cdsc_primary_reference",
            "heic_iloc_mdat_chunk",
        )
    if operation == "create_exif_item":
        return (
            "heic_top_level_meta_item_information_exif",
            "heic_iinf_infe_type_exif",
            "heic_iref_cdsc_primary_reference",
            "heic_iloc_mdat_chunk",
            "heic_exif_header_tiff_payload",
        )
    if operation in {"rewrite_existing_xmp_item", "delete_existing_xmp_item"}:
        return (
            "heic_top_level_meta_item_information_xmp",
            "heic_existing_xmp_item_rewrite",
            "heic_iloc_mdat_chunk",
        )
    if operation in {"rewrite_existing_exif_item", "delete_existing_exif_item"}:
        return (
            "heic_top_level_meta_item_information_exif",
            "heic_existing_exif_item_rewrite",
            "heic_exif_header_tiff_payload",
            "heic_iloc_mdat_chunk",
        )
    return ()


def blocker_codes_for_operation(
    operation: HeicItemInfoOperation,
    storage: HeicItemInfoStorage,
) -> tuple[HeicItemInfoBlockerCode, ...]:
    blockers: list[HeicItemInfoBlockerCode] = []
    if storage == "missing_required_boxes":
        blockers.append("missing_iinf_or_iloc_box")
    elif storage in {"existing_deflate_exif_item", "existing_deflate_xmp_item"}:
        blockers.append("compressed_metadata_requires_deflate_round_trip")
    elif storage in {"existing_protected_exif_item", "existing_protected_xmp_item"}:
        blockers.append("protected_metadata_not_decodable")
    elif storage in {"existing_external_exif_item", "existing_external_xmp_item"}:
        blockers.append("metadata_not_in_this_file")
    elif storage in {
        "existing_unsupported_construction_method_exif_item",
        "existing_unsupported_construction_method_xmp_item",
    }:
        blockers.append("construction_method_not_supported_for_heic_write")
    if operation in {"create_exif_item", "create_xmp_item"}:
        if operation == "create_exif_item":
            blockers.append("requires_exif_tiff_handoff")
        blockers.extend(
            (
                "requires_heic_item_info_atom_rebuild",
                "requires_iinf_iref_iloc_count_and_offset_fixups",
                "requires_mdat_chunk_insertion_and_offset_rewrite",
            )
        )
    elif operation in {
        "rewrite_existing_exif_item",
        "rewrite_existing_xmp_item",
        "delete_existing_exif_item",
        "delete_existing_xmp_item",
    }:
        if operation in {"rewrite_existing_exif_item", "delete_existing_exif_item"}:
            blockers.append("requires_exif_tiff_handoff")
        blockers.extend(
            (
                "requires_existing_mdat_extent_replacement",
                "requires_iinf_iref_iloc_count_and_offset_fixups",
                "requires_mdat_chunk_insertion_and_offset_rewrite",
            )
        )
    return tuple(dict.fromkeys(blockers))


def evidence_ids_for_operation(
    operation: HeicItemInfoOperation,
    requested_tag: str,
    storage: HeicItemInfoStorage,
) -> tuple[str, ...]:
    evidence_ids: list[str] = [
        HEIC_ITEM_INFO_MAP_EVIDENCE_ID,
        PARSE_ITEM_LOCATION_EVIDENCE_ID,
        PARSE_ITEM_INFO_EVIDENCE_ID,
    ]
    if operation == "create_xmp_item":
        evidence_ids.extend(
            (
                WRITE_ITEM_INFO_CREATE_EVIDENCE_ID,
                WRITE_ITEM_INFO_BOX_INSERT_EVIDENCE_ID,
                WRITE_MDAT_EDIT_EVIDENCE_ID,
                WRITE_OFFSET_FIXUP_EVIDENCE_ID,
            )
        )
    elif operation == "create_exif_item":
        evidence_ids.extend(
            (
                WRITE_ITEM_INFO_CREATE_EVIDENCE_ID,
                HEIC_EXIF_TIFF_HANDOFF_EVIDENCE_ID,
                WRITE_ITEM_INFO_BOX_INSERT_EVIDENCE_ID,
                WRITE_MDAT_EDIT_EVIDENCE_ID,
                WRITE_OFFSET_FIXUP_EVIDENCE_ID,
            )
        )
    elif operation in {"rewrite_existing_xmp_item", "delete_existing_xmp_item"}:
        evidence_ids.extend(
            (
                WRITE_ITEM_INFO_SELECTION_EVIDENCE_ID,
                WRITE_ITEM_INFO_REWRITE_EVIDENCE_ID,
                WRITE_MDAT_EDIT_EVIDENCE_ID,
                WRITE_OFFSET_FIXUP_EVIDENCE_ID,
            )
        )
    elif operation in {"rewrite_existing_exif_item", "delete_existing_exif_item"}:
        evidence_ids.extend(
            (
                WRITE_ITEM_INFO_SELECTION_EVIDENCE_ID,
                HEIC_EXIF_TIFF_HANDOFF_EVIDENCE_ID,
                HEIC_EXIF_TIFF_RESULT_EVIDENCE_ID,
                WRITE_MDAT_EDIT_EVIDENCE_ID,
                WRITE_OFFSET_FIXUP_EVIDENCE_ID,
            )
        )
    if storage not in {"no_existing_exif_item", "no_existing_xmp_item"}:
        evidence_ids.append(READ_ITEM_INFO_CONSTRAINT_EVIDENCE_ID)
    if requested_tag.lower() == "xmp-dc:title":
        evidence_ids.append(XMP_DC_TITLE_EVIDENCE_ID)
    return tuple(dict.fromkeys(evidence_ids))


def container_evidence_ids(
    container_kind: HeicContainerKind,
) -> tuple[str, ...]:
    if container_kind == "heic_item_info":
        return (
            HEIC_ITEM_INFO_MAP_EVIDENCE_ID,
            WRITE_ITEM_INFO_CREATE_EVIDENCE_ID,
            WRITE_MDAT_EDIT_EVIDENCE_ID,
            WRITE_OFFSET_FIXUP_EVIDENCE_ID,
        )
    if container_kind == "cr3_quicktime":
        return (CR3_QUICKTIME_MAP_EVIDENCE_ID, WRITE_OFFSET_FIXUP_EVIDENCE_ID)
    return (HEIC_ITEM_INFO_MAP_EVIDENCE_ID,)


def is_metadata_assignment_arg(write_arg: str) -> bool:
    return write_arg.startswith("-") and "=" in write_arg and not write_arg.startswith("-api")


def split_assignment_arg(write_arg: str) -> tuple[str, str]:
    trimmed = write_arg.removeprefix("-")
    tag, separator, value = trimmed.partition("=")
    if not separator:
        raise ValueError(f"Expected metadata assignment argument: {write_arg}")
    return tag, value


def required_string(payload: JsonObject, key: str) -> str:
    value = json_string_value(payload, key)
    if value is None:
        raise ValueError(f"Expected string JSON field: {key}")
    return value


def heic_item_info_state_to_json(state: HeicItemInfoState) -> JsonObject:
    return {
        "compatible_brands": list(state.compatible_brands),
        "container_kind": state.container_kind,
        "has_idat": state.has_idat,
        "has_iinf": state.has_iinf,
        "has_iloc": state.has_iloc,
        "has_iref": state.has_iref,
        "has_mdat": state.has_mdat,
        "has_top_level_meta": state.has_top_level_meta,
        "item_count": len(state.items),
        "major_brand": state.major_brand,
        "next_item_id": state.next_item_id,
        "primary_item_id": state.primary_item_id,
        "primary_xmp_item_ids": [item.item_id for item in state.primary_xmp_items],
    }
