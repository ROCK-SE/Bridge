import argparse
import json
import logging
import math
import os
import re
import sys

import pandas as pd
from joblib import Parallel, delayed
from Levenshtein import distance, ratio
from pymongo import MongoClient
from pymongo.collection import Collection
from tqdm.auto import tqdm, trange
from utils import insert_many_skip_large

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
        cur_tl = ""
        for pkg_name, pkg_info in relevant_packages.items():
            top_levels = pkg_info["top_levels"]
            for tl in top_levels:
                if module.startswith(f"{tl}.") or (module == tl):
                    if len(tl) > len(cur_tl):
                        cur_tl = tl
                        pkg = pkg_name
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

    data = []
    for i in trange(num_batches):
        filepath = f"../benchmark/updates/{lang}api_call_changes.json.{i}"
        data.extend(json.load(open(filepath)))
        os.remove(filepath)
    df = pd.DataFrame(data)
    print(f"{len(df)} {lang} api change records before deduplicates")
    df.drop_duplicates(
        ["old_blob", "new_blob", "package", "version_before", "version_after"],
        inplace=True,
    )
    print(f"{len(df)} {lang} api change records after deduplicates")
    data = df.to_dict("records")

    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    db.drop_collection(f"{lang}_api_call_changes")
    col = db[f"{lang}_api_call_changes"]
    insert_many_skip_large(col, data)
    col.create_index("commit")
    col.create_index("package")


def split_java_identifier(identifier: str) -> list[str]:
    res = []
    for part in identifier.split("_"):
        if not part:
            continue
        res.extend(
            re.sub("([A-Z][a-z]+)", r" \1", re.sub("([A-Z]+)", r" \1", part)).split()
        )
    return [s.lower() for s in res]


def split_identifier_list(identifiers: str | list[str], splitter) -> list[str]:
    if isinstance(identifiers, str):
        return splitter(identifiers)
    res = []
    for identifier in identifiers:
        res.extend(splitter(identifier))
    return res


def split_java_class_method_names(full_api_name: str) -> tuple[list[str], str]:
    parts = full_api_name.split(".")
    for i, part in enumerate(parts):
        if not part:
            continue
        if part[0].isupper():
            break
    return parts[i:-1], parts[-1]


def java_name_similarity(parts1: list[str], parts2: list[str]) -> float:
    if parts1 == parts2:
        return 1.0

    total = len(parts1) + len(parts2)
    num_common_parts = 0
    for p1 in parts1:
        for p2 in parts2:
            if p1 == p2:
                num_common_parts += 1
                total -= 1
                parts2.remove(p2)
                break
            if p1.startswith(p2) or p2.startswith(p1):
                num_common_parts += 0.5
                total -= 1
                parts2.remove(p2)
                break

    return num_common_parts / total


def java_method_name_similarity(
    method_name1: str,
    method_name2: str,
    min_word_len: int = 1,
) -> float:
    # List borrowed from RepFinder
    PREPOSITION = [
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "and",
        "with",
        "as",
    ]
    parts1 = [
        word
        for word in split_java_identifier(method_name1)
        if (len(word) >= min_word_len) and (word not in PREPOSITION)
    ]
    parts2 = [
        word
        for word in split_java_identifier(method_name2)
        if (len(word) >= min_word_len) and (word not in PREPOSITION)
    ]
    if not parts1:
        return 0.0
    if not parts2:
        return 0.0
    # List borrowed from RepFinder
    VERBS = [
        "add",
        "get",
        "set",
        "is",
        "have",
        "are",
        "remove",
        "delete",
        "assert",
        "query",
        "find",
        "compare",
        "any",
        "to",
        "opt",
        "select",
        "write",
        "read",
    ]
    if (parts1[0] in VERBS) and (parts2[0] in VERBS):
        # set vs get
        if parts1[0] != parts2[0]:
            return 0.0

        # isBlack vs isNotBlank
        if (len(parts1) > 1) and (len(parts2) > 1):
            if (parts1[1] == "not") and (parts2[1] != "not"):
                return 0.0
            if (parts2[1] == "not") and (parts1[1] != "not"):
                return 0.0
            if (parts1[1] == "as") and (parts2 == "as"):
                return

        return java_name_similarity(parts1[1:], parts2[1:])

    if parts1[0] in ["get", "is"]:
        return java_name_similarity(parts1[1:], parts2)

    if parts2[0] in ["get", " is"]:
        return java_name_similarity(parts1, parts2[1:])

    return java_name_similarity(parts1, parts2)


