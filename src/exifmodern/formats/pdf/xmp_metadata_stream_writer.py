"""Bounded PDF XMP /Metadata stream writer.

The supported shape mirrors the safe subset already used by the PDF Info and
delete writers: classic xref table, no encryption, no chained /Prev, and no
prior tool incremental update block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.pdf.metadata_delete_writer import (
    PDF_BEGIN_EXIFTOOL_UPDATE,
    PDF_END_EXIFTOOL_UPDATE,
    PdfDictionary,
    PdfDictionaryEntry,
    PdfIndirectRef,
    PdfNewXrefEntry,
    PdfParsedFile,
    connect_free_xref_entries,
    has_exiftool_incremental_update,
    parse_indirect_ref,
    parse_pdf_dictionary,
    parse_pdf_file,
    read_indirect_dictionary,
    required_int,
    required_ref,
    skip_pdf_space,
    write_classic_xref_table,
    write_dictionary,
    write_indirect_dictionary,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan
from exifmodern.json_types import JsonObject

type PdfXmpMetadataWriteStatus = Literal["supported", "unsupported", "no_change"]
type PdfXmpMetadataWriteOperationKind = Literal[
    "append_replacement_metadata_stream",
    "append_new_metadata_stream",
    "append_replacement_root_with_metadata",
    "append_classic_xref_table",
    "append_trailer_with_metadata",
]


@dataclass(frozen=True)
class PdfXmpMetadataWriteOperation:
    kind: PdfXmpMetadataWriteOperationKind
    object_ref: PdfIndirectRef | None = None

    def to_json(self) -> JsonObject:
        payload: JsonObject = {"kind": self.kind}
        if self.object_ref is not None:
            payload["obj"] = self.object_ref.object_number
            payload["generation"] = self.object_ref.generation
        return payload


@dataclass(frozen=True)
class PdfXmpMetadataWritePlan:
    status: PdfXmpMetadataWriteStatus
    reason: str
    operations: tuple[PdfXmpMetadataWriteOperation, ...]
    pdf_version: str | None = None
    startxref: int | None = None
    eof_offset: int | None = None
    root_ref: PdfIndirectRef | None = None
    metadata_ref: PdfIndirectRef | None = None
    next_object_number: int | None = None

    @property
    def supported(self) -> bool:
        return self.status == "supported"

    def to_json(self) -> JsonObject:
        payload: JsonObject = {
            "status": self.status,
            "reason": self.reason,
            "operations": [operation.to_json() for operation in self.operations],
        }
        if self.pdf_version is not None:
            payload["pdf_version"] = self.pdf_version
        if self.startxref is not None:
            payload["startxref"] = self.startxref
        if self.eof_offset is not None:
            payload["eof_offset"] = self.eof_offset
        if self.root_ref is not None:
            payload["root_obj"] = self.root_ref.object_number
        if self.metadata_ref is not None:
            payload["metadata_obj"] = self.metadata_ref.object_number
        if self.next_object_number is not None:
            payload["next_object_number"] = self.next_object_number
        return payload


@dataclass(frozen=True)
class PdfXmpMetadataRewriteResult:
    data: bytes
    plan: PdfXmpMetadataWritePlan
    changed: bool
    changed_xmp_properties: int
    deleted_xmp_properties: int
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class PdfStreamObject:
    dictionary: PdfDictionary
    payload: bytes


def classify_pdf_xmp_metadata_stream_write(
    data: bytes,
    xmp_plan: XmpPropertyWritePlan,
) -> PdfXmpMetadataWritePlan:
    if not xmp_plan.steps:
        return PdfXmpMetadataWritePlan(
            status="no_change",
            reason="No XMP property write steps were requested.",
            operations=(),
        )
    if has_exiftool_incremental_update(data):
        return unsupported_pdf_xmp_metadata_write_plan(
            "prior_exiftool_update",
            "Existing incremental PDF update requires rollback/reuse semantics before appending.",
        )
    try:
        parsed = parse_pdf_file(data)
    except ValueError as error:
        return unsupported_pdf_xmp_metadata_write_plan("parse_error", str(error))

    if parsed.trailer.value("Prev") is not None:
        return unsupported_pdf_xmp_metadata_write_plan(
            "chained_xref",
            "Trailer /Prev requires full chained xref capture before a safe update.",
            parsed,
        )
    if parsed.trailer.value("Encrypt") is not None:
        return unsupported_pdf_xmp_metadata_write_plan(
            "encrypted_pdf",
            "Encrypted PDFs require decrypt/re-encrypt obj handling.",
            parsed,
        )

    root_ref = parse_indirect_ref(parsed.trailer.value("Root"))
    if root_ref is None:
        return unsupported_pdf_xmp_metadata_write_plan(
            "missing_indirect_root",
            "Trailer /Root is missing or is not an indirect obj reference.",
            parsed,
        )
    try:
        root_dict = read_indirect_dictionary(data, parsed, root_ref)
    except ValueError as error:
        return unsupported_pdf_xmp_metadata_write_plan(
            "root_object_parse_error",
            str(error),
            parsed,
            root_ref=root_ref,
        )

    metadata_value = root_dict.value("Metadata")
    metadata_ref = parse_indirect_ref(metadata_value)
    if metadata_value is not None and metadata_ref is None:
        return unsupported_pdf_xmp_metadata_write_plan(
            "direct_metadata_dictionary",
            "Root /Metadata is present but is not an indirect obj reference.",
            parsed,
            root_ref=root_ref,
        )
    if metadata_ref is not None:
        try:
            read_indirect_stream(data, parsed, metadata_ref)
        except ValueError as error:
            return unsupported_pdf_xmp_metadata_write_plan(
                "metadata_stream_parse_error",
                str(error),
                parsed,
                root_ref=root_ref,
                metadata_ref=metadata_ref,
            )
        operations: tuple[PdfXmpMetadataWriteOperation, ...] = (
            PdfXmpMetadataWriteOperation("append_replacement_metadata_stream", metadata_ref),
            PdfXmpMetadataWriteOperation("append_classic_xref_table"),
            PdfXmpMetadataWriteOperation("append_trailer_with_metadata"),
        )
    else:
        next_object_number = required_int(parsed.trailer.value("Size"), "trailer /Size")
        metadata_ref = PdfIndirectRef(next_object_number, 0)
        operations = (
            PdfXmpMetadataWriteOperation("append_new_metadata_stream", metadata_ref),
            PdfXmpMetadataWriteOperation("append_replacement_root_with_metadata", root_ref),
            PdfXmpMetadataWriteOperation("append_classic_xref_table"),
            PdfXmpMetadataWriteOperation("append_trailer_with_metadata"),
        )

    return PdfXmpMetadataWritePlan(
        status="supported",
        reason="Classic xref PDF can be updated with a reversible XMP Metadata stream append.",
        operations=operations,
        pdf_version=parsed.pdf_version,
        startxref=parsed.startxref,
        eof_offset=len(data) - parsed.pdf_base,
        root_ref=root_ref,
        metadata_ref=metadata_ref,
        next_object_number=required_int(parsed.trailer.value("Size"), "trailer /Size"),
    )


def rewrite_pdf_xmp_metadata_stream(
    data: bytes,
    xmp_plan: XmpPropertyWritePlan,
) -> PdfXmpMetadataRewriteResult:
    plan = classify_pdf_xmp_metadata_stream_write(data, xmp_plan)
    if plan.status == "unsupported":
        raise ValueError(plan.reason)
    if plan.status == "no_change":
        return PdfXmpMetadataRewriteResult(
            data=data,
            plan=plan,
            changed=False,
            changed_xmp_properties=0,
            deleted_xmp_properties=0,
        )

    parsed = parse_pdf_file(data)
    root_ref = required_ref(plan.root_ref, "Root")
    metadata_ref = required_ref(plan.metadata_ref, "Metadata")
    root_dict = read_indirect_dictionary(data, parsed, root_ref)
    existing_metadata_ref = parse_indirect_ref(root_dict.value("Metadata"))
    existing_packet = (
        read_indirect_stream(data, parsed, existing_metadata_ref).payload
        if existing_metadata_ref is not None
        else empty_xmp_packet()
    )
    mutation = apply_xmp_property_write_plan(existing_packet, xmp_plan)
    if mutation.changed_properties == 0 and mutation.deleted_properties == 0:
        return PdfXmpMetadataRewriteResult(
            data=data,
            plan=plan,
            changed=False,
            changed_xmp_properties=0,
            deleted_xmp_properties=0,
        )

    output = bytearray(data)
    old_eof = len(data) - parsed.pdf_base
    output.extend(PDF_BEGIN_EXIFTOOL_UPDATE)
    new_xref: dict[int, PdfNewXrefEntry] = {0: PdfNewXrefEntry(0, 65535, "f")}

    metadata_offset = len(output) - parsed.pdf_base + len(parsed.line_separator)
    new_xref[metadata_ref.object_number] = PdfNewXrefEntry(
        metadata_offset,
        metadata_ref.generation,
        "n",
    )
    write_indirect_metadata_stream(output, parsed.line_separator, metadata_ref, mutation.packet)

    trailer = parsed.trailer.upsert("Prev", str(parsed.startxref).encode("ascii"))
    if existing_metadata_ref is None:
        root_with_metadata = root_dict.upsert("Metadata", metadata_ref.raw)
        root_offset = len(output) - parsed.pdf_base + len(parsed.line_separator)
        new_xref[root_ref.object_number] = PdfNewXrefEntry(
            root_offset,
            root_ref.generation,
            "n",
        )
        write_indirect_dictionary(output, parsed.line_separator, root_ref, root_with_metadata)
        size = max(
            required_int(trailer.value("Size"), "trailer /Size"),
            metadata_ref.object_number + 1,
        )
        trailer = trailer.upsert("Size", str(size).encode("ascii"))

    connect_free_xref_entries(new_xref, required_int(trailer.value("Size"), "trailer /Size"))

    startxref = len(output) - parsed.pdf_base + len(parsed.line_separator)
    write_classic_xref_table(output, parsed.line_separator, new_xref)
    output.extend(b"trailer")
    write_dictionary(output, parsed.line_separator, trailer)
    output.extend(parsed.line_separator)
    output.extend(PDF_END_EXIFTOOL_UPDATE)
    output.extend(str(old_eof).encode("ascii"))
    output.extend(parsed.line_separator)
    output.extend(b"startxref")
    output.extend(parsed.line_separator)
    output.extend(str(startxref).encode("ascii"))
    output.extend(parsed.line_separator)
    output.extend(b"%%EOF")
    output.extend(parsed.line_separator)
    return PdfXmpMetadataRewriteResult(
        data=bytes(output),
        plan=plan,
        changed=True,
        changed_xmp_properties=mutation.changed_properties,
        deleted_xmp_properties=mutation.deleted_properties,
    )


def rewrite_pdf_file_xmp_metadata_stream(
    input_path: Path,
    output_path: Path,
    xmp_plan: XmpPropertyWritePlan,
) -> PdfXmpMetadataRewriteResult:
    result = rewrite_pdf_xmp_metadata_stream(input_path.read_bytes(), xmp_plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return PdfXmpMetadataRewriteResult(
        data=result.data,
        plan=result.plan,
        changed=result.changed,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )


def read_indirect_stream(
    data: bytes,
    parsed: PdfParsedFile,
    ref: PdfIndirectRef,
) -> PdfStreamObject:
    xref_entry = parsed.xref_entries.get(ref.object_number)
    if xref_entry is None or not xref_entry.in_use:
        raise ValueError(f"Missing in-use xref entry for obj {ref.object_number}.")
    pos = parsed.pdf_base + xref_entry.offset
    object_header = re.match(rb"\s*(\d+)\s+(\d+)\s+obj\b", data[pos : pos + 80])
    if object_header is None:
        raise ValueError(f"Obj {ref.object_number} is not an indirect obj at its xref offset.")
    if (
        int(object_header.group(1)) != ref.object_number
        or int(object_header.group(2)) != ref.generation
    ):
        raise ValueError(f"Obj {ref.object_number} xref entry points to a different obj header.")
    dictionary, dictionary_end = parse_pdf_dictionary(data, pos + object_header.end())
    if dictionary.value("Filter") is not None:
        raise ValueError(
            "Metadata stream uses a filter; bounded PDF XMP writes support raw XML only."
        )
    length = pdf_stream_length(data, parsed, dictionary)
    stream_marker_pos = skip_pdf_space(data, dictionary_end)
    if data[stream_marker_pos : stream_marker_pos + 6] != b"stream":
        raise ValueError(f"Object {ref.object_number} is not a stream object.")
    payload_start = stream_payload_start(data, stream_marker_pos + 6)
    payload_end = payload_start + length
    if payload_end > len(data):
        raise ValueError(f"Object {ref.object_number} stream length exceeds file size.")
    endstream_pos = skip_pdf_space(data, payload_end)
    if data[endstream_pos : endstream_pos + 9] != b"endstream":
        raise ValueError(f"Object {ref.object_number} stream length does not reach endstream.")
    return PdfStreamObject(dictionary=dictionary, payload=data[payload_start:payload_end])


def pdf_stream_length(data: bytes, parsed: PdfParsedFile, dictionary: PdfDictionary) -> int:
    length_value = dictionary.value("Length")
    if length_value is None:
        raise ValueError("Metadata stream is missing /Length.")
    if length_value.isdigit():
        return int(length_value)
    length_ref = parse_indirect_ref(length_value)
    if length_ref is None:
        raise ValueError("Metadata stream /Length is neither direct numeric nor indirect ref.")
    length_dictionary_or_scalar = read_indirect_scalar(data, parsed, length_ref)
    if not length_dictionary_or_scalar.isdigit():
        raise ValueError("Metadata stream indirect /Length object is not numeric.")
    return int(length_dictionary_or_scalar)


def read_indirect_scalar(data: bytes, parsed: PdfParsedFile, ref: PdfIndirectRef) -> bytes:
    xref_entry = parsed.xref_entries.get(ref.object_number)
    if xref_entry is None or not xref_entry.in_use:
        raise ValueError(f"Missing in-use xref entry for obj {ref.object_number}.")
    pos = parsed.pdf_base + xref_entry.offset
    object_header = re.match(rb"\s*(\d+)\s+(\d+)\s+obj\b", data[pos : pos + 80])
    if object_header is None:
        raise ValueError(f"Obj {ref.object_number} is not an indirect obj at its xref offset.")
    body_start = pos + object_header.end()
    endobj = data.find(b"endobj", body_start)
    if endobj < 0:
        raise ValueError(f"Object {ref.object_number} is missing endobj.")
    return data[body_start:endobj].strip()


def stream_payload_start(data: bytes, pos: int) -> int:
    if data[pos : pos + 2] == b"\r\n":
        return pos + 2
    if data[pos : pos + 1] in {b"\r", b"\n"}:
        return pos + 1
    raise ValueError("PDF stream keyword is not followed by an end-of-line marker.")


def write_indirect_metadata_stream(
    output: bytearray,
    line_separator: bytes,
    ref: PdfIndirectRef,
    packet: bytes,
) -> None:
    dictionary = PdfDictionary(
        (
            PdfDictionaryEntry("Type", b"/Metadata"),
            PdfDictionaryEntry("Subtype", b"/XML"),
            PdfDictionaryEntry("Length", str(len(packet)).encode("ascii")),
        )
    )
    output.extend(line_separator)
    output.extend(ref.object_header)
    write_dictionary(output, line_separator, dictionary)
    output.extend(line_separator)
    output.extend(b"stream")
    output.extend(line_separator)
    output.extend(packet)
    output.extend(line_separator)
    output.extend(b"endstream")
    output.extend(line_separator)
    output.extend(b"endobj")


def unsupported_pdf_xmp_metadata_write_plan(
    status_reason: str,
    detail: str,
    parsed: PdfParsedFile | None = None,
    root_ref: PdfIndirectRef | None = None,
    metadata_ref: PdfIndirectRef | None = None,
) -> PdfXmpMetadataWritePlan:
    return PdfXmpMetadataWritePlan(
        status="unsupported",
        reason=f"{status_reason}: {detail}",
        operations=(),
        pdf_version=None if parsed is None else parsed.pdf_version,
        startxref=None if parsed is None else parsed.startxref,
        eof_offset=None if parsed is None else 0,
        root_ref=root_ref,
        metadata_ref=metadata_ref,
        next_object_number=None,
    )
