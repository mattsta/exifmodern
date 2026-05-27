"""Photoshop IPTC resource rewrite and IPTCDigest primitives.

ExifTool stores PSD IPTC in Photoshop image resource ``0x0404`` and computes
``IPTCDigest`` from the rewritten IPTC stream when the digest value is ``new``.
This module implements the bounded string dataset subset needed by the PSD
writer plan while leaving full charset, delete, and real PSD emission paths
gated elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import md5
from typing import Literal

from exifmodern.formats.photoshop.image_resources import (
    PHOTOSHOP_WRITABLE_IRB_SIGNATURE,
    PhotoshopImageResourceBlock,
)
from exifmodern.formats.photoshop.nested_metadata_plan import (
    IPTC_WRITE_DIGEST_SOURCE_ID,
    PHOTOSHOP_IPTC_DIGEST_RESOURCE_SOURCE_ID,
    PHOTOSHOP_IPTC_RESOURCE_SOURCE_ID,
    PHOTOSHOP_RESOURCE_ID_IPTC_DATA,
    PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST,
)
from exifmodern.formats.photoshop.resource_writer import (
    PhotoshopImageResourceMutation,
    PhotoshopPSDUnsupportedWriteError,
)
from exifmodern.formats.photoshop.section_boundary_plan import (
    plan_photoshop_psd_section_boundaries,
    rewrite_synthetic_photoshop_psd_image_resources,
)
from exifmodern.formats.photoshop.write_plan import (
    IPTC_BY_LINE_SOURCE_ID,
    IPTC_CAPTION_ABSTRACT_SOURCE_ID,
    IPTC_CREDIT_SOURCE_SOURCE_ID,
    IPTC_DATE_CREATED_SOURCE_ID,
    IPTC_DATE_TIME_FORMAT_SOURCE_ID,
    IPTC_HEADLINE_SOURCE_ID,
    IPTC_KEYWORDS_SOURCE_ID,
    IPTC_LOCATION_SOURCE_ID,
    IPTC_OBJECT_NAME_SOURCE_ID,
    IPTC_TIME_CREATED_SOURCE_ID,
    IPTC_URGENCY_CATEGORY_SOURCE_ID,
    WRITE_PHOTOSHOP_SOURCE_ID,
    PhotoshopEvidenceCompat,
)

type PhotoshopIPTCDatasetName = Literal[
    "ObjectName",
    "Urgency",
    "Category",
    "SupplementalCategories",
    "Keywords",
    "DateCreated",
    "TimeCreated",
    "By-Line",
    "City",
    "Province-State",
    "Country-PrimaryLocationName",
    "Headline",
    "Credit",
    "Source",
    "CopyrightNotice",
    "Caption-Abstract",
]
type PhotoshopIPTCWriteValue = str | bytes
type PhotoshopIPTCWriteValues = PhotoshopIPTCWriteValue | tuple[PhotoshopIPTCWriteValue, ...]
type PhotoshopIPTCRewriteBlockerCode = Literal[
    "not_source_backed",
    "iptc_data_malformed",
    "iptc_records_out_of_sequence",
    "iptc_date_value_invalid",
    "iptc_time_value_invalid",
    "iptc_value_not_ascii",
    "iptc_value_too_long",
    "missing_iptc_resource",
    "duplicate_iptc_resource",
    "non_8bim_iptc_resource",
    "duplicate_iptc_digest_resource",
    "non_8bim_iptc_digest_resource",
]

IPTC_DATASET_MARKER = 0x1C
IPTC_APPLICATION_RECORD = 2

IPTC_OBJECT_NAME_DATASET = 5
IPTC_URGENCY_DATASET = 10
IPTC_CATEGORY_DATASET = 15
IPTC_SUPPLEMENTAL_CATEGORIES_DATASET = 20
IPTC_KEYWORDS_DATASET = 25
IPTC_DATE_CREATED_DATASET = 55
IPTC_TIME_CREATED_DATASET = 60
IPTC_BY_LINE_DATASET = 80
IPTC_CITY_DATASET = 90
IPTC_PROVINCE_STATE_DATASET = 95
IPTC_COUNTRY_PRIMARY_LOCATION_NAME_DATASET = 101
IPTC_HEADLINE_DATASET = 105
IPTC_CREDIT_DATASET = 110
IPTC_SOURCE_DATASET = 115
IPTC_COPYRIGHT_NOTICE_DATASET = 116
IPTC_CAPTION_ABSTRACT_DATASET = 120

IPTC_APPLICATION_RECORD_VERSION_DATASET = 0
IPTC_APPLICATION_RECORD_VERSION_VALUE = (4).to_bytes(2, "big")

IPTC_REWRITE_SOURCE_ID = "photoshop.iptc.rewrite"
IPTC_DIGEST_RECONCILE_SOURCE_ID = "photoshop.iptc.digest_reconcile"


def _photoshop_iptc_source_reference(source_id: str) -> str:
    return source_id


IPTC_REWRITE_SOURCE_ID = _photoshop_iptc_source_reference(IPTC_REWRITE_SOURCE_ID)
IPTC_DIGEST_RECONCILE_SOURCE_ID = _photoshop_iptc_source_reference(IPTC_DIGEST_RECONCILE_SOURCE_ID)


@dataclass(frozen=True)
class PhotoshopIPTCDatasetSpec:
    dataset_name: PhotoshopIPTCDatasetName
    record: int
    dataset: int
    maximum_length: int
    list_valued: bool
    source_reference_id: str
    value_kind: Literal["text", "iptc_date", "iptc_time"] = "text"

    @property
    def key(self) -> tuple[int, int]:
        return (self.record, self.dataset)


@dataclass(frozen=True)
class PhotoshopIPTCDatasetEntry:
    record: int
    dataset: int
    value: bytes
    raw_entry: bytes
    entry_start: int
    entry_end: int

    @property
    def key(self) -> tuple[int, int]:
        return (self.record, self.dataset)


@dataclass(frozen=True)
class PhotoshopIPTCDatasetAssignment:
    spec: PhotoshopIPTCDatasetSpec
    values: tuple[bytes, ...]


@dataclass(frozen=True)
class PhotoshopIPTCDatasetRewriteStep:
    dataset_name: PhotoshopIPTCDatasetName
    record: int
    dataset: int
    source_values: tuple[bytes, ...]
    output_values: tuple[bytes, ...]
    changed: bool


@dataclass(frozen=True)
class PhotoshopIPTCRewritePlan(PhotoshopEvidenceCompat):
    source_length: int
    output_length: int
    source_backed: bool
    can_write_bytes: bool
    blocker_codes: tuple[PhotoshopIPTCRewriteBlockerCode, ...]
    output_data: bytes | None
    source_digest: bytes | None
    output_digest: bytes | None
    steps: tuple[PhotoshopIPTCDatasetRewriteStep, ...]
    source_reference_ids: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return any(step.changed for step in self.steps)


DATASET_SPECS: tuple[PhotoshopIPTCDatasetSpec, ...] = (
    PhotoshopIPTCDatasetSpec(
        dataset_name="ObjectName",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_OBJECT_NAME_DATASET,
        maximum_length=64,
        list_valued=False,
        source_reference_id=IPTC_OBJECT_NAME_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="Urgency",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_URGENCY_DATASET,
        maximum_length=1,
        list_valued=False,
        source_reference_id=IPTC_URGENCY_CATEGORY_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="Category",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_CATEGORY_DATASET,
        maximum_length=3,
        list_valued=False,
        source_reference_id=IPTC_URGENCY_CATEGORY_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="SupplementalCategories",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_SUPPLEMENTAL_CATEGORIES_DATASET,
        maximum_length=32,
        list_valued=True,
        source_reference_id=IPTC_URGENCY_CATEGORY_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="Keywords",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_KEYWORDS_DATASET,
        maximum_length=64,
        list_valued=True,
        source_reference_id=IPTC_KEYWORDS_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="DateCreated",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_DATE_CREATED_DATASET,
        maximum_length=8,
        list_valued=False,
        source_reference_id=IPTC_DATE_CREATED_SOURCE_ID,
        value_kind="iptc_date",
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="TimeCreated",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_TIME_CREATED_DATASET,
        maximum_length=11,
        list_valued=False,
        source_reference_id=IPTC_TIME_CREATED_SOURCE_ID,
        value_kind="iptc_time",
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="By-Line",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_BY_LINE_DATASET,
        maximum_length=32,
        list_valued=True,
        source_reference_id=IPTC_BY_LINE_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="City",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_CITY_DATASET,
        maximum_length=32,
        list_valued=False,
        source_reference_id=IPTC_LOCATION_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="Province-State",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_PROVINCE_STATE_DATASET,
        maximum_length=32,
        list_valued=False,
        source_reference_id=IPTC_LOCATION_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="Country-PrimaryLocationName",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_COUNTRY_PRIMARY_LOCATION_NAME_DATASET,
        maximum_length=64,
        list_valued=False,
        source_reference_id=IPTC_LOCATION_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="Headline",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_HEADLINE_DATASET,
        maximum_length=256,
        list_valued=False,
        source_reference_id=IPTC_HEADLINE_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="Credit",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_CREDIT_DATASET,
        maximum_length=32,
        list_valued=False,
        source_reference_id=IPTC_CREDIT_SOURCE_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="Source",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_SOURCE_DATASET,
        maximum_length=32,
        list_valued=False,
        source_reference_id=IPTC_CREDIT_SOURCE_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="CopyrightNotice",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_COPYRIGHT_NOTICE_DATASET,
        maximum_length=128,
        list_valued=False,
        source_reference_id=IPTC_CREDIT_SOURCE_SOURCE_ID,
    ),
    PhotoshopIPTCDatasetSpec(
        dataset_name="Caption-Abstract",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_CAPTION_ABSTRACT_DATASET,
        maximum_length=2000,
        list_valued=False,
        source_reference_id=IPTC_CAPTION_ABSTRACT_SOURCE_ID,
    ),
)


def plan_iptc_dataset_rewrite(
    payload: bytes,
    *,
    object_name: PhotoshopIPTCWriteValues | None = None,
    urgency: PhotoshopIPTCWriteValues | None = None,
    category: PhotoshopIPTCWriteValues | None = None,
    supplemental_categories: PhotoshopIPTCWriteValues | None = None,
    date_created: PhotoshopIPTCWriteValues | None = None,
    time_created: PhotoshopIPTCWriteValues | None = None,
    by_line: PhotoshopIPTCWriteValues | None = None,
    keywords: PhotoshopIPTCWriteValues | None = None,
    city: PhotoshopIPTCWriteValues | None = None,
    province_state: PhotoshopIPTCWriteValues | None = None,
    country_primary_location_name: PhotoshopIPTCWriteValues | None = None,
    headline: PhotoshopIPTCWriteValues | None = None,
    credit: PhotoshopIPTCWriteValues | None = None,
    source: PhotoshopIPTCWriteValues | None = None,
    copyright_notice: PhotoshopIPTCWriteValues | None = None,
    caption_abstract: PhotoshopIPTCWriteValues | None = None,
    source_backed: bool = True,
) -> PhotoshopIPTCRewritePlan:
    blockers: list[PhotoshopIPTCRewriteBlockerCode] = []
    if not source_backed:
        blockers.append("not_source_backed")

    entries_result = parse_iptc_dataset_entries(payload)
    if entries_result.blocker_code is not None:
        blockers.append(entries_result.blocker_code)

    assignments, assignment_blockers = dataset_assignments(
        object_name=object_name,
        urgency=urgency,
        category=category,
        supplemental_categories=supplemental_categories,
        date_created=date_created,
        time_created=time_created,
        by_line=by_line,
        keywords=keywords,
        city=city,
        province_state=province_state,
        country_primary_location_name=country_primary_location_name,
        headline=headline,
        credit=credit,
        source=source,
        copyright_notice=copyright_notice,
        caption_abstract=caption_abstract,
    )
    blockers.extend(assignment_blockers)
    source_reference_ids = iptc_source_reference_ids(assignments)

    if blockers:
        return PhotoshopIPTCRewritePlan(
            source_length=len(payload),
            output_length=len(payload),
            source_backed=source_backed,
            can_write_bytes=False,
            blocker_codes=tuple(dict.fromkeys(blockers)),
            output_data=None,
            source_digest=None,
            output_digest=None,
            steps=(),
            source_reference_ids=source_reference_ids,
        )

    entries = entries_result.entries
    output = rewrite_iptc_entries(entries, assignments)
    return PhotoshopIPTCRewritePlan(
        source_length=len(payload),
        output_length=len(output),
        source_backed=source_backed,
        can_write_bytes=True,
        blocker_codes=(),
        output_data=output,
        source_digest=iptc_digest(payload),
        output_digest=iptc_digest(output),
        steps=dataset_rewrite_steps(entries, assignments),
        source_reference_ids=source_reference_ids,
    )


def iptc_dataset_mutations(
    payload: bytes,
    *,
    object_name: PhotoshopIPTCWriteValues | None = None,
    urgency: PhotoshopIPTCWriteValues | None = None,
    category: PhotoshopIPTCWriteValues | None = None,
    supplemental_categories: PhotoshopIPTCWriteValues | None = None,
    date_created: PhotoshopIPTCWriteValues | None = None,
    time_created: PhotoshopIPTCWriteValues | None = None,
    by_line: PhotoshopIPTCWriteValues | None = None,
    keywords: PhotoshopIPTCWriteValues | None = None,
    city: PhotoshopIPTCWriteValues | None = None,
    province_state: PhotoshopIPTCWriteValues | None = None,
    country_primary_location_name: PhotoshopIPTCWriteValues | None = None,
    headline: PhotoshopIPTCWriteValues | None = None,
    credit: PhotoshopIPTCWriteValues | None = None,
    source: PhotoshopIPTCWriteValues | None = None,
    copyright_notice: PhotoshopIPTCWriteValues | None = None,
    caption_abstract: PhotoshopIPTCWriteValues | None = None,
    iptc_resource_name: bytes | None = None,
    digest_resource_name: bytes | None = None,
    digest_resource_present: bool = False,
    source_backed: bool = True,
) -> tuple[PhotoshopImageResourceMutation, ...]:
    plan = plan_iptc_dataset_rewrite(
        payload,
        object_name=object_name,
        urgency=urgency,
        category=category,
        supplemental_categories=supplemental_categories,
        date_created=date_created,
        time_created=time_created,
        by_line=by_line,
        keywords=keywords,
        city=city,
        province_state=province_state,
        country_primary_location_name=country_primary_location_name,
        headline=headline,
        credit=credit,
        source=source,
        copyright_notice=copyright_notice,
        caption_abstract=caption_abstract,
        source_backed=source_backed,
    )
    if not plan.can_write_bytes or plan.output_data is None or plan.output_digest is None:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop IPTC rewrite is blocked: " + ", ".join(plan.blocker_codes)
        )

    digest_action: Literal["replace", "insert"] = "replace" if digest_resource_present else "insert"
    return (
        PhotoshopImageResourceMutation(
            "replace",
            PHOTOSHOP_RESOURCE_ID_IPTC_DATA,
            plan.output_data,
            iptc_resource_name,
        ),
        PhotoshopImageResourceMutation(
            digest_action,
            PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST,
            plan.output_digest,
            digest_resource_name,
        ),
    )


def rewrite_synthetic_photoshop_psd_iptc(
    psd_data: bytes,
    *,
    object_name: PhotoshopIPTCWriteValues | None = None,
    urgency: PhotoshopIPTCWriteValues | None = None,
    category: PhotoshopIPTCWriteValues | None = None,
    supplemental_categories: PhotoshopIPTCWriteValues | None = None,
    date_created: PhotoshopIPTCWriteValues | None = None,
    time_created: PhotoshopIPTCWriteValues | None = None,
    by_line: PhotoshopIPTCWriteValues | None = None,
    keywords: PhotoshopIPTCWriteValues | None = None,
    city: PhotoshopIPTCWriteValues | None = None,
    province_state: PhotoshopIPTCWriteValues | None = None,
    country_primary_location_name: PhotoshopIPTCWriteValues | None = None,
    headline: PhotoshopIPTCWriteValues | None = None,
    credit: PhotoshopIPTCWriteValues | None = None,
    source: PhotoshopIPTCWriteValues | None = None,
    copyright_notice: PhotoshopIPTCWriteValues | None = None,
    caption_abstract: PhotoshopIPTCWriteValues | None = None,
    source_backed: bool = True,
) -> bytes:
    section_plan = plan_photoshop_psd_section_boundaries(
        psd_data,
        source_backed=source_backed,
        synthetic_psd=True,
    )
    iptc_blocks = tuple(
        block
        for block in section_plan.image_resource_blocks
        if block.resource_id == PHOTOSHOP_RESOURCE_ID_IPTC_DATA
    )
    digest_blocks = tuple(
        block
        for block in section_plan.image_resource_blocks
        if block.resource_id == PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST
    )
    blocker_codes = iptc_resource_blockers(
        iptc_blocks,
        digest_blocks,
        source_backed=source_backed,
    )
    if blocker_codes:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop synthetic PSD IPTC rewrite is blocked: " + ", ".join(blocker_codes)
        )

    iptc_block = iptc_blocks[0]
    digest_block = digest_blocks[0] if digest_blocks else None
    mutations = iptc_dataset_mutations(
        iptc_block.data,
        object_name=object_name,
        urgency=urgency,
        category=category,
        supplemental_categories=supplemental_categories,
        date_created=date_created,
        time_created=time_created,
        by_line=by_line,
        keywords=keywords,
        city=city,
        province_state=province_state,
        country_primary_location_name=country_primary_location_name,
        headline=headline,
        credit=credit,
        source=source,
        copyright_notice=copyright_notice,
        caption_abstract=caption_abstract,
        iptc_resource_name=iptc_block.name,
        digest_resource_name=None if digest_block is None else digest_block.name,
        digest_resource_present=digest_block is not None,
        source_backed=source_backed,
    )
    return rewrite_synthetic_photoshop_psd_image_resources(
        psd_data,
        mutations,
        source_backed=source_backed,
    )


@dataclass(frozen=True)
class ParsedIPTCDatasetEntries:
    entries: tuple[PhotoshopIPTCDatasetEntry, ...]
    blocker_code: PhotoshopIPTCRewriteBlockerCode | None


def parse_iptc_dataset_entries(payload: bytes) -> ParsedIPTCDatasetEntries:
    entries: list[PhotoshopIPTCDatasetEntry] = []
    position = 0
    last_record = -1
    while position < len(payload):
        if position + 5 > len(payload):
            if payload[position:] == b"\x00" * (len(payload) - position):
                break
            return ParsedIPTCDatasetEntries((), "iptc_data_malformed")

        entry_start = position
        marker = payload[position]
        if marker != IPTC_DATASET_MARKER:
            if payload[position:] == b"\x00" * (len(payload) - position):
                break
            return ParsedIPTCDatasetEntries((), "iptc_data_malformed")

        record = payload[position + 1]
        if record < last_record:
            return ParsedIPTCDatasetEntries((), "iptc_records_out_of_sequence")
        last_record = record

        dataset = payload[position + 2]
        raw_length = int.from_bytes(payload[position + 3 : position + 5], "big")
        position += 5
        if raw_length & 0x8000:
            length_byte_count = raw_length & 0x7FFF
            if length_byte_count > 8 or position + length_byte_count > len(payload):
                return ParsedIPTCDatasetEntries((), "iptc_data_malformed")
            value_length = 0
            for length_byte in payload[position : position + length_byte_count]:
                value_length = value_length * 256 + length_byte
            position += length_byte_count
        else:
            value_length = raw_length

        value_end = position + value_length
        if value_end > len(payload):
            return ParsedIPTCDatasetEntries((), "iptc_data_malformed")
        entries.append(
            PhotoshopIPTCDatasetEntry(
                record=record,
                dataset=dataset,
                value=payload[position:value_end],
                raw_entry=payload[entry_start:value_end],
                entry_start=entry_start,
                entry_end=value_end,
            )
        )
        position = value_end

    return ParsedIPTCDatasetEntries(tuple(entries), None)


def dataset_assignments(
    *,
    object_name: PhotoshopIPTCWriteValues | None,
    urgency: PhotoshopIPTCWriteValues | None,
    category: PhotoshopIPTCWriteValues | None,
    supplemental_categories: PhotoshopIPTCWriteValues | None,
    date_created: PhotoshopIPTCWriteValues | None,
    time_created: PhotoshopIPTCWriteValues | None,
    by_line: PhotoshopIPTCWriteValues | None,
    keywords: PhotoshopIPTCWriteValues | None,
    city: PhotoshopIPTCWriteValues | None,
    province_state: PhotoshopIPTCWriteValues | None,
    country_primary_location_name: PhotoshopIPTCWriteValues | None,
    headline: PhotoshopIPTCWriteValues | None,
    credit: PhotoshopIPTCWriteValues | None,
    source: PhotoshopIPTCWriteValues | None,
    copyright_notice: PhotoshopIPTCWriteValues | None,
    caption_abstract: PhotoshopIPTCWriteValues | None,
) -> tuple[tuple[PhotoshopIPTCDatasetAssignment, ...], tuple[PhotoshopIPTCRewriteBlockerCode, ...]]:
    requested: tuple[tuple[PhotoshopIPTCDatasetName, PhotoshopIPTCWriteValues | None], ...] = (
        ("ObjectName", object_name),
        ("Urgency", urgency),
        ("Category", category),
        ("SupplementalCategories", supplemental_categories),
        ("Keywords", keywords),
        ("DateCreated", date_created),
        ("TimeCreated", time_created),
        ("By-Line", by_line),
        ("City", city),
        ("Province-State", province_state),
        ("Country-PrimaryLocationName", country_primary_location_name),
        ("Headline", headline),
        ("Credit", credit),
        ("Source", source),
        ("CopyrightNotice", copyright_notice),
        ("Caption-Abstract", caption_abstract),
    )
    assignments: list[PhotoshopIPTCDatasetAssignment] = []
    blockers: list[PhotoshopIPTCRewriteBlockerCode] = []
    for dataset_name, value in requested:
        if value is None:
            continue
        spec = dataset_spec(dataset_name)
        values, value_blockers = normalized_dataset_values(value, spec)
        blockers.extend(value_blockers)
        assignments.append(PhotoshopIPTCDatasetAssignment(spec=spec, values=values))
    return tuple(assignments), tuple(dict.fromkeys(blockers))


def normalized_dataset_values(
    value: PhotoshopIPTCWriteValues,
    spec: PhotoshopIPTCDatasetSpec,
) -> tuple[tuple[bytes, ...], tuple[PhotoshopIPTCRewriteBlockerCode, ...]]:
    raw_values = dataset_value_tuple(value)
    values: list[bytes] = []
    blockers: list[PhotoshopIPTCRewriteBlockerCode] = []
    for raw_value in raw_values:
        if spec.value_kind == "iptc_date":
            encoded = normalized_iptc_date_bytes(raw_value)
            if encoded is None:
                blockers.append("iptc_date_value_invalid")
                continue
        elif spec.value_kind == "iptc_time":
            encoded = normalized_iptc_time_bytes(raw_value)
            if encoded is None:
                blockers.append("iptc_time_value_invalid")
                continue
        elif isinstance(raw_value, str):
            try:
                encoded = raw_value.encode("ascii")
            except UnicodeEncodeError:
                blockers.append("iptc_value_not_ascii")
                continue
        else:
            encoded = bytes(raw_value)
            if any(byte > 0x7F for byte in encoded):
                blockers.append("iptc_value_not_ascii")
                continue
        if len(encoded) > spec.maximum_length:
            blockers.append("iptc_value_too_long")
            continue
        values.append(encoded)
    if not spec.list_valued and len(values) > 1:
        values = values[:1]
    return tuple(values), tuple(dict.fromkeys(blockers))


def dataset_value_tuple(
    value: PhotoshopIPTCWriteValues,
) -> tuple[PhotoshopIPTCWriteValue, ...]:
    if isinstance(value, str | bytes):
        return (value,)
    return value


IPTC_DATE_PATTERN = re.compile(r"^.*?(\d{4})[-:/.]?(\d{2})[-:/.]?(\d{2}).*$", re.DOTALL)
IPTC_TIME_PATTERN = re.compile(
    r"^(?P<prefix>.*?\b)?(?P<hour>\d{1,2})(?P<sep1>:?)(?P<minute>\d{2})"
    r"(?P<sep2>:?)(?P<second>\d{2})(?P<timezone>\S*)\s*$",
    re.DOTALL,
)


def normalized_iptc_date_bytes(value: PhotoshopIPTCWriteValue) -> bytes | None:
    text = normalized_iptc_input_text(value)
    if text is None:
        return None
    if text.casefold() == "now":
        return datetime.now().strftime("%Y%m%d").encode("ascii")
    match = IPTC_DATE_PATTERN.match(text)
    if match is None:
        return None
    return "".join(match.groups()).encode("ascii")


def normalized_iptc_time_bytes(value: PhotoshopIPTCWriteValue) -> bytes | None:
    text = normalized_iptc_input_text(value)
    if text is None:
        return None
    if text.casefold() == "now":
        return datetime.now().astimezone().strftime("%H%M%S%z").encode("ascii")
    match = IPTC_TIME_PATTERN.match(text)
    if match is None:
        return None
    if not match.group("sep1") and match.group("sep2"):
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    second = int(match.group("second"))
    timezone_text = normalized_iptc_timezone(
        match.group("timezone"),
        match.group("prefix"),
        hour,
        minute,
        second,
    )
    if timezone_text is None:
        return None
    return f"{hour:02d}{minute:02d}{second:02d}{timezone_text}".encode("ascii")


def normalized_iptc_input_text(value: PhotoshopIPTCWriteValue) -> str | None:
    if isinstance(value, str):
        return value.strip()
    if any(byte > 0x7F for byte in value):
        return None
    return bytes(value).decode("ascii").strip()


def normalized_iptc_timezone(
    timezone_text: str,
    date_prefix: str | None,
    hour: int,
    minute: int,
    second: int,
) -> str | None:
    timezone_match = re.search(r"([+-]\d{1,2}):?(\d{2})", timezone_text)
    if timezone_match is not None:
        hours = int(timezone_match.group(1))
        minutes = int(timezone_match.group(2))
        return f"{hours:+03d}{minutes:02d}"
    if "Z" in timezone_text.upper():
        return "+0000"
    return local_timezone_offset_text(date_prefix, hour, minute, second)


def local_timezone_offset_text(
    date_prefix: str | None,
    hour: int,
    minute: int,
    second: int,
) -> str:
    now = datetime.now().astimezone()
    if date_prefix is not None:
        date_match = re.match(r"^(\d{4}):(\d{2}):(\d{2})\s*$", date_prefix)
        if date_match is not None:
            year, month, day = (int(part) for part in date_match.groups())
            try:
                now = datetime(year, month, day, hour, minute, second).astimezone()
            except ValueError:
                now = datetime.now().astimezone()
    return now.strftime("%z") or "+0000"


def rewrite_iptc_entries(
    entries: tuple[PhotoshopIPTCDatasetEntry, ...],
    assignments: tuple[PhotoshopIPTCDatasetAssignment, ...],
) -> bytes:
    assignment_by_key = {assignment.spec.key: assignment for assignment in assignments}
    emitted_keys: set[tuple[int, int]] = set()
    output = bytearray()

    for entry in entries:
        for assignment in pending_assignments_before(entry.key, assignments, emitted_keys):
            output.extend(encode_assignment_entries(assignment))
            emitted_keys.add(assignment.spec.key)

        existing_assignment = assignment_by_key.get(entry.key)
        if existing_assignment is not None:
            if entry.key not in emitted_keys:
                output.extend(encode_assignment_entries(existing_assignment))
                emitted_keys.add(entry.key)
            continue
        output.extend(entry.raw_entry)

    for assignment in assignments:
        if assignment.spec.key not in emitted_keys:
            output.extend(encode_assignment_entries(assignment))
            emitted_keys.add(assignment.spec.key)

    if requires_application_record_version(tuple(entries), assignments):
        output.extend(
            encode_iptc_dataset_entry(
                IPTC_APPLICATION_RECORD,
                IPTC_APPLICATION_RECORD_VERSION_DATASET,
                IPTC_APPLICATION_RECORD_VERSION_VALUE,
            )
        )
    return bytes(output)


def pending_assignments_before(
    key: tuple[int, int],
    assignments: tuple[PhotoshopIPTCDatasetAssignment, ...],
    emitted_keys: set[tuple[int, int]],
) -> tuple[PhotoshopIPTCDatasetAssignment, ...]:
    return tuple(
        assignment
        for assignment in assignments
        if assignment.spec.key not in emitted_keys and assignment.spec.key < key
    )


def requires_application_record_version(
    entries: tuple[PhotoshopIPTCDatasetEntry, ...],
    assignments: tuple[PhotoshopIPTCDatasetAssignment, ...],
) -> bool:
    if not assignments:
        return False
    has_application_record = any(entry.record == IPTC_APPLICATION_RECORD for entry in entries)
    has_version = any(
        entry.record == IPTC_APPLICATION_RECORD
        and entry.dataset == IPTC_APPLICATION_RECORD_VERSION_DATASET
        for entry in entries
    )
    return not has_application_record or not has_version


def encode_assignment_entries(assignment: PhotoshopIPTCDatasetAssignment) -> bytes:
    return b"".join(
        encode_iptc_dataset_entry(
            assignment.spec.record,
            assignment.spec.dataset,
            value,
        )
        for value in assignment.values
    )


def encode_iptc_dataset_entry(record: int, dataset: int, value: bytes) -> bytes:
    if len(value) <= 0x7FFF:
        length_bytes = len(value).to_bytes(2, "big")
    else:
        length_bytes = (0x8004).to_bytes(2, "big") + len(value).to_bytes(4, "big")
    return bytes((IPTC_DATASET_MARKER, record, dataset)) + length_bytes + value


def dataset_rewrite_steps(
    entries: tuple[PhotoshopIPTCDatasetEntry, ...],
    assignments: tuple[PhotoshopIPTCDatasetAssignment, ...],
) -> tuple[PhotoshopIPTCDatasetRewriteStep, ...]:
    steps: list[PhotoshopIPTCDatasetRewriteStep] = []
    for assignment in assignments:
        source_values = tuple(entry.value for entry in entries if entry.key == assignment.spec.key)
        steps.append(
            PhotoshopIPTCDatasetRewriteStep(
                dataset_name=assignment.spec.dataset_name,
                record=assignment.spec.record,
                dataset=assignment.spec.dataset,
                source_values=source_values,
                output_values=assignment.values,
                changed=source_values != assignment.values,
            )
        )
    return tuple(steps)


def iptc_resource_blockers(
    iptc_blocks: tuple[PhotoshopImageResourceBlock, ...],
    digest_blocks: tuple[PhotoshopImageResourceBlock, ...],
    *,
    source_backed: bool,
) -> tuple[PhotoshopIPTCRewriteBlockerCode, ...]:
    blockers: list[PhotoshopIPTCRewriteBlockerCode] = []
    if not source_backed:
        blockers.append("not_source_backed")
    if not iptc_blocks:
        blockers.append("missing_iptc_resource")
    if len(iptc_blocks) > 1:
        blockers.append("duplicate_iptc_resource")
    if any(block.signature != PHOTOSHOP_WRITABLE_IRB_SIGNATURE for block in iptc_blocks):
        blockers.append("non_8bim_iptc_resource")
    if len(digest_blocks) > 1:
        blockers.append("duplicate_iptc_digest_resource")
    if any(block.signature != PHOTOSHOP_WRITABLE_IRB_SIGNATURE for block in digest_blocks):
        blockers.append("non_8bim_iptc_digest_resource")
    return tuple(dict.fromkeys(blockers))


def dataset_spec(dataset_name: PhotoshopIPTCDatasetName) -> PhotoshopIPTCDatasetSpec:
    for spec in DATASET_SPECS:
        if spec.dataset_name == dataset_name:
            return spec
    raise KeyError(f"Unsupported Photoshop IPTC dataset: {dataset_name}")


def iptc_digest(payload: bytes) -> bytes:
    return md5(payload).digest()


def iptc_source_reference_ids(
    assignments: tuple[PhotoshopIPTCDatasetAssignment, ...],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                PHOTOSHOP_IPTC_RESOURCE_SOURCE_ID,
                PHOTOSHOP_IPTC_DIGEST_RESOURCE_SOURCE_ID,
                IPTC_REWRITE_SOURCE_ID,
                IPTC_WRITE_DIGEST_SOURCE_ID,
                IPTC_DIGEST_RECONCILE_SOURCE_ID,
                *(
                    (IPTC_DATE_TIME_FORMAT_SOURCE_ID,)
                    if any(
                        assignment.spec.value_kind in {"iptc_date", "iptc_time"}
                        for assignment in assignments
                    )
                    else ()
                ),
                WRITE_PHOTOSHOP_SOURCE_ID,
                *(assignment.spec.source_reference_id for assignment in assignments),
            )
        )
    )
