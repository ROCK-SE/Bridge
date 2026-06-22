import json
import re
from itertools import groupby

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

JAVA_LANGUAGE = Language(tsjava.language())
JAVA_PARSER = Parser(JAVA_LANGUAGE)
with open("config.json") as f:
    dest_folder = json.load(f).get("dest_folder")

JAVA_PRIMITIVE_TYPES = {
    "decimal_integer_literal": "int",
    "hex_integer_literal": "int",
    "octal_integer_literal": "int",
    "binary_integer_literal": "int",
    "decimal_floating_point_literal": "double",
    "hex_floating_point_literal": "double",
    "true": "boolean",
    "false": "boolean",
    "character_literal": "char",
    "string_literal": "String",
}
JAVA_OTHER_TYPES = {
    "null_literal": "null",
    "this": "Object",
    "instanceof_expression": "boolean",
    "class_literal": "Class",
}
SCALA_PRIMITIVE_TYPES = {
    "integer_literal": "Int",
    "floating_point_literal": "Double",
    "boolean_literal": "Boolean",
    "true": "Boolean",
    "false": "Boolean",
    "character_literal": "Char",
    "string": "String",
}
# https://docs.oracle.com/javase/tutorial/java/data/autoboxing.html
JAVA_AUTO_BOXING = (
    ("boolean", "Boolean"),
    ("byte", "Byte"),
    ("char", "Character"),
    ("float", "Float"),
    ("int", "Integer"),
    ("long", "Long"),
    ("short", "Short"),
    ("double", "Double"),
)
# https://docs.oracle.com/javase/specs/jls/se10/html/jls-5.html#jls-5.1.2
WIDENING_PRIMITIVE = {
    "byte": ("short", "int", "long", "float", "double"),
    "short": ("int", "long", "float", "double"),
    "char": ("int", "long", "float", "double"),
    "int": ("long", "float", "double"),
    "long": ("float", "double"),
    "float": ("double"),
}

java_node_type_list = []
for i in range(JAVA_LANGUAGE.node_kind_count):
    is_named = JAVA_LANGUAGE.node_kind_is_named(i)
    if not is_named:
        continue
    name = JAVA_LANGUAGE.node_kind_for_id(i)
    java_node_type_list.append(name)


def text_of(node: Node):
    return node.text.decode(errors="ignore")


def extract_java_type_str(type_node: Node) -> str:
    if type_node.type == "generic_type":
        return text_of(type_node.child(0))
    else:
        return text_of(type_node)


def deal_obj_creation_cast_expr(node: Node) -> str | None:
    type_node = node.child_by_field_name("type")
    if type_node is None:
        return None
    return extract_java_type_str(type_node)


def deal_arr_creation_expr(node: Node) -> str | None:
    type_node = node.child_by_field_name("type")
    if type_node is None:
        return None
    res = extract_java_type_str(type_node)
    for dim_node in node.children_by_field_name("dimensions"):
        dim_text = text_of(dim_node)
        seq = [c for c in dim_text if c in "[]"]
        res = res + "".join(key for key, _ in groupby(seq))
    return res


def normalize_primitive_types(value_type: str | None, value_str: str):
    if (value_type == "int") and (value_str[-1].lower() == "l"):
        value_type = "long"
    if (value_type == "double") and (value_str[-1].lower() == "f"):
        value_type = "float"
    return value_type


def normalize_node_type(node: Node) -> str | None:
    node_text = text_of(node)
    node_type = JAVA_PRIMITIVE_TYPES.get(node.type)
    return normalize_primitive_types(node_type, node_text)


def deal_unary_expr(node: Node) -> str | None:
    operator = text_of(node.child_by_field_name("operator"))
    if operator == "!":
        return "boolean"
    operand_node = node.child_by_field_name("operand")
    return normalize_node_type(operand_node)


def _deal_operand(node: Node):
    node_type = normalize_node_type(node)
    if node_type:
        return node_type
    if node.type == "unary_expression":
        return deal_unary_expr(node)
    if node.type == "binary_expression":
        return deal_binary_expr(node)
    if node.type == "ternary_expression":
        return deal_ternary_expr(node)


def deal_binary_expr(node: Node) -> str | None:
    op_node = node.child_by_field_name("operator")
    if text_of(op_node) in [">", "<", ">=", "<=", "==", "!=", "&&", "||"]:
        return "boolean"
    left_node = node.child_by_field_name("left")
    left_type = _deal_operand(left_node)
    if left_type:
        return left_type

    right_node = node.child_by_field_name("right")
    right_type = _deal_operand(right_node)
    if right_type:
        return right_type


