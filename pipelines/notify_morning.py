"""
翌朝通知パイプライン: 平日 9:00 JST（UTC 0:00）実行
Cache（ローカルまたは GCS）から通知キューを読み込み LINE 送信 → キュークリア
"""
import os
import sys
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notification.line_notifier import from_config as line_from_config
from src.utils.cache import Cache
from src.utils.credentials import override_credentials
from src.utils.logger import get_logger

logger = get_logger("notify_morning")

# 通知キューは daily-job と notify-job 間で GCS を経由して受け渡す
# TTL は 26h（平日 19:30 → 翌朝 9:00 = 約 13.5h、余裕を持たせる）
_QUEUE_TTL_HOURS = 26


def load_config(path: str = "config/settings.yaml") -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
    override_credentials(cfg)
    return cfg


def run_notify():
    logger.info("=" * 60)
    logger.info(f"翌朝通知パイプライン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    cfg = load_config()
    cache = Cache(cache_dir="cache")
    notifications = cache.get("notification_queue", ttl_hours=_QUEUE_TTL_HOURS)

    if not notifications:
        logger.info("通知キューが存在しないか期限切れです。送信する通知はありません。")
        return

    logger.info(f"キュー取得: {len(notifications)}件")

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
    cache.invalidate("notification_queue")
    logger.info("通知キューをクリアしました。翌朝通知パイプライン完了")


if __name__ == "__main__":
    run_notify()
