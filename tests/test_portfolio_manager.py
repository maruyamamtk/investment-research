"""
テスト: portfolio_manager.py
"""
import os
import sys
import tempfile

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.portfolio.portfolio_manager import PortfolioManager, Holding


# ================================================================
# Holding
# ================================================================

class TestHolding:
    def test_acquisition_value(self):
        h = Holding(ticker="7203.T", shares=100, acquisition_price=2500.0)
        assert h.acquisition_value == 250000.0

    def test_current_value_none_when_no_price(self):
        h = Holding(ticker="7203.T", shares=100, acquisition_price=2500.0)
        assert h.current_value is None

    def test_current_value_with_price(self):
        h = Holding(ticker="7203.T", shares=100, acquisition_price=2500.0, current_price=3000.0)
        assert h.current_value == 300000.0

    def test_unrealized_pnl_profit(self):
        h = Holding(ticker="7203.T", shares=100, acquisition_price=2500.0, current_price=3000.0)
        assert h.unrealized_pnl == 50000.0

    def test_unrealized_pnl_loss(self):
        h = Holding(ticker="7203.T", shares=100, acquisition_price=3000.0, current_price=2500.0)
        assert h.unrealized_pnl == -50000.0

    def test_unrealized_pnl_none_without_price(self):
        h = Holding(ticker="7203.T", shares=100, acquisition_price=2500.0)
        assert h.unrealized_pnl is None

    def test_unrealized_pnl_pct(self):
        h = Holding(ticker="7203.T", shares=100, acquisition_price=2000.0, current_price=2500.0)
        assert abs(h.unrealized_pnl_pct - 0.25) < 1e-9

    def test_unrealized_pnl_pct_none_without_price(self):
        h = Holding(ticker="7203.T", shares=100, acquisition_price=2000.0)
        assert h.unrealized_pnl_pct is None


# ================================================================
# PortfolioManager
# ================================================================

def _make_portfolio_yaml(holdings: list, settings: dict = None) -> str:
    """一時ファイルにポートフォリオYAMLを書き込みパスを返す。"""
    data = {
        "holdings": holdings,
        "settings": settings or {
            "tax_rate": 0.20315,
            "brokerage_rate": 0.001,
            "brokerage_min_fee": 100,
            "max_single_weight": 0.30,
            "min_single_weight": 0.03,
            "rebalance_threshold": 0.10,
        },
    }
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    yaml.dump(data, f, allow_unicode=True)
    f.close()
    return f.name


class TestPortfolioManagerLoad:
    def test_empty_holdings(self):
        path = _make_portfolio_yaml([])
        pm = PortfolioManager(portfolio_path=path)
        assert pm.is_empty()
        assert pm.holdings == []
        os.unlink(path)

    def test_single_holding_loaded(self):
        path = _make_portfolio_yaml([
            {"ticker": "7203.T", "shares": 100, "acquisition_price": 2500.0, "name": "トヨタ"}
        ])
        pm = PortfolioManager(portfolio_path=path)
        assert len(pm.holdings) == 1
        h = pm.holdings[0]
        assert h.ticker == "7203.T"
        assert h.shares == 100
        assert h.acquisition_price == 2500.0
        assert h.name == "トヨタ"
        os.unlink(path)

    def test_multiple_holdings(self):
        path = _make_portfolio_yaml([
            {"ticker": "7203.T", "shares": 100, "acquisition_price": 2500.0},
            {"ticker": "6758.T", "shares": 50, "acquisition_price": 10000.0},
        ])
        pm = PortfolioManager(portfolio_path=path)
        assert len(pm.holdings) == 2
        os.unlink(path)

    def test_missing_file_returns_empty(self):
        pm = PortfolioManager(portfolio_path="/tmp/nonexistent_portfolio.yaml")
        assert pm.is_empty()

    def test_skips_invalid_entry(self):
        path = _make_portfolio_yaml([
            {"shares": 100, "acquisition_price": 2500.0},  # tickerなし
            {"ticker": "6758.T", "shares": 50, "acquisition_price": 10000.0},
        ])
        pm = PortfolioManager(portfolio_path=path)
        assert len(pm.holdings) == 1
        assert pm.holdings[0].ticker == "6758.T"
        os.unlink(path)


class TestPortfolioManagerCalculations:
    def setup_method(self):
        path = _make_portfolio_yaml([
            {"ticker": "7203.T", "shares": 100, "acquisition_price": 2500.0},
            {"ticker": "6758.T", "shares": 50, "acquisition_price": 10000.0},
        ])
        self.pm = PortfolioManager(portfolio_path=path)
        self.path = path
        # 現在価格を手動設定
        self.pm.holdings[0].current_price = 3000.0
        self.pm.holdings[1].current_price = 12000.0

    def teardown_method(self):
        os.unlink(self.path)

    def test_total_acquisition_value(self):
        assert self.pm.total_acquisition_value == 100 * 2500 + 50 * 10000

    def test_total_current_value(self):
        expected = 100 * 3000 + 50 * 12000
        assert self.pm.total_current_value == expected

    def test_total_unrealized_pnl(self):
        expected = (100 * 3000 + 50 * 12000) - (100 * 2500 + 50 * 10000)
        assert self.pm.total_unrealized_pnl == expected

    def test_get_weights(self):
        total = 100 * 3000 + 50 * 12000
        weights = self.pm.get_weights()
        assert abs(weights["7203.T"] - (100 * 3000) / total) < 1e-9
        assert abs(weights["6758.T"] - (50 * 12000) / total) < 1e-9
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_to_dict_list_has_required_keys(self):
        records = self.pm.to_dict_list()
        assert len(records) == 2
        required = {"ticker", "shares", "acquisition_price", "current_price", "unrealized_pnl", "weight"}
        for r in records:
            assert required.issubset(r.keys())
