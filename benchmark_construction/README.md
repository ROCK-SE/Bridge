# Benchmark Construction

Before you proceed, you should first setup the environment for this step by following the instructions in the [INSTALL.md](../INSTALL.md).

## Construct the Benchmark Dataset
`compile_java_dataset.ipynb` and `compile_python_dataset.ipynb` construct benchmark datasets for Java and Python, respectively.
The first 8 cells in the two Jupyter Notebooks sample API update mappings and produces files `{java,python}_api_update_rules_{gte10,1to10,eq1}.xlsx` in the `../benchmark/final` folder.
`{java,python}_api_update_rules_{gte10,1to10,eq1}-labelled.xlsx` files in the `../benchmark/final` folder contains the labelled results and corresponding evidences. Then, run cell 9-10 to estimate the overall accuracy of the mined API update mappings.

Next, run cell 11-17 to compile the API update pairs datasets, which include the following files in the `../benchmark/final` folder:
- `{java,python}_labelled_rules.csv`. Each row corresponds to a sampled mapping with following fields: `package` (string), `old_api` (string), `new_api` (string), `commit` (string), `correct` (1 for correct and 0 for incorrect/unsure), `evidence` (string).
- `{java,python}_api_update_rules_exact.json`. Each record corresponds to an verified correct API update mapping and has the following fields: `package` (string), `old_api` (string), and `old_api` (a list of strings, since we can not infer the API's parameter types or an old API may have multiple replacement APIs).
- `{java,python}_api_update_rules_full.json`. Similar to the above files, except that it consists of all API update mappings.
- `{java,python}_api_pairs_exact.json`. Each record corresponds to an API update pair of a verified correct API update mapping. It has the following fields: `package` (string), `old_api` (string), `new_api` (string), `old_version` (string), `new_version` (string).
- `{java,python}_api_pairs_full.json`. Similar to the above files, except that it consists of all API update pairs of all API update mapping.
- `{java,python}_commit_pairs_exact.json`. Each record corresponds to a verified correct API update pair with the commit introducing the pair. It has the same fields as `{java,python}_api_pairs_exact.json` with an additional `commit` field.
- `{java,python}_commit_pairs_full.json`. Similar to the above files, except that it consists of all API update pairs of all API update mapping.
- **`{java,python}_sampled_api_pairs_exact.json`**. Sample API update pairs for each API update mappings from `{java,python}_api_pairs_exact.json` based on the version update types of each pair. **It is used as the final benchmark to evaluate LLMs on the recommending replacement API task.**
- **`{java,python}_sampled_api_pairs_full.json`**. Sample API update pairs for each API update mappings from `{java,python}_api_pairs_full.json` based on the version update types of each pair. **It is used as the final benchmark to evaluate LLMs on the recommending replacement API task.**

After that, run `extract_java_snippets.py` and `extract_python_snippets.py` to extract API update instances for all Java/Python API update pairs in the exact and full groups. They has the following options:
```
usage: python extract_java_snippets.py [-h] [-n N_JOBS]

Extract methods for Java API update pairs

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers

usage: python extract_python_snippets.py [-h] [-n N_JOBS]

Extract functions for Python update pairs

options:
  -h, --help            show this help message and exit
  -n N_JOBS, --n_jobs N_JOBS
                        number of workers
```

Run the following commands to extract API update instances:
```shell
python extract_java_snippets.py -n <Number of processes, default 1>
python extract_python_snippets.py -n <Number of processes, default 1>
```
In our experiments, we set `n` 128. It took about 40 minutes to finish and produces the following files in the `../benchmark/final` folder:
- `{java,python}_update_instances_full.json`. Each record corresponds to a record in corresponding `{java,python}_commit_pairs_full.json` files with four additional fields: `old_code`, `old_args`, `new_code`, `new_args`.
- `{java,python}_update_instances_exact.json`. Similar to the above files, except that each record corresponds to a record in corresponding `{java,python}_commit_pairs_exact.json` files

Finally, run the last cell in the two Jupyter Notebooks to sample instances for the two groups and produce the following files in the `../benchmark/final` folder:
-  **`{java,python}_sampled_update_instances_exact.json`**. Sample API update instances for each API update mappings from `{java,python}_update_instances_exact.json` based on the version update types of each pair. **It is used as the final benchmark to evaluate LLMs on the recommending replacement API task in our paper.**
-  `{java,python}_sampled_update_instances_full.json`. Sample API update instances for each API update mappings from `{java,python}_update_instances_full.json` based on the version update types of each pair. We do not use this dataset to evaluate LLMs on the recommending replacement API task in our paper due to the budget limit.

Please refer to [README.md in the `../benchmark/final` folder](../benchmark/final/README.md) for the statistics of these files.
