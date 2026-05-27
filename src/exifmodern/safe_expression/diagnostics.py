"""Parse diagnostic helpers for safe-expression AST roots."""

from __future__ import annotations

from exifmodern.safe_expression.ast import (
    ArrayConditionalTransformTail,
    AstNode,
    DynamicRuntimeContextKey,
    ExpressionList,
    ForeachArrayName,
    ForeachArraySetBlock,
    ForeachLiteralValues,
    ForeachReturnBlock,
    LocalScalarTarget,
    LocalScalarTargetList,
    PairwiseArrayRange,
    PairwiseArrayRef,
    PairwiseArraySubtract,
    RequiredModule,
    RuntimeContextPath,
    StaticRuntimeContextKey,
    TransformNode,
)
from exifmodern.safe_expression.errors import SafeExpressionCompileError

INVALID_EXPRESSION_ROOT_TYPES = (
    RequiredModule,
    PairwiseArrayRef,
    PairwiseArraySubtract,
    PairwiseArrayRange,
    LocalScalarTarget,
    LocalScalarTargetList,
    ExpressionList,
    ForeachLiteralValues,
    ArrayConditionalTransformTail,
    ForeachReturnBlock,
    ForeachArrayName,
    ForeachArraySetBlock,
    StaticRuntimeContextKey,
    DynamicRuntimeContextKey,
    RuntimeContextPath,
)


def require_expression_root(node: TransformNode) -> AstNode:
    if isinstance(node, INVALID_EXPRESSION_ROOT_TYPES):
        raise SafeExpressionCompileError("Require prefix must be followed by an expression.")
    return node
