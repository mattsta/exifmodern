"""Typed public request and result surfaces for ExifModern."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeAliasType

if TYPE_CHECKING:
    from exifmodern.json_types import JsonValue
    from exifmodern.public_api.models import (
        CapabilityDescriptor,
        CapabilityQueryRequest,
        CapabilityQueryResult,
        Diagnostic,
        FileInspectRequest,
        FileInspectResult,
        MetadataAssignment,
        MetadataReadRecord,
        MetadataReadRequest,
        MetadataReadResult,
        MetadataWritePlan,
        MetadataWriteRequest,
        MetadataWriteResult,
        OutputFileOverwritePolicy,
        OutputFileRoutingRequest,
        OutputPerSourceFileRouting,
        OutputPerTagFileRouting,
        OutputRenderRequest,
        OutputRenderResult,
        OutputTagFileExtensionFilter,
        OutputWriteFileRouting,
        PublicBatchFrameRequest,
        PublicBatchRequest,
        PublicCopyFromFileRequest,
        PublicCopyFromFileRouteRequest,
        PublicImportWriteRequest,
        PublicOperationStatus,
        PublicReadAlternateFile,
        PublicReadCondition,
        PublicReadFileOrder,
        PublicReadTagExclusion,
        PublicTagLookupRequest,
        PublicTagLookupResult,
        RenderFormat,
        RiffWavMetadataWriteRequest,
        RiffWebpMetadataWriteRequest,
        UnsafeBinaryOutputPolicy,
        UnsupportedReason,
        capability_query_result_to_json_value,
        file_inspect_result_to_json_value,
        inspect_file,
        metadata_read_result_to_json_value,
        metadata_write_plan_to_json_value,
        metadata_write_result_to_json_value,
        output_file_routing_request_to_json_value,
        output_render_request_to_json_value,
        plan_metadata_write,
        public_tag_lookup_result_to_json_value,
        query_capabilities,
        query_tag_lookup,
        read_metadata,
        render_output,
        write_metadata,
    )

type PublicApiLazyCallResult = (
    CapabilityQueryResult
    | FileInspectResult
    | MetadataReadResult
    | MetadataWritePlan
    | MetadataWriteResult
    | OutputRenderResult
    | PublicTagLookupResult
    | JsonValue
    | str
    | bytes
    | None
)
type PublicApiLazyCallable = (
    Callable[[CapabilityQueryResult], JsonValue]
    | Callable[[FileInspectResult], JsonValue]
    | Callable[[FileInspectRequest], FileInspectResult]
    | Callable[[MetadataReadResult], JsonValue]
    | Callable[[MetadataWritePlan], JsonValue]
    | Callable[[MetadataWriteResult], JsonValue]
    | Callable[[OutputFileRoutingRequest], JsonValue]
    | Callable[[OutputRenderRequest], JsonValue]
    | Callable[[MetadataWriteRequest], MetadataWritePlan]
    | Callable[[PublicTagLookupResult], JsonValue]
    | Callable[[CapabilityQueryRequest], CapabilityQueryResult]
    | Callable[[PublicTagLookupRequest], PublicTagLookupResult]
    | Callable[[MetadataReadRequest], MetadataReadResult]
    | Callable[[OutputRenderRequest], OutputRenderResult]
    | Callable[[MetadataWriteRequest], MetadataWriteResult]
)
type PublicApiLazyExport = type | PublicApiLazyCallable
type PublicApiModelExportMap = dict[str, PublicApiLazyExport | TypeAliasType]

__all__ = [
    "CapabilityDescriptor",
    "CapabilityQueryRequest",
    "CapabilityQueryResult",
    "Diagnostic",
    "FileInspectRequest",
    "FileInspectResult",
    "MetadataAssignment",
    "MetadataReadRecord",
    "MetadataReadRequest",
    "MetadataReadResult",
    "MetadataWritePlan",
    "MetadataWriteRequest",
    "MetadataWriteResult",
    "OutputFileOverwritePolicy",
    "OutputFileRoutingRequest",
    "OutputPerSourceFileRouting",
    "OutputPerTagFileRouting",
    "OutputRenderRequest",
    "OutputRenderResult",
    "OutputTagFileExtensionFilter",
    "OutputWriteFileRouting",
    "PublicBatchFrameRequest",
    "PublicBatchRequest",
    "PublicCopyFromFileRequest",
    "PublicCopyFromFileRouteRequest",
    "PublicImportWriteRequest",
    "PublicOperationStatus",
    "PublicReadAlternateFile",
    "PublicReadCondition",
    "PublicReadFileOrder",
    "PublicReadTagExclusion",
    "PublicTagLookupRequest",
    "PublicTagLookupResult",
    "RenderFormat",
    "RiffWavMetadataWriteRequest",
    "RiffWebpMetadataWriteRequest",
    "UnsafeBinaryOutputPolicy",
    "UnsupportedReason",
    "capability_query_result_to_json_value",
    "file_inspect_result_to_json_value",
    "inspect_file",
    "metadata_read_result_to_json_value",
    "metadata_write_plan_to_json_value",
    "metadata_write_result_to_json_value",
    "output_file_routing_request_to_json_value",
    "output_render_request_to_json_value",
    "plan_metadata_write",
    "public_tag_lookup_result_to_json_value",
    "query_capabilities",
    "query_tag_lookup",
    "read_metadata",
    "render_output",
    "write_metadata",
]

_MODEL_EXPORTS = frozenset(__all__)


def __getattr__(name: str) -> PublicApiLazyExport | TypeAliasType:
    if name not in _MODEL_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = _public_api_model_exports()[name]
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_MODEL_EXPORTS])


def _public_api_model_exports() -> PublicApiModelExportMap:
    from exifmodern.public_api.models import (
        CapabilityDescriptor,
        CapabilityQueryRequest,
        CapabilityQueryResult,
        Diagnostic,
        FileInspectRequest,
        FileInspectResult,
        MetadataAssignment,
        MetadataReadRecord,
        MetadataReadRequest,
        MetadataReadResult,
        MetadataWritePlan,
        MetadataWriteRequest,
        MetadataWriteResult,
        OutputFileOverwritePolicy,
        OutputFileRoutingRequest,
        OutputPerSourceFileRouting,
        OutputPerTagFileRouting,
        OutputRenderRequest,
        OutputRenderResult,
        OutputTagFileExtensionFilter,
        OutputWriteFileRouting,
        PublicBatchFrameRequest,
        PublicBatchRequest,
        PublicCopyFromFileRequest,
        PublicCopyFromFileRouteRequest,
        PublicImportWriteRequest,
        PublicOperationStatus,
        PublicReadAlternateFile,
        PublicReadCondition,
        PublicReadFileOrder,
        PublicReadTagExclusion,
        PublicTagLookupRequest,
        PublicTagLookupResult,
        RenderFormat,
        RiffWavMetadataWriteRequest,
        RiffWebpMetadataWriteRequest,
        UnsafeBinaryOutputPolicy,
        UnsupportedReason,
        capability_query_result_to_json_value,
        file_inspect_result_to_json_value,
        inspect_file,
        metadata_read_result_to_json_value,
        metadata_write_plan_to_json_value,
        metadata_write_result_to_json_value,
        output_file_routing_request_to_json_value,
        output_render_request_to_json_value,
        plan_metadata_write,
        public_tag_lookup_result_to_json_value,
        query_capabilities,
        query_tag_lookup,
        read_metadata,
        render_output,
        write_metadata,
    )

    return {
        "CapabilityDescriptor": CapabilityDescriptor,
        "CapabilityQueryRequest": CapabilityQueryRequest,
        "CapabilityQueryResult": CapabilityQueryResult,
        "Diagnostic": Diagnostic,
        "FileInspectRequest": FileInspectRequest,
        "FileInspectResult": FileInspectResult,
        "MetadataAssignment": MetadataAssignment,
        "MetadataReadRecord": MetadataReadRecord,
        "MetadataReadRequest": MetadataReadRequest,
        "MetadataReadResult": MetadataReadResult,
        "MetadataWritePlan": MetadataWritePlan,
        "MetadataWriteRequest": MetadataWriteRequest,
        "MetadataWriteResult": MetadataWriteResult,
        "OutputFileOverwritePolicy": OutputFileOverwritePolicy,
        "OutputFileRoutingRequest": OutputFileRoutingRequest,
        "OutputPerSourceFileRouting": OutputPerSourceFileRouting,
        "OutputPerTagFileRouting": OutputPerTagFileRouting,
        "OutputRenderRequest": OutputRenderRequest,
        "OutputRenderResult": OutputRenderResult,
        "OutputTagFileExtensionFilter": OutputTagFileExtensionFilter,
        "OutputWriteFileRouting": OutputWriteFileRouting,
        "PublicBatchFrameRequest": PublicBatchFrameRequest,
        "PublicBatchRequest": PublicBatchRequest,
        "PublicCopyFromFileRequest": PublicCopyFromFileRequest,
        "PublicCopyFromFileRouteRequest": PublicCopyFromFileRouteRequest,
        "PublicImportWriteRequest": PublicImportWriteRequest,
        "PublicOperationStatus": PublicOperationStatus,
        "PublicReadAlternateFile": PublicReadAlternateFile,
        "PublicReadCondition": PublicReadCondition,
        "PublicReadFileOrder": PublicReadFileOrder,
        "PublicReadTagExclusion": PublicReadTagExclusion,
        "PublicTagLookupRequest": PublicTagLookupRequest,
        "PublicTagLookupResult": PublicTagLookupResult,
        "RenderFormat": RenderFormat,
        "RiffWavMetadataWriteRequest": RiffWavMetadataWriteRequest,
        "RiffWebpMetadataWriteRequest": RiffWebpMetadataWriteRequest,
        "UnsafeBinaryOutputPolicy": UnsafeBinaryOutputPolicy,
        "UnsupportedReason": UnsupportedReason,
        "capability_query_result_to_json_value": capability_query_result_to_json_value,
        "file_inspect_result_to_json_value": file_inspect_result_to_json_value,
        "inspect_file": inspect_file,
        "metadata_read_result_to_json_value": metadata_read_result_to_json_value,
        "metadata_write_plan_to_json_value": metadata_write_plan_to_json_value,
        "metadata_write_result_to_json_value": metadata_write_result_to_json_value,
        "output_file_routing_request_to_json_value": output_file_routing_request_to_json_value,
        "output_render_request_to_json_value": output_render_request_to_json_value,
        "plan_metadata_write": plan_metadata_write,
        "public_tag_lookup_result_to_json_value": public_tag_lookup_result_to_json_value,
        "query_capabilities": query_capabilities,
        "query_tag_lookup": query_tag_lookup,
        "read_metadata": read_metadata,
        "render_output": render_output,
        "write_metadata": write_metadata,
    }
