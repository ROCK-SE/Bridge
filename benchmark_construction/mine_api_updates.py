import argparse
import json
import math

from joblib import Parallel, delayed
from Levenshtein import distance, ratio
from pymongo import MongoClient
from pymongo.collection import Collection
from tqdm.auto import tqdm

py_imports = json.load(open("../benchmark/updates/py_imports.json"))
java_imports = json.load(open("../benchmark/updates/java_imports.json"))


def check_imports(
    import_modules: list[str], package_imports: dict[str, list[str]]
) -> dict[str, list[str]]:
    res = {}
    if not import_modules:
        return res
    for package, imports in package_imports.items():
        for i in imports:
            for im in import_modules:
                if (im.startswith(f"{i}.")) or (im == i):
                    res[package] = res.get(package, [])
                    res[package].append(im)
    return res


def filter_relevant_api_calls(
    api_calls: list[dict], modules: list[str]
) -> dict[str | tuple[str], list[list]]:
    res = {}
    for call_pair in api_calls:
        caller = call_pair["caller"]
        if isinstance(caller, list):
            caller = tuple(caller)
        callees = call_pair["callee"]
        for api, line_no, params in callees:
            if any(
                api.startswith(f"{module}.") or (api == module) for module in modules
            ):
                res[caller] = res.get(caller, [])
                res[caller].append([api, line_no, params])
    return res


def candidate_update_instances(
    new_api_calls: list, old_api_calls: list, line_range: int = 2
) -> list:
    update_instance_candidates = []
    new_lineno_apicalls = {}
    for api, line_no, params in new_api_calls:
        new_lineno_apicalls[line_no] = new_lineno_apicalls.get(line_no, [])
        new_lineno_apicalls[line_no].append((api, params))

    for old_api, old_lineno, old_params in old_api_calls:
        tmp = []
        old_parts = old_api.split(".")
        old_method_name, old_call_chain = old_parts[-1], old_parts[:-1]
        old_params2 = [p for p in old_params if not p.startswith("#")]
        is_break = False
        for i in range(-line_range, line_range + 1):
            new_lineno = old_lineno + i
            new_api_params = new_lineno_apicalls.get(new_lineno)
            if new_api_params is None:
                continue
            for new_api, new_params in new_api_params:
                new_params2 = [p for p in new_params if not p.startswith("#")]
                # param_ratio = ratio(old_params, new_params)
                new_parts = new_api.split(".")
                new_method_name, new_call_chain = new_parts[-1], new_parts[:-1]
                method_name_dis = 1 - ratio(old_method_name, new_method_name)
                call_chain_dis = 1 - ratio(old_call_chain, new_call_chain)
                tmp.append(
                    (
                        new_api,
                        new_params,
                        new_lineno,
                        method_name_dis,
                        call_chain_dis,
                        # param_distance,
                        abs(i),
                    )
                )
        if tmp:
            best_candidate = sorted(tmp, key=lambda x: x[3:])[0]
            new_api, new_params = best_candidate[:2]
            if ("(" in old_api) or ("(") in new_api:
                continue
            if ("[" in old_api) or ("[") in new_api:
                continue
            if old_api == new_api:
                continue
            update_instance_candidates.append(
                (old_api, old_params, old_lineno) + best_candidate[:-1]
            )
    return update_instance_candidates


