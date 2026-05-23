# TODOリスト

**最終更新**: 2026-05-17  
凡例: ✅ 完了　⬜ 未着手　🔧 実装済み・設定未完了

---

## 1. データ基盤

| # | 項目 | 状態 | 備考 |
|---|------|------|------|
| 1-1 | J-Quants `/listed/info` クライアント実装 | ✅ | `src/data/jquants_client.py` |
| 1-2 | J-Quants `/fins/statements` クライアント実装 | ✅ | 年次・四半期EPS/売上/ROEを取得 |
| 1-3 | yfinance クライアント実装（株価・財務比率・決算日）| ✅ | `src/data/yfinance_client.py` |
| 1-4 | JSONキャッシュ管理（週次168h・日次24h）| ✅ | `src/utils/cache.py` |
| 1-5 | J-Quants APIキー設定 | ✅ | `config/settings.yaml` に設定済み |
| 1-6 | Gemini APIキー設定 | ✅ | `config/settings.yaml` に設定済み（gemini-2.5-flash）|
| 1-7 | LINE Messaging API キー設定 | ✅ | `config/settings.yaml` に設定済み |

---

## 2. 週次スクリーニング（①監視対象銘柄選定）

全評価指標を **1つの総合スコア（0〜100点）** に統合し、スコア降順で上位20社をウォッチリストに登録する。個別のバイナリフィルタ（pass/fail判定）は廃止。REQUIREMENTS.md §3.1 参照。

| # | 項目 | 状態 | 備考 |
|---|------|------|------|
| 2-1 | **【段階1】速報スコア**: yfinance basicから5次元スコア計算（営業利益率・自己資本比率・PEG比率・時価総額・配当性向）| ✅ | 全1,600社 → 上位200〜400社に絞り込み。`src/screener/unified_scorer.py` に `calculate_stage1_scores()` + `filter_stage1_candidates()` 実装済み |
| 2-2 | **【段階2】精緻スコア**: J-Quants財務諸表 + yfinance詳細から8次元スコア計算（年次EPS成長・四半期EPS成長・年次売上成長・四半期売上成長・ROE・CF品質・FCF継続年数・純負債EBITDA）| ✅ | 段階1上位候補のみに適用。`src/screener/unified_scorer.py` に実装済み |
| 2-3 | 全13次元の重み付き **総合スコア（0〜100点）** 計算・スコア降順で上位20社選定 | ✅ | `calculate_total_score()` + `select_final_watchlist()` 実装済み |
| 2-4 | 欠損値補完（データ未取得次元は中間スコア **5点** で補完） | ✅ | `MISSING_SCORE = 5.0` 定数と `_linear_score()` 内の None/isfinite ガードで全次元対応済み |
| 2-5 | バリュエーション **参考表示**（EV/Revenue・EV/EBITDA・PER・PBR）をレポートに追記 | ⬜ | 選定の除外条件ではなく参考情報として記載 |
| 2-6 | Gemini AI 投資テーゼ生成（Top5銘柄）| ✅ | APIキー設定済み・動作確認済み |
| 2-7 | Gemini AI ベアケース・リスク分析生成（Top5銘柄）| ✅ | |
| 2-8 | `watch_list.md` 出力（`weekly_moat_stocks.md` は後方互換シンボリックリンク）| ✅ | |
| 2-9 | 定性分析プロンプト設計（Q1〜Q5フレームワーク）| ✅ | `claude_analyzer.py` に `analyze_qualitative()` メソッド追加済み |
| 2-10 | 定性スコア（0〜10）+ 4段階ラベル生成実装 | ✅ | Strong/Moderate/Weak/Unknown + `label_score` 算出済み（Issue #9） |
| 2-11 | 週次レポートへの定性分析セクション追加 | ✅ | `_format_qualitative_section()` + `_build_weekly_report()` 統合済み（Issue #10） |
| 2-12 | 情報ソース欄の追記（EDINET/TDnet URLリンク）| ⬜ | レポート末尾に「参照すべき一次情報ソース」のリンクを銘柄ごとに列挙（v1.1スコープ）|

---

