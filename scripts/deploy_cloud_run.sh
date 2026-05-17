#!/usr/bin/env bash
# Cloud Run Jobs + Cloud Scheduler デプロイスクリプト
# 使い方: bash scripts/deploy_cloud_run.sh
set -euo pipefail

# ── 変数定義 ──────────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:-keiba-prediction-1768734113}"
REGION="asia-northeast1"                               # 東京リージョン
REPO="investment-research"                             # Artifact Registry リポジトリ名
IMAGE_NAME="investment-research"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE_NAME}:latest"

# Cloud Run Jobs 設定
WEEKLY_JOB="weekly-job"
DAILY_JOB="daily-job"
TASK_TIMEOUT="7200s"   # 週次は最大2時間
DAILY_TIMEOUT="900s"   # 日次は最大15分
MAX_RETRIES=1

# Cloud Scheduler 設定（UTC）
# 週次: JST日曜 8:00 = UTC土曜 23:00
WEEKLY_SCHEDULE="0 23 * * 6"
# 日次: JST平日 19:30 = UTC平日 10:30
DAILY_SCHEDULE="30 10 * * 1-5"

SCHEDULER_SA="${PROJECT_ID}@appspot.gserviceaccount.com"

# GCS キャッシュバケット（Cloud Run エフェメラル問題の解消）
# 事前作成: gsutil mb -p ${PROJECT_ID} -l ${REGION} gs://${PROJECT_ID}-investment-cache
# IAM付与: gcloud projects add-iam-policy-binding ${PROJECT_ID} \
#           --member=serviceAccount:${PROJECT_ID}@appspot.gserviceaccount.com \
#           --role=roles/storage.objectAdmin
GCS_CACHE_BUCKET="${GCS_CACHE_BUCKET:-${PROJECT_ID}-investment-cache}"

# Secret Manager シークレット名（gcloud secrets create で事前に作成が必要）
# 作成例:
#   echo -n "value" | gcloud secrets create jquants-email      --data-file=- --project ${PROJECT_ID}
#   echo -n "value" | gcloud secrets create jquants-password   --data-file=- --project ${PROJECT_ID}
#   echo -n "value" | gcloud secrets create gemini-api-key     --data-file=- --project ${PROJECT_ID}
#   echo -n "value" | gcloud secrets create line-channel-access-token --data-file=- --project ${PROJECT_ID}
#   echo -n "value" | gcloud secrets create line-user-id       --data-file=- --project ${PROJECT_ID}
# --set-secrets は1フラグにカンマ区切りで指定（複数フラグにすると後続が前を上書きするため）
SECRET_FLAGS="JQUANTS_EMAIL=jquants-email:latest,JQUANTS_PASSWORD=jquants-password:latest,GEMINI_API_KEY=gemini-api-key:latest,LINE_CHANNEL_ACCESS_TOKEN=line-channel-access-token:latest,LINE_USER_ID=line-user-id:latest"
# ──────────────────────────────────────────────────────────

echo "=== プロジェクト: ${PROJECT_ID} / リージョン: ${REGION} ==="

# ── ステップ 1: イメージビルド & Artifact Registry へ push ──
echo ""
echo ">>> [1/4] Docker イメージをビルドして Artifact Registry へ push"
gcloud builds submit . \
  --tag "${IMAGE}" \
  --project "${PROJECT_ID}"

# ── ステップ 2: weekly-job 作成（既存なら更新） ──────────
echo ""
echo ">>> [2/4] Cloud Run Jobs: ${WEEKLY_JOB} を作成/更新"
if gcloud run jobs describe "${WEEKLY_JOB}" --region "${REGION}" --project "${PROJECT_ID}" &>/dev/null; then
  gcloud run jobs update "${WEEKLY_JOB}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --task-timeout "${TASK_TIMEOUT}" \
    --max-retries "${MAX_RETRIES}" \
    --set-env-vars "PIPELINE=weekly,GCS_CACHE_BUCKET=${GCS_CACHE_BUCKET}" \
    --set-secrets "${SECRET_FLAGS}"
else
  gcloud run jobs create "${WEEKLY_JOB}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --task-timeout "${TASK_TIMEOUT}" \
    --max-retries "${MAX_RETRIES}" \
    --set-env-vars "PIPELINE=weekly,GCS_CACHE_BUCKET=${GCS_CACHE_BUCKET}" \
    --set-secrets "${SECRET_FLAGS}"
