import argparse
import json
import logging
import math
import os
import sys

import pandas as pd
from joblib import Parallel, delayed
from parse_pom import parse_pom
from parse_pyproject import parse_pyproject_toml
from parse_requirements import parse_requirements
from parse_setup_cfg import parse_setup_cfg
from parse_setup_py import parse_setup_py
from tqdm import tqdm
from utils import read_blob

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

PARSERS = {
    "setup.cfg": parse_setup_cfg,
    "pyproject.toml": parse_pyproject_toml,
    "requirements.txt": parse_requirements,
    "pom.xml": parse_pom,
    "setup.py": parse_setup_py,
}


def split_blobs(blob_shas: list[str], batch_size: int = 1):
    for i in range(0, len(blob_shas), batch_size):
        yield blob_shas[i : i + batch_size]


# Function to process the blob hash and choose the type of parsing (POM or requirements.txt)
def single_process(
    blobs: list[str], configuration_file_type: str, save_path: str, idx: int
):
    result = {}
    missing = []
    parser = PARSERS[configuration_file_type]
    for blob in blobs:
        content = read_blob(blob)
        if content is None:
            missing.append(blob)
        else:
            result[blob] = parser(content)
    logger.error(f"Start dumping results for {configuration_file_type} batch {idx}...")
    with open(f"{save_path}.json.{idx}", "w") as outf:
        json.dump(result, outf)
    with open(f"{save_path}.missing.{idx}", "w") as outf:
        for b in missing:
            outf.write(f"{b}\n")


def main(configuration_file_type: str, num_workers: int, batch_size: int):
    print(f"{configuration_file_type}: ")
    source_path = os.path.join(
        "../benchmark", "commits", f"{configuration_file_type}_commits.csv"
    )
    save_path = os.path.join(
        "../benchmark", "deps", f"{configuration_file_type}_dependencies"
    )
    os.makedirs(os.path.join("../benchmark", "deps"), exist_ok=True)

    df = pd.read_csv(source_path, keep_default_na=False, low_memory=False)
    blob_shas = list(set(list(df["new blob"]) + list(df["old blob"])))
    print(f"\t{len(blob_shas)} unique blobs")
    del df
    blob_shas.sort()
    num_batches = math.ceil(len(blob_shas) / batch_size)
    print(f"\tnumber of batches: {num_batches}")

    batches = split_blobs(blob_shas, batch_size)
    Parallel(n_jobs=num_workers)(
        delayed(single_process)(blobs, configuration_file_type, save_path, i)
        for i, blobs in enumerate(tqdm(batches, total=num_batches, file=sys.stdout))
    )

    result = {}
    missing = []
    for i in range(num_batches):
        with open(f"{save_path}.json.{i}") as inf:
            data = json.load(inf)
            for k, v in data.items():
                result[k] = v
        os.remove(f"{save_path}.json.{i}")

        with open(f"{save_path}.missing.{i}") as inf:
            missing.extend(inf.read().splitlines())
        os.remove(f"{save_path}.missing.{i}")

    with open(f"{save_path}.json", "w") as outf:
        json.dump(result, outf)
    with open(f"{save_path}.missing", "w") as outf:
        for b in missing:
            outf.write(f"{b}\n")


if __name__ == "__main__":
    # Command-line arguments for blob hash and parse type
    parser = argparse.ArgumentParser(
        prog="python parser.py",
        description="Parse configuration blobs to extract dependencies",
    )
    parser.add_argument("-f", "--target_files", help="a list of filname separated by ,")
    parser.add_argument(
        "-n", "--num_workers", type=int, default=1, help="number of threads"
    )
    parser.add_argument(
        "-b",
        "--batch_size",
        type=int,
        default=1,
        help="number of blobs for each thread to process per batch",
    )

    args = parser.parse_args()
    target_files = args.target_files.split(",")
    print(target_files)

    for f in target_files:
        if f not in PARSERS:
            print(f"{f} is not supported")
            continue
        main(
            f,
            args.num_workers,
            args.batch_size,
        )
