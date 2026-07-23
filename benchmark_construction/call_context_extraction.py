import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Tree
from woc.local import WocMapsLocal

woc = WocMapsLocal()


def read_blob(sha: str) -> str | None:
    """Read a blob's content by its sha1 value."""
    try:
        return woc.show_content("blob", sha)
    except:
        return None


PY_LANGUAGE = Language(tspython.language())
py_parser = Parser(PY_LANGUAGE)
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

identifier_name_query = PY_LANGUAGE.query(
    """
(identifier) @name
"""
)


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


def extract_names(root: Node, source: bytes):
    # Extract all identifiers first
    identifier_locs = []
    for match in identifier_name_query.matches(root):
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
    names = extract_names(matched.child_by_field_name("arguments"), source)
    for name in names:
        stmt = resolve_alias_name(name[0], alias_mapping)[1]
        if (not stmt) or (stmt in res):
            continue
        res.append(stmt)
    res.append(matched.text.decode(errors="ignore"))

    return "\n".join(res)


def extract_call_context_java(source: bytes | str, caller: str, callee: dict):
    pass
