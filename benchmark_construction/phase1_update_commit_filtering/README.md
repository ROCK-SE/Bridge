# Phase 1: Update Commit Filtering
This phase identifies update commits from World of Code. The data files obtained in this phase are stored in the [benchmark/Phase1](../../benchmark/Phase1) folder. Please refer to [README.md in the `benchmark/Phase1` folder](../../benchmark/Phase1/README.md) for the statistics of result files.

## Filter Candidate Update Commits
`filter_candidate_update_commits.py` filters out commits from the `c2fbb` gzipped maps that modify dependency configuration files of interest. We use the V3 version of World of Code whose data was collected in Mid May, 2024. Note that in our experiment time, the `c2fbb` gzipped maps are located at `/da7_data/basemaps/gz`. But their locations may change as the maintenance of World of Code servers. It has the following command line options:
```
usage: python filter_candidate_update_commits.py [-h] [-f TARGET_FILES] [-s SERVER] [-v VER] [-n N_JOBS] [-u]

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
python filter_candidate_update_commits.py -f pom.xml,requirements.txt,setup.cfg,pyproject.toml,setup.py -s <default da7> -v <default V3> -n <Number of processes, default 1>
```
In our experiments, we set `n` as 8. It took about 12 hours to finish. The results are stored as `<target file>_candidate_update_commits.csv` files. The csv file contains the following fields: `commit sha,filepath,new blob sha,old blob sha,project`.

## Parsing Dependencies
`parse_dependencies.py` parses dependencies declared in the collected dependency configuration files. It takes as input the csv files obtained in the previous step, gets all unique blob shas (including both `new blob` and `old blob`), and parse dependencies in each blob using the parser (`parse_pom.py`, `parse_pyproject.py`, `parse_requirements.py`, `parse_setup_cfg.py`, `parse_setup_py.py`) corresponding to its configuration file.

It has the following command line options:
```
usage: python parse_dependencies.py [-h] [-f TARGET_FILES] [-n N_JOBS] [-b BATCH_SIZE]

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
python parse_dependencies.py -f pom.xml,requirements.txt,setup.cfg,pyproject.toml,setup.py -n <Number of processes, default 1> -b <Number of blobs in a batch, default 1>
```
In our experiments, we set `n` and `b` as 128 and 5000. It took about 8 hours to finish. The results are stored as `<target file>_dependencies.json` files. The json files have the same schema: `{blob sha: {package name: version constraints}}`.

## Identify Version Bumping Commits
`identify_version_bumping_commits.py` filters out commits that perform dependency version update and filters out packages not on the Maven or PyPI platform.

It has the following command line options:
```
usage: python identify_version_bumping_commits.py [-h] [-f TARGET_FILES] [-o] [-n N_JOBS]

Obtain commits that update dependencies in the dependency configuration file

options:
  -h, --help            show this help message and exit
  -f TARGET_FILES, --target_files TARGET_FILES
                        a list of filname separated by ,
  -o, --other_constraint
                        consider other version constraints, not fixed version constraint by default
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
```

Run the following command to parse all dependency configuration files collected in the above step.
```shell
python identify_version_bumping_commits.py -f pom.xml,requirements.txt,setup.cfg,pyproject.toml,setup.py -o -n <Number of processes, default 1>
```
In our experiment, we set `n` as 50. It tooks about 10 minutes to finish. The results are stored as `<target file>_version_bumping_commits.csv` files. The csv file has the following fields: `commit,filepath,new blob,old blob,package name,version in the old blob,version in the new blob`.
We also provide a `-o` option to identify commits that involve non-fixed version constraints changes. The results are stored as `<target file>_version_changing_commits.csv`

After obtaining the `<target file>_version_bumping_commits.csv` files, run the `dep_update_statistics.ipynb` Jupyter Notebook. It produces basic statistics displayed in the `../benchmark/README.md`. It also merge all `<target file>_version_bumping_commits.csv` files to the `../benchmark/updates/c2fpkgvvtype.csv` file.

## Identify Update Commits
First run `identify_update_commits.sh` to identify update commits for each configuration file. The results are stored as `<target file>_update_commits` files. Each file has the following fields: `commit sha;filepath;new blob sha;old blob sha`.

Then run `extract_blob.sh` to filter out the above commits that modify java files (with `.java` extension) or python files (with `.py` extension) and to extract blob shas before and after the commit. It produces `c2fbb` file in the `../benchmark/updates` folder consisting of 4 fields: `commit sha,filepath,new blob sha,old blob sha`. It also produces `javablob.idx` and `pyblob.idx` files that stores each Java or Python blob's offset and length in corresponding `blob_{0..127}.bin` files. These ".idx" files are for efficient blob content retrieval from very large ".bin" files.
