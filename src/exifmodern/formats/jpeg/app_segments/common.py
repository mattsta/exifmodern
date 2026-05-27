"""Shared helpers for JPEG APP-segment readers."""

from __future__ import annotations


def jfif_resolution_unit(value: int) -> str | int:
    return {
        0: "None",
        1: "inches",
        2: "cm",
    }.get(value, value)
