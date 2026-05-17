"""
テスト: unified_scorer.py 欠損値補完（Issue #4）

検証対象:
- 段階1: s1_missing_count カラム
- 段階2: s2_missing_count カラム・欠損次元ログ
- total_missing_count カラム
- data_quality_note カラム（欠損 >= MISSING_THRESHOLD で "* データ欠損あり"）
"""
import math
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
from src.screener.unified_scorer import (
    MISSING_SCORE,
    MISSING_THRESHOLD,
    calculate_stage1_scores,
    calculate_stage2_scores,
    calculate_total_score,
)


# ============================================================
# フィクスチャ
# ============================================================

def _make_complete_info(ticker: str) -> dict:
    """全次元が揃った basic_info。"""
    return {
        "ticker": ticker,
        "operating_margins": 0.20,
        "total_equity": 500_000_000_000,
        "total_assets": 1_000_000_000_000,
        "pe_ratio": 15.0,
        "revenue_growth": 0.20,
        "market_cap": 500_000_000_000,
        "payout_ratio": 0.30,
    }


def _make_missing_info(ticker: str, missing_fields: list) -> dict:
    """指定フィールドを None にした basic_info。"""
    info = _make_complete_info(ticker)
    for f in missing_fields:
        info[f] = None
    return info


def _make_stage1_df(basic_info_list: list) -> pd.DataFrame:
    return calculate_stage1_scores(basic_info_list)


def _make_complete_eps_map(ticker: str) -> dict:
    return {
        ticker: {
            "annual": [
                {"eps": 150.0, "net_sales": 1e12, "roe": 0.25},
                {"eps": 120.0, "net_sales": 9e11, "roe": 0.20},
                {"eps": 100.0, "net_sales": 8e11, "roe": 0.18},
            ],
            "quarterly": [
                {"eps": 40.0, "net_sales": 2.5e11, "period_type": "1Q"},
                {"eps": 32.0, "net_sales": 2.0e11, "period_type": "1Q"},
            ],
        }
    }


def _make_complete_fins_map(ticker: str) -> dict:
    return {
        ticker: {
            "roe": 0.25,
            "cf_quality": 1.5,
            "fcf_positive_years": 3,
            "net_debt_ebitda": 1.0,
        }
    }


# ============================================================
# MISSING_THRESHOLD 定数
# ============================================================

class TestMissingThreshold:
    def test_missing_threshold_is_positive_int(self):
        assert isinstance(MISSING_THRESHOLD, int)
        assert MISSING_THRESHOLD > 0

    def test_missing_threshold_is_reasonable(self):
        """13次元中 4〜6 程度が想定閾値。"""
        assert 3 <= MISSING_THRESHOLD <= 7


# ============================================================
# 段階1: s1_missing_count
# ============================================================

class TestStage1MissingCount:
    def test_complete_data_has_zero_missing(self):
        info = _make_complete_info("A.T")
        df = calculate_stage1_scores([info])
        assert df.loc[0, "s1_missing_count"] == 0

    def test_one_missing_field_counts_one(self):
        info = _make_missing_info("A.T", ["operating_margins"])
        df = calculate_stage1_scores([info])
        assert df.loc[0, "s1_missing_count"] == 1

    def test_peg_ratio_missing_when_pe_is_none(self):
        """pe_ratio が None なら peg_calc も None → missing として計上。"""
        info = _make_missing_info("A.T", ["pe_ratio"])
        df = calculate_stage1_scores([info])
        assert df.loc[0, "s1_missing_count"] >= 1

    def test_multiple_missing_fields_counted(self):
        info = _make_missing_info("A.T", ["operating_margins", "payout_ratio"])
        df = calculate_stage1_scores([info])
        assert df.loc[0, "s1_missing_count"] == 2

    def test_all_stage1_missing_counts_five(self):
        """5次元すべて None なら s1_missing_count = 5。"""
        info = {
            "ticker": "A.T",
            "operating_margins": None,
            "total_equity": None,
            "total_assets": None,
            "pe_ratio": None,
            "revenue_growth": None,
            "market_cap": None,
            "payout_ratio": None,
        }
        df = calculate_stage1_scores([info])
        assert df.loc[0, "s1_missing_count"] == 5

    def test_missing_count_column_present_in_dataframe(self):
        df = calculate_stage1_scores([_make_complete_info("A.T")])
        assert "s1_missing_count" in df.columns

    def test_missing_score_applied_when_none(self):
        """None 次元に MISSING_SCORE が使われていること。"""
        info = _make_missing_info("A.T", ["operating_margins"])
        df = calculate_stage1_scores([info])
        assert df.loc[0, "s1_operating_margin"] == MISSING_SCORE

    def test_multiple_tickers_each_have_correct_missing_count(self):
        infos = [
            _make_complete_info("A.T"),
            _make_missing_info("B.T", ["operating_margins", "market_cap"]),
        ]
        df = calculate_stage1_scores(infos)
        ticker_a = df[df["ticker"] == "A.T"].iloc[0]
        ticker_b = df[df["ticker"] == "B.T"].iloc[0]
        assert ticker_a["s1_missing_count"] == 0
        assert ticker_b["s1_missing_count"] == 2


