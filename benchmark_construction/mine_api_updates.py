import argparse
import json
import logging
import math
import os
import sys

import pandas as pd
from dump_data import insert_many_skip_large
from joblib import Parallel, delayed
from Levenshtein import distance, ratio
from pymongo import MongoClient
from pymongo.collection import Collection
from tqdm.auto import tqdm, trange

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler("../log/mine_api_updates.log", mode="w")
fh.setLevel(logging.DEBUG)
# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.ERROR)
# create formatter and add it to the handlers
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
# add the handlers to logger
logger.addHandler(ch)
logger.addHandler(fh)

py_imports = json.load(open("../benchmark/updates/py_imports.json"))
java_imports = json.load(open("../benchmark/updates/java_imports.json"))
lang_pkg_import_mappings = {"py": py_imports, "java": java_imports}


def get_dependency_update_info(
    dep_updates_col: Collection, commit: str, pkg_import_mappings: dict[str, list[str]]
) -> list[dict]:
    dep_update_info = []
    for doc in dep_updates_col.find(
        {"commit": commit},
        projection={"_id": 0, "filepath": 1, "updated_packages": 1},
    ):
        pkg_info = []
        for pkg in doc["updated_packages"]:
            import_list = pkg_import_mappings.get(pkg["name"])
            if import_list is None:
                continue
            pkg_info.append(
                {
                    "name": pkg["name"],
                    "top_levels": import_list,
                    "version_before": pkg["version_before"],
                    "version_after": pkg["version_after"],
                }
            )
        dep_update_info.append(
            {
                "config_file_path": doc["filepath"].strip("/"),
                "dependency_update_info": pkg_info,
            }
        )
    return dep_update_info


def same_folder(filepath: str, config_file_path: str):
    common_path = os.path.commonpath([filepath, config_file_path])
    # We skip the case that filepath is identical to config_file_path
    if common_path == os.path.dirname(config_file_path):
        return True
    return False


def relevant_packages_by_filepath(
    filepath: str, dep_update_info: list[dict]
) -> dict[str, dict]:
    relevant_config_file = ""
    tmp = []
    for dui in dep_update_info:
        config_file_path = dui["config_file_path"]
        if not same_folder(filepath, config_file_path):
            continue
        if len(config_file_path) >= len(relevant_config_file):
            relevant_config_file = config_file_path
            tmp = dui["dependency_update_info"]

    relevant_packages = {}
    for pkg_info in tmp:
        name = pkg_info["name"]
        relevant_packages[name] = {
            k: pkg_info[k] for k in ["top_levels", "version_before", "version_after"]
        }
    return relevant_packages


def get_imported_relevant_packages(
    modules: list[str], relevant_packages: dict[str, dict]
) -> dict[str, str]:
    imported_relevant_packages = {}
    for module in modules:
        pkg = None
        for pkg_name, pkg_info in relevant_packages.items():
            top_levels = pkg_info["top_levels"]
            for tl in top_levels:
                if module.startswith(f"{tl}.") or (module == tl):
                    pkg = pkg_name
                    break
            if pkg:
                break
        if pkg:
            imported_relevant_packages[module] = pkg
    return imported_relevant_packages


def group_api_calls_by_packages(
    api_calls: list[dict], imported_relevant_packages: dict[str, tuple[str]]
) -> dict[str | tuple, dict[str, dict[str, list[dict]]]]:
    res = {}
    for api_call in api_calls:
        caller = api_call["caller"]
        if isinstance(caller, list):
            caller = tuple(caller)
        for callee in api_call["callee"]:
            full_name = callee["full_name"]
            for module, pkg in imported_relevant_packages.items():
                if full_name.startswith(f"{module}.") or (full_name == module):
                    res[caller] = res.get(caller, dict())
                    res[caller][pkg] = res[caller].get(pkg, [])
                    res[caller][pkg].append(callee)
                    break
    return res


def get_grouped_relevant_api_calls(
    api_calls_col: Collection, blob: str, relevant_packages: dict[str, dict]
) -> dict[str | tuple, dict[str, dict[str, list[dict]]]]:
    apis_calls_info = api_calls_col.find_one(
        {"blob": blob}, projection={"_id": 0, "modules": 1, "api_calls": 1}
    )
    if apis_calls_info is None:
        return {}
    imported_relevant_packages = get_imported_relevant_packages(
        apis_calls_info["modules"], relevant_packages
    )
    if not imported_relevant_packages:
        return {}
    grouped_api_calls = group_api_calls_by_packages(
        apis_calls_info["api_calls"], imported_relevant_packages
    )
    return grouped_api_calls


def get_unique_callees(new_callees: list[dict], old_callees: list[dict]) -> list[dict]:
    unique_callees = []
    for new_callee in new_callees:
        new_full_name = new_callee["full_name"]
        new_arguments = new_callee["arguments"]
        matched = False
        for old_callee in old_callees:
            old_full_name = old_callee["full_name"]
            old_arguments = old_callee["arguments"]
            if (old_full_name == new_full_name) and (
                len(old_arguments) == len(new_arguments)
            ):
                matched = True
                break
        if not matched:
            unique_callees.append(new_callee)
    return unique_callees


