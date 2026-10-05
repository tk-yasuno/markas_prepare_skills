"""Build office-dummy models and office-specific deterioration paths."""

from __future__ import annotations

import argparse
import io
import json
import pickle
import sys
from pathlib import Path

import pandas as pd

from .pipeline import (
    attach_office_metadata,
    build_markas_dataset,
    read_datlinkset,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool_markas_v06"))
from EMHM import ExponentialHazardMarkovModel
from plot_model import process_plot_model

TARGETS = {
    "主桁1_shugeta": "Mg",
    "橋脚2_kyokyaku": "P",
    "支承3_shisyo": "B",
    "床版4_shoban": "Ds",
}
NUMERIC_FEATURES = ["age_at_inspection_1", "bridge_length", "bridge_area", "traffic_mean"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("office_metadata", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--max-rows", type=int, default=20000)
    args = parser.parse_args()

    raw = read_datlinkset(args.data_dir)
    raw, office_counts = attach_office_metadata(raw, args.office_metadata)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {"raw_office_counts": office_counts, "cases": {}}

    for case_name, member_code in TARGETS.items():
        case_raw = raw[raw["member_code"].astype(str) == member_code].copy()
        dataset, excluded = build_markas_dataset(case_raw, args.max_rows, args.seed)
        case_dir = args.output_dir / case_name
        case_dir.mkdir(parents=True, exist_ok=True)
        dataset.to_csv(case_dir / "markas_dataset.csv", index=False, encoding="utf-8-sig")
        train = dataset[dataset["dataset_split"] == "train"].copy()
        all_offices = sorted(train["office_label"].unique())
        offices = [office for office in all_offices if office != "unknown"]
        dummy_names = [f"office_{index + 1}" for index in range(len(offices))]
        office_dummy_map = dict(zip(offices, dummy_names))
        for dummy in dummy_names:
            train[dummy] = (train["office_label"] == offices[dummy_names.index(dummy)]).astype(float)
        feature_names = NUMERIC_FEATURES + dummy_names
        model_input = train[["St1", "St2", "Delta_t", *feature_names]]
        model_input.to_csv(case_dir / "model_train_raw.csv", index=False, encoding="utf-8-sig")

        max_values = {}
        for feature in feature_names:
            max_value = float(model_input[feature].max())
            max_values[feature] = max_value if max_value else 1.0
        scaled = model_input.copy()
        for feature in feature_names:
            scaled[feature] = scaled[feature] / max_values[feature]
        model = ExponentialHazardMarkovModel().fit(scaled, use_class_weights=False)
        model_dir = case_dir / "estimate"
        model_dir.mkdir(parents=True, exist_ok=True)
        with (model_dir / "estimated_model.pkl").open("wb") as file:
            pickle.dump(model, file)
        summary["cases"][case_name] = {
            "member_code": member_code,
            "raw_rows": int(len(case_raw)),
            "dataset_rows": int(len(dataset)),
            "train_rows": int(len(train)),
            "office_labels": offices,
            "office_dummy_map": office_dummy_map,
            "excluded": excluded,
            "office_counts": dataset["office_label"].value_counts().to_dict(),
        }

        raw_means = train[NUMERIC_FEATURES].mean().to_dict()
        plot_offices = all_offices
        for office in plot_offices:
            factors = dict(raw_means)
            for dummy in dummy_names:
                factors[dummy] = 1.0 if office_dummy_map.get(office) == dummy else 0.0
            params = {"years": 50, "max_values": max_values}
            for index, feature in enumerate(feature_names, 1):
                params[f"factor{index}"] = factors[feature]
            buffer = io.BytesIO()
            pickle.dump(model, buffer)
            success, message, graph, curve, distribution = process_plot_model(
                buffer.getvalue(), params
            )
            if not success:
                raise RuntimeError(message)
            office_dir = model_dir / f"office_{office}"
            office_dir.mkdir(parents=True, exist_ok=True)
            (office_dir / "graph.csv").write_text(graph, encoding="utf-8-sig")
            (office_dir / "curve.png").write_bytes(curve)
            (office_dir / "distribution.png").write_bytes(distribution)

    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
