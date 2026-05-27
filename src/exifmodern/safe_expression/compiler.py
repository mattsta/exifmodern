"""Safe-expression AST bytecode compilation."""

from __future__ import annotations

from exifmodern.safe_expression import (
    expression_compilation,
    function_calls,
    statement_program,
    string_templates,
)
from exifmodern.safe_expression.ast import (
    EXTERNAL_LOCAL_SCALAR_INPUT_NAMES,
    AstNode,
    BitwiseExpression,
    ComparisonExpression,
    CompiledNode,
    CompileState,
    CurrentItemReference,
    DynamicPrtReference,
    DynamicValReference,
    FunctionCall,
    InputOverrides,
    ListLiteral,
    LocalArrayReference,
    LocalArraySliceReference,
    LocalArrayValue,
    LocalScalarContextReference,
    LocalScalarReference,
    MapExpression,
    NumberLiteral,
    NumericExpression,
    NumericUnaryExpression,
    PackageScalarAssignment,
    PackageScalarReference,
    ProgramStatement,
    PrtReference,
    RawListReference,
    RegexLiteral,
    RegexMatchExpression,
    RuntimeContextInputName,
    RuntimeContextNamespace,
    RuntimeContextPath,
    SafeInputName,
    ScalarDereferenceExpression,
    ScalarReferenceExpression,
    SelfContextAssignment,
    SelfContextReference,
    SelfReference,
    SplitSeparatorValue,
    StatementProgram,
    StringConcatExpression,
    StringLiteral,
    StringRepeatExpression,
    SystemOsReference,
    TagInfoReference,
    TagReference,
    TernaryExpression,
    TruthyAndExpression,
    TruthyNotExpression,
    TruthyOrExpression,
    UndefLiteral,
    UnitSuffixExpression,
    UnpackTemplateSpec,
    ValInterpolatedString,
    ValListReference,
    ValReference,
)
from exifmodern.safe_expression.bytecode import (
    BuildList,
    DereferenceScalar,
    LoadConst,
    LoadDynamicIndex,
    LoadHashPath,
    LoadIndex,
    LoadInput,
    LoadSelfContext,
    MakeScalarReference,
    PackTemplate,
    RegexMatch,
)
from exifmodern.safe_expression.compile_state import (
    append_instruction,
    int_literal_value_or_none,
    load_index_instruction,
    local_array_register,
    local_scalar_register_or_none,
)
from exifmodern.safe_expression.errors import SafeExpressionCompileError
from exifmodern.safe_expression.exiftool_compat import ExifToolFunction
from exifmodern.safe_expression.function_calls import (
    CompiledArguments,
    CompiledExifToolArguments,
)
from exifmodern.safe_expression.runtime_context import (
    CompiledContextPathSegments,
    package_scalar_input_name,
    runtime_context_input_name,
    static_runtime_context_path_or_none,
)
from exifmodern.safe_expression.runtime_context import (
    compile_runtime_context_assignment as _compile_runtime_context_assignment,
)
from exifmodern.safe_expression.runtime_context import (
    compile_runtime_context_assignment_fallback as _compile_runtime_context_assignment_fallback,
)
from exifmodern.safe_expression.runtime_context import (
    compile_runtime_context_assignment_if_statement as _compile_runtime_context_if_statement,
)
from exifmodern.safe_expression.runtime_context import (
    compile_runtime_context_path_reference as _compile_runtime_context_path_reference,
)
from exifmodern.safe_expression.runtime_context import (
    compile_runtime_context_path_segments as _compile_runtime_context_path_segments,
)
from exifmodern.safe_expression.runtime_context import (
    runtime_context_selected_overrides as _runtime_context_selected_overrides,
)
from exifmodern.safe_expression.vm import self_context_input_name


