import pandas as pd

config_files = [
    "pom.xml",
    "requirements.txt",
    "setup.py",
    "pyproject.toml",
    "setup.cfg",
]

for f in config_files:
    df = pd.read_csv(
        f"../../benchmark/phase1/{f}_version_bumping_commits.csv"
    ).drop_duplicates()
    print(f"{len(df)} unique version dumping commits for {f} in total")
    df["section"] = df["commit"].apply(lambda x: int(x[:2], base=16) % 128)
    for i in range(128):
        with open(f"../../benchmark/phase1/{f}_commits.{i}", "w") as outf:
            shas = list(df[df["section"] == i]["commit"])
            shas.sort()
            for c in shas:
                outf.write(f"{c}\n")
