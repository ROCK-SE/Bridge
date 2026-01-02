import argparse

import pandas as pd

CONFIG_files = [
    "setup.cfg",
]

for f in CONFIG_files:
    df = pd.read_csv(
        f"../../benchmark/Phase1/{f}_version_bumping_commits.csv"
    ).drop_duplicates()
    print(f"{len(df)} unique version dumping commits for {f} in total")
    df["section"] = df["commit"].apply(lambda x: int(x[:2], base=16) % 128)
    for i in range(128):
        with open(f"../../benchmark/Phase1/{f}_commits.{i}", "w") as outf:
            shas = list(df[df["section"] == i]["commit"])
            shas.sort()
            for c in shas:
                outf.write(f"{c}\n")
