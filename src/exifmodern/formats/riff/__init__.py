"""RIFF container reader, mutation, and transaction-planning modules."""

from pathlib import Path

from exifmodern.formats.riff.read_graph_adapter import (
    build_riff_read_graph,
    build_riff_read_graph_from_file,
    render_riff_reader_plan_record,
    riff_reader_plan_to_read_graph,
)
from exifmodern.formats.riff.reader_plan import (
    RiffNestedMetadataRoute,
    RiffReaderPlan,
    RiffReadTag,
    build_riff_reader_plan,
)
from exifmodern.formats.riff.wav_metadata_transaction_plan import (
    RiffChunkPlan,
    RiffEmissionGate,
    RiffListSubchunkPlan,
    RiffMetadataDeletePlan,
    RiffMetadataDeleteRequest,
    RiffMetadataResponsibility,
    RiffMetadataRoutePlan,
    RiffMetadataWriteRequest,
    RiffSignatureValidationPlan,
    RiffSizeUpdatePlan,
    RiffWavMetadataTransactionPlan,
    build_wav_metadata_transaction_plan,
)
from exifmodern.formats.riff.wav_metadata_writer import (
    RiffWavMetadataRewriteResult,
    delete_all_modeled_wav_metadata,
)
from exifmodern.read_graph import ReadGraph, current_dispatch_read_graph_runtime_options
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "RiffChunkPlan",
    "RiffEmissionGate",
    "RiffListSubchunkPlan",
    "RiffMetadataDeletePlan",
    "RiffMetadataDeleteRequest",
    "RiffMetadataResponsibility",
    "RiffMetadataRoutePlan",
    "RiffMetadataWriteRequest",
    "RiffNestedMetadataRoute",
    "RiffReadTag",
    "RiffReaderPlan",
    "RiffSignatureValidationPlan",
    "RiffSizeUpdatePlan",
    "RiffWavMetadataRewriteResult",
    "RiffWavMetadataTransactionPlan",
    "build_riff_read_graph",
    "build_riff_read_graph_from_file",
    "build_riff_reader_plan",
    "build_wav_metadata_transaction_plan",
    "delete_all_modeled_wav_metadata",
    "invoke_riff",
    "render_riff_reader_plan_record",
    "riff_reader_plan_to_read_graph",
]


def invoke_riff(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_riff_read_graph_from_file(
        path,
        source_file=source_file,
        runtime_options=current_dispatch_read_graph_runtime_options(),
    )


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="riff",
        builder_ref="exifmodern.formats.riff:invoke_riff",
        patterns=(Pattern(0, b"RIFF"),),
    ),
    Signature(
        format_id="riff/rf64",
        builder_ref="exifmodern.formats.riff:invoke_riff",
        patterns=(Pattern(0, b"RF64"),),
    ),
)
