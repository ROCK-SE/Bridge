import argparse
import json
import math
import re

import pandas as pd
from Levenshtein import ratio
from pymongo import MongoClient
from tqdm.auto import tqdm
from utils import insert_many_skip_large

client = MongoClient("127.0.0.1", 27017)
db = client["bridge"]


def split_java_identifier(identifier: str) -> list[str]:
    res = []
    for part in identifier.split("_"):
        if not part:
            continue
        res.extend(
            re.sub("([A-Z][a-z]+)", r" \1", re.sub("([A-Z]+)", r" \1", part)).split()
        )
    return [s.lower() for s in res]


def split_identifier_list(identifiers: str | list[str], splitter) -> list[str]:
    if isinstance(identifiers, str):
        return splitter(identifiers)
    res = []
    for identifier in identifiers:
        res.extend(splitter(identifier))
    return res


def split_java_class_method_names(full_api_name: str) -> tuple[list[str], str]:
    parts = full_api_name.split(".")
    for i, part in enumerate(parts):
        if not part:
            continue
        if part[0].isupper():
            break
    return parts[i:-1], parts[-1]


def java_name_similarity(parts1: list[str], parts2: list[str]) -> float:
    if parts1 == parts2:
        return 1.0

    types = [
        "int",
        "long",
        "byte",
        "short",
        "float",
        "double",
        "boolean",
        "char",
        "string",
    ]
    t1 = [k for k in parts1 if k in types]
    t2 = [k for k in parts1 if k in types]
    if t1 != t2:
        return 0.0
    total = len(parts1) + len(parts2)
    num_common_parts = 0
    for p1 in parts1:
        for p2 in parts2:
            if p1 == p2:
                num_common_parts += 1
                total -= 1
                parts2.remove(p2)
                break
            if p1.startswith(p2) or p2.startswith(p1):
                num_common_parts += 0.5
                total -= 1
                parts2.remove(p2)
                break

    return num_common_parts / total


def java_method_name_similarity(
    method_name1: str,
    method_name2: str,
    min_word_len: int = 1,
) -> float:
    # List borrowed from RepFinder
    PREPOSITION = [
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "and",
        "with",
        "as",
    ]
    parts1 = [
        word
        for word in split_java_identifier(method_name1)
        if (len(word) >= min_word_len) and (word not in PREPOSITION)
    ]
    parts2 = [
        word
        for word in split_java_identifier(method_name2)
        if (len(word) >= min_word_len) and (word not in PREPOSITION)
    ]
    if not parts1:
        return 0.0
    if not parts2:
        return 0.0
    # List borrowed from RepFinder
    VERBS = [
        "add",
        "get",
        "set",
        "is",
        "have",
        "are",
        "remove",
        "delete",
        "assert",
        "query",
        "find",
        "compare",
        "any",
        "to",
        "opt",
        "select",
        "write",
        "read",
    ]
    if (parts1[0] in VERBS) and (parts2[0] in VERBS):
        # set vs get
        if parts1[0] != parts2[0]:
            return 0.0

        # isBlack vs isNotBlank
        if (len(parts1) > 1) and (len(parts2) > 1):
            if (parts1[1] == "not") and (parts2[1] != "not"):
                return 0.0
            if (parts2[1] == "not") and (parts1[1] != "not"):
                return 0.0
            if (parts1[1] == "as") and (parts2 == "as"):
                return

        return java_name_similarity(parts1[1:], parts2[1:])

    if parts1[0] in ["get", "is"]:
        return java_name_similarity(parts1[1:], parts2)

    if parts2[0] in ["get", " is"]:
        return java_name_similarity(parts1, parts2[1:])

    return java_name_similarity(parts1, parts2)


def java_class_name_similarity(
    class_name1: list[str],
    class_name2: list[str],
    min_word_len: int = 1,
) -> float:
    parts1 = [
        word
        for word in split_identifier_list(class_name1, split_java_identifier)
        if len(word) >= min_word_len
    ]
    parts2 = [
        word
        for word in set(split_identifier_list(class_name2, split_java_identifier))
        if len(word) >= min_word_len
    ]
    return java_name_similarity(parts1, parts2)


