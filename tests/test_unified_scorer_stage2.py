"""
テスト: unified_scorer.py 段階2（精緻スコア）
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
from src.screener.unified_scorer import (
    MISSING_SCORE,
    WEIGHTS,
    # 段階2スコア関数
    score_eps_annual_growth,
    score_eps_quarterly_growth,
    score_revenue_annual_growth,
    score_revenue_quarterly_growth,
    score_roe,
    score_cf_quality,
    score_fcf_years,
    score_net_debt_ebitda,
    # 段階2ヘルパー
    _calc_eps_annual_growth,
    _calc_eps_quarterly_growth,
    _calc_revenue_annual_growth,
    _calc_revenue_quarterly_growth,
    # 段階2メイン
    calculate_stage2_scores,
    select_final_watchlist,
)


# ============================================================
# score_eps_annual_growth
# ============================================================

class TestScoreEpsAnnualGrowth:
    def test_zero_returns_zero(self):
        assert score_eps_annual_growth(0.0) == 0.0

    def test_30_percent_returns_ten(self):
        assert score_eps_annual_growth(0.30) == 10.0

    def test_negative_clamped_to_zero(self):
        assert score_eps_annual_growth(-0.10) == 0.0

    def test_above_30_clamped_to_ten(self):
        assert score_eps_annual_growth(0.60) == 10.0

    def test_midpoint_15_percent_returns_five(self):
        assert score_eps_annual_growth(0.15) == pytest.approx(5.0, abs=0.01)

    def test_none_returns_missing(self):
        assert score_eps_annual_growth(None) == MISSING_SCORE

    def test_nan_returns_missing(self):
        assert score_eps_annual_growth(float("nan")) == MISSING_SCORE


# ============================================================
# score_eps_quarterly_growth
# ============================================================

class TestScoreEpsQuarterlyGrowth:
    def test_zero_returns_zero(self):
        assert score_eps_quarterly_growth(0.0) == 0.0

    def test_negative_returns_zero(self):
        assert score_eps_quarterly_growth(-0.10) == 0.0

    def test_25_percent_without_monotone_returns_nine(self):
        assert score_eps_quarterly_growth(0.25) == pytest.approx(9.0, abs=0.01)

    def test_25_percent_with_monotone_returns_ten(self):
        assert score_eps_quarterly_growth(0.25, is_monotone=True) == 10.0

    def test_above_25_with_monotone_capped_at_ten(self):
        assert score_eps_quarterly_growth(0.50, is_monotone=True) == 10.0

    def test_none_returns_missing(self):
        assert score_eps_quarterly_growth(None) == MISSING_SCORE

    def test_nan_returns_missing(self):
        assert score_eps_quarterly_growth(float("nan")) == MISSING_SCORE

    def test_12_5_percent_is_half_of_nine(self):
        score = score_eps_quarterly_growth(0.125)
        assert score == pytest.approx(4.5, abs=0.01)


# ============================================================
# score_revenue_annual_growth
# ============================================================

class TestScoreRevenueAnnualGrowth:
    def test_zero_returns_zero(self):
        assert score_revenue_annual_growth(0.0) == 0.0

    def test_20_percent_returns_ten(self):
        assert score_revenue_annual_growth(0.20) == 10.0

    def test_negative_clamped_to_zero(self):
        assert score_revenue_annual_growth(-0.05) == 0.0

    def test_above_20_clamped_to_ten(self):
        assert score_revenue_annual_growth(0.40) == 10.0

    def test_midpoint_10_percent_returns_five(self):
        assert score_revenue_annual_growth(0.10) == pytest.approx(5.0, abs=0.01)

    def test_none_returns_missing(self):
        assert score_revenue_annual_growth(None) == MISSING_SCORE


# ============================================================
# score_revenue_quarterly_growth
# ============================================================

class TestScoreRevenueQuarterlyGrowth:
    def test_zero_returns_zero(self):
        assert score_revenue_quarterly_growth(0.0) == 0.0

    def test_25_percent_returns_ten(self):
        assert score_revenue_quarterly_growth(0.25) == 10.0

    def test_negative_clamped_to_zero(self):
        assert score_revenue_quarterly_growth(-0.10) == 0.0

    def test_above_25_clamped_to_ten(self):
        assert score_revenue_quarterly_growth(0.50) == 10.0

    def test_none_returns_missing(self):
        assert score_revenue_quarterly_growth(None) == MISSING_SCORE


# ============================================================
# score_roe
# ============================================================

class TestScoreRoe:
    def test_zero_returns_zero(self):
        assert score_roe(0.0) == 0.0

    def test_30_percent_returns_ten(self):
        assert score_roe(0.30) == 10.0

    def test_negative_clamped_to_zero(self):
        assert score_roe(-0.05) == 0.0

    def test_above_30_clamped_to_ten(self):
        assert score_roe(0.50) == 10.0

    def test_midpoint_15_percent_returns_five(self):
        assert score_roe(0.15) == pytest.approx(5.0, abs=0.01)

    def test_none_returns_missing(self):
        assert score_roe(None) == MISSING_SCORE


# ============================================================
# score_cf_quality
# ============================================================

class TestScoreCfQuality:
    def test_zero_returns_zero(self):
        assert score_cf_quality(0.0) == 0.0

    def test_2_0_returns_ten(self):
        assert score_cf_quality(2.0) == 10.0

    def test_negative_clamped_to_zero(self):
        assert score_cf_quality(-1.0) == 0.0

    def test_above_2_clamped_to_ten(self):
        assert score_cf_quality(3.0) == 10.0

    def test_midpoint_1_0_returns_five(self):
        assert score_cf_quality(1.0) == pytest.approx(5.0, abs=0.01)

    def test_none_returns_missing(self):
        assert score_cf_quality(None) == MISSING_SCORE


# ============================================================
# score_fcf_years
# ============================================================

class TestScoreFcfYears:
    def test_zero_returns_zero(self):
        assert score_fcf_years(0) == 0.0

    def test_three_returns_ten(self):
        assert score_fcf_years(3) == 10.0

    def test_one_returns_one_third_of_ten(self):
        assert score_fcf_years(1) == pytest.approx(10.0 / 3, abs=0.01)

    def test_two_returns_two_thirds_of_ten(self):
        assert score_fcf_years(2) == pytest.approx(20.0 / 3, abs=0.01)

    def test_above_3_clamped_to_ten(self):
        assert score_fcf_years(5) == 10.0

    def test_none_returns_missing(self):
        assert score_fcf_years(None) == MISSING_SCORE


# ============================================================
# score_net_debt_ebitda
# ============================================================

class TestScoreNetDebtEbitda:
    def test_zero_returns_ten(self):
        assert score_net_debt_ebitda(0.0) == 10.0

    def test_five_returns_zero(self):
        assert score_net_debt_ebitda(5.0) == 0.0

    def test_negative_clamped_to_ten(self):
        assert score_net_debt_ebitda(-2.0) == 10.0

    def test_above_five_clamped_to_zero(self):
        assert score_net_debt_ebitda(10.0) == 0.0

    def test_midpoint_2_5_returns_five(self):
        assert score_net_debt_ebitda(2.5) == pytest.approx(5.0, abs=0.01)

    def test_none_returns_missing(self):
        assert score_net_debt_ebitda(None) == MISSING_SCORE

    def test_nan_returns_missing(self):
        assert score_net_debt_ebitda(float("nan")) == MISSING_SCORE

    def test_large_negative_ebitda_returns_ten(self):
        # EBITDAが負の場合に net_debt/EBITDA が極端な負値になっても 10.0 を返す
        assert score_net_debt_ebitda(-999.0) == 10.0


# ============================================================
# _calc_eps_annual_growth
# ============================================================

def _make_annual(eps_list: list) -> list[dict]:
    return [{"date": f"2024-0{i}-31", "eps": e} for i, e in enumerate(eps_list, 1)]


class TestCalcEpsAnnualGrowth:
    def test_single_period_returns_none(self):
        assert _calc_eps_annual_growth(_make_annual([100])) is None

    def test_two_periods_one_growth(self):
        # (120 - 100) / 100 = 0.20
        result = _calc_eps_annual_growth(_make_annual([120, 100]))
        assert result == pytest.approx(0.20)

    def test_four_periods_averages_three_growths(self):
        # 成長率: 50→100=1.0, 100→150=0.5, 150→200=0.333...
        # 平均 = (1.0 + 0.5 + 0.333) / 3 ≈ 0.611
        annual = _make_annual([200, 150, 100, 50])
        result = _calc_eps_annual_growth(annual)
        expected = ((200 - 150) / 150 + (150 - 100) / 100 + (100 - 50) / 50) / 3
        assert result == pytest.approx(expected, abs=0.001)

    def test_zero_previous_eps_skipped(self):
        annual = _make_annual([100, 0, 50])
        result = _calc_eps_annual_growth(annual)
        # 0→100はゼロ除算スキップ, 50→0は0除算スキップ
        # valid: eps=100, 0, 50 → [100, 0, 50]
        # i=0: curr=100, prev=0 → skip
        # i=1: curr=0, prev=50 → (0-50)/50 = -1.0
        assert result == pytest.approx(-1.0)

    def test_empty_returns_none(self):
        assert _calc_eps_annual_growth([]) is None

    def test_no_eps_data_returns_none(self):
        annual = [{"date": "2024-03-31", "eps": None}]
        assert _calc_eps_annual_growth(annual) is None


# ============================================================
# _calc_eps_quarterly_growth
# ============================================================

def _make_quarterly(data: list[tuple]) -> list[dict]:
    """(eps, period_type) のリストから四半期データを生成"""
    return [{"date": f"2024-0{i}-30", "eps": e, "period_type": pt} for i, (e, pt) in enumerate(data, 1)]


class TestCalcEpsQuarterlyGrowth:
    def test_less_than_two_periods_returns_none(self):
        growth, monotone = _calc_eps_quarterly_growth(_make_quarterly([(100, "3Q")]))
        assert growth is None
        assert monotone is False

    def test_yoy_growth_calculated_correctly(self):
        # 最新3Q=150, 前年3Q=100 → growth=0.50
        quarterly = _make_quarterly([(150, "3Q"), (120, "2Q"), (100, "1Q"), (100, "3Q")])
        growth, _ = _calc_eps_quarterly_growth(quarterly)
        assert growth == pytest.approx(0.50)

    def test_no_matching_period_type_returns_none(self):
        # 最新が3Qだが、過去データに3Qなし
        quarterly = _make_quarterly([(150, "3Q"), (100, "2Q"), (80, "1Q")])
        growth, _ = _calc_eps_quarterly_growth(quarterly)
        assert growth is None

    def test_monotone_true_when_growth_accelerates(self):
        # 3Q: 150→100=50%, 2Q: 120→80=50%, 1Q: 100→60=67% → 最新が最高なら単調
        # growths[0]=最新3Q成長, growths[1]=2Q成長, growths[2]=1Q成長
        # is_monotone = growths[0] >= growths[1] >= growths[2]
        quarterly = _make_quarterly([
            (180, "3Q"),  # 最新
            (160, "2Q"),
            (140, "1Q"),
            (100, "3Q"),  # 1年前
            (80, "2Q"),
            (60, "1Q"),
        ])
        _, is_monotone = _calc_eps_quarterly_growth(quarterly)
        # growths: 3Q=(180-100)/100=0.8, 2Q=(160-80)/80=1.0, 1Q=(140-60)/60=1.33
        # [0]=0.8, [1]=1.0 → 0.8 >= 1.0 is False → not monotone
        assert is_monotone is False

    def test_monotone_true_when_newest_has_highest_growth(self):
        quarterly = _make_quarterly([
            (200, "3Q"),  # 最新
            (140, "2Q"),
            (110, "1Q"),
            (100, "3Q"),  # 1年前
            (100, "2Q"),
            (100, "1Q"),
        ])
        _, is_monotone = _calc_eps_quarterly_growth(quarterly)
        # growths: 3Q=1.0, 2Q=0.4, 1Q=0.1 → [0]=1.0 >= [1]=0.4 >= [2]=0.1 → True
        assert is_monotone is True


# ============================================================
# _calc_revenue_annual_growth
# ============================================================

def _make_annual_sales(sales_list: list) -> list[dict]:
    return [{"date": f"2024-0{i}-31", "net_sales": s} for i, s in enumerate(sales_list, 1)]


class TestCalcRevenueAnnualGrowth:
    def test_two_periods_one_growth(self):
        # (1200 - 1000) / 1000 = 0.20
        result = _calc_revenue_annual_growth(_make_annual_sales([1200, 1000]))
        assert result == pytest.approx(0.20)

    def test_three_periods_averages_two_growths(self):
        # (1200-1000)/1000=0.20, (1000-800)/800=0.25 → avg=0.225
        result = _calc_revenue_annual_growth(_make_annual_sales([1200, 1000, 800]))
        assert result == pytest.approx(0.225, abs=0.001)

    def test_single_period_returns_none(self):
        assert _calc_revenue_annual_growth(_make_annual_sales([1000])) is None

    def test_empty_returns_none(self):
        assert _calc_revenue_annual_growth([]) is None

    def test_zero_sales_filtered_out(self):
        annual = [{"date": "2024-03-31", "net_sales": 1000}, {"date": "2023-03-31", "net_sales": 0}]
        assert _calc_revenue_annual_growth(annual) is None


# ============================================================
# _calc_revenue_quarterly_growth
# ============================================================

class TestCalcRevenueQuarterlyGrowth:
    def test_yoy_growth_calculated_correctly(self):
        quarterly = _make_quarterly([(1500, "3Q"), (1200, "2Q"), (1000, "3Q")])
        # 最新3Q=1500, 前年3Q=1000 → (1500-1000)/1000 = 0.50
        result = _calc_revenue_quarterly_growth(
            [{"date": "2024-03", "net_sales": 1500, "period_type": "3Q"},
             {"date": "2024-02", "net_sales": 1200, "period_type": "2Q"},
             {"date": "2023-03", "net_sales": 1000, "period_type": "3Q"}]
        )
        assert result == pytest.approx(0.50)

    def test_no_matching_period_returns_none(self):
        result = _calc_revenue_quarterly_growth(
            [{"date": "2024-03", "net_sales": 1500, "period_type": "3Q"},
             {"date": "2024-02", "net_sales": 1200, "period_type": "2Q"}]
        )
        assert result is None

    def test_empty_returns_none(self):
        assert _calc_revenue_quarterly_growth([]) is None


# ============================================================
# calculate_stage2_scores
# ============================================================

def _make_stage1_row(ticker: str, stage1_raw: float = 1.0) -> dict:
    return {
        "ticker": ticker,
        "name": ticker,
        "stage1_raw": stage1_raw,
        "s1_operating_margin": 5.0,
        "s1_equity_ratio": 5.0,
        "s1_peg": 5.0,
        "s1_market_cap": 5.0,
        "s1_payout_ratio": 5.0,
    }


def _make_eps_series(
    annual_eps: list[float] = None,
    annual_sales: list[float] = None,
    quarterly_data: list[tuple] = None,
    roe: float = None,
) -> dict:
    annual = []
    n = max(len(annual_eps or []), len(annual_sales or []))
    for i in range(n):
        eps = (annual_eps or [None] * n)[i]
        sales = (annual_sales or [None] * n)[i]
        annual.append({
            "date": f"202{4-i}-03-31",
            "eps": eps,
            "net_sales": sales,
            "roe": roe if i == 0 else None,
        })
    quarterly = []
    for i, (eps, pt) in enumerate(quarterly_data or []):
        quarterly.append({"date": f"2024-0{i+1}-30", "eps": eps, "net_sales": None, "period_type": pt})
    return {"annual": annual, "quarterly": quarterly}


class TestCalculateStage2Scores:
    def _make_stage1_df(self, tickers: list[str]) -> pd.DataFrame:
        return pd.DataFrame([_make_stage1_row(t) for t in tickers])

    def test_returns_dataframe_with_total_score(self):
        df = self._make_stage1_df(["1234.T"])
        eps_map = {"1234.T": _make_eps_series([120, 100, 80], [1200, 1000, 800])}
        fins_map = {"1234.T": {"cf_quality": 1.5, "fcf_positive_years": 2, "net_debt_ebitda": 1.0}}
        result = calculate_stage2_scores(df, eps_map, fins_map)
        assert len(result) == 1
        assert "total_score" in result.columns
        assert "stage2_raw" in result.columns

    def test_total_score_is_stage1_plus_stage2(self):
        df = self._make_stage1_df(["1234.T"])
        eps_map = {"1234.T": {"annual": [], "quarterly": []}}
        fins_map = {"1234.T": {}}
        result = calculate_stage2_scores(df, eps_map, fins_map)
        row = result.iloc[0]
        assert row["total_score"] == pytest.approx(row["stage1_raw"] + row["stage2_raw"], abs=1e-4)

    def test_sorted_by_total_score_descending(self):
        # 良い銘柄（高成長）と悪い銘柄（低成長）
        df = self._make_stage1_df(["GOOD.T", "BAD.T"])
        eps_map = {
            "GOOD.T": _make_eps_series([130, 100, 77], [1300, 1000, 800], roe=0.25),
            "BAD.T": _make_eps_series([101, 100, 99], [1010, 1000, 990], roe=0.05),
        }
        fins_map = {
            "GOOD.T": {"cf_quality": 2.0, "fcf_positive_years": 3, "net_debt_ebitda": 0.5},
            "BAD.T": {"cf_quality": 0.5, "fcf_positive_years": 1, "net_debt_ebitda": 4.0},
        }
        result = calculate_stage2_scores(df, eps_map, fins_map)
        assert result.iloc[0]["ticker"] == "GOOD.T"

    def test_missing_data_uses_missing_score(self):
        df = self._make_stage1_df(["NULL.T"])
        eps_map = {"NULL.T": {"annual": [], "quarterly": []}}
        fins_map = {"NULL.T": {}}
        result = calculate_stage2_scores(df, eps_map, fins_map)
        assert len(result) == 1
        # 全欠損でも MISSING_SCORE が使われるためスコアは正の値
        assert result.iloc[0]["total_score"] > 0

    def test_roe_fallback_to_yfinance(self):
        """J-Quantsにroеデータがない場合、yfinanceのROEを使用する"""
        df = self._make_stage1_df(["1234.T"])
        eps_map = {"1234.T": {"annual": [], "quarterly": []}}
        fins_map = {"1234.T": {"roe": 0.25, "cf_quality": None, "fcf_positive_years": None, "net_debt_ebitda": None}}
        result = calculate_stage2_scores(df, eps_map, fins_map)
        assert result.iloc[0]["roe"] == pytest.approx(0.25)

    def test_all_score_columns_present(self):
        df = self._make_stage1_df(["1234.T"])
        eps_map = {"1234.T": {"annual": [], "quarterly": []}}
        fins_map = {"1234.T": {}}
        result = calculate_stage2_scores(df, eps_map, fins_map)
        for col in (
            "s2_eps_annual", "s2_eps_quarterly",
            "s2_revenue_annual", "s2_revenue_quarterly",
            "s2_roe", "s2_cf_quality", "s2_fcf_years", "s2_net_debt_ebitda",
        ):
            assert col in result.columns, f"{col} がDataFrameに存在しません"

    def test_empty_stage1_df_returns_empty(self):
        result = calculate_stage2_scores(pd.DataFrame(), {}, {})
        assert result.empty

    def test_ticker_not_in_maps_uses_defaults(self):
        """eps_series_map/detailed_fins_mapにtickerが存在しない場合もクラッシュしない"""
        df = self._make_stage1_df(["UNKNOWN.T"])
        result = calculate_stage2_scores(df, {}, {})
        assert len(result) == 1
        assert "total_score" in result.columns


# ============================================================
# select_final_watchlist
# ============================================================

class TestSelectFinalWatchlist:
    def _make_df(self, n: int) -> pd.DataFrame:
        return pd.DataFrame([{"ticker": f"{i}.T", "total_score": float(n - i)} for i in range(n)])

    def test_returns_top_n(self):
        df = self._make_df(50)
        result = select_final_watchlist(df, top_n=20)
        assert len(result) == 20

    def test_returns_all_when_less_than_top_n(self):
        df = self._make_df(10)
        result = select_final_watchlist(df, top_n=20)
        assert len(result) == 10

    def test_preserves_order(self):
        df = self._make_df(30)
        result = select_final_watchlist(df, top_n=5)
        assert result.iloc[0]["ticker"] == "0.T"
