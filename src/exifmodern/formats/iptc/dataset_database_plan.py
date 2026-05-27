"""Source-backed IPTC dataset database extraction planning.

ExifTool's IPTC.pm is both the dataset database and part of the runtime
behavior for charset, validation, digest, and record-order handling. This
module captures those source facts as typed planning data while keeping the
current modern read/write modules as explicit runtime gates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.iptc.reader import IPTC_APPLICATION_TAGS, IPTC_ENVELOPE_TAGS
from exifmodern.formats.iptc.write_plan import IPTC_APPLICATION_TAG_SPECS

type IptcDatasetRecordName = Literal["EnvelopeRecord", "ApplicationRecord"]
type IptcDatasetValueKind = Literal["digits", "int", "string", "undef"]
type IptcDatasetRuntimeGateStatus = Literal["ready", "planned", "blocked"]
type IptcDatasetRuntimeSurface = Literal["read", "write", "charset", "digest", "database"]


IPTC_DATASET_MARKER = 0x1C
IPTC_ENVELOPE_RECORD = 1
IPTC_APPLICATION_RECORD = 2
IPTC_CODED_CHARACTER_SET_DATASET = 90
IPTC_CODED_CHARACTER_SET_UTF8_ESCAPE = b"\x1b%G"

IPTC_MAIN_TABLE_EVIDENCE_ID = "iptc.iptc-main-table"
IPTC_ENVELOPE_TABLE_EVIDENCE_ID = "iptc.iptc-envelope-table"
IPTC_APPLICATION_TABLE_EVIDENCE_ID = "iptc.iptc-application-table"
IPTC_CHECK_EVIDENCE_ID = "iptc.iptc-check"
IPTC_FORMAT_WRITE_EVIDENCE_ID = "iptc.iptc-format-write"
IPTC_WRITE_ORDER_EVIDENCE_ID = "iptc.iptc-write-order"
IPTC_LIST_WRITE_EVIDENCE_ID = "iptc.iptc-list-write"
IPTC_MANDATORY_WRITE_EVIDENCE_ID = "iptc.iptc-mandatory-write"
IPTC_MANDATORY_INSERT_EVIDENCE_ID = "iptc.iptc-mandatory-insert"
IPTC_STANDARD_LOCATION_EVIDENCE_ID = "iptc.iptc-standard-location"
IPTC_READ_DIGEST_EVIDENCE_ID = "iptc.iptc-read-digest"
IPTC_WRITE_DIGEST_EVIDENCE_ID = "iptc.iptc-write-digest"
IPTC_CODED_CHARACTER_SET_EVIDENCE_ID = "iptc.iptc-coded-character-set"
IPTC_CHARSET_TABLE_EVIDENCE_ID = "iptc.iptc-charset-table"
IPTC_PRINT_CODED_CHARSET_EVIDENCE_ID = "iptc.iptc-print-coded-charset"
IPTC_PRINT_INV_CODED_CHARSET_EVIDENCE_ID = "iptc.iptc-print-inv-coded-charset"
IPTC_HANDLE_CODED_CHARSET_EVIDENCE_ID = "iptc.iptc-handle-coded-charset"
IPTC_TRANSLATE_CODED_STRING_EVIDENCE_ID = "iptc.iptc-translate-coded-string"
IPTC_PROCESS_CHARSET_EVIDENCE_ID = "iptc.iptc-process-charset"

_IPTC_FORMAT_RE = re.compile(r"^(?P<kind>string|digits|undef)\[(?P<min>\d+)(?:,(?P<max>\d*))?\]$")
_IPTC_INT_FORMAT_RE = re.compile(r"^int(?P<bits>\d+)u?$")


@dataclass(frozen=True)
class IptcDatasetFormatPlan:
    raw_format: str
    value_kind: IptcDatasetValueKind
    min_bytes: int
    max_bytes: int
    fixed_width: bool
    binary: bool = False


@dataclass(frozen=True)
class IptcDatasetRecordPlan:
    record_id: int
    record_name: IptcDatasetRecordName
    main_tag_name: str
    source_symbol: str
    writable: bool
    write_proc: str
    check_proc: str
    evidence_id: str


@dataclass(frozen=True)
class IptcDatasetPlan:
    record_id: int
    dataset_id: int
    tag_name: str
    format: IptcDatasetFormatPlan
    repeatable: bool
    mandatory: bool
    protected: bool
    evidence_id: str
    notes: str | None = None

    @property
    def key(self) -> tuple[int, int]:
        return (self.record_id, self.dataset_id)

    @property
    def current_writer_supported(self) -> bool:
        spec = IPTC_APPLICATION_TAG_SPECS.get(self.tag_name)
        return spec is not None and (spec.record_id, spec.dataset_id) == self.key

    @property
    def current_reader_supported(self) -> bool:
        if self.record_id == IPTC_ENVELOPE_RECORD:
            return IPTC_ENVELOPE_TAGS.get(self.dataset_id) == self.tag_name
        if self.record_id == IPTC_APPLICATION_RECORD:
            return IPTC_APPLICATION_TAGS.get(self.dataset_id) == self.tag_name
        return False


@dataclass(frozen=True)
class IptcCodedCharacterSetPlan:
    dataset_key: tuple[int, int]
    tag_name: str
    raw_utf8_escape: bytes
    print_name: str
    protected_from_default_copy: bool
    affects_record_ids: tuple[int, ...]
    evidence_ids: tuple[str, ...]

    def print_value(self, raw_value: bytes) -> str:
        return print_coded_character_set(raw_value)

    def inverse_print_value(self, value: str) -> bytes:
        return inverse_print_coded_character_set(value)


@dataclass(frozen=True)
class IptcDigestResponsibilityPlan:
    current_digest_tag: str
    photoshop_digest_tag: str
    standard_locations: tuple[str, ...]
    read_behavior: str
    write_behavior: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IptcRuntimeGate:
    gate_id: str
    surface: IptcDatasetRuntimeSurface
    status: IptcDatasetRuntimeGateStatus
    target: str
    requirement: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IptcDatasetDatabasePlan:
    records: tuple[IptcDatasetRecordPlan, ...]
    datasets: tuple[IptcDatasetPlan, ...]
    coded_character_set: IptcCodedCharacterSetPlan
    digest_responsibility: IptcDigestResponsibilityPlan
    runtime_gates: tuple[IptcRuntimeGate, ...]

    def record(self, record_id: int) -> IptcDatasetRecordPlan:
        for record in self.records:
            if record.record_id == record_id:
                return record
        raise KeyError(record_id)

    def dataset(self, record_id: int, dataset_id: int) -> IptcDatasetPlan:
        for dataset in self.datasets:
            if dataset.key == (record_id, dataset_id):
                return dataset
        raise KeyError((record_id, dataset_id))

    def dataset_by_name(self, tag_name: str) -> IptcDatasetPlan:
        for dataset in self.datasets:
            if dataset.tag_name == tag_name:
                return dataset
        raise KeyError(tag_name)

    def current_writer_datasets(self) -> tuple[IptcDatasetPlan, ...]:
        return tuple(dataset for dataset in self.datasets if dataset.current_writer_supported)

    def current_reader_datasets(self) -> tuple[IptcDatasetPlan, ...]:
        return tuple(dataset for dataset in self.datasets if dataset.current_reader_supported)

    def runtime_gate(self, gate_id: str) -> IptcRuntimeGate:
        for gate in self.runtime_gates:
            if gate.gate_id == gate_id:
                return gate
        raise KeyError(gate_id)


def iptc_dataset_database_plan() -> IptcDatasetDatabasePlan:
    """Return the source-backed IPTC Application/Envelope database port plan."""

    return IptcDatasetDatabasePlan(
        records=iptc_dataset_records(),
        datasets=iptc_dataset_plans(),
        coded_character_set=iptc_coded_character_set_plan(),
        digest_responsibility=iptc_digest_responsibility_plan(),
        runtime_gates=iptc_runtime_gates(),
    )


def iptc_dataset_records() -> tuple[IptcDatasetRecordPlan, ...]:
    return (
        IptcDatasetRecordPlan(
            record_id=IPTC_ENVELOPE_RECORD,
            record_name="EnvelopeRecord",
            main_tag_name="IPTCEnvelope",
            source_symbol="Image::ExifTool::IPTC::EnvelopeRecord",
            writable=True,
            write_proc="WriteIPTC",
            check_proc="CheckIPTC",
            evidence_id=IPTC_ENVELOPE_TABLE_EVIDENCE_ID,
        ),
        IptcDatasetRecordPlan(
            record_id=IPTC_APPLICATION_RECORD,
            record_name="ApplicationRecord",
            main_tag_name="IPTCApplication",
            source_symbol="Image::ExifTool::IPTC::ApplicationRecord",
            writable=True,
            write_proc="WriteIPTC",
            check_proc="CheckIPTC",
            evidence_id=IPTC_APPLICATION_TABLE_EVIDENCE_ID,
        ),
    )


def iptc_dataset_plans() -> tuple[IptcDatasetPlan, ...]:
    return (
        envelope_dataset(0, "EnvelopeRecordVersion", "int16u", mandatory=True),
        envelope_dataset(5, "Destination", "string[0,1024]", repeatable=True),
        envelope_dataset(20, "FileFormat", "int16u"),
        envelope_dataset(22, "FileVersion", "int16u"),
        envelope_dataset(30, "ServiceIdentifier", "string[0,10]"),
        envelope_dataset(40, "EnvelopeNumber", "digits[8]"),
        envelope_dataset(50, "ProductID", "string[0,32]", repeatable=True),
        envelope_dataset(60, "EnvelopePriority", "digits[1]"),
        envelope_dataset(70, "DateSent", "digits[8]"),
        envelope_dataset(80, "TimeSent", "string[11]"),
        envelope_dataset(
            90,
            "CodedCharacterSet",
            "string[0,32]",
            protected=True,
            notes=(
                "Controls decoding for ApplicationRecord and NewsPhoto strings; "
                "ExifTool marks it protected to avoid unsafe group-copy behavior."
            ),
        ),
        envelope_dataset(100, "UniqueObjectName", "string[14,80]"),
        envelope_dataset(120, "ARMIdentifier", "int16u"),
        envelope_dataset(122, "ARMVersion", "int16u"),
        application_dataset(0, "ApplicationRecordVersion", "int16u", mandatory=True),
        application_dataset(3, "ObjectTypeReference", "string[3,67]"),
        application_dataset(4, "ObjectAttributeReference", "string[4,68]", repeatable=True),
        application_dataset(5, "ObjectName", "string[0,64]"),
        application_dataset(7, "EditStatus", "string[0,64]"),
        application_dataset(8, "EditorialUpdate", "digits[2]"),
        application_dataset(10, "Urgency", "digits[1]"),
        application_dataset(12, "SubjectReference", "string[13,236]", repeatable=True),
        application_dataset(15, "Category", "string[0,3]"),
        application_dataset(20, "SupplementalCategories", "string[0,32]", repeatable=True),
        application_dataset(22, "FixtureIdentifier", "string[0,32]"),
        application_dataset(25, "Keywords", "string[0,64]", repeatable=True),
        application_dataset(26, "ContentLocationCode", "string[3]", repeatable=True),
        application_dataset(27, "ContentLocationName", "string[0,64]", repeatable=True),
        application_dataset(30, "ReleaseDate", "digits[8]"),
        application_dataset(35, "ReleaseTime", "string[11]"),
        application_dataset(37, "ExpirationDate", "digits[8]"),
        application_dataset(38, "ExpirationTime", "string[11]"),
        application_dataset(40, "SpecialInstructions", "string[0,256]"),
        application_dataset(42, "ActionAdvised", "digits[2]"),
        application_dataset(45, "ReferenceService", "string[0,10]", repeatable=True),
        application_dataset(47, "ReferenceDate", "digits[8]", repeatable=True),
        application_dataset(50, "ReferenceNumber", "digits[8]", repeatable=True),
        application_dataset(55, "DateCreated", "digits[8]"),
        application_dataset(60, "TimeCreated", "string[11]"),
        application_dataset(62, "DigitalCreationDate", "digits[8]"),
        application_dataset(63, "DigitalCreationTime", "string[11]"),
        application_dataset(65, "OriginatingProgram", "string[0,32]"),
        application_dataset(70, "ProgramVersion", "string[0,10]"),
        application_dataset(75, "ObjectCycle", "string[1]"),
        application_dataset(80, "By-line", "string[0,32]", repeatable=True),
        application_dataset(85, "By-lineTitle", "string[0,32]", repeatable=True),
        application_dataset(90, "City", "string[0,32]"),
        application_dataset(92, "Sub-location", "string[0,32]"),
        application_dataset(95, "Province-State", "string[0,32]"),
        application_dataset(100, "Country-PrimaryLocationCode", "string[3]"),
        application_dataset(101, "Country-PrimaryLocationName", "string[0,64]"),
        application_dataset(103, "OriginalTransmissionReference", "string[0,32]"),
        application_dataset(105, "Headline", "string[0,256]"),
        application_dataset(110, "Credit", "string[0,32]"),
        application_dataset(115, "Source", "string[0,32]"),
        application_dataset(116, "CopyrightNotice", "string[0,128]"),
        application_dataset(118, "Contact", "string[0,128]", repeatable=True),
        application_dataset(120, "Caption-Abstract", "string[0,2000]"),
        application_dataset(121, "LocalCaption", "string[0,256]"),
        application_dataset(122, "Writer-Editor", "string[0,32]", repeatable=True),
        application_dataset(125, "RasterizedCaption", "undef[7360]", binary=True),
        application_dataset(130, "ImageType", "string[2]"),
        application_dataset(131, "ImageOrientation", "string[1]"),
        application_dataset(135, "LanguageIdentifier", "string[2,3]"),
        application_dataset(150, "AudioType", "string[2]"),
        application_dataset(151, "AudioSamplingRate", "digits[6]"),
        application_dataset(152, "AudioSamplingResolution", "digits[2]"),
        application_dataset(153, "AudioDuration", "digits[6]"),
        application_dataset(154, "AudioOutcue", "string[0,64]"),
        application_dataset(184, "JobID", "string[0,64]"),
        application_dataset(185, "MasterDocumentID", "string[0,256]"),
        application_dataset(186, "ShortDocumentID", "string[0,64]"),
        application_dataset(187, "UniqueDocumentID", "string[0,128]"),
        application_dataset(188, "OwnerID", "string[0,128]"),
        application_dataset(200, "ObjectPreviewFileFormat", "int16u"),
        application_dataset(201, "ObjectPreviewFileVersion", "int16u"),
        application_dataset(202, "ObjectPreviewData", "undef[0,256000]", binary=True),
        application_dataset(221, "Prefs", "string[0,64]"),
        application_dataset(225, "ClassifyState", "string[0,64]"),
        application_dataset(228, "SimilarityIndex", "string[0,32]"),
        application_dataset(230, "DocumentNotes", "string[0,1024]"),
        application_dataset(231, "DocumentHistory", "string[0,256]"),
        application_dataset(232, "ExifCameraInfo", "string[0,4096]"),
        application_dataset(255, "CatalogSets", "string[0,256]", repeatable=True),
    )


def envelope_dataset(
    dataset_id: int,
    tag_name: str,
    raw_format: str,
    *,
    repeatable: bool = False,
    mandatory: bool = False,
    protected: bool = False,
    binary: bool = False,
    notes: str | None = None,
) -> IptcDatasetPlan:
    return iptc_dataset(
        IPTC_ENVELOPE_RECORD,
        dataset_id,
        tag_name,
        raw_format,
        repeatable=repeatable,
        mandatory=mandatory,
        protected=protected,
        binary=binary,
        notes=notes,
    )


def application_dataset(
    dataset_id: int,
    tag_name: str,
    raw_format: str,
    *,
    repeatable: bool = False,
    mandatory: bool = False,
    protected: bool = False,
    binary: bool = False,
    notes: str | None = None,
) -> IptcDatasetPlan:
    return iptc_dataset(
        IPTC_APPLICATION_RECORD,
        dataset_id,
        tag_name,
        raw_format,
        repeatable=repeatable,
        mandatory=mandatory,
        protected=protected,
        binary=binary,
        notes=notes,
    )


def iptc_dataset(
    record_id: int,
    dataset_id: int,
    tag_name: str,
    raw_format: str,
    *,
    repeatable: bool = False,
    mandatory: bool = False,
    protected: bool = False,
    binary: bool = False,
    notes: str | None = None,
) -> IptcDatasetPlan:
    record_name = "EnvelopeRecord" if record_id == IPTC_ENVELOPE_RECORD else "ApplicationRecord"
    return IptcDatasetPlan(
        record_id=record_id,
        dataset_id=dataset_id,
        tag_name=tag_name,
        format=iptc_dataset_format(raw_format, binary=binary),
        repeatable=repeatable,
        mandatory=mandatory,
        protected=protected,
        evidence_id=(f"iptc.{record_name.lower()}.{dataset_id}.{_slug(tag_name)}"),
        notes=notes,
    )


def iptc_dataset_format(raw_format: str, *, binary: bool = False) -> IptcDatasetFormatPlan:
    int_match = _IPTC_INT_FORMAT_RE.match(raw_format)
    if int_match:
        byte_count = int(int_match.group("bits")) // 8
        return IptcDatasetFormatPlan(
            raw_format=raw_format,
            value_kind="int",
            min_bytes=byte_count,
            max_bytes=byte_count,
            fixed_width=True,
            binary=binary,
        )

    format_match = _IPTC_FORMAT_RE.match(raw_format)
    if format_match is None:
        raise ValueError(f"Unsupported IPTC format: {raw_format}")
    kind = format_match.group("kind")
    min_bytes = int(format_match.group("min"))
    max_text = format_match.group("max")
    max_bytes = min_bytes if max_text is None or max_text == "" else int(max_text)
    return IptcDatasetFormatPlan(
        raw_format=raw_format,
        value_kind=kind,  # type: ignore[arg-type]
        min_bytes=min_bytes,
        max_bytes=max_bytes,
        fixed_width=min_bytes == max_bytes,
        binary=binary or kind == "undef",
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    if not slug:
        return "evidence"
    return slug


def iptc_coded_character_set_plan() -> IptcCodedCharacterSetPlan:
    return IptcCodedCharacterSetPlan(
        dataset_key=(IPTC_ENVELOPE_RECORD, IPTC_CODED_CHARACTER_SET_DATASET),
        tag_name="CodedCharacterSet",
        raw_utf8_escape=IPTC_CODED_CHARACTER_SET_UTF8_ESCAPE,
        print_name="UTF8",
        protected_from_default_copy=True,
        affects_record_ids=(IPTC_APPLICATION_RECORD, 3),
        evidence_ids=(
            IPTC_CODED_CHARACTER_SET_EVIDENCE_ID,
            IPTC_CHARSET_TABLE_EVIDENCE_ID,
            IPTC_PRINT_CODED_CHARSET_EVIDENCE_ID,
            IPTC_PRINT_INV_CODED_CHARSET_EVIDENCE_ID,
            IPTC_HANDLE_CODED_CHARSET_EVIDENCE_ID,
            IPTC_TRANSLATE_CODED_STRING_EVIDENCE_ID,
            IPTC_PROCESS_CHARSET_EVIDENCE_ID,
            IPTC_FORMAT_WRITE_EVIDENCE_ID,
        ),
    )


def print_coded_character_set(raw_value: bytes) -> str:
    if raw_value == IPTC_CODED_CHARACTER_SET_UTF8_ESCAPE:
        return "UTF8"
    text = raw_value.decode("latin-1")
    pieces = []
    for char in text:
        if char == "\x1b":
            pieces.append("ESC")
        else:
            pieces.append(char)
    return " ".join(pieces).replace("ESC ", "ESC ", 1)


def inverse_print_coded_character_set(value: str) -> bytes:
    normalized = value.strip()
    if normalized.upper() in {"UTF8", "UTF-8"}:
        return IPTC_CODED_CHARACTER_SET_UTF8_ESCAPE
    if "ESC" not in normalized.upper():
        raise ValueError("Bad CodedCharacterSet syntax; use 'UTF8' or 'ESC X Y[, ...]'.")
    replaced = re.sub("ESC *", "\x1b", normalized, flags=re.IGNORECASE)
    replaced = replaced.replace(", \x1b", "\x1b").replace(",", "")
    replaced = replaced.replace(" ", "")
    return replaced.encode("latin-1")


def iptc_digest_responsibility_plan() -> IptcDigestResponsibilityPlan:
    return IptcDigestResponsibilityPlan(
        current_digest_tag="CurrentIPTCDigest",
        photoshop_digest_tag="Photoshop:IPTCDigest",
        standard_locations=(
            "JPEG-APP13-Photoshop-IPTC",
            "TIFF-IFD0-IPTC",
            "PSD-IPTC",
            "MIE-IPTC",
            "EPS-Photoshop-IPTC",
            "PS-Photoshop-IPTC",
            "EXV-APP13-Photoshop-IPTC",
        ),
        read_behavior=(
            "Read path reports CurrentIPTCDigest for the first standard IPTC "
            "directory and uses zero bytes if Digest::MD5 is unavailable."
        ),
        write_behavior=(
            "Write path updates digest data members only when Photoshop:IPTCDigest "
            "is explicitly set/deleted to 'new' or 'old'."
        ),
        evidence_ids=(
            IPTC_STANDARD_LOCATION_EVIDENCE_ID,
            IPTC_READ_DIGEST_EVIDENCE_ID,
            IPTC_WRITE_DIGEST_EVIDENCE_ID,
        ),
    )


def iptc_runtime_gates() -> tuple[IptcRuntimeGate, ...]:
    return (
        IptcRuntimeGate(
            gate_id="current_application_writer_subset",
            surface="write",
            status="ready",
            target="exifmodern.formats.iptc.write_plan.IPTC_APPLICATION_TAG_SPECS",
            requirement=(
                "Current writer may consume only datasets present in "
                "IPTC_APPLICATION_TAG_SPECS; broad database extraction must not "
                "silently make all ExifTool-writable datasets runtime-writable."
            ),
            evidence_ids=(IPTC_APPLICATION_TABLE_EVIDENCE_ID, IPTC_ENVELOPE_TABLE_EVIDENCE_ID),
        ),
        IptcRuntimeGate(
            gate_id="current_reader_subset",
            surface="read",
            status="ready",
            target="exifmodern.formats.iptc.reader",
            requirement=(
                "Current reader recognizes a subset of envelope/application tags "
                "using static dataset-number maps."
            ),
            evidence_ids=(IPTC_APPLICATION_TABLE_EVIDENCE_ID, IPTC_ENVELOPE_TABLE_EVIDENCE_ID),
        ),
        IptcRuntimeGate(
            gate_id="full_application_envelope_database_extraction",
            surface="database",
            status="planned",
            target="future generated IPTC dataset database",
            requirement=(
                "A full generated database must extract all literal dataset rows, "
                "formats, list flags, protected flags, binary flags, print/value "
                "conversions, and guessed-format notes from IPTC.pm."
            ),
            evidence_ids=(IPTC_APPLICATION_TABLE_EVIDENCE_ID, IPTC_ENVELOPE_TABLE_EVIDENCE_ID),
        ),
        IptcRuntimeGate(
            gate_id="coded_character_set_stateful_transcoding",
            surface="charset",
            status="planned",
            target="exifmodern.formats.iptc.reader and dataset_writer",
            requirement=(
                "CodedCharacterSet must be handled as record-state that affects "
                "later string datasets, not as an independent scalar write."
            ),
            evidence_ids=(
                IPTC_CODED_CHARACTER_SET_EVIDENCE_ID,
                IPTC_HANDLE_CODED_CHARSET_EVIDENCE_ID,
                IPTC_TRANSLATE_CODED_STRING_EVIDENCE_ID,
                IPTC_PROCESS_CHARSET_EVIDENCE_ID,
                IPTC_FORMAT_WRITE_EVIDENCE_ID,
            ),
        ),
        IptcRuntimeGate(
            gate_id="mandatory_record_version_insertion",
            surface="write",
            status="planned",
            target="exifmodern.formats.iptc.dataset_writer.with_required_record_versions",
            requirement=(
                "Existing mandatory insertion covers modern ApplicationRecord and "
                "NewsPhoto write steps; broad EnvelopeRecord writes must also add "
                "EnvelopeRecordVersion when creating record 1."
            ),
            evidence_ids=(IPTC_MANDATORY_WRITE_EVIDENCE_ID, IPTC_MANDATORY_INSERT_EVIDENCE_ID),
        ),
        IptcRuntimeGate(
            gate_id="standard_iptc_digest_update",
            surface="digest",
            status="planned",
            target="future Photoshop IPTCDigest integration",
            requirement=(
                "CurrentIPTCDigest is a read responsibility; NewIPTCDigest and "
                "OldIPTCDigest require explicit Photoshop:IPTCDigest requests and "
                "standard IPTC location checks."
            ),
            evidence_ids=(
                IPTC_STANDARD_LOCATION_EVIDENCE_ID,
                IPTC_READ_DIGEST_EVIDENCE_ID,
                IPTC_WRITE_DIGEST_EVIDENCE_ID,
            ),
        ),
        IptcRuntimeGate(
            gate_id="list_value_append_delete_ordering",
            surface="write",
            status="ready",
            target="exifmodern.formats.iptc.dataset_writer.apply_iptc_application_write_plan",
            requirement=(
                "List datasets are represented by repeated dataset entries, and "
                "current modern list mutation preserves source-relative ordering "
                "for the proven writer subset."
            ),
            evidence_ids=(IPTC_LIST_WRITE_EVIDENCE_ID, IPTC_WRITE_ORDER_EVIDENCE_ID),
        ),
    )
