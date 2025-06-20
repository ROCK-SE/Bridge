import itertools
import json
import logging
import math
import os
import sys


from argparse import ArgumentParser

import tree_sitter_java as tsjava
import tree_sitter_python as tspython
from isort.stdlibs.all import stdlib
from joblib import Parallel, delayed
from tqdm import tqdm
from tree_sitter import Language, Node, Parser, Tree
from utils import java_package_list
from woc.local import decomp_or_raw

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

PY_LANGUAGE = Language(tspython.language())
py_parser = Parser(PY_LANGUAGE)
JAVA_LANGUAGE = Language(tsjava.language())
java_parser = Parser(JAVA_LANGUAGE)


if not os.path.exists("java_standard_packages.json"):
    java_package_list()
JAVA_STDLIB = list(
    set(
        itertools.chain.from_iterable(
            json.load(open("java_standard_packages.json")).values()
        )
    )
)

py_import_query = PY_LANGUAGE.query(
    """
(import_statement
    ([
        name: (dotted_name) @import_name
        name: (aliased_import
            name: (dotted_name) @import_name
            alias: (identifier) @alias_name)
    ]))

(import_from_statement
    module_name: (dotted_name) @from_module
    ([
        name: (dotted_name) @import_name
        name: (aliased_import
            name: (dotted_name) @import_name
            alias: (identifier) @alias_name)
    ]))
"""
)

py_call_query = PY_LANGUAGE.query(
    """
(call
    function: (primary_expression) @name
    arguments: (argument_list) @arguments) @call
"""
)


java_import_query = JAVA_LANGUAGE.query(
    """
(import_declaration
    (identifier) @import_name .)
(import_declaration
    (scoped_identifier) @import_name .)
"""
)

java_variable_declaration_query = JAVA_LANGUAGE.query(
    """
(instanceof_expression
    right: (_) @type
    name: (_) @identifier) @variable_declaration
(type_pattern
    (_) @type
    (_) @identifier) @variable_declaration
(record_pattern_component
    (_) @type
    (_) @identifier) @variable_declaration
(catch_formal_parameter
    (catch_type . (_) @type)
    name: (_) @identifier
    !dimensions) @variable_declaration
(resource
    type: (_) @type
    name: (_) @identifier
    !dimensions) @variable_declaration
(enhanced_for_statement
    type: (_) @type
    name: (_) @identifier
    !dimensions) @variable_declaration
(field_declaration
    type: (_) @type
    (variable_declarator
        name: (_) @identifier
        !dimensions)) @variable_declaration
(formal_parameter
    type: (_) @type
    name: (_) @identifier
    !dimensions) @variable_declaration
(constant_declaration
    type: (_) @type
    (variable_declarator
        name: (_) @identifier
        !dimensions)) @variable_declaration
(local_variable_declaration
    type: (_) @type
    (variable_declarator
        name: (_) @identifier
        !dimensions)) @variable_declaration
"""
)

java_call_query = JAVA_LANGUAGE.query(
    """
(method_invocation
    object: (_)? @object
    .
    name: (_) @name
    arguments: (argument_list) @arguments)@method_invocation
"""
)


def parse_imports_python(tree: Tree):
    alias_mapping = {}

    for match in py_import_query.matches(tree.root_node):
        import_name = match[1]["import_name"][0].text.decode(errors="ignore")
        if "alias_name" in match[1]:
            alias_name = match[1]["alias_name"][0].text.decode(errors="ignore")
        else:
            alias_name = import_name
        if match[0] == 1:
            from_module = match[1]["from_module"][0].text.decode(errors="ignore")
            import_name = f"{from_module}.{import_name}"
        if import_name.split(".")[0] in stdlib:
            continue
        alias_mapping[alias_name] = import_name

    return alias_mapping


def resolve_alias_name(name: str, alias_mapping: dict[str, str]) -> str | None:
    parts = name.split(".")
    for i in range(len(parts)):
        cur_name = ".".join(parts[: i + 1])
        alias = alias_mapping.get(cur_name)
        if alias is None:
            continue
        return ".".join([alias] + parts[i + 1 :])

    return None


def get_caller_py(cur_node: Node):
    parent = cur_node.parent
    context = []
    while parent:
        if parent.type == "module":
            break
        elif parent.type == "function_definition":
            context.append(
                f"{parent.child_by_field_name('name').text.decode(errors='ignore')}()"
            )
        elif parent.type == "class_definition":
            context.append(
                parent.child_by_field_name("name").text.decode(errors="ignore")
            )
        parent = parent.parent
    return ".".join(reversed(context))


