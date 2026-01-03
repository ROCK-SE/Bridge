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

if os.path.exists("../../benchmark/Phase1/all_pypi_packages.csv"):
    PYPI_PACKAGES = (
        open("../../benchmark/Phase1/all_pypi_packages.csv").read().splitlines()
    )
else:
    PYPI_PACKAGES = list_pypi_packages()

if os.path.exists("../../benchmark/Phase1/all_maven_packages.csv"):
    MAVEN_PACKAGES = (
        open("../../benchmark/Phase1/all_maven_packages.csv").read().splitlines()
    )
else:
    raise Exception(
        "all_maven_packages.csv does not exists. Please obtain it from deps.dev BigQuery dataset: https://docs.deps.dev/bigquery/v1/.\n"
        "Use the following SQL query and save the results to all_maven_packages.csv:\n"
        'SELECT DISTINCT Name FROM `bigquery-public-data.deps_dev_v1.PackageVersions` WHERE System = "MAVEN"',
    )


def get_updates_py(row):
    update_pairs = ""
    new_deps, old_deps = row["new_deps"], row["old_deps"]
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
    new_deps, old_deps = row["new_deps"], row["old_deps"]
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
    prefix = "../../benchmark/Phase1"
    commits_path = os.path.join(prefix, f"{file_type}_candidate_update_commits.csv")
    dependency_path = os.path.join(prefix, f"{file_type}_dependencies.json")

    commits_info = pd.read_csv(commits_path, keep_default_na=False, low_memory=False)
    print(f"{len(commits_info)} commits modifying {file_type}")
    dependencies = json.load(open(dependency_path))
    print(f"{len(dependencies)} unique {file_type} blobs")

    commits_info["new_deps"] = commits_info["new_blob"].map(dependencies)
    commits_info["old_deps"] = commits_info["old_blob"].map(dependencies)

    commits_info["update_pairs"] = commits_info.parallel_apply(get_updates, axis=1)

    # Commits that update dependency versions
    updates = commits_info[commits_info["update_pairs"] != ""]
    num_update_commit = len(updates)

    # Make each update to individual row
    updates.loc[:, "update_pairs"] = updates["update_pairs"].str.split(";")
    updates = updates.explode("update_pairs")
    num_update_deps = len(updates)

    # Split package, version after, and version before in each update to individual column
    updates[["package", "version_after", "version_before"]] = updates[
        "update_pairs"
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

    save_path = os.path.join(prefix, f"{file_type}_version_bumping_commits.csv")
    updates[
        [
            "commit",
            "filepath",
            "new_blob",
            "old_blob",
            "package",
            "version_before",
            "version_after",
        ]
    ].to_csv(save_path, index=False)


def get_updates_py2(row):
    update_pairs = ""
    new_deps, old_deps = row["new_deps"], row["old_deps"]
    for pkg, new_spec in new_deps.items():
        if new_spec and (set(new_spec) - set("0123456789.><=!~, ")):
            continue
        old_spec = old_deps.get(pkg)
        if old_spec is None:
            continue
        if old_spec and (set(old_spec) - set("0123456789.><=!~, ")):
            continue
        if new_spec.startswith("==") and old_spec.startswith("=="):
            continue
        if new_spec != old_spec:
            update_pairs += f"{pkg}@{str(new_spec)}@{str(old_spec)};"
    return update_pairs.strip(";")


def get_updates_java2(row):
    update_pairs = ""
    new_deps, old_deps = row["new_deps"], row["old_deps"]
    for pkg, new_spec in new_deps.items():
        if "@" in pkg:
            continue
        if new_spec and (set(new_spec) - set("0123456789.[](), ")):
            continue
        old_spec = old_deps.get(pkg)
        if old_spec is None:
            continue
        if old_spec and (set(old_spec) - set("0123456789.[](), ")):
            continue
        if not set(new_spec + old_spec).intersection("(), "):
            continue
        if new_spec != old_spec:
            update_pairs += f"{pkg}@{str(new_spec)}@{str(old_spec)};"
    return update_pairs.strip(";")


def filter2(file_type: str):
    get_updates = get_updates_py2
    ALL_PACKAGES = PYPI_PACKAGES
    if file_type == "pom.xml":
        get_updates = get_updates_java2
        ALL_PACKAGES = MAVEN_PACKAGES
    prefix = "../../benchmark/Phase1"
    commits_path = os.path.join(prefix, f"{file_type}_candidate_update_commits.csv")
    dependency_path = os.path.join(prefix, f"{file_type}_dependencies.json")

    commits_info = pd.read_csv(commits_path, keep_default_na=False, low_memory=False)
    print(f"{len(commits_info)} commits modifying {file_type}")
    dependencies = json.load(open(dependency_path))
    print(f"{len(dependencies)} unique {file_type} blobs")

    commits_info["new_deps"] = commits_info["new_blob"].map(dependencies)
    commits_info["old_deps"] = commits_info["old_blob"].map(dependencies)

    commits_info["update_pairs"] = commits_info.parallel_apply(get_updates, axis=1)

    # Commits that update dependency versions
    updates = commits_info[commits_info["update_pairs"] != ""]
    num_update_commit = len(updates)

    # Make each update to individual row
    updates.loc[:, "update_pairs"] = updates["update_pairs"].str.split(";")
    updates = updates.explode("update_pairs")
    num_update_deps = len(updates)

    # Split package, version after, and version before in each update to individual column
    updates[["package", "version_after", "version_before"]] = updates[
        "update_pairs"
    ].str.split("@", expand=True)
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

    save_path = os.path.join(
        prefix, f"{file_type}_nonfixed_version_bumping_commits.csv"
    )
    updates[
        [
            "commit",
            "filepath",
            "new_blob",
            "old_blob",
            "package",
            "version_before",
            "version_after",
        ]
    ].to_csv(save_path, index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python identify_version_bumping_commits.py",
        description="Obtain commits that update dependencies in the dependency configuration file",
    )
    parser.add_argument("-f", "--target_files", help="a list of filname separated by ,")
    parser.add_argument(
        "-o",
        "--other_constraint",
        action="store_true",
        help="consider other version constraints, not fixed version constraint by default",
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")

    args = parser.parse_args()
    pandarallel.initialize(nb_workers=args.n_jobs, progress_bar=True)

    target_files = args.target_files.split(",")
    print(target_files)

    func = filter
    if args.other_constraint:
        func = filter2

    for f in target_files:
        if f not in CONFIG_TYPES:
            print(f"{f} is not supported")
            continue
        func(f)
