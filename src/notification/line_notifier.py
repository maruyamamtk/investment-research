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

        lines.append("\n詳細は watch_list.md を確認してください。")

        return self._send([self._text("\n".join(lines))])

    # ---- 購入候補リスト追加通知 ----

    def notify_buy_candidate_added(self, signal: dict) -> bool:
        """BUYシグナル発生・購入候補リストへの追加をLINEで通知する"""
        name = signal.get("name", signal["ticker"])
        ticker = signal["ticker"]
        msg = (
            f"🟢 購入候補リストに追加（{_today()}）\n\n"
            f"{name}（{ticker}）\n"
            f"シグナル強度: {signal.get('strength')}/10\n"
            f"現在値: {signal.get('close')}円\n"
            f"理由: {signal.get('reasons', '')[:80]}\n\n"
            f"詳細は buy_candidates.md を確認してください。"
        )
        return self._send([self._text(msg)])

    # ---- 購入候補リスト除外通知 ----

    def notify_sell_candidate_removed(self, signal: dict, reason: str = "テクニカルSELL") -> bool:
        """SELLシグナルまたは条件劣化・購入候補リストからの除外をLINEで通知する"""
        name = signal.get("name", signal["ticker"])
        ticker = signal["ticker"]
        msg = (
            f"🔴 購入候補リストから除外（{_today()}）\n\n"
            f"{name}（{ticker}）\n"
            f"除外理由: {reason}\n"
            f"現在値: {signal.get('close')}円\n"
            f"シグナル: {signal.get('reasons', '')[:80]}\n\n"
            f"詳細は buy_candidates.md を確認してください。"
        )
        return self._send([self._text(msg)])

    # ---- 決算レビュー通知 ----

    def notify_earnings_review(self, summaries: list[dict]) -> bool:
        """決算Beat/Miss結果をLINEで通知する"""
        if not summaries:
            return False

        lines = [f"📣 決算レビュー速報（{_today()}）\n"]

        beat = [s for s in summaries if s.get("verdict") == "Beat"]
        miss = [s for s in summaries if s.get("verdict") == "Miss"]
        meet = [s for s in summaries if s.get("verdict") == "Meet"]
        na = [s for s in summaries if s.get("verdict") == "N/A"]

        if beat:
            lines.append("🟢 Beat（予想超過）")
            for s in beat:
                sp = s.get("surprise_pct")
                sp_str = f" (+{sp:.1f}%)" if sp is not None else ""
                lines.append(f"  {s.get('name', s['ticker'])}（{s['ticker']}）{sp_str}")

        if miss:
            lines.append("\n🔴 Miss（予想未達）")
            for s in miss:
                sp = s.get("surprise_pct")
                sp_str = f" ({sp:.1f}%)" if sp is not None else ""
                lines.append(f"  {s.get('name', s['ticker'])}（{s['ticker']}）{sp_str}")

        if meet:
            lines.append("\n🟡 Meet（予想並み）")
            for s in meet:
                lines.append(f"  {s.get('name', s['ticker'])}（{s['ticker']}）")

        if na:
            lines.append("\n⚪ データ未取得")
            for s in na:
                lines.append(f"  {s.get('name', s['ticker'])}（{s['ticker']}）")

        lines.append("\n詳細は earnings_review_*.md を確認してください。")

        return self._send([self._text("\n".join(lines))])

    # ---- リバランス提案通知 ----

    def notify_rebalance_suggestion(
        self,
        suggestions: list,
        portfolio_summary: dict = None,
        cost_summary: dict = None,
    ) -> bool:
        """ポートフォリオのリバランス提案をLINEで通知する"""
        if not suggestions:
            return False

        summary = portfolio_summary or {}
        cost = cost_summary or {}

        total_val = summary.get("total_current_value")
        total_pnl = summary.get("total_unrealized_pnl")

        lines = [f"📊 ポートフォリオ リバランス提案（{_today()}）\n"]

        if total_val is not None:
            pnl_str = f"（含み損益: {total_pnl:+,.0f}円）" if total_pnl is not None else ""
            lines.append(f"評価額: {total_val:,.0f}円 {pnl_str}\n")

        sell = [s for s in suggestions if s.action in ("SELL", "REDUCE")]
        buy = [s for s in suggestions if s.action in ("BUY", "INCREASE")]

        if sell:
            lines.append("🔴 売却・減株")
            for s in sell[:3]:
                lines.append(f"  {s.name}（{s.ticker}）: {s.reason[:40]}")

        if buy:
            lines.append("\n🟢 購入・増株")
            for s in buy[:3]:
                lines.append(f"  {s.name}（{s.ticker}）: {s.reason[:40]}")

        total_cost = cost.get("total_cost", 0)
        if total_cost > 0:
            lines.append(f"\n💰 リバランスコスト概算: {total_cost:,.0f}円")
            lines.append(f"  （税金: {cost.get('total_tax', 0):,.0f}円 + 手数料: {cost.get('total_fee', 0):,.0f}円）")

        lines.append("\n詳細は portfolio_report.md を確認してください。")

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
