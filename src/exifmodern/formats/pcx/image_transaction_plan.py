"""Source-grounded, non-mutating PCX image transaction plans.

ExifTool's PCX reader accepts files from the first 0x50 bytes, extracts the
header fields declared in PCX.pm, and has no PCX writer. This planner preserves
the original byte stream and records the full PCX header, raster stream, and
optional EOF VGA palette ranges without rewriting them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

PCX_EXIFTOOL_READ_SIZE = 0x50
PCX_HEADER_SIZE = 128
PCX_VGA_PALETTE_SIZE = 769
PCX_VGA_PALETTE_MARKER = 0x0C
PCX_MANUFACTURER_ZSOFT = 10
PCX_ENCODING_RLE = 1
PCX_SUPPORTED_VERSIONS = frozenset({0, 1, 2, 3, 4, 5})
PCX_SUPPORTED_BITS_PER_PIXEL = frozenset({1, 2, 4, 8})
PCX_SUPPORTED_COLOR_MODES = frozenset({0, 1, 2})

type PcxPlanStatus = Literal["planned", "unsupported"]
type PcxActionKind = Literal[
    "validate_header_gate",
    "extract_image_bounds",
    "extract_resolution",
    "extract_raster_layout",
    "preserve_header",
    "preserve_header_palette",
    "preserve_image_data",
    "preserve_vga_palette",
    "block_requested_rewrite",
]
type PcxEmissionGateCode = Literal[
    "truncated_exiftool_pcx_header",
    "unsupported_pcx_manufacturer",
    "unsupported_pcx_version",
    "unsupported_pcx_compression",
    "unsupported_pcx_bits_per_pixel",
    "unsupported_pcx_color_mode",
    "truncated_pcx_header",
    "missing_pcx_image_data",
    "rewrite_requested_requires_pcx_writer",
    "non_mutating_plan_requires_explicit_emission",
]
type PcxRewriteOperation = Literal["insert", "replace", "delete"]
type PcxRewriteTarget = Literal["header", "image_data", "header_palette", "vga_palette"]
type PcxSoftwarePaletteExpectation = Literal[
    "unspecified",
    "pc_paintbrush_2_8_with_palette",
    "pc_paintbrush_2_8_without_palette",
]

PCX_PM_SOURCE_PATH = "lib/Image/ExifTool/PCX.pm"

PCX_MAIN_TABLE_SOURCE = "pcx_main_table"
PCX_ACCEPTANCE_GATE_SOURCE = "pcx_acceptance_gate"
PCX_ENDIAN_AND_BINARY_SOURCE = "pcx_endian_and_binary"
PCX_READ_ONLY_SOURCE = "pcx_read_only"

PCX_TRANSACTION_SOURCES = (
    PCX_MAIN_TABLE_SOURCE,
    PCX_ACCEPTANCE_GATE_SOURCE,
    PCX_ENDIAN_AND_BINARY_SOURCE,
    PCX_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class PcxRewriteRequest:
    target: PcxRewriteTarget
    operation: PcxRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class PcxHeaderValidationPlan:
    manufacturer: int | None
    manufacturer_name: str | None
    version: int | None
    software_name: str | None
    encoding: int | None
    encoding_name: str | None
    bits_per_pixel: int | None
    color_mode: int | None
    color_mode_description: str | None
    header_bytes_read: int
    reason: PcxEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class PcxImageBoundsPlan:
    left_margin: int | None
    top_margin: int | None
    right_margin: int | None
    bottom_margin: int | None
    image_width: int | None
    image_height: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcxResolutionPlan:
    x_resolution: int | None
    y_resolution: int | None
    screen_width: int | None
    screen_height: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcxRasterLayoutPlan:
    color_planes: int | None
    bytes_per_line: int | None
    decoded_scan_line_bytes: int | None
    compression: Literal["rle"] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcxPalettePlan:
    header_palette_range: tuple[int, int] | None
    header_palette_size: int
    color_mode: int | None
    color_mode_description: str | None
    software_palette_expectation: PcxSoftwarePaletteExpectation
    vga_palette_marker_offset: int | None
    vga_palette_range: tuple[int, int] | None
    vga_palette_size: int
    evidence_ids: tuple[str, ...]

    @property
    def has_vga_palette(self) -> bool:
        return self.vga_palette_range is not None


@dataclass(frozen=True)
class PcxBoundaryPlan:
    exiftool_header_range: tuple[int, int]
    pcx_header_range: tuple[int, int] | None
    image_data_range: tuple[int, int] | None
    vga_palette_range: tuple[int, int] | None
    trailing_data_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]

    @property
    def image_data_size(self) -> int:
        if self.image_data_range is None:
            return 0
        start, end = self.image_data_range
        return end - start


@dataclass(frozen=True)
class PcxActionPlan:
    kind: PcxActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcxOutputEmissionGate:
    code: PcxEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PcxImageTransactionPlan:
    status: PcxPlanStatus
    source_data: bytes
    header_validation: PcxHeaderValidationPlan
    image_bounds: PcxImageBoundsPlan
    resolution: PcxResolutionPlan
    raster_layout: PcxRasterLayoutPlan
    palette: PcxPalettePlan
    boundaries: PcxBoundaryPlan
    actions: tuple[PcxActionPlan, ...]
    output_emission_gates: tuple[PcxOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"PCX image transaction output is gated: {gate_codes}")
        return self.source_data


def build_pcx_image_transaction_plan(
    pcx_data: bytes,
    *,
    rewrite_requests: tuple[PcxRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> PcxImageTransactionPlan:
    """Build a preserve-only PCX image transaction plan from in-memory bytes."""

    gates: list[PcxOutputEmissionGate] = []
    header_validation = build_pcx_header_validation_plan(pcx_data)
    if header_validation.reason is not None:
        gates.append(
            PcxOutputEmissionGate(
                code=header_validation.reason,
                reason="Input does not satisfy ExifTool's PCX header acceptance gate.",
                evidence_ids=header_validation.evidence_ids,
            )
        )

    if len(pcx_data) < PCX_HEADER_SIZE and header_validation.reason is None:
        gates.append(
            PcxOutputEmissionGate(
                code="truncated_pcx_header",
                reason="Input passed ExifTool's 0x50-byte gate but lacks a full PCX header.",
                evidence_ids=(PCX_ACCEPTANCE_GATE_SOURCE,),
            )
        )
    if len(pcx_data) == PCX_HEADER_SIZE and header_validation.reason is None:
        gates.append(
            PcxOutputEmissionGate(
                code="missing_pcx_image_data",
                reason="Input has a full PCX header but no raster bytes to preserve.",
                evidence_ids=(PCX_READ_ONLY_SOURCE,),
            )
        )

    image_bounds = build_pcx_image_bounds_plan(pcx_data, header_validation)
    resolution = build_pcx_resolution_plan(pcx_data, header_validation)
    raster_layout = build_pcx_raster_layout_plan(pcx_data, header_validation)
    boundaries = build_pcx_boundary_plan(pcx_data)
    palette = build_pcx_palette_plan(pcx_data, header_validation, boundaries)
    actions = build_pcx_actions(
        boundaries,
        rewrite_requests,
        header_validation.is_exiftool_accepted,
    )
    if rewrite_requests:
        gates.append(
            PcxOutputEmissionGate(
                code="rewrite_requested_requires_pcx_writer",
                reason="PCX.pm provides read behavior only, so requested rewrites are blocked.",
                evidence_ids=(PCX_READ_ONLY_SOURCE,),
            )
        )
    add_non_mutating_gate(gates, allow_output_emission)
    unique_gates = unique_emission_gates(tuple(gates))
    status: PcxPlanStatus = "unsupported" if structural_gate_present(unique_gates) else "planned"
    sources = unique_sources(
        (
            *PCX_TRANSACTION_SOURCES,
            *header_validation.evidence_ids,
            *image_bounds.evidence_ids,
            *resolution.evidence_ids,
            *raster_layout.evidence_ids,
            *palette.evidence_ids,
            *boundaries.evidence_ids,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in unique_gates for source in gate.evidence_ids),
        )
    )
    return PcxImageTransactionPlan(
        status=status,
        source_data=pcx_data,
        header_validation=header_validation,
        image_bounds=image_bounds,
        resolution=resolution,
        raster_layout=raster_layout,
        palette=palette,
        boundaries=boundaries,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=sources,
    )


def build_pcx_header_validation_plan(pcx_data: bytes) -> PcxHeaderValidationPlan:
    header_bytes_read = min(len(pcx_data), PCX_EXIFTOOL_READ_SIZE)
    if len(pcx_data) < PCX_EXIFTOOL_READ_SIZE:
        return PcxHeaderValidationPlan(
            manufacturer=pcx_data[0] if len(pcx_data) > 0 else None,
            manufacturer_name=None,
            version=pcx_data[1] if len(pcx_data) > 1 else None,
            software_name=None,
            encoding=pcx_data[2] if len(pcx_data) > 2 else None,
            encoding_name=None,
            bits_per_pixel=pcx_data[3] if len(pcx_data) > 3 else None,
            color_mode=pcx_data[0x44] if len(pcx_data) > 0x44 else None,
            color_mode_description=None,
            header_bytes_read=header_bytes_read,
            reason="truncated_exiftool_pcx_header",
            evidence_ids=(PCX_ACCEPTANCE_GATE_SOURCE,),
        )

    manufacturer = pcx_data[0]
    version = pcx_data[1]
    encoding = pcx_data[2]
    bits_per_pixel = pcx_data[3]
    color_mode = pcx_data[0x44]
    reason = pcx_header_gate_reason(manufacturer, version, encoding, bits_per_pixel, color_mode)
    return PcxHeaderValidationPlan(
        manufacturer=manufacturer,
        manufacturer_name="ZSoft" if manufacturer == PCX_MANUFACTURER_ZSOFT else None,
        version=version,
        software_name=software_name(version),
        encoding=encoding,
        encoding_name="RLE" if encoding == PCX_ENCODING_RLE else None,
        bits_per_pixel=bits_per_pixel,
        color_mode=color_mode,
        color_mode_description=color_mode_description(color_mode),
        header_bytes_read=header_bytes_read,
        reason=reason,
        evidence_ids=(PCX_ACCEPTANCE_GATE_SOURCE, PCX_MAIN_TABLE_SOURCE),
    )


def build_pcx_image_bounds_plan(
    pcx_data: bytes,
    validation: PcxHeaderValidationPlan,
) -> PcxImageBoundsPlan:
    if len(pcx_data) < PCX_EXIFTOOL_READ_SIZE or not validation.is_exiftool_accepted:
        return PcxImageBoundsPlan(
            left_margin=None,
            top_margin=None,
            right_margin=None,
            bottom_margin=None,
            image_width=None,
            image_height=None,
            evidence_ids=(PCX_MAIN_TABLE_SOURCE,),
        )
    left_margin = read_u16le(pcx_data, 0x04)
    top_margin = read_u16le(pcx_data, 0x06)
    right_margin = read_u16le(pcx_data, 0x08)
    bottom_margin = read_u16le(pcx_data, 0x0A)
    return PcxImageBoundsPlan(
        left_margin=left_margin,
        top_margin=top_margin,
        right_margin=right_margin,
        bottom_margin=bottom_margin,
        image_width=right_margin - left_margin + 1,
        image_height=bottom_margin - top_margin + 1,
        evidence_ids=(PCX_MAIN_TABLE_SOURCE, PCX_ENDIAN_AND_BINARY_SOURCE),
    )


def build_pcx_resolution_plan(
    pcx_data: bytes,
    validation: PcxHeaderValidationPlan,
) -> PcxResolutionPlan:
    if len(pcx_data) < PCX_EXIFTOOL_READ_SIZE or not validation.is_exiftool_accepted:
        return PcxResolutionPlan(
            x_resolution=None,
            y_resolution=None,
            screen_width=None,
            screen_height=None,
            evidence_ids=(PCX_MAIN_TABLE_SOURCE,),
        )
    screen_width = raw_nonzero_u16le(pcx_data, 0x46)
    screen_height = raw_nonzero_u16le(pcx_data, 0x48)
    return PcxResolutionPlan(
        x_resolution=read_u16le(pcx_data, 0x0C),
        y_resolution=read_u16le(pcx_data, 0x0E),
        screen_width=screen_width,
        screen_height=screen_height,
        evidence_ids=(PCX_MAIN_TABLE_SOURCE, PCX_ENDIAN_AND_BINARY_SOURCE),
    )


def build_pcx_raster_layout_plan(
    pcx_data: bytes,
    validation: PcxHeaderValidationPlan,
) -> PcxRasterLayoutPlan:
    if len(pcx_data) < PCX_EXIFTOOL_READ_SIZE or not validation.is_exiftool_accepted:
        return PcxRasterLayoutPlan(
            color_planes=None,
            bytes_per_line=None,
            decoded_scan_line_bytes=None,
            compression=None,
            evidence_ids=(PCX_MAIN_TABLE_SOURCE,),
        )
    color_planes = pcx_data[0x41]
    bytes_per_line = read_u16le(pcx_data, 0x42)
    return PcxRasterLayoutPlan(
        color_planes=color_planes,
        bytes_per_line=bytes_per_line,
        decoded_scan_line_bytes=color_planes * bytes_per_line,
        compression="rle",
        evidence_ids=(PCX_MAIN_TABLE_SOURCE, PCX_ENDIAN_AND_BINARY_SOURCE),
    )


def build_pcx_boundary_plan(pcx_data: bytes) -> PcxBoundaryPlan:
    exiftool_header_range = (0, min(len(pcx_data), PCX_EXIFTOOL_READ_SIZE))
    pcx_header_range: tuple[int, int] | None = None
    image_data_range: tuple[int, int] | None = None
    vga_palette_range = find_vga_palette_range(pcx_data)
    trailing_data_range: tuple[int, int] | None = None
    if len(pcx_data) >= PCX_HEADER_SIZE:
        pcx_header_range = (0, PCX_HEADER_SIZE)
        image_data_end = vga_palette_range[0] if vga_palette_range is not None else len(pcx_data)
        image_data_range = (PCX_HEADER_SIZE, image_data_end)
    elif len(pcx_data) > PCX_EXIFTOOL_READ_SIZE:
        trailing_data_range = (PCX_EXIFTOOL_READ_SIZE, len(pcx_data))
    return PcxBoundaryPlan(
        exiftool_header_range=exiftool_header_range,
        pcx_header_range=pcx_header_range,
        image_data_range=image_data_range,
        vga_palette_range=vga_palette_range,
        trailing_data_range=trailing_data_range,
        evidence_ids=(PCX_ACCEPTANCE_GATE_SOURCE, PCX_READ_ONLY_SOURCE),
    )


def build_pcx_palette_plan(
    pcx_data: bytes,
    validation: PcxHeaderValidationPlan,
    boundaries: PcxBoundaryPlan,
) -> PcxPalettePlan:
    header_palette_range = (0x10, 0x40) if len(pcx_data) >= PCX_EXIFTOOL_READ_SIZE else None
    vga_palette_marker_offset: int | None = None
    vga_palette_size = 0
    if boundaries.vga_palette_range is not None:
        vga_palette_marker_offset = boundaries.vga_palette_range[0]
        vga_palette_size = boundaries.vga_palette_range[1] - boundaries.vga_palette_range[0]
    return PcxPalettePlan(
        header_palette_range=header_palette_range,
        header_palette_size=0 if header_palette_range is None else 0x30,
        color_mode=validation.color_mode,
        color_mode_description=validation.color_mode_description,
        software_palette_expectation=software_palette_expectation(validation.version),
        vga_palette_marker_offset=vga_palette_marker_offset,
        vga_palette_range=boundaries.vga_palette_range,
        vga_palette_size=vga_palette_size,
        evidence_ids=(PCX_MAIN_TABLE_SOURCE, PCX_READ_ONLY_SOURCE),
    )


def build_pcx_actions(
    boundaries: PcxBoundaryPlan,
    rewrite_requests: tuple[PcxRewriteRequest, ...],
    header_accepted: bool,
) -> tuple[PcxActionPlan, ...]:
    actions: list[PcxActionPlan] = [
        PcxActionPlan(
            kind="validate_header_gate",
            target="pcx_header",
            byte_range=boundaries.exiftool_header_range,
            reason="Mirror ExifTool's fixed first-0x50-byte PCX acceptance gate.",
            evidence_ids=(PCX_ACCEPTANCE_GATE_SOURCE,),
        )
    ]
    if header_accepted:
        actions.extend(
            (
                PcxActionPlan(
                    kind="extract_image_bounds",
                    target="margins",
                    byte_range=(0x04, 0x0C),
                    reason="Extract ExifTool's left/top-adjusted image dimensions.",
                    evidence_ids=(PCX_MAIN_TABLE_SOURCE,),
                ),
                PcxActionPlan(
                    kind="extract_resolution",
                    target="resolution",
                    byte_range=(0x0C, 0x10),
                    reason="Extract ExifTool's X/Y resolution fields.",
                    evidence_ids=(PCX_MAIN_TABLE_SOURCE,),
                ),
                PcxActionPlan(
                    kind="extract_raster_layout",
                    target="planes_and_stride",
                    byte_range=(0x41, 0x44),
                    reason="Extract ExifTool's color-plane and bytes-per-line fields.",
                    evidence_ids=(PCX_MAIN_TABLE_SOURCE,),
                ),
            )
        )
    if boundaries.pcx_header_range is not None:
        actions.append(
            PcxActionPlan(
                kind="preserve_header",
                target="pcx_header",
                byte_range=boundaries.pcx_header_range,
                reason="Keep the full PCX header unchanged.",
                evidence_ids=(PCX_READ_ONLY_SOURCE,),
            )
        )
    actions.append(
        PcxActionPlan(
            kind="preserve_header_palette",
            target="header_palette",
            byte_range=(0x10, 0x40) if header_accepted else None,
            reason="Preserve the in-header palette bytes covered by ExifTool's header read.",
            evidence_ids=(PCX_ACCEPTANCE_GATE_SOURCE, PCX_MAIN_TABLE_SOURCE),
        )
    )
    if boundaries.image_data_range is not None:
        actions.append(
            PcxActionPlan(
                kind="preserve_image_data",
                target="image_data",
                byte_range=boundaries.image_data_range,
                reason="Keep the encoded PCX raster stream unchanged.",
                evidence_ids=(PCX_READ_ONLY_SOURCE,),
            )
        )
    if boundaries.vga_palette_range is not None:
        actions.append(
            PcxActionPlan(
                kind="preserve_vga_palette",
                target="vga_palette",
                byte_range=boundaries.vga_palette_range,
                reason="Keep the optional EOF VGA palette block unchanged.",
                evidence_ids=(PCX_READ_ONLY_SOURCE,),
            )
        )
    for request in rewrite_requests:
        actions.append(
            PcxActionPlan(
                kind="block_requested_rewrite",
                target=f"{request.operation}:{request.target}",
                byte_range=None,
                reason="PCX.pm does not provide a writer for this requested mutation.",
                evidence_ids=(PCX_READ_ONLY_SOURCE,),
            )
        )
    return tuple(actions)


def pcx_header_gate_reason(
    manufacturer: int,
    version: int,
    encoding: int,
    bits_per_pixel: int,
    color_mode: int,
) -> PcxEmissionGateCode | None:
    if manufacturer != PCX_MANUFACTURER_ZSOFT:
        return "unsupported_pcx_manufacturer"
    if version not in PCX_SUPPORTED_VERSIONS:
        return "unsupported_pcx_version"
    if encoding != PCX_ENCODING_RLE:
        return "unsupported_pcx_compression"
    if bits_per_pixel not in PCX_SUPPORTED_BITS_PER_PIXEL:
        return "unsupported_pcx_bits_per_pixel"
    if color_mode not in PCX_SUPPORTED_COLOR_MODES:
        return "unsupported_pcx_color_mode"
    return None


def find_vga_palette_range(pcx_data: bytes) -> tuple[int, int] | None:
    if len(pcx_data) < PCX_HEADER_SIZE + PCX_VGA_PALETTE_SIZE:
        return None
    marker_offset = len(pcx_data) - PCX_VGA_PALETTE_SIZE
    if pcx_data[marker_offset] != PCX_VGA_PALETTE_MARKER:
        return None
    return (marker_offset, len(pcx_data))


def add_non_mutating_gate(
    gates: list[PcxOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        PcxOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="PCX transaction plans are preserve-only unless output emission is explicit.",
            evidence_ids=(PCX_READ_ONLY_SOURCE,),
        )
    )


def structural_gate_present(gates: tuple[PcxOutputEmissionGate, ...]) -> bool:
    non_structural_codes = {
        "rewrite_requested_requires_pcx_writer",
        "non_mutating_plan_requires_explicit_emission",
    }
    return any(gate.code not in non_structural_codes for gate in gates)


def unique_emission_gates(
    gates: tuple[PcxOutputEmissionGate, ...],
) -> tuple[PcxOutputEmissionGate, ...]:
    seen: set[PcxEmissionGateCode] = set()
    unique: list[PcxOutputEmissionGate] = []
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


def software_name(version: int) -> str | None:
    names = {
        0: "PC Paintbrush 2.5",
        2: "PC Paintbrush 2.8 (with palette)",
        3: "PC Paintbrush 2.8 (without palette)",
        4: "PC Paintbrush for Windows",
        5: "PC Paintbrush 3.0+",
    }
    return names.get(version)


def software_palette_expectation(version: int | None) -> PcxSoftwarePaletteExpectation:
    if version == 2:
        return "pc_paintbrush_2_8_with_palette"
    if version == 3:
        return "pc_paintbrush_2_8_without_palette"
    return "unspecified"


def color_mode_description(color_mode: int) -> str | None:
    descriptions = {
        0: "n/a",
        1: "Color Palette",
        2: "Grayscale",
    }
    return descriptions.get(color_mode)


def read_u16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def raw_nonzero_u16le(data: bytes, offset: int) -> int | None:
    value = read_u16le(data, offset)
    if value == 0:
        return None
    return value


plan_pcx_image_transaction = build_pcx_image_transaction_plan
