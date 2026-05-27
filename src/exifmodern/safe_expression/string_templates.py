"""String-template bytecode compilation helpers."""

from __future__ import annotations

from collections.abc import Callable

from exifmodern.safe_expression.ast import (
    CompiledNode,
    CompileState,
    LocalScalarContextReference,
    LocalScalarReference,
    SafeInputName,
    StringTemplateLiteral,
    StringTemplateLocalArrayValue,
    StringTemplateLocalScalarContextValue,
    StringTemplateLocalScalarValue,
    StringTemplateValue,
    ValInterpolatedString,
)
from exifmodern.safe_expression.bytecode import (
    InterpolateString,
    InterpolationLiteral,
    InterpolationSegment,
    InterpolationValue,
    JoinString,
    LoadConst,
    LoadIndex,
)
from exifmodern.safe_expression.compile_state import (
    append_instruction,
    local_array_register_or_none,
)

type CompileIndexedInputReference = Callable[
    [SafeInputName, int | None, CompileState],
    CompiledNode,
]
type CompileLocalScalarReference = Callable[[LocalScalarReference, CompileState], CompiledNode]
type CompileLocalScalarContextReference = Callable[
    [LocalScalarContextReference, CompileState],
    CompiledNode,
]


def compile_interpolated_string(
    ast: ValInterpolatedString,
    state: CompileState,
    *,
    compile_indexed_input_reference: CompileIndexedInputReference,
    compile_local_scalar_reference: CompileLocalScalarReference,
    compile_local_scalar_context_reference: CompileLocalScalarContextReference,
) -> CompiledNode:
    current_state = state
    segments: list[InterpolationSegment] = []
    for segment in ast.segments:
        if isinstance(segment, StringTemplateLiteral):
            segments.append(InterpolationLiteral(segment.text))
            continue
        if isinstance(segment, StringTemplateValue):
            value = compile_indexed_input_reference(
                segment.input_name, segment.index, current_state
            )
        elif isinstance(segment, StringTemplateLocalArrayValue):
            value = compile_local_array_string_template_value(segment, current_state)
        elif isinstance(segment, StringTemplateLocalScalarValue):
            value = compile_local_scalar_reference(
                LocalScalarReference(segment.name),
                current_state,
            )
        elif isinstance(segment, StringTemplateLocalScalarContextValue):
            value = compile_local_scalar_context_reference(
                LocalScalarContextReference(segment.name, segment.path),
                current_state,
            )
        else:
            value = compile_current_item_string_template_value(current_state)
        segments.append(InterpolationValue(value.register))
        current_state = value.state
    return append_instruction(
        current_state,
        lambda register: InterpolateString(register, segments),
    )


def compile_current_item_string_template_value(state: CompileState) -> CompiledNode:
    if state.current_item_register is None:
        return append_instruction(state, lambda register: LoadConst(register, "$_"))
    return CompiledNode(register=state.current_item_register, state=state)


def compile_local_array_string_template_value(
    segment: StringTemplateLocalArrayValue,
    state: CompileState,
) -> CompiledNode:
    source = local_array_register_or_none(segment.name, state)
    if source is None:
        literal = (
            f"@{segment.name}" if segment.index is None else f"${segment.name}[{segment.index}]"
        )
        return append_instruction(state, lambda register: LoadConst(register, literal))
    index = segment.index
    if index is not None:
        return append_instruction(
            state,
            lambda register: LoadIndex(register, source, index),
        )
    separator = append_instruction(state, lambda register: LoadConst(register, " "))
    return append_instruction(
        separator.state,
        lambda register: JoinString(register, separator.register, source),
    )