def java_api_name_similarity(
    full_api_name1: str,
    full_api_name2: str,
    min_word_len: int = 1,
) -> tuple[float, float]:
    full_api_name1 = re.sub("[^0-9a-zA-Z_.]", "", full_api_name1)
    full_api_name2 = re.sub("[^0-9a-zA-Z_.]", "", full_api_name2)
    class_name1, method_name1 = split_java_class_method_names(full_api_name1)
    class_name2, method_name2 = split_java_class_method_names(full_api_name2)

    if class_name1 == class_name2:
        class_similarity = 1.0
    else:
        class_similarity = java_class_name_similarity(
            class_name1, class_name2, min_word_len
        )

    # Common method naming conventions that create instance of the caller class
    # Therefore, I assign them with the value of class name
    special_method_names = [
        "valueOf",
        "from",
        "of",
        "getInstance",
        "newInstance",
        "create",
    ]
    if (method_name1 in special_method_names) and (class_name1):
        method_name1 = class_name1[0]
    if (method_name2 in special_method_names) and (class_name2):
        method_name2 = class_name2[0]
    if method_name1 == method_name2:
        method_similarity = 1.0
    else:
        method_similarity = java_method_name_similarity(
            method_name1, method_name2, min_word_len
        )

    return class_similarity, method_similarity


def offset_similarity(offset1: int, offset2: int) -> float:
    dis = abs(offset1 - offset2)
    # add 1 to avoid zero division error
    return 1 / (dis + 1)


def java_arguments_similarity(arguments1: list[dict], arguments2: list[dict]) -> float:
    func = lambda arguments: [arg["value"] for arg in arguments]
    arguments1 = func(arguments1)
    arguments2 = func(arguments2)
    lensum = len(arguments1) + len(arguments2)
    if lensum == 0:
        return 0.6
    return ratio(arguments1, arguments2)


def gte(a: float, b: float, rel_tol=1e-09, abs_tol=0.0) -> bool:
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol) or (a > b)


def lte(a: float, b: float, rel_tol=1e-09, abs_tol=0.0) -> bool:
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol) or (a < b)


def java_api_call_similarity(
    api_call1: dict,
    api_call2: dict,
    weights: list[float] = [0.3, 0.3, 0.2, 0.2],
    min_word_len: int = 1,
) -> float:
    assert len(weights) == 4
    full_name1 = api_call1["full_name"]
    full_name2 = api_call2["full_name"]
    class_sim, method_sim = java_api_name_similarity(
        full_name1, full_name2, min_word_len
    )
    if class_sim < 0.25:
        return 0.0
    if method_sim < 0.25:
        return 0.0

    offset1 = api_call1["offset"]
    offset2 = api_call2["offset"]
    offset_sim = offset_similarity(offset1, offset2)
    arguments1 = api_call1["arguments"]
    arguments2 = api_call2["arguments"]
    arg_sim = java_arguments_similarity(arguments1, arguments2)

    overall_sim = (
        weights[0] * class_sim
        + weights[1] * method_sim
        + weights[2] * offset_sim
        + weights[3] * arg_sim
    )
    return overall_sim


def process_per_caller_java(
    doc: dict,
    sim_threshold: float = 0.7,
    num_neighbors: int = 3,
    weights: list[float] = [0.3, 0.3, 0.2, 0.2],
    min_word_len: int = 1,
) -> list[dict]:
    update_instances = []
    base = {k: v for k, v in doc.items() if k not in ["new_callees", "old_callees"]}
    new_callees = doc["new_callees"]
    old_callees = doc["old_callees"]
    for new_callee in new_callees:
        max_sim_score = 0
        best_candidate = None
        candidate_old_callees = sorted(
            old_callees,
            key=lambda old_callee: abs(old_callee["offset"] - new_callee["offset"]),
        )[:num_neighbors]
        for old_callee in candidate_old_callees:
            sim_score = java_api_call_similarity(
                new_callee, old_callee, weights, min_word_len
            )
            if gte(sim_score, max_sim_score):
                max_sim_score = sim_score
                best_candidate = old_callee
        if gte(max_sim_score, sim_threshold):
            update_instances.append(
                base
                | {
                    "old_callee": best_candidate,
                    "new_callee": new_callee,
                    "similarity_score": max_sim_score,
                }
            )

    return update_instances


