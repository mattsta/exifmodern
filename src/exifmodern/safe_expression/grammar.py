"""Safe-expression grammar and parser construction."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from lark import Lark

SAFE_EXPRESSION_LALR_PARSER_RESOURCE = "safe-expression/safe-expression-lalr.lark"

SAFE_EXPRESSION_GRAMMAR = r"""
start: program -> start_expr

?program: current_item_sub_pipe ";"?
        | program_statement* terminal_assignment ";"? -> terminal_assignment_program
        | program_statement+ final_expression -> statement_program
        | return_expr ";"?
        | expr ","? ";"?

require_stmt: "require" NAME ";"
return_expr: "return" expr -> return_expr
statement_program: program_statement+ final_expression -> statement_program
?program_statement: local_array_assignment ";" -> program_statement
                  | local_array_empty_assignment ";" -> program_statement
                  | idx_set_chain ";" -> program_statement
                  | idx_transform_pair ";" -> program_statement
                  | idx_transform ";" -> program_statement
                  | local_array_push_while ";" -> program_statement
                  | local_array_transform ";" -> program_statement
                  | foreach_array_conditional_set -> program_statement
                  | local_array_slice_transform ";" -> program_statement
                  | local_array_conditional_transform ";" -> program_statement
                  | local_array_pairwise_transform ";" -> program_statement
                  | foreach_conditional_return -> program_statement
                  | input_assignment_and ";" -> program_statement
                  | input_numeric_assignment_and ";" -> program_statement
                  | input_numeric_assignment_if ";" -> program_statement
                  | input_numeric_assignment ";" -> program_statement
                  | input_assignment_if ";" -> program_statement
                  | input_append_if ";" -> program_statement
                  | input_assignment ";" -> program_statement
                  | input_substitution ";" -> program_statement
                  | current_item_assignment ";" -> program_statement
                  | current_item_substitution ";" -> program_statement
                  | current_item_transliteration ";" -> program_statement
                  | local_scalar_tuple_assignment ";" -> program_statement
                  | local_scalar_numeric_assignment_if ";" -> program_statement
                  | local_scalar_numeric_assignment_while ";" -> program_statement
                  | local_scalar_assignment_if ";" -> program_statement
                  | local_scalar_assignment ";" -> program_statement
                  | self_context_assignment_if ";" -> program_statement
                  | postfix_self_context_assignment_if ";" -> program_statement
                  | self_context_assignment ";" -> program_statement
                  | package_scalar_assignment_if ";" -> program_statement
                  | postfix_package_scalar_assignment_if ";" -> program_statement
                  | package_scalar_assignment ";" -> program_statement
                  | warn_return_if_statement ";" -> program_statement
                  | ret_input_num_if ";" -> program_statement
                  | local_scalar_append_if ";" -> program_statement
                  | function_call "if" expr ";" -> function_statement_if
                  | function_call ";" -> function_statement
                  | warn_statement ";" -> program_statement
                  | require_stmt -> program_statement
                  | return_and_statement ";" -> program_statement
                  | return_if_statement ";" -> program_statement
                  | return_unless_statement ";" -> program_statement
                  | return_or_statement ";" -> program_statement
?final_expression: return_expr ";"?
                 | expr ","? ";"?
local_array_assignment: "my" "@" LOCAL_NAME "=" expr -> local_array_assignment
local_array_empty_assignment: "my" "@" LOCAL_NAME -> local_array_empty_assignment
local_array_transform: "$_" "=" expr "foreach" "@" LOCAL_NAME -> local_array_set_transform
                     | "$_" "/=" expr "foreach" "@" LOCAL_NAME -> local_array_div_transform
                     | "$_" "*=" expr "foreach" "@" LOCAL_NAME -> local_array_mul_transform
local_array_slice_transform: "$_" "/=" expr "foreach" local_array_slice_ref -> slice_div_transform
                           | "$_" "*=" expr "foreach" local_array_slice_ref -> slice_mul_transform
local_array_push_while: "push" "@" LOCAL_NAME "," expr "while" expr -> local_array_push_while
idx_transform_pair: idx_transform "," idx_transform -> idx_pair
idx_set_chain: "$" LOCAL_NAME "[" INT "]" "=" "$" LOCAL_NAME "[" INT "]" "=" expr -> idx_set_chain
idx_transform: "$" LOCAL_NAME "[" INT "]" "/=" expr -> idx_div
             | "$" LOCAL_NAME "[" INT "]" "*=" expr -> idx_mul
             | "$" LOCAL_NAME "[" INT "]" "+=" expr -> idx_add
             | "$" LOCAL_NAME "[" INT "]" "-=" expr -> idx_sub
             | "$" LOCAL_NAME "[" INT "]" "&=" expr -> idx_bit_and
             | "$" LOCAL_NAME "[" INT "]" "|=" expr -> idx_bit_or
             | "$" LOCAL_NAME "[" INT "]" "^=" expr -> idx_bit_xor
             | "$" LOCAL_NAME "[" INT "]" "=" expr -> idx_set
