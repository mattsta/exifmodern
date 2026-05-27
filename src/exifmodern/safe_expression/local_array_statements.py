"""Local-array statement bytecode compilation helpers."""

from __future__ import annotations

from collections.abc import Callable

from exifmodern.safe_expression.ast import (
    AstNode,
    CompiledNode,
    CompileState,
    CurrentItemReference,
    LocalArrayAssignment,
    LocalArrayConditionalTransform,
    LocalArrayEmptyAssignment,
    LocalArrayIndexedAssignment,
    LocalArrayIndexedBitwiseTransform,
    LocalArrayIndexedTransform,
    LocalArrayIndexedTransformPair,
    LocalArrayPairwiseTransform,
    LocalArrayPushWhileStatement,
    LocalArraySliceTransform,
    LocalArrayTransform,
    TernaryExpression,
)
from exifmodern.safe_expression.bytecode import (
    ListIndexBitwiseTransform,
    ListIndexNumericTransform,
    ListIndexSet,
    ListPushScalar,
    LoadConst,
    PairwiseListNumeric,
    WhileLoop,
)
from exifmodern.safe_expression.compile_state import (
    append_instruction,
    branch_compile_state,
    branch_compile_state_from,
    local_array_register,
)
from exifmodern.safe_expression.errors import SafeExpressionCompileError
from exifmodern.safe_expression.operators import (
    indexed_bitwise_operator,
    indexed_numeric_operator,
)
from exifmodern.safe_expression.statement_helpers import local_array_transform_expression

type CompileNode = Callable[[AstNode, CompileState], CompiledNode]
type CompileMapList = Callable[[str, AstNode, CompileState], CompiledNode]


