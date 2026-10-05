"""Bridge inspection ETL for MARKAS transition datasets."""

from __future__ import annotations

import argparse
import hashlib
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import xlrd


GRADE_MAP = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
INSPECTION_LEVELS = (2, 3, 4, 5, 6)
MEMBER_CASES = {
    "主桁1_shugeta": ("Mg", "主桁"),
    "橋脚2_kyokyaku": ("P", "橋脚"),
    "支承3_shisyo": ("B", "支承"),
    "床版4_shoban": ("Ds", "床版"),
    "横桁5_yokogeta": ("Cr", "横桁"),
    "縦桁6_tategeta": ("St", "縦桁"),
    "橋台7_kyodai": ("A", "橋台"),
    "伸縮装置8_sinshuku": ("E", "伸縮装置"),
    "対傾溝9_taikeiko": ("Cf", "対傾構"),
    "舗装10_hoso": ("Pa", "舗装"),
}


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value).strip().replace("　", "")


def _level(value: object) -> int | None:
    normalized = _text(value).replace(" ", "").translate(str.maketrans("２３４５６", "23456"))
    match = re.search(r"([2-6])次", normalized)
    return int(match.group(1)) if match else None


def _find_column(rows: list[list[object]], predicate, start: int = 0) -> int | None:
    for index in range(start, len(rows[0])):
        if any(predicate(_text(row[index])) for row in rows[:5]):
            return index
    return None


def _find_group_columns(rows: list[list[object]], group_text: str) -> dict[int, int]:
    columns: dict[int, int] = {}
    anchor = None
    for index in range(len(rows[0])):
        context = " ".join(_text(rows[row_index][index]) for row_index in range(min(5, len(rows))))
        if group_text in context:
            anchor = index
            break
    if anchor is None:
        return columns
    for index in range(anchor, len(rows[0])):
        for row_index in range(min(5, len(rows))):
            level = _level(rows[row_index][index])
            if level is not None and level not in columns:
                columns[level] = index
        if len(columns) == len(INSPECTION_LEVELS):
            break
    return columns


def _canonical_columns(rows: list[list[object]]) -> dict[str, int | dict[int, int]]:
    def exact(label: str) -> int | None:
        return _find_column(rows, lambda value: value == label)

    columns: dict[str, int | dict[int, int]] = {
        "bridge_id_raw": exact("橋梁番号"),
        "bridge_name_raw": exact("橋梁名"),
        "completion_year": exact("竣工年度"),
        "bridge_length": exact("橋長"),
        "bridge_area": exact("橋面積"),
        "span_number": exact("径間番号"),
        "member_code": exact("部材"),
        "damage_location_code": exact("損傷箇所"),
        "damage_type_code": exact("損傷の種類"),
        "damage_id": exact("損傷ID"),
        "rank": _find_group_columns(rows, "判定ランク"),
        "inspection_year": _find_group_columns(rows, "点検実施年月"),
        "traffic": _find_group_columns(rows, "交通量"),
    }
    required = ("bridge_id_raw", "member_code", "damage_type_code")
    missing = [name for name in required if columns[name] is None]
    if missing or not columns["rank"] or not columns["inspection_year"]:
        raise ValueError(f"Required DATLINKSET columns were not found: {missing}")
    return columns


