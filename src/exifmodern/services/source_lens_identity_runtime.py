"""Runtime adapter for source-backed maker-note lens identity resolution.

The adapter keeps read-graph integration out of this service boundary.  Native
readers can pass the lens-related tag facts they already have, then defer table
selection and source diagnostics to ``SourceLensIdentityRepository``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, TypeGuard

from exifmodern.formats.nikon.lens_database_plan import (
    NIKON_LENS_DATA_ROUTING_SOURCE,
    NIKON_LENS_TYPE_SOURCE,
    NIKON_MAKERNOTE_PRESCAN_SOURCE,
    NIKON_SERIAL_KEY_SOURCE,
    NikonLensIdentityReadFact,
    NikonLensIdentityReadFactEmission,
    NikonLensIdentityReadFactEmissionStatus,
    nikon_classic_lens_identity_read_facts_from_lens_data,
    nikon_count_key_from_raw_shutter_count,
    nikon_lens_data_decode_readiness,
    nikon_lens_id_key,
    nikon_serial_key_from_raw_serial_number,
)
from exifmodern.services.lens_identity import (
    ExifLensIdentityRequest,
    LensIdentityResolution,
    LensTypeValue,
)
from exifmodern.services.lens_identity_repository import (
    SourceLensIdentityFamilyName,
    SourceLensIdentityRepository,
    SourceLensIdentityResolutionResult,
    SourceLensIdentityResolvedFamily,
    SourceLensIdentityTableRecord,
    SourceLensIdentityUnavailableFamily,
)

NIKON_LENS_DATA_ROUTING_SOURCE_ID = "nikon.lens_data.routing"
NIKON_LENS_TYPE_SOURCE_ID = "nikon.lens_type"
NIKON_MAKERNOTE_PRESCAN_SOURCE_ID = "nikon.makernote.prescan"
NIKON_SERIAL_KEY_SOURCE_ID = "nikon.serial_key"

type SourceLensIdentityRuntimeFactValue = str | int | float
type SourceLensIdentityRuntimeStatus = Literal[
    "resolved",
    "missing_required_fact",
    "invalid_required_fact",
    "missing_family",
    "missing_source",
    "unsupported",
]
type NikonComposedLensIDStatus = Literal[
    "synthesized",
    "missing_required_fact",
    "invalid_required_fact",
]
type PanasonicRawMicroFourThirdsLensTypeStatus = Literal[
    "synthesized",
    "missing_required_fact",
    "invalid_required_fact",
]
type NikonLensDataSourceLensIdentityStatus = Literal[
    "resolved",
    "unresolved",
    "fact_emission_blocked",
]
type NikonLensDataRuntimeFactValue = bytes | str | int | float
type NikonMakerNoteTagKey = str | int
type NikonMakerNoteTagMap = Mapping[NikonMakerNoteTagKey, NikonLensDataRuntimeFactValue]
type NikonLensDataRuntimeHandoffRole = Literal[
    "lens_data",
    "lens_type",
    "serial_key",
    "serial_number",
    "count_key",
    "shutter_count",
]
type NikonLensDataRuntimeHandoffStatus = Literal[
    "ready",
    "missing_required_fact",
    "invalid_required_fact",
]
type NikonLensDataRuntimeRoleStatus = Literal[
    "present",
    "derived",
    "missing_required",
    "invalid",
    "optional_absent",
]
type NikonLensDataRuntimeDerivedKeyKind = Literal[
    "nikon_serial_key",
    "nikon_count_key",
]


@dataclass(frozen=True)
class NikonMakerNoteLensDataTagSpec:
    role: NikonLensDataRuntimeHandoffRole
    fact_name: str
    tag_id: str
    accepted_keys: tuple[NikonMakerNoteTagKey, ...]
    source_reference_id: str


class _ResolvedSourceLensIdentityFamilyLike(Protocol):
    family: SourceLensIdentityFamilyName
    status: Literal["resolved"]
    resolution: LensIdentityResolution


NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
HEX_BYTE_RE = re.compile(r"[0-9A-Fa-f]{2}")
NIKON_COMPOSED_LENS_ID_FACT_NAMES = (
    "LensIDNumber",
    "LensFStops",
    "MinFocalLength",
    "MaxFocalLength",
    "MaxApertureAtMinFocal",
    "MaxApertureAtMaxFocal",
    "MCUVersion",
    "LensType",
)
NIKON_LENS_DATA_FACT_NAMES = ("LensData",)
NIKON_LENS_TYPE_FACT_NAMES = ("LensType", "Nikon:LensType")
NIKON_SERIAL_KEY_FACT_NAMES = ("NikonSerialKey", "Nikon:NikonSerialKey")
NIKON_SERIAL_NUMBER_FACT_NAMES = ("SerialNumber", "Nikon:SerialNumber")
NIKON_COUNT_KEY_FACT_NAMES = (
    "NikonCountKey",
    "Nikon:NikonCountKey",
)
NIKON_SHUTTER_COUNT_FACT_NAMES = (
    "ShutterCount",
    "Nikon:ShutterCount",
)
NIKON_LENS_DATA_ROUTED_TAG_NAMES = (
    "LensData",
    "Nikon:LensData",
    "LensData0100",
    "LensData0101",
    "LensData0201",
    "LensData0204",
    "LensData0400",
    "LensData0402",
    "LensData0403",
    "LensData0800",
)
NIKON_MAKERNOTE_LENS_DATA_TAG_SPECS = (
    NikonMakerNoteLensDataTagSpec(
        role="lens_data",
        fact_name="Nikon:LensData",
        tag_id="0x0098",
        accepted_keys=(*NIKON_LENS_DATA_ROUTED_TAG_NAMES, 0x0098, "0x0098", "0x98"),
        source_reference_id=NIKON_LENS_DATA_ROUTING_SOURCE_ID,
    ),
    NikonMakerNoteLensDataTagSpec(
        role="lens_type",
        fact_name="Nikon:LensType",
        tag_id="0x0083",
        accepted_keys=("LensType", "Nikon:LensType", 0x0083, "0x0083", "0x83"),
        source_reference_id=NIKON_LENS_TYPE_SOURCE_ID,
    ),
    NikonMakerNoteLensDataTagSpec(
        role="serial_number",
        fact_name="Nikon:SerialNumber",
        tag_id="0x001d",
        accepted_keys=("SerialNumber", "Nikon:SerialNumber", 0x001D, "0x001d", "0x1d"),
        source_reference_id=NIKON_MAKERNOTE_PRESCAN_SOURCE_ID,
    ),
    NikonMakerNoteLensDataTagSpec(
        role="shutter_count",
        fact_name="Nikon:ShutterCount",
        tag_id="0x00a7",
        accepted_keys=("ShutterCount", "Nikon:ShutterCount", 0x00A7, "0x00a7", "0xa7"),
        source_reference_id=NIKON_MAKERNOTE_PRESCAN_SOURCE_ID,
    ),
    NikonMakerNoteLensDataTagSpec(
        role="serial_key",
        fact_name="Nikon:NikonSerialKey",
        tag_id="NikonSerialKey",
        accepted_keys=("NikonSerialKey", "Nikon:NikonSerialKey"),
        source_reference_id=NIKON_SERIAL_KEY_SOURCE_ID,
    ),
    NikonMakerNoteLensDataTagSpec(
        role="count_key",
        fact_name="Nikon:NikonCountKey",
        tag_id="NikonCountKey",
        accepted_keys=("NikonCountKey", "Nikon:NikonCountKey"),
        source_reference_id=NIKON_MAKERNOTE_PRESCAN_SOURCE_ID,
    ),
)
PANASONIC_RAW_MICRO_FOUR_THIRDS_LENS_TYPE_FACT_NAMES = (
    "LensTypeMake",
    "LensTypeModel",
)
LENS_SPEC_FACT_NAMES = ("LensSpec", "LensSpecification", "LensInfo")
FOCAL_LENGTH_FACT_NAMES = ("FocalLength", "CanonFocalLength")
MAX_APERTURE_FACT_NAMES = ("MaxAperture", "SonyMaxAperture")
MAX_APERTURE_VALUE_FACT_NAMES = (
    "MaxApertureValue",
    "MaxApertureAtMaxFocal",
    "SonyMaxApertureValue",
)
SHORT_FOCAL_FACT_NAMES = ("MinFocalLength", "ShortFocalLength")
LONG_FOCAL_FACT_NAMES = ("MaxFocalLength", "LongFocalLength")


@dataclass(frozen=True)
class SourceLensIdentityRuntimeFact:
    name: str
    raw_value: SourceLensIdentityRuntimeFactValue
    printed_value: str = ""
    group: str = ""
    module: str = ""
    table: str = ""
    tag_id: str = ""


@dataclass(frozen=True)
class SourceLensIdentityRuntimeRequest:
    facts: tuple[SourceLensIdentityRuntimeFact, ...]
    family: SourceLensIdentityFamilyName | None = None
    make: str = ""
    model: str = ""


@dataclass(frozen=True)
class SourceLensIdentityRuntimeSource:
    family: SourceLensIdentityFamilyName
    status: Literal["loaded", "missing_source", "unsupported"]
    owner: str
    source_module: str
    source_paths: tuple[str, ...]
    variable: str
    entry_count: int | None


@dataclass(frozen=True)
class SourceLensIdentityRuntimeResolution:
    status: SourceLensIdentityRuntimeStatus
    family: SourceLensIdentityFamilyName | None
    value: str | None
    candidates: tuple[str, ...]
    reason: str
    lens_request: ExifLensIdentityRequest | None
    consumed_facts: tuple[SourceLensIdentityRuntimeFact, ...]
    missing_facts: tuple[str, ...]
    source: SourceLensIdentityRuntimeSource | None
    repository_resolution: SourceLensIdentityResolutionResult | None

    @property
    def resolved(self) -> bool:
        return self.status == "resolved" and self.value is not None


@dataclass(frozen=True)
class NikonComposedLensIDRuntimeSynthesis:
    status: NikonComposedLensIDStatus
    value: str | None
    reason: str
    consumed_facts: tuple[SourceLensIdentityRuntimeFact, ...]
    missing_facts: tuple[str, ...]
    invalid_facts: tuple[str, ...]

    @property
    def synthesized(self) -> bool:
        return self.status == "synthesized" and self.value is not None


@dataclass(frozen=True)
class PanasonicRawMicroFourThirdsLensTypeRuntimeSynthesis:
    status: PanasonicRawMicroFourThirdsLensTypeStatus
    value: str | None
    reason: str
    consumed_facts: tuple[SourceLensIdentityRuntimeFact, ...]
    missing_facts: tuple[str, ...]
    invalid_facts: tuple[str, ...]

    @property
    def synthesized(self) -> bool:
        return self.status == "synthesized" and self.value is not None


@dataclass(frozen=True)
class NikonLensDataRuntimeFactEmission:
    status: NikonLensIdentityReadFactEmissionStatus
    facts: tuple[NikonLensIdentityReadFact, ...]
    reason: str
    source_reference_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonLensDataSourceLensIdentityReport:
    status: NikonLensDataSourceLensIdentityStatus
    fact_emission: NikonLensDataRuntimeFactEmission
    runtime_resolution: SourceLensIdentityRuntimeResolution | None
    reason: str

    @property
    def resolved(self) -> bool:
        return (
            self.status == "resolved"
            and self.runtime_resolution is not None
            and self.runtime_resolution.resolved
        )


@dataclass(frozen=True)
class NikonLensDataRuntimeFact:
    name: str
    raw_value: NikonLensDataRuntimeFactValue
    printed_value: str = ""
    group: str = "MakerNotes"
    module: str = "Image::ExifTool::Nikon"
    table: str = ""
    tag_id: str = ""


@dataclass(frozen=True)
class NikonLensDataRuntimeRequest:
    facts: tuple[NikonLensDataRuntimeFact, ...]
    already_decoded: bool = False
    make: str = "NIKON"
    model: str = ""


@dataclass(frozen=True)
class NikonLensDataRuntimeFactRequirement:
    role: NikonLensDataRuntimeHandoffRole
    accepted_names: tuple[str, ...]
    tag_id: str
    table: str
    required_for_clear_lens_data: bool
    required_for_encrypted_lens_data: bool
    source_reference_id: str


@dataclass(frozen=True)
class NikonLensDataRuntimeHandoffContract:
    requirements: tuple[NikonLensDataRuntimeFactRequirement, ...]
    source_reference_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonLensDataRuntimeHandoffValidation:
    status: NikonLensDataRuntimeHandoffStatus
    encrypted_lens_data: bool | None
    consumed_facts: tuple[NikonLensDataRuntimeFact, ...]
    missing_roles: tuple[NikonLensDataRuntimeHandoffRole, ...]
    invalid_roles: tuple[NikonLensDataRuntimeHandoffRole, ...]
    reason: str
    source_reference_ids: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class NikonLensDataRuntimeRoleReport:
    role: NikonLensDataRuntimeHandoffRole
    status: NikonLensDataRuntimeRoleStatus
    accepted_names: tuple[str, ...]
    tag_id: str
    table: str
    required: bool
    fact_name: str | None
    raw_value: NikonLensDataRuntimeFactValue | None
    derived_key_kind: NikonLensDataRuntimeDerivedKeyKind | None
    derived_key_value: int | None
    reason: str
    source_reference_id: str


@dataclass(frozen=True)
class NikonLensDataRuntimeHandoffReport:
    validation: NikonLensDataRuntimeHandoffValidation
    roles: tuple[NikonLensDataRuntimeRoleReport, ...]
    encrypted_lens_data: bool | None
    reason: str
    source_reference_ids: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.validation.ready


@dataclass(frozen=True)
class NikonMakerNoteLensDataBridgeReport:
    request: NikonLensDataRuntimeRequest
    handoff: NikonLensDataRuntimeHandoffReport
    source_reference_ids: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.handoff.ready


@dataclass(frozen=True)
class SourceLensIdentityRuntimeFamilySpec:
    family: SourceLensIdentityFamilyName
    modules: tuple[str, ...]
    owners: tuple[str, ...]
    lens_type_tag_names: tuple[str, ...]


FAMILY_SPECS: tuple[SourceLensIdentityRuntimeFamilySpec, ...] = (
    SourceLensIdentityRuntimeFamilySpec(
        family="nikon_lens_ids",
        modules=("Image::ExifTool::Nikon",),
        owners=("nikon",),
        lens_type_tag_names=("LensID",),
    ),
    SourceLensIdentityRuntimeFamilySpec(
        family="canon_rf_lens_type",
        modules=("Image::ExifTool::Canon",),
        owners=("canon",),
        lens_type_tag_names=("RFLensType",),
    ),
    SourceLensIdentityRuntimeFamilySpec(
        family="canon_lens_types",
        modules=("Image::ExifTool::Canon",),
        owners=("canon",),
        lens_type_tag_names=("LensType",),
    ),
    SourceLensIdentityRuntimeFamilySpec(
        family="pentax_lens_types",
        modules=("Image::ExifTool::Pentax",),
        owners=("pentax",),
        lens_type_tag_names=("LensType",),
    ),
    SourceLensIdentityRuntimeFamilySpec(
        family="sigma_lens_types",
        modules=("Image::ExifTool::Sigma",),
        owners=("sigma",),
        lens_type_tag_names=("LensType",),
    ),
    SourceLensIdentityRuntimeFamilySpec(
        family="sony_e_mount",
        modules=("Image::ExifTool::Sony",),
        owners=("sony",),
        lens_type_tag_names=("LensType2", "LensType3"),
    ),
    SourceLensIdentityRuntimeFamilySpec(
        family="sony_a_mount",
        modules=("Image::ExifTool::Sony",),
        owners=("sony",),
        lens_type_tag_names=("LensType",),
    ),
    SourceLensIdentityRuntimeFamilySpec(
        family="minolta_a_mount",
        modules=("Image::ExifTool::Minolta",),
        owners=("minolta",),
        lens_type_tag_names=("LensType",),
    ),
    SourceLensIdentityRuntimeFamilySpec(
        family="minolta_teleconverters",
        modules=("Image::ExifTool::Minolta",),
        owners=("minolta",),
        lens_type_tag_names=("Teleconverter", "TeleconverterType"),
    ),
    SourceLensIdentityRuntimeFamilySpec(
        family="olympus_micro_four_thirds",
        modules=("Image::ExifTool::Olympus",),
        owners=("olympus", "olympus_micro_four_thirds"),
        lens_type_tag_names=("LensType",),
    ),
    SourceLensIdentityRuntimeFamilySpec(
        family="panasonic_leica",
        modules=("Image::ExifTool::Panasonic",),
        owners=("panasonic", "panasonic_leica", "leica"),
        lens_type_tag_names=("LensType",),
    ),
)
PANASONIC_RAW_MICRO_FOUR_THIRDS_FAMILY_SPEC = SourceLensIdentityRuntimeFamilySpec(
    family="olympus_micro_four_thirds",
    modules=("Image::ExifTool::PanasonicRaw",),
    owners=("panasonicraw",),
    lens_type_tag_names=PANASONIC_RAW_MICRO_FOUR_THIRDS_LENS_TYPE_FACT_NAMES,
)


def resolve_source_lens_identity_runtime(
    repository: SourceLensIdentityRepository,
    request: SourceLensIdentityRuntimeRequest,
) -> SourceLensIdentityRuntimeResolution:
    family = request.family or infer_source_lens_identity_family(request.facts)
    if family is None:
        return SourceLensIdentityRuntimeResolution(
            status="missing_required_fact",
            family=None,
            value=None,
            candidates=(),
            reason="Could not infer a source lens identity family from the supplied facts.",
            lens_request=None,
            consumed_facts=(),
            missing_facts=("family",),
            source=None,
            repository_resolution=None,
        )

    lens_request = lens_identity_request_from_runtime_facts(family, request)
    if lens_request is None:
        blocker = lens_identity_request_blocker(family, request.facts)
        blocker_status: SourceLensIdentityRuntimeStatus
        if blocker.status == "invalid_required_fact":
            blocker_status = "invalid_required_fact"
        else:
            blocker_status = "missing_required_fact"
        return SourceLensIdentityRuntimeResolution(
            status=blocker_status,
            family=family,
            value=None,
            candidates=(),
            reason=blocker.reason,
            lens_request=None,
            consumed_facts=blocker.consumed_facts,
            missing_facts=blocker.missing_facts,
            source=source_runtime_record(repository, family),
            repository_resolution=None,
        )

    repository_resolution = repository.resolve(family, lens_request)
    source = source_runtime_record(repository, family)
    if isinstance(repository_resolution, SourceLensIdentityResolvedFamily):
        return SourceLensIdentityRuntimeResolution(
            status="resolved",
            family=family,
            value=repository_resolution.resolution.value,
            candidates=repository_resolution.resolution.candidates,
            reason=repository_resolution.resolution.reason,
            lens_request=lens_request,
            consumed_facts=consumed_facts_for_family(family, request.facts),
            missing_facts=(),
            source=source,
            repository_resolution=repository_resolution,
        )
    if _is_resolved_source_lens_identity_family_like(repository_resolution):
        return SourceLensIdentityRuntimeResolution(
            status="resolved",
            family=family,
            value=repository_resolution.resolution.value,
            candidates=repository_resolution.resolution.candidates,
            reason=repository_resolution.resolution.reason,
            lens_request=lens_request,
            consumed_facts=consumed_facts_for_family(family, request.facts),
            missing_facts=(),
            source=source,
            repository_resolution=None,
        )
    return SourceLensIdentityRuntimeResolution(
        status=repository_resolution.status,
        family=family,
        value=None,
        candidates=(),
        reason=repository_resolution.reason,
        lens_request=lens_request,
        consumed_facts=consumed_facts_for_family(family, request.facts),
        missing_facts=(),
        source=source,
        repository_resolution=repository_resolution,
    )


def _is_resolved_source_lens_identity_family_like(
    resolution: SourceLensIdentityResolutionResult,
) -> TypeGuard[_ResolvedSourceLensIdentityFamilyLike]:
    return (
        resolution.__class__.__name__ == "SourceLensIdentityResolvedFamily"
        and resolution.status == "resolved"
        and hasattr(resolution, "resolution")
    )


def runtime_facts_from_nikon_lens_identity_read_facts(
    facts: tuple[NikonLensIdentityReadFact, ...],
) -> tuple[SourceLensIdentityRuntimeFact, ...]:
    return tuple(
        SourceLensIdentityRuntimeFact(
            name=fact.name,
            raw_value=fact.raw_value,
            printed_value=fact.printed_value,
            group=fact.group,
            module=fact.module,
            table=fact.table,
            tag_id=fact.tag_id,
        )
        for fact in facts
    )


def resolve_nikon_lensdata_source_lens_identity_runtime(
    repository: SourceLensIdentityRepository,
    lens_data: bytes,
    *,
    lens_type: int,
    serial_key: str | int | None = None,
    shutter_count: str | int | None = None,
    already_decoded: bool = False,
    make: str = "NIKON",
    model: str = "",
) -> NikonLensDataSourceLensIdentityReport:
    """Resolve Nikon source lens identity directly from a LensData value.

    This is a reader-facing seam over the lower-level decrypted LensData fact
    emission path.  It intentionally does not parse MakerNotes; callers supply
    the LensData bytes and the already-read Nikon LensType/key facts.
    """

    fact_emission = nikon_classic_lens_identity_read_facts_from_lens_data(
        lens_data,
        lens_type=lens_type,
        serial_key=serial_key,
        shutter_count=shutter_count,
        already_decoded=already_decoded,
    )
    runtime_fact_emission = nikon_lensdata_runtime_fact_emission(fact_emission)
    if fact_emission.status != "emitted":
        return NikonLensDataSourceLensIdentityReport(
            status="fact_emission_blocked",
            fact_emission=runtime_fact_emission,
            runtime_resolution=None,
            reason=runtime_fact_emission.reason,
        )

    runtime_resolution = resolve_source_lens_identity_runtime(
        repository,
        SourceLensIdentityRuntimeRequest(
            family="nikon_lens_ids",
            facts=runtime_facts_from_nikon_lens_identity_read_facts(runtime_fact_emission.facts),
            make=make,
            model=model,
        ),
    )
    return NikonLensDataSourceLensIdentityReport(
        status="resolved" if runtime_resolution.resolved else "unresolved",
        fact_emission=runtime_fact_emission,
        runtime_resolution=runtime_resolution,
        reason=runtime_resolution.reason,
    )


def resolve_nikon_lensdata_source_lens_identity_runtime_from_facts(
    repository: SourceLensIdentityRepository,
    request: NikonLensDataRuntimeRequest,
) -> NikonLensDataSourceLensIdentityReport:
    """Resolve Nikon LensData identity from already-read native tag facts.

    ExifTool routes tag 0x0098 by LensData version and decrypts encrypted
    versions with NikonSerialKey/NikonCountKey.  Native readers may already have
    those raw facts; this helper centralizes the handoff without parsing a full
    MakerNote directory here.
    """

    handoff = validate_nikon_lensdata_runtime_handoff(request)
    if handoff.status == "invalid_required_fact":
        return nikon_lensdata_fact_blocked_report(
            status="invalid_required_fact",
            reason=handoff.reason,
            source_reference_ids=handoff.source_reference_ids,
        )
    lens_data_fact = nikon_lensdata_fact_named(request.facts, NIKON_LENS_DATA_FACT_NAMES)
    lens_type_fact_value = nikon_lensdata_fact_value_named(
        request.facts,
        NIKON_LENS_TYPE_FACT_NAMES,
    )
    if lens_data_fact is None:
        return nikon_lensdata_fact_blocked_report(
            status="missing_required_fact",
            reason="Nikon LensData runtime resolution requires an already-read LensData fact.",
            source_reference_ids=(NIKON_LENS_DATA_ROUTING_SOURCE_ID,),
        )
    if not isinstance(lens_data_fact.raw_value, bytes):
        return nikon_lensdata_fact_blocked_report(
            status="invalid_required_fact",
            reason="Nikon LensData runtime resolution requires raw LensData bytes.",
            source_reference_ids=(NIKON_LENS_DATA_ROUTING_SOURCE_ID,),
        )
    lens_type = nikon_lensdata_lens_type_or_none(lens_type_fact_value)
    if lens_type is None:
        return nikon_lensdata_fact_blocked_report(
            status="missing_required_fact",
            reason="Nikon LensData runtime resolution requires an already-read LensType byte fact.",
            source_reference_ids=(NIKON_LENS_TYPE_SOURCE_ID,),
        )

    serial_key = nikon_lensdata_serial_key_from_runtime_facts(request)
    shutter_count = nikon_lensdata_count_key_from_runtime_facts(request)
    return resolve_nikon_lensdata_source_lens_identity_runtime(
        repository,
        lens_data_fact.raw_value,
        lens_type=lens_type,
        serial_key=serial_key,
        shutter_count=shutter_count,
        already_decoded=request.already_decoded,
        make=request.make,
        model=request.model,
    )


def nikon_lensdata_runtime_handoff_contract() -> NikonLensDataRuntimeHandoffContract:
    """Return the source-backed fact contract expected from native Nikon readers."""

    requirements = (
        NikonLensDataRuntimeFactRequirement(
            role="lens_data",
            accepted_names=NIKON_LENS_DATA_FACT_NAMES,
            tag_id="0x0098",
            table="Image::ExifTool::Nikon::Main",
            required_for_clear_lens_data=True,
            required_for_encrypted_lens_data=True,
            source_reference_id=NIKON_LENS_DATA_ROUTING_SOURCE_ID,
        ),
        NikonLensDataRuntimeFactRequirement(
            role="lens_type",
            accepted_names=NIKON_LENS_TYPE_FACT_NAMES,
            tag_id="0x0083",
            table="Image::ExifTool::Nikon::Main",
            required_for_clear_lens_data=True,
            required_for_encrypted_lens_data=True,
            source_reference_id=NIKON_LENS_TYPE_SOURCE_ID,
        ),
        NikonLensDataRuntimeFactRequirement(
            role="serial_key",
            accepted_names=NIKON_SERIAL_KEY_FACT_NAMES,
            tag_id="NikonSerialKey",
            table="Image::ExifTool::Nikon runtime",
            required_for_clear_lens_data=False,
            required_for_encrypted_lens_data=False,
            source_reference_id=NIKON_SERIAL_KEY_SOURCE_ID,
        ),
        NikonLensDataRuntimeFactRequirement(
            role="serial_number",
            accepted_names=NIKON_SERIAL_NUMBER_FACT_NAMES,
            tag_id="0x001d",
            table="Image::ExifTool::Nikon::Main",
            required_for_clear_lens_data=False,
            required_for_encrypted_lens_data=True,
            source_reference_id=NIKON_MAKERNOTE_PRESCAN_SOURCE_ID,
        ),
        NikonLensDataRuntimeFactRequirement(
            role="count_key",
            accepted_names=NIKON_COUNT_KEY_FACT_NAMES,
            tag_id="NikonCountKey",
            table="Image::ExifTool::Nikon runtime",
            required_for_clear_lens_data=False,
            required_for_encrypted_lens_data=False,
            source_reference_id=NIKON_MAKERNOTE_PRESCAN_SOURCE_ID,
        ),
        NikonLensDataRuntimeFactRequirement(
            role="shutter_count",
            accepted_names=NIKON_SHUTTER_COUNT_FACT_NAMES,
            tag_id="0x00a7",
            table="Image::ExifTool::Nikon::Main",
            required_for_clear_lens_data=False,
            required_for_encrypted_lens_data=True,
            source_reference_id=NIKON_MAKERNOTE_PRESCAN_SOURCE_ID,
        ),
    )
    return NikonLensDataRuntimeHandoffContract(
        requirements=requirements,
        source_reference_ids=(
            NIKON_LENS_DATA_ROUTING_SOURCE_ID,
            NIKON_LENS_TYPE_SOURCE_ID,
            NIKON_SERIAL_KEY_SOURCE_ID,
            NIKON_MAKERNOTE_PRESCAN_SOURCE_ID,
        ),
    )


def nikon_lensdata_runtime_request_from_makernote_tags(
    tags: NikonMakerNoteTagMap,
    *,
    already_decoded: bool = False,
    make: str = "NIKON",
    model: str = "",
) -> NikonLensDataRuntimeRequest:
    """Build a LensData handoff request from already-read Nikon MakerNote tags.

    This bridge intentionally consumes native reader tag maps only.  It does
    not parse MakerNote bytes; the source-backed parsing boundary remains with
    the reader that produced the tag map.
    """

    facts: list[NikonLensDataRuntimeFact] = []
    for spec in NIKON_MAKERNOTE_LENS_DATA_TAG_SPECS:
        matched = nikon_makernote_tag_value(tags, spec.accepted_keys)
        if matched is None:
            continue
        raw_value, _matched_key = matched
        facts.append(
            NikonLensDataRuntimeFact(
                name=spec.fact_name,
                raw_value=raw_value,
                group="MakerNotes",
                module="Image::ExifTool::Nikon",
                table="Image::ExifTool::Nikon::Main",
                tag_id=spec.tag_id,
            )
        )
    return NikonLensDataRuntimeRequest(
        facts=tuple(facts),
        already_decoded=already_decoded,
        make=make,
        model=model,
    )


def nikon_lensdata_runtime_handoff_report_from_makernote_tags(
    tags: NikonMakerNoteTagMap,
    *,
    already_decoded: bool = False,
    make: str = "NIKON",
    model: str = "",
) -> NikonMakerNoteLensDataBridgeReport:
    """Return request plus existing handoff diagnostics for native tag maps."""

    request = nikon_lensdata_runtime_request_from_makernote_tags(
        tags,
        already_decoded=already_decoded,
        make=make,
        model=model,
    )
    handoff = nikon_lensdata_runtime_handoff_report(request)
    return NikonMakerNoteLensDataBridgeReport(
        request=request,
        handoff=handoff,
        source_reference_ids=handoff.source_reference_ids,
    )


def validate_nikon_lensdata_runtime_handoff(
    request: NikonLensDataRuntimeRequest,
) -> NikonLensDataRuntimeHandoffValidation:
    """Validate that native Nikon reader facts satisfy the LensData handoff contract."""

    consumed: list[NikonLensDataRuntimeFact] = []
    missing: list[NikonLensDataRuntimeHandoffRole] = []
    invalid: list[NikonLensDataRuntimeHandoffRole] = []
    source_reference_ids = nikon_lensdata_runtime_handoff_contract().source_reference_ids

    lens_data_fact = nikon_lensdata_fact_named(request.facts, NIKON_LENS_DATA_FACT_NAMES)
    if lens_data_fact is None:
        missing.append("lens_data")
    elif not isinstance(lens_data_fact.raw_value, bytes):
        consumed.append(lens_data_fact)
        invalid.append("lens_data")
    else:
        consumed.append(lens_data_fact)

    lens_type_fact = nikon_lensdata_fact_named(request.facts, NIKON_LENS_TYPE_FACT_NAMES)
    if lens_type_fact is None:
        missing.append("lens_type")
    elif nikon_lensdata_lens_type_or_none(lens_type_fact.raw_value) is None:
        consumed.append(lens_type_fact)
        invalid.append("lens_type")
    else:
        consumed.append(lens_type_fact)

    if (
        missing
        or invalid
        or lens_data_fact is None
        or not isinstance(lens_data_fact.raw_value, bytes)
    ):
        return nikon_lensdata_runtime_handoff_validation_result(
            missing=tuple(missing),
            invalid=tuple(invalid),
            consumed=tuple(consumed),
            encrypted_lens_data=None,
            source_reference_ids=source_reference_ids,
        )

    readiness = nikon_lens_data_decode_readiness(
        lens_data_fact.raw_value,
        already_decoded=request.already_decoded,
    )
    encrypted_lens_data = readiness.encrypted
    if encrypted_lens_data:
        serial_key_fact = nikon_lensdata_fact_named(request.facts, NIKON_SERIAL_KEY_FACT_NAMES)
        serial_number_fact = nikon_lensdata_fact_named(
            request.facts,
            NIKON_SERIAL_NUMBER_FACT_NAMES,
        )
        count_key_fact = nikon_lensdata_fact_named(request.facts, NIKON_COUNT_KEY_FACT_NAMES)
        shutter_count_fact = nikon_lensdata_fact_named(
            request.facts, NIKON_SHUTTER_COUNT_FACT_NAMES
        )
        for fact in (serial_key_fact, serial_number_fact, count_key_fact, shutter_count_fact):
            if fact is not None:
                consumed.append(fact)
        if nikon_lensdata_serial_key_from_runtime_facts(request) is None:
            if serial_key_fact is None and serial_number_fact is None:
                missing.append("serial_number")
            else:
                invalid.append("serial_number")
        if nikon_lensdata_count_key_from_runtime_facts(request) is None:
            if count_key_fact is None and shutter_count_fact is None:
                missing.append("shutter_count")
            else:
                invalid.append("shutter_count")

    return nikon_lensdata_runtime_handoff_validation_result(
        missing=tuple(missing),
        invalid=tuple(invalid),
        consumed=tuple(consumed),
        encrypted_lens_data=encrypted_lens_data,
        source_reference_ids=source_reference_ids,
    )


def nikon_lensdata_runtime_handoff_report(
    request: NikonLensDataRuntimeRequest,
) -> NikonLensDataRuntimeHandoffReport:
    """Return per-role native-reader handoff diagnostics for Nikon LensData.

    This is a planning and integration contract for native MakerNote readers:
    it describes exactly which ExifTool source facts are present, missing, or
    invalid before this service attempts LensData decryption and LensID lookup.
    """

    validation = validate_nikon_lensdata_runtime_handoff(request)
    lens_data_fact = nikon_lensdata_fact_named(request.facts, NIKON_LENS_DATA_FACT_NAMES)
    encrypted_lens_data = nikon_lensdata_runtime_encrypted_state(request, lens_data_fact)
    roles = tuple(
        nikon_lensdata_runtime_role_report(request, requirement, encrypted_lens_data)
        for requirement in nikon_lensdata_runtime_handoff_contract().requirements
    )
    return NikonLensDataRuntimeHandoffReport(
        validation=validation,
        roles=roles,
        encrypted_lens_data=encrypted_lens_data,
        reason=validation.reason,
        source_reference_ids=validation.source_reference_ids,
    )


def infer_source_lens_identity_family(
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
) -> SourceLensIdentityFamilyName | None:
    panasonic_raw_mft = synthesize_panasonic_raw_micro_four_thirds_lens_type(facts)
    if panasonic_raw_mft.consumed_facts and any(
        fact_matches_panasonic_raw_micro_four_thirds_identity(fact) for fact in facts
    ):
        return "olympus_micro_four_thirds"
    for spec in FAMILY_SPECS:
        if lens_type_fact(spec, facts) is not None and any(
            fact_matches_spec_identity(fact, spec) for fact in facts
        ):
            return spec.family
    for spec in FAMILY_SPECS:
        if lens_type_fact(spec, facts) is not None:
            return spec.family
    return None


def lens_identity_request_from_runtime_facts(
    family: SourceLensIdentityFamilyName,
    request: SourceLensIdentityRuntimeRequest,
) -> ExifLensIdentityRequest | None:
    spec = family_spec(family)
    lens_fact = lens_type_fact(spec, request.facts)
    synthesized_lens_id: NikonComposedLensIDRuntimeSynthesis | None = None
    synthesized_panasonic_raw_mft_lens_type: (
        PanasonicRawMicroFourThirdsLensTypeRuntimeSynthesis | None
    ) = None
    if lens_fact is None and family == "nikon_lens_ids":
        synthesized_lens_id = synthesize_nikon_composed_lens_id(request.facts)
    if lens_fact is None and family == "olympus_micro_four_thirds":
        synthesized_panasonic_raw_mft_lens_type = (
            synthesize_panasonic_raw_micro_four_thirds_lens_type(request.facts)
        )
    if (
        lens_fact is None
        and synthesized_lens_id is None
        and synthesized_panasonic_raw_mft_lens_type is None
    ):
        return None
    if lens_fact is None:
        synthesized_key: str | None
        if synthesized_lens_id is not None:
            if not synthesized_lens_id.synthesized:
                return None
            synthesized_key = synthesized_lens_id.value
        elif synthesized_panasonic_raw_mft_lens_type is not None:
            if not synthesized_panasonic_raw_mft_lens_type.synthesized:
                return None
            synthesized_key = synthesized_panasonic_raw_mft_lens_type.value
        else:
            return None
        if synthesized_key is None:
            return None
        lens_type: LensTypeValue | None = synthesized_key
        lens_type_print = f"Unknown ({synthesized_key})"
    else:
        lens_type = lens_type_value_for_family(family, lens_fact)
        lens_type_print = printed_or_raw_value(lens_fact)
    if lens_type is None:
        return None
    return ExifLensIdentityRequest(
        lens_type=lens_type,
        lens_type_print=lens_type_print,
        make=request.make or printed_or_raw_named(request.facts, "Make"),
        model=request.model or printed_or_raw_named(request.facts, "Model"),
        lens_spec_print=printed_or_raw_first_named(request.facts, LENS_SPEC_FACT_NAMES),
        focal_length=float_first_named(request.facts, FOCAL_LENGTH_FACT_NAMES),
        max_aperture=float_first_named(request.facts, MAX_APERTURE_FACT_NAMES),
        max_aperture_value=float_first_named(request.facts, MAX_APERTURE_VALUE_FACT_NAMES),
        short_focal=float_first_named(request.facts, SHORT_FOCAL_FACT_NAMES),
        long_focal=float_first_named(request.facts, LONG_FOCAL_FACT_NAMES),
        lens_model=printed_or_raw_named(request.facts, "LensModel"),
        lens_focal_range=printed_or_raw_named(request.facts, "LensFocalRange"),
        lens_spec=raw_first_named(request.facts, LENS_SPEC_FACT_NAMES),
    )


def lens_identity_request_blocker(
    family: SourceLensIdentityFamilyName,
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
) -> NikonComposedLensIDRuntimeSynthesis | PanasonicRawMicroFourThirdsLensTypeRuntimeSynthesis:
    if family == "nikon_lens_ids":
        nikon_synthesis = synthesize_nikon_composed_lens_id(facts)
        if nikon_synthesis.consumed_facts:
            return nikon_synthesis
    if family == "olympus_micro_four_thirds":
        panasonic_raw_mft_synthesis = synthesize_panasonic_raw_micro_four_thirds_lens_type(facts)
        if panasonic_raw_mft_synthesis.consumed_facts:
            return panasonic_raw_mft_synthesis
    return NikonComposedLensIDRuntimeSynthesis(
        status="missing_required_fact",
        value=None,
        reason=f"Missing required lens identity fact for source family: {family}.",
        consumed_facts=consumed_facts_for_family(family, facts),
        missing_facts=family_lens_type_tag_names(family),
        invalid_facts=(),
    )


def synthesize_panasonic_raw_micro_four_thirds_lens_type(
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
) -> PanasonicRawMicroFourThirdsLensTypeRuntimeSynthesis:
    """Compose PanasonicRaw's Olympus LensType key from LensTypeMake/Model facts."""

    make_fact = fact_named(facts, "LensTypeMake")
    model_fact = fact_named(facts, "LensTypeModel")
    consumed = tuple(fact for fact in (make_fact, model_fact) if fact is not None)
    missing = tuple(
        name
        for name, fact in (
            ("LensTypeMake", make_fact),
            ("LensTypeModel", model_fact),
        )
        if fact is None
    )
    if missing:
        return PanasonicRawMicroFourThirdsLensTypeRuntimeSynthesis(
            status="missing_required_fact",
            value=None,
            reason=(
                "PanasonicRaw Micro Four Thirds LensType synthesis requires "
                "LensTypeMake and LensTypeModel facts."
            ),
            consumed_facts=consumed,
            missing_facts=missing,
            invalid_facts=(),
        )
    if make_fact is None or model_fact is None:
        raise AssertionError("missing facts should have returned above")

    make_key = panasonic_raw_lens_type_make_key(make_fact.raw_value)
    model_key = panasonic_raw_lens_type_model_key(model_fact.raw_value)
    invalid = tuple(
        name
        for name, value in (
            ("LensTypeMake", make_key),
            ("LensTypeModel", model_key),
        )
        if value is None
    )
    if invalid:
        return PanasonicRawMicroFourThirdsLensTypeRuntimeSynthesis(
            status="invalid_required_fact",
            value=None,
            reason=(
                "PanasonicRaw Micro Four Thirds LensType synthesis requires a numeric "
                "LensTypeMake and an int16u or already-converted LensTypeModel."
            ),
            consumed_facts=consumed,
            missing_facts=(),
            invalid_facts=invalid,
        )

    return PanasonicRawMicroFourThirdsLensTypeRuntimeSynthesis(
        status="synthesized",
        value=f"{make_key} {model_key}",
        reason="Synthesized PanasonicRaw Micro Four Thirds LensType from source-required facts.",
        consumed_facts=consumed,
        missing_facts=(),
        invalid_facts=(),
    )


