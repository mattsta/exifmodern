"""Source-grounded Canon CIFF write plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type CiffWriteTagName = Literal["OwnerName"]
type CiffWriteOperation = Literal["upsert"]

type CiffEvidenceId = str

CIFF_OWNER_NAME_SOURCE = "canon.ciff.owner_name"
CIFF_JPEG_WRITER_SOURCE = "canon.ciff.jpeg_writer"


@dataclass(frozen=True)
class CiffWriteStep:
    tag_name: CiffWriteTagName
    tag_id: int
    operation: CiffWriteOperation
    value: str
    max_byte_count: int
    evidence_ids: tuple[CiffEvidenceId, ...]


@dataclass(frozen=True)
class CiffWritePlan:
    steps: tuple[CiffWriteStep, ...]


def build_ciff_owner_name_write_plan(value: str) -> CiffWritePlan:
    encoded = value.encode("utf-8")
    max_byte_count = 32
    if len(encoded) >= max_byte_count:
        raise ValueError("CIFF OwnerName must encode to fewer than 32 bytes.")
    return CiffWritePlan(
        (
            CiffWriteStep(
                tag_name="OwnerName",
                tag_id=0x0810,
                operation="upsert",
                value=value,
                max_byte_count=max_byte_count,
                evidence_ids=(CIFF_OWNER_NAME_SOURCE, CIFF_JPEG_WRITER_SOURCE),
            ),
        )
    )
