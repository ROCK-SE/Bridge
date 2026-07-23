import hashlib
import json
import os
import random

import pandas as pd
from call_context_extraction import (
    extract_call_context_java,
    extract_call_context_python,
    read_blob,
)
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


def obtain_all_sigs(lang: str):
    signature_file = f"../benchmark/llm_evaluation/{lang}_signature_level.jsonl"
    if not os.path.exists(signature_file):
        signature_level_dataset(lang)

    signatures = []
    with open(signature_file) as inf:
        for line in inf:
            row = json.loads(line.strip())
            signatures.append(row)
    return signatures


def obtain_all_instances(lang: str):
    col = db[f"java_candidate_update_instances"]
    if lang == "python":
        col = db[f"py_candidate_update_instances"]

    instances = {}
    for doc in col.find({"validation": True}):
        version_before = doc["version_before"]
        version_after = doc["version_after"]
        old_callee = doc["old_callee"]
        new_callee = doc["new_callee"]
        old_blob = doc["old_blob"]
        new_blob = doc["new_blob"]
        old_api = old_callee["full_name"]
        new_api = new_callee["full_name"]
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
            old_callee, new_callee = new_callee, old_callee
            old_blob, new_blob = new_blob, old_blob

        key = (doc["library"], old_version, new_version, legacy_api, replacement_api)
        instances.setdefault(key, []).append(
            {
                "instance_id": str(doc["_id"]),
                "library": doc["library"],
                "old_version": old_version,
                "new_version": new_version,
                "legacy_api": legacy_api,
                "reference_replacement": replacement_api,
                "commit": doc["commit"],
                "filepath": doc["filepath"],
                "old_blob": old_blob,
                "new_blob": new_blob,
                "caller": doc["caller"],
                "old_callee": old_callee,
                "new_callee": new_callee,
            }
        )
    return instances


def sample_instances(instances, signatures):
    sampled_instances = []
    rng = random.Random(42)
    for sig in signatures:
        key = tuple(
            (
                sig["library"],
                sig["old_version"],
                sig["new_version"],
                sig["legacy_api"],
                sig["reference_replacement"],
            )
        )
        try:
            sampled_instance = rng.sample(instances[key], 1)[0]
        except:
            print(key)
            continue
        data = {
            "query_id": sig["query_id"],
            "language": sig["language"],
            **sampled_instance,
        }
        sampled_instances.append(data)
    return sampled_instances


def context_level_dataset(lang: str):
    signatures = obtain_all_sigs(lang)
    instances = obtain_all_instances(lang)
    instance_samples = sample_instances(instances, signatures)

    output_path = f"../benchmark/llm_evaluation/{lang}_context_level.jsonl"
    outf = open(output_path, "w")
    if lang == "python":
        call_context_extractor = extract_call_context_python
    elif lang == "java":
        call_context_extractor = extract_call_context_java
    res = []
    for ins in instance_samples:
        old_blob = ins["old_blob"]
        source = read_blob(old_blob)
        context = call_context_extractor(source, ins["caller"], ins["old_callee"])
        if context == "":
            print(ins["instance_id"], old_blob, ins["caller"], ins["old_callee"])
        record = dict(
            query_id=ins["query_id"],
            instance_id=ins["instance_id"],
            language=ins["language"],
            library=ins["library"],
            old_version=ins["old_version"],
            new_version=ins["new_version"],
            legacy_api=ins["legacy_api"],
            reference_replacement=ins["reference_replacement"],
            context=context,
            commit=ins["commit"],
            filepath=ins["filepath"],
            source_blob=ins["old_blob"],
            caller=ins["caller"],
        )
        outf.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        res.append(record)
    outf.close()
    return res


if __name__ == "__main__":
    # signature_level_dataset("java")
    # signature_level_dataset("python")
    context_level_dataset("python")
    context_level_dataset("java")