def compile_node(ast: AstNode, state: CompileState) -> CompiledNode:
    if isinstance(ast, NumberLiteral):
        return append_instruction(state, lambda register: LoadConst(register, ast.value))
    if isinstance(ast, StringLiteral):
        return append_instruction(state, lambda register: LoadConst(register, ast.value))
    if isinstance(ast, ListLiteral):
        return append_instruction(state, lambda register: LoadConst(register, ast.values))
    if isinstance(ast, RegexLiteral):
        return compile_current_item_regex_literal(ast, state)
    if isinstance(ast, ValInterpolatedString):
        return string_templates.compile_interpolated_string(
            ast,
            state,
            compile_indexed_input_reference=compile_indexed_input_reference,
            compile_local_scalar_reference=compile_local_scalar_reference,
            compile_local_scalar_context_reference=compile_local_scalar_context_reference,
        )
    if isinstance(ast, UnitSuffixExpression):
        return compile_string_concat_expression(
            StringConcatExpression(ast.value, StringLiteral(f" {ast.suffix}")),
            state,
        )
    if isinstance(ast, UndefLiteral):
        return append_instruction(state, lambda register: LoadConst(register, None))
    if isinstance(ast, ValReference):
        return compile_indexed_input_reference("$val", ast.index, state)
    if isinstance(ast, ValListReference):
        return compile_indexed_input_reference("$val", None, state)
    if isinstance(ast, RawListReference):
        return compile_indexed_input_reference("@raw", None, state)
    if isinstance(ast, ScalarReferenceExpression):
        return compile_scalar_reference_expression(ast, state)
    if isinstance(ast, ScalarDereferenceExpression):
        return compile_scalar_dereference_expression(ast, state)
    if isinstance(ast, DynamicValReference):
        return compile_dynamic_input_reference("$val", ast.index, state)
    if isinstance(ast, PrtReference):
        return compile_indexed_input_reference("$prt", ast.index, state)
    if isinstance(ast, DynamicPrtReference):
        return compile_dynamic_input_reference("$prt", ast.index, state)
    if isinstance(ast, SelfReference):
        raise SafeExpressionCompileError("$self is only valid inside ExifTool helper calls.")
    if isinstance(ast, TagInfoReference):
        raise SafeExpressionCompileError("$tagInfo is only valid inside ExifTool helper calls.")
    if isinstance(ast, SelfContextReference):
        return compile_self_context_reference(ast, state)
    if isinstance(ast, SelfContextAssignment):
        return compile_self_context_assignment(ast, state)
    if isinstance(ast, PackageScalarReference):
        return compile_package_scalar_reference(ast, state)
    if isinstance(ast, PackageScalarAssignment):
        return compile_package_scalar_assignment(ast, state)
    if isinstance(ast, LocalScalarContextReference):
        return compile_local_scalar_context_reference(ast, state)
    if isinstance(ast, SystemOsReference):
        return compile_indexed_input_reference("$^O", None, state)
    if isinstance(ast, TagReference):
        raise SafeExpressionCompileError("$tag is only valid inside ExifTool helper calls.")
    if isinstance(ast, LocalArrayReference):
        return compile_local_array_reference(ast, state)
    if isinstance(ast, LocalArraySliceReference):
        return compile_local_array_slice_reference(ast, state)
    if isinstance(ast, LocalArrayValue):
        return compile_local_array_value(ast, state)
    if isinstance(ast, LocalScalarReference):
        return compile_local_scalar_reference(ast, state)
    if isinstance(ast, CurrentItemReference):
        return compile_current_item_reference(state)
    if isinstance(ast, MapExpression):
        return compile_map_expression(ast, state)
    if isinstance(ast, RegexMatchExpression):
        return compile_regex_match_expression(ast, state)
    if isinstance(ast, ComparisonExpression):
        return compile_comparison_expression(ast, state)
    if isinstance(ast, BitwiseExpression):
        return compile_bitwise_expression(ast, state)
    if isinstance(ast, NumericUnaryExpression):
        return compile_numeric_unary_expression(ast, state)
    if isinstance(ast, NumericExpression):
        return compile_numeric_expression(ast, state)
    if isinstance(ast, StringConcatExpression):
        return compile_string_concat_expression(ast, state)
    if isinstance(ast, StringRepeatExpression):
        return compile_string_repeat_expression(ast, state)
    if isinstance(ast, TruthyAndExpression):
        return compile_truthy_and_expression(ast, state)
    if isinstance(ast, TruthyNotExpression):
        return compile_truthy_not_expression(ast, state)
    if isinstance(ast, TruthyOrExpression):
        return compile_truthy_or_expression(ast, state)
    if isinstance(ast, TernaryExpression):
        return compile_ternary_expression(ast, state)
    if isinstance(ast, FunctionCall):
        return compile_function_call(ast, state)
    if isinstance(ast, StatementProgram):
        return compile_statement_program(ast, state)
    raise SafeExpressionCompileError("Unsupported safe-expression AST node.")