def synthesize_nikon_composed_lens_id(
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
) -> NikonComposedLensIDRuntimeSynthesis:
    """Compose Nikon's classic 8-byte LensID key from source-required raw facts."""

    consumed: list[SourceLensIdentityRuntimeFact] = []
    missing: list[str] = []
    invalid: list[str] = []
    byte_values: list[int] = []
    for name in NIKON_COMPOSED_LENS_ID_FACT_NAMES:
        fact = fact_named(facts, name)
        if fact is None:
            missing.append(name)
            continue
        consumed.append(fact)
        byte_value = strict_nikon_lens_id_byte_value(fact.raw_value)
        if byte_value is None:
            invalid.append(name)
            continue
        byte_values.append(byte_value)

    if missing:
        return NikonComposedLensIDRuntimeSynthesis(
            status="missing_required_fact",
            value=None,
            reason=(
                "Nikon composite LensID synthesis requires LensIDNumber, LensFStops, "
                "MinFocalLength, MaxFocalLength, MaxApertureAtMinFocal, "
                "MaxApertureAtMaxFocal, MCUVersion, and LensType raw byte facts."
            ),
            consumed_facts=tuple(consumed),
            missing_facts=tuple(missing),
            invalid_facts=tuple(invalid),
        )
    if invalid:
        return NikonComposedLensIDRuntimeSynthesis(
            status="invalid_required_fact",
            value=None,
            reason=(
                "Nikon composite LensID synthesis only accepts integer byte values "
                "or strict two-digit hexadecimal byte strings."
            ),
            consumed_facts=tuple(consumed),
            missing_facts=(),
            invalid_facts=tuple(invalid),
        )

    return NikonComposedLensIDRuntimeSynthesis(
        status="synthesized",
        value=nikon_lens_id_key(
            byte_values[0],
            byte_values[1],
            byte_values[2],
            byte_values[3],
            byte_values[4],
            byte_values[5],
            byte_values[6],
            byte_values[7],
        ),
        reason="Synthesized Nikon composite LensID from source-required raw byte facts.",
        consumed_facts=tuple(consumed),
        missing_facts=(),
        invalid_facts=(),
    )


