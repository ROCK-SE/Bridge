# Phase 2: API Call Analysis
This phase analyzes API calls in extracted code blobs obtained in the last phase. The data files obtained in this phase are stored in the [benchmark/Phase2](../../benchmark/Phase2) folder. Please refer to [README.md in the `benchmark/Phase2` folder](../../benchmark/Phase2/README.md) for the statistics of result files.

## Extract Blob locations
First run `python list_blobs.py` to split unique blobs into 128 files based on their sha-1 value. Then run `bash get_blob_idx.sh` to extract the offset and length of each blob in corresponding bin files. The results are stored in `java/py_blob.idx` files. Each row has fields: `blob`, `offset`, `length`.

## Parse API Calls
`parse_api_calls.py` parses API calls in Java/Python code blobs and store them to MongoDB collections. For Java, we deal with object type resolution and caller extraction. For Python, we deal with alias resolution and caller extraction. It has the following command line options:
```
usage: python parse_api_calls.py [-h] [-n N_JOBS] [-b BATCH_SIZE] [--python] [--java]

Parse api calls in Java/Python files and store them in MongoDB collections

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
  -b BATCH_SIZE, --batch_size BATCH_SIZE
                        number of blobs to processed in a batch
  --python              Parse Python files
  --java                Parse Java files
```
Run the following command to parse API calls for all Java/Python blobs obtained in above steps.
```shell
python parse_api_calls.py --java --python -n <Number of processes, default 1> -b <Number of blobs in a batch, default 1>
```
In our experiments, we set `n` and `b` as 512, 6000 and 512, 2000 for Java and Python, respectively. It took about 16 hours and 6 hours to finish. The results are stored to `java_api_calls` and `py_api_calls` collections in the `bridge` database for Java and Python, respectively.
