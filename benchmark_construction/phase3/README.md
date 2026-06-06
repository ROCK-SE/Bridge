# Phase 3: Update Instance Identification
This phase identifies update instances via API call similarity metrics. The data files obtained in this phase are stored in the [benchmark/phase3](../../benchmark/phase3) folder. Please refer to [README.md in the `benchmark/phase3` folder](../../benchmark/phase3/README.md) for the statistics of result files.

## Build Import Mappings
[`query_library_versions.py`](./query_library_versions.py) obtains all versions released before 2024-06-01 for each updated Java/Python library. The Java library release information is obtained via the [deps.dev API](https://docs.deps.dev/api/v3/), while the Python library release information is obtained via [PyPI Index API](https://docs.pypi.org/api/index-api/#json_1). It has the following command line options:
```
usage: python query_library_versions.py [-h] [-n N_JOBS] [-b BATCH_SIZE]

Query Deps.dev API and PyPI API to obtain all versions of updated Java/Python libraries

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers. DEFAULT: 1
  -b BATCH_SIZE, --batch_size BATCH_SIZE
                        number of libraries to be processed. DEFAULT: 100
```

Run the following command:
```shell
python query_library_versions.py -n <Number of processes, default 1> -b <Number of blobs in a batch, default 100>
```
Optionally, you can specify your email address and proxies in `config.json` which are used in the header and proxies to comply and speed up the requests.
In our experiments, we set `n` as 50 and use IP pools to speed up the process. It took about 30 minutes to finish. The results are store as `maven_releases.json` and `pypi_releases.json` in the [benchmark/phase3](../../benchmark/phase3/) folder for Java libraries and Python libraries, respectively. The `maven_releases.json` file has the following schema: `library name: [versions]`. The `pypi_releases.json` file has the following schema: `library name: {version: distribution file url}`.

Then [`build_import_mappings.py`](./build_import_mappings.py) downloads the jar/wheel file for the latest release of each updated Java/Python library and extracts import names for each Java/Python library. Here, we assume that the import names of each Java/Python library are consistent across releases to reduce the network workload. It has the following command line options:
```shell
usage: python build_import_mappings.py [-h] [-n N_JOBS] -d DEST_FOLDER [--python] [--java] [--extract]

Download wheel/jar file of the latest release for each updated Python library / Java library and build import mappings

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers. DEFAULT: 1
  -d DEST_FOLDER, --dest_folder DEST_FOLDER
  --python              download Python library wheels. DEFAULT: False
  --java                download Java library jars. DEFAULT: False
  --extract             extract import names. DEFAULT: False
```
Run the following command to construct the import name database:
```shell
python build_import_mappings.py -d <DEST_FOLDER> --python --java --extract -n <N_JOBS>
```
Optionally, you can specify the mirror site of PyPI in `config.json` to reduce the network bandwith burden of PyPI service and speed up the download process.
In our experiments, we set `n` as 128. It took about 4 hours to finish. It takes approximately 96G to store the Java library jars and Python library wheels. So please ensure that the <DEST_FOLDER> has sufficient spaces. The results are stored as `py_imports.json` and `java_imports.json` files. They share the same schema: `library name: [import names]`.

## Detect API Call Discrepancies
[`detect_api_call_changes.py`](./detect_api_call_changes.py) detects API call discrepancies between the old and new blobs. In this process, it removes updates whose library version does not exist on Maven/PyPI or whose library does have importable code files. It has the following command line options:
```
usage: python detect_api_call_changes.py [-h] [-n N_JOBS]

Detect API call discrepancies within the same caller between the new and old blobs.

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        the number of workers. DEFAULT: 1
```
In our experiments, we set `n` as 100. It took about 20 minutes to finish. The results are stored in the `java_api_call_changes` and `py_api_call_changes` collections in the `bridge` database for Java and Python, respectively. Each document has the following fields: `commit`, `filepath`, `old_blob`, `new_blob`, `library`, `version_before`, `version_after`, `caller`, `old_callees`, and `new_callees`. It drops duplicate documents who shared the same `old_blob`, `new_blob`, `library`, `version_before`, `version_after`, and `caller`.

## Identify Update Instances
[`identify_update_instances.py`](./identify_update_instances.py) identifies candidate Java/Python update instances from the API call discrepancies between old and new blobs. It has the following command line options:
```
usage: python identify_update_instances.py [-h] [--java] [--python]

Mine update instances based on the API call changes between the new and old blobs.

options:
  -h, --help  show this help message and exit
  --java      mine Java update instances. DEFAULT: False
  --python    mine Python update instances. DEFAULT: False
```
Run the following command to mine update instances.
```shell
python identify_update_instances.py --java --python
```
The identified candidate update instances are stored in the `java_candidate_update_instances` and `py_candidate_update_instances` collections in the `bridge` database for Java and Python, respectively.
