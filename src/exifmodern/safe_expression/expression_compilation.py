"""Generic expression bytecode compilation helpers."""

from __future__ import annotations

from collections.abc import Callable

from exifmodern.safe_expression.ast import (
    AstNode,
    BitwiseExpression,
    ComparisonExpression,
    CompiledNode,
    CompileState,
    LocalArrayValue,
    NumericExpression,
    NumericUnaryExpression,
    StringConcatExpression,
    StringRepeatExpression,
    TernaryExpression,
    TruthyAndExpression,
    TruthyNotExpression,
    TruthyOrExpression,
    UndefLiteral,
)
from exifmodern.safe_expression.bytecode import (
    BitwiseBinary,
    Compare,
    LazyTernary,
    LazyTruthyAnd,
    LazyTruthyOr,
    ListLength,
    MapList,
    NumericBinary,
    NumericBinaryIfTruthy,
    NumericUnary,
    StringConcat,
    StringRepeat,
    TruthyNot,
)
from exifmodern.safe_expression.compile_state import (
    append_instruction,
    branch_compile_state,
)
from exifmodern.safe_expression.operators import (
    NUMERIC_COMPARISON_SYMBOLS,
    bitwise_operator,
    comparison_operator,
    numeric_operator,
    numeric_unary_operator,
)


