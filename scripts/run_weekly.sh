#!/bin/bash
# 週次スクリーニング実行スクリプト（cron用）
# 実行タイミング: 毎週日曜日 8:00 AM
# cron設定: 0 8 * * 0 /path/to/scripts/run_weekly.sh >> /path/to/logs/weekly.log 2>&1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 週次パイプライン開始"

# Python PATH（pyenvやanacondaを使っている場合はパスを調整）
PYTHON=$(which python3)

$PYTHON pipelines/weekly_pipeline.py

EXIT_CODE=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 週次パイプライン終了（終了コード: $EXIT_CODE）"
exit $EXIT_CODE
