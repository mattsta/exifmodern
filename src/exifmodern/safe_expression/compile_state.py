"""Compile-state helper primitives for safe-expression bytecode emission."""

from __future__ import annotations

from exifmodern.safe_expression.ast import (
    AstNode,
    CompiledNode,
    CompileState,
    InputOverrides,
    InstructionBuilder,
    LocalArrayName,
    LocalArrayRegisters,
    LocalScalarName,
    LocalScalarRegisters,
    NumberLiteral,
)
from exifmodern.safe_expression.bytecode import LoadIndex, LoadInput, VmInstruction
from exifmodern.safe_expression.errors import SafeExpressionCompileError


def append_instruction(state: CompileState, builder: InstructionBuilder) -> CompiledNode:
    register = f"r{state.next_register}"
    instruction = builder(register)
    return CompiledNode(
        register=register,
        state=CompileState(
            instructions=[*state.instructions, instruction],
            next_register=state.next_register + 1,
            local_arrays=state.local_arrays,
            local_scalars=state.local_scalars,
            input_overrides=state.input_overrides,
            current_item_register=state.current_item_register,
        ),
    )


def load_index_instruction(source: str, index: int) -> InstructionBuilder:
    def build(register: str) -> VmInstruction:
        return LoadIndex(register, source, index)

    return build


def load_input_instruction(input_name: str) -> InstructionBuilder:
    def build(register: str) -> VmInstruction:
        return LoadInput(register, input_name)

    return build


def branch_compile_state(
    next_register: int,
    local_arrays: LocalArrayRegisters,
    local_scalars: LocalScalarRegisters,
    input_overrides: InputOverrides,
    current_item_register: str | None,
) -> CompileState:
    return CompileState(
        instructions=[],
        next_register=next_register,
        local_arrays=local_arrays,
        local_scalars=local_scalars,
        input_overrides=input_overrides,
        current_item_register=current_item_register,
    )


def branch_compile_state_from(state: CompileState) -> CompileState:
    return branch_compile_state(
        state.next_register,
        state.local_arrays,
        state.local_scalars,
        state.input_overrides,
        state.current_item_register,
    )


def local_array_register(name: LocalArrayName, state: CompileState) -> str:
    register = local_array_register_or_none(name, state)
    if register is None:
        raise SafeExpressionCompileError(f"Unknown local array: @{name}")
    return register


def local_array_register_or_none(name: LocalArrayName, state: CompileState) -> str | None:
    return state.local_arrays.get(name)


def local_scalar_register_or_none(name: LocalScalarName, state: CompileState) -> str | None:
    return state.local_scalars.get(name)


def int_literal_value_or_none(ast: AstNode) -> int | None:
    if not isinstance(ast, NumberLiteral):
        return None
    if not isinstance(ast.value, int):
        return None
    return ast.value
