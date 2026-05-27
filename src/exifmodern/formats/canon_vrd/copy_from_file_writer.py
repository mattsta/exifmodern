"""Safe CanonVRD/CanonDR4 copy-from-file block materialization."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.canon_vrd.dr4_value_writer import (
    CanonVrdDr4ValueWriteUnsupportedError,
    materialize_supported_standalone_dr4_value_write,
)
from exifmodern.formats.canon_vrd.external_write_plan import CanonVrdExternalWriteStep
from exifmodern.formats.canon_vrd.reader import (
    CANON_VRD_SIGNATURE,
    canon_vrd_blocks,
    find_canon_vrd_trailer,
    read_u32,
)

CANON_VRD_DR4_BLOCK = 0xFFFF00F7


@dataclass(frozen=True)
class CanonVrdCopyFromFileResult:
    data: bytes
    copied_bytes: int
    block_tag: str


class CanonVrdCopyFromFileUnsupportedError(ValueError):
    """Raised when a CanonVRD external write step requires real byte mutation."""


def materialize_supported_canon_vrd_copy(
    source_data: bytes,
    step: CanonVrdExternalWriteStep,
) -> CanonVrdCopyFromFileResult:
    if not step.can_write_bytes:
        blockers = ", ".join(step.blocker_codes) or step.status
        raise CanonVrdCopyFromFileUnsupportedError(
            f"CanonVRD step is not an exact block copy: {step.action} ({blockers})"
        )
    if step.action == "copy_canon_vrd_block_to_vrd_file":
        data = extract_canon_vrd_block(source_data)
        return CanonVrdCopyFromFileResult(
            data=data,
            copied_bytes=len(data),
            block_tag="CanonVRD",
        )
    if step.action == "copy_canon_dr4_block_to_dr4_file":
        data = extract_canon_dr4_block(source_data)
        return CanonVrdCopyFromFileResult(
            data=data,
            copied_bytes=len(data),
            block_tag="CanonDR4",
        )
    if step.action == "rewrite_standalone_dr4_values":
        try:
            result = materialize_supported_standalone_dr4_value_write(source_data, step)
        except CanonVrdDr4ValueWriteUnsupportedError as error:
            raise CanonVrdCopyFromFileUnsupportedError(str(error)) from error
        return CanonVrdCopyFromFileResult(
            data=result.data,
            copied_bytes=result.written_bytes,
            block_tag="CanonDR4",
        )
    raise CanonVrdCopyFromFileUnsupportedError(
        f"Unsupported CanonVRD block-copy action: {step.action}"
    )


def extract_canon_vrd_block(source_data: bytes) -> bytes:
    trailer = find_canon_vrd_trailer(source_data)
    if trailer is None:
        raise ValueError("No CanonVRD block found in source data")
    return trailer.payload


def extract_canon_dr4_block(source_data: bytes) -> bytes:
    if is_standalone_canon_dr4(source_data):
        return source_data
    trailer = find_canon_vrd_trailer(source_data)
    if trailer is None:
        raise ValueError("No CanonDR4 block found in source data")
    for block_type, payload in canon_vrd_blocks(trailer.payload):
        if block_type != CANON_VRD_DR4_BLOCK:
            continue
        if len(payload) < 8:
            raise ValueError("Truncated CanonDR4 edit record")
        record_length = read_u32(payload, 0)
        record_end = 4 + record_length
        if record_end + 4 > len(payload):
            raise ValueError("Truncated CanonDR4 wrapped record")
        data = payload[4:record_end]
        if not is_standalone_canon_dr4(data):
            raise ValueError("Wrapped CanonDR4 record has invalid DR4 header")
        return data
    raise ValueError("No CanonDR4 block found in source data")


def is_standalone_canon_dr4(data: bytes) -> bool:
    return (
        len(data) >= 8
        and data[:4] == b"IIII"
        and data[4] in {0x04, 0x05}
        and data[5:8] == b"\0\x04\0"
    )


def is_standalone_canon_vrd(data: bytes) -> bool:
    return data.startswith(CANON_VRD_SIGNATURE) and find_canon_vrd_trailer(data) is not None
