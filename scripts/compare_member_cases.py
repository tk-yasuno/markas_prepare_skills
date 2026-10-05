"""Compare MARKAS v0.6.1 with and without class weights."""

from __future__ import annotations

import argparse
import io
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool_markas_v06"))
from EMHM import ExponentialHazardMarkovModel
from plot_model import process_plot_model


def _normalise_features(frame: pd.DataFrame, feature_names: list[str], max_values: dict) -> pd.DataFrame:
    result = frame[feature_names].copy().astype(float)
    for name in feature_names:
        maximum = float(max_values.get(name, 0.0))
        result[name] = result[name] / maximum if maximum else 0.0
    return result


def _evaluate(model: ExponentialHazardMarkovModel, frame: pd.DataFrame, max_values: dict) -> dict:
    feature_names = model.feature_cols[1:]
    if frame.empty:
        return {"n": 0, "log_loss": None, "accuracy": None, "macro_recall": None}
    supported = (
        frame["St1"].between(1, model.num_states)
        & frame["St2"].between(1, model.num_states)
    )
    unsupported = int((~supported).sum())
    frame = frame.loc[supported].copy()
    if frame.empty:
        return {
            "n": 0,
            "unsupported_states": unsupported,
            "log_loss": None,
            "accuracy": None,
            "macro_recall": None,
        }
    x = _normalise_features(frame, feature_names, max_values)
    design = model._prepare_X_from_df(x)
    theta = model._calculate_theta(model.params, design)
    pi = model._calculate_pi(theta, frame["Delta_t"].to_numpy(float))
    before = frame["St1"].to_numpy(int) - 1
    after = frame["St2"].to_numpy(int) - 1
    probabilities = np.maximum(pi[np.arange(len(frame)), before, after], 1e-12)
    predicted = pi[np.arange(len(frame)), before].argmax(axis=1)
    correct = predicted == after
    recalls = []
    for transition in sorted(set(zip(before, after))):
        mask = (before == transition[0]) & (after == transition[1])
        recalls.append(float(correct[mask].mean()))
    return {
        "n": int(len(frame)),
        "unsupported_states": unsupported,
        "log_loss": float(-np.mean(np.log(probabilities))),
        "accuracy": float(np.mean(correct)),
        "macro_recall": float(np.mean(recalls)) if recalls else None,
    }


def _save_outputs(model, output_dir: Path, max_values: dict, raw_means: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    parameter_csv = io.StringIO()
    parameter_csv.write("model_stats\nlog_likelihood,AIC,BIC\n")
    parameter_csv.write(
        f"{model.log_likelihood:.8f},{model.aic:.8f},{model.bic:.8f}\n\n"
    )
    parameter_csv.write("beta_estimates\n")
    parameter_csv.write("," + ",".join(model.param_names) + "\n")
    parameter_csv.write("," + ",".join(f"{value:.8f}" for value in model.params) + "\n")
    parameter_csv.write("\nt_values\n")
    parameter_csv.write("," + ",".join(model.param_names) + "\n")
    parameter_csv.write("," + ",".join(f"{value:.8f}" for value in model.t_values) + "\n")
    parameter_csv.write("\navg_hazard\n")
    parameter_csv.write(",".join(f"state_{index + 1}" for index in range(len(model.avg_theta))) + "\n")
    parameter_csv.write(",".join(f"{value:.8f}" for value in model.avg_theta) + "\n")
    parameter_csv.write("\navg_transition_probs\n")
    for row in model.avg_pi:
        parameter_csv.write(",".join(f"{value:.8f}" for value in row) + "\n")
    (output_dir / "estimated.csv").write_text(
        parameter_csv.getvalue(), encoding="utf-8-sig"
    )
    (output_dir / "estimated.json").write_text(
        json.dumps(
            {
                "weighting": model.weighting,
                "num_states": model.num_states,
                "log_likelihood": float(model.log_likelihood),
                "aic": float(model.aic),
                "bic": float(model.bic),
                "feature_cols": model.feature_cols,
                "params": [float(value) for value in model.params],
                "forward_transition_counts": model.forward_transition_counts,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    with (output_dir / "estimated_model.pkl").open("wb") as file:
        pickle.dump(model, file)
    params = {"years": 50, "max_values": max_values}
    for index, name in enumerate(model.feature_cols[1:], 1):
        params[f"factor{index}"] = float(raw_means[name])
    model_bytes = io.BytesIO()
    pickle.dump(model, model_bytes)
    success, message, graph, curve, distribution = process_plot_model(
        model_bytes.getvalue(), params
    )
    if not success:
        raise RuntimeError(message)
    (output_dir / "graph.csv").write_text(graph, encoding="utf-8-sig")
    (output_dir / "curve.png").write_bytes(curve)
    (output_dir / "distribution.png").write_bytes(distribution)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument(
        "--weighting",
        choices=("both", "unweighted", "weighted"),
        default="both",
    )
    args = parser.parse_args()
    comparison_rows = []

    for case_dir in sorted(path for path in args.cases_dir.iterdir() if path.is_dir()):
        dataset_path = case_dir / "markas_dataset.csv"
        train_path = case_dir / "loaded_data.csv"
        metadata_path = case_dir / "loaded_data.json"
        if not dataset_path.exists() or not train_path.exists():
            continue
        dataset = pd.read_csv(dataset_path)
        train = pd.read_csv(train_path, encoding="utf-8-sig")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        feature_names = train.columns[3:].tolist()
        raw_train = dataset[dataset["dataset_split"] == "train"]
        raw_means = raw_train[feature_names].mean().to_dict()
        weighting_options = {
            "unweighted": (False,),
            "weighted": (True,),
            "both": (False, True),
        }[args.weighting]
        for use_weights in weighting_options:
            np.random.seed(args.seed)
            model = ExponentialHazardMarkovModel().fit(
                train, use_class_weights=use_weights
            )
            label = "weighted" if use_weights else "unweighted"
            output_dir = args.output_dir / case_dir.name / label
            raw_means_normalized = {
                name: float(raw_means[name]) for name in feature_names
            }
            _save_outputs(model, output_dir, metadata["max_values"], raw_means_normalized)
            for split in ("validation", "golden_test"):
                metrics = _evaluate(
                    model,
                    dataset[dataset["dataset_split"] == split],
                    metadata["max_values"],
                )
                comparison_rows.append({
                    "case": case_dir.name,
                    "weighting": label,
                    "split": split,
                    **metrics,
                    "train_log_likelihood": float(model.log_likelihood),
                    "aic": float(model.aic),
                })

    result = pd.DataFrame(comparison_rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output_dir / "comparison_metrics.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "comparison_metrics.json").write_text(
        json.dumps(comparison_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
