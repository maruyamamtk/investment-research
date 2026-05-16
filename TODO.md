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
| 2-14 | **Step2-H**: バリュエーション合理性チェック（EV/Revenue・EV/EBITDA・PER・PBRのレンジ確認をレポートに記載）| ⬜ | 要件定義書 §3.1 参照 |
| 2-15 | **Step2-I**: 銘柄分類（「全条件」「EPS条件のみ」）| ✅ | |
| 2-16 | Gemini AI 投資テーゼ生成（Top5銘柄）| ✅ | APIキー設定済み・動作確認済み |
| 2-17 | Gemini AI ベアケース・リスク分析生成（Top5銘柄）| ✅ | APIキー設定済み・動作確認済み |
| 2-18 | `weekly_moat_stocks.md` 出力 | ✅ | |

---

## 3. 日次シグナル検知

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

---

## 6. 自動実行（Cron）

| # | 項目 | 状態 | 備考 |
|---|------|------|------|
| 6-1 | 週次cronスクリプト作成（`run_weekly.sh`）| ✅ | |
| 6-2 | 日次cronスクリプト作成（`run_daily.sh`）| ✅ | |
| 6-3 | Cloud Run + Cloud Schedulerへの登録 | ⬜ | Dockerfile作成 → Artifact Registryへpush → Cloud Run Jobs作成 → Cloud Schedulerで定時起動設定 |

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
✅ 完了       : 39項目
🔧 設定未完了 :  0項目
⬜ 未着手     :  4項目（バリュエーション合理性チェック・LINE翌朝通知・cron登録・将来拡張5項目）
```

### 直近の優先アクション

1. **`Cloud Run + Cloud Scheduler登録`（6-3）** — Dockerfile作成・デプロイ・スケジューラ設定が必要
2. **`Gemini APIキー設定`（1-6）** — `config/settings.yaml` の `api.gemini.api_key` に入力するだけで AI機能（2-16・2-17・3-12）が一括解決
3. **`バリュエーション合理性チェック`（2-14）** — レポートへの倍数レンジ備考追記（コード修正）
4. **`LINE翌朝通知`（4-4）** — 通知専用の朝9:00 cronジョブの追加（小規模な実装）
