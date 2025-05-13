import argparse
import json
import os

import pandas as pd
from pandarallel import pandarallel
from utils import is_strict_ver, list_pypi_packages

CONFIG_TYPES = [
    "setup.cfg",
    "setup.py",
    "pyproject.toml",
    "requirements.txt",
    "pom.xml",
]

if os.path.exists("./pypi_packages.csv"):
    PYPI_PACKAGES = open("./pypi_packages.csv").read().splitlines()
else:
    PYPI_PACKAGES = list_pypi_packages()

if os.path.exists("./maven_packages.csv"):
    MAVEN_PACKAGES = open("./maven_packages.csv").read().splitlines()
else:
    raise Exception(
        "maven_packages.csv does not exists. Please obtain it from deps.dev BigQuery dataset: https://docs.deps.dev/bigquery/v1/.\n"
        "Use the following SQL query and save the results to maven_packages.csv:\n"
        'SELECT DISTINCT Name FROM `bigquery-public-data.deps_dev_v1.PackageVersions` WHERE System = "MAVEN"',
    )


def get_updates_py(row):
    update_pairs = ""
    new_deps, old_deps = row["new deps"], row["old deps"]
    for pkg, new_spec in new_deps.items():
        if not new_spec.startswith("=="):
            continue
        new_version = new_spec[2:]
        if not is_strict_ver(new_version):
            continue

        old_spec = old_deps.get(pkg)
        if old_spec is None:
            continue
        if not old_spec.startswith("=="):
            continue
        old_version = old_spec[2:]
        if not is_strict_ver(old_version):
            continue

        if new_version != old_version:
            update_pairs += f"{pkg},{str(new_version)},{str(old_version)};"
    return update_pairs.strip(";")


def get_updates_java(row):
    update_pairs = ""
    new_deps, old_deps = row["new deps"], row["old deps"]
    for pkg, new_spec in new_deps.items():
        # https://maven.apache.org/pom.html#Dependency_Version_Requirement_Specification
        if ("," in new_spec) or ("(" in new_spec) or (")" in new_spec):
            continue
        new_version = new_spec.strip("[]")
        if not is_strict_ver(new_version):
            continue

        old_spec = old_deps.get(pkg)
        if old_spec is None:
            continue
        if ("," in old_spec) or ("(" in old_spec) or (")" in old_spec):
            continue
        old_version = old_spec.strip("[]")
        if not is_strict_ver(old_version):
            continue

        if new_version != old_version:
            update_pairs += f"{pkg},{str(new_version)},{str(old_version)};"
    return update_pairs.strip(";")


def filter(file_type: str):
    get_updates = get_updates_py
    ALL_PACKAGES = PYPI_PACKAGES
    if file_type == "pom.xml":
        get_updates = get_updates_java
        ALL_PACKAGES = MAVEN_PACKAGES
    prefix = "../benchmark"
    commits_path = os.path.join(prefix, "commits", f"{file_type}_commits.csv")
    dependency_path = os.path.join(prefix, "deps", f"{file_type}_dependencies.json")

    commits_info = pd.read_csv(commits_path, keep_default_na=False, low_memory=False)
    print(f"{len(commits_info)} commits modifying {file_type}")
    dependencies = json.load(open(dependency_path))
    print(f"{len(dependencies)} unique {file_type} blobs")

    commits_info["new deps"] = commits_info["new blob"].map(dependencies)
    commits_info["old deps"] = commits_info["old blob"].map(dependencies)

    commits_info["update pairs"] = commits_info.parallel_apply(get_updates, axis=1)

    # Commits that update dependency versions
    updates = commits_info[commits_info["update pairs"] != ""]
    num_update_commit = len(updates)

    # Make each update to individual row
    updates.loc[:, "update pairs"] = updates["update pairs"].str.split(";")
    updates = updates.explode("update pairs")
    num_update_deps = len(updates)

    # Split package, version before, and version after in each update to individual column
    updates[["package", "version before", "version after"]] = updates[
        "update pairs"
    ].str.split(",", expand=True)
    num_unique_pkgs1 = updates["package"].nunique()

    # Ensure packages exist on PyPI or Maven Central
    updates = updates[updates["package"].isin(ALL_PACKAGES)]
    num_unique_pkgs2 = updates["package"].nunique()

    print(
        f"\n{num_update_commit} commits perform {num_update_deps} dependency version updates in {file_type}, involve {num_unique_pkgs1} packages"
    )
    print(
        f"{num_update_deps - len(updates)} updates involving {num_unique_pkgs1 - num_unique_pkgs2} packages that do not exist on PyPI or Maven Central",
    )
    print(
        f"Save {updates['commit'].nunique()} commits, {len(updates)} update, {num_unique_pkgs2} packages"
    )

    save_folder = os.path.join(prefix, "updates")
    os.makedirs(save_folder, exist_ok=True)
    save_path = os.path.join(save_folder, f"{file_type}_updates.csv")
    updates[
        [
            "commit",
            "filepath",
            "new blob",
            "old blob",
            "package",
            "version before",
            "version after",
        ]
    ].to_csv(save_path, index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python dep_update_commits.py",
        description="Obtain commits that update dependencies in the dependency configuration file",
    )
    parser.add_argument("-f", "--target_files", help="a list of filname separated by ,")
    parser.add_argument(
        "-n", "--num_workers", type=int, default=1, help="number of threads"
    )

    args = parser.parse_args()
    pandarallel.initialize(nb_workers=args.num_workers, progress_bar=True)

    target_files = args.target_files.split(",")
    print(target_files)

    for f in target_files:
        if f not in CONFIG_TYPES:
            print(f"{f} is not supported")
            continue
        filter(f)
