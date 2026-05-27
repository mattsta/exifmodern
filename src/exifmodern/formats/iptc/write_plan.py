"""Typed write plans for IPTC ApplicationRecord datasets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

type IptcApplicationTagName = str
type IptcApplicationWriteOperation = Literal["upsert", "delete", "delete_value"]
type IptcDatasetValue = str | bytes
type IptcDatasetValueKind = Literal[
    "text",
    "digits",
    "date",
    "time",
    "int8u",
    "int16u",
    "int32u",
    "binary",
    "picture_number",
    "prefs",
]
type IptcTextEncoding = Literal["latin-1", "utf-8", "cp1251"]

IPTC_ENVELOPE_RECORD = 1
IPTC_APPLICATION_RECORD = 2
IPTC_NEWS_PHOTO_RECORD = 3
IPTC_APPLICATION_RECORD_VERSION_DATASET = 0
IPTC_APPLICATION_RECORD_VERSION_VALUE = 4
IPTC_MANDATORY_RECORD_VERSION_DATASET = 0
IPTC_MANDATORY_RECORD_VERSION_VALUE = 4
IPTC_ENVELOPE_RECORD_EVIDENCE_ID = "iptc.iptc-envelope-record"
IPTC_APPLICATION_RECORD_EVIDENCE_ID = "iptc.iptc-application-record"
IPTC_NEWS_PHOTO_RECORD_EVIDENCE_ID = "iptc.iptc-news-photo-record"
IPTC_OBJECT_DATA_RECORD = 8
IPTC_OBJECT_DATA_RECORD_EVIDENCE_ID = "iptc.iptc-object-data-record"
IPTC_APPLICATION_RECORD_VERSION_EVIDENCE_ID = "iptc.iptc-application-record-version"
PHOTOSHOP_IPTC_RESOURCE_EVIDENCE_ID = "iptc.photoshop-iptc-resource"


@dataclass(frozen=True)
class IptcApplicationTagSpec:
    tag_name: IptcApplicationTagName
    dataset_id: int
    max_length: int
    is_list: bool
    evidence_id: str
    record_id: int = IPTC_APPLICATION_RECORD
    value_kind: IptcDatasetValueKind = "text"
    min_length: int = 0


@dataclass(frozen=True)
class IptcApplicationWriteStep:
    operation: IptcApplicationWriteOperation
    tag_name: IptcApplicationTagName
    record_id: int
    dataset_id: int
    is_list: bool
    value_kind: IptcDatasetValueKind
    values: tuple[IptcDatasetValue, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IptcApplicationWritePlan:
    steps: tuple[IptcApplicationWriteStep, ...]
    text_encoding: IptcTextEncoding | None = None

    @property
    def is_delete_only(self) -> bool:
        return all(step.operation == "delete" for step in self.steps)


@dataclass(frozen=True)
class IptcBinaryPayloadBlocker:
    tag_name: str
    record_id: int
    dataset_id: int
    code: str
    reason: str
    evidence_id: str


IPTC_APPLICATION_TAG_SPECS: dict[str, IptcApplicationTagSpec] = {
    "ARMIdentifier": IptcApplicationTagSpec(
        tag_name="ARMIdentifier",
        record_id=IPTC_ENVELOPE_RECORD,
        dataset_id=120,
        max_length=2,
        is_list=False,
        value_kind="int16u",
        evidence_id="iptc.enveloperecord-armidentifier",
    ),
    "ARMVersion": IptcApplicationTagSpec(
        tag_name="ARMVersion",
        record_id=IPTC_ENVELOPE_RECORD,
        dataset_id=122,
        max_length=2,
        is_list=False,
        value_kind="int16u",
        evidence_id="iptc.enveloperecord-armversion",
    ),
    "CodedCharacterSet": IptcApplicationTagSpec(
        tag_name="CodedCharacterSet",
        record_id=IPTC_ENVELOPE_RECORD,
        dataset_id=90,
        max_length=32,
        is_list=False,
        evidence_id="iptc.enveloperecord-codedcharacterset",
    ),
    "ApplicationRecordVersion": IptcApplicationTagSpec(
        tag_name="ApplicationRecordVersion",
        dataset_id=0,
        max_length=2,
        is_list=False,
        value_kind="int16u",
        evidence_id=IPTC_APPLICATION_RECORD_VERSION_EVIDENCE_ID,
    ),
    "ObjectName": IptcApplicationTagSpec(
        tag_name="ObjectName",
        dataset_id=5,
        max_length=64,
        is_list=False,
        evidence_id="iptc.objectname",
    ),
    "Urgency": IptcApplicationTagSpec(
        tag_name="Urgency",
        dataset_id=10,
        max_length=1,
        is_list=False,
        value_kind="digits",
        evidence_id="iptc.urgency",
    ),
    "Category": IptcApplicationTagSpec(
        tag_name="Category",
        dataset_id=15,
        max_length=3,
        is_list=False,
        evidence_id="iptc.category",
    ),
    "SupplementalCategories": IptcApplicationTagSpec(
        tag_name="SupplementalCategories",
        dataset_id=20,
        max_length=32,
        is_list=True,
        evidence_id="iptc.supplementalcategories",
    ),
    "Keywords": IptcApplicationTagSpec(
        tag_name="Keywords",
        dataset_id=25,
        max_length=64,
        is_list=True,
        evidence_id="iptc.keywords",
    ),
    "SpecialInstructions": IptcApplicationTagSpec(
        tag_name="SpecialInstructions",
        dataset_id=40,
        max_length=256,
        is_list=False,
        evidence_id="iptc.specialinstructions",
    ),
    "ReleaseDate": IptcApplicationTagSpec(
        tag_name="ReleaseDate",
        dataset_id=30,
        max_length=8,
        is_list=False,
        value_kind="date",
        evidence_id="iptc.releasedate",
    ),
    "ReleaseTime": IptcApplicationTagSpec(
        tag_name="ReleaseTime",
        dataset_id=35,
        max_length=11,
        is_list=False,
        value_kind="time",
        evidence_id="iptc.releasetime",
    ),
    "ExpirationDate": IptcApplicationTagSpec(
        tag_name="ExpirationDate",
        dataset_id=37,
        max_length=8,
        is_list=False,
        value_kind="date",
        evidence_id="iptc.expirationdate",
    ),
    "ExpirationTime": IptcApplicationTagSpec(
        tag_name="ExpirationTime",
        dataset_id=38,
        max_length=11,
        is_list=False,
        value_kind="time",
        evidence_id="iptc.expirationtime",
    ),
    "ActionAdvised": IptcApplicationTagSpec(
        tag_name="ActionAdvised",
        dataset_id=42,
        max_length=2,
        is_list=False,
        value_kind="digits",
        evidence_id="iptc.actionadvised",
    ),
    "DateCreated": IptcApplicationTagSpec(
        tag_name="DateCreated",
        dataset_id=55,
        max_length=8,
        is_list=False,
        value_kind="date",
        evidence_id="iptc.datecreated",
    ),
    "TimeCreated": IptcApplicationTagSpec(
        tag_name="TimeCreated",
        dataset_id=60,
        max_length=11,
        is_list=False,
        value_kind="time",
        evidence_id="iptc.timecreated",
    ),
    "DigitalCreationDate": IptcApplicationTagSpec(
        tag_name="DigitalCreationDate",
        dataset_id=62,
        max_length=8,
        is_list=False,
        value_kind="date",
        evidence_id="iptc.digitalcreationdate",
    ),
    "DigitalCreationTime": IptcApplicationTagSpec(
        tag_name="DigitalCreationTime",
        dataset_id=63,
        max_length=11,
        is_list=False,
        value_kind="time",
        evidence_id="iptc.digitalcreationtime",
    ),
    "By-line": IptcApplicationTagSpec(
        tag_name="By-line",
        dataset_id=80,
        max_length=32,
        is_list=True,
        evidence_id="iptc.by-line",
    ),
    "By-lineTitle": IptcApplicationTagSpec(
        tag_name="By-lineTitle",
        dataset_id=85,
        max_length=32,
        is_list=True,
        evidence_id="iptc.by-linetitle",
    ),
    "City": IptcApplicationTagSpec(
        tag_name="City",
        dataset_id=90,
        max_length=32,
        is_list=False,
        evidence_id="iptc.city",
    ),
    "Province-State": IptcApplicationTagSpec(
        tag_name="Province-State",
        dataset_id=95,
        max_length=32,
        is_list=False,
        evidence_id="iptc.province-state",
    ),
    "Country-PrimaryLocationCode": IptcApplicationTagSpec(
        tag_name="Country-PrimaryLocationCode",
        dataset_id=100,
        max_length=3,
        is_list=False,
        evidence_id="iptc.country-primarylocationcode",
    ),
    "Country-PrimaryLocationName": IptcApplicationTagSpec(
        tag_name="Country-PrimaryLocationName",
        dataset_id=101,
        max_length=64,
        is_list=False,
        evidence_id="iptc.country-primarylocationname",
    ),
    "OriginalTransmissionReference": IptcApplicationTagSpec(
        tag_name="OriginalTransmissionReference",
        dataset_id=103,
        max_length=32,
        is_list=False,
        evidence_id="iptc.originaltransmissionreference",
    ),
    "Headline": IptcApplicationTagSpec(
        tag_name="Headline",
        dataset_id=105,
        max_length=256,
        is_list=False,
        evidence_id="iptc.headline",
    ),
    "Credit": IptcApplicationTagSpec(
        tag_name="Credit",
        dataset_id=110,
        max_length=32,
        is_list=False,
        evidence_id="iptc.credit",
    ),
    "Source": IptcApplicationTagSpec(
        tag_name="Source",
        dataset_id=115,
        max_length=32,
        is_list=False,
        evidence_id="iptc.source",
    ),
    "CopyrightNotice": IptcApplicationTagSpec(
        tag_name="CopyrightNotice",
        dataset_id=116,
        max_length=128,
        is_list=False,
        evidence_id="iptc.copyrightnotice",
    ),
    "Caption-Abstract": IptcApplicationTagSpec(
        tag_name="Caption-Abstract",
        dataset_id=120,
        max_length=2000,
        is_list=False,
        evidence_id="iptc.caption-abstract",
    ),
    "Writer-Editor": IptcApplicationTagSpec(
        tag_name="Writer-Editor",
        dataset_id=122,
        max_length=32,
        is_list=True,
        evidence_id="iptc.writer-editor",
    ),
    "AudioSamplingRate": IptcApplicationTagSpec(
        tag_name="AudioSamplingRate",
        dataset_id=151,
        max_length=6,
        is_list=False,
        value_kind="digits",
        evidence_id="iptc.audiosamplingrate",
    ),
    "AudioSamplingResolution": IptcApplicationTagSpec(
        tag_name="AudioSamplingResolution",
        dataset_id=152,
        max_length=2,
        is_list=False,
        value_kind="digits",
        evidence_id="iptc.audiosamplingresolution",
    ),
    "AudioDuration": IptcApplicationTagSpec(
        tag_name="AudioDuration",
        dataset_id=153,
        max_length=6,
        is_list=False,
        value_kind="digits",
        evidence_id="iptc.audioduration",
    ),
    "AudioOutcue": IptcApplicationTagSpec(
        tag_name="AudioOutcue",
        dataset_id=154,
        max_length=64,
        is_list=False,
        evidence_id="iptc.audiooutcue",
    ),
    "IPTCPixelWidth": IptcApplicationTagSpec(
        tag_name="IPTCPixelWidth",
        record_id=IPTC_NEWS_PHOTO_RECORD,
        dataset_id=40,
        max_length=5,
        is_list=False,
        value_kind="int16u",
        evidence_id="iptc.iptc-newsphoto-iptcpixelwidth",
    ),
}


def _iptc_pm_evidence_id(symbol: str) -> str:
    return f"iptc.{_slug(symbol)}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    if not slug:
        return "evidence"
    return slug


IPTC_APPLICATION_TAG_SPECS.update(
    {
        "EnvelopeRecordVersion": IptcApplicationTagSpec(
            tag_name="EnvelopeRecordVersion",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=0,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecordVersion"),
        ),
        "Destination": IptcApplicationTagSpec(
            tag_name="Destination",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=5,
            max_length=1024,
            is_list=True,
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecord Destination"),
        ),
        "FileFormat": IptcApplicationTagSpec(
            tag_name="FileFormat",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=20,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecord FileFormat"),
        ),
        "FileVersion": IptcApplicationTagSpec(
            tag_name="FileVersion",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=22,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecord FileVersion"),
        ),
        "ServiceIdentifier": IptcApplicationTagSpec(
            tag_name="ServiceIdentifier",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=30,
            max_length=10,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecord ServiceIdentifier"),
        ),
        "EnvelopeNumber": IptcApplicationTagSpec(
            tag_name="EnvelopeNumber",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=40,
            max_length=8,
            is_list=False,
            value_kind="digits",
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecord EnvelopeNumber"),
        ),
        "ProductID": IptcApplicationTagSpec(
            tag_name="ProductID",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=50,
            max_length=32,
            is_list=True,
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecord ProductID"),
        ),
        "EnvelopePriority": IptcApplicationTagSpec(
            tag_name="EnvelopePriority",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=60,
            max_length=1,
            is_list=False,
            value_kind="digits",
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecord EnvelopePriority"),
        ),
        "DateSent": IptcApplicationTagSpec(
            tag_name="DateSent",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=70,
            max_length=8,
            is_list=False,
            value_kind="date",
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecord DateSent"),
        ),
        "TimeSent": IptcApplicationTagSpec(
            tag_name="TimeSent",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=80,
            max_length=11,
            is_list=False,
            value_kind="time",
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecord TimeSent"),
        ),
        "UniqueObjectName": IptcApplicationTagSpec(
            tag_name="UniqueObjectName",
            record_id=IPTC_ENVELOPE_RECORD,
            dataset_id=100,
            min_length=14,
            max_length=80,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("EnvelopeRecord UniqueObjectName"),
        ),
        "ObjectTypeReference": IptcApplicationTagSpec(
            tag_name="ObjectTypeReference",
            dataset_id=3,
            min_length=3,
            max_length=67,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("ObjectTypeReference"),
        ),
        "ObjectAttributeReference": IptcApplicationTagSpec(
            tag_name="ObjectAttributeReference",
            dataset_id=4,
            min_length=4,
            max_length=68,
            is_list=True,
            evidence_id=_iptc_pm_evidence_id("ObjectAttributeReference"),
        ),
        "EditStatus": IptcApplicationTagSpec(
            tag_name="EditStatus",
            dataset_id=7,
            max_length=64,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("EditStatus"),
        ),
        "EditorialUpdate": IptcApplicationTagSpec(
            tag_name="EditorialUpdate",
            dataset_id=8,
            max_length=2,
            is_list=False,
            value_kind="digits",
            evidence_id=_iptc_pm_evidence_id("EditorialUpdate"),
        ),
        "SubjectReference": IptcApplicationTagSpec(
            tag_name="SubjectReference",
            dataset_id=12,
            min_length=13,
            max_length=236,
            is_list=True,
            evidence_id=_iptc_pm_evidence_id("SubjectReference"),
        ),
        "FixtureIdentifier": IptcApplicationTagSpec(
            tag_name="FixtureIdentifier",
            dataset_id=22,
            max_length=32,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("FixtureIdentifier"),
        ),
        "ContentLocationCode": IptcApplicationTagSpec(
            tag_name="ContentLocationCode",
            dataset_id=26,
            min_length=3,
            max_length=3,
            is_list=True,
            evidence_id=_iptc_pm_evidence_id("ContentLocationCode"),
        ),
        "ContentLocationName": IptcApplicationTagSpec(
            tag_name="ContentLocationName",
            dataset_id=27,
            max_length=64,
            is_list=True,
            evidence_id=_iptc_pm_evidence_id("ContentLocationName"),
        ),
        "ReferenceService": IptcApplicationTagSpec(
            tag_name="ReferenceService",
            dataset_id=45,
            max_length=10,
            is_list=True,
            evidence_id=_iptc_pm_evidence_id("ReferenceService"),
        ),
        "ReferenceDate": IptcApplicationTagSpec(
            tag_name="ReferenceDate",
            dataset_id=47,
            max_length=8,
            is_list=True,
            value_kind="date",
            evidence_id=_iptc_pm_evidence_id("ReferenceDate"),
        ),
        "ReferenceNumber": IptcApplicationTagSpec(
            tag_name="ReferenceNumber",
            dataset_id=50,
            max_length=8,
            is_list=True,
            value_kind="digits",
            evidence_id=_iptc_pm_evidence_id("ReferenceNumber"),
        ),
        "OriginatingProgram": IptcApplicationTagSpec(
            tag_name="OriginatingProgram",
            dataset_id=65,
            max_length=32,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("OriginatingProgram"),
        ),
        "ProgramVersion": IptcApplicationTagSpec(
            tag_name="ProgramVersion",
            dataset_id=70,
            max_length=10,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("ProgramVersion"),
        ),
        "ObjectCycle": IptcApplicationTagSpec(
            tag_name="ObjectCycle",
            dataset_id=75,
            min_length=1,
            max_length=1,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("ObjectCycle"),
        ),
        "Sub-location": IptcApplicationTagSpec(
            tag_name="Sub-location",
            dataset_id=92,
            max_length=32,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("Sub-location"),
        ),
        "Contact": IptcApplicationTagSpec(
            tag_name="Contact",
            dataset_id=118,
            max_length=128,
            is_list=True,
            evidence_id=_iptc_pm_evidence_id("Contact"),
        ),
        "LocalCaption": IptcApplicationTagSpec(
            tag_name="LocalCaption",
            dataset_id=121,
            max_length=256,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("LocalCaption"),
        ),
        "RasterizedCaption": IptcApplicationTagSpec(
            tag_name="RasterizedCaption",
            dataset_id=125,
            min_length=7360,
            max_length=7360,
            is_list=False,
            value_kind="binary",
            evidence_id=_iptc_pm_evidence_id("RasterizedCaption"),
        ),
        "ImageType": IptcApplicationTagSpec(
            tag_name="ImageType",
            dataset_id=130,
            min_length=2,
            max_length=2,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("ImageType"),
        ),
        "ImageOrientation": IptcApplicationTagSpec(
            tag_name="ImageOrientation",
            dataset_id=131,
            min_length=1,
            max_length=1,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("ImageOrientation"),
        ),
        "LanguageIdentifier": IptcApplicationTagSpec(
            tag_name="LanguageIdentifier",
            dataset_id=135,
            min_length=2,
            max_length=3,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("LanguageIdentifier"),
        ),
        "AudioType": IptcApplicationTagSpec(
            tag_name="AudioType",
            dataset_id=150,
            min_length=2,
            max_length=2,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("AudioType"),
        ),
        "JobID": IptcApplicationTagSpec(
            tag_name="JobID",
            dataset_id=184,
            max_length=64,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("JobID"),
        ),
        "MasterDocumentID": IptcApplicationTagSpec(
            tag_name="MasterDocumentID",
            dataset_id=185,
            max_length=256,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("MasterDocumentID"),
        ),
        "ShortDocumentID": IptcApplicationTagSpec(
            tag_name="ShortDocumentID",
            dataset_id=186,
            max_length=64,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("ShortDocumentID"),
        ),
        "UniqueDocumentID": IptcApplicationTagSpec(
            tag_name="UniqueDocumentID",
            dataset_id=187,
            max_length=128,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("UniqueDocumentID"),
        ),
        "OwnerID": IptcApplicationTagSpec(
            tag_name="OwnerID",
            dataset_id=188,
            max_length=128,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("OwnerID"),
        ),
        "ObjectPreviewFileFormat": IptcApplicationTagSpec(
            tag_name="ObjectPreviewFileFormat",
            dataset_id=200,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("ObjectPreviewFileFormat"),
        ),
        "ObjectPreviewFileVersion": IptcApplicationTagSpec(
            tag_name="ObjectPreviewFileVersion",
            dataset_id=201,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("ObjectPreviewFileVersion"),
        ),
        "ObjectPreviewData": IptcApplicationTagSpec(
            tag_name="ObjectPreviewData",
            dataset_id=202,
            max_length=256000,
            is_list=False,
            value_kind="binary",
            evidence_id=_iptc_pm_evidence_id("ObjectPreviewData"),
        ),
        "Prefs": IptcApplicationTagSpec(
            tag_name="Prefs",
            dataset_id=221,
            max_length=64,
            is_list=False,
            value_kind="prefs",
            evidence_id=_iptc_pm_evidence_id("Prefs"),
        ),
        "DocumentNotes": IptcApplicationTagSpec(
            tag_name="DocumentNotes",
            dataset_id=230,
            max_length=1024,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("DocumentNotes"),
        ),
        "DocumentHistory": IptcApplicationTagSpec(
            tag_name="DocumentHistory",
            dataset_id=231,
            max_length=256,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("DocumentHistory"),
        ),
        "ExifCameraInfo": IptcApplicationTagSpec(
            tag_name="ExifCameraInfo",
            dataset_id=232,
            max_length=4096,
            is_list=False,
            evidence_id=_iptc_pm_evidence_id("ExifCameraInfo"),
        ),
        "CatalogSets": IptcApplicationTagSpec(
            tag_name="CatalogSets",
            dataset_id=255,
            max_length=256,
            is_list=True,
            evidence_id=_iptc_pm_evidence_id("CatalogSets"),
        ),
        "NewsPhotoVersion": IptcApplicationTagSpec(
            tag_name="NewsPhotoVersion",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=0,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("NewsPhotoVersion"),
        ),
        "IPTCPictureNumber": IptcApplicationTagSpec(
            tag_name="IPTCPictureNumber",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=10,
            min_length=16,
            max_length=16,
            is_list=False,
            value_kind="picture_number",
            evidence_id=_iptc_pm_evidence_id("IPTCPictureNumber"),
        ),
        "IPTCImageWidth": IptcApplicationTagSpec(
            tag_name="IPTCImageWidth",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=20,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("IPTCImageWidth"),
        ),
        "IPTCImageHeight": IptcApplicationTagSpec(
            tag_name="IPTCImageHeight",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=30,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("IPTCImageHeight"),
        ),
        "IPTCPixelHeight": IptcApplicationTagSpec(
            tag_name="IPTCPixelHeight",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=50,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("IPTCPixelHeight"),
        ),
        "SupplementalType": IptcApplicationTagSpec(
            tag_name="SupplementalType",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=55,
            max_length=1,
            is_list=False,
            value_kind="int8u",
            evidence_id=_iptc_pm_evidence_id("SupplementalType"),
        ),
        "ColorRepresentation": IptcApplicationTagSpec(
            tag_name="ColorRepresentation",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=60,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("ColorRepresentation"),
        ),
        "InterchangeColorSpace": IptcApplicationTagSpec(
            tag_name="InterchangeColorSpace",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=64,
            max_length=1,
            is_list=False,
            value_kind="int8u",
            evidence_id=_iptc_pm_evidence_id("InterchangeColorSpace"),
        ),
        "ColorSequence": IptcApplicationTagSpec(
            tag_name="ColorSequence",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=65,
            max_length=1,
            is_list=False,
            value_kind="int8u",
            evidence_id=_iptc_pm_evidence_id("ColorSequence"),
        ),
        "NumIndexEntries": IptcApplicationTagSpec(
            tag_name="NumIndexEntries",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=84,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("NumIndexEntries"),
        ),
        "IPTCBitsPerSample": IptcApplicationTagSpec(
            tag_name="IPTCBitsPerSample",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=86,
            max_length=1,
            is_list=False,
            value_kind="int8u",
            evidence_id=_iptc_pm_evidence_id("IPTCBitsPerSample"),
        ),
        "SampleStructure": IptcApplicationTagSpec(
            tag_name="SampleStructure",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=90,
            max_length=1,
            is_list=False,
            value_kind="int8u",
            evidence_id=_iptc_pm_evidence_id("SampleStructure"),
        ),
        "ScanningDirection": IptcApplicationTagSpec(
            tag_name="ScanningDirection",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=100,
            max_length=1,
            is_list=False,
            value_kind="int8u",
            evidence_id=_iptc_pm_evidence_id("ScanningDirection"),
        ),
        "IPTCImageRotation": IptcApplicationTagSpec(
            tag_name="IPTCImageRotation",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=102,
            max_length=1,
            is_list=False,
            value_kind="int8u",
            evidence_id=_iptc_pm_evidence_id("IPTCImageRotation"),
        ),
        "DataCompressionMethod": IptcApplicationTagSpec(
            tag_name="DataCompressionMethod",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=110,
            max_length=4,
            is_list=False,
            value_kind="int32u",
            evidence_id=_iptc_pm_evidence_id("DataCompressionMethod"),
        ),
        "QuantizationMethod": IptcApplicationTagSpec(
            tag_name="QuantizationMethod",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=120,
            max_length=1,
            is_list=False,
            value_kind="int8u",
            evidence_id=_iptc_pm_evidence_id("QuantizationMethod"),
        ),
        "ExcursionTolerance": IptcApplicationTagSpec(
            tag_name="ExcursionTolerance",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=130,
            max_length=1,
            is_list=False,
            value_kind="int8u",
            evidence_id=_iptc_pm_evidence_id("ExcursionTolerance"),
        ),
        "BitsPerComponent": IptcApplicationTagSpec(
            tag_name="BitsPerComponent",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=135,
            max_length=1,
            is_list=False,
            value_kind="int8u",
            evidence_id=_iptc_pm_evidence_id("BitsPerComponent"),
        ),
        "MaximumDensityRange": IptcApplicationTagSpec(
            tag_name="MaximumDensityRange",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=140,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("MaximumDensityRange"),
        ),
        "GammaCompensatedValue": IptcApplicationTagSpec(
            tag_name="GammaCompensatedValue",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=145,
            max_length=2,
            is_list=False,
            value_kind="int16u",
            evidence_id=_iptc_pm_evidence_id("GammaCompensatedValue"),
        ),
        "SubFile": IptcApplicationTagSpec(
            tag_name="SubFile",
            record_id=IPTC_OBJECT_DATA_RECORD,
            dataset_id=10,
            max_length=0xFFFFFFFF,
            is_list=True,
            value_kind="binary",
            evidence_id=_iptc_pm_evidence_id("ObjectData SubFile"),
        ),
    }
)


def build_iptc_application_write_plan(
    keywords: tuple[str, ...] = (),
    city: str | None = None,
) -> IptcApplicationWritePlan:
    steps: list[IptcApplicationWriteStep] = []
    if keywords:
        steps.append(keywords_step(keywords))
    if city is not None:
        steps.append(city_step(city))
    if not steps:
        raise ValueError("IPTC ApplicationRecord write plan requires at least one value.")
    return IptcApplicationWritePlan(tuple(steps))


def keywords_step(values: tuple[str, ...]) -> IptcApplicationWriteStep:
    return upsert_text_step("Keywords", values)


def city_step(value: str) -> IptcApplicationWriteStep:
    return upsert_text_step("City", (value,))


def upsert_text_step(
    tag_name: str,
    values: tuple[str, ...],
    *,
    text_encoding: IptcTextEncoding = "latin-1",
) -> IptcApplicationWriteStep:
    return text_step("upsert", tag_name, values, text_encoding=text_encoding)


def upsert_binary_step(tag_name: str, values: tuple[bytes, ...]) -> IptcApplicationWriteStep:
    return text_step("upsert", tag_name, values)


def delete_text_value_step(
    tag_name: str,
    values: tuple[str, ...],
    *,
    text_encoding: IptcTextEncoding = "latin-1",
) -> IptcApplicationWriteStep:
    return text_step("delete_value", tag_name, values, text_encoding=text_encoding)


def text_step(
    operation: IptcApplicationWriteOperation,
    tag_name: str,
    values: tuple[IptcDatasetValue, ...],
    *,
    text_encoding: IptcTextEncoding = "latin-1",
) -> IptcApplicationWriteStep:
    spec = iptc_application_tag_spec(tag_name)
    if spec is None:
        raise ValueError(f"Unsupported IPTC ApplicationRecord tag: {tag_name}")
    if operation != "delete" and not values:
        raise ValueError(f"IPTC {spec.tag_name} requires at least one value.")
    if not spec.is_list and len(values) > 1:
        raise ValueError(f"IPTC {spec.tag_name} accepts one value.")
    validate_iptc_values(spec, values, text_encoding=text_encoding)
    return IptcApplicationWriteStep(
        operation=operation,
        tag_name=spec.tag_name,
        record_id=spec.record_id,
        dataset_id=spec.dataset_id,
        is_list=spec.is_list,
        value_kind=spec.value_kind,
        values=values,
        evidence_ids=(
            iptc_record_evidence_id(spec.record_id),
            spec.evidence_id,
            PHOTOSHOP_IPTC_RESOURCE_EVIDENCE_ID,
        ),
    )


def iptc_record_evidence_id(record_id: int) -> str:
    if record_id == IPTC_ENVELOPE_RECORD:
        return IPTC_ENVELOPE_RECORD_EVIDENCE_ID
    if record_id == IPTC_NEWS_PHOTO_RECORD:
        return IPTC_NEWS_PHOTO_RECORD_EVIDENCE_ID
    if record_id == IPTC_OBJECT_DATA_RECORD:
        return IPTC_OBJECT_DATA_RECORD_EVIDENCE_ID
    return IPTC_APPLICATION_RECORD_EVIDENCE_ID


def iptc_application_tag_spec(tag_name: str) -> IptcApplicationTagSpec | None:
    return IPTC_APPLICATION_TAG_SPECS.get(tag_name)


def coalesce_iptc_application_steps(
    steps: tuple[IptcApplicationWriteStep, ...],
) -> tuple[IptcApplicationWriteStep, ...]:
    coalesced: list[IptcApplicationWriteStep] = []
    for step in steps:
        if coalesced and can_coalesce_iptc_application_steps(coalesced[-1], step):
            previous = coalesced[-1]
            coalesced[-1] = IptcApplicationWriteStep(
                operation=previous.operation,
                tag_name=previous.tag_name,
                record_id=previous.record_id,
                dataset_id=previous.dataset_id,
                is_list=previous.is_list,
                value_kind=previous.value_kind,
                values=(*previous.values, *step.values),
                evidence_ids=previous.evidence_ids,
            )
        else:
            coalesced.append(step)
    return tuple(coalesced)


def can_coalesce_iptc_application_steps(
    left: IptcApplicationWriteStep,
    right: IptcApplicationWriteStep,
) -> bool:
    return (
        left.operation == right.operation
        and left.record_id == right.record_id
        and left.dataset_id == right.dataset_id
        and left.value_kind == right.value_kind
        and left.evidence_ids == right.evidence_ids
    )


def validate_iptc_values(
    spec: IptcApplicationTagSpec,
    values: tuple[IptcDatasetValue, ...],
    *,
    text_encoding: IptcTextEncoding = "latin-1",
) -> None:
    for value in values:
        if spec.value_kind == "text":
            if not isinstance(value, str):
                raise ValueError(f"IPTC {spec.tag_name} requires text.")
            validate_iptc_text_value(spec.tag_name, value, spec.max_length, text_encoding)
        elif spec.value_kind == "digits":
            if not isinstance(value, str):
                raise ValueError(f"IPTC {spec.tag_name} requires digits text.")
            validate_iptc_digits_value(spec.tag_name, value, spec.max_length)
        elif spec.value_kind == "date":
            if not isinstance(value, str):
                raise ValueError(f"IPTC {spec.tag_name} requires date text.")
            validate_iptc_converted_text_value(
                spec.tag_name,
                iptc_date_value(value),
                spec.max_length,
            )
        elif spec.value_kind == "time":
            if not isinstance(value, str):
                raise ValueError(f"IPTC {spec.tag_name} requires time text.")
            validate_iptc_converted_text_value(
                spec.tag_name,
                iptc_time_value(value),
                spec.max_length,
            )
        elif spec.value_kind == "int8u":
            if not isinstance(value, str):
                raise ValueError(f"IPTC {spec.tag_name} requires integer text.")
            validate_iptc_unsigned_int_value(spec.tag_name, value, 0xFF)
        elif spec.value_kind == "int16u":
            if not isinstance(value, str):
                raise ValueError(f"IPTC {spec.tag_name} requires integer text.")
            validate_iptc_unsigned_int_value(spec.tag_name, value, 0xFFFF)
        elif spec.value_kind == "int32u":
            if not isinstance(value, str):
                raise ValueError(f"IPTC {spec.tag_name} requires integer text.")
            validate_iptc_unsigned_int_value(spec.tag_name, value, 0xFFFFFFFF)
        elif spec.value_kind == "binary":
            if not isinstance(value, bytes):
                raise ValueError(f"IPTC {spec.tag_name} requires bytes.")
            validate_iptc_binary_value(spec.tag_name, value, spec.min_length, spec.max_length)
        elif spec.value_kind == "picture_number":
            if not isinstance(value, str):
                raise ValueError(f"IPTC {spec.tag_name} requires picture-number text.")
            validate_iptc_converted_text_value(
                spec.tag_name,
                iptc_picture_number_value(value),
                spec.max_length,
            )
        elif spec.value_kind == "prefs":
            if not isinstance(value, str):
                raise ValueError(f"IPTC {spec.tag_name} requires preferences text.")
            validate_iptc_converted_text_value(
                spec.tag_name,
                iptc_prefs_value(value),
                spec.max_length,
            )


def validate_iptc_text_value(
    tag_name: str,
    value: str,
    max_length: int,
    text_encoding: IptcTextEncoding = "latin-1",
) -> None:
    if not value:
        raise ValueError(f"IPTC {tag_name} must not be empty.")
    encoded_iptc_text_value(tag_name, value, text_encoding)


def validate_iptc_binary_value(
    tag_name: str,
    value: bytes,
    min_length: int,
    max_length: int,
) -> None:
    if len(value) < min_length:
        raise ValueError(f"IPTC {tag_name} must be at least {min_length} bytes.")
    if len(value) > max_length:
        raise ValueError(f"IPTC {tag_name} must be at most {max_length} bytes.")


def encoded_iptc_text_value(tag_name: str, value: str, text_encoding: str) -> bytes:
    if tag_name == "CodedCharacterSet":
        return coded_character_set_value_bytes(value)
    return value.encode(text_encoding)


def coded_character_set_value_bytes(value: str) -> bytes:
    if value.upper().replace("-", "") == "UTF8":
        return b"\x1b%G"
    if re.search("ESC", value, flags=re.IGNORECASE):
        coded = re.sub("ESC *", "\x1b", value, flags=re.IGNORECASE)
        coded = coded.replace(", \x1b", "\x1b")
        coded = coded.replace(" ", "")
        return coded.encode("latin-1")
    return value.encode("latin-1")


def validate_iptc_converted_text_value(tag_name: str, value: str | bytes, max_length: int) -> None:
    if len(value) > max_length:
        raise ValueError(f"IPTC {tag_name} must be at most {max_length} bytes.")


def validate_iptc_digits_value(tag_name: str, value: str, max_length: int) -> None:
    if not value.isdecimal():
        raise ValueError(f"IPTC {tag_name} must contain only digits.")
    if len(value) > max_length:
        raise ValueError(f"IPTC {tag_name} must be at most {max_length} digits.")


def validate_iptc_unsigned_int_value(tag_name: str, value: str, max_value: int) -> None:
    integer = iptc_unsigned_int_value(tag_name, value)
    if integer > max_value:
        raise ValueError(f"IPTC {tag_name} must be at most {max_value}.")


def iptc_unsigned_int_value(tag_name: str, value: str) -> int:
    normalized = value.strip()
    if re.fullmatch(r"0x[0-9a-fA-F]+", normalized):
        return int(normalized, 16)
    if normalized.isdecimal():
        return int(normalized)
    raise ValueError(f"IPTC {tag_name} must be an unsigned integer.")


def iptc_picture_number_value(value: str) -> bytes:
    normalized = re.sub(r"\(.*?\)", "", value)
    normalized = normalized.replace(":", "")
    normalized = re.sub(r"[^0-9]", " ", normalized)
    parts = normalized.split()
    if len(parts) >= 4:
        manufacturer = int(parts[0])
        equipment = int(parts[1])
        date = parts[2].encode("ascii")
        sequence = int(parts[3])
        if manufacturer > 0xFFFF or equipment > 0xFFFFFFFF or sequence > 0xFFFF:
            raise ValueError("IPTC IPTCPictureNumber numeric component is too large.")
        if len(date) != 8 or not date.isdigit():
            raise ValueError("IPTC IPTCPictureNumber date must be YYYYMMDD.")
        return (
            manufacturer.to_bytes(2, "big")
            + equipment.to_bytes(4, "big")
            + date
            + sequence.to_bytes(2, "big")
        )
    if "unknown" in value.lower():
        return b"\x00" * 16
    raise ValueError("IPTC IPTCPictureNumber requires four numbers or Unknown.")


def iptc_prefs_value(value: str) -> str:
    match = re.search(
        r"Tagged:\s*(\d+).*ColorClass:\s*(\d+).*Rating:\s*(\d+).*FrameNum:\s*(\S*)",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return value
    return f"{match.group(1)}:{match.group(2)}:{match.group(3)}:{match.group(4)}"


def iptc_date_value(value: str) -> str:
    match = re.search(r"(\d{4})[-:/.]?(\d{2})[-:/.]?(\d{2})", value)
    if match is None:
        raise ValueError("Invalid date format (use YYYY:mm:dd).")
    return "".join(match.groups())


def iptc_time_value(value: str) -> str:
    match = re.search(
        r"(?:^|.*?\b)(\d{1,2})(:?)(\d{2})(:?)(\d{2})(\S*)\s*$",
        value,
    )
    if match is None or (not match.group(2) and match.group(4)):
        raise ValueError("Invalid time format (use HH:MM:SS[+/-HH:MM]).")
    hour = int(match.group(1))
    minute = int(match.group(3))
    second = int(match.group(5))
    suffix = match.group(6)
    if suffix.upper() == "Z":
        timezone = "+0000"
    else:
        zone_match = re.fullmatch(r"([+-]\d{1,2}):?(\d{2})", suffix)
        if zone_match is None:
            timezone = "+0000"
        else:
            timezone = f"{int(zone_match.group(1)):+03d}{zone_match.group(2)}"
    return f"{hour:02d}{minute:02d}{second:02d}{timezone}"


def blocked_iptc_binary_payload_datasets() -> tuple[IptcBinaryPayloadBlocker, ...]:
    return (
        IptcBinaryPayloadBlocker(
            tag_name="RasterizedCaption",
            record_id=IPTC_APPLICATION_RECORD,
            dataset_id=125,
            code="rasterized_caption_generation_unowned",
            reason=(
                "Raw RasterizedCaption bytes are writable as fixed undef[7360], but "
                "ExifTool source does not define text-to-raster caption generation semantics."
            ),
            evidence_id=_iptc_pm_evidence_id("RasterizedCaption"),
        ),
        IptcBinaryPayloadBlocker(
            tag_name="ICC_Profile",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=66,
            code="newsphoto_binary_not_writable",
            reason="IPTC.pm marks NewsPhoto ICC_Profile Writable => 0.",
            evidence_id=_iptc_pm_evidence_id("ICC_Profile"),
        ),
        IptcBinaryPayloadBlocker(
            tag_name="ColorCalibrationMatrix",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=70,
            code="newsphoto_binary_not_writable",
            reason="IPTC.pm marks NewsPhoto ColorCalibrationMatrix Writable => 0.",
            evidence_id=_iptc_pm_evidence_id("ColorCalibrationMatrix"),
        ),
        IptcBinaryPayloadBlocker(
            tag_name="LookupTable",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=80,
            code="newsphoto_binary_not_writable",
            reason="IPTC.pm marks NewsPhoto LookupTable Writable => 0.",
            evidence_id=_iptc_pm_evidence_id("LookupTable"),
        ),
        IptcBinaryPayloadBlocker(
            tag_name="ColorPalette",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=85,
            code="newsphoto_binary_not_writable",
            reason="IPTC.pm marks NewsPhoto ColorPalette Writable => 0.",
            evidence_id=_iptc_pm_evidence_id("ColorPalette"),
        ),
        IptcBinaryPayloadBlocker(
            tag_name="EndPoints",
            record_id=IPTC_NEWS_PHOTO_RECORD,
            dataset_id=125,
            code="newsphoto_binary_not_writable",
            reason="IPTC.pm marks NewsPhoto EndPoints Writable => 0.",
            evidence_id=_iptc_pm_evidence_id("EndPoints"),
        ),
    )
