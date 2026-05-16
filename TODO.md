# TODOリスト

**最終更新**: 2026-05-16  
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

## 2. 週次スクリーニング

| # | 項目 | 状態 | 備考 |
|---|------|------|------|
| 2-1 | **Step1**: 時価総額フィルタ（≥100億円）| ✅ | `src/screener/step1_filter.py` |
| 2-2 | **Step1**: 営業利益率フィルタ（>0%）| ✅ | |
| 2-3 | **Step1**: PBRフィルタ（>0）| ✅ | |
| 2-4 | **Step1**: 売上高成長率フィルタ（≥−10%）| ✅ | |
| 2-5 | **Step1**: 自己資本比率フィルタ（≥10%）| ✅ | |
| 2-6 | **Step2-A**: 年次EPS成長フィルタ（≥25%・直近3期）| ✅ | `filter_eps_annual()` |
| 2-7 | **Step2-B**: 四半期EPS成長フィルタ（≥25%・単調増加）| ✅ | `filter_eps_quarterly()` |
| 2-8 | **Step2-C**: 四半期売上高フィルタ（3期連続プラスOR最新25%以上）| ✅ | `filter_netsales_quarterly()` |
| 2-9 | **Step2-D**: ROEフィルタ（>15%）| ✅ | J-Quants財務データから計算 |
| 2-10 | **Step2-E**: FCFプラス継続フィルタ（直近2期）| ✅ | |
| 2-11 | **Step2-E**: CF品質フィルタ（OCF/純利益 ≥0.8）| ✅ | |
| 2-12 | **Step2-F**: 純負債/EBITDAフィルタ（≤3.0x）| ✅ | |
| 2-13 | **Step2-G**: スコアリング・加重平均で上位20社選定 | ✅ | 6指標×重み |
| 2-14 | **Step2-H**: バリュエーション合理性チェック（EV/Revenue・EV/EBITDA・PER・PBRのレンジ確認をレポートに記載）| ⬜ | REQUIREMENTS.md §3.1 2-H 参照 |
| 2-15 | **Step2-I**: 銘柄分類（「全条件」「EPS条件のみ」）| ✅ | |
| 2-16 | Gemini AI 投資テーゼ生成（Top5銘柄）| ✅ | APIキー設定済み・動作確認済み |
| 2-17 | Gemini AI ベアケース・リスク分析生成（Top5銘柄）| ✅ | APIキー設定済み・動作確認済み |
| 2-18 | `weekly_moat_stocks.md` 出力 | ✅ | |
| 2-19 | **Step2-J**: 定性分析プロンプト設計（Q1〜Q5フレームワーク）| ⬜ | `claude_analyzer.py` に `analyze_qualitative()` メソッド追加。REQUIREMENTS.md §3.1 2-J 参照 |
| 2-20 | **Step2-J**: 定性スコア（0〜10）+ 4段階ラベル生成実装 | ⬜ | Strong/Moderate/Weak/Unknown の4段階評価 + 根拠コメント（1〜2文）|
| 2-21 | **Step2-J**: 週次レポートへの定性分析セクション追加 | ⬜ | Top5各社のQ1〜Q5評価表 + 総合定性スコアを `weekly_moat_stocks.md` に追記 |
| 2-22 | **Step2-J**: 情報ソース欄の追記（EDINET/TDnet URLリンク）| ⬜ | レポート末尾に「参照すべき一次情報ソース」のリンクを銘柄ごとに列挙（v1.1スコープ）|

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
| 3-15 | **②購入候補リスト管理**: BUYシグナル発生時に `output/buy_candidates.md` へ追加（重複除外・最新シグナル日時更新）| ⬜ | REQUIREMENTS.md §3.2「②の出力・更新ルール」参照 |
| 3-16 | **②購入候補リスト管理**: `output/watch_list.md` を `weekly_moat_stocks.md` の代替として出力（後方互換シンボリックリンク対応）| ⬜ | REQUIREMENTS.md §3.4 参照 |
| 3-17 | **③売却判断 軸A**: テクニカルSELLスコア ≥3点 発生時に `buy_candidates.md` から除外し LINE通知 | ⬜ | REQUIREMENTS.md §3.3「軸A」参照 |
| 3-18 | **③売却判断 軸B**: 週次スクリーニング時に購入候補リスト内銘柄のファンダメンタルズ再確認。条件劣化時は要注意フラグを付与し 2回連続で除外 | ⬜ | REQUIREMENTS.md §3.3「軸B」参照 |
| 3-19 | **③売却判断**: 両軸（テクニカルSELL + ファンダメンタルズ劣化）同時該当時は即時除外 + 優先度高のLINE通知 | ⬜ | |
| 3-20 | **signals.csv 拡張**: `list_type`（watch/buy_candidate）列を追加し、銘柄がどのリストに属するかを記録 | ⬜ | |

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
| 7-1 | Comps分析レポート（同業他社5社との5+5指標比較表）| ⬜ | `financial-services/comps-analysis` |
| 7-2 | 簡易DCFモデル自動計算（WACC・TV・フェアバリュー試算）| ⬜ | `financial-services/dcf-model` |
| 7-3 | 決算レビュー自動化（Beat/Miss・ガイダンス変更の解析）| ⬜ | `financial-services/earnings-reviewer` |
| 7-4 | マルチエージェント分解（Researcher → Screener → Analyst）| ⬜ | `financial-services/managed-agents` |
| 7-5 | ポートフォリオ管理・リバランス提案 | ⬜ | `financial-services/wealth-management` |

