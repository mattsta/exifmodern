"""Source-backed QuickTime ``mvhd``/``tkhd``/``mdhd`` date mutation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, NoReturn

from exifmodern.formats.quicktime.atoms import (
    QuickTimeAtom,
    encode_quicktime_atoms,
    read_quicktime_atoms,
)

QT_MOVIE_ATOM = "moov"
QT_TRACK_ATOM = "trak"
QT_MEDIA_ATOM = "mdia"
QT_MOVIE_HEADER_ATOM = "mvhd"
QT_TRACK_HEADER_ATOM = "tkhd"
QT_MEDIA_HEADER_ATOM = "mdhd"
QT_QUICKTIME_EPOCH_DELTA_SECONDS = (66 * 365 + 17) * 24 * 3600

type QuickTimeHeaderDateTag = Literal[
    "CreateDate",
    "ModifyDate",
    "TrackCreateDate",
    "TrackModifyDate",
    "MediaCreateDate",
    "MediaModifyDate",
]
type QuickTimeHeaderDateBlockerCode = Literal[
    "invalid_quicktime_date_value",
    "unsupported_quicktime_date_timezone",
    "truncated_quicktime_header_dates",
    "unsupported_quicktime_header_version",
]
type QuickTimeDateHeaderKind = Literal["MovieHeader", "TrackHeader", "MediaHeader"]


@dataclass(frozen=True)
class QuickTimeTrackHeaderDateAssignment:
    tag_name: QuickTimeHeaderDateTag
    value: str | None
    track_index: int | None = None


@dataclass(frozen=True)
class QuickTimeHeaderDateBlocker:
    code: QuickTimeHeaderDateBlockerCode
    tag_name: QuickTimeHeaderDateTag | None
    header_kind: QuickTimeDateHeaderKind | None
    track_index: int | None
    message: str


@dataclass(frozen=True)
class QuickTimeTrackHeaderDateRewriteResult:
    data: bytes
    changed_movie_headers: int = 0
    changed_track_headers: int = 0
    changed_media_headers: int = 0
    blockers: tuple[QuickTimeHeaderDateBlocker, ...] = ()

    @property
    def changed_headers(self) -> int:
        return self.changed_movie_headers + self.changed_track_headers + self.changed_media_headers


@dataclass(frozen=True)
class HeaderDateLayout:
    header_kind: QuickTimeDateHeaderKind
    create_date_offset: int
    modify_date_offset: int
    date_byte_count: int


def rewrite_quicktime_track_header_dates(
    data: bytes,
    assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...],
) -> QuickTimeTrackHeaderDateRewriteResult:
    return rewrite_quicktime_header_dates(data, assignments)


def rewrite_quicktime_header_dates(
    data: bytes,
    assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...],
) -> QuickTimeTrackHeaderDateRewriteResult:
    if not assignments:
        return QuickTimeTrackHeaderDateRewriteResult(data=data)
    validation_blockers = validate_assignments(assignments)
    if validation_blockers:
        return QuickTimeTrackHeaderDateRewriteResult(data=data, blockers=validation_blockers)
    try:
        rewritten_atoms, changed = rewrite_top_level_atoms(read_quicktime_atoms(data), assignments)
    except QuickTimeHeaderDateRewriteError as error:
        return QuickTimeTrackHeaderDateRewriteResult(data=data, blockers=(error.blocker,))
    return QuickTimeTrackHeaderDateRewriteResult(
        data=encode_quicktime_atoms(rewritten_atoms),
        changed_movie_headers=changed.changed_movie_headers,
        changed_track_headers=changed.changed_track_headers,
        changed_media_headers=changed.changed_media_headers,
    )


def validate_assignments(
    assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...],
) -> tuple[QuickTimeHeaderDateBlocker, ...]:
    blockers: list[QuickTimeHeaderDateBlocker] = []
    for assignment in assignments:
        if assignment.value is None:
            continue
        if date_value_has_timezone(assignment.value):
            blockers.append(
                QuickTimeHeaderDateBlocker(
                    code="unsupported_quicktime_date_timezone",
                    tag_name=assignment.tag_name,
                    header_kind=None,
                    track_index=assignment.track_index,
                    message=(
                        f"QuickTime {assignment.tag_name} value {assignment.value!r} carries an "
                        "explicit timezone; this writer only supports "
                        "Exif"
                        "Tool's local-time "
                        "header date write shape without QuickTimeUTC."
                    ),
                )
            )
            continue
        try:
            quicktime_date_value(assignment.value)
        except ValueError:
            blockers.append(
                QuickTimeHeaderDateBlocker(
                    code="invalid_quicktime_date_value",
                    tag_name=assignment.tag_name,
                    header_kind=None,
                    track_index=assignment.track_index,
                    message=(
                        f"QuickTime {assignment.tag_name} value {assignment.value!r} is not a "
                        "supported 'YYYY:MM:DD HH:MM:SS' date."
                    ),
                )
            )
    return tuple(blockers)


@dataclass(frozen=True)
class ChangedHeaderCounts:
    changed_movie_headers: int = 0
    changed_track_headers: int = 0
    changed_media_headers: int = 0

    def add(self, other: ChangedHeaderCounts) -> ChangedHeaderCounts:
        return ChangedHeaderCounts(
            changed_movie_headers=self.changed_movie_headers + other.changed_movie_headers,
            changed_track_headers=self.changed_track_headers + other.changed_track_headers,
            changed_media_headers=self.changed_media_headers + other.changed_media_headers,
        )


class QuickTimeHeaderDateRewriteError(Exception):
    def __init__(self, blocker: QuickTimeHeaderDateBlocker) -> None:
        self.blocker = blocker
        super().__init__(blocker.message)


def rewrite_top_level_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...],
) -> tuple[tuple[QuickTimeAtom, ...], ChangedHeaderCounts]:
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_counts = ChangedHeaderCounts()
    for atom in atoms:
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten_atoms.append(atom)
            continue
        movie_atoms, changed = rewrite_movie_atoms(read_quicktime_atoms(atom.payload), assignments)
        rewritten_atoms.append(QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(movie_atoms)))
        changed_counts = changed_counts.add(changed)
    return tuple(rewritten_atoms), changed_counts


def rewrite_movie_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...],
) -> tuple[tuple[QuickTimeAtom, ...], ChangedHeaderCounts]:
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_counts = ChangedHeaderCounts()
    track_index = 0
    for atom in atoms:
        if atom.atom_type == QT_MOVIE_HEADER_ATOM:
            rewritten_payload = rewrite_header_payload(
                atom.payload,
                movie_header_date_layout(atom.payload),
                assignments_for_tags(assignments, ("CreateDate", "ModifyDate"), None),
                None,
            )
            rewritten_atoms.append(QuickTimeAtom(atom.atom_type, rewritten_payload))
            if rewritten_payload != atom.payload:
                changed_counts = changed_counts.add(ChangedHeaderCounts(changed_movie_headers=1))
            continue
        if atom.atom_type != QT_TRACK_ATOM:
            rewritten_atoms.append(atom)
            continue
        track_index += 1
        track_atoms, changed = rewrite_track_atoms(
            read_quicktime_atoms(atom.payload),
            assignments_for_track(assignments, track_index),
            track_index,
        )
        rewritten_atoms.append(QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(track_atoms)))
        changed_counts = changed_counts.add(changed)
    return tuple(rewritten_atoms), changed_counts


def assignments_for_track(
    assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...],
    track_index: int,
) -> tuple[QuickTimeTrackHeaderDateAssignment, ...]:
    return tuple(
        assignment
        for assignment in assignments
        if assignment.track_index is None or assignment.track_index == track_index
    )


def assignments_for_tags(
    assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...],
    tag_names: tuple[QuickTimeHeaderDateTag, ...],
    track_index: int | None,
) -> tuple[QuickTimeTrackHeaderDateAssignment, ...]:
    return tuple(
        assignment
        for assignment in assignments
        if assignment.tag_name in tag_names
        and (assignment.track_index is None or assignment.track_index == track_index)
    )


def rewrite_track_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...],
    track_index: int,
) -> tuple[tuple[QuickTimeAtom, ...], ChangedHeaderCounts]:
    if not assignments:
        return atoms, ChangedHeaderCounts()
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_counts = ChangedHeaderCounts()
    for atom in atoms:
        if atom.atom_type == QT_TRACK_HEADER_ATOM:
            rewritten_payload = rewrite_header_payload(
                atom.payload,
                track_header_date_layout(atom.payload),
                assignments_for_tags(
                    assignments,
                    ("TrackCreateDate", "TrackModifyDate"),
                    track_index,
                ),
                track_index,
            )
            rewritten_atoms.append(QuickTimeAtom(atom.atom_type, rewritten_payload))
            if rewritten_payload != atom.payload:
                changed_counts = changed_counts.add(ChangedHeaderCounts(changed_track_headers=1))
            continue
        if atom.atom_type != QT_MEDIA_ATOM:
            rewritten_atoms.append(atom)
            continue
        media_atoms, changed = rewrite_media_atoms(
            read_quicktime_atoms(atom.payload),
            assignments_for_tags(assignments, ("MediaCreateDate", "MediaModifyDate"), track_index),
            track_index,
        )
        rewritten_atoms.append(QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(media_atoms)))
        changed_counts = changed_counts.add(changed)
    return tuple(rewritten_atoms), changed_counts


def rewrite_media_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...],
    track_index: int,
) -> tuple[tuple[QuickTimeAtom, ...], ChangedHeaderCounts]:
    if not assignments:
        return atoms, ChangedHeaderCounts()
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_counts = ChangedHeaderCounts()
    for atom in atoms:
        if atom.atom_type != QT_MEDIA_HEADER_ATOM:
            rewritten_atoms.append(atom)
            continue
        rewritten_payload = rewrite_header_payload(
            atom.payload,
            media_header_date_layout(atom.payload),
            assignments,
            track_index,
        )
        rewritten_atoms.append(QuickTimeAtom(atom.atom_type, rewritten_payload))
        if rewritten_payload != atom.payload:
            changed_counts = changed_counts.add(ChangedHeaderCounts(changed_media_headers=1))
    return tuple(rewritten_atoms), changed_counts


def rewrite_header_payload(
    payload: bytes,
    layout: HeaderDateLayout,
    assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...],
    track_index: int | None,
) -> bytes:
    if not assignments:
        return payload
    rewritten = bytearray(payload)
    for assignment in assignments:
        value = quicktime_date_value(assignment.value)
        if assignment.tag_name.endswith("CreateDate"):
            offset = layout.create_date_offset
        elif assignment.tag_name.endswith("ModifyDate"):
            offset = layout.modify_date_offset
        else:
            continue
        rewritten[offset : offset + layout.date_byte_count] = value.to_bytes(
            layout.date_byte_count,
            "big",
        )
    return bytes(rewritten)


def movie_header_date_layout(payload: bytes) -> HeaderDateLayout:
    return header_date_layout(payload, "MovieHeader", QT_MOVIE_HEADER_ATOM)


def track_header_date_layout(payload: bytes) -> HeaderDateLayout:
    return header_date_layout(payload, "TrackHeader", QT_TRACK_HEADER_ATOM)


def media_header_date_layout(payload: bytes) -> HeaderDateLayout:
    return header_date_layout(payload, "MediaHeader", QT_MEDIA_HEADER_ATOM)


def header_date_layout(
    payload: bytes,
    header_kind: QuickTimeDateHeaderKind,
    atom_type: str,
) -> HeaderDateLayout:
    if len(payload) < 12:
        raise_rewrite_blocker(
            "truncated_quicktime_header_dates",
            header_kind,
            f"Truncated QuickTime {atom_type} date fields.",
        )
    version = payload[0]
    if version == 0:
        return HeaderDateLayout(
            header_kind=header_kind,
            create_date_offset=4,
            modify_date_offset=8,
            date_byte_count=4,
        )
    if version == 1:
        if len(payload) < 20:
            raise_rewrite_blocker(
                "truncated_quicktime_header_dates",
                header_kind,
                f"Truncated QuickTime version 1 {atom_type} date fields.",
            )
        return HeaderDateLayout(
            header_kind=header_kind,
            create_date_offset=4,
            modify_date_offset=12,
            date_byte_count=8,
        )
    raise_rewrite_blocker(
        "unsupported_quicktime_header_version",
        header_kind,
        f"Unsupported QuickTime {atom_type} version: {version}.",
    )


def raise_rewrite_blocker(
    code: QuickTimeHeaderDateBlockerCode,
    header_kind: QuickTimeDateHeaderKind,
    message: str,
) -> NoReturn:
    raise QuickTimeHeaderDateRewriteError(
        QuickTimeHeaderDateBlocker(
            code=code,
            tag_name=None,
            header_kind=header_kind,
            track_index=None,
            message=message,
        )
    )


def quicktime_date_value(value: str | None) -> int:
    if value is None or value == "0000:00:00 00:00:00":
        return 0
    parsed = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    return int(parsed.replace(tzinfo=UTC).timestamp()) + QT_QUICKTIME_EPOCH_DELTA_SECONDS


def date_value_has_timezone(value: str) -> bool:
    return value.endswith("Z") or "+" in value[19:] or "-" in value[19:]
