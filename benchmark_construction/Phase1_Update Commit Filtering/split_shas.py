import argparse

import pandas as pd


def split(
    filename: str,
    column: int,
    prefix: str,
    num_sections: int = 32,
    skiprows: int = 0,
    sep: str = ",",
):
    df = pd.read_csv(
        f"../benchmark/updates/{filename}",
        sep=sep,
        usecols=[column],
        skiprows=skiprows,
        names=["sha"],
    ).drop_duplicates()
    print(f"{len(df)} unique shas in total")

    df["section"] = df["sha"].apply(lambda x: int(x[:2], base=16) % num_sections)
    print(df["section"].value_counts().sort_index())
    for i in range(num_sections):
        with open(f"../benchmark/updates/{prefix}.{i}", "w") as outf:
            shas = list(df[df["section"] == i]["sha"])
            shas.sort()
            for c in shas:
                outf.write(f"{c}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python split_sha.py",
        description="Split large chunks of shas into sections",
    )
    parser.add_argument("-f", "--filename", help="the csv file name")
    parser.add_argument("-c", "--column", type=int, help="the sha column")
    parser.add_argument("-p", "--prefix", help="file prefix to store the splited shas")
    parser.add_argument(
        "-n", "--num_sections", type=int, default=32, help="number of sections to split"
    )
    parser.add_argument(
        "-s", "--skiprows", type=int, default=0, help="path to the csv file"
    )
    parser.add_argument("-d", "--sep", default=",", help="separator in the csv file")
    args = parser.parse_args()
    split(
        args.filename,
        args.column,
        args.prefix,
        args.num_sections,
        args.skiprows,
        args.sep,
    )
