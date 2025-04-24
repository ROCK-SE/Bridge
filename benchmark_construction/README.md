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
The results are stored as `<target file>_dependencies.json` files in the `../benchmark/deps` folder. The json file has the following diagram: `{blob sha: {package name: version constraints}}`.

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
