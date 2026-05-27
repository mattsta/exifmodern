"""Machine-readable diagnostics for generated XMP write plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.xmp.property_write import (
    XmpBooleanPropertyWrite,
    XmpGeneratedPlanDiagnostic,
    XmpJobRefPropertyWrite,
    XmpLocalizedTextPropertyPatch,
    XmpLocalizedTextPropertyWrite,
    XmpManifestItemPropertyWrite,
    XmpManifestItemReferenceFieldValue,
    XmpManifestItemSimpleFieldValue,
    XmpPantryItemPropertyWrite,
    XmpPropertyDelete,
    XmpPropertySpec,
    XmpPropertyWritePlan,
    XmpPropertyWriteStep,
    XmpResourceEventPropertyWrite,
    XmpResourceRefPropertyWrite,
    XmpSimpleStructListPropertyWrite,
    XmpSimpleStructPropertyWrite,
    XmpTextListPropertyWrite,
    XmpTextPropertyWrite,
)
from exifmodern.json_types import JsonArray, JsonObject

type XmpGeneratedPlanMode = Literal["write", "delete"]
type XmpGeneratedPlanReportStatus = Literal["supported", "unsupported"]


@dataclass(frozen=True)
class XmpGeneratedPlanReport:
    mode: XmpGeneratedPlanMode
    status: XmpGeneratedPlanReportStatus
    step_count: int
    diagnostic_count: int
    diagnostics: tuple[JsonObject, ...]
    steps: tuple[JsonObject, ...]
    specs: tuple[JsonObject, ...]

    def to_json_object(self) -> JsonObject:
        diagnostics: JsonArray = [dict(item) for item in self.diagnostics]
        steps: JsonArray = [dict(item) for item in self.steps]
        specs: JsonArray = [dict(item) for item in self.specs]
        return {
            "diagnostic_count": self.diagnostic_count,
            "diagnostics": diagnostics,
            "mode": self.mode,
            "specs": specs,
            "status": self.status,
            "step_count": self.step_count,
            "steps": steps,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_json_object(), indent=2, sort_keys=True) + "\n"


def build_xmp_generated_plan_report(
    mode: XmpGeneratedPlanMode,
    plan: XmpPropertyWritePlan,
) -> XmpGeneratedPlanReport:
    diagnostics = tuple(diagnostic_to_json(diagnostic) for diagnostic in plan.generated_diagnostics)
    steps = tuple(step_to_json(step) for step in plan.steps)
    specs = tuple(spec_to_json(spec) for spec in plan.generated_specs)
    status: XmpGeneratedPlanReportStatus = "unsupported" if diagnostics else "supported"
    return XmpGeneratedPlanReport(
        mode=mode,
        status=status,
        step_count=len(steps),
        diagnostic_count=len(diagnostics),
        diagnostics=diagnostics,
        steps=steps,
        specs=specs,
    )


def write_xmp_generated_plan_report(
    mode: XmpGeneratedPlanMode,
    plan: XmpPropertyWritePlan,
    output: Path | None,
) -> XmpGeneratedPlanReport:
    report = build_xmp_generated_plan_report(mode, plan)
    payload = report.to_json()
    if output is None:
        print(payload, end="")
        return report
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")
    return report


def diagnostic_to_json(diagnostic: XmpGeneratedPlanDiagnostic) -> JsonObject:
    return {
        "detail": diagnostic.detail,
        "property_name": diagnostic.property_name,
        "reason": diagnostic.reason,
    }


def spec_to_json(spec: XmpPropertySpec) -> JsonObject:
    return {
        "element_name": spec.element_name,
        "namespace_prefix": spec.namespace_prefix,
        "namespace_uri": spec.namespace_uri,
        "property_name": spec.property_name,
        "rdf_container": spec.rdf_container,
        "value_shape": spec.value_shape,
    }


def step_to_json(step: XmpPropertyWriteStep) -> JsonObject:
    if isinstance(step, XmpPropertyDelete):
        return {"operation": "delete", "property_name": step.property_name}
    if isinstance(step, XmpBooleanPropertyWrite):
        return {
            "operation": "write_boolean",
            "property_name": step.property_name,
            "value": step.value,
        }
    if isinstance(step, XmpTextListPropertyWrite):
        return {
            "operation": "write_text_list",
            "property_name": step.property_name,
            "value_count": len(step.values),
            "values": list(step.values),
        }
    if isinstance(step, XmpLocalizedTextPropertyWrite):
        localized_values: JsonArray = []
        for localized_value in step.values:
            localized_values.append(
                {
                    "language_code": localized_value.language_code,
                    "value": localized_value.value,
                }
            )
        return {
            "operation": "write_lang_alt",
            "property_name": step.property_name,
            "value_count": len(step.values),
            "values": localized_values,
        }
    if isinstance(step, XmpLocalizedTextPropertyPatch):
        localized_writes: JsonArray = []
        for localized_value in step.writes:
            localized_writes.append(
                {
                    "language_code": localized_value.language_code,
                    "value": localized_value.value,
                }
            )
        return {
            "delete_count": len(step.deletes),
            "deletes": list(step.deletes),
            "operation": "patch_lang_alt",
            "property_name": step.property_name,
            "value_count": len(step.writes),
            "values": localized_writes,
        }
    if isinstance(step, XmpJobRefPropertyWrite):
        job_ref_values: JsonArray = []
        for job_ref_value in step.values:
            job_ref_values.append(
                {
                    "field_name": job_ref_value.field_name,
                    "value": job_ref_value.value,
                }
            )
        return {
            "operation": "write_job_ref",
            "property_name": step.property_name,
            "value_count": len(step.values),
            "values": job_ref_values,
        }
    if isinstance(step, XmpManifestItemPropertyWrite):
        manifest_item_values: JsonArray = []
        for manifest_item_value in step.values:
            if isinstance(manifest_item_value, XmpManifestItemSimpleFieldValue):
                manifest_item_values.append(
                    {
                        "field_kind": "simple",
                        "field_name": manifest_item_value.field_name,
                        "value": manifest_item_value.value,
                    }
                )
            elif isinstance(manifest_item_value, XmpManifestItemReferenceFieldValue):
                manifest_item_values.append(
                    {
                        "field_kind": "reference",
                        "field_name": manifest_item_value.field_name,
                        "value": manifest_item_value.value,
                    }
                )
        return {
            "operation": "write_manifest_item",
            "property_name": step.property_name,
            "value_count": len(step.values),
            "values": manifest_item_values,
        }
    if isinstance(step, XmpPantryItemPropertyWrite):
        pantry_item_values: JsonArray = []
        for pantry_item_value in step.values:
            pantry_item_values.append(
                {
                    "field_name": pantry_item_value.field_name,
                    "value": pantry_item_value.value,
                }
            )
        return {
            "operation": "write_pantry_item",
            "property_name": step.property_name,
            "value_count": len(step.values),
            "values": pantry_item_values,
        }
    if isinstance(step, XmpResourceRefPropertyWrite):
        resource_ref_values: JsonArray = []
        for resource_ref_value in step.values:
            resource_ref_values.append(
                {
                    "field_name": resource_ref_value.field_name,
                    "value": resource_ref_value.value,
                }
            )
        return {
            "operation": "write_resource_ref",
            "property_name": step.property_name,
            "value_count": len(step.values),
            "values": resource_ref_values,
        }
    if isinstance(step, XmpResourceEventPropertyWrite):
        resource_event_values: JsonArray = []
        for resource_event_value in step.values:
            resource_event_values.append(
                {
                    "field_name": resource_event_value.field_name,
                    "value": resource_event_value.value,
                }
            )
        return {
            "operation": "write_resource_event",
            "property_name": step.property_name,
            "value_count": len(step.values),
            "values": resource_event_values,
        }
    if isinstance(step, XmpSimpleStructPropertyWrite):
        simple_struct_values: JsonArray = []
        for simple_struct_value in step.values:
            simple_struct_values.append(
                {
                    "field_name": simple_struct_value.field_spec.field_name,
                    "nested_field_name": simple_struct_value.field_spec.nested_field_name,
                    "nested_list_kind": simple_struct_value.field_spec.nested_list_kind,
                    "readback_suffix": simple_struct_value.field_spec.readback_suffix,
                    "value": simple_struct_value.value,
                    "value_kind": simple_struct_value.field_spec.value_kind,
                }
            )
        return {
            "operation": "write_simple_struct",
            "parent_name": step.parent_spec.parent_name,
            "property_name": step.property_name,
            "struct_namespace_prefix": step.parent_spec.struct_namespace_prefix,
            "value_count": len(step.values),
            "values": simple_struct_values,
        }
    if isinstance(step, XmpSimpleStructListPropertyWrite):
        simple_struct_items: JsonArray = []
        for item_group in step.item_groups:
            item_values: JsonArray = []
            for item_value in item_group:
                item_values.append(
                    {
                        "field_name": item_value.field_spec.field_name,
                        "nested_field_name": item_value.field_spec.nested_field_name,
                        "nested_list_kind": item_value.field_spec.nested_list_kind,
                        "readback_suffix": item_value.field_spec.readback_suffix,
                        "value": item_value.value,
                        "value_kind": item_value.field_spec.value_kind,
                    }
                )
            simple_struct_items.append(item_values)
        return {
            "item_count": len(step.item_groups),
            "items": simple_struct_items,
            "operation": "write_simple_struct_list",
            "parent_name": step.parent_spec.parent_name,
            "property_name": step.property_name,
            "struct_namespace_prefix": step.parent_spec.struct_namespace_prefix,
            "value_count": sum(len(item_group) for item_group in step.item_groups),
        }
    if isinstance(step, XmpTextPropertyWrite):
        return {
            "operation": "write_text",
            "property_name": step.property_name,
            "value": step.value,
        }
    raise ValueError(f"Unsupported XMP generated plan step: {step!r}")


def xmp_generated_plan_report_summary(report: XmpGeneratedPlanReport) -> JsonObject:
    return {
        "diagnostic_count": report.diagnostic_count,
        "mode": report.mode,
        "status": report.status,
        "step_count": report.step_count,
    }
