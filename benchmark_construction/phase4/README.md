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


## Perform Post Validation
`post_validation.py` resolves the signature of API call in corresponding library versions and validates the validity of mined candidate update instances. It has the following command line options:
```
usage: python post_validation.py [-h] [--java] [--python] [-n N_JOBS]

Perform post validation on mined candidate update instances.

options:
  -h, --help            show this help message and exit
  --java                validate Java update instances. DEFAULT: False
  --python              validate Python update instances. DEFAULT: False
  -n N_JOBS, --n_jobs N_JOBS
                        the number of workers. DEFAULT: 1
```
Run the following command to perform post validation:
```shell
python post_validation.py -n <Number of workers, default 1> --python --java
```
In our experiments, we set `n` 128. It took about 2 hours to finish. The results are stored in the `java_candidate_update_instances` and `py_candidate_update_instances` collections in the `bridge` database.
