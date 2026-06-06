import argparse
import logging
import math
import os
import random
import sys
import time
import zipfile
from urllib.error import HTTPError
from urllib.request import urlretrieve

import pandas as pd
import requests
from joblib import Parallel, delayed
from packaging.utils import canonicalize_name
from pymongo import MongoClient
from tqdm import tqdm
from utils import gen_sources_jar_path

logger = logging.getLogger(__name__)


RELEASE_JSON_API_ENDPOINT = "https://pypi.org/pypi/{name}/{version}/json"
JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def download_sources_jar(row, dest_folder: str):
    library = row["name"]
    version = row["version"]
    url, save_path = gen_sources_jar_path(library, version, dest_folder)
    if os.path.exists(save_path):
        logger.error(f"[INFO] Sources Jar Already Downloaded: {library} {version}")
        try:
            zipfile.ZipFile(save_path)
            return
        except:
            logger.error(f"[ERROR] Bad Sources Jar: {library} {version}")
            pass
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    try:
        urlretrieve(url, save_path)
        logger.error(f"[INFO] Successfully download jar for {library} {version}")
    except HTTPError as e:
        if e.code == 404:
            logger.error(f"[ERROR] Jar does not exist: {library} {version} ")
        else:
            logger.error(f"[ERROR] Other HTTPError: {library} {version} {e}")
    except Exception as e:
        logger.error(f"[ERROR] Downloading Error for {library} {version}: {e}")

    time.sleep(random.random() * 3)


def releases_from_excel(lang: str):
    releases = []
    df = pd.read_excel(f"../../benchmark/ground_truth/{lang}_record_samples.xlsx")
    for row in df.itertuples(index=False):
        name = row.library
        version_before = row.version_before
        version_after = row.version_after
        releases.append([name, version_before])
        releases.append([name, version_after])
    return releases


def releases_from_mongo(lang: str):
    releases = []
    client = MongoClient("127.0.0.1", 27017)
    db = client["bridge"]
    col = db[f"{lang}_candidate_update_instances"]
    for doc in tqdm(
        col.find({}), total=col.estimated_document_count(), file=sys.stdout
    ):
        library = doc["library"]
        version_before = doc["version_before"]
        version_after = doc["version_after"]
        releases.append([library, version_before])
        releases.append([library, version_after])
    return releases


def download_jars(mode: str, n_jobs: int, dest_folder: str):
    releases = []
    if mode == "evaluation":
        releases = releases_from_excel("java")

    elif mode == "validation":
        releases = releases_from_mongo("java")

    releases = (
        pd.DataFrame(releases, columns=["name", "version"])
        .drop_duplicates()
        .to_dict("records")
    )
    print(f"{len(releases)} releases")
    Parallel(n_jobs=n_jobs)(
        delayed(download_sources_jar)(rls, dest_folder)
        for rls in tqdm(releases, file=sys.stdout)
    )


def download_wheel(record: dict, dest_folder: str):
    name = record["name"]
    version = record["version"]
    url = record["url"]
    filename = url.split("/")[-1]
    save_path = os.path.join(dest_folder, "python", name, filename)

    if os.path.exists(save_path):
        logger.error(f"[INFO] Wheel Already Downloaded: {name}, {version}")
        try:
            zipfile.ZipFile(save_path)
            return
        except:
            logger.error(f"[ERROR] Bad Wheel: {name}, {version}, {filename}")

    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    try:
        urlretrieve(url, save_path)
        logger.error(f"[INFO] Successfully download wheel for {name} {version}")
    except HTTPError as e:
        if e.code == 404:
            logger.error(f"[ERROR] Wheel Not Found: {name}, {version}, {url}")
        else:
            logger.error(f"[ERROR] Other HTTPError: {name}, {version}, {url}")
    except Exception as e:
        logger.error(f"[ERROR] Download Error: {name}, {version}, {url}, {e}")

    time.sleep(random.random() * 3)


