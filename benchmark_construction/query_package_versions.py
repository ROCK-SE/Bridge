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
from tqdm import tqdm

DEPS_DEV_ENDPOINT = "https://api.deps.dev/v3/systems/maven/packages/{name}"
PACKAGE_SIMPLE_JSON_API_ENDPOINT = "https://pypi.org/simple/{name}"

SIMPLE_JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/vnd.pypi.simple.v1+json",
}
JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


try:
    with open("config.json") as inf:
        config = json.load(inf)
except:
    config = {}


def get_unique_packages():
    df = pd.read_csv(
        "../benchmark/updates/c2fpkgvvtype.csv", low_memory=False, keep_default_na=False
    )
    df.head()
    py_info = df[df["config file"] != "pom.xml"][
        ["package", "version before", "version after"]
    ]
    java_info = df[df["config file"] == "pom.xml"][
        ["package", "version before", "version after"]
    ]
    py_pkgs = pd.concat(
        [
            py_info[["package", "version before"]].rename(
                columns={"version before": "version"}
            ),
            py_info[["package", "version after"]].rename(
                columns={"version after": "version"}
            ),
        ]
    ).drop_duplicates()
    print(f"Python: {py_pkgs['package'].nunique()} packages, {len(py_pkgs)} releases")
    java_pkgs = pd.concat(
        [
            java_info[["package", "version before"]].rename(
                columns={"version before": "version"}
            ),
            java_info[["package", "version after"]].rename(
                columns={"version after": "version"}
            ),
        ]
    ).drop_duplicates()
    print(
        f"Java:   {java_pkgs['package'].nunique()} packages, {len(java_pkgs)} releases"
    )
    py_pkgs.to_csv("../benchmark/updates/py_packages.csv", header=False, index=False)
    java_pkgs.to_csv(
        "../benchmark/updates/java_packages.csv", header=False, index=False
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
        url = PACKAGE_SIMPLE_JSON_API_ENDPOINT.format(name=name)
        resp = my_get(url, session, SIMPLE_JSON_HEADERS)
    if resp is None:
        return None
    if resp.status_code == requests.codes.ok:
        if system == "maven":
            return [ver["versionKey"]["version"] for ver in resp.json()["versions"]]
        if system == "pypi":
            return [v for v in resp.json()["versions"]]
    if resp.status_code == requests.codes.not_found:
        return []
    else:
        return None


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
            "..", "benchmark", "updates", f"{system}_releases.json.{i}"
        )
        with open(save_path, "w") as outf:
            json.dump(results, outf)


def create_batches(data: list, batch_size: int):
    for i in range(0, len(data), batch_size):
        yield data[i : i + batch_size]


def query_all(n_jobs: int, batch_size: int):
    java_save_path = os.path.join("..", "benchmark", "updates", f"maven_releases.json")
    if os.path.exists(java_save_path):
        with open(java_save_path) as inf:
            java_releases = json.load(inf)
    else:
        java_releases = {}

    java_packages = []
    with open("../benchmark/updates/java_packages.csv") as inf:
        for line in inf:
            java_packages.append(line.split(",")[0])
    remaining_java_packages = list(set(java_packages) - set(java_releases.keys()))
    print(
        f"{len(java_packages)} Java packages, {len(remaining_java_packages)} remaining Java packages"
    )

    java_batches = create_batches(remaining_java_packages, batch_size)
    num_java_batches = math.ceil(len(remaining_java_packages) / batch_size)

    Parallel(n_jobs=n_jobs)(
        delayed(batch_query)("maven", batch, i)
        for i, batch in enumerate(tqdm(java_batches, total=num_java_batches))
    )

    for i in range(num_java_batches):
        for k, v in json.load(open(f"{java_save_path}.{i}")).items():
            java_releases[k] = v
        os.remove(f"{java_save_path}.{i}")
    with open(java_save_path, "w") as outf:
        json.dump(java_releases, outf)

    py_save_path = os.path.join("..", "benchmark", "updates", f"pypi_releases.json")
    if os.path.exists(py_save_path):
        with open(py_save_path) as inf:
            py_releases = json.load(inf)
    else:
        py_releases = {}

    py_packages = []
    with open("../benchmark/updates/py_packages.csv") as inf:
        for line in inf:
            py_packages.append(line.split(",")[0])
    remaining_py_packages = list(set(py_packages) - set(py_releases.keys()))
    print(
        f"{len(py_packages)} Python packages, {len(remaining_py_packages)} remaining Python packages"
    )

    py_batches = create_batches(remaining_py_packages, batch_size)
    num_py_batches = math.ceil(len(remaining_py_packages) / batch_size)
    Parallel(n_jobs=n_jobs)(
        delayed(batch_query)("pypi", batch, i)
        for i, batch in enumerate(tqdm(py_batches, total=num_py_batches))
    )

    for i in range(num_py_batches):
        for k, v in json.load(open(f"{py_save_path}.{i}")).items():
            py_releases[k] = v
        os.remove(f"{py_save_path}.{i}")
    with open(py_save_path, "w") as outf:
        json.dump(py_releases, outf)


def canonic_names():
    result = {}
    for k, v in json.load(open("../benchmark/updates/pypi_releases.json")).items():
        result[canonicalize_name(k)] = v
    with open("../benchmark/updates/pypi_releases.json", "w") as outf:
        json.dump(result, outf)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python query_deps_dev.py",
        description="Query Deps.dev API to obtain all versions of Java/Python packages",
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")
    parser.add_argument(
        "-b",
        "--batch_size",
        type=int,
        default=100,
        help="number of packages to be processed",
    )

    args = parser.parse_args()
    get_unique_packages()
    query_all(args.n_jobs, args.batch_size)
    canonic_names()