---

## 進捗サマリー

```
✅ 完了       : 40項目（6-3 デプロイ完了 2026-05-16）
🔧 設定未完了 :  0項目
⬜ 未着手     : 17項目（購入候補リスト管理・売却判断3項目・signals.csv拡張・バリュエーション合理性チェック・定性分析4項目・LINE翌朝通知・将来拡張5項目・Secret Manager移行・キャッシュ永続化）
```

### 直近の優先アクション

1. **`Secret Manager 移行`（5-8）** ⚠️ セキュリティ — `settings.yaml` の平文APIキーを GCP Secret Manager へ移行し、Cloud Run 環境変数として注入する
2. **`キャッシュ永続化`（5-9）** — Cloud Storage バケットへの読み書きを `cache.py` に追加し、週次ジョブの実行時間・コストを削減する
3. **`②購入候補リスト管理`（3-15〜16）** — BUYシグナル発生時に `buy_candidates.md` へ追加するロジック実装 + `watch_list.md` 出力への切り替え
4. **`③売却判断（軸A）`（3-17）** — テクニカルSELLシグナルで購入候補リストから除外 + LINE通知
5. **`③売却判断（軸B）`（3-18〜19）** — 週次ファンダメンタルズ再確認ロジック + 両軸同時除外
6. **`バリュエーション合理性チェック`（2-14）** — 上位20社のEV/Revenue・EV/EBITDA・PER・PBRレンジをレポートに追記
7. **`定性分析プロンプト設計`（2-19）** — `claude_analyzer.py` に `analyze_qualitative()` メソッドを追加し、Q1〜Q5の5フレームワーク評価を Gemini に生成させる
8. **`定性分析スコア生成`（2-20）** — Strong/Moderate/Weak/Unknown ラベル・根拠コメント・総合定性スコア（0〜10）の出力フォーマットを実装
9. **`週次レポートへの定性分析追記`（2-21）** — Top5 各社の定性分析テーブルを `watch_list.md` に統合
10. **`情報ソースリンク追記`（2-22）** — 銘柄ごとに EDINET / TDnet / IR ページのURL を自動生成してレポートに付記
11. **`LINE翌朝通知`（4-4）** — 通知専用の朝9:00 cronジョブ追加（小規模）
