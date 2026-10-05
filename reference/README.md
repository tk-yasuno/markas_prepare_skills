# MARKAS Tool for Data Preparedness and Covariates Scaling

## 1. 目的

橋梁点検データ（DATLINKSET-I/II/III）とメタデータから、部材ー損傷単位のMARKAS推計用データセットを作成し、MARKAS v0.6.2で部材別モデルを推計する。v0.6.2では、4種類の説明変数スケーリングをGolden Test上の精度と最適化収束時間で比較する。

最終的な1行は、少なくとも次の情報を持つ。

- `St1`: 初回点検時の健全度ランク
- `St2`: 次回点検時の健全度ランク
- `Delta_t`: 点検間隔（年）
- `x`: 説明変数
- `bridge_id`: 匿名化済み橋梁ID
- `member_code`, `damage_type_code`, `damage_id`: 部材ー損傷単位の監査キー
- `dataset_split`: `train`、`validation`、`golden_test`

## 2. 使用環境

プロジェクト専用仮想環境は `.venv-mark06` とする。

```powershell
.\.venv-mark06\Scripts\python.exe -m pip install -r tool_markas_v06\requirements.txt
```

`.xls` 読込には `xlrd==2.0.1` を使用する。

## 3. 入力データ

### 点検データ

```text
data/bridge_metro2005/DATLINKSETI-III/
  DATLINKSET-I.xls
  DATLINKSET-II.xls
  DATLINKSET-III.xls
```

多段ヘッダーから次の列を検出する。

- 橋梁番号、橋梁名、径間番号
- 部材、損傷箇所、損傷の種類、損傷ID
- 2次〜6次の点検年
- 2次〜6次の判定ランク
- 竣工年度、橋長、橋面積、交通量

### メタデータ

```text
data/bridge_metro2005/コード表.xls
data/bridge_metro2005/0507損傷グループピング一覧.xls
```

`コード表.xls` で部材コードを検証し、損傷グループ一覧で対象部材のグループを監査する。

### GitHub公開用匿名化データ

原本のExcelは公開せず、次の匿名化済みCSVだけをGitHubへ登録する。

```text
data/bridge_metro2005_anonymized/
  ANONYMIZATION_MANIFEST.json
  DATLINKSETI-III/
    DATLINKSET-I.csv
    DATLINKSET-II.csv
    DATLINKSET-III.csv
```

公開版では、橋梁名、元橋梁番号、地名、元ファイル名を含めない。
橋梁識別子は全ファイル共通の内部ID `bridge_####` へ置換する。

原本から匿名化版を再生成するコマンド:

```powershell
.\.venv-mark06\Scripts\python.exe -m tool_markas_prepare.anonymize_datlinkset `
  data\bridge_metro2005\DATLINKSETI-III `
  data\bridge_metro2005_anonymized\DATLINKSETI-III
```

匿名化版の件数と削除列は `ANONYMIZATION_MANIFEST.json` を参照する。

この匿名化済みDATLINKSETは、GitHubリポジトリへ登録済みである。
登録実績は15,927行、153橋梁で、登録コミットは `c340a99` である。
原本Excel（`data/bridge_metro2005/`）は秘匿情報を含むため、GitHubへ登録していない。

## 4. 匿名化とサンプリング

橋梁番号は安定した内部IDへ置換する。

```text
bridge_0001
bridge_0002
...
```

橋名・地名は出力データへ含めない。匿名化対応表も成果物として保存しない。

サンプリング条件は以下で固定する。

- 乱数seed: `20260924`
- 上限: 20,000行
- 橋梁を分割しない
- 20,000行を超える橋梁は対象から除外
- 同一橋梁の部材ー損傷系列を維持

## 5. 部材ー損傷単位

次のキーでグループ化する。

```text
bridge_id
span_number
member_code
damage_location_code
damage_type_code
damage_id
```

`damage_id` を含めることが重要である。同一橋梁・部材・損傷種類でも損傷IDが異なる場合は、別の損傷系列として扱う。

## 6. 状態遷移の作成

隣接する点検次数から次の2種類を生成する。

```text
3次点検 -> 4次点検: train
4次点検 -> 5次点検: validation / golden_test候補
```

品質フィルタは以下のとおり。

- 健全度ランクが欠損、未知、または変換不能なら除外
- `Delta_t < 0.1` 年なら除外
- 点検年が欠損、負の間隔なら除外
- `St2 < St1` の下降遷移は点検誤差として除外
- 説明変数の欠損は生成後の列中央値で補完