def strict_nikon_lens_id_byte_value(value: SourceLensIdentityRuntimeFactValue) -> int | None:
    if isinstance(value, int) and 0 <= value <= 0xFF:
        return value
    if isinstance(value, float) and value.is_integer() and 0 <= value <= 0xFF:
        return int(value)
    if isinstance(value, str) and HEX_BYTE_RE.fullmatch(value):
        return int(value, 16)
    return None


def consumed_facts_for_family(
    family: SourceLensIdentityFamilyName,
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
) -> tuple[SourceLensIdentityRuntimeFact, ...]:
    spec = family_spec(family)
    consumed_names = {
        normalize_name(name)
        for name in (
            *spec.lens_type_tag_names,
            "Make",
            "Model",
            *LENS_SPEC_FACT_NAMES,
            *FOCAL_LENGTH_FACT_NAMES,
            *MAX_APERTURE_FACT_NAMES,
            *MAX_APERTURE_VALUE_FACT_NAMES,
            *SHORT_FOCAL_FACT_NAMES,
            *LONG_FOCAL_FACT_NAMES,
            "LensModel",
            "LensFocalRange",
            *NIKON_COMPOSED_LENS_ID_FACT_NAMES,
            *PANASONIC_RAW_MICRO_FOUR_THIRDS_LENS_TYPE_FACT_NAMES,
        )
    }
    return tuple(fact for fact in facts if normalize_name(fact.name) in consumed_names)