def split_python_identifier(identifier: str) -> list[str]:
    res = []
    for part in identifier.split("_"):
        if not part:
            continue
        part = re.sub("(([0-9]+[A-Za-z])|([A-Z]+))", r" \1", part)
        part = re.sub("(([0-9]+[A-Za-z]+)|([A-Z][a-z]+))", r" \1", part)
        res.extend(part.split())
    return [s.lower() for s in res]


def python_custom_equal(p1: str, p2: str) -> bool:
    if p1 == p2:
        return True
    if p1.startswith(p2) or p2.startswith(p1):
        return True
    return False


def python_name_similarity(name1: str, name2: str, min_word_len: int = 1) -> float:
    parts1 = [
        word for word in split_python_identifier(name1) if len(word) >= min_word_len
    ]
    parts2 = [
        word for word in split_python_identifier(name2) if len(word) >= min_word_len
    ]
    if not parts1:
        return 0.0
    if not parts2:
        return 0.0

    if parts1 == parts2:
        return 1.0

    max_len = max(len(parts1), len(parts2))
    num_common_parts = 0
    for p1 in parts1:
        for p2 in parts2:
            if python_custom_equal(p1, p2):
                parts2.remove(p2)
                num_common_parts += 1
                break
    return num_common_parts / max_len


def is_compact(method_name1: str, method_name2: str) -> bool:
    name_list1 = split_python_identifier(method_name1)
    name_list2 = split_python_identifier(method_name2)
    if len(name_list1) == 1:
        if name_list1[0] == "".join(n[0] for n in name_list2):
            return True
    elif len(name_list2) == 1:
        if name_list2[0] == "".join(n[0] for n in name_list1):
            return True
    return False


def python_api_name_similarity(
    api_name1: str,
    api_name2: str,
    min_word_len: int = 1,
) -> float:
    api_parts1 = api_name1.split(".")
    api_parts2 = api_name2.split(".")
    method_name1 = api_parts1[-1]
    method_name2 = api_parts2[-1]

    norm_method_name1 = method_name1.replace("_", "").lower()
    norm_method_name2 = method_name2.replace("_", "").lower()
    # AutoTokenizer.from_pretrained BertTokenizer.from_pretrained
    if method_name1 == method_name2:
        if (len(api_parts1) > 1) and (len(api_parts2) > 1):
            if api_parts1[-2][0].isupper() and api_parts2[-2][0].isupper():
                return python_name_similarity(api_parts1[-2], api_parts2[-2])
        return 1.0
    # arg_max vs argmin
    if norm_method_name1 == norm_method_name2:
        return 1.0

    if is_compact(method_name1, method_name2):
        return 1.0

    return python_name_similarity(method_name1, method_name2, min_word_len)


