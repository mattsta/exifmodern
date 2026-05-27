"""Statement-program bytecode emission for safe expressions."""

from __future__ import annotations

from collections.abc import Callable

from exifmodern.safe_expression import local_array_statements, scalar_statements
from exifmodern.safe_expression.ast import (
    AstNode,
    ByteOrderAssignmentStatement,
    ByteOrderToggleIfStatement,
    ByteOrderToggleStatement,
    CompiledNode,
    CompileState,
    CurrentItemAssignment,
    CurrentItemSubstitutionStatement,
    CurrentItemTransliterationStatement,
    ForeachConditionalReturnStatement,
    FunctionCallStatement,
    InputAssignment,
    InputAssignmentIfStatement,
    InputSubstitutionStatement,
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
    LocalScalarAppendIfStatement,
    LocalScalarAssignment,
    LocalScalarAssignmentIfStatement,
    LocalScalarNumericAssignmentIfStatement,
    LocalScalarNumericAssignmentWhileStatement,
    LocalScalarTupleAssignment,
    LocalScalarTupleListAssignment,
    NoOpStatement,
    PackageScalarAssignment,
    PackageScalarAssignmentIfStatement,
    ProgramStatement,
    RequiredModule,
    ReturnIfStatement,
    ReturnUnlessStatement,
    RuntimeContextNamespace,
    RuntimeContextPath,
    SafeInputName,
    SelfContextAssignment,
    SelfContextAssignmentIfStatement,
    StatementProgram,
    ToFloatValListStatement,
)
from exifmodern.safe_expression.bytecode import LazyTernary, LoadConst
from exifmodern.safe_expression.compile_state import append_instruction, branch_compile_state_from
from exifmodern.safe_expression.errors import SafeExpressionCompileError
from exifmodern.safe_expression.runtime_context import (
    compile_runtime_context_assignment_fallback,
    compile_runtime_context_assignment_if_statement,
    package_scalar_input_name,
)

type CompileNode = Callable[[AstNode, CompileState], CompiledNode]
type CompileIndexedInputReference = Callable[
    [SafeInputName, int | None, CompileState],
    CompiledNode,
]
type CompileMapList = Callable[[str, AstNode, CompileState], CompiledNode]


def compile_statement_program(
    ast: StatementProgram,
    state: CompileState,
    *,
    compile_node: CompileNode,
    compile_indexed_input_reference: CompileIndexedInputReference,
    compile_map_list: CompileMapList,
) -> CompiledNode:
    return compile_statement_program_tail(
        ast.statements,
        ast.expression,
        state,
        compile_node=compile_node,
        compile_indexed_input_reference=compile_indexed_input_reference,
        compile_map_list=compile_map_list,
    )


def compile_statement_program_tail(
    statements: list[ProgramStatement],
    expression: AstNode,
    state: CompileState,
    *,
    compile_node: CompileNode,
    compile_indexed_input_reference: CompileIndexedInputReference,
    compile_map_list: CompileMapList,
) -> CompiledNode:
    if not statements:
        return compile_node(expression, state)
    first = statements[0]
    remaining = statements[1:]
    if isinstance(first, ReturnUnlessStatement):
        return compile_guarded_return_statement(
            condition_expression=first.condition,
            return_expression=first.fallback,
            continue_when_truthy=True,
            remaining=remaining,
            final_expression=expression,
            state=state,
            compile_node=compile_node,
            compile_indexed_input_reference=compile_indexed_input_reference,
            compile_map_list=compile_map_list,
        )
    if isinstance(first, ReturnIfStatement):
        return compile_guarded_return_statement(
            condition_expression=first.condition,
            return_expression=first.value,
            continue_when_truthy=False,
            remaining=remaining,
            final_expression=expression,
            state=state,
            compile_node=compile_node,
            compile_indexed_input_reference=compile_indexed_input_reference,
            compile_map_list=compile_map_list,
        )
    if isinstance(first, ForeachConditionalReturnStatement):
        return compile_foreach_conditional_return_statement(
            statement=first,
            remaining=remaining,
            final_expression=expression,
            state=state,
            compile_node=compile_node,
            compile_indexed_input_reference=compile_indexed_input_reference,
            compile_map_list=compile_map_list,
        )
    next_state = compile_program_statement(
        first,
        state,
        compile_node=compile_node,
        compile_indexed_input_reference=compile_indexed_input_reference,
        compile_map_list=compile_map_list,
    )
    return compile_statement_program_tail(
        remaining,
        expression,
        next_state,
        compile_node=compile_node,
        compile_indexed_input_reference=compile_indexed_input_reference,
        compile_map_list=compile_map_list,
    )


