---
name: markas-prepare
description: 'Use when preparing bridge/pavement inspection data (DATLINKSET-I/II/III and similar periodic-inspection records) into member-damage-level transition datasets for MARKAS Markov deterioration hazard model estimation — anonymizing bridge IDs for public release, deriving explanatory variables (age_at_inspection_1, bridge_length, bridge_area, traffic_mean), building per-member-case train/validation/golden_test splits, and comparing scaling/weighting options. Trigger phrases: "MARKASの前処理をして", "点検データをMARKAS推計用に変換", "DATLINKSETを部材ー損傷単位のデータセットにして", "匿名化済みCSVを作って", "部材ケースを一括実行して", "tool_markas_prepareを使って". Produces bridge_id-anonymized, member-case CSV datasets (train/validation/golden_test) ready for tool_markas_v06 (EMHM) estimation, following the MARKAS v0.6.1/v0.6.2 pipeline conventions used by Takato Yasuno.'
---

# MARKAS Prepare Skill（橋梁点検データの前処理・共変量化）

橋梁点検データ（DATLINKSET-I/II/III）とメタデータ（コード表、損傷グルーピング一覧）から、部材ー損傷単位のMARKAS推計用データセット（`St1`/`St2`/`Delta_t`/説明変数/`dataset_split`）を作成するためのスキル。`tool_markas_prepare` モジュール（本スキルの [scripts/](./scripts) にバンドル済み）を核とし、MARKAS v0.6.1（前処理確立）〜v0.6.2（スケーリング比較）で確立した規約に基づく。

## いつ使うか

- 新しい橋梁・路面点検データ（Excel形式の多段ヘッダー点検台帳）をMARKAS推計（`tool_markas_v06` モジュールの `EMHM`/`load_data.py`/`estimate_model.py`）に投入できる形へ変換したいとき
- 秘匿情報（橋梁名・元番号・地名・元ファイル名）を含む原本データから、GitHub公開用の匿名化済みCSVを生成したいとき
- 部材（主桁・橋脚・支承・床版・横桁・縦桁・橋台・伸縮装置・対傾構・舗装の10ケース）ごとにtrain/validation/golden_testデータセットを一括生成したいとき
- 説明変数のスケーリング方式（baseline max / min-max / z-score / Box-Cox）や重み付けの有無を比較したいとき
- 既存パイプラインを新しいリポジトリ・新しいデータソースへ横展開したいとき

## ワークフロー

### 1. 入力データと環境を確認する
- 点検データ: 多段ヘッダーExcel `DATLINKSET-I.xls`/`-II.xls`/`-III.xls`（橋梁番号、部材、損傷箇所・種類・ID、2〜6次点検年・判定ランク、竣工年度、橋長、橋面積、交通量を含む）
- メタデータ: `コード表.xls`（部材コード→正式名称）、`0507損傷グループピング一覧.xls`（部材グループ監査用）
- プロジェクト専用仮想環境（例 `.venv-mark06`）に `pandas`, `numpy`, `xlrd==2.0.1`（`.xls` 読込に必須）を用意する
- 詳細な列検出ロジック・ディレクトリ規約は [reference/README.md](./reference/README.md) を参照する

### 2. 原本から匿名化済みCSVを生成する（公開用）
[scripts/anonymize_datlinkset.py](./scripts/anonymize_datlinkset.py) の `anonymize_datlinkset()` を使う。橋梁番号を安定な内部ID `bridge_####` に置換し、`bridge_name_raw`/`bridge_id_raw`/`source_file` 列を除去してからCSV（`utf-8-sig`）へ出力し、`ANONYMIZATION_MANIFEST.json`（件数・橋梁数・削除列の監査記録）を書き出す。
```powershell
python -m tool_markas_prepare.anonymize_datlinkset `
  data\bridge_metro2005\DATLINKSETI-III `
  data\bridge_metro2005_anonymized\DATLINKSETI-III
```
出力例は [examples/raw_bridge_anonymized/](./examples/raw_bridge_anonymized) を参照（`DATLINKSET-I/II/III.csv` + `ANONYMIZATION_MANIFEST.json`）。**橋名・地名・匿名化対応表は成果物として保存しない。**

### 3. 部材ー損傷単位のデータセットを作成する
[scripts/pipeline.py](./scripts/pipeline.py) が中核ロジックを提供する:
- `read_datlinkset()` — 多段ヘッダーから列を自動検出し正規化フレームへ変換
- `read_member_case_definitions()` — コード表とグルーピング一覧から10部材ケース（`MEMBER_CASES`）を解決
- `build_member_case_datasets()` — 部材ー損傷単位（`bridge_id, span_number, member_code, damage_location_code, damage_type_code, damage_id`）でグループ化し、状態遷移（St1→St2、Delta_t）と4説明変数を生成
- `attach_office_metadata()` — 橋梁番号プレフィックスから事務所・環境ラベルを付与（office_member_cases向け）

