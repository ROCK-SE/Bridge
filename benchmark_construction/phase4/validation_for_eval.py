import argparse
import json

import pandas as pd
from bson import ObjectId
from java_post_validation import check_existence
from pymongo import MongoClient
from tqdm import tqdm

client = MongoClient("127.0.0.1", 27017)
db = client["bridge"]
java_col = db["java_api_call_changes"]
with open("config.json") as f:
    dest_folder = json.load(f).get("dest_folder")


def validate_per_java_doc(df: pd.DataFrame):
    oid = df["record_id"].values[0]
    doc = java_col.find_one({"_id": ObjectId(oid)})
    library = doc["library"]
    version_before = doc["version_before"]
    version_after = doc["version_after"]
    old_callees = doc["old_callees"]
    new_callees = doc["new_callees"]

    parts_before = [int(_) for _ in version_before.split(".")]
    parts_after = [int(_) for _ in version_after.split(".")]
    reverse = parts_before > parts_after

    res = []
    for i, old_callee in enumerate(old_callees):
        old_api_fqn = old_callee["full_name"]
        old_arg_count = len(old_callee["arguments"])
        old_existence = True
        old_api_sigs = check_existence(
            library,
            version_before,
            dest_folder,
            old_api_fqn,
            old_arg_count,
        )
        if not old_api_sigs:
            old_existence = False

        for j, new_callee in enumerate(new_callees):
            new_api_fqn = new_callee["full_name"]
            new_arg_count = len(new_callee["arguments"])
            new_api_sigs = check_existence(
                library,
                version_after,
                dest_folder,
                new_api_fqn,
                new_arg_count,
            )
            new_existence = True
            if not new_api_sigs:
                new_existence = False
            if reverse:
                old_api_sigs_in_new = check_existence(
                    library, version_before, dest_folder, new_api_fqn, new_arg_count
                )
            else:
                old_api_sigs_in_new = check_existence(
                    library, version_after, dest_folder, old_api_fqn, old_arg_count
                )
            old_removal = False
            if not old_api_sigs_in_new:
                old_removal = True
            old_deprecated = any(
                sig.get("member_deprecated", False)
                or sig.get("receiver_type_deprecated", False)
                for sig in old_api_sigs_in_new
            )
            final = old_existence and new_existence and (old_removal or old_deprecated)
            res.append(
                (
                    oid,
                    i,
                    j,
                    old_existence,
                    new_existence,
                    old_removal,
                    old_deprecated,
                    final,
                )
            )
    return res


import json
import os

import pandas as pd
from bson import ObjectId
from py_post_validation import APIResolver
from pymongo import MongoClient
from tqdm import tqdm

client = MongoClient("127.0.0.1", 27017)
db = client["bridge"]
py_col = db["py_api_call_changes"]
with open("config.json") as f:
    dest_folder = json.load(f).get("dest_folder")


def prepre_wheel_path():
    res = {}
    data_path = f"../../benchmark/phase4/py_wheel_evaluation.csv"
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


def check_api_existence_py(resolver: APIResolver, api_fqn: str):
    if resolver is None:
        return
    try:
        resolver.seen = set()
        api_sig = resolver.resolve(api_fqn)
        if api_sig:
            module_deprecation = resolver.check_module_deprecated(api_fqn)
            api_sig["deprecation"] = api_sig["deprecation"] or module_deprecation
        return api_sig
    except:
        return


def validate_per_py_doc(df: pd.DataFrame):
    oid = df["record_id"].values[0]
    doc = py_col.find_one({"_id": ObjectId(oid)})
    library = doc["library"]
    version_before = doc["version_before"]
    version_after = doc["version_after"]
    old_callees = doc["old_callees"]
    new_callees = doc["new_callees"]

    parts_before = [int(_) for _ in version_before.split(".")]
    parts_after = [int(_) for _ in version_after.split(".")]
    reverse = parts_before > parts_after

    wheel_path_before = wheel_paths.get((library, version_before))
    if wheel_path_before is None:
        resolver_before = None
    else:
        resolver_before = APIResolver(wheel_path_before)
    wheel_path_after = wheel_paths.get((library, version_after))
    if wheel_path_after is None:
        resolver_after = None
    else:
        resolver_after = APIResolver(wheel_path_after)

    res = []
    for i, old_callee in enumerate(old_callees):
        old_api_fqn = old_callee["full_name"]
        old_existence = True
        old_api_sig = check_api_existence_py(resolver_before, old_api_fqn)
        if not old_api_sig:
            old_existence = False

        for j, new_callee in enumerate(new_callees):
            new_api_fqn = new_callee["full_name"]
            new_api_sig = check_api_existence_py(resolver_after, new_api_fqn)
            new_existence = True
            if not new_api_sig:
                new_existence = False
            if reverse:
                old_api_sig_in_new = check_api_existence_py(
                    resolver_before, new_api_fqn
                )
            else:
                old_api_sig_in_new = check_api_existence_py(resolver_after, old_api_fqn)
            old_removal = False
            old_deprecated = False
            if not old_api_sig_in_new:
                old_removal = True
            else:
                old_deprecated = old_api_sig_in_new.get("deprecation", False)
            final = False
            # some old library versions do not have a wheel file
            # in these case, if old fqn is deprecated in new version
            # we consider old fqn exist in old version
            if new_existence and old_deprecated:
                final = True
            if old_existence and new_existence and old_removal:
                final = True
            res.append(
                (
                    oid,
                    i,
                    j,
                    old_existence,
                    new_existence,
                    old_removal,
                    old_deprecated,
                    final,
                )
            )
    return res


def validate(lang: str):
    if lang == "py":
        validate_per_doc = validate_per_py_doc
    elif lang == "java":
        validate_per_doc = validate_per_java_doc
    res = []
    df = pd.read_csv(f"../../benchmark/ground_truth/{lang}_ground_truth.csv")

    for _, group_df in tqdm(df.groupby("record_id")):
        res.extend(validate_per_doc(group_df))
    res = pd.DataFrame(
        res,
        columns=[
            "record_id",
            "old_index",
            "new_index",
            "old_existence",
            "new_existence",
            "old_removal",
            "old_deprecated",
            "validation",
        ],
    )
    res.to_csv(
        f"../../benchmark/ground_truth/{lang}_validation_results.csv", index=False
    )
    print(len(res))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python validation_for_eval.py",
        description="Perform post validation on ground truth dataset.",
    )
    parser.add_argument(
        "--java",
        action="store_true",
        help="validation for Java. DEFAULT: False",
    )
    parser.add_argument(
        "--python",
        action="store_true",
        help="validation for Python. DEFAULT: False",
    )
    args = parser.parse_args()

    if args.java:
        validate("java")

    if args.python:
        validate("py")
