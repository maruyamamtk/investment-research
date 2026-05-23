"""
テスト: dcf_calculator.py
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.screener.dcf_calculator import (
    estimate_wacc,
    estimate_fcf_growth,
    project_fcf,
    calculate_terminal_value,
    calculate_enterprise_value,
    calculate_fair_value_per_share,
    sensitivity_matrix,
    generate_dcf_report,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_MARKET_PREMIUM,
    DEFAULT_TERMINAL_GROWTH,
    FCF_GROWTH_CAP,
)


# ================================================================
# estimate_wacc
# ================================================================

class TestEstimateWacc:
    def _make_dcf_data(self, beta=1.0, market_cap=1e12, total_debt=5e11):
        return {"beta": beta, "market_cap": market_cap, "total_debt": total_debt}

    def test_beta_one_no_debt_equals_ke(self):
        data = self._make_dcf_data(beta=1.0, market_cap=1e12, total_debt=0)
        ke = DEFAULT_RISK_FREE_RATE + 1.0 * DEFAULT_MARKET_PREMIUM
        assert abs(estimate_wacc(data) - ke) < 1e-9

    def test_debt_lowers_wacc_due_to_tax_shield(self):
        """負債のタックスシールドにより、純負債時のWACCが純株式時より低くなることを確認。"""
        all_equity = self._make_dcf_data(total_debt=0)
        with_debt = self._make_dcf_data(total_debt=5e11)
        assert estimate_wacc(with_debt) < estimate_wacc(all_equity)

    def test_high_beta_raises_wacc(self):
        low = self._make_dcf_data(beta=0.5)
        high = self._make_dcf_data(beta=2.0)
        assert estimate_wacc(high) > estimate_wacc(low)

    def test_none_beta_falls_back_to_one(self):
        data = {"beta": None, "market_cap": 1e12, "total_debt": 0}
        ke = DEFAULT_RISK_FREE_RATE + 1.0 * DEFAULT_MARKET_PREMIUM
        assert abs(estimate_wacc(data) - ke) < 1e-9

    def test_zero_capital_returns_cost_of_equity(self):
        data = {"beta": 1.2, "market_cap": 0, "total_debt": 0}
        ke = DEFAULT_RISK_FREE_RATE + 1.2 * DEFAULT_MARKET_PREMIUM
        assert abs(estimate_wacc(data) - ke) < 1e-9

    def test_result_is_at_least_floor(self):
        data = {"beta": 0.0, "market_cap": 1e12, "total_debt": 0}
        assert estimate_wacc(data) >= 0.01


# ================================================================
# estimate_fcf_growth
# ================================================================

class TestEstimateFcfGrowth:
    def test_two_period_growth_calculation(self):
        # FCF: 100 → 110 → 121 (3データ点 = 2期間) → CAGR = 10%
        data = {"fcf_list": [121e8, 110e8, 100e8], "revenue_growth": None}
        g = estimate_fcf_growth(data)
        assert abs(g - 0.10) < 1e-6

    def test_three_period_cagr(self):
        # FCF: 1000 → 1100 → 1210 → CAGR ≈ 10%
        data = {"fcf_list": [1210e8, 1100e8, 1000e8], "revenue_growth": None}
        g = estimate_fcf_growth(data)
        assert abs(g - 0.10) < 1e-4

    def test_negative_oldest_fcf_falls_back_to_revenue_growth(self):
        data = {"fcf_list": [100e8, -50e8], "revenue_growth": 0.08}
        g = estimate_fcf_growth(data)
        assert g == 0.08

    def test_empty_fcf_list_uses_revenue_growth(self):
        data = {"fcf_list": [], "revenue_growth": 0.12}
        assert estimate_fcf_growth(data) == 0.12

    def test_no_data_returns_default_five_percent(self):
        data = {"fcf_list": [], "revenue_growth": None}
        assert estimate_fcf_growth(data) == 0.05

    def test_growth_capped_at_upper_bound(self):
        data = {"fcf_list": [1e12, 1e8], "revenue_growth": None}
        assert estimate_fcf_growth(data) == FCF_GROWTH_CAP[1]

    def test_growth_capped_at_lower_bound(self):
        data = {"fcf_list": [1e8, 1e12], "revenue_growth": None}
        assert estimate_fcf_growth(data) == FCF_GROWTH_CAP[0]


# ================================================================
# project_fcf
# ================================================================

class TestProjectFcf:
    def test_returns_correct_number_of_periods(self):
        assert len(project_fcf(100.0, 0.10, years=5)) == 5

    def test_first_year_is_base_times_one_plus_g(self):
        result = project_fcf(100.0, 0.10)
        assert abs(result[0] - 110.0) < 1e-9

    def test_compound_growth(self):
        result = project_fcf(100.0, 0.10, years=3)
        assert abs(result[2] - 100.0 * 1.1 ** 3) < 1e-9

    def test_zero_growth_stays_flat(self):
        result = project_fcf(200.0, 0.0, years=3)
        assert all(abs(v - 200.0) < 1e-9 for v in result)


# ================================================================
# calculate_terminal_value
# ================================================================

class TestCalculateTerminalValue:
    def test_gordon_growth_formula(self):
        # TV = 100 × (1 + 0.02) / (0.10 - 0.02) = 1275
        tv = calculate_terminal_value(100.0, wacc=0.10, terminal_growth=0.02)
        assert abs(tv - 1275.0) < 1e-6

    def test_spread_clamped_when_wacc_equals_growth(self):
        """WACC == g の場合にクランプされて有限値を返すことを確認。"""
        tv = calculate_terminal_value(100.0, wacc=0.05, terminal_growth=0.05)
        assert math.isfinite(tv)

    def test_higher_wacc_gives_lower_tv(self):
        tv_low = calculate_terminal_value(100.0, wacc=0.08, terminal_growth=0.02)
        tv_high = calculate_terminal_value(100.0, wacc=0.12, terminal_growth=0.02)
        assert tv_high < tv_low


# ================================================================
# calculate_enterprise_value
# ================================================================

class TestCalculateEnterpriseValue:
    def test_single_period_calculation(self):
        # EV = 100 / 1.1 + 1000 / 1.1 = 1100 / 1.1 = 1000
        ev = calculate_enterprise_value([100.0], terminal_value=1000.0, wacc=0.10)
        assert abs(ev - (100 / 1.1 + 1000 / 1.1)) < 1e-6

    def test_longer_projection_discounts_further(self):
        fcf_short = [100.0] * 3
        fcf_long = [100.0] * 5
        tv = 1000.0
        ev_short = calculate_enterprise_value(fcf_short, tv, 0.10)
        ev_long = calculate_enterprise_value(fcf_long, tv, 0.10)
        # TVの割引がより深くなるためev_longの方が小さい
        assert ev_long < ev_short


# ================================================================
# calculate_fair_value_per_share
# ================================================================

class TestCalculateFairValuePerShare:
    def test_basic_calculation(self):
        # EV=1000, net_debt=200, shares=100 → (1000-200)/100 = 8
        fv = calculate_fair_value_per_share(1000.0, net_debt=200.0, shares_outstanding=100)
        assert abs(fv - 8.0) < 1e-9

    def test_returns_none_when_equity_negative(self):
        fv = calculate_fair_value_per_share(100.0, net_debt=500.0, shares_outstanding=100)
        assert fv is None

    def test_returns_none_when_shares_zero(self):
        fv = calculate_fair_value_per_share(1000.0, net_debt=0.0, shares_outstanding=0)
        assert fv is None

    def test_returns_none_when_shares_none(self):
        fv = calculate_fair_value_per_share(1000.0, net_debt=0.0, shares_outstanding=None)
        assert fv is None


# ================================================================
# sensitivity_matrix
# ================================================================

class TestSensitivityMatrix:
    def _run(self):
        return sensitivity_matrix(
            base_fcf=100e8,
            base_wacc=0.08,
            base_growth=0.05,
            terminal_growth=0.02,
            net_debt=50e8,
            shares_outstanding=1_000_000,
        )

    def test_matrix_shape_3x3(self):
        sens = self._run()
        assert len(sens["matrix"]) == 3
        assert all(len(row) == 3 for row in sens["matrix"])

    def test_wacc_labels_count(self):
        sens = self._run()
        assert len(sens["wacc_labels"]) == 3

    def test_growth_labels_count(self):
        sens = self._run()
        assert len(sens["growth_labels"]) == 3

    def test_lower_wacc_higher_fair_value(self):
        """同じ成長率で WACC が低いほどフェアバリューが高い。"""
        sens = self._run()
        for row in sens["matrix"]:
            if all(v is not None for v in row):
                assert row[0] >= row[1] >= row[2], f"Expected descending: {row}"

    def test_higher_growth_higher_fair_value(self):
        """同じ WACC で成長率が高いほどフェアバリューが高い。"""
        sens = self._run()
        for col_idx in range(3):
            col = [sens["matrix"][r][col_idx] for r in range(3)]
            if all(v is not None for v in col):
                assert col[2] >= col[1] >= col[0], f"Expected ascending: {col}"

    def test_wacc_delta_is_one_percent(self):
        sens = self._run()
        labels = sens["wacc_labels"]
        assert abs(labels[1] - labels[0] - 0.01) < 1e-9
        assert abs(labels[2] - labels[1] - 0.01) < 1e-9

    def test_growth_delta_is_two_percent(self):
        sens = self._run()
        labels = sens["growth_labels"]
        assert abs(labels[1] - labels[0] - 0.02) < 1e-9
        assert abs(labels[2] - labels[1] - 0.02) < 1e-9


# ================================================================
# generate_dcf_report（統合テスト）
# ================================================================

class FakeYFClient:
    def __init__(self, dcf_data: dict):
        self._data = dcf_data

    def get_dcf_data(self, ticker: str) -> dict:
        return self._data


class TestGenerateDcfReport:
    def _make_client(self, override=None):
        base = {
            "ticker": "1234.T",
            "name": "テスト株式会社",
            "current_price": 1000.0,
            "shares_outstanding": 10_000_000,
            "beta": 1.1,
            "market_cap": 10e9,
            "total_debt": 2e9,
            "total_cash": 1e9,
            "net_debt": 1e9,
            "fcf_list": [500e6, 450e6, 400e6],
            "latest_fcf": 500e6,
            "revenue_growth": 0.10,
            "ebitda": 1e9,
        }
        if override:
            base.update(override)
        return FakeYFClient(base)

    def test_report_contains_ticker(self):
        client = self._make_client()
        report = generate_dcf_report("1234.T", client)
        assert "1234.T" in report

    def test_report_contains_fair_value(self):
        client = self._make_client()
        report = generate_dcf_report("1234.T", client)
        assert "フェアバリュー" in report

    def test_report_contains_sensitivity_section(self):
        client = self._make_client()
        report = generate_dcf_report("1234.T", client)
        assert "感度分析マトリクス" in report

    def test_report_contains_upside_downside(self):
        client = self._make_client()
        report = generate_dcf_report("1234.T", client)
        assert "乖離率" in report

    def test_report_warns_when_fcf_none(self):
        client = self._make_client({"latest_fcf": None, "fcf_list": []})
        report = generate_dcf_report("1234.T", client)
        assert "FCFデータが取得できない" in report

    def test_report_warns_when_fcf_negative(self):
        client = self._make_client({"latest_fcf": -100e6, "fcf_list": [-100e6]})
        report = generate_dcf_report("1234.T", client)
        assert "FCFデータが取得できない" in report

    def test_report_warns_when_no_shares(self):
        client = self._make_client({"shares_outstanding": None})
        report = generate_dcf_report("1234.T", client)
        assert "発行済み株式数" in report

    def test_report_ends_with_separator(self):
        client = self._make_client()
        report = generate_dcf_report("1234.T", client)
        assert report.strip().endswith("---")

    def test_sensitivity_table_has_wacc_headers(self):
        client = self._make_client()
        report = generate_dcf_report("1234.T", client)
        assert "WACC" in report