def source_runtime_record(
    repository: SourceLensIdentityRepository,
    family: SourceLensIdentityFamilyName,
) -> SourceLensIdentityRuntimeSource | None:
    record = repository.family(family)
    if isinstance(record, SourceLensIdentityTableRecord):
        return SourceLensIdentityRuntimeSource(
            family=record.family,
            status=record.status,
            owner=record.owner,
            source_module=record.source_module,
            source_paths=record.source_paths,
            variable=record.variable,
            entry_count=record.entry_count,
        )
    if isinstance(record, SourceLensIdentityUnavailableFamily):
        return SourceLensIdentityRuntimeSource(
            family=record.family,
            status=record.status,
            owner=record.owner,
            source_module=record.source_module,
            source_paths=record.source_paths,
            variable=record.variable,
            entry_count=None,
        )
    return None


def family_spec(family: SourceLensIdentityFamilyName) -> SourceLensIdentityRuntimeFamilySpec:
    for spec in FAMILY_SPECS:
        if spec.family == family:
            return spec
    raise ValueError(f"Unsupported source lens identity family: {family}.")


def family_lens_type_tag_names(family: SourceLensIdentityFamilyName) -> tuple[str, ...]:
    return family_spec(family).lens_type_tag_names


def lens_type_fact(
    spec: SourceLensIdentityRuntimeFamilySpec,
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
) -> SourceLensIdentityRuntimeFact | None:
    expected_names = {normalize_name(name) for name in spec.lens_type_tag_names}
    for fact in facts:
        if normalize_name(fact.name) in expected_names:
            return fact
    return None


