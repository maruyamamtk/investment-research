"""
テスト: unified_scorer.py calculate_total_score()
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
from src.screener.unified_scorer import calculate_total_score, WEIGHTS


# ============================================================
# ヘルパー
# ============================================================

def _make_df(scores: list[float]) -> pd.DataFrame:
    """total_score 列を持つ最小限の DataFrame を生成する。"""
    return pd.DataFrame({
        "ticker": [f"100{i}.T" for i in range(len(scores))],
        "total_score": scores,
    })


# ============================================================
# 基本動作
# ============================================================

class TestCalculateTotalScoreBasic:
    def test_empty_dataframe_returns_empty(self):
        df = pd.DataFrame()
        result = calculate_total_score(df)
        assert result.empty

    def test_total_score_100_column_added(self):
        df = _make_df([5.0, 3.0, 7.0])
        result = calculate_total_score(df)
        assert "total_score_100" in result.columns

    def test_total_score_scaled_by_10(self):
        df = _make_df([5.0])
        result = calculate_total_score(df)
        assert result["total_score_100"].iloc[0] == pytest.approx(50.0)

    def test_max_score_10_becomes_100(self):
        df = _make_df([10.0])
        result = calculate_total_score(df)
        assert result["total_score_100"].iloc[0] == pytest.approx(100.0)

    def test_zero_score_becomes_0(self):
        df = _make_df([0.0])
        result = calculate_total_score(df)
        assert result["total_score_100"].iloc[0] == pytest.approx(0.0)

    def test_score_rounded_to_2_decimals(self):
        df = _make_df([3.333])
        result = calculate_total_score(df)
        assert result["total_score_100"].iloc[0] == pytest.approx(33.33)


# ============================================================
# ソート・上位選定
# ============================================================

class TestCalculateTotalScoreTopN:
    def test_sorted_descending(self):
        df = _make_df([3.0, 7.0, 5.0, 9.0, 1.0])
        result = calculate_total_score(df)
        scores = result["total_score_100"].tolist()
        assert scores == sorted(scores, reverse=True)

    def test_default_top_n_is_20(self):
        df = _make_df([float(i) for i in range(30)])
        result = calculate_total_score(df)
        assert len(result) == 20

    def test_custom_top_n(self):
        df = _make_df([float(i) for i in range(30)])
        result = calculate_total_score(df, top_n=5)
        assert len(result) == 5

    def test_top_n_larger_than_df_returns_all(self):
        df = _make_df([5.0, 3.0])
        result = calculate_total_score(df, top_n=20)
        assert len(result) == 2

    def test_top_ticker_has_highest_score(self):
        df = _make_df([3.0, 9.0, 6.0])
        result = calculate_total_score(df)
        assert result["total_score_100"].iloc[0] == pytest.approx(90.0)

    def test_index_reset(self):
        df = _make_df([3.0, 7.0, 5.0])
        result = calculate_total_score(df)
        assert result.index.tolist() == list(range(len(result)))


# ============================================================
# 実スコア域の検証（WEIGHTS を用いた統合計算）
# ============================================================

class TestCalculateTotalScoreWithRealWeights:
    def test_all_perfect_scores_yields_100(self):
        """全13次元が10点満点 → total_score=10.0 → total_score_100=100"""
        stage1_raw = sum(w * 10.0 for k, w in WEIGHTS.items()
                         if k in ("operating_margin", "equity_ratio", "peg_ratio", "market_cap", "payout_ratio"))
        stage2_raw = sum(w * 10.0 for k, w in WEIGHTS.items()
                         if k not in ("operating_margin", "equity_ratio", "peg_ratio", "market_cap", "payout_ratio"))
        total = round(stage1_raw + stage2_raw, 5)
        df = _make_df([total])
        result = calculate_total_score(df)
        assert result["total_score_100"].iloc[0] == pytest.approx(100.0, abs=0.01)

    def test_weights_sum_one_means_max_10(self):
        """WEIGHTS合計=1.0 かつ各次元最大10点 → total_score最大=10.0"""
        assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

    def test_missing_score_5_midpoint(self):
        """全次元欠損(=MISSING_SCORE=5.0)の場合 → 50点/100点"""
        total = sum(w * 5.0 for w in WEIGHTS.values())
        df = _make_df([total])
        result = calculate_total_score(df)
        assert result["total_score_100"].iloc[0] == pytest.approx(50.0, abs=0.01)

    def test_original_total_score_preserved(self):
        """元の total_score 列が変更されないこと"""
        df = _make_df([7.5])
        result = calculate_total_score(df)
        assert result["total_score"].iloc[0] == pytest.approx(7.5)
