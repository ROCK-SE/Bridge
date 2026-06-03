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
from tqdm import tqdm

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
info_fh = logging.FileHandler("../../log/download_wheels.log", mode="a")
info_fh.setLevel(logging.INFO)
# create formatter and add it to the handlers
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(lineno)d %(message)s")
info_fh.setFormatter(formatter)
# add the handlers to logger
logger.addHandler(info_fh)

RELEASE_JSON_API_ENDPOINT = "https://pypi.org/pypi/{name}/{version}/json"
JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def download_wheel(record: dict, dest_folder: str):
    name = record["name"]
    version = record["version"]
    url = record["url"]
    filename = url.split("/")[-1]
    save_path = os.path.join(dest_folder, "python", name, filename)

    if os.path.exists(save_path):
        logger.info(f"Wheel Already Downloaded: {name}, {version}")
        try:
            zipfile.ZipFile(save_path)
            return
        except:
            logger.error(f"Bad Wheel: {name}, {version}, {filename}")

    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    try:
        urlretrieve(url, save_path)
    except HTTPError as e:
        if e.code == 404:
            logger.error(f"Wheel Not Found: {name}, {version}, {url}")
        else:
            logger.error(f"Other HTTPError: {name}, {version}, {url}")
    except Exception as e:
        logger.error(f"Download Error: {name}, {version}, {url}, {e}")

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
        df = pd.read_excel("../../benchmark/ground_truth/py_record_samples.xlsx")
        for row in df.itertuples(index=False):
            name = row.library
            version_before = row.version_before
            version_after = row.version_after
            releases.append([name, version_before])
            releases.append([name, version_after])

    elif mode == "validation":
        pass

    releases = pd.DataFrame(releases, columns=["name", "version"]).drop_duplicates()
    releases.to_csv(f"../../benchmark/phase4/py_releases_{mode}.csv", index=False)


def create_batches(data: list, batch_size: int):
    for i in range(0, len(data), batch_size):
        yield data[i : i + batch_size]


def release_wheel_url(name: str, version: str, s: requests.Session) -> str | None:
    url = RELEASE_JSON_API_ENDPOINT.format(name=name, version=version)
    resp = my_get(url, s, JSON_HEADERS)
    if resp is None:
        logger.info(f"Request Error: {name}, {version}")
        return

    if resp.status_code == requests.codes.not_found:
        logger.info(f"Release Not Found: {name}, {version}")
        return

    try:
        urls = resp.json().get("urls", [])
        whl_files = [
            (f["url"], f["upload_time"]) for f in urls if f["filename"].endswith(".whl")
        ]
        if not whl_files:
            logger.info(f"No Wheel File: {name}, {version}")
            return
        whl_url = max(whl_files, key=lambda x: x[1])[0]
        return whl_url
    except:
        logger.error(f"Error: {name}, {version}")
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
        prog="python download_wheels.py",
        description="Download the latest wheel file for a list of Python leases",
    )
    parser.add_argument(
        "--evaluation", action="store_true", help="on ground truth dataset"
    )
    parser.add_argument(
        "--validation", action="store_true", help="on all update instances"
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")
    parser.add_argument(
        "-b",
        "--batch_size",
        type=int,
        default=1,
        help="number of libraries to be processed",
    )
    parser.add_argument("-d", "--dest_folder", required=True, type=str)

    args = parser.parse_args()
    if args.evaluation:
        get_wheel_urls("evaluation", args.n_jobs, args.batch_size)
        download_wheels("evaluation", args.n_jobs, args.dest_folder)
    if args.validation:
        get_wheel_urls("validation", args.n_jobs, args.batch_size)
        download_wheels("validation", args.n_jobs, args.dest_folder)
