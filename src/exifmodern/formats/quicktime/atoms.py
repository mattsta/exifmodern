"""Reusable QuickTime/ISO BMFF atom parsing and encoding primitives."""

from __future__ import annotations

from dataclasses import dataclass

QT_ATOM_HEADER_SIZE = 8
QT_EXTENDED_ATOM_HEADER_SIZE = 16


@dataclass(frozen=True)
class QuickTimeAtom:
    atom_type: str
    payload: bytes


def read_quicktime_atoms(data: bytes) -> tuple[QuickTimeAtom, ...]:
    atoms: list[QuickTimeAtom] = []
    offset = 0
    while offset < len(data):
        atom, next_offset = read_quicktime_atom(data, offset)
        atoms.append(atom)
        offset = next_offset
    return tuple(atoms)


def read_quicktime_atom(data: bytes, offset: int) -> tuple[QuickTimeAtom, int]:
    if offset + QT_ATOM_HEADER_SIZE > len(data):
        raise ValueError("Truncated QuickTime atom header.")
    atom_size = int.from_bytes(data[offset : offset + 4], "big")
    atom_type = data[offset + 4 : offset + 8].decode("latin-1")
    if atom_size == 0:
        atom_end = len(data)
        payload_offset = offset + QT_ATOM_HEADER_SIZE
    elif atom_size == 1:
        if offset + QT_EXTENDED_ATOM_HEADER_SIZE > len(data):
            raise ValueError("Truncated QuickTime extended atom header.")
        extended_size = int.from_bytes(data[offset + 8 : offset + 16], "big")
        if extended_size > 0xFFFFFFFF:
            raise ValueError("QuickTime atoms larger than 4 GB are not supported.")
        atom_end = offset + extended_size
        payload_offset = offset + QT_EXTENDED_ATOM_HEADER_SIZE
    else:
        atom_end = offset + atom_size
        payload_offset = offset + QT_ATOM_HEADER_SIZE
    if atom_end < payload_offset or atom_end > len(data):
        raise ValueError(f"Invalid QuickTime atom length for {atom_type!r}.")
    return QuickTimeAtom(atom_type=atom_type, payload=data[payload_offset:atom_end]), atom_end


def encode_quicktime_atom(atom_type: str, payload: bytes) -> bytes:
    if len(atom_type) != 4:
        raise ValueError("QuickTime atom types must be four characters.")
    atom_size = len(payload) + QT_ATOM_HEADER_SIZE
    if atom_size > 0xFFFFFFFF:
        raise ValueError("QuickTime atoms larger than 4 GB are not supported.")
    return atom_size.to_bytes(4, "big") + atom_type.encode("latin-1") + payload


def encode_quicktime_atoms(atoms: tuple[QuickTimeAtom, ...]) -> bytes:
    return b"".join(encode_quicktime_atom(atom.atom_type, atom.payload) for atom in atoms)
