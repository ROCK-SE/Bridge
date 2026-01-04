from argparse import ArgumentParser

import pandas as pd
from pymongo import MongoClient
from tqdm import tqdm
from utils import insert_many_skip_large

client = MongoClient("127.0.0.1", 27017)
db = client["bridge"]

config_files = [
    "pom.xml",
    "requirements.txt",
    "setup.py",
    "pyproject.toml",
    "setup.cfg",
]


def dump(datafix: str):
    py_col = db[f"py_{datafix}_commits"]
    java_col = db[f"java_{datafix}_commits"]
    py_col.drop()
    java_col.drop()

    for f in config_files[1:]:
        with pd.read_csv(
            f"../../benchmark/Phase1/{f}_{datafix}_commits.csv",
            low_memory=False,
            keep_default_na=False,
            chunksize=100000,
        ) as reader:
            for chunk in tqdm(reader):
                insert_many_skip_large(py_col, chunk.to_dict("records"))
    py_col.create_index("commit")

    with pd.read_csv(
        f"../../benchmark/Phase1/{config_files[0]}_{datafix}_commits.csv",
        low_memory=False,
        keep_default_na=False,
        chunksize=100000,
    ) as reader:
        for chunk in tqdm(reader):
            insert_many_skip_large(java_col, chunk.to_dict("records"))
    java_col.create_index("commit")


def merge_update_commits(lang: str):
    bumping_col = db[f"{lang}_version_bumping_commits"]
    update_col = db[f"{lang}_update_commits"]
    tmp_col = db[f"{lang}_tmp"]

    update_commits = list(
        pd.DataFrame(update_col.find({}, projection={"_id": 0, "commit": 1}))[
            "commit"
        ].unique()
    )

    data = []
    for commit in tqdm(update_commits):
        code_file_changes = []
        for doc in update_col.find({"commit": commit}):
            code_file_changes.append(
                {
                    "filepath": doc["filepath"],
                    "new_blob": doc["new_blob"],
                    "old_blob": doc["old_blob"],
                }
            )
        cfg_file_changes = {}
        for doc in bumping_col.find({"commit": commit}):
            filepath = doc["filepath"]
            cfg_file_changes.setdefault(filepath, [])
            cfg_file_changes[filepath].append(
                {
                    "package": doc["package"],
                    "version_before": doc["version_before"],
                    "version_after": doc["version_after"],
                }
            )
        cfg_file_changes = [
            {"filepath": k, "dependency_changes": v}
            for k, v in cfg_file_changes.items()
        ]
        data.append(
            {
                "commit": commit,
                "configuration_files": cfg_file_changes,
                "code_files": code_file_changes,
            }
        )
        if len(data) == 10000:
            insert_many_skip_large(tmp_col, data)
            data = []
    insert_many_skip_large(tmp_col, data)

    update_col.drop()
    tmp_col.rename(f"{lang}_update_commits")


if __name__ == "__main__":
    parser = ArgumentParser(
        prog="python dump_data.py",
        description="Dump data files to the `bridge` MongoDB database",
    )
    parser.add_argument(
        "-c",
        "--candidate",
        action="store_true",
        help="dump candidate update commits to java/py_candidate_update_commits collection",
    )
    parser.add_argument(
        "-b",
        "--bumping",
        action="store_true",
        help="dump version bumping commits to java/py_version_bumping_commits collection",
    )
    parser.add_argument(
        "-n",
        "--nonfixed",
        action="store_true",
        help="dump nonfixed version bumping commits to java/py_nonfixed_version_bumping_commits collection",
    )
    parser.add_argument(
        "-u",
        "--update",
        action="store_true",
        help="dump update commits to java/py_update_commits collection",
    )
    args = parser.parse_args()

    if args.candidate:
        dump("candidate_update")

    if args.bumping:
        dump("version_bumping")

    if args.nonfixed:
        dump("nonfixed_version_bumping")

    if args.update:
        dump("update")
        merge_update_commits("py")
        merge_update_commits("java")
