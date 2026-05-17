"""
翌朝通知パイプライン: 平日 9:00 JST（UTC 0:00）実行
output/notification_queue.json を読み込み LINE 送信 → キュークリア
"""
import json
import os
import sys
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notification.line_notifier import from_config as line_from_config
from src.utils.credentials import override_credentials
from src.utils.logger import get_logger

logger = get_logger("notify_morning")


def load_config(path: str = "config/settings.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    override_credentials(cfg)
    return cfg


def run_notify():
    logger.info("=" * 60)
    logger.info(f"翌朝通知パイプライン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    cfg = load_config()
    queue_path = cfg["output"].get("notification_queue", "output/notification_queue.json")

    if not os.path.exists(queue_path):
        logger.info(f"通知キューが存在しません: {queue_path}")
        logger.info("送信する通知はありません。")
        return

    with open(queue_path, encoding="utf-8") as f:
        queue = json.load(f)

    notifications = queue.get("notifications", [])
    queued_at = queue.get("queued_at", "不明")
    logger.info(f"キュー取得: {len(notifications)}件 (キュー日時: {queued_at})")

    if not notifications:
        logger.info("通知キューが空です。")
        _clear_queue(queue_path)
        return

    notifier = line_from_config(cfg)

    sent = 0
    for item in notifications:
        ntype = item.get("type")
        data = item.get("data")

        try:
            if ntype == "buy_candidate_added":
                if notifier.notify_buy_candidate_added(data):
                    sent += 1
            elif ntype == "sell_candidate_removed":
                reason = data.get("reason", "テクニカルSELL") if isinstance(data, dict) else "テクニカルSELL"
                if notifier.notify_sell_candidate_removed(data, reason=reason):
                    sent += 1
            elif ntype == "daily_signals":
                if notifier.notify_daily_signals(data):
                    sent += 1
            else:
                logger.warning(f"不明な通知タイプをスキップ: {ntype}")
        except Exception as e:
            logger.error(f"通知送信エラー (type={ntype}): {e}")

    logger.info(f"LINE通知送信完了: {sent}/{len(notifications)}件")
    _clear_queue(queue_path)
    logger.info("翌朝通知パイプライン完了")


def _clear_queue(queue_path: str) -> None:
    try:
        os.remove(queue_path)
        logger.info(f"通知キューをクリア: {queue_path}")
    except OSError as e:
        logger.warning(f"通知キューの削除に失敗: {e}")


if __name__ == "__main__":
    run_notify()