def compile_indexed_input_reference(
    input_name: SafeInputName,
    index: int | None,
    state: CompileState,
) -> CompiledNode:
    override = state.input_overrides.get(input_name)
    if override is not None:
        if index is None:
            return CompiledNode(register=override, state=state)
        return append_instruction(state, lambda register: LoadIndex(register, override, index))
    if input_name == "$val" and index is None:
        local_val = local_scalar_register_or_none("val", state)
        if local_val is not None:
            return CompiledNode(register=local_val, state=state)
    if index is None:
        return append_instruction(state, lambda register: LoadInput(register, input_name))
    input_node = append_instruction(state, lambda register: LoadInput(register, input_name))
    return append_instruction(
        input_node.state,
        lambda register: LoadIndex(register, input_node.register, index),
    )


def compile_dynamic_input_reference(
    input_name: SafeInputName,
    index_expression: AstNode,
    state: CompileState,
) -> CompiledNode:
    override = state.input_overrides.get(input_name)
    input_node = (
        CompiledNode(register=override, state=state)
        if override is not None
        else append_instruction(state, lambda register: LoadInput(register, input_name))
    )
    index = compile_node(index_expression, input_node.state)
    return append_instruction(
        index.state,
        lambda register: LoadDynamicIndex(register, input_node.register, index.register),
    )


def compile_self_context_reference(
    ast: SelfContextReference,
    state: CompileState,
) -> CompiledNode:
    static_path = static_runtime_context_path_or_none(ast.path)
    input_name = (
        self_context_input_name(static_path[0])
        if static_path is not None and len(static_path) == 1
        else runtime_context_input_name("$$self", ast.path)
    )
    override = state.input_overrides.get(input_name)
    if override is not None:
        return CompiledNode(register=override, state=state)
    if static_path is not None and len(static_path) == 1:
        return append_instruction(
            state,
            lambda register: LoadSelfContext(register, static_path[0]),
        )
    return compile_runtime_context_path_reference("$$self", ast.path, state)


def compile_package_scalar_reference(
    ast: PackageScalarReference,
    state: CompileState,
) -> CompiledNode:
    input_name = package_scalar_input_name(ast.name, ast.path)
    override = state.input_overrides.get(input_name)
    if override is not None:
        return CompiledNode(register=override, state=state)
    if ast.path is None:
        return append_instruction(state, lambda register: LoadInput(register, input_name))
    return compile_runtime_context_path_reference(
        package_scalar_input_name(ast.name), ast.path, state
    )


def compile_self_context_assignment(
    ast: SelfContextAssignment,
    state: CompileState,
) -> CompiledNode:
    return compile_runtime_context_assignment(
        "$$self",
        ast.path,
        ast.value,
        state,
    )


def compile_package_scalar_assignment(
    ast: PackageScalarAssignment,
    state: CompileState,
) -> CompiledNode:
    return compile_runtime_context_assignment(
        package_scalar_input_name(ast.name),
        ast.path,
        ast.value,
        state,
    )


def compile_runtime_context_assignment(
    namespace: RuntimeContextNamespace,
    path: RuntimeContextPath | None,
    value: AstNode,
    state: CompileState,
) -> CompiledNode:
    return _compile_runtime_context_assignment(
        namespace,
        path,
        value,
        state,
        compile_node,
    )


def compile_runtime_context_path_segments(
    path: RuntimeContextPath | None,
    state: CompileState,
) -> CompiledContextPathSegments:
    return _compile_runtime_context_path_segments(path, state, compile_node)


def compile_runtime_context_path_reference(
    namespace: RuntimeContextNamespace,
    path: RuntimeContextPath,
    state: CompileState,
) -> CompiledNode:
    return _compile_runtime_context_path_reference(
        namespace,
        path,
        state,
        compile_node,
    )


def compile_scalar_reference_expression(
    ast: ScalarReferenceExpression,
    state: CompileState,
) -> CompiledNode:
    value = compile_node(ast.value, state)
    return append_instruction(
        value.state,
        lambda register: MakeScalarReference(register, value.register),
    )


def compile_scalar_dereference_expression(
    ast: ScalarDereferenceExpression,
    state: CompileState,
) -> CompiledNode:
    value = compile_node(ast.value, state)
    return append_instruction(
        value.state,
        lambda register: DereferenceScalar(register, value.register),
    )


