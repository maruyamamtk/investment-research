"""
テスト: earnings_reviewer.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.screener.earnings_reviewer import (
    determine_beat_miss,
    calculate_surprise_pct,
    detect_guidance_change,
    generate_earnings_report,
    _fmt_val,
    _fmt_jpy,
    _fmt_pct,
    BEAT_THRESHOLD,
    MISS_THRESHOLD,
)


# ================================================================
# determine_beat_miss
# ================================================================

class TestDetermineBeatMiss:
    def test_beat_when_actual_exceeds_estimate_by_more_than_threshold(self):
        assert determine_beat_miss(110.0, 100.0) == "Beat"

    def test_miss_when_actual_below_estimate_by_more_than_threshold(self):
        assert determine_beat_miss(89.0, 100.0) == "Miss"

    def test_meet_when_within_threshold(self):
        assert determine_beat_miss(100.5, 100.0) == "Meet"

    def test_meet_when_exact_match(self):
        assert determine_beat_miss(100.0, 100.0) == "Meet"

    def test_na_when_actual_none(self):
        assert determine_beat_miss(None, 100.0) == "N/A"

    def test_na_when_estimate_none(self):
        assert determine_beat_miss(100.0, None) == "N/A"

    def test_na_when_estimate_zero(self):
        assert determine_beat_miss(100.0, 0.0) == "N/A"

    def test_negative_eps_beat(self):
        # 予想 -10, 実績 -8 → 予想より良い → Beat
        assert determine_beat_miss(-8.0, -10.0) == "Beat"

    def test_negative_eps_miss(self):
        # 予想 -10, 実績 -12 → 予想より悪い → Miss
        assert determine_beat_miss(-12.0, -10.0) == "Miss"


# ================================================================
# calculate_surprise_pct
# ================================================================

class TestCalculateSurprisePct:
    def test_positive_surprise(self):
        pct = calculate_surprise_pct(110.0, 100.0)
        assert abs(pct - 10.0) < 1e-9

    def test_negative_surprise(self):
        pct = calculate_surprise_pct(90.0, 100.0)
        assert abs(pct - (-10.0)) < 1e-9

    def test_zero_surprise(self):
        pct = calculate_surprise_pct(100.0, 100.0)
        assert pct == 0.0

    def test_none_actual_returns_none(self):
        assert calculate_surprise_pct(None, 100.0) is None

    def test_none_estimate_returns_none(self):
        assert calculate_surprise_pct(100.0, None) is None

    def test_zero_estimate_returns_none(self):
        assert calculate_surprise_pct(100.0, 0.0) is None


# ================================================================
# detect_guidance_change
# ================================================================

class TestDetectGuidanceChange:
    def test_upward_revision(self):
        assert detect_guidance_change(120.0, 100.0) == "上方修正"

    def test_downward_revision(self):
        assert detect_guidance_change(80.0, 100.0) == "下方修正"

    def test_no_change_within_threshold(self):
        assert detect_guidance_change(100.5, 100.0) == "変化なし"

    def test_exact_same(self):
        assert detect_guidance_change(100.0, 100.0) == "変化なし"

    def test_none_current_returns_na(self):
        assert detect_guidance_change(None, 100.0) == "N/A"

    def test_none_prev_returns_na(self):
        assert detect_guidance_change(100.0, None) == "N/A"

    def test_zero_prev_returns_na(self):
        assert detect_guidance_change(100.0, 0.0) == "N/A"


# ================================================================
# _fmt_val
# ================================================================

class TestFmtVal:
    def test_jpy_format(self):
        assert _fmt_val(1234.56, "JPY") == "¥1,234.56"

    def test_usd_format(self):
        assert _fmt_val(1234.56, "USD") == "1,234.56"

    def test_none_returns_na(self):
        assert _fmt_val(None, "JPY") == "N/A"


# ================================================================
# _fmt_jpy
# ================================================================

class TestFmtJpy:
    def test_oku_format(self):
        result = _fmt_jpy(1e9)
        assert "億円" in result
        assert "10.0" in result

    def test_man_format(self):
        result = _fmt_jpy(5e6)
        assert "万円" in result

    def test_none_returns_na(self):
        assert _fmt_jpy(None) == "N/A"


# ================================================================
# _fmt_pct
# ================================================================

class TestFmtPct:
    def test_positive_shows_plus(self):
        assert _fmt_pct(5.5) == "+5.5%"

    def test_negative_no_extra_sign(self):
        assert _fmt_pct(-3.2) == "-3.2%"

    def test_zero_shows_plus(self):
        assert _fmt_pct(0.0) == "+0.0%"

    def test_none_returns_na(self):
        assert _fmt_pct(None) == "N/A"


# ================================================================
# generate_earnings_report（統合テスト）
# ================================================================

class FakeYFClient:
    """yfinance を使用せずに固定データを返す偽クライアント。"""

    def __init__(self, override=None):
        self._override = override or {}

    def get_earnings_data(self, ticker):
        import importlib
        import src.screener.earnings_reviewer as er
        # get_earnings_data を直接呼ばず、テストでモックデータを差し込む
        pass


def _make_fake_data(override=None):
    base = {
        "ticker": "1234.T",
        "name": "テスト株式会社",
        "sector": "テクノロジー",
        "industry": "ソフトウェア",
        "currency": "JPY",
        "current_price": 1500.0,
        "eps_history": [
            {"quarter": "2024-03-31", "actual": 55.0, "estimate": 50.0, "surprise_pct": 10.0},
            {"quarter": "2023-12-31", "actual": 48.0, "estimate": 50.0, "surprise_pct": -4.0},
            {"quarter": "2023-09-30", "actual": 52.0, "estimate": 51.0, "surprise_pct": 2.0},
            {"quarter": "2023-06-30", "actual": 45.0, "estimate": 44.0, "surprise_pct": 2.3},
        ],
        "revenue_history": [
            {"quarter": "2024-03-31", "actual": 50e9},
            {"quarter": "2023-12-31", "actual": 48e9},
            {"quarter": "2023-09-30", "actual": 47e9},
            {"quarter": "2023-06-30", "actual": 45e9},
            {"quarter": "2023-03-31", "actual": 43e9},
        ],
        "current_eps_estimate": 220.0,
        "trailing_eps": 200.0,
        "earnings_date": "2024-05-15",
    }
    if override:
        base.update(override)
    return base


class PatchedYFClient:
    """get_earnings_data をモックデータで差し替えるクライアント。"""

    def __init__(self, data):
        self._data = data

    # yf_client として渡されるが get_earnings_data は earnings_reviewer 内で直接呼ぶ
    # そのため earnings_reviewer.get_earnings_data をモンキーパッチする方式でテスト


import unittest.mock as mock


class TestGenerateEarningsReport:
    def _run_report(self, data_override=None, prev_estimates=None):
        data = _make_fake_data(data_override)
        ticker = data["ticker"]
        with mock.patch(
            "src.screener.earnings_reviewer.get_earnings_data",
            return_value=data,
        ):
            # yf_client は get_earnings_data をパッチするため None で OK
            report = generate_earnings_report(
                target_ticker=ticker,
                yf_client=None,
                prev_estimates=prev_estimates,
            )
        return report

    def test_report_contains_ticker(self):
        report = self._run_report()
        assert "1234.T" in report

    def test_report_contains_company_name(self):
        report = self._run_report()
        assert "テスト株式会社" in report

    def test_report_contains_eps_section(self):
        report = self._run_report()
        assert "EPS" in report

    def test_report_contains_revenue_section(self):
        report = self._run_report()
        assert "売上高" in report

    def test_report_contains_guidance_section(self):
        report = self._run_report()
        assert "ガイダンス" in report

    def test_beat_shows_green_icon(self):
        report = self._run_report()
        assert "🟢" in report
        assert "Beat" in report

    def test_miss_shows_red_icon(self):
        data = _make_fake_data()
        data["eps_history"][0]["actual"] = 40.0
        data["eps_history"][0]["estimate"] = 50.0
        data["eps_history"][0]["surprise_pct"] = -20.0
        report = self._run_report(data_override=data)
        assert "🔴" in report
        assert "Miss" in report

    def test_upward_guidance_detected(self):
        report = self._run_report(prev_estimates={"1234.T": 200.0})
        assert "上方修正" in report

    def test_downward_guidance_detected(self):
        data = _make_fake_data({"current_eps_estimate": 180.0})
        with mock.patch(
            "src.screener.earnings_reviewer.get_earnings_data",
            return_value=data,
        ):
            report = generate_earnings_report(
                "1234.T", None, prev_estimates={"1234.T": 220.0}
            )
        assert "下方修正" in report

    def test_no_eps_history_shows_warning(self):
        report = self._run_report(data_override={"eps_history": []})
        assert "EPSデータが取得できません" in report or "取得できません" in report

    def test_report_ends_with_separator(self):
        report = self._run_report()
        assert report.strip().endswith("---")

    def test_surprise_pct_formatted_in_report(self):
        report = self._run_report()
        assert "10.0%" in report or "+10.0%" in report