def compile_foreach_conditional_return_statement(
    statement: ForeachConditionalReturnStatement,
    remaining: list[ProgramStatement],
    final_expression: AstNode,
    state: CompileState,
    *,
    compile_node: CompileNode,
    compile_indexed_input_reference: CompileIndexedInputReference,
    compile_map_list: CompileMapList,
) -> CompiledNode:
    return compile_foreach_conditional_return_values(
        values=statement.values,
        condition_expression=statement.condition,
        return_expression=statement.value,
        remaining=remaining,
        final_expression=final_expression,
        state=state,
        outer_current_item_register=state.current_item_register,
        compile_node=compile_node,
        compile_indexed_input_reference=compile_indexed_input_reference,
        compile_map_list=compile_map_list,
    )


def compile_foreach_conditional_return_values(
    values: list[int],
    condition_expression: AstNode,
    return_expression: AstNode,
    remaining: list[ProgramStatement],
    final_expression: AstNode,
    state: CompileState,
    outer_current_item_register: str | None,
    *,
    compile_node: CompileNode,
    compile_indexed_input_reference: CompileIndexedInputReference,
    compile_map_list: CompileMapList,
) -> CompiledNode:
    if not values:
        return compile_statement_program_tail(
            remaining,
            final_expression,
            CompileState(
                instructions=state.instructions,
                next_register=state.next_register,
                local_arrays=state.local_arrays,
                local_scalars=state.local_scalars,
                input_overrides=state.input_overrides,
                current_item_register=outer_current_item_register,
            ),
            compile_node=compile_node,
            compile_indexed_input_reference=compile_indexed_input_reference,
            compile_map_list=compile_map_list,
        )
    item = append_instruction(state, lambda register: LoadConst(register, values[0]))
    item_scope = CompileState(
        instructions=item.state.instructions,
        next_register=item.state.next_register,
        local_arrays=item.state.local_arrays,
        local_scalars=item.state.local_scalars,
        input_overrides=item.state.input_overrides,
        current_item_register=item.register,
    )
    condition = compile_node(condition_expression, item_scope)
    continue_state = CompileState(
        instructions=[],
        next_register=condition.state.next_register,
        local_arrays=condition.state.local_arrays,
        local_scalars=condition.state.local_scalars,
        input_overrides=condition.state.input_overrides,
        current_item_register=outer_current_item_register,
    )
    continue_expression = compile_foreach_conditional_return_values(
        values=values[1:],
        condition_expression=condition_expression,
        return_expression=return_expression,
        remaining=remaining,
        final_expression=final_expression,
        state=continue_state,
        outer_current_item_register=outer_current_item_register,
        compile_node=compile_node,
        compile_indexed_input_reference=compile_indexed_input_reference,
        compile_map_list=compile_map_list,
    )
    return_value = compile_node(
        return_expression,
        branch_compile_state_from(condition.state),
    )
    return append_instruction(
        CompileState(
            instructions=condition.state.instructions,
            next_register=max(
                return_value.state.next_register,
                continue_expression.state.next_register,
            ),
            local_arrays=condition.state.local_arrays,
            local_scalars=condition.state.local_scalars,
            input_overrides=condition.state.input_overrides,
            current_item_register=outer_current_item_register,
        ),
        lambda register: LazyTernary(
            register,
            condition.register,
            return_value.state.instructions,
            return_value.register,
            continue_expression.state.instructions,
            continue_expression.register,
        ),
    )


