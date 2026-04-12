from pandas import DataFrame


def greedy_matching(record_df: DataFrame, thresh: float):
    sorted_df = record_df.sort_values(by="score", ascending=False)
    predicted_pairs, used_old, used_new = set(), set(), set()

    for _, row in sorted_df.iterrows():
        if row["score"] < thresh:
            break
        o_idx, n_idx = row["old_index"], row["new_index"]
        if o_idx not in used_old and n_idx not in used_new:
            predicted_pairs.add((o_idx, n_idx))
            used_old.add(o_idx)
            used_new.add(n_idx)

    gt_pairs = set(
        record_df[record_df["label"] == 1][["old_index", "new_index"]].itertuples(
            index=False, name=None
        )
    )
    return (
        len(predicted_pairs.intersection(gt_pairs)),
        len(predicted_pairs - gt_pairs),
        len(gt_pairs - predicted_pairs),
    )


def calculate_f1(df: DataFrame, thresh: float):
    total_tp, total_fp, total_fn = 0, 0, 0
    for _, record_df in df.groupby("record_id"):
        tp, fp, fn = greedy_matching(record_df, thresh)
        total_tp += tp
        total_fp += fp
        total_fn += fn

    p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0
    r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1 = 2 * (p * r) / (p + r) if (p + r) > 0 else 0.0

    return f1, p, r
