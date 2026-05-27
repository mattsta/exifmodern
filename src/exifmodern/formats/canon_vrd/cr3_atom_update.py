"""CanonVRD CR3 UUID-Canon2 atom update contracts.

This module consumes the CanonVRD setup atom-boundary contract and builds the
Canon2 uuid atom payloads routed through the QuickTime update path.  Whole-file
CR3 emission is delegated to the shared bounded Canon RAW final emitter so
WriteLast ordering and CTBO/mdat fixups stay centralized.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.canon_raw.final_emission import (
    Cr3AtomReplacement,
    Cr3BoundedEmissionResult,
    emit_bounded_cr3_quicktime_stream,
)
from exifmodern.formats.canon_vrd.copy_from_file_writer import extract_canon_dr4_block
from exifmodern.formats.canon_vrd.dr4_value_writer import (
    CanonVrdDr4ValueWriteUnsupportedError,
    requested_values_for_step,
    rewrite_standalone_dr4_values,
)
from exifmodern.formats.canon_vrd.reader import canon_vrd_blocks
from exifmodern.formats.canon_vrd.setup_write_plan import (
    CR3_CANON2_UUID_HEX,
    CanonVrdCr3SetupAtomBoundary,
    CanonVrdSetupWriteStep,
)
from exifmodern.formats.canon_vrd.setup_writer import (
    CANON_DR4_BLOCK_TYPE,
    wrap_canon_dr4_as_vrd_trailer,
)
from exifmodern.json_types import JsonObject

type CanonVrdCr3AtomUpdateAction = Literal[
    "insert_uuid_canon2_dr4_trailer",
    "replace_uuid_canon2_dr4_trailer",
    "rewrite_uuid_canon2_embedded_dr4_values",
]
type CanonVrdCr3AtomGateCode = Literal[
    "requires_quicktime_write_last_emitter",
    "requires_cr3_ctbo_offset_size_fixup",
    "requires_cr3_mdat_offset_context",
    "requires_existing_uuid_canon2_atom",
    "requires_canon_vrd_trailer_payload",
    "requires_canon_dr4_payload",
    "unsupported_canon_vrd_cr3_action",
]

UUID_ATOM_HEADER_SIZE = 8
UUID_IDENTIFIER_SIZE = 16
UUID_CANON2_IDENTIFIER = bytes.fromhex(CR3_CANON2_UUID_HEX)
UUID_CANON2_ATOM_TYPE = "uuid"


@dataclass(frozen=True)
class CanonVrdCr3UuidAtomRange:
    offset: int
    size: int
    payload_offset: int
    payload_size: int

    def to_json(self) -> JsonObject:
        return {
            "offset": self.offset,
            "payload_offset": self.payload_offset,
            "payload_size": self.payload_size,
            "size": self.size,
        }


@dataclass(frozen=True)
class CanonVrdCr3UuidAtomReplacement:
    atom_type: str
    uuid_hex: str
    old_range: CanonVrdCr3UuidAtomRange | None
    new_atom: bytes
    new_payload_size: int
    dr4_payload_size: int
    canon_vrd_trailer_size: int

    @property
    def new_size(self) -> int:
        return len(self.new_atom)

    @property
    def size_delta(self) -> int | None:
        if self.old_range is None:
            return None
        return self.new_size - self.old_range.size

    def to_json(self) -> JsonObject:
        return {
            "atom_type": self.atom_type,
            "canon_vrd_trailer_size": self.canon_vrd_trailer_size,
            "dr4_payload_size": self.dr4_payload_size,
            "new_payload_size": self.new_payload_size,
            "new_size": self.new_size,
            "old_range": self.old_range.to_json() if self.old_range is not None else None,
            "size_delta": self.size_delta,
            "uuid_hex": self.uuid_hex,
        }


@dataclass(frozen=True)
class CanonVrdCr3UuidFixupContract:
    length_fixups: tuple[str, ...]
    can_apply_container_update: bool
    gate_codes: tuple[CanonVrdCr3AtomGateCode, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_apply_container_update": self.can_apply_container_update,
            "gate_codes": list(self.gate_codes),
            "length_fixups": list(self.length_fixups),
        }


@dataclass(frozen=True)
class CanonVrdCr3AtomUpdatePlan:
    action: CanonVrdCr3AtomUpdateAction
    boundary: CanonVrdCr3SetupAtomBoundary
    replacement: CanonVrdCr3UuidAtomReplacement | None
    fixup_contract: CanonVrdCr3UuidFixupContract
    embedded_value_tags: tuple[str, ...]

    @property
    def can_materialize_uuid_atom(self) -> bool:
        return self.replacement is not None

    @property
    def can_emit_cr3_bytes(self) -> bool:
        return (
            self.can_materialize_uuid_atom
            and self.fixup_contract.can_apply_container_update
            and not self.fixup_contract.gate_codes
        )

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "boundary": self.boundary.to_json(),
            "can_emit_cr3_bytes": self.can_emit_cr3_bytes,
            "can_materialize_uuid_atom": self.can_materialize_uuid_atom,
            "embedded_value_tags": list(self.embedded_value_tags),
            "fixup_contract": self.fixup_contract.to_json(),
            "replacement": self.replacement.to_json() if self.replacement is not None else None,
        }


@dataclass(frozen=True)
class CanonVrdCr3BoundedReplacementResult:
    data: bytes
    replaced_offset: int
    replaced_size: int
    preserved_size: bool
    source_reference_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "preserved_size": self.preserved_size,
            "replaced_offset": self.replaced_offset,
            "replaced_size": self.replaced_size,
        }


@dataclass(frozen=True)
class CanonVrdCr3BoundedWriteLastEmissionResult:
    data: bytes
    action: CanonVrdCr3AtomUpdateAction
    replaced_offset: int | None
    write_last_atom_count: int
    source_reference_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "replaced_offset": self.replaced_offset,
            "write_last_atom_count": self.write_last_atom_count,
        }


class CanonVrdCr3AtomUpdateUnsupportedError(ValueError):
    """Raised when a CR3 CanonVRD atom update cannot be planned from local bytes."""


def plan_canon_vrd_cr3_setup_atom_update(
    *,
    target_cr3_data: bytes,
    source_dr4_data: bytes,
    step: CanonVrdSetupWriteStep,
) -> CanonVrdCr3AtomUpdatePlan:
    boundary = require_cr3_boundary(step)
    if step.action != "copy_generated_dr4_block_to_canon_raw_trailer":
        return gated_plan("unsupported_canon_vrd_cr3_action", boundary, step)
    dr4_data = extract_canon_dr4_block(source_dr4_data)
    existing_atom = find_uuid_canon2_atom(target_cr3_data)
    replacement = uuid_replacement_for_dr4(dr4_data, existing_atom)
    action: CanonVrdCr3AtomUpdateAction = (
        "replace_uuid_canon2_dr4_trailer"
        if existing_atom is not None
        else "insert_uuid_canon2_dr4_trailer"
    )
    return CanonVrdCr3AtomUpdatePlan(
        action=action,
        boundary=boundary,
        replacement=replacement,
        fixup_contract=container_fixup_contract_for_target(
            boundary,
            target_cr3_data,
            replacement,
            (),
        ),
        embedded_value_tags=(),
    )


def plan_canon_vrd_cr3_embedded_value_update(
    *,
    source_cr3_data: bytes,
    step: CanonVrdSetupWriteStep,
) -> CanonVrdCr3AtomUpdatePlan:
    boundary = require_cr3_boundary(step)
    if step.action != "rewrite_embedded_generated_dr4_values":
        return gated_plan("unsupported_canon_vrd_cr3_action", boundary, step)
    existing_atom = find_uuid_canon2_atom(source_cr3_data)
    if existing_atom is None:
        return gated_plan("requires_existing_uuid_canon2_atom", boundary, step)
    try:
        trailer = uuid_canon2_payload(source_cr3_data, existing_atom)
    except CanonVrdCr3AtomUpdateUnsupportedError:
        return gated_plan("requires_canon_vrd_trailer_payload", boundary, step)
    try:
        dr4_data = extract_canon_dr4_block(trailer)
    except ValueError:
        return gated_plan("requires_canon_dr4_payload", boundary, step)
    requested_values = requested_values_for_step(step.external_step)
    if not requested_values:
        return gated_plan("requires_canon_dr4_payload", boundary, step)
    try:
        rewrite_result = rewrite_standalone_dr4_values(dr4_data, requested_values)
    except CanonVrdDr4ValueWriteUnsupportedError as error:
        raise CanonVrdCr3AtomUpdateUnsupportedError(str(error)) from error
    replacement = uuid_replacement_for_dr4(rewrite_result.data, existing_atom)
    return CanonVrdCr3AtomUpdatePlan(
        action="rewrite_uuid_canon2_embedded_dr4_values",
        boundary=boundary,
        replacement=replacement,
        fixup_contract=container_fixup_contract_for_target(
            boundary,
            source_cr3_data,
            replacement,
            (),
        ),
        embedded_value_tags=rewrite_result.changed_tags,
    )


def require_cr3_boundary(step: CanonVrdSetupWriteStep) -> CanonVrdCr3SetupAtomBoundary:
    boundary = step.cr3_atom_boundary
    if boundary is None:
        raise CanonVrdCr3AtomUpdateUnsupportedError("CanonVRD step has no CR3 atom boundary")
    return boundary


def gated_plan(
    gate_code: CanonVrdCr3AtomGateCode,
    boundary: CanonVrdCr3SetupAtomBoundary,
    step: CanonVrdSetupWriteStep,
) -> CanonVrdCr3AtomUpdatePlan:
    action: CanonVrdCr3AtomUpdateAction = (
        "rewrite_uuid_canon2_embedded_dr4_values"
        if step.action == "rewrite_embedded_generated_dr4_values"
        else "insert_uuid_canon2_dr4_trailer"
    )
    return CanonVrdCr3AtomUpdatePlan(
        action=action,
        boundary=boundary,
        replacement=None,
        fixup_contract=container_fixup_contract(boundary, (gate_code,)),
        embedded_value_tags=(),
    )


def uuid_replacement_for_dr4(
    dr4_data: bytes,
    old_range: CanonVrdCr3UuidAtomRange | None,
) -> CanonVrdCr3UuidAtomReplacement:
    trailer = wrap_canon_dr4_as_vrd_trailer(dr4_data)
    return CanonVrdCr3UuidAtomReplacement(
        atom_type=UUID_CANON2_ATOM_TYPE,
        uuid_hex=CR3_CANON2_UUID_HEX,
        old_range=old_range,
        new_atom=encode_uuid_canon2_atom(trailer),
        new_payload_size=len(UUID_CANON2_IDENTIFIER) + len(trailer),
        dr4_payload_size=len(dr4_data),
        canon_vrd_trailer_size=len(trailer),
    )


def encode_uuid_canon2_atom(canon_vrd_trailer: bytes) -> bytes:
    size = UUID_ATOM_HEADER_SIZE + UUID_IDENTIFIER_SIZE + len(canon_vrd_trailer)
    if size > 0x7FFFFFFF:
        raise CanonVrdCr3AtomUpdateUnsupportedError("CanonVRD UUID atom is too large")
    return size.to_bytes(4, "big") + b"uuid" + UUID_CANON2_IDENTIFIER + canon_vrd_trailer


def find_uuid_canon2_atom(data: bytes) -> CanonVrdCr3UuidAtomRange | None:
    offset = 0
    while offset + UUID_ATOM_HEADER_SIZE <= len(data):
        atom_size = int.from_bytes(data[offset : offset + 4], "big")
        atom_type = data[offset + 4 : offset + 8]
        header_size = UUID_ATOM_HEADER_SIZE
        if atom_size == 1:
            if offset + 16 > len(data):
                return None
            atom_size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header_size = 16
        if atom_size < header_size or offset + atom_size > len(data):
            return None
        identifier_offset = offset + header_size
        payload_offset = identifier_offset + UUID_IDENTIFIER_SIZE
        if (
            atom_type == b"uuid"
            and payload_offset <= offset + atom_size
            and data[identifier_offset:payload_offset] == UUID_CANON2_IDENTIFIER
        ):
            return CanonVrdCr3UuidAtomRange(
                offset=offset,
                size=atom_size,
                payload_offset=payload_offset,
                payload_size=offset + atom_size - payload_offset,
            )
        offset += atom_size
    return None


def uuid_canon2_payload(data: bytes, atom_range: CanonVrdCr3UuidAtomRange) -> bytes:
    start = atom_range.payload_offset
    end = start + atom_range.payload_size
    payload = data[start:end]
    try:
        has_dr4_block = any(
            block_type == CANON_DR4_BLOCK_TYPE for block_type, _payload in canon_vrd_blocks(payload)
        )
        if not has_dr4_block:
            raise ValueError
    except ValueError as error:
        raise CanonVrdCr3AtomUpdateUnsupportedError(
            "UUID-Canon2 payload does not contain a CanonVRD DR4 trailer"
        ) from error
    return payload


def materialize_bounded_uuid_canon2_replacement(
    target_cr3_data: bytes,
    atom_plan: CanonVrdCr3AtomUpdatePlan,
) -> CanonVrdCr3BoundedReplacementResult:
    """Apply the source-backed UUID-Canon2 replacement shape that needs no CTBO repair.

    This is intentionally narrower than the full CR3 writer.  UUID-Canon2 is
    staged as WriteLast and CTBO offsets/sizes are repaired after mdat positions
    are known.  When the UUID already exists after a top-level mdat and the new
    atom has exactly the old atom size, positions and CTBO sizes are preserved,
    so a package-local in-place replacement is safe without fabricating the
    missing generic CR3 atom rebuild machinery.
    """
    replacement = atom_plan.replacement
    if replacement is None or replacement.old_range is None:
        raise CanonVrdCr3AtomUpdateUnsupportedError(
            "CanonVRD CR3 replacement requires an existing UUID-Canon2 atom"
        )
    old_range = replacement.old_range
    if replacement.size_delta != 0:
        raise CanonVrdCr3AtomUpdateUnsupportedError(
            "CanonVRD CR3 replacement changes UUID-Canon2 size and requires CTBO repair"
        )
    if len(replacement.new_atom) != old_range.size:
        raise CanonVrdCr3AtomUpdateUnsupportedError(
            "CanonVRD CR3 replacement length does not match existing atom"
        )
    if not uuid_canon2_is_write_last_positioned(target_cr3_data, old_range):
        raise CanonVrdCr3AtomUpdateUnsupportedError(
            "CanonVRD CR3 replacement requires existing UUID-Canon2 after mdat"
        )
    data = bytearray(target_cr3_data)
    data[old_range.offset : old_range.offset + old_range.size] = replacement.new_atom
    return CanonVrdCr3BoundedReplacementResult(
        data=bytes(data),
        replaced_offset=old_range.offset,
        replaced_size=old_range.size,
        preserved_size=True,
        source_reference_ids=(
            "quicktime.uuid_canon2.write_last",
            "write_quicktime.modified_uuid_size_update",
            "write_quicktime.cr3_ctbo_uuid_offset_fixup",
        ),
    )


def materialize_bounded_uuid_canon2_write_last_update(
    target_cr3_data: bytes,
    atom_plan: CanonVrdCr3AtomUpdatePlan,
) -> CanonVrdCr3BoundedWriteLastEmissionResult:
    """Emit a CR3 container update for an already-built UUID-Canon2 atom.

    UUID-Canon2 is emitted as WriteLast, so the shared bounded CR3 emitter owns
    the top-level ordering, media copy, and CTBO repair.  This CanonVRD seam
    only supplies the UUID-Canon2 atom materialized from DR4 data.
    """

    replacement = atom_plan.replacement
    if replacement is None:
        raise CanonVrdCr3AtomUpdateUnsupportedError(
            "CanonVRD CR3 WriteLast update requires a materialized UUID-Canon2 atom"
        )
    old_offset = replacement.old_range.offset if replacement.old_range is not None else None
    emission = emit_bounded_cr3_quicktime_stream(
        target_cr3_data,
        (
            Cr3AtomReplacement(
                new_atom=replacement.new_atom,
                old_atom_offset=old_offset,
                write_last=True,
            ),
        ),
    )
    if not emission.can_emit_bytes or emission.data is None:
        raise CanonVrdCr3AtomUpdateUnsupportedError(
            f"CanonVRD CR3 WriteLast update blocked by CR3 emitter: {emission.status}"
        )
    return CanonVrdCr3BoundedWriteLastEmissionResult(
        data=emission.data,
        action=atom_plan.action,
        replaced_offset=old_offset,
        write_last_atom_count=emission.write_last_atom_count,
        source_reference_ids=bounded_write_last_source_reference_ids(emission),
    )


def bounded_write_last_source_reference_ids(
    emission: Cr3BoundedEmissionResult,
) -> tuple[str, ...]:
    source_ids = [
        "quicktime.uuid_canon2.write_last",
        "write_quicktime.final_mdat_write_last_emission",
        "write_quicktime.cr3_ctbo_uuid_offset_fixup",
    ]
    for evidence_id in emission.evidence_ids:
        if evidence_id == "canon_raw.quicktime_xmp_uuid":
            source_ids.append("canon_raw.quicktime_uuid_selector")
            continue
        if evidence_id in {
            "canon_raw.cr3_quicktime_canon2",
            "canon_raw.cr3_final_emit",
            "canon_raw.cr3_ctbo_fixup",
        }:
            continue
        source_ids.append(evidence_id)
    return tuple(dict.fromkeys(source_ids))


def uuid_canon2_is_write_last_positioned(
    data: bytes,
    atom_range: CanonVrdCr3UuidAtomRange,
) -> bool:
    seen_mdat = False
    offset = 0
    while offset + UUID_ATOM_HEADER_SIZE <= len(data):
        atom_size = int.from_bytes(data[offset : offset + 4], "big")
        atom_type = data[offset + 4 : offset + 8]
        header_size = UUID_ATOM_HEADER_SIZE
        if atom_size == 1:
            if offset + 16 > len(data):
                return False
            atom_size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header_size = 16
        if atom_size < header_size or offset + atom_size > len(data):
            return False
        if offset == atom_range.offset:
            return seen_mdat
        if atom_type == b"mdat":
            seen_mdat = True
        offset += atom_size
    return False


def container_fixup_contract(
    boundary: CanonVrdCr3SetupAtomBoundary,
    extra_gates: tuple[CanonVrdCr3AtomGateCode, ...],
) -> CanonVrdCr3UuidFixupContract:
    gate_codes = unique_gate_codes(
        (
            *extra_gates,
            "requires_quicktime_write_last_emitter",
            "requires_cr3_ctbo_offset_size_fixup",
            "requires_cr3_mdat_offset_context",
        )
    )
    return CanonVrdCr3UuidFixupContract(
        length_fixups=boundary.length_fixups,
        can_apply_container_update=False,
        gate_codes=gate_codes,
    )


def container_fixup_contract_for_target(
    boundary: CanonVrdCr3SetupAtomBoundary,
    target_cr3_data: bytes,
    replacement: CanonVrdCr3UuidAtomReplacement | None,
    extra_gates: tuple[CanonVrdCr3AtomGateCode, ...],
) -> CanonVrdCr3UuidFixupContract:
    if replacement is None:
        return container_fixup_contract(boundary, extra_gates)
    old_offset = replacement.old_range.offset if replacement.old_range is not None else None
    emission = emit_bounded_cr3_quicktime_stream(
        target_cr3_data,
        (
            Cr3AtomReplacement(
                new_atom=replacement.new_atom,
                old_atom_offset=old_offset,
                write_last=True,
            ),
        ),
    )
    if not emission.can_emit_bytes:
        return container_fixup_contract(boundary, extra_gates)
    return CanonVrdCr3UuidFixupContract(
        length_fixups=boundary.length_fixups,
        can_apply_container_update=True,
        gate_codes=(),
    )


def unique_gate_codes(
    gate_codes: tuple[CanonVrdCr3AtomGateCode, ...],
) -> tuple[CanonVrdCr3AtomGateCode, ...]:
    seen: set[CanonVrdCr3AtomGateCode] = set()
    unique: list[CanonVrdCr3AtomGateCode] = []
    for gate_code in gate_codes:
        if gate_code in seen:
            continue
        seen.add(gate_code)
        unique.append(gate_code)
    return tuple(unique)
