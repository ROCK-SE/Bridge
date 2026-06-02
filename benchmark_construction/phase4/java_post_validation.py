import logging
import os
import zipfile

import tree_sitter_java as tsjava
import tree_sitter_scala as tsscala
from tree_sitter import Language, Node, Parser
from utils import construct_file_tree, gen_sources_jar_path, parse_imports_java

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
debug_fh = logging.FileHandler("../../log/java_api_signature_resolver.debug", mode="w")
debug_fh.setLevel(logging.DEBUG)
info_fh = logging.FileHandler("../../log/java_api_signature_resolver.info", mode="w")
info_fh.setLevel(logging.INFO)
# create formatter and add it to the handlers
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(lineno)d %(message)s")
debug_fh.setFormatter(formatter)
info_fh.setFormatter(formatter)
# add the handlers to logger
logger.addHandler(debug_fh)
logger.addHandler(info_fh)

JAVA_LANGUAGE = Language(tsjava.language())
SCALA_LANGUAGE = Language(tsscala.language())
JAVA_PARSER = Parser(JAVA_LANGUAGE)
SCALA_PARSER = Parser(SCALA_LANGUAGE)


def text_of(node: Node) -> str:
    if node is None:
        return ""
    return node.text.decode(errors="ignore")


def has_deprecated_java_annotation(node: Node) -> bool:
    if not node.children:
        return False
    if node.children[0].type != "modifiers":
        return False

    modifiers_node = node.children[0]
    for node in modifiers_node.named_children:
        if node.type not in ["annotation", "marker_annotation"]:
            continue
        annotation_name = text_of(node.child_by_field_name("name"))
        if annotation_name in ["Deprecated", "java.lang.Deprecated"]:
            return True

    return False


def has_deprecated_scala_annotation(node: Node) -> bool:
    if not node.children:
        return False

    for child in node.named_children:
        if child.type != "annotation":
            continue
        annotation_name = text_of(child.child_by_field_name("name"))
        if annotation_name.startswith("deprecated") or annotation_name.startswith(
            "scala.deprecated"
        ):
            return True

    return False


def deprecated_tag_in_doc(node: Node) -> bool:
    prev_sibling = node.prev_sibling
    if not prev_sibling:
        return False

    # Only block_comment is Javadoc/Scaladoc
    if prev_sibling.type != "block_comment":
        return False

    return "deprecat" in text_of(prev_sibling)


def is_deprecated_java_node(node: None):
    return has_deprecated_java_annotation(node) or deprecated_tag_in_doc(node)


def is_deprecated_scala_node(node: None):
    return has_deprecated_scala_annotation(node) or deprecated_tag_in_doc(node)


def extract_java_type_str(type_node: Node) -> str:
    if type_node.type == "generic_type":
        return type_node.child(0).text.decode(errors="ignore")
    else:
        return type_node.text.decode(errors="ignore")


def extract_java_method_declaration(
    node: Node,
    filepath: str,
    receiver_type_deprecated: bool | None = None,
) -> dict:
    method_parameters = node.child_by_field_name("parameters")
    named_children = []
    if method_parameters:
        named_children = method_parameters.named_children
    parameter_types = []
    for param in named_children:
        if param.type == "formal_parameter":
            type_node = param.child_by_field_name("type")
            if type_node is None:
                continue
            type_str = extract_java_type_str(type_node)
            parameter_types.append(type_str)
        elif param.type == "spread_parameter":
            if param.child(0).type == "modifiers":
                type_node = param.child(1)
            else:
                type_node = param.child(0)
            type_str = extract_java_type_str(type_node)
            parameter_types.append(f"{type_str}...")

    member_deprecated = is_deprecated_java_node(node)

    if receiver_type_deprecated is None:
        receiver_type_deprecated = False
    res = {
        "parameter_types": parameter_types,
        "filepath": filepath,
        "member_deprecated": member_deprecated,
        "receiver_type_deprecated": receiver_type_deprecated,
    }
    return res


def extract_parents_java(node: Node) -> list[str]:
    inherited = []
    superclass_node = node.child_by_field_name("superclass")
    if superclass_node:
        inherited += superclass_node.named_children
    interfaces_node = node.child_by_field_name("interfaces")
    if interfaces_node:
        inherited += interfaces_node.named_child(0).named_children
    if node.type == "interface_declaration":
        for child in node.named_children:
            if child.type != "extends_interfaces":
                continue
            inherited += child.named_child(0).named_children

    res = []
    for type_node in inherited:
        if type_node.type in ["annotated_type", "array_type"]:
            continue
        res.append(extract_java_type_str(type_node))
    return res