健全度コードは次で数値化する。

```text
a -> 1
b -> 2
c -> 3
d -> 4
e -> 5
```

## 7. 説明変数

4変数構成を標準とする。

```text
age_at_inspection_1
bridge_length
bridge_area
traffic_mean
```

`age_at_inspection_1` は次で計算する。

```text
inspection_year_1 - completion_year
```

絶対的な竣工年度をそのまま使ってはいけない。竣工年度は切片と強く共線になり、係数が相殺して数値不安定になるためである。竣工年度は監査列として保持する。

`traffic_mean` は3次点検時と4次点検時の交通量の平均値である。単一点検時の交通量ではなく隣接点検間の平均を使い、偶然の変動を抑える。

v0.6.2では、学習データだけから各スケーリングのパラメータを推定し、Golden Testには保存済みのパラメータを適用する。比較対象は次の4方式である。

- baseline max scaling
- min-max scaling
- z-score scaling
- Box-Cox transformation（学習データ由来の正値化シフトとlambdaを保存）

実験ではz-score scalingが10部材すべてで収束し、平均Golden Test精度も4方式中で最高だった。Box-Coxは高速に収束するケースがある一方、収束率と確率校正に問題が確認されたため、accuracyだけで採用しない。詳細は `docs/MARKAS_v062_scaling.md` と `LESSON_MARKAS_SCALING.md` を参照する。

## 8. データ分割

- 3次→4次: `train`
- 4次→5次: 橋梁単位で固定seed分割
- 5次相当データの20%: `validation`
- 5次相当データの80%: `golden_test`

同じ橋梁をvalidationとgolden testへ重複配置しない。v0.6.2のスケーリング実験では、ユーザー指定によりGolden Testを方式比較に使用した。このため、選定後のGolden Test精度は独立した最終汎化性能ではない。将来の最終報告では、validationまたはネストした再標本化で方式を選定し、独立test setで確認する。

## 9. 実行方法

### syntheticデータでの確認

```powershell
.\.venv-mark06\Scripts\python.exe tool_markas_v06\load_data.py `
  data\syn_pave20k\input\input_2000_rows.csv `
  .tmp_v061\loaded_data.csv .tmp_v061\loaded_data.json

.\.venv-mark06\Scripts\python.exe tool_markas_v06\estimate_model.py local `
  .tmp_v061\loaded_data.csv .tmp_v061

.\.venv-mark06\Scripts\python.exe tool_markas_v06\plot_model.py `
  .tmp_v061\estimated_model.pkl .tmp_v061 .tmp_v061\loaded_data.json
```

### 部材ケースの一括実行

```powershell
.\.venv-mark06\Scripts\python.exe -m tool_markas_prepare.run_member_cases `
  data\bridge_metro2005\DATLINKSETI-III `
  data\bridge_metro2005\コード表.xls `
  data\bridge_metro2005\0507損傷グループピング一覧.xls `
  .tmp_member_cases_x4_extended `
  --seed 20260924 --max-rows 20000
```

### v0.6.2スケーリング比較

10部材、4説明変数、重みなし、固定seedの条件で4方式を比較する。

```powershell
.\.venv-mark06\Scripts\python.exe -m tool_markas_scaling.run_scaling_comparison `
  data\bridge_metro2005\DATLINKSETI-III `
  data\bridge_metro2005\コード表.xls `
  data\bridge_metro2005\0507損傷グループピング一覧.xls `
  .tmp_member_cases_v062_scaling `
  --seed 20260924 --max-rows 20000
```

英語ラベルのグラフを生成する。

```powershell
.\.venv-mark06\Scripts\python.exe -m tool_markas_scaling.plot_scaling_lessons `
  .tmp_member_cases_v062_scaling\comparison_metrics.csv `
  docs\figures\markas_scaling
```

結果は `.tmp_member_cases_v062_scaling/comparison_metrics.csv`、選定理由は `LESSON_MARKAS_SCALING.md`、実行・出力契約は `docs/MARKAS_v062_scaling.md` に保存する。

部材ケースの定義は `tool_markas_prepare/pipeline.py` の `MEMBER_CASES` にある。

## 10. 実行済み10ケース

4説明変数、seed `20260924`、橋梁単位20,000行上限での実績である。

