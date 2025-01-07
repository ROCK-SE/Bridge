import gzip
import os

import pandas as pd
from joblib import Parallel, delayed

c2fbb_base_path = "/da7_data/basemaps/gz/c2fbbFull.V3.{id}.s"
c2P_base_path = "/da7_data/basemaps/gz/c2PFull.V3.{id}.s"

# Non-GitHub platforms that WoC collects
URL_PREFIXES = [
    "gitlab.com",
    "bitbucket.org",
    "0xacab.org",
    "android.googlesource.com",
    "bioconductor.org",
    "blitiri.com.ar",
    "code.ill.fr",
    "code.qt.io",
    "drupal.com",
    "fedorapeople.org",
    "forgemia.inra.fr",
    "framagit.org",
    "gcc.git",
    "git.alpinelinux.org",
    "git.debian.org",
    "git.eclipse.org",
    "git.kernel.org",
    "git.openembedded.org",
    "git.pleroma.social",
    "git.postgresql.org",
    "git.savannah.gnu.org",
    "git.savannah.nongnu.org",
    "git.torproject.org",
    "git.unicaen.fr",
    "git.unistra.fr",
    "git.xfce.org",
    "git.yoctoproject.org",
    "git.zx2c4.com",
    "gitbox.apache.org",
    "gite.lirmm.fr",
    "gitlab.adullact.net",
    "gitlab.cerema.fr",
    "gitlab.common-lisp.net",
    "gitlab.fing.edu.uy",
    "gitlab.freedesktop.org",
    "gitlab.gnome.org",
    "gitlab.huma-num.fr",
    "gitlab.inria.fr",
    "gitlab.irstea.fr",
    "gitlab.ow2.org",
    "invent.kde.org",
    "kde.org",
    "notabug.org",
    "pagure.io",
    "repo.or.cz",
    "salsa.debian.org",
    "sourceforge.net",
]


def normalize_url(url: str) -> str:
    """Normalize an url by lowercasing all characters and removing `/` and `.git` suffixes."""
    url = url.lower().strip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url


def restore_url(woc_uri: str) -> str | None:
    """Convert a woc uri to corresponsing GitHub repository URL"""
    if woc_uri.count("_") < 1:
        return
    prefix = woc_uri.split("_", 1)[0]
    if prefix not in URL_PREFIXES:
        url = f"https://github.com/" + woc_uri.replace("_", "/", 1)
        return normalize_url(url)


Record = tuple[str, str, str, str, str]


def commits_by_filenames(i: int, target_files: list[str], save_folder: str) -> None:
    """Query commits that modify filenames in `target_files`

    Parameters
    ----------
    i : int
        the index of mapping to query, valid range [0, 127]
    target_files : list[str]
        a list of file names to query
    save_folder : str
        the folder the save query results for each file
    """
    results = {f: [] for f in target_files}
    c2fbb_path = c2fbb_base_path.format(id=i)
    c2P_path = c2P_base_path.format(id=i)

    commit_proj = {}
    err_line = 0
    with gzip.open(c2P_path) as inf:
        for line in inf:
            try:
                line = line.decode(encoding="utf-8")
                entries = line.strip("\n").split(";")
                # If there are multiple projects, we only keep the first one
                commit, proj = entries[0], entries[1]
                commit_proj[commit] = proj
            except:
                err_line += 1
    print(f"{len(commit_proj)} commits in {c2P_path}, {err_line} error line(s)")

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
                proj = restore_url(commit_proj.get(commit, ""))
                if proj:
                    results[filename].append(
                        (commit, filepath, new_blob, old_blob, proj)
                    )
            except:
                err_line += 1

    total = sum([len(r) for r in results.values()])
    print(
        f"{c2fbb_path}: {total} commits modified {', '.join(target_files)} files, {err_line} error line(s)"
    )
    os.makedirs(os.path.join(save_folder, "commits"), exist_ok=True)
    for fn, data in results.items():
        save_path = os.path.join(save_folder, f"commits/{fn}_commits.csv.{i}")
        df = pd.DataFrame(
            data,
            columns=["commit", "filepath", "new blob", "old blob", "project"],
        )
        df.to_csv(save_path, index=False)


def main(
    target_files: list[str],
    save_folder: str,
    num_workers: int = 1,
    update: bool = False,
) -> None:
    """The entry function to run `commits_by_filenames` parallelly

    Parameters
    ----------
    target_files : list[str]
        a list of file names to query
    save_folder : str
        the folder to save the results
    num_workers : int, optional
        the number of processes, by default 1
    update : bool, optional
        whether to perform update, by default False
    """

    remaining_target_files = []
    # When `update` is set to False, we only process filenames whose result file does not exist
    # Else, we process all filenames
    os.makedirs(os.path.join(save_folder, "commits"), exist_ok=True)
    if not update:
        for fn in target_files:
            save_path = os.path.join(save_folder, f"commits/{fn}_commits.csv")
            if os.path.exists(save_path):
                continue
            remaining_target_files.append(fn)
    else:
        remaining_target_files = target_files[:]

    Parallel(n_jobs=num_workers)(
        delayed(commits_by_filenames)(i, remaining_target_files, save_folder)
        for i in range(128)
    )

    for fn in remaining_target_files:
        save_path = os.path.join(save_folder, f"commits/{fn}_commits.csv")
        data = []
        for i in range(128):
            df = pd.read_csv(f"{save_path}.{i}")
            data.append(df)
            os.remove(f"{save_path}.{i}")

        data = pd.concat(data)
        data.to_csv(save_path, index=False)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python filter_commits.py",
        description="Query commits that modify specific files",
    )
    parser.add_argument(
        "-f",
        "--target_files",
        type=str,
        help="a list of filname separated by ,",
    )
    parser.add_argument(
        "-d",
        "--destination_folder",
        type=str,
        help="the folder to save query results",
    )
    parser.add_argument(
        "-n", "--num_workers", type=int, default=1, help="number of threads"
    )
    parser.add_argument("-u", "--update", action="store_true", help="update results")

    args = parser.parse_args()

    if args.target_files:
        target_files = args.target_files.split(",")
        print(target_files)
        main(target_files, args.destination_folder, args.num_workers, args.update)