def java_ast_dfs(
    node: Node | None,
    api_seqs: list[str],
    source_jar: zipfile.ZipFile,
    filepath: str,
    class_mappings: dict[str, str],
    receiver_type_deprecated: bool | None = None,
) -> list[dict]:
    if node is None:
        return []

    if len(api_seqs) == 0:
        if node.type != "method_declaration":
            return []
        return [
            extract_java_method_declaration(node, filepath, receiver_type_deprecated)
        ]

    if node.type == "method_declaration":
        if len(api_seqs) != 0:
            return []

    res = []
    for child in node.named_children:
        if child.type in [
            "class_declaration",
            "record_declaration",
            "interface_declaration",
            "enum_declaration",
            "method_declaration",
            "annotation_type_declaration",
        ]:
            child_name_node = child.child_by_field_name("name")
            if child_name_node is None:
                continue
            child_name = child_name_node.text.decode(errors="ignore")
            if child_name != api_seqs[0]:
                continue
            if child.type == "method_declaration":
                tmp_res = java_ast_dfs(
                    child,
                    api_seqs[1:],
                    source_jar,
                    filepath,
                    class_mappings,
                    receiver_type_deprecated,
                )
                res.extend(tmp_res)
            else:
                if receiver_type_deprecated is None:
                    receiver_type_deprecated = is_deprecated_java_node(child)
                if child.type == "enum_declaration":
                    body_node = None
                    for body_child in child.child_by_field_name("body").named_children:
                        if body_child.type == "enum_body_declarations":
                            body_node = body_child
                            break
                else:
                    body_node = child.child_by_field_name("body")
                tmp_res = java_ast_dfs(
                    body_node,
                    api_seqs[1:],
                    source_jar,
                    filepath,
                    class_mappings,
                    receiver_type_deprecated,
                )
                res.extend(tmp_res)

                parents = extract_parents_java(child)
                logger.debug(f"{filepath} {parents}")
                for parent in parents:
                    parts = parent.split(".")
                    full_path = class_mappings.get(parts[0])
                    # If the parent is imported
                    if full_path:
                        parent_full_name = ".".join(
                            [full_path] + parts[1:] + api_seqs[1:]
                        )
                    # Else, the parent is in the same folder with the child
                    else:
                        parent_full_name = ".".join(
                            filepath.split("/")[:-1] + parts + api_seqs[1:]
                        )
                    res.extend(
                        extract_api_signatures(
                            source_jar, parent_full_name, receiver_type_deprecated
                        )
                    )
    return res


def traverse_java_file(
    source_jar: zipfile.ZipFile,
    filepath: str,
    rest_parts: list[str],
    receiver_type_deprecated: bool | None = None,
) -> list[dict]:
    # In case that filepath does not exist in source jar
    if filepath not in source_jar.namelist():
        logger.info(f"Java File Not Exists: {filepath}")
        return []

    source = source_jar.read(filepath)
    tree = JAVA_PARSER.parse(source)
    root_node = tree.root_node
    # Record imported class names to its full qualified name for dealing with inheritance
    class_mappings = parse_imports_java(tree)

    return java_ast_dfs(
        root_node,
        rest_parts,
        source_jar,
        filepath,
        class_mappings,
        receiver_type_deprecated,
    )


def _extract_scala_type_str(node: Node) -> str | None:
    if node.type == "annotated_type":
        node = node.named_child(0)
    if node is None:
        return
    if node.type == "generic_type":
        type_node = node.child_by_field_name("type")
        if type_node:
            return type_node.text.decode(errors="ignore")
    else:
        return node.text.decode(errors="ignore")


def extract_scala_type_str(para_type_node: Node) -> str | None:
    if para_type_node.type == "lazy_parameter_type":
        type_node = para_type_node.child_by_field_name("type")
        if type_node:
            return _extract_scala_type_str(type_node)
    elif para_type_node.type == "repeated_parameter_type":
        type_node = para_type_node.child_by_field_name("type")
        if type_node:
            return _extract_scala_type_str(type_node) + "*"
    else:
        return _extract_scala_type_str(para_type_node)