local_array_pairwise_transform: pairwise_array_subtract foreach_pairwise_range -> pw_sub
?local_array_conditional_transform: comparison array_subtract_foreach -> array_sub_if
                                  | foreach_array_conditional_set
foreach_array_conditional_set: foreach_array_name foreach_array_set_block -> foreach_array_set
foreach_array_name: "foreach" "(" "@" LOCAL_NAME ")" -> foreach_array_name
foreach_array_set_block: "{" current_item_assignment_if ";" "}" -> foreach_array_set_block
current_item_assignment_if: "$_" "=" expr "if" expr -> current_item_assignment_if
array_subtract_foreach: "and" "$_" "-=" expr "foreach" "@" LOCAL_NAME -> array_subtract_foreach
foreach_conditional_return: foreach_literal_values foreach_return_block -> foreach_return
foreach_return_block: "{" "next" "unless" expr ";" "return" expr ";" "}" -> foreach_return_block
foreach_literal_values: "foreach" "(" INT ("," INT)+ ","? ")" -> foreach_literal_values
pairwise_array_subtract: pairwise_array_ref "-=" pairwise_array_ref -> pairwise_array_subtract
foreach_pairwise_range: "foreach" pairwise_array_range -> foreach_pairwise_range
pairwise_array_ref: "$" LOCAL_NAME "[" "$_" "]" -> pairwise_array_ref
pairwise_array_range: "0" ".." "$#" LOCAL_NAME -> pairwise_array_range
input_assignment: "$val" "=" expr -> input_assignment
input_assignment_and: comparison "and" input_assignment -> input_assignment_and
input_numeric_assignment: "$val" "+=" expr -> input_add_assignment
                        | "$val" "-=" expr -> input_sub_assignment
                        | "$val" "*=" expr -> input_mul_assignment
                        | "$val" "/=" expr -> input_div_assignment
input_numeric_assignment_and: comparison "and" input_numeric_assignment -> input_num_assignment_and
input_numeric_assignment_if: "$val" "+=" expr "if" expr -> input_add_assignment_if
                           | "$val" "-=" expr "if" expr -> input_sub_assignment_if
                           | "$val" "*=" expr "if" expr -> input_mul_assignment_if
                           | "$val" "/=" expr "if" expr -> input_div_assignment_if
input_assignment_if: "$val" "=" expr "if" expr -> input_assignment_if
input_append_if: "$val" ".=" expr "if" expr -> input_append_if
input_substitution: "$val" "=~" SUBSTITUTION -> input_substitution
current_item_assignment: "$_" "=" expr -> current_item_assignment
current_item_substitution: SUBSTITUTION -> current_item_substitution
current_item_transliteration: TRANSLITERATION -> current_item_transliteration
current_item_sub_pipe: current_item_assignment current_item_sub_tail -> current_item_sub_pipe
current_item_sub_tail: "," current_item_substitution "," "$_" -> current_item_sub_tail
local_scalar_assignment: "my" "$" LOCAL_NAME "=" expr -> local_scalar_assignment
                       | "my" "$" LOCAL_NAME -> local_scalar_undef_assignment
                       | "$" LOCAL_NAME "=" expr -> local_scalar_assignment
local_scalar_assignment_if: "$" LOCAL_NAME "=" expr "if" expr -> local_scalar_assignment_if
local_scalar_tuple_assignment: "my" tuple_scalar_targets "=" tuple_expression_values -> scalar_tuple
                             | "my" tuple_scalar_targets "=" expr -> scalar_tuple_from_list
tuple_scalar_targets: "(" tuple_scalar_target ("," tuple_scalar_target)* ","? ")"
tuple_scalar_target: "$" LOCAL_NAME -> tuple_scalar_target
tuple_expression_values: "(" expr ("," expr)+ ","? ")"
?terminal_assignment: input_assignment
                    | input_assignment_if
                    | local_scalar_assignment