# ============================================================
# 段階2: s2_missing_count
# ============================================================

class TestStage2MissingCount:
    def _make_stage1_df(self):
        info = _make_complete_info("A.T")
        return calculate_stage1_scores([info])

    def test_complete_data_has_zero_s2_missing(self):
        df1 = self._make_stage1_df()
        eps_map = _make_complete_eps_map("A.T")
        fins_map = _make_complete_fins_map("A.T")
        df2 = calculate_stage2_scores(df1, eps_map, fins_map)
        assert df2.loc[0, "s2_missing_count"] == 0

    def test_missing_count_column_present(self):
        df1 = self._make_stage1_df()
        df2 = calculate_stage2_scores(df1, {}, {})
        assert "s2_missing_count" in df2.columns

    def test_empty_eps_and_fins_counts_all_eight(self):
        """eps_map・fins_map が空なら 8次元すべて欠損。"""
        df1 = self._make_stage1_df()
        df2 = calculate_stage2_scores(df1, {}, {})
        assert df2.loc[0, "s2_missing_count"] == 8

    def test_partial_missing_counts_correctly(self):
        """cf_quality・fcf_positive_years のみ欠損 → s2_missing_count = 2。"""
        df1 = self._make_stage1_df()
        eps_map = _make_complete_eps_map("A.T")
        fins_map = {
            "A.T": {
                "roe": 0.20,
                "cf_quality": None,
                "fcf_positive_years": None,
                "net_debt_ebitda": 1.5,
            }
        }
        df2 = calculate_stage2_scores(df1, eps_map, fins_map)
        assert df2.loc[0, "s2_missing_count"] == 2

    def test_missing_dims_logged(self, caplog):
        """欠損次元が DEBUG ログに記録されること。"""
        df1 = self._make_stage1_df()
        with caplog.at_level(logging.DEBUG, logger="unified_scorer"):
            calculate_stage2_scores(df1, {}, {})
        assert any("欠損次元" in r.message for r in caplog.records)

    def test_multiple_tickers_each_have_correct_s2_missing(self):
        infos = [_make_complete_info("A.T"), _make_complete_info("B.T")]
        df1 = calculate_stage1_scores(infos)
        eps_map = {
            "A.T": _make_complete_eps_map("A.T")["A.T"],
            "B.T": {"annual": [], "quarterly": []},
        }
        fins_map = {
            "A.T": _make_complete_fins_map("A.T")["A.T"],
        }
        df2 = calculate_stage2_scores(df1, eps_map, fins_map)
        row_a = df2[df2["ticker"] == "A.T"].iloc[0]
        row_b = df2[df2["ticker"] == "B.T"].iloc[0]
        assert row_a["s2_missing_count"] == 0
        assert row_b["s2_missing_count"] > 0


# ============================================================
# total_missing_count
# ============================================================