def extract_scala_function_definition(
    node: Node,
    filepath: str,
    receiver_type_deprecated: bool | None = None,
) -> dict:
    function_parameters = None
    for child in node.children_by_field_name("parameters"):
        if child.type == "parameters":
            function_parameters = child
            break
    if function_parameters is None:
        named_children = []
    else:
        named_children = function_parameters.named_children

    parameter_types = []
    for parameter in named_children:
        para_type_node = parameter.child_by_field_name("type")
        if para_type_node is None:
            continue
        type_str = extract_scala_type_str(para_type_node)
        if type_str:
            parameter_types.append(type_str)

    member_deprecated = is_deprecated_scala_node(node)
    if receiver_type_deprecated is None:
        receiver_type_deprecated = False
    res = {
        "parameter_types": parameter_types,
        "filepath": filepath,
        "member_deprecated": member_deprecated,
        "receiver_type_deprecated": receiver_type_deprecated,
    }
    return res


def extract_scala_variable_definition(
    node: Node,
    filepath: str,
    receiver_type_deprecated: bool | None = None,
) -> dict | None:
    type_node = node.child_by_field_name("type")
    if receiver_type_deprecated is None:
        receiver_type_deprecated = False
    if type_node:
        if type_node.type != "function_type":
            return

        parameter_types_node = type_node.child_by_field_name("parameter_types")
        if parameter_types_node is None:
            return
        parameter_types = []
        for parameter_type in parameter_types_node.named_children:
            type_str = extract_scala_type_str(parameter_type)
            if type_str:
                parameter_types.append(type_str)

        member_deprecated = is_deprecated_scala_node(node)
        res = {
            "parameter_types": parameter_types,
            "filepath": filepath,
            "member_deprecated": member_deprecated,
            "receiver_type_deprecated": receiver_type_deprecated,
        }
        return res

    value_node = node.child_by_field_name("value")
    if value_node:
        if value_node.type != "lambda_expression":
            return
        parameters_node = value_node.child_by_field_name("parameters")
        if parameters_node is None:
            return
        if parameters_node.type != "bindings":
            return
        parameter_types = []
        for binding_node in parameters_node.named_children:
            type_node = binding_node.child_by_field_name("type")
            if type_node is None:
                continue
            type_str = extract_scala_type_str(type_node)
            if type_str:
                parameter_types.append(type_str)

        member_deprecated = is_deprecated_scala_node(node)
        res = {
            "parameter_types": parameter_types,
            "filepath": filepath,
            "member_deprecated": member_deprecated,
            "receiver_type_deprecated": receiver_type_deprecated,
        }
        return res


scala_import_query = SCALA_LANGUAGE.query(
    """
(import_declaration) @import
"""
)


def parse_imports_scala(tree):
    class_mappings = {}
    for match in scala_import_query.matches(tree.root_node):
        node = match[1]["import"][0]
        named_children = node.named_children
        if named_children[-1].type == "namespace_wildcard":
            continue
        ids = [child.text.decode(errors="ignore") for child in named_children[:-1]]
        if named_children[-1].type == "namespace_selectors":
            for child in named_children[-1].named_children:
                if child.type == "identifier":
                    name = child.text.decode(errors="ignore")
                    ids.append(name)
                    class_mappings[name] = ".".join(ids)
                elif child.type in [
                    "arrow_renamed_identifier",
                    "as_renamed_identifier",
                ]:
                    name_node = child.child_by_field_name("name")
                    if name_node is None:
                        continue
                    name = name_node.text.decode(errors="ignore")
                    ids.append(name)
                    alias = child.child_by_field_name("alias")
                    if alias is None:
                        continue
                    if alias.type == "wildcard":
                        continue
                    alias = alias.text.decode(errors="ignore")
                    class_mappings[alias] = ".".join(ids)
        elif named_children[-1].type == "as_renamed_identifier":
            name_node = named_children[-1].child_by_field_name("name")
            if name_node is None:
                continue
            name = name_node.text.decode(errors="ignore")
            ids.append(name)
            alias = named_children[-1].child_by_field_name("alias")
            if alias is None:
                continue
            if alias.type == "wildcard":
                continue
            alias = alias.text.decode(errors="ignore")
            class_mappings[alias] = ".".join(ids)
        else:
            name = named_children[-1].text.decode(errors="ignore")
            ids.append(name)
            class_mappings[name] = ".".join(ids)

    return class_mappings


def extract_parents_scala(node) -> list[str]:
    extends_clause_node = node.child_by_field_name("extend")
    if extends_clause_node is None:
        return []

    inherited = []
    for type_node in extends_clause_node.children_by_field_name("type"):
        if not type_node.is_named:
            continue
        type_str = _extract_scala_type_str(type_node)
        if type_str:
            inherited.append(type_str)
    return inherited