local_scalar_append_if: "$" LOCAL_NAME ".=" expr "if" expr -> local_scalar_append_if
local_scalar_numeric_assignment_if: "$" LOCAL_NAME "+=" expr "if" expr -> scalar_add_if
                                  | "$" LOCAL_NAME "-=" expr "if" expr -> scalar_sub_if
                                  | "$" LOCAL_NAME "*=" expr "if" expr -> scalar_mul_if
                                  | "$" LOCAL_NAME "/=" expr "if" expr -> scalar_div_if
local_scalar_numeric_assignment_while: "$" LOCAL_NAME "+=" expr "while" expr -> scalar_add_while
                                     | "$" LOCAL_NAME "-=" expr "while" expr -> scalar_sub_while
                                     | "$" LOCAL_NAME "*=" expr "while" expr -> scalar_mul_while
                                     | "$" LOCAL_NAME "/=" expr "while" expr -> scalar_div_while
warn_statement: "warn" expr -> warn_statement
return_if_statement: "return" expr "if" expr -> return_if_statement
ret_input_num_if: "return" input_numeric_assignment "if" expr -> ret_input_num_if
warn_return_if_statement: function_call "and" "return" expr "if" expr -> warn_return_if_statement
return_and_statement: comparison "and" "return" expr -> return_and_statement
return_unless_statement: "return" expr "unless" expr -> return_unless_statement
return_or_statement: expr "or" "return" expr -> return_or_statement

?expr: context_assignment
     | ternary

?context_assignment: self_context_assignment
                   | package_scalar_assignment

?ternary: or_expr
        | or_expr "?" expr ":" expr -> ternary_expr

?or_expr: and_expr
        | or_expr "or" and_expr -> truthy_or
        | or_expr "||" and_expr -> truthy_or

?and_expr: comparison
         | and_expr "and" comparison -> truthy_and
         | and_expr "&&" comparison -> truthy_and

?comparison: bit_or
           | bit_or "=~" REGEX -> regex_match
           | bit_or "!~" REGEX -> regex_not_match
           | bit_or "==" bit_or -> num_eq
           | bit_or "!=" bit_or -> num_ne
           | bit_or "<=" bit_or -> le
           | bit_or ">=" bit_or -> ge
           | bit_or "<" bit_or -> lt
           | bit_or ">" bit_or -> gt
           | bit_or "eq" bit_or -> str_eq
           | bit_or "ne" bit_or -> str_ne
           | bit_or "lt" bit_or -> str_lt
           | bit_or "le" bit_or -> str_le
           | bit_or "gt" bit_or -> str_gt
           | bit_or "ge" bit_or -> str_ge

?bit_or: bit_xor
       | bit_or "|" bit_xor -> bit_or

?bit_xor: bit_and
        | bit_xor "^" bit_and -> bit_xor

?bit_and: shift
        | bit_and "&" shift -> bit_and

?shift: concat
      | shift "<<" concat -> shift_left
      | shift ">>" concat -> shift_right

?concat: repeat
       | concat "." repeat -> concat

?repeat: sum
       | repeat "x" sum -> repeat

?sum: product
    | sum "+" product -> add
    | sum "-" product -> sub

?product: unary
        | product "*" unary -> mul
        | product "/" unary -> div
        | product "%" unary -> mod

?unary: "not" unary -> truthy_not
      | "!" unary -> truthy_not
      | "-" unary -> neg
      | "+" unary -> pos
      | power

?power: atom
      | atom "**" unary -> pow

?atom: val_unit_suffix
     | val_ref
     | scalar_ref
     | self_context_ref
     | self_method_call
     | scalar_deref
     | "$_" -> current_item_ref
     | "@val" -> val_list_ref
     | "@raw" -> raw_list_ref
     | prt_ref
     | package_scalar_ref
     | "$^O" -> system_os_ref
     | "$self" -> self_ref
     | "$tag" -> tag_ref
     | local_array_ref
     | local_array_slice_ref
     | local_scalar_ref
     | "@" LOCAL_NAME -> local_array_value
     | map_block_call
     | map_paren_block_call
     | map_function_call
     | map_unary_call
     | eval_block
     | function_call
     | bareword_function_call
     | QW_LIST -> qw_list
     | HEX_NUMBER -> hex_number
     | OCT_NUMBER -> oct_number
     | SIGNED_NUMBER -> number
     | STRING -> string
     | REGEX -> regex_string
     | "undef" -> undef
     | "(" expr ")"

val_ref: "$val" ["[" expr "]"]
val_unit_suffix: val_ref NAME -> val_unit_suffix
prt_ref: "$prt" ["[" expr "]"]
self_context_ref: "$$self" context_key_path -> self_context_ref
                | "$self" "->" context_key_path -> self_context_ref
