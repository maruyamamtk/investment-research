#!/bin/bash
# 日次シグナル検知実行スクリプト（cron用）
# 実行タイミング: 平日（月〜金）19:30（東証閉場後）
# cron設定: 30 19 * * 1-5 /path/to/scripts/run_daily.sh >> /path/to/logs/daily.log 2>&1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 日次パイプライン開始"

PYTHON=$(which python3)

$PYTHON pipelines/daily_pipeline.py

EXIT_CODE=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 日次パイプライン終了（終了コード: $EXIT_CODE）"
exit $EXIT_CODE
