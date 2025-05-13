# Benchmark Construction

Before you proceed, you should first setup the environment for this step by following the instructions in the [INSTALL.md](../INSTALL.md).

## Commit Filtering
`filter_commits.py` filters out commits from the `c2fbb` gzipped maps that modify dependency configuration files of interest. It also extracts projects that contain these commits from the `c2P` gzipped maps. We use the V3 version of World of Code whose data was collected in Mid May, 2024. Note that in our experiment time, the `c2fbb` and `c2P` gzipped maps are located at `/da7_data/basemaps/gz`. But their locations may change as the maintenance of World of Code servers.

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
The results are stored as `<target file>_commits.csv` files in the `../benchmark/commits` folder. The csv file contains the following fields: `commit`, `filepath`, `new blob`, `old blob`, and `project`.

## Dependency Parsing
`parser.py` parses dependencies declared in the collected dependency configuration files. It takes as input the csv files obtained in the previous step, gets all unique blob shas (including both `new blob` and `old blob`), and parse dependencies in each blob.

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
The results are stored as `<target file>_dependencies.json` files in the `../benchmark/deps` folder. The json file has the following schema: `{blob sha: {package name: version constraints}}`.

## Version Update Extraction
`dep_update_commits.py` filters out commits that perform dependency version update.

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
The results are stored as `<target file>_updates.csv` files in the `../benchmark/updates` folder. The csv file has the following fields: `commit`, `filepath`, `new blob`, `old blob`, and `update pairs`. The `update pairs` filed is a list where each element is a `(package name, version in new blob, version in old blob)` tuple.

After obtaining the `<target file>_updates.csv` files, run the `dep_update_statistics.ipynb` Jupyter Notebook. It produces basic statistics displayed in the `../benchmark/README.md`. It also merge all `<target file>_updates.csv` files to the `../benchmark/updates/c2fpkgvvtype.csv` file.

## Update Behavior Commits Extraction
First run `nearby_commits.sh` to get the 2 commits before and after the dependency update commits, respectively. It produces the `c.pc.ppc.cc.ccc` file where the five columns corresponds to the dependency update commit, parent commits, parent commit's parent commit, child commit, child commit's child commit, respectively. Note that the `c` column includes all commits that modify the 5 kinds of dependency specification files.

Then run `extract_blob.sh` to filter out the above commits that modify java files (with `.java` extension) or python files (with `.py` extension) and to extract blob shas before and after the commit. It produces `c2fbb` file consisting of 4 fields: `commit sha,filepath,new blob sha,old blob sha`. It also produces `javablob_{0..127}.idx` and `pyblob_{0..127}.idx` files that stores each Java or Python blob's offset and length in corresponding `blob_{0..127}.bin` files. These ".idx" files are for efficient blob content retrieval from very large ".bin" files.


# Construct Import Name Database
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
The results are store as `maven_releases.json` and `pypi_releases.json` in the `../benchmark/updates` folder for Java packages and Python packages, respectively. The `maven_releases.json` file has the following schema: `packsage name: [versions]`. The `pypi_releases.json` file has the following schema: `packsage name: {version: distribution file url}`.

Then `extract_import_prefixes.py` downloads the jar/wheel file for the latest release of each updated Java/Python package and extracts import names for each Java/Python package. Here, we assume that the import names of each Java/Python package are consistent across releases to reduce the network workload. It has the following command line options:
```shell
usage: python extract_import_prefixes.py [-h] [-n N_JOBS] -d DEST_FOLDER [--python] [--java] [--extract]

Download wheel/jar file of the latest release for each updated Python package / Java library and extract import names

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
python extract_import_prefixes.py -d <DEST_FOLDER> --python --java --extract -n <N_JOBS>
```
It takes approximately 96G to store the Java package jars and Python package wheels. So please ensure that the <DEST_FOLDER> has sufficient spaces. The results are stored as `py_imports.json` and `java_imports.json` in the `../benchmark/updates` folder. They share the same schema: `package name: [import names]`.