def deal_ternary_expr(node: Node) -> str | None:
    cons_node = node.child_by_field_name("consequence")
    cons_type = _extract_type_from_node(cons_node)
    if cons_type:
        return cons_type
    cons_type = _deal_operand(cons_node)
    if cons_type:
        return cons_type

    alter_node = node.child_by_field_name("alternative")
    alter_type = _extract_type_from_node(alter_node)
    if alter_type:
        return alter_type
    alter_type = _deal_operand(alter_node)
    if alter_type:
        return alter_type


def _extract_type_from_node(node: Node) -> str | None:
    node_type = node.type

    if node_type in ["object_creation_expression", "cast_expression"]:
        return deal_obj_creation_cast_expr(node)
    if node_type == "array_creation_expression":
        return deal_arr_creation_expr(node)
    if node_type == "unary_expression":
        return deal_unary_expr(node)
    if node_type == "binary_expression":
        return deal_binary_expr(node)
    if node_type == "ternary_expression":
        return deal_ternary_expr(node)
    if node_type == "lambda_expression":
        return "lambda_expression"
    if node_type == "method_reference":
        return "method_reference"


def extract_type_from_expression(arg_value: str) -> str | None:
    try:
        root_node = JAVA_PARSER.parse((arg_value + ";").encode()).root_node
        expr_node = root_node.named_children[0].named_children[0]
    except:
        return

    return _extract_type_from_node(expr_node)


def resolve_type(value_type: str, value: str) -> str:
    if value_type in JAVA_PRIMITIVE_TYPES:
        value_type = JAVA_PRIMITIVE_TYPES.get(value_type)
        return normalize_primitive_types(value_type, value)
    elif value_type in JAVA_OTHER_TYPES:
        return JAVA_OTHER_TYPES[value_type]
    elif value_type in SCALA_PRIMITIVE_TYPES:
        value_type = SCALA_PRIMITIVE_TYPES.get(value_type)
        return normalize_primitive_types(value_type, value)
    elif value_type in java_node_type_list:
        res = extract_type_from_expression(value)
        if res:
            return res
        return value
    return value_type


FUNCTION_WORDS = ["callback", "function"]


def split_java_identifier(identifier: str) -> list[str]:
    res = []
    for part in identifier.split("_"):
        if not part:
            continue
        res.extend(
            re.sub("([A-Z][a-z]+)", r" \1", re.sub("([A-Z]+)", r" \1", part)).split()
        )
    return [s.lower() for s in res]


def split_argument(arg_value: str):
    res = []
    for p in re.sub(r"[^a-zA-Z0-9]+", " ", arg_value).strip().split():
        res.extend(split_java_identifier(p))
    return res


def type_matcher(arg_type: str, param_type: str) -> float:
    if arg_type == param_type:
        return 1.0
    if arg_type in WIDENING_PRIMITIVE and param_type in WIDENING_PRIMITIVE[arg_type]:
        return 0.99 - 0.01 * WIDENING_PRIMITIVE[arg_type].index(param_type)
    if (arg_type, param_type) in JAVA_AUTO_BOXING:
        return 0.45
    if (param_type, arg_type) in JAVA_AUTO_BOXING:
        return 0.45
    if param_type in ["Object", "Type", "T", "TypeReference"]:
        return 0.45
    if arg_type == "null":
        return 0.45
    if arg_type in ["lambda_expression", "method_reference"]:
        if any(n in param_type.lower() for n in FUNCTION_WORDS):
            return 0.45
        return 0.0
    param_parts = split_argument(param_type)
    arg_parts = split_argument(arg_type)
    matched = 0
    for p in param_parts:
        if p in arg_parts:
            matched += 0.4
    return matched / len(param_parts)


def type_list_matcher(arg_types: list[str], param_types: list[str]):
    matched = 0
    num_params = len(param_types)
    if len(arg_types) + num_params == 0:
        return 1.0
    for i in range(num_params - 1):
        matched += type_matcher(arg_types[i], param_types[i])
    if param_types[-1].endswith("..."):
        num_remain_args = len(arg_types) - num_params + 1
        if num_remain_args > 0:
            tmp = 0
            for at in arg_types[num_params - 1 :]:
                tmp += type_matcher(at, param_types[-1][:-3])
            matched = matched + tmp / num_remain_args
    else:
        matched += type_matcher(arg_types[-1], param_types[-1])

    return matched / num_params


def best_cand(arguments: list[dict], param_type_lists: list[list]):
    arg_types = []
    for arg in arguments:
        arg_types.append(resolve_type(arg["value_type"], arg["value"]))
    res = 0
    best = -1
    for i in range(len(param_type_lists)):
        sim = type_list_matcher(arg_types, param_type_lists[i])
        if sim > best:
            best = sim
            res = i
    return param_type_lists[res]
