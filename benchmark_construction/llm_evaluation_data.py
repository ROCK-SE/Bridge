import hashlib
import json

import pandas as pd
from pymongo import MongoClient

client = MongoClient("127.0.0.1", 27017)
db = client["bridge"]


def signature_level_dataset(lang: str):
    col = db[f"java_candidate_update_instances"]
    if lang == "python":
        col = db[f"py_candidate_update_instances"]
    data = {}
    for doc in col.find({"validation": True}):
        library = doc["library"]

        version_before = doc["version_before"]
        version_after = doc["version_after"]
        old_api = doc["old_callee"]["full_name"]
        new_api = doc["new_callee"]["full_name"]
        if lang == "java":
            old_api = f"{old_api}({','.join(doc['most_prob_old_param_types'])})"
            new_api = f"{new_api}({','.join(doc['most_prob_new_param_types'])})"
        old_version, new_version = version_before, version_after
        legacy_api, replacement_api = old_api, new_api

        parts1 = [int(_) for _ in version_before.split(".")]
        parts2 = [int(_) for _ in version_after.split(".")]
        if parts1 > parts2:
            old_version, new_version = version_after, version_before
            legacy_api, replacement_api = new_api, old_api

        key = (library, old_version, new_version, legacy_api)
        data.setdefault(key, dict())
        data[key][replacement_api] = data[key].get(replacement_api, 0) + 1

    query_wo_majority = 0
    outf = open(f"../benchmark/llm_evaluation/{lang}_update_pairs.jsonl", "w")
    records = []
    for k, replacements in data.items():
        query_id = hashlib.sha256(",".join(k).encode("utf-8")).hexdigest()[:20]
        replacements = sorted(replacements.items(), key=lambda x: x[1], reverse=True)
        highest_frequency = replacements[0][1]
        total_frequency = sum(f[1] for f in replacements)
        if highest_frequency * 2 <= total_frequency:
            query_wo_majority += 1
            continue
        record = dict(
            query_id=query_id,
            language=lang,
            library=k[0],
            old_version=k[1],
            new_version=k[2],
            legacy_api=k[3],
            reference_replacement=replacements[0][0],
            instances=replacements[0][1],
        )
        records.append(record)
        outf.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(
        f"{lang}: {len(data)} queries, exclude {query_wo_majority} without a strict replacement API"
    )
    outf.close()
    records = pd.DataFrame(records)
    samples = records.groupby(
        ["library", "legacy_api", "reference_replacement"]
    ).sample(1, random_state=42)
    with open(f"../benchmark/llm_evaluation/{lang}_signature_level.jsonl", "w") as f:
        for s in samples.to_dict("records"):
            f.write(json.dumps(s, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    signature_level_dataset("java")
    signature_level_dataset("python")
