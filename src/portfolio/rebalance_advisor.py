"""
リバランス提案モジュール

週次スクリーニング結果とポートフォリオを照合し、
税金・手数料を考慮したリバランス推奨（増減・入替）を提案する。

リバランス判断ロジック:
  1. 保有銘柄がウォッチリストに残留している → 継続保有
  2. 保有銘柄がウォッチリストから脱落した → 売却候補
  3. ウォッチリスト上位銘柄が未保有 → 購入候補
  4. 1銘柄ウェイトが上限超過 / 下限未満 → ウェイト調整
"""
from dataclasses import dataclass, field
from typing import Optional

from src.utils.logger import get_logger
from .portfolio_manager import PortfolioManager, Holding

logger = get_logger("rebalance_advisor")

_DEFAULT_TAX_RATE = 0.20315
_DEFAULT_BROKERAGE_RATE = 0.001
_DEFAULT_MIN_FEE = 100
_DEFAULT_MAX_WEIGHT = 0.30
_DEFAULT_MIN_WEIGHT = 0.03
_DEFAULT_THRESHOLD = 0.10


@dataclass
class RebalanceSuggestion:
    ticker: str
    name: str
    action: str          # "BUY" | "SELL" | "INCREASE" | "REDUCE" | "HOLD"
    reason: str
    current_weight: Optional[float] = None
    target_weight: Optional[float] = None
    current_price: Optional[float] = None
    current_shares: int = 0
    suggested_shares_delta: int = 0  # 正=購入株数, 負=売却株数
    estimated_trade_value: float = 0.0
    estimated_tax: float = 0.0
    estimated_fee: float = 0.0
    estimated_net_cost: float = 0.0  # 税金+手数料の合計コスト
    watchlist_rank: Optional[int] = None
    score: Optional[float] = None

    @property
    def action_label(self) -> str:
        labels = {
            "BUY": "🟢 新規購入",
            "SELL": "🔴 売却",
            "INCREASE": "🟡 増株",
            "REDUCE": "🟡 減株",
            "HOLD": "⚪ 継続保有",
        }
        return labels.get(self.action, self.action)


