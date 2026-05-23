"""
テスト: rebalance_advisor.py
"""
import os
import sys
import tempfile

import pandas as pd
import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.portfolio.portfolio_manager import PortfolioManager, Holding
from src.portfolio.rebalance_advisor import RebalanceAdvisor, RebalanceSuggestion


def _make_portfolio(holdings_data: list, settings: dict = None) -> PortfolioManager:
    """テスト用PortfolioManagerを作成する。"""
    data = {
        "holdings": holdings_data,
        "settings": settings or {
            "tax_rate": 0.20315,
            "brokerage_rate": 0.001,
            "brokerage_min_fee": 100,
            "max_single_weight": 0.30,
            "min_single_weight": 0.03,
            "rebalance_threshold": 0.05,
        },
    }
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    yaml.dump(data, f, allow_unicode=True)
    f.close()
    pm = PortfolioManager(portfolio_path=f.name)
    os.unlink(f.name)
    return pm


def _make_watchlist(tickers_scores: list[tuple]) -> pd.DataFrame:
    """テスト用ウォッチリストDataFrameを作成する。"""
    rows = []
    for ticker, score in tickers_scores:
        rows.append({"ticker": ticker, "total_score_100": score, "name": ticker, "close": 1000.0})
    return pd.DataFrame(rows)


# ================================================================
# RebalanceSuggestion
# ================================================================

class TestRebalanceSuggestionLabels:
    def test_action_labels(self):
        for action, label in [
            ("BUY", "🟢 新規購入"),
            ("SELL", "🔴 売却"),
            ("INCREASE", "🟡 増株"),
            ("REDUCE", "🟡 減株"),
            ("HOLD", "⚪ 継続保有"),
        ]:
            s = RebalanceSuggestion(ticker="X", name="X", action=action, reason="")
            assert s.action_label == label


# ================================================================
# RebalanceAdvisor.generate
# ================================================================

class TestRebalanceAdvisorHold:
    def test_hold_when_in_watchlist(self):
        # 2銘柄保有でウェイトが均等（約50%ずつ）→ 上限30%超過のため単一銘柄では REDUCE になる
        # 上限を1.0に設定して HOLD を確認する
        pm = _make_portfolio(
            [
                {"ticker": "7203.T", "shares": 100, "acquisition_price": 2500.0},
                {"ticker": "6758.T", "shares": 10, "acquisition_price": 2500.0},
            ],
            settings={
                "tax_rate": 0.20315,
                "brokerage_rate": 0.001,
                "brokerage_min_fee": 100,
                "max_single_weight": 1.0,   # 上限なし（HOLDを確認するため）
                "min_single_weight": 0.01,
                "rebalance_threshold": 0.05,
            },
        )
        pm.holdings[0].current_price = 3000.0
        pm.holdings[1].current_price = 3000.0
        watchlist = _make_watchlist([("7203.T", 80.0), ("6758.T", 70.0)])

        advisor = RebalanceAdvisor(pm, watchlist)
        suggestions = advisor.generate()

        hold = [s for s in suggestions if s.ticker == "7203.T" and s.action == "HOLD"]
        assert len(hold) == 1
        assert hold[0].watchlist_rank == 1


class TestRebalanceAdvisorSell:
    def test_sell_when_dropped_from_watchlist(self):
        pm = _make_portfolio([
            {"ticker": "7203.T", "shares": 100, "acquisition_price": 2500.0}
        ])
        pm.holdings[0].current_price = 3000.0
        # 7203.T はウォッチリストにない
        watchlist = _make_watchlist([("6758.T", 70.0)])

        advisor = RebalanceAdvisor(pm, watchlist)
        suggestions = advisor.generate()

        sell = [s for s in suggestions if s.ticker == "7203.T" and s.action == "SELL"]
        assert len(sell) == 1
        assert sell[0].suggested_shares_delta == -100


class TestRebalanceAdvisorTaxCalc:
    def test_tax_on_profit(self):
        pm = _make_portfolio([
            {"ticker": "7203.T", "shares": 100, "acquisition_price": 2000.0}
        ])
        pm.holdings[0].current_price = 3000.0
        watchlist = _make_watchlist([("6758.T", 70.0)])

        advisor = RebalanceAdvisor(pm, watchlist)
        suggestions = advisor.generate()

        sell = [s for s in suggestions if s.ticker == "7203.T" and s.action == "SELL"]
        assert len(sell) == 1
        expected_tax = (3000 - 2000) * 100 * 0.20315
        assert abs(sell[0].estimated_tax - round(expected_tax, 0)) < 1

    def test_no_tax_on_loss(self):
        pm = _make_portfolio([
            {"ticker": "7203.T", "shares": 100, "acquisition_price": 4000.0}
        ])
        pm.holdings[0].current_price = 3000.0
        watchlist = _make_watchlist([("6758.T", 70.0)])

        advisor = RebalanceAdvisor(pm, watchlist)
        suggestions = advisor.generate()

        sell = [s for s in suggestions if s.ticker == "7203.T" and s.action == "SELL"]
        assert len(sell) == 1
        assert sell[0].estimated_tax == 0.0


