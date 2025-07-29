# Benchmark Construction

Before you proceed, you should first setup the environment for this step by following the instructions in the [INSTALL.md](../INSTALL.md).

## Commit Filtering
`filter_commits.py` filters out commits from the `c2fbb` gzipped maps that modify dependency configuration files of interest. We use the V3 version of World of Code whose data was collected in Mid May, 2024. Note that in our experiment time, the `c2fbb` gzipped maps are located at `/da7_data/basemaps/gz`. But their locations may change as the maintenance of World of Code servers.

It has the following command line options:
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
  -n NUM_WORKERS, --num_workers NUM_WORKERS
                        number of threads
  -u, --update          requery if specified
```

Run the following command to query all commits that modify dependency configuration files in Java (`pom.xml`) and Python (`requirements.txt`, `setup.cfg`, `pyproject.toml`, `setup.py`) projects.
```shell
python filter_commits.py -f pom.xml,requirements.txt,setup.cfg,pyproject.toml,setup.py -s <default da7> -v <default V3> -n <Number of processes, default 1>
```
In our experiments, we aet `n` as 8. It took about 12 hours to finish. The results are stored as `<target file>_commits.csv` files in the `../benchmark/commits` folder. The csv file contains the following fields: `commit`, `filepath`, `new blob`, `old blob`, and `project`.

Please refer to [README.md in the `benchmark/commits` folder](../benchmark/commits/README.md) for the statistics of result files.

## Dependency Parsing
`parser.py` parses dependencies declared in the collected dependency configuration files. It takes as input the csv files obtained in the previous step, gets all unique blob shas (including both `new blob` and `old blob`), and parse dependencies in each blob using the parser (`parse_pom.py`, `parse_pyproject.py`, `parse_requirements.py`, `parse_setup_cfg.py`, `parse_setup_py.py`) corresponding to its configuration file.

It has the following command line options:
```
usage: python parser.py [-h] [-f TARGET_FILES] [-n NUM_WORKERS] [-b BATCH_SIZE]

Parse configuration blobs to extract dependencies

options:
  -h, --help            show this help message and exit
  -f TARGET_FILES, --target_files TARGET_FILES
                        a list of filname separated by ,
  -n NUM_WORKERS, --num_workers NUM_WORKERS
                        number of threads
  -b BATCH_SIZE, --batch_size BATCH_SIZE
                        number of blobs for each thread to process per batch
```

Run the following command to parse all dependency configuration files collected in the above step.
```shell
python parser.py -f pom.xml,requirements.txt,setup.cfg,pyproject.toml,setup.py -n <Number of processes, default 1> -b <Number of blobs in a batch, default 1>
```
In our experiments, we set `n` and `b` as 128 and 5000. It took about 8 hours to finish. The results are stored as `<target file>_dependencies.json` files in the `../benchmark/deps` folder. The json files have the same schema: `{blob sha: {package name: version constraints}}`.

Please refer to [README.md in the `../benchmark/deps` folder](../benchmark/deps/README.md) for the statistics of result files.

## Version Update Extraction
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

## Update Behavior Commits Extraction
First run `nearby_commits.sh` to get the previous and after 2 commits of the dependency update commits. It produces the `c.pc.ppc.cc.ccc` file in the `../benchmark/updates` folder, where the five columns corresponds to the dependency update commit, parent commits, parent commit's parent commit, child commit, child commit's child commit, respectively. Note that the `c` column includes all commits that modify the 5 kinds of dependency specification files.

Then run `extract_blob.sh` to filter out the above commits that modify java files (with `.java` extension) or python files (with `.py` extension) and to extract blob shas before and after the commit. It produces `c2fbb` file in the `../benchmark/updates` folder consisting of 4 fields: `commit sha,filepath,new blob sha,old blob sha`. It also produces `javablob.idx` and `pyblob.idx` files that stores each Java or Python blob's offset and length in corresponding `blob_{0..127}.bin` files. These ".idx" files are for efficient blob content retrieval from very large ".bin" files.

Please refer to [README.md in the `../benchmark/updates` folder](../benchmark/updates/README.md) for the statistics of these files.

## Build Import Mappings
`query_package_versions.py` obtains all versions released before 2024-06-01 for each updated Java/Python packages. The Java package release information is obtained via the [deps.dev API](https://docs.deps.dev/api/v3/), while the Python package release information is obtained via [PyPI Index API](https://docs.pypi.org/api/index-api/#json_1). It has the following command line options:
```
usage: python query_package_versions.py [-h] [-n N_JOBS] [-b BATCH_SIZE]

Query Deps.dev API and PyPI API to obtain all versions of updated Java/Python packages

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
  -b BATCH_SIZE, --batch_size BATCH_SIZE
                        number of packages to be processed
