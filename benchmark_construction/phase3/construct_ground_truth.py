import math
import os

import pandas as pd
from api_call_similarity import (
    java_similarity_metrics,
    python_similarity_metrics,
)
from bson import ObjectId
from pymongo import MongoClient
from tqdm import tqdm

client = MongoClient("127.0.0.1", 27017)
db = client["bridge"]
java_api_call_changes = db["java_api_call_changes"]
py_api_call_changes = db["py_api_call_changes"]


def sample_records(df):
    res = []
    existing_old_old_fqns = set()
    for row in df.sample(frac=1, random_state=42).itertuples(index=False):
        fqns = set()
        for old_callee in row.old_callees:
            fqns.add(old_callee["full_name"])
        if fqns.issubset(existing_old_old_fqns):
            continue
        existing_old_old_fqns |= fqns
        res.append([row[0], row.library, row.version_before, row.version_after])
        if len(existing_old_old_fqns) >= 10:
            break
    return res


def sample(lang: str):
    data = []
    col = db[f"{lang}_api_call_changes"]
    for doc in tqdm(col.find({}), total=col.estimated_document_count()):
        version_before = doc["version_before"]
        version_after = doc["version_after"]
        parts_before = [int(_) for _ in version_before.split(".")]
        parts_after = [int(_) for _ in version_after.split(".")]
        if parts_before > parts_after:
            data.append(
                [
                    str(doc["_id"]),
                    doc["commit"],
                    doc["library"],
                    version_before,
                    version_after,
                    doc["new_callees"],
                    doc["old_callees"],
                ]
            )
        else:
            data.append(
                [
                    str(doc["_id"]),
                    doc["commit"],
                    doc["library"],
                    version_before,
                    version_after,
                    doc["old_callees"],
                    doc["new_callees"],
                ]
            )

    df = pd.DataFrame(
        data,
        columns=[
            "_id",
            "commit",
            "library",
            "version_before",
            "version_after",
            "old_callees",
            "new_callees",
        ],
    )
    df = df[df["old_callees"].str.len() * df["new_callees"].str.len() <= 25]
    count = df.groupby("library")["commit"].nunique()
    sampled_libraries = count.sample(n=100, weights=count.values, random_state=42).index
    record_samples = []
    for lib in sampled_libraries:
        record_samples.extend(sample_records(df[df["library"] == lib]))
    print(f"{lang}: {len(record_samples)} sampled records")
    pd.DataFrame(
        record_samples, columns=["_id", "library", "version_before", "version_after"]
    ).to_csv(f"../../benchmark/ground_truth/{lang}_record_samples.csv", index=False)


def check_annotated_data(lang: str, col):
    df = pd.read_excel(f"../../benchmark/ground_truth/{lang}_record_samples.xlsx")
    for row in df[df["index_before"].notna()].itertuples(index=False):
        objid = ObjectId(row[0])
        doc = col.find_one({"_id": objid})
        if row[1] != doc["library"]:
            print(row[0], "library")
        if row[2] != doc["version_before"]:
            print(row[0], "version_before")
        if row[3] != doc["version_after"]:
            print(row[0], "version_after")
        if int(row[4]) > len(doc["old_callees"]):
            print(row[0], "old callees")
        if int(row[5]) > len(doc["new_callees"]):
            print(row[0], "new callees")
        parts_before = [int(_) for _ in row[2].split(".")]
        parts_after = [int(_) for _ in row[3].split(".")]
        # commons-io:commons-io case
        if parts_before[0] == 20030203:
            parts_before[0] = -20030203
        if parts_after[0] == 20030203:
            parts_after[0] = -20030203
        if parts_before > parts_after:
            api_before = row[7].split("(")[0]
            api_after = row[6].split("(")[0]
        else:
            api_before = row[6].split("(")[0]
            api_after = row[7].split("(")[0]
        if api_before != doc["old_callees"][int(row[4])]["full_name"]:
            print(row[0], "api before")
        if api_after != doc["new_callees"][int(row[5])]["full_name"]:
            print(row[0], "api after")


def java_api_call_text(callee):
    full_name = callee["full_name"]
    arguments = ", ".join([a["value"] for a in callee["arguments"]])
    return f"{full_name}({arguments})"


def python_api_call_text(callee):
    full_name = callee["full_name"]
    arguments = []
    for arg in callee["arguments"]:
        if "key" in arg:
            arguments.append(arg["key"] + "=" + arg["value"])
        else:
            arguments.append(arg["value"])
    return f"{full_name}({', '.join(arguments)})"


def process_single_doc(
    idx: str,
    index_pairs: list[tuple[int, int]],
    lang: str,
    min_word_len: int = 1,
):
    if lang == "py":
        col = py_api_call_changes
        similarity_metrics = python_similarity_metrics
    if lang == "java":
        col = java_api_call_changes
        similarity_metrics = java_similarity_metrics
    doc = col.find_one({"_id": ObjectId(idx)})

    old_callees, new_callees = doc["old_callees"], doc["new_callees"]
    res = [[None for _ in range(len(new_callees))] for _ in range(len(old_callees))]

    for i, old_callee in enumerate(old_callees):
        for j, new_callee in enumerate(new_callees):
            metric_scores = similarity_metrics(old_callee, new_callee, min_word_len)
            # old_api_call = api_call_text(old_callee)
            # new_api_call = api_call_text(new_callee)
            # old_offset = old_callee["offset"]
            # new_offset = new_callee["offset"]
            res[i][j] = [idx, i, j] + metric_scores + [0]
            if (i, j) in index_pairs:
                res[i][j][-1] = 1
    return [x for xs in res for x in xs]


def calculate_metric_values(lang: str):
    df = pd.read_excel(f"../../benchmark/ground_truth/{lang}_record_samples.xlsx")
    id_index_pairs = {}
    for row in df.itertuples(index=False):
        id_index_pairs.setdefault(row[0], [])
        if math.isnan(row[4]):
            continue
        id_index_pairs[row[0]].append((int(row[4]), int(row[5])))

    res = []
    for idx, index_pairs in id_index_pairs.items():
        try:
            res.extend(process_single_doc(idx, index_pairs, lang))
        except:
            print(idx)
            return
    return res


if __name__ == "__main__":
    sample("java")
    sample("py")

    if os.path.exists(f"../../benchmark/ground_truth/java_record_samples.xlsx"):
        check_annotated_data("java", java_api_call_changes)
        data = calculate_metric_values("java")
        df = pd.DataFrame(
            data,
            columns=[
                "record_id",
                "old_index",
                "new_index",
                "class_sim",
                "method_sim",
                "arg_sim",
                "label",
            ],
        )
        df.to_csv("../../benchmark/ground_truth/java_ground_truth.csv", index=False)
        print(len(df), len(df[df["label"] == 1]))

    if os.path.exists(f"../../benchmark/ground_truth/py_record_samples.xlsx"):
        check_annotated_data("py", py_api_call_changes)
        data = calculate_metric_values("py")
        df = pd.DataFrame(
            data,
            columns=[
                "record_id",
                "old_index",
                "new_index",
                "fqn_sim",
                "arg_sim",
                "label",
            ],
        )
        df.to_csv("../../benchmark/ground_truth/py_ground_truth.csv", index=False)
        print(len(df), len(df[df["label"] == 1]))
