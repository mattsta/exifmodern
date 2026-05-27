"""Runtime-context path helpers for safe-expression compilation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from exifmodern.safe_expression.ast import (
    AstNode,
    CompiledNode,
    CompileState,
    DynamicRuntimeContextKey,
    InputOverrides,
    RuntimeContextInputName,
    RuntimeContextNamespace,
    RuntimeContextPath,
    StaticRuntimeContextKey,
)
from exifmodern.safe_expression.bytecode import (
    DynamicContextPathSegment,
    LazyTernary,
    LoadConst,
    LoadContextPath,
    StaticContextPathSegment,
    StoreContextPath,
)
from exifmodern.safe_expression.compile_state import append_instruction, branch_compile_state_from
from exifmodern.safe_expression.vm import context_path_input_name

type CompileNode = Callable[[AstNode, CompileState], CompiledNode]


@dataclass(frozen=True)
class CompiledContextPathSegments:
    segments: list[StaticContextPathSegment | DynamicContextPathSegment]
    state: CompileState


def compile_runtime_context_assignment(
    namespace: RuntimeContextNamespace,
    path: RuntimeContextPath | None,
    value: AstNode,
    state: CompileState,
    compile_node: CompileNode,
) -> CompiledNode:
    segments = compile_runtime_context_path_segments(path, state, compile_node)
    assigned = compile_node(value, segments.state)
    stored = append_instruction(
        assigned.state,
        lambda register: StoreContextPath(
            register,
            namespace,
            segments.segments,
            assigned.register,
        ),
    )
    input_name = runtime_context_effect_input_name(namespace, path)
    input_overrides = stored.state.input_overrides
    if input_name is not None:
        input_overrides = {**input_overrides, input_name: stored.register}
    return CompiledNode(
        register=stored.register,
        state=CompileState(
            instructions=stored.state.instructions,
            next_register=stored.state.next_register,
            local_arrays=stored.state.local_arrays,
            local_scalars=stored.state.local_scalars,
            input_overrides=input_overrides,
            current_item_register=stored.state.current_item_register,
        ),
    )


def compile_runtime_context_path_segments(
    path: RuntimeContextPath | None,
    state: CompileState,
    compile_node: CompileNode,
) -> CompiledContextPathSegments:
    if path is None:
        return CompiledContextPathSegments(segments=[], state=state)
    current_state = state
    segments: list[StaticContextPathSegment | DynamicContextPathSegment] = []
    for key in path.keys:
        if isinstance(key, StaticRuntimeContextKey):
            segments.append(StaticContextPathSegment(key.value))
            continue
        compiled_key = compile_node(key.value, current_state)
        segments.append(DynamicContextPathSegment(compiled_key.register))
        current_state = compiled_key.state
    return CompiledContextPathSegments(segments=segments, state=current_state)


def compile_runtime_context_path_reference(
    namespace: RuntimeContextNamespace,
    path: RuntimeContextPath,
    state: CompileState,
    compile_node: CompileNode,
) -> CompiledNode:
    compiled_path = compile_runtime_context_path_segments(path, state, compile_node)
    return append_instruction(
        compiled_path.state,
        lambda register: LoadContextPath(register, namespace, compiled_path.segments),
    )


def compile_runtime_context_assignment_if_statement(
    namespace: RuntimeContextNamespace,
    path: RuntimeContextPath | None,
    value: AstNode,
    condition: AstNode,
    state: CompileState,
    compile_node: CompileNode,
) -> CompileState:
    condition_node = compile_node(condition, state)
    assigned = compile_runtime_context_assignment(
        namespace,
        path,
        value,
        branch_compile_state_from(condition_node.state),
        compile_node,
    )
    input_name = runtime_context_effect_input_name(namespace, path)
    fallback = compile_runtime_context_assignment_fallback(
        input_name,
        CompileState(
            instructions=condition_node.state.instructions,
            next_register=assigned.state.next_register,
            local_arrays=condition_node.state.local_arrays,
            local_scalars=condition_node.state.local_scalars,
            input_overrides=condition_node.state.input_overrides,
            current_item_register=condition_node.state.current_item_register,
        ),
    )
    selected = append_instruction(
        CompileState(
            instructions=condition_node.state.instructions,
            next_register=max(assigned.state.next_register, fallback.state.next_register),
            local_arrays=condition_node.state.local_arrays,
            local_scalars=condition_node.state.local_scalars,
            input_overrides=condition_node.state.input_overrides,
            current_item_register=condition_node.state.current_item_register,
        ),
        lambda register: LazyTernary(
            register,
            condition_node.register,
            assigned.state.instructions,
            assigned.register,
            fallback.state.instructions,
            fallback.register,
        ),
    )
    return CompileState(
        instructions=selected.state.instructions,
        next_register=selected.state.next_register,
        local_arrays=selected.state.local_arrays,
        local_scalars=selected.state.local_scalars,
        input_overrides=runtime_context_selected_overrides(
            selected.state.input_overrides,
            input_name,
            selected.register,
        ),
        current_item_register=selected.state.current_item_register,
    )


def compile_runtime_context_assignment_fallback(
    input_name: RuntimeContextInputName | None,
    state: CompileState,
) -> CompiledNode:
    if input_name is not None:
        existing = state.input_overrides.get(input_name)
        if existing is not None:
            return CompiledNode(register=existing, state=branch_compile_state_from(state))
    return append_instruction(
        branch_compile_state_from(state),
        lambda register: LoadConst(register, None),
    )


def runtime_context_selected_overrides(
    input_overrides: InputOverrides,
    input_name: RuntimeContextInputName | None,
    register: str,
) -> InputOverrides:
    if input_name is None:
        return input_overrides
    return {**input_overrides, input_name: register}


def package_scalar_input_name(
    name: str,
    path: RuntimeContextPath | None = None,
) -> RuntimeContextInputName:
    namespace = f"${name}"
    if path is None:
        return namespace
    return runtime_context_input_name(namespace, path)


def runtime_context_input_name(
    namespace: RuntimeContextNamespace,
    path: RuntimeContextPath,
) -> RuntimeContextInputName:
    static_path = static_runtime_context_path_or_none(path)
    if static_path is None:
        return namespace
    return context_path_input_name(namespace, static_path)


def runtime_context_effect_input_name(
    namespace: RuntimeContextNamespace,
    path: RuntimeContextPath | None,
) -> RuntimeContextInputName | None:
    if path is None:
        return namespace
    static_path = static_runtime_context_path_or_none(path)
    if static_path is None:
        return None
    return context_path_input_name(namespace, static_path)


def static_runtime_context_path_or_none(path: RuntimeContextPath) -> list[str] | None:
    keys: list[str] = []
    for key in path.keys:
        if isinstance(key, DynamicRuntimeContextKey):
            return None
        keys.append(key.value)
    return keys