def fact_matches_spec_identity(
    fact: SourceLensIdentityRuntimeFact,
    spec: SourceLensIdentityRuntimeFamilySpec,
) -> bool:
    if source_identifier_matches_spec(fact.module, spec):
        return True
    group = fact.group.casefold()
    table = fact.table.casefold()
    return source_identifier_matches_spec(fact.table, spec) or any(
        owner in {group, table} for owner in spec.owners
    )


def fact_matches_panasonic_raw_micro_four_thirds_identity(
    fact: SourceLensIdentityRuntimeFact,
) -> bool:
    return source_identifier_matches_spec(
        fact.module,
        PANASONIC_RAW_MICRO_FOUR_THIRDS_FAMILY_SPEC,
    ) or source_identifier_matches_spec(fact.table, PANASONIC_RAW_MICRO_FOUR_THIRDS_FAMILY_SPEC)


def source_identifier_matches_spec(
    identifier: str,
    spec: SourceLensIdentityRuntimeFamilySpec,
) -> bool:
    if not identifier:
        return False
    return any(
        identifier == module or identifier.startswith(f"{module}::") for module in spec.modules
    )


def printed_or_raw_named(
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
    name: str,
) -> str:
    fact = fact_named(facts, name)
    if fact is None:
        return ""
    return printed_or_raw_value(fact)


