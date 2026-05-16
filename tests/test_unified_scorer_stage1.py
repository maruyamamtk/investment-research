"""
テスト: unified_scorer.py 段階1（速報スコア）
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.screener.unified_scorer import (
    MISSING_SCORE,
    WEIGHTS,
    calculate_stage1_scores,
    filter_stage1_candidates,
    score_equity_ratio,
    score_market_cap,
    score_operating_margin,
    score_payout_ratio,
    score_peg_ratio,
    _calc_equity_ratio,
    _calc_peg,
)


# ============================================================
# 重み検証
# ============================================================

def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


# ============================================================
# score_operating_margin
# ============================================================

class TestScoreOperatingMargin:
    def test_zero_margin_returns_zero(self):
        assert score_operating_margin(0.0) == 0.0

    def test_25_percent_returns_ten(self):
        assert score_operating_margin(0.25) == 10.0

    def test_negative_margin_clamped_to_zero(self):
        assert score_operating_margin(-0.10) == 0.0

    def test_excess_margin_clamped_to_ten(self):
        assert score_operating_margin(0.50) == 10.0

    def test_midpoint_returns_five(self):
        assert score_operating_margin(0.125) == pytest.approx(5.0, abs=0.01)

    def test_none_returns_missing(self):
        assert score_operating_margin(None) == MISSING_SCORE

    def test_nan_returns_missing(self):
        assert score_operating_margin(float("nan")) == MISSING_SCORE


# ============================================================
# score_equity_ratio
# ============================================================

class TestScoreEquityRatio:
    def test_10_percent_returns_zero(self):
        assert score_equity_ratio(0.10) == 0.0

    def test_50_percent_returns_ten(self):
        assert score_equity_ratio(0.50) == 10.0

    def test_below_10_clamped(self):
        assert score_equity_ratio(0.05) == 0.0

    def test_above_50_clamped(self):
        assert score_equity_ratio(0.80) == 10.0

    def test_none_returns_missing(self):
        assert score_equity_ratio(None) == MISSING_SCORE


# ============================================================
# score_peg_ratio
# ============================================================

class TestScorePegRatio:
    def test_0_5_returns_ten(self):
        assert score_peg_ratio(0.5) == 10.0

    def test_5_0_returns_zero(self):
        assert score_peg_ratio(5.0) == 0.0

    def test_below_0_5_clamped_to_ten(self):
        assert score_peg_ratio(0.1) == 10.0

    def test_above_5_clamped_to_zero(self):
        assert score_peg_ratio(10.0) == 0.0

    def test_midpoint_2_75_returns_five(self):
        assert score_peg_ratio(2.75) == pytest.approx(5.0, abs=0.01)

    def test_none_returns_missing(self):
        assert score_peg_ratio(None) == MISSING_SCORE


# ============================================================
# score_market_cap
# ============================================================

class TestScoreMarketCap:
    def test_100_oku_returns_zero(self):
        assert score_market_cap(10_000_000_000) == 0.0

    def test_1_cho_returns_ten(self):
        assert score_market_cap(1_000_000_000_000) == 10.0

    def test_below_100_oku_clamped(self):
        assert score_market_cap(1_000_000_000) == 0.0

    def test_above_1_cho_clamped(self):
        assert score_market_cap(100_000_000_000_000) == 10.0

    def test_zero_returns_missing(self):
        assert score_market_cap(0) == MISSING_SCORE

    def test_none_returns_missing(self):
        assert score_market_cap(None) == MISSING_SCORE

    def test_log_midpoint(self):
        # log10(100億)=10, log10(1兆)=12 の中間 = log10(sqrt(100億*1兆)) = 11
        mid = 10 ** 11  # 1000億
        score = score_market_cap(mid)
        assert score == pytest.approx(5.0, abs=0.01)


# ============================================================
# score_payout_ratio
# ============================================================

class TestScorePayoutRatio:
    def test_zero_returns_ten(self):
        assert score_payout_ratio(0.0) == 10.0

    def test_70_percent_returns_zero(self):
        assert score_payout_ratio(0.70) == 0.0

    def test_above_70_clamped(self):
        assert score_payout_ratio(1.00) == 0.0

    def test_none_returns_missing(self):
        assert score_payout_ratio(None) == MISSING_SCORE


# ============================================================
# _calc_equity_ratio
# ============================================================

class TestCalcEquityRatio:
    def test_normal_case(self):
        info = {"total_equity": 400, "total_assets": 1000}
        assert _calc_equity_ratio(info) == pytest.approx(0.40)

    def test_missing_equity(self):
        assert _calc_equity_ratio({"total_assets": 1000}) is None

    def test_zero_assets(self):
        assert _calc_equity_ratio({"total_equity": 100, "total_assets": 0}) is None


# ============================================================
# _calc_peg
# ============================================================

class TestCalcPeg:
    def test_normal_case(self):
        info = {"pe_ratio": 20.0, "revenue_growth": 0.20}
        # PEG = 20 / (0.20 * 100) = 1.0
        assert _calc_peg(info) == pytest.approx(1.0)

    def test_zero_revenue_growth(self):
        assert _calc_peg({"pe_ratio": 20.0, "revenue_growth": 0.0}) is None

    def test_negative_revenue_growth(self):
        assert _calc_peg({"pe_ratio": 20.0, "revenue_growth": -0.10}) is None

    def test_missing_pe(self):
        assert _calc_peg({"revenue_growth": 0.15}) is None

    def test_missing_growth(self):
        assert _calc_peg({"pe_ratio": 20.0}) is None


# ============================================================
# calculate_stage1_scores
# ============================================================

def _make_info(ticker: str, **kwargs) -> dict:
    """テスト用の最小 basic_info を生成する。"""
    defaults = {
        "name": ticker,
        "operating_margins": 0.15,
        "total_equity": 500,
        "total_assets": 1000,
        "pe_ratio": 15.0,
        "revenue_growth": 0.10,
        "market_cap": 100_000_000_000,   # 1000億
        "payout_ratio": 0.30,
    }
    defaults.update(kwargs)
    return {"ticker": ticker, **defaults}


class TestCalculateStage1Scores:
    def test_returns_dataframe(self):
        infos = [_make_info("1234.T"), _make_info("5678.T")]
        df = calculate_stage1_scores(infos)
        assert len(df) == 2
        assert "stage1_raw" in df.columns

    def test_sorted_descending(self):
        good = _make_info("GOOD.T", operating_margins=0.25, market_cap=1_000_000_000_000)
        bad  = _make_info("BAD.T",  operating_margins=0.0,  market_cap=10_000_000_000)
        df = calculate_stage1_scores([bad, good])
        assert df.iloc[0]["ticker"] == "GOOD.T"

    def test_all_missing_data(self):
        info = {
            "ticker": "NULL.T",
            "name": "NULL",
            "operating_margins": None,
            "total_equity": None,
            "total_assets": None,
            "pe_ratio": None,
            "revenue_growth": None,
            "market_cap": None,
            "payout_ratio": None,
        }
        df = calculate_stage1_scores([info])
        assert len(df) == 1
        # 全欠損時は各次元が MISSING_SCORE(5) なので stage1_raw > 0
        assert df.iloc[0]["stage1_raw"] > 0

    def test_score_columns_present(self):
        df = calculate_stage1_scores([_make_info("A.T")])
        for col in ("s1_operating_margin", "s1_equity_ratio", "s1_peg", "s1_market_cap", "s1_payout_ratio"):
            assert col in df.columns

    def test_empty_input(self):
        df = calculate_stage1_scores([])
        assert df.empty


# ============================================================
# filter_stage1_candidates
# ============================================================

class TestFilterStage1Candidates:
    def _make_df(self, n: int) -> "pd.DataFrame":
        import pandas as pd
        return pd.DataFrame([{"ticker": f"{i}.T", "stage1_raw": float(i)} for i in range(n)])

    def test_returns_at_most_top_n_max(self):
        df = self._make_df(1000)
        result = filter_stage1_candidates(df, top_n_min=200, top_n_max=400)
        assert len(result) <= 400

    def test_returns_at_least_top_n_min_when_possible(self):
        df = self._make_df(1000)
        result = filter_stage1_candidates(df, top_n_min=200, top_n_max=400)
        assert len(result) >= 200

    def test_small_input_returns_all(self):
        df = self._make_df(30)
        result = filter_stage1_candidates(df, top_n_min=200, top_n_max=400)
        assert len(result) == 30
