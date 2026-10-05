"""Create GitHub-safe anonymized CSVs from DATLINKSET-I/II/III."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .pipeline import anonymize_bridge_ids, read_datlinkset


PUBLIC_DROP_COLUMNS = {"bridge_name_raw", "bridge_id_raw"}


def anonymize_datlinkset(input_dir: Path, output_dir: Path) -> dict[str, object]:
    source = read_datlinkset(input_dir)
    bridge_ids = sorted(source["bridge_id_raw"].astype(str).unique())
    bridge_map = {
        bridge_id: f"bridge_{index:04d}"
        for index, bridge_id in enumerate(bridge_ids, 1)
    }
    source["bridge_id"] = source["bridge_id_raw"].astype(str).map(bridge_map)
    public = source.drop(columns=PUBLIC_DROP_COLUMNS, errors="ignore")
    public = public.drop(columns=["source_file"], errors="ignore")
    output_dir.mkdir(parents=True, exist_ok=True)

    file_stats = {}
    for source_name, group in source.groupby("source_file", sort=True):
        output = group.drop(columns=PUBLIC_DROP_COLUMNS | {"source_file"}, errors="ignore")
        output_path = output_dir / source_name.replace(".xls", ".csv")
        output.to_csv(output_path, index=False, encoding="utf-8-sig")
        file_stats[output_path.name] = {
            "rows": int(len(output)),
            "bridges": int(output["bridge_id"].nunique()),
        }

    manifest = {
        "source": "DATLINKSET-I/II/III.xls",
        "rows": int(len(public)),
        "bridges": int(public["bridge_id"].nunique()),
        "files": file_stats,
        "removed_columns": sorted(PUBLIC_DROP_COLUMNS | {"source_file"}),
        "public_id": "bridge_####",
        "location_labels_included": False,
    }
    (output_dir.parent / "ANONYMIZATION_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    manifest = anonymize_datlinkset(args.input_dir, args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