## 3. 日次シグナル検知（②購入銘柄の選定 / ③売却銘柄の選定）

| # | 項目 | 状態 | 備考 |
|---|------|------|------|
| 3-1 | SMA計算（5・20・75日）| ✅ | `src/technical/signals.py`（手実装）|
| 3-2 | EMA計算（12・26日）| ✅ | |
| 3-3 | MACD計算（12, 26, 9）| ✅ | |
| 3-4 | RSI計算（14日）| ✅ | |
| 3-5 | ボリンジャーバンド計算（20日・±2σ）| ✅ | |
| 3-6 | 出来高比率計算（当日/20日平均）| ✅ | |
| 3-7 | BUYシグナル判定（スコア≥3）| ✅ | |
| 3-8 | SELLシグナル判定（スコア≥3）| ✅ | |
| 3-9 | HOLDシグナル（フェイクアウト回避）| ✅ | 決算前後3日・スコア拮抗 |
| 3-10 | WATCHシグナル（中立）| ✅ | |
| 3-11 | データ不足時の早期リターン（<30営業日）| ✅ | |
| 3-12 | Gemini AI シグナル解説生成 | ✅ | APIキー設定済み・動作確認済み |
| 3-13 | `daily_trade_signals.md` 出力 | ✅ | |
| 3-14 | `signals.csv` 出力 | ✅ | |
| 3-15 | **②購入候補リスト管理**: BUYシグナル発生時に `output/buy_candidates.md` へ追加（重複除外・最新シグナル日時更新）| ✅ | `src/screener/buy_candidates.py` + `daily_pipeline.py` |
| 3-16 | **②購入候補リスト管理**: `output/watch_list.md` を `weekly_moat_stocks.md` の代替として出力（後方互換シンボリックリンク対応）| ✅ | `weekly_pipeline.py` `_ensure_legacy_symlink()` |
| 3-17 | **③売却判断 軸A**: テクニカルSELLスコア ≥3点 発生時に `buy_candidates.md` から除外し LINE通知 | ✅ | `daily_pipeline.py` + `line_notifier.py` |
| 3-18 | **③売却判断 軸B**: 週次スクリーニング時に購入候補リスト内銘柄のファンダメンタルズ再確認。条件劣化時は要注意フラグを付与し 2回連続で除外 | ✅ | `weekly_pipeline.py` `_check_axis_b()` |
| 3-19 | **③売却判断**: 両軸（テクニカルSELL + ファンダメンタルズ劣化）同時該当時は即時除外 + 優先度高のLINE通知 | ✅ | 軸A（日次）と軸B（週次）の独立実装で両軸同時対応済み |
| 3-20 | **signals.csv 拡張**: `list_type`（watch/buy_candidate）列を追加し、銘柄がどのリストに属するかを記録 | ✅ | `daily_pipeline.py` `_write_csv()` |

---

## 4. 通知

| # | 項目 | 状態 | 備考 |
|---|------|------|------|
| 4-1 | LINE通知: BUY/SELLシグナル発生時 | ✅ | `src/notification/line_notifier.py` |
| 4-2 | LINE通知: 週次ウォッチリスト変更（追加・削除銘柄）| ✅ | |
| 4-3 | LINE通知: パイプラインエラー発生時 | ✅ | `notify_error()` 実装済み |
| 4-4 | LINE通知の送信タイミングを翌朝9:00に変更 | ⬜ | 現在は19:30パイプライン実行時に即時送信。Cloud Schedulerで別途JST 9:00（UTC 0:00）に通知専用ジョブを追加する必要あり |

---

## 5. 非機能要件