def scala_ast_dfs(
    node: Node | None,
    api_seqs: list[str],
    source_jar: zipfile.ZipFile,
    filepath: str,
    class_mappings: dict[str, str],
    receiver_type_deprecated: bool | None = None,
) -> list[dict]:
    if node is None:
        return []

    if len(api_seqs) == 0:
        if node.type not in [
            "function_definition",
            "function_declaration",
            "val_definition",
            "var_definition",
        ]:
            return []
        if node.type.startswith("function"):
            return [
                extract_scala_function_definition(
                    node, filepath, receiver_type_deprecated
                )
            ]
        else:
            tmp = extract_scala_variable_definition(
                node, filepath, receiver_type_deprecated
            )
            if tmp:
                return [tmp]
            return []

    if node.type in [
        "function_definition",
        "function_declaration",
        "val_definition",
        "var_definition",
    ]:
        if len(api_seqs) != 0:
            return []

    res = []
    for child in node.named_children:
        if child.type in [
            "class_definition",
            "enum_definition",
            "object_definition",
            "trait_definition",
            "function_definition",
            "function_declaration",
        ]:
            child_name_node = child.child_by_field_name("name")
            if child_name_node is None:
                continue
            child_name = child_name_node.text.decode(errors="ignore")
            if child_name != api_seqs[0]:
                continue
            if child.type.startswith("function"):
                tmp_res = scala_ast_dfs(
                    child,
                    api_seqs[1:],
                    source_jar,
                    filepath,
                    class_mappings,
                    receiver_type_deprecated,
                )
                res.extend(tmp_res)
            else:
                if receiver_type_deprecated is None:
                    receiver_type_deprecated = is_deprecated_scala_node(child)
                tmp_res = scala_ast_dfs(
                    child.child_by_field_name("body"),
                    api_seqs[1:],
                    source_jar,
                    filepath,
                    class_mappings,
                    receiver_type_deprecated,
                )
                res.extend(tmp_res)
                parents = extract_parents_scala(child)
                logger.debug(f"{filepath} {parents}")
                for parent in parents:
                    parts = parent.split(".")
                    full_path = class_mappings.get(parts[0])
                    # If the parent is imported
                    if full_path:
                        parent_full_name = ".".join(
                            [full_path] + parts[1:] + api_seqs[1:]
                        )
                    # Else, the parent is in the same folder with the child
                    else:
                        parent_full_name = ".".join(
                            filepath.split("/")[:-1] + parts + api_seqs[1:]
                        )
                    # This asks whether the API is declared in the parent.
                    # It should use the parent's own deprecation metadata,
                    # not the child's lexical deprecation state.
                    res.extend(
                        extract_api_signatures(
                            source_jar, parent_full_name, receiver_type_deprecated
                        )
                    )

        elif child.type in ["var_definition", "val_definition"]:
            child_name_node = child.child_by_field_name("pattern")
            if child_name_node is None:
                continue
            child_name = child_name_node.text.decode(errors="ignore")
            if child_name != api_seqs[0]:
                continue
            res.extend(
                scala_ast_dfs(
                    child,
                    api_seqs[1:],
                    source_jar,
                    filepath,
                    class_mappings,
                    receiver_type_deprecated,
                )
            )
    return res


def traverse_scala_file(
    source_jar: zipfile.ZipFile,
    filepath: str,
    rest_parts: list[str],
    receiver_type_deprecated: bool | None = None,
) -> list[dict]:
    # In case that filepath does not exist in source jar
    if filepath not in source_jar.namelist():
        logger.error(f"Java File Not Exists: {filepath}")
        return []

    source = source_jar.read(filepath)
    tree = SCALA_PARSER.parse(source)
    root_node = tree.root_node
    # Record imported class names to its full qualified name for dealing with inheritance
    class_mappings = parse_imports_scala(tree)

    return scala_ast_dfs(
        root_node,
        rest_parts,
        source_jar,
        filepath,
        class_mappings,
        receiver_type_deprecated,
    )


def split_api_name(api_name: str, file_tree: dict) -> dict:
    parts = api_name.split(".")
    folder = ""
    for i, p in enumerate(parts):
        cur_folder = os.path.join(folder, p)
        if cur_folder not in file_tree:
            break
        folder = cur_folder
    file_name, rest_parts = parts[i], parts[i:]
    files = file_tree.get(folder, [[], []])[1]
    candidate_files = []
    for f in files:
        if not f.startswith(f"{file_name}."):
            continue
        candidate_files.append(f)
    return {
        "folder": folder,
        "candidate_files": candidate_files,
        "rest_parts": rest_parts,
    }


