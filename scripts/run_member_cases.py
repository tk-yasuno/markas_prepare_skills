"""Create and estimate the three metadata-defined member cases."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .pipeline import (
    build_member_case_datasets,
    read_datlinkset,
    read_member_case_definitions,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("code_table", type=Path)
    parser.add_argument("grouping_table", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--max-rows", type=int, default=20000)
    args = parser.parse_args()

    raw = read_datlinkset(args.data_dir)
    definitions = read_member_case_definitions(args.code_table, args.grouping_table)
    datasets = build_member_case_datasets(raw, definitions, args.max_rows, args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    summary = {}

    for case_name, (dataset, excluded) in datasets.items():
        case_dir = args.output_dir / case_name
        case_dir.mkdir(parents=True, exist_ok=True)
        dataset_path = case_dir / "markas_dataset.csv"
        dataset.to_csv(dataset_path, index=False, encoding="utf-8-sig")
        train = dataset[dataset["dataset_split"] == "train"]
        model_input = train[[
            "St1", "St2", "Delta_t", "age_at_inspection_1", "bridge_length", "bridge_area", "traffic_mean"
        ]]
        raw_input = case_dir / "model_train_raw.csv"
        model_input.to_csv(raw_input, index=False, encoding="utf-8-sig")
        loaded_input = case_dir / "loaded_data.csv"
        loaded_metadata = case_dir / "loaded_data.json"
        estimate_dir = case_dir / "estimate"
        commands = [
            [python, str(root / "tool_markas_v06" / "load_data.py"), str(raw_input), str(loaded_input), str(loaded_metadata)],
            [python, str(root / "tool_markas_v06" / "estimate_model.py"), "local", str(loaded_input), str(estimate_dir)],
            [
                python,
                str(root / "tool_markas_v06" / "plot_model.py"),
                str(estimate_dir / "estimated_model.pkl"),
                str(estimate_dir),
                str(loaded_metadata),
            ],
        ]
        for command in commands:
            subprocess.run(command, check=True, cwd=root)
        summary[case_name] = {
            "member_code": definitions[case_name]["member_code"],
            "member_label": definitions[case_name]["member_label"],
            "groups": definitions[case_name]["groups"],
            "rows": int(len(dataset)),
            "train_rows": int(len(train)),
            "split_counts": dataset["dataset_split"].value_counts().to_dict(),
            "transition_counts": dataset["transition_class"].value_counts().to_dict(),
            "excluded": excluded,
            "dataset": str(dataset_path),
            "estimate_dir": str(estimate_dir),
        }

    with (args.output_dir / "summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
