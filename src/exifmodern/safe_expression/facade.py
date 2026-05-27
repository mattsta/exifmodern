"""Parse and compile facade helpers for safe-expression programs."""

from __future__ import annotations

from lark import Lark
from lark.exceptions import LarkError, VisitError

from exifmodern.safe_expression.ast import AstNode, CompileState, TransformNode
from exifmodern.safe_expression.bytecode import SafeExpressionProgram
from exifmodern.safe_expression.diagnostics import require_expression_root
from exifmodern.safe_expression.errors import SafeExpressionCompileError
from exifmodern.safe_expression.grammar import (
    safe_expression_earley_parser,
    safe_expression_lalr_parser,
    safe_expression_parser,
)


def compile_safe_expression(summary: str) -> SafeExpressionProgram | None:
    try:
        ast = parse_safe_expression(summary)
        return compile_ast(ast)
    except LarkError, VisitError, SafeExpressionCompileError, ValueError:
        return None


def compile_safe_filter_expression(expression: str) -> SafeExpressionProgram | None:
    if not expression:
        return None
    # ExifTool Filter evals with $_ set to the value and expects $_ as the output.
    # Source: ../exiftool/lib/Image/ExifTool.pm lines 6497-6523.
    return compile_safe_expression(f"$_ = $val; {expression}; $_")


def parse_safe_expression(summary: str) -> AstNode:
    return require_expression_root(transform_safe_expression(summary))


def transform_safe_expression(summary: str) -> TransformNode:
    try:
        tree = safe_expression_lalr_parser().parse(summary)
    except LarkError:
        tree = safe_expression_earley_parser().parse(summary)

    from exifmodern.safe_expression.transformer import SafeExpressionAstTransformer

    return SafeExpressionAstTransformer().transform(tree)


def parser() -> Lark:
    return safe_expression_parser()


def fallback_parser() -> Lark:
    return safe_expression_earley_parser()


def compile_ast(ast: AstNode) -> SafeExpressionProgram:
    from exifmodern.safe_expression.compiler import compile_node

    compiled = compile_node(ast, CompileState(instructions=[], next_register=0))
    return SafeExpressionProgram(instructions=compiled.state.instructions, result=compiled.register)