def compile_map_list(
    source: str,
    expression: AstNode,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    item_register = f"r{state.next_register + 1}"
    item = compile_node(
        expression,
        CompileState(
            instructions=[],
            next_register=state.next_register + 2,
            local_arrays=state.local_arrays,
            local_scalars=state.local_scalars,
            input_overrides=state.input_overrides,
            current_item_register=item_register,
        ),
    )
    return append_instruction(
        state,
        lambda register: MapList(
            register,
            source,
            item_register,
            item.state.instructions,
            item.register,
        ),
    )


def compile_numeric_expression(
    ast: NumericExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    left = compile_numeric_context_node(ast.left, state, compile_node=compile_node)
    right = compile_numeric_context_node(ast.right, left.state, compile_node=compile_node)
    return append_instruction(
        right.state,
        lambda register: NumericBinary(
            register,
            left.register,
            numeric_operator(ast.operator),
            right.register,
        ),
    )


def compile_numeric_unary_expression(
    ast: NumericUnaryExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    value = compile_numeric_context_node(ast.value, state, compile_node=compile_node)
    return append_instruction(
        value.state,
        lambda register: NumericUnary(
            register,
            numeric_unary_operator(ast.operator),
            value.register,
        ),
    )


def compile_comparison_expression(
    ast: ComparisonExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    if ast.operator in NUMERIC_COMPARISON_SYMBOLS:
        left = compile_numeric_context_node(ast.left, state, compile_node=compile_node)
        right = compile_numeric_context_node(ast.right, left.state, compile_node=compile_node)
    else:
        left = compile_node(ast.left, state)
        right = compile_node(ast.right, left.state)
    return append_instruction(
        right.state,
        lambda register: Compare(
            register,
            left.register,
            comparison_operator(ast.operator),
            right.register,
        ),
    )


def compile_bitwise_expression(
    ast: BitwiseExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    left = compile_numeric_context_node(ast.left, state, compile_node=compile_node)
    right = compile_numeric_context_node(ast.right, left.state, compile_node=compile_node)
    return append_instruction(
        right.state,
        lambda register: BitwiseBinary(
            register,
            left.register,
            bitwise_operator(ast.operator),
            right.register,
        ),
    )


def compile_string_concat_expression(
    ast: StringConcatExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    left = compile_node(ast.left, state)
    right = compile_node(ast.right, left.state)
    return append_instruction(
        right.state,
        lambda register: StringConcat(register, left.register, right.register),
    )


def compile_string_repeat_expression(
    ast: StringRepeatExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    value = compile_node(ast.value, state)
    count = compile_numeric_context_node(ast.count, value.state, compile_node=compile_node)
    return append_instruction(
        count.state,
        lambda register: StringRepeat(register, value.register, count.register),
    )


def compile_numeric_context_node(
    ast: AstNode,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    compiled = compile_node(ast, state)
    if isinstance(ast, LocalArrayValue):
        return append_instruction(
            compiled.state,
            lambda register: ListLength(register, compiled.register),
        )
    return compiled


def compile_truthy_and_expression(
    ast: TruthyAndExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    left = compile_node(ast.left, state)
    right = compile_node(
        ast.right,
        branch_compile_state(
            left.state.next_register,
            left.state.local_arrays,
            left.state.local_scalars,
            left.state.input_overrides,
            left.state.current_item_register,
        ),
    )
    return append_instruction(
        CompileState(
            instructions=left.state.instructions,
            next_register=right.state.next_register,
            local_arrays=left.state.local_arrays,
            local_scalars=left.state.local_scalars,
            input_overrides=left.state.input_overrides,
            current_item_register=left.state.current_item_register,
        ),
        lambda register: LazyTruthyAnd(
            register,
            left.register,
            right.state.instructions,
            right.register,
        ),
    )


def compile_truthy_not_expression(
    ast: TruthyNotExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    value = compile_node(ast.value, state)
    return append_instruction(
        value.state,
        lambda register: TruthyNot(register, value.register),
    )


def compile_truthy_or_expression(
    ast: TruthyOrExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    left = compile_node(ast.left, state)
    right = compile_node(
        ast.right,
        branch_compile_state(
            left.state.next_register,
            left.state.local_arrays,
            left.state.local_scalars,
            left.state.input_overrides,
            left.state.current_item_register,
        ),
    )
    return append_instruction(
        CompileState(
            instructions=left.state.instructions,
            next_register=right.state.next_register,
            local_arrays=left.state.local_arrays,
            local_scalars=left.state.local_scalars,
            input_overrides=left.state.input_overrides,
            current_item_register=left.state.current_item_register,
        ),
        lambda register: LazyTruthyOr(
            register,
            left.register,
            right.state.instructions,
            right.register,
        ),
    )


def compile_ternary_expression(
    ast: TernaryExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    guarded = compile_guarded_numeric_ternary(ast, state, compile_node=compile_node)
    if guarded is not None:
        return guarded
    condition = compile_node(ast.condition, state)
    true_expression = compile_node(
        ast.true_expression,
        branch_compile_state(
            condition.state.next_register,
            condition.state.local_arrays,
            condition.state.local_scalars,
            condition.state.input_overrides,
            condition.state.current_item_register,
        ),
    )
    false_expression = compile_node(
        ast.false_expression,
        branch_compile_state(
            true_expression.state.next_register,
            condition.state.local_arrays,
            condition.state.local_scalars,
            condition.state.input_overrides,
            condition.state.current_item_register,
        ),
    )
    return append_instruction(
        CompileState(
            instructions=condition.state.instructions,
            next_register=false_expression.state.next_register,
            local_arrays=condition.state.local_arrays,
            local_scalars=condition.state.local_scalars,
            input_overrides=condition.state.input_overrides,
            current_item_register=condition.state.current_item_register,
        ),
        lambda register: LazyTernary(
            register,
            condition.register,
            true_expression.state.instructions,
            true_expression.register,
            false_expression.state.instructions,
            false_expression.register,
        ),
    )


def compile_guarded_numeric_ternary(
    ast: TernaryExpression,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode | None:
    if not isinstance(ast.true_expression, NumericExpression):
        return None
    if not isinstance(ast.false_expression, UndefLiteral):
        return None
    if ast.true_expression.operator != "/":
        return None
    condition = compile_node(ast.condition, state)
    left = compile_node(ast.true_expression.left, condition.state)
    right = compile_node(ast.true_expression.right, left.state)
    return append_instruction(
        right.state,
        lambda register: NumericBinaryIfTruthy(
            register,
            condition.register,
            left.register,
            "div",
            right.register,
            None,
        ),
    )
