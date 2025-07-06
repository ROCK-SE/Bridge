import argparse
import logging
import os
import random
import sys
import time
import zipfile
from urllib.error import HTTPError
from urllib.request import urlretrieve

import pandas as pd
import tree_sitter_java as tsjava
import tree_sitter_scala as tsscala
from build_import_mappings import construct_file_tree
from joblib import Parallel, delayed
from parse_api_calls import parse_imports_java
from pymongo import MongoClient
from tqdm.auto import tqdm
from tree_sitter import Language, Node, Parser
from utils import cal_sample_size, insert_many_skip_large

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
debug_fh = logging.FileHandler("../log/java_api_update_validator.debug", mode="w")
debug_fh.setLevel(logging.DEBUG)
info_fh = logging.FileHandler("../log/java_api_update_validator.info", mode="w")
info_fh.setLevel(logging.INFO)
# create formatter and add it to the handlers
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(lineno)d %(message)s")
debug_fh.setFormatter(formatter)
info_fh.setFormatter(formatter)
# add the handlers to logger
logger.addHandler(debug_fh)
logger.addHandler(info_fh)

client = MongoClient("127.0.0.1", 27017)
db = client["api_update"]
col = db["java_candidate_api_update_instances"]

JAVA_LANGUAGE = Language(tsjava.language())
SCALA_LANGUAGE = Language(tsscala.language())
JAVA_PARSER = Parser(JAVA_LANGUAGE)
SCALA_PARSER = Parser(SCALA_LANGUAGE)


def gen_sources_jar_path(package: str, version: str, dest_folder: str):
    group_id, artifact_id = package.split(":")
    group_path = "/".join(group_id.split("."))
    jar_name = f"{artifact_id}-{version}-sources.jar"
    url = (
        f"https://repo1.maven.org/maven2/{group_path}"
        + f"/{artifact_id}/{version}/{jar_name}"
    )
    save_path = os.path.join(dest_folder, "java", group_path, jar_name)
    return url, save_path


def download_sources_jar(row, dest_folder: str):
    package = row["package"]
    version = row["version"]
    url, save_path = gen_sources_jar_path(package, version, dest_folder)
    if os.path.exists(save_path):
        logger.info(f"Sources Jar Already Downloaded: {package} {version}")
        try:
            zipfile.ZipFile(save_path)
            return
        except:
            logger.error(f"Bad Sources Jar: {package} {version}")
            pass
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    try:
        urlretrieve(url, save_path)
        logger.info(f"Successfully download jar for {package} {version}")
    except HTTPError as e:
        if e.code == 404:
            logger.error(f"Jar does not exist: {package} {version}")
        else:
            logger.error(f"Other HTTPError: {package} {version}")
    except Exception as e:
        logger.error(f"Downloading Error for {package} {version}: {e}")

    time.sleep(random.random() * 3)


def download_java_packages(dest_folder: str, n_jobs: int = 1):
    data = pd.DataFrame(
        col.find(
            {},
            projection={
                "_id": 0,
                "package": 1,
                "version_before": 1,
                "version_after": 1,
            },
        )
    )
    package_releases = pd.concat(
        [
            data[["package", "version_before"]].rename(
                columns={"version_before": "version"}
            ),
            data[["package", "version_after"]].rename(
                columns={"version_after": "version"}
            ),
        ],
        ignore_index=True,
    )
    package_releases.drop_duplicates(inplace=True)
    package_releases = package_releases.to_dict("records")
    print(f"{len(package_releases)} unique Maven library verisons")

    Parallel(n_jobs=n_jobs, backend="multiprocessing")(
        delayed(download_sources_jar)(row, dest_folder)
        for row in tqdm(package_releases, file=sys.stdout)
    )


def extract_java_type_str(type_node: Node) -> str:
    if type_node.type == "generic_type":
        return type_node.child(0).text.decode(errors="ignore")
    else:
        return type_node.text.decode(errors="ignore")


