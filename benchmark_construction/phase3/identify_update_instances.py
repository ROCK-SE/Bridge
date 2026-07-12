import argparse

from api_call_similarity import similarity_score
from pymongo import MongoClient
from tqdm.auto import tqdm
from utils import insert_many_skip_large

client = MongoClient("127.0.0.1", 27017)
db = client["bridge"]


DEFAULT_PARAMS = {
    "py": {"thresh": 0.35, "weights": [0.5, 0.5]},
    "java": {"thresh": 0.45, "weights": [1 / 3, 1 / 3, 1 / 3]},
}


def greedy_match(scores: list[tuple[int, int, float]], thresh: float):
    matched_pairs, used_old, used_new = list(), set(), set()
    scores = sorted(scores, key=lambda s: (-s[2], s[0], abs(s[0] - s[1])))
    for oid, nid, s in scores:
        if (oid in used_old) or (nid in used_new):
            continue
        if s <= thresh:
            break
        if s > thresh:
            matched_pairs.append((oid, nid, s))
            used_old.add(oid)
            used_new.add(nid)

    return matched_pairs


def process_per_doc(
    lang: str,
    doc: dict,
    thresh: float,
    weights: list[float],
    min_word_len: int = 1,
) -> list[dict]:
    old_callees, new_callees = doc["old_callees"], doc["new_callees"]

    scores = []
    for i, old_callee in enumerate(old_callees):
        for j, new_callee in enumerate(new_callees):
            if i - j >= 10:
                continue
            if j - i >= 10:
                break
            score = similarity_score(
                lang, old_callee, new_callee, weights, min_word_len
            )
            if score <= thresh:
                continue
            scores.append((i, j, score))
    matched_pairs = greedy_match(scores, thresh)

    update_instances = []
    base = {k: v for k, v in doc.items() if k not in ["new_callees", "old_callees"]}
    for oid, nid, score in matched_pairs:
        # print(oid, nid)
        pair_info = {
            "old_callee": old_callees[oid],
            "new_callee": new_callees[nid],
            "similarity_score": score,
        }
        update_instances.append(base | pair_info)

    return update_instances


def main(lang: str):
    hyperparams = DEFAULT_PARAMS.get(lang)
    thresh = hyperparams.get("thresh")
    weights = hyperparams.get("weights")
    print(f"{lang}: {weights=}, {thresh=}")

    api_call_changes_col = db[f"{lang}_api_call_changes"]
    num_docs = api_call_changes_col.estimated_document_count()
    print(f"{lang}: {num_docs} api call change records")
    res = []
    for doc in tqdm(
        api_call_changes_col.find({}, projection={"_id": 0}),
        total=num_docs,
    ):
        res.extend(process_per_doc(lang, doc, thresh, weights))

    print(f"{lang}: identify {len(res)} candidate update instances")
    update_instance_col = db[f"{lang}_candidate_update_instances"]
    update_instance_col.drop()
    insert_many_skip_large(update_instance_col, res)
    update_instance_col.create_index("commit")
    update_instance_col.create_index("library")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python identify_update_instances.py",
        description="Mine update instances based on the API call changes between the new and old blobs.",
    )
    parser.add_argument(
        "--java",
        action="store_true",
        help="mine Java update instances. DEFAULT: False",
    )
    parser.add_argument(
        "--python",
        action="store_true",
        help="mine Python update instances. DEFAULT: False",
    )
    args = parser.parse_args()

    if args.java:
        main("java")

    if args.python:
        main("py")
