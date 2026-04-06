import argparse
import itertools
import json
import os
import sys

import pandas as pd
from joblib import Parallel, delayed
from pymongo import MongoClient
from pymongo.collection import Collection
from tqdm.auto import tqdm

data_folder = "../../benchmark/phase3"
py_imports = json.load(open(f"{data_folder}/py_imports.json"))
java_imports = json.load(open(f"{data_folder}/java_imports.json"))
lang_lib_imports = {"py": py_imports, "java": java_imports}

py_valid_versions = {
    lib: v.get("versions", [])
    for lib, v in json.load(open(f"{data_folder}/pypi_releases.json")).items()
}
java_valid_versions = json.load(open(f"{data_folder}/maven_releases.json"))
lang_valid_versions = {"py": py_valid_versions, "java": java_valid_versions}


def same_folder(filepath: str, cfg_filepath: str):
    common_path = os.path.commonpath([filepath, cfg_filepath])
    # We skip the case that filepath is identical to cfg_filepath
    if common_path == os.path.dirname(cfg_filepath):
        return True
    return False


def select_relevant_updates(filepath: str, cfg_files: list[dict]) -> dict[str, dict]:
    closest_cfg_file = ""
    relevant_updates = []
    for cfg_file in cfg_files:
        cfg_filepath = cfg_file["cfg_filepath"]
        # configuration files and code files should be in the same folder
        if not same_folder(filepath, cfg_filepath):
            continue
        if len(cfg_filepath) >= len(closest_cfg_file):
            closest_cfg_file = cfg_filepath
            relevant_updates = cfg_file["library_update_info"]

    res = {}
    for update in relevant_updates:
        res[update["library"]] = {
            k: update[k] for k in ["top_levels", "version_before", "version_after"]
        }
    return res


def remove_libs_wo_imports(
    cfg_files: list[dict], lib_imports: dict, valid_versions: dict
):
    res = []
    for cfg in cfg_files:
        library_update_info = []
        for update in cfg["dependency_changes"]:
            lib = update["library"]
            version_before = update["version_before"]
            version_after = update["version_after"]
            top_levels = lib_imports.get(lib)
            if top_levels is None:
                continue
            if version_before not in valid_versions.get(lib, []):
                continue
            if version_after not in valid_versions.get(lib, []):
                continue
            library_update_info.append(
                {
                    "library": lib,
                    "top_levels": top_levels,
                    "version_before": update["version_before"],
                    "version_after": update["version_after"],
                }
            )
        if library_update_info:
            res.append(
                {
                    "cfg_filepath": cfg["filepath"],
                    "library_update_info": library_update_info,
                }
            )

    return res


def identify_imported_libraries(
    modules: list[str], relevant_updates: dict[str, dict]
) -> dict[str, str]:
    imported_libraries = {}
    for module in modules:
        lib = None
        longest_match = ""
        for name, info in relevant_updates.items():
            top_levels = info["top_levels"]
            for top_level in top_levels:
                if module.startswith(f"{top_level}.") or (module == top_level):
                    # if multiple updated libraries have overlapped top-level modules
                    # select the longest matched library
                    if len(top_level) > len(longest_match):
                        longest_match = top_level
                        lib = name
        if lib:
            imported_libraries[module] = lib
    return imported_libraries


def group_api_calls_by_libraries(
    api_calls: list[dict], libraries: dict[str, tuple[str]]
) -> dict[str | tuple, dict[str, dict[str, list[dict]]]]:
    res = {}
    for api_call in api_calls:
        caller = api_call["caller"]
        if isinstance(caller, list):
            caller = tuple(caller)
        for callee in api_call["callee"]:
            full_name = callee["full_name"]
            for module, lib in libraries.items():
                if full_name.startswith(f"{module}.") or (full_name == module):
                    res[caller] = res.get(caller, dict())
                    res[caller][lib] = res[caller].get(lib, [])
                    res[caller][lib].append(callee)
                    break
    return res


def group_relevant_api_calls(
    api_calls_col: Collection, blob: str, relevant_updates: dict[str, dict]
) -> dict[str | tuple, dict[str, dict[str, list[dict]]]]:
    apis_calls = api_calls_col.find_one(
        {"blob": blob}, projection={"_id": 0, "modules": 1, "api_calls": 1}
    )
    if apis_calls is None:
        return {}

    imported_libraries = identify_imported_libraries(
        apis_calls["modules"], relevant_updates
    )
    if not imported_libraries:
        return {}
    res = group_api_calls_by_libraries(apis_calls["api_calls"], imported_libraries)
    return res


