import argparse
import json
import os
import random
import sys
import time

import pandas as pd
from joblib import Parallel, delayed
from tqdm import tqdm
from utils import download, is_strict_ver

try:
    with open("config.json") as inf:
        config = json.load(inf)
except:
    config = {}


def get_latest_releases(lang: str):
    pkg_vers = {}
    with open(f"../benchmark/updates/{lang}_packages.csv") as inf:
        for line in inf:
            pkg, ver = line.strip("\n").split(",", 1)
            pkg_vers[pkg] = pkg_vers.get(pkg, [])
            pkg_vers[pkg].append(ver)
    platform = "pypi" if lang == "py" else "maven"
    pkg_all_vers = json.load(open(f"../benchmark/updates/{platform}_releases.json"))

    result = []
    for pkg, vers in pkg_vers.items():
        all_vers = pkg_all_vers.get(pkg)
        if all_vers is None:
            continue
        if lang == "java":
            common_vers = [
                [v]
                for v in list(set(vers).intersection(set(all_vers)))
                if is_strict_ver(v)
            ]
        elif lang == "py":
            common_vers = [[ver, url] for ver, url in all_vers.items() if ver in vers]

        if common_vers:
            latest_ver = max(
                common_vers, key=lambda v: tuple(int(p) for p in v[0].split("."))
            )
            result.append((pkg, latest_ver))
    with open(f"../benchmark/updates/{lang}_latest_release", "w") as outf:
        for p, v in result:
            outf.write(f"{p},{','.join(v)}\n")


def download_python_packages(n_jobs: int, dest_folder: str):
    latest_release_path = "../benchmark/updates/py_latest_release"
    if not os.path.exists(latest_release_path):
        get_latest_releases("py")
    df = pd.read_csv(
        latest_release_path,
        low_memory=False,
        keep_default_na=False,
        names=["name", "version", "url"],
    )
    print(f"{len(df)} package wheels")
    mirror = config.get("mirror", None)
    if mirror:
        df.loc[:, "url"] = df["url"].apply(
            lambda x: x.replace("https://files.pythonhosted.org", mirror.rstrip("/"))
        )

    Parallel(n_jobs=n_jobs)(
        delayed(download)(
            row.url,
            os.path.join(dest_folder, "python", row.name, row.url.split("/")[-1]),
        )
        for row in tqdm(df.itertuples(), file=sys.stdout, total=len(df))
    )


def gen_jar_url_path(name: str, version: str):
    group_id, artifact_id = name.split(":")
    group_path = "/".join(group_id.split("."))
    jar_name = f"{artifact_id}-{version}.jar"
    url = (
        f"https://repo1.maven.org/maven2/{group_path}"
        + f"/{artifact_id}/{version}/{jar_name}"
    )
    save_path = os.path.join(group_path, jar_name)
    return url, save_path


def polite_download(url, save_path: str):
    download(url, save_path)
    time.sleep(random.random() * 3)


def download_java_packages(n_jobs: int, dest_folder: str):
    latest_release_path = "../benchmark/updates/java_latest_release"
    if not os.path.exists(latest_release_path):
        get_latest_releases("java")
    data = []
    with open(latest_release_path) as f:
        for line in f:
            name, version = line.strip("\n").split(",")
            url, path = gen_jar_url_path(name, version)
            save_path = os.path.join(dest_folder, "java", path)
            data.append((name, version, url, save_path))
    Parallel(n_jobs=n_jobs)(
        delayed(polite_download)(url, save_path)
        for _, _, url, save_path in tqdm(data, file=sys.stdout, total=len(data))
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python download_packages.py",
        description="Download wheel/jar file of the latest release for each updated Python package / Java library",
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")
    parser.add_argument("-d", "--dest_folder", required=True, type=str)
    parser.add_argument("--python", action="store_true")
    parser.add_argument("--java", action="store_true")

    args = parser.parse_args()
    if args.python:
        download_python_packages(args.n_jobs, args.dest_folder)
    if args.java:
        download_java_packages(args.n_jobs, args.dest_folder)