self_context_assignment: self_context_ref "=" expr -> self_context_assignment
self_context_assignment_if: comparison "and" self_context_assignment -> self_context_assignment_if
postfix_self_context_assignment_if: self_context_assignment "if" expr -> postfix_self_assign_if
self_method_call: "$self" "->" NAME "(" [arguments] ")" -> self_method_call
package_scalar_ref: "$" PACKAGE_NAME [context_key_path] -> package_scalar_ref
package_scalar_assignment: package_scalar_ref "=" expr -> package_scalar_assignment
package_scalar_assignment_if: comparison "and" package_scalar_assignment -> pkg_scalar_assign_if
postfix_package_scalar_assignment_if: package_scalar_assignment "if" expr -> postfix_pkg_assign_if
context_key_path: context_key+ -> context_key_path
?context_key: "{" NAME "}" -> static_context_key
            | "{" expr "}" -> dynamic_context_key
            | "[" expr "]" -> dynamic_context_key
local_array_ref: "$" LOCAL_NAME "[" expr "]"
local_array_slice_ref: "@" LOCAL_NAME "[" INT ("," INT)+ "]"
local_scalar_ref: "$" LOCAL_NAME
scalar_ref: "\\" scalar_ref_value -> scalar_ref
?scalar_ref_value: val_ref
                 | local_scalar_ref
                 | self_context_ref
                 | package_scalar_ref
                 | array_ref_value
array_ref_value: "@val" -> val_list_ref
               | "@" LOCAL_NAME -> local_array_ref_value
scalar_deref: "$$" LOCAL_NAME [context_key_path] -> scalar_deref
            | "$" "{" braced_scalar_deref_value "}" -> braced_scalar_deref
?braced_scalar_deref_value: val_ref
                          | local_scalar_ref

function_call: NAME "(" [arguments] ")"
map_block_call: "map" "{" expr "}" expr -> map_block_call
map_paren_block_call: "map" "(" "{" expr "}" expr ")" -> map_block_call
map_function_call: "map" function_call "," expr -> map_function_call
map_unary_call: "map" NAME "," expr -> map_unary_call
eval_block: "eval" "{" expr "}" -> eval_block
bareword_function_call: NAME atom ("," expr)*
arguments: expr ("," expr)* ","?

PACKAGE_NAME.2: /[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)+/
NAME: /[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*/
LOCAL_NAME: /[A-Za-z_][A-Za-z0-9_]*/
QW_LIST.2: /qw\([^)]*\)/
HEX_NUMBER.2: /0x[0-9a-fA-F]+/
OCT_NUMBER.2: /0[0-7]+/
STRING: ESCAPED_STRING | SINGLE_QUOTED_STRING
SINGLE_QUOTED_STRING: /'([^'\\]|\\.)*'/
REGEX: /\/([^\/\\]|\\.)*\/[a-z]*/
SUBSTITUTION: /s\/([^\/\\]|\\.)*\/([^\/\\]|\\.)*\/[a-z]*/
TRANSLITERATION.3: /tr\/([^\/\\]|\\.)*\/([^\/\\]|\\.)*\//

%import common.ESCAPED_STRING
%import common.SIGNED_NUMBER
%import common.INT
%import common.WS
%ignore WS
%ignore /#[^\n]*/
"""


def build_safe_expression_lalr_parser() -> Lark:
    return Lark(
        SAFE_EXPRESSION_GRAMMAR,
        parser="lalr",
        start="start",
        maybe_placeholders=False,
    )


def build_safe_expression_earley_parser() -> Lark:
    return Lark(
        SAFE_EXPRESSION_GRAMMAR,
        parser="earley",
        start="start",
        maybe_placeholders=False,
    )


@lru_cache(maxsize=1)
def safe_expression_lalr_parser() -> Lark:
    saved = load_safe_expression_lalr_parser_resource()
    if saved is not None:
        return saved
    return build_safe_expression_lalr_parser()


@lru_cache(maxsize=1)
def safe_expression_earley_parser() -> Lark:
    return build_safe_expression_earley_parser()


def safe_expression_parser() -> Lark:
    return safe_expression_lalr_parser()


def load_safe_expression_lalr_parser_resource() -> Lark | None:
    resource = files("exifmodern.data").joinpath(*SAFE_EXPRESSION_LALR_PARSER_RESOURCE.split("/"))
    if not resource.is_file():
        return None
    with resource.open("rb") as file:
        return Lark.load(file)
