import argparse
from itertools import product

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from pandas import DataFrame
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.model_selection import GroupKFold
from tqdm import tqdm


def greedy_matching(record_df: DataFrame):
    sorted_df = record_df.sort_values(
        by=["score", "old_index", "index_sim"], ascending=(False, True, True)
    )
    matched_pairs, used_old, used_new = list(), set(), set()

    for _, row in sorted_df.iterrows():
        o_idx, n_idx = row["old_index"], row["new_index"]
        if o_idx not in used_old and n_idx not in used_new:
            matched_pairs.append((o_idx, n_idx, row["score"]))
            used_old.add(o_idx)
            used_new.add(n_idx)

    return matched_pairs


def match(df: DataFrame):
    matched_df = df.copy()
    matched_pairs_all = []
    for record_id, record_df in matched_df.groupby("record_id"):
        matched_pairs = greedy_matching(record_df)
        for p in matched_pairs:
            matched_pairs_all.append([record_id, p[0], p[1]])

    keys = ["record_id", "old_index", "new_index"]

    # create a new column indicating greedy matched pairs
    mask = matched_df[keys].apply(list, axis=1).isin(matched_pairs_all)
    matched_df["matched"] = False
    matched_df.loc[mask, "matched"] = True
    return matched_df


def classify_by_thresh(
    matched_df: DataFrame, thresh: float, validation_fail_pairs: DataFrame | None = None
):
    res = matched_df.copy()

    # create a new column indicating classification results based on the threshold
    res["pred"] = 0
    mask2 = res["matched"] & (res["score"] > thresh)
    res.loc[mask2, "pred"] = 1

    # if phantom api pairs are given, set corresponding results to 0
    keys = ["record_id", "old_index", "new_index"]
    if validation_fail_pairs is not None:
        idx1 = pd.MultiIndex.from_frame(res[keys])
        idx2 = pd.MultiIndex.from_frame(validation_fail_pairs)
        mask3 = idx1.isin(idx2)
        res["phantom"] = False
        res.loc[mask3, "phantom"] = True
        res.loc[mask3, "pred"] = 0
    return res


def calculate_metrics(df: DataFrame):
    p = precision_score(df["label"], df["pred"], zero_division=1.0)
    r = recall_score(df["label"], df["pred"])
    f1 = f1_score(df["label"], df["pred"])
    return f1, p, r


def kfold_evaluation(
    df, folds, params, feature_cols, phantom_pairs: DataFrame | None = None
):
    res = []
    fold_idx = 0
    for fold_idx, (train_idx, test_idx) in enumerate(folds, start=1):
        train_df, test_df = df.iloc[train_idx].copy(), df.iloc[test_idx].copy()
        train_df["score"] = sum(
            train_df[feature_cols[i]] * params[i] for i in range(len(feature_cols))
        )
        train_df["index_sim"] = abs(train_df["new_index"] - train_df["old_index"])

        best_thresh = None
        best_train_f1 = 0.0
        matched_train_df = match(train_df)
        for thresh in np.linspace(0.0, 1.0, 21):
            train_f1, _, _ = calculate_metrics(
                classify_by_thresh(matched_train_df, thresh, phantom_pairs)
            )
            if train_f1 >= best_train_f1:
                best_train_f1 = train_f1
                best_thresh = thresh

        test_df["score"] = sum(
            test_df[feature_cols[i]] * params[i] for i in range(len(feature_cols))
        )
        test_df["index_sim"] = abs(test_df["new_index"] - test_df["old_index"])
        matched_test_df = match(test_df)
        test_f1, test_p, test_r = calculate_metrics(
            classify_by_thresh(matched_test_df, best_thresh, phantom_pairs)
        )
        res.append(params + [fold_idx, best_thresh, test_f1, test_p, test_r])
    return res


def kfold_grid_search(df, feature_cols, phantom_pairs: DataFrame | None = None):
    """Finds the best hyperparameters/weights using a sub-split of the training data."""
    # 1. Define Search Space
    num_features = len(feature_cols)
    step = 0.1
    scale = int(1 / step)
    param_grid = [
        [_ * step for _ in w]
        for w in product(range(1, scale + 1), repeat=num_features)
        if sum(w) == scale
    ]
    if len(feature_cols) == 3:
        param_grid.append([1 / 3, 1 / 3, 1 / 3])
    print(f"{len(param_grid)} weight configurations")

    # 2. Grid Search with K-fold cross validation
    gkf = GroupKFold(n_splits=5)
    folds = list(gkf.split(df, groups=df["record_id"]))
    n_jobs = 128 if len(param_grid) > 128 else len(param_grid)
    res = Parallel(n_jobs=n_jobs)(
        delayed(kfold_evaluation)(df, folds, params, feature_cols, phantom_pairs)
        for params in tqdm(param_grid)
    )
    return pd.DataFrame(
        [_ for wc in res for _ in wc],
        columns=feature_cols + ["fold", "threshold", "f1", "precision", "recall"],
    )


def full_evaluation(df, params, feature_cols, phantom_pairs: DataFrame | None = None):
    tmp = df.copy()
    tmp["score"] = sum(
        tmp[feature_cols[i]] * params[i] for i in range(len(feature_cols))
    )
    tmp["index_sim"] = abs(tmp["new_index"] - tmp["old_index"])
    res = []
    matched_tmp = match(tmp)
    for thresh in np.linspace(0.0, 1.0, 21):
        f1, p, r = calculate_metrics(
            classify_by_thresh(matched_tmp, thresh, phantom_pairs)
        )
        res.append(params + [thresh, f1, p, r])
    return pd.DataFrame(
        res, columns=feature_cols + ["threshold", "f1", "precision", "recall"]
    )


def main(lang: str):
    df = pd.read_csv(f"../benchmark/ground_truth/{lang}_ground_truth.csv")
    if lang == "py":
        feature_cols = ["fqn_sim", "arg_sim"]
    elif lang == "java":
        feature_cols = ["class_sim", "method_sim", "arg_sim"]
    validation_results = pd.read_csv(
        f"../benchmark/ground_truth/{lang}_validation_results.csv"
    )
    validation_fail_pairs = validation_results[~validation_results["validation"]][
        ["record_id", "old_index", "new_index"]
    ]
    weight_sensitivity = kfold_grid_search(df, feature_cols, validation_fail_pairs)
    weight_sensitivity.to_csv(
        f"../benchmark/evaluation/{lang}_weight_analysis.csv", index=False
    )
    equal_weights = [1 / len(feature_cols) for _ in feature_cols]
    threshold_sensitivity = full_evaluation(
        df, equal_weights, feature_cols, validation_fail_pairs
    )
    threshold_sensitivity["Phase4"] = True
    phase4_ablation = full_evaluation(df, equal_weights, feature_cols)
    phase4_ablation["Phase4"] = False
    pd.concat([threshold_sensitivity, phase4_ablation]).to_csv(
        f"../benchmark/evaluation/{lang}_threshold_ablation.csv", index=False
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python evaluation.py",
        description="Performance Evaluation on ground truth dataset.",
    )
    parser.add_argument(
        "--java",
        action="store_true",
        help="validation for Java. DEFAULT: False",
    )
    parser.add_argument(
        "--python",
        action="store_true",
        help="validation for Python. DEFAULT: False",
    )
    args = parser.parse_args()

    if args.java:
        main("java")

    if args.python:
        main("py")
