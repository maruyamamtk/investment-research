---
name: deploy
description: Cloud Run Jobs をビルド・デプロイし、daily-job で動作確認まで実施する
disable-model-invocation: true
---

以下のステップを順に実行してください。失敗した場合はそこで止め、エラー内容を日本語で報告してください。

## Step 1: 認証・プロジェクト確認

```bash
gcloud auth list --filter=status:ACTIVE --format="value(account)"
gcloud config get-value project
```

アクティブアカウントとプロジェクトIDを表示し、続行してよいか確認する。

## Step 2: Artifact Registry リポジトリ確認・作成

```bash
gcloud artifacts repositories describe investment-research \
  --location=asia-northeast1 \
  --project=keiba-prediction-1768734113 2>/dev/null || echo "NOT_FOUND"
```

`NOT_FOUND` の場合は以下を実行してから次へ進む:

```bash
gcloud artifacts repositories create investment-research \
  --repository-format=docker \
  --location=asia-northeast1 \
  --project=keiba-prediction-1768734113
```

## Step 3: 必要な API の有効化確認

```bash
gcloud services list --enabled --project=keiba-prediction-1768734113 \
  --filter="name:(run.googleapis.com OR cloudscheduler.googleapis.com OR artifactregistry.googleapis.com OR cloudbuild.googleapis.com)" \
  --format="table(name,state)"
```

無効な API があれば有効化する:

```bash
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  --project=keiba-prediction-1768734113
```

## Step 4: デプロイ実行

```bash
cd /Users/michika_maruyama/Desktop/investment_research
bash scripts/deploy_cloud_run.sh
```

## Step 5: 動作確認（daily-job を手動実行）

```bash
gcloud run jobs execute daily-job \
  --region asia-northeast1 \
  --project keiba-prediction-1768734113 \
  --wait
```

終了コード 0 なら「✅ デプロイ＆動作確認 完了」と報告する。
失敗した場合は以下でログを確認して原因を報告する:

```bash
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="daily-job" AND severity>=ERROR' \
  --limit=20 \
  --project=keiba-prediction-1768734113 \
  --format="table(timestamp,textPayload)"
```
