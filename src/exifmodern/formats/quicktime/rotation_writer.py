"""Source-grounded QuickTime Rotation writer."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.quicktime.atoms import (
    QuickTimeAtom,
    encode_quicktime_atoms,
    read_quicktime_atoms,
)

type QuickTimeRotationDegrees = Literal[0, 90, 180, 270]

QT_MOVIE_ATOM = "moov"
QT_TRACK_ATOM = "trak"
QT_MEDIA_ATOM = "mdia"
QT_HANDLER_ATOM = "hdlr"
QT_TRACK_HEADER_ATOM = "tkhd"
QT_VIDEO_HANDLER = "vide"
QT_MATRIX_ELEMENT_COUNT = 9
QT_FIXED_16_16_SCALE = 0x10000
QT_FIXED_2_30_SCALE = 0x40000000
QT_MATRIX_2_30_INDICES = {2, 5, 8}


@dataclass(frozen=True)
class QuickTimeRotationWritePlan:
    rotation_degrees: QuickTimeRotationDegrees


@dataclass(frozen=True)
class QuickTimeRotationRewriteResult:
    data: bytes
    changed_track_headers: int
    transaction: FileWriteTransactionResult | None = None


def rewrite_quicktime_rotation(
    data: bytes,
    plan: QuickTimeRotationWritePlan,
) -> QuickTimeRotationRewriteResult:
    atoms = read_quicktime_atoms(data)
    rewritten_atoms, changed_track_headers = rewrite_movie_atoms_for_rotation(atoms, plan)
    return QuickTimeRotationRewriteResult(
        data=encode_quicktime_atoms(rewritten_atoms),
        changed_track_headers=changed_track_headers,
    )


def rewrite_quicktime_file_rotation(
    input_path: Path,
    output_path: Path,
    plan: QuickTimeRotationWritePlan,
) -> QuickTimeRotationRewriteResult:
    result = rewrite_quicktime_rotation(input_path.read_bytes(), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return QuickTimeRotationRewriteResult(
        data=result.data,
        changed_track_headers=result.changed_track_headers,
        transaction=transaction,
    )


def rewrite_movie_atoms_for_rotation(
    atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeRotationWritePlan,
) -> tuple[tuple[QuickTimeAtom, ...], int]:
    rewritten: list[QuickTimeAtom] = []
    changed_track_headers = 0
    for atom in atoms:
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten.append(atom)
            continue
        moov_atoms = read_quicktime_atoms(atom.payload)
        rewritten_moov_atoms, changed = rewrite_tracks_for_rotation(moov_atoms, plan)
        rewritten.append(
            QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(rewritten_moov_atoms))
        )
        changed_track_headers += changed
    return tuple(rewritten), changed_track_headers


def rewrite_tracks_for_rotation(
    atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeRotationWritePlan,
) -> tuple[tuple[QuickTimeAtom, ...], int]:
    rewritten: list[QuickTimeAtom] = []
    changed_track_headers = 0
    for atom in atoms:
        if atom.atom_type != QT_TRACK_ATOM:
            rewritten.append(atom)
            continue
        track_atoms = read_quicktime_atoms(atom.payload)
        rewritten_track_atoms, changed = rewrite_track_header_for_rotation(track_atoms, plan)
        rewritten.append(
            QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(rewritten_track_atoms))
        )
        changed_track_headers += changed
    return tuple(rewritten), changed_track_headers


def rewrite_track_header_for_rotation(
    atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeRotationWritePlan,
) -> tuple[tuple[QuickTimeAtom, ...], int]:
    rewritten: list[QuickTimeAtom] = []
    changed_track_headers = 0
    for atom in atoms:
        if atom.atom_type != QT_TRACK_HEADER_ATOM:
            rewritten.append(atom)
            continue
        rewritten_payload = rewrite_track_header_payload(atom.payload, plan)
        rewritten.append(QuickTimeAtom(atom.atom_type, rewritten_payload))
        changed_track_headers += 1 if rewritten_payload != atom.payload else 0
    return tuple(rewritten), changed_track_headers


def rewrite_track_header_payload(
    payload: bytes,
    plan: QuickTimeRotationWritePlan,
) -> bytes:
    layout = track_header_layout(payload)
    current_matrix = decode_quicktime_matrix(
        payload[layout.matrix_offset : layout.matrix_offset + 36]
    )
    if current_matrix[6] != 0 or current_matrix[7] != 0:
        return payload
    width = fixed_16_16_to_float(payload[layout.width_offset : layout.width_offset + 4])
    height = fixed_16_16_to_float(payload[layout.height_offset : layout.height_offset + 4])
    if width == 0 or height == 0:
        return payload
    matrix = rotation_matrix_with_offsets(plan.rotation_degrees, width, height)
    return (
        payload[: layout.matrix_offset]
        + encode_quicktime_matrix(matrix)
        + payload[layout.matrix_offset + 36 :]
    )


@dataclass(frozen=True)
class TrackHeaderLayout:
    matrix_offset: int
    width_offset: int
    height_offset: int


def track_header_layout(payload: bytes) -> TrackHeaderLayout:
    if len(payload) < 4:
        raise ValueError("Truncated QuickTime tkhd full atom header.")
    version = payload[0]
    if version == 0:
        matrix_offset = 40
    elif version == 1:
        matrix_offset = 52
    else:
        raise ValueError(f"Unsupported QuickTime tkhd version: {version}.")
    width_offset = matrix_offset + 36
    height_offset = width_offset + 4
    if height_offset + 4 > len(payload):
        raise ValueError("Truncated QuickTime tkhd matrix/size fields.")
    return TrackHeaderLayout(
        matrix_offset=matrix_offset,
        width_offset=width_offset,
        height_offset=height_offset,
    )


def quicktime_track_handler_type(atoms: tuple[QuickTimeAtom, ...]) -> str | None:
    for atom in atoms:
        if atom.atom_type != QT_MEDIA_ATOM:
            continue
        for media_atom in read_quicktime_atoms(atom.payload):
            if media_atom.atom_type == QT_HANDLER_ATOM:
                return quicktime_handler_type(media_atom.payload)
    return None


def quicktime_handler_type(payload: bytes) -> str | None:
    if len(payload) < 12:
        return None
    return payload[8:12].decode("latin-1")


def rotation_matrix_with_offsets(
    rotation_degrees: QuickTimeRotationDegrees,
    width: float,
    height: float,
) -> tuple[float, float, float, float, float, float, float, float, float]:
    base = rotation_matrix(rotation_degrees)
    if rotation_degrees == 90:
        return (*base[:6], height, 0.0, base[8])
    if rotation_degrees == 180:
        return (*base[:6], width, height, base[8])
    if rotation_degrees == 270:
        return (*base[:6], 0.0, width, base[8])
    return base


def rotation_matrix(
    rotation_degrees: QuickTimeRotationDegrees,
) -> tuple[float, float, float, float, float, float, float, float, float]:
    angle = math.pi * rotation_degrees / 180
    cosine = rounded_zero(math.cos(angle))
    sine = rounded_zero(math.sin(angle))
    return (cosine, sine, 0.0, -sine, cosine, 0.0, 0.0, 0.0, 1.0)


def rounded_zero(value: float) -> float:
    return 0.0 if abs(value) < 1e-12 else value


def encode_quicktime_matrix(
    matrix: tuple[float, float, float, float, float, float, float, float, float],
) -> bytes:
    return b"".join(
        encode_quicktime_matrix_value(index, value) for index, value in enumerate(matrix)
    )


def encode_quicktime_matrix_value(index: int, value: float) -> bytes:
    scale = QT_FIXED_2_30_SCALE if index in QT_MATRIX_2_30_INDICES else QT_FIXED_16_16_SCALE
    raw_value = round(value * scale)
    return raw_value.to_bytes(4, "big", signed=True)


def decode_quicktime_matrix(payload: bytes) -> tuple[float, ...]:
    if len(payload) != 36:
        raise ValueError("QuickTime matrix payload must be 36 bytes.")
    return tuple(
        decode_quicktime_matrix_value(index, payload[index * 4 : index * 4 + 4])
        for index in range(QT_MATRIX_ELEMENT_COUNT)
    )


def decode_quicktime_matrix_value(index: int, payload: bytes) -> float:
    raw_value = int.from_bytes(payload, "big", signed=True)
    scale = QT_FIXED_2_30_SCALE if index in QT_MATRIX_2_30_INDICES else QT_FIXED_16_16_SCALE
    return raw_value / scale


def fixed_16_16_to_float(payload: bytes) -> float:
    return int.from_bytes(payload, "big", signed=False) / QT_FIXED_16_16_SCALE


def build_quicktime_rotation_write_plan(value: str) -> QuickTimeRotationWritePlan:
    degrees = int(value)
    if degrees == 0:
        return QuickTimeRotationWritePlan(rotation_degrees=0)
    if degrees == 90:
        return QuickTimeRotationWritePlan(rotation_degrees=90)
    if degrees == 180:
        return QuickTimeRotationWritePlan(rotation_degrees=180)
    if degrees == 270:
        return QuickTimeRotationWritePlan(rotation_degrees=270)
    raise ValueError("QuickTime Rotation must be 0, 90, 180, or 270 degrees.")