一括実行は [scripts/run_member_cases.py](./scripts/run_member_cases.py)（10部材ケース一括生成 + `tool_markas_v06` の推計コマンドを自動連結）を使う:
```powershell
python -m tool_markas_prepare.run_member_cases `
  data\bridge_metro2005\DATLINKSETI-III `
  data\bridge_metro2005\コード表.xls `
  data\bridge_metro2005\0507損傷グループピング一覧.xls `
  .tmp_member_cases_x4_extended `
  --seed 20260924 --max-rows 20000
```
品質フィルタ・状態遷移・分割規約（3次→4次=train、4次→5次=validation/golden_test、橋梁単位で重複なし）の詳細は [reference/README.md](./reference/README.md) の「6. 状態遷移の作成」「8. データ分割」を参照する。

### 4. 説明変数を確認する
標準4変数: `age_at_inspection_1`（= 点検年 − 竣工年度。竣工年度そのものは切片と共線になるため使わない）、`bridge_length`、`bridge_area`、`traffic_mean`（隣接2点検時の交通量平均）。欠損は列中央値で補完する。事務所ダミーを使う拡張版は [scripts/office_member_cases.py](./scripts/office_member_cases.py) の `NUMERIC_FEATURES` を参照する。

### 5. 比較・検証する（必要な場合）
- 重み付けあり/なしの比較: [scripts/compare_member_cases.py](./scripts/compare_member_cases.py)（`EMHM`/`plot_model` を直接呼び出し log loss・accuracy・macro recall を評価）
- スケーリング方式比較（baseline/min-max/z-score/Box-Cox）は別モジュール `tool_markas_scaling`（本スキルには同梱していない）。方式選定の根拠・実績数値は [reference/README.md](./reference/README.md) の該当節、確立した知見は元リポジトリの `LESSON_MARKAS_SCALING.md` を参照する。

### 6. 推計へ引き継ぐ
生成した `markas_dataset.csv`（`train`/`validation`/`golden_test` 列を含む）を `tool_markas_v06` の `load_data.py` → `estimate_model.py local` → `plot_model.py` に渡す。syntheticデータでの動作確認は [examples/prepared_pavement_20k/](./examples/prepared_pavement_20k) の `input/input_10000_rows.csv`（点検データ入力例、Shift-JIS）と `output/output_10000_rows.csv`（推計結果レポート例: 対数尤度・AIC・ベータ係数・ハザード率・マルコフ推移確率・残存余命）の対を見本にする。

### 7. 新しいリポジトリへ横展開する場合
[scripts/](./scripts) は `tool_markas_prepare` パッケージ一式（`__init__.py` を含む）そのままのコピーである。新しいリポジトリに導入する際は:
1. `tool_markas_prepare/` としてリポジトリ直下に配置する
2. 兄弟ディレクトリに `tool_markas_v06/`（`EMHM.py`, `load_data.py`, `estimate_model.py`, `plot_model.py`）を用意する（`compare_member_cases.py`/`office_member_cases.py` が `sys.path` 経由でimportする）
3. データパス（`data\bridge_metro2005\...` 等）とseed（既定 `20260924`）、上限行数（既定 `20000`）を対象データに合わせて調整する
4. 新しい点検台帳が異なる列名・部材体系を使う場合は、`pipeline.py` の `MEMBER_CASES`、`_canonical_columns()` の列ラベル（`橋梁番号`, `判定ランク` 等）を実データに合わせて拡張する

## 参考資料

- [reference/README.md](./reference/README.md) — 前処理コード（`tool_markas_prepare`）の仕様書。目的・入力データ・匿名化規約・部材ー損傷単位定義・状態遷移・説明変数・データ分割・実行方法・実行済み10ケースの実績表を網羅
- [reference/MARKASユーザーガイド_v05.pdf](./reference/MARKASユーザーガイド_v05.pdf) — MARKASツール全体のユーザーガイド（v0.5）
- [reference/2609.31786v1.pdf](./reference/2609.31786v1.pdf) — マルコフ劣化ハザードモデル推計の方法論を記したarXiv論文
- [examples/raw_bridge_anonymized/](./examples/raw_bridge_anonymized) — 匿名化済み生データの実例（DATLINKSET-I/II/III.csv + ANONYMIZATION_MANIFEST.json、15,927行・153橋梁）
- [examples/prepared_pavement_20k/](./examples/prepared_pavement_20k) — 前処理を完了したsyntheticデータの入出力対（舗装部材、1万行/2万行規模）
- [scripts/](./scripts) — 前処理コード本体（`tool_markas_prepare` パッケージ: `pipeline.py`, `anonymize_datlinkset.py`, `run_member_cases.py`, `office_member_cases.py`, `compare_member_cases.py`）