def extract_api_signatures(
    source_jar: zipfile.ZipFile,
    api_name: str,
    receiver_type_deprecated: bool | None = None,
) -> list[dict]:
    """Extract the signature with deprecation information within a sources jar."""
    # 1. Locate the code file that the api_name reside in source jar
    # Return: folder, Code file path, remaining apis
    file_tree = construct_file_tree(source_jar.namelist())
    api_parts = split_api_name(api_name, file_tree)
    if not api_parts["candidate_files"]:
        logger.info(f"Code File Not Found: {api_name}")
        return []

    # 2. Locate api declaration in the file
    folder = api_parts["folder"]
    candidate_files = api_parts["candidate_files"]
    rest_parts = api_parts["rest_parts"]
    class_name = rest_parts[0]

    # Deal with Java file
    if f"{class_name}.java" in candidate_files:
        filepath = os.path.join(folder, f"{class_name}.java")
        apis = traverse_java_file(
            source_jar, filepath, rest_parts, receiver_type_deprecated
        )
        if not apis:
            logger.info(f"Java APIs Not Found: {api_name}")
        return apis

    # Deal with Scala file
    elif f"{class_name}.scala" in candidate_files:
        filepath = os.path.join(folder, f"{class_name}.scala")
        apis = traverse_scala_file(
            source_jar, filepath, rest_parts, receiver_type_deprecated
        )
        if not apis:
            logger.info(f"Scala APIs Not Found: {api_name}")
        return apis
    else:
        logger.info(f"Unsupported languages: {','.join(candidate_files)}")

    return []


def match_by_arg_count(apis: list[dict], num_args: int):
    res = []
    for api in apis:
        var_symbol = "@@@@@@@"
        if api["filepath"].endswith(".java"):
            var_symbol = "..."
        elif api["filepath"].endswith(".scala"):
            var_symbol = "*"

        para_types = api["parameter_types"]
        # param_types = []
        if len(para_types) == 0:
            # arg_types != [], mismatch
            if num_args > 0:
                continue
            # arg_types == [], match
            res.append(api | {"count_match": 1})

        # Spread paramter case, num_args can be num_paras-1, num_paras, ...
        elif para_types[-1].endswith(var_symbol):
            if num_args < (len(para_types) - 1):
                continue
            # we assign a lower count_match value
            res.append(api | {"count_match": 0.5})
        # In other cases, num_args should be equal to num_paras
        else:
            if num_args == len(para_types):
                res.append(api | {"count_match": 1})

    return res


def check_existence(
    library: str, version: str, dest_folder: str, api_name: str, num_args: int
) -> list[dict]:
    _, sources_jar_path = gen_sources_jar_path(library, version, dest_folder)
    dedup_apis = []
    if not os.path.exists(sources_jar_path):
        return dedup_apis
    with zipfile.ZipFile(sources_jar_path) as sources_jar:
        candidate_apis = extract_api_signatures(sources_jar, api_name)
        count_matching_apis = match_by_arg_count(candidate_apis, num_args)

        existing_para_types = []
        for api in count_matching_apis:
            if api["parameter_types"] in existing_para_types:
                continue
            dedup_apis.append(api)
            existing_para_types.append(api["parameter_types"])
    return dedup_apis


def validate(
    library: str,
    old_version: str,
    new_version: str,
    dest_folder: str,
    old_api_fqn: str,
    old_arg_count: int,
    new_api_fqn: str,
    new_arg_count: str,
):
    # 1. Existence check
    old_api_sigs = check_existence(
        library, old_version, dest_folder, old_api_fqn, old_arg_count
    )
    if not old_api_sigs:
        return False
    new_api_sigs = check_existence(
        library, new_version, dest_folder, new_api_fqn, new_arg_count
    )
    if not new_api_sigs:
        return False

    # 2. Removal/deprecation check
    old_api_sigs_in_new = check_existence(
        library, new_version, dest_folder, old_api_fqn, old_arg_count
    )
    # Removed in new version
    if not old_api_sigs_in_new:
        return True
    # Still exists, but deprecated in new version
    return any(
        sig.get("member_deprecated", False)
        or sig.get("receiver_type_deprecated", False)
        for sig in old_api_sigs_in_new
    )