def mine_api_updates(
    new_api_calls: dict[str, list] | None,
    old_api_calls: dict[str, list] | None,
    package_imports: dict[str, list[str]],
):
    if (new_api_calls is None) or (old_api_calls is None):
        return
    new_packages = check_imports(new_api_calls["modules"], package_imports)
    if not new_packages:
        return
    old_packages = check_imports(old_api_calls["modules"], package_imports)
    if not old_packages:
        return
    common_packages = list(
        set(new_packages.keys()).intersection(set(old_packages.keys()))
    )
    if not common_packages:
        return
    new_module2packages = {}
    for k in common_packages:
        for v in new_packages[k]:
            new_module2packages[v] = new_module2packages.get(v, [])
            new_module2packages[v].append(k)
    old_module2packages = {}
    for k in common_packages:
        for v in old_packages[k]:
            old_module2packages[v] = old_module2packages.get(v, [])
            old_module2packages[v].append(k)

    new_api_calls = filter_relevant_api_calls(
        new_api_calls["api_calls"], list(new_module2packages.keys())
    )
    if not new_api_calls:
        return
    old_api_calls = filter_relevant_api_calls(
        old_api_calls["api_calls"], list(old_module2packages.keys())
    )
    if not old_api_calls:
        return
    common_callers = list(
        set(new_api_calls.keys()).intersection(set(old_api_calls.keys()))
    )

    res = []
    for caller in common_callers:
        update_instance_candidates = candidate_update_instances(
            new_api_calls[caller], old_api_calls[caller]
        )
        if not update_instance_candidates:
            continue
        for uic in update_instance_candidates:
            old_api, new_api = uic[0], uic[3]
            old_pkgs = []
            for m, p in old_module2packages.items():
                if (old_api == m) or (old_api.startswith(f"{m}.")):
                    old_pkgs = p
            new_pkgs = []
            for m, p in new_module2packages.items():
                if (new_api == m) or (new_api.startswith(f"{m}.")):
                    new_pkgs = p
            com_pkgs = list(set(old_pkgs).intersection(set(new_pkgs)))
            if not com_pkgs:
                continue
            for p in com_pkgs:
                res.append([caller, p, uic])
    return res


def mine_api_updates_batch(batch: list[dict], idx: int):
    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    col = db["py_api_calls"]

    res = []
    for doc in batch:
        commit = doc["commit"]
        filepath = doc["filepath"]
        package_imports = {}
        for p in doc["packages"]:
            imports = py_imports.get(p)
            if imports:
                package_imports[p] = imports
        blob_pairs = doc["blob_pairs"]
        for f, nb, ob in blob_pairs:
            new_api_calls = col.find_one(
                {"blob_sha": nb}, projection={"_id": 0, "modules": 1, "api_calls": 1}
            )
            old_api_calls = col.find_one(
                {"blob_sha": ob}, projection={"_id": 0, "modules": 1, "api_calls": 1}
            )
            apiu = mine_api_updates(new_api_calls, old_api_calls, package_imports)
            if apiu is None:
                continue
            for caller, p, uic in apiu:
                res.append(
                    {
                        "commit": commit,
                        "filepath": filepath,
                        "file": f,
                        "old_blob": ob,
                        "new_blob": nb,
                        "caller": caller,
                        "package": p,
                        "old_api": uic[0],
                        "old_params": uic[1],
                        "old_lineno": uic[2],
                        "new_api": uic[3],
                        "new_params": uic[4],
                        "new_lineno": uic[5],
                        "method_name_dis": uic[6],
                        "call_chain_dis": uic[7],
                        # "param_distance": uic[8],
                    }
                )
    with open(f"../benchmark/updates/api_update_instances.json.{idx}", "w") as outf:
        json.dump(res, outf)


def gen_batch(col: Collection, batch_size: int):
    batch = []
    for doc in col.find({}, projection={"_id": 0}):
        batch.append(doc)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def mine_api_updates_all(n_jobs: int = 1, batch_size: int = 1):
    client = MongoClient("127.0.0.1", 27017)
    db = client["api_update"]
    col = db["py_update_blobs"]
    total_docs = col.count_documents({})

    num_batches = math.ceil(total_docs / batch_size)
    batches = gen_batch(col, batch_size)
    Parallel(n_jobs=n_jobs, backend="multiprocessing")(
        delayed(mine_api_updates_batch)(batch, i)
        for i, batch in enumerate(tqdm(batches, total=num_batches))
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python mine_api_updates.py",
        description="Mine API Updates based on the API call changes between the new and old blobs.",
    )
    parser.add_argument(
        "-n", "--n_jobs", type=int, default=1, help="the number of workers"
    )
    parser.add_argument(
        "-b",
        "--batch_size",
        type=int,
        default=1,
        help="the number of records per batch",
    )
    args = parser.parse_args()

    mine_api_updates_all(args.n_jobs, args.batch_size)
