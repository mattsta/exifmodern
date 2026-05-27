"""Operator and function mapping helpers for safe-expression compilation."""

from __future__ import annotations

from exifmodern.safe_expression.ast import (
    BitwiseSymbol,
    ComparisonSymbol,
    ListIndexBitwiseTransformSymbol,
    ListTransformSymbol,
    NumericSymbol,
    NumericUnarySymbol,
)
from exifmodern.safe_expression.bytecode import (
    BinaryNumericFunction,
    BinaryReadKind,
    BitwiseOperator,
    ComparisonOperator,
    NumericOperator,
    NumericUnaryOperator,
    UnaryNumericFunction,
    UnaryScalarFunction,
)
from exifmodern.safe_expression.errors import SafeExpressionCompileError

NUMERIC_COMPARISON_SYMBOLS: frozenset[ComparisonSymbol] = frozenset(
    {"==", "!=", "<", "<=", ">", ">="}
)


def indexed_numeric_operator(operator: ListTransformSymbol) -> NumericOperator:
    if operator == "/=":
        return "div"
    if operator == "*=":
        return "mul"
    if operator == "+=":
        return "add"
    if operator == "-=":
        return "sub"
    raise SafeExpressionCompileError(f"Unsupported indexed list transform operator: {operator}")


def indexed_bitwise_operator(operator: ListIndexBitwiseTransformSymbol) -> BitwiseOperator:
    if operator == "&=":
        return "bit_and"
    if operator == "|=":
        return "bit_or"
    if operator == "^=":
        return "bit_xor"
    raise SafeExpressionCompileError(f"Unsupported indexed list bitwise operator: {operator}")


def numeric_operator(operator: NumericSymbol) -> NumericOperator:
    if operator == "+":
        return "add"
    if operator == "-":
        return "sub"
    if operator == "*":
        return "mul"
    if operator == "/":
        return "div"
    if operator == "%":
        return "mod"
    if operator == "**":
        return "pow"
    raise SafeExpressionCompileError(f"Unsupported numeric operator: {operator}")


def numeric_unary_operator(operator: NumericUnarySymbol) -> NumericUnaryOperator:
    if operator == "-":
        return "neg"
    if operator == "+":
        return "pos"
    raise SafeExpressionCompileError(f"Unsupported numeric unary operator: {operator}")


def bitwise_operator(operator: BitwiseSymbol) -> BitwiseOperator:
    if operator == "&":
        return "bit_and"
    if operator == "|":
        return "bit_or"
    if operator == "^":
        return "bit_xor"
    if operator == "<<":
        return "shift_left"
    if operator == ">>":
        return "shift_right"
    raise SafeExpressionCompileError(f"Unsupported bitwise operator: {operator}")


def comparison_operator(operator: ComparisonSymbol) -> ComparisonOperator:
    if operator == "==":
        return "num_eq"
    if operator == "!=":
        return "num_ne"
    if operator == "<":
        return "lt"
    if operator == "<=":
        return "le"
    if operator == ">":
        return "gt"
    if operator == ">=":
        return "ge"
    if operator == "eq":
        return "str_eq"
    if operator == "ne":
        return "str_ne"
    if operator == "lt":
        return "str_lt"
    if operator == "le":
        return "str_le"
    if operator == "gt":
        return "str_gt"
    if operator == "ge":
        return "str_ge"
    raise SafeExpressionCompileError(f"Unsupported comparison operator: {operator}")


def unary_numeric_function(name: str) -> UnaryNumericFunction:
    if name == "int":
        return "int"
    if name == "log":
        return "log"
    if name == "exp":
        return "exp"
    if name == "sqrt":
        return "sqrt"
    raise SafeExpressionCompileError(f"Unsupported unary numeric function: {name}")


def binary_numeric_function(name: str) -> BinaryNumericFunction:
    if name == "atan2":
        return "atan2"
    raise SafeExpressionCompileError(f"Unsupported binary numeric function: {name}")


def binary_read_kind_or_none(name: str) -> BinaryReadKind | None:
    if name == "Get8u":
        return "uint8"
    if name == "Get16s":
        return "int16"
    if name == "Get16u":
        return "uint16"
    if name == "Get32u":
        return "uint32"
    if name == "GetFloat":
        return "float32"
    if name == "GetDouble":
        return "float64"
    return None


def unary_scalar_function(name: str) -> UnaryScalarFunction:
    if name == "abs":
        return "abs"
    if name == "length":
        return "length"
    if name == "chr":
        return "chr"
    if name == "defined":
        return "defined"
    if name == "hex":
        return "hex"
    if name == "getgrgid":
        return "getgrgid"
    if name == "getpwuid":
        return "getpwuid"
    if name == "oct":
        return "oct"
    if name == "IsInt":
        return "is_int"
    if name == "IsFloat":
        return "is_float"
    if name == "lc":
        return "lc"
    if name == "ord":
        return "ord"
    if name == "ref":
        return "ref"
    if name == "uc":
        return "uc"
    if name == "ucfirst":
        return "ucfirst"
    raise SafeExpressionCompileError(f"Unsupported unary scalar function: {name}")
