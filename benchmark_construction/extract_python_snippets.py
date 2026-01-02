import json
import os
from argparse import ArgumentParser

import pandas as pd
import tree_sitter_python as tspython
from joblib import Parallel, delayed
from benchmark_construction.phase2_api_call_analysis.parse_api_calls import (
    parse_api_calls_python,
    read_raw_blob,
)
from pymongo import MongoClient
from tqdm import tqdm
from tree_sitter import Language, Node, Parser

PY_LANGUAGE = Language(tspython.language())
PY_PARSER = Parser(PY_LANGUAGE)

py_imports = json.load(open("../benchmark/updates/py_imports.json"))


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


def select_blob_index():
    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    col = db["py_candidate_api_update_instances"]
    blob_index = {}
    with open("../benchmark/updates/pyblob.idx") as f:
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
    with open("../benchmark/final/py_blob_index.json", "w") as outf:
        json.dump(related_blobs_index, outf, indent=2)


if not os.path.exists("../benchmark/final/py_blob_index.json"):
    select_blob_index()

blob_index = json.load(open("../benchmark/final/py_blob_index.json"))
print(f"{len(blob_index)} unique blobs")


def extract_spaces(line: str):
    res = ""
    for c in line:
        if not c.isspace():
            break
        res += c
    return res


def method_caller(caller: str) -> bool:
    parts = caller.split(".")
    if not parts[-1].endswith("()"):
        return False
    if any([c.endswith("()") for c in parts[:-1]]):
        return False
    return True


def parse_imports_python(root_node: Node):
    alias_mapping = {}

    for match in py_import_query.matches(root_node):
        import_name = match[1]["import_name"][0].text.decode(errors="ignore")
        alias_name = None
        if "alias_name" in match[1]:
            alias_name = match[1]["alias_name"][0].text.decode(errors="ignore")
        if match[0] == 1:
            from_module = match[1]["from_module"][0].text.decode(errors="ignore")
            statement = f"from {from_module} import {import_name}"
            import_name = f"{from_module}.{import_name}"

        else:
            statement = f"import {import_name}"
        if alias_name:
            statement = statement + f" as {alias_name}"
        alias_mapping[import_name] = statement

    return alias_mapping


def extract_code(source: str, root_node: Node, package: str, caller: str) -> str | None:
    if not method_caller(caller):
        return

    source_lines = source.splitlines()

    imports = py_imports[package]
    related_imports = [
        v
        for k, v in parse_imports_python(root_node).items()
        if any(k.startswith(f"{imp}.") or (k == imp) for imp in imports)
    ]
    cur_node = root_node
    i = 0
    caller = caller.split(".")
    res = []
    while cur_node and (i < len(caller)):
        ctx = caller[i]
        if ctx.endswith("()"):
            query = PY_LANGUAGE.query("(function_definition)@definition")
            found = False
            for match in query.matches(cur_node):
                match_node = match[1]["definition"][0]
                node_name = match_node.child_by_field_name("name").text.decode(
                    errors="ignore"
                )
                context_name = ctx.split("(", 1)[0]
                if node_name != context_name:
                    continue
                found = True
                cur_node = match_node
                start_line = match_node.start_point[0]
                end_line = match_node.end_point[0]
                res.append("\n".join(source_lines[start_line : end_line + 1]))
                i += 1
                break

            if not found:
                return
        else:
            query = PY_LANGUAGE.query("(class_definition)@definition")
            found = False
            for match in query.matches(cur_node):
                match_node = match[1]["definition"][0]
                node_name = match_node.child_by_field_name("name").text.decode(
                    errors="ignore"
                )
                if node_name == ctx:
                    cur_node = match_node
                    found = True
                    start_line = match_node.start_point[0]
                    leading_spaces = extract_spaces(source_lines[start_line])
                    class_header = " ".join(
                        [
                            child.text.decode(errors="ignore")
                            for child in match_node.children[:-1]
                        ]
                    )
                    res.append(leading_spaces + class_header)
                    i += 1
                    break
            if not found:
                return

    return "\n".join(related_imports + res)


def extract_arguments(source, api: str):
    api_full_name = api.split("(")[0]
    res = []
    api_calls = parse_api_calls_python(source).get("api_calls", [])
    for api_call in api_calls:
        for callee in api_call["callee"]:
            full_name = callee["full_name"]
            if api_full_name != full_name:
                continue
            arguments = []
            for arg in callee["arguments"]:
                if "key" in arg:
                    arguments.append(f"{arg['key']}={arg['value']}")
                else:
                    arguments.append(arg["value"])
            res.append(arguments)
    return res