class TestRebalanceAdvisorBuy:
    def test_buy_candidates_from_watchlist(self):
        pm = _make_portfolio([
            {"ticker": "7203.T", "shares": 100, "acquisition_price": 2500.0}
        ])
        pm.holdings[0].current_price = 3000.0
        # 6758.T は未保有
        watchlist = _make_watchlist([("7203.T", 80.0), ("6758.T", 70.0)])

        advisor = RebalanceAdvisor(pm, watchlist)
        suggestions = advisor.generate(top_n_new=3)

        buy = [s for s in suggestions if s.action == "BUY"]
        tickers = [s.ticker for s in buy]
        assert "6758.T" in tickers
        assert "7203.T" not in tickers  # 既保有なので購入提案なし

    def test_no_buy_when_watchlist_empty(self):
        pm = _make_portfolio([
            {"ticker": "7203.T", "shares": 100, "acquisition_price": 2500.0}
        ])
        pm.holdings[0].current_price = 3000.0

        advisor = RebalanceAdvisor(pm, watchlist_df=None)
        suggestions = advisor.generate()

        buy = [s for s in suggestions if s.action == "BUY"]
        assert len(buy) == 0


class TestRebalanceAdvisorReduce:
    def test_reduce_when_overweight(self):
        # 7203.T が100%ウェイト（上限30%超え）
        pm = _make_portfolio([
            {"ticker": "7203.T", "shares": 100, "acquisition_price": 2500.0}
        ], settings={
            "tax_rate": 0.20315,
            "brokerage_rate": 0.001,
            "brokerage_min_fee": 100,
            "max_single_weight": 0.30,
            "min_single_weight": 0.03,
            "rebalance_threshold": 0.05,
        })
        pm.holdings[0].current_price = 3000.0
        watchlist = _make_watchlist([("7203.T", 80.0)])

        advisor = RebalanceAdvisor(pm, watchlist)
        suggestions = advisor.generate()

        # 1銘柄のみなので100%ウェイト = 上限(30%)超え
        reduce = [s for s in suggestions if s.action == "REDUCE"]
        assert len(reduce) == 1
        assert reduce[0].suggested_shares_delta < 0


# ================================================================
# estimate_total_rebalance_cost
# ================================================================

class TestEstimateTotalRebalanceCost:
    def test_cost_aggregation(self):
        suggestions = [
            RebalanceSuggestion(
                ticker="A", name="A", action="SELL", reason="",
                estimated_tax=5000.0, estimated_fee=500.0, estimated_net_cost=5500.0,
                estimated_trade_value=100000.0,
            ),
            RebalanceSuggestion(
                ticker="B", name="B", action="BUY", reason="",
                estimated_tax=0.0, estimated_fee=200.0, estimated_net_cost=200.0,
                estimated_trade_value=50000.0,
            ),
            RebalanceSuggestion(
                ticker="C", name="C", action="HOLD", reason="",
            ),
        ]
        pm = _make_portfolio([])
        advisor = RebalanceAdvisor(pm, watchlist_df=None)
        cost = advisor.estimate_total_rebalance_cost(suggestions)

        assert cost["sell_count"] == 1
        assert cost["buy_count"] == 1
        assert cost["total_tax"] == 5000.0
        assert cost["total_fee"] == 700.0
        assert cost["total_cost"] == 5700.0


# ================================================================
# build_report
# ================================================================

class TestBuildReport:
    def test_report_contains_key_sections(self):
        pm = _make_portfolio([
            {"ticker": "7203.T", "shares": 100, "acquisition_price": 2500.0, "name": "トヨタ"}
        ])
        pm.holdings[0].current_price = 3000.0

        watchlist = _make_watchlist([("7203.T", 80.0), ("6758.T", 70.0)])
        advisor = RebalanceAdvisor(pm, watchlist)
        suggestions = advisor.generate()
        report = advisor.build_report(suggestions)

        assert "ポートフォリオ・リバランスレポート" in report
        assert "ポートフォリオ概況" in report
        assert "リバランス提案" in report
        assert "リバランスコスト試算" in report
        assert "免責事項" in report
