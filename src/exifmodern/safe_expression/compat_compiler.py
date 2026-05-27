"""Compatibility facade for safe-expression parsing and compilation.

Implementation lives under :mod:`exifmodern.safe_expression`.
"""

from __future__ import annotations

from exifmodern.safe_expression.ast import *  # noqa: F403
from exifmodern.safe_expression.bytecode import *  # noqa: F403
from exifmodern.safe_expression.compile_state import (  # noqa: F401
    append_instruction,
    branch_compile_state_from,
    int_literal_value_or_none,
    load_index_instruction,
    load_input_instruction,
    local_array_register,
    local_scalar_register_or_none,
)
from exifmodern.safe_expression.compiler import (  # noqa: F401
    compile_bitwise_expression,
    compile_call_arguments,
    compile_comparison_expression,
    compile_current_item_reference,
    compile_dynamic_input_reference,
    compile_exiftool_call_arguments,
    compile_function_call,
    compile_guarded_numeric_ternary,
    compile_indexed_input_reference,
    compile_local_array_reference,
    compile_local_array_slice_reference,
    compile_local_array_value,
    compile_local_scalar_context_reference,
    compile_local_scalar_reference,
    compile_map_expression,
    compile_map_list,
    compile_node,
    compile_numeric_context_node,
    compile_numeric_expression,
    compile_numeric_unary_expression,
    compile_package_scalar_assignment,
    compile_package_scalar_reference,
    compile_program_statement,
    compile_regex_match_expression,
    compile_runtime_context_assignment,
    compile_runtime_context_assignment_fallback,
    compile_runtime_context_assignment_if_statement,
    compile_runtime_context_path_reference,
    compile_runtime_context_path_segments,
    compile_scalar_dereference_expression,
    compile_scalar_reference_expression,
    compile_self_context_assignment,
    compile_self_context_reference,
    compile_statement_program,
    compile_string_concat_expression,
    compile_string_repeat_expression,
    compile_ternary_expression,
    compile_truthy_and_expression,
    compile_truthy_not_expression,
    compile_truthy_or_expression,
    exiftool_context_argument_input_name,
    exiftool_context_local_input_name,
    hex_group_unpack_lengths_or_none,
    pack_template_value,
    runtime_context_selected_overrides,
    split_separator_value,
    static_string_expression_value_or_none,
    unpack_template_value,
)
from exifmodern.safe_expression.diagnostics import (  # noqa: F401
    INVALID_EXPRESSION_ROOT_TYPES,
    require_expression_root,
)
from exifmodern.safe_expression.errors import SafeExpressionCompileError  # noqa: F401
from exifmodern.safe_expression.facade import (
    compile_ast as compile_ast,
)
from exifmodern.safe_expression.facade import (
    compile_safe_expression as compile_safe_expression,
)
from exifmodern.safe_expression.facade import (
    compile_safe_filter_expression as compile_safe_filter_expression,
)
from exifmodern.safe_expression.facade import (
    fallback_parser as fallback_parser,
)
from exifmodern.safe_expression.facade import (
    parse_safe_expression as parse_safe_expression,
)
from exifmodern.safe_expression.facade import (
    parser as parser,
)
from exifmodern.safe_expression.facade import (
    transform_safe_expression as transform_safe_expression,
)
from exifmodern.safe_expression.function_calls import (  # noqa: F401
    CompiledArguments,
    CompiledExifToolArguments,
)
from exifmodern.safe_expression.grammar import (
    SAFE_EXPRESSION_GRAMMAR as SAFE_EXPRESSION_GRAMMAR,
)
from exifmodern.safe_expression.grammar import (
    safe_expression_earley_parser as safe_expression_earley_parser,
)
from exifmodern.safe_expression.grammar import (
    safe_expression_lalr_parser as safe_expression_lalr_parser,
)
from exifmodern.safe_expression.grammar import (
    safe_expression_parser as safe_expression_parser,
)
from exifmodern.safe_expression.literals import *  # noqa: F403
from exifmodern.safe_expression.runtime_context import (  # noqa: F401
    CompiledContextPathSegments,
    package_scalar_input_name,
    runtime_context_effect_input_name,
    runtime_context_input_name,
    static_runtime_context_path_or_none,
)
from exifmodern.safe_expression.statement_helpers import (  # noqa: F401
    function_statement_from_call,
    function_statement_if_from_call,
    guarded_input_numeric_assignment,
    input_numeric_assignment,
    local_scalar_numeric_assignment_if,
    local_scalar_numeric_assignment_while,
    statement_program_from_children,
    terminal_assignment_program_from_statements,
)
from exifmodern.safe_expression.transformer import SafeExpressionAstTransformer  # noqa: F401