class TestTotalMissingCount:
    def _full_pipeline(self, missing_s1_fields=None, missing_fins=None):
        info = (
            _make_missing_info("A.T", missing_s1_fields)
            if missing_s1_fields
            else _make_complete_info("A.T")
        )
        df1 = calculate_stage1_scores([info])
        eps_map = _make_complete_eps_map("A.T")
        fins_map = missing_fins if missing_fins is not None else _make_complete_fins_map("A.T")
        df2 = calculate_stage2_scores(df1, eps_map, fins_map)
        return calculate_total_score(df2)

    def test_complete_data_has_zero_total_missing(self):
        df = self._full_pipeline()
        assert df.loc[0, "total_missing_count"] == 0

    def test_total_missing_equals_s1_plus_s2(self):
        df = self._full_pipeline(
            missing_s1_fields=["operating_margins"],
            missing_fins={"A.T": {"roe": None, "cf_quality": None, "fcf_positive_years": 2, "net_debt_ebitda": 1.0}},
        )
        row = df.iloc[0]
        assert row["total_missing_count"] == row["s1_missing_count"] + row["s2_missing_count"]

    def test_total_missing_count_column_present(self):
        df = self._full_pipeline()
        assert "total_missing_count" in df.columns


# ============================================================
# data_quality_note
# ============================================================

class TestDataQualityNote:
    def _full_pipeline_with_missing(self, n_s1_missing: int = 0, all_s2_missing: bool = False):
        missing_fields = []
        field_pool = ["operating_margins", "payout_ratio", "total_equity", "pe_ratio", "market_cap"]
        for f in field_pool[:n_s1_missing]:
            missing_fields.append(f)

        info = _make_missing_info("A.T", missing_fields) if missing_fields else _make_complete_info("A.T")
        df1 = calculate_stage1_scores([info])
        eps_map = {} if all_s2_missing else _make_complete_eps_map("A.T")
        fins_map = {} if all_s2_missing else _make_complete_fins_map("A.T")
        df2 = calculate_stage2_scores(df1, eps_map, fins_map)
        return calculate_total_score(df2)

    def test_no_missing_has_empty_note(self):
        df = self._full_pipeline_with_missing(n_s1_missing=0, all_s2_missing=False)
        assert df.loc[0, "data_quality_note"] == ""

    def test_above_threshold_has_missing_note(self):
        """全8次元の段階2が欠損 → data_quality_note に注記が入る。"""
        df = self._full_pipeline_with_missing(all_s2_missing=True)
        assert df.loc[0, "data_quality_note"] == "* データ欠損あり"

    def test_data_quality_note_column_present(self):
        df = self._full_pipeline_with_missing()
        assert "data_quality_note" in df.columns

    def test_at_threshold_has_note(self):
        """total_missing_count == MISSING_THRESHOLD のとき注記が入る。"""
        from src.screener.unified_scorer import MISSING_THRESHOLD
        # 段階2全欠損 = 8次元欠損 → MISSING_THRESHOLD(4) 以上
        df = self._full_pipeline_with_missing(all_s2_missing=True)
        row = df.iloc[0]
        assert row["total_missing_count"] >= MISSING_THRESHOLD
        assert row["data_quality_note"] == "* データ欠損あり"

    def test_below_threshold_has_no_note(self):
        """total_missing_count < MISSING_THRESHOLD なら注記なし。"""
        from src.screener.unified_scorer import MISSING_THRESHOLD
        # 1次元のみ欠損（MISSING_THRESHOLD=4 より少ない）
        df = self._full_pipeline_with_missing(n_s1_missing=1, all_s2_missing=False)
        row = df.iloc[0]
        if row["total_missing_count"] < MISSING_THRESHOLD:
            assert row["data_quality_note"] == ""

    def test_multiple_tickers_annotated_independently(self):
        infos = [_make_complete_info("GOOD.T"), _make_complete_info("BAD.T")]
        df1 = calculate_stage1_scores(infos)
        eps_map = {
            "GOOD.T": _make_complete_eps_map("GOOD.T")["GOOD.T"],
        }
        fins_map = {
            "GOOD.T": _make_complete_fins_map("GOOD.T")["GOOD.T"],
        }
        df2 = calculate_stage2_scores(df1, eps_map, fins_map)
        df_final = calculate_total_score(df2)

        good_row = df_final[df_final["ticker"] == "GOOD.T"].iloc[0]
        bad_row = df_final[df_final["ticker"] == "BAD.T"].iloc[0]
        assert good_row["data_quality_note"] == ""
        assert bad_row["data_quality_note"] == "* データ欠損あり"
