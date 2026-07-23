import tree_sitter_java as tsjava
import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Tree
from woc.local import WocMapsLocal

woc = WocMapsLocal()


PY_LANGUAGE = Language(tspython.language())
py_parser = Parser(PY_LANGUAGE)
JAVA_LANGUAGE = Language(tsjava.language())
java_parser = Parser(JAVA_LANGUAGE)

py_import_query = PY_LANGUAGE.query(
    """
(import_statement
    ([
        name: (dotted_name) @import_name
        name: (aliased_import
            name: (dotted_name) @import_name
            alias: (identifier) @alias_name)
    ]))@import_node

(import_from_statement
    module_name: (dotted_name) @from_module
    ([
        name: (dotted_name) @import_name
        name: (aliased_import
            name: (dotted_name) @import_name
            alias: (identifier) @alias_name)
    ]))@import_node
"""
)
py_call_query = PY_LANGUAGE.query(
    """
(call
    function: (primary_expression) @name
    arguments: (argument_list) @arguments) @call
"""
)

python_identifier_name_query = PY_LANGUAGE.query(
    """
(identifier) @name
"""
)

java_import_query = JAVA_LANGUAGE.query(
    """
(import_declaration
    (identifier) @import_name .) @statement
(import_declaration
    (scoped_identifier) @import_name .) @statement
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

java_identifier_name_query = JAVA_LANGUAGE.query(
    """
(identifier) @name
"""
)


def read_blob(sha: str) -> str | None:
    """Read a blob's content by its sha1 value."""
    try:
        return woc.show_content("blob", sha)
    except:
        return None


def parse_imports_python(tree: Tree) -> dict[str, tuple[str, str]]:
    alias_mapping = {}

    for match in py_import_query.matches(tree.root_node):
        import_name = match[1]["import_name"][0].text.decode(errors="ignore")
        import_alias = None
        if "alias_name" in match[1]:
            alias_name = match[1]["alias_name"][0].text.decode(errors="ignore")
            import_alias = alias_name
        else:
            alias_name = import_name
        if match[0] == 1:
            from_module = match[1]["from_module"][0].text.decode(errors="ignore")
            statement = f"from {from_module} import {import_name}"
            import_name = f"{from_module}.{import_name}"

        else:
            statement = f"import {import_name}"
        if import_alias:
            statement = statement + f" as {alias_name}"
        alias_mapping[alias_name] = (import_name, statement)

    return alias_mapping


def resolve_alias_name(
    name: str, alias_mapping: dict[str, str]
) -> tuple[str | None, str | None]:
    parts = name.split(".")
    for i in range(len(parts)):
        cur_name = ".".join(parts[: i + 1])
        alias = alias_mapping.get(cur_name)
        if alias is None:
            continue
        return ".".join([alias[0]] + parts[i + 1 :]), alias[1]

    return None, None


def get_caller_py(cur_node: Node):
    parent = cur_node.parent
    context = []
    line_no = 0
    while parent:
        if parent.type == "module":
            if len(context) == 0:
                line_no = parent.start_point[0]
            break
        elif parent.type == "function_definition":
            if len(context) == 0:
                line_no = parent.start_point[0]
            context.append(
                f"{parent.child_by_field_name('name').text.decode(errors='ignore')}()"
            )
        elif parent.type == "class_definition":
            if len(context) == 0:
                line_no = parent.start_point[0]
            context.append(
                parent.child_by_field_name("name").text.decode(errors="ignore")
            )
        parent = parent.parent
    return ".".join(reversed(context)), line_no


def merge_identifiers(identifier_locs: list, source: bytes):
    # First pass: merge identifiers separated only by a dot and whitespace.
    initial_merge = []
    longest_match, last_start, last_end = identifier_locs[0]
    for name, start, end in identifier_locs[1:]:
        separator = source[last_end:start]
        if separator.strip() == b".":
            longest_match += "." + name
            last_end = end
        else:
            initial_merge.append((longest_match, last_start, last_end))
            longest_match = name
            last_start = start
            last_end = end
    initial_merge.append((longest_match, last_start, last_end))

    # Second pass: discard a sequence that starts after a dot.
    #
    # a.b().c.d
    # ------ ----
    #  a.b    c.d
    #
    # c.d starts after a dot, so discard the entire sequence.
    results = []
    for name, start, end in initial_merge:
        prefix = source[:start].rstrip()
        if prefix.endswith(b"."):
            continue
        results.append((name, start, end))

    return results


def extract_python_names(root: Node, source: bytes):
    # Extract all identifiers first
    identifier_locs = []
    for match in python_identifier_name_query.matches(root):
        node = match[1]["name"][0]
        parent = node.parent

        # Skip only `name` in name=value, not `value`.
        if (
            parent is not None
            and parent.type == "keyword_argument"
            and parent.child_by_field_name("name") == node
        ):
            continue

        identifier_locs.append(
            (
                source[node.start_byte : node.end_byte].decode(errors="ignore"),
                node.start_byte,
                node.end_byte,
            )
        )
    # Sort query results by starting bytes.
    identifier_locs.sort(key=lambda item: item[1])
    # No identifiers
    if not identifier_locs:
        return []

    return merge_identifiers(identifier_locs, source)


def extract_call_context_python(source: bytes | str, caller: str, callee: dict):
    if isinstance(source, str):
        source = source.encode()
    tree = py_parser.parse(source)

    alias_mapping = parse_imports_python(tree)

    matched, import_stmt = None, None
    for match in py_call_query.matches(tree.root_node):
        name = match[1]["name"][0].text.decode(errors="ignore")
        if not all(i.isidentifier() for i in name.split(".")):
            continue

        # full_name match
        full_name, import_stmt = resolve_alias_name(name, alias_mapping)
        if full_name is None:
            continue
        if full_name != callee["full_name"]:
            continue

        # caller match
        cur_node = match[1]["call"][0]
        cur_caller, caller_line_no = get_caller_py(cur_node)
        if cur_caller != caller:
            continue
        # offset match
        offset = match[1]["name"][0].start_point[0] - caller_line_no
        if offset != callee["offset"]:
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
            if arg_info["value_type"] == "comment":
                continue
            arguments.append(arg_info)
        if arguments != callee["arguments"]:
            continue
        matched = match[1]["call"][0]
        break

    if matched is None:
        return ""

    res = [import_stmt] if import_stmt else []
    names = extract_python_names(matched.child_by_field_name("arguments"), source)
    for name in names:
        stmt = resolve_alias_name(name[0], alias_mapping)[1]
        if (not stmt) or (stmt in res):
            continue
        res.append(stmt)
    res.append(matched.text.decode(errors="ignore"))

    return "\n".join(res)


def parse_imports_java(tree: Tree):
    class_mappings = {}
    for match in java_import_query.matches(tree.root_node):
        import_name = match[1]["import_name"][0].text.decode(errors="ignore")
        import_stmt = match[1]["statement"][0].text.decode(errors="ignore")
        # if any(import_name.startswith(f"{p}.") for p in JAVA_STDLIB):
        #     continue
        class_mappings[import_name.split(".")[-1]] = (import_name, import_stmt)
    return class_mappings


def get_caller_java(cur_node: Node):
    parent = cur_node.parent
    context = []
    line_no = 0
    while parent:
        if parent.type == "program":
            if len(context) == 0:
                line_no = parent.start_point[0]
            break
        elif parent.type in ["method_declaration", "constructor_declaration"]:
            if len(context) == 0:
                line_no = parent.start_point[0]
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
            if len(context) == 0:
                line_no = parent.start_point[0]
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
            if len(context) == 0:
                line_no = parent.start_point[0]
            class_name = parent.child_by_field_name("name").text.decode(errors="ignore")
            context.append(f"{parent.type.split('_')[0]}@{class_name}")
        parent = parent.parent

    return tuple(reversed(context)), line_no


def parse_variable_types_java(tree: Tree):
    variable_types = {}
    for match in java_variable_declaration_query.matches(tree.root_node):
        declaration_node = match[1]["variable_declaration"][0]
        declaration_stmt = declaration_node.text.decode(errors="ignore")
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

        if (
            declaration_node.type in ["enhanced_for_statement", "instanceof_expression"]
            or len(declaration_stmt) > 100
        ):
            declaration_stmt = (
                f"{type_node.text.decode(errors='ignore')} {identifier_str};"
            )

        context, _ = get_caller_java(declaration_node)
        variable_types[identifier_str] = variable_types.get(identifier_str, {})
        if context not in variable_types[identifier_str]:
            variable_types[identifier_str][context] = [
                (line_no, type_str, declaration_stmt)
            ]
        else:
            variable_types[identifier_str][context].append(
                (line_no, type_str, declaration_stmt)
            )

    return variable_types


def resolve_obj_type_java(
    obj_name: str,
    context: tuple[str],
    line_no: int,
    variable_types: dict[str, dict[str, list[tuple[int, str]]]],
) -> str | None:
    if obj_name not in variable_types:
        return obj_name, None
    context_type_info = variable_types.get(obj_name)
    context_len = len(context)
    for i in range(context_len):
        tmp_context = context[: context_len - i]
        if tmp_context in context_type_info:
            res = context_type_info[tmp_context][0][1]
            stmt = context_type_info[tmp_context][0][2]
            for l, t, s in context_type_info[tmp_context][1:]:
                if l > line_no:
                    break
                res = t
                stmt = s
            return res, stmt
    return obj_name, None


def extract_java_names(root: Node, source: bytes):
    # Extract all identifiers first
    identifier_locs = []
    for match in java_identifier_name_query.matches(root):
        node = match[1]["name"][0]
        parent = node.parent

        # Skip only `name` in name=value, not `value`.
        if (
            parent is not None
            and parent.type == "keyword_argument"
            and parent.child_by_field_name("name") == node
        ):
            continue

        identifier_locs.append(
            (
                source[node.start_byte : node.end_byte].decode(errors="ignore"),
                node.start_byte,
                node.end_byte,
            )
        )
    # Sort query results by starting bytes.
    identifier_locs.sort(key=lambda item: item[1])
    # No identifiers
    if not identifier_locs:
        return []

    return merge_identifiers(identifier_locs, source)


def extract_call_context_java(source: bytes | str, caller: str, callee: dict):
    if isinstance(source, str):
        source = source.encode()

    tree = java_parser.parse(source)

    class_mappings = parse_imports_java(tree)
    variable_types = parse_variable_types_java(tree)

    matched, import_stmt, decl_stmt = None, None, None
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
        context, caller_line_no = get_caller_java(cur_node)
        # caller and offset match
        if (list(context) != caller) or (line_no - caller_line_no != callee["offset"]):
            continue
        if left_part in variable_types:
            left_part, decl_stmt = resolve_obj_type_java(
                left_part, context, line_no, variable_types
            )
        if left_part not in class_mappings:
            continue
        left_part_type, import_stmt = class_mappings.get(left_part)
        method_name = ".".join([left_part_type] + right_parts)
        # full_name match
        if method_name != callee["full_name"]:
            continue

        arguments_node = match[1]["arguments"][0]
        arguments = []
        for arg_node in arguments_node.named_children:
            arg_value = arg_node.text.decode(errors="ignore")
            arg_type = arg_node.type
            if arg_type == "line_comment":
                continue
            elif arg_type == "block_comment":
                continue
            elif arg_type == "identifier":
                arg_type, _ = resolve_obj_type_java(
                    arg_value, context, line_no, variable_types
                )
            arguments.append(
                {
                    "value": arg_value,
                    "value_type": arg_type,
                }
            )
        # arguments match
        if arguments != callee["arguments"]:
            continue
        matched = match[1]["method_invocation"][0]
        break

    if matched is None:
        return ""

    import_statements = [import_stmt] if import_stmt else []
    decl_statements = [decl_stmt] if decl_stmt else []

    for name, _, _ in extract_java_names(arguments_node, source):
        recv_type, d_stmt = resolve_obj_type_java(
            name.split(".")[0], context, line_no, variable_types
        )
        if d_stmt:
            decl_statements.append(d_stmt)
        if recv_type not in class_mappings:
            continue
        left_part_type, i_stmt = class_mappings.get(recv_type)
        if i_stmt:
            import_statements.append(i_stmt)
    res = []
    for s in (
        import_statements + decl_statements + [matched.text.decode(errors="ignore")]
    ):
        if not s.rstrip().endswith(";"):
            s = s + ";"
        if s not in res:
            res.append(s)

    return "\n".join(res)