def extract_code_commit_pair(row):
    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    col = db["py_candidate_api_update_instances"]

    package = row["package"]
    old_api = row["old_api"]
    new_api = row["new_api"]
    old_version = row["old_version"]
    new_version = row["new_version"]
    commit = row["commit"]
    res = []
    for doc in col.find({"commit": commit, "package": package}, projection={"_id": 0}):
        version_before = doc["version_before"]
        version_after = doc["version_after"]
        old_blob = doc["old_blob"]
        old_source = read_raw_blob(*blob_index[old_blob])
        old_root_node = PY_PARSER.parse(old_source).root_node
        new_blob = doc["new_blob"]
        new_source = read_raw_blob(*blob_index[new_blob])
        new_root_node = PY_PARSER.parse(new_source).root_node
        visited_caller = []
        for pair in doc["api_update_pairs"]:
            caller = pair["caller"]
            if caller in visited_caller:
                continue
            visited_caller.append(caller)
            old_callee = pair["old_callee"]
            old_callee_api = old_callee["full_name"]

            new_callee = pair["new_callee"]
            new_callee_api = new_callee["full_name"]

            if (version_before == old_version) and (version_after == new_version):
                if (old_callee_api == old_api) and (new_callee_api == new_api):
                    old_code = extract_code(
                        old_source.decode(errors="ignore"),
                        old_root_node,
                        package,
                        caller,
                    )
                    if old_code is None:
                        continue
                    old_args = extract_arguments(old_code, old_api)
                    if not old_args:
                        continue
                    new_code = extract_code(
                        new_source.decode(errors="ignore"),
                        new_root_node,
                        package,
                        caller,
                    )
                    if new_code is None:
                        continue
                    new_args = extract_arguments(new_code, new_api)
                    if not new_args:
                        continue
                    res.append(
                        row
                        | {
                            "old_code": old_code,
                            "old_args": old_args,
                            "new_code": new_code,
                            "new_args": new_args,
                        }
                    )

            if (version_before == new_version) and (version_after == old_version):
                if (old_callee_api == new_api) and (new_callee_api == old_api):
                    old_code = extract_code(
                        old_source.decode(errors="ignore"),
                        old_root_node,
                        package,
                        caller,
                    )
                    if old_code is None:
                        continue
                    old_args = extract_arguments(old_code, new_api)
                    if not old_args:
                        continue
                    new_code = extract_code(
                        new_source.decode(errors="ignore"),
                        new_root_node,
                        package,
                        caller,
                    )
                    if new_code is None:
                        continue
                    new_args = extract_arguments(new_code, old_api)
                    if not new_args:
                        continue
                    res.append(
                        row
                        | {
                            "old_code": new_code,
                            "old_args": new_args,
                            "new_code": old_code,
                            "new_args": old_args,
                        }
                    )
    return res


def extract_main(n_jobs: int = 1):
    commit_pairs_full = json.load(
        open("../benchmark/final/python_commit_pairs_full.json")
    )
    print(len(commit_pairs_full), "commit pairs for full rules")

    res = Parallel(n_jobs=n_jobs, backend="multiprocessing")(
        delayed(extract_code_commit_pair)(row) for row in tqdm(commit_pairs_full)
    )
    final = []
    for r in res:
        final.extend(r)
    with open("../benchmark/final/python_update_instances_full.json", "w") as outf:
        json.dump(final, outf, indent=2)

    instances_full = pd.read_json(
        "../benchmark/final/python_update_instances_full.json"
    )
    print(f"{len(instances_full)} update instances for full rules")
    commit_pairs_exact = pd.read_json(
        "../benchmark/final/python_commit_pairs_exact.json"
    )
    print(f"{len(commit_pairs_exact)} commit pairs for correct verified rules")
    instances_exact = commit_pairs_exact.merge(instances_full)
    print(f"{len(instances_exact)} update instances for correct verified rules")
    instances_exact.to_json(
        "../benchmark/final/python_update_instances_exact.json",
        indent=2,
        orient="records",
    )


if __name__ == "__main__":
    parser = ArgumentParser(
        prog="python extract_python_snippets.py",
        description="Extract functions for Python update pairs",
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")

    args = parser.parse_args()
    extract_main(args.n_jobs)
