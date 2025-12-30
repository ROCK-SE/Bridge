# Phase 1: Update Commit Filtering
This phase identifies update commits from World of Code.

## Candidate Update Commits Filter
`filter_commits.py` filters out commits from the `c2fbb` gzipped maps that modify dependency configuration files of interest. We use the V3 version of World of Code whose data was collected in Mid May, 2024. Note that in our experiment time, the `c2fbb` gzipped maps are located at `/da7_data/basemaps/gz`. But their locations may change as the maintenance of World of Code servers. It has the following command line options:
```
usage: python filter_commits.py [-h] [-f TARGET_FILES] [-s SERVER] [-v VER] [-n NUM_WORKERS] [-u]

Query commits that modify specific files

options:
  -h, --help            show this help message and exit
  -f TARGET_FILES, --target_files TARGET_FILES
                        a list of filname separated by ,
  -s SERVER, --server SERVER
                        the server that stores the c2fbb mapping files
  -v VER, --ver VER     the version of c2fbb mappings
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
  -u, --update          requery if specified
```

Run the following command to query all commits that modify dependency configuration files in Java (`pom.xml`) and Python (`requirements.txt`, `setup.cfg`, `pyproject.toml`, `setup.py`) projects.
```shell
python filter_commits.py -f pom.xml,requirements.txt,setup.cfg,pyproject.toml,setup.py -s <default da7> -v <default V3> -n <Number of processes, default 1>
```
In our experiments, we set `n` as 8. It took about 12 hours to finish. The results are stored as `<target file>_candidate_update_commits.csv` files in the [benchmark/Phase1](../../benchmark/Phase1) folder. The csv file contains the following fields: `commit`, `filepath`, `new blob`, `old blob`, and `project`.

Please refer to [README.md in the `benchmark/Phase1` folder](../../benchmark/Phase1/README.md) for the statistics of result files.

## Dependency Parser
`parser.py` parses dependencies declared in the collected dependency configuration files. It takes as input the csv files obtained in the previous step, gets all unique blob shas (including both `new blob` and `old blob`), and parse dependencies in each blob using the parser (`parse_pom.py`, `parse_pyproject.py`, `parse_requirements.py`, `parse_setup_cfg.py`, `parse_setup_py.py`) corresponding to its configuration file.

It has the following command line options:
```
usage: python parser.py [-h] [-f TARGET_FILES] [-n NUM_WORKERS] [-b BATCH_SIZE]

Parse configuration blobs to extract dependencies

options:
  -h, --help            show this help message and exit
  -f TARGET_FILES, --target_files TARGET_FILES
                        a list of filname separated by ,
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
  -b BATCH_SIZE, --batch_size BATCH_SIZE
                        number of blobs for each thread to process per batch
```

Run the following command to parse all dependency configuration files collected in the above step.
```shell
python parser.py -f pom.xml,requirements.txt,setup.cfg,pyproject.toml,setup.py -n <Number of processes, default 1> -b <Number of blobs in a batch, default 1>
```
In our experiments, we set `n` and `b` as 128 and 5000. It took about 8 hours to finish. The results are stored as `<target file>_dependencies.json` files in the [benchmark/Phase1](../../benchmark/Phase1) folder. The json files have the same schema: `{blob sha: {package name: version constraints}}`.

Please refer to [README.md in the `benchmark/Phase1` folder](../../benchmark/Phase1/README.md) for the statistics of result files.

## Version Bumping Commit Extraction
`dep_update_commits.py` filters out commits that perform dependency version update and filters out packages not on the Maven or PyPI platform.

It has the following command line options:
```
usage: python dep_update_commits.py [-h] [-f TARGET_FILES] [-n NUM_WORKERS]

Obtain commits that update dependencies in the dependency configuration file

options:
  -h, --help            show this help message and exit
  -f TARGET_FILES, --target_files TARGET_FILES
                        a list of filname separated by ,
  -n NUM_WORKERS, --num_workers NUM_WORKERS
                        number of threads
```

Run the following command to parse all dependency configuration files collected in the above step.
```shell
python dep_update_commits.py -f pom.xml,requirements.txt,setup.cfg,pyproject.toml,setup.py -n <Number of processes, default 1>
```
In our experiment, we set `n` as 50. It tooks about 10 minutes to finish. The results are stored as `<target file>_updates.csv` files in the `../benchmark/updates` folder. The csv file has the following fields: `commit`, `filepath`, `new blob`, `old blob`, `package name`, `version in the old blob`, `version in the new blob`.

After obtaining the `<target file>_updates.csv` files, run the `dep_update_statistics.ipynb` Jupyter Notebook. It produces basic statistics displayed in the `../benchmark/README.md`. It also merge all `<target file>_updates.csv` files to the `../benchmark/updates/c2fpkgvvtype.csv` file.

Please refer to [README.md in the `../benchmark/updates` folder](../benchmark/updates/README.md) for the statistics of these files.
