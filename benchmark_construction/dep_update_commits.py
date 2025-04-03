import argparse
import json
import os

import pandas as pd
from packaging.version import Version
from tqdm import tqdm

tqdm.pandas()

CONFIG_TYPES = [
    "setup.cfg",
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "pom.xml",
]


def get_updates(row):
    update_pairs = []
    new_deps, old_deps = row["new deps"], row["old deps"]
    for pkg, new_spec in new_deps.items():
        if not new_spec.startswith("=="):
            continue
        try:
            new_version = Version(new_spec[2:])
        except:
            continue

        old_spec = old_deps.get(pkg)
        if old_spec is None:
            continue
        if not old_spec.startswith("=="):
            continue
        try:
            old_version = Version(old_spec[2:])
        except:
            continue

        if new_version != old_version:
            update_pairs.append((pkg, str(new_version), str(old_version)))
    return update_pairs


def filter(file_type: str, prefix: str):
    commits_path = os.path.join(prefix, "commits", f"{file_type}_commits.csv")
    dependency_path = os.path.join(prefix, "deps", f"{file_type}_dependencies.json")

    dependencies = json.load(open(dependency_path))
    print(f"{len(dependencies)} unique {file_type} blobs")
    commits_info = pd.read_csv(commits_path, keep_default_na=False, low_memory=False)
    print(f"{len(commits_info)} commits modifying {file_type}")

    commits_info["new deps"] = commits_info["new blob"].map(dependencies)
    commits_info["old deps"] = commits_info["old blob"].map(dependencies)
    commits_info["update pairs"] = commits_info.progress_apply(get_updates, axis=1)
    updates = commits_info[commits_info["update pairs"].str.len() > 0]
    print(f"{len(updates)} commits update dependencies in {file_type}")

    save_folder = os.path.join(prefix, "updates")
    os.makedirs(save_folder, exist_ok=True)
    save_path = os.path.join(save_folder, f"{file_type}_updates.csv")
    updates.to_csv(save_path, index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python dep_update_commits.py",
        description="Obtain commits that update dependencies in the dependency configuration file",
    )
    parser.add_argument(
        "-t", "--configuration_file_type", help="type of configuration file"
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=str,
        help="the directory to read commits and save results",
    )

    args = parser.parse_args()
    cft = args.configuration_file_type
    if cft == "all":
        for cfg in CONFIG_TYPES:
            filter(cfg, args.directory)
    elif cft in CONFIG_TYPES:
        filter(cft, args.directory)