def get_update_relevant_apis(
    blob_changes_col: Collection,
    api_calls_col: Collection,
    commit: str,
    dep_update_info: list[dict],
) -> list:
    blob_changes = blob_changes_col.find_one(
        {"commit": commit}, projection={"_id": 0, "blob_changes": 1}
    )
    if blob_changes is None:
        return []

    res = []
    for blob_change in blob_changes["blob_changes"]:
        filepath = blob_change["filepath"].strip("/")
        relevant_packages = relevant_packages_by_filepath(filepath, dep_update_info)

        new_blob = blob_change["new_blob"]
        new_grouped_api_calls = get_grouped_relevant_api_calls(
            api_calls_col, new_blob, relevant_packages
        )
        if not new_grouped_api_calls:
            continue

        old_blob = blob_change["old_blob"]
        old_grouped_api_calls = get_grouped_relevant_api_calls(
            api_calls_col, old_blob, relevant_packages
        )
        if not old_grouped_api_calls:
            continue

        tmp = {}
        for caller, new_pkg_callees in new_grouped_api_calls.items():
            old_pkg_callees = old_grouped_api_calls.get(caller)
            if old_pkg_callees is None:
                continue
            for pkg, new_callees in new_pkg_callees.items():
                old_callees = old_pkg_callees.get(pkg)
                if old_callees is None:
                    continue
                new_unique_callees = get_unique_callees(new_callees, old_callees)
                if not new_unique_callees:
                    continue
                old_unique_callees = get_unique_callees(old_callees, new_callees)
                if not old_unique_callees:
                    continue
                tmp[pkg] = tmp.get(pkg, [])
                tmp[pkg].append(
                    {
                        "caller": caller,
                        "new_callees": new_unique_callees,
                        "old_callees": old_unique_callees,
                    }
                )
        if tmp:
            for pkg, api_call_info in tmp.items():
                res.append(
                    {
                        "commit": commit,
                        "filepath": filepath,
                        "old_blob": old_blob,
                        "new_blob": new_blob,
                        "package": pkg,
                        "version_before": relevant_packages[pkg]["version_before"],
                        "version_after": relevant_packages[pkg]["version_after"],
                        "api_calls": api_call_info,
                    }
                )

    return res


def get_nearby_apis_batch(commit_records: list[str], lang: str, idx: int):
    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    dep_updates_col = db[f"{lang}_dependency_updates"]
    api_calls_col = db[f"{lang}_api_calls"]
    blob_changes_col = db["blob_changes"]

    pkg_import_mappings = lang_pkg_import_mappings[lang]
    res = []
    for record in commit_records:
        try:
            dep_update_info = get_dependency_update_info(
                dep_updates_col, record[0], pkg_import_mappings
            )

            for commit in record:
                if commit == "":
                    continue
                try:
                    tmp = get_update_relevant_apis(
                        blob_changes_col, api_calls_col, commit, dep_update_info
                    )
                    if tmp:
                        res.extend(tmp)
                except:
                    logger.debug(f"get_update_relevant_apis() error for {commit}")
        except:
            logger.debug(f"get_dependency_update_info() error for {record[0]}")
    with open(f"../benchmark/updates/{lang}api_call_changes.json.{idx}", "w") as outf:
        json.dump(res, outf)


def gen_batch_from_file(filepath: str, batch_size: int):
    batch = []
    with open(filepath) as f:
        for line in f:
            batch.append(line.strip("\n").split(","))
            if len(batch) == batch_size:
                yield batch
                batch = []
        if batch:
            yield batch


def split_commit_rows():
    df = pd.read_csv(
        "../benchmark/updates/c.pc.ppc.cc.ccc",
        sep=";",
        names=["commit", "parent", "parent parent", "child", "child child"],
    )
    print(f"{len(df)} commits rows")
    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    for lang in ["py", "java"]:
        dep_updates_col = db[f"{lang}_dependency_updates"]
        commits = pd.DataFrame(
            dep_updates_col.find({}, projection={"_id": 0, "commit": 1})
        )["commit"].unique()
        print(f"{lang}: {len(commits)} unique commits")
        commits = df[df["commit"].isin(commits)]
        print(len(commits))
        commits.to_csv(
            f"../benchmark/updates/{lang}c.pc.ppc.cc.ccc", index=False, header=False
        )


def get_nearby_apis(lang: str, n_jobs: int = 1, batch_size: int = 1):
    commit_filepath = f"../benchmark/updates/{lang}c.pc.ppc.cc.ccc"
    if not os.path.exists(commit_filepath):
        split_commit_rows()

    total_lines = sum(1 for i in open(commit_filepath, "rb"))
    num_batches = math.ceil(total_lines / batch_size)
    print(
        f"{lang}: {n_jobs} processes",
        f"{batch_size} blobs/batch",
        f"{total_lines} lines",
        f"{num_batches} batches",
    )
    batches = gen_batch_from_file(commit_filepath, batch_size)
    Parallel(n_jobs=n_jobs, backend="multiprocessing")(
        delayed(get_nearby_apis_batch)(batch, lang, i)
        for i, batch in tqdm(enumerate(batches), total=num_batches, file=sys.stdout)
    )

    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    db.drop_collection(f"{lang}_api_call_changes")
    col = db[f"{lang}_api_call_changes"]
    for i in trange(num_batches):
        filepath = f"../benchmark/updates/{lang}api_call_changes.json.{i}"
        insert_many_skip_large(col, json.load(open(filepath)))
        os.remove(filepath)
    df = pd.DataFrame(col.find({}, projection={"_id": 0}))
    df.drop_duplicates(
        ["old_blob", "new_blob", "package", "version_before", "version_after"],
        inplace=True,
    )
    db.drop_collection(f"{lang}_api_call_changes")
    data = df.to_dict("records")
    col.create_index("commit")
    col.create_index("packages")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python mine_api_updates.py",
        description="Mine API Updates based on the API call changes between the new and old blobs.",
    )
    parser.add_argument(
        "-n", "--n_jobs", type=int, default=1, help="the number of workers"
    )
    parser.add_argument(
        "-b",
        "--batch_size",
        type=int,
        default=1,
        help="the number of records per batch",
    )
    args = parser.parse_args()

    get_nearby_apis("py", args.n_jobs, args.batch_size)
    get_nearby_apis("java", args.n_jobs, args.batch_size)