def compile_guarded_return_statement(
    condition_expression: AstNode,
    return_expression: AstNode,
    continue_when_truthy: bool,
    remaining: list[ProgramStatement],
    final_expression: AstNode,
    state: CompileState,
    *,
    compile_node: CompileNode,
    compile_indexed_input_reference: CompileIndexedInputReference,
    compile_map_list: CompileMapList,
) -> CompiledNode:
    condition = compile_node(condition_expression, state)
    continue_expression = compile_statement_program_tail(
        remaining,
        final_expression,
        branch_compile_state_from(condition.state),
        compile_node=compile_node,
        compile_indexed_input_reference=compile_indexed_input_reference,
        compile_map_list=compile_map_list,
    )
    return_value = compile_node(
        return_expression,
        branch_compile_state_from(
            CompileState(
                instructions=condition.state.instructions,
                next_register=continue_expression.state.next_register,
                local_arrays=condition.state.local_arrays,
                local_scalars=condition.state.local_scalars,
                input_overrides=condition.state.input_overrides,
                current_item_register=condition.state.current_item_register,
            )
        ),
    )
    if continue_when_truthy:
        true_instructions = continue_expression.state.instructions
        true_result = continue_expression.register
        false_instructions = return_value.state.instructions
        false_result = return_value.register
        next_register = return_value.state.next_register
    else:
        true_instructions = return_value.state.instructions
        true_result = return_value.register
        false_instructions = continue_expression.state.instructions
        false_result = continue_expression.register
        next_register = return_value.state.next_register
    return append_instruction(
        CompileState(
            instructions=condition.state.instructions,
            next_register=next_register,
            local_arrays=condition.state.local_arrays,
            local_scalars=condition.state.local_scalars,
            input_overrides=condition.state.input_overrides,
            current_item_register=condition.state.current_item_register,
        ),
        lambda register: LazyTernary(
            register,
            condition.register,
            true_instructions,
            true_result,
            false_instructions,
            false_result,
        ),
    )