def python_arguments_similarity(
    arguments1: list[dict], arguments2: list[dict]
) -> float:
    num_args1 = len(arguments1)
    num_args2 = len(arguments2)
    if (num_args1 + num_args2) == 0:
        return 1.0

    num_commons = 0

    pos_args1 = [arg["value"] for arg in arguments1 if arg["arg_type"] == "positional"]
    pos_args2 = [arg["value"] for arg in arguments2 if arg["arg_type"] == "positional"]
    for i in range(min(len(pos_args1), len(pos_args2))):
        if pos_args1[i] == pos_args2[i]:
            num_commons += 1

    star_pos1 = [arg["value"] for arg in arguments1 if arg["arg_type"] == "*positional"]
    star_pos2 = [arg["value"] for arg in arguments2 if arg["arg_type"] == "*positional"]
    num_commons += len(set(star_pos1).intersection(star_pos2))

    star_kw1 = [arg["value"] for arg in arguments1 if arg["arg_type"] == "**keyword"]
    star_kw2 = [arg["value"] for arg in arguments2 if arg["arg_type"] == "**keyword"]
    num_commons += len(set(star_kw1).intersection(star_kw2))

    kw_args1 = {
        arg["key"]: arg["value"] for arg in arguments1 if arg["arg_type"] == "keyword"
    }
    kw_args2 = {
        arg["key"]: arg["value"] for arg in arguments2 if arg["arg_type"] == "keyword"
    }
    for k, v1 in kw_args1.items():
        v2 = kw_args2.get(k)
        if v2:
            num_commons += 0.5
        if v1 == v2:
            num_commons += 0.5

    num_commons2 = 0
    arg_values1 = [arg["value"] for arg in arguments1]
    arg_values2 = [arg["value"] for arg in arguments2]
    for i in range(min(num_args1, num_args2)):
        if arg_values1[i] == arg_values2[i]:
            num_commons2 += 1

    return max(num_commons, num_commons2) / (num_args1 + num_args2 - num_commons)


def python_api_call_similarity(
    api_call1: dict,
    api_call2: dict,
    weights: list[float] = [0.5, 0.3, 0.2],
    min_word_len: int = 1,
) -> float:
    assert len(weights) == 3
    full_name1 = api_call1["full_name"]
    full_name2 = api_call2["full_name"]
    name_sim = python_api_name_similarity(full_name1, full_name2, min_word_len)
    if not gte(name_sim, 0.5):
        return 0.0

    offset1 = api_call1["offset"]
    offset2 = api_call2["offset"]
    offset_sim = offset_similarity(offset1, offset2)
    arguments1 = api_call1["arguments"]
    arguments2 = api_call2["arguments"]
    arg_sim = python_arguments_similarity(arguments1, arguments2)

    # print(name_sim, arg_sim, offset_sim)
    overall_sim = weights[0] * name_sim + weights[1] * arg_sim + weights[2] * offset_sim

    return overall_sim


def process_per_caller_python(
    doc: dict,
    sim_threshold: float = 0.7,
    num_neighbors: int = 3,
    weights: list[float] = [0.5, 0.3, 0.2],
    min_word_len: int = 1,
):
    update_instances = []
    base = {k: v for k, v in doc.items() if k not in ["new_callees", "old_callees"]}
    new_callees = doc["new_callees"]
    old_callees = doc["old_callees"]
    for new_callee in new_callees:
        max_sim_score = 0
        best_candidate = None
        candidate_old_callees = sorted(
            old_callees,
            key=lambda old_callee: abs(old_callee["offset"] - new_callee["offset"]),
        )[:num_neighbors]
        for old_callee in candidate_old_callees:
            sim_score = python_api_call_similarity(
                new_callee, old_callee, weights, min_word_len
            )
            if gte(sim_score, max_sim_score):
                max_sim_score = sim_score
                best_candidate = old_callee
        if gte(max_sim_score, sim_threshold):
            update_instances.append(
                base
                | {
                    "old_callee": best_candidate,
                    "new_callee": new_callee,
                    "similarity_score": max_sim_score,
                }
            )
    return update_instances


def main(lang: str):
    api_call_changes_col = db[f"{lang}_api_call_changes"]
    num_docs = api_call_changes_col.estimated_document_count()

    if lang == "java":
        processor = process_per_caller_java
    elif lang == "py":
        processor = process_per_caller_python
    print(f"{lang}: {num_docs} api call change records")
    res = []
    for doc in tqdm(
        api_call_changes_col.find({}, projection={"_id": 0}),
        total=num_docs,
    ):
        res.extend(processor(doc))

    print(f"{lang}: identify {len(res)} update instances")
    update_instance_col = db[f"{lang}_update_instances"]
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
        help="mine Java update instances",
    )
    parser.add_argument(
        "--python",
        action="store_true",
        help="mine Python update instances",
    )
    args = parser.parse_args()

    if args.java:
        main("java")

    if args.python:
        main("py")
