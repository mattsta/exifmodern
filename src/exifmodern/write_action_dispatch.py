"""Typed capability registry for generated write-plan actions.

The generated golden write-modern plan is a closed artifact: an action appearing
there is evidence that a request shape is proven by generated planning, but it
does not necessarily mean runtime execution exists.  This module keeps that
distinction explicit for production dispatch callers.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from exifmodern.json_types import (
    JsonObject,
    json_array_value,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type WriteAction = str

DEFAULT_GOLDEN_WRITE_MODERN_PLAN_PATH = (
    Path(__file__).resolve().parents[2] / "artifacts/tests/exifmodern-golden-write-modern-plan.json"
)


class WriteActionCapabilityStatus(StrEnum):
    """Runtime capability status for an action string."""

    NATIVE_CALLABLE_AVAILABLE = "native_callable_available"
    GENERATED_PLAN_AVAILABLE = "generated_plan_available"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, order=True)
class NativeCallableEntry:
    """Package-local callable evidence without importing the callable eagerly."""

    module: str
    name: str
    role: str

    @property
    def dotted_path(self) -> str:
        return f"{self.module}.{self.name}"


@dataclass(frozen=True)
class WriteActionCapability:
    """Classification for one generated write action string."""

    action: WriteAction
    status: WriteActionCapabilityStatus
    reason: str
    native_callables: tuple[NativeCallableEntry, ...] = ()
    evidence_modules: tuple[str, ...] = ()

    @property
    def has_native_callable(self) -> bool:
        return self.status == WriteActionCapabilityStatus.NATIVE_CALLABLE_AVAILABLE

    @property
    def is_currently_classified(self) -> bool:
        return self.status not in {
            WriteActionCapabilityStatus.UNKNOWN,
            WriteActionCapabilityStatus.UNSUPPORTED,
        }


@dataclass(frozen=True)
class GoldenWriteModernPlanRecord:
    """Small typed view over a generated write-plan record."""

    action: WriteAction
    status: str
    request_id: str
    request_path: str
    container_family: str | None
    implementation_module: str | None
    write_tags: tuple[str, ...]


@dataclass(frozen=True)
class WriteActionClassification:
    """A generated artifact record joined to its dispatch capability."""

    record: GoldenWriteModernPlanRecord
    capability: WriteActionCapability


@dataclass(frozen=True)
class WriteActionDispatchReport:
    """Deterministic classification report for modern-runnable artifact actions."""

    classifications: tuple[WriteActionClassification, ...]

    @property
    def record_count(self) -> int:
        return len(self.classifications)

    @property
    def action_count(self) -> int:
        return len({classification.record.action for classification in self.classifications})

    @property
    def actions(self) -> tuple[WriteAction, ...]:
        return tuple(
            sorted({classification.record.action for classification in self.classifications})
        )

    @property
    def unknown_actions(self) -> tuple[WriteAction, ...]:
        return tuple(
            sorted(
                {
                    classification.record.action
                    for classification in self.classifications
                    if classification.capability.status == WriteActionCapabilityStatus.UNKNOWN
                }
            )
        )

    @property
    def unsupported_actions(self) -> tuple[WriteAction, ...]:
        return tuple(
            sorted(
                {
                    classification.record.action
                    for classification in self.classifications
                    if classification.capability.status == WriteActionCapabilityStatus.UNSUPPORTED
                }
            )
        )

    def record_counts_by_status(self) -> dict[WriteActionCapabilityStatus, int]:
        counts = empty_status_counts()
        for classification in self.classifications:
            counts[classification.capability.status] += 1
        return counts

    def action_counts_by_status(self) -> dict[WriteActionCapabilityStatus, int]:
        action_status: dict[WriteAction, WriteActionCapabilityStatus] = {}
        for classification in self.classifications:
            action_status[classification.record.action] = classification.capability.status
        counts = empty_status_counts()
        for status in action_status.values():
            counts[status] += 1
        return counts


def load_modern_runnable_write_action_records(
    artifact_path: Path = DEFAULT_GOLDEN_WRITE_MODERN_PLAN_PATH,
) -> tuple[GoldenWriteModernPlanRecord, ...]:
    """Load only `modern_runnable` records from the generated write-plan artifact."""

    payload = load_json_object(artifact_path)
    records: list[GoldenWriteModernPlanRecord] = []
    for item in json_array_value(payload, "records"):
        if not isinstance(item, dict):
            continue
        record = golden_write_modern_plan_record(item)
        if record is not None and record.status == "modern_runnable":
            records.append(record)
    return tuple(sorted(records, key=lambda record: (record.action, record.request_id)))


@dataclass(frozen=True)
class NativeCallableVerification:
    """Resolution result for one native callable registry entry."""

    action: WriteAction
    entry: NativeCallableEntry
    resolved: bool
    error: str | None = None

    @property
    def dotted_path(self) -> str:
        return self.entry.dotted_path


@dataclass(frozen=True)
class WriteActionNativeCallableVerificationReport:
    """Typed optional verification report for native write-action callables."""

    results: tuple[NativeCallableVerification, ...]

    @property
    def callable_count(self) -> int:
        return len(self.results)

    @property
    def resolved_count(self) -> int:
        return sum(1 for result in self.results if result.resolved)

    @property
    def missing_count(self) -> int:
        return sum(1 for result in self.results if not result.resolved)

    @property
    def resolved_callables(self) -> tuple[NativeCallableVerification, ...]:
        return tuple(result for result in self.results if result.resolved)

    @property
    def missing_callables(self) -> tuple[NativeCallableVerification, ...]:
        return tuple(result for result in self.results if not result.resolved)


def verify_write_action_native_callables(
    capabilities: tuple[WriteActionCapability, ...] | None = None,
) -> WriteActionNativeCallableVerificationReport:
    """Resolve native callable registry entries without validating generated plans.

    This verifier is intentionally optional: production dispatch classification
    remains string/data based, while tests and audits can check that native
    dotted paths still point at importable package attributes.
    """

    results: list[NativeCallableVerification] = []
    checked_capabilities = WRITE_ACTION_CAPABILITY_LIST if capabilities is None else capabilities
    for capability in sorted(checked_capabilities, key=lambda item: item.action):
        if capability.status != WriteActionCapabilityStatus.NATIVE_CALLABLE_AVAILABLE:
            continue
        for entry in capability.native_callables:
            results.append(verify_native_callable_entry(capability.action, entry))
    return WriteActionNativeCallableVerificationReport(tuple(results))


def verify_native_callable_entry(
    action: WriteAction,
    entry: NativeCallableEntry,
) -> NativeCallableVerification:
    try:
        module = importlib.import_module(entry.module)
    except Exception as exc:
        return NativeCallableVerification(
            action=action,
            entry=entry,
            resolved=False,
            error=f"module import failed: {type(exc).__name__}: {exc}",
        )
    try:
        value = getattr(module, entry.name)
    except AttributeError:
        return NativeCallableVerification(
            action=action,
            entry=entry,
            resolved=False,
            error=f"missing attribute: {entry.name}",
        )
    if not callable(value):
        return NativeCallableVerification(
            action=action,
            entry=entry,
            resolved=False,
            error=f"attribute is not callable: {entry.name}",
        )
    return NativeCallableVerification(action=action, entry=entry, resolved=True)


def golden_write_modern_plan_record(
    item: JsonObject,
) -> GoldenWriteModernPlanRecord | None:
    action = json_string_value(item, "action")
    status = json_string_value(item, "status")
    request_id = json_string_value(item, "request_id")
    request_path = json_string_value(item, "request_path")
    if action is None or status is None or request_id is None or request_path is None:
        return None
    return GoldenWriteModernPlanRecord(
        action=action,
        status=status,
        request_id=request_id,
        request_path=request_path,
        container_family=json_string_value(item, "container_family"),
        implementation_module=json_string_value(item, "implementation_module"),
        write_tags=tuple(json_string_array_value(item, "write_tags")),
    )


def classify_write_action(action: WriteAction) -> WriteActionCapability:
    """Return the production dispatch capability for an action string."""

    capability = WRITE_ACTION_CAPABILITIES.get(action)
    if capability is not None:
        return capability
    return WriteActionCapability(
        action=action,
        status=WriteActionCapabilityStatus.UNKNOWN,
        reason="Action is not present in the production write-action capability registry.",
    )


def build_write_action_dispatch_report(
    artifact_path: Path = DEFAULT_GOLDEN_WRITE_MODERN_PLAN_PATH,
) -> WriteActionDispatchReport:
    records = load_modern_runnable_write_action_records(artifact_path)
    classifications = tuple(
        WriteActionClassification(record, classify_write_action(record.action))
        for record in records
    )
    return WriteActionDispatchReport(classifications)


def write_action_dispatch_summary(
    report: WriteActionDispatchReport,
) -> JsonObject:
    record_counts = report.record_counts_by_status()
    action_counts = report.action_counts_by_status()
    return {
        "record_count": report.record_count,
        "action_count": report.action_count,
        "record_counts_by_status": status_counts_to_json(record_counts),
        "action_counts_by_status": status_counts_to_json(action_counts),
        "unknown_actions": list(report.unknown_actions),
        "unsupported_actions": list(report.unsupported_actions),
        "actions": [
            write_action_capability_to_json(classify_write_action(action))
            for action in report.actions
        ],
    }


def write_action_capability_to_json(capability: WriteActionCapability) -> JsonObject:
    return {
        "action": capability.action,
        "status": capability.status.value,
        "reason": capability.reason,
        "native_callables": [
            native_callable_to_json(entry) for entry in capability.native_callables
        ],
        "evidence_modules": list(capability.evidence_modules),
    }


def native_callable_to_json(entry: NativeCallableEntry) -> JsonObject:
    return {
        "module": entry.module,
        "name": entry.name,
        "dotted_path": entry.dotted_path,
        "role": entry.role,
    }


def status_counts_to_json(
    counts: dict[WriteActionCapabilityStatus, int],
) -> JsonObject:
    return {status.value: counts[status] for status in WriteActionCapabilityStatus}


def empty_status_counts() -> dict[WriteActionCapabilityStatus, int]:
    return {status: 0 for status in WriteActionCapabilityStatus}


def native(
    action: WriteAction,
    reason: str,
    callables: tuple[NativeCallableEntry, ...],
    evidence_modules: tuple[str, ...] = (),
) -> WriteActionCapability:
    return WriteActionCapability(
        action=action,
        status=WriteActionCapabilityStatus.NATIVE_CALLABLE_AVAILABLE,
        reason=reason,
        native_callables=tuple(sorted(callables)),
        evidence_modules=tuple(sorted(evidence_modules)),
    )


def proven_plan(
    action: WriteAction,
    reason: str,
    evidence_modules: tuple[str, ...],
) -> WriteActionCapability:
    return WriteActionCapability(
        action=action,
        status=WriteActionCapabilityStatus.GENERATED_PLAN_AVAILABLE,
        reason=reason,
        evidence_modules=tuple(sorted(evidence_modules)),
    )


def callable_entry(module: str, name: str, role: str) -> NativeCallableEntry:
    return NativeCallableEntry(module=module, name=name, role=role)


WRITE_ACTION_CAPABILITY_LIST: tuple[WriteActionCapability, ...] = (
    native(
        "run_modern_canon_vrd_external_writer",
        "CanonVRD external copy/value writes have package-local byte materializers.",
        (
            callable_entry(
                "exifmodern.formats.canon_vrd.copy_from_file_writer",
                "materialize_supported_canon_vrd_copy",
                "byte_materializer",
            ),
        ),
    ),
    native(
        "run_modern_canon_vrd_setup_writer",
        "CanonVRD generated-target setup writes have a package-local batch materializer.",
        (
            callable_entry(
                "exifmodern.formats.canon_vrd.setup_writer",
                "materialize_canon_vrd_setup_data",
                "setup_materializer",
            ),
        ),
    ),
    native(
        "run_modern_dng_protected_private_data_writer",
        (
            "DNG protected private-data handling has package-local ODD private-data "
            "rewrite entrypoints."
        ),
        (
            callable_entry(
                "exifmodern.formats.dng.private_data_writer",
                "rewrite_dng_private_data_original_decision_data",
                "private_data_rewriter",
            ),
        ),
    ),
    native(
        "run_modern_exif_scalar_jpeg_writer",
        "JPEG EXIF scalar writes have a package-local transactional file writer.",
        (
            callable_entry(
                "exifmodern.formats.jpeg.exif_scalar_writer",
                "rewrite_jpeg_file_exif_scalars_creating_if_needed",
                "file_writer",
            ),
        ),
    ),
    native(
        "run_modern_exif_scalar_tiff_writer",
        "TIFF EXIF scalar writes have a package-local transactional file writer.",
        (
            callable_entry(
                "exifmodern.formats.tiff.exif_scalar_file_writer",
                "rewrite_tiff_file_exif_scalars_creating_if_needed",
                "file_writer",
            ),
        ),
    ),
    native(
        "run_modern_exif_sidecar_copy_from_file_writer",
        "EXIF sidecar copy-from-file writes have a package-local path-to-path writer.",
        (
            callable_entry(
                "exifmodern.formats.exif_sidecar.sidecar_writer",
                "rewrite_exif_sidecar_copy_from_file_to_path",
                "file_writer",
            ),
        ),
    ),
    proven_plan(
        "run_modern_fujifilm_raf_mutation_engine",
        (
            "FujiFilm RAF mutation is represented by source-backed mutation and "
            "transactional-output plans."
        ),
        (
            "exifmodern.formats.fujifilm_raw.mutation_plan",
            "exifmodern.oracle_parity.golden_write_modern.fujifilm_raw",
        ),
    ),
    native(
        "run_modern_gps_jpeg_writer",
        "JPEG GPS writes have a package-local transactional EXIF GPS file writer.",
        (
            callable_entry(
                "exifmodern.formats.jpeg.exif_gps_writer",
                "rewrite_jpeg_file_exif_gps_creating_if_needed",
                "file_writer",
            ),
        ),
    ),
    native(
        "run_modern_heic_item_info_writer",
        "HEIC ItemInfo/XMP writes have a constrained package-local transactional writer.",
        (
            callable_entry(
                "exifmodern.formats.heic.item_info_writer",
                "rewrite_heic_xmp_item_transactionally",
                "transactional_writer",
            ),
        ),
    ),
    native(
        "run_modern_jpeg2000_metadata_writer",
        "JPEG 2000 metadata writes have a package-local JP2 metadata file writer.",
        (
            callable_entry(
                "exifmodern.formats.jpeg2000.metadata_writer",
                "rewrite_jp2_file_metadata",
                "file_writer",
            ),
        ),
    ),
    proven_plan(
        "run_modern_png_metadata_writer",
        (
            "PNG golden-write metadata requests are proven through the package-local "
            "PNG runner and generated request artifacts, but are not yet exposed as a "
            "stable production write dispatcher."
        ),
        (
            "exifmodern.oracle_parity.golden_write_modern.png",
            "exifmodern.formats.png.metadata_writer",
        ),
    ),
    proven_plan(
        "run_modern_jpeg_composed_metadata_writer",
        (
            "Composed JPEG writes are proven by generated plan composition but have no "
            "stable production dispatcher."
        ),
        (
            "exifmodern.oracle_parity.golden_write_modern.jpeg_composed",
            "exifmodern.formats.jpeg",
        ),
    ),
    native(
        "run_modern_jxl_metadata_writer",
        "JXL metadata writes have a package-local metadata file writer.",
        (
            callable_entry(
                "exifmodern.formats.jxl.metadata_writer",
                "rewrite_jxl_file_metadata",
                "file_writer",
            ),
        ),
    ),
    proven_plan(
        "run_modern_minolta_mrw_native_writer",
        "Minolta MRW native promotion is represented by source-backed native-promotion plans.",
        (
            "exifmodern.formats.minolta_raw.native_promotion",
            "exifmodern.oracle_parity.golden_write_modern.plan",
        ),
    ),
    proven_plan(
        "run_modern_nikon_nef_native_writer",
        "Nikon NEF native mutation is represented by source-backed mutation/materialization plans.",
        (
            "exifmodern.formats.nikon_raw.mutation_plan",
            "exifmodern.formats.nikon_raw.capture_rebuild_plan",
        ),
    ),
    native(
        "run_modern_panasonic_raw_mutation_engine",
        "Panasonic RW2 mutation has a package-local metadata rewrite entrypoint.",
        (
            callable_entry(
                "exifmodern.formats.panasonic_raw.metadata_writer",
                "rewrite_panasonic_raw_metadata",
                "byte_rewriter",
            ),
        ),
    ),
    native(
        "run_modern_pdf_metadata_delete_writer",
        "PDF metadata delete writes have a package-local incremental delete file writer.",
        (
            callable_entry(
                "exifmodern.formats.pdf.metadata_delete_writer",
                "rewrite_pdf_file_metadata_delete",
                "file_writer",
            ),
        ),
    ),
    proven_plan(
        "run_modern_phaseone_iiq_mutation_engine",
        "Phase One IIQ mutation is represented by source-backed mutation and installation plans.",
        (
            "exifmodern.formats.phaseone_raw.mutation_plan",
            "exifmodern.formats.phaseone_raw.installation_plan",
        ),
    ),
    native(
        "run_modern_photoshop_psd_metadata_writer",
        "Photoshop PSD metadata writes have a package-local metadata transaction entrypoint.",
        (
            callable_entry(
                "exifmodern.formats.photoshop.metadata_writer",
                "apply_photoshop_psd_metadata_transaction",
                "byte_rewriter",
            ),
        ),
    ),
    native(
        "run_modern_quicktime_fanout_writer",
        "QuickTime fanout writes have a package-local file writer.",
        (
            callable_entry(
                "exifmodern.formats.quicktime.fanout_writer",
                "rewrite_quicktime_file_fanout",
                "file_writer",
            ),
        ),
    ),
    native(
        "run_modern_quicktime_rotation_writer",
        "QuickTime rotation writes have a package-local file writer.",
        (
            callable_entry(
                "exifmodern.formats.quicktime.rotation_writer",
                "rewrite_quicktime_file_rotation",
                "file_writer",
            ),
        ),
    ),
    native(
        "run_modern_quicktime_setup_writer",
        "QuickTime generated-target setup writes have a package-local setup materializer.",
        (
            callable_entry(
                "exifmodern.formats.quicktime.setup_writer",
                "materialize_quicktime_setup_data",
                "setup_materializer",
            ),
        ),
    ),
    native(
        "run_modern_riff_webp_metadata_writer",
        "RIFF WebP metadata writes have a package-local metadata file writer.",
        (
            callable_entry(
                "exifmodern.formats.riff.webp_writer",
                "rewrite_webp_file_metadata",
                "file_writer",
            ),
        ),
    ),
    native(
        "run_modern_xmp_generated_writer",
        "Generated XMP property writes have package-local JPEG and sidecar writer entrypoints.",
        (
            callable_entry(
                "exifmodern.formats.jpeg.xmp_property_writer",
                "rewrite_jpeg_file_xmp_properties_creating_if_needed",
                "jpeg_file_writer",
            ),
            callable_entry(
                "exifmodern.formats.xmp.sidecar_writer",
                "rewrite_xmp_sidecar_file_properties",
                "sidecar_file_writer",
            ),
        ),
    ),
    native(
        "run_modern_xmp_namespace_delete_jpeg_writer",
        "JPEG XMP namespace deletes have a package-local file writer.",
        (
            callable_entry(
                "exifmodern.formats.jpeg.xmp_group_delete_writer",
                "delete_jpeg_file_xmp_namespace",
                "file_writer",
            ),
        ),
    ),
    native(
        "run_modern_xmp_sidecar_copy_from_file_writer",
        "XMP sidecar copy-from-file writes have a package-local path-to-path writer.",
        (
            callable_entry(
                "exifmodern.formats.xmp.sidecar_copy_writer",
                "rewrite_xmp_sidecar_copy_from_file_to_path",
                "file_writer",
            ),
        ),
    ),
    proven_plan(
        "run_modern_canon_raw_cr2_mutation_engine",
        "Canon CR2 mutation is represented by source-backed final-emission and ledger plans.",
        (
            "exifmodern.formats.canon_raw.cr2_mutation_plan",
            "exifmodern.formats.canon_raw.final_emission",
        ),
    ),
    proven_plan(
        "run_modern_canon_raw_cr3_mutation_engine",
        "Canon CR3 mutation is represented by source-backed UUID/XMP/TIFF handoff plans.",
        (
            "exifmodern.formats.canon_raw.cr3_mutation_plan",
            "exifmodern.formats.canon_raw.final_emission",
        ),
    ),
)

WRITE_ACTION_CAPABILITIES: dict[WriteAction, WriteActionCapability] = {
    capability.action: capability for capability in WRITE_ACTION_CAPABILITY_LIST
}
