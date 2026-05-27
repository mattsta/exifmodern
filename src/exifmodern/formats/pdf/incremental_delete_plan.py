"""Typed PDF incremental metadata-delete transaction planning.

The planner is intentionally non-mutating: it records the source-backed gates
and append-only transaction shape that :mod:`metadata_delete_writer` can emit,
but it does not write output bytes or files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.pdf.metadata_delete_writer import (
    PDF_BEGIN_EXIFTOOL_UPDATE,
    PDF_END_EXIFTOOL_UPDATE,
    PdfDictionary,
    PdfIndirectRef,
    PdfMetadataDeletePlan,
    PdfNewXrefEntry,
    PdfParsedFile,
    classify_pdf_metadata_delete,
    connect_free_xref_entries,
    has_exiftool_incremental_update,
    parse_indirect_ref,
    parse_pdf_file,
    read_indirect_dictionary,
    required_int,
    write_indirect_dictionary,
)
from exifmodern.json_types import JsonObject

type PdfIncrementalDeletePlanStatus = Literal["planned", "blocked", "no_change"]
type PdfPlanGateStatus = Literal["passed", "blocked", "not_applicable"]
type PdfObjectRole = Literal["root", "info", "metadata"]
type PdfDeleteResponsibilityCode = Literal[
    "delete_info_dictionary",
    "delete_xmp_metadata_stream",
    "replace_root_catalog_without_metadata",
    "no_pdf_metadata_delete_needed",
]
type PdfXrefUpdateEntryKind = Literal["free", "in_use_replacement"]
type PdfOffsetPolicy = Literal[
    "append_indirect_object_before_xref",
    "free_list_link_resolved_before_emit",
]


PDF_HEADER_SOURCE = "pdf.incremental_delete.header"
PDF_LINEARIZED_SOURCE = "pdf.incremental_delete.linearized"
PDF_XREF_SOURCE = "pdf.incremental_delete.xref"
WRITEPDF_CAPTURE_SOURCE = "pdf.incremental_delete.writepdf_capture"
WRITEPDF_INFO_SOURCE = "pdf.incremental_delete.writepdf_info"
WRITEPDF_XMP_SOURCE = "pdf.incremental_delete.writepdf_xmp"
WRITEPDF_APPEND_SOURCE = "pdf.incremental_delete.writepdf_append"
WRITEPDF_REVERSIBLE_SOURCE = "pdf.incremental_delete.writepdf_reversible"


@dataclass(frozen=True)
class PdfPlanGate:
    code: str
    status: PdfPlanGateStatus
    invariant: str
    observed: str
    evidence_ids: tuple[str, ...]

    @property
    def blocks_mutation(self) -> bool:
        return self.status == "blocked"

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "status": self.status,
            "blocks_mutation": self.blocks_mutation,
            "invariant": self.invariant,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class PdfPlannedObject:
    role: PdfObjectRole
    ref: PdfIndirectRef
    xref_offset: int | None
    in_use: bool | None

    def to_json(self) -> JsonObject:
        payload: JsonObject = {
            "role": self.role,
            "object_number": self.ref.object_number,
            "generation": self.ref.generation,
        }
        if self.xref_offset is not None:
            payload["xref_offset"] = self.xref_offset
        if self.in_use is not None:
            payload["in_use"] = self.in_use
        return payload


@dataclass(frozen=True)
class PdfXrefDiscovery:
    pdf_base: int | None
    pdf_version: str | None
    startxref: int | None
    line_separator: str | None
    trailer_size: int | None
    xref_entry_count: int
    objects: tuple[PdfPlannedObject, ...]

    def object_by_role(self, role: PdfObjectRole) -> PdfPlannedObject | None:
        for planned_object in self.objects:
            if planned_object.role == role:
                return planned_object
        return None

    def to_json(self) -> JsonObject:
        return {
            "pdf_base": self.pdf_base,
            "pdf_version": self.pdf_version,
            "startxref": self.startxref,
            "line_separator": self.line_separator,
            "trailer_size": self.trailer_size,
            "xref_entry_count": self.xref_entry_count,
            "objects": [planned_object.to_json() for planned_object in self.objects],
        }


@dataclass(frozen=True)
class PdfMetadataDeleteResponsibility:
    code: PdfDeleteResponsibilityCode
    object_ref: PdfIndirectRef | None
    action: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        payload: JsonObject = {
            "code": self.code,
            "action": self.action,
        }
        if self.object_ref is not None:
            payload["object_number"] = self.object_ref.object_number
            payload["generation"] = self.object_ref.generation
        return payload


@dataclass(frozen=True)
class PdfPlannedXrefUpdateEntry:
    object_number: int
    generation: int
    kind: PdfXrefUpdateEntryKind
    offset_policy: PdfOffsetPolicy
    planned_offset: int | None

    def to_json(self) -> JsonObject:
        payload: JsonObject = {
            "object_number": self.object_number,
            "generation": self.generation,
            "kind": self.kind,
            "offset_policy": self.offset_policy,
        }
        if self.planned_offset is not None:
            payload["planned_offset"] = self.planned_offset
        return payload


@dataclass(frozen=True)
class PdfXrefUpdatePlan:
    entries: tuple[PdfPlannedXrefUpdateEntry, ...]
    free_list_head_object_number: int | None
    evidence_ids: tuple[str, ...]

    def entry_for_object(self, object_number: int) -> PdfPlannedXrefUpdateEntry | None:
        for entry in self.entries:
            if entry.object_number == object_number:
                return entry
        return None

    def to_json(self) -> JsonObject:
        return {
            "entries": [entry.to_json() for entry in self.entries],
            "free_list_head_object_number": self.free_list_head_object_number,
        }


@dataclass(frozen=True)
class PdfTrailerUpdatePlan:
    remove_keys: tuple[str, ...]
    add_or_update_keys: tuple[str, ...]
    size_value: int | None
    prev_startxref: int | None
    output_kind: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "remove_keys": list(self.remove_keys),
            "add_or_update_keys": list(self.add_or_update_keys),
            "size_value": self.size_value,
            "prev_startxref": self.prev_startxref,
            "output_kind": self.output_kind,
        }


@dataclass(frozen=True)
class PdfOutputEmissionContract:
    append_only: bool
    no_in_place_mutation: bool
    begin_marker: str
    end_marker_prefix: str
    old_eof_offset: int | None
    planned_startxref: int | None
    emits_startxref_and_eof: bool
    reversible_delete_warning: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "append_only": self.append_only,
            "no_in_place_mutation": self.no_in_place_mutation,
            "begin_marker": self.begin_marker,
            "end_marker_prefix": self.end_marker_prefix,
            "old_eof_offset": self.old_eof_offset,
            "planned_startxref": self.planned_startxref,
            "emits_startxref_and_eof": self.emits_startxref_and_eof,
            "reversible_delete_warning": self.reversible_delete_warning,
        }


@dataclass(frozen=True)
class PdfIncrementalMetadataDeleteTransactionPlan:
    status: PdfIncrementalDeletePlanStatus
    reason: str
    gates: tuple[PdfPlanGate, ...]
    discovery: PdfXrefDiscovery
    responsibilities: tuple[PdfMetadataDeleteResponsibility, ...]
    xref_update: PdfXrefUpdatePlan
    trailer_update: PdfTrailerUpdatePlan
    output_contract: PdfOutputEmissionContract
    writer_plan: PdfMetadataDeletePlan
    evidence_ids: tuple[str, ...]

    @property
    def blocked_gate_codes(self) -> tuple[str, ...]:
        return tuple(gate.code for gate in self.gates if gate.blocks_mutation)

    @property
    def responsibility_codes(self) -> tuple[PdfDeleteResponsibilityCode, ...]:
        return tuple(responsibility.code for responsibility in self.responsibilities)

    def gate(self, code: str) -> PdfPlanGate:
        for gate in self.gates:
            if gate.code == code:
                return gate
        raise KeyError(code)

    def to_json(self) -> JsonObject:
        return {
            "status": self.status,
            "reason": self.reason,
            "blocked_gate_codes": list(self.blocked_gate_codes),
            "gates": [gate.to_json() for gate in self.gates],
            "discovery": self.discovery.to_json(),
            "responsibilities": [
                responsibility.to_json() for responsibility in self.responsibilities
            ],
            "xref_update": self.xref_update.to_json(),
            "trailer_update": self.trailer_update.to_json(),
            "output_contract": self.output_contract.to_json(),
            "writer_plan": self.writer_plan.to_json(),
        }


def plan_pdf_incremental_metadata_delete(
    data: bytes,
) -> PdfIncrementalMetadataDeleteTransactionPlan:
    """Build a source-backed, non-mutating PDF metadata delete transaction plan."""

    writer_plan = classify_pdf_metadata_delete(data)
    parsed = None
    root_dict: PdfDictionary | None = None
    parse_error: str | None = None
    root_parse_error: str | None = None
    try:
        parsed = parse_pdf_file(data)
        root_ref = parse_indirect_ref(parsed.trailer.value("Root"))
        if root_ref is not None:
            try:
                root_dict = read_indirect_dictionary(data, parsed, root_ref)
            except ValueError as error:
                root_parse_error = str(error)
    except ValueError as error:
        parse_error = str(error)

    gates = build_plan_gates(data, writer_plan, parsed, parse_error, root_parse_error)
    discovery = build_xref_discovery(parsed, root_dict)
    responsibilities = build_responsibilities(writer_plan)
    xref_update = build_xref_update_plan(data, parsed, writer_plan)
    trailer_update = build_trailer_update_plan(parsed, writer_plan)
    output_contract = build_output_emission_contract(data, parsed, root_dict, writer_plan)
    blocked = tuple(gate.code for gate in gates if gate.blocks_mutation)
    if blocked:
        status: PdfIncrementalDeletePlanStatus = "blocked"
        reason = f"Blocked by: {', '.join(blocked)}."
    elif writer_plan.status == "no_change":
        status = "no_change"
        reason = writer_plan.reason
    else:
        status = "planned"
        reason = writer_plan.reason
    return PdfIncrementalMetadataDeleteTransactionPlan(
        status=status,
        reason=reason,
        gates=gates,
        discovery=discovery,
        responsibilities=responsibilities,
        xref_update=xref_update,
        trailer_update=trailer_update,
        output_contract=output_contract,
        writer_plan=writer_plan,
        evidence_ids=PDF_INCREMENTAL_DELETE_SOURCES,
    )


def build_plan_gates(
    data: bytes,
    writer_plan: PdfMetadataDeletePlan,
    parsed: PdfParsedFile | None,
    parse_error: str | None,
    root_parse_error: str | None,
) -> tuple[PdfPlanGate, ...]:
    gates: list[PdfPlanGate] = []
    header_match = re.match(rb"^(\s*)%PDF-(\d+\.\d+)", data)
    gates.append(
        PdfPlanGate(
            code="pdf_header_present",
            status="passed" if header_match else "blocked",
            invariant="Input must begin with an optional PDFBase prefix followed by %PDF-version.",
            observed="found PDF header" if header_match else "missing PDF header",
            evidence_ids=(PDF_HEADER_SOURCE, WRITEPDF_CAPTURE_SOURCE),
        )
    )
    if parsed is not None:
        pdf_version = parsed.pdf_version
        version_blocked = float(pdf_version) > 2.0
        gates.append(
            PdfPlanGate(
                code="pdf_version_write_tested",
                status="blocked" if version_blocked else "passed",
                invariant="WritePDF refuses untested PDF versions greater than 2.0.",
                observed=f"PDF {pdf_version}",
                evidence_ids=(WRITEPDF_CAPTURE_SOURCE,),
            )
        )
    else:
        gates.append(
            PdfPlanGate(
                code="pdf_version_write_tested",
                status="not_applicable" if not header_match else "blocked",
                invariant="WritePDF refuses untested PDF versions greater than 2.0.",
                observed=parse_error or "version unavailable",
                evidence_ids=(WRITEPDF_CAPTURE_SOURCE,),
            )
        )
    gates.append(
        PdfPlanGate(
            code="no_prior_exiftool_update",
            status="blocked" if has_exiftool_incremental_update(data) else "passed",
            invariant="Existing ExifTool updates require rollback/reuse handling before append.",
            observed=(
                "prior %EndExifToolUpdate marker found"
                if has_exiftool_incremental_update(data)
                else "no prior ExifTool update marker found"
            ),
            evidence_ids=(WRITEPDF_CAPTURE_SOURCE,),
        )
    )
    gates.append(
        PdfPlanGate(
            code="not_linearized_pdf",
            status="blocked" if is_linearized_pdf(data) else "passed",
            invariant=(
                "Linearized PDFs need first-page hint-table invalidation/rebuild before append."
            ),
            observed=(
                "linearization dictionary found" if is_linearized_pdf(data) else "not linearized"
            ),
            evidence_ids=(PDF_LINEARIZED_SOURCE,),
        )
    )
    if parsed is None:
        gates.append(
            PdfPlanGate(
                code="classic_xref_table_captured",
                status="blocked",
                invariant=(
                    "Existing writer path requires startxref to resolve to a classic xref table."
                ),
                observed=parse_error or "xref unavailable",
                evidence_ids=(PDF_XREF_SOURCE,),
            )
        )
        return tuple(gates)
    trailer = parsed.trailer
    xref_entries = parsed.xref_entries
    trailer_size = trailer.value("Size")
    gates.extend(
        (
            PdfPlanGate(
                code="classic_xref_table_captured",
                status="passed",
                invariant="startxref must resolve to a readable classic xref table and trailer.",
                observed=(f"{len(xref_entries)} xref entries captured at {parsed.startxref}"),
                evidence_ids=(PDF_XREF_SOURCE,),
            ),
            PdfPlanGate(
                code="no_chained_prev_xref",
                status="blocked" if trailer.value("Prev") is not None else "passed",
                invariant=(
                    "This writer wrapper supports one captured main xref table, not /Prev chains."
                ),
                observed=(
                    "/Prev present" if trailer.value("Prev") is not None else "no /Prev entry"
                ),
                evidence_ids=(PDF_XREF_SOURCE,),
            ),
            PdfPlanGate(
                code="not_encrypted_pdf",
                status="blocked" if trailer.value("Encrypt") is not None else "passed",
                invariant="Encrypted PDFs require ExifTool object encryption/decryption handling.",
                observed=(
                    "/Encrypt present"
                    if trailer.value("Encrypt") is not None
                    else "no /Encrypt entry"
                ),
                evidence_ids=(PDF_XREF_SOURCE,),
            ),
            PdfPlanGate(
                code="trailer_size_numeric",
                status=(
                    "passed" if trailer_size is not None and trailer_size.isdigit() else "blocked"
                ),
                invariant="Trailer /Size must be numeric so xref free-list bounds can be planned.",
                observed=(
                    trailer_size.decode("latin-1")
                    if trailer_size is not None
                    else "missing trailer /Size"
                ),
                evidence_ids=(PDF_XREF_SOURCE, WRITEPDF_APPEND_SOURCE),
            ),
        )
    )
    root_ref = parse_indirect_ref(trailer.value("Root"))
    info_value = trailer.value("Info")
    info_ref = parse_indirect_ref(info_value)
    metadata_value = root_dict_value(root_parse_error, writer_plan, "metadata")
    metadata_ref = writer_plan.metadata_ref
    gates.extend(
        (
            PdfPlanGate(
                code="root_is_indirect_dictionary",
                status="blocked" if root_ref is None or root_parse_error else "passed",
                invariant="Trailer /Root must be an indirect dictionary object.",
                observed=root_parse_error
                or ("root ref found" if root_ref else "missing indirect /Root"),
                evidence_ids=(PDF_XREF_SOURCE,),
            ),
            PdfPlanGate(
                code="info_is_indirect_or_absent",
                status="blocked" if info_value is not None and info_ref is None else "passed",
                invariant="Trailer /Info must be absent or an indirect object reference.",
                observed=(
                    "absent"
                    if info_value is None
                    else ("indirect /Info ref found" if info_ref else "direct /Info value")
                ),
                evidence_ids=(WRITEPDF_INFO_SOURCE,),
            ),
            PdfPlanGate(
                code="metadata_is_indirect_or_absent",
                status=(
                    "blocked"
                    if (
                        root_dict_value(root_parse_error, writer_plan, "direct_metadata")
                        == "direct"
                    )
                    else "passed"
                ),
                invariant="Root /Metadata must be absent or an indirect stream reference.",
                observed=metadata_value or ("metadata ref found" if metadata_ref else "absent"),
                evidence_ids=(WRITEPDF_XMP_SOURCE,),
            ),
        )
    )
    return tuple(gates)


def build_xref_discovery(
    parsed: PdfParsedFile | None, root_dict: PdfDictionary | None
) -> PdfXrefDiscovery:
    if parsed is None:
        return PdfXrefDiscovery(
            pdf_base=None,
            pdf_version=None,
            startxref=None,
            line_separator=None,
            trailer_size=None,
            xref_entry_count=0,
            objects=(),
        )
    trailer = parsed.trailer
    xref_entries = parsed.xref_entries
    objects: list[PdfPlannedObject] = []
    root_ref = parse_indirect_ref(trailer.value("Root"))
    info_ref = parse_indirect_ref(trailer.value("Info"))
    metadata_ref = parse_indirect_ref(
        root_dict.value("Metadata") if root_dict is not None else None
    )
    role_refs: tuple[tuple[PdfObjectRole, PdfIndirectRef | None], ...] = (
        ("root", root_ref),
        ("info", info_ref),
        ("metadata", metadata_ref),
    )
    for role, ref in role_refs:
        if ref is None:
            continue
        xref_entry = xref_entries.get(ref.object_number)
        objects.append(
            PdfPlannedObject(
                role=role,
                ref=ref,
                xref_offset=None if xref_entry is None else xref_entry.offset,
                in_use=None if xref_entry is None else xref_entry.in_use,
            )
        )
    size_value = trailer.value("Size")
    return PdfXrefDiscovery(
        pdf_base=parsed.pdf_base,
        pdf_version=parsed.pdf_version,
        startxref=parsed.startxref,
        line_separator=parsed.line_separator.decode("latin-1"),
        trailer_size=(int(size_value) if size_value is not None and size_value.isdigit() else None),
        xref_entry_count=len(xref_entries),
        objects=tuple(objects),
    )


def build_responsibilities(
    writer_plan: PdfMetadataDeletePlan,
) -> tuple[PdfMetadataDeleteResponsibility, ...]:
    responsibilities: list[PdfMetadataDeleteResponsibility] = []
    if writer_plan.info_ref is not None:
        responsibilities.append(
            PdfMetadataDeleteResponsibility(
                code="delete_info_dictionary",
                object_ref=writer_plan.info_ref,
                action=(
                    "Remove trailer /Info and mark the previous Info object free in the new xref."
                ),
                evidence_ids=(WRITEPDF_INFO_SOURCE,),
            )
        )
    if writer_plan.metadata_ref is not None:
        responsibilities.extend(
            (
                PdfMetadataDeleteResponsibility(
                    code="delete_xmp_metadata_stream",
                    object_ref=writer_plan.metadata_ref,
                    action=(
                        "Mark the existing Root /Metadata stream object free when XMP "
                        "becomes empty."
                    ),
                    evidence_ids=(WRITEPDF_XMP_SOURCE,),
                ),
                PdfMetadataDeleteResponsibility(
                    code="replace_root_catalog_without_metadata",
                    object_ref=writer_plan.root_ref,
                    action=(
                        "Append a replacement Root dictionary with the /Metadata entry omitted."
                    ),
                    evidence_ids=(WRITEPDF_XMP_SOURCE, WRITEPDF_APPEND_SOURCE),
                ),
            )
        )
    if not responsibilities:
        responsibilities.append(
            PdfMetadataDeleteResponsibility(
                code="no_pdf_metadata_delete_needed",
                object_ref=None,
                action="No trailer /Info or Root /Metadata references are present.",
                evidence_ids=(WRITEPDF_INFO_SOURCE, WRITEPDF_XMP_SOURCE),
            )
        )
    return tuple(responsibilities)


def build_xref_update_plan(
    data: bytes,
    parsed: PdfParsedFile | None,
    writer_plan: PdfMetadataDeletePlan,
) -> PdfXrefUpdatePlan:
    if parsed is None or writer_plan.status != "supported":
        return PdfXrefUpdatePlan(
            entries=(),
            free_list_head_object_number=None,
            evidence_ids=(WRITEPDF_APPEND_SOURCE,),
        )
    new_xref: dict[int, PdfNewXrefEntry] = {0: PdfNewXrefEntry(0, 65535, "f")}
    if writer_plan.metadata_ref is not None:
        metadata_ref = writer_plan.metadata_ref
        new_xref[metadata_ref.object_number] = PdfNewXrefEntry(
            0,
            increment_generation(metadata_ref.generation),
            "f",
        )
    if writer_plan.info_ref is not None:
        info_ref = writer_plan.info_ref
        new_xref[info_ref.object_number] = PdfNewXrefEntry(
            0,
            increment_generation(info_ref.generation),
            "f",
        )
    if writer_plan.metadata_ref is not None and writer_plan.root_ref is not None:
        new_xref[writer_plan.root_ref.object_number] = PdfNewXrefEntry(
            replacement_root_offset(data, parsed),
            writer_plan.root_ref.generation,
            "n",
        )
    trailer_size = required_int(parsed.trailer.value("Size"), "trailer /Size")
    connect_free_xref_entries(new_xref, trailer_size)
    entries = tuple(
        PdfPlannedXrefUpdateEntry(
            object_number=object_number,
            generation=entry.generation,
            kind="free" if entry.entry_type == "f" else "in_use_replacement",
            offset_policy=(
                "free_list_link_resolved_before_emit"
                if entry.entry_type == "f"
                else "append_indirect_object_before_xref"
            ),
            planned_offset=entry.offset,
        )
        for object_number, entry in sorted(new_xref.items())
    )
    free_head = next(
        (entry.planned_offset for entry in entries if entry.object_number == 0),
        None,
    )
    return PdfXrefUpdatePlan(
        entries=entries,
        free_list_head_object_number=free_head,
        evidence_ids=(WRITEPDF_APPEND_SOURCE,),
    )


def build_trailer_update_plan(
    parsed: PdfParsedFile | None, writer_plan: PdfMetadataDeletePlan
) -> PdfTrailerUpdatePlan:
    if parsed is None or writer_plan.status != "supported":
        return PdfTrailerUpdatePlan(
            remove_keys=(),
            add_or_update_keys=(),
            size_value=None,
            prev_startxref=None,
            output_kind="none",
            evidence_ids=(WRITEPDF_APPEND_SOURCE,),
        )
    trailer = parsed.trailer
    trailer_size = trailer.value("Size")
    return PdfTrailerUpdatePlan(
        remove_keys=("Info",) if writer_plan.info_ref is not None else (),
        add_or_update_keys=("Prev", "Size"),
        size_value=(
            int(trailer_size) if trailer_size is not None and trailer_size.isdigit() else None
        ),
        prev_startxref=parsed.startxref,
        output_kind="classic_trailer_dictionary",
        evidence_ids=(WRITEPDF_INFO_SOURCE, WRITEPDF_APPEND_SOURCE),
    )


def build_output_emission_contract(
    data: bytes,
    parsed: PdfParsedFile | None,
    root_dict: PdfDictionary | None,
    writer_plan: PdfMetadataDeletePlan,
) -> PdfOutputEmissionContract:
    if parsed is None or writer_plan.status != "supported":
        return PdfOutputEmissionContract(
            append_only=True,
            no_in_place_mutation=True,
            begin_marker=PDF_BEGIN_EXIFTOOL_UPDATE.decode("ascii"),
            end_marker_prefix=PDF_END_EXIFTOOL_UPDATE.decode("ascii"),
            old_eof_offset=None,
            planned_startxref=None,
            emits_startxref_and_eof=False,
            reversible_delete_warning=True,
            evidence_ids=(WRITEPDF_APPEND_SOURCE, WRITEPDF_REVERSIBLE_SOURCE),
        )
    return PdfOutputEmissionContract(
        append_only=True,
        no_in_place_mutation=True,
        begin_marker=PDF_BEGIN_EXIFTOOL_UPDATE.decode("ascii"),
        end_marker_prefix=PDF_END_EXIFTOOL_UPDATE.decode("ascii"),
        old_eof_offset=len(data) - parsed.pdf_base,
        planned_startxref=planned_startxref(data, parsed, root_dict, writer_plan),
        emits_startxref_and_eof=True,
        reversible_delete_warning=True,
        evidence_ids=(WRITEPDF_APPEND_SOURCE, WRITEPDF_REVERSIBLE_SOURCE),
    )


def planned_startxref(
    data: bytes,
    parsed: PdfParsedFile,
    root_dict: PdfDictionary | None,
    writer_plan: PdfMetadataDeletePlan,
) -> int:
    line_separator = parsed.line_separator
    added_object_len = 0
    if (
        writer_plan.metadata_ref is not None
        and writer_plan.root_ref is not None
        and root_dict is not None
    ):
        root_without_metadata = root_dict.without("Metadata")
        scratch = bytearray()
        write_indirect_dictionary(
            scratch,
            line_separator,
            writer_plan.root_ref,
            root_without_metadata,
        )
        added_object_len = len(scratch)
    return (
        len(data)
        - parsed.pdf_base
        + len(PDF_BEGIN_EXIFTOOL_UPDATE)
        + added_object_len
        + len(line_separator)
    )


def replacement_root_offset(data: bytes, parsed: PdfParsedFile) -> int:
    return len(data) - parsed.pdf_base + len(PDF_BEGIN_EXIFTOOL_UPDATE) + len(parsed.line_separator)


def root_dict_value(
    root_parse_error: str | None,
    writer_plan: PdfMetadataDeletePlan,
    mode: Literal["metadata", "direct_metadata"],
) -> str | None:
    if root_parse_error is not None:
        return root_parse_error
    if writer_plan.reason.startswith("direct_metadata_dictionary"):
        return "direct" if mode == "direct_metadata" else "direct /Metadata value"
    return None


def is_linearized_pdf(data: bytes) -> bool:
    first_kib = data[:1024]
    header = re.match(rb"^(\s*)%PDF-\d+\.\d+", data)
    pdf_base = len(header.group(1)) if header else 0
    match = re.search(
        rb"<<(?P<body>.{0,512}?/Linearized\s+\S+.{0,512}?/L\s+(?P<size>\d+).*?)>>",
        first_kib,
        re.DOTALL,
    )
    if match is None:
        return False
    return int(match.group("size")) == len(data) - pdf_base


def increment_generation(generation: int) -> int:
    return generation + 1 if generation < 65535 else generation


PDF_INCREMENTAL_DELETE_SOURCES: tuple[str, ...] = (
    PDF_HEADER_SOURCE,
    PDF_LINEARIZED_SOURCE,
    PDF_XREF_SOURCE,
    WRITEPDF_CAPTURE_SOURCE,
    WRITEPDF_INFO_SOURCE,
    WRITEPDF_XMP_SOURCE,
    WRITEPDF_APPEND_SOURCE,
    WRITEPDF_REVERSIBLE_SOURCE,
)


install_evidence_reference_compat(globals())