class RebalanceAdvisor:
    """
    週次スクリーニング結果とポートフォリオを照合し、リバランス提案を生成する。

    portfolio_manager: PortfolioManager（保有銘柄・設定を保持）
    watchlist_df: 週次スクリーニング結果 DataFrame（ticker, total_score_100, name 列を含む）
    """

    def __init__(self, portfolio_manager: PortfolioManager, watchlist_df=None):
        self.pm = portfolio_manager
        self.watchlist_df = watchlist_df
        self._settings = portfolio_manager.settings

        self.tax_rate = self._settings.get("tax_rate", _DEFAULT_TAX_RATE)
        self.brokerage_rate = self._settings.get("brokerage_rate", _DEFAULT_BROKERAGE_RATE)
        self.brokerage_min_fee = self._settings.get("brokerage_min_fee", _DEFAULT_MIN_FEE)
        self.max_weight = self._settings.get("max_single_weight", _DEFAULT_MAX_WEIGHT)
        self.min_weight = self._settings.get("min_single_weight", _DEFAULT_MIN_WEIGHT)
        self.threshold = self._settings.get("rebalance_threshold", _DEFAULT_THRESHOLD)

    def _calc_fee(self, trade_value: float) -> float:
        fee = max(trade_value * self.brokerage_rate, self.brokerage_min_fee)
        return round(fee, 0)

    def _calc_tax(self, holding: Holding, sell_shares: int) -> float:
        """譲渡益税を計算する（含み益がある場合のみ）。"""
        if holding.current_price is None:
            return 0.0
        gain_per_share = holding.current_price - holding.acquisition_price
        if gain_per_share <= 0:
            return 0.0
        taxable_gain = gain_per_share * sell_shares
        return round(taxable_gain * self.tax_rate, 0)

    def _watchlist_rank(self, ticker: str) -> Optional[int]:
        if self.watchlist_df is None or self.watchlist_df.empty:
            return None
        df = self.watchlist_df.reset_index(drop=True)
        positions = df.index[df["ticker"] == ticker].tolist()
        if not positions:
            return None
        return int(positions[0]) + 1

    def _watchlist_score(self, ticker: str) -> Optional[float]:
        if self.watchlist_df is None or self.watchlist_df.empty:
            return None
        matches = self.watchlist_df[self.watchlist_df["ticker"] == ticker]
        if matches.empty:
            return None
        score = matches.iloc[0].get("total_score_100")
        try:
            return float(score) if score is not None else None
        except (TypeError, ValueError):
            return None

    def generate(self, top_n_new: int = 5) -> list[RebalanceSuggestion]:
        """
        リバランス提案リストを生成する。

        top_n_new: ウォッチリスト上位からの新規購入候補を最大何件提案するか
        """
        suggestions: list[RebalanceSuggestion] = []
        cv = self.pm.total_current_value
        total_value = cv if cv is not None else self.pm.total_acquisition_value
        weights = self.pm.get_weights()
        holding_tickers = {h.ticker for h in self.pm.holdings}

        # ---- 1. 既存保有銘柄の評価 ----
        for h in self.pm.holdings:
            rank = self._watchlist_rank(h.ticker)
            score = self._watchlist_score(h.ticker)
            current_w = weights.get(h.ticker, 0)
            current_price = h.current_price or h.acquisition_price

            # ウォッチリストから脱落
            if rank is None and self.watchlist_df is not None and not self.watchlist_df.empty:
                sell_shares = h.shares
                trade_val = sell_shares * current_price
                tax = self._calc_tax(h, sell_shares)
                fee = self._calc_fee(trade_val)
                suggestions.append(RebalanceSuggestion(
                    ticker=h.ticker,
                    name=h.name or h.ticker,
                    action="SELL",
                    reason="週次スクリーニングのウォッチリストから脱落",
                    current_weight=current_w,
                    target_weight=0.0,
                    current_price=current_price,
                    current_shares=h.shares,
                    suggested_shares_delta=-sell_shares,
                    estimated_trade_value=trade_val,
                    estimated_tax=tax,
                    estimated_fee=fee,
                    estimated_net_cost=tax + fee,
                    watchlist_rank=None,
                    score=None,
                ))
                continue

            # ウェイト上限超過 → 一部売却
            if current_w > self.max_weight + self.threshold:
                target_w = self.max_weight
                target_value = total_value * target_w
                current_value = h.current_value or (h.shares * current_price)
                excess_value = current_value - target_value
                sell_shares = max(1, int(excess_value / current_price))
                trade_val = sell_shares * current_price
                tax = self._calc_tax(h, sell_shares)
                fee = self._calc_fee(trade_val)
                suggestions.append(RebalanceSuggestion(
                    ticker=h.ticker,
                    name=h.name or h.ticker,
                    action="REDUCE",
                    reason=f"ウェイト上限超過（現在 {current_w:.1%} > 上限 {self.max_weight:.1%}）",
                    current_weight=current_w,
                    target_weight=target_w,
                    current_price=current_price,
                    current_shares=h.shares,
                    suggested_shares_delta=-sell_shares,
                    estimated_trade_value=trade_val,
                    estimated_tax=tax,
                    estimated_fee=fee,
                    estimated_net_cost=tax + fee,
                    watchlist_rank=rank,
                    score=score,
                ))
                continue

            # ウェイト下限未満かつスコアが高い → 増株
            if current_w < self.min_weight - self.threshold and rank is not None and rank <= 10:
                target_w = self.min_weight
                target_value = (total_value or 0) * target_w
                current_val = h.current_value or (h.shares * current_price)
                shortage = target_value - current_val
                if shortage <= 0:
                    # 評価額が既に目標を超えているため HOLD にフォールスルー
                    suggestions.append(RebalanceSuggestion(
                        ticker=h.ticker,
                        name=h.name or h.ticker,
                        action="HOLD",
                        reason=f"条件維持（ウォッチリスト {rank}位、スコア {score:.1f}）" if rank is not None and score is not None else "継続保有",
                        current_weight=current_w,
                        target_weight=current_w,
                        current_price=current_price,
                        current_shares=h.shares,
                        watchlist_rank=rank,
                        score=score,
                    ))
                    continue
                add_shares = max(1, int(shortage / current_price))
                trade_val = add_shares * current_price
                fee = self._calc_fee(trade_val)
                suggestions.append(RebalanceSuggestion(
                    ticker=h.ticker,
                    name=h.name or h.ticker,
                    action="INCREASE",
                    reason=f"ウェイト下限未満かつウォッチリスト上位（現在 {current_w:.1%} < 下限 {self.min_weight:.1%}、順位 {rank}位）",
                    current_weight=current_w,
                    target_weight=target_w,
                    current_price=current_price,
                    current_shares=h.shares,
                    suggested_shares_delta=add_shares,
                    estimated_trade_value=trade_val,
                    estimated_tax=0.0,
                    estimated_fee=fee,
                    estimated_net_cost=fee,
                    watchlist_rank=rank,
                    score=score,
                ))
                continue

            # 継続保有
            suggestions.append(RebalanceSuggestion(
                ticker=h.ticker,
                name=h.name or h.ticker,
                action="HOLD",
                reason=f"条件維持（ウォッチリスト {rank}位、スコア {score:.1f}）" if rank is not None and score is not None else "継続保有",
                current_weight=current_w,
                target_weight=current_w,
                current_price=current_price,
                current_shares=h.shares,
                watchlist_rank=rank,
                score=score,
            ))

        # ---- 2. 新規購入候補（ウォッチリスト上位・未保有） ----
        if self.watchlist_df is not None and not self.watchlist_df.empty:
            new_candidates = self.watchlist_df[
                ~self.watchlist_df["ticker"].isin(holding_tickers)
            ].head(top_n_new)

            for _, row in new_candidates.iterrows():
                ticker = row.get("ticker", "")
                name = row.get("name", ticker)
                score = self._watchlist_score(ticker)
                actual_rank = self._watchlist_rank(ticker)
                current_price = row.get("close") or row.get("current_price")

                try:
                    current_price = float(current_price) if current_price else None
                except (TypeError, ValueError):
                    current_price = None

                # 購入株数試算（ポートフォリオ全体の min_weight 相当）
                target_w = self.min_weight
                buy_value = (total_value * target_w) if total_value else 0
                buy_shares = int(buy_value / current_price) if current_price and current_price > 0 else 0
                trade_val = buy_shares * current_price if current_price else 0
                fee = self._calc_fee(trade_val) if trade_val > 0 else 0.0

                rank_str = f"{actual_rank}位" if actual_rank is not None else "圏外"
                suggestions.append(RebalanceSuggestion(
                    ticker=ticker,
                    name=name,
                    action="BUY",
                    reason=f"ウォッチリスト {rank_str}（未保有）、スコア {score:.1f}" if score is not None else f"ウォッチリスト {rank_str}（未保有）",
                    current_weight=0.0,
                    target_weight=target_w,
                    current_price=current_price,
                    current_shares=0,
                    suggested_shares_delta=buy_shares,
                    estimated_trade_value=trade_val,
                    estimated_tax=0.0,
                    estimated_fee=fee,
                    estimated_net_cost=fee,
                    watchlist_rank=actual_rank,
                    score=score,
                ))

        return suggestions

    def estimate_total_rebalance_cost(self, suggestions: list[RebalanceSuggestion]) -> dict:
        """リバランス全体の試算コスト（税金・手数料合計）を返す。"""
        sell = [s for s in suggestions if s.action in ("SELL", "REDUCE")]
        buy = [s for s in suggestions if s.action in ("BUY", "INCREASE")]

        total_sell_value = sum(s.estimated_trade_value for s in sell)
        total_buy_value = sum(s.estimated_trade_value for s in buy)
        total_tax = sum(s.estimated_tax for s in sell)
        total_fee = sum(s.estimated_fee for s in suggestions if s.action != "HOLD")
        total_cost = total_tax + total_fee

        return {
            "sell_count": len(sell),
            "buy_count": len(buy),
            "total_sell_value": total_sell_value,
            "total_buy_value": total_buy_value,
            "total_tax": total_tax,
            "total_fee": total_fee,
            "total_cost": total_cost,
        }

    def build_report(self, suggestions: list[RebalanceSuggestion]) -> str:
        """Markdown形式のリバランスレポートを生成する。"""
        from datetime import datetime
        now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        total = self.pm.total_current_value
        total_acq = self.pm.total_acquisition_value
        pnl = (total or 0) - total_acq
        pnl_pct = pnl / total_acq if total_acq else 0

        cost = self.estimate_total_rebalance_cost(suggestions)

        lines = [
            "# ポートフォリオ・リバランスレポート",
            f"生成日時: {now}",
            "",
            "---",
            "",
            "## ポートフォリオ概況",
            "",
            f"| 項目 | 値 |",
            f"|------|-----|",
            f"| 保有銘柄数 | {len(self.pm.holdings)}社 |",
            f"| 取得総額 | {total_acq:,.0f}円 |",
            f"| 現在評価額 | {total:,.0f}円 |" if total else "| 現在評価額 | N/A |",
            f"| 含み損益 | {pnl:+,.0f}円（{pnl_pct:+.1%}） |" if total else "| 含み損益 | N/A |",
            "",
            "---",
            "",
            "## 保有銘柄詳細",
            "",
            "| 銘柄 | 株数 | 取得単価 | 現在値 | 評価額 | 含み損益 | ウェイト |",
            "|------|------|----------|--------|--------|----------|---------|",
        ]

        weights = self.pm.get_weights()
        for h in self.pm.holdings:
            label = f"{h.name or h.ticker}（{h.ticker}）"
            base = f"| {label} | {h.shares}株 | {h.acquisition_price:,.0f}円 "
            if h.current_price:
                lines.append(base + f"| {h.current_price:,.0f}円 |")
            else:
                lines.append(base + "| N/A |")

        lines += [
            "",
            "---",
            "",
            "## リバランス提案",
            "",
        ]

        action_order = {"SELL": 0, "REDUCE": 1, "BUY": 2, "INCREASE": 3, "HOLD": 4}
        sorted_suggestions = sorted(suggestions, key=lambda s: action_order.get(s.action, 5))

        for s in sorted_suggestions:
            lines += [
                f"### {s.action_label}: {s.name}（{s.ticker}）",
                "",
                f"- **理由**: {s.reason}",
            ]
            if s.current_weight is not None:
                lines.append(f"- **現在ウェイト**: {s.current_weight:.1%}")
            if s.target_weight is not None and s.action != "HOLD":
                lines.append(f"- **目標ウェイト**: {s.target_weight:.1%}")
            if s.current_price:
                lines.append(f"- **現在値**: {s.current_price:,.0f}円")
            if s.action != "HOLD":
                delta_sign = "+" if s.suggested_shares_delta > 0 else ""
                lines.append(f"- **売買株数**: {delta_sign}{s.suggested_shares_delta}株")
                lines.append(f"- **取引金額（概算）**: {s.estimated_trade_value:,.0f}円")
                lines.append(f"- **譲渡益税（概算）**: {s.estimated_tax:,.0f}円")
                lines.append(f"- **手数料（概算）**: {s.estimated_fee:,.0f}円")
                lines.append(f"- **取引コスト合計**: {s.estimated_net_cost:,.0f}円")
            if s.watchlist_rank:
                lines.append(f"- **ウォッチリスト順位**: {s.watchlist_rank}位")
            if s.score is not None:
                lines.append(f"- **スコア**: {s.score:.1f}/100")
            lines.append("")

        lines += [
            "---",
            "",
            "## リバランスコスト試算",
            "",
            f"| 項目 | 値 |",
            f"|------|-----|",
            f"| 売却銘柄数 | {cost['sell_count']}銘柄 |",
            f"| 購入銘柄数 | {cost['buy_count']}銘柄 |",
            f"| 売却総額（概算） | {cost['total_sell_value']:,.0f}円 |",
            f"| 購入総額（概算） | {cost['total_buy_value']:,.0f}円 |",
            f"| 譲渡益税合計 | {cost['total_tax']:,.0f}円 |",
            f"| 手数料合計 | {cost['total_fee']:,.0f}円 |",
            f"| **総コスト** | **{cost['total_cost']:,.0f}円** |",
            "",
            "---",
            "",
            "## 免責事項",
            "",
            "> このレポートは自動生成された情報提供を目的としたものであり、投資助言ではありません。",
            "> 税金・手数料の試算は概算であり、実際の取引では異なる場合があります。",
            "> 投資判断はご自身の責任で行ってください。",
        ]

        return "\n".join(lines)
