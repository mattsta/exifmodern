"""Scalar, input, and byte-order statement bytecode compilation helpers."""

from __future__ import annotations

from collections.abc import Callable

from exifmodern.safe_expression.ast import (
    AstNode,
    ByteOrderAssignmentStatement,
    ByteOrderToggleIfStatement,
    ComparisonExpression,
    CompiledNode,
    CompileState,
    CurrentItemAssignment,
    CurrentItemReference,
    CurrentItemSubstitutionStatement,
    CurrentItemTransliterationStatement,
    FunctionCall,
    InputAssignment,
    InputAssignmentIfStatement,
    InputSubstitutionStatement,
    LocalScalarAppendIfStatement,
    LocalScalarAssignment,
    LocalScalarAssignmentIfStatement,
    LocalScalarNumericAssignmentIfStatement,
    LocalScalarNumericAssignmentWhileStatement,
    LocalScalarReference,
    LocalScalarTupleAssignment,
    LocalScalarTupleListAssignment,
    NumericExpression,
    SafeInputName,
    StringLiteral,
    TernaryExpression,
)
from exifmodern.safe_expression.bytecode import (
    LazyTernary,
    NumericBinary,
    RegexSubstitute,
    StringConcat,
    Transliterate,
    WhileLoop,
)
from exifmodern.safe_expression.compile_state import (
    append_instruction,
    branch_compile_state_from,
    load_index_instruction,
    local_scalar_register_or_none,
)
from exifmodern.safe_expression.errors import SafeExpressionCompileError
from exifmodern.safe_expression.operators import numeric_operator

type CompileNode = Callable[[AstNode, CompileState], CompiledNode]
type CompileIndexedInputReference = Callable[
    [SafeInputName, int | None, CompileState],
    CompiledNode,
]
type CompileMapList = Callable[[str, AstNode, CompileState], CompiledNode]


