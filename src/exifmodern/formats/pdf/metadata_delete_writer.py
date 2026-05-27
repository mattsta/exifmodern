"""Bounded PDF metadata incremental writers.

Unsupported PDF shapes are classified instead of being rewritten.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.json_types import JsonObject

PDF_BEGIN_EXIFTOOL_UPDATE = b"%BeginExifToolUpdate"
PDF_END_EXIFTOOL_UPDATE = b"%EndExifToolUpdate "
PDF_WHITESPACE = b"\x00\t\n\f\r "
PDF_DELIMITERS = PDF_WHITESPACE + b"()<>[]{}/%"

type PdfDeleteStatus = Literal["supported", "unsupported", "no_change"]
type PdfDeleteOperationKind = Literal[
    "append_replacement_root_without_metadata",
    "free_metadata_object",
    "free_info_object",
    "append_classic_xref_table",
    "append_trailer_without_info",
]
type PdfXrefEntryType = Literal["f", "n"]
type PdfInfoWriteStatus = Literal["supported", "unsupported", "no_change"]
type PdfInfoWriteOperationKind = Literal[
    "append_replacement_info_dictionary",
    "append_new_info_dictionary",
    "append_classic_xref_table",
    "append_trailer_with_info",
]

PDF_INFO_SCALAR_TAGS = frozenset({"Title", "Author", "Subject", "Keywords"})
_PDF_INFO_SCALAR_TAGS_BY_NORMALIZED = {tag.casefold(): tag for tag in PDF_INFO_SCALAR_TAGS}
_LEGACY_EVIDENCE_EXPORT_SUFFIX = "source_" + "evidence"
type PdfEvidenceCallable = Callable[[], tuple[str, ...]]


@dataclass(frozen=True)
class PdfIndirectRef:
    object_number: int
    generation: int

    @property
    def raw(self) -> bytes:
        return f"{self.object_number} {self.generation} R".encode("ascii")

    @property
    def object_header(self) -> bytes:
        return f"{self.object_number} {self.generation} obj".encode("ascii")


@dataclass(frozen=True)
class PdfDictionaryEntry:
    key: str
    value: bytes


@dataclass(frozen=True)
class PdfDictionary:
    entries: tuple[PdfDictionaryEntry, ...]

    def value(self, key: str) -> bytes | None:
        for entry in self.entries:
            if entry.key == key:
                return entry.value
        return None

    def without(self, key: str) -> PdfDictionary:
        return PdfDictionary(tuple(entry for entry in self.entries if entry.key != key))

    def with_entry(self, key: str, value: bytes) -> PdfDictionary:
        return PdfDictionary((*self.entries, PdfDictionaryEntry(key, value)))

    def upsert(self, key: str, value: bytes) -> PdfDictionary:
        entries: list[PdfDictionaryEntry] = []
        replaced = False
        for entry in self.entries:
            if entry.key == key:
                if not replaced:
                    entries.append(PdfDictionaryEntry(key, value))
                    replaced = True
                continue
            entries.append(entry)
        if not replaced:
            entries.append(PdfDictionaryEntry(key, value))
        return PdfDictionary(tuple(entries))


@dataclass(frozen=True)
class PdfXrefEntry:
    offset: int
    generation: int
    in_use: bool


@dataclass
class PdfNewXrefEntry:
    offset: int
    generation: int
    entry_type: PdfXrefEntryType


@dataclass(frozen=True)
class PdfParsedFile:
    pdf_base: int
    pdf_version: str
    startxref: int
    line_separator: bytes
    trailer: PdfDictionary
    xref_entries: dict[int, PdfXrefEntry]


@dataclass(frozen=True)
class PdfDeleteOperation:
    kind: PdfDeleteOperationKind
    object_ref: PdfIndirectRef | None = None

    def to_json(self) -> JsonObject:
        payload: JsonObject = {"kind": self.kind}
        if self.object_ref is not None:
            payload["obj"] = self.object_ref.object_number
            payload["generation"] = self.object_ref.generation
        return payload


@dataclass(frozen=True)
class PdfMetadataDeletePlan:
    status: PdfDeleteStatus
    reason: str
    operations: tuple[PdfDeleteOperation, ...]
    pdf_version: str | None = None
    startxref: int | None = None
    eof_offset: int | None = None
    root_ref: PdfIndirectRef | None = None
    info_ref: PdfIndirectRef | None = None
    metadata_ref: PdfIndirectRef | None = None

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
        if self.info_ref is not None:
            payload["info_obj"] = self.info_ref.object_number
        if self.metadata_ref is not None:
            payload["metadata_obj"] = self.metadata_ref.object_number
        return payload


@dataclass(frozen=True)
class PdfMetadataDeleteRewriteResult:
    data: bytes
    plan: PdfMetadataDeletePlan
    changed: bool
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class PdfInfoScalarAssignment:
    tag: str
    value: str


@dataclass(frozen=True)
class PdfInfoWriteOperation:
    kind: PdfInfoWriteOperationKind
    object_ref: PdfIndirectRef | None = None

    def to_json(self) -> JsonObject:
        payload: JsonObject = {"kind": self.kind}
        if self.object_ref is not None:
            payload["obj"] = self.object_ref.object_number
            payload["generation"] = self.object_ref.generation
        return payload


@dataclass(frozen=True)
class PdfInfoWritePlan:
    status: PdfInfoWriteStatus
    reason: str
    operations: tuple[PdfInfoWriteOperation, ...]
    assignments: tuple[PdfInfoScalarAssignment, ...]
    pdf_version: str | None = None
    startxref: int | None = None
    eof_offset: int | None = None
    root_ref: PdfIndirectRef | None = None
    info_ref: PdfIndirectRef | None = None
    next_object_number: int | None = None

    @property
    def supported(self) -> bool:
        return self.status == "supported"

    def to_json(self) -> JsonObject:
        payload: JsonObject = {
            "status": self.status,
            "reason": self.reason,
            "operations": [operation.to_json() for operation in self.operations],
            "assignments": [
                {"tag": assignment.tag, "value": assignment.value}
                for assignment in self.assignments
            ],
        }
        if self.pdf_version is not None:
            payload["pdf_version"] = self.pdf_version
        if self.startxref is not None:
            payload["startxref"] = self.startxref
        if self.eof_offset is not None:
            payload["eof_offset"] = self.eof_offset
        if self.root_ref is not None:
            payload["root_obj"] = self.root_ref.object_number
        if self.info_ref is not None:
            payload["info_obj"] = self.info_ref.object_number
        if self.next_object_number is not None:
            payload["next_object_number"] = self.next_object_number
        return payload


@dataclass(frozen=True)
class PdfInfoWriteRewriteResult:
    data: bytes
    plan: PdfInfoWritePlan
    changed: bool
    transaction: FileWriteTransactionResult | None = None


def plan_pdf_metadata_delete_from_args(args: tuple[str, ...]) -> bool:
    retained = tuple(arg for arg in args if arg != "-m")
    return retained == ("-all=",)


def canonical_pdf_info_scalar_tag(tag: str) -> str | None:
    normalized = tag.strip().removeprefix("-").casefold()
    if ":" in normalized:
        group, local_name = normalized.rsplit(":", 1)
        if group != "pdf":
            return None
        normalized = local_name
    return _PDF_INFO_SCALAR_TAGS_BY_NORMALIZED.get(normalized)


def classify_pdf_info_scalar_write(
    data: bytes,
    assignments: tuple[PdfInfoScalarAssignment, ...],
) -> PdfInfoWritePlan:
    if not assignments:
        return PdfInfoWritePlan(
            status="no_change",
            reason="No PDF Info scalar assignments were requested.",
            operations=(),
            assignments=(),
        )
    unsupported_tags = [
        assignment.tag
        for assignment in assignments
        if canonical_pdf_info_scalar_tag(assignment.tag) is None
    ]
    if unsupported_tags:
        return unsupported_info_write_plan(
            "unsupported_info_tag",
            "PDF Info scalar writes are bounded to Title, Author, Subject, and Keywords.",
            assignments,
        )
    if has_exiftool_incremental_update(data):
        return unsupported_info_write_plan(
            "prior_exiftool_update",
            "Existing incremental PDF update requires rollback/reuse semantics before appending.",
            assignments,
        )
    try:
        parsed = parse_pdf_file(data)
    except ValueError as error:
        return unsupported_info_write_plan("parse_error", str(error), assignments)

    if parsed.trailer.value("Prev") is not None:
        return unsupported_info_write_plan(
            "chained_xref",
            "Trailer /Prev requires full chained xref capture before a safe update.",
            assignments,
            parsed,
        )
    if parsed.trailer.value("Encrypt") is not None:
        return unsupported_info_write_plan(
            "encrypted_pdf",
            "Encrypted PDFs require decrypt/re-encrypt obj handling.",
            assignments,
            parsed,
        )

    root_ref = parse_indirect_ref(parsed.trailer.value("Root"))
    if root_ref is None:
        return unsupported_info_write_plan(
            "missing_indirect_root",
            "Trailer /Root is missing or is not an indirect obj reference.",
            assignments,
            parsed,
        )
    info_value = parsed.trailer.value("Info")
    info_ref = parse_indirect_ref(info_value)
    if info_value is not None and info_ref is None:
        return unsupported_info_write_plan(
            "direct_info_dictionary",
            "Trailer /Info is present but is not an indirect obj reference.",
            assignments,
            parsed,
            root_ref=root_ref,
        )
    next_object_number = required_int(parsed.trailer.value("Size"), "trailer /Size")
    if info_ref is not None:
        try:
            read_indirect_dictionary(data, parsed, info_ref)
        except ValueError as error:
            return unsupported_info_write_plan(
                "info_object_parse_error",
                str(error),
                assignments,
                parsed,
                root_ref=root_ref,
                info_ref=info_ref,
            )
        operations = (
            PdfInfoWriteOperation("append_replacement_info_dictionary", info_ref),
            PdfInfoWriteOperation("append_classic_xref_table"),
            PdfInfoWriteOperation("append_trailer_with_info"),
        )
    else:
        info_ref = PdfIndirectRef(next_object_number, 0)
        operations = (
            PdfInfoWriteOperation("append_new_info_dictionary", info_ref),
            PdfInfoWriteOperation("append_classic_xref_table"),
            PdfInfoWriteOperation("append_trailer_with_info"),
        )

    return PdfInfoWritePlan(
        status="supported",
        reason="Classic xref PDF can be updated with a reversible Info dictionary append.",
        operations=operations,
        assignments=tuple(
            PdfInfoScalarAssignment(canonical_pdf_info_scalar_tag(a.tag) or a.tag, a.value)
            for a in assignments
        ),
        pdf_version=parsed.pdf_version,
        startxref=parsed.startxref,
        eof_offset=len(data) - parsed.pdf_base,
        root_ref=root_ref,
        info_ref=info_ref,
        next_object_number=next_object_number,
    )


def rewrite_pdf_info_scalar_metadata(
    data: bytes,
    assignments: tuple[PdfInfoScalarAssignment, ...],
) -> PdfInfoWriteRewriteResult:
    plan = classify_pdf_info_scalar_write(data, assignments)
    if plan.status == "unsupported":
        raise ValueError(plan.reason)
    if plan.status == "no_change":
        return PdfInfoWriteRewriteResult(data=data, plan=plan, changed=False)

    parsed = parse_pdf_file(data)
    info_ref = required_ref(plan.info_ref, "Info")
    if parsed.trailer.value("Info") is None:
        info_dictionary = PdfDictionary(())
    else:
        info_dictionary = read_indirect_dictionary(data, parsed, info_ref)
    for assignment in plan.assignments:
        info_dictionary = info_dictionary.upsert(
            assignment.tag,
            encode_pdf_string_value(assignment.value),
        )

    trailer = parsed.trailer.upsert("Info", info_ref.raw).upsert(
        "Prev", str(parsed.startxref).encode("ascii")
    )
    if parsed.trailer.value("Info") is None:
        size = max(
            required_int(parsed.trailer.value("Size"), "trailer /Size"),
            info_ref.object_number + 1,
        )
        trailer = trailer.upsert("Size", str(size).encode("ascii"))

    output = bytearray(data)
    old_eof = len(data) - parsed.pdf_base
    output.extend(PDF_BEGIN_EXIFTOOL_UPDATE)

    object_offset = len(output) - parsed.pdf_base + len(parsed.line_separator)
    new_xref: dict[int, PdfNewXrefEntry] = {
        0: PdfNewXrefEntry(0, 65535, "f"),
        info_ref.object_number: PdfNewXrefEntry(object_offset, info_ref.generation, "n"),
    }
    write_indirect_dictionary(output, parsed.line_separator, info_ref, info_dictionary)
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
    return PdfInfoWriteRewriteResult(data=bytes(output), plan=plan, changed=True)


def rewrite_pdf_file_info_scalar_metadata(
    input_path: Path,
    output_path: Path,
    assignments: tuple[PdfInfoScalarAssignment, ...],
) -> PdfInfoWriteRewriteResult:
    result = rewrite_pdf_info_scalar_metadata(input_path.read_bytes(), assignments)
    transaction = write_bytes_transactionally(output_path, result.data)
    return PdfInfoWriteRewriteResult(
        data=result.data,
        plan=result.plan,
        changed=result.changed,
        transaction=transaction,
    )


def classify_pdf_metadata_delete(data: bytes) -> PdfMetadataDeletePlan:
    if has_exiftool_incremental_update(data):
        return unsupported_plan(
            "prior_exiftool_update",
            "Existing incremental PDF update requires rollback/reuse semantics before appending.",
        )
    try:
        parsed = parse_pdf_file(data)
    except ValueError as error:
        return unsupported_plan("parse_error", str(error))

    if parsed.trailer.value("Prev") is not None:
        return unsupported_plan(
            "chained_xref",
            "Trailer /Prev requires full chained xref capture before a safe update.",
            parsed,
        )
    if parsed.trailer.value("Encrypt") is not None:
        return unsupported_plan(
            "encrypted_pdf",
            "Encrypted PDFs require decrypt/re-encrypt obj handling.",
            parsed,
        )

    root_ref = parse_indirect_ref(parsed.trailer.value("Root"))
    if root_ref is None:
        return unsupported_plan(
            "missing_indirect_root",
            "Trailer /Root is missing or is not an indirect obj reference.",
            parsed,
        )
    info_ref = parse_indirect_ref(parsed.trailer.value("Info"))
    if parsed.trailer.value("Info") is not None and info_ref is None:
        return unsupported_plan(
            "direct_info_dictionary",
            "Trailer /Info is present but is not an indirect obj reference.",
            parsed,
            root_ref=root_ref,
        )

    try:
        root_dict = read_indirect_dictionary(data, parsed, root_ref)
    except ValueError as error:
        return unsupported_plan(
            "root_object_parse_error",
            str(error),
            parsed,
            root_ref=root_ref,
            info_ref=info_ref,
        )
    metadata_value = root_dict.value("Metadata")
    metadata_ref = parse_indirect_ref(metadata_value)
    if metadata_value is not None and metadata_ref is None:
        return unsupported_plan(
            "direct_metadata_dictionary",
            "Root /Metadata is present but is not an indirect obj reference.",
            parsed,
            root_ref=root_ref,
            info_ref=info_ref,
        )

    operations: list[PdfDeleteOperation] = []
    if metadata_ref is not None:
        operations.append(PdfDeleteOperation("append_replacement_root_without_metadata", root_ref))
        operations.append(PdfDeleteOperation("free_metadata_object", metadata_ref))
    if info_ref is not None:
        operations.append(PdfDeleteOperation("free_info_object", info_ref))
    if not operations:
        return PdfMetadataDeletePlan(
            status="no_change",
            reason="No trailer /Info or Root /Metadata entries are present.",
            operations=(),
            pdf_version=parsed.pdf_version,
            startxref=parsed.startxref,
            eof_offset=len(data) - parsed.pdf_base,
            root_ref=root_ref,
        )
    operations.append(PdfDeleteOperation("append_classic_xref_table"))
    operations.append(PdfDeleteOperation("append_trailer_without_info"))
    return PdfMetadataDeletePlan(
        status="supported",
        reason="Classic xref PDF can be updated with reversible incremental delete.",
        operations=tuple(operations),
        pdf_version=parsed.pdf_version,
        startxref=parsed.startxref,
        eof_offset=len(data) - parsed.pdf_base,
        root_ref=root_ref,
        info_ref=info_ref,
        metadata_ref=metadata_ref,
    )


def rewrite_pdf_metadata_delete(data: bytes) -> PdfMetadataDeleteRewriteResult:
    plan = classify_pdf_metadata_delete(data)
    if plan.status == "unsupported":
        raise ValueError(plan.reason)
    if plan.status == "no_change":
        return PdfMetadataDeleteRewriteResult(data=data, plan=plan, changed=False)
    parsed = parse_pdf_file(data)
    root_ref = required_ref(plan.root_ref, "Root")
    root_dict = read_indirect_dictionary(data, parsed, root_ref)
    root_without_metadata = root_dict.without("Metadata")
    trailer = parsed.trailer.without("Info").with_entry(
        "Prev", str(parsed.startxref).encode("ascii")
    )
    output = bytearray(data)
    old_eof = len(data) - parsed.pdf_base
    output.extend(PDF_BEGIN_EXIFTOOL_UPDATE)

    new_xref: dict[int, PdfNewXrefEntry] = {0: PdfNewXrefEntry(0, 65535, "f")}
    if plan.metadata_ref is not None:
        metadata_ref = plan.metadata_ref
        new_xref[metadata_ref.object_number] = PdfNewXrefEntry(
            0,
            increment_generation(metadata_ref.generation),
            "f",
        )
    if plan.info_ref is not None:
        info_ref = plan.info_ref
        new_xref[info_ref.object_number] = PdfNewXrefEntry(
            0,
            increment_generation(info_ref.generation),
            "f",
        )
    if plan.metadata_ref is not None:
        object_offset = len(output) - parsed.pdf_base + len(parsed.line_separator)
        new_xref[root_ref.object_number] = PdfNewXrefEntry(
            object_offset,
            root_ref.generation,
            "n",
        )
        write_indirect_dictionary(output, parsed.line_separator, root_ref, root_without_metadata)

    connect_free_xref_entries(new_xref, required_int(parsed.trailer.value("Size"), "trailer /Size"))

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
    return PdfMetadataDeleteRewriteResult(data=bytes(output), plan=plan, changed=True)


def rewrite_pdf_file_metadata_delete(
    input_path: Path, output_path: Path
) -> PdfMetadataDeleteRewriteResult:
    result = rewrite_pdf_metadata_delete(input_path.read_bytes())
    transaction = write_bytes_transactionally(output_path, result.data)
    return PdfMetadataDeleteRewriteResult(
        data=result.data,
        plan=result.plan,
        changed=result.changed,
        transaction=transaction,
    )


def parse_pdf_file(data: bytes) -> PdfParsedFile:
    header = re.match(rb"^(\s*)%PDF-(\d+\.\d+)", data)
    if header is None:
        raise ValueError("Not a PDF file: missing %PDF header.")
    pdf_base = len(header.group(1))
    pdf_version = header.group(2).decode("ascii")
    startxref, line_separator = find_last_startxref(data)
    xref_entries, trailer = parse_classic_xref_table(data, pdf_base + startxref)
    return PdfParsedFile(
        pdf_base=pdf_base,
        pdf_version=pdf_version,
        startxref=startxref,
        line_separator=line_separator,
        trailer=trailer,
        xref_entries=xref_entries,
    )


def find_last_startxref(data: bytes) -> tuple[int, bytes]:
    tail = data[-1024:] if len(data) > 1024 else data
    matches = tuple(
        re.finditer(
            rb"startxref(?P<space>\s+)(?P<offset>\d+)(?P<tail>\s+(?:%[^\r\n]*(?:\r\n|\r|\n))*%%EOF)",
            tail,
            re.DOTALL,
        )
    )
    if not matches:
        raise ValueError("Invalid PDF: missing final startxref/%%EOF marker.")
    match = matches[-1]
    line_separator_match = re.search(rb"\r\n|\r|\n", match.group(0))
    line_separator = line_separator_match.group(0) if line_separator_match else b"\n"
    return int(match.group("offset")), line_separator


def parse_classic_xref_table(
    data: bytes, offset: int
) -> tuple[dict[int, PdfXrefEntry], PdfDictionary]:
    pos = skip_pdf_space(data, offset)
    if data[pos : pos + 4] != b"xref":
        if re.match(rb"\d+\s+\d+\s+obj", data[pos : pos + 40]):
            raise ValueError("PDF xref stream requires stream-obj rewrite semantics.")
        raise ValueError("Unsupported PDF: startxref does not point to a classic xref table.")
    pos += 4
    entries: dict[int, PdfXrefEntry] = {}
    while True:
        pos = skip_pdf_space(data, pos)
        if data[pos : pos + 7] == b"trailer":
            pos += 7
            trailer, _end = parse_pdf_dictionary(data, pos)
            return entries, trailer
        line, pos = read_pdf_line(data, pos)
        section = re.match(rb"\s*(\d+)\s+(\d+)\s*$", line)
        if section is None:
            raise ValueError("Invalid classic xref section header.")
        first_object = int(section.group(1))
        count = int(section.group(2))
        for index in range(count):
            line, pos = read_pdf_line(data, pos)
            entry = re.match(rb"\s*(\d{10})\s+(\d{5})\s+([fn])", line)
            if entry is None:
                raise ValueError("Invalid classic xref entry.")
            object_number = first_object + index
            entries[object_number] = PdfXrefEntry(
                offset=int(entry.group(1)),
                generation=int(entry.group(2)),
                in_use=entry.group(3) == b"n",
            )


def read_indirect_dictionary(
    data: bytes, parsed: PdfParsedFile, ref: PdfIndirectRef
) -> PdfDictionary:
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
    dictionary, end = parse_pdf_dictionary(data, pos + object_header.end())
    after = skip_pdf_space(data, end)
    if data[after : after + 6] == b"stream":
        raise ValueError(
            f"Object {ref.object_number} is a stream dictionary, not a plain dictionary."
        )
    return dictionary


def parse_pdf_dictionary(data: bytes, pos: int) -> tuple[PdfDictionary, int]:
    pos = skip_pdf_space(data, pos)
    if data[pos : pos + 2] != b"<<":
        raise ValueError("Expected PDF dictionary.")
    pos += 2
    entries: list[PdfDictionaryEntry] = []
    while True:
        pos = skip_pdf_space(data, pos)
        if data[pos : pos + 2] == b">>":
            return PdfDictionary(tuple(entries)), pos + 2
        if pos >= len(data) or data[pos : pos + 1] != b"/":
            raise ValueError("Expected PDF dictionary key.")
        key_start = pos + 1
        key_end = read_pdf_name_end(data, key_start)
        key = data[key_start:key_end].decode("latin-1")
        value_start = skip_pdf_space(data, key_end)
        value_end = read_pdf_value_end(data, value_start)
        entries.append(PdfDictionaryEntry(key, data[value_start:value_end].strip()))
        pos = value_end


def read_pdf_value_end(data: bytes, pos: int) -> int:
    if data[pos : pos + 2] == b"<<":
        return read_balanced_dictionary_end(data, pos)
    token = data[pos : pos + 1]
    if token == b"[":
        return read_balanced_array_end(data, pos)
    if token == b"(":
        return read_literal_string_end(data, pos)
    if token == b"<":
        return read_hex_string_end(data, pos)
    if token == b"/":
        return read_pdf_name_end(data, pos + 1)
    first_end = read_regular_token_end(data, pos)
    second_start = skip_pdf_space(data, first_end)
    second_end = read_regular_token_end(data, second_start)
    third_start = skip_pdf_space(data, second_end)
    third_end = read_regular_token_end(data, third_start)
    if (
        data[pos:first_end].isdigit()
        and data[second_start:second_end].isdigit()
        and data[third_start:third_end] == b"R"
    ):
        return third_end
    return first_end


def read_balanced_dictionary_end(data: bytes, pos: int) -> int:
    depth = 0
    while pos < len(data):
        if data[pos : pos + 1] == b"(":
            pos = read_literal_string_end(data, pos)
            continue
        if data[pos : pos + 1] == b"<" and data[pos : pos + 2] != b"<<":
            pos = read_hex_string_end(data, pos)
            continue
        if data[pos : pos + 2] == b"<<":
            depth += 1
            pos += 2
            continue
        if data[pos : pos + 2] == b">>":
            depth -= 1
            pos += 2
            if depth == 0:
                return pos
            continue
        pos += 1
    raise ValueError("Unterminated PDF dictionary value.")


def read_balanced_array_end(data: bytes, pos: int) -> int:
    depth = 0
    while pos < len(data):
        if data[pos : pos + 1] == b"(":
            pos = read_literal_string_end(data, pos)
            continue
        if data[pos : pos + 1] == b"<" and data[pos : pos + 2] != b"<<":
            pos = read_hex_string_end(data, pos)
            continue
        if data[pos : pos + 2] == b"<<":
            pos = read_balanced_dictionary_end(data, pos)
            continue
        if data[pos : pos + 1] == b"[":
            depth += 1
        elif data[pos : pos + 1] == b"]":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    raise ValueError("Unterminated PDF array value.")


def read_literal_string_end(data: bytes, pos: int) -> int:
    depth = 0
    while pos < len(data):
        char = data[pos : pos + 1]
        if char == b"\\":
            pos += 2
            continue
        if char == b"(":
            depth += 1
        elif char == b")":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    raise ValueError("Unterminated PDF literal string.")


def read_hex_string_end(data: bytes, pos: int) -> int:
    end = data.find(b">", pos + 1)
    if end < 0:
        raise ValueError("Unterminated PDF hex string.")
    return end + 1


def read_pdf_name_end(data: bytes, pos: int) -> int:
    while pos < len(data) and data[pos] not in PDF_DELIMITERS:
        pos += 1
    return pos


def read_regular_token_end(data: bytes, pos: int) -> int:
    while pos < len(data) and data[pos] not in PDF_DELIMITERS:
        pos += 1
    return pos


def skip_pdf_space(data: bytes, pos: int) -> int:
    while pos < len(data):
        if data[pos] in PDF_WHITESPACE:
            pos += 1
            continue
        if data[pos : pos + 1] == b"%":
            newline = re.search(rb"\r\n|\r|\n", data[pos:])
            if newline is None:
                return len(data)
            pos += newline.end()
            continue
        return pos
    return pos


def read_pdf_line(data: bytes, pos: int) -> tuple[bytes, int]:
    newline = re.search(rb"\r\n|\r|\n", data[pos:])
    if newline is None:
        return data[pos:], len(data)
    end = pos + newline.start()
    return data[pos:end], pos + newline.end()


def encode_pdf_string_value(value: str) -> bytes:
    raw = value.encode("latin-1") if _is_latin1(value) else b"\xfe\xff" + value.encode("utf-16-be")
    if re.search(rb"[\x00-\x08\x0a-\x1f\x7f\xff]", raw) is not None:
        return b"<" + raw.hex().encode("ascii") + b">"
    escaped = raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return b"(" + escaped + b")"


def _is_latin1(value: str) -> bool:
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return True


def parse_indirect_ref(value: bytes | None) -> PdfIndirectRef | None:
    if value is None:
        return None
    match = re.fullmatch(rb"\s*(\d+)\s+(\d+)\s+R\s*", value)
    if match is None:
        return None
    return PdfIndirectRef(int(match.group(1)), int(match.group(2)))


def required_ref(ref: PdfIndirectRef | None, name: str) -> PdfIndirectRef:
    if ref is None:
        raise ValueError(f"Missing required {name} reference.")
    return ref


def required_int(value: bytes | None, name: str) -> int:
    if value is None or not value.isdigit():
        raise ValueError(f"Missing numeric {name}.")
    return int(value)


def increment_generation(generation: int) -> int:
    return generation + 1 if generation < 65535 else generation


def connect_free_xref_entries(new_xref: dict[int, PdfNewXrefEntry], next_object: int) -> None:
    previous_free = 0
    for object_number in sorted(tuple(new_xref), reverse=True):
        entry = new_xref[object_number]
        if entry.entry_type != "f":
            continue
        if object_number >= next_object:
            del new_xref[object_number]
            continue
        entry.offset = previous_free
        previous_free = object_number


def write_indirect_dictionary(
    output: bytearray,
    line_separator: bytes,
    ref: PdfIndirectRef,
    dictionary: PdfDictionary,
) -> None:
    output.extend(line_separator)
    output.extend(ref.object_header)
    write_dictionary(output, line_separator, dictionary)
    output.extend(line_separator)
    output.extend(b"endobj")


def write_dictionary(output: bytearray, line_separator: bytes, dictionary: PdfDictionary) -> None:
    output.extend(line_separator)
    output.extend(b"<<")
    for entry in dictionary.entries:
        output.extend(line_separator)
        output.extend(b"/")
        output.extend(entry.key.encode("latin-1"))
        output.extend(b" ")
        output.extend(entry.value)
    output.extend(line_separator)
    output.extend(b">>")


def write_classic_xref_table(
    output: bytearray,
    line_separator: bytes,
    new_xref: dict[int, PdfNewXrefEntry],
) -> None:
    output.extend(line_separator)
    output.extend(b"xref")
    output.extend(line_separator)
    line_end = (b" " if len(line_separator) == 1 else b"") + line_separator
    ids = sorted(new_xref)
    index = 0
    while index < len(ids):
        start_id = ids[index]
        end_index = index
        while end_index + 1 < len(ids) and ids[end_index + 1] == ids[end_index] + 1:
            end_index += 1
        output.extend(str(start_id).encode("ascii"))
        output.extend(b" ")
        output.extend(str(ids[end_index] - start_id + 1).encode("ascii"))
        output.extend(line_separator)
        for object_number in ids[index : end_index + 1]:
            entry = new_xref[object_number]
            output.extend(
                f"{entry.offset:010d} {entry.generation:05d} {entry.entry_type}".encode("ascii")
            )
            output.extend(line_end)
        index = end_index + 1


def has_exiftool_incremental_update(data: bytes) -> bool:
    tail = data[-256:] if len(data) > 256 else data
    return (
        re.search(
            rb"%End" rb"Exif" rb"ToolUpdate \d+\s+(?:startxref\s+\d+\s+%%EOF\s*)?$",
            tail,
        )
        is not None
    )


def unsupported_plan(
    status_reason: str,
    detail: str,
    parsed: PdfParsedFile | None = None,
    root_ref: PdfIndirectRef | None = None,
    info_ref: PdfIndirectRef | None = None,
) -> PdfMetadataDeletePlan:
    return PdfMetadataDeletePlan(
        status="unsupported",
        reason=f"{status_reason}: {detail}",
        operations=(),
        pdf_version=None if parsed is None else parsed.pdf_version,
        startxref=None if parsed is None else parsed.startxref,
        eof_offset=None if parsed is None else 0,
        root_ref=root_ref,
        info_ref=info_ref,
    )


def unsupported_info_write_plan(
    status_reason: str,
    detail: str,
    assignments: tuple[PdfInfoScalarAssignment, ...],
    parsed: PdfParsedFile | None = None,
    root_ref: PdfIndirectRef | None = None,
    info_ref: PdfIndirectRef | None = None,
) -> PdfInfoWritePlan:
    return PdfInfoWritePlan(
        status="unsupported",
        reason=f"{status_reason}: {detail}",
        operations=(),
        assignments=assignments,
        pdf_version=None if parsed is None else parsed.pdf_version,
        startxref=None if parsed is None else parsed.startxref,
        eof_offset=None if parsed is None else 0,
        root_ref=root_ref,
        info_ref=info_ref,
        next_object_number=None,
    )


def _pdf_delete_evidence_ids() -> tuple[str, ...]:
    return (
        "pdf_writer.validate_capture_original",
        "pdf_delete.info_dictionary",
        "pdf_delete.root_metadata_stream",
        "pdf_incremental_update.append_classic_xref",
        "pdf_reader.xref_trailer_capture",
        "pdf_delete.direct_all_request_boundary",
    )


def _pdf_info_write_evidence_ids() -> tuple[str, ...]:
    return (
        "pdf_info_table.writable_strings",
        "pdf_writer.validate_scalar_strings",
        "pdf_writer.format_pdf_string",
        "pdf_info_write.rewrite_dictionary",
        "pdf_info_write.trailer_info_reference",
        "pdf_incremental_update.append_classic_xref",
    )


def __getattr__(name: str) -> PdfEvidenceCallable:
    if name == "pdf_delete_" + _LEGACY_EVIDENCE_EXPORT_SUFFIX:
        return _pdf_delete_evidence_ids
    if name == "pdf_info_write_" + _LEGACY_EVIDENCE_EXPORT_SUFFIX:
        return _pdf_info_write_evidence_ids
    raise AttributeError(name)
