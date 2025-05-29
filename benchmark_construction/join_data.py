import glob
import json
import os

import pandas as pd
import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection
from tqdm.auto import tqdm

client = MongoClient("127.0.0.1", 27017)
db = client["api_update"]
tqdm.pandas()


def join_data():
    py_imports = json.load(open("../benchmark/updates/py_imports.json"))
    java_imports = json.load(open("../benchmark/updates/java_imports.json"))

    df = pd.read_csv(
        "../benchmark/updates/c2fpkgvvtype.csv",
        low_memory=False,
        keep_default_na=False,
        usecols=["commit", "filepath", "package", "config file"],
    )
    py_info = df[df["config file"] != "pom.xml"]
    java_info = df[df["config file"] == "pom.xml"]
    print(f"Before: {len(py_info)} Python records, {len(java_info)} Java records")
    py_info = py_info[py_info["package"].isin(py_imports.keys())]
    java_info = java_info[java_info["package"].isin(java_imports.keys())]
    print(f"After: {len(py_info)} Python records, {len(java_info)} Java records")

    nearby_commits = {}
    with open("../benchmark/updates/c.pc.ppc.cc.ccc") as f:
        for line in tqdm(f):
            entries = line.strip("\n").split(";")
            nearby_commits[entries[0]] = [c for c in entries[1:] if c]
    print(f"{len(nearby_commits)} neary commits")

    c2fbb = {}
    with open("../benchmark/updates/c2fbb") as f:
        for line in tqdm(f):
            c, f, nb, ob = line.strip("\n").split(";")
            c2fbb[c] = c2fbb.get(c, [])
            c2fbb[c].append((f, nb, ob))
    print(f"{len(c2fbb)} c2fbb")

    def join_func(df):
        packages = list(set(df["package"]))
        commit, filepath = df.iloc[0]["commit"], df.iloc[0]["filepath"]
        filepath = filepath.strip("/")
        blob_pairs = []
        for c in nearby_commits.get(commit, []):
            for f, b, ob in c2fbb.get(c, []):
                f = f.strip("/")
                common_path = os.path.commonpath([filepath, f])
                if (common_path == os.path.dirname(filepath)) or (
                    common_path == filepath
                ):
                    blob_pairs.append((f, b, ob))
        if blob_pairs:
            return {
                "commit": commit,
                "filepath": filepath,
                "packages": packages,
                "blob_pairs": blob_pairs,
            }

    py_res = py_info.groupby(["commit", "filepath"])[
        ["commit", "filepath", "package"]
    ].progress_apply(join_func)
    py_res = list(py_res[py_res.notna()].values)
    print(f"{len(py_res)} Python records")
    db.drop_collection("py_update_blobs")
    py_col = db["py_update_blobs"]
    for i in range(0, len(py_res), 10000):
        py_col.insert_many(py_res[i : i + 10000])
    py_col.create_index("packages")
    py_col.create_index("commit")

    java_res = java_info.groupby(["commit", "filepath"])[
        ["commit", "filepath", "package"]
    ].progress_apply(join_func)
    java_res = list(java_res[java_res.notna()].values)
    print(f"{len(java_res)} Java records")

    db.drop_collection("java_update_blobs")

    java_col = db["java_update_blobs"]

    for i in range(0, len(java_res), 10000):
        java_col.insert_many(java_res[i : i + 10000])
    java_col.create_index("packages")
    java_col.create_index("commit")


def insert_many_skip_large(col: Collection, documents: list[dict]):
    error_docs = []
    try:
        col.insert_many(documents, ordered=False)
    except Exception as e:
        for doc in documents:
            try:
                col.insert_one(doc)
            except pymongo.errors.DuplicateKeyError as e:
                pass
            except Exception as e:
                error_docs.append(doc)
    return error_docs


def dump_api_call():
    for lang in ["py", "java"]:
        col_name = f"{lang}_api_calls"
        db.drop_collection(col_name)
        api_calls_col = db[col_name]
        path = f"../benchmark/updates/{lang}blob_api_calls.json.*"
        for fn in tqdm(glob.glob(path), desc=lang):
            with open(fn) as f:
                res = []
                for blob_sha, values in json.load(f).items():
                    modules = values[0]
                    api_calls = values[1]
                    tmp = []
                    if isinstance(api_calls, dict):
                        api_calls = api_calls.items()
                    for caller, callee in api_calls:
                        tmp.append({"caller": caller, "callee": callee})
                    res.append(
                        {
                            "blob_sha": blob_sha,
                            "modules": modules,
                            "api_calls": tmp,
                        }
                    )
                error_docs = insert_many_skip_large(api_calls_col, res)
                for doc in error_docs:
                    print(fn.split(".")[-1], doc["blob_sha"])
        api_calls_col.create_index("blob_sha")


if __name__ == "__main__":
    # join_data()
    dump_api_call()