def compile_current_item_reference(state: CompileState) -> CompiledNode:
    if state.current_item_register is None:
        raise SafeExpressionCompileError("$_ is only valid inside a foreach transform.")
    return CompiledNode(register=state.current_item_register, state=state)


def compile_map_expression(ast: MapExpression, state: CompileState) -> CompiledNode:
    source = compile_node(ast.source, state)
    return compile_map_list(source.register, ast.expression, source.state)


def compile_regex_match_expression(
    ast: RegexMatchExpression,
    state: CompileState,
) -> CompiledNode:
    value = compile_node(ast.value, state)
    return append_instruction(
        value.state,
        lambda register: RegexMatch(
            register,
            value.register,
            ast.regex.pattern,
            ast.regex.ignore_case,
            ast.regex.dot_matches_newline,
        ),
    )


def compile_current_item_regex_literal(
    ast: RegexLiteral,
    state: CompileState,
) -> CompiledNode:
    if state.current_item_register is None:
        raise SafeExpressionCompileError(
            "Regex literals as expressions require an assigned current item."
        )
    return compile_regex_match_expression(RegexMatchExpression(CurrentItemReference(), ast), state)


def compile_local_array_reference(ast: LocalArrayReference, state: CompileState) -> CompiledNode:
    source = local_array_register(ast.name, state)
    index_value = int_literal_value_or_none(ast.index)
    if index_value is not None:
        return append_instruction(
            state,
            lambda register: LoadIndex(register, source, index_value),
        )
    index = compile_node(ast.index, state)
    return append_instruction(
        index.state,
        lambda register: LoadDynamicIndex(register, source, index.register),
    )


def compile_local_array_slice_reference(
    ast: LocalArraySliceReference,
    state: CompileState,
) -> CompiledNode:
    source = local_array_register(ast.name, state)
    current_state = state
    registers: list[str] = []
    for index in ast.indexes:
        item = append_instruction(
            current_state,
            load_index_instruction(source, index),
        )
        registers.append(item.register)
        current_state = item.state
    return append_instruction(
        current_state,
        lambda register: BuildList(register, registers),
    )


def compile_local_array_value(ast: LocalArrayValue, state: CompileState) -> CompiledNode:
    return CompiledNode(register=local_array_register(ast.name, state), state=state)


def compile_local_scalar_reference(ast: LocalScalarReference, state: CompileState) -> CompiledNode:
    register = local_scalar_register_or_none(ast.name, state)
    if register is None:
        if ast.name in EXTERNAL_LOCAL_SCALAR_INPUT_NAMES:
            return append_instruction(state, lambda target: LoadInput(target, f"${ast.name}"))
        raise SafeExpressionCompileError(f"Unknown local scalar: ${ast.name}")
    return CompiledNode(register=register, state=state)


def compile_local_scalar_context_reference(
    ast: LocalScalarContextReference,
    state: CompileState,
) -> CompiledNode:
    source = compile_local_scalar_reference(LocalScalarReference(ast.name), state)
    compiled_path = compile_runtime_context_path_segments(ast.path, source.state)
    return append_instruction(
        compiled_path.state,
        lambda register: LoadHashPath(register, source.register, compiled_path.segments),
    )


def compile_statement_program(ast: StatementProgram, state: CompileState) -> CompiledNode:
    return statement_program.compile_statement_program(
        ast,
        state,
        compile_node=compile_node,
        compile_indexed_input_reference=compile_indexed_input_reference,
        compile_map_list=compile_map_list,
    )


def compile_program_statement(statement: ProgramStatement, state: CompileState) -> CompileState:
    return statement_program.compile_program_statement(
        statement,
        state,
        compile_node=compile_node,
        compile_indexed_input_reference=compile_indexed_input_reference,
        compile_map_list=compile_map_list,
    )


def compile_runtime_context_assignment_if_statement(
    namespace: RuntimeContextNamespace,
    path: RuntimeContextPath | None,
    value: AstNode,
    condition: AstNode,
    state: CompileState,
) -> CompileState:
    return _compile_runtime_context_if_statement(
        namespace,
        path,
        value,
        condition,
        state,
        compile_node,
    )


def compile_runtime_context_assignment_fallback(
    input_name: RuntimeContextInputName | None,
    state: CompileState,
) -> CompiledNode:
    return _compile_runtime_context_assignment_fallback(input_name, state)