| ケース | コード | 全行数 | train | validation | golden_test |
|---|---:|---:|---:|---:|---:|
| 主桁1_shugeta | Mg | 2,409 | 624 | 217 | 1,568 |
| 橋脚2_kyokyaku | P | 3,087 | 1,158 | 285 | 1,644 |
| 支承3_shisyo | B | 4,269 | 1,634 | 640 | 1,995 |
| 床版4_shoban | Ds | 3,478 | 1,491 | 325 | 1,662 |
| 横桁5_yokogeta | Cr | 604 | 216 | 113 | 275 |
| 縦桁6_tategeta | St | 272 | 86 | 41 | 145 |
| 橋台7_kyodai | A | 800 | 271 | 91 | 438 |
| 伸縮装置8_sinshuku | E | 779 | 323 | 105 | 351 |
| 対傾溝9_taikeiko | Cf | 79 | 27 | 14 | 38 |
| 舗装10_hoso | Pa | 1,924 | 742 | 208 | 974 |

「対傾溝9_taikeiko」は、コード表の正式名称「対傾構」を対象とする。

v0.6.2の実績出力は次に保存される。

```text
.tmp_member_cases_v062_scaling/
```

各ケースには次がある。

- `markas_dataset.csv`
- `model_train_raw.csv`
- `loaded_data.csv`
- `loaded_data.json`
- `estimate/estimated.csv`
- `estimate/estimated.json`
- `estimate/estimated_model.pkl`
- `estimate/curve.png`
- `estimate/distribution.png`
- `estimate/graph.csv`

## 11. 可視化で判明した注意点

### 極端な劣化パス

初期実装では、可視化CLIが旧来の固定因子（例: `factor1=50`, `factor2=1000`）を使っていた。3説明変数以上のモデルへ適用すると、学習範囲外の外挿となり、RMDや状態割合が極端になった。

対策:

- 学習モデルの `feature_defaults` を保存する
- `loaded_data.json` の `max_values` を可視化へ渡す
- 学習データの代表値で可視化する
- 学習時と可視化時の説明変数順序を一致させる

### 推定不能な最終状態

ある状態から上位状態への観測が0件の場合、その状態のハザードはデータから推定できない。RMDを巨大な年数として表示せず、`NaN` として期待劣化パスから除外する。

これはモデルの失敗を隠す処理ではなく、推定不能状態を明示するための処理である。状態ごとの前向き遷移件数を確認し、必要なら追加データ、類似部材との統合、状態定義の再検討を行う。

### 小標本ケース

縦桁（train 86行）と対傾構（train 27行）は、係数・Hessian・標準誤差が不安定になりやすい。Hessianが特異行列になった場合、推計値は生成されても標準誤差は信頼できない。

## 12. 最低限の検証

```powershell
.\.venv-mark06\Scripts\python.exe -m pytest -q
```

確認項目:

- `Delta_t >= 0.1`
- `St2 >= St1`
- 匿名橋梁ID
- 行数20,000以下
- `traffic_mean` の欠損なし
- CSVパラメータ出力
- 期待劣化パス
- 状態割合推移図
- pickle再読込後の `predict_rmd` / `predict_pi`
- 4種類のスケーリングと定数列処理
- Box-Coxの学習由来シフトとメタデータ復元
- パレート選定と非収束試行の除外

実績の回帰テストは現在 `11 passed` である。

## 13. 変更してはいけない前提

- `0_LogBAK/v06_team_code` は退避版のため変更しない
- 選定済みのGolden Test精度を独立した最終性能として扱わない
- 橋名・地名を出力しない
- 部材ー損傷単位を損傷IDなしで結合しない
- 絶対竣工年度をそのまま推計説明変数にしない
- 学習時と異なる説明変数順序で可視化しない

## 14. GitHub登録

推奨リポジトリ名:

```text
markas_v06_20k5r3v
```

推奨Description:

```text
MARKAS v0.6.2 preprocessing and Markov deterioration hazard modeling pipeline for bridge inspection data, including reproducible member-level scaling comparison and convergence-aware evaluation.
```

ライセンスはApache License 2.0とし、ルートの `LICENSE` に配置する。

GitHubで空のリポジトリを手動作成した後、ローカルで次を実行する。

```powershell
git init
git add .
git commit -m "MARKAS v0.6.2 scaling comparison"
git branch -M main
git remote add origin https://github.com/<OWNER>/markas_v06_20k5r3v.git
git push -u origin main
```

`data/bridge_metro2005/`、`0_LogBAK/`、`.venv-mark06/` は `.gitignore` により登録しない。
実験生成物 `.tmp_*` も再生成可能なため登録しない。
