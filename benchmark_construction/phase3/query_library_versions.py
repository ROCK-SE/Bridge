import argparse
import json
import math
import os
import random
import time

import pandas as pd
import requests
from joblib import Parallel, delayed
from packaging.utils import canonicalize_name
from pymongo import MongoClient
from tqdm import tqdm

DEPS_DEV_ENDPOINT = "https://api.deps.dev/v3/systems/maven/libraries/{name}"
LIBRARY_SIMPLE_JSON_API_ENDPOINT = "https://pypi.org/simple/{name}"

SIMPLE_JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/vnd.pypi.simple.v1+json",
}
JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

client = MongoClient("127.0.0.1", 27017)
db = client["bridge"]


try:
    with open("config.json") as inf:
        config = json.load(inf)
except:
    config = {}


def get_unique_library_versions():
    for lang in ["py", "java"]:
        col = db[f"{lang}_update_commits"]
        data = []
        for doc in tqdm(col.find({}, projection={"configuration_files": 1, "_id": 0})):
            for f in doc["configuration_files"]:
                for dc in f["dependency_changes"]:
                    data.append([dc["library"], dc["version_before"]])
                    data.append([dc["library"], dc["version_after"]])

        data = pd.DataFrame(data, columns=["library", "version"]).drop_duplicates()
        print(f"{lang}: {data['library'].nunique()} libraries, {len(data)} releases")
        data.to_csv(
            f"../../benchmark/phase3/{lang}_library_versions.csv",
            header=False,
            index=False,
        )


def my_get(
    url: str,
    session: requests.Session | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response | None:
    try:
        if session:
            r = session.get(url, timeout=5)
        else:
            with requests.Session() as s:
                s.headers.update(headers)
                r = s.get(url, timeout=5)
        return r
    except:
        return None


def single_query(system: str, name: str, session: requests.Session | None = None):
    if system == "maven":
        url = DEPS_DEV_ENDPOINT.format(name=name)
        resp = my_get(url, session, JSON_HEADERS)
    elif system == "pypi":
        url = LIBRARY_SIMPLE_JSON_API_ENDPOINT.format(name=name)
        resp = my_get(url, session, SIMPLE_JSON_HEADERS)
    if resp is None:
        return

    if resp.status_code == requests.codes.ok:
        if system == "maven":
            result = []
            for ver in resp.json()["versions"]:
                ver_id = ver["versionKey"]["version"]
                published_at = ver.get("publishedAt", "2025-01-01")
                if published_at < "2024-06-01":
                    result.append(ver_id)
            return result
        elif system == "pypi":
            data = resp.json()
            versions = data["versions"]
            whl_files = [
                (f["filename"], f["url"], f["upload-time"])
                for f in data["files"]
                if f["filename"].endswith(".whl")
            ]
            if not whl_files:
                return {}
            whl_file = max(whl_files, key=lambda x: x[2])[:2]
            return {"versions": versions, "latest_whl": whl_file}

    if resp.status_code == requests.codes.not_found:
        if system == "maven":
            return []
        if system == "pypi":
            return {}


def batch_query(system: str, names: list[str], i: int):
    with requests.Session() as s:
        if system == "maven":
            s.headers.update(JSON_HEADERS)
        elif system == "pypi":
            s.headers.update(SIMPLE_JSON_HEADERS)
        email = config.get("email", None)
        if email:
            s.headers.update({"email": email})
        proxies = config.get("proxies", None)
        if proxies:
            s.proxies.update(proxies)

        results = {}
        for name in names:
            versions = single_query(system, name, s)
            if versions is None:
                continue
            results[name] = versions
            time.sleep(random.randint(2, 10) * 0.01)

        save_path = os.path.join(
            "../../benchmark/phase3", f"{system}_releases.json.{i}"
        )
        with open(save_path, "w") as outf:
            json.dump(results, outf, indent=2)


def create_batches(data: list, batch_size: int):
    for i in range(0, len(data), batch_size):
        yield data[i : i + batch_size]


def query_all(n_jobs: int, batch_size: int):
    java_save_path = os.path.join("../../benchmark/phase3", f"maven_releases.json")
    if os.path.exists(java_save_path):
        with open(java_save_path) as inf:
            java_releases = json.load(inf)
    else:
        java_releases = {}

    java_libraries = []
    with open("../../benchmark/phase3/java_library_versions.csv") as inf:
        for line in inf:
            java_libraries.append(line.split(",")[0])
    remaining_java_libraries = list(set(java_libraries) - set(java_releases.keys()))
    print(
        f"{len(java_libraries)} Java libraries, {len(remaining_java_libraries)} remaining Java libraries"
    )

    java_batches = create_batches(remaining_java_libraries, batch_size)
    num_java_batches = math.ceil(len(remaining_java_libraries) / batch_size)

    Parallel(n_jobs=n_jobs)(
        delayed(batch_query)("maven", batch, i)
        for i, batch in enumerate(tqdm(java_batches, total=num_java_batches))
    )

    for i in range(num_java_batches):
        for k, v in json.load(open(f"{java_save_path}.{i}")).items():
            java_releases[k] = v
        os.remove(f"{java_save_path}.{i}")
    with open(java_save_path, "w") as outf:
        json.dump(java_releases, outf, indent=2)

    py_save_path = os.path.join("../../benchmark/phase3", f"pypi_releases.json")
    if os.path.exists(py_save_path):
        with open(py_save_path) as inf:
            py_releases = json.load(inf)
    else:
        py_releases = {}

    py_libraries = []
    with open("../../benchmark/phase3/py_library_versions.csv") as inf:
        for line in inf:
            py_libraries.append(line.split(",")[0])
    remaining_py_libraries = list(set(py_libraries) - set(py_releases.keys()))
    print(
        f"{len(py_libraries)} Python libraries, {len(remaining_py_libraries)} remaining Python libraries"
    )

    py_batches = create_batches(remaining_py_libraries, batch_size)
    num_py_batches = math.ceil(len(remaining_py_libraries) / batch_size)
    Parallel(n_jobs=n_jobs)(
        delayed(batch_query)("pypi", batch, i)
        for i, batch in enumerate(tqdm(py_batches, total=num_py_batches))
    )

    for i in range(num_py_batches):
        for k, v in json.load(open(f"{py_save_path}.{i}")).items():
            py_releases[k] = v
        os.remove(f"{py_save_path}.{i}")
    with open(py_save_path, "w") as outf:
        json.dump(py_releases, outf, indent=2)


def canonic_names():
    result = {}
    for k, v in json.load(open("../../benchmark/phase3/pypi_releases.json")).items():
        result[canonicalize_name(k)] = v
    with open("../../benchmark/phase3/pypi_releases.json", "w") as outf:
        json.dump(result, outf, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python query_library_versions.py",
        description="Query Deps.dev API and PyPI API to obtain all versions of updated Java/Python libraries",
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")
    parser.add_argument(
        "-b",
        "--batch_size",
        type=int,
        default=100,
        help="number of libraries to be processed",
    )

    args = parser.parse_args()
    get_unique_library_versions()
    query_all(args.n_jobs, args.batch_size)
    canonic_names()
