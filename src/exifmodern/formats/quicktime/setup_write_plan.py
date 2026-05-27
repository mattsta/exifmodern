"""QuickTime generated-target setup materialization planning.

This package-local planner covers the setup-backed QuickTime golden requests
that reuse the test-10 ``all``-deleted MOV as a generated target, then apply
QuickTime metadata writes.  It deliberately does not change the shared modern
planner; broad fan-out gaps remain explicit blockers on this typed plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.quicktime.fanout_write_plan import (
    QuickTimeFanoutBlocker,
    QuickTimeFanoutBlockerCode,
    QuickTimeFanoutEvidenceAnchor,
    QuickTimeFanoutPrerequisite,
    QuickTimeXmpAssignment,
    plan_quicktime_fanout_write_args,
)
from exifmodern.formats.quicktime.metadata_atoms import (
    QuickTimeMetadataGroup,
    QuickTimeMetadataValue,
    QuickTimeMetadataWritePlan,
)
from exifmodern.json_types import (
    JsonObject,
    JsonValue,
    json_array_value,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type QuickTimeSetupStepScope = Literal["setup_step", "main_write"]
type QuickTimeSetupAction = Literal[
    "materialize_reusable_t7_setup_movie",
    "apply_quicktime_metadata_writes",
    "unsupported",
]
type QuickTimeSetupStatus = Literal[
    "quicktime_setup_materialization_planned",
    "quicktime_setup_materialization_planned_with_deferred_fanout",
    "unsupported",
]
type QuickTimeSetupSupplementalName = Literal["Publisher"]
type QuickTimeSetupSupplementalXmpProperty = Literal["XMP-dc:Publisher"]
type QuickTimeSetupBlockerCode = (
    QuickTimeFanoutBlockerCode
    | Literal[
        "unsupported_quicktime_setup_step_shape",
        "quicktime_setup_source_shape_pending",
    ]
)
type QuickTimeSetupPrerequisite = QuickTimeFanoutPrerequisite
type QuickTimeSetupSurface = (
    QuickTimeMetadataGroup
    | Literal[
        "QuickTime:all",
        "XMP",
        "generated_target",
        "argument",
        "api",
        "Microsoft",
        "UserData-3GP",
        "ItemList-Binary",
        "Rotation",
    ]
)


QUICKTIME_T10_SETUP_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="t/QuickTime.t",
    line_start=113,
    line_end=127,
    symbol="QuickTime test 10 generated target setup",
    evidence=(
        "Test 10 writes all= with QuickTimeHandler enabled to a temporary MOV, "
        "then applies QuickTime, Keys, and UserData metadata in a second step."
    ),
)
QUICKTIME_T14_REUSE_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="t/QuickTime.t",
    line_start=181,
    line_end=188,
    symbol="QuickTime test 14 generated target reuse",
    evidence=("Test 14 reuses the test-10 setup MOV and writes an unqualified Publisher tag."),
)
QUICKTIME_DIR_MAP_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/WriteQuickTime.pl",
    line_start=15,
    line_end=23,
    symbol="%dirMap",
    evidence=(
        "QuickTime writes default to ItemList; Keys and UserData route to their "
        "separate movie metadata locations."
    ),
)
QUICKTIME_DELETE_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/WriteQuickTime.pl",
    line_start=985,
    line_end=1010,
    symbol="WriteQuickTime delete group selection",
    evidence="WriteQuickTime checks each directory delete group while rewriting MOV atoms.",
)
QUICKTIME_CREATE_KEYS_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/WriteQuickTime.pl",
    line_start=941,
    line_end=959,
    symbol="WriteQuickTime Keys creation",
    evidence="Keys writes may create a movie-level Meta/Keys/ItemList path before item writes.",
)
QUICKTIME_ITEMLIST_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=3478,
    line_end=3501,
    symbol="%Image::ExifTool::QuickTime::ItemList",
    evidence="ItemList is writable and the preferred location for new QuickTime tags.",
)
QUICKTIME_USERDATA_ARRANGER_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1582,
    line_end=1613,
    symbol="%Image::ExifTool::QuickTime::UserData Arranger",
    evidence="UserData is writable and includes the Arranger atom used by test 10.",
)
QUICKTIME_KEYS_DIRECTOR_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=6648,
    line_end=6685,
    symbol="%Image::ExifTool::QuickTime::Keys director",
    evidence="Keys is writable and includes the director key used by test 10.",
)
QUICKTIME_ITEMLIST_PUBLISHER_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=6570,
    line_end=6573,
    symbol="%Image::ExifTool::QuickTime::ItemList Publisher",
    evidence="Publisher is an ItemList atom with tag ID \\xa9pub.",
)
QUICKTIME_XMP_PUBLISHER_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="t/QuickTime.t",
    line_start=181,
    line_end=188,
    symbol="QuickTime test 14 Publisher fan-out",
    evidence=(
        "The unqualified Publisher write creates both QuickTime ItemList Publisher "
        "and XMP dc:publisher in the generated MOV target."
    ),
)
XMP_DC_PUBLISHER_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/XMP.pm",
    line_start=1018,
    line_end=1035,
    symbol="%Image::ExifTool::XMP::dc publisher",
    evidence="The XMP Dublin Core publisher property is writable as a Bag list.",
)


@dataclass(frozen=True)
class QuickTimeSetupBlocker:
    code: QuickTimeSetupBlockerCode
    argument: str
    surface: QuickTimeSetupSurface
    message: str
    source: QuickTimeFanoutEvidenceAnchor
    prerequisites: tuple[QuickTimeSetupPrerequisite, ...] = ()


@dataclass(frozen=True)
class QuickTimeSetupSupplementalMetadataValue:
    group: Literal["ItemList"]
    name: QuickTimeSetupSupplementalName
    atom_id: str
    value: str | None
    source: QuickTimeFanoutEvidenceAnchor


@dataclass(frozen=True)
class QuickTimeSetupSupplementalXmpValue:
    property_name: QuickTimeSetupSupplementalXmpProperty
    namespace_prefix: Literal["dc"]
    namespace_uri: str
    element_name: Literal["publisher"]
    value: str | None
    source: QuickTimeFanoutEvidenceAnchor


@dataclass(frozen=True)
class QuickTimeSetupWriteStep:
    scope: QuickTimeSetupStepScope
    step_index: int | None
    fixture: str | None
    target_filename: str | None
    write_args: tuple[str, ...]
    action: QuickTimeSetupAction
    metadata_plan: QuickTimeMetadataWritePlan
    supplemental_values: tuple[QuickTimeSetupSupplementalMetadataValue, ...]
    supplemental_xmp_values: tuple[QuickTimeSetupSupplementalXmpValue, ...]
    ignored_api_options: tuple[str, ...]
    blockers: tuple[QuickTimeSetupBlocker, ...]
    evidence_refs: tuple[QuickTimeFanoutEvidenceAnchor, ...]

    @property
    def can_apply_quicktime_atoms(self) -> bool:
        return self.action != "unsupported" and not any(
            blocker.code
            in {
                "unsupported_quicktime_write_argument",
                "unsupported_quicktime_api_option",
                "unsupported_quicktime_setup_step_shape",
            }
            for blocker in self.blockers
        )

    @property
    def has_quicktime_atom_mutations(self) -> bool:
        return bool(
            self.metadata_plan.values
            or self.metadata_plan.delete_groups
            or self.supplemental_values
            or self.supplemental_xmp_values
        )


@dataclass(frozen=True)
class QuickTimeSetupMaterializationPlan:
    request_id: str
    fixture: str
    target_filename: str | None
    reusable_setup_target: str | None
    status: QuickTimeSetupStatus
    setup_steps: tuple[QuickTimeSetupWriteStep, ...]
    main_step: QuickTimeSetupWriteStep

    @property
    def steps(self) -> tuple[QuickTimeSetupWriteStep, ...]:
        return (*self.setup_steps, self.main_step)

    @property
    def can_apply_quicktime_atoms(self) -> bool:
        return all(step.can_apply_quicktime_atoms for step in self.steps)

    @property
    def can_complete_exiftool_parity(self) -> bool:
        return all(not step.blockers for step in self.steps)

    @property
    def blocked_surfaces(self) -> tuple[QuickTimeSetupSurface, ...]:
        return dedupe_values(
            tuple(blocker.surface for step in self.steps for blocker in step.blockers)
        )

    @property
    def blocked_prerequisites(self) -> tuple[QuickTimeSetupPrerequisite, ...]:
        return dedupe_values(
            tuple(
                prerequisite
                for step in self.steps
                for blocker in step.blockers
                for prerequisite in blocker.prerequisites
            )
        )


def classify_quicktime_setup_request_file(path: Path) -> QuickTimeSetupMaterializationPlan:
    return classify_quicktime_setup_request_payload(load_json_object(path))


def classify_quicktime_setup_request_payload(
    payload: JsonObject,
) -> QuickTimeSetupMaterializationPlan:
    request_id = required_string(payload, "request_id")
    fixture = required_string(payload, "fixture")
    target_filename = json_string_value(payload, "target_filename")
    setup_steps = tuple(
        classify_setup_step(value, index)
        for index, value in enumerate(json_array_value(payload, "setup_steps"), start=1)
    )
    main_step = classify_write_step(
        scope="main_write",
        step_index=None,
        fixture=fixture,
        target_filename=target_filename,
        write_args=tuple(json_string_array_value(payload, "write_args")),
    )
    steps = (*setup_steps, main_step)
    return QuickTimeSetupMaterializationPlan(
        request_id=request_id,
        fixture=fixture,
        target_filename=target_filename,
        reusable_setup_target=reusable_setup_target(setup_steps, target_filename),
        status=overall_status(steps),
        setup_steps=setup_steps,
        main_step=main_step,
    )


def classify_setup_step(value: JsonValue, index: int) -> QuickTimeSetupWriteStep:
    if not isinstance(value, dict):
        return unsupported_step(
            scope="setup_step",
            step_index=index,
            fixture=None,
            target_filename=None,
            write_args=(),
        )
    return classify_write_step(
        scope="setup_step",
        step_index=index,
        fixture=json_string_value(value, "fixture"),
        target_filename=json_string_value(value, "target_filename"),
        write_args=tuple(json_string_array_value(value, "write_args")),
    )


def classify_write_step(
    *,
    scope: QuickTimeSetupStepScope,
    step_index: int | None,
    fixture: str | None,
    target_filename: str | None,
    write_args: tuple[str, ...],
) -> QuickTimeSetupWriteStep:
    supplemental_args, fanout_args = split_supplemental_args(write_args)
    fanout_plan = plan_quicktime_fanout_write_args(fanout_args)
    supplemental_values = tuple(
        value for arg in supplemental_args for value in supplemental_values_for_arg(arg)
    )
    supplemental_xmp_values = tuple(
        value for arg in supplemental_args for value in supplemental_xmp_values_for_arg(arg)
    )
    supplemental_xmp_values = (
        *supplemental_xmp_values,
        *supplemental_xmp_values_for_fanout(fanout_plan.xmp_assignments),
    )
    action = action_for_step(scope, write_args, fanout_plan.metadata_plan, supplemental_values)
    blockers = (
        *tuple(
            setup_blocker
            for blocker in fanout_plan.blockers
            for setup_blocker in setup_blockers_from_fanout(
                blocker,
                action,
                scope,
                fixture,
                target_filename,
                write_args,
            )
        ),
        *tuple(blocker for arg in supplemental_args for blocker in supplemental_blockers(arg)),
    )
    evidence_refs = evidence_refs_for_step(
        scope,
        fanout_plan.metadata_plan,
        supplemental_values,
        supplemental_xmp_values,
        blockers,
    )
    return QuickTimeSetupWriteStep(
        scope=scope,
        step_index=step_index,
        fixture=fixture,
        target_filename=target_filename,
        write_args=write_args,
        action=action,
        metadata_plan=fanout_plan.metadata_plan,
        supplemental_values=supplemental_values,
        supplemental_xmp_values=supplemental_xmp_values,
        ignored_api_options=fanout_plan.ignored_api_options,
        blockers=blockers,
        evidence_refs=evidence_refs,
    )


def unsupported_step(
    *,
    scope: QuickTimeSetupStepScope,
    step_index: int | None,
    fixture: str | None,
    target_filename: str | None,
    write_args: tuple[str, ...],
) -> QuickTimeSetupWriteStep:
    return QuickTimeSetupWriteStep(
        scope=scope,
        step_index=step_index,
        fixture=fixture,
        target_filename=target_filename,
        write_args=write_args,
        action="unsupported",
        metadata_plan=QuickTimeMetadataWritePlan(values=()),
        supplemental_values=(),
        supplemental_xmp_values=(),
        ignored_api_options=(),
        blockers=(
            QuickTimeSetupBlocker(
                code="unsupported_quicktime_setup_step_shape",
                argument="setup_steps",
                surface="generated_target",
                message="QuickTime setup materialization expected JSON mapping setup steps.",
                source=QUICKTIME_T10_SETUP_SOURCE,
            ),
        ),
        evidence_refs=(QUICKTIME_T10_SETUP_SOURCE,),
    )


def split_supplemental_args(args: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    supplemental: list[str] = []
    fanout: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-api":
            fanout.append(arg)
            if index + 1 < len(args):
                fanout.append(args[index + 1])
            index += 2
            continue
        if is_supplemental_publisher_arg(arg):
            supplemental.append(arg)
        else:
            fanout.append(arg)
        index += 1
    return tuple(supplemental), tuple(fanout)


def is_supplemental_publisher_arg(arg: str) -> bool:
    if not arg.startswith("-") or "=" not in arg:
        return False
    return False


def supplemental_values_for_arg(arg: str) -> tuple[QuickTimeSetupSupplementalMetadataValue, ...]:
    spec, value = arg[1:].split("=", 1)
    if spec.lower() not in {"publisher", "quicktime:publisher", "itemlist:publisher"}:
        return ()
    return (
        QuickTimeSetupSupplementalMetadataValue(
            group="ItemList",
            name="Publisher",
            atom_id="\xa9pub",
            value=value if value != "" else None,
            source=QUICKTIME_ITEMLIST_PUBLISHER_SOURCE,
        ),
    )


def supplemental_xmp_values_for_arg(arg: str) -> tuple[QuickTimeSetupSupplementalXmpValue, ...]:
    spec, value = arg[1:].split("=", 1)
    if spec.lower() != "publisher":
        return ()
    return (
        QuickTimeSetupSupplementalXmpValue(
            property_name="XMP-dc:Publisher",
            namespace_prefix="dc",
            namespace_uri="http://purl.org/dc/elements/1.1/",
            element_name="publisher",
            value=value if value != "" else None,
            source=XMP_DC_PUBLISHER_SOURCE,
        ),
    )


def supplemental_xmp_values_for_fanout(
    assignments: tuple[QuickTimeXmpAssignment, ...],
) -> tuple[QuickTimeSetupSupplementalXmpValue, ...]:
    values: list[QuickTimeSetupSupplementalXmpValue] = []
    for assignment in assignments:
        if assignment.property_name != "XMP-dc:Publisher":
            continue
        values.append(
            QuickTimeSetupSupplementalXmpValue(
                property_name="XMP-dc:Publisher",
                namespace_prefix="dc",
                namespace_uri="http://purl.org/dc/elements/1.1/",
                element_name="publisher",
                value=assignment.value if assignment.value != "" else None,
                source=XMP_DC_PUBLISHER_SOURCE,
            )
        )
    return tuple(values)


def supplemental_blockers(arg: str) -> tuple[QuickTimeSetupBlocker, ...]:
    return ()


def setup_blockers_from_fanout(
    blocker: QuickTimeFanoutBlocker,
    action: QuickTimeSetupAction,
    scope: QuickTimeSetupStepScope,
    fixture: str | None,
    target_filename: str | None,
    write_args: tuple[str, ...],
) -> tuple[QuickTimeSetupBlocker, ...]:
    if (
        action == "materialize_reusable_t7_setup_movie"
        and blocker.code == "broad_all_delete_requires_full_atom_tree_writer"
    ):
        if is_source_backed_reusable_t7_setup_step(
            scope,
            fixture,
            target_filename,
            write_args,
        ):
            return ()
        return (
            QuickTimeSetupBlocker(
                code="quicktime_setup_source_shape_pending",
                argument=blocker.argument,
                surface=blocker.surface,
                message=(
                    "QuickTime setup -all= is only promoted for the source-backed "
                    "t/images/QuickTime.mov -> t-quicktime-t-7-setup.mov setup shape; "
                    "other generated-target shapes must prove their DEL_GROUP traversal "
                    "and offset repair surfaces before runnable promotion."
                ),
                source=QUICKTIME_T10_SETUP_SOURCE,
                prerequisites=(
                    "complete_quicktime_tag_table_del_group_traversal",
                    "quicktime_non_sample_offset_model_repair",
                ),
            ),
        )
    return (
        QuickTimeSetupBlocker(
            code=blocker.code,
            argument=blocker.argument,
            surface=blocker.surface,
            message=blocker.message,
            source=blocker.source,
            prerequisites=blocker.prerequisites,
        ),
    )


def is_source_backed_reusable_t7_setup_step(
    scope: QuickTimeSetupStepScope,
    fixture: str | None,
    target_filename: str | None,
    write_args: tuple[str, ...],
) -> bool:
    return (
        scope == "setup_step"
        and fixture == "t/images/QuickTime.mov"
        and target_filename == "t-quicktime-t-7-setup.mov"
        and write_args == ("-api", "QuickTimeHandler=1", "-all=")
    )


def action_for_step(
    scope: QuickTimeSetupStepScope,
    write_args: tuple[str, ...],
    metadata_plan: QuickTimeMetadataWritePlan,
    supplemental_values: tuple[QuickTimeSetupSupplementalMetadataValue, ...],
) -> QuickTimeSetupAction:
    if scope == "setup_step" and write_args == ("-api", "QuickTimeHandler=1", "-all="):
        return "materialize_reusable_t7_setup_movie"
    if metadata_plan.values or metadata_plan.delete_groups or supplemental_values:
        return "apply_quicktime_metadata_writes"
    return "unsupported"


def evidence_refs_for_step(
    scope: QuickTimeSetupStepScope,
    metadata_plan: QuickTimeMetadataWritePlan,
    supplemental_values: tuple[QuickTimeSetupSupplementalMetadataValue, ...],
    supplemental_xmp_values: tuple[QuickTimeSetupSupplementalXmpValue, ...],
    blockers: tuple[QuickTimeSetupBlocker, ...],
) -> tuple[QuickTimeFanoutEvidenceAnchor, ...]:
    references: list[QuickTimeFanoutEvidenceAnchor] = [
        QUICKTIME_T10_SETUP_SOURCE if scope == "setup_step" else QUICKTIME_DIR_MAP_SOURCE
    ]
    if metadata_plan.delete_groups:
        references.append(QUICKTIME_DELETE_SOURCE)
    for value in metadata_plan.values:
        references.extend(references_for_metadata_value(value))
    for supplemental_value in supplemental_values:
        references.append(supplemental_value.source)
        if supplemental_value.name == "Publisher":
            references.append(QUICKTIME_T14_REUSE_SOURCE)
            references.append(QUICKTIME_XMP_PUBLISHER_SOURCE)
    for supplemental_xmp_value in supplemental_xmp_values:
        if supplemental_xmp_value.property_name == "XMP-dc:Publisher":
            references.append(QUICKTIME_XMP_PUBLISHER_SOURCE)
        references.append(supplemental_xmp_value.source)
    references.extend(blocker.source for blocker in blockers)
    return dedupe_evidence_refs(tuple(references))


def references_for_metadata_value(
    value: QuickTimeMetadataValue,
) -> tuple[QuickTimeFanoutEvidenceAnchor, ...]:
    if value.group == "ItemList":
        if value.name == "Publisher":
            return (QUICKTIME_ITEMLIST_PUBLISHER_SOURCE, QUICKTIME_T14_REUSE_SOURCE)
        return (QUICKTIME_ITEMLIST_SOURCE,)
    if value.group == "Keys":
        return (QUICKTIME_KEYS_DIRECTOR_SOURCE, QUICKTIME_CREATE_KEYS_SOURCE)
    if value.group == "UserData":
        return (QUICKTIME_USERDATA_ARRANGER_SOURCE,)
    return ()


def dedupe_evidence_refs(
    references: tuple[QuickTimeFanoutEvidenceAnchor, ...],
) -> tuple[QuickTimeFanoutEvidenceAnchor, ...]:
    deduped: list[QuickTimeFanoutEvidenceAnchor] = []
    seen: set[tuple[str, int, int, str]] = set()
    for reference in references:
        key = (reference.path, reference.line_start, reference.line_end, reference.symbol)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(reference)
    return tuple(deduped)


def dedupe_values[T: str](values: tuple[T, ...]) -> tuple[T, ...]:
    deduped: list[T] = []
    seen: set[T] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def reusable_setup_target(
    setup_steps: tuple[QuickTimeSetupWriteStep, ...],
    target_filename: str | None,
) -> str | None:
    if not setup_steps:
        return None
    first = setup_steps[0]
    if (
        first.action == "materialize_reusable_t7_setup_movie"
        and first.target_filename == target_filename
    ):
        return target_filename
    return None


def overall_status(
    steps: tuple[QuickTimeSetupWriteStep, ...],
) -> QuickTimeSetupStatus:
    if not all(step.can_apply_quicktime_atoms for step in steps):
        return "unsupported"
    if any(step.blockers for step in steps):
        return "quicktime_setup_materialization_planned_with_deferred_fanout"
    return "quicktime_setup_materialization_planned"


def required_string(payload: JsonObject, key: str) -> str:
    value = json_string_value(payload, key)
    if value is None:
        raise ValueError(f"Expected string field: {key}")
    return value