def compile_local_array_assignment_statement(
    statement: LocalArrayAssignment,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    assigned_value = compile_node(statement.value, state)
    local_arrays = {
        **assigned_value.state.local_arrays,
        statement.name: assigned_value.register,
    }
    return CompileState(
        instructions=assigned_value.state.instructions,
        next_register=assigned_value.state.next_register,
        local_arrays=local_arrays,
        local_scalars=assigned_value.state.local_scalars,
        input_overrides=assigned_value.state.input_overrides,
        current_item_register=assigned_value.state.current_item_register,
    )


def compile_local_array_empty_assignment_statement(
    statement: LocalArrayEmptyAssignment,
    state: CompileState,
) -> CompileState:
    assigned_value = append_instruction(state, lambda register: LoadConst(register, []))
    return CompileState(
        instructions=assigned_value.state.instructions,
        next_register=assigned_value.state.next_register,
        local_arrays={**assigned_value.state.local_arrays, statement.name: assigned_value.register},
        local_scalars=assigned_value.state.local_scalars,
        input_overrides=assigned_value.state.input_overrides,
        current_item_register=assigned_value.state.current_item_register,
    )


def compile_local_array_transform_statement(
    statement: LocalArrayTransform,
    state: CompileState,
    *,
    compile_map_list: CompileMapList,
) -> CompileState:
    source = local_array_register(statement.name, state)
    expression = local_array_transform_expression(statement)
    mapped = compile_map_list(source, expression, state)
    return _with_local_array(mapped, statement.name)


def compile_local_array_slice_transform_statement(
    statement: LocalArraySliceTransform,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    current_state = state
    for index in statement.indexes:
        current_state = compile_local_array_indexed_transform_statement(
            LocalArrayIndexedTransform(
                name=statement.name,
                index=index,
                operator=statement.operator,
                value=statement.value,
            ),
            current_state,
            compile_node=compile_node,
        )
    return current_state


def compile_local_array_conditional_transform_statement(
    statement: LocalArrayConditionalTransform,
    state: CompileState,
    *,
    compile_map_list: CompileMapList,
) -> CompileState:
    source = local_array_register(statement.name, state)
    transformed_value = local_array_transform_expression(
        LocalArrayTransform(
            name=statement.name,
            operator=statement.operator,
            value=statement.value,
        )
    )
    expression = TernaryExpression(
        condition=statement.condition,
        true_expression=transformed_value,
        false_expression=CurrentItemReference(),
    )
    mapped = compile_map_list(source, expression, state)
    return _with_local_array(mapped, statement.name)


def compile_local_array_indexed_transform_statement(
    statement: LocalArrayIndexedTransform,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    source = local_array_register(statement.name, state)
    operand = compile_node(statement.value, state)
    transformed = append_instruction(
        operand.state,
        lambda register: ListIndexNumericTransform(
            register,
            source,
            statement.index,
            indexed_numeric_operator(statement.operator),
            operand.register,
        ),
    )
    return _with_local_array(transformed, statement.name)


def compile_local_array_indexed_bitwise_transform_statement(
    statement: LocalArrayIndexedBitwiseTransform,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    source = local_array_register(statement.name, state)
    operand = compile_node(statement.value, state)
    transformed = append_instruction(
        operand.state,
        lambda register: ListIndexBitwiseTransform(
            register,
            source,
            statement.index,
            indexed_bitwise_operator(statement.operator),
            operand.register,
        ),
    )
    return _with_local_array(transformed, statement.name)


def compile_local_array_indexed_assignment_statement(
    statement: LocalArrayIndexedAssignment,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    source = local_array_register(statement.name, state)
    item = compile_node(statement.value, state)
    assigned = append_instruction(
        item.state,
        lambda register: ListIndexSet(register, source, statement.index, item.register),
    )
    return _with_local_array(assigned, statement.name)


def compile_local_array_index_statement(
    statement: LocalArrayIndexedTransform
    | LocalArrayIndexedBitwiseTransform
    | LocalArrayIndexedAssignment,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    if isinstance(statement, LocalArrayIndexedTransform):
        return compile_local_array_indexed_transform_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalArrayIndexedBitwiseTransform):
        return compile_local_array_indexed_bitwise_transform_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    return compile_local_array_indexed_assignment_statement(
        statement,
        state,
        compile_node=compile_node,
    )


def compile_local_array_indexed_transform_pair_statement(
    statement: LocalArrayIndexedTransformPair,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    first_state = compile_local_array_index_statement(
        statement.first,
        state,
        compile_node=compile_node,
    )
    return compile_local_array_index_statement(
        statement.second,
        first_state,
        compile_node=compile_node,
    )


def compile_local_array_push_while_statement(
    statement: LocalArrayPushWhileStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    target = local_array_register(statement.name, state)
    condition = compile_node(statement.condition, branch_compile_state_from(state))
    body = compile_node(
        statement.value,
        branch_compile_state(
            condition.state.next_register,
            state.local_arrays,
            state.local_scalars,
            state.input_overrides,
            state.current_item_register,
        ),
    )
    body_instructions = [
        *body.state.instructions,
        ListPushScalar(target, target, body.register),
    ]
    return CompileState(
        instructions=[
            *state.instructions,
            WhileLoop(condition.state.instructions, condition.register, body_instructions),
        ],
        next_register=body.state.next_register,
        local_arrays=state.local_arrays,
        local_scalars=state.local_scalars,
        input_overrides=state.input_overrides,
        current_item_register=state.current_item_register,
    )


def compile_local_array_pairwise_transform_statement(
    statement: LocalArrayPairwiseTransform,
    state: CompileState,
) -> CompileState:
    if statement.target_name != statement.limit_name:
        raise SafeExpressionCompileError("Pairwise local-array transform limit must match target.")
    target = local_array_register(statement.target_name, state)
    source = local_array_register(statement.source_name, state)
    transformed = append_instruction(
        state,
        lambda register: PairwiseListNumeric(register, target, "sub", source),
    )
    return _with_local_array(transformed, statement.target_name)


def _with_local_array(compiled: CompiledNode, name: str) -> CompileState:
    return CompileState(
        instructions=compiled.state.instructions,
        next_register=compiled.state.next_register,
        local_arrays={**compiled.state.local_arrays, name: compiled.register},
        local_scalars=compiled.state.local_scalars,
        input_overrides=compiled.state.input_overrides,
        current_item_register=compiled.state.current_item_register,
    )