def compile_program_statement(
    statement: ProgramStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
    compile_indexed_input_reference: CompileIndexedInputReference,
    compile_map_list: CompileMapList,
) -> CompileState:
    if isinstance(statement, LocalArrayAssignment):
        return local_array_statements.compile_local_array_assignment_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalArrayEmptyAssignment):
        return local_array_statements.compile_local_array_empty_assignment_statement(
            statement,
            state,
        )
    if isinstance(statement, LocalArrayTransform):
        return local_array_statements.compile_local_array_transform_statement(
            statement,
            state,
            compile_map_list=compile_map_list,
        )
    if isinstance(statement, LocalArraySliceTransform):
        return local_array_statements.compile_local_array_slice_transform_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalArrayConditionalTransform):
        return local_array_statements.compile_local_array_conditional_transform_statement(
            statement,
            state,
            compile_map_list=compile_map_list,
        )
    if isinstance(statement, LocalArrayIndexedTransform):
        return local_array_statements.compile_local_array_indexed_transform_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalArrayIndexedBitwiseTransform):
        return local_array_statements.compile_local_array_indexed_bitwise_transform_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalArrayIndexedAssignment):
        return local_array_statements.compile_local_array_indexed_assignment_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalArrayIndexedTransformPair):
        return local_array_statements.compile_local_array_indexed_transform_pair_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalArrayPairwiseTransform):
        return local_array_statements.compile_local_array_pairwise_transform_statement(
            statement,
            state,
        )
    if isinstance(statement, LocalArrayPushWhileStatement):
        return local_array_statements.compile_local_array_push_while_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, InputAssignment):
        return scalar_statements.compile_input_assignment_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, InputAssignmentIfStatement):
        return scalar_statements.compile_input_assignment_if_statement(
            statement,
            state,
            compile_node=compile_node,
            compile_indexed_input_reference=compile_indexed_input_reference,
        )
    if isinstance(statement, InputSubstitutionStatement):
        return scalar_statements.compile_input_substitution_statement(
            statement,
            state,
            compile_indexed_input_reference=compile_indexed_input_reference,
        )
    if isinstance(statement, CurrentItemAssignment):
        return scalar_statements.compile_current_item_assignment_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, CurrentItemSubstitutionStatement):
        return scalar_statements.compile_current_item_substitution_statement(statement, state)
    if isinstance(statement, CurrentItemTransliterationStatement):
        return scalar_statements.compile_current_item_transliteration_statement(statement, state)
    if isinstance(statement, LocalScalarAssignment):
        return scalar_statements.compile_local_scalar_assignment_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalScalarAssignmentIfStatement):
        return scalar_statements.compile_local_scalar_assignment_if_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalScalarTupleAssignment):
        return scalar_statements.compile_local_scalar_tuple_assignment_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalScalarTupleListAssignment):
        return scalar_statements.compile_local_scalar_tuple_list_assignment_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalScalarAppendIfStatement):
        return scalar_statements.compile_local_scalar_append_if_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalScalarNumericAssignmentIfStatement):
        return scalar_statements.compile_local_scalar_numeric_assignment_if_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, LocalScalarNumericAssignmentWhileStatement):
        return scalar_statements.compile_local_scalar_numeric_assignment_while_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, FunctionCallStatement):
        return compile_node(statement.function, state).state
    if isinstance(statement, ToFloatValListStatement):
        return scalar_statements.compile_to_float_val_list_statement(
            state,
            compile_indexed_input_reference=compile_indexed_input_reference,
            compile_map_list=compile_map_list,
        )
    if isinstance(statement, ByteOrderAssignmentStatement):
        return scalar_statements.compile_byte_order_assignment_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, ByteOrderToggleStatement):
        return scalar_statements.compile_byte_order_toggle_statement(
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, ByteOrderToggleIfStatement):
        return scalar_statements.compile_byte_order_toggle_if_statement(
            statement,
            state,
            compile_node=compile_node,
            compile_indexed_input_reference=compile_indexed_input_reference,
        )
    if isinstance(statement, SelfContextAssignment):
        return compile_self_context_assignment_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, SelfContextAssignmentIfStatement):
        return compile_self_context_assignment_if_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, PackageScalarAssignment):
        return compile_package_scalar_assignment_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, PackageScalarAssignmentIfStatement):
        return compile_package_scalar_assignment_if_statement(
            statement,
            state,
            compile_node=compile_node,
        )
    if isinstance(statement, RequiredModule):
        return state
    if isinstance(statement, NoOpStatement):
        return state
    raise SafeExpressionCompileError("Unsupported statement-program statement.")


def compile_self_context_assignment_statement(
    statement: SelfContextAssignment,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    assigned = compile_runtime_context_assignment_statement(
        "$$self",
        statement.path,
        statement.value,
        state,
        compile_node=compile_node,
    )
    return assigned.state


def compile_self_context_assignment_if_statement(
    statement: SelfContextAssignmentIfStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    return compile_runtime_context_assignment_if_statement(
        "$$self",
        statement.assignment.path,
        statement.assignment.value,
        statement.condition,
        state,
        compile_node,
    )


def compile_package_scalar_assignment_statement(
    statement: PackageScalarAssignment,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    assigned = compile_runtime_context_assignment_statement(
        package_scalar_input_name(statement.name),
        statement.path,
        statement.value,
        state,
        compile_node=compile_node,
    )
    return assigned.state


def compile_package_scalar_assignment_if_statement(
    statement: PackageScalarAssignmentIfStatement,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompileState:
    return compile_runtime_context_assignment_if_statement(
        package_scalar_input_name(statement.assignment.name),
        statement.assignment.path,
        statement.assignment.value,
        statement.condition,
        state,
        compile_node,
    )


def compile_runtime_context_assignment_statement(
    namespace: RuntimeContextNamespace,
    path: RuntimeContextPath | None,
    value: AstNode,
    state: CompileState,
    *,
    compile_node: CompileNode,
) -> CompiledNode:
    from exifmodern.safe_expression.runtime_context import compile_runtime_context_assignment

    return compile_runtime_context_assignment(namespace, path, value, state, compile_node)


def compile_runtime_context_assignment_fallback_node(
    input_name: str | None,
    state: CompileState,
) -> CompiledNode:
    return compile_runtime_context_assignment_fallback(input_name, state)
