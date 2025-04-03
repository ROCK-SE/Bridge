# Benchmark Construction

Before you proceed, you should first setup the environment for this step by following the instructions in the [INSTALL.md](../INSTALL.md).

## Commit Filtering
`filter_commits.py` has several command line options:
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

Run the following command to query all commits that modify dependency configuration files in Java (`pom.xml`) and Python (`requirements.txt`, `setup.cfg`, `pyproject.toml`, `setup.py`) projects
```shell
python filter_commits.py -f pom.xml,requirements.txt,setup.cfg,pyproject.toml,setup.py -d <Folder to save query results> -n <Number of processes, recommended 4>
```

## Dependency Parsing
`parser.py` has several command line options:
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