def java_class_name_similarity(
    class_name1: list[str],
    class_name2: list[str],
    min_word_len: int = 1,
) -> float:
    parts1 = [
        word
        for word in split_identifier_list(class_name1, split_java_identifier)
        if len(word) >= min_word_len
    ]
    parts2 = [
        word
        for word in set(split_identifier_list(class_name2, split_java_identifier))
        if len(word) >= min_word_len
    ]
    return java_name_similarity(parts1, parts2)


def java_api_name_similarity(
    full_api_name1: str,
    full_api_name2: str,
    min_word_len: int = 1,
) -> tuple[float, float]:
    full_api_name1 = re.sub("[^0-9a-zA-Z_.]", "", full_api_name1)
    full_api_name2 = re.sub("[^0-9a-zA-Z_.]", "", full_api_name2)
    class_name1, method_name1 = split_java_class_method_names(full_api_name1)
    class_name2, method_name2 = split_java_class_method_names(full_api_name2)

    if class_name1 == class_name2:
        class_similarity = 1.0
    else:
        class_similarity = java_class_name_similarity(
            class_name1, class_name2, min_word_len
        )

    # Common method naming conventions that create instance of the caller class
    # Therefore, I assign them with the value of class name
    special_method_names = [
        "valueOf",
        "from",
        "of",
        "getInstance",
        "newInstance",
        "create",
    ]
    if (method_name1 in special_method_names) and (class_name1):
        method_name1 = class_name1[0]
    if (method_name2 in special_method_names) and (class_name2):
        method_name2 = class_name2[0]
    if method_name1 == method_name2:
        method_similarity = 1.0
    else:
        method_similarity = java_method_name_similarity(
            method_name1, method_name2, min_word_len
        )

    return class_similarity, method_similarity


def offset_similarity(offset1: int, offset2: int) -> float:
    dis = abs(offset1 - offset2)
    # add 1 to avoid zero division error
    return 1 / (dis + 1)


def java_arguments_similarity(arguments1: list[dict], arguments2: list[dict]) -> float:
    func = lambda arguments: [arg["value"] for arg in arguments]
    arguments1 = func(arguments1)
    arguments2 = func(arguments2)
    lensum = len(arguments1) + len(arguments2)
    if lensum == 0:
        return 0.6
    return ratio(arguments1, arguments2)


def gte(a: float, b: float, rel_tol=1e-09, abs_tol=0.0) -> bool:
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol) or (a > b)


def lte(a: float, b: float, rel_tol=1e-09, abs_tol=0.0) -> bool:
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol) or (a < b)


def java_api_call_similarity(
    api_call1: dict,
    api_call2: dict,
    weights: list[float] = [0.3, 0.3, 0.2, 0.2],
    min_word_len: int = 1,
) -> float:
    assert len(weights) == 4
    full_name1 = api_call1["full_name"]
    full_name2 = api_call2["full_name"]
    class_sim, method_sim = java_api_name_similarity(
        full_name1, full_name2, min_word_len
    )
    if class_sim < 0.25:
        return 0.0
    if method_sim < 0.25:
        return 0.0

    offset1 = api_call1["offset"]
    offset2 = api_call2["offset"]
    offset_sim = offset_similarity(offset1, offset2)
    arguments1 = api_call1["arguments"]
    arguments2 = api_call2["arguments"]
    arg_sim = java_arguments_similarity(arguments1, arguments2)

    overall_sim = (
        weights[0] * class_sim
        + weights[1] * method_sim
        + weights[2] * offset_sim
        + weights[3] * arg_sim
    )
    return overall_sim


def mine_java_api_update_instance(
    doc: dict,
    sim_threshold: float = 0.7,
    num_neighbors: int = 3,
    weights: list[float] = [0.3, 0.3, 0.2, 0.2],
    min_word_len: int = 1,
):
    assert len(weights) == 4
    api_update_pairs = []
    for api_calls in doc["api_calls"]:
        caller = api_calls["caller"]
        new_callees = api_calls["new_callees"]
        old_callees = api_calls["old_callees"]
        for new_callee in new_callees:
            max_sim_score = 0
            best_candidate = None
            candidate_old_callees = sorted(
                old_callees,
                key=lambda old_callee: abs(old_callee["offset"] - new_callee["offset"]),
            )[:num_neighbors]
            for old_callee in candidate_old_callees:
                sim_score = java_api_call_similarity(
                    new_callee, old_callee, weights, min_word_len
                )
                if gte(sim_score, max_sim_score):
                    max_sim_score = sim_score
                    best_candidate = old_callee
            if gte(max_sim_score, sim_threshold):
                api_update_pairs.append(
                    {
                        "caller": caller,
                        "old_callee": best_candidate,
                        "new_callee": new_callee,
                        "similarity_score": max_sim_score,
                    }
                )
    if api_update_pairs:
        res = {}
        for k in [
            "commit",
            "filepath",
            "old_blob",
            "new_blob",
            "package",
            "version_before",
            "version_after",
        ]:
            res[k] = doc[k]
        res["api_update_pairs"] = api_update_pairs
        return res


