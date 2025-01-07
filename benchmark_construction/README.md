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
