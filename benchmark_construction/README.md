# Benchmark Construction

Before you proceed, you should first setup the environment for this step by following the instructions in the [INSTALL.md](../INSTALL.md).

## Commit Filtering
`filter_commits.py` filters out commits from the `c2fbb` gzipped maps that modify dependency configuration files of interest. It also extracts projects that contain these commits from the `c2P` gzipped maps. We use the V3 version of World of Code whose data was collected in Mid May, 2024. Note that in our experiment time, the `c2fbb` and `c2P` gzipped maps are located at `/da7_data/basemaps/gz`. But their locations may change as the maintenance of World of Code servers.

It has the following command line options:
```
usage: python filter_commits.py [-h] [-f TARGET_FILES] [-d DESTINATION_FOLDER] [-n NUM_WORKERS] [-u]

Query commits that modify specific files

options:
  -h, --help            show this help message and exit
  -f TARGET_FILES, --target_files TARGET_FILES
                        a list of filname separated by ,
  -d DESTINATION_FOLDER, --destination_folder DESTINATION_FOLDER
                        the folder to save query results
  -n NUM_WORKERS, --num_workers NUM_WORKERS
                        number of threads
  -u, --update          update results
```

Run the following command to query all commits that modify dependency configuration files in Java (`pom.xml`) and Python (`requirements.txt`, `setup.cfg`, `pyproject.toml`, `setup.py`) projects.
```shell
python filter_commits.py -f pom.xml,requirements.txt,setup.cfg,pyproject.toml,setup.py -d <Folder to save query results> -n <Number of processes, recommended 8 on the world of code server>
```
The results are stored as `<target file>_commits.csv` files in the `commits` subfolder of destination folder. In our study, we specify `-d`'s argument as `benchmark`. The csv file contains the following fields: `commit`, `filepath`, `new blob`, `old blob`, and `project`.

## Dependency Parsing
`parser.py` parses dependencies declared in the collected dependency configuration files. It takes as input the csv files obtained in the previous step, gets all unique blob shas (including both `new blob` and `old blob`), and parse dependencies in each blob.

It has the following command line options:
```
usage: python parser.py [-h] [-t CONFIGURATION_FILE_TYPE] [-d DIRECTORY] [-n NUM_WORKERS] [-b BATCH_SIZE]

Parse configuration blobs to extract dependencies

options:
  -h, --help            show this help message and exit
  -t CONFIGURATION_FILE_TYPE, --configuration_file_type CONFIGURATION_FILE_TYPE
                        type of configuration file
  -d DIRECTORY, --directory DIRECTORY
                        the directory to read commits and save results
  -n NUM_WORKERS, --num_workers NUM_WORKERS
                        number of threads
  -b BATCH_SIZE, --batch_size BATCH_SIZE
                        number of blobs for each thread to process per batch
```

Run the following command to parse all dependency configuration files collected in the above step.
```shell
# `all` indicates all types of dependency configuration files. You can also specify pom.xml, setup.cfg, pyproject.toml, requirements.txt, setup.py as the argument.
python parser.py -t all -d <Folder to save query results> -n <Number of processes, recommended 4> -b <Number of blobs in a batch>
```
The results are stored as `<target file>_dependencies.json` files in the `deps` subfolder of destination folder. In our study, we specify `-d`'s argument as `benchmark`. The json file has the following diagram: `{blob sha: {package name: version constraints}}`.

## Version Update Extraction
`dep_update_commits.py` filters out commits that perform dependency version update.

It has the following command line options:
```
usage: python dep_update_commits.py [-h] [-t CONFIGURATION_FILE_TYPE] [-d DIRECTORY] [-n NUM_WORKERS]

Obtain commits that update dependencies in the dependency configuration file

options:
  -h, --help            show this help message and exit
  -t CONFIGURATION_FILE_TYPE, --configuration_file_type CONFIGURATION_FILE_TYPE
                        type of configuration file
  -d DIRECTORY, --directory DIRECTORY
                        the directory to read commits and save results
  -n NUM_WORKERS, --num_workers NUM_WORKERS
                        number of threads
```

Run the following command to parse all dependency configuration files collected in the above step.
```shell
# `all` indicates all types of dependency configuration files. You can also specify pom.xml, setup.cfg, pyproject.toml, requirements.txt, setup.py as the argument.
python dep_update_commits.py -t all -d <Folder to save query results> -n <Number of processes>
```
The results are stored as `<target file>_updates.csv` files in the `updates` subfolder of destination folder. In our study, we specify `-d`'s argument as `benchmark`. The csv file has the following fields: `commit`, `filepath`, `new blob`, `old blob`, and `update pairs`. The `update pairs` filed is a list where each element is a `(package name, version in new blob, version in old blob)` tuple.