def split_python_identifier(identifier: str) -> list[str]:
    res = []
    for part in identifier.split("_"):
        if not part:
            continue
        part = re.sub("(([0-9]+[A-Za-z])|([A-Z]+))", r" \1", part)
        part = re.sub("(([0-9]+[A-Za-z]+)|([A-Z][a-z]+))", r" \1", part)
        res.extend(part.split())
    return [s.lower() for s in res]


def python_custom_equal(p1: str, p2: str) -> bool:
    if p1 == p2:
        return True
    if p1.startswith(p2) or p2.startswith(p1):
        return True
    return False


def python_name_similarity(name1: str, name2: str, min_word_len: int = 1) -> float:
    parts1 = [
        word for word in split_python_identifier(name1) if len(word) >= min_word_len
    ]
    parts2 = [
        word for word in split_python_identifier(name2) if len(word) >= min_word_len
    ]
    if not parts1:
        return 0.0
    if not parts2:
        return 0.0

    if parts1 == parts2:
        return 1.0

    max_len = max(len(parts1), len(parts2))
    num_common_parts = 0
    for p1 in parts1:
        for p2 in parts2:
            if python_custom_equal(p1, p2):
                parts2.remove(p2)
                num_common_parts += 1
                break
    return num_common_parts / max_len


def is_compact(method_name1: str, method_name2: str) -> bool:
    name_list1 = split_python_identifier(method_name1)
    name_list2 = split_python_identifier(method_name2)
    if len(name_list1) == 1:
        if name_list1[0] == "".join(n[0] for n in name_list2):
            return True
    elif len(name_list2) == 1:
        if name_list2[0] == "".join(n[0] for n in name_list1):
            return True
    return False


def python_api_name_similarity(
    api_name1: str,
    api_name2: str,
    min_word_len: int = 1,
) -> float:
    api_parts1 = api_name1.split(".")
    api_parts2 = api_name2.split(".")
    method_name1 = api_parts1[-1]
    method_name2 = api_parts2[-1]

    norm_method_name1 = method_name1.replace("_", "").lower()
    norm_method_name2 = method_name2.replace("_", "").lower()
    # AutoTokenizer.from_pretrained BertTokenizer.from_pretrained
    if method_name1 == method_name2:
        if (len(api_parts1) > 1) and (len(api_parts2) > 1):
            if api_parts1[-2][0].isupper() and api_parts2[-2][0].isupper():
                return python_name_similarity(api_parts1[-2], api_parts2[-2])
        return 1.0
    # arg_max vs argmin
    if norm_method_name1 == norm_method_name2:
        return 1.0

    if is_compact(method_name1, method_name2):
        return 1.0

    return python_name_similarity(method_name1, method_name2, min_word_len)


def python_arguments_similarity(
    arguments1: list[dict], arguments2: list[dict]
) -> float:
    num_args1 = len(arguments1)
    num_args2 = len(arguments2)
    if (num_args1 + num_args2) == 0:
        return 1.0

    num_commons = 0

    pos_args1 = [arg["value"] for arg in arguments1 if arg["arg_type"] == "positional"]
    pos_args2 = [arg["value"] for arg in arguments2 if arg["arg_type"] == "positional"]
    for i in range(min(len(pos_args1), len(pos_args2))):
        if pos_args1[i] == pos_args2[i]:
            num_commons += 1

    star_pos1 = [arg["value"] for arg in arguments1 if arg["arg_type"] == "*positional"]
    star_pos2 = [arg["value"] for arg in arguments2 if arg["arg_type"] == "*positional"]
    num_commons += len(set(star_pos1).intersection(star_pos2))

    star_kw1 = [arg["value"] for arg in arguments1 if arg["arg_type"] == "**keyword"]
    star_kw2 = [arg["value"] for arg in arguments2 if arg["arg_type"] == "**keyword"]
    num_commons += len(set(star_kw1).intersection(star_kw2))

    kw_args1 = {
        arg["key"]: arg["value"] for arg in arguments1 if arg["arg_type"] == "keyword"
    }
    kw_args2 = {
        arg["key"]: arg["value"] for arg in arguments2 if arg["arg_type"] == "keyword"
    }
    for k, v1 in kw_args1.items():
        v2 = kw_args2.get(k)
        if v2:
            num_commons += 0.5
        if v1 == v2:
            num_commons += 0.5

    num_commons2 = 0
    arg_values1 = [arg["value"] for arg in arguments1]
    arg_values2 = [arg["value"] for arg in arguments2]
    for i in range(min(num_args1, num_args2)):
        if arg_values1[i] == arg_values2[i]:
            num_commons2 += 1

    return max(num_commons, num_commons2) / (num_args1 + num_args2 - num_commons)