```

Run the following command:
```shell
python query_package_versions.py -n <Number of processes, default 1> -b <Number of blobs in a batch, default 100>
```
Optionally, you can specify your email address and proxies in `config.json` which are used in the header and proxies to comply and speed up the requests.
In our experiments, we set `n` as 50 and use IP pools to speed up the process. It took about 30 minutes to finish. The results are store as `maven_releases.json` and `pypi_releases.json` in the `../benchmark/updates` folder for Java packages and Python packages, respectively. The `maven_releases.json` file has the following schema: `packsage name: [versions]`. The `pypi_releases.json` file has the following schema: `packsage name: {version: distribution file url}`.

Then `build_import_mappings.py` downloads the jar/wheel file for the latest release of each updated Java/Python package and extracts import names for each Java/Python package. Here, we assume that the import names of each Java/Python package are consistent across releases to reduce the network workload. It has the following command line options:
```shell
usage: python build_import_mappings.py [-h] [-n N_JOBS] -d DEST_FOLDER [--python] [--java] [--extract]

Download wheel/jar file of the latest release for each updated Python package / Java library and build import mappings

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
  -d DEST_FOLDER, --dest_folder DEST_FOLDER
  --python              download Python package wheels
  --java                download Java package jars
  --extract             extract import names
```
Run the following command to construct the import name database:
```shell
python build_import_mappings.py -d <DEST_FOLDER> --python --java --extract -n <N_JOBS>
```
Optionally, you can specify the mirror site of PyPI in `config.json` to reduce the network bandwith burden of PyPI service and speed up the download process.
In our experiments, we set `n` as 128. It took about 4 hours to finish. It takes approximately 96G to store the Java package jars and Python package wheels. So please ensure that the <DEST_FOLDER> has sufficient spaces. The results are stored as `py_imports.json` and `java_imports.json` in the `../benchmark/updates` folder. They share the same schema: `package name: [import names]`.

Please refer to [README.md in the `../benchmark/updates` folder](../benchmark/updates/README.md) for the statistics of these files.

## Dump Data to MongoDB
`dump_data.py` dumps the above obtained data into three collections in the `api_update` MongoDB database. Specifically, `../benchmark/updates/c2fpkgvvtype.csv` is dumped into `py_dependency_updates` and `java_dependency_updates` collections; `../benchmark/updates/c2fbb` is dumpted into `blob_changes` collection. It has the following command line options:
```
usage: python dump_data.py [-h] [-d] [-b]

Dump dependency update info and blob change info for commits and api call info for modified blobs to MongoDB.

options:
  -h, --help            show this help message and exit
  -d, --dependency_updates
                        dump dependency update info for commits
  -b, --blob_changes    dump blob change info for commits
```

Run the following command to dump data into MongoDB collections.
```shell
python dump_data.py -d -b
```
Please refer to [README.md in the `../benchmark/db` folder](../db/README.md) for the statistics of these collections.


## Parse API Calls
`parse_api_calls.py` parses API calls in Java/Python code files and store them to MongoDB collections. For Java, we deal with object type resolution and access chain identification. For Python, we deal with alias resolution and access chain identification. It has the following command line options:
```
usage: python parse_api_calls.py [-h] [-n N_JOBS] [-b BATCH_SIZE] [--python] [--java]

Parse api calls in Java/Python files and store them in MongoDB collections

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
  -b BATCH_SIZE, --batch_size BATCH_SIZE
                        number of blobs to processed in a batch
  --python              Parse Python files
  --java                Parse Java files
```
Run the following command to parse API calls for all Java/Python blobs obtained in above steps.
```shell
python parse_api_calls.py --java --python -n <Number of processes, default 1> -b <Number of blobs in a batch, default 1>
```
In our experiments, we set `n` and `b` as 512, 6000 and 512, 2000 for Java and Python, respectively. It took about 16 hours and 6 hours to finish. The results are stored to `java_api_calls`  and `py_api_calls` collections in the `api_update` database for Java and Python, respectively.

Please refer to [README.md in the `../benchmark/db` folder](../db/README.md) for the statistics of these collections.

## Mine API Update Mappings
`mine_api_updates.py` mines Java/Python API update mappings from the API call changes between old and new blobs. It has the following command line options:
```
usage: python mine_api_updates.py [-h] [-n N_JOBS] [-b BATCH_SIZE] [--nearby] [--java] [--python]

Mine API Updates based on the API call changes between the new and old blobs.

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        the number of workers
  -b BATCH_SIZE, --batch_size BATCH_SIZE
                        the number of records per batch
  --nearby              get api call changes
  --java                mine candidate api update instances for Java
  --python              mine candidate api update instances for Python
```
Run the following command to parse API calls for all Java/Python blobs obtained in above steps.
```shell
python mine_api_updates.py --nearby --java --python  -n <Number of processes, default 1> -b <Number of blobs in a batch, default 1>
```
In our experiments, we set `n` and `b` as 128, 10000 and 64, 10000 for Java and Python, respectively. It took about 40 minutes to finish. The results for api call changes are stored in the `java_api_call_changes` and `py_api_call_changes` collection in the `api_update` database for Java and Python, respectively. The results for candidate API updates are stored in the `java_candidate_api_update_instances` and `py_candidate_api_update_instances` collection in the `api_update` database for Java and Python, respectively.

`java_api_update_validator.py` downloads the sources jar of Java package release and check the exitence of an API in it. It has the following command line options:

```
usage: python java_api_update_validator.py [-h] [-n N_JOBS] [-d] [-c] --dest_folder DEST_FOLDER

