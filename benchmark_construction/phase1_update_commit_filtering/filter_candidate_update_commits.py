import gzip
import os
import string

import pandas as pd
from joblib import Parallel, delayed

c2fbb_base_path = "/{server}_data/basemaps/gz/c2fbbFull.{ver}."


def commits_by_filenames(i: int, target_files: list[str], save_path: str) -> None:
    """Query commits that modify filenames in `target_files`

    Parameters
    ----------
    i : int
        the index of mapping to query, valid range [0, 127]
    target_files : list[str]
        a list of file names to query
    save_path : str
        the path to save query results for each target file
    """
    results = {f: [] for f in target_files}
    c2fbb_path = c2fbb_base_path + f"{i}.s"

    err_line = 0
    with gzip.open(c2fbb_path) as inf:
        for line in inf:
            try:
                line = line.decode(encoding="utf-8")
                entries = line.strip("\n").split(";")
                # We only consider `commit, filename, new blob, old blob` lines
                if len(entries) != 4 or (entries[2] == "") or (entries[3] == ""):
                    continue
                commit, filepath, new_blob, old_blob = entries

                # regardless of whether the filename is in the root directory or subdirectory
                filename = os.path.basename(filepath)
                if filename not in target_files:
                    continue
                results[filename].append(
                    (commit, filepath.strip("/"), new_blob, old_blob)
                )
            except:
                err_line += 1

    total = sum([len(r) for r in results.values()])
    print(
        f"{c2fbb_path}: {total} commits modified {', '.join(target_files)} files, {err_line} error line(s)"
    )
    for fn, data in results.items():
        df = pd.DataFrame(
            data,
            columns=["commit", "filepath", "new_blob", "old_blob"],
        )
        df.to_csv(f"{save_path}.{i}", index=False)


def is_valid_sha1(sha: str):
    if (len(sha) == 40) and all(c in string.hexdigits for c in sha):
        return True
    return False


def valid_sha_value(row):
    if is_valid_sha1(row["new_blob"]) and is_valid_sha1(row["old_blob"]):
        return True
    return False


def main(
    target_files: list[str],
    num_workers: int = 1,
    update: bool = False,
) -> None:
    """The entry function to run `commits_by_filenames` parallelly

    Parameters
    ----------
    target_files : list[str]
        a list of file names to query
    num_workers : int, optional
        the number of processes, by default 1
    update : bool, optional
        whether to perform update, by default False
    """
    save_folder = "../../benchmark/Phase1"
    remaining_target_files = []
    # When `update` is set to False, we only process filenames whose result file does not exist
    # Else, we process all filenames
    os.makedirs(save_folder, exist_ok=True)
    save_path = os.path.join(save_folder, f"{fn}_candidate_update_commits.csv")
    if not update:
        for fn in target_files:
            if os.path.exists(save_path):
                continue
            remaining_target_files.append(fn)
    else:
        remaining_target_files = target_files[:]

    Parallel(n_jobs=num_workers)(
        delayed(commits_by_filenames)(i, remaining_target_files, save_path)
        for i in range(128)
    )

    for fn in remaining_target_files:
        data = []
        for i in range(128):
            df = pd.read_csv(f"{save_path}.{i}")
            data.append(df)
            os.remove(f"{save_path}.{i}")

        data = pd.concat(data)
        data = data[data.apply(valid_sha_value, axis=1)]
        data.to_csv(save_path, index=False)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python filter_candidate_update_commits.py",
        description="Filter commits that modify dependency configuration files",
    )
    parser.add_argument(
        "-f",
        "--target_files",
        type=str,
        help="a list of filname separated by ,",
    )
    parser.add_argument(
        "-s",
        "--server",
        default="da7",
        type=str,
        help="the server that stores the c2fbb mapping files",
    )
    parser.add_argument(
        "-v",
        "--ver",
        default="V3",
        type=str,
        help="the version of c2fbb mappings",
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")
    parser.add_argument(
        "-u", "--update", action="store_true", help="requery if specified"
    )

    args = parser.parse_args()

    c2fbb_base_path = c2fbb_base_path.format(server=args.server, ver=args.ver)

    if args.target_files:
        target_files = args.target_files.split(",")
        print(target_files)
        main(target_files, args.n_jobs, args.update)
