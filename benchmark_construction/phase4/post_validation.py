import argparse
import json
import os

import pandas as pd
from java_api_signature_resolver import best_cand
from java_post_validation import check_existence as check_existence_java
from joblib import Parallel, delayed
from py_post_validation import APIResolver
from pymongo import MongoClient
from tqdm import tqdm
from utils import insert_many_skip_large

with open("config.json") as f:
    dest_folder = json.load(f).get("dest_folder")


def prepre_wheel_path():
    res = {}
    data_path = f"../../benchmark/phase4/py_wheel_validation.csv"
    for rec in pd.read_csv(data_path, keep_default_na=False).itertuples(index=False):
        name = rec.name
        version = rec.version
        url = rec.url
        filename = url.split("/")[-1]
        wheel_path = os.path.join(dest_folder, "python", name, filename)
        res[(name, version)] = wheel_path
    return res


wheel_paths = prepre_wheel_path()
print(len(wheel_paths), "wheels")


def java_validation(
    library: str,
    version1: str,
    api_fqn1: str,
    arguments1: int,
    version2: str,
    api_fqn2: str,
    arguments2: int,
):
    arg_count1 = len(arguments1)
    # 1. Existence check
    old_existence = True
    old_api_sigs = check_existence_java(
        library, version1, dest_folder, api_fqn1, arg_count1
    )
    most_prob_old_param_types = []
    if not old_api_sigs:
        old_existence = False
    elif len(old_api_sigs) == 1:
        most_prob_old_param_types = old_api_sigs[0]["parameter_types"]
    else:
        candidates = [sig["parameter_types"] for sig in old_api_sigs]
        most_prob_old_param_types = best_cand(arguments1, candidates)

    arg_count2 = len(arguments2)
    new_existence = True
    new_api_sigs = check_existence_java(
        library, version2, dest_folder, api_fqn2, arg_count2
    )
    most_prob_new_param_types = []
    if not new_api_sigs:
        new_existence = False
    elif len(new_api_sigs) == 1:
        most_prob_new_param_types = new_api_sigs[0]["parameter_types"]
    else:
        candidates = [sig["parameter_types"] for sig in new_api_sigs]
        most_prob_new_param_types = best_cand(arguments2, candidates)

    # 2. Removal/deprecation check
    parts1 = [int(_) for _ in version1.split(".")]
    parts2 = [int(_) for _ in version2.split(".")]
    old_removal = False
    # version2 is old version, version1 is new version
    if parts1 > parts2:
        old_api_sigs_in_new = check_existence_java(
            library, version1, dest_folder, api_fqn2, arg_count2
        )
    # otherwise, version2 is new version
    else:
        old_api_sigs_in_new = check_existence_java(
            library, version2, dest_folder, api_fqn1, arg_count1
        )
    # Removed in new version
    if not old_api_sigs_in_new:
        old_removal = True

    # Still exists, but deprecated in new version
    old_deprecated = any(
        sig.get("member_deprecated", False)
        or sig.get("receiver_type_deprecated", False)
        for sig in old_api_sigs_in_new
    )

    validation = old_existence and new_existence and (old_removal or old_deprecated)

    res = {
        "old_existence": old_existence,
        "old_candidate_sigs": old_api_sigs,
        "most_prob_old_param_types": most_prob_old_param_types,
        "new_existence": new_existence,
        "new_candidate_sigs": new_api_sigs,
        "most_prob_new_param_types": most_prob_new_param_types,
        "old_removal": old_removal,
        "old_deprecated": old_deprecated,
        "validation": validation,
    }
    return res


def check_existence_py(library: str, version: str, api_fqn: str) -> list[dict]:
    wheel_path = wheel_paths.get((library, version))
    if wheel_path is None:
        return
    resolver = APIResolver(wheel_path)
    return resolver.check_existence(api_fqn)


def python_validation(
    library: str,
    version1: str,
    api_fqn1: str,
    version2: str,
    api_fqn2: str,
):
    # 1. Existence check
    old_existence = True
    old_api_sigs = check_existence_py(library, version1, api_fqn1)
    if not old_api_sigs:
        old_existence = False

    new_existence = True
    new_api_sigs = check_existence_py(library, version2, api_fqn2)
    if not new_api_sigs:
        new_existence = False

    # 2. Removal/deprecation check
    parts1 = [int(_) for _ in version1.split(".")]
    parts2 = [int(_) for _ in version2.split(".")]
    old_removal = False
    old_deprecated = False
    # version2 is old version, version1 is new version
    if parts1 > parts2:
        old_api_sig_in_new = check_existence_py(library, version1, api_fqn2)
    # otherwise, version2 is new version
    else:
        old_api_sig_in_new = check_existence_py(library, version2, api_fqn1)
    # Removed in new version
    if not old_api_sig_in_new:
        old_removal = True
    else:
        old_deprecated = old_api_sig_in_new.get("deprecation", False)

    validation = False
    # some old library versions do not have a wheel file
    # in these case, if old fqn is deprecated in new version
    # we consider old fqn exist in old version
    if new_existence and old_deprecated:
        validation = True
    if old_existence and new_existence and old_removal:
        validation = True
    res = {
        "old_existence": old_existence,
        "new_existence": new_existence,
        "old_removal": old_removal,
        "old_deprecated": old_deprecated,
        "validation": validation,
    }
    return res


def validate_per_instance(doc: dict, lang: str):
    library = doc["library"]
    version_before = doc["version_before"]
    version_after = doc["version_after"]
    old_api_call = doc["old_callee"]
    new_api_call = doc["new_callee"]

    old_api_fqn = old_api_call["full_name"]
    new_api_fqn = new_api_call["full_name"]
    if lang == "java":
        validation_results = java_validation(
            library,
            version_before,
            old_api_fqn,
            old_api_call["arguments"],
            version_after,
            new_api_fqn,
            new_api_call["arguments"],
        )

    elif lang == "py":
        validation_results = python_validation(
            library,
            version_before,
            old_api_fqn,
            version_after,
            new_api_fqn,
        )

    return doc | validation_results


def main(lang: str, n_jobs: int = 1):
    client = MongoClient("127.0.0.1", 27017)
    db = client["bridge"]
    col = db[f"{lang}_candidate_update_instances"]
    res = Parallel(n_jobs=n_jobs)(
        delayed(validate_per_instance)(doc, lang)
        for doc in tqdm(
            col.find({}, projection={"_id": 0}), total=col.estimated_document_count()
        )
    )
    col.drop()
    insert_many_skip_large(col, res)
    col.create_index("commit")
    col.create_index("library")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python post_validation.py",
        description="Perform post validation on mined candidate update instances.",
    )
    parser.add_argument(
        "--java",
        action="store_true",
        help="validate Java update instances. DEFAULT: False",
    )
    parser.add_argument(
        "--python",
        action="store_true",
        help="validate Python update instances. DEFAULT: False",
    )
    parser.add_argument(
        "-n", "--n_jobs", type=int, default=1, help="the number of workers. DEFAULT: 1"
    )
    args = parser.parse_args()

    if args.java:
        main("java", args.n_jobs)

    if args.python:
        main("py", args.n_jobs)
