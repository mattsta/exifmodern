"""Typed binary decoding helpers shared by parser modules."""

from __future__ import annotations

import math
from typing import Literal

type ByteOrder = Literal["little", "big"]


def ieee754_float(
    raw_value: bytes, byte_order: ByteOrder, exponent_bits: int, fraction_bits: int
) -> float:
    packed = int.from_bytes(raw_value, byte_order)
    sign_bit = 1 << (exponent_bits + fraction_bits)
    sign = -1.0 if packed & sign_bit else 1.0
    exponent_mask = (1 << exponent_bits) - 1
    fraction_mask = (1 << fraction_bits) - 1
    exponent = (packed >> fraction_bits) & exponent_mask
    fraction = packed & fraction_mask
    exponent_bias = (1 << (exponent_bits - 1)) - 1
    if exponent == exponent_mask:
        return sign * math.inf if fraction == 0 else math.nan
    if exponent == 0:
        return sign * math.ldexp(float(fraction), 1 - exponent_bias - fraction_bits)
    mantissa = (1 << fraction_bits) + fraction
    return sign * math.ldexp(float(mantissa), exponent - exponent_bias - fraction_bits)


def ieee754_float32(raw_value: bytes, byte_order: ByteOrder) -> float:
    return ieee754_float(raw_value, byte_order, exponent_bits=8, fraction_bits=23)


def ieee754_float64(raw_value: bytes, byte_order: ByteOrder) -> float:
    return ieee754_float(raw_value, byte_order, exponent_bits=11, fraction_bits=52)
