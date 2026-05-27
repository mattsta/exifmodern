"""AFCP trailer transaction planning public API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from exifmodern.formats.afcp.trailer_transaction_plan import (
    AfcpRewriteRequest,
    AfcpTrailerTransactionPlan,
    afcp_trailer_byte_range,
    build_afcp_trailer_transaction_plan,
)

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph


class BuildAfcpReadGraph(Protocol):
    def __call__(
        self,
        data: bytes,
        *,
        source_file: str,
        generated_at_epoch: int | None = None,
        scan_for_trailer: bool = False,
    ) -> ReadGraph: ...


__all__ = (
    "AfcpRewriteRequest",
    "AfcpTrailerTransactionPlan",
    "afcp_trailer_byte_range",
    "build_afcp_read_graph",
    "build_afcp_trailer_transaction_plan",
)


def __getattr__(name: str) -> BuildAfcpReadGraph:
    if name == "build_afcp_read_graph":
        from exifmodern.formats.afcp.read_graph_adapter import build_afcp_read_graph

        return build_afcp_read_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