def _sheet_to_frame(sheet: xlrd.sheet.Sheet) -> pd.DataFrame:
    rows = [sheet.row_values(row_index) for row_index in range(min(6, sheet.nrows))]
    columns = _canonical_columns(rows)
    records = []
    for row_index in range(5, sheet.nrows):
        row = sheet.row_values(row_index)
        bridge_id = _text(row[columns["bridge_id_raw"]])
        if not bridge_id:
            continue
        record = {
            "bridge_id_raw": bridge_id,
            "bridge_name_raw": _text(row[columns["bridge_name_raw"]])
            if columns["bridge_name_raw"] is not None
            else "",
            "span_number": _text(row[columns["span_number"]])
            if columns["span_number"] is not None
            else "",
            "member_code": _text(row[columns["member_code"]]),
            "damage_location_code": _text(row[columns["damage_location_code"]])
            if columns["damage_location_code"] is not None
            else "",
            "damage_type_code": _text(row[columns["damage_type_code"]]),
            "damage_id": _text(row[columns["damage_id"]])
            if columns["damage_id"] is not None
            else "",
            "completion_year": pd.to_numeric(row[columns["completion_year"]], errors="coerce"),
            "bridge_length": pd.to_numeric(row[columns["bridge_length"]], errors="coerce"),
            "bridge_area": pd.to_numeric(row[columns["bridge_area"]], errors="coerce"),
        }
        for level, column in columns["rank"].items():
            record[f"rank_{level}"] = _text(row[column]).lower()
        for level, column in columns["inspection_year"].items():
            value = row[column]
            record[f"inspection_year_{level}"] = pd.to_numeric(value, errors="coerce")
        for level, column in columns["traffic"].items():
            value = row[column]
            record[f"traffic_{level}"] = pd.to_numeric(value, errors="coerce")
        records.append(record)
    return pd.DataFrame(records)


def read_datlinkset(input_path: str | Path) -> pd.DataFrame:
    """Read all DATLINKSET-I/II/III sheets into one normalized frame."""
    input_path = Path(input_path)
    files = sorted(input_path.glob("DATLINKSET-*.xls")) if input_path.is_dir() else [input_path]
    if not files:
        raise FileNotFoundError(f"No DATLINKSET xls files found in {input_path}")
    frames = []
    for file_path in files:
        workbook = xlrd.open_workbook(file_path, on_demand=True)
        for sheet in workbook.sheets():
            frame = _sheet_to_frame(sheet)
            frame["source_file"] = file_path.name
            frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def read_office_metadata(metadata_path: str | Path) -> dict[str, tuple[str, str]]:
    """Read unique bridge-prefix to office/environment mappings."""
    sheet = xlrd.open_workbook(metadata_path, on_demand=True).sheet_by_name("橋長")
    mapping: dict[str, tuple[str, str]] = {}
    for row_index in range(2, sheet.nrows):
        bridge_id = _text(sheet.cell_value(row_index, 4))
        office = _text(sheet.cell_value(row_index, 2))
        environment = _text(sheet.cell_value(row_index, 3)).replace(" ", "")
        if len(bridge_id) >= 3 and office:
            prefix = bridge_id[:3]
            value = (office, environment)
            if prefix in mapping and mapping[prefix] != value:
                raise ValueError(f"Ambiguous office metadata prefix: {prefix}")
            mapping[prefix] = value
    return mapping


