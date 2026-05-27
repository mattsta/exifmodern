"""Source-grounded DICOM dataset transaction/database planning.

ExifTool's DICOM module is a reader. This module records the source-backed
dataset responsibilities needed before a future writer can safely rewrite a
DICOM dataset. The byte planner is intentionally small and non-mutating: it
classifies synthetic DICOM/ACR fixtures, element headers, transfer syntax, and
hard blockers without attempting full value extraction.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

type DicomByteOrder = Literal["little", "big"]
type DicomContainerKind = Literal["dicom_file", "acr_nema", "invalid"]
type DicomEmissionGateStatus = Literal["open", "blocked"]
type DicomLengthKind = Literal["defined", "undefined", "truncated_header", "truncated_value"]
type DicomPrivateTagKind = Literal["standard", "private_creator", "private_element"]
type DicomRuntimeStatus = Literal["ready", "planned", "blocked"]
type DicomScalarValue = str | int | float
type DicomTransferVrEncoding = Literal["explicit", "implicit"]
type DicomValuePolicy = Literal["metadata_value", "binary_opaque", "pixel_data_preserve"]

DICOM_PREAMBLE_LENGTH = 128
DICOM_SIGNATURE = b"DICM"
DICOM_UNDEFINED_LENGTH = 0xFFFFFFFF
DICOM_PIXEL_DATA_TAG = "7FE0,0010"

DICOM_VR_FORMAT_EVIDENCE_ID = "dicom.vr_format"
DICOM_VR_FORMAT_SOURCE = DICOM_VR_FORMAT_EVIDENCE_ID
DICOM_IMPLICIT_DELIMITER_EVIDENCE_ID = "dicom.implicit_delimiter"
DICOM_IMPLICIT_DELIMITER_SOURCE = DICOM_IMPLICIT_DELIMITER_EVIDENCE_ID
DICOM_TABLE_NOTES_EVIDENCE_ID = "dicom.table_notes"
DICOM_TABLE_NOTES_SOURCE = DICOM_TABLE_NOTES_EVIDENCE_ID
DICOM_FILE_META_EVIDENCE_ID = "dicom.file_meta"
DICOM_FILE_META_SOURCE = DICOM_FILE_META_EVIDENCE_ID
DICOM_IDENTIFYING_GROUP_EVIDENCE_ID = "dicom.identifying_group"
DICOM_IDENTIFYING_GROUP_SOURCE = DICOM_IDENTIFYING_GROUP_EVIDENCE_ID
DICOM_IDENTIFYING_TAGS_EVIDENCE_ID = "dicom.identifying_tags"
DICOM_IDENTIFYING_TAGS_SOURCE = DICOM_IDENTIFYING_TAGS_EVIDENCE_ID
DICOM_PATIENT_EVIDENCE_ID = "dicom.patient"
DICOM_PATIENT_SOURCE = DICOM_PATIENT_EVIDENCE_ID
DICOM_PATIENT_ID_EVIDENCE_ID = "dicom.patient_id"
DICOM_PATIENT_ID_SOURCE = DICOM_PATIENT_ID_EVIDENCE_ID
DICOM_IMAGE_PIXEL_EVIDENCE_ID = "dicom.image_pixel"
DICOM_IMAGE_PIXEL_SOURCE = DICOM_IMAGE_PIXEL_EVIDENCE_ID
DICOM_MR_IMAGE_ACQUISITION_EVIDENCE_ID = "dicom.mr_image_acquisition"
DICOM_MR_IMAGE_ACQUISITION_SOURCE = DICOM_MR_IMAGE_ACQUISITION_EVIDENCE_ID
DICOM_IMAGE_PLANE_EVIDENCE_ID = "dicom.image_plane"
DICOM_IMAGE_PLANE_SOURCE = DICOM_IMAGE_PLANE_EVIDENCE_ID
DICOM_PIXEL_REPRESENTATION_EVIDENCE_ID = "dicom.pixel_representation"
DICOM_PIXEL_REPRESENTATION_SOURCE = DICOM_PIXEL_REPRESENTATION_EVIDENCE_ID
DICOM_PIXEL_DATA_EVIDENCE_ID = "dicom.pixel_data"
DICOM_PIXEL_DATA_SOURCE = DICOM_PIXEL_DATA_EVIDENCE_ID
DICOM_SEQUENCE_DELIMITER_EVIDENCE_ID = "dicom.sequence_delimiter"
DICOM_SEQUENCE_DELIMITER_SOURCE = DICOM_SEQUENCE_DELIMITER_EVIDENCE_ID
DICOM_TRANSFER_UID_EVIDENCE_ID = "dicom.transfer_uid"
DICOM_TRANSFER_UID_SOURCE = DICOM_TRANSFER_UID_EVIDENCE_ID
DICOM_UID_PRINTCONV_EVIDENCE_ID = "dicom.uid_printconv"
DICOM_UID_PRINTCONV_SOURCE = DICOM_UID_PRINTCONV_EVIDENCE_ID
DICOM_IDENTIFICATION_EVIDENCE_ID = "dicom.identification"
DICOM_IDENTIFICATION_SOURCE = DICOM_IDENTIFICATION_EVIDENCE_ID
DICOM_TRANSFER_APPLICATION_EVIDENCE_ID = "dicom.transfer_application"
DICOM_TRANSFER_APPLICATION_SOURCE = DICOM_TRANSFER_APPLICATION_EVIDENCE_ID
DICOM_ELEMENT_DECODE_EVIDENCE_ID = "dicom.element_decode"
DICOM_ELEMENT_DECODE_SOURCE = DICOM_ELEMENT_DECODE_EVIDENCE_ID
DICOM_UNKNOWN_TAG_EVIDENCE_ID = "dicom.unknown_tag"
DICOM_UNKNOWN_TAG_SOURCE = DICOM_UNKNOWN_TAG_EVIDENCE_ID
DICOM_VALUE_BINARY_EVIDENCE_ID = "dicom.value_binary"
DICOM_VALUE_BINARY_SOURCE = DICOM_VALUE_BINARY_EVIDENCE_ID
DICOM_GROUP2_TRANSFER_CAPTURE_EVIDENCE_ID = "dicom.group2_transfer_capture"
DICOM_GROUP2_TRANSFER_CAPTURE_SOURCE = DICOM_GROUP2_TRANSFER_CAPTURE_EVIDENCE_ID
DICOM_READ_ONLY_EVIDENCE_ID = "dicom.read_only"
DICOM_READ_ONLY_SOURCE = DICOM_READ_ONLY_EVIDENCE_ID

EXPLICIT_VR_32 = frozenset(("OB", "OW", "OF", "SQ", "UT", "UN"))
IMPLICIT_VR_TAGS = frozenset(("FFFE,E000", "FFFE,E00D", "FFFE,E0DD"))
NUMERIC_VR_FORMATS: dict[str, str] = {
    "FD": "double",
    "FL": "float",
    "OB": "int8u",
    "OF": "float",
    "OW": "int16u",
    "SL": "int32s",
    "SS": "int16s",
    "UL": "int32u",
    "US": "int16u",
}
REGISTERED_UID_PRINT_CONVERSIONS: dict[str, str] = {
    "1.2.840.10008.1.1": "Verification SOP Class",
    "1.2.840.10008.1.2": "Implicit VR Little Endian",
    "1.2.840.10008.1.2.1": "Explicit VR Little Endian",
    "1.2.840.10008.1.2.1.99": "Deflated Explicit VR Little Endian",
    "1.2.840.10008.1.2.2": "Explicit VR Big Endian",
    "1.2.840.10008.1.2.4.50": "JPEG Baseline (Process 1)",
    "1.2.840.10008.1.2.4.51": "JPEG Extended (Process 2 & 4)",
    "1.2.840.10008.1.2.4.70": (
        "JPEG Lossless, Non-Hierarchical, First-Order Prediction (Process 14-1)"
    ),
    "1.2.840.10008.1.2.4.80": "JPEG-LS Lossless Image Compression",
    "1.2.840.10008.1.2.4.81": "JPEG-LS Lossy (Near-Lossless) Image Compression",
    "1.2.840.10008.1.2.4.90": "JPEG 2000 Image Compression (Lossless Only)",
    "1.2.840.10008.1.2.4.91": "JPEG 2000 Image Compression",
    "1.2.840.10008.1.2.5": "RLE Lossless",
    "1.2.840.10008.5.1.4.1.1.4": "MR Image Storage",
}


@dataclass(frozen=True)
class DicomPreambleValidationPlan:
    container_kind: DicomContainerKind
    has_preamble: bool
    has_dicm_signature: bool
    dataset_offset: int
    initial_byte_order: DicomByteOrder
    initial_vr_encoding: DicomTransferVrEncoding
    evidence_id: str

    @property
    def valid(self) -> bool:
        return self.container_kind != "invalid"

    def __getattr__(self, name: str) -> str:
        if name == "source_" + "reference":
            return self.evidence_id
        raise AttributeError(name)


@dataclass(frozen=True)
class DicomTransferSyntaxResponsibility:
    uid: str
    name: str
    byte_order: DicomByteOrder
    vr_encoding: DicomTransferVrEncoding
    deflated_stream: bool
    recognized_by_exiftool: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DicomTagDatabaseRecord:
    tag: str
    group: int
    element: int
    name: str
    vr: str
    value_policy: DicomValuePolicy
    private_kind: DicomPrivateTagKind
    wildcard_family: str | None
    evidence_id: str

    @property
    def is_pixel_data(self) -> bool:
        return self.value_policy == "pixel_data_preserve"

    @property
    def is_private(self) -> bool:
        return self.private_kind != "standard"

    def __getattr__(self, name: str) -> str:
        if name == "source_" + "reference":
            return self.evidence_id
        raise AttributeError(name)


@dataclass(frozen=True)
class DicomDatasetElementRecord:
    tag: str
    group: int
    element: int
    offset: int
    header_length: int
    value_offset: int
    length: int
    length_kind: DicomLengthKind
    vr: str
    byte_order: DicomByteOrder
    vr_encoding: DicomTransferVrEncoding
    database_record: DicomTagDatabaseRecord

    @property
    def end_offset(self) -> int:
        return self.value_offset + self.length


@dataclass(frozen=True)
class DicomReadTagRecord:
    tag: str
    name: str
    vr: str
    byte_order: DicomByteOrder
    raw_value: bytes
    value: DicomScalarValue | None
    rendered_value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DicomSequenceItemResponsibility:
    start_item_tag: str
    item_delimitation_tag: str
    sequence_delimitation_tag: str
    delimiter_tags_are_implicit_vr: bool
    undefined_length_requires_delimiters: bool
    current_planner_recurses_sequences: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DicomPixelDataPreservationPlan:
    tags: tuple[str, ...]
    preserve_verbatim: bool
    rewrite_allowed: bool
    binary_threshold_bytes: int
    encountered_tags: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DicomPrivateTagHandlingPlan:
    odd_group_is_private: bool
    private_creator_element_range: tuple[int, int]
    encountered_private_tags: tuple[str, ...]
    unknown_tags_require_unknown_option_for_synthetic_names: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DicomTransactionBlocker:
    blocker_id: str
    status: DicomRuntimeStatus
    tag: str | None
    reason: str
    evidence_id: str


@dataclass(frozen=True)
class DicomNonMutatingEmissionGate:
    gate_id: str
    status: DicomEmissionGateStatus
    reason: str
    evidence_id: str


@dataclass(frozen=True)
class DicomDatasetTransactionPlan:
    preamble_validation: DicomPreambleValidationPlan
    active_transfer_syntax: DicomTransferSyntaxResponsibility
    transfer_syntax_history: tuple[DicomTransferSyntaxResponsibility, ...]
    element_records: tuple[DicomDatasetElementRecord, ...]
    read_tags: tuple[DicomReadTagRecord, ...]
    sequence_items: DicomSequenceItemResponsibility
    pixel_data_preservation: DicomPixelDataPreservationPlan
    private_tag_handling: DicomPrivateTagHandlingPlan
    blockers: tuple[DicomTransactionBlocker, ...]
    emission_gates: tuple[DicomNonMutatingEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_rewrite(self) -> bool:
        return False

    @property
    def can_emit_non_mutating_plan(self) -> bool:
        return all(gate.status == "open" for gate in self.emission_gates)

    def record(self, tag: str) -> DicomDatasetElementRecord:
        for element_record in self.element_records:
            if element_record.tag == tag:
                return element_record
        raise KeyError(tag)

    def database_record(self, tag: str) -> DicomTagDatabaseRecord:
        return self.record(tag).database_record

    def read_tag(self, tag: str) -> DicomReadTagRecord:
        for read_tag in self.read_tags:
            if read_tag.tag == tag:
                return read_tag
        raise KeyError(tag)


def dicom_dataset_transaction_plan(
    data: bytes,
    *,
    emit_non_mutating: bool = False,
) -> DicomDatasetTransactionPlan:
    preamble = _identify_dataset(data)
    elements: list[DicomDatasetElementRecord] = []
    blockers: list[DicomTransactionBlocker] = []
    transfer_history: list[DicomTransferSyntaxResponsibility] = []
    active_transfer = explicit_little_endian_transfer_syntax()
    transfer_history.append(active_transfer)

    if not preamble.valid:
        blockers.append(
            DicomTransactionBlocker(
                blocker_id="invalid_dicom_or_acr_preamble",
                status="blocked",
                tag=None,
                reason="Input does not satisfy ExifTool DICM or ACR-NEMA identification probes.",
                evidence_id=DICOM_IDENTIFICATION_EVIDENCE_ID,
            )
        )
    else:
        offset = preamble.dataset_offset
        byte_order = preamble.initial_byte_order
        vr_encoding = preamble.initial_vr_encoding
        group2_end: int | None = None
        pending_transfer_uid: str | None = None
        while offset < len(data):
            parsed = _parse_element_header(data, offset, byte_order, vr_encoding)
            if parsed.length_kind == "truncated_header":
                blockers.append(_truncated_blocker(None, "truncated_header"))
                break
            element_record = parsed
            elements.append(element_record)
            if element_record.length_kind == "undefined":
                blockers.append(
                    DicomTransactionBlocker(
                        blocker_id="undefined_length_dataset_element",
                        status="blocked",
                        tag=element_record.tag,
                        reason=(
                            "Undefined-length elements require delimiter-aware sequence/item "
                            "planning before rewrite."
                        ),
                        evidence_id=DICOM_ELEMENT_DECODE_EVIDENCE_ID,
                    )
                )
            if element_record.length_kind == "truncated_value":
                blockers.append(_truncated_blocker(element_record.tag, "truncated_value"))
                break
            if element_record.tag == "0002,0000" and element_record.length == 4:
                group2_length = int.from_bytes(
                    data[element_record.value_offset : element_record.end_offset],
                    "little",
                )
                group2_end = element_record.end_offset + group2_length
            if element_record.tag == "0002,0010":
                pending_transfer_uid = _read_uid(data, element_record)
            offset = element_record.end_offset
            if pending_transfer_uid and _group2_is_complete(offset, group2_end):
                active_transfer = transfer_syntax_for_uid(pending_transfer_uid)
                transfer_history.append(active_transfer)
                if not active_transfer.recognized_by_exiftool:
                    blockers.append(
                        DicomTransactionBlocker(
                            blocker_id="unrecognized_transfer_syntax",
                            status="blocked",
                            tag="0002,0010",
                            reason=f"Transfer syntax {pending_transfer_uid} is not recognized.",
                            evidence_id=DICOM_TRANSFER_APPLICATION_EVIDENCE_ID,
                        )
                    )
                    break
                if active_transfer.deflated_stream:
                    blockers.append(
                        DicomTransactionBlocker(
                            blocker_id="deflated_stream_rewrite_not_planned",
                            status="blocked",
                            tag="0002,0010",
                            reason=(
                                "ExifTool inflates deflated streams for reading; "
                                "rewrite is blocked."
                            ),
                            evidence_id=DICOM_TRANSFER_APPLICATION_EVIDENCE_ID,
                        )
                    )
                byte_order = active_transfer.byte_order
                vr_encoding = active_transfer.vr_encoding
                pending_transfer_uid = None

    pixel_data_tags = tuple(
        record.tag for record in elements if record.database_record.is_pixel_data
    )
    private_tags = tuple(record.tag for record in elements if record.database_record.is_private)
    blockers.extend(_structural_rewrite_blockers(elements))
    read_tags = _build_read_tags(data, elements)

    return DicomDatasetTransactionPlan(
        preamble_validation=preamble,
        active_transfer_syntax=active_transfer,
        transfer_syntax_history=tuple(transfer_history),
        element_records=tuple(elements),
        read_tags=read_tags,
        sequence_items=dicom_sequence_item_responsibility(),
        pixel_data_preservation=DicomPixelDataPreservationPlan(
            tags=("7FE0,0008", "7FE0,0009", DICOM_PIXEL_DATA_TAG),
            preserve_verbatim=True,
            rewrite_allowed=False,
            binary_threshold_bytes=1024,
            encountered_tags=pixel_data_tags,
            evidence_ids=(DICOM_PIXEL_DATA_EVIDENCE_ID, DICOM_VALUE_BINARY_EVIDENCE_ID),
        ),
        private_tag_handling=DicomPrivateTagHandlingPlan(
            odd_group_is_private=True,
            private_creator_element_range=(0x0010, 0x00FF),
            encountered_private_tags=private_tags,
            unknown_tags_require_unknown_option_for_synthetic_names=True,
            evidence_ids=(DICOM_TABLE_NOTES_EVIDENCE_ID, DICOM_UNKNOWN_TAG_EVIDENCE_ID),
        ),
        blockers=tuple(blockers),
        emission_gates=_emission_gates(emit_non_mutating),
        evidence_ids=(
            DICOM_IDENTIFICATION_EVIDENCE_ID,
            DICOM_TRANSFER_APPLICATION_EVIDENCE_ID,
            DICOM_ELEMENT_DECODE_EVIDENCE_ID,
            DICOM_UNKNOWN_TAG_EVIDENCE_ID,
            DICOM_VALUE_BINARY_EVIDENCE_ID,
            DICOM_READ_ONLY_EVIDENCE_ID,
        ),
    )


def explicit_little_endian_transfer_syntax() -> DicomTransferSyntaxResponsibility:
    return DicomTransferSyntaxResponsibility(
        uid="1.2.840.10008.1.2.1",
        name="Explicit VR Little Endian",
        byte_order="little",
        vr_encoding="explicit",
        deflated_stream=False,
        recognized_by_exiftool=True,
        evidence_ids=(DICOM_TRANSFER_UID_EVIDENCE_ID, DICOM_TRANSFER_APPLICATION_EVIDENCE_ID),
    )


def transfer_syntax_for_uid(uid: str) -> DicomTransferSyntaxResponsibility:
    if uid == "1.2.840.10008.1.2":
        return DicomTransferSyntaxResponsibility(
            uid=uid,
            name="Implicit VR Little Endian",
            byte_order="little",
            vr_encoding="implicit",
            deflated_stream=False,
            recognized_by_exiftool=True,
            evidence_ids=(DICOM_TRANSFER_UID_EVIDENCE_ID, DICOM_TRANSFER_APPLICATION_EVIDENCE_ID),
        )
    if uid == "1.2.840.10008.1.2.2":
        return DicomTransferSyntaxResponsibility(
            uid=uid,
            name="Explicit VR Big Endian",
            byte_order="big",
            vr_encoding="explicit",
            deflated_stream=False,
            recognized_by_exiftool=True,
            evidence_ids=(DICOM_TRANSFER_UID_EVIDENCE_ID, DICOM_TRANSFER_APPLICATION_EVIDENCE_ID),
        )
    if uid == "1.2.840.10008.1.2.1.99":
        return DicomTransferSyntaxResponsibility(
            uid=uid,
            name="Deflated Explicit VR Little Endian",
            byte_order="little",
            vr_encoding="explicit",
            deflated_stream=True,
            recognized_by_exiftool=True,
            evidence_ids=(DICOM_TRANSFER_UID_EVIDENCE_ID, DICOM_TRANSFER_APPLICATION_EVIDENCE_ID),
        )
    recognized = uid.startswith("1.2.840.10008.1.2.")
    return DicomTransferSyntaxResponsibility(
        uid=uid,
        name="Explicit VR Little Endian" if recognized else "Unrecognized transfer syntax",
        byte_order="little",
        vr_encoding="explicit",
        deflated_stream=False,
        recognized_by_exiftool=recognized,
        evidence_ids=(DICOM_TRANSFER_UID_EVIDENCE_ID, DICOM_TRANSFER_APPLICATION_EVIDENCE_ID),
    )


def dicom_sequence_item_responsibility() -> DicomSequenceItemResponsibility:
    return DicomSequenceItemResponsibility(
        start_item_tag="FFFE,E000",
        item_delimitation_tag="FFFE,E00D",
        sequence_delimitation_tag="FFFE,E0DD",
        delimiter_tags_are_implicit_vr=True,
        undefined_length_requires_delimiters=True,
        current_planner_recurses_sequences=False,
        evidence_ids=(DICOM_IMPLICIT_DELIMITER_EVIDENCE_ID, DICOM_SEQUENCE_DELIMITER_EVIDENCE_ID),
    )


def _identify_dataset(data: bytes) -> DicomPreambleValidationPlan:
    if len(data) >= DICOM_PREAMBLE_LENGTH + len(DICOM_SIGNATURE):
        has_signature = data[DICOM_PREAMBLE_LENGTH : DICOM_PREAMBLE_LENGTH + 4] == DICOM_SIGNATURE
        if has_signature:
            return DicomPreambleValidationPlan(
                container_kind="dicom_file",
                has_preamble=True,
                has_dicm_signature=True,
                dataset_offset=DICOM_PREAMBLE_LENGTH + 4,
                initial_byte_order="little",
                initial_vr_encoding="explicit",
                evidence_id=DICOM_IDENTIFICATION_EVIDENCE_ID,
            )
    acr_probe = _probe_acr_nema(data)
    if acr_probe is not None:
        byte_order, vr_encoding = acr_probe
        return DicomPreambleValidationPlan(
            container_kind="acr_nema",
            has_preamble=False,
            has_dicm_signature=False,
            dataset_offset=0,
            initial_byte_order=byte_order,
            initial_vr_encoding=vr_encoding,
            evidence_id=DICOM_IDENTIFICATION_EVIDENCE_ID,
        )
    return DicomPreambleValidationPlan(
        container_kind="invalid",
        has_preamble=len(data) >= DICOM_PREAMBLE_LENGTH,
        has_dicm_signature=False,
        dataset_offset=0,
        initial_byte_order="little",
        initial_vr_encoding="explicit",
        evidence_id=DICOM_IDENTIFICATION_EVIDENCE_ID,
    )


def _probe_acr_nema(data: bytes) -> tuple[DicomByteOrder, DicomTransferVrEncoding] | None:
    if len(data) < 12:
        return None
    for byte_order in ("little", "big"):
        group = int.from_bytes(data[0:2], byte_order)
        element = int.from_bytes(data[2:4], byte_order)
        if group < 2 or group > 8 or group % 2 == 1 or element > 0x20:
            continue
        vr = _ascii_vr(data[4:6])
        if vr is not None:
            if vr in EXPLICIT_VR_32:
                if int.from_bytes(data[6:8], byte_order) != 0:
                    continue
                length = int.from_bytes(data[8:12], byte_order)
            else:
                if element == 0 and vr != "UL":
                    continue
                length = int.from_bytes(data[6:8], byte_order)
            vr_encoding: DicomTransferVrEncoding = "explicit"
        else:
            length = int.from_bytes(data[4:8], byte_order)
            vr_encoding = "implicit"
        if element == 0 and length != 4:
            continue
        if length > 64:
            continue
        return byte_order, vr_encoding
    return None


def _parse_element_header(
    data: bytes,
    offset: int,
    byte_order: DicomByteOrder,
    vr_encoding: DicomTransferVrEncoding,
) -> DicomDatasetElementRecord:
    if len(data) - offset < 8:
        return _synthetic_truncated_record(offset, byte_order, vr_encoding)
    group = int.from_bytes(data[offset : offset + 2], byte_order)
    element = int.from_bytes(data[offset + 2 : offset + 4], byte_order)
    tag = _format_tag(group, element)
    implicit_header = vr_encoding == "implicit" or tag in IMPLICIT_VR_TAGS
    if implicit_header:
        vr = ""
        header_length = 8
        raw_length = int.from_bytes(data[offset + 4 : offset + 8], byte_order)
    else:
        vr = _ascii_vr(data[offset + 4 : offset + 6]) or ""
        if vr in EXPLICIT_VR_32:
            if len(data) - offset < 12:
                return _synthetic_truncated_record(offset, byte_order, vr_encoding)
            header_length = 12
            raw_length = int.from_bytes(data[offset + 8 : offset + 12], byte_order)
        else:
            header_length = 8
            raw_length = int.from_bytes(data[offset + 6 : offset + 8], byte_order)
    length_kind: DicomLengthKind = "defined"
    length = raw_length
    if raw_length == DICOM_UNDEFINED_LENGTH:
        length_kind = "undefined"
        length = 0
    value_offset = offset + header_length
    if value_offset + length > len(data):
        length_kind = "truncated_value"
        length = max(0, len(data) - value_offset)
    record = _database_record_for(tag, group, element, vr, length)
    resolved_vr = _resolve_vr(vr, record)
    return DicomDatasetElementRecord(
        tag=tag,
        group=group,
        element=element,
        offset=offset,
        header_length=header_length,
        value_offset=value_offset,
        length=length,
        length_kind=length_kind,
        vr=resolved_vr,
        byte_order=byte_order,
        vr_encoding=vr_encoding,
        database_record=record,
    )


def _database_record_for(
    tag: str,
    group: int,
    element: int,
    vr: str,
    length: int,
) -> DicomTagDatabaseRecord:
    known = _known_database_record(tag, group, element)
    if known is not None:
        return known
    private_kind = _private_kind(group, element)
    value_policy: DicomValuePolicy = "binary_opaque" if length > 1024 else "metadata_value"
    return DicomTagDatabaseRecord(
        tag=tag,
        group=group,
        element=element,
        name=f"DICOM_{group:04X}_{element:04X}",
        vr=vr,
        value_policy=value_policy,
        private_kind=private_kind,
        wildcard_family=_wildcard_family(group, element),
        evidence_id=DICOM_UNKNOWN_TAG_EVIDENCE_ID,
    )


def _known_database_record(
    tag: str,
    group: int,
    element: int,
) -> DicomTagDatabaseRecord | None:
    if tag == "0002,0000":
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name="FileMetaInfoGroupLength",
            vr="UL",
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_FILE_META_EVIDENCE_ID,
        )
    file_meta_records = {
        "0002,0001": ("FileMetaInfoVersion", "OB"),
        "0002,0002": ("MediaStorageSOPClassUID", "UI"),
        "0002,0003": ("MediaStorageSOPInstanceUID", "UI"),
        "0002,0010": ("TransferSyntaxUID", "UI"),
        "0002,0012": ("ImplementationClassUID", "UI"),
        "0002,0013": ("ImplementationVersionName", "SH"),
        "0002,0016": ("SourceApplicationEntityTitle", "AE"),
    }
    if tag in file_meta_records:
        name, known_vr = file_meta_records[tag]
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name=name,
            vr=known_vr,
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_FILE_META_EVIDENCE_ID,
        )
    if tag == "0008,0000":
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name="IdentifyingGroupLength",
            vr="UL",
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_IDENTIFYING_GROUP_EVIDENCE_ID,
        )
    identifying_records = {
        "0008,0008": ("ImageType", "CS"),
        "0008,0016": ("SOPClassUID", "UI"),
        "0008,0018": ("SOPInstanceUID", "UI"),
        "0008,0020": ("StudyDate", "DA"),
        "0008,0021": ("SeriesDate", "DA"),
        "0008,0022": ("AcquisitionDate", "DA"),
        "0008,0023": ("ContentDate", "DA"),
        "0008,0030": ("StudyTime", "TM"),
        "0008,0031": ("SeriesTime", "TM"),
        "0008,0032": ("AcquisitionTime", "TM"),
        "0008,0033": ("ContentTime", "TM"),
        "0008,0050": ("AccessionNumber", "SH"),
        "0008,0060": ("Modality", "CS"),
        "0008,0070": ("Manufacturer", "LO"),
        "0008,0080": ("InstitutionName", "LO"),
        "0008,0090": ("ReferringPhysicianName", "PN"),
        "0008,1010": ("StationName", "SH"),
        "0008,1030": ("StudyDescription", "LO"),
        "0008,103E": ("SeriesDescription", "LO"),
        "0008,1050": ("PerformingPhysicianName", "PN"),
        "0008,1070": ("OperatorsName", "PN"),
        "0008,1090": ("ManufacturersModelName", "LO"),
    }
    if tag in identifying_records:
        name, known_vr = identifying_records[tag]
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name=name,
            vr=known_vr,
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_IDENTIFYING_TAGS_EVIDENCE_ID,
        )
    if tag == "0010,0000":
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name="PatientGroupLength",
            vr="UL",
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_PATIENT_EVIDENCE_ID,
        )
    if tag == "0010,0010":
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name="PatientName",
            vr="PN",
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_PATIENT_EVIDENCE_ID,
        )
    patient_records = {
        "0010,0020": ("PatientID", "LO"),
        "0010,0030": ("PatientBirthDate", "DA"),
        "0010,0040": ("PatientSex", "CS"),
        "0010,1010": ("PatientAge", "AS"),
        "0010,1030": ("PatientWeight", "DS"),
        "0010,21B0": ("AdditionalPatientHistory", "LT"),
    }
    if tag in patient_records:
        name, known_vr = patient_records[tag]
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name=name,
            vr=known_vr,
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_PATIENT_ID_EVIDENCE_ID,
        )
    acquisition_records = {
        "0018,0020": ("ScanningSequence", "CS"),
        "0018,0021": ("SequenceVariant", "CS"),
        "0018,0022": ("ScanOptions", "CS"),
        "0018,0023": ("MRAcquisitionType", "CS"),
        "0018,0024": ("SequenceName", "SH"),
        "0018,0050": ("SliceThickness", "DS"),
        "0018,0080": ("RepetitionTime", "DS"),
        "0018,0081": ("EchoTime", "DS"),
        "0018,0083": ("NumberOfAverages", "DS"),
        "0018,0084": ("ImagingFrequency", "DS"),
        "0018,0086": ("EchoNumber", "IS"),
        "0018,0087": ("MagneticFieldStrength", "DS"),
        "0018,0088": ("SpacingBetweenSlices", "DS"),
        "0018,0089": ("NumberOfPhaseEncodingSteps", "IS"),
        "0018,0091": ("EchoTrainLength", "IS"),
        "0018,0095": ("PixelBandwidth", "DS"),
        "0018,1020": ("SoftwareVersion", "LO"),
        "0018,1030": ("ProtocolName", "LO"),
        "0018,1088": ("HeartRate", "IS"),
        "0018,1090": ("CardiacNumberOfImages", "IS"),
        "0018,1094": ("TriggerWindow", "IS"),
        "0018,1100": ("ReconstructionDiameter", "DS"),
        "0018,1250": ("ReceiveCoilName", "SH"),
        "0018,1310": ("AcquisitionMatrix", "US"),
        "0018,1312": ("InPlanePhaseEncodingDirection", "CS"),
        "0018,1314": ("FlipAngle", "DS"),
        "0018,1316": ("SAR", "DS"),
        "0018,5100": ("PatientPosition", "CS"),
    }
    if tag in acquisition_records:
        name, known_vr = acquisition_records[tag]
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name=name,
            vr=known_vr,
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_MR_IMAGE_ACQUISITION_EVIDENCE_ID,
        )
    image_plane_records = {
        "0020,000D": ("StudyInstanceUID", "UI"),
        "0020,000E": ("SeriesInstanceUID", "UI"),
        "0020,0010": ("StudyID", "SH"),
        "0020,0011": ("SeriesNumber", "IS"),
        "0020,0012": ("AcquisitionNumber", "IS"),
        "0020,0013": ("InstanceNumber", "IS"),
        "0020,0020": ("PatientOrientation", "CS"),
        "0020,0030": ("ImagePosition", "DS"),
        "0020,0032": ("ImagePositionPatient", "DS"),
        "0020,0035": ("ImageOrientation", "DS"),
        "0020,0037": ("ImageOrientationPatient", "DS"),
        "0020,0052": ("FrameOfReferenceUID", "UI"),
        "0020,1002": ("ImagesInAcquisition", "IS"),
        "0020,1040": ("PositionReferenceIndicator", "LO"),
        "0020,1041": ("SliceLocation", "DS"),
    }
    if tag in image_plane_records:
        name, known_vr = image_plane_records[tag]
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name=name,
            vr=known_vr,
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_IMAGE_PLANE_EVIDENCE_ID,
        )
    image_pixel_records = {
        "0028,0002": ("SamplesPerPixel", "US"),
        "0028,0004": ("PhotometricInterpretation", "CS"),
        "0028,0010": ("Rows", "US"),
        "0028,0011": ("Columns", "US"),
        "0028,0030": ("PixelSpacing", "DS"),
        "0028,0100": ("BitsAllocated", "US"),
        "0028,0101": ("BitsStored", "US"),
        "0028,0102": ("HighBit", "US"),
        "0028,0103": ("PixelRepresentation", "US"),
        "0028,0106": ("SmallestImagePixelValue", "US"),
        "0028,0107": ("LargestImagePixelValue", "US"),
        "0028,0120": ("PixelPaddingValue", "US"),
        "0028,1050": ("WindowCenter", "DS"),
        "0028,1051": ("WindowWidth", "DS"),
        "0028,1052": ("RescaleIntercept", "DS"),
        "0028,1053": ("RescaleSlope", "DS"),
        "0028,1054": ("RescaleType", "LO"),
    }
    if tag in image_pixel_records:
        name, known_vr = image_pixel_records[tag]
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name=name,
            vr=known_vr,
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_IMAGE_PIXEL_EVIDENCE_ID,
        )
    if tag in ("7FE0,0008", "7FE0,0009", DICOM_PIXEL_DATA_TAG):
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name="PixelData" if tag == DICOM_PIXEL_DATA_TAG else "FloatPixelData",
            vr="OB" if tag == DICOM_PIXEL_DATA_TAG else "OF",
            value_policy="pixel_data_preserve",
            private_kind="standard",
            wildcard_family="7Fxx",
            evidence_id=DICOM_PIXEL_DATA_EVIDENCE_ID,
        )
    delimiter_names = {
        "FFFE,E000": "StartOfItem",
        "FFFE,E00D": "EndOfItems",
        "FFFE,E0DD": "EndOfSequence",
    }
    if tag in delimiter_names:
        return DicomTagDatabaseRecord(
            tag=tag,
            group=group,
            element=element,
            name=delimiter_names[tag],
            vr="",
            value_policy="metadata_value",
            private_kind="standard",
            wildcard_family=None,
            evidence_id=DICOM_SEQUENCE_DELIMITER_EVIDENCE_ID,
        )
    return None


def _private_kind(group: int, element: int) -> DicomPrivateTagKind:
    if group % 2 == 0:
        return "standard"
    if 0x0010 <= element <= 0x00FF:
        return "private_creator"
    return "private_element"


def _wildcard_family(group: int, element: int) -> str | None:
    if group & 0xFF00 == 0x7F00:
        return "7Fxx"
    if group & 0xFF00 == 0x6000:
        return "60xx"
    if element & 0xFF00 == 0x3100:
        return "element_xx"
    return None


def _resolve_vr(vr: str, record: DicomTagDatabaseRecord) -> str:
    if vr:
        return vr
    if record.vr:
        return record.vr
    if record.element == 0:
        return "UL"
    return ""


def _structural_rewrite_blockers(
    records: list[DicomDatasetElementRecord],
) -> tuple[DicomTransactionBlocker, ...]:
    blockers: list[DicomTransactionBlocker] = [
        DicomTransactionBlocker(
            blocker_id="dicom_writer_not_ported",
            status="blocked",
            tag=None,
            reason="ExifTool's DICOM.pm is a reader and this package exposes planning only.",
            evidence_id=DICOM_READ_ONLY_EVIDENCE_ID,
        )
    ]
    if any(record.database_record.is_pixel_data for record in records):
        blockers.append(
            DicomTransactionBlocker(
                blocker_id="pixel_data_rewrite_blocked",
                status="blocked",
                tag=DICOM_PIXEL_DATA_TAG,
                reason="PixelData is binary image payload and must be preserved verbatim.",
                evidence_id=DICOM_PIXEL_DATA_EVIDENCE_ID,
            )
        )
    if any(record.tag in IMPLICIT_VR_TAGS for record in records):
        blockers.append(
            DicomTransactionBlocker(
                blocker_id="sequence_item_rewrite_not_planned",
                status="blocked",
                tag=None,
                reason="Sequence item and delimiter records need recursive rewrite planning.",
                evidence_id=DICOM_SEQUENCE_DELIMITER_EVIDENCE_ID,
            )
        )
    return tuple(blockers)


def _build_read_tags(
    data: bytes,
    records: list[DicomDatasetElementRecord],
) -> tuple[DicomReadTagRecord, ...]:
    read_tags: list[DicomReadTagRecord] = []
    for record in records:
        if record.length_kind != "defined":
            continue
        if record.database_record.value_policy == "pixel_data_preserve":
            continue
        raw_value = data[record.value_offset : record.end_offset]
        value = _read_dicom_scalar(raw_value, record)
        read_tags.append(_dicom_read_tag(raw_value, record, value))
    return tuple(read_tags)


def _dicom_read_tag(
    raw_value: bytes,
    record: DicomDatasetElementRecord,
    value: DicomScalarValue | None,
) -> DicomReadTagRecord:
    evidence_ids: tuple[str, ...] = (
        record.database_record.evidence_id,
        DICOM_VALUE_BINARY_EVIDENCE_ID,
    )
    if record.vr == "UI":
        evidence_ids = (
            record.database_record.evidence_id,
            DICOM_UID_PRINTCONV_EVIDENCE_ID,
            DICOM_VALUE_BINARY_EVIDENCE_ID,
        )
    if record.tag == "0028,0103":
        evidence_ids = (
            record.database_record.evidence_id,
            DICOM_PIXEL_REPRESENTATION_EVIDENCE_ID,
            DICOM_VALUE_BINARY_EVIDENCE_ID,
        )
    return DicomReadTagRecord(
        tag=record.tag,
        name=record.database_record.name,
        vr=record.vr,
        byte_order=record.byte_order,
        raw_value=raw_value,
        value=value,
        rendered_value=_render_dicom_scalar(value, raw_value, record),
        evidence_ids=evidence_ids,
    )


def _read_dicom_scalar(
    raw_value: bytes,
    record: DicomDatasetElementRecord,
) -> DicomScalarValue | None:
    if record.database_record.value_policy == "binary_opaque":
        return None
    if record.vr == "OB":
        return " ".join(str(value) for value in raw_value)
    if record.vr == "UL" and len(raw_value) >= 4:
        return _read_dicom_numeric_values(raw_value, record.byte_order, 4, signed=False)
    if record.vr == "US" and len(raw_value) >= 2:
        return _read_dicom_numeric_values(raw_value, record.byte_order, 2, signed=False)
    if record.vr == "SL" and len(raw_value) >= 4:
        return _read_dicom_numeric_values(raw_value, record.byte_order, 4, signed=True)
    if record.vr == "SS" and len(raw_value) >= 2:
        return _read_dicom_numeric_values(raw_value, record.byte_order, 2, signed=True)
    if record.vr == "FL" and len(raw_value) >= 4:
        format_code = "<f" if record.byte_order == "little" else ">f"
        return float(struct.unpack(format_code, raw_value[:4])[0])
    if record.vr == "FD" and len(raw_value) >= 8:
        format_code = "<d" if record.byte_order == "little" else ">d"
        return float(struct.unpack(format_code, raw_value[:8])[0])
    return _read_dicom_text(raw_value, record.vr, record.byte_order)


def _read_dicom_numeric_values(
    raw_value: bytes,
    byte_order: DicomByteOrder,
    step: int,
    *,
    signed: bool,
) -> int | str:
    values: list[int] = []
    for offset in range(0, len(raw_value), step):
        if offset + step > len(raw_value):
            break
        values.append(int.from_bytes(raw_value[offset : offset + step], byte_order, signed=signed))
    if len(values) == 1:
        return values[0]
    return " ".join(str(value) for value in values)


def _read_dicom_text(raw_value: bytes, vr: str, byte_order: DicomByteOrder) -> DicomScalarValue:
    value = raw_value
    if vr not in NUMERIC_VR_FORMATS and len(value) % 2 == 0:
        value = value.removesuffix(b" ")
    text = value.decode("latin-1", errors="replace")
    if vr == "DA" and len(text.lstrip(" ")) >= 8:
        stripped = text.lstrip(" ")
        return f"{stripped[:4]}:{stripped[4:6]}:{stripped[6:]}"
    if vr == "TM" and len(text.lstrip(" ")) >= 6:
        stripped = text.lstrip(" ")
        return f"{stripped[:2]}:{stripped[2:4]}:{stripped[4:]}"
    if vr == "DT" and len(text.lstrip(" ")) >= 14:
        stripped = text.lstrip(" ")
        return (
            f"{stripped[:4]}:{stripped[4:6]}:{stripped[6:8]} "
            f"{stripped[8:10]}:{stripped[10:12]}:{stripped[12:]}"
        )
    if vr == "AT" and len(raw_value) == 4:
        group = int.from_bytes(raw_value[:2], byte_order)
        element = int.from_bytes(raw_value[2:4], byte_order)
        return _format_tag(group, element)
    if vr == "UI":
        return text.split("\0", maxsplit=1)[0]
    if vr in {"DS", "IS"}:
        return _dicom_decimal_or_int_text(text.strip(" "))
    if vr in {"AE", "CS", "LO", "PN", "SH"}:
        return text.strip(" ")
    if vr in {"LT", "ST", "UT"}:
        return text.rstrip(" ")
    return text


def _dicom_decimal_or_int_text(value: str) -> int | float | str:
    if "\\" in value or not value:
        return value
    try:
        if "." not in value and "e" not in value.lower():
            return int(value)
        return float(value)
    except ValueError:
        return value


def _render_dicom_scalar(
    value: DicomScalarValue | None,
    raw_value: bytes,
    record: DicomDatasetElementRecord,
) -> str:
    if value is None:
        return f"Binary data {len(raw_value)} bytes"
    if record.vr == "UI" and isinstance(value, str):
        return REGISTERED_UID_PRINT_CONVERSIONS.get(value, value)
    if record.tag == "0028,0103" and isinstance(value, int):
        return {0: "Unsigned", 1: "Signed"}.get(value, str(value))
    return str(value)


def _emission_gates(emit_non_mutating: bool) -> tuple[DicomNonMutatingEmissionGate, ...]:
    status: DicomEmissionGateStatus = "open" if emit_non_mutating else "blocked"
    return (
        DicomNonMutatingEmissionGate(
            gate_id="explicit_non_mutating_emission",
            status=status,
            reason="DICOM planning emits no bytes unless the caller explicitly requests a plan.",
            evidence_id=DICOM_READ_ONLY_EVIDENCE_ID,
        ),
        DicomNonMutatingEmissionGate(
            gate_id="no_write_or_rewrite_backend",
            status="blocked",
            reason=(
                "Dataset write/rewrite is intentionally blocked until a "
                "source-grounded writer exists."
            ),
            evidence_id=DICOM_READ_ONLY_EVIDENCE_ID,
        ),
    )


def _truncated_blocker(tag: str | None, kind: DicomLengthKind) -> DicomTransactionBlocker:
    return DicomTransactionBlocker(
        blocker_id=kind,
        status="blocked",
        tag=tag,
        reason="Input ended before the planned DICOM element could be read completely.",
        evidence_id=DICOM_ELEMENT_DECODE_EVIDENCE_ID,
    )


def _synthetic_truncated_record(
    offset: int,
    byte_order: DicomByteOrder,
    vr_encoding: DicomTransferVrEncoding,
) -> DicomDatasetElementRecord:
    record = DicomTagDatabaseRecord(
        tag="FFFF,FFFF",
        group=0xFFFF,
        element=0xFFFF,
        name="TruncatedElementHeader",
        vr="",
        value_policy="metadata_value",
        private_kind="private_element",
        wildcard_family=None,
        evidence_id=DICOM_ELEMENT_DECODE_EVIDENCE_ID,
    )
    return DicomDatasetElementRecord(
        tag=record.tag,
        group=record.group,
        element=record.element,
        offset=offset,
        header_length=0,
        value_offset=offset,
        length=0,
        length_kind="truncated_header",
        vr="",
        byte_order=byte_order,
        vr_encoding=vr_encoding,
        database_record=record,
    )


def _group2_is_complete(offset: int, group2_end: int | None) -> bool:
    if group2_end is None:
        return True
    return offset >= group2_end


def _read_uid(data: bytes, element_record: DicomDatasetElementRecord) -> str:
    raw = data[element_record.value_offset : element_record.end_offset]
    return raw.split(b"\0", maxsplit=1)[0].decode("ascii", errors="ignore").strip()


def _ascii_vr(raw: bytes) -> str | None:
    if len(raw) != 2:
        return None
    if all(65 <= value <= 90 for value in raw):
        return raw.decode("ascii")
    return None


def _format_tag(group: int, element: int) -> str:
    return f"{group:04X},{element:04X}"