def printed_or_raw_first_named(
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
    names: tuple[str, ...],
) -> str:
    fact = fact_first_named(facts, names)
    if fact is None:
        return ""
    return printed_or_raw_value(fact)


def raw_named(facts: tuple[SourceLensIdentityRuntimeFact, ...], name: str) -> str | None:
    fact = fact_named(facts, name)
    if fact is None:
        return None
    return string_value(fact.raw_value)


def raw_first_named(
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
    names: tuple[str, ...],
) -> str | None:
    fact = fact_first_named(facts, names)
    if fact is None:
        return None
    return string_value(fact.raw_value)


def float_named(facts: tuple[SourceLensIdentityRuntimeFact, ...], name: str) -> float | None:
    fact = fact_named(facts, name)
    if fact is None:
        return None
    return float_value(fact.raw_value)


def float_first_named(
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
    names: tuple[str, ...],
) -> float | None:
    fact = fact_first_named(facts, names)
    if fact is None:
        return None
    return float_value(fact.raw_value)


def fact_named(
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
    name: str,
) -> SourceLensIdentityRuntimeFact | None:
    normalized = normalize_name(name)
    for fact in facts:
        if normalize_name(fact.name) == normalized:
            return fact
    return None


def fact_first_named(
    facts: tuple[SourceLensIdentityRuntimeFact, ...],
    names: tuple[str, ...],
) -> SourceLensIdentityRuntimeFact | None:
    normalized_names = {normalize_name(name) for name in names}
    for fact in facts:
        if normalize_name(fact.name) in normalized_names:
            return fact
    return None


