import json
import os
from argparse import ArgumentParser

import pandas as pd
from joblib import Parallel, delayed
from pymongo import MongoClient
from tqdm import tqdm

java_imports = json.load(open("../benchmark/updates/java_imports.json"))

import tree_sitter_java as tsjava
from parse_api_calls import read_raw_blob
from tree_sitter import Language, Node, Parser

JAVA_LANGUAGE = Language(tsjava.language())
JAVA_PARSER = Parser(JAVA_LANGUAGE)


method_query = JAVA_LANGUAGE.query(
    """
[
    (method_declaration)
    (constructor_declaration)
]@declaration
"""
)

java_import_query = JAVA_LANGUAGE.query(
    """
(import_declaration
    (identifier) @import_name .)@import_declaration
(import_declaration
    (scoped_identifier) @import_name .)@import_declaration
"""
)


def select_blob_index():
    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    col = db["java_existent_api_update_instances"]
    blob_index = {}
    with open("../benchmark/updates/javablob.idx") as f:
        for line in tqdm(f):
            blob_sha, offset, length = line.strip("\n").split(";")
            idx = int(blob_sha[:2], base=16) % 128
            blob_index[blob_sha] = (idx, int(offset), int(length))
    blobs = list()
    for doc in col.find({}):
        blobs.append(doc["old_blob"])
        blobs.append(doc["new_blob"])
    blobs = list(set(blobs))
    related_blobs_index = {b: blob_index[b] for b in blobs}
    with open("../benchmark/final/java_blob_index.json", "w") as outf:
        json.dump(related_blobs_index, outf)


if not os.path.exists("../benchmark/final/java_blob_index.json"):
    select_blob_index()

blob_index = json.load(open("../benchmark/final/java_blob_index.json"))
print(f"{len(blob_index)} unique blobs")


def extract_spaces(line: str):
    res = ""
    for c in line:
        if not c.isspace():
            break
        res += c
    return res


def method_caller(caller: list[str]) -> bool:
    if len(caller) == 0:
        return False

    # the last caller must be a method
    if not caller[-1].endswith(")"):
        return False

    # Outer callers must be either class, enum, record, interface, or annotation_type
    if any(["@" not in c for c in caller[:-1]]):
        return False
    return True


def parse_imports_java(root_node: Node):
    class_mappings = {}
    for match in java_import_query.matches(root_node):
        import_declaration = match[1]["import_declaration"][0].text.decode(
            errors="ignore"
        )
        import_name = match[1]["import_name"][0].text.decode(errors="ignore")
        name = import_name.split(".")[-1]
        if name == "*":
            continue
        class_mappings[import_name] = import_declaration
    return class_mappings


def extract_code(
    source: str, root_node: Node, package: str, caller: list[str]
) -> str | None:
    if not method_caller(caller):
        return

    source_lines = source.splitlines()

    imports = java_imports[package]
    related_imports = [
        v
        for k, v in parse_imports_java(root_node).items()
        if any(k.startswith(f"{imp}.") for imp in imports)
    ]
    cur_node = root_node
    i = 0
    res = []
    end_brackets = []
    while cur_node and (i < len(caller)):
        ctx = caller[i]
        if "@" in ctx:
            context_type, context_name = ctx.split("@", 1)
            if context_type not in [
                "class",
                "reocrd",
                "enum",
                "interface",
                "annotation_type",
            ]:
                return
            query = JAVA_LANGUAGE.query(f"({context_type}_declaration)@declaration")
            found = False
            for match in query.matches(cur_node):
                match_node = match[1]["declaration"][0]
                node_name = match_node.child_by_field_name("name").text.decode(
                    errors="ignore"
                )
                if node_name == context_name:
                    cur_node = match_node
                    found = True
                    start_line = match_node.start_point[0]
                    leading_spaces = extract_spaces(source_lines[start_line])
                    res.append(
                        leading_spaces
                        + match_node.text.decode(errors="ignore").split("{", 1)[0]
                        + "{"
                    )
                    end_brackets.insert(0, leading_spaces + "}")
                    i += 1
                    break
            if not found:
                return

        elif ctx.endswith(")"):
            found = False
            for match in method_query.matches(cur_node):
                match_node = match[1]["declaration"][0]
                node_name = match_node.child_by_field_name("name").text.decode(
                    errors="ignore"
                )
                context_name, context_parameter_types = ctx.split("(", 1)
                context_parameter_types = context_parameter_types.strip(")")
                if node_name != context_name:
                    continue
                method_parameters = match_node.child_by_field_name("parameters")
                parameter_types = []
                for param in method_parameters.named_children:
                    if param.type == "formal_parameter":
                        t = param.child_by_field_name("type").text.decode(
                            errors="ignore"
                        )
                        parameter_types.append(t)
                if ", ".join(parameter_types) == context_parameter_types:
                    found = True
                    cur_node = match_node
                    start_line = match_node.start_point[0]
                    end_line = match_node.end_point[0]
                    res.append("\n".join(source_lines[start_line:end_line]))
                    i += 1
                    break
            if not found:
                return
        else:
            query = JAVA_LANGUAGE.query(
                f"(compact_constructor_declaration)@declaration"
            )
            found = False
            for match in query.matches(cur_node):
                match_node = match[1]["declaration"][0]
                node_name = match_node.child_by_field_name("name").text.decode(
                    errors="ignore"
                )
                if node_name == ctx:
                    found = True
                    cur_node = match_node
                    start_line = match_node.start_point[0]
                    end_line = match_node.end_point[0]
                    res.append("\n".join(source_lines[start_line:end_line]))
                    i += 1
                    break
            if not found:
                return

    return "\n".join(related_imports + res + end_brackets)


