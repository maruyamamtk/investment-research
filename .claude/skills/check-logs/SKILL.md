---
name: check-logs
description: Cloud Run Jobs（weekly-job・daily-job）の直近実行ログを取得してエラーを要約する
---

以下を実行し、結果を日本語で要約してください。

## weekly-job の直近ログ

```bash
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="weekly-job"' \
  --limit=150 \
  --project=keiba-prediction-1768734113 \
  --format="table(timestamp,severity,textPayload)" 2>/dev/null | head -80
```

## daily-job の直近ログ

```bash
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="daily-job"' \
  --limit=150 \
  --project=keiba-prediction-1768734113 \
  --format="table(timestamp,severity,textPayload)" 2>/dev/null | head -80
```

## 要約の形式

- ERROR / WARNING を抽出し、以下の形式で報告する:
  - **発生日時**
  - **ジョブ名**
  - **エラー内容**
  - **推定原因**（J-Quantsトークン切れ / yfinanceレート制限 / Gemini APIエラー / その他）
  - **推奨対処**
- エラーがなければ「✅ 直近の実行に問題はありません」と報告する。