def parse_api_calls_python(source: bytes | str):
    if isinstance(source, str):
        source = source.encode()

    tree = py_parser.parse(source)

    alias_mapping = parse_imports_python(tree)
    modules = list(set(alias_mapping.values()))

    call_graphs = {}
    for match in py_call_query.matches(tree.root_node):
        name = match[1]["name"][0].text.decode(errors="ignore")
        if not all(i.isidentifier() for i in name.split(".")):
            continue
        full_name = resolve_alias_name(name, alias_mapping)
        if full_name is None:
            continue

        arguments_node = match[1]["arguments"][0]
        arguments = []
        for arg in arguments_node.named_children:
            arg_type = arg.type
            arg_text = arg.text.decode(errors="ignore")
            if arg_type == "keyword_argument":
                keyword_name = arg.child_by_field_name("name")
                keyword_value = arg.child_by_field_name("value")
                arg_info = {
                    "arg_type": "keyword",
                    "key": keyword_name.text.decode(errors="ignore"),
                    "value": keyword_value.text.decode(errors="ignore"),
                    "value_type": keyword_value.type,
                }
            elif arg_type == "dictionary_splat":
                tmp_node = arg.children[1]
                arg_info = {
                    "arg_type": "**keyword",
                    "value": tmp_node.text.decode(errors="ignore"),
                    "value_type": tmp_node.type,
                }
            elif arg_type == "list_splat":
                tmp_node = arg.children[1]
                arg_info = {
                    "arg_type": "*positional",
                    "value": tmp_node.text.decode(errors="ignore"),
                    "value_type": tmp_node.type,
                }
            else:
                arg_info = {
                    "arg_type": "positional",
                    "value": arg_text,
                    "value_type": arg_type,
                }
            arguments.append(arg_info)

        cur_node = match[1]["call"][0]
        caller = get_caller_py(cur_node)

        line_no = match[1]["name"][0].start_point[0]
        call_graphs[caller] = call_graphs.get(caller, [])
        call_graphs[caller].append(
            {"full_name": full_name, "line_no": line_no, "arguments": arguments}
        )

    return {
        "modules": modules,
        "api_calls": [{"caller": k, "callee": v} for k, v in call_graphs.items()],
    }


def parse_imports_java(tree: Tree):
    class_mappings = {}
    for match in java_import_query.matches(tree.root_node):
        import_name = match[1]["import_name"][0].text.decode(errors="ignore")
        if any(import_name.startswith(f"{p}.") for p in JAVA_STDLIB):
            continue
        class_mappings[import_name.split(".")[-1]] = import_name
    return class_mappings


def get_caller_java(cur_node: Node):
    parent = cur_node.parent
    context = []
    while parent:
        if parent.type == "program":
            break
        elif parent.type in ["method_declaration", "constructor_declaration"]:
            method_name = parent.child_by_field_name("name").text.decode(
                errors="ignore"
            )
            method_parameters = parent.child_by_field_name("parameters")
            parameter_types = []
            for param in method_parameters.named_children:
                if param.type == "formal_parameter":
                    t = param.child_by_field_name("type").text.decode(errors="ignore")
                    parameter_types.append(t)
            context.append(f"{method_name}({', '.join(parameter_types)})")
        elif parent.type == "compact_constructor_declaration":
            context.append(
                parent.child_by_field_name("name").text.decode(errors="ignore")
            )
        elif parent.type in [
            "class_declaration",
            "record_declaration",
            "enum_declaration",
            "interface_declaration",
            "annotation_type_declaration",
        ]:
            class_name = parent.child_by_field_name("name").text.decode(errors="ignore")
            context.append(f"{parent.type.split('_')[0]}@{class_name}")
        parent = parent.parent

    return tuple(reversed(context))


def parse_variable_types_java(tree: Tree):
    variable_types = {}
    for match in java_variable_declaration_query.matches(tree.root_node):
        declaration_node = match[1]["variable_declaration"][0]
        line_no = declaration_node.start_point[0]

        type_node = match[1]["type"][0]
        if type_node.type in ["annotated_type", "array_type"]:
            continue
        if type_node.type == "generic_type":
            type_str = type_node.child(0).text.decode(errors="ignore")
        else:
            type_str = type_node.text.decode(errors="ignore")

        identifier_str = match[1]["identifier"][0].text.decode(errors="ignore")
        if identifier_str == "_":
            continue

        context = get_caller_java(declaration_node)
        variable_types[identifier_str] = variable_types.get(identifier_str, {})
        if context not in variable_types[identifier_str]:
            variable_types[identifier_str][context] = [(line_no, type_str)]
        else:
            variable_types[identifier_str][context].append((line_no, type_str))

    return variable_types


def resolve_obj_type_java(
    obj_name: str,
    context: tuple[str],
    line_no: int,
    variable_types: dict[str, dict[str, list[tuple[int, str]]]],
) -> str | None:
    if obj_name not in variable_types:
        return obj_name
    context_type_info = variable_types.get(obj_name)
    context_len = len(context)
    for i in range(context_len):
        tmp_context = context[: context_len - i]
        if tmp_context in context_type_info:
            res = context_type_info[tmp_context][0][1]
            for l, t in context_type_info[tmp_context][1:]:
                if l > line_no:
                    break
                res = t
            return res
    return obj_name