def get_unique_callees(new_callees: list[dict], old_callees: list[dict]) -> list[dict]:
    unique_callees = []
    for new_callee in new_callees:
        new_full_name = new_callee["full_name"]
        matched = False
        for old_callee in old_callees:
            old_full_name = old_callee["full_name"]
            # It is common that two different method calls have the same full qualified name
            # but have different parameters in both Java and Python.
            # Java: method overloading
            # Python: default arguments, arbitrary arguments (*args, **kwargs)
            # In these cases, it it hard to validate whether two api calls with the same full
            # qualified name but different parameters are breaking changes or not. That is, they
            # can lead to many false positives. Therefore, to keep the dataset with high precision,
            # we simply filter api calls with the same full qualified name.
            if old_full_name == new_full_name:
                matched = True
                break
        if not matched:
            unique_callees.append(new_callee)
    return unique_callees


def update_relevant_api_call_changes(
    commit: str, code_files: dict, cfg_files: list[dict], api_calls_col: Collection
):
    res = []
    for code_file in code_files:
        filepath = code_file["filepath"]
        if "third_party" in filepath.split("/"):
            continue
        # select library updates in the closest configuration file
        relevant_updates = select_relevant_updates(filepath, cfg_files)

        new_blob = code_file["new_blob"]
        new_api_calls = group_relevant_api_calls(
            api_calls_col, new_blob, relevant_updates
        )
        if not new_api_calls:
            continue

        old_blob = code_file["old_blob"]
        old_api_calls = group_relevant_api_calls(
            api_calls_col, old_blob, relevant_updates
        )
        if not old_api_calls:
            continue

        for caller, new_lib_callees in new_api_calls.items():
            old_lib_callees = old_api_calls.get(caller)
            if old_lib_callees is None:
                continue

            for lib, new_callees in new_lib_callees.items():
                old_callees = old_lib_callees.get(lib)
                if old_callees is None:
                    continue
                new_unique_callees = get_unique_callees(new_callees, old_callees)
                if not new_unique_callees:
                    continue
                old_unique_callees = get_unique_callees(old_callees, new_callees)
                if not old_unique_callees:
                    continue
                res.append(
                    {
                        "commit": commit,
                        "filepath": filepath,
                        "old_blob": old_blob,
                        "new_blob": new_blob,
                        "library": lib,
                        "version_before": relevant_updates[lib]["version_before"],
                        "version_after": relevant_updates[lib]["version_after"],
                        "caller": caller,
                        "old_callees": old_unique_callees,
                        "new_callees": new_unique_callees,
                    }
                )

    return res


def detect_api_call_changes(doc: dict, lang: str):
    client = MongoClient("127.0.0.1", 27017)
    db = client["bridge"]
    api_calls_col = db[f"{lang}_api_calls"]

    # remove libraries without importable files
    cfg_files = remove_libs_wo_imports(
        doc["configuration_files"], lang_lib_imports[lang], lang_valid_versions[lang]
    )
    if not cfg_files:
        return []

    api_call_changes = update_relevant_api_call_changes(
        doc["commit"], doc["code_files"], cfg_files, api_calls_col
    )

    return api_call_changes


def main(lang: str, n_jobs: int = 1):
    client = MongoClient("127.0.0.1", 27017)
    db = client["bridge"]
    col = db[f"{lang}_update_commits"]

    num_update_commits = col.estimated_document_count()
    print(f"{lang}: {num_update_commits} update commits")

    results = Parallel(n_jobs=n_jobs, backend="multiprocessing")(
        delayed(detect_api_call_changes)(doc, lang)
        for doc in tqdm(
            col.find({}, projection={"_id": 0}),
            total=num_update_commits,
            file=sys.stdout,
        )
    )

    results = list(itertools.chain.from_iterable(results))

    df = pd.DataFrame(results)
    data = df.drop_duplicates(
        ["old_blob", "new_blob", "library", "version_before", "version_after", "caller"]
    ).to_dict("records")

    api_call_changes_col = db[f"{lang}_api_call_changes"]
    api_call_changes_col.drop()
    api_call_changes_col.insert_many(data)
    api_call_changes_col.create_index("commit")
    api_call_changes_col.create_index("library")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python detect_api_call_changes.py",
        description="Detect API call discrepancies within the same caller between the new and old blobs.",
    )
    parser.add_argument(
        "-n", "--n_jobs", type=int, default=1, help="the number of workers"
    )

    args = parser.parse_args()
    main("py", args.n_jobs)
    main("java", args.n_jobs)