def python_api_call_similarity(
    api_call1: dict,
    api_call2: dict,
    weights: list[float] = [0.5, 0.3, 0.2],
    min_word_len: int = 1,
) -> float:
    assert len(weights) == 3
    full_name1 = api_call1["full_name"]
    full_name2 = api_call2["full_name"]
    name_sim = python_api_name_similarity(full_name1, full_name2, min_word_len)
    if math.isclose(name_sim, 0.0):
        return 0.0

    offset1 = api_call1["offset"]
    offset2 = api_call2["offset"]
    offset_sim = offset_similarity(offset1, offset2)
    arguments1 = api_call1["arguments"]
    arguments2 = api_call2["arguments"]
    arg_sim = python_arguments_similarity(arguments1, arguments2)

    # print(name_sim, arg_sim, offset_sim)
    overall_sim = weights[0] * name_sim + weights[1] * arg_sim + weights[2] * offset_sim

    return overall_sim


def mine_python_api_update_instance(
    doc: dict,
    sim_threshold: float = 0.7,
    num_neighbors: int = 3,
    weights: list[float] = [0.5, 0.3, 0.2],
    min_word_len: int = 1,
):
    assert len(weights) == 3
    api_update_pairs = []
    for api_calls in doc["api_calls"]:
        caller = api_calls["caller"]
        new_callees = api_calls["new_callees"]
        old_callees = api_calls["old_callees"]
        for new_callee in new_callees:
            max_sim_score = 0
            best_candidate = None
            candidate_old_callees = sorted(
                old_callees,
                key=lambda old_callee: abs(old_callee["offset"] - new_callee["offset"]),
            )[:num_neighbors]
            for old_callee in candidate_old_callees:
                sim_score = python_api_call_similarity(
                    new_callee, old_callee, weights, min_word_len
                )
                if gte(sim_score, max_sim_score):
                    max_sim_score = sim_score
                    best_candidate = old_callee
            if gte(max_sim_score, sim_threshold):
                api_update_pairs.append(
                    {
                        "caller": caller,
                        "old_callee": best_candidate,
                        "new_callee": new_callee,
                        "similarity_score": max_sim_score,
                    }
                )
    if api_update_pairs:
        res = {}
        for k in [
            "commit",
            "filepath",
            "old_blob",
            "new_blob",
            "package",
            "version_before",
            "version_after",
        ]:
            res[k] = doc[k]
        res["api_update_pairs"] = api_update_pairs
        return res


def mine_all(lang: str):
    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    api_call_changes_col = db[f"{lang}_api_call_changes"]
    docs = list(api_call_changes_col.find({}))
    print(f"{lang}: {len(docs)} api call change records")
    if lang == "java":
        miner = mine_java_api_update_instance
    elif lang == "py":
        miner = mine_python_api_update_instance
    res = []
    for doc in tqdm(docs):
        res.append(miner(doc))
    if lang == "java":
        releases_filepath = "../benchmark/updates/maven_releases.json"
        releases_info = json.load(open(releases_filepath))
    elif lang == "py":
        releases_filepath = "../benchmark/updates/pypi_releases.json"
        releases_info = {
            pkg: list(v.keys()) for pkg, v in json.load(open(releases_filepath)).items()
        }
    print(f"{lang}: {len(releases_info)} packages' release information")
    final_res = []
    for doc in res:
        if not doc:
            continue
        package = doc["package"]
        all_versions = releases_info[package]
        version_before = doc["version_before"]
        version_after = doc["version_after"]
        if version_before not in all_versions:
            continue
        if version_after not in all_versions:
            continue
        final_res.append(doc)

    print(f"{lang}: {len(final_res)} candidates")
    db.drop_collection(f"{lang}_candidate_api_update_instances")
    candidate_api_update_instances = db[f"{lang}_candidate_api_update_instances"]
    insert_many_skip_large(candidate_api_update_instances, final_res)
    candidate_api_update_instances.create_index("commit")
    candidate_api_update_instances.create_index("package")


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
    parser.add_argument(
        "--nearby",
        action="store_true",
        help="get nearby apis",
    )
    parser.add_argument(
        "--java",
        action="store_true",
        help="mine candidate api update instances for Java",
    )
    parser.add_argument(
        "--python",
        action="store_true",
        help="mine candidate api update instances for Python",
    )
    args = parser.parse_args()

    if args.nearby:
        get_nearby_apis("py", args.n_jobs, args.batch_size)
        get_nearby_apis("java", args.n_jobs, args.batch_size)

    if args.java:
        mine_all("java")

    if args.python:
        mine_all("py")
