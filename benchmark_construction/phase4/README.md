# Phase 4: Post Validation
This phase perform post validation on the candidate update instances mined in the last phase. The post validation consists of two checks: API existence in corresponding library releases and explicit deprecation descriptions in the definition of old API (Java annotator, Javadoc, Python decorator, docstring, etc).

## Download Sources Jars/Wheels
We first download all sources jars/wheels for Java/Python library releases involved in the candidate update instances.
[`download_libraries.py`](./download_libraries.py) has the following command line options:
```
usage: python download_libraries.py [-h] [--java] [--python] [--evaluation] [--validation] [-n N_JOBS] [-b BATCH_SIZE] -d DEST_FOLDER

Download the sources jars/latest wheel file for a list of Java/Python library leases

options:
  -h, --help            show this help message and exit
  --java                download sources jars. DEFAULT: False
  --python              download wheels. DEFAULT: False
  --evaluation          on ground truth dataset. DEFAULT: False
  --validation          on all candidate update instances. DEFAULT: False
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers. DEFAULT: 1
  -b BATCH_SIZE, --batch_size BATCH_SIZE
                        number of Python library releases to be processed. DEFAULT: 1
  -d DEST_FOLDER, --dest_folder DEST_FOLDER
                        folder to save downloaded libraries
```
Run the following command:
```shell
python download_libraries.py -d <DEST_FOLDER> -n <number of workers, default 1> --java --validation 2>../../log/download_libraries.log
python download_libraries.py -d <DEST_FOLDER> -n <number of workers, default 1> --python --validation 2>../../log/download_libraries.log
```
The `<DEST_FOLDER>` is the same with the one used in phase 3 for building import mappings.



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
