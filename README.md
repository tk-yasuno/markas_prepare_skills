# markas-prepare skill

橋梁・路面点検データ（DATLINKSET-I/II/III 等の定期点検記録）を、MARKAS
マルコフ劣化ハザードモデル（EMHM）推計用の部材ー損傷単位データセットへ変換する
Copilot/Claude Skill です。公開用に橋梁IDを匿名化したCSV生成、説明変数
（`age_at_inspection_1`, `bridge_length`, `bridge_area`, `traffic_mean`）の
導出、部材ケースごとの train/validation/golden_test 分割生成までを一貫して
行います。

このリポジトリは [SKILL.md](./SKILL.md) を本体とする Skill パッケージであり、
Claude/Copilot の Agent Skills 形式（`name` / `description` の frontmatter +
`scripts/` / `reference/` / `examples/`）に準拠しています。

## 構成

- [SKILL.md](./SKILL.md) — スキル本体。トリガー条件・ワークフロー・使用方法を記述
- [scripts/](./scripts) — 前処理コード本体（`tool_markas_prepare` パッケージ）
  - `pipeline.py` — DATLINKSET読込・部材ケース定義・状態遷移/説明変数生成の中核ロジック
  - `anonymize_datlinkset.py` — 橋梁IDの匿名化・秘匿列の除去
  - `run_member_cases.py` — 10部材ケース一括生成 + 推計コマンド自動連結
  - `office_member_cases.py` — 事務所ダミー付き拡張版
  - `compare_member_cases.py` — 重み付けあり/なしの比較評価
- [reference/](./reference) — 前処理仕様書（`README.md`）、MARKASユーザーガイド（v0.5）、
  マルコフ劣化ハザードモデルのarXiv論文
- [examples/](./examples) — 匿名化済み実データ例（`raw_bridge_anonymized/`）と
  syntheticな前処理済み入出力対（`prepared_pavement_20k/`）

## 使い方

Claude Code / Copilot CLI の Skills 機能で読み込む場合は、本リポジトリの内容を
`~/.copilot/skills/markas-prepare/`（またはプロジェクトの `.claude/skills/markas-prepare/`
等、各ツールのSkill探索パス）に配置してください。

新しいリポジトリへ前処理コードのみを横展開する場合の手順は
[SKILL.md](./SKILL.md) の「7. 新しいリポジトリへ横展開する場合」を参照してください。

## ライセンス

[MIT License](./LICENSE)

## 作者

Takato Yasuno
