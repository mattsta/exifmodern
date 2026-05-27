"""Source-grounded PGF image transaction plans.

ExifTool's PGF module reads a fixed 24-byte header, accepts version 0x36,
extracts little-endian header fields, optionally skips an indexed colour table,
and re-enters metadata parsing for a bounded embedded PNG metadata block.  This
planner mirrors those read responsibilities without adding a PGF writer.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

PGF_EXIFTOOL_HEADER_READ_SIZE = 24
PGF_SUPPORTED_VERSION = 0x36
PGF_INDEXED_COLOR_MODE = 2
PGF_INDEXED_COLOR_TABLE_SIZE = 1024
PGF_METADATA_REENTRY_LIMIT = 0x1000000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

type PgfPlanStatus = Literal["planned", "unsupported"]
type PgfRewriteOperation = Literal["insert", "replace", "delete"]
type PgfRewriteTarget = Literal[
    "header",
    "color_table",
    "embedded_png_metadata",
    "image_payload",
]
type PgfActionKind = Literal[
    "validate_signature_header",
    "extract_image_geometry",
    "extract_sample_layout",
    "extract_compression_header_fields",
    "preserve_fixed_header",
    "skip_indexed_color_table",
    "route_embedded_png_metadata",
    "preserve_post_header_metadata",
    "preserve_image_payload",
    "block_requested_rewrite",
]
type PgfEmissionGateCode = Literal[
    "truncated_pgf_header",
    "unsupported_pgf_signature",
    "unsupported_pgf_version",
    "invalid_pgf_header_size",
    "truncated_pgf_color_table",
    "truncated_pgf_metadata_block",
    "pgf_metadata_block_too_large_for_reentry",
    "rewrite_requested_requires_pgf_writer",
    "non_mutating_plan_requires_explicit_emission",
]
type PgfColorModeName = Literal[
    "Bitmap",
    "Grayscale",
    "Indexed",
    "RGB",
    "CMYK",
    "Multichannel",
    "Duotone",
    "Lab",
]
type PgfMetadataKind = Literal["embedded_png_metadata", "post_header_metadata"]

PGF_PM_SOURCE_PATH = "lib/Image/ExifTool/PGF.pm"

PGF_DESCRIPTION_SOURCE = "pgf_description"
PGF_MAIN_TABLE_SOURCE = "pgf_main_table"
PGF_HEADER_GATE_SOURCE = "pgf_header_gate"
PGF_VERSION_SOURCE = "pgf_version"
PGF_PROCESS_DIRECTORY_SOURCE = "pgf_process_directory"
PGF_POST_HEADER_LENGTH_SOURCE = "pgf_post_header_length"
PGF_INDEXED_COLOR_TABLE_SOURCE = "pgf_indexed_color_table"
PGF_EMBEDDED_METADATA_SOURCE = "pgf_embedded_metadata"
PGF_READ_ONLY_SOURCE = "pgf_read_only"

PGF_TRANSACTION_SOURCES = (
    PGF_DESCRIPTION_SOURCE,
    PGF_MAIN_TABLE_SOURCE,
    PGF_HEADER_GATE_SOURCE,
    PGF_VERSION_SOURCE,
    PGF_PROCESS_DIRECTORY_SOURCE,
    PGF_POST_HEADER_LENGTH_SOURCE,
    PGF_INDEXED_COLOR_TABLE_SOURCE,
    PGF_EMBEDDED_METADATA_SOURCE,
    PGF_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class PgfRewriteRequest:
    target: PgfRewriteTarget
    operation: PgfRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class PgfHeaderValidationPlan:
    signature: bytes
    version: int | None
    header_bytes_read: int
    reason: PgfEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class PgfImageGeometryPlan:
    image_width: int | None
    image_height: int | None
    pyramid_levels: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PgfSampleLayoutPlan:
    bits_per_pixel: int | None
    color_components: int | None
    color_mode: int | None
    color_mode_name: PgfColorModeName | None
    background_color: tuple[int, int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PgfCompressionPlan:
    quality: int | None
    pyramid_levels: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PgfPostHeaderPlan:
    header_size: int | None
    declared_post_header_length: int | None
    color_table_range: tuple[int, int] | None
    color_table_preserved: bool
    metadata_kind: PgfMetadataKind | None
    metadata_range: tuple[int, int] | None
    metadata_declared_length: int | None
    metadata_available_length: int
    reason: PgfEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def has_metadata(self) -> bool:
        return self.metadata_range is not None


@dataclass(frozen=True)
class PgfPayloadPlan:
    payload_range: tuple[int, int] | None
    action: Literal["preserve"]
    evidence_ids: tuple[str, ...]

    @property
    def payload_length(self) -> int | None:
        if self.payload_range is None:
            return None
        start, end = self.payload_range
        return end - start


@dataclass(frozen=True)
class PgfActionPlan:
    kind: PgfActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PgfOutputEmissionGate:
    code: PgfEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PgfImageTransactionPlan:
    status: PgfPlanStatus
    source_data: bytes
    header_validation: PgfHeaderValidationPlan
    image_geometry: PgfImageGeometryPlan
    sample_layout: PgfSampleLayoutPlan
    compression: PgfCompressionPlan
    post_header: PgfPostHeaderPlan
    image_payload: PgfPayloadPlan
    actions: tuple[PgfActionPlan, ...]
    output_emission_gates: tuple[PgfOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"PGF image transaction output is gated: {gate_codes}")
        return self.source_data


def build_pgf_image_transaction_plan(
    pgf_data: bytes,
    *,
    rewrite_requests: tuple[PgfRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> PgfImageTransactionPlan:
    """Build a preserve-only PGF image transaction plan from in-memory bytes."""

    gates: list[PgfOutputEmissionGate] = []
    header_validation = build_pgf_header_validation_plan(pgf_data)
    if header_validation.reason is not None:
        gates.append(
            PgfOutputEmissionGate(
                code=header_validation.reason,
                reason="Input does not satisfy ExifTool's PGF signature and version gate.",
                evidence_ids=header_validation.evidence_ids,
            )
        )

    image_geometry = build_pgf_image_geometry_plan(pgf_data, header_validation)
    sample_layout = build_pgf_sample_layout_plan(pgf_data, header_validation)
    compression = build_pgf_compression_plan(image_geometry, pgf_data, header_validation)
    post_header = build_pgf_post_header_plan(pgf_data, header_validation, sample_layout)
    if post_header.reason is not None:
        gates.append(
            PgfOutputEmissionGate(
                code=post_header.reason,
                reason="PGF post-header data cannot be handled with ExifTool-equivalent bounds.",
                evidence_ids=post_header.evidence_ids,
            )
        )

    image_payload = build_pgf_payload_plan(pgf_data, header_validation, post_header)
    actions = build_pgf_actions(
        header_validation,
        image_geometry,
        sample_layout,
        post_header,
        image_payload,
        rewrite_requests,
    )
    if rewrite_requests:
        gates.append(
            PgfOutputEmissionGate(
                code="rewrite_requested_requires_pgf_writer",
                reason="PGF.pm provides read behavior only, so requested rewrites are blocked.",
                evidence_ids=(PGF_READ_ONLY_SOURCE,),
            )
        )
    add_non_mutating_gate(gates, allow_output_emission)
    unique_gates = unique_emission_gates(tuple(gates))
    status: PgfPlanStatus = "unsupported" if structural_gate_present(unique_gates) else "planned"
    sources = unique_sources(
        (
            *PGF_TRANSACTION_SOURCES,
            *header_validation.evidence_ids,
            *image_geometry.evidence_ids,
            *sample_layout.evidence_ids,
            *compression.evidence_ids,
            *post_header.evidence_ids,
            *image_payload.evidence_ids,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in unique_gates for source in gate.evidence_ids),
        )
    )
    return PgfImageTransactionPlan(
        status=status,
        source_data=pgf_data,
        header_validation=header_validation,
        image_geometry=image_geometry,
        sample_layout=sample_layout,
        compression=compression,
        post_header=post_header,
        image_payload=image_payload,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=sources,
    )


def build_pgf_header_validation_plan(pgf_data: bytes) -> PgfHeaderValidationPlan:
    header_bytes_read = min(len(pgf_data), PGF_EXIFTOOL_HEADER_READ_SIZE)
    signature = pgf_data[:3]
    version = pgf_data[3] if len(pgf_data) > 3 else None
    if len(pgf_data) < PGF_EXIFTOOL_HEADER_READ_SIZE:
        return PgfHeaderValidationPlan(
            signature=signature,
            version=version,
            header_bytes_read=header_bytes_read,
            reason="truncated_pgf_header",
            evidence_ids=(PGF_HEADER_GATE_SOURCE,),
        )
    if signature != b"PGF":
        return PgfHeaderValidationPlan(
            signature=signature,
            version=version,
            header_bytes_read=header_bytes_read,
            reason="unsupported_pgf_signature",
            evidence_ids=(PGF_HEADER_GATE_SOURCE,),
        )
    if version != PGF_SUPPORTED_VERSION:
        return PgfHeaderValidationPlan(
            signature=signature,
            version=version,
            header_bytes_read=header_bytes_read,
            reason="unsupported_pgf_version",
            evidence_ids=(PGF_HEADER_GATE_SOURCE, PGF_VERSION_SOURCE),
        )
    return PgfHeaderValidationPlan(
        signature=signature,
        version=version,
        header_bytes_read=header_bytes_read,
        reason=None,
        evidence_ids=(PGF_HEADER_GATE_SOURCE, PGF_VERSION_SOURCE),
    )


def build_pgf_image_geometry_plan(
    pgf_data: bytes,
    validation: PgfHeaderValidationPlan,
) -> PgfImageGeometryPlan:
    if not validation.is_exiftool_accepted:
        return PgfImageGeometryPlan(
            image_width=None,
            image_height=None,
            pyramid_levels=None,
            evidence_ids=(PGF_MAIN_TABLE_SOURCE,),
        )
    return PgfImageGeometryPlan(
        image_width=read_u32le(pgf_data, 8),
        image_height=read_u32le(pgf_data, 12),
        pyramid_levels=pgf_data[16],
        evidence_ids=(PGF_MAIN_TABLE_SOURCE, PGF_PROCESS_DIRECTORY_SOURCE),
    )


def build_pgf_sample_layout_plan(
    pgf_data: bytes,
    validation: PgfHeaderValidationPlan,
) -> PgfSampleLayoutPlan:
    if not validation.is_exiftool_accepted:
        return PgfSampleLayoutPlan(
            bits_per_pixel=None,
            color_components=None,
            color_mode=None,
            color_mode_name=None,
            background_color=None,
            evidence_ids=(PGF_MAIN_TABLE_SOURCE,),
        )
    color_mode = pgf_data[20]
    return PgfSampleLayoutPlan(
        bits_per_pixel=pgf_data[18],
        color_components=pgf_data[19],
        color_mode=color_mode,
        color_mode_name=pgf_color_mode_name(color_mode),
        background_color=(pgf_data[21], pgf_data[22], pgf_data[23]),
        evidence_ids=(PGF_MAIN_TABLE_SOURCE, PGF_PROCESS_DIRECTORY_SOURCE),
    )


def build_pgf_compression_plan(
    geometry: PgfImageGeometryPlan,
    pgf_data: bytes,
    validation: PgfHeaderValidationPlan,
) -> PgfCompressionPlan:
    if not validation.is_exiftool_accepted:
        return PgfCompressionPlan(
            quality=None,
            pyramid_levels=None,
            evidence_ids=(PGF_MAIN_TABLE_SOURCE,),
        )
    return PgfCompressionPlan(
        quality=pgf_data[17],
        pyramid_levels=geometry.pyramid_levels,
        evidence_ids=(PGF_MAIN_TABLE_SOURCE, PGF_PROCESS_DIRECTORY_SOURCE),
    )


def build_pgf_post_header_plan(
    pgf_data: bytes,
    validation: PgfHeaderValidationPlan,
    sample_layout: PgfSampleLayoutPlan,
) -> PgfPostHeaderPlan:
    if not validation.is_exiftool_accepted:
        return PgfPostHeaderPlan(
            header_size=None,
            declared_post_header_length=None,
            color_table_range=None,
            color_table_preserved=False,
            metadata_kind=None,
            metadata_range=None,
            metadata_declared_length=None,
            metadata_available_length=0,
            reason=None,
            evidence_ids=(PGF_POST_HEADER_LENGTH_SOURCE,),
        )

    header_size = read_u32le(pgf_data, 4)
    declared_length = header_size - 16
    if declared_length < 0:
        return PgfPostHeaderPlan(
            header_size=header_size,
            declared_post_header_length=declared_length,
            color_table_range=None,
            color_table_preserved=False,
            metadata_kind=None,
            metadata_range=None,
            metadata_declared_length=None,
            metadata_available_length=0,
            reason="invalid_pgf_header_size",
            evidence_ids=(PGF_POST_HEADER_LENGTH_SOURCE,),
        )

    metadata_offset = PGF_EXIFTOOL_HEADER_READ_SIZE
    metadata_length = declared_length
    color_table_range: tuple[int, int] | None = None
    color_table_preserved = False
    sources: tuple[str, ...] = (PGF_POST_HEADER_LENGTH_SOURCE,)
    if sample_layout.color_mode == PGF_INDEXED_COLOR_MODE:
        sources = (PGF_POST_HEADER_LENGTH_SOURCE, PGF_INDEXED_COLOR_TABLE_SOURCE)
        color_table_end = PGF_EXIFTOOL_HEADER_READ_SIZE + PGF_INDEXED_COLOR_TABLE_SIZE
        if len(pgf_data) < color_table_end:
            return PgfPostHeaderPlan(
                header_size=header_size,
                declared_post_header_length=declared_length,
                color_table_range=(PGF_EXIFTOOL_HEADER_READ_SIZE, len(pgf_data)),
                color_table_preserved=False,
                metadata_kind=None,
                metadata_range=None,
                metadata_declared_length=0,
                metadata_available_length=0,
                reason="truncated_pgf_color_table",
                evidence_ids=sources,
            )
        color_table_range = (PGF_EXIFTOOL_HEADER_READ_SIZE, color_table_end)
        color_table_preserved = True
        metadata_offset = color_table_end
        metadata_length = declared_length - PGF_INDEXED_COLOR_TABLE_SIZE

    if metadata_length <= 0:
        return PgfPostHeaderPlan(
            header_size=header_size,
            declared_post_header_length=declared_length,
            color_table_range=color_table_range,
            color_table_preserved=color_table_preserved,
            metadata_kind=None,
            metadata_range=None,
            metadata_declared_length=metadata_length,
            metadata_available_length=max(0, len(pgf_data) - metadata_offset),
            reason=None,
            evidence_ids=sources,
        )
    if metadata_length >= PGF_METADATA_REENTRY_LIMIT:
        return PgfPostHeaderPlan(
            header_size=header_size,
            declared_post_header_length=declared_length,
            color_table_range=color_table_range,
            color_table_preserved=color_table_preserved,
            metadata_kind=None,
            metadata_range=None,
            metadata_declared_length=metadata_length,
            metadata_available_length=max(0, len(pgf_data) - metadata_offset),
            reason="pgf_metadata_block_too_large_for_reentry",
            evidence_ids=(*sources, PGF_EMBEDDED_METADATA_SOURCE),
        )

    available_length = max(0, len(pgf_data) - metadata_offset)
    if available_length < metadata_length:
        return PgfPostHeaderPlan(
            header_size=header_size,
            declared_post_header_length=declared_length,
            color_table_range=color_table_range,
            color_table_preserved=color_table_preserved,
            metadata_kind=None,
            metadata_range=(metadata_offset, len(pgf_data)),
            metadata_declared_length=metadata_length,
            metadata_available_length=available_length,
            reason="truncated_pgf_metadata_block",
            evidence_ids=(*sources, PGF_EMBEDDED_METADATA_SOURCE),
        )

    metadata_range = (metadata_offset, metadata_offset + metadata_length)
    metadata = pgf_data[metadata_range[0] : metadata_range[1]]
    metadata_kind: PgfMetadataKind = (
        "embedded_png_metadata" if metadata.startswith(PNG_SIGNATURE) else "post_header_metadata"
    )
    return PgfPostHeaderPlan(
        header_size=header_size,
        declared_post_header_length=declared_length,
        color_table_range=color_table_range,
        color_table_preserved=color_table_preserved,
        metadata_kind=metadata_kind,
        metadata_range=metadata_range,
        metadata_declared_length=metadata_length,
        metadata_available_length=available_length,
        reason=None,
        evidence_ids=(*sources, PGF_EMBEDDED_METADATA_SOURCE),
    )


def build_pgf_payload_plan(
    pgf_data: bytes,
    validation: PgfHeaderValidationPlan,
    post_header: PgfPostHeaderPlan,
) -> PgfPayloadPlan:
    if not validation.is_exiftool_accepted:
        return PgfPayloadPlan(
            payload_range=None,
            action="preserve",
            evidence_ids=(PGF_READ_ONLY_SOURCE,),
        )
    payload_start = PGF_EXIFTOOL_HEADER_READ_SIZE
    if post_header.color_table_range is not None and post_header.color_table_preserved:
        payload_start = post_header.color_table_range[1]
    if post_header.metadata_range is not None and post_header.reason is None:
        payload_start = post_header.metadata_range[1]
    payload_start = min(payload_start, len(pgf_data))
    return PgfPayloadPlan(
        payload_range=(payload_start, len(pgf_data)),
        action="preserve",
        evidence_ids=(PGF_READ_ONLY_SOURCE,),
    )


def build_pgf_actions(
    validation: PgfHeaderValidationPlan,
    geometry: PgfImageGeometryPlan,
    sample_layout: PgfSampleLayoutPlan,
    post_header: PgfPostHeaderPlan,
    payload: PgfPayloadPlan,
    rewrite_requests: tuple[PgfRewriteRequest, ...],
) -> tuple[PgfActionPlan, ...]:
    actions: list[PgfActionPlan] = [
        PgfActionPlan(
            kind="validate_signature_header",
            target="pgf_header",
            byte_range=(0, validation.header_bytes_read),
            reason="Mirror ExifTool's fixed 24-byte PGF acceptance gate.",
            evidence_ids=(PGF_HEADER_GATE_SOURCE, PGF_VERSION_SOURCE),
        )
    ]
    if validation.is_exiftool_accepted:
        actions.extend(
            (
                PgfActionPlan(
                    kind="extract_image_geometry",
                    target="dimensions_and_levels",
                    byte_range=(8, 17),
                    reason="Extract ExifTool's width, height, and pyramid level fields.",
                    evidence_ids=geometry.evidence_ids,
                ),
                PgfActionPlan(
                    kind="extract_compression_header_fields",
                    target="quality",
                    byte_range=(17, 18),
                    reason="Extract ExifTool's PGF Quality header field.",
                    evidence_ids=(PGF_MAIN_TABLE_SOURCE,),
                ),
                PgfActionPlan(
                    kind="extract_sample_layout",
                    target="bits_components_color",
                    byte_range=(18, 24),
                    reason=(
                        "Extract bits per pixel, component count, color mode, and background color."
                    ),
                    evidence_ids=sample_layout.evidence_ids,
                ),
                PgfActionPlan(
                    kind="preserve_fixed_header",
                    target="pgf_header",
                    byte_range=(0, PGF_EXIFTOOL_HEADER_READ_SIZE),
                    reason="Keep the fixed PGF header unchanged.",
                    evidence_ids=(PGF_READ_ONLY_SOURCE,),
                ),
            )
        )
    if post_header.color_table_range is not None:
        actions.append(
            PgfActionPlan(
                kind="skip_indexed_color_table",
                target="indexed_color_table",
                byte_range=post_header.color_table_range,
                reason="Preserve the indexed colour table that ExifTool skips before metadata.",
                evidence_ids=(PGF_INDEXED_COLOR_TABLE_SOURCE,),
            )
        )
    if post_header.metadata_range is not None:
        action_kind: PgfActionKind = (
            "route_embedded_png_metadata"
            if post_header.metadata_kind == "embedded_png_metadata"
            else "preserve_post_header_metadata"
        )
        actions.append(
            PgfActionPlan(
                kind=action_kind,
                target="post_header_metadata",
                byte_range=post_header.metadata_range,
                reason="Represent ExifTool's bounded post-header metadata extraction attempt.",
                evidence_ids=(PGF_EMBEDDED_METADATA_SOURCE,),
            )
        )
    if payload.payload_range is not None:
        actions.append(
            PgfActionPlan(
                kind="preserve_image_payload",
                target="image_payload",
                byte_range=payload.payload_range,
                reason="Keep the remaining PGF image payload unchanged.",
                evidence_ids=(PGF_READ_ONLY_SOURCE,),
            )
        )
    for request in rewrite_requests:
        actions.append(
            PgfActionPlan(
                kind="block_requested_rewrite",
                target=f"{request.operation}:{request.target}",
                byte_range=None,
                reason="PGF.pm does not provide a writer for this requested mutation.",
                evidence_ids=(PGF_READ_ONLY_SOURCE,),
            )
        )
    return tuple(actions)


def add_non_mutating_gate(
    gates: list[PgfOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        PgfOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="PGF transaction plans are preserve-only unless output emission is explicit.",
            evidence_ids=(PGF_READ_ONLY_SOURCE,),
        )
    )


def structural_gate_present(gates: tuple[PgfOutputEmissionGate, ...]) -> bool:
    non_structural_codes = {
        "rewrite_requested_requires_pgf_writer",
        "non_mutating_plan_requires_explicit_emission",
        "pgf_metadata_block_too_large_for_reentry",
    }
    return any(gate.code not in non_structural_codes for gate in gates)


def unique_emission_gates(
    gates: tuple[PgfOutputEmissionGate, ...],
) -> tuple[PgfOutputEmissionGate, ...]:
    seen: set[PgfEmissionGateCode] = set()
    unique: list[PgfOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def pgf_color_mode_name(color_mode: int) -> PgfColorModeName | None:
    names: dict[int, PgfColorModeName] = {
        0: "Bitmap",
        1: "Grayscale",
        2: "Indexed",
        3: "RGB",
        4: "CMYK",
        7: "Multichannel",
        8: "Duotone",
        9: "Lab",
    }
    return names.get(color_mode)


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


plan_pgf_image_transaction = build_pgf_image_transaction_plan