def compile_input_assignment_statement(
    statement: InputAssignment,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    assigned_value = compile_node(statement.value, state)
    return CompileState(
        instructions=assigned_value.state.instructions,
        next_register=assigned_value.state.next_register,
        local_arrays=assigned_value.state.local_arrays,
        local_scalars=assigned_value.state.local_scalars,
        input_overrides={**assigned_value.state.input_overrides, "$val": assigned_value.register},
        current_item_register=assigned_value.state.current_item_register,
    )


def compile_input_assignment_if_statement(
    statement: InputAssignmentIfStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
    compile_indexed_input_reference: CompileIndexedInputReference,
) -> CompileState:
    condition = compile_node(statement.condition, state)
    assigned_value = compile_node(statement.value, branch_compile_state_from(condition.state))
    current_value = compile_indexed_input_reference(
        "$val",
        None,
        branch_compile_state_from(
            CompileState(
                instructions=condition.state.instructions,
                next_register=assigned_value.state.next_register,
                local_arrays=condition.state.local_arrays,
                local_scalars=condition.state.local_scalars,
                input_overrides=condition.state.input_overrides,
                current_item_register=condition.state.current_item_register,
            )
        ),
    )
    selected = append_instruction(
        CompileState(
            instructions=condition.state.instructions,
            next_register=assigned_value.state.next_register,
            local_arrays=condition.state.local_arrays,
            local_scalars=condition.state.local_scalars,
            input_overrides=condition.state.input_overrides,
            current_item_register=condition.state.current_item_register,
        ),
        lambda register: LazyTernary(
            register,
            condition.register,
            assigned_value.state.instructions,
            assigned_value.register,
            current_value.state.instructions,
            current_value.register,
        ),
    )
    return CompileState(
        instructions=selected.state.instructions,
        next_register=selected.state.next_register,
        local_arrays=selected.state.local_arrays,
        local_scalars=selected.state.local_scalars,
        input_overrides={**selected.state.input_overrides, "$val": selected.register},
        current_item_register=selected.state.current_item_register,
    )


def compile_input_substitution_statement(
    statement: InputSubstitutionStatement,
    state: CompileState,
    *,
    compile_indexed_input_reference: CompileIndexedInputReference,
) -> CompileState:
    value = compile_indexed_input_reference("$val", None, state)
    substituted = append_instruction(
        value.state,
        lambda register: RegexSubstitute(
            register,
            value.register,
            statement.pattern,
            statement.replacement,
            statement.global_substitution,
            statement.ignore_case,
            statement.dot_matches_newline,
        ),
    )
    return CompileState(
        instructions=substituted.state.instructions,
        next_register=substituted.state.next_register,
        local_arrays=substituted.state.local_arrays,
        local_scalars=substituted.state.local_scalars,
        input_overrides={**substituted.state.input_overrides, "$val": substituted.register},
        current_item_register=substituted.state.current_item_register,
    )


def compile_current_item_assignment_statement(
    statement: CurrentItemAssignment,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    assigned_value = compile_node(statement.value, state)
    return CompileState(
        instructions=assigned_value.state.instructions,
        next_register=assigned_value.state.next_register,
        local_arrays=assigned_value.state.local_arrays,
        local_scalars=assigned_value.state.local_scalars,
        input_overrides=assigned_value.state.input_overrides,
        current_item_register=assigned_value.register,
    )


def compile_current_item_substitution_statement(
    statement: CurrentItemSubstitutionStatement,
    state: CompileState,
) -> CompileState:
    if state.current_item_register is None:
        raise SafeExpressionCompileError("Current item substitution requires $_ assignment.")
    current_item_register = state.current_item_register
    substituted = append_instruction(
        state,
        lambda register: RegexSubstitute(
            register,
            current_item_register,
            statement.pattern,
            statement.replacement,
            statement.global_substitution,
            statement.ignore_case,
            statement.dot_matches_newline,
        ),
    )
    return CompileState(
        instructions=substituted.state.instructions,
        next_register=substituted.state.next_register,
        local_arrays=substituted.state.local_arrays,
        local_scalars=substituted.state.local_scalars,
        input_overrides=substituted.state.input_overrides,
        current_item_register=substituted.register,
    )


def compile_current_item_transliteration_statement(
    statement: CurrentItemTransliterationStatement,
    state: CompileState,
) -> CompileState:
    if state.current_item_register is None:
        raise SafeExpressionCompileError("Current item transliteration requires $_ assignment.")
    current_item_register = state.current_item_register
    transliterated = append_instruction(
        state,
        lambda register: Transliterate(
            register,
            current_item_register,
            statement.source_chars,
            statement.replacement_chars,
        ),
    )
    return CompileState(
        instructions=transliterated.state.instructions,
        next_register=transliterated.state.next_register,
        local_arrays=transliterated.state.local_arrays,
        local_scalars=transliterated.state.local_scalars,
        input_overrides=transliterated.state.input_overrides,
        current_item_register=transliterated.register,
    )


def compile_local_scalar_assignment_statement(
    statement: LocalScalarAssignment,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    assigned_value = compile_node(statement.value, state)
    return CompileState(
        instructions=assigned_value.state.instructions,
        next_register=assigned_value.state.next_register,
        local_arrays=assigned_value.state.local_arrays,
        local_scalars={
            **assigned_value.state.local_scalars,
            statement.name: assigned_value.register,
        },
        input_overrides=assigned_value.state.input_overrides,
        current_item_register=assigned_value.state.current_item_register,
    )


def compile_local_scalar_assignment_if_statement(
    statement: LocalScalarAssignmentIfStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    current_register = _local_scalar_register(statement.name, state)
    condition = compile_node(statement.condition, state)
    assigned_value = compile_node(statement.value, branch_compile_state_from(condition.state))
    selected = append_instruction(
        CompileState(
            instructions=condition.state.instructions,
            next_register=assigned_value.state.next_register,
            local_arrays=condition.state.local_arrays,
            local_scalars=condition.state.local_scalars,
            input_overrides=condition.state.input_overrides,
            current_item_register=condition.state.current_item_register,
        ),
        lambda register: LazyTernary(
            register,
            condition.register,
            assigned_value.state.instructions,
            assigned_value.register,
            [],
            current_register,
        ),
    )
    return _with_local_scalar(selected, statement.name)


def compile_local_scalar_tuple_assignment_statement(
    statement: LocalScalarTupleAssignment,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    if len(statement.targets) != len(statement.values):
        raise SafeExpressionCompileError(
            "Local scalar tuple assignment requires matching target and value counts."
        )
    current_state = state
    local_scalars = state.local_scalars
    for target, value in zip(statement.targets, statement.values, strict=True):
        assigned_value = compile_node(value, current_state)
        local_scalars = {**assigned_value.state.local_scalars, target.name: assigned_value.register}
        current_state = CompileState(
            instructions=assigned_value.state.instructions,
            next_register=assigned_value.state.next_register,
            local_arrays=assigned_value.state.local_arrays,
            local_scalars=local_scalars,
            input_overrides=assigned_value.state.input_overrides,
            current_item_register=assigned_value.state.current_item_register,
        )
    return current_state


def compile_local_scalar_tuple_list_assignment_statement(
    statement: LocalScalarTupleListAssignment,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    assigned_value = compile_node(statement.value, state)
    current_state = assigned_value.state
    local_scalars = assigned_value.state.local_scalars
    for index, target in enumerate(statement.targets):
        indexed_value = append_instruction(
            current_state,
            load_index_instruction(assigned_value.register, index),
        )
        local_scalars = {**indexed_value.state.local_scalars, target.name: indexed_value.register}
        current_state = CompileState(
            instructions=indexed_value.state.instructions,
            next_register=indexed_value.state.next_register,
            local_arrays=indexed_value.state.local_arrays,
            local_scalars=local_scalars,
            input_overrides=indexed_value.state.input_overrides,
            current_item_register=indexed_value.state.current_item_register,
        )
    return current_state


def compile_local_scalar_append_if_statement(
    statement: LocalScalarAppendIfStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    current_register = _local_scalar_register(statement.name, state)
    condition = compile_node(statement.condition, state)
    append_value = compile_node(statement.value, branch_compile_state_from(condition.state))
    appended = append_instruction(
        append_value.state,
        lambda register: StringConcat(register, current_register, append_value.register),
    )
    unchanged = CompiledNode(
        register=current_register,
        state=branch_compile_state_from(
            CompileState(
                instructions=condition.state.instructions,
                next_register=appended.state.next_register,
                local_arrays=condition.state.local_arrays,
                local_scalars=condition.state.local_scalars,
                input_overrides=condition.state.input_overrides,
                current_item_register=condition.state.current_item_register,
            )
        ),
    )
    selected = append_instruction(
        CompileState(
            instructions=condition.state.instructions,
            next_register=appended.state.next_register,
            local_arrays=condition.state.local_arrays,
            local_scalars=condition.state.local_scalars,
            input_overrides=condition.state.input_overrides,
            current_item_register=condition.state.current_item_register,
        ),
        lambda register: LazyTernary(
            register,
            condition.register,
            appended.state.instructions,
            appended.register,
            unchanged.state.instructions,
            unchanged.register,
        ),
    )
    return _with_local_scalar(selected, statement.name)


def compile_local_scalar_numeric_assignment_if_statement(
    statement: LocalScalarNumericAssignmentIfStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    current_register = _local_scalar_register(statement.name, state)
    condition = compile_node(statement.condition, state)
    computed_value = compile_node(
        NumericExpression(
            LocalScalarReference(statement.name), statement.operator, statement.value
        ),
        branch_compile_state_from(condition.state),
    )
    selected = append_instruction(
        CompileState(
            instructions=condition.state.instructions,
            next_register=computed_value.state.next_register,
            local_arrays=condition.state.local_arrays,
            local_scalars=condition.state.local_scalars,
            input_overrides=condition.state.input_overrides,
            current_item_register=condition.state.current_item_register,
        ),
        lambda register: LazyTernary(
            register,
            condition.register,
            computed_value.state.instructions,
            computed_value.register,
            [],
            current_register,
        ),
    )
    return _with_local_scalar(selected, statement.name)


def compile_local_scalar_numeric_assignment_while_statement(
    statement: LocalScalarNumericAssignmentWhileStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    current_register = _local_scalar_register(statement.name, state)
    condition = compile_node(statement.condition, branch_compile_state_from(state))
    operand = compile_node(statement.value, branch_compile_state_from(condition.state))
    body_instructions = [
        *operand.state.instructions,
        NumericBinary(
            current_register,
            current_register,
            numeric_operator(statement.operator),
            operand.register,
        ),
    ]
    return CompileState(
        instructions=[
            *state.instructions,
            WhileLoop(condition.state.instructions, condition.register, body_instructions),
        ],
        next_register=operand.state.next_register,
        local_arrays=state.local_arrays,
        local_scalars=state.local_scalars,
        input_overrides=state.input_overrides,
        current_item_register=state.current_item_register,
    )


def compile_to_float_val_list_statement(
    state: CompileState,
    *,
    compile_indexed_input_reference: CompileIndexedInputReference,
    compile_map_list: CompileMapList,
) -> CompileState:
    source = compile_indexed_input_reference("$val", None, state)
    expression = FunctionCall("ToFloat", [CurrentItemReference()])
    mapped = compile_map_list(source.register, expression, source.state)
    return CompileState(
        instructions=mapped.state.instructions,
        next_register=mapped.state.next_register,
        local_arrays=mapped.state.local_arrays,
        local_scalars=mapped.state.local_scalars,
        input_overrides={**mapped.state.input_overrides, "$val": mapped.register},
        current_item_register=mapped.state.current_item_register,
    )


def compile_byte_order_assignment_statement(
    statement: ByteOrderAssignmentStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    assigned_value = compile_node(statement.value, state)
    return CompileState(
        instructions=assigned_value.state.instructions,
        next_register=assigned_value.state.next_register,
        local_arrays=assigned_value.state.local_arrays,
        local_scalars=assigned_value.state.local_scalars,
        input_overrides={
            **assigned_value.state.input_overrides,
            "$byte_order": assigned_value.register,
        },
        current_item_register=assigned_value.state.current_item_register,
    )


def compile_byte_order_toggle_statement(
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    toggled = compile_byte_order_toggle_value(state, compile_node=compile_node)
    return CompileState(
        instructions=toggled.state.instructions,
        next_register=toggled.state.next_register,
        local_arrays=toggled.state.local_arrays,
        local_scalars=toggled.state.local_scalars,
        input_overrides={**toggled.state.input_overrides, "$byte_order": toggled.register},
        current_item_register=toggled.state.current_item_register,
    )


def compile_byte_order_toggle_if_statement(
    statement: ByteOrderToggleIfStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
    compile_indexed_input_reference: CompileIndexedInputReference,
) -> CompileState:
    condition = compile_node(statement.condition, state)
    toggled = compile_byte_order_toggle_value(
        branch_compile_state_from(condition.state),
        compile_node=compile_node,
    )
    current_byte_order = compile_indexed_input_reference(
        "$byte_order",
        None,
        branch_compile_state_from(
            CompileState(
                instructions=condition.state.instructions,
                next_register=toggled.state.next_register,
                local_arrays=condition.state.local_arrays,
                local_scalars=condition.state.local_scalars,
                input_overrides=condition.state.input_overrides,
                current_item_register=condition.state.current_item_register,
            )
        ),
    )
    selected = append_instruction(
        CompileState(
            instructions=condition.state.instructions,
            next_register=toggled.state.next_register,
            local_arrays=condition.state.local_arrays,
            local_scalars=condition.state.local_scalars,
            input_overrides=condition.state.input_overrides,
            current_item_register=condition.state.current_item_register,
        ),
        lambda register: LazyTernary(
            register,
            condition.register,
            toggled.state.instructions,
            toggled.register,
            current_byte_order.state.instructions,
            current_byte_order.register,
        ),
    )
    return CompileState(
        instructions=selected.state.instructions,
        next_register=selected.state.next_register,
        local_arrays=selected.state.local_arrays,
        local_scalars=selected.state.local_scalars,
        input_overrides={**selected.state.input_overrides, "$byte_order": selected.register},
        current_item_register=selected.state.current_item_register,
    )


def compile_byte_order_toggle_value(
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompiledNode:
    return compile_node(
        TernaryExpression(
            ComparisonExpression(FunctionCall("GetByteOrder", []), "eq", StringLiteral("II")),
            StringLiteral("MM"),
            StringLiteral("II"),
        ),
        state,
    )


def _local_scalar_register(name: str, state: CompileState) -> str:
    register = local_scalar_register_or_none(name, state)
    if register is None:
        raise SafeExpressionCompileError(f"Unknown local scalar: ${name}")
    return register


def _with_local_scalar(compiled: CompiledNode, name: str) -> CompileState:
    return CompileState(
        instructions=compiled.state.instructions,
        next_register=compiled.state.next_register,
        local_arrays=compiled.state.local_arrays,
        local_scalars={**compiled.state.local_scalars, name: compiled.register},
        input_overrides=compiled.state.input_overrides,
        current_item_register=compiled.state.current_item_register,
    )
