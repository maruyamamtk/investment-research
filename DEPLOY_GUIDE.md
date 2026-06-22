# 動作確認 & Cloud Run デプロイ手順書

## 目次

1. [前提条件](#前提条件)
2. [ローカル動作確認](#ローカル動作確認)
3. [Cloud Run デプロイ](#cloud-run-デプロイ)
4. [クラウド上の動作確認](#クラウド上の動作確認)
5. [スケジュール確認](#スケジュール確認)
6. [トラブルシューティング](#トラブルシューティング)

---

## 前提条件

### 必要なツール

```bash
python3 --version   # 3.11 以上
docker --version    # Docker Desktop 起動済み
gcloud --version    # Google Cloud CLI
```

### 必要な認証情報

| 項目 | 取得先 | 用途 |
|------|--------|------|
| J-Quants APIキー | https://jpx-jquants.com/ | 日本株データ取得（V2・APIキー方式） |
| Gemini API キー | https://aistudio.google.com/ | AI分析 |
| LINE Channel Access Token | LINE Developers Console | LINE通知 |
| LINE User ID | LINE Developers Console | LINE通知 |

---

## ローカル動作確認

### Step 1: 環境セットアップ

```bash
cd ~/Desktop/investment_research

# 依存パッケージインストール
bash scripts/setup.sh
```

### Step 2: APIキー設定

`config/settings.yaml` を編集してAPIキーを記入する（`.gitignore` 対象なのでコミットされない）：

```yaml
api:
  jquants:
    api_key: "your-jquants-api-key"   # V2 APIキー（必須）
  gemini:
    api_key: "AIza..."
  line:
    channel_access_token: "your-token"
    user_id: "Uxxxxxxxx"
```

または環境変数で指定（`config/settings.yaml` より優先される）：

```bash
export JQUANTS_API_KEY="your-jquants-api-key"
export GEMINI_API_KEY="AIza..."
export LINE_CHANNEL_ACCESS_TOKEN="your-token"
export LINE_USER_ID="Uxxxxxxxx"
```

### Step 3: 単体テスト実行

```bash
cd ~/Desktop/investment_research

# 全テスト
python3 -m pytest tests/ -v

# 特定モジュールのみ
python3 -m pytest tests/test_unified_scorer_stage2.py -v
```

### Step 4: パイプライン動作確認

#### 週次パイプライン（週次スクリーニング）

```bash
# --dry-run: APIを呼ばずにキャッシュデータで動作確認
python3 pipelines/weekly_pipeline.py --dry-run

# 本番モード（APIキー必要）
python3 pipelines/weekly_pipeline.py
```

出力: `output/watch_list.md`, `output/weekly_moat_stocks.md`

#### 日次パイプライン（売買シグナル検知）

```bash
# --dry-run
python3 pipelines/daily_pipeline.py --dry-run

# 特定銘柄で動作確認（トヨタ）
python3 pipelines/daily_pipeline.py --ticker 7203.T --dry-run

# 本番モード
python3 pipelines/daily_pipeline.py
```

出力: `output/daily_trade_signals.md`, `output/signals.csv`

#### 翌朝通知パイプライン（LINE送信）

```bash
# 通知キュー確認
cat output/notification_queue.json

# 通知送信（LINE APIキー必要）
python3 pipelines/notify_morning.py
```

#### 決算レビュー・DCFパイプライン

```bash
python3 pipelines/earnings_pipeline.py
python3 pipelines/dcf_pipeline.py
```

### Step 5: entrypoint.py での動作確認（Cloud Run と同等）

```bash
# 環境変数で切り替え（Cloud Run と同じ動作）
PIPELINE=weekly python3 pipelines/entrypoint.py
PIPELINE=daily  python3 pipelines/entrypoint.py
PIPELINE=notify python3 pipelines/entrypoint.py
```

### Step 6: Docker イメージのローカルテスト

```bash
cd ~/Desktop/investment_research

# イメージビルド
docker build -t investment-research:local .

# 週次パイプラインをコンテナ内で実行
docker run --rm \
  -e PIPELINE=weekly \
  -e JQUANTS_API_KEY="${JQUANTS_API_KEY}" \
  -e GEMINI_API_KEY="${GEMINI_API_KEY}" \
  -e LINE_CHANNEL_ACCESS_TOKEN="${LINE_CHANNEL_ACCESS_TOKEN}" \
  -e LINE_USER_ID="${LINE_USER_ID}" \
  investment-research:local \
  python3 pipelines/entrypoint.py

# 日次パイプラインをコンテナ内で実行
docker run --rm \
  -e PIPELINE=daily \
  -e JQUANTS_API_KEY="${JQUANTS_API_KEY}" \
  -e GEMINI_API_KEY="${GEMINI_API_KEY}" \
  investment-research:local \
  python3 pipelines/entrypoint.py
```

---

## Cloud Run デプロイ

### Step 1: GCP 認証

```bash
gcloud auth login
gcloud config set project keiba-prediction-1768734113
```

### Step 2: Secret Manager にシークレットを登録（初回のみ）

```bash
PROJECT_ID="keiba-prediction-1768734113"

# 各シークレットを作成（値を直接入力）
echo -n "your-jquants-api-key" | \
  gcloud secrets create jquants-api-key --data-file=- --project "${PROJECT_ID}"

echo -n "your-gemini-api-key" | \
  gcloud secrets create gemini-api-key --data-file=- --project "${PROJECT_ID}"

echo -n "your-line-channel-token" | \
  gcloud secrets create line-channel-access-token --data-file=- --project "${PROJECT_ID}"

echo -n "your-line-user-id" | \
  gcloud secrets create line-user-id --data-file=- --project "${PROJECT_ID}"
```

既存シークレットの値を更新する場合：

```bash
echo -n "new-value" | \
  gcloud secrets versions add jquants-api-key --data-file=- --project "${PROJECT_ID}"
```

### Step 3: GCS キャッシュバケットの作成（初回のみ）

```bash
PROJECT_ID="keiba-prediction-1768734113"
REGION="asia-northeast1"

gsutil mb -p "${PROJECT_ID}" -l "${REGION}" \
  "gs://${PROJECT_ID}-investment-cache"

# App Engine デフォルト SA に権限付与
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${PROJECT_ID}@appspot.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

### Step 4: デプロイ実行

```bash
cd ~/Desktop/investment_research

# デプロイスクリプト実行（ビルド → Cloud Run Jobs 作成/更新 → Scheduler 登録）
bash scripts/deploy_cloud_run.sh
```

スクリプトが実行する内容：
1. **[1/5]** Docker イメージを Artifact Registry へビルド & プッシュ
2. **[2/5]** `weekly-job` を作成または更新
3. **[3/5]** `daily-job` を作成または更新
4. **[4/5]** `notify-job` を作成または更新
5. **[5/5]** Cloud Scheduler にスケジュール登録

### スケジュール設定（変更不要、参考情報）

| ジョブ | 実行タイミング | cron (UTC) |
|--------|--------------|------------|
| `weekly-job` | 毎週日曜 8:00 JST | `0 23 * * 6` |
| `daily-job` | 平日 19:30 JST | `30 10 * * 1-5` |
| `notify-job` | 平日 9:00 JST | `0 0 * * 2-6` |

---

## クラウド上の動作確認

### Step 1: 手動実行でジョブをテスト

```bash
PROJECT_ID="keiba-prediction-1768734113"
REGION="asia-northeast1"

# 週次ジョブを即時実行
gcloud run jobs execute weekly-job \
  --region "${REGION}" \
  --project "${PROJECT_ID}"

# 日次ジョブを即時実行
gcloud run jobs execute daily-job \
  --region "${REGION}" \
  --project "${PROJECT_ID}"

# 通知ジョブを即時実行
gcloud run jobs execute notify-job \
  --region "${REGION}" \
  --project "${PROJECT_ID}"
```

### Step 2: 実行ログの確認

```bash
PROJECT_ID="keiba-prediction-1768734113"
REGION="asia-northeast1"

# 週次ジョブのログ（直近100件）
gcloud logging read \
  'resource.type="cloud_run_job" resource.labels.job_name="weekly-job"' \
  --project "${PROJECT_ID}" \
  --limit 100 \
  --format "value(timestamp, textPayload)" | head -50

# 日次ジョブのログ
gcloud logging read \
  'resource.type="cloud_run_job" resource.labels.job_name="daily-job"' \
  --project "${PROJECT_ID}" \
  --limit 100 \
  --format "value(timestamp, textPayload)" | head -50
```

または Claude Code のスキルを使う（要 gcloud 認証済み）：

```
/check-logs
```

### Step 3: ジョブ実行結果の確認

```bash
PROJECT_ID="keiba-prediction-1768734113"
REGION="asia-northeast1"

# 過去の実行一覧と成否確認
gcloud run jobs executions list \
  --job weekly-job \
  --region "${REGION}" \
  --project "${PROJECT_ID}"

gcloud run jobs executions list \
  --job daily-job \
  --region "${REGION}" \
  --project "${PROJECT_ID}"
```

成功時は `SUCCEEDED`、失敗時は `FAILED` と表示される。

### Step 4: Cloud Console での確認

- **Cloud Run Jobs**: https://console.cloud.google.com/run/jobs?project=keiba-prediction-1768734113
- **Cloud Scheduler**: https://console.cloud.google.com/cloudscheduler?project=keiba-prediction-1768734113
- **Cloud Logging**: https://console.cloud.google.com/logs?project=keiba-prediction-1768734113

---

## スケジュール確認

登録済みスケジューラーの一覧：

```bash
gcloud scheduler jobs list \
  --location asia-northeast1 \
  --project keiba-prediction-1768734113
```

スケジューラーを手動トリガー（スケジュール外で即時実行）：

```bash
gcloud scheduler jobs run schedule-weekly-job \
  --location asia-northeast1 \
  --project keiba-prediction-1768734113
```

---

## トラブルシューティング

### Secret Manager: シークレットが読めない

```bash
# シークレット一覧確認
gcloud secrets list --project keiba-prediction-1768734113

# 最新バージョンの値を確認
gcloud secrets versions access latest \
  --secret jquants-api-key \
  --project keiba-prediction-1768734113
```

### Cloud Run: イメージが古い

デプロイスクリプトを再実行して最新イメージを反映する：

```bash
bash scripts/deploy_cloud_run.sh
```

### Cloud Run: ジョブが `FAILED` になる

```bash
# 直近の実行詳細を確認
gcloud run jobs executions describe <execution-name> \
  --region asia-northeast1 \
  --project keiba-prediction-1768734113
```

ログからエラー箇所を特定し、ローカルで再現してから修正 → 再デプロイ。

### GCS キャッシュ: データが古い

```bash
# バケット内のキャッシュ一覧
gsutil ls gs://keiba-prediction-1768734113-investment-cache/

# 特定のキャッシュを削除（次回実行時に再取得）
gsutil rm gs://keiba-prediction-1768734113-investment-cache/prime_stock_list.json
```

### J-Quants: 認証エラー

J-Quants のIDトークンの有効期限は1日。Cloud Run では毎回取得するため通常問題ない。ローカルでキャッシュが古い場合：

```bash
rm cache/jquants_id_token.json
```