def extract_code_commit_pair(row):
    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    col = db["java_existent_api_update_instances"]

    package = row["package"]
    old_api_full_name = row["old_api_full_name"]
    old_params = row["old_params"]
    new_api_full_name = row["new_api_full_name"]
    new_params = row["new_params"]
    old_version = row["old_version"]
    new_version = row["new_version"]
    commit = row["commit"]
    res = []
    for doc in col.find({"commit": commit, "package": package}, projection={"_id": 0}):
        version_before = doc["version_before"]
        version_after = doc["version_after"]
        old_blob = doc["old_blob"]
        old_source = read_raw_blob(*blob_index[old_blob])
        old_root_node = JAVA_PARSER.parse(old_source).root_node
        new_blob = doc["new_blob"]
        new_source = read_raw_blob(*blob_index[new_blob])
        new_root_node = JAVA_PARSER.parse(new_source).root_node
        visited_caller = []
        for pair in doc["api_update_pairs"]:
            caller = pair["caller"]
            if caller in visited_caller:
                continue
            visited_caller.append(caller)
            old_callee = pair["old_callee"]
            old_callee_full_name = old_callee["full_name"]
            if old_callee["parameter_types"] == "":
                old_callee_params = ""
            else:
                old_callee_params = f"({', '.join(old_callee['parameter_types'])})"
            new_callee = pair["new_callee"]
            new_callee_full_name = new_callee["full_name"]
            if new_callee["parameter_types"] == "":
                new_callee_params = ""
            else:
                new_callee_params = f"({', '.join(new_callee['parameter_types'])})"
            if (version_before == old_version) and (version_after == new_version):
                if (
                    (old_callee_full_name == old_api_full_name)
                    and (old_callee_params == old_params)
                    and (new_callee_full_name == new_api_full_name)
                    and (new_callee_params == new_params)
                ):
                    old_code = extract_code(
                        old_source.decode(errors="ignore"),
                        old_root_node,
                        package,
                        caller,
                    )
                    if old_code is None:
                        continue
                    new_code = extract_code(
                        new_source.decode(errors="ignore"),
                        new_root_node,
                        package,
                        caller,
                    )
                    if new_code is None:
                        continue
                    res.append(row | {"old_code": old_code, "new_code": new_code})

            if (version_before == new_version) and (version_after == old_version):
                if (
                    (old_callee_full_name == new_api_full_name)
                    and (old_callee_params == new_params)
                    and (new_callee_full_name == old_api_full_name)
                    and (new_callee_params == old_params)
                ):
                    old_code = extract_code(
                        old_source.decode(errors="ignore"),
                        old_root_node,
                        package,
                        caller,
                    )
                    if old_code is None:
                        continue
                    new_code = extract_code(
                        new_source.decode(errors="ignore"),
                        new_root_node,
                        package,
                        caller,
                    )
                    if new_code is None:
                        continue
                    res.append(row | {"old_code": new_code, "new_code": old_code})
    return res


def extract_main(n_jobs: int = 1):
    commit_pairs_full = json.load(
        open("../benchmark/final/java_commit_pairs_full.json")
    )
    print(len(commit_pairs_full), "commit pairs for full rules")

    res = Parallel(n_jobs=n_jobs, backend="multiprocessing")(
        delayed(extract_code_commit_pair)(row) for row in tqdm(commit_pairs_full)
    )
    final = []
    for r in res:
        final.extend(r)
    with open("../benchmark/final/java_update_instances_full.json", "w") as outf:
        json.dump(final, outf)

    instances_full = pd.read_json("../benchmark/final/java_update_instances_full.json")
    print(f"{len(instances_full)} update instances for full rules")
    commit_pairs_exact = pd.read_json("../benchmark/final/java_commit_pairs_exact.json")
    print(f"{len(commit_pairs_exact)} commit pairs for correct verified rules")
    instances_exact = commit_pairs_exact.merge(instances_full)
    print(f"{len(instances_exact)} update instances for correct verified rules")
    instances_exact.to_json(
        "../benchmark/final/java_update_instances_exact.json", orient="records"
    )


if __name__ == "__main__":
    parser = ArgumentParser(
        prog="python extract_java_code.py",
        description="Extract methods for update pairs",
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")

    args = parser.parse_args()
    extract_main(args.n_jobs)