def download_wheels(mode: str, n_jobs: int, dest_folder: str):
    data_path = f"../../benchmark/phase4/py_wheel_{mode}.csv"
    if not os.path.exists(data_path):
        get_wheel_urls(mode, n_jobs)
    data = pd.read_csv(data_path, keep_default_na=False).to_dict("records")
    Parallel(n_jobs=n_jobs)(
        delayed(download_wheel)(rec, dest_folder) for rec in tqdm(data, file=sys.stdout)
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


def prepare_releases(mode: str):
    releases = []
    if mode == "evaluation":
        releases = releases_from_excel("py")

    elif mode == "validation":
        releases = releases_from_mongo("py")

    releases = pd.DataFrame(releases, columns=["name", "version"]).drop_duplicates()
    releases.to_csv(f"../../benchmark/phase4/py_releases_{mode}.csv", index=False)


def create_batches(data: list, batch_size: int):
    for i in range(0, len(data), batch_size):
        yield data[i : i + batch_size]


def release_wheel_url(name: str, version: str, s: requests.Session) -> str | None:
    url = RELEASE_JSON_API_ENDPOINT.format(name=name, version=version)
    resp = my_get(url, s, JSON_HEADERS)
    if resp is None:
        logger.error(f"[ERROR] Request Error: {name}, {version}")
        return

    if resp.status_code == requests.codes.not_found:
        logger.error(f"[ERROR] Release Not Found: {name}, {version}")
        return

    try:
        urls = resp.json().get("urls", [])
        whl_files = [
            (f["url"], f["upload_time"]) for f in urls if f["filename"].endswith(".whl")
        ]
        if not whl_files:
            logger.error(f"[ERROR] No Wheel File: {name}, {version}")
            return
        whl_url = max(whl_files, key=lambda x: x[1])[0]
        return whl_url
    except:
        logger.error(f"[ERROR] Error: {name}, {version}")
        return


def _batch_wheel_url(batch: list[tuple], i: int) -> list[tuple]:
    with requests.Session() as s:
        s.headers.update(JSON_HEADERS)

        res = []
        for name, version in batch:
            wheel_url = release_wheel_url(name, version, s)
            if wheel_url is None:
                continue
            res.append((canonicalize_name(name), version, wheel_url))
            time.sleep(random.randint(2, 10) * 0.01)
        return res


def get_wheel_urls(mode: str, n_jobs: int = 1, batch_size: int = 1):
    assert mode in ["evaluation", "validation"]

    releases = []
    releases_path = f"../../benchmark/phase4/py_releases_{mode}.csv"
    if not os.path.exists(releases_path):
        prepare_releases(mode)
    for row in pd.read_csv(releases_path, keep_default_na=False).itertuples(
        index=False
    ):
        releases.append((canonicalize_name(row.name), row.version))
    print(f"{len(releases)} releases in total")

    res = []
    save_path = f"../../benchmark/phase4/py_wheel_{mode}.csv"
    if os.path.exists(save_path):
        existing = []
        for row in pd.read_csv(save_path, keep_default_na=False).itertuples(
            index=False
        ):
            res.append((canonicalize_name(row.name), row.version, row.url))
            existing.append((canonicalize_name(row.name), row.version))
        releases = [r for r in releases if r not in existing]

    print(f"{len(releases)} releases to be processed")
    batches = create_batches(releases, batch_size)
    num_batches = math.ceil(len(releases) / batch_size)
    batch_results = Parallel(n_jobs=n_jobs)(
        delayed(_batch_wheel_url)(batch, i)
        for i, batch in enumerate(tqdm(batches, total=num_batches, file=sys.stdout))
    )
    for batch_res in batch_results:
        res.extend(batch_res)
    pd.DataFrame(res, columns=["name", "version", "url"]).to_csv(save_path, index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python download_libraries.py",
        description="Download the sources jars/latest wheel file for a list of Java/Python library leases",
    )
    parser.add_argument(
        "--java",
        action="store_true",
        help="download sources jars. DEFAULT: False",
    )
    parser.add_argument(
        "--python",
        action="store_true",
        help="download wheels. DEFAULT: False",
    )
    parser.add_argument(
        "--evaluation",
        action="store_true",
        help="on ground truth dataset. DEFAULT: False",
    )
    parser.add_argument(
        "--validation",
        action="store_true",
        help="on all candidate update instances. DEFAULT: False",
    )
    parser.add_argument(
        "-n", "--n_jobs", type=int, default=1, help="number of workers. DEFAULT: 1"
    )
    parser.add_argument(
        "-b",
        "--batch_size",
        type=int,
        default=1,
        help="number of Python library releases to be processed. DEFAULT: 1",
    )
    parser.add_argument(
        "-d",
        "--dest_folder",
        required=True,
        type=str,
        help="folder to save downloaded libraries",
    )
    args = parser.parse_args()

    if args.java:
        if args.evaluation:
            download_jars("evaluation", args.n_jobs, args.dest_folder)
        if args.validation:
            download_jars("validation", args.n_jobs, args.dest_folder)

    if args.python:
        if args.evaluation:
            get_wheel_urls("evaluation", args.n_jobs, args.batch_size)
            download_wheels("evaluation", args.n_jobs, args.dest_folder)
        if args.validation:
            get_wheel_urls("validation", args.n_jobs, args.batch_size)
            download_wheels("validation", args.n_jobs, args.dest_folder)
