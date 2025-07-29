import json

import pandas as pd
from pymongo import MongoClient
from tqdm.auto import tqdm, trange
from utils import insert_many_skip_large

client = MongoClient("127.0.0.1", 27017)
db = client["api_update"]
tqdm.pandas()


def merge_packages(df):
    res = []
    for row in df.itertuples(index=False):
        res.append(
            {
                "name": row[0],
                "version_before": row[1],
                "version_after": row[2],
                "update_type": row[3],
            }
        )
    return res


def merge_files(df):
    res = []
    for row in df.itertuples(index=False):
        res.append({"filepath": row[0], "new_blob": row[1], "old_blob": row[2]})
    return res


def dump_dependency_updates():
    df = pd.read_csv(
        "../benchmark/updates/c2fpkgvvtype.csv", low_memory=False, keep_default_na=False
    )
    df.loc[:, "filepath"] = df["filepath"].str.strip("/")

    for lang in ["py", "java"]:
        if lang == "py":
            info = df[df["config file"] != "pom.xml"]
        else:
            info = df[df["config file"] == "pom.xml"]
        print(f"Before: {len(info)} {lang} records")
        pkg_with_imports = json.load(open(f"../benchmark/updates/{lang}_imports.json"))
        print(f"{lang}: {len(pkg_with_imports)} packages have importable modules")
        info = info[info["package"].isin(pkg_with_imports.keys())]
        print(f"After: {len(info)} {lang} records")
        info = (
            info.groupby(["commit", "filepath"])[
                [
                    "package",
                    "version before",
                    "version after",
                    "update type",
                ]
            ]
            .progress_apply(merge_packages)
            .reset_index(name="updated_packages")
        )
        print(f"{lang}: {len(info)} {lang} commit updates")
        db.drop_collection(f"{lang}_dependency_updates")
        col = db[f"{lang}_dependency_updates"]
        batch_size = 50000
        for i in trange(0, len(info), batch_size):
            batch = info.iloc[i : i + batch_size].to_dict("records")
            col.insert_many(batch)
        col.create_index("commit")
        col.create_index("updated_packages.name")


def dump_blob_changes():
    c2fbb = pd.read_csv(
        "../benchmark/updates/c2fbb",
        sep=";",
        names=["commit", "filepath", "new_blob", "old_blob"],
        low_memory=False,
        keep_default_na=False,
    )
    print(f"Before merge: {len(c2fbb)} c2fbb records")
    c2fbb = (
        c2fbb.groupby(["commit"])[["filepath", "new_blob", "old_blob"]]
        .progress_apply(merge_files)
        .reset_index(name="blob_changes")
    )
    print(f"After merge: {len(c2fbb)} commits")
    db.drop_collection(f"blob_changes")
    col = db["blob_changes"]
    batch_size = 50000
    for i in trange(0, len(c2fbb), batch_size):
        batch = c2fbb.iloc[i : i + batch_size].to_dict("records")
        error_docs = insert_many_skip_large(col, batch)
        for doc in error_docs:
            print(doc["commit"])
    col.create_index("commit")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python dump_data.py",
        description="Dump dependency update info and blob change info for commits and api call info for modified blobs to MongoDB.",
    )
    parser.add_argument(
        "-d",
        "--dependency_updates",
        action="store_true",
        help="dump dependency update info for commits",
    )
    parser.add_argument(
        "-b",
        "--blob_changes",
        action="store_true",
        help="dump blob change info for commits",
    )
    args = parser.parse_args()

    if args.dependency_updates:
        dump_dependency_updates()
    if args.blob_changes:
        dump_blob_changes()
