---
name: pipeline-reviewer
description: weekly_pipeline.py と agent_weekly_pipeline.py の実装差分を検出し、片方だけに実装されている変更を警告する。デプロイ前に呼び出すと安全。
---

`pipelines/weekly_pipeline.py` と `pipelines/agent_weekly_pipeline.py` の2つのパイプラインを比較し、
実装の一貫性を確認してください。

## チェック項目

### 1. キャッシュキーの一貫性
両ファイルで `cache_prefix`・`stage1_key`・`stage2_key`・`watchlist_key` の命名ルールが同じか確認する。

### 2. LINE通知ロジック
`notify_watchlist_update` の呼び出し引数（new_watchlist, prev_watchlist, ticker_names）が両ファイルで揃っているか確認する。

### 3. dry_run / force_refresh の取り扱い
dry_run=True 時の挙動（キャッシュキー分離・銘柄数制限）が両ファイルで統一されているか確認する。

### 4. GCSアップロード
`upload_report_to_gcs` の呼び出しが weekly_pipeline.py にあって agent_weekly_pipeline.py に抜けていないか（またはその逆）を確認する。

### 5. 軸B（BuyCandidate）確認ロジック
`_check_axis_b` の呼び出し条件（`not dry_run`）が両ファイルで同じか確認する。

## 報告形式

差分が見つかった場合:
- ファイル名・行番号を明示
- 「weekly_pipeline.py にはあるが agent_weekly_pipeline.py にない」などの形式で報告
- 修正が必要な場合は具体的な修正案を提示

差分がなければ「✅ 両パイプラインの実装は一貫しています」と報告する。
