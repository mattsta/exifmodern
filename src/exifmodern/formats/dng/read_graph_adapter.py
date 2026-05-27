"""DNG read-graph adapter for Canon OriginalDecisionData in Adobe MakN."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.dng.private_data_writer import (
    discover_original_decision_data_full_file_coordinates,
)
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance
from exifmodern.services.canon_original_decision_data import (
    CanonOriginalDecisionDataDiagnostic,
    CanonOriginalDecisionDataReadRequest,
    CanonOriginalDecisionDataRuntimeResult,
    read_canon_original_decision_data,
)


@dataclass(frozen=True)
class DngOriginalDecisionDataReadGraphResult:
    graph: ReadGraph
    service_result: CanonOriginalDecisionDataRuntimeResult | None
    diagnostics: tuple[CanonOriginalDecisionDataDiagnostic, ...]

    @property
    def resolved(self) -> bool:
        return self.service_result is not None and self.service_result.resolved


def build_dng_original_decision_data_read_graph(
    file_data: bytes,
    source_file: str,
    generated_at_epoch: int = 0,
) -> DngOriginalDecisionDataReadGraphResult:
    """Read Canon ODD through DNG Adobe MakN coordinates.

    DNG Adobe MakN parsing locates the nested maker-note IFD, then resolves the
    `OriginalDecisionDataOffset` coordinate relative to the maker-note TIFF base.
    """

    try:
        coordinates, _directory = discover_original_decision_data_full_file_coordinates(file_data)
    except ValueError as error:
        graph = dng_original_decision_data_graph(
            source_file=source_file,
            generated_at_epoch=generated_at_epoch,
            value=None,
            diagnostics=(f"Canon OriginalDecisionData coordinate discovery failed: {error}",),
        )
        diagnostic = CanonOriginalDecisionDataDiagnostic(
            severity="error",
            code="invalid_dng_original_decision_data_coordinates",
            message=str(error),
        )
        return DngOriginalDecisionDataReadGraphResult(graph, None, (diagnostic,))

    if coordinates.status != "discovered":
        diagnostic = CanonOriginalDecisionDataDiagnostic(
            severity="error",
            code=coordinates.status,
            message=coordinates.reason,
        )
        graph = dng_original_decision_data_graph(
            source_file=source_file,
            generated_at_epoch=generated_at_epoch,
            value=None,
            diagnostics=(coordinates.reason,),
        )
        return DngOriginalDecisionDataReadGraphResult(graph, None, (diagnostic,))

    if coordinates.endian is None or coordinates.tiff_base_offset is None:
        message = (
            "Discovered Canon OriginalDecisionData coordinates must include "
            "DNG maker-note byte order and TIFF base offset."
        )
        diagnostic = CanonOriginalDecisionDataDiagnostic(
            severity="error",
            code="incomplete_dng_original_decision_data_coordinates",
            message=message,
        )
        graph = dng_original_decision_data_graph(
            source_file=source_file,
            generated_at_epoch=generated_at_epoch,
            value=None,
            diagnostics=(message,),
        )
        return DngOriginalDecisionDataReadGraphResult(graph, None, (diagnostic,))

    service_result = read_canon_original_decision_data(
        CanonOriginalDecisionDataReadRequest(
            original_decision_data_offset=coordinates.existing_offset_value,
            file_data=file_data,
            current_byte_order=coordinates.endian,
            offset_base=coordinates.tiff_base_offset,
        )
    )
    graph = dng_original_decision_data_graph(
        source_file=source_file,
        generated_at_epoch=generated_at_epoch,
        value=BinaryTagValue(service_result.data)
        if service_result.data is not None and service_result.resolved
        else None,
        diagnostics=tuple(diagnostic.message for diagnostic in service_result.diagnostics),
    )
    return DngOriginalDecisionDataReadGraphResult(
        graph=graph,
        service_result=service_result,
        diagnostics=service_result.diagnostics,
    )


def dng_original_decision_data_graph(
    source_file: str,
    generated_at_epoch: int,
    value: BinaryTagValue | None,
    diagnostics: tuple[str, ...],
) -> ReadGraph:
    tags: list[ReadTag] = []
    if value is not None:
        tags.append(
            ReadTag(
                name="OriginalDecisionData",
                value=value,
                provenance=TagProvenance(
                    group="Composite",
                    table_name="Image::ExifTool::Canon::Composite",
                    tag_id=None,
                    source="dng-adobe-makn-canon-readodd",
                    family_0_group="Composite",
                    family_1_group="Canon",
                    family_2_group="Image",
                ),
                schema=None,
            )
        )
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=generated_at_epoch,
        source_file=source_file,
        tags=tags,
        diagnostics=list(diagnostics),
    )