def attach_office_metadata(
    frame: pd.DataFrame, metadata_path: str | Path
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Attach conservative office labels using verified bridge-number prefixes."""
    mapping = read_office_metadata(metadata_path)
    result = frame.copy()
    normalized = result["bridge_id_raw"].map(_text).str.replace(r"\.0$", "", regex=True).str.zfill(7)
    result["office_label"] = normalized.str[:3].map(lambda key: mapping.get(key, ("unknown", "unknown"))[0])
    result["office_environment"] = normalized.str[:3].map(lambda key: mapping.get(key, ("unknown", "unknown"))[1])
    counts = result["office_label"].value_counts().to_dict()
    return result, {str(key): int(value) for key, value in counts.items()}


def read_member_case_definitions(
    code_table_path: str | Path,
    grouping_path: str | Path,
) -> dict[str, dict[str, object]]:
    """Resolve requested member cases from the supplied metadata workbooks."""
    code_sheet = xlrd.open_workbook(code_table_path, on_demand=True).sheet_by_index(0)
    code_map: dict[str, str] = {}
    for row_index in range(3, code_sheet.nrows):
        row = code_sheet.row_values(row_index)
        code = _text(row[1])
        label = _text(row[2])
        if code and label:
            code_map[code] = label.split("(", 1)[0]

    grouping_sheet = xlrd.open_workbook(grouping_path, on_demand=True).sheet_by_name("SET-TOTAL")
    groups_by_label: dict[str, list[dict[str, object]]] = {}
    for row_index in range(5, grouping_sheet.nrows):
        row = grouping_sheet.row_values(row_index)
        group_id = _text(row[1])
        label = _text(row[2])
        damage = _text(row[6])
        if group_id and label:
            groups_by_label.setdefault(label, []).append({
                "group_id": group_id,
                "damage": damage,
                "count": int(row[7]) if isinstance(row[7], (int, float)) else 0,
            })

    definitions: dict[str, dict[str, object]] = {}
    for case_name, (code, expected_label) in MEMBER_CASES.items():
        actual_label = code_map.get(code, "")
        if actual_label != expected_label:
            raise ValueError(
                f"Metadata mismatch for {case_name}: code {code!r} maps to {actual_label!r}"
            )
        definitions[case_name] = {
            "member_code": code,
            "member_label": expected_label,
            "groups": groups_by_label.get(expected_label, []),
        }
    return definitions


def build_member_case_datasets(
    raw_frame: pd.DataFrame,
    definitions: dict[str, dict[str, object]],
    max_rows: int = 20000,
    seed: int = 20260924,
) -> dict[str, tuple[pd.DataFrame, dict[str, int]]]:
    """Build one MARKAS dataset for each metadata-defined member case."""
    datasets = {}
    for case_name, definition in definitions.items():
        member_code = str(definition["member_code"])
        case_frame = raw_frame[raw_frame["member_code"].astype(str) == member_code].copy()
        dataset, excluded = build_markas_dataset(case_frame, max_rows=max_rows, seed=seed)
        if not dataset.empty:
            dataset.insert(0, "case_name", case_name)
            dataset.insert(1, "member_label", str(definition["member_label"]))
        datasets[case_name] = (dataset, excluded)
    return datasets


def anonymize_bridge_ids(frame: pd.DataFrame) -> pd.DataFrame:
    """Replace bridge identifiers and names with stable internal IDs."""
    result = frame.copy()
    bridge_keys = sorted(result["bridge_id_raw"].dropna().astype(str).unique())
    mapping = {key: f"bridge_{index:04d}" for index, key in enumerate(bridge_keys, 1)}
    result["bridge_id"] = result["bridge_id_raw"].map(mapping)
    result = result.drop(columns=["bridge_id_raw", "bridge_name_raw"], errors="ignore")
    return result


def sample_bridges(frame: pd.DataFrame, max_rows: int = 20000, seed: int = 20260924) -> pd.DataFrame:
    """Select whole bridges in a reproducible order without splitting them."""
    counts = frame.groupby("bridge_id", sort=False).size()
    eligible = counts[counts <= max_rows].index.to_numpy()
    rng = np.random.default_rng(seed)
    ordered = rng.permutation(eligible)
    selected: list[str] = []
    total = 0
    for bridge_id in ordered:
        count = int(counts[bridge_id])
        if total + count > max_rows:
            continue
        selected.append(str(bridge_id))
        total += count
    return frame[frame["bridge_id"].isin(selected)].copy()


def _parse_grade(value: object) -> int | None:
    return GRADE_MAP.get(_text(value).lower())


def _finite_mean(values: list[object]) -> float:
    numeric = [float(value) for value in values if pd.notna(value)]
    return float(np.mean(numeric)) if numeric else np.nan


def _transition_key(row: pd.Series) -> tuple[object, ...]:
    return tuple(row.get(column, "") for column in (
        "bridge_id", "span_number", "member_code", "damage_location_code", "damage_type_code"
    ))


def build_markas_dataset(
    frame: pd.DataFrame,
    max_rows: int = 20000,
    seed: int = 20260924,
    min_interval: float = 0.1,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Create transition rows from adjacent inspections for each member-damage unit."""
    sampled = sample_bridges(anonymize_bridge_ids(frame), max_rows=max_rows, seed=seed)
    rows: list[dict[str, object]] = []
    excluded = Counter()
    for _, group in sampled.groupby(
        [
            "bridge_id",
            "span_number",
            "member_code",
            "damage_location_code",
            "damage_type_code",
            "damage_id",
        ],
        dropna=False,
    ):
        row = group.iloc[0]
        for first_level, second_level in ((3, 4), (4, 5)):
            state_1 = _parse_grade(row.get(f"rank_{first_level}"))
            state_2 = _parse_grade(row.get(f"rank_{second_level}"))
            time_1 = pd.to_numeric(row.get(f"inspection_year_{first_level}"), errors="coerce")
            time_2 = pd.to_numeric(row.get(f"inspection_year_{second_level}"), errors="coerce")
            if state_1 is None or state_2 is None:
                excluded["missing_state"] += 1
                continue
            delta_t = float(time_2 - time_1) if pd.notna(time_1) and pd.notna(time_2) else np.nan
            if not np.isfinite(delta_t) or delta_t < min_interval:
                excluded["invalid_interval"] += 1
                continue
            if state_2 < state_1:
                excluded["state_regression"] += 1
                continue
            dataset_split = "train" if second_level == 4 else "golden_candidate"
            rows.append({
                "bridge_id": row["bridge_id"],
                "span_number": row["span_number"],
                "member_code": row["member_code"],
                "damage_location_code": row["damage_location_code"],
                "damage_type_code": row["damage_type_code"],
                "damage_id": row["damage_id"],
                "office_label": row.get("office_label", "unknown"),
                "office_environment": row.get("office_environment", "unknown"),
                "completion_year": row["completion_year"],
                "age_at_inspection_1": time_1 - row["completion_year"],
                "bridge_length": row["bridge_length"],
                "bridge_area": row["bridge_area"],
                "traffic_1": row.get("traffic_3", np.nan),
                "traffic_2": row.get("traffic_4", np.nan),
                "traffic_mean": _finite_mean([row.get("traffic_3", np.nan), row.get("traffic_4", np.nan)]),
                "St1": state_1,
                "St2": state_2,
                "Delta_t": delta_t,
                "inspection_level_1": first_level,
                "inspection_level_2": second_level,
                "inspection_year_1": time_1,
                "inspection_year_2": time_2,
                "dataset_split": dataset_split,
            })
    result = pd.DataFrame(rows)
    if result.empty:
        return result, dict(excluded)
    numeric_features = [
        "completion_year", "bridge_length", "bridge_area", "traffic_1", "traffic_2", "traffic_mean"
    ]
    for feature in numeric_features:
        result[feature] = pd.to_numeric(result[feature], errors="coerce")
        median = result[feature].median()
        result[feature] = result[feature].fillna(0.0 if pd.isna(median) else median)
    result = _split_golden(result, seed)
    counts = result.groupby(["dataset_split", "St1", "St2"]).size()
    result["transition_class"] = result["St1"].astype(str) + "->" + result["St2"].astype(str)
    result["weight"] = result.apply(
        lambda row: 1.0 / counts[(row["dataset_split"], row["St1"], row["St2"])], axis=1
    )
    return result, dict(excluded)


def _split_golden(frame: pd.DataFrame, seed: int) -> pd.DataFrame:
    result = frame.copy()
    candidates = result.loc[result["dataset_split"] == "golden_candidate", "bridge_id"].unique()
    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(candidates)
    validation_count = int(np.ceil(len(shuffled) * 0.2)) if len(shuffled) else 0
    validation_bridges = set(shuffled[:validation_count])
    result.loc[
        result["bridge_id"].isin(validation_bridges) & (result["dataset_split"] == "golden_candidate"),
        "dataset_split",
    ] = "validation"
    result.loc[
        (result["dataset_split"] == "golden_candidate"), "dataset_split"
    ] = "golden_test"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--max-rows", type=int, default=20000)
    args = parser.parse_args()
    raw = read_datlinkset(args.input_dir)
    prepared, excluded = build_markas_dataset(raw, max_rows=args.max_rows, seed=args.seed)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    prepared.to_csv(args.output_csv, index=False, encoding="utf-8-sig")
    print(f"saved={args.output_csv} rows={len(prepared)} excluded={dict(excluded)}")


if __name__ == "__main__":
    main()