Validate candidate Java library API update instances

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
  -d, --download        download sources jars
  -c, --check           check whether apis in each update instance exist in corresponding package release
  --dest_folder DEST_FOLDER
                        the folder to store downloaded sources jars
```
Run the following command to remove API update instances in the `java_candidate_api_update_instances` where APIs does not exist in corresponding Java package releases:
```shell
python mine_api_updates.py -d -c --dest_folder <DEST_FOLDER> -n <Number of processes, default 1>
```
In our experiments, we set `n` 128. It took about 1 hour to finish. The results are stored in the `java_existent_api_update_instances` collection in the `api_update` database.

Please refer to [README.md in the `../benchmark/db` folder](../db/README.md) for the statistics of these collections.

## Construct the Benchmark Dataset
`compile_java_dataset.ipynb` and `compile_python_dataset.ipynb` construct benchmark datasets for Java and Python, respectively.
The first 8 cells in the two Jupyter Notebooks sample API update mappings and produces files `{java,python}_api_update_rules_{gte10,1to10,eq1}.xlsx` in the `../benchmark/final` folder.
`{java,python}_api_update_rules_{gte10,1to10,eq1}-labelled.xlsx` files in the `../benchmark/final` folder contains the labelled results and corresponding evidences. Then, run cell 9-10 to estimate the overall accuracy of the mined API update mappings.

Next, run cell 11-17 to compile the API update pairs datasets, which include the following files in the `../benchmark/final` folder:
- `{java,python}_labelled_rules.csv`. Each row corresponds to a sampled mapping with following fields: `package` (string), `old_api` (string), `new_api` (string), `commit` (string), `correct` (1 for correct and 0 for incorrect/unsure), `evidence` (string).
- `{java,python}_api_update_rules_exact.json`. Each record corresponds to an verified correct API update mapping and has the following fields: `package` (string), `old_api` (string), and `old_api` (a list of strings, since we can not infer the API's parameter types or an old API may have multiple replacement APIs).
- `{java,python}_api_update_rules_full.json`. Similar to the above files, except that it consists of all API update mappings.
- `{java,python}_api_pairs_exact.json`. Each record corresponds to an API update pair of a verified correct API update mapping. It has the following fields: `package` (string), `old_api` (string), `new_api` (string), `old_version` (string), `new_version` (string).
- `{java,python}_api_pairs_full.json`. Similar to the above files, except that it consists of all API update pairs of all API update mapping.
- `{java,python}_commit_pairs_exact.json`. Each record corresponds to a verified correct API update pair with the commit introducing the pair. It has the same fields as `{java,python}_api_pairs_exact.json` with an additional `commit` field.
- `{java,python}_commit_pairs_full.json`. Similar to the above files, except that it consists of all API update pairs of all API update mapping.
- **`{java,python}_sampled_api_pairs_exact.json`**. Sample API update pairs for each API update mappings from `{java,python}_api_pairs_exact.json` based on the version update types of each pair. **It is used as the final benchmark to evaluate LLMs on the recommending replacement API task.**
- **`{java,python}_sampled_api_pairs_full.json`**. Sample API update pairs for each API update mappings from `{java,python}_api_pairs_full.json` based on the version update types of each pair. **It is used as the final benchmark to evaluate LLMs on the recommending replacement API task.**

After that, run `extract_java_snippets.py` and `extract_python_snippets.py` to extract API update instances for all Java/Python API update pairs in the exact and full groups. They has the following options:
```
usage: python extract_java_snippets.py [-h] [-n N_JOBS]

Extract methods for Java API update pairs

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers

usage: python extract_python_snippets.py [-h] [-n N_JOBS]

Extract functions for Python update pairs

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
```

Run the following commands to extract API update instances:
```shell
python extract_java_snippets.py -n <Number of processes, default 1>
python extract_python_snippets.py -n <Number of processes, default 1>
```
In our experiments, we set `n` 128. It took about 40 minutes to finish and produces the following files in the `../benchmark/final` folder:
- `{java,python}_update_instances_full.json`. Each record corresponds to a record in corresponding `{java,python}_commit_pairs_full.json` files with four additional fields: `old_code`, `old_args`, `new_code`, `new_args`.
- `{java,python}_update_instances_exact.json`. Similar to the above files, except that each record corresponds to a record in corresponding `{java,python}_commit_pairs_exact.json` files

Finally, run the last cell in the two Jupyter Notebooks to sample instances for the two groups and produce the following files in the `../benchmark/final` folder:
-  **`{java,python}_sampled_update_instances_exact.json`**. Sample API update instances for each API update mappings from `{java,python}_update_instances_exact.json` based on the version update types of each pair. **It is used as the final benchmark to evaluate LLMs on the recommending replacement API task in our paper.**
-  `{java,python}_sampled_update_instances_full.json`. Sample API update instances for each API update mappings from `{java,python}_update_instances_full.json` based on the version update types of each pair. We do not use this dataset to evaluate LLMs on the recommending replacement API task in our paper due to the budget limit.

Please refer to [README.md in the `../benchmark/final` folder](../benchmark/final/README.md) for the statistics of these files.