def parse_api_calls_java(source: bytes | str):
    if isinstance(source, str):
        source = source.encode()

    tree = java_parser.parse(source)

    class_mappings = parse_imports_java(tree)
    variable_types = parse_variable_types_java(tree)

    call_graphs = {}
    for match in java_call_query.matches(tree.root_node):
        method_name = match[1]["name"][0].text.decode(errors="ignore")
        if "object" in match[1]:
            obj_node = match[1]["object"][0]
            if obj_node.type in ["identifier", "_reserved_identifier", "field_access"]:
                obj_name = obj_node.text.decode(errors="ignore")
                method_name = f"{obj_name}.{method_name}"
            else:
                continue

        parts = method_name.split(".")
        left_part, right_parts = parts[0], parts[1:]
        if (left_part not in variable_types) and (left_part not in class_mappings):
            continue
        cur_node = match[1]["method_invocation"][0]
        line_no = cur_node.start_point[0]
        context = get_caller_java(cur_node)
        if left_part in variable_types:
            left_part = resolve_obj_type_java(
                left_part, context, line_no, variable_types
            )
        if left_part not in class_mappings:
            continue
        left_part_type = class_mappings.get(left_part)
        method_name = ".".join([left_part_type] + right_parts)

        arguments_node = match[1]["arguments"][0]
        arguments = []
        for arg_node in arguments_node.named_children:
            arg_value = arg_node.text.decode(errors="ignore")
            arg_type = arg_node.type
            if arg_type == "identifier":
                arg_type = resolve_obj_type_java(
                    arg_value, context, line_no, variable_types
                )
            arguments.append(
                {
                    "value": arg_value,
                    "value_type": arg_type,
                }
            )

        call_graphs[context] = call_graphs.get(context, [])
        call_graphs[context].append(
            {"full_name": method_name, "line_no": line_no, "arguments": arguments}
        )

    return {
        "modules": list(class_mappings.values()),
        "api_calls": [{"caller": k, "callee": v} for k, v in call_graphs.items()],
    }


def read_raw_blob(idx: int, offset: int, length: int) -> bytes:
    with open(f"/woc/All.blobs/blob_{idx}.bin", "rb") as f:
        f.seek(offset)
        return decomp_or_raw(f.read(length))


def generate_batch(lang: str, batch_size: int):
    batch = []
    with open(f"../benchmark/updates/{lang}blob.idx") as f:
        for line in f:
            blob_sha, offset, length = line.strip("\n").split(";")
            batch.append([blob_sha, int(offset), int(length)])
            if len(batch) == batch_size:
                yield batch
                batch = []
        if batch:
            yield batch


def parse_batch(lang: str, i: int, batch: list):
    if lang == "py":
        parser = parse_api_calls_python
        api_calls = [[], {}]
    elif lang == "java":
        parser = parse_api_calls_java
        api_calls = [[], []]

    res = {}
    for blob_sha, offset, length in batch:
        idx = int(blob_sha[:2], base=16) % 128
        try:
            raw_content = read_raw_blob(idx, int(offset), int(length))
            api_calls = parser(raw_content)
        except:
            logger.error(f"Parse Error: {lang}, {blob_sha}, {offset}, {length}")
        res[blob_sha] = api_calls

    logger.error(f"{lang} {i}: Start dumping results...")
    with open(f"../benchmark/updates/{lang}blob_api_calls.json.{i}", "w") as outf:
        json.dump(res, outf)


def parse_all(lang: str, n_jobs: int = 1, batch_size: int = 1):
    total_lines = sum(1 for i in open(f"../benchmark/updates/{lang}blob.idx", "rb"))
    num_batches = math.ceil(total_lines / batch_size)
    print(
        f"{lang}: {n_jobs} processes",
        f"{batch_size} blobs/batch",
        f"{total_lines} lines",
        f"{num_batches} batches",
    )
    batches = generate_batch(lang, batch_size)
    Parallel(n_jobs=n_jobs, backend="multiprocessing")(
        delayed(parse_batch)(lang, i, batch)
        for i, batch in tqdm(enumerate(batches), total=num_batches, file=sys.stdout)
    )


if __name__ == "__main__":
    parser = ArgumentParser(
        prog="python import_parsing.py",
        description="Parse imported modules in Java/Python files",
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")
    parser.add_argument(
        "-b",
        "--batch_size",
        type=int,
        default=1,
        help="number of blobs to processed in a batch",
    )
    parser.add_argument("--python", action="store_true", help="Parse Python files")
    parser.add_argument("--java", action="store_true", help="Parse Java files")

    args = parser.parse_args()
    if args.python:
        parse_all("py", args.n_jobs, args.batch_size)
    if args.java:
        parse_all("java", args.n_jobs, args.batch_size)
