# Phase 4: API Mapping Extraction

##

`java_api_update_validator.py` downloads the sources jar of Java library release and check the exitence of an API in it. It has the following command line options:

```
usage: python java_api_update_validator.py [-h] [-n N_JOBS] [-d] [-c] --dest_folder DEST_FOLDER

Validate candidate Java library API update instances

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
  -d, --download        download sources jars
  -c, --check           check whether apis in each update instance exist in corresponding library release
  --dest_folder DEST_FOLDER
                        the folder to store downloaded sources jars
```
Run the following command to remove API update instances in the `java_candidate_api_update_instances` where APIs does not exist in corresponding Java library releases:
```shell
python mine_api_updates.py -d -c --dest_folder <DEST_FOLDER> -n <Number of processes, default 1>
```
In our experiments, we set `n` 128. It took about 1 hour to finish. The results are stored in the `java_existent_api_update_instances` collection in the `api_update` database.
