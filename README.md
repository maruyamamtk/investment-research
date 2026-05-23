# 日本株投資調査自動化システム

## 目的

日本株プライム市場（約1,600社）を対象に、**定量的なファンダメンタルズ分析**と**テクニカル分析**を自動で実行し、中長期的に市場をアウトパフォームする可能性の高い銘柄の発見と、最適な売買タイミングの検知を支援するシステムです。

人間が週次・日次で行う銘柄調査を自動化することで、感情に左右されない規律ある投資判断の補助ツールとして機能します。

## 概要

銘柄選定は **3段階** で自動管理されます。

```
全プライム市場銘柄（約1,600社）
        ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【①週次】監視対象銘柄の選定（毎週日曜 8:00）
  Step1: 基本財務フィルタ（業績不振・財務脆弱な企業を除外）→ 約200〜400社
  Step2: 成長性・モート精緻分析（EPS成長・ROE・FCF・スコアリング）→ 上位20社
  Gemini AI: 投資テーゼ・ベアケース・定性分析（Top5銘柄）
        ↓ 監視対象銘柄リスト（watch_list.md）更新
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【②日次】購入銘柄の選定（平日 19:30）
  監視対象リストにテクニカル分析を実施
  BUYシグナル（≥3点）発生 → 購入候補リストに追加
  ※チャート状況によっては長期間選定が行われない可能性あり
        ↓ 購入候補リスト（buy_candidates.md）に追加
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【③日次 + 週次】売却銘柄の選定
  購入候補リストの銘柄にテクニカル分析 + ①と同等のファンダメンタルズ再確認
  SELLシグナル OR 条件劣化 → 購入候補リストから除外・LINE通知
        ↓ 購入候補リスト（buy_candidates.md）から削除
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        → daily_trade_signals.md / signals.csv（全シグナル記録）
        → LINE通知（BUY追加・SELL除外・監視リスト変更時）
```

全体フローの詳細は [`flowchart.html`](flowchart.html) を参照してください。

### 使用データソース

| ソース | 用途 |
|--------|------|
| J-Quants API（無料） | プライム市場の全銘柄リスト・財務諸表（EPS・売上・ROE） |
| Yahoo Finance（yfinance） | 株価OHLCV履歴・財務比率・決算予定日 |
| Gemini API（任意） | 投資メモ・シグナル解説の自然言語生成 |

## クイックスタート

```bash
# 1. 依存パッケージのインストール
bash scripts/setup.sh

# 2. APIキーを設定
#    config/settings.yaml の api.jquants と api.gemini を編集

# 3. 動作テスト（APIキー不要）
python3 pipelines/daily_pipeline.py --ticker 7203.T --dry-run

# 4. 週次スクリーニング（全銘柄）
python3 pipelines/weekly_pipeline.py

# 5. Cron自動実行を設定
bash scripts/setup_cron.sh
```

## 出力ファイル

| ファイル | 内容 | 更新タイミング | 生成パイプライン |
|---------|------|-------------|----------------|
| `output/watch_list.md` | ①監視対象銘柄リスト・AI投資テーゼ | 週次（日曜 8:00） | `pipelines/weekly_pipeline.py` |
| `output/weekly_moat_stocks.md` | `watch_list.md` への後方互換シンボリックリンク | 週次（日曜 8:00） | `pipelines/weekly_pipeline.py` |
| `output/buy_candidates.md` | ②購入候補銘柄リスト（BUYシグナル銘柄） | BUY追加: `daily_pipeline.py` / 軸B削除: `weekly_pipeline.py` | `pipelines/daily_pipeline.py` + `pipelines/weekly_pipeline.py` |
| `output/daily_trade_signals.md` | 当日の全シグナル一覧・判定理由 | 日次（平日 19:30） | `pipelines/daily_pipeline.py` |
| `output/signals.csv` | 機械可読シグナルデータ | 日次（平日 19:30） | `pipelines/daily_pipeline.py` |
| `output/earnings_review_YYYYMMDD.md` | 決算Beat/Miss・ガイダンス変化レポート | 手動実行 | `pipelines/earnings_pipeline.py` |

## 詳細仕様

スクリーニング条件・テクニカル指標の閾値・システム要件の詳細は [**要件定義書**](REQUIREMENTS.md) を参照してください。

---

> **免責事項**: このシステムは情報提供を目的とした補助ツールであり、投資助言ではありません。投資判断はご自身の責任で行ってください。
