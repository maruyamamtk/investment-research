"""
LINE Messaging API 通知モジュール
Desktop/日本株分析/line_notifier.py の実装パターンを参考に移植・拡張
"""
import os
from typing import Optional

import requests

from src.utils.logger import get_logger

logger = get_logger("line_notifier")

LINE_API_URL = "https://api.line.me/v2/bot/message/push"


class LineNotifier:
    def __init__(self, channel_access_token: str, user_id: str, enabled: bool = True):
        self.token = channel_access_token
        self.user_id = user_id
        self.enabled = enabled and bool(channel_access_token) and bool(user_id)

        if not self.enabled:
            logger.info("LINE通知: 無効（トークンまたはuser_id未設定）")

    def _send(self, messages: list[dict]) -> bool:
        if not self.enabled:
            return False
        try:
            resp = requests.post(
                LINE_API_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.token}",
                },
                json={"to": self.user_id, "messages": messages},
                timeout=15,
            )
            resp.raise_for_status()
            logger.info(f"LINE通知送信成功: {len(messages)}件のメッセージ")
            return True
        except Exception as e:
            logger.error(f"LINE通知送信失敗: {e}")
            return False

    def _text(self, text: str) -> dict:
        return {"type": "text", "text": text}

    # ---- 日次シグナル通知 ----

    def notify_daily_signals(self, signals: list[dict]) -> bool:
        """日次売買シグナルをLINEで通知する"""
        buy = [s for s in signals if s.get("signal") == "BUY"]
        sell = [s for s in signals if s.get("signal") == "SELL"]
        hold = [s for s in signals if s.get("signal") == "HOLD"]

        if not buy and not sell:
            logger.info("LINE通知: BUY/SELLシグナルなし。通知をスキップします。")
            return False

        lines = [f"📊 本日の売買シグナル（{_today()}）\n"]

        if buy:
            lines.append("🟢 BUY シグナル")
            for s in buy:
                lines.append(
                    f"  {s.get('name', s['ticker'])}（{s['ticker']}）\n"
                    f"  強度: {s.get('strength')}/10 | 現在値: {s.get('close')}円\n"
                    f"  {s.get('reasons', '')[:60]}..."
                )
        if sell:
            lines.append("\n🔴 SELL シグナル")
            for s in sell:
                lines.append(
                    f"  {s.get('name', s['ticker'])}（{s['ticker']}）\n"
                    f"  強度: {s.get('strength')}/10 | 現在値: {s.get('close')}円\n"
                    f"  {s.get('reasons', '')[:60]}..."
                )
        if hold:
            names = "、".join(s.get("name", s["ticker"]) for s in hold)
            lines.append(f"\n🟡 HOLD（決算前後）: {names}")

        lines.append("\n詳細は daily_trade_signals.md を確認してください。")

        return self._send([self._text("\n".join(lines))])

    # ---- 週次ウォッチリスト変更通知 ----

    def notify_watchlist_update(
        self,
        new_watchlist: list[str],
        prev_watchlist: list[str],
        ticker_names: dict[str, str] = None,
    ) -> bool:
        """週次ウォッチリストの変更をLINEで通知する（Desktop/日本株分析のパターン踏襲）"""
        names = ticker_names or {}
        new_set = set(new_watchlist)
        prev_set = set(prev_watchlist)

        added = new_set - prev_set
        removed = prev_set - new_set

        lines = [f"📋 ウォッチリスト更新（{_today()}）\n"]
        lines.append(f"対象銘柄数: {len(new_watchlist)}社")

        if added:
            lines.append("\n✅ 新規追加")
            for t in sorted(added):
                lines.append(f"  + {names.get(t, t)}（{t}）")

        if removed:
            lines.append("\n❌ 除外")
            for t in sorted(removed):
                lines.append(f"  - {names.get(t, t)}（{t}）")

        if not added and not removed:
            lines.append("\n（前週からの変更なし）")

        lines.append("\n詳細は weekly_moat_stocks.md を確認してください。")

        return self._send([self._text("\n".join(lines))])

    # ---- エラー通知 ----

    def notify_error(self, pipeline: str, error_msg: str) -> bool:
        """パイプラインのエラーをLINEで通知する"""
        msg = f"⚠️ {pipeline} でエラーが発生しました（{_today()}）\n\n{error_msg[:200]}"
        return self._send([self._text(msg)])


def from_config(cfg: dict) -> LineNotifier:
    """設定ファイルからLineNotifierを生成する"""
    line_cfg = cfg.get("api", {}).get("line", {})
    return LineNotifier(
        channel_access_token=line_cfg.get("channel_access_token", ""),
        user_id=line_cfg.get("user_id", ""),
        enabled=line_cfg.get("enabled", False),
    )


def _today() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y年%m月%d日")
