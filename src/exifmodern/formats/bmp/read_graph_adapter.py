"""BMP header-plan adapters for the shared read graph and renderer contracts."""

from __future__ import annotations

import time

from exifmodern.formats.bmp.header_transaction_plan import (
    BmpHeaderTransactionPlan,
    bmp_icc_profile_diagnostic,
    build_bmp_header_transaction_plan,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.renderer import JsonRecord, RenderIssue, graph_record_for_request


def build_bmp_read_graph(
    bmp_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    return bmp_header_transaction_plan_to_read_graph(
        build_bmp_header_transaction_plan(bmp_data, allow_output_emission=True),
        source_file,
        generated_at_epoch,
    )


def bmp_header_transaction_plan_to_read_graph(
    plan: BmpHeaderTransactionPlan,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=list(plan.read_tags()),
        diagnostics=bmp_plan_diagnostics(plan),
    )


def render_bmp_header_transaction_plan_record(
    plan: BmpHeaderTransactionPlan,
    source_file: str,
    args: tuple[str, ...],
    generated_at_epoch: int | None = None,
) -> tuple[JsonRecord, list[RenderIssue]]:
    graph = bmp_header_transaction_plan_to_read_graph(plan, source_file, generated_at_epoch)
    return graph_record_for_request(graph, source_file, args)


def bmp_plan_diagnostics(plan: BmpHeaderTransactionPlan) -> list[str]:
    diagnostics = [f"{gate.code}: {gate.reason}" for gate in plan.output_emission_gates]
    if (
        plan.profile.metadata_kind == "icc_profile"
        and plan.profile.payload is not None
        and not plan.profile_tags()
    ):
        icc_reason = bmp_icc_profile_diagnostic(plan.profile)
        if icc_reason is not None:
            diagnostics.append(f"bad_icc_profile: {icc_reason}")
            return diagnostics
        diagnostics.append(
            "icc_profile_adapter_missing: BMP.pm routes MBED profile data to "
            "Image::ExifTool::ICC_Profile::Main, but the embedded profile could "
            "not be promoted by the current ICC reader subset."
        )
    return diagnostics