def nikon_lensdata_fact_named(
    facts: tuple[NikonLensDataRuntimeFact, ...],
    names: tuple[str, ...],
) -> NikonLensDataRuntimeFact | None:
    normalized_names = {normalize_name(name) for name in names}
    for fact in facts:
        if normalize_name(fact.name) in normalized_names:
            return fact
    return None


def nikon_lensdata_fact_value_named(
    facts: tuple[NikonLensDataRuntimeFact, ...],
    names: tuple[str, ...],
) -> NikonLensDataRuntimeFactValue | None:
    fact = nikon_lensdata_fact_named(facts, names)
    return None if fact is None else fact.raw_value


def nikon_makernote_tag_value(
    tags: NikonMakerNoteTagMap,
    accepted_keys: tuple[NikonMakerNoteTagKey, ...],
) -> tuple[NikonLensDataRuntimeFactValue, NikonMakerNoteTagKey] | None:
    for key in accepted_keys:
        if key in tags:
            return tags[key], key
    for actual_key, value in tags.items():
        if any(nikon_makernote_tag_key_matches(actual_key, key) for key in accepted_keys):
            return value, actual_key
    return None


def nikon_makernote_tag_key_matches(
    actual_key: NikonMakerNoteTagKey,
    accepted_key: NikonMakerNoteTagKey,
) -> bool:
    if actual_key == accepted_key:
        return True
    if isinstance(actual_key, int) and isinstance(accepted_key, str):
        return nikon_makernote_hex_key(actual_key) == nikon_makernote_string_key(accepted_key)
    if isinstance(actual_key, str) and isinstance(accepted_key, int):
        return nikon_makernote_string_key(actual_key) == nikon_makernote_hex_key(accepted_key)
    if isinstance(actual_key, str) and isinstance(accepted_key, str):
        return normalize_name(actual_key) == normalize_name(
            accepted_key
        ) or nikon_makernote_string_key(actual_key) == nikon_makernote_string_key(accepted_key)
    return False


def nikon_makernote_hex_key(tag_id: int) -> str:
    return f"0x{tag_id:04x}"


def nikon_makernote_string_key(tag_id: str) -> str:
    text = tag_id.casefold()
    if not text.startswith("0x"):
        return text
    try:
        return nikon_makernote_hex_key(int(text, 16))
    except ValueError:
        return text


def nikon_lensdata_lens_type_or_none(
    value: NikonLensDataRuntimeFactValue | None,
) -> int | None:
    if isinstance(value, int) and 0 <= value <= 0xFF:
        return value
    if isinstance(value, float) and value.is_integer() and 0 <= value <= 0xFF:
        return int(value)
    if isinstance(value, str) and HEX_BYTE_RE.fullmatch(value):
        return int(value, 16)
    return None


def nikon_string_or_int_key(value: NikonLensDataRuntimeFactValue | None) -> str | int | None:
    if isinstance(value, str | int):
        return value
    return None


def nikon_lensdata_serial_key_from_runtime_facts(
    request: NikonLensDataRuntimeRequest,
) -> int | None:
    key_fact = nikon_lensdata_fact_named(request.facts, NIKON_SERIAL_KEY_FACT_NAMES)
    if key_fact is not None:
        return nikon_count_key_from_raw_shutter_count(nikon_string_or_int_key(key_fact.raw_value))
    serial_fact = nikon_lensdata_fact_named(request.facts, NIKON_SERIAL_NUMBER_FACT_NAMES)
    if serial_fact is None:
        return None
    serial_value = nikon_string_or_int_key(serial_fact.raw_value)
    if serial_value is None:
        return None
    return nikon_serial_key_from_raw_serial_number(serial_value, model=request.model)


def nikon_lensdata_count_key_from_runtime_facts(
    request: NikonLensDataRuntimeRequest,
) -> int | None:
    key_fact = nikon_lensdata_fact_named(request.facts, NIKON_COUNT_KEY_FACT_NAMES)
    if key_fact is not None:
        return nikon_count_key_from_raw_shutter_count(nikon_string_or_int_key(key_fact.raw_value))
    shutter_count_fact = nikon_lensdata_fact_named(request.facts, NIKON_SHUTTER_COUNT_FACT_NAMES)
    if shutter_count_fact is None:
        return None
    return nikon_count_key_from_raw_shutter_count(
        nikon_string_or_int_key(shutter_count_fact.raw_value)
    )


def nikon_lensdata_runtime_encrypted_state(
    request: NikonLensDataRuntimeRequest,
    lens_data_fact: NikonLensDataRuntimeFact | None,
) -> bool | None:
    if lens_data_fact is None or not isinstance(lens_data_fact.raw_value, bytes):
        return None
    return nikon_lens_data_decode_readiness(
        lens_data_fact.raw_value,
        already_decoded=request.already_decoded,
    ).encrypted


def nikon_lensdata_runtime_role_report(
    request: NikonLensDataRuntimeRequest,
    requirement: NikonLensDataRuntimeFactRequirement,
    encrypted_lens_data: bool | None,
) -> NikonLensDataRuntimeRoleReport:
    fact = nikon_lensdata_fact_named(request.facts, requirement.accepted_names)
    required = nikon_lensdata_runtime_role_required(requirement, encrypted_lens_data)
    raw_value = None if fact is None else fact.raw_value
    status = nikon_lensdata_runtime_role_status(request, requirement, fact, required)
    derived_key_kind = nikon_lensdata_runtime_role_derived_key_kind(requirement.role, fact)
    derived_key_value = nikon_lensdata_runtime_role_derived_key_value(
        request,
        requirement.role,
        fact,
    )
    return NikonLensDataRuntimeRoleReport(
        role=requirement.role,
        status=status,
        accepted_names=requirement.accepted_names,
        tag_id=requirement.tag_id,
        table=requirement.table,
        required=required,
        fact_name=None if fact is None else fact.name,
        raw_value=raw_value,
        derived_key_kind=derived_key_kind,
        derived_key_value=derived_key_value,
        reason=nikon_lensdata_runtime_role_reason(
            requirement=requirement,
            status=status,
            required=required,
            fact=fact,
            derived_key_value=derived_key_value,
        ),
        source_reference_id=requirement.source_reference_id,
    )


def nikon_lensdata_runtime_role_required(
    requirement: NikonLensDataRuntimeFactRequirement,
    encrypted_lens_data: bool | None,
) -> bool:
    if encrypted_lens_data is True:
        return requirement.required_for_encrypted_lens_data
    if encrypted_lens_data is False:
        return requirement.required_for_clear_lens_data
    return requirement.required_for_clear_lens_data or requirement.required_for_encrypted_lens_data


def nikon_lensdata_runtime_role_status(
    request: NikonLensDataRuntimeRequest,
    requirement: NikonLensDataRuntimeFactRequirement,
    fact: NikonLensDataRuntimeFact | None,
    required: bool,
) -> NikonLensDataRuntimeRoleStatus:
    if fact is None:
        return "missing_required" if required else "optional_absent"
    if requirement.role == "lens_data":
        return "present" if isinstance(fact.raw_value, bytes) else "invalid"
    if requirement.role == "lens_type":
        return (
            "present" if nikon_lensdata_lens_type_or_none(fact.raw_value) is not None else "invalid"
        )
    if requirement.role == "serial_key":
        derived = nikon_lensdata_runtime_role_derived_key_value(request, requirement.role, fact)
        return "present" if derived is not None else "invalid"
    if requirement.role == "serial_number":
        derived = nikon_lensdata_runtime_role_derived_key_value(request, requirement.role, fact)
        return "derived" if derived is not None else "invalid"
    if requirement.role == "count_key":
        derived = nikon_lensdata_runtime_role_derived_key_value(request, requirement.role, fact)
        return "present" if derived is not None else "invalid"
    derived = nikon_lensdata_runtime_role_derived_key_value(request, requirement.role, fact)
    return "derived" if derived is not None else "invalid"


