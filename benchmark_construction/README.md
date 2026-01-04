# Benchmark Construction

Before you proceed, you should first setup the environment for this step by following the instructions in the [INSTALL.md](../INSTALL.md).

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
