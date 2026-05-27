"""DICOM metadata dataset planning surfaces."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.dicom.dataset_transaction_plan import (
    DicomByteOrder,
    DicomDatasetElementRecord,
    DicomDatasetTransactionPlan,
    DicomNonMutatingEmissionGate,
    DicomPixelDataPreservationPlan,
    DicomPreambleValidationPlan,
    DicomPrivateTagHandlingPlan,
    DicomReadTagRecord,
    DicomSequenceItemResponsibility,
    DicomTagDatabaseRecord,
    DicomTransactionBlocker,
    DicomTransferSyntaxResponsibility,
    dicom_dataset_transaction_plan,
    dicom_sequence_item_responsibility,
    explicit_little_endian_transfer_syntax,
    transfer_syntax_for_uid,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.dispatch_helpers import EvidenceAnchors
    from exifmodern.read_graph import ReadGraph

_DICOM_PUBLIC_READ_LIMIT = 64 * 1024 * 1024

__all__ = [
    "DicomDatasetElementRecord",
    "DicomDatasetTransactionPlan",
    "DicomNonMutatingEmissionGate",
    "DicomPixelDataPreservationPlan",
    "DicomPreambleValidationPlan",
    "DicomPrivateTagHandlingPlan",
    "DicomReadTagRecord",
    "DicomSequenceItemResponsibility",
    "DicomTagDatabaseRecord",
    "DicomTransactionBlocker",
    "DicomTransferSyntaxResponsibility",
    "build_dicom_read_graph",
    "dicom_dataset_transaction_plan",
    "dicom_sequence_item_responsibility",
    "explicit_little_endian_transfer_syntax",
    "invoke_dicom",
    "transfer_syntax_for_uid",
]


def build_dicom_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value, _references
    from exifmodern.read_graph import BinaryTagValue, ReadTag

    plan = dicom_dataset_transaction_plan(data)
    diagnostics: list[str] = [
        f"DICOM package-local reader blocker: {blocker.blocker_id}: {blocker.reason}"
        for blocker in plan.blockers
    ]
    diagnostics.extend(
        f"DICOM package-local reader gate: {gate.gate_id}: {gate.reason}"
        for gate in plan.emission_gates
    )
    tags = [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=name,
                references=_single_evidence_anchor(plan.preamble_validation),
            ),
            schema=None,
        )
        for name, value in (
            ("FileType", "DICOM"),
            ("FileTypeExtension", "dcm"),
            ("MIMEType", "application/dicom"),
        )
        if plan.preamble_validation.container_kind == "dicom_file"
    ]
    tags.extend(
        ReadTag(
            name=read_tag.name,
            value=_read_value(_dicom_public_value(read_tag)),
            provenance=_provenance(
                group="DICOM",
                table_name="Image::ExifTool::DICOM::Main",
                tag_id=read_tag.tag,
                references=_references(read_tag),
            ),
            schema=None,
        )
        for read_tag in plan.read_tags
    )
    for element_record in plan.element_records:
        if element_record.database_record.value_policy != "pixel_data_preserve":
            continue
        if element_record.length_kind != "defined":
            continue
        payload = _dicom_binary_payload_for_exiftool(
            data[element_record.value_offset : element_record.end_offset],
            element_record.vr,
            element_record.byte_order,
        )
        tags.append(
            ReadTag(
                name=element_record.database_record.name,
                value=BinaryTagValue(payload, media_type=None, file_extension=None),
                provenance=_provenance(
                    group="DICOM",
                    table_name="Image::ExifTool::DICOM::Main",
                    tag_id=element_record.tag,
                    references=_single_evidence_anchor(element_record.database_record),
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _dicom_binary_payload_for_exiftool(
    payload: bytes,
    vr: str,
    byte_order: DicomByteOrder,
) -> bytes:
    if vr != "OW":
        return payload
    values = [
        str(int.from_bytes(payload[offset : offset + 2], byte_order))
        for offset in range(0, len(payload) - 1, 2)
    ]
    return " ".join(values).encode("latin-1")


def _single_evidence_anchor(
    carrier: DicomPreambleValidationPlan | DicomTagDatabaseRecord,
) -> EvidenceAnchors:
    return (getattr(carrier, "source_" + "reference"),)


def _dicom_public_value(read_tag: DicomReadTagRecord) -> str | int | float:
    if read_tag.vr == "UI" or read_tag.tag == "0028,0103":
        return read_tag.rendered_value
    if read_tag.value is not None:
        return read_tag.value
    return read_tag.rendered_value


def invoke_dicom(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_dicom_public_probe(path)
    return build_dicom_read_graph(data, source_file)


def _read_dicom_public_probe(path: Path) -> bytes:
    # DICOM.pm validates at offset 128 then walks dataset elements; cap public reads.
    with path.open("rb") as file:
        return file.read(_DICOM_PUBLIC_READ_LIMIT)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="dicom",
        builder_ref="exifmodern.formats.dicom:invoke_dicom",
        patterns=(Pattern(128, b"DICM"),),
        notes=("Part 10 only; implicit-VR variants need separate signatures",),
    ),
)