def nikon_lensdata_runtime_role_derived_key_kind(
    role: NikonLensDataRuntimeHandoffRole,
    fact: NikonLensDataRuntimeFact | None,
) -> NikonLensDataRuntimeDerivedKeyKind | None:
    if fact is None:
        return None
    if role == "serial_number":
        return "nikon_serial_key"
    if role == "shutter_count":
        return "nikon_count_key"
    return None


def nikon_lensdata_runtime_role_derived_key_value(
    request: NikonLensDataRuntimeRequest,
    role: NikonLensDataRuntimeHandoffRole,
    fact: NikonLensDataRuntimeFact | None,
) -> int | None:
    if fact is None:
        return None
    if role == "serial_number":
        serial_value = nikon_string_or_int_key(fact.raw_value)
        if serial_value is None:
            return None
        return nikon_serial_key_from_raw_serial_number(serial_value, model=request.model)
    if role == "serial_key":
        return nikon_count_key_from_raw_shutter_count(nikon_string_or_int_key(fact.raw_value))
    if role == "shutter_count" or role == "count_key":
        return nikon_count_key_from_raw_shutter_count(nikon_string_or_int_key(fact.raw_value))
    return None


def nikon_lensdata_runtime_role_reason(
    *,
    requirement: NikonLensDataRuntimeFactRequirement,
    status: NikonLensDataRuntimeRoleStatus,
    required: bool,
    fact: NikonLensDataRuntimeFact | None,
    derived_key_value: int | None,
) -> str:
    if status == "missing_required":
        return (
            f"Native Nikon reader must provide {requirement.role} from "
            f"{requirement.tag_id} before LensData resolution."
        )
    if status == "optional_absent":
        return f"{requirement.role} is not required for this LensData version."
    if status == "invalid":
        fact_name = "<missing>" if fact is None else fact.name
        return f"Native Nikon reader provided invalid {requirement.role} fact: {fact_name}."
    if status == "derived":
        return f"Derived {requirement.role} runtime key {derived_key_value} from source fact."
    if required:
        return f"Native Nikon reader provided required {requirement.role} fact."
    return f"Native Nikon reader provided optional {requirement.role} fact."


def nikon_lensdata_runtime_handoff_validation_result(
    *,
    missing: tuple[NikonLensDataRuntimeHandoffRole, ...],
    invalid: tuple[NikonLensDataRuntimeHandoffRole, ...],
    consumed: tuple[NikonLensDataRuntimeFact, ...],
    encrypted_lens_data: bool | None,
    source_reference_ids: tuple[str, ...],
) -> NikonLensDataRuntimeHandoffValidation:
    status: NikonLensDataRuntimeHandoffStatus
    if invalid:
        status = "invalid_required_fact"
        reason = "Nikon LensData native-reader handoff has invalid required facts."
    elif missing:
        status = "missing_required_fact"
        reason = "Nikon LensData native-reader handoff is missing required facts."
    else:
        status = "ready"
        reason = "Nikon LensData native-reader facts satisfy the source-backed handoff contract."
    return NikonLensDataRuntimeHandoffValidation(
        status=status,
        encrypted_lens_data=encrypted_lens_data,
        consumed_facts=consumed,
        missing_roles=missing,
        invalid_roles=invalid,
        reason=reason,
        source_reference_ids=source_reference_ids,
    )


def nikon_lensdata_fact_blocked_report(
    *,
    status: Literal["missing_required_fact", "invalid_required_fact"],
    reason: str,
    source_reference_ids: tuple[str, ...],
) -> NikonLensDataSourceLensIdentityReport:
    return NikonLensDataSourceLensIdentityReport(
        status="fact_emission_blocked",
        fact_emission=NikonLensDataRuntimeFactEmission(
            status=status,
            facts=(),
            reason=reason,
            source_reference_ids=source_reference_ids,
        ),
        runtime_resolution=None,
        reason=reason,
    )


def nikon_lensdata_runtime_fact_emission(
    fact_emission: NikonLensIdentityReadFactEmission,
) -> NikonLensDataRuntimeFactEmission:
    return NikonLensDataRuntimeFactEmission(
        status=fact_emission.status,
        facts=fact_emission.facts,
        reason=fact_emission.reason,
        source_reference_ids=fact_emission.evidence_ids,
    )


_NIKON_LENSDATA_SOURCE_ANCHORS_BY_ID = {
    NIKON_LENS_DATA_ROUTING_SOURCE_ID: NIKON_LENS_DATA_ROUTING_SOURCE,
    NIKON_LENS_TYPE_SOURCE_ID: NIKON_LENS_TYPE_SOURCE,
    NIKON_MAKERNOTE_PRESCAN_SOURCE_ID: NIKON_MAKERNOTE_PRESCAN_SOURCE,
    NIKON_SERIAL_KEY_SOURCE_ID: NIKON_SERIAL_KEY_SOURCE,
}


def _nikon_lensdata_source_anchor(source_reference_id: str) -> str:
    return _NIKON_LENSDATA_SOURCE_ANCHORS_BY_ID[source_reference_id]


def _nikon_lensdata_source_anchors(
    source_reference_ids: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(_nikon_lensdata_source_anchor(id_) for id_ in source_reference_ids)


def lens_type_value(value: SourceLensIdentityRuntimeFactValue) -> LensTypeValue | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value:
        return value
    if isinstance(value, float):
        return string_value(value)
    return None


def lens_type_value_for_family(
    family: SourceLensIdentityFamilyName,
    fact: SourceLensIdentityRuntimeFact,
) -> LensTypeValue | None:
    if family == "panasonic_leica":
        panasonic_leica_key = panasonic_leica_lens_type_key(fact.raw_value)
        if panasonic_leica_key is not None:
            return panasonic_leica_key
    if family == "olympus_micro_four_thirds":
        olympus_key = olympus_lens_type_key(fact.raw_value)
        if olympus_key is not None:
            return olympus_key
    return lens_type_value(fact.raw_value)


def panasonic_leica_lens_type_key(value: SourceLensIdentityRuntimeFactValue) -> str | None:
    number = non_negative_int_value(value)
    if number is None:
        return None
    return f"{number >> 2} {number & 0x3}"


def olympus_lens_type_key(value: SourceLensIdentityRuntimeFactValue) -> str | None:
    if not isinstance(value, str):
        return None
    parts = value.split()
    if len(parts) != 6:
        return None
    numbers: list[int] = []
    for part in parts:
        number = non_negative_int_value(part)
        if number is None or number > 0xFF:
            return None
        numbers.append(number)
    return f"{numbers[0]:x} {numbers[2]:02x} {numbers[3]:02x}"


def panasonic_raw_lens_type_make_key(
    value: SourceLensIdentityRuntimeFactValue,
) -> str | None:
    number = non_negative_int_value(value)
    if number is None:
        return None
    return str(number)


def panasonic_raw_lens_type_model_key(
    value: SourceLensIdentityRuntimeFactValue,
) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[0-9A-Fa-f]{1,2} [0-9A-Fa-f]{2}", value):
        head, tail = value.split(" ")
        return f"{int(head, 16):x} {int(tail, 16):02x}"
    number = non_negative_int_value(value)
    if number is None or number > 0xFFFF:
        return None
    text = f"{number:04x}"
    return f"{text[2:4]} {text[0:2]}"


def non_negative_int_value(value: SourceLensIdentityRuntimeFactValue) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    if isinstance(value, str) and value.casefold().startswith("0x"):
        try:
            number = int(value, 16)
        except ValueError:
            return None
        return number if number >= 0 else None
    return None


def printed_or_raw_value(fact: SourceLensIdentityRuntimeFact) -> str:
    return fact.printed_value or string_value(fact.raw_value)


def string_value(value: SourceLensIdentityRuntimeFactValue) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def float_value(value: SourceLensIdentityRuntimeFactValue) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    match = NUMBER_RE.search(value)
    if match is None:
        return None
    return float(match.group(0))


def normalize_name(value: str) -> str:
    leaf_name = value.rsplit(":", 1)[-1]
    return leaf_name.replace("_", "").replace("-", "").casefold()
