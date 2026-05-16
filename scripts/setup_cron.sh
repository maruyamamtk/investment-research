#!/bin/bash
# Cron自動実行の設定スクリプト

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

chmod +x "$SCRIPT_DIR/run_weekly.sh"
chmod +x "$SCRIPT_DIR/run_daily.sh"

WEEKLY_CRON="0 8 * * 0 cd $PROJECT_DIR && $SCRIPT_DIR/run_weekly.sh >> $PROJECT_DIR/logs/weekly.log 2>&1"
DAILY_CRON="30 19 * * 1-5 cd $PROJECT_DIR && $SCRIPT_DIR/run_daily.sh >> $PROJECT_DIR/logs/daily.log 2>&1"

echo "現在のcron設定:"
crontab -l 2>/dev/null || echo "（cron未設定）"
echo ""
echo "以下のcronジョブを追加します:"
echo "  週次: $WEEKLY_CRON"
echo "  日次: $DAILY_CRON"
echo ""
read -p "追加しますか？ [y/N]: " confirm

if [[ "$confirm" =~ ^[Yy]$ ]]; then
    (crontab -l 2>/dev/null; echo "$WEEKLY_CRON"; echo "$DAILY_CRON") | crontab -
    echo "Cronジョブを設定しました。"
    echo ""
    echo "現在のcron設定:"
    crontab -l
else
    echo "キャンセルしました。"
    echo ""
    echo "手動で設定する場合は以下を crontab -e で追加してください:"
    echo "$WEEKLY_CRON"
    echo "$DAILY_CRON"
fi