def extract_java_method_declaration(node: Node, filepath: str) -> dict:
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

    method_body = node.child_by_field_name("body")
    if method_body is None:
        body = ""
    else:
        body = method_body.text.decode(errors="ignore")
    res = {"parameter_types": parameter_types, "body": body, "filepath": filepath}
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
) -> list[dict]:
    if node is None:
        return []

    if len(api_seqs) == 0:
        if node.type != "method_declaration":
            return []
        return [extract_java_method_declaration(node, filepath)]

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
                    child, api_seqs[1:], source_jar, filepath, class_mappings
                )
                res.extend(tmp_res)
            else:
                tmp_res = java_ast_dfs(
                    child.child_by_field_name("body"),
                    api_seqs[1:],
                    source_jar,
                    filepath,
                    class_mappings,
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
                    res.extend(extract_apis(source_jar, parent_full_name))
    return res


def traverse_java_file(
    source_jar: zipfile.ZipFile, filepath: str, rest_parts: list[str]
) -> list[dict]:
    # In case that filepath does not exist in source jar
    if filepath not in source_jar.namelist():
        logger.error(f"Java File Not Exists: {filepath}")
        return []

    source = source_jar.read(filepath)
    tree = JAVA_PARSER.parse(source)
    root_node = tree.root_node
    # Record imported class names to its full qualified name for dealing with inheritance
    class_mappings = parse_imports_java(tree)

    return java_ast_dfs(root_node, rest_parts, source_jar, filepath, class_mappings)


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


def extract_scala_function_definition(node: Node, filepath: str) -> dict:
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

    # Although Scala allow default parameters, since default parameters in Scala
    # are not optional when called from Java code, we do not consider them.
    function_body = node.child_by_field_name("body")
    if function_body is None:
        body = ""
    else:
        body = function_body.text.decode(errors="ignore")

    res = {"parameter_types": parameter_types, "body": body, "filepath": filepath}
    return res


def extract_scala_variable_definition(node: Node, filepath: str) -> dict | None:
    type_node = node.child_by_field_name("type")
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
        val_body = node.child_by_field_name("value")
        if val_body:
            body = val_body.text.decode(errors="ignore")
        else:
            body = ""
        res = {"parameter_types": parameter_types, "body": body, "filepath": filepath}
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
        val_body = value_node.named_children[-1]
        if val_body:
            body = val_body.text.decode(errors="ignore")
        else:
            body = ""
        res = {"parameter_types": parameter_types, "body": body, "filepath": filepath}
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
) -> list[dict]:
    if node is None:
        return []

    if len(api_seqs) == 0:
        if not node.type in [
            "function_definition",
            "function_declaration",
            "val_definition",
            "var_definition",
        ]:
            return []
        if node.type.startswith("function"):
            return [extract_scala_function_definition(node, filepath)]
        else:
            tmp = extract_scala_variable_definition(node, filepath)
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
                    child, api_seqs[1:], source_jar, filepath, class_mappings
                )
                res.extend(tmp_res)
            else:
                tmp_res = scala_ast_dfs(
                    child.child_by_field_name("body"),
                    api_seqs[1:],
                    source_jar,
                    filepath,
                    class_mappings,
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
                    res.extend(extract_apis(source_jar, parent_full_name))

        elif child.type in ["var_definition", "val_definition"]:
            child_name_node = child.child_by_field_name("pattern")
            if child_name_node is None:
                continue
            child_name = child_name_node.text.decode(errors="ignore")
            if child_name != api_seqs[0]:
                continue
            res.extend(
                scala_ast_dfs(child, api_seqs[1:], source_jar, filepath, class_mappings)
            )
    return res


def traverse_scala_file(
    source_jar: zipfile.ZipFile, filepath: str, rest_parts: list[str]
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

    return scala_ast_dfs(root_node, rest_parts, source_jar, filepath, class_mappings)


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


def extract_apis(
    source_jar: zipfile.ZipFile,
    api_name: str,
) -> list[dict]:
    # 1. Locate the code file that the api_name reside in source jar: locate_code_file(api_name, source_jar)
    # Return: folder, Code file path, remaining apis
    file_tree = construct_file_tree(source_jar.namelist())
    api_parts = split_api_name(api_name, file_tree)
    if not api_parts["candidate_files"]:
        logger.error(f"Code File Not Found: {api_name}")
        return []

    # 2. Locate api declaration in the file
    folder = api_parts["folder"]
    candidate_files = api_parts["candidate_files"]
    rest_parts = api_parts["rest_parts"]
    class_name = rest_parts[0]
    # Deal with Java file
    if f"{class_name}.java" in candidate_files:
        filepath = os.path.join(folder, f"{class_name}.java")
        apis = traverse_java_file(source_jar, filepath, rest_parts)
        if not apis:
            logger.error(f"Java API Not Found: {api_name}")
        return apis
    # Deal with Scala file
    elif f"{class_name}.scala" in candidate_files:
        filepath = os.path.join(folder, f"{class_name}.scala")
        apis = traverse_scala_file(source_jar, filepath, rest_parts)
        if not apis:
            logger.error(f"Scala API Not Found: {api_name}")
        return apis
    else:
        logger.error(f"Unsupported languages: {','.join(candidate_files)}")

    return []


def arg_num_match(api: dict, num_args: int) -> bool:
    para_types = api["parameter_types"]
    filepath = api["filepath"]
    var_symbol = "@"
    if filepath.endswith(".java"):
        var_symbol = "..."
    elif filepath.endswith(".scala"):
        var_symbol = "*"
    num_paras = len(para_types)

    # param_types = []
    if num_paras == 0:
        # arg_types != [], mismatch
        if num_args != 0:
            return False
        # arg_types == [], match
        return True

    # In the spread parameter case, num_args can be num_paras-1, num_paras, ...
    # In other cases, num_args = num_paras
    # Therefore, num_args should be greater or equal to num_args - 1
    if para_types[-1].endswith(var_symbol):
        if num_args >= (num_paras - 1):
            return True
        return False

    return num_paras == num_args


def extract_method_body_per_doc(doc: dict, dest_folder: str) -> dict | None:
    package = doc["package"]
    version_before = doc["version_before"]
    version_after = doc["version_after"]
    _, old_sources_jar_path = gen_sources_jar_path(package, version_before, dest_folder)
    _, new_sources_jar_path = gen_sources_jar_path(package, version_after, dest_folder)
    if not os.path.exists(old_sources_jar_path):
        logger.error(f"Sources Jar Not Found: {package} {version_before}")
        return
    if not os.path.exists(new_sources_jar_path):
        logger.error(f"Sources Jar Not Found: {package} {version_after}")
        return

    with zipfile.ZipFile(old_sources_jar_path) as old_sources_jar, zipfile.ZipFile(
        new_sources_jar_path
    ) as new_sources_jar:
        update_pairs_with_method_body = []
        for pair in doc["api_update_pairs"]:
            old_callee = pair["old_callee"]
            old_api_name = old_callee["full_name"]
            num_old_args = len(old_callee["arguments"])
            logger.info(f"Checking {package} {version_before} {old_api_name} ...")
            try:
                old_apis = extract_apis(old_sources_jar, old_api_name)
            except:
                logger.error(
                    f"RecursionError: {package} {version_before} {old_api_name}"
                )
                continue
            old_matches_api = None
            for api in old_apis:
                if arg_num_match(api, num_old_args):
                    old_matches_api = api
                    break
            if old_matches_api is None:
                logger.error(f"Parameter Not Match: {old_api_name}")
                continue

            new_callee = pair["new_callee"]
            new_api_name = new_callee["full_name"]
            num_new_args = len(new_callee["arguments"])
            logger.info(f"Checking {package} {version_after} {new_api_name} ...")
            try:
                new_apis = extract_apis(new_sources_jar, new_api_name)
            except:
                logger.error(
                    f"RecursionError: {package} {version_after} {new_api_name}"
                )
                continue
            new_matches_api = None
            for api in new_apis:
                if arg_num_match(api, num_new_args):
                    new_matches_api = api
                    break
            if new_matches_api is None:
                logger.error(f"Parameter Not Match: {new_api_name}")
                continue

            update_pairs_with_method_body.append(
                {
                    "caller": pair["caller"],
                    "old_callee": old_callee | old_matches_api,
                    "new_callee": new_callee | new_matches_api,
                    "similarity_score": pair["similarity_score"],
                }
            )
        if update_pairs_with_method_body:
            return doc | {
                "api_update_pairs": update_pairs_with_method_body,
            }


def extract(dest_folder: str, n_jobs: int = 1, batch_size: int = 100):
    docs = list(col.find({}, projection={"_id": 0}))
    print(len(docs), "docs to be processed")
    res = Parallel(n_jobs=n_jobs, backend="multiprocessing")(
        delayed(extract_method_body_per_doc)(doc, dest_folder)
        for doc in tqdm(docs, file=sys.stdout)
    )
    res = [r for r in res if r]
    print(f"{len(res)} docs survived after checking")
    save_col_name = "java_existent_api_update_instances"
    db.drop_collection(save_col_name)
    save_col = db[save_col_name]
    insert_many_skip_large(save_col, res)
    save_col.create_index("commit")
    save_col.create_index("package")


def sample_api_pairs_by_occurences():
    col = db["java_existent_api_update_instances"]
    api_update_instances = []
    for doc in tqdm(col.find({}), total=col.estimated_document_count()):
        commit = doc["commit"]
        filepath = doc["filepath"]
        old_blob = doc["old_blob"]
        new_blob = doc["new_blob"]
        package = doc["package"]
        version_before = doc["version_before"]
        version_after = doc["version_after"]
        for pair in doc["api_update_pairs"]:
            old_callee = pair["old_callee"]
            old_full_name = old_callee["full_name"]
            old_parameter_types = f"({', '.join(old_callee['parameter_types'])})"
            old_api = old_full_name + old_parameter_types
            old_body = old_callee["body"]

            new_callee = pair["new_callee"]
            new_full_name = new_callee["full_name"]
            new_parameter_types = f"({', '.join(new_callee['parameter_types'])})"
            new_api = new_full_name + new_parameter_types
            new_body = new_callee["body"]
            api_update_instances.append(
                [
                    commit,
                    filepath,
                    old_blob,
                    new_blob,
                    package,
                    version_before,
                    version_after,
                    old_api,
                    new_api,
                    old_body,
                    new_body,
                ]
            )
    api_update_instances = pd.DataFrame(
        api_update_instances,
        columns=[
            "commit",
            "filepath",
            "old_blob",
            "new_blob",
            "package",
            "version_before",
            "version_after",
            "old_api",
            "new_api",
            "old_body",
            "new_body",
        ],
    )
    print(f"{len(api_update_instances)} API update instances")
    api_update_pairs = (
        api_update_instances[["old_api", "new_api"]]
        .value_counts()
        .to_frame()
        .reset_index()
    )
    api_update_pairs.to_csv("../benchmark/final/java_api_update_pairs.csv", index=False)
    print(f"{len(api_update_pairs)} API update pairs, the most frequently pairs are:")
    print(api_update_pairs.head())

    sample_size = cal_sample_size(len(api_update_pairs))
    samples = api_update_pairs.sample(
        sample_size, weights=api_update_pairs["count"], random_state=42
    )
    samples = samples.merge(api_update_instances).drop_duplicates(
        ["old_api", "new_api"], keep="first"
    )
    samples.to_csv("../benchmark/final/sampled_java_api_update_pairs.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python java_api_update_validator.py",
        description="Validate candidate Java library API update instances",
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")
    parser.add_argument(
        "-d", "--download", action="store_true", help="download sources jars"
    )
    parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="check whether apis in each update instance exist in corresponding package release",
    )
    parser.add_argument(
        "--dest_folder",
        required=True,
        type=str,
        help="the folder to store downloaded sources jars",
    )
    parser.add_argument(
        "-s",
        "--sample",
        action="store_true",
        help="sample API update pairs",
    )

    args = parser.parse_args()

    if args.download:
        download_java_packages(args.dest_folder, args.n_jobs)

    if args.check:
        extract(args.dest_folder, args.n_jobs)

    if args.sample:
        sample_api_pairs_by_occurences()