def runtime_context_selected_overrides(
    input_overrides: InputOverrides,
    input_name: RuntimeContextInputName | None,
    register: str,
) -> InputOverrides:
    return _runtime_context_selected_overrides(input_overrides, input_name, register)


def compile_map_list(source: str, expression: AstNode, state: CompileState) -> CompiledNode:
    return expression_compilation.compile_map_list(
        source,
        expression,
        state,
        compile_node=compile_node,
    )


def compile_numeric_expression(ast: NumericExpression, state: CompileState) -> CompiledNode:
    return expression_compilation.compile_numeric_expression(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_numeric_unary_expression(
    ast: NumericUnaryExpression,
    state: CompileState,
) -> CompiledNode:
    return expression_compilation.compile_numeric_unary_expression(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_comparison_expression(ast: ComparisonExpression, state: CompileState) -> CompiledNode:
    return expression_compilation.compile_comparison_expression(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_bitwise_expression(ast: BitwiseExpression, state: CompileState) -> CompiledNode:
    return expression_compilation.compile_bitwise_expression(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_string_concat_expression(
    ast: StringConcatExpression,
    state: CompileState,
) -> CompiledNode:
    return expression_compilation.compile_string_concat_expression(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_string_repeat_expression(
    ast: StringRepeatExpression,
    state: CompileState,
) -> CompiledNode:
    return expression_compilation.compile_string_repeat_expression(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_numeric_context_node(ast: AstNode, state: CompileState) -> CompiledNode:
    return expression_compilation.compile_numeric_context_node(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_truthy_and_expression(
    ast: TruthyAndExpression,
    state: CompileState,
) -> CompiledNode:
    return expression_compilation.compile_truthy_and_expression(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_truthy_not_expression(
    ast: TruthyNotExpression,
    state: CompileState,
) -> CompiledNode:
    return expression_compilation.compile_truthy_not_expression(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_truthy_or_expression(
    ast: TruthyOrExpression,
    state: CompileState,
) -> CompiledNode:
    return expression_compilation.compile_truthy_or_expression(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_ternary_expression(ast: TernaryExpression, state: CompileState) -> CompiledNode:
    return expression_compilation.compile_ternary_expression(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_guarded_numeric_ternary(
    ast: TernaryExpression,
    state: CompileState,
) -> CompiledNode | None:
    return expression_compilation.compile_guarded_numeric_ternary(
        ast,
        state,
        compile_node=compile_node,
    )


def compile_function_call(ast: FunctionCall, state: CompileState) -> CompiledNode:
    return function_calls.compile_function_call(
        ast,
        state,
        compile_node=compile_node,
        compile_indexed_input_reference=compile_indexed_input_reference,
    )


def split_separator_value(ast: AstNode) -> SplitSeparatorValue:
    return function_calls.split_separator_value(ast)


def unpack_template_value(ast: AstNode) -> UnpackTemplateSpec:
    return function_calls.unpack_template_value(ast)


def hex_group_unpack_lengths_or_none(ast: AstNode) -> list[int] | None:
    return function_calls.hex_group_unpack_lengths_or_none(ast)


def pack_template_value(ast: AstNode) -> PackTemplate:
    return function_calls.pack_template_value(ast)


def static_string_expression_value_or_none(ast: AstNode) -> str | None:
    return function_calls.static_string_expression_value_or_none(ast)


def compile_exiftool_call_arguments(
    function: ExifToolFunction,
    arguments: list[AstNode],
    state: CompileState,
) -> CompiledExifToolArguments:
    return function_calls.compile_exiftool_call_arguments(
        function,
        arguments,
        state,
        compile_node=compile_node,
    )


def exiftool_context_argument_input_name(
    function: ExifToolFunction,
    argument: SelfReference | TagReference | TagInfoReference | LocalScalarReference,
) -> str | None:
    return function_calls.exiftool_context_argument_input_name(function, argument)


def exiftool_context_local_input_name(
    function: ExifToolFunction,
    argument: LocalScalarReference,
) -> str | None:
    return function_calls.exiftool_context_local_input_name(function, argument)


def compile_call_arguments(arguments: list[AstNode], state: CompileState) -> CompiledArguments:
    return function_calls.compile_call_arguments(arguments, state, compile_node=compile_node)
