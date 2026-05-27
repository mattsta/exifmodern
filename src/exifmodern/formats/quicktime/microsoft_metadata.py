"""Classification for QuickTime Microsoft Xtra metadata.

The QuickTime container stores these tags in a ``UserData/Xtra`` atom and
delegates value handling to the upstream Microsoft Xtra routines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type MicrosoftXtraWritableFormat = Literal["Unicode", "int64u"]
type MicrosoftXtraBlockerCode = Literal[
    "unsupported_microsoft_tag",
    "invalid_microsoft_value",
]
type MicrosoftXtraEvidenceId = Literal[
    "quicktime.microsoft_xtra.atom",
    "quicktime.microsoft_xtra.write",
    "quicktime.microsoft_xtra.unicode",
    "quicktime.microsoft_xtra.int64",
    "quicktime.microsoft_xtra.value",
]


@dataclass(frozen=True)
class MicrosoftXtraTagSpec:
    name: str
    xtra_id: str
    writable_format: MicrosoftXtraWritableFormat
    list_values: bool
    source: MicrosoftXtraEvidenceId


@dataclass(frozen=True)
class MicrosoftXtraAssignment:
    name: str
    xtra_id: str
    values: tuple[str, ...]
    writable_format: MicrosoftXtraWritableFormat
    list_values: bool
    source: MicrosoftXtraEvidenceId


@dataclass(frozen=True)
class MicrosoftXtraBlocker:
    code: MicrosoftXtraBlockerCode
    tag: str
    value: str
    message: str
    source: MicrosoftXtraEvidenceId


MICROSOFT_XTRA_ATOM_SOURCE: MicrosoftXtraEvidenceId = "quicktime.microsoft_xtra.atom"
MICROSOFT_XTRA_WRITE_SOURCE: MicrosoftXtraEvidenceId = "quicktime.microsoft_xtra.write"
MICROSOFT_XTRA_UNICODE_SOURCE: MicrosoftXtraEvidenceId = "quicktime.microsoft_xtra.unicode"
MICROSOFT_XTRA_INT64_SOURCE: MicrosoftXtraEvidenceId = "quicktime.microsoft_xtra.int64"
MICROSOFT_XTRA_VALUE_SOURCE: MicrosoftXtraEvidenceId = "quicktime.microsoft_xtra.value"

MICROSOFT_XTRA_TAGS: tuple[MicrosoftXtraTagSpec, ...] = (
    MicrosoftXtraTagSpec(
        name="Director",
        xtra_id="WM/Director",
        writable_format="Unicode",
        list_values=True,
        source=MICROSOFT_XTRA_UNICODE_SOURCE,
    ),
    MicrosoftXtraTagSpec(
        name="SharedUserRating",
        xtra_id="WM/SharedUserRating",
        writable_format="int64u",
        list_values=False,
        source=MICROSOFT_XTRA_INT64_SOURCE,
    ),
)

MICROSOFT_XTRA_TAGS_BY_NAME: dict[str, MicrosoftXtraTagSpec] = {
    tag.name.lower(): tag for tag in MICROSOFT_XTRA_TAGS
}


def microsoft_xtra_tag_spec(tag: str) -> MicrosoftXtraTagSpec | None:
    return MICROSOFT_XTRA_TAGS_BY_NAME.get(tag.lower())


def classify_microsoft_xtra_assignment(
    tag: str,
    value: str,
) -> MicrosoftXtraAssignment | MicrosoftXtraBlocker:
    spec = microsoft_xtra_tag_spec(tag)
    if spec is None:
        return MicrosoftXtraBlocker(
            code="unsupported_microsoft_tag",
            tag=tag,
            value=value,
            message=(
                "Microsoft Xtra tag is not in the source-backed writable subset for "
                "QuickTime test coverage."
            ),
            source=MICROSOFT_XTRA_WRITE_SOURCE,
        )
    if spec.writable_format == "int64u" and not value.isdecimal():
        return MicrosoftXtraBlocker(
            code="invalid_microsoft_value",
            tag=tag,
            value=value,
            message="Microsoft Xtra int64u values must be unsigned integer scalars.",
            source=MICROSOFT_XTRA_VALUE_SOURCE,
        )
    return MicrosoftXtraAssignment(
        name=spec.name,
        xtra_id=spec.xtra_id,
        values=(value,),
        writable_format=spec.writable_format,
        list_values=spec.list_values,
        source=spec.source,
    )


def merge_microsoft_xtra_assignments(
    assignments: tuple[MicrosoftXtraAssignment, ...],
) -> tuple[MicrosoftXtraAssignment, ...]:
    merged: list[MicrosoftXtraAssignment] = []
    for assignment in assignments:
        replacement: MicrosoftXtraAssignment | None = None
        for existing in merged:
            if existing.name != assignment.name:
                continue
            values = (
                (*existing.values, *assignment.values)
                if existing.list_values
                else assignment.values
            )
            replacement = MicrosoftXtraAssignment(
                name=existing.name,
                xtra_id=existing.xtra_id,
                values=values,
                writable_format=existing.writable_format,
                list_values=existing.list_values,
                source=existing.source,
            )
            break
        if replacement is None:
            merged.append(assignment)
        else:
            merged = tuple_replace_assignment(merged, replacement)
    return tuple(merged)


def tuple_replace_assignment(
    assignments: list[MicrosoftXtraAssignment],
    replacement: MicrosoftXtraAssignment,
) -> list[MicrosoftXtraAssignment]:
    return [
        replacement if assignment.name == replacement.name else assignment
        for assignment in assignments
    ]