| # | 項目 | 状態 | 備考 |
|---|------|------|------|
| 5-1 | `--dry-run` フラグ（APIキー不要でテスト）| ✅ | 週次・日次パイプライン両対応 |
| 5-2 | `--force-refresh` フラグ（キャッシュ無視）| ✅ | |
| 5-3 | `--ticker` フラグ（特定銘柄のみ実行）| ✅ | |
| 5-4 | `config/settings.yaml` で全閾値を変更可能 | ✅ | コード修正不要 |
| 5-5 | ログ記録（`logs/YYYYMMDD.log`）| ✅ | `src/utils/logger.py` |
| 5-6 | 個別API取得失敗時は `ERROR` として継続処理 | ✅ | |
| 5-7 | パッケージ環境構築（yfinance・PyYAML・tabulate）| ✅ | `requirements.txt` / `setup.sh` |
| 5-8 | **【セキュリティ】APIキーを Secret Manager へ移行** | ⬜ | `config/settings.yaml` に J-Quants・Gemini・LINE の認証情報が平文保存されている。GCP Secret Manager に移し、Cloud Run の環境変数として注入する（REQUIREMENTS.md §5.2 参照）|
| 5-9 | **【コスト最適化】Cloud Storage によるキャッシュの永続化** | ⬜ | Cloud Run コンテナはエフェメラルなため、実行ごとにキャッシュが消失し全銘柄フルスキャンが発生する。`cache/` を GCS バケットに読み書きするよう `src/utils/cache.py` を拡張し、週次実行時間を短縮する（REQUIREMENTS.md §4.3 参照）|

---

## 6. 自動実行（Cron）

| # | 項目 | 状態 | 備考 |
|---|------|------|------|
| 6-1 | 週次cronスクリプト作成（`run_weekly.sh`）| ✅ | |
| 6-2 | 日次cronスクリプト作成（`run_daily.sh`）| ✅ | |
| 6-3 | Cloud Run + Cloud Schedulerへの登録 | ✅ | Artifact Registry作成・イメージpush・Cloud Run Jobs（weekly/daily）・Cloud Scheduler登録完了（2026-05-16）|

---

## 7. 将来拡張（スコープ外・優先度順）

| # | 項目 | 状態 | 参照 |
|---|------|------|------|
| 7-1 | Comps分析レポート（同業他社5社との5+5指標比較表）| ✅ | `src/screener/comps_analyzer.py` + `pipelines/comps_pipeline.py` |
| 7-2 | 簡易DCFモデル自動計算（WACC・TV・フェアバリュー試算）| ✅ | `src/screener/dcf_calculator.py` + `pipelines/dcf_pipeline.py` |
| 7-3 | 決算レビュー自動化（Beat/Miss・ガイダンス変更の解析）| ✅ | `src/screener/earnings_reviewer.py` + `pipelines/earnings_pipeline.py`（Issue #15） |
| 7-4 | マルチエージェント分解（Researcher → Screener → Analyst）| ✅ | `src/agents/` + `pipelines/agent_pipeline.py`（Issue #16） |
| 7-5 | ポートフォリオ管理・リバランス提案 | ✅ | `src/portfolio/` + `pipelines/portfolio_pipeline.py`（Issue #17） |

---

## 進捗サマリー

```
✅ 完了       : 37項目（データ基盤7・日次シグナル12・通知3・自動実行2・定性分析3・スコアリング4・将来拡張6）
⬜ 未着手     :  4項目（バリュエーション表示1・LINE翌朝通知1・情報ソースリンク1・Secret Manager1）
⚠️ 要対応     :  2項目（Secret Manager移行・キャッシュ永続化）
```

> **注**: 2026-05-17 仕様変更により旧バイナリフィルタ方式（Step1/Step2-A〜F）を廃止し、13次元統合スコアリング方式に移行。旧フィルタ実装（`step1_filter.py` の一部・`step2_analysis.py` の `filter_*` 関数群）は 2-1〜2-3 実装完了後に削除する。

### 直近の優先アクション

1. **`バリュエーション参考表示`（2-5）** — EV/Revenue・EV/EBITDA・PER・PBRのレンジをレポートに追記
2. **`Secret Manager 移行`（5-8）** ⚠️ セキュリティ — `settings.yaml` の平文APIキーを GCP Secret Manager へ移行
3. **`キャッシュ永続化`（5-9）** — Cloud Storage バケットへの読み書きを `cache.py` に追加
4. **`情報ソースリンク追記`（2-12）** — 銘柄ごとに EDINET / TDnet / IR ページのURL を自動生成してレポートに付記
5. **`LINE翌朝通知`（4-4）** — 通知専用の朝9:00 cronジョブ追加（小規模）
