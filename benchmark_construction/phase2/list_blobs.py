import json
import math
import os

from joblib import Parallel, delayed
from pymongo import MongoClient
from tqdm import tqdm, trange
from utils import insert_many_skip_large


def get_all_blobs(lang: str):
    client = MongoClient("127.0.0.1", 27017)
    db = client["bridge"]
    col = db[f"{lang}_update_commits"]
    blobs = set()
    for doc in tqdm(
        col.find({}, projection={"_id": 0}),
        total=col.estimated_document_count(),
    ):
        for fbb in doc["code_files"]:
            blobs.add(fbb["new_blob"])
            blobs.add(fbb["old_blob"])
    print(len(blobs), f"unique {lang} blobs")

    sections = {i: [] for i in range(128)}
    for b in tqdm(blobs):
        i = int(b[:2], base=16) % 128
        sections[i].append(b)

    for i in range(128):
        with open(f"../../benchmark/phase2/{lang}_blob.{i}", "w") as outf:
            sections[i].sort()
            for b in sections[i]:
                outf.write(f"{b}\n")


if __name__ == "__main__":
    get_all_blobs("py")
    get_all_blobs("java")