fi

# ── ステップ 3: daily-job 作成（既存なら更新） ───────────
echo ""
echo ">>> [3/4] Cloud Run Jobs: ${DAILY_JOB} を作成/更新"
if gcloud run jobs describe "${DAILY_JOB}" --region "${REGION}" --project "${PROJECT_ID}" &>/dev/null; then
  gcloud run jobs update "${DAILY_JOB}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --task-timeout "${DAILY_TIMEOUT}" \
    --max-retries "${MAX_RETRIES}" \
    --set-env-vars "PIPELINE=daily,GCS_CACHE_BUCKET=${GCS_CACHE_BUCKET}" \
    --set-secrets "${SECRET_FLAGS}"
else
  gcloud run jobs create "${DAILY_JOB}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --task-timeout "${DAILY_TIMEOUT}" \
    --max-retries "${MAX_RETRIES}" \
    --set-env-vars "PIPELINE=daily,GCS_CACHE_BUCKET=${GCS_CACHE_BUCKET}" \
    --set-secrets "${SECRET_FLAGS}"
fi

# ── ステップ 4: Cloud Scheduler ジョブ登録 ───────────────
echo ""
echo ">>> [4/4] Cloud Scheduler ジョブを登録"

_WEEKLY_JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${WEEKLY_JOB}:run"
_DAILY_JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${DAILY_JOB}:run"

# 週次スクリーニング（UTC土曜 23:00 = JST日曜 8:00）
if gcloud scheduler jobs describe "schedule-${WEEKLY_JOB}" --location "${REGION}" --project "${PROJECT_ID}" &>/dev/null; then
  gcloud scheduler jobs update http "schedule-${WEEKLY_JOB}" \
    --location "${REGION}" \
    --project "${PROJECT_ID}" \
    --schedule "${WEEKLY_SCHEDULE}" \
    --uri "${_WEEKLY_JOB_URI}" \
    --http-method POST \
    --oauth-service-account-email "${SCHEDULER_SA}" \
    --time-zone "UTC"
else
  gcloud scheduler jobs create http "schedule-${WEEKLY_JOB}" \
    --location "${REGION}" \
    --project "${PROJECT_ID}" \
    --schedule "${WEEKLY_SCHEDULE}" \
    --uri "${_WEEKLY_JOB_URI}" \
    --http-method POST \
    --oauth-service-account-email "${SCHEDULER_SA}" \
    --time-zone "UTC" \
    --description "週次スクリーニング (JST日曜8:00)"
fi

# 日次シグナル検知（UTC平日 10:30 = JST平日 19:30）
if gcloud scheduler jobs describe "schedule-${DAILY_JOB}" --location "${REGION}" --project "${PROJECT_ID}" &>/dev/null; then
  gcloud scheduler jobs update http "schedule-${DAILY_JOB}" \
    --location "${REGION}" \
    --project "${PROJECT_ID}" \
    --schedule "${DAILY_SCHEDULE}" \
    --uri "${_DAILY_JOB_URI}" \
    --http-method POST \
    --oauth-service-account-email "${SCHEDULER_SA}" \
    --time-zone "UTC"
else
  gcloud scheduler jobs create http "schedule-${DAILY_JOB}" \
    --location "${REGION}" \
    --project "${PROJECT_ID}" \
    --schedule "${DAILY_SCHEDULE}" \
    --uri "${_DAILY_JOB_URI}" \
    --http-method POST \
    --oauth-service-account-email "${SCHEDULER_SA}" \
    --time-zone "UTC" \
    --description "日次シグナル検知 (JST平日19:30)"
fi

echo ""
echo "=== デプロイ完了 ==="
echo "  イメージ   : ${IMAGE}"
echo "  weekly-job : ${WEEKLY_SCHEDULE} UTC (JST日曜 8:00)"
echo "  daily-job  : ${DAILY_SCHEDULE} UTC (JST平日 19:30)"
echo ""
echo "手動実行テスト:"
echo "  gcloud run jobs execute ${WEEKLY_JOB} --region ${REGION} --project ${PROJECT_ID}"
echo "  gcloud run jobs execute ${DAILY_JOB}  --region ${REGION} --project ${PROJECT_ID}"
