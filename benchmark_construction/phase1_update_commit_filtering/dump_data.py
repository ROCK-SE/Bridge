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


def dump(datafix: str, drop: bool = False):
    py_col = db[f"py_{datafix}_commits"]
    java_col = db[f"java_{datafix}_commits"]
    if drop:
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
    parser.add_argument(
        "--drop",
        default=False,
        action="store_true",
        help="drop existing collection",
    )
    args = parser.parse_args()

    if args.candidate:
        dump("candidate_update", args.drop)

    if args.bumping:
        dump("version_bumping", args.drop)

    if args.nonfixed:
        dump("nonfixed_version_bumping", args.drop)

    if args.update:
        dump("update", args.drop)
