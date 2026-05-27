"""Source-grounded Kodak APP3 MetaIFD write plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type KodakMetaWriteTagName = Literal["SerialNumber"]
type KodakMetaWriteOperation = Literal["upsert"]

KODAK_META_SERIAL_NUMBER_SOURCE = "kodak.meta.serial_number"
KODAK_META_WRITE_PROC_SOURCE = "kodak.meta.write_proc"


@dataclass(frozen=True)
class KodakMetaWriteStep:
    tag_name: KodakMetaWriteTagName
    tag_id: int
    operation: KodakMetaWriteOperation
    value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class KodakMetaWritePlan:
    steps: tuple[KodakMetaWriteStep, ...]


def build_kodak_meta_serial_number_write_plan(value: str) -> KodakMetaWritePlan:
    value.encode("ascii")
    return KodakMetaWritePlan(
        (
            KodakMetaWriteStep(
                tag_name="SerialNumber",
                tag_id=0xC354,
                operation="upsert",
                value=value,
                evidence_ids=(KODAK_META_SERIAL_NUMBER_SOURCE, KODAK_META_WRITE_PROC_SOURCE),
            ),
        )
    )
