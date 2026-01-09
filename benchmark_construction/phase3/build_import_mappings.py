import argparse
import json
import logging
import os
import sys
import zipfile

import pandas as pd
from joblib import Parallel, delayed
from tqdm import tqdm
from utils import download, gen_jar_url_path, is_strict_ver, polite_download

try:
    with open("config.json") as inf:
        config = json.load(inf)
except:
    config = {}

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def get_latest_java_releases():
    lib_vers = {}
    with open(f"../../benchmark/phase3/java_library_versions.csv") as inf:
        for line in inf:
            lib, ver = line.strip("\n").split(",", 1)
            lib_vers[lib] = lib_vers.get(lib, [])
            lib_vers[lib].append(ver)
    lib_all_vers = json.load(open(f"../../benchmark/phase3/maven_releases.json"))

    result = []
    for lib, vers in lib_vers.items():
        all_vers = lib_all_vers.get(lib)
        if all_vers is None:
            continue
        common_vers = [
            [v] for v in list(set(vers).intersection(set(all_vers))) if is_strict_ver(v)
        ]

        if common_vers:
            latest_ver = max(
                common_vers, key=lambda v: tuple(int(p) for p in v[0].split("."))
            )
            result.append((lib, latest_ver))
    with open(f"../../benchmark/phase3/java_latest_release", "w") as outf:
        for p, v in result:
            outf.write(f"{p},{','.join(v)}\n")


def download_python_libraries(n_jobs: int, dest_folder: str):
    lib_whls = []
    with open("../../benchmark/phase3/pypi_releases.json") as inf:
        for lib, vw in json.load(inf).items():
            if not vw:
                continue
            lib_whls.append(lib, vw["latest_whl"])
    df = pd.DataFrame(lib_whls, columns=["name", "url"])
    df.to_csv("../../benchmark/phase3/py_latest_release", index=False, header=False)
    print(f"{len(df)} library wheels")
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


def download_java_libraries(n_jobs: int, dest_folder: str):
    latest_release_path = "../../benchmark/phase3/java_latest_release"
    if not os.path.exists(latest_release_path):
        get_latest_java_releases()
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


def deal_whl_data(root: dict[str, dict]):
    default_dir = [[], []]
    res = {"": [[d for d in root[""][0]], [f for f in root[""][1]]]}

    data_dir = None
    for top_dir in root[""][0]:
        if not top_dir.endswith(".data"):
            continue
        data_dir = top_dir

        res[""][0].remove(data_dir)
        for lib in ["platlib", "purelib"]:
            if lib not in root[data_dir][0]:
                continue

            lib_dir = root.get(f"{data_dir}/{lib}", default_dir)
            res[""][0].extend(lib_dir[0])
            res[""][1].extend(lib_dir[1])
        break
    if data_dir is None:
        return root

    platlib, purelib = f"{data_dir}/platlib", f"{data_dir}/purelib"
    for k, v in root.items():
        if k in ["", data_dir, platlib, purelib]:
            continue
        if k.startswith(platlib):
            res[k.replace(f"{platlib}/", "")] = v
        elif k.startswith(purelib):
            res[k.replace(f"{purelib}/", "")] = v
        else:
            res[k] = v

    return res


def construct_file_tree(filelist: list[str]) -> dict:
    root = {}

    def get_dir_dict(dir_name: str):
        d = root.get(dir_name)
        if d is None:
            d = root[dir_name] = [[], []]
        return d

    for f in filelist:
        if f.endswith("/"):
            continue
        f = f.strip("/")
        dirname, basename = os.path.split(f)
        if dirname == "/":
            continue
        dir_dict = get_dir_dict(dirname)
        dir_dict[1].append(basename)
        while dirname != "":
            par_name, name = os.path.split(dirname)
            par_dict = get_dir_dict(par_name)
            if name not in par_dict[0]:
                par_dict[0].append(name)
            dirname = par_name

    return root


def extract_import_prefixes(filepath: str, lang: str):
    if lang == "py":
        exts = (".py", ".so", ".pyd")
        exclude_dir = "."
    elif lang == "java":
        exts = (".class",)
        exclude_dir = "META-INF"
    with zipfile.ZipFile(filepath) as myzip:
        import_prefixes = []
        root = construct_file_tree(myzip.namelist())
        if lang == "py":
            root = deal_whl_data(root)

        for file in root[""][1]:
            if file.endswith(exts):
                import_prefixes.append(file.split(".")[0])
        for dir in root[""][0]:
            if exclude_dir in dir:
                continue

            dir_list = [dir]
            while dir_list:
                cur_dir = dir_list.pop(0)
                if lang == "py":
                    import_prefixes.append(cur_dir.replace("/", "."))
                sub_dir = root[cur_dir][0]
                sub_files = root[cur_dir][1]
                if any(f.endswith(exts) for f in sub_files):
                    if lang == "java":
                        import_prefixes.append(cur_dir.replace("/", "."))
                    continue
                dir_list.extend([f"{cur_dir}/{sd}" for sd in sub_dir])
        return import_prefixes


def extract(dest_folder: str, lang: str):
    latest_release_path = f"../../benchmark/phase3/{lang}_latest_release"
    lib_imports = {}

    with open(latest_release_path) as inf:
        for line in tqdm(inf, file=sys.stdout):
            entries = line.strip("\n").split(",")
            name = entries[0]
            if lang == "py":
                url = entries[-1]
                filename = url.split("/")[-1]
                path = os.path.join(dest_folder, "python", name, filename)
            elif lang == "java":
                version = entries[1]
                _, path = gen_jar_url_path(name, version)
                path = os.path.join(dest_folder, "java", path)

            logger.error(f"Processing {path} ...")
            if not os.path.exists(path):
                logger.error(f"{name}-{version}: {path} does not exist")
                continue
            try:
                imports = extract_import_prefixes(path, lang)
                if imports:
                    lib_imports[name] = imports
            except:
                logger.error(f"{name}-{version}: {path} extract imports error")

    with open(f"../../benchmark/phase3/{lang}_imports.json", "w") as outf:
        json.dump(lib_imports, outf)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python build_import_mappings.py",
        description="Download wheel/jar file of the latest release for each updated Python library / Java library and build import mappings",
    )
    parser.add_argument("-n", "--n_jobs", type=int, default=1, help="number of workers")
    parser.add_argument("-d", "--dest_folder", required=True, type=str)
    parser.add_argument(
        "--python", action="store_true", help="download Python library wheels"
    )
    parser.add_argument(
        "--java", action="store_true", help="download Java library jars"
    )
    parser.add_argument("--extract", action="store_true", help="extract import names")

    args = parser.parse_args()
    if args.python:
        download_python_libraries(args.n_jobs, args.dest_folder)
        if args.extract:
            extract(args.dest_folder, "py")
    if args.java:
        download_java_libraries(args.n_jobs, args.dest_folder)
        if args.extract:
            extract(args.dest_folder, "java")
