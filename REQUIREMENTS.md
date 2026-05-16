# 要件定義書

**システム名**: 日本株投資調査自動化システム  
**バージョン**: 1.0  
**最終更新**: 2026-05-16  
**参照元**:
- `Desktop/日本株分析/` — 既存スクリーニングロジック
- [anthropics/financial-services](https://github.com/anthropics/financial-services) — Claude AI金融分析パターン

---

## 1. システム概要

### 1.1 目的

日本株プライム市場（約1,600社）を対象に、週次のファンダメンタルズスクリーニングと日次のテクニカルシグナル検知を自動化し、投資判断の補助情報を提供する。

### 1.2 設計原則

- **再現性**: 同じ入力データに対して同じ結果を出力する定量ロジック
- **透明性**: シグナルの判定理由を自然言語で説明する（Claude AI）
- **保守性**: APIキーなしでも`--dry-run`モードで動作確認できる
- **コスト効率**: キャッシュにより不要なAPI呼び出しを抑制する

---

## 2. データ要件

### 2.1 データソース

| ソース | 用途 | 取得方法 | 更新頻度 |
|--------|------|---------|---------|
| J-Quants API `/listed/info` | プライム市場の全銘柄コード・企業情報 | REST API（認証トークン） | 週次キャッシュ（168h） |
| J-Quants API `/fins/statements` | EPS・売上高・利益・自己資本の財務諸表 | REST API（銘柄別） | 週次キャッシュ（168h） |
| Yahoo Finance `ticker.info` | PER・PBR・ROE・時価総額・営業利益率 | yfinance ライブラリ | 週次キャッシュ（168h） |
| Yahoo Finance `ticker.financials` | 損益計算書・貸借対照表・キャッシュフロー | yfinance ライブラリ | 週次キャッシュ（168h） |
| Yahoo Finance `yf.download()` | 日足OHLCV（終値・出来高） | yfinance ライブラリ | 日次キャッシュ（24h） |
| Yahoo Finance `ticker.calendar` | 次回決算発表予定日 | yfinance ライブラリ | キャッシュなし（毎回取得） |

### 2.2 対象市場

- 東京証券取引所 プライム市場（MarketCode: `0111`）
- 対象銘柄数: 約1,571社（J-Quants APIで取得）
- J-Quantsの無料プランは財務データに約12週間の遅延があるため、リアルタイムの財務比率はyfinanceで補完する

### 2.3 データ取得制約

- yfinanceはレート制限なしだが、非公式APIのため過度な並列リクエストを避ける
- バッチサイズ: 30銘柄/回、バッチ間インターバル: 2秒
- J-Quants `/fins/statements` はリフレッシュトークン → IDトークンの2段階認証が必要

---

## 3. 機能要件

### 3.1 週次スクリーニングパイプライン

毎週日曜日 8:00 に自動実行し、全プライム銘柄を2段階でスクリーニングして `weekly_moat_stocks.md` を更新する。

#### Step 1: 基本財務フィルタ（全1,600社 → 約200〜400社）

業績が著しく悪化している企業・財務的に脆弱な企業を除外する。yfinance `ticker.info` から取得した指標を使用する。

| 条件 | 閾値 | 除外する企業像 |
|------|------|-------------|
| 時価総額 | ≥ 100億円 | 流動性が低く取引困難な小型株 |
| 営業利益率 | > 0% | 本業が赤字の企業 |
| PBR | > 0 | 純資産がマイナスの債務超過企業 |
| 売上高成長率（前年比） | ≥ −10% | 大幅な収縮局面にある企業 |
| 自己資本比率 | ≥ 10% | 過剰なレバレッジを抱える企業 |

#### Step 2: 成長性・キャッシュフロー・バリュエーション精緻分析（200〜400社 → 上位20社）

「経済的な堀（Moat）」を持つ高成長・高資本効率の企業を選定する。

**2-A. 年次EPS成長フィルタ**（J-Quants `/fins/statements` から取得）

- 直近3期分の年次EPS（1株当たり利益）を取得する
- 条件: **直近3期のEPSがすべてプラス**、かつ**各期の成長率が25%以上**
- `filter_eps_annual_stocks()` ロジックを参照

**2-B. 四半期EPS成長フィルタ**（J-Quants `/fins/statements` から取得）

- 直近3四半期のEPS成長率を取得する
- 条件: **直近3四半期のEPSがすべてプラス**、かつ**各四半期の成長率が25%以上**、かつ**EPS成長が単調増加**（加速しているか横ばいを許容）
- 単調性チェック: EPS成長差分の四半期順序と成長率順序が一致していること

**2-C. 四半期売上高フィルタ**（J-Quants `/fins/statements` から取得）

以下のいずれかを満たすこと（OR条件）:
- （A）直近3四半期の売上高成長率がすべてプラス
- （B）直近四半期の売上高成長率が25%以上

**2-D. ROEフィルタ**（J-Quants財務データ または yfinance から計算）

- 条件: **直近1年のROE > 15%**
- 計算式: `ROE = 当期純利益 / 自己資本`

**2-E. キャッシュフロー品質フィルタ**（yfinance `ticker.cashflow` から取得）

- フリーキャッシュフロー（FCF = 営業CF + 設備投資）が**直近2期連続プラス**
- CF品質（OCF / 純利益）: **≥ 0.8**（利益の裏付けとなる現金創出力）

**2-F. 財務健全性フィルタ**（yfinance `ticker.info` から取得）

- ネット有利子負債 / EBITDA: **≤ 3.0x**

**2-G. スコアリングと最終選定**

ハードフィルタ（2-A〜F）を通過した銘柄に対して、以下の指標で0〜10点スコアを付与し加重平均で上位20社を選定する。

| 指標 | 重み | スコア基準 |
|------|------|---------|
| ROE | 25% | 0% → 0点、30% → 10点 |
| 売上高CAGR（3年） | 20% | 0% → 0点、20% → 10点 |
| CF品質（OCF/純利益） | 20% | 0 → 0点、2.0 → 10点 |
| ネット有利子負債/EBITDA | 15% | 5x → 0点、0x → 10点（逆転） |
| 営業利益率 | 10% | 0% → 0点、25% → 10点 |
| 配当性向 | 10% | 70% → 0点、0% → 10点（逆転） |

**2-H. バリュエーション合理性チェック**（financial-services Comps分析パターンを参照）

スコア上位20社について以下の倍数レンジを確認し、著しく逸脱している場合は備考としてレポートに記載する（除外はしない）。

| 指標 | 合理的レンジ |
|------|-------------|
| EV/Revenue | 0.5x〜20x |
| EV/EBITDA | 8x〜25x |
| PER（P/E） | 10x〜50x |
| PBR | 0.5x〜5x |

**2-I. 銘柄分類**（Desktop/日本株分析のロジックを踏襲）

| 分類 | 条件 |
|------|------|
| **全条件銘柄** | 2-A〜F すべてを満たす |
| **EPS条件銘柄** | 2-A・2-B のみ満たす（ROE・売上条件は未達） |

#### Gemini AI 分析（Step 2通過後 Top5銘柄）

financial-services の `equity-research` パターンを参考にした分析内容を生成する。

- **投資テーゼ**: 強み・成長ドライバー・競争優位性（200〜300字）
- **ベアケース**: リスクスコア（0〜10）・主なリスク要因3点（地政学リスク・金利耐性・競合・財務脆弱性）
- モデル: `gemini-2.0-flash`（コスト最適化）

### 3.2 日次シグナル検知パイプライン

平日 19:30（東証閉場後）に自動実行し、週次選定銘柄を対象にテクニカル分析を行い `daily_trade_signals.md` と `signals.csv` を更新する。

#### 使用するテクニカル指標

| 指標 | パラメータ | 計算ライブラリ |
|------|----------|-------------|
| 単純移動平均 (SMA) | 5日・20日・75日 | pandas（手実装） |
| 指数移動平均 (EMA) | 12日・26日 | pandas（手実装） |
| MACD | (12, 26, 9) | pandas（手実装） |
| RSI | 14日 | pandas（手実装） |
| ボリンジャーバンド | 20日・±2σ | pandas（手実装） |
| 出来高比率 | 当日 / 20日平均 | pandas（手実装） |

> `pandas-ta` がPython 3.9非対応のため、全指標を `src/technical/signals.py` に手実装している。

#### シグナル判定ロジック

**🟢 BUY（強度スコア3以上）**

以下の条件をスコアで加算し、3点以上かつBUY > SELLの場合:

| 条件 | スコア |
|------|-------|
| ゴールデンクロス発生（SMA5 > SMA20 に転換） | +3 |
| ゴールデンクロス維持 | +1 |
| RSI < 35 から反転上昇中 | +2 |
| RSI < 35（売られすぎ圏） | +1 |
| MACDヒストグラムがプラス転換 | +2 |
| MACDヒストグラムがプラス圏 | +1 |
| ボリンジャー下限ブレイク（反発期待） | +1 |
| 出来高比率 ≥ 1.2x（BUY優勢時に加算） | +1 |

**🔴 SELL（強度スコア3以上）**

| 条件 | スコア |
|------|-------|
| デッドクロス発生（SMA5 < SMA20 に転換） | +3 |
| デッドクロス維持 | +1 |
| RSI > 75 から反転下落中 | +2 |
| RSI > 75（過熱圏） | +1 |
| MACDヒストグラムがマイナス転換 | +2 |
| MACDヒストグラムがマイナス圏 | +1 |
| ボリンジャー上限ブレイク（過熱注意） | +1 |
| 出来高比率 ≥ 1.2x（SELL優勢時に加算） | +1 |

**🟡 HOLD（フェイクアウト回避）**

BUY/SELL条件を満たしていても、以下の場合はHOLDに上書きする:

- 次回決算発表日の **前後3日以内**（yfinance `ticker.calendar` で取得）
- BUYとSELLのスコアが拮抗している場合

**⚪ WATCH**

BUY/SELLスコアがともに3未満の場合。

#### フェイクアウト回避ルール（重要）

financial-services の「人間レビュー必須」原則に準拠し、以下のケースでは自動シグナルを抑制する:

1. 決算発表の前後3日間（誤ったシグナルが発生しやすい）
2. テクニカル指標のデータが30営業日未満の場合（指標の信頼性が低い）

### 3.3 通知・出力

#### 出力ファイル

| ファイル | 形式 | 内容 |
|---------|------|------|
| `output/weekly_moat_stocks.md` | Markdown | スコアランキング表・Top5の投資テーゼ・ベアケース |
| `output/daily_trade_signals.md` | Markdown | シグナル一覧・判定理由・AIコメント |
| `output/signals.csv` | CSV | 機械可読シグナルデータ（日付・銘柄・シグナル・指標値） |

#### LINE通知

`Desktop/日本株分析/line_notifier.py` の実装を参考に、以下のタイミングで通知を送信する:

- 🟢 BUY シグナルが発生した銘柄の一覧
- 🔴 SELL シグナルが発生した銘柄の一覧
- 前日比での新規追加・削除銘柄（週次ウォッチリスト変更時）
- 通知時刻: 平日 9:00（翌朝通知）/ 設定変更可

> LINE通知はオプション機能。`config/settings.yaml` の `api.line.enabled: false` で無効化できる。

---

## 4. 非機能要件

### 4.1 パフォーマンス

| 要件 | 目標値 |
|------|-------|
| 週次スクリーニング全体の実行時間 | 60〜120分（全1,600社対象時） |
| 日次シグナル検知の実行時間 | 5〜10分（20銘柄対象時） |
| APIキャッシュヒット時の再実行時間 | 1〜3分（週次）/ 1分（日次） |

### 4.2 信頼性・可用性

- パイプライン失敗時はログ（`logs/YYYYMMDD.log`）にエラーを記録し、正常終了した処理結果は保持する
- 個別銘柄のAPI取得失敗は `ERROR` シグナルとして出力し、他の銘柄の処理を継続する
- キャッシュ破損時は `--force-refresh` フラグで再取得できる

### 4.3 保守性

- APIキーなしでも `--dry-run` フラグで動作確認できる
- スクリーニング閾値はすべて `config/settings.yaml` で変更可能（コード修正不要）
- `--ticker` フラグで特定銘柄のみテスト実行できる

---

## 5. システム構成要件

### 5.1 実行環境

| 項目 | 要件 |
|------|------|
| 実行基盤 | Google Cloud Run Jobs（サーバーレスコンテナ） |
| スケジューラ | Cloud Scheduler（タイムゾーン: Asia/Tokyo） |
| Python | 3.11以上（Dockerイメージ） |
| 必須パッケージ | yfinance ≥ 0.2.40、PyYAML ≥ 6.0、tabulate ≥ 0.9.0、google-genai ≥ 1.0.0 |
| ネットワーク | J-Quants API・Yahoo Finance・LINE API・Gemini API への HTTPS アクセス |
| GCP | プロジェクト作成済み・Cloud Run / Cloud Scheduler / Artifact Registry API 有効化済み |

> **選定理由**: macOS のローカル cron はPCが起動していないと実行されない。Cloud Run Jobs はコンテナをオンデマンドで起動・実行・停止するため、PC非依存で確実に定時実行できる。

### 5.2 スケジューリング（Cloud Scheduler → Cloud Run Jobs）

Cloud Scheduler のスケジュール式は **UTC** で記述する。JST（UTC+9）からの変換に注意すること。

| ジョブ | JST | UTC | cron式（UTC） |
|--------|-----|-----|--------------|
| 週次スクリーニング | 日曜 8:00 JST | 日曜 23:00 UTC（前日土曜） | `0 23 * * 6` |
| 日次シグナル検知 | 平日 19:30 JST | 平日 10:30 UTC | `30 10 * * 1-5` |
| LINE翌朝通知 | 平日 9:00 JST | 平日 0:00 UTC | `0 0 * * 2-6` |

> Cloud Scheduler の `--time-zone=Asia/Tokyo` オプションを使えばJSTで直接指定可能だが、UTC基準の方が環境依存を減らせる。

#### アーキテクチャ概要

```
Cloud Scheduler（cron式）
    ↓ HTTP POST（OIDC認証）
Cloud Run Jobs
    ├── weekly-job  → pipelines/weekly_pipeline.py
    ├── daily-job   → pipelines/daily_pipeline.py
    └── notify-job  → pipelines/notify_morning.py（将来実装）
```

#### 機密情報の管理

APIキー（Gemini・J-Quants・LINE）は `config/settings.yaml` にハードコードせず、**Secret Manager** に格納してCloud Runの環境変数として注入する方式を推奨する。

### 5.3 ディレクトリ構成

```
investment_research/
├── Dockerfile                  # Cloud Run Jobs 用コンテナ定義
├── config/settings.yaml        # APIキー・閾値・通知設定（要編集）
├── src/
│   ├── data/
│   │   ├── jquants_client.py   # J-Quants APIクライアント（銘柄マスター・財務諸表）
│   │   └── yfinance_client.py  # Yahoo Financeクライアント（株価・財務比率）
│   ├── screener/
│   │   ├── step1_filter.py     # Step1: 基本財務フィルタ
│   │   └── step2_analysis.py   # Step2: 成長性・モート精緻分析
│   ├── technical/
│   │   └── signals.py          # テクニカル指標・シグナル判定（全指標手実装）
│   ├── ai_analyst/
│   │   └── claude_analyzer.py  # Gemini API（投資テーゼ・ベアケース・シグナル解説）
│   └── utils/
│       ├── cache.py            # JSONキャッシュ管理
│       └── logger.py           # ログ出力
├── pipelines/
│   ├── weekly_pipeline.py      # 週次パイプライン（--dry-run / --force-refresh）
│   └── daily_pipeline.py       # 日次パイプライン（--ticker / --dry-run）
├── output/                     # 自動生成レポート
├── cache/                      # APIキャッシュ（.json）
├── logs/                       # 実行ログ（日付別）
└── scripts/
    ├── setup.sh                # 初回セットアップ（ローカル）
    ├── deploy_cloud_run.sh     # Cloud Run デプロイスクリプト
    ├── run_weekly.sh           # 週次実行スクリプト（ローカルテスト用）
    └── run_daily.sh            # 日次cron実行スクリプト
```

### 5.4 必要なAPIキー

| サービス | 設定箇所 | 必須/任意 | 用途 |
|---------|---------|---------|------|
| J-Quants | `api.jquants.email` / `api.jquants.password` | **必須**（全銘柄スキャン） | 銘柄マスター・財務諸表取得 |
| Google Gemini | `api.gemini.api_key` | 任意 | 投資テーゼ・シグナル解説の生成 |
| LINE Messaging API | `api.line.channel_access_token` / `user_id` | 任意 | 売買シグナル・銘柄変更通知 |

---

## 6. 将来拡張（スコープ外）

以下の機能は現バージョンのスコープ外だが、`anthropics/financial-services` のパターンを参考に将来実装を検討する。

| 機能 | 参照パターン | 概要 |
|------|------------|------|
| DCFモデル自動生成 | `financial-analysis/dcf-model` | 上位銘柄の簡易DCFを自動計算・感度分析表を出力 |
| Comps分析レポート | `financial-analysis/comps-analysis` | 同業他社5社との5+5指標比較表を自動生成 |
| 決算レビュー自動化 | `earnings-reviewer` | 決算発表後に数値のBeat/Miss・ガイダンス変更を解析 |
| マルチエージェント分解 | Managed Agents パターン | Researcher → Screener → Analyst の職務分離 |
| ポートフォリオ管理 | `wealth-management/rebalance` | 保有銘柄のリバランス提案 |

---

## 7. 変更履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|---------|
| 1.0 | 2026-05-16 | 初版作成。Step1/Step2スクリーニング・テクニカルシグナル・LINE通知・AI分析の基本要件を定義 |

---

> **免責事項**: このシステムは情報提供を目的とした補助ツールであり、投資助言ではありません。すべての投資判断はご自身の責任で行ってください。
