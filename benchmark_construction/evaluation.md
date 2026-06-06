# Evaluation
We evaluate the effectiveness of Bridge on mining update instances, specifically phase 3 and phase 4. Besides, this step also help determine the weights and threshold used in phase 3 to mine candidate update instances.

## Annotate Ground Truth Dataset
We evaluate Bridge by first sampling a set of API call change records from the `{py,java}_api_call_changes` collections obtained in Phase 3. The sampling procedure takes two stages:

1. Sample 100 libraires by the number of update commits.
2. For each sampled library, shuffle its API call change records, take one record at a time and accept it if it contains at least a new old API FQN, repeat until reaching at least 10 unique old API FQNs or iterating all records.

Finally, we obtain 638 and 609 records for Java and Python respectively.

Then we manually annotate update instances between old API calls and new API calls in each sampled record. Using the annotated data, we calculate the pair-wise similarity metrics between each old API call and new API call.

[`construct_ground_truth.py`](./phase3/construct_ground_truth.py) file in phase folder finished the above process. Just run the following commands:
```shell
cd phase3
python construct_ground_truth.py
```
The sampled records are stored as `{java,py}_record_samples.csv` files in the [`benchmark/ground_truth`](../benchmark/ground_truth/) folder.
`{java,py}_record_samples.xlsx` files store the annotated data.
The ground truth data are stored in `{java,py}_ground_truth.csv` files.

## Post Validation
To avoid duplicate post validation on the ground truth dataset, we perform post validation on every API call pair in the ground truth dataset.
We first download all sources jars/wheels for each Java/Python library release in the dataset. Run the following commands:
```shell
cd phase4
python download_libraries.py -d <DEST_FOLDER> --java --python --evaluation 2>../log/download_libraries.log
```
The `<DEST_FOLDER>` is the same folder with the one in phase 3 for building import mappings.

Then, perform post validation on all API call pairs in the ground truth dataset by executing code blocks in [`validation_for_eval.ipynb`](./phase4/validation_for_eval.ipynb) in the phase4 folder. The post validation results are stored as `{java,py}_validation_results.csv` in the [`benchmark/ground_truth`](../benchmark/ground_truth/) folder.

## Performance Evaluation
Execute code blocks in [`evaluation.ipynb`](./evaluation.ipynb) to evaluate the performance of different hyperparameter configurations.
